"""Centralized configuration for screen-agent.

All tunable parameters live here. No magic numbers in other modules.
Supports environment variable overrides for deployment flexibility.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class GuardianConfig:
    """Safety system configuration."""

    cooldown_seconds: float = 1.5
    check_interval_seconds: float = 0.1
    timeout_seconds: float = 30.0
    enabled: bool = True


@dataclass
class CaptureConfig:
    """Screenshot capture configuration."""

    max_dimension: int = 2000
    jpeg_quality: int = 80
    default_format: str = "PNG"


@dataclass
class InputConfig:
    """Input delivery configuration."""

    backend_order: list[str] = field(
        default_factory=lambda: ["ax", "cgevent", "pyautogui"]
    )
    pause_between_actions: float = 0.05
    mouse_move_duration: float = 0.3
    drag_duration: float = 0.5
    type_interval: float = 0.02
    post_action_delay: float = 0.3


@dataclass
class ScreenAgentConfig:
    """Top-level configuration container."""

    guardian: GuardianConfig = field(default_factory=GuardianConfig)
    capture: CaptureConfig = field(default_factory=CaptureConfig)
    input: InputConfig = field(default_factory=InputConfig)
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> ScreenAgentConfig:
        """Create config with environment variable overrides.

        Environment variables:
            SCREEN_AGENT_COOLDOWN: Guardian cooldown in seconds
            SCREEN_AGENT_GUARDIAN_DISABLED: Set to "1" to disable guardian
            SCREEN_AGENT_INPUT_BACKENDS: Comma-separated backend order
            SCREEN_AGENT_MAX_DIMENSION: Max screenshot dimension in pixels
            SCREEN_AGENT_LOG_LEVEL: Logging level (DEBUG, INFO, WARNING, ERROR)
        """
        config = cls()

        if v := os.environ.get("SCREEN_AGENT_COOLDOWN"):
            config.guardian.cooldown_seconds = float(v)

        if os.environ.get("SCREEN_AGENT_GUARDIAN_DISABLED") == "1":
            config.guardian.enabled = False

        if v := os.environ.get("SCREEN_AGENT_INPUT_BACKENDS"):
            config.input.backend_order = [b.strip() for b in v.split(",")]

        if v := os.environ.get("SCREEN_AGENT_MAX_DIMENSION"):
            config.capture.max_dimension = int(v)

        if v := os.environ.get("SCREEN_AGENT_LOG_LEVEL"):
            config.log_level = v.upper()

        return config
