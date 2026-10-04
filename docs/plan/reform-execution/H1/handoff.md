# H1 — Bàn giao

- **Trạng thái:** verified. Module + test đóng trên `962cd84`; không nối runtime.
- **Quyết định:**
  - revision/epoch là số nguyên ≥ 1, không coerce `bool`/chuỗi/float (H1.2);
  - kiểm cột DB cũ theo danh sách cột bắt buộc, không chỉ `schema_version` (H1.3);
  - text trường hợp đồng có trần độ dài, vượt → fail closed (H1.1).
- **Blocker:** không.
- **Việc tiếp:** H2 dùng hợp đồng này làm đầu vào cho kernel admission; khi H2/H3 nối runtime, gọi lại legacy read trên DB thật lần nữa.
- **Tham chiếu:** PR #3; commit `ab26776`, `3975ab6`; `docs/plan/reform-status.md` H1–H1.3.
