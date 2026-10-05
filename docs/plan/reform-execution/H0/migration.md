# H0 — Migration / rollback

- Không có thay đổi schema, dữ liệu hay runtime ở checkpoint này: chỉ đọc artifact W10.F và ghim mốc so sánh.
- Không migrate, không chạy lại, không sửa fixture/oracle mà suite cũ đang dùng; W10.F giữ nguyên trên `6adbe78`.
- Rollback: không áp dụng (không có gì để hoàn tác).
- Kill switch: không áp dụng.
- Nếu cần chạy lại W10.F sau này: cần tài nguyên/consent riêng, và kết quả mới không được trộn vào bộ đã ghim.
