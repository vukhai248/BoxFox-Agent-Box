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


# ---------------------------------------------------------------------------
# inspect_point — element-selector §7-B2. Đọc JSON từ STDIN (không qua argv,
# vì `candidates` mang webSocketDebuggerUrl — argv hiện trong `ps`/`/proc/<pid>/cmdline`
# của MỌI tiến trình trong container).
# ---------------------------------------------------------------------------

# Ngưỡng khớp cửa sổ khi có nhiều CDP target ứng viên (Browser.getWindowForTarget
# so với hình học X11 đã hit-test).
WINDOW_MATCH_TOLERANCE_PX = 80
# Chốt chặn 2 (sanity check còn lại sau khi đã loại DevTools docked ở chốt chặn 1):
# side panel / theme lạ vượt ngưỡng này ⇒ viewport_origin_unknown thay vì suy sai.
MAX_CHROME_HEIGHT_PX = 200
MAX_SIDE_SLACK_PX = 24

VIEWPORT_EXPRESSION = r"""
(() => ({
  dpr: window.devicePixelRatio || 1,
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight,
  outerWidth: window.outerWidth,
  outerHeight: window.outerHeight,
  screenX: window.screenX,
  screenY: window.screenY,
  url: document.location ? document.location.href : '',
  title: document.title || '',
}))()
"""

# Text/comment node → cha có phần tử (DOM.getNodeForLocation có thể trả một text
# node — CSS box/attributes chỉ có ý nghĩa trên phần tử).
ELEMENT_OF_FN = r"""
function() {
  var TEXT_NODE = 3, COMMENT_NODE = 8;
  if ((this.nodeType === TEXT_NODE || this.nodeType === COMMENT_NODE) && this.parentElement) {
    return this.parentElement;
  }
  return this;
}
"""

# Selector theo thứ tự ưu tiên #id → tag.class(tối đa 4) → :nth-of-type → giữ +
# ghi chú "selector_not_unique". KHÔNG đọc data-boxfox-src (Phase 1, §10.3).
# Kiểm tra duy nhất chạy trên getRootNode() — KHÔNG document — để đúng trong
# shadow root (author).
EXTRACT_FN = r"""
function(maxText, maxAttrs, maxAttrValue) {
  var notes = [];
  var node = this;
  if (node.nodeType !== 1) {
    return {error: 'not_element'};
  }
  var root = node.getRootNode ? node.getRootNode() : document;
  var isUnique = function(sel) {
    try {
      var found = root.querySelectorAll(sel);
      return found.length === 1 && found[0] === node;
    } catch (e) {
      return false;
    }
  };
  var selector = null;
  if (node.id && /^[A-Za-z][A-Za-z0-9_-]*$/.test(node.id)) {
    var byId = '#' + node.id;
    if (isUnique(byId)) selector = byId;
  }
  if (!selector) {
    var tag = node.tagName.toLowerCase();
    var classes = (node.className && typeof node.className === 'string')
      ? node.className.trim().split(/\s+/).filter(Boolean).slice(0, 4)
      : [];
    var candidate = tag + classes.map(function(c) { return '.' + c; }).join('');
    if (isUnique(candidate)) {
      selector = candidate;
    } else {
      var index = 1;
      var sibling = node;
      while ((sibling = sibling.previousElementSibling)) {
        if (sibling.tagName === node.tagName) index += 1;
      }
      candidate = candidate + ':nth-of-type(' + index + ')';
      selector = candidate;
      if (!isUnique(candidate)) notes.push('selector_not_unique');
    }
  }
  var shadowHostSelector = null;
  if (root !== document && root.host) {
    shadowHostSelector = root.host.tagName ? root.host.tagName.toLowerCase() : null;
    notes.push('shadow_dom');
  }
  if (node.ownerDocument !== document) {
    notes.push('iframe_boundary');
  }
  var fullText = node.textContent || '';
  var textTruncated = fullText.length > maxText;
  var text = fullText.slice(0, maxText);

  var attributes = {};
  var attrCount = 0;
  var attrsTruncated = false;
  var attrList = Array.prototype.slice.call(node.attributes || []);
  for (var i = 0; i < attrList.length; i++) {
    if (attrCount >= maxAttrs) { attrsTruncated = true; break; }
    var attr = attrList[i];
    var value = attr.value || '';
    if (value.length > maxAttrValue) { value = value.slice(0, maxAttrValue); attrsTruncated = true; }
    attributes[attr.name] = value;
    attrCount += 1;
  }

  return {
    tagName: node.tagName.toLowerCase(),
    selector: selector,
    text: text,
    textTruncated: textTruncated,
    attributes: attributes,
    attrsTruncated: attrsTruncated,
    notes: notes,
    shadowHostSelector: shadowHostSelector,
  };
}
"""


