"""Vỏ mode `/design` của P1 (plan v1 §7, hợp đồng design-interfaces §2–§6).

Nhóm D của plan (§8 P1) chạy tất định trong CI: không mạng, không gọi mô hình thật. Mọi hành vi mới
nằm sau công tắc `BOXFOX_DESIGN_MODE` — tệp này bật công tắc bằng `monkeypatch`, và bài cuối chứng
minh công tắc TẮT thì `/design` quay về đúng lệnh VAI cũ.
"""
from __future__ import annotations

import asyncio

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core import runtime as runtime_module
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore
from agentbox.skills.catalog import SkillCatalog
from agentbox.skills.commands import CommandRegistry

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
    """Đếm số lượt đã chạy — D-01/D-03/D-04 khẳng định KHÔNG gọi mô hình."""

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
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
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
    async def main():
        await runtime.submit(sid, prompt, invocation_id=invocation_id)
        task = runtime.tasks.get(sid)
        if task is not None:
            await task

    asyncio.run(main())


# ------------------------------------------------------------------ D-01


def test_d01_turning_the_toggle_on_changes_the_config_and_sends_no_turn(harness):
    store, runtime, sid = harness
    result = design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    assert result['on'] is True and result['prompt'] is None
    config = session_of(store, sid)['config']
    assert config['designMode']['on'] is True
    assert config['designMode']['enteredBy'] == 'toggle'
    assert events(store, sid, limits.DESIGN_MODE_EVENT_CODE) == [
        {'on': True, 'by': 'toggle', 'activeRunId': None, 'revision': 1}]
    assert sid not in runtime.tasks, 'D-01: bật mode không gửi lượt nào'
    assert not store.design_jobs_for(sid), 'D-01: bật mode không mở run'


# ------------------------------------------------------------------ D-02 / D-03 / D-04


def test_d02_slash_design_with_text_is_a_mode_command_that_opens_a_run(harness):
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    registry = CommandRegistry(store, SkillCatalog())
    resolved = registry.resolve('/design thiết kế lại màn hình chat', subagents=[])
    assert resolved.kind == 'mode' and resolved.command == 'design'
    assert resolved.prompt == 'thiết kế lại màn hình chat'
    run_turn(runtime, sid, '/design thiết kế lại màn hình chat')
    assert session_of(store, sid)['config']['designMode']['on'] is True
    jobs = store.design_jobs_for(sid)
    assert len(jobs) == 1 and jobs[0]['state']['origin'] == 'mode'
    assert model.calls == 1, 'lệnh có nội dung mở đúng một lượt'
    assert limits.DESIGN_MODE_BLOCK_MARKER in session_of(store, sid)['messages'][0]['content']


def test_d03_bare_slash_design_turns_the_mode_on_without_a_turn_or_a_run(harness):
    store, runtime, sid = harness
    model = RecordingModel()
    runtime.client = model
    result = asyncio.run(runtime.submit(sid, '/design'))
    assert result['status'] == 'idle'
    assert session_of(store, sid)['config']['designMode']['on'] is True
    assert model.calls == 0
    assert sid not in runtime.tasks, 'D-03: `/design` rỗng KHÔNG tạo lượt'
    assert not store.design_jobs_for(sid), 'D-03: `/design` rỗng KHÔNG mở run'


def test_d04_slash_design_status_replays_the_card_without_a_model_call(harness):
    store, runtime, sid = harness
    asyncio.run(runtime.submit(sid, '/design'))
    design_runtime.new_design_job(runtime, sid, 'thiết kế màn hình Bảng điều khiển')
    model = RecordingModel()
    runtime.client = model
    result = asyncio.run(runtime.submit(sid, '/design status'))
    assert result['status'] == 'idle'
    assert model.calls == 0, 'D-04: `/design status` không gọi mô hình'
    card = events(store, sid, 'design_run')[-1]
    assert card['kind'] == 'status' and card['message'].startswith('d-')


# ------------------------------------------------------------------ D-05


def test_d05_delegating_to_the_design_role_opens_a_run_with_origin_delegate(harness):
    store, runtime, sid = harness
    runtime.client = RecordingModel()
    session = session_of(store, sid)
    session['config']['subagents'] = [{'id': 'design', 'enabled': True}]
    store.update_config(sid, session['config'])
    assert runtime_module.design_mode(session_of(store, sid))['on'] is False
    asyncio.run(runtime.delegate(session_of(store, sid),
                                 {'role': 'design', 'goal': 'thiết kế màn hình Thanh bên'}))
    jobs = store.design_jobs_for(sid)
    assert len(jobs) == 1
    assert jobs[0]['state']['origin'] == 'delegate'


# ------------------------------------------------------------------ D-06


