"""Pure content gate for `write_plan`: a plan must carry evidence, limits and sources.

Why this module exists
----------------------
The owner asked for "a plan for an agent that looks up patient records" and got a document with
no verification mechanism at all: no command, no expected result, no risks. Nothing in the product
objected, because the only checks were the slug, the 1 MiB size and the target path
(``agent_core/runtime.py`` write_plan) and the sandbox writer (``sandbox/worker.py``) just picks the
next free ``.plans/vN-<slug>.md``.

Contract
--------
``plan_quality_issues(markdown)`` returns the ids of the missing requirements (``[]`` = accepted).
``check_plan_quality(markdown)`` returns ``None`` or raises
``ValueError('PLAN_QUALITY_REJECTED: …')`` — a single-line, actionable message that names exactly
what is missing. Both are pure: no I/O, no session state, no model call.

A plan that satisfies the gate is written exactly as before; the gate only refuses *before* the
sandbox writer runs, so a rejected plan leaves no file behind.
"""

from __future__ import annotations

import re

__all__ = ['REQUIRED_SECTIONS', 'PLAN_QUALITY_PREFIX', 'plan_quality_issues', 'plan_quality_message',
           'check_plan_quality', 'sections', 'has_concrete_check', 'has_expected_result',
           'claims_external_facts', 'source_lines', 'cited_hosts', 'sources_issues', 'sources_message',
           'ASSUMPTION_HEADING_KEYS', 'assumption_items']

#: Tiêu đề của một mục GIẢ ĐỊNH / CÂU HỎI MỞ (F2, đợt soát 2026-09-27). Độc lập với
#: `REQUIRED_SECTIONS['risks']`: mục rủi ro nói về thất bại, còn mục này nói về điều CHƯA BIẾT —
#: thứ duy nhất mà một câu hỏi cho chủ nhà gỡ được.
ASSUMPTION_HEADING_KEYS = ('assumption', 'unknown', 'open question', 'unconfirmed', 'to confirm',
                            'giả định', 'chưa xác nhận', 'cần xác nhận', 'câu hỏi mở')

#: Trần số mục và số ký tự mỗi mục: notice chỉ cần đủ để chủ nhà nhận ra GIẢ ĐỊNH NÀO chưa xác nhận.
ASSUMPTION_ITEMS_MAX = 5
ASSUMPTION_ITEM_CHARS = 160

PLAN_QUALITY_PREFIX = 'PLAN_QUALITY_REJECTED'

# The plan document must contain each of these sections. `heading_keys` are matched against a
# normalized heading, `missing` lists the issue ids the section can raise, and `trigger` names the
# condition that makes the section mandatory (`None` = always). Vietnamese keys are included on
# purpose: this product's users write Vietnamese plans and the repository's own plans are Vietnamese,
# and the gate is about structure, not language.
REQUIRED_SECTIONS = (
    {
        'id': 'verification',
        'label': 'Verification / Acceptance criteria',
        'heading_keys': ('verification', 'acceptance criteri', 'acceptance test', 'acceptance check',
                         'how to verify', 'verify', 'validation', 'test plan', 'checklist', 'checks',
                         'nghiệm thu', 'kiểm thử', 'xác minh', 'kiểm chứng', 'cách kiểm'),
        'missing': ('verification-section', 'verification-command', 'verification-expected'),
        'trigger': None,
        'requirement': 'names at least one exact command or check plus its expected result',
    },
    {
        'id': 'risks',
        'label': 'Risks / Limitations',
        'heading_keys': ('risk', 'limitation', 'caveat', 'open question', 'unknown', 'assumption',
                         'trade-off', 'tradeoff', 'rủi ro', 'giới hạn', 'hạn chế', 'câu hỏi mở'),
        'missing': ('risks-section',),
        'trigger': None,
        'requirement': 'states the risks, failure modes or limitations (or "none known" and why)',
    },
    {
        'id': 'sources',
        'label': 'Sources / Citations',
        'heading_keys': ('source', 'citation', 'reference', 'bibliography', 'nguồn', 'trích dẫn',
                         'tham chiếu'),
        'missing': ('sources-section',),
        'trigger': 'external_facts',
        'requirement': 'lists where each external fact came from (URL, doc path or quoted source)',
    },
)

