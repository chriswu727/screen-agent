"""Screen state cache.

Caches the last screenshot and window state to reduce redundant
captures. Invalidated automatically after a configurable TTL.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_agent.types import ScreenshotResult, WindowInfo


class ScreenState:
    """Lightweight cache for screen observations."""

    def __init__(self, ttl_seconds: float = 1.0):
        self._ttl = ttl_seconds
        self._last_screenshot: ScreenshotResult | None = None
        self._last_screenshot_time: float = 0
        self._last_windows: list[WindowInfo] = []
        self._last_windows_time: float = 0

    @property
    def last_screenshot(self) -> ScreenshotResult | None:
        if time.monotonic() - self._last_screenshot_time > self._ttl:
            return None
        return self._last_screenshot

    def update_screenshot(self, result: ScreenshotResult) -> None:
        self._last_screenshot = result
        self._last_screenshot_time = time.monotonic()

    @property
    def last_windows(self) -> list[WindowInfo]:
        if time.monotonic() - self._last_windows_time > self._ttl:
            return []
        return self._last_windows

    def update_windows(self, windows: list[WindowInfo]) -> None:
        self._last_windows = windows
        self._last_windows_time = time.monotonic()

    def invalidate(self) -> None:
        self._last_screenshot = None
        self._last_windows = []
