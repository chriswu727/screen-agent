"""Window-scoped test session.

Locks all capture/input operations to a specific window ID.
The window can be behind other windows — the user's screen stays free.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from io import BytesIO

from PIL import Image

from screen_agent.types import Point, Region

logger = logging.getLogger(__name__)

# Global active window session
_active: WindowSession | None = None


class WindowSession:
    """Binds screen agent operations to a specific window."""

    def __init__(self, window_id: int, app: str, title: str, bounds: Region):
        self.window_id = window_id
        self.app = app
        self.title = title
        self.bounds = bounds

    def window_to_screen(self, point: Point) -> Point:
        """Convert window-relative coordinates to screen-absolute."""
        return Point(self.bounds.x + point.x, self.bounds.y + point.y)

    async def capture(self) -> dict | None:
        """Capture this window's content, return same format as CaptureBackend."""
        from screen_agent.platform.macos.window_capture import capture_window, get_window_bounds

        # Refresh bounds (window may have moved)
        new_bounds = await asyncio.to_thread(get_window_bounds, self.window_id)
        if new_bounds:
            self.bounds = new_bounds

        img = await capture_window(self.window_id)
        if img is None:
            return None

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=75)
        data = base64.standard_b64encode(buf.getvalue()).decode("ascii")

        return {
            "image_base64": data,
            "mime_type": "image/jpeg",
            "width": img.size[0],
            "height": img.size[1],
            "scale_factor": 1.0,
        }


def get_active() -> WindowSession | None:
    return _active


def set_active(session: WindowSession | None) -> None:
    global _active
    _active = session
