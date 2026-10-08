"""Offline fault fixtures; no live service/process is restarted or mutated."""
import asyncio
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from agentbox.agent_core.decision_store import DecisionStore, DecisionStoreError
from agentbox.agent_core.longtask_runtime import ProfileWriterGuard
from agentbox.agent_core.longtask_store import LongtaskError, LongtaskStore
from agentbox.agent_core.runtime import DecisionError, HarnessRuntime
from agentbox.agent_core.task_service import TaskService
from agentbox.memory.session_store import SessionStore
from test_decision_flow import FixtureExecutor, FixtureModel, answer, call
from test_harness_task_service import request


def runtime(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    rt = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer()]))
    sid = rt.create({'skills': []})['id']
    return rt, sid


def binding(sid):
    return {'projectId': 'project-1', 'goalRevision': 1, 'contractRevision': 1, 'contractHash': 'canonical-hash',
            'ownerEventRef': {'sessionId': sid, 'seq': 1}, 'capabilityEpoch': 1}


def configure(rt, sid, **changes):
    rt.longtask.binding = lambda _sid, body: binding(sid)
    rt.longtask.authority = lambda _sid, run: binding(sid)
    body = {'enabled': True, 'resumePolicy': 'safe_auto', 'goalRevision': 1,
            'invocationId': 'configure-1', 'budget': {'totalStepLimit': 10, 'activeTimeLimitMs': 2000000}}
    body.update(changes)
    return rt.configure_longtask(sid, body)


def persisted_card(rt, sid, *, kind='approval', deadline=None):
    did = '0123456789abcdef'
    record = {'decisionId': did, 'sessionId': sid, 'kind': kind, 'resolved': False, 'outcome': None,
              'toolCallId': 'tool-1', 'deadline': deadline or time.time() + 600, 'defaultChoice': 'reject',
              'options': [{'id': 'approve', 'label': 'Approve', 'kind': 'approve'},
                          {'id': 'reject', 'label': 'Reject', 'kind': 'reject'}]}
    payload = {**record, 'action': 'fixture mutation', 'reason': 'fixture'}
    rt.decision_store.request(record, payload, rt.decision_binding(sid, 'tool-1', {}))
    return did


def subprocess_code(code, *args):
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[2] / 'src'))
    return subprocess.run([sys.executable, '-c', code, *map(str, args)], env=env, capture_output=True, text=True)


def test_pending_card_same_id_outcome_and_retry_after_restart(tmp_path):
    rt, sid = runtime(tmp_path)
    did = persisted_card(rt, sid)
    rt.store.close()
    rt = HarnessRuntime(SessionStore(tmp_path / 'sessions.db'), FixtureExecutor(), FixtureModel([]))
    restored = rt.pending_decisions(sid)['decisions'][0]
    assert restored['decisionId'] == did and restored['revision'] == 1
    result = rt.resolve_decision(sid, did, 'reject', invocation_id='reply-1', expected_revision=1)
    assert result['revision'] == 2
    rt.store.close()
    rt = HarnessRuntime(SessionStore(tmp_path / 'sessions.db'), FixtureExecutor(), FixtureModel([]))
    assert rt.resolve_decision(sid, did, 'reject', invocation_id='reply-1', expected_revision=1) == result
    with pytest.raises(DecisionError, match='different reply'):
        rt.resolve_decision(sid, did, 'approve', invocation_id='reply-1', expected_revision=1)
    with pytest.raises(DecisionError) as exc:
        rt.resolve_decision(sid, did, 'reject')
    assert exc.value.code == 'DECISION_ALREADY_RESOLVED'
    assert len([e for e in rt.store.events(sid) if e['type'] == 'decision_resolved']) == 1


