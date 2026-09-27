"""Vỏ mode `/research` + ranh giới main↔research của P1 (plan v2 §5.2, §5.3, §5.10, §5.12).

Nhóm M của plan (§8.2) chạy tất định trong CI: không mạng, không gọi mô hình thật. Mọi hành vi mới
của P1 nằm sau công tắc `BOXFOX_RESEARCH_MODE` — tệp này bật công tắc bằng `monkeypatch`, và bài
cuối cùng chứng minh công tắc TẮT thì hành vi quay về đúng f17d54b.
"""
from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import limits, research_runtime, tool_contracts
from agentbox.agent_core import runtime as runtime_module
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app, research_continuation_step, research_job_pumpable
from agentbox.memory.session_store import SessionStore
from agentbox.skills.commands import CommandRegistry
from agentbox.skills.catalog import SkillCatalog

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


class RecordingModel:
    """Ghi lại danh sách công cụ mỗi lượt và ĐẾM số lần được gọi (M-16: không gọi mô hình)."""

    def __init__(self, answer='ok'):
        self.offered = []
        self.calls = 0
        self.answer = answer

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls += 1
        self.offered.append([schema['function']['name'] for schema in tools])
        return {'choices': [{'message': {'content': self.answer}, 'finish_reason': 'stop'}],
                'usage': None, 'boxfox': None}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.RESEARCH_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    yield store, runtime, sid
    store.close()


def session_of(store, sid):
    return store.get(sid)


def events(store, sid, kind=None):
    return [row['data'] for row in store.events(sid) if kind is None or row['type'] == kind]


def run_turn(runtime, sid, prompt, invocation_id=None):
    """Nộp một lượt và chờ xong — dùng ở đây để đo bộ công cụ/hồ sơ lượt thật."""

    async def main():
        await runtime.submit(sid, prompt, invocation_id=invocation_id)
        task = runtime.tasks.get(sid)
        if task is not None:
            await task

    asyncio.run(main())


# ------------------------------------------------------------------ M-01 / M-02 / M-03 / M-04 / M-16


def test_m01_turning_mode_on_from_the_toggle_changes_the_config_and_sends_no_turn(harness):
    store, runtime, sid = harness
    result = research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True, 'by': 'toggle'})
    assert result['on'] is True and result['prompt'] is None
    config = session_of(store, sid)['config']
    assert config['researchMode']['on'] is True
    assert config['researchMode']['enteredBy'] == 'toggle'
    assert [item for item in events(store, sid, limits.RESEARCH_MODE_EVENT_CODE)] == [
        {'on': True, 'by': 'toggle', 'activeRunId': None, 'revision': 1}]
    assert sid not in runtime.tasks, 'bật mode không gửi lượt nào'


def test_m02_slash_research_with_text_is_a_mode_command_that_opens_a_turn(harness):
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    registry = CommandRegistry(store, SkillCatalog())
    resolved = registry.resolve('/research tìm tài liệu chính thức', subagents=[])
    assert resolved.kind == 'mode' and resolved.command == 'research'
    assert resolved.prompt == 'tìm tài liệu chính thức'
    run_turn(runtime, sid, '/research tìm tài liệu chính thức')
    assert session_of(store, sid)['config']['researchMode']['on'] is True
    assert model.calls == 1, 'lệnh có nội dung vẫn mở đúng một lượt'
    assert limits.RESEARCH_MODE_BLOCK_MARKER in session_of(store, sid)['messages'][0]['content']


def test_m03_bare_slash_research_turns_the_mode_on_without_a_turn(harness):
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    result = asyncio.run(runtime.submit(sid, '/research'))
    assert result['status'] == 'idle'
    assert session_of(store, sid)['config']['researchMode']['on'] is True
    assert model.calls == 0
    assert sid not in runtime.tasks, 'M-03: `/research` rỗng KHÔNG tạo lượt'


def test_m04_slash_research_off_without_a_run_turns_the_mode_off(harness):
    store, runtime, sid = harness
    asyncio.run(runtime.submit(sid, '/research'))
    model = RecordingModel()
    runtime.client = model
    result = asyncio.run(runtime.submit(sid, '/research off'))
    assert session_of(store, sid)['config']['researchMode']['on'] is False
    assert result['status'] == 'idle'
    assert model.calls == 0
    event = events(store, sid, limits.RESEARCH_MODE_EVENT_CODE)[-1]
    assert event['on'] is False and event['by'] == 'command'


def test_m16_slash_research_status_replays_the_card_without_a_turn_or_a_model_call(harness):
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    asyncio.run(runtime.submit(sid, '/research'))
    store.research_job_save('run-a', sid, {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600,
                                          'questions': [], 'scope': {'revision': 2}}, status='researching')
    before = model.calls
    result = asyncio.run(runtime.submit(sid, '/research status'))
    assert 'run-a' in result['output'] and 'searching' in result['output']
    # D-4 (vòng kiểm thử P2–P5): sự kiện phải mang `message` — giao diện dựng thẻ trạng thái từ CHÍNH
    # sự kiện này; bản trước cắt trường ấy nên `/research status` đúng ở server mà im lặng với người dùng.
    card = events(store, sid, 'research_run')[-1]
    assert card['kind'] == 'status' and card['message'] == result['output']
    assert model.calls == before, 'M-16: `/research status` không gọi mô hình'
    assert sid not in runtime.tasks or runtime.tasks[sid].done()


# ------------------------------------------------------------------ M-05 (mức 3 chỉ trong mode)


def test_m05_tier_three_outside_mode_is_refused_with_research_mode_required(harness):
    store, runtime, sid = harness
    session = session_of(store, sid)
    before = json.dumps(session['config'], sort_keys=True)
    with pytest.raises(ValueError, match=limits.RESEARCH_MODE_REQUIRED_CODE):
        asyncio.run(runtime.dispatch(session, 'research_brief', {
            'tier': 3, 'question': 'Toàn cảnh thị trường?', 'rationale': 'việc lớn'}))
    assert json.dumps(session_of(store, sid)['config'], sort_keys=True) == before, \
        'từ chối chứ KHÔNG hạ mức im lặng (và không ghi brief)'


def test_m05_tier_three_is_allowed_once_the_mode_is_on(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    answer = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_brief', {
        'tier': 3, 'question': 'Toàn cảnh thị trường?', 'rationale': 'việc lớn'}))
    assert answer['tier'] == 3


# ------------------------------------------------------------------ M-06 (research_suggest không đổi config)


def test_m06_research_suggest_only_emits_and_never_changes_the_config(harness):
    store, runtime, sid = harness
    before = json.dumps(session_of(store, sid)['config'], sort_keys=True)
    answer = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_suggest',
                                          {'reason': 'cần bản đồ tài liệu', 'draftGoal': 'Toàn cảnh X'}))
    assert answer['suggested'] is True and answer['changedConfig'] is False
    assert json.dumps(session_of(store, sid)['config'], sort_keys=True) == before
    [suggestion] = events(store, sid, 'research_suggested')
    assert suggestion['draftGoal'] == 'Toàn cảnh X'
    assert session_of(store, sid)['config'].get('researchMode', {}).get('on', False) is False


# ------------------------------------------------------------------ M-07 (cửa 2: brief bắt buộc)


def test_m07_outside_mode_the_second_unbriefed_branch_is_refused(harness):
    store, runtime, sid = harness
    runtime.active_turn[sid] = 1
    assert research_runtime.missing_brief_gate(runtime, session_of(store, sid), 'research') is True
    store.child_start('child-1', sid, 1, 1, 'research')
    with pytest.raises(ValueError, match=limits.RESEARCH_BRIEF_MISSING_CODE):
        research_runtime.missing_brief_gate(runtime, session_of(store, sid), 'research')


