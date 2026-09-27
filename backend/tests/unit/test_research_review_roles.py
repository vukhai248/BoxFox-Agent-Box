"""P3 (§5.9/§5.11): chế độ soát, mẫu trích xuất, danh mục phát hiện và phân xử mâu thuẫn.

Một nguồn sự thật cho "có phải phản biện không": `research_review.review_modes`. Bài kiểm ghim
đúng ba điều dễ lệch nhất:

* phản biện mặc định từ mức 2 khi công tắc bật, và khi công tắc `off` thì quay lại ĐÚNG
  `limits.RESEARCH_TIER_CRITIQUE` (chỉ mức 3) — không có đường thứ hai;
* `missing-direction` mức cao chưa xử lý ⇒ nhãn `limits.RESEARCH_COVERAGE_LABEL`;
* hai bên soát ĐỘC LẬP mâu thuẫn ⇒ nhận định bị tranh chấp, trần lấy mức THẤP NHẤT và hồ sơ phải
  nói ra — không lấy theo đa số.
"""
import pathlib
import pytest

from agentbox.agent_core import limits, research_evidence, research_review, research_runtime, roles
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

OFF = {limits.RESEARCH_CRITIQUE_TIER2_ENV: 'off'}


class _FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        pass


class _FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


def _harness(tmp_path):
    store = SessionStore(pathlib.Path(tmp_path) / 'sessions.db')
    runtime = HarnessRuntime(store, _FixtureExecutor(), _FixtureModel())
    return store, runtime


def _research_branch(store, runtime, research_id, scope):
    """Một phiên con `research` mở sẵn một run với thẻ phạm vi cho trước."""
    sid = runtime.create({'skills': [], 'research': {'researchId': research_id}},
                         role='research')['id']
    store.research_job_save(research_id, sid, {'scope': scope, 'questions': []},
                            status='researching')
    return store.get(sid)


def _row(row_id, host, published_at='2020-06-01', survey=True):
    return {'rowId': row_id, 'claim': f'nguồn {row_id}', 'url': f'https://{host}/bai',
            'host': host, 'excerpt': f'đoạn trích {row_id}', 'publishedAt': published_at,
            'accessLevel': 'fulltext-read', 'payload': {'survey': survey}}



# --- chế độ soát -------------------------------------------------------------

def test_critique_is_default_from_tier_two_while_the_switch_is_on():
    assert research_review.review_modes(2, {}) == ['critique']
    assert research_review.review_modes(1, {}) == []
    assert 'critique' in research_review.review_modes(3, {})


def test_with_the_switch_off_the_old_tier_table_is_the_only_path():
    assert research_review.review_modes(1, {}, env=OFF) == []
    assert research_review.review_modes(2, {}, env=OFF) == []
    assert 'critique' in research_review.review_modes(3, {}, env=OFF)
    # Mức 3 vẫn có phản biện: bảng cũ là nguồn, không phải một bản sao khác.
    assert limits.RESEARCH_TIER_CRITIQUE[3] is True


def test_evidence_follows_the_existing_question_rule_and_coverage_follows_the_job_kind():
    many = {'questions': [{'importance': 'high'}, {'importance': 'high'}, {'importance': 'low'}]}
    assert research_review.review_modes(2, many, env=OFF) == ['evidence']
    assert research_review.review_modes(2, {'questions': [{'importance': 'low'}]},
                                        env=OFF) == []
    landscape = {'scope': {'jobKinds': ['landscape']}}
    assert research_review.review_modes(1, landscape, env=OFF) == ['coverage']
    assert research_review.review_modes(2, {'scope': {'jobKinds': ['gap']}}) \
        == ['critique', 'coverage']
    # Mức 3 LUÔN có bằng chứng (luật hiện có của `_choose_review_modes`) + phản biện + bao phủ.
    assert research_review.review_modes(3, {}, env=OFF) == ['evidence', 'critique', 'coverage']


def test_the_mode_list_keeps_the_public_order_and_never_repeats():
    state = {'questions': [{'importance': 'high'}, {'importance': 'high'}, {'importance': 'high'}],
             'scope': {'jobKinds': ['landscape']}}
    modes = research_review.review_modes(3, state)
    assert modes == ['evidence', 'critique', 'coverage']
    assert modes == [mode for mode in research_review.REVIEW_MODES if mode in modes]
    payload = research_review.review_modes_payload(2, {})
    assert payload['modes'] == ['critique'] and payload['critiqueRule'] == 'tier>=2'


# --- mẫu trích xuất ----------------------------------------------------------

