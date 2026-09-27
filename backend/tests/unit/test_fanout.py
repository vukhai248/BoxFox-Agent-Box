"""Fan-out theo CHA và trần toàn cục (vòng 22, T5).

Trần cũ là MỘT `Semaphore(3)` dùng chung cả tiến trình: ba con của phiên thứ nhất đã chặn mọi
phiên khác, và một cha không bao giờ có bốn con cùng lúc. Bộ kiểm này khoá bốn tính chất:

- hai cha × ba con chạy được CÙNG LÚC (trần theo cha, không tranh nhau);
- trần toàn cục vẫn có, và chạm nó thì model nhận `FANOUT_BUSY` — lượt không treo, không chết;
- lần mua slot thất bại KHÔNG rò slot (10 lần sinh liên tiếp ⇒ cả hai tầng về đủ trần);
- `parent_slots` không phình: entry bị bỏ khi bộ đếm về 0.
"""
import asyncio
import json

import pytest

from agentbox.agent_core.limits import (CHILDREN_PER_TURN_CODE, CHILDREN_PER_TURN_MAX, FANOUT_GLOBAL_CEILING,
                                        FANOUT_PER_PARENT_DEFAULT, FANOUT_PER_PARENT_MAX, PEER_FANOUT_ENV)
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

ARGS = {'role': 'research', 'goal': 'khảo sát'}


@pytest.fixture(autouse=True)
def _legacy_research_mode(monkeypatch):
    """Bộ kiểm này khoá CƠ CHẾ fan-out, không khoá chế độ Research.

    Khi công tắc `BOXFOX_RESEARCH_MODE` bật (mặc định từ F4 của phiếu soát), cửa 2 đổi hành vi của
    nhánh research KHÔNG brief: nhánh đầu bị kẹp mức 1 và từ nhánh thứ hai thì bị từ chối. Các ca ở
    đây cố tình sinh nhiều nhánh research không brief nên phải chạy ở đường CŨ (công tắc tắt); hành vi
    mới được khoá riêng trong `test_research_mode_shell.py` (M-07)."""
    monkeypatch.setenv('BOXFOX_RESEARCH_MODE', 'off')


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


class Concurrency:
    """Đếm số con đang chạy: toàn cục và theo từng cha, giữ mức cao nhất đã thấy."""

    def __init__(self):
        self.running = 0
        self.peak = 0
        self.per_parent = {}
        self.peak_per_parent = {}

    def enter(self, parent_sid):
        self.running += 1
        self.peak = max(self.peak, self.running)
        self.per_parent[parent_sid] = self.per_parent.get(parent_sid, 0) + 1
        self.peak_per_parent[parent_sid] = max(self.peak_per_parent.get(parent_sid, 0),
                                               self.per_parent[parent_sid])

    def leave(self, parent_sid):
        self.running -= 1
        self.per_parent[parent_sid] -= 1


def build(tmp_path, parents=1, values=None):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), None)
    base = {'skills': [], 'subagents': [{'id': 'research', 'enabled': True}], **(values or {})}
    sessions = [runtime.create(dict(base)) for _ in range(parents)]
    return store, runtime, sessions


def fake_start(runtime, counter, seconds=0.2):
    """`start` giả: một Task THẬT (để `done_callback` có chỗ bám) ngủ `seconds` giây rồi trả lời."""

    def start(sid, prompt):
        parent_sid = runtime.store.get(sid)['parent_id']

        async def run():
            counter.enter(parent_sid)
            try:
                await asyncio.sleep(seconds)
                return 'kết quả giả'
            finally:
                counter.leave(parent_sid)

        return asyncio.ensure_future(run())

    return start


def test_hai_cha_ba_con_chay_cung_luc_va_tran_toan_cuc_van_con(tmp_path):
    store, runtime, sessions = build(tmp_path, parents=2)
    counter = Concurrency()
    runtime.start = fake_start(runtime, counter, seconds=0.3)

    async def run():
        spawns = [runtime.delegate(sessions[0], ARGS) for _ in range(3)] \
            + [runtime.delegate(sessions[1], ARGS) for _ in range(3)]
        return await asyncio.gather(*spawns)

    results = asyncio.run(run())

    assert counter.peak_per_parent[sessions[0]['id']] == FANOUT_PER_PARENT_DEFAULT, \
        'một cha phải chạy được đủ ba con cùng lúc'
    assert counter.peak_per_parent[sessions[1]['id']] == FANOUT_PER_PARENT_DEFAULT, \
        'và cha thứ hai KHÔNG phải chờ ba slot của cha thứ nhất'
    assert counter.peak == 6 <= FANOUT_GLOBAL_CEILING
    ids = [row['sessionId'] for row in results]
    assert len(ids) == 6 and len(set(ids)) == 6, 'mỗi lời gọi sinh MỘT phiên con riêng'
    assert runtime.parent_running == {}, 'mọi con đã đóng ⇒ không còn bộ đếm nào'
    assert runtime.parent_slots == {}, 'entry của semaphore bị bỏ khi bộ đếm về 0'
    store.close()


