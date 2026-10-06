# Test E2E "Web Search API" — khoá tìm kiếm trong router (PART 2)

> **Trạng thái:** bốn tầng test đã chạy trên máy này ngày **2026-10-06** — router `305 xanh`, harness
> `263 xanh + 1 ca đỏ có sẵn từ `main`` (xem §1), frontend `32 xanh`, E2E **8/8 kịch bản tự động xanh**
> (+1 kịch bản chỉ in hướng dẫn) trên máy **không có** biến khoá nào. Phạm vi: người dùng dán khoá tìm kiếm trong
> **Settings → Provider → Web Search**, harness đọc khoá đó qua loopback và dùng nó **trước** các
> bậc còn lại; không cấu hình gì thì `web_search` vẫn chạy bằng đường built-in của PART 1.
>
> Bản ghi quyết định: [`docs/plan/builtin-search-default.md`](../plan/builtin-search-default.md) (§4 là hợp đồng giao diện).
> Hợp đồng HTTP của router: [`router/CONTRACT.md`](../../router/CONTRACT.md).
> Đường built-in không khoá (PART 1): [`docs/testing/builtin-search-e2e.md`](builtin-search-e2e.md).

## 1. Bốn tầng test

| Tầng | Lệnh (chạy từ gốc repo) | Cần gì | Kết quả đo 2026-10-06 |
|---|---|---|---|
| 1 — router | `cd router && npm test` | Node 24 | `305 passed, 0 failed` (6,7 s) — gồm `tests/search-providers.test.mjs` (10 ca) và `tests/search-http.test.mjs` (5 ca) |
| 2 — harness (đơn vị) | `cd backend && TMPDIR=/var/tmp PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/unit/test_search_credentials.py tests/unit/test_web_search_selected_source.py` | không mạng, không router | `22 passed` |
| 2b — harness (bộ liên quan) | thêm `test_search_pipeline.py test_searxng_provider.py test_search_failures.py test_health_search_status.py test_web_tools.py test_recovery_policy.py test_tool_recovery.py test_runtime_info.py` | như trên | `263 passed, 1 failed` — ca đỏ là **có sẵn từ `main`**, xem ghi chú dưới |
| 3 — frontend | `cd frontend && npx vitest run src/components/settings/SearchProviderPanel.test.tsx src/components/settings/ProviderView.test.tsx && npx tsc -b --noEmit` | `node_modules` | `32 passed` (14 ca mới + 18 ca cũ), `tsc` sạch |
| 4 — E2E xuyên hệ thống | `cd backend && TMPDIR=/var/tmp PYTHONPATH=src /var/tmp/boxfox-venv/bin/python ../scripts/e2e/search_provider_e2e.py` | Node 24; **không** mạng, **không** khoá | **`8/8 kịch bản tự động XANH`** (mã thoát 0, +1 thủ công), xem §3 |

Máy này dùng venv sẵn có thay cho `python3` trần:
`/var/tmp/boxfox-venv/bin/python` (có pytest 8.4.2). Trên máy khác cứ dùng `python3` sau khi cài
`backend/requirements.txt`.

**Ghi chú ca đỏ tầng 2b (trung thực):** `test_web_tools.py::test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`
đỏ với `AttributeError: 'types.SimpleNamespace' object has no attribute 'db'` tại
`agent_core/research_gateway.py:37`. Ca này **đã đỏ trên `main` @ `f8f33b3`** (ghi lại ở
[`docs/testing/builtin-search-e2e.md`](builtin-search-e2e.md) §1) ⇒ nợ có sẵn, không phải hồi quy của
PART 2. Đừng "chữa" nó bằng cách sửa `web.py`.

## 2. Khoá nằm ở đâu (mô hình bảo mật)

| Bề mặt | Chứa khoá thô? |
|---|---|
| `POST/PATCH/DELETE /api/router/search/providers…` | **không** — chỉ `prefix` (6 ký tự đầu + `…`) |
| `GET /api/router/search`, `GET /api/router/state` | **không** — chỉ `prefix` |
| Nhật ký router, bản ghi `search_provider` trong store | **không** — khoá nằm ở bảng `credentials` (AES-256-GCM, AAD = `search:<id>`) |
| `POST …/providers/:id/reveal` | **có** — chỉ khi người dùng bấm "Hiện" trong UI |
| `GET /api/router/search/resolve` | **có** — hợp đồng đọc của harness qua loopback (kèm header admin) |

Khoá thô **không bao giờ** vào prompt, vào payload `web_search`, hay vào dòng log nào. E2E kịch bản
3 và 8 khẳng định điều này bằng cách quét chuỗi khoá trên toàn bộ JSON trả về.

## 3. Tầng 4 — E2E 9 kịch bản (không cần khoá thật)

`scripts/e2e/search_provider_e2e.py` tự làm hết: mở máy chủ provider giả, mở router tạm ở cổng
**3199** với `BOXFOX_ROUTER_DATA_DIR` riêng, trỏ cả hai vào máy giả, chạy 9 kịch bản, rồi dọn tiến
trình con. Không chạm router thật ở 3101, không chạm mạng ngoài, và **không chạm DB thật** —
`BOXFOX_SEARCH_DB` được trỏ vào `BOXFOX_E2E_DIR` trước lời gọi `search()` đầu tiên (xem §3.1).

