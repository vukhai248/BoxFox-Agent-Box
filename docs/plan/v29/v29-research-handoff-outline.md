# Vòng 29 — đề cương tài liệu handoff `docs/handoff/research-verification.md`

> **TL;DR:** tài liệu handoff nói thẳng ba thứ: cái gì đã đo được trên app thật, cái gì **chưa**
> làm được và vì sao (bẫy hạn mức khoá là lý do chính), và vòng 29 đổi gì ở router — kèm lệnh chạy
> nhanh. Đợt này chỉ chứng minh bằng unit test, **không** chứng minh lượt research thật chạy xong.

## 1. Đường dẫn, khuôn, độ dài

- **Đường dẫn:** `docs/handoff/research-verification.md` (đúng yêu cầu của đợt này).
  - Ghi chú cấu trúc: lúc viết, tài liệu khuôn nằm **phẳng** ở gốc `docs/`, và `docs/handoff/` **chưa
    tồn tại** (2026-10-09: thư mục đã có, mọi handoff gom về đó — xem `docs/handoff/README.md`). Nếu muốn theo đúng lối đặt tên đang có thì tên phẳng là
    `docs/handoff-research-verification.md`; **khuyến nghị** cứ theo đường dẫn đã yêu cầu
    (`docs/handoff/research-verification.md`) và tạo thư mục — chọn xong thì nói một câu trong tài
    liệu để người đọc sau không đi tìm sai chỗ.
- **Khuôn theo `docs/handoff/router-settings.md`** (146 dòng, đã đọc): mở đầu `# Handoff — <tiêu đề>`,
  rồi danh sách bullet `- Branch:` / `- Pull request:` và một đoạn "giai đoạn hiện tại"; các mục
  `## Trạng thái`, `## Đã hoàn thành`, `## Kiểm tra đã đạt tại commit <sha>`, `## Việc còn lại`
  (đánh số `### 0.` … `### 3.`), `## File chính`, `## Thiết kế và nghiên cứu`,
  `## Lệnh bắt đầu nhanh` (khối bash). Văn xuôi tiếng Việt, thuật ngữ kỹ thuật giữ tiếng Anh, **không
  emoji**, gạch đầu dòng; bảng chỉ dùng khi thật cần (tài liệu khuôn không dùng bảng).
- **Độ dài dự định:** ~220–260 dòng (dài hơn khuôn vì phải mang bảng sáu lượt và mục migrate một lần).
- `docs/README.md` **không** có mục index cho handoff ⇒ thêm liên kết vào bảng index nếu bảng đó cho
  phép, còn không thì chỉ đặt tệp, đừng dựng mục mới.

## 2. Đề cương từng mục và **sự thật bắt buộc phải có**

### (a) Mục tiêu

Research nhiều tầng (mức 1–3), hồ sơ `.research/**`, sổ nguồn phân tầng, cổng chất lượng, nhánh con.
Lượt research thật đầu tiên đã chạy để đo; đợt này kiểm bằng unit test; đợt sau chạy sống tiếp.

### (b) Đã chứng minh được (kèm bảng sáu lượt)

Bảng **nguyên văn** từ sổ (mỗi hàng: mã phiên, khoá, số hàng sổ nguồn, hồ sơ ghi được hay không, kết
thúc lượt, ghi chú đo được):

| Lần | Khoá | Sổ nguồn | Hồ sơ | Kết thúc lượt | Ghi chú đo được |
|---|---|---|---|---|---|
| 1 `0d0fe166` | OpenCode Free | 13 hàng | không (từ chối 1 lần) | `failed` — `UPSTREAM_HTTP_502` bước 22, 13,8 phút | 3 nhánh con xong (9–13 bước) |
| 2 `30003232` | OpenCode Free | 24 hàng | không | `failed` — `UPSTREAM_HTTP_502` bước 15, 13,7 phút | 502 ⇒ thử lại 1 rồi chuyển khoá |
| 3 `b5832e29` | key 1 | 9 hàng | không (từ chối 2 lần) | `completed partial` — `DEADLINE_EXCEEDED` bước 30, 20,2 phút, 41 tool | `ceilingSeconds: 1200` ⇒ `TURN_EXTENDED +600s` (trần cứng mức 2 = 1800 s) |
| 4 `bc8d9125` | key 1 | 9 hàng | không (từ chối 1 lần) | `failed` — `UPSTREAM_HTTP_502` bước 21, 13,0 phút | 2 lần JSON tham số hỏng; 3 hàng `confirm` cùng host ⇒ `independent` = 2 |
| 5 `6e274b19` | key 1 | 2 hàng | không | `failed` — `DEADLINE_EXCEEDED` đúng **600 s**, bước 2 | xin `ceilingSeconds: 600` ⇒ **không** có `TURN_EXTENDED`; chết khi chờ nhánh con thứ ba |
| 6 `5e689d49` | key 1 | 0 hàng | không | `failed` — `UPSTREAM_HTTP_502` bước 14, 8,5 phút | có `TURN_EXTENDED +600s` nhưng provider cắt trước khi gọi `source_add` |

