# SearXNG tự host cho BoxFox (P0b)

Thư mục này chạy **SearXNG trên HOST** — không phải trong box. Từ 02/10/2026 compose đặt
`BOX_DEFAULT_NETWORK: "on"` (quyết định chủ máy, cho verify_exec/reviewer xác nhận nguồn), nên
lý do giữ SearXNG ở host bây giờ là **chính sách**: truy vấn tìm kiếm đi từ host và chỉ văn bản
đã trích mới qua ranh giới vào box, không phụ thuộc trạng thái mạng của box.

Lớp tìm không khoá 10 bước (kế hoạch v2 §5.4.1) dùng SearXNG làm nguồn chính, gộp nhiều engine rồi
xếp hạng lại để tiệm cận chất lượng Brave **mà không cần khoá nào**. Từ 06/10/2026 harness **tự
dò** instance này ở `127.0.0.1:8888`, nên bật xong là dùng được ngay.

## 1. Chạy

Ảnh `searxng/searxng:latest` đã được kéo sẵn trên máy này.

```bash
# Khuyến nghị: bật + chờ sẵn sàng + kiểm engine + in URL dùng được
bash deploy/searxng/up.sh

# Thủ công
docker compose -f deploy/searxng/docker-compose.yml up -d
docker compose -f deploy/searxng/docker-compose.yml logs -f
docker compose -f deploy/searxng/docker-compose.yml down
```

**Mặc định = port-mapping** `127.0.0.1:8888:8888`: chỉ loopback của HOST được publish nên
**không lộ ra LAN**; trong container instance bind `0.0.0.0` (xem `settings.yml`).

Đổi cổng: `SEARXNG_PORT=8899 bash deploy/searxng/up.sh` — biến này điều khiển cả vế publish lẫn
cổng granian trong container; `up.sh` đổi **cả tên dự án compose** (`boxfox-searxng-8899`) lẫn tên
container (`boxfox-searxng-8899`) để lần chạy cổng khác **không tái tạo** instance mặc định — compose
đối chiếu theo dự án + dịch vụ, chỉ đổi tên container là chưa đủ. Đổi tên dự án: `BOXFOX_SEARXNG_PROJECT`.

> **Đã đo 2026-10-06 (hai cái bẫy thật, ghi lại để lần sau không mất thời gian):**
> 1. Ảnh `searxng/searxng:latest` mở cổng **8080** của granian và **không đọc `server.port`**
>    trong `settings.yml` — `SEARXNG_PORT` mới là nút thật (compose đặt sẵn). Thiếu biến này thì
>    cổng 8888 không có ai nghe: `ss` vẫn thấy cổng LISTEN do docker-proxy, nhưng mọi lời gọi
>    trả `Recv failure: Connection reset by peer`. Đây **không** phải lỗi của harness.
> 2. Trong sandbox này `network_mode: host` **không bind được** (`RuntimeError: Address already in
>    use (os error 98)` từ `granian._init_shared_socket()`, dù `ss` không thấy ai giữ cổng), nên
>    từ 06/10/2026 **mặc định là port-mapping**; biến thể host networking chỉ còn là khối chú
>    thích ở cuối `docker-compose.yml` (kèm cách đổi `bind_address` về `127.0.0.1` nếu dùng lại).
>
> `up.sh` chờ `/healthz` = `OK` tối đa 30 s (dò bằng `python3`, không cần `curl`), rồi chạy
> `probe.py` để lấy phán quyết sâu; thất bại thì in 40 dòng log cuối của compose.

Hai dòng `ERROR` lúc khởi động cho `ahmia` và `torch` là **tiếng ồn của ảnh gốc** (engine onion
mặc định của SearXNG: `ahmia` cần Tor, `torch.py` không còn trong ảnh). Sau hai dòng đó, log chỉ
còn `[INFO] Started worker-1`. Ở **port-mapping**, mỗi địa chỉ nguồn mới còn sinh một dòng
`ERROR:searx.botdetection: X-Forwarded-For nor X-Real-IP header is set!` — docker-proxy che IP thật
của client; vô hại khi `limiter: false` (chỉ harness gọi), nhưng có thì biết vì sao.

`settings.yml` được mount **chỉ đọc**.

## 2. Trỏ harness vào instance (thường KHÔNG cần gì)

Harness **tự dò** `http://127.0.0.1:8888` khi `BOXFOX_SEARXNG_URL` trống: bật SearXNG xong là
`web_search` dùng được — **không cần đặt biến môi trường, không cần khởi động lại harness** (tự
nhận trong ≤30 s; cache dò dương 30 s / âm 15 s). Env luôn **thắng** tự dò.