def test_d06_a_vague_brief_opens_an_interview_and_a_clear_one_does_not(harness):
    store, runtime, sid = harness
    run_turn(runtime, sid, '/design thiết kế một giao diện chat')
    jobs = store.design_jobs_for(sid)
    assert len(jobs) == 1
    prompts = jobs[0]['state']['prompts']
    assert [p['kind'] for p in prompts] == ['interview']
    questions = prompts[0]['questions']
    assert 1 <= len(questions) <= limits.DESIGN_INTERVIEW_MAX_QUESTIONS
    assert 'dq-screen' in [q['id'] for q in questions]
    assert all(2 <= len(q['options']) <= 5 for q in questions)
    interview_events = events(store, sid, 'design_prompt')
    assert interview_events[0]['kind'] == 'interview'

    # Brief đã đủ dữ kiện (thiết kế lại + đường dẫn tệp đích) ⇒ KHÔNG mở lời hỏi nào.
    run_turn(runtime, sid, '/design thiết kế lại màn hình chat ở src/ui/ChatPanel.tsx')
    clear = [job for job in store.design_jobs_for(sid)
             if str((job['state'].get('brief') or {}).get('path') or '')]
    assert clear and not clear[0]['state']['prompts'], 'brief rõ KHÔNG được hỏi'


# ------------------------------------------------------------------ D-07


def test_d07_updating_the_brief_bumps_the_revision_and_rejects_the_old_one(harness):
    store, runtime, sid = harness
    run_turn(runtime, sid, '/design thiết kế lại màn hình chat')
    job = store.design_jobs_for(sid)[0]
    before = job['revision']
    result = design_runtime.design_scope(runtime, sid, job, 'update',
                                         {'screen': 'màn hình chat', 'revision': before})
    assert result['revision'] == before + 1
    with pytest.raises(ValueError, match=limits.DESIGN_TOUCH_LIST_REVISION_STALE_CODE):
        design_runtime.design_scope(runtime, sid, store.design_job(job['design_id']), 'update',
                                    {'screen': 'màn hình khác', 'revision': before})


# ------------------------------------------------------------------ D-08


