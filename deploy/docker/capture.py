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
from collections import OrderedDict
from pathlib import Path

# `session_files.py` nằm cùng thư mục trong box (`/usr/local/bin`) — nguồn duy nhất cho khung
# thư mục phiên, chỉ mục ảnh và trần dọn dẹp. Import có phòng: một container chưa kịp stage file
# phụ vẫn phải chụp/ghi hình được (control plane không chết vì thiếu bản sao hằng số), chỉ mất
# phần chỉ mục/dọn dẹp cho tới khi file đó có mặt.
try:
    import session_files as _session_files
except Exception:  # noqa: BLE001
    _session_files = None

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
# W9 (recording-finalization): MP4 thường chỉ ghi `moov` khi ffmpeg kết thúc êm; bị SIGKILL là
# mất `moov` ("moov atom not found"). MP4 phân mảnh (`empty_moov` + fragment theo keyframe, GOP
# 2 giây, flush mỗi packet) vẫn đọc được tới fragment cuối khi ffmpeg bị kill. Đo trong box
# (deploy/docker/tests/probe_recorder.py): SIGSTOP ffmpeg → SIGINT không tác dụng → SIGKILL sau
# 20 s → bản cũ trả `ok` với file 48 byte không probe được, đúng chữ ký lỗi sweep đã lưu.
RECORD_GOP_SECONDS = 2
RECORD_MOVFLAGS = "+frag_keyframe+empty_moov+default_base_moof"
# Ngân sách dừng (giây). Harness chờ HTTP tối đa 40 s (`sandbox/executor.py`), nên tổng
# SIGINT + SIGTERM + SIGKILL + ffprobe phải nằm dưới mức đó.
RECORD_STOP_SIGINT_WAIT = 15
RECORD_STOP_SIGTERM_WAIT = 5
RECORD_STOP_SIGKILL_WAIT = 5
# stderr của ffmpeg (trước đây DEVNULL nên mất chẩn đoán) vào file ngoài workspace người dùng.
FFMPEG_LOG_DIR = Path(os.environ.get("BOXFOX_FFMPEG_LOG_DIR", "/tmp/boxfox-ffmpeg"))
FFMPEG_LOG_TAIL_CHARS = 800
CDP_ENDPOINT = "http://127.0.0.1:9222"
BROWSER_CAPTURE_BIN = Path(os.environ.get("BROWSER_CAPTURE_BIN", "/usr/local/bin/browser_capture.py"))

SUPPORTED_IMAGE_FORMATS = ("png", "jpg")

# Trần dọn dẹp (F2): hằng số nằm ở `session_files.py` để tầng ghi và tầng dọn không bao giờ lệch
# nhau; nhánh dự phòng chỉ chạy khi container chưa có file đó.
CAPTURE_KEEP_PER_KIND = _session_files.CAPTURE_KEEP_PER_KIND if _session_files else 200
CAPTURE_MAX_BYTES_PER_SESSION = (_session_files.CAPTURE_MAX_BYTES_PER_SESSION if _session_files
                                 else 512 * 1024 * 1024)
CAPTURE_MAX_BYTES_BOX = _session_files.CAPTURE_MAX_BYTES_BOX if _session_files else 4 * 1024 * 1024 * 1024
RECORD_KEEP_PER_SESSION = _session_files.RECORD_KEEP_PER_SESSION if _session_files else 40
CAPTURE_EVICT_EVERY = _session_files.CAPTURE_EVICT_EVERY if _session_files else 20
CAPTURE_DEDUP_LRU = _session_files.CAPTURE_DEDUP_LRU if _session_files else 256
# File vừa ghi trong tiến trình này không bao giờ bị dọn: capture.py chạy trong box, không đọc
# được DB nên không biết "50 event tool_end mới nhất" — nó giữ đúng 50 đường dẫn gần nhất của
# chính mình. Danh sách bảo vệ phía harness (ảnh đang hiện trên UI) là việc của route prune.
CAPTURE_RECENT_PROTECT = 50
SESSION_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")

# Serial hoá thao tác raise + chụp/record X11: không có compositor nên việc raise
# cửa sổ B trong lúc đang quay cửa sổ A sẽ đè nhiễm vào bản ghi A.
_X11_LOCK = threading.RLock()
_RECORDS_LOCK = threading.Lock()
_RECORDS: dict[str, dict] = {}
# Bản ghi đã dừng (stop tường minh hoặc tự hết `-t`) — giữ một phần gần nhất để
# agent có thể tra lại kết quả sau khi record kết thúc, kể cả khi nó quên stop.
_FINISHED_RECORDS: dict[str, dict] = {}
_MAX_FINISHED_RECORDS = 20

# Khử trùng lặp theo nội dung: `{(sid8, kind): OrderedDict[sha256 -> relPath]}`. Ảnh desktop
# không đổi giữa hai lần chụp là ca **rất** thường gặp trong box dùng chung — mỗi lần lưu thêm
# một bản y hệt vừa tốn đĩa vừa làm chỉ mục dài vô nghĩa.
_DEDUP_LOCK = threading.Lock()
_DEDUP: dict[tuple[str, str], "OrderedDict[str, str]"] = {}
_RECENT_CAPTURE_PATHS: list[str] = []
_WRITES_SINCE_EVICT = 0


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
        stdin=subprocess.PIPE,
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


