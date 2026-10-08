# Hợp đồng kỹ thuật — đợt 4 (chốt trước khi song song hoá)

Đây là hợp đồng **đóng băng** giữa bốn luồng công việc của đợt 4. Mọi luồng phải khớp đúng tên, kiểu, giá trị trong tài liệu này. Nếu thấy cần đổi, báo lại thay vì tự đổi một phía.

## 0. Quy tắc chung

1. Không có dữ liệu giả trên đường chạy thật. Không thêm chuỗi tiếng Việt/tiếng Anh cứng trong component — dùng `useT()` với khoá i18n.
2. **Không đổi thiết kế giao diện.** Chỉ nối dữ liệu và hành vi vào các component, lớp CSS, token sẵn có. Không thêm màu, font, bố cục mới. Nếu buộc phải thêm phần tử, dùng đúng lớp CSS của các phần tử anh em.
3. Mọi sự kiện đều đi qua `SessionStore.emit(sid, kind, payload)` (bảng `events`, cột `kind` tự do, không cần migration). Frontend đọc qua `harnessChatStore` (`events[]`, mỗi phần tử `{seq, type, data, created}`).
4. Mọi route ghi của container bắt buộc có header `X-BoxFox-Api-Key` (giá trị `boxfox-local-dev-token` trong dev) — thiếu thì trả 401.
5. Việc gì cần người dùng quyết định thì đi qua **một** đường: tool `ask_user` / `request_approval` → event `decision_requested` → route trả lời → `decision_resolved`.

## 1. Sự kiện harness (`backend/`)

### `decision_requested`

```json
{
  "decisionId": "9f2c…hex16",
  "kind": "question",
  "question": "Chọn cách triển khai?",
  "action": null,
  "reason": null,
  "options": [
    {"id": "approve", "label": "Duyệt", "kind": "approve"},
    {"id": "reject",  "label": "Từ chối", "kind": "reject"}
  ],
  "deadline": 1758300000.0,
  "defaultChoice": "reject",
  "toolCallId": "call_abc"
}
```

- `kind`: `"question"` (từ `ask_user`) hoặc `"approval"` (từ `request_approval`).
- `action`, `reason`: chỉ có khi `kind == "approval"`; ngược lại là `null`.
- `options`: 2–5 mục, mỗi mục `{id, label, kind}` với `kind ∈ {approve, reject, alternative}`. `ask_user` luôn có ít nhất một `approve` và một `reject`.
- `deadline`: epoch giây (float). `ask_user` mặc định 300 s; `request_approval` mặc định 600 s; trần 3600 s.
- `defaultChoice`: luôn `"reject"`.

### `decision_resolved`

```json
{"decisionId": "9f2c…", "choice": "approve", "status": "approved", "note": "ok", "reason": "user", "resolvedAt": 1758300012.5}
```

- `status ∈ {approved, rejected, expired, cancelled}`.
- `reason ∈ {user, timeout, session_cancelled}`.
- `choice`: id lựa chọn; khi hết hạn/cancel thì bằng `defaultChoice`.
- Đúng một `decision_resolved` cho mỗi `decisionId` (kể cả đường hết hạn và đường huỷ phiên).

### `plan_written`

```json
{"identity": "workspace-plan", "version": 2, "slug": "workspace-plan",
 "relativePath": ".plans/v2-workspace-plan.md", "title": "Workspace plan", "bytes": 4312}
```

- `identity`: **đúng giá trị mà `GET /__box/plans` dùng để nhóm plan** — slug trần khi file nằm ở gốc `.plans/`, hoặc `dir/slug` khi file nằm trong thư mục con (xem `plan_files.py:315-321`). TUYỆT ĐỐI KHÔNG kèm tiền tố `vN-`; số version nằm ở trường `version`. UI chọn đúng bản mới bằng cặp `(identity, version)`.
- `version`: số nguyên của version vừa ghi.
- `relativePath`: đường dẫn tương đối so với `WORKSPACE_ROOT`, dạng `.plans/v2-<slug>.md`.

### `ui_intent`

