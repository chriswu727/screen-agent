"""MCP tool dispatch handlers.

Each handler is a small function registered by name. No if/elif chain.
Handlers receive parsed arguments and return MCP content blocks.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from mcp.types import ImageContent, TextContent

from screen_agent.errors import (
    CoordinateOutOfBoundsError,
    ElementNotFoundError,
    GuardianBlockedError,
    ScreenAgentError,
)
from screen_agent.types import Point, Region

if TYPE_CHECKING:
    from screen_agent.engine.guardian import InputGuardian
    from screen_agent.engine.input_chain import InputChain
    from screen_agent.platform.protocols import CaptureBackend, OCRBackend, WindowBackend

logger = logging.getLogger(__name__)

ContentList = list[TextContent | ImageContent]
HandlerFunc = Callable[[dict], Awaitable[ContentList]]

# Handler registry
_handlers: dict[str, HandlerFunc] = {}


def handler(name: str):
    """Decorator to register a tool handler."""
    def decorator(func: HandlerFunc) -> HandlerFunc:
        _handlers[name] = func
        return func
    return decorator


def get_handler(name: str) -> HandlerFunc | None:
    return _handlers.get(name)


def _text(data: Any) -> ContentList:
    """Helper to return a single text content block."""
    if isinstance(data, str):
        return [TextContent(type="text", text=data)]
    return [TextContent(type="text", text=json.dumps(data, ensure_ascii=False))]


def _error(err: ScreenAgentError) -> ContentList:
    """Return structured error response."""
    return _text({"error": err.to_dict()})


class HandlerContext:
    """Dependencies injected into handlers."""

    def __init__(
        self,
        input_chain: InputChain,
        capture: CaptureBackend,
        window: WindowBackend,
        guardian: InputGuardian,
        ocr: OCRBackend | None = None,
    ):
        self.input_chain = input_chain
        self.capture = capture
        self.window = window
        self.guardian = guardian
        self.ocr = ocr


# Global context, set during server startup
_ctx: HandlerContext | None = None


def set_context(context: HandlerContext) -> None:
    global _ctx
    _ctx = context


def ctx() -> HandlerContext:
    if _ctx is None:
        raise RuntimeError("HandlerContext not initialized — server setup incomplete")
    return _ctx


def _parse_point(args: dict, x_key: str = "x", y_key: str = "y") -> Point:
    """Parse and validate coordinate arguments."""
    try:
        x = int(args[x_key])
        y = int(args[y_key])
    except (KeyError, TypeError, ValueError) as e:
        raise CoordinateOutOfBoundsError(
            args.get(x_key, 0), args.get(y_key, 0),
            reason=f"Invalid coordinates: {e}",
        ) from e
    if x < 0 or y < 0:
        raise CoordinateOutOfBoundsError(x, y, reason="Coordinates must be non-negative")
    return Point(x, y)


def _parse_region(args: dict, key: str = "region") -> Region | None:
    """Parse and validate an optional region argument."""
    r = args.get(key)
    if not r:
        return None
    try:
        return Region(x=int(r["x"]), y=int(r["y"]), width=int(r["width"]), height=int(r["height"]))
    except (KeyError, TypeError, ValueError) as e:
        raise CoordinateOutOfBoundsError(
            r.get("x", 0), r.get("y", 0),
            reason=f"Invalid region: {e}",
        ) from e


def _detect_lang(text: str) -> str:
    """Auto-detect OCR language from query text.

    Uses Unicode block detection. Kanji/Hanzi overlap between Chinese and
    Japanese is resolved by checking for kana first (Japanese-specific).
    Returns "zh" (not "zh-Hans") so the Vision backend tries both
    Simplified and Traditional Chinese.
    """
    # Japanese kana (unique to Japanese) — check before CJK ideographs
    if re.search(r'[\u3040-\u309f\u30a0-\u30ff\u31f0-\u31ff\uff65-\uff9f]', text):
        return "ja"
    # CJK Ideographs (shared by Chinese/Japanese/Korean, treat as Chinese)
    if re.search(r'[\u3400-\u9fff\uf900-\ufaff]', text):
        return "zh"
    # Korean Hangul
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    return "en"


async def _guardian_check(point: Point | None = None) -> None:
    """Check guardian clearance. Raises GuardianBlockedError if blocked."""
    result = await ctx().guardian.wait_for_clearance(point=point)
    if not result.allowed:
        raise GuardianBlockedError(result.reason, ctx().guardian.get_status())


async def _verify_screenshot() -> list[ImageContent]:
    """Capture a verification screenshot after an action."""
    await asyncio.sleep(0.3)
    result = await ctx().capture.capture()
    return [
        ImageContent(
            type="image",
            data=result["image_base64"],
            mimeType=result["mime_type"],
        ),
        TextContent(
            type="text",
            text=f"Verification: {result['width']}x{result['height']}px",
        ),
    ]


# ── Perception Handlers ───────────────────────────────────────────

@handler("capture_screen")
async def handle_capture_screen(args: dict) -> ContentList:
    region = _parse_region(args)
    result = await ctx().capture.capture(region)
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


@handler("list_windows")
async def handle_list_windows(args: dict) -> ContentList:
    windows = await ctx().window.list_windows()
    data = [
        {"app": w.app, "title": w.title, "x": w.x, "y": w.y,
         "width": w.width, "height": w.height}
        for w in windows
    ]
    return _text(data)


@handler("get_active_window")
async def handle_get_active_window(args: dict) -> ContentList:
    win = await ctx().window.get_active_window()
    if win:
        return _text({"app": win.app, "title": win.title, "pid": win.pid})
    return _text({"error": "No active window found"})


@handler("get_cursor_position")
async def handle_get_cursor_position(args: dict) -> ContentList:
    try:
        import pyautogui
        pos = pyautogui.position()
        return _text({"x": pos[0], "y": pos[1]})
    except Exception as e:
        return _text({"error": str(e)})


# ── Input Handlers ────────────────────────────────────────────────

@handler("click")
async def handle_click(args: dict) -> ContentList:
    point = _parse_point(args)
    await _guardian_check(point)
    result = await ctx().input_chain.click(
        point, button=args.get("button", "left"), clicks=args.get("clicks", 1),
    )
    content = _text({"action": "click", **asdict(result)})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


@handler("type_text")
async def handle_type_text(args: dict) -> ContentList:
    await _guardian_check()
    text = args.get("text", "")
    if not text:
        return _text({"error": "Empty text"})
    result = await ctx().input_chain.type_text(text)
    content = _text({"action": "type_text", **asdict(result)})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


@handler("press_key")
async def handle_press_key(args: dict) -> ContentList:
    await _guardian_check()
    result = await ctx().input_chain.press_key(
        args["key"], modifiers=args.get("modifiers"),
    )
    content = _text({"action": "press_key", **asdict(result)})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


@handler("scroll")
async def handle_scroll(args: dict) -> ContentList:
    point = None
    if "x" in args and "y" in args:
        point = _parse_point(args)
    await _guardian_check(point)
    result = await ctx().input_chain.scroll(args["amount"], point)
    content = _text({"action": "scroll", **asdict(result)})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


@handler("move_mouse")
async def handle_move_mouse(args: dict) -> ContentList:
    point = _parse_point(args)
    await _guardian_check(point)
    result = await ctx().input_chain.move(point)
    content = _text({"action": "move", **asdict(result)})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


@handler("drag")
async def handle_drag(args: dict) -> ContentList:
    start = _parse_point(args, "start_x", "start_y")
    end = _parse_point(args, "end_x", "end_y")
    await _guardian_check(start)
    result = await ctx().input_chain.drag(start, end, button=args.get("button", "left"))
    content = _text({"action": "drag", **asdict(result)})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


@handler("focus_window")
async def handle_focus_window(args: dict) -> ContentList:
    await _guardian_check()
    success = await ctx().window.focus_window(args["title"])
    content = _text({"success": success, "title": args["title"]})
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


# ── OCR Handlers ──────────────────────────────────────────────────

@handler("ocr")
async def handle_ocr(args: dict) -> ContentList:
    if not ctx().ocr or not ctx().ocr.available():
        return _text({"error": "OCR not available on this system"})

    region = _parse_region(args)

    # Capture screenshot first
    result = await ctx().capture.capture(region, resize=False)
    image_data = base64.b64decode(result["image_base64"])

    blocks = await ctx().ocr.recognize(image_data, lang=args.get("lang", "en"))
    return _text([
        {"text": b.text, "confidence": b.confidence,
         "bbox": {"x": b.bbox.x, "y": b.bbox.y, "width": b.bbox.width, "height": b.bbox.height},
         "center": {"x": b.center.x, "y": b.center.y}}
        for b in blocks
    ])


@handler("find_text")
async def handle_find_text(args: dict) -> ContentList:
    if not ctx().ocr or not ctx().ocr.available():
        return _text({"error": "OCR not available on this system"})

    result = await ctx().capture.capture(resize=False)
    image_data = base64.b64decode(result["image_base64"])

    lang = args.get("lang") or _detect_lang(args["query"])
    blocks = await ctx().ocr.recognize(image_data, lang=lang)
    query = args["query"].lower()
    matches = [b for b in blocks if query in b.text.lower()]
    if not matches:
        return _text({"error": f"Text '{args['query']}' not found on screen"})
    return _text([
        {"text": m.text, "center": {"x": m.center.x, "y": m.center.y},
         "bbox": {"x": m.bbox.x, "y": m.bbox.y, "width": m.bbox.width, "height": m.bbox.height}}
        for m in matches
    ])


@handler("click_text")
async def handle_click_text(args: dict) -> ContentList:
    if not ctx().ocr or not ctx().ocr.available():
        return _text({"error": "OCR not available on this system"})

    result = await ctx().capture.capture(resize=False)
    image_data = base64.b64decode(result["image_base64"])

    lang = args.get("lang") or _detect_lang(args["query"])
    blocks = await ctx().ocr.recognize(image_data, lang=lang)
    query = args["query"].lower()
    matches = [b for b in blocks if query in b.text.lower()]
    if not matches:
        raise ElementNotFoundError(args["query"])

    idx = args.get("index", 0)
    if idx < 0 or idx >= len(matches):
        raise ElementNotFoundError(
            f"{args['query']} (index {idx} out of range, {len(matches)} matches found)"
        )
    target = matches[idx]

    await _guardian_check(target.center)
    click_result = await ctx().input_chain.click(
        target.center, button=args.get("button", "left"),
    )
    return _text({
        "clicked": target.text,
        "at": {"x": target.center.x, "y": target.center.y},
        **asdict(click_result),
    })


# ── Guardian Handlers ─────────────────────────────────────────────

@handler("add_app")
async def handle_add_app(args: dict) -> ContentList:
    ctx().guardian.add_app(args["app_name"])
    return _text(ctx().guardian.get_status())


@handler("remove_app")
async def handle_remove_app(args: dict) -> ContentList:
    ctx().guardian.remove_app(args["app_name"])
    return _text(ctx().guardian.get_status())


@handler("set_region")
async def handle_set_region(args: dict) -> ContentList:
    if "x" in args and "y" in args and "width" in args and "height" in args:
        region = Region(x=args["x"], y=args["y"], width=args["width"], height=args["height"])
    else:
        region = None
    ctx().guardian.set_region(region)
    return _text(ctx().guardian.get_status())


@handler("clear_scope")
async def handle_clear_scope(args: dict) -> ContentList:
    ctx().guardian.clear_scope()
    return _text(ctx().guardian.get_status())


@handler("get_agent_status")
async def handle_get_agent_status(args: dict) -> ContentList:
    status = ctx().guardian.get_status()
    status["input_backends"] = ctx().input_chain.backend_names
    status["backend_stats"] = ctx().input_chain.stats_summary()
    status["ocr_available"] = ctx().ocr is not None and ctx().ocr.available()
    return _text(status)
