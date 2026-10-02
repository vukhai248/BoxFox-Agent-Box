"""W8.A4.2 — cổng giao việc (`delegate`) và lệnh người dùng tự gõ (`_command_task`).

Hai đường này tạo con NGOÀI Work Graph, nên chúng là đường vòng của phạm vi thi công: một `delegate`
vai `build` trong lượt artifact-only là một nhánh sửa mã không có node/admission, còn custom command
`/claude-code` (hoặc vai ghi) cũng vậy. Bộ kiểm này khẳng định cổng chặn TRƯỚC khi tạo con / trước
pre-flight CLI, và rằng con thường thừa hưởng phạm vi của lượt chủ.
"""
import asyncio

import pytest

from agentbox.agent_core import work_graph as wg, work_scope
from agentbox.agent_core.failures import classify_failure
from test_work_checks import RESEARCH
from test_work_graph import build

BUILD = {'id': 'B1', 'kind': 'build', 'title': 'Exporter', 'goal': 'Fix exporter Unicode serialization',
         'acceptance': ['Preserve Unicode'], 'tests': ['vitest ChatHeader.test.tsx']}


async def root(rt, sid, name, args):
    return await rt.dispatch(rt.store.get(sid), name, args)


async def created_run(rt, sid, flow='research', nodes=None, goal='Research exporter formats'):
    result = await root(rt, sid, 'work_graph', {'action': 'create', 'goal': goal, 'flow': flow,
                                                'nodes': nodes or [RESEARCH]})
    return wg.service(rt).get(result['runId'])


def children(store, sid):
    return store.children_of(sid)


def test_delegate_to_a_write_role_is_blocked_but_explore_children_inherit_the_scope(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        await created_run(rt, sid)
        session = store.get(sid)
        with pytest.raises(PermissionError, match='WORK_SCOPE_DELEGATE_ROLE') as failure:
            await rt.delegate(session, {'role': 'build', 'goal': 'write the exporter'})
        assert 'build' in str(failure.value)
        assert classify_failure(failure.value)[0] == 'WORK_SCOPE_DELEGATE_ROLE'
        assert children(store, sid) == [], 'cổng phải chặn TRƯỚC khi tạo phiên con'
        # Vai đọc/khảo sát vẫn giao được: đây là đường mà run artifact-only cần.
        child = await rt.delegate(session, {'role': 'explore', 'goal': 'find the exporter tests',
                                            'wait': False})
        child_session = store.get(child['sessionId'])
        origin = child_session['config'][work_scope.ORIGIN_KEY]
        assert origin['mode'] == 'artifact_only' and origin['runId']
        assert work_scope.resolve(rt, child_session)['mode'] == 'artifact_only'
        # Con thừa hưởng phạm vi: terminal sửa mã của con cũng bị chặn, kể cả khi config của nó
        # không có `workBinding`/`workIntent` nào.
        with pytest.raises(PermissionError, match='WORK_SCOPE_TERMINAL_MUTATING'):
            await rt.dispatch(child_session, 'terminal_exec', {'command': 'pip install requests'})
        assert not [call for call in executor.calls if call[0] == 'terminal_exec'
                    and 'pip install' in call[1]['command']]
    asyncio.run(check())


def test_a_custom_command_with_a_write_role_never_probes_or_spawns(tmp_path, monkeypatch):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        await created_run(rt, sid)
        rt.commands.configure({'enabled': list(rt.catalog.items), 'revision': 0})
        enabled = rt.commands.settings()['enabled']
        resolved = rt.commands.resolve('/claude-code List the files.', enabled)
        probes = []

        async def fake_probe(self):
            probes.append(True)
            return {'executor': 'claude-code', 'status': 'ready', 'binary': True}

        monkeypatch.setattr('agentbox.sandbox.claude_executor.ClaudeExecutor.probe', fake_probe)
        await rt._command_task(sid, resolved, None)
        errors = [event for event in rt.store.events(sid) if event['type'] == 'error']
        assert errors and 'WORK_SCOPE_COMMAND_ROLE' in errors[0]['data']['message']
        assert probes == [], 'cổng phải chặn trước pre-flight CLI'
        assert children(store, sid) == [], 'không được tạo phiên con cho custom command bị chặn'
    asyncio.run(check())


def test_legacy_turns_still_allow_write_delegates_and_custom_commands(tmp_path, monkeypatch):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        session = store.get(sid)
        child = await rt.delegate(session, {'role': 'build', 'goal': 'write the exporter', 'wait': False})
        assert store.get(child['sessionId'])['role'] == 'build'
        assert work_scope.ORIGIN_KEY not in store.get(child['sessionId'])['config']
        rt.commands.configure({'enabled': list(rt.catalog.items), 'revision': 0})
        enabled = rt.commands.settings()['enabled']
        resolved = rt.commands.resolve('/claude-code List the files.', enabled)

        async def fake_probe(self):
            return {'executor': 'claude-code', 'status': 'setup_required', 'binary': False,
                    'reason': 'Install Claude Code inside the sandbox, then sign in there.'}

        monkeypatch.setattr('agentbox.sandbox.claude_executor.ClaudeExecutor.probe', fake_probe)
        monkeypatch.setattr(executor, 'container', object(), raising=False)
        await rt._command_task(sid, resolved, None)
        errors = [event for event in rt.store.events(sid) if event['type'] == 'error']
        assert errors and 'SETUP_REQUIRED' in errors[0]['data']['message'], \
            'lượt thường giữ nguyên đường cũ: pre-flight CLI vẫn chạy'
    asyncio.run(check())


def test_revoked_admission_blocks_a_pending_execution_child(tmp_path):
    """Revoke/Stop/khởi động lại đều làm admission chết: `delegate(work=...)` phải chặn, không gọi executor."""

    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid, flow='fix', nodes=[BUILD], goal='Fix the Unicode export behavior')
        graph = wg.service(rt)
        graph.approve_by_autopilot(run)
        graph.save(run, 'approved', 'autopilot')
        work = {'runId': run['runId'], 'nodeId': 'B1', 'stage': 'execute', 'purpose': 'produce',
                'taskKind': 'implementation'}
        work['progressAdmissionId'] = await graph.progress.reserve(sid, work)
        assert work_scope.check_execute_binding(rt, sid, work)['mode'] == 'run_execute'
        # Revoke: hàng đợi admission bị huỷ (đường `progress.cancel` mà Stop/Revoke gọi).
        graph.progress.cancel(sid)
        with pytest.raises(PermissionError, match='WORK_SCOPE_REVOKED') as failure:
            await rt.delegate(store.get(sid), {'role': 'build', 'goal': 'write the exporter'}, work=work)
        assert run['runId'] in str(failure.value)
        assert children(store, sid) == []
        # Khởi động lại tiến trình (WorkGraph mới đọc lại DB) rồi cấp admission mới: mở lại được.
        rt.work_graph = wg.WorkGraph(rt)
        work['progressAdmissionId'] = await wg.service(rt).progress.reserve(sid, work)
        assert work_scope.check_execute_binding(rt, sid, work)['mode'] == 'run_execute'
        child = await rt.delegate(store.get(sid), {'role': 'build', 'goal': 'write the exporter',
                                                   'wait': False}, work=work)
        assert store.get(child['sessionId'])['config']['workBinding']['nodeId'] == 'B1'
    asyncio.run(check())
