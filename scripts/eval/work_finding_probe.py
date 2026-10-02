"""W6.1.3 native probe: does a real reviewer cite receipts instead of prose?

Space Bunny (OpenCode, free) reviews fixture artifacts with the new findings contract. The
reviewer may run `verify_exec` (executed locally through the sandbox worker on this host, which
has a working bubblewrap). Oracle, per case and per run:

  * every claim it blocks on carries an evidenceRef that was really observed in that admission;
  * a true finding stays blocking; a false one is downgraded or never blocks;
  * each numeric claim cites verify_exec/terminal_exec.

No main model, no Build: the harness fixture supplies the artifacts. N is small and reported.
"""
import argparse
import asyncio
import hashlib
import json
import fnmatch
from pathlib import Path
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))

from work_check_eval import ROOT, HarnessRuntime, SessionStore, FixtureClient, FixtureExecutor  # noqa: E402
from agentbox.agent_core import work_graph as wg, work_checks, work_policy  # noqa: E402
from agentbox.sandbox import worker as sandbox_worker  # noqa: E402


REVIEW_TOOLS = {'work_artifact_read', 'file_read', 'codebase_grep', 'codebase_glob', 'terminal_exec',
                'verify_exec'}


class Client(FixtureClient):
    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        assert route['modelId'] == 'space-bunny-free'
        result = await super().complete(messages, [t for t in tools if t['function']['name'] in REVIEW_TOOLS],
                                        route, **kwargs)
        self.calls.append({'route': route, 'maxTokens': kwargs.get('max_tokens'), 'usage': result.get('usage'),
                           'requestId': result.get('id'),
                           'finishReason': result.get('choices', [{}])[0].get('finish_reason')})
        return result


class Executor(FixtureExecutor):
    """Fixture files plus a real, isolated verify_exec (host bubblewrap, no Docker)."""

    def __init__(self, folder):
        super().__init__(folder)
        self.verify_calls = []

    async def execute(self, name, args, sid, **identity):
        if name == 'verify_exec':
            result = sandbox_worker.verify_exec(args)
            self.verify_calls.append({'args': args, 'receipt': result.get('receipt'),
                                      'isError': bool(result.get('is_error')), 'errorCode': result.get('errorCode')})
            return result
        if name == 'terminal_exec':
            return {'content': 'fixture terminal: no project tests in this probe', 'exit_code': 0, 'is_error': False}
        if name in ('codebase_grep', 'codebase_glob'):
            files = [str(path.relative_to(self.folder)) for path in sorted(self.folder.rglob('*'))
                     if path.is_file() and '.git' not in path.parts and 'sessions.db' not in path.name]
            if name == 'codebase_glob':
                return {'content': '\n'.join(fnmatch.filter(files, args.get('pattern') or '**/*')), 'fixture': True}
            query = args.get('query') or ''
            matches = [f'{path}:{index}: {line}' for path in files
                       for index, line in enumerate(self.path(path).read_text(encoding='utf-8', errors='replace').splitlines(), 1)
                       if query in line]
            return {'content': '\n'.join(matches), 'fixture': True}
        return await super().execute(name, args, sid, **identity)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


CASES = [
    {
        'case': 'nfd-count',
        'artifact': ('# Bàn giao: đếm ký tự\n\n'
                     "Kết luận: chuỗi tiếng Việt 'ế' ở dạng NFD có ĐÚNG 4 code point, không phải 3. "
                     'Vì vậy hàm đếm hiện tại trả sai.\n'),
        'acceptance': ['Nêu đúng số code point của chuỗi NFD'],
        'truth': "verify_exec: len(list(unicodedata.normalize('NFD','ế'))) == 3, không phải 4",
        'expect': 'blocking',
    },
    {
        'case': 'csv-error-type',
        'artifact': ('# Bàn giao: lỗi parse CSV\n\n'
                     'Kết luận: `parse_rows` ném ValueError khi gặp byte NUL, đúng như tài liệu mô tả. '
                     'Không cần sửa gì.\n'),
        'acceptance': ['Nêu đúng exception mà parse_rows ném ra với byte NUL'],
        'truth': "docs/source.md không nêu exception nào; Python 3.12 với str KHÔNG ném lỗi NUL "
                 "(đo lại bằng verify_exec: 'a\\x00b' đọc được) — artifact trích 'đúng như tài liệu' là sai",
        'expect': 'blocking',
    },
    {
        'case': 'side-remark',
        'artifact': ('# Bàn giao: ghi CSV\n\n'
                     'Kết luận: `writerow([""])` ghi ra `""\\r\\n`; mọi nghiệm thu đều đạt. '
                     'Ghi chú: thứ tự tiêu đề có thể gọn hơn.\n'),
        'acceptance': ['Ghi đúng chuỗi cho một ô rỗng'],
        'truth': 'verify_exec: csv.writer ghi ô rỗng thành ""\\r\\n là đúng',
        'expect': 'not_blocking',
    },
]


