"""Platform abstraction protocols.

Each protocol defines a capability that platform-specific backends must
implement. The engine layer programs against these protocols, never
against concrete implementations.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from screen_agent.types import (
    Point,
    Region,
    ScreenshotResult,
    TextBlock,
    WindowInfo,
)


@runtime_checkable
class InputBackend(Protocol):
    """Platform-specific input delivery.

    Multiple backends can coexist; the InputChain tries them in priority
    order and falls back automatically on failure.
    """

    @property
    def name(self) -> str:
        """Short identifier for this backend (e.g., 'ax', 'cgevent')."""
        ...

    def available(self) -> bool:
        """Return True if this backend can function on the current system."""
        ...

    async def click(
        self, point: Point, button: str = "left", clicks: int = 1
    ) -> bool:
        """Click at logical coordinates. Return True on success."""
        ...

    async def type_text(self, text: str) -> bool:
        """Type text string. Return True on success."""
        ...

    async def press_key(
        self, key: str, modifiers: list[str] | None = None
    ) -> bool:
        """Press a key with optional modifiers. Return True on success."""
        ...

    async def scroll(self, amount: int, point: Point | None = None) -> bool:
        """Scroll by amount (positive=up). Return True on success."""
        ...

    async def move(self, point: Point) -> bool:
        """Move cursor to logical coordinates. Return True on success."""
        ...

    async def drag(
        self, start: Point, end: Point, button: str = "left"
    ) -> bool:
        """Click-drag from start to end. Return True on success."""
        ...


@runtime_checkable
class CaptureBackend(Protocol):
    """Platform-specific screen capture."""

    async def capture(
        self, region: Region | None = None
    ) -> ScreenshotResult:
        """Capture the screen or a region. Returns base64-encoded image."""
        ...

    def get_scale_factor(self) -> float:
        """Return display scale factor (2.0 for Retina, 1.0 for standard)."""
        ...


@runtime_checkable
class WindowBackend(Protocol):
    """Platform-specific window management."""

    async def list_windows(self) -> list[WindowInfo]:
        """List all visible windows."""
        ...

    async def get_active_window(self) -> WindowInfo | None:
        """Get the currently focused window."""
        ...

    async def focus_window(self, title: str) -> bool:
        """Bring a window to front by partial title match. Return True on success."""
        ...


@runtime_checkable
class OCRBackend(Protocol):
    """Text recognition from screen images."""

    def available(self) -> bool:
        """Return True if OCR is available on this system."""
        ...

    async def recognize(
        self, image_data: bytes, lang: str = "en"
    ) -> list[TextBlock]:
        """Recognize text in an image. Returns text blocks with positions."""
        ...
