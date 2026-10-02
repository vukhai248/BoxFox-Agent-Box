"""Vai phản biện hồ sơ (`research-review`, vòng 27 đợt 6, D-36/D-40).

Người phản biện phải là người KHÔNG viết ra bản ấy: chỉ đọc, không được gieo bằng chứng cho hồ sơ
nó đang chấm, không sửa hồ sơ, và không tự ghi phán quyết. Ba ca ở đây ghim đúng ba chuyện ấy —
chúng là hợp đồng giữa `roles.py` và cổng `research_critique`, không phải chuyện văn phong.
"""
from __future__ import annotations

from agentbox.agent_core import roles


def test_the_research_critic_role_exists_and_can_only_read():
    role = roles.ROLES['research-review']
    assert role.name == 'Research Review'
    # W6.1.3 + quyết định #6423: người phản biện hồ sơ cũng kiểm chứng được số liệu bằng verify_exec
    # (đọc repo read-only, ghi scratch trong /tmp/work, ra mạng được) — vẫn không có quyền ghi vào hồ sơ.
    assert role.tools == roles.READ | roles.SOURCE_READ | {'web_search', 'web_fetch', 'read_source', 'paper_citations', 'claim_assess', 'verify_exec'}
    assert 'claim_assess' in roles.allowed_tools('research-review', parent=roles.ORCHESTRATOR_TOOLS)
    for forbidden in ('source_add', 'dossier_write', 'research_verify', 'write_plan', 'delegate_task'):
        assert forbidden not in role.tools, f'vai phản biện không được có {forbidden}'
    assert {'file_read', 'source_list', 'source_verify', 'research_status'} <= set(role.tools)
    assert role.skills == (), 'vai phản biện không cần skill nào'


def test_the_research_critic_instructions_demand_a_final_verdict_line():
    text = roles.RESEARCH_REVIEW_INSTRUCTIONS
    assert 'VERDICT: ok' in text and 'VERDICT: revise' in text
    lowered = text.lower()
    assert 'final line' in lowered or 'last line' in lowered
    assert 'source_verify' in text, 'phải mở LẠI nguồn, không tin lời kể'
    assert 'never edit the dossier' in lowered and 'never insert source rows' in lowered


def test_the_review_role_is_declared_last_in_the_delegate_enum_and_the_research_role_reads_the_ledger():
    from agentbox.agent_core import tool_contracts

    delegate = [item for item in tool_contracts.SCHEMAS if item['function']['name'] == 'delegate_task']
    assert len(delegate) == 1
    enum = delegate[0]['function']['parameters']['properties']['role']['enum']
    assert enum[-1] == 'research-review', 'giá trị mới phải nằm CUỐI enum (hợp đồng FE)'
    assert set(enum) <= set(roles.ROLES)
    # Vai research GHI được sổ, ĐỌC được trạng thái việc và GHI được hồ sơ qua đúng một công cụ
    # (`dossier_write`, op của box — không phải `file_write`). Mức/hồ sơ/phán quyết vẫn của main.
    research = roles.ROLES['research'].tools
    assert {'source_add', 'source_list', 'source_verify', 'research_status'} <= set(research)
    # "Không mở quyền ghi cho con" (ledger subplan §A3.5): nhánh KHÔNG có đường ghi hồ sơ.
    assert {'dossier_write', 'research_brief', 'research_verify', 'file_write',
            'delegate_task'} & set(research) == set()
    assert 'research-team' in roles.ROLES['research'].skills
    assert 'grounded-citations' in roles.ROLES['research'].skills


def test_the_supervisor_role_cannot_be_confused_with_the_worker_role():
    assert roles.ROLES['research-review'].id != roles.ROLES['research'].id
    assert roles.ROLES['research-review'].instructions != roles.ROLES['research'].instructions
    assert 'source_add' in roles.ROLES['research'].tools
