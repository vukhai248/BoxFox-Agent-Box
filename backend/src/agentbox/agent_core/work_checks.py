"""Main-dispatched verification, fail-closed contracts and snapshot bindings."""
import asyncio
import base64
import json
import re
import time
import uuid

from . import work_policy, work_prompts, work_repair, work_worktrees

INPUTS_VERSION = 'work-check-inputs/2'  # W6.1.3: findings/citation contract

SNAPSHOT_SCRIPT = '''import hashlib,json,os,re,subprocess
p=subprocess.run(['git','ls-files','-co','--exclude-standard','-z'],capture_output=True,check=True)
paths=sorted(set(x.decode('utf-8') for x in p.stdout.split(b'\\0') if x))
ignored=subprocess.run(['git','ls-files','-o','-i','--exclude-standard','-z'],capture_output=True,check=True)
source_ext=('.py','.ts','.tsx','.js','.jsx','.mjs','.json','.toml','.yaml','.yml','.sql','.sh','.ps1','.html','.css','.env')
paths=sorted(set(paths+[x.decode('utf-8') for x in ignored.stdout.split(b'\\0') if x and x.decode('utf-8').endswith(source_ext)]))
JUNK=('.plans','.tmp','.boxfox','.pytest_cache','__pycache__','test-results','coverage','node_modules','.venv','venv')
junk=lambda path: any(x in JUNK for x in path.split('/')) or path.endswith(('.pyc','.pyo'))
paths=[path for path in paths if not junk(path)]
if len(paths)>30000: raise ValueError('snapshot file limit')
h=hashlib.sha256(); total=0
for path in paths:
 if junk(path): continue
 if not os.path.lexists(path): data=b'<deleted>'
 elif os.path.islink(path): data=os.readlink(path).encode('utf-8')
 elif os.path.isfile(path):
  total+=os.path.getsize(path)
  if total>268435456: raise ValueError('snapshot byte limit')
  with open(path,'rb') as f: data=f.read()
 else: continue
 h.update(path.encode('utf-8')+b'\\0'+hashlib.sha256(data).digest())
head=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,check=True).stdout.decode().strip()
base=os.environ.get('BOXFOX_SNAPSHOT_BASE') or 'HEAD'
diff=subprocess.run(['git','diff','--name-only',base,'-z'],capture_output=True,check=True).stdout
changed=[x.decode('utf-8') for x in diff.split(b'\\0') if x]
tracked=subprocess.run(['git','ls-files','-z'],capture_output=True,check=True).stdout
tracked={x.decode('utf-8') for x in tracked.split(b'\\0') if x}
changed+=sorted(set(paths)-tracked)
critical=any(re.search(r'api|schema|auth|migration|contract|concurr|lock',x,re.I) for x in changed) or len(changed)>8
print(json.dumps({'schema':'work-code/1','hash':h.hexdigest(),'head':head,'criticalChanges':critical}))
'''
SNAPSHOT_COMMAND = "python3 -c \"import base64;exec(base64.b64decode('%s'))\"" % base64.b64encode(
    SNAPSHOT_SCRIPT.encode()).decode()


async def snapshot(graph, sid, root=None, base=None):
    """Code identity of the workspace, or (W8.A4.4) of one run/node worktree.

    A scoped snapshot records its `root`/`base` so every later comparison reads the
    same tree: node A editing its worktree never makes node B's snapshot stale.
    """
    command = SNAPSHOT_COMMAND
    if base:
        if not re.fullmatch(r'[0-9a-f]{40}', str(base)):
            return None
        command = f'BOXFOX_SNAPSHOT_BASE={base} {command}'
    if root:
        from .work_worktrees import ROOT_RE
        if not ROOT_RE.fullmatch(str(root)):
            return None
        command = f"cd '{root}' && {command}"
    try:
        result = await graph.rt.executor.execute('terminal_exec', {'command': command, 'timeout': 90}, sid)
        if result.get('is_error') or result.get('exit_code', result.get('exitCode')) != 0:
            return None
        value = json.loads(result.get('content') or result.get('output') or '')
        if value.get('schema') == 'work-code/1' and re.fullmatch(r'[a-f0-9]{64}', value.get('hash', '')):
            if root:
                value['root'] = root
            if base:
                value['base'] = base
            return value
    except Exception:
        pass
    return None


async def snapshot_of(graph, sid, source):
    """Re-read the tree a stored snapshot was taken from (legacy: the whole workspace)."""
    source = source if isinstance(source, dict) else {}
    return await snapshot(graph, sid, source.get('root'), source.get('base'))


def complete(result):
    return isinstance(result, dict) and result.get('status') == 'completed' and not result.get('is_error')


def observations(graph, child_id, *, after=None):
    if not child_id:
        return []
    try:
        admission = (graph.store.get(child_id)['config'].get('workBinding') or {}).get('admissionSeq', 0) if after is None else after
    except KeyError:
        return []
    rows = graph.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='tool_end' AND seq>? ORDER BY seq",
                            (child_id, admission)).fetchall()
    return [json.loads(row['payload']) for row in rows]


