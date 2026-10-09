"""Hai route plan của harness: `POST /api/agent/plans/review` + `GET /api/agent/plans/status`.

Đây là hợp đồng §4.1/§4.2 của plan vòng 20 nhìn từ phía giao diện, nên test gọi **route thật**
qua aiohttp (đúng thứ tab Plan gọi, không tham số nào), và kiểm ba ca mà plan đặt tên:

* một cú bấm của người dùng **vẫn** được ghi khi box đang tắt (`forwarded: false` + nhật ký
  `plan_review_forward_failed`) — quyết định không được biến mất vì hạ tầng;
* `reviewStale` bật khi số đo trên box đổi sau lúc duyệt, và bản duyệt đó không còn là đồng ý;
* duyệt `v1` không bao giờ làm `v2` thành `approved`.
"""
from __future__ import annotations

import asyncio
import json

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import plan_registry
from agentbox.api import server as api_server
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore
from agentbox.observability.system_log import SystemLog, read_entries

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
REVIEW_ROUTE = '/api/agent/plans/review'
STATUS_ROUTE = '/api/agent/plans/status'
IDENTITY = 'clinical-patient-record-lookup-research'


def plan_payload(*, versions=((3, 4650, '2026-09-20T13:50:00Z'),), identity=IDENTITY, slug=None):
    directory, tail = plan_registry.split_identity(identity)
    return {
        'plans': [{
            'identity': identity, 'relativeDirectory': directory, 'slug': slug or tail,
            'versions': [{'version': version, 'label': f'v{version}',
                          'relativePath': f'.plans/v{version}-{tail}.md', 'sizeBytes': size,
                          'modifiedAt': modified, 'status': 'draft', 'headerStatus': 'ok',
                          'headerVersion': version, 'headerIdentity': identity,
                          'declaredParent': None, 'declaredSlug': None}
                         for version, size, modified in versions],
        }],
        'ignoredCount': 0, 'warnings': [],
    }


class BoxExecutor:
    """Sandbox giả: `request()` là chỉ mục + đường chuyển tiếp duyệt, `execute()` không dùng."""

    def __init__(self, payload=None, index_error=None, forward_error=None):
        self.payload = payload
        self.index_error = index_error
        self.forward_error = forward_error
        self.requests = []

    async def request(self, path, body=None, session=None):
        self.requests.append((path, body))
        if path == plan_registry.INDEX_PATH:
            if self.index_error is not None:
                raise self.index_error
            return self.payload
        if self.forward_error is not None:
            raise self.forward_error
        return {'identity': (body or {}).get('identity'), 'decision': (body or {}).get('decision')}

    async def execute(self, name, args, sid):
        return {'content': 'not used by these routes'}

    async def cleanup(self, sid):
        return None


class QuietRouter:
    async def model_metadata_map(self):
        return {}


def make_runtime(tmp_path, executor):
    store = SessionStore(tmp_path / 'sessions.db')
    from agentbox.agent_core.runtime import HarnessRuntime
    return store, HarnessRuntime(store, executor, QuietRouter())


def call(tmp_path, executor, method, path, body=None, monkeypatch=None, log=None, verified=None):
    """Một request thật qua aiohttp; trả `(status, payload)` và store để kiểm hậu quả.

    `verified` = số version (hoặc tuple) đã có phán quyết `ok` **trước** request: vòng 25 đặt cổng
    "chưa phản biện thì không duyệt được" (`PLAN_APPROVAL_UNVERIFIED`) ở cả hai đường duyệt, nên
    các ca kiểm *sổ duyệt* phải nói rõ bản nào đã qua phản biện. Cổng này có bộ ca riêng
    (`test_plan_verify_gate.py`).
    """
    async def run():
        store, runtime = make_runtime(tmp_path, executor)
        for number in ([verified] if isinstance(verified, int) else list(verified or ())):
            store.record_plan_verification(IDENTITY, number, 'ok', issues=[], summary='đã phản biện',
                                           critic_session_id='critic-fixture', critic_answer_chars=500,
                                           critic_verdict='ok')
        if monkeypatch is not None and log is not None:
            monkeypatch.setattr(api_server, 'system_log', log)
            monkeypatch.setattr(plan_registry, 'system_log', log)
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
            # Đọc sổ duyệt TRƯỚC khi máy chủ đóng: `create_app` đóng store trong cleanup.
            rows = store.plan_reviews_for(IDENTITY)
        return status, payload, rows

    return asyncio.run(run())


