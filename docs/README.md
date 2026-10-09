# Tài liệu BoxFox

Đây là điểm bắt đầu duy nhất cho tài liệu dự án. Các tài liệu mô tả **hướng thiết kế hoặc kế hoạch** không phải xác nhận rằng runtime đã triển khai và bảo vệ các cơ chế đó. Trạng thái đã xác minh, giới hạn và lộ trình nằm trong [kế hoạch sản phẩm](plan/agent-box-plan.md).

> **Vừa nhận việc?** Đọc [bàn giao hiện hành](../HANDOFF.md) trước; mục lục mọi bản bàn giao (kể cả bản lịch sử) nằm ở [docs/handoff/README.md](handoff/README.md).

## Chọn đường đọc

| Nếu cần… | Đọc đầu tiên | Rồi đến |
|---|---|---|
| Nắm sản phẩm, phạm vi và thứ tự triển khai | [Tóm tắt kế hoạch](plan/agent-box-plan-summary.md) | [Kế hoạch sản phẩm](plan/agent-box-plan.md) |
| Thiết kế bộ chạy nhiều agent | [Kiến trúc harness](architecture/agent-harness.md) | [Nghiên cứu harness](research/agent-harness/index.md), [mô hình bảo mật](architecture/security-model.md) |
| Kết nối và chọn mô hình AI an toàn | [Kiến trúc model router](architecture/model-router.md) | [Nghiên cứu model router](research/model-router/index.md), [mô hình bảo mật](architecture/security-model.md) |
| Hiểu hoặc kiểm chứng ranh giới an toàn | [Mô hình bảo mật và IFC](architecture/security-model.md) | [Sandbox](architecture/sandbox.md), [đánh giá](plan/agent-box-evaluation.md) |
| Đọc bằng chứng từ dự án tham chiếu | [Chỉ mục nghiên cứu kỹ thuật](research/README.md) | [Snapshot mã nguồn tham chiếu](../code-reference/README.md) |
| Làm tính năng Element Selector / DOM Inspector | [Kế hoạch v1](plan/element-selector-plan-v1.md) | [Kiến trúc](architecture/element-selector.md), [nghiên cứu cạnh tranh](research/element-selector-competitive-research.md) |

## 1. Sản phẩm, kiến trúc và quyết định

### 1.1 Kế hoạch và đánh giá

- [Kế hoạch sản phẩm BoxFox Agent Box](plan/agent-box-plan.md) — mục tiêu, trạng thái hiện tại đã xác minh, các quyết định sản phẩm, lộ trình và bảng chuyển nội dung từ kế hoạch cũ.
- [Cải tổ Plan mode — tiến độ và bàn giao](plan/plan-mode-reform-v1.md) — đặc tả đã chốt, checklist triển khai trên nhánh B, kiểm thử và phần còn dở.
- [Tóm tắt kế hoạch](plan/agent-box-plan-summary.md) — bản đọc nhanh của các quyết định và giới hạn quan trọng.
- [Đánh giá BoxFox Agent Box](plan/agent-box-evaluation.md) — câu hỏi nghiên cứu, cấu hình, benchmark, chỉ số an toàn/utility và cách tái lập đánh giá; đây là đặc tả đánh giá, không phải kết quả benchmark đã chạy.
- [Chế độ plan dưới mắt mô hình thật (2026-09-27)](plan/plan-mode-live-verification-2026-09-27.md) — số đo ba ca trên harness thật với `muse-spark-1.3-contributor-free`: xử lý yêu cầu mơ hồ, độ sâu tìm hiểu, chuyển sang design khi là việc UI, và vì sao chưa lượt nào có kết luận phản biện ghi sổ.

### 1.2 Harness, router và bảo mật

- [Kiến trúc harness đa agent](architecture/agent-harness.md) — vòng đời session/task/run/turn, prompt, tool, skill, agent con, event và artifact.
- [Kiến trúc model router](architecture/model-router.md) — giao thức chuẩn, alias, policy định tuyến, credential broker, fallback và audit.
- [Mô hình bảo mật và kiểm soát luồng thông tin (IFC)](architecture/security-model.md) — mô hình đe dọa, nhãn dữ liệu, approval/lease, kiểm tra lúc thực thi và giới hạn của các tuyên bố bảo mật.
- [Kiến trúc sandbox](architecture/sandbox.md) — desktop box, mạng, proxy, cổng và các ranh giới thực thi hiện có.
- [ADR-0001: các lựa chọn cô lập shell](architecture/decisions/0001-shell-isolation-options.md) — giữ ba phương án; thử worker ngắn hạn trước, chưa coi đây là quyết định triển khai cuối cùng.
- [ADR-0002: điều khiển desktop đồng thời](architecture/decisions/0002-concurrent-desktop-control.md) — quyết định được hoãn cùng tiêu chí trước khi bật.

> **Thứ bậc nguồn chuẩn:** mô hình bảo mật quy định dữ liệu/quyền; harness và router phải gọi cổng policy thay vì tự diễn giải quyền; sandbox thực thi ranh giới tiến trình, filesystem và mạng; ADR lưu lựa chọn chưa chốt. Kế hoạch liên kết các tài liệu này, không thay thế chúng.

