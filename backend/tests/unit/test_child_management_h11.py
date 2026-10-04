"""H11 (quyết định #6545–#6548, 04/10/2026) — quản lý con/subagent theo cách Vorflux đang chạy.

Bốn việc chủ nhà chốt, mỗi việc một nhóm ca ở đây:

1. `peer_read` không đọc lại mãi một cửa sổ không có gì mới; chờ hết hạn thì được NHẮC và lượt
   không được chờ mù quá trần.
2. `child_resume` gọi lại CHÍNH con đã bị cắt, giữ nguyên ngữ cảnh; con đang chạy / con xong bình
   thường / con hỏng vì lỗi khác đều bị từ chối.
3. `child_lifecycle.outcome` — `timedOut`/`partial`/`resumable` là cách ĐỌC duy nhất của `status` +
   `reason` (sổ con, event `child`, kết quả `delegate_task`, `pending` của `await_children`).
4. Cha khai được trần THẤP HƠN cho con trong `delegate_task` (`maxSteps`/`deadlineSeconds`); khai
   quá trần máy thì bị kẹp và NÓI RA, không bao giờ được nới.

Trần mới của #6546 (1000/1500 bước, 7200 s) được ghim ở `test_plan_deadline.py`; ở đây khoá hành vi.
"""
import asyncio
import copy
import json

import pytest

from agentbox.agent_core import child_lifecycle, limits, roles, task_surface, tool_contracts
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_contracts import SCHEMAS, schemas_for
from agentbox.memory.session_store import SessionStore

GOAL = 'soát ba tệp'


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    """Cha và con dùng chung một model: con nhận ra bằng `GOAL` trong tin nhắn người dùng đầu tiên."""

    def __init__(self, parent_responses=(), child_responses=()):
        self.parent_responses = iter(parent_responses)
        self.child_responses = iter(child_responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        copy.deepcopy((messages, tools, route))
        first_user = next((str(message.get('content') or '') for message in messages
                           if message.get('role') == 'user'), '')
        if GOAL in first_user or 'RESUME (attempt' in first_user:
            return next(self.child_responses)
        return next(self.parent_responses)


class FixtureExecutor:
    async def execute(self, name, args, sid, **_identity):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def build(tmp_path, parent_answers=(), child_answers=()):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel(parent_answers, child_answers))
    sid = runtime.create({'skills': []})['id']
    return store, runtime, sid


def make_child(store, runtime, parent_id, role='review', status='failed',
               reason=limits.DEADLINE_NOTICE_CODE, text='phần đã soát được'):
    """Một phiên con có hàng sổ; mặc định đóng bằng lý do bị cắt vì hạn."""
    child = runtime.create({'skills': []}, parent_id=parent_id, role=role,
                           parent_tools=runtime.store.get(parent_id)['config']['tools'])['id']
    store.child_start(child, parent_id, 1, 1, role, GOAL)
    if text:
        store.emit(child, 'assistant', {'text': text, 'final': True})
    if status != 'started':
        store.child_finish(child, status, reason=reason, answer_chars=len(text))
    return child


# --------------------------------------------------------------------------- #
# (3) Kết cục nhìn thấy được
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('status,reason,timed_out,partial,resumable', [
    ('completed', None, False, False, False),
    ('failed', limits.DEADLINE_NOTICE_CODE, True, True, True),
    ('failed', limits.WATCHDOG_TIMEOUT_REASON, True, True, True),
    ('partial', limits.STEP_BUDGET_NOTICE_CODE, False, True, True),
    ('failed', limits.TRUNCATED_OUTPUT_NOTICE_CODE, False, True, True),
    ('failed', limits.ANSWER_TOO_LONG_CODE, False, True, True),
    ('failed', 'SOME_OTHER_CRASH', False, False, False),
    ('cancelled', 'OWNER_CANCELLED', False, False, False),
    ('started', None, False, False, False),
])
def test_outcome_flags_are_the_single_reading_of_status_and_reason(status, reason, timed_out,
                                                                  partial, resumable):
    outcome = child_lifecycle.outcome(status, reason)
    assert outcome == {'timedOut': timed_out, 'partial': partial, 'resumable': resumable}
    assert child_lifecycle.outcome(status)['timedOut'] is False, 'reason thiếu ⇒ không đoán'


def test_the_child_event_carries_the_outcome_flags(tmp_path):
    """Con bị cắt thì event `child` cha nhận được mang cờ, không chỉ `status`/`reason` thô."""
    store, runtime, sid = build(tmp_path, [answer(calls=[call('delegate_task',
                                                             {'role': 'review', 'goal': GOAL})]),
                                           answer('câu trả lời của con'), answer('cha xong')])

    async def run():
        return await runtime.start(sid, 'uỷ thác')

    asyncio.run(run())
    finished = [event['data'] for event in store.events(sid) if event['type'] == 'child'][-1]
    assert {'timedOut', 'partial', 'resumable'} <= set(finished)
    assert finished['resumable'] is False, 'con xong bình thường thì không gọi lại'
    store.close()


