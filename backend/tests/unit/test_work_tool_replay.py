"""W7.2 — phục hồi tool call chưa kịp ghi kết quả (event log là điểm commit).

Bốn nhánh của `tool_recovery.reconcile`:
1. đã có `tool_end` → dùng lại đúng kết quả đó, không chạy lại, không gọi model;
2. chưa có `tool_start` → nói thật là chưa chạy;
3. tool chỉ đọc → chạy lại ĐÚNG MỘT lần ở đầu lượt, có dấu `replayed`;
4. tool có tác dụng phụ → không chạy lại, ghi biên nhận `TOOL_INTERRUPTED_UNSAFE`.
"""
import asyncio
import json

import pytest

from agentbox.agent_core import work_graph
from agentbox.agent_core.tool_contracts import replay_class
from agentbox.agent_core.tool_recovery import INTERRUPTED_UNSAFE, interrupted_calls
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.work_feedback import FeedbackError
from agentbox.memory.session_store import SessionStore
from test_harness_runtime import FixtureExecutor, FixtureModel, answer, call
from test_work_feedback_w7 import setup


def interrupted(tmp_path, name, args, cid='c1', started=True, committed=None):
    """A transcript that ends inside a tool group, then a real restart (same DB, new store).

    A crash leaves the session `running`; reopening the DB marks it `interrupted`, which is the
    state the next turn must reconcile.
    """
    path = tmp_path / 'sessions.db'
    store = SessionStore(path)
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([]))
    sid = runtime.create({'skills': []})['id']
    runtime.store.save(sid, [{'role': 'user', 'content': 'việc đang dở'},
                             {'role': 'assistant', 'content': '', 'tool_calls': [call(name, args, cid)]}], 'running')
    if started:
        runtime.store.emit(sid, 'tool_start', {'id': cid, 'name': name, 'args': args,
                                               'replay': replay_class(name, args)})
    if committed is not None:
        runtime.store.emit(sid, 'tool_end', {'id': cid, 'name': name, 'args': args, 'result': committed})
    store.close()
    store = SessionStore(path)
    executor = FixtureExecutor()
    model = FixtureModel([answer('tiếp tục')])
    return store, HarnessRuntime(store, executor, model), model, executor, sid


def transcript(runtime, sid):
    return [m for m in runtime.store.get(sid)['messages'] if m.get('role') == 'tool']


def test_committed_tool_end_is_reused_without_model_call(tmp_path):
    async def run():
        store, runtime, model, executor, sid = interrupted(
            tmp_path, 'file_read', {'path': 'src/a.py'},
            committed={'content': 'committed before the crash'})
        await runtime.start(sid, 'đọc tiếp')
        tools = [m for m in model.requests[0][0] if m.get('role') == 'tool']
        assert len(tools) == 1 and 'committed before the crash' in tools[0]['content']
        assert not [c for c in executor.calls if c[0] == 'file_read'], 'kết quả đã commit thì không chạy lại'
        assert not [e for e in store.events(sid) if e['type'] == 'tool_end' and e['data'].get('replayed')]
        store.close()
    asyncio.run(run())


def test_safe_read_tool_is_replayed_once(tmp_path):
    async def run():
        store, runtime, model, executor, sid = interrupted(tmp_path, 'file_read', {'path': 'src/a.py'})
        await runtime.start(sid, 'đọc lại')
        reads = [c for c in executor.calls if c[0] == 'file_read']
        assert len(reads) == 1 and reads[0][1] == {'path': 'src/a.py'}
        events = [e for e in store.events(sid) if e['type'] == 'tool_end' and e['data'].get('replayed')]
        assert len(events) == 1 and events[0]['data']['id'] == 'c1'
        content = transcript(runtime, sid)[0]['content']
        assert 'observed fixture result' in content and 'TOOL_REPLAY_PENDING' not in content
        store.close()
    asyncio.run(run())


@pytest.mark.parametrize('name,args', [('terminal_exec', {'command': 'rm -rf build'}),
                                       ('work_ship', {'runId': 'wr-x', 'invocationId': 'ship-1'})])
def test_unsafe_terminal_exec_is_not_replayed_and_gets_interrupted_receipt(tmp_path, name, args):
    async def run():
        store, runtime, model, executor, sid = interrupted(tmp_path, name, args)
        await runtime.start(sid, 'kiểm tra trạng thái')
        assert [c for c in executor.calls if c[0] == name] == [], 'tool có tác dụng phụ không được chạy lại'
        content = transcript(runtime, sid)[0]['content']
        assert INTERRUPTED_UNSAFE in content and 'Inspect current state' in content
        receipts = [e for e in store.events(sid) if e['type'] == 'tool_end' and e['data'].get('interrupted')]
        assert len(receipts) == 1 and receipts[0]['data']['result']['errorCode'] == INTERRUPTED_UNSAFE
        store.close()
    asyncio.run(run())


def test_not_started_call_says_nothing_ran(tmp_path):
    async def run():
        store, runtime, model, executor, sid = interrupted(tmp_path, 'terminal_exec', {'command': 'make'}, started=False)
        await runtime.start(sid, 'thử lại')
        content = transcript(runtime, sid)[0]['content']
        assert 'TOOL_NOT_STARTED' in content and 'nothing ran' in content
        assert [c for c in executor.calls if c[0] == 'terminal_exec'] == []
        store.close()
    asyncio.run(run())


