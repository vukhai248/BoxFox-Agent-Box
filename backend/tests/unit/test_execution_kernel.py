"""H2 guard parity and fail-closed controls, without an executor or model."""
from types import SimpleNamespace

import pytest

from agentbox.agent_core import execution_kernel, work_scope
from agentbox.memory.session_store import SessionStore


POLICY = {'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'}
TOOLS = ['file_read', 'file_write', 'terminal_exec', 'delegate_task']


@pytest.fixture
def environment(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / 'sessions.db')
    root = store.create({'tools': TOOLS}, role='orchestrator')['id']
    runtime = SimpleNamespace(store=store)
    monkeypatch.setattr(work_scope, '_graph', lambda rt: None)
    monkeypatch.delenv('BOXFOX_ADAPTIVE_HARNESS', raising=False)
    yield runtime, root
    store.db.close()


def policy_session(runtime, sid, value=POLICY):
    current = runtime.store.get(sid)
    runtime.store.update_config(sid, dict(current['config'], harnessPolicy=value))
    return runtime.store.get(sid)


def test_legacy_guard_remains_the_behavior_source(environment):
    runtime, sid = environment
    session = runtime.store.get(sid)
    for name, args in [('file_write', {'path': 'x'}), ('terminal_exec', {'command': 'touch x'})]:
        assert execution_kernel.guard_tool(runtime, session, name, args) == work_scope.check_tool(
            runtime, session, name, args)


@pytest.mark.parametrize('name,args', [
    ('file_write', {'path': 'x'}), ('file_edit_block', {'path': 'x'}),
    ('terminal_exec', {'command': 'touch x'}), ('terminal_exec', {'command': 'python -m pytest'}),
    ('delegate_task', {'role': 'build'}), ('delegate_task', {'role': 'testing'}),
])
def test_new_policy_cannot_use_off_switch_to_mutate(environment, name, args):
    runtime, sid = environment
    current = runtime.store.get(sid)
    runtime.store.update_config(sid, dict(current['config'], tools=TOOLS + ['file_edit_block']))
    current = policy_session(runtime, sid)
    with pytest.raises(PermissionError):
        execution_kernel.guard_tool(runtime, current, name, args)


def test_enable_flag_without_canonical_engine_does_not_open_legacy(environment, monkeypatch):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
        execution_kernel.guard_tool(runtime, current, 'file_write', {'path': 'x'})
    assert execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})['mode'] == 'artifact_only'


def test_enabled_engine_without_execution_binding_stays_restricted(environment, monkeypatch):
    runtime, sid = environment
    child = runtime.store.create({'tools': ['file_read'], 'harnessPolicy': POLICY},
                                 role='explore', parent_id=sid)['id']
    current = runtime.store.get(child)
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    monkeypatch.setattr(work_scope, '_graph', lambda rt: object())
    view = execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})
    assert view['mode'] == 'artifact_only'
    assert 'no canonical execution binding' in view['reason']


def test_read_only_controls_work_with_switch_off(environment):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    assert execution_kernel.guard_tool(runtime, current, 'terminal_exec', {'command': 'ls'})['mode'] == 'artifact_only'
    assert execution_kernel.guard_tool(runtime, current, 'delegate_task', {'role': 'explore'})['mode'] == 'artifact_only'


@pytest.mark.parametrize('policy', [
    None, {}, 'adaptive', [], {'schema': 'boxfox-execution-policy/2', 'mode': 'adaptive'},
    dict(POLICY, grant='forged'), dict(POLICY, mode='legacy'),
])
def test_unknown_policy_is_not_permission(environment, policy):
    runtime, sid = environment
    current = policy_session(runtime, sid, policy)
    with pytest.raises(PermissionError, match='HARNESS_POLICY_UNSUPPORTED'):
        execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})


def test_owner_revoke_reads_fresh_config_not_the_callers_copy(environment):
    runtime, sid = environment
    stale = policy_session(runtime, sid)
    runtime.store.update_config(sid, dict(stale['config'], tools=[]))
    with pytest.raises(PermissionError, match='WORK_CAPABILITY_REVOKED'):
        execution_kernel.guard_tool(runtime, stale, 'file_read', {'path': 'x'})


def test_missing_parent_does_not_use_child_tool_fallback(environment):
    runtime, sid = environment
    child = runtime.store.create({'tools': ['file_read'], 'harnessPolicy': POLICY},
                                 role='explore', parent_id=sid)['id']
    current = runtime.store.get(child)
    with runtime.store.db:
        runtime.store.db.execute('DELETE FROM sessions WHERE id=?', (sid,))
    with pytest.raises(PermissionError, match='HARNESS_OWNER_UNKNOWN'):
        execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})
    with pytest.raises(PermissionError, match='HARNESS_OWNER_UNKNOWN'):
        execution_kernel.permission_view(runtime, current)


def test_missing_session_does_not_fallback_to_caller_config(environment):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    with runtime.store.db:
        runtime.store.db.execute('DELETE FROM sessions WHERE id=?', (sid,))
    with pytest.raises(PermissionError, match='HARNESS_SESSION_UNKNOWN'):
        execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})


def test_scope_guard_runs_before_new_policy_gate(environment, monkeypatch):
    runtime, sid = environment
    current = policy_session(runtime, sid, {})
    seen = []
    original = work_scope.check_tool
    def observe(*args, **kwargs):
        seen.append(args[2])
        return original(*args, **kwargs)
    monkeypatch.setattr(work_scope, 'check_tool', observe)
    with pytest.raises(PermissionError, match='HARNESS_POLICY_UNSUPPORTED'):
        execution_kernel.guard_tool(runtime, current, 'file_read', {})
    assert seen == ['file_read']


def test_view_is_application_level_not_os_or_network_isolation(environment):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    view = execution_kernel.permission_view(runtime, current)
    assert view['ownerId'] == sid
    assert view['scope']['mode'] == 'artifact_only'
    assert view['enforcement'] == 'application'
    assert view['filesystemIsolation'] == view['networkIsolation'] == 'unverified'
    assert view['adaptiveEnabled'] is False
