"""CDP-backed window session for true background testing.

When window_scope detects Chrome on a different Space (CGWindowListCreateImage
returns blank), it falls back to CDP. Screenshots come from Chrome's internal
renderer, clicks go through Chrome's input pipeline. Zero macOS window server
dependency — works on any Space, minimized, or even headless.
"""

from __future__ import annotations

import asyncio
import base64
import logging

from screen_agent.platform.cdp.client import CDPClient
from screen_agent.types import Point, Region

logger = logging.getLogger(__name__)


class CDPSession:
    """A window session backed by Chrome DevTools Protocol."""

    def __init__(self, cdp: CDPClient, tab_id: str, title: str, width: int, height: int):
        self.cdp = cdp
        self.tab_id = tab_id
        self.title = title
        self.width = width
        self.height = height
        # CDP uses page-relative coordinates — no screen translation needed
        self.bounds = Region(x=0, y=0, width=width, height=height)

    def window_to_screen(self, point: Point) -> Point:
        """CDP clicks are page-relative. No translation needed."""
        return point

    async def capture(self) -> dict | None:
        """Capture via CDP Page.captureScreenshot."""
        try:
            b64 = await self.cdp.screenshot(format="jpeg", quality=75)
            jpeg_bytes = base64.b64decode(b64)

            from PIL import Image
            from io import BytesIO
            img = Image.open(BytesIO(jpeg_bytes))

            return {
                "image_base64": b64,
                "mime_type": "image/jpeg",
                "width": img.size[0],
                "height": img.size[1],
                "scale_factor": 1.0,
            }
        except Exception as e:
            logger.error("CDP capture failed: %s", e)
            return None

    async def click(self, point: Point, button: str = "left") -> bool:
        """Click via CDP Input.dispatchMouseEvent."""
        try:
            await self.cdp.click(point.x, point.y, button)
            return True
        except Exception as e:
            logger.error("CDP click failed: %s", e)
            return False

    async def type_text(self, text: str) -> bool:
        """Type via CDP Input.dispatchKeyEvent."""
        try:
            await self.cdp.type_text(text)
            return True
        except Exception as e:
            logger.error("CDP type failed: %s", e)
            return False

    async def press_key(self, key: str) -> bool:
        try:
            await self.cdp.press_key(key)
            return True
        except Exception as e:
            logger.error("CDP press_key failed: %s", e)
            return False

    async def evaluate(self, expression: str):
        """Run JavaScript in the page."""
        return await self.cdp.evaluate(expression)

    async def close(self):
        await self.cdp.close()


async def create_cdp_session(
    host: str = "localhost",
    port: int = 9222,
    url_contains: str | None = None,
    title_contains: str | None = None,
) -> CDPSession | None:
    """Connect to Chrome via CDP and return a session for the matching tab.

    Chrome must be running with --remote-debugging-port=9222.
    """
    try:
        cdp = CDPClient(host, port)
        tab = await cdp.find_tab(url_contains=url_contains, title_contains=title_contains)
        if not tab:
            logger.warning("CDP: no tab matching url=%s title=%s", url_contains, title_contains)
            return None

        await cdp.connect_tab(tab["id"])

        # Get viewport size
        layout = await cdp.send("Page.getLayoutMetrics")
        vp = layout.get("cssVisualViewport", layout.get("visualViewport", {}))
        width = int(vp.get("clientWidth", 1920))
        height = int(vp.get("clientHeight", 1080))

        return CDPSession(
            cdp=cdp,
            tab_id=tab["id"],
            title=tab.get("title", ""),
            width=width,
            height=height,
        )
    except Exception as e:
        logger.warning("CDP connection failed: %s", e)
        return None