Kèm **năm kết luận đo được**, nguyên văn: (1) đọc nguồn là thật — trích nguyên văn 79–464 ký tự, hàng
79 ký tự bị cổng bắt vì dưới sàn 80; (2) sổ nguồn phân tầng thật — `host`+`tier` do máy chấm, có
`byTier`/`independent`; (3) cổng chất lượng chạy thật ở `enforce` — `dossier_write` bị TỪ CHỐI năm
lần, model quay lại sửa chứ không bịa; (4) hạn mức lượt là chỗ chặn thật của mức 2; (5) nhà cung cấp
miễn phí cắt lượt ở phút 8,5–14. Sổ đầy đủ ở `docs/tracking/test-rounds.md` §vòng 27 (từ dòng 2607)
và `/var/tmp/v28/rounds_live_runs2.md`.

### (c) Những gì **CHƯA** làm được (phần trung thực — không được lược)

| # | Chưa làm được | Bằng chứng | Cái gì đóng lại |
|---|---|---|---|
| 1 | Không lượt nào ghi ra `.research/**` | sáu lượt trên; `scripts/eval/results/tier-r1-research/manifest.json` còn `measured: false`; `scores.jsonl` đúng **một** dòng dựng tay | giao thức sống (mục d) |
| 2 | `R1–R12` chưa chạy trên dữ liệu thật; **C-7** còn mở; **F19** cấm nói "đã có benchmark research" | `scripts/eval/benchmarks/tier-r1.md` banner "CHƯA CHẠY LƯỢT THẬT NÀO"; `run_eval.py --execute` ⇒ `EXIT_NOT_IMPLEMENTED` (mã 5) | ba lượt thật cho `R1+R3+R6+R7`, ghi số đầu tiên |
| 3 | **Bẫy hạn mức khoá — lý do chính sáu lượt chết** | mức 2 xin `ceilingSeconds` **bằng đúng** hạn mức phiên (600 s) ⇒ không được nới (lượt 5 chết đúng 600 s); bốn lượt chết vì `UPSTREAM_HTTP_502` của provider ở phút 8,5–14; harness ghim `connectionId` nên router chỉ có **một** đích ⇒ một khoá là một phát | vòng khoá đổi được: 429 **không** còn kết thúc request khi trong vòng còn khoá khác. Vòng khoá **không** đổi được: hạn mức theo phiên của provider miễn phí, bẫy trần lượt (phát hiện d), lỗi khoá mục hồ sơ (phát hiện a) |
| 4 | Năm phát hiện sống còn `Pending` | (a) khoá mục hồ sơ chê tiêu đề Việt tự nhiên; (b) câu "Thêm nguồn khác nguồn tin gốc" đọc thành "thêm một TRANG" trong khi luật là khác **HOST**; (c) JSON tham số hỏng bị thay bằng `{}`, model chỉ nhận một dòng "Invalid tool arguments"; (d) `ceilingSeconds` không được mô tả trong hợp đồng `research_brief`; (e) nhánh con nhận `RESEARCH_GATE_NOTE` với tiêu chí hồ sơ (`research-shape-missing`, `research-lineage-missing`) mà nhánh con không có `dossier_write` | (a)(b)(d) sửa được offline bằng unit test; (c) sửa được nhưng phải chốt chỗ sửa (câu lỗi nằm trong cây vendor `vendor/hermes/tool_arguments.py:14`); (e) phải sửa hành vi rồi **kiểm bằng một lượt thật** |
| 5 | Việc còn treo từ trước | **M6** router chưa bao giờ trả trường `cost`; ghim âm `final-report`/D-44 mới ở mức chuỗi; dọn nhỏ `v27e1-simplify` (tham số `final` của `_extract`, `import READ_STORE_MAX_ENTRIES` thừa ở `runtime.py:49`) | ghim riêng, không chặn đợt này |
| 6 | Chưa có bằng chứng đầu-cuối offline cho vòng khoá | `RouterClient` mặc định `http://127.0.0.1:3101` (`runtime.py:460`) và `main()` không truyền client khác (`server.py:924`) ⇒ không nối được harness với router scratch ở cổng khác | nếu muốn: cho `RouterClient` đọc `BOXFOX_ROUTER_URL` (**một dòng**), rồi dựng router scratch bằng `BOXFOX_ROUTER_PORT`/`BOXFOX_ROUTER_DATA_DIR` |

