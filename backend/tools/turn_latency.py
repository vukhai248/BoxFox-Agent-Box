"""Đo MỘT LƯỢT CUA từ lúc chủ nhà ra đề nghị đến lúc trả lời — đọc bảng `events` của harness.

Công cụ này **chỉ đọc** store SQLite của harness (chỉ thư viện chuẩn, không cần X server, không cần
mạng), nên chạy được ở mọi máy có tệp store. Nguồn chân lý là bảng `events` (lược đồ ở
`backend/src/agentbox/memory/session_store.py:24-26`). Payload của `turn_start`/`turn_end` **không**
mang mốc thời gian — mọi số ms dưới đây đọc từ cột `created` (epoch, số thực), trừ `deadlineUsedMs`
(bộ đếm ngân sách nội bộ của harness, bắt đầu ở `runtime.py:4123`).

    cd backend && .venv/bin/python tools/turn_latency.py --db ~/BoxFox/harness/sessions.sqlite
    cd backend && .venv/bin/python tools/turn_latency.py --json /var/tmp/turn-latency.json

Một lượt được tách thành các phần **cộng đúng bằng tổng** (phần nào thiếu mốc thì in `—`, không suy diễn):

    harnessMs = modelMs + toolMs + unaccountedMs            (bất biến của phép chia)
    wallMs    = modelMs + toolMs + unaccountedMs + outsideMs

Ba ràng buộc trung thực (không được nới):

1. `modelMs` mang nhãn **model + vòng lặp**, KHÔNG phải "thời gian model": nó là phần còn lại của
   bước sau khi trừ tool, nên gồm cả dựng request, kiểm cổng bằng chứng, thử lại. Muốn tách thật thì
   phải nối nhật ký router vào phiên (K5 của kế hoạch v2 — chưa làm).
2. `waitedMs` ("chờ bạn giao kết quả", `peer_turn_cost`) là số **báo kèm**, không bao giờ bị trừ khỏi
   phần nào: harness không ghi một khoảng bắt đầu/kết thúc riêng cho lần chờ, nên nó chồng lấn với
   `model + vòng lặp`.
3. Hai số thời gian có thể lệch nhau và không số nào bị "sửa": `created` (tức `wallMs`) là số có thẩm
   quyền cho câu "chủ nhà chờ bao lâu" — thời gian tường thật, gồm cả phần trước khi `_run` bắt đầu;
   `deadlineUsedMs` (tức `harnessMs`) là số có thẩm quyền cho câu "lượt đã tiêu bao nhiêu ngân sách".
   Lệch quá `DISAGREE_MS` thì in thêm dòng `LỆCH` và **vẫn** lấy `wallMs` làm số chính.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

#: Tên công cụ thuộc nhóm CUA: một lượt có ít nhất một `tool_start` tên trong đây là **ca CUA**.
CUA_TOOLS = ('computer_use', 'computer_screen_capture', 'computer_screen_record', 'inspect_element')

#: Ngưỡng cảnh báo khi `wallMs` và `deadlineUsedMs` lệch nhau (ms). Đo được trên máy này: một lượt
#: 145,7 ms lệch 3,7 ms (bình thường — `deadlineUsedMs` bắt đầu bên trong `_run`). Ngưỡng 1 000 ms
#: là để bắt ca bất thường (hàng đợi dài, tiến trình bận), KHÔNG phải để "sửa" một trong hai số.
DISAGREE_MS = 1000.0

#: Số lượt gần nhất đưa vào báo cáo (mặc định 20). `--limit 0` = không giới hạn.
DEFAULT_LIMIT = 20

#: Nhãn ca CUA cắt từ dòng đầu của `user.payload.text`.
MAX_LABEL_CHARS = 60


class StoreUnavailable(Exception):
    """Store không mở/đọc được, hoặc không có lượt nào để đo.

    In `CHƯA ĐO ĐƯỢC` kèm lý do rồi thoát mã 2 — không thoát 0: im lặng coi như đạt là đúng lỗi mà
    `check_budget` đã sửa một lần (thiếu số đo không được phép trông giống ĐẠT).
    """


def default_db_path() -> Path:
    """Store mặc định, ĐÚNG như harness dựng nó (`backend/src/agentbox/api/server.py:2456`)."""
    base = os.environ.get('BOXFOX_AGENT_DATA_DIR') or str(
        Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'BoxFox' / 'harness')
    return Path(base) / 'sessions.sqlite'


def load_rows(db_path: Path) -> tuple[list[dict], int]:
    """Mọi hàng `events` theo `seq`, chỉ đọc — không bao giờ ghi vào store sống.

    Trả `(rows, broken_payloads)`: hàng có payload không đọc được vẫn giữ (để gom lượt theo `seq`)
    nhưng payload coi như rỗng, và số hàng hỏng được đếm để báo trung thực.
    """
    if not db_path.exists():
        raise StoreUnavailable('không thấy tệp %s' % db_path)
    try:
        # `mode=ro`: tuyệt đối không mở đường ghi vào store đang được harness dùng.
        con = sqlite3.connect('file:%s?mode=ro' % db_path.resolve(), uri=True)
    except sqlite3.Error as exc:
        raise StoreUnavailable('không mở được %s (%s)' % (db_path, exc)) from None
    rows: list[dict] = []
    broken = 0
    try:
        con.row_factory = sqlite3.Row
        cursor = con.execute('SELECT seq, session_id, kind, payload, created FROM events ORDER BY seq')
        for row in cursor:
            try:
                payload = json.loads(row['payload'])
            except (TypeError, ValueError):
                payload, broken = {}, broken + 1
            rows.append({'seq': int(row['seq']), 'sessionId': row['session_id'], 'kind': row['kind'],
                         'payload': payload if isinstance(payload, dict) else {},
                         'created': float(row['created'])})
    except sqlite3.Error as exc:
        raise StoreUnavailable('không đọc được bảng `events` của %s (%s)' % (db_path, exc)) from None
    finally:
        con.close()
    return rows, broken


def build_turns(rows: list[dict]) -> list[dict]:
    """Gom hàng thành lượt: theo `payload.turn`, hàng thiếu `turn` thì theo dãy `seq` giữa hai `user`.

    Đây là cùng đường lùi mà `HarnessStepView.buildHarnessTurns` dùng ở phía UI (một `user` mở một
    lượt; hàng trước `user` đầu tiên không thuộc lượt nào). Hàng `user` có `steer: true` là chỉ thị
    giữa lượt, KHÔNG mở lượt mới.
    """
    turns: dict[tuple[str, int], dict] = {}
    order: list[tuple[str, int]] = []
    user_count: dict[str, int] = {}
    last_user: dict[str, tuple[int, dict]] = {}
    for row in rows:
        sid = row['sessionId']
        payload = row['payload']
        is_user = row['kind'] == 'user' and payload.get('steer') is not True
        if is_user:
            user_count[sid] = user_count.get(sid, 0) + 1
            last_user[sid] = (user_count[sid], row)
        turn_no = payload.get('turn')
        if not isinstance(turn_no, int) or isinstance(turn_no, bool):
            fallback = last_user.get(sid)
            if fallback is None:
                continue            # hàng cấp phiên trước lượt `user` đầu tiên — không phải một lượt
            turn_no = fallback[0]
        key = (sid, turn_no)
        turn = turns.get(key)
        if turn is None:
            turn = {'sessionId': sid, 'turn': turn_no, 'rows': [], 'user': None}
            turns[key] = turn
            order.append(key)
        turn['rows'].append(row)
        if is_user and turn['user'] is None:
            turn['user'] = row
    return [turns[key] for key in order]


def _last(rows: list[dict], predicate) -> dict | None:
    for row in reversed(rows):
        if predicate(row):
            return row
    return None


def _number(value) -> float | None:
    """Số thực hợp lệ, hoặc None (bool không phải số ở đây)."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _tool_pairs(rows: list[dict]) -> tuple[list[tuple[dict, dict]], int]:
    """Ghép `tool_start` với `tool_end` theo `payload.id`; đếm số lời gọi không ghép được."""
    starts: dict[str, dict] = {}
    pairs: list[tuple[dict, dict]] = []
    unmatched = 0
    for row in rows:
        key = row['payload'].get('id')
        key = 'seq:%s' % row['seq'] if key is None else str(key)
        if row['kind'] == 'tool_start':
            starts.setdefault(key, row)
        elif row['kind'] == 'tool_end':
            start = starts.pop(key, None)
            if start is None:
                unmatched += 1
            else:
                pairs.append((start, row))
    return pairs, unmatched + len(starts)


