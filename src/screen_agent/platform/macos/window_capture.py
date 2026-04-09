"""macOS window-targeted capture via CGWindowListCreateImage.

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


def _find_window_sync(app: str | None = None, title: str | None = None) -> dict | None:
    """Find a window by app name and/or title. Returns CGWindow info dict."""
    import Quartz

    # kCGWindowListOptionAll finds windows on ALL Spaces (critical for background testing)
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


def _capture_window_sync(window_id: int) -> bytes | None:
    """Capture a specific window by ID. Returns JPEG bytes."""
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

    provider = Quartz.CGImageGetDataProvider(cg_image)
    data = Quartz.CGDataProviderCopyData(provider)
    bpr = Quartz.CGImageGetBytesPerRow(cg_image)

    img = Image.frombytes("RGBA", (width, height), bytes(data), "raw", "BGRA", bpr, 1)
    img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _get_window_bounds_sync(window_id: int) -> Region | None:
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


def _is_on_current_space(window_id: int) -> bool:
    """Check if a window is on the currently active Space."""
    import Quartz
    on_screen = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly,
        Quartz.kCGNullWindowID,
    )
    return any(w.get("kCGWindowNumber") == window_id for w in (on_screen or []))


def _bring_to_current_space(app_name: str) -> None:
    """Bring app to current Space by activating then immediately deactivating.

    macOS moves all windows of an app to the current Space when activated.
    We then re-activate the previous frontmost app so the user's workflow
    is minimally disrupted (~300ms flicker).
    """
    import subprocess, time

    # Get current frontmost app
    prev = subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to name of first process whose frontmost is true'],
        capture_output=True, text=True, timeout=5,
    )
    prev_app = prev.stdout.strip()

    # Activate target app (brings windows to current Space)
    subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to activate'],
        capture_output=True, timeout=5,
    )
    time.sleep(0.3)

    # Reactivate previous app so user stays in their workflow
    if prev_app and prev_app != app_name:
        subprocess.run(
            ["osascript", "-e", f'tell application "{prev_app}" to activate'],
            capture_output=True, timeout=5,
        )

    logger.info("Brought %s to current Space (was on different Space)", app_name)


class MacOSWindowCaptureBackend:
    """Window-targeted capture for macOS via Quartz."""

    async def find_window(self, app: str | None = None, title: str | None = None) -> dict | None:
        return await asyncio.to_thread(_find_window_sync, app, title)

    async def capture_window(self, window_id: int) -> bytes | None:
        return await asyncio.to_thread(_capture_window_sync, window_id)

    async def get_window_bounds(self, window_id: int) -> Region | None:
        return await asyncio.to_thread(_get_window_bounds_sync, window_id)

    async def ensure_on_current_space(self, window_id: int, app_name: str) -> None:
        """Ensure window is on current Space. Brings it here if not."""
        on_space = await asyncio.to_thread(_is_on_current_space, window_id)
        if not on_space:
            await asyncio.to_thread(_bring_to_current_space, app_name)
