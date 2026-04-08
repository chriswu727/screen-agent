"""
MCP tool definitions and handlers for the testing layer.

These tools are registered alongside the existing screen-agent tools,
giving Claude Code the ability to run structured visual E2E tests.

Workflow:
  1. test_start("Login flow test")
  2. test_step("Open login page")          → auto-captures before screenshot
  3. [agent does actions via existing screen-agent tools: click, type_text, etc.]
  4. test_verify(text="Welcome Dashboard")  → auto-captures after screenshot + OCR verify
  5. test_step("Try invalid password")      → next step
  6. ...
  7. test_end()                             → generates markdown report
"""

from __future__ import annotations

from mcp.types import Tool

from screen_agent.mcp.handlers import handler, ctx
from screen_agent.testing.session import TestSession, Screenshot
from screen_agent.testing.verifier import ScreenVerifier
from screen_agent.testing.reporter import TestReporter


# ---------------------------------------------------------------------------
# Module-level state for the active test session
# ---------------------------------------------------------------------------
_session: TestSession | None = None
_verifier: ScreenVerifier | None = None


def _get_session() -> TestSession:
    if _session is None:
        raise RuntimeError("No active test session. Call test_start first.")
    return _session


def _get_verifier() -> ScreenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = ScreenVerifier(capture=ctx().capture, ocr=ctx().ocr)
    return _verifier


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
TEST_TOOLS: list[Tool] = [
    Tool(
        name="test_start",
        description=(
            "Start a visual E2E test session. All subsequent test_step and test_verify "
            "calls will be recorded. Call test_end to finish and generate a report."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Test name (e.g., 'Login flow')"},
                "description": {"type": "string", "description": "What this test verifies", "default": ""},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="test_step",
        description=(
            "Begin a new test step. Automatically captures a 'before' screenshot. "
            "After performing actions (click, type, etc.), call test_verify to check the result."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "description": {"type": "string", "description": "What this step does (e.g., 'Click the Login button')"},
            },
            "required": ["description"],
        },
    ),
    Tool(
        name="test_verify",
        description=(
            "Verify the current test step. Captures an 'after' screenshot and runs verification. "
            "Supported methods: "
            "'text' — verify text is visible on screen via OCR. "
            "'no_text' — verify text is NOT visible. "
            "'changed' — verify the screen changed since the step began. "
            "'unchanged' — verify the screen did NOT change."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["text", "no_text", "changed", "unchanged"],
                    "description": "Verification method",
                },
                "expected": {
                    "type": "string",
                    "description": "Expected text (for 'text' and 'no_text' methods)",
                    "default": "",
                },
                "action_performed": {
                    "type": "string",
                    "description": "Description of what action was taken (e.g., 'Clicked Login at (450, 320)')",
                    "default": "",
                },
            },
            "required": ["method"],
        },
    ),
    Tool(
        name="test_end",
        description=(
            "End the test session and generate a markdown report with all steps, "
            "screenshots, and verification results. Returns the report path and summary."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "output_dir": {
                    "type": "string",
                    "description": "Directory to save the report (default: current directory)",
                    "default": ".",
                },
                "include_screenshots": {
                    "type": "boolean",
                    "description": "Embed screenshots in report (default: true)",
                    "default": True,
                },
            },
        },
    ),
    Tool(
        name="test_status",
        description="Get the current test session status — steps completed, pass/fail counts, active step.",
        inputSchema={"type": "object", "properties": {}},
    ),
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@handler("test_start")
async def handle_test_start(args: dict) -> list:
    """Start a new test session."""
    global _session, _verifier

    name = args["name"]
    description = args.get("description", "")

    # End any existing session
    if _session and not _session.is_finished:
        _session.finish()

    _session = TestSession(name=name, description=description)
    _verifier = ScreenVerifier(capture=ctx().capture, ocr=ctx().ocr)

    return [{"type": "text", "text": f'{{"status": "started", "name": "{name}"}}'}]


