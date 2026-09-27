# `scripts/eval` — giàn đánh giá chất lượng và benchmark

Trạng thái 2026-09-20: **đã dựng xong giàn, CHƯA chạy lượt đánh giá nào, CHƯA tiêu đồng nào.**
Mọi con số chi phí trong thư mục này là **ước lượng của kế hoạch**, không phải hoá đơn.

Hai kế hoạch gốc:

- [`docs/plan/agent-output-quality-plan.md`](../../docs/plan/agent-output-quality-plan.md) — rubric C1–C8,
  chỉ số vội S1–S10, 12 fixture Q1–Q12, ba lớp chấm.
- [`docs/plan/cua-benchmark-plan.md`](../../docs/plan/cua-benchmark-plan.md) — bốn tầng benchmark.

## 1. Chạy được ngay, miễn phí, không mở kết nối mạng

```bash
python3 scripts/eval/run_eval.py                     # mặc định là dry-run: in kế hoạch + chi phí ước lượng
python3 scripts/eval/run_eval.py --list              # liệt kê 12 fixture và các tầng benchmark
python3 scripts/eval/run_eval.py --plan-tier 0       # kế hoạch chi phí của một tầng cụ thể
python3 scripts/eval/run_eval.py --fixture Q1 --fixture Q2 --configs 3 --repeat 2
python3 scripts/eval/rushed_index.py                 # chỉ số vội từ nhật ký hệ thống thật (~/BoxFox/logs)
python3 scripts/eval/rushed_index.py --rotated --json # đọc thêm bản xoay vòng .0-.3, in JSON
python3 scripts/eval/judge.py --info                 # phiên bản + sha256 của prompt giám khảo đã đóng băng
python3 scripts/eval/judge.py --layer 2 --fixture Q5 # in prompt giám khảo cho một ca, nhãn mù
python3 scripts/eval/scoreboard.py --results <thư-mục-kết-quả> [--out docs/tracking/eval-<tên>.md] [--verify]
```

Bốn bộ test hiện có cũng là "benchmark hồi quy" của tầng 0 — xem
[`benchmarks/tier0.md`](benchmarks/tier0.md) để có lệnh và số đo ngày 2026-09-20.

Dry-run **không** import thư viện mạng và **không** gọi model: bài test
`backend/tests/unit/test_eval_setup.py::test_dry_run_writes_a_plan_and_refuses_to_touch_the_network`
thay `socket.socket` bằng một lớp luôn ném lỗi rồi chạy `run_eval.main(['--dry-run'])`.

## 2. Muốn tiêu tiền thì phải mở hai khoá

`--execute` cần **đủ hai yếu tố**, thiếu một là dừng (mã thoát 3):

| Khoá | Cách mở |
|---|---|
| Đồng ý chi tiêu | `BOXFOX_EVAL_ALLOW_SPEND=1` (đúng chuỗi `1`) |
| Ngân sách | `--budget-usd N` **hoặc** `BOXFOX_EVAL_BUDGET_USD=N`, với `N > 0` |

Thêm bốn biến kết nối, thiếu thì dừng với mã thoát 4 **trước khi** gọi gì:
`BOXFOX_ROUTER_BASE_URL`, `BOXFOX_ROUTER_KEY` (khoá `bf_…`), `BOXFOX_HARNESS_BASE_URL`,
`BOXFOX_HARNESS_ADMIN_TOKEN`.

**Không dán giá trị bí mật vào chat.** Khoá do chủ sở hữu đặt trong môi trường của máy.

**Từ P0a, `--execute` thật sự chạy**: nó gọi `runner.run_scenario` cho từng ô
(fixture × cấu hình × lần lặp), rồi ghi `scores.jsonl` theo schema `research-scores-v2`
và `manifest.json` (ghim commit, băm gói nguồn, route, model, tỉ lệ lỗi hạ tầng).
`judge.JudgeRunner.request()` gọi thẳng router (`/v1/chat/completions`, hạn chờ 120 s,
thử lại hai lần khi 5xx) — vẫn qua cổng `guard.py` trước mọi lời gọi. Chưa có lượt
thật nào được chạy; ô `validity=infra-failed`/`harness-bug` ghi `metrics: null` (chưa
đo), không bao giờ ghi 0.

### Mã thoát

| Mã | Nghĩa |
|---|---|
| 0 | xong (dry-run, hoặc lượt `--execute` có ít nhất một ô hợp lệ về chất lượng) |
| 2 | sai cách dùng |
| 3 | bị cổng chi tiêu từ chối (thiếu opt-in hoặc thiếu ngân sách) |
| 4 | thiếu biến kết nối — dừng trước khi gọi; hoặc `--execute` xong mà không ô nào hợp lệ |
| 5 | (nghỉ hưu) trước đây là "chưa cài đặt runner"; `--execute` không còn trả mã này |

## 3. Chi phí ước lượng theo tầng (số của kế hoạch, chưa đo)

| Đợt | Lượt gọi model | Chi phí ước lượng |
|---|---|---|
| Tầng 0 (4 bộ test hồi quy) | 0 | 0 USD |
| Tầng 0 (BFCL simple subset) | 200 (BFCL V4 `simple_python` thật: 399) | 2–10 USD |
| Bộ 12 fixture chất lượng × 3 cấu hình × 1 lần lặp | 108 (36 agent + 72 chấm lớp 2) | 6,44–23,60 USD |
| Tầng 1 (cộng theo hạng mục) | 268 | 61,44–213,60 USD (kế hoạch ghi cả tầng 50–150 USD) |

