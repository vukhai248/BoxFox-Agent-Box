"""H8 — kiểm thử thuần cho bộ soạn quyết định thích ứng.

Không store, không model, không I/O: chỉ dữ liệu vào/ra của `adaptive_main`.
"""
import pytest

from agentbox.agent_core import adaptive_main
from agentbox.agent_core.orchestration_contracts import ContractError

POLICY = {'schema': 'boxfox-execution-policy/1', 'mode': 'adaptive'}


def policy(**extra):
    return dict(POLICY, **extra)


def full_capability(tokens=16000, levels=None):
    capability = {'maxOutputTokens': tokens}
    if levels is not None:
        capability['thinkingLevels'] = levels
    return capability


def decision_actions(decision):
    return {item['action'] for item in decision['alternatives']}


# --------------------------------------------------------------------------- #
# progress_signal — từng loại tiến triển
# --------------------------------------------------------------------------- #

def test_new_artifact_is_progress():
    result = adaptive_main.progress_signal(
        {'artifacts': ['plan@1']}, {'artifacts': ['plan@1', 'plan@2']})
    assert result['progress'] is True
    assert result['kind'] == 'artifact'
    assert any('plan@2' in reason for reason in result['reasons'])


def test_new_evidence_is_progress():
    result = adaptive_main.progress_signal(
        {'evidenceRefs': ['log@1']}, {'evidenceRefs': ['log@1', 'receipt@9']})
    assert result['progress'] is True
    assert result['kind'] == 'evidence'
    assert any('receipt@9' in reason for reason in result['reasons'])


def test_reduced_acceptance_gap_is_progress():
    result = adaptive_main.progress_signal({'acceptanceGap': 5}, {'acceptanceGap': 2})
    assert result['progress'] is True
    assert result['kind'] == 'acceptance_gap'


def test_shrinking_open_criteria_is_progress():
    result = adaptive_main.progress_signal(
        {'openCriteria': ['A1', 'A2', 'A3']}, {'openCriteria': ['A2']})
    assert result['progress'] is True
    assert result['kind'] == 'acceptance_gap'
    assert any('A1' in reason for reason in result['reasons'])


def test_closing_the_last_open_criterion_is_progress():
    result = adaptive_main.progress_signal({'openCriteria': ['c1']}, {'openCriteria': []})
    assert result['progress'] is True
    assert result['kind'] == 'acceptance_gap'
    assert any('c1' in reason for reason in result['reasons'])


def test_open_criteria_absent_before_cannot_claim_a_shrink():
    result = adaptive_main.progress_signal({}, {'openCriteria': []})
    assert result['progress'] is False
    assert result['kind'] is None


def test_resolved_uncertainty_is_progress():
    result = adaptive_main.progress_signal(
        {'uncertainties': ['q1', 'q2']}, {'uncertainties': ['q2']})
    assert result['progress'] is True
    assert result['kind'] == 'uncertainty'
    assert any('q1' in reason for reason in result['reasons'])


def test_lower_uncertainty_level_is_progress():
    result = adaptive_main.progress_signal({'uncertainty': 'high'}, {'uncertainty': 'medium'})
    assert result['progress'] is True
    assert result['kind'] == 'uncertainty'


def test_checkpoint_with_observed_result_is_progress():
    result = adaptive_main.progress_signal(
        {'checkpoint': {'id': 'cp1'}},
        {'checkpoint': {'id': 'cp1', 'status': 'observed', 'result': {'exitCode': 0}}})
    assert result['progress'] is True
    assert result['kind'] == 'checkpoint'


def test_unchanged_checkpoint_is_not_progress():
    checkpoint = {'id': 'cp1', 'status': 'observed', 'result': {'exitCode': 0}}
    result = adaptive_main.progress_signal({'checkpoint': checkpoint}, {'checkpoint': checkpoint})
    assert result['progress'] is False
    assert result['kind'] is None


