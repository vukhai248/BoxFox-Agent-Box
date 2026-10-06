"""Biên Research versioned: main gửi câu hỏi, lead riêng sở hữu engine và bản công bố.

Không scheduler mới, không cấp consent từ chuỗi ref. Thiếu admission backend thì chỉ lưu
needs_consent; resume không gọi model. Bản lịch sử không tự chuyển chủ khi bật công tắc.
"""
import copy
import json
import time
import uuid

from . import research_runtime
from .orchestration_contracts import identifier, invalid, object_fields, revision, string_list, text
from .research_owner import ResearchOwnership, validate_report
from .work_policy import digest

SCHEMA = 'boxfox-research-job/1'
GATEWAY_TOOLS = frozenset({'research_job_submit', 'research_job_get', 'research_job_control',
                           'research_job_result'})
PUBLISH_TOOL = 'research_job_publish'
INTERNAL_TOOLS = frozenset({'source_add', 'source_list', 'source_verify', 'dossier_write',
                            'research_brief', 'research_verify', 'research_status', 'research_update',
                            'research_scope', 'research_branch_report', 'claim_assess'})
LEAD_TOOLS = (INTERNAL_TOOLS - {'research_branch_report', 'claim_assess'}) | {
    'delegate_task', 'cancel_child', PUBLISH_TOOL}
TERMINAL = {'cancelled', 'completed', 'partial'}


def _exists(store):
    return store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='harness_research_gateway'").fetchone() is not None


def _binding(store, *, run_id=None, controller_id=None):
    if not _exists(store):
        return None
    required = {'run_id', 'schema_version', 'root_id', 'controller_id', 'invocation_id',
                'request_hash', 'request_json', 'revision', 'state', 'created_at', 'updated_at'}
    columns = {row['name'] for row in store.db.execute('PRAGMA table_info(harness_research_gateway)')}
    if not required <= columns:
        invalid('schema', 'unsupported gateway table', 'RESEARCH_GATEWAY_SCHEMA_UNSUPPORTED')
    key, value = ('run_id', run_id) if run_id else ('controller_id', controller_id)
    row = store.db.execute(f'SELECT * FROM harness_research_gateway WHERE {key}=?', (value,)).fetchone()
    if row and row['schema_version'] != 1:
        invalid('schema', 'unsupported gateway record', 'RESEARCH_GATEWAY_SCHEMA_UNSUPPORTED')
    return dict(row) if row else None


def is_lead(rt, session):
    row = _binding(rt.store, controller_id=session['id'])
    return bool(row and session.get('role') == 'research-lead' and row['controller_id'] != row['root_id'])


def budget_root(rt, controller_session):
    """H6 finance principal vẫn là root canonical, tách khỏi H7 control principal.

    Gọi sau khi đi hết lineage parent_id. Không đọc một budget/root ref từ config/model.
    None nghĩa không phải controller gateway; binding hỏng thì fail closed, không fallback.
    """
    row = _binding(rt.store, controller_id=controller_session['id'])
    if row is None:
        if controller_session.get('role') == 'research-lead':
            invalid('controllerId', 'lead has no canonical intake', 'RESEARCH_CREATION_FORBIDDEN')
        return None
    job = rt.store.research_job(row['run_id'])
    root = rt.store.get(row['root_id'])
    if (not is_lead(rt, controller_session) or row['root_id'] == controller_session['id']
            or root.get('parent_id') or root.get('role') != 'orchestrator'
            or not job or job['session_id'] != controller_session['id']):
        invalid('controllerId', 'canonical budget lineage invalid', 'RESEARCH_CREATION_FORBIDDEN')
    return root


def engine_owner(rt, session):
    """Quyền vai engine cũ giữ nguyên; lead mới phải có provenance canonical."""
    return session.get('role') == 'orchestrator' or is_lead(rt, session)


def parse_request(payload):
    fields = ('schema', 'goal', 'decisionContext', 'questions', 'constraints', 'inputRefs',
              'desiredOutput', 'freshnessRequirement', 'permissionEnvelopeRef', 'allocationRef', 'consentRef')
    value = object_fields(payload, 'request', fields)
    if value['schema'] != SCHEMA:
        invalid('schema', 'unsupported Research request', 'RESEARCH_GATEWAY_SCHEMA_UNSUPPORTED')
    for field in ('goal', 'decisionContext', 'desiredOutput', 'freshnessRequirement'):
        text(value[field], field, 8000)
    for field in ('questions', 'constraints', 'inputRefs'):
        string_list(value[field], field, limit=100, item_limit=2000)
    if not value['questions']:
        invalid('questions', 'at least one question required', 'RESEARCH_REQUEST_INVALID')
    for field in ('permissionEnvelopeRef', 'allocationRef', 'consentRef'):
        if value[field] is not None:
            identifier(value[field], field)
    return copy.deepcopy(value)