def test_review_is_written_to_the_ledger_and_forwarded_to_the_box(tmp_path):
    executor = BoxExecutor(payload=plan_payload())
    status, payload, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                 {'identity': IDENTITY, 'version': 3,
                                  'decision': 'changes_requested', 'note': 'nêu rõ mục 3'})
    assert status == 200
    assert payload['forwarded'] is True
    assert payload['decision'] == 'changes_requested'
    assert [row['decision'] for row in rows] == ['changes_requested']
    assert rows[0]['source'] == 'plan-tab'
    assert rows[0]['note'] == 'nêu rõ mục 3'
    assert [path for path, _ in executor.requests] == [plan_registry.INDEX_PATH, '/__box/plans/review']
    forwarded = executor.requests[1][1]
    assert forwarded == {'identity': IDENTITY, 'version': 3, 'decision': 'changes_requested',
                         'note': 'nêu rõ mục 3'}


def test_review_stamps_the_box_measurement_so_staleness_can_be_detected(tmp_path):
    executor = BoxExecutor(payload=plan_payload(versions=((3, 4650, '2026-09-20T13:50:00Z'),)))
    _, _, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE,
                      {'identity': IDENTITY, 'version': 3, 'decision': 'approved'}, verified=3)
    assert rows[0]['content_size'] == 4650
    assert rows[0]['content_modified_at'] == '2026-09-20T13:50:00Z'


def test_a_decision_survives_a_dead_box(tmp_path, monkeypatch):
    """Box tắt: quyết định vẫn vào sổ, `forwarded: false`, và nhật ký nói đúng mã lỗi."""
    log = SystemLog(directory=tmp_path, source='harness', filename='harness.jsonl')
    executor = BoxExecutor(payload=plan_payload(), forward_error=RuntimeError('box down'))
    status, payload, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                 {'identity': IDENTITY, 'version': 3, 'decision': 'approved'},
                                 monkeypatch=monkeypatch, log=log, verified=3)
    assert status == 200 and payload['forwarded'] is False
    assert [row['decision'] for row in rows] == ['approved']
    # `create_app` gọi `rotate_on_shutdown()` khi máy chủ đóng, nên dòng vừa ghi nằm ở tệp
    # "previous" — đọc cả hai để test không phụ thuộc thứ tự tắt.
    entries = log.read() or read_entries([log.previous_path()])
    # Hai dòng, hai sự thật khác nhau: box tắt nên không chuyển tiếp được, và kế hoạch này chưa có
    # chủ sở hữu nào đã ghi (`plan_owners` trống) nên không có phiên nào để đánh thức (vòng 25).
    assert [entry['code'] for entry in entries if entry.get('code')] == ['PLAN_REVIEW_FORWARD_FAILED']


def test_a_dead_index_still_records_the_decision(tmp_path):
    executor = BoxExecutor(index_error=RuntimeError('box down'), forward_error=RuntimeError('box down'))
    status, payload, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE,
                                 {'identity': IDENTITY, 'version': 3, 'decision': 'approved'},
                                 verified=3)
    assert status == 200 and payload['forwarded'] is False
    assert len(rows) == 1
    assert rows[0]['content_size'] is None, 'không đo được thì để trống, không bịa số đo'


def test_review_validation(tmp_path):
    executor = BoxExecutor(payload=plan_payload())
    cases = [
        ({'version': 3, 'decision': 'approved'}, 'PLAN_IDENTITY_INVALID'),
        ({'identity': 'Login Page', 'version': 3, 'decision': 'approved'}, 'PLAN_IDENTITY_INVALID'),
        ({'identity': IDENTITY, 'version': 0, 'decision': 'approved'}, 'PLAN_REVIEW_INVALID'),
        ({'identity': IDENTITY, 'version': '3', 'decision': 'approved'}, 'PLAN_REVIEW_INVALID'),
        ({'identity': IDENTITY, 'version': 3, 'decision': 'maybe'}, 'PLAN_REVIEW_INVALID'),
        ({'identity': IDENTITY, 'version': 3, 'decision': 'approved', 'note': 7}, 'PLAN_REVIEW_INVALID'),
    ]
    for body, code in cases:
        status, payload, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE, body)
        assert status == 400, body
        assert payload['code'] == code, body
        assert rows == [], body
    assert executor.requests == [], 'yêu cầu sai không được chạm tới box'