# One actionable sentence per issue id. Joined with '; ' into the single-line rejection message.
REMEDIES = {
    'verification-section': ('add a section titled "Verification / Acceptance criteria" (or '
                             '"Acceptance criteria" / "How to verify" / "Nghiệm thu")'),
    'verification-command': ('name at least one exact command or check, e.g. '
                             '"`.venv/bin/python -m pytest backend/tests -q`"'),
    'verification-expected': ('state the expected result of that check, e.g. "expect 3 known '
                              'environment failures and everything else passing"'),
    'risks-section': 'add a "Risks / Limitations" section (write "none known" plus why, if truly none)',
    'sources-section': ('this plan relies on external facts: add a "Sources / Citations" section with '
                        'the URL, doc path or quoted source for each one, and mark anything you could '
                        'not verify as UNVERIFIED'),
    # Vòng 25 (D-34) — lớp BẰNG CHỨNG của mục `sources`: nguồn phải đến từ một lời gọi thật của
    # phiên này, không phải từ ký ức của model.
    'sources-unproven': ("delegate role='research' (or 'explore' for repo facts) in this turn and cite "
                         "what it returned"),
    'sources-vague': ('every line of Sources / Citations must name a URL, a `path:line` or an exact '
                      'command'),
    'sources-unbacked': ('this host appears in no tool result of this session — cite a host a real '
                         'tool call returned, or mark it UNVERIFIED'),
}

# A line that opens a section: ATX heading (`## Verification`), a bold label (`**Risks**`) or a short
# plain label (`Verification:`). Nothing else is treated as a heading, so prose never fakes a section.
_ATX_RE = re.compile(r'^\s{0,3}#{1,6}\s+(?P<text>.+?)\s*#*\s*$')
_BOLD_RE = re.compile(r'^\s{0,3}(?:\*\*|__)(?P<text>[^*_\n]+?)(?:\*\*|__)\s*:?\s*$')
_LABEL_RE = re.compile(r'^\s{0,3}(?P<text>[A-Z][^.!?:\n]{1,60}):\s*$')
_FENCE_RE = re.compile(r'^\s*(?:```|~~~)')

# A "concrete command or check" in the verification section: an inline code span, a fenced block, a
# real tool followed by an argument, an explicit `command:`/`verify:` marker, an HTTP call, or an
# assertion naming a concrete artifact/status ("returns 201", "exit code 0", "the file exists").
_INLINE_CODE_RE = re.compile(r'`[^`\n]*[^\s`][^`\n]*`')
_TOOL_NAMES = (r'python3?|pytest|py\.test|npm|npx|pnpm|yarn|node|deno|bash|sh|zsh|curl|wget|docker|'
               r'podman|git|make|cmake|cargo|go|rustc|java|mvn|gradle|dotnet|sqlite3|psql|mysql|'
               r'redis-cli|jq|rg|grep|find|ls|cat|sha256sum|md5sum|tsc|vitest|eslint|ruff|flake8|'
               r'mypy|alembic|systemctl|journalctl')
_COMMAND_TOKEN_RE = re.compile(
    rf'(?:^|[\s(`$>])(?:sudo\s+)?(?:[\w.~-]+/)*(?:{_TOOL_NAMES})\s+[-\w./~"\'`]', re.IGNORECASE | re.MULTILINE)
_MARKER_LINE_RE = re.compile(r'^\s*(?:[-*]\s*)?(?:\*\*)?(?:command|commands|check|checks|test|tests|run|'
                             r'verify|verification|expected|evidence)(?:\*\*)?\s*[:=]', re.IGNORECASE | re.MULTILINE)
