# H5 — Bàn giao

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`context_surface.py`: nén/`/compact`, `mode_skill`, `read_skill`, `handoff_to`); B1–B5/29 đạt trên `c836822`; `b37dafb` thêm fallback đọc catalog khi kho đăng ký trống.
- **Quyết định:**
  - pin skill theo `(skill_id, attempt_id)` là duy nhất; epoch pin là nguồn sự thật (H5.1);
  - record có cột phiên bản + decode lỗi trả mã `SKILL_RECORD_CORRUPT` (H5.2/H5.3);
  - không import/nhúng bộ skill tham khảo bên ngoài;
  - ref là dữ liệu: không đọc chéo phiên, không thay approval/quyền (H5.4).
- **Blocker:** không.
- **Việc tiếp:** chạy phiên thật cần consent (H10.1); giữ hợp đồng epoch đã ghim.
- **Bật dần:** công tắc của checkpoint này nằm trong nhóm bật dần H3–H8 — thứ tự, khuôn kiểm 5 bước và rollback ở `docs/plan/reform-execution/HANDOFF.md` §6.
- **Tham chiếu:** `probes_962cd84.json` (P3); nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`; `docs/plan/reform-status.md` H5–H5.4.
