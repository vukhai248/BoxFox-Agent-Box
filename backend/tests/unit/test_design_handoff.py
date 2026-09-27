"""P4 — khối `=== DESIGN HANDOFF ===` (plan v1 §6.6, hợp đồng design-interfaces §4, §6).

Khối bàn giao phải xuất hiện ĐÚNG MỘT lần trong prompt hệ thống, không nhân lên sau nhiều lượt, và
chỉ tới lượt main MỘT lần cho mỗi `(designId, version)`.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

BASE_SHA = 'a' * 40


class FixtureExecutor:
    async def execute(self, name, args, sid, **kwargs):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


class RecordingModel:
    def __init__(self):
        self.calls = 0

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls += 1
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
                'usage': None, 'boxfox': None}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    runtime.client = RecordingModel()
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    yield store, runtime, sid
    store.close()


def open_run(runtime, store, sid, goal='thiết kế lại màn hình chat'):
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, goal)
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    return store.design_job(job['design_id'])


def slug(job):
    return design_runtime._slug(job['design_id'])


def run_turn(runtime, sid, prompt='tiếp tục'):
    async def main():
        await runtime.submit(sid, prompt)
        task = runtime.tasks.get(sid)
        if task is not None:
            await task

    asyncio.run(main())


def finish_run(store, runtime, sid, job, version=1):
    """Ghim một run ĐÃ XONG đúng hình dạng `design_report` để lại (bàn giao chỉ đọc state)."""
    live = store.design_job(job['design_id'])
    state = dict(live['state'] or {})
    branch = {'name': 'design/ui-20260927-1200', 'base': BASE_SHA, 'status': 'active'}
    state['branch'] = branch
    state['touchList'] = {'revision': 1, 'designId': job['design_id'], 'branch': branch,
                          'items': [{'id': 't1', 'kind': 'insert', 'path': 'src/chat.tsx',
                                     'reason': 'màn hình chat', 'risk': 'low', 'status': 'written',
                                     'sha256': 'b' * 64}],
                          'forbidden': list(limits.DESIGN_HARD_FORBIDDEN), 'approvedAt': 'X'}
    state['brief'] = {'screen': {'text': 'màn hình chat', 'status': 'confirmed',
                                 'source': {'kind': 'user'}},
                      'style': {'text': 'theo phong cách hiện có'}}
    state['actions'] = [{'at': 'X', 'path': f'.design/{slug(job)}/v{version}-design.md',
                         'mode': 'create', 'sha256': 'c' * 64, 'reason': 'màn hình chat',
                         'author': 'agent'}]
    state['review'] = {'version': version, 'verdict': 'ok', 'summary': 'đứng được', 'issues': [],
                       'at': 'X', 'criticSessionId': 'child-1'}
    state['report'] = {'version': version, 'path': f'.design/{slug(job)}/v{version}-design.md',
                       'reportPath': f'.design/{slug(job)}/report.md', 'labels': [],
                       'summary': 'sẵn sàng triển khai', 'nextSteps': ['triển khai màn hình chat'],
                       'verdict': 'ok', 'at': 'X', 'branch': branch}
    state['phase'] = design_runtime.PHASE_DONE
    state['phaseHistory'] = (list(state.get('phaseHistory') or [])) + [
        {'phase': design_runtime.PHASE_DONE, 'at': 'X', 'reason': 'design-report'}]
    store.design_job_save(job['design_id'], sid, state, status='completed', revision=live['revision'])
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'activeRunId': ''}
    store.update_config(sid, config)


def system_prompt(store, sid):
    return store.get(sid)['messages'][0]['content']


def test_handoff_block_once_after_many_turns(harness):
    store, runtime, sid = harness
    job = open_run(runtime, store, sid)
    finish_run(store, runtime, sid, job)
    design_runtime.apply_design_mode(runtime, sid, False, 'toggle')
    run_turn(runtime, sid, 'bắt đầu triển khai')
    first = system_prompt(store, sid)
    assert first.count(limits.DESIGN_HANDOFF_BLOCK_MARKER) == 1
    assert first.count(limits.DESIGN_HANDOFF_BLOCK_END) == 1
    delivered = store.get(sid)['config']['designMode']['handoffDeliveredVersion']
    assert delivered[job['design_id']] == '1'
    run_turn(runtime, sid, 'làm tiếp')
    second = system_prompt(store, sid)
    assert second.count(limits.DESIGN_HANDOFF_BLOCK_MARKER) == 0, 'mỗi (designId, version) chỉ MỘT lần'
    assert second.count(limits.DESIGN_HANDOFF_BLOCK_END) == 0
    # Khối của lượt trước được GỠ trước rồi chèn lại, nên prompt không bao giờ mang hai bản.
    assert second.count(limits.DESIGN_HANDOFF_BLOCK_MARKER) <= 1


def test_handoff_block_content_contract(harness):
    store, runtime, sid = harness
    job = open_run(runtime, store, sid)
    finish_run(store, runtime, sid, job)
    design_runtime.apply_design_mode(runtime, sid, False, 'toggle')
    run_turn(runtime, sid)
    prompt = system_prompt(store, sid)
    start = prompt.index(limits.DESIGN_HANDOFF_BLOCK_MARKER)
    end = prompt.index(limits.DESIGN_HANDOFF_BLOCK_END) + len(limits.DESIGN_HANDOFF_BLOCK_END)
    block = prompt[start:end]
    assert job['design_id'] in block
    assert 'design/ui-20260927-1200' in block and BASE_SHA in block
    assert f'.design/{slug(job)}/v1-design.md' in block
    assert 'src/chat.tsx' in block
    assert 'ok' in block and 'đứng được' in block
    assert 'triển khai màn hình chat' in block
    assert 'Bạn đã xác nhận: screen: màn hình chat' in block
    assert 'Giả định của agent: style: theo phong cách hiện có' in block


def test_no_handoff_before_the_run_is_done(harness):
    store, runtime, sid = harness
    open_run(runtime, store, sid)
    # Run đang chờ chủ nhà ⇒ tắt chế độ phải chọn `pause` trước (luật §5.1), rồi mới về lượt main.
    design_runtime.apply_design_mode(runtime, sid, False, 'toggle', active_run='pause')
    run_turn(runtime, sid, 'chỉ trò chuyện')
    assert limits.DESIGN_HANDOFF_BLOCK_MARKER not in system_prompt(store, sid)


def test_done_run_hands_off_even_while_the_mode_is_on(harness):
    """§6.6: bàn giao khi mode tắt HOẶC khi run đã `done` — run xong là việc của chính nó."""
    store, runtime, sid = harness
    job = open_run(runtime, store, sid)
    finish_run(store, runtime, sid, job)
    # Mode vẫn BẬT (chủ nhà chưa tắt) — chỉ run đã xong.
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': ''}
    store.update_config(sid, config)
    run_turn(runtime, sid)
    assert system_prompt(store, sid).count(limits.DESIGN_HANDOFF_BLOCK_MARKER) == 1


def test_named_run_wins_over_a_newer_undelivered_run(harness):
    """Nút "Dùng cho plan" nêu tên run: CHỈ run ấy được bàn giao, dù run khác mới hơn."""
    store, runtime, sid = harness
    older = open_run(runtime, store, sid, goal='thiết kế màn hình cũ')
    finish_run(store, runtime, sid, older)
    newer = open_run(runtime, store, sid, goal='thiết kế màn hình mới')
    finish_run(store, runtime, sid, newer)
    design_runtime.apply_design_mode(runtime, sid, False, 'toggle')
    compact = ''.join(ch for ch in older['design_id'].lower() if ch.isalnum())
    label = f'D-{compact[-5:].upper()}'
    run_turn(runtime, sid, f'Lập plan dựa trên bàn giao thiết kế {label} v1')
    delivered = store.get(sid)['config']['designMode']['handoffDeliveredVersion']
    assert older['design_id'] in delivered
    assert newer['design_id'] not in delivered
    assert older['design_id'] in system_prompt(store, sid)
