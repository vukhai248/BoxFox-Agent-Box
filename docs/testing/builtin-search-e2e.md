# Test E2E tìm kiếm built-in không khoá (SearXNG tự host)

> **Trạng thái:** ba tầng test đã chạy trên máy này ngày **2026-10-06** — tầng đơn vị 148 xanh + **1 ca
> đỏ có sẵn từ `main`** (không phải hồi quy của đợt này, xem §1), tầng stub 4 xanh, tầng live 5 xanh.
> Phạm vi: `web_search` chạy được **không cần khoá API bên thứ ba** nhờ SearXNG tự host + tự dò
> `127.0.0.1:8888`, và lỗi F05 (thiếu cấu hình / backend chết) được phân loại thay vì xui sửa truy vấn.
>
> Bản ghi quyết định: [`docs/plan/builtin-search-default.md`](../plan/builtin-search-default.md).
> Vận hành SearXNG: [`deploy/searxng/README.md`](../../deploy/searxng/README.md).
> Nghiên cứu nhà cung cấp (kèm số đo 06/10/2026): [`docs/research/host-web-tools.md`](../research/host-web-tools.md).

## 1. Ba tầng test

| Tầng | Lệnh (chạy từ gốc repo) | Cần gì | Kết quả đo 2026-10-06 |
|---|---|---|---|
| 1 — đơn vị | `cd backend && TMPDIR=/var/tmp PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/unit/test_search_pipeline.py tests/unit/test_searxng_provider.py tests/unit/test_search_failures.py tests/unit/test_health_search_status.py tests/unit/test_web_tools.py` | không mạng, không Docker | `148 passed, 1 failed` — ca đỏ là **có sẵn từ `main`**, xem ghi chú dưới |
| 2 — stub loopback | `cd backend && TMPDIR=/var/tmp PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/integration/test_search_searxng_stub.py` | một `http.server` trong tiến trình, **không** Docker, **không** Internet | `4 passed` (2,09 s) |
| 3 — live (container thật) | `cd backend && TMPDIR=/var/tmp PYTHONPATH=src python3 -m pytest -q -p no:cacheprovider tests/integration/test_search_searxng_live.py -rs` | SearXNG đang chạy ở `http://127.0.0.1:8888` (hoặc `BOXFOX_SEARXNG_LIVE_URL`) | `5 passed` (2,86 s); khi container vắng: `5 skipped` kèm câu `SearXNG chưa chạy: bash deploy/searxng/up.sh (xem docs/testing/builtin-search-e2e.md)` |

Máy này dùng venv sẵn có thay cho `python3` trần:
`/var/tmp/boxfox-venv/bin/python` (có pytest 8.4.2). Trên máy khác cứ dùng `python3` sau khi cài
`backend/requirements.txt`.

**Ghi chú ca đỏ tầng 1 (trung thực):** `test_web_tools.py::test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`
đỏ với `AttributeError: 'types.SimpleNamespace' object has no attribute 'db'` tại
`agent_core/research_gateway.py:37` (`_exists(store)` cần `store.db`, còn ca test dựng store giả bằng
`SimpleNamespace`). Đã **tái hiện y hệt trên bản sao sạch của `main` @ `f8f33b3`** (checkout riêng,
không có thay đổi của đợt này) ⇒ đây là nợ có sẵn của `main`, không phải hồi quy tìm kiếm. Đừng
"chữa" nó bằng cách sửa `web.py`; nó thuộc `research_gateway`/ca test.

Tầng 1 cố ý **không chạm mạng**: `backend/tests/unit/conftest.py` có fixture autouse
`searxng_autodetect_off` ghim `BOXFOX_SEARXNG_AUTODETECT=off` và xoá cache dò — nếu thiếu nó, máy nào
đang chạy SearXNG thật sẽ làm một số ca đơn vị lặng lẽ đi ra mạng thật.

## 2. Bật SearXNG (điều kiện của tầng 3)

```bash
# Khuyến nghị: bật + chờ /healthz = OK (≤30 s) + chạy probe.py + in URL dùng được
bash deploy/searxng/up.sh

# Instance thứ hai trên cùng máy (tên container riêng boxfox-searxng-8899)
SEARXNG_PORT=8899 bash deploy/searxng/up.sh

# Đổi URL cho bước probe của up.sh (mặc định http://127.0.0.1:$SEARXNG_PORT)
BOXFOX_SEARXNG_URL=http://127.0.0.1:8888 bash deploy/searxng/up.sh
```

