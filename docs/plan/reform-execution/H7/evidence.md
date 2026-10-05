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

## Nối runtime (`802f51f`)
- `research_gateway.py` (48 test): submit/get/result/control/publish với principal `research-lead` riêng; main chỉ đọc; `guard_request` chặn model khi intake chưa admit; `apply_profile` ẩn/gate công cụ theo công tắc (`BOXFOX_RESEARCH_GATEWAY` mặc định off); các cửa control gọi `ownership.authorize(...)`.
- Nghiệm thu vòng chạy D1–D4 nằm trong **29/29 PASS** trên `c836822` — `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json` (gồm "lead là principal tách biệt").
- #6536: gateway giữ trong mã, mặc định off; bản này main tự spawn research sub-agent — không mô tả là đã gỡ hay đã bật.

## Chưa kiểm
- Chưa chạy Research sống (hoãn #6531); chưa kiểm migrate read view/history trên dữ liệu thật ngoài envelope.
- Khi mở rộng thêm điểm vào phải giữ `authorize(...)` (H7.2).
