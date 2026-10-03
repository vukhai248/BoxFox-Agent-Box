"""Self-contained offline SQLite H1 fixtures. No model, provider or browser."""
import copy
from pathlib import Path
import sqlite3

import pytest

from agentbox.agent_core.orchestration_contracts import ContractError, TASK_SCHEMA, TaskContract
from agentbox.agent_core.task_service import TaskService
from agentbox.memory.session_store import SessionStore


def request(**updates):
    value = {'schema': TASK_SCHEMA, 'taskId': 'inspect-recovery', 'invocationId': 'inv-create',
             'role': 'explore', 'goal': 'Find durable execution receipts.', 'intent': 'analysis',
             'mode': 'read_only', 'inputs': [],
             'scope': {'read': ['backend/src'], 'write': [], 'externalSources': 'none'},
             'deliverable': {'kind': 'knowledge', 'format': 'markdown', 'evidence': ['file_line'],
                             'acceptance': ['Cite the canonical closer.']},
             'dependsOn': [], 'budget': {'allocationPolicy': 'inherited'}}
    value.update(updates)
    return value


@pytest.fixture
def repo(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    owner = store.create({'skills': []})['id']
    foreign = store.create({'skills': []})['id']
    runs = {'run-1': {'runId': 'run-1', 'sessionId': owner},
            'run-2': {'runId': 'run-2', 'sessionId': owner},
            'foreign-run': {'runId': 'foreign-run', 'sessionId': foreign}}
    calls = []

    def resolve(owner_id, run_id):
        calls.append((owner_id, run_id))
        return copy.deepcopy(runs.get(run_id))

    service = TaskService(store, resolve)
    yield store, service, owner, foreign, runs, calls
    store.close()


def create(repo, **updates):
    _, service, owner, _, _, _ = repo
    return service.create(owner, 'run-1', request(**updates), controller_id=owner)


def child(repo, *, owner=None, role='explore'):
    store, _, root, _, _, _ = repo
    owner = root if owner is None else owner
    sid = store.create({'skills': []}, role=role, parent_id=owner)['id']
    store.child_start(sid, owner, 1, 2, role, 'Find receipts')
    return sid


def attempt(repo, task, sid, *, invocation='inv-attempt', admission='admission-1', expected=None,
            epoch=1):
    _, service, owner, _, _, _ = repo
    return service.record_attempt(owner, 'run-1', task['taskKey'], invocation_id=invocation,
                                  expected_revision=task['revision'] if expected is None else expected,
                                  session_id=sid, admission_id=admission, capability_epoch=epoch)


def send(repo, task, **updates):
    _, service, owner, _, _, _ = repo
    args = {'invocation_id': 'inv-send', 'message_id': 'message-1', 'sender_id': owner,
            'expected_revision': task['revision'], 'kind': 'information', 'body': 'Here is new evidence.'}
    args.update(updates)
    return service.send(owner, 'run-1', task['taskKey'], **args)


def error(code, call):
    with pytest.raises(ContractError) as exc:
        call()
    assert exc.value.code == code


def counts(store):
    return {table: store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
            for table in ('harness_tasks', 'harness_task_attempts', 'harness_task_messages', 'harness_invocations')}


def test_create_normalized_immutable_idempotent_snapshot(repo):
    store, service, owner, _, _, _ = repo
    raw = request()
    first = service.create(owner, 'run-1', raw, controller_id=owner)
    explicit = request(wait=False)
    assert service.create(owner, 'run-1', explicit, controller_id=owner) == first
    assert first['contractHash'] == TaskContract.parse(raw).contract_hash
    assert first['state'] == 'queued' and first['acceptanceState'] == 'unverified'
    raw['goal'] = 'Changed by caller'
    first['contract']['goal'] = 'Changed by reader'
    assert service.get(owner, 'run-1', first['taskKey'])['contract']['goal'] == request()['goal']
    assert counts(store) == {'harness_tasks': 1, 'harness_task_attempts': 0,
                             'harness_task_messages': 0, 'harness_invocations': 1}


@pytest.mark.parametrize('updates', [
    {'goal': 'Different goal'}, {'taskId': 'another-alias'}, {'wait': True},
    {'inputs': [{'artifactId': 'artifact-1', 'version': 1, 'contentHash': 'a' * 64}]},
])
def test_invocation_reuse_different_contract_rejected(repo, updates):
    create(repo)
    error('TASK_INVOCATION_CONFLICT', lambda: create(repo, **updates))
    assert counts(repo[0])['harness_tasks'] == 1


def test_request_hash_binds_run_controller_and_action(repo):
    _, service, owner, _, _, _ = repo
    task = create(repo)
    error('TASK_INVOCATION_CONFLICT', lambda: service.create(owner, 'run-2', request(), controller_id=owner))
    error('TASK_INVOCATION_CONFLICT', lambda: service.create(owner, 'run-1', request(), controller_id='controller-2'))
    error('TASK_INVOCATION_CONFLICT', lambda: send(repo, task, invocation_id='inv-create'))


def test_alias_unique_per_run_and_invocation_atomic_rollback(repo):
    store, service, owner, _, _, _ = repo
    create(repo)
    error('TASK_ALIAS_CONFLICT', lambda: create(repo, invocationId='inv-new'))
    assert counts(store)['harness_invocations'] == 1
    other = service.create(owner, 'run-2', request(invocationId='inv-other'), controller_id=owner)
    assert other['runId'] == 'run-2'


def test_mandatory_resolver_no_default_allow(repo):
    store, _, owner, _, _, _ = repo
    with pytest.raises(TypeError):
        TaskService(store)
    with pytest.raises(TypeError, match='mandatory'):
        TaskService(store, None)
    for result in (None, True, {}, {'runId': 'run-1'}, {'runId': 'wrong', 'sessionId': owner}):
        service = TaskService(store, lambda *_: result)
        error('TASK_RUN_UNKNOWN' if result is None or not isinstance(result, dict)
              or result.get('runId') != 'run-1' else 'TASK_OWNER_MISMATCH',
              lambda: service.list(owner, 'run-1'))


def test_all_operations_recheck_canonical_owner_even_cached(repo):
    store, service, owner, foreign, runs, calls = repo
    task = create(repo)
    sid = child(repo)
    recorded = attempt(repo, task, sid)
    operations = [lambda: service.create(owner, 'run-1', request(), controller_id=owner),
                  lambda: service.get(owner, 'run-1', task['taskKey']),
                  lambda: service.list(owner, 'run-1'),
                  lambda: send(repo, task),
                  lambda: service.messages(owner, 'run-1', task['taskKey']),
                  lambda: service.attempts(owner, 'run-1', task['taskKey']),
                  lambda: attempt(repo, task, sid),
                  lambda: service.project_attempt(owner, 'run-1', task['taskKey'], recorded['attemptId']),
                  lambda: service.abandon(owner, 'run-1', task['taskKey'], invocation_id='inv-abandon',
                                          expected_revision=2, reason='No longer needed')]
    before = counts(store)
    runs['run-1']['sessionId'] = foreign
    for operation in operations:
        n = len(calls)
        error('TASK_OWNER_MISMATCH', operation)
        assert len(calls) == n + 1
    assert counts(store) == before


def test_foreign_task_owner_and_run_rejected(repo):
    _, service, owner, foreign, _, _ = repo
    task = create(repo)
    error('TASK_OWNER_MISMATCH', lambda: service.get(foreign, 'foreign-run', task['taskKey']))
    error('TASK_OWNER_MISMATCH', lambda: service.get(owner, 'run-2', task['taskKey']))
    error('TASK_RUN_UNKNOWN', lambda: service.list(owner, 'missing-run'))


def test_persistent_message_receipt_not_delivery_or_scope_elevation(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    before = service.get(owner, 'run-1', task['taskKey'])
    receipt = send(repo, task, kind='scope_proposal', body='Please consider implementation.',
                   input_refs=[{'artifactId': 'artifact-1', 'version': 1, 'contentHash': 'a' * 64}])
    assert receipt['deliveryState'] == 'received' and receipt['consumedAt'] is None
    assert service.get(owner, 'run-1', task['taskKey']) == before
    assert store.db.execute('SELECT COUNT(*) FROM child_deliveries').fetchone()[0] == 0
    assert service.messages(owner, 'run-1', task['taskKey'])['items'] == [receipt]
    assert send(repo, task, kind='scope_proposal', body='Please consider implementation.',
                input_refs=receipt['payload']['inputRefs']) == receipt
    assert send(repo, task, invocation_id='inv-message-retry', kind='scope_proposal',
                body='Please consider implementation.', input_refs=receipt['payload']['inputRefs']) == receipt
    error('TASK_MESSAGE_CONFLICT', lambda: send(repo, task, invocation_id='inv-conflict', body='Different'))
    assert counts(store)['harness_task_messages'] == 1


@pytest.mark.parametrize('updates', [
    {'kind': 'auto_resume'}, {'kind': []}, {'message_id': '../message'}, {'expected_revision': True},
    {'body': ''}, {'body': 'x' * 16001}, {'input_refs': [{'artifactId': 'bad'}]},
])
def test_message_validation(repo, updates):
    task = create(repo)
    with pytest.raises(ContractError):
        send(repo, task, **updates)
    assert counts(repo[0])['harness_task_messages'] == 0


def test_stale_revision_rejected_without_mutation(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    attempt(repo, task, child(repo))
    before = counts(store)
    error('TASK_REVISION_CONFLICT', lambda: send(repo, task))
    error('TASK_REVISION_CONFLICT', lambda: service.abandon(owner, 'run-1', task['taskKey'],
                                                           invocation_id='inv-abandon', expected_revision=1,
                                                           reason='Changed priority'))
    error('TASK_REVISION_CONFLICT', lambda: attempt(repo, task, child(repo), admission='admission-2',
                                                    invocation='inv-attempt-2'))
    assert counts(store) == before


@pytest.mark.parametrize('binding', ['missing', 'foreign', 'role'])
def test_attempt_canonical_child_binding(repo, binding):
    task = create(repo)
    sid = 'missing-child' if binding == 'missing' else child(
        repo, owner=repo[3] if binding == 'foreign' else repo[2], role='review' if binding == 'role' else 'explore')
    error('TASK_CHILD_UNKNOWN' if binding == 'missing' else 'TASK_CHILD_BINDING',
          lambda: attempt(repo, task, sid))
    assert counts(repo[0])['harness_task_attempts'] == 0


def test_one_active_attempt_and_new_admission_per_attempt(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    assert attempt(repo, task, sid) == first
    current = service.get(owner, 'run-1', task['taskKey'])
    error('TASK_ATTEMPT_CONFLICT', lambda: attempt(repo, current, child(repo),
                                                  invocation='inv-second', admission='admission-2'))
    assert counts(store)['harness_task_attempts'] == 1
    store.child_close_once(sid, 'completed')
    service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    current = service.get(owner, 'run-1', task['taskKey'])
    error('TASK_ATTEMPT_CONFLICT', lambda: attempt(repo, current, child(repo),
                                                  invocation='inv-reused-admission', admission='admission-1'))


def test_child_completion_without_grant_never_becomes_accepted(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    assert store.child_close_once(sid, 'completed') is not None
    refs = [{'artifactId': 'artifact-1', 'version': 1, 'contentHash': 'a' * 64}]
    projected = service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'], result_refs=refs)
    assert projected['status'] == 'succeeded' and projected['resultRefs'] == refs
    current = service.get(owner, 'run-1', task['taskKey'])
    assert current['state'] == 'succeeded' and current['acceptanceState'] == 'unverified'
    assert service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId']) == projected
    assert service.get(owner, 'run-1', task['taskKey'])['revision'] == current['revision']
    assert store.child_close_once(sid, 'failed') is None, 'projection did not steal/reopen the closer'
    assert store.db.execute('SELECT COUNT(*) FROM plan_verifications').fetchone()[0] == 0
    error('TASK_ATTEMPT_CLOSED', lambda: service.project_attempt(owner, 'run-1', task['taskKey'],
                                                               first['attemptId'], result_refs=[]))


def test_waiting_projection_is_explicit_and_read_only(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_wait(sid, ['role:review'], 123)
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'running'
    assert service.attempts(owner, 'run-1', task['taskKey'])['items'][0]['status'] == 'running'
    projected = service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    assert projected['status'] == 'waiting_input' and store.child(sid)['status'] == 'started'
    store.child_wait(sid, [], None)
    assert service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])['status'] == 'running'


def test_reused_legacy_session_creates_new_attempt_not_reopening_old(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_close_once(sid, 'partial', reason='BUDGET')
    closed = service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    with store.db:
        store.db.execute("UPDATE children SET status='started', finished=NULL, reason=NULL, started=started+1, "
                         'parent_turn=0 WHERE session_id=?', (sid,))
    current = service.get(owner, 'run-1', task['taskKey'])
    second = attempt(repo, current, sid, invocation='inv-resume', admission='admission-2')
    assert first['attemptId'] != second['attemptId']
    assert (first['attemptSeq'], second['attemptSeq']) == (1, 2)
    assert first['sessionId'] == second['sessionId'] == sid
    assert first['contractHash'] == second['contractHash'] == task['contractHash']
    assert second['provenance']['parentTurn'] == 0
    assert service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId']) == closed
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'running'
    assert len(service.attempts(owner, 'run-1', task['taskKey'])['items']) == 2


def test_missed_close_projection_never_projects_reopened_child_onto_old_attempt(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_close_once(sid, 'partial')
    with store.db:
        store.db.execute("UPDATE children SET status='started', finished=NULL, started=started+1"
                         ' WHERE session_id=?', (sid,))
    error('TASK_ATTEMPT_BINDING',
          lambda: service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId']))
    current = service.get(owner, 'run-1', task['taskKey'])
    error('TASK_ATTEMPT_CONFLICT',
          lambda: attempt(repo, current, sid, invocation='inv-resume', admission='admission-2'))
    assert service.get(owner, 'run-1', task['taskKey'])['acceptanceState'] == 'unverified'


def test_terminal_message_and_abandon_have_no_execution_effects(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    current = service.get(owner, 'run-1', task['taskKey'])
    abandoned = service.abandon(owner, 'run-1', task['taskKey'], invocation_id='inv-abandon',
                                expected_revision=current['revision'], reason='Goal no longer needed')
    assert abandoned['state'] == 'abandoned' and abandoned['controlState'] == 'cancel_requested'
    assert store.child(sid)['status'] == 'started'
    assert service.abandon(owner, 'run-1', task['taskKey'], invocation_id='inv-abandon',
                           expected_revision=current['revision'], reason='Goal no longer needed') == abandoned
    store.child_close_once(sid, 'completed')
    service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    current = service.get(owner, 'run-1', task['taskKey'])
    send(repo, current, kind='clarification')
    assert store.child(sid)['status'] == 'completed'
    assert counts(store)['harness_task_attempts'] == 1
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'abandoned'
    error('TASK_ABANDONED', lambda: attempt(repo, current, child(repo),
                                           invocation='inv-followup', admission='admission-2'))


@pytest.mark.parametrize('table,reader', [
    ('harness_tasks', 'get'), ('harness_task_attempts', 'attempts'),
    ('harness_task_messages', 'messages'), ('harness_invocations', 'create'),
])
def test_persisted_unsupported_schema_fails_closed(repo, table, reader):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    attempt(repo, task, child(repo))
    send(repo, task, expected_revision=2)
    with store.db:
        store.db.execute(f'UPDATE {table} SET schema_version=999')
    before = counts(store)
    operation = (lambda: create(repo)) if reader == 'create' else (
        lambda: getattr(service, reader)(owner, 'run-1', task['taskKey']))
    error('TASK_SCHEMA_UNSUPPORTED', operation)
    assert counts(store) == before


def test_cached_attempt_and_message_do_not_bypass_schema_checks(repo):
    store, _, _, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    attempt(repo, task, sid)
    send(repo, task, expected_revision=2)
    with store.db:
        store.db.execute('UPDATE harness_task_attempts SET schema_version=2')
        store.db.execute('UPDATE harness_task_messages SET schema_version=2')
    error('TASK_SCHEMA_UNSUPPORTED', lambda: attempt(repo, task, sid))
    error('TASK_SCHEMA_UNSUPPORTED', lambda: send(repo, task, expected_revision=2))


def test_contract_tampering_fails_closed(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    with store.db:
        store.db.execute("UPDATE harness_tasks SET contract_hash=?", ('b' * 64,))
    error('TASK_CONTRACT_CORRUPT', lambda: service.get(owner, 'run-1', task['taskKey']))


def test_bounded_keyset_pages_only_metadata(repo):
    _, service, owner, _, _, _ = repo
    keys = {create(repo, taskId=f'task-{i}', invocationId=f'inv-{i}')['taskKey'] for i in range(7)}
    after, seen = None, []
    while True:
        page = service.list(owner, 'run-1', after=after, limit=2)
        assert all('contract' not in row and 'messages' not in row and 'transcript' not in row for row in page['items'])
        seen.extend(row['taskKey'] for row in page['items'])
        after = page['nextAfter']
        if not page['hasMore']:
            break
    assert seen == sorted(keys) and len(seen) == len(set(seen))
    assert service.list(owner, 'run-1', state='running')['items'] == []
    task = service.get(owner, 'run-1', seen[0])
    for i in range(5):
        send(repo, task, message_id=f'message-{i}', invocation_id=f'send-{i}')
    first = service.messages(owner, 'run-1', task['taskKey'], limit=3)
    second = service.messages(owner, 'run-1', task['taskKey'], after=first['nextAfter'], limit=3)
    assert [r['messageId'] for r in first['items'] + second['items']] == [f'message-{i}' for i in range(5)]
    assert first['hasMore'] and not second['hasMore']


@pytest.mark.parametrize('limit', [0, -1, 101, True, '2'])
def test_invalid_page_bounds(repo, limit):
    _, service, owner, _, _, _ = repo
    task = create(repo)
    for operation in (lambda: service.list(owner, 'run-1', limit=limit),
                      lambda: service.messages(owner, 'run-1', task['taskKey'], limit=limit),
                      lambda: service.attempts(owner, 'run-1', task['taskKey'], limit=limit)):
        with pytest.raises(ContractError):
            operation()


def test_crash_gap_reopen_is_read_only_then_explicit_projection(repo):
    store, service, owner, _, runs, _ = repo
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_close_once(sid, 'failed', reason='RESTART')
    before = counts(store)
    contract_before = tuple(store.db.execute('SELECT contract_hash,contract_json FROM harness_tasks').fetchone())
    reopened = SessionStore(Path(path))
    try:
        again = TaskService(reopened, lambda _, run_id: runs.get(run_id))
        assert again.get(owner, 'run-1', task['taskKey'])['state'] == 'running'
        assert again.attempts(owner, 'run-1', task['taskKey'])['items'][0]['closedAt'] is None
        assert counts(reopened) == before
        result = again.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
        assert result['status'] == 'failed' and result['reason'] == 'RESTART'
        assert again.get(owner, 'run-1', task['taskKey'])['acceptanceState'] == 'unverified'
        after = reopened.db.execute('SELECT contract_hash,contract_json FROM harness_tasks').fetchone()
        assert tuple(after) == contract_before
    finally:
        reopened.close()


def test_old_database_reopen_preserves_history_and_never_creates_grants(tmp_path):
    path = tmp_path / 'legacy.db'
    db = sqlite3.connect(path)
    db.executescript('''
        CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_id TEXT, role TEXT NOT NULL,
            config TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]',
            status TEXT NOT NULL DEFAULT 'idle', updated REAL NOT NULL);
        CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
            kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, session_id TEXT NOT NULL,
            messages TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL);
        CREATE TABLE work_grants (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL, doc TEXT NOT NULL);
        CREATE TABLE plan_verifications (identity TEXT NOT NULL, version INTEGER NOT NULL,
            verdict TEXT NOT NULL, issues TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '',
            critic_session_id TEXT, critic_answer_chars INTEGER, critic_verdict TEXT,
            created REAL NOT NULL, PRIMARY KEY(identity,version));
        PRAGMA user_version=17;
    ''')
    config, messages = '{ "legacyHash": "unchanged" }', '[ {"role":"user", "content":"old input"} ]'
    grant = '{ "scopeHash": "old-approval-hash", "status": "revoked" }'
    db.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)',
               ('old-owner', None, 'orchestrator', config, messages, 'idle', 1))
    db.execute('INSERT INTO work_grants VALUES(?,?,?,?)', ('grant-old', 'run-old', 'old-owner', grant))
    approval = ('historical-plan-hash', 2, 'ok', '[ "old issue bytes" ]', 'Legacy approval',
                'old-critic', 45, 'ok', 2.5)
    db.execute('INSERT INTO plan_verifications VALUES(?,?,?,?,?,?,?,?,?)', approval)
    db.execute('INSERT INTO events(session_id,kind,payload,created) VALUES(?,?,?,?)',
               ('old-owner', 'notice', '{ "oldHash": "historical" }', 1))
    db.commit()
    db.close()
    for _ in range(2):
        store = SessionStore(path)
        try:
            service = TaskService(store, lambda owner, run: {'runId': run, 'sessionId': 'old-owner'})
            assert service.list('old-owner', 'run-old')['items'] == []
            assert all(count == 0 for count in counts(store).values())
            row = store.db.execute('SELECT config,messages FROM sessions WHERE id=?', ('old-owner',)).fetchone()
            assert (row['config'], row['messages']) == (config, messages)
            assert store.db.execute('SELECT doc FROM work_grants').fetchone()[0] == grant
            assert store.db.execute('SELECT COUNT(*) FROM work_grants').fetchone()[0] == 1
            assert [tuple(row) for row in store.db.execute('SELECT * FROM plan_verifications')] == [approval]
            assert store.db.execute('SELECT payload FROM events').fetchone()[0] == '{ "oldHash": "historical" }'
            assert store.db.execute('PRAGMA user_version').fetchone()[0] == 17
        finally:
            store.close()


@pytest.mark.parametrize('status,outcome', [('partial', 'partial'), ('failed', 'failed'),
                                           ('interrupted', 'interrupted'), ('cancelled', 'cancelled')])
def test_terminal_child_outcome_is_not_acceptance(repo, status, outcome):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    recorded = attempt(repo, task, sid)
    store.child_close_once(sid, status, reason='CANONICAL_REASON')
    projected = service.project_attempt(owner, 'run-1', task['taskKey'], recorded['attemptId'])
    assert projected['status'] == outcome and projected['reason'] == 'CANONICAL_REASON'
    assert service.get(owner, 'run-1', task['taskKey'])['acceptanceState'] == 'unverified'


@pytest.mark.parametrize('status,finished', [('completed', None), ('accepted', 123), ('unknown', 123)])
def test_incomplete_or_unknown_child_receipt_never_projected(repo, status, finished):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    recorded = attempt(repo, task, sid)
    with store.db:
        store.db.execute('UPDATE children SET status=?, finished=? WHERE session_id=?', (status, finished, sid))
    error('TASK_CHILD_NOT_TERMINAL',
          lambda: service.project_attempt(owner, 'run-1', task['taskKey'], recorded['attemptId']))
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'running'


def test_invocation_receipt_failure_rolls_back_data_and_preserves_caller_transaction(repo):
    store, service, owner, _, _, _ = repo
    store.db.executescript('''CREATE TRIGGER fail_task_receipt BEFORE INSERT ON harness_invocations
                             BEGIN SELECT RAISE(ABORT, 'fixture crash before receipt'); END;''')
    with pytest.raises(sqlite3.IntegrityError, match='fixture crash'):
        create(repo)
    assert all(count == 0 for count in counts(store).values())
    store.db.execute('DROP TRIGGER fail_task_receipt')
    store.db.execute('BEGIN IMMEDIATE')
    task = create(repo)
    assert store.db.in_transaction
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'queued'
    store.db.rollback()
    assert all(count == 0 for count in counts(store).values())


def test_unversioned_harness_table_rejected_without_rewriting(tmp_path):
    store = SessionStore(tmp_path / 'unversioned.db')
    try:
        store.db.executescript('CREATE TABLE harness_tasks(task_key TEXT PRIMARY KEY, contract_json TEXT);'
                              "INSERT INTO harness_tasks VALUES('legacy-task','unchanged');")
        error('TASK_SCHEMA_UNSUPPORTED', lambda: TaskService(store, lambda *_: None))
        assert tuple(store.db.execute('SELECT * FROM harness_tasks').fetchone()) == ('legacy-task', 'unchanged')
        assert 'schema_version' not in {r['name'] for r in store.db.execute('PRAGMA table_info(harness_tasks)')}
    finally:
        store.close()


def test_two_connections_duplicate_create_has_one_record_and_same_receipt(repo):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    store, service, owner, _, runs, _ = repo
    other = SessionStore(Path(store.db.execute('PRAGMA database_list').fetchone()['file']))
    barrier = Barrier(2)

    def resolve(_, run_id):
        barrier.wait(timeout=10)
        return runs[run_id]

    service.resolve_run = resolve
    second = TaskService(other, resolve)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(s.create, owner, 'run-1', request(), controller_id=owner)
                       for s in (service, second)]
            results = [f.result(timeout=15) for f in futures]
        assert results[0] == results[1]
        assert counts(store)['harness_tasks'] == counts(store)['harness_invocations'] == 1
    finally:
        other.close()


def test_needs_user_close_projects_and_a_resume_opens_a_new_attempt(repo):
    """The checkpoint/resume flow: a `needs_user` child must project, then admit a fresh attempt."""
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_close_once(sid, 'needs_user', 'Which export format?')
    view = service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    assert view['status'] == 'waiting_input' and view['reason'] == 'Which export format?'
    assert view['closedAt'] is not None
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'waiting_input'
    # A closed snapshot stays immutable even after the canonical child is reopened.
    with store.db:
        store.db.execute("UPDATE children SET status='started', finished=NULL, started=started+1"
                         ' WHERE session_id=?', (sid,))
    assert service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId']) == view
    current = service.get(owner, 'run-1', task['taskKey'])
    second = attempt(repo, current, sid, invocation='inv-resume', admission='admission-2')
    assert second['attemptSeq'] == 2 and second['status'] == 'running'
    assert second['reason'] is None  # a stale close reason must never ride on an open attempt
    assert second['startedAt'] == store.child(sid)['started']
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'running'
    items = service.attempts(owner, 'run-1', task['taskKey'])['items']
    assert {item['status'] for item in items} == {'waiting_input', 'running'}


def test_capability_epoch_must_be_a_positive_integer(repo):
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    for bad in (0, -1, True, 1.0, '1', None):
        error('HARNESS_CONTRACT_INVALID',
              lambda bad=bad: attempt(repo, task, sid, epoch=bad))
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'queued'


def test_two_connections_never_leak_raw_integrity_errors(repo):
    """A second connection must get a canonical code, never `sqlite3.IntegrityError`."""
    store, service, owner, _, _, _ = repo
    path = store.db.execute('PRAGMA database_list').fetchone()['file']
    other_store = SessionStore(Path(path))
    try:
        runs = {'run-1': {'runId': 'run-1', 'sessionId': owner}}
        other = TaskService(other_store, lambda owner_id, run_id: copy.deepcopy(runs.get(run_id)))
        task = create(repo)
        sid = child(repo)
        attempt(repo, task, sid)
        with store.db:
            store.db.execute('UPDATE children SET started=started+1 WHERE session_id=?', (sid,))
        current = other.get(owner, 'run-1', task['taskKey'])
        error('TASK_ATTEMPT_CONFLICT',
              lambda: other.record_attempt(owner, 'run-1', task['taskKey'], invocation_id='inv-other',
                                           expected_revision=current['revision'], session_id=sid,
                                           admission_id='admission-other', capability_epoch=1))
        error('TASK_ALIAS_CONFLICT',
              lambda: other.create(owner, 'run-1', request(invocationId='inv-other-create'), controller_id=owner))
    finally:
        other_store.close()


def test_one_active_attempt_per_child_session_across_tasks(repo):
    """A second task may not bind a child that was never reopened for it."""
    store, service, owner, _, _, _ = repo
    first = create(repo)
    second = create(repo, taskId='second-task', invocationId='inv-create-2',
                    goal='Second goal for the same child session.')
    sid = child(repo)
    attempt(repo, first, sid)
    current = service.get(owner, 'run-1', second['taskKey'])
    error('TASK_ATTEMPT_BINDING',
          lambda: service.record_attempt(owner, 'run-1', second['taskKey'], invocation_id='inv-second',
                                         expected_revision=current['revision'], session_id=sid,
                                         admission_id='admission-2', capability_epoch=1))
    assert service.get(owner, 'run-1', second['taskKey'])['state'] == 'queued'


def test_active_index_survives_a_stale_waiting_input_schema(tmp_path):
    """A database written by the previous schema must be repaired, not re-used as-is."""
    store = SessionStore(tmp_path / 'stale.db')
    try:
        store.db.executescript('''
            CREATE TABLE IF NOT EXISTS harness_task_attempts (
                attempt_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, task_key TEXT NOT NULL,
                session_id TEXT NOT NULL, attempt_seq INTEGER NOT NULL, admission_id TEXT NOT NULL,
                capability_epoch INTEGER NOT NULL, contract_hash TEXT NOT NULL, task_revision INTEGER NOT NULL,
                status TEXT NOT NULL, reason TEXT, result_refs_json TEXT NOT NULL, provenance_json TEXT NOT NULL,
                started_at REAL NOT NULL, closed_at REAL);
            CREATE UNIQUE INDEX harness_task_active ON harness_task_attempts(task_key)
                WHERE status IN ('running','waiting_input');
        ''')
        TaskService(store, lambda owner_id, run_id: None)
        sql = store.db.execute("SELECT sql FROM sqlite_master WHERE name='harness_task_active'").fetchone()['sql']
        assert 'closed_at IS NULL' in sql and sql.count('waiting_input') == 1
    finally:
        store.close()


def test_parked_open_attempt_still_blocks_a_second_attempt(repo):
    """The unique index must keep covering a parked-open attempt, not only `running` ones."""
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_wait(sid, ['main'], since=123.0)
    parked = service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    assert parked['status'] == 'waiting_input' and parked['closedAt'] is None
    assert service.get(owner, 'run-1', task['taskKey'])['state'] == 'waiting_input'
    # A resume reopens the child, but this row was never closed: it must still block a new one.
    with store.db:
        store.db.execute('UPDATE children SET started=started+1, waiting_since=NULL WHERE session_id=?', (sid,))
    current = service.get(owner, 'run-1', task['taskKey'])
    error('TASK_ATTEMPT_CONFLICT',
          lambda: service.record_attempt(owner, 'run-1', task['taskKey'], invocation_id='inv-resume',
                                         expected_revision=current['revision'], session_id=sid,
                                         admission_id='admission-2', capability_epoch=1))
    store.child_wait(sid, ['main'], since=124.0)
    error('TASK_ATTEMPT_BINDING',
          lambda: service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId']))


def test_open_projection_never_carries_a_stale_close_reason(repo):
    """A resumed child keeps `children.reason`; the open attempt must not show it."""
    store, service, owner, _, _, _ = repo
    task = create(repo)
    sid = child(repo)
    first = attempt(repo, task, sid)
    store.child_close_once(sid, 'needs_user', 'Which export format?')
    service.project_attempt(owner, 'run-1', task['taskKey'], first['attemptId'])
    with store.db:
        store.db.execute("UPDATE children SET status='started', finished=NULL, started=started+1"
                         ' WHERE session_id=?', (sid,))
    assert store.child(sid)['reason'] == 'Which export format?'
    current = service.get(owner, 'run-1', task['taskKey'])
    second = attempt(repo, current, sid, invocation='inv-resume', admission='admission-2')
    view = service.project_attempt(owner, 'run-1', task['taskKey'], second['attemptId'])
    assert view['status'] == 'running' and view['reason'] is None
    assert service.attempts(owner, 'run-1', task['taskKey'])['items'][0]['reason'] in (None, 'Which export format?')


def test_missing_required_column_fails_closed(tmp_path):
    store = SessionStore(tmp_path / 'narrow.db')
    try:
        store.db.executescript('''
            CREATE TABLE harness_tasks (
                task_key TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, run_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, controller_id TEXT NOT NULL, task_alias TEXT NOT NULL,
                contract_hash TEXT NOT NULL, contract_json TEXT NOT NULL, state TEXT NOT NULL,
                acceptance_state TEXT NOT NULL, control_state TEXT, abandoned_at REAL,
                abandon_reason TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL);
        ''')
        with pytest.raises(ContractError) as exc:
            TaskService(store, lambda owner_id, run_id: None)
        assert exc.value.code == 'TASK_SCHEMA_UNSUPPORTED'
    finally:
        store.close()
