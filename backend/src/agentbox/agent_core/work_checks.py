"""Main-dispatched verification, fail-closed contracts and snapshot bindings."""
import asyncio
import base64
import json
import re
import time
import uuid

from . import work_policy, work_prompts

SNAPSHOT_SCRIPT = '''import hashlib,json,os,re,subprocess
p=subprocess.run(['git','ls-files','-co','--exclude-standard','-z'],capture_output=True,check=True)
paths=sorted(set(x.decode('utf-8') for x in p.stdout.split(b'\\0') if x))
ignored=subprocess.run(['git','ls-files','-o','-i','--exclude-standard','-z'],capture_output=True,check=True)
source_ext=('.py','.ts','.tsx','.js','.jsx','.mjs','.json','.toml','.yaml','.yml','.sql','.sh','.ps1','.html','.css','.env')
paths=sorted(set(paths+[x.decode('utf-8') for x in ignored.stdout.split(b'\\0') if x and x.decode('utf-8').endswith(source_ext)]))
paths=[path for path in paths if not any(x in ('.plans','.tmp','.pytest_cache','__pycache__','test-results','coverage','node_modules','.venv','venv') for x in path.split('/'))]
if len(paths)>30000: raise ValueError('snapshot file limit')
h=hashlib.sha256(); total=0
for path in paths:
 if any(x in ('.plans','.tmp','.pytest_cache','__pycache__','test-results','coverage') for x in path.split('/')): continue
 if not os.path.lexists(path): data=b'<deleted>'
 elif os.path.islink(path): data=os.readlink(path).encode('utf-8')
 elif os.path.isfile(path):
  total+=os.path.getsize(path)
  if total>268435456: raise ValueError('snapshot byte limit')
  with open(path,'rb') as f: data=f.read()
 else: continue
 h.update(path.encode('utf-8')+b'\\0'+hashlib.sha256(data).digest())
head=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,check=True).stdout.decode().strip()
diff=subprocess.run(['git','diff','--name-only','HEAD','-z'],capture_output=True,check=True).stdout
changed=[x.decode('utf-8') for x in diff.split(b'\\0') if x]
tracked=subprocess.run(['git','ls-files','-z'],capture_output=True,check=True).stdout
tracked={x.decode('utf-8') for x in tracked.split(b'\\0') if x}
changed+=sorted(set(paths)-tracked)
critical=any(re.search(r'api|schema|auth|migration|contract|concurr|lock',x,re.I) for x in changed) or len(changed)>8
print(json.dumps({'schema':'work-code/1','hash':h.hexdigest(),'head':head,'criticalChanges':critical}))
'''
SNAPSHOT_COMMAND = "python3 -c \"import base64;exec(base64.b64decode('%s'))\"" % base64.b64encode(
    SNAPSHOT_SCRIPT.encode()).decode()


async def snapshot(graph, sid):
    try:
        result = await graph.rt.executor.execute('terminal_exec', {'command': SNAPSHOT_COMMAND, 'timeout': 90}, sid)
        if result.get('is_error') or result.get('exit_code', result.get('exitCode')) != 0:
            return None
        value = json.loads(result.get('content') or result.get('output') or '')
        if value.get('schema') == 'work-code/1' and re.fullmatch(r'[a-f0-9]{64}', value.get('hash', '')):
            return value
    except Exception:
        pass
    return None


def complete(result):
    return isinstance(result, dict) and result.get('status') == 'completed' and not result.get('is_error')


def observations(graph, child_id):
    if not child_id:
        return []
    rows = graph.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='tool_end' ORDER BY seq",
                            (child_id,)).fetchall()
    return [json.loads(row['payload']) for row in rows]


