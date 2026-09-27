"""Decision flow: ask_user / request_approval block the turn until the user really answers.

Contract: docs/plan/next-batch-contract.md §1 (events + awaiting_decision) and §2 (route).
"""
import asyncio
import copy
import json
import time

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS, ROLES
from agentbox.agent_core.runtime import (DECISION_MAX_SECONDS, DecisionError, HarnessRuntime,
                                         decision_deadline, normalize_decision_options,
                                         with_other_option)
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

REQUESTED_KEYS = {'decisionId', 'kind', 'question', 'action', 'reason', 'options', 'deadline',
                  'defaultChoice', 'toolCallId'}
RESOLVED_KEYS = {'decisionId', 'choice', 'status', 'note', 'reason', 'resolvedAt'}
DECISION_TOOLS = {'ask_user', 'request_approval'}
HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append(copy.deepcopy((messages, tools, route)))
        return next(self.responses)


class FixtureExecutor:
    def __init__(self):
        self.calls = []
        self.cleaned = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        self.cleaned.append(sid)


def events_of(store, sid, kind):
    return [event for event in store.events(sid) if event['type'] == kind]


def only(store, sid, kind):
    items = events_of(store, sid, kind)
    assert len(items) == 1, 'expected exactly one ' + kind + ', found ' + str(len(items))
    return items[0]


def tool_results(store, sid):
    return [json.loads(message['content']) for message in store.get(sid)['messages'] if message['role'] == 'tool']


async def wait_for_status(store, sid, status, timeout=5):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if store.get(sid)['status'] == status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError('session never reached ' + status + '; it is ' + store.get(sid)['status'])


async def blocked_session(runtime, store, prompt='Làm việc'):
    sid = runtime.create({'skills': []})['id']
    runtime.start(sid, prompt)
    await wait_for_status(store, sid, 'awaiting_decision')
    record = runtime.pending_for(sid)[0]
    return sid, record


