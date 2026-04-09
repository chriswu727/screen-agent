"""Window-scoped test session.

Locks all capture/input operations to a specific window ID.
The window can be behind other windows — the user's screen stays free.
Uses the platform-appropriate WindowCaptureBackend (macOS/Windows/Linux).
"""

from __future__ import annotations

import base64
import logging

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
        """Capture this window's content via the platform backend."""
        from screen_agent.platform import get_window_capture_backend

        backend = get_window_capture_backend()
        if backend is None:
            logger.error("No window capture backend available on this platform")
            return None

        # Refresh bounds (window may have moved)
        new_bounds = await backend.get_window_bounds(self.window_id)
        if new_bounds:
            self.bounds = new_bounds

        jpeg_bytes = await backend.capture_window(self.window_id)
        if jpeg_bytes is None:
            return None

        # Decode to get dimensions
        from PIL import Image
        from io import BytesIO
        img = Image.open(BytesIO(jpeg_bytes))
        w, h = img.size

        data = base64.standard_b64encode(jpeg_bytes).decode("ascii")
        return {
            "image_base64": data,
            "mime_type": "image/jpeg",
            "width": w,
            "height": h,
            "scale_factor": 1.0,
        }


def get_active() -> WindowSession | None:
    return _active


def set_active(session: WindowSession | None) -> None:
    global _active
    _active = session
