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
    from screen_agent.engine.window_session import get_active
    status = ctx().guardian.get_status()
    status["input_backends"] = ctx().input_chain.backend_names
    status["backend_stats"] = ctx().input_chain.stats_summary()
    status["ocr_available"] = ctx().ocr is not None and ctx().ocr.available()
    ws = get_active()
    status["window_scope"] = {
        "active": ws is not None,
        "app": ws.app if ws else None,
        "title": ws.title if ws else None,
        "window_id": ws.window_id if ws else None,
    }
    return _text(status)


# ── Window Scope Handlers ────────────────────────────────────────

@handler("window_scope")
async def handle_window_scope(args: dict) -> ContentList:
    """Lock all operations to a specific window. Frees the user's screen.

    For Chrome/Electron: if CDP port is available, uses Chrome DevTools Protocol
    for true cross-Space background testing (no macOS window server dependency).
    Otherwise falls back to CGWindowListCreateImage (same-Space only).
    """
    from screen_agent.platform import get_window_capture_backend
    from screen_agent.engine.window_session import WindowSession, set_active, set_cdp_session

    app = args.get("app")
    title = args.get("title")
    cdp_port = args.get("cdp_port", 9222)
    if not app and not title:
        return _text({"error": "Provide at least 'app' or 'title' to identify the window"})

    # Try CDP first (works across Spaces, zero screen disruption)
    is_chrome = app and ("chrome" in app.lower() or "electron" in app.lower())
    if is_chrome or args.get("use_cdp"):
        try:
            from screen_agent.platform.cdp.session import create_cdp_session
            cdp_session = await create_cdp_session(
                port=cdp_port,
                url_contains=args.get("url"),
                title_contains=title,
            )
            if cdp_session:
                set_cdp_session(cdp_session)
                return _text({
                    "status": "scoped",
                    "mode": "cdp",
                    "title": cdp_session.title,
                    "viewport": {"width": cdp_session.width, "height": cdp_session.height},
                    "info": "Connected via Chrome DevTools Protocol — full cross-Space support",
                })
        except Exception as e:
            logger.info("CDP not available (%s), falling back to window capture", e)

    # Fallback: CGWindowListCreateImage (same-Space only)
    backend = get_window_capture_backend()
    if backend is None:
        return _text({"error": "Window capture not available on this platform"})

    info = await backend.find_window(app=app, title=title)
    if not info:
        return _text({"error": f"Window not found: app={app}, title={title}"})

    bounds = Region(
        x=int(info["bounds"].get("X", 0)),
        y=int(info["bounds"].get("Y", 0)),
        width=int(info["bounds"].get("Width", 0)),
        height=int(info["bounds"].get("Height", 0)),
    )
    session = WindowSession(
        window_id=info["window_id"],
        app=info["app"],
        title=info["title"],
        bounds=bounds,
    )
    set_active(session)

    return _text({
        "status": "scoped",
        "mode": "window_capture",
        "window_id": info["window_id"],
        "app": info["app"],
        "title": info["title"],
        "bounds": {"x": bounds.x, "y": bounds.y, "width": bounds.width, "height": bounds.height},
        "info": "Using CGWindowListCreateImage — window must be on same Space",
    })


@handler("window_release")
async def handle_window_release(args: dict) -> ContentList:
    """Release window scope. Operations return to full-screen mode."""
    from screen_agent.engine.window_session import set_active, set_cdp_session, get_cdp_session
    cdp = get_cdp_session()
    if cdp:
        await cdp.close()
        set_cdp_session(None)
    set_active(None)
    return _text({"status": "released", "mode": "full_screen"})


# ── Interact Handler ─────────────────────────────────────────────

async def _capture_for_interact() -> tuple[bytes, int, int]:
    """Capture screen (or scoped window/CDP) and return raw image bytes + dimensions."""
    from screen_agent.engine.window_session import get_current_session
    session = get_current_session()
    if session:
        result = await session.capture()
        if result is None:
            raise CaptureError("Capture failed — window may have closed or CDP disconnected")
    else:
        result = await ctx().capture.capture(resize=False)
    image_data = base64.b64decode(result["image_base64"])
    return image_data, result["width"], result["height"]


