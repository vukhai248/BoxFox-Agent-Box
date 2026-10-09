"""T13 đợt 2 — đo chi phí theo lượt, trần ngân sách, và ba công tắc giết.

Ba nhóm được ghim ở đây:

1. **Số đo.** Mỗi lượt đóng lại kèm `{turn, steps, waitedMs, extensionMs, childCount, childSteps,
   childTokens}` trong event `finish` VÀ trong `system_log.write('turn.end'|'turn.failed')`;
   `session_metrics` có khối `peers`. Số của con đọc từ SỔ CON (một nguồn), không cộng lại từ event.
2. **Ngân sách chờ là của RIÊNG LƯỢT.** Bộ đếm thời gian chờ về 0 ở mỗi lượt — không có dòng đó thì
   lượt thứ hai của một phiên từng chờ đủ 300 s sẽ không còn ngân sách chờ nào.
3. **Công tắc.** `BOXFOX_PEER_MESH=off` trả hành vi về bản trước đợt 2 (uỷ thác chặn, hai công cụ
   peer không được quảng cáo), `BOXFOX_PEER_FANOUT` áp trần cho cả máy, `BOXFOX_PEER_WAIT_MAX` hạ
   lưới an toàn của một lần chờ. Cờ `BOXFOX_PARALLEL_READ_TOOLS` chỉ được KHAI BÁO (Q3/T14).
"""

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agentbox.agent_core import runtime as runtime_module  # noqa: E402
from agentbox.agent_core.limits import (FANOUT_PER_PARENT_DEFAULT, FANOUT_PER_PARENT_MAX,  # noqa: E402
                                        PEER_WAIT_CLAMPED_CODE, PEER_WAIT_MAX_SECONDS,
                                        PEER_WAIT_SAFETY_SECONDS, PEER_MESH_ENV, PEER_FANOUT_ENV,
                                        PEER_WAIT_MAX_ENV, PARALLEL_READ_ENV, peer_fanout_limit,
                                        peer_mesh_enabled, peer_wait_max, parallel_read_tools_enabled)
from agentbox.agent_core.runtime import HarnessRuntime  # noqa: E402
from agentbox.agent_core.tool_contracts import schemas_for  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402
from agentbox.sandbox.worker import SESSION_OP_NAMES

GOAL = 'việc của con'


def answer(text='done', calls=None, usage=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': usage or {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


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


class FixtureExecutor:
    async def execute(self, name, args, sid):
        if name in SESSION_OP_NAMES:
            # Op nhật ký của box (A1/A7) trả `{ok, …}` như worker thật: thiếu `ok` thì
            # `session_journal._safe` coi là CHƯA ghi được và ghim `JOURNAL_DEGRADED`.
            return {'ok': True}
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def build(tmp_path, parent_answers=(), child_answers=(), values=None):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel(parent_answers, child_answers))
    session = runtime.create({'skills': [], **(values or {})})
    return store, runtime, session


def run_turn(runtime, sid, prompt='làm việc'):
    async def run():
        runtime.start(sid, prompt)
        await runtime.tasks[sid]

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# 1. Số đo của một lượt
# --------------------------------------------------------------------------- #

def test_luot_sinh_hai_con_thi_finish_mang_du_sau_so(tmp_path):
    store, runtime, session = build(tmp_path, [
        answer(calls=[call('delegate_task', {'role': 'testing', 'goal': GOAL, 'wait': True}, 'c1'),
                      call('delegate_task', {'role': 'review', 'goal': GOAL, 'wait': True}, 'c2')]),
        answer('xong'),
    ], child_answers=[answer('con xong', usage={'prompt_tokens': 5, 'completion_tokens': 7}),
                      answer('con xong', usage={'prompt_tokens': 5, 'completion_tokens': 9})])
    run_turn(runtime, session['id'])

    finish = next(event['data'] for event in reversed(store.events(session['id']))
                  if event['type'] == 'finish')
    assert finish['turn'] == 1 and finish['steps'] == 2
    assert finish['childCount'] == 2, 'số con đọc từ SỔ CON, không phải đếm event'
    assert finish['childTokens'] == 16, 'tổng token của hai con'
    assert finish['childSteps'] >= 2
    assert finish['waitedMs'] == 0 and finish['extensionMs'] == 0, 'lượt này không chờ bạn nào'
    store.close()


