"""W6.5 profiles, truthful clamps and metadata after long streamed responses.

Số trong đây là số của #6457 (03/10/2026): nhà sản xuất 200 bước/7200 s, kiểm ngắn 40, kiểm dài 80.
Trần phiên (`limits.py`) là 120/400 bước và 1800/7200 s; con luôn bị kẹp theo trần phiên cha.
"""
import asyncio
import json

import pytest

from agentbox.agent_core import work_budget, work_graph as wg
from agentbox.agent_core.limits import ROUTER_LARGE_INPUT_BYTES
from agentbox.agent_core.runtime import HarnessRuntime, router_http_timeout
from agentbox.memory.session_store import SessionStore
from test_work_graph import build
from test_work_checks import setup, start
from test_delegation_contract import FixtureExecutor, FixtureModel, answer, call


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ; khóa tổng `BOXFOX_REFORM` đã bị xoá ở bước B5
# (HANDOFF §10.3) nên nhãn `legacy_path` không còn kèm env nào để pin.
pytestmark = pytest.mark.legacy_path


# Bề mặt 7 (RESEARCH_GATEWAY) đã xoá: main không còn spawn được producer `research`, nhưng `design`
# vẫn là kind discovery main chạy được với đúng hồ sơ ngân sách "deliverable" (200 bước/7200 s) mà
# các bài đo dưới đây chốt, nên dùng nó thay cho nút research cũ.
DESIGN = {'id': 'R1', 'kind': 'design', 'title': 'Compare approaches',
          'goal': 'Compare two export formats using the provided evidence'}


@pytest.mark.parametrize('role,task,expected', [
    ('research', 'deliverable', 200), ('plan', 'deliverable', 200),
    ('design', 'deliverable', 200), ('research', 'lookup', 40),
    ('explore', 'lookup', 40), ('debug', 'diagnostic', 40), ('build', 'implementation', 40),
])
def test_profiles_do_not_raise_lookup_or_execution_budget(role, task, expected):
    assert work_budget.requested(role, {'purpose': 'produce'}, task, 40, 900)['maxSteps'] == expected
    assert work_budget.requested(role, None, task, 40, 900)['maxSteps'] == 40


@pytest.mark.parametrize('hints,long', [
    ({}, False), ({'artifactCount': 1, 'artifactChars': 32000, 'criterionCount': 8}, False),
    ({'artifactCount': 2}, True), ({'artifactChars': 32001}, True),
    ({'criterionCount': 9}, True), ({'risk': 'consequential'}, True),
])
def test_short_and_long_review_cap(hints, long):
    profile = work_budget.requested('plan-review', {'purpose': 'review', 'budgetHints': hints}, None, 40, 900)
    assert profile['maxSteps'] == (80 if long else 40)
    assert profile['deadlineSeconds'] == 900


@pytest.mark.parametrize('owner_steps,owner_seconds,expected_steps,expected_seconds', [
    (60, 1200, 60, 1200), (40, 600, 40, 600), (12, 60, 12, 60),
])
def test_actual_producer_child_respects_owner_and_reports_clamps(tmp_path, owner_steps, owner_seconds, expected_steps, expected_seconds):
    store, rt, _, _, sid = build(tmp_path, values={'maxSteps': owner_steps, 'deadlineSeconds': owner_seconds})
    asyncio.run(setup(rt, sid, node=DESIGN))
    child = store.get(store.children_of(sid)[0]['session_id'])
    budget = child['config']['workBudget']
    assert (child['config']['maxSteps'], child['config']['deadlineSeconds']) == (expected_steps, expected_seconds)
    assert budget['requestedMaxSteps'] == 200
    assert budget['effectiveMaxSteps'] == expected_steps
    assert budget['clamped'] == (expected_steps < 200 or expected_seconds < 7200)
    assert child['config']['maxTokens'] == 16000
    assert store.get(sid)['config']['maxSteps'] == owner_steps


def test_checker_prompt_uses_effective_budget_and_short_check_profile(tmp_path):
    store, rt, model, _, sid = build(tmp_path, values={'maxSteps': 12})
    async def run():
        _, draft = await setup(rt, sid, node=DESIGN)
        await start(rt, sid, draft)
    asyncio.run(run())
    child = store.get(store.children_of(sid)[-1]['session_id'])
    assert child['config']['workBudget']['requestedMaxSteps'] == 40
    assert child['config']['maxSteps'] == 12
    assert 'Budget: 12 model steps' in model.prompts[-1][1]


