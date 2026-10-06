"""A3.3b.1: immutable paged refs, scoped coverage and recovery without prompt truncation."""
import asyncio
import copy
import json
import re

import pytest

from agentbox.agent_core import work_graph
from test_work_graph import Model, ok_script, answer
from test_work_input_closure import fixture


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ; khóa tổng `BOXFOX_REFORM` đã bị xoá ở bước B5
# (HANDOFF §10.3) nên nhãn `legacy_path` không còn kèm env nào để pin.
pytestmark = pytest.mark.legacy_path


class ManifestModel(Model):
    """Fixture reader discovers additional refs only after reading the full manifest."""
    def __init__(self, omit=None):
        super().__init__(ok_script)
        self.omit, self.packets = omit, []

    async def complete(self, messages, *args, **kwargs):
        messages = copy.deepcopy(messages)
        first = next(m for m in messages if m['role'] == 'user')
        start = re.search(r'\{"snapshots":', first['content']).start()
        packet, length = json.JSONDecoder().raw_decode(first['content'][start:])
        self.packets.append(packet)
        if packet.get('inputManifest'):
            aid = packet['inputManifest']['artifactId']
            pages = {}
            for m in messages:
                if m.get('name') == 'work_artifact_read':
                    result = json.loads(m['content'])
                    if result.get('artifactId') == aid:
                        pages[result['offset']] = result['content']
            if sum(len(s) for s in pages.values()) == packet['inputManifest']['chars']:
                manifest = json.loads(''.join(pages[o] for o in sorted(pages)))
                assert manifest['runId'] == packet['runId']
                expanded = packet | {'snapshots': packet['snapshots'] + manifest['snapshots']}
                first['content'] = first['content'][:start] + json.dumps(expanded) + first['content'][start + length:]
        result = await super().complete(messages, *args, **kwargs)
        if self.omit:
            message = result['choices'][0]['message']
            calls = message.get('tool_calls', [])
            omitted = packet['inputManifest']['artifactId'] if self.omit == 'manifest' else self.omit
            message['tool_calls'] = [c for c in calls if json.loads(c['function']['arguments']).get('artifactId') != omitted]
            if calls and not message['tool_calls']:
                return answer('```json\n{"coverage":[{"id":"C1","status":"pass","target":"artifact","evidence":"claimed"}]}\n```\nVERDICT: ok')
        message = result['choices'][0]['message']
        if message.get('tool_calls'):
            # Respect the existing per-step batch ceiling. A large assignment
            # needs several batches, not a production limit change for a fixture.
            message['tool_calls'] = message['tool_calls'][:8]
        return result


async def large_fixture(tmp_path):
    store, rt, _, sid, graph, run, node, sources, lookup, primary = await fixture(tmp_path, large=True)
    helpers = [lookup]
    for i in range(60):
        helpers.append(await graph.artifacts.put(run, node['id'], 'knowledge', f'Bound supporting note {i}',
                                                {'purpose': 'knowledge'}, True))
    primary = await graph.artifacts.put(run, node['id'], 'produce', 'Review this target only',
        primary['binding'] | {'lookupArtifactIds': [m['artifactId'] for m in helpers]}, True)
    return store, rt, sid, graph, run, node, sources, helpers, primary


async def judge(store, rt, sid, graph, run, node, primary, model=None):
    rt.client = model or ManifestModel()
    return await graph.checks.judge(store.get(sid), run, node, 'produce',
        {'id': 'evidence', 'executorRole': 'review'}, [primary], {'C1': 'Check original sources'}, {'checkId': 'manifest-check'})


