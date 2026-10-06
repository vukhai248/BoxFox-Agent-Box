# Bản ghi quyết định — tìm kiếm web built-in không khoá (PART 1)

> **Trạng thái:** đã thi công trong cây làm việc nhánh `vorflux/web-search-builtin` (nền `main` @
> `f8f33b3`), ngày **2026-10-06**; chờ commit.
>
> **Phạm vi:** PART 1 của kế hoạch "Cải tổ Web Search" — `web_search` **chạy được ngay khi cài, không
> cần khoá API bên thứ ba**, vá lỗi F05, thêm bề mặt quan sát + bộ test E2E không cần khoá. PART 2
> (tab **Settings → Providers → Web Search**, khoá do người dùng nhập) do phần việc khác làm; §4 là
> **hợp đồng giao diện** hai phần phải khớp y hệt.
>
> **Nguồn:** kế hoạch chi tiết `/code/.plans/parts/p1-builtin-search.md`; hợp đồng PART 2
> `/code/.plans/parts/p2-search-provider-ui.md`. Tài liệu liên quan:
> [`docs/research/host-web-tools.md`](../research/host-web-tools.md) §2.2/§3 (số đo nhà cung cấp),
> [`docs/testing/builtin-search-e2e.md`](../testing/builtin-search-e2e.md) (ba tầng test + bench),
> [`deploy/searxng/README.md`](../../deploy/searxng/README.md) (vận hành).

## 1. Vấn đề

1. **Đường mặc định cũ không chạy.** `source="web"` đi qua Firecrawl **không khoá**; đo 06/10/2026
   dịch vụ trả **403/429** liên tục, nên "tìm web" coi như không có — khi chưa cấu hình gì.
2. **F05 (`docs/plan/Work-Graph-fix.md`, hàng F05, "Đã xác nhận bằng CUA"):** payload `web_search`
   hợp lệ, Firecrawl 403, SearXNG/Brave/Tavily chưa cấu hình, mà hint lỗi vẫn bảo *"sửa input và gọi
   lại"* ⇒ agent **đốt bước** thử truy vấn khác trên cùng hạ tầng chết. Đây không phải lỗi tiếng Việt
   trong truy vấn.
3. **Câu kết luận cũ bị phủ định một phần.** `docs/research/host-web-tools.md` §2.1 chốt *"không có
   máy tìm kiếm web tổng quát nào miễn phí và không khoá mà đáng tin"* — đúng cho **instance công
   khai** (8 instance + HTML front-end: 429/bot check/403), nhưng **sai cho SearXNG tự host trên
   loopback** (đo 06/10/2026: `/healthz` 200 `OK`, có kết quả thật, không khoá).

## 2. Quyết định đã chốt (không mở lại)

| # | Quyết định | Hệ quả trong mã |
|---|---|---|
| D1 | **Tự dò** SearXNG ở `http://127.0.0.1:8888` khi `BOXFOX_SEARXNG_URL` trống; đổi bằng `BOXFOX_SEARXNG_AUTODETECT_URL`, tắt bằng `BOXFOX_SEARXNG_AUTODETECT=off` | `search_pipeline.resolved_searxng_url()`; env **luôn thắng** tự dò; bật SearXNG xong không cần khởi động lại harness |
| D2 | Đầu dò là `GET /healthz` (rẻ, **không** gọi engine bên ngoài), đường lùi `GET /config`; cache dương 30 s / âm 15 s; lời gọi thật hỏng ⇒ xoá cache dương để dò lại | `probe_searxng()`, `note_searxng_failure()`; hằng số ở `agent_core/limits.py` |
| D3 | **Ống 10 bước thành mặc định có điều kiện** (`BOXFOX_SEARCH_PIPELINE` ba trạng thái `off\|on\|auto`, mặc định `auto`): chỉ bật khi `source="web"` ∧ SearXNG sống ∧ **không** cấu hình tường minh (không nguồn chọn ở Settings, không khoá env) | `pipeline_mode()` (mới) + `pipeline_enabled()` (giữ nghĩa cũ cho nhánh `papers`); `web._pipeline_applies()` |
| D4 | Ống không ra kết quả ⇒ **rơi xuống chuỗi còn lại một lần**, payload ghi `searchFallback`; mã lỗi cuối do đường chuỗi phân loại | `WebTools.search()` bắt `WebError` của ống và đi tiếp; `searchFallback = {from:'pipeline', code:…}` |
| D5 | Hai mã lỗi: `WEB_SEARCH_UNAVAILABLE` (đã có, thêm `details.searchFailure.kind` = `config\|infra\|source`) và `WEB_SEARCH_EMPTY` (**mới**); "truy vấn sai" **không** phải mã mới (đã có `WEB_URL_INVALID`/`TOOL_ARG_INVALID`) | `agent_core/search_failures.py` (mới): `classify()`, `message_for()`, `log_line_for()` |
| D6 | **Không đổi `GENERAL_PROVIDERS`** và không dựng chuỗi động trong PART 1 — chuỗi động là việc của PART 2 (`_search_chain()`); `test_searxng_is_the_first_general_provider` phải tiếp tục xanh | tuple `(searxng, firecrawl, brave, tavily, exa, parallel)` giữ nguyên |
| D7 | Ops: mặc định `deploy/searxng` chuyển sang **port-mapping** `127.0.0.1:8888:8888` + `bind_address: "0.0.0.0"` trong container; thêm `up.sh`; `network_mode: host` thành khối chú thích có cảnh báo trap | `deploy/searxng/{docker-compose.yml,settings.yml,up.sh,probe.py,README.md}` |
| D8 | Quan sát ở `GET /api/agent/health` khối `search` (rẻ, **không gọi mạng**; `?probe=search` mới dò thật) + khối `search` trong `runtime-info`. **Không** làm UI trong PART 1 | `api/server.py`, `web.search_status()`, `search_pipeline.search_status()` |
| D9 | E2E: test stub loopback chạy mặc định; test với container thật **tự skip** khi vắng; `bash deploy/searxng/up.sh` là cách bật chuẩn | `backend/tests/integration/test_search_searxng_{stub,live}.py`; `docs/testing/builtin-search-e2e.md` |