def _key_with_label(key: str, spec: dict) -> str:
    """Ghép NHÃN của lần chụp (P2.3) vào khoá tên tệp: `tab-3f9a2b1c` -> `tab-3f9a2b1c-rag-test`.

    Nhãn nằm TRONG `key` (không thành một trường mới của tên tệp), nên `_new_path` giữ nguyên luật
    cũ: `_slug` + bộ đếm chống trùng. Nhãn do HARNESS sinh từ `caption` của model và đã bỏ dấu
    (`executor.capture_label`); box chỉ làm sạch thêm một lần nữa để không ký tự lạ nào lọt vào tên
    tệp. Spec không có `label` — mọi đường gọi cũ, kể cả IDE proxy — thì tên tệp y như trước.
    """
    label = _slug(str((spec or {}).get("label") or "")).strip("-_.")
    return f"{key}-{label}" if label else key


def _new_path(kind: str, key: str, extension: str, *, session: str = None, step=None) -> Path:
    """Đường dẫn cho file mới — **theo phiên** khi biết phiên, phẳng như cũ khi không.

    Vì sao có hai khuôn: `captures/screen/` đang là một thư mục phẳng 375 file của mọi phiên, nên
    "ảnh này của phiên nào" chỉ trả lời được bằng cách quét hơn 100 000 hàng `events`. Khuôn mới
    `<kind>/<sid8>/<sid8>_<step>_<slug>.<ext>` trả lời câu đó bằng chính đường dẫn. File cũ **giữ
    nguyên tại chỗ** (link trong UI còn trỏ vào) và vẫn mở được qua `/__box/file/media`.
    """
    _ensure_dirs()
    sid = _session_id(session)
    if sid is None:
        return CAPTURE_ROOT / kind / f"{int(time.time() * 1000)}-{_slug(key)}.{extension}"
    sid8 = _sid8(sid)
    directory = _ensure_session_dirs(kind, sid8)
    stem = f"{sid8}_{_step_token(step)}_{_slug(key)}"
    candidate = directory / f"{stem}.{extension}"
    if not candidate.exists():
        return candidate
    # Cùng bước, cùng khoá, hai lần chụp: không bao giờ ghi đè ảnh cũ (link đã phát tán trong
    # event stream) — thêm hậu tố đếm, giữ nguyên khuôn `<sid8>_<step>_<slug>`.
    for index in range(2, 1000):
        candidate = directory / f"{stem}-{index}.{extension}"
        if not candidate.exists():
            return candidate
    return directory / f"{stem}-{int(time.time() * 1000)}.{extension}"


def _session_id(value) -> str | None:
    """Chuẩn hoá session id do harness gửi kèm; `None` nghĩa là "không theo phiên"."""
    text = str(value or "").strip().lower()
    return text if SESSION_ID_RE.match(text) else None


def _sid8(sid: str) -> str:
    """8 hex đầu (12 khi đụng độ) — luật đụng độ lấy từ `session_files`, gốc là `.session-history`."""
    if _session_files is not None:
        try:
            return _session_files.sid8_of(sid, root=_session_files.SESSION_HISTORY_DIR)
        except Exception:  # noqa: BLE001
            pass
    return sid[:8]


def _step_token(step) -> str:
    """Bước của công cụ thành 3 chữ số (`003`); không biết bước thì `000` — không bao giờ rỗng."""
    try:
        value = int(step)
    except (TypeError, ValueError):
        return "000"
    return f"{max(0, value):03d}"


def _ensure_session_dirs(kind: str, sid8: str) -> Path:
    """Thư mục ảnh của một phiên: `<capture root>/<kind>/<sid8>/`, quyền như mọi thư mục khác."""
    directory = CAPTURE_ROOT / kind / sid8
    directory.mkdir(parents=True, exist_ok=True)
    for target in (CAPTURE_ROOT / kind, directory):
        try:
            os.chown(target, AGENT_UID, AGENT_GID)
            os.chmod(target, 0o750)
        except OSError:
            pass
    return directory


