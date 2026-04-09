"""Autonomous test execution engine.

The LLM plans once. The server executes autonomously. No LLM round-trips.

Three strategies to find elements (tried in order):
  1. eval_js — CSS selector via CDP (instant, 100% reliable for web)
  2. OCR — find visible text on screen (works for any app)
  3. fail — return screenshot for LLM self-healing

Screenshot reuse: step N's "after" becomes step N+1's "before".
This halves the number of capture + OCR calls.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
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
    """Execute a test plan autonomously. No LLM in the loop."""
    result = TestResult(name=name)
    t_start = time.time()

    # Screenshot reuse: previous step's "after" = current step's "before"
    cached_img: bytes | None = None

    for i, step in enumerate(steps):
        t_step = time.time()
        sr = StepResult(index=i + 1, description=_describe_step(step), success=False, duration_ms=0)

        try:
            if "wait" in step:
                await asyncio.sleep(float(step["wait"]))
                cached_img = None  # invalidate after wait

            # Capture (reuse previous step's "after" screenshot)
            if cached_img is None:
                img_data, w, h = await capture_fn()
            else:
                img_data = cached_img
            sr.before_screenshot_b64 = base64.b64encode(img_data).decode("ascii")
            cached_img = None  # will be set to after-screenshot

            # ── FIND + ACT ──
            if "find" in step:
                target = step["find"]
                selector = step.get("selector")  # optional CSS selector
                action = step.get("action", "click")
                text = step.get("text", "")

                # Strategy 1: eval_js with CSS selector (instant, web-only)
                found_via_js = False
                if eval_js_fn and selector:
                    found_via_js = await _find_and_act_js(
                        eval_js_fn, selector, action, text, sr
                    )

                # Strategy 2: eval_js with text content search
                if not found_via_js and eval_js_fn:
                    found_via_js = await _find_and_act_js_by_text(
                        eval_js_fn, target, action, text, sr
                    )

                # Strategy 3: OCR (works for any app)
                if not found_via_js:
                    found_via_ocr = await _find_and_act_ocr(
                        target, action, text, img_data, ocr_fn, click_fn, type_fn, sr
                    )
                    if not found_via_ocr:
                        sr.duration_ms = (time.time() - t_step) * 1000
                        result.steps.append(sr)
                        break  # fail-fast

            # ── EVAL_JS (standalone) ──
            if "eval_js" in step and eval_js_fn:
                js_result = await eval_js_fn(step["eval_js"])
                expected = step.get("expected")
                if expected is not None and str(js_result) != str(expected):
                    sr.error = f"eval_js: expected '{expected}', got '{js_result}'"
                    sr.duration_ms = (time.time() - t_step) * 1000
                    result.steps.append(sr)
                    break

            # ── KEY PRESS ──
            if "key" in step:
                await press_key_fn(step["key"])

            # ── VERIFY ──
            if "verify" in step:
                await asyncio.sleep(float(step.get("verify_wait", 0.3)))
                img_after, _, _ = await capture_fn()
                sr.after_screenshot_b64 = base64.b64encode(img_after).decode("ascii")
                cached_img = img_after  # reuse for next step

                # Try JS verification first (faster, more reliable)
                verified = False
                if eval_js_fn:
                    verified = await _verify_js(eval_js_fn, step["verify"])

                # Fallback to OCR verification
                if not verified:
                    verified = await _verify_ocr(ocr_fn, img_after, step["verify"])

                if not verified:
                    sr.error = f"Verification failed: '{step['verify']}' not found"
                    sr.duration_ms = (time.time() - t_step) * 1000
                    result.steps.append(sr)
                    break
            else:
                # Capture after for evidence + reuse
                await asyncio.sleep(0.05)
                img_after, _, _ = await capture_fn()
                sr.after_screenshot_b64 = base64.b64encode(img_after).decode("ascii")
                cached_img = img_after

            sr.success = True

        except Exception as e:
            sr.error = str(e)
            logger.error("Step %d failed: %s", i + 1, e)

        sr.duration_ms = (time.time() - t_step) * 1000
        result.steps.append(sr)

        if not sr.success:
            break

    result.total_ms = (time.time() - t_start) * 1000
    return result


# ── Element Finding Strategies ──────────────────────────────────

async def _find_and_act_js(eval_js_fn, selector: str, action: str, text: str, sr: StepResult) -> bool:
    """Strategy 1: CSS selector via eval_js. Instant, 100% reliable for web."""
    try:
        exists = await eval_js_fn(f'!!document.querySelector("{_escape_js(selector)}")')
        if not exists:
            return False

        if action in ("click", "click_and_type"):
            await eval_js_fn(f'document.querySelector("{_escape_js(selector)}").click()')
            sr.backend = "eval_js"

        if action in ("type", "click_and_type") and text:
            await eval_js_fn(f'''(() => {{
                const el = document.querySelector("{_escape_js(selector)}");
                el.focus();
                el.value = "{_escape_js(text)}";
                el.dispatchEvent(new Event("input", {{bubbles: true}}));
            }})()''')
            sr.backend = "eval_js"

        sr.element_found = selector
        return True
    except Exception:
        return False


async def _find_and_act_js_by_text(eval_js_fn, target: str, action: str, text: str, sr: StepResult) -> bool:
    """Strategy 2: Find element by visible text via JS. Faster than OCR."""
    try:
        # Find element by text content, placeholder, value, or aria-label
        js = f'''(() => {{
            const q = "{_escape_js(target)}".toLowerCase();
            // Strategy A: text content via XPath
            const xpath = "//*[contains(text(), '{_escape_js(target)}')]";
            let el = document.evaluate(xpath, document, null,
                XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            // Strategy B: placeholder, value, aria-label
            if (!el) {{
                el = Array.from(document.querySelectorAll('input,textarea,select,[placeholder]')).find(e =>
                    (e.placeholder && e.placeholder.toLowerCase().includes(q)) ||
                    (e.getAttribute('aria-label') || '').toLowerCase().includes(q) ||
                    (e.value && e.value.toLowerCase().includes(q))
                );
            }}
            // Strategy C: button/link text
            if (!el) {{
                el = Array.from(document.querySelectorAll('button,a,[role="button"]')).find(e =>
                    e.textContent.toLowerCase().includes(q)
                );
            }}
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{tag: el.tagName, x: Math.round(r.x + r.width/2), y: Math.round(r.y + r.height/2)}};
        }})()'''
        result = await eval_js_fn(js)
        if not result or result == "null":
            return False

        if isinstance(result, dict):
            sr.element_found = f"{result.get('tag', '?')}:'{target}'"
            x, y = result.get("x", 0), result.get("y", 0)
            sr.element_at = (x, y)

            if action in ("click", "click_and_type"):
                click_js = f'''(() => {{
                    const q = "{_escape_js(target)}".toLowerCase();
                    // Find by text, placeholder, value, aria-label
                    let el = null;
                    const xpath = "//*[contains(text(), '{_escape_js(target)}')]";
                    el = document.evaluate(xpath, document, null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                    if (!el) el = Array.from(document.querySelectorAll('input,textarea,select,[placeholder]')).find(e =>
                        (e.placeholder && e.placeholder.toLowerCase().includes(q)) ||
                        (e.getAttribute('aria-label') || '').toLowerCase().includes(q));
                    if (!el) el = Array.from(document.querySelectorAll('button,a,[role="button"]')).find(e =>
                        e.textContent.toLowerCase().includes(q));
                    if (!el) return false;
                    const input = el.querySelector('input,textarea,select') ||
                                  el.closest('button,a,[role="button"]') || el;
                    input.click();
                    if (input.focus) input.focus();
                    return true;
                }})()'''
                await eval_js_fn(click_js)
                sr.backend = "eval_js_text"

            if action in ("type", "click_and_type") and text:
                type_js = f'''(() => {{
                    const active = document.activeElement;
                    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) {{
                        active.value = "{_escape_js(text)}";
                        active.dispatchEvent(new Event("input", {{bubbles: true}}));
                        return true;
                    }}
                    return false;
                }})()'''
                await eval_js_fn(type_js)
                sr.backend = "eval_js_text"

            return True
    except Exception:
        pass
    return False


async def _find_and_act_ocr(
    target: str, action: str, text: str,
    img_data: bytes, ocr_fn, click_fn, type_fn, sr: StepResult,
) -> bool:
    """Strategy 3: OCR find + coordinate click. Works for any app."""
    lang = _detect_lang(target)
    blocks = await ocr_fn(img_data, lang)
    query = target.lower()
    matches = [b for b in blocks if query in b.text.lower()]

    if not matches:
        sr.error = f"Element not found: '{target}' (tried eval_js + OCR)"
        return False

    element = matches[0]
    sr.element_found = element.text
    sr.element_at = (element.center.x, element.center.y)

    if action in ("click", "click_and_type"):
        ok = await click_fn(element.center.x, element.center.y)
        sr.backend = "ocr"
        if not ok:
            sr.error = f"Click failed at ({element.center.x}, {element.center.y})"
            return False

    if action in ("type", "click_and_type") and text:
        await asyncio.sleep(0.1)
        await type_fn(text)
        sr.backend = "ocr"

    return True


# ── Verification Strategies ─────────────────────────────────────

async def _verify_js(eval_js_fn, expected_text: str) -> bool:
    """Verify via JS: check if text exists in page body."""
    try:
        result = await eval_js_fn(
            f'document.body.innerText.toLowerCase().includes("{_escape_js(expected_text.lower())}")'
        )
        return result is True
    except Exception:
        return False


async def _verify_ocr(ocr_fn, img_data: bytes, expected_text: str) -> bool:
    """Verify via OCR: check if text is visible on screen."""
    lang = _detect_lang(expected_text)
    blocks = await ocr_fn(img_data, lang)
    all_text = " ".join(b.text for b in blocks).lower()
    return expected_text.lower() in all_text


# ── Utilities ───────────────────────────────────────────────────

def _describe_step(step: dict) -> str:
    parts = []
    if "find" in step:
        action = step.get("action", "click")
        if action == "click":
            parts.append(f"Click '{step['find']}'")
        elif action == "type":
            parts.append(f"Type into '{step['find']}'")
        elif action == "click_and_type":
            parts.append(f"Click '{step['find']}' and type '{step.get('text', '')}'")
    if "verify" in step:
        parts.append(f"Verify '{step['verify']}'")
    if "eval_js" in step:
        parts.append(f"JS: {step['eval_js'][:40]}")
    if "key" in step:
        parts.append(f"Press {step['key']}")
    if "wait" in step:
        parts.append(f"Wait {step['wait']}s")
    return " | ".join(parts) if parts else str(step)


def _detect_lang(text: str) -> str:
    if re.search(r'[\u3040-\u30ff\u31f0-\u31ff\uff65-\uff9f]', text):
        return "ja"
    if re.search(r'[\u3400-\u9fff\uf900-\ufaff]', text):
        return "zh"
    if re.search(r'[\uac00-\ud7af]', text):
        return "ko"
    return "en"


def _escape_js(s: str) -> str:
    """Escape string for JavaScript string literal."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'").replace("\n", "\\n")
