"""Công cụ research của vòng 27 (đợt 3–8) — sổ nguồn, hồ sơ, ba mức, phản biện, can thiệp giữa lượt.

Tách khỏi `runtime.py` để phần luật nằm một chỗ đọc được, còn `runtime.py` chỉ giữ đường nối:
mỗi hàm ở đây nhận `rt` (phiên bản `HarnessRuntime`) làm tham số đầu, đúng khuôn để `runtime.py`
gọi một dòng. Không hàm nào tự ghi đĩa hay tự mở mạng: việc đó đi qua `rt.executor`/`rt.web` như
mọi công cụ khác, và mọi cổng (`research_quality`) chạy TRƯỚC khi ghi.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from . import journal, research_header, research_ledger, research_profiles, research_quality
from . import session_journal, source_tiers
from . import limits
from . import research_evidence, research_facets, research_report, research_review
from .limits import (
    CHILD_DEADLINE_SECONDS, CHILD_MAX_STEPS, DOSSIER_DIR_MISMATCH_CODE, DOSSIER_MAX_BYTES, DOSSIER_ROOM,
    DOSSIER_VERSION_ATTEMPTS_MAX,
    FANOUT_PER_PARENT_MAX, OWNER_STEER_PREFIX, RESEARCH_BRIEF_DEFAULT_MODE, RESEARCH_BRIEF_ENV,
    RESEARCH_BRIEF_MISSING_CODE, RESEARCH_BRIEF_MODES, RESEARCH_BRIEF_MODE_UNKNOWN_CODE,
    RESEARCH_BRIEF_TAKEN_CODE, RESEARCH_CRITIQUE_LABEL, RESEARCH_CRITIQUE_MISSING_CODE,
    RESEARCH_GATE_NOTE_CODE, RESEARCH_LEVEL_INVALID_CODE, RESEARCH_MAX_ROWS_PER_DOSSIER,
    RESEARCH_NUDGE_PREFIX, RESEARCH_PROFILE_INVALID_CODE, RESEARCH_PROGRESS_DEFAULT_MODE,
    RESEARCH_PROGRESS_ENV, RESEARCH_PROGRESS_MAX_PER_TURN, RESEARCH_PROGRESS_MODES,
    RESEARCH_PROGRESS_NUDGE_SECONDS, RESEARCH_REVIEW_MIN_ANSWER_CHARS, RESEARCH_SLUG_RE,
    RESEARCH_TIER_BRANCHES, RESEARCH_TIER_CHILD_SECONDS, RESEARCH_TIER_CHILD_STEPS,
    RESEARCH_TIER_CRITIQUE, RESEARCH_TIER_DEFAULT, RESEARCH_TIER_HARD_CEILING_SECONDS,
    RESEARCH_TIER_INVALID_CODE, RESEARCH_TIER_TURN_SECONDS, RESEARCH_TIER_WAVES,
    RESEARCH_TIER_WAVE_SIZE, RESEARCH_TIERS, RESEARCH_TURN_EXTENSION_SECONDS_TIER3,
    RESEARCH_BRIEF_RAISE_REFUSED_CODE, RESEARCH_BRIEF_UPDATED_CODE, RESEARCH_CEILING_CLAMPED_CODE,
    RESEARCH_GATE_ENV, RESEARCH_GATE_DEFAULT_MODE, RESEARCH_GATE_MODES, RESEARCH_GATE_MODE_UNKNOWN_CODE,
    RESEARCH_TIER_DEFAULTED_CODE, RESEARCH_BRANCH_LIMIT_CODE,
    RESEARCH_OWNER_VIEWS_CODE, RESEARCH_OWNER_VIEWS_MAX, RESEARCH_OWNER_VIEW_CHARS,
    RESEARCH_VERIFY_ISSUE_CHARS, RESEARCH_VERIFY_MAX_ISSUES, RESEARCH_VERIFY_NO_CRITIC_CODE,
    RESEARCH_VERIFY_REVISE_MAX, RESEARCH_VERIFY_SUMMARY_CHARS, RESEARCH_VERIFY_UNKNOWN_CODE,
    RESEARCH_VERIFY_VERDICT_MISMATCH_CODE, RESEARCH_VERIFY_VERDICT_MISSING_CODE,
    RESEARCH_VERIFY_VERSION_MISSING_CODE, SOURCE_CLAIM_MAX_CHARS, SOURCE_EXCERPT_MAX_CHARS,
    SOURCE_FAKE_SUCCESS_MIN_CHARS, SOURCE_FAKE_SUCCESS_TITLE_MARKERS, SOURCE_ORIGIN_MAX_CHARS,
    RESEARCH_MODE_REQUIRED_CODE, RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE, RESEARCH_MODE_EVENT_CODE,
    RESEARCH_JOB_ORIGIN, RESEARCH_JOB_ORIGIN_MAIN,
    RESEARCH_SCOPE_MAX_QUESTIONS, RESEARCH_SCOPE_REVISION_INVALID_CODE,
    RESEARCH_REFRESH_DISABLED_CODE, RESEARCH_REFRESH_INHERITED_STATUS,
    RESEARCH_REFRESH_MODE_UNKNOWN_CODE, RESEARCH_REFRESH_NO_DOSSIER_CODE,
    RESEARCH_REFRESH_RUN_ACTIVE_CODE, RESEARCH_REFRESH_SOURCE_ACTIVE_CODE,
    RESEARCH_REFRESH_WITHDRAWN_STATUSES,
    RESEARCH_REFRESH_ENV, RESEARCH_REFRESH_MODES, RESEARCH_REFRESH_DEFAULT_MODE,
    RESEARCH_SCOPE_REVISION_STALE_CODE,
    RESEARCH_STALE_CURRENT_CLAIM_CODE, RESEARCH_STALE_CURRENT_CLAIM_LABEL,
    RESEARCH_COVERAGE_LABEL,
    SOURCE_ROW_LIMIT_DEFAULT, SOURCE_ROW_LIMIT_MAX, STEER_DEFAULT_MODE, STEER_DRAIN_MAX,
    STEER_ENV, STEER_MAX_PENDING, STEER_MODES, STEER_MODE_UNKNOWN_CODE, STEER_TEXT_MAX_CHARS,
)
from .reading import normalize_url
from ..observability.system_log import system_log

#: Câu nhắc tiến độ (#5969) — một câu, có số phút, nói rõ "báo xong thì đi tiếp".
_NUDGE_BODY = ('{elapsed} phút đã trôi trong lượt research này. Báo tiến độ NGẮN cho chủ nhà: '
               'đã mở được bao nhiêu nguồn (số dòng sổ), đang ở nhánh nào, còn nghi ngờ gì nhất. '
               'Báo xong thì đi tiếp, không cần dừng việc.')


# --------------------------------------------------------------------------- cấu hình


def research_config(session) -> dict:
    """Brief của phiên (`session['config']['research']`), hoặc `{}`."""
    value = (session.get('config') or {}).get('research')
    return dict(value) if isinstance(value, dict) else {}


def has_research_brief(session) -> bool:
    """Lượt này đã mở một việc research bằng `research_brief` chưa."""
    return bool(research_config(session).get('researchId'))


def research_tier_limits(tier) -> dict:
    """Trần theo mức, ĐÃ KẸP theo trần chung — số ở đây là số sẽ áp, không phải số trong bảng.

    `branchCeiling` là trần của **cả lượt** (mức 3 = 15 nhánh qua ba sóng), nên nó KHÔNG bị kẹp theo
    `FANOUT_PER_PARENT_MAX` — trần ấy là trần **chạy cùng lúc**, và một sóng chỉ mở `waveSize` nhánh.
    Kẹp nhầm chỗ này biến "ba sóng × năm nhánh" của mức 3 thành sáu nhánh rồi khoá cứng.
    """
    try:
        value = int(tier)
    except (TypeError, ValueError):
        value = 0
    tier = value if value in RESEARCH_TIERS else RESEARCH_TIER_DEFAULT
    return {
        'tier': tier,
        'branchCeiling': int(RESEARCH_TIER_BRANCHES[tier]),
        'branchCeilingPerWave': min(RESEARCH_TIER_WAVE_SIZE[tier], FANOUT_PER_PARENT_MAX),
        'waves': RESEARCH_TIER_WAVES[tier],
        'waveSize': min(RESEARCH_TIER_WAVE_SIZE[tier], FANOUT_PER_PARENT_MAX),
        'childSteps': min(RESEARCH_TIER_CHILD_STEPS[tier], CHILD_MAX_STEPS),
        'childSeconds': min(RESEARCH_TIER_CHILD_SECONDS[tier], CHILD_DEADLINE_SECONDS),
        'turnSeconds': RESEARCH_TIER_TURN_SECONDS[tier],
        'softCeilingSeconds': RESEARCH_TIER_TURN_SECONDS[tier],
        'hardCeilingSeconds': RESEARCH_TIER_HARD_CEILING_SECONDS[tier],
        'extensionSeconds': (RESEARCH_TURN_EXTENSION_SECONDS_TIER3 if tier >= 3 else 0),
        'critique': bool(RESEARCH_TIER_CRITIQUE[tier]),
    }


# Mode mà `research_verify` phải GHI được thì hồ sơ mới coi là đã soát. `coverage` có mặt trong
# `reviewModes` để nhắc giao việc, nhưng cổng hồ sơ không đòi bản ghi ấy (thiếu nó không chặn ghi).
GATE_REVIEW_MODES = ('evidence', 'critique')

# §5.8: trạng thái nào của run gốc thì được phép mở run làm mới (run đang chạy thì không).
_REFRESHABLE_JOB_STATUSES = frozenset({'completed', 'partial', 'cancelled', 'paused'})


def _review_modes_for(state: dict | None, tier: int) -> list[str]:
    """Chế độ soát ĐÃ CHỐT của run, chỉ gồm mode mà cổng hồ sơ đòi bản ghi.

    `state['reviewModes']` là điều đã chốt (thẻ phạm vi/`research_brief` đã nói ra); chưa chốt thì
    suy từ luật chung `research_review.review_modes` — luật nằm MỘT chỗ (§5.11, #6072).
    """
    configured = (state or {}).get('reviewModes')
    if isinstance(configured, list):
        return [mode for mode in GATE_REVIEW_MODES if mode in configured]
    if not tier:
        return []
    return [mode for mode in research_review.review_modes(tier, state or {})
            if mode in GATE_REVIEW_MODES]


def _choose_review_modes(tier: int, questions: list[dict], output: str, scope=None) -> list[str]:
    """Chế độ soát của một run mới — uỷ cho `research_review.review_modes` (nguồn sự thật duy nhất)."""
    state: dict = {'questions': questions, 'output': output}
    if isinstance(scope, dict) and scope:
        state['scope'] = scope
    return research_review.review_modes(tier, state)


def _mode(env_name, modes, default, env=None):
    """Đọc một công tắc `off|warn|enforce|on` — trả `(mode, giá_trị_lạ)`."""
    source = os.environ if env is None else env
    raw = str(source.get(env_name, '') or '').strip().lower()
    if not raw:
        return default, None
    if raw in modes:
        return raw, None
    return default, raw


def research_progress_mode(env=None) -> tuple[str, str | None]:
    """`(mode, unknown)` của nhịp báo tiến độ."""
    return _mode(RESEARCH_PROGRESS_ENV, RESEARCH_PROGRESS_MODES, RESEARCH_PROGRESS_DEFAULT_MODE, env)


def steer_mode(env=None) -> tuple[str, str | None]:
    """`(mode, unknown)` của công tắc can thiệp giữa lượt."""
    return _mode(STEER_ENV, STEER_MODES, STEER_DEFAULT_MODE, env)


def mode_notice(rt, sid, code, env_name, value, default):
    """Notice + log cho một công tắc đọc ra giá trị lạ — mỗi mã chỉ nói MỘT lần cho mỗi phiên."""
    if value is None or rt._notice_seen(sid, code):
        return False
    rt.store.emit(sid, 'notice', {
        'code': code, 'value': value, 'partial': False,
        'message': f'{code}: {env_name}={value!r} là giá trị lạ — dùng {default!r} cho lượt này'})
    system_log.write('research.mode_unknown', level='warn', session_id=sid, code=code, value=value)
    return True


def _fold(value: Any) -> str:
    return research_ledger.fold_text(value)


def _owner_views(raw):
    """Chuẩn hoá `ownerViews` của brief: danh sách chuỗi, bỏ rỗng, bỏ trùng, cắt trần.

    Nhận cả một chuỗi đơn (model hay gửi `ownerViews: "…"`) — một ý kiến vẫn là một ý kiến, không
    phải lỗi tham số.
    """
    if raw is None:
        return []
    items = [raw] if isinstance(raw, str) else list(raw)
    out: list[str] = []
    for item in items:
        text = str(item or '').strip()[:RESEARCH_OWNER_VIEW_CHARS]
        if text and text not in out:
            out.append(text)
    return out[:RESEARCH_OWNER_VIEWS_MAX]


def slug_from_question(question: str, research_id: str | None = None) -> str:
    """Slug phòng hồ sơ: `researchId` nếu hợp lệ, ngược lại sinh từ câu hỏi (đọc được, tất định)."""
    candidate = str(research_id or '').strip().lower()
    if candidate and re.fullmatch(RESEARCH_SLUG_RE, candidate):
        return candidate
    words = [word for word in re.findall(r'[a-z0-9]+', _fold(question)) if len(word) > 1][:5]
    slug = '-'.join(words)[:40].strip('-')
    if slug and re.fullmatch(RESEARCH_SLUG_RE, slug):
        return slug
    return f'research-{str(int(time.time()))[-4:]}'


def dossier_dir_for(slug: str) -> str:
    """`.research/<slug>-<yyyymmdd-hhmm>` — một phòng cho mỗi việc, đường dẫn chủ nhà mở được."""
    stamp = time.strftime('%Y%m%d-%H%M', time.gmtime())
    return f'{DOSSIER_ROOM}/{slug}-{stamp}'


# --------------------------------------------------------------------------- sổ nguồn


def _excerpt_key(text: str) -> str:
    """Chìa tự nhiên cho một đoạn trích: vân tay khi đủ dài, ngược lại băm ngắn (đoạn trích ngắn vẫn
    phải idempotent — model gọi lại cùng một dòng thì không được sinh dòng thứ hai)."""
    body = str(text or '')
    if len(body) >= research_ledger.MIN_FINGERPRINT_CHARS:
        return research_ledger.fingerprint(body)
    return 'sha1:' + hashlib.sha1(body.encode('utf-8')).hexdigest()[:16]


def _ledger_owner(rt, session, sid):
    """`(owner, child_id)` — sổ nguồn sống ở phiên GIỮ BRIEF, không ở nhánh con.

    Nhánh con ghi vào sổ của việc (kèm mã nhánh) để (a) cổng chất lượng đọc được cả sổ ở một chỗ,
    (b) luật "mỗi nhánh con phải để lại một dòng" đếm được, (c) hồ sơ ghi ở phiên việc thấy hết nguồn.
    Không tìm được phiên giữ brief thì đi lên tận gốc — dòng sổ vẫn nằm một chỗ, không rơi.
    """
    owner = str(sid)
    if research_config(session).get('researchId'):
        return owner, None
    current = session
    for _ in range(8):
        parent = str(current.get('parent_id') or '')
        if not parent:
            break
        owner = parent
        current = rt.store.get(parent) or {}
        if research_config(current).get('researchId'):
            break
    return owner, (None if owner == str(sid) else str(sid))


def _rows_of(rt, sid) -> list:
    """Sổ nguồn của phiên dưới dạng `research_ledger.Row` (thuần, cho mọi luật)."""
    return [_row_of(item) for item in rt.store.source_rows(sid)]


def _row_of(item) -> Any:
    return research_ledger.Row(
        row_id=item['rowId'], claim=item.get('claim') or '', url=item.get('url') or '',
        host=item.get('host') or '', tier=int(item['tier'] if item.get('tier') is not None else 4), type=item.get('type') or 'normal',
        excerpt=item.get('excerpt') or '', fetched_at=item.get('fetchedAt') or '',
        origin=item.get('origin'), method=item.get('method'), source_row_id=item.get('sourceRowId'),
        status=item.get('status') or 'unverified', fingerprint=item.get('fingerprint') or '',
        payload=item.get('payload') or {}, child_id=item.get('childId'),
        branches=tuple(str(entry) for entry in (item.get('branches') or []) if str(entry)),
        turn=int(item.get('turn') or 0), step=item.get('step'), created=str(item.get('created') or ''))


def _count_by(items, key):
    counts: dict[str, int] = {}
    for item in items:
        label = str(key(item))
        counts[label] = counts.get(label, 0) + 1
    return counts


def _ledger_counts(rt, owner) -> dict:
    """Số liệu sổ của MỘT việc: số dòng, số nguồn độc lập, theo tầng, theo nhánh con."""
    items = _rows_of(rt, owner)
    return {'rows': len(items), 'independent': research_ledger.independent_count(items),
            'byChild': rt.store.source_counts_by_child(owner),
            'byTier': _count_by(items, lambda item: str(item.tier))}


# --- P2: bằng chứng · thời gian · bao phủ (§5.5–5.9 của kế hoạch v2) ---------


def _pick(args, *names):
    """Giá trị ĐẦU TIÊN có mặt trong `args` theo danh sách tên (camelCase hoặc snake_case)."""
    for name in names:
        if isinstance(args, dict) and args.get(name) is not None:
            return args.get(name)
    return None


def _source_meta(args, *, url, host, research_id) -> dict:
    """Siêu dữ liệu P2 của MỘT dòng sổ — chuẩn hoá, không bao giờ ném.

    Mô hình chỉ khai được phần đã đọc thấy trên trang; `origin_cluster` do máy suy bằng
    `research_evidence.origin_cluster` khi mô hình không khai, nên luật "hai nguồn độc lập" luôn có
    dữ liệu để đếm cụm thay vì phụ thuộc trí nhớ của mô hình.
    """
    payload = args.get('payload') if isinstance(args.get('payload'), dict) else {}
    kind = str(_pick(args, 'sourceKind', 'source_kind') or '').strip()
    access = str(_pick(args, 'accessLevel', 'access_level') or '').strip()
    return {
        'published_at': research_evidence.parse_date(_pick(args, 'publishedAt', 'published_at')),
        'updated_at': research_evidence.parse_date(_pick(args, 'updatedAt', 'updated_at')),
        'version_label': str(_pick(args, 'versionLabel', 'version_label') or '').strip(),
        # Rỗng thì để rỗng (cột có mặc định của nó); chỉ chuẩn hoá khi mô hình CÓ khai.
        'source_kind': (research_evidence.normalize_source_kind(kind) if kind else ''),
        'origin_cluster': research_evidence.origin_cluster({**args, 'url': url, 'host': host,
                                                            'payload': payload}),
        'access_level': (research_evidence.normalize_access_level(access) if access else ''),
        'section_kind': str(_pick(args, 'sectionKind', 'section_kind') or '').strip(),
        'event_date': research_evidence.parse_date(_pick(args, 'eventDate', 'event_date')),
        'research_id': str(research_id or ''),
    }


def _search_log_rows(rt, research_id) -> list:
    """Nhật ký tìm của MỘT run, đọc từ `search_store` — KHÔNG mở đường ghi thứ hai.

    Đường dẫn lấy theo thứ tự: `rt.search_db_path` (bài kiểm ghim) → `BOXFOX_SEARCH_DB` → kho mặc
    định. Kho mặc định **chưa có tệp** thì trả `[]` thay vì tạo mới: đọc bao phủ không được sinh ra
    cơ sở dữ liệu ở nhà người dùng.
    """
    rid = str(research_id or '')
    if not rid:
        return []
    try:
        from . import search_store
        path = getattr(rt, 'search_db_path', None)
        if path is None:
            path = os.environ.get(search_store.DB_PATH_ENV) or ''
        if not path:
            default = search_store.default_path()
            if not default.exists():
                return []
            path = default
        elif not Path(path).exists():
            # Đường dẫn chỉ định (bài kiểm, `BOXFOX_SEARCH_DB`) cũng phải theo cùng một luật: ĐỌC
            # bao phủ không được tạo cơ sở dữ liệu (đợt soát `ed485f3`, finding 8).
            return []
        return list(search_store.connect(path).search_log(research_id=rid) or [])
    except Exception as error:  # pragma: no cover - đo bao phủ không bao giờ được chặn run
        system_log.write('research.coverage.log_unread', level='warn', code='RESEARCH_COVERAGE_LOG',
                         researchId=rid, error=str(error)[:300])
        return []


def _claim_metas(rt, research_id) -> list:
    """`research_claim_meta` của run — đọc an toàn (bảng vắng ⇒ danh sách rỗng)."""
    try:
        return list(rt.store.claim_meta_list(str(research_id or '')) or [])
    except Exception:  # pragma: no cover
        return []


def _facets_of(rt, research_id) -> list:
    """Facet của run — đọc an toàn."""
    try:
        return list(rt.store.facet_list(str(research_id or '')) or [])
    except Exception:  # pragma: no cover
        return []


def _scope_questions(rt, research_id) -> list:
    """Câu hỏi của run dưới dạng `research_facets.stop_checks` đọc được (ưu tiên `importance`)."""
    try:
        job = rt.store.research_job(str(research_id or ''))
    except Exception:  # pragma: no cover
        job = None
    state = (job or {}).get('state') or {}
    scope = state.get('scope') if isinstance(state.get('scope'), dict) else {}
    out = []
    for item in (scope.get('questions') or state.get('questions') or []):
        if not isinstance(item, dict):
            continue
        out.append({'questionId': item.get('id') or item.get('questionId'),
                    'importance': item.get('importance') or 'medium',
                    'state': item.get('status') or item.get('state') or 'open',
                    'text': item.get('text')})
    return out


def coverage_refresh(rt, research_id, *, write=True, questions=None):
    """Đo bao phủ của run từ facet đã lưu + NHẬT KÝ TÌM, rồi (tuỳ chọn) ghi lại facet.

    Bão hoà là chuyện ĐO ĐƯỢC, không phải chuyện mô hình tự khai: mỗi lần gọi đọc
    `search_store.search_log()` của run, tính `saturation_from_log` và cập nhật
    `status`/`lastNewRatio` của facet. Hai trạng thái do người/agent quyết (`blocked`,
    `out-of-scope`) không bị phép đo ghi đè.

    `write=False` để chỉ đọc. Trả `{}` khi công tắc `BOXFOX_RESEARCH_COVERAGE=off` (hành vi cũ).
    """
    if not limits.research_coverage_enabled():
        return {}
    rid = str(research_id or '')
    facets = _facets_of(rt, rid)
    log_rows = _search_log_rows(rt, rid)
    measured = research_facets.saturation_from_log(log_rows, research_id=rid)
    metas = _claim_metas(rt, rid)
    updated = []
    for raw in facets:
        row = research_facets.normalize_facet(raw)
        state = measured['facets'].get(row['facetId'])
        if state and row['status'] not in research_facets.CLOSED_STATUSES:
            if state['status'] in ('searched', 'saturated'):
                row['status'] = state['status']
            row['lastNewRatio'] = float(state['lastRatio'])
        row['evidenceCount'] = len([item for item in metas
                                    if str(item.get('facetId') or '') == row['facetId']])
        if write:
            try:
                row = rt.store.facet_save(rid, row) or row
            except Exception:  # pragma: no cover - ghi facet hỏng không được chặn hồ sơ
                pass
        updated.append(row)
    coverage = research_facets.coverage_payload(updated,
                                               questions=(questions if questions is not None
                                                          else _scope_questions(rt, rid)))
    coverage['measured'] = {'overall': measured['overall'],
                            'facets': {key: value['status'] for key, value in measured['facets'].items()}}
    coverage['searchLogRows'] = len(log_rows)
    return coverage


def coverage_stop(rt, research_id, *, coverage=None, stalled_waves=0, budget=None):
    """Bốn điều kiện dừng của §5.5 trên facet/câu hỏi hiện có (không bao giờ ném)."""
    rid = str(research_id or '')
    cov = coverage if isinstance(coverage, dict) else coverage_refresh(rt, rid)
    facets = _facets_of(rt, rid)
    issues = [{'kind': 'coverage', 'detail': item, 'resolved': False}
              for item in (cov.get('unexplored') or [])] if cov else []
    try:
        return research_facets.stop_checks(facets, _scope_questions(rt, rid),
                                           coverage_issues=issues, budget=budget,
                                           stalled_waves=stalled_waves)
    except Exception as error:  # pragma: no cover - điểm dừng chỉ là lời khuyên
        return {'ready': False, 'reasons': [f'không đo được điểm dừng: {str(error)[:200]}'],
                'blockers': [], 'partial': False, 'counts': {}, 'stalledWaves': int(stalled_waves or 0)}


def _claims_declared(report) -> list:
    """`claims[]` của báo cáo có cấu trúc, giữ nguyên thứ tự (rỗng nếu không có)."""
    if not isinstance(report, dict):
        return []
    raw = report.get('claims')
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _claims_by_id(rows) -> dict:
    """Sổ nhận định gom theo `claimId` (bỏ dòng thiếu mã)."""
    grouped: dict[str, list] = {}
    for item in rows:
        claim_id = str(item.get('claimId') or '')
        if claim_id:
            grouped.setdefault(claim_id, []).append(item)
    return grouped


def _claims_declared_map(report) -> dict:
    """`claims[]` của báo cáo theo khoá `claimId` (nhận cả `claim_id`)."""
    return {str(item.get('claimId') or item.get('claim_id') or ''): item
            for item in _claims_declared(report)}


def record_claim_meta(rt, owner, research_id, *, report=None, window_days=0, as_of='') -> int:
    """Ghi `research_claim_meta` cho MỌI nhận định chính của run (§7.2 của hợp đồng P2).

    Nguồn nhận định là hai đường hợp lại: `claims[]` của `report` (mô hình khai loại/lập trường/độ
    tin cậy) và các `claimId` có thật trong sổ (`store.evidence_claims`). Trần độ tin cậy do MÁY tính
    từ sổ (`research_evidence.confidence_cap`); mô hình chỉ **hạ** được, không nâng quá trần
    (`research_evidence.apply_cap`). Không bao giờ ném: nhận định thiếu mã bị bỏ qua.
    """
    rid = str(research_id or '')
    if not rid:
        return 0
    try:
        rows = list(rt.store.evidence_claims(owner, rid) or [])
    except Exception:  # pragma: no cover
        rows = []
    by_claim = _claims_by_id(rows)
    declared = _claims_declared_map(report)
    order = [cid for cid in declared if cid]
    order += [cid for cid in by_claim if cid not in declared]
    written = 0
    for claim_id in order:
        item = declared.get(claim_id) or {}
        evidence = by_claim.get(claim_id) or []
        claim_type = research_evidence.normalize_claim_type(item.get('claimType')
                                                            or item.get('claim_type'))
        stance = str(item.get('stanceOrigin') or item.get('stance_origin') or '').strip()
        stance = (research_evidence.normalize_stance(stance) if stance else
                  ('agent-inference' if research_evidence.is_inference(claim_type) else 'source-stated'))
        cap = research_evidence.confidence_cap(claim_type, evidence, stance_origin=stance,
                                               window_days=window_days, as_of=as_of)
        declared_level = str(item.get('confidence') or '').strip().lower()
        confidence = research_evidence.apply_cap(declared_level or cap['cap'], cap['cap'])
        try:
            rt.store.claim_meta_save(
                rid, claim_id,
                claimType=claim_type, stanceOrigin=stance, confidence=confidence,
                confidenceCap=cap['cap'],
                basis=research_evidence.basis_payload(claim_type, evidence, rule=cap['rule']),
                asOf=str(as_of or ''),
                questionId=str(item.get('questionId') or item.get('question_id') or ''),
                facetId=str(item.get('facetId') or item.get('facet_id') or ''))
            written += 1
        except Exception as error:  # pragma: no cover - ghi mức không được chặn ghi hồ sơ
            system_log.write('research.claim_meta.failed', level='warn', code='RESEARCH_CLAIM_META',
                             researchId=rid, claimId=claim_id, error=str(error)[:200])
    return written


def stale_current_issues(rt, owner, research_id, *, report=None, window_days=0, as_of='') -> list:
    """Lỗi `research-stale-current-claim` cho nhận định hiện trạng (§7.6 của hợp đồng P2).

    Chỉ chạy khi `BOXFOX_RESEARCH_TIME_POLICY=on` và run có cửa sổ thời gian. Trả danh sách
    `research_quality.Issue`, gắn thẳng vào `Verdict` của `dossier_write`.
    """
    rid = str(research_id or '')
    if not limits.research_time_policy_enabled() or int(window_days or 0) <= 0 or not rid:
        return []
    try:
        rows = list(rt.store.evidence_claims(owner, rid) or [])
    except Exception:  # pragma: no cover
        return []
    by_claim = _claims_by_id(rows)
    declared = _claims_declared_map(report)
    issues = []
    for claim_id, item in declared.items():
        if not claim_id:
            continue
        claim_type = research_evidence.normalize_claim_type(item.get('claimType')
                                                            or item.get('claim_type'))
        if claim_type not in research_evidence.CURRENT_CLAIM_TYPES:
            continue
        result = research_evidence.stale_current_claim(claim_type, by_claim.get(claim_id) or [],
                                                       window_days=window_days, as_of=as_of)
        if result['stale']:
            issues.append(research_quality.Issue(
                RESEARCH_STALE_CURRENT_CLAIM_CODE,
                f'{claim_id} ({RESEARCH_STALE_CURRENT_CLAIM_LABEL}: {result["inWindow"]} trong cửa sổ, '
                f'{result["outside"]} ngoài cửa sổ)'))
    return issues


def source_add(rt, session, args):
    """`source_add`: ghim một dòng sổ. Ghi lặp CÙNG (url, đoạn trích) là idempotent — một khẳng định,
    một dòng, kể cả khi model gọi lại sau một lỗi mạng hay một lượt lặp."""
    sid = session['id']
    owner, child_id = _ledger_owner(rt, session, sid)
    claim = str(args.get('claim') or '').strip()
    url = str(args.get('url') or '').strip()
    excerpt = str(args.get('excerpt') or '').strip()
    if not claim:
        raise ValueError('SOURCE_INVALID: claim must not be empty — say which assertion this row backs')
    if not url:
        raise ValueError('SOURCE_INVALID: url must not be empty — the row must point at what you opened')
    if not excerpt:
        raise ValueError('SOURCE_INVALID: excerpt must not be empty — record what you actually read, verbatim')
    tier_info = source_tiers.classify(url, type=args.get('type'), method=args.get('method'),
                                      claim=claim,
                                      overrides=source_tiers.load_from_env().overrides)
    excerpt_text = excerpt[:SOURCE_EXCERPT_MAX_CHARS]
    key = _excerpt_key(excerpt_text)
    normalized = normalize_url(url)
    research_id = str(research_config(session).get('researchId') or '')
    for item in _rows_of(rt, owner):
        if normalize_url(item.url) != normalized:
            continue
        if _excerpt_key(item.excerpt) != key:
            continue
        # Dùng LẠI dòng là chuyện đúng, nhưng lời gọi thứ hai không được biến thành im lặng:
        # (a) trường hồ sơ nó gửi lên mà dòng cũ chưa có thì phải vào dòng (nguồn vẫn là nguồn ấy);
        # (b) nhánh con gọi lần hai phải được ghi vào dòng — nếu không, nhánh ấy bị chấm
        # `research-lineage-missing` mà không có cách nào gỡ (vòng 27, đợt 8).
        incoming = args.get('payload') if isinstance(args.get('payload'), dict) else {}
        merged = dict(item.payload or {})
        added = sorted(key for key, value in incoming.items()
                       if str(value or '').strip() and not str(merged.get(key) or '').strip())
        for name in added:
            merged[name] = incoming[name]
        conflicts = sorted(key for key, value in incoming.items()
                           if str(merged.get(key) or '').strip() and merged.get(key) != value)
        linked = False
        if child_id and item.child_id != child_id and child_id not in (item.branches or ()):
            rt.store.source_link_branch(owner, item.row_id, child_id)
            linked = True
        if added or conflicts:
            rt.store.source_payload_merge(owner, item.row_id, merged)
            system_log.write('research.source.reused', level='info', session_id=sid,
                             code='SOURCE_REUSED', row=item.row_id, host=item.host,
                             added=len(added), conflicts=conflicts, branchLinked=linked)
        item = _row_of(rt.store.source_row(owner, item.row_id) or {})
        # P2 (§7.1): lượt gọi lại vẫn phải ĐẨY được siêu dữ liệu mới vào nguồn — dòng sổ là nguồn
        # sự thật, nên ghi qua chính `evidence_link` thay vì mở đường ghi thứ hai.
        meta = _source_meta(args, url=url, host=item.host or source_tiers.host_of(url),
                            research_id=research_id)
        link = rt.store.evidence_link(owner, item.row_id, claim, proposed_by=sid,
                                      published_at=meta['published_at'], updated_at=meta['updated_at'],
                                      version_label=meta['version_label'], source_kind=meta['source_kind'],
                                      origin_cluster=meta['origin_cluster'],
                                      access_level=meta['access_level'],
                                      section_kind=meta['section_kind'], event_date=meta['event_date'],
                                      research_id=meta['research_id'])
        answer = {'rowId': item.row_id, 'tier': item.tier, 'type': item.type, 'host': item.host,
                  'fetchedAt': item.fetched_at, 'reused': True,
                  'counts': _ledger_counts(rt, owner), 'label': source_tiers.TIER_LABELS.get(item.tier, ''),
                  'reason': 'đã có dòng sổ cho đúng URL và đúng đoạn trích này', **link}
        if added:
            answer['payloadMerged'] = added
        if conflicts:
            answer['payloadKept'] = conflicts
            answer['note'] = (f'trường {", ".join(conflicts)} đã có giá trị khác trong dòng sổ — giữ giá '
                              f'trị CŨ; cần sửa thì mở lại nguồn và ghim đoạn trích khác')
        if linked:
            answer['branchLinked'] = True
        return answer
    row = {
        'claim': claim[:SOURCE_CLAIM_MAX_CHARS],
        'url': url,
        'host': tier_info.host or source_tiers.host_of(url),
        'tier': tier_info.tier,
        'type': tier_info.type,
        'excerpt': excerpt_text,
        'fetched_at': str(args.get('fetchedAt') or journal.utc_now_iso()),
        'origin': (str(args.get('origin') or '').strip()[:SOURCE_ORIGIN_MAX_CHARS] or None),
        'method': str(args.get('method') or 'web_fetch'),
        'source_row_id': (str(args.get('sourceRowId') or '').strip() or None),
        'status': 'unverified',
        'fingerprint': (key if not key.startswith('sha1:') else ''),
        'payload': args.get('payload') if isinstance(args.get('payload'), dict) else {},
        'child_id': child_id,
        'job': research_config(session).get('researchId'),
        # P1 (§5.3): ghim dòng sổ vào ĐÚNG run đang mở, để nhiều run trong một phiên không trộn sổ.
        'research_id': research_id,
        'turn': int(rt.active_turn.get(sid) or 0),
        'step': rt.active_step.get(sid),
    }
    # P2 (§7.1): siêu dữ liệu P2 vào cùng hàng sổ (`source_ledger`), nên đường mới nhất quán với
    # đường dùng lại — cùng một luật chuẩn hoá, cùng một cách suy cụm gốc.
    meta = _source_meta(args, url=url, host=row['host'], research_id=research_id)
    row.update({key: value for key, value in meta.items() if value not in (None, '')})
    stored = rt.store.source_add(owner, row)
    link = rt.store.evidence_link(owner, stored['rowId'], claim, proposed_by=sid,
                                  published_at=meta['published_at'], updated_at=meta['updated_at'],
                                  version_label=meta['version_label'], source_kind=meta['source_kind'],
                                  origin_cluster=meta['origin_cluster'],
                                  access_level=meta['access_level'],
                                  section_kind=meta['section_kind'], event_date=meta['event_date'],
                                  research_id=meta['research_id'])
    counts = _ledger_counts(rt, owner)
    system_log.write('research.source.added', session_id=sid, code='SOURCE_ADDED',
                     row=stored['rowId'], host=stored['host'], tier=stored['tier'],
                     rows=counts['rows'], chars=len(excerpt_text))
    answer = {'rowId': stored['rowId'], 'tier': stored['tier'], 'type': stored['type'],
              'host': stored['host'], 'fetchedAt': stored['fetchedAt'], 'counts': counts,
              'label': tier_info.label, 'reason': tier_info.reason, 'reused': False, **link}
    if not tier_info.is_primary:
        answer['note'] = (f'{stored["host"]} xếp tầng {stored["tier"]} ({tier_info.label}); một khẳng '
                          f'định then chốt cần nguồn thứ hai KHÁC nguồn tin gốc.')
    if len(excerpt_text) < research_ledger.MIN_EXCERPT_CHARS:
        answer['warning'] = (f'đoạn trích {len(excerpt_text)} ký tự, dưới sàn '
                             f'{research_ledger.MIN_EXCERPT_CHARS} — hồ sơ sẽ bị cổng chất lượng từ chối: '
                             f'lưu đoạn NGUYÊN VĂN đã đọc, không phải tóm tắt.')
    return answer


def source_list(rt, session, args):
    """`source_list`: đọc lại sổ — thứ main phải xem TRƯỚC khi viết hồ sơ."""
    sid = session['id']
    owner, _child = _ledger_owner(rt, session, sid)
    try:
        limit = int(args.get('limit')) if args.get('limit') is not None else SOURCE_ROW_LIMIT_DEFAULT
    except (TypeError, ValueError):
        limit = SOURCE_ROW_LIMIT_DEFAULT
    limit = max(1, min(limit, SOURCE_ROW_LIMIT_MAX))
    try:
        tier = int(args.get('tier')) if args.get('tier') is not None else None
    except (TypeError, ValueError):
        tier = None
    turn = None
    if args.get('turn') is not None:
        try:
            turn = int(args.get('turn'))
        except (TypeError, ValueError):
            turn = None
    # P1 (§5.3): một phiên có thể có nhiều RUN — lọc theo run khi người gọi chỉ đích danh, hoặc khi
    # `config.research` đã mở run. KHÔNG bỏ bộ lọc khi run chưa có dòng nào: làm vậy thì sổ của run
    # mới hiện dòng của run KHÁC (review "nhỏ" — rò rỉ giữa các run).
    scope_id = str(args.get('researchId') or research_config(session).get('researchId') or '').strip()
    rows = rt.store.source_rows(owner, child_id=args.get('childId') or None, turn=turn, tier=tier,
                                limit=limit, newest_first=True, research_id=scope_id or None)
    counts = _ledger_counts(rt, owner)
    return {'rows': rows, 'counts': {'total': counts['rows'], 'byTier': counts['byTier'],
                                     'byChild': counts['byChild'], 'independent': counts['independent']},
            'window': {'limit': limit, 'returned': len(rows), 'newestFirst': True},
            'evidenceGraph': rt.store.evidence_graph(owner, limit=limit)}


def claim_assess(rt, session, args):
    """An independent reviewer assesses a claim/passage relation for one dossier hash."""
    if session.get('role') != 'research-review':
        raise PermissionError('claim_assess is research-review-only')
    target = (session.get('config') or {}).get('reviewTarget') or {}
    if target.get('kind') != 'research' or not target.get('contentHash'):
        raise ValueError('RESEARCH_REVIEW_TARGET_REQUIRED')
    parent_id = str(session.get('parent_id') or '')
    if not parent_id:
        raise ValueError('RESEARCH_REVIEW_OWNER_REQUIRED')
    dossier = rt.store.dossier(target.get('researchId'), target.get('version'))
    if not dossier or dossier['session_id'] != parent_id or \
            dossier['relative_path'] != target.get('path') or \
            dossier['content_hash'] != target.get('contentHash'):
        raise ValueError('RESEARCH_REVIEW_TARGET_CHANGED')
    if not _review_read_proof(rt, session['id'], dossier['relative_path'], dossier['content_hash']):
        raise ValueError('RESEARCH_REVIEW_DOCUMENT_NOT_READ')
    relation = str(args.get('relation') or '').strip().lower()
    if relation not in {'supports', 'contradicts', 'context', 'insufficient', 'inaccessible'}:
        raise ValueError('RESEARCH_RELATION_INVALID')
    rationale = str(args.get('rationale') or '').strip()
    if len(rationale) < 20:
        raise ValueError('RESEARCH_ASSESSMENT_REASON_TOO_SHORT')
    return rt.store.evidence_assess(parent_id, str(args.get('passageId') or ''),
                                    str(args.get('claimId') or ''), session['id'],
                                    dossier['content_hash'], relation, rationale[:2000])


def _passage_match(excerpt: str, body: str) -> tuple[bool, float]:
    """Compare a passage with local windows, never with the whole document."""
    def tokens(value):
        folded = unicodedata.normalize('NFKC', value).casefold()
        return re.findall(r'\w+', folded, flags=re.UNICODE)

    needle, haystack = tokens(excerpt), tokens(body)
    if not needle or not haystack:
        return False, 0.0
    if len(needle) <= len(haystack):
        width = len(needle)
        for start in range(len(haystack) - width + 1):
            if haystack[start:start + width] == needle:
                return True, 1.0
    # OCR and HTML extraction may disturb a few words. Compare adjacent windows,
    # not the short quotation against thousands of unrelated words.
    width = len(needle)
    step = max(1, width // 8)
    target = set(needle)
    best = 0.0
    for start in range(0, max(1, len(haystack) - width + 1), step):
        candidate = set(haystack[start:start + width])
        score = len(target & candidate) / max(1, len(target | candidate))
        best = max(best, score)
    # A near match may be OCR noise, or one changed word that reverses the
    # meaning. Keep the score for diagnosis but never certify it as verbatim.
    return False, best


async def source_verify(rt, session, args):
    """`source_verify`: mở LẠI một URL và so với đoạn trích đã ghim (chống "thành công giả")."""
    sid = session['id']
    owner, _child = _ledger_owner(rt, session, sid)
    row_id = str(args.get('rowId') or '').strip()
    if not row_id:
        raise ValueError('SOURCE_VERIFY_INVALID: rowId is required (r1, r2, … from source_add)')
    stored = rt.store.source_row(owner, row_id)
    if stored is None:
        raise ValueError(f'SOURCE_VERIFY_UNKNOWN: no ledger row {row_id!r} in this session — '
                         f'call source_list to see the row ids you have')
    url = stored['url']
    workspace_source = (stored.get('method') == 'workspace' and
                        not urllib.parse.urlsplit(url).scheme)
    async def read_workspace(offset):
        result = await rt.executor.execute('file_read',
                                           {'path': url, 'offset': offset, 'limit': 50000}, sid)
        if result.get('is_error') or result.get('encoding') == 'base64':
            raise ValueError('workspace document has no readable UTF-8 text')
        return {'text': result.get('content') or '', 'title': os.path.basename(url),
                'status': 200, 'reader': 'workspace',
                'nextOffset': result.get('nextOffset'),
                'truncated': bool(result.get('truncated')),
                'fetchedAt': journal.utc_now_iso()}
    try:
        payload = (await read_workspace(0) if workspace_source else
                   await asyncio.to_thread(rt.web.fetch, {'url': url, 'maxChars': 50000}))
    except Exception as exc:  # lỗi mở lại ⇒ KHÔNG BAO GIỜ `ok` (A-6, "thành công giả")
        rt.store.source_status_set(owner, row_id, 'unverified', matched=False)
        code = getattr(exc, 'code', exc.__class__.__name__)
        system_log.write('research.source.verify', level='warn', session_id=sid,
                         code='SOURCE_VERIFY_UNREACHABLE', row=row_id, host=stored['host'], remote=code)
        return {'rowId': row_id, 'status': 'unverified', 'matched': False,
                'claimSupport': 'not_checked', 'unreachable': True,
                'fakeSuccess': False, 'viaReader': False, 'host': stored['host'],
                'blockedSource': {'url': url, 'attempt': 'source_verify/web_fetch',
                                  'readablePortion': stored.get('excerpt') or '',
                                  'claim': stored.get('claim') or '', 'errorCode': str(code)},
                'message': f'không mở lại được {stored["host"]} ({code}) — ghi "chưa mở được bản gốc" '
                           f'vào hồ sơ thay vì coi dòng này là đã kiểm'}
    served = dict(payload or {})
    text = str(served.get('text') or '')
    matched, ratio = _passage_match(stored.get('excerpt') or '', text)
    read_error = None
    next_offset = served.get('nextOffset')
    next_page = served.get('pdfNextPage')
    current_ref = served.get('ref')
    pdf_text_truncated = bool(served.get('pdfTextTruncated'))
    segments = 1
    while not matched and (next_offset is not None or next_page is not None) and segments < 36:
        try:
            if next_offset is None:
                # A PDF window has been fully read. Reopen the following page
                # window rather than declaring a quotation on page 41 stale.
                page = await asyncio.to_thread(rt.web.fetch, {
                    'url': url, 'pdfStartPage': next_page, 'maxChars': 50000})
                current_ref = page.get('ref')
                pdf_text_truncated = pdf_text_truncated or bool(page.get('pdfTextTruncated'))
            else:
                read_args = {'offset': next_offset, 'maxChars': 20000}
                if workspace_source:
                    page = await read_workspace(next_offset)
                elif current_ref:
                    read_args['ref'] = current_ref
                    page = await asyncio.to_thread(rt.web.read_source, read_args)
                else:
                    page = await asyncio.to_thread(rt.web.fetch, {'url': url, **read_args})
        except Exception as exc:
            read_error = getattr(exc, 'code', exc.__class__.__name__)
            break
        chunk = str(page.get('text') or '')
        if not chunk or (next_offset is not None and page.get('nextOffset') == next_offset):
            break
        # Keep a small overlap so a quotation across a slice boundary is found.
        matched, ratio = _passage_match(stored.get('excerpt') or '', text[-2000:] + chunk)
        text += chunk
        next_offset = page.get('nextOffset')
        next_page = page.get('pdfNextPage')
        segments += 1
    title = str(served.get('title') or '').strip()
    body = text.strip()
    fake = (not workspace_source and
            ((title in SOURCE_FAKE_SUCCESS_TITLE_MARKERS) or
             (len(body) < SOURCE_FAKE_SUCCESS_MIN_CHARS)))
    matched = (not fake) and matched
    incomplete = bool(next_offset is not None or next_page is not None or pdf_text_truncated or read_error or
                      (segments == 1 and served.get('truncated') and
                       served.get('nextOffset') is None))
    approximate = not matched and ratio >= research_ledger.JACCARD_MERGE
    status = 'ok' if matched else ('unverified' if fake or incomplete or approximate else 'stale')
    rt.store.source_status_set(owner, row_id, status, matched=matched)
    system_log.write('research.source.verify', level='info', session_id=sid,
                     code='SOURCE_VERIFY_OK' if matched else 'SOURCE_VERIFY_MISMATCH', row=row_id,
                     host=stored['host'], status=status, overlap=round(ratio, 3), chars=len(body),
                     fakeSuccess=fake)
    answer = {'rowId': row_id, 'status': status, 'matched': matched,
              'claimSupport': 'not_checked', 'unreachable': False,
              'fakeSuccess': bool(fake), 'viaReader': bool(served.get('reader')),
              'host': stored['host'], 'httpStatus': served.get('status'),
              'overlap': round(ratio, 3), 'approximate': approximate,
              'chars': len(body), 'fetchedAt': served.get('fetchedAt')}
    answer['segmentsRead'] = segments
    if read_error:
        answer['readError'] = str(read_error)
    if fake:
        answer['message'] = (f'{stored["host"]} trả HTTP {served.get("status")} nhưng thân bài chỉ '
                             f'{len(body)} ký tự (dưới sàn {SOURCE_FAKE_SUCCESS_MIN_CHARS})'
                             f'{f", tiêu đề {title!r}" if title else ""} — "thành công giả": dòng này '
                             f'KHÔNG được coi là đã kiểm; tìm bản gốc khác, hoặc ghi "chưa mở được bản gốc".')
    elif incomplete and not matched:
        answer['message'] = 'bản đọc bị cắt trước khi tìm thấy đoạn trích; cần đọc tiếp trang/PDF'
    elif approximate:
        answer['message'] = 'đoạn gần giống nhưng không trùng nguyên văn; kiểm lại từ thay đổi và ngữ cảnh'
    elif not matched:
        answer['message'] = (f'nội dung đã đổi (trùng {round(ratio, 3)} < {research_ledger.JACCARD_MERGE}); '
                             f'cập nhật đoạn trích bằng `source_add` rồi mới viết hồ sơ.')
    return answer


def pin_source_ledger(rt, sid, payload):
    """Ghim hàng `E:` cho một hồ sơ vừa ghi — con trỏ kiểm chứng, không phải bản sao nội dung."""
    research_id, version = payload.get('researchId'), payload.get('version')
    if not research_id or not isinstance(version, int) or isinstance(version, bool):
        return None
    try:
        return session_journal.insert_row(
            rt.store, sid, 'evidence',
            f"hồ sơ {research_id} v{version} đã ghi ({payload.get('rows')} dòng sổ)",
            evidence=[{'type': 'file', 'path': payload.get('relativePath'),
                       'note': f"hồ sơ nghiên cứu {research_id} v{version}"}],
            data={'research': {'researchId': research_id, 'version': version,
                               'profile': payload.get('profile'), 'level': payload.get('level'),
                               'gate': payload.get('gate'), 'rows': payload.get('rows')}},
            turn=rt.active_turn.get(sid))
    except Exception:  # pragma: no cover - ghi sổ hỏng chỉ log + đi tiếp (bất biến §5.5)
        system_log.write('research.pin.failed', level='warn', session_id=sid,
                         code='JOURNAL_FAILED', research_id=str(research_id))
        return None


# --------------------------------------------------------------------------- brief (ba mức)


async def research_brief(rt, session, args):
    """`research_brief`: chốt mức + hồ sơ + phòng hồ sơ cho MỘT việc research (chỉ main được gọi).

    Bốn luật ở đây là bốn cách giữ "một mức cho cả việc" (#5961):
    `tier` lạ ⇒ kẹp về mức mặc định + notice; `jobProfile` lạ ⇒ kẹp về nhóm thị trường + notice;
    `ceilingSeconds` chỉ được NGẮN hơn trần của mức; và trong cùng một lượt chỉ được **hạ** mức —
    nâng mức phải xin chủ nhà ở lượt sau (D-24/D-40).
    """
    sid = session['id']
    if session.get('role') != 'orchestrator' or session.get('parent_id'):
        raise PermissionError('research_brief is orchestrator-only (#5961): a child must not choose the '
                              'level — ask the main turn to record it, or note it in your answer')
    question = str(args.get('question') or '').strip()
    if not question:
        raise ValueError('RESEARCH_BRIEF_INVALID: question must not be empty — record the research question verbatim')
    rationale = str(args.get('rationale') or '').strip()
    if not rationale:
        raise ValueError('RESEARCH_BRIEF_INVALID: rationale must not be empty — say why this level is the right one')
    raw_tier = args.get('tier')
    try:
        tier = int(raw_tier)
    except (TypeError, ValueError):
        tier = 0
    defaulted = None
    if tier not in RESEARCH_TIERS:
        defaulted, tier = str(raw_tier), RESEARCH_TIER_DEFAULT
    # P1 (§5.2, cửa 1, M-05): mức 3 CHỈ mở trong mode. Từ chối chứ KHÔNG hạ mức im lặng — hạ mức
    # mà không nói thì người dùng nhận một bản mức 2 tưởng là mức 3.
    if tier >= 3 and _mode_mod().research_mode_available() and _mode_mod().tier3_mode_only() \
            and not _mode_mod().research_mode(session)['on']:
        raise ValueError(f'{RESEARCH_MODE_REQUIRED_CODE}: research mode is off — mức 3 chỉ mở trong mode. '
                         f'Gọi `research_suggest(reason, draftGoal)` để người dùng bật mode, hoặc làm '
                         f'gọn trong mức 2 ở lượt này (không tự hạ mức).')
    existing = research_config(session)
    job_mode = bool(args.get('questions') or args.get('methods') or args.get('goal')
                    or existing.get('jobMode') == 'v2')
    raw_profile = str(args.get('jobProfile') or '').strip()
    # A v2 job is often a mix of documents, papers and user signals. An omitted
    # legacy profile must not silently turn a medical research plan into a
    # price comparison with price/currency fields. Keep the old default only
    # for legacy briefs that still rely on it.
    profile = research_profiles.resolve(raw_profile or ('mixed' if job_mode else 'market'))
    bad_profile = None
    if profile is None:
        bad_profile = raw_profile
        profile = research_profiles.resolve('mixed' if job_mode else 'market')
    limits = research_tier_limits(tier)
    branch_ceiling = limits['branchCeiling']
    owner_views = _owner_views(args.get('ownerViews'))
    branches = [str(item).strip() for item in (args.get('branches') or []) if str(item).strip()]
    dropped_branches = 0 if job_mode else max(0, len(branches) - branch_ceiling)
    if not job_mode:
        branches = branches[:branch_ceiling]
    ceiling, clamped = limits['turnSeconds'], None
    if args.get('ceilingSeconds') is not None:
        try:
            wanted = int(args.get('ceilingSeconds'))
        except (TypeError, ValueError):
            wanted = ceiling
        ceiling = max(60, min(wanted, limits['turnSeconds']))
        if ceiling != wanted:
            clamped = wanted
    # `ceilingSeconds` bỏ trống ⇒ GIỮ trần đã chốt (kẹp theo trần của mức), cho CẢ lượt mới lẫn
    # lượt đang chạy. Phải tính TRƯỚC guard bên dưới: nếu tính sau, một lời gọi "cập nhật" trong
    # cùng lượt (đổi nhánh) mà bỏ trống trần sẽ bị từ chối oan, vì lúc ấy `ceiling` còn là hạn mức
    # danh nghĩa của mức — to hơn trần đang chạy (lượt kiểm thử `v27d` đo được ở probe17 b/c).
    if args.get('ceilingSeconds') is None and existing:
        ceiling = max(60, min(int(existing.get('ceilingSeconds') or 0) or limits['turnSeconds'],
                              limits['turnSeconds']))
        clamped = None
    # Luật "một lượt một việc" và luật "chỉ được HẠ mức" là luật của MỘT LƯỢT: brief nằm trong
    # `config` của PHIÊN nên nếu không ghim lượt, mức đã chốt ở lượt trước khoá phiên ấy vĩnh viễn —
    # main không bao giờ nâng được lên mức 3 dù chủ nhà yêu cầu (lượt sau là lượt MỚI, xem D-24/D-40).
    current_turn = int(rt.active_turn.get(sid) or 0)
    same_turn = bool(existing) and int(existing.get('turn') or 0) == current_turn
    if existing and same_turn:
        # Chủ nhà mở run làm mới (§5.8) không phải mô hình mở việc thứ hai trong cùng lượt: mã run đã
        # được `refresh_run` ghim sẵn, nên luật "một lượt một việc" không áp cho đường chủ nhà.
        if not (args.get('ownerInitiated') or args.get('owner_initiated')) \
                and args.get('researchId') is not None:
            asked = slug_from_question(question, str(args.get('researchId')))
            if asked != existing.get('researchId'):
                raise ValueError(f'{RESEARCH_BRIEF_TAKEN_CODE}: việc research '
                                 f'{existing.get("researchId")!r} đang mở cho lượt này; một lượt chỉ mở '
                                 f'MỘT việc — gộp câu hỏi mới vào việc đang mở, hoặc để lượt sau')
        if int(existing.get('tier') or 0) < tier:
            raise ValueError(f'{RESEARCH_BRIEF_RAISE_REFUSED_CODE}: mức {existing.get("tier")} đã chốt cho '
                             f'việc {existing.get("researchId")!r}; nâng lên mức {tier} phải xin chủ nhà ở '
                             f'lượt sau — tiếp tục trong mức {existing.get("tier")} và gộp bớt nhánh')
        # Trần lượt: luật của MỘT LƯỢT là **chỉ được HẠ** — nâng trần phải xin chủ nhà ở lượt sau, còn
        # hạ thì main tự quyết. Bản trước so NGƯỢC (`stored > ceiling` ⇒ từ chối), nên trong cùng lượt
        # một lời gọi NÂNG trần (900 → 1800) đi qua im lặng còn lời gọi HẠ trần (900 → 600) bị từ chối
        # kèm câu "cần dài hơn thì xin chủ nhà ở lượt sau" — đúng ngược với luật (lượt kiểm thử v27d).
        stored = float(existing.get('ceilingSeconds') or 0)
        if stored and ceiling > stored:
            raise ValueError(f'{RESEARCH_BRIEF_RAISE_REFUSED_CODE}: trần lượt đã chốt '
                             f'{existing.get("ceilingSeconds")}s; cần dài hơn thì xin chủ nhà ở lượt sau')
    slug = slug_from_question(question, args.get('researchId'))
    if job_mode and not same_turn and existing.get('researchId') != slug:
        owner = rt.store.research_job(slug)
        if owner and owner['session_id'] != sid:
            # Stable per-session suffix prevents two independent owners with the
            # same question from sharing a job, dossier and verdict namespace.
            slug = f'{slug[:31].rstrip("-")}-{sid[:8].lower()}'
    # P1 (§5.3): `newRun` mở một RUN mới trong cùng phiên. Run cũ phải đã kết thúc hoặc tạm dừng,
    # và mã run mới phải KHÁC để sổ/hồ sơ hai run không trộn nhau.
    new_run = bool(args.get('newRun') or args.get('new_run'))
    if new_run and existing:
        prior_job = rt.store.research_job(existing.get('researchId'))
        if prior_job is not None and prior_job['status'] not in {'completed', 'partial', 'cancelled',
                                                                 'paused'}:
            raise ValueError(f'RESEARCH_RUN_ACTIVE: run {existing.get("researchId")!r} đang '
                             f'{prior_job["status"]}; tạm dừng hoặc huỷ nó trước khi mở run mới')
        # D-2 (vòng kiểm thử P2–P5): mã run do CHỦ NHÀ chỉ định phải được tôn trọng NGUYÊN VĂN.
        # Giao diện `Cập nhật` ghim sẵn một mã ở `refresh_run`; cộng thêm `-r{n}` ở đây từng sinh
        # mã `r-2-r4-r4` và đổi lén cả mã gõ tay (`r-3-explicit-test` → `r-3-explicit-test-r4`).
        # Chỉ tự sinh hậu tố khi KHÔNG ai chỉ định mã.
        explicit_id = str(args.get('researchId') or '').strip().lower()
        if explicit_id and explicit_id == slug:
            if any(job['research_id'].lower() == explicit_id
                   for job in rt.store.research_jobs_for(sid)):
                raise ValueError(f'RESEARCH_BRIEF_INVALID: researchId {explicit_id!r} đã là một run '
                                 f'của phiên này — run mới phải là một mã RIÊNG')
            slug = explicit_id
        else:
            slug = f'{slug[:27].rstrip("-")}-r{len(rt.store.research_jobs_for(sid)) + 1}'
    inherits = str(args.get('inheritsFrom') or args.get('inherits_from') or '').strip()
    # Một việc = MỘT phòng: hỏi tiếp cùng việc ở lượt sau thì ghi tiếp vào chính phòng ấy (bản `v2`,
    # `v3`… nối tiếp, đúng thứ mà `dossier_versions` đếm), câu hỏi mới ⇒ phòng mới vì phòng đặt tên
    # theo câu hỏi. Phòng cũ chỉ bị thay khi nó KHÔNG khớp khuôn `.research/<slug>-<yyyymmdd-hhmm>`
    # (bản ghi cũ, phòng do tay dựng) — nếu không thì một phòng hỏng sẽ theo phiên ấy mãi.
    dossier_dir = str(existing.get('dossierDir') or '').strip()
    if not re.fullmatch(rf'{re.escape(DOSSIER_ROOM)}/{re.escape(slug)}-\d{{8}}-\d{{4}}', dossier_dir):
        dossier_dir = dossier_dir_for(slug)
    config = {'researchId': slug, 'tier': tier, 'jobProfile': profile.key, 'profileGroup': profile.group,
              'question': question, 'branches': branches, 'ceilingSeconds': ceiling,
              'ownerViews': owner_views,
              'dossierDir': dossier_dir, 'startedAt': journal.utc_now_iso(), 'rationale': rationale,
              'waves': limits['waves'], 'waveSize': limits['waveSize'],
              'hardCeilingSeconds': limits['hardCeilingSeconds'], 'mode': 'brief',
              'turn': current_turn}
    if job_mode or existing.get('jobMode') == 'v2':
        config['jobMode'] = 'v2'
        previous = rt.store.research_job(slug)
        raw_questions = args.get('questions') if isinstance(args.get('questions'), list) else None
        questions = []
        for index, item in enumerate(raw_questions or []):
            if isinstance(item, dict):
                wording = str(item.get('text') or '').strip()
                importance = str(item.get('importance') or 'medium').lower()
                done_when = str(item.get('doneWhen') or '').strip()
            else:
                wording, importance, done_when = str(item).strip(), 'medium', ''
            if wording:
                questions.append({'id': f'q{index + 1}', 'text': wording[:1000],
                                  'importance': importance if importance in ('high', 'medium', 'low') else 'medium',
                                  'doneWhen': done_when[:1000], 'status': 'unexplored'})
        if not questions and previous:
            questions = previous['state'].get('questions') or []
        if not questions:
            questions = [{'id': 'q1', 'text': question, 'importance': 'high',
                          'doneWhen': '', 'status': 'unexplored'}]
        prior_state = previous['state'] if previous else {}
        methods = [str(item).strip()[:80] for item in (args.get('methods') or [])
                   if str(item).strip()][:12]
        try:
            budget = int(args.get('budgetSeconds') or prior_state.get('budgetSeconds')
                         or limits['hardCeilingSeconds'])
        except (TypeError, ValueError):
            budget = limits['hardCeilingSeconds']
        budget = max(60, min(budget, 86400))
        output = str(args.get('output') or prior_state.get('output') or '')[:1000]
        required_reviews = _choose_review_modes(
            tier, questions, output, args.get('scope') or prior_state.get('scope'))
        required_reviews = [mode for mode in research_review.REVIEW_MODES
                            if mode in required_reviews or mode in _review_modes_for(prior_state, 0)]
        state = {**prior_state, 'goal': str(args.get('goal') or prior_state.get('goal') or question)[:2000],
                 'question': question, 'questions': questions,
                 'methods': methods or prior_state.get('methods') or [],
                 'output': output,
                 'branches': branches, 'tier': tier, 'budgetSeconds': budget,
                 'reviewModes': required_reviews,
                 'findings': prior_state.get('findings') or [],
                 'blockedSources': prior_state.get('blockedSources') or [],
                 # P1 (§5.2/5.3): `origin` nói job này thuộc mode hay do main tự mở — bơm chỉ chạy
                 # job `origin='mode'`; `phase` là pha chi tiết mà bơm/API/giao diện đọc.
                 'origin': (prior_state.get('origin')
                            or (RESEARCH_JOB_ORIGIN if _mode_mod().research_mode(session)['on']
                                else RESEARCH_JOB_ORIGIN_MAIN)),
                 'phase': prior_state.get('phase') or 'clarifying',
                 'background': bool(prior_state.get('background'))}
        rt.store.research_job_save(slug, sid, state,
                                   status=previous['status'] if previous else 'scoping')
        # P1 (§5.3, F3): run do MODE mở phải được ghim làm `researchMode.activeRunId`. Thiếu dòng
        # này thì bơm không bao giờ thấy nó (`server.research_job_pumpable` đòi `mode.on` VÀ
        # `activeRunId == job id`) — thiết kế \"lượt ngắn ≤ 600 s rồi tiếp bằng bơm\" chết, và
        # `POST /prompts/{id}/answer` trả `resume: true` mà không mở lượt nào. Chỉ ghim khi mode
        # đang BẬT: việc nhẹ do main tự mở (`origin='main'`) không được giành quyền bơm.
        mode_now = _mode_mod().research_mode(session)
        if state.get('origin') == RESEARCH_JOB_ORIGIN and mode_now['on']:
            mode_now['activeRunId'] = slug
            session.setdefault('config', {})['researchMode'] = mode_now
    inherited_rows = _copy_inherited_rows(rt, sid, inherits, slug) if inherits else 0
    if inherits:
        # Dòng kế thừa phải qua `source_verify` LẠI trước khi dùng cho nhận định "hiện tại" (§5.3).
        config['inheritsFrom'] = inherits
    session.setdefault('config', {})['research'] = config
    # `save` chỉ ghi MESSAGES, nên brief nằm trong `config` phải đi qua `update_config`: không có
    # dòng này thì mức/hồ sơ/phòng hồ sơ biến mất ở lượt sau (harness đọc lại phiên từ store).
    rt.store.update_config(sid, session['config'])
    notices = []
    if defaulted is not None:
        notices.append((RESEARCH_TIER_DEFAULTED_CODE,
                        f'mức {defaulted!r} không thuộc {{1,2,3}} — dùng mức {tier} (mặc định)'))
        system_log.write('research.brief.tier_defaulted', level='warn', session_id=sid,
                         code=RESEARCH_TIER_DEFAULTED_CODE, value=defaulted, tier=tier)
    if bad_profile is not None:
        notices.append((RESEARCH_PROFILE_INVALID_CODE,
                        f'hồ sơ {bad_profile!r} không có trong danh mục — dùng {profile.key!r}'))
        system_log.write('research.brief.profile_defaulted', level='warn', session_id=sid,
                         code=RESEARCH_PROFILE_INVALID_CODE, value=bad_profile, profile=profile.key)
    if clamped is not None:
        notices.append((RESEARCH_CEILING_CLAMPED_CODE,
                        f'ceilingSeconds {clamped} vượt trần của mức {tier} ({limits["turnSeconds"]}s) — '
                        f'dùng {ceiling}s'))
    if dropped_branches:
        notices.append(('RESEARCH_BRANCHES_CLAMPED',
                        f'{dropped_branches} nhánh vượt trần mức {tier} ({branch_ceiling}) đã bị bỏ khỏi brief'))
    if owner_views and not job_mode:
        # #6025 — tự động, không hỏi lại: brief có ý kiến/giả định ⇒ pha phản biện PHẢI có mục riêng
        # ba nhãn, mỗi nhãn kèm nguồn. Câu này nói cho main biết hợp đồng ấy ngay lúc chốt brief.
        notices.append((RESEARCH_OWNER_VIEWS_CODE,
                        f'{len(owner_views)} ý kiến chủ nhà đã ghi — hồ sơ phải có mục soi ý kiến đủ ba '
                        f'nhãn {", ".join(label for label, _ in research_quality.OWNER_VIEW_LABELS)}, '
                        f'mỗi nhãn kèm nguồn'))
    # "Cập nhật" chỉ có nghĩa khi brief ĐỔI: gọi lại y hệt (model lặp một lời gọi) không được ghim
    # thêm hàng `D:` — hàng `D:` để lại dấu vết của một QUYẾT ĐỊNH, không phải của một lời gọi.
    changed = (not existing) or any(existing.get(key) != config.get(key) for key in
                                    ('tier', 'jobProfile', 'question', 'branches', 'ceilingSeconds',
                                     'researchId', 'ownerViews'))
    updated = bool(existing) and changed
    if updated:
        notices.append((RESEARCH_BRIEF_UPDATED_CODE, f'brief của {slug} đã được cập nhật (mức {tier})'))
    elif existing:
        notices.append((RESEARCH_BRIEF_UPDATED_CODE, f'brief của {slug} giữ nguyên (mức {tier})'))
    for code, message in notices:
        rt.store.emit(sid, 'notice', {'code': code, 'tier': tier, 'partial': False,
                                      'message': f'{code}: {message}'})
    requires_critique = bool(limits['critique'] or
                             (job_mode and 'critique' in state.get('reviewModes', [])))
    rt.store.emit(sid, 'notice', {'code': 'RESEARCH_BRIEF', 'tier': tier, 'jobProfile': profile.key,
                                  'profileLabel': research_profiles.label_of(profile.key),
                                  'dossierDir': dossier_dir, 'branches': branches,
                                  'ceilingSeconds': ceiling, 'partial': False,
                                  'message': (f'RESEARCH_BRIEF: mức {tier} · {research_profiles.label_of(profile.key)} '
                                              f'· phòng {dossier_dir} · trần {ceiling}s'
                                              f'{" · có phản biện độc lập" if requires_critique else ""}')})
    system_log.write('research.brief', level='info', session_id=sid, code='RESEARCH_BRIEF', tier=tier,
                     profile=profile.key, dossierDir=dossier_dir, branches=len(branches),
                     ceilingSeconds=ceiling, updated=updated)
    if changed:
        try:
            await session_journal.append(
                rt.executor, rt.store, sid, 'decision',
                f'mức {tier} · hồ sơ {profile.key} · {len(branches)} nhánh · trần {ceiling}s',
                data={'kind': 'research-brief', 'researchId': slug, 'tier': tier,
                      'jobProfile': profile.key, 'dossierDir': dossier_dir, 'branches': branches,
                      'ceilingSeconds': ceiling, 'rationale': rationale, 'updated': updated},
                turn=rt.active_turn.get(sid))
        except Exception:  # pragma: no cover - ghi sổ hỏng ⇒ log + đi tiếp (bất biến §5.5)
            system_log.write('research.brief.journal_failed', level='warn', session_id=sid,
                             code='JOURNAL_FAILED', researchId=slug)
    extended = None
    if int(ceiling) > int(rt.current_turn_seconds(sid)):
        extended = await rt.extend_research_budget(sid, tier=tier, ceiling=ceiling)
    answer = {'researchId': slug, 'tier': tier, 'jobProfile': profile.key,
              'profileLabel': research_profiles.label_of(profile.key), 'dossierDir': dossier_dir,
              'branchCeiling': branch_ceiling, 'waves': limits['waves'], 'waveSize': limits['waveSize'],
              'childSteps': limits['childSteps'], 'childSeconds': limits['childSeconds'],
              'turnSeconds': limits['turnSeconds'], 'softCeilingSeconds': limits['softCeilingSeconds'],
              # `ceilingSeconds` là trần ĐANG có hiệu lực (có thể là con số giữ lại từ lượt trước), còn
              # `turnSeconds`/`softCeilingSeconds`/`hardCeilingSeconds` là hạn mức DANH NGHĨA của mức:
              # lượt sau nâng mức mà bỏ trống trần thì hạn mức mức mới to hơn trần đang chạy, nên thiếu
              # khoá này thì thẻ mốc báo một con số không ai thi hành (lượt kiểm thử v27d, F-H).
              'ceilingSeconds': ceiling,
              'hardCeilingSeconds': limits['hardCeilingSeconds'], 'critique': requires_critique,
              'ownerViews': owner_views, 'updated': updated, 'extendedTurn': bool(extended),
              'inheritsFrom': inherits or None, 'inheritedRows': inherited_rows,
              'next': f'delegate_task(role="research", …) mở đầu context bằng '
                      f'"Mức: {tier} · hồ sơ: {profile.key} · phòng hồ sơ: {dossier_dir}"'}
    if config.get('jobMode') == 'v2':
        job = rt.store.research_job(slug)
        answer['job'] = {'status': job['status'], 'budgetSeconds': job['state']['budgetSeconds'],
                         'reviewModes': job['state'].get('reviewModes', []),
                         'questions': [{'id': item['id'], 'text': item['text'],
                                        'status': item['status']}
                                       for item in job['state']['questions']]}
        answer['next'] += (' — pass an exact lowercase `questionId` from `job.questions` '
                           'for every research branch; e.g. `q1`, not a label like `Q1`')
    if limits['waves'] > 1:
        answer['next'] += (f' — tối đa {limits["waves"]} sóng × {limits["waveSize"]} nhánh; hết sóng thì gộp '
                           f'báo cáo, đừng mở nhánh mới')
    review_modes = state.get('reviewModes', []) if job_mode else []
    if limits['critique'] or review_modes:
        answer['next'] += (' — sau khi viết hồ sơ, main giao research-review và gọi research_verify '
                           f'cho đúng bản ở các chế độ {", ".join(review_modes or ["critique"])}; '
                           'chừa ngân sách cho kiểm chứng và phản biện trước khi kết luận')
    if owner_views and not job_mode:
        answer['next'] += (f' — brief có {len(owner_views)} ý kiến chủ nhà: hồ sơ phải có mục soi ý kiến '
                           f'đủ ba nhãn {", ".join(label for label, _ in research_quality.OWNER_VIEW_LABELS)}, '
                           f'mỗi nhãn kèm nguồn')
    answer['notices'] = [code for code, _ in notices]
    return answer


def brief_mode(env=None) -> tuple[str, str | None]:
    """`(mode, unknown)` của cổng mềm thiếu brief."""
    return _mode(RESEARCH_BRIEF_ENV, RESEARCH_BRIEF_MODES, RESEARCH_BRIEF_DEFAULT_MODE, env)


def branch_limit_check(rt, session, role):
    """Cổng đếm nhánh theo mức (#5982): chỉ áp khi lượt này ĐÃ có brief, và chỉ với `role='research'`."""
    if role != 'research':
        return None
    cfg = research_config(session)
    tier = int(cfg.get('tier') or 0)
    if not tier:
        return None
    if cfg.get('jobMode') == 'v2':
        job = rt.store.research_job(cfg.get('researchId'))
        if job and job['status'] in {'paused', 'cancelled', 'completed', 'partial'}:
            raise ValueError(f'RESEARCH_JOB_NOT_ACTIVE: {job["status"]}')
        if job and rt.store.research_job_used_seconds(session['id'], cfg.get('researchId')) >= \
                int(job['state'].get('budgetSeconds') or 0):
            raise ValueError('RESEARCH_JOB_BUDGET_EXHAUSTED')
        return len([row for row in rt.store.children_of(session['id'], turn=rt.active_turn.get(session['id']))
                    if row.get('role') == 'research'])
    sid = session['id']
    ceiling = research_tier_limits(tier)['branchCeiling']
    opened = 0
    for row in rt.store.children_of(sid, turn=rt.active_turn.get(sid)):
        if row.get('role') == 'research':
            opened += 1
    if opened >= ceiling:
        raise ValueError(f'{RESEARCH_BRANCH_LIMIT_CODE}: mức {tier} cho tối đa {ceiling} nhánh research '
                         f'trong lượt này (đã mở {opened}); gộp nhánh lại — việc liên quan phải nằm trong '
                         f'MỘT con — hoặc xin chủ nhà nâng mức ở lượt sau')
    return opened


def _brief_missing_notice(rt, sid, mode, message):
    """Một notice `RESEARCH_BRIEF_MISSING` (không dùng dedup của đường cũ: đây là cổng theo lượt)."""
    rt.store.emit(sid, 'notice', {'code': RESEARCH_BRIEF_MISSING_CODE, 'mode': mode, 'partial': False,
                                 'message': f'{RESEARCH_BRIEF_MISSING_CODE}: {message}'})


def unbriefed_turn_branches(rt, session):
    """Số nhánh research đã mở trong LƯỢT này (dùng cho luật cửa 2, §5.2)."""
    sid = session['id']
    return [row for row in rt.store.children_of(sid, turn=rt.active_turn.get(sid))
            if row.get('role') == 'research']


def quick_lookup_clamp(rt, session, role):
    """Cửa 2 (§5.2, M-07): NGOÀI mode, nhánh research ĐẦU TIÊN không brief là tra cứu nhanh, và phải
    chạy trong trần MỨC 1 (20 bước/180 s). Trả `None` khi luật không áp (trong mode, đã có brief,
    hoặc không phải nhánh research)."""
    if role != 'research' or has_research_brief(session):
        return None
    runtime_module = _mode_mod()
    if not runtime_module.research_mode_available() or runtime_module.research_mode(session)['on']:
        return None
    limits = research_tier_limits(1)
    return {'tier': 1, 'childSteps': limits['childSteps'], 'childSeconds': limits['childSeconds']}


def missing_brief_gate(rt, session, role):
    """Cổng `RESEARCH_BRIEF_MISSING` (cửa 2, §5.2/M-07).

    Công tắc `BOXFOX_RESEARCH_MODE=off` ⇒ giữ nguyên hành vi cũ (`BOXFOX_RESEARCH_BRIEF` mặc định
    `warn`). Khi tính năng bật: trong mode MỌI nhánh phải có brief; ngoài mode nhánh ĐẦU TIÊN được
    coi là tra cứu nhanh, từ nhánh thứ hai trở đi thì từ chối.
    """
    mode, unknown = brief_mode()
    sid = session['id']
    if unknown is not None:
        mode_notice(rt, sid, RESEARCH_BRIEF_MODE_UNKNOWN_CODE, RESEARCH_BRIEF_ENV, unknown,
                    RESEARCH_BRIEF_DEFAULT_MODE)
    if mode == 'off' or role != 'research' or has_research_brief(session):
        return False
    runtime_module = _mode_mod()
    if not runtime_module.research_mode_available():
        # Công tắc TẮT ⇒ giữ NGUYÊN hành vi f17d54b: cổng MỀM `warn` (notice một lần/lượt, không chặn)
        # và `enforce` (từ chối). P1 không được đổi hành vi mặc định của repo.
        if rt._notice_seen(sid, RESEARCH_BRIEF_MISSING_CODE):
            return False
        system_log.write('research.brief.missing', level='warn', session_id=sid,
                         code=RESEARCH_BRIEF_MISSING_CODE, mode=mode)
        rt.store.emit(sid, 'notice', {
            'code': RESEARCH_BRIEF_MISSING_CODE, 'mode': mode, 'partial': False,
            'message': (f'{RESEARCH_BRIEF_MISSING_CODE}: lượt này giao việc research mà chưa gọi '
                        f'`research_brief` — mức/hồ sơ/phòng hồ sơ chưa được chốt, nên trần theo mức và '
                        f'cổng chất lượng hồ sơ không áp. Gọi `research_brief` rồi giao lại.')})
        if mode == 'enforce':
            raise ValueError(f'{RESEARCH_BRIEF_MISSING_CODE}: gọi `research_brief` trước khi '
                             f'delegate_task(role="research")')
        return True
    opened = len(unbriefed_turn_branches(rt, session))
    if runtime_module.research_mode(session)['on']:
        _brief_missing_notice(rt, sid, mode, 'trong mode mọi nhánh research phải có mức và câu hỏi '
                                             '(`research_brief` + `questionId`) — gọi `research_brief` '
                                             'rồi giao lại')
        raise ValueError(f'{RESEARCH_BRIEF_MISSING_CODE}: trong mode mọi nhánh research phải có brief; '
                         f'gọi `research_brief` (mức 1–3) rồi giao lại với `questionId`')
    if opened:
        _brief_missing_notice(rt, sid, mode, 'ngoài mode chỉ nhánh research ĐẦU TIÊN được tra cứu nhanh; '
                                             'gọi `research_brief` trước khi mở nhánh thứ hai')
        raise ValueError(f'{RESEARCH_BRIEF_MISSING_CODE}: nhánh research thứ hai trong lượt phải có brief — '
                         f'gọi `research_brief` trước khi `delegate_task(role="research")`')
    system_log.write('research.brief.quick_lookup', level='info', session_id=sid,
                     code=RESEARCH_BRIEF_MISSING_CODE, tier=1)
    rt.store.emit(sid, 'notice', {
        'code': RESEARCH_BRIEF_MISSING_CODE, 'mode': mode, 'partial': False,
        'message': (f'{RESEARCH_BRIEF_MISSING_CODE}: nhánh đầu tiên không brief — coi là tra cứu nhanh, '
                    f'chạy trong trần mức 1 ({RESEARCH_TIER_CHILD_STEPS[1]} bước/'
                    f'{RESEARCH_TIER_CHILD_SECONDS[1]} s). Việc lớn hơn thì gọi `research_brief`')})
    return True


# --------------------------------------------------------------------------- hồ sơ (C-2)


def _dossier_rows(rt, sid, row_ids=None) -> list:
    items = _rows_of(rt, sid)
    if row_ids:
        wanted = {str(item) for item in row_ids}
        items = [item for item in items if item.row_id in wanted]
    return items


def _verified_map(rows) -> dict:
    """`{rowId: matched}` đọc từ `payload.verify` — cái đã đi qua `source_verify`."""
    out = {}
    for row in rows:
        verify = (row.payload or {}).get('verify')
        if isinstance(verify, dict):
            out[row.row_id] = bool(verify.get('matched'))
        elif row.status in ('ok', 'stale'):
            out[row.row_id] = row.status == 'ok'
    return out


def _planned_children(rt, sid) -> list:
    """Mã các phiên con `research` của lượt này — luật `research-lineage-missing` đọc theo đây."""
    turn = rt.active_turn.get(sid)
    return [str(row['session_id']) for row in rt.store.children_of(sid, turn=turn)
            if row.get('role') == 'research']


def _dossier_tables(raw) -> list:
    """Bảng kèm hồ sơ, chuẩn hoá về `[{'name','markdown'}]` — dạng box ghi thành `tables/<tên>.md`.

    Lược đồ công bố của `dossier_write.tables` là LIST; đo được bản cũ chỉ nhận `dict`, nên model gửi
    đúng lược đồ thì bảng **mất âm thầm**, còn `{}` thì bị biến thành `[{}]` và box giết cả lần ghi.
    Không có bảng ⇒ `[]` (box không dựng thư mục `tables/`).
    """
    out = []
    if isinstance(raw, dict):
        pairs = raw.items()
    elif isinstance(raw, list):
        pairs = [(item.get('name'), item.get('markdown')) for item in raw if isinstance(item, dict)]
    else:
        return []
    for name, body in pairs:
        name, body = str(name or '').strip(), str(body or '')
        if name and body.strip():
            out.append({'name': name, 'markdown': body})
    return out


def _scope_time_window(rt, research_id, job):
    """`(surveyDate, window_days, velocity)` của run — đọc từ THẺ PHẠM VI, không hỏi mô hình.

    Chạy kiểu cũ (không có `job`) ⇒ mốc khảo sát là hôm nay và `window_days = 0`, nên cổng chính
    sách thời gian đứng yên đúng như hành vi `6eb2fd8`.
    """
    state = (job or {}).get('state') or {}
    scope = state.get('scope') if isinstance(state.get('scope'), dict) else {}
    policy = scope.get('timePolicy') if isinstance(scope.get('timePolicy'), dict) else {}
    velocity = str(policy.get('velocity') or '')
    survey = str(scope.get('surveyDate') or '') or research_evidence.survey_date()
    return survey, research_evidence.window_days(velocity), velocity


def _changelog_body(rt, research_id, version) -> str:
    """`changelog.md` của kiểu việc `refresh` (§5.8).

    Run làm mới (`state.refreshOf`) ghi bản so NGUỒN với run gốc; run thường giữ nguyên danh sách
    các bản đã ghi — tệp cũ đọc y như trước.
    """
    job = rt.store.research_job(research_id)
    state = dict(job['state'] or {}) if job else {}
    source_id = str(state.get('refreshOf') or '').strip()
    if source_id:
        return refresh_changelog(rt, job['session_id'], source_id, research_id, version=version)
    lines = ['# Nhật ký thay đổi', '']
    for item in rt.store.dossier_versions(research_id):
        lines.append(f'- bản v{int(item)}')
    lines.append(f'- bản v{int(version)} (bản này)')
    return '\n'.join(lines) + '\n'


def _refresh_mode(env=None) -> tuple[str, str | None]:
    """`(mode, unknown)` của công tắc làm mới (`off` ⇒ API từ chối `action='refresh'`)."""
    return _mode(RESEARCH_REFRESH_ENV, RESEARCH_REFRESH_MODES, RESEARCH_REFRESH_DEFAULT_MODE, env)


def _row_urls(rt, sid, research_id) -> dict:
    """Dòng sổ của MỘT run, khoá theo URL — dòng không có URL thì bỏ (không so được).

    Đọc SỔ NGUỒN chứ không đọc cặp (nhận định, đoạn trích): nguồn kế thừa từ run gốc chỉ nằm ở sổ
    (chưa qua `evidence_link`), mà `changelog.md` phải kể được cả chúng. Cùng một URL có nhiều dòng
    (làn sóng sau đọc lại) thì dòng MỚI NHẤT là dòng đại diện.
    """
    out = {}
    for row in rt.store.source_rows(sid, research_id=research_id, limit=SOURCE_ROW_LIMIT_MAX,
                                    newest_first=True):
        url = str(row.get('url') or '').strip()
        if url:
            out.setdefault(url, row)
    return out


def _row_inherited(row) -> bool:
    """Dòng này là dòng CHÉP từ run gốc (`payload.inherited`, §5.3) hay không."""
    payload = row.get('payload')
    if isinstance(payload, str):
        try:
            payload = json.loads(payload or '{}')
        except ValueError:
            return False
    return bool((payload or {}).get('inherited'))


def _row_changed(before, after) -> bool:
    """Một nguồn ĐỔI khi trạng thái, đoạn trích hoặc mức truy cập khác đi (§5.8)."""
    for key in ('status', 'excerpt', 'accessLevel'):
        if str(before.get(key) or '') != str(after.get(key) or ''):
            return True
    return False


def _row_line(row) -> str:
    """Một dòng changelog: nguồn, tầng, trạng thái, nhận định, độ dài đoạn trích."""
    return (f'- {row.get("url") or ""} · tầng {row.get("tier")} · {row.get("status") or "chưa rõ"} · '
            f'{row.get("accessLevel") or "snippet"} · {str(row.get("claim") or "")[:120]} · đoạn trích '
            f'{len(str(row.get("excerpt") or ""))} ký tự')


def refresh_changelog(rt, sid, source_id, research_id, *, version=0) -> str:
    """`changelog.md` của một lần làm mới: Nguồn mới / đổi / rút / giữ nguyên (§5.8).

    So hai run theo URL nguồn. "Rút" gồm cả nguồn biến mất khỏi run mới LẪN nguồn mang trạng thái
    rút (`limits.RESEARCH_REFRESH_WITHDRAWN_STATUSES`). Mốc khảo sát cũ đọc từ `state.refreshSince`
    của run làm mới — con số của lượt mở run, không suy lại theo giờ đọc tệp.
    """
    job = rt.store.research_job(research_id)
    state = dict(job['state'] or {}) if job else {}
    before = _row_urls(rt, sid, source_id)
    after = _row_urls(rt, sid, research_id)
    new_rows, changed, withdrawn, kept = [], [], [], []
    for url, row in after.items():
        old = before.get(url)
        if old is None:
            new_rows.append(row)
        elif _row_inherited(row):
            # Dòng chép từ run gốc CỐ Ý mang `unverified`: nguồn không đổi, chỉ phải xác minh lại —
            # xếp vào "giữ nguyên" để nhóm "đổi" nói về nguồn, không nói về cờ nội bộ.
            kept.append(row)
        elif str(row.get('status') or '') in RESEARCH_REFRESH_WITHDRAWN_STATUSES:
            withdrawn.append(row)
        elif _row_changed(old, row):
            changed.append(row)
        else:
            kept.append(row)
    for url, row in before.items():
        if url not in after:
            withdrawn.append(row)
    lines = ['# Nhật ký thay đổi', '',
             f'- Run gốc: `{source_id}`',
             f'- Run làm mới: `{research_id}`',
             f'- Mốc khảo sát cũ: {state.get("refreshSince") or "không rõ"}',
             f'- Bản hồ sơ: v{int(version or 0)}']
    for title, rows in (('Nguồn mới', new_rows), ('Nguồn đổi', changed),
                        ('Nguồn rút', withdrawn), ('Nguồn giữ nguyên', kept)):
        lines.append('')
        lines.append(f'## {title} ({len(rows)})')
        lines.extend(_row_line(row) for row in rows)
    return '\n'.join(lines) + '\n'


def evidence_rows(rt, sid, research_id, limit=50):
    """Hàng bằng chứng của MỘT run cho giao diện (§5.12, bảng 4.8) — read-only.

    Cặp (nhận định, đoạn trích, nguồn) của chính run, kèm mức truy cập của đoạn trích, quan hệ đã
    soát và độ tin cậy trong `research_claim_meta`. Sổ hỏng hay thiếu thì trả `[]`: đường đọc của
    giao diện không được vỡ vì dữ liệu phụ.
    """
    try:
        rows = list(rt.store.evidence_claims(sid, research_id) or [])
    except Exception:  # pragma: no cover - phòng khi DB cũ thiếu bảng P2
        rows = []
    try:
        meta = {str(item.get('claimId') or ''): item
                for item in (rt.store.claim_meta_list(research_id) or [])}
    except Exception:  # pragma: no cover
        meta = {}
    rows.sort(key=lambda item: int(item.get('rowSeq') or 0), reverse=True)
    out = []
    for item in rows[:max(1, int(limit))]:
        claim_id = str(item.get('claimId') or '')
        declared = meta.get(claim_id) or {}
        out.append({'rowId': item.get('rowId') or '', 'claimId': claim_id,
                    'claim': item.get('text') or '', 'url': item.get('url') or '',
                    'excerpt': item.get('excerpt') or '', 'host': item.get('host') or '',
                    'origin': item.get('origin') or '', 'tier': int(item.get('tier') or 0),
                    'status': item.get('status') or '',
                    'accessLevel': item.get('accessLevel') or 'snippet',
                    'sourceAccessLevel': item.get('sourceAccessLevel') or '',
                    'sectionKind': item.get('sectionKind') or '',
                    'eventDate': item.get('eventDate') or '',
                    'publishedAt': item.get('publishedAt') or '',
                    'updatedAt': item.get('updatedAt') or '',
                    'originCluster': item.get('originCluster') or '',
                    'sourceKind': item.get('sourceKind') or '',
                    'relation': item.get('relation') or '',
                    'confidence': declared.get('confidence') or 'unknown',
                    'confidenceCap': declared.get('confidenceCap') or 'unknown',
                    'claimType': declared.get('claimType') or '',
                    'stanceOrigin': declared.get('stanceOrigin') or '',
                    'questionId': declared.get('questionId') or '',
                    'facetId': declared.get('facetId') or ''})
    return out


def _dossier_sidecars(rt, research_id, version, *, report=None, coverage=None, scope=None,
                      job_types=(), extractions=None) -> dict:
    """Tệp phụ của run, TÊN lấy từ `research_report.sidecar_names()` — không chép tay tên nào.

    Chỉ trả những tệp có nội dung; thiếu dữ liệu (ví dụ không có `report`) thì không ghi tệp rỗng —
    một tệp rỗng trông y như một tệp hỏng với người đọc.
    """
    entries = [item for item in (extractions or []) if isinstance(item, dict)]
    names = research_report.sidecar_names(version, job_types=job_types, extractions=entries)
    claims = _claim_metas(rt, research_id)
    body = {
        f'v{int(version)}-scope.json': json.dumps(scope or {}, ensure_ascii=False, indent=2),
        f'v{int(version)}-coverage.json': (json.dumps(coverage, ensure_ascii=False, indent=2)
                                           if coverage else ''),
        f'v{int(version)}-claims.jsonl': ''.join(json.dumps(item, ensure_ascii=False) + '\n'
                                                 for item in claims),
        f'v{int(version)}-report.json': (json.dumps(report, ensure_ascii=False, indent=2)
                                         if report else ''),
        'changelog.md': _changelog_body(rt, research_id, version),
    }
    for item in entries:
        source_id = str(item.get('sourceId') or item.get('source_id') or '').replace('/', '-')
        if source_id:
            body[f'extractions/{source_id}.json'] = json.dumps(item, ensure_ascii=False, indent=2)
    return {name: body[name] for name in names if str(body.get(name) or '').strip()}


def _dossier_op_args(path, markdown, rows, args, tables, review, title, *, sidecars=None):
    """Tham số cho op `dossier_write` của box — một chỗ, để hợp đồng với worker đọc được một lần."""
    return {
        'path': path,
        'markdown': markdown,
        'title': title,
        'rows': [{'rowId': row.row_id, 'claim': row.claim, 'url': row.url, 'host': row.host,
                  'tier': row.tier, 'type': row.type, 'excerpt': row.excerpt,
                  'fetchedAt': row.fetched_at, 'origin': row.origin, 'method': row.method,
                  'status': row.status} for row in rows],
        'tables': tables,
        'review': review,
        'overwrite': bool(args.get('overwrite')),
        # P2 (§7.7): tệp phụ của run, đúng lược đồ DANH SÁCH của op; vắng ⇒ `[]` (đường cũ ghi đúng
        # bộ tệp như `6eb2fd8`).
        'sidecars': ([{'name': str(name), 'content': str(body)} for name, body in sidecars.items()]
                     if isinstance(sidecars, dict) else list(sidecars or [])),
    }


async def dossier_write(rt, session, args):
    """`dossier_write`: cổng chất lượng chạy TRƯỚC, rồi mới ghi hồ sơ vào `.research/`.

    Thứ tự ba bước là phần cốt lõi: (1) đọc sổ + hồ sơ + lượt con để máy chấm; (2) `enforce` ⇒ ném
    `RESEARCH_QUALITY_REJECTED` kèm từng dòng thiếu và cách sửa, **không** chạm đĩa; (3) chỉ khi qua
    (hoặc `warn`) mới gọi op của box, rồi ghim hàng `E:` trỏ vào tệp vừa ghi.
    """
    sid = session['id']
    # Hồ sơ do MAIN ghi (ledger subplan §A3.5): nhánh con `research` chỉ để lại dòng sổ + bản tóm tắt,
    # nên cổng vai ở đây là orchestrator. Một nhánh gọi thẳng cũng bị từ chối, không chỉ thiếu tên
    # công cụ trong `config['tools']`.
    if session.get('role') != 'orchestrator':
        raise PermissionError('dossier_write is for the orchestrator — a research branch reports its '
                              'ledger rows up and main writes the dossier')
    cfg = research_config(session)
    research_id = str(args.get('researchId') or cfg.get('researchId') or '').strip().lower()
    if not research_id or not re.fullmatch(RESEARCH_SLUG_RE, research_id):
        raise ValueError(f'RESEARCH_ID_INVALID: researchId {research_id!r} is not a slug — use the id '
                         f'`research_brief` returned, format {RESEARCH_SLUG_RE}')
    # Một lượt chỉ mở MỘT việc: brief đang mở việc nào thì hồ sơ phải ghi cho việc ấy. Bản trước nhận
    # id lạ rồi vẫn ghi vào PHÒNG của brief — hàng `E:` và bản ghi hồ sơ trỏ vào một việc khác với
    # id ghi trong header (hai danh tính cho cùng một tệp).
    brief_id = str(cfg.get('researchId') or '').strip().lower()
    if brief_id and brief_id != research_id:
        raise ValueError(f'{RESEARCH_BRIEF_TAKEN_CODE}: brief của lượt này đang mở việc {brief_id!r}; '
                         f'hồ sơ phải ghi cho việc ấy (nhận được {research_id!r})')
    try:
        level = int(args.get('level'))
    except (TypeError, ValueError):
        level = 0
    if level not in (1, 2, 3):
        raise ValueError(f'{RESEARCH_LEVEL_INVALID_CODE}: level must be 1, 2 or 3 (got '
                         f'{args.get("level")!r}) — mức quyết định khuôn hồ sơ và cổng chất lượng')
    profile_key = str(args.get('profile') or cfg.get('jobProfile') or '').strip().lower()
    profile = research_profiles.get(profile_key) or research_profiles.resolve(profile_key)
    if profile is None:
        raise ValueError(f'{RESEARCH_PROFILE_INVALID_CODE}: unknown profile {profile_key!r} — one of '
                         f'{", ".join(sorted(research_profiles.PROFILE_LABELS))}')
    markdown = str(args.get('markdown') or '')
    if not markdown.strip():
        raise ValueError('DOSSIER_INVALID: markdown must be a non-empty string')
    tier_limits = research_tier_limits(level)
    job = rt.store.research_job(research_id) if cfg.get('jobMode') == 'v2' else None
    review_modes = _review_modes_for(job['state'] if job else None, level)
    # The writer cannot certify its own independent critique. A verdict belongs
    # to this *written version* and can only be recorded after the review child.
    critique_arg = 'none' if cfg.get('jobMode') == 'v2' else str(args.get('critique') or 'none').strip().lower()
    if critique_arg not in research_header.CRITIQUE_VALUES:
        critique_arg = 'none'
    rows = _dossier_rows(rt, sid, args.get('rows'))
    if len(rows) > RESEARCH_MAX_ROWS_PER_DOSSIER:
        rows = rows[:RESEARCH_MAX_ROWS_PER_DOSSIER]
    # V2 grades the decisive claims and the question map. A branch that was
    # cancelled, blocked, or found no evidence must be able to report that
    # outcome without inventing a ledger row to satisfy the legacy lineage gate.
    children = [] if cfg.get('jobMode') == 'v2' else _planned_children(rt, sid)
    # --- P2: cổng cấu trúc · cổng thời gian · bản đồ bao phủ -------------------
    # Hồ sơ ghi cho việc nào thì sổ/mức tin cậy/facet đọc theo việc ấy.
    owner, _owner_child = _ledger_owner(rt, session, sid)
    report = args.get('report') if isinstance(args.get('report'), dict) else None
    job_scope = ((job or {}).get('state') or {}).get('scope') if job else None
    job_scope = job_scope if isinstance(job_scope, dict) else {}
    job_types = research_report.normalize_job_types(job_scope.get('jobKinds') or ())
    survey_value, window_value, _velocity = _scope_time_window(rt, research_id, job)
    coverage = coverage_refresh(rt, research_id, write=True)
    claim_ids = [str(item.get('claimId') or '')
                 for item in (rt.store.evidence_claims(owner, research_id) or [])]
    stale_issues = stale_current_issues(rt, owner, research_id, report=report,
                                       window_days=window_value, as_of=survey_value)
    # Mức tin cậy của mọi nhận định chính do MÁY chấm từ sổ; mô hình chỉ hạ được (§7.2).
    claims_recorded = record_claim_meta(rt, owner, research_id, report=report,
                                        window_days=window_value, as_of=survey_value)
    mode, raw_mode = research_quality.gate_mode()
    if raw_mode:
        mode_notice(rt, sid, RESEARCH_GATE_MODE_UNKNOWN_CODE, RESEARCH_GATE_ENV, raw_mode,
                    RESEARCH_GATE_DEFAULT_MODE)
    latest_verdict = rt.store.research_verification_latest(research_id)
    critique_ok = True
    if tier_limits['critique'] or review_modes:
        # Bản ĐẦU của mức 3 ghi được (chưa ai phản biện thì không có gì để kèm); từ bản thứ hai, sau
        # khi đã có phán quyết, hồ sơ phải mang phản biện ĐẠT — nếu không thì đây là bản viết lại
        # lờ phản biện, và cổng chặn (D-40, #6024).
        critique_ok = (True if cfg.get('jobMode') == 'v2'
                       else (critique_arg == 'ok') or latest_verdict is None)
        if critique_arg == 'none' and latest_verdict is None:
            rt.store.emit(sid, 'notice', {
                'code': RESEARCH_CRITIQUE_MISSING_CODE, 'partial': False,
                'message': (f'{RESEARCH_CRITIQUE_MISSING_CODE}: cần kiểm chứng độc lập — sau '
                            f'bản này hãy delegate_task(role="research-review") rồi `research_verify`')})
    verdict = research_quality.assess(session,
                                      profile=None if cfg.get('jobMode') == 'v2' else profile,
                                      level=level, markdown=markdown,
                                      rows=rows, child_ids=children, mode=mode,
                                      critique_ok=critique_ok, verified=_verified_map(rows),
                                      owner_views=(cfg.get('ownerViews') if cfg and
                                                   cfg.get('jobMode') != 'v2' else []),
                                      review=str(args.get('review') or ''),
                                      require_claim_citations=cfg.get('jobMode') == 'v2',
                                      report=report, job_types=job_types,
                                      facets=(coverage.get('facets') if coverage else None),
                                      claim_ids=claim_ids, extra_issues=stale_issues)
    if not verdict.ok and verdict.mode == 'enforce':
        system_log.write('research.gate.rejected', level='warn', session_id=sid,
                         code=research_quality.RESEARCH_QUALITY_PREFIX, mode=verdict.mode,
                         issues=[item['code'] for item in verdict.missing], rows=len(rows))
        if cfg.get('jobMode') != 'v2':
            raise ValueError(research_quality.rejection_message(verdict))
        # New durable jobs keep the draft and its missing items for continuation.
    versions = rt.store.dossier_versions(research_id)
    version = (int(versions[-1] or 0) if versions else 0) + 1
    # Phòng hồ sơ phải là `.research/<researchId>-<yyyymmdd-hhmm>` — đúng khuôn tên phòng của
    # `dossier_dir_for`, và cũng đúng khuôn `DOSSIER_PATH_RE` mà op của box áp. Bản trước dựng
    # `path` TỪ `dossier_dir` rồi so `path` với chính `dossier_dir` (vòng lặp rỗng), nên một phòng
    # sai vẫn đi thẳng xuống đĩa và `DOSSIER_DIR_MISMATCH_CODE` chưa từng được import ⇒ `NameError`
    # đúng vào lúc cần báo lỗi (cùng lớp BUG-94/95).
    dossier_dir = str(cfg.get('dossierDir') or '').strip() or dossier_dir_for(research_id)
    if not re.fullmatch(rf'{re.escape(DOSSIER_ROOM)}/{re.escape(research_id)}-\d{{8}}-\d{{4}}', dossier_dir):
        raise ValueError(f'{DOSSIER_DIR_MISMATCH_CODE}: phòng hồ sơ phải có dạng '
                         f'{DOSSIER_ROOM}/{research_id}-<yyyymmdd-hhmm> (nhận được: {dossier_dir!r})')
    gate_label = _gate_label(verdict, level, critique_arg)
    tables = _dossier_tables(args.get('tables'))
    review = str(args.get('review') or '')
    title = str(args.get('title') or '').strip() or research_id.replace('-', ' ')
    # Số bản phải tính theo CẢ HAI nguồn: chỉ mục trong store VÀ tệp `v<N>` đang có trong phòng.
    # Chỉ đọc store là chưa đủ — một tệp do lượt trước để lại (ghi hỏng giữa chừng, hoặc phòng dựng
    # bằng tay) mà chỉ mục chưa biết sẽ làm `DOSSIER_VERSION_TAKEN` lặp lại y hệt ở mọi lần thử, trong
    # khi cách sửa mà câu lỗi mách ("ghi bản kế") lại không thi hành được vì số bản vẫn tính ra 1
    # (lượt kiểm thử v27d, F-A). Vòng lặp dưới đây giữ nguyên luật bất biến: bản cũ KHÔNG bị ghi đè,
    # chỉ có số bản được đẩy lên bản kế trống.
    async with rt.writer_lock:
        for attempt in range(DOSSIER_VERSION_ATTEMPTS_MAX):
            path = f'{dossier_dir}/v{version}-{research_id}.md'
            header = research_header.build_research_header(
                version, research_id, profile.key, level, critique=critique_arg, gate=gate_label,
                rows=len(rows))
            full = header + markdown
            # P2 (§7.7): tệp phụ của run đi cùng lượt ghi hồ sơ; tên do `sidecar_names` cấp.
            sidecars = _dossier_sidecars(rt, research_id, version, report=report, coverage=coverage,
                                         scope=job_scope, job_types=job_types,
                                         extractions=args.get('extractions'))
            write_args = _dossier_op_args(path, full, rows, args, tables, review, title,
                                          sidecars=sidecars)
            try:
                written = await rt.executor.execute('dossier_write', write_args, sid)
                break
            except Exception as error:
                if ('DOSSIER_VERSION_TAKEN' not in str(error)
                        or attempt + 1 >= DOSSIER_VERSION_ATTEMPTS_MAX):
                    raise
                version += 1
                system_log.write('research.dossier.version_taken', level='warn', session_id=sid,
                                 code='DOSSIER_VERSION_TAKEN', researchId=research_id,
                                 taken=path, version=version)
    written = dict(written or {})
    returned = str(written.get('relativePath') or '')
    if not returned.endswith(f'v{version}-{research_id}.md'):
        raise ValueError(f'DOSSIER_WRITE_CONFLICT: box báo đường dẫn {returned!r} trong khi lượt này ghi '
                         f'{path!r}; không có gì được đăng ký')
    rt.store.record_dossier(sid, research_id, version, returned, profile=profile.key, level=level,
                            critique=critique_arg, gate=gate_label, rows=len(rows),
                            bytes=int(written.get('bytes') or len(full.encode('utf-8'))),
                            content_hash=hashlib.sha256(full.encode('utf-8')).hexdigest(),
                            quality_ok=verdict.ok)
    payload = {'researchId': research_id, 'version': version, 'profile': profile.key, 'level': level,
               'rows': len(rows), 'relativePath': returned, 'gate': verdict.mode,
               'bytes': int(written.get('bytes') or len(full.encode('utf-8')))}
    if verdict.issues:
        rt.store.emit(sid, 'notice', {
            'code': RESEARCH_GATE_NOTE_CODE, 'mode': verdict.mode, 'partial': False,
            'issues': [item['code'] for item in verdict.missing], 'soft': verdict.soft,
            'message': research_quality.notice_for(verdict.issues, len(rows))})
        system_log.write('research.gate.unbacked', level='warn', session_id=sid,
                         code=RESEARCH_GATE_NOTE_CODE, mode=verdict.mode, researchId=research_id,
                         version=version, issues=[item['code'] for item in verdict.missing])
    if verdict.soft:
        rt.store.emit(sid, 'notice', {
            'code': 'RESEARCH_GATE_SOFT', 'partial': False, 'fields': verdict.soft,
            'message': f'RESEARCH_GATE_SOFT: trường mềm còn thiếu — {", ".join(verdict.soft)}'})
    pin = pin_source_ledger(rt, sid, payload)
    system_log.write('research.dossier.written', level='info', session_id=sid,
                     code='DOSSIER_WRITTEN', researchId=research_id, version=version, rows=len(rows),
                     bytes=payload['bytes'], gateMode=verdict.mode, tierLevel=level)
    answer = {'researchId': research_id, 'version': version, 'profile': profile.key,
              'level': level, 'relativePath': returned, 'files': written.get('files') or [returned],
              'header': {'version': version, 'researchId': research_id, 'profile': profile.key,
                         'level': level, 'critique': critique_arg, 'rows': len(rows)},
              'state': 'draft' if not verdict.ok or review_modes or tier_limits['critique'] else 'ready',
              'gate': {'mode': verdict.mode, 'ok': verdict.ok,
                       'issues': [item['code'] for item in verdict.missing], 'soft': verdict.soft,
                       'counts': verdict.counts},
              'journal': bool(pin and pin[1]),
              'bytes': payload['bytes'], 'sha1': written.get('sha1'),
              'claimsRecorded': claims_recorded}
    if coverage:
        answer['coverage'] = coverage
        answer['stop'] = coverage_stop(rt, research_id, coverage=coverage)
    if stale_issues:
        answer['staleCurrentClaims'] = [item.detail for item in stale_issues]
    if not verdict.ok:
        answer['warning'] = research_quality.notice_for(verdict.issues, len(rows))
    critique_step = (' — cần kiểm chứng độc lập: **báo main** kèm đường dẫn hồ sơ để main giao '
                     'delegate_task(role="research-review") rồi main gọi `research_verify` cho bản này '
                     '(chỉ main ghi được phán quyết)')
    answer['next'] = ('báo cáo chủ nhà bằng đường dẫn hồ sơ, không dán lại toàn văn'
                      + (critique_step if tier_limits['critique'] or review_modes else ''))
    # C1 (§5.3): hồ sơ vừa ghi xong ⇒ run bước sang pha tổng hợp (`job` là None ngoài mode v2).
    set_phase(rt, sid, job, 'synthesizing', 'dossier-written')
    return answer


def _gate_label(verdict, level, critique_arg) -> str:
    """`Gate:` của header + cột `gate` của chỉ mục: `clear` sạch, `warn` có mục chỉ nhắc, `unbacked` cổng tắt.

    Ba nhãn này là hợp đồng với FE (`research_header.GATE_VALUES`), nên `off` **không** được ghi thành
    `clear`: một hồ sơ không ai chấm thì không phải một hồ sơ sạch.
    """
    mode = str(getattr(verdict, 'mode', '') or '')
    if mode == 'off':
        return 'unbacked'
    if getattr(verdict, 'issues', None):
        return 'warn'
    if research_tier_limits(level)['critique'] and critique_arg == 'none':
        return 'warn'
    return 'clear'


def annotate_branch_answer(rt, session, child_id, answer, calls=()):
    """Chú thích tất định cho câu trả lời của MỘT nhánh research (đợt 4, A5) — chỉ đọc.

    Sổ nguồn sống ở phiên GIỮ BRIEF, dòng của nhánh mang `childId` của chính nó (A3.5), nên đọc
    theo nhánh phải hỏi chủ sổ. Hàm này **không** viết lại câu trả lời (I2/D-18) và **không** đổi
    `status` (I3): kết quả chỉ là một chú thích cho chủ nhà và cho người gọi.
    """
    # Chủ sổ tìm từ PHIÊN CON: khi cha chưa giữ brief, `_ledger_owner` đi ngược LÊN từ chính con —
    # hỏi từ phiên cha thì nó dừng ngay ở cha và đọc nhầm sổ rỗng của con (BUG-108).
    child_session = rt.store.get(str(child_id)) or session
    owner, _child = _ledger_owner(rt, child_session, str(child_id))
    rows = [_row_of(item) for item in rt.store.source_rows_for(owner, [str(child_id)])]
    profile = None
    try:
        profile = research_profiles.get(research_config(rt.store.get(owner) or {}).get('jobProfile') or '')
    except Exception:  # pragma: no cover - chú thích không bao giờ được chặn đường đóng lượt con
        profile = None
    return research_quality.annotate_child_answer(answer, rows=rows, calls=calls,
                                                 child_id=str(child_id), profile=profile)


# --------------------------------------------------------------------------- phản biện (đợt 6)


def _review_read_proof(rt, child_id: str, path: str, content_hash: str) -> bool:
    """A completed reviewer must have read the exact saved bytes, including all slices."""
    if not content_hash:
        return False  # legacy versions have no immutable content identity
    slices: dict[int, str] = {}
    size = None
    after = 0
    while True:
        page = rt.store.events(child_id, after=after)
        if not page:
            break
        for event in page:
            if event['type'] != 'tool_end':
                continue
            data = event['data'] if isinstance(event['data'], dict) else {}
            args = data.get('args') or {}
            result = data.get('result') or {}
            if data.get('name') != 'file_read' or str(args.get('path') or '') != path \
                    or result.get('is_error') or not isinstance(result.get('content'), str):
                continue
            try:
                offset = int(args.get('offset') or 0)
            except (TypeError, ValueError):
                continue
            slices[offset] = result['content']
            if result.get('truncated') is False:
                size = offset + len(result['content'])
        next_after = page[-1]['seq']
        if next_after <= after:
            break
        after = next_after
    if size is None:
        return False
    cursor = 0
    parts = []
    while cursor < size:
        piece = slices.get(cursor)
        if not piece:
            return False
        parts.append(piece)
        cursor += len(piece)
    return cursor == size and hashlib.sha256(''.join(parts).encode('utf-8')).hexdigest() == content_hash


def research_critique(rt, sid, research_id, version, mode='critique'):
    """Cổng provenance của phản biện hồ sơ — khuôn `plan_critique`, đọc verdict ở DÒNG CUỐI.

    Bốn điều kiện: có bản hồ sơ thật cho `(research_id, version)`; phiên con mang vai
    `research-review`; nó chạy SAU lần ghi đó; câu trả lời đủ dài để có nội dung đọc được.

    Con MỚI NHẤT đọc được dòng verdict sẽ thắng; một con mới hơn bị nhà cung cấp cắt giữa câu
    KHÔNG được phép che con cũ hợp lệ (đo sống 2026-09-26: hai con critique liên tiếp bị cắt làm
    `research_verify` từ chối hai lần, dù cùng bản còn một con đọc được). Chỉ khi không con nào
    đọc được mới báo lỗi — và lỗi nói đúng sự thật của con mới nhất, kèm hai dòng cuối của nó.
    """
    row = rt.store.dossier(research_id, version)
    if row is None:
        raise ValueError(f'{RESEARCH_VERIFY_UNKNOWN_CODE}: no dossier write is recorded for '
                         f'{research_id}@v{version} — write it first with dossier_write')
    written_at = float(row.get('created') or 0)
    usable = []
    for child in rt.store.children_of(sid):
        if child.get('role') != 'research-review' or child.get('status') != 'completed':
            continue
        if float(child.get('started') or 0) < written_at:
            continue
        if int(child.get('answer_chars') or 0) < RESEARCH_REVIEW_MIN_ANSWER_CHARS:
            continue
        target = (rt.store.get(child['session_id']).get('config') or {}).get('reviewTarget') or {}
        # Danh tính + MỨC SOÁT đứng NGOÀI nhánh `content_hash` (đợt soát `3dc745f`, finding 7): một
        # con CÓ khai đích danh bản/mức thì phải khớp — kể cả khi hàng hồ sơ không có băm. Trước đây
        # cả khối kiểm nằm trong `if row.get('content_hash')`, nên với hàng cũ không băm, lượt quét
        # MỚI-NHẤT-TRƯỚC (A2) có thể nhận một con `evidence` cho một lần kiểm `critique`/`coverage`,
        # hoặc một con trỏ vào bản khác, chỉ vì nó xong sau cùng.
        if target.get('kind') == 'research':
            if target.get('researchId') != research_id or target.get('version') != version \
                    or target.get('mode') != mode \
                    or (target.get('path') and target.get('path') != row['relative_path']):
                continue
        if row.get('content_hash'):
            if target.get('kind') != 'research' or target.get('researchId') != research_id \
                    or target.get('version') != version or target.get('path') != row['relative_path'] \
                    or target.get('contentHash') != row.get('content_hash'):
                continue
            if not _review_read_proof(rt, child['session_id'], row['relative_path'],
                                      row.get('content_hash') or ''):
                continue
        usable.append(child)
    if not usable:
        raise ValueError(f'{RESEARCH_VERIFY_NO_CRITIC_CODE}: {research_id}@v{version} chưa có phản biện '
                         f'dùng được — delegate_task(role="research-review") SAU khi bản này được ghi và '
                         f'để nó đọc toàn bộ đúng file bằng file_read và kết thúc với câu trả lời '
                         f'ít nhất {RESEARCH_REVIEW_MIN_ANSWER_CHARS} ký tự')
    ordered = sorted(usable, key=lambda item: (float(item.get('started') or 0), str(item.get('session_id'))),
                     reverse=True)
    newest = ordered[0]
    newest_lines = 0
    newest_tail = ''
    for critic in ordered:
        text = ''
        for event in rt.store.events_tail(critic['session_id']):
            if event['type'] != 'assistant':
                continue
            piece = event['data'].get('text') if isinstance(event['data'], dict) else None
            if isinstance(piece, str) and piece.strip():
                text = piece
        lines = [line.strip() for line in str(text or '').splitlines() if line.strip()]
        found = re.match(r'(?i)^VERDICT:\s*(ok|revise)$', lines[-1] if lines else '')
        if found is not None:
            return critic, found.group(1).lower(), int(critic.get('answer_chars') or 0)
        if str(critic['session_id']) == str(newest['session_id']):
            newest_lines = len(lines)
            newest_tail = ' | '.join(line[:120] for line in lines[-2:])
    # KHÔNG con nào kết bằng dòng VERDICT. Đo sống 2026-09-26: nhà cung cấp CẮT stream giữa câu
    # nhưng báo `stop` (nay router trả `length`, xem `providers/opencode.mjs`), nên một con
    # `research-review` "hoàn thành" với câu trả lời cụt. Lời khuyên cũ ("hỏi nó dòng verdict rồi
    # gọi lại") đã khiến phiên chính lục 40 lượt `peer_read` cho một dòng KHÔNG hề tồn tại; nay
    # thông điệp nói đúng sự thật của con mới nhất và kèm luôn hai dòng cuối của nó.
    truncated = rt.partial_turn(newest['session_id'])
    if truncated:
        raise ValueError(
            f'{RESEARCH_VERIFY_VERDICT_MISSING_CODE}: con {str(newest["session_id"])[:8]} bị nhà cung cấp '
            f'cắt giữa câu ({truncated}) nên câu trả lời KHÔNG có dòng "VERDICT: ok|revise" nào để hỏi lại '
            f'— gọi `delegate_task(role="research-review")` một con MỚI cho đúng {research_id}@v{version} '
            f'(mode {mode!r}) rồi ghi verdict bằng `research_verify`; hai dòng cuối của con cũ: {newest_tail!r}')
    raise ValueError(f'{RESEARCH_VERIFY_VERDICT_MISSING_CODE}: câu trả lời phản biện phải KẾT THÚC bằng '
                     f'đúng một dòng "VERDICT: ok" hoặc "VERDICT: revise" (con '
                     f'{str(newest["session_id"])[:8]}, {newest_lines} dòng) — hỏi nó dòng verdict rồi '
                     f'gọi `research_verify` lại; hai dòng cuối: {newest_tail!r}')


def _clamp_issues(issues) -> list:
    out = []
    for item in issues or []:
        if isinstance(item, dict):
            text = str(item.get('text') or '').strip()
            if text:
                row = {'severity': item.get('severity') if item.get('severity') in
                       ('high', 'medium', 'low') else 'medium',
                       'text': text[:RESEARCH_VERIFY_ISSUE_CHARS],
                       'fix': str(item.get('fix') or '')[:RESEARCH_VERIFY_ISSUE_CHARS]}
                # P3 (§5.9): giữ `kind` khi nhận ra — hợp đồng `research_verify` hứa nó, và nhãn
                # `bao phủ chưa đủ` của hồ sơ đọc đúng trường này. Một luật, một chỗ: `research_review`.
                kind = research_review.normalize_issue_kind(item.get('kind'))
                if kind:
                    row['kind'] = kind
                # `handled`/`resolved` là dấu XỬ LÝ của một phát hiện: thiếu nó thì mọi
                # `missing-direction` mức cao mãi mãi là 'chưa xử lý' và nhãn `bao phủ chưa đủ`
                # không bao giờ tắt được (§5.9).
                for flag in ('handled', 'resolved'):
                    if item.get(flag):
                        row[flag] = True
                out.append(row)
        else:
            text = str(item).strip()
            if text:
                out.append({'severity': 'medium', 'text': text[:RESEARCH_VERIFY_ISSUE_CHARS],
                            'fix': ''})
    return out[:RESEARCH_VERIFY_MAX_ISSUES]


async def research_verify(rt, session, args):
    """`research_verify`: ghi phán quyết phản biện — CHỈ khi có phê bình độc lập thật.

    Vai: **orchestrator** (iface.md §1). Người phản biện không tự ghi phán quyết của chính mình —
    luật đó là chỗ biến "phản biện độc lập" từ lời nói thành chuyện máy kiểm được (D-40).
    """
    if session.get('role') != 'orchestrator':
        raise PermissionError('research_verify is for the orchestrator role — a research branch that '
                              'got a critique reports the verdict up to the orchestrator, which records '
                              'it (the critic is the orchestrator\'s own child)')
    sid = session['id']
    research_id = str(args.get('researchId') or '').strip().lower()
    if not research_id:
        raise ValueError(f'{RESEARCH_VERIFY_UNKNOWN_CODE}: researchId is required — the id '
                         f'`research_brief` returned')
    version = args.get('version')
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(f'{RESEARCH_VERIFY_VERSION_MISSING_CODE}: version must be an integer (which '
                         f'dossier version the critique read)')
    verdict = str(args.get('verdict') or '').strip().lower()
    if verdict not in ('ok', 'revise'):
        raise ValueError('RESEARCH_VERIFY_INVALID: verdict must be "ok" or "revise"')
    issues = _clamp_issues(args.get('issues'))
    mode = str(args.get('mode') or 'critique').strip().lower()
    if mode not in research_review.REVIEW_MODES:
        raise ValueError('RESEARCH_VERIFY_MODE_INVALID')
    summary = str(args.get('summary') or '')[:RESEARCH_VERIFY_SUMMARY_CHARS]
    critic, critic_verdict, answer_chars = research_critique(rt, sid, research_id, version, mode=mode)
    if critic_verdict != verdict:
        raise ValueError(f'{RESEARCH_VERIFY_VERDICT_MISMATCH_CODE}: phản biện nói {critic_verdict!r} mà bạn '
                         f'ghi {verdict!r} — ghi đúng điều nó nói, hoặc hỏi nó phản biện lại nếu nó sai')
    rt.store.record_research_verification(research_id, version, sid, verdict, issues=issues,
                                          summary=summary, critic_session_id=critic['session_id'],
                                          critic_answer_chars=answer_chars, critic_verdict=critic_verdict,
                                          mode=mode)
    review_rows = rt.store.research_verifications(research_id, version=version)
    by_mode = {item['mode']: item['verdict'] for item in reversed(review_rows)}
    job = rt.store.research_job(research_id)
    needed = set(_review_modes_for(job['state'], job['state'].get('tier', 0))) if job else {mode}
    if not needed:
        needed = {mode}
    combined = ('revise' if any(by_mode.get(item) == 'revise' for item in needed)
                else 'ok' if all(by_mode.get(item) == 'ok' for item in needed) else 'none')
    rt.store.dossier_critique_set(research_id, version, combined)
    coverage_label = research_review.coverage_label(issues)
    rt.store.emit(sid, 'research_verified', {
        'researchId': research_id, 'version': version, 'verdict': verdict, 'mode': mode,
        'combined': combined, 'issues': issues, 'coverageLabel': coverage_label,
        'summary': summary, 'criticSessionId': critic['session_id'], 'criticAnswerChars': answer_chars,
        'at': journal.utc_now_iso()})
    # C1 (§5.3): pha đi theo việc THẬT — `evidence` và `coverage` là hai mặt của bước KIỂM CHỨNG
    # (bảng pha của §5.2 xếp "Claim verifier, coverage reviewer" chung một bước), còn `critique` là
    # bước phản biện; một phán quyết `revise` mở pha viết lại.
    set_phase(rt, sid, job, 'verifying' if mode in {'evidence', 'coverage'} else 'critiquing',
              f'research-verify-{mode}')
    if verdict == 'revise':
        set_phase(rt, sid, job, 'revising', 'research-verdict-revise')
    rounds = rt.store.research_verification_count(research_id, verdict='revise')
    capped = rounds > RESEARCH_VERIFY_REVISE_MAX
    label = RESEARCH_CRITIQUE_LABEL if verdict == 'revise' else ''
    try:
        await session_journal.append(
            rt.executor, rt.store, sid, 'fact',
            f'phản biện độc lập hồ sơ {research_id}@v{version}: {verdict} — {len(issues)} vấn đề',
            data={'researchVerification': {'researchId': research_id, 'version': version,
                                           'verdict': verdict, 'issueCount': len(issues),
                                           'criticSessionId': critic['session_id']}},
            turn=rt.active_turn.get(sid))
    except Exception:  # pragma: no cover - ghi sổ hỏng ⇒ log + đi tiếp
        system_log.write('research.verify.journal_failed', level='warn', session_id=sid,
                         code='JOURNAL_FAILED', researchId=research_id)
    system_log.write('research.verified', level='info', session_id=sid, code='RESEARCH_VERIFIED',
                     researchId=research_id, version=version, verdict=verdict, issues=len(issues),
                     reviseRounds=rounds)
    answer = {'researchId': research_id, 'version': version, 'verdict': verdict,
              'mode': mode, 'combined': combined, 'capped': capped,
              'label': label, 'issues': issues, 'criticSessionId': critic['session_id'],
              'criticAnswerChars': answer_chars, 'reviseRounds': rounds}
    if verdict == 'revise':
        answer['next'] = ('sửa đúng các điểm đã nêu rồi ghi bản nháp mới bằng `dossier_write`, '
                          'sau đó kiểm lại đúng phiên bản')
    if capped:
        answer['message'] = (f'{RESEARCH_CRITIQUE_LABEL}: đã quá trần {RESEARCH_VERIFY_REVISE_MAX} vòng '
                             f'`revise` cho việc này — dừng viết lại và báo chủ nhà trung thực, kèm bản '
                             f'còn phải sửa')
    return answer


def research_status(rt, session, args):
    """`research_status`: đọc lại một việc — có mấy bản, bản nào, ai phản biện, bằng gì.

    Vai được đọc: orchestrator, phiên research của việc, và người phản biện (`research-review`) —
    đúng hợp đồng `/var/tmp/v27/iface.md` §1. Vai khác gọi vào là lỗi quyền, không phải lỗi dữ liệu.
    """
    if session.get('role') not in {'orchestrator', 'research', 'research-review'}:
        raise PermissionError('research_status is for the orchestrator, the research session and the reviewer')
    research_id = str(args.get('researchId') or research_config(session).get('researchId') or '').strip().lower()
    if not research_id:
        raise ValueError(f'{RESEARCH_VERIFY_UNKNOWN_CODE}: researchId is required (or call `research_brief` '
                         f'first so the turn knows which job you mean)')
    # Người gọi thường là một phiên CON (nhánh research, người phản biện) ⇒ số liệu sổ nguồn phải đọc
    # ở phiên giữ brief, không phải sổ rỗng của chính nó.
    owner, _child = _ledger_owner(rt, session, session['id'])
    versions = [int(item) for item in rt.store.dossier_versions(research_id)]
    latest = rt.store.dossier_latest(research_id)
    verifications = rt.store.research_verifications(research_id)
    job = rt.store.research_job(research_id)
    review_modes = _review_modes_for(job['state'] if job else None,
                                     int(latest['level']) if latest else 0)
    cfg = research_config(session)
    answer = {'researchId': research_id, 'versions': versions,
              'latest': ({'version': int(latest['version']), 'path': latest['relative_path'],
                          'profile': latest['profile'], 'level': int(latest['level']),
                          'critique': latest['critique'], 'gate': latest['gate'],
                          'rows': int(latest['rows']), 'bytes': int(latest['bytes']),
                          'sessionId': latest['session_id'],
                          'publication': ('reviewed' if latest.get('quality_ok') and
                                           (not review_modes or latest['critique'] == 'ok')
                                           else 'draft')} if latest else None),
              'verifications': [{'version': int(item['version']), 'mode': item.get('mode'),
                                 'verdict': item['verdict'],
                                 'issues': len(item['issues']), 'summary': item['summary'],
                                 'criticSessionId': item['criticSessionId']} for item in verifications],
              'config': ({'tier': cfg.get('tier'), 'jobProfile': cfg.get('jobProfile'),
                          'dossierDir': cfg.get('dossierDir'), 'branches': cfg.get('branches'),
                          'ceilingSeconds': cfg.get('ceilingSeconds'), 'question': cfg.get('question')}
                         if cfg else None),
              'counts': {'versions': len(versions), 'verifications': len(verifications),
                         'revise': rt.store.research_verification_count(research_id, verdict='revise'),
                         'ledgerRows': rt.store.source_count(owner),
                         'independent': research_ledger.independent_count(_rows_of(rt, owner))}}
    if job:
        used = rt.store.research_job_used_seconds(job['session_id'], research_id)
        answer['job'] = {**job, 'usedSeconds': used,
                         'remainingSeconds': max(0, job['state'].get('budgetSeconds', 0) - used),
                         'children': rt.store.children_of(job['session_id']),
                         'dependentPlans': rt.store.research_dependent_plans(research_id)}
    # P2 (§7.4): bản bao phủ của run đọc từ facet đã lưu + nhật ký tìm (bão hoà là chuyện ĐO được),
    # kèm bốn điều kiện dừng của §5.5 để người đọc biết còn hướng nào chưa đóng.
    coverage = coverage_refresh(rt, research_id, write=True)
    if coverage:
        answer['coverage'] = coverage
        answer['stop'] = coverage_stop(rt, research_id, coverage=coverage)
        answer['claimMeta'] = _claim_metas(rt, research_id)
    return answer


def research_update(rt, session, args):
    """Checkpoint a question, finding or blocker without rewriting the dossier."""
    if session.get('role') != 'orchestrator' or session.get('parent_id'):
        raise PermissionError('research_update is orchestrator-only')
    research_id = str(args.get('researchId') or research_config(session).get('researchId') or '')
    job = rt.store.research_job(research_id)
    if not job or job['session_id'] != session['id']:
        raise ValueError('RESEARCH_JOB_UNKNOWN')
    # P1 (§4.6/§5.3, M-18): `action='pause'|'cancel'` theo JOB (không `runtime.stop(session)`). Ngoài
    # mode, main chỉ được đụng vào một run CHẠY NỀN — run tiền cảnh ngoài mode là việc của chủ nhà
    # trong tab Research.
    action = str(args.get('action') or '').strip().lower()
    if action:
        if action not in {'pause', 'cancel'}:
            raise ValueError('RESEARCH_UPDATE_ACTION_INVALID: use pause or cancel')
        in_mode = _mode_mod().research_mode(session)['on']
        if not in_mode and not (job['state'] or {}).get('background'):
            raise PermissionError('RESEARCH_UPDATE_BACKGROUND_ONLY: ngoài mode bạn chỉ pause/cancel được '
                                  'một run chạy nền (`state.background=true`)')
        return _halt_action(rt, session, job, action)
    state = dict(job['state'])
    qid = str(args.get('questionId') or '')
    qstatus = str(args.get('questionStatus') or '')
    if qid:
        if qstatus not in {'unexplored', 'researching', 'evidenced', 'contested', 'blocked', 'answered'}:
            raise ValueError('RESEARCH_QUESTION_STATUS_INVALID')
        found = False
        for item in state['questions']:
            if item['id'] == qid:
                item['status'] = qstatus
                item['note'] = str(args.get('note') or '')[:2000]
                found = True
        if not found:
            raise ValueError('RESEARCH_QUESTION_UNKNOWN')
    finding = args.get('finding')
    if finding:
        state.setdefault('findings', []).append(str(finding)[:2000])
    blocked = args.get('blockedSource')
    if isinstance(blocked, dict) and blocked.get('url'):
        state.setdefault('blockedSources', []).append({
            'url': str(blocked['url'])[:2000], 'attempt': str(blocked.get('attempt') or '')[:500],
            'impact': str(blocked.get('impact') or '')[:1000]})
    status = str(args.get('status') or job['status'])
    used = rt.store.research_job_used_seconds(session['id'], research_id)
    if status == 'completed':
        unresolved = [item['id'] for item in state['questions']
                      if item.get('importance') == 'high' and
                      not (item.get('status') == 'answered' or
                           (item.get('status') == 'blocked' and item.get('note')))]
        dossier = rt.store.dossier_latest(research_id)
        required_reviews = _review_modes_for(state, state.get('tier', 0))
        if unresolved or not dossier or not dossier.get('quality_ok') or \
                (required_reviews and dossier.get('critique') != 'ok'):
            raise ValueError('RESEARCH_JOB_INCOMPLETE: resolve or qualify high-impact questions, '
                             'write a quality-checked dossier, and complete required reviews; '
                             f'unresolved={unresolved}')
    if used >= state['budgetSeconds'] and status not in {'partial', 'completed', 'paused', 'cancelled'}:
        status = 'partial'
    if status in {'completed', 'partial'}:
        # B1 (§5.3): `completed`/`partial` là pha ĐÓNG của một run, không phải một checkpoint giữa
        # đường. Đo sống 2026-09-26: model ghi `partial` ở hàng cuối (`co-hoi-nao-con-trong`, seq
        # 8107) để nói thật "chưa xong"; code cũ chỉ lưu rồi im — pha kẹt ở `planning`, vòng tiếp
        # sức tự dừng, và chủ nhà không nhận thẻ báo cáo nào cho một run TIỀN CẢNH. Nay lần ĐÓNG đi
        # qua `close_run`: pha `done`, `stopReason` đọc được, thẻ `research_report` + event
        # `research_run` cho cả run tiền cảnh (run nền vẫn qua `finish_background_run`).
        #
        # Một lần gọi LẶP LẠI (không kèm `status`, nên phân giải về đúng status đang đứng) không
        # đóng lần nữa: đợt soát `3dc745f` đo được nó phát thêm một thẻ báo cáo và một `research_run`
        # cho cùng một run. Lần đóng đổi trạng thái thật (`partial` ⇒ `completed`) thì vẫn qua cửa.
        reclosed = job['status'] == status
        if reclosed:
            updated = rt.store.research_job_save(research_id, session['id'], state, status,
                                                 revision=args.get('revision'))
        else:
            updated = close_run(rt, session, job, state, status,
                                args.get('stopReason') or args.get('finding') or '',
                                revision=args.get('revision'))
    else:
        updated = rt.store.research_job_save(research_id, session['id'], state, status,
                                             revision=args.get('revision'))
    # P2 (§7.4): sau mỗi sóng, bản đồ bao phủ được ghép thêm facet/từ khoá mô hình gửi rồi ĐO LẠI
    # bão hoà từ nhật ký tìm — điểm dừng đi kèm để người gọi biết còn hướng nào chưa đóng.
    for item in (args.get('facets') or []):
        if not isinstance(item, dict):
            continue
        try:
            current = rt.store.facet(research_id, item.get('facetId') or item.get('facet_id') or '')
            rt.store.facet_save(research_id, research_facets.merge_terms(current, item.get('terms') or [])
                                if current else item)
        except Exception as error:  # pragma: no cover - ghi facet không được chặn checkpoint
            system_log.write('research.facets.update_failed', level='warn', code='RESEARCH_FACET',
                             researchId=research_id, error=str(error)[:200])
    terms = args.get('facetTerms') if isinstance(args.get('facetTerms'), dict) else {}
    for facet_id, new_terms in terms.items():
        try:
            current = rt.store.facet(research_id, str(facet_id))
            if current:
                rt.store.facet_save(research_id, research_facets.merge_terms(current, new_terms))
        except Exception as error:  # pragma: no cover
            system_log.write('research.facets.terms_failed', level='warn', code='RESEARCH_FACET',
                             researchId=research_id, error=str(error)[:200])
    coverage = coverage_refresh(rt, research_id, write=True)
    answer = {'researchId': research_id, 'status': updated['status'],
              'revision': updated['revision'], 'questions': state['questions'],
              'usedSeconds': used, 'remainingSeconds': max(0, state['budgetSeconds'] - used)}
    if coverage:
        answer['coverage'] = coverage
        answer['stop'] = coverage_stop(rt, research_id, coverage=coverage)
    return answer


async def cancel_child(rt, session, args):
    """`cancel_child`: chủ nhà dừng MỘT nhánh — chỉ nhánh của chính phiên này, và chỉ một lần."""
    sid = session['id']
    target = str(args.get('sessionId') or '').strip()
    reason = str(args.get('reason') or '').strip()
    if not target:
        raise ValueError('CANCEL_CHILD_INVALID: sessionId is required (the child to stop)')
    row = rt.store.child(target)
    if row is None or str(row.get('parent_id') or '') != sid:
        raise PermissionError('CANCEL_CHILD_NOT_MINE: that session is not a child of this turn — only the '
                              'parent can cancel a branch')
    if str(row.get('status') or '') in {'completed', 'failed', 'cancelled', 'interrupted', 'not_found'}:
        return {'sessionId': target, 'status': 'already_closed', 'childStatus': row.get('status'),
                'reason': row.get('reason')}
    await rt.stop(target)
    closed = rt.store.child_close_once(target, 'cancelled', reason='OWNER_CANCELLED')
    # Chỉ thị giữa lượt chỉ xếp cho phiên GỐC, nên vòng lặp này thường không có gì để bỏ; giữ lại để
    # một nhánh đã đóng không bao giờ giữ chỉ thị của chủ nhà trong hàng chờ của mình.
    for steer in rt.store.claim_steers(target, limit=STEER_MAX_PENDING):
        rt.store.mark_steer(steer['id'], 'dropped')
    rt.store.emit(sid, 'child', {'sessionId': target, 'status': 'cancelled', 'cancelledBy': 'owner',
                                 'reason': reason or None, 'role': row.get('role'),
                                 'at': journal.utc_now_iso()})
    try:
        await session_journal.append(
            rt.executor, rt.store, sid, 'fact',
            f'chủ nhà dừng nhánh {row.get("role") or "con"} {target[:8]}',
            data={'childCancel': {'sessionId': target, 'reason': reason or None,
                                  'cancelledBy': 'owner'}}, turn=rt.active_turn.get(sid))
    except Exception:  # pragma: no cover - ghi sổ hỏng ⇒ log + đi tiếp
        system_log.write('research.cancel.journal_failed', level='warn', session_id=sid,
                         code='JOURNAL_FAILED', child=target)
    system_log.write('child.cancelled_by_owner', level='info', session_id=sid, code='OWNER_CANCELLED',
                     child=target, role=row.get('role'), closed=bool(closed))
    return {'sessionId': target, 'status': 'cancelled', 'childStatus': 'cancelled',
            'role': row.get('role'), 'reason': reason or None}


# --------------------------------------------------------------- chỉ thị giữa lượt (đợt 7)


async def queue_owner_steer(rt, sid, text, turn=None):
    """Xếp một chỉ thị giữa lượt — trả `(answer, notice)` cho route, hoặc `None` khi công tắc tắt."""
    mode, unknown = steer_mode()
    if unknown is not None:
        mode_notice(rt, sid, STEER_MODE_UNKNOWN_CODE, STEER_ENV, unknown, STEER_DEFAULT_MODE)
    if mode != 'on':
        return None
    body = str(text or '').strip()
    if not body:
        raise ValueError('STEER_EMPTY: chỉ thị trống — gõ nội dung cần nhắn cho lượt đang chạy')
    if len(body) > STEER_TEXT_MAX_CHARS:
        body = body[:STEER_TEXT_MAX_CHARS]
    if rt.store.pending_steer_count(sid) >= STEER_MAX_PENDING:
        raise ValueError(f'STEER_QUEUE_FULL: đã có {STEER_MAX_PENDING} chỉ thị đang chờ bơm vào lượt này — '
                         f'chờ lượt bơm bớt rồi gửi tiếp')
    turn_no = int(turn if turn is not None else (rt.active_turn.get(sid) or 0))
    record = rt.store.queue_steer(sid, body, turn_no)
    rt.store.emit(sid, 'user', {'text': f'{OWNER_STEER_PREFIX} {body}', 'control': True,
                                'steer': True, 'steerId': record['id'], 'turn': turn_no})
    try:
        await session_journal.append(
            rt.executor, rt.store, sid, 'decision', f'chỉ thị giữa lượt: {body[:120]}',
            data={'kind': 'owner-steer', 'steerId': record['id'], 'chars': len(body)},
            turn=turn_no)
    except Exception:  # pragma: no cover - ghi sổ hỏng ⇒ log + đi tiếp
        system_log.write('steer.journal_failed', level='warn', session_id=sid, code='JOURNAL_FAILED')
    system_log.write('steer.queued', level='info', session_id=sid, code='OWNER_STEER',
                     steerId=record['id'], chars=len(body), pending=rt.store.pending_steer_count(sid))
    return {'status': 'steered', 'steerId': record['id'], 'turn': turn_no,
            'pending': rt.store.pending_steer_count(sid)}


def steer_block(records) -> str:
    """Khối văn bản bơm vào transcript: mỗi chỉ thị một mục, giữ nguyên văn của chủ nhà."""
    lines = []
    for record in records:
        lines.append(f'{OWNER_STEER_PREFIX} {str(record.get("text") or "").strip()}')
    return '\n\n'.join(lines)


def drain_steers(rt, sid, messages) -> int:
    """Bơm các chỉ thị đang chờ vào transcript ở ranh giới bước — **một** lần cho mỗi chỉ thị."""
    claimed = rt.store.claim_steers(sid, limit=STEER_DRAIN_MAX)
    if not claimed:
        return 0
    messages.append({'role': 'user', 'content': steer_block(claimed)})
    try:
        rt.store.save(sid, messages)
    except Exception:  # pragma: no cover - DB hỏng: chỉ thị phải ở LẠI hàng chờ, không được rơi
        # `claim_steers` đánh dấu `injected` TRƯỚC khi transcript kịp ghi; ghi hỏng mà không trả lại
        # hàng chờ là chủ nhà mất một chỉ thị trong im lặng (vòng 27, đợt 8). Trả về `pending` rồi đi
        # tiếp: ranh giới bước sau sẽ bơm lại — lặp một câu còn hơn mất một câu.
        for record in claimed:
            rt.store.requeue_steer(record['id'])
        system_log.write('steer.inject_failed', level='warn', session_id=sid, code='OWNER_STEER',
                         steerIds=[record['id'] for record in claimed], requeued=True)
        return 0
    system_log.write('steer.injected', level='info', session_id=sid, code='OWNER_STEER',
                     count=len(claimed), steerIds=[record['id'] for record in claimed])
    return len(claimed)


def nudge_due(rt, sid) -> int | None:
    """Số phút nếu tới nhịp báo tiến độ (#5969) và còn quota trong lượt này, ngược lại `None`."""
    mode, unknown = research_progress_mode()
    if unknown is not None:
        mode_notice(rt, sid, 'RESEARCH_PROGRESS_MODE_UNKNOWN', RESEARCH_PROGRESS_ENV, unknown,
                    RESEARCH_PROGRESS_DEFAULT_MODE)
    if mode != 'on':
        return None
    state = rt.progress_state.get(sid)
    if not isinstance(state, dict):
        return None
    if state.get('turn') != (rt.active_turn.get(sid) or 0):
        return None
    if int(state.get('count') or 0) >= RESEARCH_PROGRESS_MAX_PER_TURN:
        return None
    if float(state.get('due') or 0) > time.time():
        return None
    return int(RESEARCH_PROGRESS_NUDGE_SECONDS // 60)


def inject_progress_nudge(rt, sid, messages, minutes) -> bool:
    """Bơm câu nhắc tiến độ: **không** event, **không** hàng `D:` — chỉ một mục `user` trong transcript."""
    state = rt.progress_state.get(sid)
    if not isinstance(state, dict):
        return False
    messages.append({'role': 'user', 'content': RESEARCH_NUDGE_PREFIX + ' ' + _NUDGE_BODY.format(elapsed=minutes)})
    rt.store.save(sid, messages)
    state['count'] = int(state.get('count') or 0) + 1
    state['due'] = time.time() + RESEARCH_PROGRESS_NUDGE_SECONDS
    system_log.write('research.progress.nudged', level='info', session_id=sid,
                     code='RESEARCH_PROGRESS_NUDGE', count=state['count'], minutes=minutes)
    return True


# --------------------------------------------------------------------------- P1: vỏ mode (§4/§5)
#
# Bốn việc của P1 nằm ở đây, và chúng dùng CHUNG một luật: mode là trạng thái của PHIÊN
# (`session.config.researchMode`), run là `ResearchJob` (`state.origin`/`state.phase`), còn
# `research_jobs.status` vẫn là nguồn chân lý mà bơm/API/giao diện đọc.
#   - `research_suggest` (cửa 1): main ĐỀ XUẤT mở mode, KHÔNG đổi cấu hình (M-06).
#   - `research_scope` (§5.3/4.4): thẻ phạm vi + lời hỏi nhiều câu, `needs_user` khi còn câu chặn.
#   - `answer_prompt` (§5.12): trả lời MỘT lời hỏi trong MỘT lần gọi, khoá lạc quan `revision`.
#   - `apply_research_mode` (§4.6/5.12): bật/tắt mode, và luật "tắt mode khi run đang chạy thì HỎI".


def _mode_mod():
    """Nạp lười `agent_core.runtime` — tránh vòng import (runtime ⇒ research_runtime)."""
    from . import runtime as runtime_module
    return runtime_module


def research_suggest(rt, session, args):
    """`research_suggest`: main ĐỀ XUẤT mở research mode cho một việc lớn.

    Cố ý KHÔNG có tác dụng phụ nào lên cấu hình (M-06): mode chỉ bật khi NGƯỜI DÙNG bấm nút
    hoặc gõ `/research`. Công cụ này chỉ phát một sự kiện để giao diện vẽ thẻ gợi ý.
    """
    if session.get('role') != 'orchestrator' or session.get('parent_id'):
        raise PermissionError('research_suggest is orchestrator-only: a child must not ask to enter a mode')
    reason = str(args.get('reason') or '').strip()
    if not reason:
        raise ValueError('RESEARCH_SUGGEST_INVALID: reason must not be empty — say why this needs a run')
    draft_goal = str(args.get('draftGoal') or args.get('draft_goal') or '').strip()[:2000]
    mode = _mode_mod().research_mode(session)
    if mode['on']:
        return {'suggested': False, 'reason': 'mode-on',
                'note': 'research mode is already on — call `research_brief` instead'}
    rt.store.emit(session['id'], 'research_suggested',
                  {'reason': reason[:2000], 'draftGoal': draft_goal})
    system_log.write('research.suggested', level='info', session_id=session['id'],
                     code='RESEARCH_SUGGESTED', draftGoal=draft_goal)
    return {'suggested': True, 'reason': reason[:2000], 'draftGoal': draft_goal,
            'modeOn': False, 'changedConfig': False}


def _answered_question_ids(scope) -> set:
    """Id những câu hỏi đã được NGƯỜI DÙNG trả lời (`answer_prompt` để lại `answer.status`)."""
    out = set()
    for question in (scope.get('openQuestions') or []) if isinstance(scope, dict) else []:
        if not isinstance(question, dict):
            continue
        answer = question.get('answer')
        if isinstance(answer, dict) and answer.get('status') == 'confirmed' \
                and str(answer.get('text') or '').strip():
            question_id = str(question.get('id') or '').strip()
            if question_id:
                out.add(question_id)
    return out


def _scope_entry(value, default_status='assumed', source_kind='agent', answered=None, seq=None):
    """Chuẩn hoá MỘT mục của thẻ phạm vi: mục người dùng sửa thì `confirmed`, agent đề xuất thì
    `assumed`, và mọi mục đều mang `source` (§5.10).

    `source.kind='user'` chỉ có khi CÓ BẰNG CHỨNG máy kiểm được (§8.2/M-12):
    * `source_kind='user'` — đường chủ nhà (`scope_update` từ giao diện);
    * hoặc mục tự khai `source.kind='user'` kèm `source.questionId` nằm trong `answered` (câu hỏi
      đã được người dùng trả lời thật qua `answer_prompt`).
    Mọi đường khác — kể cả mô hình tự khai `confirmed` — chỉ được `source.kind='agent'`, nên mục đó
    không bao giờ vào phần "đã xác nhận" của brief con.
    """
    if isinstance(value, dict):
        item = dict(value)
    else:
        item = {'text': str(value or '')}
    source = item.get('source') if isinstance(item.get('source'), dict) else {}
    declared_kind = str(source.get('kind') or '').strip().lower()
    question_id = str(source.get('questionId') or '').strip()
    by_owner = source_kind == 'user'
    by_answer = declared_kind == 'user' and bool(question_id) and question_id in (answered or set())
    if by_owner or by_answer:
        item['status'] = 'confirmed'
        evidence = {'kind': 'user'}
        if seq is not None:
            evidence['seq'] = seq
        if by_answer:
            evidence['questionId'] = question_id
        item['source'] = evidence
        return item
    # Không có bằng chứng người dùng ⇒ mục là GIẢ ĐỊNH, kể cả khi mô hình tự khai `confirmed`: thẻ
    # phạm vi và brief con phải nói cùng một điều (§8.2/M-12).
    item['status'] = default_status
    item['source'] = {'kind': 'agent', **({'seq': source['seq']} if source.get('seq') else {})}
    return item


def _scope_time(scope, patch) -> dict:
    """Chuẩn hoá `timePolicy` của thẻ phạm vi (§7.3) — `velocity` lạ thì **giữ giá trị cũ + ghi chú**.

    Không bao giờ ném: một giá trị tốc độ gõ sai không được làm hỏng cả lượt ghi thẻ phạm vi; nó chỉ
    để lại `note` cho người đọc biết vì sao cửa sổ thời gian không đổi.
    """
    policy = dict((scope or {}).get('timePolicy') or {})
    policy.setdefault('velocity', '')
    policy.setdefault('current', {})
    policy.setdefault('foundational', 'any')
    policy.setdefault('reason', '')
    if isinstance(patch, str):
        # Đường gửi gọn (`timePolicy: "fast"`) là cách model hay viết nhất — nhận như velocity.
        patch = {'velocity': patch}
    if not isinstance(patch, dict):
        return policy
    for key in ('current', 'foundational', 'reason'):
        if key in patch and patch[key] is not None:
            policy[key] = patch[key]
    if 'status' in patch:
        policy['status'] = patch['status']
    if 'velocity' in patch:
        wanted = str(patch.get('velocity') or '').strip().lower()
        if wanted and not research_evidence.window_days(wanted):
            policy['note'] = (f'velocity {wanted!r} không thuộc '
                              f'{", ".join(research_evidence.TIME_VELOCITIES)} — giữ '
                              f'{policy.get("velocity") or "(chưa khai)"}')
        else:
            policy['velocity'] = wanted
            policy.pop('note', None)
    return policy


def _scope_window(scope) -> dict:
    """Cửa sổ thời gian của thẻ phạm vi, suy từ `timePolicy.velocity` + `surveyDate` của runtime."""
    scope['surveyDate'] = scope.get('surveyDate') or research_evidence.survey_date()
    scope['window'] = research_evidence.window_bounds((scope.get('timePolicy') or {}).get('velocity'),
                                                      as_of=scope['surveyDate'])
    return scope


def seed_facets(rt, research_id, scope, *, survey=(), facets=(), citation_clusters=()) -> int:
    """Dựng bản đồ facet ban đầu của run (§7.4): tổng quan → cây câu hỏi → cụm trích dẫn.

    `seed` là dấu vết nguồn gốc của hướng khảo sát: `survey` (mục lục bài tổng quan), `scope` (câu
    hỏi của thẻ phạm vi), `citation-cluster` (cụm trích dẫn), `agent` (mô hình tự đề xuất). Hàm
    **không ghi đè** hàng đã có: hàng cũ được gộp từ khoá qua `merge_terms` để giữ `status` đã đo và
    nguồn gốc từng từ.
    """
    if not limits.research_coverage_enabled():
        return 0
    rid = str(research_id or '')
    if not rid:
        return 0
    incoming = []
    for entry in (survey if isinstance(survey, (list, tuple)) else []):
        incoming.append(research_facets.facet_from_survey(entry))
    for item in (facets if isinstance(facets, (list, tuple)) else []):
        incoming.append(research_facets.normalize_facet(item))
    for question in (scope.get('questions') or []):
        if not isinstance(question, dict):
            continue
        label = str(question.get('text') or '').strip()
        if not label:
            continue
        incoming.append(research_facets.new_facet(label, seed='scope',
                                                  question_id=str(question.get('id') or ''),
                                                  priority=question.get('importance') or 'medium'))
    for item in (citation_clusters if isinstance(citation_clusters, (list, tuple)) else []):
        label = str(item.get('label') if isinstance(item, dict) else item).strip()
        if not label:
            continue
        incoming.append(research_facets.new_facet(label, seed='citation-cluster',
                                                  terms=(item.get('terms') if isinstance(item, dict)
                                                         else ())))
    written = 0
    for facet in incoming:
        if not facet.get('label'):
            continue
        try:
            current = rt.store.facet(rid, facet['facetId']) or {}
            if current:
                merged = research_facets.merge_terms(current, facet.get('terms') or [])
                merged['seedSource'] = current.get('seedSource') or facet['seedSource']
                rt.store.facet_save(rid, merged)
            else:
                rt.store.facet_save(rid, facet)
            written += 1
        except Exception as error:  # pragma: no cover - dựng bản đồ không được chặn ghi thẻ
            system_log.write('research.facets.seed_failed', level='warn', code='RESEARCH_FACET',
                             researchId=rid, error=str(error)[:200])
    return written


def _scope_default(job, question=''):
    state = job['state'] if job else {}
    scope = state.get('scope') if isinstance(state.get('scope'), dict) else {}
    tier = int(state.get('tier') or scope.get('tier') or 2)
    questions = [dict(item) for item in (state.get('questions') or [])]
    return {
        'revision': int(scope.get('revision') or 0),
        'goal': scope.get('goal') or {'text': str(state.get('goal') or question or ''),
                                      'status': 'assumed', 'source': {'kind': 'agent'}},
        'purpose': scope.get('purpose') or {'text': '', 'status': 'assumed', 'source': {'kind': 'agent'}},
        'jobKinds': list(scope.get('jobKinds') or []),
        'questions': scope.get('questions') or [
            {'id': item.get('id'), 'text': item.get('text'), 'importance': item.get('importance', 'medium'),
             'parentId': item.get('parentId'), 'status': item.get('status', 'unexplored')}
            for item in questions],
        'timePolicy': scope.get('timePolicy') or {'velocity': '', 'current': {}, 'foundational': 'any',
                                                  'reason': '', 'status': 'assumed'},
        # P2 (§7.3): mốc khảo sát do RUNTIME cấp (mô hình không tự đoán), và cửa sổ suy từ velocity.
        'surveyDate': scope.get('surveyDate') or research_evidence.survey_date(),
        'window': scope.get('window') if isinstance(scope.get('window'), dict) else {},
        'sourceKinds': list(scope.get('sourceKinds') or []),
        'exclusions': list(scope.get('exclusions') or []),
        'outputs': list(scope.get('outputs') or []),
        'depth': scope.get('depth') or ('deep' if tier >= 3 else 'standard' if tier == 2 else 'quick'),
        'tier': tier,
        'budget': scope.get('budget') or {},
        'openQuestions': list(scope.get('openQuestions') or []),
    }


def scope_update(rt, session_id, job, payload):
    """Người dùng sửa thẻ phạm vi từ giao diện: `PATCH …/jobs/{id}` với `action="scope"` (§5.12).

    Khác `research_scope` (công cụ của mô hình): đây là đường của CHỦ NHÀ, nên không có cổng vai,
    chỉ có khoá lạc quan `revision` — thẻ đã đổi thì từ chối để người dùng tải lại rồi sửa tiếp.
    `payload['scope']` là một `patch` cùng khuôn với công cụ; `timePolicy`, `surveyDate` và `window`
    đi qua đúng luật P2 (velocity sai ⇒ giữ giá trị cũ + ghi chú, không bao giờ ném).
    """
    state = dict(job['state'])
    scope = state.get('scope') if isinstance(state.get('scope'), dict) else {}
    if not scope:
        raise ValueError('RESEARCH_SCOPE_MISSING: run này chưa có thẻ phạm vi để sửa')
    if str(job.get('status') or '') == 'cancelled':
        raise ValueError('RESEARCH_SCOPE_JOB_CANCELLED: run đã huỷ, không sửa thẻ được nữa')
    live_revision = int(scope.get('revision') or 0)
    expected = _revision_arg(payload, RESEARCH_SCOPE_REVISION_INVALID_CODE)
    if expected is not None and expected != live_revision:
        raise ValueError(f'{RESEARCH_SCOPE_REVISION_STALE_CODE}: phạm vi đã đổi (revision '
                         f'{live_revision}) — tải lại thẻ rồi sửa lại')
    patch_body = payload.get('scope') if isinstance(payload.get('scope'), dict) else {}
    if not patch_body:
        raise ValueError('RESEARCH_SCOPE_PATCH_REQUIRED: body needs `scope` (the patch)')
    _scope_apply_patch(scope, patch_body, source_kind='user', seq=live_revision + 1)
    _scope_window(scope)
    scope['revision'] = live_revision + 1
    state['scope'] = scope
    # D-6: người dùng vừa sửa phạm vi ⇒ các lời hỏi đang mở phải mang revision MỚI, nếu không thẻ
    # phỏng vấn 409 vĩnh viễn dù đã tải lại (§5.12, lỗ D-6 của vòng kiểm thử P2–P5).
    _repin_open_prompts(state, scope['revision'])
    _phase_history(state, state.get('phase') or 'planning', 'scope-edited', repeat=True)
    # Người dùng đã sửa thẻ ⇒ run đang chờ câu trả lời không còn bị coi là đang chờ nữa, trừ khi
    # vẫn còn câu chặn chưa trả lời.
    status = 'needs_user' if _open_blocking(scope.get('openQuestions') or []) else str(job['status'])
    updated = rt.store.research_job_save(job['research_id'], session_id, state, status=status,
                                        revision=payload.get('jobRevision'))
    coverage = coverage_refresh(rt, job['research_id'], write=False)
    _scope_event(rt, job['research_id'], scope, updated, coverage=coverage)
    answer = {'researchId': job['research_id'], 'revision': scope['revision'],
              'status': updated['status'], 'scope': scope, 'needsUser': status == 'needs_user',
              'surveyDate': scope.get('surveyDate'), 'window': scope.get('window')}
    if coverage:
        answer['coverage'] = coverage
    return answer


def deepen(rt, session_id, job, payload):
    """Người dùng yêu cầu ĐÀO SÂU một câu hỏi/hướng: `PATCH …/jobs/{id}` với `action="deepen"`.

    Không mở lượt mới ngay (chủ nhà bấm nút, không phải gõ lệnh): yêu cầu được xếp vào
    `state['deepenRequests']` để lượt tiếp tục kế tiếp đọc, hướng (facet) được nâng `priority` và
    mang ghi chú của người dùng. Câu hỏi khớp thì nâng `importance` lên `high` như `prioritize`.
    """
    state = dict(job['state'])
    note = str(payload.get('note') or '').strip()[:1000]
    question_id = str(payload.get('questionId') or '').strip()
    facet_id = str(payload.get('facetId') or '').strip()
    if not question_id and not facet_id:
        raise ValueError('RESEARCH_DEEPEN_TARGET_REQUIRED: cần `questionId` hoặc `facetId`')
    facet = None
    if facet_id:
        facet = rt.store.facet(job['research_id'], facet_id)
        if not facet:
            raise ValueError(f'RESEARCH_FACET_UNKNOWN: run này không có hướng {facet_id!r}')
        merged = dict(facet)
        merged['priority'] = 'high'
        if note:
            old = str(facet.get('note') or '').strip()
            merged['note'] = (f'{old} | {note}' if old else note)[:1000]
        facet = rt.store.facet_save(job['research_id'], merged)
    if question_id:
        matched = False
        for question in state.get('questions') or []:
            if str(question.get('id') or '') == question_id:
                matched = True
                question['importance'] = 'high'
                if note:
                    question['note'] = str(note)[:1000]
        # Cùng luật với nhánh facet (đợt soát `ed485f3`, finding 6): `questionId` lạ thì TỪ CHỐI, chứ
        # không xếp một yêu cầu không ai đọc được vào hàng đợi rồi trả 200.
        if not matched:
            raise ValueError(f'RESEARCH_QUESTION_UNKNOWN: run này không có câu hỏi {question_id!r}')
    requests = [item for item in (state.get('deepenRequests') or []) if isinstance(item, dict)]
    requests.append({'questionId': question_id, 'facetId': facet_id, 'note': note,
                     'at': journal.utc_now_iso()})
    state['deepenRequests'] = requests[-20:]
    updated = rt.store.research_job_save(job['research_id'], session_id, state)
    rt.store.emit(session_id, 'research_deepen',
                  {'researchId': job['research_id'], 'questionId': question_id, 'facetId': facet_id,
                   'note': note})
    answer = {'researchId': job['research_id'], 'revision': updated['revision'],
              'questionId': question_id, 'facetId': facet_id,
              'requests': len(state['deepenRequests'])}
    if facet:
        answer['facet'] = facet
    return answer


def _scope_event(rt, research_id, scope, job, *, coverage=None):
    payload = {'researchId': research_id, 'revision': scope['revision'],
               'phase': (job['state'] or {}).get('phase'), 'status': job['status'],
               'surveyDate': scope.get('surveyDate'), 'window': scope.get('window')}
    if isinstance(coverage, dict) and coverage:
        # Thẻ phạm vi mang bản bao phủ GỌN (số đếm + hướng chưa chạm); bản đầy đủ đi cùng
        # `research_status` và tệp phụ của run.
        payload['coverage'] = {'counts': coverage.get('counts'),
                               'unexplored': coverage.get('unexplored')}
    rt.store.emit(job['session_id'], 'research_scope', payload)


def _prompt(rt, sid, research_id, kind, questions, *, revision, note='', actions=('start', 'editScope'),
            status='open'):
    prompt = {'promptId': f'rp-{uuid_hex()}', 'researchId': research_id, 'kind': kind,
              'revision': int(revision), 'blocking': bool(kind != 'exit-choice'),
              'createdAt': journal.utc_now_iso(), 'status': status, 'questions': questions,
              'actions': list(actions), 'note': note}
    rt.store.emit(sid, 'research_prompt', {'promptId': prompt['promptId'], 'researchId': research_id,
                                          'kind': kind, 'status': status,
                                          'questions': len(questions)})
    return prompt


def _repin_open_prompts(state, revision):
    """Ghim lại revision SỐNG của phạm vi cho các lời hỏi ĐANG MỞ (§5.12, D-6 vòng kiểm thử P2–P5).

    Khoá lạc quan của tuyến trả lời so với `scope['revision']` SỐNG (review F10), còn thẻ trả lời gửi
    `prompt['revision']`. Phạm vi đổi mà không ghim lại ⇒ giao diện tải lại thẻ vẫn nhận con số CŨ và
    mọi câu trả lời bị 409 `RESEARCH_SCOPE_REVISION_STALE` MÃI MÃI (`scope_update` không đụng tới
    `prompts`, và không có sự kiện nào phát lại thẻ để nó biết số mới). Ghim ở đây giữ đúng luật F10:
    thẻ CHƯA tải lại (DOM cũ) vẫn gửi số cũ và vẫn bị từ chối, còn thẻ đã tải lại trả lời được.
    """
    for prompt in (state.get('prompts') or []):
        if isinstance(prompt, dict) and str(prompt.get('status') or 'open') == 'open':
            prompt['revision'] = int(revision)


def uuid_hex():
    import uuid as _uuid
    return _uuid.uuid4().hex[:12]


def _open_blocking(open_questions):
    return [item for item in open_questions
            if item.get('blocking') and not str(item.get('answer') or '').strip()]


def _scope_apply_patch(scope, patch, source_kind='agent', seq=None):
    """Ghép một `patch` vào thẻ phạm vi (§5.3). KHÔNG đụng `revision`, KHÔNG ghi — người gọi quyết.

    Dùng chung cho hai đường: mô hình gọi công cụ `research_scope`, và người dùng sửa thẻ trên giao
    diện (`PATCH /api/agent/research/jobs/{id}` với `action="scope"`). Một luật ghép, một chỗ sửa.
    `source_kind='user'` (+`seq`) đánh dấu mục do chủ nhà viết; mặc định `'agent'` thì mục chỉ được
    coi là "đã xác nhận" khi có `source.questionId` đã trả lời thật (`_scope_entry`).
    """
    patch = patch if isinstance(patch, dict) else {}
    answered = _answered_question_ids(scope)
    entry = lambda value: _scope_entry(value, source_kind=source_kind, answered=answered, seq=seq)
    for key in ('goal', 'purpose'):
        if key in patch:
            scope[key] = entry(patch[key])
    # P2 (§7.3): `timePolicy` có hợp đồng riêng (velocity/current/foundational/reason/status) —
    # không đi qua `_scope_entry` để khỏi bị bọc thành một mục văn bản.
    if 'timePolicy' in patch:
        scope['timePolicy'] = _scope_time(scope, patch['timePolicy'])
    for key in ('jobKinds', 'sourceKinds', 'outputs'):
        if key in patch:
            scope[key] = [str(item).strip() for item in (patch[key] or []) if str(item).strip()]
    if 'exclusions' in patch:
        scope['exclusions'] = [entry(item) for item in (patch['exclusions'] or [])]
    if 'questions' in patch:
        scope['questions'] = [dict(item) if isinstance(item, dict) else {'id': f'q{i + 1}', 'text': str(item)}
                              for i, item in enumerate(patch['questions'] or [])]
    if 'depth' in patch:
        scope['depth'] = str(patch['depth'])
    if 'tier' in patch:
        try:
            scope['tier'] = int(patch['tier'])
        except (TypeError, ValueError):
            pass
    if 'budget' in patch and isinstance(patch['budget'], dict):
        scope['budget'] = {**scope.get('budget', {}), **patch['budget']}
    if 'goalText' in patch:
        scope['goal'] = entry({'text': str(patch['goalText'])})
    return scope


def research_scope(rt, session, args):
    """`research_scope` (§5.3): ghi thẻ phạm vi — nguồn sự thật của run — và hỏi khi cần.

    `action='propose'|'update'` ghi/ghép thẻ (mỗi lần ghi tăng `revision`);
    `action='ask'` tạo lời hỏi nhiều câu (≤ 3 câu, §4.4) và đẩy run sang `needs_user` khi còn câu
    chặn chưa trả lời.
    """
    if session.get('role') != 'orchestrator':
        raise PermissionError('research_scope is orchestrator-only (a research child notes scope in its answer)')
    action = str(args.get('action') or 'propose').strip().lower()
    if action not in ('propose', 'update', 'ask'):
        raise ValueError('RESEARCH_SCOPE_ACTION_INVALID: use propose, update or ask')
    research_id = str(args.get('researchId') or research_config(session).get('researchId') or '').strip()
    job = rt.store.research_job(research_id) if research_id else None
    if job is None or job['session_id'] != session['id']:
        raise ValueError('RESEARCH_SCOPE_NO_JOB: call `research_brief` first — the scope card belongs to a run')
    scope = _scope_default(job, str(args.get('question') or ''))
    state = dict(job['state'])
    if action in ('propose', 'update'):
        patch = args.get('patch') if isinstance(args.get('patch'), dict) else {}
        _scope_apply_patch(scope, patch)
    # P2 (§7.3): cửa sổ thời gian luôn được suy lại từ `timePolicy` + `surveyDate` của runtime.
    _scope_window(scope)
    # P2 (§7.4): dựng bản đồ facet ban đầu từ tổng quan → cây câu hỏi → cụm trích dẫn.
    seeded = seed_facets(rt, research_id, scope, survey=args.get('survey'),
                         facets=args.get('facets'), citation_clusters=args.get('citationClusters'))
    if action == 'ask':
        raw = args.get('questions') if isinstance(args.get('questions'), list) else []
        if not raw:
            raise ValueError('RESEARCH_SCOPE_QUESTIONS_REQUIRED: `action="ask"` needs `questions`')
        questions = []
        for index, item in enumerate(raw[:RESEARCH_SCOPE_MAX_QUESTIONS]):
            item = item if isinstance(item, dict) else {'text': str(item)}
            options = []
            for opt_index, option in enumerate(item.get('options') or []):
                option = option if isinstance(option, dict) else {'label': str(option)}
                options.append({'id': str(option.get('id') or f'o{opt_index + 1}'),
                                'label': str(option.get('label') or '')[:300],
                                'cost': option.get('cost')})
            questions.append({'id': str(item.get('id') or f'iq{index + 1}'),
                              'text': str(item.get('text') or '')[:600],
                              'why': str(item.get('why') or '')[:300],
                              'options': options[:5],
                              'allowFreeText': bool(item.get('allowFreeText', True)),
                              'affects': [str(entry) for entry in (item.get('affects') or [])],
                              'required': bool(item.get('required', True)),
                              'blocking': bool(item.get('blocking', True)), 'answer': None})
        prompt = _prompt(rt, session['id'], research_id, str(args.get('kind') or 'interview'),
                         questions, revision=scope['revision'] + 1, note=str(args.get('note') or ''))
        scope['revision'] += 1
        scope['openQuestions'] = [*scope.get('openQuestions', []),
                                  *[{'id': item['id'], 'text': item['text'], 'options': item['options'],
                                     'blocking': item['blocking'], 'affects': item['affects'],
                                     'answer': None, 'promptId': prompt['promptId']} for item in questions]]
        state.setdefault('prompts', []).append(prompt)
        state['scope'] = scope
        # D-6: lời hỏi mới đã mang số mới; các lời hỏi CŨ còn mở cũng phải theo số mới.
        _repin_open_prompts(state, scope['revision'])
        needs_user = bool(_open_blocking(scope['openQuestions']))
        status = 'needs_user' if needs_user else str(job['status'])
        state['phase'] = 'clarifying' if needs_user else state.get('phase') or 'clarifying'
        _phase_history(state, state['phase'], 'scope-questions')
        updated = rt.store.research_job_save(research_id, session['id'], state, status)
        if needs_user:
            rt.store.emit(session['id'], 'research_notice',
                          {'researchId': research_id, 'kind': 'needs-user',
                           'promptId': prompt['promptId']})
        coverage = coverage_refresh(rt, research_id, write=False)
        _scope_event(rt, research_id, scope, updated, coverage=coverage)
        answer = {'researchId': research_id, 'revision': scope['revision'], 'status': updated['status'],
                  'promptId': prompt['promptId'], 'needsUser': needs_user,
                  'openQuestions': scope['openQuestions'], 'surveyDate': scope.get('surveyDate'),
                  'window': scope.get('window'), 'facetsSeeded': seeded,
                  'next': 'trả lời qua POST /api/agent/research/prompts/'
                          f'{prompt["promptId"]}/answer rồi `start=true`'}
        if coverage:
            answer['coverage'] = coverage
        return answer
    scope['revision'] += 1
    if scope.get('tier'):
        scope['budget'] = {**scope.get('budget', **{})} if isinstance(scope.get('budget'), dict) else {}
        budget = scope['budget']
        budget.setdefault('proposedSeconds', int(RESEARCH_TIER_CHILD_SECONDS.get(int(scope['tier']), 420)) * 3)
        budget.setdefault('hardCeilingSeconds',
                          RESEARCH_TIER_HARD_CEILING_SECONDS.get(int(scope['tier']), 1800))
        budget['bigJob'] = bool(int(scope['tier']) >= 3 or int(budget.get('proposedSeconds') or 0) > 600
                                or len(scope.get('questions') or []) > 3)
        budget.setdefault('approved', False)
    state['scope'] = scope
    # D-6: mô hình viết lại phạm vi cũng làm revision SỐNG tăng ⇒ ghim lại cho lời hỏi đang mở.
    _repin_open_prompts(state, scope['revision'])
    state.setdefault('phase', 'planning' if not _open_blocking(scope['openQuestions']) else 'clarifying')
    _phase_history(state, state['phase'], 'scope-updated')
    status = 'needs_user' if _open_blocking(scope['openQuestions']) else str(job['status'])
    updated = rt.store.research_job_save(research_id, session['id'], state, status)
    coverage = coverage_refresh(rt, research_id, write=True)
    _scope_event(rt, research_id, scope, updated, coverage=coverage)
    answer = {'researchId': research_id, 'revision': scope['revision'], 'status': updated['status'],
              'scope': scope, 'needsUser': status == 'needs_user', 'facetsSeeded': seeded}
    if coverage:
        answer['coverage'] = coverage
    return answer


def _phase_history(state, phase, reason, repeat=False):
    """Ghi `phaseHistory[]` — mỗi lần đổi pha/đổi nền đều để lại một dòng (§5.3).

    `repeat=True` cho phép ghi lại CÙNG một pha: sửa thẻ phạm vi hai lần là hai hàng `D:`-như nhau
    phải đọc được từ `state`, không bị luật chống trùng nuốt mất (đợt soát `ed485f3`, finding 7).
    """
    history = state.setdefault('phaseHistory', [])
    if history and history[-1].get('phase') == phase and not repeat:
        return
    history.append({'phase': phase, 'at': journal.utc_now_iso(), 'reason': reason})


# Pha ĐÓNG của một run (§5.3: `done` ⇔ `completed`/`partial`). Run đã đóng thì không mở lại.
PHASE_DONE = 'done'


def set_phase(rt, sid, job, phase, reason, *, force=False):
    """Đẩy một run sang pha mới: ghi `state.phase` + `phaseHistory[]` rồi PHÁT `research_run`.

    §5.3 của kế hoạch đòi mỗi lần đổi pha để lại một hàng trong `phaseHistory[]` **và** một event
    `research_run` — nhưng máy pha chưa hề được nối vào việc thật. Đo sống 2026-09-26 (run
    `co-hoi-nao-con-trong`, phiên `9ccdb26b…`): run chạy bốn lượt, ghi hồ sơ tới bản v2, kiểm chứng
    hai vòng, mà `state.phase` vẫn đứng ở `planning` — thanh tiến trình và `/research status` nói sai
    chuyện đã xảy ra. Đây là cửa chung cho mọi bước tiến pha do HARNESS ghi (nhánh con, hồ sơ,
    kiểm chứng, kết thúc), nên hai thứ đó không thể lệch nhau nữa; chỗ duy nhất còn tự ghi pha là
    `apply_research_mode` lúc BẬT mode — nó ghi `searching` như một phần của chính thao tác bật,
    kèm `research_run` riêng.

    Luật "có gì để ghi không" nằm trong `store.research_job_phase` (nó đọc hàng TƯƠI): pha đang
    đứng thì không ghi, và run đã ở pha `done` thì không lùi khỏi đó — trừ `force`, dành cho chủ
    nhà bấm Tiếp tục trên một run ĐÃ ĐÓNG. Nhích `phase` KHÔNG nhích `revision`: pha là việc của
    harness, còn `revision` là khoá lạc quan của model (`research_update(revision=…)`) — nhích nó ở
    đây là tự tạo va chạm giả. Trả về hàng job sau khi ghi, hoặc `None` khi không có gì để ghi.
    """
    if job is None:
        return None
    updated = rt.store.research_job_phase(job['research_id'], sid, str(phase), reason,
                                         journal.utc_now_iso(), force=force)
    if updated is None:
        return None
    rt.store.emit(sid, 'research_run', {
        'researchId': job['research_id'], 'status': updated['status'], 'phase': str(phase),
        'background': bool((updated['state'] or {}).get('background')),
        'revision': updated['revision'], 'reason': reason, 'at': journal.utc_now_iso()})
    return updated


def _revision_arg(payload, code):
    """`payload['revision']` → `int` hoặc `None`; giá trị không phải số ⇒ `ValueError(code: …)`.

    Khoá lạc quan nhận thẳng từ thân HTTP: `int({})` ném `TypeError` và `int('banana')` ném thông báo
    Python — cả hai đều lọt ra biên thành mã lỗi vô nghĩa với giao diện (đợt soát `ed485f3`,
    finding 2). Một chỗ kiểm, hai đường dùng (`scope_update`, `answer_prompt`).
    """
    expected = payload.get('revision')
    if expected is None or isinstance(expected, bool):
        return None
    if isinstance(expected, int):
        return expected
    try:
        return int(str(expected).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{code}: `revision` phải là số nguyên, nhận {expected!r}') from None


def answer_prompt(rt, session_id, job, payload):
    """Trả lời MỘT lời hỏi nhiều câu trong MỘT lần gọi (§5.12, M-17).

    Luật: khoá lạc quan `revision` (lệch ⇒ từ chối), mọi câu trả lời trong cùng một lần gọi,
    câu đã trả lời thành mục `confirmed`, và chỉ mở lượt tiếp tục khi KHÔNG còn câu chặn nào.
    """
    prompt_id = str(payload.get('promptId') or '').strip()
    state = dict(job['state'])
    prompts = state.get('prompts') or []
    prompt = next((item for item in prompts if item.get('promptId') == prompt_id), None)
    if prompt is None:
        raise ValueError('RESEARCH_PROMPT_UNKNOWN: no such prompt on this run')
    if prompt.get('status') == 'answered':
        raise ValueError('RESEARCH_PROMPT_ANSWERED: that prompt is already answered')
    scope = state.get('scope') if isinstance(state.get('scope'), dict) else {}
    # Khoá lạc quan so với revision SỐNG của phạm vi, KHÔNG phải revision đã đóng băng trong
    # `prompt['revision']`: thẻ trả lời sau khi phạm vi bị viết lại (revision tăng) phải bị từ chối,
    # kể cả khi `prompt['revision']` vẫn là con số cũ (review F10).
    live_revision = int(scope.get('revision') or 0) if scope else int(prompt.get('revision') or 0)
    expected = _revision_arg(payload, RESEARCH_SCOPE_REVISION_INVALID_CODE)
    if expected is not None and expected != live_revision:
        raise ValueError(f'{RESEARCH_SCOPE_REVISION_STALE_CODE}: phạm vi đã đổi (revision '
                         f'{live_revision}) — tải lại thẻ rồi trả lời lại')
    answers = payload.get('answers') if isinstance(payload.get('answers'), list) else []
    given = {str(item.get('questionId') or ''): item for item in answers if isinstance(item, dict)}
    open_questions = scope.get('openQuestions') or []
    for question in open_questions:
        answer = given.get(str(question.get('id')))
        if answer is None:
            continue
        option = next((item for item in question.get('options') or []
                       if item.get('id') == str(answer.get('optionId') or '')), None)
        text = str(answer.get('text') or (option or {}).get('label') or '').strip()
        if not text:
            continue
        question['answer'] = {'text': text[:600], 'optionId': (option or {}).get('id'),
                              'status': 'confirmed', 'at': journal.utc_now_iso()}
        question['blocking'] = False
    required = [item for item in prompt.get('questions') or [] if item.get('required', True)]
    unanswered = [item['id'] for item in required
                  if not any(str(answer.get('questionId')) == str(item['id'])
                             and (str(answer.get('text') or '').strip() or str(answer.get('optionId') or ''))
                             for answer in answers if isinstance(answer, dict))]
    wants_start = bool(payload.get('start'))
    if wants_start and unanswered:
        raise ValueError(f'RESEARCH_PROMPT_UNANSWERED: còn {len(unanswered)} câu chặn chưa trả lời '
                         f'({", ".join(unanswered)}) — gửi MỌI câu trả lời trong một lần gọi')
    prompt['status'] = 'answered' if not unanswered else 'open'
    blocked = _open_blocking(open_questions)
    if payload.get('approveBudget') and isinstance(scope.get('budget'), dict):
        scope['budget']['approved'] = True
    state['scope'] = scope
    status = str(job['status'])
    if not blocked and status == 'needs_user':
        status = 'researching' if wants_start else 'scoping'
        state['phase'] = 'planning' if wants_start else state.get('phase') or 'planning'
        _phase_history(state, state['phase'], 'prompt-answered')
    updated = rt.store.research_job_save(job['research_id'], session_id, state, status)
    rt.store.emit(session_id, 'research_scope',
                  {'researchId': job['research_id'], 'revision': scope.get('revision'),
                   'phase': state.get('phase'), 'status': updated['status']})
    return {'researchId': job['research_id'], 'promptId': prompt_id, 'status': updated['status'],
            'revision': updated['revision'], 'resume': bool(wants_start and not blocked),
            'openBlocking': [item['id'] for item in blocked], 'unanswered': unanswered}


def active_run(session):
    """Run đang hoạt động của phiên theo `researchMode.activeRunId`, hoặc `None`."""
    mode = _mode_mod().research_mode(session)
    run_id = str(mode.get('activeRunId') or '')
    return run_id or None


def apply_research_mode(rt, session, payload):
    """Bật/tắt mode (§4.6/§5.12) — logic thuần, route HTTP chỉ gọi hàm này.

    Tắt mode khi có run đang hoạt động mà THIẾU lựa chọn ⇒ `RESEARCH_EXIT_CHOICE_REQUIRED` kèm
    một lời hỏi `exit-choice`; mode KHÔNG đổi (M-10c/M-15).
    """
    runtime_module = _mode_mod()
    sid = session['id']
    if session.get('role') != 'orchestrator' or session.get('parent_id'):
        raise PermissionError('research mode belongs to the conversation, not to a child session')
    want_on = bool(payload.get('on'))
    mode = runtime_module.research_mode(session)
    run_id = active_run(session)
    job = rt.store.research_job(run_id) if run_id else None
    if job is not None and job['session_id'] != sid:
        job = None
    active = job is not None and job['status'] in {'scoping', 'researching', 'verifying', 'synthesizing',
                                                  'critiquing', 'needs_user', 'paused', 'partial'}
    if want_on:
        config = dict(session.get('config') or {})
        mode = {**mode, 'on': True, 'since': mode.get('since') or journal.utc_now_iso(),
                'enteredBy': str(payload.get('by') or 'toggle') if not mode['on'] else mode['enteredBy'],
                'revision': int(mode.get('revision') or 0) + 1}
        if job is not None:
            mode['activeRunId'] = job['research_id']
            state = dict(job['state'])
            if state.get('background'):
                state['background'] = False
                state['phase'] = 'clarifying' if job['status'] == 'needs_user' else state.get('phase') or 'searching'
                _phase_history(state, state['phase'], 'mode-on')
                rt.store.research_job_save(job['research_id'], sid, state)
                rt.store.emit(sid, 'research_run', {'researchId': job['research_id'], 'status': job['status'],
                                                    'phase': state.get('phase'), 'background': False,
                                                    'revision': job['revision'] + 1})
        config['researchMode'] = mode
        rt.store.update_config(sid, config)
        rt.store.emit(sid, RESEARCH_MODE_EVENT_CODE,
                      {'on': True, 'by': mode['enteredBy'], 'activeRunId': mode['activeRunId'],
                       'revision': mode['revision']})
        return {'on': True, 'mode': mode, 'activeRunId': mode['activeRunId'], 'prompt': None}
    # Tắt mode.
    if active:
        choice = str(payload.get('exitChoice') or payload.get('activeRun') or '').strip().lower()
        if not runtime_module.background_runs_enabled():
            # F7 (§5.13): công tắc `BOXFOX_RESEARCH_BACKGROUND_RUNS=off` ⇒ thoát mode LUÔN tạm dừng
            # run và KHÔNG mời lựa chọn chạy nền — một lời mời mà bơm sẽ không thực hiện được là lời
            # mời dối. Người dùng có gửi 'background' cũng bị hạ về 'pause'.
            choice = 'pause'
        elif choice not in ('pause', 'background'):
            prompt = dict(payload.get('prompt') or {}) if isinstance(payload.get('prompt'), dict) else {}
            if not prompt.get('promptId'):
                question = [{'id': 'exit', 'text': f'Run {job["research_id"]} đang chạy. Bạn muốn tạm dừng hay để nó '
                                                   f'chạy nền?',
                             'options': [{'id': 'pause', 'label': 'Tạm dừng run'},
                                         {'id': 'background', 'label': 'Tiếp tục chạy nền'}],
                             'allowFreeText': False, 'required': True, 'blocking': True, 'affects': []}]
                prompt = _prompt(rt, sid, job['research_id'], 'exit-choice', question,
                                 revision=int(mode.get('revision') or 0),
                                 note='Mode giữ nguyên cho đến khi bạn chọn.', actions=('chooseExit',))
                state = dict(job['state'])
                state.setdefault('prompts', []).append(prompt)
                rt.store.research_job_save(job['research_id'], sid, state)
            raise _exit_choice_required(prompt, job, mode)
        state = dict(job['state'])
        if choice == 'pause':
            state['background'] = False
            _phase_history(state, state.get('phase') or 'searching', 'mode-off-pause')
            rt.store.research_job_save(job['research_id'], sid, state, 'paused')
            rt.store.emit(sid, 'research_run', {'researchId': job['research_id'], 'status': 'paused',
                                                'phase': state.get('phase'), 'background': False,
                                                'revision': job['revision'] + 1})
        else:
            state['background'] = True
            _phase_history(state, state.get('phase') or 'searching', 'mode-off-background')
            rt.store.research_job_save(job['research_id'], sid, state)
            rt.store.emit(sid, 'research_run', {'researchId': job['research_id'], 'status': job['status'],
                                                'phase': state.get('phase'), 'background': True,
                                                'revision': job['revision'] + 1})
    config = dict(session.get('config') or {})
    mode = {**mode, 'on': False, 'activeRunId': run_id if active else mode.get('activeRunId'),
            'revision': int(mode.get('revision') or 0) + 1}
    config['researchMode'] = mode
    rt.store.update_config(sid, config)
    rt.store.emit(sid, RESEARCH_MODE_EVENT_CODE,
                  {'on': False, 'by': str(payload.get('by') or 'toggle'), 'revision': mode['revision']})
    return {'on': False, 'mode': mode, 'activeRunId': mode.get('activeRunId'), 'prompt': None,
            'exitChoice': str(payload.get('exitChoice') or payload.get('activeRun') or '') or None}


def _exit_choice_required(prompt, job, mode):
    """Lỗi 409 mà route dịch thành `RESEARCH_EXIT_CHOICE_REQUIRED` + `{prompt:{kind:'exit-choice'}}`."""
    error = ValueError(f'{RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE}: mode stays on until you choose '
                       f'"pause" or "background" for run {job["research_id"]}')
    error.payload = {'code': RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE, 'status': 409,
                     'prompt': {**prompt, 'kind': 'exit-choice'}}
    return error


def dismiss_prompt(rt, session_id, job, prompt_id):
    """Đóng lời hỏi thoát mà KHÔNG chọn ⇒ không đổi gì (M-15)."""
    state = dict(job['state'])
    prompt = next((item for item in state.get('prompts') or []
                   if item.get('promptId') == prompt_id), None)
    if prompt is None:
        raise ValueError('RESEARCH_PROMPT_UNKNOWN')
    prompt['status'] = 'dismissed'
    rt.store.research_job_save(job['research_id'], session_id, state)
    rt.store.emit(session_id, 'research_prompt', {'promptId': prompt_id,
                                                 'researchId': job['research_id'],
                                                 'kind': prompt.get('kind'), 'status': 'dismissed'})
    return {'researchId': job['research_id'], 'promptId': prompt_id, 'status': 'dismissed'}


async def refresh_run(rt, session, job, payload=None):
    """`action='refresh'` (§5.8): mở RUN LÀM MỚI kế thừa nguồn của một run đã có bản hồ sơ.

    Bản hồ sơ cũ là dấu vết của một thời điểm — KHÔNG sửa nó. Run mới giữ nguyên câu hỏi và mức, chép
    sổ nguồn sang với cờ `inherited` và trạng thái `unverified`, rồi ghim `refreshOf`/`refreshSince`/
    `supersedes` để `changelog.md` đọc được cái gì mới/đổi/rút.
    """
    payload = payload if isinstance(payload, dict) else {}
    sid = session['id']
    source_id = str(job['research_id'])
    mode, unknown = _refresh_mode()
    if unknown:
        mode_notice(rt, sid, RESEARCH_REFRESH_MODE_UNKNOWN_CODE, RESEARCH_REFRESH_ENV, unknown,
                    RESEARCH_REFRESH_DEFAULT_MODE)
    if mode != 'on':
        raise ValueError(f'{RESEARCH_REFRESH_DISABLED_CODE}: công tắc {RESEARCH_REFRESH_ENV} đang '
                         f'{mode!r} — không mở run làm mới')
    state = dict(job['state'] or {})
    scope = state.get('scope') if isinstance(state.get('scope'), dict) else {}
    latest = rt.store.dossier_latest(source_id)
    if latest is None:
        raise ValueError(f'{RESEARCH_REFRESH_NO_DOSSIER_CODE}: {source_id} chưa có bản hồ sơ nào — '
                         f'phải có hồ sơ rồi mới có cái để làm mới')
    if str(job.get('status') or '') not in _REFRESHABLE_JOB_STATUSES:
        raise ValueError(f'{RESEARCH_REFRESH_SOURCE_ACTIVE_CODE}: {source_id} đang '
                         f'{job.get("status")!r} — tạm dừng hoặc để nó xong rồi hãy làm mới')
    for other in rt.store.research_jobs_for(sid):
        other_state = other.get('state') or {}
        if str(other_state.get('refreshOf') or '') == source_id \
                and str(other.get('status') or '') not in _REFRESHABLE_JOB_STATUSES:
            raise ValueError(f'{RESEARCH_REFRESH_RUN_ACTIVE_CODE}: run làm mới '
                             f'{other["research_id"]!r} của {source_id} đang '
                             f'{other.get("status")!r} — chờ nó xong')
    since = str(scope.get('surveyDate') or '').strip() or research_evidence.survey_date()
    kinds = [str(item).strip() for item in (scope.get('jobKinds') or []) if str(item).strip()]
    if 'refresh' not in kinds:
        kinds.append('refresh')
    config = research_config(session)
    question = str(state.get('question') or config.get('question') or '').strip() \
        or str(state.get('goal') or '').strip()
    if not question:
        raise ValueError(f'RESEARCH_BRIEF_INVALID: run {source_id} không có câu hỏi nào để làm mới — '
                         f'làm mới phải giữ nguyên câu hỏi của run gốc')
    questions = [{'text': str(item.get('text') or '').strip(),
                  'importance': str(item.get('importance') or 'medium'),
                  'doneWhen': str(item.get('doneWhen') or '')}
                 for item in (state.get('questions') or [])
                 if isinstance(item, dict) and str(item.get('text') or '').strip()]
    jobs = rt.store.research_jobs_for(sid)
    wanted = str(payload.get('researchId') or '').strip()
    if wanted and slug_from_question(question, wanted).lower() == source_id.lower():
        raise ValueError(f'RESEARCH_BRIEF_INVALID: researchId {wanted!r} trùng đúng run đang được làm '
                         f'mới ({source_id}) — run mới phải là một run RIÊNG')
    # Câu hỏi của run làm mới giữ NGUYÊN, mà mã run cũ chính là slug của câu hỏi ấy — nên khuôn slug
    # tự nhiên sẽ trùng đúng mã run gốc. Ghim sẵn một mã riêng để run mới không ghi đè run cũ.
    target_id = wanted or f'{source_id[:30].rstrip("-")}-r{len(jobs) + 1}'
    answer = await research_brief(rt, session, {
        'question': question,
        'rationale': (f'làm mới {source_id}: giữ nguyên câu hỏi và mức, dựng lại nguồn từ mốc khảo '
                      f'sát {since}'),
        'tier': int(state.get('tier') or config.get('tier') or RESEARCH_TIER_DEFAULT),
        'jobProfile': str(config.get('jobProfile') or '').strip(),
        'goal': str(state.get('goal') or question),
        'output': str(state.get('output') or ''),
        'questions': questions,
        'methods': [str(item) for item in (state.get('methods') or []) if str(item).strip()],
        'budgetSeconds': int(state.get('budgetSeconds') or 0) or None,
        'newRun': True,
        'ownerInitiated': True,
        'inheritsFrom': source_id,
        'researchId': target_id,
        'scope': {**scope, 'jobKinds': kinds},
    })
    new_id = str(answer.get('researchId') or '')
    if not new_id or new_id.lower() == source_id.lower():
        raise ValueError(f'RESEARCH_BRIEF_INVALID: run làm mới trùng mã run gốc ({source_id}) — mã '
                         f'phải khác để sổ và hồ sơ hai run không trộn nhau')
    new_job = rt.store.research_job(new_id)
    new_state = dict(new_job['state'] or {}) if new_job else {}
    new_scope = dict(new_state.get('scope') or scope)
    new_scope['jobKinds'] = kinds
    # Mốc khảo sát của RUN MỚI là hôm nay: "hiện tại" của lần làm mới không thể là mốc của run cũ.
    new_scope['surveyDate'] = research_evidence.survey_date()
    _scope_window(new_scope)
    new_state['scope'] = new_scope
    new_state['refreshOf'] = source_id
    new_state['refreshSince'] = since
    new_state['supersedes'] = int(latest['version'])
    saved = rt.store.research_job_save(new_id, sid, new_state,
                                       status=(new_job or {}).get('status') or 'scoping')
    inherited = int(answer.get('inheritedRows') or 0)
    dependent = rt.store.research_dependent_plans(source_id)
    rt.store.emit(sid, 'research_refresh', {
        'researchId': new_id, 'refreshOf': source_id, 'sinceDate': since,
        'inheritedRows': inherited, 'dependentPlans': len(dependent),
        'at': journal.utc_now_iso()})
    if dependent:
        rt.store.emit(sid, 'notice', {
            'code': 'RESEARCH_REFRESH_PLANS', 'partial': False, 'researchId': new_id,
            'message': (f'RESEARCH_REFRESH_PLANS: {len(dependent)} kế hoạch đang dựa vào {source_id} — '
                        f'dùng lại chúng thì phải soi lại theo bản hồ sơ mới')})
    return {'researchId': new_id, 'refreshOf': source_id, 'sinceDate': since,
            'inheritedRows': inherited, 'dependentPlans': len(dependent), 'scope': new_scope,
            'supersedes': int(latest['version']), 'revision': saved['revision'],
            'changelog': _changelog_body(rt, new_id, 0),
            'next': (f'run {new_id} đã chép {inherited} dòng sổ của {source_id} ở trạng thái '
                     f'{RESEARCH_REFRESH_INHERITED_STATUS} — `source_verify` lại trước khi dùng cho '
                     f'nhận định "hiện tại"')}


async def _halt_action(rt, session, job, action):
    """Pause/cancel MỘT job qua `runtime.research_halt` (§4.6/§5.3). Không dừng cả phiên."""
    await rt.research_halt(job, 'pause' if action == 'pause' else 'cancel')
    updated = rt.store.research_job(job['research_id'])
    return {'researchId': job['research_id'], 'action': action,
            'status': (updated or job)['status'], 'background': bool((updated or job)['state'].get('background'))}


def _copy_inherited_rows(rt, sid, inherits, new_run_id):
    """Chép sổ nguồn của run cũ sang run mới với cờ `inherited=true` (§5.3).

    Dòng kế thừa giữ NGUYÊN url/đoạn trích nhưng trạng thái về `unverified`: nó phải qua
    `source_verify` lại trước khi đỡ một nhận định "hiện tại".
    """
    source_job = rt.store.research_job(inherits)
    if source_job is None or source_job['session_id'] != sid:
        raise ValueError('RESEARCH_INHERIT_UNKNOWN: inheritsFrom must name a run of this session')
    copied = 0
    for row in rt.store.source_rows(sid, research_id=inherits, limit=SOURCE_ROW_LIMIT_MAX):
        payload = dict(row.get('payload') or {})
        payload['inherited'] = True
        payload['inheritedFrom'] = inherits
        rt.store.source_add(sid, {
            'claim': row.get('claim') or '', 'url': row.get('url') or '', 'host': row.get('host') or '',
            'tier': row.get('tier'), 'type': row.get('type'), 'excerpt': row.get('excerpt') or '',
            'fetched_at': row.get('fetchedAt') or '', 'origin': row.get('origin'),
            'method': row.get('method'), 'status': RESEARCH_REFRESH_INHERITED_STATUS,
            'fingerprint': row.get('fingerprint') or '',
            'payload': payload, 'branches': [], 'child_id': None,
            'job': new_run_id, 'research_id': new_run_id,
            'turn': int(rt.active_turn.get(sid) or 0), 'step': rt.active_step.get(sid)})
        copied += 1
    if copied:
        rt.store.emit(sid, 'notice', {
            'code': 'RESEARCH_INHERITED', 'partial': False, 'researchId': new_run_id,
            'message': (f'RESEARCH_INHERITED: {copied} dòng sổ của {inherits} đã được chép sang '
                        f'{new_run_id} với cờ inherited — phải `source_verify` lại trước khi dùng cho '
                        f'nhận định "hiện tại"')})
    return copied


def close_run(rt, session, job, state, status, reason, revision=None):
    """Đóng một run qua MỘT cửa: ghim lý do, đưa pha về `done`, lưu, rồi phát thẻ báo cáo.

    Ba đường cùng kết thúc một run đi qua đây: model khai `completed`/`partial`
    (`research_update`), bơm cạn ngân sách, và bơm phát hiện đứng yên hai lượt (`api/server.py`).
    Đo sống 2026-09-26: `partial` do model khai đóng run mà không có thẻ báo cáo nào (gap B), còn
    hai đường BƠM thì tệ hơn — chúng gọi thẳng `finish_background_run`, hàm này tự bỏ qua khi
    `state.background` tắt, nên một run TIỀN CẢNH biến mất không thẻ, không `research_run`, và
    `phase` kẹt ở `searching` để thanh tiến trình kể về một run đã chết (đợt soát `3dc745f`,
    finding 2). Thẻ báo cáo của run nền do `_finish_background` phát (qua cùng `emit_report_card`),
    nên ở đây chỉ phát thêm khi run KHÔNG chạy nền.

    `revision` là khoá lạc quan của model khi nó gửi kèm (`research_update`), và hàng vừa đọc khi
    không (bơm): truyền `None` là dùng `job['revision']`.
    """
    state = dict(state or job['state'] or {})
    if status == 'partial' and not state.get('stopReason'):
        state['stopReason'] = str(reason or '')[:2000]
    state['phase'] = PHASE_DONE
    _phase_history(state, PHASE_DONE, f'job-{status}')
    updated = rt.store.research_job_save(job['research_id'], session['id'], state, status,
                                         revision=job['revision'] if revision is None else revision)
    was_background = bool((updated['state'] or {}).get('background'))
    finish_background_run(rt, session, updated)
    if not was_background:
        emit_report_card(rt, session['id'], updated)
        rt.store.emit(session['id'], 'research_run', {
            'researchId': job['research_id'], 'status': updated['status'], 'phase': PHASE_DONE,
            'background': False, 'revision': updated['revision'],
            'reason': f'job-{updated["status"]}', 'at': journal.utc_now_iso()})
    return updated


def finish_background_run(rt, session, job):
    """Cửa kết thúc DUY NHẤT của một run chạy nền (§5.10, F6).

    Mọi nhánh kết thúc run (mô hình gọi `research_update status=completed`, bơm cạn ngân sách, bơm
    phát hiện đứng yên) phải đi qua ĐÂY — nếu không, run biến mất im lặng: không `research_report`,
    không `research_notice{background-done}`, và `state.background` còn mãi khiến bơm chạy lại phần
    đã xong. Trả về job sau khi ghi (đã tắt cờ nền), hoặc chính `job` khi nó không chạy nền.
    """
    if job is None:
        return job
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    if not state.get('background'):
        return job
    _finish_background(rt, session, job)
    return rt.store.research_job(job['research_id'])


def emit_report_card(rt, sid, job):
    """Phát `research_report` — thẻ báo cáo của một run đã đóng — và trả về số phiên bản hồ sơ.

    Tách khỏi `_finish_background` từ khi run TIỀN CẢNH cũng cần thẻ (B1): nhãn của thẻ (`partial`,
    `chưa đạt phản biện`, `bao phủ chưa đủ`) là hợp đồng người dùng đọc được, nên nó phải do ĐÚNG một
    hàm dựng — hai bản chép tay sẽ lệch nhau ở lần sửa thứ ba. `state` đọc từ chính hàng job: cả hai
    cửa gọi đều truyền hàng vừa ghi, nên một tham số `state` chỉ là chỗ để hai bên lệch nhau.
    """
    latest = rt.store.dossier_latest(job['research_id'])
    labels = []
    if job['status'] == 'partial':
        labels.append('partial')
    review_modes = [name for name in GATE_REVIEW_MODES
                    if name in ((job.get('state') or {}).get('reviewModes') or [])]
    if latest is not None and review_modes and latest.get('critique') != 'ok':
        labels.append(RESEARCH_CRITIQUE_LABEL)
    if latest is not None and not latest.get('quality_ok') and job['status'] != 'partial':
        labels.append(RESEARCH_COVERAGE_LABEL)
    # P3 (§5.9): hướng bị bỏ ở mức `high` mà chưa xử lý ⇒ nhãn `bao phủ chưa đủ`, kể cả khi cổng
    # chất lượng của hồ sơ đã qua. Nguồn: `issues[].kind` của các lần ghi phán quyết (P2 giữ trường
    # này trong `research_verifications`).
    if latest is not None:
        open_issues = [issue for review in rt.store.research_verifications(job['research_id'])
                       for issue in (review.get('issues') or [])]
        if research_review.has_unhandled_missing_direction(open_issues) and \
                RESEARCH_COVERAGE_LABEL not in labels:
            labels.append(RESEARCH_COVERAGE_LABEL)
    version = int(latest['version']) if latest is not None else 0
    rt.store.emit(sid, 'research_report', {
        'researchId': job['research_id'], 'version': version,
        'path': latest['relative_path'] if latest is not None else '',
        'labels': labels,
        'summary': f'{job["research_id"]} v{version} · {job["status"]}'})
    return version


def _finish_background(rt, session, job):
    """Run chạy nền tới `completed`/`partial` (§5.10): thẻ báo cáo + thông báo, tắt `state.background`.

    Runtime **không** tự mở lượt main: khối bàn giao vào lượt main KẾ TIẾP của người dùng, một lần
    cho mỗi bản hồ sơ (`researchMode.handoffDeliveredVersion`).
    """
    sid = job['session_id']
    state = dict(job['state'] or {})
    state['background'] = False
    rt.store.research_job_save(job['research_id'], sid, state)
    version = emit_report_card(rt, sid, job)
    rt.store.emit(sid, 'research_notice', {'researchId': job['research_id'], 'kind': 'background-done'})
    rt.store.emit(sid, 'research_run', {'researchId': job['research_id'], 'status': job['status'],
                                        'phase': state.get('phase'), 'background': False,
                                        'revision': job['revision']})
    system_log.write('research.background.done', level='info', session_id=sid,
                     code='RESEARCH_BACKGROUND_DONE', researchId=job['research_id'],
                     status=job['status'], version=version)
