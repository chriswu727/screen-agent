"""CLI entry point for screen-agent."""

from __future__ import annotations

import asyncio
import logging
import sys

import typer

app = typer.Typer(
    name="screen-agent",
    help="Give AI coding tools eyes and hands. An MCP server for screen perception.",
    no_args_is_help=True,
)


@app.command()
def serve(
    transport: str = typer.Option(
        "stdio",
        help="MCP transport: stdio or sse",
    ),
    port: int = typer.Option(
        8765,
        help="Port for SSE transport",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable debug logging",
    ),
) -> None:
    """Start the MCP server.

    Default transport is stdio, which works directly with Claude Code
    and other MCP clients. Use --transport sse for HTTP-based clients.
    """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    from screen_agent.mcp.server import create_server

    server = create_server()

    if transport == "stdio":
        from mcp.server.stdio import stdio_server

        async def run_stdio():
            async with stdio_server() as (read_stream, write_stream):
                await server.run(
                    read_stream,
                    write_stream,
                    server.create_initialization_options(),
                )

        asyncio.run(run_stdio())

    elif transport == "sse":
        import uvicorn
        from mcp.server.sse import SseServerTransport
        from starlette.applications import Starlette
        from starlette.routing import Mount, Route

        sse = SseServerTransport("/messages/")

        async def handle_sse(request):
            async with sse.connect_sse(
                request.scope, request.receive, request._send
            ) as streams:
                await server.run(
                    streams[0], streams[1],
                    server.create_initialization_options(),
                )

        starlette_app = Starlette(
            routes=[
                Route("/sse", endpoint=handle_sse),
                Mount("/messages/", app=sse.handle_post_message),
            ],
        )
        uvicorn.run(starlette_app, host="0.0.0.0", port=port)

    else:
        typer.echo(f"Unknown transport: {transport}", err=True)
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version."""
    from screen_agent import __version__

    typer.echo(f"screen-agent v{__version__}")


@app.command()
def check() -> None:
    """Check system capabilities and permissions."""
    import platform

    typer.echo(f"Platform:  {platform.system()} {platform.machine()}")
    typer.echo(f"Python:    {sys.version.split()[0]}")

    # Check core dependencies
    checks = [
        ("mss", "Screen capture"),
        ("pyautogui", "Input control"),
        ("PIL", "Image processing"),
        ("mcp", "MCP protocol"),
    ]
    for mod, desc in checks:
        try:
            __import__(mod)
            typer.echo(f"  [OK]  {desc} ({mod})")
        except ImportError:
            typer.echo(f"  [MISSING]  {desc} ({mod})")

    # Check input backends
    typer.echo("\nInput backends:")
    backends_info = [
        ("Accessibility (AX)", "ApplicationServices", "Semantic UI actions"),
        ("CGEvent", "Quartz", "Native event injection"),
        ("pyautogui", "pyautogui", "Cross-platform fallback"),
    ]
    for name, mod, desc in backends_info:
        try:
            __import__(mod)
            typer.echo(f"  [OK]  {name} — {desc}")
        except ImportError:
            typer.echo(f"  [--]  {name} — {desc} (not installed)")

    # Check OCR
    typer.echo("\nOCR:")
    if platform.system() == "Darwin":
        try:
            __import__("Vision")
            typer.echo("  [OK]  Apple Vision Framework")
        except ImportError:
            typer.echo("  [--]  Apple Vision (pip install pyobjc-framework-Vision)")
    else:
        typer.echo("  [--]  No OCR available on this platform")

    # Platform notes
    typer.echo("\nPlatform notes:")
    if platform.system() == "Darwin":
        typer.echo("  macOS: Grant Screen Recording & Accessibility permissions in")
        typer.echo("         System Settings > Privacy & Security")
    elif platform.system() == "Linux":
        typer.echo("  Linux: Install wmctrl for window management")
