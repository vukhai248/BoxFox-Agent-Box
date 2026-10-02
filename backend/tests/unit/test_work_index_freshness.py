"""An input index/check ID is bookkeeping, not a new fact or a budget grant."""
import asyncio

import pytest

from agentbox.agent_core import work_feedback
from test_work_feedback_w7 import setup


def test_new_check_manifest_cannot_refresh_the_same_child_budget(tmp_path):
    async def check():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        store.child_start(cid, sid, 1, 1, 'research')
        meta = await graph.artifacts.put(run, 'R1', 'check_inputs', '{"sameSources":true}',
            {'purpose': 'check_inputs', 'checkId': 'new-id', 'inputsHash': 'same-input'}, True)
        work = store.get(cid)['config']['workBinding'] | {'artifactIds': [meta['artifactId']]}
        with pytest.raises(work_feedback.FeedbackError, match='NO_PROGRESS'):
            await work_feedback.resume_child(rt, store.get(sid), cid, 'Read another index', work)
        assert store.db.execute('SELECT COUNT(*) FROM work_resume_inputs').fetchone()[0] == 0
    asyncio.run(check())


@pytest.mark.parametrize('reader', ['canonical', 'relative_copy', 'absolute_copy'])
def test_check_manifest_reads_are_not_new_evidence_for_resume(tmp_path, reader):
    async def check():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        req = await graph.feedback.report(store.get(cid), {'action': 'needs_evidence', 'checkpoint': 'Need a new source'}, 'wait')
        meta = await graph.artifacts.put(run, 'R1', 'check_inputs', '{"index":"not a fact"}',
            {'purpose': 'check_inputs', 'checkId': 'new-id', 'inputsHash': 'same-input'}, True)
        if reader == 'canonical':
            event = {'name': 'work_artifact_read', 'args': {'artifactId': meta['artifactId']},
                     'result': meta | {'content': '{"index":"not a fact"}'}}
            ref = 'artifact:' + meta['artifactId']
        else:
            ref = meta['path'] if reader == 'relative_copy' else '/home/agent/workspace/' + meta['path']
            event = {'name': 'file_read', 'args': {'path': ref}, 'result': {'content': '{"index":"not a fact"}'}}
        store.emit(sid, 'tool_end', event)
        with pytest.raises(work_feedback.FeedbackError, match='EVIDENCE_REQUIRED'):
            graph.feedback.main_action(store.get(sid), {'action': 'resume', 'requestId': req['requestId'],
                'revision': req['revision'], 'evidenceRefs': [ref]})
        assert graph.feedback.get(req['requestId'])['status'] == 'waiting_main'
    asyncio.run(check())


def test_new_source_artifact_remains_a_genuine_input(tmp_path):
    async def check():
        store, rt, graph, run, _, cid = setup(tmp_path)
        meta = await graph.artifacts.put(run, 'R1', 'knowledge', 'New verified fact', {'purpose': 'knowledge'}, True)
        work = store.get(cid)['config']['workBinding'] | {'artifactIds': [meta['artifactId']]}
        assert work_feedback.input_snapshots(graph.feedback, cid, work)
    asyncio.run(check())
