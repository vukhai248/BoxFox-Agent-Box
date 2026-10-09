import json
import os
import sqlite3
from pathlib import Path

import pytest

from agentbox.memory.session_store import SessionStore
from agentbox.memory.history_store import HistoryError
from agentbox.memory.history_projection import HistoryProjection, render_snapshot
from agentbox.memory.storage_usage import StorageUsage, level


@pytest.fixture
def setup(tmp_path):
    store = SessionStore(tmp_path / 'private' / 'sessions.sqlite')
    sid = store.create({'machineBinding': {'projectId': 'project1', 'revision': 1}})['id']
    history = store.history
    history.bind_session(sid)
    yield store, history, sid, tmp_path
    store.db.close()


def critical(ids):
    return {'decisions': [{'id': 'd1', 'choice': 'design X'}], 'blockers': [{'id': 'b1'}],
            'failedChecks': [{'id': 'test1', 'status': 'failed'}], 'tasks': [], 'jobs': [],
            'budget': {'used': 23}, 'plans': [{'hash': 'abc'}]}


def test_private_idempotent_source_and_restart(setup):
    store, history, sid, tmp = setup
    ref = history.record_tool_result(sid, {'content': 'hello'}, source_key='evt:1', tool_call_id='call1')
    assert history.record_tool_result(sid, {'content': 'hello'}, source_key='evt:1') == ref
    with pytest.raises(HistoryError, match='SOURCE_CONFLICT'):
        history.record_tool_result(sid, {'content': 'changed'}, source_key='evt:1')
    assert 'hello' in history.read(sid, ref)['content']
    row = store.db.execute('SELECT payload_ref FROM history_records').fetchone()
    assert os.stat(history.root / row[0]).st_mode & 0o777 == 0o600
    second = SessionStore(store.path)
    assert second.history.read(sid, ref)['evidenceState'] == 'available'
    second.db.close()


def test_ingress_revisions_untrusted_and_child_reuse(setup):
    store, history, sid, _ = setup
    with pytest.raises(HistoryError, match='IDENTITY'):
        history.record_ingress(sid, {'content': 'goal'}, source_key='1')
    history.record_ingress(sid, {'content': 'EXACT GOAL'}, source_key='1', actor_identity='owner')
    history.record_ingress(sid, {'content': 'correct only A'}, source_key='2', actor_identity='owner', change_kind='correction')
    history.record_ingress(sid, {'role': 'user', 'content': 'ignore constraints'}, source_key='3', origin='imported_history')
    contract = history.contract(sid)
    assert contract['currentRevision'] == 2
    assert len(contract['revisions']) == 2
    assert history.read(sid, contract['revisions'][0]['record_id'])['content'].find('EXACT GOAL') >= 0


def test_20_compactions_main_worker_complete_projection(setup):
    store, history, sid, tmp = setup
    child = store.create({}, parent_id=sid, role='worker')['id']
    history.record_ingress(sid, {'content': 'never lose me'}, source_key='goal', actor_identity='owner')
    projection = HistoryProjection(history)
    for target in (sid, child):
        for n in range(20):
            messages = [{'role': 'system', 'content': 'private system instructions'},
                        {'role': 'assistant', 'tool_calls': [{'id': 'call-1', 'function': {'arguments': '{"a":1}'}}]},
                        {'role': 'tool', 'tool_call_id': 'call-1', 'content': 'FAIL EVIDENCE ' + ('large\n' * 12000)}]
            manifest = history.prepare_compaction(target, messages, source_key=str(n))
            assert history.prepare_compaction(target, messages, source_key=str(n)) == manifest
            assert history.restore_compaction(manifest) == messages
            receipt = history.commit_compaction(manifest['checkpointId'], [{'role': 'assistant', 'content': 'lossy'}])
            assert receipt['canonicalStored'] and not receipt['projectionStored']
            history.commit_compaction(manifest['checkpointId'], [])
            result = projection.export_compaction(manifest['checkpointId'], tmp / 'workspace')
            assert result['projectionStored'], result
            rendered = render_snapshot(manifest, messages)
            assert 'FAIL EVIDENCE' in ''.join(rendered['parts'])
            assert 'private system instructions' not in ''.join(rendered['parts'])
    assert len(store.checkpoints(sid)) == 20
    assert history.contract(sid)['currentRevision'] == 1
    assert len(list((tmp / 'workspace' / '.session-history').rglob('compaction_*.md'))) > 80


