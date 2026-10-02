"""W8.A4.5 — cổng review hội tụ trên nút tổng hợp `__integration__`.

Luật: `code_review` của nút tổng hợp chỉ được chạy SAU khi `tests` của CHÍNH artifact đó
(đúng snapshot nhánh run) đã pass; và run chỉ được coi là `executed`/được ship khi cổng đó
đã qua. Bài khoá ba điều:

- `work_check action=start checkIds=[code_review]` trước khi tests xanh ⇒
  `WORK_REVIEW_NOT_CONVERGED` (không tốn một child reviewer);
- cổng chỉ áp cho nút tổng hợp: nút thường không bị chặn, và không đòi tests khi policy
  không yêu cầu;
- bằng chứng tests gắn với artifact hiện tại: `Checks.latest` chỉ thấy check của artifact
  đó, nên sau một vòng sửa (artifact mới) review lại bị chặn cho tới khi tests chạy lại.
"""
import asyncio
import uuid

import pytest

from agentbox.agent_core import work_graph as wg, work_repair, work_worktrees as ww
from test_work_graph import EXPLORE, PLAN, ok_script, raw_tool, tool
from test_work_ship_scoped import WritingModel
from test_work_worktree import BUILD, build, make_repo


def integration_policy():
    return {'version': 'work-checks/11', 'required': [{'id': 'tests', 'executorRole': 'testing'},
                                                      {'id': 'code_review', 'executorRole': 'code-review'}]}


def test_converged_gate_requires_green_tests_on_the_same_artifact():
    """Chưa có `tests` pass cho artifact hiện tại ⇒ `WORK_REVIEW_NOT_CONVERGED`."""
    node = {'id': ww.INTEGRATION_NODE}
    policy = integration_policy()
    with pytest.raises(ValueError, match='WORK_REVIEW_NOT_CONVERGED'):
        work_repair.converged(node, policy, ['code_review'], {})
    with pytest.raises(ValueError, match='WORK_REVIEW_NOT_CONVERGED'):
        work_repair.converged(node, policy, ['code_review'], {'tests': {'status': 'revise'}})
    with pytest.raises(ValueError, match='WORK_REVIEW_NOT_CONVERGED'):
        work_repair.converged(node, policy, ['code_review'], {'tests': {'status': 'unverified'}})
    work_repair.converged(node, policy, ['code_review'], {'tests': {'status': 'pass'}})  # xanh thì qua
    work_repair.converged(node, policy, ['tests'], {})  # chạy chính tests thì không cần chính nó


def test_converged_gate_is_only_for_the_integration_node():
    """Nút thường, và policy không yêu cầu tests: cổng là no-op."""
    policy = integration_policy()
    work_repair.converged({'id': 'B1'}, policy, ['code_review'], {})
    review_only = {'version': 'work-checks/11', 'required': [{'id': 'code_review', 'executorRole': 'code-review'}]}
    work_repair.converged({'id': ww.INTEGRATION_NODE}, review_only, ['code_review'], {})
    work_repair.converged({'id': ww.INTEGRATION_NODE}, {}, ['code_review'], {})


class QuietModel(WritingModel):
    """Như `WritingModel` nhưng mọi lượt phản biện đều `ok`."""

    def __init__(self):
        super().__init__(self.script_for)

    def script_for(self, kind, text):
        return ok_script(kind, text)


async def start_check(runtime, sid, run, node, check_ids):
    """Mở đúng `check_ids` cho một nút (một lệnh `work_check` thật)."""
    return await raw_tool(runtime, sid, 'work_check', {
        'action': 'start', 'runId': run['runId'], 'nodeId': node['id'], 'stage': 'execute',
        'artifactId': node['stages']['execute']['artifact']['artifactId'],
        'checkIds': check_ids, 'invocationId': uuid.uuid4().hex})


