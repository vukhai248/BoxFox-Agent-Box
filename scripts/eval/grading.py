#!/usr/bin/env python3
"""Gói chấm của chủ nhà, nhãn mù, bảng chấm và độ khớp giám khảo ↔ người (kế hoạch v2 §8.6).

Quy trình #6080:

1. bộ chạy chọn mẫu ngẫu nhiên 25% lần `quality-valid`, phân tầng theo tình huống
   và cấu hình, **cộng mọi lần judge/máy lệch > 1 điểm**;
2. mỗi lần chạy được gán nhãn mù `G-001`…; bảng nối nhãn ↔ (cấu hình, tình huống,
   lần) ghi ở `blind-key.json`, **không in** cho tới khi chủ nhà nộp;
3. mỗi nhãn có một thư mục `G-0NN/` gồm `report.md`, `scope.md`,
   `reference-map.md`, `sources.md`, `rubric.md` — đã bỏ dấu vết cấu hình;
4. chấm bằng `grading-sheet.csv` + bản Markdown, thang 0–4 có mốc cho mười tiêu chí;
5. sau khi nộp, `unblind()` mở khoá và tính độ khớp (tương quan hạng + tỉ lệ lệch ≤ 1).

Thuần stdlib, không mạng, không gọi model.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reference_map as reference_map_mod  # noqa: E402

#: Mười tiêu chí #6080, thang 0–4, neo ở 0/2/4 (1 và 3 là giữa). Nguồn: §8.5.
CRITERIA: tuple[dict, ...] = (
    {
        'code': 'c1_goal_fit', 'name': 'Khớp mục tiêu',
        'anchors': {
            0: 'Trả lời lệch hẳn câu hỏi hoặc thiếu mô-đun đã hứa.',
            2: 'Trả lời đúng câu hỏi chính, còn mô-đun/khía cạnh đã hứa bị thiếu.',
            4: 'Trả lời đúng câu hỏi và đủ mọi mô-đun đã hứa; không lệch phạm vi.',
        },
    },
    {
        'code': 'c2_coverage', 'name': 'Độ phủ',
        'anchors': {
            0: 'Thiếu phần lớn mục `must` của bản đồ tham chiếu.',
            2: 'Đủ `must`, thiếu nhiều `should`.',
            4: 'Đủ `must` và phần lớn `should`, có ghi rõ phần chưa khảo sát.',
        },
    },
    {
        'code': 'c3_read_depth', 'name': 'Độ sâu đọc',
        'anchors': {
            0: 'Toàn snippet/abstract được trình bày như đã đọc toàn văn.',
            2: 'Có đoạn toàn văn cho một phần nhận định chính, phần còn lại mỏng.',
            4: 'Mọi nhận định chính có đoạn `fulltext` kèm vị trí; thẻ trích xuất đủ trường.',
        },
    },
    {
        'code': 'c4_synthesis', 'name': 'Tổng hợp',
        'anchors': {
            0: 'Liệt kê nguồn rời rạc, không nói quan hệ.',
            2: 'Có gom nhóm nhưng quan hệ giữa nguồn còn mờ.',
            4: 'Chỉ rõ quan hệ đồng thuận/mâu thuẫn/bổ sung, không liệt kê rời.',
        },
    },
    {
        'code': 'c5_factual_timeliness', 'name': 'Đúng và đúng thời điểm',
        'anchors': {
            0: 'Sai dữ kiện, hoặc nhận định hiện trạng chỉ dựa nguồn cũ.',
            2: 'Phần lớn dữ kiện đúng; một chỗ dùng nguồn cũ cho nhận định hiện trạng.',
            4: 'Dữ kiện đúng và đúng cửa sổ thời gian; lỗi `stale-current-claim` = 0.',
        },
    },
    {
        'code': 'c6_uncertainty', 'name': 'Xử lý bất định',
        'anchors': {
            0: 'Gắn "chắc chắn"/"cao" cho nhận định chỉ có abstract hoặc nguồn yếu.',
            2: 'Có nhãn độ tin cậy nhưng lệch trần máy ở vài chỗ.',
            4: 'Nhãn độ tin cậy khớp trần máy; "Giới hạn" nói rõ phần chưa đọc được.',
        },
    },
    {
        'code': 'c7_interview_scope', 'name': 'Chất lượng phỏng vấn, bám phạm vi',
        'anchors': {
            0: 'Hỏi thừa câu chặn, hoặc tự đổi phạm vi không nói.',
            2: 'Hỏi vừa phải nhưng có câu không đổi hướng; thẻ phạm vi thiếu mục.',
            4: 'Số câu chặn khớp nhãn tình huống; thẻ phạm vi có mọi trường; sửa thẻ được tôn trọng.',
        },
    },
    {
        'code': 'c8_review_effectiveness', 'name': 'Hiệu quả soát',
        'anchors': {
            0: 'Bỏ qua lỗi cấy sẵn, hoặc báo sai trên hồ sơ sạch.',
            2: 'Bắt được một phần lỗi cấy sẵn, có báo sai lẻ tẻ.',
            4: 'Bắt đúng lỗi dữ kiện/gán sai/gỡ hướng; tỉ lệ báo sai ≤ 20%.',
        },
    },
    {
        'code': 'c9_mode_boundary', 'name': 'Vào/ra mode và ranh giới main',
        'anchors': {
            0: 'Main tự mở mức 3 khi mode tắt, hoặc pause/cancel dừng cả phiên.',
            2: 'Ranh giới đúng nhưng một nhánh pause/resume lệch pha.',
            4: 'Vào/ra mode, mức 1–2 ngoài mode, pause/cancel theo job — tất cả đúng.',
        },
    },
    {
        'code': 'c10_cost_latency', 'name': 'Chi phí, độ trễ',
        'anchors': {
            0: 'Vượt xa trần thời gian/token của mức.',
            2: 'Sát trần, có ít bước tua lại vô ích.',
            4: 'Trong trần, token/thời gian hợp lý cho việc; để trống nếu chủ nhà không chấm.',
        },
    },
)
CRITERION_CODES: tuple[str, ...] = tuple(item['code'] for item in CRITERIA)
CRITERION_BY_CODE = {item['code']: item for item in CRITERIA}
SCALE_MAX = 4
#: Cột chủ nhà được phép bỏ trống (để trống ô, không ghi 0).
OPTIONAL_COLUMNS = ('c10_cost_latency',)
SHEET_COLUMNS = ('label', 'scenario_id', *CRITERION_CODES, 'evidence_note', 'flag', 'minutes_spent')
FLAG_VALUES = ('none', 'factual-error', 'misattribution', 'scope-drift', 'other')
#: Dấu vết phải bỏ khỏi hồ sơ đưa chủ nhà (§8.6 "bỏ dấu vết cấu hình").
TRACE_KEYS = ('model', 'configId', 'config', 'commit', 'flags', 'researchId', 'sessionId', 'route')
AGREEMENT_TOLERANCE = 1


def blind_label(index: int) -> str:
    """`G-001`, `G-002`, … — nhãn mù duy nhất cho một lần chạy."""
    return f'G-{int(index):03d}'


def anchors_block() -> str:
    """Thang có mốc của cả mười tiêu chí, dạng Markdown."""
    lines = ['| Tiêu chí | 0 | 2 | 4 |', '|---|---|---|---|']
    for item in CRITERIA:
        lines.append(f"| {item['code']} — {item['name']} | {item['anchors'][0]} | "
                     f"{item['anchors'][2]} | {item['anchors'][4]} |")
    lines.append('')
    lines.append('1 và 3 là mức giữa. Ô `c10_cost_latency` được phép để trống nếu bạn '
                 'không chấm chi phí.')
    return '\n'.join(lines)


def rubric_markdown() -> str:
    return ('# Thang chấm (0–4, neo ở 0/2/4)\n\n' + anchors_block() + '\n')


def _strip_traces(text: str, run: dict) -> str:
    """Bỏ tên model/commit/cờ/researchId khỏi văn bản đưa chủ nhà."""
    stripped = str(text or '')
    for key in TRACE_KEYS:
        value = run.get(key)
        if isinstance(value, str) and value.strip():
            stripped = stripped.replace(value, '[đã ẩn]')
    return stripped


def build_pack(run: dict, *, label: str, out_dir: Path, reference_map: dict | None) -> Path:
    """Dựng thư mục chấm mù cho MỘT lần chạy; trả đường dẫn thư mục nhãn.

    Không in `blind-key.json`; không ghi cấu hình vào hồ sơ.
    """
    label_dir = Path(out_dir) / 'grading' / str(label)
    label_dir.mkdir(parents=True, exist_ok=True)
    (label_dir / 'report.md').write_text(
        _strip_traces(run.get('report') or '(chưa có báo cáo cho lần chạy này)', run),
        encoding='utf-8')
    (label_dir / 'scope.md').write_text(
        _strip_traces(run.get('scope') or '(chưa có thẻ phạm vi)', run), encoding='utf-8')
    (label_dir / 'sources.md').write_text(
        _strip_traces(run.get('sources') or '(chưa có danh sách nguồn)', run), encoding='utf-8')
    map_text = (reference_map_mod.render(reference_map) if reference_map
                else '(chưa có bản đồ tham chiếu cho tình huống này)')
    (label_dir / 'reference-map.md').write_text(map_text + '\n', encoding='utf-8')
    (label_dir / 'rubric.md').write_text(rubric_markdown(), encoding='utf-8')
    return label_dir


def write_blind_key(entries: list[dict], out_dir: Path) -> Path:
    """Ghi bảng nối nhãn ↔ (cấu hình, tình huống, lần) + điểm judge. KHÔNG in."""
    path = Path(out_dir) / 'blind-key.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({'entries': entries}, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8')
    return path


def grading_sheet(labels: list[dict], out_dir: Path) -> Path:
    """Ghi `grading-sheet.csv` + bản Markdown tương ứng; trả đường dẫn CSV.

    `labels` là danh sách `{'label', 'scenarioId'}` (chủ nhà điền tay), hoặc đã có
    sẵn khoá điểm/ghi chú của lần chấm trước.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / 'grading-sheet.csv'
    with csv_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SHEET_COLUMNS))
        writer.writeheader()
        for item in labels:
            row = {column: '' for column in SHEET_COLUMNS}
            row['label'] = item.get('label', '')
            row['scenario_id'] = item.get('scenarioId', item.get('scenario_id', ''))
            scores = item.get('scores') or {}
            for code in CRITERION_CODES:
                row[code] = '' if scores.get(code) is None else scores.get(code)
            row['evidence_note'] = item.get('evidenceNote', item.get('evidence_note', ''))
            row['flag'] = item.get('flag', '') or 'none'
            row['minutes_spent'] = item.get('minutesSpent', item.get('minutes_spent', ''))
            writer.writerow(row)
    md_lines = ['# Bảng chấm của chủ nhà (nhãn mù)', '',
                'Thang 0–4 có mốc; điền vào `grading-sheet.csv` cùng thư mục.', '',
                '| ' + ' | '.join(SHEET_COLUMNS) + ' |',
                '|' + '---|' * len(SHEET_COLUMNS)]
    for item in labels:
        scores = item.get('scores') or {}
        cells = [str(item.get('label', '')), str(item.get('scenarioId', item.get('scenario_id', '')))]
        cells += ['' if scores.get(code) is None else str(scores.get(code)) for code in CRITERION_CODES]
        cells += [str(item.get('evidenceNote', item.get('evidence_note', ''))),
                  str(item.get('flag', '') or 'none'),
                  str(item.get('minutesSpent', item.get('minutes_spent', '')))]
        md_lines.append('| ' + ' | '.join(cells) + ' |')
    md_lines += ['', '## Thang có mốc', '', anchors_block(), '']
    (out_dir / 'grading-sheet.md').write_text('\n'.join(md_lines), encoding='utf-8')
    return csv_path


