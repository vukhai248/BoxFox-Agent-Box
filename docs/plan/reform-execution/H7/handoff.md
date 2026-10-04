# H7 — Bàn giao

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`research_gateway.py`, principal `research-lead` riêng); D1–D4/29 đạt trên `c836822`; theo #6536 gateway giữ trong mã, mặc định off.
- **Quyết định:**
  - Research là hệ chuyên gia độc lập: intent của main là **đầu vào**, không bao giờ canonical (H7.1/P5);
  - publication/review bind theo version; refresh/revision không sửa kết quả cũ;
  - các điểm vào chưa xác thực phải gọi `authorize(...)` (H7.2); `guard_request` chặn model khi intake chưa admit (H7.3).
- **Blocker:** không; Research sống thuộc calibration (hoãn #6531).
- **Việc tiếp:** khi mở consent, thêm E2E main↔Research qua envelope và migrate read view trên dữ liệu thật.
- **Tham chiếu:** `probes_962cd84.json` (P5); nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`; `docs/plan/reform-status.md` H7–H7.3.
