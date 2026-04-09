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
            "Take a screenshot. Returns the image — LOOK at it to understand "
            "the screen visually. Prefer using your visual understanding over OCR "
            "for deciding where to click. When you see a button, icon, or UI element, "
            "estimate its coordinates from the image and use click(x, y) directly."
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
        description="Find specific text on screen and return its location. Auto-detects language from query (Chinese, Japanese, Korean, English).",
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
                "lang": {
                    "type": "string",
                    "description": "OCR language override: en, zh-Hans, ja, ko. Auto-detected if omitted.",
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="click_text",
        description=(
            "Find text on screen using OCR and click its center. "
            "Combines find_text + click into one action. Auto-detects language from query."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to find and click"},
                "lang": {
                    "type": "string",
                    "description": "OCR language override: en, zh-Hans, ja, ko. Auto-detected if omitted.",
                },
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
    # ── Window Scope ─────────────────────────────────────────
    Tool(
        name="window_scope",
        description=(
            "Lock all operations to a specific window. The user's screen stays free. "
            "For Chrome/Electron: auto-connects via CDP for full cross-Space support "
            "(requires Chrome started with --remote-debugging-port=9222). "
            "For other apps: uses window capture (same Space only)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "App name (partial match, e.g. 'Chrome')"},
                "title": {"type": "string", "description": "Window title (partial match)"},
                "url": {"type": "string", "description": "Match tab by URL (CDP mode, e.g. 'localhost:3456')"},
                "cdp_port": {"type": "integer", "default": 9222, "description": "Chrome debugging port"},
                "use_cdp": {"type": "boolean", "default": False, "description": "Force CDP mode"},
            },
        },
    ),
    Tool(
        name="window_release",
        description="Release window scope. Operations return to full-screen mode.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # ── Interact (compound action) ───────────────────────────
    Tool(
        name="interact",
        description=(
            "Find an element by visible text and interact with it — all in one call. "
            "Replaces the multi-step capture→find→click→type pipeline. "
            "Auto-detects CJK languages. Works with window_scope for background testing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Visible text to find (e.g. 'Submit', '蓝色按钮')"},
                "action": {
                    "type": "string",
                    "enum": ["click", "type", "click_and_type"],
                    "default": "click",
                    "description": "click=click the element, type=type at cursor, click_and_type=click then type",
                },
                "text": {"type": "string", "description": "Text to type (required for type/click_and_type)"},
                "lang": {"type": "string", "description": "OCR language override. Auto-detected if omitted."},
                "index": {
                    "type": "integer", "default": 0,
                    "description": "Which match to interact with if multiple found",
                },
                **_VERIFY,
            },
            "required": ["target"],
        },
    ),
    # ── Vision-First Testing ────────────────────────────────
    Tool(
        name="act",
        description=(
            "Vision-first interaction: take a screenshot, return it as an image, "
            "then execute an action at coordinates YOU determine by looking at the image. "
            "Unlike 'interact' (which uses OCR to find text), 'act' trusts YOUR visual "
            "understanding of the screen. Use this when:\n"
            "- Elements have no text (icons, images, colored buttons)\n"
            "- OCR might fail (white text on colored background)\n"
            "- You can SEE where to click from the screenshot\n\n"
            "Workflow: call act() → look at the returned screenshot → call act(x, y, action) "
            "to execute. Or provide x, y directly if you already know the coordinates."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Click X coordinate (from screenshot)"},
                "y": {"type": "integer", "description": "Click Y coordinate (from screenshot)"},
                "action": {
                    "type": "string",
                    "enum": ["screenshot", "click", "type", "click_and_type"],
                    "default": "screenshot",
                    "description": "screenshot=just capture, click/type/click_and_type=execute action",
                },
                "text": {"type": "string", "description": "Text to type (for type/click_and_type)"},
            },
        },
    ),
    Tool(
        name="eval_js",
        description=(
            "Execute JavaScript in the browser page (CDP mode only). "
            "Use for assertions, reading DOM state, or clicking elements that OCR can't find. "
            "Requires window_scope with CDP connection.\n\n"
            "Examples:\n"
            "- eval_js('document.title') → page title\n"
            "- eval_js('document.querySelector(\"#count\").textContent') → '3'\n"
            "- eval_js('document.querySelector(\".btn\").click()') → click via DOM"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "JavaScript expression to evaluate"},
            },
            "required": ["expression"],
        },
    ),
    # ── Autonomous Test Runner ────────────────────────────────
    Tool(
        name="run_test",
        description=(
            "Execute a test plan AUTONOMOUSLY — no LLM round-trips during execution. "
            "You plan the steps, the server executes them all. 15x faster than per-step interaction.\n\n"
            "Each step can:\n"
            "- find + click: locate element by visible text and click it\n"
            "- find + click_and_type: click element and type text\n"
            "- verify: check that text is visible after actions\n"
            "- eval_js: run JavaScript assertion (CDP mode)\n"
            "- key: press a key (enter, tab, etc.)\n"
            "- wait: pause between steps\n\n"
            "Example:\n"
            "  run_test(name='Login', steps=[\n"
            "    {find: 'Email', action: 'click_and_type', text: 'user@test.com'},\n"
            "    {find: 'Password', action: 'click_and_type', text: 'secret'},\n"
            "    {find: 'Log in', action: 'click'},\n"
            "    {verify: 'Dashboard'},\n"
            "  ])"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Test name"},
                "steps": {
                    "type": "array",
                    "description": "Test steps to execute autonomously",
                    "items": {
                        "type": "object",
                        "properties": {
                            "find": {"type": "string", "description": "Visible text to find (tries JS text search first, falls back to OCR)"},
                            "selector": {"type": "string", "description": "CSS selector (fastest, CDP only). e.g. '#email', '.btn-primary'"},
                            "action": {
                                "type": "string",
                                "enum": ["click", "type", "click_and_type"],
                                "description": "Action to perform on found element",
                            },
                            "text": {"type": "string", "description": "Text to type"},
                            "verify": {"type": "string", "description": "Text that should be visible (verification)"},
                            "eval_js": {"type": "string", "description": "JavaScript to evaluate (CDP only)"},
                            "expected": {"type": "string", "description": "Expected eval_js result"},
                            "key": {"type": "string", "description": "Key to press (enter, tab, etc.)"},
                            "wait": {"type": "number", "description": "Seconds to wait before step"},
                            "verify_wait": {"type": "number", "default": 0.3, "description": "Seconds to wait before verification"},
                        },
                    },
                },
            },
            "required": ["name", "steps"],
        },
    ),
]

# Tools that require guardian clearance before execution
INPUT_TOOLS = {
    "click", "type_text", "press_key", "scroll",
    "move_mouse", "drag", "focus_window", "click_text", "interact", "act",
}
