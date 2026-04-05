"""Integration tests for MCP handler flow with mock backends.

Tests the full handler dispatch pipeline: argument parsing -> guardian
clearance -> backend calls -> response formatting. Uses mock backends
so these tests run on any platform (including CI on Ubuntu).
"""

from __future__ import annotations

import base64
import json

import pytest

from screen_agent.config import GuardianConfig
from screen_agent.engine.guardian import InputGuardian
from screen_agent.engine.input_chain import InputChain
from screen_agent.mcp.handlers import (
    HandlerContext,
    get_handler,
    set_context,
)
from screen_agent.mcp.tools import TOOLS
from screen_agent.types import (
    Point,
    Region,
    ScreenshotResult,
    TextBlock,
    WindowInfo,
)


# ── Mock Backends ────────────────────────────────────────────────

class MockInputBackend:
    """Records all calls for assertion."""

    def __init__(self, name: str = "mock"):
        self._name = name
        self.calls: list[tuple[str, dict]] = []

    @property
    def name(self) -> str:
        return self._name

    def available(self) -> bool:
        return True

    async def click(self, point: Point, button: str = "left", clicks: int = 1) -> bool:
        self.calls.append(("click", {"point": point, "button": button, "clicks": clicks}))
        return True

    async def type_text(self, text: str) -> bool:
        self.calls.append(("type_text", {"text": text}))
        return True

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        self.calls.append(("press_key", {"key": key, "modifiers": modifiers}))
        return True

    async def scroll(self, amount: int, point: Point | None = None) -> bool:
        self.calls.append(("scroll", {"amount": amount, "point": point}))
        return True

    async def move(self, point: Point) -> bool:
        self.calls.append(("move", {"point": point}))
        return True

    async def drag(self, start: Point, end: Point, button: str = "left") -> bool:
        self.calls.append(("drag", {"start": start, "end": end, "button": button}))
        return True


# 1x1 red pixel PNG, base64-encoded
_TINY_PNG_B64 = base64.b64encode(
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
    b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
).decode("ascii")


class MockCaptureBackend:
    def __init__(self):
        self.capture_count = 0

    async def capture(self, region: Region | None = None, resize: bool = True) -> ScreenshotResult:
        self.capture_count += 1
        return ScreenshotResult(
            image_base64=_TINY_PNG_B64,
            mime_type="image/png",
            width=1920,
            height=1080,
            scale_factor=2.0,
        )

    def get_scale_factor(self) -> float:
        return 2.0


class MockWindowBackend:
    def __init__(self):
        self.windows = [
            WindowInfo(app="Chrome", title="Google", pid=123, x=0, y=0, width=1200, height=800),
            WindowInfo(app="Finder", title="Documents", pid=456, x=100, y=100, width=600, height=400),
        ]
        self.active = self.windows[0]
        self.focus_calls: list[str] = []

    async def list_windows(self) -> list[WindowInfo]:
        return self.windows

    async def get_active_window(self) -> WindowInfo | None:
        return self.active

    async def focus_window(self, title: str) -> bool:
        self.focus_calls.append(title)
        return any(title.lower() in w.title.lower() for w in self.windows)


class MockOCRBackend:
    def __init__(self):
        self._available = True
        self.blocks = [
            TextBlock(text="Submit", confidence=0.99,
                      bbox=Region(100, 200, 80, 30), center=Point(140, 215)),
            TextBlock(text="Cancel", confidence=0.97,
                      bbox=Region(200, 200, 80, 30), center=Point(240, 215)),
        ]

    def available(self) -> bool:
        return self._available

    async def recognize(self, image_data: bytes, lang: str = "en") -> list[TextBlock]:
        return self.blocks


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def mock_input():
    return MockInputBackend()


@pytest.fixture()
def mock_capture():
    return MockCaptureBackend()


@pytest.fixture()
def mock_window():
    return MockWindowBackend()


@pytest.fixture()
def mock_ocr():
    return MockOCRBackend()


