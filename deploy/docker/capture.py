#!/usr/bin/env python3
"""Capture/record theo từng cửa sổ X11, tab Chromium (CDP) hoặc full-screen.

Mô-đun này được `ide-proxy.py` (chạy root) import và gọi trực tiếp. Nó PHẢI thuần
stdlib (không import Playwright) — Playwright được tách sang `browser_capture.py`
gọi qua subprocess để cách ly crash (một lỗi CDP/Playwright không kéo chết tiến
trình ide-proxy — control plane của box).

Quy ước:
- Mọi lệnh X11 (wmctrl/xprop/xdotool/import/ffmpeg) chạy với `gosu agent` +
  DISPLAY=:99 + HOME=/home/agent để file sinh ra thuộc `agent` (1000:1000) và
  chạm đúng X server của agent.
- Lỗi được ném là `CaptureError` (có `status_code` + `public_message`) để
  ide-proxy ánh xạ thẳng thành HTTP status.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

DISPLAY = ":99"
AGENT_UID = 1000
AGENT_GID = 1000
AGENT_HOME = "/home/agent"
AGENT_USER = "agent"
WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "/home/agent/workspace"))
CAPTURE_ROOT = WORKSPACE_ROOT / ".generated_artifacts" / "captures"
RECORDS_ROOT = CAPTURE_ROOT / "records"

# RandR mở tới 32768x32768 → ảnh `root` có thể vượt hàng trăm MPx và làm OOM.
# Chốt trần an toàn (4096x4096 ≈ 16.7 MPx). Vượt trần → lỗi 413, buộc chụp nhỏ hơn.
MAX_SCREEN_PIXELS = 4096 * 4096
MAX_CONCURRENT_RECORDS = 2
MAX_RECORD_SECONDS = 600
CDP_ENDPOINT = "http://127.0.0.1:9222"
BROWSER_CAPTURE_BIN = Path(os.environ.get("BROWSER_CAPTURE_BIN", "/usr/local/bin/browser_capture.py"))

SUPPORTED_IMAGE_FORMATS = ("png", "jpg")

# Serial hoá thao tác raise + chụp/record X11: không có compositor nên việc raise
# cửa sổ B trong lúc đang quay cửa sổ A sẽ đè nhiễm vào bản ghi A.
_X11_LOCK = threading.RLock()
_RECORDS_LOCK = threading.Lock()
_RECORDS: dict[str, dict] = {}
# Bản ghi đã dừng (stop tường minh hoặc tự hết `-t`) — giữ một phần gần nhất để
# agent có thể tra lại kết quả sau khi record kết thúc, kể cả khi nó quên stop.
_FINISHED_RECORDS: dict[str, dict] = {}
_MAX_FINISHED_RECORDS = 20


class CaptureError(Exception):
    """Lỗi capture/record, mang sẵn HTTP status để ide-proxy trả thẳng."""

    def __init__(self, public_message: str, *, status_code: int = 500, details=None):
        super().__init__(public_message)
        self.public_message = public_message
        self.status_code = status_code
        self.details = details


def _invalid(message: str, details=None) -> CaptureError:
    return CaptureError(message, status_code=400, details=details)


def _not_found(message: str, details=None) -> CaptureError:
    return CaptureError(message, status_code=404, details=details)


def _ambiguous(message: str, details=None) -> CaptureError:
    return CaptureError(message, status_code=409, details=details)


def _conflict(message: str, details=None) -> CaptureError:
    return CaptureError(message, status_code=409, details=details)


# ---------------------------------------------------------------------------
# Thi hành lệnh bằng user agent (root hiện tại gọi gosu để hạ quyền)
# ---------------------------------------------------------------------------
def _agent_env() -> dict[str, str]:
    return {
        "DISPLAY": DISPLAY,
        "HOME": AGENT_HOME,
        "XDG_CONFIG_HOME": AGENT_HOME + "/.config",
        "XDG_CACHE_HOME": AGENT_HOME + "/.cache",
        "XDG_DATA_HOME": AGENT_HOME + "/.local/share",
    }


def _as_agent_argv(args: list[str]) -> list[str]:
    env_pairs = [f"{key}={value}" for key, value in _agent_env().items()]
    return ["gosu", AGENT_USER, "env", *env_pairs, *args]


def _run_as_agent(args: list[str], *, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        _as_agent_argv(args),
        timeout=timeout,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _popen_as_agent(args: list[str]) -> subprocess.Popen:
    return subprocess.Popen(
        _as_agent_argv(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


# ---------------------------------------------------------------------------
# Thư mục lưu + tên file
# ---------------------------------------------------------------------------
def _ensure_dirs() -> None:
    for directory in (CAPTURE_ROOT / "window", CAPTURE_ROOT / "screen",
                      CAPTURE_ROOT / "tab", RECORDS_ROOT):
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chown(directory, AGENT_UID, AGENT_GID)
            os.chmod(directory, 0o750)
        except PermissionError:
            pass
    try:
        os.chown(CAPTURE_ROOT, AGENT_UID, AGENT_GID)
    except PermissionError:
        pass


def _slug(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]", "-", value)[:80]


def _new_path(kind: str, key: str, extension: str) -> Path:
    _ensure_dirs()
    return CAPTURE_ROOT / kind / f"{int(time.time() * 1000)}-{_slug(key)}.{extension}"


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# X11 — liệt kê + nhận diện cửa sổ
# ---------------------------------------------------------------------------
def _wmctrl_list() -> str:
    # wmctrl -lx (KHÔNG -lxG): cột ổn định `<id> <desktop> <class> <host> <title...>`,
    # title nằm cuối nên không bị nhập nhằng với hình học. Hình học lấy riêng qua xwininfo.
    proc = _run_as_agent(["wmctrl", "-lx"], timeout=15)
    if proc.returncode != 0:
        raise CaptureError("Không chạy được wmctrl (X11 chưa sẵn sàng?).", status_code=500)
    return proc.stdout or ""


def _parse_wmctrl_line(line: str) -> dict | None:
    # wmctrl -lx: <id> <desktop> <class> <host> <title...> — title là phần còn lại.
    tokens = line.split()
    if len(tokens) < 4 or not tokens[0].startswith("0x"):
        return None
    return {
        "id": tokens[0],
        "desktop": tokens[1],
        "class": tokens[2],
        "host": tokens[3],
        "title": " ".join(tokens[4:]),
    }


def _int_after_colon(text: str) -> int | None:
    try:
        return int(text.split(":", 1)[1].strip())
    except (IndexError, ValueError):
        return None


def _wininfo_geometry(win_id: str) -> dict | None:
    proc = _run_as_agent(["xwininfo", "-id", win_id], timeout=10)
    if proc.returncode != 0:
        return None
    x = y = width = height = None
    for line in (proc.stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Absolute upper-left X:"):
            x = _int_after_colon(stripped)
        elif stripped.startswith("Absolute upper-left Y:"):
            y = _int_after_colon(stripped)
        elif stripped.startswith("Width:"):
            width = _int_after_colon(stripped)
        elif stripped.startswith("Height:"):
            height = _int_after_colon(stripped)
    if None in (x, y, width, height):
        return None
    return {"x": x, "y": y, "w": width, "h": height}


def _xprop_many(win_id: str, props: list[str]) -> dict[str, str]:
    # xprop nhận nhiều property cùng lúc → 1 subprocess cho cả state + pid.
    if not props:
        return {}
    proc = _run_as_agent(["xprop", "-id", win_id, *props], timeout=10)
    result: dict[str, str] = {}
    if proc.returncode != 0:
        return result
    for line in (proc.stdout or "").splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        # xprop in tên kèm kiểu: `_NET_WM_PID(CARDINAL)` / `_NET_WM_STATE(ATOM)`.
        name = re.sub(r"\([^)]*\)\s*$", "", name).strip()
        result[name] = value.strip()
    return result


def _parse_pid(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _parse_state(value: str | None) -> list[str]:
    if not value:
        return []
    return [atom.strip() for atom in value.split(",") if atom.strip()]


def _is_selectable(state: list[str]) -> bool:
    # Atom thật từ xprop là `_NET_WM_STATE_SKIP_TASKBAR` / `_NET_WM_STATE_HIDDEN`,
    # nên phải kiểm chuỗi con chứ KHÔNG so khớp nguyên ký tự bằng nhau (bug cũ đã
    # để panel/dock lọt thành selectable).
    return not any("SKIP_TASKBAR" in atom or "HIDDEN" in atom for atom in state)


def list_windows() -> list[dict]:
    windows: list[dict] = []
    for line in _wmctrl_list().splitlines():
        win = _parse_wmctrl_line(line)
        if not win:
            continue
        geometry = _wininfo_geometry(win["id"])
        if geometry:
            win.update(geometry)
        else:
            # Cửa sổ vừa bị đóng giữa wmctrl→xwininfo: vẫn liệt kê, chụp sẽ thất bại
            # đóng (fail-closed) lúc _check_size chứ không treo ở đây.
            win.update({"x": 0, "y": 0, "w": 0, "h": 0})
        props = _xprop_many(win["id"], ["_NET_WM_STATE", "_NET_WM_PID"])
        state = _parse_state(props.get("_NET_WM_STATE"))
        pid = _parse_pid(props.get("_NET_WM_PID"))
        win["pid"] = pid
        win["state"] = state
        win["selectable"] = _is_selectable(state)
        windows.append(win)
    return windows


def _class_matches(full: str, wanted: str) -> bool:
    full = (full or "").lower()
    wanted = (wanted or "").strip().lower()
    if not wanted:
        return False
    if wanted == full:
        return True
    if "." in full:
        instance, klass = full.split(".", 1)
        if wanted in (instance, klass):
            return True
    return wanted in full


def resolve_window(spec: dict) -> dict:
    win_id = spec.get("windowId")
    pid = spec.get("pid")
    klass = spec.get("class")
    title = spec.get("title")

    windows = list_windows()
    if win_id:
        needle = str(win_id).lower()
        matches = [w for w in windows if w["id"].lower() == needle]
    elif pid is not None:
        try:
            target_pid = int(pid)
        except (TypeError, ValueError):
            raise _invalid("pid phải là số nguyên")
        matches = [w for w in windows if w.get("pid") == target_pid]
    elif klass:
        matches = [w for w in windows if _class_matches(w["class"], str(klass))]
    elif title:
        needle = str(title).lower()
        matches = [w for w in windows if needle in (w["title"] or "").lower()]
    else:
        raise _invalid("kind=window cần ít nhất một trong windowId/pid/class/title")

    if not matches:
        raise _not_found("Không tìm thấy cửa sổ khớp target")

    selectable = [w for w in matches if w.get("selectable")]
    pool = selectable or matches
    if len(pool) > 1:
        raise _ambiguous("Nhiều cửa sổ khớp target — chọn chính xác hơn", details={"windows": pool})
    if len(pool) == 1:
        return pool[0]
    # matches có nhiều nhưng nằm ngoài pool (đều bị bỏ qua) → an toàn thất bại đóng.
    raise _not_found("Cửa sổ khớp target không chọn được", details={"windows": matches})


def _check_size(width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        raise CaptureError(f"Kích thước mục tiêu không hợp lệ ({width}x{height}).", status_code=500)
    if width * height > MAX_SCREEN_PIXELS:
        raise CaptureError(
            f"Diện tích {width}x{height} vượt trần an toàn "
            f"({int(MAX_SCREEN_PIXELS ** 0.5)}x{int(MAX_SCREEN_PIXELS ** 0.5)} px). "
            "Chụp theo cửa sổ/tab nhỏ hơn thay vì full-screen.",
            status_code=413,
        )


def screen_size() -> tuple[int, int]:
    proc = _run_as_agent(["xrandr"], timeout=10)
    if proc.returncode != 0:
        raise CaptureError("Không đọc được kích thước màn hình (xrandr).", status_code=500)
    for line in (proc.stdout or "").splitlines():
        match = re.search(r"current (\d+) x (\d+)", line)
        if match:
            return int(match.group(1)), int(match.group(2))
    raise CaptureError("Không tìm thấy kích thước 'current' trong xrandr.", status_code=500)


def _raise_window(win_id: str) -> None:
    # Activate + raise. Không dùng `xdotool windowactivate --sync` (có thể treo khi WM
    # không hỗ trợ _NET_ACTIVE_WINDOW). Mỗi lệnh là best-effort: lỗi/timeout không được
    # kéo chết capture — cửa sổ bị che sẽ cho ảnh thiếu, đó là tín hiệu rõ ràng.
    for args in (
        ["wmctrl", "-ia", win_id],
        ["xdotool", "windowactivate", win_id],
        ["xdotool", "windowraise", win_id],
    ):
        try:
            _run_as_agent(args, timeout=10)
        except (subprocess.SubprocessError, OSError):
            continue
    time.sleep(0.2)  # chờ WM map/raise xong trước khi đọc pixel


# ---------------------------------------------------------------------------
# Browser — danh sách tab qua CDP HTTP (/json/list)
# ---------------------------------------------------------------------------
def list_tabs() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{CDP_ENDPOINT}/json/list", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise CaptureError(
            f"CDP 9222 chưa sẵn sàng (Chromium desktop chưa mở qua box-chromium?): {error}",
            status_code=502,
        )
    tabs = []
    for target in payload:
        if target.get("type") != "page":
            continue
        tabs.append({
            "id": target.get("id"),
            "url": target.get("url", ""),
            "title": target.get("title", ""),
            "type": "page",
            "webSocketDebuggerUrl": target.get("webSocketDebuggerUrl", ""),
        })
    return tabs


def resolve_tab(spec: dict) -> dict:
    tab_id = spec.get("tabId")
    url = spec.get("url")
    title = spec.get("title")
    tabs = list_tabs()
    if not tabs:
        raise _not_found("Chưa có tab Chrome nào (mở Chromium desktop qua box-chromium trước)")

    if tab_id:
        matches = [t for t in tabs if t["id"] == str(tab_id)]
    elif url:
        needle = str(url).lower()
        matches = [t for t in tabs if needle in (t["url"] or "").lower()]
    elif title:
        needle = str(title).lower()
        matches = [t for t in tabs if needle in (t["title"] or "").lower()]
    else:
        raise _invalid("kind=tab cần tabId/url/title")

    if not matches:
        raise _not_found("Không tìm thấy tab khớp target")
    if len(matches) > 1:
        raise _ambiguous(
            "Nhiều tab khớp target — chọn chính xác hơn",
            details={"tabs": [_public_tab(t) for t in matches]},
        )
    return matches[0]


# ---------------------------------------------------------------------------
# Capture ảnh
# ---------------------------------------------------------------------------
def _capture_window(spec: dict, fmt: str) -> dict:
    win = resolve_window(spec)
    _check_size(win["w"], win["h"])
    path = _new_path("window", f"window-{win['id']}", fmt)
    with _X11_LOCK:
        if _count_active_records() > 0:
            raise _conflict(
                "Có record X11 đang quay — tạm thời không thể raise/chụp cửa sổ X11 (stop record trước)"
            )
        _raise_window(win["id"])
        _run_import("-window", win["id"], str(path), fmt)
    return _image_result(path, fmt, "window", "x11", win["w"], win["h"])


def _capture_screen(fmt: str) -> dict:
    width, height = screen_size()
    _check_size(width, height)
    path = _new_path("screen", "screen", fmt)
    with _X11_LOCK:
        _run_import("-window", "root", str(path), fmt)
    return _image_result(path, fmt, "screen", "x11", width, height)


def _capture_tab(spec: dict, fmt: str) -> dict:
    tab = resolve_tab(spec)
    if not tab.get("webSocketDebuggerUrl"):
        raise CaptureError("Tab không có webSocketDebuggerUrl — CDP bất thường.", status_code=500)
    path = _new_path("tab", f"tab-{tab['id'][:24]}", fmt)
    args = [
        sys.executable, str(BROWSER_CAPTURE_BIN), "capture_tab",
        "--web-socket-url", tab["webSocketDebuggerUrl"],
        "--path", str(path),
        "--format", fmt,
    ]
    if spec.get("fullPage"):
        args.append("--full-page")
    proc = _popen_as_agent(args)
    stdout, stderr = proc.communicate(timeout=90)
    if proc.returncode != 0:
        raise CaptureError(
            f"Chụp tab thất bại: {(stderr or stdout or '').strip()[:300]}",
            status_code=500,
        )
    try:
        result = json.loads(stdout)
    except json.JSONDecodeError:
        raise CaptureError("browser_capture trả output không phải JSON hợp lệ.", status_code=500)
    width = int(result.get("width") or 0)
    height = int(result.get("height") or 0)
    return _image_result(path, fmt, "tab", "cdp", width, height)


def _run_import(selector: str, window_id: str, path: str, fmt: str) -> None:
    args = ["import", selector, window_id]
    if fmt == "jpg":
        args += ["-quality", "85"]
    args.append(path)
    proc = _run_as_agent(args, timeout=60)
    if proc.returncode != 0:
        raise CaptureError(
            f"ImageMagick import thất bại: {(proc.stderr or '').strip()[:300]}",
            status_code=500,
        )
    if not Path(path).exists():
        raise CaptureError("ImageMagick import không tạo ra file ảnh.", status_code=500)


def _image_result(path: Path, fmt: str, kind: str, method: str,
                  width: int, height: int) -> dict:
    if not path.exists():
        raise CaptureError("File ảnh không tồn tại sau khi capture.", status_code=500)
    return {
        "ok": True,
        "path": str(path),
        "width": width,
        "height": height,
        "format": fmt,
        "kind": kind,
        "method": method,
        "sha256": _sha256(path),
    }


def capture(spec: dict, default_format: str = "png") -> dict:
    kind = spec.get("kind", "screen")
    fmt = spec.get("format", default_format) or default_format
    if fmt not in SUPPORTED_IMAGE_FORMATS:
        raise _invalid(f"format phải là một trong {SUPPORTED_IMAGE_FORMATS}")
    if kind == "window":
        return _capture_window(spec, fmt)
    if kind == "tab":
        return _capture_tab(spec, fmt)
    if kind == "screen":
        return _capture_screen(fmt)
    raise _invalid("kind phải là window/tab/screen")


# ---------------------------------------------------------------------------
# Record video
# ---------------------------------------------------------------------------
def _new_record_id() -> str:
    return f"rec-{int(time.time() * 1000)}-{os.getpid()}"


def _register(record_id: str, entry: dict) -> None:
    with _RECORDS_LOCK:
        _RECORDS[record_id] = entry


def _active_x11_records() -> list[dict]:
    with _RECORDS_LOCK:
        return [entry for entry in _RECORDS.values()]


def _count_active_records() -> int:
    return len(_active_x11_records())


def _video_duration_sec(path) -> float | None:
    """Đo thời lượng video THỰC bằng ffprobe, không dùng wall-clock.

    Wall-clock sai với bản ghi tự dừng bằng `-t`: ffmpeg thoát sau N giây nhưng
    agent có thể reap muộn (hàng chục giây), khiến `durationSec` bị thổi phồng.
    Trả về None khi không đọc được (fallback wall-clock ở `_record_finished_entry`).
    """
    try:
        proc = _run_as_agent(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", str(path)],
            timeout=10,
        )
        text = (proc.stdout or "").strip()
        value = float(text)
        return value if value > 0 else None
    except (ValueError, OSError, subprocess.TimeoutExpired):
        return None


def _record_finished_entry(entry: dict) -> dict:
    path = Path(entry["path"])
    duration = _video_duration_sec(path)
    if duration is None:
        started_at = float(entry.get("startedAt", time.time()))
        duration = max(0.0, time.time() - started_at)
    return {
        "recordingId": entry["recordingId"],
        "kind": entry["kind"],
        "target": entry.get("target"),
        "path": entry["path"],
        "durationSec": round(float(duration), 2),
        "sizeBytes": _file_size(path),
        "finished": True,
    }


def _remember_finished(item: dict) -> None:
    with _RECORDS_LOCK:
        _FINISHED_RECORDS[item["recordingId"]] = item
        while len(_FINISHED_RECORDS) > _MAX_FINISHED_RECORDS:
            _FINISHED_RECORDS.pop(next(iter(_FINISHED_RECORDS)))


def _reap_finished_records() -> None:
    """Bỏ khỏi danh sách active các bản ghi đã tự thoát (hết `-t` ffmpeg).

    Không có bước này, một record quên stop sẽ nằm mãi trong `_RECORDS` → `record_start`
    bị 409 "đã đạt 2 bản ghi" và `_capture_window` bị 409 "có record X11 đang quay"
    dù chẳng còn gì chạy.
    """
    reaped: list[dict] = []
    with _RECORDS_LOCK:
        for record_id in list(_RECORDS):
            entry = _RECORDS[record_id]
            if entry["process"].poll() is None:
                continue
            _RECORDS.pop(record_id, None)
            reaped.append(entry)
    for entry in reaped:
        _remember_finished(_record_finished_entry(entry))


def _spawn_ffmpeg(args: list[str]) -> subprocess.Popen:
    # DEVNULL (không PIPE) để ffmpeg không thể block vì đầy pipe khi chạy dài.
    return subprocess.Popen(
        _as_agent_argv(["ffmpeg", "-loglevel", "error", "-y", *args]),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def record_start(spec: dict) -> dict:
    # Bỏ các bản ghi đã tự thoát (hết -t) TRƯỚC khi đếm concurrency — nếu không,
    # bản ghi "ma" vẫn chiếm chỗ và chặn record mới dù ffmpeg đã dừng từ lâu.
    _reap_finished_records()

    kind = spec.get("kind", "screen")
    try:
        framerate = int(spec.get("framerate", 15))
    except (TypeError, ValueError):
        raise _invalid("framerate phải là số nguyên")
    if framerate <= 0 or framerate > 60:
        raise _invalid("framerate phải trong khoảng 1..60")
    try:
        max_duration = int(spec.get("maxDurationSec", MAX_RECORD_SECONDS))
    except (TypeError, ValueError):
        raise _invalid("maxDurationSec phải là số nguyên")
    if max_duration <= 0 or max_duration > 86400:
        max_duration = MAX_RECORD_SECONDS

    if kind == "tab":
        raise CaptureError(
            "record theo tab (CDP screencast) chưa hỗ trợ ở v1 — dùng kind=screen/window.",
            status_code=501,
        )

    with _X11_LOCK:
        if _count_active_records() >= MAX_CONCURRENT_RECORDS:
            raise _conflict(
                f"Đã đạt {MAX_CONCURRENT_RECORDS} bản ghi đồng thời — stop bớt rồi thử lại"
            )
        if kind == "window":
            win = resolve_window(spec)
            _check_size(win["w"], win["h"])
            path = _new_path("window", f"window-{win['id']}", "mp4")
            _raise_window(win["id"])
            proc = _spawn_ffmpeg([
                "-f", "x11grab", "-framerate", str(framerate),
                "-window_id", win["id"], "-video_size", f"{win['w']}x{win['h']}",
                "-i", DISPLAY,
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-t", str(max_duration),
                str(path),
            ])
            target = {"kind": "window", "windowId": win["id"]}
        elif kind == "screen":
            width, height = screen_size()
            _check_size(width, height)
            path = _new_path("screen", "screen", "mp4")
            proc = _spawn_ffmpeg([
                "-f", "x11grab", "-framerate", str(framerate),
                "-video_size", f"{width}x{height}", "-i", DISPLAY,
                "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                "-t", str(max_duration),
                str(path),
            ])
            target = {"kind": "screen"}
        else:
            raise _invalid("kind phải là window/tab/screen")

    record_id = _new_record_id()
    _register(record_id, {
        "recordingId": record_id,
        "kind": kind,
        "target": target,
        "path": str(path),
        "process": proc,
        "pid": proc.pid,
        "startedAt": time.time(),
        "maxDurationSec": max_duration,
    })
    return {
        "ok": True,
        "recordingId": record_id,
        "path": str(path),
        "format": "mp4",
        "framerate": framerate,
        "startedAt": int(time.time() * 1000),
    }


def record_stop(recording_id: str) -> dict:
    with _RECORDS_LOCK:
        entry = _RECORDS.get(recording_id)
    if not entry:
        raise _not_found("Không tìm thấy recordingId đang chạy")

    proc: subprocess.Popen = entry["process"]
    try:
        proc.send_signal(signal.SIGINT)
    except (ProcessLookupError, AttributeError, OSError):
        pass
    try:
        proc.wait(timeout=20)
    except subprocess.TimeoutExpired:
        # Hết đường mềm (SIGINT) thì dùng đường cứng rồi mới chờ lần cuối.
        try:
            proc.send_signal(signal.SIGKILL)
        except (ProcessLookupError, AttributeError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            raise CaptureError("Không dừng được tiến trình ffmpeg.", status_code=500)

    with _RECORDS_LOCK:
        _RECORDS.pop(recording_id, None)

    result = _record_finished_entry(entry)
    result["ok"] = True
    _remember_finished(result)
    return result


def record_status() -> dict:
    _reap_finished_records()
    with _RECORDS_LOCK:
        active = [
            {
                "recordingId": entry["recordingId"],
                "kind": entry["kind"],
                "target": entry.get("target"),
                "path": entry["path"],
                "pid": entry.get("pid"),
                "startedAt": int(entry["startedAt"] * 1000),
            }
            for entry in _RECORDS.values()
        ]
        finished = list(_FINISHED_RECORDS.values())
    return {"active": active, "finished": finished}


# ---------------------------------------------------------------------------
# Hàm entry trả dict theo đúng hợp đồng §5 — dùng chung cho ide-proxy
# ---------------------------------------------------------------------------
def dispatch_list_windows() -> dict:
    return {"windows": list_windows()}


def _public_tab(tab: dict) -> dict:
    # Không để lộ webSocketDebuggerUrl nội bộ ra endpoint public — chỉ capture_tab
    # (qua resolve_tab → list_tabs) dùng nó khi chụp.
    return {key: value for key, value in tab.items() if key != "webSocketDebuggerUrl"}


def dispatch_list_tabs() -> dict:
    return {"tabs": [_public_tab(tab) for tab in list_tabs()]}


def dispatch_capture(target: dict, output: str = "file") -> dict:
    result = capture(target)
    if output == "base64":
        import base64
        path = Path(result["path"])
        result["data"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return result


def dispatch_record_start(target: dict) -> dict:
    return record_start(target)


def dispatch_record_stop(recording_id: str) -> dict:
    return record_stop(recording_id)


def dispatch_record_status() -> dict:
    return record_status()
