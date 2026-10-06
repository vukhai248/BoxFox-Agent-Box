"""Soi phần tử trong host mode — ba nhánh ``dom`` → ``uia`` → ``desktop`` (H6, §4.1).

Cùng hợp đồng với ``deploy/docker/inspect_element.py`` (bản trong box): payload
``dom`` giữ nguyên bộ trường, ``label`` giữ nguyên định dạng, 11 mã ``reason`` cũ
được giữ nguyên và thêm 6 mã cho Windows. Khác biệt duy nhất về nguồn dữ liệu:
ở host mode ta không có X11 nên danh tính cửa sổ đến từ Win32, và nhánh ``uia``
mới xuất hiện ở giữa.

Thứ tự nhánh là **hợp đồng**: nhánh đầu tiên trả được dữ liệu sẽ thắng.

1. ``dom`` — cửa sổ dưới điểm bấm là Chromium **và** có endpoint CDP loopback hợp
   lệ: ``DOM.getNodeForLocation`` + ``Runtime.callFunctionOn`` y như trong box.
2. ``uia`` — UI Automation (mới, xem :mod:`agentbox.sandbox.win.uia`).
3. ``desktop`` — thoái hoá mềm kèm ``reason``/``message``.

Bất biến không được vi phạm: ``webSocketDebuggerUrl`` **không bao giờ** rời khỏi
tiến trình này. Khối ``target`` chỉ có đúng ba khoá (``windowId``,
``windowTitle``, ``targetId``) — dựng tại một chokepoint duy nhất
:func:`_public_inspect_target`.

``content_hash`` tính đúng ba bước: dựng payload ngữ nghĩa **chưa** có ``label`` →
``sha256`` trên JSON chuẩn hoá → gắn ``label``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from types import SimpleNamespace
from typing import Any, Callable

from ..sandbox.win.errors import (
    AMBIGUOUS_TARGET,
    CDP_TIMEOUT,
    CDP_UNREACHABLE,
    CONTROL_BUSY,
    DEVTOOLS_DOCKED,
    EXTRACT_FAILED,
    FRAME_EXTENTS_UNKNOWN,
    INSPECT_MESSAGES,
    INSPECT_REASONS,
    NOT_CHROMIUM,
    NO_CDP_TARGET,
    NO_NODE_AT_POINT,
    NO_WINDOW_AT_POINT,
    OUTSIDE_VIEWPORT,
    UIA_NO_ELEMENT,
    UIA_PROVIDER_HANG,
    UIA_PROVIDER_HANG_REASON,
    UIA_TIMEOUT,
    UIA_TIMEOUT_REASON,
    UIA_UNAVAILABLE,
    UIA_UNAVAILABLE_REASON,
    VIEWPORT_ORIGIN_UNKNOWN,
    WINDOW_IDENTITY_UNAVAILABLE_REASON,
    PlatformError,
)

# --- hằng số dùng chung với bản trong box ----------------------------------
INTEGRITY_UNTRUSTED = "khong_tin_duoc"
CONFIDENTIALITY_INTERNAL = "noi_bo"
SOURCE_KIND_SCREEN = "screen_capture"
TOOL_NAME = "inspect_element"

MAX_HTML_BYTES = 8 * 1024
MAX_TEXT_BYTES = 2 * 1024
MAX_ATTRS = 32
MAX_ATTR_VALUE_BYTES = 512

MAX_SIDE_SLACK_PX = 24
MAX_CHROME_HEIGHT_PX = 200
CDP_CALL_TIMEOUT_SEC = 5.0
REQUEST_BUDGET_SEC = 8.0
MAX_CONCURRENT_INSPECTS = 2
MAX_TABS_IN_PAYLOAD = 10
MAX_AMBIGUOUS_CANDIDATES = 10

#: Lớp cửa sổ của Chromium/Electron trên Windows.
CHROMIUM_CLASS_HINTS = ("chrome_widgetwin", "chromium", "chrome")
#: Tên tiến trình Chromium thường gặp (so khớp trên tên tệp, không phải đường dẫn).
CHROMIUM_PROCESS_NAMES = (
    "chrome.exe",
    "msedge.exe",
    "chromium.exe",
    "brave.exe",
    "vivaldi.exe",
    "opera.exe",
    "thorium.exe",
    "electron.exe",
)
#: Cổng debug mặc định được dò trên loopback khi chưa cấu hình endpoint.
CDP_DEFAULT_PORTS = (9222, 9223, 9224, 9229, 9333, 9444)
#: Thời gian sống của kết quả dò endpoint (giây).
CDP_DISCOVERY_TTL_SEC = 5.0

_INSPECT_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_INSPECTS)

#: Mã lỗi hành động → mã ``reason`` của nhánh soi.
_UIA_REASON_BY_CODE: dict[str, str] = {
    UIA_UNAVAILABLE: UIA_UNAVAILABLE_REASON,
    UIA_TIMEOUT: UIA_TIMEOUT_REASON,
    UIA_PROVIDER_HANG: UIA_PROVIDER_HANG_REASON,
    UIA_NO_ELEMENT: UIA_NO_ELEMENT,
    "not_implemented": UIA_UNAVAILABLE_REASON,
}

_WIN_MODULES: SimpleNamespace | None = None


def _win() -> SimpleNamespace:
    """Nạp lười gói nền tảng Windows (import trên Linux vẫn phải thành công)."""
    global _WIN_MODULES
    if _WIN_MODULES is None:
        from ..sandbox.win import capture, input as win_input, uia, windows_platform

        _WIN_MODULES = SimpleNamespace(
            capture=capture, input=win_input, uia=uia, platform=windows_platform
        )
    return _WIN_MODULES


# ---------------------------------------------------------------------------
# Tiện ích văn bản (giữ nguyên hành vi của bản trong box)
# ---------------------------------------------------------------------------
def _truncate_text(value: Any, limit: int) -> tuple[str, bool]:
    text = "" if value is None else str(value)
    if len(text.encode("utf-8", "replace")) <= limit:
        return text, False
    encoded = text.encode("utf-8", "replace")[:limit]
    return encoded.decode("utf-8", "ignore"), True


def _truncate_attributes(attributes: Any) -> tuple[dict[str, str], bool]:
    if not isinstance(attributes, dict):
        return {}, False
    truncated = False
    result: dict[str, str] = {}
    for index, (key, value) in enumerate(attributes.items()):
        if index >= MAX_ATTRS:
            truncated = True
            break
        text, was_truncated = _truncate_text(value, MAX_ATTR_VALUE_BYTES)
        if was_truncated:
            truncated = True
        result[str(key)] = text
    return result, truncated


def _canonical_payload_hash(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _label(window_id: str, content_hash: str) -> dict:
    return {
        "integrity": INTEGRITY_UNTRUSTED,
        "confidentiality": CONFIDENTIALITY_INTERNAL,
        "source_kind": SOURCE_KIND_SCREEN,
        # KHÔNG nhúng selector — selector do trang kiểm soát.
        "source_uri": f"screen://element/{window_id}",
        "tool_name": TOOL_NAME,
        "content_hash": content_hash,
    }


def _app_name(window_class: str) -> str:
    window_class = window_class or ""
    if "." in window_class:
        return window_class.rsplit(".", 1)[-1]
    return window_class


def _public_inspect_target(window: Any, target_id: str) -> dict:
    """Chokepoint DUY NHẤT cho khối ``target`` — allow-list đúng ba khoá."""
    return {
        "windowId": _window_id(window),
        "windowTitle": str(getattr(window, "title", "") or ""),
        "targetId": str(target_id or ""),
    }


def _safe_tab_list(raw: Any) -> list[dict]:
    """Ba trường KHÔNG nhạy cảm của một tab khớp — hàng rào thứ hai."""
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw[:MAX_TABS_IN_PAYLOAD]:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "targetId": str(item.get("targetId") or "")[:64],
                "title": str(item.get("title") or "")[:120],
                "url": str(item.get("url") or "")[:300],
            }
        )
    return out


def _window_id(window: Any) -> str:
    hwnd = getattr(window, "hwnd", None)
    return "" if hwnd is None else str(int(hwnd))


def _window_rect(window: Any) -> dict:
    x, y, width, height = getattr(window, "bounds", (0, 0, 0, 0))
    return {"x": int(x), "y": int(y), "w": int(width), "h": int(height)}


# ---------------------------------------------------------------------------
# Neo phiên bản hình học (§4.5) — sổ revision nằm ở tầng nền tảng (capture.py)
# ---------------------------------------------------------------------------
def window_geometry_fingerprint(window: Any, dpi: int | None = None) -> tuple:
    return _win().capture.window_geometry_fingerprint(window, dpi)


def geometry_revision(source_id: str, fingerprint: Any, layout: Any = None) -> int:
    return _win().capture.geometry_revision(source_id, fingerprint, layout)


def current_geometry_revision(source_id: str) -> int | None:
    return _win().capture.current_geometry_revision(source_id)


def reset_geometry_state() -> None:
    """Chỉ dùng trong test."""
    _win().capture.reset_geometry_state()


def _source_id(window: Any) -> str:
    hwnd = getattr(window, "hwnd", None)
    if hwnd is None:
        return "screen"
    pid = getattr(window, "pid", None)
    return f"win:{int(hwnd)}:{0 if pid is None else int(pid)}"


# ---------------------------------------------------------------------------
# CDP — WebSocket tối giản (ws:// loopback) + dò endpoint
# ---------------------------------------------------------------------------
class WebSocketError(Exception):
    pass


class CdpError(Exception):
    """Lỗi có cấu trúc của nhánh ``dom`` — ``reason`` là mã của tầng soi."""

    def __init__(self, reason: str, message: str = "", **details: Any) -> None:
        self.reason = reason
        self.message = message or INSPECT_MESSAGES.get(reason, "")
        self.details = dict(details)
        super().__init__(f"{reason}: {self.message}")


class WebSocket:
    """Client RFC6455 tối giản, chỉ ``ws://`` — port từ ``deploy/docker/browser_capture.py``."""

    OP_TEXT = 0x1
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    def __init__(self, url: str, timeout: float = CDP_CALL_TIMEOUT_SEC) -> None:
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != "ws":
            raise WebSocketError(f"chỉ hỗ trợ ws:// (nhận {parsed.scheme!r})")
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or 80
        self._path = parsed.path or "/"
        if parsed.query:
            self._path += f"?{parsed.query}"
        self._timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._buffer = b""
        self._next_id = 0

    # -- kết nối -----------------------------------------------------------
    def connect(self) -> None:
        self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        self._sock.settimeout(self._timeout)
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {self._path} HTTP/1.1\r\n"
            f"Host: {self._host}:{self._port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode("ascii"))
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WebSocketError("bắt tay WebSocket thất bại (kết nối bị đóng)")
            header += chunk
        status_line = header.split(b"\r\n", 1)[0]
        if b" 101 " not in status_line:
            raise WebSocketError(f"bắt tay WebSocket thất bại: {status_line.decode('latin-1')}")
        self._buffer = header.split(b"\r\n\r\n", 1)[1]

    def close(self) -> None:
        if not self._sock:
            return
        try:
            self._sock.sendall(_make_frame(self.OP_CLOSE, b"", masked=True))
            self._sock.close()
        except OSError:
            pass
        self._sock = None

    # -- đọc/ghi -----------------------------------------------------------
    def _read_exact(self, count: int) -> bytes:
        assert self._sock is not None
        while len(self._buffer) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise WebSocketError("kết nối WebSocket bị đóng giữa chừng")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _read_frame(self) -> tuple[bool, int, bytes]:
        first, second = self._read_exact(2)
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        masked = bool(second & 0x80)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read_exact(8))[0]
        mask = self._read_exact(4) if masked else b""
        payload = self._read_exact(length) if length else b""
        if masked:
            payload = _apply_mask(payload, mask)
        return fin, opcode, payload

    def send_text(self, text: str) -> None:
        if not self._sock:
            raise WebSocketError("WebSocket chưa kết nối")
        self._sock.sendall(_make_frame(self.OP_TEXT, text.encode("utf-8"), masked=True))

    def call(self, method: str, params: dict | None = None) -> dict:
        """Gửi một lệnh CDP, đọc tới khi gặp response khớp ``id`` (bỏ qua event)."""
        self._next_id += 1
        message_id = self._next_id
        self.send_text(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        fragments: list[bytes] = []
        while True:
            fin, opcode, payload = self._read_frame()
            if opcode == self.OP_PING:
                if self._sock:
                    self._sock.sendall(_make_frame(self.OP_PONG, payload, masked=True))
                continue
            if opcode == self.OP_CLOSE:
                raise WebSocketError("máy chủ CDP đóng kết nối")
            if opcode == self.OP_PONG:
                continue
            if opcode in (0x0, self.OP_TEXT):
                fragments.append(payload)
                if not fin:
                    continue
                text = b"".join(fragments).decode("utf-8", "replace")
                fragments = []
                try:
                    message = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if message.get("id") != message_id:
                    continue  # event hoặc response của lệnh khác
                if "error" in message:
                    raise WebSocketError(f"CDP {method} lỗi: {message['error']}")
                return message
            # opcode lạ: bỏ qua để không treo


def _apply_mask(data: bytes, mask: bytes) -> bytes:
    if not mask:
        return data
    return bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))