def test_progress_finish_records_tool_interrupted_unsafe(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        admission = await graph.progress.reserve(sid, {'runId': run['runId'], 'nodeId': 'R1',
                                                       'stage': 'produce', 'purpose': 'produce'}, cid)
        store.emit(cid, 'user', {'prompt': 'làm việc'})
        store.emit(cid, 'tool_start', {'id': 't1', 'name': 'terminal_exec', 'args': {'command': 'rm -rf x'},
                                       'replay': 'unsafe'})
        graph.progress.attach(admission, sid, {'runId': run['runId'], 'nodeId': 'R1', 'stage': 'produce',
                                               'purpose': 'produce', 'admissionSeq': 0}, cid)
        receipt = graph.progress.finish(admission, interrupted=True)
        assert receipt['status'] == 'interrupted'
        assert {'tool': 'terminal_exec', 'code': INTERRUPTED_UNSAFE, 'callId': 't1'} in receipt['errors']
        store.close()
    asyncio.run(run())


def test_revoked_grant_blocks_next_tool_call(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        grant = graph.grants.action(store.get(sid), {'action': 'grant', 'runId': run['runId'], 'nodeId': 'R1',
            'stage': 'produce', 'purpose': 'produce', 'decisionKeys': ['users', 'deploy'], 'revision': 1,
            'publishInterview': True, 'resumeOnAnswers': False, 'invocationId': 'g-1'})
        assert graph.grants.find(graph.current(run['runId']), store.get(cid)['config']['workBinding'],
                                 ['users', 'deploy'])['grantId'] == grant['grantId']
        graph.grants.action(store.get(sid), {'action': 'revoke', 'runId': run['runId'],
                                             'grantId': grant['grantId'], 'revision': 1, 'invocationId': 'g-2'})
        with pytest.raises(FeedbackError, match='WORK_CAPABILITY_REVOKED'):
            await graph.feedback.report(store.get(cid), {'action': 'needs_user', 'checkpoint': 'Cần người dùng chốt',
                'questions': [{'id': 'users', 'question': 'Ai dùng?', 'options': ['Bác sĩ', 'Điều dưỡng']},
                              {'id': 'deploy', 'question': 'Chạy ở đâu?', 'options': ['Offline', 'Cloud']}],
                'decisionKeys': ['users', 'deploy'], 'invocationId': 'r-1'}, 'tool-r')
        # Không có khoá nào bị thu hồi thì vẫn là checkpoint bình thường cho main.
        doc = await graph.feedback.report(store.get(cid), {'action': 'needs_user', 'checkpoint': 'Cần người dùng chốt',
            'questions': [{'id': 'users', 'question': 'Ai dùng?', 'options': ['Bác sĩ', 'Điều dưỡng']}],
            'invocationId': 'r-2'}, 'tool-r2')
        assert doc['status'] == 'waiting_main' and doc['decisionKeys'] == []
        store.close()
    asyncio.run(run())


def test_interrupted_calls_only_reports_started_without_end(tmp_path):
    async def run():
        store, runtime, model, executor, sid = interrupted(tmp_path, 'file_read', {'path': 'a'}, cid='c1')
        runtime.store.emit(sid, 'tool_start', {'id': 'c2', 'name': 'terminal_exec', 'args': {'command': 'x'},
                                               'replay': 'unsafe'})
        runtime.store.emit(sid, 'tool_end', {'id': 'c2', 'name': 'terminal_exec', 'result': {'ok': True}})
        rows = interrupted_calls(store, sid)
        assert [r['id'] for r in rows] == ['c1'] and rows[0]['replay'] == 'safe'
        store.close()
    asyncio.run(run())


def test_reused_call_id_does_not_reuse_an_older_receipt(tmp_path):
    """Finding 4: `tool_end` của bước cũ (id dùng lại) không được báo là kết quả của call mới."""
    async def run():
        path = tmp_path / 'sessions.db'
        store = SessionStore(path)
        runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([]))
        sid = runtime.create({'skills': []})['id']
        old_args = {'path': 'src/old.py'}
        runtime.store.save(sid, [{'role': 'user', 'content': 'việc đang dở'},
                                 {'role': 'assistant', 'content': '',
                                  'tool_calls': [call('file_read', {'path': 'src/new.py'}, 'call_0')]}], 'running')
        runtime.store.emit(sid, 'tool_start', {'id': 'call_0', 'name': 'file_read', 'args': old_args,
                                               'replay': 'safe', 'argsHash': 'sha256:cũ'})
        runtime.store.emit(sid, 'tool_end', {'id': 'call_0', 'name': 'file_read', 'args': old_args,
                                             'result': {'content': 'STALE-RESULT'}})
        store.close()
        store = SessionStore(path)
        executor = FixtureExecutor()
        runtime = HarnessRuntime(store, executor, FixtureModel([answer('tiếp tục')]))
        await runtime.start(sid, 'đọc tiếp')
        tools = [m for m in runtime.store.get(sid)['messages'] if m.get('role') == 'tool']
        assert tools and 'STALE-RESULT' not in tools[0]['content'], tools
        assert INTERRUPTED_UNSAFE in tools[0]['content']
        assert not [c for c in executor.calls if c[0] == 'file_read'], 'không được chạy lại mù'
        store.close()
    asyncio.run(run())