def test_turn_end_trong_nhat_ky_mang_cung_bo_so(tmp_path):
    store, runtime, session = build(tmp_path, [answer('xong')])
    writes = []
    original = runtime_module.system_log.write
    runtime_module.system_log.write = lambda event, **data: writes.append((event, data))
    try:
        run_turn(runtime, session['id'])
    finally:
        runtime_module.system_log.write = original

    lines = [data for event, data in writes if event == 'turn.end']
    assert len(lines) == 1
    assert lines[0]['childCount'] == 0 and lines[0]['waitedMs'] == 0 and lines[0]['childSteps'] == 0
    assert lines[0]['turn'] == 1 and lines[0]['steps'] == 1
    store.close()


def test_luot_that_bai_cung_mang_bo_so(tmp_path):
    store, runtime, session = build(tmp_path, [answer('')])   # câu trả lời rỗng ⇒ lượt `failed`
    writes = []
    original = runtime_module.system_log.write
    runtime_module.system_log.write = lambda event, **data: writes.append((event, data))
    try:
        run_turn(runtime, session['id'])
    finally:
        runtime_module.system_log.write = original

    assert store.get(session['id'])['status'] == 'failed'
    lines = [data for event, data in writes if event == 'turn.failed']
    assert len(lines) == 1 and 'childCount' in lines[0] and 'waitedMs' in lines[0]
    store.close()


def test_session_metrics_co_khoi_peers_doc_tu_so_con(tmp_path):
    store, runtime, session = build(tmp_path, [
        answer(calls=[call('delegate_task', {'role': 'testing', 'goal': GOAL, 'wait': True}, 'c1')]),
        answer('xong'),
    ], child_answers=[answer('con xong')])
    run_turn(runtime, session['id'])

    metrics = runtime.session_metrics(session['id'])
    assert metrics['peerMesh'] is True
    assert metrics['peers']['spawned'] == 1 and metrics['peers']['completed'] == 1
    assert metrics['peers']['failed'] == 0 and metrics['peers']['running'] == 0
    assert metrics['peers']['childTokens'] == 2

    # Một con bị dừng giữa đường: `failed` đếm nó, `running` không còn.
    child = store.create({'skills': []}, role='review', parent_id=session['id'])['id']
    store.child_start(child, session['id'], 1, 1, 'review', goal='soát')
    metrics = runtime.session_metrics(session['id'])
    assert metrics['peers']['spawned'] == 2 and metrics['peers']['running'] == 1
    store.child_finish(child, 'failed', reason='WATCHDOG_TIMEOUT')
    metrics = runtime.session_metrics(session['id'])
    assert (metrics['peers']['running'], metrics['peers']['failed']) == (0, 1)
    store.close()


# --------------------------------------------------------------------------- #
# 2. Ngân sách chờ là của RIÊNG LƯỢT
# --------------------------------------------------------------------------- #

