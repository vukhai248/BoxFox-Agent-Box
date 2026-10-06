"""Contract regressions; semantic correctness also requires live adjudication."""
import asyncio

import pytest

from agentbox.agent_core import work_checks, work_policy, work_prompts
from test_work_graph import build, raw_tool
from test_work_checks import setup, start


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ; khóa tổng `BOXFOX_REFORM` đã bị xoá ở bước B5
# (HANDOFF §10.3) nên nhãn `legacy_path` không còn kèm env nào để pin.
pytestmark = pytest.mark.legacy_path


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
    assert work_policy.VERSION == 'work-checks/10'


@pytest.mark.parametrize('lang,terms', [
    ('en', ('optional notes relevant', 'opened original evidence or actual execution',
            'Check numeric examples', 'omit unchecked', 'requires final VERDICT: revise')),
    ('vi', ('Ghi chú tùy chọn phải liên quan', 'gốc đã mở hoặc lệnh thực đã chạy',
            'Kiểm ví dụ số', 'bỏ minh họa chưa kiểm', 'cuối phải VERDICT: revise')),
])
def test_notes_and_criterion_conflicts_follow_the_same_evidence_contract(lang, terms):
    assert all(term in work_prompts.review_tail(lang) for term in terms)


@pytest.mark.parametrize('lang,terms', [
    ('en', ('Establish each proposed correction independently', 'Preserve values',
            'original inputs, units', 'applicable conversion rule from opened evidence',
            'inequalities and code-point ranges', 'omit the invented replacement',
            'does not prove the opposite claim', 'Quote only text present', 'smallest evidenced correction')),
    ('vi', ('chứng minh riêng từng', 'giữ giá trị', 'input gốc, đơn vị',
            'quy tắc chuyển đổi từ nguồn đã mở', 'bất đẳng thức', 'khoảng code point',
            'bỏ giá trị bịa', 'chưa chứng minh claim ngược lại', 'Chỉ trích nguyên văn',
            'sửa tối thiểu có bằng chứng')),
])
def test_one_valid_finding_cannot_license_unproved_numeric_or_quoted_corrections(lang, terms):
    assert all(term in work_prompts.review_tail(lang) for term in terms)


@pytest.mark.parametrize('lang,terms', [
    ('en', ('REVIEW SCOPE: node R1, stage produce', 'Assigned work: Verify the premise',
            'Owner constraints', 'does not make', 'cannot remove assigned requirements')),
    ('vi', ('PHẠM VI REVIEW: nút R1, pha produce', 'Nhiệm vụ được giao: Verify the premise',
            'Ràng buộc người dùng', 'nó không nêu', 'không xóa yêu cầu được giao')),
])
def test_node_scope_respects_constraints_and_does_not_inherit_all_owner_work(lang, terms):
    assert all(term in work_prompts.node_review_scope({'id': 'R1', 'goal': 'Verify the premise'}, 'produce', lang)
               for term in terms)


def test_node_check_dispatch_includes_actual_assignment_scope(tmp_path):
    _, rt, model, _, sid = build(tmp_path)

    async def run():
        _, draft = await setup(rt, sid)
        await start(rt, sid, draft)
        assert 'REVIEW SCOPE: node R1, stage produce' in model.prompts[-1][1]
        assert 'Assigned work: Compare two export formats using the provided evidence' in model.prompts[-1][1]
        assert 'Coverage elsewhere belongs to whole review' in model.prompts[-1][1]

    asyncio.run(run())


@pytest.mark.parametrize('lang', ['en', 'vi'])
@pytest.mark.parametrize('research', [False, True])
def test_whole_scope_keeps_global_coverage_without_widening_every_node(lang, research):
    text = work_prompts.whole_review_goal('Title', 'Goal', lang, research_only=research)
    assert ('Missing overall coverage belongs to the whole-run criteria' if lang == 'en'
            else 'Thiếu bao phủ tổng thể thuộc tiêu chí toàn run') in text
    assert ('within its assignment' if lang == 'en' else 'trong nhiệm vụ của nút') in text
