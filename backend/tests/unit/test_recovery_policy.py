"""H3 — bảng luật hồi phục: một mã lỗi → một quyết định, và các bất biến không được nới.

Sáu bất biến của `recovery_policy` (ghi ở docstring module) mỗi cái có ít nhất một ca ghim riêng,
cộng thêm ca "mã lạ ⇒ fail closed" và ca mã thật của hệ đều phải khai lớp (không rơi `unknown`).
Không I/O, không model, không store: chỉ hàm thuần.
"""
import pytest

from agentbox.agent_core import recovery_policy as policy
from agentbox.agent_core.tool_contracts import REPLAY_SAFE, replay_class


def test_every_decision_has_the_same_shape():
    result = policy.decision('ROUTER_TIMEOUT')
    assert set(result) == {'code', 'class', 'action', 'replay', 'keepsPartial', 'checkpoint', 'reason'}
    assert result['class'] in policy.CLASSES and result['action'] in policy.ACTIONS
    assert isinstance(result['reason'], str) and result['reason']


def test_unknown_code_fails_closed_to_checkpoint():
    assert policy.classify('SOMETHING_NEW') == 'unknown'
    assert policy.classify(None) == 'unknown' and policy.classify('') == 'unknown'
    result = policy.decision('SOMETHING_NEW')
    assert result['action'] == 'checkpoint_and_ask' and result['replay'] is False
    assert result['checkpoint'] is True
    assert policy.is_transient('SOMETHING_NEW') is False


def test_declared_codes_never_fall_through_to_unknown():
    """Mã trong bảng phải trỏ tới lớp thật; một mã gõ sai sẽ lộ ngay ở đây."""
    assert policy.CODES, 'bảng mã không được rỗng'
    for code, cls in policy.CODES.items():
        assert cls in policy.CLASSES, f'{code} trỏ tới lớp lạ {cls!r}'
        assert policy.classify(code) == cls
        assert policy.decision(code)['class'] == cls


def test_transport_is_the_only_transient_class():
    assert policy.is_transient('ROUTER_HTTP_429') is True
    assert policy.is_transient('ROUTER_UNREACHABLE') is True
    assert policy.is_transient('WORK_CAPABILITY_REVOKED') is False
    assert policy.is_transient('TOOL_INTERRUPTED_UNSAFE') is False
    assert policy.decision('ROUTER_HTTP_503')['action'] == 'retry_backoff'
    assert policy.decision('ROUTER_HTTP_503')['checkpoint'] is False


def test_retry_after_is_reported_without_changing_the_action():
    result = policy.decision('ROUTER_HTTP_429', retry_after=30)
    assert result['action'] == 'retry_backoff' and 'Retry-After=30' in result['reason']


# --- 1. Mutation kết quả không rõ: KHÔNG BAO GIỜ replay -----------------------------------

def test_unknown_outcome_mutation_is_never_replayed():
    for safe in (False, True):
        result = policy.decision('TOOL_INTERRUPTED_UNSAFE', replay_safe=safe, has_receipt=False)
        assert result['replay'] is False, 'nhãn replay-safe của tool không biến mutation thành replay được'
        assert result['action'] == 'inspect_only'
        assert result['keepsPartial'] is True
        assert 'TUYỆT ĐỐI không chạy lại mutation' in result['reason']


def test_no_class_ever_returns_replay_true_today():
    """Chưa lớp nào được phép replay: transport thử lại REQUEST, không chạy lại tool."""
    for code in policy.CODES:
        assert policy.decision(code, replay_safe=True, has_receipt=True)['replay'] is False


def test_replay_safe_tools_are_a_declared_subset():
    """Cặp đôi với `tool_contracts`: chỉ tool khai `safe` mới được xét replay ở tầng tool."""
    assert isinstance(REPLAY_SAFE, (set, frozenset))
    assert 'file_read' in REPLAY_SAFE and 'file_write' not in REPLAY_SAFE
    assert replay_class('file_read') == 'safe' and replay_class('file_write') != 'safe'


