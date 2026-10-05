"""Phân loại hồi phục: một mã lỗi → một quyết định, không có "retry N lần" chung.

Kế hoạch v1 §7 chốt: tách hồi phục theo **loại lỗi**, vì mỗi loại có hành vi đúng khác nhau.
Module này là bảng luật thuần (không I/O, không model, không store):

- `classify(code)` — mã lỗi thật của hệ → một lớp trong `CLASSES`.
- `decision(code, ...)` — lớp + ngữ cảnh → quyết định có `action`, `replay`, `reason`, `keepsPartial`.

Bất biến (kiểm bằng test):

1. Mutation có kết quả không rõ (`TOOL_INTERRUPTED_UNSAFE`) **không bao giờ** replay.
2. Lỗi quyền/ngân sách/epoch không phải lỗi tạm thời: không retry, phải checkpoint + hỏi.
3. Hết output thì **giữ phần đã có**, không âm thầm tăng trần cho mọi vai.
4. Lỗi schema/validation không phải transient: sửa input, không lặp nguyên payload.
5. Empty/reasoning-only/refusal phân biệt được: empty có đúng một lần thử lại, còn lại dừng/hỏi đổi route.
6. Mã lạ ⇒ fail closed: checkpoint + hỏi, không đoán.

Nối runtime (H8a): công tắc `BOXFOX_RECOVERY_POLICY` (mặc định BẬT từ v2, #6599). Khi bật, runtime
(a) ghi quyết định của module vào kết quả tool lỗi và event `error`, và (b) dùng
quyết định làm **cổng chỉ-chặn**: mã nào module nói `checkpoint_and_ask`/`stop` mà
vòng retry cũ định thử lại thì bị chặn (`RECOVERY_POLICY_DENIED`). Cổng không bao giờ
THÊM một lần thử lại — hôm nay nó khớp `failures.retry_advice` từng mã (H3.7), nên
bật công tắc không đổi hành vi; nó là lưới cho các mã mới.
"""

from . import feature_switches

#: Công tắc giết khi nối vào runtime: mặc định BẬT từ v2 (#6599), tắt tường minh bằng `off`.
SWITCH = 'BOXFOX_RECOVERY_POLICY'

#: Hai hành động mà module nói "được phép chạy lại việc"; mọi hành động khác là dừng/giữ.
RETRY_ACTIONS = ('retry_backoff', 'recover_model')

#: Lớp hồi phục. Thứ tự này cũng là thứ tự ưu tiên khi một mã khớp nhiều luật.
CLASSES = ('transport', 'provider_stream', 'provider_empty', 'output_limit', 'tool_validation',
           'tool_unknown', 'rights_budget', 'no_progress', 'unknown')

#: Hành động đề xuất. `retry_backoff` và `recover_model` là hai hành động *được phép thử lại*;
#: mọi hành động còn lại không tự chạy lại việc đã làm.
ACTIONS = ('retry_backoff', 'recover_model', 'keep_partial', 'fix_input', 'inspect_only',
           'checkpoint_and_ask', 'change_approach', 'stop')

