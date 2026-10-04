# H7 — Research ownership

- **Trạng thái:** đạt mức thư viện + probe; **chưa nối runtime** nên envelope giữa main và Research chưa chạy trong phiên thật.
- **Mục tiêu:** controller principal + gateway có version; migrate read view/history; main không sửa internals, không điều khiển worker nội bộ.
- **Phạm vi:** `research_owner.py` (52 ca); sửa lỗi vòng review H7.1–H7.2.
- **Ngoài phạm vi:** chạy Research sống (thuộc calibration/H10.1); nối `research_runtime` (chưa làm).
- **Phụ thuộc:** H2–H6.
- **Nghiệm thu (runbook §II.3):** main submit/get/control/result trong envelope; Research tự chọn phương pháp; publication/review bind đúng version; refresh/revision không sửa kết quả cũ; nguồn bị chặn còn hiện rõ.
- **Nguồn:** `docs/plan/reform-status.md` H7–H7.2; probe P5 `probes_962cd84.json`.
