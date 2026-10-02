"""W8.A4.5 — sửa có điều kiện sau check đỏ (chỉ trên run có worktree) và cổng review hội tụ.

Bốn luật được khoá ở đây:

- check đỏ **rõ** (lệnh bắt buộc thật sự fail, traceback trỏ vào tệp đã track trong worktree
  của nút) resume ĐÚNG child Build cũ trong ĐÚNG worktree đó — không mở child mới, không
  chạy lại từ đầu;
- check đỏ **chưa phân loại** (reviewer nói revise nhưng không có lệnh đỏ nào) chạy một child
  Debug chỉ-đọc trước, rồi Build nhận bản chẩn đoán đó làm đầu vào;
- hết `maxRepairs` thì nút dừng (`rejected`) và main nhận decision `repair_decision_required`,
  không tự sửa vô hạn;
- `work_graph action=set_repair` là CAS theo `revision` và idempotent theo `invocationId`.

Bài dùng lại repo git thật + executor thật của `test_work_worktree`, thêm một executor làm
`vitest ChatHeader.test.tsx` đỏ đúng MỘT lần trong worktree `n-B1` để có một lệnh đỏ thật.
"""
import asyncio
import json
import uuid

from agentbox.agent_core import work_graph as wg, work_repair, work_worktrees as ww
from test_work_graph import EXPLORE, PLAN, ok_script, tool
from test_work_ship_scoped import WritingModel
from test_work_worktree import BUILD, build, execute_run, make_repo

RED_OUTPUT = ('Traceback (most recent call last):\n'
              '  File "src/app.py", line 2, in header\n'
              'AssertionError: expected the export button\n')


class FlakyExecutor(__import__('test_work_worktree').RealExecutor):
    """`vitest ChatHeader.test.tsx` đỏ MỘT lần trong worktree `n-B1`, xanh từ lần sau."""

    def __init__(self, workspace):
        super().__init__(workspace)
        self.failed = set()

    async def execute(self, name, args, sid, **identity):
        root = identity.get('root') or ''
        if name == 'terminal_exec' and args.get('command') == 'vitest ChatHeader.test.tsx':
            if 'n-B1' not in root:
                return await super().execute(name, args, sid, **identity)
            self.calls.append((name, dict(args), dict(identity)))
            if root not in self.failed:
                self.failed.add(root)
                return {'content': RED_OUTPUT, 'exit_code': 1, 'is_error': True}
            return {'content': 'ok', 'exit_code': 0, 'is_error': False}
        return await super().execute(name, args, sid, **identity)


class ReviseOnce(WritingModel):
    """Trả `revise` đúng MỘT lần cho một prompt khớp `match`, sau đó `ok`."""

    def __init__(self, match):
        self.match = match
        self.revises = 0
        super().__init__(self.script_for)

    def script_for(self, kind, text):
        if self.revises == 0 and self.match(kind, text):
            self.revises += 1
            return '## Blocking findings\n1. src/app.py:2 header does not export\nVERDICT: revise'
        return ok_script(kind, text)


def failing_test_model():
    """Tester của nút B1 nói revise (đúng như lệnh đỏ nó vừa chạy)."""
    return ReviseOnce(lambda kind, text: kind == 'review' and 'node B1' in text and '"id": "tests"' in text)


def unclassified_model():
    """Lượt kiểm của nút tổng hợp nói revise nhưng KHÔNG có lệnh đỏ nào."""
    return ReviseOnce(lambda kind, text: 'node __integration__' in text and '"id": "tests"' in text)


def build_run(tmp_path, model, policy=None):
    """Dựng runtime, thay executor, tạo repo và bật autopilot. Trả `(runtime, service, sid)`."""
    store, runtime, _, executor, sid, workspace = build(tmp_path, model=model)
    runtime.executor = FlakyExecutor(workspace)
    make_repo(workspace)
    wg.set_autopilot(runtime, sid, True)
    return runtime, wg.service(runtime), sid


