"""MCP tool schema definitions.

Pure data: no logic, no imports beyond mcp.types.
Tool behavior lives in handlers.py.
"""

from __future__ import annotations

from mcp.types import Tool

_VERIFY = {
    "verify": {
        "type": "boolean",
        "default": False,
        "description": "Capture a screenshot after the action to verify it worked",
    },
}

TOOLS: list[Tool] = [
    # ── Perception ────────────────────────────────────────────
    Tool(
        name="capture_screen",
        description=(
            "Take a screenshot of the entire screen or a specific region. "
            "Returns the image for visual analysis. Use this to see what's "
            "currently displayed on the user's screen."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region to capture. Omit for full screen.",
                    "properties": {
                        "x": {"type": "integer", "description": "Left edge"},
                        "y": {"type": "integer", "description": "Top edge"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["x", "y", "width", "height"],
                },
            },
        },
    ),
    Tool(
        name="list_windows",
        description="List all visible windows with their titles and positions.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_active_window",
        description="Get the currently focused window's app name and title.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_cursor_position",
        description="Get the current mouse cursor position.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # ── Input ─────────────────────────────────────────────────
    Tool(
        name="click",
        description="Click at specific screen coordinates.",
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
                "clicks": {
                    "type": "integer",
                    "default": 1,
                    "description": "Number of clicks (2 for double-click)",
                },
                **_VERIFY,
            },
            "required": ["x", "y"],
        },
    ),
    Tool(
        name="type_text",
        description=(
            "Type text at the current cursor position. "
            "Click on an input field first, then use this to type into it."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
                **_VERIFY,
            },
            "required": ["text"],
        },
    ),
    Tool(
        name="press_key",
        description=(
            "Press a key or key combination. "
            "Examples: 'enter', 'tab', 'escape', 'backspace', 'space', "
            "'up', 'down', 'left', 'right'. "
            "Use modifiers for combos like Cmd+C."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key to press"},
                "modifiers": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["command", "ctrl", "alt", "shift"],
                    },
                    "description": "Modifier keys to hold while pressing",
                },
                **_VERIFY,
            },
            "required": ["key"],
        },
    ),
    Tool(
        name="scroll",
        description="Scroll the mouse wheel. Positive=up, negative=down.",
        inputSchema={
            "type": "object",
            "properties": {
                "amount": {"type": "integer", "description": "Scroll amount"},
                "x": {"type": "integer", "description": "Optional X position"},
                "y": {"type": "integer", "description": "Optional Y position"},
                **_VERIFY,
            },
            "required": ["amount"],
        },
    ),
    Tool(
        name="move_mouse",
        description="Move the mouse cursor to specific coordinates without clicking.",
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                **_VERIFY,
            },
            "required": ["x", "y"],
        },
    ),
    Tool(
        name="drag",
        description="Click and drag from one position to another.",
        inputSchema={
            "type": "object",
            "properties": {
                "start_x": {"type": "integer"},
                "start_y": {"type": "integer"},
                "end_x": {"type": "integer"},
                "end_y": {"type": "integer"},
                "button": {
                    "type": "string",
                    "enum": ["left", "right"],
                    "default": "left",
                },
                **_VERIFY,
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    ),
    Tool(
        name="focus_window",
        description="Bring a window to the front by title. Supports partial matching.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Full or partial window title"},
                **_VERIFY,
            },
            "required": ["title"],
        },
    ),
    # ── OCR ───────────────────────────────────────────────────
    Tool(
        name="ocr",
        description=(
            "Extract all visible text from the screen with positions. "
            "Returns detected text blocks with bounding boxes and confidence."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lang": {
                    "type": "string",
                    "default": "en",
                    "description": "Language code: en, zh-Hans, ja, ko, etc.",
                },
                "region": {
                    "type": "object",
                    "description": "Optional region to scan",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["x", "y", "width", "height"],
                },
            },
        },
    ),
    Tool(
        name="find_text",
        description="Find specific text on screen and return its location.",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="click_text",
        description=(
            "Find text on screen using OCR and click its center. "
            "Combines find_text + click into one action."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to find and click"},
                "index": {
                    "type": "integer",
                    "default": 0,
                    "description": "Which match to click if multiple found (0=first)",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
            },
            "required": ["query"],
        },
    ),
    # ── Guardian / Safety ─────────────────────────────────────
    Tool(
        name="add_app",
        description=(
            "Add an app to the allowed list. The agent can ONLY interact with "
            "apps in this list. Use partial names (e.g. 'Chrome', 'Figma')."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "App name to allow"},
            },
            "required": ["app_name"],
        },
    ),
    Tool(
        name="remove_app",
        description="Remove an app from the allowed list.",
        inputSchema={
            "type": "object",
            "properties": {
                "app_name": {"type": "string", "description": "App name to remove"},
            },
            "required": ["app_name"],
        },
    ),
    Tool(
        name="set_region",
        description="Restrict agent to a pixel region on screen.",
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
        },
    ),
    Tool(
        name="clear_scope",
        description="Remove ALL scope restrictions. Agent can operate anywhere.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_agent_status",
        description=(
            "Check agent status: user activity, allowed apps, region, guardian state, "
            "and input backend statistics."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]

# Tools that require guardian clearance before execution
INPUT_TOOLS = {
    "click", "type_text", "press_key", "scroll",
    "move_mouse", "drag", "focus_window", "click_text",
}
