"""T10 đợt 2 — Watchdog sổ con: bốn luật, và tính idempotent của từng luật.

Đồng hồ được TIÊM vào (`now=`), nên không ca nào phải chờ 900 giây thật: luật là "quá
`CHILD_WALL_MAX_SECONDS`", và cái được kiểm là ngưỡng đó, không phải độ kiên nhẫn của pytest.
"""

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agentbox.agent_core import peer_watchdog as watchdog_module  # noqa: E402
from agentbox.agent_core.limits import (CHILD_WALL_MAX_SECONDS, PEER_WAIT_FORCE_GRACE_SECONDS,
                                        PEER_WAIT_SAFETY_SECONDS)  # noqa: E402
from agentbox.agent_core.peer_watchdog import PeerWatchdog  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402


class Clock:
    """Đồng hồ đứng yên rồi nhảy theo lệnh — `now()` phải là hàm, không phải giá trị."""

    def __init__(self, value=None):
        self.value = time.time() if value is None else value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds
        return self.value


def make(tmp_path, *, started_age=0.0, parent_status='running', waiting_age=None, boot=False):
    """Một cha + một con đang `started`; mọi mốc thời gian do `started_age`/`waiting_age` quyết định.

    `boot=True` giữ nguyên nhịp quét ĐẦU (luật 4 đóng mọi hàng còn `started`). Mặc định `boot=False`
    để ca kiểm ba luật còn lại, vì nhịp đầu sẽ đóng hàng trước khi chúng kịp chạy.
    """
    store = SessionStore(tmp_path / 'sessions.db')
    clock = Clock()
    parent = store.create({'skills': []})['id']
    if parent_status is not None:
        store.save(parent, [], parent_status)
    child = store.create({'skills': []}, role='review', parent_id=parent)['id']
    store.child_start(child, parent, 1, 2, 'review', goal='soát thay đổi')
    if started_age:
        store.db.execute('UPDATE children SET started=? WHERE session_id=?',
                         (clock.value - started_age, child))
    if waiting_age is not None:
        store.child_wait(child, ['peer:x'], clock.value - waiting_age)
    store.db.commit()
    watchdog = PeerWatchdog(store, runtime=None, tick=0.01, now=clock)
    watchdog.first_scan = boot   # `boot=True` ⇒ nhịp quét này LÀ nhịp đầu (luật 4 còn hiệu lực)
    return store, parent, child, clock, watchdog


def child_events(store, parent):
    return [event['data'] for event in store.events(parent) if event['type'] == 'child']


def test_hang_qua_tran_tuong_thi_mot_nhip_quet_dong_no(tmp_path):
    store, parent, child, clock, watchdog = make(tmp_path, started_age=CHILD_WALL_MAX_SECONDS + 5)
    report = watchdog.sweep()

    assert report['timeout'] == [child]
    row = store.child(child)
    assert row['status'] == 'failed' and row['reason'] == 'WATCHDOG_TIMEOUT'
    assert row['waiting_for'] == [] and row['waiting_since'] is None
    events = child_events(store, parent)
    assert [event['reason'] for event in events] == ['WATCHDOG_TIMEOUT']
    assert events[0]['watchdog'] is True and events[0]['is_error'] is True
    assert store.get(child)['status'] == 'cancelled', 'hàng phiên phải thôi hiển thị "đang chạy"'
    store.close()


def test_nhip_thu_hai_khong_lam_gi_them(tmp_path):
    store, parent, child, clock, watchdog = make(tmp_path, started_age=CHILD_WALL_MAX_SECONDS + 5)
    assert watchdog.sweep()['timeout'] == [child]
    second = watchdog.sweep()

    assert second == {'timeout': [], 'orphan': [], 'restart': [], 'forced': []}
    assert len(child_events(store, parent)) == 1, 'một cái chết, một event'
    assert store.child(child)['reason'] == 'WATCHDOG_TIMEOUT'
    store.close()


def test_con_con_trong_tran_thi_khong_bi_cham(tmp_path):
    store, parent, child, clock, watchdog = make(tmp_path, started_age=CHILD_WALL_MAX_SECONDS - 30)
    assert watchdog.sweep() == {'timeout': [], 'orphan': [], 'restart': [], 'forced': []}
    assert store.child(child)['status'] == 'started'
    assert child_events(store, parent) == []
    store.close()


