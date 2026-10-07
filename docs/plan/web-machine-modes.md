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

## Bổ sung sidebar theo phản hồi owner

Neo trước thay đổi: `63fed3e6`. Vẫn nhánh `codex/web-machine-modes`.

- IDE có section Projects, chọn folder, từng folder chứa các session của nó và nút `+` tạo phiên riêng trong project đó.
- Docker có section Sessions riêng; các phiên legacy không có binding giữ Docker, không bị gán lại theo lựa chọn mặc định.
- Giữ Recent/Groups; nhóm người dùng được phân bên trong từng project/môi trường.
- Sidebar hiển thị môi trường của phiên đang mở. Mở phiên Docker không đổi binding các phiên IDE.
- Bộ chọn môi trường vẫn chỉ ở Settings → Machines → Configuration; chọn folder trên sidebar là thao tác project.
- Nút New session toàn cục kế thừa binding đang mở. Nút `+` project dùng folder của chính project; nút `+` Docker tạo draft Docker.
- Draft giữ mode/project trước tin nhắn đầu. Đường gửi ưu tiên draft binding và chụp lựa chọn trước khi tải skill/directive bất đồng bộ.
- Session backend vẫn tạo theo cơ chế hiện hữu khi gửi tin đầu; draft chưa gửi hiện ở sidebar của project đang mở, không tuyên bố đã lưu SQLite.
- Sau khi phiên được lưu, alias frontend được đối chiếu ID backend để tránh hiện hai hàng draft/session.
- Xóa phiên hiện tại chọn phiên tiếp theo cùng project/môi trường; nếu hết thì mở draft đúng binding cũ.
- Không tự trust folder, không sửa router/provider, không làm desktop packaging.

Source bổ sung: `frontend/src/components/shell/Sidebar.tsx`, `frontend/src/lib/machineSession.ts`, `frontend/src/components/shell/SearchSessionsModal.tsx`.

Kiểm tra checkpoint sidebar:

- Hồi quy Sidebar/responsive/Search/Configuration/openSession ban đầu: 30 passed (5 files), typecheck đạt.
- Ca mới `Sidebar.machineModes.test.tsx` cùng `harnessChatStore.openSession.test.ts`: 20 passed trước khi thêm ca đổi default trong lúc catalog đang tải; typecheck đạt.
- Kiểm phân nhóm, project mới, default khác binding, picker hủy/thành công, alias saved, Groups và xóa phiên bằng fixture; chưa gọi dialog Windows thật hoặc model.
- Nhóm cuối gồm Sidebar/responsive/Search/Configuration/openSession và ca phân nhóm mới: 43 passed (6 files); typecheck đạt.
- Đọc tab `http://localhost:3100/` bằng CUA: sidebar thực tế hiện IDE · Projects, Choose folder, Docker · Sessions và ba session legacy trong nhóm Docker. Không thay cấu hình, chọn folder, trust hoặc gọi model khi kiểm UI.
- Lần suite tổng chạy đồng thời với nhóm tập trung bị SettingsModal timeout 5s rồi hai ca sau lỗi do phiên kiểm chưa kết thúc. Chạy lại bộ tổng riêng với `--maxWorkers=4` để kiểm; không sửa timeout/assertion nhằm che lỗi.
- Bộ tổng chạy riêng `npm run test -- --maxWorkers=4`: 1491 passed / 3 failed (1494 ca, 152 file). Chỉ còn đúng ba lỗi Provider đã đối chiếu baseline; SettingsModal không timeout ở lượt này.
- Kiểm whitespace bằng `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`: đạt.
- Commit checkpoint local lưu thay đổi sidebar; không push/merge. Các kết quả này không thay thế bằng chứng Windows thật còn mở ở trên.

## Bổ sung chọn folder và form Tạo dự án (07/10/2026)

Neo trước patch: `d6e19954`, nhánh `codex/web-machine-modes`.

