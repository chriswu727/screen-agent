"""CGEvent-based input backend for macOS.

Uses Quartz CGEvent API for native event injection. This is the
mid-tier backend: more reliable than pyautogui for games and Electron
apps, but less semantic than the Accessibility API.
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

# Button mapping: Quartz constants
_BUTTON_MAP = {
    "left": 0,   # kCGMouseButtonLeft
    "right": 1,  # kCGMouseButtonRight
    "middle": 2, # kCGMouseButtonCenter
}

# Key code mapping for common keys
_KEY_CODES: dict[str, int] = {
    "return": 36, "enter": 36,
    "tab": 48,
    "space": 49,
    "delete": 51, "backspace": 51,
    "escape": 53, "esc": 53,
    "up": 126, "down": 125, "left": 123, "right": 124,
    "home": 115, "end": 119,
    "pageup": 116, "pagedown": 121,
    "f1": 122, "f2": 120, "f3": 99, "f4": 118,
    "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
    "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3,
    "g": 5, "h": 4, "i": 34, "j": 38, "k": 40, "l": 37,
    "m": 46, "n": 45, "o": 31, "p": 35, "q": 12, "r": 15,
    "s": 1, "t": 17, "u": 32, "v": 9, "w": 13, "x": 7,
    "y": 16, "z": 6,
    "0": 29, "1": 18, "2": 19, "3": 20, "4": 21,
    "5": 23, "6": 22, "7": 26, "8": 28, "9": 25,
    "-": 27, "=": 24, "[": 33, "]": 30, "\\": 42,
    ";": 41, "'": 39, ",": 43, ".": 47, "/": 44, "`": 50,
}

_MODIFIER_FLAGS: dict[str, int] = {
    "command": 1 << 20,  # kCGEventFlagMaskCommand
    "cmd": 1 << 20,
    "shift": 1 << 17,    # kCGEventFlagMaskShift
    "alt": 1 << 19,      # kCGEventFlagMaskAlternate
    "option": 1 << 19,
    "ctrl": 1 << 18,     # kCGEventFlagMaskControl
    "control": 1 << 18,
}


class CGEventInputBackend:
    """Input backend using macOS Quartz CGEvent API."""

    def __init__(self, config: InputConfig | None = None):
        self._config = config
        self._Quartz = None

    @property
    def name(self) -> str:
        return "cgevent"

    def available(self) -> bool:
        try:
            import Quartz
            self._Quartz = Quartz
            return True
        except ImportError:
            return False

    def _ensure_quartz(self):
        if self._Quartz is None:
            import Quartz
            self._Quartz = Quartz

    async def click(
        self, point: Point, button: str = "left", clicks: int = 1
    ) -> bool:
        return await asyncio.to_thread(
            self._click_sync, point, button, clicks
        )

    def _click_sync(self, point: Point, button: str, clicks: int) -> bool:
        self._ensure_quartz()
        q = self._Quartz

        cg_button = _BUTTON_MAP.get(button, 0)
        pos = (point.x, point.y)

        if button == "left":
            down_type = q.kCGEventLeftMouseDown
            up_type = q.kCGEventLeftMouseUp
        elif button == "right":
            down_type = q.kCGEventRightMouseDown
            up_type = q.kCGEventRightMouseUp
        else:
            down_type = q.kCGEventOtherMouseDown
            up_type = q.kCGEventOtherMouseUp

        source = q.CGEventSourceCreate(q.kCGEventSourceStateHIDSystemState)

        for i in range(clicks):
            down = q.CGEventCreateMouseEvent(source, down_type, pos, cg_button)
            up = q.CGEventCreateMouseEvent(source, up_type, pos, cg_button)

            # Set click count for double/triple clicks
            if clicks > 1:
                q.CGEventSetIntegerValueField(
                    down, q.kCGMouseEventClickState, i + 1
                )
                q.CGEventSetIntegerValueField(
                    up, q.kCGMouseEventClickState, i + 1
                )

            q.CGEventPost(q.kCGHIDEventTap, down)
            q.CGEventPost(q.kCGHIDEventTap, up)

            if i < clicks - 1:
                time.sleep(0.05)

        logger.debug("CGEvent click at %s, button=%s, clicks=%d", point, button, clicks)
        return True

    async def type_text(self, text: str) -> bool:
        return await asyncio.to_thread(self._type_text_sync, text)

    def _type_text_sync(self, text: str) -> bool:
        """Type text via clipboard paste (Cmd+V) for Unicode support."""
        try:
            proc = subprocess.run(
                ["pbcopy"],
                input=text.encode("utf-8"),
                capture_output=True,
                timeout=5,
            )
            if proc.returncode != 0:
                logger.error("pbcopy failed: %s", proc.stderr)
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.error("pbcopy unavailable: %s", e)
            return False

        # Press Cmd+V
        self._press_key_sync("v", ["command"])
        time.sleep(0.1)

        logger.debug("CGEvent typed %d chars via clipboard", len(text))
        return True

    async def press_key(
        self, key: str, modifiers: list[str] | None = None
    ) -> bool:
        return await asyncio.to_thread(
            self._press_key_sync, key, modifiers
        )

    def _press_key_sync(self, key: str, modifiers: list[str] | None = None) -> bool:
        self._ensure_quartz()
        q = self._Quartz

        key_lower = key.lower()
        keycode = _KEY_CODES.get(key_lower)
        if keycode is None:
            logger.warning("Unknown key: %s", key)
            return False

        source = q.CGEventSourceCreate(q.kCGEventSourceStateHIDSystemState)

        # Build modifier flags
        flags = 0
        for mod in (modifiers or []):
            flag = _MODIFIER_FLAGS.get(mod.lower(), 0)
            flags |= flag

        down = q.CGEventCreateKeyboardEvent(source, keycode, True)
        up = q.CGEventCreateKeyboardEvent(source, keycode, False)

        if flags:
            q.CGEventSetFlags(down, flags)
            q.CGEventSetFlags(up, flags)

        q.CGEventPost(q.kCGHIDEventTap, down)
        q.CGEventPost(q.kCGHIDEventTap, up)

        logger.debug("CGEvent key press: %s, modifiers=%s", key, modifiers)
        return True

    async def scroll(self, amount: int, point: Point | None = None) -> bool:
        return await asyncio.to_thread(self._scroll_sync, amount, point)

    def _scroll_sync(self, amount: int, point: Point | None = None) -> bool:
        self._ensure_quartz()
        q = self._Quartz

        if point:
            # Move cursor to position first
            source = q.CGEventSourceCreate(q.kCGEventSourceStateHIDSystemState)
            move = q.CGEventCreateMouseEvent(
                source, q.kCGEventMouseMoved, (point.x, point.y), 0
            )
            q.CGEventPost(q.kCGHIDEventTap, move)
            time.sleep(0.05)

        scroll_event = q.CGEventCreateScrollWheelEvent(
            None, q.kCGScrollEventUnitLine, 1, amount
        )
        if scroll_event is None:
            logger.error("Failed to create scroll event")
            return False
        q.CGEventPost(q.kCGHIDEventTap, scroll_event)
        logger.debug("CGEvent scroll amount=%d", amount)
        return True

    async def move(self, point: Point) -> bool:
        return await asyncio.to_thread(self._move_sync, point)

    def _move_sync(self, point: Point) -> bool:
        self._ensure_quartz()
        q = self._Quartz

        source = q.CGEventSourceCreate(q.kCGEventSourceStateHIDSystemState)
        event = q.CGEventCreateMouseEvent(
            source, q.kCGEventMouseMoved, (point.x, point.y), 0
        )
        q.CGEventPost(q.kCGHIDEventTap, event)
        logger.debug("CGEvent move to %s", point)
        return True

    async def drag(
        self, start: Point, end: Point, button: str = "left"
    ) -> bool:
        return await asyncio.to_thread(self._drag_sync, start, end, button)

    def _drag_sync(self, start: Point, end: Point, button: str) -> bool:
        self._ensure_quartz()
        q = self._Quartz

        cg_button = _BUTTON_MAP.get(button, 0)
        source = q.CGEventSourceCreate(q.kCGEventSourceStateHIDSystemState)

        if button == "left":
            down_type = q.kCGEventLeftMouseDown
            drag_type = q.kCGEventLeftMouseDragged
            up_type = q.kCGEventLeftMouseUp
        elif button == "right":
            down_type = q.kCGEventRightMouseDown
            drag_type = q.kCGEventRightMouseDragged
            up_type = q.kCGEventRightMouseUp
        else:
            down_type = q.kCGEventOtherMouseDown
            drag_type = q.kCGEventOtherMouseDragged
            up_type = q.kCGEventOtherMouseUp

        # Mouse down at start
        down = q.CGEventCreateMouseEvent(
            source, down_type, (start.x, start.y), cg_button
        )
        q.CGEventPost(q.kCGHIDEventTap, down)

        # Interpolate drag path using configured duration
        duration = self._config.drag_duration if self._config else 0.5
        steps = max(10, int(duration / 0.02))  # ~50fps
        step_delay = duration / steps

        for i in range(1, steps + 1):
            t = i / steps
            x = start.x + (end.x - start.x) * t
            y = start.y + (end.y - start.y) * t
            drag = q.CGEventCreateMouseEvent(
                source, drag_type, (x, y), cg_button
            )
            q.CGEventPost(q.kCGHIDEventTap, drag)
            time.sleep(step_delay)

        # Mouse up at end
        up = q.CGEventCreateMouseEvent(
            source, up_type, (end.x, end.y), cg_button
        )
        q.CGEventPost(q.kCGHIDEventTap, up)

        logger.debug("CGEvent drag from %s to %s (%.0fms)", start, end, duration * 1000)
        return True