@handler("interact")
async def handle_interact(args: dict) -> ContentList:
    """Find an element by text and interact with it — one MCP call.

    Replaces the typical: capture_screen → find_text → click → type_text → capture_screen
    pipeline with a single server-side operation.

    In CDP mode: click/type go directly through Chrome's input pipeline.
    In window mode: coordinates are translated and sent via CGEvent.
    """
    from screen_agent.engine.window_session import get_active, get_cdp_session, get_current_session

    if not ctx().ocr or not ctx().ocr.available():
        return _text({"error": "OCR not available — needed for interact"})

    target = args["target"]
    action = args.get("action", "click")
    text = args.get("text", "")
    lang = args.get("lang") or _detect_lang(target)

    # 1. Capture
    image_data, img_w, img_h = await _capture_for_interact()

    # 2. OCR find target
    blocks = await ctx().ocr.recognize(image_data, lang=lang)
    query = target.lower()
    matches = [b for b in blocks if query in b.text.lower()]
    if not matches:
        raise ElementNotFoundError(target)

    element = matches[args.get("index", 0)]
    click_point = element.center

    # 3. Route to CDP or CGEvent
    cdp = get_cdp_session()
    ws = get_active()

    if cdp:
        # CDP mode: coordinates are page-relative, no translation needed
        pass
    elif ws:
        # Window mode: translate to screen coordinates
        click_point = ws.window_to_screen(click_point)

    # 4. Execute
    await _guardian_check(click_point)

    result_details = {"target": element.text, "at": {"x": click_point.x, "y": click_point.y}}

    if cdp:
        # CDP path: direct Chrome input, no CGEvent
        if action in ("click", "click_and_type"):
            ok = await cdp.click(click_point)
            result_details["click"] = {"success": ok, "backend": "cdp"}

        if action in ("type", "click_and_type"):
            if not text:
                return _text({"error": "action requires 'text' parameter"})
            await asyncio.sleep(0.1)
            ok = await cdp.type_text(text)
            result_details["type"] = {"success": ok, "backend": "cdp"}

    else:
        # CGEvent path
        await _guardian_check(click_point)

        if action in ("click", "click_and_type"):
            click_result = await ctx().input_chain.click(click_point)
            result_details["click"] = {"success": click_result.success, "backend": click_result.backend_used}

        if action in ("type", "click_and_type"):
            if not text:
                return _text({"error": "action requires 'text' parameter"})
            await asyncio.sleep(0.1)
            type_result = await ctx().input_chain.type_text(text)
            result_details["type"] = {"success": type_result.success, "backend": type_result.backend_used}

    result_details["action"] = action
    result_details["success"] = True

    content = _text(result_details)
    if args.get("verify"):
        content.extend(await _verify_screenshot())
    return content


# ── Vision-First Handlers ────────────────────────────────────────

@handler("act")
async def handle_act(args: dict) -> ContentList:
    """Vision-first interaction.

    Without coordinates: returns screenshot for the LLM to analyze visually.
    With coordinates: executes the action at (x, y).

    The LLM SEES the screenshot and decides where to click — no OCR needed.
    This is the key differentiator from Playwright-style tools.
    """
    from screen_agent.engine.window_session import get_cdp_session, get_active

    action = args.get("action", "screenshot")

    # Screenshot-only mode: return image for LLM to analyze
    if action == "screenshot" or ("x" not in args and "y" not in args):
        image_data, img_w, img_h = await _capture_for_interact()
        result = {
            "image_base64": base64.b64encode(image_data).decode("ascii"),
            "width": img_w,
            "height": img_h,
        }
        return [
            ImageContent(
                type="image",
                data=result["image_base64"],
                mimeType="image/jpeg",
            ),
            TextContent(
                type="text",
                text=json.dumps({
                    "width": img_w, "height": img_h,
                    "hint": "Look at this screenshot. Decide where to click based on what you SEE.",
                }),
            ),
        ]

    # Action mode: execute at (x, y)
    point = _parse_point(args)
    text = args.get("text", "")
    cdp = get_cdp_session()
    ws = get_active()

    result_details: dict = {"at": {"x": point.x, "y": point.y}}

    if cdp:
        if action in ("click", "click_and_type"):
            await cdp.click(point)
            result_details["click"] = {"backend": "cdp"}
        if action in ("type", "click_and_type"):
            if not text:
                return _text({"error": "action requires 'text' parameter"})
            await asyncio.sleep(0.1)
            await cdp.type_text(text)
            result_details["type"] = {"backend": "cdp"}
    else:
        screen_point = ws.window_to_screen(point) if ws else point
        await _guardian_check(screen_point)
        if action in ("click", "click_and_type"):
            r = await ctx().input_chain.click(screen_point)
            result_details["click"] = {"backend": r.backend_used}
        if action in ("type", "click_and_type"):
            if not text:
                return _text({"error": "action requires 'text' parameter"})
            await asyncio.sleep(0.1)
            r = await ctx().input_chain.type_text(text)
            result_details["type"] = {"backend": r.backend_used}

    result_details["action"] = action
    result_details["success"] = True

    # Always return a screenshot after action so LLM can verify visually
    content = _text(result_details)
    image_data, img_w, img_h = await _capture_for_interact()
    content.append(ImageContent(
        type="image",
        data=base64.b64encode(image_data).decode("ascii"),
        mimeType="image/jpeg",
    ))
    return content


@handler("eval_js")
async def handle_eval_js(args: dict) -> ContentList:
    """Execute JavaScript via CDP. Returns the result."""
    from screen_agent.engine.window_session import get_cdp_session

    cdp = get_cdp_session()
    if not cdp:
        return _text({"error": "eval_js requires CDP mode. Call window_scope with a Chrome app first."})

    expression = args["expression"]
    try:
        result = await cdp.evaluate(expression)
        return _text({"result": result, "expression": expression})
    except Exception as e:
        return _text({"error": str(e), "expression": expression})
