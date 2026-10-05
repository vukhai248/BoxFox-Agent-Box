"""Nhật ký tác vụ dài hơi — mô hình bản ghi, bộ tám dấu, khối "ký ức" và bản người đọc.

Vì sao có mô-đun này (đo trên máy chủ nhà 2026-09-21):

- 22 hàng `checkpoints` (17 967 616 B) gói **toàn bộ** transcript trước mỗi lần nén vào đúng
  một cột SQLite; hàng lớn nhất 3 170 519 B và `sessions.messages` lớn nhất 6 424 279 B.
  Transcript cũ nằm trong một ô TEXT thì không grep được, không mở được, không đọc được bằng
  bất cứ thứ gì ngoài SQL — mà 12/150 phiên đã từng nén.
- 87/150 phiên dưới 10 tin nhắn: phần lớn phiên không để lại dấu vết nào ngoài bảng `sessions`.
- Bên máy chủ nhà (để so): 110 file `/memory/sessions/*.jsonl` (425 913 101 B) và 32 file nén
  (28 162 763 B, 8 100 tin nhắn) — tức là bản ghi **thành file** đã sống được ở quy mô gấp trăm
  lần, còn bản ghi trong bảng thì không.

Mô-đun này THUẦN: không DB, không I/O ngoài đường dẫn được truyền vào, không import mô-đun
`agentbox.*` nào khác. Nó là **nguồn duy nhất** cho: bộ tám dấu ↔ `kind`, cách cấp mã bản ghi
(`T:`/`P:`/`S:`/`D:`/`E:`/`C:`/`F:`/`X:`), khuôn một dòng JSONL, khối ký ức chèn vào system
message, và bản `journal.md` người đọc được. Tầng file trong box (`deploy/docker/session_files.py`)
giữ một bản sao của hai hàm render vì box không import được gói Python này — hai bản đó bị khoá
với nhau bằng test `test_journal.py::RenderMirrorTest` (cùng đầu vào ⇒ cùng đầu ra, byte-đúng).

Vì sao dấu ngắn thay vì văn xuôi tự do: grep một lượt trên file lớn là ra đúng loại bản ghi; bảng
chữ cái cố định nên bản tổng hợp đọc được theo từng dấu; mã đủ ngắn để trích trong prompt
(`C:ab12cd34-2`) mà không tốn token; **một mã, bốn bề mặt** (journal.jsonl, hàng SQLite, event
stream, journal.md) nên không bao giờ lệch nhau.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Bộ tám dấu — 1:1 với `kind` (bảng F4 của kế hoạch đợt 20)
# ---------------------------------------------------------------------------
KIND_MARKER = {
    "task": "T",        # nhiệm vụ dài hơi — gốc của cây
    "plan": "P",        # một bản kế hoạch theo phiên bản
    "step": "S",        # một bước đã/đang làm
    "decision": "D",    # một quyết định đã chốt (kèm lựa chọn)
    "evidence": "E",    # bằng chứng kiểm chứng được (file+dòng, lệnh, URL, ảnh chụp)
    "checkpoint": "C",  # một lần nén + transcript trước nén
    "fact": "F",        # dữ kiện bền, đã khử trùng lặp
    "blocker": "X",     # chỗ tắc / thất bại / kết cục
}
MARKER_KIND = {marker: kind for kind, marker in KIND_MARKER.items()}
MARKERS = tuple(KIND_MARKER[kind] for kind in KIND_MARKER)
KINDS = tuple(KIND_MARKER)

# `status` hợp lệ theo từng `kind` — chốt bằng bảng chứ không bằng văn xuôi tự do, để
# người đọc máy lọc được (`status: doing`) mà không phải hiểu câu chữ.
KIND_STATUS = {
    "task": ("open", "doing", "done", "blocked"),
    "plan": ("draft", "approved", "superseded"),
    "step": ("doing", "done", "failed"),
    "decision": ("approved", "rejected", "info"),
    "evidence": ("info",),
    "checkpoint": ("recorded", "degraded"),
    "fact": ("info", "superseded"),
    "blocker": ("blocked", "failed", "resolved", "done"),
}
DEFAULT_STATUS = {
    "task": "open", "plan": "draft", "step": "doing", "decision": "info",
    "evidence": "info", "checkpoint": "recorded", "fact": "info", "blocker": "blocked",
}

# Trần chữ của một bản ghi. 1 000 ký tự ≈ 250 token: đủ một câu chuyện có số đo, nhưng
# không đủ để ai đó dán cả transcript vào nhật ký rồi biến nó thành bản sao thứ hai của
# `sessions.messages` — thứ đã có chỗ riêng.
JOURNAL_TEXT_MAX_CHARS = 1000

# Khối ký ức chèn vào system message: 4 000 ký tự ≈ 1 000 token ≈ 3 % cửa sổ 32k và
# 0,1 % cửa sổ 1M. Trần cứng, không phải "mục tiêu" — hàm render tự cắt để giữ trần.
JOURNAL_BRIEF_MAX_PER_GROUP = 8
JOURNAL_BRIEF_MAX_CHARS = 4000
JOURNAL_BRIEF_HEADER = "=== SESSION JOURNAL BRIEF (durable state rebuilt from .session-history) ==="
# Dòng thay chỗ cho một nhóm rỗng. `brief_has_items` đọc chính dòng này để phân biệt "khối có gì
# thật" với "khối chỉ có sáu tiêu đề" — nếu đổi chữ ở đây mà quên chỗ kia thì khối rỗng lại lọt
# vào system message, nên hai chỗ dùng chung một hằng số.
BRIEF_EMPTY_LINE = "- (không có bản ghi)"

# Bản `journal.md` là **bản đọc được**, không phải bản đầy đủ: 400 dòng cuối, đọc được bằng
# `tail`. Bản đầy đủ luôn là `journal.jsonl` (append-only) — không bao giờ mất dòng nào.
JOURNAL_MD_MAX_LINES = 400
JOURNAL_MD_LINE_CHARS = 300
JOURNAL_MD_MAX_TEXT_CHARS = 200

# Nhóm của khối ký ức — sáu nhóm, cố định thứ tự, luôn hiện đủ sáu kể cả khi rỗng: một
# nhóm biến mất là một câu trả lời "không biết" bị ngụy trang thành "không có gì".
BRIEF_GROUPS = (
    ("mục tiêu", "goal"),
    ("đã xong", "done"),
    ("đang làm", "doing"),
    ("đang tắc", "blocked"),
    ("việc kế tiếp", "next"),
    ("quyết định còn mở", "open_decisions"),
)

SID8_RE = re.compile(r"^[0-9a-f]{8,32}$")
# Mã bản ghi: `<dấu>:<thân>` — thân không bao giờ chứa dấu hai chấm (RULE-25 của kế hoạch
# đợt 20: tên/mã không có dấu hai chấm để `:` còn dùng được làm dấu phân cách).
ID_RE = re.compile(r"^(?P<marker>[%s]):(?P<body>[^:]{1,120})$" % "".join(MARKERS))
PLAN_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}$")
# `identity` của bản kế hoạch **không phải** slug trần: `.plans/docs/v1-docs.md` được người đọc
# nhóm thành `docs/docs` (một cấp thư mục, xem `plan_files.py`). Nếu chỉ nhận slug trần thì bản
# kế hoạch lồng thư mục viết được ra đĩa mà không ghim được `P:` — và cả LƯỢT hỏng theo, vì lỗi
# mã bản ghi ném ra từ giữa `write_plan` (bắt được thật 2026-09-21 bằng
# `test_nested_plan_target_uses_the_reader_identity_and_version`).
# Trần độ sâu là KHÔNG có, khớp đúng grammar của người đọc (`plan_files.py:_IDENTITY_RE_GROUP`,
# `plan_header.IDENTITY_PATTERN`, `runtime.PLAN_PATH_RE`) — cả ba đều là `(?:slug/)*slug`. Bản cũ
# chặn ở hai đoạn (một cấp thư mục) và đó là chỗ vỡ thật đo sống 2026-10-04: `write_plan` với
# `directory="designs/login"` ghi đúng tệp `.plans/designs/login/v1-dang-nhap-sso.md` rồi chết ở
# bước ghim `P:` vì identity ba đoạn bị từ chối — tệp nằm trên đĩa mà cả LƯỢT hỏng theo
# (`TURN_FAILED_JOURNALERROR`), đúng cái bẫy mà ghi chú trên đã cảnh báo cho trường hợp một cấp.
PLAN_IDENTITY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,78}(?:/[a-z0-9][a-z0-9-]{0,78})*$")
PLAN_ID_RE = re.compile(r"^P:(?P<slug>[a-z0-9][a-z0-9-]{0,78}(?:/[a-z0-9][a-z0-9-]{0,78})*)@v(?P<version>[0-9]{1,6})$")

BRIEF_TRUNCATED_TAIL = "\n… [cắt]"
# Chỗ chừa cho dòng "còn N bản ghi nữa": không chừa thì chính cái trần cắt mất lời nói thật.
_BRIEF_NOTE_RESERVE = 160  # dòng cuối cùng khi chạm trần ký tự — không bao giờ im lặng


class JournalError(ValueError):
    """Bản ghi không hợp lệ (kind lạ, chữ quá dài, refs không phải mã, status lạ).

    Cố ý là `ValueError`: đây là lỗi lập trình ở phía harness, không phải lỗi môi trường —
    người gọi trong một lượt chạy phải bắt và hạ xuống `notice`, không được để nó giết lượt.
    """


# ---------------------------------------------------------------------------
# Thời gian + mã định danh
# ---------------------------------------------------------------------------
def utc_now_iso(moment: float | None = None) -> str:
    """ISO-8601 UTC, mili-giây, hậu tố `Z` — cùng khuôn với `/memory/sessions/*.jsonl`."""
    now = datetime.now(timezone.utc) if moment is None else datetime.fromtimestamp(moment, timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def sid8_of(sid: str) -> str:
    """8 hex đầu của session id 32 hex — khoá thư mục/tên file của phiên.

    Đụng độ (hai phiên khác nhau cùng 8 hex đầu, xác suất ~1/4 tỉ nhưng box chạy hàng nghìn
    phiên) xử ở tầng file nơi có thể *nhìn thấy* thư mục đã tồn tại; ở đây chỉ cắt chuỗi.
    """
    value = str(sid or "").strip().lower()
    if not SID8_RE.match(value):
        raise JournalError(f"session id phải là hex thường 8..32 ký tự, nhận {sid!r}")
    return value[:8]


def mint_id(kind: str, sid8: str, seq: int, plan: dict | str | None = None) -> str:
    """Cấp mã bản ghi. Harness cấp — agent không bao giờ tự gõ mã.

    - `T:`/`S:`/`D:`/`E:`/`C:`/`F:`/`X:` → `<dấu>:<sid8>-<seq>` (ví dụ `T:ab12cd34-1`)
    - `P:` → `P:<slug>@v<n>` lấy từ `write_plan` (`identity` + `version`), ví dụ
      `P:long-task-journal@v2`. Bản kế hoạch gắn với *slug*, không với phiên: cùng một slug
      ở hai phiên vẫn là cùng một bản kế hoạch, và `@v2` mới là thứ phân biệt hai bản.
    """
    if kind not in KIND_MARKER:
        raise JournalError(f"kind lạ: {kind!r} (chỉ nhận {KINDS})")
    if kind == "plan":
        slug, version = _plan_parts(plan)
        return f"P:{slug}@v{version}"
    prefix = str(sid8 or "").strip().lower()
    if not SID8_RE.match(prefix):
        raise JournalError(f"sid8 phải là hex thường 8..32 ký tự, nhận {sid8!r}")
    if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
        raise JournalError(f"seq phải là số nguyên ≥ 1, nhận {seq!r}")
    return f"{KIND_MARKER[kind]}:{prefix}-{seq}"


def _plan_parts(plan: dict | str | None) -> tuple[str, int]:
    """Tách `(slug, version)` từ kết quả `write_plan` — chấp nhận cả dict lẫn slug trần."""
    if isinstance(plan, str):
        plan = {"identity": plan}
    if not isinstance(plan, dict):
        raise JournalError("mã `P:` cần `plan` = kết quả write_plan (identity + version)")
    slug = str(plan.get("slug") or plan.get("identity") or "").strip().lower()
    if not PLAN_IDENTITY_RE.match(slug):
        raise JournalError(
            "identity bản kế hoạch phải là kebab-case thường, có thể lồng thư mục nhiều cấp "
            f"(ví dụ `long-task-journal` hoặc `designs/login-page`), nhận {slug!r}")
    raw = plan.get("version", 1)
    try:
        version = int(str(raw).lstrip("vV"))
    except (TypeError, ValueError):
        raise JournalError(f"version phải là số nguyên, nhận {raw!r}")
    if version < 1:
        raise JournalError(f"version phải ≥ 1, nhận {version!r}")
    return slug, version


def marker_of(kind: str) -> str:
    """Dấu của một `kind` (ném `JournalError` nếu lạ) — dùng để gắn nhãn bản tổng hợp."""
    if kind not in KIND_MARKER:
        raise JournalError(f"kind lạ: {kind!r} (chỉ nhận {KINDS})")
    return KIND_MARKER[kind]


def kind_of_marker(marker: str) -> str:
    """`kind` của một dấu (`T` → `task`) — đường ngược lại, dùng khi bóc nhãn của agent."""
    key = str(marker or "").strip().upper()
    if key not in MARKER_KIND:
        raise JournalError(f"dấu lạ: {marker!r} (chỉ nhận {MARKERS})")
    return MARKER_KIND[key]


def is_record_id(value: str) -> bool:
    """Chuỗi có đúng khuôn mã bản ghi không (`T:ab12cd34-1`, `P:slug@v2`, …)."""
    return bool(ID_RE.match(str(value or "").strip()))


# ---------------------------------------------------------------------------
# Khuôn một bản ghi
# ---------------------------------------------------------------------------
def record(kind: str, text: str, *, sid: str = None, sid8: str = None, seq: int = None,
           turn: int = None, step: int = None, actor: str = "agent", status: str = None,
           refs=None, evidence=None, data=None, numbers=None, plan=None,
           ts: str = None) -> dict:
    """Dựng một bản ghi nhật ký đã kiểm — **một bản ghi = một dòng JSONL**.

    Kiểm ngay tại đây thay vì lúc ghi: một bản ghi sai khuôn lọt vào file append-only là vĩnh
    viễn (không xoá, không sửa, không đánh số lại), nên chỗ chặn phải là chỗ dựng.

    `timestamp` và `ts` là **cùng một giá trị** ISO-8601 UTC: chủ nhà đọc quen khoá
    `timestamp` (khuôn bản ghi nén của máy chủ nhà), còn bảng `journal` phía harness dùng `ts`
    (REAL, đổi sang epoch khi ghi DB). Giữ cả hai để một mã dùng chung cho bốn bề mặt mà
    không phải dịch khoá ở giữa.
    """
    if kind not in KIND_MARKER:
        raise JournalError(f"kind lạ: {kind!r} (chỉ nhận {KINDS})")
    body = text if isinstance(text, str) else str(text or "")
    body = body.strip()
    if not body:
        raise JournalError("bản ghi nhật ký phải có chữ")
    if len(body) > JOURNAL_TEXT_MAX_CHARS:
        raise JournalError(
            f"chữ bản ghi {len(body)} ký tự, vượt trần {JOURNAL_TEXT_MAX_CHARS} — "
            "nhật ký là bản trích, không phải transcript"
        )
    chosen = status or DEFAULT_STATUS[kind]
    if chosen not in KIND_STATUS[kind]:
        raise JournalError(f"status {chosen!r} không hợp lệ cho kind {kind!r} ({KIND_STATUS[kind]})")

    session = str(sid or "").strip().lower() or None
    short = str(sid8 or "").strip().lower() or (sid8_of(session) if session else None)
    if session is None and short is None and kind != "plan":
        raise JournalError("bản ghi phải có `sid` (32 hex) hoặc `sid8`")
    if short is not None and not SID8_RE.match(short):
        raise JournalError(f"sid8 phải là hex thường 8..32 ký tự, nhận {sid8!r}")
    if session is not None and not SID8_RE.match(session):
        raise JournalError(f"session id phải là hex thường 8..32 ký tự, nhận {sid!r}")

    clean_refs = _check_ids(refs, "refs")
    clean_evidence = _check_evidence(evidence)
    for name, value in (("turn", turn), ("step", step)):
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise JournalError(f"{name} phải là số nguyên ≥ 0, nhận {value!r}")

    stamp = utc_now_iso()
    if ts:
        if not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$", str(ts)):
            raise JournalError(f"ts phải là ISO-8601 UTC kết thúc bằng Z, nhận {ts!r}")
        stamp = str(ts)

    item = {
        "seq": seq if isinstance(seq, int) and not isinstance(seq, bool) else None,
        "ts": stamp,
        "timestamp": stamp,
        "kind": kind,
        "id": None,
        "session": session,
        "sid8": short,
        "turn": turn,
        "step": step,
        "actor": str(actor or "agent"),
        "text": body,
        "refs": clean_refs,
        "status": chosen,
        "evidence": clean_evidence,
        "data": dict(data) if isinstance(data, dict) else {},
    }
    if kind == "plan":
        if not plan:
            raise JournalError("bản ghi `plan` cần `plan` = kết quả write_plan (identity + version)")
        item["id"] = mint_id("plan", short or "", 0, plan)
    elif item["seq"]:
        item["id"] = mint_id(kind, short, item["seq"])
    if isinstance(numbers, dict) and numbers:
        # Số đo theo từng loại bản ghi (số tin nhắn, ước lượng token, số file đã dọn…).
        # Không bao giờ trộn vào `text`: chữ để người đọc, số để máy lọc.
        item["numbers"] = {key: numbers[key] for key in numbers}
    return item


def _check_ids(values, field: str) -> list[str]:
    """`refs` phải là **danh sách mã**, không phải câu văn — nếu không thì không nối được cây."""
    if values in (None, ""):
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise JournalError(f"{field} phải là danh sách mã bản ghi")
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not is_record_id(text):
            raise JournalError(f"{field} chứa {value!r} không phải mã bản ghi (dạng T:<sid8>-<n>)")
        out.append(text)
    return out


def _check_evidence(values) -> list[dict]:
    """Bằng chứng là **con trỏ kiểm chứng được** (file+dòng, lệnh, URL, ảnh), không phải lời kể."""
    if values in (None, ""):
        return []
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise JournalError("evidence phải là danh sách đối tượng có `type`")
    out: list[dict] = []
    for value in values:
        if not isinstance(value, dict) or not str(value.get("type") or "").strip():
            raise JournalError(f"evidence phải là dict có khoá `type`, nhận {value!r}")
        out.append({str(key): item for key, item in value.items()})
    return out


def dumps(item: dict) -> str:
    """Một dòng JSONL: không `\\n` bên trong, tiếng Việt giữ nguyên (không escape)."""
    line = json.dumps(item, ensure_ascii=False, separators=(", ", ": "))
    return line.replace("\n", " ").replace("\r", " ").strip()


def parse_line(line: str) -> dict | None:
    """Đọc một dòng JSONL, trả `None` nếu dòng hỏng — một dòng hỏng không được làm mất cả file."""
    text = (line or "").strip()
    if not text:
        return None
    try:
        item = json.loads(text)
    except (TypeError, ValueError):
        return None
    return item if isinstance(item, dict) else None


def load_lines(path: str | Path) -> list[dict]:
    """Đọc cả file JSONL, bỏ qua dòng hỏng theo đúng tinh thần append-only của nhật ký."""
    target = Path(path)
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return [item for item in (parse_line(line) for line in raw.splitlines()) if item is not None]


def append_line(path: str | Path, item: dict) -> int:
    """Ghi thêm một dòng bằng `O_APPEND`, trả số byte đã ghi.

    `O_APPEND` (không `"a"` của Python) là để hai tiến trình ghi cùng file — điều thật sự xảy ra
    giữa vòng lượt của harness và tiến trình dọn dẹp trong box — không bao giờ cắt dòng của nhau.
    """
    payload = (dumps(item) + "\n").encode("utf-8")
    target = Path(path)
    fd = None
    try:
        fd = os.open(str(target), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o640)
        written = os.write(fd, payload)
    finally:
        if fd is not None:
            os.close(fd)
    return written


def row_payload(item: dict) -> dict:
    """Phần dư của bản ghi khi lưu vào bảng `journal` (`kind`/`text` đã có cột riêng).

    Bảng chỉ có `(session_id, kind, text, payload, created)`, còn bản ghi JSONL giàu hơn — hàm
    này giữ nguyên phần giàu đó trong một ô JSON thay vì làm mỏng bản ghi cho vừa cột.
    """
    keep = ("id", "sid8", "turn", "step", "actor", "status", "refs", "evidence", "data", "numbers")
    return {key: item[key] for key in keep if key in item}


def to_db_ts(item: dict) -> float:
    """`ts` ISO của bản ghi → epoch (REAL) cho cột `created` của bảng `journal`."""
    raw = str(item.get("ts") or "")
    try:
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


# ---------------------------------------------------------------------------
# Khối "ký ức" — trạng thái bền rút từ nhật ký, chèn vào system message
# ---------------------------------------------------------------------------
def group_rows(rows) -> dict[str, list[dict]]:
    """Chia bản ghi vào sáu nhóm của khối ký ức (mới nhất trước, mỗi nhóm một danh sách).

    `C:` (nén) xếp vào **đã xong**: một lần nén đã hoàn tất và chính là dấu vết cho biết
    transcript trước đó đã được cất thành file. Không thêm nhóm thứ bảy — sáu nhóm là trần
    để khối ký ức còn đọc được trong một lần liếc.

    Một ngoại lệ có tên (C4 vòng 22): hàng **vé mơ hồ** (`kind='fact'` mang
    `data.identityAmbiguityTicket`) xếp vào **đang tắc**. Vé là dấu vết của một lần đăng ký
    kế hoạch BỊ TỪ CHỐI: việc chỉ chạy tiếp khi model gửi lại nguyên văn, nên nó không phải
    "đã xong", cũng không phải một mục tiêu mới — nó là một việc đang dừng. Các hàng `fact`
    khác vẫn **không** vào nhóm nào: một dữ kiện thường không thuộc sáu nhóm, còn vé thì phải
    tới được model, nếu không hàng `F:` chỉ nằm trong file mà không ai đọc.
    """
    groups: dict[str, list[dict]] = {key: [] for _, key in BRIEF_GROUPS}
    for item in reversed(list(rows or [])):  # JSONL là cũ → mới; khối ký ức muốn mới trước
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        status = str(item.get("status") or "")
        if kind == "task" and status in ("open", "doing"):
            groups["goal"].append(item)
        elif kind == "plan" and status == "approved":
            groups["goal"].append(item)
        elif kind == "checkpoint" or status == "done":
            if kind in ("checkpoint", "task", "step", "blocker", "plan"):
                groups["done"].append(item)
        elif kind == "decision" and status in ("info", "approved"):
            groups["open_decisions"].append(item)
        if kind in ("task", "step") and status == "doing":
            groups["doing"].append(item)
        if kind == "blocker" and status in ("blocked", "failed"):
            groups["blocked"].append(item)
        if kind == "fact" and str((item.get("data") or {}).get("identityAmbiguityTicket") or "").strip():
            groups["blocked"].append(item)  # C4 vòng 22 — vé mơ hồ là việc ĐANG TẮC
        if isinstance(item.get("data"), dict) and str(item["data"].get("next") or "").strip():
            groups["next"].append(item)
    return groups


def _brief_line(item: dict, limit: int = 160) -> str:
    """Một dòng của khối ký ức: `- <mã> · <chữ>` (cắt chữ, giữ mã nguyên vẹn)."""
    marker = KIND_MARKER.get(str(item.get("kind") or ""), "?")
    code = str(item.get("id") or f"{marker}:?")
    text = " ".join(str(item.get("text") or "").split())
    if len(text) > limit:
        text = text[:limit - 1].rstrip() + "…"
    extra = ""
    if isinstance(item.get("data"), dict) and str(item["data"].get("next") or "").strip():
        extra = " → kế tiếp: " + " ".join(str(item["data"]["next"]).split())[:80]
    return f"- {code} · {text}{extra}"


def brief_text(rows, *, limit_per_group: int = JOURNAL_BRIEF_MAX_PER_GROUP,
               max_chars: int = JOURNAL_BRIEF_MAX_CHARS) -> str:
    """Khối "ký ức" chèn vào system message: trạng thái bền của phiên, ≤ `max_chars` ký tự.

    Vì sao chèn vào **system message** (chứ không phải một tin nhắn mới): cùng kỹ thuật với
    `=== OWNER-CONFIGURED DIRECTIVES ===` — khối này là *hướng dẫn*, nên nó không được trôi vào
    lịch sử hội thoại rồi bị chính bộ nén cắt mất. Dựng lại ở bước đầu mỗi lượt và ngay sau mỗi
    lần nén là đủ: giữa hai thời điểm đó danh sách tin nhắn còn nguyên.

    Hai lượt dựng, vì hai thứ tự ưu tiên khác nhau: lượt đầu giữ cả dòng "(không có bản ghi)" cho
    nhóm rỗng (đọc là biết ngay nhóm nào không có gì); nếu chật chỗ thì lượt hai bỏ các dòng đó
    trước, và **luôn** chừa chỗ cho dòng nói rõ đã cắt bao nhiêu bản ghi.
    """
    limit = max(1, int(limit_per_group))
    cap = max(200, int(max_chars))
    groups = group_rows(rows)
    reserve = _BRIEF_NOTE_RESERVE

    def _assemble(with_fillers: bool, budget: int) -> tuple[str, int]:
        out = [JOURNAL_BRIEF_HEADER]
        lost = 0
        for index, (label, key) in enumerate(BRIEF_GROUPS, 1):
            items = groups[key]
            out.append(f"[{index}. {label}]")
            shown = 0
            for item in items[:limit]:
                line = _brief_line(item)
                if len("\n".join(out)) + len(line) > budget:
                    break
                out.append(line)
                shown += 1
            lost += len(items) - shown
            if not shown and with_fillers:
                out.append(BRIEF_EMPTY_LINE)
        return "\n".join(out), lost

    def _note(count: int) -> str:
        return f"… (+{count} bản ghi nữa — đọc .session-history/<sid8>/journal.jsonl)"

    text, lost = _assemble(True, cap)
    if lost == 0 or len(text) + len(_note(lost)) + 1 <= cap:
        return text + ("\n" + _note(lost) if lost else "")
    text, lost = _assemble(False, cap - reserve)
    if lost:
        text += "\n" + _note(lost)
    if len(text) > cap:  # chốt cứng: trần là trần, kể cả khi mọi nhóm đều rỗng
        text = text[:cap - len(BRIEF_TRUNCATED_TAIL)] + BRIEF_TRUNCATED_TAIL
    return text


# Tên gọi theo kế hoạch (F5) — cùng một hàm, hai đường gọi, không có bản thứ hai để lệch.
journal_brief = brief_text


def brief_has_items(text) -> bool:
    """Khối ký ức có ít nhất một dòng bản ghi THẬT (không chỉ tiêu đề và dòng chỗ trống)?

    Vì sao cần: nhật ký một phiên có thể chỉ chứa các hàng **không thuộc nhóm nào** — `F:` dữ kiện
    và `E:` bằng chứng (đợt 3 vòng 22) đều cố ý không có nhóm, vì chúng để tra cứu chứ không phải
    để nhắc lại mỗi lượt. Khi đó `brief_text` vẫn dựng đủ sáu tiêu đề cùng sáu dòng "(không có bản
    ghi)", và khối vô nghĩa đó sẽ bị ghép vào system message: prompt của lượt sau khác lượt trước
    dù phiên không có gì mới để nhớ. Chỗ gọi dùng hàm này để trả `''` thay vì ghép khối rỗng.
    """
    for line in str(text or '').splitlines():
        line = line.strip()
        if line.startswith('- ') and line != BRIEF_EMPTY_LINE:
            return True
    return False


# ---------------------------------------------------------------------------
# Bản người đọc — journal.md (mới nhất ở cuối, đọc được bằng `tail`, ≤ 400 dòng)
# ---------------------------------------------------------------------------
def rollup_md(rows, *, max_lines: int = JOURNAL_MD_MAX_LINES, sid8: str = None) -> str:
    """Dựng `journal.md` từ danh sách bản ghi: cũ → mới, tất định, có trần dòng.

    Bản `.md` là **bản đọc được**, không phải bản đầy đủ: khi vượt trần thì bỏ bản ghi *cũ*
    và ghi rõ đã bỏ bao nhiêu, còn `journal.jsonl` vẫn giữ nguyên từng dòng từ đầu phiên.
    """
    ceiling = max(2, int(max_lines))
    items = [item for item in (rows or []) if isinstance(item, dict)]
    header = f"# Nhật ký phiên {sid8 or (items[-1].get('sid8') if items else '') or '?'} — {len(items)} bản ghi"
    lines = [header, "<!-- máy đọc: journal.jsonl (append-only, đầy đủ); file này là bản 400 dòng cuối -->"]
    capacity = ceiling - len(lines)
    if capacity <= 0:
        return "\n".join(lines[:ceiling]) + "\n"
    kept = items[-capacity:]
    dropped = len(items) - len(kept)
    if dropped > 0:
        # Dòng ghi chú chiếm một chỗ của chính nó — nếu không chừa, nó đẩy bản ghi MỚI NHẤT ra
        # ngoài trần, tức là bản đọc được lại thiếu đúng thứ người ta cần đọc nhất.
        lines.append(f"… [bỏ {dropped} bản ghi cũ nhất khỏi bản .md — bản đầy đủ ở journal.jsonl]")
        room = capacity - 1
        kept = items[-room:] if room > 0 else []
    lines.extend(_md_line(item) for item in kept)
    return "\n".join(lines[:ceiling]) + "\n"


def _md_line(item: dict) -> str:
    """Một dòng `.md`: `<ts> · <dấu> <mã> · <status> · <chữ>` — cùng khuôn cho mọi loại."""
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
