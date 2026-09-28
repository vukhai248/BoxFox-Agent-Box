"""Plan workflow benchmark. Dry run by default; isolated SQLite/workspace per cell.

The model and all configured specialist routes/budgets come from an existing root session.
Workflow checks are automated; semantic judgments remain the independent SWE-AI/1 review.
Inspect exported documents/findings before claiming the 90% acceptance threshold.
"""
from __future__ import annotations
import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / 'backend/tests/fixtures/plan_workflow_eval_v1.json'
sys.path.insert(0, str(Path(__file__).parent))
import guard

def source_metadata():
    """Identify the exact source without saving potentially sensitive diff contents."""
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT)
    changed = git('diff', '--binary', 'HEAD')
    untracked = git('ls-files', '--others', '--exclude-standard').decode('utf-8').splitlines()
    inputs = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in untracked
              if name.startswith(('backend/', 'frontend/src/', 'scripts/eval/')) and (ROOT/name).is_file()}
    return {'commit': git('rev-parse', 'HEAD').decode().strip(),
            'branch': git('branch', '--show-current').decode().strip(),
            'trackedPatchSha256': hashlib.sha256(changed).hexdigest(), 'untrackedSourceSha256': inputs}

def classify_errors(events):
    categories = {'providerErrors': [], 'productErrors': [], 'evaluationErrors': []}
    for event in events:
        if event['type'] != 'error': continue
        error = event['data']
        text = str(error).upper()
        group = ('evaluationErrors' if 'EVAL_' in text else 'providerErrors' if any(
            token in text for token in ('UPSTREAM', 'PROVIDER', 'HTTP_', 'RATE_LIMIT', 'CONNECTION', 'TIMEOUT')) else 'productErrors')
        categories[group].append(error)
    return categories

class IsolatedExecutor:
    def __init__(self, root):
        self.root = root.resolve()
        self.calls = []
    def path(self, name):
        name = str(name).replace('/home/agent/workspace/', '')
        if name == '/home/agent/workspace':
            name = '.'
        result = (self.root / name).resolve()
        if not result.is_relative_to(self.root):
            raise ValueError('EVAL_PATH_OUTSIDE_WORKSPACE')
        return result
    async def cleanup(self, sid):
        pass
    async def request(self, path, body=None):
        from agentbox.agent_core import plan_registry
        if path != plan_registry.INDEX_PATH:
            raise ValueError('EVAL_UNSUPPORTED_GATEWAY: ' + path)
        groups = {}
        for file in sorted(self.root.glob('.plans/v*.md')):
            match = re.fullmatch(r'v(\d+)-(.+)\.md', file.name)
            if not match: continue
            version, slug = int(match[1]), match[2]
            groups.setdefault(slug, {'identity':slug,'relativeDirectory':'','slug':slug,'versions':[]})['versions'].append({
                'version':version,'label':f'v{version}','relativePath':'.plans/'+file.name,
                'sizeBytes':file.stat().st_size,'modifiedAt':str(file.stat().st_mtime),
                'status':'draft','headerStatus':'ok','headerVersion':version,'headerIdentity':slug,
                'declaredParent':None,'declaredSlug':None})
        return {'plans':list(groups.values()),'ignoredCount':0,'warnings':[]}
    async def execute(self, name, args, sid):
        self.calls.append({'name':name,'sessionId':sid})
        if name == 'file_read':
            text = self.path(args['path']).read_text(encoding='utf-8')
            offset, limit = int(args.get('offset') or 0), int(args.get('limit') or 30000)
            end = min(len(text), offset+limit)
            return {'content':text[offset:end],'nextOffset':end if end<len(text) else None,'sizeChars':len(text),'truncated':end<len(text)}
        if name == 'codebase_glob':
            pattern = args.get('pattern') or '**/*'
            paths = [p.relative_to(self.root).as_posix() for p in self.root.rglob('*') if p.is_file()]
            found = [p for p in paths if fnmatch.fnmatch(p,pattern) or fnmatch.fnmatch(p,pattern.removeprefix('**/'))]
            return {'content':'\n'.join(found[:200])}
        if name == 'codebase_grep':
            pattern = re.compile(args.get('pattern') or '')
            matches = []
            for file in self.root.rglob('*'):
                if not file.is_file() or file.suffix not in {'.md','.py','.json'}: continue
                for n,line in enumerate(file.read_text(encoding='utf-8').splitlines(),1):
                    if pattern.search(line): matches.append(f'{file.relative_to(self.root).as_posix()}:{n}:{line}')
            return {'content':'\n'.join(matches[:100])}
        if name == 'write_plan':
            version, slug = args.get('version') or 1, args['slug']
            target = self.path(f'.plans/v{version}-{slug}.md')
            if target.exists(): return {'is_error':True,'content':'PLAN_VERSION_TAKEN'}
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(args['markdown'],encoding='utf-8',newline='\n')
            return {'content':'Written isolated plan','version':version,'slug':slug,
                    'relativePath':target.relative_to(self.root).as_posix(),'bytes':target.stat().st_size}
        if name == 'journal_append':
            target = self.path('.session-history/journal.jsonl')
            target.parent.mkdir(parents=True,exist_ok=True)
            seq = len(target.read_text(encoding='utf-8').splitlines())+1 if target.exists() else 1
            record = dict(args.get('record') or {}) | {'seq':seq}
            with target.open('a',encoding='utf-8') as file:
                file.write(json.dumps(record,ensure_ascii=False)+'\n')
            return {'ok':True,'id':record.get('id'),'seq':seq,'relPath':'.session-history/journal.jsonl'}
        if name == 'journal_read':
            target = self.path('.session-history/journal.jsonl')
            records = [json.loads(line) for line in target.read_text(encoding='utf-8').splitlines()] if target.exists() else []
            return {'records':records}
        # The baseline also cannot modify implementation, even if it tries after approval.
        raise ValueError('EVAL_EXECUTION_PROHIBITED_OR_UNSUPPORTED: ' + name)

