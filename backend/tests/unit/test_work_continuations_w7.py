"""A2 direct continuation under root rights; real runtime with a scripted model."""
import asyncio
import json
import re

import pytest

from agentbox.agent_core import work_graph, work_feedback, work_continuations
from test_work_graph import build, answer
from test_work_feedback_w7 import QUESTIONS


def call(name, args, ident='call'):
    return {'choices': [{'message': {'tool_calls': [{'id': ident, 'type': 'function',
        'function': {'name': name, 'arguments': json.dumps(args)}}]}, 'finish_reason': 'tool_calls'}]}


class Model:
    def __init__(self):
        self.gate = None
        self.resumed = asyncio.Event()
        self.root_calls = 0
        self.reopen = True

    async def complete(self, messages, tools, route, **kwargs):
        first = next(m['content'] for m in messages if m['role'] == 'user')
        if not first.startswith('Work Graph'):
            self.root_calls += 1
            raise AssertionError('no main model relay for a granted continuation')
        index = max(i for i, m in enumerate(messages) if m['role'] == 'user')
        current = messages[index:]
        opened = any(m.get('name') == 'file_read' for m in current)
        if 'Independent R2' in first:
            if not opened:
                return call('file_read', {'path': 'src/a.py'})
            await self.gate.wait()
            return answer('Independent R2 finished from src/a.py:1.')
        if index > next(i for i, m in enumerate(messages) if m['role'] == 'user'):
            req = re.search(r'"requestId": "([^"]+)"', current[0]['content']).group(1)
            if not any(m.get('name') == 'work_report' for m in current):
                return call('work_report', {'action': 'read', 'requestId': req}, 'read-answers')
            if not opened and self.reopen:
                return call('file_read', {'path': 'src/a.py'}, 'read-current-source')
            self.resumed.set()
            if self.gate and 'Independent R2' not in first:
                await self.gate.wait()
            return answer('Doctors will use the Offline exporter. Confirmed owner answers; src/a.py:1.')
        if not opened:
            return call('file_read', {'path': 'src/a.py'}, 'original-read')
        return call('work_report', {'action': 'needs_user', 'checkpoint': 'CSV source inspected; owner intent unknown.',
            'questions': QUESTIONS, 'decisionKeys': ['users', 'deploy']}, 'ask-owner')


def setup(tmp_path, second=False):
    store, rt, _, executor, sid = build(tmp_path)
    model = Model(); rt.client = model
    graph = work_graph.service(rt)
    nodes = [{'id': 'R1', 'kind': 'research', 'taskKind': 'lookup', 'title': 'Owner intent',
        'goal': 'Read source then confirm users and deployment of the CSV exporter',
        'acceptance': ['Use the owner answers and source'], 'dependsOn': []}]
    if second:
        nodes.append({'id': 'R2', 'kind': 'research', 'taskKind': 'lookup', 'title': 'Independent R2',
                      'goal': 'Independent R2: inspect unrelated source while R1 needs the owner'})
    run = graph.create(store.get(sid), {'goal': 'Research exporter intent only; no implementation',
                                      'flow': 'research', 'nodes': nodes})
    grant = graph.grants.action(store.get(sid), {'action': 'grant', 'runId': run['runId'],
        'revision': run['revision'], 'nodeId': 'R1', 'decisionKeys': ['users', 'deploy'],
        'publishInterview': True, 'resumeOnAnswers': True, 'invocationId': 'rights'})
    return store, rt, graph, run, sid, model, grant


def respond(rt, sid):
    card = rt.pending_for(sid)[0]
    return rt.resolve_decision(sid, card['decisionId'], 'submit', answers=[
        {'questionId': q['id'], 'optionId': q['options'][0]['id']} for q in card['questions']])


async def drain(rt, graph):
    await work_feedback.pump(rt)
    tasks = list(graph.continuations.tasks.values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), 5)


