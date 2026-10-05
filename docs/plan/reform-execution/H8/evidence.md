# H8 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_adaptive_main.py`: **87 ca** (87 hàm).
- Probe P6 trong `probes_962cd84.json`: **14/14** —
  - stop/revoke luôn thắng (không mở nhánh mới);
  - cùng chữ ký lỗi và bằng chứng không đổi → chặn;
  - không phát minh trần step/wall;
  - mọi quyết định kèm `reason` + `evidenceRefs`.
- Lỗi đã sửa: H8.1 `_clamp_level` coi trần policy là mức duy nhất → clamp theo các mức ≤ trần, ghim ladder snap-up; H8.2 `intentChange`/`scopeChange` kiểu bool/chuỗi nổ `AttributeError` → fail closed, đòi approval; H8.3 `loop_guard` chỉ soi mục cuối cùng cùng chữ ký → quét TOÀN BỘ mục cùng chữ ký; H8.4 `progress_signal` báo không tiến bộ khi tiêu chí mở cuối cùng vừa đóng; H8.5 `_budget` thiếu mã/trường khi effort lạ → `ADAPTIVE_EFFORT_INPUT` + field.

## Nối runtime (`802f51f` + follow-up)
- `adaptive_surface.py` (13 test): decision/loop/evidence bền + cổng `recovery_policy` chặn retry khi policy từ chối; kill switch giữ checkpoint đọc được.
- `c1de24f`: sửa stub `dispatch` (uỷ nhiệm lại `HarnessRuntime.dispatch`) giữ phép ghim cửa kernel.
- `c6c88bb`: writer vận hành cho `harnessPolicy` — `execution_kernel.set_policy/status/root_session`, route `GET|PUT /api/agent/sessions/{sid}/execution-policy` (409 `POLICY_SWITCH_OFF`, 400 `POLICY_MODE_INVALID`); mode `adaptive` đòi cả `BOXFOX_ADAPTIVE_HARNESS` + `BOXFOX_USAGE_LEDGER`; model không có tool ghi policy.
- Nghiệm thu vòng chạy E1–E4 nằm trong **29/29 PASS** trên `c836822` — `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json` (gồm "lặp bị chặn `ADAPTIVE_LOOP_REPEAT`" và "denied có event `recovery_decision`").

## Chưa kiểm
- Hiệu quả/chi phí của hành vi adaptive chưa đo (calibration H10.1 — hoãn #6531).
- Phiên thật dài ngày với mode `adaptive` chưa chạy (cần consent + hai công tắc).
