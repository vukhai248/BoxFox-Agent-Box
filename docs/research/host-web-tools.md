# Nghiên cứu: công cụ tra cứu mạng chạy ở tầng host (web_search, web_fetch)

> **Trạng thái:** đã có trong mã (đợt 9, `backend/src/agentbox/agent_core/web.py`).
> Đây là câu trả lời cho việc N-5 (treo từ đợt 7) — khiếu nại của chủ dự án rằng
> "plan xong chưa có cơ chế tra cứu mạng". Quyết định của chủ dự án: *"Nghiên cứu các
> công cụ search, fetch vì không có API key của Brave. Các công cụ free. Làm công cụ ở
> tầng host."*
>
> **Cập nhật 2026-10-06 (PART 1 — "cài xong là tìm được, không khoá"):** câu kết luận cũ ở §2.1
> ("không có máy tìm kiếm web tổng quát nào miễn phí và không khoá mà đáng tin") nay chỉ còn đúng cho
> **instance công khai / HTML front-end**; **SearXNG tự host trên loopback** là chân không-khoá
> **mặc định** (bậc 3) và đã đo sống — xem §2.2. Thứ tự 5 bậc + vị trí ống 10 bước: §3. Bản ghi quyết
> định: [`docs/plan/builtin-search-default.md`](../plan/builtin-search-default.md); vận hành:
> [`deploy/searxng/README.md`](../../deploy/searxng/README.md).

## 1. Vì sao không đặt công cụ trong box

| Sự thật đo được (2026-09-20) | Hệ quả |
|---|---|
| Trong box: `iptables -S OUTPUT` = `-P OUTPUT DROP`, chỉ `-o lo -j ACCEPT` và bốn luật `--sport 5900/6080/8080/8081 … ESTABLISHED`, rồi `-A OUTPUT -j REJECT` | Box không có Internet; `browser_use` chỉ tới được trang phục vụ trong box |
| `socket.create_connection(('vi.wikipedia.org', 443))` trong box → `OSError`; `1.1.1.1:443` → `ConnectionRefusedError` | Không thể "chỉ mở một miền" mà không đổi chính sách firewall |
| Host (nơi harness và router chạy) có Internet đầy đủ | Đặt công cụ ở host: box vẫn kín, chỉ phần văn bản đã cắt đi vào ngữ cảnh |
| Box có công tắc mạng `/__box/network on|off` (mặc định tắt) | Vẫn giữ nguyên lựa chọn đó cho người dùng; công cụ web không cần nó |

## 2. Đo các nhà cung cấp miễn phí, không khoá (từ host)

Hai vòng đo: **2026-09-20** (bảng 2.1 — vòng quét đầu, chốt chuỗi) và **2026-10-06** (bảng 2.2 — đo
lại khi làm PART 1). Số của vòng cũ **giữ nguyên, không viết lại**; chỗ nào bị vòng mới phủ định thì
ghi rõ ngay dưới bảng.

### 2.1 Vòng đo 2026-09-20

| Điểm cuối | Khoá? | Nguồn cấu hình (bậc §3, chốt 06/10/2026) | Kết quả đo | Kết luận |
|---|---|---|---|---|
| `POST https://api.firecrawl.dev/v1/search` | không | Settings → Provider → Web Search (bậc 1, nếu có credential) hoặc ENV `FIRECRAWL_API_KEY` (bậc 2); bản **không khoá** là bậc 4 | **200**, JSON `{success, data:[{url,title,description}]}` với truy vấn thật (20/09); **403/429** khi đo lại 06/10 ⇒ xem 2.2 | Chân **keyless** của `source="web"` (bậc 4) |
| `api.search.brave.com` | cần | Settings/ENV `BRAVE_API_KEY`/`BOXFOX_BRAVE_API_KEY` (bậc 1–2) | không gọi được (chủ dự án không có khoá) | Bật khi có khoá |
| `api.tavily.com` | cần | Settings/ENV `TAVILY_API_KEY` (bậc 1–2) | không gọi được | Bật khi có khoá |
| `html.duckduckgo.com/html/?q=` | không | — (chỉ thử để loại) | 200 nhưng là trang thử thách bot (`anomaly-modal`), 0 kết quả phân tích được | loại |
| `lite.duckduckgo.com/lite/` (GET/POST) | không | — | 202, trang thử thách | loại |
| `api.duckduckgo.com/?format=json` | không | — | 200 nhưng Instant Answer rỗng cho truy vấn thường | loại |
| `www.mojeek.com/search` | không | — | **403** kể cả khi giả User-Agent Chrome | loại |
| `searx.be/search?format=json` và 7 bản SearXNG khác | không | — (instance **công khai**; tự host mới dùng — bậc 3, xem 2.2) | JSON bị tắt (trả HTML) hoặc **429** / "Making sure you're not a bot!" | loại |
| `s.jina.ai` (search) | cần | — | 401 `AuthenticationRequiredError` | loại |
| `api.marginalia.nu`, `freeserp.ai/api/...` | không | — | 404 / 302, không có API công khai | loại |
| `en.wikipedia.org/w/api.php?list=search` | không | `source="wikipedia"` | **200**, JSON có tiêu đề + đoạn trích | nguồn chuyên biệt, không khoá |
| `api.stackexchange.com/2.3/search/advanced` | không | `source="stackoverflow"` | **200**, JSON có `is_answered`, `score`, thân bài | nguồn chuyên biệt, không khoá |
| `api.github.com/search/repositories` | không (60 lượt/giờ) | `source="github"` | **200**, JSON | nguồn chuyên biệt, không khoá |
| `api.openalex.org/works?search=` | không | `source="papers"` | **200**, JSON (bài báo, DOI, số trích dẫn) | chân **đầu** của chuỗi học thuật, cũng là xương sống của `paper_citations` (A-6) |
| `api.crossref.org/works?query.bibliographic=` | không (`mailto`) | `source="papers"` | **200**; **429 rồi 200** cùng phiên ⇒ phải có `_retry` | chân 2 của chuỗi học thuật (A-6) |
| `www.ebi.ac.uk/europepmc/webservices/rest/search` | không | `source="papers"` | **200** rồi **503** cùng phiên ⇒ phải có `_retry`; phủ y–sinh | chân 3 của chuỗi học thuật (A-6) |
| `export.arxiv.org/api/query` | không | `source="papers"` | **406** cho `all:referral` (3 lần) mà **200** cho `all:electron` cùng phiên | chân **cuối** của chuỗi học thuật (A-6) |
| `api.exa.ai/search` | **cần** | Settings/ENV `EXA_API_KEY` (bậc 1–2) | không gọi được (chủ dự án không có khoá) | Chân 4 của `source="web"`, chỉ chạy khi có khoá (A-7) |
| `api.parallel.ai/v1beta/search` | **cần** | Settings/ENV `PARALLEL_API_KEY` (bậc 1–2) | không gọi được | Chân 5 của `source="web"`, chỉ chạy khi có khoá (A-7) |
| `r.jina.ai/<url>` | không | — (đầu đọc, không phải tìm kiếm) | **200**, Markdown có `Title:` và `Markdown Content:` | Bản dự phòng đọc trang khi bản chính bị chặn/thiếu chữ |

