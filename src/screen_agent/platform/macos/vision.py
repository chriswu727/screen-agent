"""Apple Vision Framework OCR backend.

Zero extra dependencies on macOS — uses the built-in Vision framework
via pyobjc. Much lighter than PaddleOCR (~1MB vs 2GB+) and more
accurate for screen text.
"""

from __future__ import annotations

import asyncio
import logging

from screen_agent.types import Point, Region, TextBlock

logger = logging.getLogger(__name__)


class VisionOCRBackend:
    """OCR using Apple's Vision framework."""

    def __init__(self):
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import Quartz  # noqa: F401
            import Vision  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
        return self._available

    async def recognize(
        self, image_data: bytes, lang: str = "en"
    ) -> list[TextBlock]:
        """Recognize text in a PNG/JPEG image.

        Args:
            image_data: Raw image bytes (PNG or JPEG).
            lang: Language hint (e.g., 'en', 'zh-Hans', 'ja').

        Returns:
            List of TextBlock with text, confidence, bounding box, and center.
        """
        if not self.available():
            return []
        return await asyncio.to_thread(self._recognize_sync, image_data, lang)

    def _recognize_sync(self, image_data: bytes, lang: str) -> list[TextBlock]:
        import Quartz
        import Vision
        from Foundation import NSData

        # Create CGImage from data
        ns_data = NSData.dataWithBytes_length_(image_data, len(image_data))
        source = Quartz.CGImageSourceCreateWithData(ns_data, None)
        if source is None:
            logger.error("Failed to create image source")
            return []

        cg_image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None)
        if cg_image is None:
            logger.error("Failed to create CGImage")
            return []

        img_width = Quartz.CGImageGetWidth(cg_image)
        img_height = Quartz.CGImageGetHeight(cg_image)

        # Create recognition request
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(
            Vision.VNRequestTextRecognitionLevelAccurate
        )
        request.setUsesLanguageCorrection_(True)

        # Set recognition languages
        lang_map = {
            "en": ["en-US"],
            "zh-Hans": ["zh-Hans"],
            "zh": ["zh-Hans", "zh-Hant"],
            "ja": ["ja"],
            "ko": ["ko"],
            "de": ["de"],
            "fr": ["fr"],
            "es": ["es"],
        }
        languages = lang_map.get(lang, ["en-US"])
        request.setRecognitionLanguages_(languages)

        # Perform recognition
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(
            cg_image, {}
        )
        success, error = handler.performRequests_error_([request], None)
        if not success:
            logger.error("Vision OCR failed: %s", error)
            return []

        # Process results
        results = []
        observations = request.results() or []
        for obs in observations:
            candidates = obs.topCandidates_(1)
            if not candidates:
                continue

            text = candidates[0].string()
            confidence = obs.confidence()

            # Vision returns normalized coordinates (0-1), origin at bottom-left
            bbox = obs.boundingBox()
            x = int(bbox.origin.x * img_width)
            y = int((1.0 - bbox.origin.y - bbox.size.height) * img_height)
            w = int(bbox.size.width * img_width)
            h = int(bbox.size.height * img_height)

            region = Region(x=x, y=y, width=w, height=h)
            center = Point(x + w // 2, y + h // 2)

            results.append(TextBlock(
                text=text,
                confidence=round(confidence, 3),
                bbox=region,
                center=center,
            ))

        logger.debug("Vision OCR: found %d text blocks", len(results))
        return results
