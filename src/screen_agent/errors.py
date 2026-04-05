"""Exception hierarchy for screen-agent.

All exceptions inherit from ScreenAgentError, providing structured error
codes that MCP clients can handle programmatically.
"""

from __future__ import annotations


class ScreenAgentError(Exception):
    """Base exception for all screen-agent errors."""

    code: str = "SCREEN_AGENT_ERROR"

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}


class PlatformNotSupportedError(ScreenAgentError):
    """Current OS does not support this operation."""

    code = "PLATFORM_NOT_SUPPORTED"

    def __init__(self, operation: str, platform: str):
        super().__init__(f"'{operation}' is not supported on {platform}")
        self.operation = operation
        self.platform = platform


class PermissionDeniedError(ScreenAgentError):
    """Missing OS permission (Screen Recording, Accessibility, etc.)."""

    code = "PERMISSION_DENIED"

    def __init__(self, permission: str, hint: str = ""):
        msg = f"Missing permission: {permission}"
        if hint:
            msg += f". {hint}"
        super().__init__(msg)
        self.permission = permission


class ElementNotFoundError(ScreenAgentError):
    """UI element or text not found on screen."""

    code = "ELEMENT_NOT_FOUND"

    def __init__(self, query: str):
        super().__init__(f"Element not found: {query}")
        self.query = query


class GuardianBlockedError(ScreenAgentError):
    """Action blocked by Input Guardian safety system."""

    code = "GUARDIAN_BLOCKED"

    def __init__(self, reason: str, status: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.status = status or {}

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.reason, "details": self.status}


class InputDeliveryError(ScreenAgentError):
    """All input backends failed to deliver the action."""

    code = "INPUT_DELIVERY_FAILED"

    def __init__(self, action: str, attempts: list[tuple[str, str]]):
        self.action = action
        self.attempts = attempts
        details = "; ".join(f"{name}: {err}" for name, err in attempts)
        super().__init__(f"All backends failed for '{action}': {details}")

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "message": str(self),
            "details": {
                "action": self.action,
                "attempts": [
                    {"backend": name, "error": err} for name, err in self.attempts
                ],
            },
        }


class CoordinateOutOfBoundsError(ScreenAgentError):
    """Coordinates outside allowed region or screen bounds."""

    code = "COORDINATE_OUT_OF_BOUNDS"

    def __init__(self, x: int, y: int, reason: str = ""):
        msg = f"Coordinate ({x}, {y}) out of bounds"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class CaptureError(ScreenAgentError):
    """Screenshot capture failed."""

    code = "CAPTURE_FAILED"