def test_every_pillar_source_kind_has_an_extraction_template_within_the_cap():
    assert set(research_review.EXTRACTION_FIELDS) == {
        'paper', 'blog', 'docs', 'repo', 'legal', 'dataset', 'news', 'vendor', 'forum', 'other'}
    for kind in research_review.EXTRACTION_FIELDS:
        fields = research_review.extraction_fields(kind)
        assert fields and len(fields) <= limits.RESEARCH_EXTRACTION_MAX_FIELDS, kind
        assert all(set(field) >= {'key', 'label', 'required', 'where'} for field in fields), kind
        assert all(field['where'] in ('head', 'body', 'link') for field in fields), kind


def test_an_unknown_source_kind_falls_back_and_an_alias_maps_to_its_real_template():
    unknown = research_review.extraction_fields('telegram-channel')
    assert unknown == research_review.extraction_fields('other')
    assert [field['key'] for field in research_review.extraction_fields('preprint')] \
        == [field['key'] for field in research_review.extraction_fields('paper')]
    assert 'docNumber' in [field['key'] for field in research_review.extraction_fields('standard')]


# --- danh mục phát hiện ------------------------------------------------------

def test_issue_kinds_are_normalised_and_unknown_ones_are_dropped_not_broken():
    issues = research_review.normalize_issues([
        {'severity': 'HIGH', 'text': 'thiếu hướng X', 'fix': 'thêm X', 'kind': 'missing_direction'},
        {'severity': 'weird', 'text': 'chuyện khác', 'kind': 'not-a-kind'},
        'not a dict',
    ])
    assert issues[0] == {'severity': 'high', 'text': 'thiếu hướng X', 'fix': 'thêm X',
                         'kind': 'missing-direction'}
    assert 'kind' not in issues[1] and issues[1]['severity'] == 'medium'
    assert len(issues) == 2
    assert research_review.normalize_issues([], max_items=0) == []


def test_the_cap_and_the_text_limit_of_the_old_clamp_still_hold():
    long_text = 'x' * (limits.RESEARCH_VERIFY_ISSUE_CHARS + 50)
    rows = research_review.normalize_issues(
        [{'severity': 'low', 'text': long_text} for _ in range(limits.RESEARCH_VERIFY_MAX_ISSUES + 5)])
    assert len(rows) == limits.RESEARCH_VERIFY_MAX_ISSUES
    assert len(rows[0]['text']) == limits.RESEARCH_VERIFY_ISSUE_CHARS


def test_an_unhandled_high_missing_direction_puts_the_coverage_label_on_the_dossier():
    open_finding = [{'severity': 'high', 'kind': 'missing-direction', 'text': 'thiếu hướng X'}]
    assert research_review.has_unhandled_missing_direction(open_finding) is True
    assert research_review.coverage_label(open_finding) == limits.RESEARCH_COVERAGE_LABEL
    handled = [dict(open_finding[0], handled=True)]
    assert research_review.has_unhandled_missing_direction(handled) is False
    assert research_review.coverage_label(handled) == ''
    low = [{'severity': 'low', 'kind': 'missing-direction', 'text': 'x'}]
    assert research_review.coverage_label(low) == '', 'chỉ mức CAO mới gắn nhãn'
    assert research_review.coverage_label(verdict='revise') == limits.RESEARCH_COVERAGE_LABEL


# --- phân xử mâu thuẫn -------------------------------------------------------

def test_two_independent_reviewers_in_disagreement_make_the_claim_contested_at_the_lowest_cap():
    resolved = research_review.resolve_disagreement(
        [{'reviewer': 'a', 'verdict': 'ok', 'cap': 'high', 'mode': 'evidence'},
         {'reviewer': 'b', 'verdict': 'revise', 'cap': 'low', 'mode': 'critique'}],
        claim_id='c1')
    assert resolved['contested'] is True and resolved['mustReport'] is True
    assert resolved['cap'] == 'low', 'trần là mức THẤP NHẤT, không lấy theo đa số'
    assert resolved['verdict'] == 'revise'
    assert 'c1' in resolved['reportLine']
    assert resolved['distinctReviewers'] == ['a', 'b']
    assert resolved['note']


