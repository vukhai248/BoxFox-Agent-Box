"""Thin admission boundary over the existing Work Graph guards.

This module does not schedule children, mint grants, or certify OS isolation.
Legacy dispatch retains its original scope checks. Adaptive bindings additionally
fail closed when the guard engine or canonical owner disappears.
"""
import os

from . import tool_recovery, work_scope

POLICY_SCHEMA = 'boxfox-execution-policy/1'
POLICY_KEY = 'harnessPolicy'


def enabled():
    return os.getenv('BOXFOX_ADAPTIVE_HARNESS', 'off').strip().lower() in ('1', 'on', 'true')


def _policy(current):
    config = current.get('config') or {}
    if POLICY_KEY not in config:
        return None
    value = config[POLICY_KEY]
    if (not isinstance(value, dict) or value.get('schema') != POLICY_SCHEMA
            or value.get('mode') != 'adaptive'
            or set(value) - {'schema', 'mode'}):
        raise PermissionError('HARNESS_POLICY_UNSUPPORTED: explicit supported backend policy required')
    return value


def _fresh(rt, session):
    # No fallback to caller-owned config after deletion/revocation.
    try:
        return rt.store.get(session['id'])
    except (KeyError, TypeError) as exc:
        raise PermissionError('HARNESS_SESSION_UNKNOWN: canonical session is unavailable') from exc


def guard_tool(rt, session, name, args):
    """Run the canonical scope guard first; return a view, never a grant."""
    current = _fresh(rt, session)
    scope = work_scope.check_tool(rt, current, name, args)
    policy = _policy(current)
    if policy is None:
        return scope
    parent_id = current.get('parent_id')
    if parent_id:
        try:
            rt.store.get(parent_id)
        except KeyError as exc:
            raise PermissionError('HARNESS_OWNER_UNKNOWN: no owner, no adaptive effect') from exc
    if name not in tool_recovery.owner_tools(rt.store, current):
        raise PermissionError('WORK_CAPABILITY_REVOKED: the current owner no longer permits ' + name)
    # The new switch cannot use BOXFOX_WORK_GRAPH=off to fall through to legacy.
    if not enabled() or work_scope._graph(rt) is None:
        restricted = work_scope.scope('artifact_only', scope.get('runId'),
                                      'adaptive admission is disabled or unavailable')
        work_scope.check_tool(rt, current, name, args, current=restricted)
        if name == 'delegate_task':
            work_scope.check_delegate(restricted, (args or {}).get('role'))
        return restricted
    if scope.get('mode') == 'legacy':
        # An enabled flag without canonical execution bindings is not authority.
        restricted = work_scope.scope('artifact_only', scope.get('runId'),
                                      'adaptive request has no canonical execution binding')
        work_scope.check_tool(rt, current, name, args, current=restricted)
        if name == 'delegate_task':
            work_scope.check_delegate(restricted, (args or {}).get('role'))
        return restricted
    return scope


def permission_view(rt, session):
    """A current application-level capability view, not a filesystem sandbox."""
    current = _fresh(rt, session)
    policy = _policy(current)
    parent_id = current.get('parent_id')
    if policy and parent_id:
        try:
            rt.store.get(parent_id)
        except KeyError as exc:
            raise PermissionError('HARNESS_OWNER_UNKNOWN: canonical parent is unavailable') from exc
    scope = work_scope.resolve(rt, current)
    if policy and (not enabled() or work_scope._graph(rt) is None or scope['mode'] == 'legacy'):
        scope = work_scope.scope('artifact_only', scope.get('runId'),
                                'adaptive execution is not admitted')
    return {
        'schema': 'boxfox-permission-view/1',
        'sessionId': current['id'], 'ownerId': parent_id or current['id'],
        'scope': dict(scope), 'tools': sorted(tool_recovery.owner_tools(rt.store, current)),
        'enforcement': 'application',
        'filesystemIsolation': 'unverified', 'networkIsolation': 'unverified',
        'adaptiveEnabled': bool(policy and enabled() and work_scope._graph(rt) is not None),
    }
