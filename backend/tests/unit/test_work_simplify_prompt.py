"""W11.PROMPT (P1/P3) — prompt vai Simplify phải khớp nhiệm vụ thật, không ép khai man.

Ba điều được ghim ở đây, đúng mục 37.2/37.5 của `docs/plan/Work-Graph-fix.md`:

- **Chế độ theo nhiệm vụ:** câu "Apply Streamlined Edits" cũ ra lệnh sửa bất kể assignment
  khảo sát; nay việc sửa chỉ được phép khi assignment cấp quyền ghi, còn lượt chỉ khảo sát
  phải trả finding kèm `file:line` và để nguyên cây.
- **Kiểm trung thực:** "guarantee zero behavioral regressions" và "demonstrating 100% passing
  tests" là hai câu bất khả thi — suite xanh không chứng minh hết regression, và baseline đỏ
  thì mẫu báo cáo cũ ép người viết che failure. Bản mới đòi lệnh thật + kết quả trước/sau và
  khai đủ failure/skip/NOT RUN.
- **Finding chặn có bằng chứng không bị bỏ im lặng:** kỹ năng vendor `simplify-code` cho phép
  "drop weak or wrong suggestions silently"; luật đó chỉ áp cho đề xuất dọn tùy chọn, không áp
  cho finding chặn có bằng chứng — finding đó phải được adjudicate kèm lý do và nguồn.

Các test này chỉ đọc prompt đã lắp (text), không gọi model và không đổi quyền của vai.
"""
from __future__ import annotations

from agentbox.agent_core.roles import ROLES, WRITE
from agentbox.skills.catalog import SkillCatalog
from agentbox.skills.commands import ROLE_SKILLS


def _simplify_text() -> str:
    return ROLES['simplify'].instructions


def test_the_old_impossible_claims_are_gone():
    text = _simplify_text()
    assert '100% passing tests' not in text
    assert 'guarantee zero behavioral regressions' not in text
    assert 'Complexity Reduction Metrics' not in text


def test_edits_follow_the_assignment_and_survey_mode_leaves_the_tree_alone():
    text = _simplify_text()
    assert 'apply edits with `file_edit_block` only when the assignment grants a write scope' in text
    assert 'survey-only assignment reports findings with `file:line` and leaves the tree untouched' in text


def test_verification_is_honest_about_failures_skips_and_unrun_tests():
    text = _simplify_text()
    assert 'run the targeted tests for the behaviour you touched' in text
    assert 'every failure, skip or NOT RUN' in text
    assert 'A green suite does not prove zero regressions' in text
    assert 'before/after output' in text


def test_an_evidenced_blocking_finding_is_never_dropped_silently():
    text = _simplify_text()
    assert 'Do not silently drop a blocking finding that carries evidence' in text
    assert 'adjudicate it with a reason and its source' in text
    assert 'optional cleanup idea may be dropped when you say why' in text


def test_the_work_graph_note_still_lands_after_the_role_protocol():
    text = _simplify_text()
    assert 'Work Graph node: when the prompt starts with' in text
    assert text.index('Mode Follows The Assignment') < text.index('Work Graph node: when the prompt starts with')


def test_the_role_keeps_its_permissions_and_skill_wiring():
    role = ROLES['simplify']
    assert role.tools == WRITE, 'W11 chỉ tinh chỉnh prompt — quyền ghi của vai không đổi'
    assert ROLE_SKILLS['simplify'] == {'simplify-code', 'codebase-inspection'}
    catalog = SkillCatalog()
    assert 'simplify-code' in catalog.items, 'kỹ năng vendor của vai phải còn trong catalog'
