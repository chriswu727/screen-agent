"""
Screen verification — the thing that makes this different from Playwright.

Playwright asserts on DOM: querySelector("#btn").textContent === "Submit"
We assert on what the user SEES: "the word Submit is visible on screen"

Three verification methods:
1. OCR — find expected text on screen
2. Screenshot diff — compare region to a golden image
3. Visual state — check that a region changed (or didn't change) after an action
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from screen_agent.testing.session import Screenshot, Verification
from screen_agent.platform.protocols import CaptureBackend, OCRBackend
from screen_agent.types import Region


class ScreenVerifier:
    """
    Verifies visual state of the screen.
    Uses the existing platform backends — no new dependencies.
    """

    def __init__(self, capture: CaptureBackend, ocr: OCRBackend | None = None):
        self._capture = capture
        self._ocr = ocr

    async def capture_screenshot(self, region: Region | None = None) -> Screenshot:
        """Take a screenshot, return as Screenshot dataclass."""
        result = await self._capture.capture(region=region)
        return Screenshot(
            image_base64=result.image_base64,
            mime_type=result.mime_type,
            width=result.width,
            height=result.height,
        )

    async def verify_text_visible(
        self,
        expected_text: str,
        screenshot: Screenshot | None = None,
        case_sensitive: bool = False,
    ) -> Verification:
        """
        Verify that expected text is visible on screen.
        Uses OCR on the current screen (or provided screenshot).
        """
        if not self._ocr:
            return Verification(
                passed=False,
                method="ocr",
                expected=expected_text,
                actual="",
                details={"error": "OCR backend not available"},
            )

        if screenshot is None:
            screenshot = await self.capture_screenshot()

        image_data = base64.b64decode(screenshot.image_base64)
        text_blocks = await self._ocr.recognize(image_data)

        all_text = " ".join(block.text for block in text_blocks)

        if case_sensitive:
            found = expected_text in all_text
        else:
            found = expected_text.lower() in all_text.lower()

        # Find the best matching block for details
        best_match = ""
        best_confidence = 0.0
        for block in text_blocks:
            check_block = block.text if case_sensitive else block.text.lower()
            check_expected = expected_text if case_sensitive else expected_text.lower()
            if check_expected in check_block and block.confidence > best_confidence:
                best_match = block.text
                best_confidence = block.confidence

        return Verification(
            passed=found,
            method="ocr",
            expected=expected_text,
            actual=best_match if found else f"Text not found. Screen text: {all_text[:200]}...",
            confidence=best_confidence if found else 0.0,
            details={
                "total_text_blocks": len(text_blocks),
                "full_text_length": len(all_text),
            },
        )

    async def verify_text_not_visible(
        self,
        text: str,
        screenshot: Screenshot | None = None,
    ) -> Verification:
        """Verify that text is NOT on screen (e.g., error message disappeared)."""
        result = await self.verify_text_visible(text, screenshot)
        return Verification(
            passed=not result.passed,
            method="ocr_absence",
            expected=f"'{text}' should NOT be visible",
            actual="Not found (good)" if not result.passed else f"Found: {result.actual}",
            confidence=result.confidence,
            details=result.details,
        )

    async def verify_screen_changed(
        self,
        before: Screenshot,
        after: Screenshot,
        threshold: float = 0.05,
    ) -> Verification:
        """
        Verify that the screen changed between two screenshots.
        Uses pixel-level comparison. Threshold is fraction of pixels that must differ.
        """
        try:
            from PIL import Image
            import io

            img_before = Image.open(io.BytesIO(base64.b64decode(before.image_base64)))
            img_after = Image.open(io.BytesIO(base64.b64decode(after.image_base64)))

            # Resize to same dimensions if needed
            if img_before.size != img_after.size:
                img_after = img_after.resize(img_before.size)

            # Compare pixels
            pixels_before = list(img_before.getdata())
            pixels_after = list(img_after.getdata())
            total = len(pixels_before)

            if total == 0:
                return Verification(
                    passed=False, method="screenshot_diff",
                    expected="Screen should change", actual="Empty screenshots",
                )

            diff_count = sum(1 for a, b in zip(pixels_before, pixels_after) if a != b)
            diff_ratio = diff_count / total

            return Verification(
                passed=diff_ratio >= threshold,
                method="screenshot_diff",
                expected=f"Screen change >= {threshold:.1%}",
                actual=f"Changed {diff_ratio:.1%} of pixels ({diff_count}/{total})",
                confidence=min(diff_ratio / threshold, 1.0) if threshold > 0 else 1.0,
                details={"diff_ratio": round(diff_ratio, 4), "diff_pixels": diff_count, "total_pixels": total},
            )
        except ImportError:
            return Verification(
                passed=False, method="screenshot_diff",
                expected="Screen should change", actual="Pillow not available",
            )

    async def verify_screen_unchanged(
        self,
        before: Screenshot,
        after: Screenshot,
        threshold: float = 0.02,
    ) -> Verification:
        """Verify screen did NOT change (e.g., invalid input should not navigate away)."""
        result = await self.verify_screen_changed(before, after, threshold)
        return Verification(
            passed=not result.passed,
            method="screenshot_no_diff",
            expected=f"Screen should NOT change (threshold {threshold:.1%})",
            actual=result.actual,
            confidence=result.confidence,
            details=result.details,
        )
