"""W6.5 bounded budget experiment, isolated runtime constants only; no defaults changed.

Six groups x two repeats/profile. Sequential random-linked source chains expose
step exhaustion; full artifact read gates still apply. Not a production workload
distribution or semantic SWE benchmark. Same Space Bunny/output 16k throughout.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from work_check_eval import ROOT, FixtureExecutor
from agentbox.agent_core import runtime as runtime_module, work_graph as wg, work_policy, work_checks, work_budget
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore

PROFILES = {'baseline': (40, 14), 'medium': (60, 24), 'high': (60, 40), 'native': (60, 24)}
CASES = ('short_lookup', 'long_research', 'long_plan_design', 'single_large_review', 'multi_artifact_review', 'long_testing')


class Client(RouterClient):
    def __init__(self, url):
        super().__init__(url)
        self.calls = []
    async def complete(self, messages, tools, route, **kwargs):
        allowed = {'file_read', 'work_artifact_read', 'terminal_exec'}
        start = time.monotonic()
        row = {'maxTokens': kwargs.get('max_tokens'), 'sessionId': route.get('sessionId')}
        try:
            result = await super().complete(messages, [t for t in tools if t['function']['name'] in allowed], route, **kwargs)
            row.update(finishReason=result['choices'][0].get('finish_reason'), usage=result.get('usage'))
            return result
        except BaseException as exc:
            row['error'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            row['seconds'] = round(time.monotonic() - start, 3)
            self.calls.append(row)


def fixture(folder):
    for name in ('docs', 'src', 'tests'):
        (folder/name).mkdir()
    (folder/'docs/source.md').write_text('Chỉ xuất CSV, giữ tiếng Việt; đây là dữ liệu synthetic, không JSON.\n', encoding='utf-8')
    (folder/'src/export.py').write_text("import csv, io\ndef export(value):\n    s=io.StringIO(newline='')\n    csv.writer(s).writerow([value])\n    return s.getvalue()\n", encoding='utf-8')
    (folder/'tests/test_export.py').write_text("import csv, io, time\nfrom src.export import export\ndef test_unicode():\n    time.sleep(5)\n    assert next(csv.reader(io.StringIO(export('Hồ sơ'))))==['Hồ sơ']\n", encoding='utf-8')
    (folder/'.gitignore').write_text('sessions.db*\n.plans/\n.pytest_cache/\n**/__pycache__/\n',encoding='utf-8')
    subprocess.run(['git','init','-q'],cwd=folder,check=True)
    subprocess.run(['git','add','.'],cwd=folder,check=True)
    subprocess.run(['git','-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','fixture'],cwd=folder,check=True)


async def run(args):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='B'
    os.environ['BOXFOX_WORK_CHECK_OUTPUT_TOKENS']='16000'
    out=Path(args.output).resolve()
    assert out.is_relative_to(ROOT/'.tmp')
    out.mkdir(parents=True,exist_ok=True)
    client=Client(args.router)
    state=await client.snapshot()
    route=next({'connectionId':c['id'],'modelId':m['id']} for c in state['connections']
        if c['providerId']=='opencode' and c.get('enabled') for m in c['models']
        if m['id']=='space-bunny-free' and m.get('enabled'))
    producer_steps,review_steps=PROFILES[args.profile]
    source_paths = list((ROOT/'backend/src/agentbox/agent_core').glob('work_*.py')) + [
        ROOT/'backend/src/agentbox/agent_core/runtime.py', ROOT/'backend/src/agentbox/agent_core/output_policy.py',
        ROOT/'backend/src/agentbox/memory/session_store.py', Path(__file__).resolve()]
    source_hashes = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    source_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    if args.profile != 'native':
        runtime_module.CHILD_MAX_STEPS=producer_steps
        wg.REVIEW_MAX_STEPS=review_steps
        work_budget.PRODUCER_STEPS=producer_steps
        work_budget.SHORT_REVIEW_STEPS=review_steps
        work_budget.LONG_REVIEW_STEPS=review_steps
    rows=[]
    for case in args.cases:
        for repeat in range(1,args.repeats+1):
            folder=out/f'{case}-{repeat}';folder.mkdir()
            fixture(folder)
            store=SessionStore(folder/'sessions.db')
            rt=HarnessRuntime(store,FixtureExecutor(folder),client)
            session=rt.create({**route,'skills':[],'maxSteps':60,'deadlineSeconds':1200})
            graph=wg.service(rt)
            started=time.monotonic();call_start=len(client.calls)
            row={'case':case,'repeat':repeat,'profile':args.profile,'route':route,'reviewSteps':review_steps,
                'producerSteps':producer_steps,'ownerSteps':60,'ownerDeadline':1200,'childDeadline':900,
                'outputProfile':16000,'scope':'native production profiles' if args.profile == 'native' else 'isolated constant override',
                'commit':source_commit,'sourceHashes':source_hashes,
                'distinctArtifacts': args.distinct_artifacts,
                'multiReviewShape': 'whole' if case == 'multi_artifact_review' else None}
            try:
                if case in ('short_lookup','long_research','long_plan_design'):
                    count=1 if case=='short_lookup' else 42
                    paths=['docs/'+uuid.uuid4().hex+'.md' for _ in range(count)]
                    for i,path in enumerate(paths):
                        (folder/path).write_text(f'FACT {i+1}: owner requirement {i+1} is synthetic.\n'+
                            ('NEXT '+paths[i+1] if i+1<count else 'END: all requirements read.\n'),encoding='utf-8')
                    role='explore' if case=='short_lookup' else 'research' if case=='long_research' else 'plan' if repeat==1 else 'design'
                    node={'id':'N1','kind':role,'title':case,'goal':
                        f'Đọc chuỗi {count} nguồn synthetic bắt đầu tại {paths[0]}, theo NEXT đến END. '
                        'Đừng đoán tên file hoặc bỏ bước. Trả báo cáo dưới 500 từ; kết luận dựa đúng dữ liệu đã đọc, '
                        'liệt kê số nguồn và giới hạn; không bịa đã đọc hết. Với plan/design có milestone, dữ liệu CSV, '
                        'hợp đồng, ca lỗi, kiểm chứng và planned paths; không sửa code hoặc hỏi user.',
                        'acceptance':[f'Đọc đủ {count} nguồn thực sự; không bịa nguồn'], 'tests':['Đề xuất, chưa chạy']}
                    run=graph.create(session,{'goal':'Chỉ tạo báo cáo từ các nguồn synthetic, không triển khai','flow':'research' if role!='plan' else 'plan','nodes':[node]})
                    result=await graph.run(session,{'runId':run['runId'],'phase':'discover'})
                    run=graph.get(run['runId'])
                    child=run['nodes'][0]['stages']['produce']['rounds'][-1].get('producerId')
                    reads={x['args'].get('path') for x in work_checks.good_reads(graph,child) if x['name']=='file_read'}
                    row.update(status=result['outputs'][0]['status'], readSources=len(set(paths)&reads),requiredSources=count,
                               oracle=len(set(paths)&reads)==count and work_checks.complete({'status':store.get(child)['status']}))
                elif case=='long_testing':
                    node={'id':'N1','kind':'build','title':case,'goal':'Kiểm export CSV giữ tiếng Việt trên fixture',
                          'acceptance':['Giữ nguyên tiếng Việt'],'tests':['python -m pytest -q']}
                    run=graph.create(session,{'goal':'Fix CSV export','flow':'fix','nodes':[node]});node=run['nodes'][0]
                    text='Patch fixture: CSV dùng csv.writer, giữ Unicode. Tester phải tự chạy python -m pytest -q.'
                    policy=work_policy.derive(run,node,'execute',text,changed=True)
                    meta=await graph.artifacts.put(run,'N1','execute',text,graph.checks.binding(run,node,'execute')|
                        {'policyHash':policy['hash'],'codeSnapshot':await work_checks.snapshot(graph,session['id'])},True)
                    node['stages']['execute'].update(status='needs_checks',attempts=1,output=text,policy=policy,artifact=meta,
                        rounds=[{'attempt':1,'at':time.time()}]);graph.save(run)
                    checked=await graph.checks.tool(session,{'action':'start','runId':run['runId'],'nodeId':'N1','stage':'execute',
                        'artifactId':meta['artifactId'],'checkIds':['tests'],'invocationId':uuid.uuid4().hex})
                    doc=checked['checks'][0];child=doc.get('childId');row.update(status=doc['status'],oracle=doc['status']=='pass',check=doc)
                else:
                    count=1 if case=='single_large_review' else 8
                    nodes=[{'id':f'R{i+1}','kind':'research','title':f'Scope {i+1}',
                            'goal':'Kiểm báo cáo synthetic CSV giữ phạm vi người dùng',
                            'acceptance':['Chỉ CSV, không JSON; proposal cuối không được trái nguồn']} for i in range(count)]
                    run=graph.create(session,{'goal':'Chỉ nghiên cứu synthetic CSV; không lập plan app','flow':'research','nodes':nodes})
                    metas=[]
                    for node in run['nodes']:
                        distinct = args.distinct_artifacts and count > 1
                        title = '# Báo cáo synthetic' + (' ' + node['id'] if distinct else '')
                        conclusion = ('Kết luận cuối: giữ CSV, không JSON.' if distinct and node['id'] == 'R8'
                                      else 'Kết luận cuối: bắt buộc đổi sang JSON.')
                        text=title+'\nNguồn docs/source.md: chỉ CSV.\n'+('Chi tiết synthetic trung tính, không thêm phạm vi.\n'*(3200 if count==1 else 500))+'\n'+conclusion+'\n'
                        policy=work_policy.derive(run,node,'produce',text)
                        meta=await graph.artifacts.put(run,node['id'],'produce',text,graph.checks.binding(run,node,'produce')|{'policyHash':policy['hash']},True)
                        node['stages']['produce'].update(status='needs_checks',attempts=1,output=text,artifact=meta,policy=policy,
                            rounds=[{'attempt':1,'at':time.time()}]);metas.append(meta)
                    graph.save(run)
                    criteria={f'{n["id"]}.A1':n['acceptance'][0] for n in run['nodes']}
                    doc={'checkId':'c-'+uuid.uuid4().hex,'status':'running'}
                    if count > 1:
                        doc=await graph.checks.judge(session,run,None,'verify',{'id':'whole','executorRole':'plan-review'},metas,criteria,doc,whole=True)
                    else:
                        doc=await graph.checks.judge(session,run,run['nodes'][0],'produce',{'id':'evidence','executorRole':'research-review'},metas,criteria,doc)
                    child=doc.get('childId');row.update(status=doc['status'],oracle=doc['status']=='revise',check=doc,
                        artifactChars=[m['chars'] for m in metas],fullReads=all(graph.artifacts.covered(doc['checkId'],m,child) for m in metas))
                    if args.distinct_artifacts and count > 1:
                        expected = {f'R{i}.A1': 'pass' if i == 8 else 'revise' for i in range(1, 9)}
                        actual = {c['id']: c['status'] for c in doc.get('coverage', [])}
                        row.update(expectedCoverage=expected, actualCoverage=actual,
                                   oracle=doc['status']=='revise' and actual==expected)
                events=[{'seq':e['seq'],'type':e['kind'],'data':json.loads(e['payload']),'created':e['created']}
                        for e in store.db.execute('SELECT * FROM events WHERE session_id=? ORDER BY seq',(child,))]
                row.update(childId=child,childConfig={k:store.get(child)['config'][k] for k in ('maxSteps','deadlineSeconds')},
                    childOutputProfile=store.get(child)['config'].get('maxTokens'),
                    appliedBudget=store.get(child)['config'].get('workBudget'),
                    answer=graph.child_answer(child),events=events,
                    stepsUsed=max((e['data'].get('stepsUsed',0) for e in events if e['type']=='turn_end'),default=0),
                    toolCalls=sum(e['type']=='tool_end' for e in events))
            except Exception as exc:
                row.update(status='error',oracle=False,error=type(exc).__name__+': '+str(exc))
            row.update(latencySeconds=round(time.monotonic()-started,3),completions=client.calls[call_start:])
            rows.append(row)
            (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row.get(k) for k in ('case','repeat','profile','status','oracle','stepsUsed','toolCalls','latencySeconds')},ensure_ascii=False),flush=True)
            store.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--router',required=True);p.add_argument('--output',required=True)
    p.add_argument('--profile',choices=list(PROFILES),required=True);p.add_argument('--repeats',type=int,default=2)
    p.add_argument('--cases',nargs='+',choices=CASES,default=list(CASES))
    p.add_argument('--distinct-artifacts', action='store_true', help='Distinct multi-artifact hashes; last report is valid CSV-only')
    asyncio.run(run(p.parse_args()))
