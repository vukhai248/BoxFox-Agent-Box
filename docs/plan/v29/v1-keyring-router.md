# Vòng 29 — Router key ring: một connection nhiều khoá, tự chuyển khi hết hạn mức, chọn model theo nhà cung cấp

Tài liệu này là kế hoạch chi tiết của vòng 29. Bốn kế hoạch con nằm trong `/code/.plans/subplans/` và giữ toàn bộ chi tiết thi công:

- `v29-keyring-router-plan.md` — nửa `router/` (R-0 … R-5, runbook gộp khoá).
- `v29-keyring-ui-plan.md` — nửa giao diện Settings (danh sách khoá, gộp khoá, mỗi model một dòng).
- `v29-provider-route-plan.md` — dạng route thứ ba `provider + model`, từ picker tới router.
- `v29-research-verify-plan.md` + `v29-research-handoff-outline.md` — kế hoạch kiểm nghiệm research và đề cương tài liệu handoff.

Design: chín màn hình ở `/code/.plans/designs/` (sáu màn key ring `v29-keyring-0{1..6}-*.html`, ba màn model picker `v29-picker-0{1..3}-*.html`) cùng `/code/.plans/designs/design-plan.json`.

---

## 0. Chủ nhà yêu cầu gì

Nguyên văn (2026-09-24, 09:18 UTC): *"trong phần nhập apikey, sẽ có 1 cơ chế router key. khi key này phát hiện limit, chuyển qua key kế, chứ k hiện như hiện tại là opencode key1 model A, opencode key2 model A. khi này, chúng ta sẽ xem xét và khắc phục được vấn đề research hết quota. giúp tôi lên plan và thực hiện. có thể interview nếu cần. phần plan kiểm nghiệm research, ghi vào trong handoff thật kỹ lưỡng, và những gì chưa làm được ở các lượt trước (nếu có)"*.

Ba việc: (a) cơ chế vòng khoá trong router và giao diện nhập khoá; (b) kế hoạch kiểm nghiệm research; (c) tài liệu handoff ghi kỹ, kể cả những gì chưa làm được.

### Quyết định chủ nhà đã chốt (không mở lại)

| # | Câu hỏi | Chủ nhà chốt |
|---|---|---|
| 6041 | Cơ chế khoá ở đâu | **Một connection giữ nhiều khoá** (key ring), chỉ xoay trong cùng một nhà cung cấp |
| 6042 | Khi nào chuyển khoá | Chỉ khi **429 / hết hạn mức** |
| 6043 | Nghỉ bao lâu | "5 phút là quá nhiều, căng là 1 phút thôi, hoặc còn ít hơn là 30 giây" |
| 6044/6046 | Phiên chọn model thế nào | **Theo nhà cung cấp + model** — một dòng cho mỗi model |
| 6047 | Ba connection opencode cũ | **Gộp vào một**; bỏ connection trùng "OpenCode Free" phía router |
| 6045 | Lượt research thật sau khi xong | **Không** — vòng này chỉ kiểm thử máy (unit test) trên mã |
| 6048 | Cooldown | **30 giây** mặc định, theo `retry-after` của nhà cung cấp, **tối đa 2 phút** |
| 6050 | Bốn lỗi nhỏ có gộp vào vòng này | **Có** — gộp cả (a)–(d); (c) sửa **ở chỗ gọi**, cây vendor Hermes giữ nguyên; (e) vẫn treo |
| 6051 | Chữ mới trong Settings | **Tiếng Anh** — mọi chữ mới của khối khoá và picker dùng tiếng Anh; mockup đổi theo cho khớp |
| 6052 | Cách gộp khoá | **Một hành động chuyển tất cả khoá** của connection nguồn. Chủ nhà thấy câu hỏi này rối vì yêu cầu thật rất đơn giản: *"xóa bên router và giữ bên api cho opencode free"* — kế hoạch làm đúng vậy, không cần hỏi lại |
| 6053 | Bỏ khoá cuối cùng | Chủ nhà không chọn — theo đề nghị của kế hoạch: connection **ở lại**, rỗng khoá, **không** tự xoá |
| 6050b | Tài liệu cho người tiếp nhận | Chủ nhà yêu cầu thêm **handoff2**: ghi cả kế hoạch vòng 29 vào một tài liệu handoff riêng, để agent khác đọc được "làm gì và đến đâu" nếu chủ nhà hết hạn mức |