```
cd backend && TMPDIR=/var/tmp PYTHONPATH=src \
  /var/tmp/boxfox-venv/bin/python ../scripts/e2e/search_provider_e2e.py
```

Máy sạch (không một biến `*_API_KEY` nào) chạy đúng lệnh trên; muốn chắc thì gỡ luôn các biến khoá:

```
cd backend && env -u BRAVE_API_KEY -u BOXFOX_BRAVE_API_KEY -u TAVILY_API_KEY -u EXA_API_KEY \
  -u PARALLEL_API_KEY -u FIRECRAWL_API_KEY TMPDIR=/var/tmp PYTHONPATH=src \
  /var/tmp/boxfox-venv/bin/python ../scripts/e2e/search_provider_e2e.py
```

| # | Kịch bản | Khẳng định điều gì |
|---|---|---|
| 1 | `default_choice_uses_the_builtin_path` | không cấu hình gì ⇒ kết quả đến từ SearXNG, và **không** có lời gọi nào tới Brave |
| 2 | `a_saved_brave_key_is_resolved_and_used` | lưu khoá + chọn ⇒ harness gọi Brave với `X-Subscription-Token`, khoá thô không vào payload |
| 3 | `the_router_state_endpoint_never_leaks_the_key` | `GET /api/router/state` chỉ có `prefix`, không có khoá thô |
| 4 | `a_broken_selected_key_falls_through_to_the_builtin_path` | Brave trả 401 ⇒ nguồn **đã chọn** thật sự bị gọi, bậc built-in chạy tiếp và vẫn có kết quả; khi **mọi** bậc hỏng thì câu lỗi nêu tên `selected source 'brave'` |
| 5 | `the_cloudflare_entry_needs_account_and_key_and_maps_items` | thiếu `accountId` ⇒ 400; đủ ⇒ dùng Cloudflare và map `items[]` |
| 6 | `the_custom_entry_posts_the_query_with_the_stored_key` | mục `custom` POST truy vấn kèm `Authorization`, khoá không nằm trong thân bài |
| 7 | `removing_the_active_provider_returns_to_the_builtin_path` | xoá mục đang dùng ⇒ `activeProviderId: null` và tìm kiếm về built-in |
| 8 | `the_ui_contract_shapes_match` | cả 8 đường HTTP (gồm `PUT /active`) trả đúng hình dạng hợp đồng, `revision` tăng khi đổi lựa chọn; nút Kiểm tra chạm đúng endpoint giả; thiếu header admin ⇒ 403 |
| 9 | `a_real_key_smoke_test_is_manual_and_optional` | chỉ in hướng dẫn smoke test thủ công (§6) |

Script trả mã **≠ 0** nếu một kịch bản hỏng, và in `n/9 kịch bản HỎNG: <tên…>`. Kịch bản 9 chỉ **in**
hướng dẫn smoke test thủ công nên được đếm riêng: dòng cuối là
`8/8 kịch bản tự động XANH (+1 thủ công, chỉ in hướng dẫn)` — con số "tự động" mới là thứ có khẳng định.

### 3.1 Biến môi trường chỉ dùng cho test/E2E

Đây là **hook test, không phải API người dùng** — đừng đặt chúng trong deployment thật.

| Biến | Mặc định | Dùng cho |
|---|---|---|
| `BOXFOX_ROUTER_SEARCH_URL` | `http://127.0.0.1:3101/api/router/search/resolve` | trỏ harness sang router khác (E2E dùng cổng 3199) |
| `BOXFOX_SEARCH_SOURCE_TTL` | `15` (giây) | TTL cache "nguồn đã chọn" phía harness |
| `BOXFOX_SEARCH_REFRESH` | tắt | buộc đọc lại router mỗi lời gọi (test) |
| `BOXFOX_WEB_TEST_ALLOW_LOOPBACK` | tắt | nới `assert_public_url()` cho **riêng** loopback, để E2E gọi máy giả. Không đặt ⇒ loopback vẫn bị chặn (có test khẳng định) |
| `BOXFOX_{BRAVE,TAVILY,EXA,PARALLEL,FIRECRAWL,CLOUDFLARE,CUSTOM}_SEARCH_URL` | — | ghi đè base URL của từng chân provider. Riêng `BOXFOX_CUSTOM_SEARCH_URL` chỉ dùng khi mục `custom` **không** có endpoint riêng |
| `BOXFOX_E2E_DIR` | `/var/tmp/boxfox-e2e` | thư mục dữ liệu/router log của E2E |
| `BOXFOX_E2E_ROUTER_PORT` | `3199` | cổng router tạm của E2E |
| `BOXFOX_SEARCH_DB` | `~/BoxFox/harness/search.sqlite` | E2E **tự trỏ** biến này vào `BOXFOX_E2E_DIR`: bậc built-in gọi `record_response_health`, không tách DB thì mỗi lần chạy lại gieo hàng sức khoẻ giả vào DB thật (nuôi cầu dao ngắt engine) |