_HTTP_CALL_RE = re.compile(r'\b(?:GET|POST|PUT|PATCH|DELETE|HEAD)\s+[/\w]', re.IGNORECASE)
_CONCRETE_ASSERTION_RE = re.compile(
    r'\b(?:returns?|responds?)\s+(?:with\s+)?(?:\d{3}|[2-5]xx|OK\b|HTTP)'
    r'|\bexit(?:s)?\s+(?:code|status)?\s*\d'
    r'|\b\d+\s+(?:tests?\s+)?(?:passed|failed|failures?|skipped)\b'
    r'|\b\S+\.(?:md|py|ts|tsx|js|json|sql|sh|yaml|yml|txt|log)\b'
    r'|\bno\s+(?:errors?|diff|diffs|changes|regressions?)\b'
    r'|\b(?:exists?|present|absent|unchanged)\b'
    r'|\bcontains?\s+[\'"`]', re.IGNORECASE)

# An "expected result" is any statement of what the check must produce. Deliberately flat: the point
# is that SOME expectation is written down, not the phrasing. Vietnamese markers are included because
# Vietnamese is a first-class language of this product.
_EXPECTED_MARKERS = ('expect', 'expected', 'should', 'must ', 'exit code', 'exit status', 'passes',
                     'passing', 'fails', 'failure', 'output', 'returns', 'return ', 'verified',
                     'confirms', 'succeeds', 'success', 'no error', 'equals',
                     'mong đợi', 'kỳ vọng', 'phải ', 'kết quả')
_EXPECTED_RE = re.compile(r'(?:=>|->|==|\bexit\s+code\s*\d|\bstatus\s+\d{3}\b|\b\d{3}\s+(?:OK|created|no content)\b)',
                          re.IGNORECASE)

# Phrases that mean the plan leans on knowledge from OUTSIDE this repository, which therefore needs a
# citable source. In-repo references (`docs/plan/x.md`, `backend/src/...`) deliberately do NOT match.
_EXTERNAL_FACT_RES = (
    re.compile(r'https?://', re.IGNORECASE),
    re.compile(r'\bwww\.', re.IGNORECASE),
    re.compile(r'\b(?:search|searched|looked up|consulted)\s+(?:the\s+)?web\b', re.IGNORECASE),
    re.compile(r'\bweb\s+search\b', re.IGNORECASE),
    re.compile(r'\bofficial\s+(?:docs|documentation)\b', re.IGNORECASE),
    re.compile(r'\bupstream\s+(?:docs|documentation)\b', re.IGNORECASE),
    re.compile(r'\bvendor\s+(?:docs|documentation)\b', re.IGNORECASE),
    re.compile(r'\brelease\s+notes\b', re.IGNORECASE),
    re.compile(r'\bRFC\s?\d+\b'),
    re.compile(r'\bCVE-\d{4}-\d+\b', re.IGNORECASE),
    re.compile(r'\bwikipedia\b', re.IGNORECASE),
    re.compile(r'\bper\s+the\s+documentation\b', re.IGNORECASE),
    re.compile(r'\baccording\s+to\s+the\s+(?:docs|documentation|specification|spec)\b', re.IGNORECASE),
    re.compile(r'\bexternal\s+(?:sources|references|citations)\b', re.IGNORECASE),
    re.compile(r'\b(?:HL7|FHIR|HIPAA|GDPR|ISO\s?\d+)\b'),
)


def _normalized_heading(text: str) -> str:
    """`## 3. Acceptance Criteria ###` -> `acceptance criteria`, for key matching."""
    stripped = re.sub(r'^[\s#*>_`]*(?:\d+[.)]\s*)?', '', str(text or '').strip())
    stripped = re.sub(r'[*_`:#]+$', '', stripped)
    return ' '.join(stripped.split()).lower()


def _section_heading(line: str):
    """The heading text of a section-opening line, else None."""
    if _FENCE_RE.match(line):
        return None
    for pattern in (_ATX_RE, _BOLD_RE, _LABEL_RE):
        match = pattern.match(line)
        if match:
            heading = _normalized_heading(match.group('text'))
            return heading or None
    return None


def sections(markdown: str):
    """[(heading, body)] for every section-opening line, in document order."""
    sections = []
    body = None
    for line in str(markdown or '').splitlines():
        heading = _section_heading(line)
        if heading:
            body = []
            sections.append((heading, body))
        elif body is not None:
            body.append(line)
    return [(heading, '\n'.join(lines).strip()) for heading, lines in sections]


