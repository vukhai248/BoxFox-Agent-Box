"""Native Space Bunny W7 probe; synthetic owner answers, disposable workspace."""
import argparse
import asyncio
import fnmatch
import hashlib
import json
import subprocess
import time
from pathlib import Path

from work_check_eval import ROOT, FixtureExecutor
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.agent_core import work_graph as wg
from agentbox.memory.session_store import SessionStore


class FeedbackFixtureExecutor(FixtureExecutor):
    """Advertise files that actually exist in this disposable probe workspace."""
    async def execute(self, name, args, sid, **identity):
        if name in ('codebase_glob', 'codebase_grep'):
            files = sorted(str(p.relative_to(self.folder)).replace('\\', '/')
                           for p in self.folder.rglob('*') if p.is_file()
                           and str(p.relative_to(self.folder)).replace('\\', '/').startswith(('docs/', 'src/', 'tests/'))
                           and p.suffix in ('.py', '.md', '.txt', '.json'))
            if name == 'codebase_glob':
                matches = [p for p in files if fnmatch.fnmatch(p, args.get('pattern', '**/*'))]
            else:
                matches = [f'{p}:{i}: {line}' for p in files
                           if not args.get('path') or p.startswith(args['path'].rstrip('/') + '/') or p == args['path']
                           for i,line in enumerate(self.path(p).read_text(encoding='utf-8').splitlines(),1)
                           if args.get('query', '') in line]
            return {'content': '\n'.join(matches), 'fixture': True}
        return await super().execute(name, args, sid, **identity)


async def run(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='B'
    out=Path(args.output).resolve();assert out.is_relative_to(ROOT/'.tmp');out.mkdir(parents=True,exist_ok=True)
    client=RouterClient(args.router);state=await client.snapshot()
    route=next({'connectionId':c['id'],'modelId':m['id']} for c in state['connections']
               if c['providerId']=='opencode' and c.get('enabled') for m in c['models']
               if m['id']=='space-bunny-free' and m.get('enabled'))
    sources=list((ROOT/'backend/src/agentbox/agent_core').glob('work_*.py'))+[ROOT/'backend/src/agentbox/agent_core/runtime.py',ROOT/'backend/src/agentbox/agent_core/roles.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    rows=[]
    for repeat in range(1,args.repeats+1):
        folder=out/f'rare-owner-decision-{repeat}';folder.mkdir()
        (folder/'docs').mkdir();(folder/'docs/source.md').write_text('Dữ kiện đã xác minh: exporter dùng CSV, giữ Unicode. Người dùng mục tiêu chưa chốt. Không nghiên cứu lại định dạng.\n',encoding='utf8')
        store=SessionStore(folder/'sessions.db');rt=HarnessRuntime(store,FeedbackFixtureExecutor(folder),client)
        sid=rt.create({**route,'skills':[],'maxSteps':16,'deadlineSeconds':300})['id']
        graph=wg.service(rt);run=graph.create(store.get(sid),{'flow':'research','goal':'Nghiên cứu mô tả exporter CSV sau khi chốt người dùng; chỉ báo cáo, không triển khai.',
          'nodes':[{'id':'R1','kind':'research','taskKind':'lookup','title':'Mô tả exporter','goal':
           'Đây là ca kiểm thử lớp bảo vệ hiếm. Đọc docs/source.md và giữ dữ kiện đã biết. Thiếu quyết định ai dùng exporter, không tự đoán: '
           'gọi work_report action=needs_user lưu checkpoint đã đọc và hỏi một câu có lựa chọn Bác sĩ/Điều dưỡng. '
           'Sau khi main đưa câu trả lời, tiếp tục từ checkpoint, báo đúng lựa chọn và dữ kiện có sẵn dưới 200 từ; không hỏi lại, không khảo sát lại định dạng.',
           'acceptance':['Đọc nguồn và báo đúng người dùng đã trả lời'], 'dependsOn':[]}]})
        started=time.monotonic();row={'repeat':repeat,'route':route,'sourceHashes':hashes,'scope':'native child; synthetic owner answer; no CUA/full main'}
        try:
            first=await graph.run(store.get(sid),{'phase':'discover'})
            requests=graph.feedback.records(run['runId']);row['first']=first
            row['activeSlotsAfterYield']=rt.store.live_children(sid)
            if len(requests)!=1 or requests[0]['kind']!='needs_user':
                raise ValueError('Expected one durable needs_user checkpoint')
            req=requests[0];old_child=req['childId'];card=graph.feedback.open_interview(store.get(sid),{'workRequestId':req['requestId'],'revision':req['revision']},'synthetic-interview')
            # Real backend validation/persistence, simulated human action.
            option=next(q['id'] for q in card['questions'][0]['options'] if 'Điều' in q['label'])
            response=rt.resolve_decision(sid,card['decisionId'],'submit',answers=[{'questionId':card['questions'][0]['id'],'optionId':option}])
            row['answer']=response
            # Service restart; waiting time does not run a model or use an active slot.
            rt.work_graph=wg.WorkGraph(rt);graph=rt.work_graph
            second=await graph.run(store.get(sid),{'phase':'discover'});row['second']=second
            final=graph.get(run['runId'])['nodes'][0]['stages']['produce'];output=final.get('output','')
            row.update(childId=old_child,output=output,status=final['status'],
              oracle=final['rounds'][-1]['producerId']==old_child and 'Điều dưỡng'.lower() in output.lower()
                     and final['status']=='accepted' and len(store.children_of(sid))==1,
              telemetry=store.child_usage_from_events(old_child))
            row.update(questionCount=len(card['questions']),
                       finalRequestCount=len(graph.feedback.records(run['runId'])),
                       wordCount=len(output.split()),
                       lengthOracle=bool(output.strip()) and len(output.split())<=200,
                       activeSlotsAfterCompletion=rt.store.live_children(sid))
        except Exception as exc:
            row.update(status='error',error=str(exc),oracle=False)
        row['latencySeconds']=round(time.monotonic()-started,3);rows.append(row)
        (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:row.get(k) for k in ('repeat','status','oracle','latencySeconds','error')},ensure_ascii=False),flush=True)
        store.db.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--router',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--repeats',type=int,default=2);asyncio.run(run(parser.parse_args()))