def test_cha_da_xong_thi_con_la_mo_coi(tmp_path):
    """Cha `idle`/`completed` không còn đọc kết quả của con — nhưng con còn trong trần thời gian."""
    store, parent, child, clock, watchdog = make(tmp_path, parent_status='idle')
    report = watchdog.sweep()

    assert report['orphan'] == [child]
    assert store.child(child)['reason'] == 'ORPHAN'
    assert [event['reason'] for event in child_events(store, parent)] == ['ORPHAN']
    store.close()


def test_cha_da_bi_xoa_thi_con_la_mo_coi(tmp_path):
    store, parent, child, clock, watchdog = make(tmp_path, parent_status=None)
    store.db.execute('DELETE FROM sessions WHERE id=?', (parent,))
    store.db.commit()

    assert watchdog.sweep()['orphan'] == [child]
    assert store.child(child)['reason'] == 'ORPHAN'
    store.close()


def test_cha_dang_cho_quyet_dinh_thi_con_khong_bi_coi_la_mo_coi(tmp_path):
    """`awaiting_decision` là lượt CÒN SỐNG (đang chờ người): con của nó phải được để yên."""
    store, parent, child, clock, watchdog = make(tmp_path, parent_status='awaiting_decision')
    assert watchdog.sweep()['orphan'] == []
    assert store.child(child)['status'] == 'started'
    store.close()


def test_hang_tu_lan_chay_truoc_thi_restart_ngay_nhip_dau(tmp_path):
    """Luật 4: nhịp quét đầu sau khởi động đóng MỌI hàng `started`, bất kể mới hay cũ."""
    store, parent, child, clock, watchdog = make(tmp_path, started_age=0.5, boot=True)
    report = watchdog.sweep()

    assert report['restart'] == [child], 'nhịp ĐẦU: còn `started` nghĩa là tiến trình trước đã chết'
    assert store.child(child)['reason'] == 'RESTART'
    assert [event['reason'] for event in child_events(store, parent)] == ['RESTART']
    # Và nhịp thứ hai không còn gì để làm — kể cả khi hàng đã quá trần.
    clock.advance(CHILD_WALL_MAX_SECONDS + 60)
    assert watchdog.sweep() == {'timeout': [], 'orphan': [], 'restart': [], 'forced': []}
    store.close()


def test_cho_qua_lau_thi_danh_thuc_cuong_buc_chu_khong_dong_so(tmp_path):
    """Luật 3: người chờ được đánh thức và CHẠY TIẾP — hàng sổ con không bị đóng, lượt không `failed`."""
    store, parent, child, clock, watchdog = make(
        tmp_path, waiting_age=PEER_WAIT_SAFETY_SECONDS + PEER_WAIT_FORCE_GRACE_SECONDS + 1)
    woken = []

    class FakeRuntime:
        def __init__(self):
            self.peer_force_wake = set()

        def notify_peer_delivery(self, recipient):
            woken.append(recipient)
            return 0

        def tasks(self):  # pragma: no cover - chỉ để cấu trúc rõ ràng
            return {}

    watchdog.runtime = FakeRuntime()
    report = watchdog.sweep()

    assert report['forced'] == [child]
    assert woken == [child]
    assert store.child(child)['status'] == 'started', 'đánh thức KHÔNG phải là đóng sổ'
    assert child_events(store, parent) == []
    assert watchdog.runtime.peer_force_wake == {child}
    store.close()


def test_cho_chua_qua_lau_thi_khong_danh_thuc(tmp_path):
    store, parent, child, clock, watchdog = make(tmp_path, waiting_age=PEER_WAIT_SAFETY_SECONDS)
    assert watchdog.sweep()['forced'] == []
    assert store.child(child)['waiting_since'] is not None
    store.close()


def test_watchdog_khong_co_runtime_thi_khong_hong(tmp_path):
    """Một tiến trình chỉ mở DB để soi vẫn quét được: luật 1/2 chạy, luật 3 không làm gì."""
    store, parent, child, clock, watchdog = make(tmp_path, started_age=CHILD_WALL_MAX_SECONDS + 1)
    assert watchdog.sweep()['timeout'] == [child]
    store.close()


def test_vong_quet_thuc_su_chay_va_dung_lai_duoc(tmp_path):
    """Vòng `run()` phải thật sự quét (không chỉ là code chết) và `stop()` phải dừng hẳn."""
    store, parent, child, clock, watchdog = make(tmp_path, started_age=CHILD_WALL_MAX_SECONDS + 1)

    async def scenario():
        watchdog.start()
        await asyncio.sleep(0.05)
        await watchdog.stop()
        return watchdog.sweeps, watchdog.task

    sweeps, task = asyncio.run(scenario())
    assert sweeps >= 1, 'nhịp đầu chạy ngay lúc `start()`, không chờ hết `tick`'
    assert task is None
    assert store.child(child)['status'] == 'failed'
    store.close()


