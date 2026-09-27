#!/usr/bin/env python3
"""Bộ lỗi CẤY SẴN để đo các vai soát research (§8.4 của kế hoạch v2).

Lấy một hồ sơ TỐT, cấy vào một lỗi đã biết, rồi đo xem bên soát có bắt được không. Chín
loại lỗi nằm ở ``limits.RESEARCH_SEEDED_DEFECT_KINDS``; ngưỡng ở cùng tệp đó:
``RESEARCH_SEEDED_CATCH_MIN`` (0.70), ``RESEARCH_SEEDED_COVERAGE_MIN`` (0.60),
``RESEARCH_SEEDED_FALSE_ALARM_MAX`` (0.20).

Hai đường chạy, CỐ Ý tách rời:

* **offline** (mặc định, không cần gì): chấm bằng các *bộ dò máy* dưới đây — luật thuần lấy
  từ ``agentbox.agent_core.research_evidence``/``research_report``/``research_review`` khi mã
  harness có mặt. Đây là bản chạy được trong CI: không mạng, không model, không tiêu tiền.
* **live** (``--live``): giao hồ sơ đã cấy cho các vai soát THẬT. Chỉ chạy khi
  ``BOXFOX_EVAL_ALLOW_SPEND=1`` **và** có ngân sách — hỏi ``scripts/eval/guard.py`` trước, và
  cần một hàm ``delegate`` do người gọi cấp (tệp này không tự mở kết nối model).

Bộ dò KHÔNG thay cho bên soát thật: nó là mức sàn máy kiểm được, và mỗi bộ dò nêu rõ nó đóng
vai nào (critic / verifier / coverage reviewer) để một lần hụt biết ngay đi tìm ở đâu.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE / 'fixtures' / 'seeded'
sys.path.insert(0, str(HERE))

import guard  # noqa: E402  (cùng thư mục)

HARNESS_ROOT = HERE.parents[1] / 'backend' / 'src'

#: Bản sao chỉ để tệp này chạy được một mình; khi harness có mặt, hằng của harness là nguồn.
FALLBACK_DEFECT_KINDS = ('wrong-number', 'unsupported-claim', 'misattributed',
                         'outdated-supports-current', 'removed-direction', 'survey-as-proposal',
                         'unlabeled-assumption', 'same-origin-independent', 'mismatched-benchmark')
FALLBACK_CATCH_MIN = 0.70
FALLBACK_COVERAGE_MIN = 0.60
FALLBACK_FALSE_ALARM_MAX = 0.20
FALLBACK_NOT_SATURATED = ('unexplored', 'searched', 'thin', 'blocked')
FALLBACK_ASSUMPTION_LABEL = 'GIẢ ĐỊNH (chưa xác nhận)'

#: Loại lỗi nào đóng vai bên soát nào (§8.4: "mỗi vai được đo riêng").
REVIEWER_OF_KIND = {
    'wrong-number': 'verifier',
    'unsupported-claim': 'verifier',
    'misattributed': 'verifier',
    'outdated-supports-current': 'verifier',
    'removed-direction': 'coverage',
    'survey-as-proposal': 'critic',
    'unlabeled-assumption': 'critic',
    'same-origin-independent': 'verifier',
    'mismatched-benchmark': 'critic',
}
#: Ngưỡng áp cho từng loại: hướng lớn bị gỡ dùng ngưỡng bao phủ, còn lại dùng ngưỡng bắt lỗi dữ kiện.
THRESHOLD_OF_KIND = {kind: 'catch' for kind in FALLBACK_DEFECT_KINDS}
THRESHOLD_OF_KIND['removed-direction'] = 'coverage'

_NUMBER_RE = re.compile(r'\d+(?:[.,]\d+)*\s*%?')


# --- một chỗ đọc mã harness -------------------------------------------------

def harness_module(name: str):
    """Module ``agentbox.agent_core.<name>`` nếu import được, không thì ``None``."""
    target = 'agentbox.agent_core.' + name
    if target in sys.modules:
        return sys.modules[target]
    import importlib
    attempts = [str(HARNESS_ROOT)] + [path for path in sys.path if path]
    for path in attempts:
        if path and path not in sys.path:
            sys.path.insert(0, path)
        try:
            return importlib.import_module(target)
        except Exception:  # pragma: no cover - bản chấm vẫn phải chạy được một mình
            continue
    return None


def defect_kinds() -> tuple:
    limits = harness_module('limits')
    return tuple(getattr(limits, 'RESEARCH_SEEDED_DEFECT_KINDS', FALLBACK_DEFECT_KINDS))


def thresholds() -> dict:
    limits = harness_module('limits')
    return {'catch': float(getattr(limits, 'RESEARCH_SEEDED_CATCH_MIN', FALLBACK_CATCH_MIN)),
            'coverage': float(getattr(limits, 'RESEARCH_SEEDED_COVERAGE_MIN', FALLBACK_COVERAGE_MIN)),
            'falseAlarm': float(getattr(limits, 'RESEARCH_SEEDED_FALSE_ALARM_MAX',
                                        FALLBACK_FALSE_ALARM_MAX))}


def _result(name: str, ok: bool, detail: str) -> dict:
    """Đúng ba khoá của hợp đồng §7.2 — cùng khuôn `research_checks._result`."""
    return {'name': name, 'ok': bool(ok), 'detail': str(detail)}


# --- tiện ích thuần ---------------------------------------------------------

def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ('' if value is None else str(value).strip())


def _fold(value) -> str:
    """Chuẩn hoá để so chữ: bỏ dấu, gộp khoảng trắng, chữ thường (không cần harness)."""
    import unicodedata
    text = unicodedata.normalize('NFD', _text(value))
    text = ''.join(char for char in text if unicodedata.category(char) != 'Mn')
    return re.sub(r'\s+', ' ', text).casefold()


def _rows(bundle) -> list:
    return [dict(item) for item in (bundle or {}).get('rows', []) if isinstance(item, dict)]


def _claims(bundle) -> list:
    return [dict(item) for item in (bundle or {}).get('claims', []) if isinstance(item, dict)]


def _cited(claim, by_id) -> list:
    return [by_id[row] for row in (claim.get('rowIds') or []) if row in by_id]


def _time_policy(bundle) -> dict:
    """`timePolicy` của thẻ phạm vi trong một bundle cấy — `{}` khi vắng."""
    return ((bundle or {}).get('scope') or {}).get('timePolicy') or {}


def _scope_velocity(bundle) -> str:
    return _text(_time_policy(bundle).get('velocity'))


def _recorded_conditions(row) -> bool:
    """Điều kiện đo của một dòng benchmark có được ghi lại hay không (`recordedConditions`)."""
    value = row.get('recordedConditions', row.get('recorded_conditions'))
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in ('1', 'true', 'yes', 'y', 'on')


def _scope_as_of(bundle) -> str:
    """Mốc khảo sát ĐÔNG CỨNG của run: `scope.surveyDate` (hình dạng sản xuất ghi) → đường lùi
    `timePolicy.asOf` cho hồ sơ cũ."""
    scope = (bundle or {}).get('scope') or {}
    return _text(scope.get('surveyDate')) or _text(_time_policy(bundle).get('asOf'))


# --- bộ dò: mỗi hàm là một mức sàn máy kiểm được của một bên soát -------------

def number_not_backed(bundle):
    """Verifier: con số trong nhận định không có trong đoạn trích nó dẫn."""
    by_id = {row.get('rowId'): row for row in _rows(bundle)}
    for claim in _claims(bundle):
        numbers = {match.group(0).replace(' ', '') for match in _NUMBER_RE.finditer(_text(claim.get('text')))}
        if not numbers:
            continue
        haystack = ' '.join(_text(row.get('excerpt')) for row in _cited(claim, by_id))
        missing = sorted(number for number in numbers if number not in haystack)
        if missing:
            return {'detected': True, 'detail': f'{claim.get("claimId")}: số {missing} không có trong đoạn trích'}
    return {'detected': False, 'detail': 'mọi con số đều nằm trong đoạn trích đã dẫn'}


def claim_without_source(bundle):
    """Verifier: nhận định không gắn dòng sổ nào."""
    by_id = {row.get('rowId'): row for row in _rows(bundle)}
    for claim in _claims(bundle):
        if not _cited(claim, by_id):
            return {'detected': True, 'detail': f'{claim.get("claimId")}: không có dòng sổ đỡ'}
    return {'detected': False, 'detail': 'mọi nhận định đều có dòng sổ'}


def misattributed(bundle):
    """Verifier: nhận định gán cho nguồn khác với nguồn thật của đoạn trích."""
    by_id = {row.get('rowId'): row for row in _rows(bundle)}
    for claim in _claims(bundle):
        cited = _cited(claim, by_id)
        if not cited:
            continue
        subject = _fold(claim.get('subject'))
        if subject and not any(subject in _fold(row.get('excerpt')) for row in cited):
            return {'detected': True, 'detail': f'{claim.get("claimId")}: đoạn trích không nhắc {claim.get("subject")!r}'}
        attributed = _fold(claim.get('attributedTo'))
        if attributed and not any(attributed == _fold(row.get('host')) for row in cited):
            return {'detected': True, 'detail': f'{claim.get("claimId")}: gán cho {claim.get("attributedTo")!r} nhưng dẫn nguồn khác'}
    return {'detected': False, 'detail': 'mọi nhận định dẫn đúng nguồn của đoạn trích'}


def outdated_supports_current(bundle):
    """Verifier: nguồn cũ đỡ một nhận định \"hiện tại\"."""
    evidence = harness_module('research_evidence')
    for claim in _claims(bundle):
        by_id = {row.get('rowId'): row for row in _rows(bundle)}
        cited = _cited(claim, by_id)
        if not cited:
            continue
        if evidence is not None:
            result = evidence.stale_current_claim(claim.get('claimType'), cited,
                                                  window_days=evidence.window_days(_scope_velocity(bundle)),
                                                  as_of=_scope_as_of(bundle) or None)
            if result.get('stale'):
                return {'detected': True, 'detail': f'{claim.get("claimId")}: mọi nguồn ngoài cửa sổ hiện trạng'}
        elif _scope_velocity(bundle):
            return {'detected': True, 'detail': 'thiếu mã harness để tính cửa sổ thời gian'}
    return {'detected': False, 'detail': 'nguồn đỡ nhận định hiện tại còn trong cửa sổ'}


