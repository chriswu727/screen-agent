"""Tests for shared type definitions."""

from screen_agent.types import ActionResult, Point, Region, UIElement, WindowInfo


class TestPoint:
    def test_creation(self):
        p = Point(10, 20)
        assert p.x == 10
        assert p.y == 20

    def test_str(self):
        assert str(Point(10, 20)) == "(10, 20)"

    def test_immutable(self):
        p = Point(1, 2)
        try:
            p.x = 3  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except AttributeError:
            pass


class TestRegion:
    def test_contains_inside(self):
        r = Region(10, 10, 100, 100)
        assert r.contains(Point(50, 50))

    def test_contains_edge(self):
        r = Region(10, 10, 100, 100)
        assert r.contains(Point(10, 10))
        assert r.contains(Point(110, 110))

    def test_contains_outside(self):
        r = Region(10, 10, 100, 100)
        assert not r.contains(Point(0, 0))
        assert not r.contains(Point(200, 200))

    def test_center(self):
        r = Region(0, 0, 100, 200)
        assert r.center == Point(50, 100)


class TestWindowInfo:
    def test_defaults(self):
        w = WindowInfo(app="Chrome", title="Google")
        assert w.pid is None
        assert w.x == 0


class TestActionResult:
    def test_success(self):
        r = ActionResult(success=True, action="click", backend_used="cgevent")
        assert r.success
        assert r.guardian_waited_ms == 0.0

    def test_failure(self):
        r = ActionResult(
            success=False, action="click", backend_used="ax", error="not found"
        )
        assert not r.success
        assert r.error == "not found"


class TestUIElement:
    def test_defaults(self):
        e = UIElement(element_id="0.1", role="AXButton")
        assert e.title == ""
        assert e.actions == []
        assert e.children_count == 0