### Vì sao `auto` (thay vì bật ống vô điều kiện)

- Ca chính là "cài xong là tìm được, không khoá" — đúng ca đó **chưa có gì cấu hình**, nên đây là chỗ
  duy nhất `auto` bật ống mà không phá thứ tự ưu tiên nào.
- Bật ống vô điều kiện sẽ chạy **trước** bậc 1 (Settings) và bậc 2 (khoá env) — sai hợp đồng §4.1.
  `auto` tự tắt khi có cấu hình tường minh.
- Người đã có khoá không phải chịu thêm độ trễ của 6 biến thể truy vấn.
- **Công tắc giết:** `BOXFOX_SEARCH_PIPELINE=off` (một dòng env, không cần build lại).
- `pipeline_enabled()` giữ nguyên nghĩa "đặt tường minh = `on`" cho nhánh học thuật
  (`_provider_papers_first`) ⇒ `test_papers_leg_*` không đổi.

## 3. Luồng

```
WebTools.search(source="web")
        │
        │  _pipeline_applies(source)?
        │    off  → không bao giờ
        │    auto → source=="web" ∧ SearXNG sống ∧ KHÔNG cấu hình tường minh
        │    on   → source=="web" (chạy trước cả bậc 1/2)
        ▼
  ┌──────────────────┐   không kết quả / lỗi
  │  ống 10 bước     │ ───────────────────────────► rơi xuống chuỗi còn lại MỘT lần
  │  (SearXNG)       │                              payload.searchFallback = {from:'pipeline', code:…}
  └────────┬─────────┘
           │ có kết quả
           ▼
     trả payload (kèm khối pipeline: steps/enginesUsed/…)

Không dùng ống (off, hoặc auto không đủ điều kiện) ⇒ chuỗi GENERAL_PROVIDERS:
    searxng → firecrawl → brave → tavily → exa → parallel
           │
           ├─ có hàng ⇒ trả payload
           └─ hết ⇒ phân loại cuối cùng:
                • mọi chân trả danh sách rỗng, không chân nào ném  ⇒ WEB_SEARCH_EMPTY
                • có ≥1 backend cấu hình mà mọi chân ném          ⇒ WEB_SEARCH_UNAVAILABLE (kind=infra)
                • không cấu hình gì, SearXNG không có (env+tự dò) ⇒ WEB_SEARCH_UNAVAILABLE (kind=config)
                • source != 'web'                                 ⇒ WEB_SEARCH_UNAVAILABLE (kind=source)
```

## 4. Hợp đồng giao diện (PART 2 phải khớp y hệt)

### 4.1 Thứ tự phân giải nguồn (chốt cứng)

