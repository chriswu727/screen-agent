"""Coordinate system management for macOS.

Handles logical <-> physical pixel conversion for Retina and scaled
displays. All MCP tool parameters use logical coordinates; backends
that need physical pixels use CoordinateSpace for conversion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

from screen_agent.types import Point, Region

logger = logging.getLogger(__name__)


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
        return 0 <= point.x < self.screen_width and 0 <= point.y < self.screen_height


@lru_cache(maxsize=1)
def get_coordinate_space() -> CoordinateSpace:
    """Detect the current macOS display's coordinate space via Quartz."""
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
    except ImportError:
        logger.warning("Quartz not available, falling back to mss for display info")
    except Exception as e:
        logger.warning("Quartz display detection failed: %s, falling back to mss", e)

    # Fallback: use mss (still accurate on macOS, just no Retina scale)
    try:
        import mss

        with mss.mss() as sct:
            if len(sct.monitors) < 2:
                logger.warning("No monitor detected by mss, using defaults")
                return CoordinateSpace(scale_factor=1.0, screen_width=1920, screen_height=1080)
            monitor = sct.monitors[1]
            return CoordinateSpace(
                scale_factor=1.0,
                screen_width=monitor["width"],
                screen_height=monitor["height"],
            )
    except Exception as e:
        logger.warning("mss fallback failed: %s, using 1920x1080 defaults", e)
        return CoordinateSpace(scale_factor=1.0, screen_width=1920, screen_height=1080)
