"""Additive scoped history over SessionStore. Graph/task/job ledgers remain authoritative.

Canonical failure propagates before a context swap. Projection failure is degraded only.
Authorization and critical-state providers are harness hooks, not model arguments.
"""
import base64
import json
import time
import uuid
from pathlib import Path

from .history_files import digest, encode, identifier, read, write, unlink

# Bảy nguồn critical mà một capsule phải phủ đủ trước khi cho xoá (đúng thứ tự này).
CAPSULE_KEYS = ('decisions', 'blockers', 'failedChecks', 'tasks', 'jobs', 'budget', 'plans')


class HistoryError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class HistoryStore:
    def __init__(self, store, private_root, *, authorization=None, critical_snapshot=None, quiescence=None, binding_resolver=None):
        self.store, self.db = store, store.db
        self.root = Path(private_root)
        self.authorization = authorization
        self.critical_snapshot = critical_snapshot
        self.quiescence = quiescence
        self.binding_resolver = binding_resolver
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS history_schema(version INTEGER PRIMARY KEY);
        INSERT OR IGNORE INTO history_schema VALUES(1);
        CREATE TABLE IF NOT EXISTS history_sessions(
          session_id TEXT PRIMARY KEY, project_id TEXT, root_session_id TEXT NOT NULL,
          agent_id TEXT NOT NULL, parent_agent_id TEXT, binding_revision INTEGER,
          created REAL NOT NULL, status TEXT NOT NULL DEFAULT 'active');
        CREATE TABLE IF NOT EXISTS history_records(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, record_id TEXT UNIQUE NOT NULL,
          project_id TEXT, session_id TEXT NOT NULL, agent_id TEXT NOT NULL,
          ordinal INTEGER NOT NULL, origin TEXT NOT NULL, kind TEXT NOT NULL,
          created REAL NOT NULL, source_type TEXT NOT NULL, source_key TEXT NOT NULL,
          tool_call_id TEXT, payload_ref TEXT NOT NULL, sha256 TEXT NOT NULL,
          bytes INTEGER NOT NULL, search_text TEXT NOT NULL, labels TEXT NOT NULL,
          evidence_state TEXT NOT NULL, deleted_at REAL,
          UNIQUE(session_id,agent_id,ordinal), UNIQUE(session_id,agent_id,source_type,source_key));
        CREATE INDEX IF NOT EXISTS history_scope ON history_records(project_id,seq);
        CREATE TABLE IF NOT EXISTS history_segments(
          record_id TEXT PRIMARY KEY, private_relpath TEXT NOT NULL, sha256 TEXT NOT NULL,
          bytes INTEGER NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history_compactions(
          checkpoint_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, agent_id TEXT NOT NULL,
          generation INTEGER NOT NULL, source_key TEXT NOT NULL, manifest_json TEXT NOT NULL,
          state TEXT NOT NULL, projection_status TEXT NOT NULL DEFAULT 'missing', created REAL NOT NULL,
          UNIQUE(session_id,agent_id,generation), UNIQUE(session_id,agent_id,source_key));
        CREATE TABLE IF NOT EXISTS owner_contract_revisions(
          session_id TEXT NOT NULL, revision INTEGER NOT NULL, record_id TEXT NOT NULL,
          actor_identity TEXT NOT NULL, change_kind TEXT NOT NULL, constraints_json TEXT NOT NULL,
          created REAL NOT NULL, PRIMARY KEY(session_id,revision), UNIQUE(record_id));
        CREATE TABLE IF NOT EXISTS memory_capsules(
          capsule_id TEXT PRIMARY KEY, project_id TEXT, content_ref TEXT NOT NULL,
          sha256 TEXT NOT NULL, created REAL NOT NULL, status TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS history_deletions(
          operation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, session_ids_json TEXT NOT NULL,
          expected_revision TEXT NOT NULL, capsule_id TEXT NOT NULL, state TEXT NOT NULL,
          created REAL NOT NULL, last_error TEXT);
        ''')

    def bind_session(self, sid):
        identifier(sid)
        existing = self.db.execute('SELECT * FROM history_sessions WHERE session_id=?', (sid,)).fetchone()
        if existing:
            return dict(existing)
        session = self.store.get(sid)
        parent = self.bind_session(session['parent_id']) if session['parent_id'] else None
        binding = session['config'].get('machineBinding') or {}
        if binding.get('workspace'):
            self.assert_private_workspace(binding['workspace'])
        resolved = self.binding_resolver(sid) if self.binding_resolver else {}
        resolved = resolved or {}
        if binding.get('projectId') and resolved.get('projectId') and binding['projectId'] != resolved['projectId']:
            raise HistoryError('HISTORY_BINDING_CONFLICT')
        if resolved.get('workspace'):
            self.assert_private_workspace(resolved['workspace'])
        project = binding.get('projectId') or resolved.get('projectId') or session['config'].get('historyProjectId') or (parent['project_id'] if parent else None)
        if project:
            identifier(project)
        agent = identifier(resolved.get('agentId') or session['config'].get('historyAgentId') or sid)
        root = identifier(resolved.get('rootSessionId') or (parent['root_session_id'] if parent else sid))
        with self.db:
            self.db.execute('INSERT INTO history_sessions VALUES(?,?,?,?,?,?,?,?)',
                            (sid, project, root, agent, parent['agent_id'] if parent else None,
                             resolved.get('bindingRevision', binding.get('revision')), time.time(), 'active'))
        return self.bind_session(sid)

    def _allowed(self, caller, target, labels=None):
        a, b = self.bind_session(caller), self.bind_session(target)
        # Tombstone (status='deleted') vẫn đọc được — nhưng chỉ qua caller cùng project đã được
        # hook authorization cho phép; hai cổng dưới đây là chỗ duy nhất quyết định điều đó.
        if caller != target and (not a['project_id'] or a['project_id'] != b['project_id']):
            raise HistoryError('HISTORY_SCOPE_DENIED')
        if caller != target or labels:
            if not self.authorization or not self.authorization(caller, target, {'labels': labels or []}):
                raise HistoryError('HISTORY_SCOPE_DENIED')
        return b

    def _ref(self, row):
        return {'recordId': row['record_id'], 'sessionId': row['session_id'],
                'agentId': row['agent_id'], 'ordinal': row['ordinal'], 'sha256': row['sha256']}

    def record_observation(self, sid, payload, *, source_key, source_type='message',
                           origin='assistant', kind='message', tool_call_id=None, labels=None):
        scope = self.bind_session(sid)
        if scope['status'] != 'active':
            raise HistoryError('HISTORY_DELETED')
        data = encode(payload).encode('utf-8')
        checksum = digest(data)
        old = self.db.execute('SELECT * FROM history_records WHERE session_id=? AND agent_id=? '
                              'AND source_type=? AND source_key=?',
                              (sid, scope['agent_id'], source_type, str(source_key))).fetchone()
        if old:
            if old['sha256'] != checksum:
                raise HistoryError('HISTORY_SOURCE_CONFLICT')
            return self._ref(old)
        ordinal = self.db.execute('SELECT COALESCE(MAX(ordinal),0)+1 FROM history_records '
                                  'WHERE session_id=? AND agent_id=?', (sid, scope['agent_id'])).fetchone()[0]
        rid = uuid.uuid4().hex
        components = ('history', 'projects', scope['project_id'] or ('legacy_' + sid),
                      'sessions', sid, 'agents', scope['agent_id'])
        # A bounded raw JSONL segment; large payload lives once in a separately hashed blob.
        payload_ref = write(self.root, components, 'blob_' + rid, data)
        envelope = {'schemaVersion': 1, 'recordId': rid, 'projectId': scope['project_id'],
                    'sessionId': sid, 'agentId': scope['agent_id'], 'ordinal': ordinal,
                    'origin': origin, 'kind': kind, 'payloadRef': payload_ref, 'sha256': checksum,
                    'source': {'type': source_type, 'key': str(source_key)}}
        segment_data = (encode(envelope) + '\n').encode()
        segment_ref = write(self.root, components, 'segment_' + rid, segment_data)
        with self.db:
            self.db.execute('INSERT INTO history_records(record_id,project_id,session_id,agent_id,ordinal,'
                            'origin,kind,created,source_type,source_key,tool_call_id,payload_ref,sha256,bytes,'
                            'search_text,labels,evidence_state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (rid, scope['project_id'], sid, scope['agent_id'], ordinal, origin, kind, time.time(),
                             source_type, str(source_key), tool_call_id, payload_ref, checksum, len(data),
                             '' if labels or origin == 'system' else data.decode(), encode(labels or []),
                             'unverified_import' if origin == 'imported_history' else 'available'))
            self.db.execute('INSERT INTO history_segments VALUES(?,?,?,?,?)',
                            (rid, segment_ref, digest(segment_data), len(segment_data), 'committed'))
        return self._ref(self.db.execute('SELECT * FROM history_records WHERE record_id=?', (rid,)).fetchone())

    def record_ingress(self, sid, payload, *, source_key, origin='owner_user', actor_identity=None,
                       change_kind='request', constraints=None, labels=None):
        if origin == 'owner_user' and not actor_identity:
            raise HistoryError('OWNER_IDENTITY_REQUIRED')
        if origin not in ('owner_user', 'delegated_contract', 'imported_history', 'synthetic_handoff'):
            raise HistoryError('INGRESS_ORIGIN_INVALID')
        ref = self.record_observation(sid, payload, source_key=source_key, source_type='ingress',
                                      origin=origin, kind=change_kind, labels=labels)
        if origin == 'owner_user':
            old = self.db.execute('SELECT * FROM owner_contract_revisions WHERE record_id=?', (ref['recordId'],)).fetchone()
            if not old:
                revision = self.db.execute('SELECT COALESCE(MAX(revision),0)+1 FROM owner_contract_revisions '
                                           'WHERE session_id=?', (sid,)).fetchone()[0]
                with self.db:
                    self.db.execute('INSERT INTO owner_contract_revisions VALUES(?,?,?,?,?,?,?)',
                                    (sid, revision, ref['recordId'], actor_identity, change_kind,
                                     encode(constraints or {}), time.time()))
        return ref

    def record_tool_result(self, sid, payload, *, source_key, tool_call_id=None):
        return self.record_observation(sid, payload, source_key=source_key, source_type='tool_end',
                                       origin='tool', kind='tool_result', tool_call_id=tool_call_id)

    def contract(self, sid):
        """Owner pins are independent of summary; child contracts reuse harness_tasks."""
        revisions = [dict(r) for r in self.db.execute('SELECT * FROM owner_contract_revisions '
                                                     'WHERE session_id=? ORDER BY revision', (sid,))]
        child = []
        if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_tasks'").fetchone():
            columns = {r['name'] for r in self.db.execute('PRAGMA table_info(harness_tasks)')}
            if 'task_key' in columns and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_task_attempts'").fetchone():
                child = [dict(r) for r in self.db.execute('SELECT t.contract_json,t.contract_hash FROM harness_tasks t '
                         'JOIN harness_task_attempts a ON a.task_key=t.task_key WHERE a.session_id=?', (sid,))]
        return {'sessionId': sid, 'currentRevision': revisions[-1]['revision'] if revisions else 0,
                'revisions': revisions, 'delegatedContracts': child, 'untrusted': False}

    def prepare_compaction(self, sid, messages, *, source_key, numbers=None):
        scope = self.bind_session(sid)
        old = self.db.execute('SELECT * FROM history_compactions WHERE session_id=? AND agent_id=? AND source_key=?',
                              (sid, scope['agent_id'], str(source_key))).fetchone()
        if old:
            manifest = json.loads(old['manifest_json'])
            if manifest['activeViewSha256'] != digest(encode(messages).encode()):
                raise HistoryError('HISTORY_SOURCE_CONFLICT')
            return manifest
        refs = []
        for i, message in enumerate(messages):
            # Caller may supply a proven original ref; no dedupe by text equality.
            ref = message.get('historyRef') if isinstance(message, dict) else None
            if ref:
                restored = self._payload(sid, ref)
                # The active message may be a preview of the full raw tool result.
                refs.append({'historyRef': ref, 'activeMessage': message})
            else:
                origin = 'system' if isinstance(message, dict) and message.get('role') == 'system' else 'unknown'
                ref = self.record_observation(sid, message, source_key=f'{source_key}:{i}',
                    source_type='active_view', origin=origin, kind='compaction_message')
                refs.append({'historyRef': ref})
        generation = self.db.execute('SELECT COALESCE(MAX(generation),0)+1 FROM history_compactions '
                                     'WHERE session_id=? AND agent_id=?', (sid, scope['agent_id'])).fetchone()[0]
        cid = uuid.uuid4().hex
        manifest = {'schemaVersion': 1, 'checkpointId': cid, 'sessionId': sid, 'agentId': scope['agent_id'],
                    'rootSessionId': scope['root_session_id'], 'parentAgentId': scope['parent_agent_id'],
                    'projectId': scope['project_id'], 'generation': generation, 'activeViewRefs': refs,
                    'activeViewSha256': digest(encode(messages).encode()), 'numbers': numbers or {},
                    'rawRanges': [{'sessionId': sid, 'agentId': scope['agent_id'], 'first': item['historyRef']['ordinal'], 'last': item['historyRef']['ordinal']} for item in refs],
                    'coverage': 'provider_visible', 'reasoning': 'absent_unless_recorded'}
        # Verify reconstruction before admitting a checkpoint/context swap.
        if digest(encode(self.restore_compaction(manifest)).encode()) != manifest['activeViewSha256']:
            raise HistoryError('HISTORY_MANIFEST_MISMATCH')
        with self.db:
            self.db.execute('INSERT INTO history_compactions(checkpoint_id,session_id,agent_id,generation,'
                            'source_key,manifest_json,state,created) VALUES(?,?,?,?,?,?,?,?)',
                            (cid, sid, scope['agent_id'], generation, str(source_key), encode(manifest), 'prepared', time.time()))
        return manifest

    def restore_compaction(self, manifest):
        return [item.get('activeMessage') if 'activeMessage' in item else
                self._payload(manifest['sessionId'], item['historyRef']) for item in manifest['activeViewRefs']]

    def commit_compaction(self, checkpoint_id, new_messages, *, summary=None, status=None):
        row = self.db.execute('SELECT * FROM history_compactions WHERE checkpoint_id=?', (checkpoint_id,)).fetchone()
        if not row:
            raise HistoryError('CHECKPOINT_NOT_FOUND')
        manifest = json.loads(row['manifest_json'])
        self.restore_compaction(manifest)
        if row['state'] != 'committed':
            with self.db:
                self.db.execute('INSERT INTO checkpoints(session_id,messages,reason,created) VALUES(?,?,?,?)',
                    (row['session_id'], encode({'historyManifest': manifest}), 'compaction', time.time()))
                self.db.execute('UPDATE sessions SET messages=?,status=COALESCE(?,status),updated=? WHERE id=?',
                    (encode(new_messages), status, time.time(), row['session_id']))
                self.db.execute("UPDATE history_compactions SET state='committed' WHERE checkpoint_id=?", (checkpoint_id,))
        return {'canonicalStored': True, 'checkpointId': checkpoint_id,
                'projectionStored': row['projection_status'] == 'stored', 'projectionStatus': row['projection_status']}

    def _payload(self, caller, ref):
        row = self._record(caller, ref, internal=True)
        if row['evidence_state'] == 'deleted':
            raise HistoryError('HISTORY_DELETED')
        return json.loads(read(self.root, row['payload_ref'], row['sha256']))

    def _record(self, caller, ref, internal=False):
        rid = ref if isinstance(ref, str) else ref.get('recordId')
        row = self.db.execute('SELECT * FROM history_records WHERE record_id=?', (rid,)).fetchone()
        if not row:
            raise HistoryError('HISTORY_REFERENCE_NOT_FOUND')
        self._allowed(caller, row['session_id'], json.loads(row['labels']))
        if row['origin'] == 'system' and not internal:
            raise HistoryError('HISTORY_WITHHELD')
        if isinstance(ref, dict) and any(ref.get(k, v) != v for k, v in self._ref(row).items()):
            raise HistoryError('HISTORY_REFERENCE_MISMATCH')
        return row

    def read_reference(self, caller_sid, ref, *, offset=0, limit=16000):
        row = self._record(caller_sid, ref)
        state = row['evidence_state']
        text = ''
        if state != 'deleted':
            try:
                text = read(self.root, row['payload_ref'], row['sha256']).decode('utf-8')
            except (OSError, ValueError):
                state = 'missing'
        offset, limit = max(0, int(offset)), max(1, min(16000, int(limit)))
        end = offset + limit
        return {'content': text[offset:end], 'provenance': {'projectId': row['project_id'],
                **self._ref(row), 'origin': row['origin'], 'created': row['created']},
                'nextCursor': end if end < len(text) else None, 'hasMore': end < len(text),
                'evidenceState': state, 'deletedAt': row['deleted_at'], 'untrusted': True}

    def query_history(self, caller_sid, *, query='', scope='self', session_id=None, agent_id=None,
                      kinds=None, cursor=None, limit=10, mode='search'):
        caller = self.bind_session(caller_sid)
        if scope not in ('self', 'project') or mode not in ('search', 'list'):
            raise HistoryError('HISTORY_QUERY_INVALID')
        if scope == 'project' and (not caller['project_id'] or not self.authorization):
            raise HistoryError('HISTORY_SCOPE_DENIED')
        target = session_id or (caller_sid if scope == 'self' else None)
        if scope == 'self' and target != caller_sid:
            self._allowed(caller_sid, target)
        filters = [caller_sid, query, scope, target, agent_id, kinds, mode]
        signature = digest(encode(filters).encode())
        high = self.db.execute('SELECT COALESCE(MAX(seq),0) FROM history_records').fetchone()[0]
        before = high + 1
        if cursor:
            try:
                token = json.loads(base64.urlsafe_b64decode(cursor))
                if token['filter'] != signature:
                    raise ValueError()
                high, before = int(token['high']), int(token['before'])
            except (ValueError, KeyError, TypeError):
                raise HistoryError('HISTORY_CURSOR_INVALID')
        clauses, args = ['seq<=?', 'seq<?', "origin!='system'", "evidence_state!='deleted'"], [high, before]
        if target:
            clauses.append('session_id=?'); args.append(target)
        else:
            clauses.append('project_id=?'); args.append(caller['project_id'])
        if agent_id:
            clauses.append('agent_id=?'); args.append(agent_id)
        if kinds:
            clauses.append('kind IN (' + ','.join('?' for _ in kinds) + ')'); args.extend(kinds)
        if query:
            clauses.append('instr(lower(search_text),lower(?))>0'); args.append(query)
        size = max(1, min(50, int(limit)))
        # Sort across all eligible records before LIMIT. No 200-hit precollection.
        rows = self.db.execute('SELECT * FROM history_records WHERE ' + ' AND '.join(clauses) +
                               ' ORDER BY seq DESC LIMIT ?', (*args, size + 1)).fetchall()
        hits, used, last = [], 0, before
        for row in rows[:size]:
            try:
                self._allowed(caller_sid, row['session_id'], json.loads(row['labels']))
            except HistoryError:
                last = row['seq']; continue
            text = row['search_text']
            pos = text.lower().find(query.lower()) if query else 0
            hit = {'recordId': row['record_id'], 'sessionId': row['session_id'], 'agentId': row['agent_id'],
                   'kind': row['kind'], 'origin': row['origin'], 'created': row['created'],
                   'snippet': text[max(0, pos - 100):max(0, pos - 100) + 800],
                   'historyRef': self._ref(row), 'evidenceState': row['evidence_state']}
            cost = len(encode(hit))
            if used + cost > 23000:
                break
            hits.append(hit); used += cost; last = row['seq']
        more = len(rows) > size or last != (rows[-1]['seq'] if rows else before)
        next_cursor = base64.urlsafe_b64encode(encode({'filter': signature, 'high': high, 'before': last}).encode()).decode() if more else None
        return {'hits': hits, 'nextCursor': next_cursor, 'hasMore': more, 'truncated': more,
                'coverage': 'partial' if more else 'complete'}

    def assert_private_workspace(self, workspace):
        workspace = Path(workspace).resolve()
        private = self.root.resolve()
        if private == workspace or workspace in private.parents or workspace == (private / 'history') or (private / 'history') in workspace.parents or workspace == (private / 'memory') or (private / 'memory') in workspace.parents:
            raise HistoryError('HISTORY_PRIVATE_ROOT_OVERLAPS_WORKSPACE')

    def ensure_session_binding(self, sid, project_id, workspace=None, root_session_id=None, agent_id=None):
        """Only harness registry may call this; immutable once any raw is recorded."""
        identifier(sid)
        if workspace:
            self.assert_private_workspace(workspace)
        if project_id is not None:
            identifier(project_id)
        existing = self.bind_session(sid)
        agent = identifier(agent_id or existing['agent_id'])
        root = identifier(root_session_id or existing['root_session_id'])
        recorded = self.db.execute('SELECT 1 FROM history_records WHERE session_id=? LIMIT 1', (sid,)).fetchone()
        if recorded and (existing['project_id'] != project_id or existing['agent_id'] != agent or existing['root_session_id'] != root):
            raise HistoryError('HISTORY_BINDING_CONFLICT')
        with self.db:
            self.db.execute('UPDATE history_sessions SET project_id=?,agent_id=?,root_session_id=? WHERE session_id=?',
                            (project_id, agent, root, sid))
        return self.bind_session(sid)

    def list_sessions(self, caller_sid, *, scope='self', session_id=None, agent_id=None, cursor=None, limit=20):
        caller = self.bind_session(caller_sid)
        if scope not in ('self', 'project'):
            raise HistoryError('HISTORY_SCOPE_DENIED')
        if scope == 'project' and (not caller['project_id'] or not self.authorization):
            raise HistoryError('HISTORY_SCOPE_DENIED')
        target = session_id or (caller_sid if scope == 'self' else None)
        signature = digest(encode([caller_sid, scope, target, agent_id]).encode())
        after = ''
        if cursor:
            try:
                token = json.loads(base64.urlsafe_b64decode(cursor))
                if token['filter'] != signature:
                    raise ValueError()
                after = token['after']
            except (ValueError, KeyError, TypeError):
                raise HistoryError('HISTORY_CURSOR_INVALID')
        clauses, args = ["status!='deleted'", 'session_id>?'], [after]
        clauses.append('session_id=?' if target else 'project_id=?'); args.append(target or caller['project_id'])
        if agent_id:
            clauses.append('agent_id=?'); args.append(agent_id)
        size = max(1, min(50, int(limit)))
        rows = self.db.execute('SELECT * FROM history_sessions WHERE ' + ' AND '.join(clauses) +
                              ' ORDER BY session_id LIMIT ?', (*args, size + 1)).fetchall()
        items = []
        for row in rows[:size]:
            after = row['session_id']
            try:
                self._allowed(caller_sid, row['session_id'])
            except HistoryError:
                continue
            items.append({'sessionId': row['session_id'], 'agentId': row['agent_id'], 'created': row['created'],
                          'status': row['status'], 'coverage': 'partial', 'title': '', 'lastActivity': row['created']})
        more = len(rows) > size
        return {'items': items, 'hasMore': more, 'nextCursor': base64.urlsafe_b64encode(
                encode({'filter': signature, 'after': after}).encode()).decode() if more else None}

    search = query_history
    read = read_reference

    def descendants(self, sid):
        return [r[0] for r in self.db.execute('WITH RECURSIVE tree(id) AS '
                '(SELECT id FROM sessions WHERE id=? UNION SELECT s.id FROM sessions s JOIN tree t ON s.parent_id=t.id) '
                'SELECT id FROM tree ORDER BY id', (sid,))]

    def _deletion_source(self, sid):
        ids = self.descendants(sid)
        if not ids or not self.critical_snapshot:
            raise HistoryError('CAPSULE_CRITICAL_PROVIDER_REQUIRED')
        critical = self.critical_snapshot(ids)
        if not isinstance(critical, dict) or any(k not in critical for k in CAPSULE_KEYS):
            raise HistoryError('CAPSULE_CRITICAL_COVERAGE_REQUIRED')
        # The hook returns safe retained state, never grants or credentials. Reject authority fields.
        from .continuity_memory import safe_state
        safe_state(critical)
        sessions = [self.store.get(i) for i in ids]
        contracts = [self.contract(i) for i in ids]
        refs = [dict(r) for i in ids for r in self.db.execute(
                'SELECT record_id,sha256,evidence_state FROM history_records WHERE session_id=? ORDER BY seq', (i,))]
        source = {'sessions': sessions, 'contracts': contracts, 'critical': critical, 'refs': refs}
        return ids, source, digest(encode(source).encode())

    def deletion_preview(self, sid, *, expected_revision=None, lessons=None, extraction_required=False,
                         extraction_succeeded=False, retained_refs=None):
        from .continuity_memory import safe_state
        if extraction_required and not extraction_succeeded:
            raise HistoryError('CAPSULE_EXTRACTION_FAILED')
        safe_state(lessons or [])
        ids, source, revision = self._deletion_source(sid)
        if expected_revision is not None and expected_revision != revision:
            raise HistoryError('DELETE_REVISION_CONFLICT')
        scope = self.bind_session(sid)
        # Deterministic exact owner text is retained, not merely a summary of it.
        contracts = []
        for contract in source['contracts']:
            pins = []
            for entry in contract['revisions']:
                pins.append({**entry, 'exactPayload': self._payload(contract['sessionId'], entry['record_id'])})
            contracts.append({**contract, 'revisions': pins})
        capsule = {'schemaVersion': 1, 'projectId': scope['project_id'], 'sessionIds': ids,
                   'asOf': time.time(), 'coverage': 'critical_ledgers', 'contracts': contracts,
                   'critical': source['critical'], 'lessons': lessons or [], 'evidenceRefs': source['refs'],
                   'expectedRevision': revision, 'untrusted': True, 'executionAuthority': False}
        retained = []
        for ref in retained_refs or []:
            record = self._record(sid, ref)
            if record['session_id'] not in ids:
                raise HistoryError('CAPSULE_EVIDENCE_SCOPE_DENIED')
            data = read(self.root, record['payload_ref'], record['sha256'])
            retained.append({'historyRef': self._ref(record), 'excerpt': data.decode('utf-8')[:4000],
                             'excerptSha256': digest(data.decode('utf-8')[:4000].encode()), 'coverage': 'excerpt'})
        capsule['retainedEvidence'] = retained
        data = encode(capsule).encode()
        cid, op = uuid.uuid4().hex, uuid.uuid4().hex
        path = write(self.root, ('memory', 'projects', scope['project_id'] or ('legacy_' + sid)), 'capsule_' + cid, data)
        if read(self.root, path, digest(data)) != data:
            raise HistoryError('CAPSULE_VERIFY_FAILED')
        with self.db:
            self.db.execute('INSERT INTO memory_capsules VALUES(?,?,?,?,?,?)',
                            (cid, scope['project_id'], path, digest(data), time.time(), 'validated'))
            self.db.execute('INSERT INTO history_deletions VALUES(?,?,?,?,?,?,?,NULL)',
                            (op, sid, encode(ids), revision, cid, 'prepared', time.time()))
        validation = self.validate_capsule(cid)
        return {'operationId': op, 'sessionIds': ids, 'expectedRevision': revision, 'capsuleId': cid,
                'estimatedReclaimBytes': sum(r[0] for i in ids for r in self.db.execute(
                    'SELECT bytes FROM history_records WHERE session_id=?', (i,))),
                'retainedSummary': {'contracts': len(contracts), 'critical': source['critical'], 'lessons': lessons or []},
                'validation': validation, 'warnings': ['Raw evidence will become deleted tombstones; physical DB bytes may remain.']}

    def validate_capsule(self, capsule_id):
        row = self.db.execute('SELECT * FROM memory_capsules WHERE capsule_id=?', (capsule_id,)).fetchone()
        if not row:
            raise HistoryError('CAPSULE_NOT_FOUND')
        capsule = json.loads(read(self.root, row['content_ref'], row['sha256']))
        if (capsule.get('schemaVersion') != 1 or capsule.get('executionAuthority') is not False
            or any(k not in capsule.get('critical', {}) for k in CAPSULE_KEYS)
            or not capsule.get('sessionIds') or 'contracts' not in capsule):
            raise HistoryError('CAPSULE_VERIFY_FAILED')
        for evidence in capsule.get('retainedEvidence', []):
            if digest(evidence['excerpt'].encode()) != evidence['excerptSha256']:
                raise HistoryError('CAPSULE_VERIFY_FAILED')
        return {'status': 'validated', 'errors': [], 'sha256': row['sha256']}

    def read_capsule(self, caller_sid, capsule_id):
        row = self.db.execute('SELECT * FROM memory_capsules WHERE capsule_id=?', (capsule_id,)).fetchone()
        caller = self.bind_session(caller_sid)
        if not row or not caller['project_id'] or caller['project_id'] != row['project_id']:
            raise HistoryError('HISTORY_SCOPE_DENIED')
        capsule = json.loads(read(self.root, row['content_ref'], row['sha256']))
        if not self.authorization or not all(self.authorization(caller_sid, sid, {'capsule': True}) for sid in capsule['sessionIds']):
            raise HistoryError('HISTORY_SCOPE_DENIED')
        return capsule

    def project_capsules(self, caller_sid, *, limit=3):
        """Capsule đã chốt của CÙNG project, mới nhất trước (LT-08: hội thoại mới đọc lại được).

        Project lấy từ bản ghim của CHÍNH người gọi — không nhận project từ tham số, nên không có
        đường đọc chéo project. Hàm chỉ trả id/thời điểm; nội dung vẫn phải qua `read_capsule` để
        mọi đường đọc đi qua đúng một cổng quyền.
        """
        if type(limit) is not int or not 1 <= limit <= 20:
            raise HistoryError('HISTORY_QUERY_INVALID')
        caller = self.bind_session(caller_sid)
        if not caller['project_id']:
            return []
        rows = self.db.execute("SELECT capsule_id,created FROM memory_capsules WHERE project_id=? "
                               "AND status='committed' ORDER BY created DESC LIMIT ?",
                               (caller['project_id'], limit)).fetchall()
        return [{'capsuleId': row['capsule_id'], 'created': row['created']} for row in rows]

    def delete_with_capsule(self, sid, *, operation_id, expected_revision, confirm=False):
        operation = self.db.execute('SELECT * FROM history_deletions WHERE operation_id=?', (operation_id,)).fetchone()
        if not operation or operation['session_id'] != sid or not confirm:
            raise HistoryError('DELETE_REQUIRES_CARRY_FORWARD')
        if expected_revision != operation['expected_revision']:
            raise HistoryError('DELETE_REVISION_CONFLICT')
        self.validate_capsule(operation['capsule_id'])
        ids = json.loads(operation['session_ids_json'])
        if operation['state'] == 'prepared':
            if not self.quiescence or not self.quiescence(ids):
                raise HistoryError('DELETE_NOT_QUIESCENT')
            with self.db:
                _, _, revision = self._deletion_source(sid)
                if revision != expected_revision:
                    raise HistoryError('DELETE_REVISION_CONFLICT')
                for i in ids:
                    self.db.execute("UPDATE history_records SET evidence_state='deleted',search_text='',deleted_at=? WHERE session_id=?", (time.time(), i))
                    self.db.execute("UPDATE history_segments SET status='deleted' WHERE record_id IN (SELECT record_id FROM history_records WHERE session_id=?)", (i,))
                    self.db.execute("UPDATE history_sessions SET status='deleted' WHERE session_id=?", (i,))
                    # Remove any embedded active-message previews; preserve only deleted manifest locator.
                    for compact in self.db.execute('SELECT checkpoint_id,manifest_json FROM history_compactions WHERE session_id=?', (i,)).fetchall():
                        manifest = json.loads(compact['manifest_json'])
                        for item in manifest.get('activeViewRefs', []):
                            item.pop('activeMessage', None)
                        self.db.execute("UPDATE history_compactions SET manifest_json=?,state='deleted',projection_status='deleted' WHERE checkpoint_id=?", (encode(manifest), compact['checkpoint_id']))
                    for table in ('checkpoints', 'events', 'journal'):
                        self.db.execute(f'DELETE FROM {table} WHERE session_id=?', (i,))
                    self.db.execute('DELETE FROM child_deliveries WHERE child_id=? OR recipient=?', (i, i))
                    self.db.execute('DELETE FROM children WHERE session_id=? OR parent_id=?', (i, i))
                    self.db.execute('DELETE FROM sessions WHERE id=?', (i,))
                self.db.execute("UPDATE history_deletions SET state='cleanup_pending' WHERE operation_id=?", (operation_id,))
                self.db.execute("UPDATE memory_capsules SET status='committed' WHERE capsule_id=?", (operation['capsule_id'],))
        return self.cleanup_deletion(operation_id)

    def cleanup_deletion(self, operation_id):
        operation = self.db.execute('SELECT * FROM history_deletions WHERE operation_id=?', (operation_id,)).fetchone()
        if not operation or operation['state'] not in ('cleanup_pending', 'deleted'):
            raise HistoryError('DELETE_REQUIRES_CARRY_FORWARD')
        session_ids = json.loads(operation['session_ids_json'])
        reclaimed = 0
        try:
            for sid in session_ids:
                for row in self.db.execute('SELECT * FROM history_records WHERE session_id=?', (sid,)):
                    path = self.root / row['payload_ref']
                    if path.exists() and not path.is_symlink():
                        reclaimed += path.stat().st_size
                    unlink(self.root, row['payload_ref'])
                    unlink(self.root, row['payload_ref'].rsplit('/', 1)[0] + '/segment_' + row['record_id'])
            if self.db.execute("SELECT 1 FROM sqlite_master WHERE name='history_projection_files'").fetchone():
                for sid in session_ids:
                    for row in self.db.execute('SELECT * FROM history_projection_files WHERE session_id=?', (sid,)):
                        unlink(row['workspace'], row['relpath'])
                from .history_projection import HistoryProjection
                projection = HistoryProjection(self)
                for workspace in {r[0] for sid in session_ids for r in self.db.execute('SELECT DISTINCT workspace FROM history_projection_files WHERE session_id=?', (sid,))}:
                    projection.refresh_index(workspace)
            with self.db:
                self.db.execute("UPDATE history_deletions SET state='deleted',last_error=NULL WHERE operation_id=?", (operation_id,))
        except OSError as exc:
            with self.db:
                self.db.execute("UPDATE history_deletions SET last_error=? WHERE operation_id=?", (str(exc), operation_id))
            return {'status': 'cleanup_pending', 'capsuleId': operation['capsule_id'], 'reclaimedBytes': 0,
                    'remainingBytes': None, 'retainedItems': ['capsule', 'business ledgers', 'plans']}
        return {'status': 'deleted', 'capsuleId': operation['capsule_id'], 'reclaimedBytes': reclaimed,
                'remainingBytes': None, 'retainedItems': ['capsule', 'business ledgers', 'plans']}

    def import_legacy(self, sid, data, *, source_key, max_bytes=2_000_000):
        """Bounded sniffing: workspace JSON masquerading as Markdown is untrusted evidence."""
        if isinstance(data, str):
            data = data.encode()
        if len(data) > max_bytes:
            raise HistoryError('HISTORY_IMPORT_TOO_LARGE')
        stripped = data.lstrip()
        try:
            payload = json.loads(stripped) if stripped[:1] in (b'{', b'[') else {'text': data.decode('utf-8')}
        except (ValueError, UnicodeError, RecursionError):
            raise HistoryError('HISTORY_IMPORT_INVALID')
        pending = [(payload, 0)]
        while pending:
            item, depth = pending.pop()
            if depth > 64:
                raise HistoryError('HISTORY_IMPORT_TOO_DEEP')
            if isinstance(item, dict):
                pending.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                pending.extend((v, depth + 1) for v in item)
        curated = isinstance(payload, dict) and payload.get('kind') in ('task', 'plan', 'decision', 'fact', 'blocker') and 'text' in payload
        return self.record_observation(sid, payload, source_type='legacy_import', source_key=source_key,
                                       origin='imported_history', kind='curated_journal' if curated else 'legacy_snapshot')

    def backfill_events(self, sid, *, after=0, limit=100):
        """Explicit paged migration, never a startup bulk parse or fake owner pin."""
        size = max(1, min(500, int(limit)))
        rows = self.db.execute('SELECT * FROM events WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?',
                               (sid, int(after), size + 1)).fetchall()
        refs = []
        for row in rows[:size]:
            refs.append(self.record_observation(sid, json.loads(row['payload']), source_type='legacy_event',
                        source_key=str(row['seq']), origin='imported_history', kind=row['kind']))
        return {'historyRefs': refs, 'nextAfter': rows[min(size, len(rows)) - 1]['seq'] if rows else int(after),
                'hasMore': len(rows) > size, 'coverage': 'partial', 'origin': 'unknown_legacy'}


    def critical_pins(self, sid, *, limit=8):
        """Bounded exact request/revision locators for brief-before-tail integration."""
        contract = self.contract(sid)
        revisions = contract['revisions']
        size = max(2, min(20, int(limit)))
        selected = revisions[:1] + revisions[max(1, len(revisions) - size + 1):]
        return {'sessionId': sid, 'currentRevision': contract['currentRevision'],
                'pins': [{'revision': entry['revision'], 'changeKind': entry['change_kind'],
                          'historyRef': self._ref(self.db.execute('SELECT * FROM history_records WHERE record_id=?',
                                        (entry['record_id'],)).fetchone())} for entry in selected],
                'omittedCount': len(revisions) - len(selected), 'contractLocator': {'sessionId': sid},
                'delegatedContractHashes': [entry['contract_hash'] for entry in contract['delegatedContracts']]}

    def reconcile_files(self, *, after=0, limit=100):
        """Bounded audit marks missing canonical files truthfully; never replay or prune."""
        size = max(1, min(500, int(limit)))
        rows = self.db.execute("SELECT * FROM history_records WHERE seq>? AND evidence_state!='deleted' ORDER BY seq LIMIT ?",
                               (int(after), size + 1)).fetchall()
        missing = []
        for row in rows[:size]:
            try:
                read(self.root, row['payload_ref'], row['sha256'])
                segment = self.db.execute('SELECT * FROM history_segments WHERE record_id=?', (row['record_id'],)).fetchone()
                if segment:
                    read(self.root, segment['private_relpath'], segment['sha256'])
            except (OSError, ValueError):
                missing.append(row['record_id'])
                with self.db:
                    self.db.execute("UPDATE history_records SET evidence_state='missing' WHERE record_id=?", (row['record_id'],))
                    self.db.execute("UPDATE history_segments SET status='missing' WHERE record_id=?", (row['record_id'],))
        return {'missingRefs': missing, 'nextAfter': rows[min(size, len(rows)) - 1]['seq'] if rows else int(after),
                'hasMore': len(rows) > size, 'orphanStagingPolicy': 'retained_not_authoritative'}
