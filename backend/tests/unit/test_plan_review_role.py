"""Vai thứ mười `plan-review` + kỹ năng `planning` (vòng 25, D-33/D-34).

Vì sao có tệp này: đo vòng 25 thấy sau `plan_written` lượt **dừng ngay** — 6 lượt, 0 con `review`,
0 `await_children`, 0 `request_approval` (BUG-1). Căn là việc lập kế hoạch chỉ có MỘT vai ghi, còn
việc phản biện chỉ được *khuyên*. Vòng 25 thêm vai `plan-review` (chỉ-đọc, kết thúc bằng
`VERDICT:`), công cụ `plan_verify` cho orchestrator, và kỹ năng `planning` nói vòng lặp đó ra thành
lời. Bốn thứ dưới đây phải khớp nhau, nếu không thì bản kế hoạch vẫn đi thẳng từ lệnh ghi tới câu
xin duyệt.
"""
from __future__ import annotations

import pytest

from agentbox.agent_core import runtime as runtime_module
from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS, READ, ROLES, VERIFY
from agentbox.agent_core.tool_contracts import SCHEMAS
from agentbox.agent_core.tool_groups import TOOL_GROUPS
from agentbox.skills.catalog import DEFAULT_SKILLS, SkillCatalog
from agentbox.memory.session_store import SessionStore
from agentbox.skills.commands import ROLE_COMMANDS, ROLE_SKILLS, CommandRegistry

ROLE = 'plan-review'


def delegate_roles():
    schema = next(item for item in SCHEMAS if item['function']['name'] == 'delegate_task')
    return schema['function']['parameters']['properties']['role']['enum']


def test_the_critic_role_exists_and_can_only_read():
    role = ROLES[ROLE]
    assert role.name == 'Plan review'
    # W6.1.3 + quyết định #6423: plan-review có thêm verify_exec (đọc repo read-only, ghi scratch
    # trong /tmp/work, ra mạng được) — vẫn không có công cụ ghi nào vào repo/kế hoạch.
    assert role.tools == READ | VERIFY, 'người phản biện không được có công cụ ghi nào'
    for forbidden in ('write_plan', 'file_write', 'file_edit_block', 'terminal_exec', 'browser_use',
                      'computer_use'):
        assert forbidden not in role.tools, forbidden
    assert role.skills == ('codebase-inspection',)


def test_the_critic_instructions_demand_findings_and_a_verdict_line():
    text = ROLES[ROLE].instructions
    assert len(text) > 200
    for required in ('VERDICT: ok', 'VERDICT: revise', 'severity', 'high', 'medium', 'low',
                     'path:line', 'UNVERIFIED'):
        assert required in text, required
    assert 'Findings by Severity' in text
    for section in ('Milestones That Cannot Be Executed As Written',
                    'Acceptance Checks That Would Not Prove Anything',
                    'Missing Risks, Unknowns And Unverified Claims'):
        assert section in text, section
    assert text.rstrip().endswith('unusable.'), 'câu chốt nằm ở cuối khối chỉ dẫn'


def test_only_the_orchestrator_may_write_a_verification():
    assert 'plan_verify' in ORCHESTRATOR_TOOLS
    for name, role in ROLES.items():
        assert 'plan_verify' not in role.tools, name
    group = next(item for item in TOOL_GROUPS if item['key'] == 'delegationPlans')
    assert 'plan_verify' in group['tools']
    schema = next(item for item in SCHEMAS if item['function']['name'] == 'plan_verify')
    params = schema['function']['parameters']
    assert params['required'] == ['identity', 'version', 'verdict']
    props = params['properties']
    assert props['verdict']['enum'] == ['ok', 'revise']
    assert props['issues']['type'] == 'array'
    issue = props['issues']['items']['properties']
    assert issue['severity']['enum'] == ['high', 'medium', 'low']
    assert {'severity', 'text'} <= set(props['issues']['items']['required'])


