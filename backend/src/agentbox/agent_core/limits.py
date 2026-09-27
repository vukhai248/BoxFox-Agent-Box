"""Trần số của runtime — một nguồn cho cả engine lẫn giao diện.

`INSTRUCTIONS_MAX_CHARS` trước đợt 18 nằm dưới dạng literal `[:12000]` trong
`runtime.py`, nên mọi chỗ muốn nói "engine giữ bao nhiêu ký tự" (bộ đếm ở tab
Instructions, câu giải thích phần bị bỏ) đều phải chép tay con số lần thứ hai rồi
lệch dần. Từ đây chỉ còn một con số: `runtime.py` cắt bằng nó, `api/owner_settings.py`
và `GET /api/agent/runtime-info` trả lời bằng nó.
"""

import os

INSTRUCTIONS_MAX_CHARS = 12000

# Trần của một phiên. `runtime.create()` kẹp giá trị người dùng gửi lên bằng đúng bốn
# con số này (mặc định khi thiếu trường, trần khi gửi quá), vai trò con bị chặn chặt
# hơn ở `runtime.delegate()`. Để ở đây vì `GET /api/agent/runtime-info` phải báo lại
# đúng những con số engine đang áp — giao diện không chép tay lần thứ hai.
# Vòng 22 (D-1, D-15): chủ nhà chốt phiên chính 16 → **40** bước và phiên con **40 bước / 300 s**
# (trước là 10 / 120). Số đo vòng 21: việc vừa phải xong ở 8 bước, việc dài 27 bước; con chạm
# 10 bước / 120 s thì trả `answerChars = 0` (BUG-42), nên ngân sách con là chỗ chữa chính.
# `300 s` của con là **trần**, không phải bảo đảm — `runtime.delegate()` vẫn `min()` theo cha.
MAX_STEPS_DEFAULT = 40
MAX_STEPS_MAX = 60
# Vòng 25 (D-35) — đo sống: một lượt lập kế hoạch CƠ BẢN chết ở 210 s trước cả `write_plan` khi
# mặc định là 180 s, và một lượt khác ở 622 s vẫn `partial` (chưa xong). Lượt lập kế hoạch đầu
# tiên không có dấu vết tất định nào để nhận ra TRƯỚC khi nó chạy, nên nâng toàn cục; phần nới
# theo sự kiện (`PLAN_TURN_EXTENSION_SECONDS`) chỉ để lượt kịp đi hết vòng phản biện.
DEADLINE_DEFAULT_SECONDS = 600
DEADLINE_MAX_SECONDS = 1200
CHILD_MAX_STEPS = 40
CHILD_DEADLINE_SECONDS = 900

# Trần BYTE của một request mà router chấp nhận, và phần byte của request không nằm trong
# `messages` (prompt vai + schema công cụ). Bộ nén phải biết cả hai: trên cửa sổ 1M, ngưỡng
# 70 % (≈697k token, ≈2 MiB JSON) không bao giờ chạm tới trước khi router trả
# `UPSTREAM_HTTP_413`, nên trần thật của một phiên là byte chứ không phải token. Đo sống
# 2026-09-20: body 1 060 902 B trong khi `messages` là 1 043 364 B — hiệu 17 538 B ≈ 5 846 token
# (ước lượng 3 byte/token), làm tròn lên 6 000 cho phần prompt + schema đầy đủ.
ROUTER_BODY_BUDGET = 900 * 1024
ROUTER_BODY_OVERHEAD_TOKENS = 6000

# Cửa sổ chống-thrash của bộ nén: hỏng một lượt tóm tắt (hoặc nén xong mà vẫn sát ngưỡng) thì
# không thử lại cho tới khi hết cửa sổ này. HERMES `_ANTI_THRASH_RECOVERY_SECONDS = 300.0`
# (agent/context_compressor.py:2501) — hết cửa sổ thì cho phép đúng một lần thử lại.
COMPRESSION_THRASH_SECONDS = 300.0

# Dải mục tiêu của ngưỡng nén (đợt 20, Phần D). Ngưỡng theo tỉ lệ 0,7 một mình cho ra hai đầu
# cực: cửa sổ khai tay 32 768 nén ở 20 070 token (phiên "cụt ngủn"), còn cửa sổ 1M chỉ bị trần
# byte 301 200 chặn nên phiên dài vô hạn — đo trên máy Vorflux 2026-09-21: mỗi lần gộp ở đó là
# 65–185k token. Trần dưới đây giữ box không dài hơn mức đó.
#
# `COMPRESSION_MIN_TOKENS` là SÀN bảo vệ: chỉ áp khi cửa sổ còn đủ chỗ (`budget >= MIN_ROOM`),
# nên nó KHÔNG đổi hành vi của mọi cửa sổ ≤ 32 768 — nói thật là với các cửa sổ đang dùng nó
# không chạm tới; cái chữa "quá ngắn" thật là cảnh báo cửa sổ khai nhỏ ở `runtime.heal_context_windows`.
COMPRESSION_MIN_TOKENS = 32_000
COMPRESSION_MAX_TOKENS = 200_000
COMPRESSION_MIN_ROOM = 40_000

# Sàn theo TOKEN cho phần đuôi giữ nguyên văn. Sàn hiện có (`MAX_TAIL_MESSAGE_FLOOR = 8`) đếm
# bằng SỐ message, nên trên cửa sổ 32 768 (`tail_budget` = 5 734 token) tám message có thể không
# lọt vào ngân sách. Trần của sàn này là 1/4 ngân sách một lượt, để sàn không ăn hết chỗ của bản
# tóm tắt.
MAX_TAIL_TOKEN_FLOOR = 8_000

# --- Phần C: hai lỗi đo được từ lượt chạy sống 2026-09-21 -------------------------------
# Lượt "clone repo, đọc dự án, viết plan, sửa code nhẹ" đã xong việc trên đĩa (plan `v5-…`
# 9 155 B, 4 tệp sửa, `300 passed`) mà lượt chạy vẫn kết thúc `failed`. Hai con số dưới đây
# thuộc về hai nguyên nhân của lượt đó, không phải chính sách mới.

# C1 — "kẹp âm thầm" hạn chót. Người dùng đặt `deadlineSeconds: 900`, `runtime.create()` kẹp
# về `DEADLINE_MAX_SECONDS` (600) mà không có event, không có dòng log, không có trường nào
# trong payload phiên: con số 900 trên giao diện là con số engine CHƯA BAO GIỜ dùng. Mã notice
# dưới đây là tên duy nhất của sự việc đó trong transcript.
DEADLINE_CLAMP_NOTICE_CODE = 'DEADLINE_CLAMPED'
DEADLINE_MIN_SECONDS = 5

# C2 — trần output của nhà cung cấp. Đo sống: con `6bd868ad…` trả `finishReason: length`,
# `outputTokens: 4096`, `toolCalls: 0` → `TURN_EMPTY_RESPONSE`, không thử lại, cha thấy con
# `failed` dù đó là lỗi TẠM THỜI của nhà cung cấp chứ không phải lỗi của việc uỷ thác. Lần thử
# lại hạ trần output và bỏ công cụ để model buộc phải trả lời bằng chữ.
TRUNCATED_OUTPUT_MAX_TOKENS = 2048
TRUNCATED_OUTPUT_NOTICE_CODE = 'PROVIDER_OUTPUT_TRUNCATED'