# --------------------------------------------------------------------------- #
# progress_signal — từng loại KHÔNG phải tiến triển
# --------------------------------------------------------------------------- #

def test_checkpoint_without_result_is_not_progress():
    result = adaptive_main.progress_signal(
        {'checkpoint': {'id': 'cp1'}}, {'checkpoint': {'id': 'cp1', 'status': 'planned'}})
    assert result['progress'] is False
    assert result['kind'] is None
    assert result['reasons']


def test_longer_text_is_not_progress():
    result = adaptive_main.progress_signal(
        {'text': 'short'}, {'text': 'short plus a much longer paraphrase of the same content'})
    assert result['progress'] is False
    assert any('text' in reason for reason in result['reasons'])


def test_tool_call_growth_is_not_progress():
    result = adaptive_main.progress_signal({'toolCalls': 3}, {'toolCalls': 9})
    assert result['progress'] is False
    assert any('tool-call' in reason for reason in result['reasons'])


def test_repeated_logs_are_not_progress():
    result = adaptive_main.progress_signal({'logs': ['a']}, {'logs': ['a', 'a', 'a']})
    assert result['progress'] is False
    assert any('log' in reason for reason in result['reasons'])


def test_identical_snapshots_are_not_progress():
    snapshot = {'artifacts': ['plan@1'], 'toolCalls': 2, 'text': 'same'}
    result = adaptive_main.progress_signal(snapshot, dict(snapshot))
    assert result['progress'] is False
    assert result['kind'] is None
    assert result['reasons']


def test_missing_snapshots_are_not_progress():
    result = adaptive_main.progress_signal(None, None)
    assert result['progress'] is False
    assert result['kind'] is None
    assert result['reasons']


# --------------------------------------------------------------------------- #
# loop_guard
# --------------------------------------------------------------------------- #

def signature(failure='WORK_CHECK_FAILED', inputs='hash-1', evidence=('log@1',), **extra):
    return dict({'failure': failure, 'inputs': inputs, 'evidenceRefs': list(evidence)}, **extra)


def test_loop_guard_blocks_same_signature_with_unchanged_inputs():
    history = [signature()]
    result = adaptive_main.loop_guard(history, signature())
    assert result['repeat'] is True
    assert result['code'] == adaptive_main.LOOP_REPEAT
    assert result['action'] == 'blocked'


def test_loop_guard_policy_can_choose_stop():
    history = {'entries': [signature()], 'policy': {'loopAction': 'stop'}}
    result = adaptive_main.loop_guard(history, signature())
    assert result['repeat'] is True
    assert result['action'] == 'stop'


def test_loop_guard_clears_on_changed_signature():
    result = adaptive_main.loop_guard([signature()], signature(failure='WORK_OTHER'))
    assert result['repeat'] is False
    assert result['code'] is None
    assert result['action'] == 'continue'


def test_loop_guard_clears_on_new_evidence():
    result = adaptive_main.loop_guard([signature()], signature(evidence=('log@1', 'log@2')))
    assert result['repeat'] is False
    assert result['action'] == 'continue'


def test_loop_guard_clears_on_changed_inputs():
    result = adaptive_main.loop_guard([signature()], signature(inputs='hash-2'))
    assert result['repeat'] is False


def test_loop_guard_without_history_does_not_block():
    result = adaptive_main.loop_guard([], signature())
    assert result['repeat'] is False
    assert result['code'] is None
    assert result['action'] == 'continue'


def test_loop_guard_scans_all_matching_entries_not_only_the_most_recent():
    # h1, h2, h1: entry gần nhất khác input, nhưng biến thể h1 cũ vẫn là bản lặp.
    history = [signature(inputs='hash-1'), signature(inputs='hash-2')]
    result = adaptive_main.loop_guard(history, signature(inputs='hash-1'))
    assert result['repeat'] is True
    assert result['code'] == adaptive_main.LOOP_REPEAT
    assert result['action'] == 'blocked'


