# H8 — Bàn giao

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`adaptive_surface.py` + cổng `recovery_policy`); E1–E4/29 đạt trên `c836822`; `c6c88bb` thêm writer vận hành `set_policy`/`status` + route `GET|PUT /api/agent/sessions/{sid}/execution-policy` (409/400).
- **Quyết định:**
  - mọi quyết định adaptive phải kèm `reason` + `evidenceRefs` (P6);
  - stop/revoke luôn thắng; cùng chữ ký lỗi + bằng chứng không đổi → chặn (H8.3);
  - không phát minh trần step/wall; trần chỉ đến từ policy/consent (H8.1/H8.5);
  - bật `adaptive` đòi cả `BOXFOX_ADAPTIVE_HARNESS` + `BOXFOX_USAGE_LEDGER`; chỉ vận hành viên ghi được policy, model không có tool ghi.
- **Blocker:** không; chạy thật thuộc calibration (hoãn #6531).
- **Việc tiếp:** khi mở consent, đo hiệu quả trong calibration; giữ P6 ở mức runtime.
- **Tham chiếu:** `probes_962cd84.json` (P6); nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`; `docs/plan/reform-status.md` H8–H8.7.