def seed(workspace, case, pack):
    workspace.mkdir(parents=True,exist_ok=True)
    example = workspace/'example'; example.mkdir(exist_ok=True)
    (example/'app.py').write_text('def normalise_name(value):\n    return value.strip()\n',encoding='utf-8')
    (example/'test_app.py').write_text('from app import normalise_name\ndef test_normal():\n    assert normalise_name(" a ") == "a"\n',encoding='utf-8')
    (workspace/'README.md').write_text('Isolated evaluation example: Python normalise_name, tests with pytest. No medical app exists yet.',encoding='utf-8')
    plans=workspace/'.plans'; plans.mkdir(exist_ok=True)
    if case['id']=='unrelated_old_plan':
        (plans/'v3-medical.md').write_text('<!-- boxfox-plan\nVersion: v3\nIdentity: medical\nParent: none\n-->\n# Unrelated medical prototype\nOffline mock data and OCR were proposed for a different project.',encoding='utf-8')
    if case['id']=='fake_headings':
        (plans/'v1-fake.md').write_text('<!-- boxfox-plan\nVersion: v1\nIdentity: fake\nParent: none\n-->\n# Agent hồ sơ y tế\n## Architecture\nRule + LLM, RAG, JSON Schema.\n## Data\nUse files.\n## Milestones\n1. Build.\n## Acceptance\nCitation field exists.\n## Risks\nNone.\n## Sources\nUnverified.',encoding='utf-8')
        sample=pack.get('legacySample',{}).get('path')
        if sample: (plans/'v1-medical-record-synthesis-agent.md').write_bytes((ROOT/sample).read_bytes())

