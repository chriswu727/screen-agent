"""Window-targeted screen capture via CGWindowListCreateImage.

Captures a specific window by ID — even if occluded, behind other windows,
or on a different Space. This frees the user's physical screen during testing.
"""

from __future__ import annotations

import asyncio
import logging
from io import BytesIO

from PIL import Image

from screen_agent.types import Region

logger = logging.getLogger(__name__)


def _find_window(app: str | None = None, title: str | None = None) -> dict | None:
    """Find a window by app name and/or title. Returns CGWindow info dict."""
    import Quartz

    # Use kCGWindowListOptionAll to find windows on ALL Spaces,
    # not just the current one. This is critical for background testing.
    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    )
    if not windows:
        return None

    for w in windows:
        owner = w.get("kCGWindowOwnerName", "")
        name = w.get("kCGWindowName", "")
        layer = w.get("kCGWindowLayer", 999)

        # Skip menu bar, dock, etc.
        if layer != 0:
            continue

        app_match = app is None or app.lower() in owner.lower()
        title_match = title is None or title.lower() in name.lower()

        if app_match and title_match:
            return {
                "window_id": w["kCGWindowNumber"],
                "app": owner,
                "title": name,
                "bounds": w.get("kCGWindowBounds", {}),
            }

    return None


def _capture_window_sync(window_id: int) -> Image.Image | None:
    """Capture a specific window by ID using CGWindowListCreateImage."""
    import Quartz

    cg_image = Quartz.CGWindowListCreateImage(
        Quartz.CGRectNull,
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
        Quartz.kCGWindowImageBoundsIgnoreFraming | Quartz.kCGWindowImageNominalResolution,
    )

    if cg_image is None:
        return None

    width = Quartz.CGImageGetWidth(cg_image)
    height = Quartz.CGImageGetHeight(cg_image)

    if width == 0 or height == 0:
        return None

    # Convert CGImage to PIL Image via raw bitmap data
    color_space = Quartz.CGImageGetColorSpace(cg_image)
    bpc = Quartz.CGImageGetBitsPerComponent(cg_image)
    bpr = Quartz.CGImageGetBytesPerRow(cg_image)

    provider = Quartz.CGImageGetDataProvider(cg_image)
    data = Quartz.CGDataProviderCopyData(provider)

    img = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA", bpr, 1)
    return img.convert("RGB")


async def find_window(app: str | None = None, title: str | None = None) -> dict | None:
    """Async wrapper for window lookup."""
    return await asyncio.to_thread(_find_window, app, title)


async def capture_window(window_id: int) -> Image.Image | None:
    """Async wrapper for window capture."""
    return await asyncio.to_thread(_capture_window_sync, window_id)


def get_window_bounds(window_id: int) -> Region | None:
    """Get a window's screen-space bounds."""
    import Quartz

    windows = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionIncludingWindow,
        window_id,
    )
    if not windows or len(windows) == 0:
        return None

    bounds = windows[0].get("kCGWindowBounds", {})
    return Region(
        x=int(bounds.get("X", 0)),
        y=int(bounds.get("Y", 0)),
        width=int(bounds.get("Width", 0)),
        height=int(bounds.get("Height", 0)),
    )