def test_request_and_answer_process_death_persist(tmp_path):
    rt, sid = runtime(tmp_path)
    rt.store.close()
    code = '''import os,sys,time
from agentbox.memory.session_store import SessionStore
from agentbox.agent_core.decision_store import DecisionStore
s=SessionStore(__import__('pathlib').Path(sys.argv[1])); d=DecisionStore(s)
r={'sessionId':sys.argv[2],'decisionId':'durable-id','kind':'question','resolved':False,'deadline':time.time()+600,'options':[],'defaultChoice':'reject','outcome':None}
d.request(r,r,{'toolCallId':'call-1'})
os._exit(17)
'''
    assert subprocess_code(code, tmp_path / 'sessions.db', sid).returncode == 17
    store = SessionStore(tmp_path / 'sessions.db')
    ds = DecisionStore(store)
    record = ds.get(sid, 'durable-id')
    assert record and not record['resolved']
    assert len([e for e in store.events(sid) if e['type'] == 'decision_requested']) == 1
    store.close()
    code = '''import os,sys
from agentbox.memory.session_store import SessionStore
from agentbox.agent_core.decision_store import DecisionStore
s=SessionStore(__import__('pathlib').Path(sys.argv[1]));d=DecisionStore(s);r=d.get(sys.argv[2],'durable-id')
out={'status':'answered','reason':'user'}
d.settle(r,out,{'decisionId':'durable-id','status':'answered'},invocation_id='reply-1',reply_payload={'choice':'x'},reply={'outcome':'answered'})
os._exit(18)
'''
    assert subprocess_code(code, tmp_path / 'sessions.db', sid).returncode == 18
    ds = DecisionStore(SessionStore(tmp_path / 'sessions.db'))
    assert ds.get(sid, 'durable-id')['outcome']['status'] == 'answered'
    assert ds.retry(sid, 'durable-id', 'reply-1', {'choice': 'x'}) == {'outcome': 'answered'}


def test_expiry_one_settle_and_stale_contract(tmp_path):
    rt, sid = runtime(tmp_path)
    did = persisted_card(rt, sid, deadline=time.time() - 1)
    assert rt.pending_decisions(sid)['decisions'] == []
    rt.hydrate_decisions(sid)
    assert rt.decision_store.get(sid, did)['status'] == 'expired'
    assert len([e for e in rt.store.events(sid) if e['type'] == 'decision_resolved']) == 1
    rt, sid = runtime(tmp_path / 'other')
    configure(rt, sid)
    did = persisted_card(rt, sid)
    rt.longtask.store.barrier(sid)
    with pytest.raises(DecisionError) as exc:
        rt.resolve_decision(sid, did, 'approve')
    assert exc.value.code == 'DECISION_STALE'
    assert not rt.decision_store.get(sid, did)['resolved']


def task_fixture(tmp_path):
    store = SessionStore(tmp_path / 'tasks.db')
    owner = store.create({})['id']
    svc = TaskService(store, lambda *_: {'runId': 'run-1', 'sessionId': owner})
    task = svc.create(owner, 'run-1', request(), controller_id=owner)
    child = store.create({}, role='explore', parent_id=owner)['id']
    store.child_start(child, owner, 1, 1, 'explore', 'fixture')
    svc.record_attempt(owner, 'run-1', task['taskKey'], invocation_id='attempt-1',
                       expected_revision=task['revision'], session_id=child,
                       admission_id='admission-1', capability_epoch=1)
    return store, svc, owner, child, task


def test_child_receipt_projection_atomic_rollback_and_gap_repair(tmp_path, monkeypatch):
    store, svc, owner, child, task = task_fixture(tmp_path)
    with monkeypatch.context() as m:
        m.setattr(svc, '_close_attempt_locked', lambda *_: (_ for _ in ()).throw(RuntimeError('fault in projection')))
        with pytest.raises(RuntimeError):
            svc.finish_child(child, 'completed')
    assert store.child(child)['finished'] is None
    assert svc.get(owner, 'run-1', task['taskKey'])['state'] == 'running'
    store.close()
    code = '''import os,sys
from agentbox.memory.session_store import SessionStore
s=SessionStore(__import__('pathlib').Path(sys.argv[1]));s.child_finish(sys.argv[2],'completed',reason='canonical receipt');os._exit(19)
'''
    assert subprocess_code(code, tmp_path / 'tasks.db', child).returncode == 19
    store = SessionStore(tmp_path / 'tasks.db')
    svc = TaskService(store, lambda *_: {'runId': 'run-1', 'sessionId': owner})
    before = svc.get(owner, 'run-1', task['taskKey'])['revision']
    assert len(svc.reconcile_startup()['closed']) == 1
    assert not svc.reconcile_startup()['closed']
    assert svc.get(owner, 'run-1', task['taskKey'])['revision'] == before + 1
    store.child_start(child, owner, 2, 1, 'explore', 'new attempt')
    attempt = svc.record_attempt(owner, 'run-1', task['taskKey'], invocation_id='attempt-2',
                       expected_revision=before + 1, session_id=child,
                       admission_id='admission-2', capability_epoch=1)
    assert attempt['attemptSeq'] == 2