def test_status_of_an_identity_absent_from_the_index_is_none(tmp_path):
    executor = BoxExecutor(payload=plan_payload(identity='other-topic'))
    status, payload, _ = call(tmp_path, executor, 'GET',
                              f'{STATUS_ROUTE}?identity={IDENTITY}')
    assert status == 200
    assert payload['state'] == 'none'
    assert payload['stateVersion'] is None
    assert payload['review'] is None and payload['evaluation'] is None


def test_status_needs_a_valid_identity(tmp_path):
    executor = BoxExecutor(payload=plan_payload())
    for query in ('', '?identity=', '?identity=Login%20Page'):
        status, payload, _ = call(tmp_path, executor, 'GET', STATUS_ROUTE + query)
        assert status == 400, query
        assert payload['code'] == 'PLAN_IDENTITY_INVALID'
    status, payload, _ = call(tmp_path, executor, 'GET', f'{STATUS_ROUTE}?identity={IDENTITY}&version=abc')
    assert status == 400 and payload['code'] == 'PLAN_STATUS_INVALID'


def test_status_reads_the_newest_version_and_reports_stale_approvals(tmp_path):
    executor = BoxExecutor(payload=plan_payload(versions=((3, 4650, '2026-09-20T13:50:00Z'),
                                                          (4, 4514, '2026-09-20T13:56:00Z'))))
    _, _, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE,
                      {'identity': IDENTITY, 'version': 4, 'decision': 'approved'}, verified=4)
    assert rows[0]['version'] == 4
    status, payload, _ = call(tmp_path, executor, 'GET', f'{STATUS_ROUTE}?identity={IDENTITY}')
    assert status == 200
    assert (payload['state'], payload['stateVersion']) == ('approved', 4)
    assert payload['reviewStale'] is False
    assert payload['indexAvailable'] is True
    # Box báo file đã đổi sau lúc duyệt: bản duyệt đó đã cũ, không còn là đồng ý.
    moved = BoxExecutor(payload=plan_payload(versions=((3, 4650, '2026-09-20T13:50:00Z'),
                                                       (4, 4600, '2026-09-20T14:02:00Z'))))
    _, payload, _ = call(tmp_path, moved, 'GET', f'{STATUS_ROUTE}?identity={IDENTITY}')
    assert payload['reviewStale'] is True


def test_approving_v1_does_not_approve_v2(tmp_path):
    executor = BoxExecutor(payload=plan_payload(versions=((1, 100, '2026-09-20T13:00:00Z'),
                                                          (2, 200, '2026-09-20T13:10:00Z'))))
    _, _, rows = call(tmp_path, executor, 'POST', REVIEW_ROUTE,
                      {'identity': IDENTITY, 'version': 1, 'decision': 'approved'}, verified=1)
    assert rows[0]['version'] == 1
    _, payload, _ = call(tmp_path, executor, 'GET', f'{STATUS_ROUTE}?identity={IDENTITY}')
    assert (payload['state'], payload['stateVersion']) == ('draft', 2)
    _, older, _ = call(tmp_path, executor, 'GET', f'{STATUS_ROUTE}?identity={IDENTITY}&version=1')
    assert (older['state'], older['stateVersion']) == ('approved', 1)