@handler("test_step")
async def handle_test_step(args: dict) -> list:
    """Begin a new test step with automatic before-screenshot."""
    session = _get_session()
    verifier = _get_verifier()

    description = args["description"]

    # Begin step
    step = session.begin_step(description)

    # Auto-capture before screenshot
    step.before_screenshot = await verifier.capture_screenshot()

    return [{"type": "text", "text": (
        f'{{"status": "step_started", "step": {step.index}, '
        f'"description": "{description}", '
        f'"before_screenshot": "captured"}}'
    )}]


@handler("test_verify")
async def handle_test_verify(args: dict) -> list:
    """Verify the current step and capture after-screenshot."""
    session = _get_session()
    verifier = _get_verifier()

    step = session.current_step
    if step is None:
        return [{"type": "text", "text": '{"error": "No active step. Call test_step first."}'}]

    method = args["method"]
    expected = args.get("expected", "")
    action = args.get("action_performed", "")

    if action:
        step.action = action

    # Capture after screenshot
    step.after_screenshot = await verifier.capture_screenshot()

    # Run verification
    if method == "text":
        step.verification = await verifier.verify_text_visible(expected, step.after_screenshot)
    elif method == "no_text":
        step.verification = await verifier.verify_text_not_visible(expected, step.after_screenshot)
    elif method == "changed":
        if step.before_screenshot:
            step.verification = await verifier.verify_screen_changed(step.before_screenshot, step.after_screenshot)
        else:
            step.verification = None
    elif method == "unchanged":
        if step.before_screenshot:
            step.verification = await verifier.verify_screen_unchanged(step.before_screenshot, step.after_screenshot)
        else:
            step.verification = None

    # Finish step
    session.finish_step()

    result = step.to_dict()
    emoji = "✅" if step.status.value == "passed" else "❌"

    return [{"type": "text", "text": (
        f'{emoji} Step {step.index} {step.status.value.upper()}: {step.description}\n'
        f'{{"step": {step.index}, "status": "{step.status.value}", '
        f'"verification": {{"method": "{method}", "passed": {str(step.verification.passed).lower()}, '
        f'"expected": "{expected}", "actual": "{step.verification.actual[:100] if step.verification else ""}"}},'
        f'"duration_ms": {step.duration_ms:.0f}}}'
    )}]


@handler("test_end")
async def handle_test_end(args: dict) -> list:
    """End session and generate report."""
    session = _get_session()

    output_dir = args.get("output_dir", ".")
    include_screenshots = args.get("include_screenshots", True)

    summary = session.finish()
    report_path = TestReporter.save(session, output_dir, include_screenshots)

    emoji = "✅" if session.all_passed else "❌"

    return [{"type": "text", "text": (
        f'{emoji} Test "{session.name}" complete: '
        f'{session.passed_count}/{len(session.steps)} passed '
        f'({session.total_duration_ms:.0f}ms)\n'
        f'Report saved to: {report_path}\n'
        f'{{"summary": {{"name": "{session.name}", "all_passed": {str(session.all_passed).lower()}, '
        f'"passed": {session.passed_count}, "failed": {session.failed_count}, '
        f'"total": {len(session.steps)}, "duration_ms": {session.total_duration_ms:.0f}, '
        f'"report_path": "{report_path}"}}}}'
    )}]


@handler("test_status")
async def handle_test_status(args: dict) -> list:
    """Get current session status."""
    if _session is None:
        return [{"type": "text", "text": '{"active": false}'}]

    summary = _session.summary()
    current = _session.current_step

    return [{"type": "text", "text": (
        f'{{"active": true, "name": "{_session.name}", '
        f'"total_steps": {len(_session.steps)}, '
        f'"passed": {_session.passed_count}, "failed": {_session.failed_count}, '
        f'"current_step": {current.index if current else "null"}, '
        f'"is_finished": {str(_session.is_finished).lower()}}}'
    )}]
