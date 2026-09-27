# Chế độ plan dưới mắt mô hình thật — hiện trạng đo ngày 2026-09-27

> **Trạng thái:** số đo thật, chạy ngày 2026-09-27 trên harness thật (cổng `:3102`), model
> `muse-spark-1.3-contributor-free` (provider `opencode`), box `agentbox-box`. Ba ca, một mô hình,
> một cấu hình. Mọi con số dưới đây **đo được** từ sự kiện của harness; chỗ nào là suy luận thì ghi
> rõ là suy luận. Phép đo này **không** thay thế rubric `P1–P8` (máy, đã có sẵn trong sự kiện
> `plan_evaluated`) và rubric `C1–C8` (`scripts/eval/rubric.py`).
>
> **Phạm vi:** chế độ plan (`write_plan` → con `plan-review` → `plan_verify` → duyệt) và chế độ
> design `/design` (đường vào, phỏng vấn, touch list, ghi file). Không đo research.

## 1. Bốn câu chủ nhà hỏi, trả lời ngay

| Câu hỏi | Trả lời đo được | Bằng chứng |
|---|---|---|
| Yêu cầu mơ hồ thì harness có **hỏi lại** hoặc **tìm kỹ** không? | **Không hỏi lại.** Cả ba ca đều có **0** `decision_requested` và **0** lượt gọi `ask_user`. Ca mơ hồ (A) tự chọn cách hiểu rồi viết plan. | §3, §4.1 |
| Có **tìm kỹ** không? | Ca A: **1** lượt tìm trong phiên chính, **0** ở phiên con (so với 129 lượt ở phiên con trong lượt research cũ). Ca C: 0 lượt tìm, nhưng có 1 con `explore` đọc file thật. | §3, §4.2 |
| Plan có đủ **kiến trúc/lý thuyết/luồng/data** khi cần, và **sang design** khi là việc UI không? | Ca A (hệ thống): có — bảng module + I/O contract + 6 bảng dữ liệu + 6 bước kèm lệnh và độ đo. Ca B (UI): **0** `plan_written`, đi trọn đường design, **không** vẽ kiến trúc/luồng dữ liệu. | §4.3 |
| Đánh giá có **công tâm** không? | Chấm máy `P1–P8` chạy thật (có ca bị **từ chối** 11/16, `fail`, cổng `P4`) — không phải "cho qua". Nhưng **cả ba ca đều không có `plan_verified`**: con `plan-review` chết `UPSTREAM_HTTP_502` (2 ca) hoặc trả 78 ký tự (< 400 nên bị cổng provenance chặn). Vì vậy **chưa lượt nào có kết luận phản biện ghi sổ** — và cũng chưa plan nào duyệt được (`PLAN_APPROVAL_UNVERIFIED`). | §4.4 |

## 2. Cách đo

- Ba ca, mỗi ca một phiên mới trên harness thật (`POST /api/agent/sessions`) rồi gửi một lượt
  (`POST /api/agent/sessions/{sid}/turns`): ngân sách `deadlineSeconds=1200`, `maxSteps=60`,
  model `muse-spark-1.3-contributor-free`, provider `opencode`.
- Ca A — **yêu cầu mơ hồ**: "Tôi muốn xây một hệ thống multi-agent để quản lý hồ sơ bệnh nhân rời
  rạc. Lên kế hoạch chi tiết cho tôi." (thiếu mục đích, đối tượng, nguồn dữ liệu, ràng buộc pháp lý).
- Ca B — **việc UI, mở bằng chế độ design**: `/design Tôi muốn làm lại màn hình đăng nhập của ứng
  dụng quản lý kho cho rõ ràng và dễ dùng hơn. Lên kế hoạch chi tiết cho tôi.` rồi trả lời phỏng vấn
  như một chủ dự án thật, gửi lượt tiếp, duyệt touch list.
- Ca C — **đối chứng yêu cầu đã rõ**: thêm `slugify_vi(text, max_len=60)` vào tệp `slugify.py` có
  thật trong box + test trong `test_slugify.py`, kèm đặc tả hành vi từng bước.
- Mọi sự kiện được đọc **hết mọi trang** (`GET /api/agent/sessions/{sid}?after=N` trả tối đa 500
  hàng/lần) và ghi lại nguyên văn; số liệu dưới đây tính từ bản ghi ấy, không tính từ trí nhớ.

## 3. Số đo ba ca