### (d) Kế hoạch kiểm nghiệm khi vòng khoá xong

Tóm hai câu: (1) **offline** — chạy bộ đơn vị (nền đo **lại** tại HEAD `deda6e8`: research
**286 passed / 25,09 s**, riêng `test_research_checks.py` 83 passed, **không còn `xfail`** nào), giàn
probe provider GIẢ hai tầng (`router/tests/**` bằng `createProviders({fetchImpl})`: 429 ⇒ xoay khoá,
400/5xx ⇒ không xoay, khoá cháy 429 nghỉ ≥ 30 s và ≤ 120 s, hết vòng ⇒ một lỗi không treo;
`RouterClient(url)` + `aiohttp` giả ở tầng harness: xoay khoá ở trong ⇒ harness thấy 200, **không**
phải sửa harness); (2) **sống** — `R1` → `R6` → `R7` → `R3`, mỗi ca một lượt trên harness scratch
`3151` với `BOXFOX_RESEARCH_BRIEF=enforce BOXFOX_RESEARCH_GATE=enforce BOXFOX_RESEARCH_PROGRESS=on`,
luật chuyển khoá §2.3 của `docs/plan/v27/research-quality-tests.md`, ghi số bằng
`scripts/eval/research_scores.py --append`. Chi tiết đầy đủ: `/code/.plans/subplans/v29-research-verify-plan.md` §3–§4.

### (e) Rủi ro còn treo và cách xử

| Rủi ro | Cách xử |
|---|---|
| Đọc tài liệu rồi tưởng "research đã chạy được" | câu chốt phải có nguyên văn: *"vòng 29 chỉ chứng minh bằng unit test; KHÔNG chứng minh lượt research thật chạy xong"* |
| Nhầm "nhà cung cấp cắt lượt" thành "cổng chất lượng chặn" | cổng chặn = 5 lần đo được, có danh sách mục cần sửa; nhà cung cấp cắt = 4 lần `UPSTREAM_HTTP_502` — hai thứ khác nhau, ghi riêng |
| Chạm máy chủ nhà | chỉ dùng cổng scratch `3151`; không chiếm `3101` (router) / `3102` (harness chủ nhà) |
| Rò khoá | chỉ dùng nhãn `key 1/2/3`; không dán giá trị khoá, không in blob |

### (f) Lệnh chạy nhanh (khối bash cuối tài liệu)

```bash
cd /code/minndty3-design/BoxFox-Agent-Box
./.venv/bin/python -m pytest backend/tests/unit -q -p no:randomly \
  --deselect backend/tests/unit/test_terminal_tools.py::test_terminal_exec_echo
cd router && npm test            # node >= 24
/var/tmp/v27t/start_harness.sh research-v29 3151 \
  BOXFOX_RESEARCH_BRIEF=enforce BOXFOX_RESEARCH_GATE=enforce BOXFOX_RESEARCH_PROGRESS=on
/var/tmp/v27t/run_live.py 3151 /var/tmp/v27t/research1_prompt.txt /var/tmp/v28/sid-r1.txt "research v29 lượt R1"
```

## 3. Mục mới của đợt 29: vòng khoá router (phải có trong tài liệu)

Nội dung phải nói rõ, **không** nói quá:

