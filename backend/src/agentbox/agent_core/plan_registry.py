"""Sổ đăng ký plan phía harness: đọc chỉ mục box, quyết định identity và số version.

Vì sao có file này
------------------
Ca sống của vòng 20: hai chủ đề mới toanh được ghi cách nhau 6 phút lại thành `v5` và `v6`
(không hề có `v1`), và cùng một chủ đề "Clinical Patient Record Lookup Research" nằm ở hai nhóm
vì mỗi bản do model tự đặt slug. Nguyên nhân là **không ai quyết số version và nhóm**: sandbox tự
đếm mọi file trong `.plans/`, còn nhóm thì suy từ slug trong tên file.

File này là chỗ harness quyết hai việc đó, bằng dữ liệu:

* `read_plan_index(executor)` đọc `GET /__box/plans/index` (cùng payload với `GET /__box/plans`,
  cần `X-BoxFox-Api-Key`). Chỉ mục hỏng → trả `None` và ghi nhật ký `PLAN_INDEX_UNAVAILABLE`:
  nhánh suy giảm quay về đúng hành vi cũ (sandbox tự chọn số, không header), **không bịa dữ liệu**.
* `resolve_identity(...)` chọn nhóm theo luật §3.2: khai báo tường minh thắng; không khai báo thì
  so độ giống Jaccard giữa slug đề nghị và mọi identity cùng thư mục — `j ≥ 0.75` gộp,
  `0.5 ≤ j < 0.75` mơ hồ (từ chối, chỉ đúng câu cần gọi), `j < 0.5` nhóm mới.
* Dải mơ hồ (`0.5 ≤ j < 0.75`) từ chối lần **đầu** — gộp nhầm là mất dữ liệu không hoàn tác được —
  nhưng lời từ chối để lại một **vé** (`ambiguity_ticket`): gửi lại **nguyên văn** thêm đúng một
  lần nữa thì bản đó được nhận là nhóm mới. `ticket_from_rows(...)` đọc vé từ hàng `F:` của phiên,
  `ambiguity_ticket_usable(...)` đòi "chưa có nhóm nào cho slug này" — nhờ đó vé tiêu đúng một lần.
* `next_version_and_parent(...)` theo luật §3.4/§4.3: bản kế tiếp của một nhóm luôn là `v(N+1)`
  với `Parent: vN`; model khai `Parent: none` khi N ≥ 1 thì bị từ chối.
* `group_state(...)` là máy trạng thái §4.2, đọc **sổ duyệt SQLite** (nguồn chân lý) chứ không đọc
  `.reviews/*.json` trong workspace — file đó agent ghi được, nó chỉ để hiển thị.

Ai gọi
------
`runtime.write_plan` (workstream A nối vào): đọc chỉ mục một lần cho mỗi lần ghi, gọi
`plan_registration(...)`, rồi dùng `RegistrationPlan` để dựng header (`plan_header.build_plan_header`)
và gọi sandbox với `version`/`directory` tường minh. Route `GET /api/agent/plans/status` dùng
`group_state` + `pending_submissions` để trả trạng thái duyệt cho tab Plan.

Quan hệ module: file này giữ luôn từ vựng mã lỗi của cổng §5 (`PLAN_EVAL_PREFIX`, `REMEDIES`,
`rejection_message`) vì đây là chốt từ chối **đầu tiên** trong đường ghi; `plan_eval.py` nhập lại
và thêm các mã của riêng nó. Chiều phụ thuộc là một chiều: `plan_eval` → `plan_registry`.

Tất cả hàm ở đây đều thuần (trừ `read_plan_index`) và **không raise ngoài `PlanRegistrationError`**.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from ..observability.system_log import system_log
from .plan_header import IDENTITY_PATTERN

__all__ = [
    'INDEX_PATH', 'INDEX_UNAVAILABLE_CODE', 'IDENTITY_FORCED_NEW_CODE', 'PLAN_EVAL_PREFIX',
    'MERGE_THRESHOLD', 'AMBIGUOUS_THRESHOLD', 'MIN_TOKEN_LENGTH', 'UNSET',
    'REMEDIES', 'rejection_message', 'PlanRegistrationError',
    'slug_tokens', 'jaccard', 'split_identity', 'parse_relates_to',
    'PlanIndexEntry', 'PlanGroup', 'PlanIndex', 'parse_plan_index', 'read_plan_index',
    'IdentityDecision', 'resolve_identity', 'VersionPlan', 'next_version_and_parent',
    'AMBIGUITY_TICKET_KEY', 'AMBIGUITY_MATCHED_BY', 'ambiguity_marker', 'build_ambiguity_ticket',
    'ticket_from_rows', 'ambiguity_ticket_usable',
    'GroupState', 'group_state', 'review_stale', 'pending_submissions',
    'RegistrationPlan', 'plan_registration',
    'PLAN_ROOM', 'plan_room_directory', 'plan_outside_room',
]

INDEX_PATH = '/__box/plans/index'
INDEX_UNAVAILABLE_CODE = 'PLAN_INDEX_UNAVAILABLE'
IDENTITY_FORCED_NEW_CODE = 'PLAN_IDENTITY_FORCED_NEW'

# Ranh giới §3.2. Không có bảng stop-word: `plan`, `research`… vẫn là token, vì một bảng dừng làm
# luật khó đoán. Hai con số này được ghim bằng test ở cả hai phía ranh giới (0.49/0.5/0.74/0.75).
MERGE_THRESHOLD = 0.75
AMBIGUOUS_THRESHOLD = 0.5
MIN_TOKEN_LENGTH = 2

PLAN_EVAL_PREFIX = 'PLAN_EVAL_REJECTED'

# Grammar identity, neo vào cùng hằng số với khối header (`plan_header.IDENTITY_PATTERN`) nên không
# có bản sao thứ ba của `_SLUG`.
_IDENTITY_TEXT_RE = re.compile(rf'^{IDENTITY_PATTERN}$')
# Bản sao của hai mảnh grammar trong `plan_header` (`_SLUG`/`_VERSION`), để khuôn tên tệp kế hoạch
# ở đây không lệch với bộ đọc (`deploy/docker/plan_files.py`) hay khối header.
_SLUG_TEXT = r'[a-z0-9]+(?:-[a-z0-9]+)*'
_VERSION_TEXT = r'[1-9][0-9]{0,9}'

# Phòng kế hoạch: bộ đọc (`deploy/docker/plan_files.py`) chỉ quét cây này, nên MỌI lần ghi phải nằm
# trong đây — một tệp `vN-<slug>.md` ở ngoài là một kế hoạch vô hình với tab Plan. Chủ nhà đo sống
# 2026-10-04: một lượt ghi ra ngoài phòng khiến tab Plan không thấy bản mới và sinh thêm thư mục
# `plans` khác. Luật chốt: ghi theo chỗ được chỉ, nhưng **kẹp** vào phòng.
PLAN_ROOM = '.plans'
_ROOM_SEGMENTS = ('plans', '.plans')


def plan_room_directory(value) -> str:
    """Chuẩn hoá "chỗ ghi" của một kế hoạch về thư mục con BÊN TRONG phòng, `''` = gốc phòng.

    Tiền tố trỏ vào chính phòng (`plans/`, `.plans/`, kể cả `.plans/plans/`) bị bỏ, `.`/`..`/dấu `/`
    thừa bị bỏ, đoạn còn lại phải đúng quy tắc slug của tên tệp. `'../designs'` → `'designs'`;
    `'.plans/tao-ui'` → `'tao-ui'`; `'tao-ui'` → `'tao-ui'`.
    """
    text = str(value or '').strip().replace('\\', '/')
    segments: list[str] = []
    for raw in text.split('/'):
        segment = raw.strip()
        if segment in ('', '.'):
            continue
        if segment == '..':
            if segments:
                segments.pop()
            continue
        segments.append(segment)
    while segments and segments[0] in _ROOM_SEGMENTS:
        segments.pop(0)
    for segment in segments:
        if not _IDENTITY_TEXT_RE.fullmatch(segment):
            raise PlanRegistrationError('directory-invalid', directory=text)
    return '/'.join(segments)


_PLAN_FILENAME_RE = re.compile(rf'^v{_VERSION_TEXT}-{_SLUG_TEXT}\.md$')


def plan_outside_room(path) -> str:
    """`'PLAN_OUTSIDE_ROOM'` khi `path` là một TỆP KẾ HOẠCH nằm ngoài phòng, ngược lại `''`.

    Nhận diện bằng chính tên tệp của bộ đọc (`v<version>-<slug>.md`). Mọi đường dẫn KHÔNG bắt đầu
    bằng `.plans/` mà tên tệp khớp khuôn đó đều bị chặn: kế hoạch ngoài phòng là kế hoạch vô hình
    với tab Plan, và là chỗ sinh ra thư mục `plans` thứ hai (đo sống 2026-10-04).
    """
    segments = [segment for segment in str(path or '').replace('\\', '/').split('/')
                if segment not in ('', '.')]
    if not segments or segments[0] == PLAN_ROOM:
        return ''
    return 'PLAN_OUTSIDE_ROOM' if _PLAN_FILENAME_RE.fullmatch(segments[-1]) else ''


class _Unset:
    """Vắng mặt khác với `None`: model **không viết** header ≠ model khai `Parent: none`."""

    def __repr__(self) -> str:  # pragma: no cover - chỉ để đọc log/test cho dễ
        return 'UNSET'

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()

# Mỗi mã lỗi một câu nói đúng việc phải làm, theo mẫu `REMEDIES` của `plan_quality.py`.
# `{...}` được điền bằng `rejection_message`.
REMEDIES = {
    'identity-ambiguous': (
        'slug bạn đề nghị giống {score:.0%} cả nhóm «{identity}» lẫn nhóm «{other}», nên harness '
        'không tự đoán: gọi lại write_plan với identity: "{identity}" nếu muốn nối vào nhóm cũ, '
        'hoặc relatesTo: "none" nếu đây là chủ đề mới — hoặc gửi lại NGUYÊN VĂN bản này để được '
        'nhận là kế hoạch mới (vé mơ hồ dùng được đúng một lần).'
    ),
    'revision-not-traceable': (
        'nhóm «{identity}» đang ở v{version} nên bản sửa phải khai Parent: v{version}; bạn khai '
        'Parent: none. Sửa dòng Parent trong khối boxfox-plan rồi gọi lại write_plan.'
    ),
    'identity-pending-review': (
        'nhóm «{identity}» đang chờ xử lý yêu cầu sửa («{note}») nên cùng chủ đề này không được '
        'mở identity khác: hãy sửa tiếp bản đang chờ (relatesTo: "{identity}"), hoặc chọn một chủ '
        'đề thật sự khác.'
    ),
    # `{declared}` là một MỆNH ĐỀ ("khai v3", "không đúng cú pháp (đọc được: …)"), không phải
    # con số trần: bản cũ ghép thêm `v` ở đây nên câu từ chối đọc ra "khai vv2", và một khối
    # sai cú pháp bị kể thành chuyện lệch version dù version có khớp (đo sống 2026-09-22).
    'header-mismatch': (
        'khối boxfox-plan bạn viết {declared}; harness sẽ ghi v{version}{parent_hint} — '
        'viết lại khối cho khớp, hoặc bỏ hẳn khối để harness tự chèn.'
    ),
    'identity-invalid': (
        'identity «{identity}» không hợp lệ: chỉ chữ thường và số, các từ cách nhau đúng một dấu '
        'gạch, có thể kèm thư mục (ví dụ "designs/login-page"). Sửa tham số rồi gọi lại write_plan.'
    ),
    'directory-invalid': (
        'thư mục «{directory}» không dùng được: mỗi đoạn chỉ chữ thường và số, cách nhau đúng một '
        'dấu gạch (ví dụ "tao-ui" hay "work/run-1"). Bỏ dấu chấm, dấu `/` thừa và `..` rồi gọi lại '
        'write_plan — kế hoạch luôn nằm trong `.plans`.'
    ),
}

_NOTE_QUOTE_CHARS = 120


def rejection_message(code, **fields) -> str:
    """Một dòng `PLAN_EVAL_REJECTED: (mã-lỗi) <câu khắc phục>` — không xuống dòng, không bịa."""
    remedy = REMEDIES.get(code, 'không ghi plan: dữ liệu không thoả luật của harness.')
    try:
        filled = remedy.format(**fields)
    except (KeyError, IndexError, ValueError, TypeError):
        filled = remedy
    note = fields.get('note')
    if code == 'identity-pending-review' and note:
        filled = filled.replace('«{note}»', '«' + str(note)[:_NOTE_QUOTE_CHARS] + '»')
    return f'{PLAN_EVAL_PREFIX}: ({code}) {filled}'


class PlanRegistrationError(ValueError):
    """Từ chối trước khi ghi: mã lỗi máy đọc được + câu khắc phục + dữ liệu để ghi log."""

    def __init__(self, code, message=None, **fields):
        self.code = code
        self.fields = fields
        # `message`: câu đã dựng sẵn ở nơi khác. `plan_eval` có bảng khắc phục RIÊNG cho các mã
        # P1–P8 (`steps-unanchored`, `plan-repetitive`, …); dựng lại câu ở đây bằng `REMEDIES` của
        # module này sẽ rơi về câu chung "không thoả luật của harness" — model mất đúng dòng nói
        # việc phải làm. Không truyền thì vẫn dựng từ `REMEDIES` như cũ.
        self.message = str(message) if message else rejection_message(code, **fields)
        super().__init__(self.message)

    @property
    def remedy(self) -> str:
        return self.message


# --------------------------------------------------------------------------- slug & identity


def slug_tokens(value) -> tuple[str, ...]:
    """`research-patient-record-lookup` → token ≥ 2 ký tự, giữ thứ tự, bỏ trùng."""
    tokens = []
    for token in str(value or '').lower().split('-'):
        if len(token) >= MIN_TOKEN_LENGTH and token not in tokens:
            tokens.append(token)
    return tuple(tokens)


def jaccard(left, right) -> float:
    """Độ giống Jaccard giữa hai slug (hoặc hai tập token). Hai tập rỗng → 0.0, không phải 1.0."""
    a = set(left if isinstance(left, (set, frozenset, tuple, list)) else slug_tokens(left))
    b = set(right if isinstance(right, (set, frozenset, tuple, list)) else slug_tokens(right))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def split_identity(identity) -> tuple[str, str]:
    """`'subplans/login'` → `('subplans', 'login')`; `''` → `('', '')`."""
    text = str(identity or '').strip().strip('/')
    if not text:
        return '', ''
    directory, _, slug = text.rpartition('/')
    return directory, slug


def parse_relates_to(value):
    """`'<identity>'` / `'<identity>@vN'` / `'none'` → `(identity | None, version | None)`.

    `'none'` (hoặc rỗng) nghĩa là "chủ đề mới": trả `(None, None)`. Chuỗi `@vN` chỉ giữ số để ghi
    vào header/nhật ký; **số version cuối cùng vẫn do harness quyết** (§3.1 không có tham số version).
    """
    text = str(value or '').strip()
    if not text or text.lower() == 'none':
        return None, None
    version = None
    identity = text
    head, sep, tail = text.rpartition('@')
    if sep and head and tail[1:].isdigit() and tail[:1] in {'v', 'V'}:
        identity, version = head, int(tail[1:])
    return identity.strip().strip('/') or None, version


# --------------------------------------------------------------------------- chỉ mục box


@dataclass(frozen=True)
class PlanIndexEntry:
    """Một version đang có trên box, đúng những gì reader công bố."""

    version: int
    relative_path: str
    size_bytes: int | None = None
    modified_at: str | None = None
    status: str = 'draft'
    header_status: str = 'legacy'
    header_version: int | None = None
    header_identity: str | None = None
    declared_parent: int | None = None
    declared_slug: str | None = None


@dataclass(frozen=True)
class PlanGroup:
    """Các version cùng `(thư mục, slug)`; `slug` là slug chuẩn của nhóm (box suy từ tên file)."""

    identity: str
    directory: str
    slug: str
    versions: tuple[PlanIndexEntry, ...] = ()

    @property
    def numbers(self) -> tuple[int, ...]:
        return tuple(entry.version for entry in self.versions)

    @property
    def newest(self):
        return max(self.versions, key=lambda entry: entry.version, default=None)

    def with_versions(self, versions) -> 'PlanGroup':
        return PlanGroup(self.identity, self.directory, self.slug, tuple(versions))


@dataclass(frozen=True)
class PlanIndex:
    """Chỉ mục đã đọc: nhóm theo identity, đúng thứ tự box trả về."""

    groups: tuple[PlanGroup, ...] = ()
    ignored_count: int = 0
    warnings: tuple[str, ...] = ()

    def identities(self) -> tuple[str, ...]:
        return tuple(group.identity for group in self.groups)

    def group(self, identity) -> PlanGroup | None:
        wanted = str(identity or '').strip().strip('/')
        for group in self.groups:
            if group.identity == wanted:
                return group
        return None

    def groups_in(self, directory) -> tuple[PlanGroup, ...]:
        wanted = str(directory or '').strip().strip('/')
        return tuple(group for group in self.groups if group.directory == wanted)

    def to_payload(self) -> dict:
        return {
            'plans': [
                {
                    'identity': group.identity,
                    'relativeDirectory': group.directory,
                    'slug': group.slug,
                    'versions': [
                        {
                            'version': entry.version,
                            'label': f'v{entry.version}',
                            'relativePath': entry.relative_path,
                            'sizeBytes': entry.size_bytes,
                            'modifiedAt': entry.modified_at,
                            'status': entry.status,
                            'headerStatus': entry.header_status,
                            'headerVersion': entry.header_version,
                            'headerIdentity': entry.header_identity,
                            'declaredParent': entry.declared_parent,
                            'declaredSlug': entry.declared_slug,
                        }
                        for entry in group.versions
                    ],
                }
                for group in self.groups
            ],
            'ignoredCount': self.ignored_count,
            'warnings': list(self.warnings),
        }


def _as_int(value):
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _entry_from_payload(item) -> PlanIndexEntry | None:
    """Một version từ payload; thiếu `version` hợp lệ là bỏ hàng đó chứ không đoán."""
    if not isinstance(item, dict):
        return None
    version = _as_int(item.get('version'))
    if version is None or version < 1:
        return None
    size = _as_int(item.get('sizeBytes'))
    header_status = item.get('headerStatus')
    return PlanIndexEntry(
        version=version,
        relative_path=str(item.get('relativePath') or ''),
        size_bytes=size if size is None or size >= 0 else None,
        modified_at=item.get('modifiedAt') if isinstance(item.get('modifiedAt'), str) else None,
        status=str(item.get('status') or 'draft'),
        # Không phải chuỗi (`headerStatus: 7`) thì đọc là `legacy`: giá trị lạ không được biến thành
        # một mức đánh giá mà reader chưa từng công bố.
        header_status=header_status if isinstance(header_status, str) and header_status else 'legacy',
        header_version=_as_int(item.get('headerVersion')),
        header_identity=(item.get('headerIdentity')
                         if isinstance(item.get('headerIdentity'), str) else None),
        declared_parent=_as_int(item.get('declaredParent')),
        declared_slug=(item.get('declaredSlug') if isinstance(item.get('declaredSlug'), str) else None),
    )


def parse_plan_index(payload) -> PlanIndex:
    """Payload của `GET /__box/plans/index` → `PlanIndex` (thuần, không I/O, không raise)."""
    if not isinstance(payload, dict):
        return PlanIndex()
    groups = []
    for item in payload.get('plans') or []:
        if not isinstance(item, dict):
            continue
        identity = str(item.get('identity') or '').strip().strip('/')
        if not identity:
            continue
        directory, slug = split_identity(identity)
        entries = [entry for entry in (_entry_from_payload(entry) for entry in item.get('versions') or [])
                   if entry is not None]
        entries.sort(key=lambda entry: entry.version)
        groups.append(PlanGroup(identity=identity, directory=directory,
                                slug=str(item.get('slug') or slug), versions=tuple(entries)))
    ignored = _as_int(payload.get('ignoredCount')) or 0
    warnings = payload.get('warnings')
    return PlanIndex(groups=tuple(groups), ignored_count=max(0, ignored),
                     warnings=tuple(str(entry) for entry in warnings or []))


async def read_plan_index(executor, *, log=None) -> PlanIndex | None:
    """Đọc chỉ mục plan từ box. `None` = nhánh suy giảm (đã ghi nhật ký), không bao giờ raise.

    Nhánh suy giảm được gọi tên `PLAN_INDEX_UNAVAILABLE` để người đọc nhật ký biết vì sao lần ghi
    đó quay về hành vi cũ (sandbox chọn số, không header) — thà mất tính năng còn hơn bịa số version.
    """
    logger = log or system_log
    try:
        payload = await executor.request(INDEX_PATH)
    except Exception as exc:  # mạng, 401, 500, JSON hỏng... đều là "không đọc được"
        _log_unavailable(logger, f'{type(exc).__name__}: {exc}')
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get('plans'), list):
        _log_unavailable(logger, 'payload không có danh sách plans')
        return None
    return parse_plan_index(payload)


def _log_unavailable(logger, reason: str) -> None:
    try:
        logger.write('plan.index.unavailable', level='warn', code=INDEX_UNAVAILABLE_CODE,
                     message='Không đọc được chỉ mục plan từ box; lần ghi này dùng hành vi cũ.',
                     reason=reason)
    except Exception:  # nhật ký không bao giờ được làm hỏng lượt ghi
        pass


# --------------------------------------------------------------------------- identity


@dataclass(frozen=True)
class IdentityDecision:
    """Kết quả `resolve_identity`. `action` ∈ `declared`/`merge`/`ambiguous`/`new`/`degraded`."""

    action: str
    identity: str = ''
    directory: str = ''
    slug: str = ''
    declared_slug: str | None = None
    matched_by: str = 'none'
    score: float | None = None
    matched_identity: str | None = None
    forced_new: bool = False
    candidates: tuple[tuple[str, float], ...] = ()

    @property
    def rejected(self) -> bool:
        return self.action == 'ambiguous'

    def to_payload(self) -> dict:
        return {
            'action': self.action, 'identity': self.identity, 'directory': self.directory,
            'slug': self.slug, 'declaredSlug': self.declared_slug, 'matchedBy': self.matched_by,
            'score': None if self.score is None else round(self.score, 4),
            'matchedIdentity': self.matched_identity, 'forcedNew': self.forced_new,
        }


def _decision_for_new(proposed_slug: str, directory: str, *, forced_new: bool) -> IdentityDecision:
    slug = str(proposed_slug or '').strip()
    identity = f'{directory}/{slug}' if directory else slug
    return IdentityDecision('new', identity=identity, directory=directory, slug=slug,
                            matched_by='none', forced_new=forced_new)


def _identity_is_valid(identity: str) -> bool:
    """Cùng một grammar với khối header (`plan_header.IDENTITY_PATTERN`), không có bản sao thứ ba."""
    return bool(_IDENTITY_TEXT_RE.match(identity))


def resolve_identity(proposed_slug, *, index=None, declared_identity=None, relates_to=None,
                     directory='', ambiguity_ticket=None) -> IdentityDecision:
    """Chọn identity cho một lần ghi (§3.2). Thuần: chỉ đọc `index`, không ghi gì.

    1. Có `declared_identity` (hoặc `relatesTo: "<identity>"`) hợp lệ → theo khai báo.
    2. Có `relatesTo: "none"` → chủ đề mới, **không** bị gộp ngược; vẫn báo `forced_new=True` nếu
       slug đề nghị giống `j ≥ 0.75` một nhóm cùng thư mục, để người gọi ghi mã
       `PLAN_IDENTITY_FORCED_NEW` (§3.3).
    3. Không khai báo → so Jaccard với mọi identity cùng thư mục: gộp / mơ hồ / nhóm mới.
    4. Rơi vào dải mơ hồ mà có `ambiguity_ticket` hợp lệ (vé của chính slug này, và slug chưa có nhóm
       nào) → nhóm mới, `matchedBy='ambiguity-ticket'`, nhưng **giữ** `score`/`matched_identity`/
       `candidates` để nhật ký vẫn nói được "bản này từng nằm trong dải mơ hồ" (D-3).

    `index=None` (chỉ mục hỏng) → `action='degraded'`: người gọi quay về hành vi cũ, không đoán bừa.
    Khai báo một identity sai grammar → raise `PlanRegistrationError('identity-invalid')`: viết một
    lần ghi vào tên file không hợp lệ thì phải dừng trước khi ghi, không im lặng đổi nhóm.
    """
    slug = str(proposed_slug or '').strip()
    directory = plan_room_directory(directory)
    explicit_none = relates_to is not None and str(relates_to or '').strip().lower() == 'none'
    declared = str(declared_identity or '').strip().strip('/')
    related_identity, _ = parse_relates_to(relates_to)
    related_identity = declared or related_identity

    if related_identity:
        # Chỗ chỉ định có thể kèm tiền tố phòng (`.plans/tao-ui`) hoặc dấu `/` thừa: chuẩn hoá TRƯỚC
        # khi kiểm grammar, vì `.plans/...` không phải một identity hợp lệ nhưng là một chỗ ghi hợp lệ.
        directory_of_declared, slug_of_declared = split_identity(related_identity)
        directory_of_declared = plan_room_directory(directory_of_declared)
        related_identity = (directory_of_declared + '/' if directory_of_declared else '') + slug_of_declared
        if not _identity_is_valid(related_identity):
            raise PlanRegistrationError('identity-invalid', identity=related_identity)
        canonical = slug_of_declared
        return IdentityDecision(
            'declared', identity=related_identity, directory=directory_of_declared,
            slug=canonical,
            declared_slug=slug if slug and slug != canonical else None,
            matched_by='declared')

    # Không khai chỗ ghi VÀ không khai "chủ đề mới": nếu đã có ĐÚNG một nhóm cùng slug ở một thư mục
    # con thì bản mới nối tiếp trong chính thư mục đó (`.plans/tao-ui/v1-x.md` →
    # `.plans/tao-ui/v2-x.md`) — "tìm thư mục plan mà ghi vào" theo luật chủ nhà, thay vì rơi về gốc
    # phòng và tách khỏi bản cũ. `relatesTo: "none"` là một khai báo nên nó vẫn thắng như cũ.
    if not directory and not explicit_none and index is not None and slug:
        owners = {group.directory for group in index.groups if group.slug == slug}
        if len(owners) == 1:
            directory = owners.pop()

    if index is None:
        return IdentityDecision('degraded', identity='', directory=directory,
                                slug=slug, matched_by='none')

    # `relatesTo: "none"` là một khai báo, nên nó thắng cả dải gộp: người dùng nói "chủ đề mới" thì
    # hệ thống ghi nhóm mới và để lại dấu `forcedNew` cho chủ dự án thấy (§3.3), chứ không lặng lẽ
    # kéo nó về nhóm cũ.
    candidates = []
    for group in index.groups_in(directory):
        if not group.slug:
            continue
        score = jaccard(slug, group.slug)
        if score > 0:
            candidates.append((score, group))
    candidates.sort(key=lambda item: (-item[0], item[1].identity))
    ranked = tuple((group.identity, round(score, 4)) for score, group in candidates)

    if candidates and not explicit_none:
        score, group = candidates[0]
        if score >= MERGE_THRESHOLD:
            return IdentityDecision('merge', identity=group.identity, directory=group.directory,
                                    slug=group.slug,
                                    declared_slug=slug if slug and slug != group.slug else None,
                                    matched_by='similarity', score=score,
                                    matched_identity=group.identity, candidates=ranked)
        if score >= AMBIGUOUS_THRESHOLD:
            if ambiguity_ticket_usable(ambiguity_ticket, slug=slug, directory=directory, index=index):
                # Gửi lại nguyên văn sau một lần bị từ chối vì mơ hồ: nhận là nhóm mới, nhưng giữ
                # `score`/`matched_identity`/`candidates` (khác `relatesTo: "none"` — ở đó khai báo
                # tường minh thắng và ta không có bản chấm nào để kể lại).
                fresh = _decision_for_new(slug, str(directory or '').strip('/'), forced_new=False)
                return IdentityDecision(fresh.action, identity=fresh.identity,
                                        directory=fresh.directory, slug=fresh.slug,
                                        matched_by=AMBIGUITY_MATCHED_BY, score=score,
                                        matched_identity=group.identity, candidates=ranked)
            return IdentityDecision('ambiguous', identity=group.identity, directory=group.directory,
                                    slug=group.slug, matched_by='similarity', score=score,
                                    matched_identity=group.identity, candidates=ranked)

    forced_new = bool(explicit_none and candidates and candidates[0][0] >= MERGE_THRESHOLD)
    # Giữ `candidates` để luật R3 (và nhật ký) nói được vì sao bị coi là chủ đề mới.
    decision = _decision_for_new(slug, str(directory or '').strip('/'), forced_new=forced_new)
    return IdentityDecision(decision.action, identity=decision.identity, directory=decision.directory,
                            slug=decision.slug, matched_by=decision.matched_by,
                            forced_new=decision.forced_new, candidates=ranked)


# --------------------------------------------------------------------------- vé mơ hồ (D-3)
# Dải `0.5 ≤ j < 0.75` là ca sống của vòng 21: cùng một kế hoạch bị từ chối ở lượt 4 rồi được nhận ở
# lượt 5 vì model tự đổi slug. Lần ĐẦU vẫn phải từ chối (gộp nhầm là mất dữ liệu không hoàn tác
# được), nhưng lời từ chối để lại một VÉ, để lần gửi lại **nguyên văn** được nhận là kế hoạch mới.
# Khoá dữ liệu nằm trên hàng `F:` (`kind='fact'`) — cố ý **không** phải `P:`: một bản bị từ chối thì
# không có tệp nào để giữ, nên vé không được đóng vai "người giữ" một kế hoạch không tồn tại (cổng xoá
# của `migrate_plans.py --delete-orphan` đọc đúng những hàng `P:` có `data.relativePath`).

AMBIGUITY_TICKET_KEY = 'identityAmbiguityTicket'
AMBIGUITY_MATCHED_BY = 'ambiguity-ticket'


def ambiguity_marker(decision) -> dict:
    """Dấu ghi vào hàng `P:` đã nhận: bản này từng nằm trong dải mơ hồ (D-3).

    `nearestIdentity` là nhóm gần nhất lúc đó, `score` là độ giống — đọc lại được về sau mà không phải
    suy từ bộ đếm chung. Dùng luôn cho `data.identityAmbiguity` của `pin_plan`.
    """
    return {'score': None if decision.score is None else round(decision.score, 4),
            'nearestIdentity': getattr(decision, 'matched_identity', None)}


def build_ambiguity_ticket(decision, *, slug, directory='') -> dict:
    """Vé cho một lần từ chối vì mơ hồ: dữ liệu của hàng `F:` (`data[AMBIGUITY_TICKET_KEY]`).

    Vé **không** mang `relativePath` (xem ghi chú đầu mục): nó không giữ kế hoạch nào.
    """
    return {
        'slug': str(slug or '').strip(),
        'directory': str(directory or '').strip('/'),
        'matchedIdentity': getattr(decision, 'matched_identity', None),
        'score': None if getattr(decision, 'score', None) is None else round(decision.score, 4),
        'candidates': [{'identity': name, 'score': score}
                       for name, score in getattr(decision, 'candidates', ()) or ()],
    }


def _row_data(row) -> dict:
    """`data` của một hàng nhật ký, đọc được cả ba khuôn: `payload.record.data`, payload phẳng, và
    hàng phẳng (`session_store.journal_tail` trả `payload` đã parse; hàng cũ có thể thiếu)."""
    if not isinstance(row, dict):
        return {}
    payload = row.get('payload')
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError:
            payload = None
    if not isinstance(payload, dict):
        payload = row
    record = payload.get('record')
    record = record if isinstance(record, dict) else payload
    data = record.get('data')
    return data if isinstance(data, dict) else {}


def ticket_from_rows(rows, *, slug, directory='') -> dict | None:
    """Vé còn nằm trong nhật ký phiên: dò `journal_tail(sid, kinds=['fact'])` rồi khớp `(slug, directory)`.

    Trả vé **mới nhất** khớp; `None` khi phiên chưa từng bị từ chối vì mơ hồ (hoặc mọi vé đã bị
    khoá bởi lần gửi lại trước đó). Hàm thuần: hàng vào, vé ra — người gọi tự quyết định đọc hàng nào.
    """
    wanted_slug = str(slug or '').strip()
    wanted_directory = str(directory or '').strip('/')
    found = None
    for row in rows or ():
        ticket = _row_data(row).get(AMBIGUITY_TICKET_KEY)
        if not isinstance(ticket, dict):
            continue
        if str(ticket.get('slug') or '').strip() != wanted_slug:
            continue
        if str(ticket.get('directory') or '').strip('/') != wanted_directory:
            continue
        found = ticket  # hàng xếp cũ → mới, nên vé cuối cùng là vé mới nhất
    return found


def ambiguity_ticket_usable(ticket, *, slug, directory='', index=None) -> bool:
    """Vé dùng được: khớp đúng `(slug, directory)` **và** chưa có nhóm nào cho slug đó.

    Điều kiện thứ hai là chỗ vé **tiêu đúng một lần**: lần gửi lại được nhận sẽ ghim hàng `P:` (và
    sandbox ghi tệp, nên slug có mặt trong chỉ mục); từ đó mọi lần gửi lại đi theo chỉ mục — gộp với
    chính nó (`j = 1.0 ≥ 0.75`), hoặc bị từ chối vì truy vết — chứ không "ép chủ đề mới" lần thứ hai.
    Không cần thêm bảng, thêm cột, thêm trạng thái nào.

    `index=None` (không đọc được chỉ mục) → `False`: không kiểm được "đã có `P:` chưa" thì vé không
    dùng, và nhánh suy giảm vốn đã quay về hành vi cũ.
    """
    if not isinstance(ticket, dict):
        return False
    if str(ticket.get('slug') or '').strip() != str(slug or '').strip():
        return False
    if str(ticket.get('directory') or '').strip('/') != str(directory or '').strip('/'):
        return False
    if index is None:
        return False
    directory_text = str(directory or '').strip('/')
    slug_text = str(slug or '').strip()
    identity = f'{directory_text}/{slug_text}' if directory_text else slug_text
    return index.group(identity) is None


# --------------------------------------------------------------------------- số version


@dataclass(frozen=True)
class VersionPlan:
    """Số harness sẽ ghi và `Parent` tương ứng. `parent=None` chỉ khi đây là `v1` của nhóm."""

    version: int
    parent: int | None
    declared_version: int | None = None
    declared_parent: int | None = None


def next_version_and_parent(versions, *, declared_version=UNSET, declared_parent=UNSET,
                            identity='') -> VersionPlan:
    """`v(N+1)` / `Parent: vN` cho bản kế tiếp của một nhóm (§3.4 + R1).

    Model **không** chọn được số version (§3.1): khối header nó viết chỉ được phép khớp con số
    harness đã quyết. `declared_version`/`declared_parent` là những gì model khai (nếu có khối):
    lệch → `header-mismatch`; khai `Parent: none` khi N ≥ 1 → `revision-not-traceable` (R1).
    """
    numbers = set()
    for item in versions or ():
        number = _version_of(item)
        if number is not None and number >= 1:
            numbers.add(number)
    ordered = sorted(numbers)
    newest = ordered[-1] if ordered else 0
    version = newest + 1
    parent = newest or None

    if declared_version is not UNSET and declared_version is not None and declared_version != version:
        raise PlanRegistrationError('header-mismatch', identity=identity, declared=f'khai v{declared_version}',
                                    version=version, parent_hint='')
    if declared_parent is not UNSET and parent is not None:
        if declared_parent is None:
            raise PlanRegistrationError('revision-not-traceable', identity=identity, version=newest)
        if declared_parent != parent:
            raise PlanRegistrationError('header-mismatch', identity=identity, declared=f'khai v{declared_parent}',
                                        version=version,
                                        parent_hint=f' với Parent: v{parent} (bản sửa phải khai đúng bản trước)')
    return VersionPlan(version=version, parent=parent,
                       declared_version=None if declared_version is UNSET else declared_version,
                       declared_parent=None if declared_parent is UNSET else declared_parent)


# --------------------------------------------------------------------------- trạng thái duyệt

# §4.2: `draft` (chưa có dòng nào cho bản mới nhất) → `submitted` (harness đã phát
# `request_approval` cho đúng bản đó, chưa có trả lời) → `approved` | `changes_requested`.
# `none` = identity không có trong chỉ mục; `unknown` = không đọc được chỉ mục (nói thật là không biết).
GROUP_STATES = ('none', 'draft', 'submitted', 'approved', 'changes_requested', 'unknown')
PENDING_STATES = ('draft', 'submitted', 'changes_requested')
MAX_NOTE_CHARS = 120


@dataclass(frozen=True)
class GroupState:
    """Trạng thái của **bản mới nhất** trong một nhóm, kèm hàng sổ duyệt của chính bản đó."""

    state: str = 'none'
    state_version: int | None = None
    review: dict | None = None
    review_stale: bool = False
    index_available: bool = True

    @property
    def pending(self) -> bool:
        """True khi chưa có sự đồng ý — đúng tập trạng thái của R1."""
        return self.state in PENDING_STATES

    def to_payload(self) -> dict:
        review = self.review or {}
        return {
            'state': self.state,
            'stateVersion': self.state_version,
            'review': None if not self.review else {
                'identity': review.get('identity'),
                'version': review.get('version'),
                'decision': review.get('decision'),
                'note': review.get('note') or '',
                'source': review.get('source') or 'plan-tab',
                'sessionId': review.get('session_id'),
                'decidedAt': review.get('decided_at'),
                'contentSize': review.get('content_size'),
                'contentModifiedAt': review.get('content_modified_at'),
                # Vòng 25 (M6): hàng duyệt nói được nó đã MỞ một lượt thật hay chưa.
                'resumed': bool(review.get('resumed')),
            },
            'reviewStale': bool(self.review_stale),
            'indexAvailable': bool(self.index_available),
        }


def _version_of(item):
    return item.version if isinstance(item, PlanIndexEntry) else _as_int(item)


def _entry_of(item):
    return item if isinstance(item, PlanIndexEntry) else None


def review_stale(review, entry) -> bool:
    """Bản duyệt đã cũ: chỉ mục box báo số đo khác con số chốt lúc duyệt (§4.2).

    Không đo được (thiếu `sizeBytes`/`modifiedAt` ở một trong hai phía) → `False`: thiếu dữ liệu
    không phải bằng chứng của thay đổi.
    """
    if not review or not isinstance(entry, PlanIndexEntry):
        return False
    stamp_size = review.get('content_size')
    stamp_modified = review.get('content_modified_at')
    if stamp_size is None and not stamp_modified:
        return False
    if stamp_size is not None and entry.size_bytes is not None and int(stamp_size) != entry.size_bytes:
        return True
    if stamp_modified and entry.modified_at and stamp_modified != entry.modified_at:
        return True
    return False


def group_state(versions, *, reviews=(), submitted=(), index_available=True) -> GroupState:
    """Máy trạng thái §4.2 cho một nhóm. Thuần: `reviews` là hàng bảng `plan_reviews`.

    `versions` là các version đang có (số hoặc `PlanIndexEntry`); `reviews` là hàng sổ duyệt của
    nhóm; `submitted` là các version đã được phát `request_approval` mà chưa có trả lời. Chỉ bản
    **mới nhất** quyết định trạng thái — duyệt `v1` không bao giờ làm `v2` thành `approved`.
    """
    numbers = sorted({number for number in (_version_of(item) for item in versions or ())
                      if number and number >= 1})
    by_version = {}
    for row in reviews or ():
        if isinstance(row, dict) and _as_int(row.get('version')):
            by_version[int(row['version'])] = row
    if not numbers and not index_available:
        return GroupState('unknown', None, None, False, False)
    if not numbers:
        return GroupState('none', None, None, False, index_available)
    newest = numbers[-1]
    entry = next((_entry_of(item) for item in versions or ()
                  if _version_of(item) == newest and _entry_of(item) is not None), None)
    review = by_version.get(newest)
    if review:
        decision = str(review.get('decision') or '')
        state = decision if decision in ('approved', 'changes_requested') else 'draft'
    elif newest in {int(number) for number in submitted or ()}:
        state = 'submitted'
    else:
        state = 'draft'
    return GroupState(state, newest, review, review_stale(review, entry), index_available)


def pending_submissions(pending, identity) -> tuple[int, ...]:
    """Các version đã được phát `request_approval` mà chưa trả lời, từ `runtime.pending`.

    Cố tình **không** đọc lại từ file/database nào khác: một lượt hỏi còn treo chỉ tồn tại trong
    bộ nhớ của lượt chạy đó (harness khởi động lại thì lượt bị ngắt), nên `submitted` cũng phải
    biến mất theo. Khai báo khác đi sẽ là bịa một câu trả lời đang chờ không có thật.
    """
    wanted = str(identity or '').strip().strip('/')
    found = set()
    for record in (pending or ()):
        if not isinstance(record, dict) or record.get('resolved'):
            continue
        if record.get('kind') != 'approval':
            continue
        if str(record.get('planIdentity') or '').strip().strip('/') != wanted:
            continue
        version = _as_int(record.get('planVersion'))
        if version and version >= 1:
            found.add(version)
    return tuple(sorted(found))


# --------------------------------------------------------------------------- ghép thành một lần ghi


@dataclass(frozen=True)
class RegistrationPlan:
    """Kết quả một lần đăng ký ghi plan: mọi con số harness đã quyết, sẵn sàng dựng header."""

    identity: str
    directory: str
    slug: str
    version: int
    parent: int | None
    declared_slug: str | None = None
    matched_by: str = 'none'
    score: float | None = None
    forced_new: bool = False
    degraded: bool = False
    state: str = 'draft'
    state_version: int | None = None
    notes: tuple[str, ...] = field(default=())
    ambiguity: dict | None = None

    def to_payload(self) -> dict:
        return {
            'identity': self.identity, 'directory': self.directory, 'slug': self.slug,
            'version': self.version, 'parent': self.parent, 'declaredSlug': self.declared_slug,
            'identityMatchedBy': self.matched_by,
            'identityScore': None if self.score is None else round(self.score, 4),
            'identityForcedNew': self.forced_new, 'degraded': self.degraded,
            'state': self.state, 'stateVersion': self.state_version,
            'identityAmbiguity': self.ambiguity,
        }


def _review_note(reviews, identity) -> str:
    """Ghi chú mới nhất của một nhóm đang chờ sửa — để câu từ chối trích đúng lời người dùng."""
    for row in reversed(list(reviews or ())):
        if not isinstance(row, dict):
            continue
        if row.get('decision') == 'changes_requested' and (row.get('note') or '').strip():
            return str(row['note']).strip()[:_NOTE_QUOTE_CHARS]
    return ''


def plan_registration(proposed_slug, *, index, reviews_by_identity=None, directory='',
                      declared_identity=None, relates_to=None, declared_version=UNSET,
                      declared_parent=UNSET, submitted_by_identity=None,
                      ambiguity_ticket=None) -> RegistrationPlan:
    """Toàn bộ luật §3.2–§4.3 gói trong một lời gọi, cho `runtime.write_plan`.

    Trả `RegistrationPlan` (kể cả nhánh suy giảm khi `index is None`, lúc đó `degraded=True` và
    người gọi quay về hành vi cũ) hoặc raise `PlanRegistrationError` với một trong các mã:

    * `identity-ambiguous` — dải `0.5 ≤ j < 0.75`, phải khai `identity`/`relatesTo` (hoặc gửi lại
      nguyên văn khi đã có `ambiguity_ticket` của chính slug đó);
    * `identity-pending-review` — R3: nhóm đang `changes_requested` nên không được trỏ sang identity
      khác cùng chủ đề (`relatesTo: "none"` cũng không vượt được);
    * `revision-not-traceable` — R1: khai `Parent: none` khi nhóm đã có bản cũ;
    * `header-mismatch` — model khai version/parent khác con số harness sẽ ghi.
    """
    reviews_by_identity = reviews_by_identity or {}
    submitted_by_identity = submitted_by_identity or {}
    # Chuẩn hoá MỘT lần ở đây để vé mơ hồ, quyết định identity và tên tệp ghi ra dùng chung một giá
    # trị: vé ghi bằng chỗ đã kẹp thì lượt gửi lại (cùng tham số thô) cũng phải tra được.
    directory = plan_room_directory(directory)
    decision = resolve_identity(proposed_slug, index=index, declared_identity=declared_identity,
                                relates_to=relates_to, directory=directory,
                                ambiguity_ticket=ambiguity_ticket)
    if decision.action == 'degraded':
        return RegistrationPlan(identity='', directory=directory,
                                slug=str(proposed_slug or '').strip(), version=0, parent=None,
                                degraded=True, state='unknown', state_version=None)

    if decision.action == 'ambiguous':
        others = [name for name, score in decision.candidates if name != decision.matched_identity]
        # D-3: lời từ chối mang theo VÉ dựng sẵn (`ambiguity_ticket`), vì chỉ ở đây mới còn biết
        # `proposed_slug` (trường `slug` của lỗi là slug của NHÓM, để câu khắc phục đọc được). Chỗ gọi
        # (`runtime.write_plan`) ghi nguyên khối này xuống hàng `F:` và gửi lại nguyên văn thì nhận.
        raise PlanRegistrationError('identity-ambiguous', identity=decision.matched_identity or '',
                                    other=others[0] if others else decision.matched_identity or '',
                                    score=decision.score or 0.0, slug=decision.slug,
                                    ambiguity_ticket=build_ambiguity_ticket(
                                        decision, slug=proposed_slug, directory=directory))

    group = index.group(decision.identity) if index is not None else None
    reviews = reviews_by_identity.get(decision.identity) or ()
    state = group_state(group.versions if group else (), reviews=reviews,
                        submitted=submitted_by_identity.get(decision.identity) or (),
                        index_available=index is not None)

    # R3: bỏ nhóm đang chờ sửa để mở một identity khác cho cùng chủ đề là lờ yêu cầu sửa.
    if decision.action == 'new' and decision.candidates and decision.candidates[0][1] >= AMBIGUOUS_THRESHOLD:
        abandoned = index.group(decision.candidates[0][0]) if index is not None else None
        if abandoned is not None:
            abandoned_state = group_state(abandoned.versions,
                                          reviews=reviews_by_identity.get(abandoned.identity) or (),
                                          submitted=submitted_by_identity.get(abandoned.identity) or (),
                                          index_available=True)
            if abandoned_state.state == 'changes_requested':
                raise PlanRegistrationError(
                    'identity-pending-review', identity=abandoned.identity,
                    note=_review_note(reviews_by_identity.get(abandoned.identity) or (),
                                      abandoned.identity))
    if decision.forced_new and group is not None:
        forced_state = group_state(group.versions, reviews=reviews,
                                   submitted=submitted_by_identity.get(group.identity) or ())
        if forced_state.state == 'changes_requested':
            raise PlanRegistrationError(
                'identity-pending-review', identity=group.identity,
                note=_review_note(reviews, group.identity))

    version_plan = next_version_and_parent(group.numbers if group else (), identity=decision.identity,
                                           declared_version=declared_version,
                                           declared_parent=declared_parent)
    # Dấu D-3: bản được nhận nhờ vé mơ hồ vẫn kể lại được "đã từng mơ hồ" — người gọi ghi nguyên
    # khối này vào `data` của hàng `P:` (`identityAmbiguity`), nên nhật ký không mất dấu vết.
    ambiguity = ambiguity_marker(decision) if decision.matched_by == AMBIGUITY_MATCHED_BY else None
    notes = ()
    if decision.forced_new:
        notes = (f'{IDENTITY_FORCED_NEW_CODE}: slug «{decision.slug}» giống nhóm «'
                 f'{decision.matched_identity or ""}» nhưng bạn khai relatesTo: "none" — harness vẫn '
                 'ghi thành identity mới.',)
    return RegistrationPlan(
        identity=decision.identity, directory=decision.directory, slug=decision.slug,
        version=version_plan.version, parent=version_plan.parent, declared_slug=decision.declared_slug,
        matched_by=decision.matched_by, score=decision.score, forced_new=decision.forced_new,
        degraded=False, state=state.state, state_version=state.state_version, notes=notes,
        ambiguity=ambiguity)