def removed_direction(bundle):
    """Coverage reviewer: một hướng lớn bị gỡ khỏi hồ sơ."""
    report = (bundle or {}).get('report') or {}
    modules = {_fold(item) for item in (report.get('modules') or [])}
    unexplored = {_text(item) for item in (report.get('unexplored') or [])}
    report_mod = harness_module('research_report')
    not_saturated = tuple(getattr(report_mod, 'NOT_SATURATED_STATUSES', FALLBACK_NOT_SATURATED))
    for facet in (bundle or {}).get('facets', []):
        if not isinstance(facet, dict) or _text(facet.get('status')) not in not_saturated:
            continue
        label = _fold(facet.get('label'))
        if facet.get('facetId') not in unexplored and label not in modules:
            return {'detected': True, 'detail': f'hướng {facet.get("label")!r} bị bỏ khỏi hồ sơ và bản đồ'}
    return {'detected': False, 'detail': 'mọi hướng chưa bão hoà đều còn trong hồ sơ'}


def survey_as_proposal(bundle):
    """Critic: bài tổng quan bị trình như một đề xuất của chính mình."""
    evidence = harness_module('research_evidence')
    inference_kinds = None
    if evidence is not None:
        inference_kinds = tuple(kind for kind in evidence.CLAIM_TYPES if evidence.is_inference(kind))
    for claim in _claims(bundle):
        kind = _text(claim.get('claimType') or claim.get('type'))
        is_inference = (kind in inference_kinds) if inference_kinds is not None else (
            kind in ('inference', 'recommendation'))
        if is_inference and _text(claim.get('stanceOrigin')) == 'source-stated' \
                and _text(claim.get('confidence')) in ('high', 'medium', 'low'):
            return {'detected': True, 'detail': f'{claim.get("claimId")}: suy luận/đề xuất khai là nguồn nói'}
    return {'detected': False, 'detail': 'đề xuất nào cũng được khai là suy luận của agent'}


