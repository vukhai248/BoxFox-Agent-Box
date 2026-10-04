# H9 — Bằng chứng

## Kiểm tra thật
- `scripts/eval/suite-v2.json` (commit `e7a1e6f`): schema `boxfox-eval-suite/2`, `suiteVersion v2.0`, `status unmeasured`, `measured false`, `livePilotRequiresConsent true`, `measurementContractVersion eval-manifest-v1`, `fixtureHashAlgorithm sha256`.
  - 62 ca: work-acceptance 17, research-r 12, quality-q 12, research-v2 12, seeded-defect 9.
  - 4 disposition: `preserve_invariant`, `map_outcome`, `legacy_trajectory_only`, `measurement_only`.
  - 40 safety oracle (`SAFETY_ORACLES`, `suite_v2.py:326`).
  - Khóa mỗi ca: `caseId, legacyCaseRef, family, intent, outcomeCriteria, invariants, allowedEvidenceKinds, oracleMapping, measurementContractVersion, fixtureHash, sourcePins`.
- `scripts/eval/suite_v2.py`: `SUITE_SCHEMA` (dòng 35), `SUITE_VERSION` (36), `DISPOSITIONS` (41), `SAFETY_ORACLES` (326), `build_suite` (546), `validate_suite` (591), `load_suite` (663), `write_suite` (669), `read_legacy_receipt` (684), `main` (705).
- `backend/tests/unit/test_suite_v2.py`: **23 ca** (đếm `def test_` = 23, khớp bảng trạng thái).

## Theo nghiệm thu
- **Safety oracles giữ nguyên:** khai báo đủ 40 tên + disposition `preserve_invariant`; validator từ chối xoá oracle an toàn vì đường adaptive khác (docstring suite_v2.py dòng 20).
- **Trajectory-only không ép mode adaptive:** có disposition `legacy_trajectory_only`.
- **Không sửa W10 cũ để pass:** không có thay đổi nào trên `/var/tmp/w10f-seq` hay `work_acceptance_bench.py`; suite v2 là lớp riêng.
- **Không rollout trước evidence gate:** chưa có rollout nào; `measured=false`.

## Chưa kiểm
- Chưa có fixture lỗi offline; chưa chạy parity/shadow — **chưa kiểm**.
- Chưa có báo cáo valid/invalid + quality/cost/latency/interruptions (đúng trạng thái `unmeasured`).
- Live pilot **chưa chạy**; cần consent tài chính riêng (H10.1) — không tự chạy, không ghi là đã có quyền.
