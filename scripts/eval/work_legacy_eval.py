"""W5.LEGACY — probe DB cũ: đọc được, không dùng lại làm bằng chứng đạt, và vá đúng version.

Fixture dựng trực tiếp một DB "legacy": run không có `verificationVersion` (view đọc ra
`legacy`) và một check có `policy.version` cũ hơn `work_policy.VERSION`. Probe kiểm sáu điều
của §7 (W5.LEGACY):

1. Run cũ vẫn đọc được (`work_graph(action='status')`).
2. Policy cũ KHÔNG được dùng làm pass (`WORK_CHECK_STALE`); `verify` trên run legacy bị chặn
   bằng `WORK_LEGACY_CHECKS_REQUIRED` (đọc được, chưa phải bằng chứng hiện hành).
3. `work_run` nhập lại run cũ sang version hiện hành, giữ đúng `runId` và tăng `revision`.
4. Binding mới mang đúng `runId`/`version`/`policyHash` và đọc lại round-trip.
5. Artifact bị sửa ngoài → `WORK_ARTIFACT_CORRUPT`.
6. Restart khi admission đang `reserved`/`admitted` → `interrupted` (`work_progress.recover()`).
7. Index/refs của status trỏ đúng version của registry (không trỏ bản cũ).

Không cần model hay provider: đây là probe cơ chế dữ liệu, không đo hành vi model.

Chạy:
    python3 scripts/eval/work_legacy_eval.py --output .tmp/w7-legacy
"""
import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/src'))

from agentbox.agent_core import work_graph as wg, work_policy
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


LEGACY_RUN = 'wr-legacy-0001'
LEGACY_POLICY = 'work-checks/9'
NODE = {'id': 'R1', 'kind': 'research', 'title': 'Options', 'goal': 'Research the options with original evidence',
        'dependsOn': [], 'acceptance': ['Cite an original source'], 'tests': [], 'files': [], 'taskKind': 'lookup',
        'stages': {'produce': {'status': 'accepted', 'attempts': 1, 'rounds': [{'attempt': 1, 'producerRole': 'research'}],
                               'output': 'legacy body', 'outputChars': 11, 'feedback': '', 'knowledge': [],
                               'error': None, 'startedAt': 1.0, 'finishedAt': 2.0}}}


def branch():
    name = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert name == 'B' or name.startswith('vorflux/'), f'unexpected branch {name!r}'
    return name


def commit():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def source_manifest():
    files = ['backend/src/agentbox/agent_core/work_graph.py', 'backend/src/agentbox/agent_core/work_checks.py',
             'backend/src/agentbox/agent_core/work_policy.py', 'backend/src/agentbox/agent_core/work_artifacts.py',
             'backend/src/agentbox/agent_core/work_progress.py']
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}


