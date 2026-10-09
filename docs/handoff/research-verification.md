# Handoff — kiểm nghiệm research (vòng 29, đợt 4: phần offline)

- Branch: `vorflux/v27-research-rework` (cây đang sửa, chưa commit cho đợt này)
- Pull request: chưa mở cho đợt này
- Đợt 4 của vòng 29 làm phần **offline, 0 đồng, không gọi nhà cung cấp nào**: một giàn probe provider GIẢ
  hai tầng, bốn sửa nhỏ đo được từ các lượt thật, và chính tài liệu này. Lượt research SỐNG vẫn là việc
  của đợt sau (mục `### 1.` và `### 2.`).
- Ghi chú vị trí: lúc viết, tệp khuôn của các handoff trước còn nằm **phẳng** ở gốc `docs/`; tệp này
  nằm trong thư mục `docs/handoff/` theo đúng yêu cầu của đợt. Người đọc sau đi tìm ở gốc `docs/` thì đó
  là lý do. *(2026-10-09: mọi handoff đã gom về `docs/handoff/`; tệp khuôn nay là
  `docs/handoff/router-settings.md`, và điểm bắt đầu là `docs/handoff/README.md`.)*

## Trạng thái

Điều phải đọc trước mọi thứ khác, **nguyên văn**:

> đợt 29 chỉ chứng minh bằng unit test; nó KHÔNG chứng minh một lượt research thật giờ chạy xong — đợt này không gọi nhà cung cấp nào.

Đã có trong tay:

- Sáu lượt research Y TẾ **thật** trên app thật (harness scratch cổng `3151`), đo ngày 2026-09-24 — nguồn
  của mọi con số ở mục dưới. Đọc đầy đủ ở `docs/tracking/test-rounds.md` §*"Lượt research Y TẾ THẬT"*
  (từ dòng 2607) và `/var/tmp/v28/rounds_live_runs2.md`.
- Vòng khoá router (đợt 3 của vòng 29): một connection giữ **danh sách khoá có thứ tự**, router xoay khoá
  khi gặp HTTP **429**, khoá vừa cháy **nghỉ 30 s** (theo `retry-after` thì được **nâng nhưng không quá
  2 phút**), tối đa **10 khoá** một connection, chỉ `prefix` ≤ 6 ký tự rời khỏi router, xoá connection còn
  khoá thì bị từ chối (409), bỏ khoá cuối thì connection sống với vòng rỗng (`authState: 'required'`).
- Bốn sửa nhỏ offline của đợt này (mục `## Kiểm tra đã đạt tại commit`): khớp tiêu đề hồ sơ, câu khắc phục
  `research-claim-single-source`, mô tả `ceilingSeconds` trong hợp đồng `research_brief`, và câu tài liệu
  lệch ở `scripts/eval/benchmarks/tier-r1.md`.

Vẫn CHƯA có: một lượt research thật nào ghi ra `.research/**`; một dòng điểm thật nào trong
`scripts/eval/results/tier-r1-research/scores.jsonl`; `manifest.json` vẫn `measured: false`; **C-7** còn
mở; **F19** vẫn cấm câu "đã có benchmark research".

## Đã chứng minh được (sáu lượt research THẬT — đây là giá trị của lượt kiểm nghiệm)

