"""Window management utilities.

Platform-specific window listing and focus operations.
Currently supports macOS (via AppleScript) with Linux/Windows stubs.
"""

from __future__ import annotations

import asyncio
import json
import platform
import subprocess


async def list_windows() -> list[dict]:
    """List all visible windows with their titles and positions."""
    system = platform.system()
    if system == "Darwin":
        return await _list_windows_macos()
    elif system == "Linux":
        return await _list_windows_linux()
    return [{"error": f"Unsupported platform: {system}"}]


async def focus_window(title: str) -> dict:
    """Bring a window to the front by (partial) title match."""
    system = platform.system()
    if system == "Darwin":
        return await _focus_window_macos(title)
    elif system == "Linux":
        return await _focus_window_linux(title)
    return {"success": False, "error": f"Unsupported platform: {system}"}


async def get_active_window() -> dict:
    """Return the currently focused window."""
    system = platform.system()
    if system == "Darwin":
        return await _get_active_window_macos()
    return {"error": f"Unsupported platform: {system}"}


# ── macOS ────────────────────────────────────────────────────────────────

_LIST_WINDOWS_SCRIPT = """
tell application "System Events"
    set windowList to {}
    repeat with proc in (every process whose visible is true)
        set procName to name of proc
        repeat with win in (every window of proc)
            set winName to name of win
            set winPos to position of win
            set winSize to size of win
            set end of windowList to {procName, winName, item 1 of winPos, item 2 of winPos, item 1 of winSize, item 2 of winSize}
        end repeat
    end repeat
    return windowList
end tell
"""

_FOCUS_WINDOW_SCRIPT = """
on run argv
    set targetTitle to item 1 of argv
    tell application "System Events"
        repeat with proc in (every process whose visible is true)
            repeat with win in (every window of proc)
                if name of win contains targetTitle then
                    set frontmost of proc to true
                    perform action "AXRaise" of win
                    return "focused:" & name of proc & ":" & name of win
                end if
            end repeat
        end repeat
    end tell
    return "not_found"
end run
"""

_ACTIVE_WINDOW_SCRIPT = """
tell application "System Events"
    set frontProc to first process whose frontmost is true
    set procName to name of frontProc
    try
        set winName to name of front window of frontProc
    on error
        set winName to ""
    end try
    return procName & "|" & winName
end tell
"""


async def _run_osascript(script: str, args: list[str] | None = None) -> str:
    cmd = ["osascript", "-e", script]
    if args:
        cmd.extend(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode("utf-8").strip()


async def _list_windows_macos() -> list[dict]:
    raw = await _run_osascript(_LIST_WINDOWS_SCRIPT)
    if not raw:
        return []

    windows = []
    # AppleScript returns comma-separated flat list
    parts = [p.strip() for p in raw.split(",")]
    for i in range(0, len(parts) - 5, 6):
        try:
            windows.append({
                "app": parts[i],
                "title": parts[i + 1],
                "x": int(parts[i + 2]),
                "y": int(parts[i + 3]),
                "width": int(parts[i + 4]),
                "height": int(parts[i + 5]),
            })
        except (ValueError, IndexError):
            continue
    return windows


async def _focus_window_macos(title: str) -> dict:
    result = await _run_osascript(_FOCUS_WINDOW_SCRIPT, [title])
    if result.startswith("focused:"):
        parts = result.split(":", 2)
        return {"success": True, "app": parts[1], "window": parts[2]}
    return {"success": False, "error": f"No window matching '{title}'"}


async def _get_active_window_macos() -> dict:
    result = await _run_osascript(_ACTIVE_WINDOW_SCRIPT)
    parts = result.split("|", 1)
    return {"app": parts[0], "title": parts[1] if len(parts) > 1 else ""}


# ── Linux (wmctrl) ───────────────────────────────────────────────────────

async def _list_windows_linux() -> list[dict]:
    try:
        proc = await asyncio.create_subprocess_exec(
            "wmctrl", "-l", "-G",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
    except FileNotFoundError:
        return [{"error": "wmctrl not installed. Install with: sudo apt install wmctrl"}]

    windows = []
    for line in stdout.decode().splitlines():
        parts = line.split(None, 7)
        if len(parts) >= 8:
            windows.append({
                "title": parts[7],
                "x": int(parts[2]),
                "y": int(parts[3]),
                "width": int(parts[4]),
                "height": int(parts[5]),
            })
    return windows


async def _focus_window_linux(title: str) -> dict:
    try:
        proc = await asyncio.create_subprocess_exec(
            "wmctrl", "-a", title,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return {"success": proc.returncode == 0}
    except FileNotFoundError:
        return {"success": False, "error": "wmctrl not installed"}