def _find(sections, keys):
    """The first section whose heading contains one of `keys`, as `(heading, body)`, else None."""
    for heading, body in sections:
        if any(key in heading for key in keys):
            return heading, body
    return None


def _find_with_body(sections, keys):
    """Như `_find`, nhưng bỏ qua một tiêu đề TRỐNG đứng trước.

    Đo vòng 25: `_find` khớp tiêu đề đầu tiên, nên một H1 như "Plan backed by one source" che mất mục
    `## Sources / Citations` thật ở dưới — cổng cấu trúc nói "thiếu mục nguồn" trong khi mục đó có,
    và model sửa mãi không qua được. Ở đây tiêu đề khớp đầu tiên vẫn là phương án dự phòng, chỉ khi
    không có tiêu đề khớp nào có thân bài.
    """
    first = None
    for heading, body in sections:
        if any(key in heading for key in keys):
            if first is None:
                first = (heading, body)
            if str(body or '').strip():
                return heading, body
    return first


def has_concrete_check(body: str) -> bool:
    """True when the section names a real command or check rather than a description of one."""
    return bool(_INLINE_CODE_RE.search(body) or _COMMAND_TOKEN_RE.search(body)
                or _MARKER_LINE_RE.search(body) or _HTTP_CALL_RE.search(body)
                or _CONCRETE_ASSERTION_RE.search(body)
                or any(_FENCE_RE.match(line) for line in body.splitlines()))


def has_expected_result(body: str) -> bool:
    """True when the section states what the check must produce."""
    lowered = body.lower()
    return any(marker in lowered for marker in _EXPECTED_MARKERS) or bool(_EXPECTED_RE.search(body))


def assumption_items(markdown: str):
    """Các dòng của mục GIẢ ĐỊNH / CÂU HỎI MỞ trong bản kế hoạch (rỗng = không có mục ấy).

    Đọc từ chính văn bản vừa ghi, không mở lại tệp trong box: `write_plan` đã cầm nó trên tay, và một
    lần `docker exec` chỉ để đếm dòng là thứ không thể trả giá. Một dòng dài bị cắt ở
    `ASSUMPTION_ITEM_CHARS`; số dòng bị cắt ở `ASSUMPTION_ITEMS_MAX`, và số dòng BỊ CẮT được nói ra
    trong chính danh sách (`... và N mục nữa`) để notice không nói thiếu.
    """
    found = _find_with_body(sections(markdown), ASSUMPTION_HEADING_KEYS)
    if found is None:
        return []
    items = []
    for line in str(found[1] or '').splitlines():
        text = line.strip().lstrip('-*+ ').strip()
        text = re.sub(r'^\d+[.)]\s*', '', text).strip()
        if not text or text.startswith('#'):
            continue
        items.append(text[:ASSUMPTION_ITEM_CHARS])
    if len(items) > ASSUMPTION_ITEMS_MAX:
        extra = len(items) - ASSUMPTION_ITEMS_MAX
        items = items[:ASSUMPTION_ITEMS_MAX] + [f'... và {extra} mục nữa']
    return items


def claims_external_facts(markdown: str) -> bool:
    return any(pattern.search(markdown or '') for pattern in _EXTERNAL_FACT_RES)


# Bốn hàm trên được công khai ở vòng 20 (§5 của plan): `plan_eval.py` chấm P3 (structure), P4
# (executability) và P6 (evidence) bằng đúng chúng, để luật cấu trúc chỉ có MỘT bản cài đặt —
# bản trong `check_plan_quality()` mà mọi plan đã phải đi qua từ trước. Tên cũ có gạch dưới vẫn
# là bí danh: nơi đang gọi chúng không phải đổi, và một bản sao thứ hai không thể mọc ra.
_sections = sections
_has_concrete_check = has_concrete_check
_has_expected_result = has_expected_result
_claims_external_facts = claims_external_facts