async def run_to_gate(runtime, sid, service):
    """Chạy tới lúc nút tổng hợp `needs_checks` và mọi nút thường đã accepted."""
    await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
    await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN, BUILD]})
    await tool(runtime, sid, 'work_run', {'phase': 'discover'})
    await tool(runtime, sid, 'work_graph', {'action': 'verify'})
    await tool(runtime, sid, 'work_graph', {'action': 'submit'})
    executed = await raw_tool(runtime, sid, 'work_run', {'phase': 'execute'})
    for _ in range(10):
        run = service.get(executed['runId'])
        for node in run['nodes']:
            state = node['stages'].get('execute') or {}
            if state.get('status') == 'needs_checks':
                await start_check(runtime, sid, run, node, None)
        run = service.get(executed['runId'])
        if service.integration_node(run)['stages']['execute'].get('status') == 'needs_checks':
            return run
        executed = await raw_tool(runtime, sid, 'work_run', {'phase': 'execute'})
    raise AssertionError('nút tổng hợp không tới bước check')


def test_review_before_tests_is_blocked_and_ship_waits_for_the_gate(tmp_path):
    """Cổng thật trên run: review trước tests bị chặn; ship bị chặn tới khi cổng qua."""
    store, runtime, _, executor, sid, workspace = build(tmp_path, model=QuietModel())
    make_repo(workspace)
    wg.set_autopilot(runtime, sid, True)
    service = wg.service(runtime)

    async def run_all():
        run = await run_to_gate(runtime, sid, service)
        node = service.integration_node(run)
        # 1) Chưa hội tụ: run chưa `executed`, và chưa ship được.
        assert run['status'] == 'approved'
        with pytest.raises(ValueError, match='WORK_NOT_EXECUTED'):
            await raw_tool(runtime, sid, 'work_ship', {'runId': run['runId']})
        # 2) Review trước tests: cổng chặn trước khi mở child nào.
        with pytest.raises(ValueError, match='WORK_REVIEW_NOT_CONVERGED'):
            await start_check(runtime, sid, run, node, ['code_review'])
        assert service.checks.latest(run, node, 'execute') == {}
        # 3) Tests xanh trên đúng artifact đó rồi mới review được.
        await start_check(runtime, sid, run, node, ['tests'])
        run = service.get(run['runId'])
        assert service.checks.latest(run, node, 'execute')['tests']['status'] == 'pass'
        await start_check(runtime, sid, run, node, ['code_review'])
        run = service.get(run['runId'])
        assert service.checks.latest(run, node, 'execute')['code_review']['status'] == 'pass'
        return run

    run = asyncio.run(run_all())
    # 4) Cổng qua ⇒ nút tổng hợp accepted, integration `checked`, run `executed`.
    node = wg.service(runtime).integration_node(run)
    assert node['stages']['execute']['status'] == 'accepted'
    assert run['integration']['status'] == 'checked'
    assert run['status'] == 'executed'


def test_evidence_is_bound_to_the_current_integration_artifact(tmp_path):
    """`latest()` chỉ trả check của artifact HIỆN TẠI: artifact mới ⇒ cổng đóng lại.

    Vòng sửa thật (tests đỏ ⇒ route ⇒ artifact mới ⇒ tests phải chạy lại) nằm ở
    `test_work_repair_w8.test_unclassified_red_check_gets_a_debug_child_first`.
    """
    store, runtime, _, executor, sid, workspace = build(tmp_path, model=QuietModel())
    make_repo(workspace)
    wg.set_autopilot(runtime, sid, True)
    service = wg.service(runtime)

    async def run_all():
        run = await run_to_gate(runtime, sid, service)
        node = service.integration_node(run)
        await start_check(runtime, sid, run, node, ['tests'])
        run = service.get(run['runId'])
        node = service.integration_node(run)
        assert service.checks.latest(run, node, 'execute')['tests']['status'] == 'pass'
        work_repair.converged(node, node['stages']['execute']['policy'], ['code_review'],
                              service.checks.latest(run, node, 'execute'))  # bằng chứng xanh: qua cổng
        # Artifact đổi (một vòng sửa): bằng chứng cũ không còn thuộc artifact hiện tại.
        node['stages']['execute']['artifact'] = dict(node['stages']['execute']['artifact'],
                                                     artifactId='a-' + '0' * 32)
        latest = service.checks.latest(run, node, 'execute')
        assert latest == {}
        with pytest.raises(ValueError, match='WORK_REVIEW_NOT_CONVERGED'):
            work_repair.converged(node, node['stages']['execute']['policy'], ['code_review'], latest)

    asyncio.run(run_all())