def _rel_path(path) -> str:
    """Đường dẫn tương đối so với workspace — đúng khuôn `relPath` của chỉ mục ảnh."""
    try:
        return str(Path(path).relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


def _from_rel(rel: str) -> Path:
    return WORKSPACE_ROOT / str(rel)


def _dedup_lookup(key: tuple[str, str], sha: str) -> str | None:
    if not sha:
        return None
    with _DEDUP_LOCK:
        bucket = _DEDUP.get(key)
        return bucket.get(sha) if bucket else None


def _dedup_remember(key: tuple[str, str], sha: str, rel: str) -> None:
    if not sha:
        return
    with _DEDUP_LOCK:
        bucket = _DEDUP.setdefault(key, OrderedDict())
        bucket.pop(sha, None)
        bucket[sha] = rel
        while len(bucket) > CAPTURE_DEDUP_LRU:
            bucket.popitem(last=False)


def _remember_recent(path) -> None:
    text = str(path)
    if text in _RECENT_CAPTURE_PATHS:
        _RECENT_CAPTURE_PATHS.remove(text)
    _RECENT_CAPTURE_PATHS.append(text)
    del _RECENT_CAPTURE_PATHS[:-CAPTURE_RECENT_PROTECT]


def _index_append(item: dict) -> None:
    """Ghi một dòng chỉ mục — **best effort**: chỉ mục là bản phụ, hỏng nó không được làm hỏng ảnh."""
    if _session_files is None:
        return
    session = item.get("session")
    try:
        _session_files.capture_index_append(CAPTURE_ROOT, sid=session, item=item)
    except Exception:  # noqa: BLE001
        return
    _note_capture_write()


def _note_capture_write() -> None:
    """Đếm đường ghi; cứ `CAPTURE_EVICT_EVERY` lần thì dọn một lượt (dọn hỏng cũng không sao)."""
    global _WRITES_SINCE_EVICT
    _WRITES_SINCE_EVICT += 1
    if _WRITES_SINCE_EVICT < CAPTURE_EVICT_EVERY:
        return
    _WRITES_SINCE_EVICT = 0
    _prune_captures()


def _prune_captures(session: str = None, dry_run: bool = False) -> dict:
    """Dọn ảnh/ghi hình theo trần F2, giữ lại 50 đường dẫn gần nhất của tiến trình này."""
    if _session_files is None:
        return {"ok": False, "removedFiles": 0, "removedBytes": 0,
                "error": "session_files chưa có trong container"}
    try:
        return _session_files.retention(CAPTURE_ROOT, session=session,
                                        protect=list(_RECENT_CAPTURE_PATHS), dry_run=dry_run)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "removedFiles": 0, "removedBytes": 0, "error": str(exc)}


def _image_index_item(result: dict, *, sid: str, sid8: str, kind: str, step, tool_call_id,
                      dedup: str = "new", duplicate_of: str = None) -> dict:
    """Một dòng chỉ mục cho ảnh — đủ để nối ảnh về đúng bước công cụ đã sinh ra nó."""
    item = {
        "ts": time.time(), "session": sid, "sid8": sid8, "kind": kind,
        "path": str(result.get("path") or ""), "relPath": _rel_path(result.get("path") or ""),
        "bytes": _file_size(Path(result.get("path") or ".")), "sha256": result.get("sha256"),
        "format": result.get("format"), "width": result.get("width"), "height": result.get("height"),
        "method": result.get("method"), "media": "image", "durationSec": None,
        "dedup": dedup, "step": step, "toolCallId": tool_call_id, "backfilled": False,
    }
    if duplicate_of:
        item["duplicateOf"] = duplicate_of
    return item


def _finish_image(result: dict, *, session: str = None, step=None, tool_call_id=None) -> dict:
    """Sau khi chụp: khử trùng lặp, ghi chỉ mục, rồi trả artifact (có thể trỏ về file cũ).

    Khử theo **nội dung** (sha256) chứ không theo tên: cùng một màn hình desktop chụp hai lần là
    hai file khác tên, cùng nội dung. Trùng thì **không** giữ file thứ hai và artifact trỏ về file
    cũ — ảnh vẫn hiện đúng, mà đĩa không phình.
    """
    sid = _session_id(session)
    if sid is None:
        return result
    sid8 = _sid8(sid)
    kind = str(result.get("kind") or "screen")
    path = Path(str(result.get("path") or ""))
    sha = str(result.get("sha256") or "")
    rel = _rel_path(path)
    dedup, duplicate_of = "new", None
    old = _dedup_lookup((sid8, kind), sha)
    if old and old != rel:
        old_path = _from_rel(old)
        if old_path.exists():
            dedup, duplicate_of = "duplicate", old
            _safe_unlink(path)
            result["path"] = str(old_path)
            result["relPath"] = old
            result["deduplicateOf"] = old
    result["relPath"] = _rel_path(result.get("path"))
    if dedup == "new":
        _dedup_remember((sid8, kind), sha, rel)
        _remember_recent(result.get("path"))
    _index_append(_image_index_item(result, sid=sid, sid8=sid8, kind=kind, step=step,
                                    tool_call_id=tool_call_id, dedup=dedup,
                                    duplicate_of=duplicate_of))
    return result