### 2.2 Vòng đo 2026-10-06 — SearXNG tự host thành chân mặc định không khoá

| Phép đo | Nguồn cấu hình | Kết quả đo |
|---|---|---|
| `GET http://127.0.0.1:8888/healthz` (image `searxng/searxng:latest`, port-mapping `127.0.0.1:8888:8888`) | **tự dò** — không cần biến | **200 `OK`** — dùng làm đầu dò tự dò |
| `searxng_search(...)` gọi thẳng | env `BOXFOX_SEARXNG_URL` hoặc tự dò | **251 ms**, **3 hàng** |
| `deploy/searxng/probe.py` (không khoá) | như trên | mã thoát **0**; `google cse` 14 hàng + `bing` 10 hàng (24 hàng, 542 ms); `brave` **429** "Suspended: too many requests"; `duckduckgo`/`qwant` **CAPTCHA**; `google` "Suspended: access denied" (403) từ IP trung tâm dữ liệu |
| Ống 10 bước với SearXNG thật, không khoá | `BOXFOX_SEARCH_PIPELINE=on` | **5 kết quả trong 0,3 s** |
| Chân `_provider_searxng` (chuỗi cũ), không khoá | `BOXFOX_SEARCH_PIPELINE=off` | **5 hàng trong 0,2 s**, `provider=searxng` |
| Firecrawl không khoá (đường mặc định cũ) | bậc 4 | **403/429** liên tục — đúng F05 (`docs/plan/Work-Graph-fix.md`, hàng F05); đây **không** phải lỗi truy vấn |
| 8 instance SearXNG công khai + HTML front-end | — | 429 / bot check / 403 ⇒ **loại** (không đổi so với 20/09) |

**Câu kết luận cũ ở §2.1 (nguyên văn):** *"không có máy tìm kiếm web tổng quát nào miễn phí và không
khoá mà đáng tin (ba nhà cung cấp thử thách bot, bảy bản SearXNG bị 429)"* — **vòng đo 06/10/2026 phủ
định một phần, nói thẳng:**

- Đúng cho **instance công khai** và **HTML front-end**: vẫn 429 / bot check / 403;
- **Sai cho SearXNG tự host trên loopback**: nó là máy tìm kiếm web tổng quát, miễn phí, không khoá, và
  đáng tin *ở mức đo được hôm nay* — chân **mặc định** của `source="web"` khi máy có nó (bậc 3).
  Bật bằng `bash deploy/searxng/up.sh`; harness **tự dò** `127.0.0.1:8888` nên không cần biến và
  không cần khởi động lại. Vận hành đầy đủ: `deploy/searxng/README.md`.

Chuỗi thiết kế cũ giữ nguyên hiệu lực cho các bậc 1/2/4, chỉ **chèn thêm bậc 3**:

1. `source="web"` → **bậc 1** Settings → **bậc 2** Brave/Tavily/Exa/Parallel nếu có khoá (A-7) →
   **bậc 3** SearXNG tự host (mới, 06/10/2026) → **bậc 4** Firecrawl không khoá;
