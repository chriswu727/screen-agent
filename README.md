# Screen Agent

**Give AI agents eyes and hands on the desktop.**

An [MCP](https://modelcontextprotocol.io/) server that lets AI tools (Claude Code, Cursor, etc.) see your screen and interact with any application — with a multi-backend input system that works where others fail.

## Why?

AI coding assistants are powerful but blind. Screen Agent fixes that with:

- **Multi-Backend Input Chain** — three input methods (Accessibility API → CGEvent → pyautogui) tried in priority order with automatic fallback. Works with native apps, Electron apps, and game engines.
- **Input Guardian** — real-time safety system that pauses all agent actions when you touch your mouse or keyboard. No other tool provides this.
- **Apple Vision OCR** — zero-dependency text recognition on macOS (no 2GB PaddleOCR install needed).
- **Retina-Aware Coordinates** — unified logical coordinate system that handles display scaling correctly.

## Architecture

```
┌──────────────────────────────────┐
│          MCP Layer               │  19 tools via Model Context Protocol
├──────────────────────────────────┤
│          Engine Layer            │  InputChain (fallback) + Guardian (safety)
├──────────────────────────────────┤
│        Platform Layer            │  Protocol-based backends
│  AX → CGEvent → pyautogui       │  macOS / Linux
└──────────────────────────────────┘
```

### Input Backend Chain

The core design challenge: `pyautogui` works for ~80% of apps but fails for game engines and many Electron apps. Screen Agent solves this with a **Chain of Responsibility** pattern:

| Priority | Backend | Method | Best For |
|----------|---------|--------|----------|
| 1 | **AX** | `AXPerformAction` | Native macOS apps — semantic, no coordinates needed |
| 2 | **CGEvent** | `CGEventPost` | Games, Electron — native OS event injection |
| 3 | **pyautogui** | Python wrapper | Cross-platform fallback |

Each backend implements the same `InputBackend` protocol. If one fails, the chain automatically tries the next. All attempts are logged with telemetry for observability.

## Install

```bash
pip install screen-agent

# Recommended: install macOS native backends
pip install screen-agent[macos]
```

## Quick Start

### With Claude Code

```bash
claude mcp add screen -- screen-agent serve
```

### With Cursor / other MCP clients

Add to your MCP config:

```json
{
  "mcpServers": {
    "screen": {
      "command": "screen-agent",
      "args": ["serve"]
    }
  }
}
```

### Check system capabilities

```bash
screen-agent check
```

## Tools

### Perception
| Tool | Description |
|------|-------------|
| `capture_screen` | Screenshot (full or region), returns image for vision analysis |
| `list_windows` | List all visible windows with positions |
| `get_active_window` | Currently focused window |
| `get_cursor_position` | Current mouse position |

### Input (all support `verify: true` for post-action screenshots)
| Tool | Description |
|------|-------------|
| `click` | Click at coordinates (left/right/middle, multi-click) |
| `type_text` | Type text at cursor (Unicode via clipboard on macOS) |
| `press_key` | Key press with modifiers (e.g., Cmd+C) |
| `scroll` | Scroll wheel at optional position |
| `move_mouse` | Move cursor without clicking |
| `drag` | Click-drag between two points |
| `focus_window` | Bring window to front by partial title match |

### OCR (requires macOS with Vision framework)
| Tool | Description |
|------|-------------|
| `ocr` | Extract all text with bounding boxes |
| `find_text` | Find text and return location |
| `click_text` | Find text and click its center |

### Safety (Input Guardian)
| Tool | Description |
|------|-------------|
| `add_app` | Add app to allowlist — agent can ONLY interact with listed apps |
| `remove_app` | Remove from allowlist |
| `set_region` | Restrict to pixel region |
| `clear_scope` | Remove all restrictions |
| `get_agent_status` | Guardian state, backend stats, scope info |

## Input Guardian

Screen Agent's unique safety system with two guarantees:

1. **User Priority** — any keyboard/mouse activity instantly pauses the agent. It resumes only after you've been idle for 1.5s (configurable).
2. **Scope Lock** — restrict the agent to specific apps and/or screen regions.

```python
# Agent can only interact with Chrome and Figma
add_app("Chrome")
add_app("Figma")

# Or restrict to a region
set_region(x=0, y=0, width=800, height=600)
```

## Configuration

All parameters are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SCREEN_AGENT_COOLDOWN` | 1.5 | Guardian cooldown seconds |
| `SCREEN_AGENT_GUARDIAN_DISABLED` | 0 | Set to "1" to disable |
| `SCREEN_AGENT_INPUT_BACKENDS` | ax,cgevent,pyautogui | Backend priority order |
| `SCREEN_AGENT_MAX_DIMENSION` | 2000 | Max screenshot dimension |
| `SCREEN_AGENT_LOG_LEVEL` | INFO | Logging level |

## Platform Support

| Feature | macOS | Linux |
|---------|-------|-------|
| Screenshot | ✅ mss | ✅ mss |
| AX Input | ✅ | — |
| CGEvent Input | ✅ | — |
| pyautogui Input | ✅ | ✅ |
| Window Management | ✅ AppleScript | ✅ wmctrl |
| OCR | ✅ Vision Framework | — |
| Retina Scaling | ✅ | — |

## Development

```bash
git clone https://github.com/chriswu727/screen-agent
cd screen-agent
pip install -e ".[dev,macos]"
pytest tests/unit/ -v
ruff check src/ tests/
```

## License

MIT
