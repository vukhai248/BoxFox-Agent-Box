"""A4 retest context: new code needs new admission reads and command receipts."""
import asyncio
import hashlib
import json
import time

import pytest

from agentbox.agent_core import work_checks, work_graph
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_work_graph import build, raw_tool, answer


NODE = {'id': 'B1', 'kind': 'build', 'title': 'Exporter',
        'goal': 'Fix exporter while preserving Unicode contents', 'acceptance': ['Preserve Unicode'],
        'tests': ['vitest ChatHeader.test.tsx']}


def fixture(tmp_path):
    path = tmp_path / 'src' / 'a.py'; path.parent.mkdir(); path.write_text('version = 1\n')
    mode = {'verdict': 'revise', 'testExit': 1, 'skipTest': False, 'skipReads': False}
    store, rt, model, executor, sid = build(tmp_path,
        lambda kind, prompt: ('Failure observed\nVERDICT: ' + mode['verdict']) if kind == 'review'
        else 'Patch handoff: src/a.py:1.\n## Knowledge requests\n- none')
    model.latest_assignment = True
    execute = executor.execute

    async def actual_snapshot(name, args, *rest, **kwargs):
        if name == 'terminal_exec' and args['command'] == work_checks.SNAPSHOT_COMMAND:
            return {'content': json.dumps({'schema': 'work-code/1',
                'hash': hashlib.sha256(path.read_bytes()).hexdigest(), 'head': 'fixture', 'criticalChanges': False}), 'exit_code': 0}
        if name == 'terminal_exec' and args['command'] == NODE['tests'][0]:
            executor.calls.append((name, args))
            return {'content': '1 passed' if mode['testExit'] == 0 else '1 failed', 'exit_code': mode['testExit']}
        if name == 'file_read':
            return {'content': path.read_text()}
        return await execute(name, args, *rest, **kwargs)
    executor.execute = actual_snapshot
    complete = model.complete

    async def control(messages, tools, route, **kwargs):
        result = await complete(messages, tools, route, **kwargs)
        choice = result['choices'][0]
        calls = choice.get('message', {}).get('tool_calls')
        if calls:
            kept = [c for c in calls if not (mode['skipTest'] and c['function']['name'] == 'terminal_exec')
                    and not (mode['skipReads'] and c['function']['name'] == 'work_artifact_read')]
            if kept != calls:
                if kept:
                    choice['message']['tool_calls'] = kept
                else:
                    coverage = [{'id': k, 'status': 'pass', 'target': 'artifact', 'evidence': 'claims only'} for k in ('A1', 'C1')]
                    return answer('```json\n' + json.dumps({'coverage': coverage}) + '\n```\nVERDICT: ok')
        return result
    model.complete = control
    return store, rt, model, executor, sid, path, mode


async def draft(rt, sid):
    graph = work_graph.service(rt); run = graph.active(sid)
    if run is None:
        run = graph.create(rt.store.get(sid), {'goal': 'Fix exporter while preserving Unicode', 'flow': 'fix', 'nodes': [NODE]})
    run['status'] = 'approved'; run['nodes'][0]['stages']['execute']['status'] = 'pending'; graph.save(run)
    result = await raw_tool(rt, sid, 'work_run', {'phase': 'execute'})
    return result['nodes'][0]['artifacts']['execute']


async def check(rt, sid, meta, invocation):
    result = await raw_tool(rt, sid, 'work_check', {'action': 'start', 'nodeId': 'B1', 'stage': 'execute',
        'artifactId': meta['artifactId'], 'invocationId': invocation})
    return result['checks'][0]