- **Đợt này làm gì:** một connection giữ **danh sách khoá có thứ tự**; router xoay khoá **chỉ** khi
  gặp HTTP **429**; khoá vừa cháy bị **nghỉ 30 s** (hoặc theo `retry-after` của nhà cung cấp, **chặn
  trần 2 phút**); bốn connection `opencode` của chủ nhà được **gộp thành một** connection ba khoá;
  model picker chọn theo **provider + model** nên một model chỉ hiện **một hàng**.
- **Đợt này chứng minh bằng gì:** unit test (mục (d)). Câu phải có nguyên văn: *"đợt 29 chỉ chứng
  minh bằng unit test; nó KHÔNG chứng minh một lượt research thật giờ chạy xong — đợt này không gọi
  nhà cung cấp nào."*
- **Vì sao chỗ này quan trọng:** hôm nay harness ghim `connectionId` ⇒ router chỉ dựng một đích
  (`router/src/engine.mjs:22-48`), nên "một connection = một khoá = một phát"; 429/502 là hết đường và
  refusal về tới harness. Vòng khoá đặt nhiều khoá **trong cùng một connection** nên `connectionId`
  ghim vẫn sống.

### Một lần chạy tay trên máy chủ nhà (bước một lần, khi chủ nhà gọi)

1. **Trước khi làm gì:** dừng router; **sao lưu cả thư mục** `~/.local/share/boxfox/router/`
   (`router.sqlite` + `router.sqlite-wal` + `router.sqlite-shm` + **`master.key`**) ra chỗ ngoài repo,
   mode `0600`. Sai lầm chí mạng cần tránh: **không** xoá/đổi `master.key` — mất khoá là mất hết
   credential, và `store.mjs:22-26` sẽ từ chối mở DB cũ (assert "Credential encryption key is
   missing").
2. **Migrate là chuyển khoá phía máy chủ, không nhập lại khoá:** blob credential gắn chặt với id
   bản ghi qua AAD (`store.mjs:44,54` — `cipher.setAAD(Buffer.from(id))`), nên **không** copy blob
   sang id khác được; script một lần phải đọc khoá của từng connection **trong bộ nhớ** rồi ghi lại
   dưới entry mới của vòng khoá — **không in giá trị khoá** ra màn hình/log. Chủ nhà không phải dán
   lại khoá (chỉ khi script lỗi mới phải đọc lại từ `~/BoxFox/secrets/opencode-free-keys.txt`).
3. **Bốn connection liên quan:** `f8a5f4e8-0986-45f9-bf5b-555e8b96a95c` (key 1),
   `a43ff124-359f-4da5-bbd0-82c54df64a53` (key 2), `3d27b0b0-1de7-4c67-a803-c6e26afab631` (key 3),
   `7c59f6b5-d0ee-4206-9d04-bc19936b0681` ("OpenCode Free", đang `inferenceState: failed`). Đo được
   (probe chỉ in sha256-vài-ký-tự-đầu + độ dài, **không** in khoá): bốn blob của provider `opencode`
   khác nhau **cả bốn**, và cả 5 blob trong DB cũng khác nhau ⇒ **bốn khoá khác nhau**, không có khoá
   trùng. Đề nghị: giữ
   `f8a5f4e8…` làm connection sống sót (vì `/var/tmp/v27t/run_live.py:28` đã ghim đúng id này, không
   phải sửa gì) với vòng ba khoá theo thứ tự key 1 → key 2 → key 3; connection `7c59f6b5…` **tắt chứ
   không xoá** (giữ làm đường lùi và là khoá dự phòng nếu sau này muốn thêm khoá thứ tư).
4. **Kiểm trên giao diện sau khi migrate:** provider `opencode` chỉ còn **một** connection đang bật
   với **ba** khoá; model picker hiện **một hàng** cho `muse-spark-1.3-contributor-free`; chạy **một
   lượt thường** (không phải research) từ app để chắc đường model còn sống — lượt thường **không**
   phải bằng chứng research.
5. **Đường lùi nếu chuyển khoá trông sai:** dừng router, **chép lại hai tệp từ bản sao lưu**
   (`router.sqlite` + `master.key`, và `-wal`/`-shm` nếu có), mở lại router, rồi kiểm bằng
   sha256-vài-ký-tự-đầu + độ dài của từng blob: phải trùng đúng bộ digest đã ghi trước khi migrate.
   Ghi kết quả một hàng vào `docs/tracking/test-rounds.md` (**tệp CRLF**), kèm ngày và id connection.