def test_whole_review_nodeless_profile_preserves_read_and_coverage_gates(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    async def run():
        _, draft = await setup(rt, sid)
        await start(rt, sid, draft)
        verified = await rt.work_tool(rt.store.get(sid), 'work_graph', {'action': 'verify'})
        assert verified['status'] == 'verified'
        assert any(c['kind'] == 'whole' and c['status'] == 'pass'
                   for c in rt.work_graph.checks.records(verified['runId']))
    asyncio.run(run())


def test_event_summary_does_not_drop_late_error_final_or_batched_tools(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    model = FixtureModel([answer('child final')])
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': []})['id']
    original = rt.start
    def noisy(cid, text, *args, **kwargs):
        for _ in range(550):
            store.emit(cid, 'thought_delta', {'text': 'stream'})
        store.emit(cid, 'error', {'message': 'A real late error'})
        for i in range(5):
            store.emit(cid, 'tool_start', {'name': 'file_read', 'id': f't{i}'})
        return original(cid, text, *args, **kwargs)
    rt.start = noisy
    # Bề mặt 7 đã xoá: main chỉ delegate được các vai còn lại — `explore` là nhánh tra cứu tương đương.
    result = asyncio.run(rt.delegate(store.get(sid), {'role': 'explore', 'goal': 'Bounded fixture lookup'}))
    assert result['last_error'] == 'A real late error'
    assert result['tools_run'] == ['file_read'] * 5
    assert result['answerChars'] == len('child final')
    assert len(store.events(result['sessionId'])) == 500  # public pagination unchanged
    events = store.execution_events(result['sessionId'])
    assert events[-1]['type'] == 'turn_end'
    assert any(e['type'] == 'assistant' and e['data'].get('final') for e in events)


def test_five_actual_tool_calls_count_as_one_model_step(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    model = FixtureModel([answer(calls=[call('file_read', {'path': f'{i}.txt'}, str(i)) for i in range(5)]), answer('done')])
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': []})['id']
    async def run():
        await rt.start(sid, 'Read five fixture files')
    asyncio.run(run())
    events = store.execution_events(sid)
    end = [e['data'] for e in events if e['type'] == 'turn_end']
    assert end[0]['stepsUsed'] == 1
    assert end[0]['toolsRun'] == 5
    assert end[-1]['stepsUsed'] == 2
    assert len([e for e in events if e['type'] == 'tool_start']) == 5


def test_http_read_timeout_covers_bounded_large_router_option_without_unbounded_wait():
    normal, large = router_http_timeout(4096), router_http_timeout(16000)
    assert normal.read == 120
    assert large.read == 270 > 240
    assert large.connect == large.write == large.pool == 120


def test_http_read_timeout_follows_the_router_large_input_rule():
    """A big transcript must get the long read backstop even with a small output ceiling.

    Measured 2026-10-09 on the long-task owner turns: the router cut a ~108k-token request at
    exactly 90 s (`chat.failed TIMEOUT`, 90006/90011/90007 ms) while the harness's own backstop was
    120 s — both sides keyed "large" on `max_tokens` alone.
    """
    small_body = ROUTER_LARGE_INPUT_BYTES - 1
    assert router_http_timeout(4096, small_body).read == 120
    assert router_http_timeout(4096, ROUTER_LARGE_INPUT_BYTES).read == 270
    # The body measurement wins over the output ceiling, and an unknown size keeps the old default.
    assert router_http_timeout(4096, None).read == 120
    assert router_http_timeout(16000, small_body).read == 270
    assert router_http_timeout(16000, None).read == 270
    large = router_http_timeout(4096, ROUTER_LARGE_INPUT_BYTES)
    assert large.connect == large.write == large.pool == 120


def test_partial_checkpoint_retains_real_reason_refs_and_budget_after_restart(tmp_path):
    store, rt, model, _, sid = build(tmp_path)
    original = model.complete
    async def partial(*args, **kwargs):
        value = await original(*args, **kwargs)
        if value['choices'][0]['finish_reason'] == 'stop':
            value['choices'][0]['finish_reason'] = 'length'
        return value
    model.complete = partial
    async def run():
        rid, draft = await setup(rt, sid, node=DESIGN)
        output = draft['outputs'][0]
        checkpoint = output['checkpoint']
        assert output['status'] == 'failed'
        assert checkpoint['artifactId'] == output['artifact']['artifactId']
        assert checkpoint['execution']['reason'] == 'PROVIDER_OUTPUT_TRUNCATED'
        assert checkpoint['execution']['budget']['requestedMaxSteps'] == 200
        restarted = wg.WorkGraph(rt)
        current = restarted.get(rid)['nodes'][0]['stages']['produce']
        assert current['checkpoint'] == checkpoint
        assert current['artifact']['status'] == 'partial'
    asyncio.run(run())


def test_budget_eval_driver_reads_owner_limits_from_the_limits_module():
    """#9: driver đo ngân sách không được chép số cũ (60/1200) — phải đọc trần thật ở `limits.py`.

    Bản trước ghi cứng `maxSteps:60`/`deadlineSeconds:1200` (thời trước #6457) nên mọi lượt đo sau
    khi trần đổi vẫn chạy dưới một ngân sách không còn tồn tại, và cột `ownerSteps` trong kết quả
    nói sai thực tế. Bài này giữ hợp đồng đó: số của driver phải theo hằng số, kèm nguồn.
    """
    from pathlib import Path
    source = (Path(__file__).resolve().parents[3] / 'scripts/eval/work_budget_eval.py').read_text(encoding='utf-8')
    assert "'maxSteps':60" not in source and "'deadlineSeconds':1200" not in source, 'số cũ 60/1200 còn trong driver'
    assert "'maxSteps':OWNER_STEPS" in source and "'deadlineSeconds':OWNER_DEADLINE" in source
    assert 'limits_module.MAX_STEPS_DEFAULT' in source and 'limits_module.DEADLINE_DEFAULT_SECONDS' in source
    assert "'limitsSource':'agentbox.agent_core.limits'" in source, 'kết quả đo phải ghi nguồn số ngân sách'