def _step_pairs(rows: list[dict]) -> tuple[list[tuple[dict, dict]], int]:
    """Ghép `turn_start` với `turn_end` theo TỪNG BƯỚC (cặp này mở/đóng mỗi bước, không phải mỗi lượt)."""
    open_starts: list[dict] = []
    pairs: list[tuple[dict, dict]] = []
    for row in rows:
        if row['kind'] == 'turn_start':
            open_starts.append(row)
        elif row['kind'] == 'turn_end':
            match = None
            for index in range(len(open_starts) - 1, -1, -1):
                if open_starts[index]['payload'].get('step') == row['payload'].get('step'):
                    match = index
                    break
            if match is None and open_starts:
                match = len(open_starts) - 1
            if match is not None:
                pairs.append((open_starts.pop(match), row))
    return pairs, len(open_starts)


def _label(user: dict | None) -> str:
    """Nhãn ca: dòng đầu `user.payload.text` (cắt 60 ký tự) + 8 ký tự đầu `invocationId`."""
    if not user:
        return ''
    text = str(user['payload'].get('text') or '')
    first = text.splitlines()[0] if text else ''
    first = first[:MAX_LABEL_CHARS]
    invocation = str(user['payload'].get('invocationId') or '')[:8]
    if first and invocation:
        return '%s · %s' % (first, invocation)
    return first or invocation


