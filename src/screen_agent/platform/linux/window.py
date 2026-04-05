"""Linux window management backend using wmctrl."""

from __future__ import annotations

import asyncio
import logging

from screen_agent.types import WindowInfo

logger = logging.getLogger(__name__)


class LinuxWindowBackend:
    """Window management via wmctrl."""

    async def list_windows(self) -> list[WindowInfo]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "wmctrl", "-l", "-G", "-p",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
        except FileNotFoundError:
            logger.error("wmctrl not installed")
            return []
        except asyncio.TimeoutError:
            logger.error("wmctrl timed out")
            return []

        windows = []
        for line in stdout.decode().splitlines():
            parts = line.split(None, 8)
            if len(parts) >= 9:
                try:
                    windows.append(WindowInfo(
                        app="",
                        title=parts[8],
                        pid=int(parts[2]),
                        x=int(parts[3]),
                        y=int(parts[4]),
                        width=int(parts[5]),
                        height=int(parts[6]),
                    ))
                except (ValueError, IndexError):
                    continue
        return windows

    async def get_active_window(self) -> WindowInfo | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "getactivewindow", "getwindowname",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
            title = stdout.decode().strip()
            if title:
                return WindowInfo(app="", title=title)
        except (FileNotFoundError, asyncio.TimeoutError):
            pass
        return None

    async def focus_window(self, title: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                "wmctrl", "-a", title,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5.0)
            return proc.returncode == 0
        except (FileNotFoundError, asyncio.TimeoutError):
            return False