def good_reads(graph, child_id, *, retained_checkpoint=False):
    # Reading a workspace copy of the assigned artifact is still self-evidence,
    # even when the model uses file_read rather than work_artifact_read.
    try:
        binding = graph.store.get(child_id)['config'].get('workBinding') or {}
    except KeyError:
        binding = {}
    start = None
    if retained_checkpoint and binding.get('purpose') == 'produce' and binding.get('stage') == 'produce':
        # A same-assignment producer may use sources genuinely opened before
        # its durable checkpoint. This is observed evidence, not a current
        # revalidation. Test/reviewer callers always use the new admission only.
        records = graph.feedback.records(binding['runId'])
        resumed = any(d['childId'] == child_id and d['status'] == 'consumed'
                      and d.get('resumedBinding', {}).get('admissionSeq') == binding.get('admissionSeq') for d in records)
        if resumed:
            for doc in records:
                if doc['childId'] != child_id or doc['status'] != 'consumed':
                    continue
                if any(doc['binding'].get(k) != binding.get(k) for k in ('nodeId', 'stage', 'purpose', 'checkKind')):
                    continue
                try:
                    graph.feedback.validate(doc)
                except ValueError:
                    continue
                seq = doc['binding'].get('admissionSeq', 0)
                start = seq if start is None else min(start, seq)
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
    return [item for item in observations(graph, child_id, after=start)
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


# --- W6.1.3: finding/citation contract và self-challenge ------------------------------------------
FINDING_LIMIT = 8
FINDING_CLAIM_MAX = 300
FINDING_REFS_MAX = 6
PROSE_WORD_CAP = 600
COUNTER_OUTCOMES = ('refuted', 'confirmed', 'not_run')
NUMERIC_CLAIM_RE = re.compile(
    r'(\d[\d.,]*)\s*(?:-\s*)?(?:chars?|characters?|bytes?|code[ -]?points?|words?|lines?|ký tự|byte|từ|dòng)\b',
    re.I)
COMPUTE_TOOLS = ('verify_exec', 'terminal_exec')
SOURCE_TOOLS = ('file_read', 'web_fetch', 'read_source', 'codebase_grep', 'work_artifact_read')


def report_json(raw):
    """The last fenced json object of a report, or {} (legacy/prose reports stay parseable)."""
    blocks = re.findall(r'```json\s*\n(.*?)\n```', str(raw or ''), re.S)
    try:
        value = json.loads(blocks[-1]) if blocks else {}
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def prose_words(raw):
    """Words outside fenced blocks and the VERDICT line: the contract's 600-word cap is a metric."""
    text = re.sub(r'```.*?```', ' ', str(raw or ''), flags=re.S)
    text = re.sub(r'^\s*VERDICT: (?:ok|revise)\s*$', ' ', text, flags=re.M)
    return len(re.findall(r'\S+', text))


def receipt_index(graph, child_id, admission_seq, artifacts):
    """ref -> observed content text ('' when none) for refs valid in THIS admission only."""
    from .work_feedback import evidence_signature
    index = {}
    for event in observations(graph, child_id, after=admission_seq or 0):
        result = event.get('result') if isinstance(event.get('result'), dict) else {}
        name = event.get('name')
        receipt = result.get('receipt') if name == 'verify_exec' else None
        # A failed tool proves nothing, except a verify_exec timeout: that is still an observation.
        if result.get('is_error') and not isinstance(receipt, dict):
            continue
        text = str(result.get('content') or result.get('text') or result.get('output') or '')
        # `computed`: the observation may stand in for a CALCULATED number. A run that timed out, was
        # cut by the output cap, failed, or printed nothing proves no value — citing it as `computed`
        # is how a receipt that proves nothing used to satisfy the numeric gate (review vòng 2, F6).
        entry = {'kind': name, 'text': text,
                 'computed': bool(name in COMPUTE_TOOLS and text.strip() and not result.get('is_error')
                                  and not (isinstance(receipt, dict)
                                           and (receipt.get('timedOut') or receipt.get('outputOverflow'))))}
        if event.get('id'):
            index[str(event['id'])] = entry
        signature = evidence_signature(event)
        if signature:
            index.setdefault(signature['ref'], entry)
    for meta in artifacts or []:
        ref = f"artifact:{meta.get('artifactId')}@{meta.get('contentHash')}"
        text = ''
        try:
            _, text = graph.artifacts.get(meta['runId'], meta['artifactId'])
        except (KeyError, ValueError, TypeError, AttributeError):
            continue  # an unknown or corrupt snapshot is not a valid receipt
        index[ref] = {'kind': 'work_artifact_read', 'text': text}
    return index


def finding_problem(item, required, scope_kind, receipts):
    """None when a blocking finding stands; otherwise the downgrade reason."""
    refs = item.get('evidenceRefs')
    if scope_kind == 'node' and item.get('scope') == 'run':
        return 'SCOPE_RUN_IN_NODE_REVIEW'
    if item.get('criterionId') not in required:
        return 'CRITERION_UNKNOWN'
    if not isinstance(refs, list) or not refs or not all(isinstance(r, str) and r.strip() for r in refs):
        return 'NO_RECEIPT'
    if any(ref not in receipts for ref in refs):
        return 'UNKNOWN_RECEIPT'
    for number in NUMERIC_CLAIM_RE.findall(item['claim']):
        computed = any(receipts[ref].get('computed') for ref in refs)
        sourced = any(receipts[ref]['kind'] in SOURCE_TOOLS and number in receipts[ref]['text'] for ref in refs)
        if not computed and not sourced:
            return 'NUMERIC_UNVERIFIED'
    counter = item.get('counterCheck')
    if (not isinstance(counter, dict) or counter.get('outcome') not in COUNTER_OUTCOMES
            or not isinstance(counter.get('strongest'), str) or not counter['strongest'].strip()):
        return 'NO_COUNTERCHECK'
    if counter['outcome'] == 'confirmed':
        return 'SELF_REFUTED'  # the strongest objection held, yet the finding still claims to block
    if counter['outcome'] == 'refuted' and (not isinstance(counter.get('checkedBy'), str)
                                           or not counter['checkedBy'].strip()):
        return 'NO_COUNTERCHECK'  # "refuted" must name what refuted it (receipt id or source)
    return None


def validate_findings(graph, child_id, admission_seq, raw, required, scope_kind, artifacts):
    """Backend check of the findings block; the model's VERDICT alone never blocks.

    Returns {'findings': n, 'blocking': [ids], 'notes': [ids], 'downgraded': [{findingId, reason}],
    'items': [...]}. Called right after parse_report() and before the existing gates.
    """
    items = report_json(raw).get('findings')
    items = items if isinstance(items, list) else []
    receipts = receipt_index(graph, child_id, admission_seq, artifacts) if child_id else {}
    blocking, notes, downgraded, kept = [], [], [], []
    for position, item in enumerate(items):
        fid = str(item.get('id') or f'F{position + 1}') if isinstance(item, dict) else f'F{position + 1}'
        if position >= FINDING_LIMIT:
            downgraded.append({'findingId': fid, 'reason': 'FINDING_LIMIT'})
            continue
        if (not isinstance(item, dict) or item.get('severity') not in ('blocking', 'note')
                or item.get('scope', 'node') not in ('node', 'run')
                or not isinstance(item.get('claim'), str) or not item['claim'].strip()
                or len(item['claim']) > FINDING_CLAIM_MAX
                or isinstance(item.get('evidenceRefs'), list) and len(item['evidenceRefs']) > FINDING_REFS_MAX):
            downgraded.append({'findingId': fid, 'reason': 'MALFORMED'})
            continue
        kept.append(item | {'id': fid})
        if item['severity'] == 'note':
            notes.append(fid)  # a side remark never blocks
            continue
        reason = finding_problem(item, required, scope_kind, receipts)
        if reason:
            downgraded.append({'findingId': fid, 'reason': reason})
            notes.append(fid)
        else:
            blocking.append(fid)
    return {'findings': len(items), 'blocking': blocking, 'notes': notes, 'downgraded': downgraded,
            'items': kept}


def apply_findings(raw, status, coverage, analysis):
    """Re-derive status: only a valid blocking finding (or an evidenced criterion conflict) revises.

    A report that never declares `findings` keeps the old semantics (policy-10 records and legacy
    fixtures stay readable); the stricter rule applies to the new contract.

    Returns (status, coverage, uncitedError|None).
    """
    if status == 'error' or not isinstance(report_json(raw).get('findings'), list):
        return status, coverage, None
    by_id = {item['id']: item for item in analysis['items']}
    valid = set(analysis['blocking'])
    reasons = {d['findingId']: d['reason'] for d in analysis['downgraded']}
    uncited, updated = [], []
    for entry in coverage:
        entry = dict(entry)
        if entry['status'] == 'revise' and entry.get('target', 'artifact') != 'criterion':
            linked = entry.get('findingIds')
            linked = [str(x) for x in linked] if isinstance(linked, list) and linked else \
                [fid for fid, item in by_id.items() if item.get('criterionId') == entry['id']]
            if not any(fid in valid for fid in linked):
                entry['status'] = 'unverified'
                entry['findingError'] = 'WORK_FINDING_UNCITED'
                uncited.append((entry['id'], [(fid, reasons.get(fid, 'NOT_BLOCKING')) for fid in linked]))
        updated.append(entry)
    verdict = re.findall(r'^\s*VERDICT: (ok|revise)\s*$', str(raw or ''), re.M)[-1:] or ['revise']
    statuses = {entry['status'] for entry in updated}
    if 'revise' in statuses or verdict[0] == 'revise' and valid:
        new = 'revise'
    elif verdict[0] == 'revise' or 'unverified' in statuses:
        new = 'unverified'
    else:
        new = 'pass'
    ignored = sorted(valid) if new == 'pass' and valid else []
    if ignored:
        # Soundness: a validated blocking finding is the thing that blocks. A report cannot neutralise
        # it by marking every criterion pass and writing `VERDICT: ok` — the finding stays authoritative
        # (review vòng 2, F1). Downgrading is the only way out, and that happens in validate_findings.
        new = 'revise'
    error = None
    if ignored:
        error = ('WORK_FINDING_IGNORED: kept blocking finding(s) ' + ', '.join(ignored) + ' but every criterion '
                 'is pass and VERDICT: ok. A validated blocking finding blocks the artifact: mark the criterion '
                 'revise, downgrade the finding, or drop it.')
    if status == 'revise' and new != 'revise':
        detail = '; '.join(f"{cid}: " + (', '.join(f'{fid} {why}' for fid, why in pairs) or 'no linked finding')
                           for cid, pairs in uncited) or 'VERDICT: revise without a valid blocking finding'
        error = ('WORK_FINDING_UNCITED: ' + detail + '. A blocking finding needs criterionId, 1-6 evidenceRefs '
                 'from THIS review (tool call ids, verify:<codeHash>, artifact:<id>@<contentHash>) and a counterCheck; '
                 'numeric claims need a verify_exec/terminal_exec receipt or an opened source containing the number.')
    return new, updated, error


def stuck_criteria(state, doc, criteria, limit=2):
    """#6456(c): cùng một tiêu chí vẫn `revise` sau ≥ `limit` lượt sửa ⇒ nâng thành xung đột đầu vào.

    Con kiểm có thể cứ `revise` mãi trên một tiêu chí bất khả thi/mâu thuẫn mà không dán nhãn
    `criterion` (đo ở W8.A4.5.N lượt 14–16: coverage sai hợp đồng, `UNKNOWN_RECEIPT`, `SELF_REFUTED`).
    Luật này KHÔNG phụ thuộc nhãn của con kiểm: quá `limit` vòng sửa trên cùng một tiêu chí thì main
    phải xem lại định nghĩa nhiệm vụ thay vì sửa artifact lần thứ ba.
    """
    if doc.get('status') != 'revise' or len(state.get('repairs') or []) < limit:
        return []
    out = []
    for item in doc.get('coverage') or []:
        if item.get('status') == 'revise' and item.get('target', 'artifact') != 'criterion' \
                and item.get('id') in criteria:
            out.append({'id': item['id'], 'requirement': criteria[item['id']],
                        'evidence': item.get('evidence') or item.get('findingError') or '',
                        'source': 'stuck_criteria'})
    return out


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
                             'evidence': '<reference or finding>'} for key in criteria],
                'findings': []}
    return head + work_prompts.choose(lang,
        '\nKeep findings under 600 words. Do not rewrite the deliverable or add scope. Snapshot hashes are checked by the backend; do not spend steps recomputing them. ',
        '\nFinding dưới 600 từ. Không viết lại sản phẩm hoặc thêm phạm vi. Backend kiểm hash snapshot; không tốn bước tính lại hash. ') + work_prompts.choose(lang,
        '\ncodeSnapshot.hash identifies working-tree contents; head identifies a Git commit, and criticalChanges is a risk signal. '
        'A matching head or criticalChanges=false does not prove the working tree is unchanged. '
        'A test proves only its exercised assertions/inputs; do not infer untested quoting/encoding/empty-field behavior. ',
        '\ncodeSnapshot.hash nhận diện nội dung cây mã; head nhận diện commit Git, criticalChanges là tín hiệu rủi ro. '
        'Head trùng hoặc criticalChanges=false không chứng minh cây mã chưa đổi. '
        'Test chỉ chứng minh assertion/input thực đã chạy; không suy ra quoting/encoding/field rỗng chưa kiểm. ') + work_prompts.choose(lang,
        '\nJudge the EXACT wording of each criterion. target=criterion means THE CRITERION ITSELF is wrong: '
        'its wording is ambiguous, contradicts another requirement, or rests on a premise no implementation can satisfy. '
        'Only then use status=revise, target=criterion, with evidence naming the conflict and the correction for main. '
        'When the criterion is clear and the artifact merely does not satisfy it, use status=revise with target=artifact: '
        'that is an implementation failure, and the repair loop fixes it — never label a failing artifact criterion. '
        'Keep a factually correct artifact intact; do not silently replace the criterion and mark it pass. '
        'Every coverage entry explicitly includes target. target=criterion is not for C/G rubrics. ',
        '\nKiểm ĐÚNG nội dung từng tiêu chí. target=criterion nghĩa là CHÍNH TIÊU CHÍ sai: câu chữ mơ hồ, '
        'mâu thuẫn với yêu cầu khác, hoặc dựa trên tiền đề không artifact nào thoả được. Chỉ khi đó mới ghi '
        'status=revise, target=criterion và evidence nêu mâu thuẫn/sửa tiêu chí cho main. '
        'Khi tiêu chí RÕ RÀNG mà artifact không đạt, ghi status=revise với target=artifact: đó là lỗi triển khai '
        'và vòng sửa lo — tuyệt đối không dán nhãn criterion cho một artifact hỏng. '
        'Giữ artifact đúng dữ kiện; không âm thầm đổi nghĩa tiêu chí rồi ghi pass. '
        'Mỗi coverage entry ghi rõ target. target=criterion không áp dụng rubric C/G. ') + '\n' + json.dumps(criteria, ensure_ascii=False) + work_prompts.choose(lang,
        '\nReturn findings and a fenced json object {"coverage":[{"id":"A1","status":"pass|revise|unverified","target":"artifact|criterion","evidence":"specific reference or finding"}]}. '
        'Example for a criterion no artifact can satisfy: {"id":"A1","status":"revise","target":"criterion","evidence":"A1 rests on a premise the opened source refutes; no artifact can satisfy A1 as written, so main must correct A1."}. '
        'Include every criterion id exactly once. END with one line VERDICT: ok or VERDICT: revise.',
        '\nTrả finding và object trong fenced json {"coverage":[{"id":"A1","status":"pass|revise|unverified","target":"artifact|criterion","evidence":"tham chiếu hoặc finding cụ thể"}]}. '
        'Ví dụ tiêu chí không artifact nào thoả được: {"id":"A1","status":"revise","target":"criterion","evidence":"Tiền đề của A1 bị nguồn đã mở bác; không artifact nào thoả A1 như đang viết, main phải sửa A1."}. '
        'Mỗi id xuất hiện đúng một lần. KẾT THÚC bằng một dòng VERDICT: ok hoặc VERDICT: revise.') + work_prompts.choose(lang,
        '\nFindings (same json object, at most 8): {"id":"F1","criterionId":"A1","severity":"blocking|note",'
        '"scope":"node|run","claim":"<=300 chars","evidenceRefs":["<tool call id>","verify:<codeHash>",'
        '"artifact:<artifactId>@<contentHash>"],"counterCheck":{"strongest":"best objection to this finding",'
        '"checkedBy":"<tool call id>","outcome":"refuted|confirmed|not_run"},"impact":"...","fix":"..."}. '
        'A revise coverage entry lists its findingIds. The backend keeps a blocking finding only when every evidenceRef '
        'was observed in THIS review (1-6 refs), criterionId is assigned, counterCheck is present and not confirmed, '
        'and a numeric count/encoding/byte claim cites verify_exec/terminal_exec or an opened source containing that '
        'number; otherwise it becomes a note and the criterion is UNVERIFIED, not revise. '
        'An evidenceRef must be the toolCallId of a call YOU made in this admission (e.g. "call_ab12..."), a '
        '"verify:<codeHash>" signature returned by verify_exec, or "artifact:<artifactId>@<contentHash>". A prose '
        'reference such as "file_read:src/x.py" or "codebase_grep:NFD" matches no receipt and downgrades the finding. '
        'For any count, encoding, byte, arithmetic, parser or limit claim call verify_exec first (it reads the repo '
        'read-only, writes scratch files under /tmp/work and can reach the network) and cite its tool call id. '
        'In a node review a run-level gap is scope=run (a note for main).',
        '\nFinding (cùng object json, tối đa 8): {"id":"F1","criterionId":"A1","severity":"blocking|note",'
        '"scope":"node|run","claim":"<=300 ký tự","evidenceRefs":["<tool call id>","verify:<codeHash>",'
        '"artifact:<artifactId>@<contentHash>"],"counterCheck":{"strongest":"phản biện mạnh nhất với finding",'
        '"checkedBy":"<tool call id>","outcome":"refuted|confirmed|not_run"},"impact":"...","fix":"..."}. '
        'Coverage revise ghi findingIds. Backend chỉ giữ finding chặn khi mọi evidenceRef được quan sát trong CHÍNH '
        'lượt review này (1-6 ref), criterionId thuộc tiêu chí được giao, có counterCheck và outcome không phải confirmed, '
        'và claim số đếm/encoding/byte trích verify_exec/terminal_exec hoặc nguồn đã mở chứa đúng con số đó; nếu không, '
        'finding thành ghi chú và tiêu chí thành UNVERIFIED, không phải revise. '
        'Mỗi evidenceRef phải là toolCallId của một call BẠN đã gọi trong chính lượt này (ví dụ "call_ab12..."), '
        'chữ ký "verify:<codeHash>" do verify_exec trả về, hoặc "artifact:<artifactId>@<contentHash>". Tham chiếu văn '
        'xuôi như "file_read:src/x.py" hay "codebase_grep:NFD" không khớp receipt nào và làm finding bị hạ. '
        'Với mọi claim số đếm/encoding/byte/số học/parser/giới hạn, hãy gọi verify_exec trước (đọc repo read-only, ghi '
        'scratch trong /tmp/work, ra mạng được) rồi trích tool call id của nó. '
        'Trong review một nút, khoảng trống cấp run ghi scope=run (ghi chú cho main).') + '\n' + json.dumps(skeleton, ensure_ascii=False)


