# H2 — Bàn giao

- **Trạng thái:** verified. Kernel là một cửa admission duy nhất; kho task bền vững đã có; dispatch runtime đã nối.
- **Quyết định:**
  - enforcement ở tầng **application** (không tuyên bố OS/network isolation) — đúng thiết kế #6492 giai đoạn harness;
  - child không bao giờ rộng hơn parent; thiếu canonical → fail closed (H2.1, H2.6);
  - kill switch mặc định off, giữ nguyên đường legacy khi tắt.
- **Blocker:** không.
- **Việc tiếp:** H3 dựng bề mặt task trên kho này và nối runtime; giữ nguyên hợp đồng H2.
- **Tham chiếu:** parity `parity_checks_3975ab6.json`; `docs/plan/reform-status.md` H2–H2.6; commit `ab26776`, `3975ab6`, `2c7ec66`.
