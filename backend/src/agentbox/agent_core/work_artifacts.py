"""Immutable, session-owned Work Graph snapshots, with audited paginated reads.

SQLite is canonical; the workspace copy is for handoff. A file-write failure never
produces a finalized artifact. Reviewers consume references rather than prompt excerpts.
"""
import hashlib
import json
import time
import uuid

PAGE = 8000


class Artifacts:
    def __init__(self, graph):
        self.graph = graph
        self.db = graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_artifacts (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, session_id TEXT NOT NULL,
                metadata TEXT NOT NULL, content TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS work_artifacts_run ON work_artifacts(run_id);
            CREATE TABLE IF NOT EXISTS work_artifact_reads (
                check_id TEXT NOT NULL, artifact_id TEXT NOT NULL, start INTEGER NOT NULL,
                end INTEGER NOT NULL, reader_id TEXT NOT NULL, admission_seq INTEGER NOT NULL DEFAULT 0);
        ''')
        if 'admission_seq' not in {row['name'] for row in self.db.execute('PRAGMA table_info(work_artifact_reads)')}:
            with self.db:
                self.db.execute('ALTER TABLE work_artifact_reads ADD COLUMN admission_seq INTEGER NOT NULL DEFAULT 0')

    async def put(self, run, node_id, stage, text, binding, finalized, producer_id=None):
        aid = 'a-' + uuid.uuid4().hex
        count = self.db.execute('SELECT COUNT(*) FROM work_artifacts WHERE run_id=?',
                                (run['runId'],)).fetchone()[0] + 1
        owner = hashlib.sha256(run['sessionId'].encode()).hexdigest()[:20]
        path = f'.plans/work/{owner}/{run["runId"]}/{node_id}/{stage}/v{count}-{aid}.md'
        # Only harness-generated ids enter the path; no model-provided paths are used.
        result = await self.graph.rt.executor.execute('file_write', {'path': path, 'content': text},
                                                       run['sessionId'])
        if not isinstance(result, dict) or result.get('is_error'):
            raise ValueError('WORK_ARTIFACT_WRITE_FAILED: workspace copy not saved')
        meta = {'artifactId': aid, 'runId': run['runId'], 'nodeId': node_id, 'stage': stage,
                'version': count, 'path': path, 'chars': len(text),
                'contentHash': hashlib.sha256(text.encode('utf-8')).hexdigest(),
                'status': 'finalized' if finalized else 'partial', 'producerId': producer_id,
                'createdAt': time.time(), 'originTurn': self.graph.rt.active_turn.get(run['sessionId']), 'binding': binding}
        with self.db:
            self.db.execute('INSERT INTO work_artifacts VALUES(?,?,?,?,?)',
                            (aid, run['runId'], run['sessionId'], json.dumps(meta, ensure_ascii=False), text))
        return meta

    def get(self, run_id, aid):
        row = self.db.execute('SELECT * FROM work_artifacts WHERE id=? AND run_id=?', (aid, run_id)).fetchone()
        if row is None:
            raise ValueError('WORK_ARTIFACT_UNKNOWN: artifact is not owned by this run')
        meta = json.loads(row['metadata'])
        text = row['content']
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != meta['contentHash']:
            raise ValueError('WORK_ARTIFACT_CORRUPT: stored content hash changed')
        return meta, text

    def read(self, session, args):
        binding = (session.get('config') or {}).get('workBinding') or {}
        root = session.get('parent_id') or session['id']
        run_id = args.get('runId') or binding.get('runId')
        self.graph.resolve(root, run_id)  # ownership before exposing metadata or text
        aid = str(args.get('artifactId') or '')
        if session.get('parent_id') and aid not in binding.get('artifactIds', []):
            raise PermissionError('WORK_ARTIFACT_SCOPE: child may read only assigned snapshots')
        meta, text = self.get(run_id, aid)
        offset = int(args.get('offset') or 0)
        limit = int(args.get('limit') or PAGE)
        if offset < 0 or offset > len(text) or not 1 <= limit <= PAGE:
            raise ValueError(f'WORK_ARTIFACT_RANGE: offset 0..{len(text)}, limit 1..{PAGE}')
        end = min(len(text), offset + limit)
        cid = binding.get('checkId') or binding.get('inputReadId')
        if cid:
            with self.db:
                self.db.execute('INSERT INTO work_artifact_reads VALUES(?,?,?,?,?,?)',
                                (cid, aid, offset, end, session['id'], binding.get('admissionSeq', 0)))
        result = meta | {'offset': offset, 'content': text[offset:end], 'nextOffset': end if end < len(text) else None}
        if cid:
            prefix, complete = self.progress(cid, meta, session['id'])
            result['unreadOffset'] = None if complete else prefix
            result['coverageComplete'] = complete
            remaining = []
            for assigned_id in dict.fromkeys(binding.get('artifactIds', [])):
                assigned, _ = self.get(run_id, assigned_id)
                unread, done = self.progress(cid, assigned, session['id'])
                if not done:
                    remaining.append({'artifactId': assigned_id, 'nodeId': assigned['nodeId'],
                                      'unreadOffset': unread, 'chars': assigned['chars']})
            result['unreadArtifacts'] = remaining
            result['allAssignedArtifactsRead'] = not remaining
            result['readingInstruction'] = 'Read unreadOffset next, even if nextOffset is null. Every assigned range is required.'
        return result

    def input_closure(self, run_id, targets):
        """Resolve only immutable inputs bound to these targets, never every run artifact."""
        inputs, seen, visiting = [], set(), set()

        def visit(aid, expected=None, relation=None):
            if aid in visiting:
                raise ValueError('WORK_ARTIFACT_INPUT_CYCLE: bound input references form a cycle')
            meta, _ = self.get(run_id, aid)
            if expected is not None and meta != expected:
                raise ValueError('WORK_ARTIFACT_INPUT_CHANGED: metadata differs from the immutable registry')
            if meta['status'] != 'finalized':
                raise ValueError('WORK_ARTIFACT_INPUT_PARTIAL: a bound input is not finalized')
            if relation == 'lookup' and meta['binding'].get('purpose') != 'knowledge':
                raise ValueError('WORK_ARTIFACT_INPUT_KIND: lookup ref must name a knowledge artifact')
            if aid in seen:
                return meta
            seen.add(aid)
            visiting.add(aid)
            inputs.append(meta)
            binding = meta['binding']
            for ref in binding.get('lookupArtifactIds', []):
                visit(ref, relation='lookup')
            for node_id, dependency in binding.get('dependencies', {}).items():
                ref = dependency.get('artifact')
                if not ref:
                    continue
                source = visit(ref)
                if source['nodeId'] != node_id or (dependency.get('definition') and
                        source['binding'].get('nodeDefinition') != dependency['definition']):
                    raise ValueError('WORK_ARTIFACT_INPUT_BINDING: dependency snapshot does not match its binding')
            if binding.get('ownPlan'):
                plan = visit(binding['ownPlan'])
                if plan['nodeId'] != meta['nodeId'] or plan['stage'] != 'produce':
                    raise ValueError('WORK_ARTIFACT_INPUT_BINDING: ownPlan must name this node plan snapshot')
            visiting.remove(aid)
            return meta

        # Preserve targets first: caller uses the primary code snapshot separately.
        for target in targets:
            registered, _ = self.get(run_id, target['artifactId'])
            if registered != target:
                raise ValueError('WORK_ARTIFACT_INPUT_CHANGED: target differs from the immutable registry')
            if registered['status'] != 'finalized':
                raise ValueError('WORK_ARTIFACT_INPUT_PARTIAL: review target is not finalized')
        for target in targets:
            visit(target['artifactId'], target)
        return list(targets) + [meta for meta in inputs if meta['artifactId'] not in {t['artifactId'] for t in targets}]

    def progress(self, check_id, meta, reader_id):
        """Contiguous audited prefix, scoped to this exact check/artifact/reader."""
        admission = (self.graph.store.get(reader_id)['config'].get('workBinding') or {}).get('admissionSeq', 0)
        rows = self.db.execute('SELECT start,end FROM work_artifact_reads WHERE check_id=? '
                              'AND artifact_id=? AND reader_id=? AND admission_seq=? ORDER BY start',
                              (check_id, meta['artifactId'], reader_id, admission)).fetchall()
        end = 0
        for row in rows:
            if row['start'] > end:
                break
            end = max(end, row['end'])
        return end, end >= meta['chars'] and bool(rows)

    def covered(self, check_id, meta, reader_id):
        return self.progress(check_id, meta, reader_id)[1]