- Theo ảnh owner, hộp trắng cũ là `FolderBrowserDialog` dạng cây. Thay bằng Windows Common Item Dialog (`IFileDialog` + `FOS_PICKFOLDERS`): giao diện Explorer với đường dẫn và tìm kiếm. Không thay màu/theme của Windows hoặc theme BoxFox.
- Helper chạy STA, có owner để dialog hiện phía trước. Probe so sánh cho thấy bản cũ cũng có thể hiện trong môi trường kiểm; chưa chứng minh mọi lần không hiện đều do cùng một nguyên nhân. Bản mới được kiểm riêng với helper hidden và cửa sổ Windows thật.
- Sidebar mở form Tạo dự án: tên → Add/chọn folder → hiển thị đường dẫn → Create project. Chọn folder hoặc hủy form không thêm project, đổi môi trường hoặc tạo draft.
- API `selectOnly: true` chỉ trả đường dẫn. Các caller cũ vẫn dùng hành vi đăng ký folder hiện hữu. API projects nhận tên tùy chọn, giới hạn 120 ký tự và cấm ký tự điều khiển; folder trùng giữ ID/tên/quyền cũ.
- Create project mới đăng ký folder, chọn project host và mở draft đúng binding. Không tự trust project; quyền sửa/chạy vẫn theo cơ chế hiện có.
- Picker đang mở trả `FOLDER_PICKER_BUSY`, không xếp thêm dialog trùng. Timeout trả lỗi riêng; không suy là user đã bấm Cancel. JSON sai hoặc không mở được helper có lỗi rõ.
- Form giữ i18n vi/en, focus và Escape/Cancel; không sửa provider/model/thinking/DAG hoặc đóng gói app.

Source: `backend/src/agentbox/sandbox/machine_router.py`, `frontend/src/components/shell/CreateProjectModal.tsx`, `frontend/src/store/machineStore.ts`, `Sidebar.tsx` và hai catalog i18n.
API tham khảo: [Microsoft Common Item Dialog](https://learn.microsoft.com/en-us/windows/win32/shell/common-file-dialog).

Kiểm chứng trên Windows hiện tại:

| Lệnh/ca | Kết quả thật |
|---|---|
| `python -m pytest backend/tests/unit/test_web_folder_picker.py backend/tests/unit/test_web_machine_modes.py backend/tests/unit/test_harness_runtime.py -q` | 50 passed |
| Probe native trong nhóm trên | Dialog thật được tìm thấy, visible/topmost và có lớp DirectUI của dialog hiện đại; timer hủy đúng dialog của chính tiến trình probe |
| Sidebar.machineModes / Sidebar / Sidebar.responsive / MachineConfigurationView / harnessChatStore.openSession | 41 passed, 5 file |
| `npm run typecheck` | Đạt |
| `npm run test -- --maxWorkers=4`, chạy bộ frontend riêng | 1493 passed / 3 failed, 1496 ca; đúng ba lỗi Provider baseline đã đối chiếu ở trên |
| Whitespace diff check có `cr-at-eol` | Đạt |
| GET health và configuration qua Vite, header admin hiện hữu | HTTP 200 sau reload |

Các fixture kiểm hủy picker, hủy form sau chọn folder, đường dẫn/tên chỉ gửi khi Create, không tự trust, folder trùng, và selectOnly không đổi registry/revision. Probe native kiểm mở/hủy; chưa thay bằng chứng user chọn folder cụ thể rồi chạy model trong project đó.

Đã reload riêng harness sang bản mới sau khi kiểm các session lưu đều completed. Giữ Vite/router/Docker đang chạy. Log: `.tmp/web-start-20261007/harness-modern-picker.stdout.log` và `harness-modern-picker.stderr.log`. Bảng trắng trong ảnh gửi trước reload vẫn là dialog của bản cũ; lần mở mới dùng code Common Item Dialog.

Các giới hạn host/Desktop còn mở ở phần trên tiếp tục giữ nguyên trạng thái. Patch này chỉ hoàn thiện thao tác thêm project/chọn folder trên web, không nghiệm thu toàn bộ roadmap desktop.
