"""One entry point for the eval scaffolding: list, plan a run, or (later) run it.

Default is `--dry-run`: the script reads its own data files, prints exactly which
fixtures would run, how many model calls that is, and the cost range taken from
the two plan documents — and stops. It opens no socket and calls no model, which
`backend/tests/unit/test_eval_setup.py` proves by patching `socket.socket`.

`--execute` is the only path that could ever spend money. It refuses unless both
the explicit opt-in (`BOXFOX_EVAL_ALLOW_SPEND=1`) and a stated budget are
present, then hands each (fixture, config, repeat) cell to `runner.run_scenario`
and writes `results/<run>/scores.jsonl` under schema `research-scores-v2` (a cell
that never ran quality-validly is written with `metrics: null`, never 0).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fixtureset  # noqa: E402
import guard  # noqa: E402
import judge  # noqa: E402
import manifest as manifest_mod  # noqa: E402
import rubric  # noqa: E402
import runner  # noqa: E402
import rushed_index  # noqa: E402

REPO_DIR = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
TIERS_PATH = EVAL_DIR / 'benchmarks' / 'tiers.json'
# Kết quả chạy không nằm trong repo: chúng to và không bao giờ được commit.
# Cùng chỗ với dữ liệu khác của BoxFox trên host (~/BoxFox/...).
DEFAULT_OUT_ROOT = Path.home() / 'BoxFox' / 'eval-runs'
TIER_WITH_QUALITY_FIXTURES = '1'   # §3 tầng 1 liệt kê đúng bộ 12 fixture chất lượng

EXIT_OK, EXIT_USAGE, EXIT_SPEND, EXIT_CONNECTION, EXIT_NOT_IMPLEMENTED = 0, 2, 3, 4, 5
# Mã 5 (`EXIT_NOT_IMPLEMENTED`) nay KHÔNG còn đường nào trả về: `--execute` đã gọi
# `runner.run_scenario` thật (hợp đồng P0 §7). Giữ hằng số để mã cũ/tài liệu tham chiếu
# không vỡ, nhưng đừng dùng nó cho hành vi mới.
SCORES_SCHEMA_VERSION = 'research-scores-v2'

# §7 fixes the COUNT (12 fixture × 3 cấu hình) but not what the three are. These
# are placeholders so the cost arithmetic has something to multiply; the A/B axis
# itself is §1 RQ-Q5 ("so sánh A/B cùng bộ fixture, cùng model, cùng ngân sách bước").
CONFIGS = (
    {'id': 'c1', 'label': 'cấu hình nền: prompt/hợp đồng đang chạy hôm nay'},
    {'id': 'c2', 'label': 'cấu hình A: bản sửa prompt (chỗ giữ chỗ, chưa chốt)'},
    {'id': 'c3', 'label': 'cấu hình B: bản sửa hợp đồng/harness (chỗ giữ chỗ, chưa chốt)'},
)
CONFIG_NOTE = ('§7 chỉ nói "12 fixture × 3 cấu hình"; tên và nội dung ba cấu hình chưa có trong kế '
               'hoạch. Ba mã trên là chỗ giữ chỗ để tính chi phí — phải chốt với chủ sở hữu trước '
               'khi chạy, đây chính là trục A/B của §1 (RQ-Q5).')


def load_tiers() -> dict:
    return json.loads(TIERS_PATH.read_text(encoding='utf-8'))


def quality_estimate(fixture_count: int, config_count: int, repeat: int, tiers: dict) -> dict:
    """Cost of the quality-fixture track, scaled from the plan's own unit (§7)."""
    unit = tiers['qualityFixtures']
    agent_runs = fixture_count * config_count * repeat
    judge_calls = agent_runs * unit['judgePassesPerOutput']
    scale = (fixture_count / unit['fixturesInPlanUnit']) * (config_count / unit['configsInPlanUnit']) * repeat
    low_run, high_run = unit['agentRunCostUsd']
    low_judge, high_judge = unit['judgeCallCostUsd']
    agent_low, agent_high = round(low_run * scale, 2), round(high_run * scale, 2)
    judge_low, judge_high = round(judge_calls * low_judge, 2), round(judge_calls * high_judge, 2)
    return {
        'fixtures': fixture_count,
        'configs': config_count,
        'repeat': repeat,
        'agentRuns': agent_runs,
        'judgeCalls': judge_calls,
        'modelCalls': agent_runs + judge_calls,
        'agentCostUsd': [agent_low, agent_high],
        'judgeCostUsd': [judge_low, judge_high],
        'totalCostUsd': [round(agent_low + judge_low, 2), round(agent_high + judge_high, 2)],
        'basis': unit['source'],
        'scaleNote': (f'nhân theo ({fixture_count}/{unit["fixturesInPlanUnit"]} fixture) × '
                      f'({config_count}/{unit["configsInPlanUnit"]} cấu hình) × {repeat} lần lặp'),
        'judgeNote': unit['planNote'],
    }


