"""Work Graph — lớp điều phối mới: main dựng đồ thị việc, harness chạy mỗi nút qua vòng
SẢN XUẤT ↔ PHẢN BIỆN, kiểm cả kế hoạch, xin duyệt (hoặc Autopilot), chạy DAG rồi đóng gói PR.

Bộ kiểm dùng model/executor giả nhận diện lời gọi theo NỘI DUNG tin nhắn người dùng đầu tiên
(cùng cách `test_async_delegation.py`): nút sản xuất, người phản biện, người trả lời câu hỏi kiến
thức và người phản biện toàn kế hoạch có đầu câu khác nhau.
"""
import asyncio
import json
import re
import uuid
from pathlib import Path

import pytest

from agentbox.agent_core import plan_workflow, tool_groups, work_graph as wg, work_checks
from agentbox.agent_core.failures import classify_failure
from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS, ROLES
from agentbox.agent_core.runtime import DecisionError, HarnessRuntime, WORK_TOOLS
from agentbox.agent_core.tool_contracts import SCHEMAS, reflection_hint
from agentbox.memory.session_store import SessionStore

PRODUCE = 'Work Graph run'
REVIEW = 'Independent review of Work Graph node'
WHOLE = 'Whole-plan review of Work Graph run'
KNOW = 'Knowledge request from Work Graph node'


