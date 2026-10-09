"""H10 — drill rollback / kill switch (offline, không gọi model, không tốn phí).

Chứng minh ba điều:
1. Công tắc TẮT (mặc định): lượt thật không thấy công cụ `task_*`, `dispatch` từ chối
   `TASK_SURFACE_OFF`, và KHÔNG bảng `harness_*` nào được tạo.
2. Dữ liệu đã ghi khi công tắc BẬT vẫn đọc được nguyên vẹn sau khi tắt (không mất task/attempt).
3. Tắt công tắc không replay mutation: lời gọi lại bị từ chối trước khi chạm kho; bảng cũ
   (`sessions`, `children`, ...) và `PRAGMA user_version` không đổi; không grant/verdict mới.
"""
import asyncio
import copy
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else '/code/.worktrees/boxfox-harness-reform')
sys.path.insert(0, str(ROOT / 'backend' / 'src'))

from agentbox.agent_core import task_surface  # noqa: E402
from agentbox.agent_core.orchestration_contracts import TASK_SCHEMA  # noqa: E402
from agentbox.agent_core.runtime import HarnessRuntime  # noqa: E402
from agentbox.agent_core.task_service import TaskService  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402

CHECKS = []


def check(name, ok, detail=''):
    CHECKS.append({'check': name, 'ok': bool(ok), 'detail': detail})
    print(f"{'PASS' if ok else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")