def _make_frame(opcode: int, payload: bytes, *, masked: bool) -> bytes:
    header = bytearray([0x80 | opcode])
    length = len(payload)
    mask_bit = 0x80 if masked else 0
    if length < 126:
        header.append(mask_bit | length)
    elif length < 65536:
        header.append(mask_bit | 126)
        header += struct.pack(">H", length)
    else:
        header.append(mask_bit | 127)
        header += struct.pack(">Q", length)
    if not masked:
        return bytes(header) + payload
    mask = os.urandom(4)
    return bytes(header) + mask + _apply_mask(payload, mask)


def cdp_endpoint(*, force: bool = False) -> str | None:
    """Endpoint CDP loopback (``http://127.0.0.1:port``) hoặc ``None``.

    Thứ tự: ``AGENTBOX_CDP_ENDPOINT`` → ``BOXFOX_CDP_ENDPOINT`` → dò các cổng
    debug thường gặp trên loopback. Kết quả dò được nhớ 5 giây.
    """
    for name in ("AGENTBOX_CDP_ENDPOINT", "BOXFOX_CDP_ENDPOINT"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value.rstrip("/")
    global _discovered_endpoint, _discovered_at
    now = time.monotonic()
    if not force and _discovered_endpoint and now - _discovered_at < CDP_DISCOVERY_TTL_SEC:
        return _discovered_endpoint
    for port in CDP_DEFAULT_PORTS:
        candidate = f"http://127.0.0.1:{port}"
        if _endpoint_alive(candidate):
            _discovered_endpoint, _discovered_at = candidate, now
            return candidate
    _discovered_endpoint, _discovered_at = None, now
    return None


_discovered_endpoint: str | None = None
_discovered_at: float = 0.0


def _endpoint_alive(endpoint: str) -> bool:
    try:
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=0.25) as response:
            json.loads(response.read().decode("utf-8"))
        return True
    except Exception:
        return False