def test_m07_the_first_unbriefed_branch_is_clamped_to_tier_one(harness):
    store, runtime, sid = harness
    runtime.active_turn[sid] = 1
    clamp = research_runtime.quick_lookup_clamp(runtime, session_of(store, sid), 'research')
    assert clamp == {'tier': 1, 'childSteps': 20, 'childSeconds': 180}


# ------------------------------------------------- công tắc mặc định: phải là BẬT (F4, lưới vòng 2)


def test_default_config_has_the_mode_on_and_keeps_the_mode_gates(tmp_path, monkeypatch):
    """Vòng soát 2: bài này chạy trên cấu hình MẶC ĐỊNH (không đặt biến công tắc).

    Ba tệp kiểm cũ (`test_research_brief`, `test_fanout`, `test_delegation_contract`) đã được ghim
    `BOXFOX_RESEARCH_MODE=off` để giữ hành vi cũ, nên nếu không có bài này thì cấu hình thật của chủ
    nhà chỉ còn một tấm lưới. Ở đây: tính năng phải CÓ MẶT khi không đặt biến, và khi đó
    `research_brief`/`delegate_task` đi qua cửa của mode (mức 3 ngoài mode bị từ chối).
    """
    monkeypatch.delenv(limits.RESEARCH_MODE_ENV, raising=False)
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    try:
        assert runtime_module.research_mode_available() is True, 'mặc định phải là BẬT'
        session = session_of(store, sid)
        # Ngoài mode: mức 3 vẫn là cổng của mode (main không được mở mức 3 khi chưa bật mode).
        assert runtime_module.tier3_mode_only() is True
        assert research_runtime.quick_lookup_clamp(runtime, session, 'research') == {
            'tier': 1, 'childSteps': 20, 'childSeconds': 180}
        # Trong mode: chỉ vai research được giao nhánh (cổng F9 trên cấu hình mặc định).
        session['config']['subagents'] = [{'id': 'build', 'enabled': True}]
        store.update_config(sid, session['config'])
        research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
        with pytest.raises(PermissionError, match='RESEARCH_MODE_DELEGATE_ROLE'):
            asyncio.run(runtime.delegate(session_of(store, sid),
                                         {'role': 'build', 'goal': 'viết code'}))
    finally:
        store.close()


# ------------------------------------------------------------------ M-08 (bơm)


def test_m08_the_pump_skips_main_jobs_mode_off_jobs_and_needs_user(harness):
    store, runtime, sid = harness
    session = session_of(store, sid)
    main_job = {'research_id': 'main-job', 'session_id': sid, 'revision': 1, 'status': 'researching',
                'state': {'origin': 'main', 'phase': 'searching', 'budgetSeconds': 600}}
    mode_job = {'research_id': 'mode-job', 'session_id': sid, 'revision': 1, 'status': 'researching',
                'state': {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600}}
    assert research_job_pumpable(runtime, main_job, session) is False, 'origin=main không bao giờ bơm'
    assert research_job_pumpable(runtime, mode_job, session) is False, 'mode tắt và không chạy nền'
    research_runtime.apply_research_mode(runtime, session, {'on': True})
    session = session_of(store, sid)
    assert research_job_pumpable(runtime, mode_job, session) is False, 'activeRunId chưa trỏ vào job này'
    store.research_job_save('mode-job', sid, mode_job['state'], status='researching')
    config = session['config']
    config['researchMode']['activeRunId'] = 'mode-job'
    store.update_config(sid, config)
    assert research_job_pumpable(runtime, mode_job, session_of(store, sid)) is True
    background = {'research_id': 'bg', 'session_id': sid, 'revision': 1, 'status': 'researching',
                  'state': {'origin': 'mode', 'phase': 'searching', 'background': True, 'budgetSeconds': 600}}
    assert research_job_pumpable(runtime, background, session_of(store, sid)) is True
    clarifying = {'research_id': 'cl', 'session_id': sid, 'revision': 1, 'status': 'scoping',
                  'state': {'origin': 'mode', 'phase': 'clarifying', 'background': True, 'budgetSeconds': 600}}
    assert research_job_pumpable(runtime, clarifying, session_of(store, sid)) is False


# ------------------------------------------------------------------ M-09 / M-10a / M-10b / M-15


def test_m09_pause_by_job_never_stops_the_whole_session(harness, monkeypatch):
    store, runtime, sid = harness
    store.research_job_save('run-halt', sid, {'origin': 'mode', 'phase': 'searching',
                                             'budgetSeconds': 600, 'questions': []}, status='researching')

    async def forbidden(_sid):
        raise AssertionError('research_halt must never stop the whole session')

    monkeypatch.setattr(runtime, 'stop', forbidden)
    job = store.research_job('run-halt')
    updated = asyncio.run(runtime.research_halt(job, 'pause'))
    assert updated['status'] == 'paused'
    assert events(store, sid, 'research_run')[-1]['status'] == 'paused'


def test_m10a_exit_choice_pause_keeps_active_run_id_and_the_pump_stays_away(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-p', sid, {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600,
                                          'questions': []}, status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-p'
    store.update_config(sid, config)
    result = research_runtime.apply_research_mode(runtime, session_of(store, sid),
                                                 {'on': False, 'exitChoice': 'pause'})
    assert result['on'] is False and result['activeRunId'] == 'run-p'
    assert session_of(store, sid)['config']['researchMode']['activeRunId'] == 'run-p'
    assert store.research_job('run-p')['status'] == 'paused'
    assert research_job_pumpable(runtime, store.research_job('run-p'), session_of(store, sid)) is False


def test_m10b_exit_choice_background_keeps_the_run_and_the_pump_keeps_going(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-bg', sid, {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600,
                                           'questions': []}, status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-bg'
    store.update_config(sid, config)
    research_runtime.apply_research_mode(runtime, session_of(store, sid),
                                        {'on': False, 'exitChoice': 'background'})
    job = store.research_job('run-bg')
    assert job['state']['background'] is True and job['status'] == 'researching'
    assert session_of(store, sid)['config']['researchMode']['on'] is False
    assert research_job_pumpable(runtime, job, session_of(store, sid)) is True
    # Lượt bơm dùng hồ sơ research kể cả khi mode đã tắt.
    profile = runtime.turn_profile(session_of(store, sid), 'research-resume-run-bg-1')
    assert profile['mode'] == 'research'
    assert not (set(profile['tools']) & set(limits.RESEARCH_MODE_EXCLUDED_TOOLS))
    main_profile = runtime.turn_profile(session_of(store, sid), None)
    assert main_profile['mode'] == 'main'


def test_m10b_background_finish_emits_the_report_and_the_notice_and_the_handoff_once(harness):
    store, runtime, sid = harness
    store.research_job_save('run-done', sid, {'origin': 'mode', 'phase': 'done', 'background': True,
                                             'budgetSeconds': 600, 'tier': 2,
                                             'reviewModes': ['critique'],
                                             'questions': [{'id': 'q1', 'importance': 'high',
                                                            'status': 'answered'}],
                                             'scope': {'revision': 1, 'goal': {'text': 'X', 'status': 'confirmed'}}},
                            status='researching')
    store.record_dossier(sid, 'run-done', 1, '.research/run-done/v1-done.md', quality_ok=True)
    store.dossier_critique_set('run-done', 1, 'ok')
    answer = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_update',
                                          {'researchId': 'run-done', 'status': 'completed'}))
    assert answer['status'] == 'completed'
    kinds = [row['type'] for row in store.events(sid)]
    assert 'research_report' in kinds and 'research_notice' in kinds
    assert store.research_job('run-done')['state']['background'] is False
    handoff = runtime.research_handoff(session_of(store, sid))
    assert handoff is not None and handoff['researchId'] == 'run-done'
    runtime.mark_handoff_delivered(session_of(store, sid), handoff['researchId'], handoff['version'])
    assert runtime.research_handoff(session_of(store, sid)) is None, 'bàn giao MỘT lần cho mỗi bản hồ sơ'