# --- Vòng 22: ngân sách không còn "mất trắng", và trần độ dài câu trả lời -----------------
# Ba số dưới đây là hợp đồng của đường chẩn đoán chỗ tắc (yêu cầu mới của chủ nhà, D-15):
# chạm trần bước hoặc hạn chót thì lượt (cha **hoặc** con) phải tự đọc lại trạng thái, sửa
# một lần nếu đường cũ sai, rồi trả `partial` kèm bốn phần: đã làm / tắc ở đâu / còn lại /
# thử gì tiếp. `WRAP_UP_STEPS_RESERVED` là số bước giữ chỗ cho việc đó (trần của phần
# "sửa lại một lần"), nên lượt hữu ích ngắn đi đúng ba bước.
STEP_BUDGET_NOTICE_CODE = 'STEP_BUDGET_EXHAUSTED'
DEADLINE_NOTICE_CODE = 'DEADLINE_EXCEEDED'
STEPS_CLAMP_NOTICE_CODE = 'STEPS_CLAMPED'
WRAP_UP_STEPS_RESERVED = 3
WRAP_UP_MAX_TOKENS = 1024
WRAP_UP_TIMEOUT_SECONDS = 30
WRAP_UP_READ_TOOL_CALLS = 2
DIAGNOSIS_MIN_CHARS = 80

# Trần độ dài câu trả lời cuối (D-4): 60 000 ký tự thì cảnh báo, 150 000 thì từ chối và trả
# `partial` kèm tệp toàn văn. Ngưỡng của **kế hoạch** (40 000 / 150 000) là bộ số khác, không đụng.
# --- Vòng 22 đợt 2 (T5): fan-out theo CHA --------------------------------------------------
# Trần cũ là MỘT `Semaphore(3)` dùng chung cả tiến trình: hai phiên cha tranh nhau ba slot và
# một cha không thể có bốn con cùng lúc. Trần giờ đặt theo từng cha (mặc định 3, trần 6) và
# giữ một trần TOÀN CỤC 8 — đủ cho hai cha × ba con mà không tăng tải mặc định.
FANOUT_PER_PARENT_DEFAULT = 3
FANOUT_PER_PARENT_MAX = 6
FANOUT_GLOBAL_CEILING = 8
# Hết chỗ chờ quá ngần này thì trả lỗi tool cho model — một lượt không bao giờ treo vì hết slot.
FANOUT_QUEUE_WAIT_SECONDS = 30
# Chặn vòng lặp sinh con trong MỘT lượt (một lượt 40 bước có thể gọi `delegate_task` 40 lần).
CHILDREN_PER_TURN_MAX = 18
FANOUT_BUSY_CODE = 'FANOUT_BUSY'
CHILDREN_PER_TURN_CODE = 'CHILDREN_PER_TURN_EXHAUSTED'

# --- Vòng 22 đợt 2 (T9): chờ bạn GIAO kết quả -------------------------------------------
# Chủ nhà chốt (Q2): `await_children` chờ **tới lúc bạn giao xong kết quả**, không chờ một
# khoảng thời gian cố định — hàm tỉnh dậy bằng SỰ KIỆN (biên nhận giao hàng được ghi ⇒ đánh
# thức hàng chờ trong cùng một nhịp), nên không polling và không trễ nhịp. Ba con số 300 s
# dưới đây là LƯỚI AN TOÀN để một lượt không bao giờ treo vì đã chờ: một lần chờ, tổng thời
# gian hoãn hạn chót của cả lượt, và trần của `timeoutSeconds` mà người gọi tự đặt.
PEER_WAIT_SAFETY_SECONDS = 300
PEER_WAIT_MAX_SECONDS = 300
PEER_WAIT_TOTAL_MAX_SECONDS = 300
# Cửa sổ DÒ một địa chỉ vai chưa tồn tại (anh em có thể được sinh ngay sau bạn), dò mỗi 1 s.
PEER_TARGET_GRACE_SECONDS = 20
PEER_TARGET_POLL_SECONDS = 1.0
PEER_WAIT_CLAMPED_CODE = 'PEER_WAIT_CLAMPED'
# Phiên khai một khoá mesh mà vòng 22 KHÔNG đổi hành vi vì nó (`parallelReadTools` — Q3/T14), hoặc
# khai tắt mesh cho riêng mình: im lặng nhận một cờ rồi không làm gì là đúng lớp lỗi mà cả vòng này
# đang sửa, nên cờ nào cũng đi kèm một notice nói thẳng nó có hiệu lực hay không.
PEER_MESH_NOTICE_CODE = 'PEER_MESH_NOTICE'
# Tổng ngân sách chữ cho phần `summary` của MỘT kết quả `await_children`: mười hai mục tiêu ×
# 8 000 ký tự là 96 000 ký tự, vượt xa trần 20 000 của một tool result. Mục sau khi hết ngân
# sách vẫn có mặt trong `done` (kèm `truncated: True`), chỉ phần chữ là không còn.
PEER_WAIT_RESULT_CHARS = 16_000
# T11 — trần địa chỉ giao hàng trong MỘT lời gọi `delegate_task`. Bốn là đủ cho các
# đường ống thật (main + ba chuyên gia) và vẫn giữ kết quả tool nhỏ; hơn nữa là lỗi
# tool rõ ràng, không cắt im lặng.
PEER_DELIVER_MAX = 4

# --- Công tắc vận hành của mesh (T5/T10/T13) -----------------------------------------------
# Đọc env mỗi lần hỏi, không đọc một lần lúc nạp: một tiến trình harness sống lâu, nên đổi
# công tắc phải có tác dụng ngay mà không cần khởi động lại. `off` (hoặc rỗng) ⇒ hành vi y
# hệt bản trước đợt 2.
# T10 — Watchdog: ba lưới an toàn cuối của sổ con, và ba lý do chúng ghi vào sổ.
# `CHILD_WALL_MAX_SECONDS = 900` rộng hơn hẳn trần thời gian của MỘT con (`CHILD_DEADLINE_SECONDS`
# = 300): watchdog chỉ được huỷ con đã vượt xa mọi ngưỡng hợp lệ, nếu không nó thành kẻ giết việc
# đang chạy tốt. Nhịp quét thưa (10 s) vì mỗi nhịp là một giao dịch trên SQLite dùng chung.
WATCHDOG_TICK_SECONDS = 10
CHILD_WALL_MAX_SECONDS = 1200
# Hàng `started` còn sót lại từ lần chạy TRƯỚC (tiến trình bị giết): thao tác tool không được chạy
# lại, nên không hồi sinh — đóng nó bằng `RESTART`, cùng luật với `UPDATE sessions SET
# status='interrupted'` lúc mở DB.
WATCHDOG_RESTART_REASON = 'RESTART'
WATCHDOG_TIMEOUT_REASON = 'WATCHDOG_TIMEOUT'
WATCHDOG_ORPHAN_REASON = 'ORPHAN'
# Chờ bạn quá `PEER_WAIT_SAFETY_SECONDS` cộng ngần này thì watchdog đánh thức cưỡng bức. Người chờ
# chạy tiếp bình thường với `peer_wait_end status='timeout'`, lượt KHÔNG bị đánh `failed`.
PEER_WAIT_FORCE_GRACE_SECONDS = 30
PEER_MESH_ENV = 'BOXFOX_PEER_MESH'
PEER_FANOUT_ENV = 'BOXFOX_PEER_FANOUT'
PARALLEL_READ_ENV = 'BOXFOX_PARALLEL_READ_TOOLS'
PEER_WAIT_MAX_ENV = 'BOXFOX_PEER_WAIT_MAX'
SWITCH_ON = {'1', 'on', 'true', 'yes'}