| Lần | Khoá | Sổ nguồn | Hồ sơ | Kết thúc lượt | Ghi chú đo được |
|---|---|---|---|---|---|
| 1 `0d0fe166` | OpenCode Free | 13 hàng | không (từ chối 1 lần) | `failed` — `UPSTREAM_HTTP_502` bước 22, 13,8 phút | 3 nhánh con `research` xong (9–13 bước) |
| 2 `30003232` | OpenCode Free | 24 hàng | không | `failed` — `UPSTREAM_HTTP_502` bước 15, 13,7 phút | 502 ⇒ theo luật §2.3 thử lại 1 rồi **chuyển khoá** (nên lần 3 đổi sang key 1) |
| 3 `b5832e29` | key 1 | 9 hàng | không (từ chối 2 lần) | `completed partial` — `DEADLINE_EXCEEDED` bước 30, 20,2 phút, 41 tool | xin `ceilingSeconds: 1200` ⇒ `TURN_EXTENDED +600 s` (trần cứng mức 2 = 1800 s); lượt ĐẦU tới được `dossier_write` |
| 4 `bc8d9125` | key 1 | 9 hàng | không (từ chối 1 lần) | `failed` — `UPSTREAM_HTTP_502` bước 21, 13,0 phút | 2 lần JSON tham số hỏng; 3 hàng `type: confirm` cùng host ⇒ `independent` đứng ở 2 |
| 5 `6e274b19` | key 1 | 2 hàng | không (không kịp ghi) | `failed` — `DEADLINE_EXCEEDED` đúng **600 s**, bước 2 | xin `ceilingSeconds: 600` (bằng đúng hạn mức đang chạy) ⇒ **không** có `TURN_EXTENDED`; chết khi chờ nhánh con thứ ba |
| 6 `5e689d49` | key 1 | 0 hàng | không (không kịp ghi) | `failed` — `UPSTREAM_HTTP_502` bước 14, 8,5 phút | **có** `TURN_EXTENDED +600 s`, nhưng nhà cung cấp cắt trước khi model gọi `source_add` lần nào |

Năm kết luận đo được (nguyên văn của sổ):

1. **Đọc nguồn là thật** — mọi hàng sổ có URL mở bằng `web_fetch`/`web_search` và một đoạn trích nguyên
   văn 79–464 ký tự; một hàng 79 ký tự bị cổng bắt vì dưới sàn `MIN_EXCERPT_CHARS = 80` (luật chạy đúng).
2. **Sổ nguồn phân tầng thật** — `host` + `tier` do máy chấm (WHO `who.int` tầng 1, báo chính thống tầng 2,
   Wikipedia / `api.crossref.org` tầng 3) và mỗi hàng có bộ đếm `byTier` / `independent`.
3. **Cổng chất lượng chạy thật ở `enforce`** — `dossier_write` bị TỪ CHỐI năm lần trên năm lượt, kèm danh
   sách mục cần sửa (mã + câu khắc phục), và model **quay lại sửa** thay vì bịa.
4. **Hạn mức lượt là chỗ chặn THẬT của mức 2** — xin 600 s thì không được nới, xin 1200 s thì được `+600 s`.
   Hợp đồng `research_brief` trước đợt này **không nói gì** về `ceilingSeconds` (xem sửa (d)).
5. **Nhà cung cấp miễn phí cắt lượt ở phút 8,5–14** (bốn lần `UPSTREAM_HTTP_502`) — tức **trước** khi một
   lượt mức 2 kịp đóng hồ sơ.

Hai thứ khác nhau, đừng lẫn: **cổng chất lượng chặn 5 lần** (có danh sách mục cần sửa — hành vi đúng của
vòng 27) và **nhà cung cấp cắt lượt 4 lần** (`UPSTREAM_HTTP_502` — không phải lỗi của research).

## Những gì CHƯA làm được (phần trung thực)

