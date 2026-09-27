"""The C1-C8 output-quality rubric: scales, anchors and aggregate rules.

Source of truth is `docs/plan/agent-output-quality-plan.md`:

* §2 — the eight dimensions, the 0-2 scale, the hard gate, the report bands.
* §5 — which layer is allowed to score which dimension (the machine oracle may
  only touch C1/C5/C6; C2/C3/C4/C7/C8 belong to the LLM judge).
* §6 — the aggregates a report must carry.

Everything here is data plus pure functions: no model, no network, no clock.
The plan's own numbers are kept in the strings so a reader can check them
against the document instead of trusting this file.
"""
from __future__ import annotations

import statistics
from typing import Any, Iterable, Sequence

# §2: "thang 0-2 (0 = thiếu/sai, 1 = có nhưng mờ, 2 = đạt rõ)".
SCALE: dict[int, str] = {
    0: 'thiếu hoặc sai',
    1: 'có nhưng mờ',
    2: 'đạt rõ',
}
MIN_LEVEL, MAX_LEVEL = 0, 2
MAX_TOTAL = 8 * MAX_LEVEL  # 16

# §2 levels 0 and 1 are shared by every dimension (the plan defines them once);
# level 2 is the per-dimension anchor written in the plan's table.
DIMENSIONS: tuple[dict[str, Any], ...] = (
    {
        'code': 'C1',
        'name': 'Đúng yêu cầu',
        'level2': 'Trả lời đúng câu hỏi/đúng artifact được giao, không lệch phạm vi',
        'layer': 1,
        'evidence': 'diff/file/artifact so với yêu cầu trong fixture',
    },
    {
        'code': 'C2',
        'name': 'Bằng chứng',
        'level2': 'Mỗi khẳng định kỹ thuật kèm đường dẫn file, lệnh, hoặc đầu ra quan sát được',
        'layer': 2,
        'evidence': 'đường dẫn + lệnh + đầu ra tồn tại thật',
    },
    {
        'code': 'C3',
        'name': 'Kiểm chứng',
        'level2': ('Có lệnh/bước tự kiểm và kết quả mong đợi; hoặc nói rõ chưa kiểm chứng được '
                   'vì lý do gì'),
        'layer': 2,
        'evidence': 'lệnh kiểm tra + kết quả mong đợi trong đầu ra',
    },
    {
        'code': 'C4',
        'name': 'Nguồn ngoài',
        'level2': ('Khẳng định ngoài hệ thống có nguồn cụ thể (URL, chương tài liệu); nếu mạng tắt '
                   'thì ghi rõ không lấy được nguồn'),
        'layer': 2,
        'evidence': 'nguồn cụ thể hoặc câu nói rõ không truy cập được',
    },
    {
        'code': 'C5',
        'name': 'Cấu trúc hợp đồng',
        'level2': 'Đúng các mục đã yêu cầu (plan/sub-agent contract), không thiếu mục bắt buộc',
        'layer': 1,
        'evidence': 'các mục bắt buộc có mặt (ví dụ Findings/Evidence/Verification/Limitations)',
    },
    {
        'code': 'C6',
        'name': 'Không lặp, không nhiễu',
        'level2': 'Không lặp khối văn bản, không lặp câu, không dán lại nguyên văn nhiều lần',
        'layer': 1,
        'evidence': 'đo trùng lặp khối/câu trên văn bản đầu ra',
    },
    {
        'code': 'C7',
        'name': 'Trung thực về giới hạn',
        'level2': 'Nêu phần chưa làm, phần rủi ro, phần giả định; không nhận đã xong khi chưa',
        'layer': 2,
        'evidence': 'mục rủi ro/giới hạn/giả định có nội dung thật',
    },
    {
        'code': 'C8',
        'name': 'Hiệu quả',
        'level2': ('Số bước, token, thời gian nằm trong ngân sách hợp lý cho việc đó (không tua lại '
                   'vô ích)'),
        'layer': 2,
        'evidence': 'bước/token/thời gian đo từ nhật ký hệ thống so với trần',
    },
)
DIMENSION_CODES: tuple[str, ...] = tuple(item['code'] for item in DIMENSIONS)
DIMENSION_BY_CODE: dict[str, dict[str, Any]] = {item['code']: item for item in DIMENSIONS}

