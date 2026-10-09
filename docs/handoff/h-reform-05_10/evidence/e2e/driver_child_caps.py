"""Kịch bản H11 (testing agent h11-testing): các TRẦN của công cụ peer + đường resume wait=false.

Khác `driver_child.py` (đường hạnh phúc wait=true của main agent), tệp này kiểm:
  1. `await_nudge_cap`  — chờ hụt 3 lần ⇒ mỗi lần có `nudge` PEER_WAIT_EXPIRED kèm bộ đếm n/3,
     lần gọi thứ 4 bị TỪ CHỐI bằng PEER_WAIT_CAPPED.
  2. `peer_read_cap`    — đọc lặp cùng một cửa sổ journal (không dòng mới) ⇒ lần đọc thứ 5 bị
     TỪ CHỐI bằng PEER_READ_CAPPED (cổng đếm `idle > PEER_READ_IDLE_MAX`).
  3. `resume_wait_false` — con bị cắt bằng trần cha khai (maxSteps=2) + `wait=false`; cha chờ
     giao kết quả (đủ cờ timedOut/partial/resumable) rồi `child_resume wait=false` ⇒ attempt mới,
     cờ `previous` trả về, con chạy lại trong CHÍNH transcript cũ, giao kết quả lần 2.
  4. `resume_not_cut`   — con ĐANG chạy thì `child_resume` bị TỪ CHỐI bằng CHILD_RESUME_NOT_CUT.
  5. `resume_second_turn` — gọi lại CÙNG con ở LƯỢT THỨ HAI của cha: `attempt` phải tăng 1 → 2
     (bộ đếm cả đời con), không TASK_INVOCATION_CONFLICT (fix vòng soát H11 vòng 2).

Chạy (CHỈ sau khi main agent bật đèn xanh):
  python3 /code/.generated_artifacts/e2e/driver_child_caps.py --base 3113 --label child-caps
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Runner, http  # noqa: E402

DB = '/var/tmp/boxfox-e2e/data-on/sessions.sqlite'


def set_db(path):
    global DB
    DB = path


def rows(sql, args=()):
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()


def messages_of(sid):
    got = rows('select messages from sessions where id = ?', (sid,))
    if not got:
        return []
    raw = got[0]['messages']
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except ValueError:
        return []


def tool_ends(payload, name=None):
    out = []
    for event in payload.get('events') or []:
        if event.get('type') != 'tool_end':
            continue
        data = event.get('data') or {}
        if name and data.get('name') != name:
            continue
        out.append(data)
    return out


def results_of(payload, name):
    return [d.get('result') or {} for d in tool_ends(payload, name)]


def all_events(base, sid, cap=80):
    """MỌI sự kiện của phiên: session GET chỉ trả MỘT trang 500 (`hasMore`/`nextAfter`).

    Bản cũ đọc đúng một trang nên phiên dài (>500 sự kiện) khiến bằng chứng của lượt sau
    trỏ nhầm về sự kiện của lượt đầu (bắt oan `resume_second_turn`, 04/10: bằng chứng lượt 2
    thực ra là tool_end lượt 1 — sự thật nằm ở seq 138762, `attempt: 2`).
    """
    events, after = [], 0
    for _ in range(cap):
        _, payload = http(base, 'GET', f'/api/agent/sessions/{sid}' + (f'?after={after}' if after else ''))
        page = payload.get('events') or []
        events.extend(page)
        if not payload.get('hasMore') or not page:
            break
        after = payload.get('nextAfter') or page[-1].get('seq')
    return events


def latest_child(parent_sid):
    got = rows('select * from children where parent_id = ? order by started desc', (parent_sid,))
    return got[0] if got else None


def scenario_await_nudge_cap(runner):
    """Chờ hụt liên tiếp: nudge đếm đủ 3 lần rồi lần gọi thứ 4 bị chặn bằng PEER_WAIT_CAPPED."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Đây là BÀI KIỂM THỬ GIAO THỨC của harness. Hãy làm ĐÚNG theo thứ tự sau, '
        'kể cả khi kết quả công cụ gợi ý cách khác:\n'
        '1) Gọi delegate_task với role="explore", '
        'goal="Đọc HẾT các tệp .md dưới .plans/: mỗi bước gọi file_read cho ĐÚNG MỘT tệp, '
        'theo thứ tự, đọc xong tất cả mới trả lời danh sách tên tệp.", wait=false.\n'
        '2) Gọi await_children NGAY, timeoutSeconds=2. Con còn đang chạy nên kết quả sẽ là '
        'status="timeout" kèm "nudge" PEER_WAIT_EXPIRED — bình thường, tiếp tục.\n'
        '3) Gọi await_children lần 2, timeoutSeconds=2 (lại timeout).\n'
        '4) Gọi await_children lần 3, timeoutSeconds=2 (lại timeout).\n'
        '5) Gọi await_children lần 4, timeoutSeconds=2 — lần này sẽ bị TỪ CHỐI với mã '
        'PEER_WAIT_CAPPED. ĐÓ LÀ ĐIỀU CẦN KIỂM CHỨNG; đừng gọi lại nữa.\n'
        '6) Trả lời một câu tóm tắt: mấy lần timeout, lần thứ mấy bị chặn.'), timeout=900)
    full = {'events': all_events(runner.base, sid)}
    calls = results_of(full, 'await_children')
    timeouts = [c for c in calls if c.get('status') == 'timeout']
    nudges = [str(c.get('nudge') or '') for c in timeouts]
    counts = []
    for n in nudges:
        for part in n.split():
            if '/' in part and part.replace('/', '').isdigit():
                counts.append(part)
                break
    capped = [c for c in calls if 'PEER_WAIT_CAPPED' in str(c.get('error') or '')
              or c.get('errorCode') == 'PEER_WAIT_CAPPED']
    any_done = [c for c in calls if c.get('status') == 'done']
    child = latest_child(sid)
    checks = [
        runner.check('delegate_task đã chạy (con chạy nền)',
                     bool(tool_ends(full, 'delegate_task')), sorted(set(runner.tools_run(full)))),
        runner.check('await_children được gọi >= 4 lần', len(calls) >= 4, f'calls={len(calls)}'),
        runner.check('>= 3 lần timeout', len(timeouts) >= 3,
                     [c.get('status') for c in calls]),
        runner.check('mỗi timeout có nudge PEER_WAIT_EXPIRED kèm bộ đếm n/3',
                     bool(nudges) and all('PEER_WAIT_EXPIRED' in n and '/3' in n for n in nudges),
                     [n[:110] for n in nudges]),
        runner.check('bộ đếm tăng dần 1/3 → 3/3', counts[:3] == ['1/3', '2/3', '3/3'], counts),
        runner.check('lần gọi vượt trần bị TỪ CHỐI bằng PEER_WAIT_CAPPED', bool(capped),
                     [str(c.get('error'))[:200] for c in capped] or 'không có'),
        runner.check('con chưa giao trong lúc chờ (không lần chờ nào trả "done")', not any_done,
                     [c.get('status') for c in calls]),
        runner.check('hàng sổ con tồn tại (con chạy nền thật)', bool(child),
                     {k: (child or {}).get(k) for k in ('session_id', 'status', 'reason')}),
        runner.check('lượt cha kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('await_nudge_cap', checks, {
        'session': sid,
        'awaitCalls': [{'status': c.get('status'), 'errorCode': c.get('errorCode'),
                        'nudge': str(c.get('nudge') or '')[:160]} for c in calls],
        'child': child and {k: child.get(k) for k in ('session_id', 'status', 'reason', 'started')},
    })


