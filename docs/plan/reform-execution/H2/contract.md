# H2 — Một cửa admission + kho task bền vững

- **Trạng thái:** xong; `execution_kernel.py` (34 ca) + `task_service.py` (60 ca); `runtime.dispatch` đã đi qua kernel guard.
- **Mục tiêu:** tách luật backend khỏi prompt; tái dùng `work_scope`, `work_policy`, `work_checks`, grants và child lifecycle; chuẩn hóa effective permission + capability report; kho task bền vững (bảng additive).
- **Phạm vi:** 2 module mới + test; nối `runtime.dispatch` qua guard; sửa lỗi vòng review H2.1–H2.6.
- **Ngoài phạm vi:** task surface (H3); job nền (H4); native sandbox (không thuộc gói harness này).
- **Phụ thuộc:** H1.
- **Nghiệm thu (runbook §II.3):** analysis/plan/design không sửa source; child không rộng hơn parent; checks đúng input/snapshot; recheck sau await slot; không tuyên bố native isolation; kill switch giữ guard.
- **Nguồn:** `docs/plan/reform-status.md` H2–H2.6; `/var/tmp/boxfox-testing/results/parity_checks_3975ab6.json`; `/code/.plans/reform-h2-admission-seams.md`.