def tables(db):
    return sorted(r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'"))


def schema_of(db, names):
    out = {}
    for name in names:
        row = db.execute('SELECT sql FROM sqlite_master WHERE name=?', (name,)).fetchone()
        out[name] = row['sql'] if row else None
    return out


def counts(db, names):
    return {n: db.execute(f'SELECT COUNT(*) AS c FROM {n}').fetchone()['c'] for n in names}


def request(**updates):
    value = {'schema': TASK_SCHEMA, 'taskId': 'drill-rollback', 'invocationId': 'inv-drill',
             'role': 'explore', 'goal': 'Rollback drill receipt.', 'intent': 'analysis',
             'mode': 'read_only', 'inputs': [],
             'scope': {'read': ['backend/src'], 'write': [], 'externalSources': 'none'},
             'deliverable': {'kind': 'knowledge', 'format': 'markdown', 'evidence': ['file_line'],
                             'acceptance': ['Keep the receipt.']},
             'dependsOn': [], 'budget': {'allocationPolicy': 'inherited'}}
    value.update(updates)
    return value


def main():
    tmp = Path(tempfile.mkdtemp(prefix='rollback-drill-', dir='/var/tmp'))
    store = SessionStore(tmp / 'sessions.db')
    db = store.db
    db.row_factory = sqlite3.Row
    owner = store.create({'skills': []})['id']
    legacy = ['sessions', 'children', 'events', 'messages']
    legacy_schema_before = schema_of(db, legacy)
    user_version_before = db.execute('PRAGMA user_version').fetchone()[0]
    grant_tables = [t for t in tables(db) if 'grant' in t or 'verdict' in t]
    grant_counts_before = counts(db, grant_tables) if grant_tables else {}
    harness_before = [t for t in tables(db) if t.startswith('harness_')]

    # --- 1. Công tắc TẮT (mặc định) -----------------------------------------------------
    os.environ.pop('BOXFOX_TASK_SURFACE', None)
    rt = HarnessRuntime(store, executor=None)
    profile = rt.turn_profile(store.get(owner))
    check('switch off: lượt không thấy công cụ task',
          not (set(profile['tools']) & task_surface.TASK_TOOLS), str(sorted(profile['tools'])[:3]))
    try:
        asyncio.run(rt.dispatch(store.get(owner), 'task_get', {'runId': 'run-1', 'taskId': 'x'}))
        check('switch off: dispatch từ chối', False, 'không ném lỗi')
    except PermissionError as exc:
        check('switch off: dispatch từ chối TASK_SURFACE_OFF', 'TASK_SURFACE_OFF' in str(exc),
              str(exc)[:80])
    except Exception as exc:  # noqa: BLE001
        check('switch off: dispatch từ chối TASK_SURFACE_OFF', False, repr(exc)[:80])
    check('switch off: không tạo bảng harness_*', not [t for t in tables(db) if t.startswith('harness_')])

    # --- 2. BẬT công tắc: ghi task/attempt/message thật ---------------------------------
    os.environ['BOXFOX_TASK_SURFACE'] = 'on'
    runs = {'run-1': {'runId': 'run-1', 'sessionId': owner}}
    service = TaskService(store, lambda owner_id, run_id: copy.deepcopy(runs.get(run_id))
                          if runs.get(run_id, {}).get('sessionId') == owner_id else None)
    item = service.create(owner, 'run-1', request(), controller_id=owner)
    child = store.create({'skills': []}, role='explore', parent_id=owner)['id']
    store.child_start(child, owner, 1, 2, 'explore', 'drill')
    service.record_attempt(owner, 'run-1', item['taskKey'], invocation_id='inv-drill-attempt',
                           expected_revision=item['revision'], session_id=child,
                           admission_id='adm-drill', capability_epoch=1)
    service.send(owner, 'run-1', item['taskKey'], invocation_id='inv-drill-msg',
                 expected_revision=service.get(owner, 'run-1', item['taskKey'])['revision'],
                 message_id='msg-drill', kind='information', body='giữ biên nhận', sender_id=owner)
    harness_tables = [t for t in tables(db) if t.startswith('harness_')]
    before = counts(db, harness_tables)
    detail_before = service.get(owner, 'run-1', item['taskKey'])
    payload_before = hashlib.sha256(json.dumps(detail_before, sort_keys=True,
                                               ensure_ascii=False).encode()).hexdigest()
    check('switch on: ghi được task + attempt + message',
          before.get('harness_tasks') == 1 and before.get('harness_task_attempts') == 1
          and before.get('harness_task_messages') == 1, json.dumps(before))

    # --- 3. TẮT lại: dữ liệu còn nguyên, không replay mutation --------------------------
    os.environ.pop('BOXFOX_TASK_SURFACE', None)
    check('switch off again: lượt thôi thấy công cụ task',
          not (set(rt.turn_profile(store.get(owner))['tools']) & task_surface.TASK_TOOLS))
    try:
        asyncio.run(rt.dispatch(store.get(owner), 'task_abandon',
                                {'runId': 'run-1', 'taskId': item['taskId'], 'reason': 'replay?'}))
        check('switch off again: mutation bị từ chối, không replay', False, 'không ném lỗi')
    except PermissionError as exc:
        check('switch off again: mutation bị từ chối, không replay', 'TASK_SURFACE_OFF' in str(exc),
              str(exc)[:80])
    after = counts(db, harness_tables)
    detail_after = service.get(owner, 'run-1', item['taskKey'])
    payload_after = hashlib.sha256(json.dumps(detail_after, sort_keys=True,
                                              ensure_ascii=False).encode()).hexdigest()
    check('rollback: dữ liệu task đọc được, không mất hàng', after == before, json.dumps(after))
    check('rollback: nội dung task không đổi (không replay mutation)',
          payload_before == payload_after and detail_after['revision'] == detail_before['revision'],
          f"rev {detail_before['revision']} -> {detail_after['revision']}")
    check('rollback: bảng cũ không đổi schema', schema_of(db, legacy) == legacy_schema_before)
    check('rollback: PRAGMA user_version không đổi',
          db.execute('PRAGMA user_version').fetchone()[0] == user_version_before)
    if grant_tables:
        check('rollback: không grant/verdict mới', counts(db, grant_tables) == grant_counts_before,
              json.dumps(counts(db, grant_tables)))
    else:
        check('rollback: không bảng grant/verdict nào sinh ra', True, 'không có bảng')

    store.close()
    failed = [c for c in CHECKS if not c['ok']]
    print(f"\nTOTAL {len(CHECKS)} checks, {len(CHECKS) - len(failed)} passed, {len(failed)} failed")
    print('harness_before=' + json.dumps(harness_before))
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
