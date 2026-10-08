"""Nhật ký phiên — nửa **harness** của workstream A (việc A4/A5/A7).

Đo trên máy chủ nhà 2026-09-21: bản transcript trước nén **chỉ nằm trong một hàng SQLite**
(22 hàng `checkpoints` / 17 967 616 B / 12 trong 150 phiên; hàng lớn nhất 3 170 519 B) — không có
file, không có bản người đọc được. Tầng này ghi thêm hai bản nữa, và giữ đúng hai luật:

1. **Lỗi ghi không bao giờ giết một lượt.** Mọi thao tác ra file trong box đi qua `_safe()`: hỏng thì
   `emit(notice)` với mã nói rõ (`CHECKPOINT_FILE_FAILED` / `JOURNAL_DEGRADED`) rồi đi tiếp. Bảng
   `checkpoints` vẫn giữ bản đầy đủ — tầng file chỉ là bản đọc được.
2. **Một bản ghi, hai chỗ đọc.** Hàng JSONL/SQLite là nguồn để dựng lại "khối ký ức" (A5) bằng
   `journal.brief_text`, nên khối đó không phụ thuộc việc file trong box có ghi được hay không.

Đường gọi trong box là op của worker (`session_ensure`, `journal_append`, `checkpoint_write`) — cùng
đường `docker exec` mà mọi công cụ sandbox đã dùng, không mở thêm cổng nào.
"""
from __future__ import annotations

import asyncio
import json

from . import journal
from .limits import EVIDENCE_PRUNE_CODE, EVIDENCE_PRUNE_TIMEOUT_SECONDS

CHECKPOINT_FAILED_CODE = 'CHECKPOINT_FILE_FAILED'
JOURNAL_FAILED_CODE = 'JOURNAL_DEGRADED'


def _notice(store, sid, code, message, **extra):
    """Ghim một `notice` — chỗ duy nhất được phép nói ra lỗi ghi nhật ký."""
    try:
        return store.emit(sid, 'notice', {'code': code, 'message': message, **extra})
    except Exception:  # pragma: no cover - notice hỏng thì im, không được làm hỏng lượt
        return None


async def _safe(executor, op, args, store, sid, code, label):
    """Gọi một op trong box; trả `None` (kèm `notice`) khi không có executor hoặc op lỗi.

    Không nuốt lỗi im lặng: mã và thông điệp luôn được ghim, vì "nhật ký không ghi được" là dữ kiện
    người dùng phải thấy — chính nó là thứ đã thiếu trong 22 hàng checkpoint cũ.
    """
    if executor is None:
        _notice(store, sid, code, f'{code}: {label} chưa có executor để ghi bản đọc được',
                op=op, projectionStored=False)
        return None
    try:
        answer = await executor.execute(op, args, sid)
    except Exception as exc:  # executor hỏng, container tắt, op ném — cùng một cách xử lý
        _notice(store, sid, code, f'{code}: {label} không ghi được trong box ({type(exc).__name__}: {exc})',
                op=op)
        return None
    if not isinstance(answer, dict):
        _notice(store, sid, code, f'{code}: {label} trả về dữ liệu không hợp lệ',
                op=op, projectionStored=False)
        return None
    if (answer.get('ok') is False or answer.get('is_error') is True
            or answer.get('errorCode')):
        error = answer.get('errorCode') or answer.get('error') or answer.get('code')
        _notice(store, sid, code, f'{code}: {label} bị executor từ chối ({error})',
                op=op, projectionStored=False, projectionError=error)
        return None
    if answer.get('ok') is not True:
        _notice(store, sid, code, f'{code}: {label} chưa xác nhận ghi thành công',
                op=op, projectionStored=False)
        return None
    return answer


async def ensure_session(executor, store, sid, *, role=None, parent=None, goal=None) -> dict | None:
    """Tạo thư mục phiên trong box (`<workspace>/.session-history/<sid8>/`) — A1."""
    return await _safe(executor, 'session_ensure',
                       {'session': sid, 'role': role, 'parent': parent, 'goal': goal},
                       store, sid, JOURNAL_FAILED_CODE, 'thư mục phiên')