async def execute_with_policy(runtime, sid, repair=None, nodes=None):
    """Như `test_work_worktree.execute_run`, thêm bước `set_repair` trước khi chạy execute."""
    await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
    await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': nodes or [EXPLORE, PLAN, BUILD]})
    await tool(runtime, sid, 'work_run', {'phase': 'discover'})
    await tool(runtime, sid, 'work_graph', {'action': 'verify'})
    await tool(runtime, sid, 'work_graph', {'action': 'submit'})
    if repair:
        await tool(runtime, sid, 'work_graph', {'action': 'set_repair',
                                                'invocationId': uuid.uuid4().hex, **repair})
    executed = await tool(runtime, sid, 'work_run', {'phase': 'execute'})
    service = wg.service(runtime)
    for _ in range(8):
        run = service.get(executed['runId'])
        node = service.integration_node(run)
        state = node['stages']['execute']
        if state.get('status') in ('needs_checks', 'revise'):
            passed = {kind for kind, doc in service.checks.latest(run, node, 'execute').items()
                      if doc['status'] == 'pass'}
            todo = [r['id'] for r in state['policy']['required'] if r['id'] not in passed]
            await tool(runtime, sid, 'work_check', {'action': 'start', 'runId': run['runId'],
                                                    'nodeId': ww.INTEGRATION_NODE, 'stage': 'execute',
                                                    'artifactId': state['artifact']['artifactId'],
                                                    'checkIds': todo[:1], 'invocationId': uuid.uuid4().hex})
            continue
        if (run.get('integration') or {}).get('status') == 'checked' or run['status'] == 'execute_failed':
            break
        try:
            executed = await tool(runtime, sid, 'work_run', {'phase': 'execute'})
        except ValueError as exc:  # một nút bị từ chối: run đóng ở `execute_failed`, main phải quyết
            if 'WORK_EXECUTE_FAILED' not in str(exc):
                raise
            break
    return service.get(executed['runId'])


def stage_of(run, node_id):
    return next(node for node in run['nodes'] if node['id'] == node_id)['stages']['execute']


def test_clear_failure_resumes_the_same_build_child(tmp_path):
    """Lệnh đỏ thật + traceback vào tệp đã track ⇒ `clear`, resume đúng child cũ."""
    runtime, service, sid = build_run(tmp_path, failing_test_model())

    async def run():
        return await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])

    run_doc = asyncio.run(run())
    state = stage_of(run_doc, 'B1')
    assert run_doc['status'] == 'executed'
    assert state['status'] == 'accepted' and state['attempts'] == 2
    assert len(state['repairs']) == 1
    repair = state['repairs'][0]
    assert repair['class'] == 'clear' and 'trace into tracked files' in repair['reason']
    assert repair['debugChildId'] is None, 'lỗi rõ thì không tốn một child Debug'
    assert repair['resumed'] is True and repair['repairChildReason'] is None
    # ĐÚNG child cũ: vòng 2 do chính producer của vòng 1 làm tiếp, trong cùng worktree.
    producers = [item['producerId'] for item in state['rounds']]
    assert producers[0] == producers[1] == repair['buildChildId']
    assert [item['verdict'] for item in state['rounds']] == ['revise', 'ok']
    assert repair['codeHash'], 'lượt sửa phải chốt được code snapshot của worktree'
    # Bản findings nằm trong input của child được resume.
    child = service.rt.store.get(repair['buildChildId'])
    assert repair['findingsArtifactId'] in json.dumps(child.get('config') or {}, ensure_ascii=False) \
        or repair['findingsArtifactId'] in json.dumps(child, ensure_ascii=False)


