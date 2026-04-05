"""Accessibility API input backend for macOS.

Uses AXUIElement to interact with UI elements semantically.
This is the highest-priority backend: works with native apps
even when coordinate-based clicking fails. Falls through to
CGEvent for apps without accessibility support (games, etc.).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_agent.config import InputConfig
    from screen_agent.types import Point

logger = logging.getLogger(__name__)


class AXInputBackend:
    """Input backend using macOS Accessibility API."""

    def __init__(self, config: InputConfig | None = None):
        self._config = config
        self._available: bool | None = None

    @property
    def name(self) -> str:
        return "ax"

    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            from ApplicationServices import (  # noqa: F401
                AXIsProcessTrusted,
                AXUIElementCreateSystemWide,
            )

            self._available = AXIsProcessTrusted()
            if not self._available:
                logger.info("AX backend: accessibility not trusted")
        except ImportError:
            self._available = False
        return self._available

    async def click(
        self, point: Point, button: str = "left", clicks: int = 1
    ) -> bool:
        if button != "left" or clicks != 1:
            return False  # AX only supports single left click via AXPress
        return await asyncio.to_thread(self._click_sync, point)

    def _click_sync(self, point: Point) -> bool:
        """Find element at point and perform AXPress."""
        try:
            from ApplicationServices import (
                AXUIElementCopyElementAtPosition,
                AXUIElementCreateSystemWide,
                AXUIElementPerformAction,
            )

            system = AXUIElementCreateSystemWide()
            err, element = AXUIElementCopyElementAtPosition(
                system, float(point.x), float(point.y)
            )
            if err != 0 or element is None:
                logger.debug("AX: no element at %s (err=%d)", point, err)
                return False

            err = AXUIElementPerformAction(element, "AXPress")
            if err != 0:
                logger.debug("AX: AXPress failed at %s (err=%d)", point, err)
                return False

            logger.debug("AX: clicked element at %s", point)
            return True
        except Exception as e:
            logger.debug("AX click failed: %s", e)
            return False

    async def type_text(self, text: str) -> bool:
        """AX can set value on focused text fields."""
        return await asyncio.to_thread(self._type_text_sync, text)

    def _type_text_sync(self, text: str) -> bool:
        try:
            from AppKit import NSWorkspace
            from ApplicationServices import (
                AXUIElementCopyAttributeValue,
                AXUIElementSetAttributeValue,
            )

            # Get focused app
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not app:
                return False

            pid = app.processIdentifier()
            from ApplicationServices import AXUIElementCreateApplication

            app_ref = AXUIElementCreateApplication(pid)

            # Get focused element
            err, focused = AXUIElementCopyAttributeValue(
                app_ref, "AXFocusedUIElement"
            )
            if err != 0 or focused is None:
                return False

            # Check if it accepts text
            err, role = AXUIElementCopyAttributeValue(focused, "AXRole")
            if err != 0:
                return False

            text_roles = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField"}
            if role not in text_roles:
                return False

            # Get current value and append
            err, current = AXUIElementCopyAttributeValue(focused, "AXValue")
            new_value = (current or "") + text

            err = AXUIElementSetAttributeValue(focused, "AXValue", new_value)
            if err != 0:
                return False

            logger.debug("AX: typed %d chars into %s", len(text), role)
            return True
        except Exception as e:
            logger.debug("AX type_text failed: %s", e)
            return False

    async def press_key(
        self, key: str, modifiers: list[str] | None = None
    ) -> bool:
        # AX doesn't support key presses; fall through to CGEvent
        return False

    async def scroll(self, amount: int, point: Point | None = None) -> bool:
        return False

    async def move(self, point: Point) -> bool:
        return False

    async def drag(
        self, start: Point, end: Point, button: str = "left"
    ) -> bool:
        return False