def unlabeled_assumption(bundle):
    """Critic: giả định chưa xác nhận được viết thành câu khẳng định."""
    review = harness_module('research_review')
    label = getattr(review, 'ASSUMPTION_LABEL', '') or FALLBACK_ASSUMPTION_LABEL
    scope = (bundle or {}).get('scope') or {}
    assumed: list[str] = []
    if review is not None:
        assumed = [item['text'] for item in review.scope_brief_items(scope)['assumed']]
    else:
        for field in ('goal', 'purpose'):
            value = scope.get(field)
            if isinstance(value, dict) and _text(value.get('status')) != 'confirmed':
                if _text(value.get('text')):
                    assumed.append(_text(value.get('text')))
    report = (bundle or {}).get('report') or {}
    facts = [_text(item) for item in (report.get('facts') or []) if _text(item)]
    for text in assumed:
        folded = _fold(text)
        if not folded:
            continue
        for fact in facts:
            if folded in _fold(fact) and _fold(label) not in _fold(fact):
                return {'detected': True, 'detail': f'giả định {text!r} được viết thành khẳng định không nhãn'}
    return {'detected': False, 'detail': 'mọi giả định đều mang nhãn chưa xác nhận'}


def same_origin_independent(bundle):
    """Verifier: hai bản của CÙNG một nguồn được đếm là hai nguồn độc lập.

    Tín hiệu RIÊNG của loại này là sự thu gọn cụm gốc: một nhận định dẫn từ hai dòng trở lên mà
    số cụm gốc (``research_evidence.cluster_count``) lại ÍT hơn số dòng ⇒ chúng là bản sao/bài viết
    lại của cùng một nguồn, không phải hai nguồn độc lập. Không dùng lại thước "khai cao hơn trần"
    (đó là bộ dò của loại khác) — bắt đúng dấu vết `originCluster` của bundle cấy.
    """
    evidence = harness_module('research_evidence')
    if evidence is None:
        return {'detected': False, 'detail': 'thiếu mã harness để đếm cụm gốc'}
    by_id = {row.get('rowId'): row for row in _rows(bundle)}
    for claim in _claims(bundle):
        cited = _cited(claim, by_id)
        if len(cited) < 2:
            continue
        clusters = evidence.cluster_count(cited)
        if clusters < len(cited):
            return {'detected': True,
                    'detail': (f'{claim.get("claimId")}: {len(cited)} dòng chỉ gộp thành '
                               f'{clusters} cụm gốc — cùng một nguồn, không độc lập')}
    return {'detected': False, 'detail': 'các nguồn được dẫn nằm ở cụm gốc khác nhau'}


