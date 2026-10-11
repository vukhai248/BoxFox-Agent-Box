#!/usr/bin/env python3
"""Thư mục riêng cho mỗi phiên trong box: `session.json`, nhật ký, và bản transcript trước nén.

Vì sao có mô-đun này (đo trên máy chủ nhà 2026-09-21):

- Transcript trước nén của **cả** lịch sử box chỉ tồn tại trong một cột SQLite: 22 hàng
  `checkpoints` = 17 967 616 B, hàng lớn nhất 3 170 519 B, và `sessions.messages` lớn nhất
  6 424 279 B. Đọc được thì phải có SQL, grep thì không, và một hàng hỏng là mất cả đoạn.
- Bên máy chủ nhà, đúng loại dữ liệu đó sống thành file (110 file `.jsonl` = 425 913 101 B,
  32 file nén = 28 162 763 B) — nên bản ghi thành file đã được chứng minh ở quy mô đó.
- `grep -c unlink|retention|ttl|prune|cleanup` trong `capture.py`/`ide-proxy.py`/`workspace_files.py`
  = **0**: box chưa bao giờ dọn ảnh, nên `captures/screen/` đã 375 file / 113 MB mà không ai
  đếm. Thêm đường ghi thì phải thêm đường dọn, cùng một chỗ.

Cấu trúc một phiên (đúng "một mã, bốn bề mặt" của đợt 20):

    <root>/<sid8>/session.json          ghi một lần, không ghi đè
    <root>/<sid8>/journal.jsonl         append-only, 1 bản ghi = 1 dòng
    <root>/<sid8>/journal.md            bản người đọc, cũ → mới, ≤ 400 dòng cuối
    <root>/<sid8>/checkpoints/ck-<sid8>-NNN.json   khuôn {timestamp, message_count, messages}
    <root>/<sid8>/checkpoints/ck-<sid8>-NNN.md     bản người đọc của chính transcript đó

Mô-đun này THUẦN (stdlib, không DB, không gọi tiến trình ngoài) để test được bằng thư mục tạm và
để `worker.py`/`ide-proxy.py`/`capture.py` đều import được nó trong box. Mọi hàm công khai **ném**
`SessionFilesError` khi hỏng; người gọi trong một lượt chạy phải bắt và hạ xuống `notice` — không
bao giờ để lỗi ghi file giết một lượt (quy tắc "trung thực khi hỏng" của kế hoạch đợt 20).
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Vị trí + trần (mọi con số ở đây là trần có tên, chủ nhà chỉnh sau)
# ---------------------------------------------------------------------------
AGENT_UID = 1000
AGENT_GID = 1000

WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "/home/agent/workspace"))
SESSION_HISTORY_DIRNAME = ".session-history"
# Thư mục đã có sẵn từ `box-entrypoint.sh:15` (chmod 0750, chown 1000:1000) — dùng lại chứ
# không tạo thêm `.sessions/`: một thư mục đã có chủ thì đừng đẻ thư mục thứ hai cùng nghĩa.
SESSION_HISTORY_DIR = Path(
    os.environ.get("SESSION_HISTORY_DIR", str(WORKSPACE_ROOT / SESSION_HISTORY_DIRNAME))
)
CAPTURE_ROOT = Path(
    os.environ.get("CAPTURE_ROOT", str(WORKSPACE_ROOT / ".generated_artifacts" / "captures"))
)
SESSION_JSON_NAME = "session.json"
JOURNAL_JSONL_NAME = "journal.jsonl"
JOURNAL_MD_NAME = "journal.md"
CHECKPOINTS_DIRNAME = "checkpoints"
INDEX_NAME = "INDEX.json"

# Trần file transcript: hàng lớn nhất hiện có 3 170 519 B, `sessions.messages` lớn nhất
# 6 424 279 B → 8 MiB phủ hết thực tế và vẫn là một file mở được bằng `less`/`jq`.
CHECKPOINT_FILE_MAX_BYTES = 8 * 1024 * 1024
# Tầng file là **bản đọc được**, tầng bảng là **bản đầy đủ**: 40 cặp file/phiên là đủ để đọc
# lại lịch sử nén, còn mọi hàng `checkpoints` vẫn nằm nguyên trong SQLite.
CHECKPOINT_KEEP_PER_SESSION = 40
CHECKPOINT_MD_MAX_CHARS = 200_000
SUMMARY_MESSAGE_CHARS = 2000
JOURNAL_MD_MAX_LINES = 400
JOURNAL_MD_LINE_CHARS = 300
JOURNAL_MD_MAX_TEXT_CHARS = 200
JOURNAL_TEXT_MAX_CHARS = 1000

SID8_LEN = 8
SID8_LEN_ON_COLLISION = 12
SESSION_ID_RE = re.compile(r"^[0-9a-f]{8,32}$")

# Cùng bộ tám dấu với `agentbox/agent_core/journal.py` (harness). Hai bản là bắt buộc vì box
# không import được gói Python của harness — chúng bị khoá với nhau bằng test
# `backend/tests/unit/test_journal.py::VocabularyMirrorTest`.
KIND_MARKER = {
    "task": "T", "plan": "P", "step": "S", "decision": "D",
    "evidence": "E", "checkpoint": "C", "fact": "F", "blocker": "X",
}

# Chính sách dọn ảnh/ghi hình (F2). Đĩa box còn ~132 GB trống — trần 4 GiB không phải vì thiếu
# chỗ mà để một vòng lặp chụp ảnh không bao giờ biến box thành cái đĩa đầy.
CAPTURE_KEEP_PER_KIND = 200
CAPTURE_MAX_BYTES_PER_SESSION = 512 * 1024 * 1024
CAPTURE_MAX_BYTES_BOX = 4 * 1024 * 1024 * 1024
RECORD_KEEP_PER_SESSION = 40
CAPTURE_EVICT_EVERY = 20
CAPTURE_DEDUP_LRU = 256
RECORD_SUFFIXES = (".mp4",)

_MD_DEGRADED_PREFIX = "> Transcript vượt trần 8 MiB — bản đầy đủ chỉ nằm trong bảng checkpoints"


class SessionFilesError(Exception):
    """Lỗi tầng file của phiên — người gọi hạ xuống `notice`, không để chết lượt.

    Mang sẵn `code` để chỗ bắt lỗi ánh xạ thẳng thành mã `notice` của kế hoạch
    (`CHECKPOINT_FILE_FAILED`, `JOURNAL_DEGRADED`, …) mà không phải đoán theo câu chữ.
    """

    code = "SESSION_FILES_FAILED"

    def __init__(self, message, *, code: str = None, details: dict = None):
        super().__init__(str(message))
        self.message = str(message)
        self.code = code or type(self).code
        self.details = dict(details or {})

    def as_notice(self, **extra) -> dict:
        """Khuôn `notice` để harness `emit` thẳng — lý do luôn đi kèm, không nói mơ hồ."""
        payload = {"code": self.code, "message": self.message}
        payload.update(self.details)
        payload.update(extra)
        return payload


class CheckpointTooLarge(SessionFilesError):
    code = "CHECKPOINT_FILE_FAILED"


class InvalidSessionId(SessionFilesError):
    code = "SESSION_FILES_BAD_ID"


class PathOutsideHistory(SessionFilesError):
    code = "SESSION_FILES_BAD_PATH"


# ---------------------------------------------------------------------------
# Đường dẫn
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class SessionPaths:
    """Mọi đường dẫn của một phiên, tính một lần — không nơi nào tự nối chuỗi bằng tay."""

    root: Path
    sid: str
    sid8: str
    dir: Path
    session_json: Path
    journal_jsonl: Path
    journal_md: Path
    checkpoints_dir: Path

    def rel(self, path) -> str:
        """Đường dẫn tương đối so với gốc lịch sử — thứ được ghi vào `evidence`/INDEX."""
        try:
            return str(Path(path).relative_to(self.root))
        except ValueError:
            return str(path)


def utc_now_iso(moment: float = None) -> str:
    """ISO-8601 UTC, mili-giây, hậu tố `Z` — cùng khuôn với `/memory/sessions/*.jsonl`."""
    now = datetime.now(timezone.utc) if moment is None else datetime.fromtimestamp(moment, timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def sid8_of(sid: str, root=None) -> str:
    """8 hex đầu của session id — kèm luật đụng độ 8 → 12 hex (D6 của đợt 20).

    Chỉ khi biết `root` mới phát hiện được đụng độ (phải *nhìn thấy* `<sid8>/session.json` của
    phiên khác). 8 hex đầu trùng nhau là chuyện hiếm nhưng box này chạy hàng nghìn phiên, và
    hậu quả của một lần trùng là **hai phiên ghi vào cùng một thư mục** — hỏng bản ghi theo
    cách không thể dựng lại, nên rẻ hơn nhiều là kiểm tra.
    """
    value = str(sid or "").strip().lower()
    if not SESSION_ID_RE.match(value):
        raise InvalidSessionId(f"session id phải là hex thường 8..32 ký tự, nhận {sid!r}")
    if root is None:
        return value[:SID8_LEN]
    root_path = Path(root)
    for width in (SID8_LEN, SID8_LEN_ON_COLLISION, 16, 20, 24, 28, 32):
        candidate = value[:width]
        owner = _session_json_owner(root_path / candidate)
        if owner is None or owner == value:
            return candidate
    raise SessionFilesError(f"không tách được thư mục phiên cho {value} (trùng khoá ở mọi độ dài)")


def session_paths(root=None, sid: str = None, *, sid8: str = None) -> SessionPaths:
    """Dựng bộ đường dẫn của một phiên, có chặn thoát khỏi gốc lịch sử."""
    root_path = Path(root or SESSION_HISTORY_DIR)
    value = str(sid or "").strip().lower()
    if not SESSION_ID_RE.match(value):
        raise InvalidSessionId(f"session id phải là hex thường 8..32 ký tự, nhận {sid!r}")
    short = str(sid8 or "").strip().lower() or sid8_of(value, root=root_path)
    if not SESSION_ID_RE.match(short):
        raise InvalidSessionId(f"sid8 phải là hex thường 8..32 ký tự, nhận {sid8!r}")
    base = root_path / short
    _assert_inside(root_path, base)
    return SessionPaths(
        root=root_path, sid=value, sid8=short, dir=base,
        session_json=base / SESSION_JSON_NAME,
        journal_jsonl=base / JOURNAL_JSONL_NAME,
        journal_md=base / JOURNAL_MD_NAME,
        checkpoints_dir=base / CHECKPOINTS_DIRNAME,
    )


def _assert_inside(root: Path, target: Path) -> None:
    """Chặn mọi đường dẫn thoát khỏi `<root>/.session-history` (kể cả qua symlink)."""
    root_res = Path(root).resolve()
    target_res = Path(target).resolve()
    if target_res == root_res or root_res in target_res.parents:
        return
    raise PathOutsideHistory(f"đường dẫn {target} nằm ngoài gốc lịch sử {root}")


def _session_json_owner(directory: Path) -> str | None:
    """Session id đang sở hữu một thư mục (`None` nếu chưa có hoặc file hỏng)."""
    body = _read_json(directory / SESSION_JSON_NAME)
    if isinstance(body, dict):
        value = str(body.get("session") or "").strip().lower()
        return value or None
    return None


def _read_json(path: Path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ensure_dir(directory: Path) -> None:
    """Tạo thư mục (lười — chỉ khi có dòng đầu tiên) rồi hạ quyền về `agent`.

    `chown`/`chmod` best-effort: chạy trong test (không phải root, uid 1000 không tồn tại) vẫn
    phải đi tiếp — quyền sai là chuyện của người vận hành, không phải lý do để mất một bản ghi.
    """
    Path(directory).mkdir(parents=True, exist_ok=True)
    try:
        if hasattr(os, 'chown'):
            os.chown(directory, AGENT_UID, AGENT_GID)
        os.chmod(directory, 0o750)
    except (OSError, AttributeError):
        pass


def _chown_agent(path: Path) -> None:
    try:
        if hasattr(os, 'chown'):
            os.chown(path, AGENT_UID, AGENT_GID)
        os.chmod(path, 0o640)
    except (OSError, AttributeError):
        pass


def _safe_unlink(path: Path) -> None:
    try:
        Path(path).unlink()
    except OSError:
        pass


def _write_atomic(path: Path, text: str) -> int:
    """Ghi qua file tạm cùng thư mục rồi `os.replace` — người đọc không bao giờ thấy file nửa vời.

    Tên tạm có pid để hai lần ghi song song (hai phiên khác nhau thì khác thư mục, nhưng một
    lần ghi lại của cùng phiên vẫn có thể chồng) không giẫm lên nhau.
    """
    target = Path(path)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = text.encode("utf-8")
    try:
        fd = os.open(str(tmp), os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o640)
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(target))
    finally:
        _safe_unlink(tmp)
    _chown_agent(target)
    return len(payload)


# ---------------------------------------------------------------------------
# session.json — ghi một lần, không ghi đè
# ---------------------------------------------------------------------------
def session_ensure(paths: SessionPaths, meta: dict = None) -> dict:
    """Tạo thư mục phiên + `session.json` (lười, một lần). Không bao giờ ghi đè.

    Vì sao **lười** và không tạo lúc `POST /api/agent/sessions`: 150 phiên hiện có, nhưng 87
    phiên dưới 10 tin nhắn — tạo thư mục ở thời điểm tạo phiên là đẻ 150 thư mục gần rỗng, và
    biến một lỗi đĩa thành lỗi tạo phiên (một chỗ hỏng mới cho đường vào quan trọng nhất của box).
    """
    info = dict(meta or {})
    _ensure_dir(paths.dir)
    _ensure_dir(paths.checkpoints_dir)
    existing = _read_json(paths.session_json)
    if isinstance(existing, dict):
        return {"ok": True, "created": False, "session": paths.sid, "sid8": paths.sid8,
                "dir": str(paths.dir), "sessionFile": str(paths.session_json), "meta": existing}

    body = {
        "session": paths.sid,
        "sid8": paths.sid8,
        "role": str(info.get("role") or "orchestrator"),
        "parent": info.get("parent"),
        "created": utc_now_iso(),
        "goal": info.get("goal"),
        "workspace": str(info.get("workspace") or WORKSPACE_ROOT),
    }
    tmp = paths.dir / f".{SESSION_JSON_NAME}.{os.getpid()}.tmp"
    created = False
    try:
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.link(str(tmp), str(paths.session_json))  # link = "tạo nếu chưa có", nguyên tử
            created = True
        except FileExistsError:
            created = False
    finally:
        _safe_unlink(tmp)
    _chown_agent(paths.session_json)
    return {"ok": True, "created": created, "session": paths.sid, "sid8": paths.sid8,
            "dir": str(paths.dir), "sessionFile": str(paths.session_json), "meta": body}


# ---------------------------------------------------------------------------
# journal.jsonl — append-only, một bản ghi một dòng
# ---------------------------------------------------------------------------
def journal_append(paths: SessionPaths, item: dict) -> dict:
    """Ghi thêm **một dòng** vào `journal.jsonl` rồi dựng lại `journal.md`.

    Ghi bằng `os.open(..., O_APPEND)`: hai tiến trình ghi cùng file (vòng lượt của harness và
    tiến trình dọn dẹp trong box) không cắt dòng của nhau — điều mà `"a"` của Python không bảo
    đảm khi mỗi bên tự đệm riêng.
    """
    if not isinstance(item, dict):
        raise SessionFilesError("bản ghi nhật ký phải là dict", code="JOURNAL_DEGRADED")
    kind = str(item.get("kind") or "")
    if kind not in KIND_MARKER:
        raise SessionFilesError(f"kind lạ trong nhật ký: {kind!r}", code="JOURNAL_DEGRADED")
    text = str(item.get("text") or "").strip()
    if not text:
        raise SessionFilesError("bản ghi nhật ký phải có chữ", code="JOURNAL_DEGRADED")
    body = dict(item)
    if len(text) > JOURNAL_TEXT_MAX_CHARS:
        # Cắt và **nói ra** đã cắt: nhật ký là bản trích, nhưng một bản trích im lặng thì người
        # đọc sau tưởng đó là toàn bộ câu chuyện.
        note = dict(body.get("data") or {})
        note["truncated"] = True
        note["textChars"] = len(text)
        body["text"] = text[:JOURNAL_TEXT_MAX_CHARS]
        body["data"] = note

    _ensure_dir(paths.dir)
    line = json.dumps(body, ensure_ascii=False, separators=(", ", ": "))
    payload = (line.replace("\n", " ").replace("\r", " ") + "\n").encode("utf-8")
    fd = None
    try:
        fd = os.open(str(paths.journal_jsonl), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
        written = os.write(fd, payload)
    except OSError as exc:
        raise SessionFilesError(f"không ghi được nhật ký: {exc}", code="JOURNAL_DEGRADED",
                                details={"path": str(paths.journal_jsonl)})
    finally:
        if fd is not None:
            os.close(fd)
    _chown_agent(paths.journal_jsonl)

    rows = journal_rows(paths)
    md = render_journal_md(rows, sid8=paths.sid8, total=len(rows))
    _write_atomic(paths.journal_md, md)
    return {"ok": True, "path": str(paths.journal_jsonl), "mdPath": str(paths.journal_md),
            "relPath": paths.rel(paths.journal_jsonl), "seq": body.get("seq"),
            "id": body.get("id"), "bytes": written, "lines": len(rows)}


def journal_rows(paths: SessionPaths) -> list[dict]:
    """Các bản ghi của phiên, cũ → mới; dòng hỏng bị bỏ qua chứ không làm mất cả file."""
    try:
        raw = paths.journal_jsonl.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def render_journal_md(rows, *, max_lines: int = JOURNAL_MD_MAX_LINES, sid8: str = None,
                      total: int = None) -> str:
    """Bản `journal.md` cũ → mới, tất định, ≤ `max_lines` dòng.

    Bản sao thuật toán của `agentbox/agent_core/journal.py::rollup_md` — box không import được
    gói của harness, nên hai bản bị khoá với nhau bằng test (cùng đầu vào ⇒ cùng đầu ra).
    """
    ceiling = max(2, int(max_lines))
    items = [item for item in (rows or []) if isinstance(item, dict)]
    count = len(items) if total is None else int(total)
    header = f"# Nhật ký phiên {sid8 or (items[-1].get('sid8') if items else '') or '?'} — {count} bản ghi"
    lines = [header, "<!-- máy đọc: journal.jsonl (append-only, đầy đủ); file này là bản 400 dòng cuối -->"]
    capacity = ceiling - len(lines)
    if capacity <= 0:
        return "\n".join(lines[:ceiling]) + "\n"
    kept = items[-capacity:]
    dropped = count - len(kept)
    if dropped > 0:
        # Dòng ghi chú chiếm một chỗ của chính nó — không chừa thì nó đẩy bản ghi mới nhất ra ngoài.
        lines.append(f"… [bỏ {dropped} bản ghi cũ nhất khỏi bản .md — bản đầy đủ ở journal.jsonl]")
        room = capacity - 1
        kept = items[-room:] if room > 0 else []
    lines.extend(_md_line(item) for item in kept)
    return "\n".join(lines[:ceiling]) + "\n"


def _md_line(item: dict) -> str:
    kind = str(item.get("kind") or "")
    marker = KIND_MARKER.get(kind, "?")
    code = str(item.get("id") or f"{marker}:{item.get('sid8') or '?'}-{item.get('seq') or '?'}")
    text = " ".join(str(item.get("text") or "").split())
    if len(text) > JOURNAL_MD_MAX_TEXT_CHARS:
        text = text[:JOURNAL_MD_MAX_TEXT_CHARS - 1].rstrip() + "…"
    line = f"- {item.get('ts') or '?'} · {code} · {item.get('status') or '-'} · {text}"
    if len(line) > JOURNAL_MD_LINE_CHARS:
        line = line[:JOURNAL_MD_LINE_CHARS - 1].rstrip() + "…"
    refs = item.get("refs") or []
    if refs:
        line += " · refs: " + ",".join(str(ref) for ref in refs)
    return line


# ---------------------------------------------------------------------------
# checkpoints/ck-<sid8>-NNN.json|.md — transcript trước nén, bản đọc được
# ---------------------------------------------------------------------------
def checkpoint_next_number(paths: SessionPaths) -> int:
    """Số kế tiếp của cặp `ck-<sid8>-NNN`, đếm **theo thư mục** (RULE-1/RULE-29 của đợt 20)."""
    highest = 0
    pattern = re.compile(rf"^ck-{re.escape(paths.sid8)}-(\d+)\.json$")
    try:
        names = [entry.name for entry in paths.checkpoints_dir.iterdir()]
    except OSError:
        names = []
    for name in names:
        found = pattern.match(name)
        if found:
            highest = max(highest, int(found.group(1)))
    return highest + 1


def checkpoint_names(paths: SessionPaths, number: int) -> tuple[str, str]:
    """`(tên .json, tên .md)` — 3 chữ số, bắt đầu `001`; qua 999 thì dài thêm một chữ số."""
    stem = f"ck-{paths.sid8}-{int(number):03d}"
    return f"{stem}.json", f"{stem}.md"


def checkpoint_write(paths: SessionPaths, messages, numbers: dict = None, *, note: str = None) -> dict:
    """Ghi transcript trước nén thành **cặp file** (`.json` cho máy, `.md` cho người).

    Hai luật không được vi phạm:

    1. **Không bao giờ có `.json` nửa vời** — ghi qua file tạm rồi `os.replace`. Một bản
       transcript bị cắt cụt còn tệ hơn không có bản nào, vì nó *trông như* bản đầy đủ.
    2. **Vượt trần thì nói thẳng** — `CHECKPOINT_FILE_MAX_BYTES = 8 MiB` (hàng lớn nhất hiện có
       3 170 519 B): vượt trần thì **không** ghi `.json`, và dòng đầu của `.md` chỉ người đọc về
       bảng `checkpoints`. Bảng SQLite vẫn giữ bản đầy đủ — tầng file chỉ là bản đọc được.

    Khuôn `.json` đúng bản ghi của chủ nhà (`timestamp`, `message_count`, `messages`) vì đó là
    thứ mắt người đọc quen; riêng `messages` được serialize **y hệt** `session_store.checkpoint`
    (`json.dumps(messages, ensure_ascii=False)`) nên số byte của nó bằng đúng `length(messages)`
    trong SQLite — số đó trả về ở `messagesBytes` để bản ghi `C:` so được mà không phải mở file.
    """
    if not isinstance(messages, list):
        raise SessionFilesError("messages phải là danh sách tin nhắn", code="CHECKPOINT_FILE_FAILED")
    nums = dict(numbers or {})
    try:
        number = int(nums.get("checkpointNumber") or checkpoint_next_number(paths))
    except (TypeError, ValueError):
        number = checkpoint_next_number(paths)
    if number < 1:
        number = 1
    json_name, md_name = checkpoint_names(paths, number)
    json_path = paths.checkpoints_dir / json_name
    md_path = paths.checkpoints_dir / md_name
    _assert_inside(paths.root, json_path)

    frame = {"timestamp": utc_now_iso(), "message_count": len(messages), "messages": messages}
    payload = json.dumps(frame, ensure_ascii=False)
    size = len(payload.encode("utf-8"))
    messages_bytes = len(json.dumps(messages, ensure_ascii=False).encode("utf-8"))
    row_id = nums.get("rowId") or nums.get("checkpointRowId")

    if size > CHECKPOINT_FILE_MAX_BYTES:
        reason = (f"transcript {size} B vượt trần {CHECKPOINT_FILE_MAX_BYTES} B — "
                  f"không ghi .json, bảng checkpoints giữ bản đầy đủ")
        degraded = f"{_MD_DEGRADED_PREFIX} (hàng #{row_id if row_id is not None else '?'})."
        try:
            _ensure_dir(paths.checkpoints_dir)
            _write_atomic(md_path, render_checkpoint_md(messages, numbers=nums, degraded_prefix=degraded))
        except OSError as exc:
            raise SessionFilesError(f"không ghi được bản .md của checkpoint: {exc}",
                                    code="CHECKPOINT_FILE_FAILED", details={"number": number})
        return {"ok": True, "status": "degraded", "checkpointNumber": number,
                "file": None, "md": str(md_path), "relPath": paths.rel(md_path),
                "mdRelPath": paths.rel(md_path),
                "bytes": size, "messagesBytes": messages_bytes, "messageCount": len(messages),
                "note": note or reason}

    try:
        _ensure_dir(paths.checkpoints_dir)
        _write_atomic(json_path, payload)
        _write_atomic(md_path, render_checkpoint_md(messages, numbers=nums, note=note))
    except OSError as exc:
        raise SessionFilesError(f"không ghi được file checkpoint: {exc}",
                                code="CHECKPOINT_FILE_FAILED", details={"number": number})
    removed = _prune_checkpoints(paths)
    return {"ok": True, "status": "recorded", "checkpointNumber": number,
            "file": str(json_path), "md": str(md_path), "relPath": paths.rel(json_path),
            "mdRelPath": paths.rel(md_path),
            "bytes": size, "messagesBytes": messages_bytes, "messageCount": len(messages),
            "evicted": removed}


def _prune_checkpoints(paths: SessionPaths) -> list[str]:
    """Giữ `CHECKPOINT_KEEP_PER_SESSION` cặp file mới nhất; cũ nhất bỏ trước, theo số thứ tự."""
    pairs: dict[int, list[Path]] = {}
    pattern = re.compile(rf"^ck-{re.escape(paths.sid8)}-(\d+)\.(json|md)$")
    try:
        entries = sorted(paths.checkpoints_dir.iterdir())
    except OSError:
        return []
    for entry in entries:
        found = pattern.match(entry.name)
        if found:
            pairs.setdefault(int(found.group(1)), []).append(entry)
    removed: list[str] = []
    for number in sorted(pairs, reverse=True)[CHECKPOINT_KEEP_PER_SESSION:]:
        for path in pairs[number]:
            try:
                path.unlink()
                removed.append(paths.rel(path))
            except OSError:
                pass
    return removed


# ---------------------------------------------------------------------------
# Bản .md của một transcript trước nén — người đọc được, trần 200 000 ký tự
# ---------------------------------------------------------------------------
def render_checkpoint_md(messages, *, numbers: dict = None, note: str = None,
                         degraded_prefix: str = None,
                         ceiling: int = CHECKPOINT_MD_MAX_CHARS) -> str:
    """Mỗi tin nhắn một mục `## [<i>] <role> — <ts>`; ảnh và tool thành một dòng, không base64.

    Vì sao phải chặn base64 ngay ở đây: một ảnh chụp CUA nhúng thẳng vào ngữ cảnh là hàng trăm
    KB (đo trên máy chủ nhà: một nhiệm vụ 30 lần chụp đội lên 1 051 631 ký tự). Bản `.md` là thứ
    người ta mở bằng `less` sau sự cố — nhét base64 vào đó là tự tay phá thứ vừa dựng.
    """
    nums = dict(numbers or {})
    cap = max(1000, int(ceiling))
    parts: list[str] = []
    if degraded_prefix:
        parts.append(degraded_prefix)
    parts.append(f"# Transcript trước nén — {len(messages)} tin nhắn — {utc_now_iso()}")
    if note:
        parts.append(f"> {note}")
    if nums:
        parts.append("> số đo: " + json.dumps(nums, ensure_ascii=False, sort_keys=True))
    size = sum(len(part) + 1 for part in parts)
    cut = False
    for index, message in enumerate(messages, 1):
        block = _message_block(index, message)
        if size + len(block) > cap:
            cut = True
            break
        parts.append(block)
        size += len(block) + 1
    if cut:
        parts.append("… [cắt; bản đầy đủ ở file .json]")
    return "\n".join(parts) + "\n"


def _message_block(index: int, message) -> str:
    """Một mục `## [<i>] <role> — <ts>` + thân đã cắt theo `SUMMARY_MESSAGE_CHARS`."""
    if not isinstance(message, dict):
        return f"## [{index}] ?\n{_clip_text(json.dumps(message, ensure_ascii=False, default=str))}"
    role = str(message.get("role") or message.get("type") or "?")
    stamp = message.get("ts") or message.get("timestamp") or ""
    head = f"## [{index}] {role}" + (f" — {stamp}" if stamp else "")
    lines = [head]
    if message.get("name"):
        lines.append(f"[name] {message['name']}")
    content = message.get("content")
    if isinstance(content, str):
        lines.append(_clip_text(content))
    elif isinstance(content, list):
        for part in content:
            lines.append(_part_line(part))
    elif content is not None:
        lines.append(_clip_text(json.dumps(content, ensure_ascii=False, default=str)))
    calls = message.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            args = str(function.get("arguments") or "")
            name = str(function.get("name") or call.get("name") or "tool")
            lines.append(f"[tool] {name} {_clip_one_line(args, 80)} → {len(args)} ký tự")
    return "\n".join(lines)


def _part_line(part) -> str:
    """Một phần nội dung thành một dòng — ảnh không bao giờ đi vào file `.md` dạng base64."""
    if not isinstance(part, dict):
        return _clip_text(str(part))
    kind = str(part.get("type") or "")
    if kind in ("image_url", "image"):
        return _image_line(part)
    text = part.get("text")
    if text is None:
        text = json.dumps(part, ensure_ascii=False, default=str)
    return _clip_text(str(text))


def _image_line(part: dict) -> str:
    """`[image 1280×800 — <đường dẫn>]`, hoặc chỉ loại ảnh khi không có đường dẫn nào."""
    width = part.get("width") or ((part.get("source") or {}).get("width")
                                  if isinstance(part.get("source"), dict) else None)
    height = part.get("height") or ((part.get("source") or {}).get("height")
                                    if isinstance(part.get("source"), dict) else None)
    where = part.get("path") or part.get("artifact") or part.get("url")
    if not where:
        source = part.get("image_url")
        where = source.get("url") if isinstance(source, dict) else source
    text = str(where or "")
    if text.startswith("data:"):
        head, _, blob = text.partition(",")
        where = f"{head.split(';')[0]} — {len(blob)} ký tự base64 đã bỏ"
    dims = f"{width}×{height}" if width and height else "?"
    return f"[image {dims} — {where or 'không có đường dẫn'}]"


def _clip_text(text: str) -> str:
    """Cắt phần chữ theo `SUMMARY_MESSAGE_CHARS` — có dấu, không im lặng."""
    body = str(text or "")
    if len(body) <= SUMMARY_MESSAGE_CHARS:
        return body
    return body[:SUMMARY_MESSAGE_CHARS] + f"… [cắt {len(body) - SUMMARY_MESSAGE_CHARS} ký tự]"


def _clip_one_line(text: str, limit: int) -> str:
    body = " ".join(str(text or "").split())
    return body if len(body) <= limit else body[:limit - 1] + "…"


# ---------------------------------------------------------------------------
# INDEX.json — chỉ mục dùng chung của cả box (F6)
# ---------------------------------------------------------------------------
def index_read(root=None) -> dict:
    """Đọc `INDEX.json`; file thiếu/hỏng trả về chỉ mục rỗng chứ không ném."""
    body = _read_json(Path(root or SESSION_HISTORY_DIR) / INDEX_NAME)
    if not isinstance(body, dict):
        return {"updated": None, "sessions": {}, "tasks": []}
    body.setdefault("sessions", {})
    body.setdefault("tasks", [])
    if not isinstance(body.get("tasks"), list):
        body["tasks"] = []
    return body


def index_write(root=None, index: dict = None) -> dict:
    """Ghi `INDEX.json` qua file tạm + `os.replace` — cùng khuôn an toàn với mọi file khác."""
    root_path = Path(root or SESSION_HISTORY_DIR)
    _ensure_dir(root_path)
    body = dict(index or {})
    body["updated"] = body.get("updated") or utc_now_iso()
    _assert_inside(root_path, root_path / INDEX_NAME)
    _write_atomic(root_path / INDEX_NAME, json.dumps(body, ensure_ascii=False, indent=2) + "\n")
    return body


def index_update(root=None, *, sid: str = None, item: dict = None, meta: dict = None,
                 status: str = None, deleted: bool = False) -> dict:
    """Cập nhật `INDEX.json` từ một bản ghi nhật ký / một phiên.

    Khoá của `tasks` là **mã bản ghi** (`T:`, `P:`, `C:`) — cùng mã với `journal.jsonl`, hàng
    `journal`, và event stream, nên không bao giờ có chuyện bốn bề mặt bốn cách gọi tên.
    """
    root_path = Path(root or SESSION_HISTORY_DIR)
    index = index_read(root_path)
    short = None
    if sid:
        short = str(sid)[:SID8_LEN].lower()
    stamp = utc_now_iso()
    if meta is not None:
        key = short or str(meta.get("sid8") or "?")
        record = dict(index["sessions"].get(key) or {})
        record.update({k: v for k, v in meta.items() if k != "session"})
        record["session"] = meta.get("session") or record.get("session")
        record["sid8"] = key
        if status:
            record["status"] = status
        if deleted:
            record["sessionDeleted"] = True
        record["updatedAt"] = stamp
        index["sessions"][key] = record
    if isinstance(item, dict) and item:
        entry = _task_entry(item, short)
        if entry:
            _merge_task(index["tasks"], entry, stamp, deleted=deleted)
    index["updated"] = stamp
    index_write(root_path, index)
    return index


def _task_entry(item: dict, short: str = None) -> dict | None:
    """Một bản ghi `T:`/`P:`/`C:`/`X:` → một hàng trong `tasks` của chỉ mục."""
    kind = str(item.get("kind") or "")
    if kind not in ("task", "plan", "checkpoint", "blocker"):
        return None
    code = str(item.get("id") or "").strip()
    if not code:
        return None
    entry = {
        "id": code,
        "session": item.get("session"),
        "sid8": str(item.get("sid8") or short or ""),
        "role": str(item.get("actor") or ""),
        "kind": kind,
        "status": item.get("status"),
        "text": str(item.get("text") or ""),
        "updatedAt": item.get("ts") or utc_now_iso(),
        "refs": list(item.get("refs") or []),
        "evidence": list(item.get("evidence") or []),
        "blocked": str(item.get("status") or "") in ("blocked", "failed"),
    }
    plan = item.get("data") if isinstance(item.get("data"), dict) else {}
    if kind == "plan" and plan:
        entry["plan"] = {"identity": plan.get("identity") or plan.get("slug"),
                         "version": plan.get("version")}
    if kind == "checkpoint":
        entry["checkpoint"] = item.get("numbers") or {}
    return entry


def _merge_task(tasks: list, entry: dict, stamp: str, *, deleted: bool = False) -> None:
    for existing in tasks:
        if isinstance(existing, dict) and existing.get("id") == entry["id"]:
            existing.update(entry)
            if deleted:
                existing["sessionDeleted"] = True
            return
    entry["sessionDeleted"] = bool(deleted)
    tasks.append(entry)


# ---------------------------------------------------------------------------
# Chỉ mục ảnh/ghi hình của một phiên — captures/<sid8>/index.jsonl (F2)
# ---------------------------------------------------------------------------
def capture_index_append(root=None, *, sid: str = None, item: dict = None) -> dict:
    """Ghi thêm một dòng vào `captures/<sid8>/index.jsonl` (một file = một dòng).

    Chỉ mục này **không** thay bản ghi `tool_end` trong DB (vẫn giữ `artifact`/`mime`/`dimensions`
    để UI không phải đổi): nó là bản ngoài DB, để trả lời "ảnh này của phiên nào, bước nào, có
    trùng với ảnh nào không" mà không phải quét hơn 100 000 hàng `events`.
    """
    root_path = Path(root or CAPTURE_ROOT)
    value = str(sid or "").strip().lower()
    if not SESSION_ID_RE.match(value):
        raise InvalidSessionId(f"session id phải là hex thường 8..32 ký tự, nhận {sid!r}")
    short = sid8_of(value, root=root_path)
    directory = root_path / short
    _assert_inside(root_path, directory)
    _ensure_dir(directory)
    target = directory / "index.jsonl"
    payload = (json.dumps(item or {}, ensure_ascii=False, separators=(", ", ": "))
               .replace("\n", " ") + "\n").encode("utf-8")
    fd = None
    try:
        fd = os.open(str(target), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
        written = os.write(fd, payload)
    except OSError as exc:
        raise SessionFilesError(f"không ghi được chỉ mục ảnh: {exc}", code="CAPTURE_INDEX_FAILED",
                                details={"path": str(target)})
    finally:
        if fd is not None:
            os.close(fd)
    _chown_agent(target)
    return {"ok": True, "path": str(target), "relPath": _rel_to_workspace(target),
            "bytes": written, "sid8": short}


def capture_index_rows(root=None, sid: str = None) -> list[dict]:
    """Đọc chỉ mục ảnh của một phiên (dòng hỏng bị bỏ qua, không làm mất cả chỉ mục)."""
    root_path = Path(root or CAPTURE_ROOT)
    value = str(sid or "").strip().lower()
    if not SESSION_ID_RE.match(value):
        return []
    target = root_path / sid8_of(value, root=root_path) / "index.jsonl"
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except ValueError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _rel_to_workspace(path: Path) -> str:
    """Đường dẫn tương đối so với workspace — đúng khuôn `relPath` mà F2 mô tả."""
    try:
        return str(Path(path).relative_to(WORKSPACE_ROOT))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Dọn dẹp — trần có tên, cũ nhất trước, không bao giờ chạm file đang được nhắc
# ---------------------------------------------------------------------------
def retention(root=None, *, session: str = None, protect=None, dry_run: bool = False) -> dict:
    """Một lượt dọn ảnh/ghi hình, trả về **báo cáo** thay vì im lặng xoá.

    Bốn trần (F2), áp theo thứ tự từ hẹp tới rộng: `CAPTURE_KEEP_PER_KIND = 200` file/phiên/loại,
    `RECORD_KEEP_PER_SESSION = 40` file mp4/phiên, `CAPTURE_MAX_BYTES_PER_SESSION = 512 MiB`,
    `CAPTURE_MAX_BYTES_BOX = 4 GiB`. Dọn theo **mtime cũ nhất trước**.

    375 file ảnh cũ nằm phẳng trong `captures/screen/` **được giữ nguyên tại chỗ**: hơn 100 000
    hàng `events` và `sessions.messages` còn trỏ vào đường dẫn cũ, nên di chuyển chúng là làm gãy
    link trong UI; việc gán chúng về phiên là phần di trú, không phải đổi chỗ.
    """
    root_path = Path(root or CAPTURE_ROOT)
    protected = _protected_set(protect)
    entries, skipped = _capture_entries(root_path, session=session, protected=protected)
    marked: dict[str, dict] = {}

    def _mark(entry: dict) -> None:
        marked[str(entry["path"])] = entry

    def _remaining() -> list[dict]:
        return [entry for entry in entries if str(entry["path"]) not in marked]

    # 1. Trần số file theo từng (loại, phiên).
    for key in sorted({(entry["kind"], entry["sid8"]) for entry in entries}):
        bucket = sorted((e for e in _remaining() if (e["kind"], e["sid8"]) == key),
                        key=lambda e: (e["mtime"], str(e["path"])))
        for entry in bucket[:max(0, len(bucket) - CAPTURE_KEEP_PER_KIND)]:
            _mark(entry)

    # 2. Trần số file ghi hình theo phiên (mp4 tốn đĩa hơn hẳn ảnh).
    for short in sorted({entry["sid8"] for entry in entries}):
        bucket = sorted((e for e in _remaining() if e["sid8"] == short and e["record"]),
                        key=lambda e: (e["mtime"], str(e["path"])))
        for entry in bucket[:max(0, len(bucket) - RECORD_KEEP_PER_SESSION)]:
            _mark(entry)

    # 3. Trần byte theo phiên — chặn ca "một phiên chụp 3000 ảnh 1280x800".
    for short in sorted({entry["sid8"] for entry in entries}):
        bucket = sorted((e for e in _remaining() if e["sid8"] == short),
                        key=lambda e: (e["mtime"], str(e["path"])))
        total = sum(entry["bytes"] for entry in bucket)
        for entry in bucket:
            if total <= CAPTURE_MAX_BYTES_PER_SESSION:
                break
            total -= entry["bytes"]
            _mark(entry)

    # 4. Trần byte toàn box — bảo hiểm cuối, không phải vì thiếu chỗ (đĩa còn ~132 GB).
    remaining = _remaining()
    total = sum(entry["bytes"] for entry in remaining)
    for entry in sorted(remaining, key=lambda e: (e["mtime"], str(e["path"]))):
        if total <= CAPTURE_MAX_BYTES_BOX:
            break
        total -= entry["bytes"]
        _mark(entry)

    removed: list[str] = []
    removed_bytes = 0
    if not dry_run:
        for path_text, entry in marked.items():
            try:
                Path(path_text).unlink()
            except OSError:
                continue
            removed.append(entry["relPath"])
            removed_bytes += entry["bytes"]
    kept = [entry for entry in entries if str(entry["path"]) not in marked]
    return {
        "ok": True,
        "root": str(root_path),
        "dryRun": bool(dry_run),
        "removedFiles": len(removed) if not dry_run else len(marked),
        "removedBytes": removed_bytes if not dry_run else sum(e["bytes"] for e in marked.values()),
        "removed": removed if not dry_run else [e["relPath"] for e in marked.values()],
        "keptFiles": len(kept),
        "keptBytes": sum(entry["bytes"] for entry in kept),
        "skippedProtected": skipped,
        "sessions": _session_report(entries, kept),
    }


def _protected_set(protect) -> set:
    """Tập đường dẫn/tên file không bao giờ bị dọn trong lượt này."""
    out = set()
    for value in (protect or []):
        text = str(value or "").strip()
        if not text:
            continue
        out.add(text)
        out.add(Path(text).name)
        try:
            out.add(str(Path(text).resolve()))
        except OSError:
            pass
    return out


def _is_protected(path: Path, protected: set) -> bool:
    if not protected:
        return False
    for candidate in (str(path), path.name):
        if candidate in protected:
            return True
    try:
        return str(path.resolve()) in protected
    except OSError:
        return False


def _capture_entries(root: Path, *, session: str = None, protected: set = None) -> tuple[list[dict], int]:
    """Liệt kê file trong các thư mục **của phiên** (`<kind>/<sid8>/`), bỏ qua file phẳng cũ."""
    wanted = str(session or "").strip().lower()[:SID8_LEN] or None
    entries: list[dict] = []
    skipped = 0
    try:
        kind_dirs = sorted(entry for entry in root.iterdir() if entry.is_dir())
    except OSError:
        return entries, skipped
    for kind_dir in kind_dirs:
        try:
            session_dirs = sorted(entry for entry in kind_dir.iterdir() if entry.is_dir())
        except OSError:
            continue
        for session_dir in session_dirs:
            short = session_dir.name
            if not SESSION_ID_RE.match(short):
                continue
            if wanted and short[:len(wanted)] != wanted:
                continue
            try:
                files = sorted(entry for entry in session_dir.iterdir() if entry.is_file())
            except OSError:
                continue
            for path in files:
                if _is_protected(path, protected or set()):
                    skipped += 1
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                entries.append({
                    "path": path,
                    "relPath": _rel_to_workspace(path),
                    "bytes": int(stat.st_size),
                    "mtime": float(stat.st_mtime),
                    "kind": kind_dir.name,
                    "sid8": short,
                    "record": path.suffix.lower() in RECORD_SUFFIXES,
                })
    return entries, skipped


def _session_report(entries: list[dict], kept: list[dict]) -> dict:
    """Ảnh chụp nhanh theo phiên: còn bao nhiêu file/byte — để bản ghi `X:` có số mà ghi."""
    report: dict[str, dict] = {}
    for entry in entries:
        bucket = report.setdefault(entry["sid8"], {"files": 0, "bytes": 0, "keptFiles": 0, "keptBytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += entry["bytes"]
    for entry in kept:
        bucket = report.setdefault(entry["sid8"], {"files": 0, "bytes": 0, "keptFiles": 0, "keptBytes": 0})
        bucket["keptFiles"] += 1
        bucket["keptBytes"] += entry["bytes"]
    return report
