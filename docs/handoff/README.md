# Handoff — điểm vào duy nhất

Mọi bản bàn giao của dự án nằm trong thư mục này (hoặc trong `archive/`). Nếu bạn là agent vừa nhận
việc: **đọc [`../../HANDOFF.md`](../../HANDOFF.md) ở gốc repo trước** — đó là bản hiện hành. Tệp bạn
đang đọc chỉ là mục lục.

## Bản hiện hành

| Tài liệu | Nội dung |
| --- | --- |
| [`../../HANDOFF.md`](../../HANDOFF.md) | **Đọc trước, đặc biệt mục 0 cập nhật 2026-10-10:** checkpoint local đưa lên main; reasoning/feedback vẫn lỗi, sub đứng sau patch, source/commit, phép kiểm và việc cloud cần tái lập. Mục 1–9 giữ bối cảnh cloud 2026-10-09 về long task và F01–F17. |

## Bản lịch sử (còn giá trị tra cứu)

| Tài liệu | Nội dung | Trạng thái |
| --- | --- | --- |
| [`desktop-host-mode-handoff.md`](desktop-host-mode-handoff.md) | BoxFox Desktop alpha: hai chế độ chạy (máy người dùng / box Docker) + CUA; bảng tiến độ và việc còn lại | nền của nhánh hiện tại |
| [`router-settings.md`](router-settings.md) | Router Settings gốc: trạng thái, việc còn lại; cũng là **khuôn** viết handoff của dự án | mẫu định dạng |
| [`v29-keyring-handoff.md`](v29-keyring-handoff.md) | Vòng 29: key ring của router (một connection nhiều khoá, tự chuyển khi hết hạn mức) | xong |
| [`research-verification.md`](research-verification.md) | Kiểm nghiệm research vòng 29, đợt 4 (phần offline, 0 đồng) | xong |
| [`research-v2-live-addendum-2026-09-25.md`](research-v2-live-addendum-2026-09-25.md) | Phụ lục research v2 (2026-09-25) | xong |
| [`h-reform-05_10/evidence/`](h-reform-05_10/evidence) | Script bằng chứng của đợt cải tổ H3/H4/H8/H10 (drill rollback, mock price, driver E2E) | xong |
| [`archive/box-agent-handoff-2026-09.md`](archive/box-agent-handoff-2026-09.md) | Bản bàn giao gốc ở gốc repo: tổng quan hệ thống box Docker, 7 thư mục dot, Plan Browser, CUA | lịch sử |
| [`archive/handoff-03_10.md`](archive/handoff-03_10.md) | Bàn giao 03/10: Work Graph W6–W10 | lịch sử |
| [`archive/CLOUD-AGENT-HANDOFF-03_10.md`](archive/CLOUD-AGENT-HANDOFF-03_10.md) | Bàn giao ngắn cho cloud agent 03/10: Work Graph | lịch sử |

## Bàn giao nằm trong thư mục kế hoạch của chúng

Các bản dưới đây là **bàn giao theo checkpoint**, sống cùng kế hoạch của chúng; không di chuyển để khỏi
phá cấu trúc kế hoạch. Chúng không phải điểm bắt đầu:

- `docs/plan/reform-execution/HANDOFF.md` và `docs/plan/reform-execution/H0..H11/handoff.md` — bàn giao
  từng checkpoint của đợt cải tổ (H12, công tắc tổng, rollback).
- `docs/plan/v29/v29-research-handoff-outline.md` — đề cương bàn giao research vòng 29.

## Quy ước từ nay

1. Bản hiện hành luôn là `HANDOFF.md` ở gốc repo. Viết lại nó khi có đợt mới; **không** tạo thêm tệp
   `handoff-*.md` mới ở gốc `docs/` hay gốc repo.
2. Bản cũ đẩy xuống `docs/handoff/archive/` với tên `handoff-<ngày>-<chủ đề>.md` (ngày dạng `NN_MM`).
3. Mọi tài liệu bàn giao phải được thêm một dòng vào bảng ở tệp này.
4. Khuôn viết: theo [`router-settings.md`](router-settings.md) — mở đầu `# Handoff — <tiêu đề>`, danh
   sách `- Branch:` / `- Pull request:`, rồi các mục `## Trạng thái`, `## Đã hoàn thành`,
   `## Kiểm tra đã đạt tại commit <sha>`, `## Việc còn lại`.