| Bậc | Nguồn | Ai hiện thực | Ghi chú |
|---|---|---|---|
| 1 | Nguồn người dùng chọn trong **Settings → Provider → Web Search** (và có credential) | PART 2 (`search_credentials.active_source()`, `_search_chain()`) | Đứng đầu chuỗi; hỏng thì rơi tiếp |
| 2 | **ENV khoá**: `BRAVE_API_KEY`/`BOXFOX_BRAVE_API_KEY` → `TAVILY_API_KEY` → `EXA_API_KEY` → `PARALLEL_API_KEY` → `FIRECRAWL_API_KEY` | PART 2 kéo lên trước bậc 3; PART 1 không đổi | Hành vi cũ vẫn nguyên nghĩa |
| 3 | **SearXNG tự host** khi có URL (env `BOXFOX_SEARXNG_URL` → nguồn chọn `searxng` (PART 2) → **tự dò** `127.0.0.1:8888`) | PART 1 (tự dò + chân `_provider_searxng`) | Khi ống bật, ống **hiện thực** bậc này |
| 4 | **Firecrawl không khoá** | PART 2 (vị trí trong chuỗi) + PART 1 (phân loại lỗi) | Chân cuối luôn có mặt |
| 5 | **Lỗi đã phân loại** `WEB_SEARCH_UNAVAILABLE` (+ `WEB_SEARCH_EMPTY` cho ca rỗng) | **PART 1** | Bảng §4.2 |

Đường ống 10 bước (`BOXFOX_SEARCH_PIPELINE=auto|on|off`, mặc định `auto`):

- `auto` ⇒ ống chỉ thay bậc 3 khi `source="web"` ∧ SearXNG sống ∧ **không** cấu hình tường minh (không
  bậc 1, không bậc 2). Nhờ vậy bậc 1/2 luôn thắng ống.
- `on` ⇒ ống chạy trước cả bậc 1/2 cho `source="web"` (giới hạn v1 đã ghi ở PART 2 §Rủi ro R2).
- `off` ⇒ công tắc giết: không bao giờ dùng ống; chuỗi `GENERAL_PROVIDERS` chạy như hiện tại.
- Ống không ra kết quả ⇒ rơi xuống **phần còn lại của chuỗi** một lần (kể cả bậc 4), payload ghi
  `searchFallback`; lỗi cuối do đường chuỗi phân loại.
- `pipeline_enabled()` giữ nghĩa cũ (`mode == 'on'`) cho nhánh `papers` — hành vi nhóm học thuật không đổi.

### 4.2 Bảng mã lỗi + phân loại (F05)

| Ca | Điều kiện nhận biết (không đoán mò) | Mã | `searchFailure.kind` | Câu chữ bắt buộc có |
|---|---|---|---|---|
| Chưa cấu hình gì | không khoá env, không nguồn chọn, SearXNG không có (env + tự dò đều rỗng) | `WEB_SEARCH_UNAVAILABLE` | `config` | "not a query problem"; cách bật: `deploy/searxng/up.sh`, `BOXFOX_SEARXNG_URL`, danh sách biến khoá thiếu, `Settings → Provider → Web Search` |
| Backend có cấu hình nhưng hỏng | có ≥ 1 backend cấu hình/được chọn mà mọi chân đều ném (refused/timeout/5xx) | `WEB_SEARCH_UNAVAILABLE` | `infra` | "backend problem, not a query problem"; tên backend + URL + lý do (`errors[:3]`); `deploy/searxng/probe.py`; "do not retry the same search" |
| Backend trả lời nhưng 0 hàng | mọi chân trả danh sách rỗng, không chân nào ném (`NO_PROVIDER_ANSWERED`) | `WEB_SEARCH_EMPTY` | — | "returned no rows"; nới/đổi truy vấn **một lần** hoặc đổi nguồn; không lặp y hệt |
| Truy vấn sai (rỗng/quá dài/`count` sai) | `_search_queries`/`_validate` bắt trước khi gọi mạng | `WEB_URL_INVALID` / `TOOL_ARG_INVALID` (đã có) | — | sửa đúng trường — **không** đổi |
| Nguồn cụ thể hỏng (`source="wikipedia"`, `"github"`, …) | `source != 'web'` | `WEB_SEARCH_UNAVAILABLE` | `source` | tên nguồn + lý do; gợi ý nguồn khác; không lặp y hệt |

Quy tắc chung: **không** mã mới nào rơi vào `unknown` của `recovery_policy` (đã khai `capability_gap`
+ `WEB_SEARCH_UNAVAILABLE`/`WEB_SEARCH_EMPTY`); mọi thông báo gửi model giữ nguyên quy ước
`WebError(code, message, log_message)` — bản `log_message` **không** chứa truy vấn/URL; `details` được
runtime hợp nhất vào phong bì công cụ nên model thấy `kind`.

