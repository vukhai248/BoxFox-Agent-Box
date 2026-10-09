"""H3 — bảng luật hồi phục: một mã lỗi → một quyết định, và các bất biến không được nới.

Sáu bất biến của `recovery_policy` (ghi ở docstring module) mỗi cái có ít nhất một ca ghim riêng,
cộng thêm ca "mã lạ ⇒ fail closed" và ca mã thật của hệ đều phải khai lớp (không rơi `unknown`).
Không model, không store, không mạng: chỉ hàm thuần — riêng §9 đọc hai tệp văn bản (tài liệu phân
loại + i18n của panel) làm chốt chống trôi giữa ba bề mặt giải thích một mã lỗi.
"""
import re
from pathlib import Path

import pytest

from agentbox.agent_core import recovery_policy as policy
from agentbox.agent_core.tool_contracts import REPLAY_SAFE, replay_class
from agentbox.sandbox import host_executor as host_executor_module
from agentbox.sandbox.win import errors as win_errors

#: Câu mà MỌI mã chưa khai nhận được (fail closed). Mã host/CUA phải có câu riêng, khác câu này.
UNKNOWN_SENTENCE = 'không rõ loại lỗi: dừng ở checkpoint và hỏi chủ nhà'


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


# --- 8. Mã host/CUA (đo sống 2026-10-08): mỗi mã phải có lớp VÀ lời khuyên riêng ------------

#: Mã đường host phát ra mà ba nguồn máy đọc được ở dưới KHÔNG liệt kê (đọc thẳng trong mã nguồn):
#: `host_executor.py:503/505` (lỗi của công cụ tệp), `host_executor._inspect_element` và
#: `agent_core/cua_target.py`, `machine_router.py:875` + `api/server.py:1150` (route của panel).
#: Vẫn phải có lớp + lời khuyên: đo 2026-10-08 chúng rơi `unknown` ⇒ agent nhận câu "không rõ loại lỗi".
EXTRA_HOST_PATH_CODES = ('TARGET_KIND_INVALID', 'INSPECT_FAILED', 'FILE_NOT_FOUND',
                         'FILE_PERMISSION_DENIED', 'INSPECT_POINT_INVALID')

#: Mọi mã mà bề mặt host/CUA phát ra, lấy từ chính mã nguồn chứ không gõ tay danh sách: hai bảng
#: của `sandbox/win/errors.py` cộng các hằng `*_CODE` của `sandbox/host_executor.py`. Thiếu một mã ở
#: đây nghĩa là lỗi CUA thật bị xếp `unknown` ⇒ agent nhận câu "không rõ loại lỗi" rồi nghĩ lại vô ích.
HOST_SURFACE_CODES = sorted(
    set(win_errors.ACTION_CODES) | set(win_errors.EMITTED_INSPECT_REASONS)
    | {value for name, value in vars(host_executor_module).items()
       if name.endswith('_CODE') and isinstance(value, str)}
    | set(EXTRA_HOST_PATH_CODES))


def test_the_host_surface_code_list_is_not_empty():
    """Chốt chặn của chính danh sách: một lần đổi tên hằng sẽ làm bộ test rỗng im lặng."""
    assert len(HOST_SURFACE_CODES) >= 40
    assert 'PERMISSION_DENIED' in HOST_SURFACE_CODES  # mã đo được trong sổ thật
    assert 'COMMAND_EXIT_NONZERO' in HOST_SURFACE_CODES  # mã của ca "đỏ mà không có mã"
    assert 'uia_unavailable' in HOST_SURFACE_CODES  # mã chữ thường, dễ sót khi khai tay
    assert set(EXTRA_HOST_PATH_CODES) <= set(HOST_SURFACE_CODES)


@pytest.mark.parametrize('code', HOST_SURFACE_CODES)
def test_every_host_surface_code_has_a_declared_class(code):
    assert policy.classify(code) != 'unknown', f'{code} rơi vào unknown: lỗi CUA bị checkpoint oan'


@pytest.mark.parametrize('code', HOST_SURFACE_CODES)
def test_every_host_surface_code_gets_its_own_advice_not_the_unknown_sentence(code):
    result = policy.decision(code)
    assert result['reason'] != UNKNOWN_SENTENCE, f'{code} vẫn nhận câu "không rõ loại lỗi"'
    assert policy.advice(code) == (result['class'], result['action'], result['reason'])


def test_the_host_advice_table_and_the_class_table_cannot_drift():
    for code, (klass, action, reason) in policy._HOST_ADVICE.items():
        assert klass in policy.CLASSES, code
        assert action in policy.ACTIONS, code
        assert action == policy._ACTIONS[klass], f'{code}: hành động lệch bảng lớp'
        assert reason and reason != UNKNOWN_SENTENCE, code
        assert policy.CODES[code] == klass, f'{code}: CODES không khớp _HOST_ADVICE'


