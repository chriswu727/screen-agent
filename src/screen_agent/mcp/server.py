"""MCP server factory.

Thin entry point: wires up all layers and starts serving.
All logic lives in handlers.py and the engine/platform layers.
"""

from __future__ import annotations

import logging

from mcp.server import Server

from screen_agent.config import ScreenAgentConfig
from screen_agent.engine.guardian import InputGuardian
from screen_agent.engine.input_chain import InputChain
from screen_agent.mcp.handlers import (
    HandlerContext,
    _error,
    _text,
    get_handler,
    set_context,
)
from screen_agent.mcp.tools import TOOLS
from screen_agent.platform import (
    get_capture_backend,
    get_input_backends,
    get_ocr_backend,
    get_window_backend,
)

logger = logging.getLogger(__name__)


def create_server(config: ScreenAgentConfig | None = None) -> Server:
    """Create and configure the MCP server with all dependencies wired."""
    config = config or ScreenAgentConfig.from_env()

    # Set up logging
    logging.basicConfig(
        level=getattr(logging, config.log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Initialize platform backends
    input_backends = get_input_backends(config)
    capture = get_capture_backend()
    window = get_window_backend()
    ocr = get_ocr_backend()

    # Initialize engine
    input_chain = InputChain(input_backends)
    guardian = InputGuardian(config.guardian)
    guardian.start()

    # Wire up handler context
    set_context(HandlerContext(
        input_chain=input_chain,
        capture=capture,
        window=window,
        guardian=guardian,
        ocr=ocr,
    ))

    # Create MCP server
    server = Server("screen-agent")

    @server.list_tools()
    async def list_tools():
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        handler = get_handler(name)
        if handler is None:
            return _text({"error": {"code": "UNKNOWN_TOOL", "message": f"Unknown tool: {name}"}})

        try:
            return await handler(arguments or {})
        except Exception as e:
            from screen_agent.errors import ScreenAgentError

            if isinstance(e, ScreenAgentError):
                logger.warning("Tool '%s' blocked: %s", name, e)
                return _error(e)
            logger.exception("Tool '%s' failed unexpectedly", name)
            return _text({"error": {"code": "INTERNAL_ERROR", "message": str(e)}})

    logger.info(
        "Screen Agent MCP server ready — %d tools, %d input backends: %s",
        len(TOOLS),
        len(input_backends),
        [b.name for b in input_backends],
    )

    return server
