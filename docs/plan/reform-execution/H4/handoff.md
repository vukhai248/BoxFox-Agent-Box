# H4 — Bàn giao

- **Trạng thái:** partial — thư viện + probe đạt; chưa nối runtime nên điều kiện vòng chạy chưa kiểm.
- **Quyết định:**
  - job có owner (turn hoặc controller); job của turn chết theo turn, job controller sống qua nhiều lượt;
  - mọi đánh thức đi qua outbox + cursor có sàn theo `(consumer, job)` (H4.1);
  - `reconcile` không spawn thay thế — chỉ đối chiếu trạng thái.
- **Blocker:** không; giới hạn là phạm vi (chưa nối runtime).
- **Việc tiếp:** khi có checkpoint wiring, chạy lại P2 ở mức runtime và bổ sung E2E nhiều lượt; trước đó không tuyên bố đạt mức vòng chạy.
- **Tham chiếu:** `probes_962cd84.json` (P2); `docs/plan/reform-status.md` H4–H4.3.
