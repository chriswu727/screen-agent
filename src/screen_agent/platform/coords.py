"""Coordinate system management.

Handles logical <-> physical pixel conversion for Retina and scaled
displays. All MCP tool parameters use logical coordinates; backends
that need physical pixels use CoordinateSpace for conversion.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from functools import lru_cache

from screen_agent.types import Point, Region


@dataclass(frozen=True, slots=True)
class CoordinateSpace:
    """Encapsulates display coordinate transformation."""

    scale_factor: float
    screen_width: int  # logical
    screen_height: int  # logical

    def logical_to_physical(self, point: Point) -> Point:
        return Point(
            int(point.x * self.scale_factor),
            int(point.y * self.scale_factor),
        )

    def physical_to_logical(self, point: Point) -> Point:
        return Point(
            int(point.x / self.scale_factor),
            int(point.y / self.scale_factor),
        )

    def logical_to_physical_region(self, region: Region) -> Region:
        return Region(
            x=int(region.x * self.scale_factor),
            y=int(region.y * self.scale_factor),
            width=int(region.width * self.scale_factor),
            height=int(region.height * self.scale_factor),
        )

    def physical_to_logical_region(self, region: Region) -> Region:
        return Region(
            x=int(region.x / self.scale_factor),
            y=int(region.y / self.scale_factor),
            width=int(region.width / self.scale_factor),
            height=int(region.height / self.scale_factor),
        )

    def contains(self, point: Point) -> bool:
        """Check if a logical point is within screen bounds."""
        return 0 <= point.x <= self.screen_width and 0 <= point.y <= self.screen_height


@lru_cache(maxsize=1)
def get_coordinate_space() -> CoordinateSpace:
    """Detect the current display's coordinate space.

    On macOS, uses Quartz to determine Retina scaling.
    On other platforms, defaults to 1.0 scale factor.
    """
    if platform.system() == "Darwin":
        return _detect_macos_coordinates()
    return CoordinateSpace(scale_factor=1.0, screen_width=1920, screen_height=1080)


def _detect_macos_coordinates() -> CoordinateSpace:
    try:
        import Quartz

        main_display = Quartz.CGMainDisplayID()
        physical_width = Quartz.CGDisplayPixelsWide(main_display)
        mode = Quartz.CGDisplayCopyDisplayMode(main_display)
        logical_width = Quartz.CGDisplayModeGetWidth(mode)
        logical_height = Quartz.CGDisplayModeGetHeight(mode)
        scale = physical_width / logical_width if logical_width else 1.0
        return CoordinateSpace(
            scale_factor=scale,
            screen_width=logical_width,
            screen_height=logical_height,
        )
    except (ImportError, Exception):
        # Quartz not available; fall back to mss for dimensions
        try:
            import mss

            with mss.mss() as sct:
                monitor = sct.monitors[1]
                return CoordinateSpace(
                    scale_factor=1.0,
                    screen_width=monitor["width"],
                    screen_height=monitor["height"],
                )
        except Exception:
            return CoordinateSpace(scale_factor=1.0, screen_width=1920, screen_height=1080)
