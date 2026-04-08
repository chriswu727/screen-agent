"""
Test session management.

A session tracks a sequence of steps. Each step has:
- A description (what we're testing)
- A before screenshot (automatic)
- An action (what the agent did)
- An after screenshot (automatic)
- A verification result (pass/fail + reason)

The session collects all of this into a structure the reporter can consume.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class Screenshot:
    """A captured screenshot with metadata."""
    image_base64: str
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class Verification:
    """Result of verifying a step."""
    passed: bool
    method: str  # "ocr", "visual", "screenshot_diff", "manual"
    expected: str = ""
    actual: str = ""
    confidence: float = 1.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TestStep:
    """A single test step with full evidence chain."""
    index: int
    description: str
    status: StepStatus = StepStatus.PENDING
    action: str = ""  # what the agent did ("clicked Login button at (450, 320)")
    before_screenshot: Screenshot | None = None
    after_screenshot: Screenshot | None = None
    verification: Verification | None = None
    error_message: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at) * 1000
        return 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "description": self.description,
            "status": self.status.value,
            "action": self.action,
            "duration_ms": round(self.duration_ms, 1),
            "has_before_screenshot": self.before_screenshot is not None,
            "has_after_screenshot": self.after_screenshot is not None,
            "verification": {
                "passed": self.verification.passed,
                "method": self.verification.method,
                "expected": self.verification.expected,
                "actual": self.verification.actual,
            } if self.verification else None,
            "error": self.error_message or None,
        }


class TestSession:
    """
    Manages a test session — a sequence of steps with evidence collection.

    Usage by the LLM (via MCP tools):
        session = TestSession("Login flow test")
        step = session.begin_step("Open login page")
        step.before_screenshot = Screenshot(...)
        step.action = "Navigated to localhost:3000/login"
        step.after_screenshot = Screenshot(...)
        step.verification = Verification(passed=True, method="ocr", expected="Login", actual="Login")
        session.finish_step(passed=True)
        ...
        session.finish()
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.steps: list[TestStep] = []
        self.started_at: float = time.time()
        self.finished_at: float = 0.0
        self._current_step: TestStep | None = None

    @property
    def current_step(self) -> TestStep | None:
        return self._current_step

    @property
    def is_finished(self) -> bool:
        return self.finished_at > 0

    @property
    def passed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.steps if s.status == StepStatus.FAILED)

    @property
    def total_duration_ms(self) -> float:
        end = self.finished_at or time.time()
        return (end - self.started_at) * 1000

    @property
    def all_passed(self) -> bool:
        return all(s.status == StepStatus.PASSED for s in self.steps)

    def begin_step(self, description: str) -> TestStep:
        """Start a new test step. Returns the step for the caller to populate."""
        if self._current_step and self._current_step.status == StepStatus.RUNNING:
            # Auto-finish previous step as error if caller forgot
            self._current_step.status = StepStatus.ERROR
            self._current_step.error_message = "Step was abandoned (next step started)"
            self._current_step.finished_at = time.time()

        step = TestStep(
            index=len(self.steps) + 1,
            description=description,
            status=StepStatus.RUNNING,
            started_at=time.time(),
        )
        self.steps.append(step)
        self._current_step = step
        return step

    def finish_step(self, passed: bool | None = None, error: str = "") -> TestStep:
        """Mark the current step as finished."""
        step = self._current_step
        if step is None:
            raise RuntimeError("No active step to finish")

        step.finished_at = time.time()

        if error:
            step.status = StepStatus.ERROR
            step.error_message = error
        elif passed is not None:
            step.status = StepStatus.PASSED if passed else StepStatus.FAILED
        elif step.verification:
            step.status = StepStatus.PASSED if step.verification.passed else StepStatus.FAILED
        else:
            step.status = StepStatus.PASSED  # no verification = assume passed

        self._current_step = None
        return step

    def finish(self) -> dict[str, Any]:
        """End the session. Returns summary."""
        # Auto-finish any dangling step
        if self._current_step and self._current_step.status == StepStatus.RUNNING:
            self.finish_step(error="Session ended with step still running")

        self.finished_at = time.time()
        return self.summary()

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "total_steps": len(self.steps),
            "passed": self.passed_count,
            "failed": self.failed_count,
            "all_passed": self.all_passed,
            "duration_ms": round(self.total_duration_ms, 1),
            "steps": [s.to_dict() for s in self.steps],
        }