def good_reads(graph, child_id):
    # Reading a workspace copy of the assigned artifact is still self-evidence,
    # even when the model uses file_read rather than work_artifact_read.
    try:
        binding = graph.store.get(child_id)['config'].get('workBinding') or {}
    except KeyError:
        binding = {}
    paths = []
    for aid in binding.get('artifactIds', []):
        row = graph.db.execute('SELECT metadata FROM work_artifacts WHERE id=?', (aid,)).fetchone()
        if row:
            paths.append(json.loads(row['metadata'])['path'].replace('\\', '/').removeprefix('./'))
    def original(item):
        def assigned(path):
            path = path.replace('\\', '/').removeprefix('./')
            return any(path == p or path.endswith('/' + p) for p in paths)
        path = str(item.get('args', {}).get('path') or '').replace('\\', '/').removeprefix('./')
        if assigned(path):
            return False
        if paths and item.get('name') == 'codebase_grep':
            # The worker searches .plans too. A broad grep can return only the
            # assigned artifact even when args.path is '.' or empty. Its actual
            # path:line:content matches, not the requested directory, prove origin.
            content = item['result'].get('content') or ''
            matches = re.findall(r'^(.+?):\d+:', content, re.M) if isinstance(content, str) else []
            return any(not assigned(match) for match in matches)
        return True
    def usable(item):
        result = item['result']
        if item.get('name') not in ('web_fetch', 'read_source'):
            return True
        # Web's grade describes the retained body, including a successful reader
        # fallback. Original HTTP status can remain 0/403 after that recovery.
        if 'quality' in result:
            quality = result['quality']
            return isinstance(quality, dict) and quality.get('verdict') in ('ok', 'thin')
        # Legacy payloads without a grade remain readable, but an explicit
        # failed HTTP response must never count as evidence just because it has text.
        status = result.get('status')
        return status is None or (isinstance(status, int) and not isinstance(status, bool) and 200 <= status < 300)
    return [item for item in observations(graph, child_id)
            if item.get('name') in ('file_read', 'web_fetch', 'read_source', 'codebase_grep')
            and isinstance(item.get('result'), dict) and not item['result'].get('is_error')
            and any((value.strip() if isinstance(value, str) else bool(value))
                    for k in ('content', 'text', 'matches', 'results') for value in [item['result'].get(k)])
            and original(item) and usable(item)]


def test_proof(graph, child_id, tests):
    calls = [item for item in observations(graph, child_id) if item.get('name') == 'terminal_exec']
    # Evidence is the actual tool event, never commands/exit codes invented in prose.
    good = [item for item in calls if not item.get('result', {}).get('is_error')
            and item.get('result', {}).get('exit_code', item.get('result', {}).get('exitCode')) == 0
            and (item.get('result', {}).get('content') or item.get('result', {}).get('output'))]
    return bool(tests) and all(any(test.strip() == str(item.get('args', {}).get('command', '')).strip()
                                 for item in good) for test in tests)


def parse_report(text, required, *, require_target=False):
    """Exactly one final verdict and JSON coverage for EVERY assigned criterion."""
    raw = str(text or '').strip()
    lines = re.findall(r'^\s*VERDICT: (ok|revise)\s*$', raw, re.M)
    if len(lines) != 1 or not raw.endswith('VERDICT: ' + lines[0]):
        return 'error', [], 'Missing single final VERDICT line.'
    blocks = re.findall(r'```json\s*\n(.*?)\n```', raw, re.S)
    try:
        report = json.loads(blocks[-1])
        coverage = report['coverage']
        if not isinstance(coverage, list) or len(coverage) != len(required):
            raise ValueError('coverage count')
        by_id = {item['id']: item for item in coverage}
        if len(by_id) != len(coverage) or set(by_id) != set(required):
            raise ValueError('coverage ids')
        if any(item.get('status') not in ('pass', 'revise', 'unverified') or
               not isinstance(item.get('evidence'), str) or not item['evidence'].strip() for item in coverage):
            raise ValueError('status/evidence')
        for item in coverage:
            if (require_target and item['status'] == 'revise' and
                    re.fullmatch(r'(?:[^.]+\.)?A[1-9]\d*', item['id']) and 'target' not in item):
                raise ValueError('revised acceptance needs an explicit finding target')
            target = item.get('target', 'artifact')
            if target not in ('artifact', 'criterion'):
                raise ValueError('finding target')
            if target == 'criterion' and (item['status'] != 'revise' or
                    not re.fullmatch(r'(?:[^.]+\.)?A[1-9]\d*', item['id'])):
                raise ValueError('criterion conflict must revise an assigned A criterion')
    except (IndexError, KeyError, ValueError, TypeError):
        return 'error', [], ('Invalid JSON coverage; every assigned id needs status and evidence. '
                             'Revised A criteria must explicitly set target=artifact or target=criterion.')
    statuses = {item['status'] for item in coverage}
    status = 'revise' if 'revise' in statuses or lines[0] == 'revise' else (
        'unverified' if 'unverified' in statuses else 'pass')
    return status, coverage, raw