def test_direct_resume_same_child_with_busy_root_no_main_model_and_idempotent_pump(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path)
        first = await graph.run(store.get(sid), {'phase': 'discover'})
        req = graph.feedback.records(run['runId'])[0]
        assert first['outputs'][0]['status'] == 'needs_user'
        saved = respond(rt, sid)
        store.save(sid, store.get(sid)['messages'], 'running')  # unrelated main turn
        await work_feedback.pump(rt); await work_feedback.pump(rt)
        await asyncio.gather(*list(graph.continuations.tasks.values()))
        await work_feedback.pump(rt)
        state = graph.get(run['runId'])['nodes'][0]['stages']['produce']
        assert state['status'] == 'accepted' and state['rounds'][-1]['producerId'] == req['childId']
        assert len(store.children_of(sid)) == 1 and model.root_calls == 0
        assert len([e for e in store.events(req['childId']) if e['type'] == 'user']) == 2
        assert graph.feedback.get(req['requestId'])['status'] == 'consumed'
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'completed'
        assert not store.live_children(sid)
        assert rt.resolve_decision(sid, saved['decisionId'], 'submit', answers=[
            {'questionId': q['id'], 'optionId': q['options'][0]['id']} for q in req['questions']]) == saved
    asyncio.run(run_test())


def test_answer_wakes_live_scheduler_before_independent_branch_finishes(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path, second=True)
        model.gate = asyncio.Event()
        operation = asyncio.create_task(graph.run(store.get(sid), {'phase': 'discover'}))
        for _ in range(100):
            if rt.pending_for(sid):
                break
            await asyncio.sleep(.01)
        assert rt.pending_for(sid)
        respond(rt, sid)
        await work_feedback.pump(rt)  # wakes existing owner; does not create a competing worker
        await asyncio.wait_for(model.resumed.wait(), 3)
        assert not operation.done() and not graph.continuations.tasks
        assert graph.current(run['runId'])['nodes'][1]['stages']['produce']['status'] == 'running'
        model.gate.set(); result = await asyncio.wait_for(operation, 5)
        assert all(n['stages']['produce'] == 'accepted' for n in result['nodes'])
        assert len(store.children_of(sid)) == 2 and model.root_calls == 0
    asyncio.run(run_test())


@pytest.mark.parametrize('control', ['revoke', 'stop', 'cancel_request', 'closed', 'paused', 'off'])
def test_control_before_admission_cannot_start_a_child(tmp_path, monkeypatch, control):
    async def run_test():
        store, rt, graph, run, sid, model, rights = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'}); respond(rt, sid)
        req = graph.feedback.records(run['runId'])[0]
        if control == 'revoke':
            graph.grants.action(store.get(sid), {'action': 'revoke', 'grantId': rights['grantId'],
                'revision': 1, 'invocationId': 'revoke'})
        elif control == 'stop':
            await rt.stop(sid)
        elif control == 'cancel_request':
            doc = graph.feedback.get(req['requestId'])
            args = {'action': 'cancel', 'requestId': doc['requestId'], 'revision': doc['revision'], 'invocationId': 'cancel'}
            assert graph.feedback.main_action(store.get(sid), args)['status'] == 'cancelled'
            assert graph.feedback.main_action(store.get(sid), args)['status'] == 'cancelled'
        elif control in ('closed', 'paused'):
            run = graph.get(run['runId']); run['status'] = 'cancelled' if control == 'closed' else 'paused'; graph.save(run)
        else:
            monkeypatch.setenv('BOXFOX_WORK_GRAPH', 'off')
        await drain(rt, graph)
        assert not model.resumed.is_set() and model.root_calls == 0
        assert len([e for e in store.events(req['childId']) if e['type'] == 'user']) == 1
        if control in ('paused', 'off'):
            assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'pending'
    asyncio.run(run_test())