| # | Chưa làm được | Bằng chứng | Cái gì đóng lại |
|---|---|---|---|
| 1 | Không lượt nào ghi ra `.research/**` | sáu lượt trên; `manifest.json` còn `measured: false`; `scores.jsonl` đúng **một** dòng dựng tay | giao thức sống (mục `### 1.`) |
| 2 | `R1–R12` chưa chạy trên dữ liệu thật; **C-7** mở; **F19** cấm nói "đã có benchmark research" | banner "CHƯA CHẠY LƯỢT THẬT NÀO" trong `scripts/eval/benchmarks/tier-r1.md`; `run_eval.py --execute` ⇒ `EXIT_NOT_IMPLEMENTED` (mã 5) | ba lượt thật cho `R1+R3+R6+R7`, rồi ghi số bằng `research_scores.py` |
| 3 | **Bẫy hạn mức khoá là lý do chính sáu lượt chết** | mức 2 xin trần bằng đúng hạn mức đang chạy ⇒ không được nới (lượt 5 chết đúng giây thứ 600); bốn lượt chết vì provider ở phút 8,5–14; harness ghim `connectionId` nên router chỉ dựng **một** đích ⇒ "một connection = một khoá = một phát" | vòng khoá sửa được phần "một khoá là một phát"; nó KHÔNG sửa được hạn mức theo phiên của provider miễn phí, KHÔNG sửa được bẫy trần lượt, KHÔNG sửa được (e) |
| 4 | Năm phát hiện sống còn treo | (a) khoá mục hồ sơ chê tiêu đề Việt tự nhiên; (b) câu "Thêm nguồn khác nguồn tin gốc" đọc thành "thêm một TRANG" trong khi luật là khác **HOST**; (c) JSON tham số hỏng bị thay bằng `{}`, model chỉ nhận một dòng "Invalid tool arguments"; (d) `ceilingSeconds` không được mô tả trong hợp đồng `research_brief`; (e) nhánh con nhận `RESEARCH_GATE_NOTE` với tiêu chí **hồ sơ** (`research-shape-missing`, `research-lineage-missing`) mà nhánh con không có `dossier_write` để thoả | (a)(b)(d) **đã sửa đợt này** bằng unit test; (c) **đã sửa đợt này** ở chỗ gọi; (e) **còn treo** — phải sửa hành vi rồi kiểm bằng một lượt thật |
| 5 | Việc treo từ trước | **M6** router chưa bao giờ trả trường `cost`; ghim âm `final-report`/D-44 mới ở mức chuỗi; dọn nhỏ `v27e1-simplify` (tham số `final` của `_extract`, `import READ_STORE_MAX_ENTRIES` thừa ở `runtime.py:49`) | ghim riêng, không chặn đợt này |
| 6 | Chưa có bằng chứng đầu-cuối offline cho vòng khoá | `RouterClient` mặc định `http://127.0.0.1:3101` và `main()` không truyền client khác ⇒ không nối được harness với router scratch ở cổng khác | nếu chủ nhà muốn: cho `RouterClient` đọc `BOXFOX_ROUTER_URL` (**một dòng**, giữ nguyên mặc định 3101), rồi dựng router scratch bằng `BOXFOX_ROUTER_PORT` / `BOXFOX_ROUTER_DATA_DIR` |
| 7 | Bộ từ của cổng bị **chép** ở bộ đo eval | `scripts/eval/research_checks.py:403-405` có bản sao riêng (`CRITIQUE_SECTION_WORDS`, `CONFLICT_SECTION_WORDS`, `FINDINGS_SECTION_WORDS`) — đợt này nới bảng của **cổng**, **không** đụng bản sao ấy | luồng eval nên gộp hai nơi về một nguồn (`research_quality.DOSSIER_SECTIONS`), nếu không thì một hồ sơ viết "Kết luận" qua được cổng mà vẫn bị số đo tầng R đếm là thiếu mục |

## Đợt 29 (vòng khoá) chứng minh bằng gì — và KHÔNG chứng minh gì

Vòng khoá sống **trong router**. Đợt này ghim bằng **unit test hai tầng**, cả hai chạy trong tiến trình,
không mở socket ra Internet:

- **Tầng router (Node)** — `router/tests/**`, dùng `createProviders({ fetchImpl: stub })`; sở hữu của luồng
  router, đã ghim: 429 ⇒ xoay khoá trong cùng request, 400/5xx ⇒ **không** xoay, khoá cháy 429 nghỉ ≥ 30 s và
  ≤ 120 s, hết vòng ⇒ **một** lỗi, không treo. Số ca trước/sau của tầng ấy do luồng router ghi.
