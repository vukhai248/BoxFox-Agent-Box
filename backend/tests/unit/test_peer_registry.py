"""Sổ con, biên nhận giao hàng, bộ đếm lượt và toạ độ (lượt, bước) của con (vòng 22, T1+T3).

Bộ kiểm này cố ý mở **DB theo schema CŨ** (đúng ba bảng của bản trước) để chứng minh di trú chỉ
ghi thêm: hàng cũ đọc được, bảng mới có mặt, và mở lần thứ hai không đổi gì. Phần cuối kiểm
việc cha ghi sổ con ngay lúc sinh con, với cặp (lượt, bước) khớp cả hai event `child`.
"""
import asyncio
import json
import sqlite3
import time

import pytest

from agentbox.memory.session_store import SessionStore


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


def old_database(path):
    """DB y hệt bản trước T1: chỉ `sessions`/`events`/`checkpoints`, cộng một hàng phiên cũ."""
    db = sqlite3.connect(path)
    db.executescript('''
        CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_id TEXT, role TEXT NOT NULL,
            config TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'idle', updated REAL NOT NULL);
        CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
            messages TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL);
    ''')
    db.execute("INSERT INTO sessions(id,role,config,status,updated) VALUES('old-1','orchestrator','{}','idle',1.0)")
    db.commit()
    db.close()
    return path


def test_schema_cu_mo_bang_ma_moi_khong_mat_gi(tmp_path):
    path = old_database(tmp_path / 'sessions.db')
    store = SessionStore(path)
    tables = {row['name'] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'children', 'child_deliveries'} <= tables
    columns = {row['name'] for row in store.db.execute('PRAGMA table_info(sessions)')}
    assert 'turn_count' in columns
    assert store.get('old-1')['role'] == 'orchestrator', 'hàng cũ vẫn đọc được'
    assert store.get('old-1')['turn_count'] == 0, 'phiên cũ chưa có lượt nào'
    store.close()

    again = SessionStore(path)
    assert again.get('old-1')['turn_count'] == 0
    again.close()