`run_eval.py` luôn in dải giá **của hạng mục** và, khi khác, in luôn con số kế hoạch ghi cho cả tầng,
kèm lý do lệch. Chỗ lệch đã biết: §7 của kế hoạch chất lượng ước ~1,2 lượt chấm cho mỗi đầu ra, còn
§5 nói mỗi đầu ra chấm **hai lần** — script tính 2, nên khoảng tiền lớp 2 luôn ≥ khoảng của kế hoạch.

## 4. Cấu trúc

| Tệp | Việc |
|---|---|
| `run_eval.py` | cửa vào duy nhất: `--list`, `--dry-run`, `--plan-tier`, `--execute` (chạy thật khi đủ khoá) |
| `guard.py` | cổng chi tiêu hai yếu tố + kiểm biến kết nối |
| `net.py` | **chỗ duy nhất** mở socket trong `scripts/eval` (`urllib`, stdlib); chỉ gọi trong đường `--execute` |
| `runner.py` | chạy một ca qua harness, phân loại `quality-valid`/`infra-failed`/`harness-bug`, chạy lại, băm gói nguồn |
| `reference_map.py` | bản đồ tham chiếu (§8.3) + recall có trọng số |
| `grading.py` | gói chấm mù `G-0NN` (§8.6), bảng chấm 0–4, mở khoá + độ khớp |
| `search_bench.py` | đo 8.7: `search_queries.jsonl`, nDCG@10, recall top-20, tỉ lệ mới/lỗi, p50/p95 |
| `packs/build_pack.py` + `packs/README.md` | dựng/kiểm gói nguồn đúng định dạng §3 |
| `rubric.py` | rubric C1–C8, điều kiện cứng, dải điểm, thống kê; tách lớp 1/lớp 2 |
| `rushed_index.py` | chỉ số vội S1–S10 đọc từ nhật ký hệ thống; tín hiệu không đo được thì ghi `not_measured` |
| `logread.py` | đọc JSONL thuần, không import `agentbox`, không mở socket; cửa sổ gồm cả `harness.previous.jsonl` (và `.0-.3` khi `--rotated`), bỏ dòng trùng giữa các tệp |
| `fixtureset.py` + `fixtures/Q*.json` | 12 ca Q1–Q12, kiểm tra hợp lệ khi nạp |
| `judge.py` + `prompts/*.md` | prompt giám khảo đóng băng (có mã phiên bản), gộp điểm hai lớp |
| `manifest.py` | ghim commit/dirty/hash nguồn/schema công cụ/phiên bản prompt + chi phí thật từ nhật ký |
| `scoreboard.py` | dựng `docs/tracking/eval-<tên>.md`, `--verify` phát hiện lệch bảng điểm |
| `benchmarks/tiers.json`, `benchmarks/tier0.md` | bốn tầng benchmark + checklist tầng 0 |

## 5. Nơi ghi kết quả

Kết quả thô nằm **ngoài repo**: `~/BoxFox/eval-runs/<tầng>/` (có `manifest.json`, `cases.jsonl`,
`scores.jsonl`). Bảng điểm mới vào repo, ở `docs/tracking/eval-<tên>.md`. Bảng điểm không chứa dấu
thời gian render nên tính lại được từ dữ liệu thô; `--verify` so từng byte và thoát mã 1 khi lệch.

## 6. Còn thiếu (nói thẳng)

- Runner chạy fixture thật: **đã cài đặt (P0a)** — chưa chạy lượt thật nào (cần opt-in + ngân sách + harness).
- Lớp 2 (gọi giám khảo LLM): **đã cài đặt (P0a)** — chưa gọi lần nào; lớp 3 (chấm tay) có prompt + bảng chấm.
- Gói nguồn cố định cho 13 tình huống (§8.3): **chưa thu thập** — xem `packs/README.md`.
- Bộ 120 truy vấn đo 8.7: **đã có** (`search_queries.jsonl`), chưa chạy lượt đo nào.
- Lớp 1 mới có chỉ số vội; phần oracle kiểm từng fixture còn thiếu, và mỗi fixture đều có mục
  `open_questions` ghi rõ chỗ chưa có dữ liệu (repo mẫu, phiên 30 lượt, giả lập lỗi upstream rỗng…).
- Ba tín hiệu S1/S4/S5: **S4 đã đo được** từ vòng 22 — cổng bằng chứng ghi
  `data.evidenceVerdict`/`data.evidenceMissing` vào `turn.end`, nên `rushed_index.py` đọc thẳng con số
  thay vì đọc câu chữ; `value` = tỉ lệ lượt bị gắn cờ trên số lượt **đã đo**, `threshold` vẫn `> 20 %`,
  `flagged` kèm `verdict` từng lượt, và `note` in mốc nâng mặc định lên `enforce` (≥ 20 phiên có số
  VÀ tỉ lệ báo động sai < 10 % — D-8, kế hoạch đợt 3 §6). Cửa sổ log **không có khoá nào** của cổng
  (log cũ) thì S4 vẫn `not_measured` như trước, kèm lý do `not-evidence-gate-keys`.
  **S1/S5 vẫn không đo được** từ nhật ký hiện tại (S1 cần thêm một khoá vào `turn.end`/`tool.end`;
  S5 cần danh sách tệp trong workspace). S3/S6/S7 chỉ đo được bằng **proxy** vì nhật ký có tên tool và
  `isError` nhưng **không có tham số tool** — mọi proxy đều ghi rõ trong mã.
- Chưa chạy lượt nào ⇒ mọi chỉ số chất lượng vẫn là **chưa đo**.
