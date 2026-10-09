"""Full readable snapshots. Projection is never a source of authority.

Transport can send render_snapshot()'s bounded parts to host or Docker; no private
canonical directory needs to be mounted into a workspace. No total trim/retention.
"""
import json

from .history_files import digest, encode, read, write, read_unverified

PART_CHARS = 64000


def render_snapshot(manifest, messages, part_chars=PART_CHARS):
    """Small snapshots live in the primary Markdown; huge snapshots have ordered parts."""
    size = max(512, int(part_chars))
    title = f'# Compaction {manifest["generation"]}\n\nFull provider-visible active view; protected system text withheld.\n\n'
    title += f'Session: {manifest["sessionId"]}; agent: {manifest["agentId"]}\n\n'
    blocks = []
    for index, message in enumerate(messages):
        withheld = isinstance(message, dict) and message.get('role') == 'system'
        content = '[withheld: protected system source]' if withheld else json.dumps(message, ensure_ascii=False, indent=2)
        ref = manifest['activeViewRefs'][index]['historyRef']
        header = f'## Message {index + 1}\n\nRole/origin: {message.get("role", "unknown") if isinstance(message, dict) else "unknown"}\n'
        header += f'History reference: `{encode(ref)}`\n\n'
        blocks.append((index + 1, header, content, withheld))
    full = title + ''.join(header + content + '\n\n' for _, header, content, _ in blocks)
    if len(full) <= size:
        return {'index': full, 'parts': [], 'coverage': [{'part': 0, 'message': i, 'offset': 0,
                'chars': len(content), 'sha256': digest(full.encode()), 'withheld': withheld}
                for i, _, content, withheld in blocks]}
    parts, coverage, buffer = [], [], ''
    def flush():
        nonlocal buffer
        if buffer:
            parts.append(buffer)
            buffer = ''
    for i, header, content, withheld in blocks:
        block = header + content + '\n\n'
        if len(block) <= size:
            if len(buffer) + len(block) > size:
                flush()
            buffer += block
            coverage.append({'part': len(parts) + 1, 'message': i, 'offset': 0,
                             'chars': len(content), 'withheld': withheld})
        else:
            flush()
            available = max(1, size - len(header) - 100)
            for offset in range(0, len(content), available):
                part = header + f'Continuation characters {offset}–{min(offset + available, len(content))}\n\n'
                part += content[offset:offset + available] + '\n'
                parts.append(part)
                coverage.append({'part': len(parts), 'message': i, 'offset': offset,
                                 'chars': min(available, len(content) - offset), 'withheld': withheld})
    flush()
    for item in coverage:
        item['sha256'] = digest(parts[item['part'] - 1].encode())
        title += f'- part_{item["part"]:03d}: message {item["message"]}, offset {item["offset"]}, chars {item["chars"]}, SHA256 {item["sha256"]}\n'
    return {'index': title, 'parts': parts, 'coverage': coverage}