# --- Hàm thuần (test được không cần socket) ---------------------------------
def content_origin(win_geom: dict, metrics: dict) -> tuple[float, float]:
    """Gốc (trên-trái) của viewport CSS trong toạ độ màn hình X11.

    Giả định (KHÔNG luôn đúng — xem sanity check `_viewport_origin_plausible`):
    viewport sát ĐÁY cửa sổ client, căn GIỮA ngang.
    """
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    origin_y = win_geom["y"] + win_geom["h"] - metrics["innerHeight"] * dpr
    origin_x = win_geom["x"] + (win_geom["w"] - metrics["innerWidth"] * dpr) / 2.0
    return origin_x, origin_y


def screen_to_css(screen_x: float, screen_y: float, win_geom: dict, metrics: dict) -> tuple[float, float]:
    origin_x, origin_y = content_origin(win_geom, metrics)
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    return (screen_x - origin_x) / dpr, (screen_y - origin_y) / dpr


def point_in_viewport(css_x: float, css_y: float, metrics: dict) -> bool:
    return 0 <= css_x < metrics["innerWidth"] and 0 <= css_y < metrics["innerHeight"]


def quad_to_css_box(quad: list[float]) -> dict:
    # CDP content quad: 8 số [x1,y1, x2,y2, x3,y3, x4,y4] (4 góc, không nhất thiết
    # theo thứ tự trục) → bounding box qua min/max.
    xs = quad[0::2]
    ys = quad[1::2]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    return {"x": x_min, "y": y_min, "width": x_max - x_min, "height": y_max - y_min}


def css_box_to_screen_box(css_box: dict, origin_x: float, origin_y: float, dpr: float) -> dict:
    return {
        "x": round(origin_x + css_box["x"] * dpr),
        "y": round(origin_y + css_box["y"] * dpr),
        "width": round(css_box["width"] * dpr),
        "height": round(css_box["height"] * dpr),
    }


def _bounds_score(bounds: dict, win_geom: dict) -> float:
    left = abs(float(bounds.get("left", 0)) - float(win_geom.get("x", 0)))
    top = abs(float(bounds.get("top", 0)) - float(win_geom.get("y", 0)))
    width = abs(float(bounds.get("width", 0)) - float(win_geom.get("w", 0)))
    height = abs(float(bounds.get("height", 0)) - float(win_geom.get("h", 0)))
    return left + top + width + height


def _viewport_origin_plausible(win_geom: dict, metrics: dict) -> bool:
    """Chốt chặn 2: sai lệch còn lại (side panel, theme lạ) sau khi chốt chặn 1
    (DevTools docked, xem `_devtools_docked`) đã loại DevTools."""
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    slack_x = win_geom["w"] - metrics["innerWidth"] * dpr
    slack_y = win_geom["h"] - metrics["innerHeight"] * dpr
    return 0 <= slack_y <= MAX_CHROME_HEIGHT_PX and 0 <= slack_x <= MAX_SIDE_SLACK_PX


def viewport_metrics(ws: "WebSocket") -> dict:
    response = ws.call("Runtime.evaluate", {
        "expression": VIEWPORT_EXPRESSION,
        "returnByValue": True,
    })
    value = response.get("result", {}).get("result", {}).get("value")
    if not isinstance(value, dict):
        raise WebSocketError("Runtime.evaluate không trả object viewport hợp lệ")
    for key in ("dpr", "innerWidth", "innerHeight"):
        if key not in value:
            raise WebSocketError(f"Viewport metrics thiếu khoá {key}")
    return value


