"""Ca kiểm cho bộ lỗi cấy sẵn (``scripts/eval/seeded_defects.py``, §8.4).

Không ca nào gọi mạng hay model: đường OFFLINE là hàm thuần trên các tệp JSON của
``scripts/eval/fixtures/seeded/``. Đường LIVE chỉ được kiểm ở chỗ NÓ TỪ CHỐI: thiếu
``BOXFOX_EVAL_ALLOW_SPEND=1`` thì không có gì chạy, và qua được cổng mà thiếu hàm `delegate`
thì ném lỗi rõ ràng thay vì lặng lẽ tiêu tiền.
"""
import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
SCRIPT = ROOT / 'scripts' / 'eval' / 'seeded_defects.py'
HARNESS = ROOT / 'backend' / 'src'
sys.path.insert(0, str(HARNESS))


@pytest.fixture(scope='module')
def seeded():
    spec = importlib.util.spec_from_file_location('seeded_defects', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['seeded_defects'] = module
    spec.loader.exec_module(module)
    return module


def test_every_frozen_defect_kind_has_a_fixture_a_detector_and_a_reviewer(seeded):
    kinds = seeded.defect_kinds()
    assert len(kinds) == 9, 'danh mục trong `limits` là nguồn, không phải con số chép tay'
    fixtures = seeded.load_fixtures()
    assert {fixture['kind'] for fixture in fixtures} == set(kinds)
    for fixture in fixtures:
        assert fixture['clean'] and fixture['injected']
        assert fixture['oracle_pass'] is True
        assert fixture['environment']['network'] == 'off'
        assert seeded.detector_for(fixture).__name__ != '<lambda>', fixture['kind']
    assert set(seeded.DETECTORS) == set(kinds)
    assert set(seeded.REVIEWER_OF_KIND) == set(kinds)


def test_the_detector_fires_on_the_injected_bundle_and_stays_quiet_on_the_clean_one(seeded):
    """Từng loại lỗi được đo riêng: một lần hụt chỉ thẳng bộ dò nào hụt."""
    for fixture in seeded.load_fixtures():
        injected = seeded.run_detector(fixture, injected=True)
        clean = seeded.run_detector(fixture, injected=False)
        assert injected['detected'] is True, f'{fixture["kind"]}: bộ dò không bắt ({injected["detail"]})'
        assert clean['detected'] is False, f'{fixture["kind"]}: báo sai trên hồ sơ sạch ({clean["detail"]})'
        assert injected['hits'] == injected['total'] == 2
        assert clean['hits'] == 0 and clean['total'] == 2


def test_the_offline_run_meets_the_frozen_thresholds_and_reports_them(seeded):
    report = seeded.run()
    assert report['passed'] is True
    assert report['missingKinds'] == []
    assert report['injectedTotal'] >= 18 and report['cleanTotal'] >= 18
    assert report['falseAlarmRate'] <= report['falseAlarmMax']
    for row in report['kinds'].values():
        assert row['catchRate'] >= row['threshold'], row['kind']
        assert row['falseAlarmRate'] <= report['falseAlarmMax'], row['kind']
        assert row['thresholdKey'] in ('catch', 'coverage')
    # Hướng lớn bị gỡ dùng ngưỡng bao phủ, không phải ngưỡng dữ kiện.
    assert report['kinds']['removed-direction']['threshold'] == seeded.thresholds()['coverage']
    assert 'báo sai' in seeded.render(report) and 'KẾT LUẬN' in seeded.render(report)


def test_the_criteria_come_from_limits_so_the_benchmark_and_the_gate_cannot_drift(seeded):
    limits = seeded.harness_module('limits')
    assert limits is not None, 'ca này phải chạy trong cây mã harness'
    assert seeded.defect_kinds() == tuple(limits.RESEARCH_SEEDED_DEFECT_KINDS)
    assert seeded.thresholds() == {'catch': limits.RESEARCH_SEEDED_CATCH_MIN,
                                   'coverage': limits.RESEARCH_SEEDED_COVERAGE_MIN,
                                   'falseAlarm': limits.RESEARCH_SEEDED_FALSE_ALARM_MAX}


def test_an_unknown_detector_name_falls_back_to_the_kind_and_an_unknown_kind_stays_quiet(seeded):
    # Tên bộ dò là tuỳ chọn: thiếu thì lấy theo `kind`.
    fallback = seeded.run_detector({'kind': 'wrong-number', 'detector': 'nope',
                                    'injected': [{'rows': [], 'claims': []}], 'clean': []})
    assert fallback['detected'] is False
    quiet = seeded.run_detector({'kind': 'not-a-kind', 'detector': 'nope',
                                 'injected': [{}], 'clean': []})
    assert quiet['detected'] is False and 'not-a-kind' in quiet['detail']


def test_the_live_path_refuses_before_any_spend(seeded, monkeypatch):
    monkeypatch.delenv(seeded.guard.SPEND_ENV, raising=False)
    monkeypatch.delenv(seeded.guard.BUDGET_ENV, raising=False)
    refused = seeded.run_live(fixtures=seeded.load_fixtures(), delegate=lambda *a: 'text')
    assert refused['allowed'] is False and refused['results'] == []
    assert seeded.guard.SPEND_ENV in refused['reason']
    assert seeded.main([]) == 0, 'mặc định là đường offline và nó phải đạt'
    assert seeded.main(['--live', '--budget-usd', '5']) == 2, 'thiếu opt-in ⇒ từ chối, mã thoát 2'


def test_the_live_path_needs_a_delegate_even_when_the_gate_is_open(seeded, monkeypatch):
    monkeypatch.setenv(seeded.guard.SPEND_ENV, '1')
    monkeypatch.setenv(seeded.guard.BUDGET_ENV, '10')
    briefs = seeded.live_briefs(seeded.load_fixtures())
    assert briefs and all(brief['prompt'] and brief['taskKind'] for brief in briefs)
    assert {brief['taskKind'] for brief in briefs} <= {'evidence', 'critique', 'coverage'}
    with pytest.raises(ValueError, match='LIVE_DELEGATE_REQUIRED'):
        seeded.run_live(fixtures=seeded.load_fixtures(), delegate=None)
    # Có `delegate` thì bên soát THẬT được gọi — ở đây là một hàm giả trả lời đúng mọi loại lỗi.
    seen = []

    def fake_delegate(role, task_kind, prompt):
        seen.append((role, task_kind))
        return ('số không khớp; gán sai; nguồn cũ; thiếu hướng; đề xuất của chính mình; '
                'giả định chưa xác nhận; cùng nguồn; điều kiện đo; không có nguồn')

    live = seeded.run_live(fixtures=seeded.load_fixtures(), delegate=fake_delegate)
    assert live['allowed'] is True and live['total'] == len(seen) == len(briefs)
    assert live['catchRate'] == 1.0
    assert all(role == 'research-review' for role, _ in seen)
    # Đường live tự nói nó chỉ là tín hiệu khói, không phải điểm đo chất lượng.
    assert live['smoke'] is True and live['signal'] == 'smoke' and 'TÍN HIỆU KHÓI' in live['note']


def test_the_live_hit_needs_phrase_level_evidence_not_generic_words(seeded):
    """Bài soát chung chung (chỉ có "số", "so sánh", "điều kiện") KHÔNG được tính là bắt lỗi."""
    generic = 'Bài này có nhiều số và cần so sánh điều kiện giữa các bảng đo.'
    assert seeded._live_hit('wrong-number', generic) is False
    assert seeded._live_hit('mismatched-benchmark', generic) is False
    assert seeded._live_hit('same-origin-independent', generic) is False
    # Cụm từ đặc trưng của đúng loại lỗi thì mới tính.
    assert seeded._live_hit('wrong-number', 'Số không khớp với đoạn trích.') is True
    assert seeded._live_hit('mismatched-benchmark', 'Hai bảng đo khác điều kiện nên không so được.') is True
    assert seeded._live_hit('same-origin-independent', 'Hai dòng cùng một nguồn, không độc lập.') is True



def test_the_two_formerly_shared_detectors_read_their_own_signal(seeded):
    """R4: `same-origin-independent` và `mismatched-benchmark` không còn dùng chung một bộ dò."""
    assert seeded.same_origin_independent is not seeded.mismatched_benchmark
    collapse = {'rows': [
        {'rowId': 'r1', 'url': 'https://a.example/p', 'host': 'a.example', 'excerpt': 'x'},
        {'rowId': 'r2', 'url': 'https://a.example/q', 'host': 'a.example', 'excerpt': 'y'}],
        'claims': [{'claimId': 'c1', 'claimType': 'numeric', 'confidence': 'high',
                    'rowIds': ['r1', 'r2']}]}
    distinct = {'rows': [
        {'rowId': 'r1', 'url': 'https://a.example/p', 'host': 'a.example', 'excerpt': 'x'},
        {'rowId': 'r2', 'url': 'https://b.example/q', 'host': 'b.example', 'excerpt': 'y'}],
        'claims': collapse['claims']}
    # Tín hiệu riêng của same-origin: hai dòng thu về MỘT cụm gốc.
    assert seeded.same_origin_independent(collapse)['detected'] is True
    assert seeded.same_origin_independent(distinct)['detected'] is False
    # Tín hiệu riêng của mismatched-benchmark: điều kiện đo không được ghi lại.
    unrecorded = {'rows': [{'rowId': 'r1', 'host': 'a.example', 'excerpt': 'x',
                            'recordedConditions': False}],
                  'claims': [{'claimId': 'c1', 'claimType': 'benchmark', 'confidence': 'high',
                              'rowIds': ['r1']}]}
    recorded = {'rows': [dict(unrecorded['rows'][0], recordedConditions=True)],
                'claims': unrecorded['claims']}
    assert seeded.mismatched_benchmark(unrecorded)['detected'] is True
    assert seeded.mismatched_benchmark(recorded)['detected'] is False
    # Mỗi bộ dò chỉ bắt đúng loại của mình.
    assert seeded.mismatched_benchmark(collapse)['detected'] is False
    assert seeded.same_origin_independent(unrecorded)['detected'] is False


def test_the_survey_anchor_is_the_frozen_scope_survey_date_with_a_legacy_fallback(seeded):
    """R3: mốc khảo sát đọc `scope.surveyDate` (hình dạng sản xuất) trước, `timePolicy.asOf` là đường lùi."""
    assert seeded._scope_as_of({'scope': {'surveyDate': '2026-09-25'}}) == '2026-09-25'
    assert seeded._scope_as_of({'scope': {'timePolicy': {'asOf': '2020-01-01'}}}) == '2020-01-01'
    assert seeded._scope_as_of(
        {'scope': {'surveyDate': '2026-09-25', 'timePolicy': {'asOf': '2020-01-01'}}}) \
        == '2026-09-25', 'surveyDate thắng khi cả hai cùng có'
    assert seeded._scope_as_of({}) == ''
    # Bộ ca outdated nay dùng ĐÚNG hình dạng sản xuất ghi, không còn `timePolicy.asOf`.
    fixture = next(item for item in seeded.load_fixtures()
                   if item['kind'] == 'outdated-supports-current')
    scopes = [bundle['scope'] for key in ('clean', 'injected') for bundle in fixture[key]]
    assert scopes and all('surveyDate' in scope for scope in scopes)
    assert all('asOf' not in (scope.get('timePolicy') or {}) for scope in scopes)
