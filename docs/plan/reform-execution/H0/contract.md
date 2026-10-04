# H0 — Chốt baseline trước reform

- **Trạng thái:** đạt mục tiêu chốt baseline; độ phủ đo dừng ở 31/34 cell theo lệnh chủ nhà.
- **Mục tiêu:** đóng băng harness cũ (W10.F) trước mọi sửa runtime; pin code, fixture, oracle, model/route và tài nguyên; đối chiếu code đích với `346da06`.
- **Phạm vi:**
  - đọc artifact W10.F tại `/var/tmp/w10f-seq/` (freeze, plan, bundle, DB, cell state);
  - kiểm parity `6adbe78` ↔ `346da06`;
  - ghi Test Report W8.A4.5.N và cập nhật `docs/plan/reform-status.md`.
- **Ngoài phạm vi:** chạy thêm cell; gọi model; sửa runtime/test/script/oracle; dùng baseline làm kết quả reform.
- **Phụ thuộc:** plan 1257 được duyệt (Plan panel, 2026-10-03); W10.F dừng trước khi sửa runtime.
- **Nghiệm thu (runbook §II.3):**
  - giữ 34/34 cell gồm mọi failure — **không đạt đủ**: giữ 31 completed + 1 ownerInterrupted + 2 notRun (dừng theo lệnh chủ nhà);
  - phân loại product/provider/measurement/unknown — có trong báo cáo phát hành;
  - ghi code đích và cơ chế thiếu/khác baseline — có (parity `git diff`);
  - không gọi baseline là reform result — tuân thủ trong toàn bộ tài liệu này.
- **Nguồn:** `/code/.plans/v1-boxfox-harness-reform.md` §17; `/code/.plans/reform-execution-runbook.md` §II.3–§II.5; `docs/plan/reform-status.md` dòng H0.
