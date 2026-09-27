"""Judging layers (§5 of the quality plan) as data files + a guarded runner.

§5 defines three layers:

1. machine oracle — no model at all, computes §3/C1/C5/C6 (`rushed_index.py` +
   the per-fixture checks);
2. LLM judge — scores C2/C3/C4/C7/C8 from a **frozen, versioned** prompt, sees
   neither the oracle nor the config label, two passes per output;
3. human sample — the owner scores 3–5 cases by hand to calibrate layer 2.

This module owns the layer-2 and layer-3 prompts (they live in `prompts/`, not
inline) and the plumbing that calls the router. The call is real as of P0a:
`JudgeRunner.request()` POSTs `{ROUTER}/v1/chat/completions` (no stream, 120 s
timeout, two retries on 5xx) — and it refuses to send anything unless
`guard.check()` passes first, so no accidental spend is possible.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixtureset  # noqa: E402
import guard  # noqa: E402
import net  # noqa: E402
import rubric  # noqa: E402

PROMPT_DIR = Path(__file__).resolve().parent / 'prompts'
LAYER2_TEMPLATE = 'judge-layer2.md'
LAYER3_TEMPLATE = 'judge-layer3-human.md'
LAYERS = (1, 2, 3)

#: §1 của hợp đồng P0: tên biến đã đóng băng.
ROUTER_ENV = 'BOXFOX_ROUTER_BASE_URL'
ROUTER_KEY_ENV = 'BOXFOX_ROUTER_KEY'
JUDGE_MODEL_ENV = 'BOXFOX_EVAL_JUDGE_MODEL'
DEFAULT_ROUTER = 'http://127.0.0.1:3101'
DEFAULT_JUDGE_MODEL = 'muse-spark-1.3-contributor-free'
#: §7: hạn chờ 120 s cho mỗi lời chấm.
JUDGE_TIMEOUT = 120.0
#: §7: thử lại **hai lần** khi máy chủ trả 5xx (tổng tối đa 3 lời gọi).
RETRY_ON_5XX = 2

VERSION_RE = re.compile(r'<!--\s*version:\s*([A-Za-z0-9._-]+)\s*-->')
MIN_ORACLE_LEAK_CHARS = 30  # ngắn hơn thì dễ trùng ngẫu nhiên, không tính là rò oracle


def load_template(name: str) -> dict:
    """Read one template and take its version marker from the file itself."""
    path = PROMPT_DIR / name
    text = path.read_text(encoding='utf-8')
    match = VERSION_RE.search('\n'.join(text.splitlines()[:5]))
    if not match:
        raise ValueError(f'{name}: thiếu dòng `<!-- version: … -->` — prompt phải có phiên bản')
    return {
        'name': name,
        'path': str(path),
        'version': match.group(1),
        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'body': text,
    }


def prompt_info(name: str = LAYER2_TEMPLATE) -> dict:
    """The block the manifest pins for a run."""
    template = load_template(name)
    return {'path': template['path'], 'name': template['name'],
            'version': template['version'], 'sha256': template['sha256']}


def scale_line() -> str:
    return '; '.join(f'{level} = {label}' for level, label in sorted(rubric.SCALE.items()))


def anchors_block(dimensions=rubric.LAYER2_DIMENSIONS) -> str:
    lines = []
    for code in dimensions:
        item = rubric.DIMENSION_BY_CODE[code]
        lines.append(f'- {code} — {item["name"]}: {item["level2"]}')
    return '\n'.join(lines)


def output_contract(dimensions=rubric.LAYER2_DIMENSIONS) -> str:
    scores = ', '.join(f'"{code}": 0 hoặc 1 hoặc 2' for code in dimensions)
    why = ', '.join(f'"{code}": "một câu lý do"' for code in dimensions)
    return ('```json\n'
            '{\n'
            f'  "scores": {{{scores}}},\n'
            f'  "why": {{{why}}},\n'
            '  "note": "một câu về chỗ đáng ngờ nhất của đầu ra"\n'
            '}\n'
            '```')


def blind_label(answer: str) -> str:
    """Neutral id for the judge: no fixture id, no config, no run index."""
    return 'case-' + hashlib.sha256(answer.encode('utf-8')).hexdigest()[:10]


def rubric_table(dimensions=rubric.DIMENSION_CODES) -> str:
    lines = ['| Chiều | Đạt mức 2 khi |', '|---|---|']
    for code in dimensions:
        item = rubric.DIMENSION_BY_CODE[code]
        lines.append(f'| {code} — {item["name"]} | {item["level2"]} |')
    return '\n'.join(lines)


def assert_no_oracle_leak(rendered: str, fixture: dict) -> None:
    """§5: the judge must never see the oracle or the 'bad answer' wording."""
    for key in ('oracle_pass', 'bad_answer', 'case', 'bad_answer_source'):
        for item in fixture.get(key) or ([fixture[key]] if isinstance(fixture.get(key), str) else []):
            chunk = str(item).strip()
            if len(chunk) >= MIN_ORACLE_LEAK_CHARS and chunk in rendered:
                raise AssertionError(f'prompt giám khảo bị rò {key!r}: {chunk[:60]}…')


def render_layer2(fixture: dict, answer: str, label: str | None = None) -> str:
    """The exact text sent to the layer-2 judge for one output."""
    template = load_template(LAYER2_TEMPLATE)
    rendered = (template['body']
                .replace('{{request}}', str(fixture['request']).strip())
                .replace('{{label}}', label or blind_label(answer))
                .replace('{{answer}}', answer if answer.strip() else '(đầu ra rỗng)')
                .replace('{{scale}}', scale_line())
                .replace('{{dimensions}}', ', '.join(rubric.LAYER2_DIMENSIONS))
                .replace('{{anchors}}', anchors_block())
                .replace('{{output_contract}}', output_contract()))
    assert_no_oracle_leak(rendered, fixture)
    return rendered


def render_layer3() -> str:
    """The hand-scoring form (not sent to any model)."""
    template = load_template(LAYER3_TEMPLATE)
    return (template['body']
            .replace('{{scale}}', scale_line())
            .replace('{{rubric_table}}', rubric_table()))


def render(layer: int, fixture: dict, answer: str = '', label: str | None = None) -> str:
    if layer == 2:
        return render_layer2(fixture, answer, label)
    if layer == 3:
        return render_layer3()
    raise ValueError('lớp 1 không có prompt: đó là oracle máy, xem rushed_index.py')


def parse_scores(payload: str) -> dict[str, int]:
    """Read a judge answer back; raise when it is not the contracted JSON."""
    try:
        data = json.loads(payload)
    except ValueError as exc:
        raise ValueError(f'giám khảo trả về không phải JSON: {exc}') from exc
    scores = data.get('scores') if isinstance(data, dict) else None
    if not isinstance(scores, dict):
        raise ValueError('JSON của giám khảo thiếu khoá "scores"')
    missing = [code for code in rubric.LAYER2_DIMENSIONS if code not in scores]
    if missing:
        raise ValueError('giám khảo bỏ chiều: ' + ', '.join(missing))
    return {code: rubric.clamp_level(scores[code]) for code in rubric.LAYER2_DIMENSIONS}


def merge_layers(layer1: dict[str, int], layer2: dict[str, int]) -> dict[str, int]:
    """Ghép ĐIỂM của hai lớp thành một bộ C1-C8 đầy đủ."""
    wrong_layer = [code for code in layer1 if code not in rubric.LAYER1_DIMENSIONS]
    if wrong_layer:
        raise ValueError('lớp 1 không được chấm: ' + ', '.join(wrong_layer))
    stray = [code for code in layer2 if code in rubric.LAYER1_DIMENSIONS]
    if stray:
        raise ValueError('lớp 2 chấm chiều của lớp 1: ' + ', '.join(stray))
    merged = {**layer1, **layer2}
    return rubric.normalize_scores(merged)


class JudgeRunner:
    """Plumbing for the layer-2 call. Real HTTP, but only through the spend gate."""

    def __init__(self, base_url: str | None = None, model: str | None = None,
                 temperature: float = 0.0, budget_usd: float | None = None):
        self.base_url = (base_url or os.environ.get(ROUTER_ENV) or DEFAULT_ROUTER).rstrip('/')
        self.model = model or os.environ.get(JUDGE_MODEL_ENV) or DEFAULT_JUDGE_MODEL
        self.temperature = temperature
        self.budget_usd = budget_usd

    def request(self, prompt: str) -> str:
        """Gửi MỘT prompt tới router và trả nguyên văn nội dung giám khảo trả về.

        Từ chối trước khi mở socket nếu `guard.check()` chưa cho phép (§7: cổng
        trước mọi lời gọi). 5xx ⇒ thử lại tối đa `RETRY_ON_5XX` lần; lỗi transport
        hoặc 4xx ⇒ ném thẳng.
        """
        verdict = guard.check(self.budget_usd)
        if not verdict['allowed']:
            raise SpendRefused('cổng chi tiền chưa mở: ' + (verdict['reason'] or 'không rõ'))
        headers = {'Content-Type': 'application/json'}
        api_key = str(os.environ.get(ROUTER_KEY_ENV) or '').strip()
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'
        payload = {
            'model': self.model,
            'messages': [{'role': 'user', 'content': prompt}],
            'temperature': self.temperature,
            'stream': False,
        }
        last_error: net.HttpStatusError | None = None
        for attempt in range(RETRY_ON_5XX + 1):
            try:
                data = net.request_json(f'{self.base_url}/v1/chat/completions', method='POST',
                                        payload=payload, headers=headers, timeout=JUDGE_TIMEOUT)
            except net.HttpStatusError as exc:
                if 500 <= exc.status < 600 and attempt < RETRY_ON_5XX:
                    last_error = exc
                    continue
                raise
            return _content_of(data)
        raise last_error or net.NetError('giám khảo: không có câu trả lời nào')

    def score(self, prompt: str) -> dict[str, int]:
        return parse_scores(self.request(prompt))


class SpendRefused(RuntimeError):
    """Cổng chi tiền chưa mở: thiếu opt-in hoặc thiếu ngân sách."""


def _content_of(data: dict) -> str:
    """Bóc phần nội dung từ câu trả lời `/v1/chat/completions` (hợp kiểu OpenAI)."""
    choices = data.get('choices') if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        raise ValueError(f'router không trả "choices": {str(data)[:200]}')
    message = choices[0].get('message') if isinstance(choices[0], dict) else None
    if isinstance(message, dict) and message.get('content') is not None:
        return str(message['content'])
    if isinstance(choices[0], dict) and choices[0].get('text') is not None:
        return str(choices[0]['text'])
    raise ValueError(f'router không trả nội dung trong "choices[0]": {str(choices[0])[:200]}')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Các lớp chấm của kế hoạch chất lượng §5. Mặc định chỉ in prompt (dry-run).')
    parser.add_argument('--layer', type=int, default=2, choices=list(LAYERS))
    parser.add_argument('--fixture', default='Q1')
    parser.add_argument('--answer-file', default=None,
                        help='tệp chứa đầu ra cần chấm; không có thì in prompt với chỗ trống')
    parser.add_argument('--label', default=None, help='mã định danh mù (mặc định: băm của đầu ra)')
    parser.add_argument('--out', default=None, help='ghi prompt ra tệp thay vì stdout')
    parser.add_argument('--dry-run', action='store_true',
                        help='in prompt rồi dừng (đây là hành vi mặc định; cờ này cho rõ ý)')
    parser.add_argument('--budget-usd', type=float, default=None)
    parser.add_argument('--execute', action='store_true',
                        help='CHỈ đường này mới gọi model; cần opt-in + ngân sách')
    parser.add_argument('--info', action='store_true', help='in version/sha256 của prompt')
    parser.add_argument('--base-url', default=None, help='router sẽ gọi nếu có đường chạy thật')
    parser.add_argument('--model', default=None, help='model giám khảo sẽ chọn nếu chạy thật')
    args = parser.parse_args(argv)

    if args.info:
        print(json.dumps({'layer2': prompt_info(LAYER2_TEMPLATE),
                          'layer3': prompt_info(LAYER3_TEMPLATE),
                          'layer2Dimensions': list(rubric.LAYER2_DIMENSIONS),
                          'layer1Dimensions': list(rubric.LAYER1_DIMENSIONS)},
                         ensure_ascii=False, indent=2))
        return 0

    if args.execute:
        verdict = guard.check(args.budget_usd)
        if not verdict['allowed']:
            print(guard.rendered_refusal(verdict, guard.missing_connection()))
            return 3
        if not args.answer_file:
            print('--execute cần --answer-file: đó là đầu ra THẬT cần chấm. Không có tệp thì '
                  'prompt chỉ là chỗ trống, gọi model là tiêu tiền vô ích.', file=sys.stderr)
            return 2
        fixture = fixtureset.load_fixtures()[args.fixture]
        answer = Path(args.answer_file).read_text(encoding='utf-8')
        prompt = render_layer2(fixture, answer, args.label)
        runner = JudgeRunner(base_url=args.base_url, model=args.model, budget_usd=args.budget_usd)
        scores = runner.score(prompt)
        print(json.dumps({'fixture': args.fixture, 'label': args.label or blind_label(answer),
                          'model': runner.model, 'scores': scores}, ensure_ascii=False, indent=2))
        return 0

    if args.layer == 1:
        print('Lớp 1 không có prompt: đây là oracle máy. Chạy:')
        print('  python scripts/eval/rushed_index.py --log ~/BoxFox/logs/harness.jsonl')
        return 0

    if args.layer == 3:
        text = render_layer3()
    else:
        fixture = fixtureset.load_fixtures()[args.fixture]
        answer = ''
        if args.answer_file:
            answer = Path(args.answer_file).read_text(encoding='utf-8')
        else:
            answer = ('(dry-run) đây là chỗ trống: khi chạy thật, phần này là nguyên văn đầu ra của '
                      'agent cho ca ' + args.fixture)
        text = render_layer2(fixture, answer, args.label)
        if not args.answer_file:
            print('! DRY-RUN: phần câu trả lời là chỗ trống, mọi phần khác là prompt thật sẽ gửi.')
            print(f'! Prompt giám khảo: {prompt_info()["version"]} '
                  f'sha256={prompt_info()["sha256"][:12]}…')
            print('! Không có model nào được gọi, không có kết nối mạng nào được mở.\n')
    if args.out:
        Path(args.out).write_text(text, encoding='utf-8')
        print(f'đã ghi {args.out} ({len(text)} ký tự)')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