def test_unclassified_red_check_gets_a_debug_child_first(tmp_path):
    """Không có lệnh đỏ nào ⇒ chạy Debug chỉ-đọc trước, rồi Build nhận chẩn đoán."""
    runtime, service, sid = build_run(tmp_path, unclassified_model())

    async def run():
        return await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])

    run_doc = asyncio.run(run())
    node = service.integration_node(run_doc)
    state = node['stages']['execute']
    assert run_doc['status'] == 'executed' and state['status'] == 'accepted'
    assert len(state['repairs']) == 1
    repair = state['repairs'][0]
    assert repair['class'] == 'unclassified'
    assert repair['debugChildId'] and repair['debugArtifactId'] == repair['findingsArtifactId']
    assert repair['buildChildId'] and repair['status'] == 'needs_checks'
    assert [item['verdict'] for item in state['rounds']] == ['revise', 'ok']
    # Child Debug chỉ được đọc: binding `diagnosticOnly`, không phải producer của artifact.
    debug = service.rt.store.get(repair['debugChildId'])
    assert 'diagnosticOnly' in json.dumps(debug.get('config') or {}, ensure_ascii=False) \
        or 'diagnosticOnly' in json.dumps(debug, ensure_ascii=False)


def test_debug_never_skips_the_diagnosis_child(tmp_path):
    """`debug=never`: check chưa phân loại đi thẳng vào Build, không mở child Debug."""
    runtime, service, sid = build_run(tmp_path, unclassified_model())

    async def run():
        return await execute_with_policy(runtime, sid, {'revision': 1, 'debug': 'never'})

    run_doc = asyncio.run(run())
    state = service.integration_node(run_doc)['stages']['execute']
    assert run_doc['status'] == 'executed' and state['status'] == 'accepted'
    repair = state['repairs'][0]
    assert repair['class'] == 'unclassified' and repair['debugChildId'] is None
    assert repair['buildChildId'] and repair['findingsArtifactId']


def test_repair_budget_exhausted_asks_main_for_a_decision(tmp_path):
    """`maxRepairs=0`: nút dừng ở `rejected` và main nhận `repair_decision_required`."""
    runtime, service, sid = build_run(tmp_path, failing_test_model())

    async def run():
        return await execute_with_policy(runtime, sid, {'revision': 1, 'maxRepairs': 0})

    run_doc = asyncio.run(run())
    state = stage_of(run_doc, 'B1')
    assert state['status'] == 'rejected'
    assert state['error'].startswith('WORK_REPAIR_LIMIT: 0/0')
    assert len(state['rounds']) == 1, 'không có vòng sửa nào được phép chạy'
    kinds = [doc['kind'] for doc in service.decisions.records(run_doc['runId'])]
    assert 'repair_decision_required' in kinds
    issue = next(doc for doc in service.decisions.records(run_doc['runId'])
                 if doc['kind'] == 'repair_decision_required')
    assert issue['refs']['nodeId'] == 'B1' and issue['refs']['stage'] == 'execute'
    assert issue['refs']['checkIds'] and issue['sourceId'] == 'B1:execute:repair_decision_required'
    assert run_doc['status'] == 'execute_failed'


class FakeWorktrees:
    """Chỉ đủ cho `classify`: `git ls-files` trên worktree nút."""

    def __init__(self, tracked):
        self.tracked = set(tracked)
        self.commands = []

    async def sh(self, sid, command, timeout=120):
        self.commands.append(command)
        names = [part.strip("'") for part in command.split(' -- ', 1)[1].split()] if ' -- ' in command else []
        return True, '\n'.join(sorted(name for name in names if name in self.tracked))


class FakeGraph:
    def __init__(self, tracked, observations):
        self.worktrees = FakeWorktrees(tracked)
        self.observations = observations

    def observations_for(self):
        return self.observations


def observations(output, command='python -m pytest -q'):
    return [{'name': 'terminal_exec', 'args': {'command': command},
             'result': {'exit_code': 1, 'is_error': True, 'content': output}}]