def scenario_peer_read_cap(runner):
    """Đọc lặp một cửa sổ không có dòng mới: lần đọc thứ 5 bị chặn bằng PEER_READ_CAPPED."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Đây là BÀI KIỂM THỬ GIAO THỨC của harness. Hãy làm ĐÚNG theo thứ tự sau, '
        'kể cả khi kết quả công cụ gợi ý cách khác:\n'
        '1) Gọi delegate_task với role="explore", goal="Đọc tệp .plans/v1-agent-box-plan.md '
        'bằng file_read rồi trả lời đúng một dòng OK.", wait=false.\n'
        '2) Gọi await_children NGAY, timeoutSeconds=120, để chờ con giao kết quả.\n'
        '3) Gọi peer_read với ĐÚNG tham số: sessionId=<sessionId của con ở bước 1>, '
        'afterSeq=0, limit=5.\n'
        '4) Gọi peer_read THÊM 5 lần nữa với ĐÚNG cùng tham số cũ (afterSeq=0, limit=5). '
        'Một trong các lần cuối sẽ bị TỪ CHỐI với mã PEER_READ_CAPPED — ĐÓ LÀ ĐIỀU CẦN '
        'KIỂM CHỨNG; sau lần bị chặn thì DỪNG, không đọc nữa.\n'
        '5) Trả lời một câu tóm tắt: đọc được mấy lần, lần thứ mấy bị chặn.'), timeout=900)
    reads = results_of(payload, 'peer_read')
    ok_reads = [r for r in reads if not r.get('is_error')]
    capped = [r for r in reads if r.get('errorCode') == 'PEER_READ_CAPPED'
              or 'PEER_READ_CAPPED' in str(r.get('error') or '')]
    first_idx = next((i for i, r in enumerate(reads) if r in capped), None)
    after_capped_ok = False
    if first_idx is not None:
        after_capped_ok = any(not r.get('is_error') for r in reads[first_idx + 1:])
    first_ok = ok_reads[0] if ok_reads else {}
    checks = [
        runner.check('delegate_task đã chạy', bool(tool_ends(payload, 'delegate_task')),
                     sorted(set(runner.tools_run(payload)))),
        runner.check('await_children đã chạy', bool(tool_ends(payload, 'await_children')),
                     sorted(set(runner.tools_run(payload)))),
        runner.check('lần đọc đầu trả dữ liệu thật (có events)',
                     bool(first_ok.get('events')), {'window': first_ok.get('window')}),
        runner.check('có lần bị chặn bằng PEER_READ_CAPPED', bool(capped),
                     [str(r.get('error'))[:200] for r in capped] or 'không có'),
        runner.check('không đọc thành công sau khi đã bị chặn', not after_capped_ok,
                     f'cappedAt={first_idx} reads={len(reads)}'),
        runner.check('>= 4 lần đọc thành công trước khi bị chặn (3 lần lặp còn được phép)',
                     len(ok_reads) >= 4, f'okReads={len(ok_reads)}'),
        runner.check('lượt cha kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('peer_read_cap', checks, {
        'session': sid,
        'reads': [{'ok': not r.get('is_error'), 'window': r.get('window'),
                   'errorCode': r.get('errorCode'), 'error': str(r.get('error') or '')[:120]}
                  for r in reads],
    })


def scenario_resume_wait_false(runner):
    """Con bị cắt (trần cha khai) + wait=false: chờ giao (đủ cờ) → child_resume wait=false → chạy lại."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Đây là BÀI KIỂM THỬ GIAO THỨC của harness. Hãy làm ĐÚNG theo thứ tự sau, '
        'kể cả khi kết quả công cụ gợi ý cách khác:\n'
        '1) Gọi delegate_task với role="explore", goal="Liệt kê các tệp .md dưới .plans/ '
        'và trả kết quả đầy đủ.", maxSteps=2, wait=false.\n'
        '2) Gọi await_children NGAY, timeoutSeconds=120 — con sẽ bị cắt vì trần bước và giao '
        'phần đã làm; kết quả phải có status="done" với cờ partial=true, resumable=true.\n'
        '3) Gọi child_resume với sessionId=<sessionId của con ở bước 1>, '
        'note="Hoàn tất danh sách tệp .md và trả kết quả cuối.", wait=false. '
        'Kết quả phải có resumed=true, attempt=1.\n'
        '4) Gọi await_children timeoutSeconds=120 để chờ con chạy lại giao kết quả.\n'
        '5) Trả lời một câu tóm tắt: kết quả lần 1 (bị cắt) và lần 2 (sau khi gọi lại).'), timeout=900)
    resumes = results_of(payload, 'child_resume')
    ok_resume = next((r for r in resumes if r.get('resumed')), {})
    child = latest_child(sid)
    child_id = child['session_id'] if child else ''
    child_msgs = messages_of(child_id) if child_id else []
    resume_briefs = [m for m in child_msgs
                     if m.get('role') == 'user' and 'RESUME (attempt' in str(m.get('content') or '')]
    child_row = rows('select turn_count, status from sessions where id = ?', (child_id,)) if child_id else []
    resumed_events = [e for e in (payload.get('events') or [])
                      if e.get('type') == 'child' and (e.get('data') or {}).get('resumed')]
    detached_events = [e for e in (payload.get('events') or [])
                       if e.get('type') == 'child' and (e.get('data') or {}).get('detached')]
    awaits = results_of(payload, 'await_children')
    done_flat = []
    for a in awaits:
        for item in (a.get('done') or []):
            done_flat.append(item)
    cut_delivery = next((d for d in done_flat if d.get('partial') and d.get('resumable')), {})
    checks = [
        runner.check('await_children đã chạy', bool(tool_ends(payload, 'await_children')),
                     sorted(set(runner.tools_run(payload)))),
        runner.check('giao kết quả lần 1 mang cờ partial/resumable (con bị cắt)',
                     bool(cut_delivery),
                     {k: cut_delivery.get(k) for k in ('status', 'reason', 'partial', 'resumable', 'timedOut')}),
        runner.check('child_resume wait=false trả resumed=true, attempt=1, previous đủ cờ',
                     ok_resume.get('resumed') is True and ok_resume.get('attempt') == 1
                     and isinstance(ok_resume.get('previous'), dict)
                     and ok_resume['previous'].get('resumable') is True,
                     {k: ok_resume.get(k) for k in ('status', 'resumed', 'attempt', 'previous', 'is_error')}),
        runner.check('sổ con mở lại: brief RESUME trong transcript CŨ của chính con',
                     bool(resume_briefs), [str(m.get('content'))[:160] for m in resume_briefs[:1]]),
        runner.check('con chạy lại (turn_count >= 2)', bool(child_row) and child_row[0]['turn_count'] >= 2,
                     child_row[0] if child_row else None),
        runner.check('event child mang resumed=true', bool(resumed_events),
                     [e.get('data') for e in resumed_events[:1]]),
        runner.check('event child lúc con tự đóng (detached) mang cờ partial/resumable',
                     any((e.get('data') or {}).get('partial') and (e.get('data') or {}).get('resumable')
                         for e in detached_events),
                     [{k: (e.get('data') or {}).get(k) for k in
                       ('status', 'reason', 'partial', 'resumable', 'timedOut')} for e in detached_events[:2]]),
        runner.check('hàng sổ con đóng lại sau lần chạy 2 (finished mới, reason còn)',
                     bool(child) and bool(child.get('finished')) and bool(child.get('reason')),
                     {k: child.get(k) for k in ('status', 'reason', 'started', 'finished', 'steps_used')} if child else None),
        runner.check('lượt cha kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('resume_wait_false', checks, {
        'session': sid, 'child': child and {k: child.get(k) for k in
                                            ('session_id', 'status', 'reason', 'started', 'finished', 'steps_used')},
        'resumeResult': {k: ok_resume.get(k) for k in
                         ('status', 'resumed', 'attempt', 'previous', 'is_error', 'reason')},
        'deliveries': [{'status': d.get('status'), 'reason': d.get('reason'), 'partial': d.get('partial'),
                        'resumable': d.get('resumable'), 'timedOut': d.get('timedOut')} for d in done_flat],
    })


