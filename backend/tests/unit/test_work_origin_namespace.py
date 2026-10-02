"""Stable session/origin/run namespace; legacy artifacts are never moved."""
import asyncio
import copy

import pytest

from agentbox.agent_core import work_graph
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_work_graph import build, Executor, Model, ok_script


def create(graph, store, sid, **extra):
    return graph.create(store.get(sid), {'goal': 'Research the deterministic export scope', 'flow': 'research',
        'nodes': [{'id': 'R1', 'kind': 'research', 'title': 'Export scope',
                   'goal': 'Research the export scope without implementation', 'acceptance': ['Use the source']}], **extra})


def test_continuation_keeps_origin_metadata_and_folder_for_all_artifact_kinds(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path); rt.active_turn[sid] = 1
        graph = work_graph.service(rt); run = create(graph, store, sid)
        first = await graph.artifacts.put(run, 'R1', 'produce', 'First draft', {}, True)
        rt.active_turn[sid] = 9
        for stage, binding in [('produce', {}), ('knowledge', {'purpose': 'knowledge'}),
                               ('check_inputs', {'purpose': 'check_inputs'}), ('produce', {'checkpoint': True})]:
            meta = await graph.artifacts.put(graph.get(run['runId']), 'R1', stage, 'Continued output', binding, True)
            assert meta['originTurn'] == first['originTurn'] == 1
            assert meta['originTurnId'] == first['originTurnId'] == run['artifactNamespace']['originTurnId']
            assert meta['path'].split('/R1/')[0] == first['path'].split('/R1/')[0]
            assert '/' + first['originTurnId'] + '/' in meta['path']
        assert graph.artifacts.get(run['runId'], first['artifactId'])[1] == 'First draft'
    asyncio.run(check())


def test_turns_and_owners_are_distinct_while_runs_in_one_turn_share_origin(tmp_path):
    store, rt, _, _, sid = build(tmp_path); graph = work_graph.service(rt)
    rt.active_turn[sid] = 1
    first = create(graph, store, sid); second = create(graph, store, sid)
    assert first['runId'] != second['runId'] and first['artifactNamespace'] == second['artifactNamespace']
    rt.active_turn[sid] = 2; third = create(graph, store, sid)
    assert third['artifactNamespace'] != first['artifactNamespace']
    other = rt.create({'skills': []})['id']; rt.active_turn[other] = 1
    assert create(graph, store, other)['artifactNamespace'] != first['artifactNamespace']


def test_api_origin_is_stable_backend_generated_and_model_cannot_choose_path(tmp_path):
    store, rt, _, _, sid = build(tmp_path); graph = work_graph.service(rt)
    first = create(graph, store, sid, artifactNamespace={'version': 2, 'originTurnId': '../../other'}, originTurn=999)
    second = create(graph, store, sid)
    assert first['originTurn'] is None
    assert first['artifactNamespace']['originTurnId'].startswith('t-')
    assert len(first['artifactNamespace']['originTurnId']) == 22
    assert first['artifactNamespace'] != second['artifactNamespace']


def test_restart_preserves_origin_and_legacy_layout_and_content(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path); graph = work_graph.service(rt); rt.active_turn[sid] = 3
        run = create(graph, store, sid)
        first = await graph.artifacts.put(run, 'R1', 'produce', 'Tiếng Việt có dấu', {}, True)
        store.db.close(); store = SessionStore(tmp_path/'sessions.db')
        rt = HarnessRuntime(store, Executor(), Model(ok_script)); graph = work_graph.service(rt)
        rt.active_turn[sid] = 8
        resumed = await graph.artifacts.put(graph.get(run['runId']), 'R1', 'produce', 'Bản tiếp tục', {}, True)
        assert resumed['originTurnId'] == first['originTurnId'] and resumed['originTurn'] == 3
        assert graph.artifacts.get(run['runId'], first['artifactId']) == (first, 'Tiếng Việt có dấu')
        # Existing runs keep their old namespace, including new versions.
        legacy = create(graph, store, sid); legacy.pop('artifactNamespace'); graph.save(legacy)
        old = await graph.artifacts.put(legacy, 'R1', 'produce', 'Legacy', {}, True)
        assert '/t-' not in old['path'] and 'originTurnId' not in old
        rt.active_turn[sid] = 11
        new = await graph.artifacts.put(graph.get(legacy['runId']), 'R1', 'produce', 'Legacy continued', {}, True)
        assert old['path'].split('/R1/')[0] == new['path'].split('/R1/')[0]
        assert new['originTurn'] == legacy['originTurn'] == 8
        assert graph.artifacts.get(legacy['runId'], old['artifactId']) == (old, 'Legacy')
    asyncio.run(check())


def test_legacy_refs_stay_readable_and_scoped_after_new_namespace_run(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path); graph = work_graph.service(rt)
        legacy = create(graph, store, sid); legacy.pop('artifactNamespace'); graph.save(legacy)
        old = await graph.artifacts.put(legacy, 'R1', 'produce', 'Historical reference', {}, True)
        newer = create(graph, store, sid)
        current = await graph.artifacts.put(newer, 'R1', 'produce', 'New reference', {}, True)
        child = rt.create({'skills': []}, parent_id=sid, role='research-review')
        store.update_config(child['id'], child['config'] | {'workBinding': {
            'runId': legacy['runId'], 'artifactIds': [old['artifactId']]}})
        assert graph.artifacts.read(store.get(child['id']), {'artifactId': old['artifactId']})['content'] == 'Historical reference'
        with pytest.raises(PermissionError, match='WORK_ARTIFACT_SCOPE'):
            graph.artifacts.read(store.get(child['id']), {'runId': newer['runId'], 'artifactId': current['artifactId']})
        assert graph.artifacts.read(store.get(sid), {'runId': legacy['runId'], 'artifactId': old['artifactId']})['content'] == 'Historical reference'
    asyncio.run(check())


@pytest.mark.parametrize('fault', ['owner', 'origin', 'version'])
def test_invalid_namespace_fails_before_file_write(tmp_path, fault):
    async def check():
        store, rt, _, executor, sid = build(tmp_path); graph = work_graph.service(rt)
        run = create(graph, store, sid); altered = copy.deepcopy(run)
        if fault == 'owner':
            altered['sessionId'] = 'another-owner'
        elif fault == 'origin':
            altered['originTurn'] = 99
        else:
            altered['artifactNamespace']['version'] = 3
        before = len(executor.calls)
        with pytest.raises(ValueError, match='WORK_ARTIFACT_NAMESPACE_INVALID'):
            await graph.artifacts.put(altered, 'R1', 'produce', 'Must not write', {}, True)
        assert len(executor.calls) == before
        assert not graph.db.execute('SELECT * FROM work_artifacts').fetchall()
    asyncio.run(check())
