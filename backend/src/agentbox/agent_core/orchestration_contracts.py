"""Versioned data contracts, not authority to spawn, write, or spend.

Validated requests are immutable JSON snapshots. Admission must still resolve
owners, input refs, policies, grants, and allocation against canonical stores.
Legacy delegate arguments deliberately do not pass through this new parser.
"""
from dataclasses import dataclass
import json
import re

from .roles import ROLES
from .work_policy import digest

TASK_SCHEMA = 'boxfox-task-contract/1'
TASK_STATES = frozenset({'queued', 'running', 'waiting_input', 'succeeded', 'partial',
                         'failed', 'interrupted', 'cancelled', 'abandoned'})
ACCEPTANCE_STATES = frozenset({'unverified', 'accepted', 'needs_revision', 'blocked'})
ARTIFACT_STATES = frozenset({'draft', 'finalized', 'superseded'})
MESSAGE_KINDS = frozenset({'information', 'clarification', 'scope_proposal'})
INTENTS = frozenset({'analysis', 'plan', 'design', 'implementation'})
MODES = frozenset({'read_only', 'workspace_write'})
ALIAS = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,119}\Z')
IDENTITY = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z')
HASH = re.compile(r'[a-f0-9]{64}\Z')
GOAL_MAX = 12000
SHORT_TEXT_MAX = 200
LIST_MAX = 100
LIST_ITEM_MAX = 2000


class ContractError(ValueError):
    def __init__(self, code, field, detail):
        self.code, self.field = code, field
        super().__init__(f'{code}: {field}: {detail}')


def invalid(field, detail, code='HARNESS_CONTRACT_INVALID'):
    raise ContractError(code, field, detail)


def identifier(value, field, *, alias=False):
    pattern = ALIAS if alias else IDENTITY
    if not isinstance(value, str) or not pattern.fullmatch(value):
        invalid(field, 'expected a bounded non-path identifier')
    return value


def revision(value, field='expectedRevision'):
    if type(value) is not int or value < 1:
        invalid(field, 'expected a positive integer, not a boolean')
    return value


def object_fields(value, field, required, optional=()):
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        invalid(field, 'expected an object with string keys')
    missing = set(required) - set(value)
    extra = set(value) - set(required) - set(optional)
    if missing or extra:
        invalid(field, f'missing fields {sorted(missing)}; unsupported fields {sorted(extra)}')
    return value


def text(value, field, limit=None):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        invalid(field, 'expected nonempty text without NUL')
    if limit is not None and len(value) > limit:
        invalid(field, f'expected text of at most {limit} characters')
    return value


def string_list(value, field, *, nonempty=False, limit=None, item_limit=None):
    if not isinstance(value, list) or (nonempty and not value):
        invalid(field, 'expected a list' + (' with at least one entry' if nonempty else ''))
    if limit is not None and len(value) > limit:
        invalid(field, f'expected at most {limit} entries')
    for item in value:
        text(item, field, item_limit)
    if len(value) != len(set(value)):
        invalid(field, 'duplicate entries')
    return list(value)


def input_ref(value, field='inputRef'):
    ref = object_fields(value, field, ('artifactId', 'version', 'contentHash'), ('ownerId', 'kind'))
    identifier(ref['artifactId'], field + '.artifactId')
    revision(ref['version'], field + '.version')
    if not isinstance(ref['contentHash'], str) or not HASH.fullmatch(ref['contentHash']):
        invalid(field + '.contentHash', 'expected a SHA-256 hex digest')
    if 'ownerId' in ref:
        identifier(ref['ownerId'], field + '.ownerId')
    if 'kind' in ref:
        text(ref['kind'], field + '.kind', SHORT_TEXT_MAX)
    return dict(ref)


def refs(value, field='inputs'):
    if not isinstance(value, list):
        invalid(field, 'expected artifact references')
    if len(value) > LIST_MAX:
        invalid(field, f'expected at most {LIST_MAX} references')
    result = [input_ref(item, field) for item in value]
    identities = [(item['artifactId'], item['version']) for item in result]
    if len(identities) != len(set(identities)):
        invalid(field, 'duplicate artifact versions')
    return result


