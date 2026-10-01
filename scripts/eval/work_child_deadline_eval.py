"""Space Bunny + real worker: observe finite 900s child and 1200s watchdog.

Disposable offline worker/container and SQLite. Fixed <=120s commands accumulate
active time. This is native child/transport, not a full main/DAG or CUA benchmark.
Failures are retained; a provider error before 900s is not deadline evidence.
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
from agentbox.agent_core import work_graph
from agentbox.agent_core.peer_watchdog import PeerWatchdog
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.executor import SandboxExecutor
from work_tool_budget_eval import observe, alive


def execution_trace(store, sid):
    # SessionStore.execution_events is a runtime summary, not the tool-result
    # ledger: it intentionally omits tool_end/finish. Measure actual completions
    # from the persisted trace rather than treating that omission as zero work.
    return [{'seq': r['seq'], 'type': r['kind'], 'data': json.loads(r['payload']), 'created': r['created']}
            for r in store.db.execute("SELECT * FROM events WHERE session_id=? AND kind NOT IN "
                "('assistant_delta','thought_delta') ORDER BY seq", (sid,))]


class Client(RouterClient):
    async def complete(self, messages, tools, route, **kw):
        return await super().complete(messages,
            [t for t in tools if t['function']['name'] == 'terminal_exec'], route, **kw)


async def main(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'B'
    assert args.container.startswith('boxfox-eval-')
    out=Path(args.output).resolve();assert out.is_relative_to(ROOT/'.tmp');out.mkdir(parents=True,exist_ok=True)
    client=Client(args.router);state=await client.snapshot()
    route=next({'connectionId':c['id'],'modelId':m['id']} for c in state['connections']
        if c['providerId']=='opencode' and c.get('enabled') for m in c['models']
        if m['id']=='space-bunny-free' and m.get('enabled'))
    store=SessionStore(out/'sessions.db');executor=SandboxExecutor(container=args.container)
    rt=HarnessRuntime(store,executor,client)
    parent=rt.create({**route,'skills':[],'maxSteps':60,'deadlineSeconds':900,'tools':['terminal_exec','delegate_task']})
    # Parent is the evaluator awaiting delegate. It never calls a second model.
    store.save(parent['id'],parent['messages'],'running');parent=store.get(parent['id'])
    rt.active_turn[parent['id']]=1;rt.active_step[parent['id']]=1
    commands=[f'python3 -c "import time; time.sleep(100); print(\'probe-{i}-completed\')"' for i in range(1,10)]
    graph=work_graph.service(rt)
    run=graph.create(parent,{'goal':'Đo deadline bằng lệnh chờ fixture riêng; chỉ thực thi các lệnh kiểm thử cố định, không sửa sản phẩm.',
        'flow':'fix','nodes':[{'id':'T1','kind':'testing','title':'Finite child active deadline',
            'goal':'Chạy lần lượt các lệnh kiểm thử chờ cố định để ghi nhận deadline và hủy tiến trình.',
            'tests':commands,'acceptance':['Báo đúng lệnh đã chạy và lệnh còn thiếu, không tự khai đủ nếu deadline cắt.']}]})
    wd=PeerWatchdog(store,rt);wd.sweep();wd.start()
    goal=('Đây là phép đo deadline, chỉ có container fixture riêng. Chạy ĐÚNG các lệnh sau theo thứ tự, '
        'mỗi lệnh dùng terminal_exec timeout=110. Có thể batch tool calls; harness thực hiện tuần tự. '
        'Không sửa nguồn, không chạy chúng ở background hoặc gộp chúng thành lệnh song song. '
        'Nếu ngân sách cắt, báo phần đã làm thật và phần còn thiếu; không giả vờ hoàn thành.\n'
        + '\n'.join(commands))
    paths=['backend/src/agentbox/agent_core/runtime.py','backend/src/agentbox/agent_core/peer_watchdog.py',
        'backend/src/agentbox/sandbox/executor.py','backend/src/agentbox/sandbox/worker.py']
    record={'schema':'boxfox-w65-real-child-deadline/1','branch':'B','route':route,'parentId':parent['id'],
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'sourceHashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'commands':commands,'watchdogWallSeconds':wd.wall_max,'watchdogTickSeconds':wd.tick,
        'scope':'Actual delegated child, model and Docker worker; evaluator supplies live parent, not full main/DAG.'}
    task=asyncio.create_task(rt.delegate(parent,{'role':'testing','goal':goal},
        work={'runId':run['runId'],'nodeId':'T1','stage':'execute','purpose':'produce','taskKind':'implementation'}))
    started=time.monotonic();pids=set();samples=[]
    try:
        while not task.done():
            rows=store.children_of(parent['id']);child=rows[-1]['session_id'] if rows else None
            if child:
                marker=await asyncio.to_thread(observe,args.container,child)
                if marker.get('pid'):pids.add(marker['pid'])
                events=execution_trace(store,child)
                samples.append({'elapsed':round(time.monotonic()-started,2),'childId':child,
                    'registryStatus':rows[-1]['status'],'sessionStatus':store.get(child)['status'],
                    'lastEvent':events[-1]['type'] if events else None,'liveShell':bool(marker)})
            (out/'progress.json').write_text(json.dumps(record|{'samples':samples},indent=2),encoding='utf-8')
            await asyncio.wait({task},timeout=15)
        result=await task;child=result['sessionId']
        events=execution_trace(store,child)
        finished=[e['data'] for e in events if e['type']=='tool_end' and e['data'].get('name')=='terminal_exec']
        marker=await asyncio.to_thread(observe,args.container,child)
        live_pids=[p for p in pids if await asyncio.to_thread(alive,args.container,p)]
        elapsed=round(time.monotonic()-started,3)
        record.update(result=result,elapsedSeconds=elapsed,samples=samples,events=events,
            completedCommands=sum(not e.get('result',{}).get('is_error') for e in finished),
            markerRemoved=not marker,observedLeadersAlive=live_pids,
            oracle=bool(result.get('reason')=='DEADLINE_EXCEEDED' and 895<=elapsed<960
                and not marker and not live_pids))
        (out/'results.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:record[k] for k in ('elapsedSeconds','completedCommands','markerRemoved','observedLeadersAlive','oracle')}),flush=True)
    finally:
        await wd.stop()
        if not task.done():task.cancel();await asyncio.gather(task,return_exceptions=True)
        store.save(parent['id'],store.get(parent['id'])['messages'],'completed')
        store.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--router',required=True);p.add_argument('--container',required=True)
    p.add_argument('--output',required=True);asyncio.run(main(p.parse_args()))