# §5 lớp 1 (oracle máy) chấm C1/C5/C6; lớp 2 (giám khảo LLM) chấm C2/C3/C4/C7/C8.
LAYER1_DIMENSIONS: tuple[str, ...] = tuple(item['code'] for item in DIMENSIONS if item['layer'] == 1)
LAYER2_DIMENSIONS: tuple[str, ...] = tuple(item['code'] for item in DIMENSIONS if item['layer'] == 2)

# §2: "C2 = 0 hoặc C7 = 0 thì đầu ra bị coi là 'chưa đạt' dù tổng điểm cao".
HARD_GATE_DIMENSIONS: tuple[str, ...] = ('C2', 'C7')
HARD_GATE_MIN = 1

# §2: "≥ 13 đạt tốt, 9-12 đạt có điều kiện, ≤ 8 chưa đạt".
BANDS: tuple[tuple[int, str], ...] = ((13, 'đạt tốt'), (9, 'đạt có điều kiện'), (0, 'chưa đạt'))
PASS_MIN_TOTAL = 9  # §6: pass = qua điều kiện cứng VÀ tổng điểm ≥ 9


# ------------------------------------------------------------------ oracle máy (R1–R12)
#
# Đây là khối hằng **RIÊNG** của bộ ca research R1–R12 (`docs/plan/v27/subplans/flow.md` §7.2
# + `docs/plan/v27/research-rework.md` §5). Nó KHÔNG phải chiều chất lượng C1–C8, không đổi
# `HARD_GATE_DIMENSIONS`, và không đi vào `MAX_TOTAL`. Mỗi tên dưới đây là một hàm thuần
# trong `scripts/eval/research_checks.py` (khối "oracle máy cho bộ ca research R1–R12"),
# trả `{name, ok, detail}` và chạy được hoàn toàn offline.
RESEARCH_CHECKS: tuple[str, ...] = (
    'dossier_frontmatter_present',
    'sources_opened',
    'tier_recorded',
    'tier_recorded_default',
    'brief_notice_present',
    'branch_files_exist',
    'dossier_files_exist',
    'branch_count_at_most',
    'claims_have_sources',
    'read_beyond_first_chunk',
    'no_snippet_cited_as_read',
    'no_unread_snippet',
    'citation_chase_logged',
    'saturation_logged',
    'conflicts_file_exists',
    'review_file_exists',
    'critique_file_exists',
    'conflict_row_present',
    'dual_source_declared',
    'blocked_source_recorded',
    'no_fabricated_url',
    'tables_from_structured_source',
    'gap_labelled_as_signal_unverified',
    'wave_branch_ceiling_respected',
    'milestone_ceiling_declared',
    'hard_ceiling_reported',
    'owner_views_three_labels',
    'modules_present',
)

#: Bộ ca R và oracle máy của từng ca — cột "Oracle máy (layer1_checks)" của flow §7.1, cộng
#: bốn ca R8–R12 của `docs/plan/v27/research-rework.md` §5. Dùng để kiểm một fixture có ghim
#: đúng những oracle mà ca của nó cần, thay vì ghim tên bằng tay ở ba chỗ.
RESEARCH_CASE_CHECKS: dict[str, tuple[str, ...]] = {
    'R1': ('dossier_frontmatter_present', 'sources_opened', 'tier_recorded'),
    'R2': ('branch_files_exist', 'dossier_files_exist', 'branch_count_at_most', 'claims_have_sources'),
    'R3': ('read_beyond_first_chunk', 'no_snippet_cited_as_read'),
    'R4': ('citation_chase_logged', 'saturation_logged', 'conflicts_file_exists', 'critique_file_exists'),
    'R5': ('conflict_row_present', 'dual_source_declared'),
    'R6': ('tier_recorded_default', 'brief_notice_present'),
    'R7': ('blocked_source_recorded', 'no_fabricated_url', 'no_unread_snippet'),
    'R8': ('tables_from_structured_source',),
    'R9': ('gap_labelled_as_signal_unverified',),
    'R10': ('wave_branch_ceiling_respected',),
    'R11': ('milestone_ceiling_declared', 'hard_ceiling_reported'),
    'R12': ('owner_views_three_labels', 'review_file_exists'),
}

