# H5 — Context và skills

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`context_surface.py`); nghiệm thu mức vòng chạy B1–B5 nằm trong **29/29 PASS** trên `c836822`; `b37dafb` thêm fallback đọc catalog khi kho đăng ký còn trống.
- **Mục tiêu:** `ContextBundle` giữ intent/consent/pending task/conflict/unknown outcome qua compaction; `SkillSpec` readiness/version/epoch + capability mapping.
- **Phạm vi:** `context_bundle.py` (79 ca), `skill_spec.py` (114 ca), `context_surface.py` (56 ca trên head); nối runtime (nén/`/compact`, `mode_skill`, `read_skill`, `handoff_to`); sửa lỗi vòng review H5.1–H5.3.
- **Ngoài phạm vi:** nhập bộ skill tham khảo bên ngoài (cấm); dùng context ref để thay approval/quyền.
- **Phụ thuộc:** H1, H3; H4 cho handoff job.
- **Nghiệm thu (runbook §II.3):** sau compaction còn đúng intent, consent, pending task, conflict, unknown outcome; skill reload đúng epoch; tool thiếu trả blocked, không chế tunnel/installer; không import bộ skill tham khảo.
- **Nguồn:** `docs/plan/reform-status.md` H5–H5.4; probe P3 `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`; nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`.
