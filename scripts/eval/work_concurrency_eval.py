"""Small native Space Bunny fanout pilot with fixed independent lookup nodes.

The evaluator supplies main; actual children/slots/scheduler/artifacts are used.
Local fixture executor substitutes Docker transport. Shared provider load can
affect elapsed times; this does not estimate production throughput or redesign
the DAG. Failures are retained, with no repeat-until-pass or provider changes.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'backend/src'))
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore
from work_check_eval import FixtureExecutor


class Client(RouterClient):
    async def complete(self, messages, tools, route, **kw):
        names = {'file_read','codebase_glob','codebase_grep','work_artifact_read'}
        return await super().complete(messages, [t for t in tools if t['function']['name'] in names], route, **kw)


async def main(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'B'
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT/'.tmp')
    out.mkdir(parents=True,exist_ok=True)
    client = Client(args.router)
    state = await client.snapshot()
    route = next({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId']=='opencode' and c.get('enabled') for m in c['models']
        if m['id']=='space-bunny-free' and m.get('enabled'))
    paths = ['backend/src/agentbox/agent_core/runtime.py','backend/src/agentbox/agent_core/work_graph.py',
             'backend/src/agentbox/agent_core/work_budget.py','scripts/eval/work_concurrency_eval.py']
    hashes = {p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    rows = []
    for fanout in (1,3):
        for repeat in range(1,args.repeats+1):
            folder = out/f'f{fanout}-r{repeat}'
            (folder/'facts').mkdir(parents=True)
            expected = {f'L{i}':f'NATIVE_LOOKUP_{i}_314159' for i in range(1,4)}
            for nid, value in expected.items():
                (folder/'facts'/f'{nid}.txt').write_text(f'Fixture synthetic.\nGiá trị: {value}\n',encoding='utf-8')
            store = SessionStore(folder/'sessions.db')
            rt = HarnessRuntime(store,FixtureExecutor(folder),client)
            parent = rt.create({**route,'skills':[],'maxSteps':40,'deadlineSeconds':120,
                'fanoutPerParent':fanout})
            assert rt.fanout_limit(parent['config']) == fanout, 'Environment fanout override invalidates this pilot'
            store.save(parent['id'],parent['messages'],'running')
            rt.active_turn[parent['id']] = 1
            rt.active_step[parent['id']] = 1
            run = await rt.work_tool(parent,'work_graph',{'action':'create','flow':'research',
                'goal':'Đọc ba giá trị synthetic độc lập để đo fanout; không nghiên cứu ngoài hoặc triển khai.',
                'nodes':[{'id':nid,'kind':'explore','taskKind':'lookup','title':f'Tra cứu {nid}',
                    'goal':f'Đọc facts/{nid}.txt. Trả giá trị chính xác với path; tối đa 3 câu, không khảo sát ngoài.',
                    'files':[f'facts/{nid}.txt'],'acceptance':['Giá trị đúng nội dung file và có nguồn đã đọc.']}
                    for nid in expected]})
            started = time.monotonic()
            error = None
            try:
                await rt.work_tool(store.get(parent['id']),'work_run',{'runId':run['runId'],'phase':'discover'})
            except Exception as exc:
                error = str(exc)
            children = store.children_of(parent['id'])
            points = []
            for c in children:
                points.append((c['started'],1))
                if c['finished'] is not None:
                    points.append((c['finished'],-1))
            active = peak = 0
            for _, delta in sorted(points):
                active += delta
                peak = max(peak,active)
            current = rt.work_graph.get(run['runId'])
            artifacts = []
            for n in current['nodes']:
                s = n['stages']['produce']
                meta = s.get('artifact')
                doc = store.db.execute('SELECT content FROM work_artifacts WHERE id=?',
                    (meta['artifactId'],)).fetchone() if meta else None
                artifacts.append({'nodeId':n['id'],'stageStatus':s['status'],'artifact':meta,
                    'valuePresent':bool(doc and expected[n['id']] in doc['content'])})
            trace = [{'seq':r['seq'],'sessionId':r['session_id'],'type':r['kind'],'data':json.loads(r['payload'])}
                for r in store.db.execute("SELECT * FROM events WHERE kind NOT IN "
                    "('assistant_delta','thought_delta') ORDER BY seq")]
            row = {'fanout':fanout,'repeat':repeat,'sessionId':parent['id'],'runId':run['runId'],
                'elapsedSeconds':round(time.monotonic()-started,3),'peakChildren':peak,'error':error,
                'children':children,'artifacts':artifacts,'events':trace,
                'oracle':bool(not error and 0<peak<=fanout and len(children)==3
                    and all(c['status']=='completed' for c in children)
                    and all(a['stageStatus']=='accepted' and a['valuePresent'] for a in artifacts))}
            rows.append(row)
            (out/'results.json').write_text(json.dumps({'schema':'boxfox-w65-concurrency-pilot/1',
                'branch':'B','route':route,'sourceHashesAtStart':hashes,'scope':__doc__,
                'sharedProviderLoad':'Other isolated main integration job can overlap; do not infer speedup.',
                'rows':rows},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row[k] for k in ('fanout','repeat','elapsedSeconds','peakChildren','oracle')},ensure_ascii=False),flush=True)
            store.save(parent['id'],store.get(parent['id'])['messages'],'completed')
            store.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--router',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--repeats',type=int,default=2)
    asyncio.run(main(p.parse_args()))
