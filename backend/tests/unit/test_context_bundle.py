"""Offline manifest fixtures; no live model recall, permissions or compression."""
import copy
from dataclasses import FrozenInstanceError
import json

import pytest

from agentbox.agent_core.context_bundle import (
    CHECKPOINT_SCHEMA, CONTEXT_SCHEMA, ContextBundle, compare_recall,
)
from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.work_policy import digest


def ref(name, **updates):
    result = {'artifactId': name, 'version': 1, 'contentHash': 'a' * 64,
              'provenance': 'backend', 'status': 'available', 'reason': None}
    result.update(updates)
    return result


def manifest():
    return {
        'schema': CONTEXT_SCHEMA, 'contextEpoch': 3,
        'intentRef': ref('intent'), 'taskContractRef': ref('contract'),
        'activeDecisionRefs': [ref('decision')],
        'capabilityView': {'policyRef': ref('policy'), 'capabilityRef': ref('capability'),
                           'policyEpoch': 7, 'capabilityEpoch': 9},
        'inputManifestRef': ref('inputs'),
        'checkpoints': {
            'schema': CHECKPOINT_SCHEMA, 'goal': 'Inspect uncertain recovery receipts.',
            'nonGoals': ['Do not restart the frozen baseline.'],
            'consentRefs': [ref('consent')],
            'pendingTasks': [{'taskId': 'task-1', 'attemptId': 'attempt-2',
                              'taskContractRef': ref('contract'), 'state': 'interrupted'}],
            'unknownToolOutcomes': [{'invocationId': 'inv-9', 'taskId': 'task-1',
                                     'attemptId': 'attempt-2', 'toolName': 'write_file',
                                     'outcome': 'unknown', 'replaySafety': 'unsafe', 'receiptRef': None}],
            'readCoverage': [
                {'ref': ref('target'), 'purpose': 'target', 'required': True,
                 'coverage': 'full', 'reason': None},
                {'ref': ref('source', provenance='data'), 'purpose': 'supporting',
                 'required': False, 'coverage': 'partial', 'reason': 'Only requested range read.'}],
            'uncertaintyRefs': [ref('uncertainty', provenance='data')],
        },
        'unresolvedConflicts': [ref('conflict')],
        'resultRefs': [ref('draft-result', provenance='data')],
        'recentEventCursor': {'runId': 'run-1', 'sequence': 15},
        'loadedSkillRefs': [{'skillId': 'boxfox-inspect', 'version': 2,
                             'fullTextRef': ref('skill-body', version=2),
                             'loadedContextEpoch': 3, 'bodyContextEpoch': 3}],
        'providerMetadataRef': ref('provider', provenance='data'),
    }


def test_immutable_snapshot_serializer_and_canonical_hash():
    raw = manifest()
    bundle = ContextBundle.parse(raw)
    snapshot = bundle.payload_json
    raw['checkpoints']['nonGoals'].clear()
    bundle.payload['activeDecisionRefs'][0]['version'] = 99
    assert bundle.payload_json == snapshot
    assert bundle.manifest_hash == digest(json.loads(snapshot))
    assert ContextBundle.from_json(snapshot) == bundle
    reordered = dict(reversed(list(manifest().items())))
    assert ContextBundle.parse(reordered).manifest_hash == bundle.manifest_hash
    with pytest.raises(FrozenInstanceError):
        bundle.payload_json = '{}'
    with pytest.raises(TypeError, match='ContextBundle.parse'):
        ContextBundle('{}')


def test_checkpoint_handoff_preserves_registers_but_not_skill_body_presence():
    before = ContextBundle.parse(manifest())
    after = before.checkpoint(4)
    assert before.payload['contextEpoch'] == 3
    assert after.payload['loadedSkillRefs'][0]['bodyContextEpoch'] is None
    report = compare_recall(before, after)
    assert report.preserved
    assert report.reload_skill_ids == ('boxfox-inspect',)
    for field in ('checkpoints', 'capabilityView', 'activeDecisionRefs', 'unresolvedConflicts'):
        assert after.payload[field] == before.payload[field]
    assert any(g.code == 'tool_outcome_unknown' for g in after.manifest_gaps())


@pytest.mark.parametrize('epoch', [3, 2, 0, True, '4', None])
def test_checkpoint_requires_new_explicit_epoch(epoch):
    with pytest.raises(ContractError):
        ContextBundle.parse(manifest()).checkpoint(epoch)


@pytest.mark.parametrize('name', ['goal', 'nonGoals', 'consentRefs', 'pendingTasks',
                                  'unknownToolOutcomes', 'readCoverage', 'uncertaintyRefs'])
