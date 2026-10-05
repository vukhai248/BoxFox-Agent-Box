"""Kịch bản bổ sung: model SỐNG chạm được đường task bền vững của H3 (vá `fcc6819`).

Trước `fcc6819`, schema `delegate_task` không khai `task`/`runId`, nên model thật
không thể tạo hàng task bền vững — bề mặt H3 chỉ chạy được khi test gọi thẳng.
Kịch bản này bắt model gọi `delegate_task` KÈM hợp đồng `boxfox-task-contract/1`
và kiểm hàng thật trong SQLite của backend BẬT công tắc.

Chạy: python3 /code/.generated_artifacts/e2e/driver_task.py --base 3113 --label task
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Runner  # noqa: E402

DB = '/var/tmp/boxfox-e2e/data-on/sessions.sqlite'
ROUTE = None
TASK_ID = 'e2e-durable-count'
INVOCATION = 'e2e-inv-1'


def rows(sql, args=()):
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql, args)]
    finally:
        db.close()


def scenario_delegate_contract(runner):
    route = ROUTE or None
    contract = {
        'schema': 'boxfox-task-contract/1', 'taskId': TASK_ID, 'invocationId': INVOCATION,
        'role': 'explore', 'goal': 'Đếm số tệp .md nằm dưới .plans/ và nêu đường dẫn.',
        'intent': 'analysis', 'mode': 'read_only', 'inputs': [],
        'scope': {'read': ['.plans'], 'write': [], 'externalSources': 'none'},
        'deliverable': {'kind': 'knowledge', 'format': 'markdown', 'evidence': ['file_line'],
                        'acceptance': ['Nêu đúng danh sách đường dẫn .md']},
        'dependsOn': [], 'budget': {'allocationPolicy': 'inherited'},
    }
    sid = runner.create(route)
    payload = runner.drive(sid, (
        'Làm ĐÚNG hai bước, theo thứ tự:\n'
        '1) Gọi `work_graph` với action="create" và goal="Đếm tệp .md dưới .plans/ để kiểm bề mặt task".\n'
        '2) Gọi ĐÚNG MỘT lần delegate_task với tham số `task` là hợp đồng JSON sau (giữ nguyên khoá, '
        'có thể sửa `goal`):\n' + json.dumps(contract, ensure_ascii=False) + '\n'
        'Tham số `role` = "explore", `goal` mô tả việc đếm tệp .md dưới .plans/. '
        'KHÔNG truyền `runId` (bề mặt tự lấy run đang mở). '
        'CHÚ Ý KIỂU DỮ LIỆU (sai kiểu là bị từ chối): `inputs`, `dependsOn`, `scope.write` là '
        'MẢNG RỖNG `[]`; `scope.read` là mảng một phần tử; `deliverable.evidence` là mảng '
        '`["file_line"]`; `deliverable.acceptance` là mảng một phần tử. TUYỆT ĐỐI không bọc '
        'mảng trong `{"item": ...}`, không viết `""` cho mảng; giữ `inputs` LUÔN có mặt. '
        'Nếu harness từ chối đúng một trường, sửa CHỈ trường đó rồi gọi lại một lần. '
        'KHÔNG tự làm lấy. Sau khi con trả lời, tóm tắt lại kết quả trong một câu.'), timeout=900)
    tools = runner.tools_run(payload)
    tasks = rows('select * from harness_tasks where task_alias = ?', (TASK_ID,))
    attempts = rows('select * from harness_task_attempts where task_key = ?',
                    (tasks[0]['task_key'],)) if tasks else []
    checks = [
        runner.check('work_graph đã mở run', 'work_graph' in tools, sorted(set(tools))),
        runner.check('delegate_task đã chạy', 'delegate_task' in tools, sorted(set(tools))),
        runner.check('có hàng task bền vững do model sống tạo', bool(tasks),
                     [{'task_key': t.get('task_key'), 'task_alias': t.get('task_alias'),
                       'run_id': t.get('run_id'), 'revision': t.get('revision'),
                       'state': t.get('state')} for t in tasks]),
        runner.check('attempt gắn vào phiên con thật', bool(attempts),
                     [{'attempt': a.get('attempt_seq'), 'session': a.get('session_id'),
                       'status': a.get('status'), 'reason': a.get('reason')} for a in attempts]),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
        runner.check('có câu trả lời tổng hợp', bool(runner.answer(payload).strip()),
                     runner.answer(payload)[:200]),
    ]
    return runner.record('delegate_contract', checks,
                         {'session': sid, 'taskId': TASK_ID, 'tasks': tasks[:2], 'attempts': attempts[:2]})


SCENARIOS = {'delegate_contract': scenario_delegate_contract}


def main():
    global DB, TASK_ID, INVOCATION, ROUTE
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3113')
    parser.add_argument('--label', default='task')
    parser.add_argument('--only', default='')
    parser.add_argument('--db', default=DB, help='SQLite của CHÍNH instance đang kiểm')
    parser.add_argument('--task-id', default=TASK_ID, help='taskId trong hợp đồng (đổi để chạy lại sạch)')
    parser.add_argument('--invocation', default=INVOCATION,
                        help='invocationId = khoá idempotency của hợp đồng')
    parser.add_argument('--model', default='', help='ghim modelId (model miễn phí khác) cho phiên kiểm')
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
    TASK_ID = args.task_id
    INVOCATION = args.invocation
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