#: Năm số của một ca R (flow §7.3) — thang riêng, KHÔNG phải C1–C8 và không cộng vào `MAX_TOTAL`.
RESEARCH_CASE_NUMBERS: tuple[str, ...] = (
    'factual_accuracy', 'citation_precision', 'coverage', 'source_quality', 'efficiency',
)

#: Trần của oracle: ba khoá, không ném, không gọi mạng. Ghi ở đây để người đọc tài liệu thấy
#: hợp đồng trước khi mở `research_checks.py`.
RESEARCH_CHECK_KEYS: tuple[str, ...] = ('name', 'ok', 'detail')

# §6: "không gộp ca hỏng vì hạ tầng vào điểm chất lượng — đó là `infrastructure outcome`".
INFRASTRUCTURE_OUTCOMES: tuple[str, ...] = (
    'network_down',      # mạng đứt
    'rate_limited',      # 429
    'quota_exhausted',   # hết hạn mức
    'upstream_error',    # lỗi nhà cung cấp model
    'harness_error',     # lỗi harness/container
    'timeout_external',  # hết hạn ngoài ngân sách của ca
)

# §5: "lệch > 2 điểm thì chấm lần ba"; §6: "tỷ lệ hai lần chấm lệch ≤ 2 điểm".
JUDGE_AGREEMENT_TOLERANCE = 2


