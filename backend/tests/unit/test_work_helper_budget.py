"""W6.5.3: helper lookup output cap (default 16000 after measurement) and its env override."""
import asyncio

import pytest

from agentbox.agent_core import output_policy as policy, work_graph as wg
from test_work_graph import build
from test_work_checks import RESEARCH


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


ENV = 'BOXFOX_WORK_HELPER_OUTPUT_TOKENS'
HELPER = {'runId': 'w-x', 'nodeId': 'R1', 'stage': 'produce', 'purpose': 'knowledge', 'helperRole': 'research'}


def test_unset_uses_measured_default(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    for role in ('research', 'explore'):
        assert policy.child_budget(role, HELPER) == 16000 == policy.WORK_HELPER_OUTPUT_TOKENS
    # Unrelated defaults are untouched by the W6.5.3 decision.
    assert policy.request_budget({}) == policy.DEFAULT_OUTPUT_TOKENS == 4096


@pytest.mark.parametrize('raw,expected', [('4096', 4096), ('16000', 16000)])
def test_override_applies_only_to_knowledge_helpers(raw, expected, monkeypatch):
    monkeypatch.setenv(ENV, raw)
    for var in ('BOXFOX_RESEARCH_OUTPUT_TOKENS', 'BOXFOX_DOCUMENT_OUTPUT_TOKENS',
                'BOXFOX_REVIEW_OUTPUT_TOKENS', 'BOXFOX_WORK_CHECK_OUTPUT_TOKENS'):
        monkeypatch.delenv(var, raising=False)
    assert policy.child_budget('research', HELPER) == expected
    assert policy.child_budget('explore', HELPER) == expected
    # Producer, reviewer and bound check profiles are not touched by the helper knob.
    assert policy.child_budget('research', {'purpose': 'produce', 'stage': 'produce'}) == 16000
    assert policy.child_budget('explore', {'purpose': 'produce', 'stage': 'produce'}) is None
    assert policy.child_budget('review', {'purpose': 'review', 'checkId': 'c1'}) == 16000
    assert policy.child_budget('research', {'purpose': 'review', 'stage': 'review'}) is None
    # Outside Work Graph (no binding) the knob has no effect either.
    assert policy.child_budget('explore') is None
    assert policy.child_budget('research', task_kind='knowledge') is None


@pytest.mark.parametrize('raw', ['8192', '0', 'banana', '', '64000', '32000'])
def test_invalid_override_fails_closed(raw, monkeypatch):
    monkeypatch.setenv(ENV, raw)
    with pytest.raises(ValueError, match='OUTPUT_BUDGET_INVALID: BOXFOX_WORK_HELPER_OUTPUT_TOKENS'):
        policy.child_budget('research', HELPER)


def test_parent_ceiling_still_bounds_helper_request():
    assert policy.request_budget({'maxTokens': 16000, 'outputTokenCeiling': 8192}) == 8192


@pytest.mark.parametrize('raw,expected', [(None, 16000), ('16000', 16000), ('4096', 4096)])
def test_helper_child_request_uses_override_through_runtime(raw, expected, tmp_path, monkeypatch):
    if raw is None:
        monkeypatch.delenv(ENV, raising=False)
    else:
        monkeypatch.setenv(ENV, raw)
    _, rt, model, _, sid = build(tmp_path)
    graph = wg.service(rt)
    run = graph.create(rt.store.get(sid), {'goal': 'Research export formats', 'flow': 'research'})
    result = asyncio.run(graph.answer_knowledge(rt.store.get(sid), run, wg.normalize_node(RESEARCH), 'produce',
                                                [{'role': 'research', 'question': 'Where is CSV declared?'}], 1))
    assert result[0]['status'] == 'completed'
    assert [tokens for kind, _, tokens in model.tokens if kind == 'knowledge'] == [expected]
    child = rt.store.get(result[0]['childId'])['config']
    assert child.get('maxTokens') == expected
    assert child['workBinding']['purpose'] == 'knowledge'