def plan_quality_issues(markdown: str) -> list:
    """Ids of the requirements `markdown` fails, in the order of REQUIRED_SECTIONS; `[]` = accepted."""
    text = str(markdown or '')
    found_sections = sections(text)
    issues = []
    for spec in REQUIRED_SECTIONS:
        if spec['trigger'] == 'external_facts' and not claims_external_facts(text):
            continue
        if spec['id'] == 'verification':
            # Product and research plans often have both an acceptance-target
            # section and a later verification procedure. The first heading
            # alone must not hide the concrete checks in the second.
            bodies = [body for heading, body in found_sections
                      if body.strip() and any(key in heading for key in spec['heading_keys'])]
            if not bodies:
                issues.append(spec['missing'][0])
            else:
                if not any(has_concrete_check(body) for body in bodies):
                    issues.append('verification-command')
                if not any(has_expected_result(body) for body in bodies):
                    issues.append('verification-expected')
            continue
        found = _find_with_body(found_sections, spec['heading_keys'])
        if not found:
            issues.append(spec['missing'][0])
            continue
        body = found[1]
        if not body.strip():
            issues.append(spec['missing'][0])
            continue
    return issues


def plan_quality_message(issues) -> str:
    """One line naming exactly what is missing and what to write instead."""
    listed = '; '.join(f'({issue}) {REMEDIES[issue]}' for issue in issues)
    return (f'{PLAN_QUALITY_PREFIX}: the plan was not written: missing {listed}. '
            'Rewrite the markdown with those sections and call write_plan again; nothing was written.')


def check_plan_quality(markdown: str) -> None:
    """Raise `ValueError('PLAN_QUALITY_REJECTED: …')` when the plan is structurally empty."""
    issues = plan_quality_issues(markdown)
    if issues:
        raise ValueError(plan_quality_message(issues))


# --------------------------------------------------------------------------------------------
# Vòng 25 (D-34) — cổng NGUỒN: lớp bằng chứng của mục `Sources / Citations`
# --------------------------------------------------------------------------------------------
# Ba mã lỗi, ba cách hụt khác nhau của cùng một câu hỏi "nguồn này ở đâu ra":
#   * `sources-unproven` — chưa có con research/explore nào chạy trong lượt: chưa ai đi tra;
#   * `sources-vague`    — có dòng nguồn nhưng không có URL/`path:line`/lệnh cụ thể;
#   * `sources-unbacked` — host/ký hiệu được viện dẫn nhưng không xuất hiện trong kết quả công cụ
#                          nào của phiên: nguồn không kiểm được bằng chính lượt này.
# Hàm ở đây THUẦN: không đọc đĩa, không gọi mạng, không biết gì về runtime. Bằng chứng do runtime
# thu (`plan_sources_evidence`) rồi truyền vào — nhờ vậy luật đọc được trong test mà không cần box.
_HOST_RE = re.compile(r'https?://([^\s/)\'"<>\]]+)', re.IGNORECASE)
_PATHY_RE = re.compile(r'(?:[\w.~-]+/)+[\w.~-]+|\b[\w.~-]+\.(?:py|ts|tsx|js|json|md|sh|sql|yaml|yml|toml|cfg|ini)\b')
_COMMANDY_RE = re.compile(r'`[^`\n]+`|\b(?:npm|npx|pnpm|yarn|python3?|pytest|bash|sh|curl|docker|git|'
                          r'make|rg|grep|sqlite3|psql|jq|node)\s+[-\w./~$]')
_UNVERIFIED_RE = re.compile(r'\bunverified\b', re.IGNORECASE)
# Ranh giới một dòng nguồn: dòng có gạch đầu dòng, hoặc dòng có địa chỉ/đường dẫn/lệnh.
_SOURCE_MARKER_RE = re.compile(r'https?://|\bwww\.', re.IGNORECASE)


def source_lines(markdown: str) -> list:
    """Các dòng của mục `Sources / Citations` (bỏ dòng trống) — phần văn bản phải tự chứng minh."""
    found = _find_with_body(sections(str(markdown or '')),
                            ('source', 'citation', 'reference', 'bibliography',
                             'nguồn', 'trích dẫn', 'tham chiếu'))
    if not found:
        return []
    return [line.strip() for line in found[1].splitlines() if line.strip()]


