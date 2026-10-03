"""Fixture offline cho HarnessJobs: không model, không mạng, không tiến trình thật."""
import json
import sqlite3
from types import SimpleNamespace

import pytest

from agentbox.agent_core import harness_jobs
from agentbox.agent_core.harness_jobs import HarnessJobs
from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.memory.session_store import SessionStore


def request(**updates):
    value = {'schema': harness_jobs.JOB_SCHEMA, 'kind': 'model', 'ownership': 'controller'}
    value.update(updates)
    return value


def ref(name='artifact-1', version=1, digest_char='a'):
    return {'artifactId': name, 'version': version, 'contentHash': digest_char * 64}


@pytest.fixture
def repo(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    owner = store.create({'tools': []})['id']
    service = HarnessJobs(store)
    yield store, service, owner
    store.close()


def start(repo, *, invocation='inv-1', capability=None, **updates):
    _, service, owner = repo
    return service.start(owner, request(**updates), capability or {'capabilityId': 'cap-1', 'epoch': 2},
                         invocation)


def child(store, parent, *, role='research', finish=None):
    sid = store.create({'tools': []}, role=role, parent_id=parent)['id']
    store.child_start(sid, parent, 1, 2, role, 'job')
    if finish is not None:
        store.child_finish(sid, finish)
    return sid


def outbox(store):
    return store.db.execute('SELECT * FROM harness_wake_outbox ORDER BY event_seq').fetchall()


def job_row(store, job_id):
    return store.db.execute('SELECT * FROM harness_jobs WHERE job_id=?', (job_id,)).fetchone()


def error(code, call):
    with pytest.raises(ContractError) as exc:
        call()
    assert exc.value.code == code


def test_tables_have_exact_required_columns(repo):
    store, _, _ = repo
    expected = {
        'harness_jobs': {'job_id', 'schema_version', 'controller_id', 'owner_id', 'task_key', 'kind',
                         'ownership', 'revision', 'state', 'capability_epoch', 'admission_json',
                         'checkpoint_ref', 'result_refs_json', 'executor_handle_json',
                         'created_at', 'updated_at', 'closed_at'},
        'harness_wake_outbox': {'wake_id', 'job_id', 'consumer_id', 'event_seq', 'predicate',
                                'status', 'payload_json', 'created_at', 'delivered_at'},
        'harness_wake_cursors': {'consumer_id', 'job_id', 'last_seq', 'updated_at'},
        'harness_wake_locks': {'owner_id', 'consumer_id', 'cursor_json', 'acquired_at', 'expires_at'},
    }
    for table, columns in expected.items():
        actual = {row['name'] for row in store.db.execute(f'PRAGMA table_info({table})')}
        assert actual == columns, table


def test_schema_validation_fails_closed_when_a_column_is_missing(tmp_path):
    store = SessionStore(tmp_path / 'stale.db')
    with store.db:
        store.db.execute('CREATE TABLE harness_jobs(job_id TEXT PRIMARY KEY, schema_version INTEGER)')
    error('JOB_SCHEMA_UNSUPPORTED', lambda: HarnessJobs(store))
    store.close()


def test_schema_validation_covers_the_outbox_table(tmp_path):
    store = SessionStore(tmp_path / 'stale.db')
    with store.db:
        store.db.execute('CREATE TABLE harness_wake_outbox(wake_id TEXT PRIMARY KEY, job_id TEXT)')
    error('JOB_SCHEMA_UNSUPPORTED', lambda: HarnessJobs(store))
    store.close()


def test_unsupported_record_schema_version_fails_closed(repo):
    store, service, _ = repo
    job = start(repo)
    with store.db:
        store.db.execute('UPDATE harness_jobs SET schema_version=99 WHERE job_id=?', (job['jobId'],))
    error('JOB_SCHEMA_UNSUPPORTED', lambda: service.get(job['jobId']))


def test_start_records_controller_ownership_and_capability_epoch(repo):
    _, service, owner = repo
    job = start(repo, taskKey='task-alpha', checkpointRef='checkpoint-1')
    assert job['jobId'].startswith('job-')
    assert job['controllerId'] == owner and job['ownerId'] == owner
    assert job['kind'] == 'model' and job['ownership'] == 'controller' and job['survivesTurn'] is True
    assert job['state'] == 'queued' and job['revision'] == 1
    assert job['capabilityEpoch'] == 2
    assert job['taskKey'] == 'task-alpha' and job['checkpointRef'] == 'checkpoint-1'
    assert job['resultRefs'] == [] and job['closedAt'] is None
    assert job['admission']['invocationId'] == 'inv-1'
    assert job['admission']['capabilityRef'] == {'capabilityId': 'cap-1', 'epoch': 2}
    live = service.get(job['jobId'])
    assert all(live[key] == value for key, value in job.items())
    assert service.open_jobs() == [job]


def test_start_is_idempotent_by_owner_invocation(repo):
    store, service, owner = repo
    first = start(repo)
    replay = service.start(owner, request(), {'capabilityId': 'cap-1', 'epoch': 2}, 'inv-1')
    assert replay == first
    assert store.db.execute('SELECT COUNT(*) FROM harness_jobs').fetchone()[0] == 1
    assert store.db.execute('SELECT COUNT(*) FROM harness_job_invocations').fetchone()[0] == 1


@pytest.mark.parametrize('updates, capability', [
    ({'taskKey': 'other'}, None),
    ({}, {'capabilityId': 'cap-other', 'epoch': 2}),
])
def test_start_rejects_invocation_reuse_with_different_request(repo, updates, capability):
    _, service, owner = repo
    start(repo)
    args = {'capabilityId': 'cap-1', 'epoch': 2} if capability is None else capability
    error('JOB_INVOCATION_CONFLICT', lambda: service.start(owner, request(**updates), args, 'inv-1'))


def test_start_rejects_a_second_open_job_for_the_same_alias(repo):
    _, service, owner = repo
    first = start(repo, taskKey='task-alpha')
    error('JOB_ALIAS_CONFLICT', lambda: service.start(owner, request(taskKey='task-alpha'),
                                                      {'capabilityId': 'cap-2'}, 'inv-2'))
    service.append(first['jobId'], {'kind': 'result', 'state': 'succeeded'})
    reopened = service.start(owner, request(taskKey='task-alpha'), {'capabilityId': 'cap-3'}, 'inv-3')
    assert reopened['state'] == 'queued' and reopened['jobId'] != first['jobId']


def test_start_rejects_unknown_schema_kind_and_ownership(repo):
    _, service, owner = repo
    error('HARNESS_SCHEMA_UNSUPPORTED', lambda: service.start(
        owner, request(schema='boxfox-job-request/2'), {'capabilityId': 'cap-1'}, 'inv-1'))
    error('HARNESS_CONTRACT_INVALID', lambda: service.start(
        owner, request(kind='daemon'), {'capabilityId': 'cap-1'}, 'inv-1'))
    error('HARNESS_CONTRACT_INVALID', lambda: service.start(
        owner, request(ownership='detached'), {'capabilityId': 'cap-1'}, 'inv-1'))
    error('HARNESS_CONTRACT_INVALID', lambda: service.start(
        owner, request(extra='x'), {'capabilityId': 'cap-1'}, 'inv-1'))
    error('HARNESS_CONTRACT_INVALID', lambda: service.start(
        owner, request(), 'not-a-ref', 'inv-1'))


def test_turn_owned_job_does_not_survive_the_turn(repo):
    turn = start(repo, ownership='turn')
    controller = start(repo, invocation='inv-2')
    assert turn['survivesTurn'] is False and controller['survivesTurn'] is True


def test_append_commits_state_and_outbox_in_one_transaction(repo):
    store, service, _ = repo
    job = start(repo)
    seq = service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded',
                                        'resultRefs': [ref()], 'reason': 'done'})
    assert seq == 1
    row = job_row(store, job['jobId'])
    assert row['state'] == 'succeeded' and row['closed_at'] is not None and row['revision'] == 2
    assert json.loads(row['result_refs_json']) == [ref()]
    rows = outbox(store)
    assert len(rows) == 1 and rows[0]['event_seq'] == 1 and rows[0]['status'] == 'pending'
    assert json.loads(rows[0]['payload_json'])['state'] == 'succeeded'
    view = service.get(job['jobId'])
    assert view['state'] == 'succeeded' and view['closedAt'] is not None
    assert view['outputRef'] == ref() and view['reason'] == 'done'