def mismatched_benchmark(bundle):
    """Critic: số của hai bàn đo khác điều kiện bị so thẳng với nhau.

    Tín hiệu RIÊNG của loại này là `recordedConditions` của bundle cấy: một nhận định `benchmark`
    dẫn nguồn mà điều kiện đo KHÔNG được ghi lại thì con số không so được với nhau. Không dùng lại
    thước "khai cao hơn trần".
    """
    evidence = harness_module('research_evidence')
    by_id = {row.get('rowId'): row for row in _rows(bundle)}
    for claim in _claims(bundle):
        raw_kind = claim.get('claimType') or claim.get('type')
        kind = (evidence.normalize_claim_type(raw_kind) if evidence is not None
                else _text(raw_kind).casefold().replace('_', '-'))
        if kind != 'benchmark':
            continue
        cited = _cited(claim, by_id)
        if not cited:
            continue
        unrecorded = [row.get('rowId') for row in cited
                      if not _recorded_conditions(row)]
        if unrecorded:
            return {'detected': True,
                    'detail': (f'{claim.get("claimId")}: điều kiện đo không được ghi lại ở '
                               f'{unrecorded} — không so thẳng con số')}
    return {'detected': False, 'detail': 'mọi con số benchmark đều kèm điều kiện đo'} 



