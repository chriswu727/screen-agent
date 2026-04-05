"""Platform backend factory — macOS only.

Returns macOS-specific backend implementations.
Backends are lazily imported to avoid pulling in optional dependencies
until they are actually needed.
"""

from __future__ import annotations

import logging
import platform
from typing import TYPE_CHECKING

from screen_agent.config import ScreenAgentConfig
from screen_agent.errors import PlatformNotSupportedError

if TYPE_CHECKING:
    from screen_agent.platform.protocols import (
        CaptureBackend,
        InputBackend,
        OCRBackend,
        WindowBackend,
    )

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


def _require_macos(operation: str) -> None:
    if _SYSTEM != "Darwin":
        raise PlatformNotSupportedError(operation, _SYSTEM)


def get_input_backends(config: ScreenAgentConfig) -> list[InputBackend]:
    """Return available input backends in configured priority order."""
    _require_macos("input backends")

    registry: dict[str, type] = {}

    try:
        from screen_agent.platform.macos.input_ax import AXInputBackend

        registry["ax"] = AXInputBackend
    except ImportError:
        logger.debug("AX input backend not available")

    try:
        from screen_agent.platform.macos.input_cg import CGEventInputBackend

        registry["cgevent"] = CGEventInputBackend
    except ImportError:
        logger.debug("CGEvent input backend not available")

    try:
        from screen_agent.platform.macos.input_pyautogui import PyAutoGUIInputBackend

        registry["pyautogui"] = PyAutoGUIInputBackend
    except ImportError:
        logger.debug("pyautogui input backend not available")

    backends: list[InputBackend] = []
    for name in config.input.backend_order:
        if name in registry:
            backend = registry[name](config.input)
            if backend.available():
                backends.append(backend)
                logger.info("Input backend '%s' available", name)
            else:
                logger.info("Input backend '%s' not available", name)
    return backends


def get_capture_backend() -> CaptureBackend:
    """Return the macOS capture backend."""
    _require_macos("screen capture")
    from screen_agent.platform.macos.capture import MacOSCaptureBackend

    return MacOSCaptureBackend()


def get_window_backend() -> WindowBackend:
    """Return the macOS window management backend."""
    _require_macos("window management")
    from screen_agent.platform.macos.window import MacOSWindowBackend

    return MacOSWindowBackend()


def get_ocr_backend() -> OCRBackend | None:
    """Return the Vision OCR backend if available, or None."""
    _require_macos("OCR")
    try:
        from screen_agent.platform.macos.vision import VisionOCRBackend

        backend = VisionOCRBackend()
        if backend.available():
            return backend
    except ImportError:
        logger.debug("Apple Vision Framework not available")
    return None