def test_append_rolls_back_state_when_outbox_insert_fails(repo, monkeypatch):
    store, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'progress', 'payload': {'step': 1}})
    before = job_row(store, job['jobId'])
    wake_id = outbox(store)[0]['wake_id']
    monkeypatch.setattr(harness_jobs.uuid, 'uuid4', lambda: SimpleNamespace(hex=wake_id[5:]))
    with pytest.raises(sqlite3.IntegrityError):
        service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded'})
    after = job_row(store, job['jobId'])
    assert (after['state'], after['revision'], after['closed_at']) == (
        before['state'], before['revision'], before['closed_at'])
    assert len(outbox(store)) == 1


def test_append_replay_of_the_same_sequence_has_no_second_effect(repo):
    store, service, _ = repo
    job = start(repo)
    event = {'kind': 'progress', 'eventSeq': 1, 'payload': {'step': 1}}
    assert service.append(job['jobId'], event) == 1
    before = job_row(store, job['jobId'])
    assert service.append(job['jobId'], event) == 1
    after = job_row(store, job['jobId'])
    assert after['revision'] == before['revision'] and after['updated_at'] == before['updated_at']
    assert len(outbox(store)) == 1


def test_append_replay_with_a_different_payload_conflicts(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'result', 'predicate': 'p', 'eventSeq': 1,
                                  'payload': {'a': 1}})
    error('JOB_EVENT_CONFLICT', lambda: service.append(
        job['jobId'], {'kind': 'result', 'predicate': 'p', 'eventSeq': 1, 'payload': {'a': 2}}))
    error('JOB_EVENT_CONFLICT', lambda: service.append(
        job['jobId'], {'kind': 'result', 'predicate': 'other', 'eventSeq': 1}))


