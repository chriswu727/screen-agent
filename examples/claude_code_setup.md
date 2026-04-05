# Using Screen Agent with Claude Code

## Setup

1. Install screen-agent:

```bash
pip install screen-agent
```

2. Add to your Claude Code MCP config:

**Option A: Project-level** (`.mcp.json` in your project root):

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

**Option B: Global** (`~/.claude/mcp.json`):

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

3. Restart Claude Code. You should see the screen tools available.

## macOS Permissions

On first use, macOS will prompt you to grant:

- **Screen Recording** — needed for screenshots
- **Accessibility** — needed for keyboard/mouse control

Go to: **System Settings → Privacy & Security** and enable both for your terminal app.

## Usage Examples

In Claude Code, just ask naturally:

```
> Take a screenshot and tell me what you see

> Click on the "Submit" button in the browser

> The form on screen has an empty "Email" field — fill in test@example.com

> List all open windows and focus the one with "Figma" in the title
```

## Available Tools

Once connected, Claude Code gains these tools:

| Tool | Description |
|------|-------------|
| `capture_screen` | Take a screenshot (full screen or region) |
| `click` | Click at coordinates |
| `type_text` | Type text at cursor position |
| `press_key` | Press key or key combo (e.g., Cmd+C) |
| `scroll` | Scroll up or down |
| `move_mouse` | Move cursor without clicking |
| `drag` | Click and drag |
| `get_cursor_position` | Get current cursor position |
| `list_windows` | List all visible windows |
| `focus_window` | Bring a window to front |
| `get_active_window` | Get current focused window |

### With OCR plugin (`pip install screen-agent[ocr]`):

| Tool | Description |
|------|-------------|
| `ocr` | Extract all text from screen with positions |
| `find_text` | Find specific text and get its coordinates |
