"""Live reviewer feasibility/uncertainty probes with a real official source.

Assignment uses Python's official documentation. Runtime web tools fetch/cache
real sources (not FixtureExecutor); all opened URLs and access failures are retained.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from work_check_eval import ROOT, FixtureExecutor
from agentbox.agent_core import work_graph as wg, work_policy, work_checks
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore

URL = 'https://docs.python.org/3/library/csv.html'


class Client(RouterClient):
    async def complete(self, messages, tools, route, **kwargs):
        allowed = {'work_artifact_read', 'file_read', 'web_fetch', 'read_source'}
        return await super().complete(messages, [t for t in tools if t['function']['name'] in allowed], route, **kwargs)


CASES = {
    'false_impossibility': ('Python csv không thể xử lý tiếng Việt/Unicode nên bắt buộc đổi sang JSON. '
        'Không cần mở nguồn vì đây là giới hạn cố hữu. Nguồn được trích: ' + URL, 'revise'),
    'honest_limit': ('csv.reader/writer dùng chuỗi; có thể giữ tiếng Việt bằng mở file encoding="utf-8", newline="". '
        'CSV không tự lưu metadata kiểu dữ liệu. Chưa kiểm tương thích với một HIS cụ thể và không tuyên bố đã test nó. '
        'Giới hạn này không đổi kết luận về khả năng xử lý Unicode. Nguồn: ' + URL, 'pass'),
}


async def run(args):
    assert subprocess.check_output(['git','branch','--show-current'], cwd=ROOT,text=True).strip() == 'B'
    os.environ['BOXFOX_WORK_CHECK_OUTPUT_TOKENS'] = '16000'
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT/'.tmp')
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.router)
    state = await client.snapshot()
    route = next({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                 if c['providerId'] == 'opencode' and c.get('enabled')
                 for m in c['models'] if m['id'] == 'space-bunny-free' and m.get('enabled'))
    rows = []
    for case,(text,expected) in CASES.items():
        for repeat in range(1,args.repeats+1):
            folder=out/f'{case}-{repeat}'
            folder.mkdir()
            store=SessionStore(folder/'sessions.db')
            rt=HarnessRuntime(store,FixtureExecutor(folder),client)
            session=rt.create({**route,'skills':[],'maxSteps':40,'deadlineSeconds':600})
            graph=wg.service(rt)
            run=graph.create(session,{'goal':'Chỉ nghiên cứu csv chuẩn của Python có giữ được tiếng Việt không. '
                'Không đánh giá HIS, không triển khai app. Đọc nguồn chính thức để xác nhận hoặc bác kết luận.',
                'flow':'research','nodes':[{'id':'R1','kind':'research','title':'CSV Unicode feasibility',
                    'goal':'Kiểm khả năng Unicode của Python csv từ nguồn chính thức '+URL,
                    'acceptance':['Kết luận Unicode đúng nguồn chính thức; không nói không khả thi khi có thể làm',
                                  'Giới hạn HIS chưa kiểm là giới hạn trung thực, không yêu cầu thêm triển khai ngoài phạm vi']}]})
            node=run['nodes'][0]
            policy=work_policy.derive(run,node,'produce',text)
            meta=await graph.artifacts.put(run,'R1','produce',text,graph.checks.binding(run,node,'produce')|{'policyHash':policy['hash']},True)
            node['stages']['produce'].update(status='needs_checks',attempts=1,artifact=meta,policy=policy,output=text,
                rounds=[{'attempt':1,'producerRole':'research','at':time.time()}])
            graph.save(run)
            start=time.monotonic()
            try:
                result=await graph.checks.tool(session,{'action':'start','runId':run['runId'],'nodeId':'R1','stage':'produce',
                    'artifactId':meta['artifactId'],'checkIds':['evidence'],'invocationId':uuid.uuid4().hex})
                doc=result['checks'][0]
                row={'case':case,'repeat':repeat,'expected':expected,'status':doc['status'], 'check':doc,
                    'answer':graph.child_answer(doc.get('childId')),'reads':work_checks.good_reads(graph,doc.get('childId')),
                    'oracle':doc['status']==expected,'latencySeconds':round(time.monotonic()-start,3)}
            except Exception as exc:
                row={'case':case,'repeat':repeat,'status':'error','error':str(exc),'oracle':False}
            rows.append(row)
            (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row.get(k) for k in ('case','repeat','status','oracle','latencySeconds')},ensure_ascii=False),flush=True)
            store.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--router',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--repeats',type=int,default=2)
    asyncio.run(run(p.parse_args()))
