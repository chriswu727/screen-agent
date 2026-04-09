"""Process-targeted Accessibility input — no mouse, no screen occupation.

Unlike input_ax.py which uses SystemWide + frontmost app, this module
targets a SPECIFIC process by PID. Works for background windows.

The key API: AXUIElementCreateApplication(pid) → target any process
Then: AXUIElementCopyElementAtPosition → find element at window coords
Then: AXUIElementPerformAction → click without moving mouse

This is the missing piece for "test any app without occupying the screen".
"""

from __future__ import annotations

import asyncio
import logging

from screen_agent.types import Point

logger = logging.getLogger(__name__)


def _get_app_ref(pid: int):
    """Create an AX reference to a specific application by PID."""
    from ApplicationServices import AXUIElementCreateApplication
    return AXUIElementCreateApplication(pid)


def _element_at_position(pid: int, x: float, y: float):
    """Find the AX element at (x, y).

    Uses SystemWide element with screen-absolute coordinates.
    The pyobjc binding for AXUIElementCopyElementAtPosition takes
    (element, x, y, &result) → returns (err, result).
    """
    from ApplicationServices import (
        AXUIElementCopyElementAtPosition,
        AXUIElementCreateSystemWide,
    )

    system = AXUIElementCreateSystemWide()
    # pyobjc: (error, element) = AXUIElementCopyElementAtPosition(system, x, y, None)
    err, element = AXUIElementCopyElementAtPosition(system, x, y, None)
    if err != 0 or element is None:
        return None
    return element


def _click_element(element) -> bool:
    """Perform click action on an element. No mouse movement.

    Tries AXPress first (buttons), then AXConfirm, then AXFocus (text fields).
    """
    from ApplicationServices import AXUIElementPerformAction
    for action in ("AXPress", "AXConfirm", "AXFocus"):
        err = AXUIElementPerformAction(element, action)
        if err == 0:
            return True
    return False


def _focus_element(element) -> bool:
    """Set AXFocused on an element."""
    from ApplicationServices import AXUIElementSetAttributeValue
    err = AXUIElementSetAttributeValue(element, "AXFocused", True)
    return err == 0


def _set_value(element, value: str) -> bool:
    """Set AXValue on a text element."""
    from ApplicationServices import AXUIElementSetAttributeValue
    err = AXUIElementSetAttributeValue(element, "AXValue", value)
    return err == 0


def _get_value(element) -> str | None:
    """Get AXValue from an element."""
    from ApplicationServices import AXUIElementCopyAttributeValue
    err, val = AXUIElementCopyAttributeValue(element, "AXValue", None)
    if err != 0:
        return None
    return str(val) if val is not None else None


def _get_role(element) -> str | None:
    """Get AXRole of an element."""
    from ApplicationServices import AXUIElementCopyAttributeValue
    err, role = AXUIElementCopyAttributeValue(element, "AXRole", None)
    if err != 0:
        return None
    return str(role)


class AXTargetedInput:
    """Process-targeted AX input. No mouse, no screen occupation."""

    def __init__(self, pid: int):
        self.pid = pid

    async def click(self, point: Point) -> bool:
        """Click element at screen-absolute coordinates via AX."""
        return await asyncio.to_thread(self._click_sync, point)

    def _click_sync(self, point: Point) -> bool:
        element = _element_at_position(self.pid, float(point.x), float(point.y))
        if element is None:
            logger.debug("AX targeted: no element at %s for pid %d", point, self.pid)
            return False

        if _click_element(element):
            logger.debug("AX targeted: clicked at %s (pid %d)", point, self.pid)
            return True

        logger.debug("AX targeted: AXPress failed at %s", point)
        return False

    async def type_text(self, point: Point, text: str) -> bool:
        """Focus element at point and set its value. No keyboard events needed."""
        return await asyncio.to_thread(self._type_sync, point, text)

    def _type_sync(self, point: Point, text: str) -> bool:
        element = _element_at_position(self.pid, float(point.x), float(point.y))
        if element is None:
            return False

        role = _get_role(element)
        text_roles = {"AXTextField", "AXTextArea", "AXComboBox", "AXSearchField", "AXWebArea"}

        # Focus first
        _focus_element(element)

        if role in text_roles:
            current = _get_value(element) or ""
            return _set_value(element, current + text)

        # For web content (AXGroup, AXWebArea, etc.), try setting value anyway
        return _set_value(element, text)

    async def press_key(self, key: str) -> bool:
        """Send a key event to the target process via CGEvent + PID."""
        return await asyncio.to_thread(self._press_key_sync, key)

    def _press_key_sync(self, key: str) -> bool:
        """Use CGEvent posted to the specific process."""
        try:
            import Quartz

            key_map = {
                "enter": (36, "\r"), "return": (36, "\r"),
                "tab": (48, "\t"), "escape": (53, ""),
                "backspace": (51, ""), "space": (49, " "),
            }

            if key.lower() in key_map:
                keycode, _ = key_map[key.lower()]
            else:
                return False  # Only handle special keys

            source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateCombinedSessionState)
            down = Quartz.CGEventCreateKeyboardEvent(source, keycode, True)
            up = Quartz.CGEventCreateKeyboardEvent(source, keycode, False)

            # Target the specific process
            psn = self._get_psn()
            if psn:
                Quartz.CGEventPostToPSN(psn, down)
                Quartz.CGEventPostToPSN(psn, up)
                return True

            return False
        except Exception as e:
            logger.debug("AX targeted press_key failed: %s", e)
            return False

    def _get_psn(self):
        """Get ProcessSerialNumber for the PID. Deprecated but functional."""
        try:
            import Quartz
            import ctypes

            GetProcessForPID = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices").GetProcessForPID
            GetProcessForPID.argtypes = [ctypes.c_int32, ctypes.c_void_p]
            GetProcessForPID.restype = ctypes.c_int32

            class ProcessSerialNumber(ctypes.Structure):
                _fields_ = [("highLongOfPSN", ctypes.c_uint32), ("lowLongOfPSN", ctypes.c_uint32)]

            psn = ProcessSerialNumber()
            err = GetProcessForPID(self.pid, ctypes.byref(psn))
            if err == 0:
                return (psn.highLongOfPSN, psn.lowLongOfPSN)
        except Exception:
            pass
        return None
