"""Linux window-targeted capture via xdotool + xwd/import.

Uses subprocess calls to standard X11 utilities — no compiled dependencies.
Falls back gracefully if tools are missing.

For X11: uses xdotool for window discovery, import (ImageMagick) for capture.
Wayland: limited support via GNOME screenshot portal (D-Bus).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
from io import BytesIO

from screen_agent.types import Region

logger = logging.getLogger(__name__)


def _has_command(name: str) -> bool:
    return shutil.which(name) is not None


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a command and return stdout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return ""


def _find_window_sync(app: str | None = None, title: str | None = None) -> dict | None:
    """Find a window using wmctrl or xdotool."""
    if _has_command("wmctrl"):
        return _find_via_wmctrl(app, title)
    if _has_command("xdotool"):
        return _find_via_xdotool(app, title)
    logger.warning("Neither wmctrl nor xdotool found — install one for window discovery")
    return None


def _find_via_wmctrl(app: str | None, title: str | None) -> dict | None:
    """Find window via wmctrl -l -p."""
    output = _run(["wmctrl", "-l", "-p"])
    if not output:
        return None

    for line in output.splitlines():
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue

        wid_hex = parts[0]
        pid = int(parts[2]) if parts[2].isdigit() else 0
        win_title = parts[4]

        # Get app name from PID
        app_name = ""
        if pid:
            app_name = _run(["ps", "-p", str(pid), "-o", "comm="])

        app_match = app is None or app.lower() in app_name.lower()
        title_match = title is None or title.lower() in win_title.lower()

        if app_match and title_match:
            wid = int(wid_hex, 16)
            bounds = _get_window_geometry(wid)
            return {
                "window_id": wid,
                "app": app_name,
                "title": win_title,
                "bounds": {
                    "X": bounds.x if bounds else 0,
                    "Y": bounds.y if bounds else 0,
                    "Width": bounds.width if bounds else 0,
                    "Height": bounds.height if bounds else 0,
                },
            }
    return None


def _find_via_xdotool(app: str | None, title: str | None) -> dict | None:
    """Find window via xdotool search."""
    search_args = ["xdotool", "search", "--onlyvisible"]
    if title:
        search_args.extend(["--name", title])
    elif app:
        search_args.extend(["--class", app])
    else:
        return None

    output = _run(search_args)
    if not output:
        return None

    wid = int(output.splitlines()[0])
    win_name = _run(["xdotool", "getwindowname", str(wid)])
    win_pid = _run(["xdotool", "getwindowpid", str(wid)])
    app_name = ""
    if win_pid.isdigit():
        app_name = _run(["ps", "-p", win_pid, "-o", "comm="])

    bounds = _get_window_geometry(wid)
    return {
        "window_id": wid,
        "app": app_name,
        "title": win_name,
        "bounds": {
            "X": bounds.x if bounds else 0,
            "Y": bounds.y if bounds else 0,
            "Width": bounds.width if bounds else 0,
            "Height": bounds.height if bounds else 0,
        },
    }


def _get_window_geometry(wid: int) -> Region | None:
    """Get window geometry via xdotool."""
    output = _run(["xdotool", "getwindowgeometry", "--shell", str(wid)])
    if not output:
        return None

    vals = {}
    for line in output.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k.strip()] = int(v.strip())

    return Region(
        x=vals.get("X", 0),
        y=vals.get("Y", 0),
        width=vals.get("WIDTH", 0),
        height=vals.get("HEIGHT", 0),
    )


def _capture_window_sync(window_id: int) -> bytes | None:
    """Capture a window using ImageMagick's import command."""
    if not _has_command("import"):
        # Fallback: try xwd + convert
        if _has_command("xwd") and _has_command("convert"):
            return _capture_via_xwd(window_id)
        logger.warning("Neither 'import' (ImageMagick) nor 'xwd' found for window capture")
        return None

    try:
        result = subprocess.run(
            ["import", "-window", hex(window_id), "jpeg:-"],
            capture_output=True, timeout=10.0,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _capture_via_xwd(window_id: int) -> bytes | None:
    """Capture via xwd piped to convert (ImageMagick)."""
    try:
        xwd = subprocess.Popen(
            ["xwd", "-id", str(window_id), "-silent"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        convert = subprocess.Popen(
            ["convert", "xwd:-", "jpeg:-"],
            stdin=xwd.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        xwd.stdout.close()
        output, _ = convert.communicate(timeout=10.0)
        if convert.returncode == 0 and output:
            return output
    except Exception:
        pass
    return None


def _get_window_bounds_sync(window_id: int) -> Region | None:
    return _get_window_geometry(window_id)


class LinuxWindowCaptureBackend:
    """Window-targeted capture for Linux (X11)."""

    async def find_window(self, app: str | None = None, title: str | None = None) -> dict | None:
        return await asyncio.to_thread(_find_window_sync, app, title)

    async def capture_window(self, window_id: int) -> bytes | None:
        return await asyncio.to_thread(_capture_window_sync, window_id)

    async def get_window_bounds(self, window_id: int) -> Region | None:
        return await asyncio.to_thread(_get_window_bounds_sync, window_id)
