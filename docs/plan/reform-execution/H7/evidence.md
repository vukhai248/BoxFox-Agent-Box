# H7 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_research_owner.py`: **52 ca** (52 hàm).
- Probe P5 trong `probes_962cd84.json`: **8/8** —
  - intent do main viết **không** trở thành canonical;
  - revision cũ → `RESEARCH_REVISION_CONFLICT` không kèm receipt;
  - `control_view` được che cho non-owner;
  - `validate_report` từ chối kết luận do main viết và báo cáo thiếu bằng chứng.
- Bảng mới (additive): `harness_research_ownership` (dòng 88), `harness_research_handoffs` (94), `harness_research_controls` (101), `harness_research_invocations` (107).
- Lỗi đã sửa: H7.1 đua replay trong `claim` → kiểm cache invocation TRONG giao dịch ghi (trả replay thay vì conflict); H7.2 thiếu ghi chú nối dây cho các điểm vào chưa xác thực (`assign`, `handoff`, `release`, `record_intent`, `get`, `validate_report`) → thêm mục "GHI CHÚ NỐI DÂY" trong docstring, yêu cầu wiring gọi `authorize(...)`.

## Chưa kiểm
- Chưa nối runtime: chưa có phiên thật main↔Research để kiểm envelope; **chưa kiểm** migrate read view/history trên dữ liệu thật.
- Chưa chạy Research sống (ngoài phạm vi, chờ consent + wiring).
- Các điểm vào ghi chú H7.2 mới là hợp đồng ở docstring; chưa có mã nối thật — khi nối phải gọi `authorize(...)`.
