"""Offline H1 input contracts: no model calls, admission, grants or scheduler."""
import copy
from dataclasses import FrozenInstanceError

import pytest

from agentbox.agent_core.orchestration_contracts import (
    ACCEPTANCE_STATES, ARTIFACT_STATES, TASK_SCHEMA, TASK_STATES, ContractError,
    TaskContract, input_ref, revision,
)
from agentbox.agent_core.work_policy import digest


def request(**updates):
    value = {
        'schema': TASK_SCHEMA, 'taskId': 'inspect-recovery', 'invocationId': 'inv-1',
        'role': 'explore', 'goal': 'Find durable tool receipts.', 'intent': 'analysis',
        'mode': 'read_only', 'inputs': [],
        'scope': {'read': ['backend/src'], 'write': [], 'externalSources': 'none'},
        'deliverable': {'kind': 'knowledge', 'format': 'markdown',
                        'evidence': ['file_line'], 'acceptance': ['Cite the code path.']},
        'dependsOn': [], 'budget': {'allocationPolicy': 'inherited'},
    }
    value.update(updates)
    return value


def test_snapshot_severs_caller_and_reader_mutations():
    raw = request(inputs=[{'artifactId': 'wa-1', 'version': 1, 'contentHash': 'a' * 64}])
    contract = TaskContract.parse(raw)
    before = contract.payload_json, contract.contract_hash
    raw['scope']['read'].append('private')
    raw['inputs'][0]['version'] = 2
    contract.payload['scope']['read'].append('another')
    assert (contract.payload_json, contract.contract_hash) == before
    assert contract.contract_hash == digest(contract.payload)
    with pytest.raises(FrozenInstanceError):
        contract.payload_json = '{}'
    with pytest.raises(TypeError, match='TaskContract.parse'):
        TaskContract('{}')


def test_default_wait_is_normalized_before_digest():
    implicit = TaskContract.parse(request())
    explicit = TaskContract.parse(request(wait=False))
    reordered = dict(reversed(list(request(wait=False).items())))
    assert implicit.payload['wait'] is False
    assert implicit.contract_hash == explicit.contract_hash == TaskContract.parse(reordered).contract_hash


@pytest.mark.parametrize('field,value', [
    ('schema', None), ('schema', 'boxfox-task-contract/2'), ('role', 'orchestrator'),
    ('role', []), ('intent', None), ('intent', 'mixed'), ('mode', 'legacy'), ('mode', {}),
    ('taskId', '../task'), ('taskId', 'task/child'), ('taskId', 'a' * 121),
    ('invocationId', ''), ('invocationId', True), ('invocationId', 'x/y'),
    ('goal', ''), ('goal', False), ('goal', 'x\x00y'), ('wait', 1), ('wait', None),
    ('inputs', {}), ('inputs', [{'artifactId': 'wa', 'version': 1}]),
    ('dependsOn', ['inspect-recovery']), ('dependsOn', ['upstream', 'upstream']),
    ('dependsOn', ['../parent']), ('budget', {'allocationPolicy': 'unlimited'}),
    ('budget', {'allocationPolicy': 'referenced'}),
    ('budget', {'allocationPolicy': 'inherited', 'usd': 0}),
])
def test_invalid_model_fields_fail_closed(field, value):
    with pytest.raises(ContractError):
        TaskContract.parse(request(**{field: value}))


@pytest.mark.parametrize('backend_field', [
    'ownerId', 'runId', 'taskKey', 'revision', 'attemptId', 'sessionId',
    'capabilityEpoch', 'effectiveScope', 'approvalRef', 'state', 'acceptanceState',
])
def test_model_cannot_supply_backend_authority_fields(backend_field):
    with pytest.raises(ContractError):
        TaskContract.parse(request(**{backend_field: 'forged'}))


@pytest.mark.parametrize('intent', ['analysis', 'plan', 'design'])
def test_nonimplementation_intent_cannot_request_write_mode(intent):
    with pytest.raises(ContractError):
        TaskContract.parse(request(intent=intent, mode='workspace_write'))
    raw = request(intent=intent)
    raw['scope']['write'] = ['backend/src']
    with pytest.raises(ContractError):
        TaskContract.parse(raw)


def test_implementation_write_is_only_a_request_not_a_permission():
    raw = request(intent='implementation', role='build', mode='workspace_write')
    raw['scope']['write'] = ['backend/src']
    contract = TaskContract.parse(raw)
    assert contract.payload['scope']['write'] == ['backend/src']
    assert 'approvalRef' not in contract.payload
    assert 'effectiveScope' not in contract.payload
    assert 'ownerId' not in contract.payload


@pytest.mark.parametrize('path', ['/etc', '../host', 'a/../b', 'a//b', 'C:\\Users', 'a\\b'])
def test_task_selectors_are_not_host_roots_or_traversal(path):
    raw = request()
    raw['scope']['read'] = [path]
    with pytest.raises(ContractError):
        TaskContract.parse(raw)


@pytest.mark.parametrize('field,value', [
    ('evidence', []), ('acceptance', []), ('kind', None), ('format', ''),
])
def test_deliverable_needs_evidence_and_acceptance(field, value):
    raw = request()
    raw['deliverable'][field] = value
    with pytest.raises(ContractError):
        TaskContract.parse(raw)


@pytest.mark.parametrize('number', [True, False, 0, -1, 1.0, '1', None])
def test_revision_does_not_coerce_boolean_string_or_float(number):
    with pytest.raises(ContractError):
        revision(number)
    with pytest.raises(ContractError):
        input_ref({'artifactId': 'wa', 'version': number, 'contentHash': 'a' * 64})


def test_refs_bind_version_and_hash_but_do_not_claim_resolution():
    ref = {'artifactId': 'wa', 'version': 1, 'contentHash': 'f' * 64, 'ownerId': 'owner-1'}
    assert input_ref(ref) == ref
    raw = request(inputs=[ref, copy.deepcopy(ref)])
    with pytest.raises(ContractError, match='duplicate artifact versions'):
        TaskContract.parse(raw)
    with pytest.raises(ContractError):
        input_ref(dict(ref, contentHash='not-a-hash'))


def test_unsupported_schema_has_specific_code():
    with pytest.raises(ContractError) as error:
        TaskContract.parse(request(schema='boxfox-task-contract/999'))
    assert error.value.code == 'HARNESS_SCHEMA_UNSUPPORTED'
    assert error.value.field == 'schema'


def test_every_required_field_stays_explicit():
    for field in request():
        raw = request()
        del raw[field]
        with pytest.raises(ContractError):
            TaskContract.parse(raw)


def test_lifecycle_acceptance_and_artifact_states_are_distinct():
    assert 'succeeded' in TASK_STATES and 'accepted' not in TASK_STATES
    assert 'accepted' in ACCEPTANCE_STATES and 'succeeded' not in ACCEPTANCE_STATES
    assert 'finalized' in ARTIFACT_STATES and 'cancel_requested' not in TASK_STATES
