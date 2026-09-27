#!/usr/bin/env python3
"""Đo "tiệm cận Brave" của ống tìm không khoá (kế hoạch v2 §8.7, #6077).

Bốn nhóm cấu hình:

* `legacy` — đường cũ (`BOXFOX_SEARCH_PIPELINE` tắt);
* `brave_proxy` — nền giống Brave: SearXNG **chỉ** engine `brave`, một truy vấn, không rerank;
* `pipeline` — ống tìm đầy đủ (5.4.1);
* các **bản bỏ từng bước** (ablation): `ablation-no-expansion`, `ablation-no-rrf`,
  `ablation-no-dedupe`, `ablation-no-tierb-rerank`, `ablation-no-local-index`.

Chỉ số: nDCG@10, recall bản đồ tham chiếu trong top 20, tỉ lệ kết quả mới cho truy vấn
`needsFresh`, tỉ lệ lỗi/hết giờ, độ trễ p50/p95 mỗi lời gọi `web_search`.

**Chạy thật, gọi mạng từ host** ⇒ mô-đun này từ chối chạy nếu thiếu `BOXFOX_EVAL_ALLOW_SPEND=1`
và ngân sách (`BOXFOX_EVAL_BUDGET_USD` / `--budget-usd`). Kết quả thô được lưu lại để **chấm lại
không cần gọi lại**; khung giờ chạy ghi vào manifest.

Mã thoát CLI: ``0`` xong, ``2`` sai cách dùng, ``3`` cổng chi tiền chưa mở.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import guard  # noqa: E402
import reference_map as reference_map_mod  # noqa: E402

REPO_DIR = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_QUERIES = EVAL_DIR / 'search_queries.jsonl'
#: Tên tệp DB tách riêng cho MỘT cấu hình trong MỘT lượt chạy (H2). Nếu để chung DB mặc định của
#: harness, cấu hình sau đọc payload của cấu hình trước (latency ≈ 0 ms, chỉ số y hệt, số cũ).
BENCH_RUN_ENV = 'BOXFOX_SEARCH_BENCH_RUN'
BENCH_DB_DIR_ENV = 'BOXFOX_SEARCH_BENCH_DB_DIR'
SPLIT_VALUES = ('dev', 'test')

#: Cấu hình so sánh + cách chúng đi ống tìm. `ablation` chỉ được truyền vào
#: `run_pipeline(..., options={'ablation': …})`; B1 đọc khoá đó trong bước tương ứng.
CONFIG_SPECS: dict[str, dict] = {
    'legacy': {'label': 'Đường cũ (pipeline tắt)', 'kind': 'web', 'pipeline': False},
    'brave_proxy': {'label': 'Nền proxy Brave (SearXNG chỉ brave)', 'kind': 'searxng'},
    'pipeline': {'label': 'Ống tìm đầy đủ', 'kind': 'web', 'pipeline': True},
    'ablation-no-expansion': {'label': 'Bỏ mở rộng truy vấn', 'kind': 'web', 'pipeline': True,
                              'ablation': 'no-expansion'},
    'ablation-no-rrf': {'label': 'Bỏ RRF (một engine tốt nhất)', 'kind': 'web', 'pipeline': True,
                        'ablation': 'no-rrf'},
    'ablation-no-dedupe': {'label': 'Bỏ khử trùng', 'kind': 'web', 'pipeline': True,
                           'ablation': 'no-dedupe'},
    'ablation-no-tierb-rerank': {'label': 'Bỏ rerank tầng B', 'kind': 'web', 'pipeline': True,
                                 'ablation': 'no-tierb-rerank'},
    'ablation-no-local-index': {'label': 'Bỏ chỉ mục cục bộ', 'kind': 'web', 'pipeline': True,
                                'ablation': 'no-local-index'},
}
DEFAULT_CONFIGS = ('legacy', 'brave_proxy', 'pipeline')
#: Ngưỡng hết giờ một lời gọi (mục 7/8.7).
CALL_TIMEOUT_MS = 12000
REQUIRED_QUERY_KEYS = ('id', 'text', 'lang', 'needsFresh', 'facet', 'split', 'mapItems')
DEFAULT_JUDGE_TEMPLATE = (
    'Bạn chấm mức liên quan của MỘT kết quả tìm cho MỘT truy vấn. Thang 0–3:\n'
    '0 = không liên quan; 1 = liên quan xa; 2 = liên quan; 3 = rất liên quan/nguồn chính.\n'
    'Chỉ thấy tiêu đề và đoạn trích; không biết cấu hình nào tạo ra kết quả.\n'
    'Trả về ĐÚNG một chữ số 0–3, không giải thích.\n\n'
    'Truy vấn: {query}\nTiêu đề: {title}\nĐoạn trích: {snippet}\n')


def load_queries(path: str | Path = DEFAULT_QUERIES) -> list[dict]:
    """Đọc bộ truy vấn JSONL, kiểm hợp lệ; lỗi ⇒ `ValueError` kèm số dòng."""
    path = Path(path)
    rows: list[dict] = []
    seen: set[str] = set()
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise ValueError(f'{path}:{number}: dòng không phải JSON ({exc})') from exc
        if not isinstance(item, dict):
            raise ValueError(f'{path}:{number}: mỗi dòng phải là một đối tượng JSON')
        missing = [key for key in REQUIRED_QUERY_KEYS if key not in item]
        if missing:
            raise ValueError(f'{path}:{number}: thiếu khoá ' + ', '.join(missing))
        if not str(item.get('text') or '').strip():
            raise ValueError(f'{path}:{number}: text rỗng')
        if item.get('split') not in SPLIT_VALUES:
            raise ValueError(f"{path}:{number}: split phải là {SPLIT_VALUES}")
        if item['id'] in seen:
            raise ValueError(f'{path}:{number}: trùng id {item["id"]!r}')
        seen.add(item['id'])
        rows.append(item)
    if not rows:
        raise ValueError(f'{path}: không có truy vấn nào')
    return rows


def load_split(queries: list[dict], split: str) -> list[dict]:
    if split not in SPLIT_VALUES:
        raise ValueError(f'split phải là {SPLIT_VALUES}')
    return [item for item in queries if item.get('split') == split]


def ndcg_at_k(ranked: list[str], grades: dict, k: int = 10) -> float | None:
    """nDCG@k với mức liên quan 0–3. `None` khi chưa có nhãn nào (chưa đo, không ghi 0)."""
    if not grades:
        return None
    dcg = 0.0
    for position, row in enumerate(ranked[:k]):
        key = _grade_key(row, grades)
        if key is None:
            continue
        dcg += (2 ** int(grades[key]) - 1) / math.log2(position + 2)
    ideal = sorted((int(value) for value in grades.values()), reverse=True)[:k]
    idcg = sum((2 ** value - 1) / math.log2(position + 2) for position, value in enumerate(ideal))
    if idcg <= 0:
        return 0.0
    return round(dcg / idcg, 4)


def _grade_key(row: str, grades: dict) -> str | None:
    if row in grades:
        return row
    canonical = reference_map_mod.canonical_url(row)
    for key in grades:
        if reference_map_mod.canonical_url(key) == canonical:
            return key
    return None


def percentile(values: list[float], fraction: float) -> float | None:
    """Phân vị nội suy tuyến tính (p50 = 0.5); `None` khi rỗng."""
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] * (1 - weight) + ordered[upper] * weight, 2)


def compute_metrics(rows: list[dict], queries: dict[str, dict], grades_by_query: dict[str, dict],
                    maps: dict[str, dict] | None = None, *, k: int = 10,
                    fresh_windows: dict[str, dict] | None = None) -> dict:
    """Chỉ số của MỘT cấu hình từ các hàng thô. Chỉ số nào thiếu dữ liệu ⇒ `None`."""
    maps = maps or {}
    latencies: list[float] = []
    failures = 0
    ndcgs: list[float] = []
    recalls: list[float] = []
    fresh_flags: list[bool] = []
    for row in rows:
        latencies.append(float(row.get('latencyMs') or 0))
        error = row.get('error')
        if error or float(row.get('latencyMs') or 0) > CALL_TIMEOUT_MS:
            failures += 1
        results = row.get('results') or []
        ranked = [item.get('url') for item in results]
        query = queries.get(row.get('queryId')) or {}
        grades = grades_by_query.get(row.get('queryId'))
        if grades:
            value = ndcg_at_k(ranked, grades, k)
            if value is not None:
                ndcgs.append(value)
        reference = maps.get(str(query.get('facet') or '')) or maps.get(row.get('queryId'))
        if reference:
            recall = reference_map_mod.weighted_recall(reference, ranked[:20])['recall']
            if recall is not None:
                recalls.append(recall)
        if query.get('needsFresh'):
            window = (fresh_windows or {}).get(row.get('queryId'))
            if not window:
                continue  # chưa có cửa sổ thời gian ⇒ chưa đo, KHÔNG ghi 0
            fresh_flags.append(_is_fresh(results, window))
    total = len(rows)
    return {
        'calls': total,
        'ndcgAt10': round(statistics.fmean(ndcgs), 4) if ndcgs else None,
        'mapRecallTop20': round(statistics.fmean(recalls), 4) if recalls else None,
        'freshRate': round(sum(fresh_flags) / len(fresh_flags), 4) if fresh_flags else None,
        'failureRate': round(failures / total, 4) if total else None,
        'latencyP50Ms': percentile(latencies, 0.5),
        'latencyP95Ms': percentile(latencies, 0.95),
    }


def _is_fresh(results: list[dict], window: dict | None) -> bool:
    """Kết quả mới: ít nhất một URL top-10 có `publishedAt` nằm trong cửa sổ (nếu có)."""
    if not window:
        return False
    after = str(window.get('from') or '')
    for item in results[:10]:
        published = str(item.get('publishedAt') or '')
        if published and after and published >= after:
            return True
    return False


def _slug(value: str) -> str:
    return ''.join(char if char.isalnum() or char in '-_' else '-' for char in str(value or '')).strip('-')


def _bench_db_path(config: str) -> Path:
    """Tệp SQLite RIÊNG cho (lượt chạy, cấu hình) — không đụng DB thật của harness (H2).

    Token lượt chạy lấy từ `BOXFOX_SEARCH_BENCH_RUN` (do `run_bench` đặt; mặc định `pid`). Nhờ
    token này, chạy lại sau khi sửa ống KHÔNG đọc lại số cũ; nhờ tách theo cấu hình, cấu hình sau
    không đọc payload của cấu hình trước.
    """
    token = (os.environ.get(BENCH_RUN_ENV) or '').strip() or f'pid{os.getpid()}'
    base = (os.environ.get(BENCH_DB_DIR_ENV) or '').strip()
    root = Path(base) if base else (Path(os.environ.get('TMPDIR', '/tmp')) / 'boxfox-search-bench')
    return root / f'{token}-{_slug(config) or "config"}.sqlite'


def run_query(query: dict, config: str) -> dict:
    """MỘT lời gọi `web_search` cho một cấu hình. Mạng thật — chỉ gọi sau cổng chi tiền.

    Hàm này là ranh giới sống: test thay bằng `monkeypatch.setattr(search_bench,
    'run_query', fake)` để chạy hoàn toàn offline.
    """
    spec = CONFIG_SPECS.get(config)
    if spec is None:
        return {'queryId': query.get('id'), 'config': config, 'results': [], 'latencyMs': 0,
                'error': f'CONFIG_UNKNOWN: {config}', 'errorCode': 'CONFIG_UNKNOWN'}
    started = time.monotonic()
    try:
        rows = _perform_search(query['text'], spec, config)
        error = None
        error_code = None
    except Exception as exc:  # pragma: no cover - đường sống
        rows = []
        error = f'{type(exc).__name__}: {exc}'
        error_code = 'SEARCH_TOOLING_FAILED'
    return {
        'queryId': query.get('id'),
        'config': config,
        'results': rows,
        'latencyMs': int((time.monotonic() - started) * 1000),
        'error': error,
        'errorCode': error_code,
    }


def _perform_search(text: str, spec: dict, config: str) -> list[dict]:  # pragma: no cover - đường sống
    """Đường tìm thật. Gói nguồn LUÔN tắt (8.7 chạy không gói nguồn), DB đệm TÁCH theo cấu hình."""
    os.environ.pop('BOXFOX_WEB_PACK', None)
    if str(REPO_DIR / 'backend' / 'src') not in sys.path:
        sys.path.insert(0, str(REPO_DIR / 'backend' / 'src'))
    if spec.get('kind') == 'searxng':
        from agentbox.agent_core.search_pipeline import searxng_search
        payload = searxng_search(text, engines=['brave'], count=10)
        if payload.get('error'):
            raise RuntimeError(payload['error'])
        return [_result_row(item) for item in payload.get('results') or []]
    os.environ['BOXFOX_SEARCH_PIPELINE'] = 'on' if spec.get('pipeline') else 'off'
    if spec.get('ablation'):
        os.environ['BOXFOX_SEARCH_ABLATION'] = str(spec['ablation'])
    else:
        os.environ.pop('BOXFOX_SEARCH_ABLATION', None)
    db_path = _bench_db_path(config)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    os.environ['BOXFOX_SEARCH_DB'] = str(db_path)
    from agentbox.agent_core import search_pipeline
    search_pipeline.reset_store()                    # quên store cũ khi DB vừa đổi
    from agentbox.agent_core import web
    payload = web.WebTools().search({'query': text, 'count': 10})
    return [_result_row(item) for item in payload.get('results') or []]


def _result_row(item: dict) -> dict:
    return {'url': item.get('url'), 'title': item.get('title'), 'snippet': item.get('snippet'),
            'publishedAt': item.get('publishedAt')}


def build_pool(raw_rows: list[dict], queries: dict[str, dict]) -> list[dict]:
    """Gộp top-10 mọi cấu hình theo truy vấn, khử trùng URL chuẩn hoá, gán nhãn mù."""
    pool: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in raw_rows:
        query_id = str(row.get('queryId'))
        for item in (row.get('results') or [])[:10]:
            key = (query_id, reference_map_mod.canonical_url(item.get('url') or ''))
            if key in seen:
                continue
            seen.add(key)
            query = queries.get(query_id) or {}
            pool.append({
                'label': f'P-{len(pool) + 1:04d}',
                'queryId': query_id,
                'query': query.get('text'),
                'url': item.get('url'),
                'title': item.get('title'),
                'snippet': item.get('snippet'),
                'content': item.get('content') or item.get('snippet'),
            })
    return pool


def relevance_prompt(item: dict) -> str:
    """Prompt chấm liên quan 0–3; chỉ thấy truy vấn + tiêu đề + đoạn trích (nhãn mù)."""
    return DEFAULT_JUDGE_TEMPLATE.format(query=item.get('query') or '', title=item.get('title') or '',
                                         snippet=item.get('snippet') or '')


def parse_relevance(text: str) -> int:
    """Đọc một chữ số 0–3 từ câu trả lời giám khảo; lỗi ⇒ `ValueError`."""
    for char in str(text or ''):
        if char.isdigit() and 0 <= int(char) <= 3:
            return int(char)
    raise ValueError(f'giám khảo không trả mức 0–3: {text!r}')


def _pool_key(item: dict) -> str:
    """Khoá cache điểm giám khảo = băm của (văn bản truy vấn, URL chuẩn hoá) (M10).

    Nhãn vị trí (`P-0001…`) tái dùng giữa các lượt với cặp (truy vấn, URL) KHÁC nhau, nên khoá
    theo nhãn là dùng điểm của bài khác. Băm theo cặp (truy vấn, URL) là khoá đúng của một phiếu.
    """
    payload = f"{str(item.get('query') or '')}\u0000{reference_map_mod.canonical_url(str(item.get('url') or ''))}"
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def judge_pool(pool: list[dict], out_dir: Path, *, runner=None) -> dict[str, int]:
    """Chấm gộp (pooled) qua `judge.JudgeRunner`; phiếu đã có thì dùng lại, không gọi lại.

    Cache khoá theo `_pool_key` (truy vấn, URL), KHÔNG theo nhãn vị trí; trả `{label: grade}` để
    người gọi cũ không phải đổi.
    """
    out_dir = Path(out_dir)
    cache_path = out_dir / 'judged.jsonl'
    cache: dict[str, int] = {}
    grades: dict[str, int] = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            key = item.get('key')
            if key:
                cache[key] = int(item['grade'])
    for item in pool:
        key = _pool_key(item)
        if key in cache:
            grades[item['label']] = cache[key]
    missing = [item for item in pool if item['label'] not in grades]
    if not missing:
        return grades
    if runner is None:
        import judge  # noqa: PLC0415 - chỉ nạp khi thật sự cần gọi model
        runner = judge.JudgeRunner()
    out_dir.mkdir(parents=True, exist_ok=True)
    with cache_path.open('a', encoding='utf-8') as handle:
        for item in missing:
            key = _pool_key(item)
            grade = parse_relevance(runner.request(relevance_prompt(item)))
            cache[key] = grade
            grades[item['label']] = grade
            handle.write(json.dumps({'key': key, 'label': item['label'], 'url': item.get('url'),
                                     'grade': grade}, ensure_ascii=False) + '\n')
    return grades


def _load_reference_maps(out_dir: Path) -> dict[str, dict]:
    """Bản đồ tham chiếu nếu có (M9): `<out>/maps/*.json` hoặc `scripts/eval/reference_maps/*.json`.

    Bộ truy vấn đã commit hiện có 0/120 `mapItems`, nên hàm này thường trả `{}` và
    `mapRecallTop20` là `chưa đo` cho tới khi P6 dựng bản đồ tham chiếu.
    """
    maps: dict[str, dict] = {}
    for root in (Path(out_dir) / 'maps', EVAL_DIR / 'reference_maps'):
        if not root.is_dir():
            continue
        for path in sorted(root.glob('*.json')):
            try:
                data = reference_map_mod.load_map(path)
            except ValueError:
                continue
            maps[str(data.get('scenarioId') or path.stem)] = data
    return maps


def _load_fresh_windows(out_dir: Path) -> dict[str, dict]:
    """Cửa sổ thời gian cho truy vấn `needsFresh` nếu có (`<out>/fresh_windows.json`), ngược lại {}."""
    path = Path(out_dir) / 'fresh_windows.json'
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def run_bench(configs: list[str], *, split: str, out_dir: Path) -> dict:
    """Chạy 8.7 thật: xen kẽ truy vấn giữa cấu hình, lưu thô, chấm gộp, ghi manifest.

    Mỗi cấu hình chạy trên một DB đệm RIÊNG (`_bench_db_path`) và mỗi lượt `run_bench` có token
    riêng, nên không cấu hình nào đọc payload của cấu hình khác (H2).
    """
    verdict = guard.check(None)
    if not verdict['allowed']:
        raise guard_refusal(verdict)
    unknown = [name for name in configs if name not in CONFIG_SPECS]
    if unknown:
        raise ValueError('cấu hình lạ: ' + ', '.join(unknown))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Token lượt chạy: chạy lại sau khi sửa ống dùng DB mới, không đọc lại số cũ.
    os.environ[BENCH_RUN_ENV] = f"{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}-{os.getpid()}"
    queries = load_queries()
    selected = load_split(queries, split)
    query_index = {item['id']: item for item in selected}
    started_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    raw_rows: list[dict] = []
    raw_path = out_dir / 'raw.jsonl'
    with raw_path.open('w', encoding='utf-8') as handle:
        for query in selected:
            for config in configs:
                row = run_query(query, config)
                raw_rows.append(row)
                handle.write(json.dumps(row, ensure_ascii=False) + '\n')
    pool = build_pool(raw_rows, query_index)
    (out_dir / 'pool.jsonl').write_text(
        '\n'.join(json.dumps(item, ensure_ascii=False) for item in pool) + '\n', encoding='utf-8')
    grades = judge_pool(pool, out_dir)
    grades_by_query: dict[str, dict] = {}
    for item in pool:
        if item['label'] in grades:
            grades_by_query.setdefault(item['queryId'], {})[item['url']] = grades[item['label']]
    maps = _load_reference_maps(out_dir)
    fresh_windows = _load_fresh_windows(out_dir)
    metrics = {
        config: compute_metrics([row for row in raw_rows if row.get('config') == config],
                                query_index, grades_by_query, maps, fresh_windows=fresh_windows)
        for config in configs
    }
    ended_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    map_items = sum(len(item.get('mapItems') or []) for item in selected)
    bench = {
        'schemaVersion': 'search-bench-v1',
        'split': split,
        'configs': list(configs),
        'queryCount': len(selected),
        'window': {'startedAt': started_at, 'endedAt': ended_at},
        'metrics': metrics,
        'judgedPairs': len(grades),
        'poolPairs': len(pool),
        'maps': sorted(maps) or None,
        'freshWindows': sorted(fresh_windows) or None,
        'mapItemsInCorpus': map_items,
    }
    (out_dir / 'metrics.json').write_text(json.dumps(bench, ensure_ascii=False, indent=2) + '\n',
                                          encoding='utf-8')
    _write_manifest(out_dir, bench, len(selected))
    return bench


def guard_refusal(verdict: dict) -> 'SpendRefused':
    """Cổng chi tiền chưa mở ⇒ ngoại lệ mang lý do của `guard` (không tự bịa câu)."""
    reason = verdict.get('reason') or ''
    return SpendRefusedForBench('cổng chi tiền chưa mở: ' + reason)


class SpendRefusedForBench(RuntimeError):
    """8.7 gọi mạng thật: thiếu opt-in hoặc ngân sách là từ chối thẳng."""


def _write_manifest(out_dir: Path, bench: dict, query_count: int) -> None:
    import manifest as manifest_mod  # noqa: PLC0415 - tránh vòng import ở cấp mô-đun
    payload = {
        'benchmark': {'name': 'search-bench-8.7', 'version': 'v1'},
        'repo': manifest_mod.repo_state(REPO_DIR),
        'configs': bench['configs'],
        'split': bench['split'],
        'queryCount': query_count,
        'window': bench['window'],
        'judgedPairs': bench['judgedPairs'],
    }
    (out_dir / 'manifest.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')


def report(bench: dict) -> str:
    """Bảng chỉ số theo cấu hình (nDCG@10, recall top-20, tỉ lệ mới, lỗi, p50/p95)."""
    lines = [f"Đo 8.7 · tập {bench.get('split')} · "
             f"{bench.get('queryCount')} truy vấn · {bench.get('poolPairs')} cặp gộp "
             f"({bench.get('judgedPairs')} đã chấm)",
             f"Khung giờ: {bench.get('window', {}).get('startedAt')} → "
             f"{bench.get('window', {}).get('endedAt')}", '',
             '| Cấu hình | nDCG@10 | Recall top-20 | Tỉ lệ mới | Tỉ lệ lỗi | p50 (ms) | p95 (ms) |',
             '|---|---|---|---|---|---|---|']
    for config, metrics in (bench.get('metrics') or {}).items():
        lines.append(f"| {config} | {_show(metrics.get('ndcgAt10'))} | "
                     f"{_show(metrics.get('mapRecallTop20'))} | {_show(metrics.get('freshRate'))} | "
                     f"{_show(metrics.get('failureRate'))} | {_show(metrics.get('latencyP50Ms'))} | "
                     f"{_show(metrics.get('latencyP95Ms'))} |")
    lines.append('')
    lines.append('`chưa đo` = thiếu nhãn/bản đồ/cửa sổ — không ghi 0 để giả có số.')
    # Vòng soát 2 — hai bản bỏ có giới hạn CẤU TRÚC của thước này, nói trước để không đọc sai bảng:
    lines.append('')
    lines.append('Hai bản bỏ có giới hạn riêng của thước này (đọc kèm, đừng kết luận "bước vô dụng"):')
    lines.append('- `ablation-no-local-index`: DB của thước bắt đầu RỖNG và không nạp trang nào vào '
                 'chỉ mục, nên bước 9 vốn không có gì để trả — hai dòng trùng nhau là hệ quả của '
                 'thước, không phải của ống. Muốn đo thật phải nạp chỉ mục trước (P6).')
    lines.append('- `ablation-no-rrf`: chỉ lấy một chân (một engine) nên với truy vấn chung, các chân '
                 'trùng kết quả thì thứ hạng cuối trùng với ống đầy đủ; chỉ khác khi các chân thật sự '
                 'khác nhau.')
    # M9 — nói thẳng cổng §8.7 "map ≥ Brave proxy" chưa thể đo cho tới khi P6 dựng bản đồ tham chiếu.
    if not bench.get('maps'):
        lines.append('')
        lines.append('Cổng §8.7 "recall bản đồ ≥ Brave proxy" CHƯA THỂ ĐO: bộ truy vấn đã commit '
                     f"có {bench.get('mapItemsInCorpus', 0)} mục bản đồ tham chiếu "
                     f"({bench.get('queryCount')} truy vấn), nên `mapRecallTop20` là `chưa đo`. "
                     'Chờ P6 dựng bản đồ tham chiếu trước khi kết luận về cổng này.')
    return '\n'.join(lines)


def _show(value) -> str:
    return 'chưa đo' if value is None else str(value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Đo 8.7 (gọi mạng thật; cần cổng chi tiền).')
    parser.add_argument('--configs', nargs='*', default=list(DEFAULT_CONFIGS))
    parser.add_argument('--split', default='test', choices=list(SPLIT_VALUES))
    parser.add_argument('--out', required=True)
    parser.add_argument('--budget-usd', type=float, default=None)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    if args.budget_usd is not None:
        # `run_bench` giữ chữ ký đóng băng (configs, *, split, out_dir) nên nó chỉ đọc
        # ngân sách từ môi trường; cờ dòng lệnh ghi vào env trước khi gọi.
        os.environ[guard.BUDGET_ENV] = str(args.budget_usd)
    try:
        bench = run_bench(args.configs, split=args.split, out_dir=Path(args.out))
    except SpendRefusedForBench as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f'lỗi dữ liệu: {exc}', file=sys.stderr)
        return 2
    print(json.dumps(bench, ensure_ascii=False, indent=2) if args.json else report(bench))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