def test_classify_clear_needs_a_trace_into_tracked_files(monkeypatch):
    """`clear` chỉ khi lệnh bắt buộc đỏ THẬT và traceback trỏ vào tệp đã track của worktree."""
    red = FakeGraph({'src/app.py'}, observations(RED_OUTPUT))
    silent = FakeGraph({'src/app.py'}, observations('1 failed, 1 passed\n'))  # không có traceback
    monkeypatch.setattr(work_repair.work_checks, 'observations',
                        lambda g, child, after=None: g.observations_for())
    node = {'id': 'B1', 'tests': ['python -m pytest -q']}
    doc = {'kind': 'tests', 'childId': 'c1'}
    root = '.boxfox/worktrees/w-1/n-B1'

    async def run():
        clear, detail = await work_repair.classify(red, {}, node, doc, root, 's1')
        no_trace, detail2 = await work_repair.classify(silent, {}, node, doc, root, 's1')
        review, detail3 = await work_repair.classify(silent, {}, node, {'kind': 'code_review', 'childId': 'c1'}, None, 's1')
        return clear, detail, no_trace, detail2, review, detail3

    clear, detail, no_trace, detail2, review, detail3 = asyncio.run(run())
    assert clear == 'clear' and detail['paths'] == ['src/app.py']
    assert no_trace == 'unclassified' and 'no traceback' in detail2['reason']
    assert review == 'clear' and 'review findings' in detail3['reason']


def test_classify_unclassified_when_the_trace_names_untracked_files(monkeypatch):
    """Traceback trỏ ra ngoài tệp của nút (hoặc không có traceback) ⇒ chưa phân loại."""
    graph = FakeGraph({'src/app.py'}, observations(RED_OUTPUT.replace('src/app.py', 'other/thing.py')))
    monkeypatch.setattr(work_repair.work_checks, 'observations',
                        lambda g, child, after=None: g.observations_for())
    node = {'id': 'B1', 'tests': ['python -m pytest -q']}

    async def run():
        return await work_repair.classify(graph, {}, node, {'kind': 'tests', 'childId': 'c1'},
                                          '.boxfox/worktrees/w-1/n-B1', 's1')

    cls, detail = asyncio.run(run())
    assert cls == 'unclassified' and 'not files of the node worktree' in detail['reason']


def test_repair_policy_is_cas_and_idempotent():
    """`set_repair`: chặn revision cũ, lặp lại cùng `invocationId` không tăng revision."""
    run = {'nodes': [{'id': 'B1'}]}
    first = work_repair.set_policy(run, {'invocationId': 'i-1', 'revision': 1, 'maxRepairs': 1, 'debug': 'never'}, 4)
    assert first['revision'] == 2 and first['maxRepairs'] == 1 and first['debug'] == 'never'
    assert work_repair.set_policy(run, {'invocationId': 'i-1', 'revision': 99}, 4)['revision'] == 2
    try:
        work_repair.set_policy(run, {'invocationId': 'i-2', 'revision': 1}, 4)
    except ValueError as exc:
        assert 'WORK_REPAIR_POLICY_STALE' in str(exc)
    else:
        raise AssertionError('revision cũ phải bị chặn')
    per_node = work_repair.set_policy(run, {'invocationId': 'i-3', 'revision': 2, 'maxRepairs': 0, 'nodeId': 'B1'}, 4)
    assert per_node['revision'] == 3 and per_node['nodes']['B1'] == {'maxRepairs': 0, 'debug': 'never'}
    assert work_repair.node_policy(run, {'id': 'B1'})['maxRepairs'] == 0
    assert work_repair.node_policy(run, {'id': 'B2'})['maxRepairs'] == 1
    for bad in ({'invocationId': 'i-4', 'revision': 3, 'maxRepairs': 9},
                {'invocationId': 'i-5', 'revision': 3, 'debug': 'sometimes'},
                {'invocationId': '', 'revision': 3}):
        try:
            work_repair.set_policy(run, bad, 4)
        except ValueError as exc:
            assert 'WORK_REPAIR_POLICY_INVALID' in str(exc)
        else:
            raise AssertionError('tham số sai phải bị chặn: %r' % (bad,))


def test_default_policy_is_bounded_by_max_rounds():
    """`maxRepairs` mặc định không bao giờ vượt `maxRounds - 1`."""
    assert work_repair.default_policy(3)['maxRepairs'] == 2
    assert work_repair.default_policy(1)['maxRepairs'] == 0
    assert work_repair.default_policy(0)['maxRepairs'] == 0
    assert work_repair.default_policy(3, 'main')['source'] == 'main'
