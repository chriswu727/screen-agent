"""Tests for centralized configuration."""

import os

from screen_agent.config import (
    CaptureConfig,
    GuardianConfig,
    InputConfig,
    ScreenAgentConfig,
)


class TestDefaults:
    def test_guardian_defaults(self):
        c = GuardianConfig()
        assert c.cooldown_seconds == 1.5
        assert c.enabled is True

    def test_input_defaults(self):
        c = InputConfig()
        assert c.backend_order == ["ax", "cgevent", "pyautogui"]
        assert c.mouse_move_duration == 0.3

    def test_capture_defaults(self):
        c = CaptureConfig()
        assert c.max_dimension == 2000
        assert c.jpeg_quality == 80

    def test_top_level_defaults(self):
        c = ScreenAgentConfig()
        assert c.log_level == "INFO"
        assert c.guardian.enabled is True


class TestEnvOverrides:
    def test_cooldown(self, monkeypatch):
        monkeypatch.setenv("SCREEN_AGENT_COOLDOWN", "3.0")
        c = ScreenAgentConfig.from_env()
        assert c.guardian.cooldown_seconds == 3.0

    def test_guardian_disabled(self, monkeypatch):
        monkeypatch.setenv("SCREEN_AGENT_GUARDIAN_DISABLED", "1")
        c = ScreenAgentConfig.from_env()
        assert c.guardian.enabled is False

    def test_input_backends(self, monkeypatch):
        monkeypatch.setenv("SCREEN_AGENT_INPUT_BACKENDS", "cgevent,pyautogui")
        c = ScreenAgentConfig.from_env()
        assert c.input.backend_order == ["cgevent", "pyautogui"]

    def test_max_dimension(self, monkeypatch):
        monkeypatch.setenv("SCREEN_AGENT_MAX_DIMENSION", "1568")
        c = ScreenAgentConfig.from_env()
        assert c.capture.max_dimension == 1568

    def test_log_level(self, monkeypatch):
        monkeypatch.setenv("SCREEN_AGENT_LOG_LEVEL", "debug")
        c = ScreenAgentConfig.from_env()
        assert c.log_level == "DEBUG"

    def test_no_env_vars(self):
        # Ensure clean environment
        for key in [
            "SCREEN_AGENT_COOLDOWN",
            "SCREEN_AGENT_GUARDIAN_DISABLED",
            "SCREEN_AGENT_INPUT_BACKENDS",
            "SCREEN_AGENT_MAX_DIMENSION",
            "SCREEN_AGENT_LOG_LEVEL",
        ]:
            os.environ.pop(key, None)
        c = ScreenAgentConfig.from_env()
        assert c.guardian.cooldown_seconds == 1.5
        assert c.input.backend_order == ["ax", "cgevent", "pyautogui"]
