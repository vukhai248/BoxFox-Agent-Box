"""Native Space Bunny Testing child retests real fixture code after a code edit.

The harness fixture supplies the approved Build handoff; no native main/Build or
production files. Real Git code snapshots and pytest are executed in each folder.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid

from work_check_eval import ROOT, HarnessRuntime, SessionStore, FixtureExecutor, FixtureClient
from agentbox.agent_core import work_graph as wg, work_checks, work_policy


class Client(FixtureClient):
    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        assert route['modelId'] == 'space-bunny-free'
        result = await super().complete(messages, tools, route, **kwargs)
        self.calls.append({'route': route, 'maxTokens': kwargs.get('max_tokens'), 'usage': result.get('usage'),
            'requestId': result.get('id'), 'finishReason': result.get('choices', [{}])[0].get('finish_reason')})
        return result


def write_code(folder, valid):
    body = "import csv, io\ndef export(value):\n"
    if not valid:
        body += "    value = value.encode('ascii', errors='ignore').decode()\n"
    body += "    stream = io.StringIO(newline='')\n    csv.writer(stream).writerow([value])\n    return stream.getvalue()\n"
    (folder/'src/export.py').write_bytes(body.encode('utf8'))


async def main(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    def freeze():
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p, h in frozen.items()), 'source drift'
    freeze()
    output = Path(args.output).resolve(); assert output.is_relative_to(ROOT/'.tmp')
    output.mkdir(parents=True, exist_ok=False)
    state = await Client(args.router).snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
        if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    rows = []
    for case in ('red_to_green', 'green_to_red'):
        folder = output/case
        for directory in ('src', 'docs', 'tests'): (folder/directory).mkdir(parents=True)
        (folder/'docs/source.md').write_bytes('Yêu cầu: xuất CSV và giữ đúng Unicode tiếng Việt.\n'.encode('utf8'))
        (folder/'tests/test_export.py').write_bytes("import csv, io\nfrom src.export import export\ndef test_unicode():\n    assert next(csv.reader(io.StringIO(export('Hồ sơ')))) == ['Hồ sơ']\n".encode('utf8'))
        (folder/'.gitignore').write_bytes(b'sessions.db*\n.plans/\n.pytest_cache/\n**/__pycache__/\n')
        write_code(folder, case == 'green_to_red')
        subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
        subprocess.run(['git', 'add', 'src', 'docs', 'tests', '.gitignore'], cwd=folder, check=True)
        subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@localhost', 'commit', '-qm', 'fixture'], cwd=folder, check=True)
        client = Client(args.router); store = SessionStore(folder/'sessions.db')
        rt = HarnessRuntime(store, FixtureExecutor(folder), client)
        sid = rt.create({**route, 'skills': [], 'maxSteps': 24, 'deadlineSeconds': 300})['id']
        graph = wg.service(rt)
        run = graph.create(store.get(sid), {'goal': 'Sửa xuất CSV để giữ đúng Unicode tiếng Việt, nghiệm thu bằng test đã giao.',
            'flow': 'fix', 'nodes': [{'id': 'B1', 'kind': 'build', 'title': 'Xuất CSV',
                'goal': 'Giữ đúng Unicode khi xuất CSV; chỉ thay src/export.py.',
                'acceptance': ['CSV giữ đúng chuỗi Hồ sơ khi đọc lại'], 'tests': ['python -m pytest -q']}]})
        node = run['nodes'][0]; stage = node['stages']['execute']
        row = {'case': case, 'route': route, 'sourceManifest': frozen, 'checks': [],
            'scope': 'Native Testing only; fixture-approved Build artifacts, actual code edits/Git snapshots/pytest; no main/UI'}
        started = time.monotonic()
        try:
            for index in range(2):
                if index: write_code(folder, case == 'red_to_green')
                run['status'] = 'approved'
                text = f'# Bàn giao bản {index+1}\nPhạm vi: src/export.py. Giữ CSV/Unicode. Chưa chạy test; Testing phải tự chạy.\n'
                policy = work_policy.derive(run, node, 'execute', text, changed=True)
                source = await work_checks.snapshot(graph, sid)
                assert source
                binding = graph.checks.binding(run, node, 'execute') | {'policyHash': policy['hash'], 'codeSnapshot': source}
                meta = await graph.artifacts.put(run, node['id'], 'execute', text, binding, True)
                stage.update(status='needs_checks', attempts=index+1, policy=policy, artifact=meta,
                    rounds=stage['rounds']+[{'attempt': index+1, 'producerRole': 'build', 'at': time.time()}])
                graph.save(run)
                result = await graph.checks.tool(store.get(sid), {'action': 'start', 'runId': run['runId'],
                    'nodeId': node['id'], 'stage': 'execute', 'artifactId': meta['artifactId'], 'checkIds': ['tests'],
                    'invocationId': uuid.uuid4().hex})
                doc = result['checks'][0]
                row['checks'].append({'doc': doc, 'answer': graph.child_answer(doc.get('childId')),
                    'tools': work_checks.observations(graph, doc.get('childId')),
                    'covered': graph.artifacts.covered(doc['checkId'], meta, doc.get('childId')),
                    'lifetime': store.child_usage_from_events(doc['childId'])})
            first, second = [r['doc'] for r in row['checks']]
            row['oracle'] = (first['status'] == ('revise' if case == 'red_to_green' else 'pass')
                and second['status'] == ('pass' if case == 'red_to_green' else 'revise')
                and second['childId'] == first['childId'] and second.get('retestOf') == first['checkId']
                and second['admissionSeq'] > first['admissionSeq']
                and second['binding']['codeSnapshot']['hash'] != first['binding']['codeSnapshot']['hash']
                and all(r['covered'] for r in row['checks'])
                and row['checks'][1]['lifetime'][0] > row['checks'][0]['lifetime'][0]
                and all(any(t['name'] == 'terminal_exec' and t['args']['command'] == 'python -m pytest -q'
                            for t in r['tools']) for r in row['checks']))
        except Exception as exc:
            row.update(oracle=False, error=str(exc))
        row.update(calls=client.calls, latencySeconds=round(time.monotonic()-started, 3),
            rootModelAttempts=store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='completion_attempt'", (sid,)).fetchone()[0])
        rows.append(row)
        (output/'results.json').write_bytes((json.dumps(rows, ensure_ascii=False, indent=2)+'\n').encode('utf8'))
        print(json.dumps({k: row.get(k) for k in ('case', 'oracle', 'latencySeconds', 'error')}, ensure_ascii=False), flush=True)
        await rt.stop(sid); store.db.close()
    freeze()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True); parser.add_argument('--manifest', required=True)
    asyncio.run(main(parser.parse_args()))