def answer(text):
    return {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


class Model:
    """`script(kind, first_user_text)` → text. Records every prompt and the peak concurrency."""

    def __init__(self, script, delay=0.0):
        self.script = script
        self.delay = delay
        self.prompts = []
        self.tokens = []
        self.active = 0
        self.peak = 0

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        if getattr(self, 'latest_assignment', False):
            # Same-child continuations receive a new assignment/ref packet while
            # retaining the old messages. This fixture reads fresh inputs too.
            index = max(i for i,m in enumerate(messages) if m.get('role') == 'user')
            messages = messages[index:]
        first = next((str(m.get('content') or '') for m in messages if m.get('role') == 'user'), '')
        kind = next((name for name, head in (('whole', WHOLE), ('review', REVIEW), ('knowledge', KNOW),
                                             ('produce', PRODUCE)) if head in first), 'main')
        if first.startswith('Phản biện toàn kế hoạch'):
            kind='whole'
        elif first.startswith('Phản biện độc lập'):
            kind='review'
        elif first.startswith('Yêu cầu tra cứu'):
            kind='knowledge'
        elif first.startswith('Work Graph "'):
            kind='produce'
        tool_messages = [m for m in messages if m.get('role') == 'tool']
        calls = []
        if not tool_messages:
            calls.append({'id': 'source', 'type': 'function', 'function': {'name': 'file_read', 'arguments': json.dumps({'path':'src/a.py'})}})
        match = re.search(r'\{"snapshots":', first)
        refs = json.JSONDecoder().raw_decode(first[match.start():])[0]['snapshots'] if match else []
        reads = {}
        for m in tool_messages:
            if m.get('name') == 'work_artifact_read':
                data=json.loads(m['content'])
                if 'artifactId' in data:
                    reads[data['artifactId']]=data.get('nextOffset')
        for meta in refs:
            aid=meta['artifactId']
            if aid not in reads or reads[aid] is not None:
                calls.append({'id':aid+str(reads.get(aid,0)), 'type':'function', 'function': {'name':'work_artifact_read', 'arguments':json.dumps({'artifactId':aid,'offset':reads.get(aid,0) or 0})}})
        if kind == 'review' and '"id": "tests"' in first and not any(m.get('name')=='terminal_exec' for m in tool_messages):
            calls.append({'id':'tests','type':'function','function':{'name':'terminal_exec','arguments':json.dumps({'command':'vitest ChatHeader.test.tsx'})}})
        if calls:
            return {'choices':[{'message':{'tool_calls':calls},'finish_reason':'tool_calls'}]}
        self.prompts.append((kind, first))
        self.tokens.append((kind, first, max_tokens))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            text = self.script(kind, first)
            if kind in ('review','whole'):
                match=re.search(r'\{"(?:A1|C1|G1)"', first)
                criteria=json.JSONDecoder().raw_decode(first[match.start():])[0] if match else {'C1':'contract'}
                verdict=wg.parse_verdict(text)[0]
                coverage=[{'id':key,'status':'pass' if verdict=='ok' else 'revise','target':'artifact','evidence':'Fixture assertion: '+str(value)} for key,value in criteria.items()]
                text=wg.VERDICT_RE.sub('',text).strip()+'\n```json\n'+json.dumps({'coverage':coverage})+'\n```\nVERDICT: '+(verdict or 'revise')
            return answer(text)
        finally:
            self.active -= 1


class Executor:
    def __init__(self, git=False):
        self.git = git
        self.commit_fails = False
        self.calls = []

    async def execute(self, name, args, sid, **_identity):
        self.calls.append((name, args))
        if name == 'write_plan':
            return {'relativePath': f".plans/{args['directory']}/{args['slug']}.md", 'version': 1}
        if name == 'terminal_exec':
            if args['command'] == work_checks.SNAPSHOT_COMMAND:
                return {'content':json.dumps({'schema':'work-code/1','hash':'a'*64,'head':'fixture'}), 'exit_code':0}
            command = args['command'].split(' && ', 1)[1] if args['command'].startswith('cd ') \
                else args['command']
            if command.startswith('git rev-parse --is-inside-work-tree'):
                return {'content': 'true' if self.git else 'fatal: not a git repository',
                        'exit_code': 0 if self.git else 128, 'is_error': not self.git}
            if command.startswith('git remote get-url'):
                return {'content': 'error: No such remote', 'exit_code': 2, 'is_error': True}
            if 'commit -m' in command and self.commit_fails:
                return {'content': 'pre-commit hook failed', 'exit_code': 1, 'is_error': True}
            if command.startswith('git rev-parse --short'):
                return {'content': 'abc1234\n', 'exit_code': 0, 'is_error': False}
            return {'content': 'ok', 'exit_code': 0, 'is_error': False}
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def ok_script(kind, text):
    if kind in ('review', 'whole'):
        return 'Blocking findings: none\nVERDICT: ok'
    if kind == 'knowledge':
        return 'The answer is 42 (src/a.py:3).'
    return '## Findings\n- src/a.py:1 fixture\n## Knowledge requests\n- none'


def build(tmp_path, script=ok_script, delay=0.0, git=False, values=None):
    store = SessionStore(tmp_path / 'sessions.db')
    model = Model(script, delay)
    executor = Executor(git)
    runtime = HarnessRuntime(store, executor, model)
    sid = runtime.create({'skills': [], **(values or {})})['id']
    return store, runtime, model, executor, sid


async def raw_tool(runtime, sid, name, args):
    return await runtime.work_tool(runtime.store.get(sid), name, args)


async def tool(runtime, sid, name, args):
    """Simulated main for legacy orchestration tests, explicitly drives new check calls."""
    result=await raw_tool(runtime,sid,name,args)
    if name != 'work_run':
        return result
    stage='produce' if args['phase']=='discover' else 'execute'
    for _ in range(8):
        run=wg.service(runtime).get(result['runId'])
        needs=[n for n in run['nodes'] if n['stages'].get(stage,{}).get('status')=='needs_checks']
        for node in needs:
            await raw_tool(runtime,sid,'work_check',{'action':'start','nodeId':node['id'],'stage':stage,
                'artifactId':node['stages'][stage]['artifact']['artifactId'],'invocationId':uuid.uuid4().hex})
        run=wg.service(runtime).get(result['runId'])
        if not wg.ready_nodes(run,stage) or result.get('budgetExhausted'):
            break
        result=await raw_tool(runtime,sid,name,args)
    run=wg.service(runtime).get(result['runId'])
    for item in result['outputs']:
        state=next(n for n in run['nodes'] if n['id']==item['id'])['stages'][stage]
        item.update(status=state['status'],attempts=state['attempts'],verdicts=[r.get('verdict') for r in state['rounds']],
                    artifact=state.get('artifact'),policy=state.get('policy'),acceptedWithCaveats=False)
    return result | wg.service(runtime).result(run)


EXPLORE = {'id': 'E1', 'kind': 'explore', 'title': 'Explore chat', 'goal': 'Find the chat header and its store'}
PLAN = {'id': 'P1', 'kind': 'plan', 'title': 'Export plan', 'goal': 'Plan the export button implementation',
        'dependsOn': ['E1'], 'acceptance': ['button exports markdown'], 'tests': ['vitest ChatHeader.test.tsx']}


# ------------------------------------------------------------------------------ pure helpers

def test_normalize_node_names_the_field_and_the_rule():
    with pytest.raises(ValueError, match='WORK_NODE_INVALID: id'):
        wg.normalize_node({'id': '1x', 'kind': 'explore', 'title': 't', 'goal': 'x' * 30})
    with pytest.raises(ValueError, match="kind 'coder'"):
        wg.normalize_node({'id': 'E1', 'kind': 'coder', 'title': 't', 'goal': 'x' * 30})
    with pytest.raises(ValueError, match='at least 20 characters'):
        wg.normalize_node({'id': 'E1', 'kind': 'explore', 'title': 't', 'goal': 'short'})
    with pytest.raises(ValueError, match='needs `acceptance`'):
        wg.normalize_node({'id': 'P1', 'kind': 'plan', 'title': 't', 'goal': 'x' * 30, 'tests': ['a']})
    with pytest.raises(ValueError, match='needs `tests`'):
        wg.normalize_node({'id': 'B1', 'kind': 'build', 'title': 't', 'goal': 'x' * 30})
    node = wg.normalize_node(PLAN)
    assert set(node['stages']) == {'produce', 'execute'}
    assert set(wg.normalize_node(EXPLORE)['stages']) == {'produce'}


def test_graph_issues_find_cycles_unknown_nodes_and_planning_waiting_for_code():
    nodes = [wg.normalize_node(item) for item in (
        {'id': 'A', 'kind': 'plan', 'title': 'a', 'goal': 'x' * 30, 'dependsOn': ['B'], 'acceptance': ['a'],
         'tests': ['t']},
        {'id': 'B', 'kind': 'plan', 'title': 'b', 'goal': 'x' * 30, 'dependsOn': ['A'], 'acceptance': ['a'],
         'tests': ['t']},
        {'id': 'C', 'kind': 'explore', 'title': 'c', 'goal': 'x' * 30, 'dependsOn': ['Z', 'D']},
        {'id': 'D', 'kind': 'build', 'title': 'd', 'goal': 'x' * 30, 'tests': ['t']})]
    issues = ' | '.join(wg.graph_issues(nodes))
    assert 'dependency cycle' in issues
    assert 'unknown node Z' in issues
    assert 'planning must not wait for code' in issues


def test_execution_waves_are_topological_layers():
    nodes = [wg.normalize_node(item) for item in (
        EXPLORE, PLAN,
        {'id': 'P2', 'kind': 'plan', 'title': 'two', 'goal': 'x' * 30, 'dependsOn': ['E1'], 'acceptance': ['a'],
         'tests': ['t']},
        {'id': 'P3', 'kind': 'plan', 'title': 'three', 'goal': 'x' * 30, 'dependsOn': ['P1', 'P2'],
         'acceptance': ['a'], 'tests': ['t']})]
    assert wg.execution_waves(nodes) == [['P1', 'P2'], ['P3']]


def test_parse_verdict_takes_the_last_line_and_accepts_the_legacy_form():
    assert wg.parse_verdict('VERDICT: revise\nlater\n**VERDICT:** ok')[0] == 'ok'
    assert wg.parse_verdict('looks bad [CHANGES REQUESTED]')[0] == 'revise'
    assert wg.parse_verdict('[APPROVED]')[0] == 'ok'
    assert wg.parse_verdict('no verdict here') == (None, 'no verdict here')


def test_parse_knowledge_requests_and_revise_targets():
    text = ('## Plan\nx\n## Knowledge requests\n- research: which Vite version supports Node 20?\n'
            '- explore: where is the chat store defined?\n- none\n- research: tiny\n## Other\n- research: ignored one')
    assert wg.parse_knowledge_requests(text) == [
        {'role': 'research', 'question': 'which Vite version supports Node 20?'},
        {'role': 'explore', 'question': 'where is the chat store defined?'}]
    assert wg.parse_knowledge_requests('## Knowledge requests\n- none') == []
    assert wg.parse_revise_targets('REVISE P1: add tests\n- REVISE X9: unknown\nREVISE P2 — order', {'P1', 'P2'}) \
        == {'P1': 'add tests', 'P2': 'order'}


def test_slugify_folds_vietnamese_letters():
    assert wg.slugify('Đổi tên đường dẫn') == 'doi-ten-duong-dan'
    assert wg.slugify('!!!') == 'work'


# --------------------------------------------------------------------------- engine: discover

def test_discover_runs_the_review_loop_until_ok_and_feeds_the_findings_back(tmp_path):
    reviews = {'E1': 0}

    def script(kind, text):
        if kind == 'review' and 'node E1' in text:
            reviews['E1'] += 1
            return ('1. The store path is missing (fix: cite src/store.ts:10).\nVERDICT: revise'
                    if reviews['E1'] == 1 else 'none\nVERDICT: ok')
        return ok_script(kind, text)

    store, runtime, model, _, sid = build(tmp_path, script)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button', 'flow': 'plan'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE | {'risk':'consequential'}]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    node = out['outputs'][0]
    assert node['status'] == 'accepted' and node['verdicts'] == ['revise', 'ok'] and node['attempts'] == 2
    second = [text for kind, text in model.prompts if kind == 'produce'][1]
    assert 'REJECTED by the reviewer' in second and 'src/store.ts:10' in second
    children = [e['data'] for e in store.events(sid) if e['type'] == 'child' and e['data'].get('status') == 'started']
    assert {c['work']['purpose'] for c in children} == {'produce', 'review'}
    assert all(c['work']['runId'] == out['runId'] for c in children)


def test_at_the_round_cap_evidence_is_rejected_without_caveat_auto_accept(tmp_path):
    def script(kind,text):
        return 'Still wrong\nVERDICT: revise' if kind=='review' else ok_script(kind,text)
    _,runtime,_,_,sid=build(tmp_path,script)
    async def run():
        await tool(runtime,sid,'work_graph',{'action':'create','goal':'Survey the architecture'})
        await tool(runtime,sid,'work_graph',{'action':'add','nodes':[EXPLORE | {'risk':'consequential'},PLAN]})
        return await tool(runtime,sid,'work_run',{'phase':'discover','maxRounds':2})
    result=asyncio.run(run())
    assert result['outputs'][0]['status']=='rejected'
    assert not result['outputs'][0]['acceptedWithCaveats']
    assert result['outputs'][1]['status']=='pending'


def test_a_revise_without_blocking_findings_does_not_auto_pass(tmp_path):
    def script(kind, text):
        if kind == 'review':
            return '## Blocking findings\nnone\n## Non-blocking notes\n- line 12 is line 14\nVERDICT: revise'
        return ok_script(kind, text)

    _, runtime, _, _, sid = build(tmp_path, script)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Survey the chat header'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE | {'risk':'consequential'}]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    assert out['outputs'][0]['status'] == 'rejected'
    assert out['outputs'][0]['attempts'] == 3


def test_has_no_blocking_findings_reads_the_common_forms():
    assert wg.has_no_blocking_findings('## Blocking findings\n- none\n\n## Non-blocking notes\n- a')
    assert wg.has_no_blocking_findings('**Blocking findings:** None.')
    assert wg.has_no_blocking_findings('## Blocking findings — none')
    assert not wg.has_no_blocking_findings('## Blocking findings\n1. tests/x.py:3 has a TestCase')
    assert not wg.has_no_blocking_findings('no section at all')


def test_default_sessions_can_open_the_work_graph_skill():
    from agentbox.skills.catalog import DEFAULT_SKILLS
    from agentbox.skills.commands import ROLE_SKILLS
    assert 'work-graph-planning' in DEFAULT_SKILLS
    assert 'work-graph-planning' in DEFAULT_SKILLS & ROLE_SKILLS['plan']


def test_knowledge_requests_are_answered_by_children_and_fed_back(tmp_path):
    produced = {'n': 0}

    def script(kind, text):
        if kind == 'produce':
            produced['n'] += 1
            if produced['n'] == 1:
                return '## Draft\n## Knowledge requests\n- research: which Vite version supports Node 20 exactly?'
            return '## Findings\nfinal\n## Knowledge requests\n- none'
        return ok_script(kind, text)

    _, runtime, model, _, sid = build(tmp_path, script)
    model.latest_assignment = True

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Upgrade the build tool'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    assert out['outputs'][0]['status'] == 'accepted'
    kinds = [kind for kind, _ in model.prompts]
    assert kinds == ['produce', 'knowledge', 'produce']
    rerun = [text for kind, text in model.prompts if kind == 'produce'][1]
    assert 'Lookup artifacts for your knowledge requests' in rerun and 'The answer is 42' not in rerun
    run_doc = runtime.work_graph.get(out['runId'])
    knowledge = run_doc['nodes'][0]['stages']['produce']['rounds'][0]['knowledge']
    assert knowledge[0]['role'] == 'research' and knowledge[0]['childId']
    assert knowledge[0]['artifact']['artifactId'] in rerun
    assert knowledge[0]['artifact']['binding']['verification'] == 'unreviewed'
    producer = run_doc['nodes'][0]['stages']['produce']['rounds'][0]
    assert producer['initialProducerId'] == producer['producerId']
    assert len(runtime.store.children_of(sid)) == 2


def test_independent_nodes_run_in_parallel(tmp_path):
    _, runtime, model, _, sid = build(tmp_path, delay=0.05)
    nodes = [{'id': f'E{i}', 'kind': 'explore', 'title': f'explore {i}', 'goal': f'Explore area number {i} fully'}
             for i in range(1, 4)]

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Survey three areas'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': nodes})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    assert [item['status'] for item in out['outputs']] == ['accepted'] * 3
    assert model.peak >= 2, 'nodes without dependencies must overlap in time'