---

## 1. Số đo hiện trạng (đọc từ code tại `deda6e8`)

Bản đồ đầy đủ: `/code/.generated_artifacts/v29-keys-map.md` (296 dòng, mọi khẳng định kèm `path:line`). Tám điểm quyết định hình dạng kế hoạch:

1. **Một connection = một khoá.** `router/src/store.mjs:32` tạo `credentials (id TEXT PRIMARY KEY, encrypted TEXT NOT NULL)` — mỗi connection id giữ đúng một blob AES-256-GCM; `connection.credentialPresent` là một boolean. Không lớp nào (schema, service, HTTP, UI) có chỗ chứa nhiều khoá.
2. **AAD của blob là id của dòng**, không phải id connection (`store.mjs:44`). Hệ quả tốt: chuyển một khoá giữa hai connection là thao tác **dữ liệu**, không phải giải mã rồi mã hoá lại — ciphertext không đổi một byte.
3. **Đã có xoay ở mức connection:** `provider_config.roundRobin` + `connectionOrder` (`engine.mjs:24-35`), alias `strategy: 'round_robin'` (`engine.mjs:36-47`), và vòng lặp `targets` trong `RouterEngine.generate` (`engine.mjs:70-181`).
4. **Harness chỉ thử lại cùng một connection:** `backend/src/agentbox/agent_core/failures.py:203-295` (429 có trong `RETRYABLE_STATUS`, backoff 1/4/12 giây, ngân sách 60 giây) — không đổi khoá, không đổi connection.
5. **Luật "429 thì sang khoá kế" chỉ là quy ước tài liệu:** `docs/plan/v27/research-quality-tests.md` §2.3. Không một dòng mã nào thực hiện.
6. **Phiên chat ghim một connection:** `frontend/src/store/harnessChatStore.ts:642-643`, `:711-713` lưu `route = {connectionId, modelId}`; `selection()` (`engine.mjs:8-54`) vì thế chỉ dựng **một** đích cho router.
7. **Cooldown hiện tại là hai `Map` trong bộ nhớ** (`engine.mjs:7`), luật cũ "2 strike rồi nghỉ 5 giây–5 phút" (`engine.mjs:161-171`); chỉ `antigravity` gieo `retryAfterMs`, các adapter khác bỏ qua header `Retry-After`.
8. **Mỗi connection opencode = một bucket hạn mức** (`providers/opencode.mjs:179-182`) ⇒ ba khoá trong một connection phải mang danh tính riêng, nếu không chúng dùng chung một bucket.

Chuỗi chết của sáu lượt research thật (sổ ở `docs/tracking/test-rounds.md` §vòng 27): bốn lượt `UPSTREAM_HTTP_502` ở phút 8,5–14, một lượt `DEADLINE_EXCEEDED` ở 20,2 phút, một lượt chết đúng 600 giây vì xin `ceilingSeconds` bằng đúng hạn mức phiên. **Không lượt nào ghi được hồ sơ `.research/**`.** Nguyên nhân gốc của phần lớn cái chết: một connection một khoá, phiên ghim connection, nên 429/502 là hết đường.

---

## 2. Phạm vi vòng 29

**Làm:**

