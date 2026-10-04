# H5 — Context và skills

- **Trạng thái:** đạt mức thư viện + probe; **chưa nối runtime** nên điều kiện recall sau compaction và reload trong phiên thật chưa kiểm.
- **Mục tiêu:** `ContextBundle` giữ intent/consent/pending task/conflict/unknown outcome qua compaction; `SkillSpec` readiness/version/epoch + capability mapping.
- **Phạm vi:** `context_bundle.py` (79 ca), `skill_spec.py` (114 ca); sửa lỗi vòng review H5.1–H5.3.
- **Ngoài phạm vi:** nối loader/composer runtime (chưa làm); nhập bộ skill tham khảo bên ngoài (cấm).
- **Phụ thuộc:** H1, H3; H4 cho handoff job.
- **Nghiệm thu (runbook §II.3):** sau compaction còn đúng intent, consent, pending task, conflict, unknown outcome; skill reload đúng epoch; tool thiếu trả blocked, không chế tunnel/installer; không import bộ skill tham khảo.
- **Nguồn:** `docs/plan/reform-status.md` H5–H5.3; probe P3 `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`.