def input_conflicts(coverage, criteria):
    """An evidenced conflict in main's assignment, not a request to falsify the artifact."""
    return [{'id': item['id'], 'requirement': criteria[item['id']], 'evidence': item['evidence']}
            for item in coverage if item.get('target') == 'criterion' and item['status'] == 'revise']


def contract(lang, criteria):
    head = work_prompts.choose(lang,
        'Read ALL assigned snapshots with work_artifact_read, following nextOffset/unreadOffset until allAssignedArtifactsRead is true; '
        'coverageComplete is only for the current artifact, not the whole assignment. '
        'Inspect original evidence too; artifact reads alone do not verify facts. Do not edit source. '
        'For tests, execute EXACT required commands; never claim pass without tool output. ',
        'Đọc HẾT snapshot được giao bằng work_artifact_read theo nextOffset/unreadOffset đến khi allAssignedArtifactsRead=true; '
        'coverageComplete chỉ áp dụng cho artifact hiện tại, không phải toàn bộ nhiệm vụ. '
        'Kiểm cả bằng chứng gốc; đọc artifact chưa chứng minh dữ kiện đúng. Không sửa source. '
        'Với test, chạy ĐÚNG lệnh bắt buộc; không bịa pass khi thiếu output tool. ')
    skeleton = {'coverage': [{'id': key, 'status': 'unverified', 'target': 'artifact',
                             'evidence': '<reference or finding>'} for key in criteria]}
    return head + work_prompts.choose(lang,
        '\nKeep findings under 600 words. Do not rewrite the deliverable or add scope. Snapshot hashes are checked by the backend; do not spend steps recomputing them. ',
        '\nFinding dưới 600 từ. Không viết lại sản phẩm hoặc thêm phạm vi. Backend kiểm hash snapshot; không tốn bước tính lại hash. ') + work_prompts.choose(lang,
        '\nJudge the EXACT wording of each criterion. When an A criterion contains a disproved technical premise, '
        'use status=revise, target=criterion and evidence naming the conflict and correction for main. '
        'Keep a factually correct artifact intact; do not silently replace the criterion and mark it pass. '
        'Every coverage entry explicitly includes target. Other findings use target=artifact; '
        'target=criterion is not for C/G rubrics. ',
        '\nKiểm ĐÚNG nội dung từng tiêu chí. Tiêu chí A có tiền đề kỹ thuật bị nguồn bác bỏ phải ghi '
        'status=revise, target=criterion và evidence nêu mâu thuẫn/sửa tiêu chí cho main. '
        'Giữ artifact đúng dữ kiện; không âm thầm đổi nghĩa tiêu chí rồi ghi pass. '
        'Mỗi coverage entry ghi rõ target. Finding khác dùng target=artifact; '
        'target=criterion không áp dụng rubric C/G. ') + '\n' + json.dumps(criteria, ensure_ascii=False) + work_prompts.choose(lang,
        '\nReturn findings and a fenced json object {"coverage":[{"id":"A1","status":"pass|revise|unverified","target":"artifact|criterion","evidence":"specific reference or finding"}]}. '
        'Example for a disproved premise: {"id":"A1","status":"revise","target":"criterion","evidence":"Opened source refutes the premise; main must correct A1, not rewrite the correct artifact."}. '
        'Include every criterion id exactly once. END with one line VERDICT: ok or VERDICT: revise.',
        '\nTrả finding và object trong fenced json {"coverage":[{"id":"A1","status":"pass|revise|unverified","target":"artifact|criterion","evidence":"tham chiếu hoặc finding cụ thể"}]}. '
        'Ví dụ tiền đề bị bác bỏ: {"id":"A1","status":"revise","target":"criterion","evidence":"Nguồn đã mở bác tiền đề; main sửa A1, không viết lại artifact đúng."}. '
        'Mỗi id xuất hiện đúng một lần. KẾT THÚC bằng một dòng VERDICT: ok hoặc VERDICT: revise.') + '\n' + json.dumps(skeleton, ensure_ascii=False)