`up.sh` = `docker compose -f deploy/searxng/docker-compose.yml up -d` → dò `/healthz` bằng `python3`
(không phụ thuộc `curl`) → chạy `probe.py`. Mã thoát `0`/`2` của probe được coi là sẵn sàng; mọi mã
khác in 40 dòng log cuối của compose rồi thoát khác 0.

Harness **tự dò** `http://127.0.0.1:8888` khi `BOXFOX_SEARXNG_URL` trống — bật SearXNG xong là
`web_search` dùng được, **không cần đặt biến, không cần khởi động lại harness** (tự nhận trong ≤30 s;
cache dò dương 30 s / âm 15 s). Hai cái bẫy đã đo (granian bỏ qua `server.port`; `network_mode: host`
không bind được trong sandbox) ghi ở `deploy/searxng/README.md` §1.

## 3. Biến môi trường quan trọng

| Biến | Mặc định | Dùng cho |
|---|---|---|
| `BOXFOX_SEARXNG_URL` | (rỗng — tự dò) | Ghi đè địa chỉ instance; **luôn thắng** tự dò |
| `BOXFOX_SEARXNG_AUTODETECT` | bật | `off/0/false/no` ⇒ tắt tự dò (test đơn vị ghim `off`) |
| `BOXFOX_SEARXNG_AUTODETECT_URL` | `http://127.0.0.1:8888` | Đổi địa chỉ tự dò |
| `BOXFOX_SEARCH_PIPELINE` | `auto` | `auto\|on\|off` — điều khiển đường ống 10 bước (`off` = công tắc giết một dòng) |
| `BOXFOX_SEARCH_DB` | `$BOXFOX_AGENT_DATA_DIR/search.sqlite` → `~/BoxFox/harness/` | DB bộ đệm + bảng sức khoẻ engine; **mỗi lượt test/bench nên trỏ chỗ riêng** để không ăn cache của nhau |
| `BOXFOX_SEARXNG_LIVE_URL` | `http://127.0.0.1:8888` | Chỉ tầng 3: đổi đích container (đặt `http://127.0.0.1:9` để thử nhánh `skip`/chân chết) |

Tầng 3 **xoá sạch** `BRAVE_API_KEY`, `BOXFOX_BRAVE_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY`,
`PARALLEL_API_KEY`, `FIRECRAWL_API_KEY` trước mỗi bài — bài xanh vì có khoá thì không chứng minh
được "không khoá vẫn tìm được". Đừng "sửa" chỗ này.

## 4. `probe.py` — phán quyết sâu theo engine

```bash
python3 deploy/searxng/probe.py                 # bản người đọc
python3 deploy/searxng/probe.py --json          # JSON cho up.sh/E2E/trạm đo
python3 deploy/searxng/probe.py --url http://127.0.0.1:8899 --query 'một truy vấn'
```

| Mã thoát | Nghĩa |
|---|---|
| `0` | Có ít nhất một truy vấn trả hàng |
| `2` | Instance sống nhưng **không** truy vấn nào trả hàng (được coi là sẵn sàng về hạ tầng) |
| `3` | Không kết nối được instance |

`--json` in **một** đối tượng JSON trên stdout: `url`, `ok`, `verdict` (`results|empty|unreachable`),
`exit_code`, `probes[]` (mỗi truy vấn: `query`, `http_status`, `latency_ms`, `results`, `engines[]`,
`unresponsive_engines[]`), tổng hợp `engines[]` / `unresponsive_engines[]`, và khối `brave` (một lời
gọi riêng `engines=brave` — nền proxy Brave của kịch bản đo 8.7). Trích kết quả đo thật 2026-10-06
(một truy vấn, không khoá):