async def cell(args, config, case, repeat, pack):
    from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
    from agentbox.memory.session_store import SessionStore
    directory=Path(args.out)/args.variant/case['id']/str(repeat)
    if directory.exists(): raise ValueError('EVAL_CELL_ALREADY_EXISTS: choose a fresh output directory')
    workspace=directory/'workspace'; seed(workspace,case,pack)
    db=directory/'sessions.sqlite'
    executor=IsolatedExecutor(workspace)
    rt=HarnessRuntime(SessionStore(db),executor,RouterClient(args.router))
    injected=[False]
    if case['id']=='reviewer_failure':
        original=rt.client.complete
        async def fail_once(messages, *a, **kw):
            if not injected[0] and 'Plan Review Specialist' in str(messages[0].get('content')):
                injected[0]=True
                raise RuntimeError('UPSTREAM_HTTP_502: seeded reviewer provider failure')
            return await original(messages,*a,**kw)
        rt.client.complete=fail_once
    sid=rt.create(config)['id']; started=time.monotonic(); rounds=0; approved=False; approval_started_build=False
    if args.variant=='reform':
        from agentbox.agent_core import plan_workflow as pw
    try:
        await rt.submit(sid,case['prompt'],invocation_id='initial')
        while True:
            task=rt.tasks.get(sid)
            if task and not task.done():
                for pending in list(rt.pending.values()):
                    if pending['resolved']: continue
                    choice='approve' if pending['kind']=='approval' else 'other'
                    rt.resolve_decision(pending['sessionId'],pending['decisionId'],choice,
                                        '\n'.join(case['answersByField'].values()) or 'Theo yêu cầu đã nêu.')
                await asyncio.wait([task],timeout=1)
                continue
            if args.variant!='reform': break
            flow=pw.service(rt); run=flow.runs(sid)[0]
            if run['status']=='needs_user':
                rounds+=1
                pending=flow.pending_questions(run)
                if case['id']=='changed_intent' and rounds==2:
                    await rt.submit(sid,case['afterFirstInterview'],invocation_id='changed-intent'); continue
                answers=[]
                for q in pending:
                    answer={'questionId':q['id']}
                    if q['field']=='__confirm__': answer['optionId']='confirm'
                    elif q['field']=='__approval__': answer['optionId']='approve'
                    else: answer['text']=case['answersByField'].get(q['field']) or 'Thông tin đã có trong yêu cầu; nếu chưa biết kỹ thuật, hãy nghiên cứu và đề xuất có lý do.'
                    answers.append(answer)
                before = rt.store.get(sid)['turn_count']
                answered = flow.answers(run['runId'],{'revision':run['revision'],'invocationId':f'answer-{rounds}','answers':answers})
                approved = approved or answered['run']['phase'] == 'approved'
                if case['id']=='restart' and rounds==1:
                    rt.store.close(); rt=HarnessRuntime(SessionStore(db),executor,RouterClient(args.router)); pw.service(rt).recover()
                await pw.pump(rt)
                if answered['run']['phase'] == 'approved':
                    approval_started_build = rt.store.get(sid)['turn_count'] != before
                continue
            if run['phase']=='ready':
                before=rt.store.get(sid)['turn_count']
                result=flow.action(run['runId'],run['document']|{'action':'approve','revision':run['revision'],'invocationId':'approve'})
                approved=result['run']['phase']=='approved'
                await pw.pump(rt)
                approval_started_build=rt.store.get(sid)['turn_count']!=before
            break
        events=[{'sessionId':r['session_id'],'type':r['kind'],'data':json.loads(r['payload']),'created':r['created']} for r in rt.store.db.execute('SELECT * FROM events ORDER BY seq')]
        children=rt.store.children_of(sid)
        runs=pw.service(rt).runs(sid) if args.variant=='reform' else []
        result={'case':case['id'],'repeat':repeat,'variant':args.variant,'config':config,'elapsedSeconds':round(time.monotonic()-started,3),
                'rootSessionId':sid,'status':rt.store.get(sid)['status'],'runs':runs,'approved':approved,
                'approvalStartedBuild':approval_started_build,'interviewRounds':rounds,'injectedReviewerFailure':injected[0],
                **classify_errors(events),
                'usage':[e['data'] for e in events if e['type']=='usage'],
                'implementationDelegations':[c for c in children if c['role'] in {'build','backend','frontend','debug'}],
                'semanticJudgment':'Inspect bound independent review and exported plan; automated workflow flags alone are not a quality score.'}
        (directory/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    except Exception as exc:
        result = {'case':case['id'],'repeat':repeat,'variant':args.variant,'status':'failed',
                  'error':str(exc),'errorType':type(exc).__name__,'elapsedSeconds':round(time.monotonic()-started,3)}
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        return result
    finally:
        for active in list(rt.tasks): await rt.stop(active)
        rt.store.close()

def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true'); parser.add_argument('--budget-usd',type=float)
    parser.add_argument('--variant',choices=['reform','baseline'],default='reform')
    parser.add_argument('--baseline-src',help='Extracted baseline backend/src, never checkout main')
    parser.add_argument('--harness',default='http://127.0.0.1:3102'); parser.add_argument('--router',default='http://127.0.0.1:3101')
    parser.add_argument('--session-id'); parser.add_argument('--case'); parser.add_argument('--out',default=str(Path.home()/'BoxFox'/'plan-eval'/str(int(time.time()))))
    args=parser.parse_args(); pack=json.loads(PACK.read_text(encoding='utf-8'))
    cases=[c for c in pack['cases'] if not args.case or c['id']==args.case]
    if not cases: parser.error('Unknown case')
    if not args.execute:
        print(json.dumps({'dryRun':True,'variant':args.variant,'cells':len(cases)*pack['repeats'],'cases':[c['id'] for c in cases],'modelCalls':0,'budgetGate':guard.check(args.budget_usd)},ensure_ascii=False,indent=2)); return
    check=guard.check(args.budget_usd)
    if not check['allowed']: parser.error(check['reason'])
    args.budget_usd=check['budgetUsd']
    if args.variant=='baseline' and not args.baseline_src: parser.error('baseline requires --baseline-src from the recorded baseline commit')
    sys.path.insert(0,args.baseline_src if args.variant=='baseline' else str(ROOT/'backend/src'))
    # Preserve the repository's single network boundary for evaluation entry points.
    import net
    sid=args.session_id
    if not sid:
        rows=net.request_json(args.harness+'/api/agent/sessions',headers={'X-BoxFox-Admin':'1'},timeout=10)
        rows=rows.get('sessions',[]) if isinstance(rows,dict) else rows
        sid=next(r['id'] for r in rows if not r.get('parent_id'))
    saved=net.request_json(args.harness+'/api/agent/sessions/'+sid,headers={'X-BoxFox-Admin':'1'},timeout=10)
    saved=saved.get('session',saved); config=saved['config']
    if not config.get('route',{}).get('modelId'): parser.error('The existing root session has no selected model; do not choose a replacement')
    config={k:v for k,v in config.items() if k not in {'planMode','designMode','researchMode','planBinding'}}
    metadata=source_metadata()
    async def run():
        results=[]
        for case in cases:
            for repeat in range(1,pack['repeats']+1):
                try:
                    result=await cell(args,config,case,repeat,pack)
                except Exception as exc:
                    result={'case':case['id'],'repeat':repeat,'variant':args.variant,'status':'failed','error':str(exc),'errorType':type(exc).__name__}
                results.append(result)
                result['source']=metadata
                print(json.dumps({'case':case['id'],'repeat':repeat,'status':result['status'],'approved':result.get('approved')},ensure_ascii=False),flush=True)
                # Checkpoint every completed cell, including failures, for interrupted evaluation runs.
                out=Path(args.out)/args.variant/'summary.json'; out.parent.mkdir(parents=True,exist_ok=True)
                out.write_text(json.dumps({'schema':pack['schema'],'budgetUsd':args.budget_usd,
                    'budgetEnforcement':'Repository opt-in gate; no dollar cost meter. Runtime token/time budgets remain configured.',
                    'baselineCommit':pack['baselineCommit'],'source':metadata,'results':results},ensure_ascii=False,indent=2),encoding='utf-8')
    asyncio.run(run())

if __name__=='__main__': main()