def test_begin_turn_dem_mot_chieu(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    sid = store.create({'skills': []})['id']
    assert [store.begin_turn(sid) for _ in range(3)] == [1, 2, 3]
    assert store.get(sid)['turn_count'] == 3
    with pytest.raises(KeyError):
        store.begin_turn('khong-co-phien-nay')
    store.close()


def test_hang_so_con_di_tron_vong_doi(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    parent = store.create({'skills': []})['id']
    child = store.create({'skills': []}, role='testing', parent_id=parent)['id']

    store.child_start(child, parent, 2, 5, 'testing', goal='kiểm phần upload')
    row = store.child(child)
    assert (row['parent_id'], row['parent_turn'], row['spawn_step']) == (parent, 2, 5)
    assert row['role'] == 'testing' and row['status'] == 'started' and row['goal'] == 'kiểm phần upload'
    assert [r['session_id'] for r in store.children_of(parent)] == [child]
    assert [r['session_id'] for r in store.children_of(parent, turn=2)] == [child]
    assert store.children_of(parent, turn=3) == []
    assert [r['session_id'] for r in store.live_children(parent)] == [child]

    store.child_wait(child, ['role:review'], time.time())
    assert store.child(child)['waiting_for'] == ['role:review']

    store.child_finish(child, 'partial', reason='STEP_BUDGET_EXHAUSTED', steps_used=40,
                       output_tokens=1234, answer_chars=465)
    row = store.child(child)
    assert (row['status'], row['reason'], row['steps_used'], row['output_tokens']) == \
        ('partial', 'STEP_BUDGET_EXHAUSTED', 40, 1234)
    assert row['answer_chars'] == 465 and row['finished'] is not None
    assert row['waiting_for'] == [] and row['waiting_since'] is None, 'chờ xong thì ghi lại là hết chờ'
    assert store.live_children(parent) == []

    store.child_finish(child, 'failed', reason='WATCHDOG_TIMEOUT')
    row = store.child(child)
    assert (row['status'], row['reason']) == ('partial', 'STEP_BUDGET_EXHAUSTED'), \
        'lần gọi thứ hai không ghi đè hàng đã đóng'
    store.close()


def test_bien_nhan_giao_hang_khong_the_giao_hai_lan(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    parent = store.create({'skills': []})['id']
    child = store.create({'skills': []}, role='review', parent_id=parent)['id']
    store.child_start(child, parent, 1, 3, 'review', goal='soát')

    first = store.queue_delivery(child, 'peer-sid-2', 1, 'peer', chars=120, truncated=False)
    again = store.queue_delivery(child, 'peer-sid-2', 1, 'peer', chars=120, truncated=False)
    assert first['id'] == again['id'], 'cùng (con, người nhận, lượt) ⇒ đúng một hàng'
    assert store.deliveries_of(child) == [first] or len(store.deliveries_of(child)) == 1

    other_turn = store.queue_delivery(child, 'peer-sid-2', 2, 'peer', chars=90, truncated=True)
    assert other_turn['id'] != first['id']

    assert [r['id'] for r in store.pending_deliveries('peer-sid-2')] == [first['id'], other_turn['id']]
    assert store.pending_deliveries('peer-sid-2', limit=1)[0]['id'] == first['id']

    done = store.mark_delivered(first['id'])
    assert done['state'] == 'injected' and done['injected'] is not None
    assert store.mark_delivered(first['id'])['state'] == 'injected', 'gọi lại không đổi gì thêm'
    assert [r['id'] for r in store.pending_deliveries('peer-sid-2')] == [other_turn['id']]

    skipped = store.mark_delivered(other_turn['id'], state='skipped', skip_reason='recipient_not_running')
    assert skipped['skip_reason'] == 'recipient_not_running'
    with pytest.raises(ValueError):
        store.mark_delivered(other_turn['id'], state='bịa')

    receipts = store.child_delivery_receipts(child)
    assert receipts == [
        {'recipient': 'peer-sid-2', 'state': 'injected', 'chars': 120, 'truncated': False},
        # T11 thêm `reason`: biên nhận bỏ qua phải nói VÌ SAO, nếu không thì "không giao được" và
        # "người nhận đã xong" trông giống nhau trong sổ.
        {'recipient': 'peer-sid-2', 'state': 'skipped', 'chars': 90, 'truncated': True,
         'reason': 'recipient_not_running'},
    ]
    assert store.child_set_deliveries(child, receipts)['deliveries'] == receipts
    store.close()


def test_xoa_phien_thi_so_con_di_theo(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    parent = store.create({'skills': []})['id']
    child = store.create({'skills': []}, role='review', parent_id=parent)['id']
    store.child_start(child, parent, 1, 1, 'review', goal='soát')
    store.queue_delivery(child, 'peer-x', 1, 'peer', chars=10)

    assert store.delete(parent) is True
    assert store.child(child) is None
    assert store.deliveries_of(child) == []
    assert store.db.execute('SELECT COUNT(*) AS n FROM child_deliveries').fetchone()['n'] == 0
    store.close()


# --------------------------------------------------------------------------- #
# T3 — cha ghi sổ con NGAY khi sinh con; cặp (lượt, bước) nằm trong cả hai event
# --------------------------------------------------------------------------- #

def answer(text='done', calls=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return next(self.responses)


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def run_parent_with_a_delegation_on_turn_two(tmp_path):
    """Lượt 1 không giao việc, lượt 2 mới giao: toạ độ lượt của con phải là 2, không phải 1.

    Con mang vai `explore` — vai main CÒN giao được; vai `research`/`research-review` đã bị cổng
    Research vô điều kiện chặn từ main (`RESEARCH_MAIN_READ_ONLY`)."""
    from agentbox.agent_core.runtime import HarnessRuntime

    store = SessionStore(tmp_path / 'sessions.db')
    model = FixtureModel([answer('lượt một xong'),
                          answer(calls=[call('delegate_task', {'role': 'explore', 'goal': 'tra cứu'})]),
                          answer('con trả lời'),
                          answer('cha chốt')])
    runtime = HarnessRuntime(store, FixtureExecutor(), model)
    sid = runtime.create({'skills': [], 'subagents': [{'id': 'explore', 'enabled': True}]})['id']

    async def run():
        await runtime.submit(sid, 'lượt một')
        await runtime.tasks[sid]
        await runtime.submit(sid, 'lượt hai')
        await runtime.tasks[sid]

    asyncio.run(run())
    child_events = [event['data'] for event in store.events(sid) if event['type'] == 'child']
    return store, sid, child_events


def test_hai_event_child_mang_dung_luot_va_buoc_cua_cha(tmp_path):
    store, sid, child_events = run_parent_with_a_delegation_on_turn_two(tmp_path)
    started, finished = child_events[0], child_events[-1]

    assert (started['status'], started['turn'], started['step']) == ('started', 2, 1)
    assert (finished['turn'], finished['step']) == (2, 1), \
        'cả hai event mang cùng toạ độ: lượt 2 của CHA, bước 1'
    assert started['sessionId'] == finished['sessionId']
    assert started['deliverTo'] == [] and started['wait'] is True, \
        'T6/T11 điền nghĩa; T3 chỉ mang trường đi'
    assert finished['status'] == 'completed' and finished['stepsUsed'] >= 1
    assert finished['answerChars'] == len('con trả lời')
    assert isinstance(finished['wallMs'], int) and finished['wallMs'] >= 0
    store.close()


def test_hang_so_con_khop_voi_hai_event_child(tmp_path):
    store, sid, child_events = run_parent_with_a_delegation_on_turn_two(tmp_path)
    started, finished = child_events[0], child_events[-1]

    assert store.children_of(sid, turn=1) == [], 'lượt 1 không giao việc ⇒ không có hàng sổ con nào'
    rows = store.children_of(sid, turn=2)
    assert len(rows) == 1
    row = rows[0]
    assert (row['session_id'], row['parent_id'], row['role']) == (started['sessionId'], sid, 'explore')
    assert row['status'] == finished['status'] == 'completed'
    assert row['spawn_step'] == 1 and row['steps_used'] == finished['stepsUsed']
    assert row['answer_chars'] == finished['answerChars']
    assert row['finished'] is not None and store.live_children(sid) == [], 'con đã đóng, không còn sống'
    store.close()