def test_two_reconcilers_and_reopened_child_do_not_close_wrong_attempt(tmp_path):
    store, svc, owner, child, task = task_fixture(tmp_path)
    store.child_finish(child, 'completed')
    store.close()
    barrier, results = threading.Barrier(2), []
    def reconcile():
        s = SessionStore(tmp_path / 'tasks.db')
        service = TaskService(s, lambda *_: {'runId': 'run-1', 'sessionId': owner})
        barrier.wait()
        results.append(service.reconcile_startup())
        s.close()
    threads = [threading.Thread(target=reconcile) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
        assert not t.is_alive()
    assert sum(len(item['closed']) for item in results) == 1
    store, svc, owner, child, task = task_fixture(tmp_path / 'reopened')
    store.child_finish(child, 'completed')
    store.child_start(child, owner, 2, 1, 'explore', 'new')
    store.child_finish(child, 'failed')
    report = svc.reconcile_startup()
    assert report['conflicts'] == [child] and not report['closed']
    assert svc.get(owner, 'run-1', task['taskKey'])['state'] == 'running'


def test_budget_reservation_crash_bound_restart_and_one_card_delta(tmp_path):
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid, budget={'totalStepLimit': 3, 'activeTimeLimitMs': 10000})
    rt.longtask.store.reserve(run, 'model-1', 1, 2000)
    assert rt.longtask.store.settle_segment(run, 'model-1', 50)
    assert not rt.longtask.store.settle_segment(run, 'model-1', 50)
    rt.longtask.store.reserve(run, 'crashed-child', 1, 2000)
    rt.store.close()
    rt = HarnessRuntime(SessionStore(tmp_path / 'sessions.db'), FixtureExecutor(), FixtureModel([]))
    run = rt.longtask.store.get(sid)
    assert run['budget']['totalStepsUsed'] == 2 and run['budget']['activeTimeUsedMs'] == 2050
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.store.reserve(run, 'new-turn', 1, 1000)
    assert exc.value.code == 'LONGTASK_BUDGET_EXHAUSTED'
    rt.longtask.block(sid, exc.value)
    card = rt.pending_decisions(sid)['decisions'][0]
    assert card['kind'] == 'budget' and card['deadline'] is None
    rt.longtask.budget_card(rt.longtask.store.get(sid))
    assert len(rt.pending_decisions(sid)['decisions']) == 1
    result = rt.resolve_decision(sid, card['decisionId'], 'extend', invocation_id='extend-1', expected_revision=1)
    assert rt.resolve_decision(sid, card['decisionId'], 'extend', invocation_id='extend-1', expected_revision=1) == result
    run = rt.longtask.store.get(sid)
    assert run['budget']['totalStepsUsed'] == 2 and run['budget']['totalStepLimit'] == 6
    assert run['budget']['activeTimeLimitMs'] == 20000 and run['checkpointRef']['id']


@pytest.mark.parametrize('budget', [{}, {'totalStepLimit': 0, 'activeTimeLimitMs': 2},
                                   {'totalStepLimit': True, 'activeTimeLimitMs': 2},
                                   {'totalStepLimit': 3, 'activeTimeLimitMs': float('inf')}])
def test_explicit_finite_budget_required(tmp_path, budget):
    rt, sid = runtime(tmp_path)
    with pytest.raises((LongtaskError, ValueError)):
        configure(rt, sid, budget=budget)
    assert rt.longtask_state(sid) is None