def switch_enabled(name, default=False):
    """`True`/`False` cho một công tắc môi trường, có giá trị mặc định khi env trống."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in SWITCH_ON


def peer_mesh_enabled():
    """Công tắc giết của cả mesh: `BOXFOX_PEER_MESH=off` ⇒ không tool peer, uỷ thác chặn như cũ."""
    return switch_enabled(PEER_MESH_ENV, True)


def peer_fanout_limit():
    """Trần con mỗi cha do `BOXFOX_PEER_FANOUT` đặt, hoặc `None` khi biến trống.

    Nhận hai cách viết, vì cả hai đều đã có trong tài liệu: một SỐ (kẹp `[1, FANOUT_PER_PARENT_MAX]`)
    và các chữ nới trần (`on`/`true`/`yes`). Một con số được ưu tiên đọc là con số, nên `=1` là MỘT
    con mỗi cha — cách viết mà kế hoạch T13 chốt cho công tắc giết — chứ không phải "bật".
    """
    raw = (os.environ.get(PEER_FANOUT_ENV) or '').strip().lower()
    if not raw:
        return None
    if raw.isdigit():
        return max(1, min(FANOUT_PER_PARENT_MAX, int(raw)))
    return FANOUT_PER_PARENT_MAX if raw in SWITCH_ON else None


def peer_wait_max():
    """Trần `timeoutSeconds` của MỘT lần chờ bạn (T13): `BOXFOX_PEER_WAIT_MAX=<giây>` hạ nó xuống.

    Chỉ HẠ được, không nâng: trần 300 s là lưới an toàn của lượt, còn biến môi trường là để vận
    hành chạy chặt hơn. Giá trị không phải số nguyên dương thì bị bỏ qua (giữ trần).
    """
    raw = (os.environ.get(PEER_WAIT_MAX_ENV) or '').strip()
    if not raw.isdigit():
        return PEER_WAIT_MAX_SECONDS
    return max(1, min(PEER_WAIT_MAX_SECONDS, int(raw)))


def parallel_read_tools_enabled():
    """`BOXFOX_PARALLEL_READ_TOOLS` (mặc định `off`). Vòng 22 CHỈ KHAI BÁO cờ này.

    Q3 chốt: chạy song song tool ĐỌC trong một bước không nằm trong vòng này (nó là T14, vòng sau).
    Hàm này tồn tại để `runtime_info` nói được trạng thái cờ, và để T14 chỉ việc dùng — mã vòng 22
    KHÔNG đổi hành vi tool trong bước vì nó.
    """
    return switch_enabled(PARALLEL_READ_ENV, False)

# --------------------------------------------------------------------------------------------
# Vòng 22 đợt 3 — cổng bằng chứng sống: công tắc, trần của vòng vá, trần của phép dò box
# --------------------------------------------------------------------------------------------
# Ba chế độ là ba mức CAN THIỆP, không phải ba mức "chặt": `off` không làm gì; `warn` ghim nhãn
# và đếm nhưng KHÔNG gọi model, KHÔNG sửa một chữ nào của câu trả lời; `enforce` cho phép ĐÚNG
# MỘT vòng vá. Giá trị lạ ⇒ rơi về mặc định KÈM notice (xem `evidence_mode` của runtime).
EVIDENCE_GATE_ENV = 'BOXFOX_EVIDENCE_GATE'
EVIDENCE_MODES = ('off', 'warn', 'enforce')
EVIDENCE_DEFAULT_MODE = 'warn'
# Trần của vòng vá. Ba con số này là điều kiện sống còn: vòng vá nằm TRONG `asyncio.timeout`
# của lượt, nên nếu nó tiêu hết thời gian còn lại thì lượt chết vì `DEADLINE` mà không có câu
# trả lời nào — ngược hẳn mục tiêu của cả đợt.
EVIDENCE_REPAIR_MAX_TOKENS = 2048
EVIDENCE_REPAIR_TIMEOUT_SECONDS = 60
EVIDENCE_REPAIR_MIN_REMAINING_SECONDS = 20
# Phép dò box (một lệnh `find`, xem `runtime.probe_workspace`): trần thời gian, trần số tệp, và
# trần số mảnh bằng chứng mang vào câu trả lời.
EVIDENCE_PROBE_TIMEOUT_SECONDS = 20
EVIDENCE_PROBE_MAX_FILES = 200
# P1.5 — dọn thư mục bằng chứng: không phải mỗi lượt (mỗi lượt là một `find`/`scandir` thừa trên
# đường trả lời), nhưng cũng không phải "để cuối phiên" (phiên dài là chỗ thư mục phình).
EVIDENCE_PRUNE_EVERY = 20
EVIDENCE_PRUNE_TIMEOUT_SECONDS = 30
EVIDENCE_PRUNE_CODE = 'EVIDENCE_PRUNE_DEGRADED'
EVIDENCE_MAX_ARTIFACTS = 20
EVIDENCE_EXCERPT_CHARS = 500
# Mã notice của cổng. `X:` chỉ dành cho cổng TỰ hỏng; thiếu bằng chứng là `EVIDENCE_INSUFFICIENT`
# và KHÔNG bao giờ làm lượt hỏng.
EVIDENCE_INSUFFICIENT_CODE = 'EVIDENCE_INSUFFICIENT'
EVIDENCE_GATE_FAILED_CODE = 'EVIDENCE_GATE_FAILED'
# Giá trị lạ của công tắc: rơi về mặc định **kèm notice** — đổi hành vi trong im lặng là
# thứ kế hoạch cấm (và là thứ đã làm vòng 21 tốn thời gian để tìm ra sự thật).
EVIDENCE_MODE_UNKNOWN_CODE = 'EVIDENCE_GATE_MODE_UNKNOWN'

# --------------------------------------------------------------------------------------------
# Vòng 25 (D-33/D-34/D-35) — vòng lặp kế hoạch: cổng phản biện, cổng nguồn, và phần nới hạn chót
# --------------------------------------------------------------------------------------------
# Cùng khuôn ba chế độ với cổng bằng chứng: `off` không kiểm; `warn` ghi sổ + cảnh báo nhưng cho
# đi tiếp; `enforce` từ chối. Giá trị lạ ⇒ rơi về mặc định KÈM notice.
PLAN_VERIFY_ENV = 'BOXFOX_PLAN_VERIFY'
PLAN_VERIFY_MODES = ('enforce', 'warn', 'off')
PLAN_VERIFY_DEFAULT_MODE = 'enforce'
# Cổng nguồn có công tắc RIÊNG: hạ cấp nó (để ghi một kế hoạch dựa vào dữ kiện ngoài) không được
# kéo theo việc cho phép duyệt một kế hoạch chưa ai phản biện.
PLAN_SOURCES_ENV = 'BOXFOX_PLAN_SOURCES_GATE'
PLAN_SOURCES_MODES = ('enforce', 'warn', 'off')
PLAN_SOURCES_DEFAULT_MODE = 'enforce'
# Ngưỡng của cổng bằng chứng `plan_verify` (xem `runtime.plan_verify` cho bốn điều kiện đầy đủ).
PLAN_REVIEW_MIN_ANSWER_CHARS = 400
PLAN_VERIFY_MAX_ISSUES = 30
PLAN_VERIFY_ISSUE_CHARS = 400
PLAN_VERIFY_SUMMARY_CHARS = 800
# Trần số vòng `revise` trong MỘT lượt: quá trần thì model phải báo chủ nhà trung thực kèm danh
# sách lỗi chưa sửa, không được lặp vô hạn.
PLAN_VERIFY_REVISE_MAX = 2
# Nới hạn chót ĐÚNG MỘT LẦN cho mỗi lượt, theo sự kiện `plan_written` (đúng chỗ lượt đang kết
# thúc vì hết giờ), không theo cảm tính của model. Trần hiệu dụng vẫn là `DEADLINE_MAX_SECONDS`.
PLAN_TURN_EXTENSION_SECONDS = 420
PLAN_TURN_EXTENSIONS_MAX = 1
TURN_EXTENDED_CODE = 'TURN_EXTENDED'
# Mã của cổng phản biện, cổng nguồn và đường đánh thức phiên. Một chỗ khai báo để route, sổ và
# giao diện không bao giờ lệch chữ (giao diện đọc chúng từ `runtime_info`, không chép tay).
PLAN_APPROVAL_UNVERIFIED_CODE = 'PLAN_APPROVAL_UNVERIFIED'
PLAN_VERIFY_MODE_UNKNOWN_CODE = 'PLAN_VERIFY_MODE_UNKNOWN'
PLAN_SOURCES_MODE_UNKNOWN_CODE = 'PLAN_SOURCES_GATE_MODE_UNKNOWN'
PLAN_VERIFY_INVALID_CODE = 'PLAN_VERIFY_INVALID'
PLAN_VERIFY_NO_CRITIC_CODE = 'PLAN_VERIFY_NO_CRITIC'
PLAN_VERIFY_VERDICT_MISSING_CODE = 'PLAN_VERIFY_VERDICT_MISSING'
PLAN_VERIFY_VERDICT_MISMATCH_CODE = 'PLAN_VERIFY_VERDICT_MISMATCH'
PLAN_SOURCES_REJECTED_CODE = 'PLAN_SOURCES_REJECTED'
PLAN_WAKE_NO_OWNER_CODE = 'PLAN_WAKE_NO_OWNER'
PLAN_WAKE_FAILED_CODE = 'PLAN_WAKE_FAILED'
# P1.1 — mã của dòng log nói bộ đếm lượt và transcript lệch nhau.
TURN_INDEX_DRIFT_CODE = 'TURN_INDEX_DRIFT'

ANSWER_WARN_CHARS = 60_000
ANSWER_MAX_CHARS = 150_000
ANSWER_LENGTH_WARN_CODE = 'ANSWER_LENGTH_WARN'
ANSWER_TOO_LONG_CODE = 'ANSWER_TOO_LONG'
# Kế hoạch đợt 3 gọi hai mã này là `ANSWER_LONG` / `ANSWER_TRUNCATED`; đợt 1 đã ship chúng dưới tên
# trên và giao diện đang đọc hai tên đó, nên tên trong kế hoạch chỉ là cách gọi, không phải hằng số.
# Dòng chỉ dẫn này sống ở ĐÂY, không chép tay vào từng prompt vai: `runtime.start()` là nơi
# duy nhất dựng prompt hệ thống cho mọi vai, nên mọi prompt đều mang câu này.
ANSWER_LENGTH_HINT = (
    f'Keep the final answer under {ANSWER_WARN_CHARS:,} characters. If the content is longer, '
    'write it to a file in the workspace and quote the path instead of pasting it into the answer.'
)

# --------------------------------------------------------------------------------------------
# Vòng 27 (đợt 1, A-9) — ba công tắc của lớp đọc web (Phạm vi A)
# --------------------------------------------------------------------------------------------
# `WEB_READER` là thang đọc dự phòng: `auto` = luật mới (PDF / non-2xx / rác / thiếu chữ),
# `thin` = ĐÚNG hành vi commit `2add905` (chỉ khi thân bài < 200 ký tự — công tắc hồi quy),
# `off` = không bao giờ gọi đầu đọc. Giá trị lạ ⇒ rơi về mặc định KÈM notice.
WEB_READER_ENV = 'BOXFOX_WEB_READER'
WEB_READER_MODES = ('auto', 'thin', 'off')
WEB_READER_DEFAULT_MODE = 'auto'
# Bộ đệm đọc (`ReadStore`) sống trong bộ nhớ tiến trình: hoặc lưu, hoặc không — không có mức
# giữa nào có nghĩa, nên chỉ hai giá trị (ghi rõ lý do thay vì bịa ra giá trị thứ ba).
WEB_READ_STORE_ENV = 'BOXFOX_WEB_READ_STORE'
WEB_READ_STORE_MODES = ('on', 'off')
WEB_READ_STORE_DEFAULT_MODE = 'on'
# Công tắc lùi cho việc giải nén `Content-Encoding`: thay đổi này chạm MỌI lượt đọc, nên phải có
# đường về `2add905` bằng một biến môi trường thay vì một bản revert.
WEB_DECODE_ENV = 'BOXFOX_WEB_DECODE'
WEB_DECODE_MODES = ('on', 'off')
WEB_DECODE_DEFAULT_MODE = 'on'
# Hai mã notice cho giá trị lạ của công tắc lớp đọc (cùng khuôn hai cổng vòng 25).
WEB_READER_MODE_UNKNOWN_CODE = 'WEB_READER_MODE_UNKNOWN'
WEB_READ_STORE_MODE_UNKNOWN_CODE = 'WEB_READ_STORE_MODE_UNKNOWN'
# Trần của bộ đệm đọc (A-4 dựng `ReadStore` theo đúng con số này); đợt 1 chỉ phơi ra cho giao diện.
READ_STORE_MAX_ENTRIES = 24
# ĐO ĐƯỢC 2026-09-23: trang dài nhất đã đo là `docs.python.org/3/whatsnew/3.13.html`
# (113 936 ký tự) — trần 400 000 ký tự/một bản chứa được nó và cả một bài báo dài, còn trần
# tổng 4 000 000 ký tự là 24 bản đầy (≈ 16 MB nếu là tiếng Việt UTF-8) trong bộ nhớ tiến trình.
READ_STORE_ENTRY_MAX_CHARS = 400_000
READ_STORE_MAX_CHARS = 4_000_000
# `offset` của `read_source`/`web_fetch`: kẹp trần để một con số sai không thành phép cắt im lặng.
READ_OFFSET_MAX = 5_000_000
# `find` nhận tối đa bốn từ khoá một lời gọi (nhiều hơn thì mỗi từ chỉ còn một mẩu vụn).
READ_FIND_MAX_TERMS = 4
# --- Vòng 27 (đợt 2, A-6/A-7) — nguồn học thuật và lớp tìm kiếm -------------------------------
# OpenAlex 'polite pool': `mailto` là địa chỉ liên hệ, KHÔNG phải khoá. Mặc định là một địa chỉ
# trung tính của dự án — không lấy địa chỉ cá nhân của ai (đo 2026-09-23: Crossref 429 rồi 200 khi
# có `mailto`; OpenAlex trả lời nhanh hơn cùng lúc).
OPENALEX_MAILTO_ENV = 'BOXFOX_OPENALEX_MAILTO'
OPENALEX_MAILTO_DEFAULT = 'boxfox-agent@example.invalid'
# `paper_citations`: `limit` là số hàng trả về (1–25); một lời gọi `backward` phân giải tối đa 50
# mã tham chiếu trong MỘT request `filter=openalex_id:…` (đo: 54 tham chiếu cho W2741809807).
PAPER_CITATIONS_LIMIT_MAX = 25
PAPER_CITATIONS_RESOLVE_MAX = 50
# Lớp tìm kiếm (A-7): một cache trong tiến trình là chỗ duy nhất chống đốt chân keyless (đo: cùng
# truy vấn tốn ~0,7 s mỗi lần), và `web_search` chạy tối đa ba truy vấn TUẦN TỰ (D-13/F7: không
# tool song song trong một bước).
SEARCH_CACHE_TTL_SECONDS = 300
SEARCH_CACHE_MAX_ENTRIES = 16
SEARCH_QUERY_MAX = 3
# Ngân sách ký tự cho CÁC HÀNG của một lời gọi `web_search`.
# VÌ SAO CÓ: `queries` cho phép 3 chân × `count` 10 hàng, mỗi hàng tới ~900 ký tự (tiêu đề 400 +
# đoạn trích 400 + URL + khung JSON) ⇒ ~27 000 ký tự, mà runtime cắt kết quả công cụ ở 24 000
# (giữ 20 000) ⇒ JSON bị cắt GIỮA CHỪNG và các hàng cuối biến mất im lặng. Ngân sách này giữ
# payload dưới trần ấy và nói ra số hàng bị bỏ (`dropped`).
SEARCH_PAYLOAD_CHARS = 18_000
SEARCH_RETRY_ATTEMPTS = 2

# --- Vòng research v2 (P0b) — lớp tìm kiếm 10 bước (#6077) -------------------------------------
# Hợp đồng `/code/.plans/p0-interfaces.md` §6: ĐÚNG những hằng dưới đây, không thêm bớt tên.
# Nguồn nội dung: kế hoạch v2 §5.4.1 (bước 2 hạn chờ, bước 4 k=60, bước 5 đa dạng tên miền),
# §5.4.2 (mặc định riêng tư), §5.4.3 (học thuật), §5.4.4 (top-k). Mọi con số là [ƯỚC LƯỢNG] và
# được chỉnh trên tập `dev` của 8.7, KHÔNG chỉnh trên tập `test`.
SEARXNG_TIMEOUT_SECONDS = 8.0
ACADEMIC_TIMEOUT_SECONDS = 10.0
SEARCH_PIPELINE_VARIANTS_L2 = 6
SEARCH_PIPELINE_VARIANTS_L3 = 10
SEARCH_RRF_K = 60
SEARCH_PER_DOMAIN_TOP = 2
# Cầu dao engine: 3 lần lỗi liên tiếp ⇒ ngưng 5', rồi 15', rồi 60' (bước 7, lùi theo cấp số).
SEARCH_ENGINE_FAIL_STREAK = 3
SEARCH_ENGINE_SUSPEND_SECONDS = (300, 900, 3600)
# Bộ đệm bền (bước 9): web chung 24 h · tin tức/hiện trạng 6 h · metadata học thuật 7 ngày.
SEARCH_CACHE_TTL_WEB = 24 * 3600
SEARCH_CACHE_TTL_NEWS = 6 * 3600
SEARCH_CACHE_TTL_ACADEMIC = 7 * 86400
SEARCH_PIPELINE_TOP_K = 8
SEARCH_ENGINE_ROTATION_N = 4
SEARCH_WEIGHTS = {'rrf': 0.4, 'bm25': 0.2, 'llm': 0.3, 'tier': 0.05, 'fresh': 0.05}
PAPERS_GROUP_MAX_LEGS = 6
OPENALEX_DAILY_CALLS_DEFAULT = 50


def _web_switch(name, modes, default):
    """Giá trị công tắc trong `modes`, hoặc `default` khi biến trống/giá trị lạ."""
    raw = (os.environ.get(name) or '').strip().lower()
    return raw if raw in modes else default


def web_reader_mode():
    """Mức đang áp của thang đọc (`BOXFOX_WEB_READER`)."""
    return _web_switch(WEB_READER_ENV, WEB_READER_MODES, WEB_READER_DEFAULT_MODE)


def web_read_store_mode():
    """`on`/`off` cho bộ đệm đọc (`BOXFOX_WEB_READ_STORE`)."""
    return _web_switch(WEB_READ_STORE_ENV, WEB_READ_STORE_MODES, WEB_READ_STORE_DEFAULT_MODE)


def web_decode_mode():
    """`on`/`off` cho việc giải nén thân bài (`BOXFOX_WEB_DECODE`)."""
    return _web_switch(WEB_DECODE_ENV, WEB_DECODE_MODES, WEB_DECODE_DEFAULT_MODE)


# --- Vòng 27 (đợt 3–8) — sổ nguồn, ba mức, bốn pha, can thiệp giữa lượt ----------------------
# Một chỗ duy nhất để rà soát (hợp đồng `/var/tmp/v27/iface.md` §2): mọi hằng của đợt 3–8 ở đây.

# Ba mức việc research. Mức 2 là MẶC ĐỊNH (mơ hồ ⇒ 2), mức 3 là mức đắt nhất.
RESEARCH_TIERS = (1, 2, 3)
RESEARCH_TIER_DEFAULT = 2
RESEARCH_TIER_BRANCHES = {1: 1, 2: 5, 3: 15}        # trần nhánh cho CẢ VIỆC (mức 3 ≤ 3 sóng)
RESEARCH_TIER_WAVE_SIZE = {1: 1, 2: 5, 3: 5}        # số nhánh mỗi sóng (D-41)
RESEARCH_TIER_WAVES = {1: 1, 2: 1, 3: 3}            # số sóng
RESEARCH_TIER_CHILD_STEPS = {1: 20, 2: 40, 3: 40}   # bước tối đa của một nhánh con
RESEARCH_TIER_CHILD_SECONDS = {1: 180, 2: 420, 3: 900}   # trần thời gian một nhánh con
RESEARCH_TIER_TURN_SECONDS = {1: 1200, 2: 1200, 3: 3600}  # D-40: mức 3 = 3 600 s cho cả lượt
RESEARCH_TIER_HARD_CEILING_SECONDS = {1: 1200, 2: 1800, 3: 7200}  # trần cứng 30'/120'
RESEARCH_TIER_CRITIQUE = {1: False, 2: False, 3: True}   # #6024: chỉ mức 3 bắt buộc phản biện
RESEARCH_TURN_EXTENSION_SECONDS_TIER3 = 1800         # một lần chủ nhà nới trần ở mức 3

# Nhịp báo tiến độ (#5969).
RESEARCH_PROGRESS_ENV = 'BOXFOX_RESEARCH_PROGRESS'
RESEARCH_PROGRESS_MODES = ('on', 'off')
RESEARCH_PROGRESS_DEFAULT_MODE = 'on'
RESEARCH_PROGRESS_NUDGE_SECONDS = 600
RESEARCH_PROGRESS_MAX_PER_TURN = 12

# Brief bắt buộc trước khi chạy (#5964): `warn` là mặc định — chạy được ngay, nhưng có tiếng nói.
RESEARCH_BRIEF_ENV = 'BOXFOX_RESEARCH_BRIEF'
RESEARCH_BRIEF_MODES = ('enforce', 'warn', 'off')
RESEARCH_BRIEF_DEFAULT_MODE = 'warn'

# Cổng chất lượng hồ sơ (`research_quality`).
RESEARCH_GATE_ENV = 'BOXFOX_RESEARCH_GATE'
RESEARCH_GATE_MODES = ('enforce', 'warn', 'off')
RESEARCH_GATE_DEFAULT_MODE = 'enforce'
RESEARCH_QUALITY_PREFIX = 'RESEARCH_QUALITY_REJECTED'
RESEARCH_MIN_EXCERPT_CHARS = 80
RESEARCH_MAX_ROWS_PER_DOSSIER = 400
RESEARCH_BRIEF_MISSING_CODE = 'RESEARCH_BRIEF_MISSING'
RESEARCH_GATE_NOTE_CODE = 'RESEARCH_GATE_NOTE'
RESEARCH_GATE_MODE_UNKNOWN_CODE = 'RESEARCH_GATE_MODE_UNKNOWN'
RESEARCH_BRIEF_MODE_UNKNOWN_CODE = 'RESEARCH_BRIEF_MODE_UNKNOWN'
RESEARCH_TIER_INVALID_CODE = 'RESEARCH_TIER_INVALID'
RESEARCH_LEVEL_INVALID_CODE = 'RESEARCH_LEVEL_INVALID'
RESEARCH_PROFILE_INVALID_CODE = 'RESEARCH_PROFILE_INVALID'
RESEARCH_BRIEF_TAKEN_CODE = 'RESEARCH_BRIEF_TAKEN'
DOSSIER_DIR_MISMATCH_CODE = 'DOSSIER_DIR_MISMATCH'

# Pha phản biện độc lập (#5968, #6024): `revise` chặn MỘT vòng cho mỗi version.
RESEARCH_REVIEW_MIN_ANSWER_CHARS = 400
RESEARCH_VERIFY_REVISE_MAX = 1
RESEARCH_VERIFY_MAX_ISSUES = 30
RESEARCH_VERIFY_ISSUE_CHARS = 400
RESEARCH_VERIFY_SUMMARY_CHARS = 800
RESEARCH_VERIFY_NO_CRITIC_CODE = 'RESEARCH_VERIFY_NO_CRITIC'
RESEARCH_VERIFY_VERDICT_MISSING_CODE = 'RESEARCH_VERIFY_VERDICT_MISSING'
RESEARCH_VERIFY_VERDICT_MISMATCH_CODE = 'RESEARCH_VERIFY_VERDICT_MISMATCH'
RESEARCH_VERIFY_VERSION_MISSING_CODE = 'RESEARCH_VERIFY_VERSION_MISSING'
RESEARCH_VERIFY_UNKNOWN_CODE = 'RESEARCH_VERIFY_UNKNOWN'
RESEARCH_CRITIQUE_MISSING_CODE = 'RESEARCH_CRITIQUE_MISSING'
RESEARCH_CRITIQUE_LABEL = 'chưa đạt phản biện'
# #6025 — soi ý kiến chủ nhà: `research_brief` nhận `ownerViews` (ý kiến/giả định/khẳng định của
# chủ nhà nói trong yêu cầu), và hồ sơ phải có mục riêng đủ ba nhãn, mỗi nhãn kèm nguồn.
RESEARCH_OWNER_VIEWS_CODE = 'RESEARCH_OWNER_VIEWS'
RESEARCH_OWNER_VIEWS_MAX = 12
RESEARCH_OWNER_VIEW_CHARS = 300

# Mã của đường research (đợt 3–8): bốn thông điệp nêu ĐÚNG cách sửa (#5970, #5982, D-40).
RESEARCH_TIER_DEFAULTED_CODE = 'RESEARCH_TIER_DEFAULTED'
RESEARCH_CEILING_CLAMPED_CODE = 'RESEARCH_CEILING_CLAMPED'
RESEARCH_BRIEF_UPDATED_CODE = 'RESEARCH_BRIEF_UPDATED'
RESEARCH_BRIEF_RAISE_REFUSED_CODE = 'RESEARCH_BRIEF_RAISE_REFUSED'
RESEARCH_BRANCH_LIMIT_CODE = 'RESEARCH_BRANCH_LIMIT'
RESEARCH_HARD_CEILING_NOTICE_CODE = 'RESEARCH_HARD_CEILING'

# Chỉ thị giữa lượt (#5981) + nhịp tiến độ (#5969).
STEER_ENV = 'BOXFOX_STEER'
STEER_MODES = ('on', 'off')
STEER_DEFAULT_MODE = 'on'
STEER_MAX_PENDING = 5
STEER_DRAIN_MAX = 3
STEER_TEXT_MAX_CHARS = 4000
OWNER_STEER_PREFIX = '[Chỉ thị giữa lượt của chủ nhà]'
RESEARCH_NUDGE_PREFIX = '[Nhịp tiến độ:'
STEER_MODE_UNKNOWN_CODE = 'STEER_MODE_UNKNOWN'
OWNER_STEER_EVENT_CODE = 'OWNER_STEER'

# Phòng hồ sơ trong workspace (.research) — hình dạng khớp `deploy/docker/research_files.py`.
DOSSIER_ROOM = '.research'
RESEARCH_SLUG_RE = r'^[a-z0-9]+(-[a-z0-9]+)*$'
DOSSIER_MAX_BYTES = 262_144
# Số lần thử ghi một bản hồ sơ: số bản tính từ CHỈ MỤC, mà tệp `v<N>` trong phòng có thể nhiều
# hơn chỉ mục (ghi hỏng giữa chừng, phòng dựng bằng tay) — op của box từ chối bản đã có, nên
# phải thử bản kế tiếp trong ngân sách này thay vì chết ở bản đã chiếm.
DOSSIER_VERSION_ATTEMPTS_MAX = 10
RESEARCH_FILENAME_RE = r'^v([1-9][0-9]{0,9})-([a-z0-9]+(-[a-z0-9]+)*)\.md$'

# Sổ nguồn (`research_ledger`).
SOURCE_ROW_PREFIX = 'r'
SOURCE_EXCERPT_MAX_CHARS = 2000
SOURCE_CLAIM_MAX_CHARS = 400
SOURCE_ORIGIN_MAX_CHARS = 120
SOURCE_UNIT_MERGE_JACCARD = 0.85
SOURCE_ROW_LIMIT_DEFAULT = 50
SOURCE_ROW_LIMIT_MAX = 200
SOURCE_SPOT_TARGETS = ('vanban.chinhphu.vn', 'vbpl.vn', 'moh.gov.vn', 'thuvienphapluat.vn')
SOURCE_FAKE_SUCCESS_TITLE_MARKERS = ('Trang chủ', 'Warning: This page maybe not yet fully loaded')
SOURCE_FAKE_SUCCESS_MIN_CHARS = 300


# --- P1 research mode (appended block) ---
# Vỏ chế độ Research (plan v2 §4.1, §5.2, §5.3, §5.12). Mọi hằng ở đây chỉ thuộc pha P1; khối
# này nằm CUỐI tệp để không đụng phần thân mà một tác nhân khác đang sửa.
#
# Công tắc giết: mặc định `on` = tính năng CÓ MẶT, nhưng mọi phiên vẫn bắt đầu với mode TẮT
# (mode chỉ bật khi người dùng bấm nút hoặc gõ `/research`). `off` ⇒ mọi hành vi cũ của f17d54b.
RESEARCH_MODE_ENV = 'BOXFOX_RESEARCH_MODE'
RESEARCH_MODE_MODES = ('on', 'off')
# Mặc định `on`: tính năng CÓ MẶT (vỏ mode + cửa 1..4 chạy thật). Người dùng vẫn phải TỰ bật mode
# cho từng phiên. `off` là công tắc giết, quay về đúng f17d54b. Docstring `runtime.research_mode_available`
# và ý O1 của kế hoạch đã nói `on`; để `off` thì cả P1 là mã chết (review F4).
RESEARCH_MODE_DEFAULT_MODE = 'on'

# Mức 3 chỉ mở được trong mode (cổng bốn cửa, §5.2). `off` ⇒ main được mở mức 3 như cũ.
RESEARCH_TIER3_MODE_ONLY_ENV = 'BOXFOX_RESEARCH_TIER3_MODE_ONLY'
RESEARCH_TIER3_MODE_ONLY_MODES = ('on', 'off')
RESEARCH_TIER3_MODE_ONLY_DEFAULT_MODE = 'on'

# Chạy nền khi tắt mode (#6078). `off` ⇒ tắt mode luôn tạm dừng run (không có lựa chọn chạy nền).
RESEARCH_BACKGROUND_RUNS_ENV = 'BOXFOX_RESEARCH_BACKGROUND_RUNS'
RESEARCH_BACKGROUND_RUNS_MODES = ('on', 'off')
RESEARCH_BACKGROUND_RUNS_DEFAULT_MODE = 'on'

# Mỗi lượt research nhắm xong trong ngắn hạn (5.3); việc dài chạy qua nhiều lượt tiếp tục.
RESEARCH_TURN_TARGET_SECONDS_ENV = 'BOXFOX_RESEARCH_TURN_TARGET_SECONDS'
RESEARCH_TURN_TARGET_SECONDS = 600

# Mã lỗi/sự kiện ổn định cho giao diện và test.
RESEARCH_MODE_REQUIRED_CODE = 'RESEARCH_MODE_REQUIRED'
RESEARCH_MODE_EXIT_CHOICE_REQUIRED_CODE = 'RESEARCH_EXIT_CHOICE_REQUIRED'
# Công tắc `BOXFOX_RESEARCH_MODE=off`: API bật/tắt mode phải trả lỗi RÕ thay vì bật một chế độ
# nửa vời (mọi cổng khác đều tắt khi công tắc tắt).
RESEARCH_MODE_UNAVAILABLE_CODE = 'RESEARCH_MODE_UNAVAILABLE'
RESEARCH_SCOPE_REVISION_STALE_CODE = 'RESEARCH_SCOPE_REVISION_STALE'
# Khoá lạc quan nhận thẳng từ thân HTTP: giá trị không phải số phải trả về một MÃ hợp đồng, chứ
# không phải `int() argument must be ...` của Python (đợt soát `ed485f3`, finding 2).
RESEARCH_SCOPE_REVISION_INVALID_CODE = 'RESEARCH_SCOPE_REVISION_INVALID'
RESEARCH_JOB_BUDGET_EXHAUSTED_CODE = 'RESEARCH_JOB_BUDGET_EXHAUSTED'
RESEARCH_MODE_ENTRY_BY = ('toggle', 'command')
RESEARCH_MODE_BLOCK_MARKER = '=== ACTIVE MODE: RESEARCH ==='
RESEARCH_MODE_BLOCK_END = '=== END ACTIVE MODE ==='
RESEARCH_MODE_EVENT_CODE = 'research_mode'
# Khối bàn giao research → main (§5.10). Cặp mốc này là hợp đồng để `_sync_mode_block` GỠ được khối
# cũ trước khi chèn khối mới: chỉ-ghi-thêm thì mỗi bản hồ sơ để lại một khối cũ nằm mãi trong
# prompt hệ thống (đo sống 2026-09-25: hồ sơ v4 ⇒ prompt mang CẢ nhãn `partial` của v3 lẫn
# `status completed` của v4).
RESEARCH_HANDOFF_BLOCK_MARKER = '=== RESEARCH HANDOFF ==='
RESEARCH_HANDOFF_BLOCK_END = '=== END RESEARCH HANDOFF ==='
# Dòng nhắc "run đang chạy nền" ở lượt main (§5.2). Cặp mốc cũng là hợp đồng để `_sync_mode_block`
# GỠ khối của lượt trước trước khi chèn lại: chỉ-ghi-thêm thì mỗi lượt chất thêm một bản (đo sống
# 2026-09-25: ba lượt ⇒ ba khối trong cùng một prompt hệ thống).
RESEARCH_BACKGROUND_BLOCK_MARKER = '=== BACKGROUND RESEARCH RUN ==='
RESEARCH_BACKGROUND_BLOCK_END = '=== END BACKGROUND RESEARCH RUN ==='

# Công cụ bị BỎ khỏi hồ sơ lượt khi ở mode: mode không có công cụ ghi (5.2, M-14).
RESEARCH_MODE_EXCLUDED_TOOLS = frozenset({'file_write', 'file_edit_block', 'terminal_exec',
                                          'write_plan', 'plan_verify'})
# Vai con mà `delegate_task` của mode được phép giao (5.2).
RESEARCH_MODE_DELEGATE_ROLES = frozenset({'research', 'research-review', 'explore'})

# Thẻ phạm vi (5.3, 5.12): vòng hỏi tối đa 3 câu; lựa chọn mỗi câu 2–5.
RESEARCH_SCOPE_MAX_QUESTIONS = 3
RESEARCH_PROMPT_KINDS = ('interview', 'scope-change', 'exit-choice', 'out-of-scope', 'budget')
RESEARCH_EXIT_CHOICES = ('pause', 'background')

# Cờ `state` của một job trong mode.
RESEARCH_JOB_ORIGIN = 'mode'
RESEARCH_JOB_ORIGIN_MAIN = 'main'


# --- P2 research evidence / time / coverage (appended block) ----------------
# Mô hình bằng chứng, chính sách thời gian và bản đồ bao phủ (plan v2 §5.5–5.8, §7 P2). Mọi hằng ở
# đây chỉ thuộc pha P2/P3; khối nằm CUỐI tệp để không đụng phần thân. Mặc định `on` = tính năng CÓ
# MẶT; `off` = hành vi y hệt `6eb2fd8` (mọi cổng mới tắt, cổng cũ dò tiêu đề vẫn chạy).
RESEARCH_COVERAGE_ENV = 'BOXFOX_RESEARCH_COVERAGE'
RESEARCH_COVERAGE_MODES = ('on', 'off')
RESEARCH_COVERAGE_DEFAULT_MODE = 'on'

# Cổng cấu trúc thay cho dò từ khoá tiêu đề (`research_quality.DOSSIER_SECTIONS`).
RESEARCH_STRUCTURED_REPORT_ENV = 'BOXFOX_RESEARCH_STRUCTURED_REPORT'
RESEARCH_STRUCTURED_REPORT_MODES = ('on', 'off')
RESEARCH_STRUCTURED_REPORT_DEFAULT_MODE = 'on'

# Cửa sổ "hiện trạng" (5.6): nhận định `trend`/`current-fact` chỉ đỡ bằng nguồn ngoài cửa sổ ⇒ lỗi.
RESEARCH_TIME_POLICY_ENV = 'BOXFOX_RESEARCH_TIME_POLICY'
RESEARCH_TIME_POLICY_MODES = ('on', 'off')
RESEARCH_TIME_POLICY_DEFAULT_MODE = 'on'

# Mã ổn định cho cổng/test/giao diện.
RESEARCH_STALE_CURRENT_CLAIM_CODE = 'research-stale-current-claim'
RESEARCH_REPORT_STRUCTURE_CODE = 'research-report-structure'
RESEARCH_STALE_CURRENT_CLAIM_LABEL = 'nguồn cũ cho nhận định hiện trạng'

# Bão hoà (5.5): hai sóng liên tiếp dưới 10% kết quả mới ⇒ `saturated`; săn trích dẫn dừng sau 3 vòng
# liên tiếp không thêm bài mới liên quan (#6008).
RESEARCH_SATURATION_NEW_RATIO = 0.10
RESEARCH_SATURATION_WAVES = 2
RESEARCH_CITATION_CHASE_STOP_ROUNDS = 3

# --- P3 subagent roles (appended block) -------------------------------------
# Vai con và hợp đồng của chúng (plan v2 §5.9, §5.11, §7 P3, §8.4). Không thêm vai mới vào
# `ROLES`: dùng `task.kind` trên hai vai có sẵn `research` và `research-review`.
RESEARCH_BRANCH_REPORT_ENV = 'BOXFOX_RESEARCH_BRANCH_REPORT'
RESEARCH_BRANCH_REPORT_MODES = ('on', 'off')
RESEARCH_BRANCH_REPORT_DEFAULT_MODE = 'on'
RESEARCH_BRANCH_REPORT_MISSING_CODE = 'RESEARCH_BRANCH_REPORT_MISSING'

# Phản biện bắt buộc từ mức 2 (#6072, §5.11). `off` ⇒ quay lại `RESEARCH_TIER_CRITIQUE` cũ.
RESEARCH_CRITIQUE_TIER2_ENV = 'BOXFOX_RESEARCH_CRITIQUE_TIER2'
RESEARCH_CRITIQUE_TIER2_MODES = ('on', 'off')
RESEARCH_CRITIQUE_TIER2_DEFAULT_MODE = 'on'

#: Kiểu việc của một nhánh con (`delegate_task.taskKind`). Không phải vai mới: vai vẫn là
#: `research` hoặc `research-review`, quyền công cụ giữ nguyên đã kiểm.
RESEARCH_BRANCH_KINDS = ('branch', 'deep-read', 'counter', 'critique', 'evidence', 'coverage')
RESEARCH_TASK_KIND_INVALID_CODE = 'RESEARCH_TASK_KIND_INVALID'
RESEARCH_TASK_KIND_DEFAULT = 'branch'

#: Mã phát hiện của bên soát (§5.9). Giữ `severity`; `kind` là trường MỚI, thêm được, không đổi cũ.
RESEARCH_ISSUE_KINDS = ('unsupported', 'misattributed', 'outdated', 'missing-direction',
                        'counter-evidence', 'reasoning', 'fit', 'unlabeled-assumption')
#: Phát hiện `missing-direction` mức cao chưa xử lý ⇒ nhãn này trên hồ sơ (§5.9).
RESEARCH_COVERAGE_LABEL = 'bao phủ chưa đủ'
#: Nhãn khi vòng sửa vẫn bị `revise` (#5968) — đã có từ trước, nhắc lại cho một chỗ đọc.
RESEARCH_CRITIQUE_LABEL_KEPT = 'chưa đạt phản biện'

#: Thẻ trích xuất của con `deep-read`: số nguồn trụ cột mỗi lần theo mức (§5.9, §5.11).
RESEARCH_DEEP_READ_SOURCES = {1: 0, 2: 2, 3: 10}
RESEARCH_EXTRACTION_MAX_FIELDS = 24

#: Ngưỡng nghiệm thu của bộ lỗi cấy sẵn (§8.4): critic+verifier bắt ≥ 70% lỗi dữ kiện/gán sai;
#: coverage reviewer bắt ≥ 60% hướng lớn bị gỡ; tỉ lệ báo sai ≤ 20% [ƯỚC LƯỢNG ngưỡng].
RESEARCH_SEEDED_CATCH_MIN = 0.70
RESEARCH_SEEDED_COVERAGE_MIN = 0.60
RESEARCH_SEEDED_FALSE_ALARM_MAX = 0.20
RESEARCH_SEEDED_DEFECT_KINDS = ('wrong-number', 'unsupported-claim', 'misattributed',
                                'outdated-supports-current', 'removed-direction', 'survey-as-proposal',
                                'unlabeled-assumption', 'same-origin-independent',
                                'mismatched-benchmark')

# --- P5 (làm mới báo cáo) ----------------------------------------------------
#: Run LÀM MỚI (`refresh`, use case H của §5.1) — công tắc giết: `off` ⇒ tuyến `refresh` biến mất,
#: hành vi y hệt `6eb2fd8`.
RESEARCH_REFRESH_ENV = 'BOXFOX_RESEARCH_REFRESH'
RESEARCH_REFRESH_MODES = ('on', 'off')
RESEARCH_REFRESH_DEFAULT_MODE = 'on'
RESEARCH_REFRESH_MODE_UNKNOWN_CODE = 'RESEARCH_REFRESH_MODE_UNKNOWN'
#: Dòng sổ của run cũ chép sang run làm mới được đánh dấu thế nào (§5.3): chưa đọc lại thì không
#: được đỡ một nhận định "hiện trạng".
RESEARCH_REFRESH_INHERITED_STATUS = 'unverified'
#: Trạng thái một dòng sổ coi như RÚT khỏi run làm mới (nguồn cũ không còn đọc lại được).
RESEARCH_REFRESH_WITHDRAWN_STATUSES = ('blocked', 'unverified', 'gone', 'removed')
#: Mã lỗi của tuyến làm mới.
RESEARCH_REFRESH_DISABLED_CODE = 'RESEARCH_REFRESH_DISABLED'
RESEARCH_REFRESH_NO_DOSSIER_CODE = 'RESEARCH_REFRESH_NO_DOSSIER'
RESEARCH_REFRESH_SOURCE_ACTIVE_CODE = 'RESEARCH_REFRESH_SOURCE_ACTIVE'
RESEARCH_REFRESH_RUN_ACTIVE_CODE = 'RESEARCH_REFRESH_RUN_ACTIVE'


# --- Công tắc P2/P3: một chỗ đọc --------------------------------------------
# `runtime._env_switch` là bản riêng tư của P1. P2/P3 đọc công tắc qua đây để không mọc bản sao thứ
# ba, và để bài kiểm truyền `env={...}` thay vì vá `os.environ` (thứ tự kiểm không ảnh hưởng nhau).
def env_switch(name, modes, default, env=None):
    """Giá trị công tắc trong `modes`; biến trống hoặc giá trị lạ ⇒ `default` (không bao giờ ném)."""
    source = os.environ if env is None else env
    raw = str(source.get(name) or '').strip().lower()
    return raw if raw in modes else default


def research_coverage_enabled(env=None):
    """`BOXFOX_RESEARCH_COVERAGE`: `on` (mặc định) ⇒ facet, bão hoà và cổng bao phủ CÓ MẶT.

    Mặc định `on` là "tính năng CÓ MẶT", không phải "đang bật": một run chỉ dựng bản đồ bao phủ khi
    mode `/research` đang bật, còn `off` là đường lùi về đúng hành vi `6eb2fd8`.
    """
    return env_switch(RESEARCH_COVERAGE_ENV, RESEARCH_COVERAGE_MODES,
                      RESEARCH_COVERAGE_DEFAULT_MODE, env) == 'on'


def research_structured_report_enabled(env=None):
    """`BOXFOX_RESEARCH_STRUCTURED_REPORT`: `on` ⇒ cổng kiểm CẤU TRÚC; `off` ⇒ quay lại dò tiêu đề."""
    return env_switch(RESEARCH_STRUCTURED_REPORT_ENV, RESEARCH_STRUCTURED_REPORT_MODES,
                      RESEARCH_STRUCTURED_REPORT_DEFAULT_MODE, env) == 'on'


def research_time_policy_enabled(env=None):
    """`BOXFOX_RESEARCH_TIME_POLICY`: `on` ⇒ có cửa sổ "hiện trạng" và lỗi nguồn cũ."""
    return env_switch(RESEARCH_TIME_POLICY_ENV, RESEARCH_TIME_POLICY_MODES,
                      RESEARCH_TIME_POLICY_DEFAULT_MODE, env) == 'on'


def research_critique_tier2_enabled(env=None):
    """`BOXFOX_RESEARCH_CRITIQUE_TIER2`: `on` (mặc định) ⇒ phản biện từ mức 2 (vòng 34, #6072).

    `off` ⇒ quay lại đúng `RESEARCH_TIER_CRITIQUE` (critic chỉ ở mức 3).
    """
    return env_switch(RESEARCH_CRITIQUE_TIER2_ENV, RESEARCH_CRITIQUE_TIER2_MODES,
                      RESEARCH_CRITIQUE_TIER2_DEFAULT_MODE, env) == 'on'


def research_branch_report_enabled(env=None):
    """`BOXFOX_RESEARCH_BRANCH_REPORT`: `on` ⇒ con research trả thẻ có cấu trúc; `off` ⇒ văn bản tự do."""
    return env_switch(RESEARCH_BRANCH_REPORT_ENV, RESEARCH_BRANCH_REPORT_MODES,
                      RESEARCH_BRANCH_REPORT_DEFAULT_MODE, env) == 'on'


def research_refresh_enabled(env=None):
    """`BOXFOX_RESEARCH_REFRESH`: `on` (mặc định) ⇒ `PATCH .../jobs/{id}` nhận `action: 'refresh'`."""
    return env_switch(RESEARCH_REFRESH_ENV, RESEARCH_REFRESH_MODES,
                      RESEARCH_REFRESH_DEFAULT_MODE, env) == 'on'
