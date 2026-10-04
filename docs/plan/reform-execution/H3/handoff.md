# H3 — Bàn giao

- **Trạng thái:** verified trên `962cd84` (E2E 9/9, probe 71/71, scoped 716 passed); bản kiểm thử độc lập kết luận PASSED.
- **Quyết định:**
  - công tắc `BOXFOX_TASK_SURFACE` mặc định off; bật chỉ khi có hợp đồng task;
  - gọi lại `delegate` cùng `invocationId` khi attempt đã đóng → mở attempt mới qua admission (docstring ghim ngữ nghĩa; E3b/E3c);
  - F4 sửa bằng cờ `owner_cancels` đặt trước khi dừng + `close_owner_cancelled_child`; F6 đóng hàng phiên con ngay trong nhánh bind hỏng;
  - biên nhận huỷ là dữ liệu sự thật của cha; lỗi đường huỷ vẫn báo biên nhận đã ghi (H3.3/H3.5).
- **Blocker:** không chặn; F5 (`attemptSeq` theo phiên) chờ chủ nhà quyết; mục E3 trong `/code/.plans/reform-h3-seams.md` nên được đồng bộ câu chữ.
- **Việc tiếp:** H4 (job nền) — H3 là bề mặt được H4/H8 dùng lại; giữ hợp đồng công cụ nguyên vẹn.
- **Bật dần:** công tắc của checkpoint này nằm trong nhóm bật dần H3–H8 — thứ tự, khuôn kiểm 5 bước và rollback ở `docs/plan/reform-execution/HANDOFF.md` §6.
- **Tham chiếu:** `/code/.generated_artifacts/h3h8/e2e/summary.json`, `E5.json`, `probes_962cd84.json`, `unit/scoped_suites_962cd84.log`; `docs/plan/reform-status.md` H3–H3.11.
