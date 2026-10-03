"""Durable specialist checkpoints, root-owned interview and granted continuation.

Only user actions confirm answers. Requests release the model turn; typed jobs
either continue the original child under root rights or request a main decision.
"""
import asyncio
import json
import time
import uuid

from . import work_policy


class FeedbackError(ValueError):
    def __init__(self, code, message, status=409, details=None):
        super().__init__(code + ': ' + message)
        self.code, self.status = code, status
        if details:
            self.details = details


# W7.2 — one tool, per-action contract. Checked before any other logic so the
# model gets the exact field, a hint where the value comes from and the args it
# actually sent. Never aliases: a missing requestId is not guessed from the only
# open request, and a needs_user is never downgraded to a checkpoint.
CHILD_ACTIONS = ('needs_user', 'needs_evidence', 'checkpoint', 'read')
MAIN_ACTIONS = ('status', 'resume', 'cancel', 'read')
ACTION_FIELDS = {
    'needs_user': {'required': ('checkpoint', 'questions'), 'forbidden': ()},
    'needs_evidence': {'required': ('checkpoint',), 'forbidden': ('questions', 'decisionKeys')},
    'checkpoint': {'required': ('checkpoint',), 'forbidden': ('questions', 'decisionKeys')},
    'status': {'required': ('runId',), 'forbidden': ('checkpoint',)},
    'resume': {'required': ('requestId', 'revision'), 'forbidden': ('checkpoint', 'questions')},
    'cancel': {'required': ('requestId', 'revision'), 'forbidden': ('checkpoint', 'questions')},
    'read': {'required': ('requestId',), 'forbidden': ()},
}
FIELD_HINTS = {
    'runId': "runId from work_graph(action='status') or the work_run/work_check result",
    'requestId': "requestId from work_report(action='status', runId) or the work_feedback event",
    'revision': "current revision from work_report(action='status', runId)",
    'checkpoint': 'save your findings so far as checkpoint text (1..60000 characters)',
    'questions': '1..3 questions, each with 2..4 options',
}
FORBIDDEN_HINTS = {
    'questions': 'questions belong to needs_user; evidence requests use reason',
    'checkpoint': 'checkpoint text belongs to a bound child report; main uses context',
    'decisionKeys': 'decisionKeys belong to needs_user',
}


MAIN_INTERVIEW = 'main_interview'


def _missing(value):
    return value is None or isinstance(value, (str, list, dict)) and not (value.strip() if isinstance(value, str) else value)


def check_action_fields(args, actor):
    """Raise WORK_REPORT_ACTION / _FIELD_REQUIRED / _FIELD_FORBIDDEN, else None."""
    from .tool_arg_errors import field_details
    args = args if isinstance(args, dict) else {}
    action = args.get('action')
    allowed = CHILD_ACTIONS if actor == 'child' else MAIN_ACTIONS
    if action not in allowed:
        message = ('child uses needs_user, needs_evidence or checkpoint (or read for its own request)'
                   if actor == 'child' else
                   'main uses status, resume, cancel or read; ask the user with interview(workRequestId, revision)')
        raise FeedbackError('WORK_REPORT_ACTION', message + f'; received action={action!r}', 400,
                            field_details('action', action, args, 'allowed actions: ' + ', '.join(allowed)))
    rule = ACTION_FIELDS[action]
    for name in rule['required']:
        if _missing(args.get(name)):
            hint = FIELD_HINTS.get(name)
            raise FeedbackError('WORK_REPORT_FIELD_REQUIRED', f'{name} required for action={action}'
                                + (f'; hint: {hint}' if hint else ''), 400, field_details(name, action, args, hint))
    for name in rule['forbidden']:
        if name in args and not _missing(args.get(name)):
            hint = FORBIDDEN_HINTS.get(name)
            raise FeedbackError('WORK_REPORT_FIELD_FORBIDDEN', f'{name} not allowed for action={action}'
                                + (f'; {hint}' if hint else ''), 400, field_details(name, action, args, hint))


def service(rt):
    return __import__('agentbox.agent_core.work_graph', fromlist=['service']).service(rt).feedback


def evidence_signature(event):
    """Successful opened content, not its event ID/time or a path alone."""
    result, args = event.get('result') or {}, event.get('args') or {}
    name = event.get('name')
    if name == 'verify_exec' and isinstance(result, dict):
        # W6.1.3: a receipt proves a computation, never an opened source. A timeout is still an
        # observation (is_error with receipt); an unavailable sandbox has no receipt.
        receipt = result.get('receipt')
        if not isinstance(receipt, dict) or not receipt.get('codeHash') or not receipt.get('outputHash'):
            return None
        return {'ref': 'verify:' + str(receipt['codeHash']), 'kind': 'verify_exec',
                'contentHash': receipt['outputHash'], 'range': None}
    if not isinstance(result, dict) or result.get('is_error'):
        return None
    if name in ('web_fetch', 'read_source'):
        quality = result.get('quality')
        if quality is not None:
            if not isinstance(quality, dict) or quality.get('verdict') not in ('ok', 'thin'):
                return None
        else:
            status = result.get('status', result.get('statusCode'))
            if status is not None and (not isinstance(status, int) or isinstance(status, bool) or not 200 <= status < 300):
                return None
    content = result.get('content') or result.get('text') or result.get('output')
    if not content:
        return None
    if name in ('file_read', 'web_fetch'):
        ref = args.get('path') or args.get('url')
    elif name == 'read_source':
        ref = result.get('url') or args.get('url') or args.get('ref')
    elif name == 'terminal_exec' and result.get('exit_code', result.get('exitCode')) == 0:
        ref = 'command:' + str(args.get('command') or '')
    elif name == 'work_artifact_read' and result.get('status') == 'finalized':
        ref = 'artifact:' + str(result.get('artifactId') or '')
    else:
        return None
    if not isinstance(ref, str) or not ref:
        return None
    # Actual reader offsets distinguish source ranges; caller's requested limits do not.
    actual_range = {k: result[k] for k in ('offset', 'endOffset') if k in result}
    return {'ref': ref, 'kind': name, 'contentHash': work_policy.digest(content), 'range': actual_range}