def test_erased_checkpoint_fields_report_recall_gaps(name):
    raw = manifest()
    raw['checkpoints'][name] = 'Changed goal' if name == 'goal' else []
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert not report.preserved
    assert any(g.field.startswith('checkpoints.' + name) for g in report.gaps)


@pytest.mark.parametrize('name', ['intentRef', 'taskContractRef', 'inputManifestRef', 'providerMetadataRef'])
@pytest.mark.parametrize('pin', ['version', 'contentHash'])
def test_changed_artifact_versions_and_hashes_invalidate_recall(name, pin):
    raw = manifest()
    raw[name][pin] = 2 if pin == 'version' else 'b' * 64
    if name == 'taskContractRef':
        raw['checkpoints']['pendingTasks'][0]['taskContractRef'] = copy.deepcopy(raw[name])
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert any(g.field == name for g in report.gaps)


@pytest.mark.parametrize('name', ['activeDecisionRefs', 'unresolvedConflicts', 'resultRefs'])
def test_canonical_refs_cannot_disappear_in_handoff(name):
    raw = manifest()
    raw[name].clear()
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert not report.preserved
    assert any(g.field.startswith(name) for g in report.gaps)


@pytest.mark.parametrize('name', ['policyEpoch', 'capabilityEpoch'])
def test_changed_policy_capability_epochs_need_revalidation(name):
    raw = manifest()
    raw['capabilityView'][name] += 1
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert any(g.field == 'capabilityView' for g in report.gaps)


def test_pending_attempt_identity_is_not_replaced_by_completion_or_acceptance():
    raw = manifest()
    raw['checkpoints']['pendingTasks'][0]['attemptId'] = 'attempt-3'
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert not report.preserved
    for value in ('succeeded', 'accepted'):
        raw['checkpoints']['pendingTasks'][0]['state'] = value
        with pytest.raises(ContractError):
            ContextBundle.parse(raw)


@pytest.mark.parametrize('status', ['blocked', 'truncated', 'unknown', 'missing'])
def test_unavailable_refs_stay_visible_with_reason(status):
    raw = manifest()
    raw['resultRefs'][0].update(status=status, reason='Read did not finish.')
    bundle = ContextBundle.parse(raw)
    after = bundle.checkpoint(4)
    assert after.payload['resultRefs'][0]['status'] == status
    assert any(g.code == 'ref_unavailable' and status in g.detail for g in after.manifest_gaps())
    assert compare_recall(bundle, after).preserved


@pytest.mark.parametrize('purpose,required', [('target', True), ('supporting', True), ('supporting', False)])
def test_target_supporting_read_coverage_distinction(purpose, required):
    raw = manifest()
    raw['checkpoints']['readCoverage'] = [
        {'ref': ref('target'), 'purpose': purpose, 'required': required,
         'coverage': 'partial', 'reason': 'Truncated at bound.'}]
    gaps = ContextBundle.parse(raw).manifest_gaps()
    assert any(g.code == 'read_incomplete' for g in gaps) is required


@pytest.mark.parametrize('path', ['intentRef', 'taskContractRef', 'inputManifestRef',
                                  'activeDecisionRefs', 'consentRefs', 'policyRef', 'capabilityRef'])
def test_summary_data_cannot_be_promoted_to_backend_authority(path):
    raw = manifest()
    if path == 'consentRefs':
        target = raw['checkpoints'][path][0]
    elif path == 'activeDecisionRefs':
        target = raw[path][0]
    elif path in ('policyRef', 'capabilityRef'):
        target = raw['capabilityView'][path]
    else:
        target = raw[path]
    target['provenance'] = 'data'
    with pytest.raises(ContractError):
        ContextBundle.parse(raw)


def test_missing_consent_does_not_become_implicit_consent_or_acceptance():
    raw = manifest()
    raw['checkpoints']['consentRefs'] = []
    bundle = ContextBundle.parse(raw).checkpoint(4)
    assert bundle.payload['checkpoints']['consentRefs'] == []
    assert 'accepted' not in bundle.payload_json
    assert not compare_recall(ContextBundle.parse(manifest()), bundle).preserved
    for field in ('approval', 'grants', 'verdict', 'acceptanceState', 'transcript', 'hiddenReasoning', 'secret'):
        injected = bundle.payload
        injected[field] = 'not a supported manifest field'
        with pytest.raises(ContractError):
            ContextBundle.parse(injected)


@pytest.mark.parametrize('body,loaded,epoch', [(None, 3, 3), (2, 3, 3), (3, 3, 4), (4, 3, 4)])
def test_skill_body_presence_is_per_context_and_epoch_change_revalidates(body, loaded, epoch):
    raw = manifest()
    raw['contextEpoch'] = epoch
    raw['loadedSkillRefs'][0].update(bodyContextEpoch=body, loadedContextEpoch=loaded)
    bundle = ContextBundle.parse(raw)
    assert bundle.reload_skill_ids() == ('boxfox-inspect',)
    assert any(g.code == 'skill_reload_required' for g in bundle.manifest_gaps())