def test_d08_every_write_is_refused_before_the_touch_list_is_approved(harness):
    store, runtime, sid = harness
    run_turn(runtime, sid, '/design thiết kế lại màn hình chat')
    job = store.design_jobs_for(sid)[0]
    session = session_of(store, sid)
    config = dict(session['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)

    async def call():
        return await runtime.dispatch(store.get(sid), 'design_write',
                                      {'path': 'src/ui/ChatPanel.tsx', 'content': 'x', 'mode': 'create'})

    with pytest.raises(ValueError, match=limits.DESIGN_TOUCH_LIST_REQUIRED_CODE):
        asyncio.run(call())

    # Duyệt danh sách rồi thì cổng danh sách mở — nhưng P1 chưa có nhánh thiết kế (P3), nên lần ghi
    # kế tiếp bị chối vì lý do THẬT: chưa có nhánh để ghi vào.
    design_runtime.design_touch_list_store(runtime, sid, store.design_job(job['design_id']),
                                          [{'kind': 'new', 'path': 'src/ui/ChatPanel.tsx',
                                            'reason': 'màn hình chat mới', 'risk': 'low'}])
    approved = design_runtime.design_touch_list_approve(
        runtime, sid, store.design_job(job['design_id']),
        store.design_job(job['design_id'])['state']['touchList']['revision'])
    assert approved['approved'] == 1
    with pytest.raises(ValueError, match=limits.DESIGN_BRANCH_REQUIRED_CODE):
        asyncio.run(call())


# ------------------------------------------------------------------ Cổng mode (§4)


def test_the_design_tools_are_refused_outside_the_mode(harness):
    store, runtime, sid = harness
    run_turn(runtime, sid, '/design thiết kế lại màn hình chat')
    session = session_of(store, sid)
    config = dict(session['config'])
    config['designMode'] = {**config['designMode'], 'on': False}
    store.update_config(sid, config)

    async def call():
        return await runtime.dispatch(store.get(sid), 'design_scope', {'action': 'propose'})

    with pytest.raises(ValueError, match=limits.DESIGN_MODE_REQUIRED_CODE):
        asyncio.run(call())
    # Ngoài mode, hồ sơ lượt KHÔNG mang công cụ design và không mang khối mode.
    profile = runtime.turn_profile(store.get(sid))
    assert profile['mode'] == 'main'
    assert not (set(profile['tools']) & set(limits.DESIGN_TOOL_FAMILY))


def test_the_design_profile_swaps_tools_and_prompt_block(harness):
    store, runtime, sid = harness
    run_turn(runtime, sid, '/design thiết kế lại màn hình chat')
    session = session_of(store, sid)
    profile = runtime.turn_profile(session)
    assert profile['mode'] == 'design'
    assert set(limits.DESIGN_TOOL_FAMILY) & set(profile['tools']) == set(design_runtime.WIRED_DESIGN_TOOLS)
    assert not (set(profile['tools']) & set(limits.DESIGN_MODE_EXCLUDED_TOOLS))
    assert profile['promptBlock'].startswith(limits.DESIGN_MODE_BLOCK_MARKER)
    assert profile['promptBlock'].rstrip().endswith(limits.DESIGN_MODE_BLOCK_END)


# ------------------------------------------------------------------ Tuyến HTTP (§5)


def test_the_design_routes_serve_the_run_and_the_exit_choice(harness):
    store, runtime, sid = harness

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                async with http.put(str(server.make_url(f'/api/agent/sessions/{sid}/design-mode')),
                                    json={'on': True, 'by': 'toggle'}) as resp:
                    assert resp.status == 200
                    enabled = await resp.json()
                async with http.put(str(server.make_url(f'/api/agent/sessions/{sid}/design-mode')),
                                    json={'on': False}) as off:
                    assert off.status == 200
                    disabled = await off.json()
                # `store` sống trong suốt phiên của server; đọc sự kiện NGAY TẠI ĐÂY, trước khi
                # `create_app` dọn dẹp và đóng store.
                recorded = events(store, sid, limits.DESIGN_MODE_EVENT_CODE)
            return enabled, disabled, recorded

    enabled, disabled, recorded = asyncio.run(run())
    assert enabled['on'] is True and disabled['on'] is False
    assert [event['on'] for event in recorded] == [True, False]


def test_the_put_route_answers_409_with_the_exit_choice_prompt(harness):
    store, runtime, sid = harness
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế màn hình Bảng điều khiển')
    config = dict(session_of(store, sid)['config'])
    config['designMode'] = {**config['designMode'], 'activeRunId': job['design_id']}
    store.update_config(sid, config)

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                async with http.put(str(server.make_url(f'/api/agent/sessions/{sid}/design-mode')),
                                    json={'on': False}) as resp:
                    status, body = resp.status, await resp.json()
                still_on = runtime_module.design_mode(store.get(sid))['on']
            return status, body, still_on

    status, body, still_on = asyncio.run(run())
    assert status == 409
    assert body['code'] == limits.DESIGN_EXIT_CHOICE_REQUIRED_CODE
    assert body['prompt']['kind'] == 'exit-choice'
    assert len(body['prompt']['questions'][0]['options']) == 2
    assert still_on is True, 'mode KHÔNG đổi'


def test_the_run_list_and_touch_list_approval_routes(harness):
    store, runtime, sid = harness
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế lại màn hình chat')

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                async with http.get(str(server.make_url(f'/api/agent/design/runs?sessionId={sid}'))) as resp:
                    assert resp.status == 200
                    listing = await resp.json()
                async with http.get(str(server.make_url(f'/api/agent/design/runs/{job["design_id"]}'))) as resp:
                    assert resp.status == 200
                    detail = await resp.json()
                async with http.patch(str(server.make_url(f'/api/agent/design/runs/{job["design_id"]}')),
                                      json={'action': 'touch-list',
                                            'items': [{'kind': 'new', 'path': 'src/ui/Chat.tsx',
                                                       'reason': 'vỏ chat', 'risk': 'low'}]}) as resp:
                    assert resp.status == 200
                    stored = await resp.json()
                async with http.post(str(server.make_url(
                        f'/api/agent/design/runs/{job["design_id"]}/touch-list/approve')),
                        json={'revision': stored['revision']}) as resp:
                    assert resp.status == 200
                    approved = await resp.json()
            return listing, detail, approved

    listing, detail, approved = asyncio.run(run())
    assert [item['designId'] for item in listing['runs']] == [job['design_id']]
    assert detail['job']['phase'] == 'interviewing'
    assert approved['approved'] == 1


# ------------------------------------------------------------------ Công tắc tắt (byte-identical)


def test_switching_the_feature_off_keeps_the_old_role_command_and_no_design_tools(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'off')
    assert runtime_module.design_mode_available() is False
    assert design_runtime.design_mode_available(env={'BOXFOX_DESIGN_MODE': 'off'}) is False
    store = SessionStore(tmp_path / 'off.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30})['id']
    registry = CommandRegistry(store, SkillCatalog())
    resolved = registry.resolve('/design specify contracts', subagents=[{'id': 'design'}])
    store.close()
    assert resolved.kind == 'task' and resolved.role == 'design', '/design là lệnh VAI khi tắt'