# ------------------------------------------------------------------ verify, submit, execute, ship

def test_verify_revise_resets_the_named_sub_plan_then_ok_writes_documents(tmp_path):
    whole = {'n': 0}

    def script(kind, text):
        if kind == 'whole':
            whole['n'] += 1
            return ('## Blocking findings\n1. tests missing\nREVISE P1: add a failing-path test\nVERDICT: revise'
                    if whole['n'] == 1 else 'none\nVERDICT: ok')
        return ok_script(kind, text)

    store, runtime, model, _, sid = build(tmp_path, script)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button', 'flow': 'plan'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        first = await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        rerun = await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        second = await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        return first, rerun, second

    first, rerun, second = asyncio.run(run())
    assert first['verdict'] == 'revise' and first['reviseNodes'] == ['P1'] and first['status'] == 'needs_revision'
    assert [o['id'] for o in rerun['outputs'] if o['attempts'] == 1 and o['kind'] == 'plan'] == ['P1']
    plan_prompt = [text for kind, text in model.prompts if kind == 'produce' and 'node P1' in text][-1]
    assert 'Whole-plan review: add a failing-path test' in plan_prompt
    assert second['verdict'] == 'ok' and second['status'] == 'verified'
    paths = [doc['path'] for doc in second['documents']]
    assert paths[0].endswith('/plan.md') and paths[1].endswith('/p1-export-plan.md')
    written = [e['data'] for e in store.events(sid) if e['type'] == 'plan_written']
    assert {item['workRunId'] for item in written} == {second['runId']}