def test_no_progress_survives_restart_and_completion_scoped_failures(tmp_path, monkeypatch):
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.completion = lambda *_: {'state': 'runnable', 'evidenceFingerprint': 'same-artifact'}
    for _ in range(3):
        rt.longtask.finish(sid)
    assert rt.longtask.store.get(sid)['lastProgress']['unchangedCount'] == 2
    rt.store.close()
    rt = HarnessRuntime(SessionStore(tmp_path / 'sessions.db'), FixtureExecutor(), FixtureModel([]))
    rt.longtask.authority = lambda *_: binding(sid)
    rt.longtask.completion = lambda *_: {'state': 'runnable', 'evidenceFingerprint': 'same-artifact'}
    rt.longtask.finish(sid)
    assert rt.longtask_state(sid)['state'] == 'needs_user'
    assert rt.longtask_state(sid)['blockedReason'] == 'LONGTASK_NO_PROGRESS'
    rt, sid = runtime(tmp_path / 'gate')
    configure(rt, sid)
    rt.longtask.completion = lambda *_: {'state': 'completed', 'acceptanceSatisfied': True,
        'evidenceFingerprint': 'unit-pass', 'failedChecks': ['required-live']}
    assert rt.longtask.finish(sid)['state'] == 'needs_user'


def test_stop_epoch_late_result_and_single_writer(tmp_path):
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid)
    rt.longtask.store.reserve(run, 'inflight', 1, 1000)
    stopped = rt.longtask.store.barrier(sid, 'cancelled')
    assert stopped['stopEpoch'] == run['stopEpoch'] + 1
    assert rt.longtask.store.settle_segment(run, 'inflight', 20)
    assert rt.longtask.store.transition(run, 'completed')['state'] == 'cancelled'
    guard = ProfileWriterGuard(tmp_path / 'profile.db').acquire()
    try:
        code = '''from agentbox.agent_core.longtask_runtime import ProfileWriterGuard
import sys
ProfileWriterGuard(sys.argv[1]).acquire()
'''
        result = subprocess_code(code, tmp_path / 'profile.db')
        assert result.returncode != 0 and 'another harness' in result.stderr
    finally:
        guard.close()
    ProfileWriterGuard(tmp_path / 'profile.db').acquire().close()


def test_unsafe_missing_tool_cannot_restart_with_new_call_id(tmp_path, monkeypatch):
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.store.emit(sid, 'tool_start', {'id': 'old-call', 'name': 'terminal_exec',
                                     'args': {'command': 'unsafe fixture'}, 'replay': 'unsafe'})
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid)
    assert exc.value.code == 'LONGTASK_UNSAFE_INTERRUPTION'
    assert rt.executor.calls == []


def test_provider_metadata_stripped_without_mutating_stored_message(tmp_path):
    rt, sid = runtime(tmp_path)
    messages = [{'role': 'assistant', 'content': 'Summary', 'origin': 'synthetic_handoff',
                 'summaryGeneration': 22, 'sourceRanges': [{'startMessage': 1}]}]
    original = copy.deepcopy(messages)
    asyncio.run(rt.complete_model(sid, messages, [], rt.store.get(sid)['config']['route']))
    # FixtureModel instance is stored on runtime.model; inspect actual request after seam.
    model = next(value for value in rt.__dict__.values() if isinstance(value, FixtureModel))
    assert model.requests[-1][0] == [{'role': 'assistant', 'content': 'Summary'}]
    assert messages == original


def unsafe_seq(rt, sid):
    rt.store.emit(sid, 'tool_end', {'id': 'old-call', 'name': 'terminal_exec',
                                    'result': {'is_error': True, 'errorCode': 'TOOL_INTERRUPTED_UNSAFE'}})
    return rt.store.db.execute("SELECT MAX(seq) FROM events WHERE session_id=? AND kind='tool_end'",
                               (sid,)).fetchone()[0]