def test_manifest_keeps_large_exact_assignment_and_large_content_readable(tmp_path):
    async def check():
        store, rt, sid, graph, run, node, sources, helpers, primary = await large_fixture(tmp_path)
        model = ManifestModel()
        result = await judge(store, rt, sid, graph, run, node, primary, model)
        assert result['status'] == 'pass', result
        manifest = result['inputManifest']
        assert manifest['chars'] > 16000
        child = store.get(result['childId'])
        binding = child['config']['workBinding']
        assert len(binding['artifactIds']) == 65
        assert binding['inputManifestId'] == manifest['artifactId']
        assert all(graph.artifacts.covered('manifest-check', graph.artifacts.get(run['runId'], a)[0], child['id'])
                   for a in binding['artifactIds'])
        assert sources[3]['artifactId'] not in binding['artifactIds']
        assert all(len(json.dumps(p, ensure_ascii=False)) < 16000 for p in model.packets)
        assert all(len(p['snapshots']) == 1 and 'inputArtifactIds' not in p for p in model.packets)
        prompt = model.prompts[-1][1]
        assert 'A model-step budget counts completions, not individual tool calls' in prompt
        assert 'original-source lookup cap does not cap assigned artifact reads' in prompt
        assert 'sampling apparently similar inputs cannot satisfy this contract' in prompt
        assert result['reviewTargetArtifactIds'] == [primary['artifactId']]
        assert set(result['inputArtifactIds']) == {m['artifactId'] for m in helpers + sources[:2]}
        events = [json.loads(r['payload']) for r in store.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='tool_end'", (child['id'],))]
        reads = [e['result'] for e in events if e['name'] == 'work_artifact_read']
        first_manifest = next(r for r in reads if r['artifactId'] == manifest['artifactId'])
        assert first_manifest['nextOffset'] and first_manifest['unreadArtifactCount'] == 65
        assert len(first_manifest['unreadArtifacts']) == 12 and first_manifest['unreadListTruncated']
        assert not first_manifest['allAssignedArtifactsRead']
        assert any(r['artifactId'] == sources[0]['artifactId'] and r['offset'] > 16000 for r in reads)
        assert reads[-1]['allAssignedArtifactsRead']
        with pytest.raises(PermissionError, match='WORK_ARTIFACT_SCOPE'):
            graph.artifacts.read(child, {'artifactId': sources[3]['artifactId']})
    asyncio.run(check())


@pytest.mark.parametrize('omit', ['source', 'manifest'])
def test_manifest_does_not_replace_reading_all_assigned_ranges(tmp_path, omit):
    async def check():
        store, rt, sid, graph, run, node, sources, _, primary = await large_fixture(tmp_path)
        result = await judge(store, rt, sid, graph, run, node, primary,
                             ManifestModel(omit=sources[0]['artifactId'] if omit == 'source' else 'manifest'))
        assert result['status'] == 'unverified' and 'ranges' in result['error'], result
        assert graph.artifacts.covered('manifest-check', result['inputManifest'], result['childId']) == (omit == 'source')
        assert not graph.artifacts.covered('manifest-check', sources[0], result['childId'])
    asyncio.run(check())


@pytest.mark.parametrize('change', ['before', 'during'])
def test_code_snapshot_guard_uses_target_not_the_new_manifest(tmp_path, change):
    from agentbox.agent_core import work_checks

    async def check():
        store, rt, sid, graph, run, node, _, _, primary = await large_fixture(tmp_path)
        node['kind'] = 'build'
        node['stages']['execute'] = copy.deepcopy(node['stages']['produce'])
        source = {'schema': 'work-code/1', 'hash': 'a' * 64, 'head': 'fixture'}
        primary = await graph.artifacts.put(run, node['id'], 'execute', 'Code handoff',
                                           primary['binding'] | {'codeSnapshot': source}, True)
        original, calls = rt.executor.execute, []
        async def observe(name, args, *a, **k):
            if name == 'terminal_exec' and args['command'] == work_checks.SNAPSHOT_COMMAND:
                calls.append(args)
                return {'content': json.dumps(source | {'hash': 'b' * 64}
                    if change == 'before' or len(calls) > 1 else source), 'exit_code': 0}
            return await original(name, args, *a, **k)
        rt.executor.execute = observe
        rt.client = ManifestModel()
        result = await graph.checks.judge(store.get(sid), run, node, 'execute',
            {'id': 'code_review', 'executorRole': 'review'}, [primary], {'C1': 'Check code'}, {'checkId': 'code-manifest'})
        assert result['inputManifest'] and result['status'] == 'superseded', result
        assert len(store.children_of(sid)) == (0 if change == 'before' else 1)
        assert len(calls) == (1 if change == 'before' else 2)
    asyncio.run(check())


@pytest.mark.parametrize('fault', ['content', 'binding', 'partial', 'different_inputs', 'reference'])
def test_manifest_replay_rejects_tampering_or_rebinding(tmp_path, fault):
    async def check():
        _, _, _, graph, run, _, _, _, primary = await large_fixture(tmp_path)
        metas = graph.artifacts.input_closure(run['runId'], [primary])
        doc = {'checkId': 'pin-check'}
        meta = await graph.artifacts.check_manifest(run, doc, metas, [primary['artifactId']])
        doc['inputManifest'] = meta
        if fault == 'content':
            with graph.db:
                graph.db.execute('UPDATE work_artifacts SET content=? WHERE id=?', ('tampered', meta['artifactId']))
        elif fault in ('binding', 'partial'):
            edited = copy.deepcopy(meta)
            if fault == 'binding':
                edited['binding']['inputsHash'] = '0' * 64
            else:
                edited['status'] = 'partial'
            with graph.db:
                graph.db.execute('UPDATE work_artifacts SET metadata=? WHERE id=?', (json.dumps(edited), meta['artifactId']))
        elif fault == 'different_inputs':
            metas = metas[:-1]
        else:
            doc['inputManifest'] = meta | {'version': 999}
        with pytest.raises(ValueError, match='WORK_(ARTIFACT_CORRUPT|INPUT_MANIFEST_CONFLICT)'):
            await graph.artifacts.check_manifest(run, doc, metas, [primary['artifactId']])
    asyncio.run(check())


def test_manifest_replays_same_ref_after_restart_without_writing_duplicate(tmp_path):
    from agentbox.agent_core.runtime import HarnessRuntime
    from agentbox.memory.session_store import SessionStore
    from test_work_graph import Executor

    async def check():
        store, _, sid, graph, run, _, _, _, primary = await large_fixture(tmp_path)
        metas = graph.artifacts.input_closure(run['runId'], [primary])
        doc = {'checkId': 'restart-check'}
        first = await graph.artifacts.check_manifest(run, doc, metas, [primary['artifactId']])
        before = store.db.execute('SELECT COUNT(*) FROM work_artifacts').fetchone()[0]
        store.db.close()
        restarted = SessionStore(tmp_path / 'sessions.db')
        executor = Executor()
        graph = work_graph.service(HarnessRuntime(restarted, executor, ManifestModel()))
        again = await graph.artifacts.check_manifest(run, doc | {'inputManifest': first}, metas, [primary['artifactId']])
        assert again == first
        assert restarted.db.execute('SELECT COUNT(*) FROM work_artifacts').fetchone()[0] == before
        assert executor.calls == []
        alien = graph.rt.create({}, parent_id=sid, role='research-review')
        restarted.update_config(alien['id'], alien['config'] | {'workBinding': {'runId': run['runId'], 'artifactIds': []}})
        with pytest.raises(PermissionError, match='WORK_ARTIFACT_SCOPE'):
            graph.artifacts.read(restarted.get(alien['id']), {'artifactId': first['artifactId']})
    asyncio.run(check())


def test_manifest_copy_cannot_be_original_source_and_write_failure_does_not_admit(tmp_path):
    from agentbox.agent_core.work_checks import good_reads

    async def check():
        store, rt, sid, graph, run, node, _, _, primary = await large_fixture(tmp_path)
        original = rt.executor.execute
        async def fail(name, args, *a, **k):
            if name == 'file_write' and '/check_inputs/' in args.get('path', ''):
                return {'is_error': True, 'error': 'disk unavailable'}
            return await original(name, args, *a, **k)
        rt.executor.execute = fail
        result = await judge(store, rt, sid, graph, run, node, primary)
        assert result['status'] == 'unverified' and 'WRITE_FAILED' in result['error']
        assert not store.children_of(sid)
        rt.executor.execute = original
        metas = graph.artifacts.input_closure(run['runId'], [primary])
        meta = await graph.artifacts.check_manifest(run, {'checkId': 'copy'}, metas, [primary['artifactId']])
        child = graph.rt.create({}, parent_id=sid, role='research-review')
        store.update_config(child['id'], child['config'] | {'workBinding': {'runId': run['runId'], 'artifactIds': [meta['artifactId']]}})
        store.emit(child['id'], 'tool_end', {'name': 'file_read', 'args': {'path': meta['path']}, 'result': {'content': 'copied manifest'}})
        assert not good_reads(graph, child['id'])
    asyncio.run(check())