| | A — mơ hồ | B — UI (`/design`) | C — đã rõ (đối chứng) |
|---|---|---|---|
| Phiên (`sid`) | `accf8839acdd48cb9cfabad12dc8ed95` | `23d1ee8ad8e043e9aafd5f2ab56dc272` | `6ecff139a8314efeadca4ecd44d5f6a9` |
| Lượt / bước | 1 lượt / 15 bước | 3 lượt / 5+6+3 bước | 1 lượt / 8 bước |
| Thời gian tường | 756 s (ngân sách 1200) | 86 + 202 + 96 ≈ 384 s | 648 s |
| Sự kiện ghi được | 201 | 329 | 101 |
| **Lời hỏi qua `ask_user`** | **0** | **0** | **0** |
| Lời hỏi qua đường design | — | 3 (`dp-48ce3be3cd62`, `dp-202a70d484d5` phỏng vấn; `dp-be5d1e19e28c` out-of-scope) | — |
| Tìm kiếm (chính / con) | 1 / 0 | 0 / 0 | 0 / 0 |
| Phiên con | 3: `explore` (7097 ký tự), `plan-review` (584), `plan-review` **fail 502** | 0 | 4: `explore` (4425), `plan-review` (78 ký tự), `plan-review` **fail 502** ×2 |
| Plan ghi được | `v1` 4309 B, `v2` 7991 B (identity `multi-agent-ho-so-roi-rac`) | **0** | `v1` 6008 B (`slugify-vi-plan`) |
| Chấm máy `P1–P8` | v1 **11/16 `fail`** (cổng `P4`, `stepsAnchored` 2/6) → v1 lại **14/16 `pass`** → v2 **13/16 `pass`** | — | **15/16 `pass`** (chỉ `P1` = 1) |
| `plan_verified` | **0** | — | **0** |
| Cảnh báo cuối lượt | `EVIDENCE_INSUFFICIENT` | — | `EVIDENCE_INSUFFICIENT` |
| Kết cục | `completed`, plan v2 nằm trong box, **chưa duyệt được** | run `designing`/`briefing`, **đứng im** sau khi trả lời (xem §5.F1) | `completed`, plan v1 trong box, **chưa duyệt được** |

Cổng `plan_verify` không có dữ liệu để chặn ở cả ba ca, vì con phản biện hoặc chết, hoặc trả quá
ngắn. Hệ quả đo được: lượt kết thúc ở trạng thái "plan viết xong, chưa có kết luận phản biện" — đúng
**anti-pattern đầu tiên** mà chính kỹ năng `planning` liệt kê ("Stopping after `write_plan`").

## 4. Chi tiết bốn câu trả lời

### 4.1 Hỏi lại khi mơ hồ: KHÔNG

Ca A là phép thử trực tiếp: yêu cầu thiếu mục đích, thiếu nguồn dữ liệu, thiếu ràng buộc pháp lý.
Mô hình **không hỏi câu nào**:

- 0 sự kiện `decision_requested` / `decision_resolved`; 0 lượt gọi `ask_user` (đường duy nhất để
  mô hình hỏi chủ nhà và **chặn** lượt cho tới khi có câu trả lời).