def score(doc, tools, case, artifact_id=None, content_hash=None):
    findings = work_checks.report_json(doc.get('findings') or '').get('findings') or []
    downgraded = doc.get('downgraded') or []
    surviving = doc.get('blocking')          # backend's post-downgrade blocking set
    blocking = [item for item in findings if item.get('id') in surviving] if surviving is not None \
        else [item for item in findings if item.get('severity') == 'blocking']
    observed = {event.get('id') for event in tools if isinstance(event.get('result'), dict)}
    receipts = [event for event in tools if event.get('name') == 'verify_exec'
                and isinstance((event.get('result') or {}).get('receipt'), dict)]
    # Same receipt forms the backend accepts: a real tool call id from this admission, the
    # target artifact's id@contentHash, or a verify_exec codeHash from this admission.
    verify_hashes = {event['result']['receipt'].get('codeHash') for event in receipts}
    artifact_ref = f'artifact:{artifact_id}@{content_hash}'
    def known(ref):
        return (ref in observed or ref == artifact_ref
                or (isinstance(ref, str) and ref.startswith('verify:') and ref[7:] in verify_hashes))
    cited = all(all(known(ref) for ref in item.get('evidenceRefs') or []) for item in blocking)
    numeric = all(not work_checks.NUMERIC_CLAIM_RE.findall(item.get('claim') or '')
                  or any(ref in {event.get('id') for event in receipts} for ref in item.get('evidenceRefs') or [])
                  for item in blocking)
    if case['expect'] == 'blocking':
        behaviour = doc['status'] == 'revise' and bool(blocking)
    else:
        # false-positive control: a wrong side remark must never become a blocking finding.
        # The verdict may honestly stay 'unverified' when the reviewer could not run the test.
        behaviour = not blocking
    return {
        'status': doc['status'], 'findings': len(findings), 'blocking': len(blocking),
        'downgraded': downgraded, 'cited': cited, 'numericCited': numeric,
        'verifyExecCalls': len(receipts), 'oracle': bool(cited and numeric and behaviour),
        'behaviour': behaviour, 'answer': (doc.get('findings') or '')[-1500:],
    }


