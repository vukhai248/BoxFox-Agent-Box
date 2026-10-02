"""W6.1.3 `verify_exec`: reviewer capability, dispatch path and receipt signature.

The box-level behaviour (bwrap, rlimits, timeouts) lives in test_sandbox_verify_exec.py.
"""
import asyncio
import hashlib
import json

import pytest

from agentbox.agent_core import verify_exec, work_checks, work_feedback, work_graph
from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS, ROLES, allowed_tools, work_check_tools
from agentbox.agent_core.tool_contracts import SCHEMAS
from test_work_graph import build


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def schema(name):
    return next(item for item in SCHEMAS if item['function']['name'] == name)


def test_review_roles_get_verify_exec_only_when_parent_allows():
    assert 'verify_exec' in ORCHESTRATOR_TOOLS  # thiếu ở cha thì con bị cắt
    for role in ('review', 'plan-review', 'research-review'):
        assert 'verify_exec' in allowed_tools(role, ORCHESTRATOR_TOOLS), role
        assert 'verify_exec' in work_check_tools(role, ORCHESTRATOR_TOOLS), role
        without = {name for name in ORCHESTRATOR_TOOLS if name != 'verify_exec'}
        assert 'verify_exec' not in allowed_tools(role, without), role
        assert 'verify_exec' not in work_check_tools(role, without), role
    # A producer role keeps its existing tool set: verify_exec is a reviewer capability.
    assert 'verify_exec' not in ROLES['build'].tools
    assert 'verify_exec' not in work_check_tools('build', ORCHESTRATOR_TOOLS)


def test_verify_exec_schema_errors_name_field():
    properties = schema('verify_exec')['function']['parameters']
    assert properties['required'] == ['language', 'code', 'claim']
    assert properties['properties']['code']['maxLength'] == 8000
    assert properties['properties']['timeoutSeconds'] == {'type': 'integer', 'minimum': 1, 'maximum': 20}
    assert verify_exec.arg_error({'language': 'python', 'code': 'print(1)'}) == \
        'VERIFY_EXEC_INVALID: claim must be a non-empty string'
    assert 'timeoutSeconds' in verify_exec.arg_error(
        {'language': 'python', 'code': 'print(1)', 'claim': 'x', 'timeoutSeconds': 30})
    assert 'code' in verify_exec.arg_error({'language': 'python', 'code': 'x' * 8001, 'claim': 'x'})
    assert verify_exec.arg_error({'language': 'python', 'code': 'print(1)', 'claim': 'x', 'extra': 1}) == \
        'VERIFY_EXEC_INVALID: unknown field extra'
    assert verify_exec.arg_error({'language': 'python', 'code': 'print(1)', 'claim': 'x'}) is None


def test_verify_exec_bypasses_writer_lock_and_check_read_only_gate(tmp_path):
    async def check():
        store, rt, _, executor, sid = build(tmp_path)
        session = store.get(sid)
        calls = []
        original = executor.execute
        async def recording(name, args, *rest, **kwargs):
            calls.append(name)
            return await original(name, args, *rest, **kwargs)
        executor.execute = recording
        args = {'language': 'python', 'code': 'print(1)', 'claim': 'one'}
        await rt.dispatch(session, 'verify_exec', args, 'call_1')
        assert calls == ['verify_exec']
        # A bound checker may run verify_exec: the read-only gate covers source writes/delegation.
        bound = dict(session)
        bound['config'] = dict(session['config'], workBinding={'checkId': 'c-1'})
        await rt.dispatch(bound, 'verify_exec', args, 'call_2')
        assert calls == ['verify_exec', 'verify_exec']
        with pytest.raises(ValueError, match='VERIFY_EXEC_INVALID'):
            await rt.dispatch(bound, 'verify_exec', {'language': 'python', 'code': 'print(1)'}, 'call_3')
    asyncio.run(check())


def test_verify_exec_receipt_signature():
    receipt = {'kind': 'verify_exec', 'language': 'python', 'codeHash': 'a' * 8,
               'outputHash': 'b' * 8, 'exitCode': 1, 'truncated': False, 'claim': 'csv.Error'}
    event = {'id': 'call_1', 'name': 'verify_exec', 'args': {'code': 'x'},
             'result': {'content': 'csv.Error', 'exit_code': 1, 'is_error': False, 'receipt': receipt}}
    proof = work_feedback.evidence_signature(event)
    assert proof == {'ref': 'verify:a' * 1 + 'aaaaaaa', 'kind': 'verify_exec',
                     'contentHash': 'b' * 8, 'range': None}
    # A timeout is still an observation: is_error=true but the receipt exists.
    timeout = dict(event, result={'content': '', 'is_error': True, 'receipt': receipt})
    assert work_feedback.evidence_signature(timeout)['ref'] == proof['ref']
    # No receipt (sandbox unavailable) proves nothing.
    assert work_feedback.evidence_signature(dict(event, result={'is_error': True, 'error': 'x'})) is None


def test_verify_exec_not_counted_as_good_read(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path)
        graph = work_graph.service(rt)
        store.emit(sid, 'tool_end', {'id': 'call_1', 'name': 'verify_exec',
                                     'args': {'code': 'print(1)'},
                                     'result': {'content': '1', 'exit_code': 0, 'is_error': False,
                                                'receipt': {'kind': 'verify_exec', 'codeHash': 'a' * 8,
                                                            'outputHash': 'b' * 8, 'exitCode': 0}}})
        assert work_checks.good_reads(graph, sid) == []
    asyncio.run(check())


def test_verify_exec_status_observed_for_health():
    unavailable = {'is_error': True, 'errorCode': 'VERIFY_EXEC_UNAVAILABLE', 'error': 'VERIFY_EXEC_UNAVAILABLE: no bwrap'}
    assert verify_exec.observed(unavailable)['available'] is False
    assert verify_exec.observed({'available': True, 'procMode': 'proc'})['available'] is True
    assert verify_exec.observed({'receipt': {'isolation': 'tmpfs'}}) == {
        'available': True, 'reason': None, 'procMode': 'tmpfs'}
    assert verify_exec.observed({'content': 'unrelated'}, {'available': None, 'reason': 'not probed yet'}) == \
        {'available': None, 'reason': 'not probed yet'}