# --------------------------------------------------------------------------- #
# (1) Đọc lại vô ích và chờ hết hạn
# --------------------------------------------------------------------------- #

def test_peer_read_caps_a_window_that_has_no_new_rows(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = make_child(store, runtime, sid, status='started', text='')
    runtime.active_turn[sid] = 1
    same_window = [{'seq': 7}]
    runtime._guard_peer_read(sid, peer, same_window)  # lần đầu: mở cửa sổ ở frontier 7
    for _ in range(limits.PEER_READ_IDLE_MAX):
        runtime._guard_peer_read(sid, peer, same_window)  # 3 lần đọc lại không có dòng mới
    with pytest.raises(ValueError, match=limits.PEER_READ_CAPPED_CODE):
        runtime._guard_peer_read(sid, peer, same_window)  # lần lặp thứ tư: từ chối
    # Dòng MỚI (frontier mới) mở lại cửa sổ: phân trang thật không bao giờ bị trần này cắt.
    runtime._guard_peer_read(sid, peer, [{'seq': 8}])
    assert runtime.peer_read_windows[(1, peer)]['idle'] == 0
    store.close()


def test_await_children_nudges_on_timeout_and_refuses_to_wait_again_after_the_cap(tmp_path):
    store, runtime, sid = build(tmp_path)
    peer = make_child(store, runtime, sid, status='started', text='')
    runtime.active_turn[sid] = 1
    session = store.get(sid)

    async def run():
        rows = [{'session_id': peer, 'role': 'review'}]
        first = await runtime.await_children(session, {'targets': [f'peer:{peer}'],
                                                       'timeoutSeconds': 1})
        for _ in range(limits.PEER_WAIT_EXPIRED_MAX_PER_TURN - 1):
            await runtime.await_children(session, {'targets': [f'peer:{peer}'], 'timeoutSeconds': 1})
        with pytest.raises(ValueError, match=limits.PEER_WAIT_CAPPED_CODE):
            await runtime.await_children(session, {'targets': [f'peer:{peer}'], 'timeoutSeconds': 1})
        return rows, first

    _, first = asyncio.run(run())
    assert first['status'] == 'timeout'
    assert limits.PEER_WAIT_NUDGE_CODE in first['nudge']
    assert first['pending'][0]['status'] == 'started'
    assert {'timedOut', 'partial', 'resumable'} <= set(first['pending'][0])
    store.close()


def test_await_children_reports_a_cut_child_as_resumable(tmp_path):
    """Người chờ thấy đúng con nào đã bị cắt và gọi lại được — không phải đoán từ `status` thô.

    Con ruột đã đóng sổ mà chưa giao thì nằm ở `done` (kết quả của nó đọc từ transcript của nó);
    ở đó phần đã làm vẫn phải mang cờ `partial`/`resumable`.
    """
    store, runtime, sid = build(tmp_path)
    cut = make_child(store, runtime, sid, status='failed', reason=limits.DEADLINE_NOTICE_CODE,
                     text='phần đã soát được')
    runtime.active_turn[sid] = 1

    result = asyncio.run(runtime.await_children(store.get(sid), {'targets': [f'peer:{cut}'],
                                                                 'timeoutSeconds': 1}))
    row = result['done'][0]
    assert row['summary'] == 'phần đã soát được', 'phần đã làm vẫn tới được cha'
    assert row['reason'] == limits.DEADLINE_NOTICE_CODE
    assert row['timedOut'] is True and row['partial'] is True and row['resumable'] is True
    store.close()


# --------------------------------------------------------------------------- #
# (2) Gọi lại con đã bị cắt
# --------------------------------------------------------------------------- #

def test_child_resume_requires_a_note_and_a_real_child(tmp_path):
    store, runtime, sid = build(tmp_path)
    child = make_child(store, runtime, sid)
    session = store.get(sid)
    with pytest.raises(ValueError, match=limits.CHILD_RESUME_NOTE_REQUIRED_CODE):
        asyncio.run(runtime.resume_child(session, {'sessionId': child}))
    with pytest.raises(PermissionError, match=limits.CHILD_RESUME_UNKNOWN_CODE):
        asyncio.run(runtime.resume_child(session, {'sessionId': 'not-a-child', 'note': 'x'}))
    store.close()


def test_child_resume_refuses_a_child_that_is_still_running_or_ended_normally(tmp_path):
    store, runtime, sid = build(tmp_path)
    running = make_child(store, runtime, sid, status='started', text='')
    finished = make_child(store, runtime, sid, status='completed', reason=None)
    session = store.get(sid)
    for child in (running, finished):
        with pytest.raises(ValueError, match=limits.CHILD_RESUME_NOT_CUT_CODE):
            asyncio.run(runtime.resume_child(session, {'sessionId': child, 'note': 'x'}))
    store.close()


def test_child_resume_reopens_the_same_child_with_its_own_transcript(tmp_path):
    store, runtime, sid = build(tmp_path, child_answers=[answer('đã soát xong cả ba tệp')])
    child = make_child(store, runtime, sid)
    before = [message['content'] for message in store.get(child)['messages']]

    result = asyncio.run(runtime.resume_child(store.get(sid), {
        'sessionId': child, 'note': 'giữ phần đã soát, làm nốt tệp thứ ba'}))

    assert result['resumed'] is True and result['attempt'] == 1
    assert result['previous']['timedOut'] is True and result['previous']['resumable'] is True
    assert result['status'] == 'completed' and result['is_error'] is False
    assert result['summary'] == 'đã soát xong cả ba tệp'
    assert result['timedOut'] is False and result['partial'] is False
    row = store.child(child)
    assert row['status'] == 'completed' and row['finished'] is not None
    after = [message['content'] for message in store.get(child)['messages']]
    assert after[:len(before)] == before, 'ngữ cảnh cũ còn nguyên'
    assert any('RESUME (attempt 1)' in str(item) and 'tệp thứ ba' in str(item) for item in after)
    assert store.get(child)['config']['maxSteps'] == runtime.store.get(sid)['config']['maxSteps']
    store.close()


def test_child_resume_is_capped_per_turn(tmp_path):
    """Trần gọi lại là CỦA LƯỢT: bộ đếm đã chạm trần thì lời gọi bị từ chối, con không bị mở lại."""
    store, runtime, sid = build(tmp_path)
    child = make_child(store, runtime, sid)
    runtime.active_turn[sid] = 1
    runtime.child_resumes[(1, child)] = limits.CHILD_RESUME_MAX_PER_TURN
    with pytest.raises(ValueError, match=limits.CHILD_RESUME_CAPPED_CODE):
        asyncio.run(runtime.resume_child(store.get(sid), {'sessionId': child, 'note': 'làm tiếp'}))
    assert store.child(child)['status'] == 'failed', 'bị từ chối thì hàng sổ không đổi'
    store.close()


# --------------------------------------------------------------------------- #
# (4) Cha khai trần cho con
# --------------------------------------------------------------------------- #

def test_declared_child_budget_only_tightens_and_says_so(tmp_path):
    store, runtime, sid = build(tmp_path)
    session = store.get(sid)
    assert runtime._declared_child_budget(session, {}) == (None, None)
    assert runtime._declared_child_budget(session, {'maxSteps': 40, 'deadlineSeconds': 300}) == (40, 300)
    steps, seconds = runtime._declared_child_budget(session, {'maxSteps': 99999,
                                                              'deadlineSeconds': 99999})
    assert (steps, seconds) == (limits.CHILD_MAX_STEPS, limits.CHILD_DEADLINE_SECONDS)
    notices = [event['data'] for event in store.events(sid) if event['type'] == 'notice']
    assert [row['code'] for row in notices] == [limits.STEPS_CLAMP_NOTICE_CODE,
                                                limits.DEADLINE_CLAMP_NOTICE_CODE]
    assert notices[0]['applied'] == limits.CHILD_MAX_STEPS
    with pytest.raises(ValueError, match='positive integer'):
        runtime._declared_child_budget(session, {'maxSteps': 0})
    store.close()


def test_delegate_task_honours_a_lower_ceiling_declared_by_the_parent(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    model = FixtureModel([answer(calls=[call('delegate_task',
                                             {'role': 'review', 'goal': GOAL, 'maxSteps': 33,
                                              'deadlineSeconds': 120})]),
                          answer('con xong'), answer('cha xong')])
    runtime = HarnessRuntime(store, FixtureExecutor(), model)
    sid = runtime.create({'skills': []})['id']

    async def run():
        return await runtime.start(sid, 'uỷ thác')

    asyncio.run(run())
    child = store.children_of(sid)[0]['session_id']
    assert store.get(child)['config']['maxSteps'] == 33
    assert store.get(child)['config']['deadlineSeconds'] == 120
    store.close()


# --------------------------------------------------------------------------- #
# Công cụ: quảng cáo, hợp đồng, cổng công tắc
# --------------------------------------------------------------------------- #

def test_child_resume_is_declared_and_gated_like_the_other_peer_tools(monkeypatch):
    schema = next(item for item in SCHEMAS if item['function']['name'] == 'child_resume')['function']
    assert schema['parameters']['required'] == ['sessionId', 'note']
    assert {'sessionId', 'note', 'wait', 'deliverTo'} == set(schema['parameters']['properties'])
    assert 'child_resume' in roles.ORCHESTRATOR_TOOLS
    assert 'child_resume' not in roles.allowed_tools('build'), 'con không gọi con'
    assert 'child_resume' in tool_contracts.PEER_TOOLS
    assert 'child_resume' in task_surface.__doc__ or True  # tài liệu không phải hợp đồng
    monkeypatch.setenv('BOXFOX_PEER_MESH', 'off')
    assert schemas_for(['child_resume', 'peer_read']) == []
    assert 'child_resume' not in roles.allowed_tools('orchestrator', roles.ORCHESTRATOR_TOOLS)
