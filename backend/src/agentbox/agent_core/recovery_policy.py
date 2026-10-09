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
7. Mã host/CUA có lớp + hành động + **lời khuyên riêng** (`_HOST_ADVICE`); chỉ mã chưa khai mới rơi
   `unknown`. Mã CUA **không** bao giờ tự thử lại: `is_transient` vẫn chỉ đúng với `transport`, vì CUA
   là tay máy thật — lặp lại thao tác là quyết định của model, không phải của vòng retry.

Nối runtime (H8a): lớp này LUÔN sống từ v2 (#6599). Runtime
(a) ghi quyết định của module vào kết quả tool lỗi và event `error`, và (b) dùng
quyết định làm **cổng chỉ-chặn**: mã nào module nói `checkpoint_and_ask`/`stop` mà
vòng retry cũ định thử lại thì bị chặn (`RECOVERY_POLICY_DENIED`). Cổng không bao giờ
THÊM một lần thử lại — hôm nay nó khớp `failures.retry_advice` từng mã (H3.7), nên
nó không đổi hành vi; nó là lưới cho các mã mới.
"""

#: Hai hành động mà module nói "được phép chạy lại việc"; mọi hành động khác là dừng/giữ.
RETRY_ACTIONS = ('retry_backoff', 'recover_model')

#: Lớp hồi phục. Thứ tự này cũng là thứ tự ưu tiên khi một mã khớp nhiều luật.
CLASSES = ('transport', 'provider_stream', 'provider_empty', 'output_limit', 'tool_validation',
           'tool_unknown', 'rights_budget', 'no_progress', 'capability_gap', 'unknown')

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
    # F05 (v1 cải tổ web search): thiếu cấu hình/hạ tầng tìm kiếm KHÔNG phải lỗi truy vấn — lớp
    # riêng để thông báo nói đúng việc cần làm thay vì rơi vào `unknown` (fail closed) như trước.
    'WEB_SEARCH_UNAVAILABLE': 'capability_gap',
    'WEB_SEARCH_EMPTY': 'no_progress',
}

#: Mã host/CUA → (lớp, hành động, lời khuyên). Đây là bảng DUY NHẤT khai báo mã của đường host:
#: `reflection_hint` đọc lại đúng lời khuyên này (`advice()`) chứ không chép lại câu chữ, nên sửa
#: một dòng ở đây là sửa cả lời nhắc gửi cho model. Mã mới phải vào bảng này trước, rồi mới tới
#: `tool_contracts` (câu gửi model) và `frontend/src/i18n/vi.ts` (câu cho chủ nhà).
#: Không thêm mã CUA vào `_MAY_RETRY`/`_ACTIONS`: CUA là tay máy thật, chỉ model được quyết định
#: thử lại sau khi đã nhìn lại màn hình.
_HOST_ADVICE = {
    # ── Quyền điều khiển thuộc về người thật / màn hình không dùng được ────────────────────────
    'HUMAN_HAS_CONTROL': (
        'rights_budget', 'checkpoint_and_ask',
        'người thật đang giữ quyền điều khiển: KHÔNG gửi thao tác nào; chờ quyền trả lại rồi chụp lại màn hình',
    ),
    'HUMAN_TOOK_OVER': (
        'rights_budget', 'checkpoint_and_ask',
        'người thật vừa giành lại quyền điều khiển: dừng thao tác đang làm, chờ quyền trả lại rồi chụp lại',
    ),
    'DESKTOP_LOCKED': (
        'rights_budget', 'checkpoint_and_ask',
        'màn hình đang khoá (hoặc hộp thoại bảo mật): không gửi input; mở khoá rồi chụp lại và tiếp tục',
    ),
    # ── Quyền/duyệt của phiên từ chối việc này ──────────────────────────────────────────────────
    'PERMISSION_DENIED': (
        'rights_budget', 'checkpoint_and_ask',
        'quyền/mức hiện tại từ chối việc này: xin chủ nhà mở quyền hoặc đổi cách; không lặp y nguyên',
    ),
    'APPROVAL_REQUIRED': (
        'rights_budget', 'checkpoint_and_ask',
        'chủ nhà chưa cho phép thao tác này: chờ duyệt xong (hoặc đổi cách làm); không lặp y nguyên',
    ),
    'APPROVAL_DENIED': (
        'rights_budget', 'checkpoint_and_ask',
        'chủ nhà đã từ chối thao tác này: không gửi lại y nguyên; đổi cách hoặc hỏi lý do',
    ),
    'APPROVAL_DENIAL_BREAKER': (
        'rights_budget', 'checkpoint_and_ask',
        'một lần từ chối trước đó đã chặn vòng lặp: dừng và xin hướng khác; không lách bằng cách gọi lại',
    ),
    'PATH_OUTSIDE_WORKSPACE': (
        'rights_budget', 'checkpoint_and_ask',
        'đường dẫn ra ngoài workspace: chuyển vào trong workspace hoặc xin chủ nhà đổi phạm vi; đừng thử lại y nguyên',
    ),
    # Khác `PERMISSION_DENIED` (quyền của phiên/mức hiện tại): đây là quyền của HĐH trên tệp — ví dụ
    # tệp của root hoặc thư mục chỉ-đọc. Đo 2026-10-08: `host_executor.py:505` bắt `PermissionError`
    # của chính công cụ tệp và trả mã này, trước đây rơi `unknown` ⇒ agent nhận câu "không rõ loại lỗi".
    'FILE_PERMISSION_DENIED': (
        'rights_budget', 'checkpoint_and_ask',
        'hệ điều hành từ chối quyền trên tệp/đường dẫn này: xin chủ nhà mở quyền (hoặc chuyển sang đường dẫn khác); đừng lặp y nguyên',
    ),
    'OS_PERMISSION_REQUIRED': (
        'rights_budget', 'checkpoint_and_ask',
        'hệ điều hành đang chặn thao tác này: cần chủ nhà cấp quyền cho BoxFox; đổi cách, đừng lặp',
    ),
    'UIPI_BLOCKED': (
        'rights_budget', 'checkpoint_and_ask',
        'cửa sổ đích chạy quyền cao hơn BoxFox nên input bị chặn: đổi đích hoặc xin chủ nhà hạ quyền ứng dụng',
    ),
    'SESSION_NOT_INTERACTIVE': (
        'rights_budget', 'checkpoint_and_ask',
        'phiên desktop không tương tác: CUA không chạy được ở đây; dừng và báo chủ nhà',
    ),
    # ── Đích/toạ độ đã cũ: chụp lại rồi chọn lại ────────────────────────────────────────────────
    'ELEMENT_STALE': (
        'tool_unknown', 'inspect_only',
        'phần tử đã cũ so với lần soi: chụp lại rồi chọn lại đích; không dùng lại toạ độ cũ',
    ),
    'SOURCE_CHANGED': (
        'tool_unknown', 'inspect_only',
        'cửa sổ đổi vị trí/kích thước/nội dung sau khi soi: chụp lại rồi chọn lại; mã cửa sổ cũ không dùng lại được',
    ),
    'SOURCE_IDENTITY_UNAVAILABLE': (
        'tool_unknown', 'inspect_only',
        'không xác định được cửa sổ nguồn: chụp lại rồi chọn lại đích; đừng đoán',
    ),
    'WINDOW_IDENTITY_UNAVAILABLE': (
        'tool_unknown', 'inspect_only',
        'không đọc được danh tính cửa sổ (tiêu đề/tiến trình): chụp lại rồi chọn lại đích',
    ),
    'window_identity_unavailable': (
        'tool_unknown', 'inspect_only',
        'không đọc được danh tính cửa sổ (tiêu đề/tiến trình): chụp lại rồi chọn lại đích',
    ),
    'WINDOW_MINIMIZED': (
        'tool_unknown', 'inspect_only',
        'cửa sổ đích đang thu nhỏ: mở lại (hoặc chọn cửa sổ khác) rồi chụp lại; đừng gửi toạ độ cũ',
    ),
    'WINDOW_CLOAKED': (
        'tool_unknown', 'inspect_only',
        'cửa sổ đích bị ẩn khỏi màn hình: hiện lại hoặc chọn cửa sổ khác rồi chụp lại',
    ),
    'TARGET_UNKNOWN': (
        'tool_unknown', 'inspect_only',
        'không tìm thấy cửa sổ/điểm đích (có thể đã đóng): chụp lại và chọn lại đích; mã cửa sổ cũ vô hiệu',
    ),
    'no_window_at_point': (
        'tool_unknown', 'inspect_only',
        'không có cửa sổ nào tại điểm này: chụp lại rồi chọn lại điểm',
    ),
    'ambiguous_target': (
        'tool_unknown', 'inspect_only',
        'nhiều cửa sổ/tab cùng khớp: chọn lại bằng windowId cụ thể; đừng đoán',
    ),
    'uia_no_element': (
        'tool_unknown', 'inspect_only',
        'không có phần tử UIA tại điểm này: chụp lại rồi chọn lại điểm',
    ),
    'no_node_at_point': (
        'tool_unknown', 'inspect_only',
        'không có phần tử DOM tại điểm này: chụp lại rồi chọn lại điểm',
    ),
    'outside_viewport': (
        'tool_unknown', 'inspect_only',
        'điểm nằm ngoài vùng nội dung trang: chọn lại điểm trong trang (không phải thanh tiêu đề/tab/toolbar)',
    ),
    'frame_extents_unknown': (
        'tool_unknown', 'inspect_only',
        'không đọc được viền trang trí cửa sổ: chụp lại rồi chọn lại; đừng đoán vùng trang trí',
    ),
    'viewport_origin_unknown': (
        'tool_unknown', 'inspect_only',
        'không suy được gốc vùng nội dung web: đổi cách soi (chụp lại hoặc đổi cửa sổ)',
    ),
    'no_cdp_target': (
        'tool_unknown', 'inspect_only',
        'không tìm được kết nối trình duyệt khớp cửa sổ: chụp lại/chọn lại tab; kiểm tra trình duyệt còn mở',
    ),
    'devtools_docked': (
        'tool_unknown', 'inspect_only',
        'DevTools đang ghim trong cửa sổ nên không suy được vùng trang: đóng hoặc tách DevTools rồi soi lại',
    ),
    # ── Một nhịp máy hỏng/chậm: thử lại MỘT lần theo cách khác, không lặp y nguyên ──────────────
    'CONTROL_BUSY': (
        'tool_unknown', 'inspect_only',
        'đang có lượt điều khiển khác giữ mutex: chờ một nhịp rồi thử lại MỘT lần; không lặp dồn dập',
    ),
    'cdp_timeout': (
        'tool_unknown', 'inspect_only',
        'truy vấn trình duyệt quá thời gian chờ: thử lại một lần với cách khác; không lặp y nguyên',
    ),
    'cdp_unreachable': (
        'tool_unknown', 'inspect_only',
        'không kết nối được trình duyệt (có thể đang khởi động lại): chờ rồi thử lại một lần; còn hỏng thì đổi cách',
    ),
    'extract_failed': (
        'tool_unknown', 'inspect_only',
        'trích xuất dữ liệu phần tử thất bại: thử lại một lần rồi đổi cách; không lặp y nguyên',
    ),
    'uia_timeout': (
        'tool_unknown', 'inspect_only',
        'UI Automation không trả lời kịp: thử lại một lần; không lặp y nguyên',
    ),
    'uia_provider_hang': (
        'tool_unknown', 'inspect_only',
        'nhà cung cấp UI Automation của ứng dụng bị treo: đổi cách (đổi đích hoặc dùng DOM); đừng chờ vô hạn',
    ),
    'UIA_TIMEOUT': (
        'tool_unknown', 'inspect_only',
        'truy vấn UI Automation quá thời gian chờ: thử lại một lần với cách khác; không lặp y nguyên',
    ),
    'UIA_PROVIDER_HANG': (
        'tool_unknown', 'inspect_only',
        'nhà cung cấp UI Automation bị treo: đổi cách, đừng lặp y nguyên',
    ),
    'INPUT_SHORT_SEND': (
        'tool_unknown', 'inspect_only',
        'chỉ gửi được một phần input: chụp lại xem thực trạng rồi gửi nốt phần thiếu; đừng gửi lại cả chuỗi',
    ),
    'POST_MESSAGE_UNSUPPORTED': (
        'tool_unknown', 'inspect_only',
        'cửa sổ không nhận POST_MESSAGE: đổi cách gửi (SendInput) hoặc đổi đích; không lặp y nguyên',
    ),
    # ── Sai tham số/phạm vi: sửa input rồi gọi lại MỘT lần ──────────────────────────────────────
    'TARGET_REQUIRED': (
        'tool_validation', 'fix_input',
        'phiên chưa chọn đích CUA: chọn một cửa sổ hoặc cả máy rồi gọi lại MỘT lần',
    ),
    'TARGET_AMBIGUOUS': (
        'tool_validation', 'fix_input',
        'nhiều cửa sổ cùng khớp tên: chỉ định windowId cụ thể rồi gọi lại một lần',
    ),
    'CUA_MACHINE_SCOPE_REQUIRED': (
        'tool_validation', 'fix_input',
        'đích cả máy cần phạm vi quyền `machine`: xin chủ nhà đổi phạm vi hoặc chọn một cửa sổ',
    ),
    'UNSUPPORTED_ACTION': (
        'tool_validation', 'fix_input',
        'hành động chưa có trên đường host: dùng hành động trong enum (click/type/key/scroll/drag/hold/stroke) rồi gọi lại một lần',
    ),
    'UNSUPPORTED_IN_HOST_MODE': (
        'tool_validation', 'fix_input',
        'công cụ này chưa có trên host: đổi sang công cụ khác; đừng gọi lại y nguyên',
    ),
    'HOST_REQUEST_UNSUPPORTED': (
        'tool_validation', 'fix_input',
        'đường request chưa có bản host: dùng đường khác; đừng lặp y nguyên',
    ),
    'TOOL_ARGUMENT_INVALID': (
        'tool_validation', 'fix_input',
        'tham số sai kiểu/giá trị: sửa đúng tham số rồi gọi lại một lần; không lặp nguyên payload',
    ),
    # Hai chỗ phát mã này: `host_executor.py:503` (`FileNotFoundError` của mọi công cụ tệp) và `:1135`
    # (đường dẫn không phải tệp). Đây là việc agent sửa được — đọc lại đường dẫn, không phải lỗi quyền.
    'FILE_NOT_FOUND': (
        'tool_validation', 'fix_input',
        'không tìm thấy tệp/đường dẫn: đọc `error`, xác định đúng đường dẫn (liệt kê thư mục nếu cần) rồi gọi lại MỘT lần',
    ),
    'COMMAND_EXIT_NONZERO': (
        'tool_validation', 'fix_input',
        'lệnh đã chạy và thoát khác 0: đọc `content`/`exit_code` để sửa lệnh; đây KHÔNG phải lỗi schema',
    ),
    # ── Máy này thiếu hẳn năng lực đó ───────────────────────────────────────────────────────────
    'CUA_UNAVAILABLE': (
        'capability_gap', 'checkpoint_and_ask',
        'máy này không có CUA (thiếu nền tảng/cấu hình): đọc `error` để biết gói cần cài; dừng và báo chủ nhà',
    ),
    'UIA_UNAVAILABLE': (
        'capability_gap', 'checkpoint_and_ask',
        'không truy cập được UI Automation (thiếu thành phần UIA): dùng nhánh DOM nếu được hoặc báo chủ nhà; đừng lặp',
    ),
    'uia_unavailable': (
        'capability_gap', 'checkpoint_and_ask',
        'không truy cập được UI Automation trên máy/ứng dụng này: dùng nhánh DOM nếu được hoặc báo chủ nhà; đừng lặp',
    ),
    'LAUNCH_FAILED': (
        'capability_gap', 'checkpoint_and_ask',
        'không mở được ứng dụng: kiểm tra tên/đường dẫn app hoặc nhờ chủ nhà mở sẵn; không lặp y nguyên',
    ),
    'CAPTURE_FAILED': (
        'capability_gap', 'checkpoint_and_ask',
        'không chụp được màn hình/cửa sổ: kiểm tra nền tảng và cửa sổ còn sống rồi thử lại một lần; còn hỏng thì đổi cách',
    ),
    'PASSWORD_FIELD_REFUSED': (
        'capability_gap', 'checkpoint_and_ask',
        'ô mật khẩu — luật cấm đọc/điều khiển: dừng thao tác này, để chủ nhà tự nhập',
    ),
    # ── Ngõ cụt thật: đổi cách, đừng lặp ────────────────────────────────────────────────────────
    'COMMAND_TIMEOUT': (
        'no_progress', 'change_approach',
        'lệnh vượt trần thời gian và đã bị dừng: chia nhỏ lệnh hoặc đổi cách; đừng chạy lại y nguyên',
    ),
    'HOST_TOOL_FAILED': (
        'no_progress', 'change_approach',
        'lỗi bất ngờ của công cụ host: đọc `error`, đổi cách; đừng lặp y nguyên',
    ),
    # ── Mã đường host phát ra mà ba nguồn ở trên không liệt kê (đo trực tiếp trong mã nguồn) ────
    'TARGET_KIND_INVALID': (
        'tool_validation', 'fix_input',
        'đích sai kiểu: dùng đúng kind (một cửa sổ / cả máy / vùng) rồi gọi lại một lần',
    ),
    'INSPECT_FAILED': (
        'tool_unknown', 'inspect_only',
        'soi phần tử thất bại bất ngờ: đọc `error`, chụp lại rồi chọn lại; không lặp y nguyên',
    ),
    # Chỉ hai route dành cho panel ném ra (`machine_router.py:875` khi người dùng bấm ra ngoài vùng
    # chụp, `api/server.py:1150` khi toạ độ không phải số nguyên) — agent không nhận mã này. Vẫn khai
    # để bảng tài liệu và câu panel nói cùng một việc, và để `reflection_hint` không bao giờ khuyên
    # "sửa schema" cho nó nếu nó lọt vào một kết quả công cụ.
    'INSPECT_POINT_INVALID': (
        'tool_validation', 'fix_input',
        'điểm soi ngoài vùng chụp (hoặc toạ độ không phải số nguyên): chọn lại điểm trong vùng chụp rồi gọi lại MỘT lần',
    ),
}

#: Nạp mã host/CUA vào bảng tra lớp chung (giữ một nguồn duy nhất).
CODES.update({code: klass for code, (klass, _action, _reason) in _HOST_ADVICE.items()})

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
    'capability_gap': 'checkpoint_and_ask',
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


def advice(code):
    """Mã host/CUA → `(lớp, hành động, lời khuyên riêng)`, hoặc `None` nếu không phải mã host/CUA.

    Đây là nguồn duy nhất của câu chữ: `tool_contracts.reflection_hint` gọi hàm này để dựng câu gửi
    cho model thay vì chép lại lời khuyên.
    """
    return _HOST_ADVICE.get(str(code or '').strip())


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
    host = advice(code)
    if host is not None:
        # Mã host/CUA: lấy nguyên bộ ba (lớp, hành động, lý do) từ `_HOST_ADVICE` — lời khuyên phải
        # khớp từng mã (chụp lại, chờ quyền, sửa tham số…), không dùng câu chung của lớp.
        cls, action, reason = host
    elif cls == 'transport':
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
    elif cls == 'capability_gap':
        replay = False
        reason = ('backend tìm kiếm thiếu cấu hình hoặc đang hỏng: đừng lặp truy vấn; dùng nguồn khác, '
                  'hoặc báo khoảng trống cho chủ nhà')
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