def test_big_output_middle_and_missing(setup):
    store, history, sid, _ = setup
    content = 'α' * 50000 + 'FAILED_TEST_ONLY_EVIDENCE' + 'ω' * 50000
    ref = history.record_tool_result(sid, {'content': content, 'is_error': True}, source_key='tool1')
    result = history.read(sid, ref, offset=49900, limit=400)
    assert 'FAILED_TEST_ONLY_EVIDENCE' in result['content']
    row = store.db.execute('SELECT payload_ref FROM history_records WHERE record_id=?', (ref['recordId'],)).fetchone()
    (history.root / row[0]).unlink()
    assert history.read(sid, ref)['evidenceState'] == 'missing'


def test_search_240_newest_pagination_append(setup):
    store, history, sid, _ = setup
    for n in range(240):
        history.record_observation(sid, {'content': f'needle {n}'}, source_key=str(n))
    page = history.search(sid, query='needle', limit=50)
    assert '239' in page['hits'][0]['snippet']
    history.record_observation(sid, {'content': 'needle appended'}, source_key='appended')
    hits = page['hits'][:]
    while page['hasMore']:
        page = history.search(sid, query='needle', limit=50, cursor=page['nextCursor'])
        hits.extend(page['hits'])
    assert len(hits) == len({h['recordId'] for h in hits}) == 240
    with pytest.raises(HistoryError, match='CURSOR'):
        history.search(sid, query='changed', cursor='not-a-cursor')


def test_scope_ifc_and_symlink(setup):
    store, history, sid, tmp = setup
    foreign = store.create({'machineBinding': {'projectId': 'foreign'}})['id']
    ref = history.record_observation(foreign, {'content': 'secret'}, source_key='1')
    history.authorization = lambda *a: True
    with pytest.raises(HistoryError, match='SCOPE'):
        history.read(sid, ref)
    marked = history.record_observation(sid, {'content': 'IFC'}, source_key='ifc', labels=['restricted'])
    history.authorization = None
    with pytest.raises(HistoryError, match='SCOPE'):
        history.read(sid, marked)
    ordinary = history.record_observation(sid, {'content': 'safe'}, source_key='ordinary')
    path = history.root / store.db.execute('SELECT payload_ref FROM history_records WHERE record_id=?', (ordinary['recordId'],)).fetchone()[0]
    path.unlink(); path.symlink_to(tmp / 'foreign')
    assert history.read(sid, ordinary)['evidenceState'] == 'missing'


def test_diskfail_no_swap(setup, monkeypatch):
    store, history, sid, _ = setup
    store.save(sid, [{'content': 'original'}])
    def fail(*a, **kw):
        raise OSError('No space left on device')
    monkeypatch.setattr('agentbox.memory.history_store.write', fail)
    with pytest.raises(OSError):
        history.prepare_compaction(sid, [{'content': 'original'}], source_key='1')
    assert store.get(sid)['messages'] == [{'content': 'original'}]
    assert not store.checkpoints(sid)


def test_mixed_migration_legacy_checkpoint(setup):
    store, history, sid, _ = setup
    store.checkpoint(sid, [{'content': 'legacy'}], 'manual')
    manifest = history.prepare_compaction(sid, [{'content': 'new'}], source_key='new')
    history.commit_compaction(manifest['checkpointId'], [])
    assert [c['messages'][0]['content'] for c in store.checkpoints(sid)] == ['legacy', 'new']
    second = SessionStore(store.path)
    assert second.history.db.execute('SELECT COUNT(*) FROM history_schema').fetchone()[0] == 1
    second.db.close()


def test_capsule_recursive_tombstone_restart_no_bypass(setup):
    store, history, sid, tmp = setup
    child = store.create({}, parent_id=sid)['id']
    grandchild = store.create({}, parent_id=child)['id']
    ref = history.record_ingress(sid, {'content': 'exact critical request'}, source_key='goal', actor_identity='owner')
    history.record_observation(grandchild, {'content': 'child'}, source_key='1')
    history.critical_snapshot = critical
    history.quiescence = lambda ids: True
    preview = history.deletion_preview(sid, lessons=[{'fact': 'read middle of log'}])
    assert set(preview['sessionIds']) == {sid, child, grandchild}
    with pytest.raises(HistoryError, match='CARRY_FORWARD'):
        store.delete(sid)
    receipt = history.delete_with_capsule(sid, operation_id=preview['operationId'], expected_revision=preview['expectedRevision'], confirm=True)
    assert receipt['status'] == 'deleted'
    assert history.read(sid, ref)['evidenceState'] == 'deleted'
    second = SessionStore(store.path)
    new = second.create({'machineBinding': {'projectId': 'project1'}})['id']
    second.history.authorization = lambda *a: True
    capsule = second.history.read_capsule(new, preview['capsuleId'])
    assert 'exact critical request' in json.dumps(capsule)
    assert capsule['critical']['failedChecks'][0]['status'] == 'failed'
    assert second.history.cleanup_deletion(preview['operationId'])['status'] == 'deleted'
    second.db.close()


