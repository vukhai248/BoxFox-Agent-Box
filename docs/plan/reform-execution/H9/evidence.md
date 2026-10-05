# H9 — Bằng chứng

## Kiểm tra thật
- `scripts/eval/suite-v2.json` (commit `e7a1e6f`): schema `boxfox-eval-suite/2`, `suiteVersion v2.0`, `status unmeasured`, `measured false`, `livePilotRequiresConsent true`, `measurementContractVersion eval-manifest-v1`, `fixtureHashAlgorithm sha256`.
  - 62 ca: work-acceptance 17, research-r 12, quality-q 12, research-v2 12, seeded-defect 9.
  - 4 disposition: `preserve_invariant`, `map_outcome`, `legacy_trajectory_only`, `measurement_only`.
  - 40 safety oracle (`SAFETY_ORACLES`, `suite_v2.py:326`).
  - Khóa mỗi ca: `caseId, legacyCaseRef, family, intent, outcomeCriteria, invariants, allowedEvidenceKinds, oracleMapping, measurementContractVersion, fixtureHash, sourcePins`.
- `scripts/eval/suite_v2.py`: `SUITE_SCHEMA` (dòng 35), `SUITE_VERSION` (36), `DISPOSITIONS` (41), `SAFETY_ORACLES` (326), `build_suite` (546), `validate_suite` (591), `load_suite` (663), `write_suite` (669), `read_legacy_receipt` (684), `main` (705).
- `backend/tests/unit/test_suite_v2.py`: **38 ca** (đếm `def test_` = 38; 23 ca vòng đầu + 15 ca cho fault corpus/shadow).
- `scripts/eval/fixtures/suite-v2-faults.json` (214 dòng): **33 lỗi** — 26 `manifestFaults`, 2 `receiptFaults`, 4 `buildFaults`, 1 `treeFault`.
- `run_fault_corpus` (`suite_v2.py:854`), `shadow_legacy_cells` (`:928`), `legacy_label_case_id` (`:920`), CLI `--faults`/`--shadow` (`main`, `:984`).

## Theo nghiệm thu
- **Safety oracles giữ nguyên:** khai báo đủ 40 tên + disposition `preserve_invariant`; validator từ chối xoá oracle an toàn vì đường adaptive khác (docstring suite_v2.py dòng 20).
- **Trajectory-only không ép mode adaptive:** có disposition `legacy_trajectory_only`.
- **Không sửa W10 cũ để pass:** không có thay đổi nào trên `/var/tmp/w10f-seq` hay `work_acceptance_bench.py`; suite v2 là lớp riêng.
- **Không rollout trước evidence gate:** chưa có rollout nào; `measured=false`.

## Vòng H9.2 — fixture lỗi offline + shadow (commit `ed5d771`, dọn cây tạm `c3bee48`)
- `python3 scripts/eval/suite_v2.py --faults` → **33/33 lỗi bị bắt đúng mã**, exit 0, 0,57 s; mỗi mã lỗi có đúng một negative control (`len(set(codes)) == len(results)`).
  - 26 lỗi manifest (schema, measured, consent, tập disposition/evidence/family, safety drift, cases/field/duplicate/family/hash/pin, evidence/oracle, disposition, safety remap, trajectory-as-invariant, invariant unknown/not-mapped, hash/pin mismatch).
  - 2 lỗi receipt legacy (`SUITE_RECEIPT_NOT_AN_OBJECT`, `SUITE_RECEIPT_MISSING_CASE_ID`).
  - 4 lỗi nguồn dựng (`SUITE_FIXTURE_ID_MISMATCH`, `SUITE_SOURCE_UNREADABLE`, `SUITE_SOURCE_MISSING_CASE`, `SUITE_ORACLE_UNMAPPED`) — tiêm vào bản chép `scripts/eval` trong cây tạm, cây thật không đổi.
  - 1 lỗi cây (`SUITE_FIXTURE_MISSING`) — manifest đã commit đối chiếu cây thiếu fixture.
  - Test `test_fault_corpus_covers_every_validation_code` ghim: mọi literal mã `SUITE_*` (trừ mã của chính runner `SUITE_FAULT_*`) phải có trong corpus; các mã `SHADOW_*` được ghim riêng bằng test shadow (nguồn `backend/tests/unit/test_suite_v2.py:246`).
- `python3 scripts/eval/suite_v2.py --shadow /code/.plans/w10f-adjudication-working.json --out /code/.generated_artifacts/h3h8/h9/shadow_w10f.json` → **34/34 cell ánh xạ** (17 ca W10 × 2 repeat), `unmapped=0`, `verdictsProduced=0`, `rescored=false`, `measured=false`; trạng thái legacy chỉ ghi làm quan sát: `quality-valid` 31, `unknown` 3 (3 cell chưa hoàn tất theo stop của chủ nhà).
  - Shadow không chấm lại: mọi receipt `verdict=None`; rò verdict bị chặn bằng `SHADOW_VERDICT_LEAKED` (test `test_shadow_blocks_a_leaked_verdict`).
  - Tệp legacy `/code/.plans/w10f-adjudication-working.json` chỉ được đọc (không ghi).
- Bộ test suite v2: **38 passed** (`backend/tests/unit/test_suite_v2.py`); các commit sau `c3bee48` đến `82550cc` không đổi `scripts/eval/**` hay `test_suite_v2.py`.

## Chưa kiểm
- Live pilot + báo cáo valid/invalid + quality/cost/latency/interruptions **chưa chạy** (đúng trạng thái `unmeasured`); cần consent tài chính riêng (H10.1) — không tự chạy, không ghi là đã có quyền.
- Chưa có lượt shadow nào chạy trên dữ liệu cell của research-r/quality-q/research-v2/seeded (các nhóm đó chưa có receipt legacy dạng cell như W10.F).
- "parity" trong runbook H9 được hiểu là **parity ánh xạ** (shadow ở trên); chưa có lượt parity hành vi nào giữa đường legacy và đường v2 vì đường v2 chưa chạy sống.
