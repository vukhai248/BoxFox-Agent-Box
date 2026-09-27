# SearXNG tự host cho BoxFox (P0b)

Thư mục này chạy **SearXNG trên HOST** — không phải trong box. Box không có mạng
(`BOX_DEFAULT_NETWORK: "off"`), nên mọi truy vấn ra Internet đi từ host và chỉ văn bản đã trích
mới qua được ranh giới vào box.

Lớp tìm không khoá 10 bước (kế hoạch v2 §5.4.1) dùng SearXNG làm nguồn chính, gộp nhiều engine rồi
xếp hạng lại để tiệm cận chất lượng Brave **mà không cần khoá nào**.

## 1. Chạy

Ảnh `searxng/searxng:latest` đã được kéo sẵn trên máy này.

```bash
# Bật (dịch vụ tự chạy lại sau khi khởi động máy: restart unless-stopped)
docker compose -f deploy/searxng/docker-compose.yml up -d

# Xem log (mức WARNING nên rất ít dòng)
docker compose -f deploy/searxng/docker-compose.yml logs -f

# Tắt
docker compose -f deploy/searxng/docker-compose.yml down
```

Cấu hình dùng `network_mode: host` để instance nghe **đúng `127.0.0.1:8888`** như `settings.yml`
khai. Trên Docker Desktop (Mac/Windows), nếu host networking không chạy được, mở
`docker-compose.yml`, bỏ `network_mode: host`, bật khối `ports` (đã chú thích ở cuối tệp) và đổi
`server.bind_address` trong `settings.yml` thành `"0.0.0.0"` — cổng vẫn chỉ publish trên loopback
host nên **không lộ ra LAN**.

> **Đã đo 2026-09-25 (hai cái bẫy thật, ghi lại để lần sau không mất thời gian):**
> 1. Ảnh `searxng/searxng:latest` mở cổng **8080** của granian và **không đọc `server.port`** trong
>    `settings.yml`. Thiếu biến `SEARXNG_PORT=8888` (compose đã đặt sẵn) thì cổng 8888 không có ai
>    nghe: `ss` vẫn thấy cổng LISTEN do docker-proxy, nhưng mọi lời gọi trả
>    `Recv failure: Connection reset by peer`. Đây **không** phải lỗi của harness.
> 2. Trong sandbox này `network_mode: host` **không bind được** (`RuntimeError: Address already in
>    use (os error 98)` từ `granian._init_shared_socket()`), dù `ss` không thấy ai giữ cổng. Biến
>    thể port-mapping ở cuối `docker-compose.yml` chạy tốt — dùng nó khi gặp lỗi đó.

Hai dòng `ERROR` lúc khởi động cho `ahmia` và `torch` là **tiếng ồn của ảnh gốc** (engine onion
mặc định của SearXNG: `ahmia` cần Tor, `torch.py` không còn trong ảnh). Sau hai dòng đó, log chỉ
còn `[INFO] Started worker-1`. Ở **biến thể port-mapping**, mỗi địa chỉ nguồn mới còn sinh một dòng
`ERROR:searx.botdetection: X-Forwarded-For nor X-Real-IP header is set!` — docker-proxy che IP thật
của client; vô hại khi `limiter: false` (chỉ harness gọi), nhưng có thì biết vì sao.

`settings.yml` được mount **chỉ đọc**.

## 2. Trỏ harness vào instance

Đặt biến môi trường cho tiến trình harness (mặc định rỗng ⇒ chân searxng tắt):

```
BOXFOX_SEARXNG_URL=http://127.0.0.1:8888
```

Để bật **ống tìm 10 bước** (tuỳ chọn; mặc định `off` vẫn dùng đường tìm cũ):

```
BOXFOX_SEARCH_PIPELINE=on
```

## 3. Kiểm tra mức sẵn sàng

```bash
BOXFOX_SEARXNG_URL=http://127.0.0.1:8888 python deploy/searxng/probe.py
```

Probe gọi vài truy vấn thử, in **số kết quả theo từng engine**, danh sách `unresponsive_engines`
(engine bị CAPTCHA/403/429/hết giờ) và một lời gọi riêng `engines=brave` (nền proxy Brave của 8.7).
Mã thoát: `0` có kết quả · `2` instance sống nhưng rỗng · `3` không kết nối được.

**Kết quả đo thật trên máy này (2026-09-25, `probe.py`, không khoá):**

| Engine | Kết quả đo |
|---|---|
| `brave` | 7–24 kết quả, dùng tốt (cũng là nền so sánh của §8.7) |
| `mojeek`, `startpage` | 34 kết quả |
| `bing`, `google`, `google cse` | 9–16 kết quả |
| `duckduckgo`, `qwant` | **CAPTCHA** — không dùng được từ IP trung tâm dữ liệu |
| `wikidata` | hết giờ một lần |

Bộ luân phiên bước 7 tự bỏ qua engine hỏng, nên lượt tìm vẫn chạy: đo được `enginesUsed=['bing',
'google']` và **5 kết quả trong 0,8 s** cho truy vấn `retrieval augmented generation survey 2026`.

## 4. Đổi danh sách engine

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

## 5. Giới hạn riêng tư (nói thẳng)

Những gì cấu hình này **làm được**:

* Chỉ nghe `127.0.0.1`; `public_instance: false` và `limiter: false` (chỉ harness gọi, không có
  người lạ; limiter còn cần thêm Valkey và dành cho máy công khai).
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
engine nhận ít truy vấn hơn và ít bị chặn hơn. Khi mọi engine web chung đều bị ngưng, run ghi
"web chung suy giảm" chứ không giả là đã tìm đủ.