```json
{ "url": "http://127.0.0.1:8888", "ok": true, "verdict": "results", "exit_code": 0,
  "probes": [ { "query": "retrieval augmented generation", "http_status": 200, "latency_ms": 542,
                "results": 24, "engines": [ {"engine": "google cse", "rows": 14}, {"engine": "bing", "rows": 10} ],
                "unresponsive_engines": [ {"engine": "brave", "reason": "Suspended: too many requests"},
                                          {"engine": "duckduckgo", "reason": "CAPTCHA"},
                                          {"engine": "google", "reason": "Suspended: access denied"},
                                          {"engine": "qwant", "reason": "CAPTCHA"} ] } ] }
```

Bảng engine đo được (2026-10-06, IP trung tâm dữ liệu — dịch vụ ngoài, có thể đổi):

| Engine | Kết quả |
|---|---|
| `google cse` | 14–20 hàng (nguồn chính hôm nay) |
| `bing` | 10 hàng |
| `brave` | 429 — `"Suspended: too many requests"` |
| `google` | 403 — `"Suspended: access denied"` |
| `duckduckgo`, `qwant` | CAPTCHA |

Bộ luân phiên bước 7 tự bỏ qua engine hỏng nên lượt tìm vẫn chạy. **Đừng dùng bảng này làm ngưỡng
cứng**: engine sống/chết theo IP và theo ngày.

## 5. Kịch bản bench

### 5.1 `scripts/eval/search_bench.py` — đo đầy đủ (cần cổng chi tiêu)

Script **đã có trong cây** (`scripts/eval/search_bench.py`, kế hoạch v2 §8.7). Cờ đã kiểm đúng
trong mã:

```bash
BOXFOX_EVAL_ALLOW_SPEND=1 python3 scripts/eval/search_bench.py \
    --configs legacy brave_proxy pipeline \
    --split test \
    --budget-usd 5 \
    --out /var/tmp/search-bench-2026-10-06 \
    --json
```

| Cờ | Ý nghĩa |
|---|---|
| `--configs [tên…]` | Mặc định `legacy brave_proxy pipeline`; nhận cả 5 ablation |
| `--split {dev,test}` | Mặc định `test` |
| `--out <thư mục>` | **Bắt buộc**; ghi `raw.jsonl`, `pool.jsonl`, `judged.jsonl`, `metrics.json`, `manifest.json` |
| `--budget-usd <số>` | Ngân sách (ghi vào `BOXFOX_EVAL_BUDGET_USD`) |
| `--json` | In JSON thay vì bảng người đọc |

| Tên cấu hình | Đường chạy |
|---|---|
| `legacy` | Đường cũ — ống **tắt** |
| `brave_proxy` | Nền proxy Brave: SearXNG **chỉ** engine `brave` |
| `pipeline` | Ống 10 bước đầy đủ |
| `ablation-no-expansion`, `ablation-no-rrf`, `ablation-no-dedupe`, `ablation-no-tierb-rerank`, `ablation-no-local-index` | Bỏ từng bước của ống |

Mã thoát: `0` xong · `2` sai cách dùng/dữ liệu · `3` cổng chi tiêu chưa mở.

**Cổng chi tiêu là hai yếu tố và áp cho TOÀN BỘ script**, không riêng phần chấm điểm: cần
`BOXFOX_EVAL_ALLOW_SPEND=1` **và** ngân sách (`--budget-usd N` hoặc `BOXFOX_EVAL_BUDGET_USD=N`,
> 0 USD). Thiếu một yếu tố ⇒ thoát mã `3` trước khi gọi gì. Phần chấm điểm bằng model nằm ở khâu gộp
nhóm (`judge.JudgeRunner`) nên còn cần kết nối router (`BOXFOX_ROUTER_BASE_URL`,
`BOXFOX_ROUTER_KEY`, … — xem `scripts/eval/guard.py` `KEY_HINTS`); bộ truy vấn là
`scripts/eval/search_queries.jsonl` (120 dòng). **Nói thẳng:** mọi `mapItems` trong bộ truy vấn còn
rỗng, nên `mapRecallTop20` là `chưa đo` cho tới khi P6 dựng bản đồ tham chiếu; các chỉ số còn lại
(nDCG@10 sau khi chấm, `freshRate`, `failureRate`, `latencyP50Ms`, `latencyP95Ms`) đo được.

### 5.2 Khi chưa có cổng chi tiêu — đo tối thiểu, không cần LLM

