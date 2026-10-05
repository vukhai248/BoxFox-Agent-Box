"""H12 — khóa tổng `BOXFOX_REFORM`: một tay nắm cho cả nhóm công tắc H3–H8.

Luật (chủ nhà 04/10/2026, bật dần từng công tắc):
1. Thiếu env ⇒ TẮT (giữ nguyên hành vi cũ) — mọi công tắc thành viên theo khóa tổng.
2. `BOXFOX_REFORM=on` ⇒ cả nhóm BẬT; `=off` ⇒ cả nhóm TẮT.
3. Công tắc thành viên đặt tường minh LUÔN thắng khóa tổng (để bật dần từng cái).
4. `/api/agent/runtime-info` phải cho thấy khóa tổng và từng thành viên kèm nguồn.
"""
import pytest

from agentbox.agent_core import feature_switches as fs
from agentbox.agent_core import context_surface, job_surface, recovery_policy, research_gateway
from agentbox.agent_core import task_surface, tool_contracts, usage_ledger

MEMBERS = fs.MEMBERS

READERS = {
    'BOXFOX_TASK_SURFACE': (task_surface.enabled, tool_contracts.task_surface_enabled),
    'BOXFOX_CONTEXT_SURFACE': (context_surface.enabled,),
    'BOXFOX_CONTROLLER_JOBS': (job_surface.enabled, tool_contracts.controller_jobs_enabled),
    'BOXFOX_USAGE_LEDGER': (usage_ledger.enabled,),
    'BOXFOX_RESEARCH_GATEWAY': (research_gateway.enabled,),
    'BOXFOX_RECOVERY_POLICY': (recovery_policy.enabled,),
}


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in MEMBERS + (fs.MASTER_SWITCH,):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


def test_master_is_off_when_unset_and_every_member_follows():
    assert fs.master() is False
    assert [fs.member_switch(name) for name in MEMBERS] == [False] * len(MEMBERS)
    assert {fs.source(name) for name in MEMBERS} == {'default'}


def test_master_on_turns_the_whole_group_on(clean_env):
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    assert fs.master() is True
    assert [fs.member_switch(name) for name in MEMBERS] == [True] * len(MEMBERS)
    assert {fs.source(name) for name in MEMBERS} == {'master'}


def test_master_off_turns_the_whole_group_off(clean_env):
    clean_env.setenv(fs.MASTER_SWITCH, 'off')
    assert fs.member_switch('BOXFOX_TASK_SURFACE') is False


@pytest.mark.parametrize('value', ['on', 'ON', 'true', '1', 'yes'])
def test_master_accepts_every_on_spelling(clean_env, value):
    clean_env.setenv(fs.MASTER_SWITCH, value)
    assert fs.master() is True


def test_an_explicit_member_wins_over_the_master_in_both_directions(clean_env):
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    clean_env.setenv('BOXFOX_RECOVERY_POLICY', 'off')
    assert fs.member_switch('BOXFOX_RECOVERY_POLICY') is False
    assert fs.source('BOXFOX_RECOVERY_POLICY') == 'explicit'
    clean_env.setenv(fs.MASTER_SWITCH, 'off')
    clean_env.setenv('BOXFOX_TASK_SURFACE', 'on')
    assert fs.member_switch('BOXFOX_TASK_SURFACE') is True
    assert fs.source('BOXFOX_TASK_SURFACE') == 'explicit'


def test_a_blank_member_value_is_not_an_explicit_choice(clean_env):
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    clean_env.setenv('BOXFOX_TASK_SURFACE', '   ')
    assert fs.member_switch('BOXFOX_TASK_SURFACE') is True
    assert fs.source('BOXFOX_TASK_SURFACE') == 'master'


@pytest.mark.parametrize('name,readers', list(READERS.items()))
def test_every_member_reader_follows_the_master(clean_env, name, readers):
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    for reader in readers:
        assert reader() is True, (name, reader)
    clean_env.setenv(fs.MASTER_SWITCH, 'off')
    for reader in readers:
        assert reader() is False, (name, reader)


def test_execution_kernel_switch_follows_the_master_for_its_two_members(clean_env):
    from agentbox.agent_core import execution_kernel
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    assert execution_kernel.enabled() is True
    assert execution_kernel._switch(execution_kernel.LEDGER_SWITCH) is True
    clean_env.setenv(fs.MASTER_SWITCH, 'off')
    assert execution_kernel.enabled() is False
    assert execution_kernel._switch(execution_kernel.LEDGER_SWITCH) is False


def test_switch_readers_still_honour_their_own_raw_test_value(clean_env):
    """Khuôn cũ của test (`env=`/`value=`) không đổi: giá trị thô truyền vào thắng khóa tổng."""
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    assert task_surface.enabled('off') is False
    assert usage_ledger.enabled('off') is False
    assert recovery_policy.enabled('off') is False
    assert research_gateway.enabled('off') is False
    assert job_surface.enabled('off') is False
    assert tool_contracts.task_surface_enabled('off') is False


def test_snapshot_names_the_master_and_every_member_with_its_source(clean_env):
    snap = fs.snapshot()
    assert snap['master'] == {'name': 'BOXFOX_REFORM', 'on': False, 'source': 'default'}
    assert set(snap['members']) == set(MEMBERS)
    assert all(item == {'on': False, 'source': 'default'} for item in snap['members'].values())
    clean_env.setenv(fs.MASTER_SWITCH, 'on')
    clean_env.setenv('BOXFOX_CONTEXT_SURFACE', 'off')
    snap = fs.snapshot()
    assert snap['master'] == {'name': 'BOXFOX_REFORM', 'on': True, 'source': 'explicit'}
    assert snap['members']['BOXFOX_CONTEXT_SURFACE'] == {'on': False, 'source': 'explicit'}
    assert snap['members']['BOXFOX_TASK_SURFACE'] == {'on': True, 'source': 'master'}