def strip_www(host: str) -> str:
    """`www.example.com` -> `example.com`; viết thường, bỏ dấu chấm cuối. Giữ nguyên phần còn lại.

    `str.lstrip('www.')` là một BẪY: nó cắt theo TẬP ký tự chứ không theo tiền tố, nên `web.dev`
    thành `eb.dev` và `w3.org` thành `3.org`. Hậu kiểm vòng 25 đo được đúng lỗi đó ở `sources_issues`
    (`known_hosts`): một kế hoạch viện dẫn `web.dev` — đúng host mà lời gọi công cụ vừa trả về — vẫn
    bị `sources-unbacked` chặn, tức cổng nguồn từ chối một kế hoạch CÓ bằng chứng thật. Ba chỗ chuẩn
    hoá host (`cited_hosts`, `sources_issues`, `runtime.plan_sources_evidence`) nay dùng chung hàm này
    để chúng không trôi khỏi nhau lần nữa.
    """
    text = str(host or '').strip().lower().rstrip('.')
    return text[4:] if text.startswith('www.') else text


def normalize_path(path: str) -> str:
    """Đường dẫn tương đối hoá: bỏ tiền tố `./` (lặp được) và các dấu `/` ở đầu.

    Cùng một họ lỗi với `strip_www`: `lstrip('./')` cắt theo tập ký tự, nên `.github/workflows/ci.yml`
    mất luôn dấu chấm đầu tiên. Hai chỗ dùng nó (`sources_issues.known_paths`, `plan_sources_evidence`)
    nay đi qua đây.
    """
    text = str(path or '').strip()
    while text.startswith('./'):
        text = text[2:]
    return text.lstrip('/')


def cited_hosts(markdown: str) -> list:
    """Host được viện dẫn trong cả tài liệu (đã bỏ `www.`, viết thường), theo thứ tự xuất hiện."""
    hosts = []
    for match in _HOST_RE.finditer(str(markdown or '')):
        host = strip_www(match.group(1))
        if host and host not in hosts:
            hosts.append(host)
    return hosts


def sources_issues(markdown: str, *, children=(), hosts=(), paths=()) -> list:
    """Mã lỗi của lớp bằng chứng nguồn; `[]` = đạt.

    Chỉ chạy khi `claims_external_facts(markdown)` đúng — CÙNG trigger với mục `sources` của
    `REQUIRED_SECTIONS`, nên không mở rộng ngữ nghĩa của luật cũ, chỉ thêm lớp bằng chứng.

    `children` là sổ con của phiên (`{'role','status','answer_chars'}`), `hosts` là host mà kết quả
    công cụ THẬT của phiên đã trả về, `paths` là đường dẫn tệp tương tự. Ba nguồn này do runtime
    thu; hàm này không tự đi tìm.
    """
    text = str(markdown or '')
    if not claims_external_facts(text):
        return []
    lines = source_lines(text)
    if not lines:
        return ['sources-section']
    issues = []
    if not any(str(row.get('role') or '') in ('research', 'explore') for row in (children or ())):
        issues.append('sources-unproven')
    concrete = [line for line in lines
                if _SOURCE_MARKER_RE.search(line) or _COMMANDY_RE.search(line)
                or (_PATHY_RE.search(line) and not _UNVERIFIED_RE.search(line))]
    if not concrete:
        issues.append('sources-vague')
    known_hosts = {strip_www(host) for host in (hosts or ()) if str(host).strip()}
    known_paths = {normalize_path(path) for path in (paths or ()) if str(path).strip()}
    for host in cited_hosts(text):
        if host in known_hosts:
            continue
        if any(host in path or path in host for path in known_paths):
            continue
        issues.append('sources-unbacked')
        break
    return issues


def sources_message(issues) -> str:
    """Một dòng `PLAN_QUALITY_REJECTED` + câu khắc phục cho từng mã lỗi của cổng nguồn."""
    listed = '; '.join(f'({issue}) {REMEDIES[issue]}' for issue in issues)
    return (f'{PLAN_QUALITY_PREFIX}: the plan leans on facts from outside this workspace and the '
            f'sources gate refused it: {listed}. Rewrite the Sources / Citations section from what a '
            f'real tool call returned and call write_plan again; nothing was written.')
