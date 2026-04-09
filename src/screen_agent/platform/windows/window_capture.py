"""Windows window-targeted capture via Win32 API.

Uses PrintWindow + ctypes — zero external dependencies.
Captures a specific window by HWND, even when occluded by other windows.
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging
from io import BytesIO

from screen_agent.types import Region

logger = logging.getLogger(__name__)

# Win32 constants
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0
BI_RGB = 0
PW_RENDERFULLCONTENT = 0x00000002
GWL_STYLE = -16
WS_VISIBLE = 0x10000000

# Win32 structures
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.wintypes.LONG),
        ("top", ctypes.wintypes.LONG),
        ("right", ctypes.wintypes.LONG),
        ("bottom", ctypes.wintypes.LONG),
    ]

# Win32 DLLs
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def _enum_windows() -> list[dict]:
    """Enumerate all top-level windows with title and bounds."""
    results = []

    def callback(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True

        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value

        # Get process name
        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        # Get bounds
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))

        results.append({
            "window_id": hwnd,
            "app": _get_process_name(pid.value),
            "title": title,
            "bounds": {
                "X": rect.left,
                "Y": rect.top,
                "Width": rect.right - rect.left,
                "Height": rect.bottom - rect.top,
            },
        })
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(callback), 0)
    return results


def _get_process_name(pid: int) -> str:
    """Get process executable name from PID."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi

        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010

        handle = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if handle:
            buf = ctypes.create_unicode_buffer(260)
            psapi.GetModuleBaseNameW(handle, None, buf, 260)
            kernel32.CloseHandle(handle)
            name = buf.value
            # Strip .exe extension
            if name.lower().endswith(".exe"):
                name = name[:-4]
            return name
    except Exception:
        pass
    return ""


def _find_window_sync(app: str | None = None, title: str | None = None) -> dict | None:
    """Find a window by app name and/or title."""
    windows = _enum_windows()
    for w in windows:
        app_match = app is None or app.lower() in w["app"].lower()
        title_match = title is None or title.lower() in w["title"].lower()
        if app_match and title_match:
            return w
    return None


def _capture_window_sync(hwnd: int) -> bytes | None:
    """Capture a window by HWND using PrintWindow. Returns raw BGRA bytes or None."""
    rect = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top

    if width <= 0 or height <= 0:
        return None

    # Create compatible DC and bitmap
    hwnd_dc = user32.GetDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hwnd_dc)
    bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
    old_bitmap = gdi32.SelectObject(mem_dc, bitmap)

    # PrintWindow captures even occluded windows
    user32.PrintWindow(hwnd, mem_dc, PW_RENDERFULLCONTENT)

    # Extract bitmap data
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    buf_size = width * height * 4
    buf = ctypes.create_string_buffer(buf_size)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    # Cleanup
    gdi32.SelectObject(mem_dc, old_bitmap)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hwnd_dc)

    # Convert BGRA to PIL Image and encode as JPEG
    try:
        from PIL import Image
        img = Image.frombytes("RGBA", (width, height), buf.raw, "raw", "BGRA")
        img = img.convert("RGB")
        out = BytesIO()
        img.save(out, format="JPEG", quality=75)
        return out.getvalue()
    except ImportError:
        logger.error("Pillow required for window capture")
        return None


def _get_window_bounds_sync(hwnd: int) -> Region | None:
    """Get window screen-space bounds."""
    rect = RECT()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return Region(
            x=rect.left, y=rect.top,
            width=rect.right - rect.left,
            height=rect.bottom - rect.top,
        )
    return None


class WindowsWindowCaptureBackend:
    """Window-targeted capture for Windows."""

    async def find_window(self, app: str | None = None, title: str | None = None) -> dict | None:
        return await asyncio.to_thread(_find_window_sync, app, title)

    async def capture_window(self, window_id: int) -> bytes | None:
        return await asyncio.to_thread(_capture_window_sync, window_id)

    async def get_window_bounds(self, window_id: int) -> Region | None:
        return await asyncio.to_thread(_get_window_bounds_sync, window_id)
