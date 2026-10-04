# H6 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_usage_ledger.py`: 50 hàm / **55 ca** (số ca theo bảng trạng thái/PR body).
- Probe P4 trong `probes_962cd84.json`: **7/7** —
  - giá lạ là `None`, không bao giờ 0;
  - retry/child/Research không double-count;
  - settle→release cho con bị huỷ;
  - thiếu trần caller ⇒ từ chối chi mới;
  - usage đến muộn vẫn là nợ `unsettled`.
- Bảng mới (additive): `harness_usage` (`usage_ledger.py:458`), `harness_allocations` (dòng 469).
- Lỗi đã sửa: H6.1 `observed_at` nằm trong hash idempotency của `record` → retry y hệt bị `USAGE_CALL_CONFLICT` oan; H6.2 `settle`/`release` của cha bỏ qua hold của con → vượt trần gốc; H6.3 idempotency chỉ nhớ lần cuối → A→B→A áp dụng đúp; H6.4 JSON hỏng rò `JSONDecodeError` → `USAGE_RECORD_CORRUPT`; H6.5 consent của con lỏng hơn luật tiền tệ của cha.

## Chưa kiểm
- Chưa nối runtime: "caller constraints và Stop có hiệu lực" trong vòng chạy thật — **chưa kiểm**.
- Calibration sống (giá/độ trễ/hiệu quả thật) — **chưa chạy**, chờ consent tài chính riêng (H10.1); không tự chọn số mặc định.
- Chưa có số đo hiệu năng của sổ (khối lượng ghi) ngoài unit/probe.
