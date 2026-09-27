"""Quyền của chủ nhà trên một run: sửa thẻ phạm vi (`scope`) và xin đào sâu (`deepen`) — §5.12.

Hai đường được kiểm ở ĐÚNG chỗ chúng gặp nhau: hàm runtime (`scope_update`, `deepen`) và tuyến HTTP
`PATCH /api/agent/research/jobs/{id}` dựng qua `create_app` với một runtime tối thiểu — chính là
tuyến mà giao diện P4 gọi.
"""
from __future__ import annotations

import asyncio
import types

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import research_runtime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FakeRuntime:
    """Runtime đủ dùng cho hai tuyến: `store` thật + vòng đời của ứng dụng aiohttp."""

    def __init__(self, store):
        self.store = store
        self.tasks: dict = {}
        self.search_db_path = None

    async def heal_context_windows(self):
        return None


def a_session(store):
    """Một phiên làm chủ; mọi run trong cùng bài dùng CHUNG phiên (một job không đổi chủ được)."""
    return store.create({'skills': []})['id']


def scope_job(store, sid=None, *, research_id='RS1', revision=1, status='researching',
              velocity='fast'):
    sid = sid or a_session(store)
    scope = {'revision': revision, 'goal': {'text': 'mục tiêu', 'status': 'confirmed'},
             'timePolicy': {'velocity': velocity, 'status': 'confirmed'},
             'questions': [], 'exclude': [], 'openQuestions': [],
             'budget': {'proposedSeconds': 1800, 'hardCeilingSeconds': 7200}}
    return store.research_job_save(research_id, sid,
                                   {'goal': 'mục tiêu', 'phase': 'planning', 'scope': scope},
                                   status=status)


# --- hàm runtime ------------------------------------------------------------

