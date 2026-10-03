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
    store.close()


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


# --------------------------------------------------------------------------- #
# Wiring pin: the runtime must route dispatch through this kernel, not legacy.
# --------------------------------------------------------------------------- #

class _Reached(Exception):
    pass


def test_dispatch_routes_through_the_kernel_guard(environment, monkeypatch):
    """Reverting `runtime.dispatch` to `work_scope.check_tool` must fail this test."""
    import asyncio

    from agentbox.agent_core import runtime as runtime_module

    runtime, sid = environment
    session = runtime.store.get(sid)
    seen = []

    def stop(rt, current, name, args):
        seen.append((rt, current['id'], name, args))
        raise _Reached()

    monkeypatch.setattr(execution_kernel, 'guard_tool', stop)
    with pytest.raises(_Reached):
        asyncio.run(runtime_module.HarnessRuntime.dispatch(runtime, session, 'file_read', {'path': 'x'}))
    assert seen == [(runtime, sid, 'file_read', {'path': 'x'})]


# --------------------------------------------------------------------------- #
# Switch-off isolation: the two disjuncts must each hold on their own.
# --------------------------------------------------------------------------- #

LIVE = work_scope.scope('run_execute', 'run-1', 'approved execution of node build-1', admission='adm-1')


def test_switch_off_beats_a_live_graph(environment, monkeypatch):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    monkeypatch.setattr(work_scope, '_graph', lambda rt: object())
    monkeypatch.delenv('BOXFOX_ADAPTIVE_HARNESS', raising=False)
    with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
        execution_kernel.guard_tool(runtime, current, 'file_write', {'path': 'x'})
    assert execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})['mode'] == 'artifact_only'


def test_switch_off_beats_a_live_run_execute_binding(environment, monkeypatch):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    monkeypatch.setattr(work_scope, '_graph', lambda rt: object())
    monkeypatch.setattr(work_scope, 'resolve', lambda rt, session: dict(LIVE))
    monkeypatch.delenv('BOXFOX_ADAPTIVE_HARNESS', raising=False)
    with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
        execution_kernel.guard_tool(runtime, current, 'file_write', {'path': 'x'})
    assert execution_kernel.guard_tool(runtime, current, 'terminal_exec', {'command': 'ls'})['mode'] == 'artifact_only'
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    assert execution_kernel.guard_tool(runtime, current, 'file_write', {'path': 'x'})['mode'] == 'run_execute'


def test_live_graph_without_switch_still_reports_restricted_view(environment, monkeypatch):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    monkeypatch.setattr(work_scope, '_graph', lambda rt: object())
    view = execution_kernel.permission_view(runtime, current)
    assert view['scope']['mode'] == 'artifact_only'
    assert view['admitted'] is False
    assert view['adaptiveEnabled'] is False


# --------------------------------------------------------------------------- #
# Mode-injected tools: plan/design tools never appear in `config.tools`.
# --------------------------------------------------------------------------- #

def test_mode_injected_tools_are_not_reported_as_revoked(environment):
    """`plan_scope`/`design_scope` never appear in `config.tools`; the owner check must exempt them."""
    runtime, sid = environment
    current = policy_session(runtime, sid)
    runtime.turn_profile = lambda session: {'mode': 'plan', 'tools': TOOLS + ['plan_scope'], 'promptBlock': ''}
    assert execution_kernel.guard_tool(runtime, current, 'plan_scope', {'action': 'status'})['mode'] == 'artifact_only'
    runtime.turn_profile = lambda session: {'mode': 'design',
                                            'tools': TOOLS + ['design_scope'], 'promptBlock': ''}
    assert execution_kernel.guard_tool(runtime, current, 'design_scope', {'action': 'status'})['mode'] == 'artifact_only'


def test_injected_design_tool_survives_the_owner_check_when_admitted(environment, monkeypatch):
    """With a live binding the scope gate stands aside, so only the exemption can save this call."""
    runtime, sid = environment
    current = policy_session(runtime, sid)
    runtime.turn_profile = lambda session: {'mode': 'design',
                                            'tools': TOOLS + ['design_write'], 'promptBlock': ''}
    monkeypatch.setattr(work_scope, '_graph', lambda rt: object())
    monkeypatch.setattr(work_scope, 'resolve', lambda rt, session: dict(LIVE))
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    assert execution_kernel.guard_tool(runtime, current, 'design_write', {'path': 'x'})['mode'] == 'run_execute'


def test_tools_outside_the_owner_switchboard_and_the_turn_profile_are_revoked(environment):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    runtime.turn_profile = lambda session: {'mode': 'chat', 'tools': TOOLS, 'promptBlock': ''}
    with pytest.raises(PermissionError, match='WORK_CAPABILITY_REVOKED'):
        execution_kernel.guard_tool(runtime, current, 'design_write', {'path': 'x'})


def test_unavailable_turn_profile_fails_closed(environment):
    runtime, sid = environment
    current = policy_session(runtime, sid)

    def broken(session):
        raise RuntimeError('profile unavailable')

    runtime.turn_profile = broken
    with pytest.raises(PermissionError, match='WORK_CAPABILITY_REVOKED'):
        execution_kernel.guard_tool(runtime, current, 'design_write', {'path': 'x'})
    assert execution_kernel.guard_tool(runtime, current, 'file_read', {'path': 'x'})['mode'] == 'artifact_only'


# --------------------------------------------------------------------------- #
# Permission view: filtered by the restricted scope, never a grant.
# --------------------------------------------------------------------------- #

def test_view_filters_mutating_tools_outside_legacy(environment):
    runtime, sid = environment
    current = policy_session(runtime, sid)
    view = execution_kernel.permission_view(runtime, current)
    assert 'file_write' not in view['tools'] and 'file_read' in view['tools']
    assert view['scope']['mode'] == 'artifact_only'
    assert view['admitted'] is False
    assert 'toolsNote' in view


def test_view_keeps_the_owner_switchboard_for_legacy_sessions(environment):
    runtime, sid = environment
    current = runtime.store.get(sid)
    view = execution_kernel.permission_view(runtime, current)
    assert view['scope']['mode'] == 'legacy'
    assert 'file_write' in view['tools']
    assert view['admitted'] is False and view['adaptiveEnabled'] is False
