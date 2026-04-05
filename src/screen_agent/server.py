"""MCP Server implementation.

Exposes screen capture, input control, and window management
as MCP tools that any MCP-compatible client can invoke.
"""

from __future__ import annotations

import json
import logging

from mcp.server import Server
from mcp.types import (
    ImageContent,
    TextContent,
    Tool,
)

from screen_agent.capture import capture_screen
from screen_agent.guardian import ClearanceResult, get_guardian
from screen_agent.input import (
    drag,
    get_cursor_position,
    keyboard_type,
    mouse_click,
    mouse_double_click,
    mouse_move,
    press_key,
    scroll,
)
from screen_agent.window import focus_window, get_active_window, list_windows

logger = logging.getLogger("screen-agent")

# Tools that perform input actions (require guardian + support verify)
_INPUT_TOOLS = {
    "click", "type_text", "press_key", "scroll",
    "move_mouse", "drag", "focus_window", "click_text",
}

_VERIFY_PROPERTY = {
    "verify": {
        "type": "boolean",
        "default": False,
        "description": "Capture a screenshot after the action to verify it worked",
    },
}


# ── Guardian Helper ──────────────────────────────────────────────────────

async def _require_clearance(
    x: int | None = None,
    y: int | None = None,
) -> list[TextContent] | None:
    """Check guardian before any input action. Returns error content if blocked."""
    guardian = get_guardian()
    result = await guardian.wait_for_clearance(x=x, y=y)
    if not result.allowed:
        return [TextContent(type="text", text=json.dumps({
            "error": "blocked_by_guardian",
            "reason": result.reason,
            "status": guardian.get_status(),
        }))]
    return None

# ── Tool Definitions ─────────────────────────────────────────────────────

