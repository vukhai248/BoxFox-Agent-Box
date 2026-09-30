# Roadmap v1 — Môi trường thực thi, Desktop, Update và Android Remote của BoxFox

> **Trạng thái:** Đã lập kế hoạch và gộp quyết định. Thứ tự đã chốt mới nhất: Desktop tương tự web, vẫn Docker → native hoàn chỉnh M1–M7 → Update → Android Remote. Linux guest và cloud giữ cổng riêng. Chưa triển khai hoặc nghiệm thu các tính năng mới.
>
> **Ngày:** 2026-09-30. **Nhánh:** B. **Baseline khảo sát:** 8ffb82ad.
>
> **Mục đích:** Lưu quyết định, căn cứ, phương án, checkpoint và tiêu chí kiểm tra để coding agent khác tiếp tục. Tài liệu không phải lệnh bắt đầu triển khai.
>
> **Bằng chứng:** Đọc code/tài liệu, phỏng vấn nhiều vòng, tra nguồn chính thức. Chưa chạy prototype, test, browser flow, benchmark hoặc CUA.

> **Bổ sung ngày 2026-09-30:** Gộp kế hoạch Desktop/Update/Android vào chính tài liệu này. Flow và thứ tự mới ở §13; quyết định/giới hạn ở §14; thiết kế Desktop ở §15; Update ở §16; checkpoint và checklist kiểm tra ở §17; Android ở §18; handoff tổng ở §19.
>
> **Thứ tự ưu tiên mới nhất:** Desktop Docker D1–D4 → native M1–M7 và người dùng nghiệm thu đầy đủ → Update U1–U4 → Android R0–R3 → các phần tương lai theo cổng riêng. Không làm Update hoặc Android trước khi native hoàn chỉnh. M1–M7 vẫn là mã của nhánh môi trường, được đưa vào flow tổng ngay sau Desktop.

## 1. Kết luận và quyết định đã chốt

BoxFox cần tách môi trường thực thi khỏi harness và giao diện. Roadmap giữ cả ba hướng:

| Hướng | Ý nghĩa | Nơi chạy code/tool | Machine screen |
|---|---|---|---|
| A — Môi trường tách biệt | Docker hiện tại; về sau có thể thay máy được cấp trên cloud | Máy tách biệt được cấp cho công việc | Desktop của máy đó |
| B — Máy người dùng | Hook trực tiếp host, hoạt động không cần Docker | Windows/macOS/Linux của người dùng | Cửa sổ hoặc màn hình host được chọn |
| C — Linux không Docker | Linux qua WSL/VM, có thể chia sẻ workspace host | Guest Linux hoặc môi trường Linux riêng đã kiểm chứng | Desktop Linux phải provision riêng |

**Khuyến nghị cho nhánh môi trường thực thi:** Refactor ranh giới máy bằng A trước; prototype B trên cả ba nền tảng trước khi triển khai rộng. Giữ C trong roadmap, có cổng nghiên cứu và quyết định riêng. Không triển khai mọi hướng cùng lúc khi routing và quyền chưa được chứng minh. **Ưu tiên roadmap tổng mới nhất:** đóng gói giao diện Desktop tương tự web và giữ Docker, tiếp theo hoàn thành native M1–M7; Update/Android chỉ bắt đầu sau cổng nghiệm thu native (§13).

Ba hướng trong tài liệu không yêu cầu lập tức có ba nút Settings. Trải nghiệm chính dự kiến là **Môi trường tách biệt** và **Máy này**. C chỉ trở thành lựa chọn Linux thử nghiệm sau khi qua cổng nghiệm thu. Naming này là đề xuất kỹ thuật/sản phẩm, chưa phải tên người dùng đã chọn.

### 1.1 Quyết định do người dùng xác nhận

- Lưu cả ba hướng để thực hiện trong tương lai; hiện đánh giá độ phức tạp rất cao.
- B không dùng Docker; không dùng container làm fallback native ẩn.
- Native đủ luồng file, shell, browser, screen, Select Element và control trên Windows, macOS, Linux.
- Linux hỗ trợ chính thức ban đầu tập trung Ubuntu GNOME/KDE; kiểm tra Wayland/X11 riêng.
- Quyết định mới nhất: Desktop đợt đầu tương tự giao diện web hiện tại và vẫn chạy Docker, chỉ chuyển sang cửa sổ app. Sau nghiệm thu Desktop làm trọn native M1–M7 rồi mới Update/Android (§13–14). Việc đóng gói không tự tạo backend native.
- Người dùng chọn cửa sổ/màn hình chia sẻ; chọn element trong preview của Machine screen.
- Quyền xem và điều khiển tách riêng. Agent có lượt input rõ ràng, Stop và đường trả quyền cho user.
- File giới hạn theo workspace được chọn; mặc định xem trước, bật ghi rõ ràng.
- Lệnh host mặc định cần phê duyệt; có hướng tự chủ theo phạm vi và toàn quyền tài khoản.
- Browser riêng của BoxFox là mặc định; browser cá nhân kết nối theo lựa chọn. Chrome/Edge là mục tiêu đầu.
- Settings đổi default cho phiên mới; phiên cũ giữ binding máy/workspace.
- IDE native có editor/diff trong BoxFox và nút mở IDE đã cài.
- Preview ở máy; gửi snapshot/element tới model theo tác vụ; không quay video nền mặc định.
- Automation native dùng file/shell theo quyền; desktop cần lượt điều khiển hợp lệ và chờ khi máy khóa.
- Job dài có log, status, Stop và phục hồi trạng thái sau restart.
- Bộ nhớ agent và file dự án cần tiếp tục sử dụng theo phạm vi, không chuyển quyền thực thi ngầm.
- Không kiểm CUA trong đợt này; checklist dành cho agent khác ở §11.
- Chỉ thao tác công việc này trên nhánh B, không sửa main.

### 1.2 Ý tưởng đã thay thế và giới hạn

Đã cân nhắc Docker gắn thư mục host và gọi Conda/Java trên host. Sau đó người dùng làm rõ A/B phải tách, native không dùng Docker. Vì vậy **Docker + host execution không phải kiến trúc native mặc định đã chốt**. Shared folder vẫn là ứng viên cho A/C, không được dùng để đổi tên một luồng còn phụ thuộc Docker thành native.

Docker hiện mô phỏng **môi trường thực thi tách biệt**, chưa phải toàn bộ BoxFox chạy trên cloud: harness/router hiện khởi động trên host. Đưa cả harness, database, tenancy và control plane lên cloud là phần việc riêng khi có dịch vụ cloud thực tế.

Native dùng OS thực tế. Windows không tự có desktop Linux vì giao diện có panel Machine screen.

## 2. Hiện trạng từ mã nguồn

Các file dưới đây là hiện hữu tại baseline; bảng không mô tả code mới đã làm.

| Thành phần | Căn cứ | Khoảng cách |
|---|---|---|
| Configuration | frontend/src/components/settings/SettingsSidebar.tsx có mục configuration; SettingsModal.tsx chưa có nhánh riêng thực hiện nó | Cần cấu hình thật |
| Runtime | backend/src/agentbox/api/server.py tạo HarnessRuntime với một SandboxExecutor | Cần routing theo session binding |
| Executor | sandbox/executor.py dùng docker cp, docker exec và API box | Không thể chỉ đổi container thành host |
| Worker | sandbox/worker.py cố định /home/agent/workspace, Bash, DISPLAY :99, xdotool và CDP | Phụ thuộc Linux box |
| Prompt/tool schema | agent_core/runtime.py có identity Docker; tool_contracts.py nói terminal_exec chỉ chạy Bash trong sandbox | Phải dựng hướng dẫn theo máy/capability thật |
| Engine khác | sandbox/claude_executor.py cũng dùng docker exec; tools/terminal_ops.py có đường terminal riêng | Audit mọi đường thực thi và fallback |
| Desktop | deploy/docker cung cấp XFCE/Xvnc/websockify; useVncScreen.ts và SandboxScreenPanel.tsx dùng noVNC | Native capture cần adapter mới |
| Inspector | deploy/docker/inspect_element.py dùng X11/CDP; frontend/types/inspect.ts có dom/desktop | Cần accessibility/region và source identity |
| File/IDE/terminal | frontend/lib/workspace, plans, ide, terminal gọi dịch vụ box; IDE cố định code-server/root Linux | Các panel phải cùng binding với agent |
| Power/network | useBoxState.ts cache cấp module, gọi /__box/power và /__box/network | Cache global có thể hiển thị/sửa nhầm máy |
| Docker workspace | deploy/docker/docker-compose.yml dùng named volume agentbox-workspace | Không phải thư mục host được chọn |
| File safety | deploy/docker/workspace_files.py dùng dir_fd/O_NOFOLLOW và POSIX | Không bê nguyên sang Windows |
| Memory/artifacts | session_journal.py lưu file qua worker; SQLite session/checkpoint/ledger trên host | Cần locator và namespace theo máy/workspace |
| Quyền | security-model.md ghi rõ đặc tả chưa chứng minh enforcement; frontend/lib/permissions.ts không có “luôn cho phép” | Không suy có sandbox/gateway host từ prompt/UI |
| Launcher | scripts/start.ps1/start.bat gồm logic Docker | Native cần nhánh không Docker và launcher macOS/Linux |

Điểm sửa đầu tiên là ranh giới thực thi và dữ liệu; không bắt đầu bằng cách thêm dropdown rồi để panel tiếp tục gọi một box API global.

## 3. Khả thi, giá trị và chi phí của từng hướng

### 3.1 A — Docker và cloud tương lai

**Nên làm:** Có, làm nền tương thích trước. Bọc Docker hiện tại bằng adapter, giữ luồng desktop, selector, code-server, terminal, mạng và artifacts. Phiên cũ migrate sang Docker legacy, không tự chuyển sang host.

Cloud thay provisioning/transport adapter, cần ownership, authentication, heartbeat, cancellation và audit. Không hardcode IP/cổng Docker thành giao thức cloud. Mất remote không tự chạy thay trên host.

Không tự đồng bộ toàn ổ đĩa lên cloud. Upload/migration có preview dữ liệu, quyền, tiến độ và xử lý thất bại riêng.

**Độ phức tạp:** Vừa đến cao cho adapter/routing; rất cao nếu bao gồm provisioning, tenant isolation, storage, billing và remote harness. Phần cloud đầy đủ chưa thuộc đợt đầu.

### 3.2 B — Host native

**Khả thi về nguyên lý:** Có. File/process có API host; capture/accessibility/input có cơ chế OS. Không có API chung bảo đảm mọi ứng dụng trên ba OS có DOM/control đọc được.

**Giá trị:** Dùng repo, IDE, Conda/JDK, browser và tài nguyên host đang có.

**Chi phí lớn nhất:** Enforcement quyền, capture/source identity, coordinate mapping, tương thích ứng dụng, process lifecycle và bảo vệ local API.

**Điều kiện nên làm:** Prototype chứng minh không gọi Docker, file đúng scope, duyệt lệnh, Stop, browser và inspector đúng nguồn. Không gọi một bản chạy được shell/chụp desktop là “native đầy đủ”.

Giữ mục tiêu ba nền tảng, nghiệm thu độc lập. Khả năng chưa đạt có nhãn experimental/unavailable; không lấy kết quả Windows làm bằng chứng cho macOS/Linux.

### 3.3 C — Linux không Docker

**Khả thi có điều kiện:** Bỏ Docker vẫn cần môi trường Linux và provisioning. Các ứng viên nghiên cứu:

