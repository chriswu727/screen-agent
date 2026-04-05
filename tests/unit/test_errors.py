"""Tests for exception hierarchy."""

from screen_agent.errors import (
    CaptureError,
    CoordinateOutOfBoundsError,
    ElementNotFoundError,
    GuardianBlockedError,
    InputDeliveryError,
    PermissionDeniedError,
    PlatformNotSupportedError,
    ScreenAgentError,
)


class TestErrorHierarchy:
    def test_all_inherit_from_base(self):
        errors = [
            PlatformNotSupportedError("click", "Windows"),
            PermissionDeniedError("Accessibility"),
            ElementNotFoundError("AXButton 'Submit'"),
            GuardianBlockedError("user active"),
            InputDeliveryError("click", [("ax", "no element"), ("cg", "denied")]),
            CoordinateOutOfBoundsError(9999, 9999),
            CaptureError("mss failed"),
        ]
        for err in errors:
            assert isinstance(err, ScreenAgentError)

    def test_error_codes_unique(self):
        codes = [
            ScreenAgentError.code,
            PlatformNotSupportedError.code,
            PermissionDeniedError.code,
            ElementNotFoundError.code,
            GuardianBlockedError.code,
            InputDeliveryError.code,
            CoordinateOutOfBoundsError.code,
            CaptureError.code,
        ]
        assert len(codes) == len(set(codes))


class TestInputDeliveryError:
    def test_message_includes_all_attempts(self):
        err = InputDeliveryError(
            "click", [("ax", "no element"), ("cgevent", "permission denied")]
        )
        assert "ax: no element" in str(err)
        assert "cgevent: permission denied" in str(err)

    def test_to_dict(self):
        err = InputDeliveryError("click", [("ax", "failed")])
        d = err.to_dict()
        assert d["code"] == "INPUT_DELIVERY_FAILED"
        assert d["details"]["action"] == "click"
        assert len(d["details"]["attempts"]) == 1


class TestGuardianBlockedError:
    def test_to_dict_includes_status(self):
        err = GuardianBlockedError(
            "App not in allowlist",
            status={"allowed_apps": ["Chrome"], "active_app": "Slack"},
        )
        d = err.to_dict()
        assert d["code"] == "GUARDIAN_BLOCKED"
        assert d["details"]["active_app"] == "Slack"


class TestPlatformError:
    def test_message(self):
        err = PlatformNotSupportedError("accessibility", "Linux")
        assert "Linux" in str(err)
        assert err.operation == "accessibility"


class TestPermissionError:
    def test_hint(self):
        err = PermissionDeniedError(
            "Accessibility",
            hint="Open System Settings > Privacy > Accessibility",
        )
        assert "System Settings" in str(err)
