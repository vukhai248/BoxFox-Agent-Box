"""Native main recovery with injected empty failures and Space Bunny recap.

Only the first graph creation and failure response are scripted. The recovery
completion uses the configured actual provider. This is not a full plan/DAG or
provider-failure incidence benchmark; no production sessions/resources are used.
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
    def __init__(self, url, failure):
        super().__init__(url)
        self.failure = failure
        self.calls = 0
        self.native_calls = 0

    async def complete(self, messages, tools, route, **kw):
        self.calls += 1
        if self.calls == 1:
            return {'choices': [{'finish_reason': 'tool_calls', 'message': {
                'content': '', 'tool_calls': [{'id': 'fixture-graph', 'type': 'function',
                    'function': {'name': 'work_graph', 'arguments': json.dumps({
                        'action': 'create', 'flow': 'plan', 'goal': 'Lập kế hoạch đã kiểm chứng cho fixture riêng.',
                        'nodes': []}, ensure_ascii=False)}}]}}]}
        if self.calls == 2:
            return {'choices': [{'finish_reason': self.failure, 'message': {'content': ''}}]}
        self.native_calls += 1
        return await super().complete(messages, tools, route, **kw)


async def main(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'B'
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT/'.tmp')
    out.mkdir(parents=True, exist_ok=True)
    state = await RouterClient(args.router).snapshot()
    route = next({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
        if m['id'] == 'space-bunny-free' and m.get('enabled'))
    paths = ['backend/src/agentbox/agent_core/runtime.py', 'backend/src/agentbox/agent_core/work_graph.py',
             'scripts/eval/work_main_recovery_eval.py']
    hashes = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    rows = []
    for failure, code in [('length','PROVIDER_OUTPUT_TRUNCATED'),
                          ('stream_incomplete','PROVIDER_STREAM_INTERRUPTED')]:
        folder = out/failure
        folder.mkdir()
        client = Client(args.router, failure)
        store = SessionStore(folder/'sessions.db')
        rt = HarnessRuntime(store, FixtureExecutor(folder), client)
        sid = rt.create({**route, 'skills': [], 'maxSteps': 10, 'deadlineSeconds': 240,
            'maxTokens': 16000})['id']
        started = time.monotonic()
        error = None
        try:
            await rt.start(sid, 'Đọc fixture và lập plan đã kiểm chứng. Không triển khai hoặc đổi tài nguyên sản phẩm.')
        except Exception as exc:
            error = str(exc)
        events = [{'seq': r['seq'], 'type': r['kind'], 'data': json.loads(r['payload'])}
            for r in store.db.execute("SELECT * FROM events WHERE session_id=? AND kind NOT IN "
                "('assistant_delta','thought_delta') ORDER BY seq", (sid,))]
        ends = [e['data'] for e in events if e['type'] == 'turn_end']
        finish = next((e['data'] for e in reversed(events) if e['type'] == 'finish'), {})
        run = rt.work_graph.active(sid) if getattr(rt, 'work_graph', None) else None
        row = {'injectedFailure': failure, 'expectedCode': code, 'sessionId': sid,
            'route': route, 'sourceHashesAtStart': hashes, 'scriptedCompletionCalls': 2,
            'nativeCompletionCalls': client.native_calls, 'error': error,
            'elapsedSeconds': round(time.monotonic()-started, 3),
            'mainEnd': ends[-1] if ends else None, 'finish': finish,
            'partialReason': rt.partial_turn(sid), 'runStatus': run['status'] if run else None,
            'events': events, 'childCount': len(store.children_of(sid))}
        row['oracle'] = bool(not error and client.native_calls and row['mainEnd']
            and row['mainEnd']['status'] == 'partial' and row['partialReason'] == code
            and finish.get('partial') and row['runStatus'] == 'drafting' and row['childCount'] == 0)
        rows.append(row)
        (out/'results.json').write_text(json.dumps({'schema': 'boxfox-w61-main-recovery-live/1',
            'branch': 'B', 'scope': __doc__, 'rows': rows}, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: row[k] for k in ('injectedFailure','elapsedSeconds','nativeCompletionCalls',
            'partialReason','runStatus','oracle')}, ensure_ascii=False), flush=True)
        store.db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--router', required=True)
    p.add_argument('--output', required=True)
    asyncio.run(main(p.parse_args()))