| Host | Ứng viên prototype | Cần chứng minh |
|---|---|---|
| Windows | WSL 2, distro riêng của BoxFox | Lifecycle, file sharing, desktop Linux, quyền/network; không tác động distro cá nhân |
| macOS | Linux VM qua Virtualization.framework | Guest image, shared directory, desktop, architecture và lifecycle |
| Linux | VM qua QEMU/KVM | Virtualization, desktop/transport, file sharing và isolation |

Đây là ứng viên, chưa benchmark/chốt provider. Trước coding provisioning C, ADR phải khóa provider/version, workspace sharing và cách thu hồi quyền từng OS. Không đạt prototype thì giữ backlog.

WSLg chạy ứng dụng Linux không tự có toàn bộ XFCE/VNC/code-server hiện tại. Muốn giữ Machine screen phải provision các dịch vụ đó trong guest.

Không dùng distro/VM cá nhân mặc định; không tự cài WSL, bật virtualization hoặc sửa cấu hình hệ thống.

Nguồn: [Microsoft WSL](https://learn.microsoft.com/en-us/windows/wsl/about?trk=article-ssr-frontend-pulse_little-text-block), [WSL filesystem](https://learn.microsoft.com/en-us/windows/wsl/filesystems), [Apple Linux VM](https://developer.apple.com/documentation/virtualization/running-linux-in-a-virtual-machine).

### 3.4 Conda, Java và “dùng chung”

- Mount chia sẻ file, không chia sẻ interpreter/process hay tự chuyển thư viện host thành thư viện Linux.
- Conda Windows/macOS không được coi là chạy trong Linux chỉ bằng mount folder.
- Virtualenv Python không portable bằng cách chép thư mục.
- Java phân biệt source/JAR có thể dùng chung với JVM/native library thuộc nền tảng.
- B chạy đúng Conda/JVM host. A/C dùng runtime của máy đó.
- Runtime không tương thích trả lỗi rõ OS/architecture/nơi chạy; không âm thầm đổi máy hoặc cài dependency.
- Với deep learning, chỉ hứa GPU sau probe runtime thật; tên môi trường không chứng minh CUDA hoạt động.

Nguồn: [Docker bind mounts](https://docs.docker.com/engine/storage/bind-mounts/), [Python venv](https://docs.python.org/3/library/venv.html), [Conda environments](https://docs.conda.io/projects/conda/en/stable/user-guide/tasks/manage-environments.html), [Docker multi-platform](https://docs.docker.com/build/building/multi-platform/).

## 4. Kiến trúc chung đề xuất

### 4.1 Trách nhiệm và stack

~~~text
BoxFox web UI
    |
Harness: model loop, workflow, delegation, checkpoint
    |
Machine router + policy/approval + artifact routing
    |
    +-- A: Docker adapter -> dịch vụ Linux box hiện tại
    |       về sau: Remote adapter -> máy được cấp trên cloud
    +-- B: Local Host Bridge -> file/process/browser/capture/control host
    +-- C: Guest adapter -> WSL/VM riêng + dịch vụ Linux guest
~~~

Mỗi request chỉ tới máy đã bind. Không fan-out hoặc fallback sang host khi Docker/remote lỗi.

Harness sở hữu trạng thái/ý định và giao tiếp user. Router lấy binding đã lưu. Bridge/backend kiểm quyền và trả bằng chứng thật về nơi thực thi; model không tự khai máy đã chạy.

Giữ Python harness, React/TypeScript UI, tái sử dụng Docker services qua adapter. Đề xuất Host Bridge core điều phối Python và helper OS cho capture/accessibility/input. Phần môi trường thực thi này chưa triển khai framework desktop; thiết kế Electron shell cho đợt đóng gói riêng nằm ở §15. Host supervisor của app không phải Host Bridge cấp quyền native.

Module dưới backend/src/agentbox/machines và helper dưới deploy/native là **đường dẫn dự kiến tạo**, không phải code đã có.

### 4.2 Binding và capability

~~~text
MachineBinding:
  machineId
  backendKind: docker | native | linux_guest | remote
  workspaceId
  bindingRevision
  machineEpoch
  permissionProfileId
  runtimeSelection

Capability:
  name
  state: available | needs_permission | unsupported | degraded | disconnected
  reasonCode
  implementationVersion
~~~

Root session lưu binding; child kế thừa và chỉ nhận quyền bằng/hẹp hơn cha. Role, custom command hoặc model không tự đổi profile/máy.

Settings chỉ đặt default phiên mới. Chuyển môi trường công việc đang có tạo phiên tiếp tục sau preview dữ liệu cần chuyển; phiên cũ giữ binding/lịch sử.

Capability tối thiểu: file.read/write, process.exec/jobs/pty, browser.managed/personal_dom, screen.preview/capture/record, element.dom/accessibility/region, desktop.input, network.enforced và workspace.enforced.

Unsupported khác chưa cấp quyền. UI phải nói rõ nguyên nhân, không che bằng một nút disable chung.

### 4.3 Lifecycle và concurrency

- A legacy giữ container hiện tại.
- Native có bridge/device identity theo host; workspace, grant, job theo phiên/dự án.
- Browser profile theo workspace; input thật có owner/lease theo device.
- Guest/remote có instance theo binding; quota số máy và tài nguyên cần chốt trước provisioning.
- State máy: stopped, starting, ready, degraded, disconnected, error.
- Cache UI keyed machineId/workspaceId/bindingRevision, gồm screen, network, files, plan, terminal.
- Reconnect không tự khôi phục grant hết hạn hoặc ref của epoch cũ.
- Cùng workspace cần kiểm soát writer/job conflict; không cho hai agent sửa cùng file mà không đối chiếu version/hash.

## 5. Workspace, runtime, job và memory

### 5.1 File/IDE/artifacts

Người dùng chọn root bằng picker/helper; backend ghi canonical root và nguồn grant. Model không tự đăng ký cả ổ đĩa.

Ban đầu file tools chỉ đọc; bật ghi là grant rõ. Dùng workspaceId + relative path. Adapter OS xử lý Windows drive/UNC/junction/reparse point, symlink, case sensitivity và Unicode.

Không dùng prefix chuỗi làm ranh giới. Kiểm tra tại thời điểm mở file, gồm thay link lúc request chờ. POSIX dir_fd không tự tương đương Windows filesystem safety.

Editor/diff/upload/download/thumbnail/archive và model file tools cùng FileService. Archive chặn traversal/link escape. File panel và agent luôn cùng workspace.

App-data/sidecar lưu cache và artifact khi workspace chỉ đọc; không tự ghi .plans hoặc .generated_artifacts vào repo chưa có write grant.

IDE native có editor/diff và mở IDE host đúng workspace. Docker/guest giữ code-server khi có capability. Không để native panel gọi code-server Docker rồi nói đang sửa host.

### 5.2 Runtime registry

Lưu runtimeId, loại, OS/architecture, executable/prefix, version, probe result và revision. Không sửa PATH/Conda/JDK toàn hệ thống.

Probe cũng là thực thi code; executable phải được đăng ký/chọn và qua kiểm quyền. Không gọi shell tùy ý dưới tên “khảo sát”.

- Conda: chọn executable và prefix; chạy argv có cấu trúc qua conda run, không ghép model text vào conda activate.
- Python: interpreter đã chọn; log executable/prefix thật.
- Java: chọn JDK/JRE, xác minh version, JAVA_HOME/PATH riêng cho process.
- Shell: PowerShell Windows, shell đã đăng ký trên macOS/Linux. Không tự coi Bash/PowerShell tương đương.
- Env process dùng allowlist/override riêng, không chuyển toàn bộ env harness/router chứa provider keys.
- Install dependency hoặc sửa môi trường user là action riêng; không tự làm để qua test.

### 5.3 Lệnh và job dài

Request phân biệt argv với shell script; không cùng xuất hiện. Backend resolve runtime, caller không thay máy bằng executable/path gửi tùy ý.

Lệnh ngắn có timeout. Job dài có jobId, stdout/stderr stream, status, exit code, cancel và artifact; không giữ model loop polling. Hết lượt model không phải hết job.

State: queued, awaiting_approval, running, succeeded, failed, cancelled, interrupted, unknown. Spawn thành công chưa phải tác vụ thành công.

Job lưu máy/cwd/runtime thật, request hash, actor/grant, process identity, start time, timeout và artifacts. Timeout được hiển thị/cấp trước khi chạy, không mặc định vô hạn.

Cancel xử lý owned process tree theo OS: Windows Job Object hoặc cơ chế tương đương; Unix process group/job scope kiểm chứng. Không hứa dừng hết descendants chỉ bằng một PID.

Reload nối lại log. Restart đối chiếu runner/ownership/PID/start identity; không tự chạy lại training/install/server không idempotent. Không xác minh được thì unknown/interrupted, báo user.

### 5.4 Bộ nhớ dùng chung

SQLite là nguồn session/checkpoint/ledger. Artifact locator có machineId, workspaceId, URI/path tương đối, hash và provenance.

Memory theo workspace/task lineage:
- Mục tiêu/brief/câu trả lời có thể tiếp tục dùng sau đối chiếu.
- Bằng chứng file thuộc workspace/hash snapshot.
- Test result thuộc máy/runtime/commit đã chạy.
- Grant, PID, DOM/element ref không chuyển sang máy khác.

Chuyển máy phải khảo sát lại OS/runtime và đối chiếu file. Test Docker không chứng minh test Conda host. Giữ plan/research/design/history cũ đọc được; namespace lookup theo workspace để hai dự án cùng slug không nhận nhầm approval/review.

## 6. Machine screen và Select Element

### 6.1 Hành vi từng hướng

| UI | A — Docker/remote | B — Native | C — Guest Linux |
|---|---|---|---|
| Screen | Desktop máy tách biệt | Nguồn host được chọn | Desktop guest |
| Resize | VNC nếu capability cho phép | Scale preview, không đổi resolution host | Theo guest |
| Selector | X11/CDP adapter | DOM/accessibility/region | Inspector guest kiểm chứng |
| Terminal | Shell máy tách biệt | Host/runtime đã chọn | Linux guest |
| Power | Start/stop môi trường | Connect/pause BoxFox, không shutdown host | Start/stop guest |
| Network | Policy máy tách biệt | Policy job/bridge khi enforce được, không tắt mạng host | Guest policy |

Nhãn phải chỉ rõ Docker local, Máy này, guest hay remote. Không dùng “LIVE · REAL MACHINE” chung cho mọi backend.

### 6.2 Luồng chọn element

1. User chọn nguồn, cấp view; backend trả sourceId và hình học.
2. Select Element bật overlay trong preview; cú click chỉ chọn, không gửi input thật.
3. Request có sourceId, frameId, geometryRevision và điểm tọa độ frame.
4. Backend inspect đúng nguồn cấp quyền; element nguồn khác bị từ chối.
5. Drawer ghi loại, ứng dụng/cửa sổ/tab, bounds, giới hạn và status.
6. Add to Chat gắn snapshot có nhãn untrusted, không biến text thành lệnh/grant.
7. Trước action, resolve lại ref, kiểm grant/source/epoch/geometry/focus. Stale thì refresh, không click tọa độ cũ.

Kết quả:
- **DOM:** node/selector/role/text/bounds thuộc tab kết nối.
- **Accessibility:** role/name/value được phép, supported actions và elementRef; không tự chế CSS selector.
- **Region/window:** vùng ảnh/metadata cửa sổ khi không có control semantic; nói rõ giới hạn.

OCR/vision là suy luận, không khai thành DOM/accessibility đã xác minh. Không lấy password value/clipboard hệ thống. Screenshot vẫn có thể chứa bí mật dù đã lọc field.

### 6.3 Adapter OS và vấn đề bắt buộc prototype

| OS | Capture | Inspector | Input |
|---|---|---|---|
| Windows | Windows.Graphics.Capture/picker | UIA + browser bridge | UIA actions hoặc SendInput có quyền |
| macOS | ScreenCaptureKit/picker | AX + browser bridge | Accessibility/OS input có quyền |
| Wayland | Portal ScreenCast/PipeWire | AT-SPI khi map đúng nguồn + DOM | RemoteDesktop portal/EIS theo capability |
| X11 | Capture nguồn được cấp | AT-SPI/window + DOM | X11 adapter có kiểm quyền |

Windows input chịu UIPI; không tự chạy admin để vượt chặn. macOS phản ánh quyền/revoke OS. Linux có thể có stream nhưng thiếu identity/hình học để map control; trả region/degraded thay vì đoán.

**Cửa sổ bị che:** preview có thể vẫn có hình nhưng global hit-test trúng app che. Cần target-scoped tree/geometry đã kiểm chứng hoặc refresh/đưa đúng app lên trước trong lượt điều khiển được cấp. Không tự đổi focus chỉ để user chọn element.

Metadata gồm DPI, monitor origin, rotation, crop, frame pixels và transform. Move/resize/change monitor tăng geometryRevision. Không giữ giả định X11 1280×800 cho native.

Nguồn: [Windows capture](https://learn.microsoft.com/en-us/windows/apps/develop/media-authoring-processing/screen-capture), [UIA](https://learn.microsoft.com/en-us/windows/win32/api/uiautomationclient/nf-uiautomationclient-iuiautomation-elementfrompoint), [SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput), [Apple picker](https://developer.apple.com/documentation/screencapturekit/sccontentsharingpicker), [Apple hit-test](https://developer.apple.com/documentation/applicationservices/1462077-axuielementcopyelementatposition), [XDG](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.RemoteDesktop.html), [AT-SPI](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Component.get_accessible_at_point.html).

## 7. Browser, quyền và Host Bridge

### 7.1 Browser

Managed browser có profile riêng theo workspace, automation kiểm quyền; không sao chép cookie/profile cá nhân.

Chrome/Edge cá nhân dùng extension kết nối rõ: đề xuất MV3 + Native Messaging. User chọn tab/site; không mặc định toàn browser. Extension chỉ nhận action schema có allowlist, không là cổng CDP/JavaScript tùy ý từ model.

Tab đóng/navigation/revoke invalidates ref/grant. Browser chưa kết nối vẫn có thể xem như app desktop, nhưng không gọi đó là DOM. Không yêu cầu mở CDP trên profile cá nhân để né extension.

Nguồn: [Chrome remote debugging](https://developer.chrome.com/blog/remote-debugging-port), [Native Messaging](https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging), [debugger](https://developer.chrome.com/docs/extensions/reference/api/debugger).

### 7.2 Preset

| Preset đề xuất | Hành vi | Điều kiện |
|---|---|---|
| Cần phê duyệt — mặc định | Read theo root; write cần grant; host command duyệt payload | Gateway mọi đường |
| Tự chủ theo phạm vi | Tự làm trong ranh giới enforce, vượt scope hỏi user | OS sandbox đã kiểm chứng |
| Toàn quyền tài khoản | Grant chủ động cho phiên, tác động rộng | Warning/expiry/revoke rõ; không tự có admin |

cwd/path check/regex không sandbox được Python/Java/shell. Không bật preset giữa như workspace-only khi chưa enforce.

OS sandbox cho lệnh và desktop control là hai ranh giới. Control terminal/IDE/Run dialog có thể thực thi ngoài shell sandbox; không gọi toàn phiên là workspace-only khi vẫn cấp khả năng này.

Toàn quyền là grant phiên có thể revoke, không thêm “luôn cho phép” vĩnh viễn vào thẻ hiện tại. Plan/Research không được build/install vì native/full profile.

Không thêm reviewer tự duyệt đợt đầu: user đã chọn tự chủ theo phạm vi. Auto-review là công việc riêng. Codex là tham khảo phân biệt sandbox/approval, không phải bảo đảm BoxFox đã có: [Sandbox](https://learn.chatgpt.com/docs/sandboxing), [Auto-review](https://learn.chatgpt.com/docs/sandboxing/auto-review), [Windows sandbox](https://learn.chatgpt.com/docs/windows/windows-sandbox).

### 7.3 Grant/gateway

Grant lưu actor, machine/workspace/source, actions, epoch/revision, expiry, request hash và revoke. Backend ghi nguồn user; model không tự approved.

Duyệt ràng buộc máy/cwd/runtime/argv-script/env override/job limit. Request đổi cần quyết định mới; kiểm lại ở dequeue và ngay trước spawn.

Pending approval sống qua reload, không tự approve vì timeout. Invocation trùng không chạy hai lần; revision cũ trả conflict có status mới.

Direct calls, custom command, delegation, engine khác, file panel, PTY, browser và desktop đều kiểm gateway. Không có host fallback trong registry/CLI.

Native sớm có thể chỉ expose Cần phê duyệt. Preset chưa có enforcement phải unavailable, không giả lập bằng prompt. OS sandbox implementation/version phải qua prototype/ADR trước bật.

### 7.4 Local transport

Host Bridge first-party core + helper OS; không phải script model tự chạy. Harness ↔ bridge ưu tiên named pipe Windows/Unix socket macOS/Linux với ownership. Không mở RPC host không auth trên LAN.

UI ↔ harness cần authenticated local channel. Loopback/Origin/CORS không đủ: native endpoints kiểm token UI, CSRF và session ownership. Không dùng dev token tĩnh frontend làm quyền host production.

Key provider/credential không đặt trong container/workspace; scrub log/env subprocess. Website/container không được gọi host exec chỉ bằng HTTP POST.

Windows helper nền không mở terminal gây gián đoạn; macOS helper có identity/quyền ổn định dù UI web. Launcher phát hiện thiếu dependency và hướng dẫn, không tự cài/sửa môi trường hoặc đổi provider.

### 7.5 Input và dữ liệu

View/control độc lập; control không cho đọc toàn filesystem. Một device có một owner input; Stop chặn action mới, release held keys/buttons và trả quyền.

Không hứa global hotkey/user-input detection trên mọi Wayland compositor khi chưa chứng minh; luôn có Stop UI/bridge. Lock/login/UAC secure desktop trả blocked, không auto unlock.

Preview không tự stream provider. Snapshot/element theo tác vụ và grant dữ liệu vào context model đang cấu hình. Video chỉ bật rõ; retention/delete phải được hiển thị. Redaction heuristic không chứng minh hết bí mật.

Automation file/shell chỉ khi runtime hoạt động/grant còn hiệu lực; task theo lịch không tạo quyền mới. Desktop cần lượt control, chờ khi máy khóa.

## 8. API và dữ liệu đề xuất

Các interface sau **chưa triển khai**. Hội tụ với session/approval hiện có, không tạo hai nguồn quyền:

| Interface | Mục đích |
|---|---|
| GET /api/agent/machines | Inventory/capability/status |
| PUT /api/agent/settings/machine-default | Default phiên mới |
| GET /api/agent/sessions/{sid}/machine | Binding/runtime/capability |
| POST /api/agent/sessions/{sid}/machine-continuations | Phiên tiếp tục sau preview chuyển dữ liệu |
| POST /api/agent/workspaces/pick | Picker host/grant root |
| GET /api/agent/machines/{mid}/runtimes | Registry/probe đã cấp |
| POST /api/agent/sessions/{sid}/execution-requests | Approval hoặc job |
| GET /api/agent/jobs/{jid} | Status/metadata |
| GET /api/agent/jobs/{jid}/events | Stream/replay có cursor |
| POST /api/agent/jobs/{jid}/cancel | Cancel idempotent |
| POST /api/agent/sessions/{sid}/capture-sources/pick | Source/view grant |
| POST /api/agent/sessions/{sid}/elements/inspect | Inspect frame/source/geometry |
| POST /api/agent/sessions/{sid}/control-actions | Acquire/release/revoke control |

Mutation có invocationId/revision. Machine binding lấy server-side, không tin machineId caller. Execution request phân biệt argv/script, có runtimeId/cwdRelative/grant/limit; response ghi máy/runtime/cwd thật, job/exit status, duration và artifact locator.

Error code: MACHINE_DISCONNECTED, CAPABILITY_UNSUPPORTED, OS_PERMISSION_REQUIRED, BINDING_REVISION_CONFLICT, GRANT_REVOKED, APPROVAL_EXPIRED, WORKSPACE_SCOPE_DENIED, RUNTIME_INCOMPATIBLE, RUNTIME_UNAVAILABLE, ELEMENT_STALE, SOURCE_CHANGED, SOURCE_IDENTITY_UNAVAILABLE, CONTROL_BUSY, DESKTOP_LOCKED, JOB_STATE_UNKNOWN.

Lỗi quyền/stale binding không retry vô hạn hoặc thử tool khác. Trả status mới/hành động cần làm; permission quay về user.

SQLite bổ sung machine/workspace/grant/runtime/job; binding versioned trong session config. Plan/research/artifact namespace workspace/machine. Migration backup và gán session cũ Docker legacy, không viết lại lịch sử.

## 9. Milestone và cổng quyết định

Thứ tự trong nhánh môi trường: M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7. Flow tổng ở §13 đặt nhánh này ngay sau Desktop D1–D4 và trước Update/Android. Phải hoàn tất nghiệm thu native, không dừng ở prototype rồi nhảy sang phần sau. C1/C2 và A-cloud giữ cổng riêng, không đồng nghĩa native B phải triển khai cả guest/cloud.

| Mốc | Bàn giao | Điều kiện tick |
|---|---|---|
| M0 — Tài liệu | Roadmap/decisions/checklist/handoff | File lưu; giả định và phần chưa kiểm chứng rõ |
| M1 — Routing | Machine contract, Docker adapter, binding, capability/cache | Docker đúng baseline; panel/tool cùng binding; session cũ đọc được |
| M2 — Native core | Bridge, file/artifact/editor, launcher ba OS | Native không gọi Docker; đúng root/grant/secret/transport |
| M3 — Runtime/job | Conda/Python/Java/shell, approval, stream/cancel/reconcile | Đúng env; default deny; duplicate không duplicate job; restart không rerun |
| M4 — Browser | Managed + Chrome/Edge extension | Scope tab/site, stale/revoke; không copy profile |
| M5 — Desktop | Capture/preview/inspector/transform/control | Từng OS qua fixture; bị che/DPI không nhầm; view không cấp input |
| M6 — Enforcement | Audit engine/tool/delegation, sandbox prototype, automation/memory | Không bypass; profile có bảo đảm thật; mode restrictions giữ |
| M7 — Pilot/release | Test, CUA, tác vụ thật, migration/rollback | Report OS độc lập; capability thiếu không được tính hoàn tất |
| C1 — Prototype | WSL/VM ADR, file sharing, resource measurements | Lifecycle/screen/filesystem chứng minh; chọn provider/version |
| C2 — Guest | Adapter/provisioning/grant/artifact/UI | Không Docker; không phá distro/VM cá nhân; runtime Linux thật |
| A-cloud — Đợt riêng | Remote agent/control plane | Chốt hosting/ownership/auth/data/budget trước implementation |

Mỗi mốc cập nhật commit, file thay đổi, ca đã chạy, kết quả, vấn đề còn và bước tiếp theo. Có code chưa đủ tick nghiệm thu.

Không mở native rộng trước M1, không bật tự chủ có giới hạn trước enforcement, không coding provisioning C trước ADR.

## 10. Kiểm thử và nghiệm thu

**Đây là kế hoạch; chưa chạy test trong đợt này.**

### 10.1 Test xác định bắt buộc

- Docker legacy: đúng box/root/terminal/IDE/inspector/plan ledger.
- Native chạy khi không cài Docker hoặc daemon dừng; không có lời gọi docker.
- Default không đổi session cũ; child kế thừa máy/root/quyền.
- Traversal, symlink/junction race, archive escape và outside-root bị chặn.
- Read-only không ghi qua editor/tool/API khác; model không tự grant.
- Payload/cwd/runtime đổi sau approve làm grant invalid; revoke khi queued ngăn spawn.
- Duplicate invocation chỉ một process; old revision conflict rõ.
- Conda fixture xác minh sys.executable/prefix/package chỉ có ở env đó; Java đúng binary/version.
- Không có provider secrets trong env/log/output fixture.
- Cancel xử lý owned descendants; PID reuse không kill nhầm.
- Reload có log; restart không tự rerun job không idempotent.
- Source/frame/geometry sai/stale không input; occlusion không trả element app che.
- Semantic không có trả region/unsupported, không tạo DOM/control giả.
- View không control; control busy/Stop/revoke có hiệu lực.
- Browser navigation/tab close/revoke invalidates ref; bridge không cho JS/CDP tùy ý.
- Power/network native không tắt máy/internet host.
- Plan/Research/Review không vượt bằng native tool/custom/delegate/engine/PTY/desktop.
- Memory transfer không biến grant/ref/test cũ thành bằng chứng mới.
- UTF-8, tên Việt, space, drives và multi-monitor giữ đúng.

### 10.2 Tác vụ thật

| Ca | Fixture | Output đúng |
|---|---|---|
| Coding | Repo được chọn | Diff/file/test đúng root và runtime |
| Conda | Env có package riêng | Dùng đúng env host; không cài lại vào box/global |
| Java | JDK được chọn | Compile/run đúng version/nơi chạy |
| Server | App localhost job | URL/process/runtime/log đúng; Stop hiệu lực |
| Browser | Managed và tab cá nhân cấp quyền | Inspect/action đúng scope; revoke có hiệu lực |
| Desktop | App có accessibility và app chỉ có pixels | Semantic đúng hoặc region có giới hạn rõ |
| Nhiều phiên | Hai workspace, nhiều child | Không nhầm root/máy/runtime/artifact/input |
| Guest | Linux riêng + shared root được chọn | File sharing thật/runtime Linux thật, không giả host Conda |

Live evaluation dùng workspace/database/tài khoản thử riêng, giữ model/provider hiện có. Ghi commit, OS/build/compositor, helper/browser/extension, mode, runtime và từng result. Tách lỗi provider/model, lỗi sản phẩm và OS limitation.

Latency/FPS/CPU/tỷ lệ thành công chưa đo; prototype lập baseline, ADR trước pilot chốt ngưỡng có lý do/tập tác vụ. Không đặt ngưỡng đẹp rồi gọi đạt. Invariant routing/quyền bắt buộc, không dùng trung bình bù lỗi nghiêm trọng.

## 11. Checklist CUA cho agent sau

**Chưa kiểm CUA.** Chạy trên Windows, macOS và Ubuntu GNOME/KDE, phân biệt Wayland/X11. Chỉ fixture vô hại, không dùng dữ liệu thật hoặc action phá máy.

| Check | Thao tác | Output đúng |
|---|---|---|
| Configuration | Settings → Machines → Configuration | Loại máy/default/status/capability thật, không placeholder |
| Default | Đổi default khi session Docker mở | Session cũ Docker; mới native; không đổi ngầm |
| Không Docker | Dừng Docker, mở native | Native hoạt động, không bắt bật Docker |
| Workspace read | Chọn folder có tên Việt | Đúng root; editor không ghi chưa grant |
| Workspace write | Bật sửa, đổi fixture | UI ghi trực tiếp host rõ; file/diff đúng |
| Runtime | Chọn Conda/JDK và chạy | Approval có máy/cwd/env/command; log đúng executable/version |
| Approval | Reject/duplicate/reload | Không chạy bị reject; một approve một job; pending/history còn |
| Job dài | Chạy rồi đóng/mở panel | JobId/log/status giữ; Stop xử lý process sở hữu |
| Source | Chọn rồi đổi window/monitor | Preview đúng nguồn; ref cũ stale |
| Selector | Click preview khi armed | App thật không nhận click; result đúng DOM/AX/region |
| Occlusion | Che cửa sổ nguồn | Không chọn app che; degraded/refresh có lý do |
| DPI/monitor | Move/resize/change scale | Bounds đúng hoặc stale bị chặn; không input nhầm |
| Add to Chat | Thêm, gửi, reload | Snapshot/source/label còn; untrusted không thành grant |
| View/control | View-only rồi xin click | Bị chặn; cấp rồi revoke thì action tiếp bị chặn |
| Input owner | Hai session xin control | Một owner, còn lại busy/wait; Stop trả quyền |
| Browser cá nhân | Connect/navigate/revoke tab | DOM đúng tab; grant/ref invalidate |
| IDE | Editor/diff và mở IDE ngoài | Đúng workspace, không dùng Docker IDE ở native |
| Power/network | Control native | Pause/connection/policy đúng scope; không tắt host |
| Lock/restart | Lock/restart bridge | Input blocked/status đổi; không rerun/restore quyền ngầm |
| Docker regression | Mở lại Docker session | Screen Linux/selector/terminal/IDE/plan đúng baseline |
| Guest | Chọn C sau prototype | Nhãn WSL/VM, Linux runtime thật; không giả native/Docker |

Report có môi trường/commit/expected-actual/evidence đã cấp phép/bug ID và kết luận từng check. Chưa chạy ghi chưa chạy; backend pass không thay UI pass.

## 12. Rollout, rollback và handoff

### 12.1 Rollout

1. Adapter/routing, default Docker legacy.
2. Native sau flag/capability probe, pilot fixture.
3. Support matrix theo từng OS/capability gồm degraded/unavailable.
4. Chỉ bật tự chủ cho backend/runtime đã chứng minh enforcement.
5. C sau C1/C2; cloud triển khai riêng.

Migration có backup/rollback; session/artifact cũ đọc được. Rollback native ngăn request mới, revoke grants, đối chiếu job và giữ history. Không xóa host folder, Conda/JDK hay user files. Job còn sống phải báo rõ.

### 12.2 Track hiện tại

- [x] Khảo sát entrypoint và phụ thuộc Docker chính ở 8ffb82ad.
- [x] Phỏng vấn và lưu quyết định product/OS/quyền/screen/browser/IDE/runtime.
- [x] Phân biệt ba hướng và ghi quyết định thay thế hybrid Docker + host.
- [x] Soạn roadmap/checkpoint/cổng quyết định/checklist CUA.
- [x] Lưu tài liệu trên nhánh B.
- [ ] M1 — Routing/Docker adapter.
- [ ] M2 — Native core.
- [ ] M3 — Runtime/job.
- [ ] M4 — Browser.
- [ ] M5 — Desktop/inspector ba OS.
- [ ] M6 — Enforcement/workflow/automation.
- [ ] M7 — Test/CUA/pilot/release.
- [ ] C1 — Prototype Linux không Docker/ADR.
- [ ] C2 — Guest backend.
- [ ] A-cloud — Khi có quyết định ưu tiên/budget.

**Agent tiếp tục:** Đọc roadmap và instructions hiện hành; kiểm branch/worktree/status, chỉ sửa B. Baseline có thay đổi di chuyển research-design-exploration-report.md sang docs/research thuộc công việc khác, không nhận đó là thay đổi của roadmap này.

Khi được yêu cầu implementation toàn roadmap, bắt đầu D1 theo §13 và §17. Sau D4 chuyển M1–M7 theo thứ tự đã chốt; native nghiệm thu đầy đủ mới chuyển Update/Android. Không tự đổi provider, cài WSL/VM hay dựng native capture trước routing/acceptance nền. Nếu chuyển task, giữ trạng thái từng checkpoint và các nhánh chưa triển khai.

**Chưa có:** code môi trường mới, prototype, chứng minh host sandbox, benchmark/test/CUA results. Việc lưu tài liệu không chứng minh đã thực hiện các phần này.

## 13. Flow triển khai tuần tự của roadmap tổng

### 13.1 Thứ tự người dùng đã cập nhật

Người dùng đã sửa thứ tự sau khi gộp tài liệu: **Desktop tương tự web hiện tại, vẫn Docker → hoàn thành các mốc native trọn vẹn → mới làm các phần sau**. Flow hiện hành cụ thể là **D1–D4 → M1–M7 → U1–U4 → R0–R3**. Thay thế cả ý tưởng Android trước và thứ tự Desktop + Update → Android → native đã ghi trước đó. Bản Desktop đầu phục vụ kiểm thử cá nhân trên máy đã có Docker, chưa phải installer cho user mới.

~~~mermaid
flowchart TD
    P[Đã khảo sát và lưu kế hoạch] --> D1[D1: Build và runtime đóng gói]
    D1 --> D2[D2: Supervisor, gateway và dữ liệu riêng]
    D2 --> D3[D3: Installer, cửa sổ và tray]
    D3 --> D4[D4: Người dùng kiểm thử Desktop Docker]
    D4 --> Gate{Desktop như web, hoạt động ổn định?}
    Gate -->|Lỗi đóng gói| Fix[Sửa checkpoint Desktop, ghi evidence]
    Fix --> D4
    Gate -->|Thiếu tài nguyên hoặc mất môi trường| MC[MC0: Khảo sát và bổ sung kế hoạch Machine Configuration]
    MC --> MCgate{Khắc phục điều kiện chạy đã được chốt?}
    MCgate -->|Chưa| Hold[Giữ các phần sau chưa bắt đầu; ghi blocker]
    MCgate -->|Có| D4
    Gate -->|Đạt và user xác nhận| M1[M1: Routing và Docker adapter]
    M1 --> M2[M2: Native core, file, IDE và bridge]
    M2 --> M3[M3: Runtime, job và approval]
    M3 --> M4[M4: Managed và personal browser]
    M4 --> M5[M5: Screen, Select Element và control]
    M5 --> M6[M6: Enforcement, workflow và automation]
    M6 --> M7[M7: Test, CUA và native pilot đầy đủ]
    M7 --> NativeGate{Native trọn vẹn và user nghiệm thu?}
    NativeGate -->|Chưa| Nfix[Sửa mốc native còn thiếu, kiểm lại]
    Nfix --> M7
    NativeGate -->|Đạt| U1[U1: Release và manifest có chữ ký]
    U1 --> U2[U2: Nút Update và maintenance]
    U2 --> U3[U3: Backup, validation và recovery]
    U3 --> U4[U4: Nghiệm thu Update trên Docker và native]
    U4 --> UpdateGate{Update và recovery đạt?}
    UpdateGate -->|Chưa| Ufix[Sửa checkpoint Update, kiểm lại]
    Ufix --> U4
    UpdateGate -->|Đạt| R0[R0: Phỏng vấn Android và chốt spec bảo mật]
    R0 --> R1[R1: Spike LAN, relay miễn phí và E2E]
    R1 --> Rgate{Khả thi trong ngân sách 0 phí?}
    Rgate -->|Chưa| Rhold[Ghi giới hạn, hỏi user đổi phạm vi; chưa phát hành remote]
    Rgate -->|Có| R2[R2: Remote gateway, QR và Android chat]
    R2 --> R3[R3: Kiểm thử quyền, mất mạng, thu hồi và pilot]
    R3 --> Future[C1-C2 và A-cloud theo cổng, ưu tiên riêng]
~~~

Flow là thứ tự ưu tiên hiện tại, không phải tự động cho phép agent chạy hết mọi nhánh. Sửa lỗi luôn quay lại checkpoint gây lỗi và chạy lại ca bị ảnh hưởng. D4, M7/native gate và U4 là điểm nghiệm thu; không tự tick bằng kết quả backend hoặc bỏ qua để mở phần tiếp theo.

### 13.2 Cách làm từng bước

1. **D1:** Tạo build tái lập và bundle runtime; chứng minh không phụ thuộc môi trường developer.
2. **D2:** Làm ownership/profile/gateway trước khi mở cửa sổ app; bảo đảm API và panel đều kết nối đúng backend.
3. **D3 → D4:** Có installer alpha, UI/chức năng tương tự web và vẫn dùng Docker. User kiểm thử app thật; chưa thêm nút Update, QR, Android hoặc native trong đợt này.
4. **MC0 khi có blocker:** Lập phần bổ sung cho Configuration/tài nguyên/vòng đời môi trường. Không giải quyết lỗi installer bằng host fallback ngầm. Configuration nhiều backend hội tụ vào M1–M7.
5. **M1 → M7:** Sau D4 làm routing, native core, runtime/job, browser, screen/selector/control, enforcement và pilot. Đọc chi tiết §1–12; không tick native trọn chỉ bằng shell hoặc capture chạy được.
6. **Native gate:** Nghiệm thu native theo §13.4; còn mốc/capability bắt buộc chưa đạt thì tiếp tục native, chưa làm Update/Android.
7. **U1 → U4:** Sau native gate làm release có xác thực, Update/maintenance, recovery và nghiệm thu tương thích Docker/native. Không phát hành nút Update chạy chuỗi shell/Git.
8. **R0 → R1:** Sau U4 phỏng vấn Android còn thiếu và kiểm chứng kết nối miễn phí. §18 chưa phải spec đủ để bắt đầu code.
9. **R2 → R3:** Chỉ làm Android/QR sau khi kiến trúc/quyền/crypto đã chốt và spike đạt. Pilot một PC/một điện thoại.
10. **C1/C2, A-cloud:** Thực hiện theo cổng/ưu tiên riêng; giữ roadmap đã có. Đây khác remote chat với PC và khác native B.

### 13.3 Điểm dừng và quy tắc tick

- Đã viết code không đồng nghĩa đạt nghiệm thu. Mỗi checkpoint có trạng thái: not_started, in_progress, blocked, ready_for_user_test, accepted.
- Có evidence kỹ thuật nhưng chưa có acceptance thì D4/M7/U4/R3 vẫn chưa accepted. Native gate chưa đạt thì U1–U4/R0–R3 đều not_started.
- Khi blocked, ghi điều kiện chặn và checkpoint tiếp tục được; không tự đổi provider, mode máy hoặc dịch vụ trả phí để vượt qua.
- Ghi rõ nhánh, commit và profile/container/workspace của từng lần chạy; không dùng dữ liệu thật hay sửa checkout khác để làm đẹp kết quả.
- Khi hết context/token hoặc chuyển agent, cập nhật §19 và bảng handoff trước khi dừng.

### 13.4 Cổng bắt buộc: native trọn vẹn trước các phần sau

Native hoàn chỉnh ở đây là hướng B trong §1–12, không phải chỉ bỏ Docker khỏi launcher:

- M1–M7 hoàn tất, có bằng chứng kiểm tra và người dùng xác nhận; giữ Docker regression.
- Windows/macOS/Linux mục tiêu được nghiệm thu độc lập theo support matrix; Linux phân biệt Ubuntu GNOME/KDE, Wayland/X11. Chưa chạy OS nào phải ghi chưa đạt, không lấy Windows thay chứng minh.
- File/read-write/workspace, editor/diff/IDE host, runtime Conda/Python/Java/shell, jobs/cancel/reconcile và memory/artifact routing hoạt động đúng máy.
- Managed/personal browser, Machine screen, Select Element, source/geometry mapping và view/control/Stop/revoke đạt; fallback region phải phản ánh giới hạn thật.
- Quyền native, bridge transport, secret boundaries, mode restrictions, custom command/delegation/engine audit, automation và migration/rollback đã qua ca bắt buộc.
- Chức năng/capability bắt buộc chưa đạt hoặc lỗi nghiêm trọng còn mở không được gọi là native hoàn chỉnh. Các giới hạn OS thực sự phải có evidence và được user chấp nhận rõ; nhãn experimental không tự mở gate.
- C1/C2 guest Linux và A-cloud là các hướng khác, chưa là điều kiện của gate native B. Desktop installer ba OS cũng là phạm vi riêng; Windows app trước không được khai là đã đóng gói macOS/Linux.

Chỉ sau gate này mới bắt đầu U1. Nếu được user thay đổi thứ tự về sau, ghi quyết định thay thế trong tài liệu trước khi đổi flow.

## 14. Quyết định Desktop/Update/Android và các giới hạn

### 14.1 Quyết định người dùng đã xác nhận

| Chủ đề | Quyết định mới |
|---|---|
| Ưu tiên mới nhất | Desktop như web/vẫn Docker → native hoàn chỉnh M1–M7 → Update → Android/QR và phần sau |
| Desktop đợt đầu | Windows alpha; UI/chức năng tương tự web, chỉ đóng gói vào app và kiểm thử |
| Backend đợt đầu | Docker hiện tại; sau Desktop làm đầy đủ native/mode máy trước Update/Android |
| Thiếu Docker ở máy user mới | Chưa giải quyết trong alpha; cần Machine Configuration/onboarding trước phát hành rộng |
| Đóng cửa sổ | Tiếp tục chạy ở khay hệ thống |
| Nguồn cập nhật | Bộ cài release đã build từ tag/commit xác định, do user chủ động phát hành |
| Agent đang bận | Cho tải update; chờ rảnh và xác nhận restart mới cài |
| Remote | LAN và Internet; hướng QR + dịch vụ chuyển tiếp BoxFox đã chọn, chưa triển khai hạ tầng |
| Thiết bị | Một PC ↔ một điện thoại |
| Android | Chat, session, tiến độ, plan, interview/decision và quản lý agent; không stream desktop/IDE/terminal ở v1 |
| Quyền điện thoại | Có thể duyệt thực thi, xác nhận từng lần |
| QR | Ghép Android với máy BoxFox, chưa làm đăng nhập tài khoản cloud |
| Thông báo | User bật/tắt trong Settings; chỉ cân nhắc dịch vụ miễn phí |
| Kinh phí | Chưa có ngân sách thuê server/domain hoặc dịch vụ trả phí |
| Branch | B; không sửa main |

### 14.2 Mặc định kỹ thuật của bản alpha

Các lựa chọn sau là thiết kế đề xuất của agent để làm bản alpha cụ thể, không gán ngược thành câu trả lời của người dùng:

- Electron/TypeScript, React build production, NSIS per-user Windows x64.
- Bundle Node 24 và CPython 3.13 cùng dependency đã khóa; khóa patch tại D1 theo bản hỗ trợ có Windows binary và kiểm chứng tương thích.
- Profile/container/volume mới, độc lập với bản localhost. User nói dữ liệu có thể tương tự hoặc mới; chọn profile sạch để tránh tác động dữ liệu đang dùng. Import chưa thuộc alpha.
- Tải image build sẵn theo digest ở lần đầu; không nhúng image lớn vào installer. Chưa cam kết bộ cài offline.
- Khởi động cùng Windows mặc định tắt, có tùy chọn bật.
- Update thuộc giai đoạn sau native; khi triển khai sẽ check/tải/cài theo thao tác user, không tự cài trên quit hoặc theo mỗi commit.
- Chưa mua chứng thư Authenticode. Manifest release có chữ ký riêng; không gọi chữ ký đó là chứng thư publisher Windows.

### 14.3 Tài nguyên và Machine Configuration cần nối tiếp

Compose hiện không có mem_limit/cpus/quota disk riêng; workspace dùng named volume. Tài nguyên Docker thực tế phụ thuộc Docker Desktop/WSL, disk engine và dung lượng ổ host. Chưa đo runtime hoặc xác định nguyên nhân thiếu dung lượng trên máy user; không kết luận BoxFox đang cấp một quota cụ thể chỉ từ code.

Sandbox mặc định tắt egress; cài package cần Internet có thể bị chặn. Package/môi trường cài ở writable layer có thể mất khi recreate container, dù workspace volume còn.

**MC0 — phần kế hoạch bổ sung, chưa implementation:**

- Phân biệt host RAM/disk, tài nguyên VM/WSL, giới hạn container, image/layer và workspace volume.
- Khảo sát workload thật và nhu cầu cài môi trường; đo baseline trước khi đề xuất quota.
- Phỏng vấn dung lượng, vị trí lưu disk/workspace, runtime cần giữ và chấp nhận cài Docker của user mới.
- Chốt vòng đời runtime/package, nâng cấp image, backup, migration và rollback để không làm mất môi trường.
- Đề xuất Configuration hiển thị/cấp tài nguyên theo backend; nêu giới hạn OS và quyền thay đổi Docker/WSL.
- Liên kết với routing/binding/capability ở §4–8; không tự đổi hạn mức WSL toàn máy trong đợt đóng gói.

Nếu thiếu tài nguyên làm Desktop Docker không chạy được, xử lý MC0 trước D4. Sau D4 vẫn phải hoàn tất native M1–M7 theo quyết định mới; không mở Android chỉ vì Docker alpha chạy được. Resource/môi trường nâng cao hội tụ vào kế hoạch Configuration trước phát hành cho user mới.

## 15. Thiết kế Desktop alpha

**Phạm vi đợt đầu:** chuyển BoxFox web hiện tại thành cửa sổ app Windows, giữ UI/chức năng và backend Docker. Runtime bundle/supervisor/gateway/installer là phần cần để app hoạt động; không redesign layout/chat/panel, đổi model/provider hoặc thêm tính năng sản phẩm Update, QR, Android hay native ở đợt này. Thiết kế các phần sau vẫn lưu để handoff, chỉ code khi tới gate tương ứng.

### 15.1 Stack và trách nhiệm

| Thành phần | Lựa chọn | Trách nhiệm |
|---|---|---|
| Shell | Electron + TypeScript | Window/tray/lifecycle và IPC; update manager bổ sung sau native |
| UI | React/Vite production hiện tại | Giữ luồng chat/plan/decisions/panel; không chạy Vite dev server |
| Installer | electron-builder stable v26, NSIS per-user | Cài runtime/app theo tài khoản, shortcut/icon/uninstall |
| Router | Node 24 runtime riêng | Tương thích node:sqlite và router hiện có |
| Harness | CPython 3.13 Windows x64 | Bundle Python, thư viện và tài nguyên runtime |
| Supervisor | Module first-party trong desktop | Ownership, config/ports, child process, health và maintenance |
| Gateway | HTTP/WebSocket localhost | Static UI và proxy production đến dịch vụ đúng profile |
| Sandbox | Docker image build sẵn | Tool/desktop Linux hiện tại, image digest và protocol version |
| Artifact alpha | Build từ commit xác định, bộ cài và image theo digest | Phục vụ user cài/kiểm thử; chưa có release feed/nút Update |

Electron phù hợp React/Node đang có. Tauri có thể giảm runtime trình duyệt nhưng vẫn cần Node/Python sidecar và thêm Rust/WebView2; chưa chọn cho alpha. Không coi phần shell desktop là giải pháp loại bỏ Docker hoặc giảm tổng tài nguyên khi chưa đo.

~~~mermaid
flowchart TB
    UI[React production trong Electron] --> Gateway[Gateway loopback]
    Main[Electron main] --> Supervisor[Host supervisor]
    Supervisor --> Gateway
    Supervisor --> Router[Node router]
    Supervisor --> Harness[Python harness]
    Harness --> Docker[Sandbox riêng của desktop alpha]
    Gateway --> Router
    Gateway --> Harness
    Gateway --> Panels[IDE, terminal, VNC và box API]
    Panels --> Docker
~~~

Sau native gate mới thêm UpdateManager vào Electron main (§16). Remote gateway/Android là giai đoạn riêng (§18), không có trong flow Desktop Docker đầu tiên.

Đường dẫn dự kiến tạo: desktop/ cho shell/supervisor/gateway/update/build configuration và .github/workflows/ cho pipeline. Đây chưa phải thư mục/code đã triển khai. Không đổi tên roadmap thành một plan mới độc lập; tracking nằm trong tài liệu này.

### 15.2 Khởi động, ownership và health

1. Lấy single-instance lock theo profile; mở lại app chỉ focus cửa sổ đang có.
2. Đọc config/recovery journal, kiểm tra runtime, thư mục và cổng.
3. Kiểm tra Docker đang hoạt động; thiếu thì hướng dẫn, không tự cài Docker/WSL hoặc hiện máy mock.
4. Lần đầu: đọc manifest image đã xác thực, hiển thị dung lượng, tải image theo digest, tạo sandbox riêng.
5. Khởi động router, harness và gateway với cấu hình profile cụ thể, process ẩn không bật terminal.
6. Kiểm health, instance ID, version và giao thức của từng dịch vụ.
7. Mở UI; chỉ cho nhận công việc khi backend cần thiết sẵn sàng. Lỗi một thành phần phải chỉ rõ thành phần đó.

Không dùng start.ps1 làm engine bản phát hành. Không tin một localhost health trả ok rồi tự coi service đó thuộc app. Giữ script phát triển hiện tại.

Chỉ dừng/khôi phục process/container có identity và label của app. Không kill theo cổng hoặc tên executable, không docker compose down của checkout khác.

### 15.3 Gateway production và cấu hình kết nối

Vite hiện proxy API; một số panel dùng URL localhost cố định. Gateway desktop phải hỗ trợ API harness/router, box API, IDE HTTP/WS, terminal WS, VNC WS và streaming. Chỉ bọc UI trong BrowserWindow chưa đủ.

- Frontend nhận cấu hình runtime/capability lúc chạy; chế độ web giữ cấu hình hiện có.
- Lần đầu chọn bộ cổng loopback còn trống và lưu profile. Lần sau giữ cổng để origin/cấu hình container ổn định.
- Cổng bị chiếm báo conflict và hướng dẫn; không kill service khác, không tự đổi cổng rồi recreate máy mất môi trường.
- Allowlist Host/Origin/CSP/WS theo cấu hình cụ thể; không mở wildcard hoặc tắt webSecurity.
- Container name/api URL/ports inject từ config desktop vào SandboxExecutor và UI transport; không dùng agentbox-box toàn cục cho alpha mới.
- Không mount đường dẫn checkout developer vào bản cài. Image/bundle phải chứa skill, worker và static asset cần thiết.

### 15.4 Quyền Electron và API

- Renderer sandbox/contextIsolation bật, nodeIntegration tắt. Main/preload chỉ expose interface có phạm vi.
- Validate IPC sender/frame chính. IDE iframe, website, Markdown và tên file là dữ liệu; không có IPC quản trị.
- Shared secret sandbox và model key giữ ở backend/supervisor; không bake dev token thành quyền production trong VITE_*.
- Gateway xác thực theo instance; API dùng token cấp cho frame chính qua preload, kiểm origin và chống CSRF. Không cấp token quản trị cho iframe.
- IDE/VNC/terminal có quyền kết nối riêng, không được dùng credential đó để gọi API quản trị. WebSocket/stream cũng phải qua kiểm quyền phù hợp.
- Model/custom command/delegate không được gọi install/update hoặc truyền shell command cho supervisor.
- Giới hạn navigation/new windows; openExternal chỉ scheme/URL hợp lệ qua hành động user.

Nguồn: [Electron security](https://www.electronjs.org/docs/latest/tutorial/security), [Tauri sidecar](https://v2.tauri.app/develop/sidecar/).

### 15.5 Dữ liệu và bộ cài

~~~text
%LOCALAPPDATA%/BoxFoxDesktopAlpha/
  profile/
    harness/
    router/
    ui/
    machine.json
    desktop-settings.json
  updates/
  recovery/
  logs/
~~~

- Profile UI ổn định qua update. Harness DB, router DB và khóa router đi cùng profile; giữ cơ chế mã hóa/ACL hiện có.
- Container/network/volume mang identity riêng. Workspace volume giữ bền; không dùng chung volume dev mặc định.
- Không tự import localStorage/SQLite/workspace cũ. Chưa triển khai import trong alpha.
- Tách dependency runtime/test; khóa phiên bản và bundle Python library/native DLL/resource cần thiết. Không dựa Conda/PATH/pip máy user.
- Build production frontend; không chạy npm install, pip install hoặc docker build khi mở app phát hành.
- Tải image lần đầu có tiến độ/lỗi/retry; các lần sau dùng image có sẵn. Model cloud vẫn cần mạng riêng.
- Uninstall mặc định giữ dữ liệu và volume. Không tự prune Docker hoặc xóa workspace.

### 15.6 Tray, Stop và diagnostics

Tray đợt Desktop có Mở BoxFox, Trạng thái dịch vụ và Thoát BoxFox. Chỉ thêm Update sau native gate/U2. X đóng cửa sổ nhưng giữ agent/supervisor. Autostart Windows là tùy chọn mặc định tắt.

Thoát khi bận cho chọn giữ chạy nền hoặc yêu cầu dừng có kiểm soát. Không báo checkpoint đã lưu khi chưa lưu thật; không kill công việc ngầm để qua update. Crash/restart phải hiện trạng thái gián đoạn; không tự rerun công việc.

Diagnostics hiển thị version/commit, service health, Docker/container/image identity, tình trạng disk và log đã scrub. Đợt này đo/hiển thị tài nguyên, chưa thêm slider cấp RAM/CPU/disk.

## 16. Nút Update, release và phục hồi

**Giai đoạn sau native M1–M7:** toàn bộ §16 chỉ triển khai khi native gate ở §13.4 đạt. Đợt Desktop Docker đầu không expose nút/IPC update. Khi làm Update phải kiểm cả Docker và native, không chỉ giả định một SandboxExecutor cố định.

### 16.1 UX và interface

Thêm Settings → About & Updates: version/commit hiện tại, release mới, notes/dung lượng, Kiểm tra cập nhật, Tải cập nhật, Cài và khởi động lại, trạng thái chờ công việc và lỗi cụ thể. Tray mở cùng luồng.

| IPC đề xuất | Hành vi |
|---|---|
| desktop.getStatus() | Version và health dịch vụ |
| desktop.getRuntimeConfig() | Endpoint/capability UI; không trả secret quản trị |
| desktop.checkUpdate() | Kiểm tra release của kênh alpha được phép |
| desktop.downloadUpdate(releaseId) | Tải đúng release đã kiểm tra |
| desktop.installUpdate(releaseId) | Kiểm tra lại và vào maintenance |
| desktop.subscribeStatus() | Stream status/progress |

UI không gửi URL tùy ý, command shell hoặc installer path. Main resolve release/artifact từ manifest đã xác minh. Desktop IPC không trở thành tool model hoặc endpoint remote Android.

### 16.2 Artifact và trust

Release gồm Windows x64 installer, release.json/chữ ký Ed25519, version/commit, size/SHA-256 artifact, schema compatibility, runtime/dependency manifest, licenses và release notes. Compatibility khai theo backend: image digest/sandbox protocol cho Docker; Host Bridge/helper/policy protocol và OS/architecture cho native. Không ép native phải có Docker image. macOS/Linux installer/update có gate riêng, không nhận artifact Windows.

- Ký đúng bytes UTF-8 của release.json; verify trước khi dùng trường trong file. Không tự tạo canonicalization phức tạp.
- App chứa public key. Private key ngoài repo, chỉ cấp bước phát hành đã được phép; không cấp workflow PR không tin cậy.
- Chỉ download HTTPS từ nguồn release được cấu hình sẵn; validate URL/redirect, size/hash và nền tảng.
- Thiếu/sai chữ ký, hash hoặc manifest không hợp lệ: fail closed; bản đang dùng còn hoạt động.
- Chưa mua Authenticode; chữ ký manifest xác thực update nhưng không thay nhận diện publisher của Windows. First install alpha cần lấy từ release bạn đã xác minh.
- Không phụ thuộc signed-manifest tích hợp electron-builder v27: tài liệu tại đợt khảo sát ghi v27 chưa phát hành. Dùng stable v26 cho NSIS và Node crypto chuẩn cho manifest BoxFox.
- Không chạy git pull/reset, npm install/pip install/docker build hoặc script do release notes/model sinh trên máy user.

Nguồn: [Signed update manifests và trạng thái v27](https://www.electron.build/docs/features/signed-update-manifests/). Cần kiểm lại version hỗ trợ tại D1, không giả định tính năng next là stable.

### 16.3 State và thứ tự update

~~~text
idle → checking → available → downloading → verified
     → waiting_for_idle → ready_to_install → maintenance
     → installing → validating → completed

error / recovery_required là trạng thái riêng, lưu bền.
~~~

1. User check và chọn tải; agent vẫn làm trong lúc tải.
2. Tải vào staging, kiểm chữ ký/hash; chưa cài.
3. Kiểm toàn bộ tác vụ có thể mutate trên máy đã bind: model turn, delegated job, terminal/job/PTY, automation, browser/control action và thao tác ghi dữ liệu. Pending workflow cần bảo toàn, không tự approve/execute khi khởi động lại. Native phải release input/held keys và không khôi phục grant/ref hết hiệu lực ngầm.
4. Rảnh thì cho user xác nhận restart; không tự cài ngay khi rảnh hoặc khi đóng cửa sổ.
5. Lấy maintenance lock, chặn nhận chat/delegation/automation mới và kiểm lại busy dưới khóa để tránh race.
6. Đóng dịch vụ có kiểm soát; backup nhất quán; ghi journal trước mutation.
7. Recovery helper chạy executable installer đã verify với argv cố định. Không ghép command string từ dữ liệu user/model.
8. Khởi động bản mới ở chế độ chưa nhận công việc; validate health, schema, gateway và backend compatibility theo binding. Docker kiểm sandbox; native kiểm Bridge/helper/grant/epoch và không fallback sang Docker.
9. Thành công mới commit trạng thái và mở nhận công việc. Không tự chạy lại task cũ chưa idempotent.

Check/download/install dùng invocationId, trạng thái bền và single-flight lock. Double-click/retry không tạo hai installer. Lỗi network không giữ maintenance, không làm dừng bản hiện tại.

### 16.4 Backup, rollback và môi trường Docker

- Backup gồm harness/router SQLite nhất quán, khóa credential đi kèm, desktop config và UI profile. Flush/close hoặc backup API đúng; không copy SQLite đang mở mà bỏ WAL.
- Giữ installer trước đã xác thực và recovery helper/runtime ngoài thư mục bị NSIS thay thế.
- Bản mới validation fail trước khi nhận công việc: đóng bản lỗi, giữ dữ liệu/log lỗi, khôi phục installer và snapshot trước update; mở lại bản trước.
- Không ghi đè mất dữ liệu của lần chạy lỗi. Journal lưu release IDs/hashes, backup locator, stage và failure để agent/user biết đang dở đâu.
- Mất điện giữa install: có recovery độc lập và hướng dẫn cài lại bản trước. NSIS không được coi là atomic; phải kiểm tình huống ngắt thực tế.
- App update không recreate sandbox mặc định. Release phải tương thích image/protocol hiện tại; cần đổi image/migration thì báo NEEDS_MACHINE_MIGRATION, giữ bản đang dùng.
- Không gọi giữ workspace là đã giữ toàn bộ môi trường: runtime/package writable layer còn phải giải quyết ở MC0.
- Với native, không xóa/chép đè workspace, Conda/JDK hoặc user environment; chỉ nâng cấp app/helper thuộc BoxFox. Đối chiếu native job ownership sau restart, không dùng PID cũ để kill nhầm. Revoke/expiry/input lease phải giữ đúng qua update/recovery.

### 16.5 Pipeline phát hành và chi phí

Build từ tag/commit được chọn trên B → frontend/runtime/image/installer → manifest/signature → draft release → user kiểm thử → user publish. Chỉ release đã publish của kênh alpha được cấu hình mới tới app. Không phát hành mỗi commit tự động hoặc tự merge main.

Pin image bằng digest, không dùng agentbox-sandbox:latest làm version contract. Image GHCR phải được cấu hình public để máy kiểm thử không cần credential GitHub cho pull.

Standard GitHub Actions runner cho repo public hiện có thể dùng miễn phí; artifact storage/quota phải theo dõi riêng, không bật dịch vụ tính phí để qua pipeline. Chưa chạy CI hoặc publish release trong đợt viết tài liệu này.

Nguồn: [GitHub Actions billing](https://docs.github.com/en/actions/concepts/billing-and-usage), [GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).

## 17. Checkpoint và nghiệm thu Desktop/Update

### 17.1 Bàn giao theo checkpoint

| Mã | Bàn giao | Điều kiện tick accepted |
|---|---|---|
| D0 | Khảo sát/phỏng vấn/gộp roadmap | Quyết định, căn cứ và thứ tự lưu; không khai code đã làm |
| D1 | Build tái lập/runtime/resources | Không cần Node/Python/Conda/source checkout trên máy kiểm thử; lock/manifest/license đủ |
| D2 | Supervisor/gateway/profile | Ownership đúng; production HTTP/WS/panel hoạt động; profile/ports không đụng dev |
| D3 | Installer/window/tray | NSIS per-user, shortcut/icon/tray/shutdown/diagnostics; các chức năng chính dùng backend thật |
| D4 | User acceptance Desktop Docker | UI/chức năng tương tự web, Docker đúng; chưa cần Update/Android/native để tick |
| MC0 | Kế hoạch tài nguyên/môi trường khi cần | Có khảo sát/đo/phỏng vấn và thiết kế migration/resource; không tự coi mọi issue là RAM |
| M1–M7 | Native hoàn chỉnh | Chi tiết §9–12; đạt native gate §13.4 và user acceptance trước U1 |
| U1 | Release có xác thực sau native | Draft từ commit xác định, chữ ký/hash/compatibility Docker/native; tamper bị từ chối |
| U2 | Update UI/maintenance | Tải khi bận, cài khi rảnh có xác nhận; admission race và duplicate không bypass |
| U3 | Backup/validation/recovery | DB/key/UI/native grants/job state đúng; recovery không làm mất môi trường/user files |
| U4 | Nghiệm thu Update | CUA/recovery trên backend Docker/native thật; user xác nhận trước Android |
| R0 | Spec Android sau native và Update | Chốt framework/OS/distribution/auth/crypto/quyền/reconnect còn thiếu |
| R1 | Spike remote miễn phí | LAN/4G, reachability/E2E/quota/latency và revoke đã kiểm chứng |
| R2 | Android/QR/remote gateway | Theo spec đã chốt sau R0/R1; không expose toàn localhost |
| R3 | Android pilot | Một PC/phone; quyền, loss/replay/revoke/notifications kiểm trên máy thật |

### 17.2 Kiểm tra xác định cho coding agent

**D1–D4 — kiểm Desktop Docker trước native:**

- [ ] Runtime không phụ thuộc hardcoded Conda/PATH/source directory; PDF/skill/worker/static asset load đúng trong bundle.
- [ ] Production không dùng Vite dev server, không cài dependency hoặc build image lúc khởi động.
- [ ] Streaming/IDE/terminal/VNC/box API dùng đúng endpoint và origin; không sửa bằng webSecurity off/CORS wildcard.
- [ ] Single-instance/process/container identity đúng; cổng occupied không kill hoặc reuse service khác.
- [ ] Desktop profile và checkout dev cùng tồn tại không dùng chung DB/volume/secret.
- [ ] X giữ job; explicit quit có stop/interrupt thật; restart không tự chạy lại job.
- [ ] Provider secrets không có trong renderer bundle, logs hoặc task env.
- [ ] Model/custom command/iframe không gọi được IPC admin; Desktop chưa expose IPC/nút Update.
- [ ] Session/decision/plan còn sau restart; chờ approval không biến thành execution.
- [ ] Uninstall không xóa workspace/dev container hoặc prune Docker.
- [ ] UTF-8/tên Việt/đường dẫn có space giữ đúng qua installer, logs, dữ liệu và export.

**M1–M7 — kiểm native trước Update:** dùng toàn bộ §10–11 và gate §13.4, theo từng OS/backend. Các ca này không được bỏ qua vì Desktop Docker đã đạt.

**U1–U4 — chỉ kiểm khi đã qua native gate:**

- [ ] Provider secrets không có trong update manifest; model/iframe/remote không gọi được IPC update.
- [ ] Session/decision/plan còn sau update; grant/ref/revocation không được khôi phục ngầm.
- [ ] Download/install duplicate chỉ một invocation; maintenance chặn tác vụ mới kể cả automation.
- [ ] Manifest/signature/hash/platform/compatibility lỗi bị chặn; không retry vô hạn hoặc fallback unsigned.
- [ ] Backup DB/master key/UI nhất quán; rollback phục hồi đúng phiên bản và dữ liệu.
- [ ] Crash/mất điện ở các stage có journal/recovery; không tuyên bố NSIS atomic.
- [ ] App update giữ container/volume/package; incompatible image trả NEEDS_MACHINE_MIGRATION.
- [ ] Native update không sửa Conda/JDK/user environment hoặc fallback Docker; reconcile/cancel đúng owned process tree, release input lease.
- [ ] Backend capability/permission/bridge/helper incompatibility chặn install hoặc validation; không tự nâng quyền.

### 17.3 Checklist CUA/user theo giai đoạn

**Chưa thực hiện CUA.** Agent khác hoặc người dùng kiểm thử và ghi version/commit/Windows build/Docker/image/profile, ảnh hoặc video đã được cấp phép và log liên quan. Không dùng kết quả test backend thay cho UI acceptance.

**D4 — nghiệm thu giao diện app tương tự web, Docker hiện tại:**

| Thao tác | Output đúng |
|---|---|
| Cài Windows 11 x64 không có Node/Python | App dùng runtime bundle; không yêu cầu mở terminal |
| Docker chưa chạy | Chỉ rõ Docker unavailable và cách khởi động; không hiện sandbox giả |
| Tải image lần đầu, ngắt mạng | Có size/progress/error/retry; không báo ready khi pull chưa thành công |
| Khởi động lần sau | Dùng image có sẵn, không npm/pip install/docker build |
| Chạy bản web dev đồng thời | Không tranh DB/container/ports; conflict báo rõ, không kill |
| Chat/tool/Plan/Decisions | Backend thật, status đúng; phiên/phỏng vấn/history còn sau reload |
| IDE/terminal/VNC/Select Element | Kết nối đúng sandbox; selector đúng nguồn/toạ độ và Add to Chat giữ dữ liệu |
| X khi job đang chạy | Window đóng, tray còn và job tiếp tục |
| Mở app thêm lần nữa | Focus instance đang chạy; không thêm agent/container |
| Thoát khi đang có tác vụ | Chọn giữ nền/dừng rõ; status phản ánh dừng/gián đoạn thật |
| Restart sau tạo file/env fixture | File/session/key/UI và package trong container không mất |
| Kiểm tra menu/settings/tray | Chức năng web cũ còn; chưa có tính năng Update/QR/native hoạt động sớm |
| Uninstall alpha | Giữ data/volume theo chính sách; checkout/dev sandbox không bị tác động |

**M7 — native trọn:** thực hiện bảng §11 cùng fixtures §10; ghi kết quả từng nền tảng và user acceptance trước U1.

**U4 — nghiệm thu Update sau native:** chạy trên cả Docker và native; Docker-specific check chỉ áp dụng Docker, native có ca riêng.

| Thao tác | Output đúng |
|---|---|
| Check update không có release mới | Báo phiên bản hiện tại; không tạo installer/download giả |
| Tải update khi agent bận | Tải được; cài disabled/chờ có lý do; job không dừng |
| Cài khi rảnh | Xác nhận restart; version mới chỉ nhận việc sau validation |
| Double-click Tải/Cài | Một invocation và một installer |
| Sửa manifest hoặc artifact fixture | Từ chối chữ ký/hash; app cũ dùng được |
| Release yêu cầu image mới | Báo cần nâng cấp Machine; sandbox/môi trường hiện tại giữ nguyên |
| Startup bản mới thất bại | Có recovery; đúng installer/profile/key/DB trước được khôi phục |
| Ngắt install/reboot fixture | Journal và đường recovery không phụ thuộc app exe đang hỏng |
| Restart/update sau tạo file/env fixture | File/session/key/UI và package trong container không mất |
| Native update sau tạo host file/Conda/JDK fixture | User files/environment giữ nguyên; job/permissions/binding phản ánh đúng, không chuyển Docker |
| Update trong lúc native đang có input/job/browser action | Tải được; cài chờ idle, maintenance/Stop/release input đúng; không chạy song song |
| Native helper/protocol không tương thích | Chặn hoặc recovery; không báo thành công bằng health của Docker |

### 17.4 Đo tài nguyên và cổng phát hành

So cùng workload giữa web baseline và Desktop: idle/startup/chat/tool/IDE/VNC/job dài. Ghi riêng Electron/router/harness/Docker CPU/RAM, startup time, installer/image/disk size và network download. Chưa có số đo hoặc ngưỡng được chứng minh; không hứa app nhẹ hoặc đủ tài nguyên bằng con số tự đặt.

Đạt Desktop D4 cần ownership/dữ liệu/quyền và UI/chức năng Docker tương tự web; chưa yêu cầu updater hoặc native ở D4. M7 yêu cầu gate native §13.4. U4 kiểm update/recovery trên backend thật sau native. Không lấy trung bình bù lỗi nghiêm trọng. Phát hành cho user mới cần onboarding/resource/machine; đạt D4 không tự coi đã đạt native hoặc installer mọi OS.

## 18. Android Remote sau khi native hoàn chỉnh và Update được nghiệm thu

**Gate:** R0 chỉ bắt đầu sau D4, M1–M7/native gate và U4. Các ý tưởng/source/ca kiểm tra dưới đây được giữ để không mất context; không phải lệnh làm Android sớm. Remote chọn đúng backend/binding đã nghiệm thu, không cố định Docker hoặc mở rộng quyền native bằng credential ghép QR.

### 18.1 Căn cứ Happy và vai trò relay

Repo Happy khảo sát tại commit 4cf54d18488cba4787cc251cc37010f31125af29. CLI có server URL mặc định; mobile/CLI/daemon dùng API/socket server để sync và RPC. Agent chạy ở PC: PC tắt thì không làm công việc mới, nhưng điều đó không chứng minh remote không có server.

QR Happy sử dụng khóa tạm và response auth; client mã hóa message/metadata/RPC trước gửi. Học mô hình này, không bê nguyên account/shared-key/protocol thành quyền thiết bị của BoxFox hoặc coi nhãn E2E là đã qua audit.

Nguồn: [Happy backend](https://github.com/slopus/happy/blob/4cf54d18488cba4787cc251cc37010f31125af29/docs/backend-architecture.md), [cấu hình CLI](https://github.com/slopus/happy/blob/4cf54d18488cba4787cc251cc37010f31125af29/packages/happy-cli/src/configuration.ts), [QR](https://github.com/slopus/happy/blob/4cf54d18488cba4787cc251cc37010f31125af29/packages/happy-cli/src/ui/auth.ts), [mã hóa](https://github.com/slopus/happy/blob/4cf54d18488cba4787cc251cc37010f31125af29/docs/encryption.md).

~~~text
Android ⇄ Relay chuyển nội dung mã hóa ⇄ Remote gateway trên PC ⇄ Harness
                                         Agent và key model ở PC
~~~

Remote gateway khác desktop localhost gateway: expose allowlist tác vụ, có danh tính/quyền thiết bị và audit. Không proxy mọi port/API của máy; không expose router secrets, update/admin, IDE, terminal, VNC hoặc Docker daemon ở Android v1.

### 18.2 Phạm vi/quyền đã chốt và nguyên tắc đề xuất

- Một PC/một điện thoại; QR ghép thiết bị với PC, không làm account cloud login.
- Android xem session/chat/progress/plan, gửi yêu cầu, trả lời interview/decision và dừng agent.
- Duyệt thực thi mỗi lần hiển thị action/plan version/hash liên quan; grant không suy từ việc đã ghép QR.
- QR không chứa provider key/credential lâu dài; đề xuất expiry, single-use, khóa tạm và PC confirmation.
- PC quản lý/thu hồi thiết bị. Revoke làm mất quyền và kết nối đang mở; re-pair không tự phục hồi approval cũ.
- Nội dung E2E giữa PC/Android; relay chỉ chuyển ciphertext. Metadata/traffic/availability vẫn là giới hạn cần công bố.
- Dùng crypto/protocol/library đã kiểm chứng, không tự dựng thuật toán. Lựa chọn cụ thể phải chốt tại R0/R1 trước code.
- Request ID/dedup, event cursor/replay và decision revision; stale decision báo conflict, không đoán user đã approve.
- PC sleep/offline báo rõ. Không queue rồi tự phát lại execution/approval khi online; có thể giữ bản nháp để user gửi lại chủ động.
- Concurrent chat/local approval/remote approval phải hội tụ cùng harness và trạng thái; không có nguồn quyền riêng trong Android UI.
- Hai endpoint outbound khi dùng relay; LAN direct cùng auth semantics, không mở harness hiện tại ra 0.0.0.0.

### 18.3 Ứng viên hạ tầng miễn phí và thông báo

Chưa có server/domain và user không có ngân sách trả phí. **Ứng viên để spike**, chưa phải kiến trúc production đã chứng minh: Cloudflare Workers Free + Durable Objects SQLite, endpoint workers.dev, WebSocket hibernation phù hợp để giảm tài nguyên.

Durable Objects hiện có Free tier; vượt quota làm operation thất bại. Cần đo chat event batching, reconnect, presence, abuse limit và quota trước chọn. Không hứa miễn phí vô hạn hoặc 24/7. Không đăng ký Paid plan hoặc tự mua domain để vượt blocker.

Nguồn: [Durable Objects pricing](https://developers.cloudflare.com/durable-objects/platform/pricing/), [workers.dev](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/).

Firebase Cloud Messaging được liệt kê no-cost; có thể thêm khi Android bắt đầu. Chỉ cấu hình phần miễn phí, không mặc định bật Cloud Functions/hosting trả phí. Thiết bị có Google Play Services hay không chưa được xác nhận; phải kiểm tại R0.

- Thông báo mặc định tắt, Settings bật mới xin quyền OS; tắt không làm mất remote khi app mở.
- Không gửi chat/code/key vào push; thông báo chung mở app để lấy nội dung đã xác thực.
- Nếu không có GMS hoặc app bị force-stop/OS hạn chế nền, UI nói rõ khả năng nhận thông báo; không hứa WebSocket luôn sống khi app đóng.

Nguồn: [FCM pricing](https://firebase.google.com/pricing), [FCM Android](https://firebase.google.com/docs/cloud-messaging/android/get-started).

### 18.4 Phỏng vấn/spec còn thiếu trước implementation Android

R0 phải chốt framework Android, min OS/device, APK distribution/update/signing key, khóa app/biometric, cách quản lý danh tính/khóa/khôi phục, exact pairing/expiry/revoke, remote action allowlist, crypto transport, relay ownership/abuse/quota và event/command failure semantics.

Không hỏi user chọn thuật toán/db khi chưa có cơ sở; agent nghiên cứu và trình phương án/đánh đổi. R1 có spike trên PC/Android 4G và LAN, ghi cấu hình/latency/cost/quota và kết quả. Không đạt trong ngân sách thì báo giới hạn và hỏi thay đổi phạm vi; không tự chuyển sang dịch vụ trả phí hoặc expose port.

### 18.5 Checklist Android/QR cho đợt sau

| Check | Output đúng |
|---|---|
| Quét QR mới và PC xác nhận | Đúng máy/đúng điện thoại, quyền hiển thị, không lộ key lâu dài |
| QR hết hạn/sử dụng lại | Từ chối, phải tạo mới |
| Gửi chat/answer khi LAN và 4G | Đúng session/question, có receipt/cursor và lưu lịch sử |
| Double-click/retry sau mất mạng | Không tạo hai turn hoặc duyệt hai lần |
| Plan/decision thay đổi khi phone đang mở | Cũ báo conflict, refresh nội dung, không approve nhầm |
| PC tắt/sleep/mất mạng | Offline rõ; không tự thực thi queued approval khi reconnect |
| Revoke điện thoại | Kết nối hiện tại và credential cũ không còn thực hiện action |
| Phone gọi secrets/update/IDE/VNC/terminal API | Không có capability và bị backend từ chối |
| Relay tamper/replay nội dung fixture | Endpoint từ chối; không thực hiện action |
| Relay hết quota hoặc unavailable | Báo degraded/offline, giữ dữ liệu host, không mở port/fallback thiếu auth |
| Bật/tắt/thay quyền notification | Settings/OS nhất quán; không có nội dung nhạy cảm trong push |
| Phone khóa/app đóng/force-stop fixture | Hành vi đúng khả năng OS, không hứa notification/connection không được kiểm chứng |

## 19. Tracking tổng và handoff cho agent tiếp theo

### 19.1 Tiến độ tại lần gộp tài liệu

- [x] Giữ roadmap ba hướng môi trường và checklist native/guest/cloud cũ.
- [x] Phỏng vấn Desktop/Update/Android và ghi quyết định mới/ý tưởng bị thay thế.
- [x] Khảo sát launcher/runtime/proxy/ports/data/Docker và tham khảo Happy tại commit đã ghi.
- [x] Gộp thiết kế Desktop/Update và roadmap Android vào chính file hiện tại trên B.
- [x] Thêm flow tuần tự, cổng user acceptance, prefix checkpoint riêng và expected output cho CUA.
- [x] Cập nhật quyết định mới nhất: Desktop như web/vẫn Docker → native trọn M1–M7 → Update → Android; gỡ thứ tự cũ và cập nhật gate/contract.
- [ ] D1 — Build/runtime tái lập.
- [ ] D2 — Supervisor/gateway/profile/ports.
- [ ] D3 — Installer/window/tray.
- [ ] D4 — Người dùng kiểm thử và chấp thuận Desktop Docker tương tự web.
- [ ] MC0 — Kế hoạch bổ sung tài nguyên/môi trường/onboarding khi cần.
- [ ] M1–M7 — Native hoàn chỉnh, chi tiết tại §12.2; hoàn tất trước U1.
- [ ] Native gate — Evidence từng nền tảng/capability và người dùng xác nhận (§13.4).
- [ ] U1 — Release/signature/backend compatibility sau native.
- [ ] U2 — Update UI/maintenance.
- [ ] U3 — Backup/validation/recovery.
- [ ] U4 — Nghiệm thu Update Docker/native trước Android.
- [ ] R0 — Phỏng vấn và chốt spec Android.
- [ ] R1 — Spike remote miễn phí và security transport.
- [ ] R2 — Android/QR/gateway theo spec đã chốt.
- [ ] R3 — Android pilot/acceptance.
- [ ] C1/C2/A-cloud — Hướng guest/cloud tương lai, cổng riêng tại §12.2.

Các tick trên chỉ xác nhận công việc tài liệu/khảo sát. Chưa có Desktop shell, runtime bundle, installer, updater, release pipeline, remote gateway, Android app hoặc kết quả test/CUA/benchmark của các phần mới.

### 19.2 Mẫu cập nhật sau mỗi checkpoint

| Checkpoint | Status | Branch/commit | File/artifact | Kiểm tra đã chạy + evidence | Lỗi/blocker | Việc tiếp theo |
|---|---|---|---|---|---|---|
| D0 | accepted cho tài liệu | B / baseline 8ffb82ad, bản tài liệu chưa commit | docs/plan/v1-machine-environments-roadmap.md | Đọc code, interview, đọc nguồn; chưa chạy test/CUA | Chưa implementation | Khi được giao code: D1 |
| D1 | not_started | — | — | Chưa chạy | — | Khóa build/runtime và tạo artifact |

Thêm hàng thật khi làm; không ghi test pass hoặc commit hash dự kiến. Nếu một mốc được tách cho nhiều agent, ghi owner và dependency; không có hai agent cùng sửa một nguồn quyền/gateway mà thiếu contract chung.

### 19.3 Chỉ dẫn tiếp tục

1. Đọc §13–19 để biết ưu tiên mới, rồi đọc §1–12 khi làm nhánh môi trường.
2. Kiểm AGENTS/instructions, branch/worktree/status; chỉ sửa B. Giữ thay đổi research-design-exploration-report.md của công việc khác.
3. Nếu được giao implementation hiện tại, bắt đầu D1; không tự quay về M1 chỉ vì nó nằm trước trong tài liệu.
4. Làm D1–D4 để Desktop như web/vẫn Docker, rồi M1–M7 để native trọn. Không làm U1 trước native gate; không làm R0 trước U4, không code R2 trước R0/R1. WSL/VM/cloud theo cổng riêng.
5. Lưu expected/actual, artifacts và blocker trong bảng; cập nhật checkbox khi đã nghiệm thu. CUA do người dùng/agent sau thực hiện, không tick từ suy đoán.
6. Khi dừng, ghi checkpoint đang dở, thao tác đã làm, files/commit, trạng thái dữ liệu/process và bước tiếp theo đủ để agent khác tiếp tục an toàn.