def test_status_reports_submitted_only_while_the_approval_is_live(tmp_path):
    executor = BoxExecutor(payload=plan_payload(versions=((3, 4650, '2026-09-20T13:50:00Z'),)))
    from agentbox.agent_core.runtime import HarnessRuntime
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, executor, QuietRouter())
    runtime.pending['abc'] = {'kind': 'approval', 'resolved': False, 'planIdentity': IDENTITY,
                              'planVersion': 3}

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                async with client.get(f'{STATUS_ROUTE}?identity={IDENTITY}', headers=HEADERS) as response:
                    live = await response.json()
                runtime.pending['abc']['resolved'] = True
                async with client.get(f'{STATUS_ROUTE}?identity={IDENTITY}', headers=HEADERS) as response:
                    settled = await response.json()
        return live, settled

    live, settled = asyncio.run(run())
    assert live['state'] == 'submitted'
    assert settled['state'] == 'draft'


def test_status_degrades_honestly_when_the_index_is_unreadable(tmp_path):
    executor = BoxExecutor(index_error=RuntimeError('box down'))
    status, payload, _ = call(tmp_path, executor, 'GET', f'{STATUS_ROUTE}?identity={IDENTITY}')
    assert status == 200
    assert payload['state'] == 'unknown'
    assert payload['indexAvailable'] is False


def test_status_returns_the_stored_evaluation_when_one_exists(tmp_path):
    executor = BoxExecutor(payload=plan_payload(versions=((3, 4650, '2026-09-20T13:50:00Z'),)))
    store, runtime = make_runtime(tmp_path, executor)
    store.record_plan_evaluation(IDENTITY, 3, {'total': 14, 'levels': {'P1': 2}}, 14, 'pass')

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                async with client.get(f'{STATUS_ROUTE}?identity={IDENTITY}', headers=HEADERS) as response:
                    return await response.json()

    payload = asyncio.run(run())
    assert payload['evaluation']['total'] == 14
    assert payload['evaluation']['verdict'] == 'pass'
    assert payload['evaluation']['payload']['levels'] == {'P1': 2}
    store.close()