def scope(value):
    result = object_fields(value, 'scope', ('read', 'write', 'externalSources'))
    for field in ('read', 'write'):
        paths = string_list(result[field], 'scope.' + field, limit=LIST_MAX, item_limit=LIST_ITEM_MAX)
        for path in paths:
            # Task paths are workspace-relative selectors, not host writable roots.
            if (path.startswith('/') or '\\' in path or ':' in path
                    or any(part in ('', '..') for part in path.split('/'))):
                invalid('scope.' + field, 'expected workspace-relative paths without traversal')
    if result['externalSources'] not in ('none', 'approved'):
        invalid('scope.externalSources', 'expected none or approved; this is not a grant')
    return {k: (list(v) if isinstance(v, list) else v) for k, v in result.items()}


def deliverable(value):
    fields = ('kind', 'format', 'evidence', 'acceptance')
    result = object_fields(value, 'deliverable', fields)
    text(result['kind'], 'deliverable.kind', SHORT_TEXT_MAX)
    text(result['format'], 'deliverable.format', SHORT_TEXT_MAX)
    string_list(result['evidence'], 'deliverable.evidence', nonempty=True,
                limit=LIST_MAX, item_limit=LIST_ITEM_MAX)
    string_list(result['acceptance'], 'deliverable.acceptance', nonempty=True,
                limit=LIST_MAX, item_limit=LIST_ITEM_MAX)
    return dict(result)


def allocation(value):
    result = object_fields(value, 'budget', ('allocationPolicy',), ('allocationRef', 'consentRef'))
    if result['allocationPolicy'] not in ('inherited', 'referenced'):
        invalid('budget.allocationPolicy', 'expected inherited or referenced')
    for name in ('allocationRef', 'consentRef'):
        if name in result:
            identifier(result[name], 'budget.' + name)
    if result['allocationPolicy'] == 'referenced' and 'allocationRef' not in result:
        invalid('budget.allocationRef', 'required for referenced allocation')
    return dict(result)


@dataclass(frozen=True, init=False)
class TaskContract:
    """A checked data snapshot. It is never an admission or acceptance receipt."""
    payload_json: str

    def __init__(self, *args, **kwargs):
        raise TypeError('Use TaskContract.parse to validate a task contract')

    @property
    def payload(self):
        return json.loads(self.payload_json)

    @property
    def contract_hash(self):
        return digest(self.payload)

    @classmethod
    def parse(cls, value):
        required = ('schema', 'taskId', 'invocationId', 'role', 'goal', 'intent', 'mode',
                    'inputs', 'scope', 'deliverable', 'dependsOn', 'budget')
        request = object_fields(value, 'task', required, ('wait',))
        if request['schema'] != TASK_SCHEMA:
            invalid('schema', 'unsupported task schema', 'HARNESS_SCHEMA_UNSUPPORTED')
        identifier(request['taskId'], 'taskId', alias=True)
        identifier(request['invocationId'], 'invocationId')
        if not isinstance(request['role'], str) or request['role'] not in ROLES:
            invalid('role', 'expected a registered specialist role')
        text(request['goal'], 'goal', GOAL_MAX)
        if not isinstance(request['intent'], str) or request['intent'] not in INTENTS:
            invalid('intent', 'explicit supported intent required')
        if not isinstance(request['mode'], str) or request['mode'] not in MODES:
            invalid('mode', 'explicit supported mode required; legacy is not an admission mode')
        wait = request.get('wait', False)
        if type(wait) is not bool:
            invalid('wait', 'expected a boolean')
        normalized = dict(request, wait=wait)
        normalized['inputs'] = refs(request['inputs'])
        normalized['scope'] = scope(request['scope'])
        normalized['deliverable'] = deliverable(request['deliverable'])
        normalized['budget'] = allocation(request['budget'])
        dependencies = string_list(request['dependsOn'], 'dependsOn', limit=LIST_MAX, item_limit=LIST_ITEM_MAX)
        for dependency in dependencies:
            identifier(dependency, 'dependsOn', alias=True)
        if request['taskId'] in dependencies:
            invalid('dependsOn', 'task cannot depend on itself')
        normalized['dependsOn'] = dependencies
        if request['mode'] == 'read_only' and normalized['scope']['write']:
            invalid('scope.write', 'read-only contract cannot request source writes')
        if request['intent'] != 'implementation' and (request['mode'] == 'workspace_write'
                                                     or normalized['scope']['write']):
            invalid('mode', 'analysis/plan/design cannot request source writes')
        # Serialization severs all caller-owned containers, including nested refs.
        try:
            snapshot = json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False)
        except (ValueError, TypeError) as exc:
            invalid('task', f'not a finite JSON document: {exc}')
        instance = object.__new__(cls)
        object.__setattr__(instance, 'payload_json', snapshot)
        return instance