class HistoryProjection:
    def __init__(self, history):
        self.history = history
        history.db.execute('CREATE TABLE IF NOT EXISTS history_projection_files('
                           'session_id TEXT, checkpoint_id TEXT, workspace TEXT, relpath TEXT, sha256 TEXT,'
                           'PRIMARY KEY(workspace,relpath))')
        history.db.commit()

    def export_compaction(self, checkpoint_id, workspace):
        self.history.assert_private_workspace(workspace)
        row = self.history.db.execute('SELECT * FROM history_compactions WHERE checkpoint_id=?', (checkpoint_id,)).fetchone()
        if not row:
            raise ValueError('CHECKPOINT_NOT_FOUND')
        manifest = json.loads(row['manifest_json'])
        messages = self.history.restore_compaction(manifest)
        scope = self.history.bind_session(row['session_id'])
        components = ('.session-history', scope['root_session_id'],
                      'general_agent' if scope['session_id'] == scope['root_session_id'] else 'subagent_' + scope['agent_id'])
        # Check group identity from canonical index, not from a role name/prefix.
        identity = {k: scope[k] for k in ('project_id', 'root_session_id', 'session_id', 'agent_id', 'parent_agent_id')}
        rendered = render_snapshot(manifest, messages)
        base = f'compaction_{manifest["generation"]:03d}'
        files = [(base + '.md', rendered['index']), (base + '.json', encode({'manifest': manifest, 'coverage': rendered['coverage']}))]
        files += [(base + f'.part_{i:03d}.md', part) for i, part in enumerate(rendered['parts'], 1)]
        try:
            existing = self.history.db.execute('SELECT DISTINCT session_id FROM history_projection_files '
                                               'WHERE workspace=? AND relpath LIKE ?',
                                               (str(workspace), '/'.join(components) + '/%')).fetchall()
            if any(r[0] != row['session_id'] for r in existing):
                raise ValueError('HISTORY_GROUP_COLLISION')
            try:
                marker = json.loads(read_unverified(workspace, components, 'identity.json'))
                if marker != identity:
                    raise ValueError('HISTORY_GROUP_COLLISION')
            except FileNotFoundError:
                pass
            files.insert(0, ('identity.json', encode(identity)))
            for name, text in files:
                data = text.encode()
                path = write(workspace, components, name, data)
                if read(workspace, path, digest(data)) != data:
                    raise ValueError('PROJECTION_VERIFY_FAILED')
                with self.history.db:
                    self.history.db.execute('INSERT OR REPLACE INTO history_projection_files VALUES(?,?,?,?,?)',
                        (row['session_id'], checkpoint_id, str(workspace), path, digest(data)))
            self.ensure_session(row['session_id'], workspace)
            self.refresh_index(workspace)
            with self.history.db:
                self.history.db.execute("UPDATE history_compactions SET projection_status='stored' WHERE checkpoint_id=?", (checkpoint_id,))
            return {'canonicalStored': True, 'projectionStored': True, 'projectionError': None,
                    'files': [name for name, _ in files]}
        except (OSError, ValueError) as exc:
            with self.history.db:
                self.history.db.execute("UPDATE history_compactions SET projection_status='degraded' WHERE checkpoint_id=?", (checkpoint_id,))
            return {'canonicalStored': True, 'projectionStored': False, 'projectionError': str(exc),
                    'errorCode': 'CHECKPOINT_FILE_FAILED'}

    def verify(self, checkpoint_id):
        rows = self.history.db.execute('SELECT * FROM history_projection_files WHERE checkpoint_id=?', (checkpoint_id,)).fetchall()
        if not rows:
            return 'projection_stale'
        try:
            for row in rows:
                read(row['workspace'], row['relpath'], row['sha256'])
        except (OSError, ValueError):
            return 'projection_stale'
        return 'stored'


    def ensure_session(self, sid, workspace):
        self.history.assert_private_workspace(workspace)
        scope = self.history.bind_session(sid)
        root_scope = self.history.bind_session(scope['root_session_id'])
        root_identity = {k: root_scope[k] for k in ('project_id', 'root_session_id', 'session_id', 'agent_id', 'parent_agent_id')}
        components = ('.session-history', scope['root_session_id'])
        try:
            marker = json.loads(read_unverified(workspace, components, 'session.json'))
            if marker != root_identity:
                raise ValueError('HISTORY_GROUP_COLLISION')
        except FileNotFoundError:
            pass
        data = encode(root_identity).encode()
        path = write(workspace, components, 'session.json', data)
        with self.history.db:
            self.history.db.execute('INSERT OR REPLACE INTO history_projection_files VALUES(?,?,?,?,?)',
                (root_scope['session_id'], None, str(workspace), path, digest(data)))
        return {'canonicalStored': True, 'projectionStored': True, 'sessionId': sid,
                'rootSessionId': scope['root_session_id'], 'agentId': scope['agent_id']}

    def refresh_index(self, workspace):
        rows = self.history.db.execute('SELECT DISTINCT s.* FROM history_sessions s JOIN history_projection_files p '
                                      "ON p.session_id=s.session_id WHERE p.workspace=? AND s.status!='deleted'",
                                      (str(workspace),)).fetchall()
        body = {'schemaVersion': 1, 'projectionOnly': True, 'sessions': [dict(r) for r in rows]}
        write(workspace, ('.session-history',), 'INDEX.json', encode(body).encode())
        return body

    def export_journal(self, sid, workspace):
        scope = self.history.bind_session(sid)
        self.ensure_session(sid, workspace)
        components = ('.session-history', scope['root_session_id'],
                      'general_agent' if sid == scope['root_session_id'] else 'subagent_' + scope['agent_id'])
        # Curated journal is explicitly not the raw transcript. No cumulative journal in snapshots.
        rows = self.history.db.execute('SELECT * FROM journal WHERE session_id=? ORDER BY seq', (sid,))
        body = '# Curated journal (not raw transcript)\n\n'
        for row in rows:
            body += f'## {row["seq"]}: {row["kind"]}\n\n{row["text"]}\n\n'
        contract = self.history.contract(sid)
        body += '\n## Critical contract locator\n\n' + encode(contract) + '\n'
        path = write(workspace, components, 'journal.md', body.encode())
        with self.history.db:
            self.history.db.execute('INSERT OR REPLACE INTO history_projection_files VALUES(?,?,?,?,?)',
                                   (sid, None, str(workspace), path, digest(body.encode())))
        self.refresh_index(workspace)
        return {'canonicalStored': True, 'projectionStored': True, 'projectionError': None}
