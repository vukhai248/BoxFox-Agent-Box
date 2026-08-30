#!/usr/bin/env python3
"""Thanh tra phần tử (element inspector) — `/__box/inspect-element`.

Điểm vào duy nhất: `dispatch_inspect_element(x, y)`. Toạ độ `(x, y)` là toạ độ
FRAMEBUFFER X11 (không phải CSS viewport).

Ba tầng của tính năng này (element-selector §7):
    ide-proxy.py (route mỏng) → inspect_element.py (module này, orchestration)
    → capture.py (primitive X11) + browser_capture.py (subprocess CDP, cách ly
    crash + hạ quyền qua `gosu agent`).

Hai nhánh phản hồi, CẢ HAI đều HTTP 200 (§5.1):
- `type == "dom"`   — bấm trúng nội dung web Chromium, trích được phần tử.
- `type == "desktop"` — mọi trường hợp suy biến (không phải Chromium, ngoài
  vùng nội dung web, CDP không khả dụng, …) kèm `reason` (11 mã, §5.2) để
  drawer vẫn hiển thị được thông tin cửa sổ.

Chỉ 4 mã HTTP là lỗi thật: 400 (toạ độ sai), 404 (không có cửa sổ nào tại
điểm bấm), 429 (vượt số request `inspect-element` đồng thời), 500/504 (lỗi
nội bộ / hết ngân sách toàn cục). CDP thất bại KHÔNG BAO GIỜ thành 500 — luôn
suy biến mềm thành nhánh `desktop` (§5.2).

Bảo mật (§10.1): `webSocketDebuggerUrl` là handle điều khiển toàn quyền
Chromium — KHÔNG BAO GIỜ được xuất hiện trong response hay bị log ra stderr.
Khối `target` CHỈ được dựng qua `capture._public_inspect_target()` (chokepoint
allow-list duy nhất) — cấm mọi kiểu `{**tab}` / `dict(tab)` / `"target": tab`.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

try:
    import capture
except ImportError:  # chạy như package con (test import tương đối)
    from . import capture


# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------
MAX_HTML_BYTES = 8 * 1024
MAX_TEXT_BYTES = 2 * 1024
MAX_ATTRS = 32
MAX_ATTR_VALUE_BYTES = 512

CDP_CALL_TIMEOUT_SEC = 5.0
REQUEST_BUDGET_SEC = 8.0
# Trần trên an toàn cho subprocess — CHỈ là lưới chặn lỗi tính toán, KHÔNG BAO
# GIỜ được dùng làm timeout thật: `_sub_timeout()` luôn lấy phần còn lại của
# `REQUEST_BUDGET_SEC` (8 s), nhỏ hơn hằng này, nên hằng này không bao giờ
# thực sự kích hoạt trong luồng bình thường (element-selector §7-B3).
SUBPROCESS_TIMEOUT_SEC = 10.0
MAX_CONCURRENT_INSPECTS = 2

CHROMIUM_WM_CLASS_HINTS = ("chromium", "chrome")

INTEGRITY_UNTRUSTED = "khong_tin_duoc"
CONFIDENTIALITY_INTERNAL = "noi_bo"
SOURCE_KIND_SCREEN = "screen_capture"
TOOL_NAME = "inspect_element"

# Khi không đọc được `_NET_FRAME_EXTENTS` (lỗi đọc, KHÔNG phải vắng mặt hợp
# lệ) — dải nghi vấn quanh clientGeom để dò trang trí một cách fail-closed.
MAX_DECORATION_TOP_PX = 64
MAX_DECORATION_SIDE_PX = 16

# 10/11 mã `reason` — `not_chromium` CỐ Ý không có ở đây vì nhánh desktop
# tương ứng bỏ hẳn khoá `reason`/`message` (không có gì thất bại cả, §5.1).
MSG: dict[str, str] = {
    "outside_viewport": (
        "Thanh tra phần tử Chrome thất bại: điểm bấm nằm ngoài vùng nội dung web "
        "(titlebar/tab/toolbar/scrollbar)."
    ),
    "frame_extents_unknown": (
        "Không đọc được viền trang trí cửa sổ (_NET_FRAME_EXTENTS) nên không thể "
        "xác định điểm bấm có rơi vào trang trí hay không."
    ),
    "devtools_docked": (
        "DevTools đang được ghim (docked) trong chính cửa sổ này — đóng hoặc tách "
        "DevTools rồi thử lại."
    ),
    "viewport_origin_unknown": (
        "Không suy được gốc vùng nội dung web (side panel hoặc giao diện Chromium "
        "bất thường)."
    ),
    "no_cdp_target": "Không tìm được tab Chrome (CDP) khớp với cửa sổ này.",
    "ambiguous_target": (
        "Có nhiều tab khớp cửa sổ này, không xác định được chính xác tab nào."
    ),
    "cdp_unreachable": (
        "Không kết nối được Chrome DevTools Protocol (Chromium desktop có thể đã "
        "tắt hoặc đang khởi động lại)."
    ),
    "cdp_timeout": "Vượt thời gian chờ khi lấy dữ liệu phần tử qua Chrome DevTools Protocol.",
    "no_node_at_point": "Không tìm thấy phần tử DOM nào tại điểm bấm này.",
    "extract_failed": "Trích xuất dữ liệu phần tử thất bại.",
}


# ---------------------------------------------------------------------------
# Ngân sách thời gian — một trần duy nhất (8 s), lan xuống mọi helper X11/CDP
# ---------------------------------------------------------------------------
def _deadline() -> float:
    return time.monotonic() + REQUEST_BUDGET_SEC


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _clamped_timeout(deadline: float, cap: float) -> float:
    return max(0.05, min(cap, _remaining(deadline)))


def _sub_timeout(deadline: float) -> float:
    return max(0.05, min(SUBPROCESS_TIMEOUT_SEC, _remaining(deadline)))


# ---------------------------------------------------------------------------
# Hit-test — tìm cửa sổ X11 tại điểm bấm, phân biệt frame/client (§7-B1)
# ---------------------------------------------------------------------------
def _normalize_win_id(raw) -> int | None:
    # Cạm bẫy P1: `_NET_CLIENT_LIST_STACKING` in id có zero-padding khác
    # `wmctrl -lx` — PHẢI chuẩn hoá bằng int(id, 16) ở cả hai phía.
    try:
        return int(str(raw), 16)
    except (TypeError, ValueError):
        return None


def _contains(geom: dict, x: int, y: int) -> bool:
    # Hình chữ nhật nửa mở: [x, x+w) x [y, y+h).
    return geom["x"] <= x < geom["x"] + geom["w"] and geom["y"] <= y < geom["y"] + geom["h"]


def _expand_by_extents(client_geom: dict, ext: dict) -> dict:
    return {
        "x": client_geom["x"] - ext["left"],
        "y": client_geom["y"] - ext["top"],
        "w": client_geom["w"] + ext["left"] + ext["right"],
        "h": client_geom["h"] + ext["top"] + ext["bottom"],
    }


def _probe_zone(client_geom: dict) -> dict:
    # Dùng khi `frame_extents()` trả None (lỗi đọc) — dải nghi vấn fail-closed
    # thay cho hình học trang trí thật (top rộng hơn vì titlebar, các cạnh
    # khác chỉ cần đủ cho viền cửa sổ mỏng).
    return {
        "x": client_geom["x"] - MAX_DECORATION_SIDE_PX,
        "y": client_geom["y"] - MAX_DECORATION_TOP_PX,
        "w": client_geom["w"] + 2 * MAX_DECORATION_SIDE_PX,
        "h": client_geom["h"] + MAX_DECORATION_TOP_PX + MAX_DECORATION_SIDE_PX,
    }


def window_at_point(x: int, y: int, deadline: float) -> dict:
    """Tìm cửa sổ X11 tại `(x, y)`, KHÔNG di chuột/raise/warp con trỏ.

    Trả về dict `win` (các khoá của `wmctrl -lx` + hình học client + `pid` +
    khoá riêng `_hitZone` ∈ {"client", "decoration", "frame_extents_unknown"}
    — `dispatch_inspect_element` đọc rồi bỏ khoá này trước khi trả ra ngoài).

    KHÔNG có fallback "đoán cửa sổ trên cùng": `wmctrl -lx` không mang thứ tự
    stacking, nên khi `_NET_CLIENT_LIST_STACKING` thiếu/không đọc được thì
    404 ngay (§7-B1) — không dò từng cửa sổ theo thứ tự liệt kê của wmctrl.
    """
    stacking = capture.client_list_stacking(timeout=_clamped_timeout(deadline, 10))
    if not stacking:
        raise capture._not_found(
            "Không đọc được thứ tự chồng cửa sổ (_NET_CLIENT_LIST_STACKING) — "
            "không thể xác định cửa sổ tại điểm bấm."
        )

    wmctrl_output = capture._wmctrl_list(timeout=_clamped_timeout(deadline, 15))
    by_id: dict[int, dict] = {}
    for line in wmctrl_output.splitlines():
        parsed = capture._parse_wmctrl_line(line)
        if not parsed:
            continue
        normalized = _normalize_win_id(parsed["id"])
        if normalized is None:
            continue
        by_id[normalized] = parsed

    for raw_id in reversed(stacking):  # trên→dưới: stacking là dưới→trên
        win = by_id.get(raw_id)
        if win is None:
            continue

        if _remaining(deadline) <= 0:
            raise capture.CaptureError(
                "Hết ngân sách thời gian khi dò cửa sổ tại điểm bấm.", status_code=504
            )

        probe = capture._wininfo_probe(win["id"], timeout=_clamped_timeout(deadline, 5))
        if probe is None or probe.get("mapState") != "IsViewable":
            continue

        props = capture._xprop_many(
            win["id"], ["_NET_WM_STATE", "_NET_WM_PID"], timeout=_clamped_timeout(deadline, 5)
        )
        state = capture._parse_state(props.get("_NET_WM_STATE"))
        if not capture._is_hittable(state):
            continue

        client_geom = {"x": probe["x"], "y": probe["y"], "w": probe["w"], "h": probe["h"]}
        pid = capture._parse_pid(props.get("_NET_WM_PID"))

        if _contains(client_geom, x, y):
            hit_zone = "client"
        else:
            ext = capture.frame_extents(win["id"], timeout=_clamped_timeout(deadline, 5))
            if ext is not None:
                frame_geom = _expand_by_extents(client_geom, ext)
                if not _contains(frame_geom, x, y):
                    continue  # ngoài cả frame -> thử cửa sổ dưới
                hit_zone = "decoration"
            else:
                # Lỗi đọc _NET_FRAME_EXTENTS — KHÔNG coi như {0,0,0,0}.
                if not _contains(_probe_zone(client_geom), x, y):
                    continue  # quá xa để là trang trí -> an toàn khi thử tiếp
                # Trong dải nghi vấn -> DỪNG quét ngay, fail-closed cho CHÍNH
                # cửa sổ này. KHÔNG rơi xuống cửa sổ dưới.
                hit_zone = "frame_extents_unknown"

        result = dict(win)
        result.update(client_geom)
        result["pid"] = pid
        result["_hitZone"] = hit_zone
        return result

    raise capture._not_found("Không có cửa sổ nào tại điểm bấm này.")


def _is_chromium(win: dict) -> bool:
    win_class = (win.get("class") or "").lower()
    return any(hint in win_class for hint in CHROMIUM_WM_CLASS_HINTS)


def _app_name(win_class: str) -> str:
    win_class = win_class or ""
    if "." in win_class:
        return win_class.rsplit(".", 1)[-1]
    return win_class


# ---------------------------------------------------------------------------
# CDP — danh sách target thô (KHÔNG lọc type=="page" như list_tabs(), để còn
# thấy cả target devtools:// dùng cho phát hiện DevTools docked)
# ---------------------------------------------------------------------------
def _cdp_candidates(deadline: float) -> tuple[str | None, list[dict], list[str]]:
    browser_ws_url = capture.browser_debugger_url(timeout=_clamped_timeout(deadline, 10))
    try:
        with urllib.request.urlopen(
            f"{capture.CDP_ENDPOINT}/json/list", timeout=_clamped_timeout(deadline, 10)
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise capture.CaptureError(f"CDP /json/list thất bại: {error}", status_code=502)

    page_candidates: list[dict] = []
    devtools_ids: list[str] = []
    for target in payload:
        url = target.get("url") or ""
        if target.get("type") == "page":
            page_candidates.append({
                "targetId": str(target.get("id") or ""),
                "title": target.get("title") or "",
                "url": url,
                "webSocketDebuggerUrl": target.get("webSocketDebuggerUrl") or "",
            })
        elif url.startswith("devtools://"):
            devtools_ids.append(str(target.get("id") or ""))
    return browser_ws_url, page_candidates, devtools_ids


def _run_inspect_subprocess(request: dict, timeout: float) -> dict:
    """Spawn `browser_capture.py inspect_point`, gửi request qua STDIN — KHÔNG
    BAO GIỜ qua argv (`webSocketDebuggerUrl` sẽ hiện trong `ps`/`/proc/*/cmdline`).
    """
    proc = capture._popen_as_agent(
        [sys.executable, str(capture.BROWSER_CAPTURE_BIN), "inspect_point"]
    )
    try:
        stdout, stderr = proc.communicate(input=json.dumps(request), timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise
    if proc.returncode != 0:
        raise subprocess.SubprocessError((stderr or stdout or "").strip()[:300])
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"browser_capture trả stdout không phải JSON hợp lệ: {error}")


# ---------------------------------------------------------------------------
# Cắt bớt dữ liệu trước khi trả ra ngoài
# ---------------------------------------------------------------------------
def _truncate_text(value: str, limit_bytes: int) -> tuple[str, bool]:
    value = value or ""
    encoded = value.encode("utf-8")
    if len(encoded) <= limit_bytes:
        return value, False
    truncated = encoded[:limit_bytes].decode("utf-8", errors="ignore")
    return truncated, True


def _truncate_attributes(attrs) -> tuple[dict, bool]:
    if not isinstance(attrs, dict):
        return {}, False
    truncated_flag = False
    result: dict[str, str] = {}
    for index, (key, value) in enumerate(attrs.items()):
        if index >= MAX_ATTRS:
            truncated_flag = True
            break
        text_value, was_truncated = _truncate_text(str(value), MAX_ATTR_VALUE_BYTES)
        if was_truncated:
            truncated_flag = True
        result[str(key)] = text_value
    return result, truncated_flag


# ---------------------------------------------------------------------------
# Khối `label` — dữ liệu KHÔNG TIN ĐƯỢC, trên CẢ HAI nhánh (§5.4)
# ---------------------------------------------------------------------------
def _canonical_payload_hash(payload: dict) -> str:
    # Hash trên payload NGỮ NGHĨA, CHƯA có khoá `label` — tránh tự tham chiếu.
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _label(window_id: str, content_hash: str) -> dict:
    return {
        "integrity": INTEGRITY_UNTRUSTED,
        "confidentiality": CONFIDENTIALITY_INTERNAL,
        "source_kind": SOURCE_KIND_SCREEN,
        # KHÔNG nhúng selector — selector do trang kiểm soát (§5.4).
        "source_uri": f"screen://element/{window_id}",
        "tool_name": TOOL_NAME,
        "content_hash": content_hash,
    }


def _desktop_response(win: dict, reason: str = "", message: str = "") -> dict:
    payload: dict = {"type": "desktop"}
    if reason and reason != "not_chromium":
        payload["reason"] = reason
        payload["message"] = message or MSG.get(reason, MSG["extract_failed"])

    app_name = _app_name(win.get("class") or "")
    if app_name:
        payload["appName"] = app_name
    payload["windowClass"] = win.get("class") or ""
    payload["windowTitle"] = win.get("title") or ""
    payload["windowId"] = str(win.get("id") or "")
    payload["position"] = {"x": win.get("x", 0), "y": win.get("y", 0)}
    payload["size"] = {"width": win.get("w", 0), "height": win.get("h", 0)}
    pid = win.get("pid")
    if pid is not None:
        payload["pid"] = pid

    content_hash = _canonical_payload_hash(payload)
    payload["label"] = _label(str(win.get("id") or ""), content_hash)
    return payload


def _dom_response(win: dict, child: dict) -> dict:
    html, html_truncated = _truncate_text(child.get("html") or "", MAX_HTML_BYTES)
    text, text_truncated = _truncate_text(child.get("text") or "", MAX_TEXT_BYTES)
    attributes, attrs_truncated = _truncate_attributes(child.get("attributes") or {})
    truncated = bool(html_truncated or text_truncated or attrs_truncated or child.get("truncatedInPage"))

    # Chokepoint DUY NHẤT cho `target` — KHÔNG dựng bằng cách khác (§10.1).
    target = capture._public_inspect_target(win, {"targetId": child.get("targetId", "")})

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
    }
    content_hash = _canonical_payload_hash(payload)
    payload["label"] = _label(str(win.get("id") or ""), content_hash)
    return payload


# ---------------------------------------------------------------------------
# Validate đầu vào
# ---------------------------------------------------------------------------
def _validate_point(x, y) -> tuple[int, int]:
    # bool là subclass của int trong Python -> phải loại trước isinstance(int).
    if isinstance(x, bool) or isinstance(y, bool) or not isinstance(x, int) or not isinstance(y, int):
        raise capture._invalid("x/y phải là số nguyên (toạ độ framebuffer X11).")
    width, height = capture.screen_size()
    if not (0 <= x < width) or not (0 <= y < height):
        raise capture._invalid(f"Toạ độ ngoài màn hình (kích thước hiện tại {width}x{height}).")
    return x, y


# ---------------------------------------------------------------------------
# Đồng bộ hoá — giới hạn 2 request inspect-element đồng thời (§7-B1 bước 3)
# ---------------------------------------------------------------------------
_INSPECT_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT_INSPECTS)


def _dispatch_inspect_element_locked(x, y) -> dict:
    deadline = _deadline()
    x, y = _validate_point(x, y)
    win = window_at_point(x, y, deadline)
    hit_zone = win.pop("_hitZone", "client")

    if hit_zone == "frame_extents_unknown":
        return _desktop_response(win, "frame_extents_unknown", MSG["frame_extents_unknown"])
    if not _is_chromium(win):
        return _desktop_response(win, "not_chromium")
    if hit_zone == "decoration":
        return _desktop_response(win, "outside_viewport", MSG["outside_viewport"])

    if _remaining(deadline) <= 0:
        return _desktop_response(win, "cdp_timeout", MSG["cdp_timeout"])

    try:
        browser_ws_url, page_candidates, devtools_ids = _cdp_candidates(deadline)
        if not page_candidates:
            return _desktop_response(win, "no_cdp_target", MSG["no_cdp_target"])

        request = {
            "point": {"x": x, "y": y},
            "window": {
                "x": win.get("x", 0),
                "y": win.get("y", 0),
                "w": win.get("w", 0),
                "h": win.get("h", 0),
                "title": win.get("title") or "",
            },
            "browserWebSocketUrl": browser_ws_url,
            "candidates": page_candidates,
            "devtoolsTargetIds": devtools_ids,
            "limits": {
                "maxText": MAX_TEXT_BYTES,
                "maxAttrs": MAX_ATTRS,
                "maxAttrValue": MAX_ATTR_VALUE_BYTES,
                "cdpTimeoutSec": CDP_CALL_TIMEOUT_SEC,
            },
        }
        child = _run_inspect_subprocess(request, timeout=_sub_timeout(deadline))
    except subprocess.TimeoutExpired:
        # PHẢI bắt TRƯỚC SubprocessError — TimeoutExpired là lớp con của nó.
        return _desktop_response(win, "cdp_timeout", MSG["cdp_timeout"])
    except (capture.CaptureError, subprocess.SubprocessError, OSError, ValueError):
        return _desktop_response(win, "cdp_unreachable", MSG["cdp_unreachable"])

    if not child.get("ok"):
        reason = child.get("reason") or "extract_failed"
        if reason not in MSG:
            reason = "extract_failed"
        return _desktop_response(win, reason, MSG[reason])

    return _dom_response(win, child)


def dispatch_inspect_element(x, y) -> dict:
    """Điểm vào công khai duy nhất — `ide-proxy.py` chỉ gọi hàm này."""
    if not _INSPECT_SEMAPHORE.acquire(blocking=False):
        raise capture.CaptureError(
            f"Đã đạt {MAX_CONCURRENT_INSPECTS} yêu cầu inspect-element đồng thời — thử lại sau.",
            status_code=429,
        )
    try:
        return _dispatch_inspect_element_locked(x, y)
    finally:
        _INSPECT_SEMAPHORE.release()
