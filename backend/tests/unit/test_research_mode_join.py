"""P3 lắp vào lõi: chế độ soát của run có MỘT nguồn sự thật (`research_review.review_modes`).

Cổng hồ sơ chỉ đòi mode mà `research_verify` ghi được (`GATE_REVIEW_MODES`), còn `reviewModes`
công bố cho mô hình/giao diện thì theo đủ bộ `research_review.REVIEW_MODES` (có `coverage`).
"""
from __future__ import annotations

import asyncio
import pathlib

import pytest

from agentbox.agent_core import research_review, research_runtime
from agentbox.agent_core.limits import (
    RESEARCH_CRITIQUE_TIER2_ENV, RESEARCH_VERIFY_UNKNOWN_CODE)
from agentbox.memory.session_store import SessionStore

OFF = {RESEARCH_CRITIQUE_TIER2_ENV: 'off'}
ON = {RESEARCH_CRITIQUE_TIER2_ENV: 'on'}


def modes(tier, state=None, env=ON):
    return research_review.review_modes(tier, state or {}, env=env)


def test_the_run_rules_are_the_review_module_rules():
    questions = [{'text': 'a', 'importance': 'high'}, {'text': 'b', 'importance': 'high'},
                 {'text': 'c', 'importance': 'medium'}]
    state = {'questions': questions, 'output': 'Plan a referral agent',
             'scope': {'jobKinds': ['landscape']}}
    assert research_runtime._choose_review_modes(2, questions, 'Plan a referral agent',
                                                 state['scope']) == modes(2, state)
    assert research_runtime._choose_review_modes(3, [], '') == modes(3, {})
    assert research_runtime._choose_review_modes(1, [], '') == modes(1, {})


def test_a_third_tier_run_declares_coverage_but_the_gate_does_not_demand_it():
    state = {'questions': [], 'output': ''}
    declared = modes(3, state)
    assert declared == ['evidence', 'critique', 'coverage']
    assert research_runtime._review_modes_for(state, 3) == ['evidence', 'critique']
    with_coverage = {'questions': [], 'output': '', 'reviewModes': list(declared)}
    assert research_runtime._review_modes_for(with_coverage, 3) == ['evidence', 'critique']


def test_the_critique_switch_keeps_tier_two_on_the_old_constant_when_it_is_off():
    many = {'questions': [{'text': 'a', 'importance': 'high'}, {'text': 'b', 'importance': 'high'},
                          {'text': 'c', 'importance': 'medium'}], 'output': 'plan'}
    assert modes(2, many) == ['evidence', 'critique']
    assert modes(2, many, env=OFF) == ['evidence']
    assert research_runtime._review_modes_for({'reviewModes': ['critique']}, 2) == ['critique']


def test_a_coverage_verdict_is_recordable_because_the_tool_accepts_it(tmp_path):
    store = SessionStore(pathlib.Path(tmp_path) / 'sessions.sqlite')
    sid = store.create({'skills': []})['id']
    runtime = type('FakeRuntime', (), {'store': store})()

    async def call(mode):
        return await research_runtime.research_verify(
            runtime, store.get(sid),
            {'researchId': 'RS1', 'version': 1, 'verdict': 'ok', 'mode': mode})

    with pytest.raises(ValueError, match='RESEARCH_VERIFY_MODE_INVALID'):
        asyncio.run(call('banana'))
    with pytest.raises(ValueError, match=RESEARCH_VERIFY_UNKNOWN_CODE):
        asyncio.run(call('coverage'))
