#!/usr/bin/env python3
"""Op nhật ký phiên cho worker trong box — `session_ensure`, `journal_append`, `checkpoint_write`.

Mô-đun này là **mặt gọi** của `session_files.py`: `worker.py` (được gửi nội tuyến qua
`docker exec`) và mọi chỗ khác trong box gọi đúng bốn hàm ở đây thay vì tự nối đường dẫn hay tự
mở file. Đường dây tích hợp (chép đúng chữ này khi nối vào `worker.py`):

    import sys
    sys.path.insert(0, '/usr/local/bin')          # box: session_files.py + session_ops.py ở đây
    import session_ops
    ...
    if name in session_ops.OPS:
        return session_ops.run_op(name, args)     # KHÔNG BAO GIỜ ném — trả {'is_error': True, ...}

Bốn op:

| op | args | trả về |
|---|---|---|
| `session_ensure` | `{session, root?, role?, parent?, goal?}` | `{ok, created, sessionFile, dir, meta}` |
| `journal_append` | `{session, record}` hoặc `{session, kind, text, seq?, …}` | `{ok, relPath, mdPath, lines, seq, id}` |
| `checkpoint_write` | `{session, messages, numbers?, note?, journalRecord?}` | `{ok, status, checkpointNumber, file, md, messagesBytes}` |
| `captures_prune` | `{session?, captureRoot?, root?, dryRun?, protect?, updateIndex?}` | `{ok, removedFiles, removedBytes, pinned}` |
| `uploads_prune` | `{session?, uploadRoot?, root?, dryRun?, protect?, updateIndex?}` | `{ok, removedFiles, removedBytes, pinned}` |

Luật của tầng này — **một lỗi ghi file không bao giờ được giết một lượt** (kế hoạch đợt 20,
"trung thực khi hỏng"): mọi handler **ném** `SessionFilesError` (có `code` để ánh xạ thẳng thành
`CHECKPOINT_FILE_FAILED` / `JOURNAL_DEGRADED`), và `run_op` là mặt không bao giờ ném để chỗ gọi
trong một lượt chỉ việc `emit(sid, 'notice', ...)` rồi đi tiếp.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import session_files  # noqa: E402  (import sau khi vá sys.path — cùng thư mục, cùng bản phát hành)
import upload_files  # noqa: E402  (cùng thư mục: retention cho `.uploaded_artifacts`, D-6)
from session_files import SessionFilesError  # noqa: E402

# Bản ghi `X:` ghim mỗi lượt dọn dẹp — **một** bản ghi cho cả lượt, không bao giờ một dòng
# cho mỗi file đã xoá (một lượt dọn 200 file sẽ biến nhật ký thành bảng kê rác).
PRUNE_RECORD_KIND = "blocker"
PRUNE_RECORD_STATUS = "done"
PRUNE_RECORD_ACTOR = "box-retention"
PRUNE_RECORD_MARKER_NOTE = "dọn ảnh/ghi hình theo trần F2"


def _require(args: dict, key: str) -> str:
    value = str((args or {}).get(key) or "").strip()
    if not value:
        raise SessionFilesError(f"thiếu tham số `{key}`", code="SESSION_FILES_BAD_ARGS")
    return value


def implicit_id(kind: str, sid8: str, seq: int, data: dict = None) -> str:
    """Mã cho bản ghi khi chỗ gọi không gửi kèm — `P:` lấy từ slug + phiên bản, còn lại `<dấu>:<sid8>-<n>`.

    Bản kế hoạch **không** gắn với phiên (`P:long-task-journal@v2`), nên nếu rơi vào nhánh
    `<dấu>:<sid8>-<n>` thì cùng một kế hoạch ở hai phiên sẽ thành hai mã khác nhau — đúng thứ
    mà bảng `P:` sinh ra để tránh.
    """
    info = data if isinstance(data, dict) else {}
    if kind == "plan":
        slug = str(info.get("slug") or info.get("identity") or "").strip().lower()
        slug = re.sub(r"[^a-z0-9-]", "-", slug).strip("-")[:80]
        raw = str(info.get("version", 1)).lstrip("vV")
        version = int(raw) if raw.isdigit() and int(raw) >= 1 else 1
        if slug:
            return f"P:{slug}@v{version}"
    return f"{session_files.KIND_MARKER.get(kind, '?')}:{sid8}-{seq}"


def _paths(args: dict):
    """Bộ đường dẫn của phiên từ args của op (chấp nhận `root` để test/đa gốc)."""
    return session_files.session_paths(args.get("root"), _require(args, "session"),
                                       sid8=args.get("sid8"))


# ---------------------------------------------------------------------------
# session_ensure
# ---------------------------------------------------------------------------
def op_session_ensure(args: dict) -> dict:
    """Tạo thư mục phiên + `session.json` một lần (lười — gọi ở lần ghi đầu tiên, không lúc tạo phiên)."""
    paths = _paths(args)
    meta = {"role": args.get("role"), "parent": args.get("parent"), "goal": args.get("goal"),
            "workspace": args.get("workspace")}
    result = session_files.session_ensure(paths, meta)
    if args.get("updateIndex"):
        try:
            session_files.index_update(paths.root, sid=paths.sid, meta=result.get("meta"),
                                       status=args.get("status"))
        except SessionFilesError:
            pass  # chỉ mục là bản phụ: hỏng chỉ mục không được làm hỏng việc tạo thư mục
    return result


# ---------------------------------------------------------------------------
# journal_append
# ---------------------------------------------------------------------------
def op_journal_append(args: dict) -> dict:
    """Ghim một bản ghi vào `journal.jsonl` rồi dựng lại `journal.md`.

    Bản ghi do harness dựng (`agent_core/journal.py::record`) và mang sẵn mã + `seq`; op này chỉ
    điền `session`/`sid8` nếu thiếu, rồi ghi đúng một dòng.
    """
    paths = _paths(args)
    item = args.get("record")
    if not isinstance(item, dict):
        item = {
            "kind": args.get("kind"),
            "text": args.get("text"),
            "status": args.get("status"),
            "seq": args.get("seq"),
            "id": args.get("id"),
            "turn": args.get("turn"),
            "step": args.get("step"),
            "actor": args.get("actor") or "agent",
            "refs": args.get("refs") or [],
            "evidence": args.get("evidence") or [],
            "data": args.get("data") or {},
        }
    body = {key: value for key, value in item.items() if value is not None}
    body.setdefault("ts", session_files.utc_now_iso())
    body.setdefault("timestamp", body["ts"])
    body["session"] = body.get("session") or paths.sid
    body["sid8"] = body.get("sid8") or paths.sid8
    if not body.get("seq"):
        body["seq"] = len(session_files.journal_rows(paths)) + 1
    if not body.get("id"):
        body["id"] = implicit_id(str(body.get("kind") or ""), paths.sid8, body["seq"],
                                 body.get("data"))

    result = session_files.journal_append(paths, body)
    if args.get("updateIndex", True) and str(body.get("kind")) in ("task", "plan", "checkpoint", "blocker"):
        try:
            session_files.index_update(paths.root, sid=paths.sid, item=body,
                                       status=str(body.get("status") or "") or None)
        except SessionFilesError:
            pass
    return result


# ---------------------------------------------------------------------------
# checkpoint_write
# ---------------------------------------------------------------------------
def op_checkpoint_write(args: dict) -> dict:
    """Ghi cặp `ck-<sid8>-NNN.json`/`.md` cho transcript trước nén.

    Gọi **sau khi** hàng SQLite đã được ghi (đúng thứ tự của F3): nếu tầng file hỏng thì bản
    transcript vẫn còn trong bảng `checkpoints`, và chỗ gọi hạ lỗi xuống `notice`
    `CHECKPOINT_FILE_FAILED` rồi vẫn tiến hành nén — không thì phiên chết ngay tại trần ngữ cảnh.
    """
    paths = _paths(args)
    messages = args.get("messages")
    if not isinstance(messages, list):
        raise SessionFilesError("`messages` phải là danh sách tin nhắn",
                                code="CHECKPOINT_FILE_FAILED")
    numbers = args.get("numbers") if isinstance(args.get("numbers"), dict) else {}
    result = session_files.checkpoint_write(paths, messages, numbers, note=args.get("note"))
    record = args.get("journalRecord")
    if isinstance(record, dict) and record:
        # Cặp file đã ghi xong trước khi tới đây. Lỗi của DÒNG nhật ký không được xoá kết quả đó:
        # nếu để ngoại lệ bay ra, `run_op` vứt cả kết quả — chỗ gọi tưởng không có file nào và
        # ghim `CHECKPOINT_FILE_FAILED` sai (đúng ca đã xảy ra khi bản ghi thiếu `text`).
        try:
            item = dict(record)
            item.setdefault("kind", "checkpoint")
            item.setdefault("status", "degraded" if result.get("status") == "degraded" else "recorded")
            item["session"] = item.get("session") or paths.sid
            item["sid8"] = item.get("sid8") or paths.sid8
            item["id"] = item.get("id") or f"C:{paths.sid8}-{result.get('checkpointNumber')}"
            # Số đo của chính lần nén (số tin nhắn trước/sau, cửa sổ, model) đi cùng DÒNG nhật ký,
            # không chỉ nằm trong hàng SQLite: người mở `journal.jsonl` phải đọc được lần nén đó đo
            # bằng gì mà không phải sang bảng khác.
            numbers_out = dict(numbers)
            numbers_out.update(item.get("numbers") or {})
            numbers_out.setdefault("checkpointNumber", result.get("checkpointNumber"))
            numbers_out.setdefault("messageCount", result.get("messageCount"))
            numbers_out.setdefault("messagesBytes", result.get("messagesBytes"))
            item["numbers"] = numbers_out
            data_out = dict(item.get("data") or {})
            # Con trỏ tới CHÍNH cặp file vừa ghi: đọc `journal.jsonl` phải biết mở file nào, chứ
            # không phải đoán theo thứ tự tới.
            for key, value in (("relPath", result.get("relPath")),
                               ("mdRelPath", result.get("mdRelPath")),
                               ("checkpointNumber", result.get("checkpointNumber")),
                               ("messagesBytes", result.get("messagesBytes"))):
                if value is not None:
                    data_out.setdefault(key, value)
            if data_out:
                item["data"] = data_out
            if result.get("status") == "degraded":
                item.setdefault("note", result.get("note"))
            result["journal"] = op_journal_append({"session": paths.sid, "root": args.get("root"),
                                                   "record": item})
        except SessionFilesError as exc:
            result["journal"] = {"ok": False, "code": exc.code or "JOURNAL_DEGRADED",
                                 "error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# captures_prune
# ---------------------------------------------------------------------------
def op_captures_prune(args: dict) -> dict:
    """Một lượt dọn ảnh/ghi hình, và **một** bản ghi `X:` cho cả lượt (số file, số byte).

    Chủ nhà gọi được qua route `POST /__box/captures/prune` (người vận hành) hoặc để tiến trình
    ghi ảnh tự gọi mỗi `CAPTURE_EVICT_EVERY = 20` lần ghi.
    """
    # `captureRoot` = gốc ảnh, `root` = gốc lịch sử (mặc định `.session-history`): hai gốc khác
    # nhau nên không bao giờ suy cái này từ cái kia.
    capture_root = args.get("captureRoot")
    history_root = args.get("root")
    report = session_files.retention(capture_root, session=args.get("session"),
                                     protect=args.get("protect"), dry_run=bool(args.get("dryRun")))
    pinned: list[str] = []
    session = str(args.get("session") or "").strip().lower()
    if report["removedFiles"] and session and not report["dryRun"]:
        paths = session_files.session_paths(history_root, session, sid8=args.get("sid8"))
        body = {
            "kind": PRUNE_RECORD_KIND,
            "status": PRUNE_RECORD_STATUS,
            "actor": PRUNE_RECORD_ACTOR,
            "text": (f"{PRUNE_RECORD_MARKER_NOTE}: bỏ {report['removedFiles']} file / "
                     f"{report['removedBytes']} B (còn {report['keptFiles']} file / "
                     f"{report['keptBytes']} B)."),
            "numbers": {"removedFiles": report["removedFiles"], "removedBytes": report["removedBytes"],
                        "keptFiles": report["keptFiles"], "keptBytes": report["keptBytes"]},
            "data": {"origin": PRUNE_RECORD_ACTOR, "removed": report["removed"][:50]},
        }
        written = op_journal_append({"session": session, "root": history_root,
                                     "sid8": args.get("sid8"), "record": body,
                                     "updateIndex": bool(args.get("updateIndex"))})
        pinned.append(str(written.get("id") or ""))
    report["pinned"] = [item for item in pinned if item]
    return report


# ---------------------------------------------------------------------------
# uploads_prune
# ---------------------------------------------------------------------------
def op_uploads_prune(args: dict) -> dict:
    """Dọn tệp người dùng tải lên (`.uploaded_artifacts`) — trần 200 tệp / 500 MiB (D-6).

    Ghim **một** hàng `X:` cho cả lượt, y như `op_captures_prune`. Hàng `X:` do `upload_files.prune`
    ghi (nó cũng là nơi duy nhất gọi `unlink`), ở đây chỉ chuyển tham số và giữ nguyên khuôn trả về
    `{ok, removedFiles, removedBytes, pinned}` mà `worker.py` đã biết.
    """
    return upload_files.prune(
        args.get("uploadRoot"),
        session=args.get("session"),
        history_root=args.get("root"),
        sid8=args.get("sid8"),
        dry_run=bool(args.get("dryRun")),
        protect=args.get("protect"),
        update_index=bool(args.get("updateIndex")),
    )


# ---------------------------------------------------------------------------
# Đường gọi chung
# ---------------------------------------------------------------------------
OPS = {
    "session_ensure": op_session_ensure,
    "journal_append": op_journal_append,
    "checkpoint_write": op_checkpoint_write,
    "captures_prune": op_captures_prune,
    "uploads_prune": op_uploads_prune,
}


def execute(name: str, args: dict = None) -> dict:
    """Chạy một op; **ném** `SessionFilesError` khi op lạ hoặc khi ghi file hỏng."""
    handler = OPS.get(str(name or "").strip())
    if handler is None:
        raise SessionFilesError(f"op lạ: {name!r} (chỉ nhận {sorted(OPS)})",
                                code="SESSION_FILES_BAD_OP")
    return handler(dict(args or {}))


def run_op(name: str, args: dict = None) -> dict:
    """Mặt **không bao giờ ném** cho `worker.py`: hỏng thì trả `{'is_error': True, 'code': …}`.

    Cùng khuôn với `worker.py::execute` khi nó hỏng (`{'is_error': True, 'error': …}`), nên chỗ
    gọi cũ xử lý được ngay mà không phải biết op này khác op kia ở đâu.
    """
    try:
        return execute(name, args)
    except SessionFilesError as exc:
        return {"ok": False, "is_error": True, "code": exc.code, "error": exc.message,
                "details": exc.details}
    except Exception as exc:  # phòng xa: op lạ về sau không được làm sập worker
        return {"ok": False, "is_error": True, "code": "SESSION_FILES_FAILED", "error": str(exc)}


def main(argv=None) -> int:
    """CLI: đọc JSON `{'name'|'op', 'args', 'session'}` từ stdin, in JSON ra stdout (cho `docker exec`).

    `worker.py` (cùng thư mục trong box) đọc yêu cầu theo khuôn
    `{'name': …, 'args': {…}, 'session': …}` — `session` nằm **ngoài** `args` vì mọi op của worker
    đều nhận nó như một tham số riêng (`execute(name, args, session)`). Nhận luôn `session` (và
    `root`, `captureRoot`) ở tầng ngoài rồi hạ xuống `args` để chỗ nối không phải viết thêm một
    dòng chuyển đổi — chỉ cần `run_op(request['name'], {**request['args'], 'session': request['session']})`
    là đủ, và nếu quên thì CLI vẫn đúng.
    """
    raw = sys.stdin.read() if (argv is None or not argv) else " ".join(argv)
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        payload = {}
    name = payload.get("name") or payload.get("op")
    args = dict(payload.get("args") or {})
    for key in ("session", "root", "captureRoot", "sid8"):
        if not args.get(key) and payload.get(key):
            args[key] = payload[key]
    result = run_op(name, args)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover — chỉ chạy trong box
    raise SystemExit(main())