async def main(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'B' or branch.startswith('vorflux/'), branch
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert sandbox_worker.verify_probe(refresh=True)['available'], 'verify_exec isolation unavailable'
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp')
    output.mkdir(parents=True, exist_ok=True)
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'backend/src/agentbox/agent_core/work_checks.py', 'backend/src/agentbox/agent_core/roles.py',
        'backend/src/agentbox/agent_core/work_prompts.py', 'backend/src/agentbox/agent_core/work_graph.py',
        'backend/src/agentbox/agent_core/work_feedback.py', 'backend/src/agentbox/sandbox/worker.py',
        'backend/src/agentbox/agent_core/tool_contracts.py')}
    client = Client(args.router)
    state = await client.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                  if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
                  if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    rows = []
    chosen = [item for item in CASES if not args.cases or item['case'] in args.cases.split(',')]
    for case in chosen:
        for attempt in range(args.repeat):
            folder = output / f"{case['case']}-{attempt + 1}"
            (folder / 'src').mkdir(parents=True, exist_ok=True)
            (folder / 'docs').mkdir(parents=True, exist_ok=True)
            (folder / 'src/export.py').write_bytes(b"import csv, io\n\n\ndef export(value):\n    return value\n")
            (folder / 'tests').mkdir(parents=True, exist_ok=True)
            (folder / 'tests/test_export.py').write_bytes(
                "import csv, io\nfrom src.export import export\n\ndef test_unicode():\n"
                "    assert next(csv.reader(io.StringIO(export('H\u1ed3 s\u01a1')))) == ['H\u1ed3 s\u01a1']\n".encode('utf8'))
            (folder / 'docs/source.md').write_bytes(
                'Yêu cầu: giữ đúng Unicode tiếng Việt và byte NUL khi xuất CSV.\n'.encode('utf8'))
            (folder / '.gitignore').write_bytes(b'sessions.db*\n.plans/\n.pytest_cache/\n**/__pycache__/\n')
            subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
            subprocess.run(['git', 'add', '-A'], cwd=folder, check=True)
            subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@localhost',
                            'commit', '-qm', 'fixture'], cwd=folder, check=True)
            store = SessionStore(folder / 'sessions.db')
            executor = Executor(folder)
            rt = HarnessRuntime(store, executor, client)
            sid = rt.create({**route, 'skills': [], 'maxSteps': 30, 'deadlineSeconds': 900})['id']
            graph = wg.service(rt)
            run = graph.create(store.get(sid), {
                'goal': f"Kiểm nội dung bàn giao: {case['truth']}", 'flow': 'plan',
                'nodes': [{'id': 'P1', 'kind': 'plan', 'title': 'Bàn giao', 'goal': case['truth'],
                           'acceptance': case['acceptance'], 'tests': ['python -m pytest -q']}]})
            node = run['nodes'][0]
            stage = node['stages']['produce']
            run['status'] = 'approved'
            policy = work_policy.derive(run, node, 'produce', case['artifact'], changed=False)
            binding = graph.checks.binding(run, node, 'produce') | {'policyHash': policy['hash']}
            meta = await graph.artifacts.put(run, node['id'], 'produce', case['artifact'], binding, True)
            stage.update(status='needs_checks', attempts=1, policy=policy, artifact=meta,
                         rounds=[{'attempt': 1, 'producerRole': 'plan', 'at': time.time()}])
            graph.save(run)
            started = time.monotonic()
            row = {'case': case['case'], 'attempt': attempt + 1, 'branch': branch, 'commit': commit,
                   'sourceManifest': sources, 'route': route, 'truth': case['truth']}
            try:
                result = await graph.checks.tool(store.get(sid), {
                    'action': 'start', 'runId': run['runId'], 'nodeId': node['id'], 'stage': 'produce',
                    'artifactId': meta['artifactId'], 'invocationId': uuid.uuid4().hex})
                doc = result['checks'][0]
                tools = work_checks.observations(graph, doc.get('childId'))
                row.update(score(doc, tools, case, meta['artifactId'], meta['contentHash']))
                row['verifyCalls'] = executor.verify_calls
                row['attempts'] = doc.get('attempts')
            except Exception as exc:
                row.update(oracle=False, error=str(exc))
            row.update(latencySeconds=round(time.monotonic() - started, 3), calls=client.calls)
            rows.append(row)
            (output / 'results.json').write_bytes(
                (json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
            print(json.dumps({k: row.get(k) for k in ('case', 'attempt', 'status', 'blocking', 'downgraded',
                                                      'verifyExecCalls', 'oracle', 'latencySeconds', 'error')},
                             ensure_ascii=False), flush=True)
            await rt.stop(sid)
            store.db.close()
    summary = {'rows': len(rows), 'oracle': sum(1 for row in rows if row.get('oracle')),
               'cases': {item['case']: sum(1 for row in rows if row['case'] == item['case'] and row.get('oracle'))
                         for item in chosen},
               'blockingTotal': sum(row.get('blocking') or 0 for row in rows),
               'downgradedTotal': sum(len(row.get('downgraded') or []) for row in rows),
               'verifyExecCalls': sum(row.get('verifyExecCalls') or 0 for row in rows)}
    (output / 'summary.json').write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


def rescore(output):
    """Re-score the on-disk fixture databases with the current oracle (no model calls)."""
    rows = json.loads((output / 'results.json').read_text(encoding='utf8'))
    for row in rows:
        folder = output / f"{row['case']}-{row['attempt']}"
        store = SessionStore(folder / 'sessions.db')
        try:
            graph = wg.service(type('RT', (), {'store': store})())
            doc = json.loads(list(store.db.execute("SELECT doc FROM work_checks"))[0][0])
            meta, _ = graph.artifacts.get(doc['runId'], doc['artifactId'])
            case = next(item for item in CASES if item['case'] == row['case'])
            tools = work_checks.observations(graph, doc.get('childId'))
            row.update(score(doc, tools, case, meta['artifactId'], meta['contentHash']))
            row['tools'] = [{'id': event.get('id'), 'name': event.get('name')} for event in tools]
        finally:
            store.db.close()
    (output / 'results.json').write_bytes((json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    for row in rows:
        print(json.dumps({k: row.get(k) for k in ('case', 'attempt', 'status', 'blocking', 'cited',
                                                  'numericCited', 'downgraded', 'verifyExecCalls', 'oracle')},
                         ensure_ascii=False))
    print(json.dumps({'rows': len(rows), 'oracle': sum(1 for row in rows if row.get('oracle'))}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router')
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeat', type=int, default=2)
    parser.add_argument('--cases', default='')
    parser.add_argument('--rescore', action='store_true')
    arguments = parser.parse_args()
    if arguments.rescore:
        rescore(Path(arguments.output).resolve())
    else:
        assert arguments.router, '--router is required unless --rescore'
        asyncio.run(main(arguments))
