"""Máy pha và pha ĐÓNG của một run (§5.3) — hai lỗi ĐO ĐƯỢC trên chạy thật ngày 2026-09-26.

Run `co-hoi-nao-con-trong` (phiên `9ccdb26b…`, model `muse-spark-1.3-contributor-free`) chạy bốn
lượt: phỏng vấn ⇒ năm nhánh tra cứu ⇒ hồ sơ v1 ⇒ hai vòng soát độc lập ⇒ hồ sơ v2, mà
`state.phase` vẫn đứng ở `planning` (chưa lần nào ghi `searching`/`synthesizing`/`verifying`/
`critiquing`). Rồi ở hàng cuối, chính model ghi `status='partial'` để nói thật "chưa xong" — code cũ
chỉ lưu trạng thái rồi im: vòng tiếp sức dừng, pha kẹt, và chủ nhà không nhận thẻ báo cáo nào.

Bộ kiểm này khoá bốn chuyện, mỗi chuyện là một điều người dùng NHÌN THẤY được: (1) `set_phase` là
cửa duy nhất ghi pha — có `phaseHistory`, đúng một event `research_run`, và KHÔNG nhích `revision`
(khoá lạc quan của model); (2) một nhánh tra cứu thật đưa run sang `searching`; (3) `partial` là
pha ĐÓNG, có lý do đọc được và có thẻ báo cáo; (4) `coverage` là chế độ soát giao được cho con —
trước đây `research_verify` nhận `mode='coverage'` mà `delegate_task` không cho giao, nên đường ấy
chết ở đầu còn lại.
"""
from __future__ import annotations

import asyncio

import pytest

import agentbox.agent_core.research_runtime as research_runtime
from agentbox.api.server import research_continuation_step
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    yield store, runtime, sid, store.get(sid)
    store.close()


def _job(store, sid, research_id='RS1', *, phase='planning', status='researching', extra=None):
    state = {'goal': 'mục tiêu', 'phase': phase, 'budgetSeconds': 1800, 'questions': [],
             'phaseHistory': [{'phase': phase, 'reason': 'fixture'}], 'facet': []}
    state.update(extra or {})
    return store.research_job_save(research_id, sid, state, status=status)


def _events(store, sid, kind):
    return [event['data'] for event in store.events(sid) if event['type'] == kind]


def test_set_phase_writes_history_and_one_run_event_without_moving_revision(harness):
    store, _runtime, sid, _session = harness
    job = _job(store, sid)
    before = job['revision']
    updated = research_runtime.set_phase(_runtime, sid, job, 'searching', 'branch-delegated')
    assert updated['state']['phase'] == 'searching'
    assert updated['state']['phaseHistory'][-1] == {'phase': 'searching', 'at':
                                                   updated['state']['phaseHistory'][-1]['at'],
                                                   'reason': 'branch-delegated'}
    assert updated['revision'] == before, 'đổi pha KHÔNG phải một bản ghi mới của run'
    runs = _events(store, sid, 'research_run')
    assert len(runs) == 1
    assert runs[0]['phase'] == 'searching' and runs[0]['status'] == 'researching'
    assert runs[0]['reason'] == 'branch-delegated' and runs[0]['revision'] == before


def test_set_phase_ignores_a_repeat_and_never_moves_off_done(harness):
    store, runtime, sid, _session = harness
    job = _job(store, sid)
    research_runtime.set_phase(runtime, sid, job, 'searching', 'branch-delegated')
    again = research_runtime.set_phase(runtime, sid, store.research_job('RS1'), 'searching', 'repeat')
    assert again is None, 'ghi lại đúng pha đang đứng là nhiễu, không phải tiến trình'
    assert len(_events(store, sid, 'research_run')) == 1
    research_runtime.set_phase(runtime, sid, store.research_job('RS1'), 'done', 'job-completed')
    closed = research_runtime.set_phase(runtime, sid, store.research_job('RS1'), 'searching', 'late')
    assert closed is None, 'run đã đóng thì không mở lại'
    assert store.research_job('RS1')['state']['phase'] == 'done'


