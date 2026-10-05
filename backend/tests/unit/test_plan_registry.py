"""Luật identity/số version/trạng thái duyệt: `agent_core/plan_registry.py`.

Ba nhóm chính, theo đúng nghiệm thu của plan §6 bước 2:

* ranh giới Jaccard được **ghim** ở 0.49 / 0.5 / 0.74 / 0.75 (không có bảng stop-word để tinh chỉnh);
* `identity`/`relatesTo` khai báo tường minh thắng mọi suy đoán;
* R1/R2/R3 và `next_version_and_parent`, cùng nhánh suy giảm khi không đọc được chỉ mục;
* **vé mơ hồ** (D-3 / C4): dải `0.5 ≤ j < 0.75` từ chối lần đầu nhưng để lại vé, gửi lại nguyên văn thì
  nhận — và vé tiêu đúng một lần (nhóm đã có mặt ⇒ mọi lần sau đi theo chỉ mục).

Ca sống (v3/v4 của vòng 20) có mặt nguyên vẹn: `{clinical,patient,record,lookup,research}` vs
`{research,patient,record,lookup}` → j = 4/5 = 0.8 → gộp, `v4` mang `Parent: v3`.
"""
from __future__ import annotations

import asyncio
import unittest

from agentbox.agent_core import plan_registry
from agentbox.agent_core.plan_registry import (
    AMBIGUITY_MATCHED_BY, AMBIGUITY_TICKET_KEY, AMBIGUOUS_THRESHOLD, IDENTITY_FORCED_NEW_CODE,
    INDEX_PATH, INDEX_UNAVAILABLE_CODE,
    MERGE_THRESHOLD, RegistrationPlan, PlanIndex, PlanIndexEntry, PlanRegistrationError,
    PlanGroup, ambiguity_ticket_usable, build_ambiguity_ticket, group_state, jaccard,
    next_version_and_parent, parse_plan_index, parse_relates_to,
    pending_submissions, plan_registration, plan_outside_room, read_plan_index, resolve_identity,
    review_stale, rejection_message, slug_tokens, split_identity, ticket_from_rows,
)

CLINICAL = 'clinical-patient-record-lookup-research'
RESEARCH = 'research-patient-record-lookup'

# Dải mơ hồ D-3: `{research, patient, record}` chung, `history` ≠ `lookup` ⇒ j = 3/5 = 0.6.
AMBIGUOUS_SLUG = 'research-patient-record-history'
# Dải gộp: thêm một token ⇒ j = 4/5 = 0.8 (vé mơ hồ **không** được đụng vào nhánh này).
MERGE_BAND_SLUG = 'research-patient-record-lookup-history'


def group(identity, *numbers, size=1000, modified='2026-09-20T13:56:00Z', header='ok'):
    directory, slug = split_identity(identity)
    versions = tuple(PlanIndexEntry(version=number, relative_path=f'.plans/v{number}-{slug}.md',
                                    size_bytes=size, modified_at=modified, header_status=header)
                     for number in numbers)
    return PlanGroup(identity=identity, directory=directory, slug=slug, versions=versions)


def index_of(*groups, warnings=()):
    return PlanIndex(groups=tuple(groups), warnings=tuple(warnings))


