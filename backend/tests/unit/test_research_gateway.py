"""Research qua dispatch thật, principal riêng và negative controls không model/network."""
import asyncio
import copy

import pytest

from agentbox.agent_core import research_gateway as gateway
from agentbox.agent_core.research_owner import REPORT_SCHEMA
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class Executor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid, **kwargs):
        self.calls.append((name, copy.deepcopy(args), sid))
        return {'content': 'fixture'}

    async def cleanup(self, sid):
        pass


class NoModel:
    async def complete(self, *args, **kwargs):
        raise AssertionError('no model spend authorized')


def request():
    return {'schema': gateway.SCHEMA, 'goal': 'Find independent evidence for the decision.',
            'decisionContext': 'Compare uncertainty before deciding.', 'questions': ['What is known?'],
            'constraints': ['No network experiment or live spend.'], 'inputRefs': [],
            'desiredOutput': 'Versioned evidence report', 'freshnessRequirement': 'as-of request',
            'permissionEnvelopeRef': None, 'allocationRef': None, 'consentRef': None}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_WORK_GRAPH', 'off')
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, Executor(), NoModel())
    # Fixture offline: adapter giá sống của main không được gọi bởi unit tests gateway.
    monkeypatch.setattr(runtime, 'prepare_research_admission', None, raising=False)
    monkeypatch.setattr(runtime, 'research_admission', None, raising=False)
    root = runtime.create({'skills': []})
    yield runtime, root
    for task in runtime.tasks.values():
        task.cancel()
    store.close()


def dispatch(rt, actor, name, args):
    return asyncio.run(rt.dispatch(rt.store.get(actor['id']), name, args))


def submit(pair, invocation='submit-1'):
    runtime, root = pair
    receipt = dispatch(runtime, root, 'research_job_submit', {'request': request(), 'invocationId': invocation})
    return receipt, runtime.store.get(receipt['ownerControllerId'])


def report(receipt, lead):
    return {'schema': REPORT_SCHEMA, 'authoredBy': 'research-lead',
            'questionState': {'status': 'partial', 'summary': 'Published evidence with remaining uncertainty.'},
            'evidenceRefs': [{'artifactId': receipt['researchJobId'], 'version': 1, 'contentHash': 'a' * 64}],
            'uncertainty': ['Fixture does not establish a live-world conclusion.'],
            'provenance': {'method': 'existing Research engine', 'runId': receipt['researchJobId'],
                           'ownerId': lead['id'], 'controllerId': lead['id']}}


def publish_args(receipt, lead):
    return {'jobId': receipt['researchJobId'], 'expectedRevision': receipt['revision'], 'report': report(receipt, lead)}


def dossier(runtime, receipt, lead):
    runtime.store.record_dossier(lead['id'], receipt['researchJobId'], 1, '.research/fixture/report.md',
                                 content_hash='a' * 64, quality_ok=True)


def control_args(receipt, action='cancel', **changes):
    args = {'jobId': receipt['researchJobId'], 'expectedRevision': receipt['revision'],
            'invocationId': 'control-1', 'action': action, 'reason': 'Observed gap or owner control.'}
    args.update(changes)
    return args