def _select_target(ws_browser: "WebSocket | None", candidates: list[dict], win_geom: dict) -> tuple[dict | None, str | None]:
    if len(candidates) == 1:
        return candidates[0], None
    if ws_browser is None:
        return None, "ambiguous_target"

    scored: list[tuple[float, dict]] = []
    for candidate in candidates:
        try:
            response = ws_browser.call("Browser.getWindowForTarget", {"targetId": candidate.get("targetId")})
            bounds = response.get("result", {}).get("bounds") or {}
        except (WebSocketError, OSError, KeyError, TypeError):
            continue
        scored.append((_bounds_score(bounds, win_geom), candidate))

    if scored:
        scored.sort(key=lambda item: item[0])
        within_tolerance = [item for item in scored if item[0] <= WINDOW_MATCH_TOLERANCE_PX]
        if len(within_tolerance) == 1:
            return within_tolerance[0][1], None

    # Dự phòng cuối: khớp theo tiêu đề (tiêu đề trang thường là tiền tố tiêu đề cửa sổ).
    window_title = win_geom.get("title") or ""
    title_matches = [
        candidate for candidate in candidates
        if window_title and window_title.startswith(candidate.get("title") or "\0")
    ]
    if len(title_matches) == 1:
        return title_matches[0], None

    return None, "ambiguous_target"


def _devtools_docked(ws_browser: "WebSocket | None", page_target_id: str, devtools_target_ids: list[str]) -> bool:
    """Chốt chặn 1 — tất định, KHÔNG dựa vào ngưỡng slackY. Mọi lỗi đọc/gọi CDP
    trên đường này FAIL-CLOSED thành docked=True (§7-B2)."""
    if not devtools_target_ids:
        return False
    if ws_browser is None:
        return True
    try:
        page_window_id = ws_browser.call(
            "Browser.getWindowForTarget", {"targetId": page_target_id}
        )["result"]["windowId"]
    except (WebSocketError, OSError, KeyError, TypeError):
        return True
    for devtools_id in devtools_target_ids:
        try:
            dt_window_id = ws_browser.call(
                "Browser.getWindowForTarget", {"targetId": devtools_id}
            )["result"]["windowId"]
        except (WebSocketError, OSError, KeyError, TypeError):
            return True
        if dt_window_id == page_window_id:
            return True
    return False


def extract_at(ws: "WebSocket", point: dict, win_geom: dict, limits: dict, selected: dict) -> dict:
    """Chuỗi CDP trên MỘT kết nối cấp page — thứ tự lệnh là hợp đồng có test khoá."""
    max_text = int(limits.get("maxText") or 2048)
    max_attrs = int(limits.get("maxAttrs") or 32)
    max_attr_value = int(limits.get("maxAttrValue") or 512)

    metrics = viewport_metrics(ws)  # (1) Runtime.evaluate

    if not _viewport_origin_plausible(win_geom, metrics):
        return {"ok": False, "reason": "viewport_origin_unknown"}

    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    origin_x, origin_y = content_origin(win_geom, metrics)
    css_x, css_y = screen_to_css(float(point["x"]), float(point["y"]), win_geom, metrics)

    if not point_in_viewport(css_x, css_y, metrics):
        return {"ok": False, "reason": "outside_viewport"}

    try:
        ws.call("DOM.enable", {})  # (2)
        ws.call("DOM.getDocument", {"depth": 0})  # (3)

        location = ws.call("DOM.getNodeForLocation", {  # (4)
            "x": round(css_x), "y": round(css_y), "includeUserAgentShadowDOM": False,
        }).get("result", {})
        backend_node_id = location.get("backendNodeId")
        if not backend_node_id:
            return {"ok": False, "reason": "no_node_at_point"}

        resolved = ws.call("DOM.resolveNode", {"backendNodeId": backend_node_id}).get("result", {})  # (5)
        object_id = (resolved.get("object") or {}).get("objectId")
        if not object_id:
            return {"ok": False, "reason": "no_node_at_point"}

        promoted = ws.call("Runtime.callFunctionOn", {  # (6)
            "objectId": object_id,
            "functionDeclaration": ELEMENT_OF_FN,
            "returnByValue": False,
        }).get("result", {}).get("result", {})
        element_object_id = promoted.get("objectId") or object_id

        extracted = ws.call("Runtime.callFunctionOn", {  # (7)
            "objectId": element_object_id,
            "functionDeclaration": EXTRACT_FN,
            "arguments": [
                {"value": max_text}, {"value": max_attrs}, {"value": max_attr_value},
            ],
            "returnByValue": True,
        }).get("result", {}).get("result", {})
        data = extracted.get("value")
        if not isinstance(data, dict) or data.get("error"):
            return {"ok": False, "reason": "extract_failed"}

        html = ws.call("DOM.getOuterHTML", {"objectId": element_object_id}).get(  # (8)
            "result", {}
        ).get("outerHTML", "")
    except (WebSocketError, KeyError, TypeError):
        return {"ok": False, "reason": "extract_failed"}

    css_box = None
    screen_box = None
    try:
        box_model = ws.call("DOM.getBoxModel", {"objectId": element_object_id}).get(  # (9)
            "result", {}
        ).get("model")
        if box_model and box_model.get("content"):
            css_box = quad_to_css_box(box_model["content"])
            screen_box = css_box_to_screen_box(css_box, origin_x, origin_y, dpr)
    except WebSocketError:
        pass  # box model thiếu vẫn OK — trả cssBox/screenBox = None (§7-B2)

    return {
        "ok": True,
        "url": metrics.get("url", ""),
        "title": metrics.get("title", ""),
        "tagName": data.get("tagName", ""),
        "selector": data.get("selector"),
        "text": data.get("text", ""),
        "attributes": data.get("attributes", {}),
        "html": html,
        "truncatedInPage": bool(data.get("textTruncated") or data.get("attrsTruncated")),
        "cssBox": css_box,
        "screenBox": screen_box,
        "notes": data.get("notes", []),
        "shadowHostSelector": data.get("shadowHostSelector"),
        "targetId": str(selected.get("targetId") or ""),
    }