| Biến | Mặc định | Dùng cho |
|---|---|---|
| `BOXFOX_SEARXNG_URL` | (rỗng — tự dò) | ghi đè địa chỉ instance |
| `BOXFOX_SEARXNG_AUTODETECT` | bật | `off/0/false/no` ⇒ tắt tự dò |
| `BOXFOX_SEARXNG_AUTODETECT_URL` | `http://127.0.0.1:8888` | đổi địa chỉ tự dò |
| `BOXFOX_SEARCH_PIPELINE` | `auto` | `auto\|on\|off` — điều khiển đường ống 10 bước |

**Ống 10 bước**: `auto` (mặc định) chỉ chạy khi `source="web"` ∧ SearXNG sống ∧ **không** có cấu
hình nguồn tường minh (nguồn chọn trong Settings / khoá env). `on` = ép chạy ống trước cả nguồn
chọn, **vẫn cần SearXNG sống** (không có thì ống không chạy và health báo `applies: false`);
`off` = không bao giờ dùng ống (công tắc giết một dòng). `pipeline_enabled()` giữ nghĩa cũ
cho nhánh `papers`.

## 3. Kiểm tra mức sẵn sàng

`bash deploy/searxng/up.sh` đã tự chạy probe ở cuối. Chạy riêng:

```bash
python3 deploy/searxng/probe.py                          # bản người đọc
python3 deploy/searxng/probe.py --json                   # JSON cho up.sh/E2E
BOXFOX_SEARXNG_URL=http://127.0.0.1:8888 python deploy/searxng/probe.py
```

Probe gọi vài truy vấn thử, in **số kết quả theo từng engine**, danh sách `unresponsive_engines`
(engine bị CAPTCHA/403/429/hết giờ) và một lời gọi riêng `engines=brave` (nền proxy Brave của 8.7).
`--json` in **cùng thông tin** dưới dạng một đối tượng JSON: `engines` (số hàng theo engine),
`unresponsive_engines`, `latency_ms`, khối `brave`, `verdict` (`results|empty|unreachable`).
Mã thoát: `0` có kết quả · `2` instance sống nhưng rỗng · `3` không kết nối được.

Trạng thái trong harness: **`GET /api/agent/health`**, khối `search` (rẻ, **không gọi mạng**; thêm
`?probe=search` mới dò thật):

```json
{ "search": { "source": "searxng", "selected": null,
              "searxng": { "url": "http://127.0.0.1:8888", "origin": "autodetect", "reachable": true },
              "pipeline": { "mode": "auto", "applies": true },
              "keys": { "brave": false, "tavily": false, "exa": false, "parallel": false, "firecrawl": false },
              "engines": [ { "engine": "brave", "blocked": 3, "suspended_until": 1759745100,
                             "suspended": false, "fails_streak": 3, "p50_ms": 210 } ],
              "fallback": ["firecrawl-keyless"] } }
```

**Kết quả đo thật trên máy này (2026-10-06, `probe.py`, không khoá):**

| Engine | Kết quả đo |
|---|---|
| `google cse` | 14–20 kết quả (nguồn chính hôm nay) |
| `bing` | 10 kết quả |
| `brave` | **"Suspended: too many requests"** (429) — tạm ngưng, không dùng được lúc đo |
| `google` | "Suspended: access denied" (403) lúc đo |
| `duckduckgo`, `qwant` | **CAPTCHA** — không dùng được từ IP trung tâm dữ liệu |

`GET /healthz` của image `latest` trả `200 OK` — dùng làm đầu dò tự dò. Bộ luân phiên bước 7 tự bỏ
qua engine hỏng, nên lượt tìm vẫn chạy: ống 10 bước với SearXNG thật trả **5 kết quả trong 0,3 s**;
chân `_provider_searxng` (đường chuỗi cũ) **5 hàng trong 0,2 s**.

## 4. Khi SearXNG không chạy

**Hệ thống không sập.** Harness rơi xuống bậc kế tiếp của chuỗi tìm (mặc định là Firecrawl không
khoá) và chỉ báo lỗi khi mọi bậc đều hỏng — lỗi được **phân loại** để agent không đốt bước:

* `WEB_SEARCH_UNAVAILABLE` + `searchFailure.kind`:
  * `config` — chưa cấu hình gì và SearXNG không có (env + tự dò đều rỗng): thông báo nêu cách bật
    (`bash deploy/searxng/up.sh`, `BOXFOX_SEARXNG_URL`) — **không** xui sửa truy vấn;
  * `infra` — có backend nhưng mọi chân đều ném: nêu tên backend + lý do, gợi ý `probe.py`;
  * `source` — nguồn cụ thể hỏng (`source="wikipedia"`, …).
* `WEB_SEARCH_EMPTY` — backend trả lời nhưng 0 hàng: được phép nới/đổi truy vấn **một lần**.

Bật lại: `bash deploy/searxng/up.sh` (hoặc `docker compose ... up -d`). Instance chạy cổng khác
8888 thì đặt `BOXFOX_SEARXNG_AUTODETECT_URL` (hoặc `BOXFOX_SEARXNG_URL`) cho khớp.

