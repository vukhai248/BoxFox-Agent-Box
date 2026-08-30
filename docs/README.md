# Tài liệu dự án

| Đường dẫn | Nội dung |
|---|---|
| [`plan/agent-box-plan.md`](plan/agent-box-plan.md) | **Bản kế hoạch đầy đủ, Phần 0 → XVI.** Đây là tài liệu duy nhất cần đọc để hiểu kiến trúc, mô hình bảo mật, benchmark và lộ trình |
| [`plan/agent-box-plan-summary.md`](plan/agent-box-plan-summary.md) | Bản tóm tắt — đọc trước nếu chỉ cần nắm quyết định lớn và các con số nhân lực |
| [`research/research-brief.md`](research/research-brief.md) | Bằng chứng thị trường và các ngách đã loại, kèm nguồn trích dẫn được |
| [`research/research-addendum-computeruse.md`](research/research-addendum-computeruse.md) | Phụ lục nghiên cứu về computer use và GUI agent |
| [`architecture/sandbox.md`](architecture/sandbox.md) | **Kiến trúc máy ảo**: mọi tiến trình, cổng, proxy, lớp bảo vệ, và sơ đồ kết nối từ giao diện web vào box |
| [`architecture/email-notification.md`](architecture/email-notification.md) | **Gửi mail thật khi task xong**: kênh `notify_owner` do Controller nắm, đi qua Policy Engine, provider Resend/SMTP, và lộ trình biến mock `completionEmail` thành live |

## Element Selector / DOM Inspector

| Đường dẫn | Nội dung |
|---|---|
| [`plan/element-selector-plan-v1.md`](plan/element-selector-plan-v1.md) | **Kế hoạch v1 đã phê duyệt** — chia 3 phase, mô hình nhãn tin cậy, bộ **11 mã `reason`**, hợp đồng `POST /__box/inspect-element`, bảo mật §10, và §5.6 liệt kê 10 điểm ghi đè đặc tả gốc |
| [`plan/element-selector-plan-v1-summary.md`](plan/element-selector-plan-v1-summary.md) | Bản rút gọn — đọc trước nếu chỉ cần nắm quyết định lớn |
| [`plan/element-selector-spec.md`](plan/element-selector-spec.md) | Đặc tả gốc. Chỗ nào lệch với kế hoạch v1 thì **kế hoạch v1 thắng** (§5.6) |
| [`research/element-selector-competitive-research.md`](research/element-selector-competitive-research.md) | Vorflux / Devin / Cursor / Lovable làm tính năng chọn phần tử thế nào, và ta chọn khác ở đâu |
| [`design/element-selector/`](design/element-selector/) | 6 mockup HTML đã phê duyệt (toolbar, drawer DOM đầy đủ/suy biến, drawer desktop, tải/lỗi, khung sáng + chip) kèm `design-plan.json` |

## Kiểm thử

| Đường dẫn | Nội dung |
|---|---|
| [`../test/README.md`](../test/README.md) | **Bộ test cấp repo**: bộ test LLM (LLM có nắm đúng quy trình và chống được tiêm nhiễm không) và cầu nối chat để thử giao diện với model thật. Cũng giải thích vì sao test Vitest và test unittest của box vẫn nằm cạnh mã nguồn |

## Quy ước đọc bản kế hoạch

- Mọi phần kỹ thuật (V-XIII) kết thúc bằng đúng hai khối: **▸ Phạm vi đồ án (3 tháng)** và **▸ Cần gì để thành sản phẩm**.
- **Phần 0 là từ điển thuật ngữ.** Đọc trước nếu chưa quen từ vựng bảo mật.
- Các con số thời gian ở Phần XIV là **tuần-người**, quy ước 1 tuần-người = 5 ngày làm việc của một người.

## Ba điểm phải quyết trước tuần 0 (mục 16.3)

1. Bao nhiêu người thực hiện — quyết định trực tiếp phạm vi. Khuyến nghị **3 người**.
2. Giảng viên hướng dẫn có bắt buộc thành phần ML tự huấn luyện hay không.
3. **Tên dự án.** Repo hiện tên `Cloud-Anget-P`; "Anget" là lỗi chính tả của "Agent", và "Cloud" đi ngược thông điệp local-first của sản phẩm.