def test_m10c_turning_mode_off_without_a_choice_is_409_and_keeps_the_mode_on(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-x', sid, {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600,
                                          'questions': []}, status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-x'
    store.update_config(sid, config)
    with pytest.raises(ValueError, match=limits.RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE) as caught:
        research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': False})
    assert caught.value.payload['code'] == limits.RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE
    assert caught.value.payload['prompt']['kind'] == 'exit-choice'
    assert session_of(store, sid)['config']['researchMode']['on'] is True, 'M-10c: mode KHÔNG đổi'
    assert store.research_job('run-x')['status'] == 'researching'


def test_the_put_route_answers_409_with_the_exit_choice_prompt(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-http', sid, {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600,
                                             'questions': []}, status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-http'
    store.update_config(sid, config)

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                async with http.put(str(server.make_url(f'/api/agent/sessions/{sid}/research-mode')),
                                    json={'on': False}) as resp:
                    assert resp.status == 409
                    body = await resp.json()
                async with http.put(str(server.make_url(f'/api/agent/sessions/{sid}/research-mode')),
                                    json={'on': True}) as ok:
                    assert ok.status == 200
                    enabled = await ok.json()
        return body, enabled

    body, enabled = asyncio.run(run())
    assert body['code'] == limits.RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE
    assert body['prompt']['kind'] == 'exit-choice'
    assert len(body['prompt']['questions'][0]['options']) == 2
    assert enabled['on'] is True


def test_m15_dismissing_the_exit_prompt_changes_nothing(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-d', sid, {'origin': 'mode', 'phase': 'searching', 'budgetSeconds': 600,
                                          'questions': []}, status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-d'
    store.update_config(sid, config)
    with pytest.raises(ValueError):
        research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': False})
    [prompt] = store.research_job('run-d')['state']['prompts']
    research_runtime.dismiss_prompt(runtime, sid, store.research_job('run-d'), prompt['promptId'])
    assert session_of(store, sid)['config']['researchMode']['on'] is True
    assert store.research_job('run-d')['status'] == 'researching'


# ------------------------------------------------------------------ M-11 / M-17 (thẻ phạm vi + lời hỏi)


def scope_job(store, sid, research_id='run-scope'):
    store.research_job_save(research_id, sid, {
        'origin': 'mode', 'phase': 'clarifying', 'budgetSeconds': 1800, 'tier': 2,
        'goal': 'Toàn cảnh X', 'questions': [{'id': 'q1', 'importance': 'high', 'status': 'unexplored'}],
        'scope': {'revision': 0}}, status='scoping')
    return store.research_job(research_id)


def test_m11_scope_edits_bump_the_revision_and_a_stale_revision_is_refused(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    scope_job(store, sid)
    first = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                         {'action': 'propose', 'researchId': 'run-scope',
                                          'patch': {'purpose': 'chọn phương án dùng ngay'}}))
    assert first['revision'] == 1
    second = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                          {'action': 'update', 'researchId': 'run-scope',
                                           'patch': {'depth': 'deep'}}))
    assert second['revision'] == 2
    scope = store.research_job('run-scope')['state']['scope']
    assert scope['purpose']['status'] == 'assumed', 'agent đề xuất ⇒ giả định, không phải xác nhận'
    assert scope['purpose']['source']['kind'] == 'agent'
    assert [item['revision'] for item in events(store, sid, 'research_scope')] == [1, 2]


def test_m17_answers_land_in_one_call_and_clear_needs_user(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    scope_job(store, sid)
    asked = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                         {'action': 'ask', 'researchId': 'run-scope', 'questions': [
                                             {'id': 'iq1', 'text': 'Dùng để làm gì?', 'blocking': True,
                                              'options': [{'id': 'o1', 'label': 'Dùng ngay'},
                                                          {'id': 'o2', 'label': 'Bản đồ nghiên cứu'}]},
                                             {'id': 'iq2', 'text': 'Cửa sổ thời gian?', 'blocking': True,
                                              'options': [{'id': 'o1', 'label': '12 tháng'},
                                                          {'id': 'o2', 'label': 'Mọi lúc'}]}]}))
    assert asked['needsUser'] is True
    assert store.research_job('run-scope')['status'] == 'needs_user'
    job = store.research_job('run-scope')
    prompt = job['state']['prompts'][0]
    with pytest.raises(ValueError, match=limits.RESEARCH_SCOPE_REVISION_STALE_CODE):
        research_runtime.answer_prompt(runtime, sid, job, {'promptId': prompt['promptId'], 'revision': 99,
                                                          'answers': []})
    with pytest.raises(ValueError, match='RESEARCH_PROMPT_UNANSWERED'):
        research_runtime.answer_prompt(runtime, sid, job, {
            'promptId': prompt['promptId'], 'revision': prompt['revision'], 'start': True,
            'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    done = research_runtime.answer_prompt(runtime, sid, job, {
        'promptId': prompt['promptId'], 'revision': prompt['revision'], 'start': True,
        'answers': [{'questionId': 'iq1', 'optionId': 'o1'}, {'questionId': 'iq2', 'text': '24 tháng'}]})
    assert done['resume'] is True and done['unanswered'] == []
    saved = store.research_job('run-scope')
    assert saved['status'] == 'researching' and saved['state']['scope']['openQuestions'][0]['answer']['status'] == 'confirmed'