def test_append_on_a_closed_job_cannot_rewrite_state(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded'})
    error('JOB_CLOSED', lambda: service.append(job['jobId'], {'kind': 'result', 'state': 'failed'}))
    seq = service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded',
                                        'resultRefs': [ref('late')], 'receiptRef': 'receipt-late'})
    view = service.get(job['jobId'])
    assert seq == 2 and view['state'] == 'succeeded' and view['resultRefs'] == [ref('late')]


def test_wake_worthy_classification():
    assert harness_jobs.wake_worthy({'kind': 'result'}) is True
    assert harness_jobs.wake_worthy({'kind': 'blocker'}) is True
    assert harness_jobs.wake_worthy({'kind': 'owner_subscribed'}) is True
    assert harness_jobs.wake_worthy({'kind': 'heartbeat'}) is False
    assert harness_jobs.wake_worthy({'kind': 'log'}) is False
    assert harness_jobs.wake_worthy({'kind': 'progress'}) is False
    assert harness_jobs.wake_worthy(None) is False
    assert harness_jobs.should_wake({'kind': 'result'}) is True
    assert harness_jobs.should_wake({'kind': 'result', 'intermediate': True}) is False
    assert harness_jobs.should_wake({'kind': 'heartbeat'}) is False


def test_heartbeat_log_and_progress_do_not_wake(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'heartbeat', 'payload': {'at': 1}})
    service.append(job['jobId'], {'kind': 'log', 'payload': {'line': 'x'}})
    service.append(job['jobId'], {'kind': 'progress', 'payload': {'pct': 50}})
    result = service.wait([job['jobId']])
    assert result['events'] == [] and result['ready'] is False
    assert result['jobs'][job['jobId']]['state'] == 'queued'
    view = service.get(job['jobId'])
    assert [item['kind'] for item in view['events']] == ['heartbeat', 'log', 'progress']
    assert all(item['status'] == 'pending' for item in outbox(repo[0]))


def test_intermediate_result_never_wakes(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'result', 'intermediate': True, 'payload': {'partial': True}})
    result = service.wait([job['jobId']])
    assert result['events'] == [] and result['ready'] is False


