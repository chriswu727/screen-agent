"""
Screen Agent Testing — AI-powered visual E2E testing.

No selectors. No DOM. The AI sees the screen and tests like a real user.
"""

from screen_agent.testing.session import TestSession, TestStep, StepStatus
from screen_agent.testing.verifier import ScreenVerifier
from screen_agent.testing.reporter import TestReporter

__all__ = ["TestSession", "TestStep", "StepStatus", "ScreenVerifier", "TestReporter"]