def test_ngan_sach_cho_ve_khong_o_moi_luot(tmp_path):
    """Lượt trước đã tiêu hết ngân sách chờ thì lượt sau vẫn phải chờ được."""
    store, runtime, session = build(tmp_path, [
        # `deliverTo: ['main']` là điều kiện để người chờ thấy BIÊN NHẬN: hợp đồng của T9 là chờ
        # tới lúc bạn GIAO, và một con đóng sổ mà không giao thì không bao giờ giao nữa.
        answer(calls=[call('delegate_task', {'role': 'review', 'goal': GOAL, 'wait': False,
                                             'deliverTo': ['main']}, 'c1')]),
        answer(calls=[call('await_children', {'targets': ['role:review'], 'mode': 'all',
                                              'timeoutSeconds': 5}, 'c2')]),
        answer('lượt một xong'),
        answer('lượt hai xong'),
    ], child_answers=[answer('bản soát')])
    sid = session['id']
    runtime.wait_extension[sid] = 1_000.0     # như thể lượt trước đã chờ cạn ngân sách

    run_turn(runtime, sid, 'lượt một')
    waits = [event['data'] for event in store.events(sid) if event['type'] == 'peer_wait_end']
    assert waits and waits[0]['extensionExhausted'] is False, \
        'ngân sách 300 s của LƯỢT này còn nguyên, dù bộ đếm của phiên đã bị đẩy lên 1000 s'
    assert waits[0]['status'] == 'done', 'review đã giao nên lượt chờ xong thật'
    assert 0 < runtime.wait_extension[sid] < 5.0, 'bộ đếm nay chỉ còn giây đã chờ của CHÍNH lượt này'

    run_turn(runtime, sid, 'lượt hai')
    assert store.get(sid)['status'] == 'completed'
    waits = [event['data'] for event in store.events(sid) if event['type'] == 'peer_wait_end']
    assert waits and all(row['status'] in ('done', 'timeout') for row in waits)
    assert not any(row.get('extensionExhausted') for row in waits), \
        'ngân sách chờ của lượt hai phải còn nguyên'
    store.close()


# --------------------------------------------------------------------------- #
# 3. Công tắc
# --------------------------------------------------------------------------- #

def test_cong_tac_mesh_off_bo_hai_cong_cu_peer(monkeypatch):
    monkeypatch.setenv(PEER_MESH_ENV, 'off')
    assert peer_mesh_enabled() is False
    assert schemas_for(['peer_read', 'await_children', 'file_read']) == \
        [schema for schema in schemas_for(['file_read'])]
    names = {schema['function']['name'] for schema in schemas_for(['peer_read', 'file_read'])}
    assert names == {'file_read'}
    store = None
    try:
        from agentbox.agent_core.roles import allowed_tools
        assert 'peer_read' not in allowed_tools('orchestrator')
        assert 'await_children' not in allowed_tools('review')
        assert 'file_read' in allowed_tools('review')
    finally:
        del store


def test_cong_tac_mesh_off_ep_u_y_thac_ve_duong_chan(tmp_path, monkeypatch):
    """`BOXFOX_PEER_MESH=off` ⇒ `wait=false` và `deliverTo` không còn nghĩa gì."""
    store, runtime, session = build(tmp_path, [
        answer(calls=[call('delegate_task', {'role': 'testing', 'goal': GOAL, 'wait': False,
                                             'deliverTo': ['main']}, 'c1')]),
        answer('xong'),
    ], child_answers=[answer('con xong')])
    monkeypatch.setenv(PEER_MESH_ENV, 'off')
    run_turn(runtime, session['id'])

    events = [event['data'] for event in store.events(session['id']) if event['type'] == 'child']
    start = next(row for row in events if row['status'] == 'started')
    assert start['wait'] is True and start['deliverTo'] == [], 'mesh tắt ⇒ hành vi trước đợt 2'
    assert len(store.deliveries_of(start['sessionId'])) == 0


def test_cong_tac_mesh_off_tu_choi_hai_cong_cu_peer(tmp_path, monkeypatch):
    store, runtime, session = build(tmp_path, [
        answer(calls=[call('peer_read', {'sessionId': 'khong-co-that'}, 'c1')]),
        answer('xong'),
    ])
    monkeypatch.setenv(PEER_MESH_ENV, 'off')
    run_turn(runtime, session['id'])

    results = [json.loads(message['content']) for message in store.get(session['id'])['messages']
               if message['role'] == 'tool']
    assert any('PEER_MESH_OFF' in str(item.get('error') or '') for item in results), results
    store.close()


def test_cong_tac_fanout_1_ep_mot_con_moi_cha(monkeypatch):
    assert peer_fanout_limit() is None
    assert HarnessRuntime.fanout_limit({}) == FANOUT_PER_PARENT_DEFAULT
    monkeypatch.setenv(PEER_FANOUT_ENV, '1')
    assert peer_fanout_limit() == 1, 'một CON SỐ được đọc là con số, không phải "bật"'
    assert HarnessRuntime.fanout_limit({}) == 1
    assert HarnessRuntime.fanout_limit({'fanoutPerParent': 5}) == 1, 'công tắc cả máy thắng phiên'
    monkeypatch.setenv(PEER_FANOUT_ENV, 'on')
    assert peer_fanout_limit() == FANOUT_PER_PARENT_MAX
    monkeypatch.setenv(PEER_FANOUT_ENV, '99')
    assert peer_fanout_limit() == FANOUT_PER_PARENT_MAX, 'kẹp vào trần lớn nhất'
    monkeypatch.setenv(PEER_FANOUT_ENV, 'ba')
    assert peer_fanout_limit() is None, 'giá trị không hiểu được thì giữ mặc định'


