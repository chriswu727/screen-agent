"""Screen capture utilities.

Cross-platform screenshot capture using mss, with automatic
resizing to stay within LLM vision API limits.
"""

from __future__ import annotations

import asyncio
import base64
from io import BytesIO
from typing import TypedDict

import mss
from PIL import Image

# Max dimensions for LLM vision APIs (Anthropic caps at 1568px internally)
MAX_DIMENSION = 2000
JPEG_QUALITY = 80


class Region(TypedDict, total=False):
    x: int
    y: int
    width: int
    height: int


class ScreenshotResult(TypedDict):
    image_base64: str
    mime_type: str
    width: int
    height: int


def _grab_sync(region: Region | None = None) -> Image.Image:
    with mss.mss() as sct:
        if region:
            monitor = {
                "left": region.get("x", 0),
                "top": region.get("y", 0),
                "width": region["width"],
                "height": region["height"],
            }
        else:
            monitor = sct.monitors[1]  # Primary display

        shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _resize_if_needed(img: Image.Image) -> Image.Image:
    if max(img.size) <= MAX_DIMENSION:
        return img
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.LANCZOS)
    return img


def _encode(img: Image.Image, format: str = "PNG") -> tuple[str, str]:
    buf = BytesIO()
    if format.upper() == "JPEG":
        img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        mime = "image/png"

    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return data, mime


async def capture_screen(
    region: Region | None = None,
    format: str = "PNG",
    resize: bool = True,
) -> ScreenshotResult:
    """Capture a screenshot of the entire screen or a specific region.

    Returns base64-encoded image data suitable for LLM vision APIs.
    Images exceeding 2000px on any side are automatically downscaled
    unless resize=False (useful for OCR where pixel coordinates matter).
    """
    img = await asyncio.to_thread(_grab_sync, region)
    if resize:
        img = _resize_if_needed(img)
    data, mime = _encode(img, format)
    return ScreenshotResult(
        image_base64=data,
        mime_type=mime,
        width=img.size[0],
        height=img.size[1],
    )


async def capture_region(x: int, y: int, width: int, height: int) -> ScreenshotResult:
    """Convenience wrapper to capture a specific rectangular region."""
    return await capture_screen(Region(x=x, y=y, width=width, height=height))