def test_wait_on_a_closed_job_returns_immediately_with_state_and_refs(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded', 'resultRefs': [ref()]})
    first = service.wait([job['jobId']])
    assert first['ready'] is True
    assert [item['kind'] for item in first['events']] == ['result']
    assert first['events'][0]['resultRefs'] == [ref()]
    assert first['jobs'][job['jobId']]['state'] == 'succeeded'
    assert first['jobs'][job['jobId']]['resultRefs'] == [ref()]
    assert first['cursor'] == 1
    # Sự kiện đã giao một lần: lần chờ sau vẫn trả ngay vì job đã đóng, nhưng không lặp event.
    second = service.wait([job['jobId']], after_seq=first['cursor'])
    assert second['ready'] is True and second['events'] == []
    assert second['jobs'][job['jobId']]['closed'] is True


def test_wait_returns_immediately_when_the_child_is_closed(repo):
    store, service, owner = repo
    sid = child(store, owner)
    job = start(repo, childSessionId=sid)
    service.append(job['jobId'], {'kind': 'heartbeat'})
    first = service.wait([job['jobId']])
    assert first['ready'] is False and first['jobs'][job['jobId']]['closed'] is False
    store.child_finish(sid, 'completed')
    second = service.wait([job['jobId']])
    assert second['ready'] is True
    assert second['jobs'][job['jobId']]['closed'] is True
    assert second['jobs'][job['jobId']]['state'] == 'queued'


def test_wait_mode_all_needs_every_job(repo):
    _, service, _ = repo
    first = start(repo)
    second = start(repo, invocation='inv-2')
    service.append(first['jobId'], {'kind': 'result', 'state': 'succeeded'})
    any_ready = service.wait([first['jobId'], second['jobId']], mode='any')
    assert any_ready['ready'] is True
    all_ready = service.wait([first['jobId'], second['jobId']], mode='all', after_seq=any_ready['cursor'])
    assert all_ready['ready'] is False and all_ready['events'] == []
    service.append(second['jobId'], {'kind': 'result', 'state': 'failed'})
    final = service.wait([first['jobId'], second['jobId']], mode='all', after_seq=any_ready['cursor'])
    assert final['ready'] is True and final['events'][0]['jobId'] == second['jobId']


def test_wait_rejects_bad_arguments(repo):
    _, service, _ = repo
    job = start(repo)
    error('HARNESS_CONTRACT_INVALID', lambda: service.wait([job['jobId']], mode='some'))
    error('HARNESS_CONTRACT_INVALID', lambda: service.wait([]))
    error('HARNESS_CONTRACT_INVALID', lambda: service.wait([job['jobId']], after_seq=-1))


def test_wait_coalesces_one_wake_per_consumer_predicate_batch(repo):
    store, service, _ = repo
    job = start(repo)
    for index in range(3):
        service.append(job['jobId'], {'kind': 'result', 'predicate': 'batch', 'payload': {'i': index}})
    result = service.wait([job['jobId']])
    assert len(result['events']) == 1
    assert result['events'][0]['eventSeq'] == 3 and result['events'][0]['payload']['i'] == 2
    rows = outbox(store)
    assert len(rows) == 3 and all(row['status'] == 'delivered' for row in rows)
    assert all(row['delivered_at'] is not None for row in rows)


def test_wait_delivers_once_and_advances_the_cursor(repo):
    store, service, owner = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'blocker', 'reason': 'needs approval'})
    first = service.wait([job['jobId']])
    assert first['events'][0]['kind'] == 'blocker' and first['cursor'] == 1
    cursor = store.db.execute('SELECT last_seq FROM harness_wake_cursors WHERE consumer_id=? AND job_id=?',
                              (owner, job['jobId'])).fetchone()['last_seq']
    assert cursor == 1
    second = service.wait([job['jobId']], after_seq=first['cursor'])
    assert second['events'] == [] and second['ready'] is False


def test_wait_reports_interrupted_jobs(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'result', 'state': 'interrupted', 'reason': 'lost executor'})
    result = service.wait([job['jobId']])
    assert result['ready'] is True
    assert [item['jobId'] for item in result['interrupted']] == [job['jobId']]
    assert result['interrupted'][0]['state'] == 'interrupted'


