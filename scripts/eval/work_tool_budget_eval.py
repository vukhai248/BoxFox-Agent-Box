"""Real Linux worker/host-transport timing in a disposable offline container.

No model calls or production workspace. Caller provisions the named container;
the SandboxExecutor syncs the B worker and uses its ordinary docker-exec path.
This does not certify desktop tools, a 900-second child or provider throughput.
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
sys.path.insert(0, str(ROOT / 'backend/src'))
from agentbox.agent_core.runtime import HarnessRuntime  # initializes package before executor
from agentbox.sandbox.executor import SandboxExecutor


def observe(container, sid):
    program = ("import json,pathlib; p=pathlib.Path('/tmp/boxfox-exec-" + sid + ".json'); "
               "d=json.loads(p.read_text()) if p.exists() else {}; "
               "print(json.dumps(d))")
    p = subprocess.run(['docker', 'exec', container, 'python3', '-c', program],
                       capture_output=True, text=True, timeout=10, check=True)
    return json.loads(p.stdout)


def alive(container, pid):
    if not pid:
        return False
    program = ("import json,pathlib; p=pathlib.Path('/proc/" + str(int(pid)) + "/stat'); "
               "print(json.dumps(p.exists() and p.read_text().split()[2] != 'Z'))")
    p = subprocess.run(['docker', 'exec', container, 'python3', '-c', program],
                       capture_output=True, text=True, timeout=10, check=True)
    return json.loads(p.stdout)


async def case(executor, container, sid, seconds, requested_timeout, cancel=False):
    command = ('python3 -c "import time; print(\'start\', flush=True); '
               f'time.sleep({seconds}); print(\'finished\', flush=True)"')
    started = time.monotonic()
    task = asyncio.create_task(executor.execute('terminal_exec',
        {'command': command, 'timeout': requested_timeout}, sid))
    marker = {}
    for _ in range(50):
        marker = await asyncio.to_thread(observe, container, sid)
        if marker or task.done():
            break
        await asyncio.sleep(0.1)
    if cancel and marker:
        await asyncio.sleep(2)
        task.cancel()
    try:
        result = await task
    except asyncio.CancelledError:
        result = {'cancelled': True}
    except Exception as exc:
        result = {'exception': type(exc).__name__, 'error': str(exc)}
    elapsed = round(time.monotonic() - started, 3)
    # The worker owns a process group, so verify its marker and original leader.
    # This observation is independent of the wording of the returned error.
    await asyncio.sleep(0.5)
    end_marker = await asyncio.to_thread(observe, container, sid)
    leader_alive = await asyncio.to_thread(alive, container, marker.get('pid'))
    if cancel:
        oracle = bool(marker) and result.get('cancelled') and elapsed < 20
    elif seconds < 120:
        oracle = result.get('exit_code') == 0 and 'finished' in result.get('content', '') and elapsed >= seconds
    else:
        oracle = result.get('is_error') and 'timed out' in result.get('error', '').lower() and 118 <= elapsed < 140
    return {'sessionId': sid, 'sleepSeconds': seconds, 'requestedToolSeconds': requested_timeout,
            'elapsedSeconds': elapsed, 'result': result, 'originalProcess': marker,
            'markerRemoved': not end_marker, 'leaderAlive': leader_alive,
            'oracle': bool(oracle and not end_marker and not leader_alive)}


async def main(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    assert args.container.startswith('boxfox-eval-')
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT / '.tmp')
    out.mkdir(parents=True, exist_ok=True)
    executor = SandboxExecutor(container=args.container)
    # Sync once before independent cases; no race writing the same worker file.
    executor._sync_worker()
    if not executor._worker_synced:
        raise RuntimeError('Could not sync B worker into disposable container')
    rows = await asyncio.gather(
        case(executor, args.container, 'w65-long95', 95, 100),
        case(executor, args.container, 'w65-cap125', 125, 130),
        case(executor, args.container, 'w65-cancel110', 110, 120, cancel=True))
    paths = ['backend/src/agentbox/sandbox/worker.py', 'backend/src/agentbox/sandbox/executor.py']
    evidence = {'schema': 'boxfox-w65-real-worker/1', 'branch': 'B', 'modelCalls': 0,
        'container': args.container, 'commit': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'sourceHashes': {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths},
        'rows': rows, 'scope': 'Actual worker and Docker transport; offline disposable Linux container, no desktop/model/child/watchdog benchmark.'}
    (out/'results.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
    for row in rows:
        print(json.dumps({k: row[k] for k in ('sessionId','elapsedSeconds','result','markerRemoved','leaderAlive','oracle')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--container', required=True)
    parser.add_argument('--output', required=True)
    asyncio.run(main(parser.parse_args()))