- Thay vào đó nó **tự chọn cách hiểu** (đổi "multi-agent" thành "modular monolith với ranh giới
  module" ở v2), tự chốt 6 bảng dữ liệu, tự đặt ngưỡng linkage (và tự ghi "chưa hiệu chỉnh").

Nguyên nhân đọc thẳng từ mã nguồn (không phải suy đoán):

- Kỹ năng `planning` (`backend/src/agentbox/vendor/hermes/skills/software-development/planning/SKILL.md`,
  72 dòng) có 5 bước, **không có bước nào là "hỏi lại khi mơ hồ"**: bước 1 là *ground* bằng
  `delegate_task role='explore'|'research'`, rồi viết, rồi phản biện, rồi ghi verdict, rồi duyệt.
  Từ `ask_user`/`clarify` **không xuất hiện** trong tệp này.
- Prompt hệ thống lại nghiêng về phía ngược lại — `ACT_DONT_ASK_GUIDANCE`
  (`backend/src/agentbox/agent_core/runtime.py:194-195`): *"When a request has an obvious default
  interpretation or can be resolved by exploring the workspace/sandbox, act immediately using tools
  instead of asking the user for clarification. Only ask when genuine ambiguity prevents choosing an
  action."*
- Hợp đồng của `ask_user` cũng tự kìm: *"If nobody answers before the deadline (default 300 s) the
  answer is a rejection, so ask only when the answer changes what you do next"*
  (`tool_contracts.py:244`).

Đối chiếu với chế độ design: cùng mô hình ấy **có hỏi**, vì ở đó luật cứng bắt hỏi —
`design_confirm_interview_required()` mở lời hỏi ngay khi brief thiếu mục, chứ không chờ mô hình
quyết định (ca B: vòng 1 do luật cứng sinh, vòng 2 do mô hình tự gọi `design_scope(action='ask')`).
Ba ca plan không có luật tương đương nào.

### 4.2 Độ sâu tìm hiểu: nông

- Ca A: **1** lượt `web_search` (phiên chính) + **0** ở phiên con; 1 con `explore` đọc workspace
  (7097 ký tự nhưng là khảo sát trong box). Plan v2 tự khai 11 "external facts", trong đó 7 có nguồn
  (`externalFactsSourced` 7/11) — v2 đạt `P6` = 1, tức "có nhưng chưa đủ".
- So sánh có sẵn: lượt research cũ (chế độ research) có **129** lượt tìm, **tất cả ở phiên con**
  (0 ở phiên chính). Chênh nhau 129 lần.
- Ca C: 0 lượt tìm — **hợp lý** vì việc nằm trong workspace; bù lại có 1 con `explore` đọc `slugify.py`
  và `test_slugify.py` thật rồi dẫn lại nội dung vào plan.

Kết luận: cơ chế "grounding" trong chế độ plan hiện phụ thuộc vào mức tự giác của mô hình; với yêu cầu
mơ hồ, nó dừng ở 1 lượt tìm. Không có ngưỡng nào của harness buộc phải tìm trước khi viết.

### 4.3 Hợp dạng yêu cầu: có — và ca UI sang design đúng

- Ca A (hệ thống): plan v2 có bảng **module + input/output + đường đi của lỗi**, hợp đồng gọi giữa
  các ranh giới, 6 bảng dữ liệu (`patients_master`, `raw_records`, `fhir_resources`, `patient_links`,
  `link_review_queue`, `audit_log`), ngưỡng linkage và cả 6 bước đều có lệnh + kết quả mong đợi đo được
  (`≥5 passed`, `valid FHIR R4`, `precision ≥0.95`, `chain OK`). Đây là "kiến trúc/lý thuyết/luồng/data"
  đúng nghĩa.
- Ca B (UI): `/design <text>` được nhận đúng là **lệnh mode** (`resolution.kind='mode'`,
  `command='design'`, `output='Đã bật chế độ Design.'`), phiên bật `designMode.on = true`; và
  **0** hàng `plan_written` — mô hình **không** sinh plan kiến trúc cho việc UI. Đầu ra là kế hoạch
  thiết kế màn hình: bố cục trái/phải, kích thước ô nhập, 7 hành vi sửa nỗi đau "sai mật khẩu không
  rõ lỗi", câu chữ tiếng Việt, và mục "Nghiệm thu 5 phút" gồm 4 mục. Đúng dạng yêu cầu.
- Ca C: đầu ra là spec chốt + 3 milestone + acceptance criteria cho **một hàm**, không phải kiến trúc
  hệ thống. Đúng dạng.

### 4.4 Công tâm: phần máy thì thật, phần phản biện thì trống

Chấm máy (từ sự kiện `plan_evaluated`) không nương tay:

- Ca A v1 lần viết đầu bị **từ chối** ngay: 11/16, `verdict='fail'`, cổng cứng `P4` không đạt vì
  `stepsAnchored` = 2/6 (2 trong 6 bước không neo được vào lệnh/độ đo). Mô hình sửa và viết lại; v2
  đạt 13/16 `pass`.
- Ca C đạt 15/16 `pass`, nhưng vẫn **P1 = 1** (thiếu "vì sao chọn cách này, phương án bị loại" ở
  phần mục tiêu). Điểm không phải mặc định 2.

Ba vết trừ về công tâm, nói thẳng:

1. **`P5` luôn = 2 dù giám khảo đã tắt.** Trong mọi hàng đo được, `levels.P5 = 2` và `layer.P5` là
   `oracle`, trong khi thang `plan_eval.py` ghi rõ chỉ `P5` là chiều do **giám khảo LLM** chấm và chỉ
   khi `BOXFOX_PLAN_JUDGE=1` (mặc định TẮT). Nghĩa là điểm ấy là **giá trị mặc định**, không phải kết
   quả đo — đọc bảng `P1–P8` phải trừ `P5` ra.
2. **Không ca nào có `plan_verified`.** Con `plan-review` của ca A (sid `224de9af953b44328903f9b3b07bf430`,
   chết ở bước 5, `deadlineUsedMs` 220327) và của ca C (sid `ed6a6104b3f440cdb95c733a1a62b4ad`
   bước 5 / `4be064d0bc8b4e50af1b9eaffa6cffad` bước 6, `deadlineUsedMs` 604034) đều chết vì
   `UPSTREAM_HTTP_502: the model router answered Router HTTP 502 (Provider returned no complete
   response.)` — lỗi nhà cung cấp phía router, **không phải lỗi harness**. Thêm một con ở ca C
   *hoàn tất* nhưng chỉ trả **78 ký tự** — dưới ngưỡng `PLAN_REVIEW_MIN_ANSWER_CHARS = 400` nên cổng
   provenance cũng chặn. Hệ quả: cổng `PLAN_VERIFY` chưa từng có dữ liệu để chạy đúng chức năng.
3. **Phần trung thực của mô hình thì đạt**: cả hai ca đều kết thúc bằng báo cáo tự nêu giới hạn
   ("Sổ nguồn: 0 dòng", "Critique v2 vừa fail `UPSTREAM_HTTP_502`, cần retry"), không nhận đã kiểm
   thử khi chưa chạy gì. Cả hai ca vẫn bị nhãn `EVIDENCE_INSUFFICIENT` vì câu trả lời cuối không mang
   bằng chứng cho việc đã làm — cổng này hành xử đúng thiết kế, không phải lỗi.

## 5. Phát hiện kèm mức độ

### F1 — (NẶNG, ĐÃ SỬA trong nhánh này) Trả lời lời hỏi design không mở lượt tiếp tục

Số đo sống: lời hỏi `dp-be5d1e19e28c` (ca B) được trả lời lúc `13:54:24.584Z` với `start=true`;
tuyến trả `{"status": "answered", "start": true, "resume": true}` và ghi `phaseHistory` mục
`briefing/prompt-answered`; run còn `status='designing'`, `phase='briefing'`. Sau đó: **không lượt
nào chạy tiếp** (kiểm lúc `14:17Z` — 23 phút — phiên vẫn `completed`, sự kiện cuối vẫn là
`design_run` ở seq 9798).

Nguyên nhân trong mã:

- `design_runtime.design_prompt_answer` (`design_runtime.py:1294`) **chỉ ghi sổ**, trả `resume: true`.
- Tuyến `api/server.py:977` **không** gọi `runtime.submit` khi `resume` — trong khi đường research đã
  làm việc đó từ trước (`research_prompt_answer`, `api/server.py:790-798`).
- Lưới an toàn cũng không phủ: `design_continuation_step` (`api/server.py:114`) **chỉ bơm run ở pha
  `scaffolding`/`reviewing`**, không phủ `briefing`.

Đã sửa trong nhánh `vorflux/plan-mode-verification`: tuyến `design_prompt_answer` nay mở lượt tiếp
tục khi `resume` và run còn thuộc mode (`design_job_pumpable`), bỏ qua khi phiên đang chạy
(`running`/`awaiting_decision`), và không biến cửa sổ đua thành 500 (`SESSION_BUSY` ghi nhật ký hệ
thống). Bốn bài kiểm mới ở `backend/tests/unit/test_design_prompt_resume.py` chứng minh: có `start`
⇒ mở đúng một lượt (và **không** mở khi thiếu `start`, khi phiên bận, khi run không thuộc mode);
bài F1-01 **fail trên cây chưa vá** và **pass sau khi vá**.

### F2 — (NẶNG về sản phẩm, CHƯA sửa) Không có bước hỏi lại bắt buộc khi yêu cầu mơ hồ

Cơ chế hiện tại: kỹ năng `planning` không đòi hỏi hỏi lại, prompt hệ thống lại khuyên "act, don't ask",
và không có cổng nào kiểm "đã hỏi khi mơ hồ". Đề xuất (không tự làm trong nhánh này):
(1) thêm bước 0 "clarify" vào kỹ năng `planning` khi plan sắp dựa trên ≥1 giả định chưa xác nhận, hoặc
(2) thêm cổng mềm phát `notice` khi plan chứa mục giả định mà lượt không có `ask_user`/`decision_requested`.
Cách (2) rẻ, không phá luồng, và đo được.

### F3 — (VỪA) Lượt plan có thể kết thúc mà không bao giờ có kết luận phản biện

Hai ca trên ba rơi đúng vào đây. Harness đã có cổng đúng chỗ (`PLAN_APPROVAL_UNVERIFIED` chặn duyệt,
`PLAN_VERIFY_NO_CRITIC` chặn ghi verdict thiếu chứng), nhưng **không có gì nhắc mô hình rằng lượt đang
kết thúc mà verdict còn trống**, và **không có đường thử lại con `plan-review` khi nhà cung cấp 502**.
Ghi nhận là phát hiện, chưa sửa (cần quyết định sản phẩm: nhắc trong prompt, hay bơm cổng chặn).

### F4 — (NHẸ, dễ đọc sai số) `P5` là điểm mặc định khi giám khảo tắt

Xem §4.4.1. Không phải lỗi tính toán, nhưng bất kỳ ai trích bảng `P1–P8` mà không biết điều này sẽ
kết luận sai về chất lượng plan.

### F5 — (MÔI TRƯỜNG) Workspace trong box không phải repo git ⇒ chặn toàn bộ nhánh ghi của design

`docker exec agentbox-box bash -lc 'cd /home/agent/workspace && git rev-parse --is-inside-work-tree'`
→ `fatal: not a git repository`. Hệ quả đúng theo hợp đồng: `design_branch_create` trả
`DESIGN_WORKSPACE_NOT_REPO`, `design_write` (sau khi touch list đã duyệt) cũng trả đúng mã ấy. Mô hình
xử lý **đúng**: nó mở lời hỏi `kind='out-of-scope'` (hai lựa chọn `exit`/`keep`) thay vì bịa kết quả.
Đây là giới hạn của môi trường đo, không phải lỗi của chế độ design; nhưng nó chặn phép đo "design ghi
được file".

## 6. Điểm theo thang D1–D10 (thang phụ của phép đo này)

Mỗi chiều 0–2; **cổng cứng D1 và D9**; `—` = không áp dụng cho dạng việc đó (theo chính định nghĩa
của thang). **Tổng không so sánh được giữa các ca** vì số chiều áp dụng khác nhau.

| Chiều | A (hệ thống) | B (UI) | C (hàm nhỏ) | Lý do ngắn |
|---|---|---|---|---|
| D1 xử lý mơ hồ | 1 | 2 | 1 | A: có 1 tìm kiếm + 1 con `explore` nhưng **không hỏi**, không nêu giả định ở đầu plan. B: hỏi 2 vòng, 3 câu/vòng, 2–5 lựa chọn + ô tự nhập (vòng 1 do luật cứng, vòng 2 do mô hình). C: không cần hỏi, grounding bằng 1 con `explore` đọc file thật |
| D2 độ sâu tìm hiểu | 1 | 0 | 0 | A: 1 lượt tìm (chính), 0 ở con. B/C: 0 lượt tìm — B hợp lý (việc UI trong app có sẵn), C hợp lý (việc trong workspace) |
| D3 kiến trúc & lý thuyết | 2 | — | — | A: bảng module + I/O + đường lỗi + 6 bảng + deps chốt; có nêu phương án bị loại (v1 "5 agent" → v2 modular monolith) |
| D4 luồng hoạt động | 1 | — | — | A: có state-machine ingest→normalize→link→serve nhưng **bằng lời**, không sơ đồ/bảng chuyển trạng thái |
| D5 nguồn dữ liệu | 2 | — | — | A: FHIR R4, HL7v2-subset, 6 bảng SQLite, `dead_letter/`, nhắc Luật KCB 15/2023/QH15; tự ghi phần "chưa hiệu chỉnh" |
| D6 hợp dạng yêu cầu | 2 | 2 | 2 | A: kiến trúc/luồng/data. B: kế hoạch màn hình + trạng thái + nghiệm thu, **không** kiến trúc. C: spec + milestone + acceptance cho một hàm |
| D7 kiểm chứng & rủi ro | 2 | 2 | 2 | A/C: mỗi bước có lệnh + kết quả mong đợi; có mục Risks. B: "Nghiệm thu 5 phút" 4 mục + nêu rủi ro môi trường |
| D8 công tâm & trung thực | 2 | 2 | 2 | A/C: tự nêu nguồn rỗng + critique fail, không nhận đã kiểm thử. B: tách rõ "Đã xác nhận với bạn" vs "Tôi tự giả định", từ chối bịa file |
| D9 bàn giao & phản biện (cổng) | **0** | 1 | **0** | A/C: **không** verdict, không `plan_verified` ⇒ 0, cổng cứng đổ. B: chưa tới bước soát độc lập (môi trường chặn ghi) nhưng **không** kết thúc trong im lặng ⇒ 1 |
| D10 tác dụng thực tế | 1 | 1 | 1 | A: plan v2 7991 B trong `.plans/` của box, nhưng **chưa duyệt được** vì thiếu verdict. C: 6008 B, cùng lý do. B: kế hoạch nằm trong chat, chưa có tệp |
| **Tổng (số chiều áp dụng)** | **14/20** | **10/14** | **8/14** | A: 11–15 "có điều kiện" nhưng **cổng D9 = 0 ⇒ chưa đạt**. B: 10/14 "có điều kiện". C: 8/14 "chưa đạt" vì cổng D9 = 0 |

## 7. Giới hạn của phép đo

- Ba ca, **một mô hình**, một cấu hình harness. Không suy ra được cho model khác.
- `UPSTREAM_HTTP_502` của nhà cung cấp làm hỏng đúng phần **phản biện** — phần quan trọng nhất của
  chế độ plan. Vì vậy các kết luận về `plan_verify` là "chưa đo được", không phải "hỏng".
- `BOXFOX_PLAN_JUDGE` đang TẮT ⇒ chiều `P5` chưa từng được chấm thật.
- Không đo chi phí token theo đồng, không đo nDCG, không so nhiều model.
- Ca B bị môi trường chặn ở bước ghi file (F5) nên phần "design ghi được gì trong box" **chưa** đo được.

## 8. Cách chạy lại

Bộ đo nằm ở `/var/tmp/plan-exp/` (máy sandbox của phiên này): `new_session.py`, `send_turn.py`,
`watch.py` (theo dõi + tự trả lời theo `policy*.json`), `score.py`, `summarize.py`, `tail_events.py`,
`lib.py`. Ba bản ghi nguyên văn: `runA-vague.events.all.jsonl`, `runB-ui.events.all.jsonl`,
`runC-clear.events.all.jsonl`.

```bash
cd /var/tmp/plan-exp
python3 new_session.py runX --deadline 1200 --steps 60        # tạo phiên, in ra sid
python3 send_turn.py runX prompts/A-system.txt                # gửi lượt
python3 watch.py runX --policy policy.json --max-seconds 1500 # theo dõi + trả lời tự động
python3 summarize.py runA-vague runB-ui runC-clear            # bảng + JSON một dòng mỗi ca
python3 tail_events.py runB-ui 9780                            # xem đuôi sự kiện
```

Mọi lời gọi HTTP tới harness cần **cả hai** header: `X-BoxFox-Admin: 1` và
`Origin: http://localhost:3100` (cổng admin ở `api/server.py:323-331`). Sự kiện trả theo trang 500 —
phải đọc hết trang, nếu không sẽ đếm thiếu (đã kiểm chứng: một phiên research cũ cần 3 trang = 1087
sự kiện; cách đọc một lần báo thiếu 587 sự kiện, tức 54%). Việc tìm kiếm nằm ở **phiên con**, không
phải phiên chính (đo trên phiên research cũ: 129 ở con, 0 ở chính). Và trước khi kết luận "không tìm
kiếm", phải kiểm hai biến `BOXFOX_SEARCH_PIPELINE=on` + `BOXFOX_SEARXNG_URL` của tiến trình harness —
thiếu chúng thì chân tìm kiếm không tồn tại, và kết luận sẽ sai.

## 9. Đề xuất ưu tiên

1. **F2 — luật "hỏi lại khi mơ hồ"** (ảnh hưởng trực tiếp câu hỏi của chủ nhà): thêm bước clarify vào
   kỹ năng `planning`, hoặc cổng mềm phát `notice` khi plan dựa trên giả định mà lượt không hỏi ai.
2. **F3 — đường phản biện có lưới**: khi con `plan-review` chết vì lỗi nhà cung cấp, lượt nên được
   nhắc (hoặc tự thử lại một lần) trước khi kết thúc, vì không có verdict thì plan **không thể** được duyệt.
3. **F1 — đã sửa** ở nhánh này; giữ bài kiểm `test_design_prompt_resume.py` làm chốt chống tái phát.
4. **F5 — môi trường**: nếu muốn đo được nhánh ghi của design, workspace trong box phải là repo git
   (hoặc phải có đường scaffold tường minh).
