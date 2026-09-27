#!/usr/bin/env python3
"""Bản đồ tham chiếu của một tình huống (kế hoạch v2 §8.3) + recall có trọng số.

Bản đồ được dựng **trước** khi chạy, bằng hai lượt độc lập rồi gộp, và ghim vào
manifest (ngày + băm). Mỗi mục là một hướng lớn / công trình nền tảng / công trình
gần đây / mâu thuẫn đã biết / dữ kiện có ngày:

```json
{
  "scenarioId": "technology-choice",
  "builtAt": "2026-09-25T00:00:00Z",
  "items": [
    {"id": "foundational-attention", "label": "Attention Is All You Need",
     "weight": "must", "urls": ["https://arxiv.org/abs/1706.03762"]}
  ]
}
```

`weight` ∈ `must|should|nice`. **Độ phủ = recall có trọng số của mục** (§8.3) —
không đếm số nguồn, số subagent, độ dài. Mô-đun này thuần stdlib, không mạng,
không gọi model.

Mã thoát CLI: ``0`` xong, ``2`` sai cách dùng (không thấy tệp / JSON hỏng).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: Thứ tự + trọng số của ba mức. Số là quy ước của mô-đun này; tỉ lệ cần/đạt
#: không đổi nếu mọi mức nhân cùng hệ số, nên chọn số nhỏ cho dễ đọc.
WEIGHT_VALUES = ('must', 'should', 'nice')
WEIGHT_SCORES = {'must': 3.0, 'should': 2.0, 'nice': 1.0}

TRACKING_PARAMS = ('utm_', 'fbclid', 'gclid', 'ref', 'spm')
_ARXIV_RE = re.compile(r'^arxiv:(?P<id>.+)$', re.IGNORECASE)
_DOI_RE = re.compile(r'^(?:doi:|https?://(?:dx\.)?doi\.org/)(?P<doi>.+)$', re.IGNORECASE)


def canonical_url(url: str) -> str:
    """Chuẩn hoá URL để so khớp bản đồ ↔ kết quả tìm.

    Cùng tinh thần `search_pipeline.canonical_url` (hợp đồng §2) nhưng tự chứa:
    bỏ `utm_*`/`fbclid`/`gclid`/`ref`/`spm`, bỏ `#`, bỏ `/` cuối, hạ host, gộp
    `arxiv abs|pdf/<id>vN` thành `arxiv:<id>` và `doi.org/<doi>` thành `doi:<doi>`.
    """
    value = str(url or '').strip()
    if not value:
        return ''
    lowered = value.lower()
    arxiv = _ARXIV_RE.match(lowered)
    if arxiv:
        return 'arxiv:' + _arxiv_id(arxiv.group('id'))
    doi = _DOI_RE.match(lowered)
    if doi:
        return 'doi:' + doi.group('doi').strip().strip('/').lower()
    if lowered.startswith('arxiv:'):
        return 'arxiv:' + _arxiv_id(lowered[len('arxiv:'):])
    # Bỏ fragment, tách query.
    base, _, fragment = lowered.partition('#')
    # arXiv dạng URL trần.
    base = re.sub(r'^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/', 'arxiv:', base)
    base = base.rstrip('/')
    if base.startswith('arxiv:'):
        return 'arxiv:' + _arxiv_id(base[len('arxiv:'):])
    base = re.sub(r'^https?://(?:dx\.)?doi\.org/', 'doi:', base)
    if base.startswith('doi:'):
        return 'doi:' + base[len('doi:'):].strip('/')
    base, _, query = base.partition('?')
    kept = []
    for part in query.split('&'):
        if not part:
            continue
        name = part.split('=', 1)[0]
        if any(name == param or name.startswith(param) for param in TRACKING_PARAMS):
            continue
        kept.append(part)
    canonical = base.rstrip('/')
    if kept:
        canonical += '?' + '&'.join(kept)
    return canonical


def _arxiv_id(raw: str) -> str:
    """`1706.03762v5` / `1706.03762.pdf` / `1706.03762` → `1706.03762`."""
    value = str(raw or '').strip().lower()
    value = re.sub(r'\.pdf$', '', value).rstrip('/')
    value = re.sub(r'v\d+$', '', value)
    return value


def issues_for(data: dict) -> list[str]:
    """Mọi lỗi của một bản đồ, thành danh sách câu hành động được."""
    issues: list[str] = []
    if not str(data.get('scenarioId') or '').strip():
        issues.append('thiếu scenarioId')
    if not str(data.get('builtAt') or '').strip():
        issues.append('thiếu builtAt (bản đồ phải có ngày)')
    items = data.get('items')
    if not isinstance(items, list) or not items:
        issues.append('items phải là danh sách không rỗng')
        return issues
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            issues.append(f'items[{index}] phải là đối tượng JSON')
            continue
        item_id = str(item.get('id') or '').strip()
        if not item_id:
            issues.append(f'items[{index}] thiếu id')
        elif item_id in seen:
            issues.append(f'items[{index}] trùng id {item_id!r}')
        else:
            seen.add(item_id)
        if not str(item.get('label') or '').strip():
            issues.append(f'items[{index}] thiếu label')
        if item.get('weight') not in WEIGHT_VALUES:
            issues.append(f'items[{index}].weight phải là một trong {WEIGHT_VALUES}')
        urls = item.get('urls')
        if not isinstance(urls, list) or not [u for u in urls if str(u).strip()]:
            issues.append(f'items[{index}].urls phải là danh sách URL không rỗng')
    return issues


def load_map(path: str | Path) -> dict:
    """Đọc + kiểm một bản đồ tham chiếu; lỗi ⇒ `ValueError` kèm lý do."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        raise ValueError(f'không thấy bản đồ tham chiếu: {path}') from None
    except ValueError as exc:
        raise ValueError(f'{path}: JSON hỏng ({exc})') from None
    if not isinstance(data, dict):
        raise ValueError(f'{path}: bản đồ phải là một đối tượng JSON')
    issues = issues_for(data)
    if issues:
        raise ValueError(f'{path.name}: ' + '; '.join(issues))
    return data