2. nếu tất cả bị từ chối → lỗi `WEB_SEARCH_UNAVAILABLE` **nói rõ** và gợi ý dùng
   `source="wikipedia"|"stackoverflow"|"github"|"papers"` hoặc `web_fetch` một URL đã biết; từ A-7,
   thông điệp này **kể tên khoá thiếu** (`Set one of BRAVE_API_KEY|BOXFOX_BRAVE_API_KEY, …`) thay vì
   chỉ nói "mọi nhà cung cấp đều từ chối"; từ 06/10/2026 nó còn **phân loại** `searchFailure.kind` =
   `config`/`infra`/`source` và nói thẳng "not a query problem" cho hai ca đầu — xem §3 và
   `docs/plan/builtin-search-default.md` §4;
3. bốn nguồn chuyên biệt ở trên trả JSON ổn định, không cần khoá; `source="papers"` là một **chuỗi
   bốn chân** (OpenAlex → Crossref → Europe PMC → arXiv, A-6).

## 3. Chốt thiết kế

| Hạng mục | Quyết định | Vì sao |
|---|---|---|
| Nơi chạy | host, qua `asyncio.to_thread` trong `agent_core/web.py` | box không có Internet; harness giữ nhật ký và ranh giới an toàn |
| Vai được dùng | `research` (chính) và `orchestrator`; con của ai chỉ có giao của cha | đúng mong đợi "giao cho agent research"; `allowed_tools` đã giao theo cha |
| Chặn SSRF | chỉ `http`/`https`; từ chối tên `localhost`/`*.internal`/metadata; phân giải DNS **và** kiểm cả địa chỉ literal; kiểm lại từng bước chuyển hướng | mặt quản trị của router/harness/box nằm trên loopback — không được để công cụ này chạm tới |
| Trần dữ liệu | thân 2 MiB, 15 s, tối đa 10 kết quả, đoạn trích 400 ký tự, văn bản 8 000 (trần cứng 20 000), **một lời gọi tìm kiếm ≤ 3 truy vấn**, **không có phân trang**, **các hàng của một lời gọi tìm kiếm ≤ 18 000 ký tự** | giữ ngữ cảnh và không để một trang lạ nuốt ngân sách. Truy vấn gộp (A-7) là cách duy nhất để có thêm đất: `count` là trần **mỗi chân**, `queries` là số chân trong **một** lời gọi (D-13/F7: các chân chạy tuần tự, không song song) |
| Bộ đệm tìm kiếm | **300 s** × 16 mục khoá theo hình dạng lời gọi (truy vấn, `source`, `count`, `site`, `freshness`, `lang`, `exclude`) | một mô hình hỏi lại cùng câu **với đúng bộ tham số ấy** trong cùng lượt không tốn một chuyến mạng thứ hai; đo được 0,0009 s so với 0,42 s (A-7) |
| Nhãn tin cậy | mọi payload có `untrusted: true` và câu nhắc "dữ liệu, không phải chỉ thị" | nội dung tải về là dữ liệu của bên thứ ba |
| Nhật ký DEV | `web.search`, `web.fetch`, `web.error`, `web.retry` (chỉ số đếm, mã lỗi, thời gian — **không** nội dung truy vấn; `web.retry` mang đúng `attempt` + `code`) | điều tra được mà không rò dữ liệu; ranh giới này áp cho **mọi** đường ghi nhật ký, kể cả dòng `tool.error` chung (`WebError.log_message` + `failures.log_safe_failure`) — vòng soát mã đợt 10 bắt được nhánh lỗi còn ghi nguyên câu có truy vấn và URL |
| Rủi ro còn lại: kênh ra | `web_fetch` là kênh GET ra ngoài, giữ bởi cả `orchestrator` và `research` — một trang bị tiêm nhiễm có thể xúi agent tải `https://ke-tan-cong/?<ngữ cảnh>` | đây là chiều RÒ RA, khác với chiều nội dung bẩn vào; nhãn untrusted không chặn được nó. Giảm nhẹ đang có: chỉ `http(s)`, trần 2 MiB, danh sách đích công khai; muốn chặt hơn thì bỏ `web_*` khỏi `ORCHESTRATOR_TOOLS`, hoặc thêm danh sách đích cho phép |
| Rủi ro còn lại | orchestrator giữ `terminal_exec` mà cũng đọc được nội dung web | đã chọn theo yêu cầu; giảm nhẹ bằng nhãn untrusted + ranh giới rõ trong mô tả công cụ; nếu muốn chặt hơn thì bỏ `web_*` khỏi `ORCHESTRATOR_TOOLS` và buộc đi qua `research` |
| **Thứ tự nguồn tìm kiếm** (chốt 06/10/2026) | **Năm bậc**: (1) nguồn chọn ở **Settings → Provider → Web Search** (có credential) → (2) khoá ENV `BRAVE_API_KEY`/`BOXFOX_BRAVE_API_KEY` → `TAVILY_API_KEY` → `EXA_API_KEY` → `PARALLEL_API_KEY` → `FIRECRAWL_API_KEY` → (3) **SearXNG tự host** (env `BOXFOX_SEARXNG_URL` → tự dò `127.0.0.1:8888`) → (4) Firecrawl **không khoá** → (5) lỗi đã phân loại `WEB_SEARCH_UNAVAILABLE` (`searchFailure.kind` = `config\|infra\|source`) / `WEB_SEARCH_EMPTY` | bậc 3 là chân **không khoá mặc định** mới đo được 06/10/2026 (§2.2); bậc 1/2 **thắng** bậc 3 nên ai đã có khoá/chọn nguồn không bị đổi hành vi; hợp đồng đầy đủ ở [`docs/plan/builtin-search-default.md`](../plan/builtin-search-default.md) §4 |
| **Đường ống 10 bước** (vị trí) | `BOXFOX_SEARCH_PIPELINE` = `auto` (mặc định) \| `on` \| `off`; khi chạy, ống **hiện thực bậc 3** cho `source="web"`: `auto` chỉ chạy khi SearXNG sống ∧ **không** cấu hình tường minh (bậc 1/2); `on` chạy trước cả bậc 1/2; ống không ra kết quả ⇒ rơi xuống phần còn lại của chuỗi **một lần**, payload ghi `searchFallback` | `auto` giữ đúng thứ tự ưu tiên (không phá hợp đồng với tab Settings); `off` là **công tắc giết** một dòng, không cần build lại; `pipeline_enabled()` giữ nghĩa cũ (`on`) cho nhánh `papers` |
| **Quan sát trạng thái** (06/10/2026) | `GET /api/agent/health` khối `search` (rẻ, **không gọi mạng**; `?probe=search` mới dò thật) + `runtime-info.search`; `python3 deploy/searxng/probe.py [--json]` cho phán quyết theo engine | người vận hành trả lời được "SearXNG sống? engine nào bị chặn? đang dùng nguồn nào? có đang rơi dự phòng không?" mà không phải đọc log hay đoán |

