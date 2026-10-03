"""Vòng 22 đợt 2, hậu kiểm — vòng đời slot fan-out và hai đường giao hàng.

Ba lỗi tìm thấy khi soát lại phần backend, mỗi lỗi một tính chất được ghim ở đây:

1. **Slot nhả hai lần.** Watchdog (T10) nhả slot ngay lúc huỷ task, rồi callback lúc task đóng nhả
   lần nữa; `asyncio.Semaphore` không cấm nhả thừa, nên trần toàn cục (8) và trần theo cha (3) cùng
   bị vượt trong im lặng. Bộ kiểm này chạy `PeerWatchdog.sweep()` trên một `HarnessRuntime` THẬT
   (không phải runtime giả) và đọc thẳng giá trị hai tầng semaphore.
2. **Giao hàng hỏng làm mất event kết thúc.** Đường `wait=true` phát event `child` SAU khi giao
   hàng; một lỗi ở giữa (SQLite khoá, đĩa đầy) làm luồng cha không bao giờ thấy con đã đóng, và lỗi
   hạ tầng đội lốt lỗi của lời gọi tool.
3. **`deliverTo: ['main']` không đánh thức người đang chờ.** Đường không khai gì đã đánh thức; nhánh
   `main` thì không, nên lượt chờ thêm một nhịp quét.

Và một lỗi thứ tư, cùng họ với (1): một lần xếp hàng bị HUỶ (người dùng bấm dừng, lượt cha đóng)
để lại slot của cha đã mua mà không có con nào tiêu nó.
"""
import asyncio
import json
import time

import pytest

from agentbox.agent_core.limits import (CHILD_WALL_MAX_SECONDS, FANOUT_GLOBAL_CEILING, FANOUT_PER_PARENT_DEFAULT,
                                       WATCHDOG_TIMEOUT_REASON)
from agentbox.agent_core.peer_watchdog import PeerWatchdog
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

ARGS = {'role': 'review', 'goal': 'soát'}
GOAL = 'việc của con'


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


class FixtureModel:
    def __init__(self, parent_responses=(), child_responses=()):
        self.parent_responses = iter(parent_responses)
        self.child_responses = iter(child_responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        first_user = next((str(message.get('content') or '') for message in messages
                           if message.get('role') == 'user'), '')
        if GOAL in first_user:
            return next(self.child_responses)
        return next(self.parent_responses)


def answer(text='done', calls=None, usage=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': usage or {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


def build(tmp_path, parents=1, model=None, values=None):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), model)
    base = {'skills': [], 'subagents': [{'id': 'review', 'enabled': True}], **(values or {})}
    sessions = [runtime.create(dict(base)) for _ in range(parents)]
    return store, runtime, sessions


def long_lived_start(runtime, seconds=30):
    """`start` giả: Task THẬT (và có ĐĂNG KÝ vào `runtime.tasks` như bản thật) để `done_callback`
    có chỗ bám và watchdog tìm thấy task mà huỷ — task không tự xong trong lúc test chạy."""
    def start(sid, prompt):
        async def run():
            await asyncio.sleep(seconds)
            return 'kết quả giả'
        task = asyncio.ensure_future(run())
        runtime.tasks[sid] = task
        return task
    return start


# --------------------------------------------------------------------------- #
# 1. Slot nhả đúng một lần
# --------------------------------------------------------------------------- #

def test_watchdog_huy_con_qua_han_chi_nha_mot_slot(tmp_path):
    """Watchdog đóng con quá hạn ⇒ mỗi con nhả ĐÚNG MỘT slot, cả hai tầng trần giữ nguyên."""
    store, runtime, sessions = build(tmp_path)
    sid = sessions[0]['id']
    runtime.start = long_lived_start(runtime)

    async def run():
        children = [await runtime.delegate(sessions[0], {**ARGS, 'wait': False}) for _ in range(3)]
        assert runtime.global_child_slots._value == FANOUT_GLOBAL_CEILING - 3
        assert runtime.parent_running[sid] == 3
        # Cha đang chạy lượt (đúng cảnh thật của một con đang sống), và CHỈ con đầu quá `wall_max`:
        # mốc `started` của con là dữ liệu, nên đẩy lùi nó là đủ để chạm luật 1.
        store.save(sid, sessions[0]['messages'], 'running')
        aged = children[0]['sessionId']
        # Tuổi phải quá trần TƯỜNG hiện hành (#6457: 4500 s), không phải con số 1 300 cũ.
        store.db.execute('UPDATE children SET started=? WHERE session_id=?',
                         (time.time() - (CHILD_WALL_MAX_SECONDS + 100), aged))
        watchdog = PeerWatchdog(store, runtime=runtime)
        watchdog.first_scan = False   # luật 4 (RESTART) chỉ đúng ở nhịp ĐẦU của một tiến trình

        report = watchdog.sweep()

        assert report['timeout'] == [aged], 'con quá `wall_max` bị huỷ ở luật 1'
        assert report['orphan'] == [], 'cha còn sống thì con không mồ côi'
        assert runtime.global_child_slots._value == FANOUT_GLOBAL_CEILING - 2, \
            'nhả đúng một slot: nhả thừa là trần thật vượt trần khai (11 > 8)'
        assert runtime.parent_running[sid] == 2
        assert aged not in runtime.tasks and aged not in runtime.child_slot_holders
        assert store.child(aged)['reason'] == WATCHDOG_TIMEOUT_REASON

        # Hai con còn lại đóng bằng chính callback của chúng: huỷ task rồi để vòng lặp chạy callback.
        for child in children[1:]:
            runtime.tasks[child['sessionId']].cancel()
        await asyncio.sleep(0.05)

        assert runtime.global_child_slots._value == FANOUT_GLOBAL_CEILING, 'cả hai tầng về đủ trần'
        assert runtime.parent_running == {} and runtime.parent_slots == {}
        assert all(store.child(child['sessionId'])['status'] == 'failed' for child in children)
        for child in children:
            assert child['sessionId'] not in runtime.child_slot_holders, 'một con, một lần nhả'

        # Và trần còn dùng được thật: mua lại đủ ba slot của cha sau khi mọi con đã đóng.
        for _ in range(FANOUT_PER_PARENT_DEFAULT):
            await runtime.acquire_child_slot(sid)
            runtime.release_child_slot(sid)
        assert runtime.parent_running == {} and runtime.parent_slots == {}

    asyncio.run(run())
    store.close()