def test_owner_inspection_is_exact_revision_bound_and_invalidates_on_goal_change(tmp_path):
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid)
    seq = unsafe_seq(rt, sid)
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid)
    assert exc.value.code == 'LONGTASK_UNSAFE_INTERRUPTION'
    # A model-shaped call cannot inspect: the runtime demands the injected authority gate.
    rt.longtask.authority = None
    with pytest.raises(LongtaskError) as exc:
        asyncio.run(rt.longtask_action(sid, {'action': 'inspect', 'confirm': True, 'runId': run['runId'],
                                             'receiptRefs': [{'sessionId': sid, 'seq': seq}],
                                             'invocationId': 'inspect-1', 'expectedRevision': run['revision']}))
    assert exc.value.code == 'LONGTASK_STALE'
    rt.longtask.authority = lambda _sid, _run: binding(sid)
    # Foreign / inexact refs are refused and never erase the receipt.
    with pytest.raises(LongtaskError) as exc:
        asyncio.run(rt.longtask_action(sid, {'action': 'inspect', 'confirm': True, 'runId': run['runId'],
                                             'receiptRefs': [{'sessionId': sid, 'seq': seq + 999}],
                                             'invocationId': 'inspect-1', 'expectedRevision': run['revision']}))
    assert exc.value.code == 'LONGTASK_INSPECTION_INVALID'
    with pytest.raises(LongtaskError) as exc:
        asyncio.run(rt.longtask_action(sid, {'action': 'inspect', 'confirm': True, 'runId': run['runId'],
                                             'receiptRefs': [], 'invocationId': 'inspect-1',
                                             'expectedRevision': run['revision']}))
    assert exc.value.code == 'LONGTASK_INSPECTION_REQUIRED'
    # Explicit owner confirmation with the exact receipt ref unblocks THIS interruption.
    result = asyncio.run(rt.longtask_action(sid, {'action': 'inspect', 'confirm': True, 'runId': run['runId'],
                                                  'receiptRefs': [{'sessionId': sid, 'seq': seq}],
                                                  'invocationId': 'inspect-1', 'expectedRevision': run['revision']}))
    assert result['state'] == 'ready' and result['blockedReason'] is None
    assert rt.longtask.check(sid) is not None
    # A later capability/goal/contract change invalidates the inspection (no standing clearance).
    rt.store.db.execute('UPDATE longtask_runs SET goal_revision=goal_revision+1,revision=revision+1 WHERE run_id=?',
                        (run['runId'],))
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid)
    assert exc.value.code == 'LONGTASK_UNSAFE_INTERRUPTION'
    # Receipts survive: the unsafe tool_end is still there for the owner to read.
    assert rt.store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='tool_end'",
                               (sid,)).fetchone()[0] == 1


def test_owner_acceptance_requires_scoped_canonical_projection_not_a_model_promise(tmp_path):
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid)
    seq = unsafe_seq(rt, sid)
    inspect = {'action': 'inspect', 'confirm': True, 'runId': run['runId'],
               'receiptRefs': [{'sessionId': sid, 'seq': seq}],
               'invocationId': 'inspect-1', 'expectedRevision': run['revision']}
    asyncio.run(rt.longtask_action(sid, inspect))
    run = rt.longtask.store.get(sid)
    evidence = [{'kind': 'check', 'ref': 'unit:longtask'}]
    accept = {'action': 'accept', 'confirm': True, 'runId': run['runId'],
              'receiptRefs': [{'sessionId': sid, 'seq': seq}], 'evidenceRefs': evidence,
              'invocationId': 'accept-1', 'expectedRevision': run['revision']}
    with pytest.raises(LongtaskError) as exc:
        asyncio.run(rt.longtask_action(sid, accept))
    assert exc.value.code == 'LONGTASK_ACCEPTANCE_UNAVAILABLE'
    # A promise without scoped evidence fails closed even with the hook present.
    rt.longtask.owner_acceptance = lambda _sid, _run, body: {'acceptanceSatisfied': True,
                                                             'evidenceFingerprint': 'x'}
    with pytest.raises(LongtaskError) as exc:
        asyncio.run(rt.longtask_action(sid, accept))
    assert exc.value.code == 'LONGTASK_ACCEPTANCE_REQUIRED'
    rt.longtask.owner_acceptance = lambda _sid, _run, body: {
        'acceptanceSatisfied': True, 'evidenceFingerprint': 'unit-pass-1', 'evidenceRefs': evidence,
        'failedChecks': [], 'staleChecks': [], 'requiredActive': [], 'requiredBlocked': []}
    result = asyncio.run(rt.longtask_action(sid, accept))
    assert result['state'] == 'completed' and result['blockedReason'] is None
    # Same invocation replays the receipt instead of accepting twice.
    replay = asyncio.run(rt.longtask_action(sid, accept))
    assert replay == result
    assert rt.store.db.execute('SELECT COUNT(*) FROM longtask_inspections').fetchone()[0] == 2