def test_explicit_reloaded_skill_metadata_is_required_not_generated():
    before = ContextBundle.parse(manifest())
    raw = before.checkpoint(4).payload
    raw['loadedSkillRefs'][0].update(loadedContextEpoch=4, bodyContextEpoch=4)
    after = ContextBundle.parse(raw)
    assert after.reload_skill_ids() == ()
    assert compare_recall(before, after).preserved
    # The caller must actually check the full body. These fields are data claims.
    assert 'fullText' not in after.payload['loadedSkillRefs'][0]


@pytest.mark.parametrize('change', ['drop', 'version', 'hash'])
def test_skill_changed_pin_or_missing_body_ref_signals_reload(change):
    raw = manifest()
    if change == 'drop':
        raw['loadedSkillRefs'].clear()
    elif change == 'version':
        raw['loadedSkillRefs'][0]['version'] += 1
    else:
        raw['loadedSkillRefs'][0]['fullTextRef']['contentHash'] = 'b' * 64
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert not report.preserved
    assert report.reload_skill_ids == ('boxfox-inspect',)


@pytest.mark.parametrize('change', ['epoch', 'cursor', 'run'])
def test_stale_epoch_cursor_and_cross_run_handoff_are_explicit_gaps(change):
    raw = manifest()
    if change == 'epoch':
        raw['contextEpoch'] = 2
        raw['loadedSkillRefs'] = []
    elif change == 'cursor':
        raw['recentEventCursor']['sequence'] = 14
    else:
        raw['recentEventCursor']['runId'] = 'foreign-run'
    report = compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw))
    assert any(g.code in ('context_epoch_stale', 'event_cursor_stale') for g in report.gaps)


def test_new_decisions_and_event_progress_do_not_erase_existing_recall():
    raw = manifest()
    raw['activeDecisionRefs'].append(ref('new-decision'))
    raw['recentEventCursor']['sequence'] = 16
    assert compare_recall(ContextBundle.parse(manifest()), ContextBundle.parse(raw)).preserved


@pytest.mark.parametrize('mutation', [
    lambda x: x.update(schema='boxfox-context-bundle/2'),
    lambda x: x.update(contextEpoch=True),
    lambda x: x['intentRef'].update(version=True),
    lambda x: x['intentRef'].update(contentHash='short'),
    lambda x: x['intentRef'].pop('version'),
    lambda x: x['intentRef'].update(status='blocked', reason=None),
    lambda x: x['intentRef'].update(provenance='summary'),
    lambda x: x['checkpoints'].update(schema='unknown'),
    lambda x: x['checkpoints']['readCoverage'][0].update(required=False),
    lambda x: x['loadedSkillRefs'][0].update(bodyContextEpoch=4),
    lambda x: x['loadedSkillRefs'][0].update(fullText='No stored body allowed'),
    lambda x: x['recentEventCursor'].update(sequence=True),
    lambda x: x['activeDecisionRefs'].append(copy.deepcopy(x['activeDecisionRefs'][0])),
    lambda x: x['loadedSkillRefs'].append(copy.deepcopy(x['loadedSkillRefs'][0])),
    lambda x: x['checkpoints']['unknownToolOutcomes'][0].update(outcome='success'),
    lambda x: x['checkpoints']['unknownToolOutcomes'][0].update(replaySafety='safe'),
])
def test_strict_schema_pins_reasons_types_and_no_unsafe_replay_promotion(mutation):
    raw = manifest()
    mutation(raw)
    with pytest.raises(ContractError):
        ContextBundle.parse(raw)


@pytest.mark.parametrize('raw', ['{}', '{', 'null', '{"schema":"old","schema":"new"}'])
def test_json_parser_rejects_malformed_missing_and_duplicate_fields(raw):
    with pytest.raises(ContractError):
        ContextBundle.from_json(raw)


@pytest.mark.parametrize('field,value', [('contentHash', 'b' * 64), ('provenance', 'data')])
def test_one_artifact_version_cannot_have_conflicting_hash_or_source(field, value):
    raw = manifest()
    raw['resultRefs'] = [ref('target', **{field: value})]
    with pytest.raises(ContractError, match='conflicting hash/provenance'):
        ContextBundle.parse(raw)


def test_existing_conflict_is_visible_even_when_its_ref_is_available():
    bundle = ContextBundle.parse(manifest()).checkpoint(4)
    assert any(g.code == 'conflict_unresolved' and g.detail == 'conflict'
               for g in bundle.manifest_gaps())
