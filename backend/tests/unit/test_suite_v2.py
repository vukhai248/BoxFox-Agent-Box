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