## 4. Vòng 27 — lớp đọc nguồn (đợt 1 xong 2026-09-23)

Bảng §2 ở trên vẫn đúng cho **tìm kiếm**; mục này bổ sung phần **đọc**: cùng một URL, cùng một
`web_fetch`, nhưng nay có giải nén, có phép kiểm thân bài, có thang đọc dự phòng và có tầng PDF.
Ghi theo từng đợt đã xong, kèm ngày đo.

### 4.1 Số đo trước/sau (host, 2026-09-23)

| Trang | Trước (commit `2add905`) | Sau (đợt 1) |
|---|---|---|
| `nhandan.vn/<bài Bộ Y tế …post900643>` | 17 421 "ký tự" mà **55 %** là rác nhị phân, junk 0,550 | cùng URL: **9 103** ký tự, **junk 0,0000**, `ok` — số lấy từ đầu đọc, vì đường trực tiếp của bài này nay trả 404 |
| `nhandan.vn/` (trang chủ) | — | 18 832 ký tự, **junk 0,0000**, `readTier: html` |
| `baochinhphu.vn/<bài Bộ Y tế …102250115105914411.htm>` | 46 692 ký tự rác, junk 0,517 | **8 079** ký tự chữ, **junk 0,0000**, `readTier: html` (giải nén tại chỗ, **không** cần đầu đọc) |
| `vanban.chinhphu.vn/` (trang chủ) | 942 ký tự — thân bài nằm trong `<form>` nên bị bỏ sạch | 31 792 ký tự, **junk 0,0000**, `readTier: html` |
| `vietnamplus.vn/` | 37 798 ký tự rác | **16 455** ký tự, **junk 0,0000** |
| `thuvienphapluat.vn` (403) | thân bài rỗng ⇒ mất cả trang, dù đầu đọc có 91 032 byte | **không còn mất trang**: 281 ký tự, `verdict: error-page`, đầu đọc không cứu được (xem §4.6) |
| PDF arXiv `1706.03762v7` | chuỗi `%PDF-1.4…`, junk 0,517, `textChars` 10 205 | 46 128 ký tự chữ, `readTier: pdf-table`, **10 bảng** / 15 trang dựng tại chỗ bằng `pdfplumber` |
| HTML arXiv `1706.03762v7` | — | 45 814 ký tự, tầng `html`: **9 bảng** mang nhãn `bảng trích tự động` (HTML có 10 thẻ `<table>`) |
| `vbpl.vn/TW/Pages/vbpq-toanvan.aspx?ItemID=1` | trả "Trang chủ" (27 378 byte) mà không ai biết | 87 ký tự; lần 6 `wrong-page`, lần 7 **`error-page`** (dấu hiệu `'đang tải dữ liệu'` đã sống — xem §4.7.1), đầu đọc **không** được nhận (xem §4.6) |
| `moh.gov.vn` | "Warning: This page maybe not yet fully loaded" (165–259 byte) | ném `WEB_FETCH_FAILED` sau 15,44 s (lần 6); lần 7 qua đầu đọc trả **21 ký tự** ⇒ `thin`, `underMinChars: true` — **không bao giờ `ok`** |
| `r.jina.ai` trên PDF | (chỉ đường này) | **0 dòng `|`** ⇒ bảng mất sạch: vì vậy đầu đọc chỉ là tầng 4, sau tầng PDF |

### 4.2 Thang đọc năm tầng (A-3/A-10)