1. Key ring trong **một** connection: nhiều khoá mã hoá-at-rest bằng master key sẵn có, thứ tự xoay nằm ở connection, mỗi khoá có nhãn/tiền tố/trạng thái; **không bao giờ** trả khoá thật ra frontend.
2. Engine xoay khoá **chỉ khi 429**: khoá vừa cháy nghỉ 30 giây (theo `retry-after` nếu lớn hơn, trần 2 phút) rồi tự về vòng; cả vòng đang nghỉ ⇒ trả lỗi thật của nhà cung cấp.
3. Năm route HTTP cho vòng khoá (thêm khoá, thay, bỏ, thử ngay, gộp/import) — cộng `GET /api/router/connections` trang trí thêm danh sách khoá.
4. Giao diện Settings: khối "Khoá API" thay ô "Replace API key", danh sách khoá có trạng thái và đếm ngược, hành động gộp khoá, chặn xoá connection còn khoá; danh sách model gộp **một dòng cho mỗi model**.
5. Chọn model theo **provider + model** (dạng route thứ ba) để sau khi gộp, một dòng vẫn định tuyến được và router tự thử các khoá/connection còn hạn mức; vẫn giữ đường ghim một connection.
6. Kế hoạch kiểm nghiệm research (offline trước, sống sau) và tài liệu handoff `docs/handoff/research-verification.md`.
7. Runbook một lần để gộp bốn connection `opencode` của chủ nhà thành một connection ba khoá, và bốn sửa lỗi nhỏ đo được từ sáu lượt thật (mục 2.5).

**Không làm (vòng này):** chạy lượt research thật (quyết định 6045); sửa trường `cost` của router (M6); dọn hai mục `v27e1-simplify`; sửa phát hiện (e) về `RESEARCH_GATE_NOTE` cho nhánh con (chỉ lượt thật mới kiểm được); mọi thay đổi giao diện ngoài Settings và picker.

---

## 3. Năm đợt công việc

### Đợt 1 — Key ring trong router (nửa `router/`)

Nguồn chi tiết: `/code/.plans/subplans/v29-keyring-router-plan.md`. Sáu việc, chạy theo thứ tự R-0 → R-1 → (R-2 ∥ R-3) → R-4 → R-5:

- **R-0 — module vòng khoá.** Tệp mới `router/src/keyring.mjs`: vòng khoá trong bộ nhớ với `headOf` (khoá trên cùng phục vụ trước, không con trỏ xoay vòng), `cooldownFor` (30 giây mặc định, `retry-after` chỉ **nâng**, trần 2 phút) và `classifyState`. Cùng lượt: hàm đọc header `Retry-After` dùng chung ở `router/src/providers/common.mjs` và áp vào `router/src/providers/opencode.mjs` (hôm nay chỉ `antigravity` gieo `retryAfterMs`).
- **R-1 — vòng khoá sống trên storage cũ.** `router/src/service.mjs`, `oauth.mjs`, `errors.mjs`: `ensureRing`, `addKey`, `replaceKey`, `removeKey`, `importKeys`, `tryKey`; `credentials(id, signal, keyId)` — mọi adapter không phải sửa; xoá connection bị **từ chối (409)** khi còn khoá. **`router/src/store.mjs` không đổi một dòng.**
- **R-2 — engine xoay khoá.** `router/src/engine.mjs`: vòng khoá **lồng bên trong** vòng target hiện có; chỉ 429 xoay (400, `AUTH`, 5xx giữ nguyên hành vi hôm nay); cả vòng nghỉ ⇒ lỗi thật của nhà cung cấp nổi lên và lượt đó không tốn thêm lượt gọi provider nào; bỏ hai `Map` strike/cooldown cũ.
- **R-3 — năm route HTTP.** `router/src/server.mjs`: `POST /api/router/connections/:id/keys`, `PATCH`/`DELETE /api/router/connections/:id/keys/:keyId`, `POST .../keys/:keyId/try`, `POST .../keys/import`; `GET /api/router/connections` trả về connection đã trang trí (danh sách khoá, `credentialPresent`).
- **R-4 — tài liệu.** `router/CONTRACT.md` (route mới + luật cooldown, nói rõ trần 2 phút là **quy ước dự án**), `docs/plan/retry-policy.md`, `docs/plan/v27/research-quality-tests.md` §2.3.
- **R-5 — runbook gộp khoá** (viết ở đợt 1, chạy ở đợt 5): `docs/plan/v29-keyring-merge-runbook.md`.

Hợp đồng đã chốt trong kế hoạch con: trần **10 khoá** một connection; `import` chỉ giữa **cùng provider và cùng endpoint**; bỏ khoá cuối ⇒ connection **ở lại** (`authState: 'required'`); chỉ `prefix` ≤ 6 ký tự rời khỏi router; `inferenceState` **không** thêm giá trị thứ tư; nhãn và tiền tố là tất cả những gì giao diện thấy.