@pytest.fixture()
def setup_context(mock_input, mock_capture, mock_window, mock_ocr):
    """Wire up all mock backends into the global handler context."""
    guardian = InputGuardian(GuardianConfig(enabled=False))
    chain = InputChain([mock_input])
    set_context(HandlerContext(
        input_chain=chain,
        capture=mock_capture,
        window=mock_window,
        guardian=guardian,
        ocr=mock_ocr,
    ))
    yield {
        "input": mock_input,
        "capture": mock_capture,
        "window": mock_window,
        "ocr": mock_ocr,
        "guardian": guardian,
        "chain": chain,
    }
    set_context(None)  # cleanup


def _parse_text(content_list) -> dict | list:
    """Extract JSON from handler response."""
    for item in content_list:
        if hasattr(item, "text"):
            return json.loads(item.text)
    raise ValueError("No text content in response")


# ── Tool Schema Tests ────────────────────────────────────────────

class TestToolSchemas:
    """Verify tool definitions are well-formed."""

    def test_all_tools_have_handlers(self):
        for tool in TOOLS:
            assert get_handler(tool.name) is not None, f"No handler for tool '{tool.name}'"

    def test_tool_names_unique(self):
        names = [t.name for t in TOOLS]
        assert len(names) == len(set(names))

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            assert tool.inputSchema is not None
            assert tool.inputSchema["type"] == "object"

    def test_tool_count(self):
        assert len(TOOLS) == 19


# ── Perception Handler Tests ─────────────────────────────────────

class TestCaptureScreenHandler:
    @pytest.mark.asyncio
    async def test_full_screen(self, setup_context):
        handler = get_handler("capture_screen")
        result = await handler({})
        # Should return image + text description
        assert len(result) == 2
        assert result[0].type == "image"
        assert result[0].data == _TINY_PNG_B64
        assert "1920x1080" in result[1].text

    @pytest.mark.asyncio
    async def test_with_region(self, setup_context):
        handler = get_handler("capture_screen")
        result = await handler({"region": {"x": 10, "y": 20, "width": 100, "height": 200}})
        assert result[0].type == "image"
        assert setup_context["capture"].capture_count == 1


class TestListWindowsHandler:
    @pytest.mark.asyncio
    async def test_returns_windows(self, setup_context):
        handler = get_handler("list_windows")
        result = await handler({})
        data = _parse_text(result)
        assert len(data) == 2
        assert data[0]["app"] == "Chrome"
        assert data[1]["app"] == "Finder"


class TestGetActiveWindowHandler:
    @pytest.mark.asyncio
    async def test_returns_active(self, setup_context):
        handler = get_handler("get_active_window")
        result = await handler({})
        data = _parse_text(result)
        assert data["app"] == "Chrome"
        assert data["pid"] == 123

    @pytest.mark.asyncio
    async def test_no_active_window(self, setup_context):
        setup_context["window"].active = None
        handler = get_handler("get_active_window")
        result = await handler({})
        data = _parse_text(result)
        assert "error" in data


# ── Input Handler Tests ──────────────────────────────────────────

class TestClickHandler:
    @pytest.mark.asyncio
    async def test_basic_click(self, setup_context):
        handler = get_handler("click")
        result = await handler({"x": 100, "y": 200})
        data = _parse_text(result)
        assert data["action"] == "click"
        assert data["success"] is True
        assert data["backend_used"] == "mock"
        # Verify mock was called correctly
        assert len(setup_context["input"].calls) == 1
        call = setup_context["input"].calls[0]
        assert call[0] == "click"
        assert call[1]["point"] == Point(100, 200)

    @pytest.mark.asyncio
    async def test_double_click(self, setup_context):
        handler = get_handler("click")
        await handler({"x": 50, "y": 50, "button": "right", "clicks": 2})
        call = setup_context["input"].calls[0]
        assert call[1]["button"] == "right"
        assert call[1]["clicks"] == 2

    @pytest.mark.asyncio
    async def test_negative_coordinates_rejected(self, setup_context):
        from screen_agent.errors import CoordinateOutOfBoundsError
        handler = get_handler("click")
        with pytest.raises(CoordinateOutOfBoundsError):
            await handler({"x": -1, "y": 100})

    @pytest.mark.asyncio
    async def test_invalid_coordinates_rejected(self, setup_context):
        from screen_agent.errors import CoordinateOutOfBoundsError
        handler = get_handler("click")
        with pytest.raises(CoordinateOutOfBoundsError):
            await handler({"x": "abc", "y": 100})

    @pytest.mark.asyncio
    async def test_guardian_blocks_when_locked(self, setup_context):
        setup_context["guardian"].lock()
        handler = get_handler("click")
        result = await handler({"x": 100, "y": 200})
        data = _parse_text(result)
        assert data["error"]["code"] == "GUARDIAN_BLOCKED"
        # Backend should NOT have been called
        assert len(setup_context["input"].calls) == 0

    @pytest.mark.asyncio
    async def test_guardian_blocks_outside_region(self, setup_context):
        setup_context["guardian"].set_region(Region(0, 0, 50, 50))
        handler = get_handler("click")
        result = await handler({"x": 100, "y": 200})
        data = _parse_text(result)
        assert data["error"]["code"] == "GUARDIAN_BLOCKED"