def tier_plan(tier_id: str, tiers: dict) -> dict:
    for tier in tiers['tiers']:
        if tier['id'] == tier_id:
            return tier
    raise KeyError('tầng không có trong kế hoạch: ' + tier_id)


def quality_line_item(estimate: dict) -> dict:
    return {
        'id': 'quality-fixtures',
        'name': (f"{estimate['fixtures']} fixture chất lượng × {estimate['configs']} cấu hình × "
                 f"{estimate['repeat']} lần lặp"),
        'modelCalls': estimate['modelCalls'],
        'costUsd': estimate['totalCostUsd'],
        'source': estimate['basis'],
        'detail': estimate,
    }


def build_plan(*, fixtures: dict[str, dict], config_count: int, repeat: int, tiers: dict,
               tier_id: str | None = None, explicit_fixtures: bool = False) -> dict:
    """The whole dry-run answer as data (so tests assert on numbers, not on prose).

    Cost is summed from line items, never from prose: each item carries the plan
    section it comes from. When the tier's own written range and the sum of its
    items disagree, both are shown instead of quietly picking one.
    """
    # Số của đường Q chỉ tính ca họ Q. Một bộ chọn chỉ có ca research (họ R) mà vẫn nhân theo
    # `len(fixtures)` là bịa ngân sách: tầng R chạy 0 lượt gọi model (vòng 27, đợt 8).
    quality_codes = [code for code in fixtures
                     if fixtureset.family_of(code) == fixtureset.QUALITY_FAMILY]
    research_codes = [code for code in fixtures
                      if fixtureset.family_of(code) == fixtureset.RESEARCH_FAMILY]
    estimate = quality_estimate(len(quality_codes), config_count, repeat, tiers)
    line_items: list[dict] = []
    tier = tier_plan(tier_id, tiers) if tier_id is not None else None
    if tier is not None:
        for item in tier['items']:
            if item['id'] == 'quality-fixtures':
                continue  # our own computed item replaces the plan's summary row
            line_items.append({
                'id': item['id'], 'name': item['name'],
                'modelCalls': item.get('modelCalls'),
                'costUsd': item.get('costUsd'),
                'source': f"docs/plan/cua-benchmark-plan.md §3 tầng {tier['id']}",
                'blocked': item.get('blocked'),
                'commands': item.get('commands'),
            })
    # Chỉ tính khối chi phí đường Q khi bộ fixture được chọn THẬT SỰ có ca chất lượng: tầng R chạy
    # 0 lượt gọi model, in khối Q ở đó là bịa ngân sách (vòng 27, đợt 8).
    families = {fixtureset.family_of(code) for code in fixtures}
    quality_selected = not families or fixtureset.QUALITY_FAMILY in families
    include_quality = quality_selected and ((tier is None)
                                            or (tier['id'] == TIER_WITH_QUALITY_FIXTURES)
                                            or explicit_fixtures)
    if include_quality:
        line_items.append(quality_line_item(estimate))
    lows = [item['costUsd'][0] for item in line_items if item.get('costUsd')]
    highs = [item['costUsd'][1] for item in line_items if item.get('costUsd')]
    plan = {
        'mode': 'dry-run',
        'modelCalls': sum(item['modelCalls'] for item in line_items
                          if isinstance(item.get('modelCalls'), int)),
        'costUsd': [round(sum(lows), 2), round(sum(highs), 2)] if lows else None,
        'lineItems': line_items,
        'estimate': estimate if include_quality else None,
        'qualityTrackIncluded': include_quality,
        'fixtures': [_fixture_row(code, fixtures[code]) for code in quality_codes]
                    if include_quality else [],
        'researchFixtures': [_fixture_row(code, fixtures[code]) for code in research_codes],
        'configs': [dict(item) for item in CONFIGS[:config_count]] if include_quality else [],
        'configNote': CONFIG_NOTE if include_quality else None,
        'networkCalls': 0,
        'tier': tier,
        'tierPlanRange': tier.get('costUsd') if tier else None,
        'judgePrompt': judge.prompt_info(),
        'rubricVersion': f'C1-C8 / manifest {manifest_mod.MANIFEST_VERSION}',
        'implementationGaps': [
            'runner chạy fixture thật: ĐÃ cài đặt (P0a) — chưa chạy lượt thật nào (cần opt-in + '
            'ngân sách + harness)',
            'lớp 2 (giám khảo LLM): ĐÃ cài đặt qua router (P0a) — chưa gọi lượt thật nào',
            'lớp 1 (oracle máy): đã có phần chỉ số vội (rushed_index.py); phần kiểm từng fixture còn thiếu',
            'gói nguồn cố định cho 13 tình huống (§8.3): chưa thu thập — xem scripts/eval/packs/README.md',
        ],
    }
    return plan