Quy mô: khoảng **1 200 dòng** (≈ 400 code sản phẩm, ≈ 670 test, ≈ 115 tài liệu), **5 tệp mới**.

### Đợt 2 — Giao diện key ring

Nguồn chi tiết: `/code/.plans/subplans/v29-keyring-ui-plan.md`. Bám sáu màn hình `v29-keyring-0{1..6}-*.html`.

- Component `ConnectionKeyRing` hiển thị danh sách khoá của một connection, gắn vào đúng chỗ ô input đơn hôm nay: `frontend/src/components/settings/ProviderView.tsx:403-421` (tab API, thay dòng 408) và `:829-861` (tab Router, chỉ với connection không phải OAuth). Connection chưa có khoá thì khối tự hiện empty state kèm nút thêm khoá đầu tiên.
- Mỗi dòng khoá: nhãn, tiền tố đã che, trạng thái `ready` / `cooling · HH:MM` (đếm ngược 30 giây) / `quota exhausted` / `error` (kèm dòng lỗi cuối), cùng các nút `Replace` / `Remove` / `Try now`. **Mọi chữ mới dùng tiếng Anh** (quyết định 6051); các chữ cũ trong màn Settings giữ nguyên. Không bao giờ render secret; dòng lỗi phải lọc bớt chuỗi dài giống khoá.
- Hành động **gộp khoá** trên card: chọn một connection **cùng provider**, gọi **một** lời gọi để router chuyển **tất cả** khoá của connection nguồn sang đích phía máy chủ (quyết định 6052 — một cú bấm cho mỗi connection cũ); connection nguồn ở lại với trạng thái rỗng khoá và dòng "moved N keys to X"; nút Delete của connection còn khoá bị chặn ngay trên giao diện (router là lớp chặn thứ hai).
- Danh sách model gộp theo provider: một model một dòng, thêm chip số connection khi nhiều hơn một, bật/tắt một dòng ghi cho mọi connection phục vụ nó.
- Năm hằng số đường dẫn nằm **một chỗ** ở `frontend/src/lib/routerKeyPaths.ts` (mới) để khớp đúng tên route của đợt 1.
- **Hợp đồng dữ liệu đã đối chiếu khớp giữa hai kế hoạch con:** router phát `connection.keys[]` với `{ id, label, prefix, createdAt, state, cooldownUntil, resetAt, lastErrorCode, lastErrorMessage, lastUsedAt }` và `connection.activeKeyId`; UI đọc đúng bộ đó và đọc phòng thủ (vắng `keys` ⇒ giữ giao diện một khoá hôm nay). Một điểm nhỏ: router phát `prefix` tối đa 6 ký tự của secret, UI `maskPrefix` cũng cắt còn 6 — nếu sau này đổi độ dài thì đổi ở đúng một chỗ.
- **Bỏ T5 của kế hoạch con này** (gộp danh sách model trong picker) — đợt 3 làm việc đó và là **nguồn sự thật duy nhất** cho danh sách model, tránh hai cách gộp xung đột (hai kế hoạch con ghi cùng một danh sách với hai khoá khác nhau).

### Đợt 3 — Chọn model theo provider + model

Nguồn chi tiết: `/code/.plans/subplans/v29-provider-route-plan.md`. Bám ba màn hình `v29-picker-0{1..3}-*.html` (một dòng cho mỗi model · nhánh ghim · phiên đang ghim).