#: Mã → lớp. Chỉ nhận mã thật đang tồn tại trong hệ; mã không có ở đây rơi vào `unknown` (fail closed).
CODES = {
    # Transport / rate limit. Nguồn mã THẬT là `failures.classify`: router báo
    # `UPSTREAM_*`/`RATE_LIMIT`/`CAPACITY`, còn `ROUTER_*` là bí danh cũ giữ lại để
    # record lịch sử vẫn phân loại được.
    'UPSTREAM_UNREACHABLE': 'transport',
    'UPSTREAM_HTTP_408': 'transport',
    'UPSTREAM_HTTP_409': 'transport',
    'UPSTREAM_HTTP_425': 'transport',
    'UPSTREAM_HTTP_429': 'transport',
    'UPSTREAM_HTTP_500': 'transport',
    'UPSTREAM_HTTP_502': 'transport',
    'UPSTREAM_HTTP_503': 'transport',
    'UPSTREAM_HTTP_504': 'transport',
    'RATE_LIMIT': 'transport',
    'CAPACITY': 'transport',
    'ROUTER_TIMEOUT': 'transport',
    'ROUTER_HTTP_429': 'transport',
    'ROUTER_HTTP_502': 'transport',
    'ROUTER_HTTP_503': 'transport',
    'ROUTER_HTTP_504': 'transport',
    'ROUTER_UNREACHABLE': 'transport',
    # Timeout và cạn-retry cũng thuộc họ transport nhưng KHÔNG thử lại trong cùng cửa sổ
    # (khớp `failures.py`: cửa sổ đã tiêu, gọi lại bắt đầu từ 0); `decision` xử riêng.
    'UPSTREAM_TIMEOUT': 'transport',
    'UPSTREAM_RETRY_EXHAUSTED': 'transport',
    # Provider stream thiếu terminal / bị cắt giữa dòng.
    'PROVIDER_STREAM_INTERRUPTED': 'provider_stream',
    'PROVIDER_ERROR': 'provider_stream',
    'PROVIDER_COMPLETION_FAILED': 'provider_stream',
    'TURN_EMPTY_STREAM': 'provider_stream',
    # Provider trả rỗng / chỉ reasoning / từ chối.
    'PROVIDER_REASONING_ONLY': 'provider_empty',
    'TURN_EMPTY_RESPONSE': 'provider_empty',
    'TURN_EMPTY_RESPONSE_RETRY': 'provider_empty',
    'PROVIDER_REFUSAL': 'provider_empty',
    'UPSTREAM_REFUSAL': 'provider_empty',
    # Hết chỗ output / câu trả lời quá dài.
    'PROVIDER_OUTPUT_TRUNCATED': 'output_limit',
    'ANSWER_TOO_LONG': 'output_limit',
    'OUTPUT_LIMIT': 'output_limit',
    'STEP_BUDGET_EXHAUSTED': 'output_limit',
    'DEADLINE_EXCEEDED': 'output_limit',
    # Tool schema/validation: sửa input, không lặp payload cũ.
    'TOOL_ARG_INVALID': 'tool_validation',
    'TOOL_NOT_STARTED': 'tool_validation',
    'TOOL_REPLAY_PENDING': 'tool_validation',
    'TURN_TOOL_BATCH': 'tool_validation',
    # Bề mặt task/job/decision (H3–H4). Đo sống 2026-10-05: model yếu gọi `delegate_task`
    # kèm hợp đồng sai kiểu mảng, bị `HARNESS_CONTRACT_INVALID`, rồi KHÔNG sửa mà dừng hỏi
    # chủ nhà — vì mã chưa khai nên rơi `unknown` ⇒ `checkpoint_and_ask`. Hợp đồng/đối số
    # sai là việc model sửa được: khai `tool_validation` để lời khuyên là `fix_input`
    # ("sửa trường/đổi cách gọi"), đúng như `reflection_hint` đã nói.
    'HARNESS_CONTRACT_INVALID': 'tool_validation',
    'HARNESS_SCHEMA_UNSUPPORTED': 'tool_validation',
    'TASK_SCHEMA_UNSUPPORTED': 'tool_validation',
    'TASK_DELEGATE_ROLE_MISMATCH': 'tool_validation',
    'TASK_SURFACE_NO_RUN': 'tool_validation',
    'TASK_ALIAS_CONFLICT': 'tool_validation',
    'TASK_INVOCATION_CONFLICT': 'tool_validation',
    'TASK_MESSAGE_CONFLICT': 'tool_validation',
    'DECISION_INVALID': 'tool_validation',
    'JOB_OWNERSHIP_REQUIRED': 'tool_validation',
    'JOB_EXECUTOR_UNSUPPORTED': 'tool_validation',
    'JOB_PREDICATE_UNSUPPORTED': 'tool_validation',
    'JOB_HANDLE_STALE': 'tool_validation',
    # Id không tồn tại: đọc lại rồi gọi bằng id đúng — vẫn là lỗi đối số, không phải quyền.
    'TASK_UNKNOWN': 'tool_validation',
    'TASK_RUN_UNKNOWN': 'tool_validation',
    'TASK_CHILD_UNKNOWN': 'tool_validation',
    'TASK_ATTEMPT_UNKNOWN': 'tool_validation',
    'JOB_UNKNOWN': 'tool_validation',
    # Quyền: công cụ bị từ chối là chuyện quyền, không phải lỗi tạm thời.
    'TOOL_NOT_PERMITTED': 'rights_budget',
    # Nhập học/owner/revision của bề mặt task–job: không tự retry để vượt quyền.
    'JOB_ADMISSION_REQUIRED': 'rights_budget',
    'TASK_OWNER_MISMATCH': 'rights_budget',
    'TASK_REVISION_CONFLICT': 'rights_budget',
    # Mutation có kết quả không rõ: chỉ được soi, không replay.
    'TOOL_INTERRUPTED_UNSAFE': 'tool_unknown',
    'WORK_SHIP_IN_PROGRESS': 'tool_unknown',
    # Quyền / ngân sách / epoch / phạm vi: dừng và hỏi, không retry.
    'WORK_CAPABILITY_REVOKED': 'rights_budget',
    'WORK_SCOPE_ARTIFACT_ONLY': 'rights_budget',
    'WORK_SCOPE_TERMINAL_MUTATING': 'rights_budget',
    'WORK_SCOPE_DELEGATE_ROLE': 'rights_budget',
    'WORK_DECISION_KEYS_INVALID': 'rights_budget',
    'WORK_RESUME_BUSY': 'rights_budget',
    'WORK_RESUME_NO_PROGRESS': 'rights_budget',
    'TASK_ATTEMPT_BINDING': 'rights_budget',
    'TASK_ATTEMPT_CONFLICT': 'rights_budget',
    # Không có tiến triển thật.
    'WORK_NO_PROGRESS': 'no_progress',
    'WORK_PRODUCER_INCOMPLETE': 'no_progress',
    'WORK_CHECK_EXHAUSTED': 'no_progress',
    'WORK_REPAIR_UNDIAGNOSED': 'no_progress',
    'WORK_REPAIR_LIMIT': 'no_progress',
    'WORK_LOOKUP_UNVERIFIED': 'no_progress',
}