def test_huy_luc_xep_hang_khong_ro_slot_cua_cha(tmp_path):
    """Lượt bị huỷ khi đang chờ slot toàn cục ⇒ slot của CHA được trả lại (BUG-54)."""
    store, runtime, sessions = build(tmp_path, parents=2)
    sid = sessions[0]['id']

    async def run():
        runtime.fanout_queue_wait = 30
        for _ in range(FANOUT_GLOBAL_CEILING):
            await runtime.global_child_slots.acquire()   # hộp đã kín chỗ (8 con của phiên khác)
        waiting = asyncio.ensure_future(runtime.acquire_child_slot(sid))
        await asyncio.sleep(0.05)                        # nó mua được slot của cha, rồi nằm chờ
        assert runtime.parent_waiters.get(sid) == 1
        slot = runtime.parent_slots[sid]
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert slot._value == FANOUT_PER_PARENT_DEFAULT, 'cả ba permit của cha đã về'
        assert runtime.parent_running == {} and runtime.parent_waiters == {}
        assert runtime.parent_slots == {}, 'entry của cha được dọn khi không còn ai chờ'
        for _ in range(FANOUT_GLOBAL_CEILING):
            runtime.global_child_slots.release()

    asyncio.run(run())
    assert runtime.global_child_slots._value == FANOUT_GLOBAL_CEILING
    store.close()


# --------------------------------------------------------------------------- #
# 2. Giao hàng hỏng không làm mất event kết thúc
# --------------------------------------------------------------------------- #

def test_giao_hang_hong_van_phat_event_ket_thuc(tmp_path):
    """`deliver_child_result` ném ⇒ event `child` kết thúc VẪN tới luồng cha (BUG-55)."""
    store, runtime, sessions = build(tmp_path, model=FixtureModel([
        answer(calls=[call('delegate_task', {'role': 'review', 'goal': GOAL, 'wait': True,
                                            'deliverTo': ['main']}, 'c1')]),
        answer('xong'),
    ], child_responses=[answer('con xong')]))
    sid = sessions[0]['id']
    writes = []
    import agentbox.agent_core.runtime as runtime_module
    original_log = runtime_module.system_log.write
    runtime_module.system_log.write = lambda event, **data: writes.append((event, data))

    def broken(*_args, **_kwargs):
        raise RuntimeError('database is locked')

    runtime.deliver_child_result = broken
    try:
        async def run():
            runtime.start(sid, 'làm việc')
            await runtime.tasks[sid]
        asyncio.run(run())
    finally:
        runtime_module.system_log.write = original_log

    events = [event['data'] for event in store.events(sid) if event['type'] == 'child']
    closed = [row for row in events if row['status'] != 'started']
    assert len(closed) == 1 and closed[0]['status'] == 'completed'
    assert closed[0]['deliveries'] == [], 'việc giao đã hỏng ⇒ không có biên nhận nào'
    assert store.get(sid)['status'] == 'completed', 'lỗi giao hàng KHÔNG phải lỗi của lượt cha'
    results = [json.loads(message['content']) for message in store.get(sid)['messages']
               if message['role'] == 'tool']
    assert results and results[0]['status'] == 'completed' and 'error' not in results[0], results
    assert [event for event, _ in writes if event == 'child.delivery_failed'], \
        'hỏng thì phải có một hàng nhật ký, không im lặng'
    store.close()


def test_giao_cho_main_danh_thuc_nguoi_cho_trong_cung_nhip(tmp_path):
    """`deliverTo: ['main']` đánh thức người đang chờ ngay, không đợi nhịp quét (BUG-58)."""
    store, runtime, sessions = build(tmp_path)
    sid = sessions[0]['id']
    child = store.create({'skills': []}, role='review', parent_id=sid)['id']
    store.child_start(child, sid, 1, 1, 'review', goal='soát')

    async def run():
        runtime.active_turn[sid] = 1
        event = asyncio.Event()
        runtime.peer_waiters[sid] = {event}
        receipts = runtime.deliver_child_result(child, sid, 'review', 1, 1, ['main'], chars=12)
        assert event.is_set(), 'biên nhận đã ghi ⇒ người chờ tỉnh trong CÙNG một nhịp vòng lặp'
        assert [row['state'] for row in receipts] == ['injected']
        assert receipts[0]['recipient'] == sid
        # Giao lặp cho cùng (con, người nhận, lượt) vẫn vô hại: `UNIQUE(child_id, recipient,
        # recipient_turn)` giữ đúng MỘT hàng, và trạng thái ở lại `injected` (đánh thức lần nữa là
        # vô hại — người chờ đọc cùng một hàng).
        event.clear()
        again = runtime.deliver_child_result(child, sid, 'review', 1, 1, ['main'], chars=12)
        assert len(again) == 1 and again[0]['state'] == 'injected'
        assert len(store.deliveries_of(child)) == 1, 'một (con, người nhận, lượt) ⇒ một hàng'
    asyncio.run(run())
