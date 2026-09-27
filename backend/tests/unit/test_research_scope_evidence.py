"""Một mục của thẻ phạm vi chỉ là "người dùng đã xác nhận" khi CÓ BẰNG CHỨNG máy kiểm được (§8.2/M-12).

Ba đường vào thẻ: công cụ của mô hình (`research_scope`), người dùng sửa trên giao diện
(`scope_update`), và câu hỏi phỏng vấn đã được người dùng trả lời thật (`answer_prompt` để lại
`answer.status='confirmed'`). Bài này ghim: chỉ hai đường SAU mới sinh `source.kind='user'`, và mô
hình tự khai `confirmed` thì mục vẫn là giả định trong brief của nhánh con.

Phần thứ hai ghim `issues[].kind` — hợp đồng `research_verify` hứa trường này (§5.9) và nhãn
`bao phủ chưa đủ` của thẻ báo cáo đọc nó.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import limits, research_review, research_runtime
from agentbox.memory.session_store import SessionStore


# --- thẻ phạm vi: bằng chứng "người dùng đã xác nhận" ------------------------

def test_an_agent_scope_item_never_becomes_a_confirmed_requirement():
    """Mô hình tự khai `confirmed` (không có nguồn người dùng) ⇒ GIẢ ĐỊNH, trong thẻ lẫn brief con."""
    scope = research_runtime._scope_apply_patch({}, {
        'goal': {'text': 'Mua nhà cung cấp X ngay', 'status': 'confirmed'}})
    goal = scope['goal']
    assert goal['status'] == 'assumed'
    assert goal['source']['kind'] == 'agent'

    items = research_review.scope_brief_items(scope)
    assert items['confirmed'] == []
    assert [item['text'] for item in items['assumed']] == ['Mua nhà cung cấp X ngay']

    brief = research_review.build_child_brief(scope, question='nhà cung cấp nào?')
    assert 'YÊU CẦU ĐÃ XÁC NHẬN' not in brief['text']
    assert research_review.ASSUMPTION_LABEL in brief['text']
    assert research_review.brief_leaks_assumption(brief) == []


def test_the_owner_marks_an_item_user_confirmed_and_the_brief_says_so():
    """Đường chủ nhà (`scope_update`) là đường DUY NHẤT tự mình sinh `source.kind='user'`."""
    scope = research_runtime._scope_apply_patch(
        {}, {'goal': {'text': 'Giữ nhà cung cấp cũ'}}, source_kind='user', seq=4)
    goal = scope['goal']
    assert goal['status'] == 'confirmed'
    assert goal['source'] == {'kind': 'user', 'seq': 4}

    items = research_review.scope_brief_items(scope)
    assert [item['text'] for item in items['confirmed']] == ['Giữ nhà cung cấp cũ']
    assert items['confirmed'][0]['sourceKind'] == 'user'
    brief = research_review.build_child_brief(scope)
    assert 'YÊU CẦU ĐÃ XÁC NHẬN (người dùng):' in brief['text']
    assert 'Giữ nhà cung cấp cũ' in brief['confirmed']


def test_an_answered_interview_question_can_mark_an_item_confirmed():
    """Câu hỏi đã được người dùng trả lời thật ⇒ mục mô hình ghi lại được coi là đã xác nhận."""
    scope = {'openQuestions': [{'id': 'iq1', 'text': 'giữ hay đổi?',
                                'answer': {'text': 'giữ', 'status': 'confirmed'}}]}
    scope = research_runtime._scope_apply_patch(scope, {
        'purpose': {'text': 'Giữ nhà cung cấp cũ', 'status': 'confirmed',
                    'source': {'kind': 'user', 'questionId': 'iq1'}}})
    purpose = scope['purpose']
    assert purpose['status'] == 'confirmed'
    assert purpose['source']['kind'] == 'user'
    assert purpose['source']['questionId'] == 'iq1'
    assert [item['text'] for item in research_review.scope_brief_items(scope)['confirmed']] \
        == ['Giữ nhà cung cấp cũ']


def test_an_unanswered_question_id_does_not_mark_an_item_confirmed():
    """`questionId` không có câu trả lời thật ⇒ vẫn là giả định, không có đường tắt nào."""
    scope = {'openQuestions': [{'id': 'iq1', 'text': 'giữ hay đổi?', 'answer': None}]}
    scope = research_runtime._scope_apply_patch(scope, {
        'purpose': {'text': 'Giữ nhà cung cấp cũ', 'status': 'confirmed',
                    'source': {'kind': 'user', 'questionId': 'iq1'}}})
    purpose = scope['purpose']
    assert purpose['status'] == 'assumed'
    assert purpose['source']['kind'] == 'agent'
    assert research_review.scope_brief_items(scope)['confirmed'] == []


def test_the_owner_revision_lock_refuses_a_non_integer_instead_of_leaking_python():
    """`revision` không phải số ⇒ MÃ hợp đồng, không phải thông báo của `int()` (finding 2)."""
    with pytest.raises(ValueError) as error:
        research_runtime._revision_arg({'revision': {}}, limits.RESEARCH_SCOPE_REVISION_INVALID_CODE)
    assert str(error.value).startswith(limits.RESEARCH_SCOPE_REVISION_INVALID_CODE)
    assert 'int()' not in str(error.value)
    assert research_runtime._revision_arg({}, limits.RESEARCH_SCOPE_REVISION_INVALID_CODE) is None
    assert research_runtime._revision_arg({'revision': '3'},
                                          limits.RESEARCH_SCOPE_REVISION_INVALID_CODE) == 3
    assert research_runtime._revision_arg({'revision': True},
                                          limits.RESEARCH_SCOPE_REVISION_INVALID_CODE) is None
    assert research_runtime._revision_arg({'revision': 7},
                                          limits.RESEARCH_SCOPE_REVISION_INVALID_CODE) == 7


# --- `issues[].kind` đi tới nhãn hồ sơ ---------------------------------------

def test_issue_kinds_survive_the_clamp_and_the_store(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    try:
        job = store.research_job_save('RS1', store.create({'skills': []})['id'],
                                      {'goal': 'x'}, status='verifying')
        issues = research_runtime._clamp_issues([
            {'severity': 'high', 'text': 'thiếu hướng về giá', 'kind': 'missing-direction'},
            {'severity': 'low', 'text': 'không có kind', 'kind': 'không-có-thật'}])
        assert issues[0]['kind'] == 'missing-direction'
        assert 'kind' not in issues[1]
        store.record_research_verification('RS1', 3, job['session_id'], 'revise', issues=issues,
                                          summary='s', critic_session_id='child-1',
                                          critic_answer_chars=900, critic_verdict='revise',
                                          mode='coverage')
        stored = store.research_verifications('RS1')[0]
        assert stored['issues'][0]['kind'] == 'missing-direction'
        assert research_review.has_unhandled_missing_direction(stored['issues']) is True
        assert research_review.coverage_label(stored['issues']) == limits.RESEARCH_COVERAGE_LABEL
    finally:
        store.close()


class FakeStore:
    """Đủ cho `_finish_background`: một việc, một bản hồ sơ đã qua cổng, hai lần ghi phán quyết."""

    def __init__(self, verifications):
        self.verifications = verifications
        self.emitted = []
        self.saved = []

    def research_job_save(self, research_id, sid, state, status=None, revision=None):
        self.saved.append((research_id, status, state.get('phase')))
        return {'research_id': research_id, 'session_id': sid, 'status': status,
                'state': state, 'revision': 1}

    def dossier_latest(self, research_id):
        return {'version': 3, 'relative_path': 'dossier/v3.md', 'critique': 'ok',
                'quality_ok': True, 'rows': 4, 'level': 2}

    def research_verifications(self, research_id, version=None, limit=20):
        return list(self.verifications)

    def emit(self, sid, kind, data=None):
        self.emitted.append((kind, data or {}))


class FakeRuntime:
    def __init__(self, store):
        self.store = store


def test_the_report_card_carries_the_coverage_label_for_an_open_missing_direction(monkeypatch):
    """Cổng chất lượng đã qua, nhưng còn hướng bị bỏ mức `high` ⇒ thẻ báo cáo phải mang nhãn."""
    monkeypatch.setattr(research_runtime.system_log, 'write', lambda *a, **k: None)
    store = FakeStore([{'verdict': 'revise', 'mode': 'coverage',
                        'issues': [{'severity': 'high', 'text': 'thiếu hướng về giá',
                                    'kind': 'missing-direction'}]}])
    job = {'research_id': 'RS1', 'session_id': 's1', 'status': 'completed',
           'state': {'reviewModes': ['evidence', 'critique'], 'phase': 'done'}, 'revision': 4}
    research_runtime._finish_background(FakeRuntime(store), {'id': 's1'}, job)
    report = [data for kind, data in store.emitted if kind == 'research_report']
    assert report and limits.RESEARCH_COVERAGE_LABEL in report[0]['labels']

    clean = FakeStore([{'verdict': 'ok', 'mode': 'coverage',
                        'issues': [{'severity': 'high', 'text': 'đã xử lý', 'fix': 'đã bổ sung',
                                    'kind': 'missing-direction', 'handled': True}]}])
    research_runtime._finish_background(FakeRuntime(clean), {'id': 's1'}, dict(job))
    report = [data for kind, data in clean.emitted if kind == 'research_report']
    assert report and limits.RESEARCH_COVERAGE_LABEL not in report[0]['labels']