def test_loop_guard_any_matching_entry_blocks_despite_a_newer_one_with_new_evidence():
    history = [signature(evidence=('log@1',)), signature(evidence=())]
    result = adaptive_main.loop_guard(history, signature(evidence=('log@1',)))
    assert result['repeat'] is True


# --------------------------------------------------------------------------- #
# effort
# --------------------------------------------------------------------------- #

def test_effort_low_for_low_uncertainty_and_value():
    result = adaptive_main.effort('low', 'low', full_capability())
    assert result['level'] == 'low'
    assert result['outputTokens'] == adaptive_main.EFFORT_OUTPUT_TOKENS['low']
    assert result['reasons']


def test_effort_high_for_high_uncertainty_and_value():
    result = adaptive_main.effort('high', 'high', full_capability())
    assert result['level'] == 'high'
    assert result['outputTokens'] == adaptive_main.EFFORT_OUTPUT_TOKENS['high']


def test_effort_clamped_by_capability_output_ceiling():
    result = adaptive_main.effort('high', 'high', full_capability(tokens=4096))
    assert result['level'] == 'high'
    assert result['outputTokens'] == 4096
    assert any('model max' in reason for reason in result['reasons'])


def test_effort_clamped_by_policy_output_ceiling():
    result = adaptive_main.effort('high', 'high', full_capability(tokens=16000),
                                  policy(outputTokensCeiling=2048))
    assert result['outputTokens'] == 2048
    assert any('policy ceiling' in reason for reason in result['reasons'])


def test_effort_never_raises_the_policy_ceiling():
    result = adaptive_main.effort('high', 'high', full_capability(tokens=64000),
                                  policy(outputTokensCeiling=8192))
    assert result['outputTokens'] == 8192


def test_effort_clamped_by_policy_effort_ceiling():
    result = adaptive_main.effort('high', 'high', full_capability(), policy(maxEffort='low'))
    assert result['level'] == 'low'


def test_effort_policy_ceiling_above_the_level_changes_nothing():
    result = adaptive_main.effort('low', 'low', full_capability(tokens=16000),
                                  policy(maxEffort='high'))
    assert result['level'] == 'low'
    assert result['outputTokens'] == adaptive_main.EFFORT_OUTPUT_TOKENS['low']
    assert not any('clamped' in reason for reason in result['reasons'])


def test_effort_model_ladder_snaps_up_to_the_lowest_published_level():
    # Model chỉ công bố medium/high: mức thấp hơn được snap lên mức thấp nhất model có.
    capability = full_capability(levels=['medium', 'high'])
    result = adaptive_main.effort('low', 'low', capability)
    assert result['level'] == 'medium'
    assert result['outputTokens'] == adaptive_main.EFFORT_OUTPUT_TOKENS['medium']
    assert any('snapped up' in reason for reason in result['reasons'])


def test_effort_clamps_level_by_published_thinking_levels():
    capability = full_capability(levels=['low', 'medium'])
    result = adaptive_main.effort('high', 'high', capability)
    assert result['level'] == 'medium'
    assert any('clamped' in reason for reason in result['reasons'])


def test_effort_unknown_capability_returns_no_token_number():
    result = adaptive_main.effort('high', 'high', None)
    assert result['level'] == 'high'
    assert result['outputTokens'] is None
    assert any('unknown' in reason for reason in result['reasons'])


def test_effort_zero_policy_ceiling_withholds_the_token_number():
    result = adaptive_main.effort('high', 'high', full_capability(), policy(outputTokensCeiling=0))
    assert result['outputTokens'] is None
    assert any('0' in reason for reason in result['reasons'])


def test_effort_ignores_previous_reasoning_history():
    history_policy = policy(previousReasoningTokens=90000, history=[{'reasoningTokens': 90000}])
    result = adaptive_main.effort('high', 'high', full_capability(), history_policy)
    assert result['level'] == 'high'
    assert result['outputTokens'] == adaptive_main.EFFORT_OUTPUT_TOKENS['high']