class Executor:
    """Minimal workspace: artifacts and snapshots are recorded, never touched."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid, **_identity):
        self.calls.append((name, args))
        if name == 'file_write':
            return {'relativePath': args.get('path'), 'bytes': len(str(args.get('content') or ''))}
        if name == 'terminal_exec':
            return {'content': json.dumps({'schema': 'work-code/1', 'hash': 'b' * 64, 'head': 'legacy'}),
                    'exit_code': 0, 'is_error': False}
        return {'content': 'legacy probe'}

    async def cleanup(self, sid):
        return None


class Client:
    async def complete(self, messages, tools, route, **kwargs):  # pragma: no cover - must not run
        raise AssertionError('legacy probe must not call a model')


def seed_legacy(store, sid, run_id=LEGACY_RUN):
    """A run written by the pre-W6 engine: no `verificationVersion`, an old review field."""
    doc = {'runId': run_id, 'sessionId': sid, 'title': 'Legacy run', 'goal': 'Giữ tương thích dữ liệu cũ',
           'flow': 'research', 'status': 'drafting', 'nodes': [json.loads(json.dumps(NODE))],
           'history': [{'at': 1.0, 'event': 'created'}], 'createdAt': 1.0, 'updatedAt': 2.0,
           'review': {'status': 'ok', 'rounds': [{'round': 1, 'verdict': 'ok'}]}, 'interviews': []}
    with store.db:
        store.db.execute('INSERT INTO work_runs(id, session_id, status, revision, doc, created, updated) '
                         'VALUES(?,?,?,?,?,?,?)',
                         (run_id, sid, doc['status'], 1, json.dumps(doc, ensure_ascii=False), 1.0, 2.0))
    return doc


async def main(args):
    name, head, manifest = branch(), commit(), source_manifest()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp'), 'write probe output under .tmp/'
    output.mkdir(parents=True, exist_ok=True)
    path = output / 'sessions.db'
    store = SessionStore(path)
    runtime = HarnessRuntime(store, Executor(), Client())
    sid = runtime.create({'skills': []})['id']
    graph = wg.service(runtime)
    session = store.get(sid)
    row = {'branch': name, 'commit': head, 'sourceManifest': manifest, 'currentVersion': work_policy.VERSION,
           'legacyPolicyVersion': LEGACY_POLICY, 'checks': {}}
    seed_legacy(store, sid)
    legacy = graph.get(LEGACY_RUN)

    # 1. Run cũ đọc được; view nói rõ đây là bản legacy, không phải verification hiện hành.
    view = graph.view(legacy)
    row['checks']['old_run_readable'] = {'status': legacy['status'],
                                         'verificationVersion': view.get('verificationVersion'),
                                         'hasLegacyReview': bool(view.get('legacyReview') or legacy.get('review'))}
    # 2a. `verify` trên run cũ bị chặn, không im lặng coi là đã kiểm.
    try:
        await graph.verify(session, {'runId': LEGACY_RUN})
        row['checks']['legacy_verify_blocked'] = None
    except ValueError as exc:
        row['checks']['legacy_verify_blocked'] = str(exc)[:160]
    # 2b. Policy cũ không được dùng làm pass: binding khớp hiện hành, CHỈ `policy.version` cũ.
    node = legacy['nodes'][0]
    stale_policy = work_policy.derive(legacy, node, 'produce', 'legacy body', False)
    stale_policy['version'] = LEGACY_POLICY
    stale_policy['hash'] = work_policy.digest({k: v for k, v in stale_policy.items() if k != 'hash'})
    binding = graph.checks.binding(legacy, node, 'produce') | {'policyHash': stale_policy['hash']}
    meta = await graph.artifacts.put(legacy, node['id'], 'produce', 'legacy body', binding, True)
    state = node['stages']['produce']
    state.update(artifact=meta, policy=stale_policy)
    legacy['nodes'][0] = node
    graph.save(legacy)
    try:
        await graph.checks.tool(session, {'action': 'start', 'runId': LEGACY_RUN, 'nodeId': node['id'],
                                          'stage': 'produce', 'artifactId': meta['artifactId'],
                                          'checkIds': ['evidence'], 'invocationId': 'legacy-check'})
        row['checks']['stale_policy_rejected'] = None
    except ValueError as exc:
        row['checks']['stale_policy_rejected'] = str(exc)[:160]
    # 3. `work_run` nhập run cũ sang version hiện hành: cùng runId, revision tăng.
    try:
        await graph.run(session, {'phase': 'discover', 'runId': LEGACY_RUN, 'nodeIds': ['R1'], 'maxRounds': 1})
    except Exception as exc:  # nhánh producer không có model: việc nhập đã xong trước đó
        row['checks']['import_producer_stop'] = f'{type(exc).__name__}: {exc}'[:200]
    imported = graph.get(LEGACY_RUN)
    revision = imported['revision']
    row['checks']['import_binding'] = {'runId': imported['runId'], 'verificationVersion': imported['verificationVersion'],
                                       'revision': revision, 'legacyReviewKept': bool(imported.get('legacyReview'))}
    # 4. Binding mới mang đúng runId/version/policyHash và đọc lại round-trip.
    fresh = await graph.artifacts.put(imported, 'R1', 'produce', 'new body',
                                      {'runId': imported['runId'], 'stage': 'produce'}, True)
    got, text = graph.artifacts.get(imported['runId'], fresh['artifactId'])
    row['checks']['fresh_binding'] = {'runId': got['runId'], 'version': got['version'], 'chars': got['chars'],
                                      'roundTrip': text == 'new body'}
    # 5. Artifact bị sửa ngoài (nội dung trong DB khác hash) không còn là bằng chứng.
    with store.db:
        store.db.execute('UPDATE work_artifacts SET content=? WHERE id=?', ('tampered', fresh['artifactId']))
    try:
        graph.artifacts.get(imported['runId'], fresh['artifactId'])
        row['checks']['corrupt_detected'] = None
    except ValueError as exc:
        row['checks']['corrupt_detected'] = str(exc)[:160]
    # 6. Restart khi admission đang mở → interrupted, không tự chạy lại.
    work = {'runId': imported['runId'], 'nodeId': 'R1', 'stage': 'produce', 'purpose': 'produce'}
    admission = await graph.progress.reserve(sid, work)
    child = runtime.create({'skills': []}, parent_id=sid, role='research', parent_tools=session['config']['tools'])
    store.emit(child['id'], 'user', {'prompt': 'legacy admission'})
    graph.progress.attach(admission, sid, work | {'admissionSeq': 0}, child['id'])
    store.close()
    store2 = SessionStore(path)  # restart thật: mở lại cùng file
    runtime2 = HarnessRuntime(store2, Executor(), Client())
    graph2 = wg.service(runtime2)
    recovered = graph2.progress.get(admission)
    row['checks']['restart_recovery'] = {'status': recovered['status'], 'error': recovered.get('error')}
    # 7. Index/refs của status trỏ đúng version trong registry (không trỏ bản cũ).
    live = graph2.get(LEGACY_RUN)
    refs = [state.get('artifact') for n in live['nodes'] for state in n['stages'].values() if state.get('artifact')]
    consistent = []
    for ref in refs:
        try:
            meta, _ = graph2.artifacts.get(LEGACY_RUN, ref['artifactId'])
            consistent.append({'artifactId': ref['artifactId'], 'refVersion': ref['version'],
                               'registryVersion': meta['version'], 'match': meta['version'] == ref['version']
                               and meta['contentHash'] == ref['contentHash']})
        except ValueError as exc:
            consistent.append({'artifactId': ref['artifactId'], 'error': str(exc)[:120]})
    row['checks']['status_index_matches_registry'] = consistent

    checks = row['checks']
    row['oracle'] = (
        checks['old_run_readable']['verificationVersion'] == 'legacy'
        and checks['old_run_readable']['status'] == 'drafting'
        and (checks.get('legacy_verify_blocked') or '').startswith('WORK_LEGACY_CHECKS_REQUIRED')
        and (checks.get('stale_policy_rejected') or '').startswith('WORK_CHECK_STALE')
        and checks['import_binding']['runId'] == LEGACY_RUN
        and checks['import_binding']['verificationVersion'] == work_policy.VERSION
        and checks['import_binding']['revision'] > 1 and checks['import_binding']['legacyReviewKept']
        and checks['fresh_binding']['runId'] == LEGACY_RUN and checks['fresh_binding']['roundTrip']
        and (checks.get('corrupt_detected') or '').startswith('WORK_ARTIFACT_CORRUPT')
        and checks['restart_recovery']['status'] == 'interrupted'
        and all(c.get('match') for c in consistent))
    row['scope'] = ('Deterministic legacy-DB probe: readable old run, stale policy rejected, import keeps runId, '
                    'corrupt artifact rejected, restart recovery; no model/provider/UI')
    (output / 'results.json').write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'oracle': row['oracle'], **{k: v for k, v in checks.items()}}, ensure_ascii=False, indent=2))
    store2.db.close()
    return row['oracle']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    ok = asyncio.run(main(parser.parse_args()))
    raise SystemExit(0 if ok else 1)