def test_new_code_retests_same_testing_child_and_preserves_context_lifetime(tmp_path):
    async def run():
        store, rt, _, _, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'red')
        assert first['status'] == 'revise'
        cid = first['childId']; old = store.get(cid); spent = store.child_usage_from_events(cid)
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        second_meta = await draft(rt, sid); second = await check(rt, sid, second_meta, 'green')
        assert second['status'] == 'pass' and second['childId'] == cid
        assert second['retestOf'] == first['checkId'] and second['admissionSeq'] > first['admissionSeq']
        assert second['binding']['codeSnapshot']['hash'] != first['binding']['codeSnapshot']['hash']
        first_meta = rt.work_graph.artifacts.get(first['runId'], first['artifactId'])[0]
        assert second_meta['originTurnId'] == first_meta['originTurnId']
        assert store.get(cid)['parent_id'] == old['parent_id']
        assert len([m for m in store.get(cid)['messages'] if m['role'] == 'user']) == 2
        assert store.child_usage_from_events(cid)[0] > spent[0]
        assert work_checks.test_proof(rt.work_graph, cid, NODE['tests'])
        assert rt.work_graph.artifacts.covered(second['checkId'], second_meta, cid)
        count = len(store.children_of(sid)); replay = await check(rt, sid, second_meta, 'green')
        assert replay['checkId'] == second['checkId'] and len(store.children_of(sid)) == count
    asyncio.run(run())


@pytest.mark.parametrize('miss', ['command', 'artifact'])
def test_old_green_proof_cannot_pass_new_code_without_current_command_and_reads(tmp_path, miss):
    async def run():
        store, rt, _, _, sid, path, mode = fixture(tmp_path); mode.update(verdict='ok', testExit=0)
        first = await check(rt, sid, await draft(rt, sid), 'old-green')
        assert first['status'] == 'pass'
        path.write_text('version = 2\n'); mode.update(skipTest=miss == 'command', skipReads=miss == 'artifact')
        second = await check(rt, sid, await draft(rt, sid), 'claims-green')
        assert second['childId'] == first['childId'] and second['status'] == 'unverified'
        assert ('test command' if miss == 'command' else 'artifact ranges') in second['error']
        assert rt.work_graph.get(first['runId'])['nodes'][0]['stages']['execute']['status'] != 'accepted'
    asyncio.run(run())


def test_old_green_then_actual_red_code_reuses_tester_but_keeps_failure(tmp_path):
    async def run():
        _, rt, _, _, sid, path, mode = fixture(tmp_path); mode.update(verdict='ok', testExit=0)
        first = await check(rt, sid, await draft(rt, sid), 'old-green')
        path.write_text('version = 2\n'); mode.update(verdict='revise', testExit=1)
        second = await check(rt, sid, await draft(rt, sid), 'new-red')
        assert second['status'] == 'revise' and second['childId'] == first['childId']
        assert not work_checks.test_proof(rt.work_graph, second['childId'], NODE['tests'])
    asyncio.run(run())


@pytest.mark.parametrize('change', ['same_code', 'scope', 'cancelled', 'legacy', 'latest_unknown'])
def test_incompatible_latest_tester_is_not_implicitly_reused(tmp_path, change):
    async def run():
        store, rt, _, _, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'first')
        if change != 'same_code': path.write_text('version = 2\n')
        if change == 'cancelled':
            # A cancelled historical admission, not Stop on an already finished task.
            store.db.execute("UPDATE children SET status='cancelled' WHERE session_id=?", (first['childId'],)); store.db.commit()
        if change == 'legacy': first.pop('testerAssignment'); rt.work_graph.checks.save(first)
        if change == 'latest_unknown':
            unknown = first | {'checkId': 'c-unknown', 'status': 'error', 'startedAt': time.time()}
            unknown.pop('childId')
            store.db.execute('INSERT INTO work_checks VALUES(?,?,?,?,?)',
                ('c-unknown', first['runId'], 'unknown', 'fixture', json.dumps(unknown))); store.db.commit()
        if change == 'scope':
            run = rt.work_graph.active(sid); run['nodes'][0]['acceptance'].append('New required behavior'); rt.work_graph.save(run)
        mode.update(verdict='ok', testExit=0)
        second = await check(rt, sid, await draft(rt, sid), 'next')
        assert second['childId'] != first['childId'] and 'retestOf' not in second
    asyncio.run(run())


