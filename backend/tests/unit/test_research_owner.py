"""Quyền sở hữu Research tường minh (H7) — luật quyền, biên nhận và hợp đồng báo cáo.

Các ca ở đây chạy trên SQLite thật trong `tmp_path`, không model, không mạng. Mỗi bất biến đều có
ca "phải qua" đi kèm ca "phải chặn": chỉ owner/controller điều khiển được run, revision cũ bị từ
chối, ý định của main không đội lốt canonical, và báo cáo thiếu trích dẫn/do main viết bị loại.
"""
from __future__ import annotations

import json

import pytest

from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.research_owner import (
    ResearchOwnership, report_contract, validate_report,
)
from agentbox.memory.session_store import SessionStore

RUN = 'run-1'
LEAD = 'research-lead'
CTL = 'controller-1'


@pytest.fixture
def own(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    owner = ResearchOwnership(store)
    yield store, owner
    store.close()


def intent(text='cau hoi kinh doanh', author='research-lead', **extra):
    value = {'authoredBy': author, 'text': text}
    value.update(extra)
    return value


def assign(store, owner, *, run=RUN, owner_id=LEAD, controller_id=CTL, intent_value=None,
           invocation='inv-assign'):
    return owner.assign(run, owner_id, controller_id,
                        intent() if intent_value is None else intent_value, invocation)


def error(code, call):
    with pytest.raises(ContractError) as exc:
        call()
    assert exc.value.code == code
    return exc.value


def count(store, table):
    return store.db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]


def report(**updates):
    value = {
        'schema': 'boxfox-research-report/1',
        'authoredBy': 'research-lead',
        'questionState': {'status': 'answered', 'summary': 'Da tra loi cau hoi.'},
        'evidenceRefs': [{'artifactId': 'artifact-1', 'version': 1, 'contentHash': 'a' * 64}],
        'uncertainty': ['Chua co so lieu doanh thu.'],
        'provenance': {'method': 'synthesis'},
    }
    value.update(updates)
    return value


# --- assign -----------------------------------------------------------------

def test_assign_creates_an_explicit_owner_and_controller(own):
    store, owner = own
    view = assign(store, owner)
    assert (view['runId'], view['ownerId'], view['controllerId']) == (RUN, LEAD, CTL)
    assert view['revision'] == 1 and view['state'] == 'assigned'
    assert view['intent']['authoredBy'] == 'research-lead'
    assert view['intent']['text'] == 'cau hoi kinh doanh'
    assert view['handoffs'] == [] and view['controls'] == []


def test_assign_replays_the_same_invocation_without_a_second_record(own):
    store, owner = own
    first = assign(store, owner)
    second = assign(store, owner)
    assert second['revision'] == first['revision'] == 1
    assert count(store, 'harness_research_ownership') == 1


def test_assign_rejects_a_reused_invocation_with_a_different_request(own):
    store, owner = own
    assign(store, owner)
    error('RESEARCH_OWNERSHIP_CONFLICT', lambda: assign(store, owner, owner_id='lead-2'))


def test_assign_rejects_a_second_assignment_of_the_same_run(own):
    store, owner = own
    assign(store, owner)
    error('RESEARCH_OWNERSHIP_CONFLICT', lambda: assign(store, owner, invocation='inv-assign-2'))
    assert count(store, 'harness_research_ownership') == 1


def test_assign_records_a_main_authored_intent_as_an_input_reference(own):
    store, owner = own
    view = assign(store, owner, intent_value=intent('cau hoi cua main', author='main'))
    assert view['intent']['authoredBy'] is None
    assert view['intent']['text'] is None
    entries = view['intent']['sourceRefs']
    assert len(entries) == 1
    assert entries[0]['authoredBy'] == 'main' and entries[0]['text'] == 'cau hoi cua main'
    assert entries[0]['inputHash']


def test_assign_rejects_an_unknown_intent_author(own):
    store, owner = own
    error('HARNESS_CONTRACT_INVALID',
          lambda: assign(store, owner, intent_value=intent(author='worker')))


# --- authorize --------------------------------------------------------------

def test_authorize_allows_the_owner_and_the_controller(own):
    store, owner = own
    assign(store, owner)
    for actor in (LEAD, CTL):
        for action in ('control', 'handoff', 'release', 'read'):
            decision = owner.authorize(RUN, actor, action)
            assert decision['allowed'] is True
            assert decision['code'] == 'RESEARCH_CONTROL_ALLOWED'