### 4.3 Hình dạng dữ liệu

```json
// Phong bì lỗi công cụ (model thấy)
{ "is_error": true, "errorCode": "WEB_SEARCH_UNAVAILABLE",
  "error": "Every configured web-search backend failed: searxng (http://127.0.0.1:8888): connection refused. This is a backend problem, not a query problem — do not retry the same search. …",
  "searchFailure": { "kind": "infra", "source": "web", "backends": ["searxng"],
                     "missing": [], "attempts": 2 },
  "reflection_hint": "AUTONOMOUS_DIAGNOSIS: …",
  "recovery": { "class": "capability_gap", "action": "checkpoint_and_ask", "replay": false } }

// payload thành công khi rơi từ ống xuống chuỗi
{ "results": [ … ], "count": 3, "searchFallback": { "from": "pipeline", "code": "WEB_SEARCH_UNAVAILABLE" } }

// GET /api/agent/health (khối mới, rẻ, không gọi mạng)
{ "status": "ok", "service": "boxfox-harness", "version": "…",
  "search": { "source": "searxng", "selected": null,
              "searxng": { "url": "http://127.0.0.1:8888", "origin": "autodetect",
                           "reachable": true, "checkedAt": 1759744800.0 },
              "pipeline": { "mode": "auto", "applies": true },
              "keys": { "brave": false, "tavily": false, "exa": false, "parallel": false, "firecrawl": false },
              "engines": [ { "engine": "brave", "ok": 0, "empty": 0, "blocked": 3, "timeouts": 0,
                             "suspendedUntil": 1759745100 } ],
              "fallback": ["firecrawl-keyless"] } }
```

### 4.4 Điểm giao với PART 2 (không được lệch)

| Hạng mục | Chốt | Ai làm |
|---|---|---|
| `GENERAL_PROVIDERS` | **Không đổi** `(searxng, firecrawl, brave, tavily, exa, parallel)`; `test_searxng_is_the_first_general_provider` tiếp tục xanh | Cả hai: không chạm tuple |
| `_search_chain()` (chuỗi động theo bậc 1/2) | PART 2 sở hữu; PART 1 **không** dựng chuỗi động | PART 2 |
| `searxng_search(..., base_url=None)` | PART 1 cung cấp — PART 2 khỏi thêm | PART 1 |
| `search_credentials.searxng_url()` / `.active_source()` | Ưu tiên số 1 cho URL của chân SearXNG; `active_source()` là nguồn sự thật cho "có cấu hình tường minh không" (quyết định `auto`). PART 1 đọc **mềm** (module chưa tồn tại ⇒ bỏ qua, không lỗi) | PART 2 |
| `sp.searxng_url()` | Nay = env → **tự dò**; PART 2 gọi `creds or sp.searxng_url()` vẫn đúng ý | PART 1 |
| Thông báo lỗi cuối + phân loại F05 | PART 1 sở hữu toàn bộ; con trỏ `Settings → Provider → Web Search` do PART 1 đặt trong `message_for` ⇒ **PART 2 bỏ bước 9 của task 4** (tránh lặp) | PART 1 |
| Dòng `selected source '<id>' failed` | PART 2 thêm vào chuỗi lý do; PART 1 chỉ in `errors[:3]` nên nó tự có mặt | PART 2 |
| `_search_leg` | **Không đổi chữ ký** (vẫn trả `(results, failure)`), chỉ đổi giá trị sentinel khi mọi chân rỗng | PART 1 |
| `WebTools.search()` | Cả hai cùng sửa: PART 1 đổi khối `if pipeline…` + khối dựng lỗi cuối; PART 2 đổi dòng `providers = …` + `_search_cache_key(selection=…)`. **Land PART 1 task 1–3 trước**, PART 2 rebase | Cả hai |

## 5. Số đo 2026-10-06 (máy này, không khoá)

