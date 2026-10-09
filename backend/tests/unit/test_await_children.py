"""T9 — `await_children`: chờ **tới lúc bạn giao kết quả**, không chờ một khoảng thời gian.

Chủ nhà chốt (Q2): người chờ dừng ở một mốc, tỉnh dậy khi biên nhận giao hàng được ghi (đánh thức
bằng sự kiện — `notify_peer_delivery`), rồi chạy tiếp với kết quả đó. Ba con số 300 s chỉ là **lưới
an toàn** để một lượt không bao giờ treo và không bao giờ `failed` vì đã chờ.

Bộ kiểm này dựng cảnh ở tầng runtime (không cần một lượt thật) cho phần thời gian, cộng một ca
tích hợp đi qua đúng đường tool call để khẳng định lượt vẫn `completed` sau khi chờ hụt.
"""
import asyncio
import copy
import json
import time

from agentbox.agent_core.limits import (PEER_WAIT_MAX_SECONDS, PEER_WAIT_SAFETY_SECONDS,
                                        PEER_WAIT_TOTAL_MAX_SECONDS)
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

CHILD_ANSWER = 'Con đã soát xong: 3 tệp, 2 lỗi, kèm bằng chứng ở dòng 41.'
GOAL = 'việc của con'


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    """Hai dòng trả lời riêng cho cha và con — con nhận ra bằng goal trong tin nhắn người dùng ĐẦU TIÊN."""

    def __init__(self, parent_responses, child_responses=()):
        self.parent_responses = iter(parent_responses)
        self.child_responses = iter(child_responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        copy.deepcopy((messages, tools, route))
        first_user = next((str(message.get('content') or '') for message in messages
                           if message.get('role') == 'user'), '')
        if GOAL in first_user:
            return next(self.child_responses)
        return next(self.parent_responses)


class FixtureExecutor:
    """`slow` = những tool ngủ thật, để dựng cảnh "bạn còn đang chạy" mà không cần đồng hồ giả."""

    def __init__(self, slow=(), seconds=3.0):
        self.slow = set(slow)
        self.seconds = seconds

    async def execute(self, name, args, sid, **_identity):
        if name in self.slow:
            await asyncio.sleep(self.seconds)
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def build(tmp_path, parent_answers=(), child_answers=(), slow=()):
    store = SessionStore(tmp_path / 'sessions.db')
    child_answers = [item if isinstance(item, dict) else answer(item) for item in child_answers]
    runtime = HarnessRuntime(store, FixtureExecutor(slow), FixtureModel(parent_answers, child_answers))
    sid = runtime.create({'skills': []})['id']
    return store, runtime, sid


def add_peer(store, parent_id, role, status='completed', turn=1, text=CHILD_ANSWER):
    """Một phiên bạn đã có câu trả lời trong transcript (chưa giao thì chưa có biên nhận)."""
    peer = store.create({'skills': []}, role=role, parent_id=parent_id)['id']
    store.child_start(peer, parent_id, turn, 1, role, goal=f'việc của {role}')
    store.emit(peer, 'assistant', {'text': text, 'final': True})
    if status != 'started':
        store.child_finish(peer, status, answer_chars=len(text))
    return peer


def target_rows(runtime, ids):
    return [{'session_id': item, 'role': runtime.store.child(item)['role']} for item in ids]


def deliver(store, runtime, peer, recipient, turn=1, chars=len(CHILD_ANSWER)):
    row = store.queue_delivery(peer, recipient, turn, 'peer', chars=chars)
    runtime.notify_peer_delivery(recipient)
    return row


# --------------------------------------------------------------------------- #
# Chờ tới lúc bạn GIAO — không phải chờ 300 s
# --------------------------------------------------------------------------- #

def test_await_children_ban_giao_sau_hai_giay_thi_tra_sau_hai_giay(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review', status='started')

    async def run():
        async def hand_over():
            await asyncio.sleep(2.0)
            deliver(store, runtime, peer, sid)

        task = asyncio.ensure_future(hand_over())
        started = time.monotonic()
        row = await runtime.wait_for_peers(sid, target_rows(runtime, [peer]), 'all', PEER_WAIT_SAFETY_SECONDS)
        elapsed = time.monotonic() - started
        await task
        return row, elapsed

    (status, done, pending, waited, exhausted), elapsed = asyncio.run(run())
    assert status == 'done' and pending == [] and exhausted is False
    assert 1.8 <= elapsed <= 2.4, f'phải tỉnh lúc bạn giao (~2 s), không phải sau {elapsed:.1f}s'
    assert 1_800 <= int(waited * 1000) <= 2_400, 'waitedMs là số đo thật, không phải con số 300 000'
    assert [row['session_id'] for row in done] == [peer]
    store.close()


def test_await_children_all_tra_du_hai_summary_khi_ca_hai_da_giao(tmp_path):
    store, runtime, sid = build(tmp_path)
    first = add_peer(store, sid, 'review')
    second = add_peer(store, sid, 'testing', text='Đã chạy 12 ca, 12 xanh.')
    deliver(store, runtime, first, sid)
    deliver(store, runtime, second, sid, chars=len('Đã chạy 12 ca, 12 xanh.'))

    async def run():
        return await runtime.await_children({'id': sid}, {'targets': [], 'mode': 'all'})

    result = asyncio.run(run())
    assert result['status'] == 'done' and result['pending'] == []
    assert [item['sessionId'] for item in result['done']] == [first, second]
    assert [item['role'] for item in result['done']] == ['review', 'testing']
    assert result['done'][0]['summary'] == CHILD_ANSWER
    assert result['done'][1]['summary'] == 'Đã chạy 12 ca, 12 xanh.'
    assert [item['truncated'] for item in result['done']] == [False, False]
    assert result['done'][0]['chars'] == len(CHILD_ANSWER)
    assert result['done'][0]['status'] == 'completed'
    assert result['waitedMs'] < 500, 'ai đã giao rồi thì không chờ thêm nhịp nào'
    store.close()


def test_await_children_mode_any_tra_ngay_khi_mot_ban_giao(tmp_path):
    store, runtime, sid = build(tmp_path)
    quick = add_peer(store, sid, 'review')
    slow = add_peer(store, sid, 'testing', status='started', text='')
    deliver(store, runtime, quick, sid)

    async def run():
        return await runtime.await_children({'id': sid}, {'mode': 'any'})

    result = asyncio.run(run())
    assert result['status'] == 'done' and result['mode'] == 'any'
    assert [item['sessionId'] for item in result['done']] == [quick]
    assert [item['sessionId'] for item in result['pending']] == [slow], 'người còn lại nằm trong `pending`'
    store.close()


# --------------------------------------------------------------------------- #
# Lưới an toàn: chờ hụt KHÔNG bao giờ là `failed`
# --------------------------------------------------------------------------- #

def test_await_children_cham_luoi_an_toan_tra_timeout_chu_khong_treo(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review', status='started', text='')

    async def run():
        return await runtime.wait_for_peers(sid, target_rows(runtime, [peer]), 'all', 1)

    status, done, pending, waited, exhausted = asyncio.run(run())
    assert status == 'timeout' and done == [] and exhausted is False
    assert [row['session_id'] for row in pending] == [peer]
    assert 1.0 <= waited <= 1.6, 'đúng lưới an toàn, không phải 300 s'
    store.close()


def test_await_children_ban_da_dong_so_ma_chua_giao_thi_thoi_cho(tmp_path):
    """Bạn CÙNG CHA đã đóng sổ mà chưa giao là chờ một việc không tới — kết thúc ngay, không đợi 300 s."""
    store, runtime, sid = build(tmp_path)
    waiter = add_peer(store, sid, 'testing', status='started')
    dead = add_peer(store, sid, 'review', status='failed', text='')

    async def run():
        started = time.monotonic()
        row = await runtime.wait_for_peers(waiter, target_rows(runtime, [dead]), 'all', 300)
        return row, time.monotonic() - started

    (status, done, pending, waited, exhausted), elapsed = asyncio.run(run())
    assert status == 'timeout' and elapsed < 1.0 and [r['session_id'] for r in pending] == [dead]
    assert done == [], 'bạn đóng sổ mà chưa giao thì không có gì để đọc'
    store.close()


def test_await_children_cha_khong_can_bien_nhan_tu_con_ruot_da_dong_so(tmp_path):
    """Luật của **cha**: con ruột đóng sổ là xong.

    Con ruột không ghi biên nhận nào trừ khi nó khai `deliverTo` (T11) — kết quả của nó tới cha
    bằng event `child`. Nếu thiếu luật này thì cách gọi tự nhiên nhất của cha (`await_children()`
    trần) trả `timeout` cho chính những đứa con đã chạy xong.
    """
    store, runtime, sid = build(tmp_path)
    child = add_peer(store, sid, 'review', status='completed')

    async def run():
        started = time.monotonic()
        row = await runtime.wait_for_peers(sid, target_rows(runtime, [child]), 'all', 300)
        return row, time.monotonic() - started

    (status, done, pending, waited, exhausted), elapsed = asyncio.run(run())
    assert status == 'done' and pending == [] and elapsed < 1.0
    assert [row['session_id'] for row in done] == [child]

    # `done` ở tầng `wait_for_peers` là hàng mục tiêu; bản cắt của câu trả lời do `await_children`
    # dựng — và với con ruột thì nó đọc thẳng câu trả lời cuối của con trong transcript.
    result = asyncio.run(runtime.await_children({'id': sid}, {'targets': [f'peer:{child}'],
                                                               'mode': 'all'}))
    assert result['status'] == 'done' and result['pending'] == []
    assert result['done'][0]['summary'] == CHILD_ANSWER, 'cha vẫn đọc được câu trả lời của con'
    assert result['done'][0]['status'] == 'completed'
    store.close()


def test_await_children_vuot_han_muc_hoan_thi_noi_that(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review', status='started', text='')
    runtime.wait_extension[sid] = PEER_WAIT_TOTAL_MAX_SECONDS

    async def run():
        return await runtime.wait_for_peers(sid, target_rows(runtime, [peer]), 'all', 300)

    status, done, pending, waited, exhausted = asyncio.run(run())
    assert status == 'timeout' and exhausted is True, 'đã chờ đủ hạn mức của lượt thì phải nói ra'
    assert waited == 0 and [row['session_id'] for row in pending] == [peer]
    store.close()


def test_await_children_trong_mot_luot_that_luot_khong_bao_gio_failed(tmp_path):
    """Chờ hụt vì **hạn người gọi tự đặt** trong lúc bạn còn chạy: lượt vẫn xong, không lỗi nào."""
    store, runtime, sid = build(tmp_path, [
        answer(calls=[call('delegate_task', {'role': 'review', 'goal': GOAL, 'wait': False})]),
        answer(calls=[call('await_children', {'targets': ['role:review'], 'timeoutSeconds': 1})]),
        answer('chạy tiếp với dữ liệu đang có'),
    ], child_answers=[answer(calls=[call('file_read', {'path': 'soát từng tệp'}, 'a1')]),
                      answer('con xong rồi')], slow={'file_read'})
    runtime.peer_wait_tick = 0.2

    async def run():
        runtime.start(sid, 'giao việc rồi chờ bạn')
        await runtime.tasks[sid]

    asyncio.run(run())

    assert store.get(sid)['status'] == 'completed', 'chờ hụt vẫn là lượt xong, không phải lượt hỏng'
    results = [json.loads(message['content']) for message in store.get(sid)['messages']
               if message['role'] == 'tool']
    wait = results[-1]
    assert wait['status'] == 'timeout' and wait['pending'], 'chỗ gọi thấy rõ ai chưa giao'
    assert wait['pending'][0]['role'] == 'review'
    assert wait['done'] == [], 'con xong nhưng CHƯA giao thì không được coi là đã giao'
    ends = [event['data'] for event in store.events(sid) if event['type'] == 'peer_wait_end']
    assert ends[-1]['status'] == 'timeout'
    assert [event['data'] for event in store.events(sid) if event['type'] == 'error'] == [], \
        'đã chờ là không được sinh ra lỗi nào'
    store.close()


# --------------------------------------------------------------------------- #
# Địa chỉ, phạm vi, event và nhật ký
# --------------------------------------------------------------------------- #

def test_await_children_dia_chi_vai_chua_ton_tai_thi_mo_cua_so_do(tmp_path):
    store, runtime, sid = build(tmp_path)
    runtime.peer_target_grace = 0.05

    async def run():
        return await runtime.await_children({'id': sid}, {'targets': ['role:review'], 'mode': 'all'})

    result = asyncio.run(run())
    assert result['status'] == 'pending_target'
    assert result['pending'] == ['role:review'], 'nói thẳng địa chỉ nào chưa có ai'
    assert result['done'] == [] and result['waitedMs'] == 0
    assert [event for event in store.events(sid) if event['type'] == 'peer_wait'] == [], \
        'chưa có ai để chờ thì không mở một cặp event chờ'
    store.close()


def test_await_children_nhan_session_id_tran_cua_ban_minh(tmp_path):
    """BUG đo sống 09/10/2026 (lượt 27): id trần bị coi là tên vai nên cha chờ mãi một địa chỉ
    không phân giải được — hơn 100 bước tiêu vô ích. Id trần của bạn mình phải chờ được."""
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review', status='started')

    async def run():
        async def hand_over():
            await asyncio.sleep(0.2)
            deliver(store, runtime, peer, sid)

        task = asyncio.ensure_future(hand_over())
        result = await runtime.await_children({'id': sid}, {'targets': [peer], 'mode': 'all'})
        await task
        return result

    result = asyncio.run(run())
    assert result['status'] == 'done', 'id trần của bạn mình phải phân giải được'
    assert [item['sessionId'] for item in result['done']] == [peer]
    store.close()


def test_await_children_dia_chi_khong_phan_giai_duoc_thi_noi_thang(tmp_path):
    """`pending_target` phải nói được "địa chỉ này KHÔNG phân giải được", kèm ba dạng hợp lệ."""
    store, runtime, sid = build(tmp_path)
    runtime.peer_target_grace = 0.05

    async def run():
        return await runtime.await_children({'id': sid},
                                            {'targets': ['khong-phai-vai-nao'], 'mode': 'all'})

    result = asyncio.run(run())
    assert result['status'] == 'pending_target'
    assert result['pending'] == ['khong-phai-vai-nao']
    assert result['unresolved'] == ['khong-phai-vai-nao'], 'trường nói rõ địa chỉ không phân giải được'
    notices = [event['data'] for event in store.events(sid)
               if event['type'] == 'notice' and event['data'].get('code') == 'PEER_TARGET_UNRESOLVED']
    assert len(notices) == 1, 'không phân giải được địa chỉ thì phải nói thẳng, không để cha đoán'
    assert 'peer:<sessionId>' in notices[0]['message']
    assert notices[0]['missing'] == ['khong-phai-vai-nao']
    store.close()


def test_await_children_cua_so_do_bat_duoc_ban_sinh_ngay_sau_do(tmp_path):
    """`role:` chưa tồn tại KHÔNG phải lỗi: anh em có thể được sinh ngay sau lời gọi này."""
    store, runtime, sid = build(tmp_path)
    runtime.peer_target_grace = 2.0
    runtime.peer_wait_tick = 0.05

    async def run():
        async def spawn_later():
            await asyncio.sleep(0.3)
            peer = add_peer(store, sid, 'review')
            deliver(store, runtime, peer, sid)
            return peer

        task = asyncio.ensure_future(spawn_later())
        result = await runtime.await_children({'id': sid}, {'targets': ['role:review']})
        return result, await task

    result, peer = asyncio.run(run())
    assert result['status'] == 'done', 'cửa sổ dò bắt được người vừa được sinh'
    assert [item['sessionId'] for item in result['done']] == [peer]
    store.close()


def test_await_children_khong_cho_duoc_phien_ngoai_pham_vi(tmp_path):
    store, runtime, sid = build(tmp_path)
    other_parent = store.create({'skills': []})['id']
    stranger = add_peer(store, other_parent, 'review')
    runtime.peer_target_grace = 0.05

    async def run():
        return await runtime.await_children({'id': sid}, {'targets': [f'peer:{stranger}']})

    result = asyncio.run(run())
    assert result['status'] == 'pending_target' and result['pending'] == [f'peer:{stranger}']
    assert store.child(stranger)['status'] == 'completed', 'không đụng vào phiên ngoài phạm vi'
    store.close()


def test_await_children_phat_dung_mot_cap_event_va_mot_hang_nhat_ky_S(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review')
    deliver(store, runtime, peer, sid)

    async def run():
        return await runtime.await_children({'id': sid}, {'targets': [f'peer:{peer}']})

    result = asyncio.run(run())
    events = store.events(sid)
    waits = [event['data'] for event in events if event['type'] == 'peer_wait']
    ends = [event['data'] for event in events if event['type'] == 'peer_wait_end']
    assert len(waits) == 1 and len(ends) == 1, 'một lần chờ, một cặp event'
    assert waits[0]['waitsUntilDelivery'] is True and waits[0]['mode'] == 'all'
    assert waits[0]['targets'] == [{'sessionId': peer, 'role': 'review'}]
    assert waits[0]['safetySeconds'] == PEER_WAIT_SAFETY_SECONDS
    assert waits[0]['deadline'] > time.time() - 5
    assert waits[0]['turn'] is None, 'ngoài lượt thật thì không có số lượt để bịa'
    assert ends[0]['status'] == 'done' and ends[0]['done'][0]['sessionId'] == peer

    rows = store.journal_tail(sid, kinds=['step'])
    assert len(rows) == 1, 'đúng MỘT hàng nhật ký cho lần chờ'
    assert rows[0]['payload']['record']['id'].startswith('S:'), 'hàng bước có mã S:<sid8>-<seq>'
    assert 'waiting for 1 peer session' in rows[0]['text']
    assert result['truncated'] is False and result['extensionExhausted'] is False
    store.close()


def test_await_children_ghi_roi_xoa_waiting_for_trong_so_con(tmp_path):
    """Phiên chờ là một CON ⇒ hàng sổ con của nó nói "đang chờ ai", rồi tự xoá khi xong."""
    store, runtime, _ = build(tmp_path)
    grandparent = store.create({'skills': []})['id']
    # Con THẬT: hàng `sessions` phải mang `parent_id`, không chỉ có hàng sổ con — phạm vi bạn bè đọc
    # từ đó, nên một hàng sổ con đơn lẻ (như vài test khác dựng) sẽ không thấy ai.
    parent = store.create({'skills': []}, role='build', parent_id=grandparent)['id']
    store.child_start(parent, grandparent, 1, 1, 'build', goal='việc của cha')
    peer = add_peer(store, grandparent, 'review', status='started')

    async def run():
        started = time.monotonic()
        task = asyncio.ensure_future(runtime.await_children({'id': parent}, {'targets': [f'peer:{peer}']}))
        await asyncio.sleep(0.2)
        during = store.child(parent)
        deliver(store, runtime, peer, parent)
        return during, await task, time.monotonic() - started

    during, result, elapsed = asyncio.run(run())
    assert during['waiting_for'] == [f'peer:{peer}'] and during['waiting_since'] is not None
    assert result['status'] == 'done' and elapsed < 2.0, 'giao sớm thì trả sớm'
    assert store.child(parent)['waiting_for'] == [], 'hết chờ thì hàng sổ con sạch'
    store.close()


def test_await_children_kep_timeout_va_ghi_notice(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review')
    deliver(store, runtime, peer, sid)

    async def run():
        return await runtime.await_children({'id': sid}, {'targets': [f'peer:{peer}'],
                                                         'timeoutSeconds': PEER_WAIT_MAX_SECONDS + 10_000})

    result = asyncio.run(run())
    assert result['status'] == 'done' and result['safetySeconds'] == PEER_WAIT_MAX_SECONDS
    notices = [event['data'] for event in store.events(sid)
               if event['type'] == 'notice' and event['data'].get('code') == 'PEER_WAIT_CLAMPED']
    assert len(notices) == 1 and notices[0]['applied'] == PEER_WAIT_MAX_SECONDS
    store.close()


def test_watchdog_danh_thuc_cuong_buc_tra_timeout_va_ghi_dau_forced(tmp_path):
    """T10 nối vào T9: watchdog cắt cơn chờ thì người chờ trả `timeout` NGAY và nói `forced: True`.

    Không có ca này thì cờ `peer_force_wake` là code chết: `wait_for_peers` vẫn ngủ đủ `tick` và
    `peer_wait_end` không phân biệt được "tự hết hạn" với "bị watchdog cắt".
    """
    store, runtime, sid = build(tmp_path)
    peer = add_peer(store, sid, 'review', status='started')
    session = store.get(sid)

    async def run():
        runtime.peer_force_wake.add(sid)          # watchdog vừa quyết định cắt
        started = time.monotonic()
        result = await runtime.await_children(session, {'targets': ['role:review'],
                                                       'mode': 'all', 'timeoutSeconds': 300})
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(run())
    assert result['status'] == 'timeout' and result['forced'] is True
    assert result['pending'][0]['role'] == 'review'
    assert elapsed < 2.0, 'bị cắt thì trả ngay, không ngủ nốt nhịp kiểm tra'
    assert sid not in runtime.peer_force_wake, 'cờ là chuyện MỘT LẦN: lần chờ sau không bị cắt oan'
    waits = [event['data'] for event in store.events(sid) if event['type'] == 'peer_wait_end']
    assert len(waits) == 1 and waits[0]['forced'] is True
    assert store.child(sid) is None, 'phiên gốc không phải con của ai'
    store.close()