def test_root_turn_cleanup_preserves_worker_but_root_stop_cancels_it(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'}); respond(rt, sid)
        req = graph.feedback.records(run['runId'])[0]
        model.gate = asyncio.Event()
        await work_feedback.pump(rt)
        await asyncio.wait_for(model.resumed.wait(), 3)
        assert graph.continuations.owns_child(req['childId'])
        assert await rt.reap_children(sid) == []
        assert not rt.tasks[req['childId']].done()
        await rt.stop(sid)
        assert graph.feedback.get(req['requestId'])['status'] == 'cancelled'
        assert not store.live_children(sid) and not graph.continuations.children
        graph.feedback.consume(req)  # stale callback must not resurrect cancellation
        assert graph.feedback.get(req['requestId'])['status'] == 'cancelled'
    asyncio.run(run_test())


def test_restart_retries_pre_admission_claim_but_not_uncertain_admission(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'}); respond(rt, sid)
        req = graph.feedback.records(run['runId'])[0]
        with store.db: store.db.execute("UPDATE work_feedback_outbox SET status='claimed'")
        rt.work_graph = work_graph.WorkGraph(rt); graph = rt.work_graph
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'pending'
        await drain(rt, graph)
        assert graph.feedback.get(req['requestId'])['status'] == 'consumed'
        with store.db:
            doc = graph.feedback.get(req['requestId']); doc['status'] = 'resuming'; graph.feedback.save(doc)
            store.db.execute("UPDATE work_feedback_outbox SET status='claimed'")
        rt.work_graph = work_graph.WorkGraph(rt); graph = rt.work_graph
        assert graph.feedback.get(req['requestId'])['status'] == 'interrupted'
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'interrupted'
        await drain(rt, graph)
        assert len([e for e in store.events(req['childId']) if e['type'] == 'user']) == 2
    asyncio.run(run_test())


def test_new_admission_cannot_reuse_old_final_test_or_artifact_read(tmp_path):
    from agentbox.agent_core import work_checks
    async def run_test():
        store, rt, graph, run, sid, _, _ = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'})
        req = graph.feedback.records(run['runId'])[0]; cid = req['childId']
        meta = await graph.artifacts.put(run, 'R1', 'produce', 'Old draft', {}, True, 'other')
        config = store.get(cid)['config']
        config['workBinding'].update(checkId='check-old', artifactIds=[meta['artifactId']])
        store.update_config(cid, config)
        graph.artifacts.read(store.get(cid), {'artifactId': meta['artifactId']})
        store.emit(cid, 'assistant', {'final': True, 'text': 'Old green final'})
        store.emit(cid, 'tool_end', {'name': 'terminal_exec', 'args': {'command': 'pytest targeted'},
                                   'result': {'content': '1 passed', 'exit_code': 0}})
        assert graph.child_answer(cid) and work_checks.test_proof(graph, cid, ['pytest targeted'])
        assert graph.artifacts.covered('check-old', meta, cid)
        config['workBinding']['admissionSeq'] = store.db.execute('SELECT MAX(seq) FROM events WHERE session_id=?', (cid,)).fetchone()[0]
        store.update_config(cid, config)
        assert not graph.child_answer(cid) and not work_checks.test_proof(graph, cid, ['pytest targeted'])
        assert not graph.artifacts.covered('check-old', meta, cid)
    asyncio.run(run_test())


@pytest.mark.parametrize('control', ['revoke', 'cancel_request'])
def test_control_during_admission_keeps_checkpoint_and_prevents_restart(tmp_path, control):
    async def run_test():
        store, rt, graph, run, sid, model, rights = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'}); respond(rt, sid)
        req = graph.feedback.records(run['runId'])[0]; model.gate = asyncio.Event()
        await work_feedback.pump(rt); await asyncio.wait_for(model.resumed.wait(), 3)
        if control == 'revoke':
            graph.grants.action(store.get(sid), {'action': 'revoke', 'grantId': rights['grantId'],
                'revision': 1, 'invocationId': 'revoke-running'})
        else:
            doc = graph.feedback.get(req['requestId'])
            graph.feedback.main_action(store.get(sid), {'action': 'cancel', 'requestId': doc['requestId'],
                'revision': doc['revision'], 'invocationId': 'cancel-running'})
        await asyncio.gather(*list(graph.continuations.tasks.values()), return_exceptions=True)
        await drain(rt, graph)
        assert graph.feedback.get(req['requestId'])['status'] == ('interrupted' if control == 'revoke' else 'cancelled')
        assert graph.get(run['runId'])['nodes'][0]['stages']['produce']['status'] == 'needs_user'
        assert not store.live_children(sid)
        assert len([e for e in store.events(req['childId']) if e['type'] == 'user']) == 2
    asyncio.run(run_test())


def test_new_user_decision_cannot_auto_bless_an_old_reviewed_artifact(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'})
        req = graph.feedback.records(run['runId'])[0]
        with store.db:
            req['binding'].update(purpose='review', checkKind='evidence')
            req['fingerprint'] = graph.feedback.fingerprint(graph.get(run['runId']), req['binding'])
            graph.feedback.save(req)
        # A checker grant is legitimate, but the answer changes the producer
        # decision binding: report this decision to main instead of passing it.
        rights = graph.grants.action(store.get(sid), {'action': 'grant', 'runId': run['runId'],
            'revision': graph.get(run['runId'])['revision'], 'nodeId': 'R1', 'purpose': 'review',
            'checkKind': 'evidence', 'decisionKeys': ['users', 'deploy'],
            'publishInterview': True, 'resumeOnAnswers': True, 'invocationId': 'checker-rights'})
        with store.db:
            req['grantId'] = rights['grantId']; graph.feedback.save(req)
        respond(rt, sid); await drain(rt, graph)
        assert not model.resumed.is_set() and model.root_calls == 0
        row = store.db.execute('SELECT * FROM work_feedback_outbox').fetchone()
        assert row['status'] == 'blocked' and 'WORK_CHECK_INPUT_CHANGED' in row['doc']
        notices = [e['data'] for e in store.events(sid) if e['type'] == 'work_notice']
        assert notices[-1]['type'] == 'main_decision_required'
    asyncio.run(run_test())


def test_watchdog_preserves_owned_worker_with_idle_root_but_keeps_wall_guard(tmp_path):
    from agentbox.agent_core.peer_watchdog import PeerWatchdog
    import time
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'}); respond(rt, sid)
        model.gate = asyncio.Event()
        await work_feedback.pump(rt); await asyncio.wait_for(model.resumed.wait(), 3)
        req = graph.feedback.records(run['runId'])[0]
        watch = PeerWatchdog(store, rt, wall_max=60, now=time.time)
        watch.first_scan = False
        assert store.get(sid)['status'] == 'idle'
        assert watch.sweep() == {'timeout': [], 'orphan': [], 'restart': [], 'forced': []}
        with store.db:
            store.db.execute('UPDATE children SET started=? WHERE session_id=?', (time.time()-61, req['childId']))
        assert watch.sweep()['timeout'] == [req['childId']]
        await asyncio.gather(*list(graph.continuations.tasks.values()), return_exceptions=True)
        assert store.child(req['childId'])['reason'] == 'WATCHDOG_TIMEOUT'
        assert graph.feedback.get(req['requestId'])['status'] == 'interrupted'
        assert not store.live_children(sid)
    asyncio.run(run_test())


def test_producer_retains_observed_checkpoint_sources_without_researching_again(tmp_path):
    from agentbox.agent_core import work_checks
    async def run_test():
        store, rt, graph, run, sid, model, _ = setup(tmp_path)
        model.reopen = False
        await graph.run(store.get(sid), {'phase': 'discover'}); respond(rt, sid)
        req = graph.feedback.records(run['runId'])[0]
        await drain(rt, graph)
        assert graph.get(run['runId'])['nodes'][0]['stages']['produce']['status'] == 'accepted'
        cid = req['childId']
        assert not work_checks.good_reads(graph, cid)  # reviewers need current evidence
        assert work_checks.good_reads(graph, cid, retained_checkpoint=True)
        calls = [e for e in store.events(cid) if e['type'] == 'tool_end' and e['data']['name'] == 'file_read']
        assert len(calls) == 1  # actual original read, never fabricate a second read
        changed = graph.get(run['runId']); changed['nodes'][0]['goal'] = 'Research a different fact not covered by the checkpoint'
        graph.save(changed)
        assert not work_checks.good_reads(graph, cid, retained_checkpoint=True)
    asyncio.run(run_test())


@pytest.mark.parametrize('control', ['stop', 'cancel_request', 'stale'])
def test_cancelled_or_stale_card_has_one_resolution_event_and_no_fake_answer(tmp_path, control):
    async def run_test():
        store, rt, graph, run, sid, _, _ = setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'})
        req = graph.feedback.records(run['runId'])[0]; card = rt.pending_for(sid)[0]
        if control == 'stop':
            await rt.stop(sid); await rt.stop(sid)
        elif control == 'cancel_request':
            args = {'action': 'cancel', 'requestId': req['requestId'], 'revision': req['revision'], 'invocationId': 'close-card'}
            graph.feedback.main_action(store.get(sid), args); graph.feedback.main_action(store.get(sid), args)
        else:
            run = graph.get(run['runId']); run['nodes'][0]['goal'] = 'Changed assignment outside the original interview'; graph.save(run)
            for _ in range(2):
                with pytest.raises(work_feedback.FeedbackError, match='STALE'):
                    graph.feedback.validate(graph.feedback.get(req['requestId']))
        resolutions = [e['data'] for e in store.events(sid) if e['type'] == 'decision_resolved']
        assert len(resolutions) == 1 and resolutions[0]['decisionId'] == card['decisionId']
        assert resolutions[0]['status'] == 'cancelled' and resolutions[0]['choice'] is None
        assert not resolutions[0]['answers'] and not rt.pending_for(sid)
        assert graph.feedback.get(req['requestId'])['answers'] == []
    asyncio.run(run_test())