READ_TOOLS = frozenset({'file_read', 'web_fetch', 'read_source', 'codebase_grep'})


def capability_preflight(session, need):
    """W1.P — one capability gate before any child spends a turn: `str` cause or None.

    `need = {role, tools: set (all required), anyTools: set (at least one), readTool: bool,
    check: bool, code}`. Reads the owner's CURRENT config; never enables a role or tool and never
    turns a missing capability into a pass.
    """
    from .roles import allowed_tools, work_check_tools
    config = session['config']
    role = need['role']
    code = need.get('code') or ('WORK_CHECK_UNAVAILABLE' if need.get('check') else 'WORK_ROLE_UNAVAILABLE')
    if not any(r['id'] == role and r.get('enabled', True) for r in config.get('subagents') or []):
        return f'{code}: required role {role} is disabled or missing; enable it explicitly before retrying'
    owner = config.get('tools') or []
    tools = set(work_check_tools(role, owner) if need.get('check') else allowed_tools(role, owner))
    for name in sorted(set(need.get('tools') or ()) - tools):
        return f'{code}: {role} requires {name}; owner tool setting is respected'
    wanted = set(need.get('anyTools') or ())
    if wanted and not tools & wanted:
        return f'{code}: {role} requires one of {", ".join(sorted(wanted))}; owner tool setting is respected'
    if need.get('readTool') and not tools & READ_TOOLS:
        return f'{code}: no tool to open original evidence; enable the required read capability explicitly'
    return None