def test_ask_user_blocks_until_answered_through_the_route(tmp_path):
    """ask_user emits the contract event, blocks the turn, and continues on a real answer."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Cần bạn chọn', calls=[call('ask_user', {
                'question': 'Chọn cách triển khai?',
                'options': [{'id': 'fast', 'label': 'Nhanh', 'kind': 'alternative'},
                            {'id': 'safe', 'label': 'An toàn', 'kind': 'alternative'},
                            {'id': 'reject', 'label': 'Từ chối', 'kind': 'reject'}]})]),
            answer('Đã làm theo lựa chọn')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        started = time.time()
        sid, record = await blocked_session(runtime, store, 'Triển khai tính năng')

        # the blocked turn is persisted as awaiting_decision, not running
        assert store.get(sid)['status'] == 'awaiting_decision'
        assert record['toolCallId'] == 'c1' and record['defaultChoice'] == 'reject'

        requested = only(store, sid, 'decision_requested')
        payload = requested['data']
        assert set(payload) == REQUESTED_KEYS, 'decision_requested must match contract §1 exactly'
        assert payload['decisionId'] == record['decisionId'] and len(payload['decisionId']) == 16
        assert payload['kind'] == 'question'
        assert payload['question'] == 'Chọn cách triển khai?'
        assert payload['action'] is None and payload['reason'] is None
        assert payload['defaultChoice'] == 'reject'
        assert payload['toolCallId'] == 'c1'
        assert payload['options'][:-1] == [
            {'id': 'approve', 'label': 'Nhanh', 'kind': 'approve'},
            # 'fast' fills the guaranteed approve slot; the untouched alternative keeps its own id
            {'id': 'safe', 'label': 'An toàn', 'kind': 'alternative'},
            {'id': 'reject', 'label': 'Từ chối', 'kind': 'reject'}]
        # P4: runtime LUÔN thêm lựa chọn tự nhập, và nó là lựa chọn free-text
        assert payload['options'][-1] == {'id': 'other', 'label': 'Khác (tự nhập)',
                                          'kind': 'alternative', 'allowFreeText': True}
        assert 290 <= payload['deadline'] - started <= 300.5, 'ask_user defaults to 300 s'
        assert isinstance(payload['deadline'], float)

        intent = only(store, sid, 'ui_intent')
        assert intent['data'] == {'tab': 'decisions', 'target': {'requestId': payload['decisionId']},
                                 'reason': 'decision_requested'}
        assert intent['seq'] == requested['seq'] + 1, 'the ui_intent must follow the request immediately'

        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as client:
                url = str(server.make_url('/api/agent/sessions')) + '/' + sid + '/decisions'
                async with client.post(url, json={'decisionId': payload['decisionId'], 'choice': 'safe', 'note': 'ok'}) as resp:
                    assert resp.status == 200
                    assert await resp.json() == {'status': 'resolved', 'decisionId': payload['decisionId'],
                                                 'choice': 'safe', 'outcome': 'approved'}
                assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Đã làm theo lựa chọn'
                async with client.post(url, json={'decisionId': payload['decisionId'], 'choice': 'safe'}) as resp:
                    assert resp.status == 409
                    assert (await resp.json())['error'].startswith('DECISION_ALREADY_RESOLVED:')

                resolved = only(store, sid, 'decision_resolved')
                assert set(resolved['data']) == RESOLVED_KEYS, 'decision_resolved must match contract §1 exactly'
                assert resolved['data']['decisionId'] == payload['decisionId']
                assert resolved['data']['choice'] == 'safe'
                assert resolved['data']['status'] == 'approved'
                assert resolved['data']['reason'] == 'user'
                assert resolved['data']['note'] == 'ok'
                assert resolved['data']['resolvedAt'] >= requested['created']
                assert store.get(sid)['status'] == 'completed'

                seen = tool_results(store, sid)[-1]
                assert seen['decision'] == 'approved' and seen['choice'] == 'safe' and seen['status'] == 'approved'
                assert 'approved' in json.dumps(model.requests[-1][0])
        store.close()

    asyncio.run(run())


def test_rejection_is_honest_and_the_status_returns_to_running(tmp_path):
    """A rejected approval never looks like consent, and the persisted status goes back to running."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin phép xoá', calls=[call('request_approval', {'action': 'rm -rf build', 'reason': 'Xoá thư mục build'})]),
            answer('Đã dừng; không xoá gì.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        started = time.time()
        sid, record = await blocked_session(runtime, store, 'Dọn dẹp')

        payload = only(store, sid, 'decision_requested')['data']
        assert payload['kind'] == 'approval'
        assert payload['action'] == 'rm -rf build' and payload['reason'] == 'Xoá thư mục build'
        assert payload['question'] is None
        assert [option['id'] for option in payload['options']] == ['approve', 'reject', 'other'], \
            'approval defaults to the pair plus the free-text choice'
        assert 590 <= payload['deadline'] - started <= 600.5, 'request_approval defaults to 600 s'

        assert runtime.resolve_decision(sid, record['decisionId'], 'reject', None) == {
            'status': 'resolved', 'decisionId': record['decisionId'], 'choice': 'reject', 'outcome': 'rejected'}
        # no await in between: the persisted status is already back to running
        assert store.get(sid)['status'] == 'running'
        assert record['future'].done() and record['outcome']['decision'] == 'rejected'

        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Đã dừng; không xoá gì.'
        resolved = only(store, sid, 'decision_resolved')['data']
        assert resolved['status'] == 'rejected' and resolved['reason'] == 'user' and resolved['note'] is None
        assert resolved['choice'] == 'reject'

        seen = tool_results(store, sid)[-1]
        assert seen['decision'] == 'rejected' and seen['status'] == 'rejected'
        assert seen['choice'] == 'reject' and seen['reason'] == 'user'
        assert 'Do not perform it' in seen['message']
        assert 'rejected' in json.dumps(model.requests[-1][0])
        assert store.get(sid)['status'] == 'completed'
        store.close()

    asyncio.run(run())


def test_timeout_expires_as_rejected_and_the_turn_continues(tmp_path):
    """Nobody answers: the decision expires as a rejection, exactly once, and the turn keeps going."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin phép dọn cache', calls=[call('request_approval', {
                'action': 'rm -rf .cache', 'reason': 'Giải phóng chỗ', 'deadlineSeconds': 1})]),
            answer('Không ai trả lời nên tôi không xoá.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        started = time.time()
        sid, record = await blocked_session(runtime, store, 'Dọn cache')

        payload = only(store, sid, 'decision_requested')['data']
        assert 0 < payload['deadline'] - started <= 3, 'the model requested a 1 s deadline'

        assert await asyncio.wait_for(runtime.tasks[sid], 10) == 'Không ai trả lời nên tôi không xoá.'
        resolved = only(store, sid, 'decision_resolved')['data']
        assert resolved['status'] == 'expired' and resolved['reason'] == 'timeout'
        assert resolved['choice'] == payload['defaultChoice'] == 'reject'
        assert resolved['note'] is None and resolved['decisionId'] == record['decisionId']
        assert resolved['resolvedAt'] >= payload['deadline'] - 0.05
        assert store.get(sid)['status'] == 'completed', 'the turn continues after the decision expires'

        seen = tool_results(store, sid)[-1]
        assert seen['decision'] == 'rejected', 'a timeout must never be reported as approval'
        assert seen['reason'] == 'timeout' and seen['status'] == 'expired'
        assert seen['choice'] == 'reject' and seen['note'] is None
        assert 'expired' in json.dumps(model.requests[-1][0])
        store.close()

    asyncio.run(run())


def test_stop_while_pending_cancels_once_and_leaks_no_task(tmp_path):
    """Stopping a blocked session releases the future and emits exactly one cancelled resolution."""

    async def run():
        baseline = {task for task in asyncio.all_tasks() if task is not asyncio.current_task()}
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([answer('Hỏi bạn', calls=[call('ask_user', {'question': 'Tiếp tục?', 'options': ['Tiếp', 'Dừng']})])])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Tiếp tục nhé')
        future = record['future']

        await runtime.stop(sid)
        assert store.get(sid)['status'] == 'cancelled'
        assert future.done(), 'the blocked turn must be released'
        assert runtime.pending_for(sid) == []
        resolved = only(store, sid, 'decision_resolved')['data']
        assert resolved['status'] == 'cancelled' and resolved['reason'] == 'session_cancelled'
        assert resolved['choice'] == record['defaultChoice'] == 'reject'
        assert resolved['decisionId'] == record['decisionId']
        assert runtime.tasks[sid].done()

        await asyncio.sleep(0.05)
        assert {task for task in asyncio.all_tasks() if task is not asyncio.current_task()} == baseline, \
            'stopping a decision must not leak a task'
        store.close()

    asyncio.run(run())


def test_decision_route_error_codes(tmp_path):
    """404 unknown decision, 409 double answer, 400 missing fields or a choice outside the options."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([answer('Hỏi', calls=[call('ask_user', {'question': 'Chọn?', 'options': ['A', 'B']})]),
                              answer('Xong')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Việc')

        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as client:
                url = str(server.make_url('/api/agent/sessions')) + '/' + sid + '/decisions'

                async def post(body):
                    async with client.post(url, json=body) as response:
                        return response.status, await response.json()

                status, body = await post({'decisionId': 'ffffffffffffffff', 'choice': 'approve'})
                assert status == 404 and body['error'].startswith('DECISION_NOT_FOUND:')
                status, body = await post({'choice': 'approve'})
                assert status == 400 and body['error'].startswith('DECISION_INVALID:')
                status, body = await post({'decisionId': record['decisionId']})
                assert status == 400 and body['error'].startswith('DECISION_INVALID:')
                status, body = await post({'decisionId': record['decisionId'], 'choice': 'nope'})
                assert status == 400 and body['error'].startswith('DECISION_INVALID:')
                status, body = await post({'decisionId': record['decisionId'], 'choice': 'approve', 'note': 7})
                assert status == 400 and body['error'].startswith('DECISION_INVALID:')

                status, body = await post({'decisionId': record['decisionId'], 'choice': 'approve'})
                assert status == 200 and body['outcome'] == 'approved'
                status, body = await post({'decisionId': record['decisionId'], 'choice': 'approve'})
                assert status == 409 and body['error'].startswith('DECISION_ALREADY_RESOLVED:')

                # a decision can only be answered through the session that owns it
                other = str(server.make_url('/api/agent/sessions')) + '/deadbeef/decisions'
                async with client.post(other, json={'decisionId': record['decisionId'], 'choice': 'approve'}) as response:
                    assert response.status == 404
                    assert (await response.json())['error'].startswith('DECISION_NOT_FOUND:')

                async with client.post(url, data='{not json', headers={'Content-Type': 'application/json'}) as response:
                    assert response.status == 400
                    assert (await response.json())['error'].startswith('DECISION_INVALID:')

                assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Xong'
        store.close()

    asyncio.run(run())


def test_decision_tools_are_role_gated(tmp_path):
    """The tools are advertised to the roles that own them and blocked at dispatch for the rest."""

    assert DECISION_TOOLS <= ORCHESTRATOR_TOOLS
    for role in ROLES.values():
        assert DECISION_TOOLS <= role.tools, role.id + ' must be able to ask the user'
    assert 'write_plan' in ORCHESTRATOR_TOOLS and 'write_plan' in ROLES['plan'].tools

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([answer(calls=[call('ask_user', {'question': 'x?', 'options': ['a', 'b']})]),
                              answer('Không dùng được công cụ')])
        executor = FixtureExecutor()
        runtime = HarnessRuntime(store, executor, model)
        session = runtime.create({'skills': []}, role='review')
        sid = session['id']
        config = session['config']
        config['tools'] = [name for name in config['tools'] if name not in DECISION_TOOLS]
        store.update_config(sid, config)

        await runtime.start(sid, 'Thử hỏi')
        assert runtime.pending_for(sid) == []
        assert events_of(store, sid, 'decision_requested') == []
        assert events_of(store, sid, 'ui_intent') == []
        # `session_ensure` (A1) chạy ở đầu MỌI lượt (dọn `<sid8>/session.json` trong box) — nó không
        # phải một công cụ, nên bỏ ra trước khi khẳng định "công cụ bị chặn không chạm executor".
        assert [name for name, _, _ in executor.calls if name != 'session_ensure'] == [], \
            'a gated tool must never reach the executor'
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'not permitted' in failures[0]['error']
        store.close()

    asyncio.run(run())


def test_a_delegated_child_cannot_ask_the_user(tmp_path):
    """A question raised inside a child session is refused before any event, so it cannot hang the parent turn.

    Only root sessions are listed (session_store.list -> parent_id IS NULL) and the UI reads decisions for
    the active chat only, so a child question would be invisible and unanswerable while still blocking the
    parent turn for the full ask_user deadline (300 s) against the parent's own 180 s budget.
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            # parent turn delegates the decision to a specialist
            answer('Giao cho chuyên gia', calls=[call('delegate_task', {'role': 'review', 'goal': 'Kiểm tra giúp'}, 'p1')]),
            # the child tries to ask the user: must be an ordinary tool error
            answer('Cần bạn chọn', calls=[call('ask_user', {'question': 'Chọn giúp tôi?', 'options': ['a', 'b']}, 'c1')]),
            answer('Tự quyết theo bằng chứng của mình'),
            # parent turn continues normally
            answer('Đã xong theo bằng chứng của chuyên gia')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        parent_sid = runtime.create({'skills': []})['id']

        started = time.monotonic()
        task = runtime.start(parent_sid, 'Nhờ chuyên gia kiểm tra')
        assert await asyncio.wait_for(task, 10) == 'Đã xong theo bằng chứng của chuyên gia'
        assert time.monotonic() - started < 5, 'a child question must never burn the parent turn budget'

        child_sid = store.db.execute('SELECT id FROM sessions WHERE parent_id=?', (parent_sid,)).fetchone()['id']
        # the child can never become the active chat, which is why asking there was refused
        assert [row['id'] for row in store.list()] == [parent_sid]

        for sid in (parent_sid, child_sid):
            assert events_of(store, sid, 'decision_requested') == [], 'no decision may be raised on ' + sid
            assert events_of(store, sid, 'ui_intent') == []
            assert runtime.pending_for(sid) == []
        assert store.get(child_sid)['status'] == 'completed', 'the child must never stall as awaiting_decision'

        failures = [result for result in tool_results(store, child_sid) if result.get('is_error')]
        assert failures and 'DECISION_UNAVAILABLE' in failures[0]['error']
        # the child saw a normal tool error and decided from its own evidence
        assert 'DECISION_UNAVAILABLE' in json.dumps(store.get(child_sid)['messages'], ensure_ascii=False)
        # the parent reads the child as a normal completed delegation, not as a stalled question
        delegation = tool_results(store, parent_sid)[-1]
        assert delegation['status'] == 'completed' and delegation['is_error'] is False
        store.close()

    asyncio.run(run())


def test_option_normalization_and_deadline_ceiling():
    """Pure helpers: 2-5 options with a guaranteed approve/reject pair, deadlines clamped to 3600 s."""
    options = normalize_decision_options(['Nhanh', 'Kỹ'], 'question')
    assert [option['kind'] for option in options] == ['approve', 'reject']
    assert [option['id'] for option in options] == ['approve', 'reject']
    assert [option['label'] for option in options] == ['Nhanh', 'Kỹ']

    mixed = normalize_decision_options([{'id': 'Alpha', 'label': 'Alpha'}, {'label': 'Beta'}, {'label': 'Gamma'}], 'question')
    assert [option['id'] for option in mixed] == ['approve', 'beta', 'reject']

    kept = normalize_decision_options([{'id': 'allow-once', 'label': 'Allow once', 'kind': 'approve'},
                                       {'id': 'deny', 'label': 'Deny', 'kind': 'reject'}], 'approval')
    assert [option['id'] for option in kept] == ['approve', 'reject']
    assert kept[0]['label'] == 'Allow once' and kept[1]['label'] == 'Deny'

    for bad in (None, [], ['only-one'], [str(index) for index in range(6)]):
        with pytest.raises(ValueError, match='DECISION_INVALID'):
            normalize_decision_options(bad, 'question')
    assert [option['id'] for option in normalize_decision_options(None, 'approval')] == ['approve', 'reject']

    # P4: cờ tự nhập của lựa chọn model đi nguyên xuống danh sách phát ra…
    free = normalize_decision_options([{'id': 'a', 'label': 'A', 'allowFreeText': True}, 'B'], 'question')
    assert free[0]['allowFreeText'] is True
    assert all('allowFreeText' not in option for option in free[1:])
    # …và mọi danh sách phát ra đều được thêm ô tự nhập, không nhân đôi khi model đã tự phát 'other'.
    other = with_other_option(normalize_decision_options(['A', 'B'], 'question'))
    assert other[-1] == {'id': 'other', 'label': 'Khác (tự nhập)', 'kind': 'alternative',
                         'allowFreeText': True}
    twice = with_other_option([{'id': 'other', 'label': 'Tự nhập', 'kind': 'alternative'},
                               {'id': 'reject', 'label': 'Không', 'kind': 'reject'}])
    assert [option['id'] for option in twice] == ['other', 'reject']
    assert twice[0]['allowFreeText'] is True and twice[0]['label'] == 'Tự nhập', \
        'id other là ô tự nhập theo hợp đồng, dù nhãn của model vẫn được giữ'

    now = 1000000.0
    assert decision_deadline({}, 'ask_user', now) == now + 300
    assert decision_deadline({}, 'request_approval', now) == now + 600
    assert decision_deadline({'deadlineSeconds': 10000}, 'ask_user', now) == now + DECISION_MAX_SECONDS
    assert decision_deadline({'deadlineSeconds': 120}, 'ask_user', now) == now + 120
    assert decision_deadline({'deadline': 5}, 'ask_user', now) == now + 5
    assert decision_deadline({'deadlineSeconds': 'nonsense'}, 'ask_user', now) == now + 300


def test_the_free_text_choice_needs_typed_text_and_the_text_reaches_the_model(tmp_path):
    """P4: `choice='other'` without text is 400; with text the answer is pinned and reaches the model."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([answer('Cần bạn chọn', calls=[call('ask_user', {'question': 'Chọn?', 'options': ['A', 'B']})]),
                              answer('Xong theo câu trả lời tự nhập')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Việc')
        payload = only(store, sid, 'decision_requested')['data']
        assert payload['options'][-1] == {'id': 'other', 'label': 'Khác (tự nhập)',
                                          'kind': 'alternative', 'allowFreeText': True}
        typed = 'Chọn phương án C và ghi rõ lý do'

        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as client:
                url = str(server.make_url('/api/agent/sessions')) + '/' + sid + '/decisions'

                async def post(body):
                    async with client.post(url, json=body) as response:
                        return response.status, await response.json()

                status, body = await post({'decisionId': record['decisionId'], 'choice': 'other'})
                assert status == 400 and body['error'].startswith('DECISION_NOTE_REQUIRED:')
                status, body = await post({'decisionId': record['decisionId'], 'choice': 'other', 'note': '   '})
                assert status == 400 and body['error'].startswith('DECISION_NOTE_REQUIRED:'), \
                    'chữ chỉ có khoảng trắng vẫn là chưa gõ gì'
                status, body = await post({'decisionId': record['decisionId'], 'choice': 'other',
                                           'note': 'x' * 2001})
                assert status == 400 and body['error'].startswith('DECISION_NOTE_TOO_LONG:')
                # Ba lần từ chối trên KHÔNG chốt gì: quyết định vẫn treo tới câu trả lời hợp lệ.
                assert store.get(sid)['status'] == 'awaiting_decision' and events_of(store, sid, 'decision_resolved') == []
                status, body = await post({'decisionId': record['decisionId'], 'choice': 'other',
                                           'note': f'  {typed}  '})
                # P4 (vá vòng soát) — chữ tự nhập là CÂU TRẢ LỜI trung tính, không phải một lời duyệt.
                assert status == 200 and body['outcome'] == 'answered'
                assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Xong theo câu trả lời tự nhập'

                # `TestServer.__aexit__` đóng store (app cleanup), nên mọi khẳng định phải ở trong khối.
                resolved = only(store, sid, 'decision_resolved')['data']
                assert resolved['choice'] == 'other' and resolved['note'] == typed
                seen = tool_results(store, sid)[-1]
                assert seen['choice'] == 'other' and seen['note'] == typed, 'model phải đọc được chữ đã gõ'
                assert seen['decision'] == 'answered' and seen['status'] == 'answered', \
                    'kết cục tự nhập phải giữ đúng chữ `answered`, không bị hoá thành `approved`'
                assert 'Do NOT treat this as approval' in seen['message'], \
                    'lời nhắn cho model phải nói thẳng: chữ tự nhập KHÔNG phải đồng ý'
                assert typed in json.dumps(model.requests[-1][0], ensure_ascii=False), 'chữ đã gõ phải tới model'
                pins = [row['payload']['record'] for row in store.journal_tail(sid, limit=50, kinds=['decision'])
                        if (row['payload'] or {}).get('record')]
                chosen = [pin for pin in pins if pin.get('data', {}).get('choice') == 'other']
                assert chosen and chosen[-1]['data']['note'] == typed, 'hàng D: phải ghim chữ đã gõ'
        store.close()

    asyncio.run(run())


def test_a_model_supplied_free_text_option_keeps_its_flag(tmp_path):
    """P4: a model option marked `allowFreeText` renders a text box and requires text when picked."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Cần bạn chọn', calls=[call('ask_user', {
                'question': 'Chọn?',
                'options': [{'id': 'a', 'label': 'A', 'allowFreeText': True}, 'B']})]),
            answer('Xong theo chữ tự nhập')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Việc')

        payload = only(store, sid, 'decision_requested')['data']
        assert payload['options'][0]['id'] == 'approve' and payload['options'][0]['allowFreeText'] is True
        assert [option['id'] for option in payload['options']] == ['approve', 'reject', 'other']

        with pytest.raises(DecisionError) as excinfo:
            runtime.resolve_decision(sid, record['decisionId'], 'approve', None)
        assert 'DECISION_NOTE_REQUIRED' in str(excinfo.value) and excinfo.value.status == 400
        # Lựa chọn của MODEL mang cờ tự nhập cũng chốt `answered`: hễ có ô gõ chữ thì đó là trả lời,
        # không phải một cái gật đầu (P4, vá vòng soát) — dù nhãn/id là `approve` đi nữa.
        assert runtime.resolve_decision(sid, record['decisionId'], 'approve', 'chữ tự nhập')['outcome'] == 'answered'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Xong theo chữ tự nhập'
        store.close()

    asyncio.run(run())