def test_agreement_and_a_single_reviewer_are_not_a_disagreement():
    agree = research_review.resolve_disagreement(
        [{'reviewer': 'a', 'verdict': 'ok', 'cap': 'high'},
         {'reviewer': 'b', 'verdict': 'ok', 'cap': 'high'}])
    assert agree['contested'] is False and agree['reportLine'] == ''
    assert agree['verdict'] == 'ok' and agree['cap'] == 'high'
    alone = research_review.resolve_disagreement([{'reviewer': 'a', 'verdict': 'revise'}])
    assert alone['contested'] is False
    # Hai phán quyết trái nhau nhưng CÙNG một người soát là không đủ: phải có hai bên độc lập.
    same = research_review.resolve_disagreement(
        [{'reviewer': 'a', 'verdict': 'ok'}, {'reviewer': 'a', 'verdict': 'revise'}])
    assert same['contested'] is False


def test_a_relation_level_conflict_is_enough_and_the_given_caps_win():
    resolved = research_review.resolve_disagreement(
        [{'reviewer': 'src-1', 'relation': 'supports'}, {'reviewer': 'src-2', 'relation': 'contradicts'}],
        caps=['high', 'medium'])
    assert resolved['contested'] is True and resolved['cap'] == 'medium'
    assert resolved['claimId'] == ''
    assert research_review.contested_claims([resolved, {'claimId': 'c9', 'contested': False}]) == [], \
        'nhận định tranh chấp không có mã thì không bịa ra một mã'
    named = research_review.resolve_disagreement(
        [{'reviewer': 'a', 'verdict': 'ok'}, {'reviewer': 'b', 'verdict': 'revise'}], claim_id='c7')
    assert research_review.contested_claims([named]) == ['c7']


# --- quyền công cụ -----------------------------------------------------------

def test_the_branch_report_tool_belongs_to_the_research_branch_only():
    assert 'research_branch_report' in roles.ROLES['research'].tools
    assert 'research_branch_report' not in roles.ROLES['research-review'].tools
    assert 'research_branch_report' not in roles.ORCHESTRATOR_TOOLS
    for role in ('explore', 'build', 'review', 'plan-review'):
        assert 'research_branch_report' not in roles.allowed_tools(role), role
    # Orchestrator không giữ nó, nên `allowed_tools` phải tự thêm lại cho nhánh — cùng khuôn
    # với `claim_assess` của vai phản biện.
    assert 'research_branch_report' in roles.allowed_tools('research',
                                                           parent=roles.ORCHESTRATOR_TOOLS)
    assert 'claim_assess' in roles.allowed_tools('research-review',
                                                 parent=roles.ORCHESTRATOR_TOOLS)


def test_two_anonymous_records_are_never_a_contested_disagreement():
    """Danh tính KHÔNG được bịa: hai hồ sơ không tên không tính là hai bên soát độc lập."""
    anonymous = research_review.resolve_disagreement(
        [{'verdict': 'ok', 'cap': 'high'}, {'verdict': 'revise', 'cap': 'low'}], claim_id='c1')
    assert anonymous['contested'] is False and anonymous['mustReport'] is False
    assert anonymous['distinctReviewers'] == []
    assert anonymous['reportLine'] == ''
    # Một bên có tên + một bên vô danh cũng KHÔNG đủ hai bên độc lập.
    mixed = research_review.resolve_disagreement(
        [{'reviewer': 'a', 'verdict': 'ok'}, {'verdict': 'revise'}])
    assert mixed['contested'] is False and mixed['distinctReviewers'] == ['a']


# --- thẻ nhánh `research_branch_report` --------------------------------------

def test_the_branch_report_caps_against_the_frozen_survey_date_not_today(tmp_path):
    """R3: thẻ nhánh và cổng hồ sơ phải kẹp cùng mốc `scope['surveyDate']`, không phải hôm nay."""
    store, runtime = _harness(tmp_path)
    scope = {'surveyDate': '2020-01-01', 'timePolicy': {'velocity': 'fast'}}
    session = _research_branch(store, runtime, 'rs1', scope)
    sid = session['id']
    result = research_review.apply_branch_report(runtime, session, {
        'researchId': 'rs1', 'facetId': 'f-x',
        'rows': [_row('r1', 'alpha.example', published_at='2019-06-01'),
                 _row('r2', 'beta.example', published_at='2019-06-01')],
        'claims': [{'claimId': 'c1', 'text': 'Xu hướng nguồn đang tăng.',
                    'claimType': 'trend', 'stanceOrigin': 'source-stated',
                    'confidence': 'high', 'rowIds': ['r1', 'r2']}],
    })
    assert result['rowIds'] == ['r1', 'r2']
    stored = store.claim_meta('rs1', result['claimIds'][0])
    # `2019-06-01` nằm TRONG cửa sổ của mốc khảo sát 2020-01-01, nhưng NGOÀI cửa sổ của hôm nay.
    assert stored['confidenceCap'] == 'high'
    survey, days, _velocity = research_runtime._scope_time_window(
        runtime, 'rs1', store.research_job('rs1'))
    assert survey == '2020-01-01' and days == research_evidence.window_days('fast')
    cited = [store.source_row(sid, row_id) for row_id in ('r1', 'r2')]
    expected = research_evidence.confidence_cap('trend', cited, stance_origin='source-stated',
                                                window_days=days, as_of=survey)
    assert stored['confidenceCap'] == expected['cap'] == 'high'
    assert research_evidence.confidence_cap(
        'trend', cited, stance_origin='source-stated', window_days=days,
        as_of=research_evidence.survey_date())['cap'] == 'medium', \
        'mốc hôm nay phải cho mức trần KHÁC — ca kiểm này thực sự phân biệt hai mốc'
    store.close()