def insert_row(store, sid, kind, text, *, data=None, numbers=None, plan=None, refs=None,
               status=None, evidence=None, record_id=None, turn=None, step=None):
    """Hàng SQLite của một bản ghi (nguồn để `brief()` dựng khối ký ức) — **không** đụng box.

    Tách khỏi `append()` vì có hai đường ghi hợp lệ: đường thường ghi hàng rồi gọi op
    `journal_append`; còn bản `C:` (nén) thì **op trong box** đã ghi dòng `journal.jsonl` cùng
    lượt với cặp file, nên ở đây chỉ còn hàng SQLite (nếu gọi thêm op nữa thì mỗi lần nén thành
    hai dòng `C:` với hai mã khác nhau). `record_id` là mã do box mint
    (`C:<sid8>-<checkpointNumber>`) để hai bề mặt đọc ra **cùng một mã**.

    Trả `(item, seq)`; `seq` là `None` khi không ghi được (bảng thiếu, DB cũ) — chỗ gọi phải nói
    thật là hàng không vào, chứ không được lấy hàng cũ ra thay.
    """
    item = journal.record(kind, text, sid=sid, data=data, numbers=numbers, plan=plan, refs=refs,
                          status=status, evidence=evidence, turn=turn, step=step)
    seq = None
    try:
        seq = store.journal_add(sid, kind, item.get('text', text), {'record': item})
        if seq and not item.get('id'):
            # Mã cần số `seq`, mà SQLite chỉ trả về sau khi chèn — mint ngay sau đó và gán vào
            # payload của CHÍNH hàng vừa tạo (không sửa hàng nào khác).
            item['id'] = record_id or journal.mint_id(kind, item.get('sid8') or '', int(seq))
            store.journal_patch(sid, seq, {'record': item})
    except Exception:  # pragma: no cover - bảng journal thiếu (DB quá cũ) không được làm hỏng lượt
        return item, None
    return item, seq


async def append(executor, store, sid, kind, text, *, data=None, numbers=None, plan=None,
                 refs=None, status=None, evidence=None, turn=None, step=None) -> dict | None:
    """Một bản ghi nhật ký: hàng SQLite trước (nguồn của khối ký ức), file trong box sau (bản đọc).

    `kind` theo đúng tám mã của `journal.KIND_MARKER` (`task`, `plan`, `step`, `decision`,
    `evidence`, `checkpoint`, `fact`, `blocker`); `plan` chỉ dùng cho `kind='plan'`
    (`P:<identity>@v<n>`); `refs` là **tham chiếu** tới bản ghi khác (ví dụ bản kế hoạch trỏ về
    `T:` đang mở), và để trống khi phiên chưa có bản ghi nào để trỏ — không bao giờ bịa mã. Hàng SQLite là thứ `brief()` đọc, nên nó được ghi **trước** và không phụ
    thuộc kết quả của tầng file.
    """
    item, stored = insert_row(store, sid, kind, text, data=data, numbers=numbers, plan=plan,
                              refs=refs, status=status, evidence=evidence, turn=turn, step=step)
    answer = await _safe(executor, 'journal_append', {'session': sid, 'record': item},
                         store, sid, JOURNAL_FAILED_CODE, 'bản ghi nhật ký')
    if answer is not None:
        # Mã của bản ghi đi kèm câu trả lời: chỗ gọi không phải mò lại hàng cuối (mò như vậy có
        # thể trả về mã của lượt TRƯỚC khi hàng của chính nó không vào được). `rowMissing` nói
        # thẳng hàng SQLite không vào được dù dòng trong box đã ghi — hai bề mặt, hai sự thật khác
        # nhau, không được gộp thành một chữ "đã ghi".
        answer.setdefault('recordId', item.get('id'))
        answer.setdefault('stored', stored)
        if stored is None:
            answer['rowMissing'] = True
        return answer
    if stored:
        # Hàng SQLite đã có, tầng file thì không: `ok False` + `file None` để chỗ gọi nói ĐÚNG
        # phần còn thiếu ("bản ghi đã vào nhật ký, file trong box chưa") thay vì báo thành công.
        return {'ok': False, 'stored': stored, 'recordId': item.get('id'), 'file': None,
                'degraded': True}
    return None