- **Backend:** thêm dạng route thứ ba `{providerId, modelId}` đi hết đường — picker chọn, phiên lưu, `RouterClient` gửi nguyên cặp lên router. Metadata gộp trên **mọi** connection dùng được của provider: cửa sổ ngữ cảnh lấy **số nhỏ nhất**, mức thinking lấy **giao** các danh sách công bố; route provider chỉ mang mức khi mức đang chọn có trong giao đó.
- **Router không sửa một dòng:** `engine.selection()` đã dựng danh sách target theo provider và `generate()` đã failover trước khi có output.
- **Frontend:** tệp mới `frontend/src/lib/routeOptions.ts`; thêm dạng selection `'provider'`; payload route trong `harnessChatStore.ts`; các chỗ tiêu thụ (`RouterTestChat`, `ChatPanel`, `ContextUsageBar`, `HarnessStepView`); picker gộp còn một dòng mỗi cặp provider+model, nhóm nhiều connection mở ra nhánh con (nhãn con giữ `key 1/2/3`), nhánh con có `Pin this connection` và `Unpin`; chữ mới tiếng Anh (quyết định 6051).
- **Tương thích ngược:** phiên cũ giữ `{connectionId, modelId}` chạy y nguyên; route là JSON tự do nên không cần migration, không đổi bảng nào.
- Quy mô: khoảng **13 tệp, ~680 dòng** (3 tệp mới).

### Đợt 4 — Kiểm nghiệm research (offline) và tài liệu handoff

Nguồn chi tiết: `/code/.plans/subplans/v29-research-verify-plan.md`; đề cương: `v29-research-handoff-outline.md`. Quyết định 6045: **vòng này không gọi nhà cung cấp nào.**

- **Offline:** bảng khoảng trống `R1–R12` (ca nào có sẵn, ca nào chưa), sửa **một câu tài liệu lệch** ở `scripts/eval/benchmarks/tier-r1.md:66`, và hai tầng probe provider **GIẢ**: tầng router bằng `createProviders({ fetchImpl })` (429 ⇒ xoay khoá; 400/5xx ⇒ không xoay; khoá cháy nghỉ ≥ 30 giây và ≤ 2 phút; hết vòng ⇒ một lỗi không treo), tầng harness bằng `RouterClient(url)` + một `aiohttp` giả (xoay khoá ở trong ⇒ harness thấy 200, **không** phải sửa harness).
- **Giao thức chạy sống viết sẵn cho đợt sau:** `R1` → `R6` → `R7` → `R3`, mỗi ca một lượt trên harness scratch, luật chuyển khoá §2.3, ghi số bằng `scripts/eval/research_scores.py --append`. Viết luôn luật dừng để lần chạy thật đầu tiên tái lập được.
- **Handoff:** `docs/handoff/research-verification.md` (~220–260 dòng), theo khuôn `docs/handoff/router-settings.md`; có bảng sáu lượt chạy thật, bảng "những gì **chưa** làm được", rủi ro còn treo, và khối lệnh chạy nhanh. Câu chốt bắt buộc có nguyên văn: *vòng 29 chỉ chứng minh bằng unit test; nó KHÔNG chứng minh một lượt research thật giờ chạy xong*.
- **Năm sửa lỗi nhỏ đo được từ sáu lượt thật** (đợt này kèm theo, tất cả ghim được bằng unit test): (a) cổng chất lượng hồ sơ chỉ nhận vài từ khoá tiêu đề, bỏ oan mục "Kết luận chính"; (b) câu khắc phục "Thêm nguồn khác nguồn tin gốc" đọc thành "thêm một TRANG" trong khi luật thật là khác **HOST**; (c) thông báo `Invalid tool arguments` chỉ một dòng, không nói độ dài hay vị trí lỗi; (d) hợp đồng công cụ `research_brief` không mô tả tham số `ceilingSeconds` — bẫy đã giết lượt thật thứ năm. Đề nghị của kế hoạch **đã được chủ nhà chốt (6050)**: gộp (a)(b)(d) **và** (c), sửa (c) **ở chỗ gọi** để cây vendor Hermes giữ nguyên. Phát hiện (e) — nhánh con nhận `RESEARCH_GATE_NOTE` với tiêu chí hồ sơ mà nhánh con không có `dossier_write` để thoả — **vẫn treo**, vì chỉ lượt thật mới kiểm được.

