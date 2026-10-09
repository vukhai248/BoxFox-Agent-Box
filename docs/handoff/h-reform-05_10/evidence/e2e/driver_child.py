"""Kịch bản H11: con bị CẮT bằng trần cha khai (maxSteps thấp) → cha gọi lại bằng `child_resume`.

Kiểm đúng đường #6547: gọi lại CHÍNH con đó, giữ nguyên ngữ cảnh cũ, cha quyết định bằng `note`.
Bằng chứng đọc từ DB thật của backend BẬT công tắc + transcript con trong `sessions.messages`.

Chạy: python3 /code/.generated_artifacts/e2e/driver_child.py --base 3113 --label child
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Runner  # noqa: E402

DB = '/var/tmp/boxfox-e2e/data-on/sessions.sqlite'


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


def scenario_cut_then_resume(runner):
    sid = runner.create()
    payload = runner.drive(sid, (
        'Bạn là main. Làm ĐÚNG ba bước, theo thứ tự:\n'
        '1) Gọi delegate_task với role="explore", goal="Liệt kê các tệp .md dưới .plans/", '
        'maxSteps=2, wait=true.\n'
        '2) Con sẽ bị cắt giữa chừng (kết quả có partial=true, resumable=true). Hãy gọi child_resume '
        'với sessionId=<sessionId của con trong kết quả bước 1>, note="Hoàn tất danh sách tệp .md '
        'và trả kết quả cuối."\n'
        '3) Tóm tắt kết quả cuối trong một câu.'), timeout=1500)
    tools = runner.tools_run(payload)
    children = rows('select * from children where parent_id = ? order by started desc', (sid,))
    child = children[0] if children else None
    child_id = child['session_id'] if child else ''
    child_msgs = messages_of(child_id) if child_id else []
    resume_briefs = [m for m in child_msgs
                     if m.get('role') == 'user' and 'RESUME (attempt' in str(m.get('content') or '')]
    child_turns = rows('select turn_count, status from sessions where id = ?', (child_id,)) if child_id else []
    resumed_events = [e for e in (payload.get('events') or [])
                      if e.get('type') == 'child' and (e.get('data') or {}).get('resumed')]
    checks = [
        runner.check('delegate_task đã chạy', 'delegate_task' in tools, sorted(set(tools))),
        runner.check('child_resume đã chạy', 'child_resume' in tools, sorted(set(tools))),
        runner.check('có con bị cắt thật (reason khác null)', bool(child) and bool(child.get('reason')),
                     {k: child.get(k) for k in ('session_id', 'status', 'reason', 'steps_used')} if child else None),
        runner.check('sổ con mở lại: có brief RESUME trong transcript CŨ của chính con đó',
                     bool(resume_briefs),
                     [str(m.get('content'))[:160] for m in resume_briefs[:1]]),
        runner.check('con chạy lại (turn_count >= 2)', bool(child_turns) and child_turns[0]['turn_count'] >= 2,
                     child_turns[0] if child_turns else None),
        runner.check('event child mang resumed=true', bool(resumed_events),
                     [e.get('data') for e in resumed_events[:1]]),
        runner.check('lượt cha kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
        runner.check('có câu trả lời tổng hợp', bool(runner.answer(payload).strip()),
                     runner.answer(payload)[:200]),
    ]
    return runner.record('cut_then_resume', checks,
                         {'session': sid, 'child': child, 'childTurns': child_turns,
                          'resumeBriefs': len(resume_briefs), 'tools': sorted(set(tools))})


SCENARIOS = {'cut_then_resume': scenario_cut_then_resume}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3113')
    parser.add_argument('--label', default='child')
    parser.add_argument('--only', default='')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.list:
        print('\n'.join(sorted(SCENARIOS)))
        return 0
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
