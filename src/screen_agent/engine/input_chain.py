"""Input backend chain with automatic fallback.

Implements Chain of Responsibility: tries each input backend in
priority order. If one fails, moves to the next. All attempts
are logged for observability.

Default chain on macOS: AX -> CGEvent -> pyautogui
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass

from screen_agent.errors import InputDeliveryError
from screen_agent.platform.protocols import InputBackend
from screen_agent.types import ActionResult, Point

logger = logging.getLogger(__name__)


@dataclass
class BackendStats:
    """Telemetry for a single backend."""

    success: int = 0
    failure: int = 0

    @property
    def total(self) -> int:
        return self.success + self.failure

    @property
    def success_rate(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0


class InputChain:
    """Orchestrates multiple input backends with automatic fallback.

    On each action, tries backends in priority order. The first
    backend that returns True wins. If all fail, raises
    InputDeliveryError with details of each attempt.

    Tracks per-backend success/failure statistics for observability.
    """

    def __init__(self, backends: list[InputBackend]):
        self._backends = backends
        self._stats: dict[str, dict[str, BackendStats]] = defaultdict(
            lambda: defaultdict(BackendStats)
        )
        self._stats_lock = threading.Lock()

    @property
    def backend_names(self) -> list[str]:
        """Names of all registered backends."""
        return [b.name for b in self._backends]

    @property
    def stats(self) -> dict[str, dict[str, BackendStats]]:
        """Per-backend, per-action statistics."""
        with self._stats_lock:
            return dict(self._stats)

    def stats_summary(self) -> dict[str, dict]:
        """Human-readable stats summary."""
        with self._stats_lock:
            result = {}
            for backend_name, actions in self._stats.items():
                result[backend_name] = {
                    action: {
                        "success": s.success,
                        "failure": s.failure,
                        "rate": f"{s.success_rate:.0%}",
                    }
                    for action, s in actions.items()
                }
            return result

    async def click(
        self, point: Point, button: str = "left", clicks: int = 1
    ) -> ActionResult:
        return await self._try_all(
            "click", point=point, button=button, clicks=clicks
        )

    async def type_text(self, text: str) -> ActionResult:
        return await self._try_all("type_text", text=text)

    async def press_key(
        self, key: str, modifiers: list[str] | None = None
    ) -> ActionResult:
        return await self._try_all(
            "press_key", key=key, modifiers=modifiers
        )

    async def scroll(self, amount: int, point: Point | None = None) -> ActionResult:
        return await self._try_all("scroll", amount=amount, point=point)

    async def move(self, point: Point) -> ActionResult:
        return await self._try_all("move", point=point)

    async def drag(
        self, start: Point, end: Point, button: str = "left"
    ) -> ActionResult:
        return await self._try_all(
            "drag", start=start, end=end, button=button
        )

    async def _try_all(self, action: str, **kwargs) -> ActionResult:
        """Try each backend in order. First success wins."""
        attempts: list[tuple[str, str]] = []
        start_time = time.monotonic()

        for backend in self._backends:
            try:
                method = getattr(backend, action)
                success = await method(**kwargs)
                if success:
                    self._record(backend.name, action, success=True)
                    elapsed = (time.monotonic() - start_time) * 1000
                    logger.info(
                        "Action '%s' succeeded via '%s' in %.1fms",
                        action, backend.name, elapsed,
                    )
                    return ActionResult(
                        success=True,
                        action=action,
                        backend_used=backend.name,
                        details=_sanitize_details(kwargs),
                    )
                attempts.append((backend.name, "returned False"))
            except Exception as e:
                attempts.append((backend.name, str(e)))
                logger.debug(
                    "Backend '%s' failed for '%s': %s",
                    backend.name, action, e,
                )

            self._record(backend.name, action, success=False)

        raise InputDeliveryError(action, attempts)

    def _record(self, backend: str, action: str, *, success: bool) -> None:
        with self._stats_lock:
            stats = self._stats[backend][action]
            if success:
                stats.success += 1
            else:
                stats.failure += 1


def _sanitize_details(kwargs: dict) -> dict:
    """Convert kwargs to JSON-serializable format."""
    result = {}
    for k, v in kwargs.items():
        if isinstance(v, Point):
            result[k] = {"x": v.x, "y": v.y}
        elif v is not None:
            result[k] = v
    return result
