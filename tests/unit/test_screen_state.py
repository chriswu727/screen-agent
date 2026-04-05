"""Tests for screen state cache."""

import time

from screen_agent.engine.screen_state import ScreenState
from screen_agent.types import ScreenshotResult, WindowInfo


def _make_screenshot(**overrides) -> ScreenshotResult:
    defaults = {
        "image_base64": "abc123",
        "mime_type": "image/png",
        "width": 1920,
        "height": 1080,
        "scale_factor": 2.0,
    }
    defaults.update(overrides)
    return ScreenshotResult(**defaults)


class TestScreenState:
    def test_empty_cache_returns_none(self):
        state = ScreenState(ttl_seconds=10.0)
        assert state.last_screenshot is None
        assert state.last_windows == []

    def test_update_and_retrieve_screenshot(self):
        state = ScreenState(ttl_seconds=10.0)
        shot = _make_screenshot()
        state.update_screenshot(shot)
        assert state.last_screenshot is not None
        assert state.last_screenshot["width"] == 1920

    def test_screenshot_ttl_expiry(self):
        state = ScreenState(ttl_seconds=0.01)
        state.update_screenshot(_make_screenshot())
        time.sleep(0.02)
        assert state.last_screenshot is None

    def test_update_and_retrieve_windows(self):
        state = ScreenState(ttl_seconds=10.0)
        windows = [WindowInfo(app="Chrome", title="Tab"), WindowInfo(app="Finder", title="Home")]
        state.update_windows(windows)
        result = state.last_windows
        assert len(result) == 2
        assert result[0].app == "Chrome"

    def test_windows_ttl_expiry(self):
        state = ScreenState(ttl_seconds=0.01)
        state.update_windows([WindowInfo(app="Chrome", title="Tab")])
        time.sleep(0.02)
        assert state.last_windows == []

    def test_windows_returns_copy(self):
        """Returned list should not be the same object as internal list."""
        state = ScreenState(ttl_seconds=10.0)
        state.update_windows([WindowInfo(app="Chrome", title="Tab")])
        result = state.last_windows
        result.append(WindowInfo(app="Hack", title="Inject"))
        assert len(state.last_windows) == 1  # internal state unchanged

    def test_invalidate(self):
        state = ScreenState(ttl_seconds=10.0)
        state.update_screenshot(_make_screenshot())
        state.update_windows([WindowInfo(app="A", title="B")])
        state.invalidate()
        assert state.last_screenshot is None
        assert state.last_windows == []