def test_subscribe_persists_the_cursor_without_rewinding(repo):
    store, service, owner = repo
    job = start(repo)
    first = service.subscribe(job['jobId'], owner, predicate='result', after_seq=5)
    assert first['subscriptionId'].startswith('sub-') and first['state'] == 'queued'
    assert first['cursor'] == 5 and first['predicate'] == 'result'
    second = service.subscribe(job['jobId'], owner, after_seq=0)
    assert second['cursor'] == 5 and second['subscriptionId'] == first['subscriptionId']
    row = store.db.execute('SELECT * FROM harness_wake_cursors WHERE consumer_id=? AND job_id=?',
                           (owner, job['jobId'])).fetchone()
    assert row['last_seq'] == 5
    error('JOB_UNKNOWN', lambda: service.subscribe('job-missing', owner))


def test_two_consumers_cannot_hold_one_wake_lock(repo):
    _, service, owner = repo
    first = service.acquire_wake(owner, 'turn-a')
    assert first['reclaimed'] is False and first['expiresAt'] > first['acquiredAt']
    error('JOB_WAKE_LOCKED', lambda: service.acquire_wake(owner, 'turn-b'))


def test_same_consumer_can_refresh_its_wake_lock(repo):
    _, service, owner = repo
    service.acquire_wake(owner, 'turn-a')
    again = service.acquire_wake(owner, 'turn-a')
    assert again['reclaimed'] is False
    error('JOB_WAKE_LOCKED', lambda: service.acquire_wake(owner, 'turn-b'))


def test_stale_wake_lock_can_be_reclaimed(repo):
    _, service, owner = repo
    service.wake_ttl_seconds = -1
    service.acquire_wake(owner, 'turn-a')
    lock = service.acquire_wake(owner, 'turn-b')
    assert lock['reclaimed'] is True and lock['consumerId'] == 'turn-b'


def test_wake_lock_carries_the_consumer_cursor(repo):
    _, service, owner = repo
    job = start(repo)
    service.subscribe(job['jobId'], 'turn-a', after_seq=3)
    lock = service.acquire_wake(owner, 'turn-a')
    assert lock['cursor'] == {job['jobId']: 3}


def test_release_wake_is_idempotent_and_does_not_steal(repo):
    _, service, owner = repo
    service.acquire_wake(owner, 'turn-a')
    assert service.release_wake(owner, 'turn-b')['released'] is False
    assert service.release_wake(owner, 'turn-a')['released'] is True
    assert service.release_wake(owner, 'turn-a')['released'] is False
    assert service.acquire_wake(owner, 'turn-b')['reclaimed'] is False


def test_cancel_is_idempotent_with_receipt_and_new_epoch(repo):
    store, service, _ = repo
    job = start(repo)
    first = service.cancel(job['jobId'], job['revision'], 'user stop')
    assert first['cancelRequested'] is True and first['alreadyRequested'] is False
    assert first['receiptRef'].startswith('receipt-')
    assert first['capabilityEpoch'] == job['capabilityEpoch'] + 1
    second = service.cancel(job['jobId'], job['revision'], 'user stop again')
    assert second['alreadyRequested'] is True and second['receiptRef'] == first['receiptRef']
    assert second['revision'] == first['revision'] and second['capabilityEpoch'] == first['capabilityEpoch']
    assert len(outbox(store)) == 1
    row = job_row(store, job['jobId'])
    assert row['state'] == 'queued' and row['closed_at'] is None


def test_cancel_never_claims_a_process_is_stopped(repo):
    _, service, _ = repo
    job = start(repo, kind='process', executor={'executorId': 'exec-1', 'pid': 4242})
    service.cancel(job['jobId'], job['revision'], 'user stop')
    view = service.get(job['jobId'])
    assert view['state'] == 'queued' and view['closedAt'] is None
    assert view['processState'] is None and view['exitCode'] is None
    assert view['controlState'] == 'cancel_requested'
    assert view['controlReceiptRef'].startswith('receipt-')
    assert view['executorHandle'] == {'executorId': 'exec-1', 'pid': 4242}