def test_authorize_denies_a_peer_and_a_child_session(own):
    store, owner = own
    assign(store, owner)
    for actor in ('peer-session-1', 'child-7'):
        decision = owner.authorize(RUN, actor, 'control')
        assert decision['allowed'] is False
        assert decision['code'] == 'RESEARCH_CONTROL_FORBIDDEN'


def test_authorize_denies_every_action_for_a_peer(own):
    store, owner = own
    assign(store, owner)
    for action in ('control', 'handoff', 'release', 'read'):
        decision = owner.authorize(RUN, 'peer-session-1', action)
        assert decision['allowed'] is False
        assert decision['code'] == 'RESEARCH_CONTROL_FORBIDDEN'


def test_authorize_unknown_run_returns_the_unknown_code(own):
    store, owner = own
    decision = owner.authorize('run-missing', LEAD, 'control')
    assert decision['allowed'] is False
    assert decision['code'] == 'RESEARCH_OWNERSHIP_UNKNOWN'


def test_authorize_rejects_an_unknown_action(own):
    store, owner = own
    assign(store, owner)
    error('RESEARCH_CONTROL_ACTION_UNKNOWN', lambda: owner.authorize(RUN, LEAD, 'promote'))


def test_authorize_receipts_both_allow_and_deny_without_bumping_revision(own):
    store, owner = own
    assign(store, owner)
    owner.authorize(RUN, LEAD, 'control')
    owner.authorize(RUN, 'peer-session-1', 'read')
    controls = owner.get(RUN)['controls']
    assert len(controls) == 2
    codes = {item['code'] for item in controls}
    assert codes == {'RESEARCH_CONTROL_ALLOWED', 'RESEARCH_CONTROL_FORBIDDEN'}
    denied = next(item for item in controls if not item['allowed'])
    assert (denied['actorId'], denied['action']) == ('peer-session-1', 'read')
    assert owner.get(RUN)['revision'] == 1


# --- claim ------------------------------------------------------------------

