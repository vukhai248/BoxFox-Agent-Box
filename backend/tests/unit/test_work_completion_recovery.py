"""Incomplete main recovery must not certify an unfinished Work Graph."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_graph as wg
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_delegation_contract import FixtureExecutor, FixtureModel, answer, call


async def run_turn(rt, sid, text):
    return await rt.start(sid, text)


@pytest.mark.parametrize('flow', ['plan', 'research', 'design'])
@pytest.mark.parametrize('finish,code', [
    ('length', 'PROVIDER_OUTPUT_TRUNCATED'),
    ('stream_incomplete', 'PROVIDER_STREAM_INTERRUPTED'),
])
def test_text_recovery_of_active_main_remains_partial(tmp_path, flow, finish, code):
    store = SessionStore(tmp_path/'sessions.db')
    model = FixtureModel([
        answer(calls=[call('work_graph', {'action': 'create', 'flow': flow,
            'goal': 'Investigate and verify the requested artifact', 'nodes': []})]),
        answer('', finish=finish),
        answer('Stopped; only a checkpoint exists. No child or verification has run.'),
    ])
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': []})['id']
    asyncio.run(run_turn(rt, sid, 'Use the graph to finish and verify this task.'))
    ends = [e['data'] for e in store.execution_events(sid) if e['type'] == 'turn_end']
    assert ends[-1]['status'] == 'partial'
    assert rt.partial_turn(sid) == code
    assert wg.service(rt).active(sid)['status'] == 'drafting'
    assert not store.children_of(sid)
    finish_row = store.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='finish' "
        "ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()
    assert json.loads(finish_row['payload'])['partial'] is True


def test_normal_empty_recovery_outside_graph_keeps_existing_contract(tmp_path):
    store = SessionStore(tmp_path/'sessions.db')
    model = FixtureModel([answer('', finish='length'), answer('A complete short answer.')])
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': []})['id']
    asyncio.run(run_turn(rt, sid, 'Answer this small read-only question.'))
    ends = [e['data'] for e in store.execution_events(sid) if e['type'] == 'turn_end']
    assert ends[-1]['status'] == 'completed'
    assert rt.partial_turn(sid) is None


def test_reasoning_only_forced_tool_recovery_is_still_executed(tmp_path):
    store = SessionStore(tmp_path/'sessions.db')
    reasoning = answer('')
    reasoning['choices'][0]['message']['reasoning_content'] = 'Need to inspect graph status.'
    model = FixtureModel([
        answer(calls=[call('work_graph', {'action': 'create', 'flow': 'plan',
            'goal': 'Read the graph status', 'nodes': []})]),
        reasoning,
        answer(calls=[call('work_graph', {'action': 'status'}, 'status-recovery')]),
        answer('Status inspected; the graph remains a draft.'),
    ])
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': []})['id']
    asyncio.run(run_turn(rt, sid, 'Inspect and report graph status.'))
    rows = store.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='tool_end'", (sid,))
    results = [json.loads(r['payload']) for r in rows]
    assert any(e['id'] == 'status-recovery' and not e['result'].get('is_error') for e in results)
    assert rt.partial_turn(sid) is None