def test_the_delegation_contract_offers_eleven_roles_in_order():
    assert delegate_roles() == ['explore', 'plan', ROLE, 'design', 'build', 'debug', 'review',
                                'simplify', 'testing', 'research', 'research-review']
    assert list(ROLES) == delegate_roles(), 'enum và ROLES phải là cùng một danh sách, cùng thứ tự'
    # Câu giải thích nằm ở MÔ TẢ CỦA CHÍNH THAM SỐ `role` (chỗ model đọc khi chọn vai), không phải
    # ở mô tả công cụ — nên bài này đọc đúng chỗ đó.
    role_param = next(item for item in SCHEMAS
                      if item['function']['name'] == 'delegate_task')['function']['parameters']
    text = role_param['properties']['role']['description']
    assert ROLE in text and 'VERDICT:' in text
    assert 'plan_verify' in text and 'before that plan can be approved' in text
    # Câu "chưa phản biện thì không duyệt được" phải nằm ngay ở mô tả `request_approval` — nơi model
    # đọc trước khi tiêu một lượt chờ người thật.
    approval = next(item for item in SCHEMAS
                    if item['function']['name'] == 'request_approval')['function']['description']
    assert 'PLAN_APPROVAL_UNVERIFIED' in approval and ROLE in approval


def test_a_slash_command_resolves_to_the_critic_role(tmp_path):
    assert ROLE_COMMANDS[ROLE] == ROLE
    store = SessionStore(tmp_path / 'commands.sqlite')
    registry = CommandRegistry(store, SkillCatalog())
    registry.configure({'enabled': list(registry.catalog.items), 'revision': 0})
    command = registry.resolve('/' + ROLE + ' soi ban v1')
    store.close()
    assert command.kind == 'task' and command.role == ROLE
    assert command.skills == ['codebase-inspection'], 'kỹ năng của vai phải theo ROLE_SKILLS'


def test_the_critic_skills_exist_in_the_catalog():
    catalog = SkillCatalog()
    assert ROLE_SKILLS[ROLE] <= set(catalog.items), 'một kỹ năng không có trong catalog là KeyError lúc chạy'


# --- SOP + kỹ năng `planning` -------------------------------------------------------------------

def sop():
    return runtime_module.ORCHESTRATOR_SOP_GUIDANCE


def test_the_sop_names_the_loop_and_its_hard_rule():
    text = sop()
    assert '10 specialist' in text
    for required in (ROLE, 'plan_verify', 'PLAN_APPROVAL_UNVERIFIED',
                     'must additionally carry a recorded independent critique'):
        assert required in text, required
    assert 'Two `revise` rounds per turn is the cap' in text, 'trần vòng sửa phải nói ra trong SOP'
    assert text.count('plan-review') >= 2, 'vòng lặp cần vai này ở cả bước phản biện lẫn bước sửa'


def test_the_planning_skill_is_a_default_and_is_named_in_the_enabled_block():
    assert 'planning' in DEFAULT_SKILLS
    catalog = SkillCatalog()
    assert 'planning' in catalog.items
    block = catalog.prompt(['planning'])
    assert block.startswith('- planning: ')
    assert 'plan_verify' in catalog.read('planning')['content']


def test_the_planning_skill_keeps_the_two_round_cap():
    text = SkillCatalog().read('planning')['content']
    assert 'plan-review' in text and 'plan_verify' in text
    assert 'VERDICT:' in text
    assert '2' in text and 'revise' in text
    # Câu bất biến của D-34 là nguyên văn: model đọc đúng câu này thì cổng không còn là bất ngờ.
    assert 'without a critique you cannot request approval' in text


@pytest.mark.parametrize('module_name', ['agentbox.agent_core.roles',
                                         'agentbox.agent_core.tool_contracts'])
def test_the_role_never_leaks_into_a_child_schema(module_name):
    """Không vai con nào có `plan_verify`, và cũng không có công cụ thứ hai để ghi phán quyết."""
    module = __import__(module_name, fromlist=['*'])
    schemas = getattr(module, 'SCHEMAS', None) or []
    names = [item['function']['name'] for item in schemas]
    assert names.count('plan_verify') <= 1