Ghi chú: `BOXFOX_SEARXNG_URL` là gốc **không** kèm `/search` — cả harness lẫn router tự nối `/search`
vào sau. Máy chủ giả phục vụ đúng đường đó ở `/searxng/search`.

### 3.2 Máy chủ provider giả

`scripts/e2e/fake_search_providers.py` là `ThreadingHTTPServer` trong thread, phục vụ 8 đường
(`/brave`, `/tavily`, `/exa`, `/parallel`, `/firecrawl`, `/cloudflare`, `/custom`, `/searxng/search`)
và ghi lại từng lời gọi (provider, method, path, truy vấn, header xác thực đã che, cờ "thân bài có
chuỗi bí mật"). Chạy lẻ để soi tay:

```
python3 scripts/e2e/fake_search_providers.py --port 0    # in ra: FAKE_READY <cổng>
curl "http://127.0.0.1:<cổng>/__calls"                   # nhật ký JSONL
curl -X POST "http://127.0.0.1:<cổng>/__reset"           # xoá nhật ký
```

Tham số diễn lỗi: `?status=401` (mọi mã HTTP), `?empty=1` (kết quả rỗng), `?shape=items` (trả
`items[]` kiểu Cloudflare) và `?shape=results` (mặc định).

## 4. Bật/tắt đường built-in so với nguồn đã chọn

| Cấu hình | Đường chạy |
|---|---|
| Không có mục nào trong tab Web Search | đúng như PART 1: `searxng` (tự host) → các chân ENV → `GENERAL_PROVIDERS` |
| Có mục **đang dùng** | nguồn đã chọn đứng **đầu** chuỗi; hỏng thì rơi xuống các bậc sau và câu lỗi cuối nêu tên nguồn đã chọn |
| `BOXFOX_SEARCH_PIPELINE=on` | **giới hạn v1 đã biết:** ống 10 bước chạy SearXNG và **không** áp dụng nguồn đã chọn |
| `BOXFOX_SEARCH_PIPELINE=auto` (mặc định) | ống 10 bước chỉ chạy khi `source="web"` ∧ SearXNG sống ∧ **chưa có cấu hình tường minh nào** (không ENV khoá, không mục nào được chọn). Có cấu hình ⇒ ống nhường đường cho chuỗi ưu tiên ở hai hàng trên |

Đổi mục đang dùng hay sửa khoá đều đẩy `revision` lên 1; harness đọc lại trong tối đa 15 giây
(`BOXFOX_SEARCH_SOURCE_TTL`). Router chết hoặc trả JSON hỏng ⇒ harness **không** ném lỗi: nó dùng
giá trị đã cache còn hạn, hết hạn thì coi như "Mặc định".

## 5. Chẩn đoán nhanh

| Triệu chứng | Kiểm tra |
|---|---|
| Tab báo "router chưa kết nối" | router phải là bản có `search` trong snapshot: `curl -s http://127.0.0.1:3101/api/router/state \| grep -c '"search"'` |
| Nút "Kiểm tra" báo lỗi mạng | `POST /api/router/search/providers/:id/test` không bao giờ ném ra ngoài — nó trả `ok:false` + `code` (`AUTH`/`RATE_LIMIT`/`TIMEOUT`/`UNAVAILABLE`) |
| Đã chọn khoá mà kết quả vẫn từ SearXNG | xem log harness: dòng `selected source '<id>'` phải xuất hiện; kiểm `BOXFOX_SEARCH_REFRESH=1` khi test |
| Muốn xem đúng chuỗi chân sẽ chạy | `GET /api/agent/health?probe=search` — mục `search.legs` báo chuỗi **thật**, không phải thứ tự tĩnh |

## 6. Smoke test với khoá thật (thủ công, tùy chọn)

Không có bước nào trong CI chạm khoá thật. Khi có khoá thật và muốn xác nhận đầu-cuối:

1. Mở **Settings → Provider → Web Search**, chọn thẻ provider, dán khoá, bấm **Lưu**.
2. Bấm **Kiểm tra** trên đúng thẻ đó ⇒ kỳ vọng `ok: true` kèm `latencyMs` và một `sample` trích từ
   kết quả thật. `ok: false` kèm `code: AUTH` nghĩa là khoá sai/hết hạn — sửa lại ở bước 1.
3. Chọn thẻ đó làm nguồn đang dùng (**Chọn dùng**).
4. Hỏi agent một câu cần tìm web, rồi xem log harness: phải có dòng `selected source '<id>'` và
   `provider=<id>` trong dòng kết quả.
5. Xong thì bấm **Xoá** để trả về đường built-in không khoá (kịch bản 7 đã kiểm đúng hành vi này).

Riêng **Cloudflare Web Search** cần cả **Account ID** lẫn token; **custom** cần endpoint (khoá là
tuỳ chọn). Hai trường này nằm trong cùng hộp thoại, do `requires`/`optional` của catalog quyết định.