def test_late_completion_after_cancel_stores_the_receipt_without_succeeding(repo):
    store, service, _ = repo
    job = start(repo)
    service.cancel(job['jobId'], job['revision'], 'user stop')
    late_event = {'kind': 'result', 'state': 'succeeded', 'resultRefs': [ref('late')],
                  'reason': 'finished anyway'}
    seq = service.append(job['jobId'], late_event)
    view = service.get(job['jobId'])
    assert view['state'] == 'cancelled' and view['closedAt'] is not None
    assert view['resultRefs'] == [ref('late')]
    assert view['controlState'] == 'cancel_requested'
    late = [item for item in view['events'] if item.get('reportedState') == 'succeeded']
    assert len(late) == 1 and late[0]['state'] == 'cancelled'
    # Producer gửi lại đúng event đó (kèm seq cũ) không có tác dụng thứ hai.
    assert service.append(job['jobId'], dict(late_event, eventSeq=seq)) == seq
    assert len(outbox(store)) == 2
    assert service.open_jobs() == []
    assert store.db.execute('SELECT COUNT(*) FROM harness_jobs').fetchone()[0] == 1


def test_cancel_rejects_a_closed_job(repo):
    _, service, _ = repo
    job = start(repo)
    service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded'})
    error('JOB_CLOSED', lambda: service.cancel(job['jobId'], 2, 'too late'))


def test_cancel_checks_the_expected_revision(repo):
    _, service, _ = repo
    job = start(repo)
    error('JOB_REVISION_CONFLICT', lambda: service.cancel(job['jobId'], 99, 'stop'))


def test_reconcile_interrupts_a_model_job_without_a_confirmed_executor(repo):
    store, service, _ = repo
    job = start(repo)
    outcome = service.reconcile()
    assert outcome['scanned'] == 1 and outcome['spawned'] == 0
    assert outcome['interrupted'] == [job['jobId']]
    view = service.get(job['jobId'])
    assert view['state'] == 'interrupted' and view['closedAt'] is not None
    assert 'unconfirmed' in view['reason']
    assert service.open_jobs() == []
    assert store.db.execute('SELECT COUNT(*) FROM harness_jobs').fetchone()[0] == 1


def test_reconcile_confirms_a_model_job_whose_child_is_still_open(repo):
    store, service, owner = repo
    sid = child(store, owner)
    job = start(repo, childSessionId=sid)
    outcome = service.reconcile()
    assert outcome['confirmed'] == [job['jobId']] and outcome['interrupted'] == []
    assert service.get(job['jobId'])['state'] == 'queued'
    store.child_finish(sid, 'failed')
    assert service.reconcile()['interrupted'] == [job['jobId']]


def test_reconcile_ends_a_turn_owned_job_even_with_a_live_child(repo):
    store, service, owner = repo
    sid = child(store, owner)
    job = start(repo, ownership='turn', childSessionId=sid)
    outcome = service.reconcile()
    assert outcome['interrupted'] == [job['jobId']] and outcome['confirmed'] == []
    assert service.get(job['jobId'])['state'] == 'interrupted'


def test_reconcile_marks_a_process_job_unknown_without_confirmation(repo):
    _, service, _ = repo
    job = start(repo, kind='process', executor={'executorId': 'exec-1', 'pid': 4242})
    outcome = service.reconcile()
    assert outcome['unknown'] == [job['jobId']]
    assert service.get(job['jobId'])['state'] == 'unknown'


def test_reconcile_marks_a_process_job_unknown_when_the_adapter_says_no(repo):
    store, _, owner = repo
    service = HarnessJobs(store, confirm_executor=lambda handle: False)
    job = service.start(owner, request(kind='process', executor={'executorId': 'exec-1', 'pid': 4242}),
                        {'capabilityId': 'cap-1'}, 'inv-9')
    assert service.reconcile()['unknown'] == [job['jobId']]


def test_reconcile_keeps_a_confirmed_process_job_running(repo):
    store, _, owner = repo
    seen = []

    def confirm(handle):
        seen.append(handle)
        return handle.get('pid') == 4242

    service = HarnessJobs(store, confirm_executor=confirm)
    job = service.start(owner, request(kind='process', executor={'executorId': 'exec-1', 'pid': 4242}),
                        {'capabilityId': 'cap-1'}, 'inv-9')
    outcome = service.reconcile()
    assert outcome['confirmed'] == [job['jobId']] and outcome['unknown'] == []
    assert seen == [{'executorId': 'exec-1', 'pid': 4242}]
    assert service.get(job['jobId'])['state'] == 'queued'


