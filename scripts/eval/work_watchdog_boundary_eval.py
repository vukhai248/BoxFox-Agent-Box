"""Observe real 1200s watchdog wall time with an injected hung child task.

No LLM calls: a deliberately hung task bypasses the usual 900s turn deadline so
the watchdog safety boundary can be reached. Actual registry, runtime slot/cancel
methods and Docker worker are used. This is not a normal delegated model run.
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
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.peer_watchdog import PeerWatchdog
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.executor import SandboxExecutor
from work_tool_budget_eval import observe, alive


class NoModel:
    async def complete(self, *a, **kw):
        raise AssertionError('This watchdog fault test must not call a model')


async def main(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'B'
    assert args.container.startswith('boxfox-eval-')
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT/'.tmp')
    out.mkdir(parents=True, exist_ok=True)
    store = SessionStore(out/'sessions.db')
    executor = SandboxExecutor(container=args.container)
    executor._sync_worker()
    if not executor._worker_synced:
        raise RuntimeError('Fixture worker sync failed')
    rt = HarnessRuntime(store, executor, NoModel())
    parent = rt.create({'skills': [], 'maxSteps': 60, 'deadlineSeconds': 900})
    store.save(parent['id'], parent['messages'], 'running')
    watchdog = PeerWatchdog(store, rt)
    watchdog.sweep()  # initial restart scan precedes the fresh child
    await rt.acquire_child_slot(parent['id'])
    child = rt.create({'skills': []}, parent_id=parent['id'], role='testing')
    sid = child['id']
    rt.track_child_slot(sid, parent['id'])
    store.save(sid, child['messages'], 'running')
    registry = store.child_start(sid, parent['id'], 1, 1, 'testing', 'Injected hang for watchdog wall measurement')
    completed = []

    async def hung():
        try:
            for i in range(12):
                command = f'python3 -c "import time; time.sleep(110); print(\'watchdog-probe-{i}\')"'
                result = await executor.execute('terminal_exec', {'command': command, 'timeout': 120}, sid)
                completed.append({'command': command, 'result': result, 'elapsed': time.time()-registry['started']})
                if result.get('is_error'):
                    return  # keep fixture failure; do not manufacture a timeout
        finally:
            await executor.cleanup(sid)
            rt.release_child_slot(parent['id'], sid)

    task = asyncio.create_task(hung())
    rt.tasks[sid] = task
    watchdog.start()
    paths = ['backend/src/agentbox/agent_core/peer_watchdog.py', 'backend/src/agentbox/agent_core/runtime.py',
             'backend/src/agentbox/sandbox/executor.py', 'backend/src/agentbox/sandbox/worker.py']
    record = {'schema': 'boxfox-w65-watchdog-boundary/1', 'branch': 'B', 'modelCalls': 0,
        'injection': 'Manual runtime task bypasses normal child deadline; no model/delegate loop.',
        'parentId': parent['id'], 'childId': sid, 'wallSeconds': watchdog.wall_max,
        'tickSeconds': watchdog.tick, 'sourceHashesAtStart': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'commitAtStart': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()}
    samples = []
    pids = set()
    started = time.monotonic()
    try:
        while not task.done() and time.monotonic()-started < 1260:
            marker = await asyncio.to_thread(observe, args.container, sid)
            if marker.get('pid'):
                pids.add(marker['pid'])
            samples.append({'elapsed': round(time.monotonic()-started, 2),
                'registry': store.child(sid)['status'], 'completedCommands': len(completed), 'liveShell': bool(marker)})
            (out/'progress.json').write_text(json.dumps(record|{'samples': samples},indent=2),encoding='utf-8')
            await asyncio.wait({task}, timeout=15)
        elapsed = round(time.monotonic()-started, 3)
        finished = store.child(sid)
        if not task.done():
            task.cancel()
        outcomes = await asyncio.gather(task, return_exceptions=True)
        marker = await asyncio.to_thread(observe, args.container, sid)
        live = [p for p in pids if await asyncio.to_thread(alive, args.container, p)]
        events = [json.loads(r['payload']) for r in store.db.execute(
            "SELECT payload FROM events WHERE session_id=? AND kind='child'", (parent['id'],))]
        record.update(elapsedSeconds=elapsed, registry=finished, samples=samples, completedCommands=completed,
            taskCancelled=task.cancelled(), originalMarkerRemoved=not marker, observedLeadersAlive=live,
            parentSlotsRunning=rt.parent_running.get(parent['id'], 0), childSlotHeld=sid in rt.child_slot_holders,
            closeEvents=events, taskErrors=[type(e).__name__ for e in outcomes if isinstance(e, BaseException)])
        record['oracle'] = bool(finished['status']=='failed' and finished['reason']=='WATCHDOG_TIMEOUT'
            and 1195 <= elapsed < 1240 and task.cancelled() and not marker and not live
            and rt.parent_running.get(parent['id'],0)==0 and sid not in rt.child_slot_holders and len(events)==1)
        (out/'results.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k: record[k] for k in ('elapsedSeconds','taskCancelled','originalMarkerRemoved',
            'parentSlotsRunning','childSlotHeld','oracle')}),flush=True)
    finally:
        await watchdog.stop()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        store.save(parent['id'],store.get(parent['id'])['messages'],'completed')
        store.db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--container',required=True)
    p.add_argument('--output',required=True)
    asyncio.run(main(p.parse_args()))
