"""Plugin system for optional CV-powered tools.

Plugins are auto-discovered based on available dependencies.
If a dependency isn't installed, its tools are simply not registered.
"""

from __future__ import annotations

import json
import logging

from mcp.types import ImageContent, TextContent, Tool

logger = logging.getLogger("screen-agent.plugins")

_plugin_tools: list[Tool] | None = None
_plugin_handlers: dict[str, object] = {}


def get_plugin_tools() -> list[Tool]:
    """Return tools from all available plugins."""
    global _plugin_tools
    if _plugin_tools is not None:
        return _plugin_tools

    _plugin_tools = []

    # OCR plugin
    try:
        from screen_agent.plugins.ocr import OCR_TOOLS, ocr_instance

        _plugin_tools.extend(OCR_TOOLS)
        _plugin_handlers["ocr"] = ocr_instance
        logger.info("OCR plugin loaded")
    except ImportError:
        logger.debug("OCR plugin not available (install with: pip install screen-agent[ocr])")

    return _plugin_tools


async def dispatch_plugin_tool(
    name: str,
    args: dict,
) -> list[TextContent | ImageContent]:
    """Route a tool call to the appropriate plugin handler."""
    if name in ("ocr", "find_text", "click_text"):
        from screen_agent.plugins.ocr import handle_ocr_tool

        result = await handle_ocr_tool(name, args)
        return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]

    raise ValueError(f"Unknown plugin tool: {name}")