def test_cong_tac_peer_wait_max_ha_tran_va_ghi_notice(tmp_path, monkeypatch):
    monkeypatch.setenv(PEER_WAIT_MAX_ENV, '2')
    assert peer_wait_max() == 2
    assert peer_wait_max() < PEER_WAIT_SAFETY_SECONDS
    status, _, pending, waited, exhausted = asyncio.run(_wait_with_stuck_peer(tmp_path))
    assert status == 'timeout' and pending and exhausted is False
    assert 1.5 <= waited <= 3.5, f'chờ theo trần mới (2 s), không phải 300 s — đo được {waited:.1f}s'


async def _wait_with_stuck_peer(tmp_path):
    store, runtime, session = build(tmp_path)
    peer = store.create({'skills': []}, role='review', parent_id=session['id'])['id']
    store.child_start(peer, session['id'], 1, 1, 'review', goal=GOAL)
    runtime.peer_wait_tick = 0.1          # không ca nào phải ngồi đợi một nhịp thật
    row = await runtime.await_children(store.get(session['id']),
                                      {'targets': ['role:review'], 'mode': 'all', 'timeoutSeconds': 300})
    notices = [event['data'] for event in store.events(session['id']) if event['type'] == 'notice']
    assert [notice['code'] for notice in notices] == [PEER_WAIT_CLAMPED_CODE]
    assert notices[0]['applied'] == 2 and notices[0]['requested'] == 300
    store.close()
    return row['status'], row['done'], row['pending'], row['waitedMs'] / 1000.0, row['extensionExhausted']


def test_cong_tac_doc_song_trong_mot_tien_trinh(monkeypatch):
    """Đọc env Ở THỜI ĐIỂM GỌI: đổi biến có tác dụng ngay, không cần khởi động lại harness."""
    monkeypatch.delenv(PEER_MESH_ENV, raising=False)
    assert peer_mesh_enabled() is True
    monkeypatch.setenv(PEER_MESH_ENV, 'off')
    assert peer_mesh_enabled() is False
    monkeypatch.setenv(PARALLEL_READ_ENV, '1')
    assert parallel_read_tools_enabled() is True, 'cờ đọc được, nhưng vòng này KHÔNG đổi hành vi'


def test_phien_khai_co_mesh_thi_duoc_ghi_lai_kem_notice(tmp_path):
    store, runtime, session = build(tmp_path, values={'peerMesh': False, 'parallelReadTools': True,
                                                      'peerWaitMax': 10_000})
    config = session['config']
    assert config['peerMeshOff'] is True and config['parallelReadTools'] is True
    assert config['peerWaitMax'] == PEER_WAIT_MAX_SECONDS, 'kẹp về trần của máy'
    assert config['peerWaitClamped'] is True
    notices = [event['data'] for event in store.events(session['id']) if event['type'] == 'notice']
    codes = sorted(notice['code'] for notice in notices)
    assert codes == ['PEER_MESH_NOTICE', 'PEER_WAIT_CLAMPED'], codes
    mesh_notice = next(notice for notice in notices if notice['code'] == 'PEER_MESH_NOTICE')
    assert mesh_notice['parallelReadTools'] is True
    assert 'not part of this round' in mesh_notice['message'], 'nói thẳng cờ chưa có tác dụng'
    store.close()


