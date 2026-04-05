"""Input Guardian — safety layer for screen agent operations.

Two core safety guarantees:
1. Scope Lock: Agent can only operate within a designated window or region.
2. User Priority: Any user keyboard/mouse activity immediately pauses the agent.
   The agent only resumes after the user has been idle for a configurable cooldown.

This ensures the agent never fights the user for control and never touches
anything outside the explicitly permitted area.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

logger = logging.getLogger("screen-agent.guardian")


class AgentState(Enum):
    IDLE = "idle"           # Agent is not doing anything
    ACTIVE = "active"       # Agent is executing actions
    PAUSED = "paused"       # Paused because user is interacting
    LOCKED_OUT = "locked"   # User explicitly disabled agent control


@dataclass
class ScopeLock:
    """Defines where the agent is allowed to operate.

    allowed_apps: set of app/window name patterns (case-insensitive partial match).
                  Empty set means no app restriction (all apps allowed).
    region:       optional pixel region constraint.
    """
    allowed_apps: set[str] = field(default_factory=set)
    region: dict | None = None  # {"x": int, "y": int, "width": int, "height": int}

    def contains(self, x: int, y: int) -> bool:
        if self.region is None:
            return True
        r = self.region
        return (
            r["x"] <= x <= r["x"] + r["width"]
            and r["y"] <= y <= r["y"] + r["height"]
        )

    def matches_window(self, app: str, title: str) -> bool:
        if not self.allowed_apps:
            return True
        text = f"{app} {title}".lower()
        return any(pattern.lower() in text for pattern in self.allowed_apps)


@dataclass
class GuardianConfig:
    cooldown: float = 1.5       # Seconds of user inactivity before agent can resume
    check_interval: float = 0.1  # How often to poll user activity status
    enabled: bool = True         # Master switch


class InputGuardian:
    """Monitors user input and enforces safety constraints.

    Usage:
        guardian = InputGuardian()
        guardian.start()

        # Before any agent action:
        await guardian.wait_for_clearance(x=400, y=300)
        # ^ blocks until user is idle AND coordinates are within scope

        guardian.stop()
    """

    def __init__(self, config: GuardianConfig | None = None):
        self.config = config or GuardianConfig()
        self._state = AgentState.IDLE
        self._scope: ScopeLock | None = None
        self._last_user_input_time: float = 0.0
        self._listeners_started = False
        self._mouse_listener = None
        self._keyboard_listener = None
        self._lock = threading.Lock()
        self._on_pause_callbacks: list[Callable] = []
        self._on_resume_callbacks: list[Callable] = []
        self._was_paused = False

    # ── Public API ───────────────────────────────────────────────────

    @property
    def state(self) -> AgentState:
        if self._state == AgentState.LOCKED_OUT:
            return AgentState.LOCKED_OUT
        if self._is_user_active():
            return AgentState.PAUSED
        return self._state

    @property
    def is_user_active(self) -> bool:
        return self._is_user_active()

    @property
    def seconds_since_user_input(self) -> float:
        if self._last_user_input_time == 0:
            return float("inf")
        return time.time() - self._last_user_input_time

    def start(self) -> None:
        """Start monitoring user input. Call once at server startup."""
        if self._listeners_started or not self.config.enabled:
            return

        try:
            from pynput import keyboard, mouse
        except ImportError:
            logger.warning(
                "pynput not installed — input guardian disabled. "
                "Install with: pip install pynput"
            )
            self.config.enabled = False
            return

        def on_mouse_activity(*_args):
            self._record_user_input()

        def on_key_activity(*_args):
            self._record_user_input()

        self._mouse_listener = mouse.Listener(
            on_move=on_mouse_activity,
            on_click=on_mouse_activity,
            on_scroll=on_mouse_activity,
        )
        self._keyboard_listener = keyboard.Listener(
            on_press=on_key_activity,
            on_release=on_key_activity,
        )

        self._mouse_listener.daemon = True
        self._keyboard_listener.daemon = True
        self._mouse_listener.start()
        self._keyboard_listener.start()
        self._listeners_started = True
        logger.info(
            "Input guardian started (cooldown=%.1fs)", self.config.cooldown
        )

    def stop(self) -> None:
        """Stop monitoring."""
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._keyboard_listener:
            self._keyboard_listener.stop()
        self._listeners_started = False
        logger.info("Input guardian stopped")

    def _ensure_scope(self) -> ScopeLock:
        if self._scope is None:
            self._scope = ScopeLock()
        return self._scope

    def add_app(self, app_name: str) -> ScopeLock:
        """Add an app to the allowed list. Agent can only operate in allowed apps."""
        scope = self._ensure_scope()
        scope.allowed_apps.add(app_name)
        logger.info("Scope: added '%s' → allowed apps: %s", app_name, scope.allowed_apps)
        return scope

    def remove_app(self, app_name: str) -> ScopeLock:
        """Remove an app from the allowed list."""
        scope = self._ensure_scope()
        scope.allowed_apps.discard(app_name)
        logger.info("Scope: removed '%s' → allowed apps: %s", app_name, scope.allowed_apps)
        return scope

    def set_region(self, region: dict | None) -> ScopeLock:
        """Restrict agent to a pixel region. Pass None to remove region constraint."""
        scope = self._ensure_scope()
        scope.region = region
        logger.info("Scope: region set to %s", region)
        return scope

    def clear_scope(self) -> None:
        """Remove all scope restrictions (apps + region)."""
        self._scope = None
        logger.info("Scope cleared — agent can operate anywhere")

    def lock(self) -> None:
        """Completely disable agent control (user-initiated kill switch)."""
        self._state = AgentState.LOCKED_OUT
        logger.info("Agent LOCKED OUT by user")

    def unlock(self) -> None:
        """Re-enable agent control."""
        self._state = AgentState.IDLE
        logger.info("Agent unlocked")

    async def wait_for_clearance(
        self,
        x: int | None = None,
        y: int | None = None,
        timeout: float = 30.0,
    ) -> ClearanceResult:
        """Block until it's safe to perform an action.

        Returns ClearanceResult with status and reason.
        Raises TimeoutError if user doesn't release control within timeout.
        """
        # Check lock state
        if self._state == AgentState.LOCKED_OUT:
            return ClearanceResult(
                allowed=False,
                reason="Agent is locked out. User must explicitly unlock.",
            )

        # Check scope
        if x is not None and y is not None and self._scope:
            if not self._scope.contains(x, y):
                return ClearanceResult(
                    allowed=False,
                    reason=(
                        f"Coordinates ({x}, {y}) are outside the allowed scope. "
                        f"Scope: {self._scope.region or self._scope.window_title}"
                    ),
                )

        # Check window scope
        if self._scope and self._scope.allowed_apps:
            match = await self._check_active_window_matches()
            if not match:
                return ClearanceResult(
                    allowed=False,
                    reason=(
                        f"Active window is not in allowed apps. "
                        f"Allowed: {sorted(self._scope.allowed_apps)}"
                    ),
                )

        # Wait for user to be idle
        if not self.config.enabled:
            return ClearanceResult(allowed=True)

        start = time.time()
        while self._is_user_active():
            if time.time() - start > timeout:
                return ClearanceResult(
                    allowed=False,
                    reason=f"User still active after {timeout}s timeout",
                )

            if not self._was_paused:
                self._was_paused = True
                self._state = AgentState.PAUSED
                logger.info("Paused — waiting for user to release control")
                for cb in self._on_pause_callbacks:
                    cb()

            await asyncio.sleep(self.config.check_interval)

        # User is idle, clear to proceed
        if self._was_paused:
            self._was_paused = False
            self._state = AgentState.ACTIVE
            logger.info(
                "Resumed — user idle for %.1fs", self.config.cooldown
            )
            for cb in self._on_resume_callbacks:
                cb()

        self._state = AgentState.ACTIVE
        return ClearanceResult(allowed=True)

    def on_pause(self, callback: Callable) -> None:
        """Register callback for when agent gets paused."""
        self._on_pause_callbacks.append(callback)

    def on_resume(self, callback: Callable) -> None:
        """Register callback for when agent resumes."""
        self._on_resume_callbacks.append(callback)

    def get_status(self) -> dict:
        """Return current guardian status as a dict (for MCP tool response)."""
        return {
            "state": self.state.value,
            "user_active": self._is_user_active(),
            "seconds_since_input": round(self.seconds_since_user_input, 1),
            "cooldown": self.config.cooldown,
            "scope": {
                "allowed_apps": sorted(self._scope.allowed_apps) if self._scope else [],
                "region": self._scope.region if self._scope else None,
            },
            "guardian_enabled": self.config.enabled,
        }

    # ── Private ──────────────────────────────────────────────────────

    def _is_user_active(self) -> bool:
        if not self.config.enabled:
            return False
        return self.seconds_since_user_input < self.config.cooldown

    def _record_user_input(self) -> None:
        with self._lock:
            self._last_user_input_time = time.time()

    async def _check_active_window_matches(self) -> bool:
        from screen_agent.window import get_active_window

        active = await get_active_window()
        return self._scope.matches_window(
            active.get("app", ""),
            active.get("title", ""),
        )


@dataclass
class ClearanceResult:
    allowed: bool
    reason: str = ""


# ── Module-level singleton ───────────────────────────────────────────────

_guardian: InputGuardian | None = None


def get_guardian() -> InputGuardian:
    """Get or create the global InputGuardian instance."""
    global _guardian
    if _guardian is None:
        _guardian = InputGuardian()
    return _guardian