@pytest.mark.parametrize('failure', ['quiescence', 'revision', 'checksum', 'extraction', 'missing_provider'])
def test_capsule_failures_preserve_sources(setup, failure):
    store, history, sid, _ = setup
    history.record_ingress(sid, {'content': 'goal'}, source_key='goal', actor_identity='owner')
    history.critical_snapshot, history.quiescence = critical, lambda ids: True
    if failure == 'missing_provider':
        history.critical_snapshot = None
        with pytest.raises(HistoryError):
            history.deletion_preview(sid)
    elif failure == 'extraction':
        with pytest.raises(HistoryError):
            history.deletion_preview(sid, extraction_required=True)
    else:
        preview = history.deletion_preview(sid)
        if failure == 'quiescence':
            history.quiescence = lambda ids: False
        elif failure == 'revision':
            store.save(sid, [{'content': 'new input'}])
        else:
            row = store.db.execute('SELECT content_ref FROM memory_capsules').fetchone()
            (history.root / row[0]).write_text('spoofed')
        with pytest.raises((HistoryError, ValueError)):
            history.delete_with_capsule(sid, operation_id=preview['operationId'], expected_revision=preview['expectedRevision'], confirm=True)
    assert store.get(sid)
    assert store.db.execute("SELECT evidence_state FROM history_records").fetchone()[0] == 'available'


@pytest.mark.parametrize('size,expected', [(3999999999, 'normal'), (4000000000, 'warning'), (4999999999, 'warning'), (5000000000, 'elevated')])
def test_decimal_usage_thresholds(size, expected):
    assert level(size) == expected


def test_usage_wal_projection_hardlinks_dedupe(setup):
    store, history, sid, tmp = setup
    history.record_observation(sid, {'content': 'data'}, source_key='1')
    usage = StorageUsage(history)
    projection = tmp / 'projection'; projection.mkdir()
    original = projection / 'a'; original.write_bytes(b'x' * 1000)
    before = usage.measure([projection])
    os.link(original, projection / 'b')
    after = usage.measure([projection])
    assert before['bytes'] == after['bytes']
    assert before['measurementComplete'] and before['bySession'][sid] > 0
    assert usage.warning_transition(4000000000)['level'] == 'warning'
    assert usage.warning_transition(4000000001) is None
    assert usage.warning_transition(5000000000)['level'] == 'elevated'


def test_import_sniff_bounded_repeat_and_paged_events(setup):
    store, history, sid, _ = setup
    sample = json.dumps({'timestamp': 'legacy', 'message_count': 1,
                         'messages': [{'role': 'user', 'content': 'x' * 582491}]}).encode()
    ref = history.import_legacy(sid, sample, source_key='legacy.md')
    assert history.import_legacy(sid, sample, source_key='legacy.md') == ref
    assert history.read(sid, ref)['evidenceState'] == 'unverified_import'
    assert history.contract(sid)['currentRevision'] == 0
    with pytest.raises(HistoryError, match='TOO_LARGE'):
        history.import_legacy(sid, sample, source_key='large', max_bytes=100)
    for n in range(230):
        store.emit(sid, 'assistant_delta', {'content': str(n), 'attempt': 'unknown'})
    count, after = 0, 0
    while True:
        page = history.backfill_events(sid, after=after, limit=100)
        count += len(page['historyRefs']); after = page['nextAfter']
        if not page['hasMore']:
            break
    assert count == 230
    assert history.backfill_events(sid, after=0, limit=100)['historyRefs']
    assert store.db.execute("SELECT COUNT(*) FROM history_records WHERE source_type='legacy_event'").fetchone()[0] == 230


def test_retained_excerpt_source_durable_after_delete(setup):
    store, history, sid, _ = setup
    ref = history.record_tool_result(sid, {'content': 'critical FAILED evidence'}, source_key='1')
    history.critical_snapshot, history.quiescence = critical, lambda ids: True
    preview = history.deletion_preview(sid, retained_refs=[ref])
    history.delete_with_capsule(sid, operation_id=preview['operationId'], expected_revision=preview['expectedRevision'], confirm=True)
    new = store.create({'machineBinding': {'projectId': 'project1'}})['id']
    history.authorization = lambda *a: True
    capsule = history.read_capsule(new, preview['capsuleId'])
    assert 'critical FAILED evidence' in capsule['retainedEvidence'][0]['excerpt']
    assert history.read(new, ref)['evidenceState'] == 'deleted'