def summarise_turn(turn: dict) -> dict:
    """Một lượt: các mốc thời gian + phép chia + số của lượt + ghi chú trung thực của riêng lượt."""
    rows, user = turn['rows'], turn['user']
    notes: list[str] = []
    started = user['created'] if user else rows[0]['created']

    # Mốc "trả lời": assistant final → finish → turn_end. Lượt hỏng ở tầng định tuyến (đo được trên
    # máy này) không có `assistant` lẫn `finish` — không lấy `turn_end` làm mốc thì `wallMs` sẽ trống
    # dù thời gian chờ ĐO ĐƯỢC; mốc đó được nêu rõ trong ghi chú chứ không im lặng.
    answered = (_last(rows, lambda r: r['kind'] == 'assistant' and r['payload'].get('final') is True)
                or _last(rows, lambda r: r['kind'] == 'finish')
                or _last(rows, lambda r: r['kind'] == 'turn_end'))
    closed = (_last(rows, lambda r: r['kind'] in ('finish', 'error'))
              or _last(rows, lambda r: r['kind'] == 'turn_end') or answered)
    if answered is None and closed is not None:
        answered = closed
        notes.append('lượt không có hàng trả lời (`assistant` final/`finish`/`turn_end`) — '
                     'wallMs tính tới lúc đóng sổ')
    elif answered is None:
        notes.append('lượt chưa đóng (thiếu `assistant` final/`finish`/`turn_end`) — wallMs để trống')

    wall_ms = round((answered['created'] - started) * 1000.0, 1) if answered else None
    closed_ms = round((closed['created'] - started) * 1000.0, 1) if closed else None

    last_end = _last(rows, lambda r: r['kind'] == 'turn_end')
    last_start = _last(rows, lambda r: r['kind'] == 'turn_start')
    harness_ms = _number(last_end['payload'].get('deadlineUsedMs')) if last_end else None

    tool_pairs, unmatched_tools = _tool_pairs(rows)
    tool_ms = round(sum((end['created'] - start['created']) * 1000.0 for start, end in tool_pairs), 1)
    step_pairs, unclosed_steps = _step_pairs(rows)
    model_ms = None
    if step_pairs:
        model_ms = 0.0
        inside_total = 0.0
        for step_start, step_end in step_pairs:
            window = (step_end['created'] - step_start['created']) * 1000.0
            inside = sum((end['created'] - start['created']) * 1000.0 for start, end in tool_pairs
                         if step_start['created'] <= start['created'] <= step_end['created'])
            inside_total += inside
            model_ms += window - inside
        model_ms = round(model_ms, 1)
        orphan_ms = round(tool_ms - inside_total, 1)
        if orphan_ms > 0.05:
            notes.append('LỆCH: %.1f ms tool nằm ngoài cửa sổ bước nào — vẫn tính vào `toolMs`'
                         % orphan_ms)
    elif tool_pairs:
        notes.append('thiếu cặp `turn_start`/`turn_end` — chưa chia được `model + vòng lặp`')

    unaccounted_ms = None
    if harness_ms is not None and model_ms is not None:
        unaccounted_ms = round(harness_ms - model_ms - tool_ms, 1)
        if unaccounted_ms < 0:
            notes.append('LỆCH: thân harness âm (%.1f ms) — `model + vòng lặp` + tool vượt '
                         '`deadlineUsedMs`; không sửa số nào' % unaccounted_ms)
    outside_ms = None
    if wall_ms is not None and harness_ms is not None:
        outside_ms = round(wall_ms - harness_ms, 1)
        if abs(outside_ms) > DISAGREE_MS:
            notes.append('LỆCH: wall %.1f ms vs deadlineUsedMs %.1f ms — lệch %.1f ms '
                         '(> %.0f ms); `wallMs` vẫn là số chính cho "chủ nhà chờ bao lâu", '
                         '`deadlineUsedMs` là số ngân sách' % (wall_ms, harness_ms, outside_ms, DISAGREE_MS))
    if unmatched_tools:
        notes.append('%d lời gọi tool không ghép được `tool_start`/`tool_end` — thời gian của chúng '
                     'nằm trong `model + vòng lặp` (không đo được riêng)' % unmatched_tools)
    if unclosed_steps:
        notes.append('%d `turn_start` không có `turn_end` — bước đó không có khoảng để đo' % unclosed_steps)

    # `waitedMs` (`peer_turn_cost`) là số báo kèm. Kế hoạch ghi nguồn là hàng `turn_end`; mã hiện tại
    # gắn nó vào hàng `finish` (`runtime.py:4371`), nên đọc hàng CUỐI mang khoá này và nói rõ nếu các
    # hàng nói hai số khác nhau.
    waits = [(row['kind'], _number(row['payload'].get('waitedMs'))) for row in rows
             if _number(row['payload'].get('waitedMs')) is not None]
    waited_ms = waits[-1][1] if waits else None
    if len({value for _kind, value in waits}) > 1:
        notes.append('LỆCH: waitedMs khác nhau giữa các hàng (%s) — lấy giá trị cuối' %
                     ', '.join('%s=%s' % (kind, int(value)) for kind, value in waits))

    names = [row['payload'].get('name') for row in rows if row['kind'] == 'tool_start']
    return {
        'sessionId': turn['sessionId'], 'turn': turn['turn'], 'seq': rows[0]['seq'],
        'label': _label(user),
        'startedAt': started, 'answeredAt': answered['created'] if answered else None,
        'closedAt': closed['created'] if closed else None,
        'wallMs': wall_ms, 'closedMs': closed_ms, 'harnessMs': harness_ms,
        'toolMs': tool_ms, 'modelMs': model_ms, 'unaccountedMs': unaccounted_ms,
        'outsideMs': outside_ms, 'waitedMs': waited_ms,
        'stepsUsed': last_end['payload'].get('stepsUsed') if last_end else None,
        'toolsRun': last_end['payload'].get('toolsRun') if last_end else None,
        'toolCalls': last_end['payload'].get('toolCalls') if last_end else None,
        'status': last_end['payload'].get('status') if last_end else None,
        'finishReason': last_end['payload'].get('finishReason') if last_end else None,
        'modelId': last_start['payload'].get('modelId') if last_start else None,
        'cua': any(name in CUA_TOOLS for name in names),
        'notes': notes,
    }