| Tầng | Khi nào | Đo được |
|---|---|---|
| 1 `html` | trang HTML thường | chữ + bảng giữ nguyên |
| 2 `jats` | `fullTextXML` của Europe PMC — nhận **theo dấu hiệu** `table-wrap` trong thân bài, vì dịch vụ trả `text/plain` chứ không phải `application/xml` | `PMC7090843`: 10 thẻ `<table-wrap>` ⇒ **5 bảng** mang nhãn (mẫu cũ `PMC3258128` không có thẻ nào nên tầng không chạy — lỗi ở mẫu đo, không ở mã) |
| 3 `pdf-table` | `Content-Type: application/pdf` **hoặc** thân bài bắt đầu `%PDF-` | dựng lại bằng `pdfplumber` trên host; 10 bảng; dòng tiêu đề nhiều tầng **có thể lệch** ⇒ bảng luôn mang nhãn `bảng trích tự động`. Dựng lại **được** ⇒ tầng 4 **không** được gọi (§4.7.3) |
| 4 `reader-text` | thân bài rác/thiếu chữ, non-2xx, hoặc PDF hỏng | `r.jina.ai`; bảng mất — chỉ dùng khi các tầng trên không cứu được |
| 5 `page-image` | (chưa hiện thực — đợt sau) | — |

Luật quan trọng: đầu đọc **không bao giờ** được dùng để lách chặn SSRF (`WEB_URL_FORBIDDEN` ném
thẳng ra), và bản của đầu đọc **chỉ được nhận khi tốt hơn** bản trực tiếp theo thang
`ok > thin > wrong-page/error-page > junk/empty`; nếu không thì lỗi gốc được giữ nguyên
(`HTTP 404` vẫn là `HTTP 404`, không đổi thành "trang rỗng").

### 4.3 Ba công tắc (A-9)

| Biến | Giá trị | Mặc định | Nghĩa |
|---|---|---|---|
| `BOXFOX_WEB_READER` | `auto` / `thin` / `off` | `auto` | `thin` = **đúng hành vi `2add905`** (chỉ gọi đầu đọc khi thân bài < 200 ký tự) — công tắc hồi quy; `off` = không bao giờ |
| `BOXFOX_WEB_DECODE` | `on` / `off` | `on` | `off` = quay về trước A-1 (không giải nén); cần có vì A-1 chạm **mọi** lượt đọc |
| `BOXFOX_WEB_READ_STORE` | `on` / `off` | `on` | bộ đệm đọc (`ReadStore`, A-4 — đợt 2). Chỉ hai giá trị vì không có mức giữa nào có nghĩa |

Giá trị lạ ⇒ **mức mặc định + notice một lần** (`WEB_READER_MODE_UNKNOWN` /
`WEB_READ_STORE_MODE_UNKNOWN`) tại lượt đầu tiên phiên thật sự đọc nguồn. Trạng thái ĐANG ÁP
được phơi ở `GET /api/agent/runtime-info` → `limits.web`:

```json
{"readerMode": "auto", "readerModes": ["auto", "thin", "off"], "readerDefault": "auto",
 "readStoreMode": "on", "readStoreModes": ["on", "off"], "readStoreDefault": "on",
 "textHardChars": 20000, "storeMaxEntries": 24}
```

### 4.4 Dòng "Trần dữ liệu" của bảng §3 — đọc kèm mục này

Dòng §3 **giữ nguyên, không sửa**: trần **một lời gọi** vẫn là `MAX_TEXT_DEFAULT = 8 000` và
`MAX_TEXT_HARD = 20 000` (trần ngữ cảnh vẫn cắt ở 20 000, nên nâng con số này chỉ tạo payload bị
cắt âm thầm). Phần **tài liệu dài** nằm ở bộ đệm đọc — **đã có trong cây này từ đợt 2** (A-4,
`BOXFOX_WEB_READ_STORE`, mặc định `on`). `ReadStore` giữ tới **24 bản × 400 000 ký tự** (trần
**4 000 000** ký tự) và `read_source(ref=…, offset=…)` trả từng mẩu; `web_fetch` bị cắt ở trần ngữ
cảnh **vẫn** lưu **toàn bộ** bản đã đọc, nên mẩu nối lại đúng bản gốc.

ĐO ĐƯỢC 2026-09-23 (thước đo lần 8, `--only store`): `docs.python.org/3/whatsnew/3.13.html` ⇒
`stored=113936`, ghép **15 mẩu** ra `joined=113936` (**khớp từng ký tự**), `find='asyncio'` ⇒ 1 vị
trí khớp, 0,14 s; cùng trang, lượt trước chỉ cho model **8 000** ký tự (7 %). Trần **một lời gọi**
vẫn là 8 000/20 000 ký tự như dòng §3 — đổi lại là **số lượt gọi**, không phải kích thước mỗi lượt.
`dispose`: chạm thì sống (LRU), vượt 24 bản hoặc 4 000 000 ký tự thì bản **cũ nhất** bị bỏ trước.

### 4.5 Ghi chú phụ thuộc

`pdfplumber` + `pypdfium2` nay là phụ thuộc của host (`backend/requirements.txt`, chủ nhà cho phép
#6011) và **không** được cài trong box (`#5977`: box không cài gói; box cũng không có mạng mặc
định). Thiếu thư viện ⇒ tầng PDF trả `''` kèm `pdfNote` nói rõ, chứ **không** trả nhị phân thô.

### 4.6 Bốn sửa đổi mà thước đo bắt được (chốt đợt 1, 2026-09-23)

`scripts/probe-reading.py` chạy lần 6: **11/11 mục đạt ngưỡng**. Bốn chỗ dưới đây không nằm trong
chữ của plan nhưng chính thước đo phơi ra; mỗi chỗ đều có số đo trước/sau.