def scenario_resume_not_cut(runner):
    """Con ĐANG chạy: child_resume phải bị TỪ CHỐI bằng CHILD_RESUME_NOT_CUT."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Đây là BÀI KIỂM THỬ GIAO THỨC của harness. Hãy làm ĐÚNG theo thứ tự sau, '
        'kể cả khi kết quả công cụ gợi ý cách khác:\n'
        '1) Gọi delegate_task với role="explore", goal="Đọc lần lượt 12 tệp .md dưới .plans/, '
        'mỗi bước ĐÚNG MỘT tệp bằng file_read, đọc xong hết mới trả lời.", wait=false.\n'
        '2) Gọi child_resume NGAY LẬP TỨC với sessionId=<sessionId của con ở bước 1>, '
        'note="Thử gọi lại khi con đang chạy." — lần này sẽ bị TỪ CHỐI với mã '
        'CHILD_RESUME_NOT_CUT (con đang chạy thì không được gọi lại). ĐÓ LÀ ĐIỀU CẦN KIỂM CHỨNG.\n'
        '3) Gọi await_children timeoutSeconds=180 để chờ con tự giao kết quả.\n'
        '4) Trả lời một câu tóm tắt: lần gọi child_resume bị từ chối thế nào.'), timeout=900)
    full = {'events': all_events(runner.base, sid)}
    resumes = results_of(full, 'child_resume')
    refused = [r for r in resumes
               if 'CHILD_RESUME_NOT_CUT' in str(r.get('error') or '')
               or r.get('errorCode') == 'CHILD_RESUME_NOT_CUT']
    # H11 r2 (04/10) — luật đúng là: lần gọi TRONG LÚC CON ĐANG CHẠY phải bị từ chối. Model có thể
    # gọi lại lần nữa SAU khi con đã bị cắt (hợp lệ, `resumed=true`) — bản cũ bắt "không lần nào
    # thành công" nên báo đỏ oan. Nay: lần gọi ĐẦU TIÊN phải bị từ chối, và không có lần thành công
    # nào TRƯỚC lần từ chối đầu tiên.
    first_refused = bool(resumes) and (resumes[0] in refused)
    first_refusal_idx = next((i for i, r in enumerate(resumes) if r in refused), None)
    success_before_refusal = any(r.get('resumed') for r in resumes[:first_refusal_idx or 0])
    checks = [
        runner.check('delegate_task đã chạy', bool(tool_ends(full, 'delegate_task')),
                     sorted(set(runner.tools_run(full)))),
        runner.check('child_resume bị TỪ CHỐI bằng CHILD_RESUME_NOT_CUT khi con đang chạy',
                     bool(refused), [str(r.get('error'))[:200] for r in refused] or
                     [str(r.get('error'))[:200] for r in resumes] or 'không gọi'),
        runner.check('lần gọi ĐẦU TIÊN bị từ chối, không resume thành công nào trước đó',
                     first_refused and not success_before_refusal,
                     [r.get('resumed') for r in resumes]),
        runner.check('lượt cha kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    child = latest_child(sid)
    return runner.record('resume_not_cut', checks, {
        'session': sid,
        'resumeResults': [{'is_error': r.get('is_error'), 'errorCode': r.get('errorCode'),
                           'error': str(r.get('error') or '')[:160]} for r in resumes],
        'child': child and {k: child.get(k) for k in ('session_id', 'status', 'reason')},
    })


def scenario_resume_second_turn(runner):
    """Gọi lại CÙNG một con ở LƯỢT THỨ HAI của cha: `attempt` phải tăng 1 → 2.

    Lỗi cũ (vòng soát H11 #3): số attempt suy từ bộ đếm theo LƯỢT nên lượt sau quay lại 1 —
    với task surface thì trùng `invocationId` (`TASK_INVOCATION_CONFLICT`), không task thì con số
    `attempt` trả về sai. Bộ đếm nay là cả đời con (`child_resume_totals`), id `resume-<con>-<lượt>-<n>`.
    """
    sid = runner.create()
    payload1 = runner.drive(sid, (
        'Đây là BÀI KIỂM THỬ GIAO THỨC của harness. Hãy làm ĐÚNG theo thứ tự sau, '
        'kể cả khi kết quả công cụ gợi ý cách khác:\n'
        '1) Gọi delegate_task với role="explore", goal="Liệt kê các tệp .md dưới .plans/ '
        'và trả kết quả đầy đủ.", maxSteps=2, wait=false.\n'
        '2) Gọi await_children NGAY, timeoutSeconds=120 — con sẽ bị cắt vì trần bước và giao '
        'phần đã làm (partial/resumable), bình thường.\n'
        '3) Gọi child_resume với sessionId=<sessionId của con ở bước 1>, '
        'note="Làm tiếp danh sách tệp.", wait=false. Kết quả phải có resumed=true, attempt=1.\n'
        '4) Gọi await_children timeoutSeconds=300 để chờ con chạy lại giao kết quả. Nếu con CHƯA '
        'giao (timeout), gọi tiếp await_children timeoutSeconds=300 — tối đa 2 lần.\n'
        '5) Trả lời một câu tóm tắt kết quả lần gọi lại thứ nhất.'), timeout=900)
    child = latest_child(sid)
    child_id = child['session_id'] if child else ''
    full1 = {'events': all_events(runner.base, sid)}
    resumes1 = results_of(full1, 'child_resume')
    ok1 = [r for r in resumes1 if r.get('resumed')]
    if not child_id or not ok1:
        checks = [
            runner.check('lượt 1: con được sinh và gọi lại được (attempt=1)',
                         bool(child_id) and bool(ok1),
                         {'child': child_id, 'resumes': [{k: r.get(k) for k in
                                                          ('resumed', 'attempt', 'is_error', 'error')} for r in resumes1]}),
        ]
        return runner.record('resume_second_turn', checks, {'session': sid, 'child': child_id,
                                                            'turn1Status': payload1.get('status')})
    # Lượt 2: gọi lại CHÍNH con đó. Con đã bị cắt lại ở lần chạy 2 (maxSteps=2) nên còn resumable.
    payload2 = runner.drive(sid, (
        'Đây là LƯỢT THỨ HAI của cùng phiên, KHÔNG phải khảo sát mới. Hãy gọi NGAY child_resume với '
        f'sessionId="{child_id}", note="Làm tiếp lần hai.", wait=true. Kết quả phải có resumed=true và '
        'attempt=2 (con số attempt phải TĂNG, không được quay lại 1). Nếu công cụ từ chối, chép '
        'NGUYÊN VĂN lỗi vào câu trả lời. Sau đó trả lời một câu tóm tắt.'), timeout=900)
    # Bằng chứng lượt 2 PHẢI lấy từ sự kiện SAU lượt 1 (phiên dài hơn một trang 500 —
    # `runner.drive` chỉ trả trang đầu, đọc thẳng trang đó là bằng chứng lượt 1 cũ).
    full2 = {'events': all_events(runner.base, sid)}
    t1_end = max([(e.get('seq') or 0) for e in full2['events']
                  if e.get('type') == 'turn_end' and (e.get('data') or {}).get('turn') == 1] or [0])
    turn2 = [e for e in full2['events'] if (e.get('seq') or 0) > t1_end]
    resumes2 = results_of({'events': turn2}, 'child_resume')
    ok2 = [r for r in resumes2 if r.get('resumed')]
    conflicts = [r for r in resumes2 if 'TASK_INVOCATION_CONFLICT' in str(r.get('error') or '')
                 or r.get('errorCode') == 'TASK_INVOCATION_CONFLICT']
    successful = ok1 + ok2
    attempts = [r.get('attempt') for r in successful]
    increasing = all(b == a + 1 for a, b in zip(attempts, attempts[1:]))
    row = rows('select status, reason, started, finished, steps_used from children where session_id = ?',
               (child_id,))
    row = row[0] if row else {}
    child_events2 = [e for e in turn2
                     if e.get('type') == 'child' and (e.get('data') or {}).get('resumed')]
    checks = [
        runner.check('lượt 1: gọi lại được, attempt=1', ok1 and ok1[0].get('attempt') == 1,
                     [{k: r.get(k) for k in ('resumed', 'attempt', 'is_error')} for r in resumes1]),
        runner.check('lượt 1 kết thúc sạch', payload1.get('status') in ('completed', 'idle'),
                     payload1.get('status')),
        runner.check('lượt 2: gọi lại được (resumed=true), attempt=2, không mất attempt',
                     bool(ok2) and ok2[-1].get('attempt') == 2,
                     [{k: r.get(k) for k in ('resumed', 'attempt', 'status', 'is_error')} for r in resumes2]),
        runner.check('không có TASK_INVOCATION_CONFLICT ở lượt 2', not conflicts,
                     [str(r.get('error'))[:200] for r in conflicts] or 'không có'),
        runner.check('chuỗi attempt tăng đều 1,2,... (không tái dùng số cũ)', increasing and attempts[:1] == [1],
                     attempts),
        runner.check('lượt 2 kết thúc sạch', payload2.get('status') in ('completed', 'idle'),
                     payload2.get('status')),
        runner.check('event child ở lượt 2 mang resumed=true', bool(child_events2),
                     [e.get('data') for e in child_events2[:1]]),
        runner.check('hàng sổ con mở lại lần nữa (finished mới)', bool(row.get('finished')),
                     row),
    ]
    return runner.record('resume_second_turn', checks, {
        'session': sid, 'child': child_id,
        'turn2From': t1_end, 'totalEvents': len(full2['events']),
        'resumes1': [{k: r.get(k) for k in ('resumed', 'attempt', 'status', 'is_error')} for r in resumes1],
        'resumes2': [{k: r.get(k) for k in ('resumed', 'attempt', 'status', 'is_error', 'error')} for r in resumes2],
        'attempts': attempts, 'childRow': row,
    })


SCENARIOS = {'await_nudge_cap': scenario_await_nudge_cap,
             'peer_read_cap': scenario_peer_read_cap,
             'resume_wait_false': scenario_resume_wait_false,
             'resume_not_cut': scenario_resume_not_cut,
             'resume_second_turn': scenario_resume_second_turn}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3113')
    parser.add_argument('--label', default='child-caps')
    parser.add_argument('--only', default='')
    parser.add_argument('--db', default=DB,
                        help='SQLite của CHÍNH backend đang kiểm (mặc định: data-on của 3113)')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.list:
        print('\n'.join(sorted(SCENARIOS)))
        return 0
    set_db(args.db)
    runner = Runner(args.base, args.label)
    for name in (args.only.split(',') if args.only else sorted(SCENARIOS)):
        if not name:
            continue
        print(f'== {name}')
        try:
            SCENARIOS[name](runner)
        except Exception as exc:  # noqa: BLE001
            runner.record(name, [runner.check('kịch bản chạy được', False, f'{type(exc).__name__}: {exc}')])
    summary = runner.save()
    print(json.dumps({k: summary[k] for k in ('label', 'total', 'passed', 'failed', 'blocked')},
                     ensure_ascii=False))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