def test_lease_claim_fences_concurrent_runners(tmp_path):
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid)
    claimed = rt.longtask.store.claim_turn(run, 'runner-a', time.time() + 60)
    assert claimed['leaseEpoch'] == run['leaseEpoch'] + 1
    again = rt.longtask.store.claim_turn(run, 'runner-a', time.time() + 60)
    assert again['leaseEpoch'] == claimed['leaseEpoch']
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.store.claim_turn(rt.longtask.store.get(sid), 'runner-b', time.time() + 60)
    assert exc.value.code == 'LONGTASK_LEASE_BUSY'
    rt.longtask.store.barrier(sid)
    assert rt.longtask.store.get(sid)['leaseEpoch'] == run['leaseEpoch'] + 2


def test_restart_recovery_seeds_only_evidence_checked_auto_runs(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.store.transition(rt.longtask.store.get(sid), 'running')
    rt.store.close()
    rt = HarnessRuntime(SessionStore(tmp_path / 'sessions.db'), FixtureExecutor(), FixtureModel([]))
    rt.longtask.authority = lambda _sid, _run: binding(sid)
    rt.longtask.completion = lambda _sid, _run: {'state': 'runnable', 'evidenceFingerprint': 'round-1'}
    report = asyncio.run(rt.recover_longtasks())
    assert report['spawned'] == 0 and report['alreadyRecovered'] is False
    run = rt.longtask.store.get(sid)
    assert run['state'] == 'ready' and run['leaseEpoch'] == 1
    pending = rt.longtask.store.db.execute("SELECT * FROM longtask_continuations WHERE state='pending'").fetchall()
    assert len(pending) == 1 and pending[0]['source_key'].startswith('restart:')
    assert asyncio.run(rt.recover_longtasks())['alreadyRecovered'] is True
    assert asyncio.run(rt.pump_longtasks())['admitted'] == 1
    assert asyncio.run(rt.pump_longtasks())['admitted'] == 0
    assert rt.longtask.store.db.execute("SELECT COUNT(*) FROM longtask_continuations").fetchone()[0] == 1
    kinds = [e['type'] for e in rt.store.events(sid)]
    # A continuation is a system wake with its own receipt kind: never a forged owner turn.
    assert kinds.count('longtask_continuation') == 1 and 'user' not in kinds


def test_restart_without_the_flag_never_continues(tmp_path, monkeypatch):
    monkeypatch.delenv('BOXFOX_LONGTASK_CONTINUITY', raising=False)
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.store.transition(rt.longtask.store.get(sid), 'running')
    rt.store.close()
    rt = HarnessRuntime(SessionStore(tmp_path / 'sessions.db'), FixtureExecutor(), FixtureModel([]))
    rt.longtask.authority = lambda _sid, _run: binding(sid)
    rt.longtask.completion = lambda _sid, _run: {'state': 'runnable', 'evidenceFingerprint': 'round-1'}
    asyncio.run(rt.recover_longtasks())
    run = rt.longtask.store.get(sid)
    assert run['state'] == 'paused' and run['blockedReason'] == 'LONGTASK_MANUAL_RESTART'
    assert rt.longtask.store.db.execute("SELECT COUNT(*) FROM longtask_continuations").fetchone()[0] == 0
    assert asyncio.run(rt.pump_longtasks())['admitted'] == 0


def test_history_seams_are_optional_and_never_break_a_turn(tmp_path, monkeypatch):
    rt, sid = runtime(tmp_path)
    # With the real surface wired, owner ingress records against the server-minted identity.
    record = rt.history_ingest(sid, {'role': 'user', 'content': 'x'}, 'k', owner=True)
    assert record and record.get('recordId')
    recorded = []
    class FakeHistory:
        def record_observation(self, sid, payload, *, source_key):
            recorded.append((sid, payload, source_key)); return {'recordId': 'r1'}
        def record_ingress(self, sid, payload, *, source_key, origin, actor_identity):
            recorded.append((sid, payload, source_key, origin, actor_identity)); return {'recordId': 'r2'}
    monkeypatch.setattr(SessionStore, 'history', property(lambda self: FakeHistory()))
    assert rt.history_ingest(sid, {'role': 'assistant', 'content': 'x'}, 'k')['recordId'] == 'r1'
    assert recorded and recorded[0][2] == 'k'
    owner = rt.history_ingest(sid, {'role': 'user', 'content': 'x'}, 'k2', owner=True)
    assert owner['recordId'] == 'r2' and recorded[-1][3] == 'owner_user' and recorded[-1][4]
    # A failing history store is logged, never fatal: the live turn keeps its own receipts.
    class BrokenHistory:
        def record_observation(self, sid, payload, *, source_key):
            raise RuntimeError('disk gone')
        def record_ingress(self, sid, payload, *, source_key, origin, actor_identity):
            raise RuntimeError('disk gone')
    monkeypatch.setattr(SessionStore, 'history', property(lambda self: BrokenHistory()))
    assert rt.history_ingest(sid, {'role': 'assistant', 'content': 'x'}, 'k') is None
    assert rt.history_ingest(sid, {'role': 'user', 'content': 'x'}, 'k', owner=True) is None


def test_an_owner_turn_rebases_the_run_on_the_new_owner_revision(tmp_path, monkeypatch):
    """Yêu cầu mới của chính chủ không được giết run: ghim lại rồi chạy tiếp.

    Đây là ca đã gặp thật: chủ cấu hình run, gửi lượt kế tiếp (ghi revision mới), lượt chết vì
    `LONGTASK_STALE`, `resume` trả 409 ngay, và cách duy nhất là `cancel` + lập run mới.
    """
    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid)
    moved = {**binding(sid), 'goalRevision': 2, 'contractRevision': 2, 'contractHash': 'hash-2'}
    rt.longtask.authority = lambda _sid, _run: moved
    rebased = rt.longtask.check(sid)
    assert rebased['goalRevision'] == 2 and rebased['binding']['contractHash'] == 'hash-2'
    assert rebased['revision'] == run['revision'] + 1
    assert rebased['state'] == 'ready'
    # Tự chạy tiếp thì KHÔNG re-base: correction của chủ làm continuation cũ stale.
    rt.longtask.authority = lambda _sid, _run: {**moved, 'goalRevision': 3, 'contractRevision': 3,
                                               'contractHash': 'hash-3'}
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid, autonomous=True)
    assert exc.value.code == 'LONGTASK_STALE'