def test_m12_the_scope_card_splits_what_the_user_confirmed_from_what_the_agent_assumed(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    scope_job(store, sid)
    asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                 {'action': 'propose', 'researchId': 'run-scope',
                                  'patch': {'purpose': 'chọn phương án dùng ngay', 'depth': 'deep'}}))
    asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                 {'action': 'ask', 'researchId': 'run-scope', 'questions': [
                                     {'id': 'iq1', 'text': 'Cửa sổ thời gian?', 'blocking': True,
                                      'options': [{'id': 'o1', 'label': '12 tháng'}]}]}))
    job = store.research_job('run-scope')
    prompt = job['state']['prompts'][0]
    research_runtime.answer_prompt(runtime, sid, job, {
        'promptId': prompt['promptId'], 'revision': prompt['revision'],
        'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    scope = store.research_job('run-scope')['state']['scope']
    assert scope['purpose']['status'] == 'assumed' and scope['purpose']['source']['kind'] == 'agent'
    [answered] = scope['openQuestions']
    assert answered['answer']['status'] == 'confirmed' and answered['answer']['text'] == '12 tháng'
    assert answered['blocking'] is False, 'trả lời xong thì câu chặn thành đã trả lời'


# ------------------------------------------------------------------ M-12 / M-13 / M-14


def test_m12_m13_the_handoff_separates_confirmed_from_assumed_and_carries_the_labels(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-h', sid, {
        'origin': 'mode', 'phase': 'done', 'budgetSeconds': 900, 'tier': 2, 'reviewModes': ['critique'],
        'questions': [], 'goal': 'X',
        'scope': {'revision': 3,
                  'goal': {'text': 'Mức hưởng 2026', 'status': 'confirmed',
                           'source': {'kind': 'user', 'seq': 12}},
                  'purpose': {'text': 'chọn phương án dùng ngay', 'status': 'assumed',
                              'source': {'kind': 'agent'}},
                  'openQuestions': [{'id': 'iq1', 'text': 'Cửa sổ thời gian?', 'blocking': False}]}},
        status='partial')
    store.record_dossier(sid, 'run-h', 1, '.research/run-h/v1-h.md', quality_ok=True)
    store.dossier_critique_set('run-h', 1, 'revise')
    # Khối bàn giao chỉ dựng khi mode TẮT (§5.10); chọn "chạy nền" để run giữ nguyên nhãn `partial`.
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-h'
    store.update_config(sid, config)
    research_runtime.apply_research_mode(runtime, session_of(store, sid),
                                        {'on': False, 'exitChoice': 'background'})
    block = runtime.research_handoff(session_of(store, sid))['block']
    assert 'Bạn đã xác nhận: goal: Mức hưởng 2026' in block
    assert 'Giả định của agent: purpose: chọn phương án dùng ngay' in block
    assert 'partial' in block and limits.RESEARCH_CRITIQUE_LABEL in block
    assert 'open questions: Cửa sổ thời gian?' in block
    assert 'do NOT raise the confidence' in block


def test_a_research_turn_is_capped_at_the_short_turn_target(harness, monkeypatch):
    """§5.5 — lượt research nhắm ≤ `RESEARCH_TURN_TARGET_SECONDS`; lượt main giữ trần của phiên."""
    store, runtime, sid = harness
    session = session_of(store, sid)
    session['config']['deadlineSeconds'] = 3600
    store.update_config(sid, session['config'])
    session = session_of(store, sid)
    assert runtime.turn_budget_seconds(session) == 3600, 'mode tắt ⇒ không chia lượt ngắn'
    research_runtime.apply_research_mode(runtime, session, {'on': True})
    session = session_of(store, sid)
    assert runtime.turn_budget_seconds(session) == limits.RESEARCH_TURN_TARGET_SECONDS
    assert runtime.turn_budget_seconds(session, 'research-resume-run-1') == limits.RESEARCH_TURN_TARGET_SECONDS
    monkeypatch.setenv(limits.RESEARCH_TURN_TARGET_SECONDS_ENV, '0')
    assert runtime.turn_budget_seconds(session) == 3600, '0 ⇒ tắt chia lượt ngắn'
    monkeypatch.setenv(limits.RESEARCH_TURN_TARGET_SECONDS_ENV, '600')
    session['config']['deadlineSeconds'] = 240
    store.update_config(sid, session['config'])
    assert runtime.turn_budget_seconds(session_of(store, sid)) == 240, 'trần phiên vẫn là trần trên'


def test_m14_the_mode_tool_set_drops_every_write_tool(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    profile = runtime.turn_profile(session_of(store, sid))
    assert profile['mode'] == 'research'
    assert not (set(profile['tools']) & set(limits.RESEARCH_MODE_EXCLUDED_TOOLS))
    assert 'ask_user' in profile['tools'] and 'delegate_task' in profile['tools']
    assert limits.RESEARCH_MODE_BLOCK_MARKER in profile['promptBlock']


def test_the_sop_naming_the_block_does_not_make_the_block_stripper_eat_the_prompt(harness):
    """Câu nhắc TÊN khối mode (không khép bằng end marker) không được làm luật gỡ nuốt phần đuôi."""
    store, runtime, sid = harness
    session = session_of(store, sid)
    mention = f'=== ASSIGNED ROLE ===\nA block named "{limits.RESEARCH_MODE_BLOCK_MARKER}" wins.\n\n'
    session['messages'][0]['content'] = mention + (session['messages'][0]['content'] or '')
    store.save(sid, session['messages'])
    runtime._sync_mode_block(session)
    after = session_of(store, sid)['messages'][0]['content']
    assert '=== ANSWER LENGTH ===' in after and '=== ENABLED SKILLS' in after, \
        'mode tắt và không có gì để bàn giao ⇒ prompt không đổi'
    assert after == store.get(sid)['messages'][0]['content']


def test_the_mode_block_is_inserted_and_removed_per_turn(harness):
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    session = session_of(store, sid)
    runtime._sync_mode_block(session)
    assert limits.RESEARCH_MODE_BLOCK_MARKER in session['messages'][0]['content']
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': False})
    session = session_of(store, sid)
    runtime._sync_mode_block(session)
    assert limits.RESEARCH_MODE_BLOCK_MARKER not in session['messages'][0]['content']


# ------------------------------------------------------------------ M-18 (research_update theo job)


def test_m18_outside_mode_main_may_only_pause_a_background_run(harness):
    store, runtime, sid = harness
    store.research_job_save('foreground', sid, {'origin': 'main', 'phase': 'searching',
                                                'budgetSeconds': 600, 'questions': []},
                            status='researching')
    with pytest.raises(PermissionError, match='RESEARCH_UPDATE_BACKGROUND_ONLY'):
        asyncio.run(runtime.dispatch(session_of(store, sid), 'research_update',
                                     {'researchId': 'foreground', 'action': 'pause'}))
    store.research_job_save('background', sid, {'origin': 'mode', 'phase': 'searching', 'background': True,
                                                'budgetSeconds': 600, 'questions': []},
                            status='researching')
    answer = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_update',
                                          {'researchId': 'background', 'action': 'cancel'}))
    assert answer['status'] == 'cancelled'
    assert store.research_job('background')['status'] == 'cancelled'


def test_m18_pausing_a_background_run_keeps_the_session_alive(harness, monkeypatch):
    store, runtime, sid = harness
    store.research_job_save('bg2', sid, {'origin': 'mode', 'phase': 'searching', 'background': True,
                                         'budgetSeconds': 600, 'questions': []}, status='researching')

    async def forbidden(_sid):
        raise AssertionError('job control must never stop the session')

    monkeypatch.setattr(runtime, 'stop', forbidden)
    answer = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_update',
                                          {'researchId': 'bg2', 'action': 'pause'}))
    assert answer['status'] == 'paused'


# ------------------------------------------------------------------ công tắc giết


def test_with_the_mode_switch_off_everything_behaves_like_before(monkeypatch, tmp_path):
    monkeypatch.setenv(limits.RESEARCH_MODE_ENV, 'off')
    assert runtime_module.research_mode_available() is False
    store = SessionStore(tmp_path / 'legacy.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1', 'timeoutSeconds': 30})['id']
    registry = CommandRegistry(store, SkillCatalog())
    resolved = registry.resolve('/research tìm tài liệu chính thức',
                                subagents=[{'id': 'research', 'enabled': True}])
    assert resolved.kind == 'task' and resolved.role == 'research', 'công tắc tắt ⇒ lệnh vai cũ'
    session = store.get(sid)
    assert runtime.turn_profile(session)['mode'] == 'main'
    assert runtime.turn_profile(session)['promptBlock'] == ''
    runtime.active_turn[sid] = 1
    store.child_start('legacy-1', sid, 1, 1, 'research')
    # Cổng cửa 2 không chạy khi công tắc tắt: cổng MỀM warn của f17d54b giữ nguyên — notice, không chặn.
    assert research_runtime.missing_brief_gate(runtime, session, 'research') is True
    assert limits.RESEARCH_BRIEF_MISSING_CODE in [item['code'] for item in events(store, sid, 'notice')]
    assert research_job_pumpable(runtime, {'research_id': 'j', 'session_id': sid, 'revision': 1,
                                          'status': 'researching',
                                          'state': {'phase': 'searching'}}, session) is True, \
        'job cũ không có origin ⇒ đường bơm cũ giữ nguyên'
    store.research_job_save('needs', sid, {'origin': 'mode', 'phase': 'clarifying', 'budgetSeconds': 600},
                            status='needs_user')
    assert 'needs' not in {job['research_id'] for job in store.research_jobs_active()}
    store.close()