DETECTORS = {
    'wrong-number': number_not_backed,
    'unsupported-claim': claim_without_source,
    'misattributed': misattributed,
    'outdated-supports-current': outdated_supports_current,
    'removed-direction': removed_direction,
    'survey-as-proposal': survey_as_proposal,
    'unlabeled-assumption': unlabeled_assumption,
    'same-origin-independent': same_origin_independent,
    'mismatched-benchmark': mismatched_benchmark,
}


# --- đọc bộ ca ---------------------------------------------------------------

def fixture_paths(directory=None) -> list:
    directory = pathlib.Path(directory or FIXTURES)
    return sorted(directory.glob('*.json'))


def load_fixture(path) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def load_fixtures(directory=None) -> list:
    return [load_fixture(path) for path in fixture_paths(directory)]


def detector_for(fixture):
    """Bộ dò của một ca: tên `detector` trước, rồi tới `kind`; không có ⇒ hàm không bao giờ bắt."""
    kind = _text(fixture.get('kind'))
    return (DETECTORS.get(_text(fixture.get('detector'))) or DETECTORS.get(kind)
            or (lambda _bundle: {'detected': False, 'detail': f'không có bộ dò cho {kind!r}'}))


def run_detector(fixture, injected=True) -> dict:
    """Chạy bộ dò của một ca trên bundle đã cấy (``injected=True``) hoặc bundle sạch."""
    detector = detector_for(fixture)
    bundles = fixture.get('injected' if injected else 'clean') or []
    hits = [detector(bundle) for bundle in bundles]
    found = [hit for hit in hits if hit.get('detected')]
    return {'detected': bool(found), 'detail': (found[0]['detail'] if found
                                                else (hits[0]['detail'] if hits else 'bundle rỗng')),
            'hits': len(found), 'total': len(hits)}


# --- chấm offline ------------------------------------------------------------

def run(fixtures=None) -> dict:
    """Chấm cả bộ: tỉ lệ bắt theo loại, tỉ lệ báo sai trên hồ sơ sạch, đạt/không đạt."""
    fixtures = fixtures if fixtures is not None else load_fixtures()
    limits = thresholds()
    kinds: dict[str, dict] = {}
    for fixture in fixtures:
        kind = _text(fixture.get('kind'))
        if not kind:
            continue
        injected = fixture.get('injected') or []
        clean = fixture.get('clean') or []
        detector = detector_for(fixture)
        caught = sum(1 for bundle in injected if detector(bundle)['detected'])
        flagged = sum(1 for bundle in clean if detector(bundle)['detected'])
        row = kinds.setdefault(kind, {'kind': kind, 'reviewer': REVIEWER_OF_KIND.get(kind, ''),
                                      'detector': _text(fixture.get('detector')) or kind,
                                      'caught': 0, 'injectedTotal': 0, 'flaggedClean': 0,
                                      'cleanTotal': 0})
        row['caught'] += caught
        row['injectedTotal'] += len(injected)
        row['flaggedClean'] += flagged
        row['cleanTotal'] += len(clean)
    for row in kinds.values():
        row['catchRate'] = (row['caught'] / row['injectedTotal']) if row['injectedTotal'] else 0.0
        row['falseAlarmRate'] = (row['flaggedClean'] / row['cleanTotal']) if row['cleanTotal'] else 0.0
        threshold_key = THRESHOLD_OF_KIND.get(row['kind'], 'catch')
        row['thresholdKey'] = threshold_key
        row['threshold'] = limits[threshold_key]
        row['pass'] = (row['catchRate'] >= row['threshold']
                       and row['falseAlarmRate'] <= limits['falseAlarm'])
    total_injected = sum(row['injectedTotal'] for row in kinds.values())
    total_clean = sum(row['cleanTotal'] for row in kinds.values())
    flagged_clean = sum(row['flaggedClean'] for row in kinds.values())
    false_alarm = (flagged_clean / total_clean) if total_clean else 0.0
    missing = sorted(set(defect_kinds()) - set(kinds))
    return {'kinds': kinds, 'missingKinds': missing,
            'catchMin': limits['catch'], 'coverageMin': limits['coverage'],
            'falseAlarmMax': limits['falseAlarm'],
            'falseAlarmRate': false_alarm, 'flaggedClean': flagged_clean, 'cleanTotal': total_clean,
            'injectedTotal': total_injected,
            'falseAlarmPass': false_alarm <= limits['falseAlarm'],
            'passed': bool(not missing and kinds and all(row['pass'] for row in kinds.values())
                           and false_alarm <= limits['falseAlarm'])}