def _safe_unlink(path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _record_index_item(item: dict, entry: dict) -> dict:
    """Một dòng chỉ mục cho bản ghi hình — `sha256` để trống: khử trùng lặp video không đổi lấy gì."""
    session = entry.get("session")
    return {
        "ts": time.time(), "session": session, "sid8": _sid8(session), "kind": entry.get("kind"),
        "path": str(item.get("path") or ""), "relPath": _rel_path(item.get("path") or ""),
        "bytes": int(item.get("sizeBytes") or 0), "sha256": None, "format": "mp4",
        "width": None, "height": None, "method": "x11grab", "media": "video",
        "durationSec": item.get("durationSec"), "dedup": "new", "step": entry.get("step"),
        "toolCallId": entry.get("toolCallId"), "backfilled": False,
        "recordingId": item.get("recordingId"),
    }


def _index_record(item: dict, entry: dict) -> None:
    if _session_id(entry.get("session")) is None:
        return
    _index_append(_record_index_item(item, entry))
    _remember_recent(item.get("path"))


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
def _wmctrl_list(*, timeout: int = 15) -> str:
    # wmctrl -lx (KHÔNG -lxG): cột ổn định `<id> <desktop> <class> <host> <title...>`,
    # title nằm cuối nên không bị nhập nhằng với hình học. Hình học lấy riêng qua xwininfo.
    proc = _run_as_agent(["wmctrl", "-lx"], timeout=timeout)
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


def _parse_xwininfo(stdout: str) -> dict | None:
    # Tách phần parse ra khỏi phần gọi subprocess để dùng chung cho `_wininfo_geometry`
    # (hình học 4 khoá công khai của /__box/windows) và `_wininfo_probe` (thêm
    # `mapState` — cần cho hit-test element-selector, §7-B1).
    x = y = width = height = None
    map_state = ""
    for line in (stdout or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("Absolute upper-left X:"):
            x = _int_after_colon(stripped)
        elif stripped.startswith("Absolute upper-left Y:"):
            y = _int_after_colon(stripped)
        elif stripped.startswith("Width:"):
            width = _int_after_colon(stripped)
        elif stripped.startswith("Height:"):
            height = _int_after_colon(stripped)
        elif stripped.startswith("Map State:"):
            map_state = stripped.split(":", 1)[1].strip()
    if None in (x, y, width, height):
        return None
    return {"x": x, "y": y, "w": width, "h": height, "mapState": map_state}


def _wininfo_probe(win_id: str, *, timeout: int = 10) -> dict | None:
    """`xwininfo -id` với `mapState` — dùng cho hit-test, KHÔNG dùng cho /__box/windows."""
    try:
        proc = _run_as_agent(["xwininfo", "-id", win_id], timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode != 0:
        return None
    return _parse_xwininfo(proc.stdout or "")


def _wininfo_geometry(win_id: str) -> dict | None:
    # Hợp đồng công khai của /__box/windows — GIỮ NGUYÊN đúng 4 khoá {x,y,w,h}.
    probe = _wininfo_probe(win_id)
    if probe is None:
        return None
    return {"x": probe["x"], "y": probe["y"], "w": probe["w"], "h": probe["h"]}


def frame_extents(win_id: str, *, timeout: int = 10) -> dict | None:
    """Đọc `_NET_FRAME_EXTENTS` — phân biệt "vắng mặt hợp lệ" và "lỗi đọc".

    Hợp đồng (element-selector §7-B1, KHÔNG được đổi):
    - rc 0, parse ra đúng 4 số nguyên >= 0  -> {"left","right","top","bottom"}.
    - rc 0, stdout chứa "not found."        -> {0,0,0,0} (vắng mặt HỢP LỆ).
    - rc != 0 / TimeoutExpired / rỗng / không parse được -> None (LỖI ĐỌC, fail-closed).
    Gọi hàm này KHÔNG BAO GIỜ được coi None như {0,0,0,0} — sai sẽ làm cú bấm vào
    titlebar trượt xuống cửa sổ dưới một cách âm thầm.
    """
    try:
        proc = _run_as_agent(["xprop", "-id", win_id, "_NET_FRAME_EXTENTS"], timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    stdout = proc.stdout or ""
    if proc.returncode != 0:
        return None
    if "not found." in stdout:
        return {"left": 0, "right": 0, "top": 0, "bottom": 0}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        _, _, value = line.partition("=")
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 4:
            continue
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            continue
        if any(number < 0 for number in numbers):
            continue
        left, right, top, bottom = numbers
        return {"left": left, "right": right, "top": top, "bottom": bottom}
    return None


def _parse_stacking(stdout: str) -> list[int]:
    # `xprop -root _NET_CLIENT_LIST_STACKING` in dạng
    # `_NET_CLIENT_LIST_STACKING(WINDOW): window id # 0x1e00003, 0x2600003`.
    # Token không parse được (rác) bị BỎ QUA từng cái, không làm rỗng cả danh sách.
    text = stdout or ""
    if "not found." in text or "#" not in text:
        return []
    _, _, value = text.partition("#")
    ids: list[int] = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            ids.append(int(token, 16))
        except ValueError:
            continue
    return ids


def client_list_stacking(*, timeout: int = 10) -> list[int]:
    """Thứ tự stacking DƯỚI→TRÊN của toàn bộ client window (id đã normalize hoá 16)."""
    try:
        proc = _run_as_agent(["xprop", "-root", "_NET_CLIENT_LIST_STACKING"], timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return []
    if proc.returncode != 0:
        return []
    return _parse_stacking(proc.stdout or "")


def _xprop_many(win_id: str, props: list[str], *, timeout: int = 10) -> dict[str, str]:
    # xprop nhận nhiều property cùng lúc → 1 subprocess cho cả state + pid.
    if not props:
        return {}
    result: dict[str, str] = {}
    try:
        proc = _run_as_agent(["xprop", "-id", win_id, *props], timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return result
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


def _is_hittable(state: list[str]) -> bool:
    # CỐ Ý khác `_is_selectable()`: một cửa sổ SKIP_TASKBAR (panel/dock) vẫn *hit
    # được* khi bấm trực tiếp lên nó, dù không *chọn được* trong danh sách capture.
    return not any("HIDDEN" in atom for atom in state)


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


# --- F6 (đợt 8): chặn SÀN kích thước framebuffer ---------------------------------
# Xvnc chạy `-AcceptSetDesktopSize` (auto-fit cho noVNC — tính năng cố ý), nhưng nó
# cho BẤT KỲ trình xem RFB nào kéo framebuffer nhỏ đi (tester từng thấy 286x311).
# Toạ độ CUA sau đó trỏ sai mà không ai báo. Giữ auto-fit, chỉ chặn sàn: trước mọi
# thao tác đọc/ghi toạ độ, nếu màn hình nhỏ hơn cỡ cấu hình thì đặt lại.
DESKTOP_ENV = "BOX_SCREEN"
DEFAULT_DESKTOP = (1280, 800)
VNC_OUTPUT = "VNC-0"


def desktop_target() -> tuple[int, int]:
    """Cỡ màn hình cấu hình (`BOX_SCREEN` = `WxH` hoặc `WxHxD`), mặc định 1280x800."""
    raw = os.environ.get(DESKTOP_ENV) or ""
    match = re.match(r"^(\d{3,5})x(\d{3,5})", raw.strip())
    if not match:
        return DEFAULT_DESKTOP
    return int(match.group(1)), int(match.group(2))


def _output_text(value) -> str:
    """Đầu ra của lệnh con, dù là `str` (`text=True`) hay `bytes` (test cũ)."""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value or "")


def ensure_desktop_size() -> dict | None:
    """Đặt lại framebuffer nếu nó đã bị kéo nhỏ hơn cỡ cấu hình.

    Trả `{"from": "WxH", "to": "WxH"}` khi CÓ đặt lại, `{"from": ..., "warning": ...}`
    khi đặt lại thất bại (không ném lỗi: ảnh chụp vẫn hợp lệ, chỉ là đúng cỡ thật của
    màn hình), và `None` khi không cần làm gì.
    """
    try:
        current = screen_size()
    except (CaptureError, subprocess.SubprocessError, OSError):
        return None
    target = desktop_target()
    if current[0] >= target[0] and current[1] >= target[1]:
        return None
    mode = f"{target[0]}x{target[1]}"
    try:
        proc = _run_as_agent(["xrandr", "--output", VNC_OUTPUT, "--mode", mode], timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        return {"from": f"{current[0]}x{current[1]}", "warning": f"xrandr failed: {exc}"}
    if proc.returncode != 0:
        # F6b (đợt 9): `_run_as_agent` chạy `text=True` nên đầu ra là `str`; gọi `.decode()`
        # lên nó làm cả nhánh "đặt lại thất bại" ném AttributeError → route trả 500 trong khi
        # hợp đồng là KHÔNG BAO GIỜ ném lỗi. Nhận cả `str` lẫn `bytes`.
        detail = _output_text(proc.stderr or proc.stdout).strip()[:200]
        return {"from": f"{current[0]}x{current[1]}", "warning": f"xrandr exit {proc.returncode}: {detail}"}
    return {"from": f"{current[0]}x{current[1]}", "to": mode}


def _attach_desktop_note(result: dict, note: dict | None) -> dict:
    if note:
        result = dict(result)
        result["desktopRestored" if "to" in note else "desktopWarning"] = note
    return result


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


def browser_debugger_url(*, timeout: int = 10) -> str:
    """`webSocketDebuggerUrl` CẤP BROWSER (không phải cấp page) — dùng để mở kết nối
    `Browser.getWindowForTarget` khi phát hiện DevTools docked (element-selector §7-B2).

    CHỈ dùng nội bộ để mở WebSocket — KHÔNG BAO GIỜ đưa ra endpoint public.
    """
    try:
        with urllib.request.urlopen(f"{CDP_ENDPOINT}/json/version", timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
        raise CaptureError(
            f"CDP 9222 chưa sẵn sàng (Chromium desktop chưa mở qua box-chromium?): {error}",
            status_code=502,
        )
    url = payload.get("webSocketDebuggerUrl")
    if not url:
        raise CaptureError("CDP không trả webSocketDebuggerUrl cấp browser.", status_code=502)
    return url


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
def _capture_window(spec: dict, fmt: str, *, session: str = None, step=None) -> dict:
    win = resolve_window(spec)
    _check_size(win["w"], win["h"])
    path = _new_path("window", _key_with_label(f"window-{win['id']}", spec), fmt, session=session, step=step)
    with _X11_LOCK:
        if _count_active_records() > 0:
            raise _conflict(
                "Có record X11 đang quay — tạm thời không thể raise/chụp cửa sổ X11 (stop record trước)"
            )
        _raise_window(win["id"])
        _run_import("-window", win["id"], str(path), fmt)
    return _image_result(path, fmt, "window", "x11", win["w"], win["h"])


def _capture_screen(fmt: str, *, session: str = None, step=None, label: str = None) -> dict:
    width, height = screen_size()
    _check_size(width, height)
    path = _new_path("screen", _key_with_label("screen", {"label": label}), fmt, session=session, step=step)
    with _X11_LOCK:
        _run_import("-window", "root", str(path), fmt)
    return _image_result(path, fmt, "screen", "x11", width, height)


def _capture_tab(spec: dict, fmt: str, *, session: str = None, step=None) -> dict:
    tab = resolve_tab(spec)
    if not tab.get("webSocketDebuggerUrl"):
        raise CaptureError("Tab không có webSocketDebuggerUrl — CDP bất thường.", status_code=500)
    path = _new_path("tab", _key_with_label(f"tab-{tab['id'][:24]}", spec), fmt, session=session, step=step)
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


def capture(spec: dict, default_format: str = "png", *, session: str = None, step=None,
            tool_call_id: str = None) -> dict:
    kind = spec.get("kind", "screen")
    fmt = spec.get("format", default_format) or default_format
    if fmt not in SUPPORTED_IMAGE_FORMATS:
        raise _invalid(f"format phải là một trong {SUPPORTED_IMAGE_FORMATS}")
    if kind == "window":
        result = (_capture_window(spec, fmt, session=session, step=step)
                  if _session_id(session) is not None else _capture_window(spec, fmt))
    elif kind == "tab":
        result = (_capture_tab(spec, fmt, session=session, step=step)
                  if _session_id(session) is not None else _capture_tab(spec, fmt))
    elif kind == "screen":
        result = (_capture_screen(fmt, session=session, step=step, label=spec.get("label"))
                  if _session_id(session) is not None
                  else _capture_screen(fmt, label=spec.get("label")))
    else:
        raise _invalid("kind phải là window/tab/screen")
    # Theo phiên thì khử trùng lặp + ghi chỉ mục; không theo phiên (đường gọi cũ) thì giữ
    # nguyên hành vi cũ, không chạm đĩa thêm.
    if _session_id(session) is not None:
        result = _finish_image(result, session=session, step=step, tool_call_id=tool_call_id)
    return result


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


def _probe_video(path) -> dict:
    """Kiểm file video bằng ffprobe: `{verified, playable, duration, error}`.

    `verified=False` khi KHÔNG chạy được ffprobe (thiếu gosu/ffprobe, quá hạn) — khi đó không
    biết file tốt hay hỏng. `verified=True, playable=False` là ffprobe ĐÃ chạy và từ chối file
    (ví dụ "moov atom not found"): bản ghi chưa hoàn tất, không được báo `ok`.
    """
    try:
        proc = _run_as_agent(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration", "-of", "csv=p=0", str(path)],
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"verified": False, "playable": None, "duration": None,
                "error": f"{type(exc).__name__}: {exc}"[:FFMPEG_LOG_TAIL_CHARS]}
    text = (proc.stdout or "").strip()
    try:
        value = float(text)
    except ValueError:
        value = None
    duration = value if value is not None and value > 0 else None
    error = (proc.stderr or "").strip()[:FFMPEG_LOG_TAIL_CHARS] if isinstance(proc.stderr, str) else ""
    returncode = proc.returncode if isinstance(proc.returncode, int) else 0
    playable = returncode == 0 and duration is not None
    return {"verified": True, "playable": playable, "duration": duration,
            "error": error or (None if playable else f"ffprobe exit {returncode}, output {text[:80]!r}")}


def _video_duration_sec(path) -> float | None:
    """Đo thời lượng video THỰC bằng ffprobe, không dùng wall-clock.

    Wall-clock sai với bản ghi tự dừng bằng `-t`: ffmpeg thoát sau N giây nhưng
    agent có thể reap muộn (hàng chục giây), khiến `durationSec` bị thổi phồng.
    Trả về None khi không đọc được.
    """
    return _probe_video(path)["duration"]


def _ffmpeg_log_tail(entry: dict) -> str | None:
    log_path = entry.get("ffmpegLog")
    if not log_path:
        return None
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return text[-FFMPEG_LOG_TAIL_CHARS:].strip() or None


def _record_finished_entry(entry: dict) -> dict:
    path = Path(entry["path"])
    probe = _probe_video(path)
    duration = probe["duration"]
    item = {
        "recordingId": entry["recordingId"],
        "kind": entry["kind"],
        "target": entry.get("target"),
        "path": entry["path"],
        "durationSec": None,
        "sizeBytes": _file_size(path),
        "finished": True,
        "verified": probe["verified"],
    }
    process = entry.get("process")
    returncode = getattr(process, "returncode", None)
    if isinstance(returncode, int):
        item["exitCode"] = returncode
    if entry.get("stopSignals"):
        item["stopSignals"] = list(entry["stopSignals"])
    if probe["verified"] and not probe["playable"]:
        # ffprobe đã chạy và từ chối file: KHÔNG lấy wall-clock làm thời lượng (đó là thứ khiến
        # bản cũ trả `durationSec: 24.01` cho một file 2 giây không đọc được).
        item.update({
            "ok": False,
            "errorCode": "RECORDING_INCOMPLETE",
            "error": ("Bản ghi không đọc được (ffprobe từ chối file); không có video hoàn tất. "
                      + (probe["error"] or "")).strip(),
        })
        tail = _ffmpeg_log_tail(entry)
        if tail:
            item["ffmpegLog"] = tail
        return item
    if duration is None:
        # ffprobe không chạy được: không kiểm được, giữ ước lượng wall-clock và nói rõ `verified`.
        started_at = float(entry.get("startedAt", time.time()))
        duration = max(0.0, time.time() - started_at)
    item["durationSec"] = round(float(duration), 2)
    if returncode == -signal.SIGKILL:
        # MP4 phân mảnh vẫn đọc được tới fragment cuối, nhưng đuôi (≤ 1 GOP) có thể mất.
        item["forcedKill"] = True
    return item


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
        finished = _record_finished_entry(entry)
        finished.setdefault("ok", True)
        _remember_finished(finished)
        _index_record(finished, entry)


def _spawn_ffmpeg(args: list[str], log_path: Path | None = None) -> subprocess.Popen:
    # Không PIPE để ffmpeg không thể block vì đầy pipe khi chạy dài: stderr vào file log (nếu
    # mở được) hoặc DEVNULL. `-nostdin`: ffmpeg không đọc stdin kế thừa của ide-proxy.
    stderr = subprocess.DEVNULL
    handle = None
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(log_path, "ab")
            stderr = handle
        except OSError:
            handle = None
    try:
        return subprocess.Popen(
            _as_agent_argv(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args]),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
        )
    finally:
        if handle is not None:
            handle.close()


def _record_output_args(framerate: int, max_duration: int, path: Path) -> list[str]:
    """Đuôi argv ffmpeg chung cho record window/screen: encoder + MP4 phân mảnh + `-t`."""
    return [
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-g", str(max(1, framerate * RECORD_GOP_SECONDS)),
        "-movflags", RECORD_MOVFLAGS, "-flush_packets", "1",
        "-t", str(max_duration),
        str(path),
    ]


def record_start(spec: dict, *, session: str = None, step=None, tool_call_id: str = None) -> dict:
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

    record_id = _new_record_id()
    log_path = FFMPEG_LOG_DIR / f"{record_id}.log"
    with _X11_LOCK:
        if _count_active_records() >= MAX_CONCURRENT_RECORDS:
            raise _conflict(
                f"Đã đạt {MAX_CONCURRENT_RECORDS} bản ghi đồng thời — stop bớt rồi thử lại"
            )
        if kind == "window":
            win = resolve_window(spec)
            _check_size(win["w"], win["h"])
            path = _new_path("window", f"window-{win['id']}", "mp4", session=session, step=step)
            _raise_window(win["id"])
            proc = _spawn_ffmpeg([
                "-f", "x11grab", "-framerate", str(framerate),
                "-window_id", win["id"], "-video_size", f"{win['w']}x{win['h']}",
                "-i", DISPLAY,
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                *_record_output_args(framerate, max_duration, path),
            ], log_path)
            target = {"kind": "window", "windowId": win["id"]}
        elif kind == "screen":
            width, height = screen_size()
            _check_size(width, height)
            path = _new_path("screen", "screen", "mp4", session=session, step=step)
            proc = _spawn_ffmpeg([
                "-f", "x11grab", "-framerate", str(framerate),
                "-video_size", f"{width}x{height}", "-i", DISPLAY,
                "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                *_record_output_args(framerate, max_duration, path),
            ], log_path)
            target = {"kind": "screen"}
        else:
            raise _invalid("kind phải là window/tab/screen")

    _register(record_id, {
        "recordingId": record_id,
        "kind": kind,
        "target": target,
        "path": str(path),
        "process": proc,
        "pid": proc.pid,
        "startedAt": time.time(),
        "maxDurationSec": max_duration,
        "session": _session_id(session),
        "step": step,
        "toolCallId": tool_call_id,
        "ffmpegLog": str(log_path),
    })
    return {
        "ok": True,
        "recordingId": record_id,
        "path": str(path),
        "format": "mp4",
        "framerate": framerate,
        "startedAt": int(time.time() * 1000),
    }


def _signal_and_wait(proc: subprocess.Popen, sig, timeout: float, sent: list, started: float) -> bool:
    """Gửi `sig` rồi chờ tối đa `timeout` giây; True khi tiến trình đã thoát."""
    try:
        proc.send_signal(sig)
        sent.append({"signal": signal.Signals(sig).name, "atSec": round(time.monotonic() - started, 3)})
    except (ProcessLookupError, AttributeError, OSError):
        pass
    try:
        proc.wait(timeout=timeout)
        return True
    except subprocess.TimeoutExpired:
        return False


def record_stop(recording_id: str) -> dict:
    with _RECORDS_LOCK:
        entry = _RECORDS.get(recording_id)
        finished = _FINISHED_RECORDS.get(recording_id)
    if not entry:
        if finished:
            # Đã tự thoát (hết `-t`) và bị reap trước lời stop: trả đúng kết quả đã kiểm thay vì
            # 404, để chủ phiên không kẹt quyền sở hữu một bản ghi không còn chạy.
            return {**finished, "alreadyFinished": True}
        raise _not_found("Không tìm thấy recordingId đang chạy")

    proc: subprocess.Popen = entry["process"]
    sent: list[dict] = []
    started = time.monotonic()
    exited = proc.poll() is not None
    # Đường mềm SIGINT (ffmpeg ghi trailer), rồi SIGTERM, cuối cùng SIGKILL. MP4 phân mảnh nên
    # cả khi phải kill, file vẫn đọc được tới fragment cuối; `_record_finished_entry` kiểm lại.
    for sig, wait in ((signal.SIGINT, RECORD_STOP_SIGINT_WAIT),
                      (signal.SIGTERM, RECORD_STOP_SIGTERM_WAIT),
                      (signal.SIGKILL, RECORD_STOP_SIGKILL_WAIT)):
        if exited:
            break
        exited = _signal_and_wait(proc, sig, wait, sent, started)
    if not exited:
        raise CaptureError("Không dừng được tiến trình ffmpeg.", status_code=500)
    entry["stopSignals"] = sent
    entry["stopSec"] = round(time.monotonic() - started, 3)

    with _RECORDS_LOCK:
        _RECORDS.pop(recording_id, None)

    result = _record_finished_entry(entry)
    result.setdefault("ok", True)
    result["stopSec"] = entry["stopSec"]
    _remember_finished(result)
    _index_record(result, entry)
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


# Chokepoint DUY NHẤT cho khối `target` của /__box/inspect-element (element-selector
# §10.1). Allow-list — KHÔNG bao giờ `{**tab}` / `dict(tab)` / `tab.copy()` /
# `"target": tab` / `result.update(tab)` ở bất kỳ đâu khác trong inspect_element.py
# hay browser_capture.py. Cần thêm trường thì sửa DUY NHẤT tuple này.
_INSPECT_TARGET_FIELDS = ("windowId", "windowTitle", "targetId")


def _public_inspect_target(win: dict, tab: dict) -> dict:
    return {
        "windowId": str(win.get("id") or ""),
        "windowTitle": str(win.get("title") or ""),
        "targetId": str(tab.get("targetId") or tab.get("id") or ""),
    }


def dispatch_list_tabs() -> dict:
    return {"tabs": [_public_tab(tab) for tab in list_tabs()]}


def dispatch_capture(target: dict, output: str = "file", session: str = None, step=None,
                     tool_call_id: str = None) -> dict:
    """Điểm vào của ide-proxy: chụp, kèm phiên/bước khi harness gửi (mặc định `None` = như cũ)."""
    note = ensure_desktop_size() if (target or {}).get("kind", "screen") == "screen" else None
    if _session_id(session) is not None:
        result = capture(target, session=session, step=step, tool_call_id=tool_call_id)
    else:
        # Không có phiên thì gọi y hệt bản cũ: mọi chỗ gọi/mock cũ không phải biết tham số mới.
        result = capture(target)
    if output == "base64":
        import base64
        path = Path(result["path"])
        result["data"] = base64.b64encode(path.read_bytes()).decode("ascii")
    return _attach_desktop_note(result, note)


def dispatch_record_start(target: dict, session: str = None, step=None,
                          tool_call_id: str = None) -> dict:
    note = ensure_desktop_size() if (target or {}).get("kind", "screen") == "screen" else None
    if _session_id(session) is not None:
        started = record_start(target, session=session, step=step, tool_call_id=tool_call_id)
    else:
        started = record_start(target)
    return _attach_desktop_note(started, note)


def dispatch_record_stop(recording_id: str) -> dict:
    return record_stop(recording_id)


def dispatch_record_status() -> dict:
    return record_status()


def dispatch_captures_prune(session: str = None, dry_run: bool = False) -> dict:
    """Dọn ảnh/ghi hình theo trần F2 (route `POST /__box/captures/prune` cho người vận hành)."""
    if _session_files is None:
        raise CaptureError("session_files.py chưa có trong container — chưa dọn được ảnh.",
                           status_code=503)
    return _prune_captures(session=session, dry_run=bool(dry_run))
