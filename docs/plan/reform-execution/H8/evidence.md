# H8 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_adaptive_main.py`: **87 ca** (87 hàm).
- Probe P6 trong `probes_962cd84.json`: **14/14** —
  - stop/revoke luôn thắng (không mở nhánh mới);
  - cùng chữ ký lỗi và bằng chứng không đổi → chặn;
  - không phát minh trần step/wall;
  - mọi quyết định kèm `reason` + `evidenceRefs`.
- Lỗi đã sửa: H8.1 `_clamp_level` coi trần policy là mức duy nhất → clamp theo các mức ≤ trần, ghim ladder snap-up; H8.2 `intentChange`/`scopeChange` kiểu bool/chuỗi nổ `AttributeError` → fail closed, đòi approval; H8.3 `loop_guard` chỉ soi mục cuối cùng cùng chữ ký → quét TOÀN BỘ mục cùng chữ ký; H8.4 `progress_signal` báo không tiến bộ khi tiêu chí mở cuối cùng vừa đóng; H8.5 `_budget` thiếu mã/trường khi effort lạ → `ADAPTIVE_EFFORT_INPUT` + field.

## Chưa kiểm
- Chưa nối composer/runtime: "legacy/adaptive không chạy hai scheduler cho cùng admission" và "main xử lý việc nhỏ trực tiếp" chưa kiểm trong phiên thật — **chưa kiểm**.
- Hiệu quả/chi phí của hành vi adaptive chưa đo (cần calibration H10.1 + consent).
