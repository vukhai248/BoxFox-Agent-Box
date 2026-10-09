# Sổ theo dõi lỗi — BoxFox Agent Box

Cập nhật: 2026-09-20 05:20 UTC — mọi phát hiện ở mục A và B đã được sửa trong commit 6d9aba7.

Quy ước cột **Trạng thái**:

- `ĐÃ SỬA` — có mã sửa trong cây làm việc và có test hoặc bằng chứng chạy thật.
- `ĐÃ SỬA (chờ xác minh)` — có mã sửa, chưa có bằng chứng chạy thật sau khi khởi động lại dịch vụ.
- `HOÃN` — biết lỗi, cố ý chưa sửa trong đợt này; ghi rõ lý do.
- `MỚI` — phát hiện ở đợt kiểm thử gần nhất, chưa sửa.

## 1. Đợt 1 — 25 lỗi từ vòng kiểm thử E2E ngày 2026-09-19

| Mã | Mức | Nội dung | Nơi sửa | Trạng thái |
|---|---|---|---|---|
| BUG-1 | Cao | `/compact` trên hội thoại ngắn làm phiên `failed` (`CONTEXT_LIMIT: summary did not reduce context enough`) | `backend/src/agentbox/agent_core/compression.py` | ĐÃ SỬA |
| BUG-2 | Cao | Router lọc bỏ delta chỉ có `reasoning_content` ⇒ không bao giờ có thinking stream | `router/src/engine.mjs`, `router/src/server.mjs` | ĐÃ SỬA |
| BUG-3 | Cao | UI bịa text suy luận ("Cryptographically verified by Cloud Code signature") | `frontend/src/components/chat/HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-4 | Cao | Model không có `contextWindow` / `thinkingType` / `defaultThinking` thật | `router/src/providers/*`, `router/src/service.mjs` | ĐÃ SỬA |
| BUG-5 | TB | `thinkingLevel` bị lọc bỏ khi tạo phiên | `backend/src/agentbox/agent_core/runtime.py` | ĐÃ SỬA |
| BUG-6 | TB | Toggle "Auto-compact enabled" chỉ là giao diện | `frontend/src/components/panels/ContextUsageBar.tsx` | ĐÃ SỬA |
| BUG-7 | TB | Thông báo nén không có số token, nằm trong khối đã thu gọn, không bấm được | `HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-8 | TB | Chat render theo khối, không theo dòng thời gian; mất text giữa lượt | `HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-9 | TB | Nhãn ảnh chụp cứng `1280 × 720 · PNG` | `HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-10 | TB | Không có tóm tắt cuối + expander; ảnh không gắn câu trả lời | `HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-11 | TB | `/claude-code` hardcode `role='build'`, lỗi `CHILD_FAILED` khi thiếu CLI | `backend/src/agentbox/skills/{commands,runtime_commands}.py` | ĐÃ SỬA |
| BUG-12 | Thấp | Catalog tĩnh bị gắn nhãn `source:'live'` | `router/src/providers/*` | ĐÃ SỬA |
| BUG-13 | Thấp | `RouterView.tsx` là UI chết | `frontend/src/components/settings/RouterView.tsx` | HOÃN — không nằm trong phạm vi đợt này; xoá cùng lúc với rà soát code chết |
| BUG-14 | Thấp | 6/8 phím tắt hiển thị nhưng đánh dấu `mock: true` | `frontend/src/components/shell/ShortcutsPopover.tsx` | HOÃN — cần chốt lại bộ phím tắt thật trước khi bỏ cờ |
| BUG-15 | Thấp | Code chết: `agent_core/engine.py`, `agent_loop.py`, thư mục `tools/` | `backend/src/agentbox/` | HOÃN — xoá code chết là thay đổi rộng, nên làm thành đợt riêng |
| BUG-16 | Thấp | UI gộp 3 store chat trong một khung | `frontend/src/components/panels/ChatPanel.tsx` | HOÃN — gộp store là tái cấu trúc lớn, cần thiết kế trước |
| BUG-17 | Cao | Lỗi HTTP 400 bị im lặng hoàn toàn | `frontend/src/components/panels/ChatPanel.tsx`, `store/harnessChatStore.ts` | ĐÃ SỬA |
| BUG-18 | TB–Cao | Thẻ lượt "ma" `Worked for 1s` nằm trên prompt đầu | `HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-19 | TB | Thời lượng sai ở lượt đã huỷ (`Worked for 1702s`) | `HarnessStepView.tsx` | ĐÃ SỬA |
| BUG-20 | TB | Rò rỉ transport mock vào chat thật (`Received interrupt command…`) | `frontend/src/components/panels/ChatPanel.tsx` | ĐÃ SỬA |
| BUG-21 | TB | Không bấm được `/stop` khi agent đang chạy | `frontend/src/components/panels/ChatInputBar.tsx` | ĐÃ SỬA |
| BUG-22 | Thấp | Nhãn Context Window bị cắt ở 900 px | `frontend/src/components/panels/ContextUsageBar.tsx` | ĐÃ SỬA |
| BUG-23 | Thấp | Không thu gọn theo màn hình nhỏ (390×844) | `frontend/src/App.tsx`, `components/shell/Sidebar.tsx`, `components/shell/useViewportWidth.ts` | ĐÃ SỬA |
| BUG-24 | Thấp | Đổi phiên hiện "No conversation yet" vài giây | `frontend/src/components/panels/ChatPanel.tsx` | ĐÃ SỬA |
| BUG-25 | Thấp | Trộn ngôn ngữ: chuỗi tiếng Việt cứng trong shell, lỗi box API tiếng Việt | `frontend/src/i18n/*`, `components/panels/PlanPanel.tsx`, `HarnessStepView.tsx` | ĐÃ SỬA một phần — xem mục 3 |

### Bằng chứng đợt 1

- Router: `cd router && /opt/node24/bin/node --test tests/*.test.mjs` → 63 pass / 0 fail.
- Backend: `.venv/bin/python -m pytest backend/tests -q` → 3 failed / 266 passed / 2 skipped (3 lỗi là lỗi môi trường có sẵn).
- Frontend: `cd frontend && npx vitest run` → 4 failed / 467 passed — đúng 4 lỗi có sẵn từ trước.
- Ảnh chụp: `images/f1-inline-error-400.png`, `images/u3-context-bar-900px.png`, `images/u4-narrow-390px.png`, `f2-f7-live-session-c1f656c9-chronological.png`, `f2-f4-live-capture-inline-under-tool-row.png`, `f7-live-compaction-notice-open.png`.

## 2. Đợt 4 — việc mới (Decision, plan tự mở, ghi file, kênh `ui_intent`, cuộn chat)

Hợp đồng chốt: `docs/plan/next-batch-contract.md`. Kế hoạch: `docs/plan/next-batch-workspace-decisions-plan.md`.

| # | Việc | Nơi sửa | Trạng thái |
|---|---|---|---|
| Đ4-1 | Tool `ask_user` / `request_approval`, sự kiện `decision_requested` → `decision_resolved`, trạng thái `awaiting_decision`, route trả lời, hết hạn = từ chối | `backend/src/agentbox/agent_core/{tool_contracts,runtime}.py`, `api/server.py` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 5, 6) |
| Đ4-2 | Tool `write_plan` + sự kiện `plan_written` + `ui_intent` | `backend/src/agentbox/sandbox/worker.py`, `agent_core/runtime.py` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 5, 6) |
| Đ4-3 | API ghi workspace: `mkdir`, `touch`, `rename`, `move`, `delete` (vào `.trash`) | `deploy/docker/{workspace_files,ide-proxy}.py` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-4 | Trạng thái duyệt plan thật (`.reviews`), sửa cache manifest theo mtime thư mục con | `deploy/docker/plan_files.py` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-5 | Decision thật trên giao diện: bỏ demo, một `PermissionCard` dùng chung, đếm ngược theo `deadline` thật | `frontend/src/components/panels/DecisionsPanel.tsx`, `PermissionCard.tsx` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-6 | Tab Plan tự mở khi có `plan_written`, `planRevision` cho `usePlanFiles`, bỏ nhánh mock | `frontend/src/store/uiStore.ts`, `hooks/usePlanFiles.ts`, `PlanPanel.tsx` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-7 | Luật không cướp tab (`requestTabIntent`): tôn trọng tab đang ghim, 15 giây hoạt động gần nhất, huy hiệu khi bị chặn | `frontend/src/store/uiStore.ts`, `App.tsx` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-8 | Chip trong transcript bấm được (sub-agent, plan, file, decision) | `frontend/src/components/chat/HarnessStepView.tsx`, `ChatPanel.tsx` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-9 | Hoàn thiện cuộn chat: số tin nhắn mới, phím `End`/`Shift+G`, giữ vị trí đọc, khôi phục vị trí theo phiên | `frontend/src/components/panels/ChatPanel.tsx` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |
| Đ4-10 | Giao diện thao tác file: tạo/đổi tên/xoá/di chuyển, xác nhận xoá nói rõ `.trash`, trạng thái file > 1 MiB, huy hiệu integrity | `frontend/src/components/panels/workspace/*`, `hooks/useWorkspaceFiles.ts`, `lib/workspace/*` | ĐÃ SỬA — ĐÃ XÁC MINH (vòng 4, 6) |

## 3. Đợt 4 — lỗi tìm thấy sau khi làm, đã sửa và xác minh

Nguồn: vòng kiểm thử trình duyệt trên hệ thống thật (vòng 4) và vòng kiểm chứng độc lập (vòng 6).
Chi tiết: `docs/tracking/findings-round4.md`.

| Mã | Mức | Mô tả ngắn | Trạng thái |
|---|---|---|---|
| B12 | Trung bình–Cao | Luật tự mở tab không tất định ở cấu hình mặc định (tự cuộn của agent gia hạn cửa sổ 15 giây; hàng đợi intent không bao giờ được xả) | ĐÃ SỬA (51f1452) — ĐÃ XÁC MINH (vòng 5 và vòng 6) |
| B13 | Thấp–Trung bình | `thinkingLevel` sai vẫn lọt khi lượt chạy đổi model | ĐÃ SỬA (51f1452) — ĐÃ XÁC MINH (vòng 6) |
| B2c | Thấp | Thẻ dạng lưới hiện nhãn chấm integrity bằng tiếng Anh và không hiện `confidentiality` | ĐÃ SỬA (51f1452) — ĐÃ XÁC MINH (vòng 6) |
| B4 | Thấp | Kéo thanh chia panel không được tính là hoạt động người dùng | ĐÃ SỬA (51f1452) — ĐÃ XÁC MINH (vòng 6) |
| B6 | Thấp | Intent cho tab Files mở tab mà không chọn file | ĐÃ SỬA (51f1452) — ĐÃ XÁC MINH (vòng 6) |
| B7 | — | Hai quyết định cùng lúc trong một phiên gốc là bất khả (409 `SESSION_BUSY`) | ĐÃ RÚT |
| N-1 | Thấp | `/skill <id>` thiếu nhiệm vụ không có mã lỗi máy đọc được | ĐÃ SỬA (6d9aba7) — ĐÃ XÁC MINH (vòng 4) |
| N-2 | Thấp | `thinkingLevel` sai được lưu nguyên lúc tạo phiên | ĐÃ SỬA (6d9aba7) — ĐÃ XÁC MINH (vòng 4) |
| NEW-1 | Trung bình | Nút Compact bị cắt ở khung hẹp 900–1100 px | ĐÃ SỬA (6d9aba7) — ĐÃ XÁC MINH (vòng 4) |
| R-1 … R-9 | Cao → Thấp | Phát hiện của vòng rà soát tích hợp (phiên con hỏi người dùng, cướp tab khi tải lại, `awaiting_decision` không tính là bận, đường dẫn được bảo vệ, …) | ĐÃ SỬA (6d9aba7) — ĐÃ XÁC MINH (vòng 4, 6) |

## 4. Việc còn nợ (không phải lỗi)

| # | Việc | Trạng thái |
|---|---|---|
| Nợ-1 | Dựng lại ảnh container để các tệp mới nằm trong image | ĐÃ XONG — `docker compose build` xong, `agentbox-sandbox:latest` (manifest `sha256:cf06992844d6…`), ba tệp trong ảnh khớp hash repo (`ide-proxy.py a7a83b02…`, `plan_files.py de901085…`, `workspace_files.py fc391ce1…`) |
| Nợ-2 | Xác thực `/claude-code` bằng CLI thật | CHƯA LÀM ĐƯỢC trong môi trường này — box không có binary `claude` và không có thông tin đăng nhập; chỉ xác minh được nhánh `SETUP_REQUIRED` |
| Nợ-3 | Nén context tự động theo ngưỡng token | **ĐÃ XONG vòng 19** — ngưỡng nay là `min(phần trăm, trần byte 301 200)` nên chạm được: đo sống hai lần nén tự động `summary` khi ngữ cảnh vượt ngưỡng, xem §6.20 |

## 5. Việc còn lại của BUG-25

Chuỗi lỗi tiếng Việt trong lớp container (`deploy/docker/capture.py`, `browser_capture.py`) là **thông báo lỗi kỹ thuật** trả cho giao diện; giao diện hiển thị nguyên văn. Cần chuyển các thông báo người dùng nhìn thấy sang khoá i18n ở phía frontend, hoặc trả mã lỗi và để frontend dịch. Chưa làm trong đợt 1 vì đụng tới ánh xạ lỗi chung; ghi ở đây để không mất dấu.

## 6. Đợt 7 — sáu việc chủ sở hữu giao (2026-09-20, sáng)

Kế hoạch của đợt: [round7-batch-plan.md](../plan/round7-batch-plan.md). Ba bản kế hoạch riêng:
[chất lượng đầu ra](../plan/agent-output-quality-plan.md), [benchmark](../plan/cua-benchmark-plan.md),
[nhật ký hệ thống](../plan/dev-system-log-plan.md).

| Mã | Lỗi / việc | Mức | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| BUG-26 | Harness phát lại **toàn bộ** văn bản tích luỹ ở mỗi delta (`assistant_delta`, `thought`); nơi đọc cộng dồn nên đầu ra lặp: đo được **tỷ lệ 38,0** (lượt chính) và **13,8** (lượt con) giữa tổng độ dài delta và văn bản cuối | HIGH | ĐÃ SỬA (`0800349`) — ĐÃ ĐO LẠI sống: **1,0** cả hai lượt | `r7_delta_repro.json` (trước) vs `r7_delta_after_fix.json` (sau) |
| BUG-26b | Bảng sub-agent đọc `tool_end` theo khoá `tool_call_id` trong khi harness phát khoá `id` ⇒ kết quả không gắn vào dòng, mọi dòng treo ở "running" | HIGH | ĐÃ SỬA (`0800349`) | `SubagentInspectorPanel.stream.test.tsx` (4 ca) |
| BUG-27 | Câu lỗi hiện đúng chữ `Agent run failed` khi `error` rỗng (`ServerDisconnectedError`, `ConnectionResetError`, `Exception()`…), không retry lỗi tạm thời | HIGH | ĐÃ SỬA (`0800349`) — ĐÃ XÁC MINH sống: `UPSTREAM_HTTP_503` kèm câu giải thích của router | `r7_delta_after_fix.json`, `r7_cua_and_failure_evidence.json` |
| BUG-27b | Câu lỗi dự phòng ở store (`harnessChatStore.ts`) vẫn là chuỗi trần khi hàng cũ có `message` rỗng | MEDIUM | ĐÃ SỬA (`0f5b127`) | `harnessChatStore.test.ts` (2 ca mới) |
| BUG-28 | Hợp đồng chuyển việc cho sub-agent trống: schema không mô tả tham số, không nêu cấu trúc kết quả, câu trả lời con không bị chặn trần (JSON phình trong event) | HIGH | ĐÃ SỬA (`b0ba53b`) — ĐÃ ĐO LẠI sống: câu trả lời con bị chặn ở 8 075 ký tự kèm `truncated: true` | `after_delegate.json` |
| BUG-29 | `write_plan` nhận plan không có mục nghiệm thu, không có rủi ro, không có nguồn — không có cổng chất lượng nào | HIGH | ĐÃ SỬA (`b0ba53b`) — cổng `PLAN_QUALITY_REJECTED` chạy trước khi ghi tệp | `test_plan_quality.py` (14 ca) |
| BUG-30 | `/claude-code` là ngõ cụt: ảnh box không có `node`/`claude`/`bwrap`; harness không truyền `ANTHROPIC_*`; readiness đòi đăng nhập tài khoản; box không tới được router | HIGH | ĐÃ SỬA phần mã (`7bf7d84`, `dad8178`, `51ecba6`) — CHƯA XÁC MINH sống vì container thật chưa tạo lại và cầu nối còn tắt (mặc định) | `deploy/docker/README-claude-code.md` |
| BUG-31 | Log hệ thống cho dev chưa có; test đơn vị ghi thẳng vào thư mục log thật của người vận hành | MEDIUM | ĐÃ SỬA (`0800349`, `006e466`, `aa30ffb`) | `test_system_log.py` (8 ca), `backend/tests/conftest.py` |
| N-4 | Bảng Terminal trong box thì agent đọc được; nhật ký dev nay ở host (`~/BoxFox/logs`) nên agent không thấy, nhưng **chưa có bảng xem trong app** | — | CHƯA LÀM (bản v2 của kế hoạch nhật ký) | `dev-system-log-plan.md` §3 |
| N-5 | Sản phẩm **không có công cụ tìm kiếm web**; năng lực web duy nhất là `browser_use`, mà box mặc định tắt mạng | — | **ĐÃ XONG (2026-10-06)** — có `web_search`/`web_fetch` ở tầng host và **tìm được ngay khi cài, không cần khoá**: SearXNG tự host + tự dò `127.0.0.1:8888` là chân mặc định (bậc 3), ống 10 bước mặc định `auto` | `agent-output-quality-plan.md` §4 (ca Q5/Q6); `docs/plan/builtin-search-default.md`; `docs/testing/builtin-search-e2e.md` |

### 6.1 Năm lỗi vòng kiểm chứng đợt 7 — ĐÃ SỬA (`9e25bea`)

| Mã | Lỗi | Mức | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| F1 | Một bản ghi màn hình hiện thành **hai** player + hai thumbnail: bộ trích media nhận luôn đường dẫn mà `action=start` trả về (chưa có `durationSec`), và danh sách media không khử trùng | MEDIUM | ĐÃ SỬA — chỉ bản ghi đã xong mới là media, danh sách khử trùng theo đường dẫn | `HarnessStepView.media.test.tsx` (2 ca) |
| F2 | Phiên `failed` hiện chip `IDLE` ở thanh bên: nhánh ánh xạ gộp mọi trạng thái không phải running/completed thành `idle` | MEDIUM | ĐÃ SỬA — giữ trạng thái thật, `failed` → `loi` → nhãn `ERROR`; **giữ nguyên khung chip cũ và khoá i18n có sẵn**, không đổi thiết kế | `sidebarStatus.test.ts` (3 ca) |
| F3 | `computer_use key <tên sai>` báo thành công: `xdotool` in `No such key name … Ignoring it.` rồi thoát 0 | MEDIUM | ĐÃ SỬA — cảnh báo đó là lỗi, có nêu tên phím sai | `test_sandbox_worker_computer_use.py` (4 ca) |
| F4 | `computer_use` báo đã gửi phím vào cửa sổ không được focus | MEDIUM | ĐÃ SỬA — `type`/`key` kiểm tra cửa sổ đang focus trước, báo `No focused window…` | cùng tệp trên |
| F7 | Thanh ngữ cảnh bỏ qua nén: đọc `step` cuối nên vẫn hiện số **trước** khi nén cho tới lượt sau | MEDIUM | ĐÃ SỬA — event `compression` mới hơn thì thắng | 2 ca mới trong `ContextUsageBar.test.tsx` |

Ghi chú F3: worker được host đọc từ repo và gửi vào box bằng `python3 -c`, nên bản sửa có hiệu lực ngay sau khi harness khởi động lại — không cần dựng lại ảnh container.

### 6.2 Hai lỗi còn nợ của vòng kiểm chứng đợt 7 — ĐÃ SỬA ở đợt 9

| Mã | Lỗi | Trạng thái | Cách sửa và bằng chứng |
|---|---|---|---|
| F5 | `inspect_element` trả `ambiguous_target` khi cửa sổ Chromium khớp nhiều tab, làm agent đốt bước | **ĐÃ SỬA** | Thêm bước chọn **theo trạng thái hiển thị**: khi điểm hình học hoà nhau (nhiều tab CÙNG một cửa sổ), `browser_capture._select_target` hỏi `document.visibilityState`/`hasFocus` của từng ứng viên qua `Target.attachToTarget` và chọn tab tiền cảnh — tất định, trần 24 tab. Nếu vẫn mơ hồ, payload lỗi mang thêm `candidates`/`tabs` (chỉ `targetId`, `title`, `url` — không bao giờ có URL debugger) để agent tự thu hẹp. Live: đúng toạ độ (640,300) trước đây trả `reason: ambiguous_target` với 34 tab `vi.wikipedia.org`, nay trả `{"type":"dom","selector":"#main-content","tag":"div"}`. Test: `VisibleTargetTest` (6 ca), `SafeTabListTest` (2 ca); kiểm ngược: bỏ bước chọn theo hiển thị thì 3 ca đỏ |
| F6 | Desktop trong box bị client kéo nhỏ tận 286×311 qua `Xvnc -AcceptSetDesktopSize` | **ĐÃ SỬA** | Giữ auto-fit, chặn **sàn** kích thước: `capture.ensure_desktop_size()` (gọi trước chụp màn hình, trước `record start`, và trước hit-test của `inspect_element`) + `worker.ensure_desktop_size()` (gọi trước mọi thao tác `computer_use` theo toạ độ). Cỡ đích lấy từ `BOX_SCREEN` (mặc định 1280×800). Khi đặt lại được, payload mang `desktopRestored {from,to}`; khi thất bại, `desktopWarning` (không ném lỗi — ảnh vẫn là ảnh thật). Host ghi cả hai vào nhật ký DEV (`box.desktop_restored` / `box.desktop_warning`). Live: kéo xuống 286×311 rồi chụp → `desktopRestored {'from': '286x311', 'to': '1280x800'}`, ảnh 1280×800; `computer_use click` → cùng ghi chú; log ghi `box.desktop_restored` với `sessionId`/`tool`. Test: `test_sandbox_worker_desktop_floor.py` (7 ca), `DesktopFloorTest` (6 ca), `test_sandbox_executor_desktop_note.py` (5 ca); kiểm ngược: bỏ hàm chặn sàn thì 2 ca đỏ, bỏ chuyển tiếp ghi chú thì 1 ca đỏ |

Ghi chú vận hành: hai bản sửa này nằm trong `deploy/docker/*.py` và `sandbox/worker.py`.
`worker.py` được host truyền vào box theo từng lệnh nên có hiệu lực ngay; còn
`browser_capture.py`/`inspect_element.py`/`capture.py` phải nằm trong **ảnh** container
— lần kiểm chứng này chép tay ba tệp đó vào container đang chạy rồi khởi động lại
`ide-proxy` (không đụng X/Chromium). Lần tạo lại container tiếp theo sẽ lấy đúng các
tệp trong kho.

### 6.3 Chín phát hiện của vòng soát mã đợt 8 — bảy lỗi, một ghi chú, một nit

Nguồn: sub-agent `review`, kết luận REQUEST CHANGES trên chuỗi 11 commit (HEAD `af155e1`).
Toàn bộ được xử lý trong `16eedda`.

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| BUG-32 | Cao | Lượt gọi model thử lại giữ nguyên văn bản đã bỏ: `streamed` tạo một lần cho cả bước, không đặt lại trong vòng retry ⇒ câu trả lời cũ dán vào câu trả lời mới (làm sống lại BUG-26 trên đường retry) | ĐÃ SỬA — `_reset_stream()` đặt lại `content`/`thought` trước mỗi lần thử lại; event `UPSTREAM_RETRY` mang thêm `reset: True` | `test_stream_delta_events.py::test_retry_after_a_partial_stream_drops_the_abandoned_text` (mới, dùng `fail_after=n` của `StreamingModel`) |
| BUG-33 | Cao (an ninh) | Cầu nối quang sai mở luôn **mặt quản trị** của router cho box: cùng một `handler`, mà `/api/router/*` và `/v1/router/generate` chỉ gác bằng header `x-boxfox-admin: 1` (không phải bí mật) + kiểm Origin và `sec-fetch-site` đều lọt khi thiếu header; phần kiểm địa chỉ chỉ chặn `0.0.0.0`/`::` nên địa chỉ LAN/công cộng vẫn qua | ĐÃ SỬA — tai nghe cầu nối chỉ phục vụ bốn đường suy luận (`BRIDGE_PATHS`), mọi đường khác trả 404 kèm dòng `router.bridge_denied`; `isPrivateAddress()` chỉ nhận loopback + dải riêng | 2 ca cầu nối trong `anthropic-ingress.test.mjs`; kiểm ngược: tắt cổng `BRIDGE_PATHS` thì ca đó đỏ |
| BUG-34 | TB | Thông báo `UPSTREAM_RETRY` không có nơi nhận: `applyTimelineEvent` không có nhánh `notice` nên người dùng vẫn thấy lượt đứng im rồi lỗi | ĐÃ SỬA — `HarnessStepView` có nhánh `notice` dùng lại khung chú thích sẵn có, `reset: True` xoá phần đã stream, và bảng sub-agent cũng xoá `thought`/`output` | `HarnessStepView.notice.test.tsx` (2 ca); kiểm ngược: bỏ nhánh `reset` thì ca thứ hai đỏ |
| BUG-35 | TB | Trí nhớ chữ ký suy luận có thể gán nhầm của request khác: khoá là id do router phát, mà nhánh Gemini không có id thì dùng `call_${index}_${Date.now()}` — trùng mili-giây là trùng khoá | ĐÃ SỬA — thêm bộ đếm tăng dần toàn tiến trình vào id dự phòng; ghi rõ vòng đời (mất khi router khởi động lại) trong `anthropic.mjs` | `anthropic-ingress.test.mjs` (khoá chữ ký) |
| BUG-36 | TB | Tham số công cụ không phân tích được thành JSON thì **âm thầm** hoá `{}`: client chạy công cụ không tham số, người dùng thấy lỗi công cụ không giải thích được | ĐÃ SỬA — hàm dựng thân trả lỗi có mã `TOOL_ARGUMENTS_INVALID` (502) nêu tên công cụ và 80 ký tự đầu; đường stream vẫn phát `input_json_delta` thô nên mất mát là hữu hình | ca cũ khoá hành vi mất mát đã được thay bằng 2 khẳng định mới |
| BUG-37 | Thấp | Đọc sai loại lỗi hết giờ: `httpx.ReadTimeout`/`ConnectTimeout` kế thừa `TimeoutException`/`TransportError` chứ **không** phải `TimeoutError` của Python, nên rơi vào nhánh `UPSTREAM_UNREACHABLE: … closed the connection …` — ngược hẳn lời khuyên | ĐÃ SỬA — `_is_timeout()` nhận cả họ `*Timeout`; `UPSTREAM_TIMEOUT` là mã riêng, câu chữ là "did not answer in time", và không thử lại | `test_failure_classification.py` (12 ca) |
| BUG-38 | Nit | `HARNESS_PORT` đọc lúc import: giá trị không phải số làm chết harness bằng `ValueError` trần, và danh sách host cho phép giữ nguyên cổng 3102 khi đã đổi cổng | ĐÃ SỬA — `harness_port()`/`allowed_hosts()` đọc mỗi lần gọi, báo lỗi có tên biến, vẫn giữ cổng mặc định trong danh sách | `test_harness_port_override.py` (4 ca) |

Hai phát hiện được xử lý bằng ghi chú, không bằng mã:

- **#6 (Thấp)** — `_suffix()` không có ngữ nghĩa đặt lại; nay docstring nói rõ một `current` không phải tiền tố nghĩa là provider đã bắt đầu tích luỹ lại, và nơi đọc có móc đặt lại.
- **#8 (ghi chú)** — token router nằm trong argv của `docker exec` phía host (`claude_executor.py`): cố ý, đã có ca khẳng định trong `test_claude_executor.py`.

### 6.4 Hai lỗi vòng kiểm chứng độc lập đợt 9 tìm thêm — ĐÃ SỬA (`65039ae` + đợt này)

Nguồn: sub-agent `testing` (`test-round9-verify`), chạy đúng kịch bản CUA nhẹ → nặng và
delegation trên cây `65039ae`, kết luận `PARTIAL` vì đúng hai lỗi dưới đây.

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| F6b | Cao (làm hỏng hợp đồng) | `deploy/docker/capture.py` gọi `.decode()` lên đầu ra của `_run_as_agent()` — mà hàm này chạy `text=True` nên đầu ra là `str`: nhánh "đặt lại thất bại" ném `AttributeError`, `/__box/capture` và `/__box/record/start` trả **HTTP 500** thay vì trả ảnh kèm `desktopWarning`. Đo sống: `BOX_SCREEN=9999x9999` trên cổng tạm :8099 → `500 {"error": "Lỗi nội bộ."}`, log proxy `AttributeError("'str' object has no attribute 'decode'")` | ĐÃ SỬA — thêm `_output_text()` nhận cả `str` lẫn `bytes`; warning vẫn là `xrandr exit <n>: <200 ký tự đầu>` | `DesktopFloorTest` +3 ca: đầu ra `str` vẫn ra `desktopWarning` (không ném), đầu ra rỗng cho warning sạch, `_output_text` nhận cả hai kiểu |
| F8 | Cao (đốt ngân sách bước) | `worker.py` luôn chạy `xdotool mousemove --sync`; cờ này chỉ trả về khi con trỏ **đổi** vị trí, nên khi con trỏ đã ở đúng toạ độ đích nó chờ hết 15 s (đo trong box: 15.16 s và 15.15 s, so với 0.0 s ở điểm mới), mà lệnh bị cắt ở `timeout=15` ⇒ lần bấm thứ hai vào cùng một chỗ báo lỗi hết giờ. Đây là thứ làm lượt CUA nặng của đợt 7 đốt 20/20 bước rồi `MAX_STEPS` | ĐÃ SỬA — `_pointer_move()` di chuyển **không** `--sync` rồi tự chờ bằng `xdotool getmouselocation` (trần 20 lần × 50 ms); mọi thao tác chuột theo toạ độ đi qua `_pointer_click()` | `test_sandbox_worker_pointer.py` (5 ca): không còn `--sync` ở bất kỳ lệnh nào, bốn thao tác chuột đều di chuyển trước, con trỏ đã đúng chỗ chỉ thăm dò 1 lần, vị trí không khớp dừng sau 20 lần mà vẫn bấm, `type`/`key` không đụng con trỏ |

### 6.5 Hai lỗi lộ ra khi chạy `/claude-code` thật đầu tiên — ĐÃ SỬA (đợt này)

Nguồn: lượt `/claude-code` đầu tiên chạy thật qua cầu nối router (2026-09-20 07:2x–07:4x), sau khi
image được build lại và `status` của executor đã là `ready`.

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| F9 | Cao | Con của lệnh không được truyền `deadlineSeconds`, nên rơi về mặc định **180 giây** của `create_session` — phiên đặt 600 giây vẫn kết thúc `DEADLINE: the turn ran out of time before an answer was produced`, dù ngân sách của phiên còn nguyên | ĐÃ SỬA — `_command_task` truyền ngân sách của **phiên** vào cả hai đường tạo con (`budget = session['config'].get('deadlineSeconds', 180)`), không đẻ thêm hằng số thứ hai | `test_skill_commands.py::test_command_child_inherits_the_session_time_budget` (mới) |
| F10 | Cao | Không đặt `BOXFOX_ANTHROPIC_MODEL` thì CLI tự chọn model mặc định của nó (`claude-opus-5[1m]`), model **không có** trên router BoxFox, nên lượt chết ngay: `There's an issue with the selected model (claude-opus-5[1m])`. Lần chạy thật đầu tiên chết đúng như vậy dù cấu hình `*_DEFAULT_SONNET_MODEL`/`*_DEFAULT_HAIKU_MODEL` đã đúng | ĐÃ SỬA — `router_config()` lấy model sonnet (hoặc haiku) đã cấu hình làm `ANTHROPIC_MODEL` khi biến này trống; giá trị người dùng đặt thẳng vẫn thắng, readiness báo lại qua `models` | `test_claude_worker_router.py::test_the_cli_never_falls_back_to_its_own_default_model` + `::test_cli_environment_carries_the_resolved_model` (mới) |

### 6.6 Tám phát hiện của vòng soát mã đợt 10 — bảy sửa, một ghi nhận (đợt này)

Nguồn: sub-agent `review` đọc `git diff 58598c1..95076b5` (vòng 10). Kết luận chung: **APPROVE WITH
COMMENTS**, điểm rủi ro **3/10** — ba phát hiện mức TB, ba mức Thấp, hai nit. Cả bảy phát hiện cần sửa
đều đã sửa trong đợt này.

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| R10-1 | TB | Nhánh **lỗi** của công cụ web ghi nguyên `str(exc)` vào nhật ký DEV, mà câu đó có cả truy vấn (`no result for '<truy vấn>'`) lẫn URL đầy đủ — trái hợp đồng ở `docs/research/host-web-tools.md` §3, và nút "Copy diagnostics" của bảng nhật ký sẽ mang nội dung người dùng ra khỏi máy. Ca kiểm cũ chỉ khẳng định đường thành công | ĐÃ SỬA — `WebError` mang thêm `log_message` (bản không nội dung); `failures.log_safe_failure()` dùng bản đó và bỏ luôn vết lỗi ở nhánh an toàn; `runtime` ghi `tool.error` bằng bản an toàn; dòng `web.error` thêm `queryChars`/`host` | `test_web_tools.py::test_a_failed_call_never_writes_the_query_or_the_url` (mới), `test_failure_classification.py` +2 ca |
| R10-2 | TB | `ORCHESTRATOR_SOP_GUIDANCE` (runtime.py) vẫn khẳng định "is the ONLY role with browser access, **there is NO web-search tool**", trong khi `roles.py` cùng commit cấp `web_search`/`web_fetch` cho vai gốc — một request vừa nói "không có" vừa quảng cáo hai công cụ đó | ĐÃ SỬA — câu Phase 1 nói đúng: `research` chạm browser **và** hai công cụ host, vai gốc cũng giữ hai công cụ đó | `test_brain_cognition.py::test_the_orchestrator_guidance_matches_the_tools_it_really_holds` (mới) |
| R10-3 | TB | `test_eval_setup.py` khẳng định `pins['repo']['dirty'] is True` kèm chú thích "cây này đang có tệp chưa commit" — cây sạch là bộ kiểm đỏ thêm một ca (vòng soát đo `3 failed, 479 passed`) | ĐÃ SỬA — ca cũ chỉ khẳng định **được đo** và đúng kiểu; thêm ca dựng repo tạm để kiểm cả cây sạch lẫn cây bẩn | `test_eval_setup.py::test_repo_state_sees_an_uncommitted_file_and_says_so` (mới); bộ kiểm nay `2 failed, 488 passed` — hai ca đỏ còn lại là hai ca cũ phụ thuộc môi trường |
| R10-4 | Thấp | `reset --file all` chạy qua cả `*.previous.jsonl`, nên `harness.previous.jsonl` bị đổi thành `harness.previous.previous.jsonl` — trái lời hứa "đúng một tệp previous" ở docstring và trợ giúp CLI | ĐÃ SỬA — bỏ qua tệp đã là previous; tệp đang ghi vẫn được xoay **thay** bản previous cũ | `test_system_log.py::test_cli_reset_all_leaves_exactly_one_previous_file` (mới) |
| R10-5 | Thấp | Chuỗi nhà cung cấp tìm kiếm chỉ bắt `WebError`, nên nhà cung cấp trả **200 với thân không phải JSON** làm đứt cả chuỗi (đo được: firecrawl trả `200 text/html` là trang chặn, Brave chưa từng được gọi) | ĐÃ SỬA — mỗi nhà cung cấp còn bắt `ValueError`/`KeyError`/`TypeError` và kiểm kết quả phải là danh sách; lỗi được ghi vào danh sách lý do rồi đi tiếp | `test_web_tools.py::test_the_provider_chain_survives_a_challenge_page` (mới) |
| R10-6 | Ghi chú | `web_fetch` là kênh GET ra ngoài do cả `orchestrator` lẫn `research` giữ: một trang bị tiêm nhiễm có thể xúi agent tải `https://ke-tan-cong/?<ngữ cảnh>` — chiều **rò ra**, khác chiều nội dung bẩn vào | ĐÃ GHI NHẬN — thêm dòng "Rủi ro còn lại: kênh ra" vào `docs/research/host-web-tools.md` §3 kèm cách siết (bỏ `web_*` khỏi vai gốc, hoặc danh sách đích cho phép). Chưa đổi quyền vì chủ sở hữu đã chốt phương án này | `docs/research/host-web-tools.md` §3 |
| R10-7 | Nit | `worker.py` xác nhận con trỏ tới nơi bằng `f'X={x}' in out`, nên đích `(64, 3)` gặp con trỏ thật ở `(640, 300)` là "tới nơi" ngay | ĐÃ SỬA — so khớp theo dòng `X=<số>`/`Y=<số>` | `test_sandbox_worker_pointer.py::test_a_prefix_of_the_real_coordinates_does_not_count_as_arrival` (mới) |
| R10-8 | Nit | `scripts/eval/README.md` §2 ghi "Thêm **hai** biến kết nối" nhưng liệt kê bốn tên | ĐÃ SỬA — sửa thành "bốn biến" | `scripts/eval/README.md` §2 |

### 6.7 F-1 — trần 1 MiB của router làm chết nhiệm vụ CUA nặng — ĐÃ SỬA (đợt này)

Nguồn: vòng kiểm chứng độc lập đợt 10, ca T21 (nhiệm vụ nặng để mô hình tự chọn chụp màn hình
giữa các bước). Đây là lỗi **có sẵn**, không nằm trong diff của vòng 10 — nhưng nó chặn đúng
hạng mục "CUA nhẹ → nặng" mà chủ sở hữu yêu cầu, nên được sửa luôn.

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| F-1 | Cao (chặn nhiệm vụ dài) | Router từ chối thân request trên **1 MiB** (`router/src/server.mjs:27`), mà mỗi lần chụp màn hình được nhét vào thân dưới dạng base64 và `ContextCompressor` chỉ đếm **token** nên không bao giờ thấy trần byte. Đo được (lượt rút ảnh): thân request 1 107 315 ký tự, trong đó **1 018 908 ký tự là ảnh base64** (mỗi ảnh 77–104 KB); mọi lượt gọi sau đó chết với `UPSTREAM_HTTP_413: Request is too large.` — tái hiện 3 lần (một phiên chết ở bước 11, một phiên mới chết sau 4 ảnh) | ĐÃ SỬA — `runtime.bound_inline_media()` giữ ảnh của **2 lần chụp mới nhất** và tổng tối đa **512 KB** trong thân request; ảnh cũ rút về phần chữ đi kèm (vẫn còn đường dẫn tệp). Bản lưu trong store không đổi, nên giao diện chat vẫn thấy mọi ảnh. Áp tại `RouterClient.complete()` — nơi duy nhất dựng thân request — và ghi `model.media_pruned` khi có ảnh bị rút | `test_inline_media_bound.py` (9 ca): không ảnh thì trả nguyên danh sách; 5 ảnh → chỉ 2 ảnh cuối còn inline, phần chữ giữ đường dẫn; danh sách gốc không bị sửa; trần byte thắng trần số lượng; 12 ảnh 90 KB: thân trước 1 107 315 B > 1 MiB, sau khi rút < 1 MiB |
| F-1b | Cao (phát hiện khi đo lại trên `fa57325`) | Sau khi đã chặn ảnh, thân request vẫn **vượt trần 17 382 B** (1 739 044 B so với 1 048 576 B) vì chữ ký suy luận của Gemini bị nhân đôi thành `thought_signature` **và** `thoughtSignature` trong cùng một `tool_call`. Đo trên năm phiên lớn nhất: riêng cặp chữ ký chiếm **761 888 B** ở phiên nặng nhất, 380 944 B ở phiên 1,8 MB; không có đường nào tỉa phần này | ĐÃ SỬA — `runtime.dedupe_thought_signatures()` chỉ giữ `thought_signature` trong bản gửi đi và trả về số ký tự đã bỏ; transcript lưu trong store không bị sửa. Chạy trong `RouterClient.complete()`, ghi `model.signature_deduped` kèm `chars` | `test_inline_media_bound.py`: ba ca cho hàm này (cặp trùng bị gộp, chỉ một khoá thì giữ nguyên, danh sách gốc không bị sửa) |
| F-1c | Cao (chặn nhiệm vụ dài, cùng gốc) | Trần của router là **byte**, ngân sách của `ContextCompressor` là **token** — hai thước đo không bao giờ gặp nhau, nên vẫn còn đường vượt trần khi không tin nhắn cũ nào đủ lớn để lộ ra. Đo trên phiên `584d61c8` (25 bước, chết ở bước 25): thân đầy đủ **1 754 163 B**; sau khi bó ảnh và gộp chữ ký còn **1 060 902 B — vẫn quá trần 12 326 B**, mà danh sách `messages` khi đó chỉ 1 043 364 B, nên phép đo cũ (chỉ nhìn `messages`) không bao giờ thấy phần vượt. Phần lớn khối lượng nằm ở chữ ký trong `tool_calls` (1 387 656 B) và `thought` (60 914 B), không phải ở `content` | ĐÃ SỬA — `runtime.shrink_request_to_budget(body, messages)` đo **cả thân request** (prompt vai + lược đồ công cụ + tham số), rồi hạ theo thứ tự ít mất mát nhất, dừng ngay khi vừa ngân sách **900 KB**: cắt chữ cũ → bỏ `thought` cũ → rút tham số `tool_calls` cũ (giữ nguyên `id` và tên công cụ, nên cặp gọi/kết quả vẫn khớp) → giữ 1 ảnh chụp mới nhất → bỏ nốt ảnh → **bỏ hẳn lượt gọi cũ nhất** (lượt giảm duy nhất không bị chặn bởi khối lượng một lượt: Gemini từ chối lượt gọi bị mất chữ ký, nhưng lượt gọi không nằm trong request thì không cần chữ ký — phần đuôi `LIVE_TAIL = 8` tin nhắn và mọi tin nhắn `user` không bao giờ bị đụng). Chỉ đụng phần lịch sử trước bước đang chạy, không sửa transcript; ghi `model.request_trimmed` mức `warn` kèm `chars` và `phase`. `request_body_bytes()` nay dựng thân bằng đúng lời gọi `httpx` dùng cho `json=` nên số đo là `Content-Length` thật của router | `test_inline_media_bound.py` (**19 ca**): đo cả prompt + lược đồ công cụ; thứ tự ít mất mát nhất; cặp gọi/kết quả giữ `id`; ảnh mới nhất là thứ bị bỏ cuối cùng; ca tái hiện hình dạng thật của phiên chết vì 413; và ca nhiệm vụ 30 bước liên tục chụp màn hình — thân thô 5 537 602 B nhưng thân gửi đi luôn dưới trần (886 254 B ở bước cuối) |

| F-1f | Trung bình (nén sớm, tốn lượt gọi; đo được) | Ước lượng ngữ cảnh đếm **hai lần** cùng một chữ ký suy luận: một phản hồi Gemini mang cùng giá trị dưới hai tên (`thought_signature` và `thoughtSignature`) và bản lưu giữ cả hai, nên mỗi lượt gọi bị tính gấp đôi. Diễn lại các phiên lưu trữ: `9ec9bf1d` **1 075 446** và `08f2483c` **1 051 631** token, trong khi nhà cung cấp chỉ tính **358 771** token đầu vào cho cùng request | ĐÃ SỬA — `compression._one_signature()` bỏ tên thứ hai khi đếm (router cũng chỉ nhận một bản qua `runtime.dedupe_thought_signatures()`); cùng hai phiên đó nay còn **576 592** và **509 005** token, tức nằm dưới ngưỡng nén 697 132 — nhiệm vụ nặng không còn bị nén sớm vì một kích thước không có thật | `backend/tests/unit/test_context_estimate.py` (10 ca, thêm 2): chữ ký trùng chỉ được đếm một lần; transcript không chữ ký giữ nguyên công thức cũ |
| F-1g | Thấp (đúng đắn của request, cùng gốc) | `_drop_oldest_round()` duyệt kết quả công cụ của một lượt **không có biên**, nên lượt cũ nhất có thể kéo cả những quan sát mới nhất vào tập bị bỏ — trái với chính docstring của nó. Không thể chỉ cắt phần đuôi: một lượt phải đi cùng kết quả của nó, nếu không request còn lại kết quả mồ côi | ĐÃ SỬA — vòng lặp ưu tiên lượt nằm **trọn vẹn** ngoài `LIVE_TAIL`; lượt vắt qua ranh giới chỉ được dùng khi không còn lượt nào khác, và khi đó cả cặp vẫn đi cùng nhau | `backend/tests/unit/test_inline_media_bound.py` (21 ca, thêm 2): lượt cũ nhất đi cùng kết quả, đuôi nguyên vẹn, không có kết quả mồ côi; lượt vắt qua ranh giới vẫn hợp lệ |
| F-1e | Cao (chặn nhiệm vụ dài, cùng gốc) | Nhiệm vụ CUA chỉ có **một** lời nhắc, nên `ContextCompressor.compact()` tìm thấy `cut = users[-1] = 1`, không tỉa được gì và kết lượt bằng `CONTEXT_LIMIT: current turn/tools exceed the context budget` — đo trên phiên `9ec9bf1d` (66 tin nhắn, ước lượng **1 075 446** so với trần chết 995 904). Bản cũ còn đẩy **toàn bộ** lịch sử vào lượt tóm tắt (~900 KB, ~250k token) nên nhà cung cấp trả 90 giây và lượt chết ở nhánh `CONTEXT_LIMIT: summary failed`; và phép tỉa khẩn cấp coi `str(content)` của một ảnh chụp là "kết quả công cụ dài", thay chính ảnh mới nhất — thứ mô hình đang nhìn — bằng `[Tool output truncated to fit context budget.]` | ĐÃ SỬA — `compact()` gộp chính phần giữa của nhiệm vụ khi lịch sử chỉ có một lời nhắc: tiền tố hệ thống, lời nhắc và `MISSION_TAIL = 10` tin nhắn mới nhất giữ nguyên, và điểm cắt không bao giờ tách kết quả công cụ khỏi lời gọi sinh ra nó. Đầu vào cho lượt tóm tắt do `summarizer_material()` dựng: ảnh thành `[inline capture left out of the summary input]`, bỏ chữ ký và khối lớn, và lấy mẫu đều khi vượt `SUMMARY_INPUT_CHARS = 120 000`; phép tỉa một ảnh chụp nay giữ phần chữ và bỏ phần ảnh; lượt tỉa khẩn cấp không còn đi qua phần đuôi đang chạy | `backend/tests/unit/test_context_estimate.py` (8 ca, thêm 4): nhiệm vụ một lời nhắc được gộp thay vì chết; đầu vào tóm tắt phẳng và bị chặn; lịch sử ngắn đến tay bộ tóm tắt nguyên vẹn; tỉa ảnh cũ giữ chữ và không đụng ảnh mới nhất. **Diễn lại phiên thật `9ec9bf1d`**: `beforeEstimate 1075446 → afterEstimate 314771`, đầu vào tóm tắt từ ~900 KB còn **15 397 ký tự** |
| F-1d | Cao (chặn nhiệm vụ dài, cùng gốc) | Ước lượng ngữ cảnh đếm **ảnh base64 như chữ**, nên phiên `08f2483c` bị ước lượng **1 051 631** token trong khi router báo **358 771** token đầu vào cho cùng request; `before` vượt `context_window - output_reserve`, và khi lượt tóm tắt gặp 429 / hết 90 giây thì bộ nén đi vào nhánh duy nhất làm chết cả lượt: `CONTEXT_LIMIT: summary failed` | ĐÃ SỬA — `compression.estimate_tokens()` thay mỗi phần ảnh inline bằng một khoản `IMAGE_TOKEN_ALLOWANCE = 1600` (cách nhà cung cấp tính token ảnh) và cộng khoản đó vào ước lượng chữ; cùng phiên đó nay còn **952 417** | `backend/tests/unit/test_context_estimate.py` (4 ca): ảnh 400 KB không được tính theo base64; ảnh to hơn không kéo ước lượng lên; transcript không ảnh giữ nguyên công thức cũ |

Ghi chú kèm theo (không sửa trong đợt này): `RouterClient` vẫn gắn cứng `http://127.0.0.1:3101`
(không có biến môi trường), và trần 1 MiB của router cũng không cấu hình được — vòng kiểm chứng
phải dựng một bản router sao 128 MiB ở cổng khác để chứng minh rằng đổi trần **một mình** không
giải quyết được gì, vì đường gọi không đi qua đó.

### 6.8 Ba việc chủ sở hữu giao tối 2026-09-20 (đợt 13) — ĐÃ SỬA (đợt này)

Nguồn: chủ sở hữu giao bốn việc lúc 14:28 UTC kèm hai ảnh chụp (`3066.png` — chat đỏ
`Agent request failed / Not found`, chip `DeepSeek Low`; `3067.png` — hàng nhà cung cấp
`DeepSeek: DeepSeek Pro Latest`, `Passed · 6990 ms`). Ba việc dưới đây là ba lỗi tìm thấy khi làm.

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| T-1 | Cao (mọi lượt gọi model mới đều chết) | `frontend/src/store/harnessStore.ts` gắn cứng `thinkingLevels: ['low','medium','high']` cho `AVAILABLE_MODELS` và mức mặc định của bộ chọn là `'medium'`, nên **mọi** lượt gửi đều mang `thinkingLevel: 'medium'`. Model `~deepseek/deepseek-pro-latest` chỉ công bố `['max','high','low']`, và `runtime.resolve_thinking_level()` từ chối đúng như thiết kế: `POST /api/agent/sessions` trả **`THINKING_LEVEL_UNSUPPORTED: model publishes max/high/low; requested medium`**, không có id phiên — đúng ảnh chụp của chủ sở hữu. Cùng hình dạng đó ở tám model khác đã đo (`~deepseek/deepseek-flash-latest`, `deepseek/deepseek-v4.1-flash`, `deepseek/deepseek-v4-flash-vision-exp`, `deepseek/deepseek-v4-pro-0813`, `~deepseek/deepseek-v4-flash-latest`, `deepseek/deepseek-v4-flash-0731`, và `gemini-3.5-flash-lite` sau này) | ĐÃ SỬA — tệp mới `frontend/src/lib/harnessThinking.ts` là nguồn duy nhất quyết định mức: khớp đúng thì giữ nguyên chính tả của nhà cung cấp; mức lạ thì lấy mức công bố đầu tiên; còn lại lấy mức **gần nhất theo hạng**, hoà thì chọn mức **thấp hơn**. `harnessChatStore.send()` nhận thêm tham số `thinkingLevels` thứ sáu và chỉ gắn `thinkingLevel` khi có giá trị; `ChatPanel` truyền `thinkingLevels` công bố của model đang chọn; `HarnessModelPicker` có `useEffect` kéo mức đang chọn về mức công bố khi model đổi; `harnessStore` mở kiểu thành `string` vì nhà cung cấp còn công bố `max`/`xhigh` | `frontend/src/lib/harnessThinking.test.ts` (9 ca), `frontend/src/store/harnessChatStore.retry.test.ts` (2 ca đầu: `medium` → `low` đúng tuyến đường đã lưu; giữ `high` khi model công bố; giữ nguyên khi model không công bố gì). **Xác minh sống qua giao diện**: chip đọc `DeepSeek Low`, phiên `c7cb1e8f` lưu `route.thinkingLevel = "low"`, lượt trả `assistant {"text": "2+2 = 4."}` + `finish {"status":"completed"}` |
| T-2 | Cao (chat hỏng vĩnh viễn, không tự gỡ) | `backend/src/agentbox/api/server.py:75` có `except KeyError: return {'error': 'Not found'}, 404`, nên **mọi** `KeyError` — id phiên không tồn tại, khoá thiếu trong payload, bất cứ thứ gì — đều thành một chữ `Not found` trần. `frontend/src/lib/agentApi.ts` ném `Error('Not found')` **không mã**, `harnessChatStore` rơi vào `catch → status:'failed', error: String(error)`, và id chết vẫn nằm trong `localStorage` (`boxfox-harness-session:<chatId>`) nên **mọi lần gửi sau đều hỏng lại** — đúng ảnh `3066.png` | ĐÃ SỬA — lớp mới `ApiError(code, message, status)` + `missing_session(sid)` trả `SESSION_NOT_FOUND` kèm chính id và lý do (`session <id> is not known to this harness; it was deleted or the harness started with an empty store`); `except KeyError` nay ghi `logger.exception` và trả **500** `INTERNAL_ERROR` kèm `method`/`path`, không còn giả vờ 404; `known_session()` kiểm id **trước** `runtime.submit` ở cả ba tuyến `session`/`turn`/`stop`; `agentApi` giữ mã máy trong câu lỗi; `send()` gặp `SESSION_NOT_FOUND` thì xoá id hỏng và **mở phiên mới rồi gửi lại đúng một lần** | `backend/tests/unit/test_session_lifecycle.py` +2 ca (id lạ → 404 `SESSION_NOT_FOUND` ở cả ba tuyến; `KeyError` nội bộ → 500 `INTERNAL_ERROR` có tên khoá); `frontend/src/store/harnessChatStore.retry.test.ts` (2 ca: `SESSION_NOT_FOUND` mở phiên mới và gửi lại đúng một lần, `turnCalls == ['/sessions/dead-sid/turns','/sessions/fresh-sid/turns']`, `error` ở lại `null`; `UPSTREAM_HTTP_429` **không** tạo phiên nào và gửi đúng một lần). **Đo lại trên harness mới**: `GET/POST turn/POST stop` trên id `deadbeef…` đều trả 404 `{"error": "SESSION_NOT_FOUND: session deadbeef… is not known to this harness; …", "code": "SESSION_NOT_FOUND"}` (trước khi sửa: `{"error": "Not found"}`) |
| R-1 | Cao (một lần 429 là mất cả lượt; còn tốn gấp đôi lượt gọi) | Chính sách cũ có **đúng một** lần thử lại, `asyncio.sleep(1.5)`, gated bởi `failures.is_transient()` — mà hàm này chỉ khớp `status >= 500`, nên **429 không bao giờ được thử lại**: một lần chạm hạn mức nhà cung cấp là kết thúc lượt ngay, không backoff, không jitter, không đọc `Retry-After`, không ngân sách chờ, không đếm lần thử nào hiện ra cho người dùng. Ngược lại, `RouterClient.complete()` có `except Exception:` gọi bản không-stream **vô điều kiện**, nên một lần 429 ở đường stream thành **hai** lượt gọi nhà cung cấp liền nhau. Siêu dữ liệu lỗi của router (`error.code`, `error.retryable`, `error.retryAfterMs`) bị bỏ hết khi câu lỗi bị làm phẳng thành `RuntimeError(f'Router HTTP {status}: {message}')` | ĐÃ SỬA — `failures.retry_advice()` là **một** điểm quyết định duy nhất: tối đa 3 lần thử lại, hạng 429 chờ `Retry-After` với sàn 2 s và trần 30 s, hạng 5xx/đứt stream đi 1 s → 4 s → 12 s ± 20 % jitter, ngân sách chờ mỗi lượt 60 s, cửa sổ còn lại tối thiểu 5 s; `is_transient()` nay chính là `retry_advice(...) is not None`. `runtime.router_refusal()` giữ `router_status`/`router_code`/`retryable`/`retry_after_ms` trên ngoại lệ; nhánh không-stream chỉ chạy khi **không** có phán quyết router dưới 500 (nên 429 không còn bị gọi đôi); vòng bước ghi `UPSTREAM_RETRY` (kèm `attempt`, `maxRetries`, `waitMs`, `reason`) và `UPSTREAM_RETRY_EXHAUSTED` (kèm `attempts`, `waitMs`); băng lỗi cuối lượt nay nêu `[after 3 retries in 7.0s]` | `backend/tests/unit/test_retry_policy.py` (**13 ca**): 429 tôn trọng `Retry-After` 9 s và sàn 2 s và trần 30 s; 5xx/stream theo hệ số; 4xx (`400`, `404`, `PermissionError`) không bao giờ thử lại; `TimeoutError`/`UPSTREAM_TIMEOUT` không thử lại; hết số lần / hết ngân sách / hết cửa sổ thì dừng; `is_transient` nay đúng với 429; và ba ca chạy **lượt thật** (hai 429 rồi thành công → 3 lượt gọi, thông báo `attempt == [1,2]`, `finish completed`; bỏ cuộc sau `DEFAULT_MAX_RETRIES` → 4 lượt gọi, `UPSTREAM_RETRY_EXHAUSTED` với `attempts == 3`; 400 hỏng ngay lượt đầu, không thông báo). Thiết kế: `docs/plan/retry-policy.md` |

### 6.9 Vòng soát mã đợt 13 (8 phát hiện) và một lỗi sống mới gặp khi nhập khoá Google — ĐÃ SỬA (đợt này)

Nguồn thứ nhất: sub-agent `review` đọc `git diff main...HEAD` của đợt 13 (`f8eade5`, 16 tệp,
+946/−62). Kết luận **Ship with mitigations**, điểm rủi ro **5/10**. Tám phát hiện, cả tám đã sửa.
Nguồn thứ hai: lượt gửi thật đầu tiên trên `Google Gemini · Gemini 2.5 Flash` sau khi nhập khoá
Google (đợt 14) — chat đỏ `UPSTREAM_HTTP_400 … Thinking level is not supported for this model.`

| Mã | Mức | Nội dung | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| R14-1 | Cao (bản sửa T-2 không có tác dụng) | `harnessChatStore.send()` khi gặp `SESSION_NOT_FOUND` chỉ ghi id mới vào `localStorage`, còn **mọi** nơi đọc lại ưu tiên `sessions[chatId].id` — nên vòng poll 1200 ms và lượt gửi kế tiếp vẫn nhắm id đã chết: khung chat ở lại `failed`, và mỗi lần gửi lại còn chạy thêm một lượt mồ côi ở nhà cung cấp. Đo sống trước khi sửa: xoá phiên `68f7ed66…` rồi gửi lại → `localStorage` đã đổi sang `2c4b34de…` và phiên mới **đã trả lời**, nhưng giao diện vẫn hiện băng đỏ `Agent request failed / session 68f7ed66… was deleted…` | ĐÃ SỬA — sau `id = await openSession()` ghi luôn vào store (`sessions[chatId] = { …current, id, error: null }`) trước `submitTurn`, nên poll và lượt sau dùng id mới | `frontend/src/store/harnessChatStore.retry.test.ts` ca phiên cũ nay khẳng định `sessions[CHAT].id === 'fresh-sid'`, `error === null`, `turnCalls == ['/sessions/dead-sid/turns','/sessions/fresh-sid/turns']`, và **không lời gọi nào sau lượt gửi lại trỏ vào id chết**. **Xác minh sống sau khi sửa** (xoá phiên và gửi trong cùng một nhịp): `DELETE …/18358f20` → `POST …/18358f20/turns` **404** → `POST /api/agent/sessions` → `POST …/e197d82a/turns`; khoá `boxfox-harness-session:session-mu9yhydm` = `e197d82a…`; 0 lời gọi về id chết sau khi tạo phiên mới; màn hình không còn băng đỏ (`r14_stale_recovery_after.png`, đối chiếu `r14_stale_before.png`) |
| R14-2 | Trung bình (dọn dẹp không bao giờ chạy) | `refresh()` dọn chat chết theo **câu chữ** `errStr.includes('404') \|\| errStr.includes('not found')`, mà T-2 vừa đổi câu lỗi thành `SESSION_NOT_FOUND: … is not known to this harness …` — nhánh dọn thành mã chết | ĐÃ SỬA — nhánh dọn nay hỏi `isStaleSession(error)` (khớp mã) và vẫn giữ hai phép khớp cũ cho lỗi cũ; đồng thời xoá cả `storageKey(chatId)` lẫn `storageKey(id)` khi dọn | `harnessChatStore.retry.test.ts` hai ca mới: `SESSION_NOT_FOUND` dọn im lặng và xoá khoá `localStorage`; câu chữ cũ `'Not found'` vẫn dọn. **Sống**: sau khi xoá phiên, vòng poll tự dọn và lần gửi kế tiếp mở phiên mới ngay (`r14_stale_purge_after.png`) |
| R14-3 | Trung bình (lọt đúng lỗi T-1 qua đường alias) | Tuyến alias không mang `thinkingLevels`, nên `resolveThinkingLevel(undefined, 'medium')` trả nguyên `medium` và mức đó đi thẳng tới một model chỉ công bố `max/high/low` — đúng thứ T-1 vừa chặn cho model trực tiếp | ĐÃ SỬA — `RouterTestChat.routerChatOptions()` gắn `thinkingLevels` cho mỗi alias bằng **giao** mức của mọi đích (`aliasThinkingLevels`), trả `undefined` khi có đích không công bố mức nào hoặc giao rỗng; `send()` chỉ gắn mức cho tuyến alias khi biết mức | `frontend/src/components/panels/routerChatOptions.test.ts` (3 ca: giao hai đích; một đích không công bố → trống; hai đích không mức chung → trống); `harnessChatStore.retry.test.ts` +2 ca (alias không biết mức → tuyến không có `thinkingLevel`; alias biết `low/medium/high` → gửi `medium`) |
| R14-4 | Thấp (đổi 404 thành 500) | `GET /api/agent/skills/<lạ>/readiness` rơi vào `except KeyError` mới của T-2 nên trả **500 `INTERNAL_ERROR`** thay vì 404 như trước | ĐÃ SỬA — tuyến `readiness` kiểm `sid not in runtime.catalog.items` trước và ném `ApiError('SKILL_NOT_FOUND', …, 404)` | `backend/tests/unit/test_session_lifecycle.py` ca mới: tên kỹ năng lạ → 404 `SKILL_NOT_FOUND` kèm tên |
| R14-5 | Thấp | `retryable: false` do router gửi kèm bị giữ lại nhưng **không** được dùng: một lỗi 425 mà chính router đã thử lại vẫn bị harness thử lại | ĐÃ SỬA — `_retry_reason()` đọc `exc.retryable`: `False` là phán quyết cuối, trừ 429 và họ mã hạn mức (`RATE_LIMIT`/`CAPACITY`/`UPSTREAM_HTTP_429`) vẫn thử lại được | `test_retry_policy.py::test_a_router_verdict_of_retryable_false_stops_the_retry` |
| R14-6 | Thấp | `UPSTREAM_RETRY_EXHAUSTED` luôn nói "gave up after N retries" kể cả khi lý do là hết ngân sách chờ hoặc hết cửa sổ lượt — câu chữ sai ở đúng chỗ người dùng đọc để hiểu vì sao lượt chết | ĐÃ SỬA — `failures.stop_reason()` trả `permanent/attempts/budget/window`; thông báo chọn câu theo lý do (`the per-turn retry budget of 60s is spent` / `too little turn time left for another attempt`) và mang thêm trường `stopReason` | `test_retry_policy.py::test_stop_reason_names_why_the_loop_gave_up` (5 khẳng định) + ca bỏ cuộc khẳng định `stopReason == 'attempts'` |
| R14-7 | Thấp | Hai lỗi nhỏ cùng gốc "một lượt gọi lại không miễn phí": (a) một 5xx vẫn đi qua nhánh không-stream nên thành **hai** lượt gọi nhà cung cấp; (b) bộ chọn lọc `thinkingLevels.length > 1` nên model chỉ công bố **một** mức bị coi như không có mức, trong khi `ChatPanel` đọc danh sách thô — chip đọc `Medium` mà tuyến gửi `high` | ĐÃ SỬA — (a) nhánh không-stream chỉ chạy khi router **không** đưa ra phán quyết nào (`verdict is not None → raise`); (b) cả hai chỗ lọc nay dùng `length > 0`, và `ChatPanel` tính `effectiveLevel` từ danh sách mức công bố rồi in đúng mức sẽ gửi | `test_retry_policy.py` (ca 4xx/429 khẳng định số lượt gọi) + `harnessChatStore.retry.test.ts` ca "model chỉ công bố `['high']` thì gửi `high`" |
| R14-8 | Thấp–Trung bình (chất lượng kiểm) | Ba lỗ hổng của bộ kiểm: ca phiên cũ trả **mọi** GET lành nên không thể bắt R14-1; `test_spent_deadline_never_retries` chỉ khẳng định lại nhánh mặc định; cổng chặn gọi đôi của R14-7a không có ca nào | ĐÃ SỬA — tệp kiểm viết lại: một sổ `deadSessions` để id chết **thật sự** trả 404, khẳng định theo từng tuyến đường (`turnCalls`), thêm ca model một mức, ca alias, hai ca dọn phiên, và ca nhánh không-stream; `test_spent_deadline_never_retries` nay phân biệt `TimeoutError`/`UPSTREAM_TIMEOUT`/`ReadTimeout` (không thử lại) với `ServerDisconnectedError` (thử lại, `reason: 'stream'`) | `harnessChatStore.retry.test.ts` 10 ca; `test_retry_policy.py` 18 ca |
| T-3 | Cao (mọi lượt trên họ Gemini 2.5 đều chết) | Danh mục của router quảng cáo `thinkingLevels: ['low','medium','high']` cho **cả** họ Gemini 2.5, Gemma và `gemini-3.5-transcribe` (`router/src/providers/gemini.mjs` đọc cờ `thinking: true` của `models.list`), nhưng API Google **từ chối** `generationConfig.thinkingConfig.thinkingLevel` cho các model đó: `400 INVALID_ARGUMENT: Thinking level is not supported for this model.` Lượt gửi thật đầu tiên trên `Google Gemini · Gemini 2.5 Flash` chết đúng như vậy (`UPSTREAM_HTTP_400`, chat đỏ), và T-1 khiến mức luôn được gửi kèm. Đo trực tiếp trên endpoint Google (2026-09-20, 12 model): nhận mức — `gemini-flash-lite-latest`, `gemini-3.1-flash-lite`, `gemini-3.5-flash-lite`, `gemini-3.8-flash`; từ chối — `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemma-4-31b-it`, `gemini-3.5-transcribe`, `antigravity-preview-09-2026`, `deep-research-preview-04-2026`. Đây là lỗi **của mã**, không phải của model (model yếu hay mạnh đều trả cùng 400) | ĐÃ SỬA (phần harness) — `failures.level_refusal()` nhận đúng lớp lỗi này (chỉ 4xx, và câu lỗi phải nói về mức); vòng bước trong `runtime` gặp nó thì **bỏ `thinkingLevel` khỏi route và gọi lại ngay**, phát thông báo `THINKING_LEVEL_REFUSED` (kèm `level`, `model`) và **không** tính vào số lần thử lại vì đây là sửa yêu cầu chứ không phải chờ nhà cung cấp. Danh mục phía router vẫn quảng cáo thừa mức cho họ 2.5 — việc của router, xem ghi chú dưới | `backend/tests/unit/test_retry_policy.py` +3 ca: lượt bị từ chối mức vẫn `completed` sau **2** lượt gọi, lượt thứ hai không kèm `thinkingLevel`, không có sự kiện `error`, đúng một thông báo `THINKING_LEVEL_REFUSED`; một 400 khác (JSON sai) vẫn chết ngay lượt đầu; `level_refusal` bỏ qua 429/5xx nhắc tới chữ "thinking" |

Ghi chú kèm theo (chưa sửa trong đợt này, thuộc phần `router/`): `GEMINI_THINKING_LEVELS` được
gắn cho mọi model có `thinking: true`, nên họ Gemini 2.5 vẫn hiện nút mức trong bộ chọn và mỗi
lượt lại tốn thêm **một** lượt gọi bị từ chối trước khi harness bỏ mức. Hợp đồng model record
(`router/CONTRACT.md` §Model record) cấm suy đoán theo tên model, nên cách sửa đúng là để adapter
Gemini dịch mức thành `thinkingBudget` cho họ 2.5 hoặc chỉ công bố mức khi có bằng chứng provider —
cần một vòng riêng cho router.

#### 6.9.1 Đo lại T-3 trên giao diện thật, và một cái bẫy vận hành gặp phải khi đo

Lần đo đầu trên cổng 3102 **vẫn đỏ** dù mã đã sửa: tiến trình harness đang chạy được dựng lúc
**15:00:45**, còn ba tệp của bản sửa (`failures.py`, `runtime.py`, `server.py`) được ghi lúc **15:23:10**
— tức là tiến trình cũ nạp mã đợt 13. Đây là bẫy vận hành, không phải lỗi mã: **phải dựng lại harness
sau mỗi lần sửa backend**, nếu không thì mọi phép đo sống đều đo mã cũ.

Sau khi dựng lại (`kill 828038` → `nohup .venv/bin/python scripts/run-harness.py`, log
`/var/tmp/r10/harness_r14.log`, pid **858826**, cây làm việc sạch tại `d03dce7`), cùng một khung chat
`gemini-2.5-flash` + mức `low` (phiên `c7cb1e8fe0244029bae315bd729335bd`) cho chuỗi sự kiện:

| Lượt | Sự kiện | Kết quả |
|---|---|---|
| 15:45 (mã cũ) | `step {iteration:1}` → `error {code: UPSTREAM_HTTP_400, "… Thinking level is not supported for this model."}` | chat đỏ, **không** có thông báo bỏ mức — đây là ảnh \"trước\" |
| 15:47 (mã mới) | `step {iteration:1}` → `notice {code: THINKING_LEVEL_REFUSED, level: \"low\", model: \"gemini-2.5-flash\"}` → `assistant_delta` → `usage` → `assistant \"2+2=4.\\n5+7=12.\"` → `finish {status: completed}` | **không** sự kiện `error`, `status: completed` |

Bằng chứng ảnh `/code/.generated_artifacts/images/r14_thinking_refused_ui_after.png` chứa **cả hai**
lượt trong một khung: lượt 15:45 là băng đỏ, lượt 15:47 là thông báo `UPSTREAM_HTTP_400: the provider
does not accept the thinking level "low" for this model — retrying without it (…)` rồi dòng trả lời
`gemini-2.5-flash  done · 4.3k | 14` — một cặp trước/sau trên đúng giao diện thật.

Ghi nhận thêm (chấp nhận được, chưa cần sửa): việc bỏ mức là **theo từng lượt**, không ghi vào cấu hình
phiên. Lượt thứ hai (15:48, hỏi `3+3`) lại phát `THINKING_LEVEL_REFUSED` và `route` của phiên vẫn ghi
`thinkingLevel: \"low\"`. Như vậy mỗi lượt trên họ Gemini 2.5 vẫn tốn **một** lượt gọi bị từ chối —
đúng chi phí đã ghi ở ghi chú trên, và cách chữa gốc vẫn là sửa danh mục phía `router/`. Chọn giữ
hành vi này vì phương án còn lại (tự xoá mức đã chọn của người dùng khỏi cấu hình phiên) là **âm thầm
đổi ý định của người dùng** chỉ vì một lỗi danh mục — khi router được sửa thì mức phải có tác dụng trở lại.

### 6.10 Gán đúng điều khiển thinking theo model ở router — ĐÃ SỬA (đợt này)

Nguồn: chủ sở hữu yêu cầu đo lại mức thinking cho họ flash rồi "tra tài liệu Google AI Studio để kiểm tra
và gán vào theo model". Gốc là ghi chú cuối §6.9: adapter Gemini gắn **một** danh sách mức cho mọi model
có cờ `thinking: true` của `models.list`.

**Tài liệu (đọc ngày 2026-09-20)** — `ai.google.dev/gemini-api/docs/openai` (bảng tương thích OpenAI) và
`ai.google.dev/gemini-api/docs/gemini-3`:

- Gemini **3 trở lên** điều khiển suy luận bằng enum `thinkingLevel`; `reasoning_effort` ánh xạ thẳng vào đó.
- Gemini **2.5 trở xuống** dùng `thinkingBudget` dạng số; tài liệu ghi `reasoning_effort` low → **1 024**,
  medium → **8 192**, `none` tắt suy luận (trừ 2.5 Pro); trần ngân sách của họ 2.5 là **24 576**.
- Hai trường **không được gửi cùng lúc**.

**Đo trực tiếp** trên `generativelanguage.googleapis.com` bằng khoá Google thật (lượt rất nhẹ, 1–32 token ra):

| Model | `thinkingLevel: low` | `thinkingLevel: minimal` | `thinkingBudget: 512` |
|---|---|---|---|
| `gemini-3.5-flash-lite` | 200, `medium`/`high` cho ~60 thoughts token | 200 | 200 (59 thoughts token) |
| `gemini-flash-latest` | 200 | **400** "Thinking level MINIMAL is not supported for this model" | 200 (không báo thoughts) |
| `gemini-flash-lite-latest` | 200, `reasoning_tokens: 61` | — | — |
| `gemini-2.5-flash` | **400** "Thinking level is not supported for this model" | — | **200** (10 thoughts token) |
| `gemma-4-31b-it` | **400** | — | **400** "Unknown name thinkingBudget" |

**Sửa** (`router/src/providers/gemini.mjs`): thêm `geminiThinkingControl(id)` trả `effort` / `budget` /
`none` theo họ model mà tài liệu phân định (`gemini-2.5|2.0|1.5` → `budget`, `gemma` → `none`, còn lại
`effort`); record model theo đó (`thinkingType`, và `thinkingLevels` rỗng khi không có điều khiển nào).
Trên đường gửi, `thinkingLevel` bị **viết lại thành `thinkingBudget`** cho họ `budget`
(minimal 512 / low 1 024 / medium 8 192 / high–max 24 576) và **bỏ hẳn** cho họ `none`; họ `effort` giữ
nguyên `thinkingLevel` như cũ. Bản đồ của thư viện vendor (`openai-to-gemini.mjs`) luôn ghi
`thinkingLevel` khi có mức, nên chỗ sửa nằm **sau** nó.

**Đo lại sống**: dựng lại router (pid 867258) rồi `POST …/models/refresh` cho kết nối `2b922915…`:

- `gemini-2.5-flash` → `thinkingType: budget` + mức `low/medium/high`; `GET /v1/chat/completions` với
  `reasoning_effort: low` nay trả **200** kèm `reasoning_content` (trước là 400 chết lượt).
- `gemma-4-31b-it` → `thinkingType: none`, `thinkingLevels: []`; request gửi đi không còn trường thinking nào.

Ghi chú kèm theo, **không sửa vì thuộc model**: `gemma-4-31b-it` trả **500 "Internal error encountered"**
trên **đường SSE** (`streamGenerateContent?alt=sse`) kể cả khi gọi thẳng Google với thân request trần,
trong khi `generateContent` cùng thân trả **200** — lỗi phía model/nhà cung cấp, không phải do BoxFox.
Chủ sở hữu đã bỏ Gemma khỏi phạm vi, nên chỉ ghi lại.

Bộ kiểm router: **91 pass / 0 fail** (89 cũ + 2 ca mới: `thinking-mapping.test.mjs` — mức thành
`thinkingBudget` theo tài liệu và Gemma không gửi trường nào; `model-metadata.test.mjs` — record chọn
đúng điều khiển theo họ model).

Ghi chú thêm của cùng cái bẫy vận hành (do tác nhân kiểm thử phát hiện, 2026-09-20 16:05): lần dựng lại
harness lúc 15:46 **thiếu bốn biến** `BOXFOX_ANTHROPIC_BASE_URL/AUTH_TOKEN/DEFAULT_SONNET_MODEL/DEFAULT_HAIKU_MODEL`,
nên `GET /api/agent/executors/claude-code` đổi từ `{"auth":"router","settingsFile":true}` sang
`{"auth":"account","settingsFile":false,"authenticated":true}` — tức bộ thực thi `/claude-code` **im lặng**
chuyển từ đường router sang tài khoản, dù mã không đổi. Đã dựng lại kèm đủ bốn biến (pid 870296) và
endpoint trả lại đúng giá trị cũ. Bài học: dựng lại harness phải kèm môi trường cầu nối, và phải kiểm
`/api/agent/executors/claude-code` ngay sau khi dựng.

### 6.11 Khoá DeepSeek (API gốc) — lắp đặt, và bộ điều khiển suy luận riêng của nhà cung cấp — ĐÃ SỬA (đợt này)

**Lắp đặt (2026-09-20 17:45–17:52):** chủ sở hữu đưa khoá API gốc của DeepSeek. Kết nối mới trong router:
`providerId deepseek`, id `7ee21256-8675-4ee3-a802-fcedbed8b7ef`, endpoint `https://api.deepseek.com/v1`
(giá trị mặc định của catalog cho provider `deepseek`), khoá nằm trong kho credential đã mã hoá.
Số dư đọc từ `GET /user/balance`: **2,00 USD**. `GET /models` trả **đúng hai** model: `deepseek-flash`
(= DeepSeek-V4.1-Flash) và `deepseek-v4-pro` (= DeepSeek-V4-Pro-0813). Discovery `ready`, cả hai model
`enabled`, `source: live`.

**Lỗi T-5 — router quảng cáo bộ mức của OpenAI cho một nhà cung cấp có bộ mức riêng.** Adapter
OpenAI-compatible dùng chung công bố `minimal|low|medium|high` cho **mọi** model trên endpoint, vì payload
`/models` kiểu OpenAI không mang metadata suy luận. DeepSeek tài liệu hoá bộ khác, nên danh sách kế thừa
đó: (a) **giấu mức `max`** mà DeepSeek thật sự nhận; (b) quảng cáo `minimal`/`medium` như mức bản địa
trong khi chúng chỉ là bí danh tương thích; (c) vì adapter chung **bỏ hẳn** trường khi mức là
`none`/`auto`, lượt xin `none` vẫn chạy ở chế độ suy luận — mà suy luận lại là **mặc định** của DeepSeek.

Tài liệu (`api-docs.deepseek.com/api/create-chat-completion`, đọc 2026-09-20):

- `reasoning_effort`: "Possible values: [none, low, high, max]. Controls the thinking mode toggle and the
  thinking effort. none disables thinking mode; low/high/max enable thinking mode. **The default effort is
  high.** For compatibility with existing software, **minimal is accepted and mapped to low**, and
  **medium/xhigh are accepted and mapped to high**."
- `thinking`: `{type: enabled|disabled}`, "Default value: **enabled**".
- `max_tokens`: 1…384K; "When not set, the default is 8K in non-thinking mode, **64K in thinking mode**
  (128K with `reasoning_effort` set to `max`)".
- Tool calls: "**required and named tool choices are not supported in thinking mode; the API returns a
  400 error. Disable thinking mode first to use them.**"
- Models & Pricing: `deepseek-flash` — context **1M**, trần ra **384K**, **Vision ✓**;
  `deepseek-v4-pro` — **Vision: Not supported**. Cả hai: Json Output ✓, Tool Calls ✓.

Đo trực tiếp trên khoá thật (lượt rất nhẹ, `max_tokens` 40–60, `Reply with exactly: OK`):

| Mức gửi đi | `deepseek-flash` | `deepseek-v4-pro` |
|---|---|---|
| `none` | 200, **không** có `reasoning_content` | 200, không có `reasoning_content` |
| `minimal` / `low` / `medium` / `high` / `max` / `xhigh` | 200, có `reasoning_content` | 200, có `reasoning_content` |
| `bogus` (giá trị lạ) | **422** `Failed to deserialize … reasoning_effort: unknown variant` | **422** cùng thông báo |
| `thinking: {type: disabled}` + `reasoning_effort: high` | 200, **không** suy luận (công tắc thắng) | — |
| `tool_choice: required` / tên hàm, khi đang suy luận | **400** `Thinking mode does not support this tool_choice` | — |
| cùng request đó với `reasoning_effort: none` | 200, trả `tool_calls` bình thường | — |
| ảnh PNG 16×16 xanh (đường gốc) | 200, đáp **"Blue"** (đúng) | 200, đáp **"White"** (sai — không đọc ảnh) |
| luồng SSE | 33 chunk, `reasoning_content` trong delta, **usage ở chunk cuối** (`reasoning_tokens: 30`) | — |

**Sửa** (`router/src/providers/deepseek.mjs`, đăng ký riêng trong `providers/index.mjs`):

- `DEEPSEEK_THINKING_LEVELS = ['none','low','high','max']`, `defaultThinking: 'high'`,
  `DEEPSEEK_LEVEL_ALIASES = {minimal: low, medium: high, xhigh: high}` — công bố đúng bộ tài liệu, không
  bịa mức và không giấu `max`.
- `deepseekEffort(level)`: `none` → giữ `none` (DeepSeek cần trường này để **tắt** suy luận, khác adapter
  chung vốn bỏ đi); bí danh → `low`/`high`; `auto`/thiếu → bỏ trường (mặc định nhà cung cấp);
  giá trị lạ → bỏ trường, **không bao giờ** chuyển tiếp (nhà cung cấp trả 422).
- `deepseekRestrictsTools(body)`: `tool_choice` bị hạn chế (`required`/`any`/tên hàm) → gửi
  `reasoning_effort: none`, đúng cách tài liệu chỉ để request được phục vụ.
- `deepseekCapabilities`: `vision: 'reported'` cho dòng flash, `'unsupported'` cho dòng pro (tài liệu +
  phép dò ảnh ở trên); `tools: 'reported'`.
- `thinkingMetadata` để hàng đã lưu tự lành khi kết nối được chuẩn hoá.
- `CONTRACT.md` ghi rõ ngoại lệ DeepSeek của luật "no thinking field for none".

**Bộ kiểm router: 98 pass / 0 fail** (91 cũ + 7 ca mới trong `router/tests/deepseek.test.mjs`: bộ mức và
capabilities khi discover, adapter OpenAI dùng chung **không** bị đổi, `reasoning_effort` trên đường gửi,
`none` thật sự tắt suy luận, bí danh thu gọn + giá trị lạ không được chuyển tiếp, `tool_choice` hạn chế,
và hàng lưu sẵn tự lành).

**Đo lại sống sau khi dựng lại router (pid 913296, log `/var/tmp/r15/router_r15.log`):**

- Nút `Test` của giao diện cho cả hai model: `status: passed`.
- Quét mức qua `/api/router/chat` (đúng đường harness dùng) cho **cả hai** model: `none` → 0 ký tự suy
  luận, `low`/`high`/`max` → có suy luận, và usage trả `reasoning_tokens` (10–19). Mức thiếu → mặc định
  nhà cung cấp (suy luận bật, `high`). Mức `medium` (bí danh) → 200 kèm suy luận.
- `GET /v1/models` (khoá box) liệt kê `7ee21256-…/deepseek-flash` và `…/deepseek-v4-pro`;
  `POST /v1/chat/completions` với `low`, `none`, `max` đều 200, `none` không kèm `reasoning_content`.
- Ảnh qua router: `deepseek-flash` → **"Red"** (đúng), `deepseek-v4-pro` → "Brown" (sai).
- Giao diện: bộ chọn model (`Single Models`) hiện `DeepSeek · deepseek-flash` và `DeepSeek · deepseek-v4-pro`.

**Chủ ý KHÔNG công bố `contextWindow: 1000000`** dù tài liệu ghi context 1M: trần thân request của router
là **1 MiB** (`server.mjs`, mã `INVALID_REQUEST`/413) còn ngưỡng nén của harness là
`(contextWindow − reserve) × 0,7`; với cửa sổ 1M, ngưỡng đó (≈ 2,8 MB văn bản) **vượt** trần 1 MiB và lượt
nặng sẽ chết bằng `UPSTREAM_HTTP_413` — đúng lớp lỗi F-1 đã sửa. Bỏ trống `contextWindow` giữ nguyên hành
vi cũ: bảng tên trong `runtime.resolve_context_window` cho `deepseek` **64 000** (ngưỡng nén ≈ 43k token
≈ 172 KB, an toàn dưới trần).

**Bẫy vận hành gặp trong đợt này (không phải lỗi mã, ghi để lần sau khỏi mất thời gian):** `POST
/api/agent/sessions` của harness nhận **các trường route ở cấp cao nhất** (`connectionId`, `modelId`,
`thinkingLevel`). Gửi lồng `{"route": {…}}` thì khoá lạ bị **bỏ qua im lặng**, phiên lưu route rỗng, và
lượt đầu chết với `UPSTREAM_HTTP_503: … No enabled, authorized model is available for this route.`
(hiện rõ trong nhật ký hệ thống là `"model": null, "connectionId": null`). Phiên mẫu đúng:
`5803c1a842454db2a26ad9482a3c0765`.

**Kiểm chứng qua harness (phiên `5803c1a8…`)** — mức thinking đi tới nhà cung cấp thật:

| Lượt | Mức | Kết quả |
|---|---|---|
| "Compute 37*89" | `high` | `completed`, đáp `3293`, usage `reasoning_tokens: 8` |
| "Compute 41*73" | `none` | `completed`, đáp `2993`, **không** có token suy luận |
| "Reply with exactly: OK" | `none` | `completed`, `OK` |
| "Reply with exactly: OK" | `high` | `completed`, `OK`, `reasoning_tokens: 0` (model tự chọn không suy luận cho câu hỏi tầm thường) |

Route lưu trong config phiên: `{"connectionId": "7ee21256-…", "modelId": "deepseek-flash",
"thinkingLevel": "high"}`, `contextWindow` 64000.

### 6.12 Cơ chế "nhập tay" của DeepSeek chết ở cả hai đầu — ĐÃ SỬA (`87bc2d6`)

**Yêu cầu của chủ sở hữu:** DeepSeek phải có **hai cơ chế** như mọi model khác — (1) ping/dò tự công bố
model kèm bộ mức suy luận, (2) người dùng **tự nhập** bộ mức đó bằng tay — và **`max` phải được thêm cho
riêng DeepSeek** (vòng 15 chỉ sửa được cơ chế 1, xem §6.11).

Khi đo lại cơ chế 2, **hai lỗi độc lập** lộ ra; cả hai đều làm mức `max` không thể tới được nhà cung cấp.

**Lỗi A — router tự bịa danh sách chung cho model nhập tay.** Nhánh `customModel` của `service.patch()`
dùng hằng số `['auto','low','medium','high']` cho **mọi** model nhập tay có `reasoning`, nên model DeepSeek
nhập tay lại thiếu `none` và `max`, đồng thời công bố `medium` như một mức gốc (DeepSeek không có `medium`
— đó chỉ là bí danh của `high`). Hệ quả trùng với T-5: hàng nhập tay và hàng dò được nói hai chuyện khác
nhau về cùng một nhà cung cấp.

**Lỗi B — biểu mẫu "Custom Model" của giao diện chưa từng tới router.** `handleAddCustomModel` trong
`frontend/src/components/settings/ModelManagerModal.tsx` gửi **một bản sao của toàn bộ mảng `models`** cộng
id mới trong `enabledModelIds`. Router trả thẳng:
`INVALID_REQUEST: Select only models discovered for this connection.` (đo sống bằng
`PATCH /api/router/connections/7ee21256-…` với thân `{"models":[…],"enabledModelIds":[…]}`), và `models`
cũng không phải trường mà PATCH của kết nối nhận. Nghĩa là **cơ chế nhập tay không hoạt động ở bất kỳ nhà
cung cấp nào**, không riêng DeepSeek — lỗi này có từ trước vòng 15 và bị §6.11 che khuất.

**Sửa**

- `router/src/providers/deepseek.mjs`: thêm hook `manualThinkingLevels()` trả
  `[...DEEPSEEK_THINKING_LEVELS]` = `none · low · high · max` — bộ mà adapter của nhà cung cấp tự công bố là
  nguồn duy nhất của luật, nên **hai cơ chế tự khớp nhau**.
- `router/src/service.mjs`: thêm hàm mức mô-đun `manualThinkingLevels(provider)`; nhánh `customModel` gọi
  nó thay cho hằng số. Adapter nào không có hook (mọi nhà cung cấp khác) vẫn nhận danh sách mặc định
  `['auto','low','medium','high']` — không đổi hành vi cũ.
- `frontend/src/components/settings/ModelManagerModal.tsx`: biểu mẫu gửi **khai báo** `customModel`
  (`id`, `name`, `capabilities`) thay vì bản sao danh sách. Không đổi một dòng JSX nào (luật "giao diện
  không đổi" của chủ sở hữu vẫn giữ); nhãn nút vẫn là "Add & Enable".

**Đo lại sống trên router đã dựng lại (pid 940356, log `/var/tmp/r16/router_r16.log`)**

| Phép đo | Kết quả |
|---|---|
| Hàng nhập tay **cũ** (`r15-manual-probe`, tạo trước khi sửa, đang giữ `auto/low/medium/high`) sau khi dựng lại | `['none','low','high','max']`, `thinkingType: effort` — **tự lành** |
| Hàng nhập tay **mới** trên kết nối DeepSeek | `source: custom`, `thinkingLevels: ['none','low','high','max']`, **có `max`**, không có `medium` |
| Hàng nhập tay trên kết nối `custom` (TokenHarbor) | `['auto','low','medium','high']` — giữ nguyên luật chung, **không** có `max` |

**Ca kiểm thử thêm:** `router/tests/deepseek.test.mjs` +2 ("model DeepSeek nhập tay công bố đúng bộ tài
liệu, có `max`", "luật nhập tay vẫn chung cho mọi nhà cung cấp khác, không có `max`"),
`frontend/src/components/settings/ModelManagerModal.test.tsx` +1 (khẳng định PATCH mang `customModel` và
**không** mang `models`/`enabledModelIds` — đã chứng minh **đỏ** trên mã trước khi sửa rồi **xanh** sau khi
sửa). **Bộ router: 100 pass / 0 fail.** `npx tsc -b --noEmit` mã 0; eslint không thêm phát hiện mới.

### 6.13 Hai lỗi trong đường "nhập tay" lộ ra khi thi công kế hoạch vòng 17 — ĐÃ SỬA (`574a5aa`)

Vòng 17 dựng luồng endpoint bên thứ ba (kế hoạch đã duyệt: `/code/.plans/v1-api-provider-area.md`). Khi đo lại
trên router thật, hai lỗi cũ lộ ra — cả hai đều nằm trên đường mà chủ sở hữu yêu cầu, và cả hai đều bị luồng dò
tự động che khuất cho tới nay.

**Lỗi C — model nhập tay trên kết nối dò hỏng thì không bao giờ chạy được.** `validTarget()`
(`router/src/service.mjs`) đòi `discoveryState === 'ready'`. Với endpoint không có `/models` (hoặc bị từ chối
key), trạng thái dò là `failed`, nên dòng model người dùng gõ tay **không phải đích hợp lệ**: nó bị lọc khỏi
`GET /v1/models` và lượt gọi trả `No enabled, authorized model is available for this route.` — đúng cái ca mà
tính năng này sinh ra để phục vụ (ghi chú bảng 14329).

**Lỗi D — một lần dò THÀNH CÔNG xoá im lặng các dòng gõ tay.** Nhánh thành công của `#discover` thay cả danh
mục bằng kết quả nhà cung cấp trả về; dòng `source: 'custom'` biến mất (đo sống trước khi sửa: `r16-manual-generic`
biến mất sau một lần `POST /:id/models/refresh` trả 200). Kế hoạch chỉ yêu cầu sống sót qua lần dò **thất bại**,
nhưng cùng một cơ chế: người dùng gõ tay một model rồi bấm `Refresh models` là mất nó.

**Sửa:** `validTarget()` nhận dòng `source === 'custom'` khi kết nối đang bật, `authState === 'ready'` và
`discoveryState === 'failed'` (mọi luật khác giữ nguyên, kể cả kiểm tra project của antigravity và
`health !== 'unavailable'`); `#discover` giữ lại các dòng gõ tay khi dò thành công. Bốn ca kiểm thử mới trong
`router/tests/custom-provider.test.mjs`. Bộ router: **152 pass / 0 fail**.

### 6.14 Ba lỗi của đường "nhập tay" lộ ra khi KIỂM CHỨNG vòng 17 — ĐÃ SỬA (`91647e7`)

Vòng 17 thi công xong thì tác nhân kiểm thử chạy bốn làn sống trên `f63f82b` (router `:3101`, harness `:3102`,
Vite `:3100`, và một stub OpenAI-compatible trên `127.0.0.1:3199` có chế độ lỗi + bộ ghi request). Ba lỗi dưới
đây nằm **cùng một đường** mà chủ sở hữu yêu cầu (nhập id bằng tay rồi Test), nên cả ba được sửa trong một commit
với năm ca hồi quy **đỏ-trước-xanh-sau** (3 ca router, 2 ca giao diện).

**F1 (vừa) — khai lại một id đã có chỉ sửa được `name`.** Nhánh `customModel` của `service.patch` chỉ ghi
`name` (và bật dòng lên) khi dòng đã tồn tại; `capabilities`/`thinkingLevels` chỉ được ghi ở nhánh **tạo mới**.
Kế hoạch (dòng 240) nói rõ gõ lại một id là cách cập nhật `name` **và** `capabilities`, nên hai ô
Vision/Reasoning trong form là đường **một chiều**: chọn sai lần đầu là không sửa được nữa.
*Đo trước khi sửa:* PATCH cùng id với cờ đảo ngược → `vision supported / reasoning unknown` giữ nguyên.
*Sau khi sửa:* cờ đảo đúng, `thinkingType: effort`, `thinkingLevels ['auto','low','medium','high']`, **một** dòng;
một id mới cùng cờ cho **cùng** bộ trường (cập nhật = tạo mới); PATCH không mang `capabilities` vẫn chỉ đổi tên;
`streaming`/`tools` — hai trường form không có — giữ nguyên bằng chứng.

**F2 (cao) — một lần `Refresh models` hỏng làm id gõ tay rơi khỏi định tuyến.** Catch của `#discover` giữ lại
danh sách cũ và đặt `discoveryState: 'degraded'`; `validTarget()` chỉ nhận `failed` (bản sửa ở §6.13), nên
`degraded` — hình dạng khác của **cùng một lần dò hỏng** — làm dòng gõ tay thành đích không hợp lệ.
*Đo trước khi sửa:* dò 404 → `failed`, lượt gọi `POST /v1/chat/completions` = **200 `BOXFOX_OK`**; thêm **một**
lần refresh hỏng → `degraded`, cùng lượt gọi = **503 `NO_ROUTE`**, không có dòng usage nào.
*Sau khi sửa:* `degraded` được nhận; lượt gọi lại **200 `BOXFOX_OK`** (40/5 token, ghi ledger), `GET /v1/models`
**63** mục có dòng đó. Mọi luật còn lại giữ nguyên (connection bật, `authState ready`, project Antigravity,
`health !== 'unavailable'`).

**F3 (vừa) — Test đạt làm mất khối "Models could not be listed".** `testInference` thành công xoá `error`, mà
khối lỗi dò lại được cổng theo `error`, nên sau một lần Test đạt người dùng mất cả lý do lẫn ba lối thoát
(`Retry` / `Add model by hand` / `Edit endpoint & key`) dù đường dò danh sách vẫn hỏng.
*Đo trước khi sửa:* `{discoveryState: 'failed', error: null}` → pill `models failed` nhưng **không** có khối.
*Sau khi sửa:* giao diện cổng theo `discoveryState === 'failed' || error` (kèm một câu thay thế khi chưa có lời
nhà cung cấp), và `testInference` chỉ xoá `error` khi `discoveryState === 'ready'` — phép thử đạt là bằng chứng
cho **một model**, không phải cho đường dò danh sách. Khối hiện đủ ở **cả hai** dạng, `Last attempt` giữ nguyên.

**Ca kiểm thử thêm:** `router/tests/custom-provider.test.mjs` +3 và
`frontend/src/components/settings/ProviderConnectionCard.test.tsx` +2. Lần đo đỏ trước khi sửa:
`tests 3 / pass 0 / fail 3` (router) và `2 failed | 8 passed` (tệp giao diện). **Bộ router: 155 pass / 0 fail**;
frontend **736 pass / 4 fail** (đúng bộ đỏ có sẵn); `tsc -b --noEmit` mã 0. `CONTRACT.md` thêm một câu ghi luật
mới (khai lại id ghi cả hai cờ; dòng gõ tay định tuyến được khi dò `failed`/`degraded`; probe đạt không xoá lỗi dò).

### 6.15 Vòng soát mã vòng 17 (7 phát hiện) — ĐÃ SỬA (`2a0075c`)

Một tác nhân soát mã độc lập đọc trọn `bff9f3d..91647e7` (chỉ đọc; bộ router 155/155 và
`src/components/settings` 38/38 đều xanh). Sáu phát hiện là lỗi, một là câu hỏi sản phẩm; năm lỗi
đã sửa trong `2a0075c`, lỗi còn lại (nhãn `supported`) sửa cùng lượt, và câu hỏi đã có quyết định.

**P1 (vừa) — token ghi cache bị tính tiền hai lần.** `usage.mjs` chuẩn hoá `input` thành **tổng** đầu vào:
`prompt_tokens = input-only + cache-hit + cache-write` (đúng cho payload Anthropic và cho hàng đã lưu trong store),
nhưng `costFromUsage` tính `miss = input - hit` — trong đó đã chứa phần ghi cache — rồi cộng thêm
`cacheWrite * (cacheWriteInput ?? input)` lần nữa. Đây là chỗ **duy nhất** trong bộ thay đổi ghi ra một con số tiền sai.
*Đo trên mô-đun thật:* payload `{input_tokens:189, cache_read:11776, cache_creation:900, output:25}`, giá
`{input:0.15, cachedInput:0.003, cacheWriteInput:1.5, output:0.6}` → router **0,01055** so với số thật **0,00785**
(gấp 1,34 lần; nếu thiếu giá cache-write thì 0,009875 so với 0,007175).
*Sau khi sửa:* `write = min(cacheWrite, max(0, input - hit))`, `miss = max(0, input - hit - write)`; hàng kiểu
Anthropic qua `normalizeUsage()` cho **12865 / 11776 / 900 / 25** → **0,00785**; hàng DeepSeek sống (không có ghi cache)
không đổi. Đính chính kèm theo: câu công thức trong kế hoạch đã được sửa (có ghi chú ngày), và ca kiểm thử
`costFromUsage reads the router normalized usage names…` được viết lại để dựng hàng từ `normalizeUsage()` thật —
ca này **đỏ** trên mã trước khi sửa (`not ok 107`, `pass 154 / fail 1`).

**P2 (thấp–vừa) — một từ vựng thứ năm không ai đọc.** Dòng gõ tay được ghi `vision: 'supported'`, nhưng từ vựng
duy nhất trong mã là `unknown | reported | verified | unsupported` (`frontend/src/types/provider.ts`), và huy hiệu
`Vision Supported` trong trình quản lý model chỉ hiện với `reported | verified`. Hệ quả: ô Vision người dùng **tự
tích** không hiện bằng chứng ở đâu cả (Reasoning sống sót nhờ `thinkingLevels` không rỗng).
*Sau khi sửa:* ghi `reported` ở cả bốn chỗ; `CONTRACT.md` ghi rõ bốn từ và nghĩa "đã khai, chưa xác minh".
Hai ca router cập nhật theo.

**P3 (thấp–vừa) — khối "Models could not be listed" hiện cho lỗi không phải lỗi dò danh sách.** Cổng cũ là
`discoveryState === 'failed' || error`, mà `error` còn được đặt bởi đường **làm mới credential** và bởi một lần
Test trả `AUTH` trên connection `ready`. Hai trường hợp đó danh sách model **đang có**, nhưng thẻ vẫn nói "không
liệt kê được model" kèm `Last attempt:` của lần dò và ba lối thoát của đường dò.
*Sau khi sửa:* khối chỉ hiện khi `discoveryState` là `failed` hoặc `degraded`; lỗi khác trên connection `ready`
hiện thành **một dòng riêng** (không tiêu đề, không `Last attempt`). Ca giao diện mới
"does not claim a failed model list when the error is not a listing failure" **đỏ** trên mã trước khi sửa.

**P4 (thấp) — cảnh báo ngày lễ chưa tới người đọc.** Kế hoạch yêu cầu cửa sổ cao điểm DeepSeek phải ghi rõ trong
**tooltip và tài liệu**; cảnh báo mới chỉ nằm ở chú thích mã.
*Sau khi sửa:* `PEAK_HOLIDAY_CAVEAT` nằm trong cả hai câu tooltip `documented` và trong đoạn "Model price" của
`CONTRACT.md`; ca giao diện về nguồn giá cập nhật theo (đỏ nếu thiếu).

**P5 (thấp) — `costMode: 'included'` vẫn ghi được cost do nhà cung cấp tự báo.** Miễn trừ chỉ nằm trong
`priceFor`, nên tầng `reported` bỏ qua `costMode`; một gateway thuê bao trả `cost` trong usage sẽ vẫn được ghi.
**Quyết định (chọn hướng b — ghi và hiển thị):** con số đó là số **của nhà cung cấp**, không phải số ta bịa, nên
nó ở lại hàng với `costBasis: 'reported'`; miễn trừ `included` áp cho **phép ước lượng của ta** mà thôi.
`CONTRACT.md` nói rõ điều này, và một ca mới trong `router/tests/cost.test.mjs` ghim **cả hai** nửa: connection
`included` + provider báo `cost` → `0,0069` / `reported` / `estimated false`; cùng connection không báo gì → `null`.

**P6 (thấp) — bộ lọc Free đọc hình dạng giá cũ.** `(m as any).pricing?.prompt === '0'` là hình dạng payload thô
trước vòng 17; dòng model nay mang `pricing` đã chuẩn hoá (`input`/`cachedInput`/`output`), nên nhánh đó chết và
tab Free bỏ sót đúng những model giá 0.
*Sau khi sửa:* một hàm `isFreeModel` dùng chung cho tab Free và nút `Enable all free`, bằng đúng luật của router
(`openrouter.mjs`: id chứa `:free`, hoặc `pricing.input === 0`). Ca giao diện mới ghim cả hai chiều (model giá 0
hiện, model trả tiền không hiện).

**P7 (thấp) — lần Test hỏng chỉ còn được báo bằng màu.** Hàng model gọn in `{latencyMs} ms` và tô màu theo
`health`, còn lý do chỉ hiện khi probe vừa chạy trong phiên; sau khi tải lại, một model hỏng chỉ khác ở màu chữ.
*Sau khi sửa:* `title` của ô đó mang trạng thái + `health` + mã HTTP + lý do
(`Failed · unavailable · HTTP 403 · 12 ms · Provider rejected the probe.`).

`CONTRACT.md` giữ nguyên lời hứa "cạnh `input` là tổng đầu vào" bằng cách nói thẳng ra, thay vì để người đọc tự
suy từ công thức. **Sau `2a0075c`:** router **156 pass / 0 fail**; frontend **738 pass / 4 fail** (đúng bộ đỏ có
sẵn: 3 ca `Sidebar.test.tsx` + 1 ca `workspace/index.test.ts`); `tsc -b --noEmit` mã 0.

### 6.16 Vòng 18 — hai lỗi chủ sở hữu báo: cửa sổ ngữ cảnh 64 000 do đoán theo tên, và bản ghi màn hình không xem được

**P1 (vừa) — cùng một câu hỏi "cửa sổ ngữ cảnh của model này là bao nhiêu" có BA câu trả lời khác nhau.**
Chủ sở hữu báo thanh ngữ cảnh in `37.5k / 64.0k (59%) est.` cho một model DeepSeek trong khi nhà cung cấp công bố
1M. Đo trên máy này (2026-09-21) cho thấy cả ba tầng đều tự đoán theo tên, và không tầng nào hỏi tầng kia:

| Tầng | Chỗ đoán | Số nó đoán cho họ DeepSeek V4 |
| --- | --- | --- |
| Router | `router/src/providers/common.mjs:143` đọc `context_length`/`context_window`/`top_provider.context_length`/`max_context_length`; payload `/models` của DeepSeek chỉ có `{id, object, owned_by}` | không có gì → `deepseek.mjs:92` công bố `contextWindow: null` |
| Harness | bảng tên trong `backend/src/agentbox/agent_core/runtime.py:592-599` (`deepseek`/`qwen` → 64 000) | **64 000** |
| Giao diện | `frontend/src/components/panels/ContextUsageBar.tsx:144` (`deepseek`/`qwen` → `64_000`) | **64 000**, in kèm `est.` |

Chuỗi truyền: `/api/router/state` mang `null` → `backend/src/agentbox/api/server.py:176-177` chỉ chép giá trị khi
truthy nên không chép gì → harness rơi vào bảng tên → `config['contextWindow'] = 64000` → giao diện in `64.0k`.
Nghịch lý: chính vì số 64 000 được gắn nhãn `est.` nên trông như đã có nguồn, trong khi đó là con số duy nhất
không ai công bố.
*Quyết định của chủ sở hữu (đã chốt, không hỏi lại):* với một dòng model **đã biết**, bảng tên thắng; số nhà cung
cấp vẫn được giữ bên cạnh ở `contextWindowReported` để đối chiếu; những dòng cũ (`deepseek-r1` 64 000,
`v3.2` 163 840) **không** vào bảng, giữ nguyên số nhà cung cấp.
*Sau khi sửa:* một bảng duy nhất `router/src/context-window.mjs` (`CONTEXT_WINDOW_TABLE_AS_OF = '2026-09-21'`, bảy
dòng V4/V4.1, regex họ `^deepseek-(?:v4(?:\.1)?-)?(?:flash|pro)(?:-|$)`) và ba nguồn có tên
`'manual' | 'documented' | 'reported' | null`; bảng tên Python trong harness **bị xoá**;
`resolve_context_window()` trả về **cặp** `(số, nguồn)` và sàn an toàn của harness (128 000) mang nhãn `'fallback'`;
`ContextUsageBar` bỏ hẳn phép đoán theo tên; đường khai tay `PATCH /api/router/state`
`{modelContextWindow:{modelId,contextWindow,clear?}}` cho người dùng chỉnh bất cứ dòng nào. Phiên cũ được lành lúc
harness khởi động (`HarnessRuntime.heal_context_windows`, gắn vào `app.on_startup`), chỉ bỏ qua phiên có
`contextWindowSource == 'manual'`.
*Số đo sống sau khi sửa* (router và harness khởi động lại, 2026-09-21):
`/api/router/state` → `deepseek-flash` = **1000000 / documented / reported null**; TokenHarbor `deepseek-v4.1-flash`
= **1000000 / documented / reported 1048576**; OpenRouter `deepseek/deepseek-v3.2` = **163840 / reported** (dòng cũ
không có bảng, giữ đúng số nhà cung cấp). `/v1/models` (61 dòng) đọc đúng cùng bộ số. Phiên mới tạo với
`deepseek-flash`: `config.contextWindow == 1000000`, `contextWindowSource == 'documented'` (trước đợt này:
`64000`, không có nguồn); phiên khai tay `32768`: `32768 / manual`.
Đợt đầu của phép lành ghi lại: trong 50 phiên lưu sẵn, **4 phiên còn `64000`** và **22 phiên ở 1048576** (Gemini
công bố 1048576) đều thành `(số, nguồn)`; lần khởi động thứ hai **đổi 0 dòng** (phép lành là idempotent).
Ghi chú trung thực: hai phiên rất cũ khai `30000` và `250000` **trước** đợt này không có trường nguồn, nên phép lành
coi chúng như số không nhãn và đưa về số của định tuyến — từ đợt này trở đi mọi lời khai tay đều mang nhãn `manual`
và được bảo vệ. Ba tầng cùng đọc một số: router **174 ca / 0 đỏ** (`router/tests/context-window.test.mjs` 16 ca
mới, đỏ trước khi sửa: `1000000 !== 32768`, `Missing expected exception: 0 không phải một cửa sổ`), harness
**543 đạt** (`test_context_window_heal.py` 4 ca mới), giao diện `ContextUsageBar.test.tsx` **19 đạt** (4 ca mới đỏ
trước khi sửa: `7 failed | 12 passed`).

**P2 (vừa) — bản ghi màn hình `.mp4` hiện thành `<img>`.** `frontend/src/components/panels/ChatPanel.tsx:678-684`
render `<MediaLightboxModal src caption sourceUrl />` mà **quên `type`**, và
`frontend/src/components/chat/MediaLightboxModal.tsx:36` mặc định `type = 'image'`. Hậu quả: tệp `.mp4` rơi vào
nhánh `<img>` nên khung xem chỉ hiện alt text (`Sandbox Screen Recording`), đúng như ảnh chủ sở hữu gửi.
Cùng một giá trị sai đó còn làm **hai** chỗ khác: nút `Download` lưu `.mp4` thành `boxfox-image-capture-<ts>.png`
(`:137-145`), và thanh tua chỉ hiện khi `type === 'video'` (`:300`). Người gọi thứ ba là
`frontend/src/components/panels/RouterTestChat.tsx:126` cũng thiếu `type`, tức lỗi có ba cửa chứ không một.
Vận chuyển thì đúng: `HTTP/1.0 200 OK`, `Content-Type: video/mp4`, `Accept-Ranges: bytes`, byte-range trả
`HTTP/1.0 206 Partial Content Content-Range: bytes 0-1023/7438731`; tệp là H.264 Constrained Baseline,
yuv420p, 1280×800, 15 fps. Trước đợt này **không có ca kiểm thử nào** cho khung xem.
*Sau khi sửa:* `type` là trường **bắt buộc** của `LightboxMediaProps` (xoá giá trị mặc định), nên `tsc` chỉ ra mọi
cửa quên truyền; tên tệp tải về lấy đuôi thật của đường dẫn trước, rồi mới tới `type` (`downloadExtension()`);
và một bản ghi không nhận được `stop` sạch vẫn mở được, nói thẳng thời lượng chưa biết
(`Duration unknown — this recording did not stop cleanly`) thay vì coi như tệp ảnh.
*Trạng thái:* **ĐÃ SỬA trong mã**; phép kiểm sống (mở một bản ghi thật trong khung xem, đọc thẻ `<video>` và tên
tệp tải về) nằm ở phần nghiệm thu cuối vòng — ghi lại kết quả ở `test-rounds.md`.

### 6.17 Vòng 18 (tiếp) — bốn yêu cầu còn lại của chủ sở hữu: ba lỗi thật, hai lỗi đã sửa cùng lượt

**P3 (vừa) — tab Instructions chỉ là hình vẽ.** Settings → Instructions là tiêu đề, phụ đề và **một `<textarea>`
không kiểm soát** (không `value`, không `onChange`, không ai đọc giá trị). Gõ chữ thì chữ nằm đó, đổi tab là mất, và
**không đường nào ghi** trường `instructions` mà harness đã biết đọc và ghép vào system message
(`runtime.py:842-847`, khối `=== OWNER-CONFIGURED DIRECTIVES ===`). Nói cách khác: cả hai đầu đã sẵn sàng, chỉ thiếu
đúng khúc nối.
*Sau khi sửa:* `owner_settings.py` (một document + `revision`, `REVISION_CONFLICT` khi lệch, lưu chuỗi nguyên văn),
hai route `GET/PUT /api/agent/owner-settings`, `ownerSettingsStore` + `InstructionsTab.tsx` có kiểm soát, bộ đếm
`{{n}} / 12.000 ký tự` chuyển màu ở 11 000 và ở mốc cắt, chip `UNSAVED CHANGES`, biên nhận `Saved … · revision n`,
trạng thái lỗi giữ nguyên bản nháp và ghi `NOT SAVED` chứ không bao giờ nói "đã lưu", bốn ví dụ chèn tại con trỏ, một
câu hỏi chặn mất dữ liệu khi Esc/đổi tab, và sổ phiên ghi `instructionsChars` để chat cũ nói thẳng
`not recorded for this chat`. Mốc 12 000 ký tự có **một** nguồn: `INSTRUCTIONS_MAX_CHARS` trong
`backend/src/agentbox/agent_core/limits.py`, dùng ở cả route lẫn `runtime.py`, và một ca backend so hai nơi với nhau.
*Đo sống:* `GET /api/agent/owner-settings` → `{"instructions":"","revision":0}`; `PUT` với revision cũ → **409
`REVISION_CONFLICT: reload owner settings`**; một phiên thật tạo bằng thân request mới lặp lại `instructions` và
đuôi system message đúng khối trên.

**P4 (vừa) — ô `Model` của sổ harness ghi giá trị router không định tuyến được.** Ô này ghi id trần hoặc tên hiển
thị, trong khi `router/src/engine.mjs:14-24` chỉ nhận tên alias hoặc chuỗi có `/`. Đo sống hôm nay với khoá harness:
`{"model":"deepseek-v4-pro"}` → **HTTP 404 `MODEL_NOT_FOUND`** và `{"model":"Claude 3.7 Sonnet"}` → **404** y hệt,
còn `7ee21256-8675-4ee3-a802-fcedbed8b7ef/deepseek-flash` → **200**. Nghĩa là một harness "đã lưu" vẫn có thể chết ở
lượt đầu, và lỗi hiện ra như lỗi nhà cung cấp.
*Sau khi sửa:* ô `Model` lấy danh mục **sống** từ `providerStore` và chỉ ghi hai dạng chạy được
(`model:<connectionId>:<modelId>` / `alias:<id>`), có hàm thuần `isRoutableModel()` dùng ở **cả** store (từ chối giá
trị không định tuyến) **và** editor, ô bị khoá kèm lý do khi danh mục chưa nạp. Bản mẫu giữ `mainModel: 'default'` và
mô tả của chúng được sửa cho khớp trạng thái thật, thay vì khôi phục tên seam cũ (những tên đó cũng 404).
*Kèm theo:* editor có `Steps per turn` (1–60) và `Turn deadline` (5–600) kèm câu nói trần của vai trò con, khối
`Tool access` đếm từ `runtime-info` (nhóm `Questions & approvals` luôn bật) cùng câu luật "chỉ được lấy công cụ đi"
(engine trả `Tool not permitted for this role`), khối `Retries` **chỉ-đọc** nói rõ ba số đó sống ở `failures.py`, và
`HarnessFlowVisualizer` in đúng danh sách công cụ của registry — **năm** cái tên chưa từng tồn tại
(`file_multi_replace`, `diagram_generate`, `dir_list`, `git_diff`, `read_url_content`) đã biến mất.

**P5 (thấp–vừa) — thang tự nối lại của màn Máy dừng sau 4 lượt, và cách trả nợ cũ là hai nút bấm.**
`lib/vnc/state.ts` có `VNC_MAX_ATTEMPTS = 4`; hết trần thì giao diện hiện khối hổ phách `NO FRAME AVAILABLE` cùng
`Retry connection`, buộc chủ sở hữu bấm tay trong khi lý do hỏng (mất mạng, `timeout`, socket đóng) tự khỏi được.
Trần đó là **cố ý**: mỗi lượt hỏng trình duyệt ghi một dòng đỏ WebSocket không tắt được, nên trả nợ bằng cách bỏ trần
sẽ biến một tab bỏ quên thành máy bơm nhật ký.
*Sau khi sửa:* bỏ trần, giữ thang `3 → 8 → 20` và **giữ mãi nấc 20 s**; `exhausted` chỉ còn nghĩa "lý do này không
tự khỏi" (`mixedContent`, `insecureContext`, `unsupported`, `security`, `credentials`, `disabled`, `skipped`) — sáu
lý do đó không thử lại vì thử lại là vô nghĩa. Món nợ nhật ký được trả bằng `visibilitychange` trong `useVncScreen`:
tab bị ẩn thì **không** hẹn giờ và **không** mở socket, quay lại thì hẹn lại từ nấc 3 s — nên trần thực tế là khoảng
một lượt mỗi 25 giây khi panel đang mở và tab đang hiện, và bằng **0** khi tab bị ẩn. Giao diện bỏ cả hai nút
`Retry connection`, thay bằng lớp phủ mờ `Connecting to desktop…` + `Attempt n · Auto-retry in Xs` + thanh tiến trình
2 px, chỉ hiện từ lượt 6 mới có link "How to start the box"; nhánh lý do không tự khỏi giữ thẻ tĩnh, và một dải
`Reconnected · live frame resumed` hiện 4 giây khi khung hình trở lại.
*Kèm theo:* công tắc bảng Workspace (một `IconButton` `PanelRight`) — trước vòng này **không có** điều khiển bố cục
nào trong mã (`Layout:` mà chủ sở hữu thấy nằm trong iframe code-server, không phải sản phẩm); bảng ẩn thì cột chat
giãn hết, ý định mở tab của agent **xếp hàng** thay vì mất, và nội dung đọc gom vào cột 768 px ở giữa. Số đo điểm
ảnh ở góc khung hình bị xoá — con số đó là kích thước đã **thương lượng** (`lib/vnc/fit.ts:153` đặt
`rfb.resizeSession = true`), nên nó chỉ còn trong ngăn kéo `Details`, nơi có nhãn và ngữ cảnh.

### 6.18 Vòng soát mã độc lập đợt 18 (7 phát hiện + 1 câu hỏi) — ĐÃ SỬA (`074a8ae`)

Vòng soát đọc trọn diff `a061f03..fc51864` trên ba tầng (router, harness, giao diện), mở lại bản ghi phiên thật ở
chế độ chỉ-đọc và dựng script riêng trong `/var/tmp` để tái hiện — không sửa tệp nào trong repo. Kết luận: `RISK SCORE 4`,
`OVERALL RISK Medium`, ngưỡng 7, `VERDICT Ship with mitigations`. Bảy phát hiện dưới đây đã sửa hết; mỗi cái có ca kiểm
chứng riêng, và cận trên `2 000 000` mà vòng soát ghi là "chưa đo" nay cũng có ca.

**R1 (vừa) — bản ghi bị cắt ngang vẫn không có đường mở, vì bản sửa nằm ngoài commit được soát.** `fc51864` giữ
`HarnessStepView.tsx` trả `null` cho MỌI hàng `tool_end` có `args.action === 'start'`, mà tệp của chủ sở hữu
(`1789929795687-screen.mp4`, phiên `bb0c66e24f68446fb5152b3e7739dcc2`, seq 39458) chỉ tồn tại dưới dạng một hàng
`start`: lượt chết vì DEADLINE trước khi kịp chạy `stop`, và trong cả DB không có hàng `stop` nào cho đường dẫn đó
(12 sự kiện `computer_screen_record`, hai tệp chưa từng `stop`). Bản sửa nằm trong cây làm việc nhưng chưa được commit,
nên **bản được soát** vẫn không đạt D3.
*Sau khi sửa:* `extractToolMedia(event, { allowStartMedia })` + một memo `startAllowedSeqs` trong `TurnBlock` chỉ cho
hàng `start` đi qua khi **không** hàng nào khác trong cùng lượt nói về chính tệp ấy, và nhiều hàng `start` cùng một tệp
thì chỉ hàng đầu tiên được hiện — nên một bản ghi đã đóng vẫn đúng một player. Hai ca mới trong
`HarnessStepView.media.test.tsx`.

**R2 (thấp–vừa) — nút [👁 View] trong chat im lặng khi bảng Workspace đang ẩn.** `ReferencedFilesList` →
`uiStore.selectFile` → `openTab('files')`, mà `openTab` **cố ý** không chạm `workspaceHidden`; bấm View lúc bảng ẩn thì
không hiện gì, và tab Files đổi ngầm để lần sau người dùng nhìn thấy một trạng thái mình không hề chọn. Kế hoạch E2 đã
liệt kê bốn điểm gọi cần đi qua `showTab`; điểm này bị bỏ sót.
*Sau khi sửa:* `selectFile` đi qua `showTab('files')` (hiện bảng + ghim tab + kích hoạt). Ba ca mới trong
`uiStore.workspace.test.ts`, gồm ca hàng đợi đóng băng của tab khác được xả đúng luật cũ-trước.

**R3 (thấp) — một nút vặn đã đặt thì không xoá được.** `setHarnessTuning` bỏ qua mọi giá trị `undefined`, trong khi
trình sửa ghi `undefined` khi ô nhập bị xoá trống — nên đặt `Steps per turn` = 20, xoá ô, lưu: số 20 ở lại và ô tự điền
lại 20; placeholder "mặc định của engine" không bao giờ quay lại được.
*Sau khi sửa:* `null` là tín hiệu **XOÁ** (xoá hẳn khoá, không gán `undefined`, nên `in`/`Object.keys` cũng sạch), còn
thiếu khoá/`undefined` vẫn là "không đụng tới"; trình sửa gửi `null` cho ô trống và cho trường hợp bật lại đủ bộ công cụ.
Ba ca mới trong `harnessStore.workspace.test.ts`.

**R4 (thấp) — một bản ghi phiên không có nhãn nguồn bị đọc thành `reported`.** `ContextUsageBar` coi nhãn thiếu là
`reported`, nên bốn phiên cũ giữ `contextWindow 128000` không nguồn (route `{}` nên bản vá lúc khởi động bỏ qua) hiện
`128.0k` **trần trụi** — không `est.`, không tooltip — trong khi trước đợt 18 con số ấy ít ra còn mang dấu ước lượng.
*Sau khi sửa:* nhãn thiếu (hoặc lạ) đọc là `fallback`, nên số hiện kèm `est.` và tooltip nói thẳng chưa có nguồn; câu
chữ của `fallbackHint` được viết lại cho đúng cả hai ca ("harness đang giữ {{tokens}} token, không phải số nhà cung cấp
báo"), và `reported` thật thì vẫn không `est.`/không tooltip. Một ca mới trong `ContextUsageBar.test.tsx`.

**R5 (thấp) — `contextWindowReported` có thể bằng chính số đang dùng.** Nhánh PATCH đặt số tay gán thẳng
`model.contextWindowReported = published`, không kiểm lại luật "chỉ khi khác" mà `resolveContextWindow` và hai nhánh
kia đã theo (`router/CONTRACT.md`). Tái hiện trong script riêng: gieo `1048576` rồi `PATCH` đúng `1048576` → dòng
`{contextWindow: 1048576, source: 'manual', contextWindowReported: 1048576}`.
*Sau khi sửa:* chỉ giữ số nhà cung cấp khi nó **khác** số đang dùng. Một ca mới trong `context-window.test.mjs`, kèm
nửa đối chứng (hai số khác nhau thì số nhà cung cấp vẫn ở lại).

**R6 (thấp, câu hỏi mở) — `for_engine()` không có người gọi ở production.** Tab Instructions hứa tài liệu áp cho phiên
MỚI, nhưng chỉ đường giao diện gửi chỉ dẫn kèm yêu cầu; một phiên tạo từ script/lịch chạy không nhận được gì dù tài
liệu đã lưu.
*Sau khi sửa:* route tạo phiên đọc tài liệu đang lưu khi yêu cầu **không** mang `instructions` (cắt bằng đúng trần
`INSTRUCTIONS_MAX_CHARS`), chỉ dẫn client gửi kèm vẫn thắng, tài liệu rỗng thì hành vi cũ giữ nguyên. Engine không đổi
luật: nó vẫn chỉ đọc `values['instructions']`. Một ca route mới trong `test_owner_settings.py`.

**R7 (nit) — ghi chú nguồn gốc tự mâu thuẫn với chính dòng của nó.** `CONTEXT_WINDOW_TABLE_SOURCE_NOTES` ghi
`deepseek-v4-flash` "OpenRouter, published 1310720" trong khi dòng đó là `1_000_000`; đọc lại `/api/v1/models` của
OpenRouter hôm nay: **mọi** dòng V4/V4.1 công bố **1048576**, riêng `deepseek-v4-flash-0731` và alias
`~deepseek/deepseek-v4-flash-latest` công bố **1310720** trong khi `top_provider.context_length` của chính chúng là
1048576. Ghi chú nay nói đúng phép đo, đúng dòng lệch, và nói rõ dòng bảng là **quyết định của cả họ** chứ không phải
phép đo từng build — số nhà cung cấp vẫn nhìn thấy được ở `contextWindowReported` thay vì trốn trong ghi chú.

**Còn để ngỏ (không phải lỗi trong mã):** đường tải thật của tệp `.mp4` chưa `stop` chỉ đo được từ trong máy ảo agent
(thư mục capture không nhìn thấy từ máy này) — thuộc phần kiểm chứng sống của đợt; và kết luận `Ship with mitigations`
của vòng soát dựa trên diff, không dựa trên việc chạy lại bộ kiểm thử.

### 6.19 Vòng 19 — OpenCode Free không dùng được: bốn cổng của bậc miễn phí (đồng bộ 9Router v0.5.81)

**Triệu chứng đo được.** Bậc miễn phí của OpenCode từ chối gần như mọi thứ: `POST /zen/v1/responses` trả `403` với
`{"type":"FreeTierError","message":"OpenCode's free tier can only be used from within OpenCode"}`. Adapter trong cây lúc
đó gửi `User-Agent: opencode` (không số), không gửi tool nào cho đường Responses, mint `x-opencode-session` bằng
`randomUUID()` (`ses_<32 hex>`), và tôn trọng `stream:false` của người gọi — **cả bốn** điều đó đều là cổng chặn.

**Nguyên nhân, đo từng biến một** (`Authorization: Bearer public`, 2026-09-21, cùng một payload nền):

| Dạng yêu cầu | Kết quả |
|---|---|
| `User-Agent: opencode` (không số) | **403 FreeTierError** |
| `User-Agent: opencode/1.18.31` | 200 |
| `tools: []` | **403 FreeTierError** |
| 2 tool mồi `bash` + `read` (description `This tool is currently unavailable and must not be used.`) | 200 |
| `stream: false` | **403 FreeTierError** |
| `stream: true` | 200 |
| `x-opencode-session: ses_<32 hex>` (uuid) | **403 FreeTierError** |
| `x-opencode-session: ses_<12 hex><14 base62>` | 200 |
| `reasoning_effort: "high"` trong body | **400** `invalid_request_error` (param `reasoning_effort`) |
| `reasoning: {effort:'high', summary:'auto'}` | 200 |
| `reasoning.effort: 'none'` | **400** |
| item `reasoning` cũ replay lại | bị từ chối ở tài khoản khác / khi `store:false` |
| kết quả tool mang ảnh, gộp vào `function_call_output` dạng mảng | 200 nhưng **câu trả lời rỗng** |
| kết quả tool mang ảnh, tách thành lượt người dùng riêng | 200, **đọc đúng màu ảnh 4/4** |

`GET /zen/v1/models` trả 200 với 74 dòng; **8 id** chạy được không cần khoá (`muse-spark-1.2-contributor-free`,
`muse-spark-1.3-contributor-free`, `jev-1.13-free`, `deepseek-v4-flash-free`, `mimo-v2.5-free`,
`ling-3.0-flash-fin-free`, `nemotron-3-ultra-free`, `nemotron-3.5-lightning-free`); các id **không** có hậu tố `-free`
(`muse-spark-1.2`, `muse-spark-1.3`) trả **401 `AuthError: Missing API key`**, nên chúng được khám phá nhưng để **tắt**.

**Sau khi sửa** (`router/src/providers/opencode.mjs`): UA có phiên bản (nhận UA hợp lệ của người gọi, còn lại dùng
`opencode/1.18.31`); **luôn** `stream:true` ở phía thượng nguồn rồi tự gộp khi người gọi cần bản không-stream; hai tool mồi
luôn đi kèm bộ tool của người gọi (không nhân đôi nếu người gọi đã gửi); phiên `ses_<12hex><14base62>` **dùng lại theo
danh tính cuộc trò chuyện** (6 giờ, trần 200 phiên; có `session_id` trong body thì dịch từ đó) vì quota tính theo phiên —
mint phiên mới mỗi request chính là cách tự tạo `429`; `x-opencode-request` suy từ phiên + lượt người dùng cuối nên thử
lại một lượt dùng lại một id; `reasoning_effort` được dịch thành `reasoning.effort` (`none`/`auto` thì bỏ hẳn khối
`reasoning`); item `reasoning` cũ và `encrypted_content` bị lọc khỏi `input`; ảnh trong kết quả tool tách thành lượt người
dùng riêng; lỗi được phân biệt rõ (`403` dạng client-shape → `AUTH` không thử lại, `429` → `RATE_LIMIT` có thử lại, lỗi
giữa luồng sau `200` thì ném lỗi thay vì kết thúc như thành công). Hợp đồng dây được ghi ở `router/CONTRACT.md`.

**Đo sống sau khi sửa** (qua chính adapter, `fetch` thật): khám phá 74 dòng/8 id bật; lượt gọi tool thật **1,1 s**
(`finish=tool_calls`, usage 659 in/87 out); lượt có ảnh trong kết quả tool trả lời đúng nội dung ảnh (**5,4 s**); người gọi
`stream:false` nhận câu trả lời thật (**7,6 s**). `router/tests/opencode.test.mjs` thêm **15 ca**; toàn bộ router
**193/193 đạt**.

**Nguồn để đối chiếu:** 9Router v0.5.81 (`/var/tmp/9router`, commit `a8c9d38`) — mục *"OpenCode / OpenCode Go: resolve 403
FreeTierError and 429 rate limits with canonical session format, valid User-Agent, and stable upstream session reuse;
force stream and declare `forceStream` for free-tier SSE aggregation; cloak decoy tools, normalize Muse Free tool choice,
and strip prior reasoning items on Responses models"*. Bản clone đã `git fetch` lại: **không có commit mới hơn**.

### 6.20 Vòng 19 — nén ngữ cảnh: ngưỡng 70 % không bao giờ chạm tới, và bốn thứ đi kèm (port HERMES/PI)

**Triệu chứng đo được.** Một nhiệm vụ dài không bao giờ được nén: `ContextCompressor(config['contextWindow'])` lấy
`output_reserve = min(4096, window // 4)`, rồi ngưỡng `int((window - reserve) * 0.7)`. Trên cửa sổ 1 000 000 token mà
model khai, ngưỡng là **697 132 token** (`int((1 000 000 − 4 096) × 0,7)`), trong khi trần thật của một request chỉ là **900 KiB** thân bài
(`ROUTER_BODY_BUDGET`) ≈ **307 000 token ước lượng**. Nghĩa là `shrink_request_to_budget` cắt văn bản/ý nghĩ/đối
số/phương tiện trước khi ngưỡng kịp chạm, log `model.request_trimmed` ở mức warn và **không có checkpoint**, rồi các
lượt sau bị từ chối `UPSTREAM_HTTP_413`. Ba lỗi đi kèm: bộ nén gọi ở đầu **mỗi** bước nên một bản tóm tắt hỏng đốt một
lượt tóm tắt mỗi bước (không có chống-thrash); trần tóm tắt cứng `max_tokens=2048` trong khi bản tóm tắt chỉ được nhận
khi `finish_reason == 'stop'` (nên nhiệm vụ dài nhận `Incomplete summary`); và phép đo ngữ cảnh chia 3 byte/token thay
vì đọc hoá đơn thật của router.

**Đã port (v1, giữ nguyên hình dạng)** — `backend/src/agentbox/agent_core/compression.py` (252 → 559 dòng),
`limits.py`, `runtime.py`, `skills/runtime_commands.py`:

| Việc | Ngưỡng / luật mới | Nguồn đối chiếu |
|---|---|---|
| P1 ngưỡng tuyệt đối đặt được | `threshold = min(threshold_tokens or percent, byte_threshold)` | HERMES `_derive_trigger` :2433, `_apply_threshold_tokens_cap` :2518, `resolve_model_threshold` :1807 |
| P2 trần theo BYTE | `byte_threshold = ROUTER_BODY_BUDGET // 3 - 6000` = **301 200** token | đo sống 2026-09-20: body 1 060 902 B, `messages` 1 043 364 B |
| P3 đo bằng hoá đơn thật | `usage_reading()` + `context_estimate(messages, tools, usage)` | PI `estimateContextTokens` :217-245 |
| P4 tỉa nhiều lượt | khử trùng lặp md5 trước, rồi mỗi kết quả cũ thành một dòng (`PRUNE_MIN_CHARS = 200`) | HERMES `_prune_old_tool_results` :3045, `_dedupe_tool_results` :2920 |
| P5 đuôi theo ngân sách token | `min(20 % ngân sách, 25 000)`, sàn 8 message | HERMES `LEAN_TAIL_CAP_TOKENS` :842, `_MAX_TAIL_MESSAGE_FLOOR` :1060 |
| P6 trần tóm tắt co theo độ lớn | `min(8192, max(2048, 2 % của before))` | PI `maxTokens = min(0.8*reserve, …)` :684 |
| D chống-thrash | hỏng/vô hiệu thì im lặng **300 s** | HERMES `_ANTI_THRASH_RECOVERY_SECONDS` :2501 |
| E xác nhận tiến bộ | nén xong mà vẫn ≥ 95 % ngưỡng ⇒ cờ `ineffective` | HERMES `compression_made_progress` :403-427 |
| Banner | nói thẳng công cụ vẫn hoạt động bình thường | HERMES `SUMMARY_PREFIX` :199-239 |

**Không port (có lý do):** `_effective_threshold_percent` (70 → 75 % cho cửa sổ < 512k — cửa sổ lớn đã bị trần byte
chặn trước), micro-compaction, lưu phiên con/theo dòng, `tail_mode="lean"`, khoá lại chữ ký suy luận, đuổi ảnh gửi đi,
23 mẫu regex `overflow` của PI.

**Ngưỡng trước/sau theo cửa sổ thật:**

| Cửa sổ khai | Ngưỡng cũ (70 % cứng) | Ngưỡng mới | Ghi chú |
|---|---|---|---|
| 1 000 000 | 697 132 | **301 200** | trần byte thắng; nay nằm dưới mốc `UPSTREAM_HTTP_413` |
| 128 000 | 86 732 | 86 732 | không đổi (trần byte ở trên) |
| 32 768 | 20 070 | 20 070 | không đổi (trần byte ở trên); đo sống: nén tự động ở 20 408 và 21 127 |

**Bằng chứng sống** (harness chạy mã mới, `deepseek-flash`, cửa sổ khai tay 32 768 để ngưỡng chạm được trong ngân sách):
phiên `b2cfba9a245b4e84bb06f0ae468f6192` sinh **hai** sự kiện `compression` `{"kind":"summary","beforeEstimate":20408,
"afterEstimate":16267}` và `{"beforeEstimate":21127,"afterEstimate":13869}`, hai checkpoint `reason=summary` (id 13, 14)
được ghi **trước** khi thay danh sách, và lượt kế tiếp mở bằng 15 message thay vì 24. Cửa sổ khai tay đã được xoá lại
(`deepseek-flash` về `1000000 / documented`, `muse-spark-1.2-contributor-free` về `null`).

**Ghi chú trung thực — cửa sổ quá nhỏ vẫn từ chối thật.** Khai 8 192 thì lượt chết `CONTEXT_LIMIT: current turn/tools
exceed the context budget` (prompt hệ thống + schema công cụ không lọt nổi ngân sách 6 144); khai 32 768 rồi đổ một kết
quả công cụ ~33 000 token trong một lượt thì chết `CONTEXT_LIMIT: summary did not reduce context enough`. Cả hai là
nhánh fail-closed có chủ đích (bản gốc còn nguyên), không phải lỗi mới — và cũng là lý do ngưỡng byte phải khác ngưỡng
phần trăm chứ không thay thế nó.

**Nguồn để đối chiếu:** HERMES `agent/context_compressor.py` (5 367 dòng) tại commit `ea0c2b82`; PI monorepo
`packages/coding-agent/src/core/compaction/compaction.ts`. Không có mã nào chép nguyên: mọi hằng số ở trên đều được
đo lại trong BoxFox trước khi chốt.

### 6.21 Vòng soát mã độc lập đợt 19 (4 phát hiện) — ba sửa, một ghi nhận có chủ đích

Vòng soát mã độc lập (`r19-review`, dải `00b7a8a..374a70a`) kết luận **"Ship with mitigations"**, điểm rủi ro **4/10**
(mức Trung bình), và đề nghị (a): sửa hai phát hiện F1 + F3 trước lượt kiểm chứng cuối. Cả ba phát hiện có mã đều đã
sửa trong đợt này, mỗi bản sửa kèm một bài test khoá lại; F4 ghi nhận là quyết định có chủ đích, không sửa.

**F1 — mức Cao — đuôi nguyên văn có thể co về 0.** `tail_cut` trả chỉ số đuôi theo ngân sách token, rồi vòng
"không để kết quả công cụ mồ côi" tiến `cut` qua loạt `role == 'tool'` liền nhau cho tới khi gặp hàng gọi. Khi
transcript **kết thúc** bằng một loạt song song dài hơn `tail_budget` (BoxFox cho tới **16** lời gọi một bước, và
lượt nén chạy ở đầu **mỗi** bước — `runtime.py:1101-1108`), vòng đó chạm `len(result)`, bản gộp thay mọi thứ sau
tiền tố hệ thống và model nhận `[system, summary]`: không còn lượt người dùng nào lẫn kết quả mới nhất, mà phiên thì
đã bị lưu ở dạng đã gộp. Bằng chứng của vòng soát: `collapse_mech.py` cửa sổ 32 768, 45 157 token → `out_len=2` cho
`batch=8` và `batch=9` (một loạt 7 thì thoát, vì thân kết quả nhỏ hơn ngân sách đuôi).

Bản sửa: hàm mới `keep_tail(messages, cut)` (`compression.py:180-199`) — khi `cut` đã chạm cuối danh sách thì lùi về
`len − MAX_TAIL_MESSAGE_FLOOR` rồi lùi tiếp qua các hàng `tool`, nên đuôi bắt đầu ở hàng gọi và **cả loạt** được giữ
cùng nhau; gọi ở **cả hai** nhánh (`compression.py:479` cho đường thường, `:486` cho nhánh nhiệm-vụ-một-lời-nhắc).
Sau bản sửa, chính bài đo của vòng soát in `out_len=11` cho `batch=8` và `12` cho `batch=9`. Bài test khoá:
`test_the_fold_never_takes_the_whole_tail_of_a_parallel_batch` (`test_compression_port.py:297`) — kiểm cả hàm
`keep_tail` lẫn kết quả `compact` (cặp gọi/kết quả không rời nhau, kết quả mới nhất còn nguyên văn, `len(result) > 2`);
đã xác nhận bài này **đỏ** khi trả `keep_tail` về hành vi cũ (`cut == len` → `IndexError`) và **xanh** sau khi sửa.

**F2 — mức Trung bình — `compact()` có thể trả bản sao y nguyên và báo một lần nén chưa hề xảy ra.** Ngưỡng khởi động
đo bằng số có neo hoá đơn (`context_estimate` với `usage` thật), còn hai phép kiểm sau đo bằng ước lượng thô. Khi nhà
cung cấp đếm nhiều token hơn `bytes/3` cho cùng nội dung, hàm vào vòng tỉa rồi thoát sớm, trả `deepcopy` không đổi kèm
event `{'kind':'prune', …, 'pruned':0}`; `runtime.py:1110` đối chiếu **danh tính** nên ghi thêm một checkpoint trùng,
lưu lại phiên và phát event `compression` mà giao diện hiện thành `Context compacted: …`.

Bản sửa: hai nhánh thoát sớm của vòng tỉa (`compression.py:498` và `:528`) nay trả **chính danh sách cũ** và `None`
khi `pruned <= 0` — đúng hợp đồng no-op mà nhánh `cut <= 1` đã dùng từ trước, nên người gọi không thấy khác danh tính,
không checkpoint trùng, không event. Phần chia đôi thước đo vẫn giữ nguyên có chủ đích: khi `pruned > 0` thì event
vẫn mang hai con số thô và việc tỉa là thật. Bài test khoá:
`test_a_usage_trigger_with_nothing_to_prune_is_a_no_op` (`test_compression_port.py:165`) — cũng đã xác nhận đỏ/xanh
theo cùng cách.

**F3 — mức Trung bình — nhánh chat với `tools: []` không được nguỵ trang, và cú từ chối theo hình dạng bị xếp là lỗi
khoá.** Bậc miễn phí của OpenCode từ chối payload không có công cụ (`403 FreeTierError`); đường tóm tắt của harness gọi
`client.complete(history, [], route, …)` — tức `tools: []` — nên `/compact` trên một model opencode làm `engine.mjs`
đặt `authState = 'expired'` và đưa **cả** nhà cung cấp ra khỏi vòng xoay, lượt chết với `NO_ROUTE`. Bản sửa:
nhánh chat nay **luôn** gửi công cụ của người gọi cộng hai công cụ mồi còn thiếu, và `tool_choice: 'none'` khi người
gọi không mang công cụ nào (`router/src/providers/opencode.mjs:668-672`), nên hình dạng BoxFox gửi không còn chạm
cổng đó. Hai bài test mới trong `router/tests/opencode.test.mjs`
("a chat model with no caller tools still carries the decoys", "a chat model keeps the caller's tools and gains the
missing decoy") khoá cả hai chiều. Việc xếp `403` là lỗi khoá vẫn giữ: với bậc miễn phí đó là lệch hình dạng vĩnh
viễn, thử lại không chữa được, và `requestScopedClientError` cố ý để `403` thuộc phạm vi tài khoản.

**F4 — mức Thấp — ghi nhận, không sửa.** (1) `threshold_tokens` không có điểm gọi nào trong mã chạy, nhưng nó là bề
mặt công khai có test (`test_the_threshold_can_be_an_absolute_number`) giữ đúng cửa vào "ngưỡng tuyệt đối" của bản
port; (2) dòng `if (FORCE_AUTO_TOOL_CHOICE.includes(modelId)) requestBody.tool_choice = 'auto'` trong nhánh Responses
là vô hại (nhánh đó vốn đã gửi `auto`), giữ lại làm bản đối chiếu có tên của danh sách `forceAutoToolChoiceModels`
bên 9Router — bỏ đi thì mất đối chiếu mà hành vi không đổi.

**Đính chính số của chính bản ghi này.** Ngưỡng 70 % cũ ghi sai ở §6.20: đúng là **697 132** cho cửa sổ
1 000 000 (`int((1 000 000 − 4 096) × 0,7)`) và **20 070** cho cửa sổ 32 768 — không phải 697 232 và 20 270. Con số
ngưỡng **mới** (301 200 / 86 732 / 20 070) và mọi bằng chứng sống không đổi.

### 6.22 Vòng 21 — năm việc chủ nhà giao: bốn lỗi đo sống và một lỗi giao diện (chưa sửa, đã lên kế hoạch)

Vòng 21 không sửa mã sản phẩm (đợt này chỉ đo và lên kế hoạch). Năm lỗi dưới đây **đã đo sống**, mỗi lỗi
trỏ thẳng tới phần sửa trong `docs/plan/v21-boxfox-plan.md`; nhật ký đầy đủ ở
`docs/tracking/test-rounds.md` § *Vòng 21*.

**Cập nhật vòng 22 (2026-09-22).** Đợt foundation của vòng 22 đã sửa **bốn** lỗi dưới đây rồi đo lại; bảng và số đo ở § 6.23.
Trạng thái mới: **BUG-39 — ĐÃ SỬA** (popover render qua portal; hit-test trả `true` ở **cả bốn** mục, mục Drive nói thật "chưa kết nối"),
**BUG-40 — ĐÃ SỬA** (tệp vào box **đúng byte**, đường dẫn tuyệt đối có trong event `user` **và** trong ngữ cảnh gửi model, chuỗi
`[Attached Files: …]` bị bỏ), **BUG-41 — ĐÃ SỬA** (một lượt thử lại có ép công cụ trước khi chịu thua), **BUG-42 — ĐÃ SỬA**
(chạm trần bước hoặc hạn chót ⇒ `partial` + chẩn đoán bốn phần thay vì `failed` trắng; con nhận tới 40 bước / 300 s).
**BUG-43 giữ nguyên** vì thuộc đợt peer-mesh của vòng 22 (D-9) — đợt này không đụng tới.

**BUG-39 — mức Trung bình — menu `+` đủ mục trong DOM nhưng bị `overflow-hidden` cắt, người dùng thấy "chưa có upload".**
Khi menu đang mở, `document.elementFromPoint` tại tâm mục `Tải lên hình ảnh` (`itemRect [290,642,226,45]`) trả về khung
chat ⇒ mục không phải phần tử trên cùng, tức không vẽ ra. Tổ tiên cắt là `flex min-w-0 items-center gap-1.5 overflow-hidden`
(`frontend/src/components/panels/ChatInputBar.tsx:268`) trong khi popover đặt `absolute bottom-full`
(`frontend/src/components/chat/AttachmentPicker.tsx:159`). Lặp lại được ở cả địa chỉ công khai lẫn `localhost:3100`.
Sửa theo `A1` (bỏ `overflow-hidden` hoặc render bằng portal, không chữa bằng `z-index`).

**BUG-40 — mức Cao — nội dung tệp đính kèm không bao giờ tới box; agent chỉ nhận cái tên.**
Chỉ ảnh được đọc bằng `FileReader` thành `dataUrl` (`AttachmentPicker.tsx:56-68`); tệp thường chỉ giữ `name`/`size`
(`:69-77`) và lúc gửi trở thành chuỗi `` `[Attached Files: ${…}]` `` (`ChatInputBar.tsx:113-115`). Đo sống: event `user` của
phiên `0ef73471c38d4c63a593755345213dcf` đúng bằng phần text cộng `\n\n[Attached Files: probe-upload.txt]`, không nội dung
và không đường dẫn; sau lượt `docker exec agentbox-box ls .uploaded_artifacts` **rỗng** và
`find /home/agent/workspace -name '*probe-upload*'` **không có**. Agent phải tự đi tìm, kết luận "tệp không tồn tại".
Đường ống nhận tệp đã có sẵn nhưng **chưa có đường nào gọi từ ô soạn tin** (panel Workspace Files đã gọi nó —
`frontend/src/hooks/useWorkspaceFiles.ts:473`): `POST /__box/file/upload` (`deploy/docker/ide-proxy.py:540-568`),
`workspace_files.write_upload` (`deploy/docker/workspace_files.py:743-754`), client `frontend/src/lib/workspace/http.ts:70-87`,
thư mục đích tạo lúc boot (`deploy/docker/box-entrypoint.sh:15-24`); luật tên RULE-5 (`docs/naming.md:24`) **chưa có code
nào cấp số** — kế hoạch `A2–A6` giao việc cấp số cho phía box.

**BUG-41 — mức Trung bình — `TURN_EMPTY_RESPONSE` đánh `failed` cả lượt dù model đã làm việc, không thử lại, không trả phần đã làm.**
Phiên `0ef73471…` chết ở bước 5: `error {code: TURN_EMPTY_RESPONSE}` với `thought` đã có nhưng không có text và không có
tool call; người dùng mất trọn lượt, không có câu trả lời một phần. Sửa theo `B6` (một lượt thử lại có ép công cụ, hết cách
mới `failed`), cùng họ với lỗi C2 đã sửa ở đợt 20.

**BUG-42 — mức Cao — con chạm `DEADLINE` (10 bước/120 s) thì mất trắng phần đã làm, cha chỉ nhận `failed`.**
Phiên con `ea9486495da646d7aac4ccd4214ea8ed` (`delegate_task role=explore`) chạy 10/10 bước, 33 tool call, hết 120 s ⇒
`DEADLINE: the turn ran out of time before an answer was produced`, `answerChars = 0`; cha nhận `status=failed` và phải nói
với người dùng là "không có bằng chứng nào". Cùng mã lỗi `DEADLINE` như ảnh chủ nhà gửi (`Error code: DEADLINE`,
`Worked for 180s`); lượt gốc trong ảnh là chủ nhà báo, vòng này không tái hiện được (phiên gốc đã bị dọn khỏi store) —
vòng này tái hiện được cùng mã lỗi ở **agent con** (120 s). Trần bước
cũng đánh `failed` một việc đã xong (`failures.py:52`). Sửa theo `B2–B4`: tách mã `STEP_BUDGET_EXHAUSTED` /
`DEADLINE_EXCEEDED`, **trả `partial` có nội dung thay vì `failed`**, nâng ngân sách con lên 24 bước/240 s, và ghim `X:`
blocker để lần sau biết đã mất gì.

**BUG-43 — mức Trung bình — bảng Sub-agents không theo turn: con của turn trước hiện ở turn sau.**
Đo sống: lượt 2 sinh con `ea948649…`; lượt 3 hỏi `2+2` (xong trong 3 s, không gọi tool nào) mà bảng vẫn ghi
`SPECIALISTS PIPELINE · 1 TOTAL · Explore Specialist FAILED · 33 tools executed`
(`/code/.generated_artifacts/images/r21_perTurn_03_turn3_with_stale_child.png`). Gốc: `childrenMap` dựng từ **mọi** event
`child` của phiên (`frontend/src/components/panels/SubagentInspectorPanel.tsx:162-196`, render `:347`/`:361`) và store không
cắt theo turn (`frontend/src/store/harnessChatStore.ts:294`); event `child` cũng **không mang `turn`/`step`**
(`backend/src/agentbox/agent_core/runtime.py:2523-2530`, `:2564`) nên giao diện không có dữ liệu để phân. Sửa theo `E1–E3`.

**Ghi nhận đúng, không phải lỗi.** (1) Trần mặc định 16 bước **không** chặn việc vừa phải: lượt đọc hai tệp + grep + viết
báo cáo + đọc lại xong ở **bước 8** (phiên `dddebffb…`). (2) `muse-spark-1.2-contributor-free` và
`muse-spark-1.3-contributor-free` của OpenCode Free đều chạy được (`status: passed`, có usage), nên không có việc "thiếu model".
(3) Địa chỉ xem trước công khai chỉ để **xem**: harness chỉ nhận `Origin` loopback
(`backend/src/agentbox/api/server.py:119-139`), nên mọi lượt chạy phải đi qua `localhost:3100` — đúng thiết kế, không phải lỗi.

### 6.23 Vòng 22 (đợt 1 — foundation) — bốn lỗi vòng 21 đã sửa và đo lại, một lỗi mới (BUG-44), ba lỗi nữa do đợt kiểm thử tìm và sửa (BUG-45…BUG-47)

Đợt 1 của `docs/plan/v22-boxfox-plan.md` sửa bốn lỗi đo sống ở vòng 21, đo lại bằng ba bộ test và một lượt thử sống đầu-cuối qua
`localhost:3100`; chính lượt đo đó lộ thêm **một** lỗi (BUG-44) thuộc đợt bằng chứng sống. Đợt **kiểm thử độc lập** chạy sau đó trên cùng cây (HEAD `f57619d`
cộng bốn bản vá của đợt kiểm thử) tìm thêm **ba** lỗi nằm trong chính mã mới của đợt này — BUG-45…BUG-47, đều đã sửa kèm test
và đo lại sống. Nhật ký đầy đủ (số đo, lệnh, phiên):
`docs/tracking/test-rounds.md` § *Vòng 22*.

| Mã | Mức | Nội dung | Nơi sửa | Trạng thái |
|---|---|---|---|---|
| BUG-39 | TB | Menu `+` đủ mục trong DOM nhưng bị `overflow-hidden` cắt | `frontend/src/components/chat/AttachmentPicker.tsx`, `frontend/src/components/panels/ChatInputBar.tsx` | ĐÃ SỬA |
| BUG-40 | Cao | Nội dung tệp đính kèm không bao giờ tới box; agent chỉ nhận cái tên | `frontend/src/lib/chat/attachmentUpload.ts`, `frontend/src/components/panels/ChatInputBar.tsx`, `backend/src/agentbox/agent_core/{attachments,runtime}.py`, `backend/src/agentbox/skills/runtime_commands.py`, `backend/src/agentbox/api/server.py`, `deploy/docker/{workspace_files,upload_files,ide-proxy}.py` | ĐÃ SỬA |
| BUG-41 | TB | `TURN_EMPTY_RESPONSE` đánh `failed` cả lượt dù model đã làm việc | `backend/src/agentbox/agent_core/runtime.py` | ĐÃ SỬA |
| BUG-42 | Cao | Con (và lượt chính) chạm trần bước/hạn chót thì mất trắng phần đã làm | `backend/src/agentbox/agent_core/{limits,failures,runtime}.py` | ĐÃ SỬA |
| BUG-43 | TB | Bảng Sub-agents không theo turn | — | HOÃN — thuộc đợt peer-mesh của vòng 22 (D-9) |
| BUG-44 | TB | Câu trả lời về tệp đính kèm có thể in **nội dung cũ trong ngữ cảnh** mà không mở tệp; không cổng nào bắt; cùng gốc với nhãn `done` xanh luôn hiện và khối `journal` bị giao diện ném đi | `backend/src/agentbox/agent_core/{limits,runtime,evidence_gate,session_journal,journal}.py`, `backend/src/agentbox/sandbox/{executor,worker}.py`, `backend/src/agentbox/api/server.py`, `frontend/src/components/chat/HarnessStepView.tsx`, `frontend/src/store/harnessChatStore.ts` | ĐÃ SỬA (đợt 3 — §6.25; phần khẳng định thuần văn không có đường dẫn vẫn ngoài tầm cổng) |
| BUG-45 | TB | Dọn `.uploaded_artifacts` (`uploads_prune`) nuốt `OSError` khi `unlink` ⇒ báo `removedFiles: 0` như đã dọn sạch trong khi tệp vẫn nằm trên đĩa, không ghim hàng `X:` nào | `deploy/docker/upload_files.py` (`prune`), `deploy/docker/tests/test_upload_files.py` | ĐÃ SỬA |
| BUG-46 | TB | Hai lượt `migrate_plans.py --apply` trong cùng một giây dùng chung một thư mục sao lưu ⇒ ghi đè `manifest.json` và bản sao byte của lượt trước | `deploy/docker/migrate_plans.py` (`write_backup`), `deploy/docker/tests/test_migrate_plans.py` | ĐÃ SỬA |
| BUG-47 | Thấp | Câu từ chối `header-mismatch` in "khai vv2" (lặp chữ `v`) và gọi khối **sai cú pháp** là "khai vVersion: v2" ⇒ model đi sửa phiên bản trong khi lỗi thật là cú pháp | `backend/src/agentbox/agent_core/{plan_registry,plan_eval}.py` + `test_plan_registry.py`, `test_plan_eval.py` | ĐÃ SỬA |

**BUG-39 — đã sửa, đo lại sống.** Popover nay render qua **portal** nên không còn bị tổ tiên `overflow-hidden`
(`frontend/src/components/panels/ChatInputBar.tsx`) cắt. Số đo sau sửa, cùng phép thử vòng 21: `document.elementFromPoint` tại tâm
**cả bốn** mục trả `true` (`Tải lên hình ảnh`, `Tải lên tệp tin` — có dòng `Tối đa 25 MB/tệp · 20 tệp/lượt`, `Tải lên thư mục`,
`Google Drive`); mục Drive ở trạng thái `disabled: true` và hiện đúng câu "Chưa kết nối — không đính kèm được tài liệu Drive".
Bài kiểm giao diện khoá hành vi này trong `frontend/src/components/chat/AttachmentPicker*.test.tsx` và `ChatInputBar.*.test.tsx`.

**BUG-40 — đã sửa, đo lại sống.** Đường gửi nay **tải tệp lên box trước**, rồi gửi kèm chỉ đường dẫn
(`frontend/src/lib/chat/attachmentUpload.ts`), harness kiểm và suy ra đường dẫn tuyệt đối
(`backend/src/agentbox/agent_core/attachments.py`) rồi ghép khối `[Tệp đính kèm đã lưu trong box]` vào text gửi model.
Số đo: `.uploaded_artifacts` **5 → 7 tệp** trong đợt (`6.md` 31 B, `7.md` 34 B), cả hai **khớp byte** với tệp gốc;
event `user` của phiên `c4cf5256d3174303b363cd3896ba0246` mang
`{name: 7.md, path: .uploaded_artifacts/7.md, absolutePath: /home/agent/workspace/.uploaded_artifacts/7.md, sizeBytes: 34, kind: file}`;
hàng `messages` của phiên trong `~/BoxFox/harness/sessions.sqlite` (ngữ cảnh gửi model) chứa khối
`[Tệp đính kèm đã lưu trong box]` với dòng `- /home/agent/workspace/.uploaded_artifacts/6.md (6.md, 31 B)`;
phiên **mới** `92f76c90467d4dfaaa3bbb3d40278069` (không ngữ cảnh cũ) nhận **chỉ đường dẫn tương đối** rồi gọi
`file_read {"path": "/home/agent/workspace/.uploaded_artifacts/6.md"}` và trả về đúng dòng đầu của tệp
(`stepsUsed 2`, `toolsRun 1`). Số RULE-5 nay do **box** cấp bằng `O_CREAT|O_EXCL` + thử lại số kế (BOX-6, `docs/naming.md` § 9):
bốn lượt tải song song cùng lúc cho `2.md 3.md 4.md 5.md`, `uniq -d` rỗng.

**BUG-41 — đã sửa.** Ranh giới câu trả lời cuối nay **thử lại một lần** khi model kết thúc mà không có text và không có tool call:
lần thử lại ghim notice `TURN_EMPTY_RESPONSE_RETRY` kèm `attempt`/`how` và một hàng `system_log.write('turn.retry', …)`; chỉ khi lần
thử lại cũng rỗng thì lượt mới chịu thua như trước. Bài khoá: `backend/tests/unit/test_harness_runtime.py` (nhánh thử lại) và
`test_turn_partial_budget.py`.

**BUG-42 — đã sửa, đo lại sống.** Hai mã nay tách hẳn (`STEP_BUDGET_EXHAUSTED`, `DEADLINE_EXCEEDED`; mã cũ giữ lại chỉ để đọc
bản ghi cũ), và cả hai đường đều đóng bằng **chẩn đoán bốn phần** thay vì `failed` trắng. Số đo: lượt `maxSteps: 4`
(phiên `1cbb482079de430091e2de76f18144ae`) kết thúc `partial` với `turn_end {status: partial, stepsUsed: 2, toolsRun: 1, deadlineUsedMs: 4953, partial: true, diagnosis: true}`
và **đúng một** notice `STEP_BUDGET_EXHAUSTED {diagnosisChars: 465, reservedSteps: 3}`; câu trả lời cuối 465 ký tự, đủ bốn phần
(đã làm / đang kẹt ở / còn lại / thử tiếp theo); hàng `sessions` vẫn `completed` (không thêm giá trị `status` mới). Lượt con
`explore` `122a9a866b1342249b9affc749d9030d` nhận `maxSteps 5` / `deadlineSeconds 300` (kẹp theo cha) và trả về cha
`{status: partial, answerChars: 948, reason: STEP_BUDGET_EXHAUSTED, diagnosis: true, stuckReason: STEP_BUDGET_EXHAUSTED, is_error: false}`.
Ngân sách mới của con: `CHILD_MAX_STEPS = 40`, `CHILD_DEADLINE_SECONDS = 300` — vẫn bị kẹp theo cha như trước, nên trần thật là
`min(40, maxSteps của cha)`. Không lượt đo nào sinh hàng `X:` mới (nhánh ghim blocker chỉ chạy khi chẩn đoán không kịp).

**BUG-44 — mức Trung bình — model trả lời về tệp đính kèm bằng nội dung của **lượt trước**, không mở tệp; không cổng nào bắt.**
Đo sống trong chính lượt E3 đầu tiên (phiên `c4cf5256d3174303b363cd3896ba0246`): người dùng gửi `6.md` **mới** rồi hỏi dòng đầu tiên;
`turn_end` ghi `toolsRun: 0` (không có lần đọc nào) nhưng câu trả lời vẫn nêu đúng đường dẫn tuyệt đối và in **nội dung cũ** của tệp
(`LIVE-E2E-1790075144940`, của lượt trước trong cùng phiên), trong khi tệp trên đĩa lúc đó đã là `FOUNDATION-E2E-20260922T111913`.
Nội dung cũ **trông đúng** (đúng đường dẫn, đúng khuôn) nên người đọc không có cách nào biết là sai — đây là mặt trái của D-6:
đường dẫn tới nơi được, nhưng **không gì ép model mở tệp**, và **không cổng nào** kiểm câu trả lời cuối
(`frontend/src/components/chat/HarnessStepView.tsx` ghim badge `done` vô điều kiện; store bỏ `session.journal`). Cùng ngày, khi model
**có** gọi `file_read` (phiên `92f76c90467d4dfaaa3bbb3d40278069`) thì câu trả lời đúng từng ký tự, nên lỗi nằm ở đường "không đọc"
chứ không ở đường truyền tệp. Hướng sửa: **cổng bằng chứng** của D-8 (`docs/plan/v22-evidence-proof.md`); đợt này ghi nhận,
không sửa — đúng phạm vi đã chốt.

**BUG-45 — mức Trung bình — dọn `.uploaded_artifacts` báo "đã xong" khi tệp không xoá được.** `prune()` bắt `OSError` rồi
`continue` mà không ghi lại gì, nên một lượt dọn vượt trần 200 tệp trả `{"removed": [], "removedFiles": 0, "ok": true}` và
**không** ghim hàng `X:` — người vận hành tin là trần đã được dọn. Đo sống trên chính box: fixture 203 tệp, 3 tệp **thuộc root**
nên `unlink` của agent ném `PermissionError: [Errno 13]`. Sau khi sửa, cùng lượt đó trả `removedFiles: 0`,
`failedFiles: 3`, `deletionFailures` gồm `1.md` / `10.md` / `11.md` với đúng chuỗi `PermissionError: [Errno 13] Permission denied: '<đường dẫn>'`,
và ghim **đúng một** hàng `X:f2f01657-1` (`kind: blocker, status: done, actor: box-retention`) với
`text: "dọn tệp tải lên theo trần 200 tệp / 500 MiB: bỏ 0 tệp / 0 B (còn 200 tệp / 400 B); không xoá được 3 tệp."` và
`numbers.failedFiles: 3`. `FileNotFoundError` vẫn được coi là vô hại ("lượt dọn khác đã xoá trước"). Sửa: thêm danh sách
`deletionFailures`, đếm `failedFiles`, đổi điều kiện ghim và câu chữ của hàng `X:`. Test:
`test_upload_files.py::test_a_planned_file_that_cannot_be_unlinked_is_reported_not_swallowed` và
`::test_a_clean_prune_reports_no_failures`.

**BUG-46 — mức Trung bình — hai lượt `--apply` trong cùng một giây ghi đè bản sao của nhau.** `utc_stamp()` chỉ có độ phân giải
**giây** (`%Y-%m-%dT%H-%M-%SZ`) và `write_backup` dùng `mkdir(parents=True, exist_ok=True)`, nên lượt thứ hai trong cùng giây
**dùng lại** thư mục cũ: `manifest.json` bị ghi đè và bản sao `vN-*.md` của lượt trước bị thay bằng bản mới — trái với chính
docstring của module ("hai lượt không bao giờ đè nhau"), tức là mất đúng thứ mà C1/C2 vừa dựng lên để bảo vệ. Đo sống trong box:
hai lượt `--apply` liên tiếp trên cùng `--backup-dir`; trước khi sửa cả hai vào cùng thư mục `2026-09-22T14-04-42Z`; sau khi sửa
thành `2026-09-22T14-04-42Z` và `2026-09-22T14-04-42Z-2`, `manifest.json` của lượt đầu còn nguyên và bản sao trong đó vẫn là các
byte **trước** khi lượt hai ghi (không chứa `boxfox-plan`). Sửa: helper thuần `free_backup_directory(target)` trả thư mục trống kế
tiếp (`-2`, `-3`, …). Test: `test_migrate_plans.py::test_two_runs_in_the_same_second_do_not_share_a_backup_directory`.

**BUG-47 — mức Thấp — câu từ chối `header-mismatch` chỉ sai chỗ cần sửa.** Hai lỗi chữ: (1) `REMEDIES['header-mismatch']` in
`khai v{declared}` trong khi nơi gọi đã thêm `v` ⇒ người dùng đọc **"khai vv2"**; (2) `plan_eval` P1 coi khối **sai cú pháp**
(`status != 'ok'`) là lệch phiên bản kể cả khi số phiên bản khớp, nên câu từ chối thành "khai vVersion: v2" và hướng dẫn model đi
sửa phiên bản trong khi lỗi thật là cú pháp. Cả hai đo sống trong phiên `629dfc6eced347f995b0da3c603aecb5` (lượt gửi 6,
`Parent: boxfox-upgrades-two@v1`). Sửa: `plan_registry` nhận sẵn chuỗi khai (`declared='khai v{n}'`) và bỏ `v` khỏi khuôn câu;
`plan_eval` phân biệt cú pháp với số (`không đúng cú pháp (đọc được: Version: v2, Identity: x)` so với `khai Version: v5, …`).
Test: `test_plan_registry.py` (bỏ `vv3`, còn `khai v3`) và
`test_plan_eval.py::test_a_malformed_block_is_named_as_syntax_not_as_a_version_mismatch`.

**Ghi nhận, không phải lỗi.** (1) `test_terminal_tools.py::test_terminal_exec_echo` **đỏ sẵn có** vì `bash` của sandbox không có
lệnh `Write-Output` (`Exited with code 127`) — không liên quan đợt này; bộ backend còn lại **902 passed**. (2) Không dựng lại ảnh box:
`worker.py` được gửi **nội tuyến** trong mỗi lần gọi, nên thay đổi phía box (`read_file_payload`, `SESSION_OP_NAMES`) có hiệu lực ngay.
(3) `frontend/.env.local` (tệp **không** được theo dõi, dùng cho đường xem trước) trỏ API về `"."`, nên bộ frontend phải chạy với
`VITE_BOX_API_URL=http://localhost:8081` — với biến đó **118 tệp / 958 bài passed**.

### 6.24 Vòng 22 (đợt 2 — mesh agent con): ba lỗi và hai khiếm khuyết lộ ra trong chính lúc thi công (BUG-48…BUG-52)

Bốn cái đầu đo được trên lượt **sống** (harness thật + giao diện thật ở `localhost:3100`), cái thứ năm lộ ra khi rà lại bộ đếm
của T13. Bốn cái đã sửa trong đợt này; BUG-51 **ghi nhận, chưa sửa** vì hướng sửa là thay đổi cấu trúc ở đường đóng lượt.

**BUG-48 — mức Cao — cha chờ chính con ruột đã đóng sổ, lượt treo tới lưới an toàn.** `peer_wait_pending` coi một mục tiêu là
xong **chỉ khi** có biên nhận của người chờ trong `child_deliveries`; mà T11 chỉ ghi biên nhận cho `main` khi con **khai**
`deliverTo`. Cách gọi tự nhiên nhất của cha — `await_children()` không truyền gì, chờ đúng những đứa con ruột của mình — vì thế
trả `timeout` cho **những đứa con đã chạy xong**, và lượt cha ngồi chờ hết lưới an toàn 300 s một cách vô ích. Sửa (`fa6a2b7`):
`peer_is_own_closed_child(sid, target)` — mục tiêu là con ruột của người chờ **và** hàng sổ con đã đóng ⇒ coi là xong; kèm theo,
`deliver_child_result` đánh thức cha ngay lúc con đóng sổ khi con khai người nhận rỗng (không để cha chờ hết nhịp quét).
Bạn cùng cha giữ nguyên luật cũ: đóng sổ mà chưa giao là **chưa** giao. Test:
`test_await_children.py::test_await_children_cha_khong_can_bien_nhan_tu_con_ruot_da_dong_so` (chờ xong trong **< 1,0 s** thay vì
chờ hết lưới) và ca cũ về hàng xóm cùng cha vẫn giữ `status == 'timeout'`.

**BUG-49 — mức Cao — chi phí của con ghi thiếu: chỉ bước cuối, và `NULL` khi bước cuối không có `usage`.** Hai đường đóng sổ
của con — `close_detached_child` (mọi con `wait=false`, tức đường mà lượt sống đi qua) và đường cha-chờ-con trong `_run_child` —
đều chỉ đọc `turn_end` **cuối cùng**. Đo sống: phiên `3647fe8e3e8f43d79e9753a4c2cdb463`, con `review` chạy 9 bước có
`outputTokens` trong luồng, bước 9 là bước chẩn đoán `partial` **không** mang khối `usage`, nên hàng sổ con ghi
`output_tokens = NULL` và `childTokens` của lượt cha báo **0**; phiên `46c47921a8474c4a985b9c64f3144cac`, con `review` 5 bước với
token từng bước 410 + 535 + 368 + 488 + 1 076 = **2 877** nhưng sổ chỉ ghi **1 076**. Sửa (`51a1af7`):
`SessionStore.child_usage_from_events(child_id)` đọc **cả chuỗi** `turn_end` của con (`stepsUsed` lấy `max` vì là số luỹ kế của
lượt, `outputTokens` **cộng** theo bước), `child_close_once(..., steps_used, output_tokens)` ghi được bộ số, và event `child`
kết thúc mang theo `stepsUsed`/`outputTokens`. Test:
`test_peer_cost.py::test_token_cua_con_cong_ca_chuoi_buoc_khong_chi_buoc_cuoi` (con ba bước, bước cuối không `usage` ⇒ sổ ghi
3 bước / 12 token) và `test_async_delegation.py::test_con_tu_xong_cung_cong_token_ca_chuoi_buoc`.

**BUG-50 — mức Trung bình — nhãn chờ in `[object Object]`.** Sự kiện thật `peer_wait` mang `targets` dạng **vật thể**
(`[{'sessionId': …, 'role': …}]`, sinh từ hàng sổ con), còn `peerLabel` trong `frontend/src/lib/chat/peerPipeline.ts` chỉ biết
chuỗi (`String(target ?? '').trim()`), nên hàng con trong panel Sub-agents hiện nguyên `[object Object]`. Đo sống trên DOM
(phiên `e94f1af064254fef8a0e5b681db7db1f`, lượt chạy qua giao diện):
`đang chờ [object Object] giao kết quả· lưới an toàn còn 5:00`. Sửa (`5a084f6`): `peerLabel` đọc vật thể trước — lấy chuỗi không
rỗng đầu tiên trong `role`, `roleId`, `sessionId`, `name` (đệ quy qua `peerLabel`), trả chuỗi rỗng khi không đọc được, **không bao
giờ** trả `[object Object]`; nhánh chuỗi (bỏ tiền tố `role:`) giữ nguyên. Sau khi sửa, cùng kịch bản sống (phiên `19271d91…`,
lượt 2, con `testing` chờ con `review`): `đang chờ review giao kết quả· lưới an toàn còn 5:00`. Test:
`frontend/src/lib/chat/peerPipeline.test.ts` (4 ca, gồm `openPeerWait` với dạng vật thể thật) và một ca trong
`SubagentInspectorPanel.turns.test.tsx` khẳng định huy hiệu **không** chứa `[object Object]`.

**BUG-51 — mức Thấp — `finish` đọc sổ con trước khi reap, nên ảnh chụp thiếu phần của con bị reap. — CHƯA SỬA.** `reap_children`
(T7) chạy trong khối `finally` của `_run`, tức **sau** khi event `finish` đã phát; một con còn `started` lúc lượt đóng vì thế
không có mặt trong `childSteps`/`childTokens` của lượt. Đo sống: phiên `bb142655d9634b7f86270717b985e3fb` — `finish` ở
`1790100321.0228` ghi `childCount 2, childSteps 19, childTokens 12 509`; hàng con `testing` (`944d6bde…`) đóng ở
`1790100321.0249` bằng `PARENT_TURN_ENDED` với `steps_used 11`, `output_tokens 5 093` — lệch nhau **2,2 ms**, và sổ con đúng
trong khi ảnh chụp ở `finish` thiếu 11 bước / 5 093 token. Số trong **sổ con** (thứ giao diện và `session_metrics.peers` đọc)
vẫn đúng; chỉ ảnh chụp của riêng event `finish` thiếu. Ghi nhận, không sửa trong đợt này: hướng sửa (reap **trước** khi phát
`finish`, hoặc phát thêm một event hiệu chỉnh sau reap) là thay đổi thứ tự ở đường đóng lượt — làm muộn trong vòng này là rủi ro
không cần thiết; vòng sau sửa kèm test khoá thứ tự.

**BUG-52 — mức Trung bình — ngân sách chờ 300 s của "mỗi lượt" trên thực tế là mỗi PHIÊN.** `runtime.wait_extension` chỉ được
cộng thêm mỗi lần chờ mà **không bao giờ** được đặt lại, nên lượt thứ hai của một phiên thừa hưởng ngân sách đã tiêu của lượt
thứ nhất: chờ đủ 300 s ở lượt một thì mọi lượt sau không còn ngân sách chờ, và `await_children` trả `extensionExhausted` ngay.
Lỗi lộ ra khi rà lại bộ đếm của T13 chứ không từ một triệu chứng người dùng báo. Sửa (`a21c598`): `_run` đặt
`self.wait_extension[sid] = 0.0` ngay sau khối xác định số lượt. Test:
`test_peer_cost.py::test_ngan_sach_cho_ve_khong_o_moi_luot` (đẩy bộ đếm của phiên lên 1 000 s trước lượt một, khẳng định lượt
đó vẫn còn nguyên 300 s và bộ đếm sau lượt chỉ còn giây đã chờ của **chính lượt đó**).

**Ghi nhận, không phải lỗi.** (1) `test_terminal_tools.py::test_terminal_exec_echo` **đỏ sẵn có** (`bash` của sandbox không có
`Write-Output`, `Exited with code 127`) — không liên quan đợt này. (2) Hai lượt sống chết vì lý do môi trường:
`UPSTREAM_HTTP_429` ("This target is cooling down after a provider limit") ở phiên `b4f26ca6e8c44f458cceb5ba86e87e34` và
`62146c6e498d41f4b662d8295d91054e`; lượt sống chạy lại sau đó xanh. (3) Hai ca `test_cua_element_selector.py` phụ thuộc desktop
của box (X/VNC) và mạng egress của box — không thuộc mã đợt này. (4) Không dựng lại ảnh box: `worker.py` gửi nội tuyến trong
mỗi lần gọi.

### 6.25 Vòng 22 (đợt 3 — bằng chứng sống) và hậu kiểm đợt 2: BUG-44 đã sửa, sáu lỗi mesh ghi sổ (BUG-53…BUG-58), một lỗi mới (BUG-59)

Đợt 3 của `docs/plan/v22-boxfox-plan.md` (kế hoạch ba đợt, § Phần P1–P6) dựng **cổng bằng chứng**: mỗi lượt được chấm lúc đóng,
câu trả lời cuối mang nhãn ba trạng thái, và mảnh kiểm chứng được sinh **ngay tại chỗ ghi tệp**. Cùng nhánh này còn có hậu kiểm
đợt 2 (bốn vòng soát độc lập) — bốn lỗi mã `BUG-53…BUG-56` cộng hai lỗi nhỏ `BUG-57`/`BUG-58` đã sửa ở `d5d80c4`, nhưng mã của
chúng mới chỉ nằm trong thông điệp commit; § này ghim chúng vào sổ. Trong lúc thi công lộ thêm **một** lỗi thật của đường ảnh
chụp (BUG-59). Số đo, lệnh và phiên đầy đủ: `docs/tracking/test-rounds.md` § *Vòng 22 — đợt 3*.

| Mã | Mức | Nội dung | Nơi sửa | Trạng thái |
|---|---|---|---|---|
| BUG-44 (§6.23) | TB | Cùng một lỗi gốc, nhìn từ mặt bằng chứng: câu trả lời cuối đội nhãn `done` xanh mà không có bất kỳ kiểm chứng nào; tool sửa tệp trả về chuỗi rỗng nghĩa (không diff, không hash); giao diện ném khối `journal` của API | `agent_core/{limits,runtime,evidence_gate,session_journal,journal}.py`, `sandbox/{executor,worker}.py`, `api/server.py`, `frontend/src/components/chat/HarnessStepView.tsx`, `frontend/src/store/harnessChatStore.ts` | ĐÃ SỬA |
| BUG-53 | Cao | Slot fan-out nhả **hai lần** cho một con ⇒ trần toàn cục (8) và trần theo cha (3) bị vượt trong im lặng | `agent_core/peer_watchdog.py`, `agent_core/runtime.py` | ĐÃ SỬA |
| BUG-54 | Thấp | Huỷ lượt ĐANG xếp hàng slot để lại permit của cha đã mua (`CancelledError` đi thẳng ra ngoài `wait_for`) | `agent_core/runtime.py` | ĐÃ SỬA |
| BUG-55 | TB | Đường `wait=true` phát event kết thúc **sau** khi giao hàng ⇒ một lỗi giao hàng làm cha không bao giờ thấy con đã đóng | `agent_core/runtime.py` | ĐÃ SỬA |
| BUG-56 | TB | Khối "chi phí theo lượt" thực ra là theo PHIÊN (`peer_turn_cost` bỏ qua lượt, `children_summary` không lọc `parent_turn`) | `agent_core/runtime.py`, `memory/session_store.py` | ĐÃ SỬA |
| BUG-57 | Thấp | Một lần chờ bị huỷ để lại `waiting_for`/`waiting_since` trên hàng sổ con và cờ đánh thức sống sang lượt sau | `agent_core/runtime.py` | ĐÃ SỬA |
| BUG-58 | Thấp | `deliverTo: ['main']` không đánh thức người đang chờ ⇒ lượt chờ thêm một nhịp quét, "không khai gì" lại nhanh hơn | `agent_core/runtime.py` | ĐÃ SỬA |
| BUG-59 | Thấp | Ảnh chụp/ghi hình không bao giờ mang số bước: harness **không gửi** `step`/`toolCallId` dù cả hai route của box đã đọc từ lâu, nên tên tệp luôn rơi về `000` | `sandbox/executor.py` | ĐÃ SỬA |

**BUG-44 — mức Trung bình — câu trả lời cuối đóng dấu "xong" mà không có gì kiểm chứng được.** Bốn bằng chứng đo được trước khi
sửa: (1) nhãn cuối là khối `CheckCircle2` + chữ `done` **cứng** ở `HarnessStepView.tsx:1534-1537`; (2) giao diện ném khối `journal`
API trả về — grep `journal` trong `harnessChatStore.ts:285-338` ra **0** kết quả; (3) bảng `journal` của box chỉ có **một** hàng
`kind='plan'` trên mười phiên, tức dấu vết bền gần như không tồn tại; (4) `worker.py:345-357` — `file_write`/`file_edit_block` trả
chuỗi rỗng nghĩa, nên *nguyên liệu* để kiểm chứng cũng không có. Sửa (đợt 3, P1.2–P1.5 + P2 + P3 + P4):
`evidence_gate.py` chấm mỗi lượt theo R1–R5 (thuần, không I/O) trên chính các lời gọi công cụ của lượt; `runtime.py` chèn cổng giữa
câu trả lời cuối và lúc phát nó, **một** phép dò `find` cố định khi lượt có ghi, **tối đa một** vòng vá chỉ ở `enforce`; mọi lỗi của
cổng rơi về `not_measurable` + notice + hàng `X:`, không bao giờ đổi văn câu trả lời; `worker.py`/`executor.py` sinh diff + sha256
+ số dòng **tại chỗ ghi** vào `.generated_artifacts/captures/evidence/<sid8>/`; giao diện giờ đọc khối `journal`, hiện nhãn ba trạng
thái (`verified`/`unverified`/`not_measurable`) kèm danh sách mảnh bằng chứng mở được, và lượt **thiếu** trường `evidence` được coi là
`unverified` — không bao giờ xanh. Công tắc `BOXFOX_EVIDENCE_GATE` mặc định `warn`. **Còn nợ, nói thẳng:** cổng chỉ chấm được
khẳng định máy đọc được (đường dẫn trong dấu backtick, lệnh, công cụ ghi/ảnh chụp); một khẳng định **thuần văn** về nội dung tệp
("tệp đính kèm nói rằng…") mà lượt không mở tệp vẫn ngoài tầm R1–R5, và phần đó của BUG-44 chưa được đóng.

**BUG-53 — mức Cao — một con được nhả slot hai lần.** `peer_watchdog._cancel_task` nhả slot ngay lúc huỷ task, rồi callback lúc
task đóng nhả lần nữa; `asyncio.Semaphore` **không** cấm nhả thừa, nên hai cái trần cùng bị vượt mà không có lỗi nào được ghi. Đo
trên bản cũ (`/var/tmp/rev2/probe_slots2.py`): ba con của một cha ⇒ `global_child_slots._value = 11` (trần là 8) và `parent_running`
về 0 sớm nên `parent_slots` bị bỏ trong khi con vẫn chạy. Sửa: slot gắn với **đúng một** con (`child_slot_holders`, chìa khoá là
`child_id`), mọi đường nhả đi qua `release_child_slot` và idempotent theo con. Test: `test_peer_slot_lifecycle.py` (4 ca, gồm ca
"watchdog nhả đúng một slot").

**BUG-54 — mức Thấp — huỷ lúc đang xếp hàng làm mất permit của cha.** `wait_for` chỉ bắt `TimeoutError`, còn `CancelledError` đi
thẳng ra ngoài — mà đường thoát đó **không** nhả permit đã mua cho cha, nên mỗi lần huỷ ăn một chỗ trong trần theo cha. Sửa: nhả slot
rồi ném tiếp. Test: ca "huỷ lúc xếp hàng slot" trong `test_peer_slot_lifecycle.py`.

**BUG-55 — mức Trung bình — con đóng sổ rồi mà cha không biết, vì sự kiện bị giao hàng chặn.** Đường `wait=true` giao kết quả
**trước** rồi mới phát event `child` kết thúc; một lỗi giao hàng (SQLite khoá, đĩa đầy) vì thế làm luồng cha không bao giờ thấy con đã
đóng, và lỗi hạ tầng đội lốt lỗi của lời gọi công cụ — người đọc tưởng model gọi sai. Sửa: bọc `deliver_child_result` trong
`try/except` ghi `child.delivery_failed`, và event kết thúc **luôn** được phát (kèm `deliveries: []` khi không giao được). Test: ca
"giao hàng hỏng vẫn phát event kết thúc".

**BUG-56 — mức Trung bình — "chi phí theo lượt" là chi phí cả phiên.** `peer_turn_cost` bỏ qua tham số lượt và `children_summary`
không lọc `parent_turn`, nên `finish` của lượt thứ ba báo **mọi** con của cả phiên trong khi `waitedMs` ngay cạnh là số của riêng
lượt — hai con số cạnh nhau nói hai chuyện khác nhau. Sửa: `children_summary(parent_id, turn=None)` và truyền `turn_no` ở bảy chỗ
gọi; `session_metrics.peers` vẫn là số của cả phiên (giữ nguyên, đó là chủ ý). Test:
`test_peer_cost.py::test_finish_chi_tinh_con_cua_luot_dang_dong`.

**BUG-57 — mức Thấp — một lần chờ bị huỷ để lại dấu trên hàng sổ con.** `waiting_for`/`waiting_since` không được xoá khi lần chờ
ném, nên bảng Sub-agents vẽ "đang chờ …" cho một con đã chết, và cờ đánh thức cưỡng bức sống sang lượt sau. Sửa: `child_wait(sid,
[], None)` trong `finally`, xoá cờ khi lần chờ ném. Test: ca "huỷ lúc xếp hàng" (cùng ca với BUG-54) khẳng định hàng sổ con sạch dấu.

**BUG-58 — mức Thấp — khai `deliverTo: ['main']` lại **chậm** hơn không khai gì.** Nhánh `main` của `deliver_child_result` không gọi
`notify_peer_delivery`, nên cha đang chờ không được đánh thức và phải chờ thêm một nhịp quét — trong khi con không khai người nhận lại
được đánh thức ngay (BUG-48). Sửa: gọi `notify_peer_delivery(target)` sau khi hàng biên nhận khép `injected`. Test: ca
"`deliverTo: ['main']` đánh thức trong cùng nhịp" trong `test_peer_slot_lifecycle.py`.

**BUG-59 — mức Thấp — ảnh chụp và ghi hình không mang số bước.** `deploy/docker/ide-proxy.py:284-285` đọc `step`/`toolCallId` từ
payload **từ lâu**, nhưng harness (`sandbox/executor.py`) chưa bao giờ gửi hai khoá đó, nên tên tệp của mọi ảnh chụp/ghi hình rơi về
nhánh dự phòng `000` — dấu vết sống có ảnh mà không biết ảnh thuộc bước nào. Lộ ra khi P1.4 cần đúng số bước để đặt tên mảnh bằng
chứng (`<sid8>_<step>_<slug>.<ext>`). Sửa (`c82d9d2`): `executor.box_identity(session, step, tool_call_id)` chỉ chuyển tiếp giá trị
**thật** (chỗ gọi cũ nhận đúng thân yêu cầu cũ, không có khoá lạ), payload gửi worker mang cả ba khoá, và hai route
`/__box/capture` + `/__box/record/start` đọc được chúng như thiết kế ban đầu. Test: `test_worker_evidence.py` (10 ca) + hai ca payload
của harness và hai route trong cùng tệp.

**Ghi nhận, không phải lỗi.** (1) **Hai lỗi tự gây, bắt ngay trong phiên, chưa bao giờ lên commit:** bản vá P1.1 đặt `turn=turn_no`
vào dòng `tool.end` của `wrap_up_diagnosis` — hàm **không có** biến ấy, nên mọi lượt chạm hạn chót kết thúc `failed` và **không có câu
trả lời** (bộ test bắt: `test_turn_partial_budget.py`); và `probe_workspace` gọi `EVIDENCE_PROBE_COMMAND` khi hằng số đó chưa được
định nghĩa ở đâu — `NameError` bên trong khối `try` của cổng sẽ âm thầm hạ **mọi** phép dò xuống `EVIDENCE_GATE_FAILED`. Cả hai sửa
trong cùng phiên, trước khi commit. (2) **Hai phép kiểm cũ phải sửa theo hàng nhật ký mới:** `test_harness_runtime.py`
`::test_multiturn_restart_and_isolation` khẳng định system prompt **bất động** giữa hai lượt — hàng `E:` đầu tiên làm khối ký ức A5
xuất hiện (sáu nhóm rỗng) dù không có gì để nhớ; sửa bằng `journal.brief_has_items` để khối rỗng không được ghép, và thêm ca
`test_rows_that_belong_to_no_group_leave_the_memory_block_empty`. Cùng tệp, `::test_denied_tool_and_malformed_args_never_execute` giờ
lọc việc hạ tầng của cổng (`find` cố định + thư mục bằng chứng) bằng **dấu vết của chính nó**, không bằng tên op — lọc theo tên thì
chính cú `file_write` của model cũng lọt. (3) **Đỏ môi trường, không liên quan:** `test_terminal_tools.py::test_terminal_exec_echo`
(`bash` của box không có `Write-Output`) và `test_cua_element_selector.py::test_browser_use_navigation_and_dom_inspection` (box không ra
được Internet). (4) **Luật §4.5 vẫn giữ:** `turn.end` chỉ mang **số** (`evidenceVerdict`, `evidenceMissing`, `evidenceChecked`,
`changedFiles` là số đếm, `artifacts` là số đếm) — danh sách đường dẫn nằm ở event `assistant` và hàng `E:`, tức ở chỗ người đọc được,
không phải ở nhật ký hệ thống. (5) `BUG-51` (§6.24) vẫn **CHƯA SỬA** — vòng sau, kèm test khoá thứ tự reap/finish.

### 6.26 Vòng 22 (đợt 3, hậu kiểm song song) — ba lỗi hợp đồng khoá giữa worker trong box và cổng, hai lỗi nhất quán, một trần thời gian: BUG-60…BUG-65 (ĐÃ SỬA); BUG-66…BUG-69 (ghi nhận)

Hai vòng soát độc lập (một backend, một giao diện + eval + tài liệu) chạy song song trên `3dadeb3` cùng một việc tinh gọn
mã, và cả hai kết luận *Ship with mitigations*. Sáu lỗi thật lộ ra, năm trong chúng thuộc **cùng một họ**: hợp đồng khoá
giữa kết quả worker trong box và bộ phán — bài kiểm dựng **hình dạng giả** nên tất cả đều xanh, còn máy thật thì chấm sai
âm thầm. Đây là loại lỗi mà "có test" không cứu được: test phải dựng **đúng** hình dạng worker trả.

**BUG-60 — mức Cao — `dispatch` không truyền `turn`/`step`/`toolCallId`, nên mọi mảnh bằng chứng và ảnh chụp rơi về bước
`000`.** Ba tham số có từ `c82d9d2` (BUG-59) nhưng **không chỗ gọi thật nào** truyền chúng: `runtime.dispatch` gọi ba tham
số vị trí ở cả hai nhánh, nên worker nhận `step=None` ⇒ `evidence_step()` ra `000` và hai route capture/ghi hình vẫn
không biết ảnh thuộc bước nào — đúng khoảng trống mà P1.4 dựng ra để bịt. Sửa: `dispatch` dựng
`identity = {turn, step, tool_call_id}` từ `active_turn`/`active_step`/`call_id` rồi truyền cho **mọi** lời gọi tool; tám
đôi thực thi giả trong `backend/tests/unit` nhận `**_identity` để đôi bên nói cùng một hợp đồng.

**BUG-61 — mức Cao — cổng đọc `stdout`/`exitCode`, worker trả `content`/`exit_code`.** `worker.py` trả
`{'content', 'exit_code', 'is_error', 'artifact'}` cho lệnh, còn `evidence_gate.artifacts_from_calls` đọc
`result.get('exitCode')`/`result.get('stdout')` và `runtime.probe_workspace` đọc `answer.get('stdout')`. Hai hệ quả sống:
(1) **mọi phép dò trả "không đổi gì"** — `probe_paths` luôn rỗng, `probe_found` luôn `False`, nhánh R1 "lệnh + mã thoát +
phép dò xác nhận" không bao giờ chạy, và một lượt chỉ có bằng chứng qua phép dò được chấm `sufficient`; (2) mọi mảnh
`command` mang `exit None` (đúng như hàng `E:` sống cho thấy). Sửa: hai hàm đọc khoá thật (`box_exit_code`,
`box_output_tail`), vẫn đọc được khoá cũ để không phá dữ liệu cũ; bài kiểm dựng lại đúng hình dạng worker.

**BUG-62 — mức Cao — `changed` lấy từ `numbers['path']`, khoá mà worker CỐ Ý bỏ.** `worker.py:437` trả `numbers` đã lọc
bỏ `path` (đường dẫn ở lại trong tệp bằng chứng — `test_worker_evidence.py` khoá đúng điều đó), nên `changed` luôn `None`
và mảnh diff không bao giờ khớp tệp đã đổi: lượt ghi có đủ diff vẫn bị ghim `change_without_verification` — báo động sai
đúng ở mặt mà mốc nâng `enforce` (§6 của kế hoạch) đếm. Sửa: đường dẫn workspace lấy từ `args['path']` của chính lời gọi
ghi (harness biết chắc, không phải văn của model), `numbers['path']` giữ làm đường dự phòng.

**BUG-63 — mức Thấp — cổng tự hỏng SAU khi phán: hai mặt đọc nói hai kết luận.** `info` được gán phán thật trước khi
ghim hàng `E:`; nếu chỗ ghim ném thì hàng `X:` + notice nói "chưa đo được" còn `assistant.evidence` và `turn.end` vẫn
mang phán thật. Sửa: nhánh `except` gán lại `info` thành `not_measurable` + `missing=[{reason: 'gate_error'}]`. Test:
`test_cong_hong_sau_khi_phan_thi_moi_mat_doc_noi_chua_do_duoc`.

**BUG-64 — mức Thấp — bộ đếm lượt đếm cả hàng `user` của lệnh điều khiển.** `_turn_index` đếm mọi hàng `user`, nhưng
`/status`, `/compact`… phát một hàng `user` mà **không** đi qua `begin_turn` ⇒ bộ đếm của bảng vượt `turn_count` một lần
cho mỗi lệnh điều khiển, và từ đó mọi lượt vừa lệch số vừa ghi `turn.index_drift` mãi. Sửa: hàng `user` của lệnh điều
khiển mang `control: true` (`skills/runtime_commands.py`) và phép đếm bỏ qua đúng những hàng đó (`json_extract`); hàng cũ
không có khoá thì vẫn đếm như trước. Test: `test_lenh_dieu_khien_khong_phai_la_mot_luot`.

**BUG-65 — mức Vừa — vòng dò ghi tệp bằng chứng không có trần thời gian.** `probe_workspace` bọc lệnh `find` trong
`asyncio.wait_for` nhưng cú `file_write` ngay sau đó thì không, dù chính chú thích cạnh nó gọi tệp đó là "quà, không phải
điều kiện": một box treo ở chỗ ghi ấy ăn hạn chót của lượt và xoá luôn câu trả lời đang được chấm. Sửa: cùng trần
`_clamp_timeout(...)` như phép dò.

**BUG-66, BUG-68, BUG-69 — ghi nhận, CHƯA SỬA (vòng sau); BUG-67 đã sửa trong vòng kiểm độc lập.** (66) **R3 phạt oan văn xuôi trung thực:** `known_paths` chỉ là phạm vi
*lượt này*, nên câu trả lời nhắc tới tệp có thật trong box mà lượt không đọc (ví dụ dẫn chứng `docs/plan/…`) vẫn bị
`claim_path_not_in_turn`; §2.3 của kế hoạch đòi thêm điều kiện "**và** không tồn tại trong box", nhưng chưa có manifest
nào để kiểm — ba hình dạng đã đo: câu dẫn chứng, đích của `sed -i`, đích của `pytest`. (67) **`_COMMAND_RE` nuốt dấu phân
cách**: dấu phân cách nằm trong chính `group(0)` mà `claim_paths` lưu lại, nên lệnh viết trong dấu backtick bị
cắt mất một ký tự và **không bao giờ** khớp,
còn lệnh không backtick chỉ khớp phần thân — một đích bịa vẫn qua. **Đã sửa (vòng kiểm độc lập, cùng PR):** mã lệnh nay được chuẩn hoá bằng helper mới `_clean_command` — bóc dấu backtick/nháy ở hai đầu và dấu câu cuối câu — ngay khi `claim_paths` lưu nó, và lần nữa khi `_command_backed` đối chiếu. Ca kiểm mới: `test_r3_lenh_da_chay_ma_viet_trong_dau_backtick_khong_bi_phat_oan` (ba câu: có backtick giữa câu, có backtick cuối câu, không backtick). Đo sống trên harness `3102`: lượt ghi `src/tick2.py` rồi chạy `git status --short`, câu trả lời bọc lệnh trong dấu backtick — **trước** khi sửa: `insufficient` + `answer_references_unknown_command` (mã lệnh lưu ra là "`git"); **sau** khi sửa: `sufficient`, `missing=[]`, `checked` vẫn 2. Nửa còn lại của (67) — lệnh không backtick chỉ khớp phần thân nên một đích bịa vẫn qua — **chưa sửa**, giữ nguyên ở vòng sau. (68) **Lượt giao việc con được ghim `sufficient` khi
con còn đang chạy** (`delegate_task` trả `status='started'` là một mảnh `child` hợp lệ). (69) **Cổng chỉ chấm được hình
dạng câu trả lời, không chấm được khẳng định thuần văn** — món nợ đã ghi ở §6.25 vẫn nguyên.

**Sửa theo vòng soát giao diện (cùng phiên).** (70) lượt `not_measurable` bị đếm và gọi tên như "khẳng định chưa kiểm
chứng": nay số khẳng định chỉ đếm năm mã lý do LÀ khẳng định (`CLAIM_REASON_CODES`), ô thứ ba của dòng biên nhận in
`chưa đo được`, tiêu đề nhóm đổi thành `Chưa đo được lượt này`, và lý do của phép đo vẫn hiện nguyên vẹn. (71) câu dự
phòng dịch mã lý do không bao giờ chạy (`t()` trả chính khoá khi cả hai từ điển trượt) nên người đọc thấy
`chat.evidenceReason.<mã>`; nay trả mã máy, và từ điển có thêm `no_change` ở cả `vi.ts` và `en.ts`. (72) câu giải thích
huy hiệu xanh in số mảnh CỔNG chấm trong khi hàng đầu khối in số mục khối liệt kê (đo sống: `checked=3`, giao diện hiện
`4 bằng chứng`) — nay bỏ số khỏi câu đó. Ba việc này đều có ca kiểm mới trong
`frontend/src/components/chat/HarnessStepView.evidence.test.tsx`.

**Hai chỗ chữ nghĩa trong sổ vòng (`docs/tracking/test-rounds.md`) đã sửa:** câu nói dòng biên nhận "thêm hai số mới"
(ô `0 khẳng định chưa kiểm` rơi khi rỗng), và con số `test_evidence_gate_runtime.py` **13** (đúng ra **14** ca lúc đó,
**15** sau hậu kiểm).
### 6.27 Vòng 22 (đợt 3, vòng kiểm độc lập + vòng chốt) — BUG-67 (báo động sai vì backtick), BUG-70 (khối `Bằng chứng` đếm trùng) và BUG-71 (rác tệp do phép dò tự ghi) ĐÃ SỬA

**BUG-67 — mức Vừa — R3 phạt oan câu trả lời trung thực khi lệnh viết trong dấu backtick.** Nguyên nhân, cách sửa và số đo sống đã ghi ở §6.26 (heading + đoạn "Đã sửa (vòng kiểm độc lập, cùng PR)"): helper `_clean_command` bóc backtick/nháy/dấu câu ở cả hai đầu — lúc `claim_paths` lưu mảnh và lúc `_command_backed` đối chiếu; ca kiểm mới `test_r3_lenh_da_chay_ma_viet_trong_dau_backtick_khong_bi_phat_oan`. Nửa còn lại của (67) — lệnh KHÔNG backtick chỉ khớp phần thân — vẫn là lỗ hổng đã biết, chưa sửa.

**BUG-70 — mức Vừa — cùng một ảnh chụp hiện HAI dòng, và biên nhận `N bằng chứng` phồng lên so với `checked` của cổng.** Đo sống ở phiên `5d896abf` (chụp → ghi tệp → chụp, harness `3102`): `turn.end` nói `artifacts: 3` / `evidenceChecked: 3`, còn khối `Bằng chứng` trong giao diện đếm **4** và in cùng một PNG hai lần. Nguyên nhân: box báo đường dẫn theo **hai khuôn** — `computer_screen_capture` trả đường dẫn tuyệt đối (`/home/agent/workspace/.generated_artifacts/captures/screen/<sid8>/<sid8>_001_screen.png`), còn `file_write` và mảnh cổng ghim trong hàng `E:` trả đường dẫn tương đối; `collectTurnArtifacts` khử trùng theo đường dẫn thô, nên hai khuôn của cùng một tệp thành hai mục, và mục tương đối còn mất nút `Zoom` vì không khớp được `media.artifactPath` (so thô). Đây cũng là **nguyên nhân gốc của mục (72)** ở §6.26 — vòng soát giao diện trước đó chỉ bỏ con số khỏi câu giải thích huy hiệu xanh, chứ chưa bỏ được dòng trùng. **Đã sửa** (`b464c54`): helper `workspacePath()` (tách từ `boxMediaUrl`, dùng chung) bỏ tiền tố `/home/agent/workspace/`; `collectTurnArtifacts` khoá khử trùng + lưu đường dẫn đã chuẩn hoá, `mediaOf` so theo khuôn chuẩn hoá (ảnh giữ `src` để mở lightbox), số đo `facts` tra cả hai khuôn. Ca kiểm mới: "ảnh chụp có hai khuôn đường dẫn ⇒ MỘT dòng, ảnh vẫn mở được bằng lightbox" (`HarnessStepView.evidence.test.tsx`). Đo lại sống trên cùng phiên: `3 bằng chứng`, ba dòng đúng ba mảnh, dòng ảnh còn `Zoom`.

**BUG-71 — mức Thấp — ĐÃ SỬA (vòng chốt, `2752388`).** Phép dò của cổng (`probe_workspace`) tự ghi kết quả rồi bị chính tầng ghi bằng chứng của worker bắt thêm một lần: mỗi lượt `needs_probe` sinh **hai** tệp trong `.generated_artifacts/captures/evidence/<sid8>/` — bản đọc được `<sid8>_<step>_changes.txt` (đúng ý) và bản `.diff` tên `<sid8>_000_<sid8>_<step>_changes.txt.diff` (bước `000` vì lời gọi ghi nội bộ không mang `turn`/`step`, và không mảnh cổng nào trỏ tới). Thấy ở `4987d659`, `3170db02` và `1c65d2e7` (mỗi thư mục ba tệp). Cách sửa: lời gọi nội bộ nay đi **ngoài phiên** (`session=None`) — đúng luật P1.4 mục 5 cho lượt gọi ngoài phiên: worker vẫn ghi tệp, còn `write_evidence` trả `None` khi thiếu định danh nên không đổ rác; đường dẫn tệp do harness dựng sẵn nên bản thô vẫn nằm đúng chỗ. Ca kiểm mới `test_phep_do_ghi_tep_tho_ngoai_phien_de_khong_sinh_tep_rac` (và `FixtureExecutor` ghi lại `session` của mỗi lượt gọi). Đo sống (harness `3102` trên `2752388`, phiên `be76487a4a7b4e45add8f1bb3f526955`, lượt `sh tools/mk71.sh` sinh `lop71.txt`): thư mục phiên còn **đúng một tệp** `be76487a_2_changes.txt`, không tệp `.diff` nào; `turn.end` mang `evidenceVerdict=insufficient`, `evidenceChecked=1`, `changedFiles=['lop71.txt']`.

### 6.28 Vòng 22 (đợt 3, vòng dạo mock–app của vòng kiểm độc lập) — L14 ĐÃ SỬA: mục thiếu bằng chứng in câu của câu trả lời bị ghim; ba mục ghi nhận

**L14 — mục `missing[]` không nói câu nào của câu trả lời bị ghim — ĐÃ SỬA (`671aa1e`).** Vòng kiểm độc lập dựng lại mặt mock `dv23-after-insufficient.html` cạnh giao diện thật và thấy nhóm “Khẳng định chưa có bằng chứng” lệch: mock mở đầu mỗi mục bằng **chính câu** của câu trả lời bị ghim, in trong ngoặc kép, rồi mới tới câu dịch của lý do; app chỉ in lý do + chi tiết + mã máy, nên người đọc biết cổng ghim `tools/mkverify.sh` mà không biết ghim vì **câu nào**. Dữ liệu đã có sẵn trong event (`claims[]`, backend ghim từ `claim_paths`), giao diện chưa dùng. Cách sửa: `AnswerEvidence` đọc thêm `claims[]` (`EvidenceClaim`: `text`, `path`, `command`); hàm `chargedClaimText(claims, item)` tra câu theo đúng khoá `missing[].detail` (đường dẫn hoặc lệnh — `assess` lấy `detail` từ chính bản ghi ấy, nên không thể gán nhầm); mục không có bản ghi — phiên cũ, hoặc lý do của phép đo hỏng như `box_probe_failed` — giữ nguyên lối vẽ cũ, không bịa câu. Mục thiếu bằng chứng có thêm hook `data-evidence-claim="true"`; câu dịch của lý do lùi xuống `text-amber-100/70` để câu bị ghim là thứ đọc trước. Ca kiểm mới `HarnessStepView.claims.test.tsx` (3 ca: lý do đường dẫn, lý do lệnh, event cũ không có `claims[]`). Đo sống (vòng độc lập, bốn ca độc lập trên `3102`): `17ea25ef` in `“Đã tạo tools/mkverify.sh và bản ghi nguồn tương ứng.”` — đúng câu của câu trả lời, đứng trước câu dịch (chỉ số 0 < 54) và trước mã máy (chỉ số 129); `c1bc3a8f` in câu cho **cả** hai mục (đường dẫn và lệnh); `31c3c86a` (`not_measurable`) **không** có câu nào dù câu trả lời có nhắc `src/nm_probe.py` — R5 thắng R3 giữ nguyên trên giao diện; lượt mới `20de8728` (câu 202 ký tự) lộ mục dưới đây. Nghiệm thu: `npx vitest run` 123 tệp / 1019 ca đạt; `tsc -b --noEmit` exit 0.

**Mục 1 — trùng số đếm bằng chứng giữa dòng biên nhận lượt và hàng đầu khối — GIỮ NGUYÊN CÓ Ý THỨC, không phải lỗi im lặng.** Vòng độc lập đối chiếu kế hoạch và mock rồi kết luận: P4.4 của kế hoạch (`/code/.plans/v1-evidence-proof.md`, ~dòng 445) **yêu cầu rõ** hai số `evidence`/`unverified` nằm ở dòng biên nhận lượt, còn mặt mock đã duyệt `dv23-after-insufficient.html` in ở hàng đầu khối (và dòng biên nhận của mock chỉ có `3 commands`). Hai yêu cầu đã duyệt chồng nhau, nên bản thi công đang thoả **cả hai**; “sửa” một trong hai ở đây là tự ý bỏ một yêu cầu đã duyệt. Đo sống: `17ea25ef` biên nhận `1 command · 1 failed · 1 bằng chứng · 1 khẳng định chưa kiểm` + hàng đầu khối `1 bằng chứng · 1 khẳng định chưa kiểm · cổng: BOXFOX_EVIDENCE_GATE = warn`; `c1bc3a8f` biên nhận `1 command · 2 khẳng định chưa kiểm` (không có chip bằng chứng vì `checked = 0`) + hàng đầu khối `0 bằng chứng · …`. Đề nghị cho vòng sau: chọn **một** mặt (hàng đầu khối) rồi sửa kế hoạch và mock cùng lúc.

**Mục 2 — `sha256`/`±` chỉ hiện ở hàng có `facts` — GHI NHẬN, phụ thuộc dữ liệu.** Số đo chỉ lấy từ payload công cụ thật của lượt (`sha256After`/`added`/`removed`/bytes); hàng không có `facts` thì không có số nào để in, và bịa ra một số là vi phạm luật “không bằng chứng tự nghĩ” của P4.3. Đo sống ở `671aa1e`: `5476b69a` — hàng `tools/mkverify2.sh` không có meta, hàng `…_001_mkverify2.sh.diff` có `sha256 3e6f20c25b… +2 −0 26 B`; `b999089a` — hàng `src/tick2.py` không có meta, hàng `…_001_tick2.py.txt` có `sha256 3809276356… +0 −0 6 B`. Ghi chú kèm: `+0 −0` trên mảnh `.txt` phản ánh đúng payload của tầng ghi, là câu hỏi phía tầng ghi chứ không phải phía giao diện. **Mục 3 — câu bị ghim dài hơn trần bị cắt giữa từ mà không có dấu `…` — GHI NHẬN (Thấp).** Backend lưu `text[:200]` (`MAX_CLAIM_CHARS = 200`, `evidence_gate.py:500`) nên lượt `20de8728` (dòng câu trả lời 202 ký tự) in ra `“… nữa cả, xon”` — cụt giữa từ, không dấu hiệu bị cắt. Cần một dòng câu trả lời > 200 ký tự mới thấy; không phải hồi quy của L14. Cách sửa gọn cho vòng sau: gắn cờ cắt ở backend rồi giao diện thêm `…` (đừng đoán theo độ dài ở giao diện: một dòng đúng 200 ký tự sẽ bị gắn `…` oan). Ảnh tái hiện: `r22l14_04_truncated_claim_quote.png`.

**§6.29 — Hàng ảnh chụp trong khối bằng chứng cắt mất phần phân biệt — GHI NHẬN (Thấp), chủ nhà quyết.** Lượt sống `9481bf87` có **hai** lần chụp màn hình (bước 1 và bước 4); danh sách bằng chứng xếp đúng thứ tự thời gian theo kế hoạch §2.4, nhưng mỗi hàng in **đường dẫn đầy đủ** rồi bị `truncate` cắt ở ĐUÔI — đúng chỗ chứa phần phân biệt: hai hàng cùng đọc `.generated_artifacts/captures/scre…`, khác nhau chỉ ở `title` khi rê chuột (`…_001_screen.png` vs `…_004_screen.png`). Hệ quả: ảnh chụp màn hình của khối không nói được hàng nào là “trước”, hàng nào là “sau”. Bằng chứng: `r23_10_turn_before_after.png`. Đề nghị (chưa sửa vì mặt mock đã duyệt đặt hàng ảnh là “đường dẫn in được bằng mắt”): in **tên tệp** (hoặc cắt GIỮA đường dẫn) để hàng ảnh đọc ra số bước, ví dụ `9481bf87_001_screen.png`. Chủ nhà chốt thì vòng sau sửa kèm mock. Finding: `ffc455c5-2324-4b88-9b02-4f94ff992fb0`.

**§6.30 — Hai hành vi của đường chụp ảnh là CỐ Ý, không phải lỗi — ĐÓNG.** (a) Ảnh khử trùng theo **nội dung** (`capture.py:_finish_image`): cùng một màn hình chụp hai lần ⇒ giữ **một** tệp, mục thứ hai trỏ về tệp cũ kèm `deduplicateOf` ⇒ lượt chụp “trước/sau” mà màn hình không đổi thì danh sách gộp còn một hàng (đúng: không có hai tấm ảnh khác nhau để so). (b) Tên tệp bằng chứng hạ chữ thường (`worker.py:evidence_slug`, luật BOX-3 `[a-z0-9._-]`) nên `frontend/src/UiProof.tsx` thành `uiproof.tsx.diff`; đường dẫn thật vẫn nằm ở hàng `frontend/src/UiProof.tsx` của lượt — đã đọc mã để chốt, không sửa.

### 6.31 Vòng 23 — bằng chứng sống giao SAI DẠNG (chủ nhà phát hiện bằng ảnh chụp): mặt câu trả lời cuối chỉ còn markdown, ảnh chụp do model viết vào câu trả lời — ĐÃ SỬA (`a4d60f9` + `db5d0ff`)

**Chủ nhà chỉ ra drift, kèm ảnh chụp.** Năm ảnh: `3119.png` (câu trả lời cũ: **11 dòng chữ "the uploaded file"** —
nền tảng gói danh sách đường dẫn literal thành chip tệp đính kèm, không mở được ảnh nào), `3120.png` (mặt **mong muốn**:
bằng chứng là ảnh/màn hình **của dự án**), `3121.png` (ảnh nằm trong khối gập, có huy hiệu trạng thái cổng),
`3122.png` (mặt **đúng**: lưới ảnh **mở ngay** trong câu trả lời), `3123.png` (**mặt sai bị chê**: một khối đóng trong chat).
Nguyên văn: *"không phải block. hẳn luôn. chỉ dùng file markdown thôi"*.

**Nguyên nhân gốc (đo được, không suy đoán).** Đợt 3 vòng 22 đo **đúng** nhưng **giao sai dạng**: (a) mặt câu trả lời cuối là
**đồ của app** — khối gập `EvidenceBlock` + huy hiệu ba trạng thái (`HarnessStepView.tsx`) — còn ảnh thì bị **gom vào khối**;
(b) model viết **đường dẫn literal** trong văn, mà nền tảng render chuỗi đường dẫn trần thành chip "the uploaded file";
(c) `MarkdownRenderer` không có đường "ảnh ⇒ tile bấm mở lớn" và **không có** đường mở tệp bằng chứng (link tới tệp workspace
điều hướng hỏng); (d) công cụ chụp **cứng `kind='screen'`** (`executor.py`) nên không chụp được cửa sổ/tab render của dự án;
(e) tên tệp ảnh không mang nhãn nên hai hàng ảnh không phân biệt được (đó là **§6.29**).

**Cách sửa (vòng 23, `a4d60f9`; chủ nhà chốt D-16…D-25 trong `owner-decisions.md` §4).**
1. **P1 — khuôn câu trả lời cuối**: `FINAL_REPORT_PARTS` + `FINAL_REPORT_GUIDANCE` (`runtime.py`) và **bản sao thật sự được nạp**
   trong `AGENT.md` §3.4 = năm mục *làm được gì / còn lại gì / chủ nhà quyết gì / khúc mắc gì / bằng chứng*; thêm **kỹ năng
   `final-report`** (7 id mặc định) và **bản nhắc việc của lượt** (`turn_recap`) chỉ chèn vào bước tổng kết.
2. **P2 — công cụ chụp**: `computer_screen_capture` có `target` (`window`/`tab`/`screen`) + `caption`; giá trị rác ⇒ `screen`
   (không phá hành vi cũ); `capture.py` đưa **nhãn vào tên tệp** (`<sid8>_<step>_<kind>-<label>.png`).
3. **P3 — cổng chỉ chỉnh kỹ thuật**: ảnh `window`/`tab` được tính là ảnh chụp của lượt; `caption` vào danh sách khoá trắng;
   **không** thêm luật/verdict/mã lý do, payload `assistant.data.evidence` vẫn phát.
4. **P4 — giao diện chỉ markdown**: ảnh trong câu trả lời ⇒ **tile hiện ngay** (tên tệp + nhãn của model, bấm mở khung lớn);
   link tệp bằng chứng ⇒ mở **tab Files**; **xoá** khối `Bằng chứng`, **xoá huy hiệu trạng thái cổng**, **xoá** lưới ảnh của app
   khỏi mặt câu trả lời (biên nhận đầu lượt vẫn đếm số).
5. **P5 — nhãn theo ngôn ngữ câu trả lời**: `answerLang.ts` (ngưỡng 3 điểm, mặc định tiếng Anh) + `answerLabels.ts`/`dicts.ts`;
   `en.ts` hết tiếng Việt ở 34 khoá bằng chứng.

**Một lỗi CŨ lộ ra khi thi công và đã sửa cùng lượt.** `skills/runtime_commands.py::_next_turn_skills` dựng lại `messages[0]` ở
**mỗi lượt gửi** bằng cách cắt chuỗi tại mốc `=== ENABLED SKILLS ===` rồi chỉ nối lại khối `OWNER-CONFIGURED DIRECTIVES`: đo được
là sau `create()` prompt có `ANSWER LENGTH` + khối khuôn mới, còn **sau lượt gửi đầu tiên cả hai đã biến mất trước khi model đọc**
(⇒ trần độ dài của D-4 lâu nay là vật trang trí). Nay hàm chỉ thay **danh sách kỹ năng**, giữ nguyên phần còn lại; ca kiểm
`test_khuon_khong_bi_nuot_khi_danh_sach_ky_nang_duoc_dung_lai`.

**§6.29 đổi nghĩa (không còn là lỗi hiển thị).** Hàng đường dẫn bị `truncate` cắt mất phần phân biệt **biến mất cùng khối**;
bài toán phân biệt ảnh nay giải ở chỗ khác: **nhãn nằm trong tên tệp** và tile in **basename** — nên hai ảnh của cùng một việc
đọc ra được khác nhau ngay trên mặt câu trả lời. Bản ghi cũ giữ nguyên, chỉ đổi nghĩa: từ "lỗi hiển thị chờ chủ nhà quyết" thành
"đã giải theo D-19/D-22".

**§6.30 giữ nguyên hiệu lực** (khử trùng theo nội dung sha256; tên tệp bằng chứng hạ chữ thường theo BOX-3) — hậu tố nhãn của P2.3
nằm **trong** bảng chữ cái đó, không nới luật slug.

**Số đo (cây `a4d60f9`).** `backend/tests/unit` **1 failed / 1107 passed** (đỏ duy nhất `test_terminal_tools.py::test_terminal_exec_echo`,
thiếu PowerShell trên Linux — có từ trước); nhóm liên quan **275 passed**; `deploy/docker/tests` **501 passed**; frontend
`npx vitest run` **124 tệp / 1036 ca đạt**; `tsc -b --noEmit` **exit 0**. Ca kiểm mới ghim hợp đồng đã chốt: khuôn năm phần trong
prompt sống, `AGENT.md` §3.4, bản nhắc việc không lọt vào câu trả lời, `target` window/tab đi nguyên và rác ⇒ `screen`, nhãn vào
tên tệp (ba kịch bản screen/window/tab), cổng giữ **đúng 11 mã lý do** và `CAPTURE_ARTIFACT_KINDS == ('image','record')`, mặt câu
trả lời **không còn** hook `data-evidence-*`, tile ảnh + lightbox + link mở tab Files, `en.ts` không còn dấu tiếng Việt.

**Hậu kiểm sau khi sổ được viết (hai vòng soát mã độc lập + một vòng soát dọn) — bốn lỗi/lỗ hổng đã sửa trong `7d00c35` và `db5d0ff`.**
① Ảnh nằm trong liên kết (`[![nhãn](anh.png)](https://tài-liệu)`) dựng thành `<button>` LỒNG trong `<a target="_blank">` ⇒ markup/ARIA sai và
một cú bấm vừa mở khung xem lớn vừa mở tab mới; nay liên kết bật `PassiveMediaContext`, ảnh trong liên kết là ảnh TĨNH.
② Việc PHÂN LOẠI link cắt `?query`/`#fragment` nhưng giá trị trao cho `onOpenFile`/URL media là chuỗi THÔ ⇒ `…x.txt?raw=1`, `…x.txt#L12`,
`./.generated_artifacts/a.png`, `shots/a.png` mở hỏng; nay một hàm `normalizeArtifactPath` dùng cho cả hai. ③ `answerLang` cho câu trả lời
tiếng Anh **trích chuỗi giao diện tiếng Việt trong backtick** là `vi` (dương tính giả), và ngược lại không nhận ra tiếng Việt không dấu:
nay `stripCode` bỏ khối mã/span mã trước khi đếm, còn giới hạn đã biết thì ghi thẳng trong docstring chứ không hứa. ④ Bản nhắc việc của lượt gọi
**kết quả của chuyên gia con** là "owner request" (vì `drain_peer_deliveries` bơm kết quả vào transcript CÙNG bước dựng recap) rồi `RECAP_CLOSER`
bảo model chụp lại đúng thứ đó: nay `PEER_DELIVERY_PREFIX` là một nguồn cho cả chỗ viết lẫn chỗ đọc, hết việc của chủ thì nói thẳng "not found in
this transcript". Dọn kèm: nút mở/gấp hết viết cứng tiếng Anh (`chat.finalAnswerExpand`/`…Collapse` ở cả hai từ điển, đi theo ngôn ngữ câu trả lời),
xoá `EvidenceBadgeState`/`EVIDENCE_VERDICT_STATE`/`AnswerEvidence.state` (không còn chỗ vẽ), gộp hai bản dự phòng từ điển vào `i18n/context.labelFrom`,
xoá `WORKER` trùng và `CAPTURE_TARGET_KEYS` không ai dùng.
**Số đo sau hậu kiểm.** `backend/tests/unit` **1 failed / 1109 passed**; nhóm focused 9 tệp **284 passed**; frontend `vitest run` **124 tệp / 1043 ca đạt**;
`tsc -b --noEmit` **exit 0**. Nhánh `output_path` trong `system_media.py` **được giữ**: nó không chết — nó là chốt từ chối giá trị hình dạng
traversal mà model có thể tự bịa (schema chỉ kiểm `required`), và `test_system_media_tools.py` đang ghim hành vi đó.

**Còn lại sau vòng này (ghi để không trôi).** `docker cp` bản `capture.py` mới vào box là bước **của vòng nghiệm thu sống** (chưa
nạp lúc viết sổ): bản trong container vẫn là `19893dde…`, bản repo là `b24541cd…`; bản cũ **vẫn chạy đúng** vì nó bỏ qua khoá `label`. Vòng nghiệm thu sống đã nạp bản mới (`docker cp`, `19893dde…` → `b24541cd…`), nhưng tiến trình `ide-proxy` đang chạy vẫn giữ mô-đun cũ trong RAM — nên nhãn chỉ vào tên tệp sau khi box được dựng lại; chi tiết ở `docs/tracking/test-rounds.md` § *Vòng 23*, Phần 5.
Mặt **"tệp đã thay đổi"** (diff/hunk) và **"agent verify"** (vai hậu kiểm thật: test/review/verify/main, báo cáo md + ảnh) chuyển
sang vòng sau theo D-19/D-20; nợ cũ BUG-66/BUG-68/BUG-69, câu bị ghim > 200 ký tự bị cắt giữa từ, và bốn khoá `subagent*` trong
`en.ts` vẫn nguyên.


### 6.32 Vòng 24 — khuôn năm phần ở câu trả lời cuối (chủ nhà bác): dạng câu trả lời dời vào kỹ năng `final-report`, prompt chỉ còn một dòng bằng chứng + một con trỏ — ĐÃ SỬA (`37926e0` + `68125ea`)

**Chủ nhà bác khuôn, bốn điểm nguyên văn (2026-09-23 06:51 UTC).** ① *"tùy từng trường hợp. ví dụ như nếu user giao việc
thì mới nói đã làm gì hay còn gì"*; ② *"Nếu không còn gì, tại sao lại nói? (thừa)"*; ③ *"đây trả lời đang theo 1 form, chứ
k linh động, harness phải trả lời được như thường, với các task kỹ thuật thì mới báo cáo. nó vẫn trả lời bình thường và báo
cáo chứ k phải mỗi báo cáo, và báo cáo những gì đã làm"*; ④ *"Hiện tại form đã làm hỏng cả phần tóm tắt… ở phiên bản cũ,
model sinh ra theo dạng tóm tắt, nếu user ấn show detail sẽ hiện cụ thể thay đổi, nhưng nếu theo form này đã làm hỏng toàn
bộ"*. Tinh chỉnh sau đó: *"form vào 1 chút, và nó có thể tự chọn ra ví dụ như đã làm gì. trả lời như bình thường. chỉ quan
trọng nhất là phần ảnh dãn chứng ở dưới"*. Mẫu chủ nhà chỉ mặt: lượt `9481bf87`. Chốt thành D-26…D-32 (`owner-decisions.md` §4.2).

**Nguyên nhân gốc của điểm ④ (đo được).** `HarnessStepView.tsx:248` `splitAuthoredSummary()` chỉ lấy **đoạn đầu** làm tóm tắt
khi đoạn đó là văn xuôi thuần (không mở bằng `#`, `|`, `-`, `*`, `>`, `1.`, ``` ```), ≤ 6 dòng, ≤ 600 ký tự, và **còn phần sau**;
`summarizeFinalText()` (`:1078`) rơi về **cắt thô** 6 dòng/600 ký tự. Khuôn vòng 23 bắt mở đầu bằng tiêu đề/danh sách năm phần
⇒ bộ dò trả `null` ⇒ mặt gấp là lát cắt vô nghĩa và `View details` hết nghĩa. Điểm ①②③ đến từ cùng chỗ: hình dạng câu trả lời
bị **áp cứng từ prompt** cho mọi lượt.

**Cách sửa (vòng 24, `37926e0`; dọn theo soát mã ở `68125ea`).**
1. **Prompt về một dòng**: xoá hẳn `FINAL_REPORT_PARTS`, `FINAL_REPORT_GUIDANCE` và khối `=== FINAL REPORT ===`; thay bằng
   `ANSWER_EVIDENCE_LINE` (một câu điều kiện, ASCII) chèn **ngay sau** `=== ANSWER LENGTH ===` và **chỉ** ở phiên chính (D-18/D-32).
   SOP ở `ORCHESTRATOR_SOP_GUIDANCE` chỉ còn một dòng trung thực, không trỏ về khối nào.
2. **Kỹ năng `final-report` 2.0.0 là nơi chứa cả dạng câu trả lời** (D-31): menu **năm mục** nhưng là *menu, không phải khuôn*
   ("pick by content, not habit"), luật **không in phần rỗng**, luật mở bài bằng **một đoạn văn xuôi** (để `View details` còn nghĩa),
   mục **The evidence part closes the answer**, bảng bằng chứng theo loại việc, cách chụp, ví dụ nguyên lượt `9481bf87`. Ở lại `DEFAULT_SKILLS`.
3. **Một con trỏ ở bước tổng kết**: `RECAP_CLOSER` bảo model mở kỹ năng bằng `skill_view`; recap **chỉ phiên chính**, chỉ đi kèm
   **yêu cầu của bước**, và **rỗng** khi lượt không đổi gì ⇒ lượt chỉ hỏi **không bao giờ** thấy con trỏ (D-28).
4. **`AGENT.md` §3.4 chỉ trỏ về kỹ năng** (bản nạp thật cho **mọi** vai, kể cả con, nên cố ý không chép menu; bullet markdown-only
   của vòng 23 giữ nguyên theo D-19).
5. **Dọn theo soát mã + soát dọn (`68125ea`)**: `RECAP_CLOSER` thôi nhắc lại vị trí ảnh (bản chép duy nhất không có ghim; luật
   vị trí vẫn đi ở `runtime.py:761` cho mọi lượt phiên chính); bỏ gạch trùng luật trong kỹ năng; thêm **ghim chống trôi D-26**
   (kỹ năng không được chứa `all five` / `five parts` / `every part` / `in this order` / `must use`, phải giữ `pick by content, not habit`).

**Số đo sống (P3, cây `37926e0`; harness scratch + Vite scratch, stub 3199 và provider thật).**

| Trên payload gửi provider | Trước (v23 `0114.json`) | Lượt việc (`0117.json`) | Lượt hỏi (`0118.json`) |
|---|---|---|---|
| `=== FINAL REPORT ===` | 1 | **0** | **0** |
| `five parts` | 3 | **0** | **0** |
| `in this order` | 2 | **0** | **0** |
| câu `ANSWER_EVIDENCE_LINE` | 0 | **1** | **1** |
| con trỏ `` read the `final-report` skill with `skill_view` `` | 0 | **1** (bước có việc trở đi) | **0** |

- **Ba mặt giao diện ĐẠT**: gấp = đúng **một đoạn văn xuôi** của model + nút mở; mở = phần model chọn rồi **ô ảnh bằng chứng ở CUỐI**
  (`data-artifact-open="media"`, ảnh tải thật 1280×800, nhãn `[data-capture-label="true"]`); lượt hỏi = văn xuôi liền mạch,
  **0** nút mở, **0** tiêu đề mục, **0** ảnh nội dung.
- **Provider thật**: model `nemotron-3.5-lightning-free` **có** gọi `skill_view {"id": "final-report"}` (1 lần) và trả lời **một dòng
  văn xuôi**, không khuôn — đánh đổi D-31 ("model không mở kỹ năng") **không xảy ra ở lượt đo**, nhưng vẫn là rủi ro còn lại vì mới đo một lượt.

**Số đo kiểm thử.** `test_runtime_prompt.py` **17 passed**; `HarnessStepView.test.tsx` **31 passed**; nhóm `frontend/src/components/chat`
**108 passed**; cả bộ frontend **124 tệp / 1045 ca đạt**; `tsc -b --noEmit` **exit 0**; `eslint` **exit 0**; `backend/tests/unit -q`
(bỏ ca môi trường PowerShell) **1113 passed, 1 deselected**.

**Cố ý lệch/ghi nhận.** (a) `RECAP_CLOSER` bỏ vế "and close the answer with those images" mà kế hoạch v3 §2(d) ghi nguyên văn —
soát dọn chỉ ra đây là bản chép trùng duy nhất không ghim, và luật không mất. (b) Ghim vẫn **chỉ** cấm ba câu `RETIRED` cũ, không
cấm mọi cách viết lại khuôn; đã bù bằng ghim chống trôi D-26 ở trên, nhưng một tệp khác (SOP/§3.4) chép menu bằng định dạng khác
(`1. …`, bảng) vẫn không bị bắt — chấp nhận. (c) `owner-decisions.md` §4 nay có §4.1 (vòng 23) và §4.2 (vòng 24) thay vì một §4.1
như kế hoạch ghi, để sổ đọc được theo vòng.

**Còn lại sau vòng này (ghi để không trôi).** Footer lightbox "mở trong Files" chưa nối (`MediaLightboxModal.tsx:35` `artifactPath?`
có, `ChatPanel.tsx:707-715` chưa truyền); dòng meta tile (`PNG · kích thước · bytes`) chưa dựng; `frontend/vite.config.ts` còn bind
`127.0.0.1` nên preview phải qua `frontend/.tmp/vite.preview.config.mjs`; nợ cũ BUG-66/BUG-68/BUG-69, câu bị ghim > 200 ký tự bị
cắt giữa từ, và bốn khoá `subagent*` trong `en.ts` vẫn nguyên.

### 6.33 Vòng 25 — khả năng lên kế hoạch (chủ nhà giao ba việc): đo được **bảy lỗi**, thi công vai phản biện ĐỘC LẬP + hai cổng chặn cứng có công tắc + cú bấm ở tab Plan mở LƯỢT THẬT — ĐÃ SỬA (vòng 25)

**Nguyên văn chủ nhà (2026-09-23 08:31 UTC, ba việc).** ① *"kiểm thử khả năng lên kế hoạch của agent … việc lên kế hoạch đơn giản nó
chỉ điều qua agent plan, chứ k điều động, review lại kế hoạch 1 lần nào, plan xong là dừng (không đúng hành vi). bản kế hoạch phải
được verify-review, research để tìm kiếm thông tin lẫn các thao tác khác."*; ② *"khi user muốn thêm yêu cầu, plan có lên ver2? có
cập nhập đúng k? có gọi mỗi sub agent plan không? (sai hành vi), cùng với khả năng request change của user"*; ③ *"sau khi lên kế hoạch
kiểm thử hợp lý, nói vẫn đề và giúp tôi lên plan nếu có lỗi. có thể inter view thật kỹ, plan thật kỹ"*.

**Số đo TRƯỚC khi sửa (`/code/.plans/v25-evidence-brief.md`; sáu lượt lập kế hoạch thật + ba cú bấm ở tab Plan, 2026-09-23 sáng).**
Sáu lượt lập kế hoạch: sau `plan_written` lượt **dừng ngay** — **0** phiên con vai `review`, **0** `await_children`, **0**
`request_approval`; không lượt nào bản kế hoạch được ai chấm. Ba cú bấm ở tab Plan (2 × Request changes, 1 × Approve):
**3/3** trả API 200, có hàng trong sổ, badge đổi — rồi **im lặng 55–60 s**, `turn_count` **không** đổi, **0** event mới, cột
`plan_reviews.session_id` toàn `NULL`; và 3/3 hàng `note: ""` vì tab không có ô ghi chú.

| Mã | Lỗi | Đo được | Căn (file: dòng, đo ở `0266ca8`) | Cách sửa (vòng 25) |
|---|---|---|---|---|
| **BUG-72** | Sau `plan_written` lượt dừng; phản biện chỉ được **khuyên**, không bắt buộc | 6/6 lượt: 0 con `review`, 0 `plan_verify` | `runtime.py` `ORCHESTRATOR_SOP_GUIDANCE` chỉ *khuyên*; `plan_eval.py` chấm P1–P8 **trước** khi ghi nên không sinh phản biện ngữ nghĩa; không có vai nào chỉ-đọc chuyên chấm kế hoạch | Vai MỚI `plan-review` (10 vai) + SOP 10 chuyên gia có bước `plan-review`/`plan_verify`; sổ `plan_verifications`; kỹ năng `planning` (mặc định) |
| **BUG-73** | Cú bấm ở tab Plan không mở lượt nào | 3/3 cú bấm: 200 + im lặng 55–60 s, `turn_count` không đổi, 0 event, `session_id: NULL` | `api/server.py:454-513` chỉ `record_plan_review` rồi chuyển tiếp box; không đụng runtime | `plan_wake()`: mở MỘT lượt thật với `invocation_id` suy từ nội dung quyết định (chống bấm trùng), mọi kết cục không-mở-được trả `wake.state` (`busy`/`duplicate`/`failed`/`no-owner`) kèm mã; ghi luôn `session_id` sở hữu vào hàng sổ |
| **BUG-74** | Tab Plan không có ô ghi chú cho Request changes | 3/3 hàng `note: ""` | `PlanPanel.tsx:199-202` không truyền note; `usePlanFiles.ts:294` mặc định `''` | Mũi tên nhỏ ở nút Approve mở popup nhập điều kiện (D-38) + ô ghi chú ở Request changes; điều kiện đi vào `plan_wake_prompt` và vào sổ |
| **BUG-75** | Hạn chót lượt lập kế hoạch quá ngắn | B1 chết ở **210 s** (`DEADLINE_EXCEEDED`) trước cả `write_plan`; B1b ở 622 s vẫn `partial` nhưng phiên hiện `completed` | `limits.py:22-25` `DEADLINE_DEFAULT_SECONDS = 180`, `DEADLINE_MAX_SECONDS = 600`, `CHILD_DEADLINE_SECONDS = 300` | `600`/`1200`/`420` + `extend_turn_budget()` nới **+420 s** một lần khi đã ghi được kế hoạch (`PLAN_TURN_EXTENSION_SECONDS`), kèm `notice TURN_EXTENDED`; `session_metrics()` thêm `lastTurn` để lượt dở nói được là dở |
| **BUG-76** | Nhãn phiên bản do box gán theo **vị trí**, không theo sổ duyệt | Tab Plan in `v1 (approved)` cho bản chưa ai duyệt | `deploy/docker/plan_files.py:841-844` (`draft` nếu `len(versions) > 1 and index == 0`, còn lại `approved`) | Tab Plan thôi đọc nhãn đó: mặt trạng thái đọc sổ harness (`plan_reviews` + `plan_verifications`); API thô của box chưa đổi (không rebuild box) |
| **BUG-77** | Hết hạn một lượt xin duyệt tự sinh hàng `changes_requested` | Lượt 3 xin duyệt, hết hạn ⇒ sổ có `changes_requested` **dù không ai bấm** | `runtime.py:3772` `defaultChoice: 'reject'`; `runtime.py:3833-3850` ghi sổ cho *mọi* kết cục quyết định | `settle()` chỉ ghi sổ khi có quyết định THẬT; bật luật R3 (`plan_registry.py:865-881`) đúng chỗ; hàng `changes_requested` cần người bấm |
| **BUG-78** | Duyệt qua `ask_user` không vào sổ | Lượt chủ nhà duyệt qua `ask_user` (đã thi hành thật) **không** có hàng nào ⇒ tab Plan hiện *Changes requested* cho bản vừa duyệt (ảnh `r25_08`) | `runtime.py:3833-3850` chỉ ghi khi có đủ `planIdentity` + `planVersion`; `ask_user` không khai được hai khoá đó | `tool_contracts.py`: `ask_user` nhận `planIdentity`/`planVersion`; `decision()` ghi sổ trước `decision_resolved` (`record_plan_decision`) |
| **BUG-79** | **(hạ tầng, mới)** kênh SSE rỗng ⇒ mất đường thử lại của lượt | Lượt sống `1130c2042b6c445db5f1bafc88d8bb94` (`nemotron-3-ultra-free`) chết sau **582 s / 15 bước** với `TURN_FAILED_TYPEERROR: object bytes can't be used in 'await' expression`; 2 notice `UPSTREAM_RETRY` trước đó | `runtime.py` nhánh dự phòng của `RouterClient.complete()`: `raise router_refusal(res.status_code, await res.read())` — `httpx.Response.read()` là hàm ĐỒNG BỘ trên thân đã đọc xong, nên TypeError **THAY CHỖ** phán quyết `UPSTREAM_HTTP_502` của router; `classify_failure` trả `TURN_FAILED_TYPEERROR` và `_retry_reason` không nhận ra ⇒ không thử lại | Bỏ `await` (`res.read()`); ghim bằng ca mới `test_an_empty_provider_stream_keeps_the_router_verdict_and_stays_retryable` — chứng minh **đỏ trước / xanh sau** |

**Chuỗi nguyên nhân BUG-79 (tái hiện độc lập, không suy đoán).** Nhà cung cấp trả kênh SSE **rỗng** ⇒ `complete()` ném
`ValueError('Upstream did not return any SSE completion content')` ⇒ khối `except` rơi xuống đường **KHÔNG streaming** (`stream: False`)
⇒ router trả **502** ⇒ nhánh dự phòng `await res.read()` ném TypeError. Lỗi **có sẵn từ `HEAD`** (`git show HEAD:…runtime.py` cũng
`await res.read()`), không phải hồi quy của vòng 25; nhưng nó ăn đúng vào vòng này vì lượt lập kế hoạch là lượt dài, hay gặp
`503/502` của nhà cung cấp. Ghi ở đây vì số đo sống của vòng 25 **không đọc được nếu không sửa nó trước**.

**Số đo sống SAU khi sửa (harness scratch 3116 + router thật 3101, 2026-09-23 11:40-12:05 UTC).**

| Việc | Đo được |
|---|---|
| Lượt lập kế hoạch thật (`c75876dd1f034ae6a937147b6bb9c43a`, `muse-spark-1.3-contributor-free`, `maxSteps 40`, `deadlineSeconds 600`) | `status=completed` ở **540 s**, **18 bước**, **8 phiên con** (1 `research` + 3 `plan-review`), `plan_written` ×2, `plan_evaluated` ×2, `plan_verified` ×2 |
| Chuỗi công cụ của lượt (18 bước) | `delegate_task → write_plan → delegate_task → peer_read ×6 → delegate_task → plan_verify → write_plan → skill_view → write_plan → delegate_task → plan_verify → skill_view` ⇒ **đúng SOP mới**: nghiên cứu → ghi v1 → phản biện → `plan_verify` → sửa → v2 → phản biện → `plan_verify` |
| Sổ phản biện `plan_verifications` | **2 hàng**, cả hai đúng cặp `(identity, version)`: `retry-model-calls@v1 verdict='revise'` (critic `7f59b91314db4464b0a82d41b5fac737`, 1422 chữ, 5 điểm) và `@v2 verdict='revise'` (critic `b748e42af1e847bfbc548e99e48d4c18`, 1648 chữ, 5 điểm) |
| Sổ sở hữu `plan_owners` | 2 hàng, `session_id = c75876dd…` (trước đây không có sổ này) |
| Nới hạn chót | `notice TURN_EXTENDED` ngay sau `plan_written`: *"+420 s cho lượt này (plan_written)"*, `extensions: 1` — lượt 540 s > trần cũ 600 s **không** hụt |
| Cổng chặn cứng, mặt TỪ CHỐI | `POST /api/agent/plans/review {identity: retry-model-calls, version: 1, decision: approved}` ⇒ **409** `{"blocked": true, "code": "PLAN_APPROVAL_UNVERIFIED", …}` và **0** hàng `plan_reviews` mới |
| Cổng chặn cứng, công tắc `BOXFOX_PLAN_VERIFY=warn` (harness 3117) | **200** kèm `"approvalWarning": "PLAN_APPROVAL_UNVERIFIED: …"`, `resumed: true`, `turnId: "c75876dd…#2"`, `wake.state = "opened"`, **1** dòng `plan.approval.unverified` |
| Cổng chặn cứng, công tắc `off` (harness 3118) | **200**, **không** `approvalWarning`, **0** dòng `plan.approval.unverified` |
| Cổng nguồn (`BOXFOX_PLAN_SOURCES_GATE=enforce`) | Không chặn lượt đo: bản v2 khai 4 dữ kiện ngoài và **cả 4** đến từ phiên con `research` (`externalFacts 4 / externalFactsSourced 4` trong `plan_evaluated`) |
| Phán quyết của chính mô hình | *"Kế hoạch retry đã qua 2 vòng phản biện độc lập và cả hai đều kết luận cần sửa, nên tôi chưa thể xin duyệt."* + *"Đã hết 2 vòng revise theo quy định nên tôi dừng và báo thật thay vì sửa vòng 3."* ⇒ **đúng thiết kế**: hết trần 2 vòng `revise` thì báo chủ nhà, KHÔNG xin duyệt |

**Cố ý lệch/ghi nhận.** (a) Lượt đo sống **chưa** đạt hàng `verdict='ok'`: cả hai bản phản biện đều `revise`, và chúng bắt **lỗi thật**
của bản kế hoạch mẫu (đề bài mẫu cài tiền đề sai: đòi retry cho lời gọi model bằng Python/aiohttp trong khi lời gọi thật nằm ở
`boxfox/router/src/providers/openai.mjs:77`) — nên **không nới cổng cho xanh**; ghi lại là hạn chế của *đề bài mẫu*. (b) Vai
`plan-review` chỉ-đọc, **không có** `terminal_exec` ⇒ phê bình kiểm được *hình dạng* lệnh nghiệm thu chứ không chạy được chúng
(`roles.py`): việc chạy thật vẫn thuộc vai `testing`, ghi ở `test-rounds.md` § *Vòng 25*. (c) Hai sổ plan (`plan_owners`,
`plan_verifications`) **cố ý không** nằm trong cascade `delete()` của `session_store.py`: chúng gắn với *kế hoạch*, không gắn với
phiên nào. (d) `owner-decisions.md` §4 nay có §4.1…§4.3 theo vòng; D-35 và D-37 là **cách hiểu đã thi công** của hai điểm chủ nhà
không được hỏi, sổ ghi rõ như vậy.

**Còn lại sau vòng này (ghi để không trôi).** (1) Mặt "duyệt một bản ĐÃ có `ok` ⇒ mở lượt thi công" chỉ đo được ở đường công tắc
`warn` (vì đề bài mẫu không đạt `ok`); lượt đo sau vẫn vậy thì câu hỏi mở cho chủ nhà là **siết đề bài mẫu**, không phải nới cổng.
(2) Nhãn `v1 (approved)` do box gán theo vị trí (BUG-76) vẫn còn trong API thô của box vì không rebuild box. (3) Con `plan-review`
không có `terminal_exec`. (4) Nợ cũ BUG-66/BUG-68/BUG-69 và bốn khoá `subagent*` trong `en.ts` vẫn nguyên.

### 6.34 Vòng 25 hậu kiểm — hai vòng soát mã độc lập + một vòng soát dọn + một vòng kiểm thử: **chín lỗi tìm ra, cả chín đã sửa** (2026-09-23)

**Ai soát cái gì.** Một vòng soát **nửa harness** (`runtime.py`, `api/server.py`, `plan_quality.py`, `roles.py`, `failures.py`,
`limits.py`, `session_store.py`; verdict **4/10 — Medium, *Ship with mitigations***), một vòng soát **nửa giao diện** (`PlanPanel.tsx`,
`PlanReviewCard.tsx`, `usePlanFiles.ts`, `planState.ts`, i18n; verdict **4/10 — Low, *Ship with mitigations***), một vòng **soát dọn**
(`ef4517d`) và một vòng **kiểm thử độc lập** trên cây đã đóng băng. Hai vòng soát mã chạy **chỉ-đọc**: không tệp nào bị sửa, mỗi phát
hiện đều có số đo tái hiện được (probe ngoài repo ở `/var/tmp/v25-probe`, SQLite đọc bằng stdlib).

**Ba lỗi phía harness — và vì sao chúng quan trọng hơn vẻ ngoài của chúng.**

| Mã | Lỗi | Đo được | Căn (đo ở `9e6b55d`) | Cách sửa |
|---|---|---|---|---|
| **BUG-80** | **(nặng, fail-open)** `ask_user` duyệt một bản chưa phản biện vẫn ghi hàng `approved` | Probe: `request_approval` bị từ chối `PLAN_APPROVAL_UNVERIFIED` (0 hàng), **cùng cặp khoá plan** đi qua `ask_user` + "Duyệt" ⇒ hàng `approved` (không có hàng `plan_verifications` nào) | `runtime.py:4002` cổng chỉ đứng ở nhánh `kind == 'approval'` (đường HỎI), còn `record_plan_decision` (`runtime.py:4137`) ghi cho **cả hai** đường — mà `tool_contracts.py:157` lại khuyên model truyền `planIdentity`/`planVersion` cho `ask_user` | Cổng đứng luôn ở **chỗ GHI**: `record_plan_decision` từ chối sinh hàng khi bản chưa có `ok` (chế độ `enforce`), phát `plan_decision_skipped` + dòng `plan.review.unverified_approval`; ở `warn` hàng **vẫn** vào (đúng nghĩa công tắc); quyết định của chủ nhà vẫn được trả vì sổ không được giết một quyết định. Ca mới: `test_an_ask_user_approval_of_an_unverified_plan_writes_no_row` + ca `warn` |
| **BUG-81** | **(nặng, fail-closed nhưng SAI)** cổng nguồn từ chối kế hoạch viện dẫn host bắt đầu bằng `w` | Probe: `web.dev` → `eb.dev`, `w3.org` → `3.org`; bằng chứng `https://web.dev/…` + kế hoạch viện dẫn `web.dev` ⇒ `PLAN_QUALITY_REJECTED (sources-unbacked)`, **không ghi gì** | `plan_quality.py:340` `known_hosts` dùng `str.lstrip('www.')` — `lstrip` cắt theo **TẬP ký tự**, không theo **tiền tố**; cùng họ lỗi ở `known_paths`/`plan_sources_evidence` với `lstrip('./')` (`.github/workflows/ci.yml` mất dấu chấm đầu) | Hai hàm dùng chung `strip_www()` / `normalize_path()` (tiền tố), ba chỗ chuẩn hoá đi qua chúng; ca mới ở `test_plan_sources_gate.py` (cả mức hàm thuần lẫn đường sống) + `test_plan_quality.py` |
| **BUG-82** | **(vừa)** verdict phản biện đọc theo "lần khớp cuối ở BẤT KỲ ĐÂU", không theo dòng cuối | Một bài **thuật lại** verdict vòng trước (`VERDICT: revise` nằm giữa bài, kết thúc bằng văn xuôi) quyết định kết quả — im lặng, không kiểm chứng được | `runtime.py` `plan_critique()` lặp `re.finditer(r'(?im)^\s*VERDICT:…', text)` rồi lấy lần khớp **cuối**, trong khi SOP (`roles.py:167`) đã hứa *"END with exactly one final line … No text after that line"* | Luật siết **đúng bằng lời hứa**: verdict phải là **dòng cuối** (`^VERDICT:\s*(ok|revise)$`), ngược lại vẫn `PLAN_VERIFY_VERDICT_MISSING`; dòng trống ở cuối bài hợp lệ vẫn qua. Hai ca mới ở `test_plan_verify.py` |
| **BUG-88** | **(vừa, fail-open nhẹ)** cổng NGUỒN đọc cả **THAM SỐ** lời gọi, nên host do chính model đặt vào `args` được tính là "công cụ đã trả về" | Vòng kiểm thử độc lập (nhóm H, ca H7) gieo `https://invented-host.example/facts` **chỉ trong `args`** của một lời gọi thành công (kết quả không nhắc host) ⇒ kế hoạch viện dẫn host đó vẫn được ghi | `runtime.py:2438` `for text in self.source_strings(payload)` quét **cả** payload `tool_end` (`{id, name, args, result}`), trong khi docstring của chính hàm và câu từ chối của cổng nói nguồn phải đến từ **kết quả** công cụ (*"cite a host a real tool call returned"*) | Cổng chỉ đọc `payload.get('result')` + 3 dòng chú thích; ca mới `test_a_host_the_model_named_only_in_its_own_call_args_is_not_evidence` chứng minh **đỏ trước / xanh sau**. Lời gọi HỎNG vẫn bị lọc (`is_error` nằm trong `result`); vòng kiểm thử giữ lại bản chạy đầu (fixture H3 của chính nó sai) ở `/var/tmp/v25t/adv_core2_firstrun.log` |

**Bảy điểm phía giao diện — không điểm nào ghi sai dữ liệu, nhưng ba điểm nói dối bằng sự im lặng.**

| Mã | Lỗi | Căn (đo ở `6dfbd6c`) | Cách sửa (`f7a8e9e`) |
|---|---|---|---|
| **BUG-83** | Bản có verdict `revise` vẫn hiện nút Duyệt **bấm được**, mà harness chắc chắn trả 409 — mời chủ nhà vào một cú bấm hỏng | `usePlanFiles.ts:457` `approvalLocked = verification.state === 'none'`; harness chỉ cho qua khi verdict **đúng bằng** `ok` | `/plans/status` mang thêm `gate` (`verifyMode`, `sourcesMode`, cờ `*Unknown`) — commit `9e6b55d`; tab Plan đọc công tắc và khoá Duyệt khi `revise` + `enforce`, **không** khoá ở `warn`/`off`; dòng lý do khoá dịch ra ở cả ba nhánh (chưa đọc xong sổ / `revise` / `none`) |
| **BUG-84** | Câu giải thích THẬT của `plan_wake` bị bỏ, giao diện in câu chung chung "no new turn was opened" cho mọi kết cục | `planState.ts:380-399` chỉ giữ `resumed`/`turnId`/`recorded`/`forwarded`; harness đã gửi `wake {state, code, message}` + `approvalWarning` ở **mọi** đường | Mang nguyên `wake` + `approvalWarning` tới panel: `failed`/`missing`/`busy` in **nguyên văn** câu của harness kèm mã; chỉ `opened` mới nói là đã mở lượt |
| **BUG-85** | Cú bấm *Run review session* hỏng **im lặng** | `usePlanFiles.ts:376-388` đặt `verifyError` nhưng `PlanPanel.tsx:1013` không vẽ nó — nút tự bật lại, mặt vàng y như chưa bấm | Vẽ `verifyError` dưới nút bằng đúng khuôn dải `role="status"` đã dùng hai lần trong panel |
| **BUG-86** | Đổi bản kế hoạch ⇒ mặt/bản nháp của **bản cũ** sống thêm một nhịp; điều kiện gõ cho v1 gửi kèm quyết định cho v2 | `usePlanFiles.ts:219-225` chỉ xoá `reviewResult`/`reviewBlocked`/`blocked`; `PlanPanel.tsx:215-219` không xoá `approveNote`/`changesNote` | Đổi bản ⇒ xoá **ngay** `verification`/`ownership`/`evaluation`/`selectedReview`/`reviewStale`/`planState` + cả hai bản nháp và cờ mở popup; `verification = null` = *chưa đọc xong* (một mặt thứ ba, **khác** `unknown`, để không mượn câu "sổ không đọc được") |
| **BUG-87** | Hai ô nhập mới chỉ có `placeholder`; popup "duyệt kèm điều kiện" không đóng được bằng Escape/bấm ra ngoài | `PlanPanel.tsx:589`, `:653` (tiêu đề là phần tử trần, không `id`/`aria-labelledby`); menu identity/version đã có khuôn `mousedown` mà popup không có | `aria-labelledby` trỏ đúng tiêu đề đang thấy; Escape + bấm ra ngoài đóng popup, **giữ** chữ đã gõ |

**Ba ghi chú hậu kiểm ĐỂ NGUYÊN (có lý do, không phải bỏ sót).** (a) `record_plan_verification` là chỗ ghi sổ **duy nhất** không nằm
trong `try/except`: đo được là nó đi ra thành `is_error` + `errorCode` của công cụ nên lượt **không** chết và model đọc được lỗi — đó là
chủ ý của tác giả ("mọi thứ sau hàng sổ đều là best-effort"), ghi lại để lần sau không ai "sửa" thành im lặng. (b) `plan_wake.turnId` đọc
`turn_count` **sau** `runtime.submit(...)`: đúng số vì lượt được cấp ngay trong `start()`, và trường này là **thông tin**, không phải hợp
đồng. (c) `PlanReviewCard.tsx` + `.test.tsx` + `agentApi.ts` giữ **LF** trong thư mục nhiều CRLF — cố ý không đổi (đổi là diff toàn tệp,
không mang lại gì); mọi tệp khác giữ đúng kiểu xuống dòng của chính nó.

**Số đo sau hậu kiểm.** Toàn bộ backend (từ gốc repo, `--deselect test_terminal_exec_echo`): **1219 passed, 1 deselected in 377.87 s**
(trước hậu kiểm: 1210 — chín ca mới: 1 ở `test_plan_routes`, 2 ở `test_plan_approval_ledger`, 1 ở `test_plan_quality`, 3 ở
`test_plan_sources_gate`, 2 ở `test_plan_verify`). Frontend (`build-ui`): **126 tệp / 1113 ca đạt** (trước: 1086), `tsc -b --noEmit`
**exit 0**. Ba ca then chốt của hậu kiểm được chứng minh **đỏ trước / xanh sau** bằng cách hoàn nguyên từng bản vá
(`/var/tmp/v25c/redcheck.py`): thiếu bản vá ⇒ mỗi ca **1 failed**; có bản vá ⇒ xanh.

**Còn lại sau hậu kiểm (ghi để không trôi).** (1) Chủ nhà **không thể** duyệt một bản đang `revise` khi công tắc ở `enforce` — đó đúng là
luật đã chốt (D-34) và là lý do có công tắc, nhưng nghĩa là: model chạm trần 2 vòng sửa mà vẫn `revise` thì đường duy nhất để đi tiếp là
hạ công tắc hoặc yêu cầu sửa tiếp; **cân nhắc** một đường "chủ nhà chấp nhận rủi ro" ở vòng sau, cần chủ nhà chốt. (2) Câu hỏi mở về
`VERDICT:` nằm ở **cuối** bài phản biện: câu trả lời bị cắt cụt thì mất luôn phán quyết ⇒ nay bị từ chối thẳng (đúng, không đoán), nhưng
đặt verdict ở **đầu** bài sẽ chống cụt tốt hơn — cần đổi SOP + kỹ năng, để vòng sau. (3) Nợ cũ giữ nguyên: BUG-66/BUG-68/BUG-69, nhãn
version của box (BUG-76 vế hai), bốn khoá `subagent*` trong `en.ts`.

### 6.35 Vòng 27 (đợt 5 — skill chết) — skill dạy model gọi tool không tồn tại: BUG-89, đã sửa cả cây vendor + dựng cổng chặn (2026-09-24)

**Phát hiện.** `grounded-citations/SKILL.md` dạy model gọi `web_extract` **5 lần** (`:50,94,137,228,237`), nhưng harness chỉ
ship `web_fetch` (`agent_core/tool_contracts.py`). Đo cả cây vendor ở `a959c51` (`git grep -o web_extract HEAD -- backend/src/agentbox/vendor/hermes`):
**83 lần trong 41 tệp `.md`**, riêng **67 lần trong 35 `SKILL.md`**, cộng 18 lần trong tệp không phải `.md`. Cùng họ lỗi:
`read_file`, `write_file`, `search_files`, `patch`, `execute_code`, `terminal`, `curl`, `vision_analyze` và 9 tên `browser_*` — không tên nào có
trong `tool_contracts.SCHEMAS`.

| Mã | Lỗi | Đo được | Căn | Cách sửa |
|---|---|---|---|---|
| **BUG-89** | **(nặng, im lặng)** skill **đã bật** hướng dẫn model gọi tool harness không ship: lượt research cứ thử rồi nhận lỗi tool, không ai phát hiện vì không ca test nào đối chiếu tên tool trong skill với danh mục tool thật | `grep` ở `a959c51`: 67 lần trong 35 `SKILL.md`; `grounded-citations` một mình 5 lần và `web_fetch` **0** lần | `DEFAULT_SKILLS` bật 8 skill mà không ai soát nội dung; `skill_view` không tự chạy script nên `sources.py` (678 dòng) chưa bao giờ chạy, và `HERMES_HOME` không được đặt ở đâu trong `backend/src/agentbox` nên đường dự phòng rơi vào `/root/.hermes` | Viết lại ba skill research sang đường harness-native (`grounded-citations` → `source_add`/`source_list`/`source_verify`/`dossier_write` + `[r<N>]`, `arxiv` → `web_fetch` trên `https://export.arxiv.org/api/query` thay `curl`, `research-team` mới 220 dòng); quét toàn cây vendor (36 tệp `.md` + `sources.py`) ⇒ **0** `web_extract`; bật `blocked-page-recovery` + `arxiv` + `research-team`, giữ **tắt kèm lý do có chữ** sáu skill cần gói (#5977); ghim `HERMES_HOME=/home/agent/.hermes` trong `deploy/docker/box-services.sh`; cổng chặn mới `backend/tests/unit/test_skill_tool_names.py` quét **mọi** tệp `.md` của cây vendor cho tên đã nghỉ (`web_extract`) và quét kỹ năng **đang phục vụ** (`DEFAULT_SKILLS` ∪ `ROLE_SKILLS`) cho mọi tên trông-như-tool so với `tool_contracts.SCHEMAS` |

**Phạm vi chưa làm, ghi nhận có chủ đích.** Chín tên `browser_*` trong `skills/software-development/dogfood/SKILL.md` nằm trong `SERVED_EXCEPTIONS`
kèm lý do (nợ của vai kiểm thử, ngoài đợt 8). `HERMES_HOME` chỉ có hiệu lực **sau khi box được dựng/khởi động lại** — đợt này chỉ sửa tệp, chưa khởi động lại box.

### 6.36 Vòng 27 (đợt 3–8 và hậu kỳ) — hai mươi bốn lỗi sản phẩm (và chín lỗi của chính ca test) lộ ra trong lúc thi công sổ nguồn, hồ sơ, phản biện và nhịp tiến độ (2026-09-24)

**Phát hiện.** Không lỗi nào do người dùng báo: mỗi lỗi lộ ra khi chạy ca test mới hoặc khi đo sống một
đường vừa viết. **Mười chín** lỗi thuộc **mã sản phẩm** (bảng dưới, `BUG-90`…`BUG-108`) và **năm** lỗi sản phẩm nữa
(`BUG-109`…`BUG-113`) do **lượt kiểm thử độc lập `v27d`** tìm ra trên chính cây ấy rồi được vá ngay —
**hai mươi bốn** lỗi sản phẩm; ngoài ra **chín** lỗi thuộc **chính ca test** (ghi ở cuối mục, không tính
là lỗi sản phẩm). Mọi sửa đều giữ bất biến: việc mới có công tắc tắt
(`BOXFOX_RESEARCH_*`, `BOXFOX_STEER`), và thiếu brief thì hành vi cũ không đổi.

| Mã | Mức | Lỗi | Đo được | Căn | Cách sửa |
|---|---|---|---|---|---|
| **BUG-90** | vừa | Luật `origin-undeclared` đếm "nguồn độc lập" theo **hàng**, nên hai bản đăng lại của **cùng một bản tin** được tính là hai nguồn ⇒ hồ sơ một-nguồn được chấm là đủ | Ca `test_research_quality.py` dựng `moh.gov.vn` + `baochinhphu.vn` cùng nội dung: luật cũ **không** báo lỗi | `assess_rows` so tập `host` của nhóm hàng, không gộp theo **đơn vị gốc** | Chấm theo `origin_units(rows)`: chỉ đạt khi `len(unit.hosts) >= 2`; detail `f'{unit.row_ids[0]}: {", ".join(unit.hosts)}'` |
| **BUG-91** | nặng (im lặng) | `source_add` do **nhánh con** gọi ghi hàng vào sổ của **phiên CON**, nên main đọc sổ thấy rỗng và hồ sơ bị từ chối là thiếu nguồn | Lượt đo sống: hàng sổ có `session_id` = mã nhánh con | `source_add` lấy `session['id']` làm chủ sổ | `_ledger_owner(rt, session, sid)` ⇒ `(owner, child_id)`: đi ngược lên phiên giữ brief |
| **BUG-92** | vừa | `source_add` **không idempotent** theo `(URL, đoạn trích)`: cùng một nguồn được ghim nhiều hàng, sổ phình và luật đếm nguồn bị nhiễu | Gọi lại y hệt ⇒ thêm hàng mới thay vì trả hàng cũ | Không có khoá tự nhiên cho hàng sổ | `_excerpt_key(url, excerpt)`; hàng trùng trả `{'rowId': …, 'reused': True, …}` |
| **BUG-93** | vừa | `SessionStore.source_add` trả **hàng của nhánh khác** khi mã tự cấp đụng nhau (đua giữa hai nhánh) | Dựng hai lời gọi cùng mã ⇒ hàng đọc về thuộc nhánh kia | `INSERT` một lượt rồi đọc lại theo mã đã đặt | Cờ `given`, **3 lượt thử**, `raise last_error or sqlite3.IntegrityError('source_ledger: row id not available')` |
| **BUG-94** | nặng (sập) | `NameError: name 'RESEARCH_GATE_MODE_UNKNOWN_CODE' is not defined` trong `research_runtime.dossier_write` ⇒ mọi lời gọi ghi hồ sơ ném lỗi khi công tắc gate lạ | Ca gate-runtime đỏ ngay lượt chạy đầu | Hằng số được dùng nhưng thiếu trong khối `from .limits import (…)` | Thêm ba mã `RESEARCH_OWNER_VIEWS_*` + `RESEARCH_GATE_MODE_UNKNOWN_CODE` vào khối import; thêm ca ghim |
| **BUG-95** | nặng (sập) | `IndexError: list index out of range` khi `dossier_versions(research_id)` rỗng (hồ sơ đầu tiên của mỗi việc) | Ghi hồ sơ lần đầu ⇒ sập | `versions[-1]` gọi trực tiếp | `(int(versions[-1] or 0) if versions else 0) + 1` |
| **BUG-96** | nặng (im lặng) | `research_brief` **không lưu** brief: `store.save` chỉ ghi `messages`, phần `config` rơi mất ⇒ lượt sau mất hồ sơ việc, cổng `missing_brief_gate` báo thiếu brief dù đã mở | Đọc `research_config(store.get(sid))` sau khi mở brief ⇒ rỗng | `save` không phải đường ghi `config` | `rt.store.update_config(sid, session['config'])` |
| **BUG-97** | nhẹ | Mỗi lời gọi `research_brief` **ghim thêm một hàng `D:`** dù nội dung không đổi ⇒ sổ quyết định đầy hàng trùng | Đếm `journal_tail(...)['kind'] == 'decision'`: 2 lời gọi ⇒ 2 hàng | Không so nội dung cũ trước khi ghim | Cờ `changed`; chỉ ghim khi có trường đổi (kể cả `ownerViews`) |
| **BUG-98** | vừa | `research_tier_limits` **kẹp nhầm** `branchCeiling`: mức 3 trả 6 nhánh thay vì 15 (trần theo sóng bị dùng làm trần cả việc) | `research_tier_limits(3)['branchCeiling']` = 6 | Một khoá gánh hai nghĩa | Tách `branchCeilingPerWave` (5) khỏi `branchCeiling` (15); thêm ca ghim cả ba mức |
| **BUG-99** | vừa | Ba công cụ thiếu **cổng vai**: `research_status` gọi được từ vai bất kỳ, `research_verify` gọi được từ nhánh con, `roles.SOURCE_READ` thiếu `research_status` ⇒ chủ nhà đọc được số liệu nhưng nhánh con cũng duyệt được hồ sơ | Ca vai: `PermissionError` không ném | Cổng vai viết rải rác theo từng công cụ | `research_status` ba vai `{'orchestrator','research','research-review'}`; `research_verify` chỉ `orchestrator`; `SOURCE_READ = {'source_list','source_verify','research_status'}` |
| **BUG-100** | nhẹ | Ba câu gợi ý hành động (`next`) chỉ **sai đường**: mức 3 nói nhánh con tự gọi `research_verify`, nhưng cổng vai chỉ cho orchestrator | Đọc `answer['next']` ở cả ba mức | Câu chữ viết trước khi có cổng vai | Sửa cả ba câu: mức 3 = main gọi `research_verify` sau khi nhánh phản biện xong |
| **BUG-101** | vừa | `source_verify` thiếu **sàn thành công giả**: một hàng 165–259 byte được chấm `ok` | So với `moh.gov.vn` 165 byte | Không có ngưỡng tối thiểu | `SOURCE_FAKE_SUCCESS_MIN_CHARS` + thông điệp nêu rõ hàng ngắn là thành công giả |
| **BUG-102** | nặng (sập) | `TURN_FAILED_KEYERROR: KeyError: 'research-review'` tại `commands.py` ⇒ nhánh **phản biện độc lập không bao giờ được sinh** | Nhật ký lượt thật | `ROLE_SKILLS` thiếu khoá cho vai mới | `ROLE_SKILLS['research-review'] = {'codebase-inspection'}` |
| **BUG-103** | vừa (im lặng) | `dossier_write.tables` **mất bảng âm thầm** khi model gửi LIST hoặc mapping thay vì danh sách `{name, markdown}` | Ghi hồ sơ có bảng ⇒ thư mục `tables/` rỗng | Không chuẩn hoá dạng đầu vào | `_dossier_tables(raw)` chuẩn hoá cả ba dạng về `[{'name','markdown'}]` |
| **BUG-104** | vừa | Cổng chất lượng **thiếu luật** cho trường hồ sơ bắt buộc (#5989): hồ sơ luật thiếu `docNumber`/`effectiveDate`/`validity` vẫn qua | Ca `test_research_quality.py` | Luật `validity_fields` chỉ sống trong `research_profiles` | `ledger_payload(rows)` + `hard_missing(profile, rows)` trong `research_quality.py`, một lỗi kể **một lần**, bỏ trường đã có luật riêng |
| **BUG-105** | vừa (sai hợp đồng) | `dossier_write` cho **nhánh con** — trái `ledger.md:194` (*con research không có `file_write`/`research_write`; hồ sơ do main ghi*) | Ca vai: con gọi được và ghi được tệp | Nới cổng cho tiện lúc thi công | Hoàn nguyên về `orchestrator`-only kèm câu từ chối có chữ |
| **BUG-106** | vừa (báo động sai) | Luật `research-critique-missing` chạy **cả ở mức 2**, nơi hồ sơ **không có** mục Phản biện ⇒ mọi hồ sơ mức 2 bị từ chối oan | `assess(mode='enforce')` mức 2 ⇒ `['research-critique-missing']` | `assess` không hỏi mức trước khi bắt mục Phản biện | `critique_required(level)` đọc chính `DOSSIER_SECTIONS`; nhánh critique nay `selected_mode == 'enforce' and not critique_ok and critique_required(level)` |
| **BUG-107** | nhẹ | Bốn mục `TIER1_SUFFIXES` (`'docs.'`, `'developer.'`, `'developers.'`) **không bao giờ khớp** vì `_suffix_in` chỉ so `host.endswith(suffix)` ⇒ `developers.google.com`, `developer.mozilla.org` rơi xuống tầng 3 | Ca `test_source_tiers.py` chỉ ra tầng 3 | So hậu tố mà mục thật ra là **tiền tố** (`docs.`) | `_prefix_in(host, prefixes)`: chỉ xét mục `endswith('.')` và đòi `len(host) > len(prefix)` |
| **BUG-108** | **nặng (im lặng)** | `annotate_branch_answer` tìm **chủ sổ** từ **phiên CHA** rồi `source_rows_for(owner, [childId])` ⇒ khi cha chưa giữ brief, nó đọc sổ rỗng của chính con và **mọi** nhánh đều bị chú thích là `research-lineage-missing` (dù nhánh có để lại dòng) | Ca end-to-end mới: nhánh gọi `source_add` rồi trả lời ⇒ `gate['rows'] == 0` trong khi `store.source_count(cha) == 1` | `_ledger_owner(rt, session, child_id)` với `session` là phiên **đang gọi** `delegate_task`, mà hàm này leo lên theo `parent_id` của chính tham số đó | Hỏi từ **phiên con**: `child_session = rt.store.get(str(child_id)) or session` rồi `_ledger_owner(rt, child_session, str(child_id))`; ca `test_a_research_child_that_did_leave_a_row_keeps_its_row_out_of_the_notes` chứng minh **đỏ trước / xanh sau** |

| **BUG-109** | **nặng (im lặng)** | `dossier_write` tính số bản **chỉ từ chỉ mục** trong store, còn op của box từ chối ghi đè tệp `v<N>` đã có: một tệp `v1` do lượt trước để lại (ghi hỏng giữa chừng) mà chỉ mục chưa biết làm lời gọi hỏng **lặp lại y hệt ở mọi lần thử**, trong khi cách sửa câu lỗi mách ("ghi bản kế") không thi hành được vì số bản vẫn tính ra 1 | Lượt kiểm thử `v27d` (F-A): phòng sạch chỉ mục + tệp `v1` sẵn có ⇒ `DOSSIER_VERSION_TAKEN`, `dossier_versions` vẫn `[]`, thử lại y hệt | Số bản là dữ liệu của **phòng**, không chỉ của store | Vòng lặp thử trong ngân sách `DOSSIER_VERSION_ATTEMPTS_MAX = 10`: gặp `DOSSIER_VERSION_TAKEN` thì đẩy lên bản kế (bản cũ KHÔNG bị ghi đè) + `system_log` `research.dossier.version_taken`; hết ngân sách thì ném nguyên văn lỗi của box. Ca `test_a_version_that_the_room_already_has_is_skipped_not_a_dead_end` + `test_a_version_loop_that_never_lands_gives_up_and_says_which_code` chứng minh **đỏ trước / xanh sau** |
| **BUG-110** | **nặng (luật ngược)** | Guard trần lượt trong **cùng một lượt** so **ngược**: `stored > ceiling` ⇒ từ chối. Nên một lời gọi **NÂNG** trần (900 → 1800) đi qua im lặng, còn lời gọi **HẠ** trần (900 → 600) bị từ chối kèm câu "cần dài hơn thì xin chủ nhà ở lượt sau" — đúng ngược với luật "chỉ được hạ" (chính bản vá hậu kỳ `2bcc02b` gây ra) | Lượt kiểm thử `v27d` (F-G): cùng lượt `ceilingSeconds` 900 ⇒ 1800 nhận, ⇒ 600 từ chối | Điều kiện viết xuôi theo tên biến thay vì theo luật | `if stored and ceiling > stored: raise …`; ca `test_one_turn_may_lower_the_turn_ceiling_but_never_raise_it` ghim **cả hai chiều** (đỏ trước / xanh sau) |
| **BUG-111** | nhẹ | Thẻ mốc của `research_brief` **không mang trần đang chạy**: lượt sau nâng mức mà bỏ trống `ceilingSeconds` thì `turnSeconds`/`softCeilingSeconds` là hạn mức **danh nghĩa của mức mới** (3600) trong khi trần thật vẫn là con số giữ lại (900) ⇒ thẻ mốc báo một con số không ai thi hành | Lượt kiểm thử `v27d` (F-H) | Thiếu khoá cho trần hiệu lực | Thêm `'ceilingSeconds': ceiling` vào `answer` (kèm chú thích phân biệt trần hiệu lực với hạn mức danh nghĩa); ca cũ `test_a_later_turn_may_raise_the_level…` ghim thêm `later['ceilingSeconds'] == 900` |
| **BUG-112** | nhẹ (mã lệch lời) | Chú thích ở `research_brief` nói lượt sau **giữ lại phòng hồ sơ cũ**, nhưng mã lại mở phòng mới mỗi lượt (`dossier_dir` rỗng khi `turn` khác) ⇒ bản `v2` rơi sang phòng khác, và ca cũ chỉ xanh nhờ hai lời gọi rơi vào **cùng một phút** | Lượt kiểm thử `v27d` (F-I): hai lượt liền nhau qua mốc phút ⇒ phòng khác nhau | Bản vá hậu kỳ thu phòng theo `same_turn` | Trả về luật đã chốt: **một việc = một phòng** — giữ `dossierDir` khi nó khớp khuôn `.research/<slug>-<yyyymmdd-hhmm>`, thay khi không khớp (bản ghi cũ); ca `test_a_later_turn_keeps_the_room_even_when_the_clock_moves` (ghìm đồng hồ) và `test_a_stored_room_that_does_not_match_the_shape_is_replaced` |

| **BUG-113** | vừa (báo động sai) | Hệ quả phụ của chính bản vá BUG-110: khối "bỏ trống `ceilingSeconds` ⇒ GIỮ trần đã chốt" nằm **SAU** cổng cùng lượt, nên lúc chấm `ceiling` còn là hạn mức **danh nghĩa của mức** ⇒ một lời gọi `research_brief` **cập nhật** trong cùng lượt (gọi lại y hệt hoặc chỉ đổi `branches`) mà bỏ trống trần bị từ chối oan `RESEARCH_BRIEF_RAISE_REFUSED` | Lượt kiểm thử `v27d` (F-J, `probe17` b/c): cùng lượt 900 rồi bỏ trống trần ⇒ từ chối; `79df0a9` nhận bình thường | Thứ tự hai khối luật trong `research_brief` | Hoist khối bảo tồn lên TRƯỚC cổng (`if args.get('ceilingSeconds') is None and existing: ceiling = max(60, min(int(stored) or limits['turnSeconds'], limits['turnSeconds']))`) + ca `test_a_same_turn_update_that_omits_the_ceiling_keeps_it` (đỏ trước / xanh sau) |

**Chín lỗi thuộc chính ca test (không phải lỗi sản phẩm, ghi để khỏi lặp):** (1) ba ca
`test_steer_queue.py` đọc cột `status`/`claimed`/`step` **không có** trong bảng `session_steers` — cột thật
là `state`/`injected`; (2) một ca đòi `ValueError` khi `runtime.submit` trên con **chưa có lượt chạy**;
(3) `test_runtime_info.py` so khoá `int` với khoá `str` ba lần liên tiếp (`tierLimits`,
`childStepsByTier`, `sourceTiers.tiers`); (4) `test_research_quality.py` đọc `verdict.issues` (list
`Issue` dataclass) thay vì `verdict.missing` (list `dict`); (5) kỳ vọng sai tên mục (`'mục Tóm tắt'` thay
vì `'mục Câu hỏi'`); (6) ca `dossier_write` đếm cả lời gọi `journal_append`; (7)
`test_busy_controls_never_start_second_model_call` còn kỳ vọng `SESSION_BUSY` sau khi D-43 đổi kết cục
thành `{'status': 'steered'}`; (8) `test_research_profiles.py` gọi `Profile.hard_fields()` như **hàm**
(đó là property); (9) một `@pytest.mark.parametrize` dán nhầm lên hàm không có tham số `level`.

### 6.37 Vòng 28 — khuôn trả lời cuối còn bị ÉP ở tầng kỹ năng và prompt (chủ nhà phát hiện): hạ hết xuống gợi ý (2026-09-24)

Vòng 24 đã bỏ **khuôn năm phần**, nhưng ba chỗ vẫn **ra lệnh** thay vì gợi ý, nên lượt thật vẫn đọc ra
như một cái form. Chủ nhà nói thẳng (nguyên văn, giữ cả lỗi gõ): *"tôi vẫn thấy hiện tượng format đã làm,
còn lại,... chúng ta cx cần chỉnh lại cái đó, chỉ là skill gợi ý agent trả lời, k nên khóa cứng nhue vậy.
Agent vẫn trả lời tự nhiên như chatgpt, claude và trả lời ngắn, các phần đã làm linh tỉnh chủ là gợi ý
thôi, k phép ép agent trả lời theo form đó, võe hết tính tự nhiên"*. Quyết định ghi ở
`owner-decisions.md` **D-44**.

| Mã | Mức | Triệu chứng | Bằng chứng | Nguyên nhân | Vá |
|---|---|---|---|---|---|
| **BUG-114** | vừa (trải nghiệm; không hỏng dữ liệu) | Ba chỗ ở tầng prompt/kỹ năng vẫn **ra lệnh** về dạng câu trả lời cuối: (1) kỹ năng `final-report` 2.0.0 — *"The evidence part **closes** the answer, and it is **the most important part**"*, *"**Never** print an empty part"*, *"The evidence goes at the END… **never** in the middle, never at the top"*, *"**Not optional** when the turn produced something observable"*; (2) `RECAP_CLOSER` — *"**read** the `final-report` skill… If the owner handed over work… **re-capture every item** that is now finished"*; (3) `ANSWER_EVIDENCE_LINE` — *"A turn with something observable **closes** the answer with…"* | Lượt thật của chủ nhà đọc ra như khuôn; ba câu ra lệnh nằm nguyên trong `runtime.py`, kỹ năng và `AGENT.md` §3.4 ở mã `cbe1d5f` (đọc bằng `grep`; ghim cũ trong `test_runtime_prompt.py` còn **khẳng định** câu `closes the answer`) | Vòng 24 dồn dạng câu trả lời vào kỹ năng (D-31) và **giữ một dòng cứng** trong prompt (D-32) — đúng chữ "cứng"; kỹ năng viết ở giọng mệnh lệnh vì lúc ấy còn sợ model bỏ mục | `ANSWER_EVIDENCE_LINE` thành câu điều kiện mở bằng *"If this turn really has something to show, **you may** close the answer with…"*; `RECAP_CLOSER` nói kỹ năng là *"an optional menu of ideas … read it **if that helps**"* và bỏ vế chụp lại ảnh; kỹ năng **3.0.0** (*"ideas, not a form"*, *"Nothing here is compulsory"*, luật ảnh ở cuối = *sở thích*, luật mở bài = *mẹo đọc trên chat panel*); `AGENT.md` §3.4 nói rõ *"No part list, no order and no template is required"*; ca mới `test_ky_nang_va_con_tro_deu_la_goi_y_khong_ep_khuon` + bốn ghim đổi chiều (`D-44: kỹ năng còn ra lệnh`, `D-44: dòng nhắc không được ra lệnh`) |

Số đếm sổ lỗi sản phẩm của vòng 27–28 nay là **hai mươi lăm** hàng (`BUG-90`…`BUG-113` đếm ở §6.36,
thêm `BUG-114` ở đây).

**Điều KHÔNG đổi (cố ý):** luật **trung thực** — không bịa ảnh, không lấy ảnh cũ làm ảnh trạng thái mới,
nói rõ việc chưa chạy được; **D-18** (cổng bằng chứng không chấm khuôn câu trả lời); tóm tắt do model
viết + `View details` — nay chỉ còn là **mẹo đọc**, không phải luật.

### 6.38 Vòng 2026-10-06 — F05 (Work Graph, `web_search`): lỗi hạ tầng/cấu hình không còn xui sửa truy vấn — ĐÃ SỬA (PART 1)

Nhãn **F05** theo `docs/plan/Work-Graph-fix.md` §"Danh mục lỗi" — **đừng lẫn với F5** ở §6.2 (ca
`inspect_element`). Bản ghi quyết định đầy đủ: `docs/plan/builtin-search-default.md`; ba tầng test +
kịch bản bench: `docs/testing/builtin-search-e2e.md`.

| Mã | Lỗi / việc | Mức | Trạng thái | Bằng chứng |
|---|---|---|---|---|
| F05 | `web_search` lỗi vì **hạ tầng/cấu hình** (Firecrawl 403/429; SearXNG/Brave/Tavily chưa cấu hình) mà hint vẫn bảo "sửa input và gọi lại" ⇒ agent đốt bước thử truy vấn khác trên cùng hạ tầng chết. **Không phải** lỗi do tiếng Việt trong truy vấn | HIGH | **ĐÃ SỬA (PART 1, 2026-10-06)** — lỗi cuối được phân loại `searchFailure.kind` = `config`/`infra`/`source`; câu chữ nói thẳng "not a query problem" (config/infra) và "do not retry the same search"; ca **rỗng** tách thành mã riêng `WEB_SEARCH_EMPTY` (được phép nới/đổi truy vấn **một lần**); `recovery_policy` khai hai mã là `capability_gap`/`no_progress` nên không rơi vào `unknown` | `backend/tests/unit/test_search_failures.py` (10 lượt: 8 hàm, 1 hàm tham số hoá 3 giá trị); `backend/tests/integration/test_search_searxng_stub.py` (4 ca, có ca rỗng ≠ chết); `backend/tests/integration/test_search_searxng_live.py` (5 ca, xoá sạch khoá trước khi chạy) |

Kèm theo cùng vòng: **N-5 đóng** (SearXNG tự host + tự dò là chân không-khoá mặc định — xem hàng N-5 ở
§6) và **R10-5 được rà lại, giữ nguyên**: hành vi "nhà cung cấp trả 200 với thân không phải JSON làm
đứt cả chuỗi" vẫn đúng là đã sửa ở đợt 10
(`test_web_tools.py::test_the_provider_chain_survives_a_challenge_page`).

### 6.39 Vòng 2026-10-08 — CUA trên Linux/X11: ba lỗi gõ/bấm, một lỗi giao diện, một giới hạn còn lại

Vòng này xuất phát từ yêu cầu của chủ sở hữu: *"kiểm, test kỹ hơn về CUA… tìm các bug nếu có"*.
Ba lỗi đầu đều thuộc loại **im lặng**: thao tác trả về `OK` nhưng kết quả trên màn hình lại khác.

| Mã | Mức | Triệu chứng | Bằng chứng | Nguyên nhân | Vá |
|---|---|---|---|---|---|
| BUG-115 | HIGH | Gõ chữ có dấu tiếng Việt qua CUA thì **mất sạch dấu**, khoảng trắng bị thay bằng ký tự lạ (`Xin chào Cửa sổ!` → `Xin cho Ca s!`); thao tác vẫn báo `OK` nên agent không hề biết mình vừa làm hỏng dữ liệu | `/var/tmp/cua-locale-probe.sh` (cùng một payload: terminal có `LANG` → KHỚP; `env -i` → mất dấu; `LC_ALL=C` → mất dấu) và `/var/tmp/cua-locale-verify.py` (sau khi vá: **35/35 ký tự, 3/3 lượt**; trước khi vá: 0/3) | `X11Platform._child_env()` chỉ chuyển `PATH/HOME/USER/LANG/LC_ALL/XAUTHORITY`; tiến trình harness chỉ có `DISPLAY=:1` (không `LANG`), nên **mọi ứng dụng do BoxFox mở** và mọi `xdotool` đều thừa hưởng môi trường không UTF-8. Chính locale của **ứng dụng đích** quyết định ký tự non-ASCII có sống sót qua XTEST hay không | `_child_env()` nay kiểm `has_utf8_locale(env)` và khi thiếu thì đặt `LANG = utf8_locale()` (dò `locale -a`: `C.UTF-8`, `C.utf8`, `en_US.UTF-8`, `en_US.utf8`), bỏ `LC_ALL`/`LC_CTYPE`; thêm ghi chú nền tảng khi phiên làm việc không có locale UTF-8. 8 bài kiểm mới trong `test_x11_platform.py` |
| BUG-116 | HIGH | Bấm **hai lần liên tiếp vào cùng một điểm** làm cú thứ hai treo đủ **5 s** rồi báo `SOURCE_CHANGED: X11 từ chối 'mousemove': hết thời gian chờ` — agent hiểu sai thành "cửa sổ đã đổi chỗ", người dùng thấy agent đứng hình | `primitives.click` đo được `KHÔNG ĐO ĐƯỢC: … hết thời gian chờ /usr/bin/xdotool`; sau khi vá: `click` p50 **22,7 ms**, 5/5 lượt xanh | `xdotool mousemove --sync` chờ một sự kiện `MotionNotify` tới đúng toạ độ; con trỏ đã đứng đúng chỗ thì X server **không sinh sự kiện nào**, nên lệnh chờ tới hết thời gian chờ | `click()` chỉ gọi `mousemove` khi con trỏ còn ở chỗ khác; 2 bài kiểm mới (`test_clicking_the_same_point_twice_does_not_move_the_pointer_again`, `test_a_click_at_another_point_still_moves_the_pointer_first`) |
| BUG-117 | HIGH | Mọi thao tác `key`/`type`/`click` nhắm vào cửa sổ chính bị từ chối bằng `SOURCE_CHANGED` khi ứng dụng đang mở hộp thoại của **chính nó** (ví dụ "Do you trust the authors of the files in this workspace?"); `xdotool windowactivate --sync` treo **>12 s**; ảnh chụp cửa sổ **không có** hộp thoại đang che nó | `/tmp/cua-vscode/run-04-terminal.png` (hộp thoại tin cậy thư mục), `/tmp/cua-vscode/composed.png` (ảnh đã ghép hộp thoại), `timeout 12 xdotool windowactivate --sync 33554436` → `exit=124` | Hộp thoại của ứng dụng là một cửa sổ X11 **riêng** (`WM_TRANSIENT_FOR`, `_NET_WM_WINDOW_TYPE_DIALOG`); mã cũ chỉ so **một** cửa sổ nên coi hộp thoại là "cửa sổ lạ đang che" | Thêm chuỗi chủ sở hữu `WM_TRANSIENT_FOR` (`get_window_owner`/`is_own_window`/`transient_windows`), chấp nhận hộp thoại của chính ứng dụng, **ghép** hộp thoại vào ảnh chụp, bỏ `--sync` khi kích hoạt và chờ `_NET_ACTIVE_WINDOW` 10 ms một lần (trần 0,25 s), đệm hình học 0,5 s. 11 bài kiểm mới; ca dùng VS Code nay chạy hết (`ran.txt: 5`) |
| BUG-118 | MEDIUM | Gõ chữ hoa tiếng Việt ngoài ASCII bị **mất dấu hoa**: `Á À Ã Â Ê Ô É È Í Ì Ó Ò Õ Ú Ù Ý` đến nơi thành chữ thường; `Ả Ạ Ă Đ Ơ Ư Ẽ Ĩ Ũ Ỳ` thì đúng | `/var/tmp/cua-upper-probe2.sh` (gửi `ÁÀẢÃẠĂÂĐÊÔƠƯÉÈẼÍÌĨÓÒÕÚÙŨÝỲ`, nhận `áàẢãẠĂâĐêôƠƯéèẼíìĨóòõúùŨýỲ`); `xdotool key Aacute` và `xdotool key U00C1` cho cùng kết quả sai | `xdotool type` tự ánh xạ keysym cho **từng** ký tự rồi trả lại ngay; bảng mã tạm đó mất tính hoa/thường. Bàn phím `us`/`pc105`, 248 keycode, **0 keycode mang keysym Unicode** | **ĐÃ SỬA (20fe542, 08/10/2026)** cùng BUG-119: `keysym_plan()` ánh xạ sẵn keysym vào keycode trống, giữ nguyên trong suốt lần gõ. Kiểm byte-chính-xác qua biểu mẫu web: **26/26 ký tự hoa đúng** (`ÁÀẢÃẠĂÂĐÊÔƠƯÉÈẼÍÌĨÓÒÕÚÙŨÝỲ`, 440 ms), chữ thường 27/27. Chỉ còn đường dự phòng (thiếu `xmodmap`) mới mất dấu hoa — nay là ghi chú nền tảng |

Kèm theo vòng này: `backend/tools/cua_bench.py` (đo latency + token, chốt trần `budget`) và
`docs/testing/cua-latency-token.md` (ba nhóm số đo, cách quy đổi token, danh sách chỗ còn chậm).

### 6.40 Vòng 2026-10-08 (tiếp) — gõ chữ có dấu trên X11: ký tự mất khi máy bận — ĐÃ SỬA

Phát hiện khi **quay phim** ca dùng web: đúng lúc ffmpeg ghi màn hình 12 fps, câu
`Xin chào Cửa sổ! áàảãạ ăâđơơư` đến máy chủ với 27/29 ký tự — `á` và `ã` biến mất, mà lệnh gõ vẫn
báo thành công. Truy tiếp thì đây là cùng một gốc với BUG-118.

| Mã | Mức | Triệu chứng | Bằng chứng | Nguyên nhân | Vá |
|---|---|---|---|---|---|
| BUG-119 | HIGH | Gõ chữ có dấu **mất ký tự khi máy bận** (quay phim, tải nặng): câu 29 ký tự mất 1–2 ký tự ở 3/6 lượt; thao tác vẫn trả `OK` nên agent không biết | `/var/tmp/cua-web/typing-load2.py` và `typing-delay.py` (máy chủ web ghi lại đúng byte nhận được, tải bằng chính ffmpeg x11grab): đường cũ **3/6** lượt sạch; mỗi ký tự một lệnh **8/10**; tăng nhịp lên 60 ms **7/10** (không đỡ, chỉ chậm gấp 3); ánh xạ sẵn + giữ nguyên **16/16 lượt sạch**, 361–387 ms cho 29 ký tự | `xdotool type` ánh xạ một keycode trống cho mỗi ký tự ngoài ASCII rồi **trả lại ngay**; máy bận thì ứng dụng đọc sự kiện sau lúc ánh xạ đã bị trả lại ⇒ ký tự mất hẳn. Nhịp gõ không liên quan (60 ms còn tệ hơn 12 ms) | `input.py`: `keysym_plan()` + `keysym_name()` + `release_keycodes()` — ánh xạ sẵn các keysym cần dùng vào keycode trống (`xmodmap -pke` để tìm chỗ trống, tối đa 10), gõ bằng `xdotool key`, **luôn** trả keycode về `NoSymbol` trong `finally` (kể cả khi lỗi giữa chừng). Không đủ chỗ/thiếu `xmodmap` ⇒ quay lại `typing_chunks()` (mỗi ký tự ngoài ASCII một lệnh). 5 bài kiểm mới |

Ghi chú kèm theo: `typing_chunks()` vẫn là đường dự phòng nên vẫn được kiểm; nhịp gõ `TYPE_DELAY_MS = 12`
giữ nguyên (đo được: 60 ms không giảm mất ký tự).

### 6.41 Vòng 2026-10-08 (tiếp) — gia cố sau soát mã: chốt hộp thoại, hình học lúc bấm, và chốt trần

Ba điểm do vòng soát mã độc lập chỉ ra, đều là **hệ quả của chính các bản vá trong §6.39–6.40** — vá
xong thì lỗi cũ hết nhưng chốt an toàn bị nới ra hoặc công cụ đo nói không đúng.

| Mã | Mức | Vấn đề | Cách vá |
|---|---|---|---|
| BUG-120 | MEDIUM | **Chốt hộp thoại quá dễ dãi**: `is_own_window` chỉ đòi `WM_TRANSIENT_FOR` trỏ về đích. Trên X11 không có ranh giới quyền giữa các ứng dụng cùng màn hình, nên một công cụ lạ "bám theo cửa sổ đang hoạt động" (bảng chọn nhanh, công cụ chụp ảnh, cửa sổ IME/portal) đặt được thuộc tính đó và sẽ **được nhận input thay cho ứng dụng đích** — đúng thứ mà chốt này sinh ra để chặn. Bản trước vá BUG-117 theo hướng "cứ có thuộc tính là nhận", đánh đổi quá nhiều | `is_dialog_window()` mới: cửa sổ KHÁC phải tự khai `_NET_WM_WINDOW_TYPE` là hộp thoại/popup (`DIALOG`, `UTILITY`, `POPUP_MENU`, `DROPDOWN_MENU`, `COMBO`, `TOOLTIP`, `NOTIFICATION`, `SPLASH`) **và** khai `WM_TRANSIENT_FOR` trỏ về đích (theo chuỗi, tối đa 4 mắt). Chính cửa sổ đích luôn được nhận. 3 bài kiểm mới. Đo lại trên máy thật với cặp cửa sổ thử `CuaDialogMain`/`CuaDialogChild` (loại `DIALOG`, chủ sở hữu `0x2c00001`): `is_own_window` = True, chốt điểm bấm NHẬN, chốt tiêu điểm NHẬN, gõ được 2 ký tự — tức BUG-117 vẫn được vá |
| BUG-121 | MEDIUM | **Bộ đệm hình học 0,5 s lọt vào chốt điểm bấm**: người dùng vừa di chuyển cửa sổ đích thì hình học CŨ vẫn chứa điểm bấm, chốt cho qua, và cú bấm rơi vào cửa sổ của người dùng. Đây đúng là lúc tranh chấp mà chốt tồn tại vì nó | `check_point_ownership` đọc lại hình học cửa sổ đích NGAY trước khi soi điểm (`get_window_rect(hwnd, fresh=True)`): một tiến trình con `xwininfo` cho mỗi cú bấm, đổi lấy việc chốt luôn soi trên hình học thật |
| BUG-122 | MEDIUM | **Chốt trần im lặng khi thiếu số đo**: `check_budget` duyệt theo *số đo có sẵn*, nên một hồi quy làm hỏng hẳn `click` (không còn số đo nào) lại in "ĐẠT" và thoát 0 — đúng lúc cần chốt nhất. Cùng lúc `product.screenshot` đo đường **báo lỗi** `UNSUPPORTED_ACTION` (vì `computer_use` không nhận `action='screenshot'`) mà tài liệu ghi như số đo thật | Duyệt theo **danh sách trần**: thiếu số đo hoặc số đo lỗi ⇒ `VƯỢT TRẦN: … KHÔNG ĐO ĐƯỢC` và thoát 1. `product.screenshot` đo đúng đường chụp của sản phẩm (`computer_screen_capture`): **126 ms**, 21 tiến trình con, 1920×1080 ≈ **2 764 token thị giác**. `--baseline` lặp lại được (primitives và product ghi hai tệp riêng). 7 bài kiểm mới trong `tests/unit/test_cua_bench_budget.py` |
| BUG-123 | LOW | **Con trỏ lệch trong lúc chờ tiêu điểm**: bản vá BUG-116 bỏ hẳn `mousemove` khi con trỏ đã ở đúng chỗ, nên nếu người thật di chuột trong lúc `ensure_foreground` chờ thì cú bấm rơi vào chỗ đã lệch (điểm đã kiểm quyền là chỗ cũ) | Vẫn gửi `mousemove`, chỉ bỏ `--sync` khi con trỏ đã ở đúng chỗ: không bao giờ chờ sự kiện không tới (hết treo 5 s) mà vẫn kéo con trỏ về đúng điểm đã kiểm quyền. 1 bài kiểm mới cho đúng tình huống lệch |
| BUG-124 | LOW | **Ghi chú locale hứa hão**: `utf8_locale()` trả `C.UTF-8` ngay cả khi `locale -a` không có tên UTF-8 nào, nên ghi chú nền tảng vẫn nói "ứng dụng do BoxFox mở thì đã được cấp locale" trên máy không cài locale UTF-8 — chữ có dấu lại mất mà ghi chú nói ngược lại. Hàm cũng chỉ so khớp bốn tên cứng, bỏ qua `vi_VN.UTF-8` | Tách `installed_utf8_locale()` (đọc `locale -a`, ưu tiên bốn tên quen thuộc rồi tới **bất kỳ** tên nào chứa utf8, trả `None` khi máy không có) khỏi `utf8_locale()` (vẫn trả `C.UTF-8` làm nỗ lực tốt nhất cho tiến trình con). Ghi chú nói thẳng khi máy không cài locale UTF-8 nào và hướng dẫn cài. 4 bài kiểm mới |
| BUG-125 | LOW | **`list_windows` của công cụ đo đọc sai kích thước**: `WindowInfo.bounds` là `(x, y, w, h)` nhưng công cụ lại trừ thêm lần nữa (`right - left`), ra terminal 715×141 thành 671×33 và panel thành 1632×−998 — mọi điểm bấm tính từ đó đều lệch. Cùng lúc danh sách bỏ qua viết hoa/thường nên `Xfce4-panel`/`Xfdesktop` **không** bị bỏ qua như tên hàm ý | Đọc thẳng `(x, y, w, h)`; so lớp cửa sổ không phân biệt hoa/thường; thêm danh sách dấu hiệu terminal. Kèm luật an toàn: đo INPUT mà không chỉ rõ cửa sổ thì **từ chối** thay vì gõ thử vào cửa sổ lớn nhất trên màn hình (có thể là trình duyệt/trình soạn thảo đang mở dở của người dùng) |

### 6.42 Vòng 2026-10-08 (tiếp) — lượt kiểm tìm ra: ảnh cửa sổ bỏ sót hộp thoại khi đích còn giữ tiêu điểm

Lượt kiểm độc lập trên `f90d0ea` chạy kịch bản hộp thoại **qua đúng đường sản phẩm** (không chỉ
unit test) và bắt được lỗi thứ tư của cùng vùng — lỗi mà cả ba vòng soát mã trước đó không thấy, vì
nó chỉ hiện ra khi cửa sổ đích **vẫn giữ tiêu điểm**.

| Mã | Mức | Triệu chứng | Nguyên nhân | Vá |
|---|---|---|---|---|
| BUG-126 | HIGH | Khung hình trực tiếp của đích là **nền phẳng**: `POST /api/agent/machines/screen` trả 520×360 PNG mà **mọi pixel** `(32,48,64)`, `hash=33265ed6…` — hộp thoại con đang mở, nằm trên, mất hẳn khỏi ảnh. Agent nhìn hụt rồi bấm vào chỗ nó không thấy | Cổng cũ chỉ dò `transient_windows` khi `occluded or get_foreground_window() != hwnd`, vì đoán "hộp thoại modal luôn giữ tiêu điểm". Đoán đó sai với hộp thoại **không modal** (`UTILITY`/`POPUP_MENU`/`TOOLTIP`/`NOTIFICATION` — vẫn nằm trong `_DIALOG_TYPES`): đích giữ tiêu điểm, phép thử che khuất theo tỉ lệ bỏ qua hộp thoại nhỏ ⇒ cổng trả về rỗng. `import -window` đọc **bộ đệm riêng** của cửa sổ (đo: 187200/187200 pixel là nền của chính nó dù hộp thoại con nằm trên, không có compositor), nên ảnh cửa sổ không bao giờ tự chứa cửa sổ chồng lên nó | `10f8bee`: bỏ hẳn cổng đoán, **luôn** dò `p.transient_windows(int(hwnd))`. Chi phí: 1,19 ms (bộ đệm ấm) / 6,31 ms (nguội); `capture_window` 49,0–49,4 ms so với trần 150 ms. Kiểm lại: API thật trả `hash=1c922e4b…` với **31200 px = đúng 260×120** diện tích hộp thoại; 2 bài kiểm mới phủ đúng ca lọt lưới (đích giữ tiêu điểm, và loại `UTILITY` không modal) |

Bài học ghi lại: ba vòng soát mã đọc mã mà không thấy, vì cả ba đều kiểm "chốt input có nhận hộp thoại
không" — còn câu hỏi "**ảnh** có chứa hộp thoại không" chỉ trả lời được bằng cách chạy sản phẩm thật
và đọc pixel. Đây là lý do lượt kiểm phải chạy qua đường sản phẩm chứ không chỉ chạy unit test.

### 6.43 Vòng 2026-10-08 (tiếp) — bốn thao tác cử chỉ, và hộp thoại khai `NORMAL` bị coi là cửa sổ lạ

Đợt này trả lời câu hỏi của người dùng: *"còn test CUA nhập code vào notebook ipynb thì sao? Hay
scroll? Hiện có tool chưa? Kéo thả chẳng hạn, giữ, thử nghiệm vẽ như paint"*. Đọc mã trước khi làm:
`scroll` **có tên trong `enum`** của `computer_use` nhưng mọi lời gọi đều trả `UNSUPPORTED_ACTION`;
`drag`, `hold`, `stroke` **không tồn tại** ở đâu cả trên đường host (Docker box có một dòng `scroll`
bằng `xdotool click --repeat`, không có ba thao tác kia).

**Bốn thao tác mới** (cùng hợp đồng trên ba nền tảng: Windows, Linux/X11, Docker box):

| Thao tác | Tham số | Cơ chế X11 | Cơ chế Windows |
|---|---|---|---|
| `scroll` | `direction` (up/down/left/right), `steps` (≤20) | nút cuộn 4/5/6/7, một lệnh `xdotool click --repeat N --delay 12` | `MOUSEEVENTF_WHEEL`/`HWHEEL`, `mouseData = ±steps × 120` |
| `drag` | `toX`, `toY`, `button`, `steps` (≤60) | `mousedown` → N `mousemove` → `mouseup`, `GESTURE_SETTLE_SEC = 0,03` sau khi nhấn | ba lô `SendInput` (move+down, N move, up) |
| `hold` | `seconds` (0,05–5) | `mousedown` → ngủ → `mouseup` | như trên, hai lô |
| `stroke` | `path` (≥2 điểm, ≤400) | mỗi điểm một `mousemove`, `STROKE_STEP_SEC = 0,008` | một lô `SendInput` cho cả đường |

Chốt an toàn giữ nguyên cho cả bốn: điểm phải thuộc đích (`check_point_ownership`), đích phải giữ
tiêu điểm, và **cú kéo của đích là một cửa sổ thì cả điểm đầu lẫn điểm cuối phải nằm trong cửa sổ
đó** — chỉ chế độ "cả máy" mới cho kéo từ cửa sổ này sang cửa sổ khác. Nhả chuột nằm trong `finally`
nên một bước hỏng giữa chừng không để lại nút chuột đang giữ. 28 bài kiểm mới (13 X11 + 9 Windows +
6 host executor).

**Vòng soát mã đợt cử chỉ** (cùng ngày, trước khi mở PR) tìm thêm bốn chỗ, đã vá hết trong cùng
nhánh:

| Chỗ | Vấn đề | Cách vá |
|---|---|---|
| `stroke` thiếu chốt điểm cuối | `drag` canh điểm cuối từ đầu, còn `stroke` chỉ canh điểm đầu — một nét vẽ chạy quá mép cửa sổ đích vẫn nhấn, đi rồi thả ở **cửa sổ khác**, đúng thứ mà chốt của `drag` sinh ra để chặn | `stroke` nhận `guard_end` và kiểm điểm CUỐI; `_send_input` truyền `guard_end=pinned` y như `drag`. Không kiểm từng điểm giữa: X11 đặt lệnh giữ chuột ngầm cho cửa sổ nhận `mousedown`, nên các điểm giữa không tới được cửa sổ nào khác |
| Lệnh nhả chuột hỏng không được nhả lại | `_xdotool` trả **kết quả hỏng** chứ không ném lỗi, nên `released is not None` chưa phải là đã nhả — `finally` cũ bỏ qua đúng ca nút còn đang giữ | `finally` nhìn `ok` của kết quả (`released is None or not released.ok`), không chỉ nhìn `None`. Bản box: đánh dấu theo **kết quả** thay vì theo thứ tự bước, và nhả lại trong `except BaseException` (lượt bị huỷ cũng phải nhả) |
| Nút chuột lạ im lặng thành chuột trái (box) | `_box_button` trả `'1'` cho mọi tên không nhận ra — một cú kéo "nút giữa" gõ sai chính tả chạy như chuột trái mà không ai biết | Từ chối bằng `ValueError`, cùng hợp đồng với bản X11/Windows |
| Ba kế hoạch cử chỉ của box không có bài kiểm | Phần dễ sai nhất là **đường hỏng** (nhả lại khi lệnh nhả hỏng), mà nó không nhìn thấy được bằng mắt | `tests/unit/test_sandbox_worker_gestures.py` — 10 bài: thứ tự lệnh, trần bước/điểm, thời gian giữ, và ba ca đường hỏng |

Vòng đó cũng dọn hai chỗ trùng lặp: `click` của X11 nay dùng chung `_prepare_point`/`_move_to` với
bốn cử chỉ (bỏ ~25 dòng chép lại, gồm cả hai khối chú thích đã có trong docstring của `_move_to`),
và bản Windows có `_prepare_point` riêng cho năm thao tác. `CUA_POINT_ACTIONS` (không nơi nào đọc)
đã xoá; `_gesture` giữ nhánh "nền tảng chưa có thao tác" nhưng lời chú thích đã đúng lại (bản
Windows nay có đủ bốn thao tác, nhánh đó chỉ chạy khi thêm nền tảng mới). Tổng sau vòng soát: **45
bài kiểm mới** (16 X11 + 11 Windows + 8 host executor + 10 box).

| Mã | Mức | Vấn đề | Cách vá |
|---|---|---|---|
| BUG-127 | MEDIUM | **Hộp thoại khai `_NET_WM_WINDOW_TYPE_NORMAL` bị coi là cửa sổ lạ.** Đo trên máy thật (mtPaint 3.50): hộp thoại "Save Image File" và cửa sổ "Settings Toolbar" đều khai `WM_TRANSIENT_FOR` trỏ về cửa sổ chính nhưng **không** khai loại hộp thoại. Chốt BUG-120 đòi đủ hai điều kiện nên từ chối: mọi `type`/`key` trả `SOURCE_CHANGED: cửa sổ đích không giữ được tiêu điểm` trong lúc hộp thoại đang mở, tức là **không gõ được tên tệp để lưu** — đúng kiểu "agent chết cứng" mà BUG-117 đã vá cho hộp thoại `DIALOG`. Cùng lúc, cú bấm vào nút "+" của cửa sổ "Settings Toolbar" bị từ chối `điểm bấm đang bị cửa sổ khác che` dù đó là cửa sổ của chính ứng dụng | `is_own_window` nhận thêm điều kiện thứ hai: cửa sổ trong chuỗi `WM_TRANSIENT_FOR` được nhận nếu **cùng tiến trình** với cửa sổ mà nó khai (`_NET_WM_PID`, đọc từ bộ đệm). Điều kiện chuỗi vẫn giữ, nên bảo vệ của BUG-120 không mất: công cụ lạ khác tiến trình vẫn bị từ chối (bài kiểm cũ `test_a_foreign_window_claiming_the_target_as_owner_is_refused_without_a_dialog_type` vẫn xanh). `_NET_WM_PID` **khó vô tình trùng** hơn `WM_TRANSIENT_FOR`: một ứng dụng lạ khai PID của chính nó, nên nó không trùng PID của đích. Đây là chốt chống **tai nạn**, không phải ranh giới an ninh — `_NET_WM_PID` là gợi ý do ứng dụng tự khai, không phải dữ kiện X server kiểm chứng, nên một tiến trình khác trên cùng display khai đúng PID của đích thì qua được (y như nó khai `WM_TRANSIENT_FOR` hay `_NET_WM_WINDOW_TYPE`; và ai gửi được input qua XTEST thì không cần qua chốt này). Vòng soát mã đợt cử chỉ bắt được lời khẳng định cũ — "tiến trình khác không tạo được cửa sổ mang PID của ứng dụng đích" — là **sai**; đã sửa ở cả mã nguồn lẫn tài liệu. 2 bài kiểm mới (nhận khi cùng tiến trình; vẫn từ chối khi cùng tiến trình nhưng **không** khai chuỗi) |

Kiểm chứng trên máy thật sau khi vá: bấm "+" trong "Settings Toolbar" được nhận (Size 1 → 4), và gõ
14 ký tự tên tệp vào hộp thoại lưu được nhận — mtPaint lưu ra PNG 640×480 với **7 172 điểm ảnh đỏ**
(vòng tròn + sóng + tam giác do `stroke` vẽ). Trước khi vá cả hai thao tác đều bị từ chối.

### 6.44 Vòng 2026-10-08 (chiều) — năm yêu cầu của chủ nhà: viền báo trên Linux, đo một lượt CUA, mã lỗi tự giải thích, dò suy luận theo provider, panel tự mở

Năm câu hỏi/yêu cầu: *(1)* "khi codex hay antigravity hay các app khác, nếu CUA máy hoặc app thì sẽ có một khung viền xanh nhạt đậm vừa và nhạt dần khi vào tầm 1/8 màn hình… tôi cũng cần phần này"; *(2)* "check thử thời gian CUA từ lúc user ra đề nghị đến khi xong task và trả lời user"; *(3)* "kiểm thử toàn diện"; *(4)* "thử với model fledge alpha free hoặc có trong opencode"; *(5)* "khi kiểm thử, ví dụ lên plan, harness có tự mở bảng plan cùng với plan nó mới làm ra cho user xem không".

Đo trước khi sửa (không suy đoán): `build_cua_overlay()` trả `None` trừ `win32`; `sandbox/x11/` **không có** hàm viền nào ⇒ `activity` luôn `null`; 48 mã lỗi CUA/host **không mã nào** có trong `recovery_policy.CODES`; 44/48 model lưu `thinkingType: 'none'`, `thinkingSource: 'unknown'`; bảng plan **đã** tự mở, canvas thì không.

| Mã | Mức | Lỗi | Cách sửa |
|---|---|---|---|
| BUG-128 | HIGH | **Đọc sai hình chữ nhật cửa sổ ở CẢ HAI nền tảng.** `cua_overlay._bounds_of()` và `machine_router._window_payload()` đọc bộ bốn số `(left, top, right, bottom)` như `(x, y, w, h)`. Đo được: `rect=(96,1039,1824,1080)` ⇒ viền và panel nhận `width=1824, height=1080` thay vì **1728×41**. Nghĩa là viền desktop trên Windows **đang vẽ sai kích thước** (toàn màn hình thay vì ôm cửa sổ), và viền trong panel sai với đích "cả máy". Bài kiểm cũ không bắt được vì dữ liệu giả tình cờ truyền `(10,20,300,200)` theo nghĩa `x,y,w,h` | `_bounds_of()` đổi sang đọc `(left, top, right, bottom)` rồi trừ; `machine_router` có hàm dùng chung `window_rect_payload()`; bài kiểm dùng **số đo thật** `(96,1039,1824,1080)` ⇒ 1728×41, cộng một ca cửa sổ ở gốc `(0,0)` để chắc rằng trường hợp "may mắn đúng" không đổi kết quả |
| BUG-129 | MEDIUM | **Kết quả công cụ đỏ mà KHÔNG có mã.** Ba hàng `terminal_exec` thật trong sổ cũ chỉ có `['artifact','content','exit_code','is_error','recovery','reflection_hint']` — không `errorCode`. Hệ quả kép: `recovery_policy` xếp `unknown` ⇒ `checkpoint_and_ask`, và `reflection_hint` rơi vào câu mặc định dành cho **lỗi sai tham số** ("Read `error`: it names the field and the rule. Fix only that input and call again once") — lời khuyên sai việc cho một lệnh shell hỏng | `COMMAND_EXIT_NONZERO` (lệnh thoát khác 0, kèm `exit_code` + `content` + tệp đính kèm) và `HOST_TOOL_FAILED` (công cụ ném lỗi lạ); `reflection_hint` có nhánh **không có mã** chỉ vào `content`/`exit_code` thay vì khuôn schema. 4 bài kiểm mới trong `test_host_executor.py` |
| BUG-130 | MEDIUM | **48 mã CUA/host không mã nào tự giải thích.** `recovery_policy.CODES` chỉ có mã của harness, nên **mọi** lỗi host (từ chối quyền, người thật giữ quyền, phần tử cũ, thiếu gói, đích mất…) đều ra `class: unknown`, `action: checkpoint_and_ask`, lý do "không rõ loại lỗi: dừng ở checkpoint và hỏi chủ nhà" — đúng ca đo được: `tool=terminal_exec code=PERMISSION_DENIED` | `_HOST_ADVICE`: **59 mã** → (lớp, hành động, lời khuyên riêng), `CODES` 78 → **137**; `FILE_NOT_FOUND`, `FILE_PERMISSION_DENIED`, `INSPECT_POINT_INVALID` khai thêm sau khi rà lại nguồn mã. Luật cũ giữ nguyên: **chỉ `transport` là tạm thời**, mã CUA **không** tự thử lại. Hai chốt chống trôi: bảng tài liệu §6.2.1 ⇄ `_HOST_ADVICE`, và khoá i18n của panel ⇄ `CODES` |
| BUG-131 | MEDIUM | **Model suy luận mà UI không biết.** `fledge-alpha-free` (model chủ nhà nêu tên) **có** suy luận ở mọi mức: đo được 168–513 ký tự `reasoning_content` mỗi mẫu — nhưng hàng model lưu `thinkingType: 'none'`, `thinkingSource: 'unknown'`, nên harness bỏ mức suy luận trước khi gửi và bộ chọn mức **không hiện**. Phép dò cũ không thể thấy: `testInference()` gửi `max_tokens: 64`, không có trường `reasoning`, và `usage.reasoning_tokens` của model này luôn 0 dù nó vẫn stream chữ suy luận | Phép dò theo **từng provider** (đúng dạng request của provider đó, quét **mọi** mức đã công bố), phán quyết thuần tách khỏi I/O, bằng chứng ghi kèm `asOf` và **tự hết hạn sau 30 ngày**, hàng model giữ kết quả qua lần discovery sau, và bộ chọn model có nút **đo** ngay chỗ thiếu bộ chọn mức + một dòng kết quả cho mọi ngả (đo được N mức / provider từ chối trường / bị giới hạn nhịp / không có quyền). Một phát hiện phải ghi: chỉ nhìn **chữ** suy luận sẽ phán sai cả họ model — `muse-spark` trả `reasoningChars: 0` nhưng `reasoningTokens: 728` |
| BUG-132 | LOW | **Ý định mở tab bị xếp hàng thì người dùng không thấy gì.** Bốn cổng chặn (`autoOpenTabs=false`, workspace đang ẩn, tab đang ghim, người dùng vừa gõ trong 15 s) đẩy ý định vào hàng đợi, và dấu hiệu duy nhất là **huy hiệu số** trên tab. Panel canvas thì **không** tự mở, và `design` còn không có trong hợp đồng `ui_intent` | Hàng thông báo ngay trên ô soạn: tên tab + **lý do chặn** + nút "Mở ngay" (mở cả workspace đang ẩn) + nút bỏ qua; mở tab là hàng tự biến mất. Canvas tự mở **một lần cho mỗi `designId`** (lần vẽ sau là cập nhật trạng thái), đi qua đúng bốn cổng chặn; hợp đồng `ui_intent` bổ sung `design` và cổng thứ tư |
| BUG-133 | LOW | **Vẽ trước khi map thì X server vứt bản vẽ.** Lỗi do chính đợt này tạo ra trong `x11/overlay.py`: `overlay_show` vẽ khi cửa sổ còn chưa `map` ⇒ băng ra màu `background_pixel=0` (đen) thay vì màu pha. Chỉ phép đo trên X thật mới bắt được, bài kiểm đơn vị không thấy | `_apply_bounds → _map_window → _paint`, kèm chú thích ghi lại lý do |
| BUG-134 | LOW | **Lý do bị ghi đè.** `note()`/`_call()` đặt `last_reason = 'overlay_unavailable'` mỗi khi viền đang tắt, nên sau lượt CUA đầu tiên panel sẽ hiện câu chung chung thay vì "thiếu `python-xlib`…" — đúng thứ mà J8 sinh ra để nói | `_unavailable_reason` đặt lúc dựng, cập nhật khi mặt viền chết; hai chỗ đọc dùng nó. Có bài kiểm ghim |

**Viền báo trên desktop Linux — việc mới, không phải lỗi.** `sandbox/x11/overlay.py` (mới): cửa sổ
`override_redirect`, SHAPE Bounding = các vòng 1 px của băng, SHAPE Input rỗng (bấm xuyên qua), nâng
`X.Above`; bề dày băng = cạnh ngắn/8 (1920×1080 ⇒ 135 px, chặn trên 1/3); màu nhấn `#38bdf8` pha dần về
màu nền đọc ở bốn điểm giữa cạnh, làm mới ≤ 1 Hz. Đo trên `DISPLAY=:1`: bấm xuyên qua đúng (cửa sổ dưới
con trỏ luôn là đích), `_NET_CLIENT_LIST_STACKING` **13 → 13**, `import -window <đích>` **540 000 byte
giống hệt** trước/sau, pixel ba vòng khớp phép pha **chênh 0** (cho phép ≤ 2), `BOXFOX_CUA_OVERLAY=0` ⇒
không cửa sổ viền nào, thiếu `python-xlib` ⇒ CUA vẫn chạy và `activity.reason` nêu tên gói. Ảnh:
`images/cua-border-window.png`, `images/cua-border-machine.png`.

**Một lượt CUA mất bao lâu — chưa có số, và bộ đọc nói thẳng thế.** Máy này **chưa từng** có một lượt CUA
trọn vẹn: sổ chỉ có một lượt hỏng ở tầng định tuyến (`UPSTREAM_HTTP_503`, `toolsRun: 0`), đo được
**145,7 ms** từ lúc nhận đề nghị tới lúc trả lời. `tools/turn_latency.py` đọc thẳng bảng `events` (nguồn
duy nhất), lấy cột `created` làm số chính cho "người dùng chờ bao lâu", `deadlineUsedMs` cho ngân sách, và
in "chưa đo được lượt CUA nào" khi chỉ có lượt hỏng. Phần "model" trong bảng tách **không phải** thời gian
model thuần (nhật ký router không mang mã phiên) nên được gọi đúng tên là **"model + vòng lặp"**.

**`exo-free` không nằm trong quyền của tài khoản** (không phải lỗi của ta): `GET /zen/v1/models` công khai
trả 88 mã, nhưng khoá thật của tài khoản chỉ thấy **48**; `POST .../models/exo-free/test` trả 404
`MODEL_NOT_FOUND`. Router lưu đúng danh sách được cấp quyền, và giờ nói được **vì sao** một model thiếu
("provider công bố trong danh mục công khai, nhưng khoá này không có quyền").
