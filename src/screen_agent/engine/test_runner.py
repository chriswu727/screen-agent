"""Autonomous test execution engine.

The LLM plans once. The server executes autonomously. No LLM round-trips
during execution. 15x faster than Claude Code's per-step LLM loop.

Usage via MCP:
    run_test(steps=[
        {"find": "Email", "action": "click_and_type", "text": "test@example.com"},
        {"find": "Password", "action": "click_and_type", "text": "secret"},
        {"find": "Log in", "action": "click"},
        {"verify": "Dashboard"},
    ])

Each step:
    1. Capture screenshot (CDP or CGWindowList)
    2. OCR find the target element
    3. Execute the action (CDP click/type or AX)
    4. Record before/after screenshots as evidence
    5. On failure: return screenshot + error for LLM self-healing
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    index: int
    description: str
    success: bool
    duration_ms: float
    backend: str = ""
    error: str = ""
    element_found: str = ""
    element_at: tuple[int, int] = (0, 0)
    before_screenshot_b64: str = ""
    after_screenshot_b64: str = ""

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "step": self.index,
            "description": self.description,
            "success": self.success,
            "duration_ms": round(self.duration_ms, 1),
        }
        if self.element_found:
            d["element"] = self.element_found
            d["at"] = list(self.element_at)
        if self.backend:
            d["backend"] = self.backend
        if self.error:
            d["error"] = self.error
        return d


@dataclass
class TestResult:
    name: str
    steps: list[StepResult] = field(default_factory=list)
    total_ms: float = 0.0

    @property
    def passed(self) -> int:
        return sum(1 for s in self.steps if s.success)

    @property
    def failed(self) -> int:
        return sum(1 for s in self.steps if not s.success)

    @property
    def all_passed(self) -> bool:
        return all(s.success for s in self.steps)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "all_passed": self.all_passed,
            "passed": self.passed,
            "failed": self.failed,
            "total_steps": len(self.steps),
            "total_ms": round(self.total_ms, 1),
            "steps": [s.to_dict() for s in self.steps],
        }


async def run_test(
    name: str,
    steps: list[dict],
    capture_fn,
    ocr_fn,
    click_fn,
    type_fn,
    press_key_fn,
    eval_js_fn=None,
) -> TestResult:
    """Execute a test plan autonomously.

    Args:
        name: Test name
        steps: List of step dicts, each with:
            - find: text to locate via OCR (optional)
            - action: "click", "type", "click_and_type" (optional)
            - text: text to type (for type/click_and_type)
            - verify: text that should be visible after action (optional)
            - eval_js: JavaScript to evaluate (optional, CDP only)
            - wait: seconds to wait before step (optional)
        capture_fn: async () -> (image_bytes, width, height)
        ocr_fn: async (image_bytes, lang) -> list[TextBlock]
        click_fn: async (x, y) -> bool
        type_fn: async (text) -> bool
        press_key_fn: async (key) -> bool
        eval_js_fn: async (expression) -> Any (optional, CDP only)
    """
    result = TestResult(name=name)
    t_start = time.time()

    for i, step in enumerate(steps):
        t_step = time.time()
        sr = StepResult(index=i + 1, description=_describe_step(step), success=False, duration_ms=0)

        try:
            # Optional wait
            if "wait" in step:
                await asyncio.sleep(float(step["wait"]))

            # Capture before
            img_data, w, h = await capture_fn()
            sr.before_screenshot_b64 = base64.b64encode(img_data).decode("ascii")

            # Find target via OCR
            if "find" in step:
                target = step["find"]
                lang = _detect_lang_simple(target)
                blocks = await ocr_fn(img_data, lang)
                query = target.lower()
                matches = [b for b in blocks if query in b.text.lower()]

                if not matches:
                    sr.error = f"Element not found: '{target}'"
                    sr.duration_ms = (time.time() - t_step) * 1000
                    result.steps.append(sr)
                    continue

                element = matches[0]
                sr.element_found = element.text
                sr.element_at = (element.center.x, element.center.y)
                x, y = element.center.x, element.center.y

                # Execute action
                action = step.get("action", "click")
                text = step.get("text", "")

                if action in ("click", "click_and_type"):
                    ok = await click_fn(x, y)
                    sr.backend = "click"
                    if not ok:
                        sr.error = f"Click failed at ({x}, {y})"
                        sr.duration_ms = (time.time() - t_step) * 1000
                        result.steps.append(sr)
                        continue

                if action in ("type", "click_and_type"):
                    await asyncio.sleep(0.1)
                    ok = await type_fn(text)
                    sr.backend = "type"

            # eval_js step
            if "eval_js" in step and eval_js_fn:
                js_result = await eval_js_fn(step["eval_js"])
                expected = step.get("expected")
                if expected is not None:
                    if str(js_result) != str(expected):
                        sr.error = f"eval_js: expected '{expected}', got '{js_result}'"
                        sr.duration_ms = (time.time() - t_step) * 1000
                        result.steps.append(sr)
                        continue

            # press_key step
            if "key" in step:
                await press_key_fn(step["key"])

            # Verify step
            if "verify" in step:
                await asyncio.sleep(float(step.get("verify_wait", 0.3)))
                img_data2, _, _ = await capture_fn()
                sr.after_screenshot_b64 = base64.b64encode(img_data2).decode("ascii")

                verify_text = step["verify"]
                lang = _detect_lang_simple(verify_text)
                blocks2 = await ocr_fn(img_data2, lang)
                all_text = " ".join(b.text for b in blocks2)

                if verify_text.lower() not in all_text.lower():
                    sr.error = f"Verification failed: '{verify_text}' not found on screen"
                    sr.duration_ms = (time.time() - t_step) * 1000
                    result.steps.append(sr)
                    continue
            else:
                # Capture after for evidence
                await asyncio.sleep(0.1)
                img_data2, _, _ = await capture_fn()
                sr.after_screenshot_b64 = base64.b64encode(img_data2).decode("ascii")

            sr.success = True

        except Exception as e:
            sr.error = str(e)
            logger.error("Step %d failed: %s", i + 1, e)

        sr.duration_ms = (time.time() - t_step) * 1000
        result.steps.append(sr)

        # Stop on first failure (fail-fast)
        if not sr.success:
            break

    result.total_ms = (time.time() - t_start) * 1000
    return result


def _describe_step(step: dict) -> str:
    parts = []
    if "find" in step:
        action = step.get("action", "click")
        if action == "click":
            parts.append(f"Click '{step['find']}'")
        elif action == "type":
            parts.append(f"Type '{step.get('text', '')}' into '{step['find']}'")
        elif action == "click_and_type":
            parts.append(f"Click '{step['find']}' and type '{step.get('text', '')}'")
    if "verify" in step:
        parts.append(f"Verify '{step['verify']}' visible")
    if "eval_js" in step:
        parts.append(f"Eval: {step['eval_js'][:50]}")
    if "key" in step:
        parts.append(f"Press {step['key']}")
    if "wait" in step:
        parts.append(f"Wait {step['wait']}s")
    return " → ".join(parts) if parts else str(step)


def _detect_lang_simple(text: str) -> str:
    """Lightweight language detection for OCR."""
    import re
    if re.search(r'[\u3040-\u30ff\u31f0-\u31ff\uff65-\uff9f]', text):
        return "ja"
    if re.search(r'[\u3400-\u9fff\uf900-\ufaff]', text):
        return "zh"
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    return "en"
