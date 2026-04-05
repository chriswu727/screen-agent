"""Tests for coordinate system management."""

from screen_agent.platform.coords import CoordinateSpace
from screen_agent.types import Point, Region


class TestCoordinateSpace:
    def test_no_scaling(self):
        cs = CoordinateSpace(scale_factor=1.0, screen_width=1920, screen_height=1080)
        p = Point(100, 200)
        assert cs.logical_to_physical(p) == Point(100, 200)
        assert cs.physical_to_logical(p) == Point(100, 200)

    def test_retina_2x(self):
        cs = CoordinateSpace(scale_factor=2.0, screen_width=1470, screen_height=956)
        p = Point(100, 200)
        phys = cs.logical_to_physical(p)
        assert phys == Point(200, 400)
        assert cs.physical_to_logical(phys) == p

    def test_fractional_scaling(self):
        # e.g., macOS "looks like 1470" on a 2560-wide display
        cs = CoordinateSpace(
            scale_factor=2560 / 1470, screen_width=1470, screen_height=956
        )
        p = Point(735, 478)  # center of screen
        phys = cs.logical_to_physical(p)
        assert phys.x > p.x  # physical is larger
        back = cs.physical_to_logical(phys)
        # Round-trip may lose a pixel due to int truncation
        assert abs(back.x - p.x) <= 1
        assert abs(back.y - p.y) <= 1

    def test_region_scaling(self):
        cs = CoordinateSpace(scale_factor=2.0, screen_width=1920, screen_height=1080)
        r = Region(10, 20, 100, 200)
        phys = cs.logical_to_physical_region(r)
        assert phys.x == 20
        assert phys.width == 200
        back = cs.physical_to_logical_region(phys)
        assert back == r

    def test_contains(self):
        cs = CoordinateSpace(scale_factor=1.0, screen_width=1920, screen_height=1080)
        assert cs.contains(Point(0, 0))
        assert cs.contains(Point(1920, 1080))
        assert not cs.contains(Point(-1, 0))
        assert not cs.contains(Point(0, 1081))

    def test_contains_retina(self):
        cs = CoordinateSpace(scale_factor=2.0, screen_width=1470, screen_height=956)
        # Logical bounds, not physical
        assert cs.contains(Point(1470, 956))
        assert not cs.contains(Point(1471, 0))