def read_turns(db_path: Path, *, session: str | None = None, limit: int = DEFAULT_LIMIT) -> dict:
    """Báo cáo đầy đủ: `{'generatedAt', 'db', 'sessions', 'turns', 'cases', 'notes'}`.

    `session` lọc theo tiền tố session id; `limit` lấy N lượt GẦN NHẤT (<= 0 = tất cả). `cases` là
    các lượt có ít nhất một lời gọi CUA trong số lượt được báo cáo.
    """
    rows, broken = load_rows(db_path)
    if session:
        rows = [row for row in rows if row['sessionId'].startswith(session)]
    turns = [summarise_turn(turn) for turn in build_turns(rows)]
    if limit and limit > 0:
        turns = turns[-limit:]
    if not turns:
        raise StoreUnavailable('store không có lượt nào để đo (%s)' % db_path)

    cases = [{'label': turn['label'], 'sessionId': turn['sessionId'], 'turn': turn['turn'],
              'wallMs': turn['wallMs'], 'modelMs': turn['modelMs'], 'toolMs': turn['toolMs'],
              'toolsRun': turn['toolsRun'], 'stepsUsed': turn['stepsUsed'], 'status': turn['status']}
             for turn in turns if turn['cua']]
    sessions: dict[str, dict] = {}
    for turn in turns:
        entry = sessions.setdefault(turn['sessionId'], {'sessionId': turn['sessionId'], 'turns': 0,
                                                        'cases': 0, 'firstAt': turn['startedAt'],
                                                        'lastAt': turn['startedAt']})
        entry['turns'] += 1
        entry['cases'] += 1 if turn['cua'] else 0
        entry['firstAt'] = min(entry['firstAt'], turn['startedAt'])
        entry['lastAt'] = max(entry['lastAt'], turn['startedAt'])

    notes = ['thời gian: `wallMs` đọc từ cột `created` — số chính cho "chủ nhà chờ bao lâu" (gồm cả '
             'phần trước `_run`); `deadlineUsedMs` là bộ đếm ngân sách của harness — số chính cho '
             '"đã tiêu bao nhiêu". Lệch quá %.0f ms thì có dòng `LỆCH`.' % DISAGREE_MS,
             '`modelMs` là **model + vòng lặp** — không phải thời gian model thuần (gồm dựng request, '
             'kiểm cổng, thử lại); muốn tách thật phải nối nhật ký router vào phiên (K5).',
             '`waitedMs` (chờ bạn giao kết quả) báo kèm, KHÔNG trừ vào phần nào vì nó chồng lấn với '
             '`model + vòng lặp`.',
             'ba phần `model + vòng lặp` + `tool` + `thân harness` cộng đúng bằng `harnessMs`; '
             'thêm `ngoài lượt` là đúng bằng `wallMs`.']
    if not cases:
        notes.insert(0, 'chưa đo được lượt CUA nào')
    if broken:
        notes.append('%d hàng `events` có payload không đọc được — vẫn gom lượt theo `seq`' % broken)
    return {'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'db': str(db_path), 'sessions': list(sessions.values()), 'turns': turns,
            'cases': cases, 'notes': notes}