def _ranks(values: list[float]) -> list[float]:
    """Hạng trung bình cho giá trị trùng (Spearman chịu được hoà)."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(order):
        end = position
        while end + 1 < len(order) and values[order[end + 1]] == values[order[position]]:
            end += 1
        average = (position + end) / 2.0 + 1.0
        for index in order[position:end + 1]:
            ranks[index] = average
        position = end + 1
    return ranks


def spearman(pairs: list[tuple[float, float]]) -> float | None:
    """Tương quan hạng Spearman; `None` khi < 2 cặp hoặc một vế không đổi."""
    pairs = [(float(x), float(y)) for x, y in pairs]
    if len(pairs) < 2:
        return None
    xs = _ranks([x for x, _ in pairs])
    ys = _ranks([y for _, y in pairs])
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return round(cov / (var_x * var_y) ** 0.5, 4)


def within_one(pairs: list[tuple[float, float]]) -> float | None:
    """Tỉ lệ cặp lệch ≤ 1 điểm; `None` khi chưa có cặp nào."""
    pairs = list(pairs)
    if not pairs:
        return None
    within = sum(1 for x, y in pairs if abs(float(x) - float(y)) <= AGREEMENT_TOLERANCE)
    return round(within / len(pairs), 4)


def _total(scores: dict | None) -> int | None:
    """Tổng điểm của các tiêu chí BẮT BUỘC; `None` khi thiếu một tiêu chí bắt buộc nào.

    `c10_cost_latency` là TUỲ CHỌN (§8.6, `OPTIONAL_COLUMNS`): bảng để trống ô này vẫn phải ra
    tổng điểm, nếu không độ khớp giám khảo ↔ người luôn co về `n=0` (M11).
    """
    if not isinstance(scores, dict):
        return None
    required = [code for code in CRITERION_CODES if code not in OPTIONAL_COLUMNS]
    values = [scores.get(code) for code in required]
    if any(value is None for value in values):
        return None
    return sum(int(value) for value in values)


def read_sheet(path: str | Path) -> dict[str, dict]:
    """Đọc `grading-sheet.csv`; trả `{label: {criterion: int|None, ...}}`."""
    rows: dict[str, dict] = {}
    with Path(path).open('r', encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            label = str(row.get('label') or '').strip()
            if not label:
                continue
            scores: dict[str, int | None] = {}
            for code in CRITERION_CODES:
                raw = str(row.get(code) or '').strip()
                if raw == '':
                    scores[code] = None
                elif raw.isdigit() and 0 <= int(raw) <= SCALE_MAX:
                    scores[code] = int(raw)
                else:
                    raise ValueError(f'{label}: điểm {code} ngoài thang 0–{SCALE_MAX}: {raw!r}')
            rows[label] = {'scores': scores, 'flag': row.get('flag') or 'none',
                           'evidenceNote': row.get('evidence_note') or '',
                           'minutesSpent': row.get('minutes_spent') or ''}
    return rows


def unblind(out_dir: Path) -> dict:
    """Mở `blind-key.json` sau khi chủ nhà nộp và tính độ khớp judge ↔ người.

    Trả tương quan hạng + tỉ lệ lệch ≤ 1 theo **tổng điểm** và theo **từng tiêu chí**,
    cộng danh sách đã giải mù. Tiêu chí nào khớp kém thì điểm judge của tiêu chí đó
    chỉ được báo, không dùng làm cổng nghiệm thu (điều đó do bên gọi quyết).
    """
    out_dir = Path(out_dir)
    key_path = out_dir / 'blind-key.json'
    key = json.loads(key_path.read_text(encoding='utf-8'))
    entries = key.get('entries') or []
    sheet_path = out_dir / 'grading-sheet.csv'
    owner = read_sheet(sheet_path) if sheet_path.exists() else {}
    by_criterion: dict[str, dict] = {}
    resolved: list[dict] = []
    total_pairs: list[tuple[float, float]] = []
    for entry in entries:
        label = str(entry.get('label') or '')
        judge = entry.get('judgeScores') or entry.get('judge') or {}
        owner_row = owner.get(label)
        resolved.append({'label': label, 'scenarioId': entry.get('scenarioId'),
                         'configId': entry.get('configId'), 'run': entry.get('run'),
                         'graded': owner_row is not None})
        if owner_row is None:
            continue
        for code in CRITERION_CODES:
            judge_score = judge.get(code)
            owner_score = owner_row['scores'].get(code)
            if judge_score is None or owner_score is None:
                continue
            by_criterion.setdefault(code, []).append((float(judge_score), float(owner_score)))
        judge_total = _total(judge) if isinstance(judge, dict) and judge else None
        owner_total = _total(owner_row['scores'])
        if judge_total is not None and owner_total is not None:
            total_pairs.append((float(judge_total), float(owner_total)))
    criterion_stats = {
        code: {'n': len(pairs), 'rankCorrelation': spearman(pairs), 'withinOne': within_one(pairs)}
        for code, pairs in by_criterion.items()
    }
    return {
        'labels': len(entries),
        'graded': sum(1 for item in resolved if item['graded']),
        'overall': {'n': len(total_pairs), 'rankCorrelation': spearman(total_pairs),
                    'withinOne': within_one(total_pairs)},
        'byCriterion': criterion_stats,
        'resolved': resolved,
    }


def select_sample(runs: list[dict], *, fraction: float = 0.25, seed: int = 0,
                  strata: tuple[str, ...] = ('scenarioId', 'configId')) -> list[str]:
    """Chọn mẫu phân tầng 25% + MỌI lần judge/máy lệch > 1 (deterministic theo `seed`).

    `runs` mỗi phần tử cần `label`; tuỳ chọn `scenarioId`, `configId` và cờ
    `needsOwner` (đã lệch). Trả danh sách nhãn đã sắp xếp.
    """
    rng = random.Random(seed)
    buckets: dict[tuple, list[str]] = {}
    forced: list[str] = []
    for run in runs:
        label = str(run.get('label') or '')
        if not label:
            continue
        if run.get('needsOwner'):
            forced.append(label)
            continue
        key = tuple(str(run.get(name) or '') for name in strata)
        buckets.setdefault(key, []).append(label)
    chosen: list[str] = []
    for key in sorted(buckets):
        labels = sorted(buckets[key])
        take = max(1, int(round(len(labels) * fraction))) if labels else 0
        chosen.extend(rng.sample(labels, min(take, len(labels))))
    return sorted(set(chosen) | set(forced))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Gói chấm mù + độ khớp (offline, §8.6).')
    sub = parser.add_subparsers(dest='command', required=True)
    sheet = sub.add_parser('sheet', help='dựng bảng chấm trống từ danh sách nhãn')
    sheet.add_argument('--labels', required=True, help='JSON [{label, scenarioId}, …]')
    sheet.add_argument('--out', required=True)
    submit = sub.add_parser('unblind', help='mở khoá sau khi chủ nhà nộp')
    submit.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    if args.command == 'sheet':
        labels = json.loads(Path(args.labels).read_text(encoding='utf-8'))
        path = grading_sheet(labels, Path(args.out))
        print(f'đã ghi {path}')
        return 0
    result = unblind(Path(args.out))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