# --- Vòng 25 (M5/M6): tab Plan đọc được mặt phản biện, và bấm là MỞ MỘT LƯỢT THẬT ------------------
# Đo vòng 25: 3/3 cú bấm trả 200, hàng sổ có, badge đổi — rồi im lặng 55-60 s, `turn_count` không
# đổi, 0 event. Nguyên nhân: route chỉ `record_plan_review` rồi chuyển tiếp box; không có sổ
# `identity → session_id` nên không ai biết phải đánh thức phiên nào.
class RecordingRouter:
    """Router giả: trả lời một câu kết thúc lượt và GIỮ LẠI prompt của từng lượt.

    Prompt là thứ chứng minh được "lượt mới nói đúng việc phải làm": nó là tin nhắn của lượt.
    """

    def __init__(self):
        self.prompts = []

    async def model_metadata_map(self):
        return {}

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.prompts.append('\n'.join(str(message.get('content') or '') for message in messages))
        return {'choices': [{'message': {'content': 'Rõ, tôi thi công.'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 5, 'completion_tokens': 2}}


def plan_tab_click(tmp_path, body, *, versions=((3, 4650, '2026-09-20T13:50:00Z'),), owned=True,
                   paused=False, clicks=1, log=None, monkeypatch=None, verified=None):
    """Một (hoặc nhiều) cú bấm ở tab Plan qua aiohttp THẬT, trên runtime đã chuẩn bị sẵn.

    Trả về SỐ ĐO đã chụp TRONG loop (`create_app` đóng store khi máy chủ tắt, nên mọi thứ phải đọc
    trước đó): `{'status', 'payload', 'rows', 'turn_count', 'userRows', 'prompts', 'owner', 'again'}`.
    """
    from agentbox.agent_core.runtime import HarnessRuntime

    if monkeypatch is not None and log is not None:
        monkeypatch.setattr(api_server, 'system_log', log)
        monkeypatch.setattr(plan_registry, 'system_log', log)

    async def run():
        executor = BoxExecutor(payload=plan_payload(versions=versions))
        router = RecordingRouter()
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, executor, router)
        owner = runtime.create({'skills': []})['id']
        await asyncio.wait_for(runtime.start(owner, 'Lượt đầu của phiên gốc'), 5)
        if owned:
            directory, tail = plan_registry.split_identity(IDENTITY)
            store.record_plan_owner(IDENTITY, owner, slug=tail,
                                    relative_path=f'.plans/v{versions[-1][0]}-{tail}.md',
                                    version=versions[-1][0])
        for number in ([verified] if isinstance(verified, int) else list(verified or ())):
            # Cổng D-34 chặn đường DUYỆT khi bản chưa có phán quyết `ok`: ca duyệt phải nói rõ
            # bản nào đã qua phản biện, còn ca yêu cầu sửa thì không cần (và bài T4 kiểm đúng cổng đó).
            store.record_plan_verification(IDENTITY, number, 'ok', issues=[], summary='đã phản biện',
                                           critic_session_id='critic-fixture', critic_answer_chars=500,
                                           critic_verdict='ok')
        if paused:
            # Phiên ĐANG chạy: đúng trạng thái mà `submit` từ chối bằng `SESSION_BUSY`.
            store.save(owner, store.get(owner)['messages'], 'running')
        before = store.get(owner)['turn_count']
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                answers = []
                for _ in range(clicks):
                    async with client.post(REVIEW_ROUTE, headers=HEADERS, json=body) as response:
                        text = await response.text()
                        try:
                            answers.append((response.status, json.loads(text)))
                        except ValueError:
                            answers.append((response.status, text))
            # Máy chủ còn sống thì store còn mở — mọi số đo phải chụp ở ĐÂY.
            task = runtime.tasks.get(owner)
            if task is not None:
                try:
                    await asyncio.wait_for(asyncio.shield(task), 5)
                except Exception:  # pragma: no cover - điều được kiểm là lượt CÓ mở ra
                    pass
            return {'status': answers[0][0], 'payload': answers[0][1],
                    'again': answers[1][1] if len(answers) > 1 else None,
                    'rows': store.plan_reviews_for(IDENTITY), 'owner': owner,
                    'turnCount': store.get(owner)['turn_count'], 'before': before,
                    'userRows': [event['data'] for event in store.events(owner)
                                 if event['type'] == 'user'],
                    'prompts': list(router.prompts)}

    return asyncio.run(run())


def tab_prompt(seen):
    return [row['text'] for row in seen['userRows'] if str(row['text']).startswith('[Tab Plan]')]


def test_status_reports_the_verification_and_the_owning_session(tmp_path):
    """`GET /plans/status` LUÔN có `verification` + `ownership`: giao diện phân biệt được
    "chưa ai phản biện" (`state: 'none'`) với "harness cũ, thiếu trường"."""
    executor = BoxExecutor(payload=plan_payload(versions=((1, 4650, '2026-09-20T13:50:00Z'),)))
    status, payload, _rows = call(tmp_path, executor, 'GET',
                                  f'{STATUS_ROUTE}?identity={IDENTITY}&version=1')
    assert status == 200
    assert payload['verification'] == {'state': 'none', 'at': None, 'criticSessionId': None, 'issues': []}
    assert payload['ownership'] == {'sessionId': None}


def test_status_reports_a_live_verdict_with_the_issue_list_intact(tmp_path):
    """Có hàng phán quyết: `state` + `at` ISO UTC (`…Z`) + `issues` nguyên vẹn cho giao diện."""
    executor = BoxExecutor(payload=plan_payload(versions=((1, 4650, '2026-09-20T13:50:00Z'),)))
    store, runtime = make_runtime(tmp_path, executor)
    # `fix` thiếu được sổ chuẩn hoá thành chuỗi rỗng (giao diện không phải tự đoán), nên hàng gieo
    # sẵn ở đây ghi đúng khuôn mà `plan_verify` ghi ra.
    issues = [{'severity': 'high', 'text': 'mốc 2 không kiểm được', 'fix': 'thay lệnh'},
              {'severity': 'low', 'text': 'thiếu mục Sources', 'fix': ''}]
    store.record_plan_verification(IDENTITY, 1, 'revise', issues=issues, summary='một lỗi nặng',
                                   critic_session_id='critic-sess', critic_answer_chars=512,
                                   critic_verdict='revise')
    store.record_plan_owner(IDENTITY, 'owner-sess', slug='clinical-patient-record-lookup-research')

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                async with client.get(f'{STATUS_ROUTE}?identity={IDENTITY}&version=1',
                                      headers=HEADERS) as response:
                    return await response.json()

    payload = asyncio.run(run())
    assert payload['verification']['state'] == 'revise'
    assert payload['verification']['criticSessionId'] == 'critic-sess'
    assert payload['verification']['issues'] == issues
    assert payload['verification']['at'].endswith('Z') and 'T' in payload['verification']['at']
    assert payload['ownership'] == {'sessionId': 'owner-sess'}


def test_status_carries_the_gate_switches_so_the_tab_can_match_the_harness(tmp_path, monkeypatch):
    """`gate` LUÔN có mặt, và nói đúng công tắc ĐANG chạy — giao diện không phải tự đoán.

    Tab Plan phải siết đúng bằng harness: khoá nút Duyệt khi bản đang chọn có phán quyết `revise`
    trong chế độ `enforce`, nhưng KHÔNG khoá khi công tắc đã hạ xuống `warn`/`off`. Giá trị env lạ
    bị hạ về mặc định KÈM cờ `*Unknown` (hạ cấp cổng trong im lặng là thứ kế hoạch cấm).
    """
    executor = BoxExecutor(payload=plan_payload(versions=((1, 4650, '2026-09-20T13:50:00Z'),)))
    monkeypatch.delenv('BOXFOX_PLAN_VERIFY', raising=False)
    monkeypatch.delenv('BOXFOX_PLAN_SOURCES_GATE', raising=False)
    status, payload, _rows = call(tmp_path, executor, 'GET',
                                  f'{STATUS_ROUTE}?identity={IDENTITY}&version=1')
    assert status == 200
    assert payload['gate'] == {'verifyMode': 'enforce', 'verifyUnknown': None,
                               'sourcesMode': 'enforce', 'sourcesUnknown': None}

    monkeypatch.setenv('BOXFOX_PLAN_VERIFY', 'warn')
    monkeypatch.setenv('BOXFOX_PLAN_SOURCES_GATE', 'nonsense')
    status, payload, _rows = call(tmp_path, executor, 'GET',
                                  f'{STATUS_ROUTE}?identity={IDENTITY}&version=1')
    assert status == 200
    assert payload['gate']['verifyMode'] == 'warn'
    assert payload['gate']['verifyUnknown'] is None
    assert payload['gate']['sourcesMode'] == 'enforce'
    assert payload['gate']['sourcesUnknown'] == 'nonsense'


def test_status_of_a_version_that_does_not_exist_still_carries_both_faces(tmp_path):
    """Bản bị xoá (hoặc gõ sai số): vẫn HAI khoá với `state: 'none'`, không phải một payload thiếu."""
    executor = BoxExecutor(payload=plan_payload(versions=((1, 4650, '2026-09-20T13:50:00Z'),)))
    status, payload, _rows = call(tmp_path, executor, 'GET',
                                  f'{STATUS_ROUTE}?identity={IDENTITY}&version=9')
    assert status == 200
    assert payload['version'] == 9
    assert payload['verification']['state'] == 'none'
    assert payload['ownership'] == {'sessionId': None}


def test_a_change_request_from_the_plan_tab_opens_a_real_turn(tmp_path):
    """Cú bấm `changes_requested` mở MỘT lượt thật: `turn_count` +1, hàng `user` mới `[Tab Plan]`."""
    seen = plan_tab_click(tmp_path, {'identity': IDENTITY, 'version': 3,
                                     'decision': 'changes_requested', 'note': 'nêu rõ mục 3'})

    assert seen['status'] == 200 and seen['payload']['recorded'] is True
    assert seen['payload']['resumed'] is True, seen['payload']
    assert seen['payload']['turnId'] == f"{seen['owner']}#{seen['before'] + 1}", \
        'turnId phải trỏ ĐÚNG lượt vừa mở'
    assert seen['payload']['wake'] == {'state': 'opened', 'sessionId': seen['owner']}
    assert seen['turnCount'] == seen['before'] + 1

    opened = tab_prompt(seen)
    assert len(opened) == 1, seen['userRows']
    assert IDENTITY in opened[0] and 'v3' in opened[0] and 'nêu rõ mục 3' in opened[0]
    assert "role='plan-review'" in opened[0] and 'plan_verify' in opened[0]
    assert seen['prompts'] and 'nêu rõ mục 3' in seen['prompts'][-1]
    # Quyết định đã vào sổ TRƯỚC khi đánh thức, và hàng đó biết nó đã mở được lượt.
    row = seen['rows'][-1]
    assert row['decision'] == 'changes_requested' and row['resumed'] == 1
    assert row['session_id'] == seen['owner']


def test_an_approval_from_the_plan_tab_only_records_acceptance(tmp_path):
    seen = plan_tab_click(tmp_path, {'identity': IDENTITY, 'version': 3, 'decision': 'approved',
                                   'note': 'chỉ sửa backend'}, verified=3)
    assert seen['status'] == 200 and seen['payload']['resumed'] is False
    assert seen['payload']['wake']['state'] == 'accepted'
    assert tab_prompt(seen) == [] and seen['turnCount'] == seen['before']
    assert seen['rows'][-1]['resumed'] == 0 and seen['rows'][-1]['note'] == 'chỉ sửa backend'


def test_an_approval_without_note_does_not_start_a_turn(tmp_path):
    seen = plan_tab_click(tmp_path, {'identity': IDENTITY, 'version': 3, 'decision': 'approved'}, verified=3)
    assert seen['status'] == 200 and seen['payload']['resumed'] is False
    assert tab_prompt(seen) == [] and seen['rows'][-1]['note'] == ''


def test_a_busy_session_records_the_decision_and_says_the_turn_was_not_opened(tmp_path):
    """Phiên đang chạy: sổ VẪN ghi, `resumed: false` + `wake.state='busy'` — không im lặng, không mất."""
    seen = plan_tab_click(tmp_path, {'identity': IDENTITY, 'version': 3,
                                     'decision': 'changes_requested', 'note': 'sửa mốc 2'},
                          paused=True)

    assert seen['status'] == 200
    assert seen['payload']['recorded'] is True and seen['payload']['resumed'] is False
    assert seen['payload']['wake']['state'] == 'busy'
    assert seen['payload']['wake']['code'] == 'PLAN_WAKE_BUSY'
    assert 'đang chạy một lượt' in seen['payload']['wake']['message']
    assert seen['turnCount'] == seen['before'], 'không mở thêm lượt nào'
    assert 'turnId' not in seen['payload']
    assert seen['rows'][-1]['decision'] == 'changes_requested', 'quyết định của chủ nhà không được mất'
    assert tab_prompt(seen) == []


def test_a_decision_without_a_known_owner_records_and_says_so(tmp_path, monkeypatch):
    """Chưa biết phiên sở hữu: hàng sổ vẫn có, `wake.state='missing'` + nhật ký `plan.review.wake_failed`."""
    log = SystemLog(directory=tmp_path, source='harness', filename='harness.jsonl')
    seen = plan_tab_click(tmp_path, {'identity': IDENTITY, 'version': 3,
                                     'decision': 'changes_requested', 'note': 'sửa mốc 2'},
                          owned=False, log=log, monkeypatch=monkeypatch)

    assert seen['status'] == 200
    assert seen['payload']['recorded'] is True and seen['payload']['resumed'] is False
    assert seen['payload']['wake']['state'] == 'missing'
    assert seen['payload']['wake']['code'] == 'PLAN_WAKE_NO_OWNER'
    assert 'turnId' not in seen['payload']
    assert seen['rows'][-1]['decision'] == 'changes_requested'
    rows = log.read() or read_entries([log.previous_path()])
    assert 'plan.review.wake_failed' in [row['event'] for row in rows]


def test_a_second_click_with_the_same_decision_does_not_open_a_second_turn(tmp_path):
    """Bấm trùng (double-click, hoặc bấm lại sau khi mạng chớp): không mở lượt thứ hai."""
    seen = plan_tab_click(tmp_path, {'identity': IDENTITY, 'version': 3,
                                     'decision': 'changes_requested', 'note': 'nêu rõ mục 3'},
                          clicks=2)

    assert seen['payload']['turnId'] == seen['again']['turnId'], 'cú bấm trùng trả lại chính lượt đã mở'
    assert seen['turnCount'] == seen['before'] + 1
    assert len(tab_prompt(seen)) == 1