def test_real_engine_creates_separate_owner_not_main_and_replays_submit(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    assert receipt['state'] == 'needs_consent'
    assert lead['id'] != root['id'] and lead['role'] == 'research-lead'
    assert runtime.store.research_job(receipt['researchJobId'])['session_id'] == lead['id']
    assert lead['config']['research']['researchId'] == receipt['researchJobId']
    assert gateway.service(runtime).ownership.get(receipt['researchJobId'])['ownerId'] == lead['id']
    assert 'file_write' not in lead['config']['tools']
    assert not runtime.tasks
    assert submit(rt)[0] == receipt


@pytest.mark.parametrize('name,args', [
    ('source_add', {'url': 'https://example.com', 'excerpt': 'forged'}),
    ('source_verify', {'researchId': 'anything'}),
    ('research_update', {'finding': 'Main verdict overwrite'}),
    ('research_verify', {'verdict': 'ok'}),
    ('dossier_write', {'researchId': 'anything'}),
    ('file_read', {'path': '.research/private/report.md'}),
    ('file_write', {'path': '.research/private/report.md', 'content': 'forged'}),
    ('file_edit_block', {'path': '.research/private/report.md', 'replacement': 'forged'}),
])
def test_main_dispatch_cannot_edit_sources_dossiers_or_verdicts(rt, name, args):
    runtime, root = rt
    submit(rt)
    before = len(runtime.executor.calls)
    with pytest.raises(PermissionError, match='RESEARCH_MAIN_READ_ONLY'):
        dispatch(runtime, root, name, args)
    assert len(runtime.executor.calls) == before


def test_peer_cannot_read_control_publish_or_mutate(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    peer = runtime.create({'skills': []}, role='research', parent_id=root['id'])
    for name, args in [('research_job_get', {'jobId': receipt['researchJobId']}),
                       ('research_job_control', control_args(receipt)),
                       ('research_job_publish', publish_args(receipt, lead)),
                       ('source_add', {'url': 'https://example.com'})]:
        with pytest.raises(PermissionError, match='RESEARCH_CONTROL_FORBIDDEN'):
            dispatch(runtime, peer, name, args)


def test_lead_has_no_general_spawn_authority_and_worker_no_peer_controls(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    with pytest.raises(PermissionError, match='RESEARCH_DELEGATE_FORBIDDEN'):
        dispatch(runtime, lead, 'delegate_task', {'role': 'build', 'goal': 'Edit source'})
    worker = runtime.create({'skills': []}, role='research', parent_id=lead['id'])
    for name in ('cancel_child', 'task_send', 'delegate_task'):
        with pytest.raises(PermissionError, match='RESEARCH_WORKER_CONTROL_FORBIDDEN'):
            dispatch(runtime, worker, name, {'sessionId': lead['id']})


def test_sanitized_result_contains_only_published_immutable_report(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    assert dispatch(runtime, root, 'research_job_result', {'jobId': receipt['researchJobId']})['reports'] == []
    dossier(runtime, receipt, lead)
    result = dispatch(runtime, lead, 'research_job_publish', publish_args(receipt, lead))
    published = dispatch(runtime, root, 'research_job_result', {'jobId': receipt['researchJobId']})
    assert published['reports'][0]['contentHash'] == result['contentHash']
    assert published['reports'][0]['report'] == report(receipt, lead)
    sanitized = dispatch(runtime, root, 'research_job_get', {'jobId': receipt['researchJobId']})
    assert not set(sanitized) & {'intent', 'children', 'controls', 'sourceLedger', 'dossier'}
    assert sanitized['revision'] == 2
    with pytest.raises(PermissionError, match='RESEARCH_CONTROL_FORBIDDEN'):
        dispatch(runtime, root, 'research_job_publish', publish_args(receipt, lead))


@pytest.mark.parametrize('field', ['runId', 'ownerId', 'controllerId'])
def test_forged_report_provenance_denied(rt, field):
    runtime, _root = rt
    receipt, lead = submit(rt)
    dossier(runtime, receipt, lead)
    args = publish_args(receipt, lead)
    args['report']['provenance'][field] = 'forged-identity'
    with pytest.raises(ValueError, match='RESEARCH_REPORT_PROVENANCE'):
        dispatch(runtime, lead, 'research_job_publish', args)


def test_report_requires_real_bound_dossier_hash(rt):
    runtime, _root = rt
    receipt, lead = submit(rt)
    with pytest.raises(ValueError, match='RESEARCH_REPORT_PROVENANCE'):
        dispatch(runtime, lead, 'research_job_publish', publish_args(receipt, lead))
    dossier(runtime, receipt, lead)
    args = publish_args(receipt, lead)
    args['report']['evidenceRefs'][0]['contentHash'] = 'b' * 64
    with pytest.raises(ValueError, match='RESEARCH_REPORT_PROVENANCE'):
        dispatch(runtime, lead, 'research_job_publish', args)


def test_cancel_stale_revision_and_late_worker_writes_denied(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    cancelled = dispatch(runtime, root, 'research_job_control', control_args(receipt))
    assert cancelled['state'] == 'cancelled' and cancelled['revision'] == 2
    assert dispatch(runtime, root, 'research_job_control', control_args(receipt)) == cancelled
    with pytest.raises(ValueError, match='RESEARCH_REVISION_CONFLICT'):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, invocationId='new-control'))
    worker = runtime.create({'skills': []}, role='research', parent_id=lead['id'])
    with pytest.raises(PermissionError, match='RESEARCH_JOB_STOPPED'):
        dispatch(runtime, worker, 'source_add', {})
    with pytest.raises(ValueError, match='RESEARCH_JOB_STOPPED'):
        dispatch(runtime, lead, 'research_job_publish', {**publish_args(receipt, lead), 'expectedRevision': 2})


def test_unadmitted_job_keeps_records_readable_and_spend_blocked(rt):
    """Không còn công tắc: bài này chốt trạng thái chưa consent vẫn đọc được và không tiêu gì."""
    runtime, root = rt
    receipt, lead = submit(rt)
    assert dispatch(runtime, root, 'research_job_get', {'jobId': receipt['researchJobId']})['state'] == 'needs_consent'
    assert dispatch(runtime, root, 'research_job_result', {'jobId': receipt['researchJobId']})['reports'] == []
    with pytest.raises(ValueError, match='RESEARCH_NEEDS_CONSENT'):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
    with pytest.raises(PermissionError, match='RESEARCH_NEEDS_CONSENT'):
        dispatch(runtime, lead, 'delegate_task', {'role': 'research', 'goal': 'Find evidence'})
    with pytest.raises(PermissionError, match='RESEARCH_MAIN_READ_ONLY'):
        dispatch(runtime, root, 'dossier_write', {})


def test_strict_ownership_creation_and_actor_required(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    owner = gateway.service(runtime).ownership
    with pytest.raises(ValueError, match='RESEARCH_CREATION_FORBIDDEN'):
        owner.assign('unknown-run', lead['id'], lead['id'], {'authoredBy': 'main', 'text': 'fake'}, 'fake', actor_id=root['id'], creation_root_id=root['id'])
    rev = owner.get(receipt['researchJobId'])['revision']
    for operation in (lambda: owner.release(receipt['researchJobId'], 'reason', rev),
                      lambda: owner.handoff(receipt['researchJobId'], root['id'], 'reason', rev),
                      lambda: owner.record_intent(receipt['researchJobId'], {'authoredBy': 'research-lead', 'text': 'fake'}, rev, actor_id=root['id'])):
        with pytest.raises(ValueError, match='RESEARCH_CONTROL_FORBIDDEN'):
            operation()
    owner.release(receipt['researchJobId'], 'no longer needed', rev, actor_id=lead['id'])
    with pytest.raises(ValueError, match='RESEARCH_OWNERSHIP_RELEASED'):
        dispatch(runtime, lead, 'research_job_publish', publish_args(receipt, lead))


def test_resume_no_consent_is_blocked_not_fabricated_from_refs(rt):
    runtime, root = rt
    receipt, _lead = submit(rt)
    with pytest.raises(ValueError, match='RESEARCH_NEEDS_CONSENT'):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
    assert not runtime.tasks


def test_legacy_research_id_in_config_does_not_reopen_the_main_tool_path(rt):
    """Bề mặt 7 đã xoá: nhánh `researchId` legacy không còn là cửa sau cho main."""
    runtime, root = rt
    runtime.store.research_job_save('legacy-run', root['id'], {'questions': []})
    config = root['config']
    config['research'] = {'researchId': 'legacy-run'}
    runtime.store.update_config(root['id'], config)
    with pytest.raises(PermissionError, match='RESEARCH_MAIN_READ_ONLY'):
        gateway.guard_tool(runtime, runtime.store.get(root['id']), 'source_add', {})
    assert not gateway._exists(runtime.store)
    assert runtime.store.research_job('legacy-run')['session_id'] == root['id']


def test_profile_exposes_gateway_tools_and_hides_internal_ones(rt):
    from agentbox.agent_core.tool_contracts import schemas_for
    runtime, root = rt
    schemas = schemas_for(runtime.turn_profile(root)['tools'])
    names = {s['function']['name'] for s in schemas}
    assert gateway.GATEWAY_TOOLS <= names
    assert len(schemas) == len(names)
    intake = next(s for s in schemas if s['function']['name'] == 'research_job_submit')
    assert set(intake['function']['parameters']['properties']['request']['required']) == set(request())
    assert not names & (gateway.INTERNAL_TOOLS | {gateway.PUBLISH_TOOL})
    submit(rt)
    names = {s['function']['name'] for s in schemas_for(runtime.turn_profile(runtime.store.get(root['id']))['tools'])}
    assert {'research_job_get', 'research_job_result', 'research_job_control'} <= names
    assert not names & (gateway.INTERNAL_TOOLS | {gateway.PUBLISH_TOOL})


def test_root_stop_reaches_independent_controller_and_preserves_receipts(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    asyncio.run(runtime.stop(root['id']))
    fresh = dispatch(runtime, root, 'research_job_get', {'jobId': receipt['researchJobId']})
    assert fresh['state'] == fresh['engineState'] == 'cancelled'
    with pytest.raises(ValueError, match='RESEARCH_JOB_STOPPED'):
        dispatch(runtime, root, 'research_job_control', control_args(fresh, 'resume'))


def test_gap_control_is_data_not_verdict_or_grant(rt):
    import json
    runtime, root = rt
    receipt, _lead = submit(rt)
    args = control_args(receipt, 'request_revision', inputRefs=['source-gap-ref'],
                        constraintPatch={'constraints': ['Require independent critique.']})
    new = dispatch(runtime, root, 'research_job_control', args)
    row = gateway._binding(runtime.store, run_id=receipt['researchJobId'])
    updated = json.loads(row['request_json'])
    assert 'Require independent critique.' in updated['constraints']
    assert 'source-gap-ref' in updated['inputRefs']
    assert updated['questions'][-1].startswith('Gap for Research to assess:')
    assert updated['consentRef'] is None and new['state'] == 'needs_consent'
    with pytest.raises(ValueError, match='unsupported fields'):
        dispatch(runtime, root, 'research_job_control', control_args(new, 'request_revision',
            invocationId='bad-gap', constraintPatch={'verdict': 'verified'}))


def test_real_controller_turn_and_worker_dispatch_use_existing_kernel(rt):
    import json
    runtime, root = rt

    class ScriptedModel:
        def __init__(self):
            self.responses = iter([
                {'choices': [{'message': {'content': '', 'tool_calls': [{'id': 'worker-call',
                    'type': 'function', 'function': {'name': 'delegate_task', 'arguments': json.dumps({
                        'role': 'research', 'goal': 'Find evidence within the question scope.',
                        'questionId': 'q1', 'wait': True})}}]}, 'finish_reason': 'tool_calls'}]},
                {'choices': [{'message': {'content': 'Worker evidence remains uncertain.'}, 'finish_reason': 'stop'}]},
                {'choices': [{'message': {'content': 'Lead synthesis, not a verified publication.'}, 'finish_reason': 'stop'}]},
            ])
            self.requests = []

        async def complete(self, messages, tools, route, **kwargs):
            self.requests.append(copy.deepcopy(messages))
            return next(self.responses)

    async def scenario():
        receipt = await runtime.dispatch(root, 'research_job_submit', {'request': request(), 'invocationId': 'turn-submit'})
        lead = runtime.store.get(receipt['ownerControllerId'])
        # Đây là fixture backend admission, KHÔNG là financial consent cho môi trường sống.
        runtime.research_admission = lambda actor, req: actor['id'] == lead['id'] and req == request()
        model = ScriptedModel()
        runtime.client = model
        original_complete = runtime.complete_model
        callers = []
        async def tracked_complete(sid, *args, **kwargs):
            callers.append(sid)
            return await original_complete(sid, *args, **kwargs)
        runtime.complete_model = tracked_complete
        started = await runtime.dispatch(root, 'research_job_control', control_args(receipt, 'resume'))
        assert started['state'] == 'running'
        await runtime.tasks[lead['id']]
        rows = runtime.store.children_of(lead['id'])
        assert len(rows) == 1 and rows[0]['role'] == 'research' and rows[0]['status'] == 'completed'
        assert runtime.store.children_of(root['id']) == []
        assert 'independent Research controller' in model.requests[0][0]['content']
        assert len(model.requests) == 3
        assert callers == [lead['id'], rows[0]['session_id'], lead['id']]
        replay = await runtime.dispatch(root, 'research_job_control', control_args(receipt, 'resume'))
        assert replay == started and len(model.requests) == 3

    asyncio.run(scenario())


def test_canonical_budget_root_ignores_forged_config(rt):
    runtime, root = rt
    _receipt, lead = submit(rt)
    lead['config']['budgetRootId'] = 'forged-finance-owner'
    runtime.store.update_config(lead['id'], lead['config'])
    assert gateway.budget_root(runtime, runtime.store.get(lead['id']))['id'] == root['id']
    assert gateway.budget_root(runtime, root) is None
    forged = runtime.create({'skills': []}, role='research-lead')
    with pytest.raises(ValueError, match='RESEARCH_CREATION_FORBIDDEN'):
        gateway.budget_root(runtime, forged)


def test_generic_delegate_and_job_delegate_cannot_bypass_lead(rt):
    runtime, root = rt
    submit(rt)
    for kwargs in ({}, {'job_request': {'model': 'opaque'}}):
        with pytest.raises(PermissionError, match='RESEARCH_MAIN_READ_ONLY'):
            asyncio.run(runtime.delegate(root, {'role': 'research', 'goal': 'Bypass independent lead'}, **kwargs))
    assert runtime.store.children_of(root['id']) == []


def test_stale_publication_and_worker_after_release_denied(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    dossier(runtime, receipt, lead)
    dispatch(runtime, root, 'research_job_control', control_args(receipt, 'request_revision'))
    with pytest.raises(ValueError, match='RESEARCH_REVISION_CONFLICT'):
        dispatch(runtime, lead, 'research_job_publish', publish_args(receipt, lead))
    worker = runtime.create({'skills': []}, role='research', parent_id=lead['id'])
    owner = gateway.service(runtime).ownership
    owner.release(receipt['researchJobId'], 'released', owner.get(receipt['researchJobId'])['revision'], actor_id=lead['id'])
    with pytest.raises(PermissionError, match='RESEARCH_JOB_STOPPED'):
        dispatch(runtime, worker, 'source_add', {})


def test_creation_crash_receipt_does_not_replay_effect(rt, monkeypatch):
    runtime, root = rt
    def failed_create(*args, **kwargs):
        raise RuntimeError('fixture creation interrupted')
    monkeypatch.setattr(runtime, 'create', failed_create)
    with pytest.raises(RuntimeError, match='interrupted'):
        submit(rt, 'failed-creation')
    receipt = dispatch(runtime, root, 'research_job_submit', {'request': request(), 'invocationId': 'failed-creation'})
    assert receipt['state'] == 'creating' and receipt['engineState'] == 'unknown'
    assert not runtime.tasks


def test_unknown_table_schema_and_revision_refused(rt):
    runtime, root = rt
    receipt, _lead = submit(rt)
    with runtime.store.db:
        runtime.store.db.execute('UPDATE harness_research_gateway SET schema_version=2 WHERE run_id=?', (receipt['researchJobId'],))
    with pytest.raises(ValueError, match='RESEARCH_GATEWAY_SCHEMA_UNSUPPORTED'):
        dispatch(runtime, root, 'research_job_get', {'jobId': receipt['researchJobId']})


def test_lead_cannot_silently_switch_intake_or_spawn_new_brief(rt):
    runtime, _root = rt
    receipt, lead = submit(rt)
    for name, args in [('research_brief', {'researchId': 'foreign-run', 'question': 'foreign'}),
                       ('research_brief', {'researchId': receipt['researchJobId'], 'newRun': True}),
                       ('dossier_write', {'researchId': 'foreign-run'})]:
        with pytest.raises(PermissionError, match='RESEARCH_RUN_MISMATCH'):
            dispatch(runtime, lead, name, args)
    assert runtime.store.research_job('foreign-run') is None


def test_root_capability_revocation_is_live_for_independent_lead_and_worker(rt):
    runtime, root = rt
    receipt, lead = submit(rt)
    worker = runtime.create({'skills': []}, role='research', parent_id=lead['id'])
    config = runtime.store.get(root['id'])['config']
    config['tools'] = [tool for tool in config['tools'] if tool not in {'source_add', 'research_job_control'}]
    runtime.store.update_config(root['id'], config)
    with pytest.raises(PermissionError, match='RESEARCH_CAPABILITY_REVOKED'):
        dispatch(runtime, lead, 'source_add', {})
    with pytest.raises(PermissionError, match='RESEARCH_CONTROL_FORBIDDEN'):
        dispatch(runtime, worker, 'source_add', {})
    with pytest.raises(PermissionError, match='RESEARCH_CAPABILITY_REVOKED'):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
    # Thu hồi capability không chặn quyền Stop hay bản đọc công bố.
    assert dispatch(runtime, root, 'research_job_get', {'jobId': receipt['researchJobId']})
    assert dispatch(runtime, root, 'research_job_control', control_args(receipt))['state'] == 'cancelled'


@pytest.mark.parametrize('prepared', [False, None, {'price': 'not-authority'}])
def test_resume_prepare_denial_never_enters_sync_admission_or_starts(rt, monkeypatch, prepared):
    runtime, root = rt
    receipt, lead = submit(rt)
    calls = []
    async def prepare(actor, intake):
        assert not runtime.store.db.in_transaction
        assert actor['id'] == lead['id'] and intake == request()
        await asyncio.sleep(0)
        assert not runtime.store.db.in_transaction
        return prepared
    runtime.prepare_research_admission = prepare
    runtime.research_admission = lambda *_: calls.append('sync') or True
    monkeypatch.setattr(runtime, 'start', lambda *_args, **_kwargs: calls.append('start'))
    with pytest.raises(ValueError, match='RESEARCH_NEEDS_CONSENT'):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
    assert calls == []
    assert gateway._binding(runtime.store, run_id=receipt['researchJobId'])['revision'] == 1


@pytest.mark.parametrize('with_prepare', [False, True])
@pytest.mark.parametrize('sync_result', ['missing', False])
def test_prepare_is_not_consent_and_missing_sync_hook_stays_blocked(rt, monkeypatch, with_prepare, sync_result):
    runtime, root = rt
    receipt, _lead = submit(rt)
    calls = []
    async def prepare(*_):
        assert not runtime.store.db.in_transaction
        calls.append('prepare')
        await asyncio.sleep(0)
        return True
    # Chỉ dùng backend hooks fixture, không gọi admission sống.
    monkeypatch.setattr(runtime, 'prepare_research_admission', prepare if with_prepare else None, raising=False)
    monkeypatch.setattr(runtime, 'research_admission', None, raising=False)
    if sync_result is False:
        def denied(*_):
            assert runtime.store.db.in_transaction
            calls.append('sync')
            return False
        runtime.research_admission = denied
    monkeypatch.setattr(runtime, 'start', lambda *_args, **_kwargs: calls.append('start'))
    with pytest.raises(ValueError, match='RESEARCH_NEEDS_CONSENT'):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
    assert calls == (['prepare'] if with_prepare else []) + (['sync'] if sync_result is False else [])
    assert gateway._binding(runtime.store, run_id=receipt['researchJobId'])['state'] == 'needs_consent'


def test_async_prepare_then_locked_sync_admission_and_start_once(rt, monkeypatch):
    runtime, root = rt
    receipt, lead = submit(rt)
    calls = []
    async def prepare(actor, intake):
        assert not runtime.store.db.in_transaction
        assert actor['id'] == lead['id'] and intake == request()
        calls.append('prepare')
        await asyncio.sleep(0)
        return True
    def admitted(actor, intake):
        assert runtime.store.db.in_transaction
        assert actor['id'] == lead['id'] and intake == request()
        calls.append('sync')
        return True
    def start(sid, *_args, **_kwargs):
        assert not runtime.store.db.in_transaction
        assert sid == lead['id']
        calls.append('start')
    runtime.prepare_research_admission = prepare
    runtime.research_admission = admitted
    monkeypatch.setattr(runtime, 'start', start)
    args = control_args(receipt, 'resume')
    started = dispatch(runtime, root, 'research_job_control', args)
    assert started['state'] == 'running' and calls == ['prepare', 'sync', 'start']
    assert dispatch(runtime, root, 'research_job_control', args) == started
    assert calls == ['prepare', 'sync', 'start']
    # Các action không tiêu tiền không gọi prepare.
    dispatch(runtime, root, 'research_job_control', control_args(started, 'cancel', invocationId='stop-after-start'))
    assert calls == ['prepare', 'sync', 'start']


@pytest.mark.parametrize('changed', ['revision', 'request', 'owner', 'released', 'revoke'])
def test_resume_rechecks_canonical_state_after_async_prepare(rt, monkeypatch, changed):
    import json
    runtime, root = rt
    receipt, lead = submit(rt)
    calls = []
    expected = {'revision': 'RESEARCH_REVISION_CONFLICT', 'request': 'RESEARCH_REVISION_CONFLICT',
                'owner': 'RESEARCH_CONTROL_FORBIDDEN', 'released': 'RESEARCH_JOB_STOPPED',
                'revoke': 'RESEARCH_CAPABILITY_REVOKED'}
    async def prepare(*_):
        assert not runtime.store.db.in_transaction
        await asyncio.sleep(0)
        if changed in {'revision', 'request', 'owner'}:
            with runtime.store.db:
                if changed == 'revision':
                    runtime.store.db.execute('UPDATE harness_research_gateway SET revision=revision+1 WHERE run_id=?', (receipt['researchJobId'],))
                elif changed == 'request':
                    altered = request()
                    altered['questions'].append('Concurrent new question without matching revision.')
                    runtime.store.db.execute('UPDATE harness_research_gateway SET request_json=? WHERE run_id=?', (json.dumps(altered), receipt['researchJobId']))
                else:
                    runtime.store.db.execute("UPDATE harness_research_gateway SET root_id='foreign-root' WHERE run_id=?", (receipt['researchJobId'],))
        elif changed == 'released':
            owner = gateway.service(runtime).ownership
            owner.release(receipt['researchJobId'], 'released during await', owner.get(receipt['researchJobId'])['revision'], actor_id=lead['id'])
        else:
            config = runtime.store.get(root['id'])['config']
            config['tools'].remove('research_job_control')
            runtime.store.update_config(root['id'], config)
        assert not runtime.store.db.in_transaction
        return True
    runtime.prepare_research_admission = prepare
    runtime.research_admission = lambda *_: calls.append('sync') or True
    monkeypatch.setattr(runtime, 'start', lambda *_args, **_kwargs: calls.append('start'))
    with pytest.raises((ValueError, PermissionError), match=expected[changed]):
        dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
    assert calls == []


def test_prepare_refuses_caller_transaction_without_awaiting_hook(rt):
    runtime, root = rt
    receipt, _lead = submit(rt)
    calls = []
    async def prepare(*_):
        calls.append('prepare')
        return True
    runtime.prepare_research_admission = prepare
    runtime.store.db.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(ValueError, match='RESEARCH_ADMISSION_TRANSACTION_OPEN'):
            dispatch(runtime, root, 'research_job_control', control_args(receipt, 'resume'))
        assert calls == []
    finally:
        runtime.store.db.rollback()


def test_engine_work_spawns_cannot_bypass_the_gateway_either(rt):
    """Đường Work Graph cũng không phải cửa sau: `work=` KHÔNG miễn kiểm của gateway.

    Bề mặt 7 đã xoá nên không còn lối thoát nào: luồng `research` của Work Graph
    (engine tự spawn producer research/research-review) dừng với `RESEARCH_MAIN_READ_ONLY` —
    Research phải đi qua biên độc lập (H7.1/P5). Bài này chốt hành vi đó để nó không âm thầm đổi.
    """
    runtime, root = rt
    submit(rt)
    with pytest.raises(PermissionError, match='RESEARCH_MAIN_READ_ONLY'):
        asyncio.run(runtime.delegate(root, {'role': 'research', 'goal': 'Engine spawn'},
                                     work={'run': 'r1', 'node': 'n1', 'stage': 'produce'}))
    assert runtime.store.children_of(root['id']) == []
