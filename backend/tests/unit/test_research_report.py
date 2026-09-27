"""`research_report` (P2 §5.8): khung tám mục, danh mục mô-đun, cổng cấu trúc, tên tệp phụ."""
from __future__ import annotations

import pytest

from agentbox.agent_core import limits
from agentbox.agent_core import research_report as rr


def full_report(*, modules=('M-landscape',), sections=None, claims=(), unexplored=()):
    return {'modules': list(modules),
            'sections': list(sections if sections is not None else rr.section_ids()),
            'claims': list(claims), 'unexplored': list(unexplored), 'coverage': {}}


def codes(errors):
    return [item['code'] for item in errors]


# --- danh mục ---------------------------------------------------------------

def test_ten_modules_and_eight_frame_sections():
    assert len(rr.module_ids()) == 10
    assert rr.module_ids() == tuple(rr.MODULES)
    assert len(rr.FRAME_SECTIONS) == 8
    assert rr.section_ids()[0] == 'conclusions'
    assert rr.section_labels()[0] == 'Kết luận ngắn'
    assert rr.section_labels()[-1] == 'Nguồn'
    assert rr.module_title('M-gaps').startswith('Sổ khoảng trống')
    assert rr.module_title('không có') == ''


@pytest.mark.parametrize('value,expected', [
    ('M-gaps', 'M-gaps'), ('gaps', 'M-gaps'), ('M-GAPS', 'M-gaps'), ('m gaps', 'M-gaps'),
    ('m_gaps', 'M-gaps'), ('mô-đun lạ', ''), ('', ''), (None, ''),
])
def test_normalize_module(value, expected):
    assert rr.normalize_module(value) == expected


def test_normalize_job_types_keeps_the_canonical_order_and_drops_junk():
    assert rr.normalize_job_types(['market', 'quick', 'lạ']) == ('quick', 'market')
    assert rr.normalize_job_types('literature_map') == ('literature-map',)
    assert rr.normalize_job_types(None) == ()
    assert rr.normalize_job_types(['mixed', 'mixed']) == ('mixed',)


def test_modules_for_covers_ten_job_types_and_never_returns_empty():
    assert rr.modules_for('landscape') == ('M-landscape',)
    assert 'M-litmap' in rr.modules_for('literature-map')
    assert rr.modules_for('claim-check') == ('M-verdict',)
    assert rr.modules_for('refresh') == ('M-changelog',)
    assert rr.modules_for('lạ') == ('M-landscape',)
    for job in rr.JOB_TYPES:
        assert rr.modules_for(job)


def test_required_modules_are_the_promise_recorded_in_the_scope_card():
    assert rr.required_modules('landscape') == ('M-landscape',)
    assert rr.required_modules(['gap', 'market']) == ('M-gaps', 'M-market')
    assert rr.required_modules('quick') == ()
    assert rr.required_modules('lạ') == ()
    assert set(rr.REQUIRED_MODULES) <= set(rr.JOB_TYPES)


def test_report_template_has_the_frame_the_modules_and_the_claims_slot():
    template = rr.report_template(['deep-dive', 'market'])
    assert template['schemaVersion'] == 1
    assert template['level'] == 2
    assert template['modules'] == ['M-paper-card', 'M-artifacts', 'M-market']
    assert template['requiredModules'] == ['M-paper-card', 'M-market']
    assert template['claims'] == []
    assert template['coverage'] == {}
    assert template['unexplored'] == []
    assert [section['sectionId'] for section in template['sections']] == list(rr.section_ids())
    assert template['sections'][0]['heading'] == '## Kết luận ngắn'
    assert rr.report_template('landscape', level=3)['sections'][0]['heading'] == '### Kết luận ngắn'
    assert rr.report_template('landscape', level='rác')['level'] == 2


def test_template_survives_a_bad_level():
    assert rr.report_template('quick', level=0)['level'] == 1


# --- tệp phụ ----------------------------------------------------------------

def test_sidecar_names_are_versioned_and_include_extractions():
    names = rr.sidecar_names(3, job_types=['landscape'])
    assert names == ('v3-scope.json', 'v3-coverage.json', 'v3-claims.jsonl', 'v3-report.json')
    with_chase = rr.sidecar_names('4', job_types=['refresh'],
                                  extractions=['s-1', {'sourceId': 's-2'}, '', None])
    assert 'changelog.md' in with_chase
    assert 'extractions/s-1.json' in with_chase
    assert 'extractions/s-2.json' in with_chase
    assert with_chase[0] == 'v4-scope.json'
    assert rr.sidecar_names(1, extractions=['a/b']) == ('v1-scope.json', 'v1-coverage.json',
                                                        'v1-claims.jsonl', 'v1-report.json',
                                                        'extractions/a-b.json')


@pytest.mark.parametrize('value', [0, -1, 'x', None, ''])
def test_sidecar_names_refuses_a_bad_version(value):
    with pytest.raises(ValueError) as error:
        rr.sidecar_names(value)
    assert str(error.value) == 'RESEARCH_VERSION_INVALID'


# --- cổng cấu trúc ----------------------------------------------------------

def test_missing_report_is_the_only_error_of_a_non_object():
    assert codes(rr.validate_report(None)) == [rr.ERROR_MISSING]
    assert codes(rr.validate_report('x')) == [rr.ERROR_MISSING]
    assert rr.ERROR_STRUCTURE == limits.RESEARCH_REPORT_STRUCTURE_CODE


