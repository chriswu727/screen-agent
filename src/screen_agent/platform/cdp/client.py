"""Minimal Chrome DevTools Protocol client.

Zero dependencies beyond stdlib. Connects to Chrome's debugging port
via WebSocket, sends JSON-RPC commands, returns results.

Usage:
    async with CDPClient("localhost", 9222) as cdp:
        tabs = await cdp.list_tabs()
        await cdp.connect_tab(tabs[0]["id"])
        screenshot_b64 = await cdp.screenshot()
        await cdp.click(100, 200)
        await cdp.type_text("hello")
        result = await cdp.evaluate("document.title")
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import struct
import hashlib
import os
from typing import Any
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# Minimal WebSocket implementation (RFC 6455) — no dependencies
# Only supports client mode, text frames, and close frames.

def _ws_handshake_key() -> tuple[str, str]:
    """Generate WebSocket handshake key and expected accept value."""
    key_bytes = os.urandom(16)
    key = base64.b64encode(key_bytes).decode()
    magic = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    accept = base64.b64encode(
        hashlib.sha1((key + magic).encode()).digest()
    ).decode()
    return key, accept


async def _ws_connect(host: str, port: int, path: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    """Perform WebSocket handshake over TCP, return reader/writer."""
    reader, writer = await asyncio.open_connection(host, port)
    key, expected_accept = _ws_handshake_key()

    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    writer.write(request.encode())
    await writer.drain()

    # Read response headers
    response = b""
    while b"\r\n\r\n" not in response:
        chunk = await reader.read(4096)
        if not chunk:
            raise ConnectionError("WebSocket handshake failed: connection closed")
        response += chunk

    if b"101" not in response.split(b"\r\n")[0]:
        raise ConnectionError(f"WebSocket handshake rejected: {response[:200]}")

    return reader, writer


def _ws_encode_frame(data: str) -> bytes:
    """Encode a text WebSocket frame with masking (client must mask)."""
    payload = data.encode("utf-8")
    mask_key = os.urandom(4)
    masked = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

    frame = bytearray()
    frame.append(0x81)  # FIN + text opcode

    length = len(payload)
    if length < 126:
        frame.append(0x80 | length)  # mask bit set
    elif length < 65536:
        frame.append(0x80 | 126)
        frame.extend(struct.pack(">H", length))
    else:
        frame.append(0x80 | 127)
        frame.extend(struct.pack(">Q", length))

    frame.extend(mask_key)
    frame.extend(masked)
    return bytes(frame)


async def _ws_read_frame(reader: asyncio.StreamReader) -> str | None:
    """Read one WebSocket text frame. Returns None on close."""
    header = await reader.readexactly(2)
    opcode = header[0] & 0x0F
    is_masked = bool(header[1] & 0x80)
    length = header[1] & 0x7F

    if length == 126:
        length = struct.unpack(">H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack(">Q", await reader.readexactly(8))[0]

    if is_masked:
        mask = await reader.readexactly(4)
        data = await reader.readexactly(length)
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    else:
        data = await reader.readexactly(length)

    if opcode == 0x08:  # close
        return None
    if opcode == 0x01:  # text
        return data.decode("utf-8")
    # ping/pong/continuation — skip
    return ""


class CDPClient:
    """Async Chrome DevTools Protocol client."""

    def __init__(self, host: str = "localhost", port: int = 9222):
        self.host = host
        self.port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._msg_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._recv_task: asyncio.Task | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.close()

    async def list_tabs(self) -> list[dict]:
        """Get all browser tabs via HTTP endpoint."""
        url = f"http://{self.host}:{self.port}/json"
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: urlopen(url, timeout=5).read())
        tabs = json.loads(data)
        return [t for t in tabs if t.get("type") == "page"]

    async def find_tab(self, url_contains: str | None = None, title_contains: str | None = None) -> dict | None:
        """Find a tab by URL or title substring."""
        tabs = await self.list_tabs()
        for tab in tabs:
            url_match = url_contains is None or url_contains.lower() in tab.get("url", "").lower()
            title_match = title_contains is None or title_contains.lower() in tab.get("title", "").lower()
            if url_match and title_match:
                return tab
        return None

    async def connect_tab(self, tab_id: str) -> None:
        """Connect to a specific tab via its WebSocket debug URL."""
        ws_url = f"ws://{self.host}:{self.port}/devtools/page/{tab_id}"
        # Parse ws URL for path
        path = f"/devtools/page/{tab_id}"
        self._reader, self._writer = await _ws_connect(self.host, self.port, path)
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info("CDP connected to tab %s", tab_id)

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass

    async def send(self, method: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        """Send a CDP command and wait for response."""
        if not self._writer:
            raise RuntimeError("Not connected — call connect_tab first")

        self._msg_id += 1
        msg_id = self._msg_id
        msg = {"id": msg_id, "method": method}
        if params:
            msg["params"] = params

        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[msg_id] = future

        frame = _ws_encode_frame(json.dumps(msg))
        self._writer.write(frame)
        await self._writer.drain()

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(msg_id, None)
            raise TimeoutError(f"CDP command {method} timed out after {timeout}s")

        if "error" in result:
            raise RuntimeError(f"CDP error: {result['error']}")
        return result.get("result", {})

    async def _recv_loop(self) -> None:
        """Background task: read WebSocket frames and dispatch responses."""
        while True:
            try:
                text = await _ws_read_frame(self._reader)
                if text is None:
                    break
                if not text:
                    continue
                msg = json.loads(text)
                msg_id = msg.get("id")
                if msg_id and msg_id in self._pending:
                    self._pending.pop(msg_id).set_result(msg)
            except (asyncio.CancelledError, asyncio.IncompleteReadError):
                break
            except Exception as e:
                logger.debug("CDP recv error: %s", e)
                break

    # ── High-level API ──────────────────────────────────────

    async def screenshot(self, format: str = "jpeg", quality: int = 75) -> str:
        """Take a screenshot. Returns base64-encoded image."""
        params = {"format": format}
        if format == "jpeg":
            params["quality"] = quality
        result = await self.send("Page.captureScreenshot", params)
        return result["data"]

    async def click(self, x: int, y: int, button: str = "left") -> None:
        """Click at page coordinates."""
        btn = {"left": "left", "right": "right", "middle": "middle"}.get(button, "left")
        await self.send("Input.dispatchMouseEvent", {
            "type": "mousePressed", "x": x, "y": y, "button": btn, "clickCount": 1,
        })
        await self.send("Input.dispatchMouseEvent", {
            "type": "mouseReleased", "x": x, "y": y, "button": btn, "clickCount": 1,
        })

    async def type_text(self, text: str) -> None:
        """Type text character by character."""
        for char in text:
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "text": char,
            })
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyUp",
            })

    async def press_key(self, key: str) -> None:
        """Press a special key (Enter, Tab, Escape, etc.)."""
        key_map = {
            "enter": ("Enter", "\r", 13),
            "tab": ("Tab", "\t", 9),
            "escape": ("Escape", "\x1b", 27),
            "backspace": ("Backspace", "\b", 8),
            "space": (" ", " ", 32),
        }
        if key.lower() in key_map:
            name, text, code = key_map[key.lower()]
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "key": name, "text": text,
                "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code,
            })
            await self.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "key": name,
                "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code,
            })
        else:
            await self.type_text(key)

    async def evaluate(self, expression: str) -> Any:
        """Execute JavaScript and return the result."""
        result = await self.send("Runtime.evaluate", {
            "expression": expression, "returnByValue": True,
        })
        val = result.get("result", {})
        if val.get("type") == "undefined":
            return None
        return val.get("value", val.get("description", str(val)))

    async def navigate(self, url: str) -> None:
        """Navigate to a URL."""
        await self.send("Page.navigate", {"url": url})
        # Wait for load
        await self.send("Page.enable")
        # Give it a moment
        await asyncio.sleep(0.5)

    async def get_page_info(self) -> dict:
        """Get current page URL and title."""
        title = await self.evaluate("document.title")
        url = await self.evaluate("window.location.href")
        return {"title": title, "url": url}
