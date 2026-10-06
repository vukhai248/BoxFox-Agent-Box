# Handoff — BoxFox Desktop alpha: hai chế độ chạy (máy người dùng / box Docker) + CUA

> **Đọc mục 2 (Bảng tiến độ) trước**, rồi làm tiếp việc chưa xong theo đúng thứ tự ở mục 6.
> Tài liệu này tự chứa: nó nói vòng này đang làm gì, đã xong tới đâu, chạm vào tệp nào, tên route nào,
> và lệnh nào để kiểm. Nó **không** thay thế các kế hoạch chi tiết ở mục 7 — chúng nằm trong repo.

Ngôn ngữ tài liệu: tiếng Việt, thuật ngữ kỹ thuật giữ tiếng Anh. Ngày viết: 2026-10-06.
Mốc xuất phát: `origin/main` = `8d45b45` (sau khi PR #3 — web search — được merge).

---

## 1. Bài toán và kết quả mong muốn

**Hiện trạng:** BoxFox chạy theo một kiểu duy nhất — harness trên máy chủ nhà, mọi công cụ thi hành
trong **box Docker** (code-server, terminal, desktop X11 ảo). Muốn dùng thật trên máy người dùng cuối,
phải cài Docker, và mọi thao tác đều nằm trong một môi trường ảo — người dùng không mở được app thật
của họ.

**Kết quả mong muốn:** một bản Desktop alpha chạy được **hai chế độ**:

| Chế độ | Thi hành ở đâu | Dùng khi |
|---|---|---|
| `docker` (mặc định) | box Docker như cũ | giữ nguyên hành vi hiện tại, không đổi một byte |
| `host` | **máy thật** của người dùng: tệp, lệnh, chuột, phím, màn hình | người dùng muốn agent làm việc trên chính máy họ |

Đi kèm host mode là **động cơ quyền** (luật `Tool(specifier)`, bốn tầng, sàn cứng) và **lớp điều khiển
desktop (CUA)**: chụp màn hình, soi phần tử, tiêm chuột/phím — có lease, epoch, mutex liên tiến trình
và thang xác minh.

**Điều vòng này KHÔNG làm:** không sandbox hoá tiến trình trên máy người dùng (agent có đúng quyền của
người dùng), không có bậc tiêm input thứ ba (`PostMessage`), không hỗ trợ DRM/HDR/đổi virtual desktop,
không có bản macOS/Linux của lớp CUA (chỉ Windows).

---

## 2. Bảng tiến độ

| Mã | Việc | Nhánh / commit | Trạng thái |
|---|---|---|---|
| H1 | Tài liệu thiết kế + hợp đồng + ADR-0002 | `vorflux/desktop-host-mode` @ `f242b0d` | **xong** |
| H2 | Động cơ quyền (`permissions.py`) | `vorflux/desktop-host-mode` @ `3da7f7f` | **xong** |
| H3 | `HostExecutor` (tệp + lệnh trên máy thật) | `vorflux/desktop-host-mode` @ `f242b0d` | **xong** |
| H4 | Chọn chế độ + 6 route quyền + khối `execution` của health | `vorflux/desktop-host-mode` @ `f242b0d` | **xong** |
| H5 | Nền tảng Windows: capture / input / UIA | `vorflux/desktop-host-mode` @ `ee1d79b` | **xong** |
| H6 | Select element ba nhánh (`dom → uia → desktop`) | `vorflux/desktop-host-mode` @ `ee1d79b` | **xong** |
| H7 | Lease / epoch / mutex / token / thang xác minh **+ ba công cụ CUA trong executor + API desktop** | `vorflux/desktop-host-mode` @ `b9e27cc` | **xong** |
| D1 | Khung Electron + bundle runtime | `vorflux/desktop-alpha` @ `fe46a70` | **xong** |
| D2 | Supervisor + gateway + profile | `vorflux/desktop-alpha` @ `fe46a70` | **xong** |
| D3 | Tray + chẩn đoán + bộ cài NSIS | `vorflux/desktop-alpha` @ `dee25ca` | **xong** |
| D4 | Tài liệu cài đặt + checklist nghiệm thu 13 bước | `vorflux/desktop-alpha` @ `9be9567` | **xong** |
| D5 | UI chọn chế độ + quyền + CUA (tab Settings "Machine & Permissions") | `vorflux/desktop-host-mode` @ `b81d095` | **xong** |

Việc đã xong và **có test chạy được trên Linux** (nền tảng Windows giả, không cần máy Windows):

| Tệp test | Số ca | Kiểm cái gì |
|---|---|---|
| `backend/tests/unit/test_permissions.py` | 47 | bốn tầng luật, 10 mục sàn cứng, `Tool(specifier)`, ngắt mạch, audit |
| `backend/tests/unit/test_host_executor.py` | 34 | tệp/lệnh trên host, chặn `..`/symlink, timeout, fail-closed khi thiếu approver |
| `backend/tests/unit/test_permissions_api.py` | 22 | 6 route quyền + `BOXFOX_EXECUTION_MODE` + khối `execution` |
| `backend/tests/unit/test_win_capture.py` | 25 | chụp GDI 7 bước, DPI, cửa sổ thu nhỏ/cloaked |
| `backend/tests/unit/test_win_input.py` | 27 | ba bậc tiêm input, tổ hợp phím bị chặn, ô mật khẩu |
| `backend/tests/unit/test_win_uia.py` | 21 | UIA: `resolve`/`invoke`/`focus`, watchdog |
| `backend/tests/unit/test_inspect_host.py` | 69 | ba nhánh select element + 17 mã `reason` + nhãn `khong_tin_duoc` |
| `backend/tests/unit/test_win_platform_input.py` | 35 | `last_input_tick`, hook chuột/phím, mutex liên tiến trình |
| `backend/tests/unit/test_desktop_control.py` | 36 | lease/epoch, phát hiện người thật, fence, thang xác minh, chống lặp ảnh |
| `backend/tests/unit/test_host_executor_cua.py` | 31 | ba công cụ CUA trong executor: lease → quyền → mutex → fence → input |
| `backend/tests/unit/test_desktop_api.py` | 11 | `GET\|POST /api/agent/desktop/lease`, `POST .../inspect-element`, health mang lease thật |
| `frontend/src/components/settings/MachinePermissionsView.test.tsx` | 9 | tab Quyền/CUA: cảnh báo khi người giữ lease, ba nút gọi đúng route, chế độ docker không vỡ |
| **Tổng** | **367** | |

Giao diện: `cd frontend && npm run typecheck` (sạch) và `npx vitest run src/components/settings`
(118 xanh; 3 ca đỏ là **có sẵn trên `main`**: `ConnectionKeyRing.test.tsx` ×2 và
`ProviderConnectionCard.test.tsx` ×1 — đã đối chiếu lại khi bỏ thay đổi của D5 ra thì vẫn đỏ đúng 3 ca đó).

Lệnh chạy test backend (không dùng `--timeout`, không dùng cache):

```bash
cd <worktree>/backend && TMPDIR=/var/tmp PYTHONPATH=src /var/tmp/boxfox-venv/bin/python \
  -m pytest -q -p no:cacheprovider tests/unit/test_desktop_control.py tests/unit/test_host_executor_cua.py \
  tests/unit/test_desktop_api.py tests/unit/test_host_executor.py tests/unit/test_permissions.py \
  tests/unit/test_permissions_api.py
```

---

## 3. Hai nhánh đang mở (đọc trước khi sửa bất cứ thứ gì)

| Nhánh | Nội dung | Worktree tham chiếu |
|---|---|---|
| `vorflux/desktop-host-mode` | PR-1: host mode phía **backend** (H1–H7) + UI quyền/CUA (D5) | `/var/tmp/boxfox-hostmode-wt` |
| `vorflux/desktop-handoff` | PR #5: **chỉ** tài liệu này | `/var/tmp/boxfox-handoff-wt` |
| `vorflux/desktop-alpha` | PR-2: **ứng dụng Electron** + bộ cài NSIS (D1–D4) | `/var/tmp/boxfox-desktop-wt` |

Cả hai cắt từ `origin/main` `8d45b45`. Chúng **không** sửa cùng tệp (`backend/` + `frontend/` so với
`desktop/` + `docs/plan/desktop-alpha-install.md`), nên có thể review song song; PR-2 cần PR-1 để có
nghĩa đầy đủ (gateway trỏ `/__box/*` sang `/api/agent/desktop/*`).

---

## 4. Hợp đồng đã chốt (không mở lại)

### 4.1 Chọn chế độ

- `BOXFOX_EXECUTION_MODE` = `docker` (mặc định, gõ sai cũng về đây) | `host` | `cloud` (chưa cài ⇒ lỗi
  rõ `EXECUTION_MODE_UNIMPLEMENTED`).
- `BOXFOX_HOST_WORKSPACE` = thư mục làm việc của host mode (mặc định `~/BoxFox/workspace`).
- `BOXFOX_AGENT_DATA_DIR` = hồ sơ harness (audit, luật, `desktop_lease.json`, DB phiên).
- `BOXFOX_DESKTOP_CONTROL=0` ⇒ tắt hẳn lớp CUA dù đang ở host mode (dùng khi gỡ lỗi).
- `mode` trong health là thứ **đang chạy** (suy từ executor), không phải thứ được cấu hình.

### 4.2 Động cơ quyền

- Bốn chế độ: `plan` (chỉ đọc) | `ask` (mặc định) | `auto` | `trusted`; hai phạm vi: `workspace` |
  `machine` (mặc định `machine`).
- Bảng năng lực là **một** nguồn: `MODE_CAPABILITIES` trong `permissions.py`; CUA chỉ `allow` ở
  `trusted`, còn lại `ask` (và `False` ở `plan`).
- Bốn tầng luật theo thứ tự thắng: `managed` → `profile` → `user` → `project`.
- Sàn cứng 10 mục chạy **trước** mọi danh sách luật, kể cả `trusted`; neo `^` ở đầu **từng lệnh con**
  nên `echo shutdown /r` không bị chặn oan còn `git status && shutdown /r` thì bị.
- Ngắt mạch: 3 lần từ chối liên tiếp ⇒ `APPROVAL_DENIAL_BREAKER`, thôi hỏi.
- Audit: `permissions-audit.jsonl` trong hồ sơ, mỗi dòng `{rule, scope, tool, command, decision, actor,
  timestamp, session_id}`, ghi best-effort.

### 4.3 CUA (H7) — chuỗi phòng thủ theo thứ tự

1. **Lease trên đĩa** (`desktop_lease.json` trong hồ sơ): `holder` ∈ `agent|human`, `epoch` **đơn điệu**.
   Thiếu tệp ⇒ **agent** (máy mới vẫn dùng được); tệp hỏng/holder lạ ⇒ **fail-closed về người**.
   Tệp cũ (epoch thấp hơn) không hạ được epoch.
2. **Lease trước MỌI thao tác**, kể cả chụp màn hình. Người đang giữ thì agent **không tự lấy được**:
   chỉ `force=True` từ nút "Trả quyền cho agent" của người dùng mới chuyển được.
3. **Phát hiện người thật:** hook chuột/phím low-level; sự kiện có cờ `injected` là của chính agent nên
   **không** trả quyền; `poll_idle()` bắt trường hợp không cài được hook.
4. **Mutex liên tiến trình** `Local\BoxFoxDesktopInput-v1`, không xếp hàng: bận ⇒ `CONTROL_BUSY`.
5. **Token + `fence()`** kiểm ngay trước khi gửi: token mang `epoch` + `generation` +
   `geometry_revision`; lệch ⇒ `HUMAN_TOOK_OVER` / `HUMAN_HAS_CONTROL`, **không** gửi gì.
6. **Thang xác minh:** hai mẫu ổn định liên tiếp mới là `confirmed`; `effect` ∈ `confirmed|partial|
   unverifiable|suspected_noop|failed|refused`; chỉ `confirmed` mới được coi là thành công.
7. **Dừng khẩn** (UI/tray/Esc vật lý): tăng `epoch` + `generation`, nhả phím/chuột đang giữ, lease về
   `human`.

### 4.4 API đã có (host mode)

| Route | Việc |
|---|---|
| `GET /api/agent/permissions` | snapshot: mode, scope, capabilities, 4 tầng + tệp, luật hợp nhất kèm nguồn, số mục sàn cứng, đếm va sàn cứng, tệp audit, khối `execution` |
| `PUT /api/agent/permissions` | đổi `mode`/`scope`, ghi xuống `layer` (mặc định `user`) |
| `POST /api/agent/permissions/decide` | hỏi quyết định; kèm `decision` (`allow`/`allow_session`/`allow_always`/`deny`) để chốt |
| `GET /api/agent/permissions/pending` | thẻ duyệt đang chờ |
| `GET\|DELETE /api/agent/permissions/rules` | luật + tệp nguồn / thu hồi một luật |
| `GET\|POST /api/agent/desktop/lease` | đọc lease / `{action: claim\|release\|stop}` |
| `POST /api/agent/desktop/inspect-element` | `{x, y}` → payload soi phần tử (khung Element Selector ở host mode) |
| `GET /api/agent/health` | khối `execution`: `mode`, `configured`, `scope`, `permissionMode`, `policy`, `cuaEnabled`, `lease`, `hardlineHits`, `workspace` |

Chế độ `docker` không có động cơ quyền ⇒ các route trên trả **409 có mã**
(`PERMISSIONS_UNAVAILABLE`, `DESKTOP_CONTROL_UNAVAILABLE`), không phải 500.

### 4.5 Ba công cụ CUA trong `HostExecutor`

`computer_screen_capture`, `inspect_element`, `computer_use` nằm trong `HOST_TOOLS`; mọi công cụ khác
chưa có trên host trả `UNSUPPORTED_IN_HOST_MODE` (danh sách `DEFERRED_TOOLS`).

- `computer_screen_capture` → payload **cùng khuôn với box**: `{content, image (base64), mime,
  dimensions, target, sha256, label}` + `artifact` (PNG ghi vào `<hồ sơ>/.generated_artifacts/captures`).
  Ảnh mang nhãn `integrity: khong_tin_duoc` — hàng rào chống prompt-injection qua màn hình.
- `inspect_element` → payload của `inspect_host.inspect_element` (ba nhánh `dom → uia → desktop`).
- `computer_use` → `click` / `double_click` / `right_click` / `middle_click` / `type` / `key`; `scroll`
  chưa có (`UNSUPPORTED_ACTION`). Cửa sổ đích: `windowId` → cửa sổ chứa điểm `(x, y)` → cửa sổ đang
  hoạt động (chỉ cho `type`/`key`).
- Mã lỗi CUA: `CUA_UNAVAILABLE`, `HUMAN_HAS_CONTROL`, `TARGET_UNKNOWN`, `CONTROL_BUSY`,
  `SOURCE_CHANGED`, `UNSUPPORTED_ACTION` + mã của tầng nền tảng (`DESKTOP_LOCKED`, `ELEMENT_STALE`,
  `INPUT_SHORT_SEND`, `OS_PERMISSION_REQUIRED`, …).

---

## 5. Bản đồ tệp (chỗ để sửa tiếp)

| Tệp | Vai trò |
|---|---|
| `backend/src/agentbox/agent_core/permissions.py` | động cơ quyền (H2) |
| `backend/src/agentbox/agent_core/desktop_control.py` | lease/epoch/mutex/token/thang xác minh (H7) |
| `backend/src/agentbox/agent_core/inspect_host.py` | select element ba nhánh (H6) |
| `backend/src/agentbox/sandbox/host_executor.py` | executor host mode + ba công cụ CUA (H3, H7) |
| `backend/src/agentbox/sandbox/win/{capture,input,uia,windows_platform,errors}.py` | nền tảng Windows (H5) |
| `backend/src/agentbox/api/server.py` | chọn chế độ, 6 route quyền, 2 route desktop, khối `execution` (H4, H7) |
| `docs/plan/desktop-host-mode.md` | kế hoạch + hợp đồng host mode |
| `docs/architecture/host-desktop-control.md` | hợp đồng CUA (17 mã `reason`, 15 mã lỗi, cổng an toàn) |
| `docs/architecture/decisions/0002-concurrent-desktop-control.md` | ADR: đã chọn kết hợp hai cơ chế (epoch + fence tại điểm hành động) |
| `docs/testing/desktop-host-mode.md` | cách kiểm tầng Windows trên Linux + checklist cho chủ nhà |
| `desktop/**` | ứng dụng Electron: supervisor, gateway, profile, tray, chẩn đoán, bộ cài (D1–D3) |
| `frontend/src/components/settings/MachinePermissionsView.tsx` | tab "Machine & Permissions" (D5) |
| `frontend/src/lib/permissions/http.ts` | adapter gọi `/api/agent/permissions*` + `/api/agent/desktop/lease` (D5) |

---

## 6. Việc phải làm tiếp, theo thứ tự

1. **D3 + D4 — xong** (`dee25ca`, `9be9567`): tray (Hiện/Ẩn, Trả quyền cho agent, Dừng khẩn, mở thư mục dữ
   liệu, sao lưu chẩn đoán, Thoát), chẩn đoán ZIP có lọc bí mật, bộ cài NSIS theo từng người dùng, tài liệu
   `docs/plan/desktop-alpha-install.md` + checklist 13 bước. Test app: `npm test` trong `desktop/` → **72 xanh**.
   Bộ cài mới: `/code/.generated_artifacts/BoxFox-Desktop-Alpha-0.1.0-Setup.exe`, sha256
   `fbf07c4ac0b0b3b85d46ab80a0a71350ae69756d82b29338a78f42cc4d2b82a6`.
2. **D5 — xong** (`b81d095`): tab Settings "Machine & Permissions" đã có adapter
   (`frontend/src/lib/permissions/http.ts`) đi qua `agentApi`, kiểu dữ liệu riêng
   (`frontend/src/types/machinePermissions.ts`), 9 ca test. Chế độ docker hiện thẻ "không có động cơ
   quyền" và **không** gọi route nào, nên không chạm `PERMISSIONS_UNAVAILABLE`.
3. **PR-1 cho `vorflux/desktop-host-mode`** (H1–H7 + D5) đang mở; **PR-2 cho `vorflux/desktop-alpha`**
   (D1–D4) đã rebase lên `origin/main` mới nhất. PR-2 cần PR-1 để có nghĩa đầy đủ (gateway trỏ
   `/__box/*` sang `/api/agent/desktop/*`).
4. **Kiểm thử độc lập trên máy Windows thật** — đây là việc **bắt buộc** trước khi phát hành, vì toàn bộ
   H5–H7 mới chỉ chạy trên nền tảng giả:
   - `ComUiaAccessor` (đường `comtypes` thật) **chưa từng chạy** — rủi ro cao nhất.
   - Hook chuột/phím thật, mutex thật, DPI awareness thật, `PrintWindow`/`BitBlt` thật.
   - `geometryRevision` tăng khi cửa sổ đổi vị trí/kích thước/DPI hoặc trang đổi layout; input mang
     revision cũ ⇒ `SOURCE_CHANGED` (`reason: geometry_changed`). Cần đo trên app thật.
5. **Cắm dây cho phần còn thiếu của CUA** (nếu người tiếp nhận muốn hoàn thiện hơn bản alpha):
   - `computer_screen_record` trên host (hiện `UNSUPPORTED_IN_HOST_MODE`).
   - `computer_use` với `scroll` và bậc tiêm `PostMessage` (bậc 3).
   - Thang xác minh đang trả `unverifiable` cho mọi lần tiêm input: nối `verify_state()` với UIA để có
     `confirmed` thật.
   - `blocked key combos` (Win+L, Ctrl+Shift+Esc, Ctrl+Alt+Del, `consent.exe`) — hợp đồng có ghi ở
     `docs/architecture/host-desktop-control.md` §7.3 nhưng **chưa** hiện thực trong `input.py`.
6. **Dọn nhánh phụ:** `vorflux/desktop-winplat` (`6894299`) chỉ là nguồn cherry-pick — hai commit đã
   nằm trong `vorflux/desktop-host-mode` (`ee1d79b`, `8cd14c2`), nên bỏ nhánh này sau khi PR-1 merge.

---

## 7. Tài liệu trong repo (không phụ thuộc thư mục ngoài)

| Tài liệu | Nội dung |
|---|---|
| `docs/plan/desktop-host-mode.md` | kế hoạch + hợp đồng host mode: bảng hai executor, bảng quyết định mode × tool, ngữ pháp `Tool(specifier)`, bốn tầng luật, sàn cứng, API, 9 tiêu chí nghiệm thu |
| `docs/architecture/host-desktop-control.md` | hợp đồng CUA: bản đồ mô-đun, ba nhánh select element + shape dữ liệu + 17 mã `reason`, chụp GDI 7 bước, ba bậc tiêm input, lease/epoch/mutex/hook, token chống stale, thang xác minh, 15 mã lỗi, cổng an toàn, giới hạn đã biết |
| `docs/testing/desktop-host-mode.md` | lệnh chạy test, cách kiểm tầng Windows trên Linux, checklist 13 bước cho chủ nhà |
| `docs/architecture/decisions/0002-concurrent-desktop-control.md` | ADR-0002: chuyển từ "Hoãn" sang "Đã chọn: kết hợp lựa chọn 1 + 2" kèm 8 cơ chế và bảng tiêu chí trước khi bật |
| `docs/plan/desktop-alpha-packaging.md` | kế hoạch đóng gói alpha: D1–D5, câu hỏi mở đã có mặc định (profile `BoxFoxDesktopAlpha`, cổng động, build kèm bản Linux, CI `workflow_dispatch`, không bundle WGC mặc định, thêm `comtypes`) |
| `docs/plan/desktop-alpha-install.md` | hướng dẫn cài bộ cài NSIS, chọn chế độ, biến môi trường thật, chỗ nằm hồ sơ/log, cách xuất chẩn đoán, cảnh báo host mode, checklist nghiệm thu 13 bước (D4) |

---

## 8. Cảnh báo phải đọc trước khi bật CUA cho người dùng thật

- **Không có sandbox hệ điều hành.** Bật host mode nghĩa là agent có **đúng quyền của người dùng**:
  đọc/ghi tệp của họ, chạy lệnh, và (nếu bật CUA) điều khiển chuột/phím.
- **Ảnh chụp màn hình đi vào hội thoại** — có thể chứa dữ liệu nhạy cảm. Ảnh mang nhãn
  `khong_tin_duoc`, nhưng nhãn không làm nó bớt nhạy cảm.
- **CUA mặc định duyệt từng hành động**; không có "luôn cho phép" vĩnh viễn cho CUA (khác luật
  shell/tệp). `trusted` là chế độ duy nhất tự cho qua, và nó chỉ nên dùng khi người dùng hiểu rõ.
- Màn hình khoá / UAC / secure desktop ⇒ từ chối (`DESKTOP_LOCKED`), **không** cố chụp.
- Phiên chạy qua SSH (session 0) không có desktop tương tác ⇒ `SESSION_NOT_INTERACTIVE`.
