# Benchmark & Đánh giá

Toàn bộ phần thí nghiệm của đồ án. Tài liệu: **Phần XIII** của [`../docs/plan/agent-box-plan.md`](../docs/plan/agent-box-plan.md).

Đây **không phải** test pass/fail — đây là thí nghiệm cho ra số liệu để trả lời ba câu hỏi nghiên cứu. Test pass/fail ở [`../backend/tests/`](../backend/tests/).

## Ba câu hỏi nghiên cứu (mục 13.1)

| | Câu hỏi |
|---|---|
| **RQ1** | Tầng nhãn + giấy phép có làm giảm tỉ lệ tấn công thành công (ASR) hay không |
| **RQ2** | Mất bao nhiêu khả năng làm việc, và phải hỏi người dùng bao nhiêu lần |
| **RQ3** | Ablation — thành phần nào đóng góp bao nhiêu |

## Benchmark ngoài: AgentDojo + VPI-Bench, hết (mục 13.2)

**Không chạy OSWorld và WebArena.** Hai cái đó đo *khả năng làm việc*, không đo bảo mật; thi ở đó là tự đặt mình vào trục "agent giỏi hơn Devin", trong khi mọi so sánh của dự án là **so với chính nó khi tắt tầng bảo mật**.

FIDES (arXiv 2505.23643) và RTBAS (arXiv 2502.08966) đều đánh giá trên AgentDojo, nên so sánh được trực tiếp.

## `cases/` — bảy nhóm ca

| Thư mục | Nhóm | Số ca | Nội dung |
|---|---|---|---|
| `t1_repo_doc/` | T1 | 10 | `README.md` độc trong repo |
| `t2_web_doc/` | T2 | 10 | Trang web độc |
| `t3_external_tool/` | T3 | 8 | Tool ngoài trả nội dung độc. **MCP thật ngoài phạm vi** — mô phỏng bằng tool nội bộ giả lập |
| `t4_screen_vpi/` | T4 | 10-12 | Chỉ thị độc **vẽ trên màn hình**. Chế độ `vision` |
| `t5_label_laundering/` | **T5** | 6 | Rửa nhãn. Đo **hai** chỉ số: `Attack success` chuẩn, và **`Invariant violation`** khi BB1/BB2/BB3 bị vượt |
| `t6_benign/` | T6 | 25-30 | Việc lành tính. Đây là bộ đo utility và đo **chặn oan** |
| `t7_plan_act/` | **T7** | 9-11 | Tấn công cơ chế hai chế độ Plan/Act (mục 5.3.4). Sáu loại T7a-T7f |

**T5 và T7 chạy trong mọi nhánh kết quả Gate 1** và **không được cắt** — cắt chúng là bỏ luôn bằng chứng cho phần thiết kế riêng của đồ án.

Mỗi ca nên là một thư mục con chứa: `case.yaml` (mục tiêu, nguồn dữ liệu, tiêu chí kiểm) + các file dữ liệu độc/lành mà ca đó cần dựng.

## `configs/` — bốn cấu hình (mục 13.7)

| Cấu hình | Là gì |
|---|---|
| **C0** | Trần — tắt hết, agent làm gì cũng được |
| **C1** | Chỉ hỏi, không có nhãn. **Đây là mức Claude Code / Cursor đang làm** |
| **C2** | Nhãn + hỏi |
| **C3** | Đầy đủ — nhãn + giấy phép có phạm vi và thời hạn |

Hai chênh lệch quan trọng nhất là **C1→C2** và **C2→C3**. Chênh lệch C2→C3 chỉ có nghĩa nếu **số giấy phép đã cấp mỗi việc ở C3 lớn hơn 0** — nếu bằng 0 thì C3 chỉ là C2 chạy chậm hơn.

## `simulated_user/` — sáu luật chốt trước (mục 13.5)

Vì cơ chế dựa vào việc hỏi người dùng, ASR phụ thuộc hoàn toàn vào cách "người dùng" trả lời. Nên:

- Bộ mô phỏng **chỉ thấy đúng những gì thẻ ở mục 12.5 hiện ra** — không có oracle biết đáp án.
- Sáu luật **P1-P6 viết trước khi chạy**, không sửa sau khi thấy kết quả. `K = 3`.
- Báo cáo **tách ba số**: số lần hỏi · ASR · khả năng làm việc — cộng **hai đường biên** (luôn đồng ý / luôn từ chối).

Hai trong sáu luật (**P4**, **P5**) tồn tại vì một lý do dễ bỏ sót: nếu bộ mô phỏng chỉ biết "đồng ý một lần" hoặc "từ chối" thì nó **không bao giờ cấp một giấy phép nào**, và chênh lệch C2→C3 sẽ bằng 0 vì bộ mô phỏng chứ không vì thiết kế.

## `runner/` và `results/`

`runner/` chứa khung chạy thí nghiệm: chạy N ca × M lần, ghi kết quả, tính trung bình ± độ lệch chuẩn.

Cấu hình cố định phải ghi vào mỗi lần chạy (mục 13.6): version string đầy đủ của model · `temperature=0` · **Gemini "prompt injection detection" TẮT** ở cấu hình chính · chế độ `a11y`/`vision` đã ghim theo nhóm ca · **lặp ≥ 5 lần** · commit hash của code.

`results/` chứa output. Kết quả có số liệu thật thì commit; file tạm thì không.
