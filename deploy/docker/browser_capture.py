#!/usr/bin/env python3
"""Chụp một tab Chromium qua CDP bằng WebSocket (thuần stdlib).

Vì sao stdlib, không import Playwright: chỉ cần đúng MỘT lệnh CDP
(`Page.captureScreenshot`) tới đúng target qua `webSocketDebuggerUrl` lấy được từ
`/json/list`. Chụp qua WeSocket chính target nên địa chỉ đích (theo target id) là
tuyệt đối — không cần ánh xạ target id ↔ Playwright Page (mong manh), cũng không
kéo Playwright nặng vào tiến trình điều khiển box.

Cách dùng (được capture.py gọi qua subprocess):
    python3 browser_capture.py capture_tab \
        --web-socket-url ws://127.0.0.1:9222/devtools/page/<ID> \
        --path /path/out.png --format png [--full-page]

Kết quả: in JSON ra stdout — {"path": ..., "width": ..., "height": ..., "format": ...}
Lỗi: in lý do ra stderr và exit != 0.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import struct
import sys
import urllib.parse
from pathlib import Path


class WebSocketError(RuntimeError):
    pass


# --- Frame primitives (thuần hàm để unit-test được) -------------------------
def apply_mask(data: bytes, mask: bytes) -> bytes:
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))


def make_frame(opcode: int, payload: bytes, *, masked: bool = True) -> bytes:
    mask = os.urandom(4) if masked else None
    length = len(payload)
    header = bytearray([0x80 | (opcode & 0x0F)])
    if length < 126:
        header.append((0x80 if masked else 0x00) | length)
    elif length < 65536:
        header.append((0x80 if masked else 0x00) | 126)
        header += struct.pack(">H", length)
    else:
        header.append((0x80 if masked else 0x00) | 127)
        header += struct.pack(">Q", length)
    if mask:
        header += mask
        payload = apply_mask(payload, mask)
    return bytes(header) + payload


class WebSocket:
    """WebSocket client tối giản — đủ dùng cho CDP request/response + event."""

    OP_TEXT = 0x1
    OP_BINARY = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    def __init__(self, ws_url: str, timeout: float = 30.0):
        self.ws_url = ws_url
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._next_id = 0

    def connect(self) -> None:
        parsed = urllib.parse.urlsplit(self.ws_url)
        if parsed.scheme != "ws":
            raise WebSocketError(f"Chỉ hỗ trợ ws:// (nhận: {parsed.scheme})")
        host = parsed.hostname
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"

        self._sock = socket.create_connection((host, port), timeout=self.timeout)
        self._sock.settimeout(self.timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(request.encode("ascii"))

        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("WebSocket handshake: kết nối bị đóng")
            head += chunk
        header, self._buffer = head.split(b"\r\n\r\n", 1)
        status_line = header.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise WebSocketError(f"WebSocket handshake bị từ chối: {status_line[:200]!r}")

    def _read_exact(self, length: int) -> bytes:
        data = bytearray()
        sock = self._sock
        while len(data) < length:
            if self._buffer:
                take = self._buffer[:length - len(data)]
                self._buffer = self._buffer[len(take):]
                data += take
            else:
                assert sock is not None
                chunk = sock.recv(length - len(data))
                if not chunk:
                    raise ConnectionError("WebSocket bị đóng giữa chừng")
                data += chunk
        return bytes(data)

    def _read_frame(self) -> tuple[bool, int, bytes]:
        b0 = self._read_exact(1)[0]
        b1 = self._read_exact(1)[0]
        fin = (b0 & 0x80) != 0
        opcode = b0 & 0x0F
        masked = (b1 & 0x80) != 0
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else None
        payload = self._read_exact(length)
        if mask:
            payload = apply_mask(payload, mask)
        return fin, opcode, payload

    def send_text(self, text: str) -> None:
        assert self._sock is not None
        self._sock.sendall(make_frame(self.OP_TEXT, text.encode("utf-8"), masked=True))

    def send_pong(self, payload: bytes) -> None:
        assert self._sock is not None
        self._sock.sendall(make_frame(self.OP_PONG, payload, masked=True))

    def close(self) -> None:
        if not self._sock:
            return
        try:
            self._sock.sendall(make_frame(self.OP_CLOSE, b"", masked=True))
            self._sock.close()
        except OSError:
            pass
        self._sock = None

    def call(self, method: str, params: dict | None = None) -> dict:
        """Gửi một lệnh CDP, đọc frame cho tới khi nhận response khớp `id`.

        Các event CDP (không có `id`) bị đọc và bỏ qua; ping được trả pong.
        """
        self._next_id += 1
        message_id = self._next_id
        self.send_text(json.dumps({
            "id": message_id,
            "method": method,
            "params": params or {},
        }))

        fragments: list[str] = []
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == self.OP_CLOSE:
                raise ConnectionError("CDP đóng WebSocket")
            if opcode == self.OP_PING:
                self.send_pong(payload)
                continue
            if opcode == self.OP_PONG:
                continue
            if opcode in (self.OP_TEXT, self.OP_BINARY):
                text = payload.decode("utf-8", "replace")
                fragments.append(text)
                if not fin:
                    continue
                full = "".join(fragments)
                fragments = []
                try:
                    obj = json.loads(full)
                except json.JSONDecodeError:
                    continue
                if obj.get("id") == message_id:
                    if "error" in obj:
                        raise WebSocketError(f"CDP {method} lỗi: {obj['error']}")
                    return obj
                # event hoặc response của lệnh khác → bỏ qua
                continue
            # RSV/unknown opcode → bỏ qua để không treo


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    capture = sub.add_parser("capture_tab")
    capture.add_argument("--web-socket-url", required=True)
    capture.add_argument("--path", required=True)
    capture.add_argument("--format", default="png", choices=("png", "jpg"))
    capture.add_argument("--full-page", action="store_true")
    return parser.parse_args()


def capture_tab(ws_url: str, path: str, fmt: str, full_page: bool) -> dict:
    ws = WebSocket(ws_url)
    try:
        ws.connect()
        ws.call("Page.enable", {})
        metrics = ws.call("Page.getLayoutMetrics", {}).get("result", {})
        width = 0
        height = 0

        if full_page:
            size = metrics.get("cssContentSize") or metrics.get("contentSize") or {}
            width = int(size.get("width") or 0)
            height = int(size.get("height") or 0)
            if width <= 0 or height <= 0:
                raise WebSocketError("Không lấy được kích thước toàn trang (Page.getLayoutMetrics)")
            params = {
                "format": fmt,
                "fromSurface": True,
                "captureBeyondViewport": True,
                "clip": {"x": 0, "y": 0, "width": width, "height": height, "scale": 1},
            }
        else:
            viewport = metrics.get("layoutViewport") or {}
            width = int(viewport.get("clientWidth") or 0)
            height = int(viewport.get("clientHeight") or 0)
            params = {"format": fmt, "fromSurface": True}

        if fmt == "jpg":
            params["quality"] = 85

        response = ws.call("Page.captureScreenshot", params)
        data = response["result"]["data"]
        raw = base64.b64decode(data)
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
        return {"path": path, "width": width, "height": height, "format": fmt}
    finally:
        ws.close()


def main() -> int:
    args = _parse_args()
    if args.command != "capture_tab":
        print("Chưa có lệnh — dùng subcommand capture_tab.", file=sys.stderr)
        return 2
    try:
        result = capture_tab(args.web_socket_url, args.path, args.format, args.full_page)
    except (WebSocketError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"browser_capture: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
