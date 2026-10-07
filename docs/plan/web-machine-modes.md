# Web checkpoint — IDE và Docker

Ngày: 2026-10-07. Nhánh: `codex/web-machine-modes`.
Baseline: `5716709c23fa2e13a285109c4e827e7b16dc4e35`.
Commit neo trước khi sửa: `3a7858f`.

## Phạm vi owner đã chốt

- Làm dần trên web hiện tại, chưa đóng gói desktop.
- Chọn IDE/Docker và folder ở Settings → Machines → Configuration.
- Menu `…` giữ các workspace. IDE chỉ ẩn Sandbox Controls; Docker giữ Machine/Network.
- Sandbox Machine đổi tên menu thành Machine screen.
- Bảo toàn router, model, thinking, ngôn ngữ mặc định và dữ liệu phiên cũ.
- Không đổi DAG, không tự push/merge.

## Có trong checkpoint này

- Configuration có IDE / Docker, picker folder Windows và nhập đường dẫn thủ công.
- Registry project/settings lưu trong SQLite hiện hữu; bảng thêm mới, không viết lại phiên cũ.
- Phiên cũ giữ Docker. Đổi môi trường/folder của phiên đã gắn tạo chat mới.
- Child kế thừa binding của owner; không nhận override folder từ model.
- Executor chọn host/Docker theo binding của từng phiên. Host không fallback sang Docker khi tool không hỗ trợ.
- Host đọc file trong folder đã chọn; ghi/chạy lệnh cần trust. Agent mutation còn qua approver và policy.
- Thu hồi trust được kiểm lại dù executor đã cache.
- Host Files/IDE có đọc, editor UTF-8, lưu với hash chống ghi đè file đã đổi.
- Host Integrated Terminal hiện là command runner Windows, không phải PTY.
- Host Machine screen có chọn cửa sổ và snapshot do người dùng yêu cầu. Select Element hiện trả metadata cửa sổ cùng ref snapshot; Add to Chat đánh dấu dữ liệu không tin cậy.
- Hook box không poll hoặc bật/tắt Machine/Network ở IDE.
- Bảng chọn mode chỉ render ở Settings Configuration. Panel chưa có folder chỉ mở Settings bằng nút, không nhúng bảng chọn lần hai.

## File để đọc tiếp

- Backend binding, executor dispatch, routes: `backend/src/agentbox/sandbox/machine_router.py`.
- Tạo session và context thực thi: `backend/src/agentbox/agent_core/runtime.py`.
- Nối web runtime và boundary API: `backend/src/agentbox/api/server.py`.
- Chặn custom Claude CLI host chưa hỗ trợ: `backend/src/agentbox/skills/runtime_commands.py`.
- Configuration/state: `frontend/src/components/settings/MachineConfigurationView.tsx`, `frontend/src/store/machineStore.ts`.
- Binding frontend: `frontend/src/hooks/useActiveMachine.ts`, `frontend/src/store/harnessChatStore.ts`.
- Menu/panel/capability: `frontend/src/App.tsx`, `frontend/src/hooks/useBoxState.ts`.
- Host panels: `frontend/src/components/panels/HostWorkspacePanel.tsx`, `HostMachineScreen.tsx`.

## Bằng chứng đã chạy

Máy Windows hiện tại, trước commit checkpoint triển khai:

| Kiểm tra | Kết quả |
|---|---|
| `python -m pytest backend/tests/unit/test_web_machine_modes.py backend/tests/unit/test_harness_runtime.py -q` | 38 passed |
| Native command trong pytest folder có dấu; trust/deny, đúng cwd, hardline | Đạt; nằm trong nhóm trên |
| Nhóm frontend Settings/menu/chat/tab (6 file) | 32 passed trước khi thêm ca panel mở Settings |
| `npm run test -- src/components/settings/MachineConfigurationView.test.tsx src/components/settings/SettingsModal.test.tsx` | 12 passed, sau chỉnh vị trí |
| `npm run typecheck` | Đạt |
| Toàn bộ frontend trước ca panel mới | 1477 passed / 3 failed, 151 file |
| GET qua Vite: `/api/agent/health`, `/api/router/health`, `/api/agent/machines/configuration` | HTTP 200; cấu hình Docker revision 1 |

### Lỗi baseline đã đối chiếu riêng

Archive commit `3a7858f` vào `.tmp/web-mode-baseline`, giữ checkout và dịch vụ đang chạy:

- `ConnectionKeyRing.test.tsx`: 2 ca kỳ vọng nhãn key/last-used không khớp.
- `ProviderConnectionCard.test.tsx`: 1 ca kỳ vọng chuỗi latency không khớp.
- Bản baseline cũng 3 failed / 21 passed trên đúng hai file này. Không sửa provider để làm xanh test trong lượt mode này.
- `test_host_executor.py` baseline cũng 7 failed / 27 passed trên Windows: fixture POSIX gọi `/bin/sh` không có, và kỳ vọng powershell.exe trong khi implementation chọn pwsh.exe.
- Nhóm hiện tại gồm host executor + runtime + mode: 7 failed / 63 passed, đúng cùng 7 ca. Probe Windows mới riêng đã đạt.

Không coi suite toàn bộ là xanh; kết quả baseline chỉ xác định các lỗi tồn tại trước patch.

## Chưa nghiệm thu / còn mở

- Host Plan/Research/Design/Pull Requests chưa nối transport; panel hiện báo rõ giới hạn, không trình dữ liệu Docker như dữ liệu host.
- Writer/index, artifact lifecycle, browser và verify_exec host đầy đủ còn phải tích hợp theo roadmap.
- Editor hiện dùng textarea, chưa Monaco; terminal chưa ConPTY và chưa nghiệm thu Stop/cancel process tree Windows.
- Preview cửa sổ/picker chưa kiểm bằng tương tác UI Windows thật. Fixture và HTTP không thay bằng chứng này.
- Select Element chưa UIA/DOM, chưa thao tác chuột/bàn phím host, chưa persistent CUA grants/lease.
- Cần kiểm cancellation của request preview: revoke/đổi target không được cho response cũ hiện trở lại.
- Nhãn header tab còn phải rà i18n cho Machine screen ở cả hai ngôn ngữ, giữ mặc định hiện hữu.
- Launcher web vẫn chuẩn bị Docker khi khởi động; executor host theo session không đồng nghĩa bootstrap đã độc lập Docker.
- Chưa model smoke chat trên patch này; router/provider/model không sửa. Chat unit regression đã chạy trong nhóm frontend/runtime.
- Chưa nghiệm thu nhiều project chạy model đồng thời, clean Windows, storage relocation, installer hoặc AppContainer.

Đây là checkpoint web từng bước, **không phải Desktop Alpha đã hoàn tất**. Đọc các roadmap hiện hữu trước khi triển khai phần còn lại:

- `docs/plan/v1-machine-environments-roadmap.md`
- `docs/plan/desktop-host-mode.md`
- `docs/plan/desktop-alpha-install.md`
- `docs/handoff/desktop-host-mode-handoff.md`

## Dịch vụ local

Web: `http://localhost:3100/`. Router :3101, harness :3102.
Chỉ harness đã reload để nhận routes mới; giữ router và Docker hiện hữu.
Ba phiên đã lưu đều completed trước reload; không chạy model/turn mới khi kiểm health.
Log reload: `.tmp/web-start-20261007/harness-reloaded.stdout.log` và `harness-reloaded.stderr.log`.