# --- 2. Quyền/ngân sách/epoch: không transient --------------------------------------------

def test_rights_and_budget_never_retry():
    for code in ('WORK_CAPABILITY_REVOKED', 'WORK_SCOPE_ARTIFACT_ONLY', 'WORK_SCOPE_DELEGATE_ROLE',
                 'WORK_DECISION_KEYS_INVALID', 'TASK_ATTEMPT_CONFLICT', 'TASK_ATTEMPT_BINDING'):
        result = policy.decision(code, attempts=9)
        assert result['class'] == 'rights_budget', code
        assert result['action'] == 'checkpoint_and_ask', code
        assert result['replay'] is False and result['checkpoint'] is True
        assert policy.is_transient(code) is False
        assert 'không retry để vượt consent' in result['reason']


# --- 3. Hết output: giữ phần đã có --------------------------------------------------------

def test_output_limit_keeps_the_partial_work():
    for code in ('PROVIDER_OUTPUT_TRUNCATED', 'ANSWER_TOO_LONG', 'STEP_BUDGET_EXHAUSTED',
                 'DEADLINE_EXCEEDED'):
        result = policy.decision(code)
        assert result['class'] == 'output_limit'
        assert result['action'] == 'keep_partial' and result['keepsPartial'] is True
        assert result['replay'] is False
    assert policy.keeps_partial('PROVIDER_OUTPUT_TRUNCATED') is True
    assert policy.keeps_partial('WORK_CAPABILITY_REVOKED') is False


# --- 4. Lỗi schema: sửa input -------------------------------------------------------------

def test_validation_errors_fix_input_instead_of_repeating_the_payload():
    result = policy.decision('TOOL_ARG_INVALID')
    assert result['class'] == 'tool_validation' and result['action'] == 'fix_input'
    assert 'không lặp nguyên payload' in result['reason']
    assert result['keepsPartial'] is False
    receipt = policy.decision('TOOL_NOT_STARTED', has_receipt=True)
    assert 'dùng lại kết quả đã commit' in receipt['reason']


# --- 5. Rỗng/reasoning-only/từ chối -------------------------------------------------------

def test_empty_response_retries_exactly_once_then_stops():
    first = policy.decision('TURN_EMPTY_RESPONSE_RETRY', attempts=0)
    assert first['action'] == 'recover_model' and 'đúng một lần' in first['reason']
    second = policy.decision('TURN_EMPTY_RESPONSE_RETRY', attempts=1)
    assert second['action'] == 'stop' and second['replay'] is False
    assert 'không lách từ chối bằng vòng retry' in second['reason']


def test_reasoning_only_and_refusal_are_distinguished_from_a_plain_empty_answer():
    for code in ('PROVIDER_REASONING_ONLY', 'PROVIDER_REFUSAL'):
        assert policy.classify(code) == 'provider_empty'
        assert policy.decision(code, attempts=0)['action'] == 'recover_model'


def test_stream_interruption_recovers_the_model_not_the_tool():
    result = policy.decision('PROVIDER_STREAM_INTERRUPTED', replay_safe=True, has_receipt=True)
    assert result['class'] == 'provider_stream' and result['action'] == 'recover_model'
    assert result['replay'] is False and result['keepsPartial'] is True
    assert 'không replay tool đã thực thi' in result['reason']


# --- 6. Không tiến triển: đổi cách, không lặp vô hạn --------------------------------------

@pytest.mark.parametrize('code', ['WORK_NO_PROGRESS', 'WORK_CHECK_EXHAUSTED', 'WORK_REPAIR_LIMIT',
                                  'WORK_LOOKUP_UNVERIFIED', 'WORK_PRODUCER_INCOMPLETE',
                                  'WORK_REPAIR_UNDIAGNOSED'])
def test_no_progress_changes_the_approach(code):
    result = policy.decision(code, attempts=5)
    assert result['class'] == 'no_progress' and result['action'] == 'change_approach'
    assert result['keepsPartial'] is True and result['replay'] is False
    assert 'không lặp lại vô hạn' in result['reason']
