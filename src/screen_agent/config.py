"""Centralized configuration for screen-agent.

All tunable parameters live here. No magic numbers in other modules.
Supports environment variable overrides for deployment flexibility.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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
            try:
                val = float(v)
                if val < 0:
                    logger.warning("SCREEN_AGENT_COOLDOWN must be >= 0, got %s; using default", v)
                else:
                    config.guardian.cooldown_seconds = val
            except ValueError:
                logger.warning("Invalid SCREEN_AGENT_COOLDOWN value: %r; using default", v)

        if os.environ.get("SCREEN_AGENT_GUARDIAN_DISABLED") == "1":
            config.guardian.enabled = False

        if v := os.environ.get("SCREEN_AGENT_INPUT_BACKENDS"):
            backends = [b.strip() for b in v.split(",") if b.strip()]
            valid = {"ax", "cgevent", "pyautogui"}
            invalid = [b for b in backends if b not in valid]
            if invalid:
                logger.warning("Unknown input backends ignored: %s", invalid)
            backends = [b for b in backends if b in valid]
            if backends:
                config.input.backend_order = backends

        if v := os.environ.get("SCREEN_AGENT_MAX_DIMENSION"):
            try:
                val = int(v)
                if val < 100:
                    logger.warning("SCREEN_AGENT_MAX_DIMENSION must be >= 100, got %s; using default", v)
                else:
                    config.capture.max_dimension = val
            except ValueError:
                logger.warning("Invalid SCREEN_AGENT_MAX_DIMENSION value: %r; using default", v)

        if v := os.environ.get("SCREEN_AGENT_LOG_LEVEL"):
            config.log_level = v.upper()

        return config
