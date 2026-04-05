# Screen Agent

**Give AI coding tools eyes and hands.**

An [MCP](https://modelcontextprotocol.io/) server that lets Claude Code, Cursor, and other AI tools see your screen and interact with your desktop.

<!-- TODO: Replace with actual demo GIF -->
<!-- ![Demo](docs/demo.gif) -->

## Why?

AI coding assistants are powerful but blind — they can edit files and run commands, but they can't see what's on your screen. Screen Agent fixes that by providing screen capture and desktop interaction as MCP tools.

```
You: "The form in the browser has a bug — can you see it?"
Claude: [captures screen] I see the registration form. The email
        validation shows an error even though the format is correct.
        The regex pattern in validators.ts is too restrictive...
```

## Install

```bash
pip install screen-agent
```

## Quick Start

### Use with Claude Code

1. Add to your MCP config (`~/.claude/mcp.json` or `.mcp.json`):

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

2. Restart Claude Code. That's it — Claude can now see your screen.

### Use as Python library

```python
import asyncio
from screen_agent import capture_screen, mouse_click, keyboard_type

async def main():
    screenshot = await capture_screen()
    print(f"Captured {screenshot['width']}x{screenshot['height']}px")

    await mouse_click(400, 300)
    await keyboard_type("Hello from screen-agent!")

asyncio.run(main())
```

## Tools

| Tool | Description |
|------|-------------|
| `capture_screen` | Screenshot the full screen or a region |
| `click` | Click at screen coordinates |
| `type_text` | Type text at cursor position |
| `press_key` | Press key / key combo (e.g. Cmd+C) |
| `scroll` | Scroll up or down |
| `move_mouse` | Move cursor |
| `drag` | Click and drag |
| `get_cursor_position` | Get cursor coordinates |
| `list_windows` | List visible windows |
| `focus_window` | Focus a window by title |
| `get_active_window` | Get active window info |

All input tools (click, type_text, press_key, scroll, move_mouse, drag, focus_window) support an optional `verify: true` parameter that captures a screenshot after the action, so the LLM can confirm it worked.

### Optional: OCR Plugin

```bash
pip install screen-agent[ocr]
```

Adds three more tools:

| Tool | Description |
|------|-------------|
| `ocr` | Extract all screen text with positions |
| `find_text` | Find text on screen and get coordinates |
| `click_text` | Find text and click its center (OCR + click in one step) |

## Safety: Input Guardian

Screen Agent is designed with **user-first** safety:

**User always has priority.** The moment you touch your keyboard or mouse, the agent pauses instantly. It only resumes after you've been idle for 1.5 seconds (configurable). The agent never fights you for control.

**App allowlist.** The agent must declare which apps it needs access to. It can only interact with apps on the list. Need to work across Chrome and Figma? Just add both.

```
Claude: [calls add_app("Chrome")]
        [calls add_app("Figma")]
        I can now operate in Chrome and Figma.

        [clicks in Chrome]      ← allowed
        [clicks in Figma]       ← allowed
        [clicks in Slack]       ← rejected, not on the list

User:   *moves mouse*
Claude: [paused — waiting for user to finish]
        ...user stops...
Claude: [resumes after 1.5s idle] Continuing where I left off.
```

| Safety Tool | Description |
|---|---|
| `add_app` | Add an app to the allowed list (e.g. "Chrome", "Figma") |
| `remove_app` | Remove an app from the allowed list |
| `set_region` | Restrict to a pixel region on screen |
| `clear_scope` | Remove all restrictions |
| `get_agent_status` | Check guardian state, user activity, allowed apps |

## Platform Support

| | Screenshot | Input Control | Window Management |
|---|---|---|---|
| **macOS** | mss | pyautogui | AppleScript |
| **Linux** | mss | pyautogui | wmctrl |
| **Windows** | mss | pyautogui | Planned |

### macOS Permissions

Screen Agent needs two permissions on macOS:

- **Screen Recording** — for screenshots
- **Accessibility** — for keyboard/mouse control

Grant them in: **System Settings → Privacy & Security**

## Architecture

```
┌──────────────────────────────────────────────┐
│  MCP Client (Claude Code / Cursor / etc.)    │
└──────────────┬───────────────────────────────┘
               │  MCP Protocol (stdio/SSE)
               ▼
┌──────────────────────────────────────────────┐
│  Screen Agent MCP Server                     │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Input Guardian (pynput)               │  │
│  │  • Monitors keyboard + mouse globally  │  │
│  │  • User active? → PAUSE all actions    │  │
│  │  • Scope lock → reject out-of-bounds   │  │
│  └────────────────────────────────────────┘  │
│       │ clearance granted                    │
│       ▼                                      │
│  capture.py  ─  mss (cross-platform)         │
│  input.py    ─  pyautogui                    │
│  window.py   ─  AppleScript / wmctrl         │
│  plugins/    ─  OCR, CV (optional)           │
└──────────────────────────────────────────────┘
```

## Configuration

### Transport modes

```bash
# stdio (default) — for Claude Code and most MCP clients
screen-agent serve

# SSE — for HTTP-based clients
screen-agent serve --transport sse --port 8765
```

### System check

```bash
screen-agent check
```

Verifies all dependencies and platform permissions.

## Development

```bash
git clone https://github.com/chriswu727/screen-agent.git
cd screen-agent
pip install -e ".[dev]"
pytest
```

## License

MIT
