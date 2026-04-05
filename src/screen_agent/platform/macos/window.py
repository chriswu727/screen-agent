"""macOS window management backend.

Uses AppleScript via osascript for window listing and focus.
Uses a tab delimiter (\\t) instead of || to avoid injection issues
when window titles contain special characters.
"""

from __future__ import annotations

import asyncio
import logging

from screen_agent.types import WindowInfo

logger = logging.getLogger(__name__)

_DELIMITER = "\t"

# AppleScript that returns tab-delimited window list
_LIST_WINDOWS_SCRIPT = """
tell application "System Events"
    set windowData to {}
    repeat with proc in (every process whose visible is true)
        set procName to name of proc
        set procID to unix id of proc
        repeat with win in (every window of proc)
            try
                set winName to name of win
                set winPos to position of win
                set winSize to size of win
                set posX to (item 1 of winPos as text)
                set posY to (item 2 of winPos as text)
                set szW to (item 1 of winSize as text)
                set szH to (item 2 of winSize as text)
                set entry to procName & tab & winName & tab & procID
                set entry to entry & tab & posX & tab & posY & tab & szW & tab & szH
                set end of windowData to entry
            end try
        end repeat
    end repeat
    set AppleScript's text item delimiters to "\\n"
    return windowData as text
end tell
"""

_FOCUS_WINDOW_SCRIPT = """
on run argv
    set targetTitle to item 1 of argv
    tell application "System Events"
        repeat with proc in (every process whose visible is true)
            repeat with win in (every window of proc)
                try
                    if name of win contains targetTitle then
                        set frontmost of proc to true
                        perform action "AXRaise" of win
                        return name of proc & tab & name of win
                    end if
                end try
            end repeat
        end repeat
    end tell
    return "NOT_FOUND"
end run
"""

_ACTIVE_WINDOW_SCRIPT = """
tell application "System Events"
    set frontProc to first process whose frontmost is true
    set procName to name of frontProc
    set procID to unix id of frontProc
    try
        set winName to name of front window of frontProc
    on error
        set winName to ""
    end try
    return procName & tab & winName & tab & procID
end tell
"""


class MacOSWindowBackend:
    """Window management via AppleScript."""

    async def list_windows(self) -> list[WindowInfo]:
        raw = await self._run_osascript(_LIST_WINDOWS_SCRIPT)
        if not raw:
            return []

        windows = []
        for line in raw.splitlines():
            parts = line.split(_DELIMITER)
            if len(parts) >= 7:
                try:
                    windows.append(WindowInfo(
                        app=parts[0].strip(),
                        title=parts[1].strip(),
                        pid=int(parts[2].strip()),
                        x=int(parts[3].strip()),
                        y=int(parts[4].strip()),
                        width=int(parts[5].strip()),
                        height=int(parts[6].strip()),
                    ))
                except (ValueError, IndexError) as e:
                    logger.debug("Skipping malformed window entry: %s", e)
        return windows

    async def get_active_window(self) -> WindowInfo | None:
        raw = await self._run_osascript(_ACTIVE_WINDOW_SCRIPT)
        if not raw:
            return None
        parts = raw.split(_DELIMITER)
        if len(parts) >= 3:
            try:
                return WindowInfo(
                    app=parts[0].strip(),
                    title=parts[1].strip(),
                    pid=int(parts[2].strip()),
                )
            except (ValueError, IndexError):
                pass
        return None

    async def focus_window(self, title: str) -> bool:
        raw = await self._run_osascript(_FOCUS_WINDOW_SCRIPT, [title])
        if raw and raw != "NOT_FOUND":
            parts = raw.split(_DELIMITER)
            if len(parts) >= 2:
                logger.info("Focused window: %s - %s", parts[0], parts[1])
                return True
        logger.warning("No window matching '%s'", title)
        return False

    async def _run_osascript(
        self, script: str, args: list[str] | None = None
    ) -> str:
        cmd = ["osascript", "-e", script]
        if args:
            cmd.extend(args)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=10.0
            )
            if proc.returncode != 0:
                logger.debug("osascript error: %s", stderr.decode("utf-8", errors="replace"))
                return ""
            return stdout.decode("utf-8").strip()
        except asyncio.TimeoutError:
            logger.error("osascript timed out")
            return ""
        except FileNotFoundError:
            logger.error("osascript not found")
            return ""