def test_no_host_code_ever_retries_automatically():
    """CUA là tay máy thật: thử lại là quyết định của model sau khi đã nhìn lại màn hình."""
    assert policy._MAY_RETRY == {'transport'}
    assert policy.RETRY_ACTIONS == ('retry_backoff', 'recover_model')
    for code in HOST_SURFACE_CODES:
        result = policy.decision(code, replay_safe=True, has_receipt=True)
        assert policy.is_transient(code) is False, code
        assert policy.may_retry(result) is False, code
        assert result['replay'] is False, code


@pytest.mark.parametrize('code,klass,action,needle', [
    ('HUMAN_HAS_CONTROL', 'rights_budget', 'checkpoint_and_ask', 'KHÔNG gửi thao tác'),
    ('DESKTOP_LOCKED', 'rights_budget', 'checkpoint_and_ask', 'khoá'),
    ('PERMISSION_DENIED', 'rights_budget', 'checkpoint_and_ask', 'xin chủ nhà'),
    ('APPROVAL_DENIED', 'rights_budget', 'checkpoint_and_ask', 'từ chối'),
    ('ELEMENT_STALE', 'tool_unknown', 'inspect_only', 'chụp lại'),
    ('SOURCE_CHANGED', 'tool_unknown', 'inspect_only', 'chọn lại'),
    ('TARGET_UNKNOWN', 'tool_unknown', 'inspect_only', 'chọn lại đích'),
    ('CONTROL_BUSY', 'tool_unknown', 'inspect_only', 'MỘT lần'),
    ('cdp_timeout', 'tool_unknown', 'inspect_only', 'thời gian chờ'),
    ('TARGET_REQUIRED', 'tool_validation', 'fix_input', 'chọn một cửa sổ'),
    ('TARGET_AMBIGUOUS', 'tool_validation', 'fix_input', 'windowId'),
    ('CUA_MACHINE_SCOPE_REQUIRED', 'tool_validation', 'fix_input', 'machine'),
    ('UNSUPPORTED_ACTION', 'tool_validation', 'fix_input', 'enum'),
    ('COMMAND_EXIT_NONZERO', 'tool_validation', 'fix_input', 'exit_code'),
    ('CUA_UNAVAILABLE', 'capability_gap', 'checkpoint_and_ask', 'gói cần cài'),
    ('UIA_UNAVAILABLE', 'capability_gap', 'checkpoint_and_ask', 'UIA'),
    ('CAPTURE_FAILED', 'capability_gap', 'checkpoint_and_ask', 'chụp'),
    ('PASSWORD_FIELD_REFUSED', 'capability_gap', 'checkpoint_and_ask', 'mật khẩu'),
    ('COMMAND_TIMEOUT', 'no_progress', 'change_approach', 'chia nhỏ'),
    ('HOST_TOOL_FAILED', 'no_progress', 'change_approach', 'đổi cách'),
    ('FILE_NOT_FOUND', 'tool_validation', 'fix_input', 'không tìm thấy tệp'),
    ('FILE_PERMISSION_DENIED', 'rights_budget', 'checkpoint_and_ask', 'xin chủ nhà'),
    ('INSPECT_POINT_INVALID', 'tool_validation', 'fix_input', 'vùng chụp'),
])
def test_representative_host_codes_carry_the_decided_class_and_advice(code, klass, action, needle):
    """Bảng quyết định của kế hoạch: đổi một dòng trong `_HOST_ADVICE` là lộ ngay ở đây."""
    result = policy.decision(code)
    assert (result['class'], result['action']) == (klass, action)
    assert needle in result['reason'], result['reason']
    assert result['replay'] is False


def test_advice_is_none_outside_the_host_table():
    for code in ('UPSTREAM_TIMEOUT', 'WORK_NO_PROGRESS', 'WEB_SEARCH_UNAVAILABLE',
                 'NEW_UNKNOWN_CODE', None, ''):
        assert policy.advice(code) is None, code


def test_a_brand_new_code_still_fails_closed():
    """Luật fail-closed KHÔNG bị nới: mã chưa từng khai vẫn `unknown`/`checkpoint_and_ask`."""
    result = policy.decision('NEW_UNKNOWN_CODE')
    assert result['class'] == 'unknown' and result['action'] == 'checkpoint_and_ask'
    assert result['reason'] == UNKNOWN_SENTENCE
    assert result['checkpoint'] is True and result['replay'] is False
    assert result['keepsPartial'] is False


# --- 9. Chống trôi giữa ba bề mặt: tài liệu phân loại + câu tiếng Việt của panel ---------------

