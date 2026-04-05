"""Platform detection and backend factory.

Detects the current OS and returns the appropriate backend
implementations. Backends are lazily imported to avoid pulling
in platform-specific dependencies on the wrong OS.
"""

from __future__ import annotations

import logging
import platform
from typing import TYPE_CHECKING

from screen_agent.config import ScreenAgentConfig

if TYPE_CHECKING:
    from screen_agent.platform.protocols import (
        CaptureBackend,
        InputBackend,
        OCRBackend,
        WindowBackend,
    )

logger = logging.getLogger(__name__)

_SYSTEM = platform.system()


def get_input_backends(config: ScreenAgentConfig) -> list[InputBackend]:
    """Return available input backends in configured priority order."""
    if _SYSTEM == "Darwin":
        return _get_macos_input_backends(config)
    if _SYSTEM == "Linux":
        return _get_linux_input_backends(config)
    logger.warning("No input backends available for %s", _SYSTEM)
    return []


def get_capture_backend() -> CaptureBackend:
    """Return the capture backend for the current platform."""
    if _SYSTEM == "Darwin":
        from screen_agent.platform.macos.capture import MacOSCaptureBackend

        return MacOSCaptureBackend()

    from screen_agent.platform.macos.capture import MacOSCaptureBackend

    # mss-based capture works cross-platform
    return MacOSCaptureBackend()


def get_window_backend() -> WindowBackend:
    """Return the window management backend for the current platform."""
    if _SYSTEM == "Darwin":
        from screen_agent.platform.macos.window import MacOSWindowBackend

        return MacOSWindowBackend()
    if _SYSTEM == "Linux":
        from screen_agent.platform.linux.window import LinuxWindowBackend

        return LinuxWindowBackend()
    from screen_agent.platform.macos.window import MacOSWindowBackend

    return MacOSWindowBackend()


def get_ocr_backend() -> OCRBackend | None:
    """Return the OCR backend if available, or None."""
    if _SYSTEM == "Darwin":
        try:
            from screen_agent.platform.macos.vision import VisionOCRBackend

            backend = VisionOCRBackend()
            if backend.available():
                return backend
        except ImportError:
            logger.debug("Apple Vision Framework not available")
    return None


def _get_macos_input_backends(config: ScreenAgentConfig) -> list[InputBackend]:
    """Build macOS input backend list in configured priority order."""
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


def _get_linux_input_backends(config: ScreenAgentConfig) -> list[InputBackend]:
    """Build Linux input backend list."""
    backends: list[InputBackend] = []
    try:
        from screen_agent.platform.macos.input_pyautogui import PyAutoGUIInputBackend

        backend = PyAutoGUIInputBackend(config.input)
        if backend.available():
            backends.append(backend)
    except ImportError:
        pass
    return backends
