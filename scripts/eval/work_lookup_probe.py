"""W6.2 native probe: does a lookup node produce the short, sourced deliverable?

A/B on the same fixture: the `legacy` arm reproduces pre-W6.2 runs (no taskKind/depth, so
`work_prompts.deliverable()` falls back to the old map); the `lookup` arm passes
`taskKind='lookup'` and gets the new short contract. Space Bunny only, fixture-approved
artifacts, no main model, no Build. N is small and reported.

Oracles (lookup arm): the Answer section stays within 120 words, a sources-opened section
exists, and no options/recommendation section is invented. The legacy arm is a measurement.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))

from work_check_eval import ROOT, HarnessRuntime, SessionStore, FixtureClient, FixtureExecutor  # noqa: E402
from agentbox.agent_core import work_graph as wg, work_prompts  # noqa: E402


ANSWER_CAP = work_prompts.LOOKUP_ANSWER_WORDS
SOURCE_HEAD = re.compile(r'(sources?\s+opened|nguồn\s+đã\s+mở)', re.I)
OPTION_HEAD = re.compile(r'(^|\n)#{1,4}\s*(options?|khuyến nghị|đề xuất|lựa chọn)', re.I)


def words(text):
    return len(re.findall(r'\S+', text))


def answer_part(text):
    lines, keep = [], []
    for line in text.splitlines():
        if SOURCE_HEAD.search(line):
            break
        keep.append(line)
    lines = keep
    return '\n'.join(lines).strip()


def contract_words(text):
    return words(text)


class Client(FixtureClient):
    """Space Bunny only; records every completion for the evidence file."""

    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        assert route['modelId'] == 'space-bunny-free'
        result = await super().complete(messages, tools, route, **kwargs)
        self.calls.append({'route': route, 'maxTokens': kwargs.get('max_tokens'), 'usage': result.get('usage'),
                           'requestId': result.get('id'),
                           'finishReason': result.get('choices', [{}])[0].get('finish_reason')})
        return result


CASES = [
    {'case': 'legacy', 'node': {'id': 'E1', 'kind': 'explore', 'title': 'Tra cứu phạm vi',
                                'goal': 'Đọc ghi chú docs/source.md và cho biết ghi chú quy định xuất CSV hay JSON.',
                                'acceptance': ['Nêu đúng phạm vi theo ghi chú']}, 'oracle': False},
    {'case': 'lookup', 'node': {'id': 'E1', 'kind': 'explore', 'title': 'Tra cứu phạm vi', 'taskKind': 'lookup',
                                'goal': 'Đọc ghi chú docs/source.md và cho biết ghi chú quy định xuất CSV hay JSON.',
                                'acceptance': ['Nêu đúng phạm vi theo ghi chú']}, 'oracle': True},
]


async def main(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'B' or branch.startswith('vorflux/'), branch
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp')
    output.mkdir(parents=True, exist_ok=True)
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
        'backend/src/agentbox/agent_core/work_prompts.py', 'backend/src/agentbox/agent_core/work_graph.py',
        'backend/src/agentbox/agent_core/work_checks.py', 'backend/src/agentbox/agent_core/work_policy.py')}
    client = Client(args.router)
    state = await client.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                  if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
                  if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    rows = []
    for case in CASES:
        for attempt in range(args.repeat):
            folder = output / f"{case['case']}-{attempt + 1}"
            (folder / 'docs').mkdir(parents=True, exist_ok=True)
            (folder / 'src').mkdir(parents=True, exist_ok=True)
            (folder / 'docs/source.md').write_bytes(
                'Ghi chú phạm vi: chỉ xuất CSV; KHÔNG thêm JSON. Giới hạn: ghi chú này không nói gì về test.\n'.encode('utf8'))
            (folder / 'src/export.py').write_bytes(b'def export(value):\n    return value\n')
            (folder / '.gitignore').write_bytes(b'sessions.db*\n.plans/\n.pytest_cache/\n**/__pycache__/\n')
            subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
            subprocess.run(['git', 'add', '-A'], cwd=folder, check=True)
            subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@localhost',
                            'commit', '-qm', 'fixture'], cwd=folder, check=True)
            store = SessionStore(folder / 'sessions.db')
            rt = HarnessRuntime(store, FixtureExecutor(folder), client)
            root = rt.create({**route, 'skills': [], 'maxSteps': 16, 'deadlineSeconds': 300, 'maxTokens': 4096})
            sid = root['id']
            graph = wg.service(rt)
            node = case['node']
            run = graph.create(root, {'goal': 'Chốt phạm vi xuất dữ liệu theo ghi chú trong repo.',
                                      'flow': 'research', 'nodes': [node]})
            row = {'case': case['case'], 'attempt': attempt + 1, 'branch': branch, 'commit': commit,
                   'sourceManifest': sources, 'route': route, 'taskKind': node.get('taskKind'),
                   'contract': work_prompts.deliverable('explore', 'vi', node.get('taskKind'), node.get('depth'))}
            started = time.monotonic()
            try:
                status = await graph.run_stage(root, run, run['nodes'][0], 'produce', 1)
                stage = graph.get(run['runId'])['nodes'][0]['stages']['produce']
                text = stage.get('output') or ''
                answer = answer_part(text)
                row.update(status=status, producerStatus=stage['status'], totalWords=words(text),
                           answerWords=words(answer), hasSources=bool(SOURCE_HEAD.search(text)),
                           optionsSection=bool(OPTION_HEAD.search(text)),
                           verifyExecNone=None, answer=text[:4000])
                if case['oracle']:
                    row['oracle'] = (stage['status'] == 'accepted' and row['answerWords'] <= ANSWER_CAP
                                     and row['hasSources'] and not row['optionsSection'])
                else:
                    row['oracle'] = None
            except Exception as exc:
                row.update(oracle=False, error=str(exc))
            row['latencySeconds'] = round(time.monotonic() - started, 3)
            row['calls'] = client.calls
            rows.append(row)
            (output / 'results.json').write_bytes((json.dumps(rows, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
            print(json.dumps({k: row.get(k) for k in ('case', 'attempt', 'status', 'producerStatus', 'totalWords',
                                                      'answerWords', 'hasSources', 'optionsSection', 'oracle',
                                                      'latencySeconds', 'error')}, ensure_ascii=False), flush=True)
            await rt.stop(sid)
            store.db.close()
    measured = [row for row in rows if row.get('oracle') is not None]
    summary = {'rows': len(rows), 'oracle': sum(1 for row in measured if row.get('oracle')),
               'lookup': [{'totalWords': row.get('totalWords'), 'answerWords': row.get('answerWords'),
                           'hasSources': row.get('hasSources'), 'optionsSection': row.get('optionsSection'),
                           'oracle': row.get('oracle')} for row in rows if row['case'] == 'lookup'],
               'legacy': [{'totalWords': row.get('totalWords'), 'answerWords': row.get('answerWords'),
                           'hasSources': row.get('hasSources'), 'optionsSection': row.get('optionsSection')}
                          for row in rows if row['case'] == 'legacy'],
               'contractWords': {row['case']: contract_words(row['contract']) for row in rows}}
    (output / 'summary.json').write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    print(json.dumps(summary, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--repeat', type=int, default=1)
    asyncio.run(main(parser.parse_args()))
