# H8 — Main thích ứng

- **Trạng thái:** đạt mức thư viện + probe; **chưa nối composer/runtime** nên "một scheduler cho mỗi admission" chưa kiểm trong phiên thật.
- **Mục tiêu:** composer theo intent/role/tool hiệu lực/skill/hợp đồng; bỏ pipeline bắt buộc ở mode mới; giữ legacy adapter theo run pin.
- **Phạm vi:** `adaptive_main.py` (87 ca); sửa lỗi vòng review H8.1–H8.5.
- **Ngoài phạm vi:** nối composer runtime (chưa làm); đổi luật minimum checks của kernel.
- **Phụ thuộc:** H2–H7.
- **Nghiệm thu (runbook §II.3):** main xử lý việc nhỏ trực tiếp, giao specialist khi có lợi; không bỏ minimum checks; scope/intent change cần receipt đúng; legacy/adaptive không chạy hai scheduler cho cùng admission.
- **Nguồn:** `docs/plan/reform-status.md` H8–H8.5; probe P6 `probes_962cd84.json`.