def preflight(session, spec):
    """Fail before spawning or consuming a retry if required capabilities are off."""
    unavailable = capability_preflight(session, {
        'role': spec['executorRole'], 'check': True,
        'tools': {'terminal_exec'} if spec['id'] == 'tests' else set(),
        'readTool': spec['id'] in ('evidence', 'critique', 'whole')})
    if unavailable and spec['id'] == 'tests' and 'terminal_exec' in unavailable:
        return 'WORK_CHECK_UNAVAILABLE: tests requires terminal_exec; owner tool setting is respected'
    return unavailable


def producer_need(role, stage, purpose):
    """Minimum capability of a spawned child; the role's own permissions decide the rest."""
    need = {'role': role, 'check': purpose == 'review', 'readTool': purpose == 'knowledge'}
    if role == 'testing' and stage == 'execute' and purpose == 'produce':
        need['tools'] = {'terminal_exec'}
    return need


class Checks:
    def __init__(self, graph):
        self.graph = graph
        self.db = graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_checks (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, invocation TEXT NOT NULL,
                request_hash TEXT NOT NULL, doc TEXT NOT NULL,
                UNIQUE(run_id, invocation));
            CREATE TABLE IF NOT EXISTS work_check_invocations (
                run_id TEXT NOT NULL, invocation TEXT NOT NULL, request_hash TEXT NOT NULL,
                check_id TEXT NOT NULL, PRIMARY KEY(run_id, invocation));
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
        return [json.loads(row['doc']) for row in self.db.execute('SELECT doc FROM work_checks WHERE run_id=? ORDER BY rowid', (run_id,))]

    def invocation_record(self, run_id, invocation, request_hash):
        row = self.db.execute('SELECT request_hash,check_id FROM work_check_invocations '
                              'WHERE run_id=? AND invocation=?', (run_id, invocation)).fetchone()
        if row:
            if row['request_hash'] != request_hash:
                raise ValueError('WORK_CHECK_INVOCATION_CONFLICT: invocation already used for a different request')
            return json.loads(self.db.execute('SELECT doc FROM work_checks WHERE id=? AND run_id=?',
                                             (row['check_id'], run_id)).fetchone()['doc'])
        # Receipts written before the alias table remain readable/idempotent.
        row = self.db.execute('SELECT request_hash,doc FROM work_checks WHERE run_id=? AND invocation=?',
                              (run_id, invocation)).fetchone()
        if row:
            if row['request_hash'] != request_hash:
                raise ValueError('WORK_CHECK_INVOCATION_CONFLICT: invocation already used for a different request')
            return json.loads(row['doc'])
        return None

    def remember_invocation(self, run_id, invocation, request_hash, check_id):
        with self.db:
            self.db.execute('INSERT INTO work_check_invocations VALUES(?,?,?,?)',
                            (run_id, invocation, request_hash, check_id))

    @staticmethod
    def input_key(run, node, stage, meta, policy, spec):
        """Backend input identity; invocation IDs do not create new work."""
        return work_policy.digest({'owner': run['sessionId'], 'run': run['runId'], 'node': node['id'],
            'stage': stage, 'artifact': {k: meta[k] for k in ('artifactId', 'version', 'contentHash', 'binding')},
            'policyHash': policy['hash'], 'check': spec, 'inputVersion': INPUTS_VERSION})

    def passed_input(self, run, node, stage, meta, policy, spec, key):
        # Select the current check first; never fall back to an older green receipt.
        doc = self.latest(run, node, stage).get(spec['id'])
        if (doc and doc['status'] == 'pass' and doc.get('inputVersion') == INPUTS_VERSION
                and doc['nodeId'] == node['id'] and doc['stage'] == stage
                and doc['artifactId'] == meta['artifactId'] and doc['policyHash'] == policy['hash']
                and doc['kind'] == spec['id'] and doc.get('binding') == meta['binding']
                and doc.get('workKey', key) == key):
            return doc
        return None

    def node(self, run, node_id):
        """Real node or the virtual `__integration__` node of a git-isolated run (W8.A4.4)."""
        return self.graph.find_node(run, node_id)

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
        if hasattr(self.graph, 'feedback'):
            decisions = [d['answers'] for d in self.graph.feedback.records(run['runId'])
                         if d['binding'].get('nodeId') == node['id'] and d['answers'] and
                         d['status'] not in ('stale', 'cancelled')]
            if decisions:
                binding['feedbackDecisions'] = work_policy.digest(decisions)
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
        if (not work_policy.version_ok(policy.get('version')) or not policy.get('hash')
                or artifact['binding'].get('policyHash') != policy['hash']
                or work_policy.digest({k: v for k, v in policy.items() if k != 'hash'}) != policy['hash']):
            return False
        latest = self.latest(run, node, stage)
        try:
            inputs = self.graph.artifacts.input_closure(run['runId'], [artifact])
            for doc in latest.values():
                self.graph.artifacts.validate_manifest(run, doc, inputs, [artifact['artifactId']])
        except (ValueError, TypeError, KeyError):
            return False
        for req in policy.get('required', []):
            if (req['id'] not in latest or latest[req['id']]['status'] != 'pass'
                    or latest[req['id']].get('inputVersion') != INPUTS_VERSION):
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

    def tester_assignment(self, run, node, stage, spec, criteria, meta):
        """Scope, not an input/version identity. Only test checks may reuse a child."""
        binding = meta['binding']
        return work_policy.digest({'goal': run['goal'], 'node': node['id'], 'stage': stage,
            'check': spec, 'criteria': criteria, 'policyHash': meta['binding'].get('policyHash'),
            'scope': {k: binding.get(k) for k in ('nodeDefinition', 'owner', 'ownPlan', 'feedbackDecisions')},
            'dependencies': {k: v.get('definition') for k, v in binding.get('dependencies', {}).items()}})

    def retest_candidate(self, session, run, node, stage, spec, criteria, meta, current_id):
        """Preserve the latest tester's context only for an actual new code body.

        A cancelled/uncertain/currently active tester, changed scope or legacy
        unbound receipt gets a new child; never fall back to an older green one.
        """
        if stage != 'execute' or spec['id'] != 'tests' or spec['executorRole'] != 'testing':
            return None
        prior = next((r for r in reversed(self.records(run['runId']))
                      if r['nodeId'] == node['id'] and r['stage'] == stage and r['kind'] == 'tests'
                      and r['checkId'] != current_id), None)
        source = meta['binding'].get('codeSnapshot') or {}
        if (not prior or not prior.get('childId')
                or prior.get('testerAssignment') != self.tester_assignment(run, node, stage, spec, criteria, meta)
                or not source.get('hash') or (prior.get('binding', {}).get('codeSnapshot') or {}).get('hash') == source['hash']
                or prior['status'] not in ('pass', 'revise', 'unverified', 'superseded')):
            return None
        try:
            child = self.graph.store.get(prior['childId'])
        except KeyError:
            return None
        work = child['config'].get('workBinding') or {}
        ledger = self.graph.store.child(child['id']) or {}
        if (child.get('parent_id') != session['id'] or child['role'] != 'testing'
                or child['status'] != 'completed' or ledger.get('status') != 'completed'
                or work.get('checkId') != prior['checkId'] or work.get('runId') != run['runId']
                or any(work.get(k) != v for k, v in {'nodeId': node['id'], 'stage': stage,
                                                   'purpose': 'review', 'checkKind': 'tests'}.items())
                or self.graph.feedback.yielded(child['id'])
                or self.graph.rt.tasks.get(child['id']) and not self.graph.rt.tasks[child['id']].done()):
            return None
        return prior

    async def revalidate_retest(self, owner, work):
        """A slot wait may invalidate the new snapshot or the owner's assignment."""
        def current():
            from .work_graph import enabled
            run = self.graph.resolve(owner, work['runId'])
            doc = next((r for r in self.records(run['runId']) if r['checkId'] == work['checkId']), None)
            node = self.graph.find_node(run, work['nodeId'])
            if (not enabled() or run['status'] in ('paused', 'cancelled', 'rejected', 'shipped')
                    or not node or not doc or doc['status'] != 'running' or doc.get('retestOf') != work['retestOf']
                    or self.graph.progress.get(work['progressAdmissionId'])['status'] != 'reserved'
                    or node['stages'][work['stage']].get('artifact', {}).get('artifactId') != doc['artifactId']
                    or any(doc['binding'].get(k) != v for k, v in self.binding(run, node, work['stage']).items())):
                raise ValueError('WORK_RETEST_STALE: paused/stopped or assignment changed while waiting for slot')
            self.graph.require_execution(run)
            self.graph.require_planning_current(run)
            return doc['binding'].get('codeSnapshot')
        source = current()
        if not source or await snapshot_of(self.graph, owner, source) != source:
            raise ValueError('WORK_RETEST_STALE: code changed while waiting for slot')
        if current() != source:
            raise ValueError('WORK_RETEST_STALE: check binding changed during code inspection')

    async def judge(self, session, run, node, stage, spec, metas, criteria, doc, whole=False):
        graph = self.graph
        # Bind the minimum transitive input set. Supporting snapshots are data,
        # not additional nodes to review or evidence of a prior semantic pass.
        targets = list(metas)
        try:
            metas = graph.artifacts.input_closure(run['runId'], targets)
        except (ValueError, TypeError, KeyError) as exc:
            return doc | {'status': 'unverified', 'error': str(exc), 'finishedAt': time.time(), 'attempts': []}
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
        if any(meta['binding'].get('purpose') == 'knowledge' for meta in metas):
            goal += work_prompts.choose(lang,
                '\nKnowledge artifacts and their opened-evidence receipts are input data, not a semantic pass. '
                'Reopen material original sources; do not accept claims just because a helper ran a tool. '
                'A receipt belongs to that artifact producerId and admission; it is not an exhaustive log of another child. '
                'A tool missing from the helper receipt does not prove the final producer did not run it. '
                'If the relevant producer log is unavailable, mark its claimed execution UNVERIFIED; '
                'do not assert a receipt mismatch by comparing different actors.',
                '\nArtifact tra cứu và receipt nguồn đã mở là dữ liệu đầu vào, không là kết luận đạt về nội dung. '
                'Mở lại nguồn gốc quan trọng; helper đã chạy tool không tự chứng minh khẳng định đúng. '
                'Receipt thuộc producerId và admission của artifact đó, không là nhật ký đầy đủ của child khác. '
                'Tool không nằm trong receipt helper không chứng minh producer cuối chưa chạy tool đó. '
                'Không có nhật ký đúng producer thì giữ claim execution là UNVERIFIED; '
                'không khẳng định receipt lệch bằng cách so hai tác nhân khác nhau.')
        if spec['id'] == 'tests':
            goal += work_prompts.choose(lang,
                '\nYou are the tester: run the required commands yourself. Your tool events and check report are the test evidence; '
                'the producer need not embed your later test output in its immutable handoff. ',
                '\nBạn là tester: tự chạy lệnh bắt buộc. Tool events và báo cáo check của bạn là bằng chứng test; '
                'producer không phải nhúng output test mà bạn chạy sau đó vào handoff bất biến. ')
            goal += work_prompts.choose(lang,
                '\nC1 is the assigned checker duty: execute every required command on the bound code and report its real result. '
                'Judge execution/reporting separately from whether the tested behavior passes. If you ran every command and honestly '
                'reported a failing assertion, that satisfies this C1 duty; mark the violated A criterion revise and keep VERDICT: revise. '
                'Missing/unrun commands or invented results do not satisfy C1. Producer saying "tests not run" is not your C1 failure, '
                'nor proof that code was not changed. If an A criterion explicitly requires producer-run tests, judge that A separately; '
                'do not invent that requirement. Do not require producer to embed your later output or commit evidence not assigned. ',
                '\nC1 là trách nhiệm checker: chạy từng lệnh bắt buộc trên mã được binding và báo kết quả thật. '
                'Kiểm việc chạy/báo cáo riêng với việc hành vi đạt test. Bạn đã chạy đủ lệnh và báo trung thực assertion đỏ thì '
                'trách nhiệm C1 này đạt; tiêu chí A về hành vi bị vi phạm ghi revise và giữ VERDICT: revise. '
                'Lệnh thiếu/chưa chạy hoặc kết quả bịa không đạt C1. Producer nói "chưa chạy test" không là lỗi C1 của bạn, '
                'cũng không chứng minh mã chưa sửa. Nếu tiêu chí A yêu cầu rõ producer tự chạy test thì kiểm A đó riêng; '
                'không tự thêm yêu cầu này. Không bắt producer nhúng output bạn chạy sau hoặc bằng chứng commit chưa được giao. ')
        target_ids = [meta['artifactId'] for meta in targets]
        doc.update(inputVersion=INPUTS_VERSION, reviewTargetArtifactIds=target_ids,
                   inputArtifactIds=[meta['artifactId'] for meta in metas if meta['artifactId'] not in target_ids])
        goal += work_prompts.choose(lang,
            '\nReview only reviewTargetArtifactIds against the assigned criteria. Other inputArtifactIds are bound '
            'supporting context: read them to assess those targets, not to reopen every supporting node as a new task. '
            'Use work_artifact_read with the supplied runId and artifactId; a folder hash is not a run ID. '
            'Workspace file copies do not satisfy audited artifact reads or prove current input coverage.',
            '\nChỉ phản biện reviewTargetArtifactIds theo tiêu chí được giao. Các inputArtifactIds khác là ngữ cảnh '
            'đầu vào đã binding: đọc để đánh giá đầu ra đích, không mở lại mọi node nguồn thành nhiệm vụ mới. '
            'Dùng work_artifact_read với runId và artifactId đã cung cấp; hash thư mục không là run ID. '
            'Đọc bản file workspace không thay thế lượt đọc artifact có audit hoặc chứng minh đã đọc đủ input hiện tại.')
        context = json.dumps({'snapshots': [{k: meta[k] for k in ('artifactId', 'nodeId', 'stage', 'version', 'contentHash', 'path', 'chars')}
                                             for meta in metas], 'runId': run['runId'],
                              'reviewTargetArtifactIds': target_ids,
                              'inputArtifactIds': [meta['artifactId'] for meta in metas if meta['artifactId'] not in target_ids],
                              'check': spec}, ensure_ascii=False)
        manifest = None
        if len(context) > 16000:
            try:
                manifest = await graph.artifacts.check_manifest(run, doc, metas, target_ids)
            except (ValueError, TypeError, KeyError) as exc:
                return doc | {'status': 'unverified', 'error': str(exc), 'finishedAt': time.time(), 'attempts': []}
            doc['inputManifest'] = manifest
            graph.checks.save(doc)  # Save the reference before admitting any checker.
            context = json.dumps({'snapshots': [{k: manifest[k] for k in
                    ('artifactId', 'nodeId', 'stage', 'version', 'contentHash', 'path', 'chars')}],
                'runId': run['runId'], 'reviewTargetArtifactIds': target_ids,
                'inputManifest': {k: manifest[k] for k in ('artifactId', 'version', 'contentHash', 'path', 'chars')},
                'inputCount': len(metas), 'check': spec}, ensure_ascii=False)
            goal += work_prompts.choose(lang,
                '\nFirst read inputManifest completely using work_artifact_read pages. It contains the complete immutable '
                'snapshot list, separating review targets from supporting inputs. Then read every referenced snapshot '
                'and its remaining ranges. A manifest read is not a content read or semantic verification. '
                'unreadArtifacts is only a limited list; use unreadArtifactCount and allAssignedArtifactsRead, '
                'and the manifest for the full assignment. Do not infer a shorter scope from the limited list. '
                'Batch at most 16 tool calls per model step, respecting the existing runtime ceiling. '
                'A model-step budget counts completions, not individual tool calls. For example, 60 short artifact '
                'reads fit in 4 batches of 15 calls, plus steps for manifest pages and long tails. '
                'The original-source lookup cap does not cap assigned artifact reads. ALL assigned inputs are mandatory; '
                'sampling apparently similar inputs cannot satisfy this contract. If insufficient budget, keep UNVERIFIED '
                'and a checkpoint rather than declaring full coverage or VERDICT: ok.',
                '\nĐầu tiên đọc hết inputManifest bằng các trang work_artifact_read. Nó chứa toàn bộ danh sách snapshot '
                'bất biến, tách đích phản biện với input hỗ trợ. Sau đó đọc mọi snapshot và các range còn lại. '
                'Đọc manifest không thay việc đọc nội dung hoặc chứng minh chất lượng. unreadArtifacts chỉ là danh sách '
                'giới hạn; dùng unreadArtifactCount, allAssignedArtifactsRead và manifest cho toàn nhiệm vụ. '
                'Không suy phạm vi nhỏ hơn từ danh sách giới hạn. '
                'Mỗi bước model gom tối đa 16 tool calls theo trần runtime hiện có. '
                'Ngân sách vòng model đếm lượt completion, không đếm từng tool call. Ví dụ 60 artifact ngắn có thể '
                'đọc trong 4 batch mỗi batch 15 calls, cộng các vòng đọc trang manifest và đuôi input dài. '
                'Trần tra cứu nguồn gốc không giới hạn việc đọc artifact được giao. MỌI input được giao đều bắt buộc; '
                'lấy mẫu các input có vẻ giống nhau không đạt hợp đồng. Nếu thiếu ngân sách, giữ UNVERIFIED và checkpoint, '
                'không tuyên bố đã đọc đủ hoặc VERDICT: ok.')
            metas = [manifest] + metas
        if len(context) > 16000:
            # A large check definition is not a ref list and cannot be silently cut.
            return doc | {'status': 'unverified', 'error': 'WORK_CHECK_INPUT_CONTEXT_TOO_LARGE: '
                          'check definition still exceeds the existing context limit',
                          'finishedAt': time.time(), 'attempts': []}
        source = targets[0]['binding'].get('codeSnapshot')
        if spec['id'] in ('tests', 'code_review') and not source:
            return doc | {'status': 'unverified', 'error': 'Exact code snapshot required.'}
        if source and await snapshot_of(graph, run['sessionId'], source) != source:
            return doc | {'status': 'superseded', 'error': 'Code changed before check.'}
        previous_tester = None if whole else self.retest_candidate(session, run, node, stage, spec, criteria, targets[0], doc['checkId'])
        if previous_tester:
            doc.update(retestOf=previous_tester['checkId'], previousArtifactId=previous_tester['artifactId'])
            self.save(doc)  # Slot/restart guards read the canonical retest assignment.
            goal += work_prompts.choose(lang,
                '\nRetest on a new code snapshot. Keep your previous investigation as context only; '
                'read every new assigned artifact and run EVERY required command in this admission. '
                'Earlier green results cannot establish this revision passes.',
                '\nKiểm tra lại snapshot mã mới. Giữ điều tra trước làm ngữ cảnh; '
                'đọc mọi artifact mới được giao và chạy lại TỪNG lệnh bắt buộc trong lượt này. '
                'Kết quả xanh cũ không chứng minh bản sửa hiện tại đạt.')
        for retry in range(2):
            attempt_goal = goal
            if retry and doc.get('status') == 'error':
                attempt_goal += '\n' + work_prompts.choose(lang,
                    'Previous review was incomplete or invalid. ' + doc.get('error', doc.get('findings', '')),
                    'Lượt review trước chưa hoàn tất hoặc sai hợp đồng. ' + doc.get('error', doc.get('findings', '')))
            result, text = await graph.spawn(session, run, None if whole else node, stage, 'review',
                                            spec['executorRole'], attempt_goal, context, None, retry + 1,
                                            extra_binding={'checkId': doc['checkId'], 'artifactIds': [m['artifactId'] for m in metas],
                                                           **({'resumeChildId': previous_tester['childId']} if previous_tester and not retry else {}),
                                                           **({'retestOf': previous_tester['checkId']} if previous_tester and not retry else {}),
                                                           **({'inputManifestId': manifest['artifactId']} if manifest else {}),
                                                           # W8.A4.3: the tester/reviewer reads and runs in the node worktree.
                                                           **({'workspace': workspace} if (workspace := graph.workspace_of(run, node)) else {}),
                                                           'checkKind': spec['id'], 'budgetHints': hints,
                                                           **({'controllerAction': doc['controllerAction']} if doc.get('controllerAction') else {})})
            if result.get('request'):
                doc.update(childId=result['sessionId'], status='needs_user', requestId=result['request']['requestId'],
                           error='Saved checkpoint: main must resolve request before continuing this checker.')
                break
            child_id = result.get('sessionId')
            status, coverage, findings = parse_report(text, criteria, require_target=True)
            doc.pop('error', None)
            admission = (graph.store.get(child_id)['config'].get('workBinding') or {}).get('admissionSeq', 0) \
                if child_id else 0
            analysis = validate_findings(graph, child_id, admission, findings if status != 'error' else '',
                                         criteria, 'run' if whole else 'node', metas)
            status, coverage, uncited = apply_findings(findings, status, coverage, analysis)
            if uncited and not retry and str(uncited).startswith('WORK_FINDING_UNCITED'):
                # Only an INVALID report (revise without a valid blocking finding) earns a retry with the
                # reasons. `WORK_FINDING_IGNORED` is the opposite case: the finding is valid and the backend
                # overrides the verdict to `revise`; turning that into `error` let a fresh attempt drop the
                # finding and pass the artifact (review vòng 2, F1 — reproduced end-to-end).
                status = 'error'
            doc.setdefault('attempts', []).append({'childId': child_id, 'status': status,
                'completed': complete(result), 'execution': work_budget.receipt(result),
                'findings': analysis['findings'], 'blocking': len(analysis['blocking']),
                'downgraded': analysis['downgraded'],
                **({'overLimit': True} if prose_words(text) > PROSE_WORD_CAP else {}),
                **({'contractError': str(uncited).split(':', 1)[0]} if uncited else
                   {'contractError': findings} if status == 'error' else {})})
            doc.update(childId=child_id, coverage=coverage, findings=findings, status=status,
                       blocking=analysis['blocking'], downgraded=analysis['downgraded'],
                       findingNotes=analysis['notes'])
            if uncited:
                doc['error'] = uncited
            if child_id:
                doc['admissionSeq'] = admission
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
        if source and await snapshot_of(graph, run['sessionId'], source) != source:
            doc.update(status='superseded', error='Source changed during check (including terminal side effects).')
        # `node` là None ở lượt duyệt TOÀN kế hoạch: chỉ lượt kiểm gắn nút mới có vòng sửa để đếm.
        stuck = stuck_criteria(node['stages'][stage], doc, criteria) if node else []
        doc['inputConflicts'] = (input_conflicts(doc.get('coverage', []), criteria)
                                 if doc['status'] == 'revise' else []) + stuck
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
            receipt = await self.busy_receipt(session, graph.current(run['runId']), args)
            if receipt is not None:
                return receipt
            raise ValueError('WORK_RUN_BUSY: another run/check operation is active')
        async with lock:
            run = graph.get(run['runId'])
            graph.live[run['runId']] = run
            try:
                return await self.start_locked(session, run, args)
            finally:
                graph.live.pop(run['runId'], None)

    async def busy_receipt(self, session, run, args):
        """Join an already admitted identical check; never start work without the run lock."""
        if session.get('parent_id') or session['id'] != run['sessionId']:
            raise PermissionError('WORK_ROOT_ONLY: only owner may join checks')
        if run['status'] in ('cancelled', 'shipped', 'rejected', 'paused') or args.get('recheck', False):
            return None
        node = self.node(run, args.get('nodeId'))
        stage = args.get('stage', 'produce')
        state = node['stages'].get(stage, {}) if node else {}
        meta, policy = state.get('artifact') or {}, state.get('policy') or {}
        if meta.get('artifactId') != args.get('artifactId') or meta.get('status') != 'finalized':
            return None
        registered, _ = self.graph.artifacts.get(run['runId'], meta['artifactId'])
        if registered != meta or any(meta['binding'].get(k) != v for k,v in self.binding(run,node,stage).items()):
            return None
        if (meta['binding'].get('policyHash') != policy.get('hash') or not work_policy.version_ok(policy.get('version'))
                or work_policy.digest({k:v for k,v in policy.items() if k!='hash'}) != policy.get('hash')):
            return None
        ids = args.get('checkIds') or [s['id'] for s in policy['required']]
        if not isinstance(ids, list) or not ids or len(ids)!=len(set(ids)) or not set(ids)<={s['id'] for s in policy['required']}:
            return None
        invocation = str(args.get('invocationId') or '').strip()
        if not 1 <= len(invocation) <= 120:
            raise ValueError('WORK_CHECK_INVOCATION: unique invocationId required (1..120 chars)')
        current = self.latest(run,node,stage)
        docs = []
        for cid in ids:
            spec = next(s for s in policy['required'] if s['id']==cid)
            unavailable = preflight(session,spec)
            if unavailable:
                raise ValueError(unavailable)
            doc = current.get(cid)
            if not doc or doc['status'] not in ('running','pass') or doc.get('workKey') != self.input_key(run,node,stage,meta,policy,spec):
                return None
            docs.append(doc)
        source = meta['binding'].get('codeSnapshot')
        if source and await snapshot_of(self.graph, run['sessionId'], source) != source:
            raise ValueError('WORK_CHECK_STALE: code changed; cannot join old check')
        # Re-read after an awaited snapshot: another operation may have stopped or
        # superseded the admission. Receipt aliases do not mutate the live graph.
        if run['status'] in ('paused','cancelled','shipped','rejected') or state.get('artifact') != meta:
            return None
        if any(meta['binding'].get(k) != v for k,v in self.binding(run,node,stage).items()):
            return None
        latest = self.latest(run,node,stage)
        docs = [latest.get(d['kind']) for d in docs]
        if any(not d or d['status'] not in ('running','pass') for d in docs):
            return None
        inputs = self.graph.artifacts.input_closure(run['runId'], [meta])
        for doc in docs:
            self.graph.artifacts.validate_manifest(run, doc, inputs, [meta['artifactId']])
        request = work_policy.digest({'node':node['id'],'stage':stage,'artifact':meta['artifactId'],'policy':policy['hash'],'ids':ids})
        for doc in docs:
            if not self.invocation_record(run['runId'],invocation+':'+doc['kind'],request):
                self.remember_invocation(run['runId'],invocation+':'+doc['kind'],request,doc['checkId'])
        return self.graph.result(run) | {'checks':docs,'joined':True}

    async def start_locked(self, session, run, args, controller_action=None):
        """Shared admission path; caller owns the canonical run lock/live copy."""
        graph = self.graph
        if not graph.busy(run) or graph.live.get(run['runId']) is not run:
            raise ValueError('WORK_CHECK_LOCK_REQUIRED: caller must hold the canonical run lock')
        if session.get('parent_id') or session['id'] != run['sessionId']:
            raise PermissionError('WORK_ROOT_ONLY: only the run owner may admit checks')
        if run['status'] in ('cancelled', 'shipped', 'rejected', 'paused'):
            raise ValueError('WORK_RUN_CLOSED: checks cannot start on a closed or paused run')
        recheck = args.get('recheck', False)
        if not isinstance(recheck, bool):
            raise ValueError('WORK_CHECK_INVALID: recheck must be a boolean')
        node = self.node(run, args.get('nodeId'))
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
        registered, _ = graph.artifacts.get(run['runId'], meta['artifactId'])
        if registered != meta:
            raise ValueError('WORK_CHECK_STALE: artifact metadata differs from the immutable registry')
        current = self.binding(run, node, stage)
        if any(meta['binding'].get(k) != v for k, v in current.items()):
            raise ValueError('WORK_CHECK_STALE: node, owner decisions or dependencies changed')
        policy = state['policy']
        if (not work_policy.version_ok(policy.get('version'))
                or policy.get('hash') != work_policy.digest({k:v for k,v in policy.items() if k!='hash'})
                or meta['binding'].get('policyHash') != policy.get('hash')):
            raise ValueError('WORK_CHECK_STALE: check policy or artifact policy binding changed')
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
        if node['id'] == work_worktrees.INTEGRATION_NODE:
            # W8.A4.5: one review on the converged tree, after its tests are green on that exact snapshot.
            work_repair.converged(node, policy, ids, self.latest(run, node, stage))
        own_budget = run['runId'] not in graph.child_budget
        if own_budget:
            graph.child_budget[run['runId']] = [8]
        records = []
        try:
            with graph.budget_paused(session['id']):
                for cid in ids:
                    spec = next(r for r in policy['required'] if r['id'] == cid)
                    request = work_policy.digest({'node': node['id'], 'stage': stage, 'artifact': meta['artifactId'],
                                                  'policy': policy['hash'], 'ids': ids, **({'recheck': True} if recheck else {})})
                    key = invocation + ':' + cid
                    work_key = self.input_key(run, node, stage, meta, policy, spec)
                    receipt = self.invocation_record(run['runId'], key, request)
                    if receipt and receipt.get('inputVersion') != INPUTS_VERSION:
                        raise ValueError('WORK_CHECK_RECEIPT_STALE: historical check is readable but needs '
                                         'current input verification with a new invocationId')
                    passed = None if receipt or recheck else self.passed_input(run, node, stage, meta, policy, spec, work_key)
                    if receipt or passed:
                        inputs = graph.artifacts.input_closure(run['runId'], [meta])
                        graph.artifacts.validate_manifest(run, receipt or passed, inputs, [meta['artifactId']])
                        source = meta['binding'].get('codeSnapshot')
                        if source and await snapshot_of(graph, run['sessionId'], source) != source:
                            raise ValueError('WORK_CHECK_STALE: code changed; old check receipt is not current proof')
                        if passed:
                            self.remember_invocation(run['runId'], key, request, passed['checkId'])
                        records.append(receipt or passed)
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
                           'kind': cid, 'status': 'running', 'binding': meta['binding'], 'workKey': work_key,
                           'requestedRecheck': recheck, 'startedAt': time.time()}
                    if controller_action:
                        doc['controllerAction'] = controller_action
                    with self.db:
                        self.db.execute('INSERT INTO work_checks VALUES(?,?,?,?,?)',
                                        (doc['checkId'], run['runId'], key, request, json.dumps(doc)))
                        self.db.execute('INSERT INTO work_check_invocations VALUES(?,?,?,?)',
                                        (run['runId'], key, request, doc['checkId']))
                    criteria = {f'A{i+1}': value for i, value in enumerate(node['acceptance'])}
                    criteria['C1'] = spec['criterion']
                    if cid == 'tests' and stage == 'execute':
                        doc['testerAssignment'] = self.tester_assignment(run, node, stage, spec, criteria, meta)
                        self.save(doc)
                    try:
                        doc = await self.judge(session, run, node, stage, spec, [meta], criteria, doc)
                    except BaseException as exc:
                        doc.update(status='error', error=str(exc)[:500])
                        self.save(doc)
                        raise
                    self.save(doc)
                    records.append(doc)
        finally:
            if own_budget:
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
        if stage == 'execute' and node['id'] == work_worktrees.INTEGRATION_NODE:
            integration = run.setdefault('integration', {})
            if state['status'] == 'accepted':
                integration.update(status='checked', checkIds=[r['checkId'] for r in self.latest(run, node, stage).values()],
                                   checkedAt=time.time())
            elif integration.get('status') == 'checked':
                integration.update(status='pending')
        if stage == 'execute':
            run['status'] = graph.execute_status(run) or ('execute_failed' if state['status'] == 'rejected' else 'approved')
        graph.save(run, 'checks_finished', f'{node["id"]}:{stage}')
        out = graph.result(run) | {'checks': records}
        if stage == 'execute' and work_repair.routed(run) and state['status'] in ('revise', 'rejected'):
            # W8.A4.5: a red check is classified and repaired here; ready_nodes no longer auto-revises.
            repair = await work_repair.route(graph, session, run, node,
                                             [r for r in records if r.get('status') == 'revise'],
                                             state.get('maxRounds', 3))
            run['status'] = graph.execute_status(run) or ('execute_failed' if state['status'] == 'rejected'
                                                          else 'approved')
            graph.save(run, 'repair_routed', json.dumps({k: v for k, v in repair.items() if k != 'entry'})[:300])
            out = graph.result(run) | {'checks': records, 'repair': repair}
        return out