# ------------------------------------------------------------------ Sửa soát mã: F1, F2, F3, F4, F5, F6, F7, F8, F9, F10 + rò rỉ sổ
# (phiếu `/code/.plans/review-mode-api-findings.md`). Mỗi ca dựng ĐÚNG tình huống mà bản gốc hỏng:
# đi qua hồ sơ lượt thật / tuyến bơm thật / API thật, không tự tay viết lại `state`.


def test_f1_research_scope_is_offered_in_the_turn_when_the_mode_is_on(harness):
    """F1: công cụ cấp thẻ phạm vi phải NẰM TRONG bộ công cụ của lượt + có schema."""
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    run_turn(runtime, sid, 'mở một run mới cho việc này')
    offered = model.offered[-1]
    assert 'research_scope' in offered, 'mode ra lệnh dùng `research_scope` nhưng không cấp schema ⇒ vô nghĩa'
    names = {schema['function']['name'] for schema in tool_contracts.schemas_for(offered)}
    assert 'research_scope' in names
    assert set(offered) & set(limits.RESEARCH_MODE_EXCLUDED_TOOLS) == set()
    # Và nhóm công cụ của runtime phải mô tả đúng: hợp của các nhóm = bộ orchestrator.
    from agentbox.agent_core.tool_groups import TOOL_GROUPS
    union = {tool for group in TOOL_GROUPS for tool in group['tools']}
    assert 'research_scope' in union


def test_f2_research_halt_inside_its_own_resume_turn_writes_the_status_without_waiting_for_itself(harness):
    """F2: lượt bơm tự tạm dừng job của mình — không được `await` chính nó, và phải GHI TRƯỚC."""
    store, runtime, sid = harness
    store.research_job_save('run-self', sid, {'origin': 'mode', 'phase': 'searching',
                                              'budgetSeconds': 600, 'questions': []}, status='researching')
    job = store.research_job('run-self')
    seen = {}

    async def scenario():
        runtime.turn_invocations[sid] = 'research-resume-run-self-1'
        runtime.tasks[sid] = asyncio.current_task()
        seen['updated'] = await runtime.research_halt(job, 'pause')

    # `research_halt` phải TRẢ VỀ ngay (bản gốc `await asyncio.gather(task)` chờ chính nó ⇒ treo tới
    # 60 s rồi `RecursionError`). Việc dừng lượt bơm đang chạy là hệ quả ĐÚNG: task tự huỷ chính nó,
    # nên `CancelledError` ở đây là tín hiệu lượt bơm đã dừng, không phải lỗi của phép thử.
    try:
        asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    except asyncio.CancelledError:
        pass
    assert seen['updated']['status'] == 'paused', 'trạng thái phải ghi TRƯỚC khi dừng lượt'
    assert store.research_job('run-self')['status'] == 'paused'
    assert events(store, sid, 'research_run')[-1]['status'] == 'paused'


