# Voice Transcriber MCP Server

MCP server that **automatically transcribes Google Chat voice messages** using [Groq Whisper API](https://console.groq.com/) (whisper-large-v3). No local GPU needed.

When Claude Code encounters an audio attachment in a Google Chat message, this server transcribes it immediately without asking for confirmation.

## Features

- Transcribe Google Chat voice messages by URL (automatic)
- Transcribe local audio files (mp3, m4a, wav, ogg, flac, webm, aac)
- Uses Groq Whisper API (free tier, fast, cloud-based)
- Reuses Google Chat OAuth2 credentials (no separate Google auth needed)

## Prerequisites

### 1. Groq API Key (free)

1. Go to [console.groq.com/keys](https://console.groq.com/keys)
2. Create a free account
3. Generate an API key
4. You'll set this as `GROQ_API_KEY` in your MCP config (see below)

### 2. Google Chat OAuth2 Token

This server needs a valid Google Chat OAuth2 token (`token.json`) to fetch messages and download audio attachments.

**If you already use a Google Chat MCP server** (e.g. [multi-chat-mcp-server](https://github.com/nicholasgasior/multi-chat-mcp-server)), the token is already available. Default path:

```
~/tools/multi-chat-mcp-server/src/providers/google_chat/token.json
```

If your token is in a different location, set the `GCHAT_TOKEN_PATH` environment variable.

**If you don't have a Google Chat token yet**, you need to:
1. Create a Google Cloud project with Chat API enabled
2. Create OAuth2 credentials (Desktop app)
3. Run the OAuth flow to generate `token.json` with scopes:
   - `https://www.googleapis.com/auth/chat.messages.readonly`
   - `https://www.googleapis.com/auth/chat.spaces.readonly`

### 3. uv (Python package manager)

| OS | Command |
|----|----|
| **Linux / macOS / WSL** | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Windows** | `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |

Verify: `uv --version`

## Installation

```bash
git clone https://github.com/fgasparetto/voice-transcriber-mcp.git
cd voice-transcriber-mcp
uv sync
```

## Configuration

Add to your Claude Code MCP config (`.mcp.json` or `~/.claude.json`):

```json
{
  "mcpServers": {
    "voice-transcriber": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "--directory", "/path/to/voice-transcriber-mcp",
        "run", "python", "server.py"
      ],
      "env": {
        "GROQ_API_KEY": "gsk_your_groq_api_key_here"
      }
    }
  }
}
```

Replace:
- `/path/to/voice-transcriber-mcp` with the actual clone directory
- `gsk_your_groq_api_key_here` with your Groq API key

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GROQ_API_KEY` | Yes | — | Groq API key ([get one free](https://console.groq.com/keys)) |
| `GCHAT_TOKEN_PATH` | No | `~/tools/multi-chat-mcp-server/src/providers/google_chat/token.json` | Path to Google Chat OAuth2 token |

## Tools

### `transcribe_voice_message`

Transcribe a voice message from Google Chat. **Called automatically** by Claude when it encounters an audio attachment.

```
transcribe_voice_message(
  message_url="https://chat.google.com/dm/SPACE/THREAD/MSG",
  language="it"
)
```

### `transcribe_audio_file`

Transcribe a local audio file.

```
transcribe_audio_file(
  file_path="/tmp/recording.m4a",
  language="it"
)
```

## Platform Notes

### Linux
No additional steps. Ensure `uv` is in your PATH.

### macOS
- If `uv` not found after install: `export PATH="$HOME/.local/bin:$PATH"`

### Windows (WSL)
Claude Code runs inside WSL. All paths must be Linux-style:
- Token path: `/home/USER/tools/...` (NOT `/mnt/c/...`)
- If `uv` not found: `source ~/.bashrc` or add `~/.local/bin` to PATH

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `GROQ_API_KEY not set` | Add it to the `env` section in your MCP config |
| `Google Chat token not found` | Set `GCHAT_TOKEN_PATH` or authenticate your Google Chat MCP |
| `Groq API error 413` | Audio file too large (Groq limit: 25MB) |
| `uv: command not found` | Install uv (see Prerequisites) |

## How It Works

```
Claude Code → MCP tool call → server.py
  1. Parse Google Chat URL
  2. Fetch message via Google Chat API (OAuth2 token)
  3. Download audio attachment via media API
  4. Send to Groq Whisper API (whisper-large-v3)
  5. Return transcribed text
```

## License

MIT