def test_a_scope_change_is_still_stale_for_an_owner_turn(tmp_path, monkeypatch):
    """Đổi phạm vi (dự án/capability/allocation) vẫn chặn cứng, kể cả lượt của chủ."""
    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.authority = lambda _sid, _run: {**binding(sid), 'capabilityEpoch': 9}
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid)
    assert exc.value.code == 'LONGTASK_STALE'


def test_the_owner_can_repin_a_parked_run_and_a_too_small_allowance_is_named(tmp_path, monkeypatch):
    """Chủ phải có đường thoát cho run đã park, và hạn mức nhỏ hơn một lượt phải đọc ra đúng."""
    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.store.transition(rt.longtask.store.get(sid), 'needs_user', 'LONGTASK_STALE')
    rt.longtask.binding = lambda _sid, _body: {**binding(sid), 'goalRevision': 2, 'contractRevision': 2,
                                               'contractHash': 'hash-2'}
    repinned = rt.configure_longtask(sid, {'enabled': True, 'goalRevision': 2, 'invocationId': 'repin-1',
                                           'expectedRevision': rt.longtask.store.get(sid)['revision']})
    assert repinned['state'] == 'ready' and repinned['goalRevision'] == 2
    # Hạn mức nhỏ hơn trần một lượt, chưa tiêu gì: mã riêng, không phải "hết ngân sách".
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.store.reserve(rt.longtask.store.get(sid), 'segment-1', 1, 7200_000, manual=True)
    assert exc.value.code == 'LONGTASK_BUDGET_TOO_SMALL'