def _fixture_row(code: str, item: dict) -> dict:
    """Một hàng fixture cho phần chi tiết của `--plan` (giữ đúng khoá giao diện cũ)."""
    return {'id': code,
            'case': item['case'],
            'dimensions': item['rubric_dimensions'],
            'network': item['environment']['network'],
            'maxSteps': item['budget']['max_steps']}


def _money(range_usd) -> str:
    if not range_usd:
        return 'chưa cho trong kế hoạch'
    low, high = range_usd
    return f'{low:.2f}-{high:.2f} USD' if low != high else f'{low:.2f} USD'


def _tier_label(tier: dict) -> str:
    """Nhãn tầng đã bỏ tiền tố 'Tầng N — ' để không lặp lại khi in kèm số tầng."""
    label = tier.get('label', '')
    prefix = f"Tầng {tier['id']} — "
    return label[len(prefix):] if label.startswith(prefix) else label


def _fixture_table(items: dict[str, dict]) -> list[str]:
    """Bảng fixture của MỘT họ — hàng nào cũng thuộc đúng tiêu đề đang in phía trên nó."""
    lines = ['| Mã | Ca | Chiều | Mạng | Trần bước |', '|---|---|---|---|---|']
    for code, item in items.items():
        lines.append(f"| {code} | {item['case']} | {', '.join(item['rubric_dimensions'])} | "
                     f"{item['environment']['network']} | {item['budget']['max_steps']} |")
    return lines


def render_list(fixtures: dict[str, dict], tiers: dict) -> str:
    """Bảng fixture ĐANG chọn + các tầng. Danh sách phải theo `--fixtures`, không in cả bộ."""
    research = {code: item for code, item in fixtures.items()
                if fixtureset.family_of(code) == fixtureset.RESEARCH_FAMILY}
    quality = {code: item for code, item in fixtures.items() if code not in research}
    if quality:
        lines = [f'Fixture chất lượng (kế hoạch chất lượng §4) — {len(quality)} ca tĩnh:']
    elif research:
        lines = [f'Fixture research (tầng R, kế hoạch vòng 27 §8) — {len(research)} ca tĩnh:']
    else:
        lines = ['Fixture: bộ đang chọn rỗng:']
    lines.extend(_fixture_table(quality if quality else research))
    if research and quality:
        # Chỉ in khối thứ hai khi bộ chọn CÓ cả hai họ (một tiêu đề là đủ khi chỉ có một họ).
        lines.append('')
        lines.append(f'Fixture research (tầng R, kế hoạch vòng 27 §8) — {len(research)} ca tĩnh:')
        lines.extend(_fixture_table(research))
        lines.append('')
    elif research:
        # Đang chỉ có họ R: bảng R đã nằm dưới tiêu đề R ở trên, không lặp tiêu đề.
        lines.append('')
    lines.append('Tầng benchmark (kế hoạch benchmark §3):')
    for tier in tiers['tiers']:
        lines.append(f"  Tầng {tier['id']} — {_tier_label(tier)} ({tier['window']}), "
                     f"{_money(tier.get('costUsd'))}")
        for item in tier['items']:
            blocked = f" [chặn: {item['blocked']}]" if item.get('blocked') else ''
            lines.append(f"    - {item['id']}: {item['name']} — {_money(item.get('costUsd'))}{blocked}")
    return '\n'.join(lines)