TOOLS: list[Tool] = [
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
                **_VERIFY_PROPERTY,
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
                **_VERIFY_PROPERTY,
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
                **_VERIFY_PROPERTY,
            },
            "required": ["key"],
        },
    ),
    Tool(
        name="scroll",
        description="Scroll the mouse wheel. Positive amount = scroll up, negative = scroll down.",
        inputSchema={
            "type": "object",
            "properties": {
                "amount": {
                    "type": "integer",
                    "description": "Scroll amount. Positive=up, negative=down.",
                },
                "x": {"type": "integer", "description": "Optional X position to scroll at"},
                "y": {"type": "integer", "description": "Optional Y position to scroll at"},
                **_VERIFY_PROPERTY,
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
                **_VERIFY_PROPERTY,
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
                **_VERIFY_PROPERTY,
            },
            "required": ["start_x", "start_y", "end_x", "end_y"],
        },
    ),
    Tool(
        name="get_cursor_position",
        description="Get the current mouse cursor position.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="list_windows",
        description="List all visible windows with their titles and positions.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="focus_window",
        description="Bring a window to the front by title. Supports partial matching.",
        inputSchema={
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Full or partial window title to match",
                },
                **_VERIFY_PROPERTY,
            },
            "required": ["title"],
        },
    ),
    Tool(
        name="get_active_window",
        description="Get the currently focused window's app name and title.",
        inputSchema={"type": "object", "properties": {}},
    ),
    # ── Safety / Guardian Tools ──────────────────────────────────────
    Tool(
        name="add_app",
        description=(
            "Add an app to the allowed list. The agent can ONLY interact with apps "
            "in this list. Use partial names (e.g. 'Chrome', 'Figma', 'Terminal'). "
            "Call this before performing any interactions."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "app_name": {
                    "type": "string",
                    "description": "App name to allow (partial match, case-insensitive)",
                },
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
                "app_name": {
                    "type": "string",
                    "description": "App name to remove",
                },
            },
            "required": ["app_name"],
        },
    ),
    Tool(
        name="set_region",
        description="Restrict agent to a pixel region on screen. Pass no arguments to clear.",
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
        description="Remove ALL scope restrictions (allowed apps + region). Agent can operate anywhere.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_agent_status",
        description=(
            "Check current agent status: whether user is active, "
            "which apps are allowed, current region restriction, and guardian state."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
]


# ── Tool Dispatch ────────────────────────────────────────────────────────

async def _dispatch(
    name: str,
    args: dict,
) -> list[TextContent | ImageContent]:
    """Route a tool call to the appropriate handler."""
    guardian = get_guardian()

    # ── Read-only tools (no guardian clearance needed) ──────────────
    if name == "capture_screen":
        result = await capture_screen(region=args.get("region"))
        return [
            ImageContent(
                type="image",
                data=result["image_base64"],
                mimeType=result["mime_type"],
            ),
            TextContent(
                type="text",
                text=f"Screenshot captured: {result['width']}x{result['height']}px",
            ),
        ]

    elif name == "get_cursor_position":
        result = await get_cursor_position()
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "list_windows":
        result = await list_windows()
        return [TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "get_active_window":
        result = await get_active_window()
        return [TextContent(type="text", text=json.dumps(result))]

    # ── Guardian management tools ────────────────────────────────
    elif name == "add_app":
        scope = guardian.add_app(args["app_name"])
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "allowed_apps": sorted(scope.allowed_apps),
        }))]

    elif name == "remove_app":
        scope = guardian.remove_app(args["app_name"])
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "allowed_apps": sorted(scope.allowed_apps),
        }))]

    elif name == "set_region":
        region = None
        if args.get("x") is not None:
            region = {k: args[k] for k in ("x", "y", "width", "height")}
        scope = guardian.set_region(region)
        return [TextContent(type="text", text=json.dumps({
            "success": True,
            "region": scope.region,
        }))]

    elif name == "clear_scope":
        guardian.clear_scope()
        return [TextContent(type="text", text=json.dumps({"success": True}))]

    elif name == "get_agent_status":
        return [TextContent(type="text", text=json.dumps(guardian.get_status()))]

    # ── Input tools (require guardian clearance) ─────────────────
    elif name == "click":
        blocked = await _require_clearance(x=args["x"], y=args["y"])
        if blocked:
            return blocked
        result = await mouse_click(
            args["x"], args["y"],
            button=args.get("button", "left"),
            clicks=args.get("clicks", 1),
        )
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "type_text":
        blocked = await _require_clearance()
        if blocked:
            return blocked
        result = await keyboard_type(args["text"])
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "press_key":
        blocked = await _require_clearance()
        if blocked:
            return blocked
        result = await press_key(args["key"], modifiers=args.get("modifiers"))
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "scroll":
        blocked = await _require_clearance(x=args.get("x"), y=args.get("y"))
        if blocked:
            return blocked
        result = await scroll(args["amount"], x=args.get("x"), y=args.get("y"))
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "move_mouse":
        blocked = await _require_clearance(x=args["x"], y=args["y"])
        if blocked:
            return blocked
        result = await mouse_move(args["x"], args["y"])
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "drag":
        blocked = await _require_clearance(x=args["start_x"], y=args["start_y"])
        if blocked:
            return blocked
        result = await drag(
            args["start_x"], args["start_y"],
            args["end_x"], args["end_y"],
            button=args.get("button", "left"),
        )
        return [TextContent(type="text", text=json.dumps(result))]

    elif name == "focus_window":
        blocked = await _require_clearance()
        if blocked:
            return blocked
        result = await focus_window(args["title"])
        return [TextContent(type="text", text=json.dumps(result))]

    else:
        # Check if it's a plugin tool
        from screen_agent.plugins import get_plugin_tools, dispatch_plugin_tool

        plugin_names = [t.name for t in get_plugin_tools()]
        if name in plugin_names:
            return await dispatch_plugin_tool(name, args)
        raise ValueError(f"Unknown tool: {name}")


# ── Server Factory ───────────────────────────────────────────────────────

def create_server() -> Server:
    """Create and configure the MCP server with all available tools."""
    server = Server("screen-agent")

    # Start input guardian for user-priority safety
    guardian = get_guardian()
    guardian.start()

    @server.list_tools()
    async def handle_list_tools() -> list[Tool]:
        from screen_agent.plugins import get_plugin_tools

        return TOOLS + get_plugin_tools()

    @server.call_tool()
    async def handle_call_tool(
        name: str,
        arguments: dict | None,
    ) -> list[TextContent | ImageContent]:
        args = arguments or {}
        verify = args.pop("verify", False)
        logger.debug("Tool call: %s(%s)", name, args)
        try:
            result = await _dispatch(name, args)
            if verify and name in _INPUT_TOOLS:
                import asyncio as _asyncio
                await _asyncio.sleep(0.3)
                screenshot = await capture_screen()
                result.append(ImageContent(
                    type="image",
                    data=screenshot["image_base64"],
                    mimeType=screenshot["mime_type"],
                ))
                result.append(TextContent(
                    type="text",
                    text=f"Verification: {screenshot['width']}x{screenshot['height']}px",
                ))
            return result
        except Exception as e:
            logger.exception("Tool %s failed", name)
            return [TextContent(type="text", text=f"Error: {e}")]

    return server