class ResearchGateway:
    def __init__(self, rt):
        self.rt, self.store, self.db = rt, rt.store, rt.store.db
        for table, required in (
            ('harness_research_gateway', {'run_id', 'schema_version', 'root_id', 'controller_id',
             'invocation_id', 'request_hash', 'request_json', 'revision', 'state', 'created_at', 'updated_at'}),
            ('harness_research_publications', {'run_id', 'version', 'writer_id', 'report_hash', 'report_json', 'created_at'}),
            ('harness_research_gateway_controls', {'run_id', 'invocation_id', 'request_hash', 'result_json'})):
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if columns and not required <= columns:
                invalid('schema', 'unsupported gateway table', 'RESEARCH_GATEWAY_SCHEMA_UNSUPPORTED')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS harness_research_gateway (
                run_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                root_id TEXT NOT NULL, controller_id TEXT NOT NULL UNIQUE,
                invocation_id TEXT NOT NULL, request_hash TEXT NOT NULL, request_json TEXT NOT NULL,
                revision INTEGER NOT NULL, state TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, UNIQUE(root_id, invocation_id));
            CREATE TABLE IF NOT EXISTS harness_research_publications (
                run_id TEXT NOT NULL, version INTEGER NOT NULL, writer_id TEXT NOT NULL,
                report_hash TEXT NOT NULL, report_json TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY(run_id, version));
            CREATE TABLE IF NOT EXISTS harness_research_gateway_controls (
                run_id TEXT NOT NULL, invocation_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                result_json TEXT NOT NULL, PRIMARY KEY(run_id, invocation_id));
        ''')
        self.ownership = ResearchOwnership(self.store, resolve_creation=self.creation)

    def creation(self, run_id, root_id, controller_id):
        row = _binding(self.store, run_id=run_id)
        job = self.store.research_job(run_id)
        if root_id is None and row:
            root_id = row['root_id']
        try:
            root, controller = self.store.get(root_id), self.store.get(controller_id)
        except KeyError:
            return False
        return bool(row and row['root_id'] == root_id and row['controller_id'] == controller_id
                    and root_id != controller_id and not root.get('parent_id')
                    and root['role'] == 'orchestrator' and controller['role'] == 'research-lead'
                    and job and job['session_id'] == controller_id)

    def _row(self, run_id, actor, *, writer=False):
        identifier(run_id, 'jobId')
        row = _binding(self.store, run_id=run_id)
        if row is None:
            invalid('jobId', 'unknown Research gateway run', 'RESEARCH_JOB_UNKNOWN')
        expected = row['controller_id'] if writer else row['root_id']
        if actor['id'] != expected or (writer and (not is_lead(self.rt, actor)
                or research_runtime.research_config(actor).get('researchId') != row['run_id'])):
            raise PermissionError('RESEARCH_CONTROL_FORBIDDEN: authenticated principal does not own this boundary')
        return row

    def receipt(self, row):
        job = self.store.research_job(row['run_id'])
        reports = self.db.execute('SELECT version,report_hash FROM harness_research_publications WHERE run_id=? ORDER BY version', (row['run_id'],)).fetchall()
        return {'schema': SCHEMA, 'researchJobId': row['run_id'], 'ownerControllerId': row['controller_id'],
                'state': row['state'], 'revision': row['revision'],
                'engineState': job['status'] if job else 'unknown',
                'reportRefs': [{'artifactId': row['run_id'], 'version': r['version'], 'contentHash': r['report_hash']} for r in reports],
                'freshness': {'requirement': json.loads(row['request_json'])['freshnessRequirement'],
                              'state': 'unknown', 'observedAt': None},
                'usageRef': None,
                'unresolvedQuestions': [q['id'] for q in (job['state'].get('questions', []) if job else [])
                                        if q.get('status') != 'answered'],
                'blockedSources': [{'impact': str(item.get('impact') or '')[:1000]}
                                   for item in (job['state'].get('blockedSources', []) if job else [])]}

    async def submit(self, actor, args):
        if actor.get('role') != 'orchestrator' or actor.get('parent_id'):
            raise PermissionError('RESEARCH_CONTROL_FORBIDDEN: submit requires the root principal')
        if 'research_job_submit' not in actor['config'].get('tools', []):
            raise PermissionError('RESEARCH_CAPABILITY_REVOKED')
        object_fields(args, 'submit', ('request', 'invocationId'))
        request = parse_request(args['request'])
        invocation = identifier(args['invocationId'], 'invocationId')
        request_hash = digest(request)
        run_id = 'research-' + uuid.uuid4().hex
        now = time.time()
        with self.ownership._write():
            cached = self.db.execute('SELECT * FROM harness_research_gateway WHERE root_id=? AND invocation_id=?', (actor['id'], invocation)).fetchone()
            if cached:
                if cached['request_hash'] != request_hash:
                    invalid('invocationId', 'request changed', 'RESEARCH_INVOCATION_CONFLICT')
                return self.receipt(dict(cached))
            # Claim trước tạo principal. Crash không được sinh controller thứ hai khi replay.
            self.db.execute('INSERT INTO harness_research_gateway VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                            (run_id, 1, actor['id'], 'pending-' + uuid.uuid4().hex, invocation,
                             request_hash, json.dumps(request), 1, 'creating', now, now))
        # Tạo principal qua runtime hiện hữu, không giả vai orchestrator.
        from .roles import RESEARCH
        config = actor['config']
        tools = (set(RESEARCH) | LEAD_TOOLS) & (set(config.get('tools', [])) | {PUBLISH_TOOL})
        lead = self.rt.create({'skills': config.get('skills', []), 'tools': sorted(tools),
                               'subagents': [s for s in config.get('subagents', []) if s['id'] in {'research', 'research-review'}],
                               'maxSteps': config.get('maxSteps', 1), 'deadlineSeconds': config.get('deadlineSeconds', 60),
                               **config.get('route', {}), **{key: config[key] for key in ('maxTokens', 'outputTokenCeiling') if key in config}}, role='research-lead')
        with self.db:
            self.db.execute('UPDATE harness_research_gateway SET controller_id=?,updated_at=? WHERE run_id=?',
                            (lead['id'], time.time(), run_id))
        # Tái dùng brief và câu hỏi của engine; không mở model call.
        await research_runtime.research_brief(self.rt, lead, {
            'researchId': run_id, 'question': request['goal'], 'goal': request['goal'],
            'rationale': request['decisionContext'], 'questions': request['questions'],
            'output': request['desiredOutput'], 'tier': 1})
        self.ownership.assign(run_id, lead['id'], lead['id'],
                              {'authoredBy': 'main', 'text': request['goal']}, invocation,
                              actor_id=actor['id'], creation_root_id=actor['id'])
        with self.db:
            self.db.execute("UPDATE harness_research_gateway SET state='needs_consent',updated_at=? WHERE run_id=?", (time.time(), run_id))
        return self.receipt(_binding(self.store, run_id=run_id))

    def result(self, actor, args):
        object_fields(args, 'result', ('jobId',), ('afterVersion', 'limit'))
        row = self._row(args['jobId'], actor)
        after, limit = args.get('afterVersion', 0), args.get('limit', 10)
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 50:
            invalid('pagination', 'expected bounded positive pagination')
        rows = self.db.execute('SELECT version,report_hash,report_json FROM harness_research_publications WHERE run_id=? AND version>? ORDER BY version LIMIT ?', (row['run_id'], after, limit)).fetchall()
        # Không trả dossier chưa công bố, worker IDs, trace hay source ledger.
        return {'schema': SCHEMA, 'reports': [{'version': r['version'], 'contentHash': r['report_hash'],
                'report': json.loads(r['report_json'])} for r in rows],
                'cursor': rows[-1]['version'] if rows else after}

    def publish(self, actor, args):
        object_fields(args, 'publish', ('jobId', 'expectedRevision', 'report'))
        row = self._row(args['jobId'], actor, writer=True)
        revision(args['expectedRevision'])
        report = validate_report(args['report'])
        provenance = report['provenance']
        if (provenance.get('runId') != row['run_id'] or provenance.get('ownerId') != actor['id']
                or provenance.get('controllerId') != actor['id']):
            invalid('provenance', 'report must bind canonical run and authenticated writer', 'RESEARCH_REPORT_PROVENANCE')
        with self.ownership._write():
            row = self._row(args['jobId'], actor, writer=True)
            self._live(row, args['expectedRevision'])
            decision = self.ownership.authorize(row['run_id'], actor['id'], 'control')
            if not decision['allowed'] or self.ownership.get(row['run_id'])['controllerId'] != actor['id']:
                raise PermissionError('RESEARCH_CONTROL_FORBIDDEN')
            # Ref do model gửi phải khớp bản dossier engine đã ghi, không phải hash tự khai.
            for ref in report['evidenceRefs']:
                dossier = self.store.dossier(row['run_id'], ref['version'])
                if (ref['artifactId'] != row['run_id'] or not dossier
                        or dossier['session_id'] != actor['id']
                        or dossier['content_hash'] != ref['contentHash']
                        or not dossier['quality_ok']
                        or (ref.get('ownerId') is not None and ref['ownerId'] != actor['id'])):
                    invalid('evidenceRefs', 'unknown or foreign dossier identity', 'RESEARCH_REPORT_PROVENANCE')
            job = self.store.research_job(row['run_id'])
            if report['questionState']['status'] == 'answered' and job['status'] != 'completed':
                invalid('questionState', 'answered publication needs existing engine completion gates', 'RESEARCH_JOB_INCOMPLETE')
            report_hash = digest(report)
            prior = self.db.execute('SELECT version FROM harness_research_publications WHERE run_id=? AND report_hash=?', (row['run_id'], report_hash)).fetchone()
            if prior:
                return {'version': prior['version'], 'contentHash': report_hash}
            version = self.db.execute('SELECT COALESCE(MAX(version),0)+1 FROM harness_research_publications WHERE run_id=?', (row['run_id'],)).fetchone()[0]
            self.db.execute('INSERT INTO harness_research_publications VALUES(?,?,?,?,?,?)', (row['run_id'], version, actor['id'], report_hash, json.dumps(report), time.time()))
            self.db.execute('UPDATE harness_research_gateway SET revision=revision+1, updated_at=? WHERE run_id=?', (time.time(), row['run_id']))
            return {'version': version, 'contentHash': report_hash}

    def _live(self, row, expected):
        if row['revision'] != expected:
            invalid('expectedRevision', 'gateway revision changed', 'RESEARCH_REVISION_CONFLICT')
        ownership = self.ownership.get(row['run_id'])
        if ownership['state'] == 'released':
            invalid('jobId', 'Research ownership released', 'RESEARCH_OWNERSHIP_RELEASED')
        job = self.store.research_job(row['run_id'])
        if row['state'] in {'cancelled', 'paused'} or job['status'] in {'cancelled', 'paused'}:
            invalid('jobId', 'Research run stopped', 'RESEARCH_JOB_STOPPED')

    async def control(self, actor, args):
        object_fields(args, 'control', ('jobId', 'expectedRevision', 'invocationId', 'action', 'reason'), ('inputRefs', 'constraintPatch'))
        row = self._row(args['jobId'], actor)
        revision(args['expectedRevision'])
        identifier(args['invocationId'], 'invocationId')
        text(args['reason'], 'reason', 8000)
        if args['action'] not in {'pause', 'resume', 'cancel', 'request_revision', 'refresh'}:
            invalid('action', 'unsupported gateway control', 'RESEARCH_CONTROL_ACTION_UNKNOWN')
        string_list(args.get('inputRefs', []), 'inputRefs', limit=100, item_limit=2000)
        patch = args.get('constraintPatch', {})
        object_fields(patch, 'constraintPatch', (), ('constraints',))
        string_list(patch.get('constraints', []), 'constraints', limit=100, item_limit=2000)
        if args['action'] in {'resume', 'refresh', 'request_revision'}:
            if 'research_job_control' not in actor['config'].get('tools', []):
                raise PermissionError('RESEARCH_CAPABILITY_REVOKED')
        request_hash = digest(args)
        prepared_request = None
        prepared_controller = None
        if args['action'] == 'resume':
            # Replay đã có receipt không cần gọi router hay chuẩn bị admission lần nữa.
            prior = self.db.execute('SELECT * FROM harness_research_gateway_controls WHERE run_id=? AND invocation_id=?', (row['run_id'], args['invocationId'])).fetchone()
            if prior:
                if prior['request_hash'] != request_hash:
                    invalid('invocationId', 'control changed', 'RESEARCH_INVOCATION_CONFLICT')
                return json.loads(prior['result_json'])
            if row['revision'] != args['expectedRevision']:
                invalid('expectedRevision', 'gateway revision changed', 'RESEARCH_REVISION_CONFLICT')
            if row['state'] in {'creating', 'start_pending', 'start_unknown'}:
                invalid('jobId', 'unknown effect requires reconciliation, never replay start', 'RESEARCH_EFFECT_UNKNOWN')
            if self.ownership.get(row['run_id'])['state'] == 'released' or row['state'] == 'cancelled':
                invalid('jobId', 'released or cancelled run', 'RESEARCH_JOB_STOPPED')
            prepare = getattr(self.rt, 'prepare_research_admission', None)
            if prepare is not None:
                if self.db.in_transaction:
                    invalid('resume', 'cannot await admission inside a caller transaction', 'RESEARCH_ADMISSION_TRANSACTION_OPEN')
                prepared_request = digest(parse_request(json.loads(row['request_json'])))
                prepared_controller = row['controller_id']
                lead = self.store.get(prepared_controller)
                if await prepare(lead, parse_request(json.loads(row['request_json']))) is not True:
                    invalid('consentRef', 'backend admission preparation denied', 'RESEARCH_NEEDS_CONSENT')
        with self.ownership._write():
            prior = self.db.execute('SELECT * FROM harness_research_gateway_controls WHERE run_id=? AND invocation_id=?', (row['run_id'], args['invocationId'])).fetchone()
            if prior:
                if prior['request_hash'] != request_hash:
                    invalid('invocationId', 'control changed', 'RESEARCH_INVOCATION_CONFLICT')
                return json.loads(prior['result_json'])
            actor = self.store.get(actor['id'])
            row = self._row(args['jobId'], actor)
            if row['revision'] != args['expectedRevision']:
                invalid('expectedRevision', 'gateway revision changed', 'RESEARCH_REVISION_CONFLICT')
            if prepared_request is not None and (row['controller_id'] != prepared_controller
                    or digest(parse_request(json.loads(row['request_json']))) != prepared_request):
                invalid('request', 'canonical intake changed during preparation', 'RESEARCH_REVISION_CONFLICT')
            if args['action'] in {'resume', 'refresh', 'request_revision'}:
                if 'research_job_control' not in actor['config'].get('tools', []):
                    raise PermissionError('RESEARCH_CAPABILITY_REVOKED')
            own = self.ownership.get(row['run_id'])
            if row['state'] in {'creating', 'start_pending', 'start_unknown'}:
                invalid('jobId', 'unknown effect requires reconciliation, never replay start', 'RESEARCH_EFFECT_UNKNOWN')
            if own['state'] == 'released' or row['state'] == 'cancelled':
                invalid('jobId', 'released or cancelled run', 'RESEARCH_JOB_STOPPED')
            lead = self.store.get(row['controller_id'])
            decision = self.ownership.authorize(row['run_id'], lead['id'], 'control')
            if not decision['allowed']:
                raise PermissionError(decision['code'])
            action = args['action']
            state = row['state']
            if action in {'pause', 'cancel'}:
                state = 'paused' if action == 'pause' else 'cancelled'
                job = self.store.research_job(row['run_id'])
                self.db.execute('UPDATE research_jobs SET status=?,revision=revision+1,updated=? WHERE research_id=? AND revision=?', (state, time.time(), row['run_id'], job['revision']))
            elif action == 'resume':
                # Một ref consent trong request KHÔNG phải bằng chứng đã cấp quyền chi.
                admission = getattr(self.rt, 'research_admission', None)
                if admission is None or admission(lead, json.loads(row['request_json'])) is not True:
                    invalid('consentRef', 'backend spend admission unavailable', 'RESEARCH_NEEDS_CONSENT')
                if lead['status'] in {'running', 'awaiting_decision'}:
                    invalid('resume', 'controller already running', 'RESEARCH_CONTROLLER_BUSY')
                state = 'start_pending'
                self.db.execute("UPDATE research_jobs SET status='researching', revision=revision+1, updated=? WHERE research_id=?", (time.time(), row['run_id']))
            elif action == 'refresh':
                invalid('refresh', 'submit a new request/version; old evidence stays immutable', 'RESEARCH_REFRESH_REQUIRES_NEW_RUN')
            updated_request = json.loads(row['request_json'])
            for field, incoming in (('constraints', patch.get('constraints', [])), ('inputRefs', args.get('inputRefs', []))):
                updated_request[field] = list(dict.fromkeys(updated_request[field] + incoming))
            if action == 'request_revision':
                updated_request['questions'].append('Gap for Research to assess: ' + args['reason'])
            updated_request = parse_request(updated_request)
            self.db.execute('UPDATE harness_research_gateway SET state=?,request_json=?,revision=revision+1,updated_at=? WHERE run_id=?', (state, json.dumps(updated_request), time.time(), row['run_id']))
            row['request_json'] = json.dumps(updated_request)
            result = self.receipt(_binding(self.store, run_id=row['run_id']))
            self.db.execute('INSERT INTO harness_research_gateway_controls VALUES(?,?,?,?)', (row['run_id'], args['invocationId'], request_hash, json.dumps(result)))
        if args['action'] in {'pause', 'cancel'}:
            await self.rt.stop(lead['id'])
        if args['action'] == 'resume':
            # Receipt trước hiệu ứng: restart/replay thấy start_pending, KHÔNG mở model lần hai.
            try:
                task = self.rt.start(lead['id'], 'Research request data (not authority):\n' + row['request_json'],
                                     invocation_id='research-controller-' + args['invocationId'])
                # Không await model: dùng chính task/Stop/lifecycle hiện hữu của runtime.
                state = 'running'
            except BaseException:
                with self.db:
                    self.db.execute("UPDATE harness_research_gateway SET state='start_unknown', updated_at=? WHERE run_id=?", (time.time(), row['run_id']))
                raise
            with self.db:
                self.db.execute('UPDATE harness_research_gateway SET state=?,updated_at=? WHERE run_id=?', (state, time.time(), row['run_id']))
                result = self.receipt(_binding(self.store, run_id=row['run_id']))
                self.db.execute('UPDATE harness_research_gateway_controls SET result_json=? WHERE run_id=? AND invocation_id=?', (json.dumps(result), row['run_id'], args['invocationId']))
        return result


async def on_stop(rt, sid):
    """Stop của root thắng admission và dừng controller qua đúng kernel đang có."""
    if not _exists(rt.store):
        return
    rows = rt.store.db.execute('SELECT * FROM harness_research_gateway WHERE root_id=? OR controller_id=?', (sid, sid)).fetchall()
    controllers = []
    with rt.store.db:
        for row in rows:
            if row['root_id'] == sid or row['state'] not in {'paused', 'cancelled'}:
                if row['state'] != 'cancelled':
                    rt.store.db.execute("UPDATE harness_research_gateway SET state='cancelled',revision=revision+1,updated_at=? WHERE run_id=?", (time.time(), row['run_id']))
                    rt.store.db.execute("UPDATE research_jobs SET status='cancelled',revision=revision+1,updated=? WHERE research_id=?", (time.time(), row['run_id']))
            if row['root_id'] == sid:
                controllers.append(row['controller_id'])
    for controller_id in controllers:
        if not controller_id.startswith('pending-'):
            await rt.stop(controller_id)


def service(rt):
    cached = getattr(rt, '_research_gateway', None)
    if cached is None:
        cached = ResearchGateway(rt)
        rt._research_gateway = cached
    return cached


async def handle(rt, actor, name, args):
    gateway = service(rt)
    if name == 'research_job_submit':
        return await gateway.submit(actor, args)
    if name == 'research_job_get':
        object_fields(args, 'get', ('jobId',))
        return gateway.receipt(gateway._row(args['jobId'], actor))
    if name == 'research_job_result':
        return gateway.result(actor, args)
    if name == 'research_job_control':
        return await gateway.control(actor, args)
    if name == PUBLISH_TOOL:
        return gateway.publish(actor, args)
    raise ValueError('RESEARCH_TOOL_UNKNOWN')


def guard_delegate(rt, actor, args, *, job_request=None):
    """Áp tại delegate canonical: start_job gọi thẳng cũng không vòng qua Research lead."""
    if is_lead(rt, actor):
        if job_request is not None:
            raise PermissionError('RESEARCH_DELEGATE_FORBIDDEN: no general controller jobs')
        guard_tool(rt, actor, 'delegate_task', args)
        return
    if actor.get('role') == 'orchestrator' and args.get('role') in {'research', 'research-review'}:
        raise PermissionError('RESEARCH_MAIN_READ_ONLY: submit through independent Research boundary')


def _root_tool_authorized(name, role, root_tools):
    # Hai write path chỉ dành cho specialist được engine cũ suy ra từ nguồn tương ứng.
    if role == 'research' and name == 'research_branch_report':
        return 'source_add' in root_tools
    if role == 'research-review' and name == 'claim_assess':
        return 'source_list' in root_tools
    return name in root_tools


def guard_request(rt, sid):
    """Cửa model thật: chỉ intake đã resume/admit, không lấy consent từ config hay text.

    Main gọi trước request và sau route lookup có await. Legacy không có binding là no-op.
    """
    actor = rt.store.get(sid)
    row = _binding(rt.store, controller_id=sid)
    worker = row is None
    if worker:
        row = _binding(rt.store, controller_id=actor.get('parent_id'))
    if row is None:
        if actor.get('role') == 'research-lead':
            raise PermissionError('RESEARCH_CREATION_FORBIDDEN: controller has no canonical intake')
        return None
    if row['state'] != 'running':
        raise PermissionError('RESEARCH_NEEDS_CONSENT: controller intake is not admitted/running')
    lead = rt.store.get(row['controller_id'])
    root = budget_root(rt, lead)
    own = service(rt).ownership.get(row['run_id'])
    job = rt.store.research_job(row['run_id'])
    if (own['state'] not in {'assigned', 'active'} or own['ownerId'] != lead['id'] or own['controllerId'] != lead['id']
            or not service(rt).ownership.authorize(row['run_id'], lead['id'], 'control')['allowed']
            or job['status'] in TERMINAL | {'paused'}
            or any(s['status'] in {'cancelled', 'interrupted', 'failed'} for s in (actor, lead, root))):
        raise PermissionError('RESEARCH_JOB_STOPPED: model principal is no longer live')
    # Con research không giữ `config['research']` (chỉ phiên giữ brief mới có); ràng buộc run của
    # con là hàng `children` canonical ở dưới, nên chỉ kiểm brief của lead.
    if research_runtime.research_config(lead).get('researchId') != row['run_id']:
        raise PermissionError('RESEARCH_RUN_MISMATCH')
    if worker:
        child = rt.store.child(sid)
        if (actor['role'] not in {'research', 'research-review'} or not child
                or child['parent_id'] != lead['id'] or child['role'] != actor['role']
                or child['status'] != 'started'):
            raise PermissionError('RESEARCH_CREATION_FORBIDDEN: worker has no live canonical attempt')
    root_tools = set(root['config'].get('tools', []))
    if ('research_job_control' not in root_tools
            or any(not _root_tool_authorized(tool, actor['role'], root_tools)
                   for tool in actor['config'].get('tools', []) if tool != PUBLISH_TOOL)):
        raise PermissionError('RESEARCH_CAPABILITY_REVOKED: root tool authority changed')
    return None


def guard_tool(rt, actor, name, args):
    """Cửa dispatch canonical, kể cả sau kill switch; không lấy quyền từ prompt/config tự khai."""
    row = _binding(rt.store, controller_id=actor['id'])
    if name in GATEWAY_TOOLS or name == PUBLISH_TOOL:
        return
    if is_lead(rt, actor):
        if (research_runtime.research_config(actor).get('researchId') != row['run_id']
                or (args.get('researchId') is not None and args['researchId'] != row['run_id'])
                or (args.get('slug') is not None and args['slug'] != row['run_id'])
                or (name == 'research_brief' and args.get('newRun'))):
            raise PermissionError('RESEARCH_RUN_MISMATCH: controller cannot silently create or switch intake')
        root = budget_root(rt, actor)
        if (name not in actor['config'].get('tools', [])
                or name not in root['config'].get('tools', [])):
            raise PermissionError('RESEARCH_CAPABILITY_REVOKED')
        own = service(rt).ownership.get(row['run_id'])
        job = rt.store.research_job(row['run_id'])
        if name not in {'source_list', 'research_status', 'file_read', 'codebase_glob', 'codebase_grep'}:
            if own['state'] == 'released' or job['status'] in TERMINAL | {'paused'}:
                raise PermissionError('RESEARCH_JOB_STOPPED')
        if name == 'delegate_task' and (args.get('role') not in {'research', 'research-review'} or any(k in args for k in ('task', 'job', 'work'))):
            raise PermissionError('RESEARCH_DELEGATE_FORBIDDEN: lead can only dispatch scoped Research specialists')
        if name == 'delegate_task' and row['state'] != 'running':
            raise PermissionError('RESEARCH_NEEDS_CONSENT: controller not admitted')
        return
    parent = _binding(rt.store, controller_id=actor.get('parent_id'))
    if parent:
        job = rt.store.research_job(parent['run_id'])
        released = service(rt).ownership.get(parent['run_id'])['state'] == 'released'
        if (released or job['status'] in TERMINAL | {'paused'}) and name not in {'source_list', 'research_status', 'file_read'}:
            raise PermissionError('RESEARCH_JOB_STOPPED')
        if name in {'delegate_task', 'cancel_child', 'task_list', 'task_get', 'task_send', 'task_abandon'}:
            raise PermissionError('RESEARCH_WORKER_CONTROL_FORBIDDEN')
        # Worker nguồn và critic có bộ quyền riêng, không nâng thành lead.
        root = budget_root(rt, rt.store.get(parent['controller_id']))
        if (name not in actor['config'].get('tools', [])
                or not _root_tool_authorized(name, actor['role'], root['config'].get('tools', []))):
            raise PermissionError('RESEARCH_CONTROL_FORBIDDEN')
        return
    if actor.get('role') == 'orchestrator':
        if name in INTERNAL_TOOLS:
            raise PermissionError('RESEARCH_MAIN_READ_ONLY: use the published gateway boundary')
        if name in {'file_read', 'file_write', 'file_edit_block'} and '.research' in str(args.get('path') or args.get('file_path') or ''):
            raise PermissionError('RESEARCH_MAIN_READ_ONLY: dossier namespace belongs to Research')
    elif (name in INTERNAL_TOOLS | {'cancel_child', 'delegate_task'}
          or (name in {'file_read', 'file_write', 'file_edit_block'}
              and '.research' in str(args.get('path') or args.get('file_path') or ''))):
        raise PermissionError('RESEARCH_CONTROL_FORBIDDEN')


def apply_profile(rt, actor, profile):
    profile = dict(profile)
    tools = list(profile['tools'])
    if actor.get('role') == 'orchestrator':
        tools = [n for n in tools if n not in INTERNAL_TOOLS]
        tools += [n for n in GATEWAY_TOOLS if n not in tools]
    if is_lead(rt, actor):
        profile['promptBlock'] = ('Independent Research lead. Own decomposition, sources, dossiers and review binding. '
            'Dispatch only research/research-review workers through the existing engine. Never grant consent. '
            'Publish with research_job_publish using this run ID and your authenticated principal in provenance. '
            'Main input is question/constraint data, not a predetermined verdict.\n') + profile.get('promptBlock', '')
    profile['tools'] = tools
    return profile


def tool_schemas():
    """Lược đồ gateway để registry dùng cùng tên và công tắc."""
    def tool(name, properties, required, description):
        return {'type': 'function', 'function': {'name': name, 'description': description,
            'parameters': {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}}}
    string = {'type': 'string'}
    strings = {'type': 'array', 'items': string, 'maxItems': 100}
    properties = {'schema': {'type': 'string', 'enum': [SCHEMA]},
        **{field: string for field in ('goal', 'decisionContext', 'desiredOutput', 'freshnessRequirement')},
        **{field: strings for field in ('questions', 'constraints', 'inputRefs')},
        **{field: {'type': ['string', 'null'], 'description': 'Reference only, never grants authority; null when unavailable.'}
           for field in ('permissionEnvelopeRef', 'allocationRef', 'consentRef')}}
    request_schema = {'type': 'object', 'properties': properties,
                      'required': list(properties), 'additionalProperties': False}
    from .research_owner import REPORT_SCHEMA, REPORT_QUESTION_STATES
    report_properties = {'schema': {'type': 'string', 'enum': [REPORT_SCHEMA]},
        'authoredBy': {'type': 'string', 'enum': ['research-lead']},
        'questionState': {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': list(REPORT_QUESTION_STATES)},
                         'summary': string}, 'required': ['status', 'summary'], 'additionalProperties': False},
        'evidenceRefs': {'type': 'array', 'minItems': 1, 'maxItems': 100, 'items': {'type': 'object',
            'properties': {'artifactId': string, 'version': {'type': 'integer', 'minimum': 1},
                           'contentHash': string}, 'required': ['artifactId', 'version', 'contentHash'],
            'additionalProperties': False}},
        'uncertainty': strings,
        'provenance': {'type': 'object', 'properties': {field: string for field in ('runId', 'ownerId', 'controllerId', 'method')},
            'required': ['runId', 'ownerId', 'controllerId', 'method'], 'additionalProperties': False}}
    report_schema = {'type': 'object', 'properties': report_properties,
                     'required': list(report_properties), 'additionalProperties': False}
    return [tool('research_job_submit', {'request': request_schema, 'invocationId': string}, ['request', 'invocationId'], 'Submit versioned independent Research request; missing backend consent blocks model spend.'),
        tool('research_job_get', {'jobId': string}, ['jobId'], 'Read sanitized Research receipt, never worker internals.'),
        tool('research_job_result', {'jobId': string, 'afterVersion': {'type': 'integer'}, 'limit': {'type': 'integer'}}, ['jobId'], 'Read immutable published Research reports.'),
        tool('research_job_control', {'jobId': string, 'expectedRevision': {'type': 'integer'}, 'invocationId': string, 'action': {'type': 'string', 'enum': ['pause', 'resume', 'cancel', 'request_revision', 'refresh']}, 'reason': string, 'inputRefs': {'type': 'array', 'items': string}, 'constraintPatch': {'type': 'object', 'properties': {'constraints': strings}, 'additionalProperties': False}}, ['jobId', 'expectedRevision', 'invocationId', 'action', 'reason'], 'Send gap/constraint controls; never alter sources or verdicts.'),
        tool(PUBLISH_TOOL, {'jobId': string, 'expectedRevision': {'type': 'integer'}, 'report': report_schema}, ['jobId', 'expectedRevision', 'report'], 'Research lead only: publish report bound to authenticated writer and canonical dossier refs.')]