def _ms(value) -> str:
    return '—' if value is None else '%.1f' % value


def format_report(report: dict) -> list[str]:
    """Báo cáo dạng chữ — cùng các con số với JSON, kèm nhãn trung thực."""
    lines = ['store: %s' % report['db'],
             '%d phiên · %d lượt · %d ca CUA' % (len(report['sessions']), len(report['turns']),
                                                 len(report['cases']))]
    if not report['cases']:
        lines.append('chưa đo được lượt CUA nào')
    for turn in report['turns']:
        lines.append('')
        head = 'lượt %s · phiên %s' % (turn['turn'], turn['sessionId'][:8])
        if turn['label']:
            head += ' · %s' % turn['label']
        lines.append(head)
        answered = '' if turn['answeredAt'] is None else ' · đóng sổ %s ms' % _ms(turn['closedMs'])
        lines.append('  wall %s ms (đề nghị → trả lời; đọc từ cột `created` — số chính)%s'
                     % (_ms(turn['wallMs']), answered))
        lines.append('  harness %s ms (deadlineUsedMs — số ngân sách) · %s bước · %s tool · '
                     'status %s · finishReason %s'
                     % (_ms(turn['harnessMs']), turn['stepsUsed'] if turn['stepsUsed'] is not None else '—',
                        turn['toolsRun'] if turn['toolsRun'] is not None else '—',
                        turn['status'] or '—', turn['finishReason'] or '—'))
        if turn['modelMs'] is None:
            lines.append('  chia lượt: chưa đủ mốc để chia (thiếu cặp `turn_start`/`turn_end`)')
        elif turn['unaccountedMs'] is None:
            lines.append('  chia lượt: thiếu `deadlineUsedMs` trên `turn_end` — chưa chia được '
                         '`thân harness`')
        else:
            lines.append('  chia lượt: model+vòng lặp %s ms + tool %s ms + thân harness %s ms '
                         '= harness %s ms; + ngoài lượt %s ms = wall %s ms'
                         % (_ms(turn['modelMs']), _ms(turn['toolMs']), _ms(turn['unaccountedMs']),
                            _ms(turn['harnessMs']), _ms(turn['outsideMs']), _ms(turn['wallMs'])))
        waited = '—' if turn['waitedMs'] is None else '%s ms' % _ms(turn['waitedMs'])
        lines.append('  chờ bạn: %s (báo kèm; không trừ vào phần nào)' % waited)
        lines.extend('  %s' % note for note in turn['notes'])
    if report['cases']:
        lines.append('')
        lines.append('ca CUA (%d): ca · wall · model+vòng lặp · tool · toolsRun · stepsUsed · status'
                     % len(report['cases']))
        for case in report['cases']:
            lines.append('  %s · %s · %s · %s · %s · %s · %s'
                         % (case['label'] or ('lượt %s' % case['turn']), _ms(case['wallMs']),
                            _ms(case['modelMs']), _ms(case['toolMs']), case['toolsRun'],
                            case['stepsUsed'], case['status'] or '—'))
    lines.append('')
    lines.append('ghi chú:')
    lines.extend('  - %s' % note for note in report['notes'])
    return lines