def test_token_cua_con_cong_ca_chuoi_buoc_khong_chi_buoc_cuoi(tmp_path):
    """Con chạy nhiều bước: token của lượt cha là TỔNG các bước, không phải token bước cuối.

    Bước cuối của con có thể là chẩn đoán (`partial`) hoặc lỗi — hai đường đó KHÔNG mang
    `outputTokens`. Bản cũ đọc riêng `turn_end` cuối nên ghi `None` (hoặc chỉ token của một
    bước): lượt sống 2026-09-22 (`3647fe8e…`) có con `review` chạy 9 bước mà hàng sổ con ghi
    `output_tokens = None`, và `childTokens` của cha báo 0. Đo được thì phải ghi được.
    """
    store, runtime, session = build(tmp_path, [
        answer(calls=[call('delegate_task', {'role': 'testing', 'goal': GOAL, 'wait': True}, 'c1')]),
        answer('xong'),
    ], child_answers=[
        answer(calls=[call('file_read', {'path': 'a.md'}, 'c9')], usage={'prompt_tokens': 5, 'completion_tokens': 7}),
        answer(calls=[call('file_read', {'path': 'b.md'}, 'c10')], usage={'prompt_tokens': 5, 'completion_tokens': 5}),
        # Bước cuối không có khối `usage` — đúng hình dạng của một bước chẩn đoán/lỗi.
        {'choices': [{'message': {'content': 'con xong'}, 'finish_reason': 'stop'}]},
    ])
    run_turn(runtime, session['id'])

    summary = runtime.store.children_summary(session['id'])
    assert summary['completed'] == 1 and summary['failed'] == 0
    assert summary['childSteps'] == 3, 'ba bước của con'
    assert summary['childTokens'] == 12, 'token của CẢ ba bước'

    finish = next(event['data'] for event in reversed(store.events(session['id']))
                  if event['type'] == 'finish')
    assert finish['childSteps'] == 3 and finish['childTokens'] == 12
    store.close()


def test_phien_khai_tran_cho_thap_hon_thi_ton_trong(tmp_path):
    store, runtime, session = build(tmp_path, values={'peerWaitMax': 30})
    assert session['config']['peerWaitMax'] == 30
    assert 'peerWaitClamped' not in session['config']
    assert not [event for event in store.events(session['id']) if event['type'] == 'notice']
    store.close()


def test_finish_chi_tinh_con_cua_luot_dang_dong(tmp_path):
    """Lượt hai KHÔNG sinh con ⇒ `childCount` của lượt hai là 0, không phải luỹ kế của phiên.

    Bản trước bỏ qua tham số `turn` và đọc `children_summary` không lọc (`FROM children WHERE
    parent_id=?`), nên `finish` của lượt thứ ba báo mọi con mà cả phiên từng sinh — trong khi
    `waitedMs` ngay cạnh đó là số của riêng lượt (đo sống `bb142655…`: `finish` mang
    `childCount: 2` của lượt một). Lượt nào tiêu gì là câu hỏi của T13.
    """
    store, runtime, session = build(tmp_path, [
        answer(calls=[call('delegate_task', {'role': 'review', 'goal': GOAL, 'wait': True}, 'c1')]),
        answer('lượt một xong'),
        answer('lượt hai xong'),
    ], child_answers=[answer('con xong')])
    sid = session['id']

    run_turn(runtime, sid, 'lượt một')
    run_turn(runtime, sid, 'lượt hai')

    finishes = [event['data'] for event in store.events(sid) if event['type'] == 'finish']
    assert [row['turn'] for row in finishes] == [1, 2]
    assert finishes[0]['childCount'] == 1 and finishes[0]['childSteps'] >= 1
    assert finishes[0]['childTokens'] == 2
    assert finishes[1]['childCount'] == 0 and finishes[1]['childSteps'] == 0 \
        and finishes[1]['childTokens'] == 0, 'con của lượt trước không được đếm vào lượt này'

    # Không lọc lượt = số của cả PHIÊN: đó là câu hỏi của `session_metrics`, vẫn giữ nguyên.
    summary = runtime.store.children_summary(sid)
    assert summary['spawned'] == 1 and summary['childSteps'] >= 1
    assert runtime.session_metrics(sid)['peers']['spawned'] == 1
    assert runtime.store.children_summary(sid, turn=2)['spawned'] == 0
    store.close()
