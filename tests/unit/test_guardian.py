"""Tests for the Input Guardian safety system."""

import pytest

from screen_agent.config import GuardianConfig
from screen_agent.engine.guardian import (
    AgentState,
    InputGuardian,
    ScopeLock,
)
from screen_agent.types import Point, Region


class TestScopeLock:
    def test_no_restrictions(self):
        scope = ScopeLock()
        assert scope.contains_point(Point(999, 999))
        assert scope.matches_window("Chrome", "Google")

    def test_region_contains(self):
        scope = ScopeLock(region=Region(100, 100, 200, 200))
        assert scope.contains_point(Point(150, 150))
        assert not scope.contains_point(Point(50, 50))

    def test_app_matching(self):
        scope = ScopeLock(allowed_apps={"Chrome", "Figma"})
        assert scope.matches_window("Google Chrome", "Tab")
        assert scope.matches_window("Figma", "Design")
        assert not scope.matches_window("Slack", "Channel")

    def test_app_matching_case_insensitive(self):
        scope = ScopeLock(allowed_apps={"chrome"})
        assert scope.matches_window("Google Chrome", "Tab")

    def test_empty_apps_allows_all(self):
        scope = ScopeLock(allowed_apps=set())
        assert scope.matches_window("AnyApp", "AnyTitle")


class TestGuardianState:
    def test_initial_state(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        assert g.state == AgentState.IDLE

    def test_lock_unlock(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.lock()
        assert g.state == AgentState.LOCKED_OUT
        g.unlock()
        assert g.state == AgentState.IDLE

    def test_seconds_since_input_initial(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        assert g.seconds_since_user_input == float("inf")


class TestGuardianScope:
    def test_add_remove_app(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.add_app("Chrome")
        assert "Chrome" in g.scope.allowed_apps
        g.remove_app("Chrome")
        assert "Chrome" not in g.scope.allowed_apps

    def test_set_region(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        r = Region(0, 0, 500, 500)
        g.set_region(r)
        assert g.scope.region == r
        g.set_region(None)
        assert g.scope.region is None

    def test_clear_scope(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.add_app("Chrome")
        g.set_region(Region(0, 0, 100, 100))
        g.clear_scope()
        assert len(g.scope.allowed_apps) == 0
        assert g.scope.region is None


class TestGuardianClearance:
    @pytest.mark.asyncio
    async def test_locked_out_denied(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.lock()
        result = await g.wait_for_clearance()
        assert not result.allowed
        assert "locked" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_disabled_guardian_allows(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        result = await g.wait_for_clearance()
        assert result.allowed

    @pytest.mark.asyncio
    async def test_coordinate_outside_region(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.set_region(Region(100, 100, 200, 200))
        result = await g.wait_for_clearance(point=Point(50, 50))
        assert not result.allowed
        assert "outside" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_coordinate_inside_region(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.set_region(Region(100, 100, 200, 200))
        result = await g.wait_for_clearance(point=Point(150, 150))
        assert result.allowed

    @pytest.mark.asyncio
    async def test_no_point_skips_region_check(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.set_region(Region(100, 100, 200, 200))
        result = await g.wait_for_clearance()
        assert result.allowed


class TestGuardianStatus:
    def test_status_dict(self):
        g = InputGuardian(GuardianConfig(enabled=False))
        g.add_app("Chrome")
        status = g.get_status()
        assert status["state"] == "idle"
        assert "Chrome" in status["scope"]["allowed_apps"]
        assert status["guardian_enabled"] is False


class TestGuardianStop:
    def test_stop_without_start(self):
        """stop() should be safe to call even if never started."""
        g = InputGuardian(GuardianConfig(enabled=False))
        g.stop()  # should not raise
