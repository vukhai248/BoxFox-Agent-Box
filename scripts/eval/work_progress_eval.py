"""Native Space Bunny producer retries and same-child fresh-source continuation.

Repeated admissions/main source handoff are deliberately driven by this fixture,
not a native main decision. No production session, UI or whole SWE benchmark.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from work_check_eval import ROOT, HarnessRuntime, SessionStore
from work_feedback_eval import FeedbackFixtureExecutor
from work_knowledge_eval import visible
from agentbox.agent_core import work_graph as wg
from agentbox.agent_core.runtime import RouterClient


class Client(RouterClient):
    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        assert route['modelId'] == 'space-bunny-free'
        selected = [t for t in tools if t['function']['name'] in ('file_read', 'work_report', 'work_artifact_read')]
        started = time.monotonic()
        result = await super().complete(messages, selected, route, **kwargs)
        self.calls.append({'route': route, 'maxTokens': kwargs.get('max_tokens'),
            'finishReason': result.get('choices', [{}])[0].get('finish_reason'), 'usage': result.get('usage'),
            'requestId': result.get('id'), 'latencySeconds': round(time.monotonic()-started, 3)})
        return result


async def main(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p,h in frozen.items())
    output = Path(args.output).resolve(); assert output.is_relative_to(ROOT/'.tmp')
    output.mkdir(parents=True, exist_ok=False)
    state = await Client(args.router).snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
        if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    rows = []
    for repeat in range(1, args.repeats+1):
        folder=output/str(repeat); (folder/'docs').mkdir(parents=True)
        source='Phạm vi fixture: chỉ xuất CSV, giữ nguyên Unicode. Chưa chốt delimiter.\n'
        (folder/'docs/source.md').write_bytes(source.encode('utf8'))
        client=Client(args.router); store=SessionStore(folder/'sessions.db')
        rt=HarnessRuntime(store, FeedbackFixtureExecutor(folder), client)
        sid=rt.create({**route, 'skills':[], 'maxSteps':12, 'deadlineSeconds':300})['id']
        graph=wg.service(rt)
        run=graph.create(store.get(sid), {'goal':'Chỉ đọc ghi chú fixture và báo đúng dữ kiện CSV/Unicode, không làm mã hoặc chốt thay.',
            'flow':'research', 'nodes':[{'id':'R1','kind':'research','taskKind':'lookup','title':'Đọc ghi chú',
            'goal':'Mở docs/source.md ở lượt này; trả bản tóm tắt dữ kiện tối đa 120 từ bằng tiếng Việt, trích đúng nguồn. '
                   'Không khuyến nghị hoặc tự chọn thông tin nguồn chưa chốt; không hỏi thêm khi chỉ yêu cầu thuật lại ghi chú.'}]})
        node=run['nodes'][0]; started=time.monotonic()
        row={'repeat':repeat,'route':route,'sourceManifest':frozen,
             'scope':'Five native producer admissions; fixture drives retries and fresh-source handoff; no native main/UI'}
        try:
            for _ in range(4):
                await graph.run_stage(store.get(sid),run,node,'produce',10)
            history=graph.progress.records(run['runId']); row['before']=history
            row['stopStage']={k:node['stages']['produce'].get(k) for k in ('status','error','artifact','checkpoint')}
            count=len(client.calls)
            await graph.run_stage(store.get(sid),run,node,'produce',10)
            row['replayCalls']=len(client.calls)-count
            old_child=history[-1]['childId']
            # The fixture asks for technical evidence on behalf of the stopped
            # sub. Backend opens an actual changed source; no synthetic user answer.
            request=await graph.feedback.report(store.get(old_child), {'action':'needs_evidence',
                'checkpoint':'Đã giữ CSV/Unicode; cần mở dữ kiện mới của docs/source.md.',
                'reason':'Ghi chú nguồn có bản sửa mới', 'invocationId':'fixture-fresh-source'}, 'fixture-fresh-source')
            (folder/'docs/source.md').write_bytes((source+'Bổ sung đã chốt trong nguồn: delimiter là dấu chấm phẩy.\n').encode('utf8'))
            opened=await rt.dispatch(store.get(sid),'file_read',{'path':'docs/source.md'}, 'main-open-source')
            store.emit(sid,'tool_end',{'name':'file_read','args':{'path':'docs/source.md'},'result':opened})
            ready=graph.feedback.main_action(store.get(sid), {'action':'resume','runId':run['runId'],
                'requestId':request['requestId'],'revision':request['revision'],
                'evidenceRefs':['docs/source.md'],'invocationId':'fresh-source-admission'})
            node['stages']['produce'].update(status='needs_user',requestId=ready['requestId'])
            graph.save(run)
            await graph.run_stage(store.get(sid),run,node,'produce',10)
            final=graph.progress.records(run['runId'])[-1]
            stage=node['stages']['produce']; row['after']=final
            row['finalStage']={k:stage.get(k) for k in ('status','error','artifact','output')}
            row['oracle']=(len(history)==4 and history[-1]['blocked'] and history[-1]['streak']==3
                and row['stopStage']['status']=='failed' and row['stopStage']['artifact']['status']=='partial'
                and row['replayCalls']==0 and final['childId']==old_child and final['novelInput']
                and final['progressed'] and final['streak']==0 and stage['status']=='accepted'
                and store.child_usage_from_events(old_child)[0]>1
                and 'chấm phẩy' in stage.get('output','').lower())
        except Exception as exc:
            row.update(oracle=False,error=str(exc))
        row.update(latencySeconds=round(time.monotonic()-started,3),calls=client.calls,
            visibleOutputs=visible(store,sid), progressAdmissions=graph.progress.records(run['runId']),
            rootModelAttempts=store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='completion_attempt'",(sid,)).fetchone()[0])
        rows.append(row)
        (output/'results.json').write_bytes((json.dumps(rows,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
        print(json.dumps({k:row.get(k) for k in ('repeat','oracle','latencySeconds','replayCalls','error')},ensure_ascii=False),flush=True)
        await rt.stop(sid); store.db.close()
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in frozen.items()),'source drift'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--router',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--manifest',required=True)
    parser.add_argument('--repeats',type=int,default=2)
    asyncio.run(main(parser.parse_args()))