```json
{"tab": "plan", "target": {"identity": "workspace-plan", "version": 2}, "reason": "plan_written"}
```

- `tab ∈ {plan, decisions, files, subagents, design}`.
- `design`: **chưa có producer `ui_intent` nào phát tab này.** Tab Design tự mở bằng nhánh suy ra từ event gốc `design_canvas` trong `dispatchTabIntents` (`harnessChatStore.ts`): lần vẽ ĐẦU TIÊN của một `designId` thì mở (bỏ qua khi nạp lịch sử, khi `actor === 'user'`, và vẫn qua đủ bốn cổng §3); các lần vẽ sau chỉ cập nhật. Không thêm `ui_intent {tab:'design'}` song song — đó là bản sao thứ hai của cùng một sự thật, và là chỗ trôi thứ hai khi một trong hai bên đổi.
- `target`: `{identity, version}` cho `plan`, `{requestId}` cho `decisions`, `{path}` cho `files`, `{sessionId}` cho `subagents`, `{designId}` cho `design`; có thể là `null`.
- `reason`: lý do gợi ý mở tab. **Hôm nay có ba giá trị được phát ra thật**: `plan_written` (khi agent ghi plan), `decision_requested` (khi agent cần người dùng quyết định) và `canvas_drawn` (lần vẽ đầu tiên của một `designId` — xem gạch đầu dòng `design` ở trên; đây cũng là `reason` trong `pendingIntents`). Hai giá trị `file_selected` và `child_started` là **chỗ dành sẵn cho đợt sau** — chưa producer nào phát, nên đừng viết mã tiêu thụ dựa vào chúng; khi nào phát thật thì bổ sung vào đây trước.
- Gợi ý cho UI, **không** phải mệnh lệnh: UI tự quyết định có mở hay không theo luật ở §3.

### `plan_evaluated` (đợt 20)

Phát sau khi harness chấm một bản kế hoạch theo thang điểm P1–P8 (`plan_eval.py`), trước khi
`plan_written` được coi là "đã xong" ở phía UI.

- `data`: `{identity, version, total, verdict, hardGate, gatesFailed, rubric, rejected}` —
  `verdict ∈ {pass, pass_with_conditions, fail}`; một hard-gate trượt ⇒ `verdict = 'fail'` dù điểm còn.
- Chỉ **một** sự kiện cho mỗi bản được chấm; bản bị từ chối không ghi file plan nào.

### Trạng thái phiên


- Trong lúc chờ trả lời, `sessions.status = 'awaiting_decision'` (giá trị mới, nằm cạnh `running|completed|failed|cancelled|interrupted`).
- Khi có trả lời, quay lại `running`; hết hạn thì lượt chạy tiếp tục với kết quả `rejected` (agent phải nói rõ là bị từ chối).

## 2. Route và endpoint

### Harness (`backend/src/agentbox/api/server.py`)

`POST /api/agent/sessions/{sid}/decisions`

- Thân: `{"decisionId": "...", "choice": "approve", "note": "..."}` (`note` tuỳ chọn).
- 200: `{"status": "resolved", "decisionId": "...", "choice": "approve", "outcome": "approved"}`.
- 404: `{"error": "DECISION_NOT_FOUND: ..."}` khi `decisionId` không nằm trong phiên này.
- 409: `{"error": "DECISION_ALREADY_RESOLVED: ..."}`.
- 400: `{"error": "DECISION_INVALID: ..."}` khi thiếu trường hoặc `choice` không nằm trong `options`.

`POST /api/agent/plans/review`

- Thân: `{identity, version, decision: 'approved'|'changes_requested', note}`.
- 200: `{identity, version, decision, note, forwarded, review}` — `forwarded: false` khi box tắt;
  quyết định **vẫn** được ghi vào sổ duyệt của harness (không bao giờ mất vì hạ tầng).
- 400 khi thiếu `identity`/`version`/`decision` hoặc `decision` lạ.

`GET /api/agent/plans/status?identity=<slug|dir/slug>&version=<n>`