Mức tối thiểu của kịch bản (kế hoạch §R9): **độ trễ p50/p95 + tỉ lệ lỗi/hết giờ** của một cấu hình,
so `legacy` với `pipeline` bằng hai lần chạy với `BOXFOX_SEARCH_PIPELINE=off` và `=auto`. Chép
nguyên kịch bản dưới đây (đã chạy thử trên máy này), chạy **từ gốc repo**:

```bash
BOXFOX_SEARCH_PIPELINE=auto BOXFOX_SEARCH_DB=/var/tmp/bench-auto.sqlite \
    python3 - <<'PY'
import json, os, sys, time
from pathlib import Path
sys.path.insert(0, 'backend/src')
from agentbox.agent_core import search_pipeline
from agentbox.agent_core.web import WebTools

rows = [json.loads(line) for line in Path('scripts/eval/search_queries.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
queries = [row for row in rows if row.get('split') == 'test'][:10]   # đổi số lượng tuỳ ngân sách thời gian
search_pipeline.reset_store()
latencies, failures, pipelined = [], 0, 0
for row in queries:
    started = time.monotonic()
    try:
        payload = WebTools().search({'query': row['text'], 'count': 10})
        pipelined += 1 if payload.get('pipeline') else 0
    except Exception as exc:
        failures += 1
        print(f"  {row['id']}: {type(exc).__name__}: {str(exc)[:160]}", file=sys.stderr)
    latencies.append((time.monotonic() - started) * 1000)
ordered = sorted(latencies)
def pct(fraction):
    position = fraction * (len(ordered) - 1)
    low = int(position); high = min(low + 1, len(ordered) - 1)
    return ordered[low] * (1 - (position - low)) + ordered[high] * (position - low)
print(json.dumps({'mode': os.environ.get('BOXFOX_SEARCH_PIPELINE') or '(mặc định)',
                  'calls': len(ordered), 'failures': failures,
                  'failureRate': round(failures / len(ordered), 4) if ordered else None,
                  'latencyP50Ms': round(pct(0.5), 1), 'latencyP95Ms': round(pct(0.95), 1),
                  'pipelineCalls': pipelined}, ensure_ascii=False))
PY
```

Kết quả đo thử 2026-10-06 (các truy vấn đầu của `split=test`, SearXNG thật, **không khoá**):

| Lần chạy | Số truy vấn | p50 | p95 | Lỗi | Lời gọi qua ống |
|---|---|---|---|---|---|
| `BOXFOX_SEARCH_PIPELINE=auto` (mặc định) | 3 | 354,6 ms | 439,8 ms | 0 | 3/3 |
| `BOXFOX_SEARCH_PIPELINE=off` | 3 | 195,7 ms | 202,4 ms | 0 | 0/3 |
| `BOXFOX_SEARCH_PIPELINE=auto` (mặc định) | 10 | 239,7 ms | 551,0 ms | 0 | 10/10 |
| `BOXFOX_SEARCH_PIPELINE=off` | 10 | 273,7 ms | 324,8 ms | 0 | 0/10 |

Đọc đúng hai điều:
1. **Chân SearXNG một mình đã đủ trả hàng, không cần khoá** — cả bốn lượt chạy đều 0 lỗi, không khoá nào.
2. **Chênh lệch độ trễ ống ↔ đường cũ chưa kết luận được** với mẫu này: ở 3 truy vấn ống đắt hơn
   (354,6 vs 195,7 ms p50), ở 10 truy vấn ống lại thấp hơn p50 nhưng cao hơn p95 — hướng đảo theo mẫu,
   tức nhiễu chiếm ưu thế. Đúng rủi ro R2/R9 của kế hoạch: muốn chốt thì phải chạy §5.1 (nhiều truy vấn
   + nhãn chất lượng) hoặc ít nhất lặp lại §5.2 với cỡ mẫu lớn hơn. Trong lúc chờ, giữ `auto` và theo
   dõi `GET /api/agent/health` khối `search`; `BOXFOX_SEARCH_PIPELINE=off` là đường lùi một dòng.

Đo sức khoẻ engine mà không cần LLM: `python3 deploy/searxng/probe.py --json` (§4) — `engines` cho
biết engine nào trả hàng, `unresponsive_engines` cho biết engine nào đang bị CAPTCHA/429/403.