def render_plan(plan: dict, out_dir: Path) -> str:
    lines: list[str] = []
    lines.append('=' * 78)
    lines.append('BOXFOX EVAL — DRY RUN (không gọi model, không mở kết nối mạng)')
    lines.append('=' * 78)
    lines.append('')
    if plan['tier']:
        tier = plan['tier']
        lines.append(f"{tier['label']} ({tier['window']})")
    else:
        lines.append('Bộ fixture chất lượng (không kèm tầng benchmark nào)')
    lines.append('')
    lines.append('Hạng mục sẽ chạy (mỗi dòng ghi rõ nguồn số):')
    for item in plan['lineItems']:
        calls = 'chưa cho số' if item.get('modelCalls') is None else f"{item['modelCalls']} lượt model"
        blocked = f" [chặn: {item['blocked']}]" if item.get('blocked') else ''
        lines.append(f"  - {item['id']}: {item['name']} — {calls}, {_money(item.get('costUsd'))}"
                     f"{blocked}")
        lines.append(f"      nguồn: {item['source']}")
        for command in item.get('commands') or []:
            lines.append(f"      lệnh: {command}")
    if not plan['qualityTrackIncluded']:
        lines.append('  (bộ fixture chất lượng KHÔNG nằm trong tầng này: kế hoạch chỉ xếp chúng vào '
                     'tầng 1. Muốn xem riêng thì bỏ --plan-tier.)')
    lines.append('')
    lines.append(f"Tổng lượt gọi model nếu chạy thật: {plan['modelCalls']}")
    lines.append(f"Tổng chi phí ước lượng: {_money(plan['costUsd'])} "
                 f"(cộng theo hạng mục ở trên, KHÔNG phải hoá đơn)")
    if plan['tier'] and plan['tierPlanRange'] and plan['costUsd']:
        low, high = plan['costUsd']
        plan_low, plan_high = plan['tierPlanRange']
        if (low, high) != (plan_low, plan_high):
            lines.append(f"  lưu ý: kế hoạch ghi cả tầng là {_money(plan['tierPlanRange'])} — số cộng "
                         f"theo hạng mục ở trên khác vì một số hạng mục chưa có dải giá riêng, và vì "
                         f"bộ 12 fixture được tính theo đúng số lần lặp sẽ chạy.")
    lines.append('')
    if plan['estimate']:
        estimate = plan['estimate']
        lines.append(f"Bộ {len(plan['fixtures'])} fixture chất lượng, chi tiết:")
        for item in plan['fixtures']:
            lines.append(f"  - {item['id']}: {item['case']} | chiều {', '.join(item['dimensions'])} | "
                         f"mạng {item['network']} | trần {item['maxSteps']} bước")
        lines.append(f"  Cấu hình ({len(plan['configs'])}): " +
                     '; '.join(f"{item['id']}={item['label']}" for item in plan['configs']))
        lines.append(f"  ({plan['configNote']})")
        lines.append(f"  lượt agent = {estimate['fixtures']} fixture × {estimate['configs']} cấu hình × "
                     f"{estimate['repeat']} lần lặp = {estimate['agentRuns']}")
        lines.append(f"  lượt chấm lớp 2 = {estimate['judgeCalls']} "
                     f"({estimate['agentRuns']} đầu ra × {2} lần chấm mỗi đầu ra, kế hoạch §5)")
        lines.append(f"  lượt agent: {_money(estimate['agentCostUsd'])} | lớp 2: "
                     f"{_money(estimate['judgeCostUsd'])} | cộng: {_money(estimate['totalCostUsd'])}")
        lines.append(f"  ({estimate['scaleNote']})")
        lines.append(f"  {estimate['judgeNote']}")
        lines.append('')
    if plan['researchFixtures']:
        lines.append(f"Bộ {len(plan['researchFixtures'])} fixture research (tầng R, không lượt model "
                     f"nào — hạng mục `research-scores` đang chặn):")
        for item in plan['researchFixtures']:
            lines.append(f"  - {item['id']}: {item['case']} | chiều {', '.join(item['dimensions'])} | "
                         f"mạng {item['network']} | trần {item['maxSteps']} bước")
        lines.append('')
    lines.append('Nơi ghi kết quả nếu chạy thật:')
    lines.append(f"  - manifest:  {out_dir / 'manifest.json'}")
    lines.append(f"  - kết quả thô: {out_dir / 'runs'}/<fixture>-<config>-<repeat>.json")
    lines.append(f"  - bảng điểm: python scripts/eval/scoreboard.py --results {out_dir} "
                 f"--out docs/tracking/eval-<benchmark>.md")
    lines.append('')
    lines.append('Còn thiếu trong scaffolding (nói thẳng, không giấu):')
    for gap in plan['implementationGaps']:
        lines.append(f"  - {gap}")
    lines.append('')
    lines.append(f"Prompt giám khảo đóng băng: {plan['judgePrompt']['version']} "
                 f"(sha256 {plan['judgePrompt']['sha256'][:12]}…)")
    lines.append(f"Rubric: {plan['rubricVersion']}")
    lines.append('')
    lines.append('Chi phí thật của lần chạy này: CHƯA ĐO (chưa chạy gì).')
    lines.append('Muốn chạy thật: đọc scripts/eval/README.md, rồi --execute với opt-in + ngân sách.')
    return '\n'.join(lines)


