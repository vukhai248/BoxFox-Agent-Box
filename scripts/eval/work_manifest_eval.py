"""A3.3b.1 native reference-manifest probes, B / OpenCode Space Bunny only.

All producer/helper documents are synthetic; the independent reviewer is native.
Large exact input closure, content-tail reads and idempotent check replay are the
oracle. This does not certify full main/DAG, medical plans, or the UI renderer.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from work_knowledge_eval import Client, visible
from work_check_eval import ROOT, FixtureExecutor, HarnessRuntime, SessionStore, wg, work_policy


async def main(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp')
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in frozen.items())
    probe = Client(args.router)
    state = await probe.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
        if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    records = []
    for case in ('valid', 'wrong_tail'):
        folder = output / case
        for part in ('docs', 'src', 'tests'):
            (folder/part).mkdir(parents=True, exist_ok=True)
        (folder/'docs/source.md').write_text('Chỉ xuất CSV; không JSON.\nGiới hạn mỗi lần xuất: 500 dòng.\n', encoding='utf8')
        (folder/'src/export.py').write_text('def export(value):\n    return value\n', encoding='utf8')
        (folder/'tests/test_export.py').write_text('# Research fixture; no execution evidence.\n', encoding='utf8')
        store = SessionStore(folder/'sessions.db')
        client = Client(args.router)
        rt = HarnessRuntime(store, FixtureExecutor(folder), client)
        session = rt.create({**route, 'skills': [], 'maxSteps': 40, 'deadlineSeconds': 600, 'maxTokens': 4096})
        sid = session['id'];graph = wg.service(rt)
        goal = 'Nghiên cứu phạm vi CSV và giới hạn số dòng theo docs/source.md, không triển khai mã.'
        run = graph.create(session, {'goal': goal, 'flow': 'research', 'nodes': [
            {'id': 'R1', 'kind': 'explore', 'taskKind': 'lookup', 'title': 'Synthetic input checkpoint',
             'goal': 'Locate the supplied original scope note'},
            {'id': 'E2', 'kind': 'research', 'title': 'Nghiên cứu phạm vi fixture', 'dependsOn': ['R1'],
             'goal': 'Tóm tắt ràng buộc CSV và số dòng; phải thống nhất với các input được giao và nguồn gốc. '
                     'Artifact tra cứu là fixture chưa phản biện, không nguồn độc lập. Không suy chất lượng mã hoặc test.',
             'acceptance': ['Giữ phạm vi chỉ CSV, không thêm JSON',
                            'Giới hạn dòng thống nhất với docs/source.md và kết luận ở cuối input hỗ trợ dài'], } ]})
        dependency, node = run['nodes']
        meta = await graph.artifacts.put(run, 'R1', 'produce', 'Synthetic checkpoint: read docs/source.md.',
                                          graph.checks.binding(run, dependency, 'produce'), True)
        dependency['stages']['produce'].update(status='accepted', artifact=meta)
        helpers = []
        for index in range(61):
            text = (f'Input fixture {index}; không là nguồn độc lập. Mở docs/source.md để kiểm lời nguồn.\n'
                    'Chỉ CSV, không JSON; không tuyên bố mã hoặc test đã đạt.\n')
            if index == 60:
                text += 'Thông tin đệm fixture; không thêm ràng buộc hoặc quyết định.\n' * 340
                text += '\nKẾT LUẬN CUỐI: docs/source.md:2 giới hạn tối đa 500 dòng mỗi lần xuất.\n'
            helpers.append(await graph.artifacts.put(run, 'E2', 'knowledge', text,
                            {'purpose': 'knowledge', 'verification': 'unreviewed'}, True))
        rows = 500 if case == 'valid' else 5000
        text = ('# Kết luận nghiên cứu fixture\n'
                'Nguồn docs/source.md:1: “Chỉ xuất CSV; không JSON.” Giữ phạm vi CSV.\n'
                f'docs/source.md:2 và kết luận ở cuối input hỗ trợ dài quy định tối đa {rows} dòng/lần xuất.\n'
                'Các ghi chú hỗ trợ là fixture chưa phản biện, không có giá trị kiểm chứng độc lập. '
                'Nguồn là ghi chú nội bộ; không chứng nhận exporter hoặc test đạt. Không tự triển khai mã.\n')
        policy = work_policy.derive(run, node, 'produce', text)
        primary = await graph.artifacts.put(run, 'E2', 'produce', text,
            graph.checks.binding(run, node, 'produce') | {'policyHash': policy['hash'],
            'lookupArtifactIds': [m['artifactId'] for m in helpers]}, True)
        node['stages']['produce'].update(status='needs_checks', attempts=1, output=text, artifact=primary,
            policy=policy, rounds=[{'attempt': 1, 'producerRole': 'research', 'at': time.time()}])
        graph.save(run)
        started = time.monotonic()
        record = {'case': case, 'route': route, 'sourceManifest': frozen, 'parentBudget': {'maxSteps': 40, 'deadlineSeconds': 600},
            'scope': 'Synthetic producer/dependency/helper artifacts; native independent checker only, no root model or UI',
            'expected': 'pass' if case == 'valid' else 'revise', 'primary': primary, 'longInput': helpers[-1],
            'inputCount': 63, 'fixtureSources': {raw: (folder/raw).read_text(encoding='utf8') for raw in
                ('docs/source.md', 'src/export.py', 'tests/test_export.py')}}
        try:
            result = await graph.checks.tool(store.get(sid), {'action': 'start', 'runId': run['runId'], 'nodeId': 'E2',
                'stage': 'produce', 'artifactId': primary['artifactId'], 'checkIds': ['evidence'], 'invocationId': 'manifest-native'})
            check = result['checks'][0];child = check.get('childId')
            assigned = store.get(child)['config']['workBinding']['artifactIds'] if child else []
            all_read = bool(child) and all(graph.artifacts.covered(check['checkId'], graph.artifacts.get(run['runId'], a)[0], child)
                                          for a in assigned)
            before = len(store.children_of(sid))
            replay = await graph.checks.tool(store.get(sid), {'action': 'start', 'runId': run['runId'], 'nodeId': 'E2',
                'stage': 'produce', 'artifactId': primary['artifactId'], 'checkIds': ['evidence'], 'invocationId': 'manifest-native'})
            record.update(status=check['status'], check=check, allAssignedRead=all_read, assignedCount=len(assigned),
                replaySameCheck=replay['checks'][0]['checkId'] == check['checkId'], replayNewChildren=len(store.children_of(sid))-before)
            record['oracle'] = (check['status'] == record['expected'] and all_read and len(assigned) == 64
                                and record['replaySameCheck'] and record['replayNewChildren'] == 0
                                and bool(check.get('inputManifest')))
        except Exception as exc:
            record.update(status='error', error=str(exc), oracle=False)
        record.update(latencySeconds=round(time.monotonic()-started, 3), calls=client.calls,
                      visibleOutputs=visible(store, sid),
                      artifactMetadata=[json.loads(r[0]) for r in store.db.execute('select metadata from work_artifacts')])
        store.db.row_factory = __import__('sqlite3').Row
        record['artifactReads'] = [dict(r) for r in store.db.execute('select * from work_artifact_reads')]
        record['rootCompletionAttempts'] = store.db.execute("select count(*) from events where session_id=? and kind='completion_attempt'",(sid,)).fetchone()[0]
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in frozen.items()), 'source drift'
        records.append(record)
        (output/'results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps({k:record.get(k) for k in ('case','status','oracle','allAssignedRead','assignedCount','latencySeconds')},ensure_ascii=False),flush=True)
        store.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    asyncio.run(main(parser.parse_args()))
