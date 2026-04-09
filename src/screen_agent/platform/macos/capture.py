"""macOS screen capture backend.

Uses mss for capture with Retina scale factor awareness.
All returned dimensions are in logical coordinates.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from io import BytesIO

import mss
from PIL import Image

from screen_agent.config import CaptureConfig
from screen_agent.errors import CaptureError
from screen_agent.platform.coords import get_coordinate_space
from screen_agent.types import Region, ScreenshotResult

logger = logging.getLogger(__name__)


class MacOSCaptureBackend:
    """Capture backend using mss with Retina awareness."""

    def __init__(self, config: CaptureConfig | None = None):
        self._config = config or CaptureConfig()

    async def capture(
        self, region: Region | None = None, resize: bool = True
    ) -> ScreenshotResult:
        """Capture the screen or a region.

        Coordinates in `region` are logical. The result dimensions
        are also logical. Image resize is intentionally skipped for
        LLM-facing captures to keep pixel positions aligned with
        screen coordinates. Use JPEG format for bandwidth reduction.
        """
        try:
            img = await asyncio.to_thread(self._grab_sync, region)
        except Exception as e:
            raise CaptureError(f"Screen capture failed: {e}") from e

        scale = self.get_scale_factor()

        # Convert physical pixel dimensions to logical
        logical_w = int(img.size[0] / scale)
        logical_h = int(img.size[1] / scale)

        if resize and max(img.size) > self._config.max_dimension:
            if scale > 1.0:
                # Retina: resize physical pixels back to logical size (no coord drift)
                img.thumbnail((logical_w, logical_h), Image.LANCZOS)
            else:
                # Non-Retina large screen (e.g. 4K at 1x): cap to max_dimension.
                # This introduces coordinate drift — image pixels no longer map
                # 1:1 to screen coordinates. The LLM must scale positions by
                # (logical_w / img_w). We report logical dims so the handler
                # can include the mapping info.
                img.thumbnail(
                    (self._config.max_dimension, self._config.max_dimension),
                    Image.LANCZOS,
                )

        data, mime = self._encode(img)

        return ScreenshotResult(
            image_base64=data,
            mime_type=mime,
            width=logical_w,
            height=logical_h,
            scale_factor=scale,
        )

    def get_scale_factor(self) -> float:
        """Return the display scale factor."""
        return get_coordinate_space().scale_factor

    def _grab_sync(self, region: Region | None = None) -> Image.Image:
        cs = get_coordinate_space()
        with mss.mss() as sct:
            if region:
                # Convert logical region to physical for mss
                phys = cs.logical_to_physical_region(region)
                monitor = {
                    "left": phys.x,
                    "top": phys.y,
                    "width": phys.width,
                    "height": phys.height,
                }
            else:
                monitor = sct.monitors[1]

            shot = sct.grab(monitor)
            return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

    def _encode(self, img: Image.Image) -> tuple[str, str]:
        buf = BytesIO()
        fmt = self._config.default_format.upper()
        if fmt == "JPEG":
            img.save(buf, format="JPEG", quality=self._config.jpeg_quality)
            mime = "image/jpeg"
        else:
            img.save(buf, format="PNG")
            mime = "image/png"
        data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
        return data, mime