def _list_targets(endpoint: str, timeout: float) -> list[dict]:
    try:
        with urllib.request.urlopen(f"{endpoint}/json/list", timeout=max(0.05, timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise CdpError(CDP_UNREACHABLE, f"CDP /json/list thất bại: {error}") from error
    if not isinstance(payload, list):
        raise CdpError(CDP_UNREACHABLE, "CDP /json/list trả về dữ liệu không phải danh sách.")
    return [item for item in payload if isinstance(item, dict)]


def _browser_ws_url(endpoint: str, timeout: float) -> str | None:
    try:
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=max(0.05, timeout)) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    url = str(payload.get("webSocketDebuggerUrl") or "")
    return url if url.startswith("ws://") else None


def _page_candidates(targets: list[dict]) -> tuple[list[dict], list[str]]:
    pages: list[dict] = []
    devtools_ids: list[str] = []
    for target in targets:
        url = str(target.get("url") or "")
        target_id = str(target.get("id") or target.get("targetId") or "")
        if target.get("type") == "page" and not url.startswith("devtools://"):
            if target.get("webSocketDebuggerUrl"):
                pages.append(target)
        elif url.startswith("devtools://") and target_id:
            devtools_ids.append(target_id)
    return pages, devtools_ids


def _select_target(candidates: list[dict], window_title: str) -> dict:
    """Chọn tab khớp cửa sổ: một ứng viên ⇒ dùng luôn; nhiều ⇒ khớp tiêu đề."""
    if not candidates:
        raise CdpError(NO_CDP_TARGET)
    if len(candidates) == 1:
        return candidates[0]
    wanted = (window_title or "").strip()
    if wanted:
        exact = [item for item in candidates if str(item.get("title") or "").strip() == wanted]
        if len(exact) == 1:
            return exact[0]
        partial = [item for item in candidates if wanted in str(item.get("title") or "")]
        if len(partial) == 1:
            return partial[0]
    raise CdpError(
        AMBIGUOUS_TARGET,
        candidates=[
            {
                "targetId": str(item.get("id") or "")[:64],
                "title": str(item.get("title") or "")[:120],
                "url": str(item.get("url") or "")[:300],
            }
            for item in candidates[:MAX_AMBIGUOUS_CANDIDATES]
        ],
    )


def _devtools_docked(browser_ws: WebSocket | None, page_target_id: str, devtools_ids: list[str]) -> bool:
    """Chốt chặn 1 — mọi lỗi đọc/gọi trên đường này FAIL-CLOSED thành docked."""
    if not devtools_ids:
        return False
    if browser_ws is None:
        return True
    try:
        page_window = browser_ws.call("Browser.getWindowForTarget", {"targetId": page_target_id})[
            "result"
        ]["windowId"]
    except (WebSocketError, OSError, KeyError, TypeError):
        return True
    for devtools_id in devtools_ids:
        try:
            devtools_window = browser_ws.call(
                "Browser.getWindowForTarget", {"targetId": devtools_id}
            )["result"]["windowId"]
        except (WebSocketError, OSError, KeyError, TypeError):
            return True
        if devtools_window == page_window:
            return True
    return False


# ---------------------------------------------------------------------------
# CDP — biểu thức chạy trong trang (giữ nguyên hợp đồng của bản trong box)
# ---------------------------------------------------------------------------
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

# Text/comment node → cha có phần tử (DOM.getNodeForLocation có thể trả text node).
ELEMENT_OF_FN = r"""
function() {
  var TEXT_NODE = 3, COMMENT_NODE = 8;
  if ((this.nodeType === TEXT_NODE || this.nodeType === COMMENT_NODE) && this.parentElement) {
    return this.parentElement;
  }
  return this;
}
"""

# Selector ưu tiên #id → tag.class(tối đa 4) → :nth-of-type; kiểm tra duy nhất trên
# getRootNode() (đúng cả trong shadow root), không đọc data-boxfox-src.
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


def viewport_metrics(ws: WebSocket) -> dict:
    """(1) ``Runtime.evaluate`` — kích thước viewport, dpr, gốc cửa sổ theo CSS px."""
    result = ws.call(
        "Runtime.evaluate", {"expression": VIEWPORT_EXPRESSION, "returnByValue": True}
    ).get("result", {})
    value = (result.get("result") or {}).get("value")
    if not isinstance(value, dict) or not value.get("innerWidth"):
        raise CdpError(VIEWPORT_ORIGIN_UNKNOWN, "Không đọc được số đo viewport từ trang.")
    return value


def content_origin(window_geom: dict, metrics: dict) -> tuple[float, float]:
    """Gốc (trên-trái) của viewport trong toạ độ màn hình **vật lý**.

    Trên Windows, ``window.screenX/screenY`` là toạ độ CSS của viewport so với màn
    hình (có thể âm khi màn hình phụ nằm bên trái) ⇒ nhân ``dpr`` là ra physical.
    Thiếu số đo thì lùi về giả định của bản trong box (sát đáy, căn giữa ngang).
    """
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    screen_x = metrics.get("screenX")
    screen_y = metrics.get("screenY")
    if isinstance(screen_x, (int, float)) and isinstance(screen_y, (int, float)):
        return float(screen_x) * dpr, float(screen_y) * dpr
    return (
        window_geom["x"] + (window_geom["w"] - metrics["innerWidth"] * dpr) / 2.0,
        window_geom["y"] + window_geom["h"] - metrics["innerHeight"] * dpr,
    )


def screen_to_css(screen_x: float, screen_y: float, window_geom: dict, metrics: dict) -> tuple[float, float]:
    origin_x, origin_y = content_origin(window_geom, metrics)
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    return (screen_x - origin_x) / dpr, (screen_y - origin_y) / dpr


def point_in_viewport(css_x: float, css_y: float, metrics: dict) -> bool:
    return 0 <= css_x < metrics["innerWidth"] and 0 <= css_y < metrics["innerHeight"]


def quad_to_css_box(quad: list[float]) -> dict:
    xs = quad[0::2]
    ys = quad[1::2]
    return {"x": min(xs), "y": min(ys), "width": max(xs) - min(xs), "height": max(ys) - min(ys)}


def css_box_to_screen_box(css_box: dict, origin_x: float, origin_y: float, dpr: float) -> dict:
    return {
        "x": round(origin_x + css_box["x"] * dpr),
        "y": round(origin_y + css_box["y"] * dpr),
        "width": round(css_box["width"] * dpr),
        "height": round(css_box["height"] * dpr),
    }


def _viewport_origin_plausible(window_geom: dict, metrics: dict) -> bool:
    """Chốt chặn 2: side panel / theme lạ vượt ngưỡng ⇒ không suy gốc viewport."""
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    slack_x = window_geom["w"] - metrics["innerWidth"] * dpr
    slack_y = window_geom["h"] - metrics["innerHeight"] * dpr
    return 0 <= slack_y <= MAX_CHROME_HEIGHT_PX and 0 <= slack_x <= MAX_SIDE_SLACK_PX


def extract_at(ws: WebSocket, point: dict, window_geom: dict, selected: dict) -> dict:
    """Chuỗi CDP trên MỘT kết nối cấp page — thứ tự lệnh là hợp đồng có test khoá."""
    metrics = viewport_metrics(ws)  # (1)
    if not _viewport_origin_plausible(window_geom, metrics):
        raise CdpError(VIEWPORT_ORIGIN_UNKNOWN)
    dpr = float(metrics.get("dpr") or 1.0) or 1.0
    origin_x, origin_y = content_origin(window_geom, metrics)
    css_x, css_y = screen_to_css(float(point["x"]), float(point["y"]), window_geom, metrics)
    if not point_in_viewport(css_x, css_y, metrics):
        raise CdpError(OUTSIDE_VIEWPORT)

    frame_id = ""
    try:
        ws.call("DOM.enable", {})  # (2)
        root = ws.call("DOM.getDocument", {"depth": 0}).get("result", {}).get("root") or {}  # (3)
        frame_id = str(root.get("frameId") or "")

        location = ws.call(  # (4)
            "DOM.getNodeForLocation",
            {"x": round(css_x), "y": round(css_y), "includeUserAgentShadowDOM": False},
        ).get("result", {})
        backend_node_id = location.get("backendNodeId")
        if not backend_node_id:
            raise CdpError(NO_NODE_AT_POINT)

        resolved = ws.call("DOM.resolveNode", {"backendNodeId": backend_node_id}).get("result", {})  # (5)
        object_id = (resolved.get("object") or {}).get("objectId")
        if not object_id:
            raise CdpError(NO_NODE_AT_POINT)

        promoted = (  # (6)
            ws.call(
                "Runtime.callFunctionOn",
                {"objectId": object_id, "functionDeclaration": ELEMENT_OF_FN, "returnByValue": False},
            )
            .get("result", {})
            .get("result", {})
        )
        element_object_id = promoted.get("objectId") or object_id

        extracted = (  # (7)
            ws.call(
                "Runtime.callFunctionOn",
                {
                    "objectId": element_object_id,
                    "functionDeclaration": EXTRACT_FN,
                    "arguments": [
                        {"value": MAX_TEXT_BYTES},
                        {"value": MAX_ATTRS},
                        {"value": MAX_ATTR_VALUE_BYTES},
                    ],
                    "returnByValue": True,
                },
            )
            .get("result", {})
            .get("result", {})
        )
        data = extracted.get("value")
        if not isinstance(data, dict) or data.get("error"):
            raise CdpError(EXTRACT_FAILED)

        html = (  # (8)
            ws.call("DOM.getOuterHTML", {"objectId": element_object_id}).get("result", {}).get("outerHTML", "")
        )
    except (WebSocketError, KeyError, TypeError) as error:
        raise CdpError(EXTRACT_FAILED, f"Chuỗi CDP thất bại: {error}") from error

    css_box = None
    screen_box = None
    try:
        model = (  # (9)
            ws.call("DOM.getBoxModel", {"objectId": element_object_id}).get("result", {}).get("model")
        )
        if model and model.get("content"):
            css_box = quad_to_css_box(model["content"])
            screen_box = css_box_to_screen_box(css_box, origin_x, origin_y, dpr)
    except (WebSocketError, KeyError, TypeError):
        pass  # thiếu box model vẫn OK: cssBox/screenBox = None

    return {
        "targetId": str(selected.get("id") or selected.get("targetId") or ""),
        "frameId": frame_id,
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
        "viewport": {
            "originX": origin_x,
            "originY": origin_y,
            "dpr": dpr,
            "innerWidth": metrics.get("innerWidth"),
            "innerHeight": metrics.get("innerHeight"),
        },
    }


def default_cdp_inspector(request: dict) -> dict:
    """Nhánh ``dom`` trong host mode: dò endpoint loopback rồi chạy :func:`extract_at`.

    ``request`` = ``{"point": {"x","y"}, "window": {x,y,w,h,title}, "timeout": float}``.
    Ném :class:`CdpError` với mã ``reason`` của tầng soi.
    """
    point = request["point"]
    window_geom = request["window"]
    timeout = float(request.get("timeout") or CDP_CALL_TIMEOUT_SEC)
    endpoint = str(request.get("endpoint") or cdp_endpoint() or "")
    if not endpoint:
        raise CdpError(NO_CDP_TARGET, "Không tìm thấy endpoint CDP loopback nào.")
    targets = _list_targets(endpoint, timeout)
    pages, devtools_ids = _page_candidates(targets)
    selected = _select_target(pages, window_geom.get("title") or "")
    browser_ws: WebSocket | None = None
    try:
        if len(pages) > 1 or devtools_ids:
            browser_url = _browser_ws_url(endpoint, timeout)
            if not browser_url:
                raise CdpError(CDP_UNREACHABLE)
            browser_ws = WebSocket(browser_url, timeout=timeout)
            browser_ws.connect()
        if _devtools_docked(browser_ws, str(selected.get("id") or ""), devtools_ids):
            raise CdpError(DEVTOOLS_DOCKED)
    finally:
        if browser_ws is not None:
            browser_ws.close()
    page_url = str(selected.get("webSocketDebuggerUrl") or "")
    if not page_url:
        raise CdpError(NO_CDP_TARGET)
    ws = WebSocket(page_url, timeout=timeout)
    try:
        ws.connect()
        return extract_at(ws, point, window_geom, selected)
    except TimeoutError as error:
        raise CdpError(CDP_TIMEOUT, f"Hết thời gian chờ CDP: {error}") from error
    except (WebSocketError, OSError) as error:
        raise CdpError(CDP_UNREACHABLE, f"Không nói chuyện được với CDP: {error}") from error
    finally:
        ws.close()


_cdp_inspector: Callable[[dict], dict] | None = None


def set_cdp_inspector(inspector: Callable[[dict], dict] | None) -> None:
    """Tiêm bộ soi CDP (test, hoặc bản khác dùng DevToolsActivePort)."""
    global _cdp_inspector
    _cdp_inspector = inspector


def get_cdp_inspector() -> Callable[[dict], dict]:
    return _cdp_inspector or default_cdp_inspector


# ---------------------------------------------------------------------------
# Danh tính cửa sổ + phân nhánh
# ---------------------------------------------------------------------------
def _is_chromium(window: Any) -> bool:
    window_class = str(getattr(window, "class_name", "") or "").lower()
    if any(hint in window_class for hint in CHROMIUM_CLASS_HINTS):
        return True
    process_name = str(getattr(window, "process_name", "") or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return process_name in CHROMIUM_PROCESS_NAMES


def window_at_point(
    x: int, y: int, *, platform: Any = None
) -> tuple[Any, str | None]:
    """(cửa sổ, lý do thất bại) — ``(None, reason)`` khi không có cửa sổ/danh tính."""
    modules = _win()
    p = platform or modules.platform.get_platform()
    hwnd = p.window_from_point(int(x), int(y))
    if not hwnd:
        return None, NO_WINDOW_AT_POINT
    root = p.get_ancestor_root(hwnd) or hwnd
    try:
        return p.describe_window(root), None
    except PlatformError:
        return None, WINDOW_IDENTITY_UNAVAILABLE_REASON
    except Exception:
        return None, WINDOW_IDENTITY_UNAVAILABLE_REASON


def _uia_reason(error: PlatformError) -> str:
    code = getattr(error, "code", "")
    if code in INSPECT_REASONS:
        return code
    return _UIA_REASON_BY_CODE.get(code, UIA_UNAVAILABLE_REASON)


def _pick_reason(dom_reason: str | None, uia_reason: str | None) -> str:
    """Lý do hiển thị khi cả hai nhánh đều thất bại (mã cụ thể thắng)."""
    if dom_reason and dom_reason != NOT_CHROMIUM:
        return dom_reason
    if uia_reason:
        return uia_reason
    return dom_reason or EXTRACT_FAILED


def _finalize(payload: dict, window_id: str) -> dict:
    """Bước 2 và 3 của ``content_hash``: băm payload **chưa** có label rồi gắn label."""
    payload["label"] = _label(window_id, _canonical_payload_hash(payload))
    return payload


def _desktop_response(
    window: Any,
    reason: str = "",
    message: str = "",
    *,
    x: int = 0,
    y: int = 0,
    tabs: Any = None,
    revision: int | None = None,
) -> dict:
    """Nhánh 3 — thoái hoá mềm. ``not_chromium`` bỏ hẳn ``reason``/``message``."""
    window_id = _window_id(window)
    source_id = _source_id(window)
    if revision is None:
        revision = geometry_revision(source_id, window_geometry_fingerprint(window, None))
    payload: dict = {"type": "desktop"}
    if reason and reason != NOT_CHROMIUM:
        payload["reason"] = reason
        payload["message"] = message or INSPECT_MESSAGES.get(reason, INSPECT_MESSAGES[EXTRACT_FAILED])
    app_name = _app_name(str(getattr(window, "class_name", "") or ""))
    if app_name:
        payload["appName"] = app_name
    payload["windowClass"] = str(getattr(window, "class_name", "") or "")
    payload["windowTitle"] = str(getattr(window, "title", "") or "")
    payload["windowId"] = window_id
    if window is None:
        payload["position"] = {"x": int(x), "y": int(y)}
        payload["size"] = {"width": 0, "height": 0}
    else:
        rect = _window_rect(window)
        payload["position"] = {"x": rect["x"], "y": rect["y"]}
        payload["size"] = {"width": rect["w"], "height": rect["h"]}
    pid = getattr(window, "pid", None)
    if pid is not None:
        payload["pid"] = int(pid)
    payload["sourceId"] = source_id
    payload["frameId"] = source_id
    payload["geometryRevision"] = int(revision)
    safe_tabs = _safe_tab_list(tabs)
    if safe_tabs:
        payload["tabs"] = safe_tabs
    return _finalize(payload, window_id)


def _uia_response(window: Any, node: Any, *, dpi: int | None, revision: int) -> dict:
    """Nhánh 2 — phần tử UI Automation."""
    modules = _win()
    body = modules.uia.node_payload(node)
    bounds = dict(body.pop("bounds", {}) or {})
    payload: dict = {"type": "uia", "name": body.get("name", ""), "controlType": node.role}
    control_type_id = body.get("controlTypeId")
    if control_type_id is not None:
        payload["controlTypeId"] = int(control_type_id)
    payload["automationId"] = body.get("automationId", "")
    payload["className"] = body.get("className", "")
    payload["helpText"] = body.get("helpText", "")
    payload["isEnabled"] = bool(body.get("isEnabled"))
    payload["isOffscreen"] = bool(body.get("isOffscreen"))
    payload["isPassword"] = bool(body.get("isPassword"))
    screen_box = {
        "x": int(bounds.get("x", 0)),
        "y": int(bounds.get("y", 0)),
        "width": int(bounds.get("width", 0)),
        "height": int(bounds.get("height", 0)),
    }
    payload["bounds"] = {"screenBox": screen_box}
    if dpi is not None:
        payload["bounds"]["dpi"] = int(dpi)
    payload["patterns"] = list(body.get("patterns") or [])
    payload["windowId"] = _window_id(window)
    pid = body.get("pid")
    if pid is None:
        pid = getattr(window, "pid", None)
    if pid is not None:
        payload["pid"] = int(pid)
    process_name = getattr(window, "process_name", None)
    if process_name:
        payload["processName"] = str(process_name)
    payload["elementToken"] = node.token
    payload["generation"] = int(node.generation)
    payload["sourceId"] = _source_id(window)
    payload["frameId"] = _source_id(window)
    payload["geometryRevision"] = int(revision)
    return _finalize(payload, _window_id(window))


def _dom_response(window: Any, child: dict, *, revision: int) -> dict:
    """Nhánh 1 — giữ nguyên bộ trường của bản trong box."""
    html, html_truncated = _truncate_text(child.get("html") or "", MAX_HTML_BYTES)
    text, text_truncated = _truncate_text(child.get("text") or "", MAX_TEXT_BYTES)
    attributes, attrs_truncated = _truncate_attributes(child.get("attributes") or {})
    truncated = bool(
        html_truncated or text_truncated or attrs_truncated or child.get("truncatedInPage")
    )
    target = _public_inspect_target(window, child.get("targetId", ""))
    source_id = _source_id(window)
    frame_id = str(child.get("frameId") or source_id)
    payload = {
        "type": "dom",
        "selector": child.get("selector"),
        "url": child.get("url", ""),
        "title": child.get("title", ""),
        "tagName": child.get("tagName", ""),
        "text": text,
        "attributes": attributes,
        "html": html,
        "truncated": truncated,
        "cssBox": child.get("cssBox"),
        "screenBox": child.get("screenBox"),
        "notes": child.get("notes") or [],
        "shadowHostSelector": child.get("shadowHostSelector"),
        "target": target,
        "sourceId": source_id,
        "frameId": frame_id,
        "geometryRevision": int(revision),
    }
    return _finalize(payload, _window_id(window))


def _dom_layout(child: dict) -> tuple:
    """Vân tay layout trang (chỉ nhánh DOM biết): gốc khung nhìn, dpr, kích thước."""
    viewport = child.get("viewport") or {}
    return (
        viewport.get("originX"),
        viewport.get("originY"),
        viewport.get("dpr"),
        viewport.get("innerWidth"),
        viewport.get("innerHeight"),
    )


# ---------------------------------------------------------------------------
# Điểm vào
# ---------------------------------------------------------------------------
def _validate_point(x: Any, y: Any, platform: Any) -> tuple[int, int]:
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
        raise ValueError("x/y phải là số nguyên (toạ độ màn hình vật lý).")
    origin_x, origin_y, width, height = platform.virtual_screen_bounds()
    if not (origin_x <= x < origin_x + width) or not (origin_y <= y < origin_y + height):
        raise ValueError(
            f"Toạ độ ngoài màn hình (desktop ảo {width}x{height} tại {origin_x},{origin_y})."
        )
    return int(x), int(y)


def inspect_element(
    x: int,
    y: int,
    *,
    platform: Any = None,
    cdp: Callable[[dict], dict] | None = None,
    session: Any = None,
) -> dict:
    """Soi phần tử tại ``(x, y)`` theo thứ tự ``dom`` → ``uia`` → ``desktop``.

    Trả về payload có cấu trúc (không bao giờ ném lỗi vì lý do nghiệp vụ: mọi
    thất bại đều thành nhánh ``desktop`` kèm ``reason``). Chỉ ném ``ValueError``
    khi toạ độ sai kiểu/ngoài màn hình, và ``PlatformError(CONTROL_BUSY)`` khi đã
    có 2 yêu cầu soi đang chạy.
    """
    modules = _win()
    p = platform or modules.platform.get_platform()
    x, y = _validate_point(x, y, p)
    if not _INSPECT_SEMAPHORE.acquire(blocking=False):
        raise PlatformError(
            CONTROL_BUSY,
            f"Đã đạt {MAX_CONCURRENT_INSPECTS} yêu cầu soi đồng thời — thử lại sau.",
            limit=MAX_CONCURRENT_INSPECTS,
        )
    try:
        return _dispatch_inspect(x, y, p, cdp, session)
    finally:
        _INSPECT_SEMAPHORE.release()


def _dispatch_inspect(
    x: int, y: int, platform: Any, cdp: Callable[[dict], dict] | None, session: Any
) -> dict:
    modules = _win()
    window, identity_failure = window_at_point(x, y, platform=platform)
    if window is None:
        return _desktop_response(None, identity_failure or NO_WINDOW_AT_POINT, x=x, y=y)

    dpi = None
    try:
        dpi = platform.get_dpi_for_window(window.hwnd)
    except Exception:
        dpi = None
    window_fingerprint = window_geometry_fingerprint(window, dpi)
    source_id = _source_id(window)

    dom_reason: str | None = None
    if _is_chromium(window):
        if getattr(window, "extended_bounds", None) is None:
            # Không biết viền thật của khung ⇒ không thể loại vùng trang trí: fail-closed.
            return _desktop_response(
                window,
                FRAME_EXTENTS_UNKNOWN,
                revision=geometry_revision(source_id, window_fingerprint),
            )
        inspector = cdp or get_cdp_inspector()
        request = {
            "point": {"x": x, "y": y},
            "window": {**_window_rect(window), "title": str(getattr(window, "title", "") or "")},
            "timeout": CDP_CALL_TIMEOUT_SEC,
        }
        try:
            child = inspector(request)
        except CdpError as error:
            dom_reason = error.reason if error.reason in INSPECT_REASONS else EXTRACT_FAILED
            dom_failure_tabs = error.details.get("candidates")
        except Exception:
            dom_reason = EXTRACT_FAILED
            dom_failure_tabs = None
        else:
            revision = geometry_revision(source_id, window_fingerprint, _dom_layout(child))
            return _dom_response(window, child, revision=revision)
    else:
        dom_reason = NOT_CHROMIUM
        dom_failure_tabs = None

    uia_reason: str | None = None
    try:
        node = modules.uia.element_at_point(
            x, y, window=window, platform=platform, session=session
        )
    except PlatformError as error:
        uia_reason = _uia_reason(error)
    except Exception:
        uia_reason = UIA_UNAVAILABLE_REASON
    else:
        revision = geometry_revision(source_id, window_fingerprint)
        return _uia_response(window, node, dpi=dpi, revision=revision)

    reason = _pick_reason(dom_reason, uia_reason)
    return _desktop_response(
        window,
        reason,
        tabs=dom_failure_tabs,
        revision=geometry_revision(source_id, window_fingerprint),
    )


def prepare(platform: Any = None) -> dict:
    """Chuẩn bị host mode một lần lúc khởi động: DPI + apartment UIA.

    Gọi trước khi tạo cửa sổ nào. Cả hai bước đều best-effort — lỗi ở đây không
    được làm chết tiến trình, chỉ ghi lại trạng thái.
    """
    modules = _win()
    p = platform or modules.platform.get_platform()
    state: dict[str, Any] = {}
    try:
        state["dpiAwareness"] = modules.capture.set_dpi_awareness(p)
    except Exception as error:
        state["dpiAwareness"] = "error"
        state["dpiError"] = repr(error)
    try:
        state["uiaApartment"] = modules.uia.get_session(p).initialize()
    except PlatformError as error:
        state["uiaApartment"] = "unavailable"
        state["uiaCode"] = error.code
    except Exception as error:
        state["uiaApartment"] = "error"
        state["uiaError"] = repr(error)
    return state
