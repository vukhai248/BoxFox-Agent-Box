"""SkillSpec gốc BoxFox: dữ liệu có phiên bản, không phải quyền hạn hay sự cho phép.

Module này không đọc và không sao chép file skill riêng của nền tảng: toàn văn nằm sau
`context.fullTextRef` và không bao giờ được nhúng thẳng vào spec. `readiness()` chỉ trả
ready/degraded/blocked kèm lý do; nó không đề xuất tạo tool thay thế, không cài package và
không vượt quyền. Registry lưu draft, review độc lập, phiên bản đã enable và ghim phiên bản
theo attempt; `enable` không bao giờ viết lại bản mà một attempt đang hoạt động dùng.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import re
import sqlite3
import time
import uuid

from .orchestration_contracts import (
    ContractError, identifier, invalid, object_fields, revision, string_list, text,
)
from .work_policy import digest

SKILL_SCHEMA = 'boxfox-skill-spec/1'
SKILL_SPEC_INVALID = 'SKILL_SPEC_INVALID'
SKILL_SCHEMA_UNSUPPORTED = 'SKILL_SCHEMA_UNSUPPORTED'
SKILL_UNKNOWN = 'SKILL_UNKNOWN'
SKILL_NOT_REVIEWED = 'SKILL_NOT_REVIEWED'
SKILL_REVISION_CONFLICT = 'SKILL_REVISION_CONFLICT'
SKILL_STATE_CONFLICT = 'SKILL_STATE_CONFLICT'
SKILL_INVOCATION_CONFLICT = 'SKILL_INVOCATION_CONFLICT'
SKILL_VERSION_CONFLICT = 'SKILL_VERSION_CONFLICT'

GOAL_MAX = 4000
TITLE_MAX = 400
SUMMARY_MAX = 400
LIST_MAX = 100
ITEM_MAX = 2000
REF_MAX = 500
PAGE_LIMIT = 100
DEFAULT_PAGE = 50
SKILL_STATES = ('draft', 'enabled', 'disabled')
REVIEW_VERDICTS = ('approve', 'reject')
READINESS_STATES = ('ready', 'degraded', 'blocked')
ORIGINS = ('builtin', 'authored', 'adapted', 'imported')
# Một ref là `scheme:phần-còn-lại`, một dòng, không khoảng trắng — đủ để loại văn xuôi
# prompt nhúng thẳng, nhưng không phải bộ phân tích URL đầy đủ.
REF = re.compile(r'[A-Za-z][A-Za-z0-9+._-]{0,63}:[^\s\x00]{1,435}\Z')

_REQUIRED = ('schemaVersion', 'id', 'version', 'title', 'goal', 'trigger', 'applicability',
             'requirements', 'procedure', 'acceptance', 'context')
_OPTIONAL = ('provenance', 'handoff', 'reviewRefs', 'testedPlatforms', 'contractVersion')
_DIMENSIONS = ('roleRevision', 'toolRevision', 'adapterRevision', 'sourceVersion', 'contextEpoch')
_DEPENDENCIES = ('tools', 'capabilities', 'commands', 'environmentRefs', 'packages')
_DEPENDENCY_LABELS = {'tools': 'tool', 'capabilities': 'capability', 'commands': 'command',
                      'environmentRefs': 'environment', 'packages': 'package'}


def _remap(exc):
    detail = str(exc).split(': ', 2)[-1]
    return ContractError(SKILL_SPEC_INVALID, exc.field, detail)


def _call(helper, *args, **kwargs):
    """Gọi helper dùng chung và quy mọi lỗi hợp đồng về mã SKILL_SPEC_INVALID."""
    try:
        return helper(*args, **kwargs)
    except ContractError as exc:
        raise _remap(exc) from None


def _fields(value, field, required, optional=()):
    return _call(object_fields, value, field, required, optional)


def _identifier(value, field, *, alias=False):
    return _call(identifier, value, field, alias=alias)


def _revision(value, field='version'):
    return _call(revision, value, field)


def _text(value, field, limit=None):
    return _call(text, value, field, limit)


def _string_list(value, field, *, nonempty=False, limit=LIST_MAX, item_limit=ITEM_MAX):
    return _call(string_list, value, field, nonempty=nonempty, limit=limit, item_limit=item_limit)


def _ref(value, field):
    _text(value, field, REF_MAX)
    if not REF.fullmatch(value):
        invalid(field, 'expected a bounded scheme:reference, never inline text', SKILL_SPEC_INVALID)
    return value


def _encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                      allow_nan=False)


def _provenance(value):
    fields = _fields(value, 'provenance', ('origin',),
                     ('sourceRefs', 'sourceVersion', 'licenseMetadata', 'authoredAt'))
    origin = fields['origin']
    if not isinstance(origin, str) or origin not in ORIGINS:
        invalid('provenance.origin', 'expected builtin, authored, adapted or imported',
                SKILL_SPEC_INVALID)
    source_refs = _string_list(fields.get('sourceRefs', []), 'provenance.sourceRefs')
    for ref in source_refs:
        _ref(ref, 'provenance.sourceRefs')
    optional = {}
    for name in ('sourceVersion', 'licenseMetadata', 'authoredAt'):
        item = fields.get(name)
        if item is not None:
            optional[name] = _text(item, 'provenance.' + name, TITLE_MAX)
    # Nguồn ngoài builtin phải khai nguồn tham chiếu và giấy phép; thiếu là từ chối.
    if origin != 'builtin':
        if not source_refs:
            invalid('provenance.sourceRefs', 'a non-builtin origin requires source references',
                    SKILL_SPEC_INVALID)
        if 'licenseMetadata' not in optional:
            invalid('provenance.licenseMetadata', 'a non-builtin origin requires license metadata',
                    SKILL_SPEC_INVALID)
    return dict({'origin': origin, 'sourceRefs': source_refs}, **optional)


def _context(value):
    fields = _fields(value, 'context', ('fullTextRef',), ('summary', 'contextCostEstimate'))
    result = {'fullTextRef': _ref(fields['fullTextRef'], 'context.fullTextRef')}
    if 'summary' in fields:
        result['summary'] = _text(fields['summary'], 'context.summary', SUMMARY_MAX)
    cost = fields.get('contextCostEstimate')
    if cost is not None:
        if type(cost) is not int or cost < 0:
            invalid('context.contextCostEstimate',
                    'expected a non-negative integer, or null when unknown', SKILL_SPEC_INVALID)
        result['contextCostEstimate'] = cost
    return result


def _normalize(value):
    request = _fields(value, 'skill', _REQUIRED, _OPTIONAL)
    if request['schemaVersion'] != SKILL_SCHEMA:
        invalid('schemaVersion', 'unsupported skill schema', SKILL_SCHEMA_UNSUPPORTED)
    trigger = _fields(request['trigger'], 'trigger', ('intents', 'artifactKinds', 'actionClasses'))
    applicability = _fields(request['applicability'], 'applicability',
                            ('roles', 'environments', 'exclusions'))
    requirements = _fields(request['requirements'], 'requirements', _DEPENDENCIES)
    procedure = _fields(request['procedure'], 'procedure',
                        ('requiredLocalChecks', 'adaptiveBranches', 'stopConditions'))
    acceptance = _fields(request['acceptance'], 'acceptance',
                         ('outcomes', 'evidenceKinds', 'forbiddenEffects'))
    handoff = request.get('handoff')
    if handoff is None:
        handoff = {'persistedRefs': [], 'revalidateConditions': []}
    else:
        handoff = _fields(handoff, 'handoff', (), ('persistedRefs', 'revalidateConditions'))
        persisted = _string_list(handoff.get('persistedRefs', []), 'handoff.persistedRefs')
        for ref in persisted:
            _ref(ref, 'handoff.persistedRefs')
        handoff = {'persistedRefs': persisted,
                   'revalidateConditions': _string_list(handoff.get('revalidateConditions', []),
                                                        'handoff.revalidateConditions')}
    return {
        'schemaVersion': SKILL_SCHEMA,
        'id': _identifier(request['id'], 'id'),
        'version': _revision(request['version'], 'version'),
        'title': _text(request['title'], 'title', TITLE_MAX),
        'goal': _text(request['goal'], 'goal', GOAL_MAX),
        'trigger': {name: _string_list(trigger[name], 'trigger.' + name)
                    for name in ('intents', 'artifactKinds', 'actionClasses')},
        'applicability': {name: _string_list(applicability[name], 'applicability.' + name)
                          for name in ('roles', 'environments', 'exclusions')},
        'requirements': {name: _string_list(requirements[name], 'requirements.' + name)
                         for name in _DEPENDENCIES},
        # Không khai provenance nghĩa là skill builtin; khai null/khai thiếu là từ chối.
        'provenance': _provenance(request['provenance']) if 'provenance' in request
                      else {'origin': 'builtin'},
        'procedure': {name: _string_list(procedure[name], 'procedure.' + name)
                      for name in ('requiredLocalChecks', 'adaptiveBranches', 'stopConditions')},
        'acceptance': {name: _string_list(acceptance[name], 'acceptance.' + name)
                       for name in ('outcomes', 'evidenceKinds', 'forbiddenEffects')},
        'context': _context(request['context']),
        'handoff': handoff,
        'reviewRefs': _string_list(request.get('reviewRefs', []), 'reviewRefs'),
        'testedPlatforms': _string_list(request.get('testedPlatforms', []), 'testedPlatforms'),
        'contractVersion': _revision(request.get('contractVersion', 1), 'contractVersion'),
    }


@dataclass(frozen=True, init=False)
class SkillSpec:
    """Ảnh chụp đã kiểm và bất biến; không phải quyền chạy hay phê duyệt."""

    payload_json: str

    def __init__(self, *args, **kwargs):
        raise TypeError('Use SkillSpec.parse to validate a skill spec')

    @property
    def payload(self):
        return json.loads(self.payload_json)

    @property
    def skill_hash(self):
        return digest(self.payload)

    @property
    def skill_id(self):
        return self.payload['id']

    @property
    def version(self):
        return self.payload['version']

    @classmethod
    def parse(cls, value):
        try:
            normalized = _normalize(value)
        except ContractError as exc:
            if exc.code in (SKILL_SPEC_INVALID, SKILL_SCHEMA_UNSUPPORTED):
                raise
            raise _remap(exc) from None
        try:
            snapshot = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False)
        except (ValueError, TypeError) as exc:
            invalid('skill', f'not a finite JSON document: {exc}', SKILL_SPEC_INVALID)
        instance = object.__new__(cls)
        object.__setattr__(instance, 'payload_json', snapshot)
        return instance


def _coerce(spec):
    if isinstance(spec, SkillSpec):
        return spec
    if isinstance(spec, dict):
        return SkillSpec.parse(spec)
    invalid('skill', 'expected a parsed SkillSpec or a skill payload', SKILL_SPEC_INVALID)


@dataclass(frozen=True)
class SkillReadiness:
    """Kết quả bất biến: một trạng thái và các lý do người đọc được."""

    state: str
    reasons: tuple = ()

    def __post_init__(self):
        if isinstance(self.reasons, (str, bytes)):
            raise ValueError('readiness reasons must be a collection of strings')
        object.__setattr__(self, 'reasons', tuple(self.reasons))
        if self.state not in READINESS_STATES:
            raise ValueError(f'unknown readiness state: {self.state!r}')
        if self.state == 'ready' and self.reasons:
            raise ValueError('ready readiness cannot carry reasons')
        if self.state != 'ready' and not self.reasons:
            raise ValueError(f'{self.state} readiness requires at least one reason')
        if any(not isinstance(reason, str) or not reason for reason in self.reasons):
            raise ValueError('readiness reasons must be nonempty strings')


def _names(value, field):
    if isinstance(value, (str, bytes)) or value is None:
        invalid(field, 'expected a collection of names', SKILL_SPEC_INVALID)
    try:
        items = list(value)
    except TypeError:
        invalid(field, 'expected a collection of names', SKILL_SPEC_INVALID)
    if any(not isinstance(item, str) or not item for item in items):
        invalid(field, 'expected nonempty names', SKILL_SPEC_INVALID)
    return set(items)


def _environment(value):
    if not isinstance(value, dict):
        invalid('environment', 'expected a mapping', SKILL_SPEC_INVALID)
    result = {name: _names(value.get(name, ()), 'environment.' + name)
              for name in ('commands', 'packages', 'environmentRefs')}
    if value.get('contextEpoch') is not None:
        result['contextEpoch'] = _revision(value['contextEpoch'], 'environment.contextEpoch')
    return result


def readiness(spec, *, tools, capabilities, roles, environment, context_epoch=None):
    """Kiểm điều kiện chạy với executor/role hiệu lực; chỉ báo cáo, không tự cấp quyền.

    Thiếu tool/capability/command/environment/package hoặc không có role phù hợp là
    `blocked`. Thiếu context tùy chọn hoặc chưa biết epoch là `degraded`. Lý do không bao
    giờ gợi ý chế tool thay thế, cài package hay vượt quyền.
    """
    spec = _coerce(spec)
    payload = spec.payload
    available = {'tools': _names(tools, 'tools'),
                 'capabilities': _names(capabilities, 'capabilities'),
                 'roles': _names(roles, 'roles')}
    env = _environment(environment)
    epoch = context_epoch if context_epoch is not None else env.get('contextEpoch')
    if epoch is not None:
        _revision(epoch, 'contextEpoch')
    sources = {'tools': available['tools'], 'capabilities': available['capabilities'],
               'commands': env['commands'], 'environmentRefs': env['environmentRefs'],
               'packages': env['packages']}
    blocked, degraded = [], []
    for name in _DEPENDENCIES:
        for item in payload['requirements'][name]:
            if item not in sources[name]:
                blocked.append(f"missing {_DEPENDENCY_LABELS[name]} '{item}'")
    declared_roles = payload['applicability']['roles']
    if declared_roles and not set(declared_roles) & available['roles']:
        blocked.append('no applicable role: skill targets ' + ', '.join(sorted(declared_roles)))
    if epoch is None:
        degraded.append('context epoch unknown: revalidate before use')
    if 'summary' not in payload['context']:
        degraded.append('context summary missing: load the full text behind fullTextRef')
    if 'contextCostEstimate' not in payload['context']:
        degraded.append('context cost estimate unknown')
    state = 'blocked' if blocked else ('degraded' if degraded else 'ready')
    return SkillReadiness(state=state, reasons=tuple(blocked + degraded))


def revalidate(spec, previous, *, role_revision=None, tool_revision=None, adapter_revision=None,
               source_version=None, context_epoch=None):
    """True chỉ khi mọi đầu vào được cung cấp vẫn khớp lần đánh giá trước.

    Đầu vào không cung cấp (None) thì không so sánh được và bị bỏ qua; đầu vào được cung
    cấp mà lần trước không ghi lại giá trị thì tính là đổi (fail closed) và trả False.
    """
    _coerce(spec)
    if not isinstance(previous, dict):
        invalid('previous', 'expected the recorded evaluation inputs', SKILL_SPEC_INVALID)
    extra = set(previous) - set(_DIMENSIONS)
    if extra:
        invalid('previous', f'unsupported fields {sorted(extra)}', SKILL_SPEC_INVALID)
    current = {}
    for name, value in (('roleRevision', role_revision), ('toolRevision', tool_revision),
                        ('adapterRevision', adapter_revision)):
        if value is not None:
            current[name] = _revision(value, name)
    if source_version is not None:
        current['sourceVersion'] = _text(source_version, 'sourceVersion', ITEM_MAX)
    if context_epoch is not None:
        current['contextEpoch'] = _revision(context_epoch, 'contextEpoch')
    reasons = []
    for name in _DIMENSIONS:
        if name not in current:
            continue
        if name not in previous:
            reasons.append(f'{name}: previous evaluation did not record a value; re-evaluate')
        elif previous[name] != current[name]:
            reasons.append(f'{name} changed from {previous[name]!r} to {current[name]!r}')
    return (not reasons, tuple(reasons))


def _cursor_of(view):
    return f"{view['skillId']}@{view['version']}"


def _cursor(value):
    _text(value, 'cursor', 200)
    skill_id, separator, raw = value.rpartition('@')
    if not separator or not skill_id or not raw.isdigit():
        invalid('cursor', 'expected <skillId>@<version>', SKILL_SPEC_INVALID)
    return _identifier(skill_id, 'cursor'), _revision(int(raw), 'cursor')


class SkillRegistry:
    """Sổ đăng ký skill bền vững trên SessionStore: draft -> review -> enable, kèm ghim.

    Đây là lưu trữ và trạng thái, không phải thẩm quyền: `enable` không cấp quyền, và một
    phiên bản đã ghim cho attempt đang mở không bao giờ bị viết lại.
    """

    def __init__(self, store):
        self.store, self.db = store, store.db
        for table, required in (
                ('harness_skills', ('skill_id', 'version', 'revision', 'state', 'spec_hash',
                                    'spec_json', 'provenance_json', 'review_json',
                                    'created_at', 'updated_at')),
                ('harness_skill_reviews', ('review_id', 'skill_id', 'version', 'reviewer_id',
                                           'verdict', 'notes', 'created_at')),
                ('harness_skill_pins', ('pin_id', 'skill_id', 'version', 'attempt_id',
                                        'session_id', 'created_at')),
                ('harness_skill_invocations', ('scope', 'invocation_id', 'operation',
                                               'request_hash', 'result_json', 'created_at'))):
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if columns and not set(required) <= columns:
                invalid('schemaVersion', f'{table} does not match the skill record schema',
                        SKILL_SCHEMA_UNSUPPORTED)
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS harness_skills (
                skill_id TEXT NOT NULL, version INTEGER NOT NULL, revision INTEGER NOT NULL,
                state TEXT NOT NULL, spec_hash TEXT NOT NULL, spec_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL, review_json TEXT NOT NULL, state_reason TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(skill_id, version));
            CREATE INDEX IF NOT EXISTS harness_skills_state ON harness_skills(state, skill_id, version);
            CREATE TABLE IF NOT EXISTS harness_skill_reviews (
                review_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, version INTEGER NOT NULL,
                reviewer_id TEXT NOT NULL, verdict TEXT NOT NULL, notes TEXT NOT NULL,
                created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS harness_skill_pins (
                pin_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, version INTEGER NOT NULL,
                attempt_id TEXT NOT NULL, session_id TEXT NOT NULL, created_at REAL NOT NULL,
                UNIQUE(skill_id, version, attempt_id));
            CREATE TABLE IF NOT EXISTS harness_skill_invocations (
                scope TEXT NOT NULL, invocation_id TEXT NOT NULL, operation TEXT NOT NULL,
                request_hash TEXT NOT NULL, result_json TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(scope, invocation_id));
        ''')
        # `state_reason` là cột cộng thêm của hàng disable; DB cũ đã có bảng từ build trước
        # thì thêm cột, không đụng dữ liệu cũ.
        self._add_missing_column('harness_skills', 'state_reason', 'state_reason TEXT')

    def _add_missing_column(self, table, name, ddl):
        columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
        if columns and name not in columns:
            with self.db:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {ddl}')

    @contextmanager
    def _write(self):
        # Khuôn của task_service: khoá ghi khi tự mở transaction, savepoint khi đã ở trong
        # transaction của caller; không bao giờ commit transaction của người gọi.
        if self.db.in_transaction:
            self.db.execute('SAVEPOINT harness_skill_write')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK TO harness_skill_write')
                raise
            finally:
                self.db.execute('RELEASE harness_skill_write')
        else:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                yield

    def _row(self, skill_id, version):
        return self.db.execute('SELECT * FROM harness_skills WHERE skill_id=? AND version=?',
                               (skill_id, version)).fetchone()

    def _require_row(self, skill_id, version):
        row = self._row(skill_id, version)
        if row is None:
            invalid('skillId', 'unknown skill version', SKILL_UNKNOWN)
        return row

    @staticmethod
    def _view(row, *, spec=False):
        result = {'skillId': row['skill_id'], 'version': row['version'], 'revision': row['revision'],
                  'state': row['state'], 'specHash': row['spec_hash'],
                  'title': json.loads(row['spec_json'])['title'],
                  'review': json.loads(row['review_json']) or None,
                  'stateReason': row['state_reason'],
                  'createdAt': row['created_at'], 'updatedAt': row['updated_at']}
        if spec:
            result['spec'] = json.loads(row['spec_json'])
            result['provenance'] = json.loads(row['provenance_json'])
        return result

    @staticmethod
    def _pin_view(row):
        return {'pinId': row['pin_id'], 'skillId': row['skill_id'], 'version': row['version'],
                'attemptId': row['attempt_id'], 'sessionId': row['session_id'],
                'createdAt': row['created_at']}

    def _cached(self, scope, invocation_id, operation, request_hash):
        if invocation_id is None:
            return None
        row = self.db.execute('SELECT * FROM harness_skill_invocations WHERE scope=? '
                              'AND invocation_id=?', (scope, invocation_id)).fetchone()
        if row is None:
            return None
        if row['operation'] != operation or row['request_hash'] != request_hash:
            invalid('invocationId', 'invocation reused with a different request',
                    SKILL_INVOCATION_CONFLICT)
        return json.loads(row['result_json'])

    def _remember(self, scope, invocation_id, operation, request_hash, result):
        if invocation_id is None:
            return result
        try:
            self.db.execute('INSERT INTO harness_skill_invocations VALUES(?,?,?,?,?,?)',
                            (scope, invocation_id, operation, request_hash, _encode(result),
                             time.time()))
        except sqlite3.IntegrityError:
            # Người ghi đồng thời có thể đã commit cùng invocation; hàng là thẩm quyền.
            cached = self._cached(scope, invocation_id, operation, request_hash)
            if cached is None:
                raise
            return cached
        return result

    def propose(self, spec, owner_id, invocation_id):
        """Ghi một hàng `draft`; idempotent theo invocation + request hash, không auto-enable."""
        spec = _coerce(spec)
        _identifier(owner_id, 'ownerId')
        _identifier(invocation_id, 'invocationId')
        payload = spec.payload
        skill_id, version = payload['id'], payload['version']
        request_hash = digest({'action': 'propose', 'ownerId': owner_id, 'skillId': skill_id,
                               'version': version, 'specHash': spec.skill_hash})
        with self._write():
            cached = self._cached(owner_id, invocation_id, 'propose', request_hash)
            if cached is not None:
                return cached
            row = self._row(skill_id, version)
            if row is None:
                now = time.time()
                try:
                    self.db.execute('INSERT INTO harness_skills VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                    (skill_id, version, 1, 'draft', spec.skill_hash,
                                     spec.payload_json, _encode(payload['provenance']), '{}',
                                     None, now, now))
                except sqlite3.IntegrityError:
                    row = self._row(skill_id, version)
                    if row is None or row['spec_hash'] != spec.skill_hash:
                        invalid('version', 'skill version already exists with different content',
                                SKILL_VERSION_CONFLICT)
            elif row['spec_hash'] != spec.skill_hash:
                invalid('version', 'skill version already exists with different content',
                        SKILL_VERSION_CONFLICT)
            return self._remember(owner_id, invocation_id, 'propose', request_hash,
                                  self._view(self._row(skill_id, version), spec=True))

    def review(self, skill_id, version, reviewer_id, verdict, notes=None, invocation_id=None):
        """Ghi phán quyết độc lập cho đúng một phiên bản; không đổi revision hay trạng thái."""
        _identifier(skill_id, 'skillId')
        _revision(version, 'version')
        _identifier(reviewer_id, 'reviewerId')
        if verdict not in REVIEW_VERDICTS:
            invalid('verdict', "expected 'approve' or 'reject'", SKILL_SPEC_INVALID)
        notes = '' if notes is None else _text(notes, 'notes', ITEM_MAX)
        if invocation_id is not None:
            _identifier(invocation_id, 'invocationId')
        request_hash = digest({'action': 'review', 'skillId': skill_id, 'version': version,
                               'reviewerId': reviewer_id, 'verdict': verdict, 'notes': notes})
        with self._write():
            cached = self._cached(reviewer_id, invocation_id, 'review', request_hash)
            if cached is not None:
                return cached
            self._require_row(skill_id, version)
            review_id, now = 'review-' + uuid.uuid4().hex, time.time()
            self.db.execute('INSERT INTO harness_skill_reviews VALUES(?,?,?,?,?,?,?)',
                            (review_id, skill_id, version, reviewer_id, verdict, notes, now))
            summary = {'reviewId': review_id, 'reviewerId': reviewer_id, 'verdict': verdict,
                       'notes': notes, 'createdAt': now}
            self.db.execute('UPDATE harness_skills SET review_json=?, updated_at=? '
                            'WHERE skill_id=? AND version=?',
                            (_encode(summary), now, skill_id, version))
            result = dict(summary, skillId=skill_id, version=version)
            return self._remember(reviewer_id, invocation_id, 'review', request_hash, result)

    def enable(self, skill_id, version, expected_revision, invocation_id=None, *,
               attempt_id=None, session_id=None):
        """Bật một phiên bản đã được review `approve`; chỉ hàng đích đổi trạng thái.

        Khi có `attempt_id`/`session_id`, ghim luôn phiên bản cho attempt đó. Bản đã ghim
        của attempt đang mở không bị viết lại: enable chỉ đổi hàng đích, giữ nguyên spec_hash.
        """
        _identifier(skill_id, 'skillId')
        _revision(version, 'version')
        _revision(expected_revision, 'expectedRevision')
        if (attempt_id is None) != (session_id is None):
            invalid('attemptId', 'attemptId and sessionId must be supplied together',
                    SKILL_SPEC_INVALID)
        if attempt_id is not None:
            _identifier(attempt_id, 'attemptId')
            _identifier(session_id, 'sessionId')
        if invocation_id is not None:
            _identifier(invocation_id, 'invocationId')
        request_hash = digest({'action': 'enable', 'skillId': skill_id, 'version': version,
                               'expectedRevision': expected_revision, 'attemptId': attempt_id,
                               'sessionId': session_id})
        with self._write():
            cached = self._cached('registry', invocation_id, 'enable', request_hash)
            if cached is not None:
                return cached
            row = self._require_row(skill_id, version)
            if row['revision'] != expected_revision:
                invalid('expectedRevision', 'skill revision changed', SKILL_REVISION_CONFLICT)
            if json.loads(row['review_json']).get('verdict') != 'approve':
                invalid('review', 'enabling requires an approved review of this exact version',
                        SKILL_NOT_REVIEWED)
            if row['state'] != 'enabled':
                now = time.time()
                self.db.execute("UPDATE harness_skills SET state='enabled', state_reason=NULL, "
                                'revision=revision+1, updated_at=? WHERE skill_id=? AND version=?',
                                (now, skill_id, version))
            if attempt_id is not None:
                self._pin(skill_id, version, attempt_id, session_id)
            return self._remember('registry', invocation_id, 'enable', request_hash,
                                  self._view(self._row(skill_id, version), spec=True))

    def disable(self, skill_id, version, reason, invocation_id=None):
        """Tắt một phiên bản; gọi lại là no-op idempotent, giữ nguyên lý do lần đầu."""
        _identifier(skill_id, 'skillId')
        _revision(version, 'version')
        reason = _text(reason, 'reason', ITEM_MAX)
        if invocation_id is not None:
            _identifier(invocation_id, 'invocationId')
        request_hash = digest({'action': 'disable', 'skillId': skill_id, 'version': version,
                               'reason': reason})
        with self._write():
            cached = self._cached('registry', invocation_id, 'disable', request_hash)
            if cached is not None:
                return cached
            row = self._require_row(skill_id, version)
            if row['state'] != 'disabled':
                now = time.time()
                self.db.execute("UPDATE harness_skills SET state='disabled', state_reason=?, "
                                'revision=revision+1, updated_at=? WHERE skill_id=? AND version=?',
                                (reason, now, skill_id, version))
            return self._remember('registry', invocation_id, 'disable', request_hash,
                                  self._view(self._row(skill_id, version), spec=True))

    def _pin(self, skill_id, version, attempt_id, session_id):
        existing = self.db.execute('SELECT * FROM harness_skill_pins WHERE skill_id=? '
                                   'AND version=? AND attempt_id=?',
                                   (skill_id, version, attempt_id)).fetchone()
        if existing is not None:
            return self._pin_view(existing)
        pin_id, now = 'pin-' + uuid.uuid4().hex, time.time()
        self.db.execute('INSERT INTO harness_skill_pins VALUES(?,?,?,?,?,?)',
                        (pin_id, skill_id, version, attempt_id, session_id, now))
        return {'pinId': pin_id, 'skillId': skill_id, 'version': version,
                'attemptId': attempt_id, 'sessionId': session_id, 'createdAt': now}

    def pin(self, skill_id, version, attempt_id, session_id):
        """Ghim một phiên bản đã enable cho attempt đang dùng; không sửa hàng skill."""
        _identifier(skill_id, 'skillId')
        _revision(version, 'version')
        _identifier(attempt_id, 'attemptId')
        _identifier(session_id, 'sessionId')
        with self._write():
            row = self._require_row(skill_id, version)
            if row['state'] != 'enabled':
                invalid('state', 'only an enabled version can be pinned to an attempt',
                        SKILL_STATE_CONFLICT)
            return self._pin(skill_id, version, attempt_id, session_id)

    def pins(self, *, skill_id=None, attempt_id=None, session_id=None, limit=PAGE_LIMIT):
        if type(limit) is not int or not 1 <= limit <= PAGE_LIMIT:
            invalid('limit', f'expected an integer between 1 and {PAGE_LIMIT}', SKILL_SPEC_INVALID)
        sql, args = 'SELECT * FROM harness_skill_pins WHERE 1=1', []
        for name, value in (('skill_id', skill_id), ('attempt_id', attempt_id),
                            ('session_id', session_id)):
            if value is not None:
                _identifier(value, name)
                sql += f' AND {name}=?'
                args.append(value)
        rows = self.db.execute(sql + ' ORDER BY created_at, pin_id LIMIT ?',
                               (*args, limit)).fetchall()
        return [self._pin_view(row) for row in rows]

    def get(self, skill_id, version=None):
        """Lấy một phiên bản; không truyền version thì ưu tiên bản enabled cao nhất."""
        _identifier(skill_id, 'skillId')
        if version is None:
            row = self.db.execute("SELECT * FROM harness_skills WHERE skill_id=? "
                                  "AND state='enabled' ORDER BY version DESC LIMIT 1",
                                  (skill_id,)).fetchone()
            if row is None:
                row = self.db.execute('SELECT * FROM harness_skills WHERE skill_id=? '
                                      'ORDER BY version DESC LIMIT 1', (skill_id,)).fetchone()
        else:
            _revision(version, 'version')
            row = self._row(skill_id, version)
        if row is None:
            invalid('skillId', 'unknown skill', SKILL_UNKNOWN)
        return self._view(row, spec=True)

    def list(self, state=None, cursor=None, limit=DEFAULT_PAGE):
        """Phân trang keyset theo (skill_id, version), khuôn `task_service.list`."""
        if state is not None and state not in SKILL_STATES:
            invalid('state', 'unknown skill state', SKILL_SPEC_INVALID)
        if type(limit) is not int or not 1 <= limit <= PAGE_LIMIT:
            invalid('limit', f'expected an integer between 1 and {PAGE_LIMIT}', SKILL_SPEC_INVALID)
        after_id, after_version = '', 0
        if cursor is not None:
            after_id, after_version = _cursor(cursor)
        sql = 'SELECT * FROM harness_skills WHERE (skill_id > ? OR (skill_id = ? AND version > ?))'
        args = [after_id, after_id, after_version]
        if state is not None:
            sql += ' AND state=?'
            args.append(state)
        rows = self.db.execute(sql + ' ORDER BY skill_id, version LIMIT ?',
                               (*args, limit + 1)).fetchall()
        items = [self._view(row) for row in rows[:limit]]
        return {'items': items, 'hasMore': len(rows) > limit,
                'nextAfter': _cursor_of(items[-1]) if items else None}