- 200: `{state, stateVersion, review, reviewStale, indexAvailable, identity, version, evaluation}`.
- `state ∈ {draft, approved, changes_requested, superseded, none, unknown}`; `reviewStale: true` khi
  bản trên box đã đổi kể từ lúc duyệt (so `sizeBytes`/`modifiedAt` đã ghim trong sổ).
- `evaluation` (đợt 20): `null` hoặc `{identity, version, total, verdict, rubric: {P1..P8}, hardGate,
  gatesFailed, layer, measures, evidence, warnings, evaluatedAt}`.

`GET /api/agent/sessions/{sid}/journal?after=<seq>&kind=<k>&limit=`

- 200: `{records, nextSeq, more, degraded}`; `records[]` mang `{seq, kind, id, status, text, data, ts}`.
- `degraded: true` khi tầng file của nhật ký đã hỏng ít nhất một lần trong phiên (đọc từ `notice`
  `JOURNAL_DEGRADED`/`CHECKPOINT_FILE_FAILED`).

`GET /api/agent/journal/tasks?status=&limit=`

- 200: `{tasks: [{id, session, sid8, status, text, created, ts, refs, evidence}]}` — đọc từ bảng
  `journal` của harness, nên trả lời được cả khi box tắt.

Payload `GET /api/agent/sessions/{sid}` cộng thêm (additive, chỗ đọc cũ không phải biết):

- `sessionMetrics: {messageCount, contextEstimate, compressionCount, deadlineClamped}`;
- `journal: {records, lastSeq, degraded}`.

### Container (`deploy/docker/ide-proxy.py` + `workspace_files.py`)

Tất cả đều `POST`, JSON, cần `X-BoxFox-Api-Key`, trả 400 `{"error": "..."}` khi sai.

| Route | Thân | Trả về |
|---|---|---|
| `/__box/files/mkdir` | `{"path": "src/new"}` | `{"path": "src/new", "type": "directory"}` |
| `/__box/files/touch` | `{"path": "src/new.md", "content": ""}` | `{"path": "src/new.md", "type": "file", "size": 0}` |
| `/__box/files/rename` | `{"path": "src/a.md", "name": "b.md"}` | `{"path": "src/a.md", "newPath": "src/b.md"}` |
| `/__box/files/move` | `{"path": "src/a.md", "destination": "docs"}` | `{"path": "src/a.md", "newPath": "docs/a.md"}` |
| `/__box/files/delete` | `{"path": "src/a.md"}` | `{"path": "src/a.md", "trashPath": ".trash/1758300012-a.md"}` |
| `/__box/plans/review` | `{"identity": "v1-pilot", "decision": "approved", "note": ""}` | `{"identity": "v1-pilot", "decision": "approved", "note": "", "updatedAt": 1758300012.5}` |
| `/__box/captures/prune` | `{"session": "<32 hex>", "dryRun": true}` | `{"ok": true, "removedFiles": 0, "removedBytes": 0, "pinned": [...]}` |

Ba route capture/record (`/__box/capture`, `/__box/record/start`) nhận thêm (tuỳ chọn)
`session`, `step`, `toolCallId`: có `session` thì file vào `captures/<kind>/<sid8>/` với tên
`<sid8>_<step3>_<slug>.<ext>`; không có thì giữ nguyên khuôn phẳng cũ (tương thích ngược).

Luật chung cho các API ghi:

- `path` là đường dẫn **tương đối** trong `/home/agent/workspace`; dùng lại đúng hàm kiểm tra đường dẫn hiện có (`workspace_files.py:153-171`). Từ chối: tuyệt đối, `..`, ký tự NUL, ổ đĩa giả, vượt quá `MAX_DEPTH`.
- `rename` chỉ đổi tên trong cùng thư mục: `name` không chứa `/`, không rỗng, không phải `.`/`..`.
- Ghi đè: `touch` trả 409 nếu đích đã tồn tại; `rename`/`move` trả 409 nếu đích đã tồn tại; `mkdir` trả 409 nếu đã có (trừ khi thân có `"exist_ok": true`).
- `delete` **không xoá thẳng**: chuyển vào `.trash/` trong workspace, tên `<epoch>-<tên gốc>`; `.trash` bị loại khỏi danh sách `GET /__box/files`.
- `delete` từ chối xoá chính `.trash` và các mục bảo vệ (`.plans`).
- `review`: `decision ∈ {approved, changes_requested}`; lưu `{"identity","decision","note","updatedAt"}` vào `/home/agent/workspace/.plans/.reviews/<identity>.json`; `GET /__box/plans` trả thêm `"review"` cho mỗi bản ghi (hoặc `null`).

