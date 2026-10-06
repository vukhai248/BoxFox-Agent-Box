# Vòng 27 — Cải tổ research agent và công cụ tìm kiếm (kế hoạch nhiều đợt)

> **TL;DR:** Hôm nay BoxFox *có* công cụ tìm kiếm nhưng **không đọc được nguồn cho tử tế**: không giải nén gzip
> (Báo Nhân Dân 17 421 · Báo Chính phủ 46 692 · VietnamPlus 37 798 ký tự **rác**), chỉ cho model thấy **7 %** của tài
> liệu dài, gần như không dùng đầu đọc dự phòng, tin mọi `http=200` kể cả trang 404 giả; con research **không ghi được
> tệp** và câu trả lời bị cắt ở 8 000 ký tự; **không có sổ nguồn**, **không có cổng nào** kiểm câu trả lời research có
> nguồn, **không có vòng phản biện** cho nghiên cứu, và **không có case đo** nào. Kế hoạch này sửa lớp đọc (đợt 1),
> dựng sổ nguồn + thang nguồn + hồ sơ việc + cổng chất lượng + pha phản biện (đợt 2–3), rồi dạy luồng chạy ba mức
> nghiên cứu, bốn pha, nhịp báo, can thiệp giữa lượt và **đầu ra 100 % là tệp** (đợt 4–6), cuối cùng là đo được bằng
> bộ ca + oracle máy (đợt 8). Ba mảng **thị trường**, **học thuật/kỹ thuật** và **phương pháp** đã phỏng vấn xong
> **trước** khi thi công (13 vòng, #5955–#6025); giá trị nháp trong ba kế hoạch con chỉ còn việc đổi sang số đã chốt.
> **Cập nhật bản 3 (vòng 9–13, #5999–#6025):** thị trường, học thuật/kỹ thuật và **phương pháp đã chốt hết** — thang đọc FULL
> năm tầng (HTML/JATS → PDF + `pdfplumber` → đầu đọc chỉ chữ → ảnh trang), luật gap **hai tầng số** (sàn 20/10/≥2 + đích
> 30–50/15/3, thiếu mẫu thì nói rõ chứ không deadlock), bão hoà săn đuổi **3 vòng**, trần đối thủ **10–15**, tài liệu hãng
> cần **phiên bản + ngày truy cập**; **trần thời gian mềm theo việc + trần cứng an toàn 30/120 phút** (chạm thì báo + hỏi;
> lượt mức 3 được **3 600 s**), **nhánh con theo sóng 3–5** (mức 2 = 1 sóng · mức 3 ≤ 3 sóng), hồ sơ **1/3/6 tệp** với **hai
> loại phản biện**, nhịp kiểm chứng (mức 2 cổng máy · mức 3 con phản biện độc lập + **mục soi ý kiến chủ nhà**), **bảng
> MỞ-A…MỞ-H duyệt nguyên bảng** và **tự dựng công cụ tìm kiếm/tải, KHÔNG mua khoá**. Phỏng vấn đã đóng.

**Trạng thái:** bản 3 — phỏng vấn đã đóng (13 vòng) · chờ chủ nhà duyệt · **Nhánh:** `vorflux/v22-peer-mesh` · **HEAD khi viết:** `698521b` (cây sạch)
**Chủ nhà chốt:** *"tạo plan trước, ghi vào plan trước rồi tiếp tục interview"* (#5998)

**Kế hoạch con (chi tiết tới tệp/hàm/test):**
- `subplans/v27-reading-plan.md` + `-summary.md` — Phạm vi A: lớp đọc nguồn & lớp tìm kiếm (9 việc A-1…A-9, 4 đợt)
- `subplans/v27-ledger-plan.md` + `-summary.md` — Phạm vi B: sổ nguồn, thang nguồn, hồ sơ việc, cổng chất lượng, pha phản biện (8 mục, 6 đợt)
- `subplans/v27-flow-plan.md` + `-summary.md` — Phạm vi C: ba mức, bốn pha, điều phối, nhịp & can thiệp, ngân sách, đầu ra tệp, benchmark (C-1…C-8)
- `v27-owner-answers.md` — biên bản **13 vòng** phỏng vấn (#5955–#6025)
- `v27-adr-research-rework.md` — ADR: quyết định đã chốt + lý do + bằng chứng đo
- `v27-market-usecases.md` — danh mục 10 usecase thị trường (TM-1…TM-10) + 4 archetype C1–C4/C2′ (chốt vòng 10–11)
- `v27-full-read-and-pain-count.md` — đo năm đường đọc FULL + luật gap hai tầng số (chốt vòng 11)
- Mockup giao diện: `designs/v27-run-queue.html`, `v27-progress-milestones.html`, `v27-report-files.html`, `v27-level-approval.html` (+ `designs/design-plan.json`)

---

## 1. Đã chốt gì (không bàn lại — chỉ hiện thực)

| # | Quyết định | Nguồn |
|---|---|---|
| 1 | **Ba mức nghiên cứu** (1 nhanh · 2 báo cáo có nguồn · 3 hồ sơ sâu có kiểm chứng chéo + phản biện); **một con số mức cho cả việc**, main chọn theo tín hiệu, **mơ hồ ⇒ mức 2** | #5960, #5965 |
| 2 | **Đọc nguồn bắt buộc ở mọi mức**; "đọc" = mở thật + lấy đoạn liên quan + lưu **trích nguyên văn**; cấm kiểu trích snippet như đã đọc | #5960, #5966 |
| 3 | **Bốn pha**: bản đồ → chốt → đào sâu → **phản biện độc lập**; mức 3 luôn có **săn đuổi trích dẫn** (lùi + tiến) và **tiêu chí bão hoà** | #5967, #5968 |
| 4 | **Thang nguồn 4 tầng**, và **tài liệu chủ nhà đưa vào xếp trên cả tầng 1** (ghi rõ "do chủ nhà cung cấp") | #5962, #5983 |
| 5 | **Khẳng định then chốt cần HAI nguồn độc lập, trừ tầng 1** (một nguồn đủ); **hai nơi cùng đăng một tin tính MỘT nguồn**, muốn tính hai phải **khác nguồn tin gốc** | #5985, #5996 |
| 6 | **Báo chí chính thống đủ cho sự kiện**; khẳng định về **nội dung văn bản** phải trỏ bản gốc nếu mở được, không mở được thì **ghi rõ "chưa mở được bản gốc"** | #5984 |
| 7 | Trang **chính thức của cơ quan trên mạng xã hội** dùng được, ghi rõ, ngang chính thống, nhưng **đủ khi hai nơi uy tín KHÁC NHAU cùng đăng cùng nội dung** | #5991, #5997 |
| 8 | **Ba nhóm hồ sơ việc** (văn bản chính thống: luật/tài chính/y tế · học thuật + kỹ thuật · thị trường) + dạng đặc biệt "tài liệu chủ nhà đưa vào"; **mỗi usecase con có trường bắt buộc riêng**; **cứng trường then chốt, mềm phần còn lại**; hiệu lực văn bản **chỉ áp cho usecase cần** | #5987–#5994 |
| 9 | **Main tự quyết hồ sơ việc và nói rõ trong báo cáo** cho chủ nhà đọc | #5995 |
| 10 | **Chỉ main nói với chủ nhà**; main tự chia nhánh + **danh mục nhắc trong skill**; **việc liên quan nhau gộp một con**; **báo tiến độ theo mốc** (mỗi nhánh con xong hoặc ~10 phút); chủ nhà **gõ lệnh giữa lúc chạy** để can thiệp | #5961, #5982, #5969, #5981 |
| 11 | **Ngân sách**: main đề xuất mức + trần thời gian/chi phí; **việc lớn có nút duyệt**; việc nhỏ chạy luôn theo mặc định | #5964 |
| 12 | **Đầu ra 100 % là TỆP**; chat **chỉ có báo cáo ngắn của main** (đã làm gì · được gì · chặn gì · vướng gì) | #5973, #5980 |
| 13 | **Chưa mua khoá tìm kiếm**: keyless trước, **chừa chỗ cắm khoá**, nhiều nhà cung cấp dự phòng, tự thử lại khi bị chặn | #5978 |
| 14 | Terminal trong box chỉ **danh sách trắng hẹp** (curl/wget tải tệp, chạy script có sẵn của skill, đọc/ghi workspace; **không cài gói**); đường chính vẫn ở phía máy chủ | #5977 (chủ nhà giao tự quyết) |
| 15 | **Thang đọc FULL năm tầng**: HTML chính chủ → toàn văn XML/JATS → **PDF + `pdfplumber`** → đầu đọc **chỉ cho chữ** → ảnh trang là đường cuối; bảng phải lấy từ bản cấu trúc khi có, bảng dựng lại ghi rõ "bảng trích tự động" | #6009, #6010; đo `probe8.py` |
| 16 | **Thư viện mới phía MÁY CHỦ**: `pdfplumber` bắt buộc, `pypdfium2` khi cần dựng ảnh trang; **box vẫn không cài gì** | #6011 |
| 17 | **Luật gap hai tầng số**: sàn **≥20 lượt / ≥10 cùng chủ đề / ≥2 nền tảng + 1 nguồn tổng hợp** để gọi "đã kiểm"; đích **30–50 / ≥15 / ≥3 nền tảng** khi dữ liệu đủ; **thiếu mẫu ⇒ ghi "tín hiệu, chưa kiểm" + lý do, dừng sau trần thử, KHÔNG deadlock** | #6006, #6012, #6013 |
| 18 | **Bão hoà săn đuổi trích dẫn ở mức 3: 3 vòng** liên tiếp không thêm bài mới (thay bản nháp 2 vòng) | #6008 |
| 19 | **Thị trường**: giữ đủ **10 usecase TM-1…TM-10**; **TM-3 dùng archetype C2′** (đếm → mẫu → luật); **TM-2 trần đối thủ 10–15** | #5999–#6007 |
| 20 | **Học thuật/kỹ thuật**: paper cần **mã bài + năm + nơi công bố + tác giả + đã mở toàn văn**; **căn cứ trích nguyên văn từ thân bài**, **số liệu lấy từ bảng/hình**; tài liệu hãng & kho mã cần **phiên bản/tag hoặc commit + ngày truy cập**, ghi rõ là tài liệu hãng | #6002, #6003, #6014 |
| 21 | **Số ước lượng/khảo sát**: dùng được nhưng phải ghi rõ "ước lượng · ai ước lượng · năm nào · cỡ mẫu nếu có" **và** cần nơi thứ hai cùng nói | #6000 |
| 22 | **Luật gap hai tầng số — CHỐT** (xác nhận cách ghép #6012 + #6013): sàn 20/10/≥2 + 1 nguồn tổng hợp cho **mọi việc**; đích 30–50/≥15/≥3 khi mức 3 hoặc khi dữ liệu đủ; hết trần thử ⇒ kết luận, đi tiếp | #6016 |
| 23 | **Nhánh con chạy theo SÓNG 3–5**, hết sóng mới mở sóng tiếp; **không mở toàn bộ cùng lúc** (lag box); số sóng tuỳ việc | #6017 |
| 24 | **Hồ sơ mẫu — CHỐT**: mức 1 = 1 tệp · mức 2 = báo cáo + sổ · mức 3 = báo cáo + sổ + `tables/` + `review.md`; **`review.md` ghi rõ hai loại phản biện**: (a) kiểm lại nguồn (gửi con check tiếp), (b) **soi ý kiến/giả định của chủ nhà** | #6019 |
| 25 | **Bảng MỞ-A…MỞ-H: DUYỆT NGUYÊN BẢNG** (box kín, bộ đệm không ghi đĩa, trần đọc 20 000 ký tự/đoạn, công cụ `paper_citations`, mở skill `blocked-page-recovery` → `rss-feeds`, trần USD để mở sau) | #6020 |
| 26 | **KHÔNG mua khoá tìm kiếm** — chỉ thị mới: **tự dựng công cụ tìm kiếm/tải trong harness**; chỗ cắm khoá vẫn giữ trong mã nhưng **mặc định tắt**; hình dạng công cụ chốt ở vòng 13 | #6020 |
| 27 | **Trần thời gian phải phụ thuộc việc** (chủ nhà chưa nhận câu hỏi cũ): ba loại trần — **trần lượt · trần con · ngân sách việc** | #6018 |
| 28 | **Trần thời gian — CHỐT (phương án A):** **trần mềm theo việc** (main tự ước lượng, khai trong thẻ mốc) **+ trần cứng an toàn 30 phút (mức 2) / 120 phút (mức 3)**; chạm trần cứng ⇒ **báo chủ nhà rồi hỏi**, không tự chạy tiếp; **lượt mức 3 có trần lượt mới 3 600 s** (D-40); **trần chờ của con giữ nguyên** | #6021, D-40 |
| 29 | **Số sóng nhánh — CHỐT:** mức 2 = **1 sóng** (3–5 nhánh) · mức 3 = **tối đa 3 sóng** (khoảng 9–15 nhánh), mở sóng tiếp khi còn thiếu bằng chứng (D-41) | #6022, D-41 |
| 30 | **Công cụ tìm kiếm tự dựng — chủ nhà SKIP ⇒ tôi tự quyết:** một công cụ trong harness gộp **nhiều chân keyless** (Firecrawl keyless + OpenAlex/Europe PMC/arXiv/Crossref + trang tìm kiếm chính thức của site); **không mua khoá**; SearXNG/crawler giá **hoãn** (D-42) | #6023, D-42 |
| 31 | **Nhịp kiểm chứng — chủ nhà SKIP ⇒ tôi tự quyết:** mức 2 = **cổng máy tự kiểm** (không mở con phản biện) · mức 3 = **luôn có một con phản biện độc lập** mở lại nguồn trước khi giao | #6024 |
| 32 | **Phản biện ý kiến chủ nhà — CHỐT:** **tự động** khi brief có ý kiến/giả định/khẳng định; pha 4 luôn có **mục riêng ba nhãn**: bằng chứng **ủng hộ / phản bác / chưa chắc** | #6025 |
| 33 | **Ba mục nhỏ tôi tự quyết:** ảnh chụp trang giá **bắt buộc với TM-1** khi giá là số sống và ở **mức 3**; luật cross-nhóm theo **#5995** (main tự mở nhánh + nói rõ trong báo cáo); cổng giữa bốn pha = **ba mốc báo tiến độ** đã có, không thêm cổng chờ người | ghi rõ để chủ nhà chỉnh |

> **Cập nhật 2026-10-06 (PART 1):** hàng 30 nay có bản ghi quyết định đầy đủ — SearXNG **tự host trên loopback** là chân không-khoá mặc định (tự dò `127.0.0.1:8888`), **không mua khoá, không thuê crawler trả giá**: xem `docs/plan/builtin-search-default.md`. **D-42 giữ nguyên hiệu lực** — "hoãn SearXNG/crawler giá" nói về dịch vụ/crawler **phải trả tiền**, còn SearXNG tự host thì không tốn phí và không cần khoá.

## 2. Vấn đề — số đo hôm nay (2026-09-23, HEAD `2add905`, không dùng khoá API)

| # | Sự thật đo được | Bằng chứng |
|---|---|---|
| 1 | **Không giải nén `Content-Encoding`**: Nhân Dân 17 421 · Báo Chính phủ 46 692 · VietnamPlus 37 798 ký tự **rác nhị phân**; rác dài hơn ngưỡng 200 nên đầu đọc không được gọi. Giải nén thủ công: 20 732 → 90 475 byte HTML ⇒ **8 264 ký tự văn bản sạch** | `web.py:147`, `:155`, `:173`; `probe7.log` |
| 2 | Tài liệu dài bị cắt **phía ta**: `docs.python.org/3/whatsnew/3.13.html` trích được **113 936** ký tự, model nhận **8 000 (7 %)**, và 8 000 đầu là điều hướng; **không có `offset`** | `web.py:56-57`, `:505` |
| 3 | Đầu đọc chỉ được gọi khi thân bài **< 200 ký tự**; non-2xx **ném lỗi trước** ⇒ mất `thuvienphapluat.vn` (403, đầu đọc có **91 032 byte**) và mọi PDF | `web.py:159-166`, `:510-518` |
| 4 | **Thành công giả**: `moh.gov.vn` 165–259 byte "chưa tải xong" (hoặc 503 sau 18,5 s); `vbpl.vn` trả tiêu đề "Trang chủ" (27 378 byte) và một trang **404 giả**; tin mọi `http=200` | `probe3/4/7.log` |
| 5 | Đầu đọc keyless **đọc được PDF** (arXiv 15 trang ⇒ **40 895 byte** markdown) và trả **cả tài liệu** (246 743 byte một lời gọi) ⇒ nút thắt 8 000 là của ta | `feasibility-probes.md` §1 |
| 6 | Nguồn học thuật keyless: OpenAlex 200 (`referenced_works` n=54; `filter=cites:` **count=1255**), Europe PMC 200, Crossref chập chờn (429→200), arXiv chập chờn (406→200), **Semantic Scholar 429 lặp lại** | `probe3/4/5.log` |
| 7 | Tìm kiếm còn **một chân keyless** (Firecrawl): `site:`, `tbs=qdr:m`, `lang=vi` chạy; `sources=['news']` và `page=2` ⇒ **400**; không retry/cache/khử trùng | `web.py:385`, `:464-483`; `probe4.log` |
| 8 | **Không cổng nào kiểm nguồn cho câu trả lời research**: `evidence_gate` **không có** khái niệm URL/citation | `evidence_gate.py:122-124`, `:420-483` |
| 9 | **Không có vòng phản biện cho research** (vòng bị cưỡng chế duy nhất là `plan-review`/`plan_verify` + sổ) | `runtime.py:4496-4607`, `roles.py:157` |
| 10 | Con research **không có `file_write`** (`roles.py:18`); câu trả lời con cắt **8 000** (`runtime.py:1015`); `await_children` gói **16 000** (`limits.py:135`) ⇒ hồ sơ dài **không bao giờ** về tới main | `roles.py:18`, `runtime.py:1015`, `limits.py:135` |
| 11 | Đang chạy lượt thì prompt thường bị **409 `SESSION_BUSY`** ⇒ "gõ lệnh giữa lúc chạy" (#5981) cần đường mới; khe bơm chữ giữa lượt **đã có tiền lệ** (`drain_peer_deliveries`) | `runtime_commands.py:39-41`, `server.py:150`, `runtime.py:4932-4965`, `:3024` |
| 12 | **Không có case đo research**: `benchmark/cases/*` rỗng (chỉ `.gitkeep`), `scripts/eval/results/tier0-regression/scores.jsonl` **không tồn tại**, judge runner `NotImplementedError` (`--execute` exit 5) | `benchmark/`, `scripts/eval/judge.py:176` |
| 13 | Skill chuyên môn **chết**: `grounded-citations` gọi `web_extract` (không tồn tại — tool thật là `web_fetch`) 5 lần, `skill_view` không tự chạy script, không ai đặt `HERMES_HOME`; các skill web/research không nằm trong `DEFAULT_SKILLS` | `tool_contracts.py:64-69`, `skills/catalog.py:7-14` |
| 14 | Box **không có Internet** mặc định (`iptables -P OUTPUT DROP`), không có `pdftotext/tesseract/pypdf/bs4/lxml`, **có** `curl`, `wget`, `node` | đo trong container; `docs/architecture/sandbox.md:203-210` |
| 15 | **Đọc FULL có năm đường, chất lượng khác nhau**: HTML chính chủ arXiv **10 bảng** thật (188 707 byte) · Europe PMC JATS **6 bảng** (102 171 byte) · đầu đọc trên PDF 40 895 byte chữ tốt nhưng **bảng MẤT** (0 dòng có `\|`) · `pdfplumber` dựng lại **10 bảng** từ PDF gốc (15 trang, 35 511 ký tự) | `probe8.log`, `probe8.json` (2026-09-23) |
| 16 | Tiêu đề nhiều tầng của bảng dựng lại **có thể lệch** (ví dụ `train N d d h d d P ϵ model ff k v drop ls steps`) ⇒ khẳng định then chốt dựa vào bảng phải đối chiếu câu văn quanh bảng hoặc mở bản HTML/JATS | `probe8.log` |
| 17 | Số ước lượng thị trường **không tự kiểm được**: chỉ dùng khi có "ai ước lượng · năm nào · cỡ mẫu" + nơi thứ hai | #6000 (yêu cầu chủ nhà) |

## 3. Kiến trúc — ba lớp khớp vào nhau thế nào

### 3.1 Lớp A — đọc thật (đợt 1–2)
Bốn tầng nhỏ, mỗi tầng đo được:

```
http_request (xin gzip/deflate)  →  reading.decode_body (giải nén, trần chống bom)
   →  html_to_text / passthrough  →  reading.body_check (ok · thin · junk · error-page · wrong-page · empty)
   →  bộ đệm đọc (trong tiến trình, LRU)  →  payload ≤ 20 000 ký tự + ref + nextOffset
   →  read_source(ref, offset, find)  cắt tiếp KHÔNG tải lại   →  thang đọc khi PDF/non-2xx/rác/thiếu chữ
```

- **Thang đọc FULL năm tầng (chốt vòng 11, #6010):** (1) **HTML chính chủ** (arXiv HTML, trang tạp chí/nhà xuất bản, PMC HTML)
  → (2) **toàn văn XML/JATS** (Europe PMC `fullTextXML`, PMC OA) → (3) **PDF + `pdfplumber`** phía máy chủ (bảng **dựng lại**,
  ghi rõ "bảng trích tự động") → (4) **đầu đọc** (chỉ **cho chữ** — đo được là mất sạch bảng) → (5) **ảnh trang + đọc ảnh**
  (đường cuối, cần `pypdfium2`). Lý do có thang, không có một đường: bản HTML giữ **10 bảng** thật, đầu đọc trên cùng bài
  giữ **0** (`probe8.log`).
- **Chỉ số rác** là thứ biến "thành công giả" thành chuyện máy phát hiện được: rác đo **0,52–0,55**, văn bản thật **0,0000**.
- `read_source` là công cụ trả lời đúng câu #5966 ("mở thật + lấy đoạn liên quan"): đọc trọn `docs.python.org` bằng **6 lời gọi** thay vì 1 lời gọi 7 %.
- Tìm kiếm: nhiều truy vấn một lượt, khử trùng theo URL chuẩn hoá, `site:`/`tbs`/`lang`, cache 5 phút, retry/backoff;
  **tự dựng công cụ** gộp nhiều chân keyless (Firecrawl keyless + OpenAlex + Europe PMC/Crossref + trang tìm kiếm chính
  thức của site) — **không mua khoá** (chốt #6020); chỗ cắm khoá Brave/Tavily vẫn giữ trong mã nhưng **mặc định tắt**,
  chỉ bật khi chủ nhà cấp khoá.
- **Giao cho B:** hàm thuần `reading.body_check(...)` để `source_verify` ra `ok` / `fakeSuccess` / `unreachable` — B không chép lại luật.

### 3.2 Lớp B — nghiên cứu có sổ (đợt 3–4)
- **Sổ nguồn** (`source_ledger`): mỗi khẳng định ↔ URL ↔ **đoạn trích nguyên văn** ↔ ngày lấy ↔ tầng ↔ **nguồn tin gốc** ↔ đã mở bản gốc chưa ↔ **loại bản đã đọc** (`html` · `jats` · `pdf-table` · `reader-text` · `page-image`) ↔ **phiên bản/tag hoặc commit + ngày truy cập** (nhóm học thuật/kỹ thuật, #6014).
- **Thang nguồn 4 tầng + tầng 0 "tài liệu chủ nhà"** cứng trong mã, đổi bằng `BOXFOX_SOURCE_TIERS`; nhánh `official-social` cho trang chính thức của cơ quan trên mạng xã hội.
- **Ba nhóm hồ sơ việc** + usecase con có trường bắt buộc riêng (bảng khai báo, sửa được không cần đụng luật).
- **Cổng chất lượng riêng** `research_quality.py` (13 mã lỗi + câu khắc phục) — **không** nhét citation vào `evidence_gate` (D-18); công tắc ba mức kiểu `BOXFOX_PLAN_SOURCES_GATE`; cổng chạy **trước** khi ghi hồ sơ, và ghi sổ hỏng chỉ **log rồi đi tiếp**.
- **Pha phản biện**: vai con riêng `research-review` (kiểu `plan-review` vòng 25), kết thúc bằng **dòng cuối** `VERDICT: ok|revise`; `research_verify` ghi sổ `research_verifications`; **`revise` chặn MỘT vòng** rồi hồ sơ mang nhãn **do máy viết** "CHƯA ĐẠT".
- Đếm nguồn **độc lập máy kiểm được**: cùng nguồn tin gốc ⇒ một nguồn; tầng 1 một nguồn là đủ.

### 3.3 Lớp C — luồng chạy (đợt 5–6)
- **`research_brief`** chốt **một mức cho cả việc** + **bảng trần**: trần **mềm theo việc** (main ước lượng, khai trong thẻ
  mốc) với **trần cứng an toàn 30 phút (mức 2) / 120 phút (mức 3)**, chạm là báo + hỏi; lượt mức 3 được **3 600 s** (D-40);
  **sóng nhánh 3–5** (mức 2 = 1 sóng · mức 3 ≤ 3 sóng, D-41); skill `research-team` giữ danh mục nhắc nhánh và SOP bốn pha.
- **`dossier_write`** + phòng `.research/<slug>/` trong workspace: `v1-<slug>.md` (hồ sơ), `sources.jsonl` (sổ), `sources.md` (bản người đọc) — **đầu ra 100 % là tệp**; chat chỉ còn báo cáo ngắn, có **hàng tệp** mở sang panel Tệp.
- **Nhịp báo tiến độ** theo mốc (mỗi nhánh con xong **hoặc** ~10 phút) bằng **văn bản model viết** trong mạch chat — không khối, không dải, không huy hiệu (D-19…D-25).
- **Steer giữa lượt**: bảng `session_steers` + `drain_steers` cạnh `drain_peer_deliveries` (tiền lệ đã có), công cụ `cancel_child`; giao diện: ô nhập nói rõ "xếp hàng · áp ở bước kế" (mockup `v27-run-queue.html`).
- **Ngân sách + duyệt việc lớn**: nối vào `request_approval` sẵn có (`action='research-budget'`) + `extend_turn_budget` theo mức; thẻ duyệt trong chat (mockup `v27-level-approval.html`).

### 3.4 Luồng mới của một việc nghiên cứu

```
chủ nhà hỏi → main đọc tín hiệu, chốt MỘT mức + hồ sơ việc + trần (việc lớn: xin duyệt)
  → pha 1 BẢN ĐỒ: main chia nhánh con theo danh mục, mỗi con đọc nguồn thật (read_source/web_fetch, không trích snippet)
  → con `source_add` từng khẳng định kèm đoạn trích nguyên văn + nguồn tin gốc  [sổ nguồn]
  → pha 2 CHỐT: main gom bản đồ, chốt chỗ còn thiếu, báo tiến độ theo mốc; chủ nhà gõ lệnh giữa lượt nếu muốn
  → pha 3 ĐÀO SÂU: mức 3 săn đuổi trích dẫn lùi + tiến tới bão hoà; mâu thuẫn ⇒ bảng đối chiếu
  → `dossier_write`: CỔNG CHẤT LƯỢNG chạy TRƯỚC khi ghi (tầng, số nguồn độc lập, trường bắt buộc, bản gốc)
  → pha 4 PHẢN BIỆN ĐỘC LẬP: con `research-review` mở lại nguồn, kiểm dòng khai "nguồn tin gốc"
       → VERDICT: ok ⇒ giao hồ sơ; revise ⇒ sửa MỘT vòng ⇒ còn revise ⇒ giao kèm nhãn "CHƯA ĐẠT"
  → main báo cáo NGẮN trong chat + hàng tệp hồ sơ (tệp là sản phẩm, chat chỉ là báo cáo)
```

---

## 4. Tám đợt thi công (thứ tự bắt buộc)

| Đợt | Nội dung | Mã việc | Phụ thuộc | **Điều kiện dừng / cách đo** |
|---|---|---|---|---|
| **1** | Lớp đọc sống lại: giải nén `Content-Encoding`, `reading.body_check`, **thang đọc FULL năm tầng (HTML/JATS → PDF + `pdfplumber` → đầu đọc chỉ chữ → ảnh trang)**, ba công tắc | A-1, A-2, A-3, A-9, **A-10** | — | Ba trang gzip ra **junk 0,0000** (`textChars` ≈ 8 264 / 8 079 / 16 455); 403 (`thuvienphapluat.vn`) và PDF arXiv đọc được (**bảng dựng lại** kèm nhãn "bảng trích tự động"); HTML arXiv `1706.03762v7` giữ **10 bảng**; `vbpl.vn`/`moh.gov.vn` **không** ra `ok`; `BOXFOX_WEB_READER=thin` xanh **toàn bộ** test cũ |
| **2** | Đọc trọn tài liệu: bộ đệm + `read_source(offset/find)` + `file_read` có `offset` + **công cụ tìm kiếm tự dựng gộp nhiều chân keyless** (D-42) | A-4, A-5, A-6 | 1 | `docs.python.org` (113 936 ký tự) đọc trọn bằng **6 lời gọi**, ghép lại đúng bản gốc; tệp 100 000 ký tự trong box đọc trọn; hai chân tìm kiếm độc lập trả kết quả cho cùng một truy vấn; ảnh PNG giữ nguyên hình dạng cũ |
| **3** | Sổ nguồn + thang nguồn 4 tầng (+ tầng 0 tài liệu chủ nhà, nhánh `official-social`) + trường **loại bản đã đọc** và **phiên bản/commit/ngày truy cập** | B-1, B-2 | 1 | Chạy lại 5 URL đã đo ⇒ `fakeSuccess`/`unreachable` đúng ca; sổ ghi/đọc được 3 dòng sống **có `bản đã đọc`**; test `test_source_ledger_store.py`, `test_source_tiers.py` xanh |
| **4** | Ba nhóm hồ sơ việc + cổng chất lượng + `dossier_write` (phòng `.research/`) + bảng khai báo thị trường (**TM-2 trần 10–15**, **TM-3 archetype C2′** hai tầng số + luật "không đủ mẫu ⇒ tín hiệu, chưa kiểm") | B-3a, B-3b, C-2 | 3 | 6 ca hàm thuần + **3 ca vi phạm bị từ chối và KHÔNG tạo tệp**; hồ sơ nháp ra đủ 3 tệp (`v1-*.md`, `sources.jsonl`, `sources.md`); ca gap thiếu mẫu ghi đúng "tín hiệu, chưa kiểm" |
| **5** | Ba mức + `research_brief` + skill `research-team` + SOP bốn pha + nhịp báo mốc + săn đuổi trích dẫn mức 3 (**bão hoà 3 vòng**) + **nhánh con theo sóng 3–5** (mức 2 = 1 sóng · mức 3 ≤ 3 sóng) + **trần mềm theo việc + trần cứng 30/120**, lượt mức 3 = **3 600 s** (D-40) | C-1, C-3, C-4 | 4 | Một lượt thật chạy mức 2 và một lượt mức 3; mốc báo xuất hiện đúng nhịp; thẻ mốc khai đúng trần mềm + trần cứng; ca `R1–R4`, `R10` xanh |
| **6** | Pha phản biện độc lập: vai `research-review`, `research_verify`, sổ `research_verifications`, nhãn "CHƯA ĐẠT"; **mức 2 = cổng máy tự kiểm · mức 3 = luôn có con phản biện**; `review.md` ghi **hai loại phản biện** + **mục soi ý kiến chủ nhà** (ủng hộ / phản bác / chưa chắc — #6019, #6025) | B-4 | 4 | 4 ca sống: `ok` ⇒ giao hồ sơ; `revise` ⇒ sửa **một** vòng; còn `revise` ⇒ giao kèm nhãn do **máy** viết; phản biện giả (không có phiên con hợp lệ) bị chặn; ca brief có ý kiến chủ nhà ⇒ `review.md` có đủ ba nhãn |
| **7** | Can thiệp giữa lượt (`session_steers`, `drain_steers`, `cancel_child`) + ngân sách/duyệt việc lớn + hai mặt giao diện | C-5, C-6 | 5 | Gõ "dừng nhánh luật" giữa lượt ⇒ nhánh dừng ở bước kế, có dòng xác nhận; việc lớn ra thẻ duyệt đúng mức + trần; `extend_turn_budget` theo mức chạy |
| **8** | Sửa skill chết + tài liệu lệch + bộ ca `R1–R9` + oracle máy + ghi sổ theo dõi | B-5, B-6, C-7, C-8 | 1–7 | `test_skill_tool_names.py` xanh (không còn `web_extract`); hai tài liệu lệch đã sửa; `scripts/eval/research_checks.py` chạy được và **số** ghi vào `docs/tracking/test-rounds.md` |

Ghi chú thi công:
- Đợt 1–2 và đợt 3–4 có thể **chạy song song theo tệp** (A sở hữu `web.py`/`worker.py`; B sở hữu module + bảng SQLite mới); chỉ đợt 4 cần `reading.body_check` của A.
- Mọi sửa tệp `backend/**`, `docs/tracking/*` giữ **đúng CRLF/LF của tệp gốc**; dùng `patch.py` cho tệp CRLF.
- Test đầy đủ chạy từ **gốc repo** với `--deselect backend/tests/unit/test_terminal_tools.py::test_terminal_exec_echo`; frontend: `VITE_BOX_API_URL=http://localhost:8081 npx vitest run` + `tsc -b --noEmit`.
- Không rebuild box (thêm op box là an toàn vì `worker.py` đi kèm tiến trình harness), không restart/kill tiến trình chủ nhà.
- **Phụ thuộc mới (chốt #6011):** `pdfplumber` bắt buộc, `pypdfium2` khi cần dựng ảnh trang — cài **phía máy chủ harness** (ghi vào danh sách phụ thuộc khi thi công đợt 1); **box không cài gì**.

## 5. Đo "thật kỹ" — bộ ca và oracle

| Ca | Nội dung | Cách chấm (máy) |
|---|---|---|
| R1 | Đọc trọn tài liệu dài: 113 936 ký tự bằng 6 lời gọi, không có đoạn nào là điều hướng | Ghép `offset` ⇒ so với bản tải trực tiếp; tỉ lệ điều hướng < ngưỡng |
| R2 | Trang nén: Nhân Dân/Báo Chính phủ/VietnamPlus ra văn bản sạch | `junkRatio` < 0,01 và có ≥ 1 câu thân bài |
| R3 | Không tin `http=200`: `vbpl.vn` 404 giả, `moh.gov.vn` 165–259 byte | `body_check` trả `error-page`/`thin`, **không** `ok` |
| R4 | Bão hoà săn đuổi trích dẫn ở mức 3 | Dừng sau **3 vòng liên tiếp không thêm bài mới** (chốt #6008) hoặc chạm trần bài (nháp: 30/50/100 theo mức) |
| R5 | Hai nguồn độc lập: ba bài chép cùng một tin ⇒ **một** nguồn | Sổ nguồn đếm theo `nguồn tin gốc`, không đếm theo URL |
| R6 | Bản gốc vs báo chính thống: khẳng định về nội dung văn bản phải trỏ bản gốc **hoặc** ghi rõ "chưa mở được bản gốc" | `research_quality` mã lỗi tương ứng |
| R7 | Giao hồ sơ: tệp ra đủ, chat chỉ có báo cáo ngắn + hàng tệp; phản biện `revise` để lại nhãn | Kiểm tệp trên đĩa + phần đầu hồ sơ + sổ `research_verifications` |
| R8 | **Bảng biểu**: paper có bản HTML/JATS ⇒ bảng lấy từ bản cấu trúc; chỉ có PDF ⇒ `pdfplumber` dựng lại **kèm nhãn "bảng trích tự động"**; khẳng định dựa vào bảng có đối chiếu câu văn quanh bảng hoặc bản cấu trúc | Đếm bảng trong hồ sơ + trường *loại bản đã đọc* trong sổ (`html`/`jats`/`pdf-table`) |
| R9 | **Gap hai tầng số**: đủ sàn ⇒ "đã kiểm"; chưa đủ sàn mà hết trần thử ⇒ ghi **"tín hiệu, chưa kiểm" + lý do**, **không** treo lượt | `research_quality` mã lỗi tương ứng + không có vòng lặp thử vô hạn |
| R10 | **Sóng nhánh**: con chỉ mở theo sóng **3–5**, sóng sau chỉ mở khi sóng trước xong; **không** mở toàn bộ cùng lúc (tránh lag box); mức 2 = 1 sóng, mức 3 ≤ 3 sóng | Đếm nhánh đồng thời theo thời gian trong nhật ký (`T/P/S/E/D/C/F/X`) |
| R11 | **Trần mềm + trần cứng**: thẻ mốc khai trần ước lượng của việc; chạm trần cứng (30 phút mức 2 / 120 phút mức 3) ⇒ **báo + hỏi chủ nhà**, không tự chạy tiếp; lượt mức 3 có trần lượt 3 600 s | Đọc thẻ mốc + dòng báo; đo lượt mức 3 không bị cắt ở 1 200 s |
| R12 | **Soi ý kiến chủ nhà**: brief có ý kiến/giả định ⇒ `review.md` có mục riêng đủ ba nhãn **ủng hộ / phản bác / chưa chắc**, mỗi nhãn kèm nguồn | Kiểm tệp `review.md` của ca có brief chứa ý kiến |

**Trung thực về đo lường:** `benchmark/cases/*` đang rỗng và judge runner là `NotImplementedError` ⇒ vòng này **tự dựng** oracle máy (`scripts/eval/research_checks.py`), **không** tuyên bố "đã có benchmark research". Mọi số phải ghi **ngày đo + tệp đo**.

## 6. Giao diện (mockup kèm kế hoạch)

| Mặt | Tệp mockup | Thay đổi thật |
|---|---|---|
| Ô nhập khi lượt đang chạy | `designs/v27-run-queue.html` | Composer gửi được **chỉ thị cho lượt đang chạy** ("xếp hàng · áp ở bước kế"), khác hẳn gửi thành lượt mới; có dòng xác nhận khi nhánh đã dừng |
| Mốc tiến độ | `designs/v27-progress-milestones.html` | Báo tiến độ là **văn bản model viết** trong mạch chat (không khối/dải/huy hiệu); im > 10 phút ⇒ có nhịp mới |
| Báo cáo cuối + hàng tệp | `designs/v27-report-files.html` | Báo cáo ngắn của main + **hàng tệp hồ sơ** mở sang panel Tệp workspace; có dòng "việc này tôi xếp nhóm …"; nhãn "CHƯA ĐẠT" do máy viết khi phản biện còn `revise` |
| Thẻ duyệt việc lớn | `designs/v27-level-approval.html` | Thẻ trong chat: mức · số nhánh · trần thời gian/token · sẽ giao gì; nút Duyệt & chạy / Sửa trần / Huỷ (nối `request_approval` sẵn có) |

Không có màn hình mới; hồ sơ đọc bằng **panel Tệp workspace có sẵn**. Chạm chữ duy nhất ngoài bốn mặt: ghi chú nhóm `webResearch` trong `HarnessEditor.tsx` (thêm `read_source`) + fixture tương ứng.

## 7. Bất biến và xung đột phải giữ

- **D-18** không thêm tiêu chí citation vào `evidence_gate.py` (cổng research là module **mới**).
- **D-19…D-25** không khối/dải/huy hiệu quanh câu trả lời cuối; **D-26…D-32** hình dạng sống trong skill.
- **D-13** không mở tool song song trong một step (cờ `BOXFOX_PARALLEL_READ_TOOLS` giữ **trơ**); **D-11** con không sinh anh em; **D-12/D-10** trần chờ là lưới an toàn; **D-14** không nâng cổng lên `enforce`.
- **R10-6** không âm thầm bỏ `web_search`/`web_fetch` khỏi bộ công cụ orchestrator; **§5(1)** không thêm giá trị `status` mới; **§5(5)** `events()` trần 500 hàng ⇒ bảng mới tự lọc.
- Cổng chạy **trước khi ghi** và chỉ là **lớp bổ sung**; ghi sổ hỏng ⇒ **log rồi đi tiếp** (sổ không bao giờ giết một quyết định).
- Giữ nguyên hai cổng plan của vòng 25 (`plan-review`/`plan_verify` + hai sổ) — không sửa, chỉ học khuôn.
- **An toàn**: `assert_public_url`/`_GuardedRedirects` phải **ném lỗi**, không lùi về đầu đọc; mọi payload giữ `untrusted: true`; nhật ký DEV không chứa truy vấn/URL.
- **F19**: không được nói "đã có benchmark research".
- Test đếm công cụ phải cập nhật: 25 → **31** (B) — cộng `read_source`/`paper_citations` của A ⇒ con số cuối chốt khi thi công đợt 1–3.

## 8. Trạng thái phỏng vấn (ba mảng của #5998)

Chủ nhà đã chốt: *"còn thị trường và paper/kỹ thuật, phương pháp thì chưa… tạo plan trước, ghi vào plan trước rồi tiếp tục interview"*.

| Mảng | Trạng thái | Chốt ở đâu |
|---|---|---|
| **Thị trường** | **ĐÃ CHỐT** (vòng 9–10) | §1 hàng 19 & 21; `v27-market-usecases.md` (TM-1…TM-10, C2′) |
| **Học thuật & kỹ thuật** | **ĐÃ CHỐT** (vòng 9, 11) | §1 hàng 15, 18, 20; `v27-full-read-and-pain-count.md` |
| **Đọc FULL tài liệu** | **ĐÃ CHỐT** (vòng 11) | §1 hàng 15, 16; §3.1 thang năm tầng |
| **Đếm nỗi đau (gap)** | **ĐÃ CHỐT** (vòng 10–11) | §1 hàng 17; luật hai tầng số |
| **Phương pháp** | **ĐÃ CHỐT** (vòng 12–13) | §1 hàng 22–33; §3.3 bảng trần; D-40…D-42 |

**Phương pháp — ĐÃ CHỐT (vòng 12–13):** luật gap hai tầng số (#6016) · **sóng 3–5** với mức 2 = 1 sóng / mức 3 ≤ 3 sóng
(#6017, #6022) · **hồ sơ 1/3/6 tệp** + hai loại phản biện (#6019) · **trần mềm theo việc + trần cứng 30/120**, lượt mức 3
= 3 600 s (#6021, D-40) · **công cụ tìm kiếm tự dựng gộp chân keyless, không mua khoá** (#6020, #6023, D-42) · **nhịp kiểm
chứng** mức 2 cổng máy / mức 3 con phản biện (#6024) · **tự động soi ý kiến chủ nhà** (#6025) · ba mục nhỏ do tôi tự quyết
(§1 hàng 33). **Phỏng vấn đã đóng; chờ chủ nhà duyệt bản 3.**

**Bảy câu kỹ thuật MỞ-A…MỞ-H — chủ nhà DUYỆT NGUYÊN BẢNG ở #6020** (riêng MỞ-C đổi hướng: tự dựng, không mua khoá):

| # | Câu hỏi | Phương án đã duyệt | Trạng thái |
|---|---|---|---|
| MỞ-A | Ngân sách đọc theo mức và trần mỗi đoạn | Giữ **trần 20 000 ký tự/đoạn** (trần ngữ cảnh là ràng buộc cứng); khác nhau ở **số lần đọc** | Đã duyệt (#6020) |
| MỞ-B | Có **bật mạng trong box** để dùng `browser_use`/terminal cho cổng JS (`moh.gov.vn`, `vbpl.vn`) không? | **Không** vòng này: box kín, `browser_use` trả lỗi có mã trong < 5 s | Đã duyệt (#6020) |
| MỞ-C | ~~Mua khoá tìm kiếm nào trước~~ → **đổi hướng** | **Không mua khoá**: **tự dựng công cụ** gộp chân keyless trong harness; chỗ cắm khoá Brave/Tavily giữ trong mã nhưng **mặc định tắt**; hình dạng công cụ chốt vòng 13 | Đã duyệt, **đổi hướng** (#6020) |
| MỞ-D | "Bão hoà" săn đuổi: ngưỡng nào, và săn đuổi là **công cụ riêng** hay tham số? | **3 vòng** liên tiếp không thêm bài mới (#6008); công cụ riêng `paper_citations` | Đã duyệt (#6020) |
| MỞ-E | Mở skill web/research nào | Mở `blocked-page-recovery` → `rss-feeds`; `duckduckgo-search`/`searxng-search` **đóng vĩnh viễn** kèm lý do đo được; `pdf`/`scrapling` sau | Đã duyệt (#6020) |
| MỞ-F | Bộ đệm đọc có ghi ra đĩa không | **Không** — trong bộ nhớ tiến trình (không để nội dung không tin cậy trên đĩa) | Đã duyệt (#6020) |
| MỞ-G | **Trần lượt cho mức 3**: trần lượt hiện tại 1 200 s có thể chặn việc dài | **Đã chốt #6021**: trần **mềm theo việc** + **trần cứng an toàn 30 phút (mức 2) / 120 phút (mức 3)**, chạm thì báo + hỏi; lượt mức 3 được **3 600 s** (D-40); trần chờ của con **giữ nguyên** | Đã chốt (#6021) |
| MỞ-H | **Trần chi phí USD**: router có `cost`/`costBasis` nhưng harness **chưa nhận** trường đó | Nêu trần bằng **giây + token** trước; USD để mở sau khi harness nhận được số | Đã duyệt (#6020) |

## 9. Không làm trong vòng này

- Không sửa `evidence_gate.py`, `plan_quality.py`, `compression.py`, `plan_eval.py`; không nâng cổng bằng chứng lên `enforce`.
- Không mở tool song song trong một step; không cho con sinh con; không cho con research quyền ghi tự do (chỉ `dossier_write`/`source_add` có kiểm).
- Không UI mới ngoài bốn mặt ở §6; không light-theme; không thêm khối/dải quanh câu trả lời cuối.
- Không bật mạng cho box, không cài gói, không rebuild box, không restart tiến trình chủ nhà.
- **Thư viện**: chỉ thêm **`pdfplumber`** phía **máy chủ** (+ `pypdfium2` khi cần dựng ảnh trang) — chủ nhà cho phép ở #6011; phần còn lại dùng chuẩn (`zlib`, `gzip`, `html.parser`, `urllib`); **box không cài gì**; không dùng `sources=`/`page=` của Firecrawl (đo được: 400); không thêm giá trị cho enum `source`.
- Không hứa đọc được **trang chỉ chạy JS** ở vòng này.

## 10. Rủi ro và cách chặn

| Rủi ro | Cách chặn |
|---|---|
| Mức 3 dài hơn trần lượt ⇒ lượt chết giữa lúc nghiên cứu | **Đã chốt #6021 (D-40)**: lượt mức 3 được **3 600 s**; trần **mềm theo việc** + trần cứng 120 phút, chạm là báo + hỏi; `extend_turn_budget` theo mức; **không** nới trần chờ của con |
| Mảng **phương pháp** còn mở, chốt muộn ⇒ phải sửa nhiều chỗ | Mọi luật hồ sơ nằm trong **bảng khai báo**; đợt 1–3 độc lập với mảng đó; phần đã chốt (thị trường, học thuật, đọc FULL) đã vào bản 2 |
| Trần 8 000 ký tự của con vẫn cắt hồ sơ | Đường chính là **ghi tệp** (`dossier_write`) + `read_source` đọc theo đoạn; trần câu trả lời chỉ dùng cho báo cáo ngắn |
| Nguồn keyless chập chờn (arXiv 406, Crossref 429, Semantic Scholar 429) | Retry/backoff + nhiều nhà cung cấp + ghi rõ nguồn nào chập chờn; Semantic Scholar **chỉ bật khi có khoá** |
| Cổng nguồn quá chặt làm việc nhỏ chậm | Cổng có **công tắc ba mức** (`enforce`/`warn`/`off`) và **mức 1 chỉ cần đọc thật**, không bắt hai nguồn |
| Đo lường bị "khoe" quá mức | §5: oracle máy, ghi ngày đo + tệp đo; F19 cấm nói "đã có benchmark research" |
| Vi phạm bất biến khi thi công | §7 + `subplans/*-plan.md` mục "KHÔNG làm"; review từng 3 việc như thường lệ |

## 11. Điều kiện bắt đầu thi công

1. Chủ nhà **duyệt kế hoạch này** (bản 3 — phỏng vấn đã đóng) ⇒ **đợt 1–3 bắt đầu ngay** (không phụ thuộc gì thêm).
2. Đã chốt hết ba mảng của #5998 (thị trường · học thuật/kỹ thuật · phương pháp) trong **13 vòng**; ba mục nhỏ do tôi tự quyết
   ghi rõ ở §1 hàng 33 — chủ nhà chỉnh lúc nào cũng được.
3. Mỗi đợt xong: chạy test đầy đủ, ghi số vào `docs/tracking/test-rounds.md`, cập nhật `docs/tracking/bug-register.md` nếu phát hiện lỗi, ghi quyết định mới vào `docs/tracking/owner-decisions.md`.
3. Mỗi đợt xong: chạy test đầy đủ, ghi số vào `docs/tracking/test-rounds.md`, cập nhật `docs/tracking/bug-register.md` nếu phát hiện lỗi, ghi quyết định mới vào `docs/tracking/owner-decisions.md`.