**handoff2 (yêu cầu riêng của chủ nhà, 6050b).** Ngoài tài liệu kiểm nghiệm ở trên, vòng này ghi thêm **một tài liệu handoff thứ hai** để người hoặc agent khác tiếp nhận được khi chủ nhà hết hạn mức: `docs/handoff/v29-keyring-handoff.md`. Tài liệu này **tự chứa** toàn bộ kế hoạch vòng 29 (mục tiêu, bảng quyết định 6041–6053, sáu đợt việc, danh sách tệp và tên route, lệnh chạy, bất biến, việc còn treo) **và một bảng tiến độ** cập nhật ở từng mốc: việc nào xong, việc nào đang làm, việc nào chưa bắt đầu, kèm số đo mới nhất (số ca test, kết quả `npm test`, kết quả pytest). Khuôn mở đầu một câu: *"Đọc mục Tiến độ trước, rồi làm tiếp việc chưa xong theo đúng thứ tự."* Kèm theo đó, các kế hoạch con được chép vào repo ở `docs/plan/v29/**` để người tiếp nhận không phụ thuộc `/code/.plans/` ngoài repo.

### Đợt 5 — Một lần chạy tay trên máy chủ nhà

Chạy runbook R-5 đã viết ở đợt 1, khi mã đợt 1 đã sẵn sàng và **chủ nhà đồng ý** (runbook cần dừng/mở lại router — tiến trình của chủ nhà; tôi không tự đụng vào):

1. Sao lưu **cả thư mục** `~/.local/share/boxfox/router/` (`router.sqlite`, `-wal`, `-shm` và `master.key`) ra ngoài repo, mode `0600`. Không xoá/đổi `master.key`.
2. Chuyển khoá **phía máy chủ**: giữ `f8a5f4e8…` ("OpenCode Free (key 1)") làm connection sống sót; import khoá của `a43ff124…` (key 2) và `3d27b0b0…` (key 3) vào vòng khoá của nó; xử lý connection trùng `7c59f6b5…` ("OpenCode Free", đang `inferenceState: failed`) — **tắt trước, xoá sau** khi chủ nhà đã thấy đúng; xoá hai vỏ rỗng còn lại; đổi tên; trỏ lại `defaultRoute` và `BOXFOX_LIVE_CONNECTION_ID` (hôm nay đang mặc định về `7c59f6b5`).
3. Kiểm trên giao diện: provider `opencode` còn **một** connection đang bật với **ba** khoá; picker hiện **một hàng** cho `muse-spark-1.3-contributor-free`; chạy **một lượt thường** (không phải research) để chắc đường model còn sống.
4. Đường lùi: chép lại DB + `master.key` từ bản sao lưu, mở lại router, đối chiếu digest từng blob với bộ đã ghi trước khi migrate.

---

## 4. Kiểm thử

- **Router:** `cd router && npm test` (node ≥ 24) — bốn tệp test mới cho vòng khoá; các ghim cũ phải sửa đúng danh sách: `auth-cooldown.test.mjs:83-84/110/123-127/130` (hai map cũ bị bỏ) và `core.test.mjs:73` (connection một khoá nay nghỉ ngay ở 429 đầu). Mười một tệp test còn lại không đụng tới.
- **Backend:** bộ đơn vị hiện có (mốc gần nhất `343458e` ⇒ **1640 passed, 1 deselected**, 264 giây) + tệp mới `backend/tests/unit/test_provider_route.py` (luật gộp metadata, lưu route nguyên văn, `route_for` hiểu tiền tố provider, lượt đổi model vẫn đối chiếu mức).
- **Frontend:** `ProviderConnectionCard.test.tsx`, `providerStore.test.ts` cũ chạy lại; test mới cho `ConnectionKeyRing` (bốn trạng thái khoá, gộp khoá, chặn xoá khi còn khoá, **không** render secret) và cho picker (bốn connection ⇒ một dòng; hai connection ⇒ hai hàng con ghim; body phiên mang `providerId` + `modelId`).
- **Probe provider GIẢ hai tầng** (đợt 4) là bằng chứng offline đầu-cuối cho vòng khoá: 429 xoay, 400/5xx không xoay, nghỉ ≥ 30 giây và ≤ 2 phút, hết vòng thì một lỗi duy nhất.
- **Trên app thật (đợt 5):** ảnh chụp khối khoá ba dòng, picker một hàng, và một lượt thường chạy xong. Vòng này **không** chạy lượt research thật; `manifest.json` của bộ đo vẫn `measured: false`, nghiệm thu **C-7** vẫn mở, và **F19** vẫn cấm nói "đã có benchmark research".