class FakeExecutor:
    """Executor giả: chỉ cần `request(path)` là chạy được `read_plan_index`."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.paths = []

    async def request(self, path, body=None):
        self.paths.append(path)
        if self.error is not None:
            raise self.error
        return self.payload


class FakeLog:
    def __init__(self):
        self.entries = []

    def write(self, event, **fields):
        self.entries.append((event, fields))


class TokenAndSimilarityTest(unittest.TestCase):
    def test_tokens_drop_single_characters_and_keeps_order(self):
        self.assertEqual(slug_tokens('research-patient-record-lookup'),
                         ('research', 'patient', 'record', 'lookup'))
        self.assertEqual(slug_tokens('a-b-plan-c'), ('plan',))

    def test_live_case_scores_point_eight(self):
        self.assertEqual(jaccard(CLINICAL, RESEARCH), 4 / 5)

    def test_boundaries_are_pinned(self):
        """Ranh giới 0.49/0.5/0.74/0.75 ghim bằng **hành vi**, không phải bằng hằng số."""
        self.assertEqual(MERGE_THRESHOLD, 0.75)
        self.assertEqual(AMBIGUOUS_THRESHOLD, 0.5)
        for overlap, expected_action in ((49, 'new'), (50, 'ambiguous'), (74, 'ambiguous'),
                                         (75, 'merge'), (100, 'merge')):
            with self.subTest(overlap=overlap):
                index = index_of(group(self.slug_of(100), 1))
                decision = resolve_identity(self.slug_of(overlap), index=index)
                self.assertAlmostEqual(jaccard(self.slug_of(100), self.slug_of(overlap)),
                                       overlap / 100, places=4)
                self.assertEqual(decision.action, expected_action)

    @staticmethod
    def slug_of(count):
        """Slug có đúng `count` token 3 ký tự, dùng để dựng tỉ lệ Jaccard chẵn."""
        return '-'.join(f'w{index:02d}' for index in range(count))

    def test_live_case_scores_point_eight(self):
        self.assertEqual(jaccard(CLINICAL, RESEARCH), 4 / 5)

    def test_empty_sets_score_zero_not_one(self):
        self.assertEqual(jaccard('', ''), 0.0)
        self.assertEqual(jaccard('a', 'b'), 0.0)

    def test_split_identity_reads_the_directory(self):
        self.assertEqual(split_identity('subplans/login'), ('subplans', 'login'))
        self.assertEqual(split_identity('login'), ('', 'login'))
        self.assertEqual(split_identity('/a/b/'), ('a', 'b'))

    def test_relates_to_forms(self):
        self.assertEqual(parse_relates_to('none'), (None, None))
        self.assertEqual(parse_relates_to(''), (None, None))
        self.assertEqual(parse_relates_to(CLINICAL), (CLINICAL, None))
        self.assertEqual(parse_relates_to(f'{CLINICAL}@v3'), (CLINICAL, 3))
        self.assertEqual(parse_relates_to('subplans/login@v2'), ('subplans/login', 2))


class ResolveIdentityTest(unittest.TestCase):
    def test_merge_for_similarity_above_the_threshold(self):
        index = index_of(group(f'{CLINICAL}', 3))
        decision = resolve_identity(RESEARCH, index=index)
        self.assertEqual(decision.action, 'merge')
        self.assertEqual(decision.identity, CLINICAL)
        self.assertEqual(decision.slug, CLINICAL)          # slug chuẩn của nhóm cũ
        self.assertEqual(decision.declared_slug, RESEARCH)  # slug model xin → dòng Slug: của header
        self.assertEqual(decision.matched_by, 'similarity')
        self.assertAlmostEqual(decision.score, 0.8, places=4)

    def test_ambiguous_between_the_two_thresholds(self):
        index = index_of(group('alpha-beta-gamma', 1))
        decision = resolve_identity('alpha-beta-delta', index=index)
        self.assertEqual(decision.action, 'ambiguous')
        self.assertEqual(decision.matched_identity, 'alpha-beta-gamma')

    def test_new_below_the_ambiguous_threshold(self):
        index = index_of(group('alpha-beta-gamma', 1))
        decision = resolve_identity('alpha-beta-delta-epsilon-zeta', index=index)
        self.assertEqual(decision.action, 'new')
        self.assertEqual(decision.identity, 'alpha-beta-delta-epsilon-zeta')
        self.assertFalse(decision.forced_new)

    def test_the_same_slug_as_the_group_is_a_plain_revision(self):
        """Đường đi thường gặp nhất: model lặp lại đúng slug cũ → cùng nhóm, không có dòng `Slug:`."""
        index = index_of(group(CLINICAL, 1, 2))
        decision = resolve_identity(CLINICAL, index=index)
        self.assertEqual(decision.action, 'merge')
        self.assertEqual(decision.identity, CLINICAL)
        self.assertIsNone(decision.declared_slug)
        self.assertEqual(decision.score, 1.0)

    def test_declared_identity_wins_over_similarity(self):
        index = index_of(group(CLINICAL, 3))
        decision = resolve_identity(RESEARCH, index=index, declared_identity='release-checklist')
        self.assertEqual(decision.action, 'declared')
        self.assertEqual(decision.identity, 'release-checklist')
        self.assertEqual(decision.matched_by, 'declared')

    def test_relates_to_version_suffix_is_a_declaration(self):
        index = index_of(group(CLINICAL, 3))
        decision = resolve_identity(RESEARCH, index=index, relates_to=f'{CLINICAL}@v3')
        self.assertEqual((decision.action, decision.identity), ('declared', CLINICAL))

    def test_relates_to_none_keeps_a_new_identity_and_marks_it_forced(self):
        index = index_of(group(CLINICAL, 3))
        decision = resolve_identity(RESEARCH, index=index, relates_to='none')
        self.assertEqual(decision.action, 'new')
        self.assertTrue(decision.forced_new)

    def test_relates_to_none_below_the_threshold_is_a_plain_new_identity(self):
        index = index_of(group(CLINICAL, 3))
        decision = resolve_identity('release-checklist', index=index, relates_to='none')
        self.assertEqual(decision.action, 'new')
        self.assertFalse(decision.forced_new)

    def test_similarity_only_compares_groups_in_the_same_directory(self):
        # Slug KHÁC nhưng giống token thì vẫn chỉ so trong cùng thư mục (luật §3.2 không đổi);
        # j = 3/4 = 0.75 nên bản trong thư mục `designs` được gộp, bản ở gốc phòng là nhóm mới.
        index = index_of(group('designs/login-page-flow', 1))
        decision = resolve_identity('login-page-flow-final', index=index)
        self.assertEqual(decision.action, 'new')
        self.assertEqual(decision.identity, 'login-page-flow-final')
        nested = resolve_identity('login-page-flow-final', index=index, directory='designs')
        self.assertEqual(nested.action, 'merge')
        self.assertEqual(nested.identity, 'designs/login-page-flow')

    def test_same_slug_group_adopts_its_folder_so_v2_lands_next_to_v1(self):
        """Chủ nhà 2026-10-04: không chỉ định chỗ ghi ⇒ tìm thư mục plan mà ghi vào.

        Cùng slug nghĩa là cùng một việc, nên bản mới phải nối tiếp trong chính thư mục của bản cũ
        (`.plans/tao-ui/v1-x.md` → `.plans/tao-ui/v2-x.md`) thay vì rơi về gốc phòng.
        """
        index = index_of(group('tao-ui/login-page', 1))
        decision = resolve_identity('login-page', index=index)
        self.assertEqual(decision.action, 'merge')
        self.assertEqual(decision.identity, 'tao-ui/login-page')
        self.assertEqual(decision.directory, 'tao-ui')

    def test_explicit_new_topic_keeps_the_room_root_and_two_folders_stay_ambiguous(self):
        one = index_of(group('tao-ui/login-page', 1))
        declared = resolve_identity('login-page', index=one, relates_to='none')
        self.assertEqual(declared.identity, 'login-page')
        self.assertEqual(declared.directory, '')
        # Hai thư mục cùng slug: harness không đoán bừa, bản mới về gốc phòng.
        two = index_of(group('tao-ui/login-page', 1), group('admin-ui/login-page', 1))
        ambiguous = resolve_identity('login-page', index=two)
        self.assertEqual(ambiguous.directory, '')
        self.assertEqual(ambiguous.identity, 'login-page')

    def test_declared_destination_is_clamped_into_the_plan_room(self):
        """`.plans/tao-ui`, `plans/tao-ui` và `tao-ui` là MỘT chỗ; `..` không ra ngoài được."""
        index = index_of()
        for declared in ('.plans/tao-ui/login-page', 'plans/tao-ui/login-page', 'tao-ui/login-page',
                         '/.plans/plans/tao-ui/login-page', '../tao-ui/login-page'):
            with self.subTest(declared=declared):
                decision = resolve_identity('login-page', index=index, declared_identity=declared)
                self.assertEqual(decision.identity, 'tao-ui/login-page')
                self.assertEqual(decision.directory, 'tao-ui')

    def test_directory_with_a_bad_segment_is_refused(self):
        for bad in ('Tao UI', 'tao_ui', 'tao.ui', 'tao--ui'):
            with self.subTest(bad=bad):
                with self.assertRaises(PlanRegistrationError) as caught:
                    resolve_identity('pilot', index=index_of(), directory=bad)
                self.assertEqual(caught.exception.code, 'directory-invalid')
                self.assertTrue(str(caught.exception).startswith('PLAN_EVAL_REJECTED: (directory-invalid)'))

    def test_plan_outside_room_flags_only_plan_files_outside_the_room(self):
        for inside in ('.plans/v1-x.md', '.plans/tao-ui/v2-x.md', '.plans/work/run-1/v3-a-3f9c2b.md'):
            with self.subTest(inside=inside):
                self.assertEqual(plan_outside_room(inside), '')
        for outside in ('v1-x.md', 'plans/v1-x.md', 'plans/sub/v1-x.md', 'docs/v1-x.md',
                        '.plans-backups/2026/v1-x.md', 'src/v1-schema.md'):
            with self.subTest(outside=outside):
                self.assertEqual(plan_outside_room(outside), 'PLAN_OUTSIDE_ROOM')
        for other in ('notes.md', '.plans/notes.md', 'src/schema-v1.md', 'src/plan.md', ''):
            with self.subTest(other=other):
                self.assertEqual(plan_outside_room(other), '')

    def test_invalid_declared_identity_is_rejected(self):
        index = index_of(group(CLINICAL, 3))
        for bad in ('Login Page', 'login_page', 'login--page', 'login.page'):
            with self.subTest(bad=bad):
                with self.assertRaises(PlanRegistrationError) as caught:
                    resolve_identity('pilot', index=index, declared_identity=bad)
                self.assertEqual(caught.exception.code, 'identity-invalid')
                self.assertTrue(str(caught.exception).startswith('PLAN_EVAL_REJECTED: (identity-invalid)'))

    def test_broken_index_means_degraded_never_a_guess(self):
        decision = resolve_identity(RESEARCH, index=None)
        self.assertEqual(decision.action, 'degraded')
        self.assertEqual(decision.identity, '')

    def test_decision_payload_names_the_rule_that_fired(self):
        index = index_of(group(CLINICAL, 3))
        payload = resolve_identity(RESEARCH, index=index).to_payload()
        self.assertEqual(payload['action'], 'merge')
        self.assertEqual(payload['matchedBy'], 'similarity')
        self.assertEqual(payload['score'], 0.8)
        self.assertFalse(payload['forcedNew'])


class NextVersionTest(unittest.TestCase):
    def test_first_version_of_a_new_identity_has_no_parent(self):
        plan = next_version_and_parent(())
        self.assertEqual((plan.version, plan.parent), (1, None))

    def test_revision_is_next_number_with_the_previous_as_parent(self):
        plan = next_version_and_parent([1, 2, 3])
        self.assertEqual((plan.version, plan.parent), (4, 3))

    def test_r1_rejects_parent_none_when_the_group_already_has_versions(self):
        with self.assertRaises(PlanRegistrationError) as caught:
            next_version_and_parent([1, 2, 3], declared_parent=None, identity=CLINICAL)
        self.assertEqual(caught.exception.code, 'revision-not-traceable')
        self.assertIn('Parent: v3', str(caught.exception))

    def test_parent_none_is_fine_for_the_first_version(self):
        plan = next_version_and_parent((), declared_parent=None)
        self.assertEqual((plan.version, plan.parent), (1, None))

    def test_declared_version_out_of_step_is_a_header_mismatch(self):
        with self.assertRaises(PlanRegistrationError) as caught:
            next_version_and_parent([1, 2, 3], declared_version=3, identity=CLINICAL)
        self.assertEqual(caught.exception.code, 'header-mismatch')
        self.assertIn('v4', str(caught.exception))
        # Câu từ chối đọc được: bản cũ ghép `v` hai lần nên in ra "khai vv3" (đo sống 2026-09-22).
        self.assertIn('khai v3', str(caught.exception))
        self.assertNotIn('vv3', str(caught.exception))

    def test_absent_declaration_is_not_none(self):
        """`UNSET` (không có khối) khác `None` (khai `Parent: none`) — ca thứ hai mới bị từ chối."""
        plan = next_version_and_parent([1, 2], declared_version=plan_registry.UNSET,
                                      declared_parent=plan_registry.UNSET)
        self.assertEqual((plan.version, plan.parent), (3, 2))


class GroupStateTest(unittest.TestCase):
    def test_no_index_and_no_ledger_is_unknown_not_draft(self):
        state = group_state((), index_available=False)
        self.assertEqual(state.state, 'unknown')
        self.assertFalse(state.index_available)

    def test_identity_absent_from_index_is_none(self):
        self.assertEqual(group_state(()).state, 'none')

    def test_newest_version_without_a_row_is_draft(self):
        self.assertEqual(group_state([1, 2]).state, 'draft')

    def test_submitted_requires_a_live_approval_request_for_that_version(self):
        self.assertEqual(group_state([1, 2], submitted=[2]).state, 'submitted')
        self.assertEqual(group_state([1, 2], submitted=[1]).state, 'draft')

    def test_approving_v1_never_makes_v2_approved(self):
        reviews = [{'version': 1, 'decision': 'approved', 'note': '', 'content_size': 1000,
                    'content_modified_at': '2026-09-20T13:56:00Z'}]
        self.assertEqual(group_state([1, 2], reviews=reviews).state, 'draft')
        self.assertEqual(group_state([1, 2], reviews=reviews).state_version, 2)

    def test_newest_decision_wins_and_comes_back_as_the_review_row(self):
        reviews = [{'version': 1, 'decision': 'approved'},
                   {'version': 2, 'decision': 'changes_requested', 'note': 'nêu rõ mục 3'}]
        state = group_state([1, 2], reviews=reviews)
        self.assertEqual(state.state, 'changes_requested')
        self.assertEqual(state.state_version, 2)
        self.assertEqual(state.review['note'], 'nêu rõ mục 3')
        self.assertTrue(state.pending)

    def test_pending_holds_for_every_state_that_has_no_consent(self):
        for state_name in ('draft', 'submitted', 'changes_requested'):
            with self.subTest(state=state_name):
                self.assertIn(state_name, plan_registry.PENDING_STATES)
        self.assertFalse(group_state([1], reviews=[{'version': 1, 'decision': 'approved'}]).pending)

    def test_review_stale_when_the_box_reports_other_numbers(self):
        entry = group('pilot', 1, size=4514, modified='2026-09-20T13:56:00Z').versions[0]
        same = {'version': 1, 'decision': 'approved', 'content_size': 4514,
                'content_modified_at': '2026-09-20T13:56:00Z'}
        changed = dict(same, content_size=4600)
        touched = dict(same, content_modified_at='2026-09-20T14:02:00Z')
        self.assertFalse(review_stale(same, entry))
        self.assertTrue(review_stale(changed, entry))
        self.assertTrue(review_stale(touched, entry))
        self.assertEqual(group_state([entry], reviews=[changed]).review_stale, True)
        self.assertFalse(group_state([entry], reviews=[same]).review_stale)

    def test_unmeasurable_stamp_is_not_claimed_stale(self):
        entry = group('pilot', 1, size=4514).versions[0]
        self.assertFalse(review_stale({'version': 1, 'decision': 'approved'}, entry))

    def test_payload_is_camel_case_and_keeps_the_five_contract_keys(self):
        state = group_state([1], reviews=[{'identity': 'pilot', 'version': 1, 'decision': 'approved',
                                           'note': 'ok', 'source': 'plan-tab', 'session_id': 's',
                                           'decided_at': 1.0, 'content_size': 1000,
                                           'content_modified_at': '2026-09-20T13:56:00Z'}])
        payload = state.to_payload()
        self.assertEqual(sorted(payload), ['indexAvailable', 'review', 'reviewStale', 'state', 'stateVersion'])
        self.assertEqual(payload['review']['decidedAt'], 1.0)
        self.assertEqual(payload['review']['contentModifiedAt'], '2026-09-20T13:56:00Z')
        self.assertEqual(payload['state'], 'approved')

    def test_pending_submissions_reads_only_live_unanswered_approvals(self):
        pending = [
            {'kind': 'approval', 'planIdentity': CLINICAL, 'planVersion': 4, 'resolved': False},
            {'kind': 'approval', 'planIdentity': CLINICAL, 'planVersion': 5, 'resolved': True},
            {'kind': 'question', 'planIdentity': CLINICAL, 'planVersion': 6, 'resolved': False},
            {'kind': 'approval', 'planIdentity': 'other', 'planVersion': 7, 'resolved': False},
        ]
        self.assertEqual(pending_submissions(pending, CLINICAL), (4,))
        self.assertEqual(pending_submissions(pending, 'other'), (7,))
        self.assertEqual(pending_submissions(None, CLINICAL), ())


class PlanRegistrationTest(unittest.TestCase):
    def test_live_case_merges_v4_into_the_v3_group_with_parent_v3(self):
        """Ca sống: chỉ nhóm v3 tồn tại, model đề nghị `research-patient-record-lookup`.

        j = 0.8 → gộp vào `clinical-patient-record-lookup-research`, harness ghi `v4` với
        `Parent: v3`, slug model xin đi vào dòng `Slug:` của header (đúng §3.2).
        """
        index = index_of(group(CLINICAL, 3, size=4650))
        plan = plan_registration(RESEARCH, index=index)
        self.assertEqual((plan.identity, plan.slug, plan.version, plan.parent),
                         (CLINICAL, CLINICAL, 4, 3))
        self.assertEqual(plan.declared_slug, RESEARCH)
        self.assertEqual(plan.matched_by, 'similarity')
        self.assertFalse(plan.forced_new)

    def test_a_second_group_with_the_same_slug_keeps_its_own_numbers(self):
        """`v5-other.md` không đẩy số của slug khác: nhóm riêng thì đếm riêng (§1.a của plan)."""
        index = index_of(group(CLINICAL, 1, 2, 3, 4), group('other-topic', 5, 6))
        plan = plan_registration(CLINICAL, index=index)
        self.assertEqual((plan.version, plan.parent), (5, 4))

    def test_two_brand_new_topics_start_at_v1(self):
        index = index_of(group(CLINICAL, 1, 2, 3, 4))
        plan = plan_registration('release-checklist', index=index)
        self.assertEqual((plan.identity, plan.version, plan.parent), ('release-checklist', 1, None))

    def test_ambiguous_is_rejected_with_the_two_calls_that_fix_it(self):
        index = index_of(group('alpha-beta-gamma', 1))
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration('alpha-beta-delta', index=index)
        message = str(caught.exception)
        self.assertEqual(caught.exception.code, 'identity-ambiguous')
        self.assertIn('identity: "alpha-beta-gamma"', message)
        self.assertIn('relatesTo: "none"', message)
        self.assertNotIn('\n', message)

    def test_r2_after_approval_a_revision_keeps_the_chain(self):
        index = index_of(group(CLINICAL, 1, 2))
        reviews = {CLINICAL: [{'version': 2, 'decision': 'approved'}]}
        plan = plan_registration(CLINICAL, index=index, declared_identity=CLINICAL,
                                reviews_by_identity=reviews)
        self.assertEqual((plan.version, plan.parent, plan.state), (3, 2, 'approved'))

    def test_r2_after_approval_a_genuinely_different_topic_may_start_over(self):
        index = index_of(group(CLINICAL, 1, 2))
        reviews = {CLINICAL: [{'version': 2, 'decision': 'approved'}]}
        plan = plan_registration('release-checklist', index=index, reviews_by_identity=reviews)
        self.assertEqual((plan.identity, plan.version, plan.parent), ('release-checklist', 1, None))

    def test_r3_a_change_request_cannot_be_abandoned_for_a_similar_identity(self):
        index = index_of(group(CLINICAL, 1, 2))
        reviews = {CLINICAL: [{'version': 2, 'decision': 'changes_requested',
                               'note': 'nêu rõ cách kiểm tra HL7'}]}
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(RESEARCH, index=index, relates_to='none', reviews_by_identity=reviews)
        self.assertEqual(caught.exception.code, 'identity-pending-review')
        self.assertIn('nêu rõ cách kiểm tra HL7', str(caught.exception))

    def test_r3_does_not_block_a_revision_of_the_same_group(self):
        index = index_of(group(CLINICAL, 1, 2))
        reviews = {CLINICAL: [{'version': 2, 'decision': 'changes_requested', 'note': 'mục 3'}]}
        plan = plan_registration(CLINICAL, index=index, declared_identity=CLINICAL,
                                reviews_by_identity=reviews)
        self.assertEqual((plan.version, plan.parent, plan.state), (3, 2, 'changes_requested'))

    def test_r3_note_is_quoted_short(self):
        """Ghi chú người dùng chỉ được trích ≤ 120 ký tự (§4.3) — một dòng, không dán cả bài."""
        index = index_of(group(CLINICAL, 1))
        reviews = {CLINICAL: [{'version': 1, 'decision': 'changes_requested', 'note': 'x' * 400}]}
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(RESEARCH, index=index, relates_to='none', reviews_by_identity=reviews)
        message = str(caught.exception)
        self.assertIn('x' * plan_registry.MAX_NOTE_CHARS, message)
        self.assertNotIn('x' * (plan_registry.MAX_NOTE_CHARS + 1), message)
        self.assertNotIn('\n', message)

    def test_r1_parent_none_on_an_existing_group_is_rejected(self):
        index = index_of(group(CLINICAL, 1, 2))
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(CLINICAL, index=index, declared_identity=CLINICAL,
                              declared_parent=None)
        self.assertEqual(caught.exception.code, 'revision-not-traceable')

    def test_forced_new_is_reported_so_the_owner_can_see_it(self):
        index = index_of(group(CLINICAL, 3))
        plan = plan_registration(RESEARCH, index=index, relates_to='none')
        self.assertTrue(plan.forced_new)
        self.assertEqual(plan.identity, RESEARCH)
        self.assertEqual(plan.version, 1)
        self.assertTrue(plan.notes and IC_IDENTITY_FORCED_NEW_CODE in plan.notes[0])

    def test_degraded_index_returns_the_old_behaviour_plan(self):
        plan = plan_registration(RESEARCH, index=None)
        self.assertTrue(plan.degraded)
        self.assertEqual((plan.identity, plan.version, plan.parent), ('', 0, None))
        self.assertEqual(plan.state, 'unknown')

    def test_registration_payload_is_what_the_event_needs(self):
        index = index_of(group(CLINICAL, 3))
        payload = plan_registration(RESEARCH, index=index).to_payload()
        self.assertEqual(payload['identity'], CLINICAL)
        self.assertEqual(payload['version'], 4)
        self.assertEqual(payload['parent'], 3)
        self.assertEqual(payload['identityMatchedBy'], 'similarity')
        self.assertEqual(payload['identityScore'], 0.8)
        self.assertFalse(payload['identityForcedNew'])
        self.assertFalse(payload['degraded'])


class PlanIndexTest(unittest.TestCase):
    def test_parse_reads_the_live_payload_shape(self):
        payload = {
            'plans': [
                {'identity': CLINICAL, 'relativeDirectory': '', 'slug': CLINICAL, 'versions': [
                    {'version': 3, 'label': 'v3', 'relativePath': '.plans/v3-clinical.md',
                     'sizeBytes': 4650, 'modifiedAt': '2026-09-20T13:50:00Z', 'status': 'draft',
                     'headerStatus': 'ok', 'headerVersion': 3, 'headerIdentity': CLINICAL,
                     'declaredParent': None, 'declaredSlug': None}]},
                {'identity': 'subplans/header-demo', 'relativeDirectory': 'subplans',
                 'slug': 'header-demo', 'versions': [
                     {'version': 1, 'label': 'v1', 'relativePath': '.plans/subplans/v1-header-demo.md',
                      'sizeBytes': 100, 'modifiedAt': '2026-09-20T13:56:00Z', 'status': 'approved',
                      'headerStatus': 'ok', 'headerVersion': 1, 'headerIdentity': 'subplans/header-demo',
                      'declaredParent': None, 'declaredSlug': None}]},
            ],
            'ignoredCount': 2,
            'warnings': ['Đã bỏ qua «.plans/x.md».'],
        }
        index = parse_plan_index(payload)
        self.assertEqual(index.identities(), (CLINICAL, 'subplans/header-demo'))
        self.assertEqual(index.ignored_count, 2)
        self.assertEqual(len(index.warnings), 1)
        self.assertEqual(index.group('subplans/header-demo').directory, 'subplans')
        self.assertEqual(index.groups_in('subplans')[0].numbers, (1,))
        entry = index.group(CLINICAL).versions[0]
        self.assertEqual((entry.version, entry.size_bytes, entry.header_status), (3, 4650, 'ok'))

    def test_parse_is_defensive_about_junk_rows(self):
        index = parse_plan_index({'plans': [None, {}, {'identity': 'x', 'versions': [
            {'version': 0}, {'version': '2'}, {'version': 2, 'headerStatus': 7}]}]})
        self.assertEqual(index.identities(), ('x',))
        self.assertEqual(index.group('x').numbers, (2,))
        self.assertEqual(index.group('x').versions[0].header_status, 'legacy')

    def test_parse_accepts_a_non_dict_payload_as_empty(self):
        self.assertEqual(parse_plan_index(None).identities(), ())

    def test_payload_round_trips_the_fields_the_route_publishes(self):
        index = index_of(group(CLINICAL, 1, size=10, modified='2026-09-20T13:56:00Z'))
        again = parse_plan_index(index.to_payload())
        self.assertEqual(again.group(CLINICAL).numbers, (1,))
        self.assertEqual(again.group(CLINICAL).versions[0].size_bytes, 10)


class ReadPlanIndexTest(unittest.TestCase):
    def test_reads_the_secret_gated_route_and_parses_it(self):
        executor = FakeExecutor(payload={'plans': [], 'ignoredCount': 0, 'warnings': []})
        index = asyncio.run(read_plan_index(executor))
        self.assertEqual(executor.paths, [INDEX_PATH])
        self.assertEqual(index.identities(), ())

    def test_network_failure_degrades_and_logs_the_code(self):
        log = FakeLog()
        index = asyncio.run(read_plan_index(FakeExecutor(error=RuntimeError('box down')), log=log))
        self.assertIsNone(index)
        event, fields = log.entries[0]
        self.assertEqual(event, 'plan.index.unavailable')
        self.assertEqual(fields['code'], INDEX_UNAVAILABLE_CODE)
        self.assertEqual(fields['level'], 'warn')

    def test_a_payload_without_plans_is_degraded_not_empty(self):
        log = FakeLog()
        index = asyncio.run(read_plan_index(FakeExecutor(payload={'error': 'nope'}), log=log))
        self.assertIsNone(index)
        self.assertEqual(log.entries[0][1]['code'], INDEX_UNAVAILABLE_CODE)

    def test_a_broken_log_never_breaks_the_write(self):
        class ExplodingLog:
            def write(self, *args, **kwargs):
                raise RuntimeError('log is full')

        index = asyncio.run(read_plan_index(FakeExecutor(error=OSError('nope')), log=ExplodingLog()))
        self.assertIsNone(index)


class AmbiguityTicketTest(unittest.TestCase):
    """Vé mơ hồ (D-3 / C4): lần đầu từ chối, gửi lại NGUYÊN VĂN thì nhận — vé tiêu đúng một lần.

    Ca sống vòng 21: cùng một kế hoạch bị từ chối `identity-ambiguous` ở lượt 4 (j ≈ 0.6) rồi được
    nhận ở lượt 5, chỉ vì model tự đổi slug. Ở đây luật được ghim: lần ĐẦU vẫn từ chối, nhưng lời từ
    chối mang theo một vé, và vé chỉ có giá trị khi slug đó **chưa** có nhóm nào (`P:`).
    """

    def setUp(self):
        self.index = index_of(group(RESEARCH, 1))
        self.decision = resolve_identity(AMBIGUOUS_SLUG, index=self.index)
        self.assertEqual(self.decision.action, 'ambiguous')
        self.ticket = build_ambiguity_ticket(self.decision, slug=AMBIGUOUS_SLUG)

    def test_a_rejection_leaves_a_ticket_that_holds_no_plan_file(self):
        """Vé **không** được mang `relativePath`: nó không giữ kế hoạch nào (không tệp nào được ghi)."""
        self.assertEqual(self.ticket['slug'], AMBIGUOUS_SLUG)
        self.assertEqual(self.ticket['directory'], '')
        self.assertEqual(self.ticket['matchedIdentity'], RESEARCH)
        self.assertAlmostEqual(self.ticket['score'], 0.6, places=4)
        self.assertNotIn('relativePath', self.ticket)
        self.assertEqual([entry['identity'] for entry in self.ticket['candidates']], [RESEARCH])

    def test_the_ticket_is_honoured_by_the_very_next_send(self):
        decision = resolve_identity(AMBIGUOUS_SLUG, index=self.index, ambiguity_ticket=self.ticket)
        self.assertEqual(decision.action, 'new')
        self.assertEqual(decision.identity, AMBIGUOUS_SLUG)
        self.assertEqual(decision.matched_by, AMBIGUITY_MATCHED_BY)
        self.assertFalse(decision.forced_new)
        # Vẫn giữ bản chấm cũ để nhật ký nói được "đã từng mơ hồ".
        self.assertAlmostEqual(decision.score, 0.6, places=4)
        self.assertEqual(decision.matched_identity, RESEARCH)
        self.assertEqual(decision.candidates, ((RESEARCH, 0.6),))
        self.assertFalse(decision.rejected)

    def test_the_ticket_is_spent_once_because_the_slug_then_has_a_group(self):
        """Gửi lại lần hai: slug đã có `P:` (nhóm có mặt trong chỉ mục) ⇒ vé hết giá trị.

        Đây là chỗ chặn "vé thành cửa sau": lần gửi lại thứ ba gộp với chính nó (`j = 1.0`), không
        mở thêm một `v1-…` thứ hai.
        """
        after = index_of(group(RESEARCH, 1), group(AMBIGUOUS_SLUG, 1))
        self.assertFalse(ambiguity_ticket_usable(self.ticket, slug=AMBIGUOUS_SLUG, index=after))
        decision = resolve_identity(AMBIGUOUS_SLUG, index=after, ambiguity_ticket=self.ticket)
        self.assertEqual((decision.action, decision.identity), ('merge', AMBIGUOUS_SLUG))
        self.assertEqual(decision.matched_by, 'similarity')
        plan = plan_registration(AMBIGUOUS_SLUG, index=after, ambiguity_ticket=self.ticket)
        self.assertEqual((plan.identity, plan.version, plan.parent), (AMBIGUOUS_SLUG, 2, 1))
        self.assertIsNone(plan.ambiguity)

    def test_a_ticket_for_another_slug_or_directory_is_not_honoured(self):
        nested = 'subplans/' + RESEARCH
        both = index_of(group(RESEARCH, 1), group(nested, 1))
        for ticket, directory in ((dict(self.ticket, slug=RESEARCH), ''),
                                  (dict(self.ticket, slug=''), ''),
                                  (self.ticket, 'subplans')):
            with self.subTest(ticket=ticket['slug'], directory=directory):
                decision = resolve_identity(AMBIGUOUS_SLUG, index=both, ambiguity_ticket=ticket,
                                            directory=directory)
                self.assertEqual((decision.action, decision.matched_by), ('ambiguous', 'similarity'))
        self.assertFalse(ambiguity_ticket_usable(self.ticket, slug=AMBIGUOUS_SLUG,
                                                directory='subplans', index=both))

    def test_a_broken_or_missing_ticket_is_never_honoured(self):
        self.assertFalse(ambiguity_ticket_usable(None, slug=AMBIGUOUS_SLUG, index=self.index))
        self.assertFalse(ambiguity_ticket_usable('vé', slug=AMBIGUOUS_SLUG, index=self.index))
        self.assertEqual(resolve_identity(AMBIGUOUS_SLUG, index=self.index).action, 'ambiguous')
        # Không đọc được chỉ mục ⇒ không kiểm được "đã có P: chưa" ⇒ không dùng vé.
        self.assertFalse(ambiguity_ticket_usable(self.ticket, slug=AMBIGUOUS_SLUG, index=None))

    def test_the_ticket_never_touches_the_merge_band(self):
        """`j ≥ 0.75` vẫn gộp như cũ, kể cả khi có vé trên tay (§3.2 không đổi)."""
        index = index_of(group(RESEARCH, 1))
        ticket = build_ambiguity_ticket(
            resolve_identity(AMBIGUOUS_SLUG, index=index), slug=MERGE_BAND_SLUG)
        decision = resolve_identity(MERGE_BAND_SLUG, index=index, ambiguity_ticket=ticket)
        self.assertEqual((decision.action, decision.identity), ('merge', RESEARCH))
        self.assertEqual(decision.matched_by, 'similarity')
        plan = plan_registration(MERGE_BAND_SLUG, index=index, ambiguity_ticket=ticket)
        self.assertEqual((plan.version, plan.parent, plan.matched_by), (2, 1, 'similarity'))

    def test_the_ticket_does_not_sneak_past_a_pending_change_request(self):
        """R3 vẫn thắng: nhóm gần nhất đang chờ sửa thì không được mở nhóm mới cho cùng chủ đề."""
        reviews = {RESEARCH: [{'version': 1, 'decision': 'changes_requested', 'note': 'nêu cách kiểm'}]}
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(AMBIGUOUS_SLUG, index=self.index, ambiguity_ticket=self.ticket,
                              reviews_by_identity=reviews)
        self.assertEqual(caught.exception.code, 'identity-pending-review')
        self.assertIn('nêu cách kiểm', str(caught.exception))

    def test_the_registration_carries_the_marker_for_the_plan_row(self):
        plan = plan_registration(AMBIGUOUS_SLUG, index=self.index, ambiguity_ticket=self.ticket)
        self.assertEqual((plan.identity, plan.version, plan.parent), (AMBIGUOUS_SLUG, 1, None))
        self.assertEqual(plan.matched_by, AMBIGUITY_MATCHED_BY)
        self.assertEqual(plan.ambiguity, {'score': 0.6, 'nearestIdentity': RESEARCH})
        payload = plan.to_payload()
        self.assertEqual(payload['identityMatchedBy'], AMBIGUITY_MATCHED_BY)
        self.assertEqual(payload['identityAmbiguity'], {'score': 0.6, 'nearestIdentity': RESEARCH})
        self.assertIsNone(plan_registration(RESEARCH, index=self.index).ambiguity)

    def test_without_a_ticket_the_second_send_is_still_refused(self):
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(AMBIGUOUS_SLUG, index=self.index)
        self.assertEqual(caught.exception.code, 'identity-ambiguous')

    def test_ticket_from_rows_reads_the_fact_row_shape_of_the_journal(self):
        """`journal_tail(sid, kinds=['fact'])` → `payload.record.data[AMBIGUITY_TICKET_KEY]`."""
        rows = [
            {'kind': 'task', 'payload': {'record': {'kind': 'task', 'data': {}}}},
            {'kind': 'fact', 'payload': {'record': {'kind': 'fact', 'data': {
                AMBIGUITY_TICKET_KEY: dict(self.ticket, slug='another-slug')}}}},
            {'kind': 'fact', 'payload': {'record': {'kind': 'fact', 'data': {
                AMBIGUITY_TICKET_KEY: self.ticket}}}},
            None, 'không phải hàng', {'payload': 'không phải JSON'},
            {'payload': {'record': {'data': None}}},
        ]
        self.assertEqual(ticket_from_rows(rows, slug=AMBIGUOUS_SLUG), self.ticket)
        # Vé mới nhất thắng: hàng cuối cùng khớp `(slug, directory)` là vé được trả.
        newer = dict(self.ticket, score=0.7)
        rows.append({'kind': 'fact', 'payload': {'record': {'kind': 'fact', 'data': {
            AMBIGUITY_TICKET_KEY: newer}}}})
        self.assertEqual(ticket_from_rows(rows, slug=AMBIGUOUS_SLUG), newer)
        self.assertIsNone(ticket_from_rows(rows, slug='chưa-từng'))
        self.assertIsNone(ticket_from_rows(rows, slug=AMBIGUOUS_SLUG, directory='subplans'))
        self.assertIsNone(ticket_from_rows(None, slug=AMBIGUOUS_SLUG))

    def test_three_sends_the_registry_half_of_the_acceptance_narrative(self):
        """Nghiệm thu C4 (a)(b)(c)(d) ở tầng registry — chỗ mà `runtime` nối vào (xem handoff).

        `runtime.plan_registration_for` là thứ đọc/ghi vé (hàng `F:`) và ghim hàng `P:`; ở đây chỉ
        chứng minh luật thuần: từ chối lần 1 kèm vé, nhận lần 2 với dấu `identityAmbiguity`, và lần 3
        **không** sinh `v1-…` thứ hai.
        """
        index = index_of(group(RESEARCH, 1))
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(AMBIGUOUS_SLUG, index=index)
        self.assertEqual(caught.exception.code, 'identity-ambiguous')
        ticket = build_ambiguity_ticket(resolve_identity(AMBIGUOUS_SLUG, index=index),
                                        slug=AMBIGUOUS_SLUG)
        second = plan_registration(AMBIGUOUS_SLUG, index=index, ambiguity_ticket=ticket)
        self.assertEqual((second.identity, second.version, second.parent), (AMBIGUOUS_SLUG, 1, None))
        self.assertEqual(second.ambiguity, {'score': 0.6, 'nearestIdentity': RESEARCH})
        # Sandbox ghi `v1-<slug>.md` ⇒ lần đọc chỉ mục kế tiếp thấy nhóm này.
        after = index_of(group(RESEARCH, 1), group(AMBIGUOUS_SLUG, 1))
        third = plan_registration(AMBIGUOUS_SLUG, index=after, ambiguity_ticket=ticket)
        self.assertEqual((third.identity, third.version, third.parent), (AMBIGUOUS_SLUG, 2, 1))
        self.assertEqual(third.matched_by, 'similarity')
        self.assertIsNone(third.ambiguity)
        # (d) biên cũ không đổi: 0.75 vẫn gộp, 0.49 vẫn nhóm mới (vé không đụng vào hai đầu này).
        wide = index_of(group(TokenAndSimilarityTest.slug_of(100), 1))
        self.assertEqual(resolve_identity(TokenAndSimilarityTest.slug_of(75), index=wide).action, 'merge')
        self.assertEqual(resolve_identity(TokenAndSimilarityTest.slug_of(49), index=wide).action, 'new')

    def test_the_rejection_carries_the_ready_ticket_for_the_caller(self):
        """Chỉ ở chỗ raise mới còn biết slug ĐỀ NGHỊ (trường `slug` của lỗi là slug của nhóm).

        `runtime.write_plan` chỉ việc ghi `exc.fields['ambiguity_ticket']` xuống hàng `F:` rồi gửi lại;
        hình dạng vé vẫn do module này sở hữu, không có bản sao thứ hai ở chỗ gọi.
        """
        with self.assertRaises(PlanRegistrationError) as caught:
            plan_registration(AMBIGUOUS_SLUG, index=index_of(group(RESEARCH, 1)))
        ticket = caught.exception.fields.get('ambiguity_ticket')
        self.assertEqual(ticket['slug'], AMBIGUOUS_SLUG)
        self.assertEqual(ticket['directory'], '')
        self.assertEqual(caught.exception.fields['slug'], RESEARCH)  # slug của nhóm, cho câu chữa
        self.assertEqual(AMBIGUITY_TICKET_KEY, 'identityAmbiguityTicket')

    def test_the_remedy_says_the_resend_is_allowed(self):
        message = rejection_message('identity-ambiguous', identity=RESEARCH, other=RESEARCH,
                                    score=0.6, slug=AMBIGUOUS_SLUG)
        self.assertIn('gửi lại NGUYÊN VĂN', message)
        self.assertNotIn('\n', message)


class RejectionVocabularyTest(unittest.TestCase):
    def test_message_has_prefix_code_and_remedy_on_one_line(self):
        message = rejection_message('identity-ambiguous', identity=CLINICAL, other=RESEARCH,
                                    score=0.6, slug=RESEARCH)
        self.assertTrue(message.startswith('PLAN_EVAL_REJECTED: (identity-ambiguous) '))
        self.assertNotIn('\n', message)
        self.assertIn('60%', message)

    def test_every_message_code_has_a_remedy(self):
        for code in ('identity-ambiguous', 'revision-not-traceable', 'identity-pending-review',
                     'header-mismatch', 'identity-invalid'):
            with self.subTest(code=code):
                self.assertIn(code, plan_registry.REMEDIES)

    def test_unknown_code_still_returns_a_single_line(self):
        message = rejection_message('something-new', anything=1)
        self.assertTrue(message.startswith('PLAN_EVAL_REJECTED: (something-new) '))


IC_IDENTITY_FORCED_NEW_CODE = IDENTITY_FORCED_NEW_CODE


if __name__ == '__main__':
    unittest.main()
