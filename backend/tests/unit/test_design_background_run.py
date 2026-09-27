"""Finding 2 — lượt BƠM của run nền vẫn phải dùng được họ công cụ design.

Chủ nhà chọn "Tiếp tục chạy nền" ở lời hỏi thoát chế độ (`mode.on=False`, `state.background=True`);
`design_job_pumpable` cố ý bơm run ấy, và `turn_profile` cấp họ công cụ design cho lượt
`design-resume-*` — nhưng cổng cứng ở `dispatch` từng chối mọi lời gọi vì mode đã tắt, nên run nền
chết ngay khi cất cánh. Bài này chạy TRỌN đường: bật mode → mở run → chủ nhà chọn chạy nền →
`design_continuation_step` → mô hình giả GỌI một công cụ design trong lượt bơm → lượt thường vẫn bị
chối như cũ.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import design_continuation_step, design_job_pumpable
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    async def execute(self, name, args, sid, **_identity):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


class DesignToolCaller:
    """Lượt đầu của mỗi lượt mô hình: gọi `design_scope(action='propose')`, rồi trả lời xong."""

    def __init__(self):
        self.calls = 0
        self.offered = []

    async def model_metadata_map(self):
        return {}

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls += 1
        self.offered.append([schema['function']['name'] for schema in tools])
        if self.calls == 1:
            call = {'id': 'call-scope', 'type': 'function',
                    'function': {'name': 'design_scope',
                                 'arguments': json.dumps({'action': 'propose',
                                                          'patch': {'screen': 'màn hình chat'}})}}
            return {'choices': [{'message': {'content': '', 'tool_calls': [call]},
                                 'finish_reason': 'tool_calls'}], 'usage': None, 'boxfox': None}
        return {'choices': [{'message': {'content': 'đã ghi brief'}, 'finish_reason': 'stop'}],
                'usage': None, 'boxfox': None}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    model = DesignToolCaller()
    runtime = HarnessRuntime(store, FixtureExecutor(), model)
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    yield store, runtime, sid, model
    store.close()


def _start_background_run(store, runtime, sid):
    """Mở một run, rời khỏi `needs_user`, rồi cho chủ nhà chọn "Tiếp tục chạy nền"."""
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế màn hình chat')
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    live = store.design_job(job['design_id'])
    prompts = [row for row in (live['state'].get('prompts') or []) if row['status'] == 'open']
    if prompts:
        design_runtime.design_prompt_answer(runtime, sid, prompts[0]['promptId'],
                                            [{'questionId': 'dq-screen', 'text': 'màn hình chat'}],
                                            start=True)
    live = store.design_job(job['design_id'])
    design_runtime.set_phase(runtime, sid, live, 'scaffolding', 'test-setup')
    design_runtime.apply_design_mode(runtime, sid, False, 'toggle', active_run='background')
    return store.design_job(job['design_id'])


def test_pumped_background_run_can_call_a_design_tool(harness):
    store, runtime, sid, model = harness
    job = _start_background_run(store, runtime, sid)
    live = store.design_job(job['design_id'])
    assert live['status'] not in {'paused', 'needs_user'} and live['state']['background'] is True
    assert store.get(sid)['config']['designMode']['on'] is False
    assert design_job_pumpable(runtime, live, store.get(sid)) is True

    async def pump():
        await design_continuation_step(runtime)
        invocation = str(runtime.turn_invocations.get(sid) or '')
        task = runtime.tasks.get(sid)
        if task is not None:
            await task
        return invocation

    invocation = asyncio.run(pump())
    assert invocation.startswith(f'design-resume-{job["design_id"]}')
    assert 'design_scope' in model.offered[0], 'lượt bơm phải được quảng cáo họ công cụ design'
    # Lời gọi công cụ THẬT SỰ chạy: patch đã vào brief của run (không có `DESIGN_MODE_REQUIRED`).
    brief = store.design_job(job['design_id'])['state'].get('brief') or {}
    value = brief.get('screen')
    value = value.get('text') if isinstance(value, dict) else value
    assert str(value or '') == 'màn hình chat'


def test_a_plain_turn_outside_the_mode_is_still_refused(harness):
    """Không nới cổng cho ai khác: lượt KHÔNG phải bơm vẫn `DESIGN_MODE_REQUIRED`."""
    store, runtime, sid, model = harness
    job = _start_background_run(store, runtime, sid)
    runtime.turn_invocations[sid] = None

    async def call():
        return await runtime.dispatch(store.get(sid), 'design_scope',
                                      {'action': 'propose', 'patch': {'screen': 'x'}})

    with pytest.raises(ValueError) as caught:
        asyncio.run(call())
    assert limits.DESIGN_MODE_REQUIRED_CODE in str(caught.value)
    assert design_job_pumpable(runtime, store.design_job(job['design_id']), store.get(sid)) is True
