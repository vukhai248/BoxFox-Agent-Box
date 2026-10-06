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


#: Mã do bề mặt task/job/decision sinh ra (H3–H4), đo sống 2026-10-05. Cùng luật với
#: `LIVE_PROVIDER_CODES`: thiếu một mã ở đây nghĩa là lỗi thật bị xếp `unknown` ⇒ checkpoint oan.
LIVE_SURFACE_CODES = ('HARNESS_CONTRACT_INVALID', 'HARNESS_SCHEMA_UNSUPPORTED',
                      'TASK_SCHEMA_UNSUPPORTED', 'TASK_DELEGATE_ROLE_MISMATCH',
                      'TASK_SURFACE_NO_RUN', 'TASK_ALIAS_CONFLICT', 'TASK_INVOCATION_CONFLICT',
                      'TASK_MESSAGE_CONFLICT', 'DECISION_INVALID', 'JOB_OWNERSHIP_REQUIRED',
                      'JOB_EXECUTOR_UNSUPPORTED', 'JOB_PREDICATE_UNSUPPORTED', 'JOB_HANDLE_STALE',
                      'TASK_UNKNOWN', 'TASK_RUN_UNKNOWN', 'TASK_CHILD_UNKNOWN',
                      'TASK_ATTEMPT_UNKNOWN', 'JOB_UNKNOWN', 'JOB_ADMISSION_REQUIRED',
                      'TASK_OWNER_MISMATCH', 'TASK_REVISION_CONFLICT',
                      'WEB_SEARCH_UNAVAILABLE', 'WEB_SEARCH_EMPTY')


@pytest.mark.parametrize('code', LIVE_SURFACE_CODES)
def test_live_surface_codes_have_a_declared_class(code):
    assert policy.classify(code) != 'unknown', f'{code} rơi vào unknown: lỗi thật bị checkpoint oan'


def test_a_bad_task_contract_tells_the_model_to_fix_the_field_not_to_stop():
    """Đo sống 2026-10-05: model yếu gửi hợp đồng sai kiểu, bị từ chối rồi DỪNG hỏi chủ nhà."""
    result = policy.decision('HARNESS_CONTRACT_INVALID')
    assert result['class'] == 'tool_validation' and result['action'] == 'fix_input'
    assert result['replay'] is False and result['keepsPartial'] is False
    assert 'sửa trường/đổi cách gọi' in result['reason']
    assert policy.may_retry(result) is False, 'fix_input là sửa rồi gọi lại, không phải vé replay tool'


def test_admission_and_ownership_stay_with_the_owner():
    for code in ('JOB_ADMISSION_REQUIRED', 'TASK_OWNER_MISMATCH', 'TASK_REVISION_CONFLICT'):
        result = policy.decision(code)
        assert result['action'] == 'checkpoint_and_ask', code
        assert result['replay'] is False and policy.may_retry(result) is False


def test_integrity_codes_still_fail_closed_to_unknown():
    for code in ('TASK_BIND_FAILED', 'TASK_CHILD_BINDING', 'TASK_CONTRACT_CORRUPT',
                 'TASK_RECORD_CORRUPT'):
        assert policy.classify(code) == 'unknown', code
        assert policy.decision(code)['action'] == 'checkpoint_and_ask'


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


# --- 7. Mã THẬT của hệ (failures.classify) phải có lớp, không rơi `unknown` ---------------

#: Mã do `failures.classify` sinh ra cho lỗi router/provider; đo 2026-10-04 bằng probe trên
#: cây này. Thiếu một mã ở đây nghĩa là lỗi thật sẽ bị xếp `unknown` ⇒ checkpoint oan.
LIVE_PROVIDER_CODES = ('UPSTREAM_TIMEOUT', 'UPSTREAM_UNREACHABLE', 'UPSTREAM_HTTP_429',
                       'UPSTREAM_HTTP_502', 'UPSTREAM_HTTP_503', 'UPSTREAM_HTTP_504',
                       'UPSTREAM_RETRY_EXHAUSTED', 'UPSTREAM_REFUSAL',
                       'PROVIDER_COMPLETION_FAILED', 'TURN_EMPTY_RESPONSE', 'TURN_EMPTY_STREAM',
                       'RATE_LIMIT', 'CAPACITY', 'TOOL_NOT_PERMITTED', 'TURN_TOOL_BATCH')


@pytest.mark.parametrize('code', LIVE_PROVIDER_CODES)
def test_live_provider_codes_have_a_declared_class(code):
    assert policy.classify(code) != 'unknown', f'{code} rơi vào unknown: lỗi thật bị checkpoint oan'


def test_timeout_and_exhausted_never_retry_in_the_same_window():
    for code in ('UPSTREAM_TIMEOUT', 'UPSTREAM_RETRY_EXHAUSTED'):
        result = policy.decision(code)
        assert result['action'] == 'checkpoint_and_ask', code
        assert result['replay'] is False and result['checkpoint'] is True
        assert result['keepsPartial'] is True, 'phần đã làm được vẫn phải giữ'
        assert policy.is_transient(code) is False
        assert policy.keeps_partial(code) is True


def test_repeated_transport_failures_escalate_instead_of_retrying_forever():
    assert policy.decision('UPSTREAM_UNREACHABLE', attempts=0)['action'] == 'retry_backoff'
    assert policy.decision('UPSTREAM_UNREACHABLE', attempts=1)['action'] == 'retry_backoff'
    escalated = policy.decision('UPSTREAM_UNREACHABLE', attempts=policy._TRANSPORT_RETRIES)
    assert escalated['action'] == 'checkpoint_and_ask' and escalated['replay'] is False


def test_rate_limit_keeps_the_retry_after_hint():
    result = policy.decision('UPSTREAM_HTTP_429', retry_after=12)
    assert result['action'] == 'retry_backoff' and 'Retry-After=12' in result['reason']
    assert policy.is_transient('RATE_LIMIT') is True and policy.is_transient('CAPACITY') is True


def test_permission_and_batch_codes_are_not_transient():
    assert policy.decision('TOOL_NOT_PERMITTED')['action'] == 'checkpoint_and_ask'
    assert policy.decision('TURN_TOOL_BATCH')['action'] == 'fix_input'
    assert policy.is_transient('TOOL_NOT_PERMITTED') is False


def test_a_missing_search_backend_asks_the_owner_instead_of_retrying_the_query():
    """F05: lỗi cấu hình/hạ tầng tìm kiếm phải dừng ở checkpoint, KHÔNG xui đổi truy vấn."""
    result = policy.decision('WEB_SEARCH_UNAVAILABLE')
    assert result['class'] == 'capability_gap'
    assert result['action'] == 'checkpoint_and_ask'
    assert result['replay'] is False
    assert 'đừng lặp truy vấn' in result['reason']


def test_an_empty_search_changes_the_approach():
    result = policy.decision('WEB_SEARCH_EMPTY')
    assert result['class'] == 'no_progress'
    assert result['action'] == 'change_approach'
    assert result['replay'] is False