| # | Phép đo | Kết quả |
|---|---|---|
| E1 | Đường mặc định cũ (Firecrawl không khoá) | 403/429 — đúng F05; harness không có khoá nào |
| E2 | Trước khi làm: SearXNG chạy chưa? | **Chưa** (không ai nghe cổng 8888; image `searxng/searxng:latest` chưa có, đã kéo được) |
| E3 | `docker compose` với `network_mode: host` trong sandbox | **Không bind được** — `RuntimeError: Address already in use (os error 98)` từ `granian._init_shared_socket()` |
| E4 | Dựng lại bằng port-mapping (`127.0.0.1:8888:8888` + `bind_address: 0.0.0.0`) | Container `boxfox-searxng` lên, `GET /search?q=…&format=json` = **200** |
| E5 | `deploy/searxng/probe.py` (không khoá) | mã thoát **0**; `google cse` 14 hàng + `bing` 10 hàng; `brave` "Suspended: too many requests"; `duckduckgo`/`qwant` CAPTCHA |
| E6 | Ống 10 bước + SearXNG thật, không khoá | **5 kết quả trong 0,3 s** (`BOXFOX_SEARCH_PIPELINE=on`) |
| E7 | `_provider_searxng` (chuỗi cũ), không khoá | **5 hàng trong 0,2 s**, `provider=searxng` |
| E8 | `GET /healthz` của image `latest` | **200 `OK`** — dùng làm đầu dò tự dò |
| E9 | `searxng_search` gọi thẳng | **251 ms**, **3 hàng** |
| E10 | 8 instance SearXNG công khai + HTML front-end | 429 / bot check / 403 ⇒ **loại** |
| E11 | Ba tầng test (chi tiết ở `docs/testing/builtin-search-e2e.md`) | đơn vị 140 xanh + 1 ca đỏ **có sẵn từ `main`**; stub **4 xanh**; live **5 xanh** (khi container vắng: 5 skip) |
| E12 | Đo tối thiểu độ trễ (10 truy vấn đầu `split=test`, không LLM) | `auto`: p50 239,7 ms / p95 551,0 ms, 0 lỗi, 10/10 qua ống; `off`: p50 273,7 ms / p95 324,8 ms, 0 lỗi — **chưa kết luận được ống đắt hơn hay rẻ hơn** (mẫu 3 truy vấn trước đó cho hướng ngược lại) |

## 6. Vận hành & công tắc giết

| Việc | Lệnh / chỗ |
|---|---|
| Bật SearXNG (chuẩn) | `bash deploy/searxng/up.sh` (chờ `/healthz` ≤30 s rồi chạy `probe.py`) |
| Instance thứ hai | `SEARXNG_PORT=8899 bash deploy/searxng/up.sh` (tên `boxfox-searxng-8899`) |
| Kiểm sâu theo engine | `python3 deploy/searxng/probe.py [--json]` — mã thoát 0/2/3 |
| Trạng thái trong harness | `GET /api/agent/health` khối `search`; `?probe=search` để dò lại ngay |
| **Công tắc giết** | `BOXFOX_SEARCH_PIPELINE=off` — không bao giờ dùng ống; chuỗi cũ chạy như trước |
| Tắt tự dò | `BOXFOX_SEARXNG_AUTODETECT=off`; hoặc trỏ tay bằng `BOXFOX_SEARXNG_URL` |

## 7. Giới hạn / việc còn lại (nói thẳng)

- **R2 (độ trễ `auto`):** cổng quyết định giữ `auto` vẫn là số đo; E12 chưa phân định được ống so với
  đường cũ (hướng đảo theo cỡ mẫu). Muốn chốt thì chạy `scripts/eval/search_bench.py` (cần cổng chi
  tiêu) — xem `docs/testing/builtin-search-e2e.md` §5.
- **Engine ngoài luôn đổi:** `brave`/`duckduckgo`/`qwant`/`google` hỏng theo IP và theo ngày; đừng lấy
  bảng E5 làm ngưỡng cứng. `/healthz` là đặc trưng của image `searxng/searxng` hiện tại; image đổi thì
  đường lùi `/config` hoặc đặt `BOXFOX_SEARXNG_URL` là xong.
- **Không có UI trong PART 1** (D8): trạng thái chỉ có ở API; hiện lên tab Settings là việc của PART 2
  (thiết kế đã có ở `/code/.plans/designs/web-search-*.html`).
- **Hai thứ nhỏ thêm ngoài kế hoạch, có lý do:** compose nhận `BOXFOX_SEARXNG_CONTAINER`, và `up.sh` tự
  đặt tên `boxfox-searxng-<cổng>` khi `SEARXNG_PORT != 8888` — vì máy này đã có container thật
  `boxfox-searxng` ở cổng 8888, không thể test cổng thứ hai nếu dùng chung tên.
- `backend/src/agentbox/api/server.py` trong diff còn một lần đổi CRLF→LF toàn tệp **không liên quan**
  tìm kiếm; đừng gán nó cho PART 1 khi soát diff.
