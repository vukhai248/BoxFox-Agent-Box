"""Cổng PHẢN BIỆN ĐỘC LẬP (D-33/D-34): chưa có phán quyết `ok` thì không xin duyệt được.

Đo vòng 25: sáu lượt liên tiếp ghi kế hoạch rồi xin duyệt mà **không ai** phản biện, và tab Plan
duyệt được một bản chưa ai kiểm — bấm một cái là phiên vào `awaiting_decision`, rồi hàng sổ nói
"approved" cho một bản chưa qua vòng nào. Chủ nhà chốt: *"chặn cứng, có công tắc hạ xuống"*.

Vòng 25 đặt **một** cổng, hai đường đi qua cùng một hàm:
* chat — `request_approval` mang cặp khoá plan bị `decision()` từ chối **trước** khi dựng
  `decision_requested`, nên phiên không vào `awaiting_decision` (không còn lượt chờ 600 s rồi hết hạn);
* tab Plan — `POST /api/agent/plans/review` với `decision='approved'` bị từ chối bằng 409 **trước**
  khi ghi sổ, nên không có hàng duyệt nào cho một bản chưa phản biện.

Ba mức `BOXFOX_PLAN_VERIFY` = `enforce|warn|off`, đọc MỖI LƯỢT: giá trị lạ **không** được hạ cấp
trong im lặng (rơi về `enforce` + một `notice` nói ra giá trị lạ).
"""
from __future__ import annotations

import asyncio
import copy
import json

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import limits, plan_registry, runtime as runtime_module
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore
from agentbox.observability.system_log import SystemLog, read_entries

IDENTITY = 'clinical-patient-record-lookup-research'
HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
REVIEW_ROUTE = '/api/agent/plans/review'
INFO_ROUTE = '/api/agent/runtime-info'


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
    def __init__(self, payload=None):
        self.payload = payload
        self.calls = []
        self.requests = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'content': 'observed fixture result'}

    async def request(self, path, body=None, session=None):
        self.requests.append((path, body))
        if path == plan_registry.INDEX_PATH:
            return self.payload
        return {'ok': True}

    async def cleanup(self, sid):
        pass


class QuietRouter:
    async def model_metadata_map(self):
        return {}


def approval_args(version=1, **extra):
    args = {'action': 'apply the plan', 'reason': 'Kế hoạch đã viết xong, cần bạn duyệt',
            'planIdentity': IDENTITY, 'planVersion': version}
    args.update(extra)
    return args


def seed_ok(store, version=1, verdict='ok'):
    """Một hàng phán quyết đã có trong sổ, đúng khuôn `plan_verify` ghi."""
    store.record_plan_verification(IDENTITY, version, verdict,
                                   issues=[{'severity': 'low', 'text': 'thiếu mục Sources'}],
                                   summary='một lỗi nhẹ', critic_session_id='critic-fixture',
                                   critic_answer_chars=512, critic_verdict=verdict)


async def drive(tmp_path, responses, seed=None, wait_for_decision=False, timeout=5.0):
    """Một lượt chat thật, chạy TRONG loop đang mở; trả `(store, runtime, sid)`.

    `wait_for_decision=True` dừng ở lúc phiên đang chờ người dùng — trạng thái đó chỉ đọc được
    TRONG loop, vì đóng loop là huỷ luôn lượt đang chờ (`asyncio.run` không giữ nó sống). Vì thế
    các ca "được phép duyệt" tự mở `asyncio.run(run())` rồi kiểm bên trong.
    """
    store = SessionStore(tmp_path / 'sessions.db')
    if seed is not None:
        seed(store)
    model = FixtureModel(responses)
    runtime = HarnessRuntime(store, FixtureExecutor(), model)
    sid = runtime.create({'skills': []})['id']
    started = runtime.start(sid, 'Trình kế hoạch để bạn duyệt')
    if wait_for_decision:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if store.get(sid)['status'] == 'awaiting_decision':
                return store, runtime, sid
            await asyncio.sleep(0.01)
        raise AssertionError('session never reached awaiting_decision; it is '
                             + store.get(sid)['status'])
    await asyncio.wait_for(started, timeout)
    return store, runtime, sid