**Mẫu lớn hơn, cùng ngày 2026-10-06** — chạy `run_bench()` của §5.1 với `judge_pool` **thay bằng
hàm rỗng** (`lambda pool, out_dir, **kw: {}`): không gọi model, nên không tiêu đồng nào, mà vẫn ra
số đo độ trễ/độ lỗi trên **48 truy vấn `split=dev`** (mặc định của `scripts/eval/search_queries.jsonl`;
72 truy vấn `test` để dành cho lượt có chấm điểm) **× 2 cấu hình = 48 lời gọi mỗi cấu hình, 96 lượt**
(SearXNG cục bộ, không khoá, DB đệm riêng theo lượt chạy). Đúng script đã chạy (dán vào tệp rồi gọi
`python <tệp>` từ gốc repo):

```python
import json, os, pathlib, sys
sys.path.insert(0, 'scripts/eval')
os.environ.setdefault('BOXFOX_EVAL_ALLOW_SPEND', '1')
os.environ.setdefault('BOXFOX_EVAL_BUDGET_USD', '1.0')
os.environ['BOXFOX_SEARXNG_URL'] = 'http://127.0.0.1:8888'
import search_bench
search_bench.judge_pool = lambda pool, out_dir, **kw: {}
bench = search_bench.run_bench(['legacy', 'pipeline'], split='dev',
                               out_dir=pathlib.Path('/var/tmp/bench-builtin/out-dev'))
print(json.dumps(bench['metrics'], ensure_ascii=False, indent=1))
```

| Cấu hình | Lời gọi | p50 | p95 | Tỉ lệ lỗi/hết giờ | nDCG@10 |
|---|---|---|---|---|---|
| `legacy` (ống tắt) | 48 | 166,5 ms | 301,4 ms | 0,0 | — (chưa chấm) |
| `pipeline` (ống đầy đủ) | 48 | 234,5 ms | 599,1 ms | 0,0 | — (chưa chấm) |

Hai lượt chạy 48 truy vấn (lượt trên và lượt 09:31 cùng ngày, p50 `legacy` 160,0 / `pipeline` 233,5)
cho **cùng một kết luận về p50**: `auto` đắt hơn đường cũ khoảng **+68…+73 ms p50** mỗi lời gọi
`web_search`, đổi lấy 10 kết quả đã hợp nhất/khử trùng và bảng sức khoẻ engine. p95 dao động mạnh
giữa hai lượt (414,6 → 599,1 ms cho `pipeline`) vì nó phụ thuộc engine nào được luân phiên và lần
chạm đầu — **chốt R2 bằng p50, đừng chốt bằng p95**. Không lời gọi nào lỗi ở cả hai cấu hình. Muốn
số nDCG thì phải mở cổng chi tiêu cho phần chấm (§5.1).

## 6. Ghi chú vận hành khi chạy test

- Tầng 3 dùng chung instance `127.0.0.1:8888` với harness thật: nó **không** tắt/bật container, chỉ
  gọi. Muốn kiểm nhánh `skip`, đặt `BOXFOX_SEARXNG_LIVE_URL=http://127.0.0.1:9`.
- Mỗi bài tầng 3 tự trỏ `BOXFOX_SEARCH_DB` vào `tmp_path` — không đọc/ghi DB tìm kiếm thật của máy.
- Tầng 1 và tầng 2 **kín với khoá API của máy chạy**: fixture chung của `tests/unit/conftest.py` và
  fixture `stub` của tầng 2 xoá sáu biến khoá (`BRAVE_/BOXFOX_BRAVE_/TAVILY_/EXA_/PARALLEL_/FIRECRAWL_API_KEY`)
  trước mỗi bài — máy dev đang giữ khoá thật vẫn cho kết quả xanh như trên CI.
- Ca đối chiếu `test_probe_json_of_the_ops_script_agrees_with_the_harness` chạy `probe.py --json` bằng
  **chính trình thông dịch đang chạy test** và đòi `body['exit_code'] == returncode` — sửa `probe.py`
  mà đổi mã thoát thì ca này đỏ trước.
- Đợt này tầng live có **5** ca (kế hoạch ghi 4): ca thứ năm là ca đối chiếu `probe.py` ↔ harness nói
  trên, thêm trong lúc thi công vì `probe.py --json` là bề mặt vận hành mới.
