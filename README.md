# Screen Agent

**Give AI agents eyes and hands on the desktop.**

An [MCP](https://modelcontextprotocol.io/) server that lets AI tools (Claude Code, Cursor, etc.) see your screen and interact with any application — with a multi-backend input system that works where others fail.

## Why?

AI coding assistants are powerful but blind. Screen Agent fixes that with:

- **Vision-First Testing** — the LLM SEES the screen and decides where to click. Not OCR text matching, not DOM selectors. Visual understanding. This is what makes Screen Agent fundamentally different from Playwright.
- **`act` + `eval_js`** — `act` returns a screenshot for the LLM to analyze visually, then executes at LLM-provided coordinates. `eval_js` runs JavaScript via CDP for assertions. 5 tests in 0.6s.
- **Background Testing** — `window_scope` + CDP lets you test Chrome apps on any macOS Space without touching the user's screen. For native apps, tests behind other windows on the same Space.
- **Multi-Backend Input Chain** — three input methods (Accessibility API → CGEvent → pyautogui) with automatic fallback. Works with native apps, Electron apps, and game engines.
- **Input Guardian** — real-time safety system that pauses all agent actions when you touch your mouse or keyboard. No other tool provides this.
- **Cross-App Workflows** — test flows spanning multiple apps (email → browser → Slack). No other tool can do this because they're all single-app.

## Architecture

```
┌──────────────────────────────────┐
│          MCP Layer               │  22 tools via Model Context Protocol
├──────────────────────────────────┤
│          Engine Layer            │  InputChain (fallback) + Guardian (safety)
│                                  │  + WindowSession (background testing)
├──────────────────────────────────┤
│        Platform Layer            │  Protocol-based backends
│  AX → CGEvent → pyautogui       │  macOS / Windows / Linux
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

### OCR (auto-detects Chinese, Japanese, Korean, English)
| Tool | Description |
|------|-------------|
| `ocr` | Extract all text with bounding boxes |
| `find_text` | Find text and return location |
| `click_text` | Find text and click its center |

### Vision-First Testing (the differentiator)
| Tool | Description |
|------|-------------|
| `act` | Returns screenshot as image → LLM looks and decides → executes at coordinates. No OCR needed. |
| `eval_js` | Execute JavaScript in the page via CDP. Read DOM state, assert values, click by selector. |
| `interact` | OCR-based fallback: find element by text + click/type in one call |

### Background Testing
| Tool | Description |
|------|-------------|
| `window_scope` | Lock to a window. Chrome: auto-CDP (any Space). Native: CGWindowList (same Space). |
| `window_release` | Release window scope, return to full-screen mode |

### Visual E2E Testing
| Tool | Description |
|------|-------------|
| `test_start` | Start a test session with automatic screenshot collection |
| `test_step` | Begin a test step (auto-captures "before" screenshot) |
| `test_verify` | Verify step via OCR text check or screenshot diff |
| `test_end` | End session, generate markdown report with evidence |
| `test_status` | Current session status |

### Safety (Input Guardian)
| Tool | Description |
|------|-------------|
| `add_app` | Add app to allowlist — agent can ONLY interact with listed apps |
| `remove_app` | Remove from allowlist |
| `set_region` | Restrict to pixel region |
| `clear_scope` | Remove all restrictions |
| `get_agent_status` | Guardian state, backend stats, scope info |

## Background Testing

Screen Agent can test applications **without occupying your screen**. Three modes, auto-selected:

### Mode 1: CDP (Chrome/Electron — any Space, fully invisible)

```bash
# Start Chrome with debugging port
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-test
```

```
# Connect — works even if Chrome is on a different desktop
window_scope(app="Chrome", url="localhost:3000")

# All operations go through Chrome's internal pipeline
interact(target="Submit", action="click")
interact(target="Email", action="click_and_type", text="test@example.com")

window_release()
```

CDP bypasses the macOS window server entirely. Screenshots come from Chrome's renderer, clicks go through Chrome's input system. **Your screen is never touched.**

### Mode 2: Window Capture (any macOS app — same Space)

```
# Works with Figma, Xcode, Terminal, games — any app
window_scope(app="Figma", title="Design v2")
interact(target="Export", action="click")
window_release()
```

Uses `CGWindowListCreateImage` to capture the window even when behind other apps. Requires same macOS Space.

### Mode 3: Full Screen (original)

Without `window_scope`, operates on the full screen as before.

### Fallback Priority
```
window_scope called → try CDP (Chrome) → try CGWindowList (same Space) → error
no scope → full screen mode
```

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
| `SCREEN_AGENT_MAX_DIMENSION` | 2560 | Max screenshot dimension |
| `SCREEN_AGENT_LOG_LEVEL` | INFO | Logging level |

## Platform Support

| Feature | macOS | Windows | Linux |
|---------|-------|---------|-------|
| Screenshot | mss | mss | mss |
| AX Input | Quartz AX | - | - |
| CGEvent Input | Quartz | - | - |
| pyautogui Input | fallback | fallback | fallback |
| Window Management | AppleScript | - | wmctrl |
| OCR | Vision Framework | - | - |
| Retina Scaling | auto-detect | - | - |
| Window Capture | CGWindowListCreateImage | PrintWindow | xdotool+ImageMagick |

## Development

```bash
git clone https://github.com/chriswu727/screen-agent
cd screen-agent
pip install -e ".[dev,macos]"
pytest tests/unit/ -v
ruff check src/ tests/
```

See [DEVPATH.md](DEVPATH.md) for development history and architectural decisions.

## License

MIT
