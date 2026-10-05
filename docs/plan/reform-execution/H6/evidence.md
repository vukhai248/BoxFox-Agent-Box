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

## Nối runtime (`802f51f` + follow-up)
- `usage_surface.py` (22 test): một seam `complete_model` cho mọi request; reserve→settle→release quanh request; hết trần chặn TRƯỚC khi gọi model; giá đọc từ snapshot router (`ping`/`documented`), giá lạ giữ `None`.
- `0419ffe`: `/compact` của người dùng đi qua `complete_model(purpose='summary')` (không gọi thẳng client).
- Nghiệm thu vòng chạy C1–C5 nằm trong **29/29 PASS** trên `c836822` — `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json` (gồm "giá lạ giữ snapshot `None`").
- Bằng chứng chặn chi phí #6526: demo model miễn phí + giá giả — `/code/.generated_artifacts/h4h8/free_model_mock_price_demo.py`.

## Chưa kiểm
- Calibration sống (giá/độ trễ/hiệu quả thật) — **hoãn #6531**, chờ consent tài chính riêng; không tự chọn số mặc định.
- Route miễn phí chỉ chụp giá lúc admission (H6.8); `harnessAllocationId` chưa có writer trong `backend/src` (H6.9).
- Chưa có số đo hiệu năng của sổ (khối lượng ghi) ngoài unit/acceptance.