def test_effort_missing_inputs_use_medium_baseline():
    result = adaptive_main.effort(None, None, full_capability())
    assert result['level'] == 'medium'
    assert any('baseline' in reason for reason in result['reasons'])


def test_effort_unknown_level_string_is_not_low():
    result = adaptive_main.effort('unknown', 'high', full_capability())
    assert result['level'] == 'medium'


def test_effort_rejects_unrecognized_level():
    with pytest.raises(ContractError) as error:
        adaptive_main.effort('hgih', 'high', full_capability())
    assert error.value.code == 'ADAPTIVE_EFFORT_INPUT'


# --------------------------------------------------------------------------- #
# plan_step — thứ tự ưu tiên và chặn quyền
# --------------------------------------------------------------------------- #

def test_policy_off_returns_legacy_continue():
    decision = adaptive_main.plan_step(None, {'branch': {'needed': True, 'reason': 'x'}})
    assert decision['action'] == 'continue'
    assert decision['reason'].startswith(adaptive_main.LEGACY_POLICY)
    assert decision['budget'] == {'outputTokens': None, 'effort': None, 'ceilingRef': None}


def test_legacy_mode_policy_is_treated_as_off():
    decision = adaptive_main.plan_step({'mode': 'legacy'}, {'goalMet': True})
    assert decision['action'] == 'continue'
    assert decision['reason'].startswith(adaptive_main.LEGACY_POLICY)


def test_stop_requested_wins_over_branch_proposal():
    decision = adaptive_main.plan_step(policy(), {
        'stopRequested': True, 'branch': {'needed': True, 'reason': 'parallel survey'}})
    assert decision['action'] == 'stop'
    assert decision['reason'].startswith(adaptive_main.STOP_REQUESTED)
    assert 'branch' in decision_actions(decision)  # branch chỉ nằm trong alternatives bị từ chối


def test_stop_requested_wins_even_when_policy_is_off():
    decision = adaptive_main.plan_step(None, {'stopRequested': True})
    assert decision['action'] == 'stop'


def test_revoked_wins_even_when_policy_is_off():
    decision = adaptive_main.plan_step(None, {'revoked': {'kind': 'consent'}})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']


def test_revoked_epoch_blocks_without_branching():
    decision = adaptive_main.plan_step(policy(), {
        'revokedEpoch': 3, 'epoch': 4, 'branch': {'needed': True, 'reason': 'x'}})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.EPOCH_REVOKED)
    assert decision['requires'] == ['capability']
    assert 'branch' in decision_actions(decision)


def test_matching_epoch_is_not_revoked():
    decision = adaptive_main.plan_step(policy(), {'revokedEpoch': 4, 'epoch': 4})
    assert decision['action'] == 'continue'


def test_loop_repeat_blocks_and_recommends_checkpoint():
    observation = {
        'loop': {'history': [{'signature': 'WORK_CHECK_FAILED', 'inputs': 'h1',
                              'evidenceRefs': ['log@1']}],
                 'signature': {'signature': 'WORK_CHECK_FAILED', 'inputs': 'h1',
                               'evidenceRefs': ['log@1']}},
        'branch': {'needed': True, 'reason': 'retry as a new branch'},
    }
    decision = adaptive_main.plan_step(policy(), observation)
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.LOOP_REPEAT)
    assert 'checkpoint' in decision['reason']
    assert decision['loop']['repeat'] is True


def test_loop_repeat_policy_stop_action():
    observation = {
        'loop': {'history': [{'signature': 'S', 'inputs': 'h'}],
                 'signature': {'signature': 'S', 'inputs': 'h', 'loopAction': 'stop'}},
    }
    decision = adaptive_main.plan_step(policy(), observation)
    assert decision['action'] == 'stop'


def test_goal_met_stops():
    decision = adaptive_main.plan_step(policy(), {'goalMet': True})
    assert decision['action'] == 'stop'
    assert decision['reason'].startswith(adaptive_main.GOAL_MET)


