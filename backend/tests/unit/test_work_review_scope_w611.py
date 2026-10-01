"""Contract regressions; semantic correctness also requires live adjudication."""
import asyncio

import pytest

from agentbox.agent_core import work_checks, work_policy, work_prompts
from test_work_graph import build, raw_tool
from test_work_checks import setup, start


@pytest.mark.parametrize('lang,terms', [
    ('en', ('premise supplied by main', 'conflicting criterion', 'false premise')),
    ('vi', ('Tiền đề main', 'tiêu chí mâu thuẫn', 'tiền đề sai')),
])
def test_assignment_premises_are_not_source_evidence(lang, terms):
    tail = work_prompts.review_tail(lang)
    assert all(term in tail for term in terms)
    assert tail in work_checks.contract(lang, {}) or all(
        term in work_prompts.whole_review_goal('Title', 'Goal', lang) for term in terms)


@pytest.mark.parametrize('lang,terms', [
    ('en', ('unit', 'target version', 'dialect', 'default versus configured',
            'bytes from characters', 'decoded values')),
    ('vi', ('đơn vị', 'phiên bản đích', 'dialect', 'mặc định so với cấu hình',
            'byte với ký tự', 'giá trị sau giải mã')),
])
def test_version_unit_and_representation_checks_remain_explicit(lang, terms):
    assert all(term in work_prompts.review_tail(lang) for term in terms)


@pytest.mark.parametrize('lang,terms', [
    ('en', ('One authoritative source can suffice', 'versioned branch',
            'commit pin alone', 'only when tools and scope permit', 'NOT RUN')),
    ('vi', ('Một nguồn chính thức có thể đủ', 'Nhánh có phiên bản',
            'thiếu commit pin', 'khi công cụ và phạm vi cho phép', 'NOT RUN')),
])
def test_reviewer_does_not_invent_source_or_execution_requirements(lang, terms):
    assert all(term in work_prompts.review_tail(lang) for term in terms)


def test_verified_response_limits_main_to_checked_snapshots(tmp_path):
    _, rt, _, _, sid = build(tmp_path)

    async def run():
        rid, draft = await setup(rt, sid)
        await start(rt, sid, draft)
        result = await raw_tool(rt, sid, 'work_graph', {'action': 'verify', 'runId': rid})
        assert result['status'] == 'verified' and result['documents']
        assert all(doc['path'] for doc in result['documents'])
        assert 'checked artifacts' in result['next']
        assert 'snapshots only' in result['next']
        assert 'New consequential conclusions' in result['next']
        assert result['next'] in rt.work_graph.prompt_block(rt.store.get(sid))

    asyncio.run(run())


def test_contract_change_has_a_new_policy_version():
    assert work_policy.VERSION == 'work-checks/7'
