"""pyautogui-based input backend for macOS.

Lowest-priority fallback backend. Works for most apps but has lower
reliability for games and Electron apps compared to CGEvent.
Uses clipboard paste for Unicode support.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_agent.config import InputConfig
    from screen_agent.types import Point

logger = logging.getLogger(__name__)


class PyAutoGUIInputBackend:
    """Input backend wrapping pyautogui (macOS)."""

    def __init__(self, config: InputConfig | None = None):
        self._config = config
        self._pyautogui = None

    @property
    def name(self) -> str:
        return "pyautogui"

    def available(self) -> bool:
        try:
            import pyautogui

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            self._pyautogui = pyautogui
            return True
        except ImportError:
            return False

    def _ensure_pyautogui(self):
        if self._pyautogui is None:
            import pyautogui

            pyautogui.FAILSAFE = True
            pyautogui.PAUSE = 0.05
            self._pyautogui = pyautogui

    async def click(
        self, point: Point, button: str = "left", clicks: int = 1
    ) -> bool:
        return await asyncio.to_thread(
            self._click_sync, point, button, clicks
        )

    def _click_sync(self, point: Point, button: str, clicks: int) -> bool:
        self._ensure_pyautogui()
        self._pyautogui.click(point.x, point.y, clicks=clicks, button=button)
        logger.debug("pyautogui click at %s, button=%s, clicks=%d", point, button, clicks)
        return True

    async def type_text(self, text: str) -> bool:
        return await asyncio.to_thread(self._type_text_sync, text)

    def _type_text_sync(self, text: str) -> bool:
        self._ensure_pyautogui()
        # Use clipboard paste for Unicode support on macOS
        try:
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
            if proc.returncode != 0:
                logger.warning("pbcopy failed: %s", proc.stderr)
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("pbcopy unavailable: %s", e)
            return False
        self._pyautogui.hotkey("command", "v")
        time.sleep(0.1)
        logger.debug("pyautogui typed %d chars via clipboard", len(text))
        return True

    async def press_key(
        self, key: str, modifiers: list[str] | None = None
    ) -> bool:
        return await asyncio.to_thread(self._press_key_sync, key, modifiers)

    def _press_key_sync(self, key: str, modifiers: list[str] | None = None) -> bool:
        self._ensure_pyautogui()
        if modifiers:
            self._pyautogui.hotkey(*modifiers, key)
        else:
            self._pyautogui.press(key)
        logger.debug("pyautogui key: %s, modifiers=%s", key, modifiers)
        return True

    async def scroll(self, amount: int, point: Point | None = None) -> bool:
        return await asyncio.to_thread(self._scroll_sync, amount, point)

    def _scroll_sync(self, amount: int, point: Point | None = None) -> bool:
        self._ensure_pyautogui()
        kwargs = {}
        if point:
            kwargs["x"] = point.x
            kwargs["y"] = point.y
        self._pyautogui.scroll(amount, **kwargs)
        logger.debug("pyautogui scroll %d", amount)
        return True

    async def move(self, point: Point) -> bool:
        return await asyncio.to_thread(self._move_sync, point)

    def _move_sync(self, point: Point) -> bool:
        self._ensure_pyautogui()
        duration = self._config.mouse_move_duration if self._config else 0.3
        self._pyautogui.moveTo(point.x, point.y, duration=duration)
        logger.debug("pyautogui move to %s", point)
        return True

    async def drag(
        self, start: Point, end: Point, button: str = "left"
    ) -> bool:
        return await asyncio.to_thread(self._drag_sync, start, end, button)

    def _drag_sync(self, start: Point, end: Point, button: str) -> bool:
        self._ensure_pyautogui()
        duration = self._config.drag_duration if self._config else 0.5
        self._pyautogui.moveTo(start.x, start.y)
        self._pyautogui.drag(
            end.x - start.x, end.y - start.y,
            duration=duration, button=button,
        )
        logger.debug("pyautogui drag %s -> %s", start, end)
        return True