def test_missing_consent_blocks():
    decision = adaptive_main.plan_step(policy(), {'needs': ['consent']})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEEDS_CONSENT)
    assert decision['requires'] == ['consent']


def test_missing_capability_blocks():
    decision = adaptive_main.plan_step(policy(), {'missingCapability': ['file_write']})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEEDS_CAPABILITY)
    assert decision['requires'] == ['capability']


def test_pending_approval_blocks():
    decision = adaptive_main.plan_step(policy(), {'approvalPending': True})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEEDS_APPROVAL)
    assert decision['requires'] == ['approval']


def test_multiple_needs_are_all_reported():
    decision = adaptive_main.plan_step(policy(), {'needs': ['approval', 'capability']})
    assert decision['requires'] == ['capability', 'approval']
    assert decision['action'] == 'blocked'


def test_unknown_need_is_refused_not_ignored():
    decision = adaptive_main.plan_step(policy(), {'needs': ['spend_everything']})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEED_UNSUPPORTED)
    assert decision['requires'] == []


def test_mixed_supported_and_unsupported_needs_keep_supported_requirements():
    decision = adaptive_main.plan_step(policy(), {'needs': ['consent', 'spend_everything']})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEED_UNSUPPORTED)
    assert decision['requires'] == ['consent']


def test_pending_user_decision_parks():
    decision = adaptive_main.plan_step(policy(), {'userDecisionPending': True})
    assert decision['action'] == 'park'
    assert decision['reason'].startswith(adaptive_main.NEEDS_USER_DECISION)
    assert decision['requires'] == ['user_decision']


def test_branch_proposal_returns_branch():
    observation = {'branch': {'needed': True, 'reason': 'independent survey questions',
                              'evidenceRefs': ['brief@1']}}
    decision = adaptive_main.plan_step(policy(), observation)
    assert decision['action'] == 'branch'
    assert decision['reason'].startswith(adaptive_main.BRANCH_BENEFICIAL)
    assert 'brief@1' in decision['evidenceRefs']


def test_park_proposal_returns_park():
    decision = adaptive_main.plan_step(policy(), {'park': {'reason': 'waiting on CI', 'waitFor': 'job'}})
    assert decision['action'] == 'park'
    assert decision['reason'].startswith(adaptive_main.PARK_REQUESTED)


def test_default_is_continue():
    decision = adaptive_main.plan_step(policy(), {})
    assert decision['action'] == 'continue'
    assert decision['reason'].startswith(adaptive_main.CONTINUE_DIRECT)


def test_analysis_intent_write_is_blocked():
    decision = adaptive_main.plan_step(policy(), {'intent': 'analysis', 'write': True})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['approval']


def test_scope_change_flag_requires_approval():
    decision = adaptive_main.plan_step(policy(), {'scopeChange': True})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEEDS_APPROVAL)
    assert decision['requires'] == ['approval']


def test_intent_change_string_requires_approval():
    decision = adaptive_main.plan_step(policy(), {'intentChange': 'implementation'})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEEDS_APPROVAL)
    assert decision['requires'] == ['approval']


def test_empty_scope_change_object_fails_closed():
    decision = adaptive_main.plan_step(policy(), {'scopeChange': {}})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.NEEDS_APPROVAL)
    assert decision['requires'] == ['approval']


def test_false_scope_change_is_not_a_declared_change():
    decision = adaptive_main.plan_step(policy(), {'scopeChange': False})
    assert decision['action'] == 'continue'
    assert decision['requires'] == []


def test_scope_change_with_receipt_is_admitted():
    decision = adaptive_main.plan_step(policy(), {
        'scopeChange': {'receiptRef': 'admission@1', 'to': 'implementation'}})
    assert decision['action'] == 'continue'


# --------------------------------------------------------------------------- #
# plan_step — ngân sách, trần và chi phí
# --------------------------------------------------------------------------- #