def test_reconcile_never_spawns_a_replacement_process(repo):
    store, service, _ = repo
    job = start(repo, kind='process', executor={'executorId': 'exec-1', 'pid': 4242})
    handle = job_row(store, job['jobId'])['executor_handle_json']
    outcome = service.reconcile()
    assert outcome['spawned'] == 0
    assert store.db.execute('SELECT COUNT(*) FROM harness_jobs').fetchone()[0] == 1
    assert job_row(store, job['jobId'])['executor_handle_json'] == handle
    assert service.reconcile()['scanned'] == 0


def test_reconcile_honours_cancel_requested(repo):
    _, service, _ = repo
    job = start(repo, kind='process', executor={'executorId': 'exec-1', 'pid': 4242})
    service.cancel(job['jobId'], job['revision'], 'user stop')
    outcome = service.reconcile()
    assert outcome['cancelled'] == [job['jobId']] and outcome['unknown'] == []
    assert service.get(job['jobId'])['state'] == 'cancelled'


def test_outbox_and_state_survive_reopening_the_store(tmp_path):
    path = tmp_path / 'sessions.db'
    store = SessionStore(path)
    owner = store.create({'tools': []})['id']
    service = HarnessJobs(store)
    job = service.start(owner, request(), {'capabilityId': 'cap-1'}, 'inv-1')
    service.append(job['jobId'], {'kind': 'result', 'state': 'succeeded', 'resultRefs': [ref()]})
    store.close()
    reopened = SessionStore(path)
    try:
        restored = HarnessJobs(reopened)
        view = restored.get(job['jobId'])
        assert view['state'] == 'succeeded' and view['events'][0]['kind'] == 'result'
        waited = restored.wait([job['jobId']])
        assert waited['ready'] is True and waited['events'][0]['resultRefs'] == [ref()]
        assert restored.open_jobs() == []
    finally:
        reopened.close()


def test_get_pages_events_and_reports_process_fields(repo):
    _, service, _ = repo
    job = start(repo, kind='process', executor={'executorId': 'exec-1', 'pid': 4242,
                                                'processState': 'running', 'exitCode': None})
    service.append(job['jobId'], {'kind': 'progress', 'payload': {'line': 1}})
    service.append(job['jobId'], {'kind': 'log', 'payload': {'line': 2}})
    view = service.get(job['jobId'])
    assert view['processState'] == 'running' and view['exitCode'] is None
    assert [item['eventSeq'] for item in view['events']] == [1, 2]
    assert view['lastEventSeq'] == 2 and view['cursor'] == 2
    page = service.get(job['jobId'], cursor=1)
    assert [item['eventSeq'] for item in page['events']] == [2]
    assert page['lastEventSeq'] == 2
    error('JOB_UNKNOWN', lambda: service.get('job-missing'))


def test_open_jobs_filters_by_owner_and_state(repo):
    store, service, owner = repo
    other = store.create({'tools': []})['id']
    first = start(repo)
    second = service.start(other, request(taskKey='task-b'), {'capabilityId': 'cap-2'}, 'inv-2')
    service.append(second['jobId'], {'kind': 'result', 'state': 'succeeded'})
    assert [item['jobId'] for item in service.open_jobs()] == [first['jobId']]
    assert [item['jobId'] for item in service.open_jobs(owner)] == [first['jobId']]
    assert service.open_jobs(other) == []
    assert service.open_jobs('session-missing') == []


def test_revision_conflict_on_append(repo):
    _, service, _ = repo
    job = start(repo)
    error('JOB_REVISION_CONFLICT', lambda: service.append(
        job['jobId'], {'kind': 'progress'}, expected_revision=99))


def test_child_binding_survives_an_explicit_executor_handle(repo):
    store, service, owner = repo
    sid = child(store, owner)
    job = start(repo, childSessionId=sid, executor={'executorId': 'model-exec-1'})
    assert service.reconcile()['confirmed'] == [job['jobId']]
    store.child_finish(sid, 'completed')
    waited = service.wait([job['jobId']])
    assert waited['ready'] is True and waited['jobs'][job['jobId']]['closed'] is True

