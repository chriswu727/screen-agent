"""Shared type definitions for screen-agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict


@dataclass(frozen=True, slots=True)
class Point:
    """Logical screen coordinate (not physical pixels)."""

    x: int
    y: int

    def __str__(self) -> str:
        return f"({self.x}, {self.y})"


@dataclass(frozen=True, slots=True)
class Region:
    """Rectangular screen region in logical coordinates."""

    x: int
    y: int
    width: int
    height: int

    def contains(self, point: Point) -> bool:
        return (
            self.x <= point.x < self.x + self.width
            and self.y <= point.y < self.y + self.height
        )

    @property
    def center(self) -> Point:
        return Point(self.x + self.width // 2, self.y + self.height // 2)


@dataclass(slots=True)
class WindowInfo:
    """Information about a visible window."""

    app: str
    title: str
    pid: int | None = None
    x: int = 0
    y: int = 0
    width: int = 0
    height: int = 0


@dataclass(slots=True)
class TextBlock:
    """A recognized text region from OCR."""

    text: str
    confidence: float
    bbox: Region
    center: Point


class ScreenshotResult(TypedDict):
    """Result from a screen capture operation."""

    image_base64: str
    mime_type: str
    width: int
    height: int
    scale_factor: float


@dataclass(slots=True)
class ActionResult:
    """Result from an input action (click, type, etc.)."""

    success: bool
    action: str
    backend_used: str
    details: dict | None = None
    error: str | None = None
    guardian_waited_ms: float = 0.0


@dataclass(slots=True)
class UIElement:
    """A UI element from the accessibility tree."""

    element_id: str
    role: str
    title: str = ""
    value: str = ""
    position: Point | None = None
    size: tuple[int, int] | None = None
    actions: list[str] = field(default_factory=list)
    children_count: int = 0
