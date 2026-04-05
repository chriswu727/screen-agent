"""Input Guardian — safety layer for screen agent operations.

Two core safety guarantees:
1. Scope Lock: Agent can only operate within designated apps/regions.
2. User Priority: Any user keyboard/mouse activity immediately pauses
   the agent. It resumes only after the user has been idle for a
   configurable cooldown period.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from screen_agent.config import GuardianConfig
from screen_agent.types import Point, Region

logger = logging.getLogger(__name__)


class AgentState(Enum):
    IDLE = "idle"
    ACTIVE = "active"
    PAUSED = "paused"
    LOCKED_OUT = "locked"


@dataclass
class ScopeLock:
    """Where the agent is allowed to operate.

    allowed_apps: app/window name patterns (case-insensitive partial match).
                  Empty set = no restriction.
    region:       optional pixel region constraint.
    """

    allowed_apps: set[str] = field(default_factory=set)
    region: Region | None = None

    def contains_point(self, point: Point) -> bool:
        if self.region is None:
            return True
        return self.region.contains(point)

    def matches_window(self, app: str, title: str) -> bool:
        if not self.allowed_apps:
            return True
        text = f"{app} {title}".lower()
        return any(pattern.lower() in text for pattern in self.allowed_apps)


@dataclass
class ClearanceResult:
    allowed: bool
    reason: str = ""
    waited_ms: float = 0.0


class InputGuardian:
    """Monitors user input and enforces safety constraints.

    Thread-safe: all shared state access is protected by _lock.
    """

    def __init__(self, config: GuardianConfig | None = None):
        self._config = config or GuardianConfig()
        self._state = AgentState.IDLE
        self._scope = ScopeLock()
        self._last_user_input_time: float = 0.0
        self._listeners_started = False
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.Lock()
        self._on_pause_callbacks: list[Callable] = []
        self._on_resume_callbacks: list[Callable] = []
        self._was_paused = False
        self._window_backend = None

    @property
    def state(self) -> AgentState:
        with self._lock:
            if self._state == AgentState.LOCKED_OUT:
                return AgentState.LOCKED_OUT
            if self._is_user_active_unlocked():
                return AgentState.PAUSED
            return self._state

    @property
    def is_user_active(self) -> bool:
        with self._lock:
            return self._is_user_active_unlocked()

    @property
    def seconds_since_user_input(self) -> float:
        with self._lock:
            if self._last_user_input_time == 0:
                return float("inf")
            return time.monotonic() - self._last_user_input_time

    @property
    def scope(self) -> ScopeLock:
        with self._lock:
            return self._scope

    def start(self) -> None:
        """Start monitoring user input."""
        if self._listeners_started or not self._config.enabled:
            return

        try:
            from pynput import keyboard, mouse
        except ImportError:
            logger.warning(
                "pynput not installed — input guardian disabled. "
                "Install with: pip install pynput"
            )
            self._config.enabled = False
            return

        def on_activity(*_args):
            self._record_user_input()

        self._mouse_listener = mouse.Listener(
            on_move=on_activity, on_click=on_activity, on_scroll=on_activity,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=on_activity, on_release=on_activity,
        )
        self._mouse_listener.daemon = True
        self._keyboard_listener.daemon = True
        self._mouse_listener.start()
        self._keyboard_listener.start()
        self._listeners_started = True
        logger.info("Guardian started (cooldown=%.1fs)", self._config.cooldown_seconds)

    def stop(self) -> None:
        try:
            if self._mouse_listener:
                self._mouse_listener.stop()
        except Exception as e:
            logger.warning("Failed to stop mouse listener: %s", e)
        try:
            if self._keyboard_listener:
                self._keyboard_listener.stop()
        except Exception as e:
            logger.warning("Failed to stop keyboard listener: %s", e)
        self._listeners_started = False

    def add_app(self, app_name: str) -> None:
        with self._lock:
            self._scope.allowed_apps.add(app_name)
        logger.info("Scope: added '%s' → %s", app_name, self._scope.allowed_apps)

    def remove_app(self, app_name: str) -> None:
        with self._lock:
            self._scope.allowed_apps.discard(app_name)
        logger.info("Scope: removed '%s' → %s", app_name, self._scope.allowed_apps)

    def set_region(self, region: Region | None) -> None:
        with self._lock:
            self._scope.region = region
        logger.info("Scope: region=%s", region)

    def clear_scope(self) -> None:
        with self._lock:
            self._scope = ScopeLock()
        logger.info("Scope cleared")

    def lock(self) -> None:
        with self._lock:
            self._state = AgentState.LOCKED_OUT
        logger.info("Agent LOCKED OUT")

    def unlock(self) -> None:
        with self._lock:
            self._state = AgentState.IDLE
        logger.info("Agent unlocked")

    async def wait_for_clearance(
        self,
        point: Point | None = None,
        timeout: float | None = None,
    ) -> ClearanceResult:
        """Block until it's safe to perform an action.

        Checks: lock state -> coordinate scope -> window scope -> user idle.
        """
        timeout = timeout or self._config.timeout_seconds
        start = time.monotonic()

        # 1. Lock check
        with self._lock:
            if self._state == AgentState.LOCKED_OUT:
                return ClearanceResult(allowed=False, reason="Agent is locked out")

            # 2. Coordinate scope check
            if point is not None and not self._scope.contains_point(point):
                region_str = str(self._scope.region) if self._scope.region else "none"
                return ClearanceResult(
                    allowed=False,
                    reason=(
                        f"Coordinate {point} outside allowed region. "
                        f"Region: {region_str}, Allowed apps: {sorted(self._scope.allowed_apps)}"
                    ),
                )

            # Copy allowed_apps for window check outside lock
            has_app_scope = bool(self._scope.allowed_apps)

        # 3. Window scope check (async, outside lock)
        if has_app_scope:
            match = await self._check_active_window()
            if not match:
                with self._lock:
                    return ClearanceResult(
                        allowed=False,
                        reason=(
                            f"Active window not in allowed apps: "
                            f"{sorted(self._scope.allowed_apps)}"
                        ),
                    )

        # 4. Wait for user idle
        if not self._config.enabled:
            return ClearanceResult(allowed=True, waited_ms=0)

        while True:
            with self._lock:
                user_active = self._is_user_active_unlocked()

            if not user_active:
                break

            elapsed = time.monotonic() - start
            if elapsed > timeout:
                return ClearanceResult(
                    allowed=False,
                    reason=f"User still active after {timeout}s timeout",
                    waited_ms=elapsed * 1000,
                )

            if not self._was_paused:
                self._was_paused = True
                with self._lock:
                    self._state = AgentState.PAUSED
                logger.info("Paused — waiting for user idle")
                for cb in self._on_pause_callbacks:
                    cb()

            await asyncio.sleep(self._config.check_interval_seconds)

        # Cleared
        waited_ms = (time.monotonic() - start) * 1000
        if self._was_paused:
            self._was_paused = False
            logger.info("Resumed after %.0fms", waited_ms)
            for cb in self._on_resume_callbacks:
                cb()

        with self._lock:
            self._state = AgentState.ACTIVE
        return ClearanceResult(allowed=True, waited_ms=waited_ms)

    def on_pause(self, callback: Callable) -> None:
        self._on_pause_callbacks.append(callback)

    def on_resume(self, callback: Callable) -> None:
        self._on_resume_callbacks.append(callback)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "state": self.state.value,
                "user_active": self._is_user_active_unlocked(),
                "seconds_since_input": round(self.seconds_since_user_input, 1),
                "cooldown": self._config.cooldown_seconds,
                "scope": {
                    "allowed_apps": sorted(self._scope.allowed_apps),
                    "region": (
                        {"x": self._scope.region.x, "y": self._scope.region.y,
                         "width": self._scope.region.width, "height": self._scope.region.height}
                        if self._scope.region else None
                    ),
                },
                "guardian_enabled": self._config.enabled,
            }

    # ── Private ���─────────────────────────────────────────────────────

    def _is_user_active_unlocked(self) -> bool:
        """Check user activity. Caller MUST hold self._lock."""
        if not self._config.enabled:
            return False
        if self._last_user_input_time == 0:
            return False
        return (time.monotonic() - self._last_user_input_time) < self._config.cooldown_seconds

    def _record_user_input(self) -> None:
        with self._lock:
            self._last_user_input_time = time.monotonic()

    async def _check_active_window(self) -> bool:
        """Check if the currently active window matches allowed apps."""
        try:
            if self._window_backend is None:
                from screen_agent.platform import get_window_backend
                self._window_backend = get_window_backend()

            active = await self._window_backend.get_active_window()
            if active is None:
                return False
            with self._lock:
                return self._scope.matches_window(active.app, active.title)
        except Exception as e:
            logger.debug("Active window check failed: %s", e)
            return True  # fail-open: don't block if we can't check
