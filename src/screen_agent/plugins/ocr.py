"""OCR plugin using PaddleOCR.

Provides text extraction and text-based element finding.
Install with: pip install screen-agent[ocr]
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

from mcp.types import Tool

from screen_agent.capture import capture_screen

OCR_TOOLS: list[Tool] = [
    Tool(
        name="ocr",
        description=(
            "Extract all visible text from the screen with positions. "
            "Returns a list of detected text blocks with bounding boxes and confidence."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "region": {
                    "type": "object",
                    "description": "Optional region to scan",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                        "width": {"type": "integer"},
                        "height": {"type": "integer"},
                    },
                    "required": ["x", "y", "width", "height"],
                },
                "lang": {
                    "type": "string",
                    "default": "en",
                    "description": "Language code: en, ch, japan, korean, etc.",
                },
            },
        },
    ),
    Tool(
        name="find_text",
        description=(
            "Find specific text on screen and return its location. "
            "Useful for locating buttons, labels, or any text element."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to search for (case-insensitive, partial match)",
                },
            },
            "required": ["query"],
        },
    ),
]


@lru_cache(maxsize=1)
def _get_ocr(lang: str = "en"):
    from paddleocr import PaddleOCR

    return PaddleOCR(use_angle_cls=True, lang=lang, show_log=False)


def _run_ocr_sync(image_bytes: bytes, lang: str) -> list[dict]:
    import base64
    import tempfile
    from pathlib import Path

    ocr = _get_ocr(lang)

    # PaddleOCR needs a file path or numpy array
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(base64.b64decode(image_bytes))
        tmp_path = f.name

    try:
        results = ocr.ocr(tmp_path, cls=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    if not results or not results[0]:
        return []

    blocks = []
    for line in results[0]:
        bbox, (text, confidence) = line
        # bbox is [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        blocks.append({
            "text": text,
            "confidence": round(confidence, 3),
            "bbox": {
                "x": int(min(xs)),
                "y": int(min(ys)),
                "width": int(max(xs) - min(xs)),
                "height": int(max(ys) - min(ys)),
            },
            "center": {
                "x": int(sum(xs) / 4),
                "y": int(sum(ys) / 4),
            },
        })
    return blocks


# Singleton for lazy init
ocr_instance = None


async def handle_ocr_tool(name: str, args: dict) -> list[dict] | dict:
    """Handle OCR and find_text tool calls."""
    screenshot = await capture_screen(region=args.get("region"))
    lang = args.get("lang", "en")
    blocks = await asyncio.to_thread(_run_ocr_sync, screenshot["image_base64"], lang)

    if name == "find_text":
        query = args["query"].lower()
        matches = [b for b in blocks if query in b["text"].lower()]
        if not matches:
            return {"found": False, "query": args["query"], "message": "Text not found on screen"}
        return {"found": True, "query": args["query"], "matches": matches}

    return blocks