def test_claim_moves_control_and_bumps_the_revision(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    view = owner.claim(RUN, LEAD, 1)
    assert view['controllerId'] == LEAD
    assert view['revision'] == 2 and view['state'] == 'active'


def test_claim_by_a_peer_is_forbidden_and_changes_nothing(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    error('RESEARCH_CONTROL_FORBIDDEN', lambda: owner.claim(RUN, 'peer-session-1', 1))
    assert owner.get(RUN)['controllerId'] == CTL
    assert owner.get(RUN)['revision'] == 1
    # Biên nhận từ chối vẫn được giữ, kể cả khi thao tác bị chặn.
    assert [item['code'] for item in owner.get(RUN)['controls']] == ['RESEARCH_CONTROL_FORBIDDEN']


def test_claim_rejects_a_stale_revision(own):
    store, owner = own
    assign(store, owner)
    error('RESEARCH_REVISION_CONFLICT', lambda: owner.claim(RUN, LEAD, 2))
    assert owner.get(RUN)['revision'] == 1


def test_claim_replays_the_same_invocation(own):
    store, owner = own
    assign(store, owner)
    first = owner.claim(RUN, LEAD, 1, 'inv-claim')
    replay = owner.claim(RUN, LEAD, 1, 'inv-claim')
    assert replay['revision'] == first['revision'] == 2
    assert owner.get(RUN)['revision'] == 2
    assert count(store, 'harness_research_controls') == 1, 'replay không ghi thêm biên nhận'


def test_claim_rejects_a_reused_invocation_with_a_different_request(own):
    store, owner = own
    assign(store, owner)
    owner.claim(RUN, LEAD, 1, 'inv-claim')
    error('RESEARCH_INVOCATION_CONFLICT', lambda: owner.claim(RUN, CTL, 1, 'inv-claim'))


def test_claim_unknown_run_fails_closed(own):
    store, owner = own
    error('RESEARCH_OWNERSHIP_UNKNOWN', lambda: owner.claim('run-missing', LEAD, 1))


# --- handoff ----------------------------------------------------------------

def test_handoff_moves_the_controller_and_writes_a_receipt(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    view = owner.handoff(RUN, 'controller-2', 'ca truc', 1)
    assert view['controllerId'] == 'controller-2'
    assert view['revision'] == 2 and view['state'] == 'active'
    handoffs = view['handoffs']
    assert len(handoffs) == 1
    assert handoffs[0]['fromController'] == CTL
    assert handoffs[0]['toController'] == 'controller-2'
    assert handoffs[0]['reason'] == 'ca truc' and handoffs[0]['revision'] == 2
    row = store.db.execute('SELECT * FROM harness_research_handoffs WHERE run_id=?',
                           (RUN,)).fetchone()
    assert (row['from_controller'], row['to_controller']) == (CTL, 'controller-2')


def test_handoff_rejects_a_stale_revision_without_a_receipt(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    error('RESEARCH_REVISION_CONFLICT', lambda: owner.handoff(RUN, 'controller-2', 'ca truc', 2))
    assert count(store, 'harness_research_handoffs') == 0
    assert owner.get(RUN)['controllerId'] == CTL


def test_handoff_replays_the_same_invocation(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    first = owner.handoff(RUN, 'controller-2', 'ca truc', 1, 'inv-handoff')
    replay = owner.handoff(RUN, 'controller-2', 'ca truc', 1, 'inv-handoff')
    assert replay['revision'] == first['revision'] == 2
    assert count(store, 'harness_research_handoffs') == 1


def test_handoff_target_can_control_and_the_old_controller_cannot(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    owner.handoff(RUN, 'controller-2', 'ca truc', 1)
    assert owner.authorize(RUN, 'controller-2', 'control')['allowed'] is True
    assert owner.authorize(RUN, CTL, 'control')['allowed'] is False


def test_handoff_unknown_run_fails_closed(own):
    store, owner = own
    error('RESEARCH_OWNERSHIP_UNKNOWN', lambda: owner.handoff('run-missing', 'controller-2', 'x', 1))


# --- release ----------------------------------------------------------------

def test_release_records_the_reason_and_is_idempotent(own):
    store, owner = own
    assign(store, owner)
    first = owner.release(RUN, 'het viec', 1)
    assert first['state'] == 'released'
    assert first['releaseReason'] == 'het viec' and first['releasedAt'] is not None
    assert first['revision'] == 2
    second = owner.release(RUN, 'ly do khac', 1)
    assert second['state'] == 'released'
    assert second['releaseReason'] == 'het viec', 'lần ghi đầu thắng'
    assert second['revision'] == 2
    assert owner.get(RUN)['releaseReason'] == 'het viec'


def test_release_rejects_a_stale_revision_before_it_is_released(own):
    store, owner = own
    assign(store, owner)
    error('RESEARCH_REVISION_CONFLICT', lambda: owner.release(RUN, 'xong', 2))
    assert owner.get(RUN)['state'] == 'assigned'


def test_claim_and_handoff_after_release_are_refused(own):
    store, owner = own
    assign(store, owner)
    owner.release(RUN, 'xong', 1)
    error('RESEARCH_OWNERSHIP_RELEASED', lambda: owner.claim(RUN, LEAD, 2))
    error('RESEARCH_OWNERSHIP_RELEASED', lambda: owner.handoff(RUN, 'controller-2', 'lai', 2))


def test_release_unknown_run_fails_closed(own):
    store, owner = own
    error('RESEARCH_OWNERSHIP_UNKNOWN', lambda: owner.release('run-missing', 'xong', 1))


# --- record_intent ----------------------------------------------------------

def test_record_intent_rejects_overwriting_canonical_without_a_revision_bump(own):
    store, owner = own
    assign(store, owner, intent_value=intent('khung cu'))
    error('RESEARCH_INTENT_CONFLICT', lambda: owner.record_intent(RUN, intent('khung moi'), 1))
    assert owner.get(RUN)['intent']['text'] == 'khung cu'


def test_record_intent_allows_a_rewrite_after_a_control_bump(own):
    store, owner = own
    assign(store, owner, intent_value=intent('khung cu'))
    owner.claim(RUN, LEAD, 1)  # revision 2 — nhịp tăng điều khiển
    view = owner.record_intent(RUN, intent('khung moi', scope=['cau hoi 1']), 2)
    assert view['intent']['authoredBy'] == 'research-lead'
    assert view['intent']['text'] == 'khung moi'
    assert view['intent']['scope'] == ['cau hoi 1']
    assert view['intent']['intentRevision'] == 2


def test_record_intent_stores_a_research_lead_intent_as_canonical(own):
    store, owner = own
    assign(store, owner, intent_value=intent('cau hoi tu main', author='main'))
    view = owner.record_intent(RUN, intent('khung nghien cuu', scope=['cau hoi 1']), 1)
    assert view['intent']['authoredBy'] == 'research-lead'
    assert view['intent']['text'] == 'khung nghien cuu'
    assert view['intent']['sourceRefs'][0]['authoredBy'] == 'main', 'đầu vào của main vẫn còn'


def test_record_intent_never_lets_main_become_canonical(own):
    store, owner = own
    assign(store, owner, intent_value=intent('khung cua lead'))
    view = owner.record_intent(RUN, intent('cau hoi tu main', author='main'), 1)
    assert view['intent']['authoredBy'] == 'research-lead'
    assert view['intent']['text'] == 'khung cua lead', 'canonical không bị main ghi đè'
    assert view['intent']['sourceRefs'][0]['authoredBy'] == 'main'
    assert view['intent']['sourceRefs'][0]['text'] == 'cau hoi tu main'


def test_record_intent_deduplicates_main_inputs(own):
    store, owner = own
    assign(store, owner)
    owner.record_intent(RUN, intent('cau hoi tu main', author='main'), 1)
    again = owner.record_intent(RUN, intent('cau hoi tu main', author='main'), 1)
    assert len(again['intent']['sourceRefs']) == 1
    assert owner.get(RUN)['revision'] == 1, 'tham chiếu đầu vào không tăng revision điều khiển'


def test_record_intent_rejects_unknown_and_unbounded_fields(own):
    store, owner = own
    assign(store, owner)
    error('HARNESS_CONTRACT_INVALID',
          lambda: owner.record_intent(RUN, {'authoredBy': 'main', 'text': 'x', 'canonical': True}, 1))
    error('HARNESS_CONTRACT_INVALID',
          lambda: owner.record_intent(RUN, intent('x' * 12001), 1))


def test_record_intent_unknown_run_fails_closed(own):
    store, owner = own
    error('RESEARCH_OWNERSHIP_UNKNOWN',
          lambda: owner.record_intent('run-missing', intent(), 1))


# --- control_view -----------------------------------------------------------

def test_control_view_is_full_for_the_owner_and_the_controller(own):
    store, owner = own
    assign(store, owner, owner_id=LEAD, controller_id=CTL)
    for actor in (LEAD, CTL):
        view = owner.control_view(RUN, actor)
        assert set(view) == {'runId', 'ownerId', 'controllerId', 'revision', 'state',
                             'intent', 'handoffs', 'controls'}
        assert view['ownerId'] == LEAD and view['controllerId'] == CTL
        assert view['intent']['authoredBy'] == 'research-lead'


def test_control_view_is_reduced_for_everyone_else(own):
    store, owner = own
    assign(store, owner)
    view = owner.control_view(RUN, 'peer-session-1')
    assert view == {'runId': RUN, 'state': 'assigned', 'revision': 1}
    assert 'intent' not in view and 'handoffs' not in view and 'controls' not in view


def test_control_view_unknown_run_fails_closed(own):
    store, owner = own
    error('RESEARCH_OWNERSHIP_UNKNOWN', lambda: owner.control_view('run-missing', LEAD))


def test_get_unknown_run_fails_closed(own):
    store, owner = own
    error('RESEARCH_OWNERSHIP_UNKNOWN', lambda: owner.get('run-missing'))


# --- report contract --------------------------------------------------------

def test_report_contract_declares_the_expert_schema(own):
    contract = report_contract()
    assert contract['schema'] == 'boxfox-research-report/1'
    assert contract['authoredBy'] == 'research-lead'
    assert set(contract['required']) == {'schema', 'authoredBy', 'questionState', 'evidenceRefs',
                                         'uncertainty', 'provenance'}
    assert contract['additionalFields'] is False
    assert contract['evidenceRefs']['minItems'] == 1
    assert contract['rejections'] == {'uncited': 'RESEARCH_REPORT_UNCITED',
                                      'authorship': 'RESEARCH_REPORT_AUTHORSHIP'}
    assert json.dumps(contract)


def test_validate_report_accepts_a_conforming_report(own):
    payload = report()
    normalized = validate_report(payload)
    assert normalized['authoredBy'] == 'research-lead'
    assert normalized['evidenceRefs'][0]['artifactId'] == 'artifact-1'
    assert normalized['questionState'] == {'status': 'answered', 'summary': 'Da tra loi cau hoi.'}
    assert normalized['uncertainty'] == ['Chua co so lieu doanh thu.']
    payload['uncertainty'].append('sua sau khi chuan hoa')
    assert normalized['uncertainty'] == ['Chua co so lieu doanh thu.'], 'cắt khỏi container gọi'


def test_validate_report_rejects_a_report_without_evidence(own):
    error('RESEARCH_REPORT_UNCITED', lambda: validate_report(report(evidenceRefs=[])))
    without = {key: value for key, value in report().items() if key != 'evidenceRefs'}
    error('RESEARCH_REPORT_UNCITED', lambda: validate_report(without))


def test_validate_report_rejects_main_authored_conclusions(own):
    error('RESEARCH_REPORT_AUTHORSHIP', lambda: validate_report(report(authoredBy='main')))
    without = {key: value for key, value in report().items() if key != 'authoredBy'}
    error('RESEARCH_REPORT_AUTHORSHIP', lambda: validate_report(without))


def test_validate_report_rejects_unknown_and_unbounded_fields(own):
    payload = report()
    payload['hiddenReasoning'] = 'khong duoc phep'
    error('HARNESS_CONTRACT_INVALID', lambda: validate_report(payload))
    oversized = report()
    oversized['questionState'] = dict(oversized['questionState'], summary='x' * 8001)
    error('HARNESS_CONTRACT_INVALID', lambda: validate_report(oversized))
    extra_provenance = report(provenance={'method': 'synthesis', 'scratch': 'y'})
    error('HARNESS_CONTRACT_INVALID', lambda: validate_report(extra_provenance))


def test_validate_report_rejects_an_unknown_question_state(own):
    payload = report()
    payload['questionState'] = dict(payload['questionState'], status='certain')
    error('HARNESS_CONTRACT_INVALID', lambda: validate_report(payload))


def test_validate_report_rejects_duplicate_evidence_refs(own):
    ref = {'artifactId': 'artifact-1', 'version': 1, 'contentHash': 'a' * 64}
    error('HARNESS_CONTRACT_INVALID', lambda: validate_report(report(evidenceRefs=[ref, dict(ref)])))


def test_validate_report_rejects_an_unsupported_schema(own):
    error('HARNESS_SCHEMA_UNSUPPORTED', lambda: validate_report(report(schema='boxfox-report/9')))


def test_validate_report_rejects_a_non_object(own):
    error('HARNESS_CONTRACT_INVALID', lambda: validate_report(['khong phai object']))


# --- schema fail-closed -----------------------------------------------------

def test_constructor_fails_closed_on_a_stale_ownership_table(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    store.db.execute('CREATE TABLE harness_research_ownership '
                     '(run_id TEXT PRIMARY KEY, schema_version INTEGER)')
    store.db.commit()
    error('RESEARCH_OWNER_SCHEMA_UNSUPPORTED', lambda: ResearchOwnership(store))
    store.close()


def test_constructor_fails_closed_on_a_stale_controls_table(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    store.db.execute('CREATE TABLE harness_research_controls (control_id TEXT PRIMARY KEY, run_id TEXT)')
    store.db.commit()
    error('RESEARCH_OWNER_SCHEMA_UNSUPPORTED', lambda: ResearchOwnership(store))
    store.close()


def test_unknown_record_schema_version_fails_closed(own):
    store, owner = own
    assign(store, owner)
    store.db.execute('UPDATE harness_research_ownership SET schema_version=99 WHERE run_id=?', (RUN,))
    store.db.commit()
    error('RESEARCH_OWNER_SCHEMA_UNSUPPORTED', lambda: owner.get(RUN))
    error('RESEARCH_OWNER_SCHEMA_UNSUPPORTED', lambda: owner.authorize(RUN, LEAD, 'read'))


def test_corrupt_intent_record_fails_closed(own):
    store, owner = own
    assign(store, owner)
    store.db.execute('UPDATE harness_research_ownership SET intent_json=? WHERE run_id=?',
                     ('{khong-phai-json', RUN))
    store.db.commit()
    error('RESEARCH_OWNER_SCHEMA_UNSUPPORTED', lambda: owner.get(RUN))
    error('RESEARCH_OWNER_SCHEMA_UNSUPPORTED', lambda: owner.record_intent(RUN, intent('moi'), 1))