def render(report: dict) -> str:
    lines = ['Bộ lỗi cấy sẵn research (§8.4) — bản OFFLINE, không gọi model',
             f'ngưỡng: bắt ≥ {report["catchMin"]:.2f} (dữ kiện/gán sai), '
             f'≥ {report["coverageMin"]:.2f} (hướng bị gỡ), báo sai ≤ {report["falseAlarmMax"]:.2f}',
             '']
    for kind in defect_kinds():
        row = report['kinds'].get(kind)
        if not row:
            lines.append(f'  THIẾU CA   {kind}')
            continue
        lines.append(f'  {"ĐẠT " if row["pass"] else "HỤT "} {kind:<26} '
                     f'{row["reviewer"]:<9} bắt {row["caught"]}/{row["injectedTotal"]} '
                     f'({row["catchRate"]:.2f} ≥ {row["threshold"]:.2f}) '
                     f'báo sai {row["flaggedClean"]}/{row["cleanTotal"]}')
    lines.append('')
    lines.append(f'báo sai trên hồ sơ sạch: {report["falseAlarmRate"]:.2f} '
                 f'({report["flaggedClean"]}/{report["cleanTotal"]})')
    lines.append('KẾT LUẬN: ' + ('ĐẠT' if report['passed'] else 'KHÔNG ĐẠT'))
    return '\n'.join(lines)


# --- đường LIVE, tách rời hẳn -----------------------------------------------

def live_briefs(fixtures=None) -> list:
    """Prompt cho bên soát thật, dựng TẤT ĐỊNH từ chính bộ ca — không gọi gì cả."""
    review = harness_module('research_review')
    out: list[dict] = []
    for fixture in (fixtures if fixtures is not None else load_fixtures()):
        kind = _text(fixture.get('kind'))
        reviewer = REVIEWER_OF_KIND.get(kind, 'verifier')
        for index, bundle in enumerate(fixture.get('injected') or [], start=1):
            out.append({'kind': kind, 'seed': index,
                        'taskKind': {'coverage': 'coverage', 'critic': 'critique'}.get(reviewer,
                                                                                        'evidence'),
                        'expect': _text(fixture.get('expectation')) or
                                  getattr(review, 'ASSUMPTION_LABEL', '') or
                                  'Name the defect you find, with the row or claim it is about.',
                        'prompt': json.dumps(bundle, ensure_ascii=False, sort_keys=True)})
    return out


def run_live(fixtures=None, *, delegate=None, budget_usd=None, env=None) -> dict:
    """Đường THẬT: chỉ qua được khi `BOXFOX_EVAL_ALLOW_SPEND=1` và có ngân sách.

    ``delegate`` là hàm ``(role, taskKind, prompt) -> str`` do người gọi cấp; tệp này không tự
    mở kết nối model, nên một lần chạy thiếu cổng chi tiền vẫn không thể tiêu gì.

    ``catchRate`` ở đây là **TÍN HIỆU KHÓI**: nó đối chiếu cụm từ khoá trên câu trả lời thật
    (``_live_hit``), KHÔNG phải điểm đo chất lượng của bên soát. Muốn chấm chất lượng thì phải
    chấm người (grade) trên câu trả lời, không dùng con số này làm bằng chứng.
    """
    gate = guard.check(budget_usd, env)
    if not gate['allowed']:
        return {'allowed': False, 'reason': gate['reason'], 'gate': gate, 'results': []}
    if delegate is None:
        raise ValueError('LIVE_DELEGATE_REQUIRED: đường live cần một hàm delegate(role, taskKind, prompt)')
    results = []
    expected_total = 0
    caught = 0
    for brief in live_briefs(fixtures):
        role = 'research-review'
        answer = delegate(role, brief['taskKind'], brief['prompt'])
        found = _live_hit(brief['kind'], answer)
        expected_total += 1
        caught += 1 if found else 0
        results.append({'kind': brief['kind'], 'seed': brief['seed'], 'role': role,
                        'taskKind': brief['taskKind'], 'found': found,
                        'answerChars': len(_text(answer))})
    return {'allowed': True, 'reason': '', 'gate': gate, 'results': results,
            'catchRate': (caught / expected_total) if expected_total else 0.0,
            'caught': caught, 'total': expected_total,
            'smoke': True, 'signal': 'smoke',
            'note': ('catchRate là TÍN HIỆU KHÓI (đối chiếu cụm từ khoá trên câu trả lời thật), '
                     'không phải điểm đo chất lượng của bên soát')}