## 5. Giới hạn riêng tư (nói thẳng)

Những gì cấu hình này **làm được**:

* Cổng chỉ publish trên **loopback của host** (`127.0.0.1:8888`); trong container bind `0.0.0.0`
  nhưng không có đường nào từ LAN tới (không publish ra `0.0.0.0`). `public_instance: false` và
  `limiter: false` (chỉ harness gọi, không có người lạ; limiter còn cần thêm Valkey và dành cho
  máy công khai).
* Harness chỉ gọi instance qua loopback (tự dò `127.0.0.1:8888`).
* **Không lưu truy vấn**: `general.debug: false`, log mức `WARNING`, không đặt reverse proxy có
  access log. SearXNG không có telemetry gửi ra ngoài.
* `enable_metrics: true` chỉ giữ **số đếm engine trong máy** cho bước 7 (sức khoẻ/ngưng engine).
* `search.autocomplete: ""` — tắt gợi ý để không gửi chữ đang gõ dở ra ngoài.
* Phía harness, truy vấn chỉ nằm trong SQLite cục bộ (`research_search_log`, `research_search_cache`)
  và bị xoá cùng phiên; không gửi đi đâu.
* Không đặt email/tên người trong user-agent.

**Điều KHÔNG che được — và không nên giả vờ che:** SearXNG là metasearch; mỗi engine bên ngoài
(Brave, Google, Bing, DuckDuckGo, Mojeek, Qwant, Startpage, Wikipedia…) **vẫn thấy truy vấn và địa
chỉ IP của host**. Nhịp thấp làm giảm rủi ro bị chặn, **không xoá** rủi ro ấy. Cách duy nhất che IP
là dùng proxy/Tor, mà thiết kế này **cố ý không dùng proxy xoay IP**.

**Điều khoản:** metasearch gửi truy vấn tự động tới engine bên ngoài; một số engine không cho phép
điều đó trong điều khoản sử dụng. Chủ nhà đã chọn hướng SearXNG (#6071); tắt một engine chỉ cần sửa
`settings.yml`.

## 6. Ngân sách nhịp (kế hoạch §5.4.2)

| Nhóm | Nhịp tối đa [ƯỚC LƯỢNG] |
|---|---|
| `google`, `startpage` | 1 lần/10 s, ≤ 150/ngày |
| Các engine web khác | 1 lần/3 s |
| Tin tức | 1 lần/10 s |
| `wikipedia` | 1 lần/s |
| `github` (qua SearXNG) | chung hạn mức GitHub 10/phút |
| `google scholar` | 1 lần/20 s, ≤ 60/ngày (trọng số thấp vì hay bị chặn) |

Bộ luân phiên của ống tìm (bước 7) chỉ chọn **3–4 engine web khoẻ nhất** mỗi truy vấn, nên mỗi
engine nhận ít truy vấn hơn và ít bị chặn hơn. **ĐO 2026-10-06**: sau nhiều lượt dò liên tiếp,
`brave` bị "Suspended: too many requests" và `google` "access denied" — đúng lý do bảng nhịp +
luân phiên tồn tại. Khi mọi engine web chung đều bị ngưng, run ghi "web chung suy giảm" chứ không
giả là đã tìm đủ.

## 7. Đổi danh sách engine

Mở `settings.yml`, sửa khối `engines`:

* **Bật**: `disabled: false` (hoặc bỏ khỏi danh sách để về mặc định của SearXNG).
* **Tắt**: `disabled: true`.
* Engine bật mặc định: `brave`, `duckduckgo`, `mojeek`, `qwant`, `startpage`, `bing`, `google`;
  tin tức `bing_news`, `google_news`; tham khảo `wikipedia`, `wikidata`; mã nguồn `github`;
  học thuật `google_scholar`.
  (`qwant_news` đã **bị xoá** khỏi danh sách: ảnh 2026.9.23 không còn mô-đun `qwant_news.py`, khai
  vào chỉ sinh một dòng ERROR lúc khởi động.)
* Engine **tắt mặc định**: `openalex`, `semantic_scholar`, `crossref`, `arxiv`, `pubmed` — vì
  harness gọi các API này **trực tiếp** (§5.4.3); gọi thêm qua SearXNG là tiêu hạn mức của cùng IP
  hai lần.
* Ghi đè ở phía harness (không cần sửa `settings.yml`): `BOXFOX_SEARCH_ENGINES=brave,bing,google`.

Tiếng Việt: chưa có engine SearXNG nào cho Cốc Cốc đã kiểm; biến thể tiếng Việt đi qua `google`,
`bing`, `brave`, `duckduckgo` với `language=vi-VN`, cộng `wikipedia` tiếng Việt.

Sau khi sửa, khởi động lại: `docker compose -f deploy/searxng/docker-compose.yml restart`.
