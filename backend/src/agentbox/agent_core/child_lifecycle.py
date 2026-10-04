"""H11 — kết cục của một con, nhìn thấy được: `timedOut` / `partial` / `resumable`.

Vì sao cần một chỗ ĐỌC DUY NHẤT: trước H11, cha chỉ thấy `status` + `reason` thô của con
(`failed/WATCHDOG_TIMEOUT`, `partial/STEP_BUDGET_EXHAUSTED`, ...) và mỗi chỗ đọc tự diễn giải — sổ
con, event `child`, kết quả `delegate_task`, hàng attempt của kho task. Chủ nhà chốt (#6545, việc 3)
rằng ba câu hỏi phải trả lời được mà KHÔNG phải đoán:

- **`timedOut`** — con bị một luật THỜI GIAN cắt (hạn chót của chính nó, hoặc watchdog cắt vì vượt
  trần tường). Đây là ca "việc còn dở vì hết giờ", không phải "con hỏng".
- **`partial`** — con có câu trả lời nhưng câu trả lời đó DỞ (chạm trần bước, hạn chót, trần output
  của nhà cung cấp, hoặc câu trả lời bị cắt ở trần độ dài). Việc dùng được, chỉ là chưa trọn.
- **`resumable`** — `child_resume` được phép gọi lại CHÍNH con đó với nguyên ngữ cảnh: chỉ đúng khi
  con đã dừng VÌ MỘT TRẦN (thời gian hoặc ngân sách). Con `completed` (xong), `cancelled`
  (chủ nhà/cha huỷ) hay `failed` vì một lỗi khác thì gọi lại là sai việc — và `resume_child` từ chối.

Từ vựng trạng thái của hàng `sessions` KHÔNG đổi (bất biến #1: không thêm trạng thái mới); hai cờ
này là dẫn xuất, sống cạnh `status`/`reason` trong mọi payload mà cha đọc.
"""

from . import limits

#: Bị cắt vì THỜI GIAN: hạn chót của con (`DEADLINE_EXCEEDED`) hoặc watchdog cắt vì vượt trần tường.
TIMED_OUT_REASONS = frozenset({
    limits.DEADLINE_NOTICE_CODE,
    limits.WATCHDOG_TIMEOUT_REASON,
})

#: Câu trả lời DỞ: hết bước, hết giờ, bị nhà cung cấp cắt ở trần output, hoặc bị cắt ở trần độ dài.
PARTIAL_REASONS = TIMED_OUT_REASONS | {
    limits.STEP_BUDGET_NOTICE_CODE,
    limits.TRUNCATED_OUTPUT_NOTICE_CODE,
    limits.ANSWER_TOO_LONG_CODE,
}


def outcome(status, reason=None):
    """`{timedOut, partial, resumable}` cho một hàng sổ con đã đóng.

    Ba cờ này là cách ĐỌC `status`/`reason` — chúng không thay hai trường đó, nên chỗ gọi cứ giữ
    nguyên `status`/`reason` của mình rồi trải thêm ba cờ. `resumable` đúng khi con đã dừng vì một
    trần (thời gian hoặc ngân sách) và hàng sổ đã đóng; con đang chạy (`started`/`running`) không
    nằm trong đây vì gọi lại một con đang chạy là việc của `task_send`.
    """
    status = str(status or '')
    reason = str(reason or '')
    timed_out = reason in TIMED_OUT_REASONS
    partial = status == 'partial' or reason in PARTIAL_REASONS
    resumable = status in ('partial', 'failed') and (timed_out or partial)
    return {'timedOut': timed_out, 'partial': partial, 'resumable': resumable}