- **Tầng harness (Python)** — `backend/tests/unit/test_router_keyring_probe.py` (mới, **2 ca**, không gọi
  nhà cung cấp nào): một `aiohttp` `TestServer` đóng vai router. Ca 1 chứng minh xoay khoá xảy ra **ở trong**
  router (ba khoá cho một request: 429, 429, 200) và harness chỉ thấy **một** lời gọi HTTP, một câu trả lời,
  route ghim `connectionId` đi nguyên vẹn, không có thông tin khoá nào rời router. Ca 2 chứng minh hết sạch
  khoá ⇒ **một** lỗi tạm thời đọc được (`Router HTTP 429`, mã `RATE_LIMIT`, `UPSTREAM_HTTP_429`), lời khuyên
  thử lại bị chặn hai đầu (`delay ∈ [2, 30] s`, hết 3 lần thử ⇒ dừng, không đủ cửa sổ ⇒ báo thay vì ngủ vào
  hạn chót), và lời gọi trả về ngay (không treo).

Vì sao chỗ này quan trọng: hôm nay harness ghim `connectionId`, và khi ghim thì router chỉ dựng **một** đích
(`router/src/engine.mjs:22-48` — chỉ nhánh `providerId` mới sinh nhiều đích); nên 429/502 là **hết đường** và
refusal về tới harness. Vòng khoá đặt nhiều khoá **trong cùng một connection**, nên `connectionId` ghim vẫn
sống — đó đúng là chỗ đã giết bốn trong sáu lượt thật.

Câu chốt của cả tài liệu, nguyên văn: **đợt 29 chỉ chứng minh bằng unit test; nó KHÔNG chứng minh một lượt research thật giờ chạy xong — đợt này không gọi nhà cung cấp nào.**

Giàn probe **KHÔNG** chứng minh (đừng nói quá): nhà cung cấp thật có cắt lượt ở phút 8,5–14 như đo được
không; một lượt mức 2 có kịp đóng hồ sơ trên khoá thật không; hạn mức theo phiên của provider miễn phí có
luật gì. Ba câu đó chỉ lượt sống trả lời.

## Kiểm tra đã đạt tại commit `deda6e8` (cây sửa thêm của đợt này)

Chạy từ gốc repo:

```bash
cd /code/minndty3-design/BoxFox-Agent-Box
./.venv/bin/python -m pytest backend/tests/unit/test_research*.py \
  backend/tests/unit/test_source*.py backend/tests/unit/test_dossier_write_tool.py \
  backend/tests/unit/test_worker_dossier.py -q -p no:randomly
./.venv/bin/python -m pytest backend/tests/unit/test_research_checks.py -q -p no:randomly
./.venv/bin/python -m pytest backend/tests/unit/test_router_keyring_probe.py -q -p no:randomly
```

Kết quả đo được (nền `deda6e8` so với cây của đợt này):

- Nhóm research: **286 passed / 25,09 s** → **291 passed / 24,85 s** (+5 ca: 4 ở `test_research_quality.py`,
  1 ở `test_research_brief.py`).
- `test_research_checks.py`: **83 passed**, **không còn `xfail`** nào — không đổi trong đợt này (đợt chỉ sửa
  một câu tài liệu mô tả nó ở `scripts/eval/benchmarks/tier-r1.md`).
- Giàn probe mới: **2 passed in 0,46 s**.
- Bộ router (`cd router && npm test`): **không chạy trong đợt này** — `router/**` đang được luồng router sửa
  song song, và `router/node_modules` chưa cài ở cây này.

Bốn sửa của đợt, mỗi sửa kèm ca ghim:

