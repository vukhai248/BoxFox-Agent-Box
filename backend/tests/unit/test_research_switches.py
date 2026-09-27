"""Công tắc giết của P2/P3 (`limits.env_switch` và các hàm đọc): mặc định BẬT, `off` là đường lùi."""
from __future__ import annotations

from agentbox.agent_core import limits


def test_env_switch_never_raises_and_ignores_case_and_spaces():
    assert limits.env_switch('X', ('on', 'off'), 'on', {}) == 'on'
    assert limits.env_switch('X', ('on', 'off'), 'on', {'X': ' OFF '}) == 'off'
    assert limits.env_switch('X', ('on', 'off'), 'on', {'X': 'bật'}) == 'on'
    assert limits.env_switch('X', ('on', 'off'), 'on', {'X': None}) == 'on'


def test_every_p2_p3_switch_is_on_by_default_and_off_when_asked():
    pairs = ((limits.research_coverage_enabled, limits.RESEARCH_COVERAGE_ENV),
             (limits.research_structured_report_enabled, limits.RESEARCH_STRUCTURED_REPORT_ENV),
             (limits.research_time_policy_enabled, limits.RESEARCH_TIME_POLICY_ENV),
             (limits.research_critique_tier2_enabled, limits.RESEARCH_CRITIQUE_TIER2_ENV),
             (limits.research_branch_report_enabled, limits.RESEARCH_BRANCH_REPORT_ENV))
    assert len({name for _reader, name in pairs}) == len(pairs)  # một biến, một công tắc
    for reader, name in pairs:
        assert reader({}) is True, name
        assert reader({name: 'on'}) is True, name
        assert reader({name: 'off'}) is False, name


def test_the_switch_readers_do_not_look_at_the_real_environment_when_given_one():
    """`env={}` phải ĐỘC LẬP với môi trường thật: bài kiểm chạy được dù máy có đặt biến nào."""
    import os
    os.environ[limits.RESEARCH_COVERAGE_ENV] = 'off'
    try:
        assert limits.research_coverage_enabled({}) is True
    finally:
        del os.environ[limits.RESEARCH_COVERAGE_ENV]