def run_turn(tmp_path, responses, seed=None, timeout=5.0):
    """`drive` cho ca lượt tự chạy hết (không chờ người dùng)."""
    return asyncio.run(drive(tmp_path, responses, seed=seed, timeout=timeout))


def tool_end_rows(store, sid):
    """KẾT QUẢ công cụ của lượt (không phải vỏ event): mã lỗi nằm trong `result`."""
    return [event['data']['result'] for event in store.events(sid) if event['type'] == 'tool_end']


def events_of(store, sid, kind):
    return [event['data'] for event in store.events(sid) if event['type'] == kind]


def call_route(tmp_path, executor, method, path, body=None, monkeypatch=None, mode=None,
               verified=None):
    """Một request thật qua aiohttp; trả `(status, payload, rows)`.

    `rows` là hàng sổ duyệt đọc TRƯỚC khi `create_app` đóng store trong cleanup — chỉ như thế mới
    kiểm được "cổng chặn trước khi ghi". `mode` (nếu có) đặt `BOXFOX_PLAN_VERIFY` cho lượt này;
    `verified` gieo sẵn phán quyết `ok` cho bản đó (ca cổng cho qua).
    """
    if monkeypatch is not None and mode is not None:
        monkeypatch.setenv(limits.PLAN_VERIFY_ENV, mode)

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        for number in ([verified] if isinstance(verified, int) else list(verified or ())):
            seed_ok(store, number)
        runtime = HarnessRuntime(store, executor, QuietRouter())
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                kwargs = {'json': body} if body is not None else {}
                async with client.request(method, path, headers=HEADERS, **kwargs) as response:
                    text = await response.text()
                    try:
                        payload = json.loads(text)
                    except ValueError:
                        payload = text
                    status = response.status
            rows = store.plan_reviews_for(IDENTITY)
        return status, payload, rows

    return asyncio.run(run())


def fake_index(versions=((1, 4650, '2026-09-20T13:50:00Z'),)):
    """Chỉ mục box tối thiểu cho route duyệt: đủ để `relativePath`/`version` phân giải được."""
    directory, tail = plan_registry.split_identity(IDENTITY)
    return {'plans': [{
        'identity': IDENTITY, 'relativeDirectory': directory, 'slug': tail,
        'versions': [{'version': version, 'label': f'v{version}',
                      'relativePath': f'.plans/v{version}-{tail}.md', 'sizeBytes': size,
                      'modifiedAt': modified, 'status': 'draft', 'headerStatus': 'ok',
                      'headerVersion': version, 'headerIdentity': IDENTITY,
                      'declaredParent': None, 'declaredSlug': None}
                     for version, size, modified in versions],
    }], 'ignoredCount': 0, 'warnings': []}


# --- Đường chat: `request_approval` ---------------------------------------------------------------

def test_approval_without_a_critique_is_refused_and_never_waits(tmp_path):
    """Bản chưa có phán quyết `ok`: lỗi công cụ + KHÔNG chờ — đo vòng 25 là lượt chờ 600 s rồi hết hạn."""
    store, runtime, sid = run_turn(tmp_path, [
        answer('Xin bạn duyệt', calls=[call('request_approval', approval_args())]),
        answer('Đã hiểu, tôi đi phản biện trước.')])

    ends = tool_end_rows(store, sid)
    assert [row.get('errorCode') for row in ends] == ['PLAN_APPROVAL_UNVERIFIED'], ends
    assert limits.PLAN_APPROVAL_UNVERIFIED_CODE in ends[0]['error']
    assert "role='plan-review'" in ends[0]['error']
    # Không có lượt chờ nào: phiên chạy tiếp ngay trong CÙNG lượt, và không có gì vào sổ duyệt.
    assert events_of(store, sid, 'decision_requested') == []
    assert runtime.pending == {}
    assert store.get(sid)['status'] != 'awaiting_decision'
    assert store.plan_review(IDENTITY, 1) is None


