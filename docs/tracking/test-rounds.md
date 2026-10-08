# Nhật ký các vòng kiểm thử — BoxFox Agent Box

Mỗi vòng ghi: phạm vi, cách chạy, kết quả, bằng chứng và lỗi tìm được. Số liệu lấy từ lần chạy cuối của vòng đó.

## Vòng 1 — E2E toàn hệ thống (2026-09-19, sáng)

- Phạm vi: 21 case trên UI 3100, harness 3102, router 3101, box 8081; bám theo kế hoạch 6 nhóm (chat, CUA, browser, router, slash command, giao diện hẹp).
- Kết quả: **15 PASS / 8 FAIL / 0 bị chặn**; tổng hợp được **25 lỗi** (BUG-1 … BUG-25).
- Báo cáo đầy đủ: `/code/.generated_artifacts/boxfox-ket-qua-kiem-thu.md` (bản tiếng Việt, 409 dòng).
- Ảnh/ghi hình: `images/06_capture_inline.png`, `images/07_thinking_block_expanded.png`, `images/12_capture_session_order.png`, `images/13_narrow_900.png`, `images/14_narrow_390.png`, `images/16_plan_panel.png`, `images/19_compaction_notice.png`, `recordings/boxfox_e2e_walkthrough_1920.webm`.

## Vòng 2 — xác minh độc lập đợt sửa (2026-09-19, tối)

- Phạm vi: 33 case trên hệ thống thật sau khi router và harness được khởi động lại; kiểm cả tính trung thực của chuỗi suy luận, thứ tự DOM so với SSE, ma trận slash command, nén context hai chiều, ưu tiên `contextWindow`, `/claude-code` thiếu CLI.
- Kết quả: **30 PASS / 1 FAIL / 1 thông tin**; trạng thái chung: PARTIAL.
- Lỗi tìm được: NEW-1 (nút Compact bị cắt ở khung hẹp 900–1100 px), N-1 (`/skill` thiếu mã lỗi), N-2 (`thinkingLevel` sai được lưu nguyên).
- Bằng chứng: `recordings/r2_walkthrough_v3.webm` (78 giây), `images/r2_19_900_compact_clipped.png`, `images/r2_20_1100_compact_clipped.png`, `images/r2_21_390x844.png`, `images/r2_23_rec_sessionF.png`, `images/r2_30_public_preview.png`.
- Ghi chú: không xác minh được "một tác vụ `/claude-code` thật chạy xong" vì box không có CLI và không có thông tin đăng nhập — chỉ xác minh được đường `SETUP_REQUIRED` trung thực cùng một CLI giả để chứng minh phần truyền tham số.

## Vòng 3 — rà soát tích hợp (2026-09-19, tối)

- Phạm vi: đọc mã hai commit đầu của nhánh, tập trung vào khớp hợp đồng giữa bốn luồng viết song song.
- Kết quả: 9 phát hiện — 1 Cao (R-1), 3 Trung bình (R-2, R-3, R-4), 5 Thấp (R-5 … R-9); kèm 4 điểm đã xác nhận đúng.
- Chi tiết: `docs/tracking/findings-round3.md`.

## Vòng 4 — xác minh đợt 4 trên hệ thống thật (2026-09-19, 21:40)

- Phạm vi: luồng quyết định (duyệt / từ chối / hết hạn / dừng khi đang chờ / trả lời hai lần), plan tự mở và duyệt thật, thao tác file qua giao diện so với `ls` trong box, chip transcript, cuộn chat, nút Compact; kèm săn lỗi mới trên toàn hệ thống.
- Kết quả: **PARTIAL PASS** — mọi luồng chạy đúng khi được kiểm, nhưng luật tự mở tab không tất định ở cấu hình mặc định.
- Lỗi mới: B12 (không tất định, Trung bình–Cao), B13, B2c, B4, B6; B7 rút lại (hai quyết định cùng lúc là bất khả vì lượt thứ hai bị chặn 409).
- Chi tiết: `docs/tracking/findings-round4.md`. Ảnh: `images/r4_*.png`.

## Con số kiểm thử đơn vị (sau khi sửa xong cả vòng 3 và vòng 4)

| Bộ | Lệnh | Kết quả |
|---|---|---|
| Router | `cd router && /opt/node24/bin/node --test tests/*.test.mjs` | 63 pass / 0 fail |
| Backend | `.venv/bin/python -m pytest backend/tests -q` | 287 passed, 3 failed, 2 skipped — 3 lỗi là lỗi môi trường có sẵn |
| Container | `.venv/bin/python -m unittest discover -s deploy/docker/tests -p "test_*.py"` | 324 tests OK, exit 0 |
| Frontend | `cd frontend && npx vitest run` | 644 passed, 4 failed — 4 lỗi có sẵn từ trước |
| Kiểu | `cd frontend && npx tsc -b --noEmit` | exit 0 |

Ba lỗi backend có sẵn: hai test CUA/Playwright cần Internet trong khi box tắt mạng theo thiết kế, và `test_terminal_exec_echo` dùng lệnh PowerShell `Write-Output` trên box chỉ có bash.

Bốn lỗi frontend có sẵn: ba test trong `src/components/shell/Sidebar.test.tsx` (jsdom/`dispatchEvent`) và một test trong `src/lib/workspace/index.test.ts` (do tệp `.env.local` cục bộ đặt `VITE_BOX_API_URL=/`).

## Vòng 5 — chứng minh luật tự mở tab ở cấu hình mặc định (2026-09-19, 22:30)

- Phạm vi: sau khi sửa B12, chạy lại đúng kịch bản đã thất bại ở vòng 4, ở cấu hình mặc định (`boxfox_auto_open_tabs` và `boxfox_auto_open_only_when_idle` đều bật).
- Kết quả: **PASS cả hai nhánh**.
  - Nhánh "tự cuộn của agent không gia hạn cửa sổ": 8 đợt cuộn lập trình (đợt cuối cách `ui_intent` 68 ms), người dùng hoàn toàn không thao tác; tab Decisions tự mở **103 ms** sau intent.
  - Nhánh "intent xếp hàng được xả khi hết cửa sổ": intent đến lúc người dùng đang kéo thanh chia panel ⇒ xếp hàng; tab tự mở **14,17 giây** sau thao tác thật cuối cùng.
- Ảnh: `images/r5_B12_scrollproof_end.png`, `images/r5_B12_queueflush3_end.png`.
- Ghi chú: một lần chạy đầu không kết luận được vì phiên đó tạo trước khi khởi động lại harness (chỉ có 15 tool, thiếu `request_approval`) — không phải lỗi sản phẩm.

## Vòng 6 — kiểm chứng độc lập năm lỗi của vòng 4 (2026-09-19, 23:25)

- Phạm vi: kiểm chứng độc lập trên hệ thống thật năm bản sửa của `51f1452` (B12, B13, B2c, B4, B6) cộng sáu phép thử hồi quy đã từng kiểm ở vòng 2. Không sửa mã nguồn (`git status --porcelain` sạch).
- Kết quả: **PASSED toàn bộ**, không ca nào bị chặn.
  - B12a (tự cuộn của agent không gia hạn cửa sổ): `lastUserActivityAt` giữ nguyên 0 qua 6 đợt cuộn; khoảng thời gian `ui_intent` → tab hoạt động = **1 ms** ở ranh giới store (tốt hơn mức 103 ms của vòng 5).
  - B12b (intent trong cửa sổ 15 giây được xếp hàng rồi tự xả): intent ở Δt 6914 ms ⇒ xếp hàng; xả **15002 ms** sau lần gõ thật cuối cùng.
  - B12c (tab ghim không bị cướp): xếp hàng 24 giây trong khi `activeTab` vẫn là `decisions`, huy hiệu `1`; mở tay thì hàng đợi được tiêu thụ.
  - B12d (tắt điều kiện "chỉ mở khi rảnh"): tab mở 7594 ms sau lần gõ cuối, tức trong cửa sổ.
  - B13: đổi route `gemini-3.8-flash` → `claude-sonnet-4-6` kèm `ultrapower` ⇒ **400 `THINKING_LEVEL_UNSUPPORTED`** (thông báo nêu đúng `low/medium/high`), route không đổi, phiên vẫn `completed`, không có sự kiện `error`; model không có mức ⇒ bỏ im lặng, trả 202.
  - B2c: lưới hiện đúng chấm hổ phách "Integrity: Out of scope — unverified" và chấm đỏ "Confidentiality: Secret", dùng chung khoá i18n với thanh công cụ.
  - B4: mỗi lần di chuyển con trỏ trong lúc kéo đều tính là hoạt động; intent đến giữa lúc kéo được xếp hàng và xả **15001 ms** sau lần kéo cuối.
  - B6: tab mở **và** chọn đúng tệp — breadcrumb `workspace > fixtures > vendor` cùng khung xem trước.
  - Hồi quy: thinking stream hiện thông báo đúng; `/compact` ⇒ `compression {8580→3641}` + "Context compaction complete.", phiên `completed`; transcript **0 thẻ lượt ma** (14 sự kiện `user` = 14 tiêu đề lượt, thứ tự DOM tăng dần theo `seq`); Stop khi `awaiting_decision` ⇒ `cancelled`; các route cần quyền trả 403/403/403/404/400 và box control 403; gõ phím thật khi phiên đang bận ⇒ 409 với băng lỗi trong chat và bản nháp được giữ.
- Kiểm tra bộ test đơn vị: mỗi bản sửa đều có test khẳng định đúng hành vi đã sửa (`uiStore.autoopen.test.ts` 18 ca, `ChatPanel.scroll.test.tsx` 13 ca, `Resizer.activity.test.tsx` 6 ca, `useWorkspaceFiles.test.tsx` 15 ca, `ExplorerGrid.labels.test.tsx` 4 ca, `test_turn_route_thinking_level.py` 8 ca) — không có lỗ hổng.
- Ảnh: `images/r6_b12a_plan_tab_after_burst.png`, `images/r6_b12c_pinned_plan_queue_badge.png`, `images/r6_b6_files_intent_opened.png`, `images/r6_b2c_grid_card_zoom.png`, `images/r6_r5_inline_error_busy.png`, `images/r6_public_preview_files_panel.png`, `images/r6_public_preview_transcript_compact.png`, `images/r6_final_clean_state.png`. Video: `recordings/r6_walkthrough.webm` (283,7 giây).
- Ghi chú nhỏ (không chặn): dạng cây và huy hiệu vẫn in chuỗi tiếng Việt cứng từ `lib/labels.ts` trong khi tiêu đề chấm đã theo i18n — đây là chia tách có từ trước, bản sửa B2c làm lưới khớp với thanh công cụ. Lệnh `agent-browser record stop` lại treo (lần thứ hai), phải diệt daemon rồi ghép lại bằng `ffmpeg -c copy`.

## Vòng 7 — dựng lại ảnh container (2026-09-19, 23:30)

- Việc còn nợ "Nợ-1" đã xong: `cd deploy/docker && docker compose build` → `agentbox-sandbox:latest`, manifest `sha256:cf06992844d6d335e76333a8bba02e6d29643347c910662b592383818bdac2de`.
- Kiểm chứng: `docker run --rm --entrypoint sha256sum agentbox-sandbox:latest /usr/local/bin/{ide-proxy,plan_files,workspace_files}.py` cho hash trùng khớp với tệp trong repo (`a7a83b02…`, `de901085…`, `fc391ce1…`). Bản triển khai mới vì thế mang sẵn các endpoint ghi mà không cần chép tay như trên container đang chạy.

## Vòng 8 — đo lại lỗi lặp văn bản và câu lỗi vô nghĩa (2026-09-20, 04:5x)

Bối cảnh: chủ sở hữu báo (a) hội thoại dài thi thoảng hiện `Agent run failed`, (b) file markdown
sub-agent trả về lặp khối văn bản, (c) plan không có cơ chế verify.

**Trước khi sửa** (harness sống `:3102`, tiến trình khởi động 2026-09-19 22:28:32, mã cũ):
đo theo cùng một cách — đếm delta, tổng độ dài delta, độ dài văn bản cuối:

| Lượt | Số delta | Tổng độ dài delta | Văn bản cuối | Tỷ lệ |
|---|---|---|---|---|
| Lượt chính (đọc README, tóm tắt 60 dòng) | 75 | 353 457 | 9 297 | **38,0** |
| Lượt con (giao việc research) | 28 | 44 165 | 3 198 | **13,8** |

Chuỗi tiền tố đúng (`prefix_chain: true`) ⇒ mỗi delta là toàn bộ văn bản tới lúc đó. Đây chính là
nguyên nhân file `.md` chủ sở hữu dán tay bị lặp. Bằng chứng: `r7_delta_repro.json`,
`r7_delta_repro_events.json`.

**Sau khi sửa** (bản sao cô lập trên `:3112`, cây mã tại `51ecba6`; đúng cách đo):

| Lượt | Số delta | Tổng độ dài delta | Văn bản cuối | Tỷ lệ | Ghép delta == văn bản cuối |
|---|---|---|---|---|---|
| Lượt chính (cùng dạng lệnh) | 42 | 4 689 | 4 689 | **1,0** | Có |
| Lượt giao việc research | 42 | 3 829 | 3 829 | **1,0** | Có |

Kết quả phụ lấy từ cùng lượt giao việc: sự kiện `child` của chuyên gia `research` **completed**,
câu trả lời bị chặn trần còn 8 075 ký tự kèm `truncated: true` (trước đây không có trần).
Bằng chứng: `r7_delta_after_fix.json`.

**Câu lỗi**: session trỏ vào connection không tồn tại trả về
`code='UPSTREAM_HTTP_503'`, `message='UPSTREAM_HTTP_503: the model router answered Router HTTP 503
(No enabled, authorized model is available for this route.)'` — không còn chuỗi trần
`Agent run failed`.

**Nhật ký hệ thống**: bản sao cô lập ghi 48 dòng trong `/var/tmp/r7-verify/logs/harness.jsonl`;
`summary` cho thấy 8 `turn.start`, 5 `turn.end`, 4 `model.error`, 3 `turn.failed`, 25 `tool.end`
(p50 73 ms, max 27 046 ms), mã lỗi `UPSTREAM_HTTP_503 ×2`, `MAX_STEPS ×1`.

**Bộ test**: backend `3 failed / 349 passed / 2 skipped` — ba lỗi có sẵn từ trước (hai ca CUA cần
Internet, một ca dùng `Write-Output` của PowerShell trên box bash). Router `node --test` 83 pass.
Frontend 653 pass / 4 lỗi có sẵn (3 × `Sidebar.test.tsx`, 1 × `workspace/index.test.ts` do
`.env.local` cục bộ).

## Vòng 9 — kiểm chứng sống sau khi khởi động lại dịch vụ (2026-09-20, 04:5x)

Khác vòng 8: lần này **chính hai tiến trình dùng chung** (`:3102` harness, `:3101` router) đã được khởi động lại trên cây mã hiện tại, nên mọi kết quả dưới đây là hành vi thật của bản đang chạy.

| Việc | Cách đo | Kết quả |
|---|---|---|
| Văn bản phát lại (BUG-26) | `measure_deltas.py 3102 turn` | 66 delta, tổng 7 892 ký tự, văn bản cuối 7 892 ký tự → **tỷ lệ 1,0**, `joined_equals_final: true`; các delta liền nhau đều là **hậu tố**, không delta nào gửi lại phần đã có |
| Câu lỗi vô nghĩa (BUG-27) | `check_live.py 3102` | `code='UPSTREAM_HTTP_503'`, `message='UPSTREAM_HTTP_503: the model router answered Router HTTP 503 (No enabled, authorized model is available for this route.)'` — không còn chuỗi trần |
| Anthropic ingress (BUG-30, phần router) | `curl -N POST :3101/v1/messages` | 33 event SSE đúng chuỗi `message_start → content_block_delta → message_delta → message_stop`, **không có `[DONE]`**; `count_tokens` → `{"input_tokens": 7}`; thiếu khoá → `{"type":"error","error":{"type":"authentication_error",…}}` |
| Máy chủ bridge (BUG-30, phần box) | cấu hình | vẫn **tắt mặc định**; cần `BOX_LLM_BRIDGE=on` + `BOXFOX_ROUTER_BRIDGE_HOST` và một lần tạo lại container — chưa xác minh sống trên container thật |

Tệp bằng chứng: `/code/.generated_artifacts/r8_delta_live_3102.json`, `/code/.generated_artifacts/r8_anthropic_stream_live.sse`, `/code/.generated_artifacts/r8_anthropic_count_tokens.json`. Mọi phiên tạo ra để đo đã được xoá.

## Vòng 10 — trả lời soát mã đợt 8 (2026-09-20, 05:0x–05:2x)

Bảy lỗi của vòng soát mã được sửa trong `16eedda`; hai phát hiện còn lại xử lý bằng ghi chú (xem
`bug-register.md` §6.3).

**Bộ test sau khi sửa** (đều chạy trên cây `16eedda`):

| Bộ | Lệnh | Kết quả |
|---|---|---|
| Backend | `.venv/bin/python -m pytest backend/tests -q` | **361 passed, 2 failed, 2 skipped** — hai lỗi có sẵn: một ca CUA cần Internet, một ca dùng `Write-Output` của PowerShell trên box bash. Lỗi thứ ba của vòng 9 (`test_cua_inspect_element_and_double_click`) nay **đã qua** |
| Router | `npm test` (từ `router/`) | **84 / 84 pass** — bộ test nay tự trỏ log vào thư mục tạm (`tests/isolate-logs.mjs`), nhật ký thật của người vận hành không bị ghi thêm |
| Frontend | `npx vitest run` | **666 passed, 4 failed** — bốn lỗi có sẵn từ trước (3 × `Sidebar.test.tsx` dưới jsdom, 1 × `workspace/index.test.ts` do `frontend/.env.local` cục bộ) |
| Kiểu | `npx tsc -b --noEmit` | exit 0 |
| Docker | `python3 -m unittest discover -s deploy/docker/tests -p "test_*.py"` | **336 OK** |

**Ca mới của vòng này**: `test_stream_delta_events.py` (+1, lượt gọi thứ hai sau khi stream dở),
`HarnessStepView.notice.test.tsx` (2), `SubagentInspectorPanel.stream.test.tsx` (+2),
`test_harness_port_override.py` (4), `test_failure_classification.py` (+1),
`anthropic-ingress.test.mjs` (thay ca khoá hành vi mất mát bằng 2 khẳng định mới).

**Kiểm ngược** (đã chạy, tắt bản sửa thì ca tương ứng đỏ): bỏ nhánh `reset` trong
`HarnessStepView.tsx`; bỏ cổng `BRIDGE_PATHS` ở cầu nối.


## Vòng 11 — đóng hai lỗi CUA còn nợ của đợt 7 (F5, F6) — 2026-09-20, 06:2x–06:5x

Hai lỗi này từng bị hoãn vì "cần chủ dự án quyết"; đợt này chốt phương án **không bỏ**
tính năng tự khớp cỡ của noVNC (`Xvnc -AcceptSetDesktopSize` là thứ giữ cho noVNC dùng
được trong cửa sổ nhỏ), thay vào đó đặt **sàn** kích thước và thêm bước chọn tab theo
trạng thái hiển thị. Cam kết: `65039ae`.

**Bộ test sau khi sửa:**

| Bộ | Lệnh | Kết quả |
|---|---|---|
| Backend | `.venv/bin/python -m pytest backend/tests -q` | **373 passed, 2 failed, 2 skipped** — hai lỗi có sẵn như vòng 10 |
| Docker | `python3 -m unittest discover -s deploy/docker/tests -p "test_*.py"` | **350 OK** |

**Ca mới của vòng này**: `test_sandbox_worker_desktop_floor.py` (7),
`test_sandbox_executor_desktop_note.py` (5, gồm cả nhánh chuyển tiếp ghi chú trong
`computer_screen_capture`), `DesktopFloorTest` (6), `VisibleTargetTest` (6),
`SafeTabListTest` (2) trong `deploy/docker/tests/test_inspect_element.py`.

**Kiểm ngược** (đã chạy, tắt bản sửa thì ca tương ứng đỏ): bỏ bước chọn theo
`visibilityState` trong `_select_target` (3 ca đỏ); cho `worker.ensure_desktop_size()`
trả `None` ngay (2 ca đỏ); bỏ vòng chuyển tiếp `desktopRestored`/`desktopWarning`
trong `executor._execute` (1 ca đỏ).

**Đo sống trong box**: trước khi sửa, `POST /__box/inspect-element` tại `(640,300)`
trả `reason: ambiguous_target` với **34 tab** cùng tiêu đề `vi.wikipedia.org`; sau khi
sửa, cùng toạ độ đó trả `{"type":"dom","selector":"#main-content","tag":"div"}`.
Kéo desktop xuống `286x311` rồi lần lượt gọi ba cửa vào (`/__box/capture`,
`computer_use click`, `/__box/inspect-element`): cả ba trả `1280x800` và
`desktopRestored {'from': '286x311', 'to': '1280x800'}`; nhật ký DEV ghi
`box.desktop_restored` kèm `sessionId` và `tool`.

Ghi chú vận hành: ba tệp `deploy/docker/{browser_capture,inspect_element,capture}.py`
đã được chép tay vào container đang chạy để kiểm chứng (rồi khởi động lại `ide-proxy`);
lần tạo lại container kế tiếp sẽ lấy đúng các tệp trong kho.

## Vòng 12 — đóng nốt hai lỗi của vòng 9, mở công cụ web ở host, chạy `/claude-code` thật — 2026-09-20, 07:1x–07:5x

Bối cảnh: chủ sở hữu chốt bốn quyết định (`#5811` công cụ web ở tầng host, `#5812` được phép build
lại image, `#5813` setup đánh giá nhưng chưa chạy, `#5814` nhật ký hệ thống v2 trong giao diện).
Vòng này làm đúng bốn việc đó, cộng hai lỗi mà vòng kiểm chứng độc lập đợt 9 để lại.

### Việc đã làm trong vòng này

| Việc | Nội dung | Bằng chứng |
|---|---|---|
| F6b | `deploy/docker/capture.py` gọi `.decode()` lên đầu ra `str` của `_run_as_agent()` ⇒ nhánh đặt lại màn hình thất bại ném `AttributeError`, `/__box/capture` trả HTTP 500 thay vì ảnh kèm `desktopWarning` | `_output_text()` nhận cả `str` lẫn `bytes`; `test_inspect_element.py` +3 ca (`DesktopFloorTest`) |
| F8 | `xdotool mousemove --sync` treo 15,16 s khi con trỏ đã ở đúng toạ độ ⇒ lần bấm thứ hai cùng chỗ báo hết giờ, đốt 20/20 bước của lượt CUA nặng đợt 7 | `_pointer_move()` bỏ `--sync` và tự thăm dò bằng `getmouselocation`; `test_sandbox_worker_pointer.py` (5 ca) |
| N-5 | Công cụ tra cứu mạng cho agent, chạy ở **host** (box không có Internet) | `agent_core/web.py` (`web_search`, `web_fetch`), 30 ca trong `test_web_tools.py`, ghi chú đo đạc `docs/research/host-web-tools.md` |
| Việc 5 v2 | Nhật ký hệ thống: API chỉ-đọc, vòng đời "ghi khi chạy, reset khi tắt", bảng trong giao diện | `test_system_log_v2.py` (16), `router/tests/system-log-lifecycle.test.mjs` (4), `deploy/docker/tests/test_ide_proxy_system_log.py` (6), `frontend/src/components/panels/SystemLogPanel.test.tsx` (12) + `App.tabs.test.tsx` (4) |
| Việc 3+4 | Bộ khung đánh giá chạy khô, có cổng chặn chi tiêu hai yếu tố | `scripts/eval/` (9 mô-đun) + `backend/tests/unit/test_eval_setup.py` (52 ca) |
| F9 | Con của lệnh nhận mặc định 180 giây ⇒ phiên 600 giây vẫn `DEADLINE` ở lượt `/claude-code` | `_command_task` truyền ngân sách của phiên; `test_skill_commands.py::test_command_child_inherits_the_session_time_budget` |
| F10 | CLI tự chọn `claude-opus-5[1m]` khi thiếu `ANTHROPIC_MODEL` ⇒ lượt chết ngay vì router không có model đó | `router_config()` lấy model sonnet/haiku đã cấu hình; 2 ca trong `test_claude_worker_router.py` |
| Ghi chú | Lỗi nhà cung cấp bị nuốt thành "Claude Code task failed" | executor đọc thêm khoá `text`; `test_claude_executor.py::test_the_provider_reason_survives_an_error_result` |

### Bằng chứng sống

- **Công cụ web**: `SEARCH web -> 3 kết quả` (firecrawl không cần khoá), `SEARCH wikipedia (vi) -> 3`,
  `SEARCH papers -> 2` (có DOI), `FETCH https://docs.python.org/3/library/asyncio-task.html` →
  `200`, tiêu đề thật, `chars 43995`, `truncated True`; SSRF chặn cả `http://127.0.0.1:3101/...` lẫn
  `http://169.254.169.254/latest/meta-data/` bằng `WEB_URL_FORBIDDEN`.
- **Box không có Internet** (đo lại): `iptables -S OUTPUT` = `DROP` rồi `REJECT`; chỉ loopback và
  bốn cổng dịch vụ 5900/6080/8080/8081 đi được — đây là lý do công cụ web phải chạy ở host.
- **Image đã build lại**: ba mô-đun trong `/usr/local/bin` của container trùng byte với repo
  (`76a64c41…` capture, `13da3416…` browser_capture, `127ec2b1…` inspect_element);
  `POST /__box/capture` → `200`, 1280×800.
- **`/claude-code`**: `probe` trả `status: ready`, `auth: router`, `baseUrl: http://172.18.0.1:3101`,
  `settingsFile: true`; lượt thật chạy CLI trong box, request đi qua cầu nối tới router và **tới
  nhà cung cấp**, nhưng nhà cung cấp trả **429** (`anthropic.failed RATE_LIMIT` trong
  `~/BoxFox/logs/router.jsonl`), nên lượt dừng ở `TURN_FAILED_VALUEERROR` với đúng câu lỗi của
  nhà cung cấp. Đây là hạn mức của tài khoản, không phải lỗi mã.
- **Nhật ký hệ thống**: `?lines=99999` → `lines=500` (trần cứng), `?level=trace` → 400, thiếu header
  admin → 403, `commit=58598c1`; tắt êm tạo `~/BoxFox/logs/harness.previous.jsonl` thật.
- **Đánh giá**: `run_eval.py` chạy khô exit 0 (108 lượt model, 6,44–23,60 USD); `--execute` luôn
  thoát mã 3/5 và không có đường nào tới model khi chưa bật cổng chi tiêu.

### Tổng số ca kiểm thử sau vòng này

| Bộ | Kết quả |
|---|---|
| Backend | **488 passed, 2 failed, 2 skipped** (trước khi sửa tám phát hiện của vòng soát mã: 479/2; ca `test_eval_setup.py` đỏ vì cây sạch nay đã xanh) — hai ca đỏ còn lại là hai ca cũ có điều kiện môi trường: `test_cua_element_selector.py` cần Internet, `test_terminal_tools.py::test_terminal_exec_echo` dùng builtin PowerShell trên box bash |
| `deploy/docker` | **359 OK** |
| Router | **89 pass / 0 fail** |
| Frontend | **682 passed / 4 failed** — bốn ca cũ (`Sidebar.test.tsx` ×3 dưới jsdom, `lib/workspace/index.test.ts` ×1 vì `frontend/.env.local` cục bộ); `tsc -b --noEmit` thoát 0 |

### Vòng 12 (tiếp) — sửa bảy phát hiện của vòng soát mã đợt 10 — 2026-09-20, 08:0x

Vòng soát mã độc lập đọc `58598c1..95076b5` và kết luận **APPROVE WITH COMMENTS**, rủi ro **3/10**,
với tám phát hiện (ba TB, ba Thấp, hai nit). Bảy phát hiện cần sửa đã sửa trong đợt này; một phát hiện
mức ghi chú được ghi nhận thành rủi ro có tên trong tài liệu thiết kế. Chi tiết từng phát hiện ở
`docs/tracking/bug-register.md` §6.6.

| Việc | Nội dung | Bằng chứng |
|---|---|---|
| R10-1 | Nhánh lỗi của công cụ web ghi nguyên câu có truy vấn và URL vào nhật ký DEV (`tool.error` lẫn `web.error`) | `WebError.log_message` + `failures.log_safe_failure()`; ca mới khẳng định truy vấn và chuỗi truy vấn trong URL đều KHÔNG có trong `harness.jsonl` |
| R10-2 | SOP của vai gốc nói "there is NO web-search tool" trong khi cùng request quảng cáo `web_search`/`web_fetch` | ca mới khoá hai vế lại (quyền trong `ORCHESTRATOR_TOOLS` ⊂ câu chữ SOP) |
| R10-3 | Ca kiểm `pins['repo']['dirty'] is True` đỏ trên cây sạch | ca cũ chỉ khẳng định kiểu/được đo; ca mới dựng repo tạm để kiểm cả cây sạch lẫn cây bẩn |
| R10-4 | `reset --file all` đổi tên luôn tệp previous thành `*.previous.previous.jsonl` | ca CLI mới: chỉ còn đúng một tệp previous, và nó là lần chạy vừa kết thúc |
| R10-5 | Nhà cung cấp trả 200 với thân không phải JSON làm đứt chuỗi tìm kiếm | ca mới: nhà cung cấp đầu trả trang chặn, nhà cung cấp sau vẫn được gọi và kết quả thật được trả về |
| R10-6 | `web_fetch` là kênh GET ra ngoài (chiều rò ra khi trang bị tiêm nhiễm) | ghi nhận thành dòng "Rủi ro còn lại: kênh ra" trong `docs/research/host-web-tools.md` §3, kèm cách siết |
| R10-7 | Phép so khớp con trỏ dùng tiền tố nên `X=64` khớp `X=640` | ca mới: đích (64, 3) gặp con trỏ (640, 300) không được coi là tới nơi |
| R10-8 | README của `scripts/eval` ghi "hai biến" nhưng liệt kê bốn | sửa câu chữ |

Tổng số ca sau khi sửa: backend **488 passed, 2 failed, 2 skipped** (+9 ca so với 479 của vòng 12, và ca đỏ vì cây sạch đã xanh);
`deploy/docker` **359 OK**; router **89 pass / 0 fail**; frontend **682 passed / 4 failed**; `tsc` thoát 0.

### Vòng 12 (tiếp) — gỡ nút chặn 1 MiB cho nhiệm vụ CUA nặng — 2026-09-20, 08:3x–09:5x

Ca T21 (nhiệm vụ nặng để mô hình tự chọn chụp màn hình) của vòng kiểm chứng độc lập đợt 10 chết với
`UPSTREAM_HTTP_413: Request is too large.`. Đây là **lỗi có sẵn**, không nằm trong diff của vòng 10,
nhưng nó chặn đúng hạng mục "CUA nhẹ → nặng" của chủ sở hữu, nên được sửa trong ba lớp — mỗi lớp đo
được trên các phiên thật trong `~/BoxFox/harness/sessions.sqlite`.

| Lớp | Việc | Đo trên phiên thật |
|---|---|---|
| 1 — `fa57325` | `runtime.bound_inline_media()`: giữ ảnh của 2 lần chụp mới nhất và tối đa 512 KB trong thân request; ảnh cũ rút về phần chữ kèm đường dẫn tệp. Transcript trong store không đổi | Phiên 1 119 229 B → **307 948 B** (bỏ 7 ảnh); 1 107 429 → **303 055** (6 ảnh); 1 090 982 → **259 986** (8 ảnh); 1 813 206 → **674 074** (8 ảnh) |
| 2 — `6991b17` | `runtime.dedupe_thought_signatures()`: cặp `thought_signature` + `thoughtSignature` của Gemini chỉ còn một khoá trong bản gửi đi | Cặp chữ ký chiếm **761 888 B** ở phiên nặng nhất, 380 944 B ở phiên 1,8 MB; sau lượt này thân đã nằm dưới trần |
| 3 — `344ce0f`, `1a2c…` | `runtime.shrink_request_to_budget(body, messages)`: lượt rút cuối, đo **cả thân request** (prompt vai + lược đồ công cụ) chứ không chỉ `messages`; khi vượt ngân sách **900 KB** thì hạ theo thứ tự ít mất mát nhất — chữ cũ → `thought` cũ → tham số `tool_calls` cũ (giữ `id` + tên công cụ) → 1 ảnh mới nhất → không ảnh nào — dừng ngay khi vừa, ghi `model.request_trimmed` kèm `phase` | Lượt đo lại trên phiên `584d61c8` (ca chết ở bước 25) chứng minh lớp 3 bản đầu **không đủ**: nó chỉ đo `messages` (1 043 364 B) trong khi thân thật là 1 060 902 B — vẫn quá trần 12 326 B. Sau bản sửa: **1 754 163 → 850 965 B**, phase `media-1`; cả năm phiên lớn còn lại đều dưới trần |

Cả năm phiên lớn nhất đo được đều nằm dưới trần 1 048 576 B sau ba lớp. Ca kiểm thử ở
`backend/tests/unit/test_inline_media_bound.py` — **19 ca** (6 ca lớp 1, 3 ca lớp 2, 10 ca lớp 3),
gồm ca khẳng định danh sách gốc không bao giờ bị sửa, ca khẳng định thân request dưới ngân sách
được trả nguyên, ca khẳng định phép đo tính **cả** prompt vai và lược đồ công cụ, ca tái hiện
hình dạng thật của phiên chết vì 413, và ca nhiệm vụ 30 bước liên tục chụp màn hình mà thân request
vẫn luôn dưới trần. Chi tiết ở `docs/tracking/bug-register.md` §6.7.

Một trần nữa lộ ra khi chạy lại ca T21 trên `a78246a`: lượt chết với `CONTEXT_LIMIT: summary failed`
chứ không còn 413. Nguyên nhân: `estimate_tokens` tính **toàn bộ ảnh base64 như chữ**, nên phiên
`08f2483c` bị ước lượng **1 051 631** token trong khi router chỉ báo **358 771** token đầu vào cho
cùng request; `before` vượt `context_window - output_reserve` nên khi lượt tóm tắt gặp 429/90 giây,
bộ nén đi vào nhánh duy nhất làm chết lượt. Nay mỗi ảnh inline được tính bằng
`IMAGE_TOKEN_ALLOWANCE = 1600` (đúng cách nhà cung cấp tính token ảnh), nên cùng phiên đó ước lượng
còn **952 417** — dưới ngưỡng chết, lượt tiếp tục với bản gốc thay vì dừng. Ca kiểm thử mới ở
`backend/tests/unit/test_context_estimate.py` (4 ca).

Lớp thứ tư (commit `14a5935`) mở nốt chỗ chết cuối cùng: nhiệm vụ CUA chỉ có một lời nhắc nên
`compact()` không có lượt cũ nào để nén (`cut = 1`), trong khi lượt tóm tắt bị đẩy cả lịch sử ~900 KB
vào nhà cung cấp. Nay `compact()` gộp chính phần giữa nhiệm vụ (giữ tiền tố hệ thống, lời nhắc và 10
tin nhắn mới nhất), đầu vào tóm tắt do `summarizer_material()` làm phẳng và chặn ở 120 000 ký tự, và
phép tỉa một ảnh chụp giữ phần chữ thay vì cắt nát chính ảnh mới nhất. **Diễn lại phiên thật
`9ec9bf1d`**: `beforeEstimate 1075446 → afterEstimate 314771`, đầu vào tóm tắt còn **15 397 ký tự**.

Hai phát hiện đo được nữa (commit `d0adf36`, ghi ở §6.7 mục F-1f/F-1g): ước lượng ngữ cảnh đếm **hai
lần** cùng một chữ ký suy luận — cùng hai phiên trên nay còn **576 592** và **509 005** token, tức
dưới ngưỡng nén 697 132 nên nhiệm vụ nặng không còn bị nén sớm; và `_drop_oldest_round()` không còn
kéo tin nhắn trong đuôi đang chạy vào tập bị bỏ.

Tổng số ca sau các lớp này: backend **519 passed, 2 failed, 2 skipped** — hai ca đỏ vẫn là hai ca cũ
có điều kiện môi trường. `deploy/docker` **359 OK**; router **89 pass / 0 fail**; frontend
**682 passed / 4 failed**; `tsc` thoát 0.

### Điều vòng này CHƯA làm được

- Chưa có câu trả lời thật từ `/claude-code` vì hạn mức nhà cung cấp (429); cầu nối và CLI đã đúng.
- Cổng mở cầu nối (luật `iptables` trong box + biến `BOXFOX_ANTHROPIC_*` của harness) vẫn làm bằng
  tay, `BOX_LLM_BRIDGE` trong `docker-compose.yml` còn `off` — người dùng phải mở/đặt lại sau mỗi
  lần tạo container.

### Vòng 13 — 2026-09-20 chiều (OpenRouter/DeepSeek Pro, mức thinking, chính sách thử lại)

Chủ sở hữu giao bốn việc lúc 14:28 UTC kèm hai ảnh chụp (`3066.png`, `3067.png`).

**Đã đo được**

- Nhập khoá API OpenRouter **bằng giao diện** (ô API key + `Refresh model`): kết nối
  `7b469e10-1d00-4358-a854-5c42ef5e93b3` ở `https://openrouter.ai/api/v1`, `discoveryState ready`,
  **446 model**, `lastModelSyncAt 2026-09-20T14:29:27Z`. Nút `Test` cho
  `~deepseek/deepseek-pro-latest`: **`Passed` 5 300 ms**, 17 token, `cost 2.28e-05`.
- Lượt chạy thật đầu tiên trên DeepSeek Pro (trước khi sửa frontend) đã **hoàn tất trong 4,0 s**
  (phiên `36b3fc5c…`, 19 sự kiện, `assistant {"text":"4"}`, `finish completed`) — tức nhà cung cấp
  và router đều tốt; lỗi nằm ở mức thinking do giao diện gửi lên.
- **Lỗi mức thinking tái hiện và đã sửa** (§6.8 T-1): `POST /api/agent/sessions` với
  `thinkingLevel: 'medium'` trả `THINKING_LEVEL_UNSUPPORTED: model publishes max/high/low`. Sau khi
  sửa, chạy lại **qua giao diện**: chip `DeepSeek Low`, phiên `c7cb1e8f…` lưu
  `route.thinkingLevel = "low"`, lượt trả `assistant {"text":"2+2 = 4.","thought":"…"}`,
  `finish {"status":"completed"}`, `step {"iteration":1,"contextEstimate":6220}`.
- **Lỗi `Not found` đã sửa** (§6.8 T-2): trên harness mới, `GET`, `POST …/turns`, `POST …/stop` với
  id `deadbeef…` đều trả **404 `SESSION_NOT_FOUND`** kèm chính id; bản cũ trả `{"error": "Not found"}`.
- **Chính sách thử lại** (§6.8 R-1): 13 ca mới trong `backend/tests/unit/test_retry_policy.py`,
  gồm ba ca chạy lượt thật (hai 429 rồi thành công; bỏ cuộc sau 3 lần; 400 hỏng ngay).
- Khoá API Google nhập lúc 14:50 UTC: kết nối `2b922915-4b9e-430d-a867-cb76e47e6965`
  (`https://generativelanguage.googleapis.com/v1beta`), `discoveryState ready`, **41 model**, trong đó
  **có `gemini-3.5-flash-lite`** — nút `Test` trả **`Passed` 600 ms** (12 token). Vậy model này
  **không thiếu**.

**Bộ kiểm sau khi sửa**

| Bộ | Kết quả |
|---|---|
| backend `pytest backend/tests -q` | **532 passed, 2 failed, 2 skipped** (77,30 s) — hai ca đỏ vẫn là hai ca cũ phụ thuộc môi trường: `test_browser_use_navigation_and_dom_inspection` (`ERR_CONNECTION_REFUSED`) và `test_terminal_exec_echo` (`Write-Output: command not found`) |
| `deploy/docker` unittest discover | **359 OK** |
| router `npm test` | **89 pass / 0 fail** (3 176 ms) |
| frontend (hai tệp mới) | `harnessThinking.test.ts` 9 ca + `harnessChatStore.retry.test.ts` 5 ca — **14 passed** |
| frontend `npx tsc -b --noEmit` | thoát **0** |
| frontend toàn bộ | 682 passed / 4 failed — bốn ca đỏ có sẵn từ trước (3 × `Sidebar.test.tsx`, 1 × `workspace/index.test.ts`) |

**Còn nợ của vòng này**: thang kiểm CUA (nhẹ → vừa → nặng có kịch bản → nặng tự do) chạy bằng
`~deepseek/deepseek-pro-latest` và bằng `gemini-3.5-flash-lite`; kết quả bổ sung vào đây khi có.

### Vòng 14 — 2026-09-20 chiều muộn (khoá Google, thang kiểm `gemini-3.5-flash-lite`, tám phát hiện của vòng soát)

**Việc chủ sở hữu giao**: nhập khoá Google, kiểm model `gemini-3.5-flash-lite` có trong danh mục
không, rồi chạy thang CUA hiện tại bằng model đó; mỗi lỗi phải phân loại **model hay mã** trước khi
kết luận, lỗi do model thì ghi vào sổ theo dõi, và nếu thang kiểm chết vì hạn mức nhà cung cấp thì
dừng và báo lại.

**Đo được**

- Khoá Google nhập lúc 14:50 UTC → kết nối `2b922915-4b9e-430d-a867-cb76e47e6965`, `discoveryState ready`,
  **41 model**, `gemini-3.5-flash-lite` **có mặt** (mức `low/medium/high`, cửa sổ 1 048 576), nút `Test`
  trả **`Passed` 600 ms**. Lượt gửi thật đầu tiên qua giao diện trên model này **hoàn tất** (`Chào bạn! BoxFox
  đã sẵn sàng…`, `finish completed`, tuyến `{"connectionId":"2b922915…","modelId":"gemini-3.5-flash-lite","thinkingLevel":"low"}`).
- Tám phát hiện của vòng soát mã đợt 13 (điểm rủi ro **5/10**) đã sửa hết — chi tiết ở §6.9 bảng R14-1…R14-8.
  Hai phát hiện đầu được **đo lại sống** trên giao diện đang chạy:
  - Xoá phiên của một chat rồi gửi ngay trong cùng một nhịp: `DELETE /api/agent/sessions/18358f20…` → 200,
    `POST /api/agent/sessions/18358f20…/turns` → **404**, `POST /api/agent/sessions` → phiên mới,
    `POST /api/agent/sessions/e197d82a…/turns` → câu trả lời. Sau khi phiên mới ra đời **không lời gọi nào**
    trỏ về id chết, khoá `boxfox-harness-session:session-mu9yhydm` mang id mới, màn hình **không còn băng đỏ**
    (`r14_stale_recovery_after.png`; ảnh trước khi sửa: `r14_stale_before.png`).
  - Nhánh còn lại (vòng poll nhận ra trước): chat được dọn im lặng rồi lần gửi kế tiếp mở phiên mới
    (`r14_stale_purge_after.png`).
- **Lỗi mới T-3 (§6.9)**: lượt gửi thật trên `Google Gemini · Gemini 2.5 Flash` chết với
  `UPSTREAM_HTTP_400 … Thinking level is not supported for this model.` Đo trực tiếp trên endpoint Google
  (12 model) để biết model nào nhận `thinkingLevel`: **nhận** — `gemini-flash-lite-latest`, `gemini-3.1-flash-lite`,
  `gemini-3.5-flash-lite`, `gemini-3.8-flash`; **từ chối** — `gemini-2.5-flash`, `gemini-2.5-flash-lite`,
  `gemma-4-31b-it`, `gemini-3.5-transcribe`, `antigravity-preview-09-2026`, `deep-research-preview-04-2026`.
  Sau khi sửa, đo lại trên harness dựng từ nhánh (cổng 3103, phiên `9c2571c3…`, tuyến
  `gemini-2.5-flash` + `thinkingLevel: "medium"`): `notice THINKING_LEVEL_REFUSED` (`level: "medium"`) rồi
  `assistant "2+2 bằng 4."`, `finish completed`, **không có sự kiện `error`**
  (`/code/.generated_artifacts/r14_thinking_level_refused_live.txt`).
- Đo lại **trên giao diện thật** (cổng 3102, sau khi dựng lại harness lúc 15:46 vì tiến trình cũ nạp mã đợt 13):
  cùng khung chat `gemini-2.5-flash` + mức `low`, lượt 15:45 chết `UPSTREAM_HTTP_400 … Thinking level is not supported`
  (không có thông báo bỏ mức), lượt 15:47 phát `notice THINKING_LEVEL_REFUSED {level:"low"}` rồi trả lời
  `2+2=4. 5+7=12.` với `finish completed` và **không** sự kiện `error`
  (`/code/.generated_artifacts/images/r14_thinking_refused_ui_after.png` — hai lượt nằm trong cùng một ảnh).
- Chính sách thử lại chạy thật trong thang kiểm: phiên `51bd6a0b…` gặp hạn mức nhà cung cấp và ghi đúng
  ba thông báo `UPSTREAM_RETRY` (`attempt 1..3`, `waitMs 2000`, `reason rate-limit`) rồi
  `UPSTREAM_RETRY_EXHAUSTED` (`attempts 3`, `waitMs 6000`), băng lỗi cuối có `[after 3 retries in 6.0s]`.

**Bộ kiểm sau khi sửa**

| Bộ | Kết quả |
|---|---|
| backend `pytest backend/tests -q` | **540 passed, 2 failed, 2 skipped** (77,41 s) — hai ca đỏ vẫn là hai ca cũ phụ thuộc môi trường |
| frontend trọng tâm (`harnessThinking`, `harnessChatStore.retry`, `routerChatOptions`, `ChatPanel`) | **35 passed** |
| frontend toàn bộ `npx vitest run` (91 tệp) | **704 passed, 4 failed** — đúng bốn ca cũ phụ thuộc môi trường (3 × `Sidebar.test.tsx`, 1 × `workspace/index.test.ts`); số ca qua tăng từ 682 lên 704 nhờ 22 ca mới |
| frontend `npx tsc -b --noEmit` | thoát **0** |
| ESLint trên các tệp đã sửa | không thêm phát hiện nào (một `no-explicit-any` còn lại trong tệp kiểm có từ trước) |

**Chặn của vòng này**: OpenRouter hết credit (`total_credits: 0`) nên thang DeepSeek Pro **không chạy
được** — lượt 2 chết ở `UPSTREAM_HTTP_402`; chủ sở hữu đã được báo. Các model `gemini-3.8-flash-*` qua
antigravity cũng đang bị hạn mức (`remainingFraction 0`, mở lại 2026-09-23T10:30:01Z).

**Thang kiểm đợt 14 trên `gemini-3.5-flash-lite`** (mức `medium`, `maxSteps 30`, hạn 600 s, do tác nhân
kiểm thử chạy trên harness đang chạy mã nhánh):

| Bậc | Phiên | Bước | Công cụ | Kết quả và phán loại |
|---|---|---|---|---|
| Rất nhẹ (một lần chụp) | `e37d4d79…` | 2 | `computer_screen_capture` ×1 | **hoàn tất**, trả lời đúng `1280x800` — không lỗi |
| Nhẹ (chữ, 3 lệnh terminal) | `8ceb062c…` | 2 | `terminal_exec` ×1 | **hoàn tất** |
| Vừa (kịch bản 4 bước, ảnh sau mỗi bước) | `f7e18f44…` | 5 | `computer_use` ×4 + `computer_screen_capture` ×4 | **hoàn tất**, 0 lỗi công cụ |
| Nặng (nhiều bước, ảnh sau mỗi hành động) | `51bd6a0b…` | 29/30 | `computer_use` ×13 + `computer_screen_capture` ×13 | **chết ở bước 27 vì hạn mức nhà cung cấp**: `UPSTREAM_HTTP_429` → `UPSTREAM_RETRY` 1/3, 2/3, 3/3 (`waitMs 2000`) → `UPSTREAM_RETRY_EXHAUSTED` (`attempts 3`, `waitMs 6000`) |
| Nặng không kịch bản | — | — | — | **không chạy**: luật dừng khi thang kiểm chết vì hạn mức nhà cung cấp |

**Phán loại model hay mã**: cả bậc chết đều **do nhà cung cấp**, không do model yếu và không do mã —
lượt nặng bám đúng kịch bản (`click(15,780)` Application, `click(60,778)` Accessories, ảnh sau mỗi hành
động, 0 lỗi công cụ) rồi mới bị hạn mức cắt ngang; trong cả lượt **0 lần** `UPSTREAM_HTTP_413`,
`CONTEXT_LIMIT`, `THINKING_LEVEL_UNSUPPORTED`, không có sự kiện lạc hay kết quả công cụ sai. Chính sách
thử lại mới hành xử đúng như thiết kế (3 lần rồi dừng, có ghi `attempt`/`waitMs`/`reason`).

**Thang DeepSeek Pro** (chạy trước đó cùng ngày, kết quả để đối chiếu): bậc chụp ảnh **thất bại ngay**
hai lần với `UPSTREAM_HTTP_404: No endpoints found that support image input` — model record của
`~deepseek/deepseek-pro-latest` không có endpoint thị giác, nên đây là **hạn chế của model**, đã ghi để
theo dõi; bậc chữ và bậc vừa **hoàn tất**; bậc nặng lượt 1 chạm `MAX_STEPS` (30 bước, 389,6 s), lượt 2–3
chết vì `UPSTREAM_HTTP_402` (số dư OpenRouter bằng 0).

**Đo lại bốn lỗi chạy sống của các vòng trước trên mã cuối** (tác nhân kiểm thử, hai bản ghi):
`/code/.generated_artifacts/recordings/r13_four_checks_live_walkthrough.mp4` (F6b nhánh khôi phục desktop
lỗi vẫn trả HTTP 200 kèm ảnh thật + `desktopWarning`, F8 hai lần bấm 0,109/0,108 s không `--sync`, F9 con
`/plan` mang `deadlineSeconds 600`, F10 `ANTHROPIC_MODEL` theo router và `grep -ric opus` = 0) và
`/code/.generated_artifacts/recordings/r13_f6b_record_route_output.mp4` (chính tuyến ghi hình trả nội dung
desktop thật trên nhánh lỗi).

### Vòng 15 — 2026-09-20 tối: khoá DeepSeek gốc (API chính chủ)

**Yêu cầu của chủ sở hữu (17:42):** lắp khoá API DeepSeek, **test các model**, **các mức độ response**,
**tra cứu tài liệu cho đúng**, **ping thử các model**, rồi **dùng model DeepSeek 4 Flash để hoàn thiện nốt
phần kiểm thử còn lại** (bậc nặng-không-kịch-bản của thang CUA, thứ mà các vòng trước không chạy được vì
hạn mức Google và vì DeepSeek Pro trên OpenRouter không có endpoint thị giác).

**Lắp đặt:** kết nối `deepseek` id `7ee21256-8675-4ee3-a802-fcedbed8b7ef`, endpoint
`https://api.deepseek.com/v1`, số dư **2,00 USD**, hai model `deepseek-flash` (DeepSeek-V4.1-Flash) và
`deepseek-v4-pro` (DeepSeek-V4-Pro-0813). Chi tiết đo, lỗi T-5 (router kế thừa bộ mức của OpenAI) và cách
sửa nằm ở `bug-register.md` §6.11.

**Số ca sau khi sửa**

| Bộ | Kết quả |
|---|---|
| Router | **98 pass / 0 fail** (91 cũ + 7 ca `tests/deepseek.test.mjs`) |
| Router, riêng tệp mới | 7/7 đạt |

**Phép dò sống (17:52–17:58), tất cả qua router thật**

| Phép đo | Kết quả |
|---|---|
| Nút `Test` cho `deepseek-flash` / `deepseek-v4-pro` | `passed` / `passed` |
| Quét mức qua `/api/router/chat` (đường harness) | `none` → 0 ký tự suy luận; `low`/`high`/`max` → có suy luận, `reasoning_tokens` 10–19; thiếu mức → mặc định nhà cung cấp |
| `/v1/models` bằng khoá box | hai model DeepSeek hiện diện |
| `/v1/chat/completions` | `low`, `none`, `max` đều 200; `none` không có `reasoning_content` |
| Ảnh 16×16 qua router | `deepseek-flash` → "Red" (đúng); `deepseek-v4-pro` → "Brown" (sai, đã ghi `vision: unsupported`) |
| Giao diện | `Single Models` hiện `DeepSeek · deepseek-flash` và `DeepSeek · deepseek-v4-pro` |
| Harness, phiên `5803c1a8…` | mức `high` → `reasoning_tokens: 8` và đáp đúng `3293`; mức `none` → không có token suy luận và đáp đúng `2993` |

Ảnh bằng chứng: `/code/.generated_artifacts/images/r15_deepseek_in_picker.png` (bộ chọn model trong giao
diện với hai model DeepSeek). Bằng chứng thô của phiên harness: `/var/tmp/r15/harness_probe_session.json`.

#### Bậc nặng-không-kịch-bản trên `deepseek-flash` — **PASSED** (18:0x)

Đây là bậc mà các vòng 12–14 không chạy nổi (hạn mức Google, DeepSeek Pro trên OpenRouter không có
endpoint thị giác). Phiên `63fa894d84af46cca41d7e77616800b4`, tuyến lưu trong config
`{7ee21256-…, deepseek-flash, high}`, `contextWindow 64000` (bảng tên), `maxSteps 40`,
`deadlineSeconds 600`.

| Phép kiểm | Kết quả |
|---|---|
| T1 cấu hình phiên | PASS — `thinkingLevels none/low/high/max`, `defaultThinking high`, `vision reported` |
| T2 đi đúng tuyến | PASS — **34/34** dòng usage trỏ đúng kết nối/model DeepSeek; nhật ký router 34 `chat.end`, 0 lỗi |
| T3 hoàn thành nhiệm vụ | PASS — `finish {"status":"completed"}`, **34 bước**, 5930 sự kiện, **78 s** |
| T4 ảnh vào được model | PASS — 2 thông điệp công cụ có phần `image_url` (~104,9 KB mỗi ảnh), 27 dòng `model.media_pruned`, **không** 413, không "No endpoints found that support image input" |
| T5 quét lỗi vận chuyển/ngữ cảnh | PASS — mọi cờ đều false (`UPSTREAM_HTTP_413`, `CONTEXT_LIMIT`, `Request is too large`, `UPSTREAM_HTTP_429`, `UPSTREAM_HTTP_402`, `balance`, `cooling down`, `MAX_STEPS`, `DEADLINE`, `No endpoints…`, `UPSTREAM_HTTP_404`), `errors`/`notices`/`toolErrors` rỗng, chuỗi sự kiện liền mạch 33212→39141 |
| T6 đọc lại bản ghi trong giao diện | PASS — đầu/cuối bản ghi có nhãn `deepseek-flash · 05:58 PM · done · ↑14,6k ↓1,2k` và dòng `Context compacted: 42276 → 21424 tokens` |
| T7 đối chứng thực địa | PASS — Thunar mở `/home/agent/workspace/` + Mousepad mở `cua_task_log.txt`, `ls -la` → **401 byte** |

Trộn công cụ: `computer_screen_capture` 15, `computer_use` 16 (click/gõ thật), `inspect_element` 2,
`terminal_exec` 1. Tổng usage: `prompt 352 591`, `completion 7 506`, `reasoning 3 578`,
cache hit 306 304 / cache miss 46 287.

Bằng chứng: `/code/.generated_artifacts/r15_ladder_deepseek_flash.json` (5930 sự kiện, 34 dòng usage,
khối cờ đều false, 15 ảnh chụp trong phiên),
`/code/.generated_artifacts/recordings/r15_deepseek_flash_cua_mission.mp4` (163,5 s hình desktop),
`/code/.generated_artifacts/recordings/r15_ui_deepseek_transcript.webm` (37,4 s, 374 khung hình),
`/code/.generated_artifacts/images/r15_deepseek_flash_transcript_top.png` và
`…_transcript_footer.png`. Tác nhân kiểm thử không tìm thấy lỗi sản phẩm nào và không sửa tệp nào trong
kho.

**Ghi chú của bậc này (không phải lỗi):** chỉ **2** ảnh chụp mới nhất còn nằm trong ngữ cảnh
(`bound_inline_media` keep=2); con số "768 byte" mà model đọc giữa luồng là tệp đang được ghi dở; thước
ngữ cảnh trong giao diện hiện `21,4k / 200k` trong khi metadata phiên ghi `contextWindow 64000` (lệch
do thước ước lượng phía giao diện, chỉ là hiển thị).

### Vòng 15b + 16 — 2026-09-20 18:2x: cơ chế nhập tay của DeepSeek, nhà cung cấp bên thứ ba (TokenHarbor), và sự thật về chi phí

**Yêu cầu của chủ sở hữu (18:2x):** (1) DeepSeek phải có **cả hai** cơ chế như các model khác — dò tự động
và **nhập tay** — và **`max` phải có cho riêng DeepSeek**; (2) sau khi verify email xong thì **dùng nhà cung
cấp API bên thứ ba (TokenHarbor)** trước, **lỗi nhiều mới quay lại DeepSeek gốc**, còn không thì chạy
DeepSeek **qua** nhà cung cấp đó; (3) đừng quên việc **đơn giản hoá giao diện khu API**.

**Phần 1 — cơ chế nhập tay (đã sửa, `87bc2d6`).** Hai lỗi độc lập, chi tiết ở `bug-register.md` §6.12:
router tự bịa danh sách mức chung cho model nhập tay (thiếu `none`/`max`), và biểu mẫu "Custom Model" của
giao diện **chưa từng tới router** (gửi bản sao mảng `models`, router trả
`INVALID_REQUEST: Select only models discovered for this connection.`). Sửa: hook `manualThinkingLevels()`
do adapter của nhà cung cấp công bố, hàm `manualThinkingLevels(provider)` ở `service.mjs`, và biểu mẫu gửi
`customModel` thay vì `models`. **Bộ router: 100 pass / 0 fail.**

Đo lại sống trên router đã dựng lại (pid 940356):

| Phép đo | Kết quả |
|---|---|
| Hàng nhập tay cũ `r15-manual-probe` (tạo trước khi sửa) | tự lành thành `['none','low','high','max']` |
| Hàng nhập tay mới trên kết nối DeepSeek | `['none','low','high','max']` — **có `max`** |
| Hàng nhập tay trên kết nối `custom` (TokenHarbor) | `['auto','low','medium','high']` — luật chung giữ nguyên |

**Phần 2 — nhà cung cấp bên thứ ba.** Kết nối `custom` id `6c498e9d-f581-455c-849c-e24c37f25ae5`, tên
`TokenHarbor`, endpoint `https://tokenharbor.ai/v1`. Trước khi verify email, cả `/v1/models` lẫn
`/v1/chat/completions` trả **403** `email_verification_required`, và router đã phơi đúng thông điệp của nhà
cung cấp (`Provider authentication failed: Verify your email address to use the API. …`). Sau khi chủ sở
hữu verify:

| Phép đo | Kết quả |
|---|---|
| `GET /v1/models` | **200, 52 model**; bản ghi có `label`, `blurb`, `tier`, `pricing`, `supports_prompt_cache`, `context_length` |
| Số dư gói trả tiền | **0 USD** — `deepseek-v4.1-flash` trả **402** `balance_zero` ("Top up at https://tokenharbor.ai/dashboard") |
| Model miễn phí `deepseek-v4.1-flash:free` | **200**, có `reasoning_content` |
| Bậc văn bản qua harness (3 lệnh `terminal_exec`) | **`completed` sau 75 s**, 2 lượt gọi model, usage `cached_tokens: 4096` |
| Mức `reasoning_effort` qua cổng | `absent`/`none`/`low`/`high`/`max` đều 200; **`none` KHÔNG tắt suy luận** qua cổng (khác API gốc); `bogus` cũng 200 (cổng bỏ qua, không 422) |
| Độ trễ mỗi lượt gọi | **18–64 s** cho một câu hỏi tầm thường (API gốc: ~1–3 s) |

Nghĩa là: TokenHarbor **dùng được** (đường ống đầy đủ đã chạy) nhưng chỉ với các id `:free`, và **điều
khiển suy luận không đáng tin qua cổng** — đúng loại khác biệt phải ghi vào bản ghi chứ không sửa vào mã.

**Phần 3 — chi phí (đo được, đầu vào cho kế hoạch vòng 16).** `router/src/engine.mjs` chỉ ghi `cost` khi
nhà cung cấp tự báo (`reportedCost(usage)`). Trên 200 dòng usage đang lưu: OpenRouter **45/50** dòng có
`cost`, DeepSeek **0/61**, Google **0/79**, nội bộ `router` **0/10**. Vì vậy phần lớn dòng hiện "No data"
dù request đã tiêu tiền thật. Đây là cơ sở cho kế hoạch ba tầng giá (nhà cung cấp báo > giá công bố trong
`/models` > bảng giá tài liệu của DeepSeek > bảng người dùng tự đặt).

**Bậc nặng-không-kịch-bản trên cổng bên thứ ba — THẤT BẠI (18:52, phiên `bb0c66e24f68446fb5152b3e7739dcc2`).**
Cùng nhiệm vụ tự do mà `deepseek-flash` gốc làm xong trong **78 s / 34 bước**, chạy qua
`deepseek-v4.1-flash:free` của TokenHarbor với `maxSteps 40`: 13–14 bước trong **10 phút**, **4 lần**
`model.error` `UPSTREAM_HTTP_502` (`Router HTTP 502 — Provider is unavailable or returned an invalid
response.`), rồi `turn.failed` với **`DEADLINE: the turn ran out of time before an answer was produced`**
(`durationMs 600011,9` — hạn của **lượt** là 600 s, không phải 1800 s khai lúc tạo phiên). Tổng usage của
lượt: `prompt 39 635`, `completion 1 577`, cache đọc 28 800 — **7/7 dòng không có `cost`** như dự đoán.
Theo luật của chủ sở hữu ("lỗi nhiều mới quay lại DeepSeek"), **việc nặng ở lại khoá DeepSeek gốc**; cổng
bên thứ ba giữ vai trò đường nhẹ/vừa và là ví dụ sống cho luồng "custom API" của kế hoạch vòng 17.

### Vòng 16–17 — 2026-09-20 tối muộn: kế hoạch khu API/Provider được duyệt và thi công

**Kế hoạch.** Ba tác nhân soạn thảo (một thiết kế + hai kế hoạch) rồi gộp thành **một** kế hoạch duy nhất
`/code/.plans/v1-api-provider-area.md` (867 dòng, kèm `v1-api-provider-area-summary.md`, 14 bản vẽ HTML và
`designs/design-plan.json` 10 mục — mỗi mục đúng một biến thể được chọn). Chủ sở hữu **đã duyệt**. Ba phần:
(1) tự nhập endpoint bên thứ ba có nút Test, (2) chi phí ba tầng có nguồn, (3) nén khu Provider.

**Đã thi công (năm nhánh song song/serial, mỗi nhánh tự chạy kiểm thử)**

| Commit | Nội dung | Đo được |
|---|---|---|
| `320f5c1` | Phân loại lỗi dò cho endpoint bên thứ ba (`NO_MODEL_LIST` / `NO_MODELS` / `AUTH` / `UNAVAILABLE`, giữ nguyên văn lời nhà cung cấp), `costMode` + `lastDiscoveryAttemptAt`, id gõ tay lưu nguyên văn, test được model chưa bật; module giá thuần `pricing.mjs` | Router **134 / 0** (13 ca `custom-provider`, 21 ca `pricing`) |
| `574a5aa` | Nối giá vào kết nối/model (ba tầng: manual > ping > documented), ghi `cost` + `costBasis` + `estimated` vào usage, sửa hai lỗi C/D ở §6.13, cập nhật `CONTRACT.md` + `README.md` | Router **152 / 0** (14 ca `cost.test.mjs`, 4 fixture dữ liệu thật) |
| `2b87163` | Giao diện: rail provider có tìm kiếm + nhóm, thẻ connection nén, hàng model 28 px, probe không chặn form | 28 ca nhóm lõi; frontend **717 / 4** (4 ca đỏ có sẵn) |
| `8fa0104` | `CustomModelForm` dùng chung có **Add & Test** và nút Test riêng; khối lỗi dò có cấu trúc với `Retry` / `Add model by hand` / `Edit endpoint & key`; sửa huy hiệu `health === 'error'` chết thành `'failed'` | 34 ca nhóm lõi; frontend **726 / 4** |
| `b998129` | Cột Cost hiện nguồn (`est.`, `No price`, `Included in plan`), KPI đếm nguồn, khối `Price` trong khung chi tiết model có `Edit price` / `Clear override`, rail dùng chung cho tab Router | 21 ca nhóm lõi; frontend **733 / 4**; `tsc` 0 |

**Bằng chứng sống của vòng này** (ảnh trong `/code/.generated_artifacts/images/`): `r17_api_tab_1440x900.png`,
`r17_api_tab_no_connection_1440x900.png` (tab API khi chưa có connection: **296 px**, trước ≈ 1 220 px),
`r17_api_tab_900px_mobile_rail.png`, `r17_custom_endpoint_failed_card.png` (đủ ba nút + câu của nhà cung cấp),
`r17_custom_endpoint_add_and_test.png`, `r17_custom_endpoint_add_and_test_running.png`,
`r17_usage_cost_column.png` (một dòng `<$0.0001 est.`, các dòng `No price`, hai dòng `Included in plan`),
`r17_usage_manual_estimate.png`, `r17_model_price_editor.png`, `r17_model_price_saved.png`,
`r17_public_preview_custom_endpoint.png`. Đo mật độ ở 1440×900: trang **không** dài thêm vì danh sách provider
(0 px), rail tự cuộn, 47 provider trong **2** cú bấm, thẻ connection 237 px (không kể khối model).

**Hai chỗ kế hoạch tự mâu thuẫn, đã chốt bằng số đo:** chỉ tiêu "12 hàng provider thấy được" không đạt vì tab
API chỉ có 2 nhóm (nhóm thứ ba thuộc tab Router) — thấy 8 hàng + 2 tiêu đề; và chỉ tiêu "hai thẻ × 8 model
≤ 716 px" mâu thuẫn với yêu cầu hàng model luôn hiện (điều kiện để có nút Test cạnh mỗi model) — chọn giữ hàng
luôn hiện, thẻ 237 px không kể khối model. Ngoài ra nhánh giao diện tự sửa hai lỗi đo được: rail cao hơn
khoảng trống 14 px (`lg:max-h-[calc(100vh-13rem)]` → `-15rem`) và hàng `Show N more` là disclosure một chiều.

### Vòng 17b — kiểm chứng độc lập khu API/Provider, ba lỗi nhập tay và lần sửa

**Lượt kiểm chứng thứ nhất** (tác nhân kiểm thử, `f63f82b`): bốn làn sống A–D trên router `:3101`, harness `:3102`,
Vite `:3100`, cùng một stub OpenAI-compatible trên `127.0.0.1:3199` (chế độ `ok/404/403/empty/html` cho `/models`,
`ok/404/403` cho chat) và bộ ghi request `/var/tmp/r17/stub-records.jsonl`.

| Làn | Đo được |
|---|---|
| A — vào cổng bên thứ ba | TokenHarbor refresh thật **200**, `ready`, 58 model (52 dò được + 6 dòng gõ tay sống sót); bốn lớp lỗi `NO_MODEL_LIST` / `AUTH` / `NO_MODELS` / `UNAVAILABLE` hiện **nguyên văn**; id gửi lên trùng từng ký tự (`matchesKnownExact: true`); probe chạy được trên dòng đã tắt; biên 400/404 |
| B — chi phí ba tầng | `reported` thắng và **không** ước lượng nào lọt khung `/v1/*`; giá tay sống qua refresh và thắng giá ping; `clear:true` trả giá documented; lượt sống DeepSeek `0,000683` (kỳ vọng `0,00068325`), lượt giá tay `0,00061` (kỳ vọng `0,0006102`) |
| C — giao diện Provider | 1440×900: trang **không** cuộn, hàng model **28 px**, rail 240 + pane 1 152; ba lối thoát đủ; lưu/`Clear override` đúng; `est.` / `No price` / `Included in plan` đúng; 1200/1024/900 px không tràn; bản ghi `r17_provider_walkthrough.webm` (317,6 s) |
| D — hồi quy | Router **152 / 0**; frontend **734 / 4** (bộ đỏ có sẵn); `tsc` 0; `deploy/docker` **359 OK** |

Lượt đó cũng so chín mockup của bản vẽ với ảnh chụp thật và ghi sáu sai lệch có chủ đích (hai tab dùng chung rail;
hộp tìm kiếm thay bộ lọc hình phễu; pill `ready` thay `custom / 1 endpoint`; `Base URL` chỉ có ở kết nối `custom`;
nút gửi `Add & Test` thay `Add & Enable`; không có dải kết quả sau refresh). Hạng mục **bị chặn** duy nhất: một dòng
usage `included` **mới** — Antigravity trả 429 và chỉ đặt lại lúc `2026-09-23T10:30:01Z`; bằng chứng thay thế là
module giá gọi trực tiếp (`included_returns: null`, `included_documented_returns: null`), tám dòng ledger Antigravity
có sẵn đều `cost: null`, và câu `Included in the plan — this provider does not bill per token.` trên giao diện.

**Ba lỗi tìm ra (F1/F2/F3) và lần sửa `91647e7`.** Chi tiết cơ chế ở `bug-register.md` §6.14. Tóm tắt số đo:
gõ lại một id đã có chỉ đổi được `name`; **một** lần `Refresh models` hỏng đưa id vừa Test đạt từ `200 BOXFOX_OK`
xuống `503 NO_ROUTE`; và một lần Test đạt làm mất khối `Models could not be listed` cùng ba lối thoát.
Năm ca hồi quy mới: `tests 3 / pass 0 / fail 3` (router) và `2 failed | 8 passed` (giao diện) trên mã **trước** khi
sửa; router **155 / 0**, frontend **736 / 4**, `tsc` 0 sau khi sửa.

**Lượt kiểm chứng thứ hai** (dựng lại router trên `91647e7`, cùng stub): F1 **ĐẠT** (cờ đảo đúng, một dòng, id mới
cùng cờ cho cùng bộ trường), F2 **ĐẠT** (`degraded` → `/v1/chat/completions` **200 `BOXFOX_OK`**, 40/5 token, có
dòng ledger; `GET /v1/models` **63** mục), F3 **ĐẠT** ở cả hai dạng (`failed` + lỗi, và `failed` + `error: null`).
Các làn đã đạt trước đó không đổi: bốn lớp lỗi vẫn nguyên văn, guardrail probe nguyên, ba tầng chi phí nguyên
(ping `0,000012`; reported `0,000123` `estimated:false`; manual `0,00005`; `clear` → ping trở lại; lượt sống
DeepSeek 32/8 → `0,00001`), dòng gõ tay sống qua refresh thành công, thẻ connection ở 1440×900 vẫn
`doc.scrollH 900 == clientH 900`. Dọn dẹp: năm kết nối tạm xoá, khoá router tạm thu hồi, stub tắt, không còn giá
tay; còn **7 dòng usage `r17/*` mồ côi** trong ledger (kết nối đã xoá, chỉ là số liệu phân tích).

### Vòng 17c — soát mã độc lập vòng 17 và năm lỗi nó tìm ra (`2a0075c`)

Vòng soát chỉ đọc trên `bff9f3d..91647e7` (bộ router 155/155, `src/components/settings` 38/38 xanh). Bảy phát hiện,
chi tiết cơ chế ở `bug-register.md` §6.15: token ghi cache bị tính hai lần (`0,01055` so với số thật `0,00785` — chỗ
**duy nhất** trong bộ thay đổi ghi ra một con số tiền sai), `capabilities` ghi một từ vựng thứ năm (`supported`) mà
không trình đọc nào biết nên ô Vision tự tích không hiện bằng chứng, khối `Models could not be listed` hiện cho cả
lỗi không phải lỗi dò danh sách, cảnh báo ngày lễ thiếu ở tooltip và tài liệu, bộ lọc Free đọc hình dạng giá cũ,
lần Test hỏng chỉ còn báo bằng màu. Câu hỏi sản phẩm còn lại — connection thuê bao có được ghi cost do chính nhà
cung cấp báo không — chốt theo hướng **ghi và hiển thị**: miễn trừ `included` chỉ áp cho phép ước lượng của ta.
Sáu ca kiểm thử được viết/thêm và **đều đỏ trên mã trước khi sửa**: dựng hàng Anthropic qua `normalizeUsage()` thật
(`not ok 107`, `pass 154 / fail 1`), cặp `included` + cost tự báo, từ vựng `capabilities`, hai ca thẻ không được nói
sai về danh sách model, bộ lọc Free hai chiều, và `title` của ô độ trễ.

**Đo lại trên `2a0075c` sau khi sửa** (tác nhân kiểm thử, tám hạng mục, tất cả ĐẠT): mô-đun trước/sau cho đúng cặp
`0,01055 → 0,00785`; một lượt chạy qua stub lưu `cost 0,001429` (miss 189) thay vì `0,001564`, và sau `clear:true`
dòng mới là `cost null / basis null` còn dòng cũ giữ `manual`; khai `{vision:true, reasoning:false}` cho
`vision 'reported'` và huy hiệu **Vision Supported** hiện được trong trình quản lý (trước đó không đường nào tới);
connection `ready` + `error` chỉ còn **một dòng đỏ** của router — `Models could not be listed`, `Last attempt:`,
`Retry`, `Add model by hand` đều vắng (đọc DOM), còn `degraded` (refresh 404, giữ 5 model) và `failed` vẫn đủ khối
ba lối thoát; tab Free liệt kê đúng dòng giá 0 và `Enable Free` chỉ bật `['r17/stub-free-1']`; bốn ô `est.` của
DeepSeek mang nguyên văn cảnh báo ngày lễ; `title` của ô độ trễ đọc `Failed · failed · HTTP 403 · 2 ms · …`.
Bộ kiểm thử: router **156 / 0**, frontend **739 / 4** (đúng bộ đỏ có sẵn), `tsc` mã 0. Dọn dẹp: hai kết nối tạm xoá,
khoá tạm thu hồi, stub tắt, không còn giá tay; ledger tăng đúng **2 dòng mồ côi** (`r17/cache-money`) → **16 dòng
`r17/*` mồ côi** tổng cộng (kết nối đã xoá, chỉ là số liệu phân tích).

## Vòng 18 — chín yêu cầu của chủ sở hữu, ba nhánh C/D/E (2026-09-21)

Kế hoạch được duyệt: *"Một lượt trợ lý gọn theo nhóm, màn Máy tự nối lại, công tắc bảng Workspace, và hai tab
Settings có thật"* (`plan_id` 1223, 15 bản vẽ thiết kế). Ba nhánh: **C** — cửa sổ ngữ cảnh có nguồn và bản ghi màn
hình xem được (yêu cầu 1, 9); **D** — một lượt trợ lý đọc gọn hơn (yêu cầu 4, 5, 6); **E** — màn Máy tự nối lại,
công tắc bảng Workspace, hai tab Settings, số đo điểm ảnh (yêu cầu 2, 3, 7, 8). Việc chốt mã: `fc51864`.

### Số ca kiểm thử trước và sau

| Bộ | Trước vòng 18 | Sau vòng 18 | Đỏ còn lại |
| --- | --- | --- | --- |
| Router (`/opt/node24/bin/npm test`) | 156 ca (155 đạt, **1 đỏ** do ca phụ thuộc ngày) | **176 ca / 176 đạt / 0 đỏ** | không |
| Harness (`backend/tests/unit`) | 544 ca (540 đạt, 2 đỏ, 2 bỏ qua — đo cả cây) | **561 ca / 560 đạt / 1 đỏ** | `test_terminal_tools.py::test_terminal_exec_echo` (có sẵn; cần PowerShell/TTY) |
| Giao diện (`npx vitest run`) | 743 ca / 94 tệp (739 đạt, 4 đỏ) | **885 ca / 111 tệp / 881 đạt / 4 đỏ** | 3 ca `components/shell/Sidebar.test.tsx` + 1 ca `lib/workspace/index.test.ts` (có sẵn) |
| Kiểu (`tsc -b --noEmit`) | 0 lỗi | **0 lỗi** | — |

### Vì sao "cửa sổ ngữ cảnh" là lỗi thật (chi tiết ở `bug-register.md` §6.16)

Ba tầng cùng đoán theo tên nên cùng một câu hỏi có ba câu trả lời khác nhau; số 64 000 mà giao diện in còn mang nhãn
`est.` nên trông như đã có nguồn. Sau khi sửa, một bảng duy nhất ở router và một nhãn nguồn đi cùng mọi con số. Số đo
sống và phép lành phiên cũ ở §6.16 và ở mục nghiệm thu dưới đây.

### Việc chốt và ca cũ phải sửa (kèm lý do)

- `router/tests/cost.test.mjs`: ca `a manual price shows through the snapshot…` so ngày hôm nay với ngày trong bảng
  giá. Sửa để so với `DEEPSEEK_PRICE_AS_OF` — ca đỏ **có sẵn** từ trước vòng này, không do đợt này.
- `router/tests/deepseek.test.mjs`: câu "payload không mang độ dài nên không bịa số nào" (`contextWindow === null`)
  nay sai có chủ đích — dòng `deepseek-flash` **có** số từ bảng kèm nhãn `documented`, còn `deepseek-r1` (ngoài
  bảng) vẫn `null` như cũ, nên ca cũ được viết lại thành hai nửa và thêm một ca mới.
- `router/tests/model-metadata.test.mjs`: `SHARED_FIELDS` thêm `contextWindowSource`/`contextWindowReported` (hợp
  đồng dòng model mở rộng), hai phép so thêm nhãn nguồn, thêm ca "dòng đã lưu nhận bảng và dòng ngoài bảng giữ số của
  nó".
- `backend/tests/unit/test_fix_batch.py`: ca `…prefers_explicit_then_router_metadata` so **số trần**; hàm nay trả
  **cặp** `(số, nguồn)` nên sáu phép so được viết lại, và thêm ca nhãn `fallback` cho model không nguồn nào biết.
- `frontend/src/components/panels/ContextUsageBar.test.tsx`: hai ca viết lại (đường "số đang hiệu lực trong phiên →
  dòng router → bảng tĩnh", và ca heuristic-theo-tên nay phải trả `unknown`), một ca dựng lại trên `claude-3.7-sonnet`
  vì `unknown` không còn in `est.`; thêm bốn ca mới.
- Nhánh D — `components/chat/HarnessStepView.test.tsx`: **8 ca cũ** phải sửa vì hành vi mới (mở khối hoạt động trước
  khi đọc một hàng, một khối `data-activity` duy nhất, bản ghi nằm sau chevron, nhãn `View details`).
- Nhánh E — `lib/vnc/state.test.ts` mở rộng theo thang mới (bỏ trần 4 lượt, nấc cuối giữ ở 20 s), và các ca
  `SandboxScreenPanel` viết lại theo lớp phủ thay cho hai nút thử lại.

### Số ca mới theo nhóm

Cửa sổ ngữ cảnh **16** (router `context-window.test.mjs`) + **1** (router `model-metadata`) + **1** (router
`deepseek`) + **4** (harness `test_context_window_heal.py`) + **4** (giao diện `ContextUsageBar.test.tsx`); lượt trợ
lý của nhánh D **17** ca mới trong `HarnessStepView*` cộng **8** ca đầu tiên cho khung xem
(`MediaLightboxModal.test.tsx`) và **2** ca chuỗi mở khung xem (`MediaLightboxFlow.test.tsx`); màn Máy và bố cục
**66** ca (vnc state 14, hook 5, `ui.test.tsx` 6, `uiStore.workspace` 11, `SandboxScreenPanel` 18, `App.workspace` 8,
`ChatPanel.workspace` 4); hai tab Settings **39** ca (instructions, sổ phiên, đường gửi, sổ harness) cộng **21** ca
editor/danh sách/visualizer của nhánh còn lại.

### Nghiệm thu sống

Router và harness được khởi động lại để chạy mã mới. `/api/router/state` → `deepseek-flash` **1000000 /
documented**; TokenHarbor `deepseek-v4.1-flash` **1000000 / documented / reported 1048576**; OpenRouter
`deepseek/deepseek-v3.2` **163840 / reported** (dòng cũ, không có bảng). `GET /v1/models` (61 dòng) đọc cùng bộ số.
Phiên mới tạo với `deepseek-flash`: `1000000 / documented` (trước đợt này: `64000`, không nhãn); phiên khai tay
`32768`: `32768 / manual`. Phép lành một lần: 4 phiên còn `64000` và 22 phiên `1048576` trong 50 phiên lưu sẵn đều
thành cặp `(số, nhãn)`; lần khởi động thứ hai **đổi 0 dòng**. `GET /api/agent/runtime-info` trả 7 nhóm / 20 công cụ /
9 vai trò, retry `{3, [1,4,12], 30, 60, 0.2}` và `limits.instructionsChars 12000`. Lỗi định tuyến được đo lại trên
router đang chạy: `deepseek-v4-pro` và `Claude 3.7 Sonnet` → `404 MODEL_NOT_FOUND`, còn
`7ee21256-…/deepseek-flash` → `200`.

Ghi chú trung thực: phép lành đưa hai phiên rất cũ (khai `30000` và `250000` **trước** vòng này, không có trường
nhãn) về số của định tuyến — từ vòng này mọi lời khai đều mang nhãn `manual` và không bị chạm. Hàng `info` "context
window healed for N stored sessions" không xuất hiện trong nhật ký harness vì harness không cấu hình handler logging
nào; phép lành được đo bằng chính các bản ghi phiên.

### Vòng soát mã độc lập đợt 18 — bảy phát hiện, đã sửa hết (`074a8ae`)

Vòng soát đọc diff `a061f03..fc51864`, kết luận `RISK SCORE 4` / `Medium` / ngưỡng 7 / `Ship with mitigations`. Nó
không chạy bộ kiểm thử (đúng phạm vi), nhưng tự dựng script trong `/var/tmp` để tái hiện hai phát hiện và mở bản ghi
phiên thật ở chế độ chỉ-đọc để chứng minh phát hiện còn lại. Bảy phát hiện và bản sửa ở `bug-register.md` §6.18; đây là
số ca kèm theo.

| Bộ | Trước lượt sửa (`fc51864`) | Sau lượt sửa (`074a8ae`) | Đỏ còn lại |
| --- | --- | --- | --- |
| Router | 176 / 176 đạt | **178 / 178 đạt** | không |
| Harness (`backend/tests/unit`) | 560 đạt, 1 đỏ | **561 đạt, 1 đỏ** | `test_terminal_tools.py::test_terminal_exec_echo` (có sẵn) |
| Giao diện (`npx vitest run`) | 885 ca / 111 tệp, 4 đỏ | **894 ca / 111 tệp, 890 đạt, 4 đỏ** | đúng bốn ca có sẵn (3 × `Sidebar`, 1 × `workspace/index`) |
| Kiểu (`tsc -b --noEmit`) | 0 lỗi | **0 lỗi** | — |

**Chín ca mới, mỗi ca khoá đúng một phát hiện:** `HarnessStepView.media.test.tsx` (+2 — hàng `start` chưa từng `stop`
được mở, và một bản ghi đã đóng vẫn đúng một player); `uiStore.workspace.test.ts` (+3 — `selectFile` hiện bảng đang ẩn,
đường cũ khi bảng đang hiện, hàng đợi đóng băng được xả đúng luật); `harnessStore.workspace.test.ts` (+3 — `null` xoá
hẳn khoá, `undefined` không đụng tới, bật lại đủ bộ công cụ thì danh sách thu hẹp biến mất);
`ContextUsageBar.test.tsx` (+1 — bản ghi không nhãn nguồn không được đọc là `reported`, kèm nhãn lạ và đối chứng
`reported` thật); `router/tests/context-window.test.mjs` (+2 — `contextWindowReported` không được bằng số đang dùng, và
cận trên `2 000 000` mà vòng soát ghi là "chưa đo"); `backend/tests/unit/test_owner_settings.py` (+1 — phiên tạo không
qua giao diện thừa hưởng tài liệu đang lưu, chỉ dẫn client gửi kèm vẫn thắng, tài liệu rỗng thì không có khối nào).

Hai câu chữ đổi theo bản sửa (không phải ca mới): `contextUsage.fallbackHint` ở **cả hai** danh mục và ca
`nguồn sàn của phiên` trong `ContextUsageBar.test.tsx` — câu cũ ("sàn an toàn {{tokens}} token") chỉ đúng cho sàn thật,
không đúng cho một bản ghi cũ mang số khác mà không có nhãn nguồn, nên câu mới nói thẳng "harness đang giữ {{tokens}}
token, không phải số nhà cung cấp báo".

**Đo lại sống sau lượt sửa:** router khởi động lại (pid 1189311) và harness khởi động lại (pid 1189363): `/api/router/state`
trả **556** dòng có cửa sổ, `deepseek-flash` vẫn `1000000 / documented / reported null`; phép lành lúc khởi động **đổi
0 dòng**; và trong 131 bản ghi phiên thì 13 dòng **không có nhãn nguồn** (9 × `1000000`, 4 × `128000`) — đúng nhóm mà
phát hiện R4 nói tới, nay hiện kèm `est.` và tooltip.

## Vòng 19 — nén ngữ cảnh theo HERMES/PI, OpenCode Free dùng được, và đồng bộ 9Router v0.5.81 (2026-09-21 chiều)

Chủ sở hữu giao bốn việc: (1) clone `hermes-agent`, đọc **cả** `hermes-agent` **và** `pi` rồi port logic nén ngữ cảnh về
BoxFox (bản v1 port thẳng, đối chiếu xem bản BoxFox hiện tại có đúng gốc không) và đề xuất cơ chế nén tự động vì ngưỡng
70 % không bao giờ chạm tới; (2) thử OpenCode Free với **Muse Spark 1.2** xem có dùng được không; (3) nếu 1.2 chạy được
thì chạy nốt các phép kiểm từng bị cắt vì giới hạn, không còn thì dùng DeepSeek API Flash (không phải Pro); (4) nếu 1.2
chạy được mà không bị giới hạn nặng thì chạy các benchmark chuẩn dùng 1.2 — chỉ 1.2, còn không thì báo lại. Tin thứ hai:
clone 9Router bản mới (v0.5.81) và đồng bộ có lọc sang BoxFox, **giữ nguyên UI/UX**, chỉ chỉnh logic.

### Số ca kiểm thử trước và sau

| Bộ | Trước vòng 19 | Sau vòng 19 | Đỏ còn lại |
| --- | --- | --- | --- |
| Router (`/opt/node24/bin/npm test`) | 178 ca / 178 đạt | **207 ca / 207 đạt / 0 đỏ** | không |
| Harness (`backend/tests/unit`) | 561 đạt, 1 đỏ | **583 đạt, 1 đỏ** | `test_terminal_tools.py::test_terminal_exec_echo` (có sẵn; cần PowerShell) |
| Giao diện (`npx vitest run`) | 894 ca / 111 tệp, 890 đạt, 4 đỏ | **894 ca / 111 tệp, 890 đạt, 4 đỏ** | y hệt bốn ca có sẵn — vòng này **không đụng** tệp giao diện nào |
| Kiểu (`tsc -b --noEmit`) | 0 lỗi | **0 lỗi** | — |

**Ca mới:** router **27** (OpenCode 15, hết hạn/cooldown tài khoản 5, lỗi giữa luồng 4, chữ ký suy luận theo họ model 3);
harness **19** (`test_compression_port.py` — 16 ca đơn vị + 3 ca chạy một lượt thật qua `HarnessRuntime` với client giả để
khoá đường ghi usage, đường thay danh sách + huỷ hoá đơn cũ, và trạng thái chống-thrash theo phiên).

### Chủ đề 1 — Nén ngữ cảnh: ngưỡng nay chạm được (chi tiết ở `bug-register.md` §6.20)

Ngưỡng cũ là 70 % cứng của cửa sổ: trên cửa sổ 1 000 000 token ⇒ **697 132 token** (`int((1 000 000 − 4 096) × 0,7)`), trong khi trần thật của một request
là 900 KiB thân bài ≈ 307 000 token. Nghĩa là router cắt bớt trước khi ngưỡng chạm, không checkpoint, rồi các lượt sau
`UPSTREAM_HTTP_413`. Sau khi port: `threshold = min(threshold_tokens hoặc phần trăm, trần byte 301 200)`, đo bằng hoá đơn
thật của router, tỉa nhiều lượt + khử trùng lặp trước khi tóm tắt, đuôi theo ngân sách token, trần tóm tắt co theo độ lớn
transcript, chống-thrash 300 s, và cờ `ineffective` khi nén xong vẫn sát ngưỡng.

**Ngưỡng theo cửa sổ:** 1 000 000 → **301 200** (trước 697 132); 128 000 → 86 732 (không đổi); 32 768 → 20 070 (không
đổi — trần byte không chạm tới ở cửa sổ này).

**Bằng chứng sống:** harness chạy mã mới; phiên `b2cfba9a245b4e84bb06f0ae468f6192` (`deepseek-flash`, cửa sổ khai tay
32 768 để ngưỡng chạm được trong ngân sách) sinh **hai** lần nén tự động:
`{"kind":"summary","beforeEstimate":20408,"afterEstimate":16267}` và `{"kind":"summary","beforeEstimate":21127,
"afterEstimate":13869}`; hai checkpoint `reason=summary` (id 13, 14) ghi **trước** khi thay danh sách; lượt kế tiếp mở
bằng 15 message thay vì 24. Cửa sổ khai tay đã xoá lại: `deepseek-flash` về `1000000 / documented`,
`muse-spark-1.2-contributor-free` về `null`.

**Hai lần từ chối thật khi cửa sổ quá nhỏ (giữ nguyên nhánh fail-closed):** khai 8 192 ⇒ `CONTEXT_LIMIT: current turn/tools
exceed the context budget` (prompt hệ thống + schema công cụ không lọt ngân sách 6 144); khai 32 768 rồi đổ một kết quả
công cụ ~33 000 token trong một lượt ⇒ `CONTEXT_LIMIT: summary did not reduce context enough`. Bản gốc còn nguyên trong cả
hai trường hợp.

### Chủ đề 2 — OpenCode Free với Muse Spark 1.2: **dùng được** (chi tiết ở `bug-register.md` §6.19)

Bậc miễn phí từ chối `403 FreeTierError`/`429` trước đây vì bốn cổng: User-Agent không số, thiếu tool mồi, `stream:false`
của người gọi, và phiên `ses_<32 hex>` mint mới mỗi request. Đo từng biến một (bảng ở §6.19), sửa hết, và hợp đồng dây
ghi ở `router/CONTRACT.md`. Sau khi sửa: khám phá **74 dòng / 8 id bật**; lượt gọi tool thật **1,1 s**; lượt có ảnh trong
kết quả tool trả lời đúng **5,4 s**; người gọi `stream:false` nhận câu trả lời thật **7,6 s**.

Hai giới hạn của nhà cung cấp, đo được và **không** phải lỗi của BoxFox: tên công cụ **quá một dấu chấm** bị từ chối
(`invalid_request_error: name may contain at most one dot`), và bậc miễn phí có **trần theo cửa sổ** (xem chủ đề 4).

### Chủ đề 3 — Hai bậc CUA từng chết vì giới hạn: **PASSED** trên Muse Spark 1.2

Vòng 14 bậc "nặng-có-kịch-bản" chết ở bước 27/30 với `UPSTREAM_HTTP_429` → `UPSTREAM_RETRY_EXHAUSTED`, còn bậc
"nặng-không-kịch-bản" chưa từng chạy. Vòng này chạy cả hai qua OpenCode Free + `muse-spark-1.2-contributor-free`
(`maxSteps 30`, `deadlineSeconds 600`):

| Bậc | Kết quả | Số bước | Công cụ | Lỗi | Giới hạn |
| --- | --- | --- | --- | --- | --- |
| Nặng có kịch bản (14 bước: menu Application → Terminal → 3 lệnh → đóng cửa sổ, chụp sau mỗi bước) | **PASSED** | 25 | 24 (`computer_use` 14, `computer_screen_capture` 9, `inspect_element` 1) | 0 | không có `429`, `413`, `CONTEXT_LIMIT` |
| Nặng không kịch bản (tự mở trình quản lý tệp, tạo thư mục + tệp, chụp bằng chứng) | **PASSED** | 8 | 7 (`terminal_exec` 5, `computer_screen_capture` 2) | 0 | như trên |

Đối chiếu khách quan cho bậc hai: trong hộp, `ls -la /home/agent/boxfox-r19/` có `ladder.txt` **25 byte**, nội dung đúng
`muse-spark-1.2 heavy rung`. Tổng hoá đơn của bậc một: 25 lượt gọi, 229 122 token vào / 13 990 token ra.

### Chủ đề 4 — Benchmark tier-0 `bfcl-simple-subset` với Muse Spark 1.2: **92,1 %**, rồi bậc miễn phí chặn

Bộ dữ liệu BFCL v3 `simple` (400 câu) tải từ HF, chạy qua chính router; lỗi hạ tầng không bao giờ tính là câu sai. Hai
lỗi của **chính bộ chạy** lộ ra và được sửa trước khi lấy số: BFCL phát schema kiểu Python (`type: dict`, `float`) nên
OpenCode từ chối `Invalid JSON schema` (50 câu "rỗng" giả), và một thân bài lỗi **không phải SSE** đã bị bỏ qua.

| Executor | Câu đã gọi | Chấm được | Đúng | Sai | Hạ tầng | Điểm trên phần chấm được |
| --- | --- | --- | --- | --- | --- | --- |
| Muse Spark 1.2 (OpenCode Free), câu `simple_0`–`simple_233` | 234 | 228 | 210 | 18 | 6 (5 lần trần token đầu ra + 1 câu bị luật tên công cụ) | **92,1 %** |
| DeepSeek Flash (API), câu `simple_234`–`simple_399` | 166 | 79 | 74 | 5 | 87 (85 câu bị nhà cung cấp từ chối vì tên công cụ có dấu chấm, 2 câu trả lời rỗng) | 93,7 % |

Hai nửa này **không chồng lên nhau** (166 câu sau chỉ chạy sau khi bậc miễn phí đã chặn hẳn), nên gộp lại là 307 câu chấm
được / 284 câu đúng = 92,5 % — con số gộp chỉ để tham khảo, không phải điểm của một model nào.

Ghi chú trung thực về điểm của Muse Spark 1.2: trong 18 câu sai, **5 câu chỉ sai cách viết** và không phải kiến thức
(2 câu `[12, 15, …]` so với `[12.0, 15.0, …]`, 3 câu viết `x^2` thay vì `x**2`); nếu tính cả năm câu đó thì 94,3 % — con số
này **không** phải thang chấm của BFCL nên chỉ ghi kèm. 13 câu còn lại sai thật (thiếu tham số, chọn giá trị khác nghĩa).

Trần của bậc miễn phí: sau câu `simple_233`, nhà cung cấp trả `[rate_limit_exceeded] Output token rate limit exceeded`, rồi mọi
lượt sau — kể cả một bậc CUA chạy song song — bị chính router trả `429` (`This target is cooling down after a provider
limit.`) trong hơn 35 phút. Đây là **giới hạn của bậc miễn phí**, không phải lỗi mã; phần còn lại chạy bằng DeepSeek API
Flash đúng như quy tắc dự phòng của chủ sở hữu.

### Chủ đề 5 — Đồng bộ 9Router v0.5.81 (lọc sáu ứng viên, không đụng giao diện)

Bản clone `/var/tmp/9router` ở commit `a8c9d38` (*"docs: update changelog header to v0.5.81"*, 2026-09-18);
`git fetch --all` xác nhận **không có commit mới hơn**. Sáu ứng viên được lọc theo đúng mã nguồn 9Router rồi mới port:

| # | Ứng viên | Kết quả | Nơi sửa | Ca khoá |
| --- | --- | --- | --- | --- |
| 1 | Chữ ký suy luận của Gemini chỉ dùng lại cho đúng họ model | **ĐÃ PORT** | `router/src/anthropic.mjs:56,66,70,83` (ghi `:506`, đọc `:286`) | 3 |
| 2 | Lỗi 4xx theo phạm vi request không được đánh hỏng tài khoản/không vào cooldown | **ĐÃ PORT** | `router/src/errors.mjs:44`, `router/src/engine.mjs:148` | 5 |
| 3 | Lỗi giữa luồng sau `200` phải thành khung lỗi + `[DONE]` | **ĐÃ PORT** (hẹp hơn bản gốc) | `router/src/server.mjs:145-153` | 4 |
| 4 | DeepSeek V4/V4.1: mức suy luận `low`/`max` và luật vision theo bản có dấu chấm | **ĐÃ PORT** (không đụng `none/low/high/max` đang ghim) | `router/src/providers/deepseek.mjs:104,112,121` | 2 |
| 5 | Kiro: giữ dấu gạch dưới, tên công cụ của client, ảnh trong kết quả tool | **BỎ QUA** | BoxFox **không có** adapter Kiro (`adapterFor('kiro')` trả `null`, catalog ghi `planned`) | — |
| 6 | Ollama Cloud thêm `deepseek-v4.1-flash:cloud` | **BỎ QUA** | không có danh sách model Ollama để sửa; inventory dò sống từ `GET https://ollama.com/v1/models` | — |

Ngoài phạm vi, đã ghi rõ: OAuth Xiaomi MiMo, công tắc 1M của Claude Code + `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, Command
Code, Zed, màn Usage/credit, phạm vi hiển thị Model Catalog, i18n tiếng Ba Tư. Vòng này **không** sửa tệp nào trong
`frontend/`.

### Vòng soát mã độc lập đợt 19 — bốn phát hiện, ba sửa (2026-09-21 tối)

Vòng soát mã độc lập (`r19-review`, dải `00b7a8a..374a70a`) chốt **"Ship with mitigations"**, rủi ro **4/10 (Trung bình)**,
và đề nghị sửa F1 + F3 trước lượt kiểm chứng cuối. Cả ba phát hiện có mã đã sửa ở commit `f827dd5`, mỗi bản sửa có bài
khoá; F4 ghi nhận có chủ đích. Chi tiết đầy đủ nằm ở `docs/tracking/bug-register.md` §6.21.

| Phát hiện | Mức | Bản sửa | Ca khoá |
| --- | --- | --- | --- |
| F1 — đuôi nguyên văn co về 0 khi transcript kết thúc giữa một loạt công cụ song song to hơn `tail_budget` | Cao | `keep_tail()` (`compression.py:180-199`, gọi ở `:479` và `:486`) | `test_the_fold_never_takes_the_whole_tail_of_a_parallel_batch` |
| F2 — `compact()` trả bản sao y nguyên kèm event `prune` khi hoá đơn vượt ngưỡng mà chưa tỉa được gì | Trung bình | hợp đồng no-op ở hai nhánh thoát sớm của vòng tỉa (`compression.py:498`, `:528`) | `test_a_usage_trigger_with_nothing_to_prune_is_a_no_op` |
| F3 — nhánh chat với `tools: []` không được nguỵ trang, cú từ chối hình dạng bị xếp là lỗi khoá | Trung bình | nhánh chat luôn gửi công cụ mồi (`opencode.mjs:668-672`) | 2 ca trong `router/tests/opencode.test.mjs` |
| F4 — `threshold_tokens` không có điểm gọi; dòng `tool_choice` vô hại | Thấp | ghi nhận, giữ nguyên (bề mặt có test / bản đối chiếu 9Router) | — |

**Khe hở bàn giao do làn kiểm thử nêu** (điểm gọi `/compact` chưa có bài nào chạm) đã đóng bằng
`test_the_manual_compact_command_anchors_on_the_recorded_usage` ở `342d31e`. **Đo sống sau khi sửa** (harness chạy mã mới,
`deepseek-flash`, cửa sổ khai 32 768, phiên `985672004f4b44ab85efc6db7c37e421`): lượt tỉa
`{"kind":"prune","beforeEstimate":20353,"afterEstimate":19517,"pruned":4}` và lượt gộp
`{"kind":"summary","beforeEstimate":21467,"afterEstimate":16325}`, hai checkpoint ghi trước khi thay danh sách, danh sách
gộp còn 13 message (3 hàng `tool`, 2 hàng `user` nguyên văn). **`/compact` đầu-cuối trên OpenCode Free** (phiên
`cfd20946b37947069c0cadedf700d8c3`, `nemotron-3-ultra-free`, qua router sống sau khi khởi động lại):
`{"kind":"summary","beforeEstimate":13626,"afterEstimate":3907}`, không lỗi — trên cửa sổ 128k thì lệnh nói thật
`{"kind":"unchanged"}`. Hình dạng `tools: []` trước/sau khi khởi động lại router, cùng khoá: trước `403 AUTH`, sau
`200` trong 1,0 s.

## Vòng 20 — nhật ký tác vụ dài và thư mục riêng cho mỗi phiên, kế hoạch có phiên bản thật kèm thang điểm, và hai lỗi trần bước/agent con (2026-09-21 tối)

Vòng này bắt đầu từ **phép đo byte**, không phải từ cảm nhận: chủ sở hữu thấy các phiên dài thường "đuối" mà không rõ vì
sao. Đo `~/BoxFox/harness/sessions.sqlite` trong box cho ra bốn con số buộc phải sửa:

| Chỗ chứa | Kích thước | Số hàng | Ghi chú |
| --- | --- | --- | --- |
| `sessions.messages` | **36 435 050 B** | 150 phiên | hàng to nhất **6 424 279 B** |
| `checkpoints.messages` | **17 967 616 B** | 22 hàng / **12** phiên | chỉ 8 % số phiên có bản lưu; hàng to nhất **3 170 519 B** |
| `events` | 6 324 257 B | **74 994** | **0** hàng `turn_start` / `turn_end` |
| tệp `sessions.sqlite` + WAL | 76 111 872 B + 4 441 392 B | — | bản sao người đọc được: **không có** |

Độ dài phiên (150 phiên sống của box): trung vị **7** message, p90 **42**, cao nhất **123**; **87/150 phiên dưới 10
message**; trạng thái `completed` 77 / `failed` **51** / `idle` 18 / `cancelled` 4. **10 phiên vượt trần thân bài của router
(`ROUTER_BODY_BUDGET` 921 600 B) — cả 10 đều to hơn 1 MiB và cả 10 mang trạng thái `failed`.**

**Bốn nguyên nhân gốc của "phiên cụt"** (mỗi cái đều có bằng chứng sống, không phải suy đoán):

1. `heal_context_windows()` bỏ qua nguồn `manual` ⇒ 12 phiên đứng nguyên ở 32 768 / 16 384 / 8 192, kéo ngưỡng nén xuống
   20 070 / 8 602 / 2 867.
2. `FALLBACK_CONTEXT_WINDOW` áp cho hai model `nemotron-*-free` mà router trả `null` ⇒ nén ở 86 732 dù cửa sổ thật lớn.
3. Ngưỡng byte `921600 // 3 − 6000 = 301 200` là ngưỡng **duy nhất** còn chạm được trên cửa sổ lớn.
4. `MAX_STEPS 20` cộng nhánh cắt hạn chót im lặng ⇒ 51/150 phiên `failed`, kể cả phiên đã làm xong việc.

Nén đo được trên các phiên thật: `920946a7` 58 → 8 message (86,2 %), `98567200` 33 → 13 (60,6 %), `43a92d61` 9 → 8 với
bốn lần `"ineffective": true` liên tiếp. Phiên to nhất `72a6a428` gỡ được **0 %**. Thư mục ảnh ghi hình: **374 tệp / 113 MB**
(79 mp4 = **94 505 331 B**), **không** có chỗ nào dọn. Đánh số plan: hai slug mới tinh nhận **v5** và **v6** cách nhau sáu
phút, vì `used` lấy từ **mọi** tệp trong `.plans/`.

### Số ca kiểm thử trước và sau

| Bộ | Trước vòng 20 | Sau vòng 20 | Đỏ còn lại |
| --- | --- | --- | --- |
| Harness (`backend/tests/unit`) | 583 đạt, 1 đỏ | **821 đạt, 1 đỏ** | `test_terminal_tools.py::test_terminal_exec_echo` (có sẵn; cần PowerShell) |
| Box (`deploy/docker`, `unittest discover -s tests -t tests`) | 437 OK | **447 OK** | không |
| Router (`/opt/node24/bin/npm test`) | 207 / 207 | **209 / 209** | không |
| Giao diện (`npx vitest run`) | 894 ca / 111 tệp, 890 đạt, 4 đỏ | **918 ca / 113 tệp, 914 đạt, 4 đỏ** | y hệt bốn ca có sẵn — vòng này chỉ đụng khối checklist ở tab Plan |
| Kiểu (`tsc -b --noEmit`) | 0 lỗi | **0 lỗi** | — |

### Phần A — thư mục theo phiên, nhật ký, dọn ảnh (A1–A9)

`deploy/docker/session_files.py` (997 dòng) + `session_ops.py` (283 dòng) là tầng file trong box; `worker.py` gọi qua bốn op
`session_ensure`, `journal_append`, `checkpoint_write`, `captures_prune` (tên op khai trong `SESSION_OP_NAMES` độc lập với
việc nạp được mô-đun, để thiếu tệp thì báo `SESSION_OPS_UNAVAILABLE` chứ không im lặng). Hình dạng mỗi phiên:
`.session-history/<sid8>/{session.json, journal.jsonl, journal.md, checkpoints/*.json + *.md}`; `session.json` không bao giờ
là bản nửa vời (ghi tệp tạm rồi `os.replace`); ghi lỗi thì lượt vẫn xong, có `notice` và bản ghi `status: degraded`.

Bảng `journal` (SQLite, `seq` tự tăng) là **chỉ mục**, file JSONL là **bản người đọc được**; bản ghi có `id` theo tiền tố
(`T:` việc, `P:` kế hoạch, `S:` bước, `D:` quyết định, `E:` bằng chứng, `C:` lần nén, `F:` sự kiện, `X:` việc giao cho con).
`session_search` v2 tra **ba nguồn** (message hiện tại, checkpoint, nhật ký) và nói thật khi bị cắt (`truncated`, `dropped`).
Hai công cụ mới cho agent (`journal_write`, `journal_brief`) đưa số công cụ **20 → 22**; `status`/`refs`/`evidence` đi thẳng
vào bộ kiểm của `journal.record` nên một lời gọi sai bị **từ chối**, không được lặng lẽ bỏ qua.

Dọn ảnh: bốn hằng số có tên — 200 tệp/loại/phiên, 512 MiB/phiên, 4 GiB/toàn box, 40 mp4/phiên (`retention()` trong
`session_files.py`). Không tệp nào bị xoá trong vòng này: `backfill_history.py` chỉ chạy dry-run.

### Phần B — kế hoạch có phiên bản thật, thang điểm, và khối checklist ở tab Plan (B1–B6)

`plan_eval.py` chấm P1–P8 theo thang 0/1/2 (hai mức là **cổng cứng**: bằng chứng đo được và tiêu chí nghiệm thu), trả
`verdict` `pass` / `pass_with_conditions` / `fail` cùng `hardGate` (`true` = **mọi** cổng cứng đạt, cùng chiều với
`scripts/eval/rubric.py`). `plan_registry.py` dựng chỉ mục theo **thư mục**, nên `v4` nằm cạnh `v3` trong cùng nhóm là một
nhóm hai bản. `plan_header.py` + header `<!-- boxfox-plan` cho mỗi bản (giờ cả tệp mồi
`deploy/docker/bootstrap-plans/v1-agent-box-plan.md` cũng có). Hai route mới: `GET /api/agent/plans/status` và
`POST /api/agent/plans/review` (ghi sổ ở harness trước, chuyển tiếp vào box sau; chuyển tiếp lỗi thì trả
`forwarded: false` chứ không báo thành công).

`deploy/docker/migrate_plans.py` (**mặc định dry-run**) nạp header cho sáu tệp `.plans` đang sống, có `--merge a=b` (từ chối
khi **tên đích** đã tồn tại, bỏ qua kèm cảnh báo khi nhóm nguồn đã gộp trước đó) và `--renumber-lone` (mặc định tắt).
Chạy thật trên **bản sao**: `wrote=6`, `renamed=1`, lần hai báo `nothingToDo=true`; chạy dry-run trên tệp sống: `wrote=0`,
md5 sáu tệp không đổi.

### Phần C — hai lỗi đo được trong lúc kiểm thử sống (C1, C2)

- **C1:** `limits.py` cắt `deadlineSeconds` 900 → 600 **im lặng**, và `MAX_STEPS` đánh dấu `failed` một phiên đã xong việc.
  Đo sống: 20 bước / 140,1 s ⇒ `failed`; chạy lại với `maxSteps: 40` trên `pallets/click` ⇒ `completed` trong **27 bước**.
  Nay việc cắt hạn chót có mã `notice` riêng, và đầu ra bị cắt vì `length` được nhận diện bằng `TRUNCATED_OUTPUT_NOTICE_CODE`.
- **C2:** agent con `6bd868ad…` trả `finishReason: length, outputTokens: 4096, toolCalls: 0` ⇒ `TURN_EMPTY_RESPONSE` **không
  thử lại**, cha nhận `failed`. Nay có `TRUNCATED_OUTPUT_MAX_TOKENS = 2048` và một lượt thử lại trước khi bỏ.

### Phần D — chính sách độ dài, đánh số, và ngưỡng nén (N1–N10, P1–P5)

`docs/naming.md` gom 29 quy luật (9 **BẮT BUỘC**, 20 **THÓI QUEN**) cùng bảng tiền tố nhật ký. Luật đánh số nay **không**
lấy `max` của mọi tệp: số chỉ tăng trong **cùng nhóm identity**, nên việc mới tinh bắt đầu ở `v1`. Ngưỡng nén theo cửa sổ
(công thức: `min(0,7 × (cửa sổ − dự trữ đầu ra), 200 000, 301 200)`, sàn 32 000 khi còn đủ chỗ):

| Cửa sổ | Ngưỡng mới | Trước |
| --- | --- | --- |
| 8 192 | 2 867 | 2 867 |
| 32 768 | 20 070 | 20 070 |
| 128 000 | 86 732 | 86 732 |
| 256 000 | **176 332** | 172 532 |
| 1 000 000 | **200 000** | 301 200 |

`FALLBACK_CONTEXT_WINDOW` 128 000 → **256 000**, và hai dòng `nemotron-3-ultra-free` / `nemotron-3.5-lightning-free` được
khai **1 000 000** trong bảng cửa sổ của router (OpenRouter công bố đúng 1 000 000 cho hai bản `:free` này).

### Nghiệm thu sống

- Bản dry-run nạp lịch sử cũ (`/code/.generated_artifacts/r20/backfill_dry_run.md`): 22 hàng checkpoint trên 12 phiên,
  **12 ghim `P:`**, **258 đường dẫn artefact trên 39 phiên**, **123 tệp ảnh không payload nào nhắc tới** (96 953 338 B) —
  chỉ đếm, không xoá.
- Bản dry-run migration (`/code/.generated_artifacts/r20/migrate_plans_dry_run.md`): sáu tệp, sáu header, một ca gộp, `wrote=0`.
- Di trú schema trên **bản sao** `sessions.sqlite`: `checkpoints` thêm bốn cột (`before_estimate`, `after_estimate`,
  `context_window`, `model_id`), bảng `journal` xuất hiện, 22 hàng còn nguyên.
- Lượt thật của làn C trên repo (`/code/.generated_artifacts/r20/cua_repo_report.md`): **300 bài đạt**, và cặp bằng chứng
  `20 bước → failed` so với `40 bước → completed trong 27 bước`.
- Hình dạng giao diện khối checklist: `/code/.generated_artifacts/images/r20_design_plan_eval_checklist.png`.

### Cần chủ nhà chốt sau vòng này

1. `maxSteps` mặc định 16 → **40** (khuyến nghị; đo được: trần bước, không phải hạn chót, là thứ đánh `failed` một việc đã xong).
2. Có `--apply` migration trên box sống không, và có `--renumber-lone` / xoá hai plan thử hay không; `v4` có đổi tên theo nhóm không.
3. Dải identity mơ hồ `0,5 ≤ j < 0,75`: từ chối một lần (khuyến nghị) hay gộp luôn.
4. Ngưỡng cứng độ dài plan: từ chối khi > 150 000 ký tự (khuyến nghị) hay chỉ cảnh báo.
5. Gốc thư mục theo phiên: `.session-history` (khuyến nghị) hay `.sessions/`.

## Vòng 21 — năm việc chủ nhà giao: upload trong dấu `+`, trần bước, sub-agent nhìn nhau, bằng chứng sống, bảng theo turn (2026-09-22, sáng)

- Phạm vi: (1) gửi nguyên nội dung một tệp Markdown dưới dạng text để kiểm chứng khả năng chạy, chất lượng
  output plan và hành vi gọi sub-agent; (2) trần `maxSteps` 16 cùng hai lỗi quanh trần bước/hạn chót;
  (3) kiến trúc để sub-agent nhìn thấy nhau và bàn giao có định tuyến; (4) bằng chứng sống gắn vào câu trả lời cuối;
  (5) bảng Sub-agents phải theo từng turn. Model chính: OpenCode Free `muse-spark-1.2/1.3-contributor-free`.
- Cách chạy: router 3101 + harness 3102 + Vite 3100 do phiên này khởi động; box `agentbox-box` đang chạy;
  ba lượt qua API (`/tmp/run_turn.py`, log `/tmp/runA.txt`, `/tmp/runB.txt`, `/tmp/runD.txt`) và ba lượt qua giao diện
  (agent-browser 0.21.2). Xem trước công khai: `https://wc91p7pgg7ed.preview.us1.vorflux.com` (chỉ để xem;
  lớt chạy bị chặn vì `Origin` của harness chỉ nhận loopback — `backend/src/agentbox/api/server.py:119-139`).
- Kết quả: **5/5 việc có kết luận đo được**; **4 lỗi mới** (BUG-39 … BUG-42) và **1 lỗi giao diện** (BUG-43);
  kế hoạch sáu phần A–F ở `docs/plan/v21-boxfox-plan.md` (+ bản tóm tắt cùng chỗ).

### Phần A — gửi tệp qua dấu `+`

- Menu có đủ bốn mục trong DOM nhưng **bị cắt**: với menu đang mở, `document.elementFromPoint` tại tâm mục
  `Tải lên hình ảnh` (`itemRect [290,642,226,45]`) trả về khung chat ⇒ mục không phải phần tử trên cùng.
  Tổ tiên cắt là `flex min-w-0 items-center gap-1.5 overflow-hidden` (`ChatInputBar.tsx:268`) trong khi popover
  đặt `absolute bottom-full` (`AttachmentPicker.tsx:159`). Lặp lại được ở **cả** địa chỉ công khai lẫn `localhost:3100`.
- Gửi thật một tệp `probe-upload.txt` (đã dán nhãn vào input ẩn, vì menu không bấm được): chip hiện tên,
  lượt chạy tạo phiên `0ef73471c38d4c63a593755345213dcf`, và event `user` **đúng bằng** phần text cộng
  `\n\n[Attached Files: probe-upload.txt]` — **không nội dung, không đường dẫn**.
- Sau lượt: `docker exec agentbox-box ls .uploaded_artifacts` **rỗng**, `find /home/agent/workspace -name '*probe-upload*'`
  **không có**. Agent tự đi tìm, kết luận "tệp không tồn tại", rồi lượt chết bằng `TURN_EMPTY_RESPONSE`.
- Đường ống đã có sẵn nhưng chưa ai gọi: `POST /__box/file/upload` (`deploy/docker/ide-proxy.py:540-568`),
  `workspace_files.write_upload` (`deploy/docker/workspace_files.py:743-754`), client
  `frontend/src/lib/workspace/http.ts:70-87`, thư mục `.uploaded_artifacts` tạo lúc boot
  (`deploy/docker/box-entrypoint.sh:15-24`), luật tên RULE-5 **chưa có code nào cấp số** (`docs/naming.md:24`).

### Phần B — gửi nguyên nội dung Markdown và chất lượng plan

- Lượt 1 (dán 2 770 byte, `muse-spark-1.3-contributor-free`, phiên `67bdfd4bd6fa4398bd0273e62dd2acc0`):
  `write_plan` bị từ chối **bốn lần** (`PLAN_QUALITY_REJECTED: missing (verification-section)`;
  `missing (verification-command)`; `PLAN_EVAL_REJECTED: (steps-unanchored) chỉ 4/11 bước có lệnh…`;
  `(plan-no-steps)`) rồi mới nhận ở lần thứ năm: `.plans/v1-boxfox-5-upgrades.md` 4 643 byte,
  `levels {P1:1, P2..P8:2}`, kèm `ui_intent` mở tab Plan. Lượt xong ở **bước 6**, `completed`,
  `contextEstimate 24001`, **không gọi sub-agent nào**.
- Plan sinh ra vẫn sai sự thật ở ba chỗ: bịa tên hằng `DEFAULT_MAX_STEPS` (thật là `MAX_STEPS_DEFAULT`),
  bịa `turnId`/`deadlineMs`, và tự nhận trong mục *Sources / Citations* rằng các số 40 bước / 10 MB / 120 s
  là "giá trị tự chọn", không có nguồn.
- Lượt 2 (delegation, `muse-spark-1.2-contributor-free`, phiên `b66559fa8e2743a79e7b1d079fecc881`):
  cha gọi `delegate_task role=explore` (con `391cbed2…`, 8 bước, 7 tool) rồi `role=review`
  (con `d79a2112…`, 8 bước, 7 tool), xong ở bước 3. Con `explore` tìm `ChatInputBar.tsx` khi mã nguồn chưa
  được chép vào box nên kết luận "tệp không tồn tại"; con `review` **sửa lại** khi mã đã có. Đây là bằng chứng
  sống cho thấy hôm nay chỉ có cha làm trung gian: con không đọc được việc của con khác, chỉ đọc lại sau khi cha
  giao việc mới.

### Phần C — trần bước và hạn chót

- Việc vừa phải (đọc 2 tệp + grep + viết báo cáo + đọc lại, phiên `dddebffb887a4f6ca814c1514367d38d`),
  chạy với **đúng mặc định** `{"maxSteps":16,"deadlineSeconds":180}`: xong ở **bước 8**, `completed`,
  `contextEstimate 28235`. Không chạm trần.
- Việc của con (`delegate_task role=explore`, phiên `ea9486495da646d7aac4ccd4214ea8ed`): chạy **10/10 bước**,
  33 tool call, hết **120 s** ⇒ `DEADLINE: the turn ran out of time before an answer was produced`,
  `answerChars = 0`, cha nhận `status=failed`. **Toàn bộ chín bước đã làm bị vứt**, không có đường trả về phần dở.
  Cùng mã lỗi `DEADLINE` như ảnh chủ nhà gửi (`Error code: DEADLINE`, `Worked for 180s`). Chủ nhà báo ở lượt gốc;
  vòng này **không tái hiện được băng đỏ ở lượt gốc** (phiên gốc cũ đã bị dọn khỏi store) — tái hiện được **cùng mã lỗi**
  ở agent con (120 s) và thấy cha vẫn báo lỗi đó cho người dùng trong dòng `last_error`.
- Lỗi thứ ba, đo được trong chính lượt gửi tệp: `TURN_EMPTY_RESPONSE: the model finished without a usable answer
  (no text, no tool call)` tại bước 5 — model đã có `thought` nhưng không có text/tool call, lượt bị đánh `failed`,
  **không thử lại**, người dùng mất cả lượt.

### Phần D — kiến trúc sub-agent (đọc mã, không sửa)

- Mỗi cha chỉ có một đường sinh con và chạy tuần tự (`runtime.py:2531-2534`); `child_slots` là `Semaphore(3)`
  **toàn tiến trình** (`runtime.py:967`) nên hai cha tranh nhau ba slot; tool trong một bước cũng tuần tự
  (`runtime.py:1730-1741`).
- Con không có tool để đọc/đợi/nhắn bạn: tập tool là frozenset theo vai (`roles.py:7-11`, gán `:148-158`,
  giao với cha `:163-165`), `session_search` chỉ orchestrator và **khoá theo sid của chính nó**
  (`roles.py:159-160`, `runtime.py:1944-1945`, `:1966-1967`), con không hỏi được người dùng (`runtime.py:1991-1995`).
- `store.events()` trả tối đa 500 hàng (`memory/session_store.py:136-139`); `child` event không mang `turn`/`step`
  (`runtime.py:2523-2530`, `:2564`) nên giao diện không thể phân turn dù muốn.

### Phần E — bằng chứng sống và bảng Sub-agents theo turn

- Không có cổng nào cho câu trả lời cuối: chỉ kiểm "có text và `finish_reason` hợp lệ" (`runtime.py:1696`) rồi
  phát thẳng (`:1712-1713`); cổng duy nhất đang chạy là cho **plan** (`runtime.py:2195`, `:2213`).
  Giao diện ghim badge `done` **vô điều kiện** (`HarnessStepView.tsx:1534-1537`) và store bỏ luôn
  `session.journal` mà backend đã trả (`harnessChatStore.ts:285-338`; `api/server.py:285-293`).
- Bảng Sub-agents sai theo turn, đo sống: lượt 2 sinh con `ea948649…`; **lượt 3** hỏi `2+2` (xong trong 3 s,
  không gọi tool nào) mà bảng vẫn ghi `SPECIALISTS PIPELINE · 1 TOTAL · Explore Specialist FAILED · 33 tools executed`.
  Gốc: `childrenMap` dựng từ mọi event `child` của phiên (`SubagentInspectorPanel.tsx:162-196`, render `:347`/`:361`)
  và store không cắt theo turn (`harnessChatStore.ts:294`).

### Kiểm chứng model (chủ nhà hỏi)

- `muse-spark-1.2-contributor-free` và `muse-spark-1.3-contributor-free`: **cả hai chạy được** — test qua router
  đều `status: passed` (usage trả về), giao diện hiện đủ chín model `-free` trong tab "Single Models".
  Không có báo cáo thiếu model.

### Bằng chứng của vòng

- Ảnh: `images/r21_preview_01_public_url.png`, `images/r21_upload_05_clipped.png`,
  `images/r21_local_02_menu_clipped.png`, `images/r21_local_03_chip.png`, `images/r21_local_04_sent.png`
  (bong bóng chat chứa `[Attached Files: probe-upload.txt]`), `images/r21_model_01_muse13_selected.png`,
  `images/r21_perTurn_02_subagents_after_turn2.png`, `images/r21_perTurn_03_turn3_with_stale_child.png`.
- Log: `/tmp/runA.txt`, `/tmp/runB.txt`, `/tmp/runD.txt`; phiên `67bdfd4b…`, `b66559fa…`, `dddebffb…`,
  `0ef73471…`, con `ea948649…`.
- Kế hoạch: `docs/plan/v21-boxfox-plan.md` (sáu phần A–F), tóm tắt `docs/plan/v21-boxfox-plan-summary.md`.
## Vòng 22 — đợt foundation: tệp đính kèm tới box, trần bước có chẩn đoán, plan sạch theo tên, trần độ dài câu trả lời (2026-09-22, chiều)

- Phạm vi (đợt 1 của kế hoạch `docs/plan/v22-boxfox-plan.md`, việc A1–A11 / B1–B10 / C1–C5 / D1–D2 / E1–E5):
  (A) gửi tệp và hình từ dấu `+` tới box, đưa **đường dẫn thật** vào lượt; (B) ngân sách bước và hạn chót theo D-1/D-15 —
  tách mã, **chẩn đoán bốn phần**, trả `partial` thay `failed`, ghi `stepsUsed`/`deadlineUsedMs`; (C) kế hoạch: `--apply`
  sao lưu trước, vé mơ hồ dùng một lần; (D) trần độ dài câu trả lời; (E) ba bộ test và một lượt thử sống đầu-cuối.
- Cách chạy: router 3101 + harness 3102 (khởi động lại trên mã mới) + Vite 3100 + box `agentbox-box` đang chạy;
  ảnh box **không** dựng lại — `worker.py` được gửi nội tuyến trong mỗi lần gọi. Lượt sống qua API (`curl`) và một lượt qua
  giao diện (agent-browser, phiên `foundation`). Xem trước: `localhost:3100`; lượt chạy bắt buộc đi qua loopback vì
  `Origin` của harness chỉ nhận loopback (`backend/src/agentbox/api/server.py:119-143`).
- Kết quả: **A, B, C, D xong**; ba bộ test xanh (backend **902 passed / 1 bài đỏ sẵn có**, frontend **958 passed**,
  `deploy/docker` **493 passed**); ba phép kiểm bắt buộc của E3 xanh; **một lỗi mới** (BUG-44) lộ ra trong chính lượt đo.
  Đợt **kiểm thử độc lập** chạy sau đó (cùng PR, HEAD `f57619d`) tìm thêm **ba** lỗi trong chính mã mới của đợt này
  (BUG-45…BUG-47, đã sửa) và đo lại cả ba bộ test — backend **1 failed / 916 passed**, `deploy/docker` **496 passed**,
  frontend **118 tệp / 958 bài**, `tsc -b --noEmit` sạch: xem mục cuối bài.

### Phần A — tệp đính kèm đi tới box (D-6, BUG-39, BUG-40)

- Menu `+` bấm được sau khi popover render qua portal: hit-test tại tâm **cả bốn** mục đều trả `true`
  (`Tải lên hình ảnh`, `Tải lên tệp tin`, `Tải lên thư mục`, `Google Drive`); mục Drive `disabled: true` và đọc đúng
  "Chưa kết nối — không đính kèm được tài liệu Drive" (A9). Cùng phép đo ở vòng 21 trả về khung chat (`itemRect [290,642,226,45]`).
- `.uploaded_artifacts` trước đợt E3: **5 tệp** (`1.md` … `5.md`). Trong đợt: **+2 tệp** — `6.md` (31 B, lượt qua API) và
  `7.md` (34 B, lượt qua giao diện); cả hai **khớp byte** (`cat <n>.md | diff - /var/tmp/foundation-e2e.md`,
  `... /var/tmp/foundation-e2e-ui.md` ⇒ không khác byte nào). Tổng sau đợt: **7 tệp / 32 KB**.
- Số RULE-5 do box cấp (BOX-6): `POST /__box/file/upload?assign=1` trả `{"path": ".uploaded_artifacts/1.md", "name": "1.md", "sizeBytes": 28}`;
  bốn lượt tải **song song** cùng lúc ⇒ `2.md 3.md 4.md 5.md`, `uniq -d` **rỗng** (không trùng số).
- Đường dẫn vào lượt: event `user` cuối của phiên `c4cf5256d3174303b363cd3896ba0246` mang
  `{name: 7.md, path: .uploaded_artifacts/7.md, absolutePath: /home/agent/workspace/.uploaded_artifacts/7.md, sizeBytes: 34, kind: file}`
  — `absolutePath` do **harness suy ra**, không lấy từ client (bài `test_turn_attachments.py` khoá điều này bằng một hàng gửi kèm
  `absolutePath: /etc/passwd` và khẳng định giá trị dùng thật không phải `/etc/passwd`).
- Ngữ cảnh gửi model (đọc từ `~/BoxFox/harness/sessions.sqlite`, hàng `messages` của phiên): phần text của tin `user` cuối bằng
  `Đọc tệp vừa đính kèm và in ra đúng dòng đầu tiên.` cộng khối `[Tệp đính kèm đã lưu trong box]` với dòng
  `- /home/agent/workspace/.uploaded_artifacts/6.md (6.md, 31 B)` — đường dẫn tuyệt đối nằm **trong ngữ cảnh**; chuỗi
  `[Attached Files: …]` của BUG-40 không còn xuất hiện ở đâu.
- Lượt sống đầu-cuối qua phiên **mới** (không ngữ cảnh cũ) `92f76c90467d4dfaaa3bbb3d40278069`: gửi **chỉ** đường dẫn tương đối
  `.uploaded_artifacts/6.md`; model gọi `file_read {"path": "/home/agent/workspace/.uploaded_artifacts/6.md"}` rồi trả về đúng dòng
  `FOUNDATION-E2E-20260922T111913` — `turn_end {status: completed, stepsUsed: 2, toolsRun: 1, deadlineUsedMs: 4514}`.
- Lượt qua giao diện (phiên `c4cf5256…`): chip `foundation-e2e-ui.md` + `1 KB` trong ô soạn tin; bong bóng người dùng mang chip
  `7.md 1 KB .uploaded_artifacts/7.md` (A10); model gọi `file_read` đúng đường dẫn tuyệt đối và trả về
  `Dòng đầu tiên của tệp /home/agent/workspace/.uploaded_artifacts/7.md: FOUNDATION-E2E-UI-20260922T113232`
  — `turn_end {status: completed, stepsUsed: 2, toolsRun: 1, deadlineUsedMs: 2569}`.

### Phần B — trần bước và hạn chót có chẩn đoán (D-1, D-15, BUG-41, BUG-42)

- Số mặc định sống: `GET /api/agent/runtime-info` ⇒
  `{maxStepsDefault: 40, maxStepsMax: 60, deadlineDefaultSeconds: 180, deadlineMaxSeconds: 600, childMaxSteps: 40, childDeadlineSeconds: 300}`.
- Kẹp trần nói ra đúng một lần: `POST /api/agent/sessions {"maxSteps": 999}` ⇒ phiên `2e92c8242d184ce3ad5d69f2192e7522`,
  **đúng một** notice `STEPS_CLAMPED {requested: 999, applied: 60}`, `config.maxSteps = 60`, `config.stepsClamped = true`,
  `sessionMetrics.stepsClamped = true`.
- Lượt trong ngân sách (phiên `43b363cc79f04e84a86af7c1f02db757`, `maxSteps: 40`, `deadlineSeconds: 300`):
  `turn_end {status: completed, stepsUsed: 1, toolsRun: 0, deadlineUsedMs: 1934}`, **không có notice nào**.
- Lượt chạm trần bước (phiên `1cbb482079de430091e2de76f18144ae`, `maxSteps: 4`) đóng bằng **`partial` có nội dung**:
  `turn_end {status: partial, stepsUsed: 2, toolsRun: 1, deadlineUsedMs: 4953, partial: true, diagnosis: true}`; **đúng một** notice
  `STEP_BUDGET_EXHAUSTED {partial: true, diagnosis: true, diagnosisChars: 465, stepsUsed: 2, toolsRun: 1, maxSteps: 4, reservedSteps: 3, deadlineSeconds: 300, deadlineUsedMs: 4959}`;
  hàng `sessions` vẫn `completed` (không thêm giá trị `status` mới — ràng buộc § 4 của sổ chủ nhà); câu trả lời cuối 465 ký tự,
  đủ bốn phần `Đã làm / Đang kẹt ở / Còn lại / Thử tiếp theo`.
- Lượt con chạm ngân sách (cha `79049fc16a2349e6866d892583ab64da`, `maxSteps 5`, `deadlineSeconds 300`): con `explore`
  `122a9a866b1342249b9affc749d9030d` **nhận** `maxSteps 5` / `deadlineSeconds 300` — bị kẹp theo **cha**, không phải số trần 40/300;
  notice của con `STEP_BUDGET_EXHAUSTED {diagnosisChars: 948, stepsUsed: 3, toolsRun: 2, maxSteps: 5, reservedSteps: 3, deadlineUsedMs: 14563}`;
  event `child` thứ hai mang về cha `{status: partial, answerChars: 948, is_error: false, reason: STEP_BUDGET_EXHAUSTED, diagnosis: true, stuckReason: STEP_BUDGET_EXHAUSTED}`;
  cha xong `turn_end {status: completed, stepsUsed: 2, toolsRun: 1, deadlineUsedMs: 24602}`.
- Hàng `X:` mới trong các lượt đo: **0** — cả hai ca chạm trần đều đóng bằng chẩn đoán, nên nhánh ghim blocker vào nhật ký
  không chạy (nhánh đó vẫn có bài khoá ở `test_limits_notice.py`, và nhãn máy `note: 'max-steps'` giữ nguyên).
- Mã cũ vẫn đọc được: `KNOWN_PREFIXES` giữ `MAX_STEPS` / `DEADLINE` cho bản ghi cũ; mã mới là `STEP_BUDGET_EXHAUSTED`,
  `DEADLINE_EXCEEDED`, `ANSWER_TOO_LONG`.
- `TURN_EMPTY_RESPONSE` (BUG-41) nay **thử lại một lần** trước khi chịu thua: lần thử lại ghim notice
  `TURN_EMPTY_RESPONSE_RETRY` kèm `attempt`/`how` và một hàng `system_log.write('turn.retry', reason='empty_response', …)`;
  nếu vẫn rỗng thì lỗi cũ được ném như trước. Trong các lượt đo của đợt này không lượt nào rỗng.

### Phần C — kế hoạch sạch theo tên (D-2, D-3, D-5)

- `migrate_plans.py --apply` nay **luôn** sao lưu từng byte vào `.plans-backups/<UTC>/` (kèm `manifest.json` có `sha256`) trước khi ghi;
  `--delete-orphan` từ chối (exit 2) khi còn bản ghi `P:` trỏ tới tệp; `--backup-dir DIR` chỉ đổi **chỗ** đặt bản sao, không tắt luật.
  Script và `upload_files.py` đã staged vào ảnh (lớp 5) cùng khối kiểm `10b-bis` của `smoke-test.sh`; quy trình ở
  `docs/plan/v22-plans-migration-runbook.md`, luật ở `docs/naming.md` § 7.
- Vé mơ hồ dùng một lần (D-3): lượt `write_plan` rơi vào dải jaccard 0,5–0,75 bị từ chối **một lần** kèm hàng `fact`
  `PLAN_IDENTITY_AMBIGUOUS: …`; gửi lại **nguyên văn** thì được nhận đúng một lần (`identityMatchedBy: 'ambiguity-ticket'`,
  `identityForcedNew: false`, `identityAmbiguity` ghim vào cả payload `plan_written` lẫn hàng `P:`), và vé **không rò** sang slug
  hay phiên khác. Ba bài trong `backend/tests/unit/test_write_plan.py` khoá cả ba chiều.
- `.session-history` giữ nguyên tên (D-5, `docs/naming.md` § 8): đo lúc ghi sổ **16 thư mục phiên / 23 tệp / 224 KB**
  (lần đo trước trong `naming.md`: 9/16/140 KB) — con số tự tăng theo phiên sống, đúng lý do không đổi tên.

### Phần D — trần độ dài câu trả lời (D-4)

- Hằng số trong `limits.py`: `ANSWER_WARN_CHARS = 60_000`, `ANSWER_MAX_CHARS = 150_000`; trần của plan không đổi
  (`PLAN_WARN_CHARS = 40_000`, `PLAN_MAX_CHARS = 150_000`).
- Cổng nằm ở ranh giới câu trả lời cuối: ≤ 60 000 ký tự không đổi gì; trong khoảng 60 000–150 000 ghim một notice
  `ANSWER_LENGTH_WARN` cùng hàng `system_log.write('answer.length', …)`; trên 150 000 cắt còn 150 000 ký tự, ghim **một** hàng `X:`
  nói rõ `chars`/`keptChars`/`limit` và lượt trả `partial`.
- Giao diện đi qua đúng bộ render notice sẵn có: `HarnessStepView.notice.test.tsx` khoá `data-notice-code="ANSWER_TOO_LONG"`,
  số `150000` trong chuỗi hiển thị và việc câu trả lời vẫn hiển thị đầy đủ.

### Phần E — ba bộ test, lượt sống, và ba phép kiểm bắt buộc

- `cd backend && .venv/bin/python -m pytest tests/unit -q` ⇒ **1 failed, 902 passed**. Bài đỏ duy nhất là
  `test_terminal_tools.py::test_terminal_exec_echo` — **có sẵn từ trước**, do `bash` của sandbox không có lệnh `Write-Output`
  (`Exited with code 127`), không liên quan đợt này.
- `-k "partial_budget or child_diagnosis"` ⇒ **15 passed**; ca bắt buộc của chủ nhà
  `test_child_diagnosis.py::test_budget_exhausted_child_returns_diagnosis` ⇒ **passed**.
- `-k "answer_length or plan_eval"` ⇒ **53 passed**; `-k "turn_attachments or partial_budget"` ⇒ **20 passed**;
  `-k "plan_registry or write_plan or plan_eval or file_tools or file_read"` ⇒ **152 passed**.
- `cd frontend && VITE_BOX_API_URL=http://localhost:8081 npx vitest run` ⇒ **118 tệp / 958 bài passed**;
  `npx tsc -b --noEmit` ⇒ **sạch**. Biến môi trường là cần thiết vì `frontend/.env.local` (tệp không được theo dõi, dùng cho
  đường xem trước) trỏ API về `"."`; với biến này, bài `src/lib/workspace/index.test.ts` cũng xanh.
- `cd deploy/docker && .venv/bin/python -m pytest tests -q` ⇒ **493 passed**.
- Ba phép kiểm **bắt buộc** của E3: (1) menu `+` bấm được — hit-test `true` ở **cả bốn** mục; (2) tệp vào box **đúng byte** —
  `6.md`/`7.md` khớp `diff`, đường dẫn thật có trong event `user` **và** trong ngữ cảnh gửi model; (3) chẩn đoán khi chạm trần —
  notice `STEP_BUDGET_EXHAUSTED` có `diagnosis: true` và câu trả lời cuối đủ bốn phần.

### Khẳng định cố ý đổi (E1)

Danh sách đầy đủ nằm trong PR của đợt này; các điểm chính: `test_failure_classification.py` (hết hạn ⇒ `DEADLINE_EXCEEDED`),
`test_limits_notice.py` (tiền tố hàng nhật ký `STEP_BUDGET_EXHAUSTED:` và ca kẹp trần mới), `test_child_truncation.py`
(`partial_turn`), `test_compaction_events.py` (`turn_end` thêm `stepsUsed`/`toolsRun`/`deadlineUsedMs`),
`test_session_length_payload.py` (`stepsClamped` trong `sessionMetrics`), `test_harness_runtime.py`, `test_delegation_contract.py`
(ca kẹp ngân sách con), `test_worker_session_ops.py` (bốn → **năm** op vì A7 thêm `uploads_prune`), và
`frontend/src/components/chat/ChatInputBar.controlSend.test.tsx:142` (`toHaveBeenCalledWith('/skill', undefined, undefined)`).

### Bằng chứng của vòng

- Ảnh: `images/foundation_e2e_01_chip.png` (chip `foundation-e2e-ui.md 1 KB` trong ô soạn tin),
  `images/foundation_e2e_02_sent.png` (sau khi gửi), `images/foundation_e2e_03_menu.png` (menu `+` đủ bốn mục, Drive nói thật
  "chưa kết nối"), `images/foundation_e2e_04_answer.png` (bong bóng người dùng có chip `7.md`, câu trả lời `done`).
- Phiên: `c4cf5256…` (lượt qua giao diện, hai lượt có tệp), `92f76c90467d4dfaaa3bbb3d40278069` (lượt API không ngữ cảnh cũ),
  `43b363cc79f04e84a86af7c1f02db757` (40/300), `1cbb482079de430091e2de76f18144ae` (chạm trần bước), `2e92c824…` (kẹp 999),
  `79049fc16a2349e6866d892583ab64da` (cha gọi con) + con `122a9a866b1342249b9affc749d9030d`.
- Tệp đo: `/var/tmp/foundation-e2e.md`, `/var/tmp/foundation-e2e-ui.md`; bản chụp `X:` = 0 hàng nên không có tệp nhật ký kèm theo.
- Ảnh chụp bằng agent-browser 0.21.2 (phiên `foundation`); lượt API bằng `curl` tới `http://127.0.0.1:3102` với
  `X-BoxFox-Admin: 1` và `Origin: http://localhost:3100`.
### Đợt kiểm thử độc lập (cùng PR) — ba lỗi nữa trong mã mới, đã sửa và đo lại

Diff `main...vorflux/v22-foundation` (HEAD `f57619d`) được kiểm thử lại độc lập theo hợp đồng tám mục: phân loại thay đổi
(BROAD / FULL-FEATURE), 15 ca bám đúng phạm vi đợt này, mỗi ca chạy trên hệ thống thật (harness `:3102`, router `:3101`,
Vite `:3100`, box `agentbox-box`), không ca nào chạy lại tính năng cũ không bị sửa. Kết quả và số đo:

- **Menu `+` (T1)** — hit-test tại tâm **cả bốn** mục trả `true`; `menuRect [283,598,240,245]`; `overflowClipAncestor: null`
  (vòng 21: `itemRect [290,642,226,45]` rơi vào khung chat); mục Drive `disabled: true` + `aria-disabled: true`, chữ
  "Chưa kết nối — không đính kèm được tài liệu Drive", bấm **không** có tác dụng (không `onAttach`); ba input ẩn đúng
  (`accept=image/*` nhiều tệp, tệp, `webkitdirectory`).
- **Tải tệp (T2)** — 75 B ⇒ `.uploaded_artifacts/8.md`, md5 khớp hai phía; **13** phép thử biên đúng thiết kế (202 cho
  `absolutePath: /etc/passwd` và tên 500 ký tự; 400 cho `/etc/passwd`, `../../etc/passwd`, `.uploaded_artifacts/../8.md`,
  NUL, hàng không phải dict, `sizeBytes` −1/`true`/`"75"`, dict thay vì mảng, **26 tệp** trong một lượt); ngữ cảnh gửi model
  kết bằng khối `[Tệp đính kèm đã lưu trong box]` với đường dẫn tuyệt đối, chuỗi `[Attached Files: …]` của BUG-40 **không còn**;
  26 MiB kèm `Content-Length` thật ⇒ **413**, đúng 25 MiB ⇒ **200**, `mkdirs=1` ⇒ `.uploaded_artifacts/deep/tree/deep.md`.
- **Lượt qua giao diện (T3)** — phiên `83bfa5a5d7044cdcaa05448ca62675e4`: chip `attach-ui3.md 1 KB`, bong bóng người dùng
  mang chip `16.md · .uploaded_artifacts/16.md` (tiêu đề chip có đường dẫn tuyệt đầy đủ), tệp trong box **khớp md5**
  (`764fb74e475daa1fd69f2f04fe87cf39`), ngữ cảnh model mang `- /home/agent/workspace/.uploaded_artifacts/16.md (16.md, 64 B)`.
  Lượt model sống (`muse-spark-1.3-contributor-free`, phiên `74630e53…`) gọi `file_read` rồi in **đúng dòng 2** của tệp —
  chứng minh trực tiếp BUG-40 đã hết; lượt này `turn_end {step 2, stepsUsed 2, deadlineUsedMs 4097}`.
- **Bốn lượt tải song song (T4)** — số `12, 13, 14, 15`, `uniq -d` rỗng, mọi md5 khớp nguồn, chủ `agent`.
- **Ngân sách (T5, T5b, T6, T7)** — `runtime-info` ⇒ `{40, 60, 180, 600, 40, 300}`; `maxSteps: 999, deadlineSeconds: 9999`
  ⇒ áp 60/600 với **đúng một** `STEPS_CLAMPED {requested: 999, applied: 60}` và một `DEADLINE_CLAMPED`; `maxSteps: 4`
  ⇒ một notice `STEP_BUDGET_EXHAUSTED {diagnosis: true, diagnosisChars: 320, stepsUsed: 2, toolsRun: 1, reservedSteps: 3}`,
  câu trả lời cuối đủ bốn phần; bốn bước xong rồi mới hết ⇒ hàng `X:94b9a926-2` (`status: blocked`, `maxSteps: 4`);
  con nhận **`min(con, cha)`** đo ở ba cha (`60/600` ⇒ con `40/300`; `5/120` ⇒ con `5/120`, cha thấy
  `{status: partial, answerChars: 320, diagnosis: true, is_error: false}`; cha `8/60` gặp lỗi nhà cung cấp ⇒ con
  `{status: failed, answerChars: 0, last_error: UPSTREAM_HTTP_500 … [after 3 retries in 15.3s]}`).
- **Trần độ dài câu trả lời (T10)** — 200 000 ký tự ⇒ câu trả lời cuối **150 097** ký tự, **đúng một** hàng
  `X:845246c5-3`, `turn_end {status: partial}`; 70 002 ký tự ⇒ chỉ `ANSWER_LENGTH_WARN`, `completed`; 12 000 ⇒ không notice.
- **`TURN_EMPTY_RESPONSE` (T12)** — thử lại **đúng một lần** với `toolChoice: 'required'` (tools 22, `maxTokens 4096`),
  biến thể `how: 'plain-text'` khi model mức `low` (tools 0), và ca cả hai lần rỗng ⇒ `error {code: TURN_EMPTY_RESPONSE}`;
  mỗi lượt thử lại một hàng `system_log` `turn.retry {reason: 'empty_response'}`.
- **Tệp nhị phân, dọn tệp, đường bảo vệ (T11)** — `file_read` trên PNG 154 578 B ⇒ `encoding: 'base64'`,
  `bytesRead: 22500`, `truncated: true`, tiền tố khớp byte trên đĩa (trước đây `UnicodeDecodeError` giết cả lượt);
  `uploads_prune` trên fixture 203 tệp ⇒ bỏ 3 tệp / 21 B, giữ đúng mốc `203.md`, **một** hàng `X:` `kind: blocker,
  status: done, actor: box-retention`; `POST /__box/files/delete` trên `.uploaded_artifacts` và `.plans` ⇒ **409** "mục được
  bảo vệ", thư mục con thì cho phép (`200`, `.trash/1790085372-deep`).
- **Kế hoạch (T8, T9)** — trên bản sao: `--apply` sao lưu **từng byte** (`sha256` ba tệp khớp), chạy lại ⇒ `nothingToDo`,
  `--backup-dir` không ghi được ⇒ **rc 2** và `.plans` không đổi byte nào, `--delete-orphan` từ chối (rc 2) khi còn hàng `P:`,
  liên kết tượng trưng bị bỏ qua và không bị đi theo. Sống (phiên `629dfc6eced347f995b0da3c603aecb5`): vé mơ hồ dùng
  **một lần** — lượt 1 từ chối + hàng `F:` với `score 0.6667` (jaccard `{boxfox, upgrades}/{boxfox, 5, upgrades}` = 2/3),
  lượt 2 **nguyên văn** được nhận và ghim vé vào hàng `P:`, lượt 4 với slug khác sinh vé mới (không rò), lượt 5 ghi `v2`.
- **Ba bộ test (T14)** — `backend/tests/unit`: **1 failed, 920 passed** (bài đỏ sẵn có `test_terminal_tools.py::test_terminal_exec_echo`,
  `Exited with code 127`); `-k "partial_budget or child_diagnosis"`: **16 passed**; `-k "plan_eval or plan_registry or write_plan"`:
  **142 passed**; `deploy/docker`: **496 passed** (493 + ba bài mới của BUG-45/BUG-46); frontend `VITE_BOX_API_URL=http://localhost:8081
  npx vitest run`: **118 tệp / 958 bài passed**; `npx tsc -b --noEmit`: **sạch**.
- **Ba lỗi trong chính mã mới** (BUG-45…BUG-47, bảng ở `bug-register.md` § 6.23, đều đã sửa kèm test): `prune` nuốt `OSError`
  ⇒ nay trả `failedFiles: 3` + `deletionFailures` + hàng `X:f2f01657-1` (đo lại **trên box**); hai lượt `--apply` cùng giây
  ⇒ nay `2026-09-22T14-04-42Z` và `2026-09-22T14-04-42Z-2`, `manifest.json` của lượt đầu còn nguyên; câu từ chối
  `header-mismatch` in "khai vv2" ⇒ nay `khai v2; harness sẽ ghi v3`, và khối **sai cú pháp** được gọi đúng tên
  (`không đúng cú pháp (đọc được: Version: v2, Identity: kettle-lantern)`), đo lại **sống** sau khi khởi động lại harness
  trên cây đã vá (phiên `a588b1c460944116b8cde73e03319071`, bốn lượt gửi).
- **Bằng chứng của đợt kiểm thử**: ảnh `images/v22_01_menu.png` (menu `+` sau portal, mục Drive mờ), `images/v22_02_chip.png`
  (chip trong ô soạn tin), `images/v22_02b_typed.png` (đã gõ, nút gửi bật), `images/v22_03_sent.png` (bong bóng người dùng
  mang chip + câu trả lời) và **một clip liên tục** `recordings/v22_composer.webm` (50,7 s) phủ cả sáu bước.
- **Bàn giao, không sửa** (ngoài phạm vi đợt này): (1) tải lên kiểu `Transfer-Encoding: chunked` **không** có `Content-Length`
  trả **200** với tệp 0 byte — đo được **trên `main` y hệt** (nhánh upload chỉ đọc `size_hint = Content-Length`), nên là lỗi
  có sẵn chứ không phải hồi quy; (2) `sizeBytes` do client khai được in nguyên vào nhãn kích thước cho model (khai 999 999
  cho tệp 75 B ⇒ "977 KB") — chỉ là nhãn; (3) `formatAttachmentSize(84)` trả `1 KB` (sàn 1 KB) trong khi khối cho model ghi
  `84 B`; (4) `maxSteps: 0` bị kẹp im lặng về 1 vì `max(1, …)` chạy trước phép so sánh; (5) hàng `command_invocations`
  giữ `result.status = 'running'` sau lượt lệnh thành công (`main` y hệt, không nơi nào đọc ngoài phép kiểm idempotency);
  (6) router chưa chuyển được một luồng nhà cung cấp **rỗng hoàn toàn** (`engine.mjs` đòi `finishReason`) nên nhánh B8 chỉ
  tới được bằng nội dung chỉ có khoảng trắng.
- **Soát engine và vá trước khi gộp** (bản soát độc lập thứ ba, `v22-review-engine3`: **5/10 — Medium**,
  "ship with mitigations"): bốn phát hiện đã vá trên chính nhánh này, mỗi phát hiện một bài kiểm mới —
  (1) cổng chẩn đoán của hạn chót hỏi `partial_turn(sid)`, hàm này quét **mọi** notice bền của **phiên**, nên một phiên
  từng có lượt dở nào đó thì mọi hạn chót sau đó bỏ luôn đường chẩn đoán và đóng lượt bằng `failed` trắng — đúng thứ
  B4/BUG-42 dựng lên để xoá; nay là cờ theo **lượt** (`turn_partial`, bài `test_a_later_turn_still_gets_the_deadline_diagnosis`);
  (2) con của đường lệnh/kỹ năng (`skills/runtime_commands._command_task`) không truyền `maxSteps` nên rơi về mặc định
  40 bước — **rộng hơn cha** khi phiên đặt ít bước; nay mọi con đi qua `clamp_child_budget()` ngay trong `create()`, nên
  đường CLI của `/claude-code` cũng bị phủ (`test_command_child_never_gets_more_steps_than_the_session`, và bài
  "con lấy đúng ngân sách thời gian của phiên" cũ vẫn xanh vì trần engine của phiên là 600 s);
  (3) câu chốt trong cửa sổ giữ chỗ vào thẳng transcript mà **không** qua cổng độ dài D2 ⇒ một câu 200 000 ký tự lọt
  trần 150 000; nay `finish_partial` gọi `enforce_answer_length` trước khi lưu
  (`test_a_diagnosis_is_never_stored_past_the_length_ceiling`); (4) `partial_turn` không quét `ANSWER_TOO_LONG` nên cha đọc
  một con bị cắt là `completed` trọn vẹn trong khi `turn_end` của chính con nói `partial` — nay cùng nhóm
  (`test_a_cut_answer_is_partial_for_the_parent_too`). Ba phát hiện còn lại của bản soát (cửa sổ giữ chỗ chỉ cần **độ dài**
  ≥ 80 ký tự là mở, không đòi dấu hiệu chẩn đoán; lượt dở khi chưa có bước nào đang mở thì thiếu hàng `turn_end` nên
  `stepsUsed`/`toolsRun` không tới bàn điều khiển; vé mơ hồ của plan ghim theo `(slug, thư mục)` chứ **không** theo nội dung
  plan) **không** vá trong đợt này — ghi ở mục "phản hồi ngoài phạm vi" của PR #3.
  Bốn điểm vá được đo lại **sống** trên hai tiến trình thật (harness PID 119915 giữ cây `3865d9c` cho phép đo "trước", rồi
  PID 137585 trên cây `7a7befd`): phiên `maxSteps: 3 / deadlineSeconds: 5` — lượt 2 *trước* là `turn_end {status: "error"}` +
  `error {DEADLINE_EXCEEDED}`, hàng `sessions` `failed`, không câu trả lời; *sau* là `turn_end {status: partial,
  diagnosis: true, deadlineUsedMs: 5254}` + notice `DEADLINE_EXCEEDED {diagnosisChars: 320, readToolCalls: 2}`, hàng
  `sessions` `completed`, không event `error`. Lượt `/explore` trên phiên 12 bước: *trước* con `40` bước — **rộng hơn cha**;
  *sau* con `12` bước kèm dòng `session.child_budget_clamped {requestedSteps: 40, steps: 12, deadlineSeconds: 600}`, còn
  phiên `60/600` vẫn cho con `40/600` (luật D-15 và luật thừa hưởng hạn chót của đường lệnh không đổi). Bộ `deploy/docker`
  (**496 passed**) và frontend (**118 tệp / 958 bài**) chạy lại trên `7a7befd`: không hồi quy.
- **Lệch nguyên văn so với kế hoạch ở C4 (đợt 1)** — C4 mục 3 viết "Nhóm *dữ kiện bền* trong `brief()` cũng hiện câu này cho
  model"; kiểm lại mã: `journal.group_rows` chỉ có **sáu** nhóm (`goal`, `done`, `doing`, `open_decisions`, `blocked`, `next`)
  và hàng `fact` của vé không rơi vào nhóm nào (nhánh `decision` đòi `kind == 'decision'`), nên câu vé **không** tới model.
  Thứ tới model là **câu từ chối** đã đổi ở mục 6 ("khai báo `identity` mới rõ ràng, **hoặc** gửi lại nguyên văn"), và đường
  gửi lại nguyên văn chạy đúng như kế hoạch (T9: vé tiêu đúng một lần, `score 0.6667`). Hành vi đạt yêu cầu, một câu trong
  kế hoạch thì không; chủ nhà quyết có sửa cho đúng nguyên văn hay không (giữ sáu nhóm hay gộp hàng `fact` vào nhóm có sẵn —
  `group_rows` đang ghi rõ "không thêm nhóm thứ bảy"). **Đã sửa ở đợt 2 (T8+T9)**: `journal.group_rows` xếp hàng vé
  (`kind='fact'` mang `data.identityAmbiguityTicket`) vào nhóm **đang tắc** — vẫn đúng sáu nhóm, hàng `fact` thường vẫn không
  vào nhóm nào; ca kiểm `test_hang_ve_mo_ho_roi_vao_nhom_dang_tac_con_fact_thuong_thi_khong` ghim cả hai nửa.
- **Dấu vết đo để lại** (đợt kiểm thử, không phải bản ghi sản phẩm): `.plans` **thêm** `v1/v2-boxfox-upgrades-two.md`,
  `v1/v2-kettle-lantern.md`, `v1-fix4-real-version.md`; hai tệp gốc `v1-agent-box-plan.md` / `v1-boxfox-5-upgrades.md`
  **không đổi một byte** (sha256 `30e05800…` / `4831506b…`); `.uploaded_artifacts` thêm `8.md`…`16.md`, `11.png`,
  `big26c.bin` (0 B, phép thử chunked), `exact25.bin` (đúng 25 MiB); `deep/` đã bị đưa vào `.trash/1790085372-deep` bởi
  chính phép kiểm đường bảo vệ.

## Vòng 22 — đợt 2 (mesh agent con): sổ con, giao hàng có định tuyến, chờ bạn, chi phí theo lượt (2026-09-22, tối)

- Phạm vi (đợt 2 của kế hoạch `docs/plan/v22-boxfox-plan.md`, việc T1–T18; T14 là việc **tuỳ chọn** để lại vòng sau theo D-13):
  (T1–T4) sổ con + bảng giao hàng + bộ đếm lượt một chiều và bảng Sub-agents theo **từng lượt**;
  (T5–T7) fan-out theo cha giữ trần toàn cục, `delegate_task(wait=false)`, hết lượt cha thì con dừng;
  (T8–T10) `peer_read`, `await_children`, watchdog; (T11–T12) `deliverTo` + biên nhận idempotent và bơm kết quả vào vòng bước;
  (T13) chi phí theo lượt + trần + công tắc; (T15) giao diện chờ/giao/nhận; (T16) chuỗi đầu-cuối trên runtime thật;
  (T17) chạy sống và thu bằng chứng; (T18) tài liệu (mục này, `bug-register.md` § 6.24, `owner-decisions.md`, ADR-0003).
- Cách chạy: router 3101 + harness 3102 (khởi động lại trên mã mới) + Vite 3100 + box `agentbox-box` đang chạy; ảnh box **không**
  dựng lại (`worker.py` gửi nội tuyến mỗi lần gọi). Lượt sống qua API (`POST /api/agent/sessions/{sid}/turns`) và qua giao diện
  (agent-browser 0.21.2); xem trước `localhost:3100`. Model: OpenCode Free `muse-spark-1.3-contributor-free`. Mọi số dưới đây đọc
  thẳng `~/BoxFox/harness/sessions.sqlite` hoặc in ra từ chính lượt chạy.
- Kết quả: **T1–T13 và T15–T18 xong**, T14 để lại vòng sau (D-13). Nhóm test peer **113 passed / 898 deselected** (38,02 s);
  ba ca chuỗi đầu-cuối (`backend/tests/integration/test_peer_mesh_chain.py`: 2 ca offline + 1 ca sống opt-in); giao diện
  **2 tệp / 15 ca**. Chuỗi sống chạy xanh — hai con cùng lượt 1, hai biên nhận `injected`, cha chờ **10 869 ms** rồi `done` —
  và lượt sống đo chi phí xác nhận `children.steps_used` / `output_tokens` **bằng tổng chuỗi bước** của chính con đó.
  **Năm khiếm khuyết** lộ ra trong lúc thi công: BUG-48, BUG-49, BUG-50 và BUG-52 (đã sửa) cùng BUG-51 (ghi nhận, chưa sửa —
  xem Phần 6); bốn ca đầu đo được trên lượt **sống**, BUG-52 lộ ra khi rà lại bộ đếm của T13.

### Phần 1 — Sổ con, bộ đếm lượt, bảng Sub-agents theo từng lượt (T1–T4)

- **Sổ con** là bảng `children` trong `~/BoxFox/harness/sessions.sqlite`:
  `(session_id PK, parent_id, parent_turn, spawn_step, role, goal, status, reason, deliveries, waiting_for, waiting_since,
  started, finished, steps_used, output_tokens, answer_chars)`. **Bảng giao hàng** là `child_deliveries`
  `(id, child_id, recipient, recipient_turn, kind, state, chars, truncated, created, injected, skip_reason)` với
  `UNIQUE(child_id, recipient, recipient_turn)` — đó là thứ làm biên nhận **idempotent**.
- **Bộ đếm lượt một chiều**: `sessions.turn_count` chỉ tăng; mọi event của một lượt mang `turn`, kể cả cặp event `child` mở/đóng
  (đo sống: hai event `child` mở và hai event `child` đóng của lượt 1 đều mang `turn: 1`), và `system_log.write(..., turn=…)`
  nhận cùng con số. `child` event mang thêm `step` (bước cha đã sinh con).
- **BUG-43 đã sửa**: bảng Sub-agents tách theo **từng lượt**. DOM sống có `data-testid="subagents-turn-scope"` với chip
  `Lượt 1 · 2` và nút `tất cả lượt`, khối theo lượt `subagents-turn-block` ("Lượt 1 · 2 con / N steps / …"), hàng con mang
  `lượt 1 · bước 1 · N steps used`. Test: `SubagentInspectorPanel.turns.test.tsx`.

### Phần 2 — Fan-out theo cha, uỷ thác bất đồng bộ, dọn con (T5–T7)

- Trần cũ là **một** `Semaphore(3)` dùng chung cả tiến trình. Trần mới: `FANOUT_PER_PARENT_DEFAULT = 3`,
  `FANOUT_PER_PARENT_MAX = 6` (qua `BOXFOX_PEER_FANOUT`), giữ **trần toàn cục** `FANOUT_GLOBAL_CEILING = 8`; hết chỗ thì sau
  `FANOUT_QUEUE_WAIT_SECONDS = 30` model nhận lỗi tool `FANOUT_BUSY` — lượt **không** treo vì hết slot. Trần thứ hai
  `CHILDREN_PER_TURN_MAX = 12` (mã `CHILDREN_PER_TURN_EXHAUSTED`) chặn vòng lặp sinh con trong một lượt 40 bước.
- `delegate_task(wait=false)` sinh con rồi trả về ngay; đường đóng sổ của nó là `close_detached_child` (xem Phần 5 vì đây chính
  là đường mà lượt sống đi qua).
- Hết lượt cha ⇒ `reap_children(sid, reason='PARENT_TURN_ENDED')` đóng mọi con còn `started`. Đo sống trong lượt đo chi phí:
  con `testing` (`944d6bde…`) được đóng bằng `PARENT_TURN_ENDED` **2,2 ms sau** khi lượt cha phát event `finish`
  (`finish` ở `1790100321.0228`, hàng con `finished` ở `1790100321.0249`) — đây là gốc của BUG-51.

### Phần 3 — Con nhìn thấy nhau: `peer_read`, `await_children`, watchdog (T8–T10)

- `peer_read` cho con đọc luồng của bạn cùng cha (có cắt theo `PEER_WAIT_RESULT_CHARS = 16 000`). `await_children` nhận
  `targets` dạng `role:<vai>` hoặc mã phiên, `mode` `any`/`all`, và `timeoutSeconds` bị kẹp ở trần
  `PEER_WAIT_MAX_SECONDS = 300` kèm notice `PEER_WAIT_CLAMPED`.
- **Chờ bằng sự kiện, không chờ đồng hồ** (D-12): hàm ngủ tới khi **biên nhận giao hàng** được ghi và tỉnh dậy trong cùng nhịp;
  ba con số 300 s (`PEER_WAIT_SAFETY_SECONDS`, `PEER_WAIT_MAX_SECONDS`, `PEER_WAIT_TOTAL_MAX_SECONDS`) là **lưới an toàn**.
  Chạm lưới ⇒ `peer_wait_end` mang `status='timeout'`, lượt **không** bị đánh `failed`. Giao diện in đúng câu đó: hàng con hiện
  `đang chờ review giao kết quả· lưới an toàn còn 5:00`.
- **Watchdog** (`peer_watchdog.py`, quét mỗi `WATCHDOG_TICK_SECONDS = 10`) đóng ba loại hàng còn sót: quá
  `CHILD_WALL_MAX_SECONDS = 900` ⇒ `WATCHDOG_TIMEOUT` (huỷ task), hàng `started` của tiến trình **trước** ⇒ `RESTART`
  (không chạy lại thao tác tool), con mồ côi ⇒ `ORPHAN`. Quá `300 + PEER_WAIT_FORCE_GRACE_SECONDS = 30` giây chờ thì watchdog
  **đánh thức cưỡng bức** người đang chờ.

### Phần 4 — Giao hàng có định tuyến và wake-up (T11–T12)

- `deliverTo` nhận tối đa `PEER_DELIVER_MAX = 4` địa chỉ, mỗi địa chỉ là `role:<vai>`, `peer:<sid>` hoặc `main`. Giao hàng
  **phân giải MỘT lần** lúc con đóng sổ: một địa chỉ chưa tồn tại thành hàng `skipped` kèm `reason` và **không** được dò lại.
  Cửa sổ dò (`PEER_TARGET_POLL_SECONDS = 1.0` giây, tối đa `PEER_TARGET_GRACE_SECONDS = 20` giây) nằm ở phía **người CHỜ**
  (`await_children`) — nơi anh em có thể được sinh ngay sau lời gọi; người GỬI thì không dò, vì nó đã đóng sổ và không còn việc gì
  để làm tiếp. Kết quả đi vào lượt kế của người nhận **đúng một lần** nhờ khoá duy nhất; hàng biên nhận đi `pending` → `injected`
  (hoặc `skipped` kèm `reason`).
- **Wake-up**: kết quả của bạn vào **vòng bước kế tiếp** của lượt đang chạy — người dùng không phải gửi thêm một câu để thấy kết quả.
  Đo sống: event `peer_delivery` mang `state='injected'` và bước kế của người nhận nhận khối kết quả trong `messages`.
- **Luật chờ của cha** (BUG-48, xem Phần 6): cha chờ con ruột **đã đóng sổ** thì xong ngay, không cần biên nhận; bạn cùng cha
  giữ luật cũ — đóng sổ mà chưa giao là **chưa** giao.

### Phần 5 — Chi phí theo lượt (T13)

Bảng đọc thẳng sổ (`sổ con` là nguồn chân lý; `chốt-cuối` là ảnh chụp tại thời điểm lượt phát `finish`):

```text
phiên                              trạng thái  lượt bước cha token cha chờ (ms)  con  bước con  token con  biên nhận chốt-cuối (con/bước/token)
bb142655d9634b7f86270717b985e3fb   completed   1    3        1376      300001    2    30        17602      1         2/19/12509
19271d91159d42b58935b7423c452115   completed   2    6        3844      421994    4    54        6346       3         4/54/6346
e94f1af064254fef8a0e5b681db7db1f   failed      1    3        1107      None      2    9         2097       2         —
3647fe8e3e8f43d79e9753a4c2cdb463   completed   1    6        1069      209208    2    10        0          2         2/10/0
62146c6e498d41f4b662d8295d91054e   failed      1    1        0         None      0    0         0          0         —
b4f26ca6e8c44f458cceb5ba86e87e34   failed      1    3        984       None      2    2         0          2         —
```

- **Sửa lỗi đếm token (BUG-49)**: dòng `3647fe8e…` là lượt sống trước bản vá — hai con chạy 10 bước mà `token con = 0`.
  Hai dòng đầu chạy sau bản vá: `bb142655…` con `review` **19 bước / 12 509 token**, `19271d91…` bốn con **54 bước / 6 346 token**.
- **Kiểm chứng theo từng con** (`/var/tmp/v22/t13_verify_cost.py`): với mỗi con, `children.steps_used` = `max(turn_end.stepsUsed)`
  và `children.output_tokens` = `sum(turn_end.outputTokens)` của **chính luồng con đó** — lượt sống `bb142655…`:
  `review 19/19 bước, 12 509/12 509 token OK`; `testing 11/11 bước, 5 093/5 093 token OK`.
- **BUG-51 (chưa sửa)**: `finish` đọc sổ con **trước** khi `reap_children` đóng những con còn `started`, nên ảnh chụp thiếu đúng
  phần của con bị reap — `bb142655…`: sổ 30 bước / 17 602 token, `finish` 19 bước / 12 509 token, lệch 11 bước / 5 093 token.
- **Công tắc và trần** (mọi env đọc lại **mỗi lần hỏi**, đổi có hiệu lực ngay): `BOXFOX_PEER_MESH=off` tắt cả mesh
  (`peer_mesh_enabled()` — không tool peer, uỷ thác chặn như bản trước đợt 2); `BOXFOX_PEER_FANOUT=1` hạ về một con mỗi cha;
  `BOXFOX_PEER_WAIT_MAX=<giây>` chỉ **hạ** trần chờ. Cờ `parallelReadTools` (Q3/T14) không đổi hành vi ⇒ đi kèm notice
  `PEER_MESH_NOTICE`.

### Phần 6 — Năm khiếm khuyết lộ ra khi thi công (BUG-48 … BUG-52)

- **BUG-48 — mức Cao — cha chờ chính con ruột đã đóng sổ, lượt treo tới lưới an toàn.** `peer_wait_pending` coi một mục tiêu là
  xong chỉ khi có biên nhận của người chờ; mà T11 chỉ ghi biên nhận cho `main` khi con **khai** `deliverTo`. Cách gọi tự nhiên
  nhất của cha — `await_children()` trần, con ruột không khai người nhận — vì thế trả `timeout` cho đúng những đứa con đã chạy
  xong. Sửa (`fa6a2b7`): `peer_is_own_closed_child` xét **con ruột đã đóng** là đã xong, và `deliver_child_result` đánh thức cha
  ngay lúc con đóng sổ khi con khai người nhận rỗng. Bạn cùng cha giữ luật cũ. Test:
  `test_await_children.py::test_await_children_cha_khong_can_bien_nhan_tu_con_ruot_da_dong_so` (đo được `elapsed < 1,0 s`
  thay vì chờ hết lưới).
- **BUG-49 — mức Cao — chi phí của con ghi thiếu (và ghi `NULL` khi bước cuối không có `usage`).** Hai đường đóng sổ của con
  (`close_detached_child` cho mọi con `wait=false`, và đường cha-chờ-con trong `_run_child`) chỉ lấy `turn_end` **cuối cùng**,
  nên `steps_used`/`output_tokens` là số của **một bước**, và là `NULL` khi bước cuối là bước chẩn đoán `partial` không mang khối
  `usage`. Đo sống: phiên `3647fe8e…` con `review` 9 bước mà hàng sổ con `output_tokens = NULL`, `childTokens` của lượt cha báo
  **0**; phiên `46c47921…` con `review` 5 bước, sổ ghi **1 076** trong khi tổng luồng là **2 877**. Sửa (`51a1af7`):
  `SessionStore.child_usage_from_events` đọc **cả chuỗi** `turn_end` (`stepsUsed` lấy `max` vì là số luỹ kế, `outputTokens`
  cộng theo bước), `child_close_once` ghi được bộ số, và event `child` kết thúc mang theo `stepsUsed`/`outputTokens`.
  Test: `test_peer_cost.py::test_token_cua_con_cong_ca_chuoi_buoc_khong_chi_buoc_cuoi` và
  `test_async_delegation.py::test_con_tu_xong_cung_cong_token_ca_chuoi_buoc`.
- **BUG-50 — mức Trung bình — nhãn chờ in `[object Object]`.** Sự kiện thật `peer_wait` mang `targets` dạng **vật thể**
  (`[{'sessionId': …, 'role': …}]`) còn `peerLabel` chỉ biết chuỗi. Đo sống trên DOM của panel (phiên
  `e94f1af064254fef8a0e5b681db7db1f`): `đang chờ [object Object] giao kết quả· lưới an toàn còn 5:00`. Sửa (`5a084f6`):
  `peerLabel` đọc vật thể trước — lấy chuỗi không rỗng đầu tiên trong `role`, `roleId`, `sessionId`, `name` (đệ quy), trả chuỗi rỗng
  khi không đọc được, **không bao giờ** trả `[object Object]`. Sau khi sửa, cùng kịch bản sống (phiên `19271d91…`, lượt 2):
  `đang chờ review giao kết quả· lưới an toàn còn 5:00` (ảnh `images/t17ui_15_child_wait_fixed.png`, ảnh trước khi sửa:
  `images/t17ui_10_child_wait.png`). Test: `frontend/src/lib/chat/peerPipeline.test.ts` (4 ca) + một ca trong
  `SubagentInspectorPanel.turns.test.tsx` khẳng định huy hiệu **không** chứa `[object Object]`.
- **BUG-51 — mức Thấp — `finish` đọc sổ con trước khi reap, nên thiếu phần của con bị reap.** `reap_children` chạy trong khối
  `finally` của `_run`, tức **sau** khi event `finish` đã phát; một con còn `started` lúc lượt đóng vì thế không có mặt trong
  `childSteps`/`childTokens` của lượt. Đo sống (phiên `bb142655…`): `finish` ở `1790100321.0228` ghi `2/19/12 509`, hàng con
  `testing` đóng ở `1790100321.0249` bằng `PARENT_TURN_ENDED` với `11` bước / `5 093` token — lệch **2,2 ms**. Số trong sổ con
  vẫn **đúng**; chỉ ảnh chụp ở `finish` thiếu. **Chưa sửa trong đợt này** (đổi thứ tự reap/finish là thay đổi cấu trúc ở đường
  đóng lượt, làm muộn vòng này là rủi ro không cần thiết); hướng sửa để vòng sau: reap trước khi phát `finish`, hoặc phát thêm
  một event hiệu chỉnh sau reap.
- **BUG-52 — mức Trung bình — ngân sách chờ 300 s của "mỗi lượt" thực ra là mỗi PHIÊN.** `wait_extension` chỉ được cộng thêm mỗi
  lần chờ mà **không bao giờ** đặt lại, nên lượt thứ hai của phiên thừa hưởng ngân sách đã tiêu của lượt thứ nhất: chờ đủ 300 s ở
  lượt một thì mọi lượt sau trả `extensionExhausted` ngay. Lỗi lộ ra khi rà lại bộ đếm của T13, không từ triệu chứng người dùng
  báo. Sửa (`a21c598`): `_run` đặt `wait_extension[sid] = 0.0` ngay sau khi xác định số lượt. Test:
  `test_peer_cost.py::test_ngan_sach_cho_ve_khong_o_moi_luot`.

### Phần 7 — Số đo kiểm thử của đợt

- Nhóm peer: `.venv/bin/python -m pytest backend/tests/unit -q -k "peer or delivery or child or delegate or watchdog or cost or async"`
  ⇒ **113 passed, 898 deselected in 38,02 s**. Riêng cụm sổ con/giao hàng/watchdog/chờ:
  `test_async_delegation.py test_peer_watchdog.py test_peer_cost.py test_peer_registry.py test_delivery_routing.py
  test_delivery_injection.py test_await_children.py` ⇒ **71 passed in 25,35 s** (ảnh chụp **trước** khi thêm hai ca chi phí của BUG-49; chạy lại cùng bộ đó hôm nay được **73**); sau khi thêm hai ca chi phí:
  `test_peer_cost.py test_async_delegation.py` ⇒ **22 passed in 9,99 s**.
- Chuỗi đầu-cuối trên runtime thật: `backend/tests/integration/test_peer_mesh_chain.py` ⇒ **2 passed, 1 skipped in 4,51 s**
  (ca sống bị bỏ qua khi thiếu `BOXFOX_LIVE_PEER_MESH=1`); bật `BOXFOX_LIVE_PEER_MESH=1` ⇒ **1 passed, 2 deselected in 24,39 s**.
- Giao diện: `npx vitest run src/lib/chat/peerPipeline.test.ts src/components/panels/SubagentInspectorPanel.turns.test.tsx`
  ⇒ **2 tệp, 15 ca đạt in 1,31 s**.

### Phần 8 — Bằng chứng sống của đợt

- Chuỗi sống xanh (`/var/tmp/v22/t17_live_chain3.log`, exit 0; phiên `8539b60acd7f4187936d0a4f0ab99582`):

```text
[SỐNG] phiên 8539b60acd7f4187936d0a4f0ab99582 — completed, 2 con, 2 biên nhận
  con testing   lượt 1 bước 1 → completed steps=2 tokens=505
  con review    lượt 1 bước 1 → completed steps=1 tokens=291
  biên nhận peer → 38aaead1 injected
  biên nhận main → 8539b60a injected
  cha chờ: [{'sessionId': '38aaead12bf54a799cc48b26195b0819', 'role': 'testing'}] mode=all hạn-an-toàn=60s
  hết chờ: done chờ=10869ms còn-lại=[]
  chốt lượt: {"status": "completed", "turn": 1, "steps": 2, "waitedMs": 10869, "childCount": 2, "childSteps": 3, "childTokens": 796, "childDeliveries": 2}
```

- Lượt sống qua **giao diện** (Vite 3100 + agent-browser), panel Sub-agents đọc bằng DOM:
  `đang chờ review giao kết quả· lưới an toàn còn 5:00` → `đã giao cho testing` → `đã nhận từ review · 212 chars`
  (phiên `19271d91…`, lượt 2); lượt trước đó: `đã nhận từ review · 1298 chars`, `đã giao cho main, testing`.
  Ảnh: `images/t17ui_15_child_wait_fixed.png`, `images/t17ui_16_receipts_after_wait.png`, `images/t17ui_14_receipt_fixed.png`,
  `images/t17ui_12_child_wait_fixed.png`, `images/t17ui_13_receipts.png`, `images/t17ui_10_child_wait.png` (trước khi sửa nhãn),
  `images/t17ui_02_waiting.png`, `images/t17ui_09_receipts.png`.
- `peer_wait` / `peer_wait_end` là chuyện của **người CHỜ**, dù người chờ là cha hay là con: lượt nào gọi `await_children` thì
  luồng của lượt đó mang hai event ấy (đo sống: con `3624ba4e…` của phiên `19271d91…`, con `6a541ef2…` của phiên `46c47921…`,
  con `944d6bde…` của phiên `bb142655…` đều có). Bảng Sub-agents vẽ nhãn chờ từ luồng **đang mở**, nên nhãn ấy chỉ hiện cho người
  chờ đang được xem; biến thể sống `test_chuoi_tren_harness_song` đọc luồng của cha (bản đầu đi tìm trong luồng con nên đỏ).
- Ghi nhận: hai lượt sống chết vì lý do môi trường — `UPSTREAM_HTTP_429` ("This target is cooling down after a provider limit")
  ở phiên `b4f26ca6…` và `62146c6e…` — không liên quan mã đợt này; phiên `e94f1af0…` `failed` ở lượt UI còn giữ nguyên trong
  bảng để đối chiếu.

## Vòng 22 — đợt 3 (bằng chứng sống): cổng bằng chứng ở câu trả lời cuối, dò box, hàng `E:` trong nhật ký, huy hiệu ba trạng thái (2026-09-22, đêm)

- Phạm vi (đợt 3 của kế hoạch `docs/plan/v22-boxfox-plan.md` §5 — 25 việc, 6 pha; bản thi công có mã việc nằm ở
  `/code/.plans/v1-evidence-proof.md`, P1.1–P6.3): (P1) danh tính lượt, nhật ký mang `turn`/`step`, hằng số và
  công tắc, bằng chứng sinh **tại gốc** mỗi lần ghi tệp, dọn rác thư mục bằng chứng; (P2) đọc lượt —
  `TurnProfile`/`classify_turn`, `assess`/`claim_paths`/`missing_reason`, `repair_message`; (P3) chèn cổng sau
  câu trả lời cuối, dò box bằng một lệnh cố định, sửa câu trả lời có trần, ghim hàng `E:` và số vào `turn.end`,
  nhóm `gate` trong `runtime-info`, trần độ dài câu trả lời; (P4) giao diện ba trạng thái; (P5) eval kéo S4 ra
  khỏi `not_measured`; (P6) sổ sách (`bug-register.md` §6.25, `owner-decisions.md` D-8, mục này).
- Cách chạy: router 3101 + harness 3102 (**khởi động lại trên mã mới**) + Vite 3100 + box `agentbox-box` đang chạy;
  ảnh box **không** dựng lại. Lượt sống qua API (`POST /api/agent/sessions/{sid}/turns`) và qua giao diện
  (agent-browser 0.21.2, phiên `v22dot3`), xem trước đã đăng ký `localhost:3100`. Model: OpenCode Free
  `muse-spark-1.3-contributor-free`. Công tắc duy nhất để tắt cổng: `BOXFOX_EVIDENCE_GATE=off` (mặc định `warn`).
- Kết quả: **P1.1–P6.3 xong**; cổng chạy **sống** trên lượt thật, giao diện ba trạng thái đo được bằng DOM, và
  **S4 đo được lần đầu** kể từ vòng 21. Hai khoảng trống ghi nhận chứ không giấu: (a) khẳng định **thuần văn**
  (không đường dẫn, không lệnh) vẫn ngoài tầm cổng — món nợ đã ghi ở §6.25; (b) mảnh bằng chứng `kind='command'`
  không mang mã thoát nên hàng `E:` ghi `exit None`, còn giao diện đọc mã thoát và thời lượng từ cặp
  `tool_start`/`tool_end` của chính lượt (Phần C).

### Phần A — Cổng bằng chứng chạy sống trên lượt thật (P2.1–P2.3, P3.1–P3.6)

- Đường đi của cổng: cuối lượt, `run_turn` dựng `TurnProfile` từ **chính event của lượt** (tool nào đã chạy, tham
  số, tệp đã ghi, mảnh bằng chứng đã sinh), chấm theo bảng §2.1 và luật R1–R5 (`assess`), rồi hoặc ghim hàng `E:`
  (chỉ đọc), hoặc mở **một** vòng sửa câu trả lời có trần `EVIDENCE_REPAIR_MAX_TOKENS = 2048` /
  `EVIDENCE_REPAIR_TIMEOUT_SECONDS = 60` (bỏ khi còn dưới `EVIDENCE_REPAIR_MIN_REMAINING_SECONDS = 20` giây).
  Chế độ `warn` **không** sửa văn của model; `not_measurable` (thiếu dữ liệu) không bao giờ bị chấm thành
  `insufficient`. Tiến trình 3102 phải **khởi động lại** mới có nhóm `gate`: trước khi khởi động lại,
  `runtime-info` trả `KeyError: 'gate'` dù mã đã nằm trong cây làm việc — báo cáo P4 vì thế ghi "chưa dựng
  `gate`" ở một thời điểm, không phải thiếu mã.
- Số của cổng đi vào **một** chỗ: `turn.end` mang thêm `gateMode`, `evidenceVerdict`, `evidenceChecked`,
  `evidenceMissing`, `evidenceRepair`, `changedFiles`, `artifacts`. Đo sống — phiên
  `b9b47d6f06404ead938048c2ab746a7b` trên harness 3102 đã khởi động lại, hai lượt liền nhau:

```text
lượt 1  turn_end {status: completed, gateMode: warn, evidenceVerdict: sufficient, evidenceChecked: 3,
        evidenceMissing: 0, evidenceRepair: false, changedFiles: 1, artifacts: 3}
        assistant.evidence {checked: 3, missing: [], changedFiles: ["src/app.py"], journalSeq: 51}
        hàng E:b9b47d6f-51  "lượt 1: đã kiểm chứng — 3 mảnh bằng chứng"
lượt 2  notice EVIDENCE_INSUFFICIENT {verdict: insufficient,
        missing: [{reason: change_without_verification, detail: "src/app.py"}], evidenceJournalSeq: 52}
        turn_end {status: completed, gateMode: warn, evidenceVerdict: insufficient, evidenceChecked: 1,
        evidenceMissing: 1, evidenceRepair: false, changedFiles: 1, artifacts: 1}
        hàng E:b9b47d6f-52  "lượt 2: chưa kiểm chứng — 1 mảnh bằng chứng; thiếu: change_without_verification"
```

- Lượt 2 là ca đúng ý đồ: model ghi `src/app.py` rồi **tự** nói "chưa chạy kiểm thử nên chưa thể nói đã kiểm thử
  đầy đủ"; cổng vẫn ghim nhãn vì *tệp đã đổi mà không có lệnh nào kiểm lại* — nhãn đo hành vi của lượt, không
  đo lời lẽ. Vòng sửa câu trả lời không bật trong hai lượt này (`evidenceRepair: false`); nhánh sửa có ca riêng
  trong `test_evidence_gate.py` / `test_evidence_gate_runtime.py`.
- Mặt đọc `runtime-info` (P3.5) đã sống trên tiến trình mới — DEV đọc trạng thái THẬT của cổng, không chép tay:

```text
{"evidenceMode": "warn", "modes": ["off", "warn", "enforce"], "default": "warn", "repairMaxTokens": 2048,
 "repairTimeoutSeconds": 60, "repairMinRemainingSeconds": 20, "probeTimeoutSeconds": 20,
 "probeMaxFiles": 200, "maxArtifacts": 20}
```

- Dò box (P3.2) là **một** lệnh shell cố định, chỉ nội suy mốc thời gian của lượt và trần số tệp; nó loại
  `.generated_artifacts/` và `.session-history/`, chạy tối đa `EVIDENCE_PROBE_TIMEOUT_SECONDS = 20` giây, cắt ở
  `EVIDENCE_PROBE_MAX_FILES = 200` tệp, và ghi cả đầu ra thô thành một mảnh bằng chứng — văn của model không bao
  giờ được nội suy vào lệnh.

### Phần B — Bằng chứng tại gốc, danh tính lượt, dọn rác (P1.1–P1.5)

- **P1.4 (đã đẩy ở `c82d9d2`)** — mỗi lần `file_write`/`file_edit_block` ghi tệp, box trả về `diff` và `numbers`
  (`sha256Before`/`sha256After`, `added`, `removed`, `lines`, `bytes`) kèm `artifact` là đường dẫn diff trong
  `.generated_artifacts/captures/evidence/<sid8>/`. Đo sống: `Written src/app.py` ⇒ artifact
  `.generated_artifacts/captures/evidence/b9b47d6f/b9b47d6f_000_app.py.diff`, `sha256After ba1a531f581d…`, `+2 −0`,
  `32 B`; lần sửa thứ hai ghi `…_000_app.py-2.diff`, `sha256After af626eb7a9c3…`, `+4 −0`, `66 B`.
- **P1.5** — `prune_captures` quét mỗi `EVIDENCE_PRUNE_EVERY = 20` lượt ghi và **chỉ** xoá tệp cũ trong thư mục
  captures; hỏng thì ghi `EVIDENCE_PRUNE_DEGRADED` chứ không làm đỏ lượt. Nghiệm thu:
  `.venv/bin/python -m pytest backend/tests/unit -q -k "prune or retention"` ⇒ **1 passed, 1073 deselected in 0,58 s**.
- **P1.1** — số lượt lấy từ SQL trên `events` (`_turn_index`), không tin `sessions.turn_count` (trường cũ mặc định
  0, và `store.events()` cắt ở 500 hàng); hai nguồn lệch nhau thì ghi `turn.index_drift` (`TURN_INDEX_DRIFT`) rồi
  vẫn đi tiếp. Lỗi `NameError` do chính bản sửa này gây ra trong `wrap_up_diagnosis` (`turn.wrapup_failed` ⇒
  `TURN_FAILED_NAMEERROR`) đã sửa trong cùng đợt.
- **P1.2** — mọi hàng nhật ký mang `turn`/`step` (kể cả hàng `E:`); hàng `E:`/`F:` **không** thuộc nhóm brief nào.
- **Hồi quy do hàng `E:` và cách chữa**: khối ký ức 6 nhóm vẫn in đủ tiêu đề kể cả khi lượt chỉ có hàng ngoài
  nhóm, nên đệm vào system prompt một khối rỗng ⇒ `test_harness_runtime.py::test_multiturn_restart_and_isolation`
  và `test_write_plan.py::test_an_ambiguous_refusal_leaves_a_one_shot_ticket` đỏ khi cổng bật (`warn`), xanh khi
  `off`. Chữa: `BRIEF_EMPTY_LINE` + `journal.brief_has_items()`, và `session_journal.brief()` trả chuỗi rỗng khi
  không nhóm nào có việc. Ca mới: `test_session_journal.py::test_rows_that_belong_to_no_group_leave_the_memory_block_empty`.

### Phần C — Giao diện ba trạng thái (P4.1–P4.5)

- **Huy hiệu ba trạng thái thay nhãn `done` viết tay** ở dòng tên model: `đã kiểm chứng` (xanh), `chưa kiểm chứng`
  (vàng), `chưa đo được` (khi cổng không đo được lượt). DOM mang **hai** thuộc tính: `data-evidence-badge` (trạng
  thái đang hiện) và `data-evidence-verdict` (verdict thật của backend, **chỉ có** khi lượt thật sự mang trường
  `evidence`). Nhờ vậy đọc máy được "chưa đo" khác "đo rồi và thiếu".
- **Khối `Bằng chứng`** trong câu trả lời cuối gom mảnh từ năm nguồn (khử trùng theo đường dẫn): `changedFiles`,
  media của lượt, `result.artifact`, hàng `E:` trong nhật ký, `assistant.evidence.artifacts[]`. Mục con:
  `Lệnh đã chạy` (kèm `exit` và thời lượng), `Tệp và ảnh của lượt`, `Khẳng định chưa có bằng chứng` — nhóm rỗng
  **vẫn hiện** kèm câu giải thích, để người đọc biết lượt đã được chấm.
- **Dòng receipt** giữ nguyên các số cũ và thêm hai số của cổng: `N bằng chứng` (đếm ĐÚNG số mục mà khối Bằng
  chứng liệt kê) và `M khẳng định chưa kiểm`. Ô thứ hai rơi khi `M = 0` (phép đếm cũ bỏ số 0), nên lượt xanh đọc ra
  `3 commands  4 bằng chứng` còn hàng đầu khối vẫn in `0 khẳng định chưa kiểm` — hai mặt của cùng một lượt, không
  phải hai số mâu thuẫn. Lượt cũ (không mang trường `evidence`) **không** được thêm số nào — vẫn
  `3 commands  1 failed` như ảnh vòng trước. (Hậu kiểm đợt 3: `M` chỉ đếm lý do LÀ khẳng định; lượt
  `not_measurable` in `chưa đo được` ở ô đó, tiêu đề nhóm đổi thành `Chưa đo được lượt này`.)
- **Bấm mở được**: ảnh/ghi hình mở lightbox như cũ; tệp bằng chứng gọi `showTab('files', { path })` nên mở thẳng
  trong panel Files — **kể cả** đường dẫn ẩn dưới `.generated_artifacts/`.
- Đo bằng DOM trên xem trước đã đăng ký (`localhost:3100`, phiên `b9b47d6f…`): hai huy hiệu
  `verified:sufficient` và `unverified:insufficient`; phiên cũ `60b3c095…` có **9** huy hiệu `unverified` và
  **không** huy hiệu nào mang `data-evidence-verdict` (đúng luật "lượt cũ không mặc định xanh").

### Phần D — Eval kéo S4 ra khỏi `not_measured` (P5.1–P5.3)

- `scripts/eval/rushed_index.py` đọc thẳng số của cổng trên `turn.end` (`data.evidenceVerdict`,
  `data.evidenceMissing`). Luật trung thực giữ nguyên: lượt **không** có khoá thì không vào mẫu (không tính là 0);
  danh sách tool ghi lấy từ chính `evidence_gate.WRITE_TOOLS`/`PLAN_TOOLS` để hai bên không lệch.
- Đo sống: `python3 scripts/eval/rushed_index.py --json` ⇒ S4 `measured`, `value = 0,5` ("2 lượt đã đo (cửa sổ log
  có 2 lượt), 1 lượt bị gắn cờ"), ngưỡng nâng `enforce` in ngay trong `note`: **≥ 20 PHIÊN có số VÀ tỉ lệ báo
  động sai < 10 %**. Trước khi thi công, cùng log đó cho `S4 = not_measured`. **S1/S5 vẫn `not_measured`** (không
  có nguồn số nào thay thế), `S2/S3/S6/S7/S8/S9` là `measured`/`measured_proxy` như cũ.

### Phần E — Số đo kiểm thử của đợt

- Backend, cả bộ unit: `.venv/bin/python -m pytest backend/tests/unit -q` ⇒ **1 failed, 1073 passed in 173,87 s**
  lúc viết mục này, và **1 failed, 1078 passed in 182,40 s** sau hậu kiểm (xem mục cuối sổ này). Ca đỏ duy nhất là
  `test_terminal_tools.py::test_terminal_exec_echo`, đỏ vì môi trường (`bash: Write-Output: command not found`, box
  không có PowerShell), không liên quan mã đợt này. Hai ca từng đỏ vì hàng `E:` (Phần B) nay xanh. Nhóm cổng: lúc
  viết mục này `test_evidence_gate.py` **28 passed**, `test_evidence_gate_runtime.py` **13 passed** (con số 13 sai:
  tệp có **14** hàm test mức module — sửa ở hậu kiểm, xem mục cuối); sau hậu kiểm **31** và **15 passed**. Nhóm bị
  đụng bởi hàng `E:`: `test_session_journal.py` **7 passed**, `test_harness_runtime.py` **17 passed**,
  `test_write_plan.py` **19 passed**, `test_eval_setup.py` **56 passed**; `-k "prune or retention"`
  **1 passed / 1073 deselected**.
- Giao diện: `npx vitest run src/components/chat/HarnessStepView.evidence.test.tsx
  src/store/harnessChatStore.journal.test.ts src/components/chat/HarnessStepView.test.tsx` ⇒ **3 tệp, 41 ca đạt**;
  cả bộ giao diện (do phiên build P4 chạy hai lần) ⇒ **122 tệp / 1012 ca đạt, 0 đỏ**; `tsc -b --noEmit` ⇒ **exit 0**.
- Ảnh chụp phía trên lấy bằng agent-browser 0.21.2 (bản cài trên máy này không nằm trong hai bản skill mô tả; đã
  đối chiếu `--help` thấy đủ `open`/`click`/`eval`/`screenshot`).

### Phần F — Bằng chứng sống của đợt, khẳng định cũ bị đổi, ghi nhận

- Lượt sống trên harness 3102 (mã mới, cổng mặc định `warn`), phiên `b9b47d6f06404ead938048c2ab746a7b`:
  lượt 1 `sufficient` · lượt 2 `insufficient`. Bản thô: `/var/tmp/v22/p35live.json`, `/var/tmp/v22/p35live2.json`.
  Lượt sống phía P4 (harness 3112, cổng `warn`): phiên `8d9cc2f099e74da594347b1289f8da8d`, bốn lượt, có cả
  `sufficient` và `insufficient` + `missing=[change_without_verification]`.
- Ảnh (đường dẫn tuyệt đối theo đúng nghiệm thu của kế hoạch):
  `/code/.generated_artifacts/images/p35_02_verified_turn.png` (lượt **đã kiểm chứng**: huy hiệu xanh, `4 bằng
  chứng`, `Lệnh đã chạy` có `exit 0 · 110ms`, nhóm "khẳng định chưa có bằng chứng" rỗng nhưng vẫn hiện),
  `/code/.generated_artifacts/images/p35_01_session_top.png` (lượt **chưa kiểm chứng**: huy hiệu vàng, notice,
  hai hàng tệp), `/code/.generated_artifacts/images/p35_06_narrow.png` (900 px: mọi khối xuống dòng gọn, chip lý
  do `tệp đã đổi nhưng không có lệnh nào kiểm lại` + mã `change_without_verification`),
  `/code/.generated_artifacts/images/p35_05_legacy_turn.png` (lượt **cũ**: `chưa kiểm chứng` +
  `lượt này không mang số đo bằng chứng (phiên cũ, hoặc công tắc đo đang tắt)`, giữ nguyên receipt
  `3 commands  1 failed`, không có khối
  bằng chứng), `/code/.generated_artifacts/images/p35_03_open_in_files.png` (bấm mở tệp bằng chứng trong panel
  Files) và `/code/.generated_artifacts/images/p35_04_open_hidden_diff.png` (mở được cả diff ẩn dưới
  `.generated_artifacts/…`). Cùng chuỗi này ở phiên P4: `/code/.generated_artifacts/images/p4_02_session_open.png`,
  `p4_03_verified_turn.png`, `p4_05_legacy_no_evidence.png`, `p4_06_narrow_verified.png`,
  `p4_07_preview_public.png`, `p4_04_open_in_files.png`, `p4_08_diff_in_files.png`.
- **Các khẳng định cũ bị đổi (đọc ảnh vòng 21/22 phải hiểu đúng, kẻo thành "hồi quy giả")**:
  1. Chỗ nhãn `done` viết tay cạnh tên model giờ là **huy hiệu ba trạng thái**. Ảnh cũ (`images/t17ui_*.png`,
     `foundation_e2e_04_answer.png`…) vẫn đúng với thời điểm chụp; lượt cũ **không** thành `đã kiểm chứng` mà
     mang `chưa kiểm chứng` kèm câu "lượt này không mang số đo bằng chứng (phiên cũ, hoặc công tắc đo đang tắt)".
  2. Dòng receipt lượt cũ giữ nguyên số cũ (`3 commands  1 failed`); hai số `N bằng chứng` / `M khẳng định chưa
     kiểm` chỉ xuất hiện ở lượt có trường `evidence`.
  3. Văn của model **không bị sửa** khi thiếu bằng chứng ở chế độ `warn` — cổng chỉ ghim nhãn và hàng `E:`;
     nhánh sửa câu trả lời là nhánh riêng, có trần, và lượt sống ở đây không đi qua nó.
  4. Khối "Bằng chứng" và hai số receipt là **mới**, không phải lỗi hiển thị của ảnh cũ.
- Ghi nhận môi trường: phiên agent-browser `v22dot2-test` của vòng hậu kiểm trước còn kẹt (daemon pid 271659) —
  không đụng tới; dấu vết do vòng kiểm thử để lại trong `.plans/` và `.uploaded_artifacts/` được giữ nguyên và
  báo lại, không xoá. Thư mục `docs/tracking/images/` vẫn không tồn tại dù các mục cũ trỏ `images/…` — đã ghi
  thành phát hiện riêng (`d8b08e2b-749b-4c8f-a060-4350a99d3c42`).

### Đợt kiểm thử độc lập (cùng PR) — bốn vòng rà soát: sáu lỗi mesh (BUG-53…BUG-58) và hai lỗi giao diện

Diff `main...vorflux/v22-peer-mesh` được rà soát độc lập theo hợp đồng tám mục (phân loại thay đổi, ca bám đúng
phạm vi, chạy trên hệ thống thật, không chạy lại tính năng cũ không bị sửa). Bốn vòng rà soát liên tiếp tìm ra sáu
lỗi trong mã mesh của đợt 2 — tất cả đã sửa và đo lại, chi tiết ở `bug-register.md` §6.25:

- **BUG-53** — nhả slot con hai lần ⇒ `global_child_slots._value = 11` trong khi trần là 8; chữa bằng
  `child_slot_holders` + `release_child_slot` (chỉ nhả khi đúng người giữ).
- **BUG-54** — `CancelledError` thoát khỏi `wait_for` mà **không** trả permit của cha.
- **BUG-55** — lỗi khi giao hàng chặn luôn event đóng sổ con; chữa bằng `child.delivery_failed`.
- **BUG-56** — khối "chi phí theo lượt" thực ra tính cả **phiên**: `peer_turn_cost` bỏ qua tham số lượt và `children_summary`
  không lọc `parent_turn` (7 chỗ gọi).
- **BUG-57** — một lần chờ bị huỷ để lại `waiting_for`/`waiting_since` trên hàng sổ con (và cờ đánh thức sống sang lượt
  sau): `child_wait(sid, [], None)` trong `finally`.
- **BUG-58** — thiếu `notify_peer_delivery(target)` nhánh `main`, biên nhận không tỉnh người chờ.
- **Hai lỗi giao diện** (vòng hậu kiểm đợt 2, nay ở `0509e17`): nhãn chờ bị cắt trong cột 256 px
  (`đa… · lưới an toàn còn 4:58`) — chữa bằng `flex-wrap` + `gap-x-1 gap-y-0.5`; và lý do bỏ giao đọc không đủ khi
  bị cắt — chữa bằng `title={line.text}` trên hai hàng `child-delivers-to` / `child-receipt`.
- **BUG-59** (lỗi mới, lộ ra khi P1.4 cần số bước để đặt tên mảnh bằng chứng; sửa ở `c82d9d2`) — hai route capture/record
  của box đọc `step`/`toolCallId` từ lâu nhưng harness **chưa bao giờ gửi**, nên tên tệp ảnh/ghi hình rơi về `000`; chữa
  bằng `executor.box_identity` (test: `test_worker_evidence.py`, 10 ca).
- Ghi nhận: **BUG-51** vẫn `CHƯA SỬA` (nợ có ý thức, đã thành phát hiện riêng
  `bb865553-5358-4f06-9f40-7ed37c249cf8`), và **BUG-44** — lỗi mở đầu của đợt này — nay `ĐÃ SỬA`, kèm món nợ
  "khẳng định thuần văn vẫn ngoài tầm cổng".

### Hậu kiểm đợt 3 — hai vòng soát song song tìm ra sáu lỗi thật trong chính mã mới (BUG-60…BUG-65), bốn phát hiện để lại sổ

**Ai soát, soát cái gì.** Ba việc chạy song song trên `3dadeb3`: một vòng soát **backend** (cổng, worker, harness), một
vòng soát **giao diện + eval + tài liệu**, một việc **tinh gọn mã**. Kết luận của cả hai vòng: *Ship with mitigations* —
hướng đúng, nhưng ba lỗi hợp đồng khoá làm cổng chấm SAI trên máy thật dù mọi bài kiểm đều xanh. Đây là loại lỗi
"test xanh, máy đỏ": bài kiểm dựng **hình dạng giả** của kết quả worker nên không ai bắt được.

**Ba lỗi hợp đồng khoá (đều mức Cao, đã sửa cùng phiên).**
1. **BUG-60** — `dispatch` không truyền `turn`/`step`/`toolCallId`. Ba tham số có từ `c82d9d2` (BUG-59) nhưng **chỗ gọi
   thật** không truyền, nên `step` luôn `None`: mọi mảnh bằng chứng và mọi ảnh chụp rơi về bước `000` — đúng khoảng
   trống mà P1.4 dựng ra để bịt. Sửa: `dispatch` dựng `identity` từ `active_turn`/`active_step`/`call_id` và truyền cho
   **mọi** lời gọi tool; tám đôi thực thi giả trong bài kiểm nhận `**_identity`.
2. **BUG-61** — cổng đọc `stdout`/`exitCode`, worker trả `content`/`exit_code`. Hệ quả: **mọi phép dò trả "không đổi
   gì"** (nhánh R1 "lệnh + mã thoát + phép dò xác nhận" không bao giờ chạy, và một lượt đáng bị ghim có thể được chấm
   `sufficient`), còn mọi mảnh lệnh mang `exit None` — đúng thứ ảnh `p35_02_verified_turn.png` cho thấy.
3. **BUG-62** — `changed` lấy từ `numbers['path']`, khoá mà worker CỐ Ý bỏ (`test_worker_evidence.py` khoá đúng điều
   đó). Nên mảnh diff không khớp tệp đã đổi ⇒ **mọi lượt ghi có đủ diff vẫn bị ghim `change_without_verification`** ở
   `warn`, và ở `enforce` là một vòng sửa vô ích mỗi lượt ghi. Đường dẫn nay lấy từ `args['path']` của chính lời gọi ghi.

**Ba lỗi nhất quán/độ bền (đã sửa).** **BUG-63**: cổng tự hỏng SAU khi phán thì hai mặt đọc nói hai kết luận (hàng `X:`
nói "chưa đo được", event `assistant` giữ phán thật) — nay nhánh `except` ghim đúng `not_measurable` + `gate_error`.
**BUG-64**: bộ đếm lượt đếm cả hàng `user` của lệnh điều khiển (`/status` phát một hàng mà không qua `begin_turn`) ⇒ từ
đó mọi lượt vừa lệch số vừa ghi `turn.index_drift` mãi; nay hàng đó mang `control: true` và phép đếm bỏ qua. **BUG-65**:
vòng dò ghi tệp bằng chứng không có trần thời gian (một box treo ở đó ăn hạn chót của lượt và xoá câu trả lời) — nay
bọc cùng `_clamp_timeout(...)` như phép dò.

**Bốn phát hiện của vòng soát giao diện, ba sửa.** (F1) lượt `not_measurable` vẫn bị đếm và gọi tên như "khẳng định
chưa kiểm chứng": nay số khẳng định chỉ đếm năm mã lý do LÀ khẳng định, ô thứ ba của dòng biên nhận in `chưa đo được`,
và tiêu đề nhóm đổi thành `Chưa đo được lượt này` (lý do vẫn hiện nguyên vẹn — đổi cách đếm không được phép giấu lý do).
(F2) câu dự phòng dịch mã lý do không bao giờ chạy (`t()` trả chính khoá khi cả hai từ điển trượt) nên người đọc thấy
`chat.evidenceReason.<mã>`; nay trả mã máy, và từ điển có thêm `no_change` ở **cả** `vi.ts` và `en.ts`. (F4) câu giải
thích huy hiệu xanh in số mảnh CỔNG chấm trong khi hàng đầu khối in số mục khối liệt kê (đo sống: `checked=3` mà giao
diện hiện `4 bằng chứng`) — nay bỏ số khỏi câu đó. (F3) câu ghi chú cho lượt không mang trường `evidence` từng đổ cho
"phiên cũ" trong khi công tắc `off` cũng không sinh trường đó: câu mới nói cả hai nguyên nhân.

**Hai chỗ chữ nghĩa trong chính tài liệu này (F5, F6) đã sửa:** câu "thêm hai số mới" ở Phần C, và con số
`test_evidence_gate_runtime.py` ở Phần E (13 → đúng **14** ca lúc đó, **15** sau hậu kiểm).

**Bốn phát hiện ghi sổ, CHƯA SỬA** (xem §6.26 sổ lỗi): R3 phạt oan văn xuôi trung thực khi lượt không đọc lại tệp đã
dẫn chứng; `_COMMAND_RE` nuốt dấu phân cách nên lệnh trong dấu backtick không bao giờ khớp; lượt giao việc con được
`sufficient` khi con còn đang chạy; và `en.ts` của khối bằng chứng vẫn là tiếng Việt (theo nếp có sẵn của tệp).

**Đo sống sau hậu kiểm** (harness `3102` khởi động lại trên `b9f6f07`, phiên `3170db0250ae43d0b6609edbd0f81a5f`,
hai lượt):
- lượt 1 ghi `src/app.py` rồi chạy `wc -c src/app.py`: `evidenceVerdict=sufficient`, `evidenceChecked=2`,
  `evidenceMissing=0`, `changedFiles=1` — trước hậu kiểm chính lượt này bị ghim `change_without_verification` (BUG-62);
- mảnh diff mang tên `…/evidence/3170db02/3170db02_001_app.py.diff` — **số bước thật** (`001`), không còn `_000_`
  (BUG-60); hàng `E:` ghi `note: 'exit 0'` thay cho `exit None` (BUG-61);
- lệnh điều khiển `/status` phát hàng `user` mang `control: true`, lượt thật kế tiếp mang số `2`, và **không** dòng
  `turn.index_drift` nào trong `~/BoxFox/logs/harness.jsonl` (BUG-64).

**Số đo sau hậu kiểm.** Backend: cả bộ unit ⇒ **1 failed, 1078 passed in 182,40 s** (ca đỏ duy nhất vẫn là
`test_terminal_tools.py::test_terminal_exec_echo`, đỏ vì box không có PowerShell); nhóm cổng ⇒ `test_evidence_gate.py`
**31 passed**, `test_evidence_gate_runtime.py` **15 passed**, `test_turn_counter.py` **5 passed** (thêm ca "lệnh điều
khiển không phải một lượt"). Giao diện: ba tệp liên quan ⇒ **50 ca đạt** (tệp bằng chứng từ 7 lên **10 ca**: thêm ba ca
— biên nhận `not_measurable`, lý do là khẳng định vẫn đếm, mã lý do lạ in nguyên mã), `tsc -b --noEmit` ⇒ **exit 0**.
### Vòng chốt — đóng BUG-71 (rác tệp của phép dò) và lấy được mặt `not_measurable` sống (2026-09-22, khuya)

**Vì sao vòng chốt còn sửa một lỗi.** Vòng kiểm độc lập để **BUG-71** lại sổ ("ghi nhận, chưa sửa — vòng sau").
Lỗi nằm trong chính mã mới của đợt 3 (phép dò P3.2), cách sửa một dòng, và nó bắt người dùng trả giá ngay: mỗi lượt
`needs_probe` để lại một tệp `.diff` vô nghĩa trong đúng thư mục mà P1.5 vừa dựng ra để dọn rác.

**Cách sửa (`2752388`).** `probe_workspace` ghi tệp thô của phép dò bằng một lời gọi **ngoài phiên** (`session=None`)
— đúng luật P1.4 mục 5: worker vẫn ghi tệp, còn `write_evidence` trả `None` khi thiếu định danh nên không ghim thêm gì.
Đường dẫn do harness dựng sẵn nên bản đọc được vẫn nằm đúng chỗ. Ca kiểm mới
`test_phep_do_ghi_tep_tho_ngoai_phien_de_khong_sinh_tep_rac`, và `FixtureExecutor` nay ghi lại `session` của mỗi lượt gọi.

**Đo sống** (harness `3102` khởi động lại trên `2752388`, phiên `be76487a4a7b4e45add8f1bb3f526955`, lượt chạy
`sh tools/mk71.sh` sinh `lop71.txt`):
- thư mục `.generated_artifacts/captures/evidence/be76487a/` còn **đúng một tệp** `be76487a_2_changes.txt`; trước bản
  vá mọi lượt `needs_probe` để lại **hai** tệp — thấy ở `4987d659`, `3170db02` và `1c65d2e7`;
- cổng vẫn chấm bình thường: `turn.end` mang `evidenceVerdict=insufficient`, `evidenceChecked=1`, `changedFiles=1`
  (`lop71.txt`). **BUG-66 lộ thêm một ca sống**: câu trả lời trung thực nhắc đúng tệp script nó vừa chạy
  (`tools/mk71.sh`) mà vẫn bị ghim `claim_path_not_in_turn` — nên ngưỡng nâng `enforce` ở §6 kế hoạch (≥ 20 phiên có
  số **và** tỉ lệ báo động sai < 10 %) **chưa đạt**; phải sửa BUG-66 trước.

**Mặt `not_measurable` lấy được sống — ca mà vòng kiểm độc lập phải bỏ dở.** Câu hỏi 127 để người dùng chọn cách ép
mặt thứ ba; vòng chốt chọn cách **không đụng gì đang dùng chung**: một harness cô lập (`3123`) với `docker` là một shim
hỏng (`/var/tmp/v22dot3b/nodocker/docker`, exit 127) — mọi lời gọi tool và cả phép dò của cổng đều hỏng, còn model vẫn
trả lời bình thường. Lượt chạy `sh tools/mk71.sh` (lệnh không nhận dạng được ⇒ `needs_probe`):
- `turn.end`: `evidenceVerdict=not_measurable`, `evidenceChecked=1`, `evidenceMissing=1`, `changedFiles=0`;
  `assistant.evidence.missing=[{reason: box_probe_failed, detail: unreachable: RuntimeError}]`;
- khẳng định về đường dẫn **không** bị ghim — R5 thắng R3 đúng như §2.3, đo được sống;
- giao diện (Vite `3131` → harness `3123`, agent-browser **0.21.2**): huy hiệu `data-evidence-badge="not_measurable"`,
  hàng biên nhận `1 bằng chứng chưa đo được · cổng: BOXFOX_EVIDENCE_GATE = warn`, tiêu đề nhóm
  `Chưa đo được lượt này`, hàng lý do `phép dò bằng chứng trong box bị lỗi / unreachable: RuntimeError /
  box_probe_failed`, và ghi chú nhật ký hỏng (`Nhật ký bên trong box chưa ghi được ở phiên này — số liệu lấy từ hàng
  SQLite của harness.`) hiện ra thay vì làm vỡ khung chat;
- ảnh: `/code/.generated_artifacts/images/r22dot3b_12_not_measurable_turn.png` (khối thu gọn) và
  `/code/.generated_artifacts/images/r22dot3b_13_not_measurable_expanded.png` (mở khối, thấy hàng lý do).

**Số đo của vòng chốt.** Backend cả bộ unit ⇒ **1 failed, 1080 passed in 176,41 s** (ca đỏ duy nhất vẫn là
`test_terminal_tools.py::test_terminal_exec_echo` — box không có PowerShell, lỗi môi trường có trước đợt này); nhóm
cổng + worker (`test_evidence_gate_runtime.py`, `test_evidence_gate.py`, `test_worker_evidence.py`) ⇒ **58 passed
in 6,59 s**.

### Vòng dạo mock–app (vòng độc lập, đợt 3) và bản vá L14 — câu bị ghim nay đọc được (2026-09-22, khuya)

**Việc vòng độc lập làm.** Tự dựng lại năm mặt mock đã duyệt (1400 px và 900 px) rồi đo **cả hai bên** bằng computed style và cấu trúc DOM, không đo bằng mắt: `/code/.generated_artifacts/images/r22dot3d_mock_verified_1400.png`, `r22dot3d_mock_after-insufficient_1400.png`, `r22dot3d_mock_after-legacy-no-evidence_1400.png`, `r22dot3d_mock_narrow_verified_900.png`, `r22dot3d_mock_partial_v22_1400.png`; phía app: `r22dot3d_app_verified_1400.png`, `r22dot3d_app_verified_paneclosed_1400.png`, `r22dot3d_app_insufficient_1400.png`, `r22dot3d_app_legacy_1400.png`, `r22dot3d_app_verified_900.png`, `r22dot3d_app_verified_900_paneclosed.png`, `r22dot3d_app_nme_900.png`.

**Khớp.** Cột đọc 766 px so với mock 768 px; cùng bộ hook `data-evidence-*`; khuôn biên nhận `N bằng chứng · M khẳng định chưa kiểm · cổng: BOXFOX_EVIDENCE_GATE = warn`; thứ tự nhóm; token emerald-400 (`rgb(52,211,153)` ≈ `oklch(0.765 0.177 163.223)`); hàng lý do mang đủ câu người đọc + chi tiết + mã máy; nhóm rỗng vẫn in câu trung thực; mặt legacy hiện huy hiệu hổ phách và **không** có khối. Bản hẹp 900 px khi đóng bảng phải: cột 766 px, biên nhận một dòng, đường mono đầy đủ, `scrollWidth = 900` (không tràn); khi **mở** bảng phải cột còn 342 px — mock không quy định ca này, app xử sự gọn (đường dài cắt ellipsis, chip lý do xuống dòng trong 302 px), không phải khiếm khuyết.

**Lệch có chủ đích.** Huy hiệu là chữ tô màu chứ không phải viên thuốc bo tròn; tiêu đề nhóm chữ thường 11px/500 thay vì IN HOA 10px; hàng lệnh mất viên thuốc viền và chip `exit 0` viền; `Mở trong Files` là liên kết xanh thay vì chip viền; đệm hàng 4px/8px thay vì 6px/10px; chú thích lượt cũ khác chữ nhưng cùng nghĩa; nhóm 2 đổi tên `Tệp đã thay đổi` → `Tệp và ảnh của lượt` (đúng, vì nhóm nay chứa cả ảnh chụp/ghi hình — đã kiểm sống) với cái giá mất dòng tổng hợp `3 tệp · +44 −6` của mock.

**Lệch đã sửa ngay trong vòng này — L14 (`671aa1e`).** Mục thiếu bằng chứng nay in **câu của câu trả lời bị ghim** trong ngoặc kép, trước câu dịch của lý do (mock `dv23` làm đúng vậy; trước bản vá khối chỉ có lý do + chi tiết + mã máy). Ba ca kiểm mới ở `HarnessStepView.claims.test.tsx`; `npx vitest run` 123 tệp / 1019 ca đạt; `tsc -b --noEmit` exit 0.

**Đo sống, bốn ca độc lập (harness `3102`, giao diện `3100`).** `17ea25ef` — hàng `[data-evidence-missing="claim_path_not_in_turn"]` có `[data-evidence-claim="true"]` = `“Đã tạo tools/mkverify.sh và bản ghi nguồn tương ứng.”`, câu bị ghim đứng **trước** câu dịch (chỉ số 0 < 54) và trước mã máy (129), đường dẫn vẫn còn. `c1bc3a8f` — hai mục bị ghim, in câu cho **cả** đường dẫn lẫn lệnh. `31c3c86a` (`not_measurable`) — **không** có câu nào dù câu trả lời nhắc `src/nm_probe.py`: R5 thắng R3 giữ nguyên trên giao diện, không bịa câu. `20de8728` — lượt do vòng này tự lái (câu 202 ký tự) để thử biên: thấy mục “cắt giữa từ, không dấu `…`” ghi ở §6.28 mục 3. Ảnh: `/code/.generated_artifacts/images/r22l14_01_claim_line_insufficient.png`, `/code/.generated_artifacts/images/r22l14_03_two_rows_claim_lines.png`, `/code/.generated_artifacts/images/r22l14_02_no_claim_not_measurable.png`, `/code/.generated_artifacts/images/r22l14_04_truncated_claim_quote.png`.

**Hai mục giữ nguyên có ý thức.** (1) Số đếm bằng chứng hiện ở **cả** dòng biên nhận lượt **và** hàng đầu khối: P4.4 của kế hoạch yêu cầu hai số ở biên nhận, mặt mock đã duyệt đặt chúng ở hàng đầu khối — hai yêu cầu đã duyệt chồng nhau, nên không tự ý bỏ một cái; đề nghị chọn một mặt ở vòng sau rồi sửa kế hoạch + mock cùng lúc. (2) `sha256`/`±` chỉ hiện ở hàng harness có gắn `facts` — phụ thuộc dữ liệu, bịa số là vi phạm luật P4.3.

**Ngoài phạm vi vòng 3 (không soát).** `docs/design/v22/evidence-badge-partial.html` là mặt khác (lượt hết ngân sách bước: `BƯỚC 40/40 · STEP_BUDGET_EXHAUSTED`, `ĐÃ LÀM TRƯỚC KHI DỪNG`/`CÒN THIẾU — CHƯA KIỂM`, `Tiếp tục lượt`/`Chạy lại phần kiểm chứng`) — không chuỗi nào có trong `frontend/src`; `evidence-badge-{verified,warn}.html` là bản cũ rộng hơn. Bản dựng theo đúng mặt đã khai trong `design-plan-dv23.json` (`after-verified`).

**Chốt.** Bản vá L14 cũng đã được vòng độc lập kiểm lại trên cây `671aa1e`: 3 ca mới + 11 ca cũ đạt, cả bộ `npx vitest run` 123 tệp / 1019 ca đạt, `tsc` exit 0 — **OVERALL STATUS: PASSED**, cây sạch, không tệp nào của kho bị vòng này sửa.

### Vòng giao bằng chứng — gói ảnh chụp + ghi hình cho chủ nhà, và bản rà soát vì sao bản giao cũ không kiểm được (2026-09-23, sáng)

**Vì sao có vòng này.** Chủ nhà chỉ ra một drift: báo cáo của vòng trước giao bằng chứng sống bằng **danh sách đường dẫn**, mà nền tảng gói chúng thành chip chung (“the uploaded file”), nên chủ nhà **không mở được tấm ảnh nào để kiểm**. Kế hoạch `/code/.plans/v1-evidence-proof.md` §3 mục (a) vốn đòi “ảnh chụp màn hình trước/sau trong `/code/.generated_artifacts/images/`” và mục (d) “ảnh chụp UI cho thấy nhãn ‘đã kiểm chứng’ và danh sách bằng chứng mở được” — tức sai ở **bản giao của agent**, không ở mã.

**Một lượt sống mới, hai tấm ảnh KHÁC nhau.** Lượt `9481bf87` (harness `3102`, stub): bước 1 chụp màn hình box (cửa sổ terminal toàn màn hình đang in `frontend/src/UiProof.tsx` bản **TRUOC**), bước 2 `file_write` (đổi nhãn — sinh mảnh `.diff`), bước 3 đổi cửa sổ sang bản **SAU**, bước 4 chụp lại, bước 5 `wc -c` kiểm chứng, bước 6 câu trả lời. `turn.end` = `{turn: 1, step: 6, status: completed, gateMode: warn, evidenceVerdict: sufficient, evidenceChecked: 5, evidenceMissing: 0, evidenceRepair: false, changedFiles: 1, artifacts: 5}`; `claims[0].backed = true`. Hai ảnh là **hai tệp thật** (`…_001_screen.png` 41 615 B, `…_004_screen.png` 40 741 B) vì nội dung khác nhau — khác lượt `095cefaa` trước đó, nơi màn hình không đổi nên phép khử trùng theo nội dung gộp còn **một** tệp (đọc mã để chốt, ghi ở §6.30).

**Gói giao cho chủ nhà.** Ảnh: `r23_10_turn_before_after.png` (lượt trong app: `5 commands · 2 captures · 6 bằng chứng`, huy hiệu `đã kiểm chứng`, hai hàng ảnh, hàng `.diff` có `sha256 2cb699391d… +3 −3 140 B`), `r23_11_capture_before.png` / `r23_12_capture_after.png` (Zoom hai ảnh), `r23_13_change_diff_files.png` (panel Workspace Files mở **đúng diff** `a/`→`b/` kèm khối số), `r23_05_box_capture_before.png` / `r23_06_box_capture_after.png` (hai tệp PNG gốc lấy từ trong box), `r23_01_final_answer.png` / `r23_02_capture_zoom.png` (lượt `095cefaa`). Ghi hình: `r23_live_evidence.webm` (48,6 s — toàn bộ thao tác kiểm: mở lượt → Zoom trước → Zoom sau → mở diff) và `r23_live_evidence_walkthrough.webm` (151 s — bản chạy `095cefaa`). Cả hai đã remux (`-c copy`) và `ffprobe` đọc được (`vp8`, 1056×696). Bảng đầy đủ nằm ở §8 của báo cáo kiểm thử.

**Rà soát hệ thống (kết quả trung thực).** (1) Sai nằm ở bản giao của agent — đã khắc phục bằng gói trên. (2) **Một khoảng trống thật của giao diện, ghi nhận chứ chưa sửa**: hai hàng ảnh chụp của cùng một lượt in đường dẫn đầy đủ rồi bị `truncate` cắt ở **đuôi** — đúng chỗ phân biệt — nên hai hàng cùng đọc `.generated_artifacts/captures/scre…`; người kiểm chỉ phân biệt được nhờ `title` khi rê chuột. Đã ghi §6.29 (Thấp, chờ chủ nhà quyết vì mặt mock đã duyệt đặt hàng ảnh là “đường dẫn in được bằng mắt”) và surface finding `ffc455c5-2324-4b88-9b02-4f94ff992fb0`. (3) Hai hành vi của đường chụp ảnh **là cố ý, không phải lỗi** (§6.30): khử trùng theo nội dung (`capture.py:_finish_image`) và tên tệp bằng chứng hạ chữ thường (`worker.py:evidence_slug`). (4) Ngưỡng nâng `enforce` vẫn chưa đạt (13 phiên có số, còn BUG-66) — không đổi trong vòng này.


## Vòng 23 — câu trả lời cuối CHỈ markdown: báo cáo ngắn do model viết + ảnh chụp chứng minh, app bỏ hết khối/dải/huy hiệu quanh câu trả lời (2026-09-23, chiều)

**Vì sao có vòng này.** Chủ nhà chê đúng một chỗ, kèm ảnh chụp: mặt bằng chứng của vòng 22 **đúng về số đo nhưng sai về dạng giao**. `3123.png` — nguyên văn: *"không phải block. hẳn luôn. chỉ dùng file markdown thôi"*. `3122.png` là mặt ĐÚNG: ảnh nằm **mở ngay** trong câu trả lời. `3119.png` cho thấy danh sách đường dẫn literal bị nền tảng gói thành chip "the uploaded file" nên không mở được ảnh nào. Kế hoạch `/code/.plans/v1-evidence-report.md` (duyệt 04:26 UTC) chốt lại mười một câu **D-16…D-25** ở `docs/tracking/owner-decisions.md` § 4.

### Phần 1 — P1: khuôn báo cáo cuối nằm trong prompt SỐNG

Năm mục (`làm được gì / còn lại gì / chủ nhà quyết gì / khúc mắc gì / bằng chứng`) có mặt ở **hai** nơi bắt buộc: `runtime.FINAL_REPORT_PARTS` + `FINAL_REPORT_GUIDANCE` (`runtime.py:763`/`:771`) và `AGENT.md` § 3.4 (khối ASCII, giữ LF). SOP chỉ **trỏ** về khuôn, không chép lại lời — ca kiểm `test_cau_chi_dan_sop_tro_ve_khuon_chu_khong_chep_lai_loi` ghim điều đó. Kỹ năng mới `final-report` vào `DEFAULT_SKILLS`; bản nhắc việc đầu lượt (`turn_recap`) dựng từ chính lời gọi tool + tệp đã đổi, chỉ ở phiên chính, không lọt vào transcript/câu trả lời, lỗi thì trả `''` (không bao giờ làm đỏ lượt).

**Lỗi CŨ lộ ra khi thi công — và đây là lý do P1.1 suýt là no-op.** `skills/runtime_commands.py::_next_turn_skills` dựng lại `messages[0]` ở **mỗi lượt gửi** bằng cách cắt chuỗi tại mốc `=== ENABLED SKILLS ===` rồi chỉ nối lại khối `OWNER-CONFIGURED DIRECTIVES`. Đo trên DB sống: **182/182** prompt orchestrator đều **thiếu** `ANSWER LENGTH`/`FINAL REPORT` ⇒ khuôn mới sẽ không bao giờ tới model, và trần độ dài của D-4 lâu nay là vật trang trí. Nay hàm chỉ thay **danh sách kỹ năng**, giữ nguyên phần còn lại; ca kiểm `test_khuon_khong_bi_nuot_khi_danh_sach_ky_nang_duoc_dung_lai`.

### Phần 2 — P2/P3: ảnh chụp có đích, có nhãn, lỗi đi lên nguyên văn

`computer_screen_capture` nhận `target` (`window`/`tab`/`screen` — `tool_contracts.CAPTURE_TARGET_SCHEMA`) và `caption` (≤ 200 ký tự), lọc ở `sandbox/executor.normalize_capture_target`. Đo **tương thích ngược**: không/`None`/list/target lạ ⇒ `{'kind':'screen'}` **byte-identical** với lời gọi cứng cũ; khoá lạ bị bỏ. Nhãn vào **tên tệp** (`capture.py:_key_with_label` → `<sid8>_<step>_<slug>.png`, trần nhãn 40 ký tự, slug lần hai phía box theo bảng chữ cái BOX-3, `tab/../../etc` → `screen-tab-..-..-etc`). Lỗi box đi lên **nguyên văn** (`BoxRequestError`; 409 `Nhiều tab khớp target — chọn chính xác hơn (tabId)`). Vế cổng chỉ siết **kỹ thuật**: `_capture_target_label` + `caption` vào khoá trắng `runtime.evidence_pointers`; payload `assistant.data.evidence` vẫn phát nguyên vẹn. Cổng **không** nới luật: vẫn **11** `REASONS`, **3** `VERDICTS`, `CAPTURE_ARTIFACT_KINDS == ('image','record')`.

**Nợ của vòng, đã ghi sổ:** bản `capture.py` trong repo (`sha256 b24541cd…409a1`) **khác** bản trong container (`19893dde…e3b5`); `docker exec agentbox-box grep -c _key_with_label` = **0**. Bản cũ vẫn chạy đúng vì nó bỏ qua khoá `label` — nghĩa là **nhãn chưa vào tên tệp cho tới khi nạp**, và đó là việc của lượt nghiệm thu sống (Phần 5).

### Phần 3 — P4/P5: mặt câu trả lời chỉ còn markdown, chữ đi theo ngôn ngữ câu trả lời

`MarkdownRenderer` thêm hai đường: ảnh ⇒ tile bấm mở khung lớn (`AnswerImageTile`, `w-40 h-24`, `cursor-zoom-in`, nhãn + basename dưới tile), và link tới tệp bằng chứng ⇒ mở **tab Files** thay vì tab trình duyệt. `HarnessStepView` **xoá** khối gập `EvidenceBlock` (262 dòng), huy hiệu ba trạng thái, `EVIDENCE_BADGE_CLASS`/`evidenceTitleText`/`receiptChargeText`, dòng `data-evidence-note` và lưới media của app (2773 → 2519 dòng). Chú thích ảnh hết viết cứng (`MediaCaptionKind`, `MEDIA_CAPTION_KEYS`, `captureKindOf`). Ngôn ngữ: `answerLang` chọn theo **câu trả lời**, nhãn quanh lượt đi theo ngôn ngữ ấy (`answerLabels`, `dicts`); 34 giá trị `evidence*` trong `en.ts` hết tiếng Việt.

**Hệ quả đã chấp nhận (D-19/D-20), ghi để không ai đọc là hồi quy:** verdict/mode của cổng, câu bị ghim, sha256, exit code, thời lượng **không còn hiện ở đâu trong app** (chỉ còn qua tab Files); năm bộ thu thập trong `HarnessStepView` (`chargedClaimText`, `evidenceReasonText`, `turnArtifactFacts`, `collectTurnArtifacts`, `collectTurnCommands`) sống chỉ nhờ bài kiểm — **cố ý giữ** cho vòng "agent verify".

### Phần 4 — Hậu kiểm: hai vòng soát mã độc lập + một vòng soát dọn, bốn lỗi/lỗ hổng đã sửa

| # | Phát hiện | Mức | Cách sửa (`commit`) |
|---|---|---|---|
| 1 | Ảnh nằm trong liên kết (`[![nhãn](anh.png)](https://tài-liệu)`) dựng thành `<button>` **lồng trong** `<a target="_blank">` ⇒ một cú bấm vừa mở khung xem lớn vừa mở tab mới, ARIA/HTML sai | vừa | `PassiveMediaContext` (`db5d0ff`): liên kết bật cờ quanh chữ của nó, bộ dựng ảnh vẽ ảnh **tĩnh**; hai ca kiểm mới ghim `button`=0 và "bấm `<a>` không gọi `onOpenImage`" |
| 2 | Việc **phân loại** link cắt `?query`/`#fragment` để quyết định nhưng giá trị trao cho `onOpenFile`/URL media là chuỗi **thô** ⇒ `…x.txt?raw=1`, `…x.txt#L12`, `./.generated_artifacts/a.png`, `shots/a.png` mở hỏng | vừa | một hàm `normalizeArtifactPath` dùng cho **cả** phân loại lẫn giá trị gửi đi; `href` thô vẫn giữ cho đường dự phòng của trình duyệt (`db5d0ff`) |
| 3 | `answerLang` cho câu trả lời **tiếng Anh** trích chuỗi giao diện tiếng Việt trong backtick là `vi` (dương tính giả); ngược lại không nhận ra tiếng Việt **không dấu** | thấp–vừa | `stripCode` bỏ khối ```/~~~ (kể cả khối chưa đóng lúc đang stream) và span mã trước khi đếm; **giới hạn đã biết ghi thẳng trong docstring**, không hứa (`db5d0ff`) |
| 4 | Bản nhắc việc gọi **kết quả của chuyên gia con** là "owner request" — `drain_peer_deliveries` bơm kết quả vào transcript **cùng bước** dựng recap — rồi `RECAP_CLOSER` bảo model đi chụp lại đúng thứ đó | vừa–thấp | `runtime.PEER_DELIVERY_PREFIX` là **một nguồn** cho cả chỗ viết lẫn chỗ đọc; hết việc của chủ ⇒ `owner request (excerpt): not found in this transcript`; ca hồi quy **ĐỎ trước khi sửa**, XANH sau, và vẫn khẳng định kết quả chuyên gia tới được model (`7d00c35`) |

Dọn theo vòng soát dọn: xoá `WORKER` trùng ở `executor.py`, xoá `CAPTURE_TARGET_KEYS` không ai dùng, `capture_label(caption)` bỏ tham số `limit`, bỏ helper `marker_count` trong bài kiểm, xoá khối 4 dòng trùng ở `test_capture_session_identity.py`; phía giao diện: xoá `EvidenceBadgeState`/`EVIDENCE_VERDICT_STATE`/`AnswerEvidence.state` (`grep` = 0), gộp hai bản dự phòng từ điển vào `i18n/context.labelFrom`, hai nhãn mở/gấp thành khoá từ điển **ở cả hai ngôn ngữ** (trước là hai hằng số tiếng Anh viết cứng), xoá ba chú thích cũ còn nói về khối đã bỏ.

**Bảy điều cố ý KHÔNG "dọn" (đã đọc mã để chốt):** `system_media.py` import schema từ `tool_contracts.py` (một nguồn, không có bản sao đôi); slug lần hai phía box (ghim bởi `test_label_is_slugged_at_the_box_and_never_leaves_a_bare_dash`); năm tên mục ở `runtime` **và** `AGENT.md` (cả hai bắt buộc); năm bộ thu thập trong `HarnessStepView.tsx` (biên nhận `TurnBlock` còn tiêu thụ + D-20 hứa); khoá nhãn ở `evidence_gate.py:369` so với `executor.py:17` (khác module/consumer); `MediaLightboxModal.artifactPath?` (khai trước cho footer chưa dựng); `normalize_capture_target` (một caller nhưng dùng **cả hai** nửa). **Nhánh `output_path` trong `system_media.py` cũng được GIỮ**: nó không chết — nó là chốt từ chối giá trị hình dạng traversal mà model có thể tự bịa (schema chỉ kiểm `required`), và `test_system_media_tools.py:19-20` đang ghim hành vi đó.

### Phần 5 — Nghiệm thu sống của vòng (testing agent, cây `0742511`)

**Vòng kiểm thử độc lập đã chạy trên cây `0742511`** (báo cáo đầy đủ: `/var/tmp/v23/test-report.md`; mọi số dưới đây do chính vòng ấy đo lại, không lấy lời khai của người viết mã). Bản đối chứng là bản trích nguyên `1be2772` ở `/var/tmp/v23/base`.

- **Bộ kiểm**: `backend/tests/unit` **1 failed / 1109 passed** (bản đối chứng 1 failed / 1080 — **đúng một ca đỏ như nhau**, `test_terminal_tools.py::test_terminal_exec_echo`, lệnh PowerShell trên Linux ⇒ **không phải hồi quy**); `deploy/docker/tests` **501 passed** (đối chứng 496); `test_runtime_prompt.py` 13; `test_delivery_injection.py` 7; `test_skill_commands.py` + `test_skills_registry.py` 187; `test_capture_session_identity.py` 10; cặp cổng 52; frontend `vitest run` **124 tệp / 1043 ca** (đối chứng 123/1019); `tsc -b --noEmit` exit 0 (đối chứng exit 0).
- **P1/P1.5 sống**: tên **năm mục** có mặt trong **cả 14** request gửi provider (không chỉ trong mã); bản nhắc việc có ở lượt chụp ảnh và lượt chạy lệnh (in cả lệnh + `exit 0`), và **KHÔNG có** ở lượt chỉ đọc — đúng ca âm mà kế hoạch đòi.
- **P2 sống**: harness thật sự gửi `target` + `caption` xuống box (`tool_end` của lượt 1: `target={"kind":"tab","url":"127.0.0.1:8099","label":"trang-fixture-sau-khi-sua"}`, `caption="Trang fixture sau khi sửa"`); **cả ba loại** chụp được thật — `tab` (CDP, 1042×494), `window` (x11 `0x01600011`, 1050×743), `screen` (x11 1280×800), mỗi loại vào đúng thư mục và mang tên đúng khuôn; `target` rác (`kind:'nope'`) ⇒ rơi về `screen`; lỗi box đi lên **nguyên văn** (`Không tìm thấy cửa sổ khớp target`).
- **P3 sống**: sáu lượt trên harness scratch `3124` cho đúng cặp đối chứng — lượt 1 chụp sau khi đổi ⇒ `sufficient` (checked 1, artifacts 1, missing 0); lượt 2 cùng loại việc **không** chụp ⇒ `insufficient / ui_change_without_capture`; lượt chỉ đọc `sufficient` checked 0; `VERDICTS` vẫn 3 / `REASONS` vẫn 11; payload `assistant.data.evidence` vẫn đủ trường cho giao diện.
- **P4 sống, CÙNG một phiên, hai frontend** (`707c9fb2`): frontend nguyên bản (Vite `3130`) thấy **6/6** dấu vết khối/huy hiệu cũ + huy hiệu `chưa kiểm chứng`; frontend mới (Vite `3100`) thấy **0/6** dấu vết ấy, **1** tile ảnh thật (`data-capture-file = 707c9fb2_001_tab-…png`, nhãn `Ảnh chứng minh trang fixture`, ảnh **đã nạp thật** `naturalWidth 1042`), bấm tile ⇒ khung xem lớn 1042×494; link `pytest-result.txt` mở **tab Workspace Files** và panel mở **đúng tệp thật** (`PASSED: 12 tests`) trong khi `location.href` **không đổi**. Ba ca biên mới đều đạt: (1) `[![label](capture.png)](#evidence)` ⇒ `a button` = **0** trong trang và một cú bấm **không** mở khung xem lớn; (2) link tệp bằng chứng ghi kèm `?rev=2#L3` ⇒ panel Files nhận **đường dẫn đã làm sạch** và mở được tệp; (3) câu trả lời tiếng Anh trích chuỗi giao diện tiếng Việt trong backtick ⇒ nhãn ra **tiếng Anh**.
- **P5 sống**: ba lượt trong một phiên — đáp án tiếng Việt ⇒ `Mở trong Files`/`› Xem chi tiết`; đáp án tiếng Anh ⇒ `Open in Files`/`› View details`; đáp án **trộn** (chữ Anh + chuỗi Việt trong backtick) ⇒ vẫn tiếng Anh.
- **Đối kháng**: chụp `window` khi có phiên ghi X11 ⇒ câu từ chối nguyên văn (chụp `tab` cùng lúc vẫn được vì đi CDP); hai tab cùng URL ⇒ `Nhiều tab khớp target — chọn chính xác hơn` rồi chụp lại được sau khi đóng tab thừa; khử trùng theo nội dung (`deduplicateOf`) chạy đúng như thiết kế; hằng số lưu trữ và các bộ ghi nhật ký `E:` không bị đụng.
- **Ảnh/g hi hình của vòng** (`/code/.generated_artifacts/`): `images/r23_00_before_real_app.png` (mặt TRƯỚC: khối + huy hiệu `chưa kiểm chứng`), `images/r23_01_after_real_app.png` và `images/r23_14_answer_with_shot.png` (mặt SAU: chữ năm mục + tile ảnh thật có nhãn), `images/r23_15_shot_zoom.png` (khung xem lớn), `images/r23_16_evidence_file_open.png` (panel Files mở đúng tệp bằng chứng), `images/r23_17_no_block.png` (chữ năm mục, **0** dấu vết khối), `images/r23_18_lang_vi.png` / `images/r23_19_lang_en.png` (nhãn theo ngôn ngữ đáp án), ghi hình `recordings/v23_ui_face.webm`.
- **Một mục KHÔNG kiểm được sống, nói thẳng ra**: nhãn vào tên tệp **qua đường HTTP `:8081`** không tái hiện được trên box này vì `ide-proxy` (pid 7399, dựng từ Sep 22 18:03) giữ mô-đun `capture` **cũ trong RAM** — `docker cp` đổi tệp chứ không đổi tiến trình, mà khởi động lại box là việc ngoài phạm vi. Đã kiểm bằng đúng cách kế hoạch chỉ (`dispatch_capture({'kind':'screen','label':'trang-chu-sau-sua'}, …)` **trong box** ⇒ `…_001_screen-trang-chu-sau-sua.png`; không nhãn ⇒ `…_002_screen.png`) + so tên cũ/mới + chứng minh sống rằng harness **có** gửi `label`. `ide-proxy` chuyển `target` nguyên vẹn (bản repo == bản box, sha `c829baed…`) nên box dựng lại sẽ hành xử như lời gọi trong box.
- **Trạng thái máy sau vòng kiểm**: repo sạch ở `0742511`; các tiến trình của chủ nhà **không bị đụng** (PID y nguyên); Vite `3130` và harness `3124` đã dừng; fixture web server trong box đã dừng; `box-chromium` đã đóng (**CDP 9222 OFF**); `capture.py` trong box vẫn là bản mới `b24541cd…` (bản cũ giữ ở `old_capture_a4d60f9.py`).

**Ghi nhận độ lệch đã chốt với chủ nhà:** P6.3 của kế hoạch ghi "qua harness 3102"; lượt nghiệm thu chạy trên harness **scratch 3124** (data dir riêng, cổng `warn`) để không đụng phiên sống của chủ nhà — cùng khuôn `docker cp` và cùng bộ ca. Bộ kiểm giao diện **bắt buộc** chạy kèm `VITE_BOX_API_URL=http://localhost:8081` vì `frontend/.env.local` (untracked) đặt `VITE_BOX_API_URL=.` làm `src/lib/workspace/index.test.ts` đỏ — ca đó có sẵn từ trước và tái hiện y hệt trên bản gốc.

### Phần 6 — Số đo kiểm thử của vòng

| Bộ | Trước vòng 23 | Sau vòng 23 (`0742511`) |
|---|---|---|
| `backend/tests/unit -q` | 1 failed / 1080 passed | **1 failed / 1109 passed** (đỏ duy nhất là ca môi trường `test_terminal_tools.py::test_terminal_exec_echo`) |
| Nhóm focused backend (9 tệp) | — | **284 passed** |
| `deploy/docker/tests` | 496 passed | **501 passed** |
| `frontend npx vitest run` (kèm `VITE_BOX_API_URL`) | 123 tệp / 1019 ca | **124 tệp / 1043 ca đạt** |
| `npx tsc -b --noEmit` | exit 0 | **exit 0** |
| `npx eslint` trên 13 tệp đã đụng | — | **exit 0** |

Ca kiểm mới ghim hợp đồng đã chốt: khuôn năm phần trong prompt sống; `AGENT.md` § 3.4; bản nhắc việc không lọt vào câu trả lời; `target` window/tab đi nguyên và rác ⇒ `screen`; nhãn vào tên tệp (ba kịch bản screen/window/tab); cổng giữ đúng 11 mã lý do và `CAPTURE_ARTIFACT_KINDS`; mặt câu trả lời **không còn** hook `data-evidence-*`; tile ảnh + khung xem lớn + link mở tab Files; `en.ts` không còn dấu tiếng Việt; `answerLang` với chữ-trong-mã (4 ca); ảnh trong liên kết (2 ca); bản nhắc việc không gọi kết quả chuyên gia là việc của chủ (3 ca).

### Phần 7 — Khẳng định cố ý đổi ở vòng này

- **Số của cổng rời khỏi mặt câu trả lời** (D-19/D-20): trước đây huy hiệu + khối in `verdict`, số mảnh, câu bị ghim, sha256, mã thoát; nay mặt đó chỉ còn markdown do model viết. Dữ liệu vẫn nằm trên event `assistant.data.evidence` và trong sổ.
- **§ 6.29 đổi nghĩa**: bài toán "hai hàng ảnh đọc giống nhau" không giải bằng cách nới hàng đường dẫn mà bằng **nhãn nằm trong tên tệp** + tile in basename — mặt cũ biến mất cùng khối.
- **Hai tệp `en.ts`/`vi.ts` không còn đối xứng ở khối bằng chứng**: 34 giá trị `evidence*` của `en.ts` đã dịch, **bốn khoá `subagent*` vẫn cố ý giữ tiếng Việt** (ngoài phạm vi P5.2) — người đọc sổ đừng coi là sót.

## Vòng 24 — câu trả lời cuối bỏ khuôn cứng: trả lời như thường, báo cáo khi có việc, tóm tắt + "View details" chạy lại, ảnh bằng chứng khép câu trả lời (2026-09-23, chiều)

Chủ nhà bác khuôn năm phần của vòng 23 bằng bốn điểm (nguyên văn ở `bug-register.md` §6.32 và `owner-decisions.md` §4.2), rồi tinh chỉnh
"form vào 1 chút… chỉ quan trọng nhất là phần ảnh dãn chứng ở dưới". Kế hoạch **v3** (`/code/.plans/v3-answer-shape.md`, duyệt 07:45 UTC)
chốt D-26…D-32. Ba đợt của kế hoạch: P1 prompt/kỹ năng, P2 ghim hợp đồng mới, P3 nghiệm thu sống, P4 sổ.

### Phần 1 — P1: dạng câu trả lời DỜI khỏi prompt, kỹ năng `final-report` giữ nó

- `runtime.py`: xoá hẳn `FINAL_REPORT_PARTS`, `FINAL_REPORT_GUIDANCE` và khối `=== FINAL REPORT ===`; thay bằng `ANSWER_EVIDENCE_LINE`
  (một câu điều kiện, ASCII, ≤ 200 ký tự) chèn **ngay sau** `=== ANSWER LENGTH ===` và **chỉ** ở phiên chính (D-18/D-32). SOP chỉ còn
  một dòng trung thực, không trỏ về khối nào.
- Kỹ năng `final-report` **2.0.0**: menu năm mục nhưng là **menu, không phải khuôn** ("pick by content, not habit"), luật **không in
  phần rỗng**, luật mở bài bằng **một đoạn văn xuôi** (để mặt gấp còn tóm tắt do model viết — D-29), mục **The evidence part closes the
  answer** (D-30), bảng bằng chứng theo loại việc, cách chụp (`target`/`caption`), ví dụ nguyên lượt `9481bf87`. Ở lại `DEFAULT_SKILLS` (D-31).
- **Một con trỏ** ở bước tổng kết: `RECAP_CLOSER` bảo model mở kỹ năng bằng `skill_view`; recap chỉ phiên chính, chỉ đi kèm **yêu cầu
  của bước**, rỗng khi lượt không đổi gì ⇒ lượt chỉ hỏi không bao giờ thấy con trỏ (D-28).
- `AGENT.md` §3.4 chỉ trỏ về kỹ năng (bản nạp thật cho **mọi** vai nên cố ý không chép menu; bullet markdown-only của D-19 giữ nguyên).
- **Mã sản phẩm giao diện KHÔNG đổi** (`git diff -- HarnessStepView.tsx` rỗng): điểm ④ là lỗi của **prompt ép hình dạng**, không phải
  của bộ dò tóm tắt.

### Phần 2 — P2: ghim hợp đồng mới (2 tệp kiểm)

- `backend/tests/unit/test_runtime_prompt.py` (LF, 17 ca): vắng khối/khuôn; `hasattr` âm cho hai hằng cũ; bốn câu `RETIRED` vắng ở **bốn
  chỗ** (đọc thẳng tệp `runtime.py`, SOP, `AGENT.md` §3.4, kỹ năng); `ANSWER_EVIDENCE_LINE` đúng **một lần**, **sau** `=== ANSWER LENGTH ===`,
  ASCII, ≤ 200 ký tự, **vắng** ở mọi vai con; khối kỹ năng không bị nhân đôi khi prompt được dựng lại (ghim cho lỗi `_next_turn_skills`
  của vòng 23); kỹ năng giữ menu + luật mở bài + luật ảnh cuối + `never print an empty part`; con trỏ ở bước tổng kết trỏ tới kỹ năng,
  recap rỗng ở lượt chỉ đọc.
- `frontend/src/components/chat/HarnessStepView.test.tsx` (CRLF, 31 ca): ca mới — mở bài một đoạn văn xuôi + dòng trống + phần sau
  **kể cả ảnh ở cuối** ⇒ tóm tắt ĐÚNG đoạn đó, mặt gấp không chứa chữ của phần sau, sau khi mở thì **ảnh là khối CUỐI**; và ca mở bài
  bằng tiêu đề ⇒ rơi về lát cắt 6 dòng/600 ký tự.

### Phần 3 — Hậu kiểm: một vòng soát mã + một vòng soát dọn

- **Soát mã** (risk **3/10**, "ship with mitigations"): nguồn sự thật duy nhất đúng; con trỏ tới được thật; ghim mạnh, **hai chỗ mềm**
  (menu chỉ ghim sự hiện diện của năm tên mục; ghim §3.4/SOP bám đúng định dạng `- **Tên mục**`). Tìm ra lỗ: không ghim nào chặn kỹ năng
  **trôi ngược thành khuôn cứng**.
- **Soát dọn**: luật "ảnh khép câu trả lời" bị chép **bốn lần**; ba bản có chủ và có ghim, bản trong `RECAP_CLOSER` là bản duy nhất không
  ghim ⇒ bỏ vế đó (luật vẫn đi ở `runtime.py:761` cho mọi lượt phiên chính); bỏ một gạch trùng luật trong kỹ năng; gọn tệp kiểm (hai
  tham số `tmp_path` không dùng, một assert đếm trùng).
- **Bù lỗ của soát mã** (`68125ea`): ghim chống trôi D-26 — kỹ năng không được chứa `all five` / `five parts` / `every part` /
  `in this order` / `must use`, và phải giữ `pick by content, not habit`.

### Phần 4 — Nghiệm thu sống của vòng (testing agent, cây `37926e0`)

| Trên payload gửi provider | Trước (v23 `0114.json`) | Lượt việc (`0117.json`) | Lượt hỏi (`0118.json`) |
|---|---|---|---|
| `=== FINAL REPORT ===` / `five parts` / `in this order` | 1 / 3 / 2 | **0 / 0 / 0** | **0 / 0 / 0** |
| câu `ANSWER_EVIDENCE_LINE` | 0 | **1** | **1** |
| con trỏ `` read the `final-report` skill with `skill_view` `` trong `messages` | 0 | **1** (từ bước có việc trở đi: `0115`=0 → `0116`=1 → `0117`=1) | **0** |

- **Ba mặt giao diện ĐẠT** (Vite scratch → harness scratch, `agent-browser` 0.21.2): gấp = đúng một đoạn văn xuôi + nút mở; mở = phần model
  chọn rồi **ô ảnh bằng chứng ở CUỐI** (`data-artifact-open="media"`, ảnh tải thật 1280×800 qua `/__box/file/media`, nhãn
  `[data-capture-label="true"]` + tên tệp); lượt hỏi = văn xuôi liền mạch, **0** nút mở, **0** tiêu đề mục, **0** ảnh nội dung. Ba mặt khớp
  cấu trúc năm mặt thiết kế `lv24-*.html` (khác chỉ ở ngôn ngữ chrome của app và số phần, vì lượt stub nhỏ hơn lượt thật trong mock).
- **Provider thật**: model `nemotron-3.5-lightning-free` chạy `terminal_exec` rồi **gọi `skill_view {"id": "final-report"}`** và trả lời **một
  dòng văn xuôi** (99 ký tự), không khuôn; nội dung kỹ năng nhận được đúng bản v2.0.0. Lượt thật không có ảnh nên "ảnh ở cuối" chỉ chứng minh
  bằng lượt stub; và mới đo **một** lượt, một model.
- Harness scratch khởi động **sau** mtime của cả sáu tệp sản phẩm (07:52:32 > 07:48–07:50) ⇒ số đo thuộc đúng mã vòng 24.

### Phần 5 — Số đo kiểm thử của vòng

| Bộ | Trước vòng 24 | Sau vòng 24 (`37926e0` + `68125ea`) |
|---|---|---|
| `backend/tests/unit -q` (bỏ ca môi trường PowerShell) | 1113 passed / 1 deselected | **1113 passed / 1 deselected** |
| `test_runtime_prompt.py` | 4 ca | **17 passed** |
| `frontend/src/components/chat` | — | **108 passed** |
| `HarnessStepView.test.tsx` | 29 ca | **31 passed** |
| `frontend npx vitest run` (kèm `VITE_BOX_API_URL`) | 124 tệp / 1045 ca | **124 tệp / 1045 ca** |
| `npx tsc -b --noEmit` | exit 0 | **exit 0** |
| `npx eslint` trên tệp đã đụng | — | **exit 0** |

Đỏ có sẵn, không phải hồi quy: `test_terminal_tools.py::test_terminal_exec_echo` (box không có PowerShell) và
`frontend/src/lib/workspace/index.test.ts` (cần `VITE_BOX_API_URL=http://localhost:8081` vì `frontend/.env.local` untracked đặt `VITE_BOX_API_URL=.`).

### Phần 6 — Khẳng định cố ý đổi ở vòng này

- **Đảo chiều vòng 23**: khuôn năm phần ra khỏi prompt; dạng câu trả lời nay nằm trong kỹ năng, prompt chỉ giữ **một dòng bằng chứng**
  (phiên chính) và **một con trỏ** ở bước tổng kết của lượt có việc.
- **`RECAP_CLOSER` bỏ vế "and close the answer with those images"** (kế hoạch v3 §2(d) ghi nguyên văn câu đó) theo soát dọn — luật không
  mất vì `runtime.py:761` vẫn đi ở mọi lượt phiên chính và kỹ năng có mục *The evidence part closes the answer*.
- **Đánh đổi đã nhận (D-31)**: model không mở kỹ năng ⇒ lượt vẫn có **ảnh bằng chứng** (nhờ dòng cứng) nhưng **thiếu menu**. Lượt provider
  thật đã mở kỹ năng, nên rủi ro này chỉ còn trên giấy — nhưng chưa đo tỉ lệ.
- **Sổ đổi số mục**: `owner-decisions.md` §4 nay có §4.1 (vòng 23) / §4.2 (vòng 24) thay vì một §4.1 như kế hoạch ghi, để sổ đọc được theo vòng.

## Vòng 25 — vòng lặp kế hoạch: phản biện độc lập BẮT BUỘC trước khi duyệt, hai cổng chặn cứng có công tắc, cú bấm ở tab Plan mở LƯỢT THẬT (2026-09-23, chiều)

Chủ nhà giao ba việc về khả năng lên kế hoạch (nguyên văn ở `bug-register.md` §6.33). Đo trước khi sửa: sáu lượt lập kế hoạch, sau
`plan_written` lượt **dừng ngay**; ba cú bấm ở tab Plan để lại dấu vết rồi **im lặng 55-60 s**; bảy lỗi ghi thành BUG-72…BUG-78
(`/code/.plans/v25-evidence-brief.md`). Kế hoạch vòng 25 (`/code/.plans/v1-plan-loop.md`, duyệt cùng ngày) chia **mười milestone
harness** (M1–M10) + **một phạm vi giao diện B**, chốt **D-33…D-38** (`owner-decisions.md` §4.3). Nguồn sự thật thi công:
`/code/.plans/subplans/v25-harness-plan.md` và `/code/.plans/subplans/v25-ui-plan.md`.

### Phần 1 — M1–M4: vai phản biện, hai sổ, cổng chặn cứng ở HAI đường

- **M1 — vai `plan-review` (vai thứ 10)**: `roles.py` thêm `Role('plan-review', 'Plan review', …, READ, ('codebase-inspection',))` +
  `PLAN_REVIEW_INSTRUCTIONS`; `ORCHESTRATOR_TOOLS` 24 → **25** (`plan_verify`); SOP có bước phản biện; kỹ năng mới `planning` (LF) vào
  `DEFAULT_SKILLS`, trong đó có nguyên văn *"without a critique you cannot request approval"*. Ghim: `test_plan_review_role.py` **11 ca**
  (vai chỉ-đọc, không có `terminal_exec`/`file_edit_block`, enum `delegate_task` đủ 10 vai, kỹ năng nằm trong bộ mặc định, SOP trỏ đúng bước).
- **M2 — hai sổ mới**: `session_store.py` thêm bảng `plan_owners` (`identity, session_id, first_session_id, slug, relative_path,
  version, created, updated`) và `plan_verifications` (`identity, version, verdict, issues, summary, critic_session_id,
  critic_answer_chars, critic_verdict, created`), thêm cột `plan_reviews.resumed`, và các hàm đọc/ghi tương ứng. **Cố ý** không đưa hai
  sổ này vào cascade `delete()`: chúng gắn với *kế hoạch*, không gắn với phiên. Ghim: `test_plan_verify_store.py` **8 ca**.
- **M3 — công cụ `plan_verify` + cổng nguồn gốc phán quyết**: `tool_contracts.py` có schema (verdict `ok|revise`, danh sách `issues` có
  `severity`/`text`/`fix`); `runtime.dispatch()` chỉ ghi sổ khi bài phản biện đến từ **phiên con thật** (`critic_session_id` +
  `critic_answer_chars`), trần `PLAN_VERIFY_MAX_ISSUES = 30`, trần **2 vòng `revise`** (`PLAN_VERIFY_REVISE_MAX`). Ghim: `test_plan_verify.py`
  **21 ca**, gồm ca `PLAN_VERIFY_VERDICT_MISSING` (bài phản biện không có dòng `VERDICT:` ⇒ **không** ghi sổ).
- **M4 — cổng duyệt hai đường**: `runtime.plan_approval_blocked()` + `decision()` (đường chat) và route `POST /api/agent/plans/review`
  (đường tab Plan) dùng **cùng một câu từ chối**; công tắc `BOXFOX_PLAN_VERIFY` ba nấc `enforce|warn|off`; mã mới
  `PLAN_APPROVAL_UNVERIFIED` + `PLAN_SOURCES_REJECTED`. Ghim: `test_plan_verify_gate.py` **16 ca** + `test_plan_sources_gate.py` **10 ca**.

### Phần 2 — M5–M9: API, cú bấm mở lượt thật, ngữ nghĩa sổ, hạn chót, cổng nguồn

- **M5 — trạng thái đọc được**: `GET /api/agent/plans/status` thêm `verification` (`state: none|ok|revise|unknown`, `at`, `criticSessionId`,
  `issues`) và `ownership` (`sessionId`); `session_metrics()` thêm `lastTurn` để lượt dở nói được là dở.
- **M6 — cú bấm ở tab Plan MỞ LƯỢT THẬT** (BUG-73): `plan_wake()` gọi `runtime.submit()` với `invocation_id` suy từ chính nội dung quyết
  định (`sha1(identity@version:decision:note)`) nên bấm trùng trả `PLAN_WAKE_DUPLICATE` thay vì mở lượt hai; `SESSION_BUSY` ⇒ `busy`;
  không biết chủ ⇒ `PLAN_WAKE_NO_OWNER` + `wake.state='missing'`; mọi nhánh đều có mã + câu giải thích, **không bao giờ im lặng**.
  Route ghi luôn **phiên sở hữu** vào hàng sổ (`session_id=owned`, trước đây toàn `NULL`). Ghim: `test_plan_routes.py` **21 ca** (6 ca
  đỏ đã sửa trong milestone này).
- **M7 — ngữ nghĩa sổ duyệt** (BUG-77, BUG-78): `settle()` gọi `record_plan_decision` **trước** `decision_resolved`; hết hạn/huỷ **không**
  sinh hàng `changes_requested` giả; `ask_user` khai được `planIdentity`/`planVersion`. Ghim: `test_plan_approval_ledger.py` **11 ca**.
- **M8 — hạn chót** (BUG-75): `DEADLINE_DEFAULT_SECONDS 180 → 600`, `DEADLINE_MAX_SECONDS 600 → 1200`, `CHILD_DEADLINE_SECONDS 300 → 420`,
  `PLAN_TURN_EXTENSION_SECONDS = 420` + `extend_turn_budget()` nới **một lần** khi lượt đã ghi được kế hoạch, kèm `notice TURN_EXTENDED`.
  Ghim: `test_plan_deadline.py` **9 ca**.
- **M9 — cổng nguồn** (`BOXFOX_PLAN_SOURCES_GATE`, D-34/D-…): `plan_quality.py` có `_find_with_body`/`source_lines`/`cited_hosts`/
  `sources_issues`/`sources_message`; bản kế hoạch dựa vào dữ kiện ngoài mà nguồn không đến từ phiên con `research`/`explore` **của chính
  phiên đó** thì `write_plan` trả `PLAN_SOURCES_REJECTED`. Ghim: `test_plan_sources_gate.py` **10 ca** + `test_write_plan.py` **20 ca**.

### Phần 3 — Phạm vi B (giao diện): mặt tab Plan đọc SỔ THẬT thay vì nhãn box

Subagent `build-ui` (task `build-ui`, success) giao: `PlanPanel.tsx` (chip trạng thái duyệt + phản biện, dải vàng cảnh báo, dải chủ sở hữu
+ nút **Open that session**, nút **Approve** bị khoá khi chưa phản biện), `PlanReviewCard.tsx` **mới** (+ `.test.tsx`) — mũi tên nhỏ
`aria-label="Approve with conditions"` mở popup nhập điều kiện (D-38), `usePlanFiles.ts` (+2 tệp test) truyền `note` và đọc
`verification`/`ownership`, `lib/plans/planState.ts` (+test) nói đúng mặt `none|ok|revise|unknown`, `lib/agentApi.ts` (+test),
`SubagentInspectorPanel.tsx` (10 vai), `CommandsView.tsx`, `lib/harnessRoles.ts` (+test), `i18n/en.ts` + `i18n/vi.ts`.
Ghim: `PlanReviewCard.test.tsx` giữ điều kiện của D-38 (không nhập gì ⇒ vẫn là Approve thường). Ảnh mặt mới: `r25_11`…`r25_14`.
**BUG-76 cố ý để lại một nửa**: API thô của box vẫn gán nhãn version theo **vị trí** (`deploy/docker/plan_files.py:841-844`) vì vòng này
**không rebuild box**; tab Plan đã thôi in nhãn đó.

### Phần 4 — Đo sống của vòng (harness scratch 3116 + router thật 3101, 2026-09-23 11:40–12:10 UTC)

| Việc | Cách đo | Kết quả |
|---|---|---|
| **V-LIVE-1** SOP lập kế hoạch có phản biện | lượt thật `c75876dd1f034ae6a937147b6bb9c43a` (`muse-spark-1.3-contributor-free`, `maxSteps 40`, `deadlineSeconds 600`) | **ĐẠT phần chuỗi**: `completed` ở **540 s / 18 bước / 8 phiên con** (1 `research` + 3 `plan-review`), chuỗi công cụ `delegate_task → write_plan → peer_read ×6 → delegate_task → plan_verify → write_plan → skill_view → write_plan → delegate_task → plan_verify → skill_view`; `plan_verifications` **2 hàng** (`v1 revise` critic `7f59b913…` 1422 chữ; `v2 revise` critic `b748e42a…` 1648 chữ); `notice TURN_EXTENDED +420 s`; mô hình tự dừng ở trần 2 vòng và báo thật (*"…cả hai đều kết luận cần sửa, nên tôi chưa thể xin duyệt"*). **KHÔNG đạt tiêu chí `verdict='ok'`** — lý do là **đề bài mẫu** cài tiền đề sai (đòi retry Python/aiohttp cho lời gọi model thật nằm ở Node), phản biện bắt đúng; **cố ý không nới cổng cho xanh**. |
| **V-LIVE-1b** lượt thứ hai, đề bài khác | lượt thật `9d61a079ca734b84a2770a061db6f789` (đề bài trong-repo, nhỏ) | `completed` ở **660 s / 24 bước**; `plan_written` v1 + `plan_evaluated` 14/16 + `TURN_EXTENDED`; phiên con `plan-review` chạy **16 bước**, tự grep mã, bắt **8 lỗi thật** của bản mẫu; mô hình tự chạy thêm một phiên `plan-review` ngắn để có dòng `VERDICT:` rồi **báo thật, không xin duyệt**; lời gọi `plan_verify` của lượt này bị từ chối đúng thiết kế (`PLAN_VERIFY_VERDICT_MISSING` — bài phản biện bị **cắt cụt dòng verdict**) nên lượt đó **không có hàng sổ**. |
| **V-LIVE-2** cú bấm "Request changes" mở lượt thật | `POST /plans/review {retry-model-calls, v2, changes_requested, note="Đổi mục Risks: bỏ retry POST/PATCH…"}` | **200** + `recorded: true` + `resumed: true` + `turnId: c75876dd…#2` + `wake.state: opened`; **~4 s sau** phiên sở hữu có event `user` `[Tab Plan] chủ nhà yêu cầu sửa kế hoạch retry-model-calls@v2 …`; hàng sổ mới có `note` nguyên văn + `resumed: 1` + `session_id` = phiên sở hữu; lượt mới **8 bước**, ghi v2→**v3**→**v4**, có 2 phiên con `plan-review`, hàng `plan_verifications@v4 revise`, và bản v3/v4 **thực hiện đúng điều kiện chủ nhà gõ ở tab** |
| **V-LIVE-3** cổng ở CẢ HAI mặt | (a) duyệt bản `revise` ⇒ **409** `PLAN_APPROVAL_UNVERIFIED` + **0 hàng** sổ mới, đo **cả trên UI** (`r25_13`: *Harness blocked the approval (PLAN_APPROVAL_UNVERIFIED)*); (b) duyệt bản có `ok` ⇒ **200** + hàng `approved` (`source: plan-tab`, `contentSize`/`contentModifiedAt` từ chỉ mục box) — hàng `ok` này là **hàng gieo có nhãn** vì lượt đo thật chưa đạt `ok`; (c) `warn` ⇒ 200 + `approvalWarning` + 1 dòng `plan.approval.unverified`; (d) `off` ⇒ 200, 0 dòng | Đủ bốn mặt |
| **V-LIVE-4** `plans/status` | `GET /plans/status?identity=retry-model-calls&version=2` | `verification.state = "revise"`, `at = "2026-09-23T11:49:04.408Z"`, `criticSessionId = b748e42af1e847bfbc548e99e48d4c18` (phiên con **thật**), `issues` 5 phần tử; `ownership.sessionId = c75876dd1f034ae6a937147b6bb9c43a` |
| **V-LIVE-5** công tắc cổng | hai harness scratch copy DB rồi `DELETE FROM plan_verifications` (3117 `warn`, 3118 `off`) | như bảng V-LIVE-3 (c)/(d); cả hai lần đều `resumed: true` + `turnId …#2` + `wake.state: opened` |
| **Lỗi hạ tầng BUG-79** | lượt sống `1130c2042b6c445db5f1bafc88d8bb94` chết sau 582 s / 15 bước | `TURN_FAILED_TYPEERROR`; tái hiện độc lập bằng router giả (`/var/tmp/v25b/repro_empty_stream.py`); vá một dòng (`await res.read()` → `res.read()`) + ca ghim mới; **đỏ trước / xanh sau** |

### Phần 5 — Số đo kiểm thử của vòng

- **Toàn bộ backend** (`./.venv/bin/python -m pytest backend/tests/unit -q -p no:randomly --deselect …test_terminal_exec_echo`, chạy từ
  gốc repo, 2026-09-23 12:14 UTC): **1210 passed, 1 deselected in 215.29 s** (mốc vòng 24: 1113; vòng 25 thêm 97 ca). Lệnh này phải chạy
  từ **gốc repo** — chạy từ `backend/` làm `test_eval_setup.py` đỏ vì nó tính `REPO = Path(__file__).resolve().parents[3]`.
- **Nhóm plan** (13 tệp): **274 ca đạt**, trong đó `test_plan_routes` 21, `test_plan_verify` 21, `test_write_plan` 20,
  `test_plan_verify_gate` 16, `test_plan_review_role` 11, `test_plan_approval_ledger` 11, `test_plan_sources_gate` 10,
  `test_plan_deadline` 9, `test_plan_verify_store` 8, còn lại `test_plan_quality`, `test_plan_registry`, `test_runtime_info`, `test_plan_eval`.
- **`test_harness_runtime.py`** (tệp của BUG-79): **19 ca đạt** (`6.55 s`), trong đó ca mới chứng minh phán quyết router `502` **không** bị
  thay bằng TypeError và lượt **còn đường thử lại** (`seen == [True, False]`: đúng hai lời gọi).
- **Frontend** (subagent `build-ui`): **126 tệp / 1086 ca đạt**, `tsc -b --noEmit` **exit 0**.
- **Số đo sống**: bảng ở Phần 4 (chạy trên harness scratch 3116 + Vite scratch 3141; **không** đụng 3100/3101/3102/3112/3120/3199 hay container box).

### Phần 6 — Khẳng định cố ý đổi ở vòng này

- **Cổng mới là lớp BỔ SUNG, không thay cổng cũ**: P1–P8 + `HARD_GATES` của `plan_eval.py` vẫn chấm **trước** khi ghi, đúng thứ tự cũ;
  cổng phản biện/nguồn chỉ là lớp thứ hai. `plan_evaluated` của lượt đo sống vẫn `verdict: pass, 14/16`.
- **Hai sổ plan CỐ Ý không nằm trong cascade `delete()`** (`session_store.py`): xoá phiên không được xoá ký ức về kế hoạch.
- **Ghi sổ hỏng thì lượt vẫn đi tiếp**: mọi chỗ ghi sổ trong route/công cụ đều bọc `try/except` + nhật ký, không ném ra ngoài làm hỏng
  lượt của mô hình (`set_plan_review_resumed` là ví dụ).
- **Quyết định của chủ nhà vào sổ TRƯỚC khi đánh thức phiên** (thứ tự trong route: ghi sổ → chuyển tiếp box → wake): chuyển tiếp hỏng
  thì quyết định **vẫn** còn (`forwarded: false` + nhật ký), và wake hỏng thì trả mã chứ không im lặng.
- **Không nới cổng cho xanh**: ba bản kế hoạch của lượt đo đều `revise` và **không** có hàng `ok` nào được ghi; mặt "duyệt bản đã `ok`"
  đo bằng hàng gieo có nhãn, ghi rõ trong sổ — chủ nhà đọc được đâu là **số đo thật**, đâu là **đồ giả để đo đường đi của cổng**.
- **BUG-76 chỉ sửa một nửa (cố ý)**: nhãn version theo vị trí còn trong API thô của box vì vòng này không rebuild box.

### Phần 7 — Hậu kiểm sau thi công: hai vòng soát mã, một vòng soát dọn, một vòng kiểm thử độc lập

Hai vòng soát mã chạy **chỉ-đọc** trên cây đã đóng băng, mỗi phát hiện phải kèm số đo tái hiện được; ba bản vá tiếp theo đều là
commit riêng, đẩy ngay lên nhánh PR (`ef4517d` soát dọn, `9e6b55d` phơi công tắc cổng, `9f2fb95` ba lỗi harness, `f7a8e9e` bảy điểm
giao diện; danh sách lỗi đầy đủ ở `bug-register.md` §6.34 — BUG-80…BUG-87).

- **Vòng soát nửa harness** (`runtime.py`, `api/server.py`, `plan_quality.py`, `roles.py`, `failures.py`, `limits.py`,
  `session_store.py`) — verdict **4/10, Medium, *Ship with mitigations***. Đã kiểm và thấy đứng vững: cổng fail-closed ở **cả hai** đường
  chính (409 trả **trước** `record_plan_review`, không ghi hàng, không chuyển tiếp box); thứ tự **ghi sổ → chuyển tiếp → đánh thức**;
  khử trùng `plan_wake` theo `sha1(identity@version:decision:note)` với mã riêng cho `busy`/`duplicate`/`missing`/`failed`; cổng tất định
  P1–P8 + `HARD_GATES` **vẫn chạy trước** khi ghi; bản vá BUG-79 giữ đúng phán quyết `UPSTREAM_HTTP_502` và đường thử lại. Ba lỗi tìm ra
  (BUG-80 fail-open qua `ask_user`, BUG-81 `lstrip('www.')` ở cổng nguồn, BUG-82 verdict đọc theo vị trí) đều đã sửa kèm ca mới.
- **Vòng soát nửa giao diện** (`PlanPanel.tsx`, `PlanReviewCard.tsx`, `usePlanFiles.ts`, `planState.ts`, i18n) — verdict **4/10, Low,
  *Ship with mitigations***. Đã kiểm và thấy đứng vững: `unknown` **không bao giờ** bị hạ thành `none`; nhánh 409 in **nguyên văn**
  `reason`/`remedy`; không đường nào ghi `approved` cho bản v2 từ quyết định của v1; `en.ts`/`vi.ts` **cùng tập khoá** (856 khoá lá);
  ghi chú của chủ nhà sống qua cả hai quyết định. Năm lỗi tìm ra (BUG-83…BUG-87) đã sửa.
- **Vòng soát dọn** (`ef4517d`, 7 tệp, +85/−82, **không đổi hành vi**): gộp khuôn env ba mức thành `mode_from_env()`, `plan_critique()`
  đọc sổ con **một lần**, gộp câu "mất chủ" của hai route đánh thức thành `plan_wake_missing()`, bảng chip phản biện sống **một chỗ**
  (`PlanReviewCard.VERIFY_CHIP`), `usePlanFiles.clearReviewFacts()`, bỏ **6 khoá i18n chết**. Cố ý để nguyên: hai khối notice "mode
  unknown" (test ghim **mã đơn lẻ**, gộp là đổi số notice), hai bản regex host giữa `plan_quality.py` (thuần) và runtime, biểu thức nhãn
  `v{n}` ở hai component, và kiểu xuống dòng của các tệp mới.
- **Số đo sau hậu kiểm**: toàn bộ backend **1219 passed, 1 deselected in 377.87 s** (trước: 1210; chín ca mới); frontend **126 tệp /
  1113 ca đạt** (trước: 1086) + `tsc -b --noEmit` exit 0; `test_plan_routes` 22, `test_plan_approval_ledger` 13, `test_plan_quality` 15,
  `test_plan_sources_gate` 13, `test_plan_verify` 23.
- **Ba ca then chốt chứng minh ĐỎ TRƯỚC / XANH SAU** (hoàn nguyên từng bản vá rồi chạy lại, `/var/tmp/v25c/redcheck.py`): BUG-80,
  BUG-81, BUG-82 mỗi ca **1 failed** khi thiếu bản vá và xanh khi có. Đây là bằng chứng ca kiểm **thật sự** ghim hành vi, không chỉ
  chạy qua.
- **Vòng kiểm thử ĐỘC LẬP (subagent `testing-25`, harness riêng 3124/3125/3126, Vite 3142/3143/3144)**: bộ đối kháng mức mô-đun
  **90/90 đạt** (nhóm A–E) trên `ef4517d` **và** trên `9f2fb95`; bộ thứ hai **55/55** cho ba luật mới (F: verdict ở DÒNG CUỐI; G: cổng ở
  chỗ GHI + hằng số công tắc; H: chuẩn hoá theo tiền tố); bộ mức API trên ba harness sống **0 FAIL** (10 nhóm: `gates`, `missing-owner`,
  `status`, `last-turn`, `wrong-version`, `verified`, `changes`, `busy`, `verify-route`, `repeat`). Mặt giao diện đo bằng trình duyệt thật:
  **cùng một mặt `retry-model-calls@v4` (`revise`) khoá ở `enforce` (`disabled:true`, lý do `plan-not-reviewed`) và MỞ ở `warn`** — tab Plan
  đi đúng theo công tắc của harness; cửa sổ "đang đọc sổ" cũng khoá (lấy mẫu 120 ms suốt 2,3 s đầu); đổi bản xoá mặt + bản nháp của bản cũ
  (hàng sổ nhận `note: ""`); popup điều kiện đóng bằng `Escape`/bấm ngoài và **giữ** chữ đã gõ; nút *Run review session* hỏng nay hiện lỗi;
  câu `wake` của harness in **nguyên văn**; duyệt mặt `ok` mở **lượt thật** (`turn …#3`, `resumed 1`, event `[Tab Plan] …`). Ghi hình
  `/code/.generated_artifacts/recordings/v25r2_plan_states.webm`.
- **Vòng kiểm thử tìm thêm MỘT lỗ (H7) và nó đã được sửa**: cổng nguồn quét **cả payload** `tool_end` nên host do chính model đặt vào
  **tham số** được tính là "công cụ đã trả về" — trái docstring của hàm và trái câu từ chối của cổng. Bản vá `a93ebd6`: cổng chỉ đọc
  `result`, kèm ca `test_a_host_the_model_named_only_in_its_own_call_args_is_not_evidence` (**đỏ trước / xanh sau**). Hai điểm khác của
  vòng kiểm thử được **ghi nhận, không sửa** (có lý do): (i) khi `/plans/status` lỗi, mặt `unknown` vẫn **mở** nút Duyệt — cố ý, vì
  `planState.ts` cấm đọc `unknown` thành `none` (khoá oan); (ii) tab Plan tự chọn lại identity theo ý định `plan` cũ sau mỗi lần làm mới
  manifest (mã có sẵn từ trước, không thuộc vòng này) nên dải kết quả chỉ hiện ~5 s trước khi bị thay — nợ ghi lại.
- **Hai lỗi `probe` tìm ra mà vòng thi công không thấy** — đáng nhớ cho lần sau: (i) một cổng đặt ở chỗ **hỏi** mà không đặt ở chỗ
  **ghi** thì fail-open trên đường thứ hai (`ask_user`); (ii) `str.lstrip()` cắt theo **tập ký tự** nên hai chỗ "cùng một luật" vẫn nói
  hai chuyện khác nhau (`web.dev` vs `docs.example.com`) — muốn chắc thì gom một hàm dùng chung, đừng chép luật.
- **Chạy lại ca H7 trên cây chốt `a670e0e`** (chính vòng kiểm thử độc lập tự chạy lại, sau khi bản vá `a93ebd6` lên): harness `3124`
  được dựng lại **từ tip**, hai chiều đều đạt — host chỉ nằm trong `args` ⇒ `PLAN_QUALITY_REJECTED … (sources-unbacked)`, **0** hàng ghi;
  cùng host đó nằm trong `result` ⇒ `Plan written …`. Cả bộ thứ hai trên tip: **58/58** (F 12, G 27, H 19). Một điều kiện nói thẳng:
  `write_plan` không có cửa HTTP, nên hai chiều được đo **trong tiến trình** qua đúng `HarnessRuntime`/`SessionStore` nạp từ cây tip —
  không phải một lời gọi HTTP vào harness đang chạy.
- **Một ca kiểm dễ chập chờn đã được siết**: `blocked_session()` ở `test_plan_approval_ledger.py` chờ `awaiting_decision` đúng **5 s**;
  khi bộ kiểm chạy song song trên máy đang tải, lượt gieo có lần chưa kịp tới trạng thái đó nên ca đỏ rồi xanh khi chạy lại (thấy trong log
  của worker khác; vòng kiểm thử **không** tái hiện được). Trần nay là **30 s**; đường xanh vẫn thoát ở vòng lặp đầu nên không chậm thêm.

## Vòng 27 — đợt 1: lớp đọc nguồn sống lại (2026-09-23)

- Phạm vi: A-1 (giải nén `Content-Encoding`), A-2 (`reading.body_check`), A-3 (thang đọc dự phòng),
  A-5 (`file_read` có `offset`/`limit` trong box), A-9 (ba công tắc + khối `limits.web`),
  A-10 (bàn giao bảng: HTML/JATS/PDF). Đo trên host, model/khoá của phần sống ghi ở mục dưới.
- **Số đo trước/sau** (đều trên host qua `web_fetch`; "trước" = dump thô chưa giải nén): bài
  `nhandan.vn/…post900643` 17 421 ký tự rác (junk 0,550) → **cùng URL nay 9 103**, junk 0,0000, `ok`
  (số lấy từ đầu đọc: đường trực tiếp của bài này nay trả 404); `nhandan.vn/` (trang chủ) **18 832**,
  junk 0,0000; bài `baochinhphu.vn/…102250115105914411.htm` 46 692 (junk 0,517) → **8 079**,
  junk 0,0000, `readTier: html` (giải nén tại chỗ, **không** cần đầu đọc); `vanban.chinhphu.vn/`
  (trang chủ) **942 → 31 792**; `vietnamplus.vn/` 37 798 → **16 455**, junk 0,0000;
  `thuvienphapluat.vn` (403, thân bài rỗng) → xem "chỗ lệch kỳ vọng" dưới: **281** ký tự *trang chặn
  bot*, `error-page`; PDF arXiv `1706.03762v7` `%PDF-1.4…` + junk 0,517 → **46 128** ký tự,
  `pdf-table` (**10** bảng, 15 trang), **không** còn nhị phân thô; HTML arXiv **9 bảng** có nhãn
  (HTML có 10 thẻ `<table>`); `vbpl.vn/…ItemID=1` → `verdict: wrong-page`; `moh.gov.vn`
  (165–259 byte) → ném timeout, không ra `ok`.
- **Bộ đơn vị mới** `backend/tests/unit/test_web_reading.py`: 34 ca, không ca nào cần mạng
  (thay `urllib.request.build_opener`), phủ: gzip/có tiêu đề giả/deflate hai biến thể/brotli là
  lỗi tường minh/bom nén bị chặn/`IncompleteRead` giữ `partial`/công tắc `WEB_DECODE=off` trả lại
  đúng rác cũ/junk ratio/thin–error-page–wrong-page/thang đọc/đầu đọc chỉ được nhận khi **tốt hơn**
  và **không** lách SSRF/`WEB_READER=thin` = đúng hành vi `2add905`/bảng HTML + JATS + tầng PDF
  (PDF viết tay trong test, không cần tệp ngoài).
- **Lệnh và kết quả**: `./.venv/bin/python -m pytest backend/tests/unit/test_web_reading.py
  backend/tests/unit/test_web_tools.py -q -p no:randomly` ⇒ **67 passed**; `test_runtime_info.py`
  ⇒ **12 passed** (khối `limits.web` được ghim bằng so khớp từ điển chính xác, cộng một ca mới:
  giá trị lạ `chặt-vừa-thôi` ⇒ mức mặc định **kèm đúng một** notice `WEB_READER_MODE_UNKNOWN`).
- **A-5 (box)**: `./.venv/bin/python -m pytest backend/tests/unit/test_worker_file_read.py
  backend/tests/unit/test_file_tools.py -q -p no:randomly` ⇒ **15 passed**; tệp 100 000 ký tự đọc
  bằng 4 lời gọi ghép lại **bằng đúng** bản gốc; `offset` âm/`'abc'`/`None` kẹp về 0; nhánh base64
  căn offset xuống bội 3 và nói ra bằng `offsetAlignedTo: 3`.
- **Hai ca đỏ cũ nay xanh theo đúng thiết kế**: lỗi gốc được **giữ nguyên** khi đầu đọc không cứu
  được (`HTTP 404` vẫn là `HTTP 404`, không đổi thành `WEB_FETCH_EMPTY`) — đúng câu A-3 "đầu đọc
  timeout ⇒ lỗi gốc được giữ".
- Ghi chú kỹ thuật: `pdfplumber 0.11.10` + `pypdfium2 5.13.0` nay là phụ thuộc host
  (`backend/requirements.txt`); PDF **không** dựng được ⇒ trả `''` + `pdfNote` nói rõ, **không**
  trả nhị phân thô. Ba trang gzip đo lại sau khi sửa đều ra chữ Việt có dấu, không còn mảnh
  replacement.
- Giao thức test model + khoá: `docs/plan/v27/research-quality-tests.md` §2. Bộ ca chất lượng
  research (`RQ1–RQ8` + sáu tiêu chí + oracle): cùng tài liệu, §3.
- **Chốt đợt 1 — đo lại toàn bộ bằng `scripts/probe-reading.py` (2026-09-23, lần 6): 11/11 đạt ngưỡng.**
  Mỗi dòng là một lời gọi `web_fetch` thật trên host; cột "ký tự" là `textChars` = độ dài văn bản
  bóc được **trước** khi cắt trần (`maxChars: 20000` của lượt đo — bốn dòng vượt trần nên model chỉ
  nhận 20 000 ký tự đầu):

  | Nguồn | giây | ký tự | junk | verdict | `readTier` | reader |
  |---|---|---|---|---|---|---|
  | `nhandan.vn` | 1,30 | 18 832 | 0,0 | `ok` | `html` | — |
  | `vanban.chinhphu.vn` (trang chủ) | 1,38 | 31 792 | 0,0 | `ok` | `html` | — |
  | `vietnamplus.vn` | 1,19 | 16 455 | 0,0 | `ok` | `html` | — |
  | `thuvienphapluat.vn/…Luat-Doanh-nghiep-2020…` | 11,66 | 281 | 0,0 | `error-page` | `reader-text` | `r.jina.ai` |
  | `vbpl.vn/…vbpq-toanvan.aspx?ItemID=1` | 1,71 | 87 | 0,0 | `wrong-page` | `html` | — |
  | `moh.gov.vn` | 15,44 | — | — | lỗi `WEB_FETCH_FAILED` (timeout) | — | — |
  | `arxiv.org/pdf/1706.03762v7` | 2,53 | 46 128 | 0,0 | `ok` | `pdf-table` (**10** bảng, 15 trang) | — |
  | `arxiv.org/html/1706.03762v7` | 0,08 | 45 814 | 0,0 | `ok` | `html` (**9** bảng có nhãn; HTML có 10 thẻ `<table>`) | — |
  | Europe PMC `PMC7090843/fullTextXML` | 1,03 | 136 836 | 0,0 | `ok` | `jats` (**5** bảng) | — |
  | `web_search` (firecrawl) | 0,13 | 5 kết quả | — | — | — | — |
  | `web_search` (wikipedia) | 0,26 | 5 kết quả | — | — | — | — |

- **Đo lại lần 7 trên cây sau ba lượt soát: 11/11 đạt ngưỡng — đo được 11/11 dòng, 0 dòng lỗi**
  (`probe_reading_7.json`). Chênh so với lần 6: `vietnamplus.vn` 16 606 (lần 6: 16 455);
  `vbpq-toanvan.aspx?ItemID=1` nay **`error-page`** thay vì `wrong-page` — dấu hiệu `'đang tải dữ
  liệu'` đã sống (mục "soát mã" 2), tức trang được bắt bằng dấu hiệu tường minh chứ không bằng tiêu đề;
  `thuvienphapluat.vn` 306 ký tự / 3,03 s (đầu đọc trả lời nhanh hơn, vẫn `error-page`);
  `moh.gov.vn` 21 ký tự qua đầu đọc ⇒ **`thin`** (lần 6 ném timeout) — vẫn **không** ra `ok`, nhưng
  đây là dạng "thân bài 21 ký tự" mà trần thời gian + chính sách lượt của đợt 5 (D-40) phải xử lý;
  PDF arXiv 2,33 s với **0** lời gọi đầu đọc (tầng 3 trước tầng 4 — mục "soát mã" 4).
- **Lưu ý về cách đếm của thước đo (bản sửa sau lượt soát mã):** một dòng NÉM LỖI bị tính là **hỏng** và
  lượt chạy thoát mã 1. Con số "11/11" ở trên là **đo được tại thời điểm đo**, không phải một bất biến:
  nếu lượt sau `moh.gov.vn` lại timeout thì thước đo in `10/11 … 1 dòng lỗi tính là hỏng` và thoát mã 1 —
  đó là **đo đúng**, không phải hồi quy. Trước bản sửa, chính một lượt cắt hết đường ra vẫn in `9/11`.
- **Bốn sửa đổi mà chính thước đo bắt được** (không nằm trong chữ của plan, đều có số đo trước/sau):
  1. **`<form>` không còn bị bỏ nội dung.** Trang ASP.NET `vanban.chinhphu.vn/?pageid=27160&docid=207396`
     bọc **toàn bộ thân bài** trong `<form id="form1">`, nên `_TextExtractor` bỏ hết: 81 697 byte HTML
     ⇒ `html_to_text` trả **2 ký tự**; sau bản sửa ⇒ **5 053**. Trang chủ cùng host: **942 → 31 792**
     (đúng cỡ 32 173 ký tự của lần đo đầu). `nav/footer/aside/svg/script/style` vẫn bị bỏ.
  2. **Tên miền không phải slug.** Phép cắt chuỗi cũ lấy cả host khi đường dẫn chỉ là `/`, nên
     `https://vanban.chinhphu.vn/` sinh token `['vanban', 'chinhphu']` rồi so với tiêu đề
     "Hệ thống văn bản" ⇒ **mọi** trang của host đó ra `wrong-page` (báo sai). Nay chỉ lấy phần `path`;
     ca đã đo của `vbpl.vn` (`vbpq-toanvan.aspx?ItemID=1` ⇒ `['vbpq','toanvan']`) vẫn **bị bắt** — nhưng
     từ lượt đo 7 nó ra `error-page` bằng dấu hiệu tường minh `'đang tải dữ liệu'`, không còn bằng phép so
     slug (mục "soát mã" 1), nên phép so slug nay là lưới thứ hai chứ không phải chốt duy nhất.
  3. **Đầu đọc không được "rửa" trang sai thành `ok`.** Cửa hậu `reading.slug_clue` chỉ nhìn **tiêu đề**
     (`Title:` hoặc dòng `#`): đo được `r.jina.ai` trả 26 522 ký tự *site chrome* cho
     `vbpq-toanvan.aspx?ItemID=1` và không có dòng `Title:` nào. Lần chạy đầu cửa hậu vẫn lọt vì bản
     chrome có chứa chính chuỗi URL đó trong liên kết ⇒ phép kiểm phải bỏ qua thân bài.
  4. **Trang chặn bot là `error-page`, không phải `thin`.** Thêm dấu hiệu `'performing security verification'`
     (`ERROR_MARKERS`) sau khi đo `thuvienphapluat.vn`; cùng lượt này hai sửa trước đó được xác nhận:
     trần PDF riêng `MAX_PDF_BYTES = 8 MiB` (tải lại **đúng một lần**) và tầng JATS nhận **theo dấu hiệu
     `table-wrap` trong thân bài** (Europe PMC trả `text/plain`, không phải `application/xml`).
- **Nghiệm thu độc lập (`v27e1-testing`, 2026-09-23) — `OVERALL STATUS: PASSED` trên `2bfedd7`:** kiểm lại
  bộ đơn vị **1272 passed, 1 deselected trong 217,41 s**; ca bị deselect đỏ y hệt trên cả ba SHA (chỉ Windows).
  Ma trận công tắc (`auto`/`thin`/`off`/`decode=off`/`read-store=off`) đúng; đọc qua box (`docker exec`) nối
  lại đúng **100 000 ký tự** với `offsetAlignedTo: 3`, **bốn** biến thể traversal bị từ chối và không rò; oracle
  CLI thoát đúng 0/1/2. Bằng chứng: `/code/.generated_artifacts/v27e1/*` (`probe-2bfedd7.json`,
  `switch-matrix.log`, `box_read_probe.json`, `unit-2bfedd7.log`, `oracle-out-rq1-pass.json`, …).
- **Hai lỗi THẬT do lượt nghiệm thu tìm ra, sửa trong bản sửa SAU nghiệm thu (commit `8b0868b`, ngay sau
  `2bfedd7` trên cùng nhánh — phép chấp nhận đứng ở `2bfedd7`; `8b0868b` chỉ sửa đúng hai nhánh ấy, sửa một
  mục `[Low]`, thêm ba ca ghim và ba dòng tài liệu):**
  1. `BOXFOX_WEB_DECODE=off` **nói dối trong payload**: `meta` được dựng TRƯỚC khi đọc header, nên một thân
     bài gzip bị báo `contentEncoding: "identity"`. Nay đọc header/magic TRƯỚC; tắt giải nén vẫn báo
     `gzip` + `decoded: False` — ca ghim trong `test_the_decode_switch_restores_the_old_behaviour`.
  2. `BOXFOX_WEB_READER=thin` **không tái hiện `2add905`**: nhánh `thin` kiểm trước `direct_error` nên một
     trang 403 vẫn tốn thêm một chuyến `r.jina.ai`. Nay nhánh `thin` gặp `direct_error` trả
     `{'use_reader': False, 'reason': 'none'}` — ca mới `test_the_thin_switch_keeps_the_original_error_instead_of_a_reader_hop`.
  3. Mục `[Low]` thứ ba sửa luôn: thân bài của **trang lỗi** cũng có thể nén, và `decode(errors='replace')`
     trên byte gzip in mojibake vào chính câu báo lỗi. Nay giải nén trước — ca mới
     `test_an_http_error_body_is_inflated_before_it_reaches_the_message`.
  Sau ba sửa đổi và ba ca ghim (`8b0868b`): **1274 passed, 1 deselected trong 214,85 s**; `test_web_reading.py`
  một mình **36 ca**; nhóm web (`test_web_reading.py` + `test_web_tools.py`) ⇒ **69 passed**.
- **Chỗ lệch kỳ vọng của plan thì nói thẳng, không làm tròn:**
  - `thuvienphapluat.vn`: A-3 kỳ vọng đầu đọc cứu được **≥ 20 000 ký tự**. Đo lại cùng ngày, muộn hơn:
    `r.jina.ai` **không khoá** nhận đúng *trang chặn bot* 281 ký tự ⇒ ngưỡng ấy không còn đứng được, và
    đó là thay đổi của dịch vụ bên ngoài chứ không phải của mã. Bất biến giữ được: **không bao giờ `ok`**
    (`error-page`, `readerReason: unreachable`). Muốn đọc được trang này phải có khoá hoặc chân đọc khác
    — việc của A-7 (đợt 2).
  - `moh.gov.vn`: Ở lượt 5–6 trang này ném `WEB_FETCH_FAILED` sau 15,44 s (bảng lần 6 ở trên ghi đúng
    trạng thái **của lượt 6**). Lượt 7 nó KHÔNG ném lỗi nữa mà qua đầu đọc trả **21 ký tự** ⇒ `thin`
    (không bao giờ `ok`) — nên hai dòng không mâu thuẫn, chúng là hai lượt khác nhau. Chính sách trần thời
    gian của lượt thuộc đợt 5 (D-40), không sửa ở đây.
  - Europe PMC: bài `PMC3258128` dùng ở lần chạy trước **không có** `<table-wrap>` nào nên nhánh JATS
    không chạy và tầng ra `html` — lỗi ở **mẫu đo**, không ở mã. Mẫu nay là `PMC7090843` (10 thẻ, 5 khối ngoài).
- **Bộ đơn vị đầy đủ trên cây này**: `./.venv/bin/python -m pytest backend/tests/unit -q -p no:randomly
  --deselect backend/tests/unit/test_terminal_tools.py::test_terminal_exec_echo` ⇒ **1274 passed, 1 deselected**
  trong 214,85 s (mốc trước đợt 1: 1219) (mốc trước bốn sửa đổi: 1247 passed; tại `2bfedd7`: 1272 passed / 217,83 s,
  lượt nghiệm thu độc lập đo lại 217,41 s). `test_web_reading.py` một mình **36 ca**;
  `test_web_reading.py` + `test_web_tools.py` ⇒ **69 passed**; `test_runtime_info.py` ⇒ **12 passed**.
  Ca deselected là `Write-Output` PowerShell trên Linux — đỏ có sẵn từ trước, đỏ y hệt trên `git archive HEAD` sạch.
- **Lượt sống với model (giao thức và khoá: `docs/plan/v27/research-quality-tests.md` §2)**:
  (i) job `b89d2e4b` — 3 lời gọi `web_fetch` (`nhandan.vn`, `vanban.chinhphu.vn`, PDF arXiv), **0 lỗi**,
  model trả lời đúng cả ba con số, không bịa; (ii) job `d01e9ed8` (chỉ PDF, sau khi vá trần):
  `readTier: pdf-table`, `tables: 10`, `pdfPages: 15`, 46 128 ký tự, junk 0,0, 0 lỗi.
  Cả hai lượt đều `truncated: true` (18 832 / 32 173 / 40 563 ký tự ở lượt (i); 46 128 ở lượt (ii))
  ⇒ phần bảng nằm ở đuôi **bị cắt** — đúng lý do tồn tại của A-4 (bộ đệm đọc + `read_source`) ở đợt 2.
- **Soát mã đợt 1 (ba lượt song song: dọn mã · lõi `reading.py`/`web.py` · kiểm thử – tài liệu – thước
  đo) tìm thêm sáu chỗ; cả sáu đã sửa ngay trong đợt:**
  1. **Thước đo đếm "không đo được" thành "đạt ngưỡng".** Nhánh `WebError` của `measure_fetch`
     (`scripts/probe-reading.py`) trả về sớm mà không đặt `problems`, nên một đích **không trả lời**
     vẫn được tính là qua. Chứng minh bằng lượt chạy **cắt hết đường ra**
     (`https_proxy=http://127.0.0.1:9`, `http_proxy=…`): trước khi sửa in **9/11 đạt ngưỡng**; sau khi
     sửa in **0/11 đạt ngưỡng — đo được 0/11 dòng, 11 dòng lỗi tính là hỏng** và thoát mã **1**.
  2. **Hai dấu hiệu lỗi tiếng Việt là chuỗi chết** (`ERROR_MARKERS` được so trên bản **bỏ dấu**):
     thân bài 404 của `vbpl.vn` chỉ bị bắt nhờ mục `'404 error'`. Nay mỗi mục có cả hai cách viết, và
     bảng tiêu đề chung (`GENERIC_TITLES`) sửa cùng lỗi.
  3. **Slug percent-encode bị giải mã sai ⇒ trang THẬT ra `wrong-page`**, kèm **kênh `Title:` của đầu
     đọc bị xoá** nên cửa hậu `slug_clue` bất động. Đo lại sống trên `vi.wikipedia.org`: bản cũ token
     `['a3o','83m']` ⇒ `wrong_page=True`; bản nay `['bao','hiem']` ⇒ `False`; cả ba URL đo lại đều
     `ok`. Nay slug được `unquote`, dòng `Title:` được giữ, và tiêu đề của bản đầu đọc đi trước khi
     bản đó được nhận vào payload.
  4. **PDF dựng lại được vẫn đi qua đầu đọc** (tầng 3 phải đứng TRƯỚC tầng 4). Đo lại sống
     `arxiv.org/pdf/1706.03762v7`: **hai** lời gọi (bản cắt ở trần 2 MiB + lần tải lại theo trần PDF
     8 MiB), **0 lời gọi đầu đọc**, `pdf-table`, **10 bảng**, 15 trang, 46 128 ký tự, 2,36 s.
  5. **Bộ đơn vị sửa `os.environ` trực tiếp** (tự `pop` `BOXFOX_WEB_READER`) ⇒ lượt chạy hồi quy ghim
     `thin` cho cả tiến trình bị hạ về mặc định ở các tệp chạy sau; nay dùng `monkeypatch`. Cùng lượt:
     ghim thêm **`verdict: empty`** + **thứ hạng thang đọc**, và bỏ câu ghim tên lớp lỗi của thư viện
     (`'PdfminerException'` — `requirements.txt` cho phép `pdfplumber>=0.11,<1`).
  6. **Năm con số trong tài liệu không tái lập được** (xem "Số đo trước/sau" ở trên: số "trước" là của
     **bài báo**, số "sau" là của **trang chủ** — hai URL khác nhau). Đã đo lại **cùng URL** và sửa cả
     `docs/research/host-web-tools.md` lẫn tệp này.
- **Ba lượt sống với model `muse-spark-1.3-contributor-free`** (mỗi lượt một khoá, cùng cây mã, cùng
  bộ ca `backend/tests/integration/test_peer_mesh_chain.py -k song`, harness scratch cổng 3188):

| Khoá | Giờ (UTC) | Kết quả | Phiên | Con | Biên nhận | Chờ | Lỗi |
|---|---|---|---|---|---|---|---|
| 1 `f8a5f4e8…` | 22:06 | **`1 passed, 2 deselected`** 26,41 s | `8b2c6d0888cb4630b357d4fe6b59849a` | 2 (`childSteps` 3, `childTokens` 1011) | 2/2 `injected` | 8 886 ms | không |
| 2 `a43ff124…` | 22:03 | **`1 passed, 2 deselected`** 26,42 s | `75a8d0fd169b46ed8c7dc6e054b69819` | 2 (`childSteps` 3, `childTokens` 836) | 2/2 `injected` | 0 ms | không |
| 3 `3d27b0b0…` | 22:05 | **`1 passed, 2 deselected`** 16,39 s | `e35a0f62e81c40d991c61c7841906ec5` | 2 (`childSteps` 4, `childTokens` 932) | 2/2 `injected` | 7 987 ms | không |

  Cả ba khoá **không** có 429/403/400/500; hai con của mỗi lượt (`testing`, `review`) đều `completed`.
- **Oracle chất lượng research nay đã có** (đợt 8, phần đầu): `scripts/eval/research_checks.py` — sáu
  tiêu chí 0/1/2, ngưỡng **9/12**, **cảnh báo chứ không chặn** — cộng bộ ca của chính nó
  `backend/tests/unit/test_research_checks.py` (**13 ca**, không cần mạng) ⇒ **13 passed**. Bốn đầu vào:
  `--sources` (sổ nguồn JSONL), `--transcript` (nhật ký: nhận cả dòng `tool_end` của bảng `events` lẫn
  dòng trần), `--answer`, `--rq`. Chạy **sống** `RQ1–RQ8` còn chờ đợt 3 (chưa có `sources.jsonl` thật)
  — ghi ở `docs/plan/v27/research-quality-tests.md` §5.

## Vòng 27 — đợt 2: bộ đệm đọc, tham chiếu học thuật, tìm kiếm gộp nhiều chân (2026-09-23, tối)

- Phạm vi: A-4 (`ReadStore` + `read_source`), A-6 (`paper_citations` + chuỗi học thuật bốn chân +
  `_retry`), A-7 (`web_search` nhiều truy vấn, khử trùng, `site`/`freshness`/`lang`/`exclude`, cache,
  kể tên khoá thiếu). Cây mã: cùng nhánh `vorflux/v27-research-rework`, tiếp sau `8b0868b`.
- **A-4 — ĐO ĐƯỢC (thước đo lần 8, `--only store`)**: `docs.python.org/3/whatsnew/3.13.html` ⇒
  `stored=113936`, ghép **15 mẩu** ra `joined=113936` (**khớp từng ký tự**), `find='asyncio'` ⇒ **1**
  vị trí khớp, **0,14 s**. Cùng trang, trước đợt 2 model chỉ thấy **8 000** ký tự (7 %). Trần **một
  lời gọi** vẫn 8 000 / 20 000 ký tự: cái đổi là **số lượt gọi**, không phải kích thước mỗi lượt.
- **Thước đo nay chạy CẢ nhóm `store` trong lượt đầy đủ.** Trước đó `wanted = args.only or
  list(GROUPS)` mà `GROUPS` không có `'store'` ⇒ nhóm ấy **chưa bao giờ** được đo trong lượt đầy đủ
  (“12/12 đạt ngưỡng” vẫn thiếu một nhóm). Đã sửa thành `[*GROUPS, 'store']`.
- **A-7 — ĐO ĐƯỢC (keyless, hai truy vấn, `count=5`)**: `hồ sơ chuyển tuyến bảo hiểm y tế` +
  `site:chinhphu.vn hồ sơ chuyển tuyến` ⇒ **10 kết quả**, `perQuery [5, 5]`, `deduped 0`,
  `duplicateUrls 0`, `distinctNormalizedUrls 10`, `providers ['firecrawl']`, **0,85 s** (ngưỡng plan:
  ≥ 6 kết quả, 0 URL trùng). Lượt lặp lại: **0,0009 s**, `cached: true`, `fetchedAt` y hệt (lượt đầu
  0,42 s). Bằng chứng: `/var/tmp/v27/a7_live.json`, `/var/tmp/v27/a7_cache_live.py`.
- **Chân keyless bị GIỚI HẠN NHỊP — nói thẳng**: đo lại muộn hơn cùng ngày (23:19 UTC), Firecrawl
  không khoá **từ chối bằng 429** hai lượt liên tiếp; `perQuery` ghi rõ truy vấn nào hỏng và thông
  điệp cuối **kể tên khoá thiếu**. Vì thế ngưỡng **cứng** của thước đo lần 8 là hình dạng mã (2 truy
  vấn chạy, 0 URL trùng, lượt lặp ăn cache); con số “≥ 6 kết quả” được ghi là **số đo có ngày**, không
  thành ngưỡng cứng — nếu lấy 6 làm ngưỡng cứng thì một thay đổi của dịch vụ miễn phí sẽ bị báo thành
  “hồi quy” của mã. Lượt ấy in `11/12 đạt ngưỡng` và thoát mã **1**.
- **Một lỗi THẬT do ca đơn vị bắt ngay khi viết**: `PAPER_CITATIONS_RESOLVE_MAX` được **dùng** ở nhánh
  `backward` (`web.py:1332`) nhưng **thiếu trong danh sách import** ⇒ mọi lời gọi `backward` có tham
  chiếu ném `NameError`. Không lượt sống nào chạm nhánh ấy (thước đo chỉ chạy `forward`), nên chỉ ca
  đơn vị mới thấy — đúng lý do tồn tại của `test_web_papers.py`. Đã sửa (import) và ghim cả hai chiều.
- **Bộ đơn vị mới**: `backend/tests/unit/test_web_read_store.py` (**20 ca**, A-4),
  `backend/tests/unit/test_web_search_multi.py` (**22 ca**, A-7 — gồm ca mới: một chân bị từ chối
  **không** được im lặng khi chân khác còn kết quả), `backend/tests/unit/test_web_papers.py`
  (**20 ca**, A-6 — hai chiều, trần, tham số hỏng, `_retry` + `Retry-After`, chuỗi bốn chân, arXiv).
  Nhóm web: `test_web_read_store.py` + `test_web_search_multi.py` + `test_web_papers.py` +
  `test_web_tools.py` + `test_web_reading.py` ⇒ **131 passed in 1,84 s**; `test_web_search_multi.py`
  một mình ⇒ **22 passed in 0,08 s**; `test_web_read_store.py` ⇒ **20 passed in 0,15 s**.
- **Ba chỗ ghim số công cụ** lên **27** (`test_journal_tools.py:63`, `test_runtime_info.py:154`,
  `:166`): `read_source` + `paper_citations` vào `ORCHESTRATOR_TOOLS` và nhóm `webResearch`.
- **Bộ đơn vị đầy đủ** (cùng lệnh, từ gốc repo): trên cây đợt 2 **trước** tệp `test_web_papers.py` +
  một ca mới + bản sửa import ⇒ **1315 passed, 1 deselected in 219,30 s** (`/var/tmp/v27/unit_run_6.log`);
  trên cây **chốt đợt 2** ⇒ **1336 passed, 1 deselected in 215,02 s** (`/var/tmp/v27/unit_run_7.log`). Mốc đợt 1: **1274 passed**.
- **Tài liệu sửa cùng lượt** (ba tệp): `docs/research/host-web-tools.md` §2 (ba chân học thuật +
  Exa/Parallel), §3 (trần dữ liệu: ≤ 3 truy vấn, không phân trang; bộ đệm tìm kiếm 300 s; nhật ký
  thêm `web.retry`), §4.4 (**sửa lời nói SAI** “bộ đệm đọc chưa có trong cây này” — nay đã có kèm số
  đo), §4.8 (A-4 + A-6, gồm cả lỗi import ở trên), §4.9 (A-7, gồm số đo sống và cảnh báo giới hạn
  nhịp của chân keyless); `docs/architecture/tools-and-skills.md` (Nhóm 6: `web_extract`/`max_results`
  đã cũ ⇒ `web_fetch` + `read_source` + `paper_citations`, `web_search` nay có `queries`/`site`/
  `freshness`/`lang`/`exclude`); tệp này.
- **Hậu kiểm sau thi công (cùng ngày)**: một lượt soát dọn (`v27e2-simplify`) + một lượt soát mã
  (`v27e2-review`, điểm rủi ro **3/10 — Low**, verdict *ship with mitigations*) trên đúng `8d1c676`.
  Ba việc đã làm ở bản sửa SAU soát (`dc5306e`): (a) xoá lớp dò chữ ký `_call_provider` — bảy chân
  không dùng bộ lọc nay cùng nhận `options: dict | None = None`, nên một `TypeError` thật bên trong
  chân không còn bị nuốt; (b) **một lời gọi tìm kiếm = MỘT dòng `web.search`** (nhánh cache từng tự
  ghi thêm một dòng thiếu `session_id`/`durationMs`) — có ca ghim mới; (c) **ngân sách ký tự cho
  payload tìm kiếm** (`SEARCH_PAYLOAD_CHARS = 18 000`, cắt ở đuôi, nói ra bằng `dropped`): 3 chân ×
  10 hàng × đoạn trích 400 ký tự = ~27 000 ký tự, vượt trần 24 000 của runtime nên JSON từng bị cắt
  GIỮA CHỪNG. Kèm sửa tài liệu: `read_source` trả `matches: {term, offset}[]` (không phải `hits`),
  hai chỗ còn ghi Nhóm 6 "4 tools", thông điệp ghim số công cụ trong test nói "26" trong khi khẳng
  định 27. Thêm một ca ghim **biên** của luật gần trùng (cặp vừa qua ngưỡng vẫn gộp, URL bị gộp nằm
  trong `alsoFrom` nên không mất dấu vết).
- **Hai phát hiện ngoài phạm vi đợt này** (đã `surface`, ghi ở mục `Out-of-Scope Feedback` của PR #6):
  `read_source`/`paper_citations` chưa nằm trong `READ_TOOLS` của `evidence_gate.py` nên mỗi lượt
  research tốn thêm một phép dò box + một tệp bằng chứng; và `compression.TOOL_RESULT_SUMMARIES`
  chưa có mục cho hai công cụ ấy. Cả hai bị kế hoạch cấm chạm ở đợt 1–2.
- **Bộ đơn vị sau hậu kiểm**: **1339 passed, 1 deselected** trong 215,98 s (`/var/tmp/v27/unit_run_9.log`);
  bản trước hậu kiểm (`8d1c676`): **1336 passed** trong 215,02 s; bản chỉ có soát dọn: 1337 passed.
- **Bất biến giữ nguyên**: D-13/F7 (các chân chạy **tuần tự** trong một lời gọi, không công cụ song
  song trong một step); nhật ký DEV **không** chứa truy vấn/URL (`web.retry` chỉ `attempt` + `code`);
  `untrusted: true` + `note` vẫn có trong mọi payload; SSRF vẫn **ném** lỗi chứ không lùi về đầu đọc;
  `exclude` **không** bật mặc định (#5991); Exa/Parallel chỉ chạy khi có khoá (#5978/#6020/#6023).

### Vòng 27 — đợt 2, bản sửa SAU lượt nghiệm thu độc lập (2026-09-23/24)

- **Lỗi THẬT thứ hai của đợt 2 (BUG A), do lượt nghiệm thu độc lập bắt được:**
  `paper_citations(doi=…, direction="forward")` trả **HTTP 400**. OpenAlex nói đúng câu:
  `'doi:10.7717/peerj.4375' is not a valid OpenAlex ID.` Nguyên nhân: nhánh `forward` nhét thẳng mã
  định danh vào `filter=cites:…`, mà `filter` **chỉ nhận mã `W…`**; nhánh `backward` không dính vì DOI
  đi trong **đường dẫn** (`works/doi:…` ⇒ 200). Ca đơn vị cũ **ghim sai hành vi** và bình luận còn
  khẳng định sai rằng OpenAlex nhận `doi:…` trong `filter`.
- **Cách vá:** `_openalex_citable_id(ident)` — mã `W…` đi thẳng; mã khác được giải bằng **một** lời gọi
  42 byte (`select=id`) rồi lấy mã cuối; không giải được thì **báo lỗi**, không đoán. Nhánh `forward`
  trả `work` là mã đã giải. Ca ghim mới (3 ca thay ca ghim cũ + 1 ca cho nhánh không giải được).
  ĐO LẠI SAU KHI VÁ: `doi_only forward` ⇒ 200, `work W2741809807`, `total 1255`, 0,25 s.
- **Số byte phụ thuộc bộ `select`:** hôm sau đo lại cùng URL với `per-page=2` là **4 895 byte** (không
  phải 891) ⇒ đọc các số 891 / 33 226 / 2 967 là "nhỏ hơn một bậc", **không** phải hằng số.
- **Sửa lại một số đã ghi sai:** thông điệp commit `dc5306e` ghi "nhóm web: 133 passed", đúng là **134**
  ở `f12de93`; lượt nghiệm thu đo **139 passed** trên cây có bản sửa (5 tệp nhóm web).
- **Giới hạn còn lại, nói thẳng:** ngân sách payload giữ hàng **đầu** vô điều kiện, nên MỘT URL khổng
  lồ (đo được một hàng 31 298 ký tự) vẫn có thể đẩy payload qua trần runtime 24 000. Trần cho một hàng
  chưa có luật riêng — việc của đợt sau.
- **Cây đóng băng của lượt nghiệm thu là `f12de93`; hai SHA:** `f12de93` là bản lượt kiểm chạy trên đó
  (một ca A-6 đỏ), còn **`0015d35`** là bản sửa sau nghiệm thu đã commit — theo luật
  `/memory/knowledge/vorflux/when-you-edit-the-tree-after-dispatching-testing-agents.md`.
- **Bộ đơn vị trên cây có bản sửa**: **1344 passed, 1 deselected in 216,63 s**
  (`/var/tmp/v27/unit_run_10.log`); `f12de93` (chưa có bản sửa): **1339 passed, 1 deselected**.
- **Ghi chú cho đúng sổ (lượt xác nhận cuối bắt được):** ba sửa một-dòng ở `web.py` (bình luận `perQuery`
  và bình luận `TypeError`/chữ ký hai tham số, ghi chú `select` trong docstring `paper_citations`) **đã
  không** vào `0015d35` — lệnh vá dừng ở mẫu không khớp nên chỉ hai sửa tài liệu `host-web-tools.md` được
  ghi. Nay đã áp lại ở **`e60ec0e`** (sau `fd76b53`); cả ba là bình luận/docstring, **không** đổi hành
  vi (nhóm web 5 tệp: **139 passed** trước và sau).
- **Lượt xác nhận cuối trên cây đã commit (`fd76b53`): `OVERALL STATUS: PASSED`.** Đúng ca A-6 từng đỏ
  nay xanh sống: `doi` + `forward` ⇒ 200, `work W2741809807`, `total 1255`, `count 3`; câu hỏi gửi đi là
  `works/doi:…?select=id` rồi `works?filter=cites:W2741809807&select=PAPER_SELECT` — **không** có DOI
  thô nào trong `filter`. Mã không giải được ⇒ ném lỗi ngay ở bước giải (`HTTP 404`), không dựng bộ lọc
  từ mã xấu. Lượt ấy cũng dựng bản sạch bằng `git archive` và so **blob hash** với repo (khớp cả bốn tệp),
  nên số đo thuộc về mã đã commit chứ không phải cây làm việc dở.

## Vòng 27 — đợt 3 đến 8: sổ nguồn, hồ sơ `.research/`, bốn pha, ba mức, phản biện, nhịp tiến độ, steer, bộ ca R1–R12 (2026-09-24, rạng sáng)

Ba commit: **`d0edca1`** (mã đợt 3–7 + test + giao diện + `deploy/`), **`a624933`** (đợt 8: bộ eval,
12 fixture, runner ghi số), **`9abd191`** (tài liệu). Nền: **`a959c51`**.

### Đợt 3 — sổ nguồn và thang nguồn (B-1, B-2)

- Tệp mới `source_tiers.py`: năm tầng (0 chủ nhà cấp … 4 chưa kiểm), 13 host chính chủ, 11 báo chính
  thống, 12 host tầng 4, 13 kênh xã hội chính chủ. Tiền tố `docs.` / `developer.` / `developers.` nay
  khớp thật qua `_prefix_in` (BUG-107: bốn mục ấy **không bao giờ** khớp trước bản sửa).
- Tệp mới `research_ledger.py`: luật thuần cho sổ — `MIN_EXCERPT_CHARS = 80`, dấu vân tay shingle 5 từ,
  `JACCARD_MERGE = 0.85`, `MAX_LEDGER_ROWS = 400`; `assess_rows` sinh **bảy nhóm lỗi**.
- ĐO SỐNG thang nguồn: `moh.gov.vn` ⇒ tầng **1** `nguồn chính chủ / chính thống`; `vnexpress.net` /
  `baochinhphu.vn` / `thanhnien.vn` / `tuoitre.vn` ⇒ tầng **2**; `dantri.com.vn` / `vietnamnet.vn` ⇒
  tầng **3** (lý do `default-unknown`).
- ĐO SỐNG `assess_rows`: hai host **khác tầng** cùng đoạn trích ⇒ chỉ `research-origin-undeclared`
  (không có `research-claim-single-source`); hai host **cùng tầng 3** + khai gốc ⇒ chỉ
  `research-claim-single-source`; hai host cùng tầng 3 nhưng **đoạn trích khác** ⇒ **0 lỗi**.
- Ba công cụ `source_add` / `source_list` / `source_verify`; `source_add` idempotent theo (URL chuẩn
  hoá, đoạn trích) và ghi vào sổ của phiên **giữ brief** kèm mã nhánh (BUG-91, BUG-92, BUG-93).
- Test: `test_source_tiers.py` **11**, `test_research_ledger.py` **12**, `test_source_add_tool.py` **6**,
  `test_source_ledger_store.py` **6**, `test_research_header.py` **5**, `test_research_verify_source.py`
  **7** — không ca nào cần mạng.

### Đợt 4 — ba nhóm hồ sơ, cổng chất lượng, đường ghi (B-3a/B-3b/C-2)

- `research_profiles.py`: chín hồ sơ, sáu nhóm việc, mười use-case TM-1…TM-10, bốn archetype C1–C4;
  `test_research_profiles.py` **7**.
- `research_quality.py`: **15 mã lỗi**, cổng `enforce|warn|off` (mặc định `enforce`), cổng đọc hồ sơ
  theo mức (`critique_required(level)` đọc chính `DOSSIER_SECTIONS` — BUG-106).
- Đường ghi: op `dossier_write` trong box (`worker.py`) + công cụ `dossier_write` **chỉ orchestrator**
  (BUG-105 hoàn nguyên theo `ledger.md:194`); bảng `research_dossiers` khoá chính `(research_id, version)`.
- Test: `test_research_quality.py` **25**, `test_research_gate_runtime.py` **12** (chạy thật đường
  `submit` → `delegate_task` → con chạy → cha chốt), `test_dossier_write_tool.py` **16**,
  `test_worker_dossier.py` **37**.
- Giao diện (đợt 4/7): hàng đợi bước, nút dừng nhánh, thẻ mốc tiến độ (ba mặt này **đã giao**);
  "hai mặt duyệt ngân sách" là **spec**, xem mục "Chỗ chưa đo được" ở cuối. Cả đợt: 126 tệp / 1130 ca
  test giao diện.

### Đợt 5 — ba mức, `research_brief`, skill `research-team`, SOP bốn pha

- `limits.py`: bảng `RESEARCH_TIER_*` — nhánh 1/5/15, sóng 1/1/3, giây con 180/420/900, lượt
  1 200/1 200/**3 600** (D-40), trần cứng 1 200/1 800/7 200, phản biện bật ở mức 3.
- `research_brief` ghim brief vào cấu hình phiên, **chỉ hạ mức**, một việc một lượt (BUG-96, BUG-97);
  `research_tier_limits` trả `branchCeiling` + `branchCeilingPerWave` (BUG-98: trước bản sửa mức 3 ra
  `6` thay vì `15`).
- Skill `research-team` (220 dòng) + sửa **36** tệp skill trong cây vendor sang tên tool thật (BUG-89):
  quét lại cây vendor ⇒ **0** `web_extract`; cổng mới `test_skill_tool_names.py` **6**.
- Test: `test_research_brief.py` **11** (bảy ca gốc + bốn ca ý kiến chủ nhà ba nhãn).

### Đợt 6 — pha phản biện độc lập

- Vai thứ 11 `research-review` — BUG-102 (`KeyError: 'research-review'`) từng làm nhánh phản biện
  **không bao giờ** được sinh.
- Sổ `research_verifications` + hai công cụ `research_critique` / `research_verify`; ba công cụ nay có
  **cổng vai** (BUG-99); `source_verify` có **sàn thành công giả** (BUG-101).
- Mục soi ý kiến chủ nhà ba nhãn (#6025): `OWNER_VIEW_LABELS`, `owner_view_findings`, schema
  `ownerViews`, hướng dẫn `### Owner Views`.
- Test: `test_research_critique.py` **7**, `test_research_review_role.py` **4**.

### Đợt 7 — nhịp tiến độ, chỉ thị giữa lượt, hai mặt giao diện

- `maybe_nudge_progress` (600 s, tối đa 12 dòng một lượt) + bảng `session_steers`
  (`pending → injected | dropped`), `queue_owner_steer` / `drain_steers` / `cancel_child`; HTTP trả
  **202** `{'status': 'steered'}` khi lượt đang chạy (`STEER_ENV = 'BOXFOX_STEER'`).
- Test: `test_research_progress.py` **7**, `test_steer_queue.py` **9**, `test_runtime_info.py` **12**.

### Đợt 8 — bộ ca R1–R12, 27 oracle máy, runner ghi số

- `scripts/eval/research_checks.py`: **27 oracle thuần**; `scripts/eval/fixtures/R1.json` … `R12.json`
  (chỉ R2 cần mạng); `rubric.py`, `fixtureset.py` (họ `Q|R`), `research_scores.py` (CLI ghi số).
- `scripts/eval/benchmarks/tiers.json` + `tier-r1.md`: tầng `tier-r1`; mục `research-scores` vẫn
  **blocked** — **chưa có benchmark research nào chạy** (F19). `scripts/eval/results/tier-r1-research/`
  có `manifest.json` `measured: false` và **đúng một** dòng `scores.jsonl` sinh từ ví dụ dựng tay
  (tên miền `.example`), không phải lượt thật.
- Test: `test_research_checks.py` **79 ca**.
- Hai lỗi thật của chính bộ đo đã vá: `milestone_ceiling_declared` so nhãn **có dấu** với dòng **đã bỏ
  dấu** nên không bao giờ đạt (nay xanh, đã bỏ dấu `xfail`); `--plan --fixtures R1` in thừa khối chi phí
  đường Q (tầng R = **0** lượt model).

### Lỗi THẬT của đợt 3–8 đã vá

Mười chín lỗi **BUG-90…BUG-108**, ghi ở `docs/tracking/bug-register.md` §6.36 (kèm căn và cách sửa).
Nặng nhất:

- **BUG-108 (im lặng, nặng):** `annotate_branch_answer` tìm **chủ sổ** từ phiên **CHA** ⇒ mọi nhánh bị
  chú thích `research-lineage-missing` dù nhánh có để lại dòng (đo sống: `gate['rows'] == 0` trong khi
  sổ cha có **1** hàng). Nay lấy phiên con rồi mới đi ngược; ca
  `test_a_research_child_that_did_leave_a_row_keeps_its_row_out_of_the_notes` **đỏ trước / xanh sau**.
- **BUG-94, BUG-95 (cổng ghi hồ sơ):** `NameError: RESEARCH_GATE_MODE_UNKNOWN_CODE` và `IndexError`
  khi `dossier_versions()` rỗng ⇒ lần ghi hồ sơ **đầu tiên** có thể đổ.
- **BUG-102:** `KeyError: 'research-review'` ⇒ nhánh phản biện không bao giờ được sinh.
- **BUG-103:** `dossier_write.tables` mất bảng **âm thầm**.
- **BUG-104:** cổng chất lượng thiếu luật `research-profile-field-missing` (#5989).
- **BUG-107:** bốn mục `TIER1_SUFFIXES` không bao giờ khớp.
- **BUG-90:** `origin-undeclared` đếm sai "nguồn độc lập".

### Số đo của cả vòng (cây đã commit)

- Bộ đơn vị đầy đủ: **1602 passed, 1 deselected in 256,05 s** (`test_terminal_exec_echo` deselected —
  ca ấy đỏ y hệt trên mọi SHA: PowerShell trên Linux, không hồi quy).
- Nhóm 17 tệp research/harness: **393 passed in 95,57 s**; 18 tệp research: **188 ca** (bảng ở trên).
- `test_research_checks.py` + `test_eval_setup.py`: **135 passed**.
- `run_eval.py --plan --fixtures R1 --tier tier-r1 --json` ⇒ `qualityTrackIncluded false`,
  `modelCalls 0`, `costUsd [0, 0]`; `--list --fixtures R1` ⇒ tiêu đề
  `Fixture research (tầng R, kế hoạch vòng 27 §8) — 1 ca tĩnh:`.

### Chỗ chưa đo được, nói thẳng

- **Chưa có benchmark research nào chạy** (F19): bộ ca `R1–R12` và 27 oracle đã có trong mã, nhưng
  điểm của một lượt thật vẫn `blocked` — cần máy có model và box sinh `.research/**`.
- **Nút duyệt ngân sách chỉ là spec**: không có mã nào đọc hay ghi `research-budget` — `grep` thấy
  **hai dòng, cả hai là luật trong chính skill** (`vendor/hermes/skills/research/research-team/SKILL.md:137`,
  `:199`), không dòng nào trong mã Python/TypeScript; trang `docs/architecture/research-agent.md` §5
  ghi rõ phần nào đã có trong mã.
- Mặt `unknown` của `researchTiers` trong `runtime-info` chưa có (bản hiện tại trả `overrides` + `tiers`).

## Vòng 27 — hậu kỳ chất lượng: soát mã, soát eval, đơn giản hoá — rồi lượt kiểm thử độc lập `v27d` (2026-09-24, sáng)

Ba commit hậu kỳ trên **`a037bea`**: **`2bcc02b`** (lõi research + đơn giản hoá, 16 tệp), **`1c9f624`** (bộ đo
eval, 18 tệp), **`79df0a9`** (tài liệu, 4 tệp). Nguồn: lượt soát lõi (`v27d-review-core`, điểm rủi ro
**5/10 — Medium**), lượt soát eval/giao diện/tài liệu (`v27d-review-eval`, **3/10 — Low**), lượt đơn giản hoá
(`v27d-simplify`) — **mười hai lỗi thật** đã vá trong cùng ngày (bảng ở `docs/tracking/bug-register.md` §6.36).

### Lượt kiểm thử độc lập `v27d`

- Đóng băng `a037bea` để so; đo trên cây ĐÃ commit. Bộ đơn vị: **1602** (`a037bea`) → **1633** (hậu kỳ) →
  **1638 passed, 1 deselected in 259,31 s** (sau bản vá dưới đây). Giao diện (**không** đổi trong bản vá):
  126 tệp / 1130 ca qua, `tsc -b --noEmit` thoát 0.
- Sáu việc ưu tiên của bản vá hậu kỳ đều đạt trên cây mới: lượt sau **nâng được mức** (bản cũ khoá phiên
  vĩnh viễn); URL dính dấu `.` ở đuôi **đi qua cổng**; hai nhánh mở cùng nguồn ⇒ **một hàng**, cả hai nhánh
  đọc được (`rows=1`, không còn `research-lineage-missing`); `BOXFOX_RESEARCH_GATE=warn` **không** còn notice
  "giá trị lạ"; phòng sai ⇒ `DOSSIER_DIR_MISMATCH` (không `NameError`), `researchId` lạ ⇒ `RESEARCH_BRIEF_TAKEN`;
  `--plan`/`--list` tách đúng họ Q/R (tầng R nói **0 lượt model**).
- Đường **chỉ thị giữa lượt** chạy thật trên giao diện (harness scratch + Vite scratch, cổng chủ nhà không
  bị chạm): lúc lượt đang chạy có dải "áp ở bước sau" và nút gửi "gửi cho lượt đang chạy"; gửi thì hộp "đã
  xếp" hiện ra và hàng `session_steers` là `state=pending`; sang bước sau hàng thành `injected` và yêu cầu
  tới model mang `[Chỉ thị giữa lượt của chủ nhà]`; lượt xong thì hộp và dải tự mất.
- **Hai lỗi nặng còn mở ở `79df0a9`** (lượt ấy chỉ đọc, không sửa): **F-A** `DOSSIER_VERSION_TAKEN` lặp lại y hệt
  khi phòng đã có tệp `v1` mà chỉ mục chưa biết — nay **BUG-109**; **F-G** guard trần lượt trong cùng lượt so
  **ngược** (nâng đi qua, hạ bị từ chối) — nay **BUG-110**, do chính bản vá `2bcc02b` gây ra. Hai mục nhẹ:
  **F-H** thẻ mốc thiếu trần đang chạy (**BUG-111**) và **F-I** chú thích nói phòng ở lại còn mã mở phòng mới
  (**BUG-112**).

### Bản vá sau lượt `v27d` (cùng ngày)

- `limits.DOSSIER_VERSION_ATTEMPTS_MAX = 10` + vòng lặp thử bản kế khi box báo `DOSSIER_VERSION_TAKEN`
  (bản cũ vẫn **không** bị ghi đè); hết ngân sách thì ném nguyên văn lỗi của box.
- Guard trần lượt cùng lượt: `if stored and ceiling > stored: raise …` — **nâng bị từ chối, hạ được nhận**.
- Thẻ mốc mang `ceilingSeconds` (trần **đang chạy**), tách khỏi `turnSeconds`/`softCeilingSeconds` (hạn mức
  danh nghĩa của mức).
- **Một việc = một phòng**: giữ `dossierDir` khi nó khớp khuôn `.research/<slug>-<yyyymmdd-hhmm>`, thay khi
  không khớp (bản ghi cũ) — ca cũ chỉ xanh nhờ hai lời gọi rơi vào cùng một phút, nay ghìm đồng hồ.
- Lượt đo lại trên `4843563` của chính lượt `v27d` tìm thêm **F-J** — hệ quả phụ của bản vá BUG-110: khối
  "bỏ trống trần ⇒ giữ trần đã chốt" nằm SAU cổng cùng lượt, nên gọi lại brief trong cùng lượt mà bỏ trống
  trần bị từ chối oan (nay **BUG-113**). Vá cùng ngày: hoist khối bảo tồn lên trước cổng.
- Sáu ca mới (`test_research_brief.py` **17**, `test_dossier_write_tool.py` **20**); mỗi ca hành vi chứng minh
  **đỏ trước / xanh sau** (đo: chạy lại trên đúng mã `4843563` thì ca F-J đỏ; trên `79df0a9` thì năm ca kia đỏ).
- Bộ đơn vị đầy đủ sau lớp vá cuối: **1639 passed, 1 deselected** (`/var/tmp/v27/unit_after_fj.log`).

### Vòng 28 — khuôn trả lời cuối hạ hết xuống GỢI Ý (D-44, ngoài plan vòng 27)

- **Nguồn yêu cầu:** tin nhắn chủ nhà (2026-09-24, 06:47 UTC) — "chỉ là skill gợi ý agent trả lời, k nên
  khóa cứng"; agent phải trả lời **tự nhiên như chat/code assistant** và **ngắn**, các phần đã làm chỉ là
  gợi ý, **không được ép** agent theo khuôn. Lượt 24 (D-31/D-32) mới gỡ khuôn cứng ở tầng *văn bản người
  dùng nhận*; lượt này gỡ nốt ba chỗ còn **RA LỆNH** ở tầng kỹ năng và prompt (**BUG-114**).
- **Ba chỗ bị gỡ:** (1) kỹ năng `final-report` — "the evidence part **closes** the answer, and it is **the
  most important part**", "**Never** print an empty part", "**Not optional**"; (2) `RECAP_CLOSER` — "**read**
  the `final-report` skill… **re-capture every item**"; (3) `ANSWER_EVIDENCE_LINE` — "A turn with something
  observable **closes** the answer with…". Ghim cũ trong `test_runtime_prompt.py` còn **khẳng định** hai câu
  ra lệnh ấy, nên phép đo cũ *bảo vệ* chính chỗ sai.
- **Đã sửa:** kỹ năng viết lại thành `3.0.0` ("ideas, not a form" — menu gợi ý, không thứ tự, không mục bắt
  buộc); `RECAP_CLOSER` nói rõ "this is not the answer… write the answer your own way: natural and short";
  `ANSWER_EVIDENCE_LINE` thành câu điều kiện ("you may close the answer with…"); `AGENT.md` §3.4 nói thẳng
  "no part list, no order and no template is required". Đổi luôn **chiều ghim**: ca cũ khẳng định hai câu ra
  lệnh, nay khẳng định chúng **vắng** và khẳng định câu gợi ý **có**.
- **Số quyết định:** dùng **D-44** (không dùng D-33 — số ấy vòng 25 đã dùng cho quyết định khác; xem
  `owner-decisions.md` §4.3). Mọi chỗ mới đã ghi D-44.
- **Đo:** `test_runtime_prompt.py` **18 ca** xanh; nhóm ba tệp prompt (`test_runtime_prompt`,
  `test_skill_commands`, `test_harness_runtime`) **232 passed**; bộ đơn vị đầy đủ **1640 passed, 1 deselected
  in 264.47s, EXIT=0** (`/var/tmp/v28/unit_v28.log` — hơn lượt trước đúng **một ca**, chính là ca ghim chiều
  ngược mới).
- **Điều KHÔNG đổi (cố ý):** luật trung thực của kỹ năng — **không bịa ảnh**, **không dùng ảnh cũ**, nói rõ
  việc chưa chạy — và dòng bằng chứng vẫn chỉ có ở **phiên chính**, vẫn chỉ **một** lần, vẫn nằm sau
  `=== ANSWER LENGTH ===`.
- **Bằng chứng SỐNG trên app thật (2026-09-24, 08:38 UTC):** một lượt THƯỜNG (không research, không công cụ)
  trên harness scratch `3151`, phiên `ede6e940`, trả lời trong **8,5 s / 188 token** bằng **một đoạn văn**
  tiếng Việt tự nhiên (*"Ừm cái này tôi gặp hoài, web tĩnh nhìn đơn giản vậy chứ lúc bàn giao hay dính lỗi
  vặt lắm…"*) — **không** tiêu đề mục, **không** gạch đầu dòng, **không** dòng bằng chứng, **không** mục nào
  của khuôn cũ. Ảnh: `/code/.generated_artifacts/images/v28-plain-turn-answer.png`.

### Lượt research Y TẾ THẬT — sáu lần thử trên app thật (harness scratch `3151`, 2026-09-24)

Đề bài của chủ nhà (nguyên văn rút gọn): *"Thử cho nó nghiên cứu thị trường, tìm gap, painpoint trong lĩnh
vực y tế để phục vụ bài toán agent trong y tế… tôi thấy các ảnh bạn gửi hầu như chưa phải research thật
của agent boxfox, nên cần kiểm nghiệm thật"*. Vì vậy lượt này chạy **trên app thật** (harness scratch cổng
`3151` dựng từ cây vòng 28, dữ liệu riêng `/var/tmp/v27t/research1`, cờ `BOXFOX_RESEARCH_BRIEF=enforce`,
`BOXFOX_RESEARCH_GATE=enforce`, `BOXFOX_RESEARCH_PROGRESS=on`), model `muse-spark-1.3-contributor-free` qua
router `3101`. Không cổng nào của chủ nhà bị chạm.

| Lần | Khoá | Sổ nguồn | Hồ sơ | Kết thúc lượt | Ghi chú đo được |
|---|---|---|---|---|---|
| 1 — `0d0fe166` | OpenCode Free | **13 hàng** (WHO tầng 1, World Bank ×2, Tuổi Trẻ ×2, Thanh Niên, Wikipedia ×2, `api.crossref.org` cho bài JAMA) | **không** (cổng từ chối 1 lần: 6 dòng sổ / 17 mục) | `failed` — `UPSTREAM_HTTP_502` ở bước 22 (13,8 phút) | 3 nhánh `research` con xong (9–13 bước); model tự nói *"Đủ 6 nguồn vào sổ — giờ tôi chốt 6 nỗi đau…"* |
| 2 — `30003232` | OpenCode Free | **24 hàng** | **không** (không kịp ghi lần nào) | `failed` — `UPSTREAM_HTTP_502` ở bước 15 (13,7 phút) | Cùng bệnh với lần 1 ⇒ theo luật §2.3 của `docs/plan/v27/research-quality-tests.md` (**502 ⇒ thử lại 1 rồi CHUYỂN KHOÁ**) nên lần 3 đổi sang **key 1** |
| 3 — `b5832e29` | **key 1** (`f8a5f4e8…`) | **9 hàng** (6 nguồn chính + 3 xác nhận WHO/World Bank) | **không** (cổng từ chối 2 lần: 6 dòng/11 mục rồi 8 dòng/13 mục) | `completed` **`partial`** — `DEADLINE_EXCEEDED` ở bước 30 (20,2 phút, 41 tool) | Lượt đầu **chạy hết trần 1200 s**; model gọi `research_brief` với `ceilingSeconds: 1200` ⇒ máy nới lượt `+600s` (`TURN_EXTENDED`, trần cứng của mức 2 là 1800 s) rồi tới được `dossier_write`; chẩn đoán cuối nêu đúng thứ cổng đòi (*"thiếu số hiệu/ngày hiệu lực văn bản, thiếu trường đối tượng hồ sơ health; hàng r9 trích 79 ký tự dưới sàn 80"*) |
| 4 — `bc8d9125` | key 1 | **9 hàng** (4 nguồn) | **không** (cổng từ chối 1 lần: 7 dòng/7 mục) | `failed` — `UPSTREAM_HTTP_502` ở bước 21 (13,0 phút) | Đổi hồ sơ sang nhóm **thị trường** (`jobProfile: users`, usecase TM-3 "nỗi đau/gap người dùng") sau khi lần 1–3 cho thấy hồ sơ `health` (nhóm văn bản chính thống) đòi `docNumber`/`effectiveDate`/`validity` trên **mọi** hàng — thứ báo chí và Wikipedia không có. Hai lần tham số JSON hỏng, ba hàng `type: confirm` trên **cùng host** (`en.wikipedia.org`, `tuoitre.vn`) nên bộ đếm `independent` đứng ở 2 |
| 5 — `6e274b19` | key 1 | **2 hàng** | **không** (không kịp ghi) | `failed` — `DEADLINE_EXCEEDED` ở đúng **600 s**, bước 2 (10,0 phút) | Model gọi `research_brief` với `ceilingSeconds: 600` (**bằng đúng hạn mức mặc định của phiên**) ⇒ **KHÔNG** có `TURN_EXTENDED`; rồi nó giao việc cho ba nhánh con (`wait: true`) và chết khi đang chờ nhánh thứ ba. Cả ba nhánh con nhận `RESEARCH_GATE_NOTE` với tiêu chí của **hồ sơ** (`research-shape-missing`, `research-lineage-missing`) — thứ nhánh con không có `dossier_write` để thoả |
| 6 — `5e689d49` | key 1 | **0 hàng** (chỉ `web_fetch`, không gọi `source_add`) | **không** (không kịp ghi) | `failed` — `UPSTREAM_HTTP_502` ở bước 14 (8,5 phút) | Lượt này **có** được nới trần (`TURN_EXTENDED +600s` sau khi xin `ceilingSeconds: 1200`), nhưng nhà cung cấp cắt ở phút 8,5 khi model vẫn đang mở trang chủ sáu host — nó đọc mà **chưa** gọi `source_add` lần nào |

**Năm điều đo được (giá trị thật của lượt kiểm nghiệm):**
1. **Đọc nguồn là thật**: mọi hàng sổ đều có URL mở bằng `web_fetch`/`web_search` và một đoạn trích nguyên
   văn 79–464 ký tự (một hàng 79 ký tự bị cổng bắt vì dưới sàn 80 — luật chạy đúng).
2. **Sổ nguồn phân tầng thật**: `host` + `tier` do máy chấm (WHO `who.int` tầng 1, báo chính thống tầng 2,
   Wikipedia/`api.crossref.org` tầng 3) và có bộ đếm `byTier`/`independent` cho từng hàng.
3. **Cổng chất lượng chạy thật ở chế độ `enforce`**: `dossier_write` bị **TỪ CHỐI** ít nhất năm lần trên
   năm lượt, kèm danh sách mục cần sửa (mã + cách khắc phục), và model **quay lại sửa** thay vì bịa (nó thêm
   hàng `type=confirm`, kéo đoạn trích dài hơn, đổi sang "suy luận"). Đây là hành vi đúng của vòng 27 và là
   thứ các lượt trước chỉ chứng minh bằng probe.
4. **Hạn mức lượt là chỗ chặn THẬT của mức 2**: xin 600 s thì máy không nới (lượt 5 chết đúng giây thứ 600
   khi đang chờ nhánh con), xin 1200 s thì được nới `+600 s` và lượt có thời gian viết hồ sơ (lượt 3 và 6).
   Hợp đồng công cụ `research_brief` **không nói gì** về tham số `ceilingSeconds`, nên chuyện "xin bao nhiêu"
   phụ thuộc hoàn toàn vào phán đoán của model.
5. **Nhà cung cấp miễn phí cắt lượt ở phút 8,5–14** (bốn lần `UPSTREAM_HTTP_502`) — tức là **trước** khi một
   lượt mức 2 kịp đóng hồ sơ; đây là lý do phần lớn lượt thật chết giữa đường dù mã chạy đúng. Hai lượt còn
   lại chạm trần thời gian: lượt 3 ở 20,2 phút (đã tới `dossier_write`), lượt 5 ở đúng 600 s (chưa kịp làm gì
   ngoài việc giao nhánh con).

**Năm phát hiện mới từ các lượt này** (ngoài phạm vi plan vòng 27, đã `surface`): (a) bộ từ khoá tiêu đề hồ
sơ không nhận tiêu đề tiếng Việt tự nhiên (*"Kết luận chính"*); (b) câu khắc phục *"Thêm nguồn khác nguồn tin
gốc"* bị hiểu là "thêm trang nữa" trong khi luật thật là **khác host**; (c) lời gọi có tham số JSON hỏng bị
thay bằng `{}` mà model chỉ nhận một câu *"Invalid tool arguments"* — không độ dài, không vị trí lỗi;
(d) lượt mức 2 xin `ceilingSeconds` bằng hạn mức mặc định thì không được nới, dù bảng mức ghi mức 2 = 1200 s;
(e) nhánh con nhận lời nhắc cổng với tiêu chí của hồ sơ mà nó không có quyền ghi.
## Vòng 29 — vòng khoá trong một connection

### Đợt 4 — kiểm OFFLINE phần research (chưa có lượt sống nào)

- **Đợt này KHÔNG gọi nhà cung cấp nào.** Bằng chứng là unit test hai tầng probe provider GIẢ: tầng router
  (`router/tests/**`, `createProviders({ fetchImpl })` — sở hữu của luồng router) và tầng harness
  (`backend/tests/unit/test_router_keyring_probe.py`, mới, **2 ca**). Câu chốt nguyên văn: *"đợt 29 chỉ
  chứng minh bằng unit test; nó KHÔNG chứng minh một lượt research thật giờ chạy xong — đợt này không gọi
  nhà cung cấp nào."*
- Giàn harness ghim hai hành vi: xoay khoá ở TRONG router ⇒ harness thấy **một** lời gọi HTTP và một câu trả
  lời 200 (không phải sửa harness); hết sạch khoá (429 cho mọi lần thử) ⇒ **một** lỗi tạm thời đọc được
  (`Router HTTP 429`, mã `RATE_LIMIT`, `UPSTREAM_HTTP_429`), lời khuyên thử lại bị chặn hai đầu
  (`delay ∈ [2, 30] s`), và lời gọi trả về ngay (đo: cả hai ca trong 0,46 s).
- **Bốn sửa nhỏ offline** (đo từ sáu lượt thật của vòng 28 — xem §"Lượt research Y TẾ THẬT" ở trên):
  (a) bảng từ tiêu đề hồ sơ nhận tiêu đề Việt tự nhiên ("Kết luận chính" không còn bị
  `research-shape-missing mục Phát hiện`); (b) câu khắc phục `research-claim-single-source` nay nói ra chữ
  **host** thay vì "khác nguồn tin gốc"; (c) thông báo tham số công cụ hỏng mang thêm độ dài + vị trí lỗi
  (`tool_arg_errors.py` + 7 ca — luồng chính của phiên); (d) `ceilingSeconds` được MÔ TẢ trong hợp đồng
  `research_brief` (bỏ trống ⇒ giữ trần đã chốt; muốn nới thì phải xin dài hơn số giây lượt đang có).
  Câu tài liệu lệch ở `scripts/eval/benchmarks/tier-r1.md:66` (còn nói ca `milestone_ceiling_declared`
  "đang là `xfail`") đã sửa cho khớp §6.1 của cùng tệp.
- **Số đo trên cây sửa của đợt này (nền `deda6e8`):** nhóm research **286 → 291 passed** (24,85 s; +5 ca:
  4 ở `test_research_quality.py`, 1 ở `test_research_brief.py`); `test_research_checks.py` **83 passed**,
  không còn `xfail` nào; giàn probe mới **2 passed in 0,46 s**. Bộ router (`cd router && npm test`)
  **không chạy ở đây** — `router/**` đang được luồng router sửa song song và `router/node_modules` chưa cài
  trên cây này.
- **Chỗ chưa đo được, nói thẳng:** vẫn KHÔNG có lượt research thật nào ghi `.research/**`;
  `scripts/eval/results/tier-r1-research/manifest.json` còn `measured: false`; `scores.jsonl` vẫn đúng **một**
  dòng dựng tay; `R1–R12` chưa chạy trên dữ liệu thật (**C-7** còn mở, **F19** còn hiệu lực). Bốn câu giàn
  probe KHÔNG trả lời: nhà cung cấp thật có cắt lượt ở phút 8,5–14 không; một lượt mức 2 có kịp đóng hồ sơ
  trên khoá thật không; hạn mức theo phiên của provider miễn phí có luật gì; và phát hiện (e) (chú thích cổng
  cho nhánh con) còn treo vì phải kiểm bằng một lượt thật.
- Tài liệu handoff của phần này: `docs/handoff/research-verification.md` (giao thức chạy sống `R1 → R6 → R7 →
  R3`, luật chuyển khoá, bước migrate một lần trên máy chủ nhà, và bảng "chưa làm được").
### Hậu kỳ vòng 29 — bảy lỗ soát mã đã vá và lượt kiểm thử sống chạy lại (2026-09-24, chiều)

- **Hai lượt soát mã độc lập trên `deda6e8..7d1c913`** — nửa router **3/10 Low**, nửa harness + giao diện
  **4/10 Medium**; cả hai kết luận *ship with mitigations*. Lượt router kiểm riêng bằng sha256 rằng
  `router/src/store.mjs` không đổi một byte, rằng vòng lặp khoá kết thúc được, và rằng 429 sau khi stream đã
  bắt đầu thì không đổi khoá giữa dòng.
- **Bảy lỗ đã vá:** router — làm mới token antigravity ghi nhầm khoá đầu của ring (F1), một dòng credential
  không giải mã được làm đổ cả mặt Settings và chặn DELETE (F2), `PATCH {projectId}` trên ring rỗng hồi sinh
  "khoá ma" (F3), `PATCH {apiKey}` không xoá cửa sổ nghỉ (F4), reset số token theo target thay vì theo lượt thử
  (F5, nit); giao diện — tab Router mất đường nhập khoá cũ khi snapshot thiếu `keys` (P1, *phải sửa*), danh sách
  model biến mất với connection `degraded` có model gõ tay (P2), luật dùng được của picker lệch luật router theo
  **cả hai chiều** (P3). Mỗi lỗ một ca ghim; riêng P2/P3 có ca chứng minh đỏ ở cả hai chiều rồi khôi phục.
- **Số đo trên cây đã commit (`261cd93`):** router `242 pass / 0 fail` (6,5 giây; trước vòng 217); frontend
  `129 tệp / 1197 ca` + `tsc -b --noEmit` sạch; nhóm settings `14 tệp / 97 ca`; nửa backend không đổi sau
  `41cbaf8` nên giữ mốc `1665 passed, 1 deselected` (275 giây).
- **Lượt kiểm thử sống (provider GIẢ, chỉ loopback):** router scratch `3161` + stub `127.0.0.1:3171`,
  `16/18` kịch bản xanh — xoay khoá trong MỘT request, `Retry-After` nâng rồi bị chặn ở 120 giây,
  `cooling`/`exhausted` theo lời nhà cung cấp, 400/401/500 và 429 giữa dòng đều KHÔNG xoay, không secret thô
  nào rời router, `409 KEYS_PRESENT`, trần 10 khoá, đủ năm route khoá. Hai ca đỏ là rác trạng thái của chính
  bộ kịch bản (một lượt gọi toả ra hai connection cùng endpoint/model), không phải lỗi mã; chạy lại sạch trên
  router mới `3163` (`/var/tmp/v29/post/check_park2.py`) cho **5/5 bất biến xanh**, gồm "cả ring nghỉ ⇒ lượt sau
  tốn **0** lượt gọi".
- **Bất thường mới ghi nhận, chưa sửa (ngoài phạm vi duyệt):** khi một lượt `provider + model` toả ra nhiều
  connection, lỗi retryable (5xx) của connection đầu có thể bị thay bằng lỗi **cũ** của ring đang nghỉ ở
  connection sau. Ghi ở `docs/handoff/v29-keyring-handoff.md` §8 kèm cách sửa gợi ý.
- **Vẫn KHÔNG có lượt research thật nào** ghi `.research/**`; `manifest.json` còn `measured: false`; **C-7** và
  **F19** giữ nguyên hiệu lực.

## Vòng 2026-10-08 — CUA trên Linux/X11: ca dùng VS Code, độ trung thực khi gõ, và đo latency/token

Vòng này theo yêu cầu chủ sở hữu: *"test kỹ hơn về CUA… mò ra các usecase để test CUA"* và
*"đo token và latency… đo latency từ lúc 1 task CUA giao đến khi hoàn tất"*.

**Ca dùng thật đã chạy hết (mở VS Code → mở tệp → gõ mã → lưu → mở terminal → chạy):**
`code --reuse-window /var/tmp/cua-work/hello.py` → gõ chương trình 111 ký tự → `Ctrl+S`
(`tệp trên đĩa: 111 ký tự KHỚP`) → mở terminal (`Ctrl+`` ``, rồi **bấm vào trong khung** vì
`Ctrl+`` `` không đưa tiêu điểm bàn phím vào terminal) → `cd /var/tmp/cua-work && python3 hello.py`
→ `ran.txt: 5` ⇒ **ĐẠT**. Hai hộp thoại chặn giữa đường được xử lý bằng chính CUA: hộp thoại ghi đè
tệp (bấm bằng CUA) và hộp thoại *"Do you trust the authors of the files in this workspace?"* (bấm
`Trust Workspace & Continue` tại toạ độ ảnh (721, 496) → màn hình (1081, 636) trong **89 ms**; trước
khi vá BUG-117 thao tác này hoặc bị từ chối, hoặc treo).

**Độ trung thực khi gõ (đo trước/sau khi vá BUG-115):** cùng một payload
`Xin chào Cửa sổ! áàảãạ ăâđôơư` — trước khi vá 0/3 lượt khớp (nhận `Xin cho Ca s!`), sau khi vá
**35/35 ký tự khớp trên 3/3 lượt**, kể cả khi có luồng nền chụp ảnh cửa sổ 50 ms một lần để tạo tải
cho X server. Gõ chữ hoa ngoài ASCII còn sai (BUG-118, giới hạn `xdotool`) — ghi nhận, chưa vá.
**Gõ khi máy bận (BUG-119, cùng vòng):** quay phim màn hình bằng ffmpeg 12 fps rồi gõ lại đúng câu
trên vào biểu mẫu web (máy chủ ghi lại đúng byte nhận được): đường cũ chỉ **3/6** lượt sạch (mất
`ăơ`, `ãơ`, `ử`), mỗi ký tự một lệnh **8/10**, nhịp 60 ms **7/10**; ánh xạ sẵn keysym rồi giữ nguyên
trong suốt lần gõ: **16/16 lượt sạch** (361–387 ms cho câu 29 ký tự). Chữ hoa tiếng Việt cũng hết
mất dấu hoa: kiểm byte-chính-xác **26/26 ký tự** `ÁÀẢÃẠĂÂĐÊÔƠƯÉÈẼÍÌĨÓÒÕÚÙŨÝỲ` (440 ms) và 27/27
chữ thường. Ca dùng web quay lại được trọn vẹn: `/tmp/cua-web/ca-dung-web.mp4` (29/29 ký tự khớp
trong lúc đang quay).


**Đo latency và token** (`backend/tools/cua_bench.py`, chi tiết ở `docs/testing/cua-latency-token.md`):
`primitives` p50 — `click` 252 → **23 ms**, `press_key` 152 → **26 ms**, `capture_window` 67 → 41 ms
(và 42 → 14 tiến trình con), `window_from_point` 7,1 → **1,3 ms** (7 → 1 tiến trình),
`get_window_rect` 1,0 → **0,0 ms** (1 → 0 tiến trình), `type_text` 200 ký tự 1 487 → 1 330 ms.
`product` — `key` 53 ms, `click` 54 ms, `type_text` 1 358 ms, `screenshot` 19 ms; payload chữ
94–102 token, một ảnh cửa sổ 1 015×483 ≈ **653 token ảnh**. `case` (giao → xong) **395–408 ms**
trên 3 lượt, trong đó 154–157 ms là hệ điều hành mở cửa sổ và 220–235 ms là ba thao tác CUA.
Chỗ còn chậm nhất: **gõ chữ ~6,6 ms/ký tự** (`TYPE_DELAY_MS = 12`).

**Bài kiểm đơn vị:** `backend/tests/unit/test_x11_platform.py` **65 lượt xanh** (44 trước vòng này).
### Vòng 2026-10-08 (tiếp) — gia cố sau soát mã: chốt hộp thoại, hình học lúc bấm, chốt trần

Vòng soát mã độc lập trên `464af30`+`a7a7454` trả về 8 điểm (3 điểm mức trung bình), trong đó 3
điểm là hệ quả của chính các bản vá trong vòng này. Đã vá hết:

| Điểm soát | Cách vá | Bằng chứng |
|---|---|---|
| Chốt hộp thoại chỉ đòi `WM_TRANSIENT_FOR` — cửa sổ lạ cùng màn hình cũng đặt được | Cửa sổ KHÁC phải khai thêm `_NET_WM_WINDOW_TYPE` là hộp thoại/popup | 3 bài kiểm mới; đo lại trên máy thật với `CuaDialogMain`/`CuaDialogChild`: chốt điểm bấm và chốt tiêu điểm vẫn NHẬN hộp thoại của chính ứng dụng (BUG-117 vẫn được vá), gõ được 2 ký tự |
| Bộ đệm hình học 0,5 s lọt vào chốt điểm bấm | `check_point_ownership` đọc lại hình học đích tươi ngay trước khi soi điểm | `primitives.click` sau vá: p50 25,3 ms, 9 tiến trình con (thêm 1 `xwininfo`) |
| Chốt trần im lặng khi thiếu số đo | Duyệt theo danh sách trần: thiếu số đo ⇒ `KHÔNG ĐO ĐƯỢC` + thoát 1 | `{"product.click": {"n": 0, "error": …}}` → 14 mục vượt trần, thoát 1; baseline đủ (primitives+product) → ĐẠT, thoát 0 |
| `product.screenshot` đo đường báo lỗi `UNSUPPORTED_ACTION` | Đo đúng `computer_screen_capture` | 126 ms, 21 tiến trình con, 1920×1080 ≈ 2 764 token thị giác (số cũ 19 ms là thời gian trả lỗi) |
| Con trỏ lệch trong lúc chờ tiêu điểm | Vẫn gửi `mousemove`, chỉ bỏ `--sync` khi con trỏ đã đúng chỗ | 2 bài kiểm mới; bấm hai lần cùng điểm: 2 lệnh `mousemove` không `--sync`, 2 lệnh bấm, con trỏ vẫn ở (50,50) |
| Ghi chú locale hứa hão khi máy không cài locale UTF-8 | Tách `installed_utf8_locale()` và nói thẳng khi máy không có | 4 bài kiểm mới (máy không có locale ⇒ `None` + ghi chú "không cài"; `vi_VN.UTF-8` được dùng) |
| `list_windows` của công cụ đo đọc sai kích thước và không bỏ qua panel | Đọc thẳng `(x, y, w, h)`, so lớp không phân biệt hoa/thường | Trước: terminal 715×141 → 671×33, panel 1632×−998. Sau: 715×141, chọn đúng `cua-truoc` |
| Đo INPUT có thể gõ vào cửa sổ bất kỳ của người dùng | Không có cửa sổ chỉ định thì TỪ CHỐI, thay vì chọn cửa sổ lớn nhất | `product` không tham số in "không thấy cửa sổ nào giống terminal để đo input" và thoát 2 |

Bài kiểm: `tests/unit/test_x11_platform.py` **81 đạt** (73 → 81), `tests/unit/test_cua_bench_budget.py`
**7 đạt** (mới). Số đo sau gia cố: `primitives` — `get_foreground_window` 1,4 ms, `get_cursor_pos`
2,6 ms, `get_window_rect` 0,0 ms (0 tiến trình), `window_from_point` 1,2 ms (1), `window_properties`
2,1 ms, `capture_window` 35,6 ms (14), `capture_screen` 49,5 ms, `press_key` 26,8 ms, `click` 25,6 ms,
`type_text` 200 ký tự 1 323 ms; `product` — `key` 60 ms (31 tiến trình con), `click` 65 ms (35),
`type_text` 1 369 ms (47), `screenshot` 126 ms (21); `case` (giao → xong) 397–462 ms.