def check_gate(report: dict, max_total_ms: int) -> list[str]:
    """Danh sách lượt vượt trần `--max-total-ms` (so `wallMs` — số chính của "chờ bao lâu")."""
    over = []
    for turn in report['turns']:
        if turn['wallMs'] is not None and turn['wallMs'] > max_total_ms:
            over.append('%s: wall %.1f ms > %s ms'
                        % (turn['label'] or ('lượt %s · %s' % (turn['turn'], turn['sessionId'][:8])),
                           turn['wallMs'], max_total_ms))
    return over


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Đo một lượt CUA từ đề nghị đến trả lời (đọc bảng `events` của harness; chỉ đọc).')
    parser.add_argument('--db', help='tệp SQLite của harness (mặc định: $BOXFOX_AGENT_DATA_DIR/'
                                     'sessions.sqlite → ~/BoxFox/harness/sessions.sqlite)')
    parser.add_argument('--session', help='lọc theo tiền tố session id (8 ký tự đầu là đủ)')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT,
                        help='số lượt gần nhất đưa vào báo cáo (mặc định %d; 0 = tất cả)'
                             % DEFAULT_LIMIT)
    parser.add_argument('--json', help='ghi báo cáo ra tệp JSON')
    parser.add_argument('--max-total-ms', type=int,
                        help='cổng tuỳ chọn: lượt nào vượt trần thì in `VƯỢT TRẦN` và thoát mã 1')
    args = parser.parse_args(argv)

    db_path = Path(args.db) if args.db else default_db_path()
    try:
        report = read_turns(db_path, session=args.session, limit=args.limit)
    except StoreUnavailable as exc:
        print('CHƯA ĐO ĐƯỢC: %s' % exc)
        return 2
    for line in format_report(report):
        print(line)
    if args.json:
        try:
            Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        except OSError as exc:
            print('CHƯA ĐO ĐƯỢC: không ghi được %s (%s)' % (args.json, exc))
            return 2
        print('đã ghi %s' % args.json)
    if args.max_total_ms is not None:
        over = check_gate(report, args.max_total_ms)
        for line in over:
            print('VƯỢT TRẦN: %s' % line)
        if over:
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