def scenarios_from(selected: dict[str, dict], *, pack: str | None = None,
                   workspace: str | None = None) -> list[dict]:
    """Biến fixture đã chọn thành `scenario` cho `runner.run_scenario` (không gọi gì)."""
    scenarios: list[dict] = []
    for code, item in selected.items():
        budget = item.get('budget') or {}
        scenarios.append({
            'id': code,
            'prompt': item.get('request') or '',
            'pack': pack,
            'workspace': workspace or item.get('workspace'),
            'budget': {'max_steps': budget.get('max_steps'),
                       'deadline_seconds': budget.get('deadline_seconds'),
                       'wall_seconds': budget.get('wall_seconds')},
            'seed': budget.get('seed', 0),
        })
    return scenarios


def write_scores(out_dir: Path, rows: list[dict], *, pack_hash: dict, route: str,
                 agent_model: str, judge_prompt: dict) -> dict:
    """Ghi `scores.jsonl` (schema `research-scores-v2`) + `manifest.json`, trả tóm tắt."""
    out_dir.mkdir(parents=True, exist_ok=True)
    scores_path = out_dir / 'scores.jsonl'
    recorded_at = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    with scores_path.open('w', encoding='utf-8') as handle:
        for row in rows:
            # H3 — `measured: true` chỉ khi THẬT SỰ có khối `metrics`; không bao giờ ghi
            # `measured: true, metrics: null`.
            metrics = row.get('metrics')
            measured = bool(row.get('measured')) and metrics is not None
            handle.write(json.dumps({
                'schemaVersion': SCORES_SCHEMA_VERSION,
                'recordedAt': recorded_at,
                'scenarioId': row.get('scenarioId'),
                'configId': row.get('configId'),
                'repeat': row.get('repeat'),
                'validity': row.get('validity'),
                'measured': measured,
                'metrics': metrics if measured else None,
                'reruns': row.get('reruns'),
                'infraFailureRate': row.get('infraFailureRate'),
                'infraErrorCodes': row.get('infraErrorCodes') or {},
                'errorCode': row.get('errorCode'),
                'artifacts': row.get('artifacts') or {},
            }, ensure_ascii=False) + '\n')
    infra = runner.summarize_infra(rows)
    flags = runner.flag_rate_divergence(infra['byConfig'])
    manifest = manifest_mod.build_manifest(
        benchmark_name='boxfox-research-eval', benchmark_version='v2',
        repo_dir=REPO_DIR, fixture_ids=sorted({row.get('scenarioId') for row in rows}),
        provider=route, model=agent_model, seed=0, temperature=0.0,
        network=manifest_mod.env_network_state(), judge_prompt=judge_prompt,
        created_at=recorded_at,
        extra={
            'scoresSchema': SCORES_SCHEMA_VERSION,
            'pack': pack_hash,
            'infraFailure': infra,
            'infraDivergence': flags,
            'runWindow': {'recordedAt': recorded_at},
        })
    manifest_mod.write_manifest(out_dir / 'manifest.json', manifest)
    summary = {
        'scoresPath': str(scores_path),
        'manifestPath': str(out_dir / 'manifest.json'),
        'cells': len(rows),
        'measured': sum(1 for row in rows if row.get('measured')),
        'infraFailure': infra,
        'infraDivergence': flags,
    }
    return summary