- **(a) Tiêu đề tiếng Việt tự nhiên.** `research_quality.DOSSIER_SECTIONS` chỉ nhận `phat hien`/`ket qua`/
  `findings` cho mục Phát hiện, nên `## Kết luận chính` bị từ chối oan bằng `research-shape-missing mục
  Phát hiện`. Nay bảng từ được tách thành sáu hằng số có tên, thêm biến thể tự nhiên (`ket luan`, `tong ket`,
  `diem chinh`, `nhan xet`, `so lieu`, `bang chung`, `muc tieu`, `xung dot`, `chua thong nhat`, `khac biet`,
  `bat dong`, `viec con`, `han che`, `gioi han`, `chua xong`, `cau hoi mo`, `can lam tiep`, `soi xet`,
  `diem yeu`) mà **giữ nguyên** mọi từ cũ (khớp vẫn bỏ dấu + không phân biệt hoa thường). Cố ý **không** thêm
  `con lai`: tiêu đề chuẩn của mục Mâu thuẫn là "Mâu thuẫn còn lại", thêm `con lai` là mục Mâu thuẫn tự thoả
  luôn mục Việc chưa làm. Ca mới: một ca ĐẠT (hồ sơ toàn tiêu đề tiếng Việt tự nhiên qua cổng) và một ca
  VẪN BỊ TỪ CHỐI (`## Ghi chú` không phải mục Phát hiện), cộng một ca ghim "mọi từ cũ còn nguyên".
- **(b) Câu khắc phục `research-claim-single-source`.** Câu cũ *"Thêm nguồn khác nguồn tin gốc"* bị đọc thành
  "thêm một TRANG nữa", trong khi luật đếm theo *nơi đăng viết độc lập* (`research_ledger.origin_units`: cùng
  `origin` đã khai, hoặc trùng bản tin giữa hai host, thì vẫn là **một** nguồn). Câu mới nói ra chữ **host**
  và chữ **độc lập**, và giữ nguyên lối thoát "hạ khẳng định xuống `suy luận`". Ca mới ghim cả ba mặt: có
  "host", có "độc lập", và **không** quay lại lối nói cũ.
- **(c) "Invalid tool arguments".** Đã sửa trong đợt này ở **chỗ gọi** (không vá cây vendor): thông báo lỗi
  tham số giờ mang cả độ dài và vị trí lỗi — `backend/src/agentbox/agent_core/tool_arg_errors.py` +
  `backend/tests/unit/test_tool_arg_errors.py` (**7 ca**, đo xanh). Hai tệp này do luồng chính của phiên thêm.
- **(d) `ceilingSeconds` trong hợp đồng `research_brief`.** Trước đợt này schema chỉ có `{'type': 'integer'}`,
  nên "xin bao nhiêu" hoàn toàn là phán đoán của model — và bẫy ấy giết lượt 5. Nay tham số có `description`
  nói đủ: bỏ trống ⇒ **giữ** trần đã chốt; giá trị ngoài khoảng bị kẹp (sàn 60 s, trần của mức,
  `RESEARCH_CEILING_CLAMPED`); trong cùng một lượt **chỉ được hạ** (`RESEARCH_BRIEF_RAISE_REFUSED`); muốn
  nới thì phải xin **dài hơn** số giây lượt đang có (`TURN_EXTENDED`, tới trần cứng của mức) — xin bằng đúng
  số đang chạy thì **không nới gì**; kèm bốn con số của bảng mức. Ca mới đọc chính schema ấy và đối chiếu số
  với `research_runtime.research_tier_limits`, nên mô tả không trôi khỏi bảng.
- **Câu tài liệu lệch.** `scripts/eval/benchmarks/tier-r1.md:66` hết nói ca `milestone_ceiling_declared`
  "đang là `xfail`" — nay khớp §6.1 của cùng tệp (lỗi so nhãn đã vá ở vòng 27, `scripts/eval/research_checks.py`
  lấy `label = _fold('trần')` rồi so với `_fold(line)`). Không sửa mã, không thêm ca.

## Việc còn lại

### 0. Bốn điều phải nhớ trước khi tin tài liệu này