def inspect_point(request: dict) -> dict:
    """Điểm vào duy nhất của subcommand `inspect_point` — orchestrate lựa target,
    kiểm DevTools docked, rồi `extract_at` trên kết nối cấp page.

    KHÔNG BAO GIỜ in `webSocketDebuggerUrl`/`browserWebSocketUrl` ra stdout hay
    stderr — chỉ `targetId`/`url` (URL TRANG WEB, không phải debugger)/`title`/`reason`.
    """
    point = request["point"]
    win_geom = request["window"]
    candidates = request.get("candidates") or []
    devtools_ids = request.get("devtoolsTargetIds") or []
    limits = request.get("limits") or {}
    browser_ws_url = request.get("browserWebSocketUrl")
    cdp_timeout = float(limits.get("cdpTimeoutSec") or 5.0)

    if not candidates:
        return {"ok": False, "reason": "no_cdp_target"}

    need_browser_ws = len(candidates) > 1 or bool(devtools_ids)
    ws_browser: WebSocket | None = None
    try:
        if need_browser_ws:
            if not browser_ws_url:
                return {"ok": False, "reason": "cdp_unreachable"}
            ws_browser = WebSocket(browser_ws_url, timeout=cdp_timeout)
            ws_browser.connect()

        selected, reason = _select_target(ws_browser, candidates, win_geom)
        if selected is None:
            return {"ok": False, "reason": reason or "ambiguous_target"}

        if _devtools_docked(ws_browser, str(selected.get("targetId") or ""), devtools_ids):
            return {"ok": False, "reason": "devtools_docked"}
    finally:
        if ws_browser is not None:
            ws_browser.close()

    page_ws_url = selected.get("webSocketDebuggerUrl")
    if not page_ws_url:
        return {"ok": False, "reason": "no_cdp_target"}

    ws_page = WebSocket(page_ws_url, timeout=cdp_timeout)
    try:
        ws_page.connect()
        return extract_at(ws_page, point, win_geom, limits, selected)
    finally:
        ws_page.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    capture = sub.add_parser("capture_tab")
    capture.add_argument("--web-socket-url", required=True)
    capture.add_argument("--path", required=True)
    capture.add_argument("--format", default="png", choices=("png", "jpg"))
    capture.add_argument("--full-page", action="store_true")

    # Không flag — request (có URL debugger) tới bằng JSON trên STDIN, không qua
    # argv (§10.1: argv hiện trong ps của mọi tiến trình trong container).
    sub.add_parser("inspect_point")
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
    if args.command == "inspect_point":
        try:
            request = json.load(sys.stdin)
            result = inspect_point(request)
        except (WebSocketError, OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            print(f"browser_capture: {error}", file=sys.stderr)
            return 1
        print(json.dumps(result))
        return 0
    if args.command != "capture_tab":
        print("Chưa có lệnh — dùng subcommand capture_tab hoặc inspect_point.", file=sys.stderr)
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