def test_caller_declared_step_limit_blocks_with_consent_requirement():
    decision = adaptive_main.plan_step(policy(), {'limits': {'steps': 40}, 'stepsTaken': 40})
    assert decision['action'] == 'blocked'
    assert decision['reason'].startswith(adaptive_main.LIMIT_REACHED)
    assert decision['requires'] == ['consent']


def test_declared_limit_not_yet_reached_does_not_block():
    decision = adaptive_main.plan_step(policy(), {'limits': {'steps': 40}, 'stepsTaken': 39})
    assert decision['action'] == 'continue'


def test_no_declared_limit_does_not_invent_a_cutoff():
    decision = adaptive_main.plan_step(policy(), {'stepsTaken': 100000, 'elapsedSeconds': 10 ** 7})
    assert decision['action'] == 'continue'
    assert decision['requires'] == []


def test_unknown_cost_is_not_treated_as_zero():
    decision = adaptive_main.plan_step(policy(), {
        'branch': {'needed': True, 'reason': 'delegate'},
        'spend': {'certainty': 'unknown', 'amount': None}})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']
    assert decision['reason'].startswith(adaptive_main.NEEDS_CONSENT)


def test_estimated_cost_without_acceptance_requires_consent():
    decision = adaptive_main.plan_step(policy(), {
        'needsBudget': True, 'spend': {'certainty': 'estimated', 'amount': 3.0}})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']


def test_known_cost_with_basis_does_not_block():
    decision = adaptive_main.plan_step(policy(), {
        'spend': {'certainty': 'known', 'amount': 1.5},
        'budget': {'remaining': 10.0}})
    assert decision['action'] == 'continue'
    assert decision['requires'] == []


def test_budget_request_without_basis_requires_consent():
    decision = adaptive_main.plan_step(policy(), {'needsBudget': True})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']


def test_exhausted_declared_budget_requires_consent():
    decision = adaptive_main.plan_step(policy(), {
        'branch': {'needed': True, 'reason': 'delegate'},
        'budget': {'remaining': 0}})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']


def test_exhausted_budget_blocks_even_without_a_branch():
    decision = adaptive_main.plan_step(policy(), {'budget': {'remaining': 0}})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']


def test_unknown_remaining_budget_blocks_a_spend_proposal():
    decision = adaptive_main.plan_step(policy(), {
        'needsBudget': True, 'budget': {'remaining': None}})
    assert decision['action'] == 'blocked'
    assert decision['requires'] == ['consent']


def test_budget_reported_from_policy_never_invented():
    decision = adaptive_main.plan_step(
        policy(ceilingRef='alloc-7', outputTokensCeiling=8192),
        {'uncertainty': 'high', 'value': 'high', 'capability': full_capability(tokens=16000)})
    assert decision['budget'] == {'outputTokens': 8192, 'effort': 'high', 'ceilingRef': 'alloc-7'}


def test_budget_without_policy_declaration_reports_none_ref():
    decision = adaptive_main.plan_step(policy(), {'uncertainty': 'low', 'value': 'low'})
    assert decision['budget']['ceilingRef'] is None
    assert decision['budget']['outputTokens'] is None  # capability không rõ ⇒ không phát minh số


def test_invalid_effort_input_is_surfaced_in_the_decision():
    decision = adaptive_main.plan_step(policy(), {
        'uncertainty': 'hgih', 'value': 'high', 'capability': full_capability()})
    assert decision['action'] == 'continue'
    assert decision['reason'].startswith(adaptive_main.CONTINUE_DIRECT)
    assert decision['budget'] == {'outputTokens': None, 'effort': None, 'ceilingRef': None}
    assert 'effort input rejected' in decision['reason']
    assert 'ADAPTIVE_EFFORT_INPUT' in decision['reason']


# --------------------------------------------------------------------------- #
# compose
# --------------------------------------------------------------------------- #

