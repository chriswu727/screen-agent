"""Window-scoped test session.

Two modes:
1. WindowSession — CGWindowListCreateImage + CGEvent (same Space, any app)
2. CDPSession — Chrome DevTools Protocol (any Space, Chrome/Electron only)

The handler picks the right mode automatically.
"""

from __future__ import annotations

import base64
import logging
from typing import TYPE_CHECKING

from screen_agent.types import Point, Region

if TYPE_CHECKING:
    from screen_agent.platform.cdp.session import CDPSession

logger = logging.getLogger(__name__)

# Global state
_active: WindowSession | None = None
_cdp: CDPSession | None = None


class WindowSession:
    """Binds operations to a specific window via CGWindowListCreateImage."""

    def __init__(self, window_id: int, app: str, title: str, bounds: Region, pid: int = 0):
        self.window_id = window_id
        self.app = app
        self.title = title
        self.bounds = bounds
        self.pid = pid

    def window_to_screen(self, point: Point) -> Point:
        """Convert window-relative coordinates to screen-absolute."""
        return Point(self.bounds.x + point.x, self.bounds.y + point.y)

    async def capture(self) -> dict | None:
        from screen_agent.platform import get_window_capture_backend

        backend = get_window_capture_backend()
        if backend is None:
            return None

        new_bounds = await backend.get_window_bounds(self.window_id)
        if new_bounds:
            self.bounds = new_bounds

        jpeg_bytes = await backend.capture_window(self.window_id)
        if jpeg_bytes is None:
            return None

        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(jpeg_bytes))

        return {
            "image_base64": base64.standard_b64encode(jpeg_bytes).decode("ascii"),
            "mime_type": "image/jpeg",
            "width": img.size[0],
            "height": img.size[1],
            "scale_factor": 1.0,
        }


# ── Global accessors ──

def get_active() -> WindowSession | None:
    return _active

def set_active(session: WindowSession | None) -> None:
    global _active
    _active = session

def get_cdp_session() -> CDPSession | None:
    return _cdp

def set_cdp_session(session: CDPSession | None) -> None:
    global _cdp
    _cdp = session

def get_current_session():
    """Return whichever session is active (CDP preferred over WindowSession)."""
    return _cdp or _active
