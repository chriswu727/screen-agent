# Screen Agent — Development Path

All changes, decisions, and lessons learned. Newest first.

---

## 2026-04-09: Cross-Space Background Testing (IN PROGRESS)

### Problem
`window_scope` feature can't work when target app is on a different macOS Space:
- `CGWindowListCreateImage` returns **blank** for windows on other Spaces (macOS doesn't render them)
- `CGEventPost` only delivers to current Space

### Failed Approaches
1. `kCGWindowImageDefault` flag → blank image
2. `kCGWindowImageBoundsIgnoreFraming` → blank on other Space
3. AppleScript reload to force render → still blank
4. `ensure_on_current_space` (activate + deactivate) → steals user's screen

### Root Cause
macOS window server does NOT render windows on inactive Spaces. This is an OS-level limitation, not a bug.

### Solution: Chrome DevTools Protocol (CDP)
- Chrome's internal renderer works regardless of Space
- `Page.captureScreenshot` → real screenshot from Chrome's own rendering pipeline
- `Input.dispatchMouseEvent` → click events sent directly to Chrome's input system
- `Runtime.evaluate` → execute JS for assertions
- Requires Chrome started with `--remote-debugging-port=9222`
- Status: **implementing**

### What DOES Work (same Space, window behind others)
- Verified 2/3 E2E tests passing: text input ✓, todo ✓, counter ✗ (OCR can't find "+" on green circle)
- `CGWindowListCreateImage` captures occluded windows on same Space perfectly
- `CGEventPost` delivers clicks to background windows on same Space

---

## 2026-04-09: Cross-Platform Window Capture (PR #5, merged)

### Changes
- Added `WindowCaptureBackend` Protocol to `protocols.py`
- Refactored macOS `window_capture.py` from standalone functions to class
- Added `platform/windows/window_capture.py` — Win32 `PrintWindow`/`BitBlt` via ctypes
- Added `platform/linux/window_capture.py` — `xdotool`/`wmctrl` + ImageMagick
- Added `get_window_capture_backend()` factory with platform auto-detection
- Removed `INTERVIEW_PREP.md` from git tracking

### Lesson
Squash merge + branching from local branch (not origin/main) causes conflicts. Always `git fetch origin main && git checkout -b new-branch origin/main` after a PR merge.

---

## 2026-04-09: Window-Scoped Capture + Interact Tool (PR #4, merged)

### Changes
- `window_scope(app, title)` / `window_release()` — lock operations to a specific window
- `interact(target, action, text)` — single MCP call replaces 6-step capture→find→click→type pipeline
- `CGWindowListCreateImage` for window-targeted capture
- `WindowSession` for coordinate translation (window-relative → screen-absolute)

### Design Decisions
- Capture uses `kCGWindowImageBoundsIgnoreFraming` — captures content area only
- Window bounds from `kCGWindowBounds` match image dimensions (0px offset verified)
- `interact` auto-detects CJK languages via `_detect_lang`

### Key Discovery
CGEvent clicks CAN reach background windows on the same Space. This is the viable path for "no screen disruption" testing.

---

## 2026-04-08-09: OCR + Capture Performance + Coordinate Fix (PR #3, merged)

### Changes
- `_detect_lang()` — auto-detect zh/ja/ko/en from query text for `find_text`/`click_text`
- Default capture format PNG → JPEG (5-10x faster encoding)
- Removed `optimize=True` from PNG/JPEG encoding
- Fixed `_verify_screenshot` crash (accessed non-existent `post_action_delay`)
- Fixed coordinate drift: resize only Retina images, not 1x screens

### Key Discovery: Coordinate Drift Bug
`img.thumbnail(max_dimension)` resizes the screenshot but the code returned the resized dimensions as "logical coordinates". LLM reads pixel positions from the resized image, but actual screen coordinates use the original dimensions. 25px offset measured on 1470px screen with max_dimension=1400.

Fix: Only resize Retina physical→logical. For 1x screens, rely on JPEG compression for size reduction.

### Code Review Fixes (same PR)
- `_detect_lang` returns "zh" not "zh-Hans" (covers both Simplified+Traditional)
- Extended CJK ranges: added Extension A, Compatibility Ideographs, halfwidth Katakana
- Check kana before CJK ideographs (Japanese kanji not misdetected as Chinese)
- Updated `test_config.py` assertions for new defaults

---

## 2026-04-08: E2E Testing Session (manual)

### What Worked
| Feature | Status |
|---------|--------|
| `focus_window` | ✓ |
| `capture_screen` | ✓ |
| `find_text` (English) | ✓ |
| `click` (coordinate) | ✓ (with precise coords) |
| `type_text` | ✓ |
| `scroll` | ✓ |
| Counter +3 | ✓ |
| Text input "Hello Screen Agent!" | ✓ |

### What Failed
| Feature | Issue |
|---------|-------|
| `click_text` (Chinese) | OCR defaulted to English |
| `find_text` (Chinese) | Same — no lang param |
| Todo input focus | Coordinate inaccuracy from visual estimation |
| Chrome unresponsive | CGEvent clicks stopped after certain operations |

### Lessons
1. Never estimate coordinates from full-screen screenshots — use small region captures
2. OCR needs correct language parameter for CJK text
3. White text on colored backgrounds (button labels) is hard for OCR
4. CGEvent reliability varies — sometimes stops working mid-session

---

## Architecture Summary

```
┌──────────────────────────────────┐
│          MCP Layer               │  22 tools (19 original + interact + window_scope/release)
├──────────────────────────────────┤
│          Engine Layer            │  InputChain + Guardian + WindowSession
├──────────────────────────────────┤
│        Platform Layer            │  Protocols → Factory → per-platform backends
│  InputBackend │ CaptureBackend   │
│  WindowBackend│ OCRBackend       │
│  WindowCaptureBackend (NEW)      │
├──────────────────────────────────┤
│    macOS / Windows / Linux       │  CGEvent, AX, Quartz, Win32, X11
└──────────────────────────────────┘
```

### Key Files
| File | Purpose |
|------|---------|
| `mcp/handlers.py` | All MCP tool handlers including interact, window_scope |
| `mcp/tools.py` | Tool schemas (22 tools) |
| `engine/window_session.py` | Window-scoped state + coord translation |
| `engine/input_chain.py` | Multi-backend fallback chain |
| `engine/guardian.py` | Safety: user priority + scope lock |
| `platform/macos/window_capture.py` | CGWindowListCreateImage backend |
| `platform/macos/capture.py` | Full-screen capture (mss) |
| `platform/macos/vision.py` | Apple Vision OCR |
| `platform/protocols.py` | 5 Protocol definitions |
| `platform/__init__.py` | Platform factory |
| `config.py` | Centralized config + env overrides |
| `testing/` | E2E test session/verifier/reporter framework |