def test_f3_a_run_opened_in_the_mode_becomes_the_active_run_and_is_pumpable(harness):
    """F3: `research_brief` trong mode phải ghim `activeRunId`, nếu không bơm không bao giờ thấy run."""
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    answer = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_brief', {
        'tier': 2, 'question': 'Mức hưởng chuyển tuyến 2026?', 'rationale': 'cần dẫn nguồn văn bản',
        'goal': 'Toàn cảnh mức hưởng', 'methods': ['web'], 'output': 'báo cáo',
        'questions': [{'text': 'Tuyến nào?', 'importance': 'high'}]}))
    run_id = answer['researchId']
    assert session_of(store, sid)['config']['researchMode']['activeRunId'] == run_id, \
        'run do mode mở phải là run đang hoạt động'
    # Pha `clarifying` CHƯA bơm được (lượt của nó là lượt đang chờ người dùng) — nhưng phải thấy run.
    assert research_job_pumpable(runtime, store.research_job(run_id), session_of(store, sid)) is False
    asked = asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope', {
        'action': 'ask', 'researchId': run_id, 'questions': [
            {'id': 'iq1', 'text': 'Tuyến nào?', 'blocking': True,
             'options': [{'id': 'o1', 'label': 'Tuyến huyện'}]}]}))
    assert asked['needsUser'] is True
    job = store.research_job(run_id)
    prompt = job['state']['prompts'][0]
    research_runtime.answer_prompt(runtime, sid, job, {
        'promptId': prompt['promptId'], 'revision': prompt['revision'], 'start': True,
        'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    job = store.research_job(run_id)
    assert (job['state'] or {}).get('phase') == 'planning'
    assert research_job_pumpable(runtime, job, session_of(store, sid)) is True, \
        'run của mode phải bơm được sau khi trả lời hết câu chặn'


def test_f4_the_default_is_on_and_the_api_refuses_a_half_built_mode_when_switched_off(monkeypatch, tmp_path):
    """F4: mặc định `on` (tính năng CÓ MẶT); khi công tắc tắt, API phải trả lỗi rõ."""
    assert limits.RESEARCH_MODE_DEFAULT_MODE == 'on'
    assert runtime_module.research_mode_available(env={}) is True
    assert runtime_module.research_mode_available(env={'BOXFOX_RESEARCH_MODE': 'off'}) is False
    monkeypatch.setenv(limits.RESEARCH_MODE_ENV, 'off')
    assert runtime_module.research_mode_available() is False
    store = SessionStore(tmp_path / 'unavailable.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30})['id']

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                async with http.put(str(server.make_url(f'/api/agent/sessions/{sid}/research-mode')),
                                    json={'on': True}) as resp:
                    return resp.status, await resp.json()

    status, body = asyncio.run(run())
    store.close()
    assert status == 409
    assert body['code'] == limits.RESEARCH_MODE_UNAVAILABLE_CODE


def test_f5_the_background_run_block_is_appended_exactly_once_per_turn(harness):
    """F5: khối run nền phải được GỠ trước khi nối — đo sống trước khi vá: 1, 2, 3 lần."""
    store, runtime, sid = harness
    store.research_job_save('run-bg-block', sid, {'origin': 'mode', 'phase': 'searching',
                                                  'background': True, 'budgetSeconds': 600,
                                                  'questions': []}, status='researching')
    counts = []
    for _ in range(3):
        session = session_of(store, sid)
        runtime._sync_mode_block(session)
        store.save(sid, session['messages'])
        counts.append(store.get(sid)['messages'][0]['content'].count(
            limits.RESEARCH_BACKGROUND_BLOCK_MARKER))
    assert counts == [1, 1, 1], f'khối run nền bị chất đống: {counts}'


def test_f5_the_handoff_block_disappears_after_it_is_delivered_once(harness):
    """F5 (nửa bàn giao): giao một lần rồi phải biến mất khỏi prompt, không nằm lại vĩnh viễn."""
    store, runtime, sid = harness
    store.research_job_save('run-hand', sid, {'origin': 'mode', 'phase': 'done', 'budgetSeconds': 600,
                                              'tier': 2, 'reviewModes': ['critique'], 'questions': [],
                                              'goal': 'X', 'scope': {'revision': 1}}, status='partial')
    store.record_dossier(sid, 'run-hand', 1, '.research/run-hand/v1.md', quality_ok=True)
    session = session_of(store, sid)
    runtime._sync_mode_block(session)
    store.save(sid, session['messages'])
    assert limits.RESEARCH_HANDOFF_BLOCK_MARKER in store.get(sid)['messages'][0]['content']
    session = session_of(store, sid)
    runtime._sync_mode_block(session)
    store.save(sid, session['messages'])
    assert limits.RESEARCH_HANDOFF_BLOCK_MARKER not in store.get(sid)['messages'][0]['content'], \
        'bàn giao xong thì khối cũ phải bị gỡ'


def _background_job(store, sid, research_id, state):
    store.research_job_save(research_id, sid, {'origin': 'mode', 'background': True,
                                               'budgetSeconds': 600, 'questions': [], **state},
                            status='researching')


def test_f6_the_pump_ending_on_the_budget_floor_still_emits_the_report_and_the_notice(harness):
    """F6: bơm cạn ngân sách ghi `partial` thẳng ⇒ phải đi qua cửa kết thúc duy nhất."""
    store, runtime, sid = harness
    _background_job(store, sid, 'run-floor', {'phase': 'searching', 'budgetSeconds': 0})
    asyncio.run(research_continuation_step(runtime))
    job = store.research_job('run-floor')
    assert job['status'] == 'partial'
    assert job['state']['background'] is False, 'cờ nền phải tắt, nếu không bơm chạy lại phần đã xong'
    kinds = [row['type'] for row in store.events(sid)]
    assert 'research_report' in kinds and 'research_notice' in kinds


def test_f6_the_pump_ending_on_a_stall_still_emits_the_report_and_the_notice(harness):
    """F6 (đường đứng yên): hai lượt bơm không tiến được cũng phải kết thúc QUA CỬA."""
    store, runtime, sid = harness
    _background_job(store, sid, 'run-stall', {'phase': 'searching', 'lastProgress': [0, 0, 0, 0],
                                              'stalledTurns': 1, 'lastContinuationAt': 0})
    asyncio.run(research_continuation_step(runtime))
    job = store.research_job('run-stall')
    assert job['status'] == 'partial'
    assert job['state']['background'] is False
    kinds = [row['type'] for row in store.events(sid)]
    assert 'research_report' in kinds and 'research_notice' in kinds


def test_f7_with_background_runs_off_turning_the_mode_off_always_pauses_and_offers_no_choice(harness, monkeypatch):
    """F7: công tắc `BOXFOX_RESEARCH_BACKGROUND_RUNS=off` ⇒ thoát mode luôn tạm dừng, không mời lựa chọn."""
    store, runtime, sid = harness
    monkeypatch.setenv(limits.RESEARCH_BACKGROUND_RUNS_ENV, 'off')
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-pause-only', sid, {'origin': 'mode', 'phase': 'searching',
                                                    'budgetSeconds': 600, 'questions': []},
                            status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-pause-only'
    store.update_config(sid, config)
    result = research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': False})
    assert result['on'] is False
    assert store.research_job('run-pause-only')['status'] == 'paused'
    # Gửi thẳng lựa chọn "chạy nền" cũng bị hạ về tạm dừng — không có đường chạy nền khi công tắc tắt.
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-pause-only', sid, {'origin': 'mode', 'phase': 'searching',
                                                   'budgetSeconds': 600, 'questions': []},
                            status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-pause-only'
    store.update_config(sid, config)
    research_runtime.apply_research_mode(runtime, session_of(store, sid),
                                        {'on': False, 'exitChoice': 'background'})
    assert store.research_job('run-pause-only')['state']['background'] is False
    assert store.research_job('run-pause-only')['status'] == 'paused'


def test_f7_the_off_command_pauses_when_background_runs_are_off(harness, monkeypatch):
    """F7 (cửa lệnh): `/research off` không phát lời hỏi thoát khi không còn lựa chọn chạy nền."""
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    asyncio.run(runtime.submit(sid, '/research'))
    monkeypatch.setenv(limits.RESEARCH_BACKGROUND_RUNS_ENV, 'off')
    store.research_job_save('run-off', sid, {'origin': 'mode', 'phase': 'searching',
                                             'budgetSeconds': 600, 'questions': []}, status='researching')
    result = asyncio.run(runtime.submit(sid, '/research off'))
    assert session_of(store, sid)['config']['researchMode']['on'] is False
    assert result['status'] == 'idle'
    assert store.research_job('run-off')['status'] == 'paused'
    assert model.calls == 0, 'lệnh điều khiển không gọi mô hình'


def test_f8_the_pump_turn_gets_the_research_block_not_the_background_one(harness):
    """F8: `_sync_mode_block` phải truyền id lượt, nếu không lượt bơm nhận khối main."""
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    _background_job(store, sid, 'run-pump', {'phase': 'searching'})
    run_turn(runtime, sid, 'tiếp tục run', invocation_id='research-resume-run-pump-1')
    content = session_of(store, sid)['messages'][0]['content']
    assert limits.RESEARCH_MODE_BLOCK_MARKER in content, 'lượt bơm phải dùng khối hồ sơ research'
    assert limits.RESEARCH_BACKGROUND_BLOCK_MARKER not in content
    store.research_job_save('run-pump', sid, {'origin': 'mode', 'phase': 'searching',
                                              'background': True, 'budgetSeconds': 600, 'questions': []},
                            status='researching')
    run_turn(runtime, sid, 'lượt người dùng')
    content = session_of(store, sid)['messages'][0]['content']
    assert limits.RESEARCH_MODE_BLOCK_MARKER not in content, 'lượt thường của main không mang khối mode'
    assert limits.RESEARCH_BACKGROUND_BLOCK_MARKER in content


def test_f9_the_mode_only_delegates_to_the_research_roles(harness):
    """F9: trong mode chỉ `research`/`research-review`/`explore` được giao nhánh."""
    store, runtime, sid = harness
    session = session_of(store, sid)
    session['config']['subagents'] = [{'id': 'build', 'enabled': True},
                                      {'id': 'research', 'enabled': True}]
    store.update_config(sid, session['config'])
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    session = session_of(store, sid)
    with pytest.raises(PermissionError, match='RESEARCH_MODE_DELEGATE_ROLE'):
        asyncio.run(runtime.delegate(session, {'role': 'build', 'goal': 'viết code'}))
    # Vai được phép thì KHÔNG bị chặn ở cửa này (chỉ cần vượt qua kiểm tra vai).
    with pytest.raises(ValueError, match='Child goal required'):
        asyncio.run(runtime.delegate(session, {'role': 'research', 'goal': '   '}))


def test_f9_the_exit_choice_prompt_uses_one_question_id(harness):
    """F9 (id lời hỏi): đường API và đường lệnh phải cùng một id câu hỏi thoát."""
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    store.research_job_save('run-exit', sid, {'origin': 'mode', 'phase': 'searching',
                                              'budgetSeconds': 600, 'questions': []}, status='researching')
    config = session_of(store, sid)['config']
    config['researchMode']['activeRunId'] = 'run-exit'
    store.update_config(sid, config)
    with pytest.raises(ValueError) as caught:
        research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': False})
    prompt = caught.value.payload['prompt']
    assert prompt['questions'][0]['id'] == 'exit'
    assert runtime._exit_choice_prompt(store.research_job('run-exit'))['questions'][0]['id'] == 'exit'


def test_f10_a_card_answered_after_the_scope_was_rewritten_is_refused(harness):
    """F10: khoá lạc quan so với revision SỐNG của phạm vi, không phải revision đóng băng trong prompt."""
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    scope_job(store, sid)
    asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                 {'action': 'ask', 'researchId': 'run-scope', 'questions': [
                                     {'id': 'iq1', 'text': 'Dùng để làm gì?', 'blocking': True,
                                      'options': [{'id': 'o1', 'label': 'Dùng ngay'}]}]}))
    job = store.research_job('run-scope')
    prompt = job['state']['prompts'][0]
    # Phạm vi bị viết lại SAU khi thẻ được tạo ⇒ revision SỐNG tăng, revision của thẻ đứng yên.
    state = dict(job['state'])
    state['scope'] = {**state['scope'], 'revision': int(state['scope']['revision']) + 1}
    store.research_job_save('run-scope', sid, state, status=job['status'])
    job = store.research_job('run-scope')
    assert job['state']['scope']['revision'] != prompt['revision']
    with pytest.raises(ValueError, match=limits.RESEARCH_SCOPE_REVISION_STALE_CODE):
        research_runtime.answer_prompt(runtime, sid, job, {
            'promptId': prompt['promptId'], 'revision': prompt['revision'], 'start': True,
            'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    done = research_runtime.answer_prompt(runtime, sid, store.research_job('run-scope'), {
        'promptId': prompt['promptId'], 'revision': job['state']['scope']['revision'],
        'start': True, 'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    assert done['resume'] is True


def test_d6_an_open_card_answers_after_the_owner_edits_the_scope(harness):
    """D-6 (vòng kiểm thử P2–P5): sửa thẻ phạm vi KHÔNG được làm thẻ phỏng vấn 409 vĩnh viễn.

    Trước bản vá, `scope_update` tăng revision SỐNG mà không ghim lại `prompt['revision']`: giao diện
    tải lại thẻ vẫn nhận con số CŨ, nên mọi câu trả lời đều 409 `RESEARCH_SCOPE_REVISION_STALE` — và
    không có sự kiện nào phát lại thẻ để nó biết số mới. Luật F10 vẫn nguyên: thẻ trong DOM CŨ bị từ chối.
    """
    store, runtime, sid = harness
    research_runtime.apply_research_mode(runtime, session_of(store, sid), {'on': True})
    scope_job(store, sid)
    asyncio.run(runtime.dispatch(session_of(store, sid), 'research_scope',
                                 {'action': 'ask', 'researchId': 'run-scope', 'questions': [
                                     {'id': 'iq1', 'text': 'Dùng để làm gì?', 'blocking': True,
                                      'options': [{'id': 'o1', 'label': 'Dùng ngay'}]}]}))
    before = store.research_job('run-scope')
    prompt = before['state']['prompts'][0]
    live = int(before['state']['scope']['revision'])
    assert prompt['revision'] == live, 'thẻ mới phải mang revision SỐNG của phạm vi'
    edited = research_runtime.scope_update(runtime, sid, before,
                                           {'revision': live,
                                            'scope': {'goal': {'text': 'mục tiêu mới'}}})
    assert edited['revision'] == live + 1
    # Giao diện tải lại thẻ (vòng 1200 ms đọc lại `prompts`) ⇒ thẻ mang revision MỚI.
    assert store.research_job('run-scope')['state']['prompts'][0]['revision'] == live + 1
    # DOM cũ: vẫn gửi con số CŨ ⇒ bị từ chối đúng luật F10.
    with pytest.raises(ValueError, match=limits.RESEARCH_SCOPE_REVISION_STALE_CODE):
        research_runtime.answer_prompt(runtime, sid, store.research_job('run-scope'), {
            'promptId': prompt['promptId'], 'revision': live, 'start': True,
            'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    done = research_runtime.answer_prompt(runtime, sid, store.research_job('run-scope'), {
        'promptId': prompt['promptId'], 'revision': live + 1, 'start': True,
        'answers': [{'questionId': 'iq1', 'optionId': 'o1'}]})
    assert done['resume'] is True and done['unanswered'] == []


LONG_EXCERPT = ('Mức hưởng chuyển tuyến bảo hiểm y tế được quy định theo tuyến và theo từng nhóm '
                'đối tượng, kèm danh mục giấy tờ phải nộp. ') * 2


def test_the_ledger_list_keeps_the_run_filter_when_the_run_has_no_rows_yet(harness):
    """Rò rỉ (mục 'nhỏ'): run mới chưa có dòng nào KHÔNG được hiện dòng của run khác."""
    store, runtime, sid = harness
    session = session_of(store, sid)
    session['config']['research'] = {'researchId': 'run-a'}
    store.update_config(sid, session['config'])
    asyncio.run(runtime.dispatch(session_of(store, sid), 'source_add',
                                 {'claim': 'x', 'url': 'https://moh.gov.vn/a', 'excerpt': LONG_EXCERPT}))
    session = session_of(store, sid)
    session['config']['research'] = {'researchId': 'run-b'}
    store.update_config(sid, session['config'])
    listed = asyncio.run(runtime.dispatch(session_of(store, sid), 'source_list', {}))
    assert listed['rows'] == [], 'sổ của run mới không được mang dòng của run khác'



# ------------------------------------- khối prompt: thay chứ không xếp chồng (B-2, B-3, F5)


def test_the_background_block_is_replaced_each_turn_not_stacked(harness, monkeypatch):
    """Vòng soát 2 (lỗ B-3/F5): khối run nền từng bị nối thêm mỗi lượt — đo được `[1, 2, 3]` và
    prompt phình 321 ký tự mỗi lượt. Bài này kiểm trên đúng đường prompt hệ thống."""
    store, runtime, sid = harness
    session = session_of(store, sid)
    session['messages'] = [{'role': 'system', 'content': 'NỀN === ANSWER LENGTH ===\nngắn'}]
    block = (f'{limits.RESEARCH_BACKGROUND_BLOCK_MARKER}\nrun nền đang chạy\n'
             f'{limits.RESEARCH_BACKGROUND_BLOCK_END}')
    monkeypatch.setattr(runtime, 'turn_profile',
                        lambda s, invocation_id=None: {'mode': 'off', 'tools': [],
                                                       'promptBlock': block})
    monkeypatch.setattr(runtime, 'research_handoff', lambda s, prompt='': None)
    sizes = []
    for _ in range(3):
        runtime._sync_mode_block(session)
        text = session['messages'][0]['content']
        assert text.count(limits.RESEARCH_BACKGROUND_BLOCK_MARKER) == 1
        sizes.append(len(text))
    assert sizes == [sizes[0]] * 3, f'prompt phình theo lượt: {sizes}'
    assert '=== ANSWER LENGTH ===' in session['messages'][0]['content']


def test_the_handoff_block_disappears_after_it_is_delivered(harness, monkeypatch):
    """Vòng soát 2 (lỗ B-2): khối bàn giao từng ở lại mãi, nên bằng chứng `partial` cũ nằm cạnh
    bản `completed` mới. Sau khi giao, lượt sau không được còn khối ấy."""
    store, runtime, sid = harness
    session = session_of(store, sid)
    session['messages'] = [{'role': 'system', 'content': 'NỀN'}]
    block = (f'{limits.RESEARCH_HANDOFF_BLOCK_MARKER}\nhồ sơ v3\n'
             f'{limits.RESEARCH_HANDOFF_BLOCK_END}')
    delivered: list[tuple[str, str]] = []
    monkeypatch.setattr(runtime, 'turn_profile',
                        lambda s, invocation_id=None: {'mode': 'off', 'tools': [], 'promptBlock': ''})
    seen: list[str] = []

    def fake_handoff(s, prompt=''):
        seen.append(prompt)
        return {'block': block, 'researchId': 'r-ho', 'version': 3}

    monkeypatch.setattr(runtime, 'research_handoff', fake_handoff)
    monkeypatch.setattr(runtime, 'mark_handoff_delivered',
                        lambda s, rid, version: delivered.append((rid, version)))
    runtime._sync_mode_block(session, None, 'Lập plan dựa trên báo cáo research r-ho v3')
    assert session['messages'][0]['content'].count(limits.RESEARCH_HANDOFF_BLOCK_MARKER) == 1
    assert delivered == [('r-ho', 3)]
    # Vòng 2 (D-5) + D-8: khối bàn giao nhận ĐÚNG lượt đang dựng — không phải `messages[0]` (prompt hệ thống).
    assert seen == ['Lập plan dựa trên báo cáo research r-ho v3']
    monkeypatch.setattr(runtime, 'research_handoff', lambda s, prompt='': None)
    runtime._sync_mode_block(session)
    assert limits.RESEARCH_HANDOFF_BLOCK_MARKER not in session['messages'][0]['content']
    assert 'NỀN' in session['messages'][0]['content']


# ------------------------- khối bàn giao theo ĐÚNG run mà lượt nói tên (vòng 2, D-5)


def test_a_turn_that_names_a_run_gets_that_run_not_the_newest_one(harness):
    """Review vòng kiểm thử P2–P5 (D-5): khối bàn giao phải theo ĐÚNG run mà lượt nói tên.

    Trước bản vá, `research_handoff` luôn lấy run chưa bàn giao MỚI NHẤT, nên bấm "Dùng cho plan"
    ở thẻ của run cũ lại bàn giao một run khác trong khi câu lệnh vẫn nói tên run cũ.
    """
    store, runtime, sid = harness
    for run_id, version in (('run-cu', 2), ('run-moi', 1)):
        store.research_job_save(run_id, sid, {'origin': 'mode', 'phase': 'done', 'tier': 2,
                                             'budgetSeconds': 600, 'questions': []},
                                status='completed')
        store.record_dossier(sid, run_id, version, f'.research/{run_id}/v{version}-{run_id}.md',
                             quality_ok=True)
    older = runtime.research_handoff(session_of(store, sid),
                                     'Lập plan dựa trên báo cáo research run-cu v2')
    assert older is not None and older['researchId'] == 'run-cu' and older['version'] == 2
    newer = runtime.research_handoff(session_of(store, sid),
                                     'Lập plan dựa trên báo cáo research run-moi v1')
    assert newer is not None and newer['researchId'] == 'run-moi'


def test_a_turn_that_names_a_delivered_run_gets_no_second_block(harness):
    """Bản hồ sơ ĐÃ bàn giao thì lượt nhắc lại nó không được kéo theo run khác (§5.10, D-5)."""
    store, runtime, sid = harness
    for run_id in ('run-cu', 'run-moi'):
        store.research_job_save(run_id, sid, {'origin': 'mode', 'phase': 'done', 'tier': 2,
                                             'budgetSeconds': 600, 'questions': []},
                                status='completed')
        store.record_dossier(sid, run_id, 1, f'.research/{run_id}/v1-{run_id}.md', quality_ok=True)
    first = runtime.research_handoff(session_of(store, sid), 'báo cáo research run-cu v1')
    assert first is not None and first['researchId'] == 'run-cu'
    runtime.mark_handoff_delivered(session_of(store, sid), 'run-cu', 1)
    assert runtime.research_handoff(session_of(store, sid), 'báo cáo research run-cu v1') is None, \
        'bản đã bàn giao không được thay bằng một run khác'
    # Lượt KHÔNG nói tên run nào vẫn theo luật cũ: bàn giao run chưa bàn giao.
    other = runtime.research_handoff(session_of(store, sid))
    assert other is not None and other['researchId'] == 'run-moi'


def test_a_turn_that_names_an_unknown_run_keeps_the_old_behaviour(harness):
    """Tên run không có trong phiên ⇒ về đúng luật cũ (`r-2` không được khớp trong `r-22`)."""
    store, runtime, sid = harness
    store.research_job_save('run-that', sid, {'origin': 'mode', 'phase': 'done', 'tier': 2,
                                             'budgetSeconds': 600, 'questions': []},
                            status='completed')
    store.record_dossier(sid, 'run-that', 1, '.research/run-that/v1.md', quality_ok=True)
    handoff = runtime.research_handoff(session_of(store, sid),
                                       'Lập plan dựa trên báo cáo research khong-co-run-nao v9')
    assert handoff is not None and handoff['researchId'] == 'run-that'
    # Token hoá: `r-2` KHÔNG được khớp khi phiên chỉ có `r-22` (so `in` thô sẽ sai).
    store.research_job_save('r-22', sid, {'origin': 'mode', 'phase': 'done', 'tier': 2,
                                         'budgetSeconds': 600, 'questions': []}, status='completed')
    store.record_dossier(sid, 'r-22', 1, '.research/r-22/v1.md', quality_ok=True)
    assert runtime.named_handoff_run(session_of(store, sid), 'run r-2 v1') == ''
    assert runtime.named_handoff_run(session_of(store, sid), 'run r-22 v1') == 'r-22'


def test_d8_the_handoff_block_follows_the_user_turn_not_the_system_prompt(harness):
    """D-8 (vòng kiểm thử P2–P5 lần 3): khối bàn giao phải theo LƯỢT NGƯỜI DÙNG đang dựng.

    Đo sống: `messages[0]` là PROMPT HỆ THỐNG (nơi khối ACTIVE MODE/ENABLED SKILLS được chèn) và không
    chứa token `r-<n>` nào — nên bản vá D-5 ở `75a24b2` không bao giờ được dùng tới: mọi lượt rơi về
    luật "run chưa bàn giao mới nhất", nút "Dùng cho plan" ở thẻ của run CŨ bàn giao run KHÁC, và cổng
    "một lần" của `f658868` không bao giờ đóng cho thẻ ấy (bấm lần hai lại gửi thêm một lượt plan).
    """
    store, runtime, sid = harness
    for run_id, version in (('run-cu', 2), ('run-moi', 1)):
        store.research_job_save(run_id, sid, {'origin': 'mode', 'phase': 'done', 'tier': 2,
                                             'budgetSeconds': 600, 'questions': []},
                                status='completed')
        store.record_dossier(sid, run_id, version, f'.research/{run_id}/v{version}-{run_id}.md',
                             quality_ok=True)
    session = session_of(store, sid)
    # Prompt hệ thống ĐÚNG như thật: khối mode + khối kỹ năng, KHÔNG có tên run nào.
    session['messages'] = [{'role': 'system', 'content':
                            f'{limits.RESEARCH_MODE_BLOCK_MARKER}\nchế độ research\n'
                            f'{limits.RESEARCH_MODE_BLOCK_END}\n\n'
                            '=== ENABLED SKILLS ===\nresearch-team'}]
    store.save(sid, session['messages'])
    runtime._next_turn_skills(session, [], None, 'Lập plan dựa trên báo cáo research run-cu v2')
    content = store.get(sid)['messages'][0]['content']
    assert limits.RESEARCH_HANDOFF_BLOCK_MARKER in content
    assert 'run-cu' in content, 'khối bàn giao phải nói tên run mà LƯỢT nêu, không phải run mới nhất'
    mode = (store.get(sid)['config'] or {}).get('researchMode') or {}
    assert mode.get('handoffDeliveredVersion') == {'run-cu': '2'}

    # Lượt sau nhắc LẠI đúng run ấy: bản đã bàn giao ⇒ KHÔNG có khối nào (cổng "một lần" của thẻ đóng).
    session = session_of(store, sid)
    runtime._next_turn_skills(session, [], None, 'Lập plan dựa trên báo cáo research run-cu v2')
    content = store.get(sid)['messages'][0]['content']
    assert limits.RESEARCH_HANDOFF_BLOCK_MARKER not in content, \
        'lượt nhắc lại bản đã bàn giao không được kéo theo run khác'
    assert mode.get('handoffDeliveredVersion') == {'run-cu': '2'}

    # Lượt KHÔNG nói tên run nào: về đúng luật cũ — bàn giao run chưa bàn giao mới nhất.
    session = session_of(store, sid)
    runtime._next_turn_skills(session, [], None, 'Viết plan đi')
    assert 'run-moi' in store.get(sid)['messages'][0]['content']