---

## 5. Bất biến không được phá

- Router: khoá mã hoá-at-rest bằng master key sẵn có; **không** trả khoá thật ra frontend (chỉ prefix đã che và nhãn); không log khoá/payload thô; chỉ loopback; giữ nguyên kiểm tra `X-BoxFox-Admin: 1` + Origin/Host; `POST /api/router/connections` và `PATCH /:id` chỉ **thêm** (additive); `router/CONTRACT.md` cập nhật nếu route đổi.
- Harness: không đổi `/v1/chat/completions`, không đổi hình dạng wire của OpenCode Free, không thêm dependency; `failures.py` vẫn chỉ thử lại cùng connection.
- Cũ: D-44 (dạng câu trả lời cuối chỉ là gợi ý), D-18/F1 (không cho cổng chấm khuôn câu trả lời), hồ sơ `v<N>` bất biến, con research không có `file_write`/`research_write`, mọi thứ mới có cờ tắt.
- Vận hành: không restart/kill tiến trình chủ nhà (3100, 3101, 3102, …); không rebuild box; không cài gói trong box. Runbook đợt 5 là việc chủ nhà cho phép và chạy.

---

## 6. Ngoài phạm vi vòng này

- Lượt research thật và số đo `R1–R12` (quyết định 6045) — có giao thức sẵn ở đợt 4 để vòng sau chạy.
- Phát hiện (e): nhánh con `research` nhận tiêu chí hồ sơ mà nó không có quyền ghi — cần một lượt thật để kiểm.
- M6: router chưa trả trường `cost`; hai mục dọn nhỏ `v27e1-simplify`; bốn khoá `subagent*` trong `en.ts`.
- Nghỉ khoá là in-memory: restart router là mọi khoá về vòng ngay (ghi vào tài liệu, không sửa vòng này).
- Một số adapter ném 429 dưới `PROVIDER_ERROR` nên chưa xoay khoá được (ví dụ `openrouter`) — ghi nhận, không mở rộng vòng này.

---

## 7. Thứ tự chạy và quy mô

Đợt 1 (R-0 → R-1 → R-2 ∥ R-3 → R-4 → R-5) → Đợt 2 (giao diện key ring, sau khi R-3 chốt tên route) → Đợt 3 (song song với đợt 2 được: nửa backend không phụ thuộc UI) → Đợt 4 (độc lập, chạy song song được từ đầu) → Đợt 5 (sau khi đợt 1–3 xanh và chủ nhà đồng ý).

Tổng quy mô dự kiến: khoảng **3 000–3 300 dòng** trên khoảng **45 tệp**, trong đó khoảng **15 tệp mới** (router 6, giao diện 5, route 3, còn lại là probe và tài liệu), cộng tài liệu handoff và runbook. Đợt 4 độc lập với đợt 1–3 nên có thể chạy trước để có tài liệu handoff sớm.

---

## 8. Điều còn mở (không chặn thi công)

1. Nhánh provider của router có nên bỏ target đang nghỉ khi tính thứ tự xoay vòng (hiện chỉ bỏ qua lúc chạy) — vòng này để nguyên, ghi vào handoff2.
2. `snapshot.defaultRoute` có nên nhận dạng provider — vòng này để nguyên.
3. `RouterClient` đọc thêm biến `BOXFOX_ROUTER_URL` (một dòng, mặc định giữ 3101) để nối harness với router scratch — chỉ cần nếu muốn bằng chứng đầu-cuối đầy đủ ở tầng harness; nếu làm thì kèm một unit test.

Đã chốt trong lượt này, không còn mở: ngôn ngữ chữ mới là **tiếng Anh** (6051); gộp khoá là **một hành động chuyển tất cả khoá của nguồn** (6052); bỏ khoá cuối thì **connection ở lại** (6053); bốn lỗi nhỏ **được gộp** với (c) sửa ở chỗ gọi (6050).