def weighted_recall(reference_map: dict, urls: list[str]) -> dict:
    """Recall có trọng số của bản đồ khi đã có danh sách URL.

    Một mục coi như trúng nếu **bất kỳ** URL của nó khớp chuẩn hoá với một URL
    trong `urls` (hoặc với chuỗi `arxiv:`/`doi:` đã chuẩn hoá). Trả:

    * `recall` — tổng trọng số mục trúng ÷ tổng trọng số toàn bản đồ;
    * `mustRecall` — tỉ lệ mục `must` trúng (`None` nếu bản đồ không có mục `must`);
    * `missing` — id những mục chưa trúng;
    * `missingMust` — id những mục `must` chưa trúng.
    """
    items = (reference_map or {}).get('items') or []
    have = {canonical_url(item) for item in urls if canonical_url(item)}
    total = 0.0
    matched = 0.0
    must_total = 0
    must_matched = 0
    missing: list[str] = []
    missing_must: list[str] = []
    for item in items:
        weight = WEIGHT_SCORES.get(str(item.get('weight')), 0.0)
        total += weight
        if str(item.get('weight')) == 'must':
            must_total += 1
        hit = any(canonical_url(url) in have for url in (item.get('urls') or []))
        if hit:
            matched += weight
            if str(item.get('weight')) == 'must':
                must_matched += 1
        else:
            missing.append(str(item.get('id')))
            if str(item.get('weight')) == 'must':
                missing_must.append(str(item.get('id')))
    return {
        'recall': round(matched / total, 4) if total else None,
        'mustRecall': round(must_matched / must_total, 4) if must_total else None,
        'total': len(items),
        'matched': len(items) - len(missing),
        'missing': missing,
        'missingMust': missing_must,
    }


def render(reference_map: dict) -> str:
    """Bản người đọc của bản đồ (đưa cho chủ nhà chấm — §8.6)."""
    lines = [f"Bản đồ tham chiếu · {reference_map.get('scenarioId')} "
             f"(dựng {reference_map.get('builtAt')})"]
    for item in reference_map.get('items') or []:
        lines.append(f"  [{item.get('weight'):6s}] {item.get('id')} — {item.get('label')}")
        for url in item.get('urls') or []:
            lines.append(f"           {url}")
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Kiểm/báo cáo một bản đồ tham chiếu (offline).')
    parser.add_argument('map', help='tệp bản đồ JSON')
    parser.add_argument('--urls', nargs='*', default=None, help='đo recall với danh sách URL này')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        reference_map = load_map(args.map)
    except ValueError as exc:
        print(f'lỗi bản đồ: {exc}', file=sys.stderr)
        return 2
    if args.urls is not None:
        result = weighted_recall(reference_map, args.urls)
        print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else render(reference_map))
        return 0
    print(json.dumps(reference_map, ensure_ascii=False, indent=2) if args.json else render(reference_map))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
