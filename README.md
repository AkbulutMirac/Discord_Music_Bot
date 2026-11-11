# 🎵 Discord Music Bot with MCP Integration

A powerful Discord music bot that integrates with **Claude AI** via the **Model Context Protocol (MCP)**. Control your Discord bot using natural language through Claude Desktop or Claude Mobile!

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Discord.py](https://img.shields.io/badge/discord.py-2.7-blue.svg)
![MCP](https://img.shields.io/badge/MCP-FastMCP-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

## ✨ Features

### 🎶 Music Playback
- Play music from YouTube with high-quality audio
- Queue management (add, remove, clear, view)
- Playback controls (play, pause, resume, skip, stop)
- Auto-play next song in queue

### 🤖 MCP Integration (Claude AI Control)
- Control the bot via **Claude Desktop** or **Claude Mobile**
- Natural language commands ("play some jazz music", "skip this song")
- Auto-join: Bot finds you in voice channels automatically

### 🗣️ Voice
- Text-to-Speech in Turkish (TTS)

## 📋 Requirements

- Python 3.8 or higher
- FFmpeg (installed and added to system PATH)
- Deno (JavaScript runtime that yt-dlp needs for YouTube)
- Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))

## 🚀 Installation

### 1. Clone the repository
```bash
git clone https://github.com/AkbulutMirac/Discord_Music_Bot.git
cd Discord_Music_Bot
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure environment variables
Create a `.env` file in the project root (copy from `.env.example`):
```env
BOT_TOKEN=your_discord_bot_token_here
CHANNEL_ID=your_default_channel_id_here
VOICE_ID=your_default_voice_channel_id_here
OWNER_ID=your_discord_user_id_here
```

### 4. Install FFmpeg
- **Windows:** Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH
- **macOS:** `brew install ffmpeg`
- **Linux:** `sudo apt install ffmpeg`

### 5. Install Deno
yt-dlp needs a JavaScript runtime to get working YouTube links (otherwise YouTube can return 403 Forbidden).
- **Windows:** `winget install DenoLand.Deno`
- **macOS:** `brew install deno`
- **Linux:** `curl -fsSL https://deno.land/install.sh | sh`

## 🎮 Usage

### Running Modes

The repo has two bot files:
- `dc_bot.py` — simple Discord-only music bot (no MCP)
- `dc_bot_mcp.py` — same commands plus MCP server, so Claude can control the bot

| Mode | Command | Description |
|------|---------|-------------|
| Simple bot | `python dc_bot.py` | Discord commands only |
| Discord Only | `python dc_bot_mcp.py` | Run as a regular Discord bot |
| MCP (stdio) | `python dc_bot_mcp.py --mode mcp` | For Claude Desktop (local) |
| MCP (HTTP) | `python dc_bot_mcp.py --mode http` | For remote access / Cloudflare Tunnel |

### Discord Commands

#### 🎵 Queue Management
| Command | Description |
|---------|-------------|
| `!add <song>` | Add a song to the queue |
| `!remove <name>` | Remove a song from the queue |
| `!clear` | Clear the entire queue |
| `!queue` | Show the current queue |

#### ▶️ Playback Controls
| Command | Description |
|---------|-------------|
| `!play <song>` | Play a song or the queue |
| `!pause` | Pause playback |
| `!resume` | Resume playback |
| `!skip` | Skip to the next song |
| `!stop` | Stop playback and clear queue |

#### 🗣️ Voice
| Command | Description |
|---------|-------------|
| `!speak <text>` | Bot speaks text in Turkish (TTS) |

#### 🔊 Voice Channel
| Command | Description |
|---------|-------------|
| `!join` | Bot joins your voice channel |
| `!leave` | Bot leaves the voice channel |
| `!help` | Show help message |

## 🔗 MCP Setup (Claude AI Integration)

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "discord-bot": {
      "command": "python",
      "args": ["C:\\path\\to\\dc_bot_mcp.py", "--mode", "mcp"]
    }
  }
}
```

### Remote Access (Mobile/Cloudflare Tunnel)

1. Start the bot in HTTP mode:
```bash
python dc_bot_mcp.py --mode http --port 9000
```

2. Create a Cloudflare Tunnel:
```bash
cloudflared tunnel --url http://localhost:9000
```

3. Add the tunnel URL to Claude Mobile:
   - Settings → MCP → Add Server
   - URL: `https://your-tunnel-url.trycloudflare.com/sse`

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `play_music` | Play a song on Discord |
| `stop_music` | Stop playback |
| `pause_music` | Pause playback |
| `resume_music` | Resume playback |
| `skip_song` | Skip to next song |
| `add_to_queue` | Add song to queue |
| `get_queue` | View current queue |
| `clear_queue` | Clear the queue |
| `speak_text` | TTS in Turkish |
| `auto_join` | Auto-find and join your channel |
| `list_servers` | List available voice channels |
| `get_playback_status` | Check what's playing |

## 📁 Project Structure

```
Discord_Music_Bot/
├── dc_bot.py          # Simple Discord music bot
├── dc_bot_mcp.py      # Music bot + MCP server (Claude control)
├── music_source.py    # Finds a playable YouTube stream (shared by both bots)
├── check.py           # Health check: versions, ffmpeg, Deno, YouTube stream
├── requirements.txt   # Python dependencies (exact, tested versions)
├── .env.example       # Example environment file
├── LICENSE            # MIT License
└── README.md          # This file
```

## 🛠️ Keeping the Bot Working

Most breakages come from three things not matching each other: **yt-dlp**, **discord.py** (with its voice encryption package `davey`) and **Deno**.

| Part | What breaks it | Symptom |
|------|----------------|---------|
| yt-dlp | YouTube changes how it serves videos | Song stops after a few seconds, or ffmpeg exits with HTTP 403 |
| Deno | Missing, or not on PATH | yt-dlp warns "No supported JavaScript runtime", streams fail |
| discord.py + davey | Updating one without the other (e.g. davey 0.2 with discord.py 2.7) | Bot shows the green speaking ring but nobody hears anything |

How to avoid it:
1. **Install exact versions:** `pip install -r requirements.txt`. Don't run `pip install -U` on everything.
2. **Run the health check** before starting the bot, and after any update:
   ```bash
   python check.py
   ```
   It checks the versions, ffmpeg, Deno, and plays 5 seconds of a YouTube song. Every line should say `[OK]`.
3. **When YouTube breaks** (check.py fails on the stream), update only yt-dlp, run `python check.py` again, and if it passes, write the new version into `requirements.txt`:
   ```bash
   pip install -U "yt-dlp[default]"
   ```
4. **Update discord.py and davey only together**, and only when the discord.py release notes say the new davey version is supported.

If no stream works, the bot now says so in the Discord channel ("Could not play ...") instead of silently skipping. `music_source.py` tries several YouTube clients in order (`PLAYER_CLIENTS`); you can change that list if a different client starts working.

## ⚠️ Notes

- Ensure FFmpeg is installed and added to your system PATH
- `dc_bot.py` uses the channel IDs written at the top of the file; `dc_bot_mcp.py` reads them from `.env`
- The bot requires permissions: Connect, Speak, Read Messages, Send Messages
- MCP integration requires [Claude Desktop](https://claude.ai/download)

## 📄 License

MIT License - feel free to use and modify!

## 🤝 Contributing

Contributions are welcome! Feel free to open issues or submit pull requests.

---

Made by Mirage