def test_delegating_a_research_branch_moves_the_run_to_searching(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    main = runtime.create({'skills': []})
    main['config']['research'] = {'researchId': 'study', 'jobMode': 'v2', 'tier': 1}
    store.update_config(main['id'], main['config'])
    _job(store, main['id'], 'study', phase='planning', status='scoping',
         extra={'questions': [{'id': 'q1', 'text': 'Which approach?', 'status': 'unexplored'}]})
    runtime.start = lambda *_: asyncio.get_running_loop().create_future()
    asyncio.run(runtime.delegate(main, {'role': 'research', 'goal': 'Find evidence',
                                        'questionId': 'q1', 'wait': False}))
    job = store.research_job('study')
    assert job['status'] == 'researching' and job['state']['questions'][0]['status'] == 'researching'
    assert job['state']['phase'] == 'searching'
    assert job['state']['phaseHistory'][-1]['reason'] == 'branch-delegated'
    assert job['revision'] == 2, 'một lần ghi trạng thái + một lần ghim pha (không nhích `revision`)'
    runs = _events(store, main['id'], 'research_run')
    assert [item['phase'] for item in runs] == ['searching']
    store.close()


def test_partial_is_a_closed_phase_with_a_reason_and_a_report_card(harness):
    store, runtime, sid, session = harness
    store.record_dossier(sid, 'RS1', 1, '.research/RS1/v1-RS1.md', profile='price', level=3,
                         critique='none', gate='warn', rows=3, bytes=1200)
    _job(store, sid, extra={'reviewModes': ['evidence', 'critique'], 'background': False})
    result = research_runtime.research_update(runtime, session, {
        'researchId': 'RS1', 'status': 'partial',
        'finding': 'critique retry xong nội dung nhưng thiếu dòng VERDICT'})
    job = store.research_job('RS1')
    assert result['status'] == 'partial' and job['status'] == 'partial'
    assert job['state']['phase'] == 'done'
    assert job['state']['stopReason'] == ('critique retry xong nội dung nhưng thiếu dòng VERDICT')
    assert job['state']['phaseHistory'][-1]['reason'] == 'job-partial'
    assert job['research_id'] not in {item['research_id'] for item in store.research_jobs_active()}
    reports = _events(store, sid, 'research_report')
    assert len(reports) == 1 and reports[0]['researchId'] == 'RS1'
    assert reports[0]['version'] == 1 and 'partial' in reports[0]['labels']
    runs = _events(store, sid, 'research_run')
    assert runs[-1]['phase'] == 'done' and runs[-1]['reason'] == 'job-partial'
    assert runs[-1]['status'] == 'partial'

def test_a_repeat_close_never_emits_a_second_report_card(harness):
    """Đợt soát `3dc745f`, finding 3: một `research_update` LẶP LẠI (không kèm `status`, nên phân
    giải về đúng status đang đứng) từng phát thêm một thẻ báo cáo và một `research_run` cho cùng
    một run — thẻ báo cáo là hợp đồng người dùng đọc được, nên đóng một lần chỉ được có một thẻ.
    """
    store, runtime, sid, session = harness
    store.record_dossier(sid, 'RS1', 1, '.research/RS1/v1-RS1.md', profile='price', level=3,
                         critique='none', gate='warn', rows=3, bytes=1200)
    _job(store, sid, extra={'reviewModes': ['evidence', 'critique'], 'background': False})
    research_runtime.research_update(runtime, session, {
        'researchId': 'RS1', 'status': 'partial', 'finding': 'thiếu dòng VERDICT'})
    research_runtime.research_update(runtime, session, {
        'researchId': 'RS1', 'finding': 'checkpoint giữa đường'})
    history = store.research_job('RS1')['state']['phaseHistory']
    assert [row['phase'] for row in history].count('done') == 1, 'pha ĐÓNG ghi đúng một lần'
    assert len(_events(store, sid, 'research_report')) == 1
    done_runs = [item for item in _events(store, sid, 'research_run') if item['phase'] == 'done']
    assert len(done_runs) == 1


def test_the_pump_closing_a_foreground_run_writes_done_and_a_report_card(harness):
    """Đợt soát `3dc745f`, finding 2: hai đường BƠM của `api/server.py` từng kết thúc một run TIỀN
    CẢNH bằng `finish_background_run` — hàm này tự bỏ qua khi cờ nền tắt — nên run biến mất không
    thẻ báo cáo và `phase` kẹt ở `searching` để thanh tiến trình kể về một run đã chết.
    """
    store, runtime, sid, _session = harness
    research_runtime.apply_research_mode(runtime, store.get(sid), {'on': True})
    store.record_dossier(sid, 'RS1', 1, '.research/RS1/v1-RS1.md', profile='price', level=3,
                         critique='none', gate='warn', rows=3, bytes=1200)
    _job(store, sid, phase='searching', extra={'origin': 'mode', 'budgetSeconds': 0})
    config = store.get(sid)['config']
    config['researchMode']['activeRunId'] = 'RS1'
    store.update_config(sid, config)
    asyncio.run(research_continuation_step(runtime))
    job = store.research_job('RS1')
    assert job['status'] == 'partial'
    assert job['state']['phase'] == 'done'
    assert 'ngân sách' in job['state']['stopReason']
    reports = _events(store, sid, 'research_report')
    assert len(reports) == 1 and 'partial' in reports[0]['labels']
    assert _events(store, sid, 'research_run')[-1]['phase'] == 'done'
    assert _events(store, sid, 'research_notice') == [], 'run tiền cảnh không đi qua thông báo nền'
    assert 'RS1' not in {item['research_id'] for item in store.research_jobs_active()}


def test_a_coverage_verdict_lands_in_the_verifying_step(harness):
    """Đợt soát `3dc745f`, finding 6: bảng pha §5.2 xếp "Claim verifier, coverage reviewer" CÙNG
    bước `verifying`, nên một lần soát bao phủ phải ghi pha `verifying`, không phải `critiquing`.
    Bộ kiểm này đi hết đường: con `coverage` đọc hồ sơ ⇒ `research_verify(mode='coverage')`.
    """
    store, runtime, sid, session = harness
    store.record_dossier(sid, 'study', 1, '.research/study/v1-study.md', profile='deep', level=2,
                         critique='none', gate='warn', rows=5, bytes=2000)
    _job(store, sid, 'study', phase='synthesizing',
         extra={'tier': 2, 'reviewModes': ['evidence', 'critique']})
    child = runtime.create({'skills': []}, parent_id=sid, role='research-review')
    # `create` chỉ nhận các khoá nằm trong danh sách trắng của nó; `delegate_task` ghim
    # `reviewTarget` vào config SAU đó bằng `update_config` — dựng đúng hàng ấy ở đây.
    child_config = store.get(child['id'])['config']
    child_config['reviewTarget'] = {'kind': 'research', 'researchId': 'study',
                                    'version': 1, 'mode': 'coverage'}
    store.update_config(child['id'], child_config)
    store.child_start(child['id'], sid, 1, 1, 'research-review', 'soát bao phủ')
    text = ('Đã đối chiếu bản đồ bao phủ với sổ nguồn: ba hướng của thẻ phạm vi chưa có hàng nào, '
            'và một hướng trong đó là high-impact vì nó quyết định giá. ' + 'Nội dung dài hơn. ' * 16 +
            '\nVERDICT: ok\n')
    assert len(text) >= research_runtime.RESEARCH_REVIEW_MIN_ANSWER_CHARS
    store.emit(child['id'], 'assistant', {'text': text})
    store.child_finish(child['id'], 'completed', answer_chars=len(text))
    asyncio.run(research_runtime.research_verify(runtime, session, {
        'researchId': 'study', 'version': 1, 'verdict': 'ok', 'mode': 'coverage',
        'summary': 'bao phủ đủ'}))
    job = store.research_job('study')
    assert job['state']['phase'] == 'verifying'
    assert job['state']['phaseHistory'][-1]['reason'] == 'research-verify-coverage'
    verified = _events(store, sid, 'research_verified')
    assert verified and verified[-1]['mode'] == 'coverage' and verified[-1]['verdict'] == 'ok'



def test_a_coverage_review_can_be_delegated_and_an_unknown_mode_is_still_refused(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    main = runtime.create({'skills': []})
    main['config']['research'] = {'researchId': 'study', 'jobMode': 'v2', 'tier': 2}
    store.update_config(main['id'], main['config'])
    _job(store, main['id'], 'study', phase='verifying', extra={'reviewModes': ['evidence', 'critique']})
    store.record_dossier(main['id'], 'study', 1, '.research/study/v1-study.md', profile='deep',
                         level=2, critique='none', gate='warn', rows=5, bytes=2000)
    runtime.start = lambda *_: asyncio.get_running_loop().create_future()
    target = {'kind': 'research', 'researchId': 'study', 'version': 1, 'mode': 'coverage'}
    asyncio.run(runtime.delegate(main, {'role': 'research-review', 'goal': 'soát bao phủ hướng',
                                        'reviewTarget': target, 'wait': False}))
    child = store.children_of(main['id'])[0]
    assert store.get(child['session_id'])['config']['reviewTarget']['mode'] == 'coverage'
    with pytest.raises(ValueError, match='RESEARCH_REVIEW_MODE_INVALID'):
        asyncio.run(runtime.delegate(main, {'role': 'research-review', 'goal': 'soát bừa',
                                            'reviewTarget': {**target, 'mode': 'vibes'},
                                            'wait': False}))
    store.close()