def test_manual_turn_allowed_while_waiting_and_finish_never_raises(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    rt, sid = runtime(tmp_path)
    run = configure(rt, sid)
    rt.longtask.store.transition(rt.longtask.store.get(sid), 'waiting_children')
    # Owner chat stays available while the run waits for children/jobs.
    assert rt.longtask.check(sid) is not None
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid, autonomous=True)
    assert exc.value.code == 'LONGTASK_BLOCKED'
    # A manual owner segment may still run; it flips the waiting run back to running.
    rt.longtask.store.reserve(rt.longtask.store.get(sid), 'manual-model', 1, 1000, manual=True)
    assert rt.longtask.store.get(sid)['state'] == 'running'
    # A pending owner decision parks the run at end of turn instead of failing the turn.
    persisted_card(rt, sid)
    rt.longtask.completion = lambda _sid, _run: {'state': 'runnable', 'evidenceFingerprint': 'round-1'}
    parked = rt.longtask.finish(sid)
    assert parked['state'] == 'needs_user' and parked['blockedReason'] == 'LONGTASK_PENDING_DECISION'
    assert rt.pending_decisions(sid)['decisions']
    # An owner-paused run refuses ordinary turns but accepts the explicit resume action.
    rt.longtask.store.barrier(sid)
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid)
    assert exc.value.code == 'LONGTASK_BLOCKED'


def test_a_pending_budget_card_keeps_the_run_answerable(tmp_path):
    """Thẻ ngân sách đang chờ thì lượt mới KHÔNG được hạ run khỏi `budget_exhausted`.

    Hạ xuống `needs_user` làm `budget_effect` từ chối (`DECISION_STALE: budget revision changed`) —
    thẻ không còn đường trả lời, mọi lượt sau của chủ đều 409 và cả phiên kẹt.
    """
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.store.transition(rt.longtask.store.get(sid), 'budget_exhausted', 'LONGTASK_BUDGET_EXHAUSTED')
    run = rt.longtask.store.get(sid)
    did = rt.longtask.budget_card(run)
    used = dict(run['budget'])
    assert rt.longtask.store.get(sid)['state'] == 'budget_exhausted'
    # Lượt của chủ khi thẻ còn treo: chặn bằng mã riêng, nhưng trạng thái run phải GIỮ NGUYÊN.
    with pytest.raises(LongtaskError) as exc:
        rt.longtask.check(sid)
    assert exc.value.code == 'LONGTASK_PENDING_DECISION'
    rt.longtask.block(sid, exc.value)
    assert rt.longtask.store.get(sid)['state'] == 'budget_exhausted'
    # Nhờ vậy thẻ vẫn trả lời được: cộng đúng delta đã lưu (không reset limit/used) rồi chạy tiếp.
    outcome = rt.resolve_decision(sid, did, 'extend', invocation_id='reply-1')
    after = rt.longtask.store.get(sid)
    assert outcome['choice'] == 'extend' and after['state'] == 'ready'
    assert after['budget']['totalStepLimit'] == used['totalStepLimit'] * 2
    assert after['budget']['activeTimeLimitMs'] == used['activeTimeLimitMs'] * 2
    assert after['budget']['revision'] == used['revision'] + 1
    assert rt.pending_decisions(sid)['decisions'] == []


def test_cancelling_a_run_with_a_pending_budget_card_closes_the_card(tmp_path):
    """Chủ huỷ chạy khi thẻ ngân sách còn treo: run đóng, thẻ đóng theo, không 409 sau khi đã huỷ."""
    rt, sid = runtime(tmp_path)
    configure(rt, sid)
    rt.longtask.store.transition(rt.longtask.store.get(sid), 'budget_exhausted', 'LONGTASK_BUDGET_EXHAUSTED')
    run = rt.longtask.store.get(sid)
    did = rt.longtask.budget_card(run)
    result = asyncio.run(rt.longtask_action(sid, {'action': 'cancel', 'runId': run['runId'],
                                                 'expectedRevision': run['revision'], 'invocationId': 'cancel-1'}))
    assert result['state'] == 'cancelled'
    assert rt.decision_store.get(sid, did)['status'] == 'cancelled'
    assert rt.pending_decisions(sid)['decisions'] == []
