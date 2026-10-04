# H2 — Bằng chứng

## Kiểm tra thật
- `/var/tmp/boxfox-testing/results/parity_checks_3975ab6.json` → `failed: []`; các check đạt:
  - `S4_dispatch_identical`, `S4_guard_identical`, `S4_switch_only_dispatch_identical`, `S4_switch_only_guard_identical`;
  - `S5_adaptive_equals_admitted` = true ở cả 5 chế độ (default, policy-off, policy-on, policy-on-nograph, switch-only);
  - `S5_default_and_switch_only_legacy`, `S5_broken_profile_fails_closed`, `S5_dispatch_matches_kernel_guard`.
- Test module: `backend/tests/unit/test_execution_kernel.py` (23 hàm) + `test_harness_task_service.py` (37 hàm); số ca thu thập 34 + 60 theo bảng trạng thái/PR body.
- Nhóm 17 file H1–H9: **780 passed** — `/var/tmp/h3h8_group_run.log`; bộ scoped `962cd84`: **716 passed** — `/code/.generated_artifacts/h3h8/unit/scoped_suites_962cd84.log`.
- Legacy read: `/var/tmp/boxfox-testing/results/legacy_read_3975ab6.json` → `harness_tables_empty: true`, `legacy_tables_unchanged: true`, `user_version_unchanged: true`.

## Theo nghiệm thu
- **Analysis/plan/design không sửa source; child không rộng hơn parent:** đạt — guard chạy trước policy mới (`test_scope_guard_runs_before_new_policy_gate`), parent/session thiếu thì không fallback (`test_missing_parent_does_not_use_child_tool_fallback`).
- **Checks đúng input/snapshot:** đạt — `test_unknown_policy_is_not_permission`, `test_read_only_controls_work_with_switch_off`; tool bơm theo mode không bị coi là revoke (`test_mode_injected_tools_are_not_reported_as_revoked`, H2.1).
- **Kill switch giữ guard:** đạt — mặc định off (`BOXFOX_ADAPTIVE_HARNESS`, `execution_kernel.py:16`); `test_switch_off_beats_a_live_graph`; bật switch mà thiếu binding canonical vẫn restricted (`test_enabled_engine_without_execution_binding_stays_restricted`).
- **Không tuyên bố native isolation:** đạt — view ghi `enforcement: application`, `filesystemIsolation/networkIsolation: unverified` (`execution_kernel.py:124-125`).

## Chưa kiểm
- Recheck sau await slot: chưa có test E2E riêng; ghim bằng `test_owner_revoke_reads_fresh_config_not_the_callers_copy`.
- Chưa kiểm hiệu năng/thời gian của guard trên lượt thật (ngoài phạm vi H2).
