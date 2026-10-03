"""Root-assigned, durable interview rights; no ambient permission for children."""
import json
import re
import time
import uuid

from . import work_policy
from .work_feedback import FeedbackError


def decision_keys(raw, count=None):
    if (not isinstance(raw, list) or not 1 <= len(raw) <= 3 or len(set(str(k) for k in raw)) != len(raw)
            or any(not isinstance(k, str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.:-]{0,79}', k) for k in raw)
            or count is not None and len(raw) != count):
        raise FeedbackError('WORK_DECISION_KEYS_INVALID', 'use 1..3 distinct stable decisionKeys, one for each question', 400)
    return raw


class Grants:
    def __init__(self, graph):
        self.graph, self.db = graph, graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_grants (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL, doc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS work_grant_invocations (
                owner_id TEXT NOT NULL, invocation TEXT NOT NULL, request_hash TEXT NOT NULL,
                result TEXT NOT NULL, PRIMARY KEY(owner_id,invocation));
        ''')

    def records(self, run_id):
        return [json.loads(row['doc']) for row in self.db.execute('SELECT doc FROM work_grants WHERE run_id=? ORDER BY rowid', (run_id,))]

    def scope(self, run, node_id, stage, purpose, check_kind=None):
        node = next((n for n in run['nodes'] if n['id'] == node_id), None)
        if not node or stage not in node['stages'] or purpose not in ('produce', 'review'):
            raise FeedbackError('WORK_GRANT_SCOPE_INVALID', 'grant needs an existing node/stage and produce or review purpose', 400)
        return work_policy.digest({'ownerGoal':run['goal'], 'node':work_policy.definition(node),
                                   'stage':stage, 'purpose':purpose, 'checkKind':check_kind})

    def valid(self, doc, run, binding):
        if doc['status'] != 'active' or run['status'] in ('cancelled','shipped','rejected'):
            return False
        if any(doc.get(k) != binding.get(k) for k in ('nodeId','stage','purpose','checkKind')):
            return False
        try:
            return doc['scopeHash'] == self.scope(run, doc['nodeId'], doc['stage'], doc['purpose'], doc.get('checkKind'))
        except FeedbackError:
            return False

    def find(self, run, binding, keys):
        return next((g for g in reversed(self.records(run['runId'])) if self.valid(g,run,binding)
                     and set(keys) <= set(g['decisionKeys'])), None)

    def any_for(self, run, binding):
        """#6475 — có grant nào (kể cả vừa bị thu hồi) trỏ đúng node/stage/purpose/checkKind không.

        Dùng để bắt buộc `decisionKeys` trên `needs_user`: khi main đã giao quyền hỏi cho đúng ô
        này thì con KHÔNG được bỏ trường khoá quyết định — bỏ đi là im lặng rơi khỏi đường grant
        (mất kiểm tra thu hồi, mất khớp câu hỏi với quyền, card thiếu khoá).
        """
        return any(g.get('status') in ('active', 'revoked')
                   and all(g.get(k) == binding.get(k) for k in ('nodeId', 'stage', 'purpose', 'checkKind'))
                   for g in self.records(run['runId']))

    def revoked(self, run, binding, keys):
        """W1.P — the latest grant covering these keys, when main revoked it mid-turn.

        A revoked right must block the NEXT tool call instead of silently degrading to an
        untracked interview: the child falls back to a checkpoint for main.
        """
        latest = next((g for g in reversed(self.records(run['runId']))
                       if g.get('status') in ('active', 'revoked') and set(keys) <= set(g['decisionKeys'])
                       and all(g.get(k) == binding.get(k) for k in ('nodeId', 'stage', 'purpose', 'checkKind'))), None)
        return latest if latest and latest['status'] != 'active' else None

    def action(self, session, args):
        if session.get('parent_id') or session['role'] != 'orchestrator':
            raise FeedbackError('WORK_ROOT_ONLY', 'only root may assign or revoke rights', 403)
        resolved = self.graph.resolve(session['id'], args.get('runId'))
        run = self.graph.current(resolved['runId'])
        invocation = args.get('invocationId')
        if not isinstance(invocation, str) or not 1 <= len(invocation) <= 120:
            raise FeedbackError('WORK_GRANT_INVOCATION', 'invocationId required (1..120 characters)', 400)
        digest = work_policy.digest(args)
        old = self.db.execute('SELECT request_hash,result FROM work_grant_invocations WHERE owner_id=? AND invocation=?', (session['id'],invocation)).fetchone()
        if old:
            if old['request_hash'] != digest:
                raise FeedbackError('WORK_GRANT_INVOCATION_CONFLICT', 'invocation reused for different rights')
            return json.loads(old['result'])
        if run['status'] in ('cancelled','shipped','rejected'):
            raise FeedbackError('WORK_RUN_CLOSED', 'closed run cannot grant rights')
        if args.get('action') == 'grant':
            if isinstance(args.get('revision'),bool) or args.get('revision') != run['revision']:
                raise FeedbackError('WORK_GRANT_REVISION_CONFLICT', f'read work_graph status; current revision is {run["revision"]}')
            keys = decision_keys(args.get('decisionKeys'))
            rights = {k:args.get(k,False) for k in ('publishInterview','resumeOnAnswers')}
            if any(not isinstance(v,bool) for v in rights.values()) or not any(rights.values()):
                raise FeedbackError('WORK_GRANT_RIGHTS_INVALID', 'declare publishInterview and/or resumeOnAnswers booleans', 400)
            node, stage, purpose, check_kind = args.get('nodeId'), args.get('stage','produce'), args.get('purpose','produce'), args.get('checkKind')
            scope = self.scope(run,node,stage,purpose,check_kind)
            doc = {'grantId':'g-'+uuid.uuid4().hex,'runId':run['runId'],'ownerId':session['id'],
                   'nodeId':node,'stage':stage,'purpose':purpose,'checkKind':check_kind,
                   'decisionKeys':keys,**rights,'scopeHash':scope,'revision':1,'status':'active','createdAt':time.time()}
        elif args.get('action') == 'revoke':
            row = self.db.execute('SELECT doc FROM work_grants WHERE id=? AND owner_id=? AND run_id=?', (args.get('grantId'),session['id'],run['runId'])).fetchone()
            if not row:
                raise FeedbackError('WORK_GRANT_UNKNOWN','grant not owned by this run',404)
            doc = json.loads(row['doc'])
            if isinstance(args.get('revision'),bool) or args.get('revision') != doc['revision']:
                raise FeedbackError('WORK_GRANT_REVISION_CONFLICT','use current grant revision')
            doc.update(status='revoked',revision=doc['revision']+1)
        else:
            raise FeedbackError('WORK_GRANT_ACTION','use grant or revoke',400)
        encoded = json.dumps(doc,ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO work_grants VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc', (doc['grantId'],run['runId'],session['id'],encoded))
            self.db.execute('INSERT INTO work_grant_invocations VALUES(?,?,?,?)',(session['id'],invocation,digest,encoded))
        self.graph.rt.store.emit(session['id'],'work_notice',{'type':'notification','event':'grant_'+doc['status'],'runId':run['runId'],'grant':doc})
        if doc['status'] == 'revoked':
            self.graph.continuations.revoke(doc['grantId'])
        return doc