## 3. Luật tự mở tab (frontend)

`useUiStore` là nơi duy nhất quyết định. API mới:

```ts
requestTabIntent: (intent: { tab: PanelTabId; target?: Record<string, unknown> | null; reason: string }) => 'opened' | 'queued'
```

Thứ tự kiểm tra (dừng ở điều kiện đầu tiên vi phạm → `'queued'`):

1. `autoOpenTabs === false` → `queued`.
2. `workspaceHidden === true` → `queued`. (Bảng Workspace đang ẩn thì mở tab là vô nghĩa — người dùng không thấy gì. Hàng đợi **đóng băng**: chỉ khi người dùng hiện bảng lại mới xả. Cổng này có trong mã từ Kế hoạch E2 nhưng hợp đồng chỉ liệt kê ba điều kiện — nay ghi đủ bốn.)
3. `pinnedTab === intent.tab` → `queued`. (`pinnedTab` đặt khi người dùng **tự bấm** vào tab trên thanh tab; xoá khi người dùng bấm tab khác hoặc đóng tab đó.)
4. `autoOpenOnlyWhenIdle === true` và `Date.now() - lastUserActivityAt < 15000` → `queued`. (`lastUserActivityAt` cập nhật khi có `keydown` trong khung soạn tin hoặc `scroll` trong khung chat — đặt ở `ChatPanel`, chỉ ghi vào store, không đổi giao diện.)

Khi `queued`: thêm vào `pendingIntents[]` (giữ tối đa 20, mới nhất ở cuối), tab đích hiện huy hiệu đếm, **và** `pendingIntentNotice` ghi lại `{tab, reason, at}` — `reason` là đúng cổng đã chặn (`'tabs off' | 'workspace hidden' | 'tab pinned' | 'user busy'`). `ChatPanel` vẽ hàng thông báo cạnh khung soạn tin từ giá trị này: “Bảng <tên tab> đang chờ mở”, lý do, nút **mở ngay** (đi qua `showTab` — hiện bảng + ghim + mở, nên tiêu thụ hàng đợi và hàng thông báo tự biến mất) và nút bỏ qua (chỉ xoá thông báo; huy hiệu vẫn còn). Khi người dùng mở tab đó thì xoá các intent thuộc tab đó.

`openTab(tab)` giữ nguyên hành vi (mở + kích hoạt) để không phá các chỗ gọi hiện có.

## 4. Điểm nối frontend ↔ backend

- `harnessChatStore` nhận sự kiện mới trong `refresh()` (đã có sẵn `events[]`); khi thấy `ui_intent` **mới** thì gọi `useUiStore.getState().requestTabIntent(...)`; khi thấy `decision_requested` **mới** thì phát một intent `decisions` kèm `{requestId}`.
- Trả lời decision: `harnessChatStore.answerDecision(chatId, decisionId, choice, note?)` → `agentApi(`/sessions/${id}/decisions`, {...})`; thành công thì cập nhật ngay chỗ chứa decision trong store, không cần chờ vòng poll.
- Hợp đồng repository workspace (thêm vào `WorkspaceRepository`): `mkdir(path)`, `touch(path)`, `rename(path, name)`, `move(path, destination)`, `deleteEntry(path)` — cùng kiểu trả về như bảng §2; bản mock phải cài đủ để test chạy được.
- `usePlanFiles` phải nghe `planRevision` (số nguyên trong `uiStore`) và tải lại khi số này đổi.