def test_scope_update_merges_the_patch_and_bumps_the_revision(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    answer = research_runtime.scope_update(object_with_store(store), job['session_id'], job,
                                          {'revision': 1, 'scope': {'goal': {'text': 'mục tiêu mới',
                                                                            'status': 'confirmed'},
                                                                    'questions': ['câu 1', 'câu 2'],
                                                                    'depth': 'deep',
                                                                    'budget': {'proposedSeconds': 900}}})
    assert answer['revision'] == 2
    scope = answer['scope']
    assert scope['goal']['text'] == 'mục tiêu mới'
    assert scope['depth'] == 'deep'
    assert len(scope['questions']) == 2
    assert scope['budget']['proposedSeconds'] == 900
    assert scope['budget']['hardCeilingSeconds'] == 7200  # ghép, không ghi đè cả cục
    assert scope['surveyDate'] and scope['window']['days'] > 0
    saved = store.research_job('RS1')
    assert saved['state']['scope']['revision'] == 2
    assert saved['state']['phaseHistory'][-1]['reason'] == 'scope-edited'


def test_scope_update_refuses_a_stale_revision_and_a_cancelled_run(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store, revision=3)
    with pytest.raises(ValueError) as error:
        research_runtime.scope_update(object_with_store(store), job['session_id'], job,
                                      {'revision': 1, 'scope': {'depth': 'deep'}})
    assert str(error.value).startswith('RESEARCH_SCOPE_REVISION_STALE')
    cancelled = scope_job(store, job['session_id'], research_id='RS2', status='cancelled')
    with pytest.raises(ValueError) as error:
        research_runtime.scope_update(object_with_store(store), cancelled['session_id'], cancelled,
                                      {'scope': {'depth': 'deep'}})
    assert 'RESEARCH_SCOPE_JOB_CANCELLED' in str(error.value)


def test_scope_update_rejects_an_empty_patch_and_a_job_without_a_scope(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    with pytest.raises(ValueError) as error:
        research_runtime.scope_update(object_with_store(store), job['session_id'], job,
                                      {'revision': 1, 'scope': {}})
    assert 'RESEARCH_SCOPE_PATCH_REQUIRED' in str(error.value)
    bare = store.research_job_save('RS3', job['session_id'], {'goal': 'không có thẻ'},
                                   status='researching')
    with pytest.raises(ValueError) as error:
        research_runtime.scope_update(object_with_store(store), job['session_id'], bare, {'scope': {'depth': 'x'}})
    assert 'RESEARCH_SCOPE_MISSING' in str(error.value)


def test_a_wrong_velocity_keeps_the_old_window_and_only_leaves_a_note(tmp_path):
    """§7.3: người dùng gõ bừa `velocity` thì KHÔNG mất cửa sổ cũ, và không có lỗi nào ném ra."""
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store, velocity='fast')
    answer = research_runtime.scope_update(object_with_store(store), job['session_id'], job,
                                          {'revision': 1, 'scope': {'timePolicy': {'velocity': 'nhanh-lam'}}})
    policy = answer['scope']['timePolicy']
    assert policy['velocity'] == 'fast'          # giữ nguyên giá trị cũ
    assert 'không thuộc' in policy['note']       # và NÓI vì sao cửa sổ không đổi
    from agentbox.agent_core import research_evidence
    expected = research_evidence.window_bounds('fast', as_of=answer['surveyDate'])
    assert answer['window'] == expected and expected['days'] > 0


def test_deepen_queues_a_request_and_raises_the_facet(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    key = store.facet_save('RS1', {'label': 'Hướng A', 'priority': 'low', 'status': 'searched'})['facetId']
    answer = research_runtime.deepen(object_with_store(store), job['session_id'], job,
                                    {'facetId': key, 'note': 'đọc kỹ hơn phần số liệu'})
    assert answer['facetId'] == key and answer['requests'] == 1
    assert answer['facet']['priority'] == 'high'
    assert 'đọc kỹ hơn phần số liệu' in answer['facet']['note']
    again = research_runtime.deepen(object_with_store(store), job['session_id'],
                                   store.research_job('RS1'), {'facetId': key, 'note': 'thêm'})
    assert again['requests'] == 2
    assert again['facet']['note'].endswith('thêm')
    saved = store.research_job('RS1')
    assert len(saved['state']['deepenRequests']) == 2


def test_deepen_needs_a_target_and_an_existing_facet(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    with pytest.raises(ValueError) as error:
        research_runtime.deepen(object_with_store(store), job['session_id'], job, {'note': 'x'})
    assert 'RESEARCH_DEEPEN_TARGET_REQUIRED' in str(error.value)
    with pytest.raises(ValueError) as error:
        research_runtime.deepen(object_with_store(store), job['session_id'], job, {'facetId': 'f-không-có'})
    assert 'RESEARCH_FACET_UNKNOWN' in str(error.value)


# --- bằng chứng theo run (bảng 4.8) ------------------------------------------

def test_the_job_endpoints_return_evidence_rows_of_this_run_only(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    sid = job['session_id']
    mine = store.source_add(sid, {'claim': 'Nhận định của run', 'url': 'https://a.example/x',
                                  'host': 'a.example', 'tier': 1, 'excerpt': 'x' * 120,
                                  'published_at': '2026-03-02', 'access_level': 'fulltext-read',
                                  'origin_cluster': 'a.example', 'research_id': 'RS1'})
    link = store.evidence_link(sid, mine['rowId'], 'Nhận định của run',
                               access_level='fulltext-read', research_id='RS1')
    store.evidence_assess(sid, link['passageId'], link['claimId'], 'reviewer-1', 'hash-1',
                          'contradicts', 'số liệu ngược chiều')
    store.source_add(sid, {'claim': 'Nhận định của run khác', 'url': 'https://b.example/y',
                           'host': 'b.example', 'tier': 2, 'excerpt': 'y' * 120,
                           'research_id': 'RS2'})

    async def flow():
        server = TestServer(create_app(FakeRuntime(store)))
        await server.start_server()
        try:
            async with ClientSession() as http:
                for url in (server.make_url(f'/api/agent/research/jobs?sessionId={sid}'),
                            server.make_url('/api/agent/research/jobs/RS1')):
                    answer = await (await http.get(url, headers=HEADERS)).json()
                    rows = answer['jobs'][0]['evidence'] if 'jobs' in answer \
                        else answer['evidence']
                    assert [row['claim'] for row in rows] == ['Nhận định của run']
                    assert rows[0]['accessLevel'] == 'fulltext-read'
                    assert rows[0]['publishedAt'] == '2026-03-02'
                    assert rows[0]['originCluster'] == 'a.example'
                    assert rows[0]['relation'] == 'contradicts'
                    assert rows[0]['confidence'] == 'unknown'
        finally:
            await server.close()

    asyncio.run(flow())


def test_evidence_rows_are_newest_first_and_capped(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    sid = job['session_id']
    for index in range(4):
        added = store.source_add(sid, {'claim': f'Nhận định {index}',
                                       'url': f'https://a.example/{index}', 'host': 'a.example',
                                       'tier': 1, 'excerpt': 'x' * 120, 'research_id': 'RS1'})
        store.evidence_link(sid, added['rowId'], f'Nhận định {index}', research_id='RS1')
    rows = research_runtime.evidence_rows(object_with_store(store), sid, 'RS1', limit=3)
    assert [row['claim'] for row in rows] == ['Nhận định 3', 'Nhận định 2', 'Nhận định 1']
    assert research_runtime.evidence_rows(object_with_store(store), sid, 'RS-none', limit=5) == []


# --- tuyến HTTP mà giao diện gọi -------------------------------------------

def test_the_job_endpoints_accept_scope_and_deepen_and_return_coverage(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    store.facet_save('RS1', {'label': 'Hướng A', 'status': 'searched'})
    runtime = FakeRuntime(store)

    async def flow():
        app = create_app(runtime)
        server = TestServer(app)
        await server.start_server()
        try:
            async with ClientSession() as http:
                base = server.make_url(f'/api/agent/research/jobs/{job["research_id"]}')
                listed = await http.get(server.make_url(
                    f'/api/agent/research/jobs?sessionId={job["session_id"]}'), headers=HEADERS)
                assert listed.status == 200
                payload = await listed.json()
                assert payload['jobs'][0]['coverage']['counts']['total'] == 1
                assert [item['label'] for item in payload['jobs'][0]['facets']] == ['Hướng A']

                detail = await (await http.get(base, headers=HEADERS)).json()
                assert detail['job']['coverage']['counts']['total'] == 1
                assert detail['job']['facets'][0]['status'] == 'searched'

                stale = await http.patch(base, headers=HEADERS,
                                         json={'action': 'scope', 'revision': 99,
                                               'scope': {'depth': 'deep'}})
                assert stale.status == 409
                assert (await stale.json())['code'] == 'RESEARCH_SCOPE_REVISION_STALE'

                edited = await http.patch(base, headers=HEADERS,
                                          json={'action': 'scope', 'revision': 1,
                                                'scope': {'depth': 'deep'}})
                assert edited.status == 200
                body = await edited.json()
                assert body['revision'] == 2 and body['scope']['depth'] == 'deep'

                unknown = await http.patch(base, headers=HEADERS,
                                           json={'action': 'deepen', 'facetId': 'f-không-có'})
                assert unknown.status == 404
                assert (await unknown.json())['code'] == 'RESEARCH_FACET_UNKNOWN'

                deeper = await http.patch(base, headers=HEADERS,
                                          json={'action': 'deepen',
                                                'facetId': detail['job']['facets'][0]['facetId'],
                                                'note': 'sâu hơn'})
                assert deeper.status == 200
                assert (await deeper.json())['facet']['priority'] == 'high'

                invalid = await http.patch(base, headers=HEADERS, json={'action': 'nhảy múa'})
                assert invalid.status == 400
                assert (await invalid.json())['code'] == 'RESEARCH_ACTION_INVALID'
        finally:
            await server.close()

    asyncio.run(flow())


def test_the_scope_event_reaches_the_session_stream(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    research_runtime.scope_update(object_with_store(store), job['session_id'], job,
                                  {'revision': 1, 'scope': {'depth': 'deep'}})
    events = [row for row in store.events(job['session_id']) if row.get('type') == 'research_scope']
    assert events and events[-1]['data']['revision'] == 2
    assert events[-1]['data']['researchId'] == 'RS1'


def object_with_store(store):
    """Runtime tối thiểu cho hàm runtime: chỉ `store` là được đọc."""
    return types.SimpleNamespace(store=store, search_db_path=None)


# --- hợp đồng lỗi của tuyến (đợt soát `ed485f3`, finding 2/6/7/8) -------------

def test_the_scope_lock_answers_a_contract_code_for_a_non_integer_revision(tmp_path):
    """`revision` không phải số ⇒ `RESEARCH_SCOPE_REVISION_INVALID`, KHÔNG phải thông báo của Python."""
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)

    async def flow():
        server = TestServer(create_app(FakeRuntime(store)))
        await server.start_server()
        try:
            async with ClientSession() as http:
                base = server.make_url('/api/agent/research/jobs/RS1')
                for revision in ({}, 'banana'):
                    answer = await http.patch(base, headers=HEADERS,
                                              json={'action': 'scope', 'revision': revision,
                                                    'scope': {'depth': 'deep'}})
                    assert answer.status == 400
                    body = await answer.json()
                    assert body['code'] == 'RESEARCH_SCOPE_REVISION_INVALID'
                    assert 'int()' not in body['error'] and 'invalid literal' not in body['error']
                    assert body['error'].count('RESEARCH_SCOPE_REVISION_INVALID') == 1
        finally:
            await server.close()

    asyncio.run(flow())


def test_a_stale_job_revision_answers_409_without_a_doubled_code(tmp_path):
    """Khoá lạc quan của VIỆC cũng là 409, và chi tiết không lặp lại mã lỗi."""
    store = SessionStore(tmp_path / 'sessions.sqlite')
    scope_job(store)

    async def flow():
        server = TestServer(create_app(FakeRuntime(store)))
        await server.start_server()
        try:
            async with ClientSession() as http:
                answer = await http.patch(server.make_url('/api/agent/research/jobs/RS1'),
                                          headers=HEADERS,
                                          json={'action': 'budget', 'revision': 99,
                                                'budgetSeconds': 600})
                assert answer.status == 409
                body = await answer.json()
                assert body['code'] == 'RESEARCH_JOB_REVISION_CONFLICT'
                assert body['error'] == 'RESEARCH_JOB_REVISION_CONFLICT'
        finally:
            await server.close()

    asyncio.run(flow())


def test_the_answers_route_names_the_code_once_when_the_scope_moved(tmp_path):
    """D-7 (vòng kiểm thử P2–P5): tuyến trả lời từng ghép mã lỗi HAI lần trong `error`.

    Handler truyền nguyên `text` (đã có mã) vào `message`, rồi middleware ghép `code: message` — người
    dùng đọc thấy `RESEARCH_SCOPE_REVISION_STALE: RESEARCH_SCOPE_REVISION_STALE: …`. Anh em cùng tệp
    đi qua `_action_error`, nên chỉ mã MỘT lần.
    """
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    state = dict(job['state'])
    state['prompts'] = [{'promptId': 'rp-1', 'researchId': 'RS1', 'kind': 'interview', 'revision': 1,
                         'status': 'open', 'blocking': True, 'createdAt': 'x', 'actions': ['start'],
                         'questions': [{'id': 'iq1', 'text': 'Dùng để làm gì?', 'blocking': True,
                                        'required': True, 'allowFreeText': True,
                                        'options': [{'id': 'o1', 'label': 'Dùng ngay'}]}]}]
    state['scope'] = {**state['scope'], 'revision': 2, 'openQuestions': [
        {'id': 'iq1', 'text': 'Dùng để làm gì?', 'blocking': True, 'answer': None,
         'promptId': 'rp-1', 'options': [{'id': 'o1', 'label': 'Dùng ngay'}]}]}
    store.research_job_save('RS1', job['session_id'], state, status='needs_user')

    async def flow():
        server = TestServer(create_app(FakeRuntime(store)))
        await server.start_server()
        try:
            async with ClientSession() as http:
                answer = await http.post(server.make_url('/api/agent/research/prompts/rp-1/answer'),
                                         headers=HEADERS,
                                         json={'revision': 1, 'start': True,
                                               'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
                assert answer.status == 409
                body = await answer.json()
                assert body['code'] == 'RESEARCH_SCOPE_REVISION_STALE'
                assert body['error'].count('RESEARCH_SCOPE_REVISION_STALE') == 1
                assert 'phạm vi đã đổi' in body['error']
        finally:
            await server.close()

    asyncio.run(flow())


def test_two_owner_scope_edits_leave_two_history_rows(tmp_path):
    """Sửa thẻ hai lần ⇒ hai hàng `phaseHistory` (finding 7), không bị luật chống trùng nuốt."""
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)
    runtime = object_with_store(store)
    research_runtime.scope_update(runtime, job['session_id'], store.research_job('RS1'),
                                  {'revision': 1, 'scope': {'depth': 'deep'}})
    research_runtime.scope_update(runtime, job['session_id'], store.research_job('RS1'),
                                  {'revision': 2, 'scope': {'depth': 'standard'}})
    history = store.research_job('RS1')['state']['phaseHistory']
    assert [row['reason'] for row in history] == ['scope-edited', 'scope-edited']


def test_deepen_refuses_an_unknown_question_and_queues_nothing(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    job = scope_job(store)

    async def flow():
        server = TestServer(create_app(FakeRuntime(store)))
        await server.start_server()
        try:
            async with ClientSession() as http:
                answer = await http.patch(server.make_url('/api/agent/research/jobs/RS1'),
                                          headers=HEADERS,
                                          json={'action': 'deepen', 'questionId': 'q-không-có',
                                                'note': 'x'})
                assert answer.status == 404
                body = await answer.json()
                assert body['code'] == 'RESEARCH_QUESTION_UNKNOWN'
                assert body['error'].count('RESEARCH_QUESTION_UNKNOWN') == 1
        finally:
            await server.close()

    assert store.research_job('RS1')['state'].get('deepenRequests') in (None, [])


def test_reading_coverage_never_creates_the_search_database(tmp_path):
    """`write=False` (tuyến danh sách/chi tiết) không được sinh cơ sở dữ liệu tìm kiếm."""
    store = SessionStore(tmp_path / 'sessions.sqlite')
    scope_job(store)
    missing = tmp_path / 'chưa-có.db'
    runtime = types.SimpleNamespace(store=store, search_db_path=str(missing))
    coverage = research_runtime.coverage_refresh(runtime, 'RS1', write=False)
    assert coverage  # công tắc đang bật ở mặc định
    assert not missing.exists()

def test_resuming_a_closed_run_moves_its_phase_off_done_and_keeps_a_paused_one(tmp_path):
    """`partial` là pha ĐÓNG: `resume` mở LẠI run nên pha phải rời `done` — nhưng không bịa bước.

    Đo sống 2026-09-26: run `co-hoi-nao-con-trong` ghi `partial` và pha kẹt ở `planning`; sau khi B1
    đóng pha ở `done`, một lần chủ nhà bấm resume mà pha vẫn `done` thì luật "done là cuối" (C1) chặn
    mọi bước tiến pha sau đó, còn thanh tiến trình thì nói "xong" cho một run vừa được hồi sức. Mặt
    kia cũng phải đúng: run `paused` giữ nguyên pha THẬT của nó lúc bị tạm dừng.
    """
    store = SessionStore(tmp_path / 'sessions.sqlite')
    sid = a_session(store)
    closed = store.research_job_save('RS1', sid, {
        'goal': 'mục tiêu', 'phase': 'done',
        'phaseHistory': [{'phase': 'done', 'reason': 'job-partial'}]}, status='partial')
    store.research_job_save('RS2', sid, {
        'goal': 'mục tiêu', 'phase': 'verifying',
        'phaseHistory': [{'phase': 'verifying', 'reason': 'research-verify-evidence'}]}, status='paused')
    runtime = FakeRuntime(store)

    async def flow():
        app = create_app(runtime)
        server = TestServer(app)
        await server.start_server()
        try:
            async with ClientSession() as http:
                resumed = await http.patch(server.make_url(f'/api/agent/research/jobs/{closed["research_id"]}'),
                                          headers=HEADERS, json={'action': 'resume'})
                assert resumed.status == 200
                body = await resumed.json()
                job = body['job']
                assert job['status'] == 'researching' and job['state']['phase'] == 'searching'
                assert job['state']['phaseHistory'][-1]['reason'] == 'owner-resume'
                assert closed['research_id'] in {item['research_id']
                                                 for item in store.research_jobs_active()}
                runs = [event['data'] for event in store.events(sid) if event['type'] == 'research_run']
                assert runs[-1]['phase'] == 'searching' and runs[-1]['status'] == 'researching'

                woken = await http.patch(server.make_url('/api/agent/research/jobs/RS2'),
                                        headers=HEADERS, json={'action': 'resume'})
                assert woken.status == 200
                paused = (await woken.json())['job']
                assert paused['status'] == 'researching' and paused['state']['phase'] == 'verifying'
                assert paused['state']['phaseHistory'] == [{'phase': 'verifying',
                                                            'reason': 'research-verify-evidence'}]
        finally:
            await server.close()

    asyncio.run(flow())