#: Lớp → hành động mặc định.
_ACTIONS = {
    'transport': 'retry_backoff',
    'provider_stream': 'recover_model',
    'provider_empty': 'recover_model',
    'output_limit': 'keep_partial',
    'tool_validation': 'fix_input',
    'tool_unknown': 'inspect_only',
    'rights_budget': 'checkpoint_and_ask',
    'no_progress': 'change_approach',
    'unknown': 'checkpoint_and_ask',
}

#: Lớp giữ lại phần đã làm được (không ném đi kết quả một phần).
_KEEPS_PARTIAL = {'provider_stream', 'provider_empty', 'output_limit', 'tool_unknown', 'no_progress'}

#: Mã transport KHÔNG thử lại trong cùng cửa sổ (khớp `failures.py`): timeout vì cửa sổ
#: thời gian đã tiêu, cạn-retry vì router đã bỏ cuộc.
_TIMEOUT_CODES = frozenset({'UPSTREAM_TIMEOUT'})
_EXHAUSTED_CODES = frozenset({'UPSTREAM_RETRY_EXHAUSTED'})
_KEEPS_PARTIAL_CODES = _TIMEOUT_CODES | _EXHAUSTED_CODES

#: Số lần thử lại tối đa của họ transport (khớp `failures.DEFAULT_MAX_RETRIES`).
_TRANSPORT_RETRIES = 3

#: Lớp chỉ được thử lại khi chưa có hiệu ứng nào được ghi nhận.
_MAY_RETRY = {'transport'}

_EMPTY_RETRIES = 1  # khớp `TURN_EMPTY_RESPONSE_RETRY` của runtime: rỗng thử lại ĐÚNG một lần


def classify(code):
    """Mã lỗi → lớp. Mã lạ trả `'unknown'` (không đoán, không coi là transient)."""
    return CODES.get(str(code or '').strip(), 'unknown')


def enabled(env=None):
    """Lớp chính sách hồi phục: đặt tường minh > khóa tổng `BOXFOX_REFORM` > mặc định BẬT từ v2 (#6599), tắt tường minh bằng `off`."""
    if env is not None:
        return str(env or '').strip().lower() == 'on'
    return feature_switches.member_switch(SWITCH)


def may_retry(decision_value):
    """Quyết định này có cho phép chạy lại việc đã làm không (chỉ hai hành động retry)."""
    return str((decision_value or {}).get('action') or '') in RETRY_ACTIONS