1. Câu chốt ở mục `## Trạng thái` là ràng buộc, không phải câu văn: đợt này **không** gọi nhà cung cấp nào.
2. Cổng chặn (5 lần) và provider cắt lượt (4 lần `UPSTREAM_HTTP_502`) là **hai** chuyện khác nhau.
3. Chỉ dùng **nhãn** `key 1/2/3`; không dán giá trị khoá, không in blob mã hoá, không in nội dung
   `~/BoxFox/secrets/opencode-free-keys.txt`.
4. Chỉ chạm cổng scratch `3151`; **không** chiếm `3101` (router của chủ nhà) hay `3102` (harness chủ nhà).

### 1. Lượt research SỐNG của đợt sau (khi vòng khoá đã xong)

Chuẩn bị (không chạm máy chủ nhà):

```bash
cd /code/minndty3-design/BoxFox-Agent-Box
/var/tmp/v27t/start_harness.sh research-v29 3151 \
  BOXFOX_RESEARCH_BRIEF=enforce BOXFOX_RESEARCH_GATE=enforce BOXFOX_RESEARCH_PROGRESS=on
```

Thứ tự đề nghị cho đợt đầu: **`R1` → `R6` → `R7` → `R3`**, mỗi ca MỘT lượt, mỗi lượt MỘT hàng vào sổ.
`/var/tmp/v27t/run_live.py` ghim `connectionId` ở **dòng 28**
(`f8a5f4e8-0986-45f9-bf5b-555e8b96a95c`, tức key 1) và `modelId` `muse-spark-1.3-contributor-free`; nếu bản
migrate chọn id sống sót khác thì **sửa đúng một dòng ấy** trước khi chạy.

Luật chuyển khoá (nguyên văn bảng §2.3 của `docs/plan/v27/research-quality-tests.md`):

| Mã lỗi gặp | Nghĩa | Việc làm |
|---|---|---|
| `429` / "rate limit" | hết hạn mức của khoá đó | chuyển **khoá kế tiếp** (nay router tự làm trong một connection) |
| `403` | khoá hỏng/không đủ quyền (AUTH, không thử lại) | chuyển khoá kế tiếp, **ghi lại** |
| `500`/timeout | lỗi hạ tầng | thử lại đúng khoá đó 1 lần rồi mới chuyển |
| `400` hình dạng | mình gửi sai (không phải khoá) | **không** chuyển khoá: sửa hình dạng trước |

Chứng cứ phải giữ cho mỗi lượt: `.research/<việc>/v<N>-<việc>.md` + `sources.jsonl` + `sources.md` +
`tables/*.md` + `conflicts.md` + `review.md` (nếu kịp ghi); nhật ký phiên (`events`, hoặc
`GET /api/agent/sessions/{sid}/journal?limit=500`) đổ ra JSONL; bảng sổ nguồn của lượt (số hàng, `tier`,
`byTier`, `independent`); một ảnh màn hình mặt câu trả lời lưu vào `/code/.generated_artifacts/`; log harness
`/var/tmp/v27t/research-v29/logs/harness.jsonl`.

Ghi số **chỉ khi có lượt thật**:

```bash
./.venv/bin/python scripts/eval/research_scores.py \
  --workspace <thư mục chứa .research/> --log <journal.jsonl> \
  --case R1 --level 1 --checks \
  --source "lượt thật <sid> <ngày> — muse-spark-1.3-contributor-free, connection <nhãn khoá>" --append
```

Sau đó, và chỉ sau đó: `manifest.json` ← `measured: true` + `provider`/`model`/`seed`/`temperature` +
`counts` thật, ghim commit đã đo; thêm **một hàng** vào `docs/tracking/test-rounds.md` (**tệp CRLF** — giữ
nguyên kiểu xuống dòng); nếu đã đủ ba lượt cho `R1+R3+R6+R7` thì đóng **C-7** và nói rõ **F19** đã hết hiệu
lực ở phần nào.