def test_an_ok_verdict_for_the_same_version_lets_the_approval_through(tmp_path):
    """Có phán quyết `ok` cho ĐÚNG bản đó thì cổng im lặng: lượt xin duyệt chạy như cũ."""
    async def run():
        store, runtime, sid = await drive(tmp_path, [
            answer('Xin duyệt', calls=[call('request_approval', approval_args())])],
            seed=lambda s: seed_ok(s, 1), wait_for_decision=True)
        record = runtime.pending_for(sid)[0]
        assert (record['planIdentity'], record['planVersion']) == (IDENTITY, 1)
        assert record['kind'] == 'approval'
        assert events_of(store, sid, 'decision_requested')
        assert store.get(sid)['status'] == 'awaiting_decision'

    asyncio.run(run())


def test_an_ok_verdict_for_another_version_does_not_unlock_this_one(tmp_path):
    """Duyệt `v1` không được nhờ phán quyết của `v2` — cổng hỏi đúng cặp (identity, version)."""
    store, runtime, sid = run_turn(tmp_path, [
        answer('Xin duyệt v1', calls=[call('request_approval', approval_args(version=1))]),
        answer('Tôi đi phản biện v1.')], seed=lambda s: seed_ok(s, 2))

    ends = tool_end_rows(store, sid)
    assert [row.get('errorCode') for row in ends] == ['PLAN_APPROVAL_UNVERIFIED'], ends
    assert 'v1' in ends[0]['error']
    assert runtime.pending == {}


def test_a_revise_verdict_is_not_a_pass(tmp_path):
    """`revise` là phán quyết THẬT nhưng không phải `ok`: cổng vẫn chặn (bản còn lỗi chưa sửa)."""
    store, runtime, sid = run_turn(tmp_path, [
        answer('Xin duyệt', calls=[call('request_approval', approval_args())]),
        answer('Tôi sửa trước.')], seed=lambda s: seed_ok(s, 1, verdict='revise'))

    ends = tool_end_rows(store, sid)
    assert [row.get('errorCode') for row in ends] == ['PLAN_APPROVAL_UNVERIFIED'], ends
    assert runtime.pending == {}


def test_warn_mode_records_the_approval_and_says_so(tmp_path, monkeypatch):
    """`warn`: đi tiếp nhưng phải NÓI RA — `notice` mang mã + dòng nhật ký hệ thống."""
    monkeypatch.setenv(limits.PLAN_VERIFY_ENV, 'warn')
    log = SystemLog(directory=tmp_path, source='harness', filename='harness.jsonl')
    monkeypatch.setattr(runtime_module, 'system_log', log)
    async def run():
        store, runtime, sid = await drive(tmp_path, [
            answer('Xin duyệt', calls=[call('request_approval', approval_args())])],
            wait_for_decision=True)
        codes = [row['code'] for row in events_of(store, sid, 'notice')]
        assert limits.PLAN_APPROVAL_UNVERIFIED_CODE in codes, codes
        assert runtime.pending_for(sid), 'warn không được chặn lượt chờ'

    asyncio.run(run())
    rows = log.read() or read_entries([log.previous_path()])
    marked = [row for row in rows if row.get('code') == limits.PLAN_APPROVAL_UNVERIFIED_CODE]
    assert len(marked) == 1, rows
    assert marked[0]['event'] == 'plan.approval.unverified'
    assert marked[0]['level'] == 'warn'


def test_off_mode_does_not_check_at_all(tmp_path, monkeypatch):
    """`off`: công tắc hạ xuống — không đo, không `notice`, lượt chờ chạy như trước vòng 25."""
    monkeypatch.setenv(limits.PLAN_VERIFY_ENV, 'off')
    async def run():
        store, runtime, sid = await drive(tmp_path, [
            answer('Xin duyệt', calls=[call('request_approval', approval_args())])],
            wait_for_decision=True)
        codes = [row['code'] for row in events_of(store, sid, 'notice')]
        assert limits.PLAN_APPROVAL_UNVERIFIED_CODE not in codes, codes
        assert runtime.pending_for(sid)
        assert store.get(sid)['status'] == 'awaiting_decision'

    asyncio.run(run())