def test_restart_reuses_sqlite_tester_without_old_command_proof(tmp_path):
    async def run():
        store, rt, model, executor, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'first')
        store.db.close(); fresh = SessionStore(tmp_path / 'sessions.db'); rt = HarnessRuntime(fresh, executor, model)
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        second = await check(rt, sid, await draft(rt, sid), 'after-restart')
        assert second['status'] == 'pass' and second['childId'] == first['childId']
        assert second['admissionSeq'] > first['admissionSeq']
    asyncio.run(run())


def test_reused_tester_loses_owner_revoked_tools_and_respects_new_ceiling(tmp_path):
    async def run():
        store, rt, _, _, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'first')
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        meta = await draft(rt, sid); cfg = store.get(sid)['config']
        cfg['tools'] = [n for n in cfg['tools'] if n != 'web_fetch']; cfg['maxSteps'] = 6; store.update_config(sid, cfg)
        second = await check(rt, sid, meta, 'restricted')
        assert second['childId'] == first['childId']
        config = store.get(second['childId'])['config']
        assert 'web_fetch' not in config['tools'] and config['workBudget']['effectiveMaxSteps'] == 6
    asyncio.run(run())


@pytest.mark.parametrize('change', ['code', 'pause', 'stop', 'disabled', 'terminal'])
def test_retest_revalidates_code_scope_and_permissions_after_slot_wait(tmp_path, change):
    async def run():
        store, rt, _, executor, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'first')
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        meta = await draft(rt, sid); started = asyncio.Event(); release = asyncio.Event()
        acquire = rt.acquire_child_slot
        async def parked(owner):
            started.set(); await release.wait(); await acquire(owner)
        rt.acquire_child_slot = parked
        before = store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='user'", (first['childId'],)).fetchone()[0]
        job = asyncio.create_task(check(rt, sid, meta, 'queued')); await asyncio.wait_for(started.wait(), 5)
        if change == 'code': path.write_text('version = 3\n')
        if change == 'pause':
            run_doc = rt.work_graph.active(sid); run_doc['status'] = 'paused'; rt.work_graph.save(run_doc)
        if change == 'stop': await rt.stop(sid)
        if change in ('disabled', 'terminal'):
            cfg = store.get(sid)['config']
            if change == 'disabled': cfg['subagents'] = [r | {'enabled': False} if r['id'] == 'testing' else r for r in cfg['subagents']]
            else: cfg['tools'] = [t for t in cfg['tools'] if t != 'terminal_exec']
            store.update_config(sid, cfg)
        release.set()
        with pytest.raises(ValueError, match='WORK_RETEST_STALE|WORK_CHECK_UNAVAILABLE'): await job
        after = store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='user'", (first['childId'],)).fetchone()[0]
        assert after == before and rt.work_graph.progress.records(meta['runId'])[-1]['status'] == ('cancelled' if change == 'stop' else 'aborted')
        assert len([c for c in executor.calls if c[0] == 'terminal_exec' and c[1]['command'] == NODE['tests'][0]]) == 1
    asyncio.run(run())


def test_tester_terminal_side_effect_stales_new_snapshot(tmp_path):
    async def run():
        _, rt, _, executor, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'first')
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        meta = await draft(rt, sid); original = executor.execute
        async def mutate(name, args, *rest, **kwargs):
            result = await original(name, args, *rest, **kwargs)
            if name == 'terminal_exec' and args['command'] == NODE['tests'][0]: path.write_text('version = 3\n')
            return result
        executor.execute = mutate
        second = await check(rt, sid, meta, 'changed-during-test')
        assert second['childId'] == first['childId'] and second['status'] == 'superseded'
    asyncio.run(run())