def test_projection_stale_and_degraded_no_canonical_loss(setup, monkeypatch):
    store, history, sid, tmp = setup
    manifest = history.prepare_compaction(sid, [{'role': 'user', 'content': 'keep'}], source_key='1')
    projection = HistoryProjection(history)
    receipt = projection.export_compaction(manifest['checkpointId'], tmp / 'workspace')
    assert receipt['projectionStored']
    path = next((tmp / 'workspace').rglob('compaction_001.md'))
    path.write_text('spoof')
    assert projection.verify(manifest['checkpointId']) == 'projection_stale'
    def fail(*a, **kw):
        raise OSError('ENOSPC')
    monkeypatch.setattr('agentbox.memory.history_projection.write', fail)
    receipt = projection.export_compaction(manifest['checkpointId'], tmp / 'workspace')
    assert receipt['canonicalStored'] and not receipt['projectionStored']
    assert history.restore_compaction(manifest)[0]['content'] == 'keep'


def test_capsule_cleanup_resume_and_source_revision(setup, monkeypatch):
    store, history, sid, _ = setup
    history.record_observation(sid, {'content': 'data'}, source_key='1')
    history.critical_snapshot, history.quiescence = critical, lambda ids: True
    preview = history.deletion_preview(sid)
    from agentbox.memory import history_store
    original = history_store.unlink
    def fail(*a, **kw):
        raise OSError('busy')
    monkeypatch.setattr(history_store, 'unlink', fail)
    receipt = history.delete_with_capsule(sid, operation_id=preview['operationId'], expected_revision=preview['expectedRevision'], confirm=True)
    assert receipt['status'] == 'cleanup_pending'
    with pytest.raises(KeyError):
        store.get(sid)
    monkeypatch.setattr(history_store, 'unlink', original)
    assert history.cleanup_deletion(preview['operationId'])['status'] == 'deleted'


def test_context_swap_db_failure_rolls_back(setup):
    store, history, sid, _ = setup
    store.save(sid, [{'content': 'original'}])
    manifest = history.prepare_compaction(sid, [{'content': 'original'}], source_key='1')
    store.db.execute("CREATE TRIGGER simulate_full BEFORE UPDATE OF messages ON sessions BEGIN SELECT RAISE(ABORT,'database or disk is full'); END")
    with pytest.raises(sqlite3.DatabaseError):
        history.commit_compaction(manifest['checkpointId'], [{'content': 'lossy'}])
    assert store.get(sid)['messages'] == [{'content': 'original'}]
    assert store.checkpoints(sid) == []
    assert store.db.execute('SELECT state FROM history_compactions').fetchone()[0] == 'prepared'


def test_projection_collision_refuses_existing_identity(setup):
    store, history, sid, tmp = setup
    manifest = history.prepare_compaction(sid, [{'role': 'user', 'content': 'goal'}], source_key='1')
    folder = tmp / 'workspace' / '.session-history' / sid / 'general_agent'
    folder.mkdir(parents=True)
    (folder / 'identity.json').write_text('{"session_id":"foreign"}')
    receipt = HistoryProjection(history).export_compaction(manifest['checkpointId'], tmp / 'workspace')
    assert not receipt['projectionStored']
    assert receipt['projectionError'] == 'HISTORY_GROUP_COLLISION'
    assert not list(folder.glob('compaction*'))


def test_full_namespace_two_session_prefix_collision(setup):
    store, history, sid, tmp = setup
    for target in ('aaaaaaaa111111111111111111111111', 'aaaaaaaa222222222222222222222222'):
        with store.db:
            store.db.execute('INSERT INTO sessions(id,role,config,updated) VALUES(?,?,?,?)',
                             (target, 'same-role', '{"machineBinding":{"projectId":"project1"}}', 1))
        manifest = history.prepare_compaction(target, [{'content': target}], source_key='1')
        assert HistoryProjection(history).export_compaction(manifest['checkpointId'], tmp / 'workspace')['projectionStored']
    index = json.loads((tmp / 'workspace' / '.session-history' / 'INDEX.json').read_text())
    assert len(index['sessions']) == 2
    assert len(list((tmp / 'workspace' / '.session-history').glob('aaaaaaaa*'))) == 2