1. **Nội dung trong `<form>` không còn bị bỏ.** `vanban.chinhphu.vn/?pageid=27160&docid=207396` là
   trang ASP.NET bọc **toàn bộ thân bài** trong `<form id="form1">`; `_TextExtractor` bỏ nội dung form
   nên 81 697 byte HTML ⇒ **2 ký tự**. Sau bản sửa: **5 053** (trang chủ cùng host: 942 → **31 792**).
   `nav`/`footer`/`aside`/`svg`/`script`/`style` vẫn bị bỏ.
2. **Tên miền không phải slug.** Phép cắt chuỗi cũ lấy cả host khi đường dẫn chỉ là `/`, nên
   `https://vanban.chinhphu.vn/` sinh token `['vanban','chinhphu']` và **mọi** trang của host đó ra
   `wrong-page` (một báo sai, không phải một phép kiểm). Nay chỉ lấy phần `path`; ca đã đo của `vbpl.vn`
   vẫn bắt đúng.
3. **Đầu đọc không được "rửa" trang sai thành `ok`.** `reading.slug_clue` là cửa hậu của `wrong_page`:
   một trang đã đo là SAI chỉ được xoá verdict bằng một bản đọc **có tiêu đề** chia sẻ token với slug.
   Đo được: `r.jina.ai` trả 26 522 ký tự *site chrome* cho `vbpq-toanvan.aspx?ItemID=1` và không có dòng
   `Title:` nào. Phép kiểm chỉ nhìn tiêu đề (`Title:` hoặc dòng `#`) — bản chrome có chứa chính chuỗi URL
   đó trong liên kết, nên quét cả thân bài thì cửa hậu không chặn được gì (lần chạy đầu đã lọt).
4. **Trang chặn bot là `error-page`.** Thêm dấu hiệu `'performing security verification'` vào
   `ERROR_MARKERS`: `thuvienphapluat.vn` trả 403 cho client thường, và đầu đọc không khoá nhận đúng
   trang chặn bot 281 ký tự — trước bản sửa chỗ đó ra `thin`, tức vẫn là một dạng thành công giả.

Hai sửa đổi của cùng lượt này (đã ghi ở §4.2/§4.5) được xác nhận sống: **trần PDF riêng 8 MiB** tải lại
đúng một lần, và **tầng JATS nhận theo dấu hiệu `table-wrap` trong thân bài** (Europe PMC trả
`text/plain` cho `fullTextXML`, không phải `application/xml`).

### 4.7 Ba sửa đổi nữa mà lượt soát mã bắt được (2026-09-23)

Sau khi chốt đợt 1, ba lượt soát mã song song (dọn mã · lõi `reading.py`/`web.py` · kiểm thử –
tài liệu – thước đo) tìm thêm ba chỗ **mã không làm điều nó nói**, đã sửa ngay trong đợt:

1. **Hai dấu hiệu lỗi tiếng Việt là chuỗi chết.** Phép so dấu hiệu chạy trên bản **bỏ dấu**
   (`_plain`), nhưng `ERROR_MARKERS` chỉ có `'văn bản không tồn tại'` và `'đang tải dữ liệu'` ⇒
   **không bao giờ khớp**. Hệ quả đo được: thân bài 404 của `vbpl.vn` (ảnh `404 Error` + "Văn bản
   không tồn tại") chỉ bị bắt nhờ mục `'404 error'`; thiếu mục ấy thì nó ra `ok` — đúng loại
   "thành công giả" mà đợt này tồn tại để giết. Nay mỗi mục có cả hai cách viết và phép so bỏ dấu
   chính dấu hiệu; bảng `GENERIC_TITLES` sửa cùng lỗi (`'trang chủ'`, `'đang tải'`).
2. **Slug tiếng Việt percent-encode bị giải mã sai, và kênh tiêu đề của đầu đọc bị xoá.**
   `_slug_tokens` không `unquote` nên `…/B%E1%BA%A3o_hi%E1%BB%83m_y_t%E1%BA%BF` sinh token
   `['a3o','83m']` ⇒ trang THẬT bị gọi `wrong-page` (đo lại trên `vi.wikipedia.org`: bản cũ
   `wrong_page=True`, bản nay `False`, tokens `['bao','hiem']`). Đường cứu đã thiết kế cũng **bất
   động**: `_read_through_reader` cắt lấy phần sau `Markdown Content:` nên dòng `Title:` — kênh duy
   nhất `slug_clue` đọc — bị xoá trước khi ai kịp thấy. Nay `unquote` slug, giữ dòng `Title:` của
   đầu đọc, và khi nhận bản đầu đọc thì **tiêu đề của nó** mô tả thân bài đang giữ.
3. **PDF dựng lại được vẫn đi qua đầu đọc.** `ladder_plan` kiểm `is_pdf` **trước** `verdict`, nên
   mọi PDF tốn thêm một lời gọi ngoài, và khi bản dựng lại ít chữ thì bản đầu đọc (không bảng) thay
   được nó — bảng bị bỏ. Nay tầng 3 đứng trước tầng 4: chỉ PDF **không dựng lại được** (không chữ,
   hoặc bị chấm `junk`/`empty`/trang lỗi/sai) mới tới lượt `r.jina.ai`. Đo sống lại
   `arxiv.org/pdf/1706.03762v7`: hai lời gọi (bản cắt 2 MiB + lần tải lại theo trần PDF 8 MiB),
   **0 lời gọi đầu đọc**, `pdf-table`, **10 bảng**, 15 trang, 46 128 ký tự, 2,36 s.

**Một chỗ lệch kỳ vọng của plan, nói thẳng:** A-3 kỳ vọng `thuvienphapluat.vn` đọc được **≥ 20 000 ký tự**
(đo được 91 032 byte ngày 2026-09-23). Đo lại cùng ngày, muộn hơn: `r.jina.ai` **không khoá** trả về đúng
trang chặn bot 281 ký tự. Ngưỡng ấy không còn đứng được, và đó là thay đổi của dịch vụ bên ngoài chứ
không phải của mã. Bất biến giữ được và đã đo: chủ nhà 403 **không bao giờ** ra `ok`. Muốn đọc được
trang này cần một chân đọc khác (không nằm trong đợt 1–2): A-7 là việc của **tìm kiếm**, không phải
của **đọc**.


### 4.8 Đợt 2 — bộ đệm đọc, tài liệu dài và tham chiếu học thuật (2026-09-23)

**A-4 `ReadStore` + `read_source`.** `web_fetch` lưu **toàn bộ** bản đã đọc vào bộ đệm kể cả khi câu
trả lời bị cắt ở trần ngữ cảnh; `read_source(ref=…, offset=…, maxChars=…, find=[…])` trả từng mẩu và
`nextOffset` đi tiếp. `find` **bỏ dấu** nên `'chuyen tuyen'` khớp `'chuyển tuyến'` (cùng luật với
tên miền và dấu hiệu lỗi ở §4.7). Vượt `READ_OFFSET_MAX = 5 000 000` hay `maxChars` rác thì kẹp về
biên, không cắt im lặng. Hình dạng câu trả lời giữ nguyên F23 (các khoá cũ vẫn có) để
`source_verify` không phải sửa.

ĐO ĐƯỢC (một lời gọi mạng, không tải lại): trang 60 000 ký tự, mẩu 8 000 ⇒ mẩu thứ hai **nối đúng**
bản gốc; `read_source` với `url` lần hai ăn bộ đệm; công tắc `off` ⇒ **không lưu** và `ref` là `null`.

**A-6 `paper_citations` + chuỗi học thuật bốn chân.** `paper_citations(workId|doi, direction=…)` đi
theo đồ thị trích dẫn của **một** bài, keyless:

- `forward` = ai trích dẫn bài này (`filter=cites:W…`), `total` lấy từ `meta.count` — **không** lấy
  số dòng trả về, nên "1 255 bài trích dẫn" là con số của nhà cung cấp, không phải của trang đầu;
- `backward` = bài này dựa trên gì: đọc `referenced_works` (sống qua `select`), rồi giải **một** lời
  gọi cho cả danh sách (`filter=openalex_id:W1|W2|…`, tối đa `PAPER_CITATIONS_RESOLVE_MAX = 50` mã).
  Danh sách dài hơn 50 ⇒ `total` nói **đủ** số thật, `count` nói số đã lấy — không im lặng.

ĐO ĐƯỢC 2026-09-23: `W2741809807` có **54** tham chiếu; `filter=cites:W2741809807&per-page=2` trả
`count=1255` trong **891 byte** (đúng bộ `select` mà `_openalex_json` gửi: `filter=cites:…&select=…&per-page=2`);
work đầy đủ 33 226 byte ⇒ cùng bộ `select` ấy còn **2 967 byte**. Con số byte phụ thuộc bộ `select` —
hôm sau đo lại cùng URL với `per-page=2` là 4 895 byte, nên hãy đọc đây là "nhỏ hơn một bậc", không
phải một hằng số. `mailto` của
dự án (`BOXFOX_OPENALEX_MAILTO`, mặc định trung tính) là thứ làm 429 biến mất ở Crossref, và
`_retry` (429/5xx/hết giờ, tôn trọng `Retry-After` ≤ 5 s, **không** thử lại 4xx khác) là thứ giữ
được nguồn khi nhà cung cấp chớp: đo được Crossref 429→200 và Europe PMC 200→503 trong cùng phiên.

**Sửa một lỗi THẬT thứ hai mà lượt kiểm độc lập bắt được (2026-09-23):** `paper_citations` với `doi`
+ `direction="forward"` từng ném `WEB_FETCH_FAILED … answered HTTP 400`: nhánh `forward` nhét thẳng
`filter=cites:doi:…`, mà `filter` của OpenAlex chỉ nhận mã `W…` (OpenAlex trả đúng câu
`'doi:10.7717/peerj.4375' is not a valid OpenAlex ID.`). Nhánh `backward` không dính vì DOI đi trong
**đường dẫn** (`works/doi:…` — đo được 200, trả `W2741809807`). Nay DOI (dạng thô, `doi:…`, hay
`https://doi.org/…`) được **giải** thành `W…` bằng một lời gọi thêm `works/doi:…?select=id` (42 byte)
trước khi lọc; `work` trong payload trả mã `W…` đã giải, và nếu không giải được thì ném
`WEB_SEARCH_UNAVAILABLE` chứ không nhét `doi:…` vào `filter` lần nữa. `backward` giữ nguyên đường dẫn cũ.

**Sửa một lỗi THẬT mà ca đơn vị bắt được ngay khi viết (2026-09-23):** `PAPER_CITATIONS_RESOLVE_MAX`
được **dùng** ở nhánh `backward` nhưng **thiếu trong danh sách import** ⇒ mọi lời gọi `backward` có
tham chiếu ném `NameError`. Không lượt đo sống nào chạm nhánh ấy (thước đo chỉ chạy `forward`), nên
chỉ ca đơn vị mới thấy; nay `test_web_papers.py` ghim cả hai chiều và cả tên hằng số.

### 4.9 Đợt 2 — A-7: một lời gọi tìm kiếm, nhiều chân (2026-09-23)

`web_search` nhận thêm `queries` (tối đa **2** truy vấn phụ, tổng ≤ `SEARCH_QUERY_MAX = 3`), `site`,
`freshness` (`day|week|month|year`), `lang`, `exclude`. Không có phân trang — và mô tả công cụ **nói
thẳng** điều đó để mô hình không thử `page=2`.

- **Ngân sách ký tự:** `queries` cho phép 3 chân × 10 hàng, mỗi hàng tới ~900 ký tự ⇒ ~27 000 ký tự,
  mà runtime cắt kết quả công cụ ở **24 000** (giữ 20 000) — payload dài hơn sẽ bị cắt **giữa JSON**.
  Vì thế các hàng bị giới hạn ở `SEARCH_PAYLOAD_CHARS = 18 000`: cắt ở **đuôi** (hàng của chân chính
  `query` đứng đầu) và **nói ra** bằng `dropped`. Không có ngân sách này thì model nhận một chuỗi JSON
  hỏng thay vì "ít kết quả hơn" — và lượt ấy lại đúng là lượt đi tìm dữ liệu.
- **Gộp + khử trùng:** mọi kết quả của mọi chân đi qua một lần khử trùng theo URL **đã chuẩn hoá**
  (bỏ fragment, bỏ `utm_*`/`fbclid`/`gclid`, bỏ `www.`, mã hoá lại query **giữ nguyên thứ tự** —
  ≥ 0,8 **và** mỗi bên ≥ 8 token — ngưỡng token là thứ giữ cho các kết quả ngắn cùng khuôn không bị
  gộp oan; đó là một ca đỏ thật trong lúc viết ca). Bản giữ lại là bản **đầu**, các bản sau vào
  `alsoFrom` ⇒ không mất dấu vết.
- **Chân mới:** Exa và Parallel **chỉ chạy khi có khoá** (`EXA_API_KEY`, `PARALLEL_API_KEY`); thiếu
  khoá thì chân ấy nói tên khoá rồi rơi tiếp, không ném ra ngoài (giữ #5978/#6020/#6023: mặc định
  vẫn keyless).
- **`exclude` không bật mặc định** (#5991): lọc **kết quả** phía ta, không cắt truy vấn, và chỉ khi
  người gọi yêu cầu.
- **Cache 300 s / 16 mục** theo hình dạng lời gọi; lời gọi lặp trả `cached: true` + `fetchedAt` gốc.
  Cùng một câu hỏi nhưng **khác** bộ tham số (ví dụ câu ấy chuyển từ `query` sang `queries`) là khoá
  khác ⇒ tốn chuyến mạng mới (đo được: 2 chuyến), nên chỗ này chỉ miễn phí khi **hình dạng y hệt**.
- **Giới hạn còn lại, nói thẳng:** ngân sách giữ hàng **đầu** vô điều kiện (hàng của chân chính), nên
  một URL khổng lồ (đo được một hàng 31 298 ký tự trong lượt kiểm độc lập) vẫn có thể đẩy payload qua
  trần runtime. Trần cho MỘT hàng ấy chưa có luật riêng; xử lý đúng sẽ là một việc của đợt sau.
- **Thử lại:** chân bị 429/5xx được thử lại **một** lần, ghi `web.retry` (`attempt` + `code`, không
  truy vấn/URL); `Retry-After` được tôn trọng tới trần 5 s.
- **Chân lỗi không im lặng:** `perQuery` nói từng truy vấn lấy được bao nhiêu, và truy vấn nào bị từ
  chối kèm **lý do** — vì chân keyless *có* bị giới hạn nhịp (xem số dưới).

ĐO ĐƯỢC 2026-09-23 (keyless, hai truy vấn: `hồ sơ chuyển tuyến bảo hiểm y tế` + `site:chinhphu.vn hồ
sơ chuyển tuyến`, `count=5`): **10 kết quả**, `perQuery [5, 5]`, `deduped 0`, `duplicateUrls 0`,
`distinctNormalizedUrls 10`, `providers ['firecrawl']`, **0,85 s** — ngưỡng của plan là ≥ 6 kết quả và
0 URL trùng. Lượt lặp lại: **0,0009 s** với `cached: true` và `fetchedAt` y hệt (so với 0,42 s lượt
đầu). Đo lại muộn hơn cùng ngày: chân keyless Firecrawl **từ chối** bằng 429 (hai lượt liên tiếp),
`perQuery` ghi rõ truy vấn nào hỏng và thông điệp cuối **kể tên khoá thiếu** — đây là hành vi của
dịch vụ miễn phí, không phải hồi quy của mã; thước đo lần 8 vì thế đặt ngưỡng **cứng** ở hình dạng
mã (2 truy vấn chạy, 0 URL trùng, lượt lặp ăn cache) và ghi con số ≥ 6 như **số đo có ngày**, không
thành ngưỡng cứng.