def _live_hit(kind: str, answer) -> bool:
    """Bên soát TRẢ LỜI có nêu đúng loại lỗi không (so CỤM TỪ đặc trưng của loại lỗi).

    Từ khoá ở mức CỤM TỪ, không phải từ đơn: một bài soát tiếng Việt chung chung (có "số", "so
    sánh") KHÔNG được tính là bắt lỗi. Vì vậy ``catchRate`` của đường live chỉ là TÍN HIỆU KHÓI —
    đối chiếu từ khoá trên câu trả lời thật — chứ không phải điểm đo chất lượng của bên soát.
    """
    text = _fold(answer)
    if not text:
        return False
    keywords = {
        'wrong-number': ('số không khớp', 'số không có trong', 'number mismatch', 'số sai'),
        'unsupported-claim': ('không có nguồn', 'thiếu nguồn', 'unsupported claim', 'no backing',
                              'không có dòng sổ'),
        'misattributed': ('gán sai', 'sai nguồn', 'misattribut', 'gán cho nguồn khác'),
        'outdated-supports-current': ('nguồn cũ', 'ngoài cửa sổ', 'stale current', 'outdated source'),
        'removed-direction': ('thiếu hướng', 'bỏ hướng', 'missing direction', 'hướng bị gỡ'),
        'survey-as-proposal': ('đề xuất của chính mình', 'suy luận khai là nguồn',
                               'trình như đề xuất', 'survey as proposal'),
        'unlabeled-assumption': ('giả định chưa xác nhận', 'không nhãn', 'unlabeled assumption',
                                 'giả định không nhãn'),
        'same-origin-independent': ('cùng một nguồn', 'cùng nguồn', 'không độc lập', 'same origin',
                                    'một cụm gốc'),
        'mismatched-benchmark': ('khác điều kiện', 'điều kiện đo', 'so sánh sai điều kiện',
                                 'benchmark condition', 'không cùng điều kiện'),
    }.get(kind, ())
    # Cả hai vế đều đã bỏ dấu: bên soát có thể trả lời có dấu hoặc không.
    return any(_fold(word) in text for word in keywords)


# --- CLI ---------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Đo các vai soát bằng bộ lỗi cấy sẵn (§8.4)')
    parser.add_argument('--fixtures', default=str(FIXTURES), help='thư mục bộ ca')
    parser.add_argument('--live', action='store_true',
                        help='giao cho bên soát THẬT (cần BOXFOX_EVAL_ALLOW_SPEND=1 + ngân sách)')
    parser.add_argument('--budget-usd', type=float, default=None, help='ngân sách đường live')
    parser.add_argument('--json', action='store_true', help='in kết quả dạng JSON')
    args = parser.parse_args(argv)
    fixtures = load_fixtures(args.fixtures)
    if not args.live:
        report = run(fixtures)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else render(report))
        return 0 if report['passed'] else 1
    gate = guard.check(args.budget_usd)
    if not gate['allowed']:
        print(guard.rendered_refusal(gate, guard.missing_connection()))
        return 2
    print('Đường LIVE cần một hàm `delegate` — dùng `run_live(fixtures, delegate=...)` trong mã.')
    print('LƯU Ý: `catchRate` của đường live là TÍN HIỆU KHÓI (đối chiếu cụm từ khoá trên câu '
          'trả lời thật), không phải điểm đo chất lượng của bên soát.')
    print(render(run(fixtures)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