def render_execute(summary: dict) -> str:
    lines = ['=' * 78, 'BOXFOX EVAL — lượt chạy thật đã ghi số', '=' * 78, '']
    lines.append(f"Ô đo: {summary['cells']} | đo được: {summary['measured']} | "
                 f"chưa đo: {summary['cells'] - summary['measured']}")
    for config_id, rate in (summary['infraFailure'].get('byConfig') or {}).items():
        shown = 'chưa đo' if rate is None else f'{rate * 100:.1f}%'
        lines.append(f"  - tỉ lệ lỗi hạ tầng {config_id}: {shown}")
    if summary['infraDivergence'].get('flagged'):
        lines.append('  ! CẢNH BÁO: tỉ lệ lỗi hạ tầng lệch > 10 điểm % giữa các cấu hình — '
                     'kết quả so sánh bị gắn cờ.')
    lines.append(f"  - bảng điểm: {summary['scoresPath']}")
    lines.append(f"  - manifest:  {summary['manifestPath']}")
    lines.append('')
    lines.append('Ô `validity=infra-failed` và `harness-bug` ghi `metrics: null` (chưa đo), không ghi 0.')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Đánh giá chất lượng đầu ra + benchmark cho BoxFox (mặc định: dry-run).')
    parser.add_argument('--list', action='store_true', help='liệt kê fixture và các tầng')
    parser.add_argument('--dry-run', action='store_true',
                        help='chỉ in kế hoạch chạy (đây là hành vi MẶC ĐỊNH)')
    parser.add_argument('--execute', action='store_true',
                        help='ĐƯỜNG DUY NHẤT có thể gọi model (cần opt-in + ngân sách)')
    parser.add_argument('--plan-tier', default=None,
                        help='mã tầng trong scripts/eval/benchmarks/tiers.json, ví dụ 0 hoặc tier-r1')
    parser.add_argument('--tier', dest='plan_tier', default=None,
                        help='tên khác của --plan-tier (bộ ca research dùng --tier tier-r1)')
    parser.add_argument('--plan', action='store_true',
                        help='tên khác của --dry-run: chỉ in kế hoạch chạy')
    parser.add_argument('--fixture', action='append', default=None,
                        help='lặp lại được, ví dụ --fixture Q1 --fixture Q5')
    parser.add_argument('--fixtures', dest='fixture', action='append', default=None,
                        help='tên khác của --fixture; nhận cả họ R, ví dụ --fixtures R1')
    parser.add_argument('--out', default=None,
                        help=f'thư mục kết quả (mặc định {DEFAULT_OUT_ROOT}/<tên bộ>)')
    parser.add_argument('--configs', type=int, default=len(CONFIGS))
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--budget-usd', type=float, default=None)
    parser.add_argument('--json', action='store_true', help='in JSON của kế hoạch')
    args = parser.parse_args(argv)

    wants_research = any(fixtureset.family_of(code) == fixtureset.RESEARCH_FAMILY
                         for code in (args.fixture or []))
    try:
        fixtures = fixtureset.load_fixtures(family=None if wants_research else fixtureset.QUALITY_FAMILY)
        selected = fixtureset.select(fixtures, args.fixture)
    except (FileNotFoundError, ValueError, KeyError) as exc:
        print(f'lỗi dữ liệu fixture: {exc}', file=sys.stderr)
        return EXIT_USAGE
    issues = fixtureset.set_issues(selected)
    tiers = load_tiers()
    if args.plan_tier is not None and args.plan_tier not in [tier['id'] for tier in tiers['tiers']]:
        known = ', '.join(tier['id'] for tier in tiers['tiers'])
        print(f'--tier/--plan-tier không có trong kế hoạch: {args.plan_tier} (đang có: {known})',
              file=sys.stderr)
        return EXIT_USAGE

    if args.list:
        print(render_list(selected, tiers))
        if issues:
            print('\ncảnh báo bộ fixture: ' + '; '.join(issues))
        return EXIT_OK

    if args.configs < 1 or args.configs > len(CONFIGS):
        print(f'--configs phải trong 1..{len(CONFIGS)}', file=sys.stderr)
        return EXIT_USAGE
    if args.repeat < 1:
        print('--repeat phải ≥ 1', file=sys.stderr)
        return EXIT_USAGE

    if args.out:
        out_dir = Path(args.out)
    else:
        name = (f"tier{args.plan_tier}" if args.plan_tier and args.plan_tier.isdigit()
                else (args.plan_tier or 'quality-fixtures'))
        out_dir = DEFAULT_OUT_ROOT / name

    if args.plan and args.execute:
        print('--plan và --execute loại trừ nhau: --plan chỉ in kế hoạch', file=sys.stderr)
        return EXIT_USAGE
    if not args.execute:
        plan = build_plan(fixtures=selected, config_count=args.configs, repeat=args.repeat,
                          tiers=tiers, tier_id=args.plan_tier,
                          explicit_fixtures=bool(args.fixture))
        if args.json:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
        else:
            print(render_plan(plan, out_dir))
        return EXIT_OK

    # ---- from here down is the ONLY place money could be spent ----
    verdict = guard.check(args.budget_usd)
    if not verdict['allowed']:
        print(guard.rendered_refusal(verdict, guard.missing_connection()))
        return EXIT_SPEND
    missing = guard.missing_connection()
    if missing:
        print('Đã qua cổng chi tiền nhưng thiếu kết nối:', file=sys.stderr)
        for item in missing:
            print(f"  - {item['name']}: {item['why']}", file=sys.stderr)
        print('Đặt các biến này rồi chạy lại. Không dán giá trị bí mật vào chat.', file=sys.stderr)
        return EXIT_CONNECTION
    print('Cổng chi tiền đã qua và kết nối đã có — bắt đầu chạy thật qua harness.')
    scenarios = scenarios_from(selected, pack=os.environ.get('BOXFOX_WEB_PACK') or None)
    configs = [dict(item) for item in CONFIGS[:args.configs]]
    rows: list[dict] = []
    for scenario in scenarios:
        for config in configs:
            for repeat in range(args.repeat):
                try:
                    rows.append(runner.run_scenario(
                        scenario, config, repeat=repeat, allow_spend=True,
                        budget_usd=verdict['budgetUsd']))
                except runner.SpendRefused as exc:
                    print(f'cổng chi tiền đóng giữa chừng: {exc}', file=sys.stderr)
                    return EXIT_SPEND
    summary = write_scores(
        out_dir, rows,
        pack_hash=runner.pack_hash(os.environ.get('BOXFOX_WEB_PACK')),
        route=os.environ.get('BOXFOX_ROUTER_BASE_URL') or runner.DEFAULT_ROUTE,
        agent_model=os.environ.get('BOXFOX_EVAL_AGENT_MODEL') or runner.DEFAULT_AGENT_MODEL,
        judge_prompt=judge.prompt_info())
    print(render_execute(summary))
    if rows and not summary['measured']:
        print('Không ô nào chạy tới trạng thái hợp lệ về chất lượng: hạ tầng chưa sẵn sàng.',
              file=sys.stderr)
        return EXIT_CONNECTION
    return EXIT_OK


if __name__ == '__main__':
    raise SystemExit(main())