Dừng khi nào (kỷ luật ngân sách): cả vòng khoá 429 ⇒ dừng phần sống ngay, ghi sổ; nhà cung cấp cắt lượt hai
lần liên tiếp trước phút 10 ⇒ dừng và ghi *"nhà cung cấp miễn phí không đủ thời lượng cho mức 2"* (đó là
**kết quả**, không phải lỗi cần sửa bằng cách đổi model); quá ba lần thử cho một ca ⇒ dừng ca đó.

### 2. Một lần chạy tay trên máy chủ nhà (gộp bốn connection thành một vòng ba khoá)

Làm khi chủ nhà gọi, **không** làm từ sandbox:

1. **Trước khi làm gì:** dừng router; **sao lưu cả thư mục** `~/.local/share/boxfox/router/`
   (`router.sqlite` + `router.sqlite-wal` + `router.sqlite-shm` + **`master.key`**) ra chỗ ngoài repo, mode
   `0600`. Sai lầm chí mạng: **không** xoá/đổi `master.key` — mất khoá là mất hết credential (`store.mjs`
   từ chối mở DB cũ).
2. **Migrate là chuyển khoá phía máy chủ, không nhập lại khoá:** blob credential gắn chặt với id bản ghi qua
   AAD (`store.mjs:44,54` — `cipher.setAAD(Buffer.from(id))`), nên **không** copy blob sang id khác được;
   script một lần phải đọc khoá của từng connection **trong bộ nhớ** rồi ghi lại dưới entry mới của vòng
   khoá — **không in giá trị khoá** ra màn hình/log.
3. **Bốn connection liên quan:** `f8a5f4e8-0986-45f9-bf5b-555e8b96a95c` (key 1),
   `a43ff124-359f-4da5-bbd0-82c54df64a53` (key 2), `3d27b0b0-1de7-4c67-a803-c6e26afab631` (key 3),
   `7c59f6b5-d0ee-4206-9d04-bc19936b0681` ("OpenCode Free", đang `inferenceState: failed`). Đo trước khi
   migrate (chỉ in sha256-vài-ký-tự-đầu + độ dài, **không** in khoá): bốn blob `opencode` khác nhau cả bốn ⇒
   **bốn khoá khác nhau**. Đề nghị: giữ `f8a5f4e8…` làm connection sống sót (vì `run_live.py:28` đã ghim
   đúng id ấy) với vòng ba khoá theo thứ tự key 1 → key 2 → key 3; connection `7c59f6b5…` **tắt chứ không
   xoá** (đường lùi, và là chỗ thêm khoá thứ tư sau này).
4. **Kiểm trên giao diện sau khi migrate:** provider `opencode` chỉ còn **một** connection đang bật với
   **ba** khoá; model picker hiện **một hàng** cho `muse-spark-1.3-contributor-free`; chạy **một lượt
   thường** (không phải research) từ app để chắc đường model còn sống — lượt thường **không** phải bằng
   chứng research.
5. **Đường lùi nếu chuyển khoá trông sai:** dừng router, **chép lại hai tệp từ bản sao lưu** (`router.sqlite`
   + `master.key`, và `-wal`/`-shm` nếu có), mở lại router, rồi kiểm bằng sha256-vài-ký-tự-đầu + độ dài của
   từng blob: phải trùng đúng bộ digest đã ghi trước khi migrate. Ghi kết quả một hàng vào
   `docs/tracking/test-rounds.md` (**tệp CRLF**), kèm ngày và id connection.

### 3. Việc nhỏ còn treo

1. **(e) chú thích cổng cho nhánh con** — nhánh `research` con nhận `RESEARCH_GATE_NOTE` với tiêu chí của
   **hồ sơ** (`research-shape-missing`, `research-lineage-missing`) mà nó không có `dossier_write` để thoả;
   sửa hành vi rồi **kiểm bằng một lượt thật**. Đo được ở lượt 5.
2. **Bản sao bộ từ ở bộ đo eval** (`scripts/eval/research_checks.py:403-405`) — gộp về một nguồn
   (`research_quality.DOSSIER_SECTIONS`), xem hàng 7 của bảng "chưa làm được".