def clamp_level(value: Any) -> int:
    """Coerce a score to the 0-2 envelope (anything else is a caller bug)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f'điểm phải là số nguyên 0-2, nhận được {value!r}')
    number = int(value)
    if float(value) != number:
        raise ValueError(f'điểm phải là số nguyên 0-2, nhận được {value!r}')
    if number < MIN_LEVEL or number > MAX_LEVEL:
        raise ValueError(f'điểm ngoài thang 0-2: {value!r}')
    return number


def normalize_scores(scores: dict[str, Any]) -> dict[str, int]:
    """Validate a full C1-C8 score map; raise when a dimension is missing."""
    missing = [code for code in DIMENSION_CODES if code not in scores]
    if missing:
        raise KeyError('thiếu chiều: ' + ', '.join(missing))
    unknown = [code for code in scores if code not in DIMENSION_BY_CODE]
    if unknown:
        raise KeyError('chiều không có trong rubric: ' + ', '.join(sorted(unknown)))
    return {code: clamp_level(scores[code]) for code in DIMENSION_CODES}


def score_total(scores: dict[str, Any]) -> int:
    """Tổng 8 chiều, 0-16."""
    return sum(normalize_scores(scores).values())


def hard_gate_ok(scores: dict[str, Any]) -> bool:
    """False when C2 or C7 is 0, whatever the total is."""
    normalized = normalize_scores(scores)
    return all(normalized[code] >= HARD_GATE_MIN for code in HARD_GATE_DIMENSIONS)


def verdict(total: int) -> str:
    """Thang quy đổi để báo cáo (§2)."""
    for floor, label in BANDS:
        if total >= floor:
            return label
    return BANDS[-1][1]


def passes(scores: dict[str, Any]) -> bool:
    """§6 pass rate: qua điều kiện cứng VÀ tổng điểm ≥ 9."""
    return hard_gate_ok(scores) and score_total(scores) >= PASS_MIN_TOTAL


def evaluate(scores: dict[str, Any], outcome: str = 'quality') -> dict[str, Any]:
    """One scored output -> the row a scoreboard writes."""
    normalized = normalize_scores(scores)
    total = sum(normalized.values())
    is_infrastructure = outcome in INFRASTRUCTURE_OUTCOMES
    return {
        'scores': normalized,
        'total': total,
        'hardGate': hard_gate_ok(normalized),
        'verdict': verdict(total),
        'pass': (not is_infrastructure) and passes(normalized),
        'outcome': outcome,
        'infrastructure': is_infrastructure,
    }


def repetition_ratio(text: str, window: int = 60, stride: int = 1) -> float:
    """C6 helper: share of sliding windows that repeat a window used earlier.

    Layer 1 needs *something* mechanical for "không lặp khối văn bản". This is a
    documented proxy, not the plan's own wording: slide a `window`-character
    window over the text and count the windows whose exact content appeared
    earlier. A doubled answer (the BUG-26 shape: the tail repeats the head)
    scores around 0.37; ordinary prose with a repeated sentence scores far less.
    `stride > 1` is for very long texts where the O(n) set would be too big.
    """
    if not text or len(text) < window * 2:
        return 0.0
    seen: set[str] = set()
    duplicates = 0
    total = 0
    for offset in range(0, len(text) - window + 1, stride):
        chunk = text[offset:offset + window]
        total += 1
        if chunk in seen:
            duplicates += 1
        else:
            seen.add(chunk)
    return duplicates / total if total else 0.0


def repeat_free(text: str, threshold: float = 0.15) -> bool:
    """C6 level-2-ish test: fewer than `threshold` of the windows repeat.

    The threshold is this script's convention — the plan says "không lặp khối văn
    bản" without a number, so the number is declared here instead of hidden.
    """
    return repetition_ratio(text) < threshold


def _stdev(values: Sequence[float]) -> float | None:
    """Sample standard deviation; None when fewer than two data points (chưa đo)."""
    if len(values) < 2:
        return None
    return statistics.stdev(values)


def dimension_stats(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """§6 'Điểm trung bình theo chiều': mean + độ lệch per dimension.

    Infrastructure rows are excluded here by design (§6) and reported by
    `infrastructure_count`. Empty input yields `chuaDo` entries, never a 0.
    """
    quality = [row for row in rows if not row.get('infrastructure')]
    stats: dict[str, dict[str, Any]] = {}
    for code in DIMENSION_CODES:
        values = [float(normalize_scores(row['scores'])[code]) for row in quality]
        stats[code] = {
            'mean': round(statistics.fmean(values), 3) if values else None,
            'stdev': _stdev(values) if values else None,
            'n': len(values),
        }
    return stats


def pass_rate(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """§6 pass rate, with the denominator stated (quality rows only)."""
    rows = list(rows)
    quality = [row for row in rows if not row.get('infrastructure')]
    passed = sum(1 for row in quality if row.get('pass'))
    return {
        'passed': passed,
        'total': len(quality),
        'rate': round(passed / len(quality), 4) if quality else None,
        'infrastructure': len(rows) - len(quality),
    }


def judge_agreement(pairs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """§5/§6: share of outputs whose two judge passes differ by ≤ 2 points.

    Each item is `{'first': {...scores}, 'second': {...scores}}`. Items that
    differ by more than 2 need a third pass (`needsThirdPass`).
    """
    items = list(pairs)
    agree = 0
    need_third: list[int] = []
    for index, item in enumerate(items):
        delta = abs(score_total(item['first']) - score_total(item['second']))
        if delta <= JUDGE_AGREEMENT_TOLERANCE:
            agree += 1
        else:
            need_third.append(index)
    return {
        'agree': agree,
        'total': len(items),
        'rate': round(agree / len(items), 4) if items else None,
        'needsThirdPass': need_third,
    }


def summarize(rows: Iterable[dict[str, Any]], agreement: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """The §6 aggregate block a scoreboard needs, with 'chưa đo' instead of zero."""
    rows = list(rows)
    quality = [row for row in rows if not row.get('infrastructure')]
    return {
        'passRate': pass_rate(rows),
        'dimensions': dimension_stats(rows),
        'averageTotal': (round(statistics.fmean([row['total'] for row in quality]), 3) if quality else None),
        'totalStdev': _stdev([float(row['total']) for row in quality]),
        'verificationRate': _verification_rate(quality),
        'judgeAgreement': judge_agreement(agreement or []),
        'infrastructureRows': [row for row in rows if row.get('infrastructure')],
    }


def _verification_rate(rows: Sequence[dict[str, Any]]) -> float | None:
    """§6 'Kiểm chứng': share of cases with a self-check or an explicit "chưa kiểm được"."""
    if not rows:
        return None
    ok = sum(1 for row in rows if normalize_scores(row['scores'])['C3'] >= 1)
    return round(ok / len(rows), 4)