def test_mot_ham_chi_dong_mot_lan(tmp_path):
    """`child_close_once` là chỗ chặn hai event cho một cái chết — kiểm thẳng hợp đồng của nó."""
    store, parent, child, clock, watchdog = make(tmp_path)
    first = store.child_close_once(child, 'failed', reason='WATCHDOG_TIMEOUT')
    second = store.child_close_once(child, 'failed', reason='ORPHAN')

    assert first is not None and first['reason'] == 'WATCHDOG_TIMEOUT'
    assert second is None, 'người đến sau không được ghi lý do thứ hai'
    assert store.child(child)['reason'] == 'WATCHDOG_TIMEOUT'
    store.close()


def test_dong_so_bang_watchdog_van_ghi_lai_so_con_da_tieu(tmp_path):
    """Đường watchdog cũng ghi chi phí: luồng của con là nguồn duy nhất còn lại sau khi nó bị cắt."""
    store, parent, child, clock, watchdog = make(tmp_path, started_age=CHILD_WALL_MAX_SECONDS + 5)
    store.emit(child, 'turn_end', {'turn': 1, 'step': 1, 'stepsUsed': 1, 'outputTokens': 7})
    store.emit(child, 'turn_end', {'turn': 1, 'step': 2, 'stepsUsed': 2, 'outputTokens': 5})

    report = watchdog.sweep()

    assert report['timeout'] == [child]
    row = store.child(child)
    assert row['steps_used'] == 2 and row['output_tokens'] == 12, 'max số bước luỹ kế, tổng token'
    finish = next(event for event in child_events(store, parent) if event['status'] != 'started')
    assert finish['stepsUsed'] == 2 and finish['outputTokens'] == 12
    store.close()


def test_bon_luat_dung_chung_mot_nhip(tmp_path):
    """Một nhịp quét xử lý cả bốn luật trong cùng danh sách — và không luật nào nuốt luật khác."""
    store = SessionStore(tmp_path / 'sessions.db')
    clock = Clock()
    parent = store.create({'skills': []})['id']
    store.save(parent, [], 'running')
    old_child = store.create({'skills': []}, role='testing', parent_id=parent)['id']
    store.child_start(old_child, parent, 1, 1, 'testing', goal='cũ')
    store.db.execute('UPDATE children SET started=? WHERE session_id=?',
                     (clock.value - CHILD_WALL_MAX_SECONDS - 10, old_child))
    waiting_child = store.create({'skills': []}, role='review', parent_id=parent)['id']
    store.child_start(waiting_child, parent, 1, 2, 'review', goal='đang chờ')
    store.child_wait(waiting_child, ['peer:x'],
                     clock.value - PEER_WAIT_SAFETY_SECONDS - PEER_WAIT_FORCE_GRACE_SECONDS - 1)
    live_child = store.create({'skills': []}, role='debug', parent_id=parent)['id']
    store.child_start(live_child, parent, 1, 3, 'debug', goal='trong trần')
    store.db.commit()

    class FakeRuntime:
        peer_force_wake = set()

        @staticmethod
        def notify_peer_delivery(recipient):
            return 0

    watchdog = PeerWatchdog(store, runtime=FakeRuntime(), now=clock)
    watchdog.first_scan = False
    report = watchdog.sweep()

    assert report == {'timeout': [old_child], 'orphan': [], 'restart': [], 'forced': [waiting_child]}
    assert store.child(live_child)['status'] == 'started'
    assert store.child(waiting_child)['status'] == 'started'
    assert store.child(old_child)['status'] == 'failed'
    store.close()


def test_tran_tuong_cua_watchdog_rong_hon_tran_cua_mot_con():
    """#6457: watchdog chỉ được huỷ con đã vượt xa mọi ngưỡng hợp lệ.

    Nếu `CHILD_WALL_MAX_SECONDS` nhỏ hơn `CHILD_DEADLINE_SECONDS` (bản #6457 đầu tiên để 1200 s so
    với trần con 3600 s), mọi con chạy dài HỢP LỆ đều bị đóng `WATCHDOG_TIMEOUT` — đúng thứ mà #6457
    vừa mở đường. Trần tường phải suy ra từ trần con, không được là một số cứng độc lập.
    """
    from agentbox.agent_core import limits
    assert limits.CHILD_WALL_MAX_SECONDS > limits.CHILD_DEADLINE_SECONDS
    assert limits.CHILD_WALL_MAX_SECONDS >= limits.CHILD_DEADLINE_SECONDS + 300
