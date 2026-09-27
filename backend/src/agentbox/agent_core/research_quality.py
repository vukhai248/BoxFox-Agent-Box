"""Cổng chất lượng research (vòng 27 · B-3b/C-2) — ngoài `evidence_gate.py` (I1).

Hai tầng, cả hai **không** đụng `evidence_gate`:

* **Tầng con — chú thích tất định** (`annotate_child_answer`): không công tắc, không chặn, chỉ
  gắn `researchGate = {issues, remedy, rows, mode: 'note'}` vào payload `child_finish`.
* **Tầng hồ sơ — cổng có công tắc** (`assess`): chạy **trước khi ghi** hồ sơ; `enforce` ⇒ từ chối,
  `warn` ⇒ ghi + notice, `off` ⇒ không kiểm.

Công tắc: `BOXFOX_RESEARCH_GATE` (`limits.RESEARCH_GATE_ENV`), giá trị lạ ⇒ mặc định `enforce`
+ mã `RESEARCH_GATE_MODE_UNKNOWN`. Không bao giờ ném trong `assess`/`annotate_*` — người gọi quyết định.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from . import plan_quality
from . import limits
from . import research_report
from .limits import (
    RESEARCH_GATE_DEFAULT_MODE,
    RESEARCH_GATE_ENV,
    RESEARCH_GATE_MODES,
    RESEARCH_MIN_EXCERPT_CHARS,
    RESEARCH_QUALITY_PREFIX,
)
from .research_ledger import Issue, Row, assess_rows, claims_index, independent_count, origin_units, tier_of
from .reading import fold_text, normalize_url

# --- Mã lỗi ----------------------------------------------------------------

RESEARCH_CODES: tuple[str, ...] = (
    'research-sources-missing',
    'research-sources-unproven',
    'research-findings-unlinked',
    'research-excerpt-missing',
    'research-tier-unknown',
    'research-claim-single-source',
    'research-origin-undeclared',
    'research-host-doc-unmarked',
    'research-doc-pointer-missing',
    'research-validity-missing',
    'research-social-unconfirmed',
    'research-profile-field-missing',
    'research-shape-missing',
    'research-critique-missing',
    'research-lineage-missing',
    'research-owner-views-missing',
    # P2 — cổng cấu trúc trên `report` (bật/tắt bằng `BOXFOX_RESEARCH_STRUCTURED_REPORT`) và cổng
    # chính sách thời gian. Mã của bộ kiểm cấu trúc lấy thẳng từ `research_report` (một nguồn).
    research_report.ERROR_MISSING,
    research_report.ERROR_MODULE_UNKNOWN,
    research_report.ERROR_MODULE_MISSING,
    research_report.ERROR_SECTION_MISSING,
    research_report.ERROR_CLAIM_MISSING,
    research_report.ERROR_CLAIM_UNKNOWN,
    research_report.ERROR_UNEXPLORED_MISMATCH,
    research_report.ERROR_INFERENCE_CONFIDENCE,
    #: Mã gói "có lỗi cấu trúc" (bộ đánh giá đọc để khỏi phải biết từng mã lẻ).
    limits.RESEARCH_REPORT_STRUCTURE_CODE,
    limits.RESEARCH_STALE_CURRENT_CLAIM_CODE,
)

#: Ba nhãn soi ý kiến chủ nhà (#6025) — `(nhãn tiếng Việt, từ tiếng Anh nhận dạng)`. Máy chỉ kiểm
#: **sự hiện diện** của ba nhãn (kèm nguồn trên cùng dòng): nội dung do model viết.
OWNER_VIEW_LABELS: tuple[tuple[str, str], ...] = (
    ('ủng hộ', 'support'),
    ('phản bác', 'contradict'),
    ('chưa chắc', 'unsure'),
)

#: Một câu khắc phục cho mỗi mã — máy chép vào payload, người đọc hiểu ngay.
REMEDIES: Mapping[str, str] = {
    'research-sources-missing': 'Thêm dòng sổ cho từng khẳng định, hoặc ghi rõ "kết luận từ mã trong workspace".',
    'research-sources-unproven': 'Mở URL bằng `web_fetch` rồi `source_add` kèm đoạn trích nguyên văn.',
    'research-findings-unlinked': 'Đặt mã dòng sổ [rN] ngay cạnh mỗi kết luận thực nghiệm hoặc ghi rõ đó là suy luận/chưa biết.',
    'research-excerpt-missing': f'Lưu đoạn trích nguyên văn ≥ {RESEARCH_MIN_EXCERPT_CHARS} ký tự đã đọc, không phải tóm tắt.',
    'research-tier-unknown': 'Khai `type` (`host-doc`/`official-social`) hoặc dùng nguồn xếp được tầng.',
    'research-claim-single-source': 'Thêm nguồn thứ hai ở host khác, viết độc lập (bản đăng lại cùng bản tin hoặc cùng `origin` đã khai vẫn tính một nguồn), hoặc hạ khẳng định xuống "suy luận".',
    'research-origin-undeclared': 'Khai `origin` cho dòng bị đăng lại (ví dụ `nguồn: TTXVN`).',
    'research-host-doc-unmarked': 'Đánh dấu dòng là "do chủ nhà cung cấp" (`type=\'host-doc\'`).',
    'research-doc-pointer-missing': 'Trỏ bản gốc bằng nguồn tầng 1; không mở được thì ghi "chưa mở được bản gốc".',
    'research-validity-missing': 'Ghi số hiệu + ngày hiệu lực + còn/hết hiệu lực cho khẳng định văn bản.',
    'research-social-unconfirmed': 'Thêm trang web của cơ quan hoặc báo chính thống nhắc lại cùng nội dung.',
    'research-profile-field-missing': 'Bổ sung trường bắt buộc của hồ sơ, hoặc đổi sang hồ sơ đúng.',
    'research-shape-missing': 'Bổ sung mục còn thiếu của hồ sơ rồi ghi lại.',
    'research-critique-missing': 'Giao `research-review` rồi gọi `research_verify` cho đúng version này.',
    'research-lineage-missing': 'Mỗi nhánh con `research` phải để lại ít nhất một dòng sổ.',
    'research-owner-views-missing': 'Thêm mục soi ý kiến chủ nhà đủ ba nhãn ủng hộ / phản bác / chưa chắc, mỗi nhãn kèm nguồn.',
    # P2 — cổng cấu trúc (`report`) và cổng chính sách thời gian.
    'research-report-missing': 'Gửi kèm `report` là object có `modules`/`sections`/`claims` thay cho văn xuôi tự do.',
    'research-report-module-unknown': 'Chỉ khai mô-đun có trong danh mục (`research_report.module_ids()`) hoặc bỏ mô-đun lạ.',
    'research-report-module-missing': 'Thêm mô-đun bắt buộc của kiểu việc đã chọn, hoặc hạ kiểu việc cho đúng phần đã làm.',
    'research-report-section-missing': 'Bổ sung mục khung còn thiếu của hồ sơ (kèm `sectionId` đúng danh mục).',
    'research-report-claim-missing': 'Mỗi nhận định chính phải có `claimId` trỏ vào sổ dòng của run.',
    'research-report-claim-unknown': 'Trỏ `claimId` vào dòng sổ có thật, hoặc bỏ nhận định không có dòng sổ.',
    'research-report-unexplored-mismatch': 'Mục "Chưa khảo sát" phải khớp đúng tập facet chưa bão hoà của run.',
    'research-report-inference-confidence': 'Nhận định suy luận phải khai `confidence` dữ kiện và liệt kê `premises` (claim id).',
    limits.RESEARCH_REPORT_STRUCTURE_CODE: 'Sửa các lỗi cấu trúc lẻ ở trên rồi ghi lại hồ sơ.',
    limits.RESEARCH_STALE_CURRENT_CLAIM_CODE: 'Tìm nguồn trong cửa sổ thời gian cho nhận định hiện trạng, hoặc đổi nhận định thành quá khứ/suy luận.',
}

#: Hai mã này sống ở `limits` (nguồn chân lý cho mã notice của vòng 27) — giữ tên ở đây làm bí danh
#: cho những chỗ gọi `research_quality.<MÃ>`, chứ không chép lại chuỗi (chép là hai chỗ trôi lệch).
NOTICE_CODE = limits.RESEARCH_GATE_NOTE_CODE
MODE_UNKNOWN_CODE = limits.RESEARCH_GATE_MODE_UNKNOWN_CODE

# --- Hình dạng hồ sơ theo mức ----------------------------------------------

#: Từ khoá nhận dạng TIÊU ĐỀ theo từng mục — khớp **bỏ dấu + không phân biệt hoa thường**, và khớp
#: theo kiểu *chứa* (`variant in line`), nên một tiêu đề dài như "Kết luận chính (mức 2)" vẫn khớp
#: `ket luan`. Bộ từ của mỗi mục là hợp của ba nguồn: từ tiếng Anh trong hợp đồng `dossier_write`,
#: từ tiếng Việt tự nhiên model hay viết, và các biến thể đã gặp trong lượt thật.
_QUESTION_WORDS: tuple[str, ...] = ('cau hoi', 'question', 'muc tieu')
_FINDINGS_WORDS: tuple[str, ...] = (
    'phat hien', 'ket qua', 'findings',           # bản gốc
    'ket luan', 'tong ket', 'diem chinh',         # tiếng Việt tự nhiên (lượt thật 2026-09-24: "Kết luận chính")
    'nhan xet', 'so lieu', 'bang chung',
)
_SOURCES_WORDS: tuple[str, ...] = ('nguon', 'sources', 'dan nguon', 'tai lieu tham khao', 'tham khao')
_CONFLICTS_WORDS: tuple[str, ...] = (
    'mau thuan', 'conflict',
    'xung dot', 'chua thong nhat', 'khac biet', 'bat dong',
)
# Cố ý KHÔNG có `con lai`: tiêu đề chuẩn của mục Mâu thuẫn là "Mâu thuẫn còn lại" — thêm `con lai` là
# mục Mâu thuẫn tự thoả luôn mục Việc chưa làm.
_TODO_WORDS: tuple[str, ...] = (
    'chua lam', 'viec chua', 'open', 'ambigu',
    'viec con', 'chua xong', 'han che', 'gioi han', 'cau hoi mo', 'can lam tiep',
)
#: `nhan xet` nằm ở CẢ hai mục: tiêu đề "Nhận xét" vừa có thể là chỗ kê điều rút ra, vừa là chỗ soi
#: lại. Chỉ TIÊU ĐỀ được quét (thân bài không), và mọi luật theo DÒNG (nguồn, đoạn trích, tầng) vẫn
#: nguyên độ chặt — nới bộ từ ở đây là để cổng thôi từ chối oan hồ sơ viết bằng tiếng Việt tự nhiên.
_CRITIQUE_WORDS: tuple[str, ...] = ('phan bien', 'critique', 'review', 'nhan xet', 'soi xet', 'diem yeu')

#: Bí danh CÔNG KHAI của ba bộ từ trên — `scripts/eval/research_checks.py` đọc tên công khai trước,
#: tên riêng tư chỉ là đường lui cho bản cũ. Một nguồn định nghĩa: ở đây gán chứ không chép lại từ,
#: để bộ từ không trôi lệch giữa cổng (chấm thật) và bộ đánh giá (chấm điểm).
FINDINGS_SECTION_WORDS: tuple[str, ...] = _FINDINGS_WORDS
CONFLICT_SECTION_WORDS: tuple[str, ...] = _CONFLICTS_WORDS
CRITIQUE_SECTION_WORDS: tuple[str, ...] = _CRITIQUE_WORDS

#: `mức -> ((khoá, nhãn), các từ khoá nhận dạng trong TIÊU ĐỀ)`. Khớp bỏ dấu, không phân biệt hoa thường.
DOSSIER_SECTIONS: Mapping[int, tuple[tuple[str, tuple[str, ...]], ...]] = {
    1: (
        ('question', _QUESTION_WORDS),
        ('findings', _FINDINGS_WORDS),
        ('sources', _SOURCES_WORDS),
    ),
    2: (
        ('question', _QUESTION_WORDS),
        ('findings', _FINDINGS_WORDS),
        ('sources', _SOURCES_WORDS),
        ('conflicts', _CONFLICTS_WORDS),
        ('todo', _TODO_WORDS),
    ),
    3: (
        ('question', _QUESTION_WORDS),
        ('findings', _FINDINGS_WORDS),
        ('sources', _SOURCES_WORDS),
        ('conflicts', _CONFLICTS_WORDS),
        ('todo', _TODO_WORDS),
        ('critique', _CRITIQUE_WORDS),
    ),
}

SECTION_LABELS: Mapping[str, str] = {
    'question': 'mục Câu hỏi',
    'findings': 'mục Phát hiện',
    'sources': 'mục Nguồn',
    'conflicts': 'mục Mâu thuẫn còn lại',
    'todo': 'mục Việc chưa làm',
    'critique': 'mục Phản biện',
}

_URL_RE = re.compile(r'https?://[^\s)\]<>"\'`]+', re.IGNORECASE)
# Dấu câu dính vào CUỐI URL trong văn xuôi (`… tại https://a.vn/x.`, `(https://a.vn/x),`,
# `**https://a.vn/x**`). Bỏ chúng là bắt buộc: `normalize_url` không cắt, và một URL sạch trong sổ
# nguồn bị so với bản còn dấu câu sẽ đội lốt "nguồn chưa chứng minh" ⇒ cổng `enforce` TỪ CHỐI hồ sơ
# không có gì sai, kèm cách sửa không thể thi hành (vòng 27, đợt 8).
_TRAILING_JUNK = '.,;:!?*`"\'’”)'
_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s+(.*)$', re.MULTILINE)
_ROW_ID_RE = re.compile(r'\br\d{1,4}\b')


def headings(markdown: str) -> list[str]:
    """Tiêu đề trong hồ sơ (đã bỏ dấu, viết thường) — chỉ tiêu đề, không quét thân bài."""
    return [fold_text(match.group(1)) for match in _HEADING_RE.finditer(str(markdown or ''))]


def missing_sections(markdown: str, level: int) -> list[str]:
    """Nhãn các mục bắt buộc còn thiếu ở mức này."""
    found = headings(markdown)
    missing: list[str] = []
    for key, variants in DOSSIER_SECTIONS.get(int(level or 1), DOSSIER_SECTIONS[1]):
        if any(any(variant in line for variant in variants) for line in found):
            continue
        missing.append(SECTION_LABELS.get(key, key))
    return missing


def clean_url(value: str) -> str:
    """Bỏ dấu câu dính ở cuối một URL trong văn xuôi, rồi chuẩn hoá (`normalize_url`).

    Dùng chung cho cả hai mặt đọc URL (`urls_in` của hồ sơ và phần chú thích nhánh con) để hai mặt
    không bao giờ lệch nhau về định nghĩa "một URL".
    """
    text = str(value or '').strip()
    while text and text[-1] in _TRAILING_JUNK:
        text = text[:-1].rstrip()
    # Một dấu `/` lẻ ở cuối cũng hay bị gõ thêm trong câu, nhưng `/` là phần thật của nhiều đường dẫn
    # (`…/x/`), nên chỉ bỏ khi bản bỏ đi khớp một URL đã biết — việc so khớp đó thuộc về người gọi.
    return normalize_url(text)


def urls_in(markdown: str) -> list[str]:
    """URL xuất hiện trong hồ sơ, đã bỏ dấu câu cuối + chuẩn hoá, giữ thứ tự."""
    out: list[str] = []
    for match in _URL_RE.finditer(str(markdown or '')):
        value = clean_url(match.group(0))
        if value and value not in out:
            out.append(value)
    return out


def has_external_claims(markdown: str) -> bool:
    """Hồ sơ có khẳng định ngoài (viện dẫn nguồn ngoài) hay không."""
    return bool(urls_in(markdown)) or bool(plan_quality.cited_hosts(markdown))


def findings_without_evidence(markdown: str) -> bool:
    """Flag a substantive findings section with no evidence pointer at all."""
    lines = str(markdown or '').splitlines()
    in_findings = False
    body: list[str] = []
    for line in lines:
        heading = _HEADING_RE.match(line)
        if heading:
            label = fold_text(heading.group(1))
            if in_findings:
                break
            in_findings = any(word in label for word in _FINDINGS_WORDS)
        elif in_findings:
            body.append(line)
    text = '\n'.join(body).strip()
    return len(text) >= 60 and not _ROW_ID_RE.search(text) and not _URL_RE.search(text)


def gate_mode(env: Mapping[str, str] | None = None) -> tuple[str, str | None]:
    """`(mode, giá trị lạ)`. Giá trị hợp lệ ⇒ phần tử hai là `None` — cùng hợp đồng với `_mode`.

    Bản trước trả `(raw, raw)` cả khi `raw` hợp lệ, nên mọi lời gọi `dossier_write` với
    `BOXFOX_RESEARCH_GATE=warn` lại phát notice `RESEARCH_GATE_MODE_UNKNOWN` ("giá trị lạ") trong khi
    `mode` áp đúng là `warn` — một lời báo sai ở đúng đường chủ nhà đọc (vòng 27, đợt 8).
    """
    source = os.environ if env is None else env
    raw = str(source.get(RESEARCH_GATE_ENV, '') or '').strip().lower()
    if raw in RESEARCH_GATE_MODES:
        return raw, None
    return RESEARCH_GATE_DEFAULT_MODE, raw or None


# --- Kết luận --------------------------------------------------------------


@dataclass
class Verdict:
    """Kết luận của cổng tầng hồ sơ."""

    ok: bool
    mode: str = RESEARCH_GATE_DEFAULT_MODE
    label: str = ''
    issues: list[Issue] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)
    counts: dict[str, Any] = field(default_factory=dict)

    @property
    def missing(self) -> list[dict[str, str]]:
        return issue_dicts(self.issues)

    def to_payload(self) -> dict[str, Any]:
        return {
            'ok': self.ok,
            'mode': self.mode,
            'label': self.label,
            'issues': [issue.code for issue in self.issues],
            'missing': self.missing,
            'softMissing': list(self.soft),
            'counts': dict(self.counts),
        }


def issue_dicts(issues: Iterable[Issue]) -> list[dict[str, str]]:
    """`[{code, detail, remedy}]` — đúng thứ tự, đã bỏ trùng."""
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        key = (issue.code, issue.detail)
        if key in seen:
            continue
        seen.add(key)
        out.append({'code': issue.code, 'detail': issue.detail, 'remedy': REMEDIES.get(issue.code, '')})
    return out


def counts_for(rows: Sequence[Row], *, children: Iterable[str] = ()) -> dict[str, Any]:
    """Số liệu máy đếm được: dòng, nguồn độc lập, host, tầng, con."""
    tiers: dict[str, int] = {}
    for row in rows:
        tiers[str(row.tier)] = tiers.get(str(row.tier), 0) + 1
    return {
        'rows': len(rows),
        'independent': independent_count(rows),
        'hosts': len({row.host for row in rows}),
        'tiers': tiers,
        'children': len({row.child_id for row in rows if row.child_id}),
        'units': [{'id': unit.unit_id, 'hosts': list(unit.hosts), 'reason': unit.reason, 'tier': unit.tier}
                  for unit in origin_units(rows)],
        'plannedChildren': len(list(children)),
    }


def critique_required(level: int) -> bool:
    """Mức này có mục Phản biện bắt buộc không — đọc từ chính bảng mục, không chép tay số mức."""
    return any(key == 'critique' for key, _variants in DOSSIER_SECTIONS.get(int(level or 1), ()))


def assess(
    session: Any = None,
    *,
    profile: Any = None,
    level: int = 2,
    markdown: str = '',
    rows: Sequence[Row] = (),
    child_ids: Iterable[str] = (),
    mode: str | None = None,
    critique_ok: bool = True,
    verified: Mapping[str, bool] | None = None,
    owner_views: Sequence[str] = (),
    review: str = '',
    require_claim_citations: bool = False,
    report: Any = None,
    job_types: Any = (),
    facets: Any = None,
    claim_ids: Any = None,
    extra_issues: Sequence[Any] = (),
) -> Verdict:
    """Cổng tầng hồ sơ. `mode=None` ⇒ đọc từ môi trường. Không bao giờ ném.

    P2 — khi có `report` (báo cáo có cấu trúc) **và** công tắc `BOXFOX_RESEARCH_STRUCTURED_REPORT`
    bật, hình dạng hồ sơ được chấm bằng `research_report.validate_report()` (mục khung, mô-đun bắt
    buộc, `claimId` trỏ vào sổ, mục "Chưa khảo sát" khớp facet) thay cho luật dò từ khoá tiêu đề.
    Công tắc `off` giữ nguyên hành vi cũ từng byte — `report` khi đó bị bỏ qua.

    `extra_issues` là chỗ máy chấm gắn thêm lỗi đã tính sẵn (ví dụ cổng chính sách thời gian); chúng
    đi cùng kênh với lỗi cấu trúc nên `warn` cũng kể ra, `enforce` cũng từ chối.
    """
    _ = session  # chỗ cắm cho tương lai; cổng này thuần theo tham số
    selected_mode = (mode or gate_mode()[0]).strip().lower()
    if selected_mode not in RESEARCH_GATE_MODES:
        selected_mode = RESEARCH_GATE_DEFAULT_MODE

    rows = list(rows or [])
    issues: list[Issue] = []
    soft: list[str] = []

    if selected_mode != 'off':
        structured = report is not None and limits.research_structured_report_enabled()
        if structured:
            for item in research_report.validate_report(report, job_types=job_types, level=level,
                                                        facets=facets, claim_ids=claim_ids):
                code = str((item or {}).get('code') or '')
                if code:
                    issues.append(Issue(code, str((item or {}).get('detail') or '')))
        else:
            for label in missing_sections(markdown, level):
                issues.append(Issue('research-shape-missing', label))

        for item in extra_issues or ():
            # Lỗi đã tính sẵn của máy (`research_ledger.Issue`) — đi cùng kênh với lỗi cấu trúc.
            code = str(getattr(item, 'code', '') or '')
            if code:
                issues.append(Issue(code, str(getattr(item, 'detail', '') or '')))

        # `r12` mà sổ không có — dấu vết trỏ sai; hồ sơ này chưa mở được dòng nào.
        for row_id in pinned_row_ids(markdown, rows):
            issues.append(Issue('research-sources-unproven', f'{row_id} không có trong sổ'))

        known_urls = {clean_url(row.url) for row in rows}
        unproven = [url for url in urls_in(markdown) if url not in known_urls]
        if rows:
            for url in unproven:
                issues.append(Issue('research-sources-unproven', url))
        elif has_external_claims(markdown) or require_claim_citations:
            issues.append(Issue('research-sources-missing', f'{len(urls_in(markdown))} URL, 0 dòng sổ'))

        if require_claim_citations and findings_without_evidence(markdown):
            issues.append(Issue('research-findings-unlinked', 'mục Phát hiện không trỏ tới dòng sổ'))

        # A verbatim short sentence can be the entire relevant passage. V2
        # checks its source and relation separately, so padding to 80 chars
        # would reward invented context rather than faithful quotation.
        issues.extend(assess_rows(rows, profile, verified=verified,
                                  min_excerpt_chars=(1 if require_claim_citations
                                                     else RESEARCH_MIN_EXCERPT_CHARS)))

        planned = [str(item) for item in child_ids if str(item)]
        # Một nhánh để lại dấu vết khi dòng sổ mang mã nhánh ấy — hoặc ở cột `child_id` (nhánh ghim
        # dòng) hoặc trong `branches` (nhánh thứ hai mở CÙNG nguồn với đoạn trích y hệt).
        seen_children = {row.child_id for row in rows if row.child_id}
        seen_children.update(str(item) for row in rows for item in (row.branches or ()) if str(item))
        for child_id in planned:
            if child_id not in seen_children:
                issues.append(Issue('research-lineage-missing', child_id))

        # Phản biện là chuyện của MỨC có mục Phản biện (mức 3, `DOSSIER_SECTIONS`): dưới mức đó
        # không ai chạy phản biện, nên `critique_ok=False` không được biến thành lời từ chối.
        if selected_mode == 'enforce' and not critique_ok and critique_required(level):
            issues.append(Issue('research-critique-missing', f'mức {level}'))

        for field_label in hard_missing(profile, rows):
            issues.append(Issue('research-profile-field-missing', field_label))

        # #6025 — brief có ý kiến/giả định của chủ nhà ⇒ hồ sơ PHẢI có mục soi ý kiến ba nhãn,
        # mỗi nhãn kèm nguồn. Máy chỉ kiểm sự hiện diện (`owner_view_findings`); ở đây chấm trên
        # tệp `review.md` khi có, không thì trên chính hồ sơ.
        if [item for item in (owner_views or []) if str(item).strip()]:
            missing_labels, unsourced = owner_view_findings(review or markdown)
            if missing_labels:
                issues.append(Issue('research-owner-views-missing',
                                    'thiếu nhãn: ' + ', '.join(missing_labels)))
            if unsourced:
                issues.append(Issue('research-owner-views-missing',
                                    'nhãn chưa kèm nguồn: ' + ', '.join(unsourced)))

        soft = soft_missing(profile, rows)

    counts = counts_for(rows, children=child_ids)
    label = profile_label(profile)
    ok = not issues
    if selected_mode == 'off':
        ok = True
    return Verdict(ok=ok, mode=selected_mode, label=label, issues=issues, soft=soft, counts=counts)


def pinned_row_ids(markdown: str, rows: Sequence[Row]) -> list[str]:
    """Các `rowId` (khuôn `r12`) hồ sơ nhắc tới mà sổ không có — dấu vết trỏ sai."""
    text = str(markdown or '')
    known = {row.row_id for row in rows}
    out: list[str] = []
    for match in re.finditer(r'\b(r\d{1,4})\b', text):
        if match.group(1) not in known and match.group(1) not in out:
            out.append(match.group(1))
    return out


def owner_view_findings(text: str) -> tuple[list[str], list[str]]:
    """`(nhãn thiếu, nhãn chưa kèm nguồn)` của mục soi ý kiến chủ nhà (#6025).

    Một nhãn phải (a) xuất hiện trong chữ và (b) trên **cùng dòng** có nguồn: URL hoặc mã dòng sổ
    (`r12`). Hai điều kiện đó là thứ máy kiểm được; phần nội dung do người viết.
    """
    lines = [line.strip() for line in str(text or '').splitlines()]
    missing: list[str] = []
    unsourced: list[str] = []
    for label, english in OWNER_VIEW_LABELS:
        wanted = (fold_text(label), fold_text(english))
        hits = [line for line in lines if any(item and item in fold_text(line) for item in wanted)]
        if not hits:
            missing.append(label)
            continue
        if not any(_URL_RE.search(line) or _ROW_ID_RE.search(line) for line in hits):
            unsourced.append(label)
    return missing, unsourced


def profile_label(profile: Any) -> str:
    """Nhãn hồ sơ người đọc được — `văn bản chính thống (y tế)`."""
    if profile is None:
        return ''
    key = str(getattr(profile, 'key', '') or '')
    try:
        from . import research_profiles

        label = research_profiles.label_of(key)
        if label:
            return label
    except Exception:  # pragma: no cover - phòng vệ, không bao giờ chặn cổng
        pass
    return str(getattr(profile, 'label', '') or key)


def ledger_payload(rows: Sequence[Row]) -> dict[str, Any]:
    """Gộp `payload` của mọi dòng sổ thành MỘT bản khai — chỗ hồ sơ khai số hiệu/giá/phiên bản.

    Hồ sơ có thể gom nhiều mảnh của cùng một tài liệu ở nhiều dòng (một dòng số hiệu, một dòng giá),
    nên luật trường hồ sơ chấm trên bản gộp chứ không trên từng dòng.
    """
    payload: dict[str, Any] = {}
    for row in rows:
        payload.update(dict(row.payload or {}))
    return payload


def _best_document_payload(profile: Any, rows: Sequence[Row]) -> dict[str, Any]:
    """Do not assemble a fictitious document from unrelated ledger rows."""
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.origin or row.url or row.row_id)
        groups.setdefault(key, {}).update(dict(row.payload or {}))
    if not groups:
        return {}
    return min(groups.values(), key=lambda payload: len(profile.missing(payload)))


def hard_missing(profile: Any, rows: Sequence[Row]) -> list[str]:
    """Nhãn trường `hard` còn thiếu (#5989) — thứ duy nhất được quyền từ chối một hồ sơ.

    Trường đã có luật riêng chấm theo dòng (`research-validity-missing` cho số hiệu/ngày hiệu lực/dấu
    hiệu lực) **không** bị kể lại lần hai: một lỗi, một dòng khắc phục.
    """
    if profile is None:
        return []
    covered = set(getattr(profile, 'validity_fields', ()) or ()) if getattr(profile, 'validity', False) else set()
    out: list[str] = []
    for field, level in profile.missing(_best_document_payload(profile, rows)):
        if level != 'hard' or field.key in covered:
            continue
        label = field.label or field.key
        if label not in out:
            out.append(label)
    return out


def soft_missing(profile: Any, rows: Sequence[Row]) -> list[str]:
    """Trường `soft` còn thiếu — **không** từ chối, chỉ hiện trong báo cáo."""
    if profile is None:
        return []
    payload = _best_document_payload(profile, rows)
    out: list[str] = []
    for field, level in profile.missing(payload):
        if level != 'soft':
            continue
        label = field.label or field.key
        if label not in out:
            out.append(label)
    return out


# --- Tầng con: chú thích tất định ------------------------------------------


def _call_names(calls: Iterable[Any]) -> list[str]:
    names: list[str] = []
    for call in calls or ():
        if isinstance(call, str):
            names.append(call)
            continue
        if isinstance(call, Mapping):
            names.append(str(call.get('name') or call.get('tool') or ''))
    return [name for name in names if name]


def annotate_child_answer(
    answer: str,
    *,
    rows: Sequence[Row] = (),
    calls: Iterable[Any] = (),
    child_id: str = '',
    profile: Any = None,
) -> dict[str, Any]:
    """Chú thích câu trả lời của con `research` — chỉ đọc, **không** viết lại câu trả lời."""
    text = str(answer or '')
    rows = list(rows or [])
    issues: list[Issue] = []

    for label in missing_sections(text, 1):
        issues.append(Issue('research-shape-missing', label))

    used_web = any(name in {'web_search', 'web_fetch', 'read_source', 'paper_citations'} for name in _call_names(calls))
    if used_web and not urls_in(text):
        issues.append(Issue('research-sources-missing', 'lượt con có gọi web mà câu trả lời không có URL'))
    if rows:
        known = {clean_url(row.url) for row in rows}
        for url in urls_in(text):
            if url not in known:
                issues.append(Issue('research-sources-unproven', url))
    elif child_id:
        issues.append(Issue('research-lineage-missing', child_id))

    if rows:
        issues.extend(issue for issue in assess_rows(rows, profile) if issue.code in {
            'research-excerpt-missing',
            'research-claim-single-source',
            'research-origin-undeclared',
            'research-tier-unknown',
        })

    payload = {
        'issues': [issue.code for issue in issues],
        'missing': issue_dicts(issues),
        'rows': len(rows),
        'mode': 'note',
        'counts': counts_for(rows),
    }
    payload['notice'] = notice_for(issues, len(rows))
    return payload


def notice_for(issues: Sequence[Issue], rows: int) -> str:
    """Một câu cho chủ nhà — nhãn **do máy viết**."""
    codes = sorted({issue.code for issue in issues})
    if not codes:
        return f'{NOTICE_CODE}: {rows} dòng sổ, không thấy thiếu sót'
    return f'{NOTICE_CODE}: {rows} dòng sổ · ' + ', '.join(codes)


def rejection_message(verdict: Verdict) -> str:
    """Chuỗi cho `RESEARCH_QUALITY_REJECTED` — mã + từng dòng thiếu + câu khắc phục."""
    lines = [f'{RESEARCH_QUALITY_PREFIX}: {verdict.counts.get("rows", 0)} dòng sổ, {len(verdict.issues)} mục cần sửa']
    for item in verdict.missing:
        lines.append(f'- {item["code"]} {item["detail"]}'.rstrip())
        if item['remedy']:
            lines.append(f'  khắc phục: {item["remedy"]}')
    return '\n'.join(lines)