def input_snapshots(feedback, child_id, work):
    """A child's own checkpoint text cannot grant itself a fresh computation budget."""
    values = []
    for aid in work.get('artifactIds', []):
        meta, _ = feedback.graph.artifacts.get(work['runId'], aid)
        if (meta['status'] != 'finalized' or meta['binding'].get('checkpoint')
                or meta['binding'].get('purpose') == 'check_inputs'):
            continue
        source = meta['binding'].get('codeSnapshot')
        # HEAD/criticalChanges are validation/risk metadata, not fresh code.
        source = {'hash': source['hash']} if isinstance(source, dict) and source.get('hash') else None
        if child_id is not None and meta.get('producerId') == child_id:
            if source:
                values.append({'codeSnapshot': source})
        else:
            values.append({k: meta[k] for k in ('nodeId', 'stage', 'contentHash')} | {'codeSnapshot': source})
    return sorted({work_policy.digest(v): v for v in values}.values(), key=work_policy.digest)


class Feedback:
    def __init__(self, graph):
        self.graph, self.rt, self.db = graph, graph.rt, graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_requests (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                child_id TEXT NOT NULL, invocation TEXT NOT NULL, request_hash TEXT NOT NULL,
                doc TEXT NOT NULL, UNIQUE(child_id, invocation));
            CREATE TABLE IF NOT EXISTS work_feedback_invocations (
                owner_id TEXT NOT NULL, invocation TEXT NOT NULL, request_hash TEXT NOT NULL,
                result TEXT NOT NULL, PRIMARY KEY(owner_id, invocation));
            CREATE TABLE IF NOT EXISTS work_feedback_outbox (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, request_id TEXT NOT NULL,
                status TEXT NOT NULL, doc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS work_resume_inputs (
                child_id TEXT NOT NULL, input_hash TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(child_id,input_hash));
        ''')
        from .work_feedback_history import CardHistory
        self.history = CardHistory(self)
        self.history.recover()

    def get(self, rid, owner=None):
        row = self.db.execute('SELECT * FROM work_requests WHERE id=?', (rid,)).fetchone()
        if not row or owner is not None and row['owner_id'] != owner:
            raise FeedbackError('WORK_REQUEST_UNKNOWN', 'request does not belong to this session', 404)
        return json.loads(row['doc'])

    def save(self, doc):
        self.db.execute('UPDATE work_requests SET doc=? WHERE id=?',
                        (json.dumps(doc, ensure_ascii=False), doc['requestId']))

    def records(self, run_id):
        return [json.loads(r['doc']) for r in self.db.execute(
            'SELECT doc FROM work_requests WHERE run_id=? ORDER BY rowid', (run_id,))]

    def opened(self, sid, child_id, after=None, before=None):
        """Exclude self-written artifacts and input indices, including file copies."""
        own = [json.loads(r['metadata']) for r in self.db.execute(
            "SELECT metadata FROM work_artifacts WHERE json_extract(metadata,'$.producerId')=? "
            "OR json_extract(metadata,'$.binding.purpose')='check_inputs'", (child_id,))]
        own_refs = {m['path'].replace('\\', '/').removeprefix('./') for m in own}
        own_refs.update('artifact:' + m['artifactId'] for m in own)
        rows = self.db.execute("SELECT seq,created,payload FROM events WHERE session_id=? AND kind='tool_end' ORDER BY seq", (sid,))
        proofs = []
        for row in rows:
            if after is not None and row['created'] <= after or before is not None and row['created'] > before:
                continue
            proof = evidence_signature(json.loads(row['payload']))
            ref = proof['ref'].replace('\\', '/').removeprefix('./') if proof else ''
            if proof and not any(ref == own_ref or ref.endswith('/' + own_ref) for own_ref in own_refs):
                proofs.append(proof | {'sourceSeq': row['seq']})
        return proofs

    def known_evidence(self, doc):
        proofs = self.opened(doc['childId'], doc['childId'], before=doc['createdAt'])
        for old in self.records(doc['runId']):
            if old['childId'] == doc['childId'] and old['requestId'] != doc['requestId']:
                proofs.extend(old.get('evidenceProofs', []))
        return {work_policy.digest({k:v for k,v in p.items() if k != 'sourceSeq'}) for p in proofs}

    def fingerprint(self, run, binding):
        node = next((n for n in run['nodes'] if n['id'] == binding.get('nodeId')), None)
        dependencies = self.graph.checks.binding(run, node, binding['stage']).get('dependencies') if node else self.graph.whole_binding(run)
        return work_policy.digest({'goal': run['goal'], 'node': work_policy.definition(node) if node else None,
                                   'dependencies': dependencies,
                                   'stage': binding['stage'], 'purpose': binding['purpose'],
                                   'artifactIds': binding.get('artifactIds', []),
                                   'checkKind': binding.get('checkKind')})

    def validate(self, doc):
        run = self.graph.current(doc['runId'])
        main = doc.get('kind') == MAIN_INTERVIEW  # owner-level question: no node assignment to drift
        if run['status'] in ('cancelled', 'rejected', 'shipped') or not main and self.fingerprint(run, doc['binding']) != doc['fingerprint']:
            pending = doc['status'] == 'needs_user'
            with self.db:
                doc.update(status='stale')
                if pending:
                    self.resolve_card(doc, 'assignment_changed')
                self.save(doc)
            raise FeedbackError('WORK_REQUEST_STALE', 'assignment changed or run closed; inspect the saved checkpoint')
        for aid in doc['binding'].get('artifactIds', []):
            self.graph.artifacts.get(run['runId'], aid)
        return run

    async def report(self, session, args, call_id):
        binding = session['config'].get('workBinding') or {}
        check_action_fields(args, 'child' if session.get('parent_id') else 'main')
        if args.get('action') == 'read':
            doc = self.get(args.get('requestId'),session.get('parent_id') or session['id'])
            if session.get('parent_id') and doc['childId'] != session['id']:
                raise FeedbackError('WORK_REQUEST_SCOPE','child may read only its own checkpoint/answers',403)
            self.validate(doc)
            self.record_main_interview(doc)
            return doc
        if not session.get('parent_id'):
            return self.main_action(session, args)
        if not binding.get('runId'):
            raise FeedbackError('WORK_REPORT_UNBOUND', 'only a bound Work Graph child can checkpoint', 403)
        run = self.graph.resolve(session['parent_id'], binding['runId'])
        kind = args.get('action')
        if kind not in ('needs_user', 'needs_evidence', 'checkpoint'):
            raise FeedbackError('WORK_REPORT_ACTION', 'child uses needs_user, needs_evidence or checkpoint', 400)
        text = args.get('checkpoint')
        if not isinstance(text, str) or not text.strip() or len(text) > 60000:
            raise FeedbackError('WORK_REPORT_INVALID', 'checkpoint must contain 1..60000 characters', 400)
        questions = args.get('questions') or []
        if kind == 'needs_user':
            questions = self.rt.normalize_interview({'questions': questions})
            if len(questions) > 3:
                raise FeedbackError('WORK_REPORT_INVALID', 'ask 1..3 questions per interview round', 400)
        elif questions:
            raise FeedbackError('WORK_REPORT_INVALID', 'questions belong to needs_user; evidence requests use reason', 400)
        keys, grant = [], None
        if kind == 'needs_user':
            from .work_grants import decision_keys
            if 'decisionKeys' not in args and self.graph.grants.any_for(run, binding):
                raise FeedbackError('WORK_DECISION_KEYS_INVALID',
                                    'main granted interview rights for this node/stage; send 1..3 decisionKeys '
                                    'matching the grant (omit them only when no grant exists)', 400)
            keys = decision_keys(args.get('decisionKeys'),len(questions)) if 'decisionKeys' in args else [q['id'] for q in questions]
            revoked = self.graph.grants.revoked(run, binding, keys)
            if revoked:
                raise FeedbackError('WORK_CAPABILITY_REVOKED', 'main revoked interview rights for '
                                    + ', '.join(sorted(keys)) + '; report a checkpoint to main instead of asking the user', 403)
            grant = self.graph.grants.find(run,binding,keys)
        invocation = str(args.get('invocationId') or call_id or '')
        if not 1 <= len(invocation) <= 120:
            raise FeedbackError('WORK_REPORT_INVOCATION', 'invocationId required, max 120 characters', 400)
        request_hash = work_policy.digest(args)
        old = self.db.execute('SELECT * FROM work_requests WHERE child_id=? AND invocation=?',
                              (session['id'], invocation)).fetchone()
        if old:
            if old['request_hash'] != request_hash:
                raise FeedbackError('WORK_REPORT_INVOCATION_CONFLICT', 'invocation already used with different content')
            return json.loads(old['doc'])
        pending = [d for d in self.records(run['runId']) if d['childId'] == session['id'] and
                   d['status'] not in ('consumed', 'stale', 'cancelled', 'resuming')]
        if pending:
            raise FeedbackError('WORK_REPORT_PENDING', 'original checkpoint is still waiting for main')
        meta = await self.graph.artifacts.put(run, binding.get('nodeId') or 'whole', binding['stage'],
                                               text, {'checkpoint': True}, False, session['id'])
        doc = {'requestId': 'wr-' + uuid.uuid4().hex, 'runId': run['runId'], 'ownerId': session['parent_id'],
               'childId': session['id'], 'originTurn': self.rt.active_turn.get(session['id']),
               'revision': 1, 'kind': kind, 'status': 'waiting_main', 'questions': questions,
               'answers': [], 'reason': str(args.get('reason') or '')[:3000], 'artifact': meta,
               'binding': binding, 'fingerprint': self.fingerprint(run, binding), 'createdAt': time.time()}
        if kind == 'needs_user':
            doc['decisionKeys'] = keys if grant or 'decisionKeys' in args else []
            if grant:
                doc['grantId'] = grant['grantId']
        with self.db:
            self.db.execute('INSERT INTO work_requests VALUES(?,?,?,?,?,?,?)',
                (doc['requestId'], run['runId'], doc['ownerId'], session['id'], invocation, request_hash,
                 json.dumps(doc, ensure_ascii=False)))
        if kind == 'needs_user' and doc.get('grantId'):
            conflict = self.decision_conflict(doc)
            if conflict:
                with self.db:
                    doc.update(routingReason='decision_conflict',conflictingRequestId=conflict['requestId'])
                    self.save(doc)
            elif grant['publishInterview']:
                self.open_interview(self.rt.store.get(doc['ownerId']),
                    {'workRequestId':doc['requestId'],'revision':doc['revision']},call_id,automatic=True)
                doc = self.get(doc['requestId'])
        self.rt.store.emit(session['parent_id'], 'work_feedback', doc)
        return doc

    def revision(self, doc, value):
        if isinstance(value, bool) or value != doc['revision']:
            raise FeedbackError('WORK_REQUEST_REVISION_CONFLICT', 'read work_report status and use current revision')

    def main_action(self, session, args):
        run = self.graph.resolve(session['id'], args.get('runId'))
        if args.get('action', 'status') == 'status':
            return {'runId': run['runId'], 'requests': self.records(run['runId'])}
        explicit = args.get('invocationId')
        if explicit is not None and (not isinstance(explicit, str) or not 1 <= len(explicit) <= 120):
            raise FeedbackError('WORK_REPORT_INVOCATION', 'invocationId must contain 1..120 characters', 400)
        digest = work_policy.digest(args)
        invocation = str(args.get('action')) + ':' + (explicit or digest)
        old = self.db.execute('SELECT request_hash,result FROM work_feedback_invocations WHERE owner_id=? AND invocation=?',
                              (session['id'], invocation)).fetchone()
        if old:
            if old['request_hash'] != digest:
                raise FeedbackError('WORK_REPORT_INVOCATION_CONFLICT', 'invocation already used with different content')
            saved = json.loads(old['result'])
            if saved['runId'] != run['runId']:
                raise FeedbackError('WORK_REQUEST_UNKNOWN', 'request is from another run', 404)
            self.history.reconcile(self.get(saved['requestId'], session['id']))
            return saved
        doc = self.get(args.get('requestId'), session['id'])
        if doc['runId'] != run['runId']:
            raise FeedbackError('WORK_REQUEST_UNKNOWN', 'request is from another run', 404)
        self.validate(doc)
        self.revision(doc, args.get('revision'))
        if args.get('action') == 'cancel':
            pending_card = self.card(doc) if doc['status'] == 'needs_user' else None
            with self.db:
                doc.update(status='cancelled', revision=doc['revision'] + 1)
                self.save(doc)
                self.db.execute("UPDATE work_feedback_outbox SET status='cancelled' WHERE request_id=? AND status IN ('pending','claimed')", (doc['requestId'],))
                if pending_card:
                    self.resolve_card(doc, 'session_cancelled', card=pending_card)
                    self.save(doc)
                self.db.execute('INSERT INTO work_feedback_invocations VALUES(?,?,?,?)',
                    (session['id'], invocation, digest, json.dumps(doc, ensure_ascii=False)))
            self.graph.continuations.cancel_request(doc['requestId'])
            self.rt.store.emit(session['id'], 'work_feedback', doc)
            return doc
        if doc['kind'] == MAIN_INTERVIEW:
            raise FeedbackError('WORK_REPORT_ACTION', 'a main interview is answered by the owner on its card; '
                                'read it with work_report(action="read", requestId)', 400)
        if args.get('action') != 'resume' or doc['kind'] == 'needs_user' and doc['status'] != 'interrupted':
            raise FeedbackError('WORK_REPORT_ACTION', 'main interviews needs_user via interview(workRequestId); resumes other checkpoints', 400)
        if doc['status'] not in ('waiting_main', 'ready', 'interrupted'):
            raise FeedbackError('WORK_REQUEST_NOT_READY', 'checkpoint cannot resume in this state')
        context = args.get('context') or ''
        if not isinstance(context, str) or len(context) > 16000:
            raise FeedbackError('WORK_REPORT_INVALID', 'context is a string of at most 16000 characters', 400)
        refs = args.get('evidenceRefs') or []
        if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) for ref in refs):
            raise FeedbackError('WORK_RESUME_EVIDENCE_REQUIRED', 'provide newly opened evidenceRefs; prose alone cannot reset budget', 400)
        opened = {p['ref']: p for p in self.opened(session['id'], doc['childId'], after=doc['createdAt'])}
        if not set(refs) <= set(opened):
            raise FeedbackError('WORK_RESUME_EVIDENCE_REQUIRED', 'evidenceRefs must match successful new read events')
        known = self.known_evidence(doc)
        proofs = [opened[ref] for ref in sorted(set(refs))]
        if not any(work_policy.digest({k:v for k,v in p.items() if k != 'sourceSeq'}) not in known for p in proofs):
            raise FeedbackError('WORK_RESUME_NO_PROGRESS', 'opened content is already known; preserve checkpoint and change strategy')
        with self.db:
            doc.update(status='ready', context=context, evidenceRefs=sorted(set(refs)), evidenceProofs=proofs,
                       revision=doc['revision'] + 1)
            self.save(doc)
            self.db.execute('INSERT INTO work_feedback_invocations VALUES(?,?,?,?)',
                            (session['id'], invocation, digest, json.dumps(doc, ensure_ascii=False)))
        return doc

    def decision_conflict(self, doc):
        """IDs define a logical decision; don't infer semantic equivalence from prose."""
        keys = set(doc.get('decisionKeys') or [])
        if not keys:
            return None
        for other in self.records(doc['runId']):
            if (other['requestId'] == doc['requestId'] or other['status'] in ('stale','cancelled')
                    or not keys & set(other.get('decisionKeys') or [])):
                continue
            try:
                self.validate(other)
            except FeedbackError:
                continue
            return other
        return None

    def open_interview(self, session, args, call_id, *, automatic=False):
        doc = self.get(args.get('workRequestId'), session['id'])
        self.validate(doc)
        self.revision(doc, args.get('revision'))
        if doc['kind'] != 'needs_user' or doc['status'] not in ('waiting_main', 'needs_user'):
            raise FeedbackError('WORK_REQUEST_NOT_READY', 'request is not waiting for an interview')
        if doc['status'] == 'needs_user':
            self.history.reconcile(doc)
            return self.card(doc)
        conflict = self.decision_conflict(doc)
        if conflict:
            raise FeedbackError('WORK_INTERVIEW_CONFLICT','decision already belongs to '+conflict['requestId']+'; resolve or cancel the conflicting request')
        questions = self.rt.normalize_interview(args) if args.get('questions') else doc['questions']
        if len(questions) > 3:
            raise FeedbackError('WORK_REPORT_INVALID', 'ask 1..3 questions per interview round', 400)
        with self.db:
            doc.update(status='needs_user', questions=questions, toolCallId=call_id,
                       publication='delegated' if automatic else 'main',requiresMainYield=not automatic,
                       title=str(args.get('title') or 'Câu hỏi làm rõ')[:160])
            card = self.card(doc)
            self.history.record(doc, 'decision_requested', card)
            self.history.event(session['id'], 'ui_intent', {'tab': 'decisions', 'target': {'requestId': card['decisionId']},
                                                          'reason': 'decision_requested'})
            self.save(doc)
        return card

    def open_main_interview(self, session, args, call_id, run_id):
        """W7.1 — main's own interview during an active run is a durable request, not a future.

        The card survives restart through CardHistory; main yields and reads the answers later with
        work_report(action='read', requestId). Answers go through `answer()` like a child request.
        """
        questions = self.rt.normalize_interview(args)
        if len(questions) > 3:
            raise FeedbackError('WORK_REPORT_INVALID', 'ask 1..3 questions per interview round', 400)
        invocation = str(call_id or args.get('invocationId') or 'interview-' + uuid.uuid4().hex)[:120]
        sid = session['id']
        request_hash = work_policy.digest({k: v for k, v in args.items() if k != 'invocationId'})
        old = self.db.execute('SELECT * FROM work_requests WHERE child_id=? AND invocation=?', (sid, invocation)).fetchone()
        if old:
            if old['request_hash'] != request_hash:
                raise FeedbackError('WORK_REPORT_INVOCATION_CONFLICT', 'invocation already used with different content')
            doc = json.loads(old['doc'])
            self.history.reconcile(doc)
            return self.card(doc)
        binding = {'runId': run_id, 'nodeId': None, 'stage': 'main', 'purpose': MAIN_INTERVIEW}
        doc = {'requestId': 'wr-' + uuid.uuid4().hex, 'runId': run_id, 'ownerId': sid, 'childId': sid,
               'originTurn': self.rt.active_turn.get(sid), 'revision': 1, 'kind': MAIN_INTERVIEW,
               'status': 'needs_user', 'questions': questions, 'answers': [], 'reason': '', 'artifact': None,
               'binding': binding, 'fingerprint': work_policy.digest(binding), 'decisionKeys': [],
               'toolCallId': call_id, 'publication': 'main', 'requiresMainYield': True,
               'title': str(args.get('title') or '').strip()[:160] or 'Câu hỏi làm rõ', 'createdAt': time.time()}
        with self.db:
            self.db.execute('INSERT INTO work_requests VALUES(?,?,?,?,?,?,?)',
                (doc['requestId'], run_id, sid, sid, invocation, request_hash, json.dumps(doc, ensure_ascii=False)))
            card = self.card(doc)
            self.history.record(doc, 'decision_requested', card)
            self.history.event(sid, 'ui_intent', {'tab': 'decisions', 'target': {'requestId': card['decisionId']},
                                                  'reason': 'decision_requested'})
            self.save(doc)
        return card | {'message': 'Interview card saved; this turn yields. The owner\'s answers arrive as a new '
                       f'main turn: read work_report(action="read", requestId="{doc["requestId"]}").'}

    def record_main_interview(self, doc):
        """Keep `run['interviews']` (whole binding / owner digest) in step with the durable answers.

        Idempotent: also called when main reads the request, which repairs a crash between the
        answer commit and this run save.
        """
        if doc.get('kind') != MAIN_INTERVIEW or doc['status'] != 'answered':
            return
        try:
            run = self.graph.current(doc['runId'])
            if any(i.get('requestId') == doc['requestId'] for i in run.get('interviews', [])):
                return
            run.setdefault('interviews', []).append({'decisionId': doc['requestId'], 'requestId': doc['requestId'],
                'status': 'resolved', 'answers': doc['answers'], 'at': round(time.time(), 3)})
            self.graph.save(run, 'interview', f'{len(doc["answers"])} answers')
        except Exception as exc:  # the answers stay durable on the request either way
            from ..observability.system_log import system_log
            system_log.write('work.interview.store_failed', level='warn', session_id=doc['ownerId'], message=str(exc)[:300])

    def card(self, doc):
        answered = {a['questionId'] for a in doc['answers']}
        return {'decisionId': doc['requestId'] + '-r' + str(doc['revision']), 'sessionId': doc['ownerId'],
                'kind': 'interview', 'question': doc.get('title', 'Câu hỏi làm rõ'), 'title': doc.get('title', 'Câu hỏi làm rõ'),
                'questions': [q for q in doc['questions'] if q['id'] not in answered],
                'options': [{'id': 'submit', 'label': 'Gửi câu trả lời', 'kind': 'approve'},
                            {'id': 'decide', 'label': 'Để agent quyết định', 'kind': 'alternative'}],
                'answers': json.loads(json.dumps(doc['answers'])), 'deadline': None, 'defaultChoice': 'decide',
                'toolCallId': doc.get('toolCallId'), 'runId': doc['runId'], 'workRequestId': doc['requestId'],
                'revision': doc['revision'], 'durable': True, 'resolved': False,
                'requiresMainYield':doc.get('requiresMainYield',True)}

    def pending(self, owner):
        docs = [json.loads(r['doc']) for r in self.db.execute(
            'SELECT doc FROM work_requests WHERE owner_id=?', (owner,))]
        for doc in docs:
            self.history.reconcile(doc)
        return [self.card(doc) for doc in docs if doc['status'] == 'needs_user']

    def resolve_card(self, doc, reason, *, card=None):
        """Close the existing UI contract without inventing an answer/consent."""
        self.history.record(doc, 'decision_resolved', (card or self.card(doc)) | {
            'status': 'cancelled', 'resolved': True, 'outcome': 'cancelled', 'reason': reason,
            'choice': None, 'resolvedAt': time.time()})

    def answer(self, owner, decision_id, choice, answers, invocation=None):
        try:
            rid, rev = decision_id.rsplit('-r', 1)
            revision = int(rev)
        except (AttributeError, ValueError):
            raise FeedbackError('WORK_REQUEST_INVALID', 'malformed decisionId', 400)
        payload = {'decisionId': decision_id, 'choice': choice, 'answers': answers}
        digest = work_policy.digest(payload)
        invocation = invocation or decision_id + ':' + digest
        old = self.db.execute('SELECT * FROM work_feedback_invocations WHERE owner_id=? AND invocation=?',
                              (owner, invocation)).fetchone()
        if old:
            if old['request_hash'] != digest:
                raise FeedbackError('WORK_REQUEST_INVOCATION_CONFLICT', 'invocation reused with different answers')
            self.history.reconcile(self.get(rid, owner))
            return json.loads(old['result'])
        doc = self.get(rid, owner)
        run = self.validate(doc)
        self.revision(doc, revision)
        if doc['status'] != 'needs_user':
            raise FeedbackError('WORK_REQUEST_NOT_READY', 'interview is not pending')
        remaining = {q['id']: q for q in self.card(doc)['questions']}
        if choice not in ('submit', 'decide') or choice == 'submit' and not isinstance(answers, list):
            raise FeedbackError('WORK_REQUEST_ANSWER_INVALID', 'submit needs an answers list; or explicitly choose decide', 400)
        supplied = answers if choice == 'submit' else [{'questionId': q, 'optionId': 'decide'} for q in remaining]
        ids = [a.get('questionId') for a in supplied if isinstance(a, dict)]
        if not ids or len(ids) != len(supplied) or len(ids) != len(set(ids)) or not set(ids) <= set(remaining):
            raise FeedbackError('WORK_REQUEST_ANSWER_INVALID', 'use unique unanswered questionIds', 400)
        if any(not a.get('optionId') and not str(a.get('text') or '').strip() for a in supplied):
            raise FeedbackError('WORK_REQUEST_ANSWER_INVALID', 'empty answer is not consent; use decide explicitly', 400)
        values = [self.rt.interview_answer(remaining[a['questionId']], a) for a in supplied]
        for value in values:
            value.update(confirmedAt=time.time(), requestRevision=revision, source='user_action')
        old_card = self.card(doc)
        doc['answers'].extend(values)
        doc['revision'] += 1
        done = len(doc['answers']) == len(doc['questions'])
        main = doc['kind'] == MAIN_INTERVIEW
        doc['status'] = ('answered' if main else 'ready') if done else 'needs_user'
        result = {'status': 'resolved', 'decisionId': decision_id, 'choice': choice, 'outcome': 'answered',
                  'answers': values, 'requestId': rid, 'revision': doc['revision'], 'remaining': not done}
        # Nothing that commits independently may be called inside this transaction.
        with self.db:
            # The old question round, its answer and any remaining round share
            # the answer/receipt/job transaction; a failed event rolls it back.
            self.history.record(doc, 'decision_requested', old_card)
            self.history.record(doc, 'decision_resolved', old_card | result | {
                'status': 'answered', 'resolved': True, 'reason': 'user', 'resolvedAt': time.time()})
            if not done:
                self.history.record(doc, 'decision_requested', self.card(doc))
            self.save(doc)
            self.db.execute('INSERT INTO work_feedback_invocations VALUES(?,?,?,?)',
                (owner, invocation, digest, json.dumps(result, ensure_ascii=False)))
            if done and main:
                job = {'action': 'main_decision', 'prompt': f'[Work Graph] The owner answered interview {rid}. '
                       f'Read work_report(action="read", requestId="{rid}"); treat decidedBy=user answers as confirmed '
                       'requirements and state agent-decided ones as assumptions, then continue the run.'}
                self.db.execute('INSERT INTO work_feedback_outbox VALUES(?,?,?,?,?)',
                    ('work-feedback-' + rid + '-' + str(doc['revision']), owner, rid, 'pending', json.dumps(job, ensure_ascii=False)))
            elif done:
                oid = 'work-feedback-' + rid + '-' + str(doc['revision'])
                rights = next((g for g in self.graph.grants.records(run['runId'])
                               if g['grantId'] == doc.get('grantId')), None)
                direct = bool(rights and rights['resumeOnAnswers'] and self.graph.grants.valid(rights, run, doc['binding']))
                job = ({'action': 'resume_child', 'runId': run['runId'], 'stage': doc['binding']['stage'],
                        'requestRevision': doc['revision'], 'childId': doc['childId']} if direct else
                       {'action': 'main_decision', 'prompt': f'[Work Graph] Answers saved for {rid}. Read work_report status; '
                        'continue the original child via work_run/work_check from the saved checkpoint. '
                        'New answers allow fresh owner-clamped turn budget; preserve lifetime usage and child identity.'})
                self.db.execute('INSERT INTO work_feedback_outbox VALUES(?,?,?,?,?)',
                    (oid, owner, rid, 'pending', json.dumps(job, ensure_ascii=False)))
            self.history.event(owner, 'work_feedback', doc)
        if done and main:
            self.record_main_interview(doc)  # after commit: graph.save commits on its own
        if done:
            self.graph.continuations.wake(run['runId'])
        return result

    def yielded(self, child_id):
        rows = self.db.execute('SELECT doc FROM work_requests WHERE child_id=? ORDER BY rowid DESC', (child_id,))
        return next((json.loads(r['doc']) for r in rows if json.loads(r['doc'])['status'] in ('waiting_main','needs_user','ready')), None)

    def ready(self, work):
        for doc in reversed(self.records(work['runId'])):
            b = doc['binding']
            if doc['status'] == 'ready' and all(b.get(k) == work.get(k) for k in ('nodeId', 'stage', 'purpose', 'checkKind')):
                self.validate(doc)
                return doc

    def consume(self, doc):
        with self.db:
            current = self.get(doc['requestId'])
            if current['status'] == 'resuming':
                current.update(status='consumed')
                self.save(current)

    def admission(self, doc, work):
        """Record before starting; an uncertain crash is not an automatic replay."""
        with self.db:
            current = self.get(doc['requestId'])
            if current['status'] != 'ready' or current['revision'] != doc['revision']:
                raise FeedbackError('WORK_RESUME_BUSY', 'request changed before admission')
            current.update(status='resuming', resumedBinding=work, resumedAt=time.time())
            self.save(current)

    def cancel(self, owner):
        with self.db:
            for row in self.db.execute('SELECT doc FROM work_requests WHERE owner_id=?', (owner,)).fetchall():
                doc = json.loads(row['doc'])
                if doc['status'] not in ('consumed', 'stale', 'cancelled'):
                    if doc['status'] == 'needs_user':
                        self.resolve_card(doc, 'session_cancelled')
                    doc['status'] = 'cancelled'
                    self.save(doc)
            self.db.execute("UPDATE work_feedback_outbox SET status='cancelled' WHERE owner_id=? AND status IN ('pending','claimed')", (owner,))


async def pump(rt):
    """Dispatch typed jobs; notifications/granted handoffs never open a main turn.

    Retrying an admission that may have run tools would replay effects. Preserve an
    interrupted receipt instead, and let main inspect the durable ready request.
    """
    from . import work_graph
    if not work_graph.enabled():
        return
    feedback = service(rt)
    feedback.graph.handoffs.dispatch()
    for row in feedback.graph.continuations.rows():
        feedback.graph.continuations.kick(row)
    feedback.graph.decisions.pump()


async def resume_child(rt, owner, child_id, prompt, work, request=None):
    """New verified input admits fresh owner-clamped budget; retain lifetime telemetry."""
    child = rt.store.get(child_id)
    if child.get('parent_id') != owner['id']:
        raise FeedbackError('WORK_RESUME_OWNER', 'child belongs to another owner', 403)
    old = child['config'].get('workBinding') or {}
    if any(old.get(k) != work.get(k) for k in ('runId', 'nodeId', 'stage', 'purpose', 'checkKind')):
        raise FeedbackError('WORK_RESUME_BINDING', 'cannot reuse a child for a different assignment')
    if child['status'] in ('running', 'awaiting_decision') or rt.tasks.get(child_id) and not rt.tasks[child_id].done():
        raise FeedbackError('WORK_RESUME_BUSY', 'previous admission is still active')
    effective = child['config'].get('workBudget') or {}
    spent, tokens = rt.store.child_usage_from_events(child_id)
    step_limit = min(effective.get('requestedMaxSteps', effective.get('effectiveMaxSteps', child['config']['maxSteps'])), owner['config']['maxSteps'])
    deadline = min(effective.get('requestedDeadlineSeconds', effective.get('effectiveDeadlineSeconds', child['config']['deadlineSeconds'])), owner['config']['deadlineSeconds'])
    feedback = service(rt)
    controller = feedback.graph.continuations if work.get('controllerAction') else None
    if controller:
        controller.authorize_new(owner['id'], work)
    fresh = {'snapshots': input_snapshots(feedback, child_id, work),
             'answers': [{k:a.get(k) for k in ('question', 'answer', 'decidedBy', 'note')} for a in (request or {}).get('answers', [])],
             'evidence': sorted([{k:v for k,v in p.items() if k != 'sourceSeq'} for p in (request or {}).get('evidenceProofs', [])], key=work_policy.digest)}
    input_hash = work_policy.digest(fresh)
    old_inputs = input_snapshots(feedback, child_id, old)
    if not fresh['answers'] and not fresh['evidence'] and fresh['snapshots'] == old_inputs:
        raise FeedbackError('WORK_RESUME_NO_PROGRESS', 'no new user decision, opened evidence or code snapshot; route the repeated failure to main')
    if feedback.db.execute('SELECT 1 FROM work_resume_inputs WHERE child_id=? AND input_hash=?', (child_id,input_hash)).fetchone():
        raise FeedbackError('WORK_RESUME_NO_PROGRESS', 'this continuation input was already admitted; preserve checkpoint and change strategy')
    await rt.acquire_child_slot(owner['id'])
    try:
        current = rt.store.get(child_id)
        if current['status'] in ('running', 'awaiting_decision') or rt.tasks.get(child_id) and not rt.tasks[child_id].done():
            raise FeedbackError('WORK_RESUME_BUSY', 'another admission won the child slot')
        if request:
            saved = feedback.get(request['requestId'])
            feedback.validate(saved)
            if saved['status'] != 'ready' or saved['revision'] != request['revision']:
                raise FeedbackError('WORK_RESUME_BUSY', 'request already admitted or changed')
        if work.get('controllerOwned'):
            feedback.graph.continuations.authorized(request, feedback.validate(request))
        if controller:
            await controller.after_slot(owner['id'], work)
        if work.get('retestOf'):
            await feedback.graph.checks.revalidate_retest(owner['id'], work)
        # The owner can lower limits while this admission waits for a slot.
        owner = rt.store.get(owner['id'])
        step_limit = min(effective.get('requestedMaxSteps', effective.get('effectiveMaxSteps', child['config']['maxSteps'])), owner['config']['maxSteps'])
        deadline = min(effective.get('requestedDeadlineSeconds', effective.get('effectiveDeadlineSeconds', child['config']['deadlineSeconds'])), owner['config']['deadlineSeconds'])
        work = dict(work)
        work['admissionSeq'] = rt.store.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE session_id=?', (child_id,)).fetchone()[0]
        config = child['config']
        if owner['config'].get('outputTokenCeiling') is not None:
            config['outputTokenCeiling'] = owner['config']['outputTokenCeiling']
        else:
            config.pop('outputTokenCeiling', None)
        # W1.P: the owner's CURRENT role/tool settings are checked again after the slot wait.
        from .work_checks import capability_preflight
        need = {'role': child['role'], 'check': bool(work.get('checkId'))}
        if work.get('checkKind') == 'tests':
            need['tools'] = {'terminal_exec'}
        unavailable = capability_preflight(owner, need)
        if unavailable:
            code, _, message = unavailable.partition(': ')
            raise FeedbackError(code, message + ' (changed while waiting for a slot)')
        if work.get('checkId'):
            from .roles import work_check_tools
            from . import work_budget
            config['tools'] = sorted(work_check_tools(child['role'], owner['config']['tools']))
            request_budget = work_budget.requested(child['role'], work, None, 40,
                effective.get('requestedDeadlineSeconds', config['deadlineSeconds']))
            effective = effective | {'profile': request_budget['profile'],
                'requestedMaxSteps': request_budget['maxSteps'], 'requestedDeadlineSeconds': request_budget['deadlineSeconds']}
            step_limit = min(request_budget['maxSteps'], owner['config']['maxSteps'])
            deadline = min(request_budget['deadlineSeconds'], owner['config']['deadlineSeconds'])
        turn_budget = effective | {'effectiveMaxSteps': step_limit, 'effectiveDeadlineSeconds': deadline,
            'clamped': step_limit < effective.get('requestedMaxSteps', step_limit)
                       or deadline < effective.get('requestedDeadlineSeconds', deadline)}
        config.update(workBinding=work, workRemaining={'maxSteps': step_limit,
                      'deadlineSeconds': deadline}, workBudget=turn_budget)
        rt.store.update_config(child_id, config)
        if request:
            feedback.admission(request, work)
        with feedback.db:
            feedback.db.execute('INSERT INTO work_resume_inputs VALUES(?,?,?)', (child_id,input_hash,time.time()))
        # The legacy child ledger aggregates this identity; the event ledger keeps each turn.
        rt.store.db.execute("UPDATE children SET status='started',finished=NULL,started=?,parent_turn=? WHERE session_id=?",
                            (time.time(), 0 if controller or work.get('controllerOwned') else rt.active_turn.get(owner['id'], 0), child_id))
        rt.store.db.commit()
        rt.track_child_slot(child_id, owner['id'])
        if controller:
            controller.register_new(owner['id'], work, child_id)
        if work.get('progressAdmissionId'):
            feedback.graph.progress.attach(work['progressAdmissionId'], owner['id'], work, child_id)
        task = rt.start(child_id, prompt, invocation_id='work-resume-' + uuid.uuid4().hex)
    except BaseException:
        rt.release_child_slot(owner['id'], child_id)
        raise
    task.add_done_callback(lambda _: rt.release_child_slot(owner['id'], child_id))
    started = time.monotonic()
    try:
        answer = await task
    except asyncio.CancelledError:
        await rt.stop(child_id)
        if request:
            saved = feedback.get(request['requestId'])
            if saved['status'] == 'resuming':
                with feedback.db:
                    saved.update(status='interrupted')
                    feedback.save(saved)
        lifetime_steps, lifetime_tokens = rt.store.child_usage_from_events(child_id)
        if (rt.store.child(child_id) or {}).get('status') == 'started':
            rt.store.child_finish(child_id, 'cancelled', reason='WORK_RESUME_CANCELLED',
                                  steps_used=lifetime_steps, output_tokens=lifetime_tokens, answer_chars=0)
        raise
    feedback = service(rt)
    checkpoint = feedback.yielded(child_id)
    if request:
        feedback.consume(request)
    events = rt.store.db.execute("SELECT kind,payload FROM events WHERE session_id=? AND seq>? ORDER BY seq",
                                 (child_id, work['admissionSeq'])).fetchall()
    finish = next((json.loads(r['payload']) for r in reversed(events) if r['kind'] == 'finish'), {})
    error = next((json.loads(r['payload']) for r in reversed(events) if r['kind'] == 'error'), {})
    status = 'needs_user' if checkpoint else 'partial' if finish.get('partial') else rt.store.get(child_id)['status']
    lifetime_steps, lifetime_tokens = rt.store.child_usage_from_events(child_id)
    result = {'sessionId': child_id, 'role': child['role'], 'status': status, 'summary': answer or '',
              'is_error': status not in ('completed', 'needs_user'), 'stepsUsed': lifetime_steps - spent,
              'outputTokens': lifetime_tokens - tokens, 'lifetimeStepsUsed': lifetime_steps,
              'lifetimeOutputTokens': lifetime_tokens,
              'reason': error.get('code') or finish.get('reason'), 'wallMs': round((time.monotonic()-started)*1000),
              'work': work, 'budget': turn_budget, 'resumed': True,
              'tools_run': [json.loads(r['payload']).get('name') for r in events if r['kind'] == 'tool_start']}
    if checkpoint:
        result['request'] = checkpoint
    rt.store.child_finish(child_id, status, reason=result['reason'], steps_used=lifetime_steps,
                          output_tokens=lifetime_tokens, answer_chars=len(answer or ''))
    rt.store.emit(owner['id'], 'child', result)
    return result
