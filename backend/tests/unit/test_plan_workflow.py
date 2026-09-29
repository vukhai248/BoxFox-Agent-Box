"""Plan workflow contracts; fixtures never count as live model quality evidence."""
import asyncio
import hashlib
import json
import pytest
from agentbox.agent_core import plan_workflow as pw
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

class Executor:
    async def execute(self, name, args, sid):
        return {'content': 'fixture contents'}
    async def cleanup(self, sid):
        pass

class Model:
    async def complete(self, messages, tools, route, **kwargs):
        return {'choices': [{'message': {'content': 'Đã lưu tiến độ.'}, 'finish_reason': 'stop'}]}

@pytest.fixture
def env(tmp_path):
    store = SessionStore(tmp_path / 'plan.sqlite')
    rt = HarnessRuntime(store, Executor(), Model())
    session = rt.create({'skills': []})
    flow = pw.service(rt)
    run = flow.set_mode(rt, session['id'], True, goal='Tạo app agent tổng hợp hồ sơ y tế')['run']
    yield rt, flow, run
    store.close()

def scope(rt, flow, run, action, **kwargs):
    return flow.scope(rt, rt.store.get(run['sessionId']), {'action': action, 'revision': flow.get(run['runId'])['revision'], **kwargs})

def fill(rt, flow, run):
    patch = {k: {'text': 'Đề xuất có căn cứ cho ' + k, 'source': {'kind': 'proposed'},
                 'reason': 'Cần hiệu chỉnh theo dữ liệu và chi phí thực tế.'} for k in pw.FIELDS if k != 'goal'}
    run = scope(rt, flow, run, 'update', brief=patch)
    run = scope(rt, flow, run, 'confirm')
    return flow.answers(run['runId'], {'revision': run['revision'], 'invocationId': 'confirm',
        'answers': [{'questionId': run['questions'][-1]['id'], 'optionId': 'confirm'}]})['run']

def ready(rt, flow, run):
    run = fill(rt, flow, run)
    flow.written(run, {'identity': 'clinical', 'version': 1, 'relativePath': '.plans/v1-clinical.md',
                       'contentHash': hashlib.sha256('Tiếng Việt có dấu'.encode()).hexdigest()}, [])
    run = flow.get(run['runId'])
    report = {'rubric': pw.RUBRIC, 'findings': [], 'dimensions': {k: {'status': 'pass', 'evidence': 'Specific independently checked evidence for ' + k} for k in pw.DIMENSIONS}}
    return flow.reviewed(run, report, 'ok', 'critic')

def test_empty_mode_has_no_run_or_turn(env):
    rt, flow, run = env
    other = rt.create({'skills': []})
    value = flow.set_mode(rt, other['id'], True)
    assert value['run'] is None and flow.runs(other['id']) == []
    assert other['id'] not in rt.tasks

def test_incomplete_cannot_write(env):
    rt, flow, run = env
    with pytest.raises(ValueError, match='BRIEF_INCOMPLETE'):
        flow.validate_write(rt, rt.store.get(run['sessionId']), {'runId': run['runId'], 'briefRevision': 1})

def test_model_cannot_forge_user_or_observed_sources(env):
    rt, flow, run = env
    for source, code in [({'kind': 'user', 'quote': 'Offline is mandatory'}, 'USER_PROVENANCE'),
                         ({'kind': 'observed', 'ref': 'missing.py'}, 'EVIDENCE_REQUIRED')]:
        with pytest.raises(ValueError, match=code):
            scope(rt, flow, run, 'update', brief={'scope': {'text': 'offline', 'source': source}})

