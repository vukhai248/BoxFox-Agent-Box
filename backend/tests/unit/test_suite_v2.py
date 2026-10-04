"""H9 — suite v2: manifest ``boxfox-eval-suite/2`` kiểm được, fail closed, không chấm lại lịch sử.

Bảy điều dễ nói suông nhất được ghim ở đây:

1. manifest đã commit nạp được, khớp schema, và băm fixture/pin nguồn khớp cây hiện tại;
2. `build_suite()` tất định: dựng lại đúng bằng tệp đã commit (không có chỉnh tay);
3. mọi oracle an toàn PHẢI mang `preserve_invariant` — gỡ/đổi là lỗi, không phải cảnh báo;
4. disposition lạ, field thiếu, hash lệch, pin lệch, tập safety lệch đều bị từ chối;
5. oracle trajectory không được nằm trong `invariants` của ca;
6. manifest không được tự nhận đã đo (`measured: false`) và phải khai consent cho live pilot;
7. `read_legacy_receipt` chỉ đọc: luôn trả `verdict=None`, `rescored=False`.

`scripts/eval` là các module phẳng cạnh nhau (không phải package) nên tệp này tự thêm thư mục
đó vào `sys.path`, giống cách chúng được chạy bằng `python scripts/eval/...`.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

def _repo_root() -> Path:
    import os
    override = os.environ.get('BOXFOX_REPO_ROOT')
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        if (parent / 'scripts' / 'eval' / 'suite_v2.py').is_file():
            return parent
    raise RuntimeError('không tìm thấy gốc kho chứa scripts/eval/suite_v2.py')


REPO = _repo_root()
EVAL_DIR = REPO / 'scripts' / 'eval'
sys.path.insert(0, str(EVAL_DIR))

import suite_v2  # noqa: E402


def _manifest() -> dict:
    return suite_v2.load_suite()


def _mutated(**changes) -> dict:
    doc = copy.deepcopy(_manifest())
    doc.update(changes)
    return doc


# --------------------------------------------------------------------------- manifest + tất định
def test_committed_manifest_validates_and_hashes_match():
    doc = _manifest()
    suite_v2.validate_suite(doc, check_hashes=True)
    assert doc['schema'] == 'boxfox-eval-suite/2'
    assert doc['measured'] is False
    assert doc['livePilotRequiresConsent'] is True
    assert len(doc['cases']) == 62
    counts = {}
    for case in doc['cases']:
        counts[case['family']] = counts.get(case['family'], 0) + 1
    assert counts == {'work-acceptance': 17, 'research-r': 12, 'quality-q': 12,
                      'research-v2': 12, 'seeded-defect': 9}


def test_build_is_deterministic_and_matches_the_committed_file():
    assert suite_v2.build_suite() == _manifest()


def test_every_disposition_is_actually_used():
    used = {row['disposition'] for case in _manifest()['cases'] for row in case['oracleMapping']}
    assert used == set(suite_v2.DISPOSITIONS)


def test_every_case_has_a_fixture_that_exists():
    for case in _manifest()['cases']:
        assert (REPO / case['legacyCaseRef']).is_file(), case['caseId']


# --------------------------------------------------------------------------- safety oracles
def test_every_safety_oracle_is_mapped_to_preserve_invariant():
    doc = _manifest()
    for case in doc['cases']:
        for row in case['oracleMapping']:
            if row['oracle'] in suite_v2.SAFETY_ORACLES:
                assert row['disposition'] == 'preserve_invariant', (case['caseId'], row['oracle'])
        for name in case['invariants']:
            assert name in suite_v2.SAFETY_ORACLES


def test_remapping_a_safety_oracle_is_rejected():
    doc = _manifest()
    target = next(row for case in doc['cases'] for row in case['oracleMapping']
                  if row['oracle'] in suite_v2.SAFETY_ORACLES)
    target['disposition'] = 'map_outcome'
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_SAFETY_ORACLE_REMAPPED'


def test_safety_oracle_set_drift_is_rejected():
    doc = _mutated(safetyOracles=sorted(suite_v2.SAFETY_ORACLES)[:-1])
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_SAFETY_SET_DRIFT'


def test_trajectory_oracle_cannot_be_claimed_as_an_invariant():
    doc = _manifest()
    case = next(case for case in doc['cases']
                if any(row['disposition'] == 'legacy_trajectory_only' for row in case['oracleMapping']))
    trajectory = next(row['oracle'] for row in case['oracleMapping']
                      if row['disposition'] == 'legacy_trajectory_only')
    # Chèn tên trajectory vào invariants: phải bị từ chối vì không phải oracle an toàn.
    case['invariants'] = list(case['invariants']) + [trajectory]
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    # Bộ kiểm bắt đúng chỗ: oracle trajectory không được mang nghĩa bất biến.
    assert excinfo.value.code == 'SUITE_TRAJECTORY_CLAIMED_AS_INVARIANT'


def test_invariant_must_appear_in_the_oracle_mapping():
    doc = _manifest()
    case = doc['cases'][0]
    case['invariants'] = list(case['invariants']) + ['no_auto_pass']
    if 'no_auto_pass' in [row['oracle'] for row in case['oracleMapping']]:
        pytest.skip('ca này đã có no_auto_pass trong bảng oracle')
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_INVARIANT_NOT_MAPPED'


# --------------------------------------------------------------------------- fail closed
def test_unknown_disposition_is_rejected():
    doc = _manifest()
    doc['cases'][0]['oracleMapping'][0]['disposition'] = 'looks_fine'
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_DISPOSITION_UNKNOWN'


def test_missing_case_field_is_rejected():
    doc = _manifest()
    del doc['cases'][0]['measurementContractVersion']
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_CASE_FIELD_MISSING'


def test_missing_oracle_field_is_rejected():
    doc = _manifest()
    doc['cases'][0]['oracleMapping'][0]['negativeControl'] = ''
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_ORACLE_FIELD_MISSING'


def test_fixture_hash_mismatch_is_rejected():
    doc = _manifest()
    doc['cases'][0]['fixtureHash'] = 'sha256:' + '0' * 64
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc, check_hashes=True)
    assert excinfo.value.code == 'SUITE_FIXTURE_HASH_MISMATCH'


def test_source_pin_mismatch_is_rejected():
    doc = _manifest()
    doc['cases'][0]['sourcePins']['scripts/eval/rubric.py'] = 'sha256:' + '1' * 64
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc, check_hashes=True)
    assert excinfo.value.code == 'SUITE_SOURCE_PIN_MISMATCH'


def test_measured_claim_is_rejected():
    doc = _mutated(measured=True)
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_MEASURED_CLAIM_UNSUPPORTED'


def test_consent_declaration_is_required():
    doc = _mutated(livePilotRequiresConsent=False)
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_CONSENT_NOT_DECLARED'


def test_duplicate_case_id_is_rejected():
    doc = _manifest()
    doc['cases'][1]['caseId'] = doc['cases'][0]['caseId']
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_CASE_DUPLICATE'


def test_unknown_evidence_kind_is_rejected():
    doc = _manifest()
    doc['cases'][0]['allowedEvidenceKinds'] = ['vibes']
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_EVIDENCE_UNKNOWN'


def test_wrong_schema_is_rejected():
    doc = _mutated(schema='boxfox-eval-suite/1')
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.validate_suite(doc)
    assert excinfo.value.code == 'SUITE_SCHEMA_UNSUPPORTED'


# --------------------------------------------------------------------------- adapter lịch sử
def test_legacy_receipt_never_returns_a_verdict():
    row = {'caseId': 'S01', 'repeat': 1, 'validity': 'quality-valid', 'statePassed': True,
           'passed': 4, 'scores': {'flow': 2}}
    receipt = suite_v2.read_legacy_receipt(row, source='w10f-seq')
    assert receipt['verdict'] is None
    assert receipt['rescored'] is False
    assert receipt['caseId'] == 'S01'
    assert receipt['payload']['validity'] == 'quality-valid'


def test_legacy_receipt_requires_a_case_id():
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.read_legacy_receipt({'validity': 'quality-valid'}, source='w10f-seq')
    assert excinfo.value.code == 'SUITE_RECEIPT_MISSING_CASE_ID'


# --------------------------------------------------------------------------- H9: fault corpus
def test_fault_corpus_is_fully_caught_with_the_declared_codes():
    report = suite_v2.run_fault_corpus()
    assert report['faults'] >= 30
    assert all(row['caught'] and row['observedCode'] == row['expectedCode']
               for row in report['results'])
    ids = [row['faultId'] for row in report['results']]
    codes = [row['expectedCode'] for row in report['results']]
    assert len(set(ids)) == len(ids), 'faultId phải duy nhất'
    assert len(set(codes)) == len(codes), 'mỗi mã lỗi chỉ cần một negative control'


def test_fault_corpus_covers_every_validation_code():
    import re as _re
    source = (EVAL_DIR / 'suite_v2.py').read_text(encoding='utf-8')
    declared = {code for code in _re.findall(r"'((?:SUITE|SHADOW)_[A-Z_]+)'", source)
                if not code.startswith(('SUITE_FAULT_', 'SHADOW_'))}
    corpus = json.loads((EVAL_DIR / 'fixtures' / 'suite-v2-faults.json').read_text(encoding='utf-8'))
    covered = {entry['expectedCode'] for section in ('manifestFaults', 'receiptFaults',
                                                     'buildFaults', 'treeFaults')
               for entry in corpus.get(section) or []}
    assert declared == covered


def _write_corpus(tmp_path: Path, **sections) -> Path:
    body = {'schema': 'boxfox-eval-faults/1',
            'manifestFaults': [{'faultId': 'noop', 'mutation': {'op': 'set',
                                                                'path': ['note'], 'value': 'x'},
                                'expectedCode': 'SUITE_SCHEMA_UNSUPPORTED'}],
            'receiptFaults': [{'faultId': 'ok-row',
                               'row': {'caseId': 'S01'}, 'expectedCode': 'SUITE_RECEIPT_NOT_AN_OBJECT'}]}
    body.update(sections)
    path = tmp_path / 'corpus.json'
    path.write_text(json.dumps(body, ensure_ascii=False), encoding='utf-8')
    return path


def test_fault_runner_refuses_a_fault_that_slips_through(tmp_path):
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.run_fault_corpus(_write_corpus(tmp_path))
    assert excinfo.value.code == 'SUITE_FAULT_NOT_CAUGHT'


def test_fault_runner_reports_a_wrong_code(tmp_path):
    path = _write_corpus(tmp_path, manifestFaults=[{'faultId': 'wrong-expectation',
                                                    'mutation': {'op': 'set', 'path': ['measured'],
                                                                 'value': True},
                                                    'expectedCode': 'SUITE_SCHEMA_UNSUPPORTED'}])
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.run_fault_corpus(path)
    assert excinfo.value.code == 'SUITE_FAULT_CODE_MISMATCH'


def test_fault_runner_rejects_an_unknown_mutation_op(tmp_path):
    path = _write_corpus(tmp_path, manifestFaults=[{'faultId': 'op-la',
                                                    'mutation': {'op': 'lam-cho-vui'},
                                                    'expectedCode': 'SUITE_SCHEMA_UNSUPPORTED'}])
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.run_fault_corpus(path)
    assert excinfo.value.code == 'SUITE_FAULT_MUTATION_INVALID'


def test_fault_runner_rejects_a_corpus_with_the_wrong_schema(tmp_path):
    path = tmp_path / 'corpus.json'
    path.write_text(json.dumps({'schema': 'boxfox-eval-faults/0'}), encoding='utf-8')
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.run_fault_corpus(path)
    assert excinfo.value.code == 'SUITE_FAULT_SCHEMA_UNSUPPORTED'


def test_cli_faults_passes(capsys):
    assert suite_v2.main(['--faults']) == 0
    assert 'đều bị bắt đúng mã' in capsys.readouterr().out


# --------------------------------------------------------------------------- H9: shadow legacy
def _legacy_cells() -> list[dict]:
    return [{'label': 'S01-r1', 'validity': 'quality-valid', 'run': 'verified',
             'disposition': 'completed'},
            {'label': 'S02-r2', 'validity': 'measurement-invalid', 'disposition': 'completed'},
            {'label': 'Z99-r1', 'validity': 'quality-valid', 'disposition': 'completed'}]


def test_shadow_maps_legacy_labels_to_cases():
    report = suite_v2.shadow_legacy_cells(_legacy_cells(), source='synthetic')
    assert report['schema'] == 'boxfox-eval-shadow/1'
    assert report['coverage'] == {'total': 3, 'mapped': 2, 'unmapped': 1, 'ratio': 0.6667}
    assert report['caseCoverage'] == {'W10/S01': 1, 'W10/S02': 1}
    assert report['legacyStates'] == {'measurement-invalid': 1, 'quality-valid': 1}
    assert report['unmapped'] == [{'label': 'Z99-r1', 'reason': 'không có ca v2 tương ứng'}]


def test_shadow_never_produces_a_verdict():
    report = suite_v2.shadow_legacy_cells(_legacy_cells(), source='synthetic')
    assert report['verdictsProduced'] == 0
    assert report['measured'] is False and report['rescored'] is False
    for receipt in report['receipts']:
        assert receipt['verdict'] is None
        assert receipt['rescored'] is False
        assert receipt['legacyObservation']['label'].startswith(('S01', 'S02'))


def test_shadow_requires_a_source():
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.shadow_legacy_cells(_legacy_cells(), source='')
    assert excinfo.value.code == 'SHADOW_SOURCE_NOT_DECLARED'


def test_shadow_requires_cells():
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.shadow_legacy_cells([], source='synthetic')
    assert excinfo.value.code == 'SHADOW_CELLS_MISSING'


def test_shadow_rejects_a_case_that_disallows_measurement_evidence():
    doc = _manifest()
    for case in doc['cases']:
        if case['caseId'] == 'W10/S01':
            case['allowedEvidenceKinds'] = ['run_state']
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.shadow_legacy_cells(_legacy_cells(), source='synthetic', manifest=doc)
    assert excinfo.value.code == 'SHADOW_EVIDENCE_KIND_NOT_ALLOWED'


def test_shadow_blocks_a_leaked_verdict(monkeypatch):
    def _leaky(row, *, source):
        return {'caseId': row.get('caseId'), 'source': source, 'evidenceKind': 'measurement',
                'payload': {}, 'verdict': 'pass', 'rescored': False, 'note': 'giả lập rò verdict'}

    monkeypatch.setattr(suite_v2, 'read_legacy_receipt', _leaky)
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.shadow_legacy_cells(_legacy_cells(), source='synthetic')
    assert excinfo.value.code == 'SHADOW_VERDICT_LEAKED'


def test_shadow_label_mapping_is_conservative():
    assert suite_v2.legacy_label_case_id('S01-r2') == 'W10/S01'
    assert suite_v2.legacy_label_case_id('V13-r1') == 'W10/V13'
    assert suite_v2.legacy_label_case_id('') is None
    assert suite_v2.legacy_label_case_id('S01') is None


def test_shadow_cli_requires_a_path():
    with pytest.raises(suite_v2.SuiteError) as excinfo:
        suite_v2.main(['--shadow'])
    assert excinfo.value.code == 'SHADOW_PATH_MISSING'


# --------------------------------------------------------------------------- CLI
def test_cli_check_passes(capsys):
    assert suite_v2.main([]) == 0
    out = capsys.readouterr().out
    assert 'boxfox-eval-suite/2' in out
    assert 'measured=False' in out


def test_cli_explain_prints_a_case(capsys):
    assert suite_v2.main(['--explain', 'W10/S01']) == 0
    assert json.loads(capsys.readouterr().out)['caseId'] == 'W10/S01'
    assert suite_v2.main(['--explain', 'W10/NOPE']) == 1