async def write_checkpoint_file(executor, store, sid, messages, *, numbers=None, note=None) -> dict | None:
    """Ghi transcript trước nén ra cặp `.json`/`.md` trong box (A4) — không bao giờ ném.

    `journalRecord` **phải có chữ**: op trong box từ chối bản ghi rỗng
    (`session_files.journal_append` → `JOURNAL_DEGRADED`), và bản 0.1 của hàm này gửi đúng
    `{'kind': 'checkpoint'}` nên mỗi lần nén sinh một `notice` sai và `journal.degraded` vĩnh viễn.
    """
    nums = dict(numbers or {})
    after = nums.get('messageCountAfter')
    record = {'kind': 'checkpoint',
              'text': (f"nén {nums.get('messageCountBefore')} → {after} tin nhắn"
                       if isinstance(after, int) else 'nén transcript trước khi gộp')}
    return await _safe(executor, 'checkpoint_write',
                       {'session': sid, 'messages': messages, 'numbers': nums,
                        'note': note, 'journalRecord': record},
                       store, sid, CHECKPOINT_FAILED_CODE, 'bản transcript trước nén')


async def prune_captures(executor, store, sid) -> dict | None:
    """P1.5 — một lượt dọn thư mục ảnh/bằng chứng trong box, qua đúng khuôn `_safe`.

    Vì sao harness gọi: tệp bằng chứng của P1.4 sinh ở **mỗi** lần ghi tệp, còn `retention()` trong
    box chỉ chạy khi có người gọi (route của người vận hành, hoặc tiến trình chụp ảnh tự gọi mỗi 20
    lần chụp) — một phiên sửa 300 tệp mà không chụp ảnh nào sẽ không bao giờ được dọn. Gọi ở đây
    đúng nhịp `EVIDENCE_PRUNE_EVERY` lượt của phiên.

    Bốn trần của `retention()` áp theo `(kind, sid8)` và **không lọc phần mở rộng**, nên thư mục
    `evidence/` nằm gọn dưới cùng trần với ảnh chụp — không cần dựng lại image.

    Box thiếu `session_ops.py` ⇒ op trả `SESSION_OPS_UNAVAILABLE`; `_safe` biến nó thành notice và
    lượt đi tiếp. Trần thời gian riêng vì đây là việc phụ trong lượt: quá hạn thì bỏ, không kéo
    theo lượt.
    """
    args = {'session': sid, 'sid8': str(sid or '')[:8]}
    try:
        return await asyncio.wait_for(
            _safe(executor, 'captures_prune', args, store, sid, EVIDENCE_PRUNE_CODE,
                  'dọn thư mục bằng chứng'),
            EVIDENCE_PRUNE_TIMEOUT_SECONDS)
    except Exception as exc:  # timeout cũng vào đây: việc phụ không được làm hỏng lượt
        _notice(store, sid, EVIDENCE_PRUNE_CODE,
                f'{EVIDENCE_PRUNE_CODE}: dọn thư mục bằng chứng bỏ dở ({type(exc).__name__}: {exc})',
                op='captures_prune')
        return None


def note_gap(store, sid, code, message, op=None):
    """Ghim lời nói thật khi op trong box trả về nhưng **một phần** việc không xong.

    `_safe` chỉ thấy cờ `ok` của cả op; `checkpoint_write` làm hai việc (cặp file + dòng nhật ký)
    nên phần hỏng phải được gọi tên riêng — nếu không thì "đã ghi được" và "chưa ghi được" trộn
    vào nhau, đúng thứ đã xảy ra ở bản 0.1 (file có, dòng nhật ký không, mà thông báo lại nói
    ngược lại).
    """
    return _notice(store, sid, code, message, op=op)