def test_a_complete_landscape_report_passes():
    report = full_report(modules=['M-landscape', 'M-extras'],
                         claims=[{'claimId': 'c-1', 'sectionId': 'content', 'confidence': 'high',
                                  'claimType': 'current-fact'}])
    assert rr.validate_report(report, job_types=['landscape'], claim_ids=['c-1']) == []


def test_module_promise_and_unknown_modules_are_gate_errors():
    missing = rr.validate_report(full_report(modules=[]), job_types=['gap'])
    assert rr.ERROR_MODULE_MISSING in codes(missing)
    wrong = rr.validate_report(full_report(modules=['M-landscape']), job_types=['gap'])
    assert codes(wrong) == [rr.ERROR_MODULE_MISSING]
    unknown = rr.validate_report(full_report(modules=['M-bịa']), job_types=['landscape'])
    assert rr.ERROR_MODULE_UNKNOWN in codes(unknown)
    dict_module = rr.validate_report(full_report(modules=[{'name': 'không có trong danh mục'}]),
                                     job_types=['landscape'])
    assert codes(dict_module) == [rr.ERROR_MODULE_UNKNOWN, rr.ERROR_MODULE_MISSING]
    named = rr.validate_report(full_report(modules=[{'moduleId': 'M-gaps'}]), job_types=['gap'])
    assert named == []


def test_an_undeclared_job_type_promises_no_module():
    """`modules_for(())` lùi về `M-landscape` (đề xuất), nhưng run KHÔNG khai gì thì không hứa gì."""
    assert rr.validate_report(full_report(modules=[])) == []
    # Kiểu việc CÓ khai thì lời hứa vẫn được thi hành (`quick` ⇒ `M-extras`, chưa cần bắt buộc).
    assert codes(rr.validate_report(full_report(modules=[]), job_types=['quick'])) == [
        rr.ERROR_MODULE_MISSING]
    # Không khai kiểu việc nhưng CÓ mô-đun ⇒ không lỗi.
    assert rr.validate_report(full_report(modules=['M-gaps'])) == []


def test_frame_sections_are_all_required():
    errors = rr.validate_report(full_report(sections=['conclusions', 'scope']))
    assert codes(errors) == [rr.ERROR_SECTION_MISSING] * 6
    assert any('Nội dung theo mô-đun' in item['detail'] for item in errors)


def test_claims_must_point_at_real_rows_in_the_ledger():
    promised = full_report(claims=[{'claimId': 'c-1'}])
    assert rr.validate_report(promised, claim_ids=['c-1']) == []
    unknown = rr.validate_report(promised, claim_ids=['c-2'])
    assert codes(unknown) == [rr.ERROR_CLAIM_UNKNOWN]
    without_id = rr.validate_report(full_report(claims=[{'sectionId': 'content'}]), claim_ids=['c-1'])
    assert codes(without_id) == [rr.ERROR_CLAIM_MISSING]
    not_an_object = rr.validate_report(full_report(claims=['c-1']), claim_ids=['c-1'])
    assert codes(not_an_object) == [rr.ERROR_CLAIM_MISSING]


def test_inference_may_not_carry_data_confidence_and_needs_premises():
    bad = rr.validate_report(full_report(claims=[{'claimId': 'c-1', 'claimType': 'inference',
                                                  'confidence': 'medium'}]))
    assert codes(bad) == [rr.ERROR_INFERENCE_CONFIDENCE, rr.ERROR_INFERENCE_CONFIDENCE]
    with_premises = full_report(claims=[{'claimId': 'c-1', 'claimType': 'inference',
                                         'confidence': 'unknown', 'premises': ['c-9']}])
    assert rr.validate_report(with_premises) == []
    # Nhận định dữ kiện vẫn mang được độ tin cậy.
    fact = full_report(claims=[{'claimId': 'c-1', 'claimType': 'current-fact', 'confidence': 'high'}])
    assert rr.validate_report(fact) == []


def test_unexplored_section_must_match_the_facets_that_are_not_saturated():
    facets = [{'facetId': 'f-1', 'label': 'A', 'status': 'saturated'},
              {'facetId': 'f-2', 'label': 'B', 'status': 'searched'},
              {'facetId': 'f-3', 'label': 'C', 'status': 'thin'},
              {'facetId': 'f-4', 'label': 'D', 'status': 'blocked'}]
    assert rr.unsat_facets(facets) == ['f-2', 'f-3', 'f-4']
    ok = full_report(unexplored=['f-2', 'f-3', 'f-4'])
    assert rr.validate_report(ok, facets=facets) == []
    by_label = full_report(unexplored=[{'label': 'B'}, 'f-3', 'f-4'])
    assert rr.validate_report(by_label, facets=facets) == []
    missed = rr.validate_report(full_report(unexplored=['f-2']), facets=facets)
    assert codes(missed) == [rr.ERROR_UNEXPLORED_MISMATCH, rr.ERROR_UNEXPLORED_MISMATCH]
    extra = rr.validate_report(full_report(unexplored=['f-1']), facets=facets)
    assert codes(extra) == [rr.ERROR_UNEXPLORED_MISMATCH] * 4


def test_gate_errors_are_reported_as_whole_codes():
    errors = rr.validate_report(full_report(modules=[], sections=[]), job_types=['gap'])
    assert rr.error_codes(errors) == (rr.ERROR_MODULE_MISSING, rr.ERROR_SECTION_MISSING)
    assert rr.error_codes(None) == ()
    assert rr.error_codes([{'code': 'x'}, {'code': 'x'}, 'y']) == ('x', 'y')
