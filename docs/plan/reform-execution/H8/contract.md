# H8 — Main thích ứng

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`adaptive_surface.py` + cổng `recovery_policy`); nghiệm thu mức vòng chạy E1–E4 nằm trong **29/29 PASS** trên `c836822`; `c6c88bb` thêm writer vận hành (`execution_kernel.set_policy/status/root_session` + route `GET|PUT /api/agent/sessions/{sid}/execution-policy`).
- **Mục tiêu:** composer theo intent/role/tool hiệu lực/skill/hợp đồng; bỏ pipeline bắt buộc ở mode mới; giữ legacy adapter theo run pin.
- **Phạm vi:** `adaptive_main.py` (87 ca), `adaptive_surface.py` (13 ca); nối runtime (decision/loop/evidence bền, cổng retry); sửa lỗi vòng review H8.1–H8.7.
- **Ngoài phạm vi:** đổi luật minimum checks của kernel; bật `BOXFOX_ADAPTIVE_HARNESS` mặc định.
- **Phụ thuộc:** H2–H7.
- **Nghiệm thu (runbook §II.3):** main xử lý việc nhỏ trực tiếp, giao specialist khi có lợi; không bỏ minimum checks; scope/intent change cần receipt đúng; legacy/adaptive không chạy hai scheduler cho cùng admission.
- **Nguồn:** `docs/plan/reform-status.md` H8–H8.7; probe P6 `probes_962cd84.json`; nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`.