def test_submit_with_autopilot_then_execute_and_ship_without_git(tmp_path):
    _, runtime, model, executor, sid = build(tmp_path)
    wg.set_autopilot(runtime, sid, True)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        submitted = await tool(runtime, sid, 'work_graph', {'action': 'submit'})
        executed = await tool(runtime, sid, 'work_run', {'phase': 'execute'})
        shipped = await tool(runtime, sid, 'work_ship', {})
        return submitted, executed, shipped

    submitted, executed, shipped = asyncio.run(run())
    assert submitted['status'] == 'approved'
    assert executed['status'] == 'executed' and executed['outputs'][0]['status'] == 'accepted'
    build_prompt = [text for kind, text in model.prompts if kind == 'produce' and '(plan, execute)' in text][0]
    assert 'acceptedDependencySnapshots' in build_prompt and 'artifactId' in build_prompt
    # Not a git repo: the PR file is written, and the run stays `executed` so main can ship again.
    assert shipped['ship']['status'] == 'no_git' and shipped['status'] == 'executed'
    assert shipped['ship']['prFile'].endswith('/pull-request.md')


def test_ship_in_a_git_repository_commits_on_a_local_branch(tmp_path):
    _, runtime, _, executor, sid = build(tmp_path, git=True)
    wg.set_autopilot(runtime, sid, True)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        await tool(runtime, sid, 'work_graph', {'action': 'submit'})
        await tool(runtime, sid, 'work_run', {'phase': 'execute'})
        with pytest.raises(ValueError, match='WORK_REPO_PATH_INVALID'):
            await tool(runtime, sid, 'work_ship', {'repoPath': '../etc'})
        with pytest.raises(ValueError, match='WORK_REPO_PATH_INVALID'):
            await tool(runtime, sid, 'work_ship', {'repoPath': '/etc'})
        return await tool(runtime, sid, 'work_ship', {'repoPath': 'BoxFox-Agent-Box'})

    shipped = asyncio.run(run())
    assert shipped['ship']['status'] == 'local' and shipped['ship']['commit'] == 'abc1234'
    assert shipped['ship']['branch'] == 'boxfox/add-an-export-button'
    commands = [args['command'] for name, args in executor.calls if name == 'terminal_exec']
    # Legacy/touch-set ship stays scoped to repoPath; the only extra read is the isolation probe
    # (W8.A4.3) that decides whether the workspace root itself is the repository.
    probe = 'cd . && t=$(git rev-parse --show-toplevel'
    assert all(command.startswith("cd 'BoxFox-Agent-Box' && ") or command.startswith(probe)
               for command in commands if 'git ' in command)
    # An existing branch is reused, never reset with `-B`; plan artifacts stay out of the commit.
    assert any("git checkout 'boxfox/add-an-export-button' || git checkout -b 'boxfox/add-an-export-button'"
               in command for command in commands)
    assert not any('checkout -B' in command for command in commands)
    assert any(":(exclude).plans/work" in command for command in commands)
    # The PR body file is workspace-relative, and the command runs inside repoPath.
    assert all("--body-file '../.plans/work/" in command for command in commands if 'gh pr create' in command)