def test_an_unknown_mode_falls_back_to_enforce_and_says_so(tmp_path, monkeypatch):
    """Giá trị lạ KHÔNG được hạ cấp cổng trong im lặng: rơi về `enforce` + một `notice` nói ra."""
    monkeypatch.setenv(limits.PLAN_VERIFY_ENV, 'lỏng-lẻo')
    store, runtime, sid = run_turn(tmp_path, [
        answer('Xin duyệt', calls=[call('request_approval', approval_args())]),
        answer('Vâng.')])

    notices = events_of(store, sid, 'notice')
    assert [row['code'] for row in notices] == [limits.PLAN_VERIFY_MODE_UNKNOWN_CODE]
    assert notices[0]['value'] == 'lỏng-lẻo'
    assert [row.get('errorCode') for row in tool_end_rows(store, sid)] == ['PLAN_APPROVAL_UNVERIFIED']
    assert runtime.pending == {}


def test_the_gate_reads_the_mode_missing_env_as_the_default(tmp_path):
    """Không đặt env ⇒ mặc định của hằng số (`enforce`) — cổng BẬT ngoài hộp."""
    store, runtime, sid = run_turn(tmp_path, [
        answer('Xin duyệt', calls=[call('request_approval', approval_args())]),
        answer('Vâng.')])
    assert [row.get('errorCode') for row in tool_end_rows(store, sid)] == ['PLAN_APPROVAL_UNVERIFIED']
    assert runtime.plan_verify_mode() == (limits.PLAN_VERIFY_DEFAULT_MODE, None)


def test_a_question_with_plan_keys_is_not_gated(tmp_path):
    """Cổng chỉ áp cho `request_approval`: câu hỏi (`ask_user`) không bị chặn vì mang cặp khoá plan."""
    async def run():
        store, runtime, sid = await drive(tmp_path, [
            answer('Hỏi trước khi duyệt', calls=[call('ask_user', {
                'question': 'Duyệt bản v1 này?', 'planIdentity': IDENTITY, 'planVersion': 1,
                'options': [{'id': 'go', 'label': 'Duyệt', 'kind': 'approve'},
                            {'id': 'wait', 'label': 'Chưa', 'kind': 'reject'}]})])],
            wait_for_decision=True)
        record = runtime.pending_for(sid)[0]
        assert record['kind'] == 'question'
        assert (record['planIdentity'], record['planVersion']) == (IDENTITY, 1)
        assert store.get(sid)['status'] == 'awaiting_decision'

    asyncio.run(run())


# --- Đường tab Plan: `POST /api/agent/plans/review` -----------------------------------------------

def test_the_plan_tab_cannot_approve_an_unverified_plan(tmp_path):
    """Bấm Duyệt cho bản chưa phản biện: 409, KHÔNG hàng sổ, KHÔNG chuyển tiếp box."""
    executor = FixtureExecutor(payload=fake_index())
    status, payload, rows = call_route(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                       {'identity': IDENTITY, 'version': 1, 'decision': 'approved'})

    assert status == 409, payload
    assert payload['blocked'] is True
    assert payload['code'] == limits.PLAN_APPROVAL_UNVERIFIED_CODE
    assert "role='plan-review'" in payload['reason'] and 'plan_verify' in payload['reason']
    assert 'plan_verify' in payload['remedy'] and 'verdict=ok' in payload['remedy']
    assert rows == [], 'cổng chặn TRƯỚC khi ghi sổ: bản chưa phản biện không được thành "đã duyệt"'
    assert [path for path, _ in executor.requests] == [plan_registry.INDEX_PATH], \
        'chỉ đọc chỉ mục; quyết định bị chặn thì không chuyển tiếp sang box'


def test_the_plan_tab_approves_once_the_verdict_is_ok(tmp_path):
    """Có phán quyết `ok` cho đúng bản: hàng duyệt vào sổ như trước, không có `blocked`."""
    executor = FixtureExecutor(payload=fake_index())
    status, payload, rows = call_route(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                       {'identity': IDENTITY, 'version': 1, 'decision': 'approved'},
                                       verified=1)

    assert status == 200, payload
    assert 'blocked' not in payload
    assert [row['decision'] for row in rows] == ['approved']
    assert rows[0]['source'] == 'plan-tab'
    assert payload['forwarded'] is True


