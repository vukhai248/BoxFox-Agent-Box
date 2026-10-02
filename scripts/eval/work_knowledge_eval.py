"""A3.3 fixture bootstrap + native helper/same-child/checker, B / Space Bunny only.

R1 and the initial E2 lookup request are synthetic. The helper, resumed E2 and
independent reviewer use the real configured provider/tools. No full main/DAG/UI
benchmark, production sessions, provider changes or workspace code mutations.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from work_check_eval import ROOT, FixtureClient, FixtureExecutor, HarnessRuntime, SessionStore, wg, work_policy


class Client(FixtureClient):
    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        index = max(i for i,m in enumerate(messages) if m.get('role') == 'user')
        current = messages[index:]
        prompt = current[0]['content']
        initial = (prompt.startswith('Work Graph') and ('nút E2 ' in prompt or 'node E2 ' in prompt)
                   and 'Artifact trả lời yêu cầu tra cứu' not in prompt and 'Lookup artifacts for' not in prompt)
        if initial:
            self.calls.append({'phase': 'synthetic_initial_request', 'native': False})
            if not any(m.get('name') == 'file_read' for m in current):
                return {'choices': [{'message': {'tool_calls': [{'id': 'fixture-bootstrap-source', 'type': 'function',
                    'function': {'name': 'file_read', 'arguments': json.dumps({'path': 'docs/source.md'})}}]},
                    'finish_reason': 'tool_calls'}]}
            return {'choices': [{'message': {'content': '## Bản nháp fixture\nCần tra cứu ghi chú phạm vi.\n'
                '## Knowledge requests\n- research: Ghi chú docs/source.md quy định chỉ CSV hay cả JSON? '
                'Mở nguồn gốc, trích đúng câu và nêu giới hạn; không suy chất lượng mã từ ghi chú.'},
                'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 0, 'completion_tokens': 0}}
        started = time.monotonic()
        phase = 'helper' if prompt.startswith('Yêu cầu tra cứu') else 'reviewer' if prompt.startswith('Phản biện độc lập') else 'same_child_synthesis'
        result = await super().complete(messages, tools, route, **kwargs)
        self.calls.append({'phase': phase, 'native': True, 'maxTokens': kwargs.get('max_tokens'),
            'latencySeconds': round(time.monotonic() - started, 3), 'requestId': result.get('id'),
            'finishReason': result.get('choices', [{}])[0].get('finish_reason'), 'usage': result.get('usage')})
        return result


async def settle(graph):
    for _ in range(12):
        graph.handoffs.dispatch()
        tasks = list(graph.continuations.tasks.values())
        if not tasks:
            return
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 1000)
        await asyncio.sleep(0)
    raise RuntimeError('fixture controller did not quiesce')


def visible(store, sid):
    outputs = []
    for child in store.children_of(sid):
        cid = child['session_id']
        config = store.get(cid)['config']
        finals = [json.loads(r[0]).get('text', '') for r in store.db.execute(
            "SELECT payload FROM events WHERE session_id=? AND kind='assistant' ORDER BY seq", (cid,))
            if json.loads(r[0]).get('final')]
        outputs.append({'child': child, 'route': config['route'], 'maxTokens': config.get('maxTokens'),
            'workBudget': config.get('workBudget'), 'workBinding': config.get('workBinding'),
            'visibleFinals': finals, 'tools': [json.loads(r[0]) for r in store.db.execute(
                "SELECT payload FROM events WHERE session_id=? AND kind='tool_end' ORDER BY seq", (cid,))],
            'turns': [json.loads(r[0]) for r in store.db.execute(
                "SELECT payload FROM events WHERE session_id=? AND kind='turn_end' ORDER BY seq", (cid,))]})
    return outputs


async def main(args):
    if subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() != 'B':
        raise SystemExit('Only branch B is permitted')
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.tmp'):
        raise SystemExit('Output must be under B .tmp')
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in frozen.items()), 'source drift'
    probe = Client(args.router)
    state = await probe.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId'] == 'opencode' and c.get('enabled')
        for m in c['models'] if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    records = []
    for repeat in range(1, args.repeats + 1):
        folder = output / f'lookup-{repeat}'
        for part in ('docs', 'src', 'tests'):
            (folder/part).mkdir(parents=True, exist_ok=True)
        (folder/'docs/source.md').write_text('Chỉ xuất CSV; không JSON.\n', encoding='utf-8')
        (folder/'src/export.py').write_text('def export(value):\n    return value\n', encoding='utf-8')
        (folder/'tests/test_export.py').write_text('# Not executed: research scope only.\n', encoding='utf-8')
        store = SessionStore(folder/'sessions.db')
        client = Client(args.router)
        rt = HarnessRuntime(store, FixtureExecutor(folder), client)
        root = rt.create({**route, 'skills': [], 'maxSteps': 18, 'deadlineSeconds': 300, 'maxTokens': 4096})
        sid = root['id'];graph = wg.service(rt)
        goal = 'Nghiên cứu phạm vi xuất CSV theo ghi chú được cung cấp; không thêm JSON, không triển khai mã.'
        run = graph.create(root, {'goal': goal, 'flow': 'research', 'nodes': [
            {'id': 'R1', 'kind': 'explore', 'taskKind': 'lookup', 'title': 'Synthetic source checkpoint',
                'goal': 'Locate the supplied scope note'},
            {'id': 'E2', 'kind': 'research', 'title': 'Nghiên cứu phạm vi CSV', 'dependsOn': ['R1'],
                'goal': 'Trả lời dựa trên ghi chú docs/source.md: phạm vi CSV, trích nguồn và nêu giới hạn. '
                        'Không tự thêm JSON, không suy rằng mã hay test đạt từ một ghi chú. Đọc artifact tra cứu và mở nguồn gốc.',
                'acceptance': ['Giữ phạm vi chỉ CSV theo nguồn', 'Trích đúng nguồn, phân biệt giới hạn với dữ kiện đã kiểm']} ]})
        source = run['nodes'][0]
        policy = work_policy.derive(run, source, 'produce', 'Fixture source location docs/source.md')
        binding = graph.checks.binding(run, source, 'produce') | {'policyHash': policy['hash']}
        meta = await graph.artifacts.put(run, 'R1', 'produce', 'Synthetic R1 checkpoint: scope note is docs/source.md.', binding, True)
        source['stages']['produce'].update(status='accepted', artifact=meta, policy=policy)
        graph.save(run)
        graph.graph(root, {'action': 'assign_handoff', 'runId': run['runId'], 'revision': run['revision'],
            'nodeId': 'R1', 'stage': 'produce', 'predicate': 'required_checks_passed',
            'target': {'kind': 'node', 'nodeId': 'E2', 'stage': 'produce'}, 'invocationId': 'consume-scope'})
        graph.graph(root, {'action': 'assign_handoff', 'runId': run['runId'], 'revision': graph.current(run['runId'])['revision'],
            'nodeId': 'E2', 'stage': 'produce', 'predicate': 'artifact_finalized',
            'target': {'kind': 'check', 'checkIds': ['evidence']}, 'invocationId': 'check-scope'})
        store.save(sid, root['messages'], 'running')  # no root model relay
        started = time.monotonic();record = {'repeat': repeat, 'route': route, 'sourceManifest': frozen,
            'scope': 'Synthetic R1 and initial E2 request; native helper, same-child final and checker'}
        try:
            await settle(graph)
            run = graph.get(run['runId']);stage = run['nodes'][1]['stages']['produce']
            entry = stage['rounds'][0];checks = graph.checks.records(run['runId'])
            before = len(store.children_of(sid))
            graph.save(run, 'fixture_replay');await settle(graph)
            actions = graph.handoffs.actions(run['runId'])
            root_calls = store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='completion_attempt'", (sid,)).fetchone()[0]
            record.update(status=stage['status'], run=graph.result(graph.get(run['runId'])), checks=checks,
                actions=[json.loads(r['doc']) | {'status':r['status']} for r in actions], rootModelAttempts=root_calls,
                oracle=stage['status']=='accepted' and entry['producerId']==entry['initialProducerId']
                    and len(checks)==1 and checks[0]['status']=='pass' and root_calls==0
                    and all(r['status']=='completed' for r in actions) and len(actions)==2
                    and len(store.children_of(sid))==before==3 and not graph.continuations.children)
        except Exception as exc:
            record.update(status='error', error=str(exc), oracle=False)
        record.update(visibleOutputs=visible(store,sid), calls=client.calls,
            latencySeconds=round(time.monotonic()-started,3))
        records.append(record)
        (output/'results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:record.get(k) for k in ('repeat','status','oracle','latencySeconds')},ensure_ascii=False),flush=True)
        store.db.close()
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in frozen.items()), 'source changed during native run'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    asyncio.run(main(parser.parse_args()))
