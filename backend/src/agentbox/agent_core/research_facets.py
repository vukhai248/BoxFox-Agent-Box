"""Bản đồ bao phủ và điểm bão hoà cho research v2 (P2, §5.5).

Tệp **thuần**: không I/O, không `self`. Người gọi (run, cổng chất lượng, bộ đánh giá) đọc/ghi hàng
qua `SessionStore.facet_*`, còn phép tính nằm ở đây.

Ba câu hỏi tệp này trả lời:

1. **Đã khảo sát những hướng nào?** — `new_facet`/`normalize_facet`/`facet_from_survey` dựng facet
   kèm `seedSource` (survey / scope / citation-cluster / agent) để giao diện nói được vì sao facet
   có mặt.
2. **Đã bão hoà chưa?** — `saturation_state` đọc **nhật ký tìm**, không dò từ khoá trong văn bản:
   `last_new_ratio = relevant_new / results`, hai sóng liên tiếp dưới ngưỡng ⇒ `saturated`. Dòng
   không mang số đo (`relevant_*`) là **chưa đo**, không phải 0 — nó không được tính vào luật bão hoà.
3. **Được dừng chưa?** — `stop_checks` gói bốn điều kiện dừng của §5.5 thành danh sách chặn có mã.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable, Mapping, Sequence

from . import limits

#: Loại facet: hướng/nhóm phương pháp, ứng dụng, thước đo, chủ thể, giai đoạn, sản phẩm kèm theo.
FACET_KINDS = ('direction', 'application', 'benchmark', 'actor', 'period', 'artifact')
#: Trạng thái khảo sát của một facet.
FACET_STATUSES = ('unexplored', 'searched', 'saturated', 'thin', 'blocked', 'out-of-scope')
#: Nguồn gốc facet — giao diện hiện trường này.
FACET_SEEDS = ('survey', 'scope', 'citation-cluster', 'agent')
#: Trạng thái được coi là "không cần khảo sát thêm" khi xét điểm dừng.
CLOSED_STATUSES = ('saturated', 'blocked', 'out-of-scope')
#: Trần số vòng săn trích dẫn liên tiếp không thêm bài mới (§5.5, #6008).
CITATION_CHASE_STOP_ROUNDS = limits.RESEARCH_CITATION_CHASE_STOP_ROUNDS

_PRIORITIES = ('high', 'medium', 'low')


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ('' if value is None else str(value).strip())


def fold_label(value: Any) -> str:
    """Chuẩn hoá nhãn để băm: gộp khoảng trắng, bỏ dấu, viết thường."""
    text = re.sub(r'\s+', ' ', _text(value)).casefold()
    decomposed = unicodedata.normalize('NFD', text)
    stripped = ''.join(char for char in decomposed if unicodedata.category(char) != 'Mn')
    return unicodedata.normalize('NFC', stripped).strip()


def facet_id_for(label: Any) -> str:
    """Khoá facet từ nhãn: `'f-' + sha1(nhãn đã gộp dấu)[:12]` — ổn định giữa các lượt."""
    digest = hashlib.sha1(fold_label(label).encode('utf-8')).hexdigest()
    return 'f-' + digest[:12]


def _as_list(value: Any) -> list:
    if isinstance(value, (list, tuple, set)):
        return [item for item in value if item not in (None, '')]
    if value in (None, ''):
        return []
    return [value]


def _clean_term(value: Any, source: str = '') -> dict:
    """Một từ khoá kèm nguồn gốc: `{'text','source'}`."""
    if isinstance(value, Mapping):
        text = _text(value.get('text') or value.get('term') or value.get('value'))
        origin = _text(value.get('source') or value.get('seedSource') or source)
        return {'text': text, 'source': origin} if text else {}
    text = _text(value)
    return {'text': text, 'source': source} if text else {}


def normalize_terms(value: Any, *, source: str = '') -> list:
    """Danh sách từ khoá đã chuẩn hoá, bỏ trùng theo `(text, source)` và giữ thứ tự gặp."""
    out, seen = [], set()
    for item in _as_list(value):
        term = _clean_term(item, source)
        if not term:
            continue
        key = (fold_label(term['text']), term['source'])
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _one_of(value: Any, allowed: Sequence[str], default: str) -> str:
    text = re.sub(r'\s+', '-', _text(value).casefold())
    return text if text in allowed else default


def normalize_facet(value: Any) -> dict:
    """Điền mặc định và cắt chuỗi cho một facet; lạ ⇒ giá trị an toàn (không bao giờ ném)."""
    raw = dict(value) if isinstance(value, Mapping) else {}
    label = _text(raw.get('label') or raw.get('title') or raw.get('name'))
    facet_id = _text(raw.get('facetId') or raw.get('facet_id')) or facet_id_for(label)
    seed = _one_of(raw.get('seedSource') or raw.get('seed_source'), FACET_SEEDS, 'agent')
    terms = normalize_terms(raw.get('terms'), source=seed)
    try:
        counts = int(raw.get('evidenceCount') or raw.get('evidence_count') or 0)
    except (TypeError, ValueError):
        counts = 0
    try:
        clusters = int(raw.get('originClusters') or raw.get('origin_clusters') or 0)
    except (TypeError, ValueError):
        clusters = 0
    try:
        ratio = float(raw.get('lastNewRatio') if raw.get('lastNewRatio') is not None
                      else raw.get('last_new_ratio', -1.0))
    except (TypeError, ValueError):
        ratio = -1.0
    return {'facetId': facet_id, 'questionId': _text(raw.get('questionId') or raw.get('question_id')),
            'label': label,
            'kind': _one_of(raw.get('kind'), FACET_KINDS, 'direction'),
            'terms': terms,
            'priority': _one_of(raw.get('priority'), _PRIORITIES, 'medium'),
            'status': _one_of(raw.get('status'), FACET_STATUSES, 'unexplored'),
            'seedSource': seed,
            'evidenceCount': max(counts, 0), 'originClusters': max(clusters, 0),
            'lastNewRatio': ratio, 'note': _text(raw.get('note'))}


def new_facet(label: Any, *, kind: Any = 'direction', seed: Any = 'agent', question_id: Any = '',
              terms: Any = (), priority: Any = 'medium', status: Any = 'unexplored',
              note: Any = '') -> dict:
    """Facet mới, khoá tính từ nhãn, từ khoá mang nguồn gốc."""
    return normalize_facet({'label': label, 'kind': kind, 'seedSource': seed,
                            'questionId': question_id, 'terms': normalize_terms(terms, source=_text(seed)),
                            'priority': priority, 'status': status, 'note': note})


def merge_terms(facet: Any, new_terms: Any) -> dict:
    """Thêm từ khoá mới vào facet, giữ nguồn gốc từng từ; trả facet đã cập nhật.

    Khoá `addedTerms` cho biết lượt này thêm được gì — nhánh con trả `newTerms`, orchestrator gọi
    hàm này rồi ghi lại facet.
    """
    merged = normalize_facet(facet)
    source = merged['seedSource']
    before = {(fold_label(term['text']), term['source']) for term in merged['terms']}
    seen_text = {fold_label(term['text']) for term in merged['terms']}
    added = []
    for raw in _as_list(new_terms):
        term = _clean_term(raw, source)
        if not term:
            continue
        key = (fold_label(term['text']), term['source'])
        # Từ trần (không nêu nguồn) chỉ cần trùng chữ là coi như đã có; từ có nguồn riêng thì
        # giữ cả hai vì nguồn gốc là thông tin, không phải bản sao.
        bare = not isinstance(raw, Mapping)
        if key in before or (bare and fold_label(term['text']) in seen_text):
            continue
        before.add(key)
        seen_text.add(fold_label(term['text']))
        merged['terms'].append(term)
        added.append(term)
    merged['addedTerms'] = added
    return merged


# --- bão hoà ----------------------------------------------------------------

def _log_field(row: Any, *names: str, default: Any = None) -> Any:
    if not isinstance(row, Mapping):
        return default
    for name in names:
        if name in row and row[name] is not None:
            return row[name]
    return default


def _relevant_new(row: Any) -> Any:
    """Số \"mới và liên quan\" của một dòng nhật ký, hoặc `None` khi dòng KHÔNG mang số đo.

    Khác biệt này là chủ ý: `search_store.log_search` mặc định cột `relevant_new` về 0, nên một
    dòng thiếu số đo (nhà ghi khác, dòng cũ, dữ liệu dựng tay) mà bị đọc thành 0 sẽ khiến MỌI facet
    bão hoà sau hai sóng (`finding 1`). Dòng thiếu số đo phải là \"chưa đo\", không phải \"không có gì mới\".
    """
    if not isinstance(row, Mapping):
        return None
    for name in ('relevantNew', 'relevant_new'):
        if name in row and row[name] is not None:
            return row[name]
    return None


def _ratio(row: Any) -> float | None:
    """`relevant_new / results` của một dòng; `None` khi dòng chưa có số đo (KHÔNG phải 0.0)."""
    new_raw = _relevant_new(row)
    if new_raw is None:
        return None
    try:
        results = int(_log_field(row, 'results', default=0) or 0)
    except (TypeError, ValueError):
        results = 0
    try:
        new = int(new_raw or 0)
    except (TypeError, ValueError):
        new = 0
    if results <= 0:
        return 0.0 if new <= 0 else 1.0
    return max(0.0, min(1.0, new / float(results)))


def _stamp(row: Any) -> float:
    value = _log_field(row, 'created', 'createdAt', 'created_at', default=0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _named_facets(facets: Any) -> list:
    """Facet đã chuẩn hoá, bỏ hàng không có nhãn (hàng rác không được kể vào bao phủ)."""
    out = []
    for item in (facets if isinstance(facets, (list, tuple)) else []):
        row = normalize_facet(item)
        if not row['label']:
            continue
        out.append(row)
    return out


def saturation_state(rows: Any, *, waves: int = limits.RESEARCH_SATURATION_WAVES,
                     threshold: float = limits.RESEARCH_SATURATION_NEW_RATIO) -> dict:
    """Trạng thái bão hoà của **một** facet từ các bản ghi nhật ký tìm (cũ → mới).

    `waves` sóng liên tiếp cuối cùng có `relevant_new / results` dưới `threshold` ⇒ `saturated`.
    Dòng **thiếu số đo** (`relevant_*`) bị bỏ qua: chưa đo được thì không được tính là \"sóng lặng\".
    """
    ordered = [row for row in (rows if isinstance(rows, (list, tuple)) else []) if isinstance(row, Mapping)]
    ordered = sorted(ordered, key=_stamp) if any(_stamp(row) for row in ordered) else list(ordered)
    ratios = [ratio for ratio in (_ratio(row) for row in ordered) if ratio is not None]
    limit = max(int(waves or 0), 1)
    below = 0
    for ratio in reversed(ratios):
        if ratio < float(threshold):
            below += 1
        else:
            break
    if not ordered:
        status = 'unexplored'
    elif below >= limit and len(ratios) >= limit:
        status = 'saturated'
    else:
        status = 'searched'
    return {'status': status, 'waves': below, 'ratios': ratios,
            'lastRatio': ratios[-1] if ratios else -1.0}


def saturation_from_log(log_rows: Any, *, research_id: Any = '') -> dict:
    """Bão hoà theo từng facet, đọc thẳng từ `search_store.search_log()` (§5.5).

    Bản ghi nhận cả camelCase (`facetId`, `relevantNew`) và snake_case. Bản ghi không có facet bị
    bỏ khỏi phần `facets` nhưng vẫn vào `overall` — nhật ký cấp run cũng phải nói được điều gì.
    """
    wanted = _text(research_id)
    grouped, overall = {}, []
    for row in (log_rows if isinstance(log_rows, (list, tuple)) else []):
        if not isinstance(row, Mapping):
            continue
        row_run = _text(_log_field(row, 'researchId', 'research_id', default=''))
        if wanted and row_run and row_run != wanted:
            continue
        overall.append(row)
        facet_id = _text(_log_field(row, 'facetId', 'facet_id', default=''))
        if not facet_id:
            continue
        grouped.setdefault(facet_id, []).append(row)
    facets = {facet_id: saturation_state(rows) for facet_id, rows in grouped.items()}
    return {'facets': facets, 'overall': saturation_state(overall),
            'facetIds': sorted(facets)}


# --- bản đồ bao phủ và điểm dừng --------------------------------------------

def coverage_payload(facets: Any, *, questions: Any = (), citations: Any = None) -> dict:
    """Gói bao phủ để ghi `v<N>-coverage.json` và để hiện trên thẻ báo cáo."""
    rows = _named_facets(facets)
    counts = {status: 0 for status in FACET_STATUSES}
    for row in rows:
        counts[row['status']] = counts.get(row['status'], 0) + 1
    counts['total'] = len(rows)
    unexplored = [row['label'] or row['facetId'] for row in rows if row['status'] == 'unexplored']
    thin = [row['label'] or row['facetId'] for row in rows if row['status'] == 'thin']
    blocked = [row['label'] or row['facetId'] for row in rows if row['status'] == 'blocked']
    open_questions, high_questions = [], 0
    for question in (questions if isinstance(questions, (list, tuple)) else []):
        if not isinstance(question, Mapping):
            continue
        importance = _one_of(question.get('importance'), _PRIORITIES, 'medium')
        state = _one_of(question.get('state') or question.get('status'), ('open', 'answered', 'contested',
                                                                          'blocked', 'unknown'), 'open')
        if importance == 'high':
            high_questions += 1
            if state not in ('answered', 'contested', 'blocked'):
                open_questions.append(_text(question.get('questionId') or question.get('id')
                                            or question.get('text')))
    chase = {'rounds': 0, 'stalledRounds': 0, 'stopRounds': CITATION_CHASE_STOP_ROUNDS}
    if isinstance(citations, Mapping):
        for key, target in (('rounds', 'rounds'), ('stalledRounds', 'stalledRounds'),
                            ('stalled_rounds', 'stalledRounds')):
            if key in citations and citations[key] is not None:
                try:
                    chase[target] = int(citations[key])
                except (TypeError, ValueError):
                    continue
    return {'facets': rows, 'counts': counts, 'unexplored': unexplored, 'thin': thin,
            'blocked': blocked,
            'questions': {'high': high_questions, 'open': [item for item in open_questions if item]},
            'citationChase': chase}


def _topic(facet: Mapping) -> str:
    label = _text(facet.get('label'))
    return label or _text(facet.get('facetId'))


def stop_checks(facets: Any, questions: Any = (), *, coverage_issues: Any = (), budget: Any = None,
                stalled_waves: int = 0) -> dict:
    """Bốn điều kiện dừng của §5.5, trả về dạng máy đọc được.

    * `blockers`: việc **phải** xong mới được kết luận đủ (câu hỏi quan trọng, facet, phát hiện
      bao phủ còn treo).
    * `partial`: hết ngân sách / chạm trần cứng / hai vòng liên tiếp không tiến — run được dừng
      nhưng phải ghi `partial` kèm lý do.
    """
    rows = _named_facets(facets)
    reasons, blockers = [], []

    for question in (questions if isinstance(questions, (list, tuple)) else []):
        if not isinstance(question, Mapping):
            continue
        if _one_of(question.get('importance'), _PRIORITIES, 'medium') != 'high':
            continue
        state = _one_of(question.get('state') or question.get('status'),
                        ('open', 'answered', 'contested', 'blocked', 'unknown'), 'open')
        if state in ('answered', 'contested'):
            continue
        if state == 'blocked' and _text(question.get('reason')):
            continue
        blockers.append({'code': 'research-question-open',
                         'detail': _text(question.get('questionId') or question.get('id')
                                         or question.get('text')) or 'câu hỏi quan trọng'})

    for facet in rows:
        status, topic = facet['status'], _topic(facet)
        if status in CLOSED_STATUSES:
            continue
        if status == 'thin' and _text(facet.get('note')):
            continue
        blockers.append({'code': 'research-facet-open', 'detail': '%s (%s)' % (topic, status)})

    open_issues = []
    for issue in (coverage_issues if isinstance(coverage_issues, (list, tuple)) else []):
        if not isinstance(issue, Mapping):
            continue
        if issue.get('resolved') is True:
            continue
        if _text(issue.get('status')).casefold() in ('done', 'resolved', 'closed'):
            continue
        open_issues.append(issue)
    if open_issues:
        for issue in open_issues:
            blockers.append({'code': 'research-coverage-open',
                             'detail': _text(issue.get('detail') or issue.get('label')
                                             or issue.get('kind')) or 'hướng bị thiếu'})

    partial = False
    if stalled_waves and int(stalled_waves) >= 2:
        partial = True
        reasons.append('Hai vòng liên tiếp không tiến — dừng run và ghi `partial`.')
    if isinstance(budget, Mapping):
        if budget.get('exhausted') or budget.get('hardCeiling') or budget.get('hard_ceiling'):
            partial = True
            reasons.append('Hết ngân sách hoặc chạm trần cứng — ghi `partial` kèm lý do.')

    ready = not blockers
    if ready:
        reasons.append('Mọi câu hỏi quan trọng đã xử lý, mọi facet đã đóng, không còn phát hiện bao phủ.')
    return {'ready': ready, 'reasons': reasons, 'blockers': blockers, 'partial': partial,
            'counts': {'facets': len(rows), 'openFacets': len([b for b in blockers
                                                               if b['code'] == 'research-facet-open'])},
            'stalledWaves': int(stalled_waves or 0)}


def facet_from_survey(entry: Any) -> dict:
    """Một mục trong mục lục của tổng quan → facet `seed='survey'`.

    Đây là đường dựng bản đồ **không** phụ thuộc suy nghĩ của agent (§5.5 bước 1): phân loại hướng
    lấy từ bài tổng quan, có nguồn, nên người đọc soi lại được.
    """
    raw = dict(entry) if isinstance(entry, Mapping) else {}
    label = _text(raw.get('label') or raw.get('title') or raw.get('heading') or raw.get('text'))
    kind = _one_of(raw.get('kind'), FACET_KINDS, 'direction')
    terms = normalize_terms(raw.get('terms'), source='survey')
    if not terms and label:
        terms = normalize_terms([label], source='survey')
    note = _text(raw.get('note'))
    source_url = _text(raw.get('url') or raw.get('sourceUrl'))
    if source_url:
        note = (note + ' · ' if note else '') + source_url
    return normalize_facet({'label': label, 'kind': kind, 'seedSource': 'survey',
                            'questionId': _text(raw.get('questionId') or raw.get('question_id')),
                            'terms': terms, 'priority': raw.get('priority') or 'medium',
                            'status': 'unexplored', 'note': note})
