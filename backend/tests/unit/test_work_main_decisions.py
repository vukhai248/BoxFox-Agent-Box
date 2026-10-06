"""Typed main decision admissions: references, replay, stop and crash boundaries."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_feedback, work_graph
from agentbox.agent_core.work_decisions import Decisions
from test_work_feedback_w7 import setup, request, open_card
from test_work_graph import answer
from test_work_handoffs_w8 import setup as handoff_setup, assign, drain


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ; khóa tổng `BOXFOX_REFORM` đã bị xoá ở bước B5
# (HANDOFF §10.3) nên nhãn `legacy_path` không còn kèm env nào để pin.
pytestmark = pytest.mark.legacy_path


class Main:
    def __init__(self):
        self.calls = []
        self.gate = None

    async def complete(self, messages, tools, route, **kwargs):
        self.calls.append((messages, tools, route, kwargs))
        if self.gate:
            await self.gate.wait()
        return answer('Checkpoint preserved; no repair or acceptance asserted.')


async def finish(rt, graph):
    await work_feedback.pump(rt)
    jobs = list(rt.tasks.values())
    if jobs:
        await asyncio.gather(*jobs, return_exceptions=True)
    await asyncio.sleep(0)


def test_report_main_decision_busy_then_idle_once_with_refs_no_body_or_consent(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid)
        model = Main(); rt.client = model
        store.save(sid, [], 'running')
        for _ in range(3):
            await work_feedback.pump(rt)
        assert not model.calls and graph.decisions.records()[0]['status'] == 'pending'
        store.save(sid, [], 'idle')
        await finish(rt, graph)
        for _ in range(3):
            await finish(rt, graph)
        assert len(model.calls) == 1
        prompt = next(m['content'] for m in model.calls[0][0] if m['role'] == 'user')
        assert req['requestId'] in prompt and req['artifact']['path'] in prompt
        assert 'Research NN completed' not in prompt and 'Who uses the output?' not in prompt
        assert graph.feedback.get(req['requestId'])['status'] == 'waiting_main'
        assert graph.decisions.records()[0]['status'] == 'delivered'
        event = next(e['data'] for e in store.events(sid) if e['type'] == 'user')
        assert event['origin'] == 'harness' and event['workDecisionBatch'] == event['invocationId']
        assert 'Decision references' not in event['text'] and req['requestId'] not in event['text']
        assert 'Agent chính' in event['text']
        assert req['requestId'] in store.get(sid)['messages'][0]['content']
        assert not store.db.execute('SELECT * FROM work_feedback_invocations').fetchall()
        assert not graph.get(run['runId'])['executionRequested']
    asyncio.run(run())


@pytest.mark.parametrize('change', ['publish', 'cancel', 'scope', 'closed'])
def test_handled_or_stale_record_never_calls_main(tmp_path, change):
    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid)
        graph.decisions.reconcile()
        if change == 'publish':
            open_card(rt, graph, sid, req)
        elif change == 'cancel':
            graph.feedback.main_action(store.get(sid), {'action': 'cancel', 'requestId': req['requestId'],
                'revision': req['revision'], 'invocationId': 'main-cancel'})
        else:
            if change == 'scope':
                run['nodes'][0]['goal'] = 'A changed assignment needing totally different evidence'
            else:
                run['status'] = 'cancelled'
            graph.save(run)
        model = Main(); rt.client = model
        await finish(rt, graph)
        assert not model.calls
        assert all(d['status'] == 'superseded' for d in graph.decisions.records())
    asyncio.run(run_test())


@pytest.mark.parametrize('hold', ['paused', 'lock', 'off', 'awaiting_decision', 'live_task'])
def test_holds_do_not_spend_main_budget_and_resume_when_released(tmp_path, monkeypatch, hold):
    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        await request(rt, graph, cid)
        model = Main(); rt.client = model
        lock = graph.locks.setdefault(run['runId'], asyncio.Lock())
        task = None
        if hold == 'paused':
            run['status'] = 'paused'; graph.save(run)
        elif hold == 'lock':
            await lock.acquire()
        elif hold == 'off':
            monkeypatch.setenv('BOXFOX_WORK_GRAPH', 'off')
        elif hold == 'live_task':
            task = asyncio.create_task(asyncio.Event().wait()); rt.tasks[sid] = task
        else:
            store.save(sid, [], 'awaiting_decision')
        await work_feedback.pump(rt)
        assert not model.calls
        if hold == 'paused':
            run['status'] = 'drafting'; graph.save(run)
        elif hold == 'lock':
            lock.release()
        elif hold == 'off':
            monkeypatch.setenv('BOXFOX_WORK_GRAPH', 'on')
        elif hold == 'live_task':
            task.cancel(); await asyncio.gather(task, return_exceptions=True)
        else:
            store.save(sid, [], 'idle')
        await finish(rt, graph)
        assert len(model.calls) == 1
    asyncio.run(run_test())


def test_atomic_batch_claim_rollback_before_any_main_admission(tmp_path):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        await request(rt, graph, cid)
        store.db.execute("CREATE TRIGGER fault_batch BEFORE UPDATE ON work_main_decisions "
            "WHEN NEW.status='admitted' BEGIN SELECT RAISE(ABORT,'claim fault'); END")
        store.db.commit()
        model = Main(); rt.client = model
        with pytest.raises(Exception, match='claim fault'):
            await work_feedback.pump(rt)
        assert not model.calls and not store.db.execute('SELECT * FROM work_main_batches').fetchall()
        assert graph.decisions.records()[0]['status'] == 'pending'
        store.db.execute('DROP TRIGGER fault_batch'); store.db.commit()
        await finish(rt, graph)
        assert len(model.calls) == 1
    asyncio.run(run())


def test_lost_compare_and_swap_rolls_back_whole_batch_without_model(tmp_path):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        await request(rt, graph, cid)
        # Fault injection changes the decision between batch insert and CAS.
        store.db.execute("CREATE TRIGGER lost_claim AFTER INSERT ON work_main_batches BEGIN "
            "UPDATE work_main_decisions SET status='superseded'; END")
        store.db.commit()
        model = Main(); rt.client = model
        await work_feedback.pump(rt)
        assert not model.calls and not store.db.execute('SELECT * FROM work_main_batches').fetchall()
        assert graph.decisions.records()[0]['status'] == 'pending'
        store.db.execute('DROP TRIGGER lost_claim'); store.db.commit()
        await finish(rt, graph)
        assert len(model.calls) == 1
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['before', 'after_user', 'after_finish'])
def test_restart_recovers_before_start_but_never_replays_uncertain_main(tmp_path, boundary):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        await request(rt, graph, cid)
        original = rt.start
        def crash(owner, prompt, invocation_id):
            if boundary != 'before':
                store.emit(owner, 'user', {'text': prompt, 'invocationId': invocation_id, 'turn': 1})
            if boundary == 'after_finish':
                store.emit(owner, 'finish', {'status': 'completed', 'turn': 1})
            raise SystemExit('crash boundary')
        rt.start = crash
        with pytest.raises(SystemExit):
            await work_feedback.pump(rt)
        model = Main(); rt.client = model; rt.start = original
        graph.decisions = Decisions(graph)
        await finish(rt, graph)
        if boundary == 'before':
            assert len(model.calls) == 1 and graph.decisions.records()[0]['status'] == 'delivered'
        else:
            assert not model.calls
            assert graph.decisions.records()[0]['status'] == ('delivered' if boundary == 'after_finish' else 'interrupted')
    asyncio.run(run())


def test_root_stop_mutes_old_sources_and_callbacks_but_new_explicit_request_can_run(tmp_path):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid)
        model = Main(); model.gate = asyncio.Event(); rt.client = model
        await work_feedback.pump(rt)
        await asyncio.sleep(0)
        await rt.stop(sid)
        await asyncio.sleep(0)
        await finish(rt, graph)
        assert len(model.calls) == 1
        assert graph.decisions.records()[0]['status'] == 'cancelled'
        assert graph.feedback.get(req['requestId'])['status'] == 'cancelled'
        model.gate = None
        await graph.feedback.report(store.get(cid), {'action': 'checkpoint', 'checkpoint': 'New investigation after explicit restart',
            'invocationId': 'new-request'}, 'new-request')
        await finish(rt, graph)
        assert len(model.calls) == 2
    asyncio.run(run())


def test_manual_answer_joins_queue_and_legacy_receipt_never_replays(tmp_path):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        rt.resolve_decision(sid, card['decisionId'], 'decide')
        model = Main(); rt.client = model
        await finish(rt, graph)
        assert len(model.calls) == 1 and graph.decisions.records()[0]['kind'] == 'answer'
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'delivered'
        store.db.execute("UPDATE work_feedback_outbox SET status='pending'"); store.db.commit()
        await finish(rt, graph)
        assert len(model.calls) == 1
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'delivered'
    asyncio.run(run())


def test_test_red_delivers_one_decision_without_retrying_checker_or_debug(tmp_path):
    async def run():
        from test_work_graph import ok_script
        store, rt, model, _, sid, graph, rid = handoff_setup(tmp_path,
            lambda k, t: 'Unsupported recommendation.\nVERDICT: revise' if k == 'review' else ok_script(k, t))
        assign(graph, store, sid, rid)
        await graph.run(store.get(sid), {'phase': 'discover'}); await drain(graph)
        for _ in range(3):
            await finish(rt, graph)
        assert [k for k, _ in model.prompts] == ['produce', 'review', 'main']
        assert len(store.children_of(sid)) == 2
        assert graph.decisions.records(rid)[0]['status'] == 'delivered'
        assert graph.get(rid)['nodes'][0]['stages']['produce']['status'] == 'revise'
    asyncio.run(run())


def test_shared_decision_conflict_routes_main_preserving_original_card_and_answers(tmp_path):
    async def run():
        from test_work_continuations_w7 import setup as granted
        store, rt, graph, run, sid, _, _ = granted(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'})
        original = graph.feedback.records(run['runId'])[0]
        other = rt.create({'skills': []}, parent_id=sid, role='research', parent_tools=store.get(sid)['config']['tools'])
        config = other['config']; config['workBinding'] = original['binding']; store.update_config(other['id'], config)
        second = await graph.feedback.report(store.get(other['id']), {'action': 'needs_user',
            'checkpoint': 'A contradictory deployment request must not publish a second card.',
            'questions': [{'id': 'other', 'question': 'Cloud only?', 'options': ['Cloud', 'Dedicated cloud']}],
            'decisionKeys': ['deploy'], 'invocationId': 'conflict'}, 'conflict')
        assert second['status'] == 'waiting_main' and second['conflictingRequestId'] == original['requestId']
        assert len(rt.pending_for(sid)) == 1
        # Do not run the first child continuation here: only inspect the conflict queue.
        model = Main(); rt.client = model
        await finish(rt, graph)
        assert len(model.calls) == 1 and len(rt.pending_for(sid)) == 1
        prompt = next(m['content'] for m in model.calls[0][0] if m['role'] == 'user')
        assert second['requestId'] in prompt and original['requestId'] in prompt
        assert not graph.feedback.get(second['requestId'])['answers']
    asyncio.run(run())


def test_batch_bound_owner_isolation_and_canonical_recovery_without_events(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        await request(rt, graph, cid)
        binding = store.get(cid)['config']['workBinding']
        for index in range(9):
            child = rt.create({'skills': []}, parent_id=sid, role='research', parent_tools=store.get(sid)['config']['tools'])
            config = child['config']; config['workBinding'] = binding; store.update_config(child['id'], config)
            await graph.feedback.report(store.get(child['id']), {'action': 'checkpoint',
                'checkpoint': 'A distinct saved checkpoint ' + str(index), 'invocationId': 'distinct'}, 'distinct')
        # Lose publication notifications; canonical requests, not events, own recovery.
        store.db.execute("DELETE FROM events WHERE kind='work_feedback'"); store.db.commit()
        model = Main(); rt.client = model
        await finish(rt, graph)
        batches = store.db.execute('SELECT doc FROM work_main_batches ORDER BY rowid').fetchall()
        assert len(json.loads(batches[0][0])['decisionIds']) == 8
        await finish(rt, graph)
        assert len(model.calls) == 2 and len(graph.decisions.records()) == 10
        assert all(d['ownerId'] == sid and d['runId'] == run['runId'] for d in graph.decisions.records())
        other = rt.create({'skills': []})['id']
        with pytest.raises(ValueError, match='belongs to another'):
            graph.resolve(other, run['runId'])
        assert not graph.decisions.admission_metadata(other, store.db.execute('SELECT id FROM work_main_batches').fetchone()[0])
    asyncio.run(run())


def test_pending_queue_survives_actual_sqlite_close_and_reopen(tmp_path):
    async def run():
        from agentbox.agent_core.runtime import HarnessRuntime
        from agentbox.memory.session_store import SessionStore
        store, rt, graph, _, sid, cid = setup(tmp_path)
        await request(rt, graph, cid); graph.decisions.reconcile()
        before = graph.decisions.records()
        executor = rt.executor
        store.db.close()
        store = SessionStore(tmp_path / 'sessions.db'); model = Main()
        rt = HarnessRuntime(store, executor, model); graph = work_graph.service(rt)
        assert graph.decisions.records() == before
        await finish(rt, graph)
        assert len(model.calls) == 1 and graph.decisions.records()[0]['status'] == 'delivered'
    asyncio.run(run())


def test_graph_recovery_can_emit_view_before_any_continuation_or_main_start(tmp_path):
    store, rt, graph, run, sid, _ = setup(tmp_path)
    run['nodes'][0]['stages']['produce']['status'] = 'running'
    graph.save(run)
    rt.work_graph = None
    reopened = work_graph.service(rt)
    assert reopened.get(run['runId'])['nodes'][0]['stages']['produce']['status'] == 'pending'
    assert not reopened.decisions.records() and not rt.tasks
    event = next(e['data'] for e in reversed(store.events(sid)) if e['type'] == 'work_graph')
    assert event['revision'] == reopened.get(run['runId'])['revision']
    assert event['nodes'][0]['stages']['produce']['status'] == 'pending'


@pytest.mark.parametrize('finish_status', ['partial', 'failed', 'cancelled'])
def test_uncertain_or_failed_main_completion_is_retained_without_automatic_retry(tmp_path, finish_status):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        await request(rt, graph, cid)
        calls = []
        def failed(owner, prompt, invocation_id):
            calls.append(invocation_id)
            store.emit(owner, 'user', {'text': prompt, 'invocationId': invocation_id, 'turn': 1})
            async def task():
                store.emit(owner, 'finish', {'status': 'completed' if finish_status == 'partial' else finish_status,
                                            'partial': finish_status == 'partial', 'turn': 1})
            return asyncio.create_task(task())
        rt.start = failed
        await work_feedback.pump(rt)
        await asyncio.sleep(0); await asyncio.sleep(0)
        for _ in range(3):
            await work_feedback.pump(rt)
        assert len(calls) == 1 and graph.decisions.records()[0]['status'] == 'interrupted'
    asyncio.run(run())


def test_legacy_manual_answer_user_receipt_is_not_a_new_main_admission(tmp_path):
    async def run():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        rt.resolve_decision(sid, card['decisionId'], 'decide')
        job = store.db.execute('SELECT id FROM work_feedback_outbox').fetchone()[0]
        store.emit(sid, 'user', {'text': 'legacy resume', 'invocationId': job})
        model = Main(); rt.client = model
        await finish(rt, graph)
        assert not model.calls and not graph.decisions.records()
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0] == 'interrupted'
    asyncio.run(run())


def test_revoked_handoff_and_stop_after_worker_error_never_reanimate_main(tmp_path):
    async def run():
        from test_work_graph import ok_script
        store, rt, model, _, sid, graph, rid = handoff_setup(tmp_path,
            lambda k, t: 'Unsupported recommendation.\nVERDICT: revise' if k == 'review' else ok_script(k, t))
        assignment = assign(graph, store, sid, rid)
        await graph.run(store.get(sid), {'phase': 'discover'}); await drain(graph)
        graph.decisions.reconcile()
        graph.graph(store.get(sid), {'action': 'revoke_handoff', 'runId': rid,
            'transitionId': assignment['transitionId'], 'revision': assignment['revision'], 'invocationId': 'revoke'})
        await finish(rt, graph)
        assert [k for k, _ in model.prompts] == ['produce', 'review']
        assert graph.decisions.records()[0]['status'] == 'superseded'
        await rt.stop(sid)
        await finish(rt, graph)
        assert [k for k, _ in model.prompts] == ['produce', 'review']
    asyncio.run(run())


def test_unassigned_required_check_routes_main_but_explicit_handoff_runs_independently(tmp_path):
    async def run():
        store, rt, model, _, sid, graph, rid = handoff_setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'})
        assert graph.get(rid)['nodes'][0]['stages']['produce']['status'] == 'needs_checks'
        graph.decisions.reconcile()
        decision = graph.decisions.records()[0]
        # Bề mặt 7 (RESEARCH_GATEWAY) đã xoá: nút mẫu của handoff là `design` (một kiểm bắt buộc
        # `design_review`, người kiểm `plan-review`) thay cho nút `research` cũ.
        assert decision['kind'] == 'checks' and decision['refs']['missingCheckIds'] == ['design_review']
        # Main can assign the existing transition before a queued decision runs.
        assign(graph, store, sid, rid); await drain(graph)
        await finish(rt, graph)
        assert [k for k, _ in model.prompts] == ['produce', 'review']
        assert graph.decisions.records()[0]['status'] == 'superseded'
    asyncio.run(run())


def test_no_check_assignment_delivers_decision_without_choosing_checker_itself(tmp_path):
    async def run():
        store, rt, model, _, sid, graph, rid = handoff_setup(tmp_path)
        await graph.run(store.get(sid), {'phase': 'discover'})
        await finish(rt, graph)
        assert [k for k, _ in model.prompts] == ['produce', 'main']
        assert len(store.children_of(sid)) == 1
        assert graph.get(rid)['nodes'][0]['stages']['produce']['status'] == 'needs_checks'
        assert graph.decisions.records()[0]['status'] == 'delivered'
    asyncio.run(run())
