"""W6.5.3: nested lookup helper output cap 4096 vs 16000, native OpenCode Space Bunny only.

Each run drives ONE real Work Graph lookup helper through `graph.answer_knowledge` (normal
delegate path, `work.purpose == 'knowledge'`, parent 18 steps/300 s) on a disposable fixture
repo. The cap is selected only by the measurement knob BOXFOX_WORK_HELPER_OUTPUT_TOKENS that
`output_policy.child_budget` reads at spawn time. No producer, reviewer, main relay, UI or
production session. Runs are sequential; order alternates per repeat to spread drift.

Pre-registered decision rule (fixed before the live run, copied into results):
  raise the helper default above 4096 only if
    (A) >= 2 of the 16 runs at 4096 contain a provider completion with finish_reason `length`
        (output_policy.completion_reason == 'output_limit'), OR
    (B) mean coverage at 4096 is >= 10 points lower than at 16000, computed as the mean over the
        8 cases of the per-case paired difference (16000 mean - 4096 mean),
  AND (C) median helper wall time at 16000 <= 1.25 x median at 4096.
  Otherwise keep 4096. Per-case differences are reported as secondary data only.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from work_check_eval import ROOT, FixtureExecutor, HarnessRuntime, SessionStore, wg
from agentbox.agent_core import output_policy
from agentbox.agent_core.runtime import RouterClient
from agentbox.sandbox.worker import read_file_payload
import work_helper_budget_fixture as fixture

ENV = 'BOXFOX_WORK_HELPER_OUTPUT_TOKENS'
CAPS = (4096, 16000)
SOURCES = ('backend/src/agentbox/agent_core/output_policy.py', 'backend/src/agentbox/agent_core/runtime.py',
           'backend/src/agentbox/agent_core/work_graph.py', 'backend/src/agentbox/agent_core/work_prompts.py',
           'backend/src/agentbox/agent_core/work_checks.py', 'router/src/providers/opencode.mjs',
           'router/src/engine.mjs', 'router/src/request-budget.mjs', 'scripts/eval/work_check_eval.py',
           'scripts/eval/work_helper_budget_fixture.py', 'scripts/eval/work_helper_budget_eval.py')
RULE = {'lengthRunsAt4096Min': 2, 'runsAt4096': 16, 'coverageDropPointsMin': 10,
        'coverageDropDefinition': 'mean over 8 cases of (mean16000 - mean4096) per case',
        'wallMedianRatioMax': 1.25, 'combine': '(A or B) and C'}


class Client(RouterClient):
    """Real router client; logs every provider call. Fixture tools only (no web, no terminal)."""
    ALLOWED = {'file_read', 'codebase_grep', 'codebase_glob', 'work_artifact_read'}

    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        started = time.monotonic()
        result = await super().complete(messages, [t for t in tools if t['function']['name'] in self.ALLOWED], route, **kwargs)
        choice = (result.get('choices') or [{}])[0]
        message = choice.get('message') or {}
        self.calls.append({'maxTokens': kwargs.get('max_tokens'), 'latencyMs': round(1000 * (time.monotonic() - started)),
            'requestId': result.get('id'), 'finishReason': choice.get('finish_reason'),
            'reason': output_policy.completion_reason(result), **output_policy.usage_counts(result.get('usage')),
            'toolCalls': len(message.get('tool_calls') or []), 'contentChars': len(message.get('content') or ''),
            'reasoningChars': len(message.get('reasoning_content') or '')})
        return result


class Executor(FixtureExecutor):
    """Fixture executor whose glob/grep walk the real fixture folder."""
    def files(self):
        return sorted(p.relative_to(self.folder).as_posix() for p in self.folder.rglob('*')
                      if p.is_file() and p.name != 'sessions.db' and not p.name.startswith('sessions.db'))

    async def execute(self, name, args, sid, **identity):
        import fnmatch
        if name == 'codebase_glob':
            pattern = args.get('pattern') or '**/*'
            return {'content': '\n'.join(p for p in self.files() if fnmatch.fnmatch(p, pattern)
                                         or fnmatch.fnmatch(p, pattern.replace('**/', ''))), 'fixture': True}
        if name == 'codebase_grep':
            query, base = args.get('query', ''), (args.get('path') or '').rstrip('/')
            hits = [f'{p}:{i}: {line}' for p in self.files() if not base or p == base or p.startswith(base + '/')
                    for i, line in enumerate((self.folder / p).read_text(encoding='utf-8').splitlines(), 1) if query in line]
            return {'content': '\n'.join(hits[:200]), 'fixture': True}
        if name == 'file_read':
            # Same payload shape as the production worker (offset/limit/nextOffset/truncated).
            path = self.path(args['path'])
            if not path.is_file():
                return {'is_error': True, 'error': 'fixture path does not exist'}
            return {**read_file_payload(path, args.get('offset'), args.get('limit')), 'path': args['path'], 'fixture': True}
        return await super().execute(name, args, sid, **identity)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def git(*args, cwd=ROOT):
    return subprocess.check_output(['git', *args], cwd=cwd, text=True).strip()


def load():
    one, five, fifteen = os.getloadavg()
    others = subprocess.run(['pgrep', '-fc', 'pytest|_eval.py|_probe.py'], capture_output=True, text=True).stdout.strip()
    return {'loadavg': [round(one, 2), round(five, 2), round(fifteen, 2)], 'otherTestProcesses': int(others or 0) - 1}


def attempts(store, child_id):
    return [json.loads(r[0]) for r in store.db.execute(
        "SELECT payload FROM events WHERE session_id=? AND kind='completion_attempt' ORDER BY seq", (child_id,))]


async def one_run(args, route, case, cap, repeat, order):
    folder = Path(args.output) / f'{case["id"]}-{cap}-r{repeat}'
    for rel, text in fixture.FILES.items():
        (folder / rel).parent.mkdir(parents=True, exist_ok=True)
        (folder / rel).write_text(text, encoding='utf-8')
    os.environ[ENV] = str(cap)
    store = SessionStore(folder / 'sessions.db')
    client = Client(args.router)
    rt = HarnessRuntime(store, Executor(folder), client)
    root = rt.create({**route, 'skills': [], 'maxSteps': 18, 'deadlineSeconds': 300})
    graph = wg.service(rt)
    run = graph.create(root, {'goal': 'Tra cứu dữ kiện trong repo kho-ve để chuẩn bị báo cáo vận hành; chỉ đọc, không sửa mã.',
                              'flow': 'research'})
    node = wg.normalize_node({'id': 'E1', 'kind': 'research', 'title': 'Báo cáo vận hành kho-ve',
                              'goal': 'Tổng hợp dữ kiện vận hành từ repo kho-ve, có trích nguồn.'})
    before = load()
    record = {'case': case['id'], 'role': case['role'], 'cap': cap, 'repeat': repeat, 'order': order, 'loadBefore': before}
    started = time.monotonic()
    try:
        result = (await graph.answer_knowledge(store.get(root['id']), run, node, 'produce',
                                               [{'role': case['role'], 'question': case['question']}], 1))[0]
        wall = time.monotonic() - started
        child = result.get('childId')
        text = graph.artifacts.get(run['runId'], result['artifact']['artifactId'])[1] if result.get('artifact') else ''
        tried = attempts(store, child) if child else []
        config = store.get(child)['config'] if child else {}
        execution = result.get('execution') or {}
        record.update(status=result.get('status'), error=result.get('error'), childId=child,
            executionStatus=execution.get('status'), executionReason=execution.get('reason'),
            stepsUsed=execution.get('stepsUsed'),
            verification='evidenced' if result.get('status') == 'completed' and not result.get('error') else 'unverified',
            childMaxTokens=config.get('maxTokens'), workBudget=config.get('workBudget'), execution=execution, attempts=tried)
    except Exception as exc:
        wall = time.monotonic() - started
        text, tried = '', []
        record.update(status='error', error=f'{type(exc).__name__}: {exc}'[:500], verification='unverified', attempts=[])
    record.update(wallMs=round(1000 * wall), loadAfter=load(), calls=client.calls,
        finalFinishReason=(tried[-1]['finishReason'] if tried else None),
        lengthHit=any(a.get('reason') == 'output_limit' or a.get('finishReason') in ('length', 'max_tokens') for a in tried + client.calls),
        promptTokens=sum(c['inputTokens'] or 0 for c in client.calls),
        completionTokens=sum(c['outputTokens'] or 0 for c in client.calls),
        reasoningTokens=sum(c['reasoningTokens'] or 0 for c in client.calls),
        finalCompletionTokens=(client.calls[-1]['outputTokens'] if client.calls else None),
        usageComplete=all(c['outputTokens'] is not None for c in client.calls),
        providerCalls=len(client.calls), words=len(text.split()), chars=len(text),
        coverage=fixture.coverage(text, case),
        mechanism={'requestedMaxTokens': sorted({c['maxTokens'] for c in client.calls}),
                   'attemptMaxTokens': sorted({a.get('requestedMaxTokens') for a in tried}),
                   'ok': bool(client.calls) and all(c['maxTokens'] == cap for c in client.calls)
                         and record.get('childMaxTokens') == cap})
    (folder / 'answer.md').write_text(text, encoding='utf-8')
    store.db.close()
    return record


def summarize(rows):
    by = {cap: [r for r in rows if r['cap'] == cap] for cap in CAPS}
    def med(values):
        return statistics.median(values) if values else None
    summary = {}
    for cap, items in by.items():
        summary[str(cap)] = {'runs': len(items), 'lengthRuns': sum(r['lengthHit'] for r in items),
            'finalFinishReasons': {k: sum(1 for r in items if r['finalFinishReason'] == k) for k in sorted({str(r['finalFinishReason']) for r in items})},
            'meanCoverage': round(statistics.mean(r['coverage']['score'] for r in items), 2) if items else None,
            'medianWallMs': med([r['wallMs'] for r in items]), 'meanWallMs': round(statistics.mean(r['wallMs'] for r in items)) if items else None,
            'medianCompletionTokens': med([r['completionTokens'] for r in items]),
            'maxFinalCompletionTokens': max((r['finalCompletionTokens'] or 0 for r in items), default=None),
            'medianPromptTokens': med([r['promptTokens'] for r in items]),
            'medianWords': med([r['words'] for r in items]),
            'statuses': {k: sum(1 for r in items if r['status'] == k) for k in sorted({str(r['status']) for r in items})},
            'evidenced': sum(r['verification'] == 'evidenced' for r in items),
            'executionReasons': {k: sum(1 for r in items if str(r.get('executionReason')) == k) for k in sorted({str(r.get('executionReason')) for r in items})},
            'limitationsSectionPresent': sum(r['coverage']['tailPresent'] for r in items),
            'mechanismOk': sum(r['mechanism']['ok'] for r in items)}
    per_case = {}
    for case in fixture.CASES:
        means = {cap: statistics.mean([r['coverage']['score'] for r in by[cap] if r['case'] == case['id']] or [0]) for cap in CAPS}
        per_case[case['id']] = {'coverage4096': round(means[4096], 1), 'coverage16000': round(means[16000], 1),
                                'drop': round(means[16000] - means[4096], 1)}
    drop = round(statistics.mean(v['drop'] for v in per_case.values()), 2)
    a = summary['4096']['lengthRuns'] >= RULE['lengthRunsAt4096Min']
    b = drop >= RULE['coverageDropPointsMin']
    m4, m16 = summary['4096']['medianWallMs'], summary['16000']['medianWallMs']
    ratio = round(m16 / m4, 3) if m4 else None
    c = ratio is not None and ratio <= RULE['wallMedianRatioMax']
    complete = len(rows) == 2 * RULE['runsAt4096']
    decision = ('incomplete' if not complete else 'raise_to_16000' if (a or b) and c else 'keep_4096')
    return {'byCap': summary, 'perCase': per_case, 'meanPairedCoverageDrop': drop, 'wallMedianRatio16000over4096': ratio,
            'conditions': {'A_length': a, 'B_coverage': b, 'C_wall': c}, 'complete': complete, 'decision': decision}


async def main(args):
    branch = git('branch', '--show-current')
    if branch != 'B' and not branch.startswith('vorflux/'):
        raise SystemExit('Only branch B or vorflux/* is permitted')
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.tmp'):
        raise SystemExit('Output must be under this checkout .tmp/')
    output.mkdir(parents=True, exist_ok=True)
    args.output = str(output)
    manifest = {p: sha(ROOT / p) for p in SOURCES}
    probe = Client(args.router)
    state = await probe.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in (state or {}).get('connections', [])
                  if c['providerId'] == 'opencode' and c.get('enabled')
                  for m in c['models'] if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode space-bunny-free unavailable; no substitute')
    path = output / 'results.json'
    doc = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'rows': []}
    rows = doc['rows']
    doc.update(meta={'branch': branch, 'commit': git('rev-parse', 'HEAD'), 'dirty': bool(git('status', '--porcelain')),
        'sourceManifest': manifest, 'sourceManifestSha256': hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
        'opencodeAdapterSha256': manifest['router/src/providers/opencode.mjs'], 'route': route, 'router': args.router,
        'routerDeadline': args.router_deadline, 'routerNote': args.router_note,
        'parentBudget': {'maxSteps': 18, 'deadlineSeconds': 300}, 'rule': RULE, 'cases': [
            {'id': c['id'], 'role': c['role'], 'items': len(c['items']), 'question': c['question']} for c in fixture.CASES],
        'fixtureSha256': hashlib.sha256(json.dumps(fixture.FILES, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
        'cpuCount': os.cpu_count(), 'scope': ('Native helper lookup only via graph.answer_knowledge; synthetic run/node; '
            'fixture tools file_read/codebase_grep/codebase_glob/work_artifact_read; no producer/reviewer/main/UI.')})
    for repeat in range(1, args.repeats + 1):
        for index, case in enumerate(fixture.CASES):
            if args.cases and case['id'] not in args.cases:
                continue
            caps = CAPS if (repeat + index) % 2 == 0 else CAPS[::-1]
            for order, cap in enumerate(caps):
                if any(r['case'] == case['id'] and r['cap'] == cap and r['repeat'] == repeat for r in rows):
                    continue
                record = await one_run(args, route, case, cap, repeat, order)
                rows.append(record)
                doc['summary'] = summarize(rows) if {r['cap'] for r in rows} == set(CAPS) else None
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
                print(json.dumps({k: record.get(k) for k in ('case', 'cap', 'repeat', 'status', 'finalFinishReason', 'lengthHit',
                    'wallMs', 'completionTokens', 'words')} | {'coverage': record['coverage']['score'],
                    'mech': record['mechanism']['ok'], 'load': record['loadBefore']['loadavg'][0]}, ensure_ascii=False), flush=True)
    after = {p: sha(ROOT / p) for p in SOURCES}
    doc['meta']['sourceUnchangedDuringRun'] = after == manifest
    doc['summary'] = summarize(rows)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(doc['summary'], ensure_ascii=False, indent=1))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--router-deadline', default='small 90000 ms (<8000 max_tokens), large 180000 ms (>=8000)')
    parser.add_argument('--router-note', default='')
    parser.add_argument('--cases', nargs='*', default=None, help='smoke subset only; decision needs all 8')
    asyncio.run(main(parser.parse_args()))