def test_the_gate_asks_the_same_question_for_the_version_that_was_clicked(tmp_path):
    """Duyệt `v2` không được nhờ phán quyết `ok` của `v1`: cổng hỏi đúng cặp (identity, version)."""
    executor = FixtureExecutor(payload=fake_index(versions=((1, 4650, '2026-09-20T13:50:00Z'),
                                                            (2, 4900, '2026-09-21T09:00:00Z'))))
    status, payload, rows = call_route(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                       {'identity': IDENTITY, 'version': 2, 'decision': 'approved'},
                                       verified=1)

    assert status == 409, payload
    assert '@v2' in payload['reason']
    assert rows == []


def test_the_plan_tab_can_still_request_changes_on_an_unverified_plan(tmp_path):
    """Cổng chỉ khoá đường DUYỆT: yêu cầu sửa một bản chưa phản biện vẫn phải ghi được."""
    executor = FixtureExecutor(payload=fake_index())
    status, payload, rows = call_route(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                       {'identity': IDENTITY, 'version': 1,
                                        'decision': 'changes_requested', 'note': 'viết lại mốc 2'})

    assert status == 200, payload
    assert [row['decision'] for row in rows] == ['changes_requested']
    assert rows[0]['note'] == 'viết lại mốc 2'


def test_the_plan_tab_approves_in_warn_mode_with_a_visible_warning(tmp_path, monkeypatch):
    """`warn`: hàng duyệt vẫn được ghi, nhưng giao diện nhận `approvalWarning` để nói ra."""
    executor = FixtureExecutor(payload=fake_index())
    status, payload, rows = call_route(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                       {'identity': IDENTITY, 'version': 1, 'decision': 'approved'},
                                       monkeypatch=monkeypatch, mode='warn')

    assert status == 200, payload
    assert limits.PLAN_APPROVAL_UNVERIFIED_CODE in payload['approvalWarning']
    assert [row['decision'] for row in rows] == ['approved']


def test_the_plan_tab_approves_in_off_mode_without_the_gate(tmp_path, monkeypatch):
    """`off` — công tắc hạ xuống cho tab Plan: không 409, không cảnh báo."""
    executor = FixtureExecutor(payload=fake_index())
    status, payload, rows = call_route(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                       {'identity': IDENTITY, 'version': 1, 'decision': 'approved'},
                                       monkeypatch=monkeypatch, mode='off')

    assert status == 200, payload
    assert 'approvalWarning' not in payload
    assert [row['decision'] for row in rows] == ['approved']


def test_the_gate_mode_is_readable_from_runtime_info(tmp_path, monkeypatch):
    """DEV phải thấy được mức đang áp — cùng luật với `evidenceMode` (không chép tay con số nào)."""
    executor = FixtureExecutor(payload=fake_index())
    _, payload, _ = call_route(tmp_path, executor, 'GET', INFO_ROUTE)
    gate = payload['limits']['gate']
    assert gate['planVerifyMode'] == limits.PLAN_VERIFY_DEFAULT_MODE
    assert gate['planVerifyModes'] == list(limits.PLAN_VERIFY_MODES)
    assert gate['planSourcesMode'] == limits.PLAN_SOURCES_DEFAULT_MODE
    assert gate['planReviewMinAnswerChars'] == limits.PLAN_REVIEW_MIN_ANSWER_CHARS
    assert gate['planVerifyReviseMax'] == limits.PLAN_VERIFY_REVISE_MAX

    monkeypatch.setenv(limits.PLAN_VERIFY_ENV, 'off')
    monkeypatch.setenv(limits.PLAN_SOURCES_ENV, 'warn')
    _, payload, _ = call_route(tmp_path / 'second', executor, 'GET', INFO_ROUTE)
    gate = payload['limits']['gate']
    assert (gate['planVerifyMode'], gate['planSourcesMode']) == ('off', 'warn')