def test_confirmation_is_user_action_and_traceability_required(env):
    rt, flow, run = env
    run = fill(rt, flow, run)
    args = {'runId': run['runId'], 'briefRevision': run['briefRevision']}
    with pytest.raises(ValueError, match='TRACEABILITY_REQUIRED'):
        flow.validate_write(rt, rt.store.get(run['sessionId']), args)
    matrix = [{'requirement': key, 'decision': 'D1', 'milestone': 'M1', 'check': 'meaningful check'} for key in pw.FIELDS]
    assert flow.validate_write(rt, rt.store.get(run['sessionId']), args | {'traceability': matrix})['runId'] == run['runId']

def test_partial_answers_wait_and_duplicate_stale_conflict(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id': k, 'field': k, 'text': k} for k in ['users','data']])
    body = {'revision': run['revision'], 'invocationId': 'answer-one', 'answers': [{'questionId': 'users', 'text': 'Bác sĩ'}]}
    first = flow.answers(run['runId'], body)
    assert first['run']['status'] == 'needs_user' and first['queued'] is False
    assert flow.answers(run['runId'], body) == first
    assert not flow.db.execute('SELECT * FROM plan_continuations').fetchall()
    with pytest.raises(ValueError, match='REVISION_CONFLICT'):
        flow.answers(run['runId'], body | {'invocationId': 'different'})
    with pytest.raises(ValueError, match='INVOCATION_CONFLICT'):
        flow.answers(run['runId'], body | {'answers': [{'questionId': 'data', 'text': 'PDF'}]})

def test_transaction_rolls_back_invalid_second_answer(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id': 'users', 'field': 'users', 'text': 'Ai?'}])
    with pytest.raises(ValueError, match='QUESTION_UNKNOWN'):
        flow.answers(run['runId'], {'revision': run['revision'], 'invocationId': 'bad', 'answers': [
            {'questionId': 'users', 'text': 'Bác sĩ'}, {'questionId': 'missing', 'text': 'PDF'}]})
    assert flow.get(run['runId']) == {k: v for k, v in run.items() if k != 'missing'}
    assert not flow.db.execute('SELECT * FROM plan_run_admissions').fetchall()

def test_answers_survive_store_restart(env, tmp_path):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id': 'users', 'field': 'users', 'text': 'Ai?'}])
    result = flow.answers(run['runId'], {'revision': run['revision'], 'invocationId': 'saved',
        'answers': [{'questionId': 'users', 'text': 'Bác sĩ tiếng Việt'}]})
    another_store = SessionStore(tmp_path / 'plan.sqlite')
    another = pw.PlanWorkflow(another_store)
    assert another.get(run['runId']) == result['run']
    assert len(another.db.execute("SELECT * FROM plan_continuations WHERE state='pending'").fetchall()) == 1
    another_store.close()

@pytest.mark.parametrize('tool', ['terminal_exec','file_write','file_edit_block','design_write','design_branch'])
def test_dispatch_blocks_direct_write_tools(env, tool):
    rt, flow, run = env
    async def check():
        with pytest.raises(PermissionError, match='PLAN_EXECUTION_BLOCKED'):
            await rt.dispatch(rt.store.get(run['sessionId']), tool, {}, 'call')
    asyncio.run(check())

def test_delegation_and_ancestor_binding_cannot_bypass(env):
    rt, flow, run = env
    root = rt.store.get(run['sessionId'])
    child = rt.store.create(root['config'], role='plan', parent_id=root['id'])
    assert 'write_plan' not in pw.allowed_tools(rt, child)
    async def check():
        with pytest.raises(PermissionError, match='PLAN_DELEGATE_BLOCKED'):
            await rt.delegate(root, {'role': 'build', 'goal': 'implement'})
        with pytest.raises(ValueError, match='PLAN_EXECUTION_BLOCKED'):
            await rt.submit(root['id'], '/build implement', invocation_id='bypass')
    asyncio.run(check())

def test_prompt_overrides_custom_identity_and_disabled_skill(env):
    rt, flow, run = env
    block = pw.prompt_block(rt, rt.store.get(run['sessionId']))
    assert pw.MARKER in block and 'Mandatory planning procedure' in block and 'Vietnamese' in block
    assert 'plan_scope' in rt.turn_profile(rt.store.get(run['sessionId']))['tools']

def test_review_requires_every_dimension_and_no_compensating_score(env):
    rt, flow, run = env
    report = {'rubric': pw.RUBRIC, 'findings': [], 'dimensions': {k: {'status': 'pass', 'evidence': 'Specific evidence for this dimension'} for k in pw.DIMENSIONS}}
    assert flow.parse_review('PLAN_REVIEW_JSON: ' + json.dumps(report), run, 'ok') == report
    report['dimensions']['ai']['status'] = 'fail'
    with pytest.raises(ValueError, match='VERDICT_MISMATCH'):
        flow.parse_review('PLAN_REVIEW_JSON: ' + json.dumps(report), run, 'ok')
    with pytest.raises(ValueError, match='REVIEW_REQUIRED'):
        flow.parse_review('VERDICT: ok', run, 'ok')

def test_ready_invalidated_by_new_requirement(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    assert flow.approval_blocked('clinical', 1) is None
    flow.note_user(run, 'Chuyển sang chỉ xử lý dữ liệu mẫu offline')
    assert flow.approval_blocked('clinical', 1).startswith('PLAN_NOT_READY')

def test_approval_stores_only_execute_is_separate_and_idempotent(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    # Remove earlier brief continuation, which a real root turn has consumed.
    flow.db.execute('DELETE FROM plan_continuations'); flow.db.commit()
    run = scope(rt, flow, run, 'approval')
    result = flow.answers(run['runId'], {'revision': run['revision'], 'invocationId': 'approve',
        'answers': [{'questionId': run['questions'][-1]['id'], 'optionId': 'approve'}]})
    assert result['queued'] is False and result['run']['phase'] == 'approved'
    assert not rt.tasks and not flow.db.execute('SELECT * FROM plan_continuations').fetchall()
    run = result['run']; body = run['document'] | {'revision': run['revision'], 'invocationId': 'execute'}
    first = flow.execute(run, body)
    assert flow.execute(flow.get(run['runId']), body) == first
    second = flow.execute(flow.get(run['runId']), body | {'revision': first['run']['revision'], 'invocationId': 'execute-2'})
    assert second['duplicate'] and not second['queued']
    assert len(flow.db.execute('SELECT * FROM plan_continuations').fetchall()) == 1
    assert pw.mode(rt.store.get(run['sessionId']))['on'] is False

def test_review_two_repairs_then_block(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    for i in range(3):
        run = flow.reviewed(run, {'dimensions': {}}, 'revise', 'critic')
    assert run['status'] == 'blocked' and run['reviseRounds'] == 3
    with pytest.raises(ValueError, match='RUN_BLOCKED'):
        flow.validate_write(rt, rt.store.get(run['sessionId']), {'runId': run['runId'], 'briefRevision': run['briefRevision']})

def test_pause_keeps_questions(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id': 'users', 'field': 'users', 'text': 'Ai?'}])
    flow.set_mode(rt, run['sessionId'], False)
    paused = flow.get(run['runId'])
    assert paused['status'] == 'paused' and paused['questions'] == run['questions']
    assert flow.set_mode(rt, run['sessionId'], True)['run']['status'] == 'needs_user'


def test_superseded_document_cannot_escape_to_legacy_gate(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    newer = run['document'] | {'version':2,'contentHash':'new-hash'}
    flow.written(run, newer, [])
    assert flow.for_document('clinical',1)['runId'] == run['runId']
    assert flow.approval_blocked('clinical',1).startswith('PLAN_REVIEW_STALE')

def test_explanation_does_not_invalidate_review(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    updated = flow.note_user(run, 'Giải thích tại sao chọn phương án này?')
    assert updated['briefRevision'] == run['briefRevision'] and updated['review'] == run['review']

def test_model_cannot_confirm_using_owner_text_itself(env):
    rt, flow, run = env
    run = fill(rt, flow, run)
    run = flow.note_user(run, 'Thêm chức năng so sánh hồ sơ')
    run = scope(rt, flow, run, 'confirm')
    flow.note_user(run, 'ok')
    with pytest.raises(ValueError, match='PLAN_USER_ACTION_REQUIRED'):
        scope(rt, flow, run, 'answer', answers=[{'questionId':run['questions'][-1]['id'],'text':'ok','optionId':'confirm'}])

def test_language_signal_is_advisory_not_a_block():
    text = '# Ke hoach\nMuc tieu, pham vi, nguoi dung, du lieu, nghiem thu.'
    assert pw.language_signal(text,'vi')['state'] == 'suspected_missing_accents'
    assert pw.language_signal('```\n'+text+'\n```','vi')['state'] == 'no_signal'
    assert pw.language_signal(text,'en')['state'] == 'not_applicable'
    assert pw.language_signal('Kế hoạch có mục tiêu, phạm vi và dữ liệu rõ ràng.','vi')['state'] == 'no_signal'

def test_blocking_semantic_finding_cannot_hide_behind_all_passes(env):
    rt, flow, run = env
    report = {'rubric':pw.RUBRIC,'dimensions':{key:{'status':'pass','evidence':'Detailed evidence for this dimension'} for key in pw.DIMENSIONS},
              'findings':[{'severity':'high','blocking':True,'evidence':'Medical summaries lack a dataset to establish correctness.'}]}
    with pytest.raises(ValueError,match='VERDICT_MISMATCH'):
        flow.parse_review('PLAN_REVIEW_JSON: '+json.dumps(report),run,'ok')


def test_interview_ends_compute_turn_without_wait_future(env):
    rt, flow, run = env
    class InterviewModel:
        count = 0
        async def complete(self, messages, tools, route, **kwargs):
            self.count += 1
            current = flow.get(run['runId'])
            assert 'file_write' not in [t['function']['name'] for t in tools]
            return {'choices':[{'message':{'content':'Cần làm rõ dữ liệu.', 'tool_calls':[{
                'id':'q','type':'function','function':{'name':'plan_scope','arguments':json.dumps({
                'action':'ask','revision':current['revision'],'questions':[{'id':'data','field':'data','text':'Dữ liệu nào?'}]})}}]},'finish_reason':'tool_calls'}]}
    model = rt.client = InterviewModel()
    async def check():
        await rt.submit(run['sessionId'],'Tiếp tục khảo sát',invocation_id='interview')
        await asyncio.wait_for(rt.tasks[run['sessionId']],timeout=5)
        assert model.count == 1 and not rt.pending
        assert flow.get(run['runId'])['status'] == 'needs_user'
        assert rt.store.get(run['sessionId'])['status'] == 'completed'
    asyncio.run(check())

def test_busy_plan_status_does_not_queue_model_steer(env):
    rt, flow, run = env
    rt.store.save(run['sessionId'], rt.store.get(run['sessionId'])['messages'], 'running')
    async def check():
        value = await rt.submit(run['sessionId'], '/plan status', invocation_id='status')
        assert value.get('output')
        assert rt.store.pending_steer_count(run['sessionId']) == 0
        assert not rt.tasks
    asyncio.run(check())

def test_recovery_marks_admitted_interrupted_turn_but_does_not_replay(env):
    rt, flow, run = env
    rt.store.save(run['sessionId'], rt.store.get(run['sessionId'])['messages'], 'interrupted')
    flow.recover()
    assert flow.get(run['runId'])['status'] == 'blocked' and not rt.tasks

def test_pending_answer_can_be_pumped_once_after_restart(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id':'users','field':'users','text':'Ai?'}])
    flow.answers(run['runId'], {'revision':run['revision'],'invocationId':'answer',
                  'answers':[{'questionId':'users','text':'Bác sĩ'}]})
    rt.store.save(run['sessionId'],rt.store.get(run['sessionId'])['messages'],'interrupted')
    flow.recover()
    assert flow.get(run['runId'])['status'] == 'active'
    async def check():
        await pw.pump(rt)
        task = rt.tasks[run['sessionId']]
        await task
        turns = rt.store.get(run['sessionId'])['turn_count']
        await pw.pump(rt)
        assert rt.store.get(run['sessionId'])['turn_count'] == turns == 1
    asyncio.run(check())


def test_clear_small_code_change_can_skip_interview_with_actual_evidence(env):
    rt, flow, original = env
    other = rt.create({'skills':[]})
    run = flow.set_mode(rt,other['id'],True,goal='Fix None input in normalise_name in app.py; keep existing behavior otherwise')['run']
    rt.store.emit(run['sessionId'],'tool_end',{'name':'file_read','args':{'path':'app.py'},'result':{'content':'def normalise_name(value): return value.strip()'}})
    run = scope(rt,flow,run,'update',profile='task',evidence=['app.py'],brief={
        'scope':{'text':'Handle None only','source':{'kind':'user','quote':'Fix None input'}},
        'success':{'text':'None returns an empty string; existing tests keep passing','source':{'kind':'proposed'},'reason':'Acceptance directly checks the bounded behavior change.'}})
    matrix=[{'requirement':k,'decision':'D1','milestone':'M1: edit app.py','check':'pytest test_normalise.py'} for k in ['goal','scope','success']]
    assert flow.validate_write(rt,rt.store.get(run['sessionId']),{'runId':run['runId'],'briefRevision':run['briefRevision'],'traceability':matrix})
    assert not run['questions'] and run['confirmedBriefRevision'] is None


@pytest.mark.parametrize('count,reason,expected', [
    (1, 'UPSTREAM_HTTP_502', 'SLOT_PROBE'),
    (2, 'UPSTREAM_HTTP_502', 'PLAN_REVIEW_RETRY_EXHAUSTED'),
    (1, 'CHILD_MAX_STEPS', 'PLAN_REVIEW_UNEVALUATED'),
])
def test_reviewer_failure_gets_only_one_provider_retry(env, monkeypatch, count, reason, expected):
    rt, flow, run = env
    run = ready(rt, flow, run)
    root = rt.store.get(run['sessionId'])
    rt.store.emit(root['id'], 'plan_written', run['document'])
    for _ in range(count):
        child = rt.create({'skills': []}, parent_id=root['id'], role='plan-review')
        child['config']['reviewTarget'] = run['document'] | {'kind': 'plan'}
        rt.store.update_config(child['id'], child['config'])
        rt.store.child_start(child['id'], root['id'], 1, 1, 'plan-review', 'review exact plan')
        rt.store.child_finish(child['id'], 'failed', reason=reason)
    async def slot_probe(parent_id):
        raise ValueError('SLOT_PROBE')
    monkeypatch.setattr(rt, 'acquire_child_slot', slot_probe)
    async def check():
        with pytest.raises(ValueError, match=expected):
            await rt.delegate(root, {'role': 'plan-review', 'goal': 'Review exact plan',
                'reviewTarget': {'kind': 'plan', 'identity': 'clinical', 'version': 1}})
    asyncio.run(check())


def test_chat_explanation_is_not_an_answer_to_pending_approval(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    flow.db.execute('DELETE FROM plan_continuations'); flow.db.commit()
    run = scope(rt, flow, run, 'approval')
    async def check():
        await rt.submit(run['sessionId'], 'Giải thích tại sao chọn phương án này?', invocation_id='explain')
        await rt.tasks[run['sessionId']]
        current = flow.get(run['runId'])
        assert current['briefRevision'] == run['briefRevision']
        assert current['review'] == run['review']
        assert current['questions'][-1]['status'] == 'open' and current['status'] == 'needs_user'
        assert not rt.store.plan_review('clinical', 1)
    asyncio.run(check())