def preflight(session, spec):
    """Fail before spawning or consuming a retry if required capabilities are off."""
    from .roles import work_check_tools
    config = session['config']
    role = spec['executorRole']
    if not any(r['id'] == role and r.get('enabled', True) for r in config['subagents']):
        return f'WORK_CHECK_UNAVAILABLE: required role {role} is disabled or missing; enable it explicitly before retrying'
    tools = work_check_tools(role, config['tools'])
    if spec['id'] == 'tests' and 'terminal_exec' not in tools:
        return 'WORK_CHECK_UNAVAILABLE: tests requires terminal_exec; owner tool setting is respected'
    if spec['id'] in ('evidence', 'critique', 'whole') and not tools & {'file_read', 'web_fetch', 'read_source', 'codebase_grep'}:
        return 'WORK_CHECK_UNAVAILABLE: no tool to open original evidence; enable the required read capability explicitly'
    return None


class Checks:
    def __init__(self, graph):
        self.graph = graph
        self.db = graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_checks (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, invocation TEXT NOT NULL,
                request_hash TEXT NOT NULL, doc TEXT NOT NULL,
                UNIQUE(run_id, invocation));
        ''')
        # A restarted process must not turn an unfinished check into a pass or start it twice.
        for row in self.db.execute('SELECT * FROM work_checks').fetchall():
            doc = json.loads(row['doc'])
            if doc['status'] == 'running':
                doc.update(status='error', error='Interrupted by restart; use a new invocationId.')
                self.save(doc)

    def save(self, doc):
        with self.db:
            self.db.execute('UPDATE work_checks SET doc=? WHERE id=?', (json.dumps(doc, ensure_ascii=False), doc['checkId']))

    def records(self, run_id):
        return [json.loads(row['doc']) for row in self.db.execute('SELECT doc FROM work_checks WHERE run_id=?', (run_id,))]

    def binding(self, run, node, stage):
        dependencies = {}
        for dep_id in node['dependsOn']:
            dep = next(n for n in run['nodes'] if n['id'] == dep_id)
            from .work_graph import gate_stage
            gate = gate_stage(node, dep, stage)
            if gate:
                state = dep['stages'].get(gate) or {}
                dependencies[dep_id] = {'definition': work_policy.definition(dep), 'artifact': state.get('artifact', {}).get('artifactId')}
        binding = {'nodeDefinition': work_policy.definition(node), 'dependencies': dependencies,
                   'owner': work_policy.digest({'goal': run['goal'], 'interviews': run.get('interviews', [])})}
        if stage == 'execute' and node['kind'] == 'plan':
            binding['ownPlan'] = node['stages']['produce'].get('artifact', {}).get('artifactId')
        return binding

    def valid(self, run, node, stage):
        state = node['stages'][stage]
        artifact = state.get('artifact')
        if not artifact or artifact['status'] != 'finalized':
            return False
        binding = self.binding(run, node, stage)
        if any(artifact['binding'].get(k) != v for k, v in binding.items()):
            return False
        policy = state.get('policy') or {}
        if (policy.get('version') != work_policy.VERSION or not policy.get('hash')
                or artifact['binding'].get('policyHash') != policy['hash']
                or work_policy.digest({k: v for k, v in policy.items() if k != 'hash'}) != policy['hash']):
            return False
        latest = self.latest(run, node, stage)
        for req in policy.get('required', []):
            if req['id'] not in latest or latest[req['id']]['status'] != 'pass':
                return False
        return True

    def latest(self, run, node, stage):
        state = node['stages'][stage]
        artifact, policy = state.get('artifact') or {}, state.get('policy') or {}
        latest = {}
        for record in self.records(run['runId']):
            if (record['nodeId'] == node['id'] and record['stage'] == stage
                    and record['artifactId'] == artifact.get('artifactId')
                    and record['policyHash'] == policy.get('hash')
                    and record['kind'] in {r['id'] for r in policy.get('required', [])}):
                previous = latest.get(record['kind'])
                if previous is None or record['startedAt'] > previous['startedAt']:
                    latest[record['kind']] = record
        return latest

    async def judge(self, session, run, node, stage, spec, metas, criteria, doc, whole=False):
        graph = self.graph
        unavailable = preflight(session, spec)
        if unavailable:
            return doc | {'status': 'unverified', 'error': unavailable, 'finishedAt': time.time(), 'attempts': []}
        lang = work_prompts.language(run['goal'])
        from . import work_budget
        policies = ([s.get('policy') or {} for n in run['nodes'] for s in n['stages'].values()]
                    if whole else [node['stages'][stage].get('policy') or {}])
        risk = 'consequential' if any(p.get('risk') == 'consequential' for p in policies) else 'normal'
        hints = work_budget.review_hints(metas, criteria, risk)
        request = work_budget.requested(spec['executorRole'],
            {'purpose': 'review', 'budgetHints': hints}, None, 40, 900)
        effective_steps = min(request['maxSteps'], session['config']['maxSteps'])
        if whole:
            goal = work_prompts.whole_review_goal(run['title'], run['goal'], lang,
                                                 research_only=work_policy.research_only(run))
        else:
            goal, _ = graph.reviewer_goal(run, node, stage, '', budget_steps=effective_steps)
            goal += work_prompts.node_review_scope(node, stage, lang)
        if whole:
            goal += work_prompts.choose(lang,
                f'\nBudget: {effective_steps} model steps; batch tools and reserve time for the verdict.',
                f'\nNgân sách: {effective_steps} vòng model; gom tool và dành thời gian viết kết luận.')
        goal += '\n' + contract(lang, criteria)
        if spec['id'] == 'tests':
            goal += work_prompts.choose(lang,
                '\nYou are the tester: run the required commands yourself. Your tool events and check report are the test evidence; '
                'the producer need not embed your later test output in its immutable handoff. ',
                '\nBạn là tester: tự chạy lệnh bắt buộc. Tool events và báo cáo check của bạn là bằng chứng test; '
                'producer không phải nhúng output test mà bạn chạy sau đó vào handoff bất biến. ')
        context = json.dumps({'snapshots': [{k: meta[k] for k in ('artifactId', 'version', 'contentHash', 'path', 'chars')}
                                             for meta in metas], 'check': spec}, ensure_ascii=False)
        source = metas[0]['binding'].get('codeSnapshot')
        if spec['id'] in ('tests', 'code_review') and not source:
            return doc | {'status': 'unverified', 'error': 'Exact code snapshot required.'}
        if source and await snapshot(graph, run['sessionId']) != source:
            return doc | {'status': 'superseded', 'error': 'Code changed before check.'}
        for retry in range(2):
            attempt_goal = goal
            if retry and doc.get('status') == 'error':
                attempt_goal += '\n' + work_prompts.choose(lang,
                    'Previous review was incomplete or invalid. ' + doc.get('error', doc.get('findings', '')),
                    'Lượt review trước chưa hoàn tất hoặc sai hợp đồng. ' + doc.get('error', doc.get('findings', '')))
            result, text = await graph.spawn(session, run, None if whole else node, stage, 'review',
                                            spec['executorRole'], attempt_goal, context, None, retry + 1,
                                            extra_binding={'checkId': doc['checkId'], 'artifactIds': [m['artifactId'] for m in metas],
                                                           'checkKind': spec['id'], 'budgetHints': hints})
            child_id = result.get('sessionId')
            status, coverage, findings = parse_report(text, criteria, require_target=True)
            doc.pop('error', None)
            doc.setdefault('attempts', []).append({'childId': child_id, 'status': status,
                'completed': complete(result), 'execution': work_budget.receipt(result)})
            doc.update(childId=child_id, coverage=coverage, findings=findings, status=status)
            if not complete(result):
                doc.update(status='error', error='Reviewer incomplete/provider failure.')
            elif not all(graph.artifacts.covered(doc['checkId'], meta, child_id) for meta in metas):
                doc.update(status='unverified', error='Reviewer did not read all assigned artifact ranges.')
            elif (spec['id'] == 'evidence' or whole and work_policy.research_only(run)
                  or any(item.get('target') == 'criterion' for item in coverage)) and not good_reads(graph, child_id):
                doc.update(status='unverified', error='No successfully opened original evidence.')
            elif status == 'pass' and spec['id'] == 'tests' and not test_proof(graph, child_id, node['tests']):
                doc.update(status='unverified', error='Missing actual successful required test command events.')
            if doc['status'] != 'error':
                break
        if source and await snapshot(graph, run['sessionId']) != source:
            doc.update(status='superseded', error='Source changed during check (including terminal side effects).')
        doc['inputConflicts'] = input_conflicts(doc.get('coverage', []), criteria) if doc['status'] == 'revise' else []
        doc['finishedAt'] = time.time()
        return doc

    async def tool(self, session, args):
        graph = self.graph
        run = graph.resolve(session['id'], args.get('runId'))
        if args.get('action', 'status') == 'status':
            return {'runId': run['runId'], 'checks': self.records(run['runId']), 'next': graph.next_step(run)}
        if args.get('action') != 'start':
            raise ValueError('WORK_CHECK_ACTION: use status or start')
        if run['status'] in ('cancelled', 'shipped', 'rejected'):
            raise ValueError('WORK_RUN_CLOSED: checks cannot start on a closed run')
        lock = graph.locks.setdefault(run['runId'], asyncio.Lock())
        if lock.locked():
            raise ValueError('WORK_RUN_BUSY: another run/check operation is active')
        async with lock:
            node = next((n for n in run['nodes'] if n['id'] == args.get('nodeId')), None)
            stage = args.get('stage', 'produce')
            if node is None or stage not in node['stages']:
                raise ValueError('WORK_NODE_UNKNOWN: node/stage not in run')
            state = node['stages'][stage]
            if state['status'] not in ('needs_checks', 'revise', 'accepted'):
                raise ValueError('WORK_CHECK_NOT_READY: producer must finish the current draft before checks')
            meta = state.get('artifact')
            if not meta or meta['status'] != 'finalized':
                raise ValueError('WORK_CHECK_NOT_READY: finalized artifact required; partial is not verifiable')
            if args.get('artifactId') != meta['artifactId']:
                raise ValueError('WORK_CHECK_STALE: use current artifactId from work_graph status')
            current = self.binding(run, node, stage)
            if any(meta['binding'].get(k) != v for k, v in current.items()):
                raise ValueError('WORK_CHECK_STALE: node, owner decisions or dependencies changed')
            policy = state['policy']
            ids = args.get('checkIds') or [r['id'] for r in policy['required']]
            if not isinstance(ids, list) or not ids or len(ids) != len(set(ids)) or not set(ids) <= {r['id'] for r in policy['required']}:
                raise ValueError('WORK_CHECK_INVALID: select ids from current required checks')
            for spec in policy['required']:
                if spec['id'] in ids:
                    unavailable = preflight(session, spec)
                    if unavailable:
                        raise ValueError(unavailable)
            invocation = str(args.get('invocationId') or '').strip()
            if not 1 <= len(invocation) <= 120:
                raise ValueError('WORK_CHECK_INVOCATION: unique invocationId required (1..120 chars)')
            graph.child_budget[run['runId']] = [8]
            records = []
            try:
                with graph.budget_paused(session['id']):
                    for cid in ids:
                        spec = next(r for r in policy['required'] if r['id'] == cid)
                        request = work_policy.digest({'node': node['id'], 'stage': stage, 'artifact': meta['artifactId'], 'policy': policy['hash'], 'ids': ids})
                        key = invocation + ':' + cid
                        row = self.db.execute('SELECT * FROM work_checks WHERE run_id=? AND invocation=?', (run['runId'], key)).fetchone()
                        if row:
                            if row['request_hash'] != request:
                                raise ValueError('WORK_CHECK_INVOCATION_CONFLICT: invocation already used for a different request')
                            records.append(json.loads(row['doc']))
                            continue
                        if state.get('inputConflicts'):
                            return graph.result(run) | {'checks': list(self.latest(run, node, stage).values()),
                                                        'inputConflicts': state['inputConflicts']}
                        previous = [c for c in self.records(run['runId']) if c.get('artifactId') == meta['artifactId']
                                    and c['kind'] == cid and c['policyHash'] == policy['hash']]
                        if len(previous) >= 3:
                            raise ValueError('WORK_CHECK_EXHAUSTED: three starts for this artifact/check; checkpoint and revise scope/artifact')
                        doc = {'checkId': 'c-' + uuid.uuid4().hex, 'runId': run['runId'], 'nodeId': node['id'],
                               'stage': stage, 'artifactId': meta['artifactId'], 'policyHash': policy['hash'],
                               'kind': cid, 'status': 'running', 'binding': meta['binding'], 'startedAt': time.time()}
                        with self.db:
                            self.db.execute('INSERT INTO work_checks VALUES(?,?,?,?,?)',
                                            (doc['checkId'], run['runId'], key, request, json.dumps(doc)))
                        criteria = {f'A{i+1}': value for i, value in enumerate(node['acceptance'])}
                        criteria['C1'] = spec['criterion']
                        try:
                            doc = await self.judge(session, run, node, stage, spec, [meta], criteria, doc)
                        except BaseException as exc:
                            doc.update(status='error', error=str(exc)[:500])
                            self.save(doc)
                            raise
                        self.save(doc)
                        records.append(doc)
            finally:
                graph.child_budget.pop(run['runId'], None)
            if self.valid(run, node, stage):
                state.update(status='accepted', feedback='', error=None)
            elif any(r['status'] == 'revise' for r in self.latest(run, node, stage).values()):
                state.update(status='revise' if state['attempts'] < state.get('maxRounds', 3) else 'rejected',
                             feedbackSource='checks',
                             feedback='\n'.join(r.get('findings', '') for r in self.latest(run, node, stage).values()
                                                if r['status'] == 'revise'))
            else:
                state['status'] = 'needs_checks'
            state['inputConflicts'] = [item for record in self.latest(run, node, stage).values()
                                      for item in record.get('inputConflicts', [])]
            if records:
                doc = records[-1]
                state['rounds'][-1].update(reviewerId=doc.get('childId'),
                    reviewerRole=next(r['executorRole'] for r in policy['required'] if r['id'] == doc['kind']),
                    verdict='ok' if state['status'] == 'accepted' else 'revise' if state['status'] in ('revise','rejected') else doc['status'],
                    findings=state.get('feedback') or doc.get('findings', ''), checkIds=[r['checkId'] for r in records])
            if stage == 'execute':
                stages = [n['stages']['execute'] for n in run['nodes'] if 'execute' in n['stages']]
                run['status'] = 'executed' if all(s['status'] == 'accepted' for s in stages) else ('execute_failed' if state['status'] == 'rejected' else 'approved')
            graph.save(run, 'checks_finished', f'{node["id"]}:{stage}')
            return graph.result(run) | {'checks': records}
