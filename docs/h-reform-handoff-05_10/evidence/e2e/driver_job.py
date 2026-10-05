"""Kịch bản bổ sung: model SỐNG chạm bề mặt job bền vững của H4 (`BOXFOX_CONTROLLER_JOBS`).

Mở một phiên thật trên backend đang BẬT công tắc job, bắt model gọi `start_job`
(kind=model, ownership=controller) rồi đọc lại bằng `get_job`; kiểm hàng thật trong
SQLite của CHÍNH instance đang kiểm (không tin lời kể của model).

Chạy: python3 /code/.generated_artifacts/e2e/driver_job.py --base 3116 \
        --label enable-step4 --db /var/tmp/boxfox-enable/data/sessions.sqlite
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Runner  # noqa: E402

DB = '/var/tmp/boxfox-enable/data/sessions.sqlite'
INVOCATION = 'e2e-job-1'
ROUTE = None


def rows(sql, args=()):
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()


def scenario_start_job(runner):
    sid = runner.create(ROUTE or None)
    payload = runner.drive(sid, (
        'Làm ĐÚNG hai bước, theo thứ tự:\n'
        '1) Gọi ĐÚNG MỘT lần `start_job` với các tham số: kind="model", role="explore", '
        f'ownership="controller", invocationId="{INVOCATION}", '
        'goal="Đếm số tệp .md dưới .plans/ và nêu một đường dẫn làm bằng chứng".\n'
        '2) Gọi `get_job` với `jobId` mà bước 1 trả về để đọc trạng thái job.\n'
        'Sau đó trả lời đúng một câu: job đang ở trạng thái nào. KHÔNG tự làm lấy việc đếm.'), timeout=900)
    tools = runner.tools_run(payload)
    jobs = rows('select job_id, controller_id, owner_id, kind, ownership, state, revision, closed_at '
                'from harness_jobs where owner_id = ?', (sid,))
    children = rows('select id, parent_id, role, status from sessions where parent_id = ?', (sid,))
    checks = [
        runner.check('start_job đã chạy', 'start_job' in tools, sorted(set(tools))),
        runner.check('get_job đã chạy', 'get_job' in tools, sorted(set(tools))),
        runner.check('không có JOB_SURFACE_OFF trong kết quả', 'JOB_SURFACE_OFF' not in json.dumps(payload),
                     'không thấy mã lỗi'),
        runner.check('có hàng job bền vững do model sống tạo', bool(jobs),
                     [{'job': j['job_id'][:12], 'state': j['state'], 'kind': j['kind'],
                       'ownership': j['ownership']} for j in jobs]),
        runner.check('job gắn phiên con thật', bool(children),
                     [{'session': c['id'][:12], 'role': c['role'], 'status': c['status']} for c in children]),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('start_job', checks,
                         {'session': sid, 'tools': sorted(set(tools)), 'jobs': jobs[:2],
                          'children': children[:2], 'answer': runner.answer(payload)[:200]})


SCENARIOS = {'start_job': scenario_start_job}


def main():
    global DB, ROUTE
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3116')
    parser.add_argument('--label', default='enable-step4')
    parser.add_argument('--only', default='')
    parser.add_argument('--db', default=DB)
    parser.add_argument('--model', default='', help='ghim modelId (model miễn phí) cho phiên kiểm')
    parser.add_argument('--connection', default='d7e26488-65b0-4012-8009-589cd94b324b',
                        help='connectionId đi kèm --model')
    parser.add_argument('--attempts', type=int, default=2,
                        help='số lần chạy mỗi kịch bản (model miễn phí hay phiên âm sai)')
    parser.add_argument('--list', action='store_true')
    args = parser.parse_args()
    if args.list:
        print('\n'.join(sorted(SCENARIOS)))
        return 0
    DB = args.db
    ROUTE = {'modelId': args.model, 'connectionId': args.connection} if args.model else None
    runner = Runner(args.base, args.label)
    for name in (args.only.split(',') if args.only else sorted(SCENARIOS)):
        if not name:
            continue
        for attempt in range(1, args.attempts + 1):
            print(f'== {name} (lần {attempt}/{args.attempts})')
            try:
                entry = SCENARIOS[name](runner)
            except Exception as exc:  # noqa: BLE001
                entry = runner.record(name, [runner.check('kịch bản chạy được', False,
                                                          f'{type(exc).__name__}: {exc}')])
            if entry['status'] == 'PASSED' or attempt == args.attempts:
                break
            # Lần hỏng vẫn phải còn trong bằng chứng: đổi tên tệp trước khi chạy lại.
            (runner.out / f'{name}.json').rename(runner.out / f'{name}.attempt{attempt}.json')
            runner.results.pop()
            print(f'  [retry] {name} hỏng ở lần {attempt} — chạy lại (model yếu hay phiên âm sai)')
        entry['evidence']['attempts'] = attempt
        (runner.out / f'{name}.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    summary = runner.save()
    print(json.dumps({k: summary[k] for k in ('label', 'total', 'passed', 'failed', 'blocked')},
                     ensure_ascii=False))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