def test_execute_needs_approval_without_autopilot(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        with pytest.raises(ValueError, match='WORK_NOT_VERIFIED'):
            await tool(runtime, sid, 'work_graph', {'action': 'submit'})
        await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        with pytest.raises(ValueError, match='WORK_APPROVAL_REQUIRED'):
            await tool(runtime, sid, 'work_run', {'phase': 'execute'})

    asyncio.run(run())


def test_owner_approval_card_unblocks_submit(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        task = asyncio.ensure_future(tool(runtime, sid, 'work_graph', {'action': 'submit'}))
        for _ in range(100):
            if runtime.pending_for(sid):
                break
            await asyncio.sleep(0.01)
        record = runtime.pending_for(sid)[0]
        assert record['workRunId'] == runtime.work_graph.active(sid)['runId']
        runtime.resolve_decision(sid, record['decisionId'], 'approve')
        return await task

    out = asyncio.run(run())
    assert out['status'] == 'approved' and out['decision']['decision'] == 'approved'
    requested = [e['data'] for e in store.events(sid) if e['type'] == 'decision_requested'][-1]
    assert requested['workRunId'] == out['runId']


def test_turning_autopilot_on_answers_a_waiting_approval(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        task = asyncio.ensure_future(tool(runtime, sid, 'work_graph', {'action': 'submit'}))
        for _ in range(100):
            if runtime.pending_for(sid):
                break
            await asyncio.sleep(0.01)
        switched = wg.set_autopilot(runtime, sid, True)
        return switched, await task

    switched, out = asyncio.run(run())
    assert switched['on'] is True and switched['runId'] == out['runId']
    assert out['status'] == 'approved'


def test_research_only_run_has_nothing_to_execute(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)
    node = {'id': 'R1', 'kind': 'research', 'title': 'Vite support', 'goal': 'Does Vite 8 support Node 20?'}

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Vite 8 and Node 20', 'flow': 'research'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [node]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        verified = await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        with pytest.raises(ValueError, match='WORK_REQUIREMENTS_ONLY'):
            await tool(runtime, sid, 'work_graph', {'action': 'submit'})
        return verified

    verified = asyncio.run(run())
    assert verified['status'] == 'verified' and 'Answer the owner' in verified['next']
    assert [doc['path'].rsplit('/', 1)[-1] for doc in verified['documents']] == ['plan.md']


def test_only_the_root_orchestrator_drives_the_engine_and_the_switch_turns_it_off(tmp_path, monkeypatch):
    store, runtime, _, _, sid = build(tmp_path)
    child = dict(store.get(sid), parent_id='parent')

    async def run():
        with pytest.raises(PermissionError, match='WORK_ROOT_ONLY'):
            await runtime.work_tool(child, 'work_graph', {'action': 'status'})
        monkeypatch.setenv(wg.WORK_GRAPH_ENV, 'off')
        with pytest.raises(PermissionError, match='WORK_GRAPH_OFF'):
            await runtime.work_tool(store.get(sid), 'work_graph', {'action': 'create', 'goal': 'anything'})

    asyncio.run(run())


# ------------------------------------------------------------------------------- interview

QUESTIONS = [{'id': 'format', 'question': 'Which format?', 'rationale': 'Changes the exporter',
              'options': [{'label': 'Markdown', 'description': 'Plain .md', 'recommended': True},
                          {'label': 'JSON', 'description': 'Raw events'}]},
             {'question': 'Where is the button?',
              'options': [{'id': 'decide', 'label': 'Header', 'description': 'Top bar'},
                          {'label': 'Menu', 'description': 'Overflow menu'}]}]


def test_normalize_interview_validates_and_renames_reserved_ids():
    questions = HarnessRuntime.normalize_interview({'questions': QUESTIONS})
    assert [q['id'] for q in questions] == ['format', 'q2']
    assert questions[1]['options'][0]['id'] not in ('decide', 'other')
    with pytest.raises(ValueError, match='INTERVIEW_INVALID'):
        HarnessRuntime.normalize_interview({'questions': ['a string']})
    with pytest.raises(ValueError, match='2-4 options'):
        HarnessRuntime.normalize_interview({'questions': [{'question': 'x', 'options': [{'label': 'one'}]}]})


def test_interview_card_collects_answers_other_text_and_delegation(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)

    async def run():
        task = asyncio.ensure_future(runtime.work_tool(store.get(sid), 'interview', {'questions': QUESTIONS}))
        for _ in range(100):
            if runtime.pending_for(sid):
                break
            await asyncio.sleep(0.01)
        record = runtime.pending_for(sid)[0]
        with pytest.raises(DecisionError):
            runtime.resolve_decision(sid, record['decisionId'], 'submit',
                                     answers=[{'questionId': 'nope', 'optionId': 'x'}])
        with pytest.raises(DecisionError):
            runtime.resolve_decision(sid, record['decisionId'], 'submit',
                                     answers=[{'questionId': 'format', 'optionId': 'other'}])
        option = record['questions'][0]['options'][1]['id']
        resolved = runtime.resolve_decision(sid, record['decisionId'], 'submit',
                                            answers=[{'questionId': 'format', 'optionId': option}])
        return resolved, await task

    resolved, out = asyncio.run(run())
    assert resolved['status'] == 'resolved'
    by_id = {item['questionId']: item for item in out['answers']}
    assert by_id['format'] == {'questionId': 'format', 'question': 'Which format?', 'optionId': 'json',
                               'answer': 'JSON', 'decidedBy': 'user'}
    assert by_id['q2']['decidedBy'] == 'agent' and by_id['q2']['recommended'] == 'Header'
    assert 'left q2 to you' in out['message']
    requested = [e['data'] for e in store.events(sid) if e['type'] == 'decision_requested'][-1]
    assert requested['kind'] == 'interview' and len(requested['questions']) == 2
    done = [e['data'] for e in store.events(sid) if e['type'] == 'decision_resolved'][-1]
    assert done['answers'] == out['answers']


def test_interview_other_text_is_a_user_answer():
    question = HarnessRuntime.normalize_interview({'questions': QUESTIONS})[0]
    assert HarnessRuntime.interview_answer(question, {'optionId': 'other', 'text': 'CSV'})['answer'] == 'CSV'
    assert HarnessRuntime.interview_answer(question, {'text': 'CSV'})['decidedBy'] == 'user'
    assert HarnessRuntime.interview_answer(question, {'optionId': 'decide'})['decidedBy'] == 'agent'


def test_interview_answers_are_recorded_on_the_active_run(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)

    async def run():
        created = await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        task = asyncio.ensure_future(runtime.work_tool(store.get(sid), 'interview', {'questions': QUESTIONS[:1]}))
        for _ in range(100):
            if runtime.pending_for(sid):
                break
            await asyncio.sleep(0.01)
        runtime.resolve_decision(sid, runtime.pending_for(sid)[0]['decisionId'], 'decide')
        await task
        return created['runId']

    run_id = asyncio.run(run())
    run = runtime.work_graph.get(run_id)
    assert run['interviews'][0]['answers'][0]['decidedBy'] == 'agent'
    assert 'Owner decisions from the interview' in runtime.work_graph.interview_context(run)


# ------------------------------------------------------------------- prompt, tools, intent

def test_orchestrator_holds_the_work_tools_and_the_groups_cover_them():
    assert set(WORK_TOOLS) <= ORCHESTRATOR_TOOLS
    groups = {group['key']: group['tools'] for group in tool_groups.TOOL_GROUPS}
    # W6.1.3: verify_exec vào nhóm workGraph (công cụ của người phản biện).
    assert groups['workGraph'] == ['work_graph', 'work_run', 'work_ship', 'work_check', 'work_report',
                                  'work_artifact_read', 'verify_exec']
    assert 'interview' in groups['questionsApprovals']
    names = {schema['function']['name'] for schema in SCHEMAS}
    assert set(WORK_TOOLS) <= names


def test_slash_intent_goes_into_the_prompt_block_and_create_consumes_it(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)
    session = store.get(sid)
    wg.set_intent(runtime, session, 'research', 'So sánh Vite 8 và Webpack 6')
    profile = runtime.turn_profile(store.get(sid))
    assert profile['mode'] == 'main'
    assert wg.MARKER in profile['promptBlock'] and 'flow `research`' in profile['promptBlock']
    assert set(WORK_TOOLS) <= set(profile['tools'])

    async def run():
        return await tool(runtime, sid, 'work_graph', {'action': 'create'})

    created = asyncio.run(run())
    assert created['flow'] == 'research'
    assert wg.INTENT_CONFIG_KEY not in store.get(sid)['config']
    assert 'Active run' in runtime.turn_profile(store.get(sid))['promptBlock']


def test_a_legacy_session_without_the_flag_gets_the_work_tools(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)
    config = store.get(sid)['config']
    config.pop('workTools')
    config['tools'] = [name for name in config['tools'] if name not in WORK_TOOLS]
    store.update_config(sid, config)
    assert set(WORK_TOOLS) <= set(runtime.turn_profile(store.get(sid))['tools'])


def test_role_prompts_teach_the_work_graph_contract():
    for role in ('explore', 'plan', 'design', 'build', 'debug', 'research'):
        assert '## Knowledge requests' in ROLES[role].instructions, role
    for role in ('review', 'plan-review', 'research-review'):
        text = ROLES[role].instructions
        assert 'VERDICT: ok' in text and 'Whole-plan review of Work Graph run' in text, role
    assert 'Do NOT call `write_plan` for a Work Graph node' in ROLES['plan'].instructions


# ------------------------------------------------------------------------ tool error bugs

def test_plan_brief_items_are_coerced_and_errors_name_the_field():
    coerce = plan_workflow.PlanWorkflow.coerce_item
    assert coerce('Xuất lịch sử chat')['source'] == {'kind': 'proposed'}
    assert coerce({'text': 'x', 'source': 'Observed'})['source'] == {'kind': 'observed'}
    assert coerce({'text': 'x', 'source': 'proposal', 'why': 'faster'}) == {
        'text': 'x', 'source': {'kind': 'proposed'}, 'why': 'faster', 'reason': 'faster'}
    assert coerce({'text': 'x', 'kind': 'user'})['source'] == {'kind': 'user'}


def test_classify_failure_keeps_the_code_of_a_coded_value_error():
    assert classify_failure(ValueError('PLAN_BRIEF_INVALID: trường goal'))[0] == 'PLAN_BRIEF_INVALID'
    assert classify_failure(ValueError('WORK_NODE_INVALID: x'))[0] == 'WORK_NODE_INVALID'
    assert classify_failure(ValueError('dữ liệu hỏng'))[0] == 'TURN_FAILED_VALUEERROR'


def test_reflection_hint_names_the_tool_code_and_arguments():
    hint = reflection_hint('plan_scope', 'PLAN_BRIEF_INVALID')
    assert '`plan_scope` failed with PLAN_BRIEF_INVALID' in hint and 'required=' in hint
    assert 'debug specialist' not in hint
    assert reflection_hint('no_such_tool').startswith('AUTONOMOUS_DIAGNOSIS: `no_such_tool`')


def test_work_graph_api_view_is_json_serializable(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})

    asyncio.run(run())
    view = runtime.work_graph.view(runtime.work_graph.active(sid))
    assert json.loads(json.dumps(view))['waves'] == [['P1']]
    assert Path(view['nodes'][0]['id']).name == 'E1'


# ------------------------------------------------------------------------ failure paths (review)

def approved_run(runtime, sid):
    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        await tool(runtime, sid, 'work_graph', {'action': 'verify'})
        return await tool(runtime, sid, 'work_graph', {'action': 'submit'})
    return run


def test_a_rejected_execution_node_is_execute_failed_and_retry_reopens_it(tmp_path):
    state = {'fail': True}

    def script(kind, text):
        if kind == 'review' and '(plan, execute)' in text and state['fail']:
            return 'Blocking findings:\n- the export test fails\nVERDICT: revise'
        return ok_script(kind, text)

    _, runtime, _, _, sid = build(tmp_path, script=script)
    wg.set_autopilot(runtime, sid, True)

    async def run():
        await approved_run(runtime, sid)()
        failed = await tool(runtime, sid, 'work_run', {'phase': 'execute', 'maxRounds': 1})
        with pytest.raises(ValueError, match='WORK_EXECUTE_FAILED'):
            await tool(runtime, sid, 'work_run', {'phase': 'execute'})
        state['fail'] = False
        retried = await tool(runtime, sid, 'work_graph', {'action': 'retry', 'nodeIds': ['P1']})
        again = await tool(runtime, sid, 'work_run', {'phase': 'execute'})
        return failed, retried, again

    failed, retried, again = asyncio.run(run())
    assert failed['status'] == 'execute_failed' and failed['outputs'][0]['status'] == 'rejected'
    assert 'action=retry' in failed['next']
    assert retried['status'] == 'approved'
    assert again['status'] == 'executed'


def test_fanout_busy_is_queued_not_a_failed_node(tmp_path, monkeypatch):
    _, runtime, _, _, sid = build(tmp_path)
    monkeypatch.setattr(wg, 'FANOUT_RETRY_PAUSE', 0.0)
    real = runtime.delegate
    calls = {'n': 0}

    async def flaky(session, args, work=None):
        calls['n'] += 1
        if calls['n'] <= 2:
            raise ValueError('FANOUT_BUSY: the box already runs 8 children at the same time')
        return await real(session, args, work=work)

    monkeypatch.setattr(runtime, 'delegate', flaky)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Survey the chat header'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    assert out['outputs'][0]['status'] == 'accepted' and calls['n'] >= 3


def test_an_exhausted_child_budget_leaves_the_node_waiting_for_the_next_call(tmp_path, monkeypatch):
    _, runtime, model, _, sid = build(tmp_path)
    original_budget = wg.WORK_CHILDREN_PER_RUN_CALL
    monkeypatch.setattr(wg, 'WORK_CHILDREN_PER_RUN_CALL', 1)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Survey the chat header'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE]})
        first = await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        monkeypatch.setattr(wg, 'WORK_CHILDREN_PER_RUN_CALL', original_budget)
        second = await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        return first, second

    first, second = asyncio.run(run())
    assert first['budgetExhausted'] is True
    assert first['outputs'][0]['status'] == 'accepted' and first['outputs'][0]['attempts'] == 1
    assert len([p for k,p in model.prompts if k=='produce']) == 1
    assert second['outputs'][0]['status'] == 'accepted'


def test_a_restart_resets_in_flight_stages_and_a_lost_approval_card_can_be_asked_again(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Survey the chat header'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE]})
    asyncio.run(run())
    service = wg.service(runtime)
    stored = service.active(sid)
    stored['nodes'][0]['stages']['produce']['status'] = 'running'
    stored['status'] = 'verifying'
    service.save(stored)

    fresh = wg.WorkGraph(runtime)  # a new process
    recovered = fresh.get(stored['runId'])
    assert recovered['nodes'][0]['stages']['produce']['status'] == 'pending'
    assert recovered['status'] == 'discovering'
    assert recovered['history'][-1]['event'] == 'recovered'


def test_the_off_switch_hides_the_engine_tools_and_the_sop_section(tmp_path, monkeypatch):
    from agentbox.agent_core import runtime as runtime_module
    store, runtime, _, _, sid = build(tmp_path)
    assert 'WORK GRAPH' in runtime_module.orchestrator_guidance()
    assert 'work_run' in runtime.turn_profile(store.get(sid))['tools']
    monkeypatch.setenv(wg.WORK_GRAPH_ENV, 'off')
    tools = runtime.turn_profile(store.get(sid))['tools']
    assert not {'work_graph', 'work_run', 'work_ship'} & set(tools)
    guidance = runtime_module.orchestrator_guidance()
    assert 'WORK GRAPH' not in guidance and 'CORE MULTI-AGENT DELEGATION PROTOCOL' in guidance


def test_an_expired_interview_records_agent_answers_in_the_resolved_event(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)
    questions = runtime.normalize_interview({'questions': QUESTIONS})

    async def run():
        record = {'decisionId': 'iv-x', 'sessionId': sid, 'kind': 'interview', 'questions': questions,
                  'answers': [], 'resolved': False, 'future': asyncio.get_running_loop().create_future()}
        runtime.settle(record, 'decide', 'expired', 'session_cancelled', None)
        return record
    record = asyncio.run(run())
    assert [item['decidedBy'] for item in record['answers']] == ['agent', 'agent']
    resolved = [event for event in store.events(sid) if event['type'] == 'decision_resolved'][-1]
    assert len(resolved['data']['answers']) == 2


def test_a_failed_commit_is_not_recorded_as_shipped(tmp_path):
    _, runtime, _, executor, sid = build(tmp_path, git=True)
    executor.commit_fails = True
    wg.set_autopilot(runtime, sid, True)

    async def run():
        await approved_run(runtime, sid)()
        await tool(runtime, sid, 'work_run', {'phase': 'execute'})
        return await tool(runtime, sid, 'work_ship', {})

    shipped = asyncio.run(run())
    assert shipped['ship']['status'] == 'commit_failed' and shipped['status'] == 'executed'
    commands = [args['command'] for name, args in executor.calls if name == 'terminal_exec']
    assert not any('git push' in command for command in commands)


def test_reviewers_get_a_hard_step_cap_and_a_verdict_wrap_up(tmp_path):
    store, runtime, _, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Survey the chat header'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE | {'risk':'consequential'}]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    children = [store.get(child['session_id']) for child in store.children_of(sid)]
    reviewers = [c for c in children if c['config']['workBinding']['purpose'] == 'review']
    producers = [c for c in children if c['config']['workBinding']['purpose'] == 'produce']
    assert out['outputs'][0]['status'] == 'accepted'
    from agentbox.agent_core import work_budget
    assert reviewers and all(c['config']['maxSteps'] == work_budget.LONG_REVIEW_STEPS for c in reviewers)
    assert producers and all(c['config']['maxSteps'] > wg.REVIEW_MAX_STEPS for c in producers)
    assert 'VERDICT' in wg.wrap_up_note(reviewers[0]) and wg.wrap_up_note(producers[0]) == ''


def test_a_session_with_old_saved_skills_can_still_open_the_work_graph_skill(tmp_path, monkeypatch):
    store, runtime, _, _, sid = build(tmp_path)
    session = store.get(sid)
    session['config']['skills'] = ['planning']  # settings saved before the skill existed
    store.update_config(sid, session['config'])

    async def run():
        return await runtime.dispatch(store.get(sid), 'skill_view', {'id': wg.WORK_SKILL}, 'call-1')
    result = asyncio.run(run())
    assert 'Work Graph' in str(result.get('content') or result)
    assert wg.WORK_SKILL in store.get(sid)['config']['skills']
    monkeypatch.setenv(wg.WORK_GRAPH_ENV, 'off')
    assert not wg.grants_skill(store.get(sid))


def test_plan_writers_get_a_document_sized_output_budget(tmp_path):
    store, runtime, model, _, sid = build(tmp_path)

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    asyncio.run(run())
    children = [store.get(child['session_id']) for child in store.children_of(sid)]
    by_role = {}
    for child in children:
        binding = child['config']['workBinding']
        by_role.setdefault((binding['purpose'], child['role']), []).append(child['config'].get('maxTokens'))
    assert set(by_role[('produce', 'plan')]) == {wg.DOCUMENT_MAX_TOKENS}
    assert set(by_role[('produce', 'explore')]) == {None}
    assert all(value == 16000 for key, values in by_role.items() if key[0] == 'review' for value in values)
    sent = {tokens for kind, text, tokens in model.tokens if kind == 'produce' and 'node P1' in text}
    assert sent == {wg.DOCUMENT_MAX_TOKENS}
    assert {tokens for kind, _, tokens in model.tokens if kind == 'review'} == {16000}


def test_main_keeps_driving_an_active_run_without_the_turn_recap(tmp_path, monkeypatch):
    store, runtime, _, _, sid = build(tmp_path)
    assert not wg.driving(runtime, store.get(sid)), 'no run yet'

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
    asyncio.run(run())
    session = store.get(sid)
    assert wg.driving(runtime, session)
    assert 'Keep this turn going' in wg.service(runtime).prompt_block(session)
    assert not wg.driving(runtime, dict(session, parent_id='parent'))
    monkeypatch.setenv(wg.WORK_GRAPH_ENV, 'off')
    assert not wg.driving(runtime, session)


def test_run_lifetime_counts_calls_children_and_seconds_across_calls(tmp_path):
    """#6457/W6.5.2: `lifetime` là bộ đếm THAM VẤN cả đời run — đo trước, chưa siết trần cứng nào.

    Trần mỗi lời gọi (`WORK_CHILDREN_PER_RUN_CALL`/`WORK_RUN_MAX_SECONDS`) không phải ngân sách suốt
    run, nên tổng đời run phải đọc được ở chính tài liệu run: `work_run` trả `lifetime` và ghi event
    `run_lifetime`. Bộ đếm này không chặn gì; nó chỉ trả lời W6.5.2 bằng số thật.
    """
    store, runtime, model, _, sid = build(tmp_path)

    async def run():
        created = await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button',
                                                          'flow': 'plan'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        first = await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        second = await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        return created['runId'], first, second

    rid, first, second = asyncio.run(run())
    assert first['lifetime']['calls'] == 1, 'mỗi lời gọi work_run đếm một lần'
    assert second['lifetime']['calls'] == 2, 'bộ đếm phải cộng dồn qua các lời gọi, không đặt lại'
    assert second['lifetime']['children'] >= first['lifetime']['children'] >= 1, 'con đã dùng phải cộng dồn'
    assert second['lifetime']['seconds'] >= first['lifetime']['seconds'] > 0, 'giây phải cộng dồn và dương'
    saved = runtime.work_graph.get(rid)
    assert saved['lifetime'] == second['lifetime'], 'số trả về là số đã ghi vào tài liệu run'
    assert 'run_lifetime' in [item['event'] for item in saved['history']]
    # Không chặn: lượt gọi vẫn chạy đủ việc dù bộ đếm đã tích luỹ.
    assert [node['id'] for node in saved['nodes']] == ['E1', 'P1']


def test_the_model_can_discover_the_resolve_action(tmp_path):
    """#6456(b): hàng rào chỉ mở được nếu mô hình BIẾT có đường mở.

    Đo lượt 14–16: cả ba lượt kiểm đỏ đều kẹt ở `inputConflicts` và mô hình không có cách nào gỡ.
    Engine nhận `action=resolve`, nhưng hợp đồng công cụ (enum + mô tả) và câu `next` mới là chỗ mô
    hình đọc — thiếu hai chỗ đó thì đường mở coi như không tồn tại.
    """
    from agentbox.agent_core import tool_contracts

    schema = next(item['function'] for item in tool_contracts.SCHEMAS
                  if item['function']['name'] == 'work_graph')
    assert 'resolve' in schema['parameters']['properties']['action']['enum']
    assert 'resolve clears the recorded input conflicts' in schema['description']

    _, runtime, _, _, sid = build(tmp_path)
    conflict = {'id': 'A1', 'requirement': 'Keep the exact owner constraints', 'evidence': 'reviewer evidence'}
    state = {'status': 'revise', 'attempts': 1, 'rounds': [], 'output': 'draft text', 'outputChars': 10,
             'feedback': '', 'knowledge': [], 'error': None, 'startedAt': None, 'finishedAt': None,
             'artifact': {'artifactId': 'a-1'}, 'inputConflicts': [conflict]}

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button', 'flow': 'plan'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        document = runtime.work_graph.get(runtime.work_graph.active(sid)['runId'])
        document['nodes'][0]['stages']['produce'] = state
        runtime.work_graph.save(document)
        return runtime.work_graph.next_step(runtime.work_graph.get(document['runId']))

    guidance = asyncio.run(run())
    assert 'action=resolve' in guidance and 'action=update' in guidance