def brief(store, sid, *, limit=60) -> str:
    """Khối "ký ức" của phiên (A5) — rỗng khi chưa có bản ghi nào **thuộc sáu nhóm** (lượt đầu
    không có gì để nhớ, và một phiên chỉ có hàng tra cứu — `F:`/`E:` — cũng vậy)."""
    try:
        rows = store.journal_tail(sid, limit=limit)
    except Exception:  # pragma: no cover - phiên chưa có nhật ký / DB cũ
        return ''
    if not rows:
        return ''
    block = journal.brief_text([record_view(row) for row in rows])
    # Đợt 3 vòng 22: hàng `E:` (bằng chứng của lượt) cố ý KHÔNG có nhóm trong khối ký ức, nên một
    # phiên chỉ có hàng `E:`/`F:` sẽ dựng ra sáu nhóm rỗng. Ghép khối đó vào system message là đổi
    # prompt giữa hai lượt mà không mang thêm thông tin nào — trả `''` thì `inject_brief` bỏ khối
    # cũ và prompt giữ nguyên tiền tố (đúng thứ prompt cache cần).
    return block if journal.brief_has_items(block) else ''


def record_view(row):
    """Hàng SQLite → bản ghi đúng khuôn `journal.record` (khối ký ức đọc theo khuôn đó).

    Hai nguồn ghi cùng tồn tại: `append()` ở đây lưu cả bản ghi dưới khoá `record`, còn đường C1
    (`_journal_blocker`) lưu thẳng các con số. Hàm này đọc được cả hai và **luôn** suy ra `status`
    đúng loại bản ghi, vì `group_rows` xếp nhóm theo `status`.
    """
    payload = row.get('payload')
    if isinstance(payload, str):  # hàng thô từ SQL: cột `payload` là JSON chưa parse
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}
    nested = payload.get('record') if isinstance(payload.get('record'), dict) else None
    record = nested or payload
    kind = str(row.get('kind') or record.get('kind') or '')
    data = record.get('data') if isinstance(record.get('data'), dict) else {}
    if not data:
        data = {key: value for key, value in payload.items() if key not in ('id', 'status', 'record')}
    return {
        'kind': kind,
        'text': row.get('text') or record.get('text') or '',
        'id': record.get('id') or payload.get('id'),
        'status': record.get('status') or payload.get('status') or journal.DEFAULT_STATUS.get(kind),
        'data': data,
        'numbers': record.get('numbers'),
        # P1.2 — lượt/bước của bản ghi (đường ghim đi qua `insert_row`/`append`). Hàng ghi trước
        # vòng này, và hàng của đường C1 (lưu số trần, không có khối `record`), KHÔNG có hai khoá
        # này ⇒ trả `None`: người đọc phải phân biệt được "không có" với "bằng 0".
        'turn': record.get('turn') if isinstance(record.get('turn'), int)
                and not isinstance(record.get('turn'), bool) else None,
        'step': record.get('step') if isinstance(record.get('step'), int)
                and not isinstance(record.get('step'), bool) else None,
        'ts': record.get('ts') or payload.get('ts'),
        # Hai trường này có thật trong bản ghi nhưng bản 0.1 không trả ra, nên route
        # `GET /api/agent/journal/tasks` luôn báo `refs`/`evidence` là `null` cho mọi việc —
        # người đọc tưởng "không có", trong khi thật ra là "không được đọc ra".
        'refs': record.get('refs') if isinstance(record.get('refs'), list) else [],
        'evidence': record.get('evidence') if isinstance(record.get('evidence'), list) else [],
    }


def inject_brief(prompt, block) -> str:
    """Ghép khối ký ức vào system prompt, **thay** khối cũ nếu đã có (gọi lại nhiều lần không chồng)."""
    clean = _strip_brief(prompt)
    if not block:
        return clean
    return f'{clean.rstrip()}\n\n{block}' if clean.strip() else block


def _strip_brief(prompt):
    """Bỏ khối ký ức đã chèn ở lần trước (nhận diện bằng đúng dòng tiêu đề của `journal.brief_text`)."""
    text = str(prompt or '')
    header = journal.JOURNAL_BRIEF_HEADER
    index = text.find(header)
    return text[:index].rstrip() if index >= 0 else text


# Tên cũ dùng trong nội bộ mô-đun này; route/nhật ký dùng tên công khai `record_view`.
_as_record = record_view