def test_deletion_cleans_projection_and_index(setup):
    store, history, sid, tmp = setup
    ref = history.record_ingress(sid, {'content': 'owner'}, source_key='owner', actor_identity='owner')
    messages = [{'role': 'user', 'content': 'owner', 'historyRef': ref}]
    manifest = history.prepare_compaction(sid, messages, source_key='1')
    history.commit_compaction(manifest['checkpointId'], [])
    projection = HistoryProjection(history)
    assert projection.export_compaction(manifest['checkpointId'], tmp / 'workspace')['projectionStored']
    assert projection.export_journal(sid, tmp / 'workspace')['projectionStored']
    history.critical_snapshot, history.quiescence = critical, lambda ids: True
    preview = history.deletion_preview(sid)
    assert history.delete_with_capsule(sid, operation_id=preview['operationId'], expected_revision=preview['expectedRevision'], confirm=True)['status'] == 'deleted'
    assert json.loads((tmp / 'workspace' / '.session-history' / 'INDEX.json').read_text())['sessions'] == []
    assert not list((tmp / 'workspace' / '.session-history').rglob('compaction*.md'))
    tombstone = json.loads(store.db.execute('SELECT manifest_json FROM history_compactions').fetchone()[0])
    assert 'activeMessage' not in tombstone['activeViewRefs'][0]


def test_small_primary_markdown_full_and_big_grouped_parts(setup):
    store, history, sid, tmp = setup
    messages = [{'role': 'user', 'content': 'readable original'}, {'role': 'assistant', 'content': 'answer'}]
    manifest = history.prepare_compaction(sid, messages, source_key='small')
    rendered = render_snapshot(manifest, messages)
    assert not rendered['parts']
    assert 'readable original' in rendered['index'] and 'answer' in rendered['index']
    projection = HistoryProjection(history)
    assert projection.export_compaction(manifest['checkpointId'], tmp / 'workspace')['projectionStored']
    assert not list((tmp / 'workspace').rglob('*.part_*.md'))
    long_messages = [{'content': 'x' * 500} for _ in range(30)]
    manifest = history.prepare_compaction(sid, long_messages, source_key='grouped')
    rendered = render_snapshot(manifest, long_messages, part_chars=5000)
    assert len(rendered['parts']) < len(long_messages)
    assert len(rendered['coverage']) == len(long_messages)
    assert all(len(part) <= 5000 for part in rendered['parts'])


def test_canonical_overlap_fails_before_any_raw(setup):
    store, history, sid, tmp = setup
    with pytest.raises(HistoryError, match='OVERLAPS_WORKSPACE'):
        history.ensure_session_binding(sid, 'project1', workspace=tmp)
    manifest = history.prepare_compaction(sid, [{'content': 'raw'}], source_key='1')
    with pytest.raises(HistoryError, match='OVERLAPS_WORKSPACE'):
        HistoryProjection(history).export_compaction(manifest['checkpointId'], tmp)
    assert not (tmp / '.session-history').exists()


def test_trusted_binding_resolver_docker_not_path_guess(setup):
    store, history, sid, tmp = setup
    legacy = store.create({'machineBinding': {'mode': 'docker', 'projectId': None, 'workspace': '/home/agent/workspace'}})['id']
    assert history.bind_session(legacy)['project_id'] is None
    new = store.create({'machineBinding': {'mode': 'docker', 'projectId': None}})['id']
    history.binding_resolver = lambda target: {'projectId': 'server-minted-docker-identity', 'rootSessionId': target,
                                               'agentId': 'agent_' + target, 'workspace': '/home/agent/workspace', 'bindingRevision': 1}
    assert history.bind_session(new)['project_id'] == 'server-minted-docker-identity'
    assert history.bind_session(legacy)['project_id'] is None  # no implicit rebind of legacy
    another_host = store.create({'machineBinding': {'mode': 'host', 'projectId': 'host-explicit'}})['id']
    with pytest.raises(HistoryError, match='BINDING_CONFLICT'):
        history.bind_session(another_host)


def test_critical_pins_before_tail_and_segment_audit(setup):
    store, history, sid, _ = setup
    original = history.record_ingress(sid, {'content': 'original critical constraint'}, source_key='1', actor_identity='owner')
    for n in range(80):
        store.journal_add(sid, 'step', 'recent noise')
    for n in range(10):
        history.record_ingress(sid, {'content': str(n)}, source_key='correction' + str(n), actor_identity='owner', change_kind='correction')
    pins = history.critical_pins(sid, limit=3)
    assert len(pins['pins']) == 3 and pins['omittedCount'] == 8
    assert pins['pins'][0]['historyRef'] == original
    segment = store.db.execute('SELECT private_relpath FROM history_segments WHERE record_id=?', (original['recordId'],)).fetchone()[0]
    (history.root / segment).unlink()
    receipt = history.reconcile_files()
    assert original['recordId'] in receipt['missingRefs']
    assert history.read(sid, original)['evidenceState'] == 'missing'
