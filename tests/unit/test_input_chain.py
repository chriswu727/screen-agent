"""Tests for input backend chain with fallback logic."""

import pytest

from screen_agent.engine.input_chain import InputChain
from screen_agent.errors import InputDeliveryError
from screen_agent.types import Point


class MockBackend:
    """A mock input backend for testing."""

    def __init__(self, name: str, *, fail: bool = False, raise_error: bool = False):
        self._name = name
        self._fail = fail
        self._raise_error = raise_error
        self.calls: list[tuple[str, dict]] = []

    @property
    def name(self) -> str:
        return self._name

    def available(self) -> bool:
        return True

    async def click(self, point: Point, button: str = "left", clicks: int = 1) -> bool:
        self.calls.append(("click", {"point": point, "button": button, "clicks": clicks}))
        if self._raise_error:
            raise RuntimeError(f"{self._name} exploded")
        return not self._fail

    async def type_text(self, text: str) -> bool:
        self.calls.append(("type_text", {"text": text}))
        if self._raise_error:
            raise RuntimeError(f"{self._name} exploded")
        return not self._fail

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> bool:
        self.calls.append(("press_key", {"key": key, "modifiers": modifiers}))
        if self._raise_error:
            raise RuntimeError(f"{self._name} exploded")
        return not self._fail

    async def scroll(self, amount: int, point: Point | None = None) -> bool:
        self.calls.append(("scroll", {"amount": amount, "point": point}))
        return not self._fail

    async def move(self, point: Point) -> bool:
        self.calls.append(("move", {"point": point}))
        return not self._fail

    async def drag(self, start: Point, end: Point, button: str = "left") -> bool:
        self.calls.append(("drag", {"start": start, "end": end, "button": button}))
        return not self._fail


class TestInputChain:
    @pytest.mark.asyncio
    async def test_first_backend_succeeds(self):
        b1 = MockBackend("fast")
        b2 = MockBackend("slow")
        chain = InputChain([b1, b2])

        result = await chain.click(Point(100, 200))

        assert result.success
        assert result.backend_used == "fast"
        assert len(b1.calls) == 1
        assert len(b2.calls) == 0  # never reached

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        b1 = MockBackend("ax", fail=True)
        b2 = MockBackend("cgevent")
        chain = InputChain([b1, b2])

        result = await chain.click(Point(100, 200))

        assert result.success
        assert result.backend_used == "cgevent"
        assert len(b1.calls) == 1  # tried first
        assert len(b2.calls) == 1  # fell through

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self):
        b1 = MockBackend("ax", raise_error=True)
        b2 = MockBackend("cgevent")
        chain = InputChain([b1, b2])

        result = await chain.click(Point(100, 200))

        assert result.success
        assert result.backend_used == "cgevent"

    @pytest.mark.asyncio
    async def test_all_fail_raises_error(self):
        b1 = MockBackend("ax", fail=True)
        b2 = MockBackend("cgevent", raise_error=True)
        chain = InputChain([b1, b2])

        with pytest.raises(InputDeliveryError) as exc_info:
            await chain.click(Point(100, 200))

        err = exc_info.value
        assert err.action == "click"
        assert len(err.attempts) == 2
        assert err.attempts[0] == ("ax", "returned False")
        assert "exploded" in err.attempts[1][1]

    @pytest.mark.asyncio
    async def test_stats_tracking(self):
        b1 = MockBackend("ax", fail=True)
        b2 = MockBackend("cgevent")
        chain = InputChain([b1, b2])

        await chain.click(Point(10, 20))
        await chain.click(Point(30, 40))

        summary = chain.stats_summary()
        assert summary["ax"]["click"]["failure"] == 2
        assert summary["cgevent"]["click"]["success"] == 2
        assert summary["cgevent"]["click"]["rate"] == "100%"

    @pytest.mark.asyncio
    async def test_type_text(self):
        b1 = MockBackend("backend")
        chain = InputChain([b1])

        result = await chain.type_text("hello")
        assert result.success
        assert b1.calls[0] == ("type_text", {"text": "hello"})

    @pytest.mark.asyncio
    async def test_press_key_with_modifiers(self):
        b1 = MockBackend("backend")
        chain = InputChain([b1])

        result = await chain.press_key("c", modifiers=["command"])
        assert result.success
        assert b1.calls[0][1]["modifiers"] == ["command"]

    @pytest.mark.asyncio
    async def test_drag(self):
        b1 = MockBackend("backend")
        chain = InputChain([b1])

        result = await chain.drag(Point(0, 0), Point(100, 100))
        assert result.success

    @pytest.mark.asyncio
    async def test_backend_names(self):
        chain = InputChain([
            MockBackend("ax"),
            MockBackend("cgevent"),
            MockBackend("pyautogui"),
        ])
        assert chain.backend_names == ["ax", "cgevent", "pyautogui"]

    @pytest.mark.asyncio
    async def test_empty_chain_raises(self):
        chain = InputChain([])
        with pytest.raises(InputDeliveryError):
            await chain.click(Point(0, 0))

    @pytest.mark.asyncio
    async def test_result_details(self):
        b1 = MockBackend("cg")
        chain = InputChain([b1])

        result = await chain.click(Point(42, 99), button="right", clicks=2)
        assert result.details["point"] == {"x": 42, "y": 99}
        assert result.details["button"] == "right"
        assert result.details["clicks"] == 2

    @pytest.mark.asyncio
    async def test_three_level_fallback(self):
        """Simulates the real AX -> CGEvent -> pyautogui chain."""
        ax = MockBackend("ax", raise_error=True)
        cg = MockBackend("cgevent", fail=True)
        pag = MockBackend("pyautogui")
        chain = InputChain([ax, cg, pag])

        result = await chain.click(Point(500, 300))
        assert result.success
        assert result.backend_used == "pyautogui"
        assert len(ax.calls) == 1
        assert len(cg.calls) == 1
        assert len(pag.calls) == 1
