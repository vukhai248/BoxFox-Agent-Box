"""Real RouterClient -> disposable production RouterEngine -> Space Bunny."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from work_check_eval import ROOT
from agentbox.agent_core.runtime import RouterClient
from agentbox.agent_core import output_policy


async def run(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip() == 'B'
    folder = Path(args.output).resolve()
    assert folder.is_relative_to(ROOT / '.tmp')
    folder.mkdir(parents=True, exist_ok=True)
    client = RouterClient(args.router)
    state = await client.snapshot()
    route = next({'connectionId':c['id'],'modelId':m['id']} for c in state['connections']
        if c['providerId']=='opencode' and c.get('enabled') for m in c['models']
        if m['id']=='space-bunny-free' and m.get('enabled'))
    text = (ROOT/'scripts/eval/work_request_budget_eval.mjs').read_text(encoding='utf-8')
    prompt = re.search(r'const prompt = `(.*?)`;', text, re.S).group(1)
    sources = ['backend/src/agentbox/agent_core/runtime.py','router/src/engine.mjs','router/src/request-budget.mjs']
    record = {'route':route,'maxTokens':16000,'scope':'real production client/server/engine, disposable DB, no tool/child/CUA test',
        'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'sourceHashes':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}}
    start = time.monotonic()
    try:
        result = await client.complete([{'role':'user','content':prompt}], [], route, max_tokens=16000)
        reason = output_policy.completion_reason(result)
        answer = result['choices'][0]['message'].get('content') or ''
        (folder/'answer.md').write_text(answer,encoding='utf-8')
        record.update(reason=reason,finishReason=result['choices'][0].get('finish_reason'),usage=result.get('usage'),
                      streamError=result.get('stream_error'),answerChars=len(answer),
                      transportFinished=reason in ('complete','output_limit'),semanticPass=False)
        (folder/'response.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    except Exception as exc:
        record.update(reason='exception',error=type(exc).__name__+': '+str(exc),transportFinished=False)
    record['seconds'] = round(time.monotonic()-start,3)
    (folder/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:record.get(k) for k in ('reason','finishReason','seconds','answerChars','transportFinished')}))


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--router',required=True);p.add_argument('--output',required=True)
    asyncio.run(run(p.parse_args()))
