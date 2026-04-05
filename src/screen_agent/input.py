"""Keyboard and mouse input control.

Wraps pyautogui with async interface and safety defaults.
All operations run in a thread pool to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import platform

import pyautogui

# Safety: moving mouse to top-left corner aborts execution
pyautogui.FAILSAFE = True
# Small pause between actions for reliability
pyautogui.PAUSE = 0.05


async def mouse_click(
    x: int,
    y: int,
    button: str = "left",
    clicks: int = 1,
) -> dict:
    """Click at the given screen coordinates."""
    await asyncio.to_thread(pyautogui.click, x, y, clicks=clicks, button=button)
    return {"action": "click", "x": x, "y": y, "button": button, "clicks": clicks}


async def mouse_double_click(x: int, y: int) -> dict:
    """Double-click at the given screen coordinates."""
    await asyncio.to_thread(pyautogui.doubleClick, x, y)
    return {"action": "double_click", "x": x, "y": y}


async def mouse_move(x: int, y: int, duration: float = 0.3) -> dict:
    """Move cursor to the given coordinates."""
    await asyncio.to_thread(pyautogui.moveTo, x, y, duration=duration)
    return {"action": "move", "x": x, "y": y}


async def get_cursor_position() -> dict:
    """Return current cursor position."""
    pos = pyautogui.position()
    return {"x": pos.x, "y": pos.y}


async def keyboard_type(text: str, interval: float = 0.02) -> dict:
    """Type text at the current cursor position.

    Uses clipboard paste on macOS for better Unicode support.
    Falls back to pyautogui.write on other platforms.
    """
    if platform.system() == "Darwin":
        await _paste_text_macos(text)
    else:
        await asyncio.to_thread(pyautogui.write, text, interval=interval)
    return {"action": "type", "length": len(text)}


async def press_key(key: str, modifiers: list[str] | None = None) -> dict:
    """Press a key, optionally with modifier keys.

    Examples:
        press_key("enter")
        press_key("c", modifiers=["command"])  # Cmd+C
        press_key("tab", modifiers=["alt"])
    """
    if modifiers:
        keys = modifiers + [key]
        await asyncio.to_thread(pyautogui.hotkey, *keys)
    else:
        await asyncio.to_thread(pyautogui.press, key)
    return {"action": "press", "key": key, "modifiers": modifiers or []}


async def scroll(
    amount: int,
    x: int | None = None,
    y: int | None = None,
) -> dict:
    """Scroll the mouse wheel. Positive = up, negative = down."""
    await asyncio.to_thread(pyautogui.scroll, amount, x=x, y=y)
    return {"action": "scroll", "amount": amount, "x": x, "y": y}


async def drag(
    start_x: int,
    start_y: int,
    end_x: int,
    end_y: int,
    duration: float = 0.5,
    button: str = "left",
) -> dict:
    """Drag from one position to another."""
    await asyncio.to_thread(pyautogui.moveTo, start_x, start_y)
    await asyncio.to_thread(
        pyautogui.drag,
        end_x - start_x,
        end_y - start_y,
        duration=duration,
        button=button,
    )
    return {
        "action": "drag",
        "from": {"x": start_x, "y": start_y},
        "to": {"x": end_x, "y": end_y},
    }


async def _paste_text_macos(text: str) -> None:
    """Type text via clipboard paste on macOS for better Unicode support."""
    import subprocess

    process = await asyncio.create_subprocess_exec(
        "pbcopy",
        stdin=asyncio.subprocess.PIPE,
    )
    await process.communicate(input=text.encode("utf-8"))
    await asyncio.to_thread(pyautogui.hotkey, "command", "v")
    await asyncio.sleep(0.1)  # Wait for paste to complete