### 1.3 Các kiến trúc và đặc tả tính năng khác

- [Element Selector / DOM Inspector](architecture/element-selector.md) — luồng, hợp đồng phản hồi, nhãn và fallback.
- [Chụp màn hình và quay video](architecture/screen-capture.md) — API computer-use của box.
- [Workspace Files](architecture/workspace-files.md) — API truy cập tệp phía box.
- [Thông báo email khi task hoàn thành](architecture/email-notification.md) và [đặc tả email](plan/task-completion-email-spec.md).
- [Design Canvas](architecture/design-canvas.md) và [tối ưu hiệu năng render](architecture/high-performance-rendering.md).

### 1.4 Ứng dụng desktop (Windows)

- [Cài BoxFox Desktop (Alpha) — bản nhanh](plan/desktop-alpha-quickstart.md) (tiếng Việt) và
  [quick start, English](plan/desktop-alpha-quickstart.en.md) — dành cho người dùng cuối: kiểm SHA-256,
  4 bước cài, chế độ `host`/`docker`, dữ liệu ở đâu, gỡ cài đặt.
- [Cài đặt, chế độ chạy và checklist nghiệm thu 13 bước](plan/desktop-alpha-install.md) (tiếng Việt) và
  [install, run modes and acceptance checklist, English](plan/desktop-alpha-install.en.md) — bản đầy đủ,
  kèm cảnh báo chế độ host.
- Bộ cài `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (Windows x64, chưa ký số) dựng từ nhánh hiện hành; cách
  dựng lại và các điểm cần biết khi cross-build trên Linux nằm ở [`desktop/README.md`](../desktop/README.md)
  và mục 3 của [`HANDOFF.md`](../HANDOFF.md).

## 2. Nghiên cứu và bằng chứng

[Nghiên cứu kỹ thuật](research/README.md) là chỉ mục cho mọi nguồn và mức bằng chứng:

- [Thuật ngữ chung](research/terminology.md) — định nghĩa Việt–Anh và chữ viết tắt.
- [Agent harness](research/agent-harness/index.md) — Hermes Agent, OpenCode và các nền tảng chỉ có tài liệu công khai.
- [Model router](research/model-router/index.md) — 9Router, OmniRoute, Claude Code Router và LiteLLM.
- [Research brief](research/research-brief.md) — bối cảnh, giả thuyết và bằng chứng ban đầu của hướng Agent Box.
- [Phụ lục computer use / GUI agent](research/research-addendum-computeruse.md) — bằng chứng bổ sung cho tác vụ qua màn hình.
- [Nghiên cứu cạnh tranh Element Selector](research/element-selector-competitive-research.md) — đầu vào cho nhánh tính năng DOM Inspector.

Mã nguồn mở được viện dẫn có [snapshot tham chiếu](../code-reference/README.md), manifest, checksum và giấy phép theo từng commit. Snapshot không phải dependency hay mã runtime. Nền tảng đóng được ghi rõ `public-docs-only`; không suy đoán nội bộ từ tài liệu công khai.

## 3. Thiết kế Element Selector / DOM Inspector

- [Kế hoạch v1 đã phê duyệt](plan/element-selector-plan-v1.md) — nguồn ưu tiên nếu khác với đặc tả cũ.
- [Tóm tắt kế hoạch v1](plan/element-selector-plan-v1-summary.md) — bản đọc nhanh.
- [Đặc tả gốc](plan/element-selector-spec.md) — chỉ dùng cho phần không bị kế hoạch v1 ghi đè.
- [Mockup đã duyệt](design/element-selector/) — HTML trạng thái giao diện và `design-plan.json`.

## 4. Kiểm thử

[Test cấp repository](../test/README.md) mô tả test LLM, cầu nối chat và lý do một số test nằm cạnh mã nguồn. Với hệ thống Agent Box, dùng thêm [đặc tả đánh giá](plan/agent-box-evaluation.md) để đánh giá an toàn, khả năng hoàn thành tác vụ và chi phí tương tác; không suy ra kết quả thực nghiệm chỉ từ sự tồn tại của tài liệu.

## Quy ước đọc

1. Đọc tài liệu theo liên kết từ chỉ mục này; không lấy một mock UI, prompt hay tài liệu tham chiếu làm bằng chứng enforcement.
2. Thuật ngữ chuyên ngành được định nghĩa ở lần đầu trong tài liệu chuyên đề; tra [thuật ngữ nghiên cứu](research/terminology.md) khi cần đối chiếu.
3. Khi có mâu thuẫn: đặc tả bảo mật và ADR được liên kết có hiệu lực cho phạm vi chúng quy định; kế hoạch v1 thắng đặc tả Element Selector gốc tại các điểm được nêu trong §5.6; trạng thái mã hiện tại thắng mô tả hay giả định cũ.
4. Mọi thay đổi thiết kế cần cập nhật liên kết ngược vào chỉ mục này hoặc chỉ mục nghiên cứu để không tạo tài liệu mồ côi.