class TestTypeTextHandler:
    @pytest.mark.asyncio
    async def test_type_text(self, setup_context):
        handler = get_handler("type_text")
        result = await handler({"text": "hello world"})
        data = _parse_text(result)
        assert data["success"] is True
        assert setup_context["input"].calls[0][1]["text"] == "hello world"

    @pytest.mark.asyncio
    async def test_empty_text_rejected(self, setup_context):
        handler = get_handler("type_text")
        result = await handler({"text": ""})
        data = _parse_text(result)
        assert "error" in data


class TestPressKeyHandler:
    @pytest.mark.asyncio
    async def test_simple_key(self, setup_context):
        handler = get_handler("press_key")
        result = await handler({"key": "enter"})
        data = _parse_text(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_key_with_modifiers(self, setup_context):
        handler = get_handler("press_key")
        await handler({"key": "c", "modifiers": ["command"]})
        call = setup_context["input"].calls[0]
        assert call[1]["key"] == "c"
        assert call[1]["modifiers"] == ["command"]


class TestScrollHandler:
    @pytest.mark.asyncio
    async def test_scroll_no_position(self, setup_context):
        handler = get_handler("scroll")
        result = await handler({"amount": -3})
        data = _parse_text(result)
        assert data["success"] is True
        call = setup_context["input"].calls[0]
        assert call[1]["amount"] == -3
        assert call[1]["point"] is None

    @pytest.mark.asyncio
    async def test_scroll_with_position(self, setup_context):
        handler = get_handler("scroll")
        await handler({"amount": 5, "x": 100, "y": 200})
        call = setup_context["input"].calls[0]
        assert call[1]["point"] == Point(100, 200)


class TestMoveMouseHandler:
    @pytest.mark.asyncio
    async def test_move(self, setup_context):
        handler = get_handler("move_mouse")
        result = await handler({"x": 500, "y": 300})
        data = _parse_text(result)
        assert data["success"] is True


class TestDragHandler:
    @pytest.mark.asyncio
    async def test_drag(self, setup_context):
        handler = get_handler("drag")
        result = await handler({"start_x": 10, "start_y": 20, "end_x": 100, "end_y": 200})
        data = _parse_text(result)
        assert data["success"] is True
        call = setup_context["input"].calls[0]
        assert call[1]["start"] == Point(10, 20)
        assert call[1]["end"] == Point(100, 200)


class TestFocusWindowHandler:
    @pytest.mark.asyncio
    async def test_focus_found(self, setup_context):
        handler = get_handler("focus_window")
        result = await handler({"title": "Google"})
        data = _parse_text(result)
        assert data["success"] is True
        assert setup_context["window"].focus_calls == ["Google"]

    @pytest.mark.asyncio
    async def test_focus_not_found(self, setup_context):
        handler = get_handler("focus_window")
        result = await handler({"title": "Nonexistent"})
        data = _parse_text(result)
        assert data["success"] is False


# ── OCR Handler Tests ────────────────────────────────────────────

class TestOCRHandler:
    @pytest.mark.asyncio
    async def test_ocr_returns_blocks(self, setup_context):
        handler = get_handler("ocr")
        result = await handler({})
        data = _parse_text(result)
        assert len(data) == 2
        assert data[0]["text"] == "Submit"
        assert data[0]["confidence"] == 0.99
        assert data[0]["center"]["x"] == 140

    @pytest.mark.asyncio
    async def test_ocr_unavailable(self, setup_context):
        setup_context["ocr"]._available = False
        handler = get_handler("ocr")
        result = await handler({})
        data = _parse_text(result)
        assert "error" in data
        assert "OCR not available" in data["error"]


class TestFindTextHandler:
    @pytest.mark.asyncio
    async def test_find_existing_text(self, setup_context):
        handler = get_handler("find_text")
        result = await handler({"query": "Submit"})
        data = _parse_text(result)
        assert len(data) == 1
        assert data[0]["text"] == "Submit"

    @pytest.mark.asyncio
    async def test_find_case_insensitive(self, setup_context):
        handler = get_handler("find_text")
        result = await handler({"query": "submit"})
        data = _parse_text(result)
        assert len(data) == 1

    @pytest.mark.asyncio
    async def test_find_not_found(self, setup_context):
        handler = get_handler("find_text")
        result = await handler({"query": "Nonexistent"})
        data = _parse_text(result)
        assert "error" in data
        assert "not found" in data["error"]


class TestClickTextHandler:
    @pytest.mark.asyncio
    async def test_click_text(self, setup_context):
        handler = get_handler("click_text")
        result = await handler({"query": "Cancel"})
        data = _parse_text(result)
        assert data["clicked"] == "Cancel"
        assert data["at"]["x"] == 240
        assert data["success"] is True
        # Verify click was dispatched at center of matched text
        call = setup_context["input"].calls[0]
        assert call[1]["point"] == Point(240, 215)

    @pytest.mark.asyncio
    async def test_click_text_not_found(self, setup_context):
        from screen_agent.errors import ElementNotFoundError
        handler = get_handler("click_text")
        with pytest.raises(ElementNotFoundError):
            await handler({"query": "Missing"})

    @pytest.mark.asyncio
    async def test_click_text_index_out_of_range(self, setup_context):
        from screen_agent.errors import ElementNotFoundError
        handler = get_handler("click_text")
        with pytest.raises(ElementNotFoundError):
            await handler({"query": "Submit", "index": 99})


# ── Guardian Handler Tests ───────────────────────────────────────

class TestGuardianHandlers:
    @pytest.mark.asyncio
    async def test_add_app(self, setup_context):
        handler = get_handler("add_app")
        result = await handler({"app_name": "Chrome"})
        data = _parse_text(result)
        assert "Chrome" in data["scope"]["allowed_apps"]

    @pytest.mark.asyncio
    async def test_remove_app(self, setup_context):
        setup_context["guardian"].add_app("Figma")
        handler = get_handler("remove_app")
        result = await handler({"app_name": "Figma"})
        data = _parse_text(result)
        assert "Figma" not in data["scope"]["allowed_apps"]

    @pytest.mark.asyncio
    async def test_set_region(self, setup_context):
        handler = get_handler("set_region")
        result = await handler({"x": 0, "y": 0, "width": 800, "height": 600})
        data = _parse_text(result)
        assert data["scope"]["region"] == {"x": 0, "y": 0, "width": 800, "height": 600}

    @pytest.mark.asyncio
    async def test_clear_scope(self, setup_context):
        setup_context["guardian"].add_app("Chrome")
        setup_context["guardian"].set_region(Region(0, 0, 100, 100))
        handler = get_handler("clear_scope")
        result = await handler({})
        data = _parse_text(result)
        assert data["scope"]["allowed_apps"] == []
        assert data["scope"]["region"] is None

    @pytest.mark.asyncio
    async def test_get_agent_status(self, setup_context):
        handler = get_handler("get_agent_status")
        result = await handler({})
        data = _parse_text(result)
        assert data["state"] == "idle"
        assert data["guardian_enabled"] is False
        assert "input_backends" in data
        assert "backend_stats" in data
        assert "ocr_available" in data


# ── End-to-end Flow Tests ────────────────────────────────────────

class TestEndToEndFlows:
    """Simulate realistic agent workflows."""

    @pytest.mark.asyncio
    async def test_scope_then_click(self, setup_context):
        """Agent sets scope, then clicks within it."""
        add = get_handler("add_app")
        await add({"app_name": "Chrome"})

        set_region = get_handler("set_region")
        await set_region({"x": 0, "y": 0, "width": 1920, "height": 1080})

        click = get_handler("click")
        result = await click({"x": 500, "y": 300})
        data = _parse_text(result)
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_scope_then_click_outside_blocked(self, setup_context):
        """Agent sets scope, click outside is blocked."""
        set_region = get_handler("set_region")
        await set_region({"x": 0, "y": 0, "width": 100, "height": 100})

        click = get_handler("click")
        result = await click({"x": 500, "y": 300})
        data = _parse_text(result)
        assert data["error"]["code"] == "GUARDIAN_BLOCKED"

    @pytest.mark.asyncio
    async def test_lock_blocks_all_actions(self, setup_context):
        """Locked guardian blocks all input tools."""
        setup_context["guardian"].lock()

        tools_to_test = [
            ("click", {"x": 100, "y": 200}),
            ("type_text", {"text": "hello"}),
            ("press_key", {"key": "enter"}),
            ("scroll", {"amount": 3}),
            ("move_mouse", {"x": 100, "y": 200}),
            ("drag", {"start_x": 0, "start_y": 0, "end_x": 100, "end_y": 100}),
        ]
        for tool_name, args in tools_to_test:
            handler = get_handler(tool_name)
            result = await handler(args)
            data = _parse_text(result)
            assert data["error"]["code"] == "GUARDIAN_BLOCKED", f"{tool_name} should be blocked"

        # No backend calls should have been made
        assert len(setup_context["input"].calls) == 0

    @pytest.mark.asyncio
    async def test_ocr_find_and_click_flow(self, setup_context):
        """Full OCR -> find -> click workflow."""
        # 1. OCR to see what's on screen
        ocr = get_handler("ocr")
        result = await ocr({})
        blocks = _parse_text(result)
        assert any(b["text"] == "Submit" for b in blocks)

        # 2. Find text
        find = get_handler("find_text")
        result = await find({"query": "Submit"})
        matches = _parse_text(result)
        assert matches[0]["center"]["x"] == 140

        # 3. Click the found text
        click_text = get_handler("click_text")
        result = await click_text({"query": "Submit"})
        data = _parse_text(result)
        assert data["clicked"] == "Submit"
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_multi_action_sequence(self, setup_context):
        """Simulate: focus window -> click field -> type text -> press enter."""
        focus = get_handler("focus_window")
        result = await focus({"title": "Google"})
        assert _parse_text(result)["success"] is True

        click = get_handler("click")
        result = await click({"x": 500, "y": 400})
        assert _parse_text(result)["success"] is True

        type_text = get_handler("type_text")
        result = await type_text({"text": "screen agent"})
        assert _parse_text(result)["success"] is True

        press = get_handler("press_key")
        result = await press({"key": "enter"})
        assert _parse_text(result)["success"] is True

        # Verify all 3 input calls were dispatched
        calls = setup_context["input"].calls
        assert len(calls) == 3
        assert calls[0][0] == "click"
        assert calls[1][0] == "type_text"
        assert calls[2][0] == "press_key"

    @pytest.mark.asyncio
    async def test_status_reflects_usage(self, setup_context):
        """Backend stats update after actions."""
        click = get_handler("click")
        await click({"x": 10, "y": 20})
        await click({"x": 30, "y": 40})

        status = get_handler("get_agent_status")
        result = await status({})
        data = _parse_text(result)
        stats = data["backend_stats"]
        assert stats["mock"]["click"]["success"] == 2
        assert stats["mock"]["click"]["rate"] == "100%"