def test_cha_thu_tu_khi_kin_tran_toan_cuc_nhan_fanout_busy(tmp_path):
    """6 con của cha A + 2 con của cha B giữ kín 8 slot toàn cục ⇒ cha C phải nhận LỖI TOOL.

    Đây là khác biệt giữa hai tầng trần: trần của cha C còn trống (nó chưa có con nào),
    nhưng trần TOÀN CỤC đã kín nên lần sinh phải bị từ chối thay vì treo lượt.
    """
    store, runtime, sessions = build(tmp_path, parents=3, values={'fanoutPerParent': 6})
    runtime.start = fake_start(runtime, Concurrency(), seconds=0.6)
    runtime.fanout_queue_wait = 0.05
    a, b, c = (session['id'] for session in sessions)

    async def run():
        holding = [runtime.delegate(sessions[0], {'role': 'research', 'goal': f'việc {n}'})
                   for n in range(6)] + [runtime.delegate(sessions[1], ARGS) for _ in range(2)]
        spawned = asyncio.gather(*holding)
        await asyncio.sleep(0.1)
        assert runtime.parent_running[a] == 6 and runtime.parent_running[b] == 2
        late = await asyncio.gather(runtime.delegate(sessions[2], ARGS), return_exceptions=True)
        return await spawned, late

    held, late = asyncio.run(run())

    assert len(held) == FANOUT_GLOBAL_CEILING and all(r['sessionId'] for r in held)
    assert isinstance(late[0], ValueError) and str(late[0]).startswith('FANOUT_BUSY:'), \
        'kín trần toàn cục ⇒ ValueError mang mã FANOUT_BUSY (model đọc được, lượt không chết)'
    assert str(FANOUT_GLOBAL_CEILING) in str(late[0])
    assert runtime.parent_running == {} and runtime.parent_slots == {}
    assert runtime.global_child_slots._value == FANOUT_GLOBAL_CEILING, 'trần toàn cục về đủ'
    assert c not in runtime.parent_slots, 'cha bị từ chối không để lại entry nào'
    store.close()


def test_lan_mua_that_bai_khong_ro_slot(tmp_path):
    """10 lần sinh liên tiếp (có cả lần thất bại) ⇒ cả hai tầng semaphore về đủ trần."""
    store, runtime, sessions = build(tmp_path, parents=1)
    sid = sessions[0]['id']
    runtime.fanout_queue_wait = 0.02

    async def run():
        for _ in range(10):
            for _ in range(FANOUT_PER_PARENT_DEFAULT):
                await runtime.acquire_child_slot(sid)
            with pytest.raises(ValueError) as excinfo:
                await runtime.acquire_child_slot(sid)
            assert str(excinfo.value).startswith('FANOUT_BUSY:')
            for _ in range(FANOUT_PER_PARENT_DEFAULT):
                runtime.release_child_slot(sid)
            # Ngay sau khi nhả, mua lại được đủ trần: lần thất bại trên không rò slot nào.
            assert runtime.parent_running == {} and runtime.parent_waiters == {}
        assert runtime.parent_slots == {}

    asyncio.run(run())
    assert runtime.global_child_slots._value == FANOUT_GLOBAL_CEILING
    store.close()


def test_tran_sinh_con_trong_mot_luot(tmp_path):
    store, runtime, sessions = build(tmp_path, parents=1)
    runtime.start = fake_start(runtime, Concurrency(), seconds=0.01)
    sid = sessions[0]['id']

    async def run():
        runtime.active_turn[sid] = 2
        for _ in range(CHILDREN_PER_TURN_MAX):
            await runtime.delegate(sessions[0], ARGS)
        with pytest.raises(ValueError) as excinfo:
            await runtime.delegate(sessions[0], ARGS)
        return str(excinfo.value)

    message = asyncio.run(run())

    assert message.startswith(CHILDREN_PER_TURN_CODE)
    assert str(CHILDREN_PER_TURN_MAX) in message
    assert len(store.children_of(sid, turn=2)) == CHILDREN_PER_TURN_MAX, \
        'con bị từ chối không sinh ra hàng sổ nào thêm'
    store.close()


def test_hoi_dung_tran_hien_hanh(monkeypatch):
    """Trần fan-out theo cha: mặc định 3, `config` của phiên kẹp vào `[1, 6]`, công tắc máy thắng."""
    assert HarnessRuntime.fanout_limit({}) == FANOUT_PER_PARENT_DEFAULT
    assert HarnessRuntime.fanout_limit({'fanoutPerParent': 5}) == 5
    assert HarnessRuntime.fanout_limit({'fanoutPerParent': 99}) == FANOUT_PER_PARENT_MAX
    assert HarnessRuntime.fanout_limit({'fanoutPerParent': 0}) == 1
    assert HarnessRuntime.fanout_limit({'fanoutPerParent': 'ba'}) == FANOUT_PER_PARENT_DEFAULT
    monkeypatch.setenv(PEER_FANOUT_ENV, '1')
    assert HarnessRuntime.fanout_limit({'fanoutPerParent': 5}) == 1, 'công tắc của MÁY thắng đường phiên'
