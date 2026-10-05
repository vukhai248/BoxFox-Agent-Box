# H1 — Hợp đồng và tương thích ngược

- **Trạng thái:** xong; module `backend/src/agentbox/agent_core/orchestration_contracts.py` + 77 ca test (số ca thu thập).
- **Mục tiêu:** định schema task/job/artifact/context/permission/budget/Research, quy ước ID/revision/owner; migration additive; đọc được record legacy.
- **Phạm vi:**
  - file module mới + `backend/tests/unit/test_orchestration_contracts.py`;
  - sửa lỗi vòng review H1.1–H1.3 (commit `ab26776`, `3975ab6`).
- **Ngoài phạm vi:** nối runtime (thuộc H2/H3); migration bảng cũ; đổi approval/verdict lịch sử.
- **Phụ thuộc:** H0.
- **Nghiệm thu (runbook §II.3):** fixtures đọc dữ liệu cũ không tự tạo grant/verdict; alias trùng, ID reuse khác payload, stale revision, schema unsupported bị từ chối; hash/approval lịch sử không đổi.
- **Nguồn:** `docs/plan/reform-status.md` dòng H1–H1.3; `/code/.plans/reform-h1-contract-seams.md`; PR #3.
