"""Pure context manifests: preservation data, never instruction or admission authority.

Backend provenance is a claim about a ref's source, not authentication. Consumers
must resolve refs/owners/epochs in canonical stores before acting. No bodies,
transcripts, model calls, grants, verdicts, or loader effects live here. Callers
must sanitize goal/non-goal and diagnostic text before persistence.
"""
from dataclasses import dataclass
import json

from .orchestration_contracts import (
    TASK_STATES, identifier, input_ref, invalid, object_fields, revision,
    string_list, text,
)
from .work_policy import digest

CONTEXT_SCHEMA = 'boxfox-context-bundle/1'
CHECKPOINT_SCHEMA = 'boxfox-context-checkpoint/1'
REF_STATES = ('available', 'blocked', 'truncated', 'unknown', 'missing')
ROOT_FIELDS = ('schema', 'contextEpoch', 'intentRef', 'taskContractRef',
               'activeDecisionRefs', 'capabilityView', 'inputManifestRef',
               'checkpoints', 'unresolvedConflicts', 'resultRefs',
               'recentEventCursor', 'loadedSkillRefs', 'providerMetadataRef')


def _choice(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        invalid(field, f'expected one of {choices}')


def _epoch(value, field, *, nullable=False):
    if nullable and value is None:
        return
    revision(value, field)


def _reason(value, field, required=False):
    if value is None and not required:
        return
    text(value, field)


def _ref(value, field, *, backend=False):
    ref = object_fields(value, field,
                        ('artifactId', 'version', 'contentHash', 'provenance', 'status', 'reason'),
                        ('ownerId', 'kind'))
    input_ref({k: v for k, v in ref.items()
               if k not in ('provenance', 'status', 'reason')}, field)
    _choice(ref['provenance'], field + '.provenance', ('backend', 'data'))
    if backend and ref['provenance'] != 'backend':
        invalid(field, 'data/summary cannot stand in for a canonical backend ref')
    _choice(ref['status'], field + '.status', REF_STATES)
    _reason(ref['reason'], field + '.reason', ref['status'] != 'available')


def _list(value, field):
    if not isinstance(value, list):
        invalid(field, 'expected a list')
    return value


def _refs(value, field, *, backend=False):
    seen = set()
    for i, ref in enumerate(_list(value, field)):
        _ref(ref, f'{field}[{i}]', backend=backend)
        key = (ref['artifactId'], ref['version'])
        if key in seen:
            invalid(field, 'duplicate artifact versions')
        seen.add(key)


def _checkpoint(value):
    field = 'checkpoints'
    cp = object_fields(value, field, ('schema', 'goal', 'nonGoals', 'consentRefs',
                                     'pendingTasks', 'unknownToolOutcomes',
                                     'readCoverage', 'uncertaintyRefs'))
    if cp['schema'] != CHECKPOINT_SCHEMA:
        invalid(field + '.schema', 'unsupported checkpoint schema', 'HARNESS_SCHEMA_UNSUPPORTED')
    text(cp['goal'], field + '.goal')
    string_list(cp['nonGoals'], field + '.nonGoals')
    _refs(cp['consentRefs'], field + '.consentRefs', backend=True)
    _refs(cp['uncertaintyRefs'], field + '.uncertaintyRefs')
    seen = set()
    for item in _list(cp['pendingTasks'], field + '.pendingTasks'):
        object_fields(item, 'pendingTask', ('taskId', 'attemptId', 'taskContractRef', 'state'))
        identifier(item['taskId'], 'pendingTask.taskId')
        if item['attemptId'] is not None:
            identifier(item['attemptId'], 'pendingTask.attemptId')
        _ref(item['taskContractRef'], 'pendingTask.taskContractRef', backend=True)
        _choice(item['state'], 'pendingTask.state', tuple(sorted(TASK_STATES - {
            'succeeded', 'partial', 'failed', 'cancelled', 'abandoned'})) + ('unknown',))
        key = (item['taskId'], item['attemptId'])
        if key in seen:
            invalid('pendingTasks', 'duplicate task/attempt')
        seen.add(key)
    seen = set()
    for item in _list(cp['unknownToolOutcomes'], field + '.unknownToolOutcomes'):
        object_fields(item, 'unknownToolOutcome', ('invocationId', 'taskId', 'attemptId',
                                                  'toolName', 'outcome', 'replaySafety', 'receiptRef'))
        for name in ('invocationId', 'taskId', 'attemptId', 'toolName'):
            identifier(item[name], 'unknownToolOutcome.' + name)
        _choice(item['outcome'], 'unknownToolOutcome.outcome', ('unknown',))
        _choice(item['replaySafety'], 'unknownToolOutcome.replaySafety', ('unsafe', 'unknown'))
        if item['receiptRef'] is not None:
            _ref(item['receiptRef'], 'unknownToolOutcome.receiptRef', backend=True)
        if item['invocationId'] in seen:
            invalid('unknownToolOutcomes', 'duplicate invocation')
        seen.add(item['invocationId'])
    seen = set()
    for item in _list(cp['readCoverage'], field + '.readCoverage'):
        object_fields(item, 'readCoverage', ('ref', 'purpose', 'required', 'coverage', 'reason'))
        _ref(item['ref'], 'readCoverage.ref')
        _choice(item['purpose'], 'readCoverage.purpose', ('target', 'supporting'))
        if type(item['required']) is not bool:
            invalid('readCoverage.required', 'expected a boolean')
        if item['purpose'] == 'target' and not item['required']:
            invalid('readCoverage.required', 'targets must require full reads')
        _choice(item['coverage'], 'readCoverage.coverage', ('full', 'partial', 'none'))
        _reason(item['reason'], 'readCoverage.reason', item['coverage'] != 'full')
        key = (item['ref']['artifactId'], item['ref']['version'])
        if key in seen:
            invalid('readCoverage', 'duplicate artifact versions')
        seen.add(key)


@dataclass(frozen=True)
class ContextGap:
    code: str
    field: str
    detail: str


@dataclass(frozen=True)
class RecallReport:
    """No gaps means structural recall only, not approval or live-model recall."""
    gaps: tuple[ContextGap, ...]
    reload_skill_ids: tuple[str, ...]

    @property
    def preserved(self):
        return not self.gaps


@dataclass(frozen=True, init=False)
class ContextBundle:
    """Immutable JSON snapshot; parse is a data constructor, not a grant."""
    payload_json: str

    def __init__(self, *args, **kwargs):
        raise TypeError('Use ContextBundle.parse to validate a context manifest')

    @property
    def payload(self):
        return json.loads(self.payload_json)

    @property
    def manifest_hash(self):
        return digest(self.payload)

    @classmethod
    def from_json(cls, value):
        # Reject duplicate keys rather than letting an authority-looking field win.
        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    invalid('context', 'duplicate JSON key: ' + key)
                result[key] = item
            return result
        try:
            payload = json.loads(value, object_pairs_hook=unique)
        except (TypeError, ValueError) as exc:
            invalid('context', f'invalid JSON: {exc}')
        return cls.parse(payload)

    @classmethod
    def parse(cls, value):
        root = object_fields(value, 'context', ROOT_FIELDS)
        if root['schema'] != CONTEXT_SCHEMA:
            invalid('schema', 'unsupported context schema', 'HARNESS_SCHEMA_UNSUPPORTED')
        _epoch(root['contextEpoch'], 'contextEpoch')
        for name in ('intentRef', 'taskContractRef', 'inputManifestRef'):
            _ref(root[name], name, backend=True)
        _ref(root['providerMetadataRef'], 'providerMetadataRef')
        _refs(root['activeDecisionRefs'], 'activeDecisionRefs', backend=True)
        for name in ('unresolvedConflicts', 'resultRefs'):
            _refs(root[name], name)
        view = object_fields(root['capabilityView'], 'capabilityView',
                             ('policyRef', 'capabilityRef', 'policyEpoch', 'capabilityEpoch'))
        for name in ('policyRef', 'capabilityRef'):
            _ref(view[name], 'capabilityView.' + name, backend=True)
        for name in ('policyEpoch', 'capabilityEpoch'):
            _epoch(view[name], 'capabilityView.' + name)
        _checkpoint(root['checkpoints'])
        cursor = object_fields(root['recentEventCursor'], 'recentEventCursor', ('runId', 'sequence'))
        identifier(cursor['runId'], 'recentEventCursor.runId')
        if type(cursor['sequence']) is not int or cursor['sequence'] < 0:
            invalid('recentEventCursor.sequence', 'expected nonnegative integer')
        seen = set()
        for skill in _list(root['loadedSkillRefs'], 'loadedSkillRefs'):
            object_fields(skill, 'skill', ('skillId', 'version', 'fullTextRef',
                                          'loadedContextEpoch', 'bodyContextEpoch'))
            identifier(skill['skillId'], 'skill.skillId')
            revision(skill['version'], 'skill.version')
            _ref(skill['fullTextRef'], 'skill.fullTextRef')
            for name in ('loadedContextEpoch', 'bodyContextEpoch'):
                _epoch(skill[name], 'skill.' + name, nullable=name == 'bodyContextEpoch')
                if skill[name] is not None and skill[name] > root['contextEpoch']:
                    invalid('skill.' + name, 'cannot claim a future context epoch')
            if skill['skillId'] in seen:
                invalid('loadedSkillRefs', 'duplicate skill ID')
            seen.add(skill['skillId'])
        pins = {}

        def check_pins(value):
            if isinstance(value, dict):
                if 'artifactId' in value:
                    key = (value['artifactId'], value['version'])
                    pin = (value['contentHash'], value['provenance'])
                    if key in pins and pins[key] != pin:
                        invalid('context', 'conflicting hash/provenance for the same artifact version')
                    pins[key] = pin
                for item in value.values():
                    check_pins(item)
            elif isinstance(value, list):
                for item in value:
                    check_pins(item)
        check_pins(root)
        try:
            snapshot = json.dumps(root, ensure_ascii=False, sort_keys=True,
                                  separators=(',', ':'), allow_nan=False)
        except (ValueError, TypeError) as exc:
            invalid('context', f'not a finite JSON manifest: {exc}')
        instance = object.__new__(cls)
        object.__setattr__(instance, 'payload_json', snapshot)
        return instance

    def checkpoint(self, context_epoch):
        """Prepare compact/handoff data. Old skill bodies are NOT carried forward."""
        revision(context_epoch, 'contextEpoch')
        payload = self.payload
        if context_epoch <= payload['contextEpoch']:
            invalid('contextEpoch', 'checkpoint must advance the context epoch')
        payload['contextEpoch'] = context_epoch
        for skill in payload['loadedSkillRefs']:
            skill['bodyContextEpoch'] = None
        return self.parse(payload)

    def reload_skill_ids(self):
        root = self.payload
        return tuple(skill['skillId'] for skill in root['loadedSkillRefs']
                     if skill['loadedContextEpoch'] != root['contextEpoch']
                     or skill['bodyContextEpoch'] != root['contextEpoch']
                     or skill['fullTextRef']['status'] != 'available')

    def manifest_gaps(self):
        """Report visible missing/partial data. Never fetch or silently drop it."""
        root, gaps = self.payload, []

        def walk(value, path):
            if isinstance(value, dict):
                if 'artifactId' in value and value['status'] != 'available':
                    gaps.append(ContextGap('ref_unavailable', path, value['status'] + ': ' + value['reason']))
                for key, item in value.items():
                    walk(item, path + '.' + key)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    walk(item, f'{path}[{i}]')
        walk(root, 'context')
        for i, item in enumerate(root['unresolvedConflicts']):
            gaps.append(ContextGap('conflict_unresolved', f'unresolvedConflicts[{i}]', item['artifactId']))
        for i, item in enumerate(root['checkpoints']['readCoverage']):
            if item['required'] and item['coverage'] != 'full':
                gaps.append(ContextGap('read_incomplete', f'checkpoints.readCoverage[{i}]',
                                       item['purpose'] + ': ' + item['reason']))
        for i, item in enumerate(root['checkpoints']['unknownToolOutcomes']):
            gaps.append(ContextGap('tool_outcome_unknown', f'checkpoints.unknownToolOutcomes[{i}]',
                                   item['invocationId'] + ': ' + item['replaySafety']))
        for skill_id in self.reload_skill_ids():
            gaps.append(ContextGap('skill_reload_required', 'loadedSkillRefs', skill_id))
        return tuple(gaps)


def compare_recall(before, after):
    """Compare immutable manifests, not model memories or canonical authority.

    A changed pin, erased conflict/consent/task, or epoch drift is an explicit gap.
    Adding new decisions or pending tasks is permitted; changing old entries is not.
    Skill reload is separate from decision preservation after a valid handoff.
    """
    old, new, gaps = before.payload, after.payload, []

    def unchanged(field, left, right):
        if left != right:
            gaps.append(ContextGap('recall_changed', field, 'preserved value missing or changed'))

    def retained(field, left, right):
        for i, item in enumerate(left):
            if item not in right:
                gaps.append(ContextGap('recall_missing', f'{field}[{i}]', 'preserved entry missing or changed'))

    if new['contextEpoch'] < old['contextEpoch']:
        gaps.append(ContextGap('context_epoch_stale', 'contextEpoch', 'epoch moved backwards'))
    for name in ('intentRef', 'taskContractRef', 'inputManifestRef', 'capabilityView', 'providerMetadataRef'):
        unchanged(name, old[name], new[name])
    for name in ('activeDecisionRefs', 'unresolvedConflicts', 'resultRefs'):
        retained(name, old[name], new[name])
    for name in ('goal', 'nonGoals'):
        unchanged('checkpoints.' + name, old['checkpoints'][name], new['checkpoints'][name])
    for name in ('consentRefs', 'pendingTasks', 'unknownToolOutcomes', 'readCoverage', 'uncertaintyRefs'):
        retained('checkpoints.' + name, old['checkpoints'][name], new['checkpoints'][name])
    if (new['recentEventCursor']['runId'] != old['recentEventCursor']['runId']
            or new['recentEventCursor']['sequence'] < old['recentEventCursor']['sequence']):
        gaps.append(ContextGap('event_cursor_stale', 'recentEventCursor', 'run changed or cursor moved backwards'))
    skills = {s['skillId']: s for s in new['loadedSkillRefs']}
    reload_ids = list(after.reload_skill_ids())
    for skill in old['loadedSkillRefs']:
        current = skills.get(skill['skillId'])
        if current is None or any(current[k] != skill[k] for k in ('version', 'fullTextRef')):
            gaps.append(ContextGap('skill_ref_changed', 'loadedSkillRefs', skill['skillId']))
            if skill['skillId'] not in reload_ids:
                reload_ids.append(skill['skillId'])
    return RecallReport(tuple(gaps), tuple(reload_ids))