def test_preassigned_testing_retests_same_child_without_main_relay_or_debug(tmp_path):
    from test_work_handoffs_w8 import drain
    async def run():
        store, rt, model, _, sid, path, mode = fixture(tmp_path)
        graph = work_graph.service(rt)
        run_doc = graph.create(store.get(sid), {'goal': 'Fix exporter while preserving Unicode', 'flow': 'fix', 'nodes': [NODE]})
        run_doc['status'] = 'approved'; graph.save(run_doc)
        graph.graph(store.get(sid), {'action': 'assign_handoff', 'runId': run_doc['runId'],
            'revision': run_doc['revision'], 'nodeId': 'B1', 'stage': 'execute',
            'predicate': 'code_snapshot_ready', 'target': {'kind': 'check', 'checkIds': ['tests']}, 'invocationId': 'test-assignment'})
        await graph.run(store.get(sid), {'phase': 'execute'}); await drain(graph)
        first = graph.checks.records(run_doc['runId'])[-1]
        assert first['status'] == 'revise'
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        current = graph.get(run_doc['runId']); current['status'] = 'approved'
        current['nodes'][0]['stages']['execute']['status'] = 'pending'; graph.save(current)
        await graph.run(store.get(sid), {'phase': 'execute'}); await drain(graph)
        second = graph.checks.records(run_doc['runId'])[-1]
        assert second['status'] == 'pass' and second['childId'] == first['childId']
        assert all(kind != 'main' for kind, _ in model.prompts)
        assert all(c['role'] != 'debug' for c in store.children_of(sid))
        count = len(store.children_of(sid)); graph.handoffs.dispatch(); await drain(graph)
        assert len(store.children_of(sid)) == count
        assert len(graph.handoffs.actions(run_doc['runId'])) == 2
    asyncio.run(run())


def test_retest_budget_uses_new_input_size_profile_still_clamped_to_owner(tmp_path):
    async def run():
        store, rt, _, _, sid, path, mode = fixture(tmp_path)
        first = await check(rt, sid, await draft(rt, sid), 'short')
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        short = await draft(rt, sid); graph = rt.work_graph; run_doc = graph.active(sid)
        meta = await graph.artifacts.put(run_doc, 'B1', 'execute', 'Detailed handoff\n' * 2200, short['binding'], True)
        run_doc['nodes'][0]['stages']['execute']['artifact'] = meta; graph.save(run_doc)
        second = await check(rt, sid, meta, 'long')
        assert second['childId'] == first['childId'] and second['status'] == 'pass'
        budget = store.get(second['childId'])['config']['workBudget']
        assert budget['profile'] == 'review_long' and budget['requestedMaxSteps'] == 80
        assert budget['effectiveMaxSteps'] == min(80, store.get(sid)['config']['maxSteps'])
    asyncio.run(run())


@pytest.mark.parametrize('before,after', [(None, 8192), (8192, None)])
def test_current_owner_output_ceiling_applies_to_same_tester(tmp_path, before, after):
    async def run():
        store, rt, model, _, sid, path, mode = fixture(tmp_path)
        cfg = store.get(sid)['config']
        if before is not None: cfg['outputTokenCeiling'] = before
        store.update_config(sid, cfg)
        first = await check(rt, sid, await draft(rt, sid), 'first')
        path.write_text('version = 2\n'); mode.update(verdict='ok', testExit=0)
        meta = await draft(rt, sid); cfg = store.get(sid)['config']
        if after is not None: cfg['outputTokenCeiling'] = after
        else: cfg.pop('outputTokenCeiling', None)
        store.update_config(sid, cfg)
        second = await check(rt, sid, meta, 'new-ceiling')
        assert second['childId'] == first['childId'] and second['status'] == 'pass'
        assert model.tokens[-1][-1] == (after or 16000)
        assert store.get(second['childId'])['config'].get('outputTokenCeiling') == after
    asyncio.run(run())