def test_compose_uses_history_for_loop_detection():
    history = [{'signature': 'WORK_CHECK_FAILED', 'inputs': 'h1', 'evidenceRefs': ['log@1']}]
    observation = {'signature': {'signature': 'WORK_CHECK_FAILED', 'inputs': 'h1',
                                 'evidenceRefs': ['log@1']}}
    decision = adaptive_main.compose(policy(), observation, history)
    assert decision['loop']['repeat'] is True
    assert decision['action'] == 'blocked'


def test_compose_history_clears_with_new_evidence():
    history = [{'signature': 'WORK_CHECK_FAILED', 'inputs': 'h1', 'evidenceRefs': ['log@1']}]
    observation = {'signature': {'signature': 'WORK_CHECK_FAILED', 'inputs': 'h1',
                                 'evidenceRefs': ['log@1', 'log@2']}}
    decision = adaptive_main.compose(policy(), observation, history)
    assert decision['loop']['repeat'] is False
    assert decision['action'] == 'continue'


def test_compose_rejects_every_other_decision_with_reasons():
    decision = adaptive_main.compose(policy(), {'branch': {'needed': True, 'reason': 'x'}})
    rejected = decision_actions(decision)
    assert rejected == set(adaptive_main.DECISIONS) - {decision['action']}
    for item in decision['alternatives']:
        assert item['reason']
        assert 'evidenceRefs' in item


def test_decision_shape_is_exact():
    decision = adaptive_main.plan_step(policy(), {})
    assert set(decision) == {'action', 'reason', 'evidenceRefs', 'requires', 'budget',
                             'alternatives', 'loop', 'progress'}
    assert set(decision['budget']) == {'outputTokens', 'effort', 'ceilingRef'}
    assert set(decision['loop']) == {'repeat', 'code', 'action'}
    assert set(decision['progress']) == {'progress', 'kind', 'reasons'}
    assert decision['action'] in adaptive_main.DECISIONS
    assert decision['reason']


def test_compose_decision_carries_evidence_refs():
    observation = {'evidenceRefs': ['plan@2', 'check@5'],
                   'branch': {'needed': True, 'reason': 'x', 'evidenceRefs': ['brief@1']}}
    decision = adaptive_main.compose(policy(), observation)
    assert decision['evidenceRefs'] == ['plan@2', 'check@5', 'brief@1']


def test_compose_loop_repeat_carries_signature_evidence():
    observation = {'evidenceRefs': ['run@1'],
                   'loop': {'history': [{'signature': 'S', 'inputs': 'h', 'evidenceRefs': ['log@1']}],
                            'signature': {'signature': 'S', 'inputs': 'h', 'evidenceRefs': ['log@1']}}}
    decision = adaptive_main.compose(policy(), observation)
    assert decision['action'] == 'blocked'
    assert 'log@1' in decision['evidenceRefs']
    assert 'run@1' in decision['evidenceRefs']


def test_progress_field_reports_caller_signal():
    observation = {'previous': {'artifacts': []}, 'current': {'artifacts': ['plan@1']}}
    decision = adaptive_main.compose(policy(), observation)
    assert decision['progress']['progress'] is True
    assert decision['progress']['kind'] == 'artifact'


def test_compose_accepts_precomputed_progress_and_loop():
    observation = {'progress': {'progress': True, 'kind': 'evidence', 'reasons': ['new evidence']},
                   'loop': {'repeat': False, 'code': None, 'action': 'continue'}}
    decision = adaptive_main.compose(policy(), observation)
    assert decision['progress'] == {'progress': True, 'kind': 'evidence', 'reasons': ['new evidence']}
    assert decision['loop']['repeat'] is False


def test_requirements_vocabulary_is_bounded():
    assert adaptive_main.REQUIREMENTS == ('consent', 'capability', 'approval', 'user_decision')
    assert adaptive_main.DECISIONS == ('continue', 'branch', 'park', 'stop', 'blocked')
