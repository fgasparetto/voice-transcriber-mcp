"""
Voice Transcriber MCP Server

Transcribes voice messages from Google Chat (and local audio files) using Groq Whisper API.
Automatically detects audio attachments in Google Chat messages and provides transcription.
"""

import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-transcriber")

# --- Configuration ---

# Path to the Google Chat OAuth2 token
# Override with GCHAT_TOKEN_PATH env var if your token is in a different location
TOKEN_PATH = os.environ.get(
    "GCHAT_TOKEN_PATH",
    os.path.join(os.path.expanduser("~"), "tools/multi-chat-mcp-server/src/providers/google_chat/token.json"),
)

SCOPES = [
    "https://www.googleapis.com/auth/chat.messages.readonly",
    "https://www.googleapis.com/auth/chat.spaces.readonly",
]

# Groq API key (each user sets their own)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# --- Google Chat Auth ---


def get_google_credentials():
    """Get valid Google OAuth2 credentials from the shared token file."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    if not os.path.exists(TOKEN_PATH):
        raise FileNotFoundError(
            f"Google Chat token not found at {TOKEN_PATH}. "
            "Make sure the google-chat MCP server is authenticated."
        )

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    if not creds or not creds.valid:
        raise RuntimeError("Google credentials are invalid. Re-authenticate the google-chat MCP server.")

    return creds


# --- Google Chat API ---


def parse_gchat_url(url: str) -> Optional[str]:
    """Parse a Google Chat URL and extract the message resource name."""
    if url.startswith("spaces/"):
        return url

    patterns = [
        r"chat\.google\.com/dm/([^/]+)/([^/]+)/([^/?]+)",
        r"chat\.google\.com/room/([^/]+)/([^/]+)/([^/?]+)",
        r"chat\.google\.com/app/chat/([^/]+)/topic/([^/]+)/message/([^/?]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            space_id = match.group(1)
            message_id = match.group(3)
            return f"spaces/{space_id}/messages/{message_id}.{message_id}"

    return None


def fetch_message_with_attachments(message_name: str) -> dict:
    """Fetch a Google Chat message and its attachment info."""
    from googleapiclient.discovery import build

    creds = get_google_credentials()
    service = build("chat", "v1", credentials=creds)
    return service.spaces().messages().get(name=message_name).execute()


def download_attachment(message: dict, output_dir: str) -> Optional[str]:
    """Download the first audio attachment from a Google Chat message via media API."""
    import requests

    attachments = message.get("attachment", [])
    if not attachments:
        return None

    for attachment in attachments:
        content_type = attachment.get("contentType", "")
        if not content_type.startswith("audio/"):
            continue

        content_name = attachment.get("contentName", "voice_message.m4a")
        data_ref = attachment.get("attachmentDataRef", {})
        resource_name = data_ref.get("resourceName")

        if not resource_name:
            logger.warning(f"No attachmentDataRef.resourceName for: {content_name}")
            continue

        # Download via media API endpoint (the only method that works with Chat OAuth scopes)
        creds = get_google_credentials()
        headers = {"Authorization": f"Bearer {creds.token}"}
        url = f"https://chat.googleapis.com/v1/media/{resource_name}?alt=media"
        response = requests.get(url, headers=headers, allow_redirects=True)

        if response.status_code != 200:
            logger.error(f"Media download failed: HTTP {response.status_code} - {response.text[:200]}")
            continue

        output_path = os.path.join(output_dir, content_name)
        with open(output_path, "wb") as f:
            f.write(response.content)

        logger.info(f"Downloaded {content_name} ({len(response.content)} bytes)")
        return output_path

    return None


# --- Transcription via Groq API ---


def transcribe_audio(file_path: str, language: str = "it") -> str:
    """Transcribe an audio file using Groq Whisper API (whisper-large-v3).

    Free, fast, no local GPU needed.
    Get your API key at https://console.groq.com/keys
    """
    import requests

    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY not set. Get a free key at https://console.groq.com/keys "
            "and set it in your MCP server config env."
        )

    with open(file_path, "rb") as f:
        response = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": (Path(file_path).name, f, "audio/mpeg")},
            data={"model": "whisper-large-v3", "language": language, "response_format": "text"},
        )

    if response.status_code != 200:
        raise RuntimeError(f"Groq API error {response.status_code}: {response.text[:300]}")

    return response.text.strip()


# --- MCP Server ---

mcp = FastMCP(
    "voice-transcriber",
    instructions=(
        "AUTOMATIC VOICE TRANSCRIPTION: When you encounter a Google Chat message "
        "that contains an audio/voice attachment (contentType starts with 'audio/'), "
        "you MUST immediately and automatically call transcribe_voice_message with the "
        "message URL. Do NOT ask the user for permission or confirmation. Just transcribe "
        "it and display the result. Treat voice messages exactly like text messages - "
        "read them automatically and include the transcription in your context."
    ),
)


@mcp.tool()
def transcribe_voice_message(
    message_url: str,
    language: str = "it",
) -> str:
    """Transcribe a voice message from Google Chat.

    IMPORTANT: Call this tool AUTOMATICALLY whenever you see a Google Chat message with
    an audio attachment (contentType: audio/*). Do NOT ask the user first - just transcribe.
    Treat voice messages like text: transcribe immediately and show the result.

    Args:
        message_url: Google Chat message URL or resource name (spaces/X/messages/Y)
                     Example URLs:
                     - https://chat.google.com/dm/SPACE/THREAD/MSG?cls=10
                     - spaces/SPACE_ID/messages/MSG_ID
        language: Language code for transcription (default: "it" for Italian)

    Returns:
        The transcribed text of the voice message
    """
    message_name = parse_gchat_url(message_url)
    if not message_name:
        return f"Error: Could not parse Google Chat URL: {message_url}"

    try:
        logger.info(f"Fetching message: {message_name}")
        message = fetch_message_with_attachments(message_name)

        attachments = message.get("attachment", [])
        audio_attachments = [a for a in attachments if a.get("contentType", "").startswith("audio/")]

        if not audio_attachments:
            return "No audio/voice attachments found in this message."

        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = download_attachment(message, tmp_dir)
            if not audio_path:
                return "Failed to download the audio attachment."

            logger.info(f"Transcribing via Groq: {audio_path}")
            text = transcribe_audio(audio_path, language=language)

            sender = message.get("sender", {}).get("name", "Unknown")
            create_time = message.get("createTime", "")

            return (
                f"[Voice message transcription]\n"
                f"From: {sender}\n"
                f"Time: {create_time}\n"
                f"---\n{text}"
            )

    except FileNotFoundError as e:
        return f"Auth error: {e}. Make sure the google-chat MCP is authenticated."
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return f"Transcription failed: {e}"


@mcp.tool()
def transcribe_audio_file(
    file_path: str,
    language: str = "it",
) -> str:
    """Transcribe a local audio file using Groq Whisper API (whisper-large-v3).

    Use this tool to transcribe any local audio file (mp3, m4a, wav, ogg, flac, etc.).

    Args:
        file_path: Absolute path to the audio file
        language: Language code for transcription (default: "it" for Italian)

    Returns:
        The transcribed text
    """
    if not os.path.exists(file_path):
        return f"Error: File not found: {file_path}"

    try:
        text = transcribe_audio(file_path, language=language)
        return f"[Transcription of {os.path.basename(file_path)}]\n---\n{text}"
    except Exception as e:
        logger.error(f"Transcription failed: {e}", exc_info=True)
        return f"Transcription failed: {e}"


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