def decision(code, *, replay_safe=False, has_receipt=False, attempts=0, retry_after=None):
    """Quyết định hồi phục cho một mã lỗi.

    `replay_safe` là nhãn replay của chính tool đã chạy (xem `tool_contracts.replay_class`);
    `has_receipt` nói đã có `tool_end`/biên nhận commit hay chưa. Hàm này KHÔNG tự chạy lại gì —
    nó chỉ nói được phép làm gì, và vì sao.
    """
    cls = classify(code)
    action = _ACTIONS[cls]
    replay = False
    reason = 'không rõ loại lỗi: dừng ở checkpoint và hỏi chủ nhà'
    if cls == 'transport':
        replay = False  # transport hỏng trước khi tool chạy; thử lại là thử lại REQUEST, không replay tool
        if str(code or '') in _TIMEOUT_CODES:
            action = 'checkpoint_and_ask'
            reason = ('hết cửa sổ thời gian: giữ phần đã có và để chủ nhà quyết định mở cửa sổ mới; '
                      'không thử lại trong cùng lượt (gọi lại bắt đầu từ 0)')
        elif str(code or '') in _EXHAUSTED_CODES:
            action = 'checkpoint_and_ask'
            reason = ('router đã thử lại và bỏ cuộc: giữ phần đã có, hỏi chủ nhà; '
                      'không xoay key và không replay tool đã chạy')
        elif attempts >= _TRANSPORT_RETRIES:
            action = 'checkpoint_and_ask'
            reason = (f'đã thử lại {attempts} lần mà vẫn lỗi kết nối: dừng và hỏi chủ nhà; '
                      'không xoay key và không replay tool đã chạy')
        else:
            reason = 'lỗi tạm thời: backoff rồi thử lại request; không xoay key và không replay tool đã chạy'
            if retry_after is not None:
                reason = f'{reason} (Retry-After={retry_after})'
    elif cls == 'provider_stream':
        replay = False  # chỉ dispatch tool call đầy đủ/đã validate của response mới
        reason = 'stream thiếu terminal: giữ phần đã có, gọi lại model có giới hạn; không replay tool đã thực thi'
    elif cls == 'provider_empty':
        if attempts < _EMPTY_RETRIES:
            action, reason = 'recover_model', 'phản hồi rỗng: thử lại đúng một lần'
        else:
            action = 'stop'
            reason = ('reasoning-only/từ chối/rỗng lặp lại: dừng và xin đổi route theo quyền; '
                      'không lách từ chối bằng vòng retry')
    elif cls == 'output_limit':
        replay = False
        reason = 'hết chỗ output: giữ artifact một phần, xin phân bổ thêm hoặc chuyển sang đọc theo trang'
    elif cls == 'tool_validation':
        replay = False
        reason = 'input sai schema: sửa trường/đổi cách gọi; không lặp nguyên payload đã bị từ chối'
    elif cls == 'tool_unknown':
        replay = False
        reason = ('mutation có kết quả không rõ: chỉ soi workspace/provider bằng tool an toàn, '
                  'ghi quyết định reconcile; TUYỆT ĐỐI không chạy lại mutation')
    elif cls == 'rights_budget':
        replay = False
        reason = ('quyền/ngân sách/epoch/phạm vi đã đổi: checkpoint phần còn lại và để chủ nhà quyết định; '
                  'không retry để vượt consent')
    elif cls == 'no_progress':
        replay = False
        reason = 'không có tiến triển thật: đổi cách/câu hỏi, lưu checkpoint; không lặp lại vô hạn'
    if cls == 'tool_unknown' and replay_safe:
        # Nhãn "safe" của tool không biến một mutation chưa rõ kết quả thành replay được.
        replay = False
    if cls == 'tool_validation' and has_receipt:
        reason = 'biên nhận đã có: dùng lại kết quả đã commit, không chạy lại'
    return {'code': str(code or ''), 'class': cls, 'action': action, 'replay': replay,
            'keepsPartial': cls in _KEEPS_PARTIAL or str(code or '') in _KEEPS_PARTIAL_CODES,
            'checkpoint': action != 'retry_backoff',
            'reason': reason}


def is_transient(code):
    """Chỉ lớp `transport` là tạm thời — trừ timeout/cạn-retry, đã tiêu hết cửa sổ."""
    code = str(code or '')
    if code in _TIMEOUT_CODES or code in _EXHAUSTED_CODES:
        return False
    return classify(code) == 'transport'


def keeps_partial(code):
    """Lớp này có giữ lại phần đã làm được không."""
    code = str(code or '')
    return classify(code) in _KEEPS_PARTIAL or code in _KEEPS_PARTIAL_CODES