#: Mã chỉ có ở bề mặt **panel-i18n** (câu cho chủ nhà) và **không bao giờ** tới tay agent, nên
#: không có lớp hồi phục — miễn trừ có lý do, không phải bỏ sót:
#: - `not_chromium`: `sandbox/win/errors.py:119` ghi rõ "deliberately never emitted" — chỉ là từ
#:   vựng của nhánh thoái hoá mềm, không phải mã lỗi; khai lớp cho nó là đoán.
#: `INSPECT_POINT_INVALID` từng ở đây và đã được khai lớp (2026-10-08, chủ nhà quyết): hai route của
#: panel ném nó ra thật, việc cần làm rõ ràng. Danh sách này KHÔNG được nới mà không ghi lý do — và
#: tự nó cũng bị ghim: miễn trừ thừa (mã đã được khai lớp) sẽ làm test đỏ.
PANEL_ONLY_CODES = {'not_chromium'}

I18N_PATH = Path(__file__).resolve().parents[3] / 'frontend' / 'src' / 'i18n' / 'vi.ts'
DOC_PATH = Path(__file__).resolve().parents[3] / 'docs' / 'architecture' / 'host-desktop-control.md'


def _strip_string_literals(text):
    """Bỏ mọi chuỗi trong dấu nháy để chữ trong câu tiếng Việt không bị đọc nhầm thành khoá."""
    for quote in ("'", '"', '`'):
        text = re.sub(quote + r'(?:[^' + quote + r'\\]|\\.)*' + quote, '""', text)
    return text


def _object_keys(text, name):
    """Khoá trực tiếp của khối `<name>: { … }` — đếm ngoặc, không cần TypeScript."""
    start = text.index(name + ': {') + len(name) + 3
    depth, end = 1, start
    while end < len(text) and depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    body = _strip_string_literals(text[start:end - 1])
    return re.findall(r'(?m)^\s*([A-Za-z_][A-Za-z0-9_]*):', body)


def test_the_panel_i18n_surface_never_gains_a_code_without_a_class():
    """Bề mặt thứ ba: câu tiếng Việt cho panel. Mã mới thêm vào đây mà chưa khai lớp là lộ ngay."""
    if not I18N_PATH.exists():  # test vẫn chạy được khi chỉ có backend/
        pytest.skip('không thấy frontend/src/i18n/vi.ts')
    text = I18N_PATH.read_text(encoding='utf-8')
    keys = _object_keys(text, 'hostError') + _object_keys(text, 'desktopReason')
    assert len(keys) >= 30, f'chỉ đọc được {len(keys)} khoá — hàm đọc khoá đã hỏng'
    unknown = {key for key in keys if policy.classify(key) == 'unknown'}
    assert unknown == PANEL_ONLY_CODES, (
        f'mã panel chưa khai lớp: {sorted(unknown - PANEL_ONLY_CODES)}; '
        f'miễn trừ đã cũ: {sorted(PANEL_ONLY_CODES - unknown)}')


def _doc_table_pairs():
    """Bảng quyết định §6.2.1: gom mọi mã trong một ô thành `mã → (lớp, hành động)`."""
    text = DOC_PATH.read_text(encoding='utf-8')
    _, found, rest = text.partition('### 6.2.1')
    if not found:  # mục bị dời/đổi tên: không ghim được, nhưng cũng không báo động giả
        pytest.skip('mục §6.2.1 không còn trong tài liệu')
    section = re.split(r'(?m)^#{1,6} ', rest, maxsplit=1)[0]
    pairs = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if len(cells) < 3:
            continue
        klass, action = cells[1].strip('`'), cells[2].strip('`')
        if klass in policy.CLASSES and action in policy.ACTIONS:
            for code in re.findall(r'`([^`]+)`', cells[0]):
                pairs[code] = (klass, action)
    return pairs


def test_the_doc_table_and_the_policy_cannot_drift():
    """Luật ở §6.2.1: mã mới phải vào bảng tài liệu TRƯỚC, rồi mới vào `_HOST_ADVICE`."""
    if not DOC_PATH.exists():
        pytest.skip('không thấy docs/architecture/host-desktop-control.md')
    pairs = _doc_table_pairs()
    assert len(pairs) >= 8, f'bảng §6.2.1 đọc được {len(pairs)} mã — hàm đọc bảng đã hỏng'
    assert set(pairs) == set(policy._HOST_ADVICE), (
        f'thiếu ở tài liệu: {sorted(set(policy._HOST_ADVICE) - set(pairs))}; '
        f'thừa trong tài liệu: {sorted(set(pairs) - set(policy._HOST_ADVICE))}')
    for code, (klass, action) in pairs.items():
        assert (klass, action) == policy._HOST_ADVICE[code][:2], code