def test_every_cited_row_is_linked_to_the_claim(tmp_path):
    """R7a: nhận định nhiều nguồn giữ đủ dấu vết trong sổ liên kết, không chỉ dòng đầu."""
    store, runtime = _harness(tmp_path)
    session = _research_branch(store, runtime, 'rs2', {'surveyDate': '2020-01-01'})
    sid = session['id']
    research_review.apply_branch_report(runtime, session, {
        'researchId': 'rs2',
        'rows': [_row('r1', 'alpha.example'), _row('r2', 'beta.example')],
        'claims': [{'claimId': 'c1', 'text': 'Một nhận định do hai nguồn đỡ.',
                    'claimType': 'numeric', 'confidence': 'high', 'rowIds': ['r1', 'r2']}],
    })
    linked = {row['row_id'] for row in store.evidence_graph(sid)}
    assert linked == {'r1', 'r2'}, 'mọi dòng được dẫn phải có liên kết (chỉ dòng đầu là thiếu)'
    store.close()


def test_the_facet_clusters_are_unioned_across_all_claims(tmp_path):
    """R7b: `originClusters` là HỢP của mọi nhận định, không phải giá trị của nhận định cuối."""
    store, runtime = _harness(tmp_path)
    session = _research_branch(store, runtime, 'rs3', {'surveyDate': '2020-01-01'})
    research_review.apply_branch_report(runtime, session, {
        'researchId': 'rs3', 'facetId': 'f-x',
        'rows': [_row('r1', 'alpha.example'), _row('r2', 'beta.example')],
        'claims': [{'claimId': 'c1', 'text': 'Nhận định một.', 'claimType': 'numeric',
                    'confidence': 'high', 'rowIds': ['r1']},
                   {'claimId': 'c2', 'text': 'Nhận định hai.', 'claimType': 'numeric',
                    'confidence': 'high', 'rowIds': ['r2']}],
    })
    facet = store.facet('rs3', 'f-x')
    assert facet['originClusters'] == 2, 'hợp hai cụm khác nhau, không chỉ cụm của nhận định cuối'
    store.close()


def test_an_unknown_row_id_does_not_resurrect_an_unrelated_source(tmp_path):
    """R7d: mã dòng lạ không được gắn nhận định vào dòng đầu tiên của báo cáo."""
    store, runtime = _harness(tmp_path)
    session = _research_branch(store, runtime, 'rs4', {'surveyDate': '2020-01-01'})
    sid = session['id']
    result = research_review.apply_branch_report(runtime, session, {
        'researchId': 'rs4',
        'rows': [_row('r1', 'alpha.example')],
        'claims': [{'text': 'Nhận định trỏ vào dòng không tồn tại.',
                    'claimType': 'numeric', 'confidence': 'high', 'rowIds': ['rBogus']}],
    })
    assert result['claimIds'] == []
    # `source_add` ghim nhận định của chính dòng lên nó; điều KHÔNG được xảy ra là nhận định trỏ
    # vào mã dòng lạ bị gắn vào dòng r1.
    assert 'Nhận định trỏ vào dòng không tồn tại.' not in {
        row['claim'] for row in store.evidence_graph(sid)}, \
        'không được hồi sinh dòng r1 cho một mã dòng lạ'
    store.close()


def test_the_branch_report_tool_refuses_anyone_but_the_research_branch(tmp_path):
    """R7e: cổng vai là `research` — không chỉ `orchestrator`/rỗng."""
    store, runtime = _harness(tmp_path)
    for role in ('orchestrator', 'research-review', 'explore'):
        sid = runtime.create({'skills': []}, role=role)['id']
        with pytest.raises(PermissionError):
            research_review.apply_branch_report(runtime, store.get(sid), {'researchId': 'rs5'})
    store.close()