3. **M6** — router chưa bao giờ trả trường `cost` (cần lượt thật hoặc metering).
4. **C-7** và **F19** — chỉ đóng được bằng ba lượt thật cho `R1+R3+R7+R6` và những dòng điểm đầu tiên.
5. **Hai việc dọn** không chặn ai: ghim âm `final-report`/D-44 ở mức cấu trúc; dọn `v27e1-simplify`.

### 4. Khi nào được gọi là "đã chạy benchmark research"

Chỉ khi `scores.jsonl` có dòng điểm **thật** cho `R1`/`R3`/`R6`/`R7` (không phải dòng dựng tay
`fixture-workspace`), và `manifest.json` đã `measured: true` kèm commit đã đo. Trước lúc đó, câu đúng vẫn là
*"bộ ca R + oracle máy đã có, benchmark research thì chưa chạy"*.

## File chính

- `backend/tests/unit/test_router_keyring_probe.py` — giàn probe tầng harness (mới, 2 ca, offline).
- `backend/src/agentbox/agent_core/research_quality.py` — bảng từ tiêu đề theo mức + câu khắc phục
  `research-claim-single-source`.
- `backend/src/agentbox/agent_core/tool_contracts.py` — mô tả `ceilingSeconds` trong hợp đồng `research_brief`.
- `backend/tests/unit/test_research_quality.py`, `backend/tests/unit/test_research_brief.py` — ca ghim (a)(b)(d).
- `backend/src/agentbox/agent_core/tool_arg_errors.py` + `backend/tests/unit/test_tool_arg_errors.py` — sửa (c).
- `scripts/eval/benchmarks/tier-r1.md` — câu tài liệu lệch (dòng 66) đã khớp §6.1.
- `docs/tracking/test-rounds.md` — hàng ghi vòng 29 (đợt 4) + sáu lượt research thật của vòng 28.
- `backend/src/agentbox/agent_core/research_ledger.py` — luật đếm nguồn (`origin_units`, `assess_rows`).
- `backend/src/agentbox/agent_core/research_runtime.py` — luật trần lượt của `research_brief`.
- `docs/tracking/bug-register.md` — nơi ghi lỗi thật của vòng 27 (`BUG-90…BUG-113`) và các mục còn mở.

## Thiết kế và nghiên cứu

- `/code/.plans/v1-keyring-router.md` — plan vòng 29 (năm đợt).
- `/code/.plans/subplans/v29-research-verify-plan.md` — spec của đợt này (bảng R1–R12, giàn probe, giao thức sống).
- `/code/.plans/subplans/v29-research-handoff-outline.md` — đề cương của tài liệu này.
- `docs/plan/v27/research-quality-tests.md` — luật chuyển khoá §2.3 và luật hạn mức của vòng 27.
- `docs/architecture/research-agent.md` — kiến trúc research trong mã.
- `scripts/eval/benchmarks/tier-r1.md` — 27 oracle máy và bộ ca `R1–R12`.
- `/var/tmp/v28/rounds_live_runs2.md` — sổ đo sáu lượt thật (bản thô).

## Lệnh bắt đầu nhanh

```bash
cd /code/minndty3-design/BoxFox-Agent-Box
./.venv/bin/python -m pytest backend/tests/unit -q -p no:randomly \
  --deselect backend/tests/unit/test_terminal_tools.py::test_terminal_exec_echo
cd router && npm test            # node >= 24
/var/tmp/v27t/start_harness.sh research-v29 3151 \
  BOXFOX_RESEARCH_BRIEF=enforce BOXFOX_RESEARCH_GATE=enforce BOXFOX_RESEARCH_PROGRESS=on
/var/tmp/v27t/run_live.py 3151 /var/tmp/v27t/research1_prompt.txt /var/tmp/v28/sid-r1.txt "research v29 lượt R1"
```
