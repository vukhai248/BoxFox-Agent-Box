# H9 — Migration / rollback

- Không thay đổi schema runtime; chỉ thêm file mới dưới `scripts/eval/` + test.
- Tương thích W10 cũ: chỉ đọc (`read_legacy_receipt`); không sửa artifact `/var/tmp/w10f-seq` hay script benchmark cũ.
- Rollback: gỡ `suite_v2.py`, `suite-v2.json`, `test_suite_v2.py` — không mất dữ liệu.
- Kill switch: không áp dụng (công cụ offline, chưa nối runtime).
- Tiền tệ: `financial_consent_ref` để `null`; live pilot chỉ chạy khi có consent riêng (H10.1). Không tiêu đồng nào ở checkpoint này.
