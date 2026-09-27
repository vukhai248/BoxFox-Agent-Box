"""Vai con của research v2 (P3, §5.9/§5.11): kiểu việc, brief do máy dựng, thẻ nhánh và luật soát.

Mô-đun này là chỗ DUY NHẤT trả lời bốn câu hỏi của phase P3:

1. **Kiểu việc** của một nhánh con — chỉ là `taskKind` trên hai vai đã có (`research`,
   `research-review`), không thêm vai mới vào `roles.ROLES` (§5.9). Giá trị lạ ⇒ ném lỗi mang
   `limits.RESEARCH_TASK_KIND_INVALID_CODE`; thiếu ⇒ `limits.RESEARCH_TASK_KIND_DEFAULT`.
2. **Brief của con do RUNTIME dựng** từ `job.state.scope` — mô hình không tự viết yêu cầu. Phần
   "đã xác nhận" chỉ nhận mục `status='confirmed'` **và** `source.kind='user'`; mọi mục còn lại
   đi xuống phần giả định và LUÔN mang nhãn `ASSUMPTION_LABEL`. Hàm `brief_leaks_assumption` là
   khoá máy của luật này (§8.2 M-12).
3. **Chế độ soát** của một run/mức — một nguồn sự thật cho cả runtime lẫn bài kiểm.
4. **Luật soát thuần**: danh mục `issues[].kind`, mẫu trích xuất theo loại nguồn, và cách phân xử
   khi hai bên soát độc lập mâu thuẫn.

Không hàm nào ở đây tự gọi mạng, tự đọc `os.environ` (mọi công tắc nhận `env=` để bài kiểm truyền
thay vì vá `os.environ`) hay tự sửa hồ sơ.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from . import limits, research_facets, research_runtime
from .research_evidence import (CONFIDENCE_RANK, apply_cap, basis_payload,
                                confidence_cap, normalize_claim_type,
                                normalize_source_kind, normalize_stance, origin_cluster,
                                survey_date, window_days)

__all__ = [
    # kiểu việc
    'normalize_task_kind', 'resolve_task_kind',
    # brief do máy dựng
    'ASSUMPTION_LABEL', 'scope_brief_items', 'build_child_brief', 'brief_leaks_assumption',
    # chế độ soát
    'REVIEW_MODES', 'COVERAGE_JOB_KINDS', 'review_modes', 'review_modes_payload',
    # thẻ nhánh
    'apply_branch_report',
    # danh mục phát hiện
    'normalize_issue_kind', 'normalize_issues', 'coverage_label', 'has_unhandled_missing_direction',
    # mẫu trích xuất
    'extraction_fields', 'EXTRACTION_FIELDS',
    # phân xử mâu thuẫn
    'resolve_disagreement',
]

#: Nhãn bắt buộc trước mọi mục CHƯA được người dùng xác nhận (§5.10). Giữ nguyên chữ, có dấu.
ASSUMPTION_LABEL = 'GIẢ ĐỊNH (chưa xác nhận)'

#: Thứ tự công khai của các chế độ soát: bằng chứng → phản biện → bao phủ.
REVIEW_MODES = ('evidence', 'critique', 'coverage')
#: Kiểu việc cần một bên soát riêng về bao phủ hướng (§7 P3, coverage reviewer).
COVERAGE_JOB_KINDS = ('landscape', 'literature-map', 'gap')

#: Trường scope là YÊU CẦU đối tượng (có `status`/`source`) — tách được xác nhận với giả định.
_BRIEF_REQUIREMENT_FIELDS = ('goal', 'purpose', 'exclusions', 'timePolicy')
#: Trần số đoạn của phần "đã xác nhận" trong brief, để một scope lạ không phình prompt con.
_BRIEF_MAX_LINES = 40


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ('' if value is None else str(value).strip())


def _slug(value: Any) -> str:
    return re.sub(r'\s+', ' ', _text(value)).casefold()


# --- 1. kiểu việc của một nhánh con -----------------------------------------

def normalize_task_kind(value: Any, *, default: str = limits.RESEARCH_TASK_KIND_DEFAULT) -> str:
    """`taskKind` hợp lệ hoặc `default` khi thiếu/lạ — KHÔNG ném (dùng cho đường đọc thuần)."""
    text = _slug(value).replace('_', '-').replace(' ', '-')
    return text if text in limits.RESEARCH_BRANCH_KINDS else default


def resolve_task_kind(value: Any, *, default: str = limits.RESEARCH_TASK_KIND_DEFAULT) -> str:
    """`taskKind` của `delegate_task`: thiếu ⇒ mặc định, lạ ⇒ ném lỗi mang mã hợp đồng.

    Thông điệp nêu rõ mã `limits.RESEARCH_TASK_KIND_INVALID_CODE` để runtime/dispatch trả về
    nguyên văn — không để mô hình tự đoán ra một kiểu việc không có trong hợp đồng.
    """
    if _text(value) == '':
        return default
    text = normalize_task_kind(value, default='')
    if text:
        return text
    raise ValueError(f'{limits.RESEARCH_TASK_KIND_INVALID_CODE}: taskKind {value!r} '
                     f'không thuộc {list(limits.RESEARCH_BRANCH_KINDS)}')


# --- 2. brief của con do runtime dựng từ `job.state.scope` -------------------

def _item_text(field: str, raw: Any) -> str:
    """Chuỗi yêu cầu của một mục scope, đã bỏ phần `text` nếu mục là dict."""
    if isinstance(raw, Mapping):
        value = raw.get('text') or raw.get('label') or raw.get('value')
        if _text(value):
            return _text(value)
        if field == 'timePolicy':
            parts = [_text(raw.get('velocity')), _text(raw.get('reason'))]
            parts = [part for part in parts if part]
            return ' — '.join(parts)
        return ''
    return _text(raw)


def _item_status(raw: Any) -> str:
    return _slug(raw.get('status')) if isinstance(raw, Mapping) else ''


def _item_source_kind(raw: Any) -> str:
    if not isinstance(raw, Mapping):
        return ''
    source = raw.get('source')
    if isinstance(source, Mapping):
        return _slug(source.get('kind') or source.get('sourceKind'))
    return _slug(raw.get('sourceKind') or raw.get('source_kind'))


def scope_brief_items(scope: Any) -> dict:
    """Tách yêu cầu trong scope thành `{'confirmed': [...], 'assumed': [...]}`.

    Mục vào phần **đã xác nhận** chỉ khi `status='confirmed'` VÀ `source.kind='user'` — mô hình tự
    khai `confirmed` mà nguồn là agent vẫn bị coi là giả định. Mỗi mục trả
    `{'field','text','status','sourceKind'}`.
    """
    raw = dict(scope) if isinstance(scope, Mapping) else {}
    confirmed: list[dict] = []
    assumed: list[dict] = []
    for field in _BRIEF_REQUIREMENT_FIELDS:
        value = raw.get(field)
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            text = _item_text(field, item)
            if not text:
                continue
            status = _item_status(item) or 'assumed'
            # Không suy hộ: mục chỉ là "người dùng đã xác nhận" khi `source.kind='user'` có thật
            # (§5.10/M-12). Thiếu nguồn ⇒ coi là giả định, đúng chiều an toàn.
            source_kind = _item_source_kind(item) or 'agent'
            row = {'field': field, 'text': text, 'status': status, 'sourceKind': source_kind}
            if status == 'confirmed' and source_kind == 'user':
                confirmed.append(row)
            else:
                assumed.append(row)
    return {'confirmed': confirmed, 'assumed': assumed}


def _scope_context_lines(scope: Mapping) -> list[str]:
    """Các trường phi yêu cầu (nguồn, đầu ra, độ sâu, loại việc) — dữ liệu, không phải yêu cầu."""
    lines: list[str] = []
    for label, key in (('Loại việc', 'jobKinds'), ('Nguồn nhận', 'sourceKinds'),
                       ('Đầu ra', 'outputs'), ('Độ sâu', 'depth')):
        value = scope.get(key)
        if isinstance(value, (list, tuple)):
            text = ', '.join(_text(item) for item in value if _text(item))
        else:
            text = _text(value)
        if text:
            lines.append(f'- {label}: {text}')
    return lines


def _scope_question_lines(scope: Mapping) -> list[str]:
    """Câu hỏi nghiên cứu của run — không phải yêu cầu đã xác nhận, chỉ là đề bài."""
    lines: list[str] = []
    for question in scope.get('questions') or []:
        if not isinstance(question, Mapping):
            continue
        text = _text(question.get('text') or question.get('question'))
        if not text:
            continue
        importance = _text(question.get('importance'))
        lines.append(f'- [{importance or "medium"}] {text}')
    return lines


def build_child_brief(scope: Any, *, question: Any = '', task_kind: Any = None,
                      context: Any = '') -> dict:
    """Dựng brief của nhánh con TỪ `job.state.scope` — mô hình không tự viết yêu cầu.

    `question` là phần DUY NHẤT do cha cấp (câu hỏi cho nhánh); mọi yêu cầu khác lấy từ scope, và
    giả định luôn mang `ASSUMPTION_LABEL`. Trả `{'taskKind','question','confirmed','assumed',
    'lines','text'}`.
    """
    raw = dict(scope) if isinstance(scope, Mapping) else {}
    kind = normalize_task_kind(task_kind)
    items = scope_brief_items(raw)
    lines: list[str] = [f'Nhánh {kind} — yêu cầu lấy từ thẻ phạm vi của run, không do bạn đặt lại.']
    if question and _text(question):
        lines.append('CÂU HỎI CỦA NHÁNH: ' + _text(question))
    if items['confirmed']:
        lines.append('YÊU CẦU ĐÃ XÁC NHẬN (người dùng):')
        lines.extend('- ' + item['text'] for item in items['confirmed'][:_BRIEF_MAX_LINES])
    if items['assumed']:
        lines.append('GIẢ ĐỊNH CỦA AGENT (chưa xác nhận — không phải yêu cầu, có thể sai):')
        lines.extend(f'- {ASSUMPTION_LABEL}: {item["text"]}'
                     for item in items['assumed'][:_BRIEF_MAX_LINES])
    questions = _scope_question_lines(raw)
    if questions:
        lines.append('CÂU HỎI NGHIÊN CỨU CỦA RUN:')
        lines.extend(questions)
    context_lines = _scope_context_lines(raw)
    if context_lines:
        lines.append('BỐI CẢNH (dữ liệu, không phải yêu cầu):')
        lines.extend(context_lines)
    extra = _text(context)
    if extra:
        lines.append('DỮ LIỆU CHA CẤP (không phải yêu cầu):')
        lines.append(extra)
    return {'taskKind': kind, 'question': _text(question),
            'confirmed': [item['text'] for item in items['confirmed']],
            'assumed': [item['text'] for item in items['assumed']],
            'lines': lines, 'text': '\n'.join(lines)}


def brief_leaks_assumption(brief: Any) -> list[str]:
    """Khoá máy (§8.2 M-12): mục giả định nào bị viết thành câu KHẲNG ĐỊNH không nhãn.

    Trả danh sách text rò rỉ; rỗng ⇒ brief không biến giả định thành điều đã xác nhận. Một mục
    giả định xuất hiện trên dòng không mang `ASSUMPTION_LABEL` (kể cả khi nó nằm trong phần "đã
    xác nhận") đều bị coi là rò.
    """
    data = dict(brief) if isinstance(brief, Mapping) else {}
    confirmed = {_text(item) for item in (data.get('confirmed') or [])}
    lines = [_text(line) for line in (data.get('lines') or []) if _text(line)]
    leaked: list[str] = []
    for text in data.get('assumed') or []:
        text = _text(text)
        if not text:
            continue
        if text in confirmed:
            leaked.append(text)
            continue
        for line in lines:
            if text in line and ASSUMPTION_LABEL not in line:
                leaked.append(text)
                break
    return leaked


# --- 3. chế độ soát của một lượt/mức (một nguồn sự thật) --------------------

def _scope(value: Any) -> dict:
    if isinstance(value, Mapping):
        return dict(value.get('scope')) if isinstance(value.get('scope'), Mapping) else dict(value)
    return {}


def _job_kinds(state: Any) -> list[str]:
    scope = _scope(state)
    raw = scope.get('jobKinds')
    if isinstance(raw, (list, tuple)):
        return [_slug(item) for item in raw if _slug(item)]
    return [_slug(raw)] if _slug(raw) else []


_PLANNING_RE = re.compile(r'\b(plan|planning|roadmap)\b|kế hoạch|triển khai', re.I)


def _state_questions(state: Any) -> list[dict]:
    """Câu hỏi của run: `state.questions` trước, rồi `state.scope.questions` — nguồn duy nhất."""
    raw = dict(state) if isinstance(state, Mapping) else {}
    for candidate in (raw.get('questions'), (raw.get('scope') or {}).get('questions')):
        if isinstance(candidate, (list, tuple)):
            return [item for item in candidate if isinstance(item, Mapping)]
    return []


def _needs_evidence(tier: int, state: Any) -> bool:
    """Luật bằng chứng HIỆN CÓ (plan §5.11 dòng 704), giữ nguyên nghĩa:

    mức 3 ⇒ luôn; ≥ 2 câu hỏi quan trọng cao và (≥ 3 câu hỏi hoặc có ý lập kế hoạch) ⇒ luôn;
    từ 2 câu hỏi trở lên ⇒ bằng chứng.
    """
    if tier >= 3:
        return True
    questions = _state_questions(state)
    output = _text((dict(state) if isinstance(state, Mapping) else {}).get('output'))
    high_count = sum(_slug(item.get('importance')) == 'high' for item in questions)
    planning = bool(_PLANNING_RE.search(output))
    if high_count >= 2 and (len(questions) >= 3 or planning):
        return True
    return len(questions) >= 2


def review_modes(tier: Any, state: Any, env: Any = None) -> list[str]:
    """Chế độ soát của một run — nguồn sự thật duy nhất (§5.11, #6072).

    * `critique`: có khi `tier >= 2` **và** công tắc mức-2 đang bật; nếu không thì đúng
      `limits.RESEARCH_TIER_CRITIQUE` (chỉ mức 3) — không có đường thứ hai.
    * `evidence`: theo luật hiện có của `_choose_review_modes` (câu hỏi quan trọng, dùng cho plan).
    * `coverage`: theo loại việc (`landscape`, `literature-map`, `gap`) và LUÔN có ở mức 3.
    """
    try:
        level = int(tier)
    except (TypeError, ValueError):
        level = 0
    scope = _scope(state)
    kinds = _job_kinds(state)
    modes: list[str] = []
    if level >= 2 and limits.research_critique_tier2_enabled(env):
        modes.append('critique')
    elif bool(limits.RESEARCH_TIER_CRITIQUE.get(level, False)):
        modes.append('critique')
    if _needs_evidence(level, state):
        modes.append('evidence')
    if (level >= 3 or any(kind in COVERAGE_JOB_KINDS for kind in kinds)
            or bool(scope.get('coverageRequired'))):
        modes.append('coverage')
    # Giữ thứ tự công khai, bỏ trùng — hợp đồng hiển thị của FE.
    return [mode for mode in REVIEW_MODES if mode in modes]


def review_modes_payload(tier: Any, state: Any, env: Any = None) -> dict:
    """`review_modes` kèm vì sao — để `research_status`/thẻ báo cáo giải thích cho người dùng."""
    modes = review_modes(tier, state, env)
    try:
        level = int(tier)
    except (TypeError, ValueError):
        level = 0
    critique_rule = ('tier>=2' if level >= 2 and limits.research_critique_tier2_enabled(env)
                     else ('tier>=3' if bool(limits.RESEARCH_TIER_CRITIQUE.get(level, False)) else ''))
    return {'modes': modes, 'critiqueRule': critique_rule,
            'coverageJobKinds': list(COVERAGE_JOB_KINDS)}


# --- 4. thẻ nhánh: `research_branch_report` ---------------------------------

def _claim_confidence(raw: Any) -> str:
    return _slug(raw.get('confidence') or raw.get('level'))


def _row_payloads(row_ids: Sequence[str], row_rows: Mapping) -> list[dict]:
    """Mục bằng chứng nội bộ cho `confidence_cap` (đủ trường cần, không lộ nội dung thô)."""
    out: list[dict] = []
    for row_id in row_ids:
        row = row_rows.get(row_id) or {}
        payload = dict(row) if isinstance(row, Mapping) else {}
        payload.setdefault('rowId', row_id)
        out.append(payload)
    return out


def apply_branch_report(rt, session, args):
    """Ghi sổ/thẻ nhánh của một con `research` (công cụ `research_branch_report`, §5.9).

    Chỉ con `research` gọi được. Mọi mức tin cậy đi qua `research_evidence.confidence_cap` — mô
    hình chỉ HẠ được, không nâng quá trần. Trả `{'rowIds','claimIds','facetStatus','coverage'}`.
    """
    if _slug(session.get('role')) != 'research':
        raise PermissionError('research_branch_report chỉ dành cho một nhánh con research')
    sid = session.get('id')
    # Sổ nguồn sống ở phiên GIỮ BRIEF (cha/việc), không ở nhánh con: hỏi cùng một chỗ với P2.
    owner, _child = research_runtime._ledger_owner(rt, session, sid)
    research_cfg = research_runtime.research_config(session) or {}
    research_id = _slug(args.get('researchId') or research_cfg.get('researchId'))
    if not research_id:
        owner_cfg = research_runtime.research_config(rt.store.get(owner) or {}) or {}
        research_id = _slug(owner_cfg.get('researchId'))
    if not research_id:
        raise ValueError(f'{limits.RESEARCH_BRANCH_REPORT_MISSING_CODE}: thiếu researchId')
    job = rt.store.research_job(research_id)
    if not job:
        raise ValueError(f'{limits.RESEARCH_BRANCH_REPORT_MISSING_CODE}: không có run {research_id!r}')
    state = job.get('state') or {}
    scope = state.get('scope') or {}
    question_id = _text(args.get('questionId'))
    if question_id:
        known = {_text(item.get('id') or item.get('questionId'))
                 for item in (state.get('questions') or []) if isinstance(item, Mapping)}
        if known and question_id not in known:
            raise ValueError(f'{limits.RESEARCH_BRANCH_REPORT_MISSING_CODE}: '
                             f'questionId {question_id!r} không thuộc run')

    # 1) Dòng sổ: đi qua đúng đường `source_add` hiện có để không mở đường ghi thứ hai.
    row_ids: list[str] = []
    row_rows: dict[str, dict] = {}
    for item in (args.get('rows') or []):
        if not isinstance(item, Mapping):
            continue
        payload = dict(item)
        payload.setdefault('researchId', research_id)
        if question_id:
            payload.setdefault('questionId', question_id)
        result = research_runtime.source_add(rt, session, payload)
        row_id = _text(result.get('rowId'))
        if not row_id:
            continue
        row_ids.append(row_id)
        stored = rt.store.source_row(owner, row_id) or {}
        merged = dict(payload)
        merged.update(stored if isinstance(stored, Mapping) else {})
        row_rows[row_id] = merged

    # 2) Nhận định: liên kết vào đúng dòng đã ghi, trần tin cậy do máy tính.
    velocity = _slug((scope.get('timePolicy') or {}).get('velocity'))
    days = window_days(velocity)
    # Mốc khảo sát ĐÔNG CỨNG của run là `scope['surveyDate']` — đúng khoá mà
    # `research_runtime._scope_time_window` (và cổng hồ sơ) đọc; `timePolicy.asOf` chỉ còn là
    # đường lùi cho hồ sơ cũ. Hai bên kẹp cùng một mốc, nếu không cùng một nhận định nhận hai mức
    # trần khác nhau (§5.6).
    as_of = (_text(scope.get('surveyDate'))
             or _text((scope.get('timePolicy') or {}).get('asOf')) or survey_date())
    cluster_keys: set[str] = set()
    unnamed_clusters = 0
    claim_ids: list[str] = []
    default_facet = _text(args.get('facetId'))
    for claim in (args.get('claims') or []):
        if not isinstance(claim, Mapping):
            continue
        text = _text(claim.get('text') or claim.get('claim'))
        # Chỉ nhận dòng đã ghi trong CHÍNH lời gọi này: mã lạ không được hồi sinh một nguồn khác.
        cited = [_text(item) for item in (claim.get('rowIds') or claim.get('rows') or [])]
        cited = [item for item in cited if item in row_rows]
        facet_id = _text(claim.get('facetId')) or default_facet
        claim_id = _text(claim.get('claimId'))
        if text and cited:
            # MỌI dòng được dẫn đều vào sổ liên kết: nhận định nhiều nguồn giữ đủ dấu vết (§5.9).
            for row_id in cited:
                link = rt.store.evidence_link(owner, row_id, text, proposed_by=sid,
                                              research_id=research_id)
                claim_id = _text(link.get('claimId')) or claim_id
        if not claim_id:
            continue
        claim_type = normalize_claim_type(claim.get('claimType') or claim.get('type'))
        # Nhận định trong sổ là điều NGUỒN nói (con đã đọc đoạn trích); muốn khai suy luận thì
        # phải nói rõ `stanceOrigin` — nên mặc định ở đây là `source-stated`.
        stance = normalize_stance(claim.get('stanceOrigin') or claim.get('stance')
                                  or 'source-stated')
        cited_rows = _row_payloads(cited, row_rows)
        cap = confidence_cap(claim_type, cited_rows, stance_origin=stance,
                             window_days=days, as_of=as_of,
                             conflict=bool(claim.get('conflict') or claim.get('contested')))
        confidence = apply_cap(_claim_confidence(claim) or 'unknown', cap['cap'])
        rt.store.claim_meta_save(research_id, claim_id, questionId=question_id, facetId=facet_id,
                                 claimType=claim_type, stanceOrigin=stance, confidence=confidence,
                                 confidenceCap=cap['cap'],
                                 basis=basis_payload(claim_type, cited_rows, rule=cap['rule']))
        claim_ids.append(claim_id)
        # Cụm gốc GỘP qua MỌI nhận định: `originClusters` của facet là hợp của các nhận định, không
        # phải giá trị của nhận định cuối cùng có dẫn nguồn (§5.9).
        for entry in cited_rows:
            cluster = origin_cluster(entry)
            if cluster:
                cluster_keys.add(cluster)
            else:
                unnamed_clusters += 1

    # 3) Facet: chỉ ghi khi biết khoá (thẻ phạm vi/người cha cấp) — không tự sinh hướng mới.
    status = _slug(args.get('status'))
    facet_id = _text(args.get('facetId'))
    facet_status = ''
    if facet_id and (status or args.get('newTerms') or row_ids):
        current = rt.store.facet(research_id, facet_id) or {}
        merged = research_facets.merge_terms(current, args.get('newTerms') or [])
        note_parts = [_text(merged.get('note')), _text(args.get('note'))]
        blocked = args.get('blocked') if isinstance(args.get('blocked'), Mapping) else {}
        if _text(blocked.get('url')):
            note_parts.append(f'chặn: {_text(blocked.get("url"))} — {_text(blocked.get("reason"))}')
        leads = [_text(item) for item in (args.get('leads') or []) if _text(item)]
        if leads:
            note_parts.append('hướng mới: ' + '; '.join(leads))
        patch = dict(merged)
        patch['facetId'] = facet_id
        # `label` là thứ `store.facet_save` dùng để suy khoá khi thiếu `facetId`, và là thứ
        # `coverage_payload` đếm — một facet không nhãn bị coi là hàng rác, không vào bao phủ.
        label = _text(args.get('label') or merged.get('label'))
        if label:
            patch['label'] = label
        if _text(args.get('kind')):
            patch['kind'] = _text(args.get('kind'))
        patch['terms'] = merged.get('terms') or []
        patch['evidenceCount'] = max(int(merged.get('evidenceCount') or 0), len(row_ids))
        origin_clusters = len(cluster_keys) + unnamed_clusters
        if origin_clusters:
            patch['originClusters'] = max(int(merged.get('originClusters') or 0), origin_clusters)
        if status:
            patch['status'] = status
        patch['note'] = ' · '.join(part for part in note_parts if part)
        saved = rt.store.facet_save(research_id, patch)
        facet_status = _text(saved.get('status'))
    elif facet_id:
        existing = rt.store.facet(research_id, facet_id) or {}
        facet_status = _text(existing.get('status'))

    coverage = research_facets.coverage_payload(rt.store.facet_list(research_id),
                                                questions=state.get('questions') or [])
    return {'rowIds': row_ids, 'claimIds': claim_ids, 'facetStatus': facet_status,
            'coverage': coverage}


# --- 5. danh mục phát hiện (`issues[].kind`) --------------------------------

_ISSUE_ALIASES = {
    'missing_direction': 'missing-direction', 'missing direction': 'missing-direction',
    'missing-direction-at': 'missing-direction', 'coverage': 'missing-direction',
    'unlabeled_assumption': 'unlabeled-assumption', 'unlabeled assumption': 'unlabeled-assumption',
    'assumption': 'unlabeled-assumption', 'counter_evidence': 'counter-evidence',
    'counter evidence': 'counter-evidence', 'no-backing': 'unsupported',
    'no backing': 'unsupported', 'unsupported-claim': 'unsupported',
    'wrong-source': 'misattributed', 'wrong source': 'misattributed',
    'stale': 'outdated', 'old-source': 'outdated',
}


def normalize_issue_kind(value: Any) -> str:
    """Mã phát hiện hợp lệ, hoặc `''` khi không nhận ra (kind là trường THÊM ĐƯỢC, không bắt buộc)."""
    text = _slug(value).replace('_', '-')
    if text in limits.RESEARCH_ISSUE_KINDS:
        return text
    return _ISSUE_ALIASES.get(text, '')


def normalize_issues(issues: Any, *, max_items: Any = None, text_chars: Any = None) -> list[dict]:
    """Chuẩn hoá `issues` GIỮ `severity` cũ và THÊM `kind` khi nhận ra (§5.9).

    Cùng khuôn `research_runtime._clamp_issues` (severity lạ ⇒ `medium`, text bị cắt) để bản P3
    và bản cũ không lệch nhau; `kind` chỉ xuất hiện khi hợp lệ nên hồ sơ cũ đọc y nguyên.
    """
    limit_items = int(max_items if max_items is not None else limits.RESEARCH_VERIFY_MAX_ISSUES)
    chars = int(text_chars if text_chars is not None else limits.RESEARCH_VERIFY_ISSUE_CHARS)
    out: list[dict] = []
    for item in (issues if isinstance(issues, (list, tuple)) else []):
        if not isinstance(item, Mapping):
            continue
        severity = _slug(item.get('severity'))
        if severity not in ('high', 'medium', 'low'):
            severity = 'medium'
        text = _text(item.get('text'))[:chars]
        fix = _text(item.get('fix'))[:chars]
        row = {'severity': severity, 'text': text, 'fix': fix}
        kind = normalize_issue_kind(item.get('kind'))
        if kind:
            row['kind'] = kind
        out.append(row)
        if len(out) >= limit_items:
            break
    return out


def has_unhandled_missing_direction(issues: Any) -> bool:
    """Có phát hiện `missing-direction` mức `high` CHƯA được xử lý (§5.9) hay không."""
    for item in (issues if isinstance(issues, (list, tuple)) else []):
        if not isinstance(item, Mapping):
            continue
        if (normalize_issue_kind(item.get('kind')) == 'missing-direction'
                and _slug(item.get('severity')) == 'high'
                and not bool(item.get('handled') or item.get('resolved'))):
            return True
    return False


def coverage_label(issues: Any = None, *, verdict: Any = None) -> str:
    """Nhãn phải gắn lên hồ sơ: `limits.RESEARCH_COVERAGE_LABEL` khi còn hướng bị bỏ (§5.9)."""
    if has_unhandled_missing_direction(issues) or _slug(verdict) in ('revise', 'incomplete'):
        return limits.RESEARCH_COVERAGE_LABEL
    return ''


# --- 6. mẫu trích xuất của một nguồn trụ cột ---------------------------------

def _field(key: str, label: str, required: bool = True, where: str = 'body') -> dict:
    return {'key': key, 'label': label, 'required': required, 'where': where}


EXTRACTION_FIELDS = {
    'paper': [_field('title', 'Tên bài', where='head'), _field('authors', 'Nhóm tác giả', where='head'),
              _field('venue', 'Hội nghị/tạp chí', where='head'), _field('year', 'Năm', where='head'),
              _field('claim', 'Nhận định chính'), _field('method', 'Phương pháp'),
              _field('dataset', 'Dữ liệu dùng'), _field('metric', 'Thước đo'),
              _field('result', 'Kết quả (số)'), _field('baseline', 'Mốc so sánh'),
              _field('limits', 'Giới hạn tác giả nêu', required=False),
              _field('code', 'Liên kết mã/dữ liệu', required=False, where='link')],
    'blog': [_field('title', 'Tiêu đề', where='head'), _field('author', 'Tác giả', where='head'),
             _field('publishedAt', 'Ngày đăng', where='head'), _field('claim', 'Nhận định chính'),
             _field('number', 'Con số được nêu'), _field('basis', 'Nguồn nó dẫn lại', required=False),
             _field('limits', 'Điều kiện áp dụng', required=False)],
    'docs': [_field('product', 'Sản phẩm/phiên bản', where='head'), _field('version', 'Phiên bản'),
             _field('updatedAt', 'Ngày cập nhật', where='head'), _field('claim', 'Hành vi/đặc tả'),
             _field('default', 'Mặc định hay không'), _field('deprecated', 'Có bị bỏ không'),
             _field('limits', 'Giới hạn đã ghi', required=False)],
    'repo': [_field('repo', 'Repo', where='head'), _field('revision', 'Commit/tag', where='head'),
             _field('claim', 'Điều mã làm'), _field('entrypoint', 'Điểm vào'),
             _field('dependency', 'Phụ thuộc chính', required=False),
             _field('test', 'Bài kiểm chứng minh', required=False),
             _field('license', 'Giấy phép', required=False)],
    'legal': [_field('docNumber', 'Số/ký hiệu văn bản', where='head'),
              _field('issuer', 'Cơ quan ban hành', where='head'),
              _field('effectiveDate', 'Ngày hiệu lực', where='head'),
              _field('validity', 'Còn hiệu lực hay không'),
              _field('claim', 'Điều khoản'), _field('scope', 'Phạm vi áp dụng'),
              _field('penalty', 'Chế tài/mức xử', required=False)],
    'dataset': [_field('name', 'Tên dữ liệu', where='head'), _field('size', 'Kích thước'),
                _field('license', 'Giấy phép', where='head'), _field('split', 'Cách chia'),
                _field('claim', 'Điều nó cho phép khẳng định'), _field('limits', 'Thiên lệch đã biết'),
                _field('updatedAt', 'Ngày cập nhật', required=False, where='head')],
    'news': [_field('outlet', 'Toà soạn', where='head'), _field('publishedAt', 'Ngày đăng', where='head'),
             _field('claim', 'Điều bài nói'), _field('number', 'Con số'),
             _field('sourceCited', 'Nguồn bài dẫn'), _field('origin', 'Nguồn gốc chung', required=False),
             _field('updatedAt', 'Lần sửa gần nhất', required=False)],
    'vendor': [_field('vendor', 'Nhà cung cấp', where='head'), _field('product', 'Sản phẩm'),
               _field('claim', 'Tuyên bố'), _field('number', 'Con số'),
               _field('conditions', 'Điều kiện đo'), _field('independent', 'Có bên thứ ba kiểm', required=False),
               _field('price', 'Giá', required=False)],
    'forum': [_field('host', 'Diễn đàn', where='head'), _field('author', 'Người viết', where='head'),
              _field('publishedAt', 'Ngày viết', where='head'), _field('claim', 'Điều được nói'),
              _field('reproduced', 'Có tái lập được không', required=False),
              _field('counter', 'Ý kiến phản bác trong luồng', required=False)],
    'other': [_field('title', 'Tiêu đề', where='head'), _field('url', 'URL đã mở', where='head'),
              _field('claim', 'Điều nguồn nói'), _field('number', 'Con số', required=False),
              _field('basis', 'Nguồn nó dẫn lại', required=False)],
}

#: Loại nguồn lạ vẫn phải có mẫu gần đúng — ánh xạ về mẫu gốc, KHÔNG bịa trường mới.
_EXTRACTION_KIND_ALIASES = {
    'preprint': 'paper', 'article': 'paper', 'spec': 'legal', 'law': 'legal',
    'regulation': 'legal', 'standard': 'legal', 'model': 'repo', 'code': 'repo',
    'github': 'repo', 'huggingface': 'repo', 'report': 'other', 'page': 'other',
    'wiki': 'other', 'release-note': 'docs', 'api': 'docs', 'discussion': 'forum',
    'social': 'forum', 'market': 'vendor', 'dataset-card': 'dataset',
}


def extraction_fields(source_kind: Any) -> list[dict]:
    """Mẫu trường trích xuất cho một loại nguồn, tối đa `limits.RESEARCH_EXTRACTION_MAX_FIELDS`.

    Mỗi trường là `{'key','label','required','where'}`; `where` ∈ `head|body|link`. Loại lạ ⇒ mẫu
    `other` (không bao giờ ném) để nhánh `deep-read` vẫn có khuôn.
    """
    raw = _slug(source_kind).replace('_', '-')
    kind = raw if raw in EXTRACTION_FIELDS else ''
    if not kind:
        normalized = normalize_source_kind(raw)
        kind = _EXTRACTION_KIND_ALIASES.get(raw) or _EXTRACTION_KIND_ALIASES.get(normalized) or ''
    rows = EXTRACTION_FIELDS.get(kind) or EXTRACTION_FIELDS['other']
    out = [dict(row, sourceKind=kind or 'other') for row in rows]
    return out[:limits.RESEARCH_EXTRACTION_MAX_FIELDS]


# --- 7. hai bên soát độc lập mâu thuẫn ---------------------------------------

_REVIEW_VERDICTS = ('ok', 'revise')
_REVIEW_RELATIONS = ('supports', 'contradicts', 'unsure')
#: Từ chỉ sự phản bác — dùng chung cho cả phán quyết lẫn quan hệ, một chỗ khai.
_REVIEW_CONTRADICTS = ('contradicts', 'contradict', 'refutes', 'no')


def _review_verdict(raw: Any) -> str:
    text = _slug(raw.get('verdict') or raw.get('result'))
    if text in _REVIEW_VERDICTS:
        return text
    relation = _review_relation(raw)
    if relation == 'contradicts':
        return 'revise'
    return 'ok' if relation else ''


def _review_relation(raw: Any) -> str:
    text = _slug(raw.get('relation') or raw.get('stance') or raw.get('supports'))
    if text in _REVIEW_RELATIONS:
        return text
    if text in _REVIEW_CONTRADICTS:
        return 'contradicts'
    if text in ('yes',):
        return 'supports'
    return ''


def _review_key(raw: Any) -> str:
    return _slug(raw.get('reviewerId') or raw.get('reviewer') or raw.get('sessionId')
                 or raw.get('by') or raw.get('role'))


def resolve_disagreement(reviews: Any, *, claim_id: Any = '', caps: Any = None) -> dict:
    """Hai bên soát ĐỘC LẬP mâu thuẫn ⇒ nhận định bị tranh chấp, trần lấy mức THẤP NHẤT (§5.9).

    Không lấy theo đa số. Trả `{'claimId','contested','cap','verdict','reviewers','note',
    'mustReport','reportLine'}`; `mustReport=True` nghĩa là hồ sơ BẮT BUỘC nói ra mâu thuẫn này.
    """
    rows = [item for item in (reviews if isinstance(reviews, (list, tuple)) else [])
            if isinstance(item, Mapping)]
    reviewers: list[dict] = []
    for raw in rows:
        # Danh tính KHÔNG được bịa: hồ sơ thiếu `reviewerId`/`reviewer` vẫn vào danh sách để soi,
        # nhưng không bao giờ tính là một bên soát độc lập (xem `distinct`).
        reviewers.append({'reviewer': _review_key(raw), 'verdict': _review_verdict(raw),
                          'relation': _review_relation(raw), 'mode': _slug(raw.get('mode')),
                          'cap': _slug(raw.get('cap') or raw.get('confidenceCap'))})
    keyed = [item for item in reviewers if item['reviewer']]
    distinct = {item['reviewer'] for item in keyed}
    decisions = {item['reviewer']: item for item in keyed if item['verdict']}
    verdicts = {item['verdict'] for item in decisions.values()}
    relations = {item['relation'] for item in decisions.values() if item['relation']}
    contested = len(distinct) >= 2 and (
        len(verdicts) >= 2 or ({'supports', 'contradicts'} <= relations))
    cap_values = [_slug(item) for item in (caps if isinstance(caps, (list, tuple)) else [])
                  if _slug(item)]
    cap_values.extend(item['cap'] for item in reviewers if item['cap'])
    known_caps = [value for value in cap_values if value in CONFIDENCE_RANK]
    if 'contested' in cap_values:
        cap = 'contested'
    elif known_caps:
        # Mức THẤP NHẤT trong mọi phán quyết — không lấy theo đa số (§5.9).
        cap = min(known_caps, key=lambda value: CONFIDENCE_RANK[value])
    else:
        cap = 'unknown'
    verdict = 'revise' if 'revise' in verdicts else ('ok' if verdicts == {'ok'} else 'none')
    note = ''
    report_line = ''
    if contested:
        note = ('Hai bên soát độc lập không đồng ý về cùng một nhận định; không lấy theo đa số — '
                'hạ mức tin cậy về mức thấp nhất.')
        report_line = (f'Mâu thuẫn: hai nguồn soát độc lập bất đồng'
                       f'{(" về " + _text(claim_id)) if _text(claim_id) else ""}; '
                       f'mức tin cậy hạ về {cap}.')
    return {'claimId': _text(claim_id), 'contested': contested, 'cap': cap, 'verdict': verdict,
            'reviewers': reviewers, 'distinctReviewers': sorted(distinct), 'note': note,
            'mustReport': contested, 'reportLine': report_line}


#: Dùng để nhắc `research_status`: có A SỐ nhận định bị tranh chấp cần hồ sơ nói ra.
def contested_claims(resolutions: Any) -> list[str]:
    out: list[str] = []
    for item in (resolutions if isinstance(resolutions, (list, tuple)) else []):
        if isinstance(item, Mapping) and item.get('contested'):
            claim = _text(item.get('claimId'))
            if claim and claim not in out:
                out.append(claim)
    return out
