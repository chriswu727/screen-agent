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
    Tool(
        name="click_text",
        description=(
            "Find text on screen using OCR and click its center. "
            "Combines find_text + click into one action. "
            "Returns the OCR match that was clicked, or an error if text not found."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Text to find and click (case-insensitive, partial match)",
                },
                "button": {
                    "type": "string",
                    "enum": ["left", "right", "middle"],
                    "default": "left",
                },
                "index": {
                    "type": "integer",
                    "default": 0,
                    "description": "Which match to click if multiple found (0=first)",
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
    """Handle OCR, find_text, and click_text tool calls."""
    # Use resize=False so OCR coordinates match actual screen pixels
    screenshot = await capture_screen(region=args.get("region"), resize=False)
    lang = args.get("lang", "en")
    blocks = await asyncio.to_thread(_run_ocr_sync, screenshot["image_base64"], lang)

    if name == "find_text":
        query = args["query"].lower()
        matches = [b for b in blocks if query in b["text"].lower()]
        if not matches:
            return {"found": False, "query": args["query"], "message": "Text not found on screen"}
        return {"found": True, "query": args["query"], "matches": matches}

    if name == "click_text":
        query = args["query"].lower()
        matches = [b for b in blocks if query in b["text"].lower()]
        if not matches:
            return {"clicked": False, "query": args["query"], "message": "Text not found on screen"}

        index = args.get("index", 0)
        if index >= len(matches):
            return {"clicked": False, "query": args["query"],
                    "message": f"Only {len(matches)} matches, index {index} out of range"}

        target = matches[index]
        x, y = target["center"]["x"], target["center"]["y"]

        # Guardian clearance (this is an input action)
        from screen_agent.guardian import get_guardian
        guardian = get_guardian()
        clearance = await guardian.wait_for_clearance(x=x, y=y)
        if not clearance.allowed:
            return {"clicked": False, "error": "blocked_by_guardian", "reason": clearance.reason}

        # Perform the click
        from screen_agent.input import mouse_click
        button = args.get("button", "left")
        await mouse_click(x, y, button=button)

        return {"clicked": True, "query": args["query"], "match": target, "x": x, "y": y, "button": button}

    return blocks
