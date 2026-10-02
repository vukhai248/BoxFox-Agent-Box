"""W8.A4.4 — probe thật: ship chỉ đẩy nhánh run (và chỉ đường dẫn thuộc run), idempotent.

Fixture: repo git thật + remote bare + shim `gh` (ghi log) trong `.tmp/`. Chủ repo cố ý có tệp
đang sửa dở (`dirty`). Nút Build do fixture bàn giao (code đã nằm trong worktree nút), còn hai
lượt kiểm của nút tổng hợp (`tests` rồi `code_review`) là child THẬT của Space Bunny chạy trong
worktree nhánh run. Sau đó `work_ship` chạy hai lần.

Oracle tách đôi:
- `mechanism`: một lần push, một PR, chỉ đường dẫn thuộc run, ship lần hai dùng lại bản ghi;
- `model`: child kiểm thật sự chạy lệnh trong worktree nhánh run và báo kết quả thật.

Chạy: `python3 scripts/eval/work_ship_scoped_eval.py --router <url> --output .tmp/<dir> --manifest <json>`
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import time
import traceback
import uuid
from pathlib import Path

from work_check_eval import ROOT, SessionStore
from work_worktree_build_eval import (Client, GitExecutor, build_nodes, git, make_repo, route_of,
                                      snapshot_source)
from agentbox.agent_core import work_graph as wg, work_checks, work_policy, work_worktrees as ww

GH_SHIM = '''#!/bin/sh
printf '%s\\n' "$*" >> "$GH_LOG"
case "$1 $2" in
  "auth status") echo "Logged in to github.com as fixture"; exit 0 ;;
  "pr view") echo "no pull requests found for branch"; exit 1 ;;
  "pr create") echo "https://github.com/fixture/repo/pull/7"; exit 0 ;;
esac
exit 0
'''

TEST_FILE = '''import csv
import io
import sys

from src.export import export_markdown


def test_unicode_round_trip():
    assert export_markdown("Hồ sơ") == "Hồ sơ"
'''


class ShipExecutor(GitExecutor):
    """Như `GitExecutor` nhưng PATH có shim `gh` để đo số lần gọi (qua env, không vá câu lệnh)."""

    def __init__(self, folder, shim, log):
        super().__init__(folder, env={'PATH': str(shim) + os.pathsep + os.environ.get('PATH', ''),
                                      'GH_LOG': str(log)})


def make_origin(folder):
    origin = folder / 'origin.git'
    subprocess.run(['git', 'init', '--bare', '-q', str(origin)], check=True)
    return origin


def write_shim(folder):
    bin_dir = folder / 'bin'
    bin_dir.mkdir(exist_ok=True)
    log = folder / 'gh.log'
    shim = bin_dir / 'gh'
    shim.write_text(GH_SHIM, encoding='utf-8')
    shim.chmod(0o755)
    os.environ['GH_LOG'] = str(log)
    return bin_dir, log


async def handoff_artifact(graph, run, node, text, sid):
    """Fixture bàn giao: code đã nằm trong worktree nút, checkpoint + artifact + policy như producer thật."""
    state = node['stages']['execute']
    policy = work_policy.derive(run, node, 'execute', text, changed=True)
    root, base = graph.worktrees.code_root(run, node)
    # Đúng thứ tự producer thật: checkpoint TRƯỚC rồi mới chụp snapshot (checkpoint tạo commit mới
    # nên `head` đổi; chụp trước sẽ khiến lượt kiểm sau bị coi là 'Code changed before check').
    commit = await graph.worktrees.checkpoint(run, node, 1, sid)
    source = await work_checks.snapshot(graph, sid, root, base)
    assert source, 'fixture phải chụp được worktree nút'
    binding = graph.checks.binding(run, node, 'execute') | {'policyHash': policy['hash'],
        'codeSnapshot': source, 'codeCommit': commit,
        'workspace': {'root': root, 'branch': commit['branch'], 'base': base}}
    meta = await graph.artifacts.put(run, node['id'], 'execute', text, binding, True)
    state.update(status='needs_checks', attempts=1, policy=policy, artifact=meta, checkpoint=commit,
                 rounds=state['rounds'] + [{'attempt': 1, 'producerRole': 'build', 'at': time.time()}])
    graph.save(run)
    return meta


async def main(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'B' or branch.startswith('vorflux/'), f'nhánh lạ: {branch}'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    snapshot_source(frozen)
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp')
    output.mkdir(parents=True, exist_ok=True)
    route = route_of(await Client(args.router).snapshot())
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    route['router'] = args.router

    folder = output / 'scoped_ship'
    # Chạy lại trên cùng thư mục phải cho kết quả như chạy mới: dọn repo/remote của lượt trước.
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    origin = make_origin(folder)
    shim, gh_log = write_shim(folder)
    repo = make_repo(folder, with_remote=origin)
    (repo / 'tests').mkdir(exist_ok=True)
    (repo / 'tests' / 'test_export.py').write_text(TEST_FILE, encoding='utf-8')
    git(repo, 'add', 'tests/test_export.py')
    git(repo, 'commit', '-q', '-m', 'fixture test')
    baseline = git(repo, 'rev-parse', 'HEAD')
    # Chủ repo đang sửa dở một tệp KHÔNG thuộc run: nó phải ở lại ngoài nhánh run.
    (repo / 'README.md').write_text('# fixture\n\nđang sửa dở\n', encoding='utf-8')

    row = {'case': 'scoped_ship_dirty_owner', 'sourceManifest': frozen,
           'scope': 'Fixture bàn giao Build; 2 lượt kiểm Space Bunny thật (tests + code_review); ship thật tới bare origin + gh shim'}
    started = time.monotonic()
    store = SessionStore(folder.parent / 'scoped_ship-sessions.db')
    client = Client(args.router)
    rt = sid = None
    try:
        from work_check_eval import HarnessRuntime
        executor = ShipExecutor(folder, shim, gh_log)
        rt = HarnessRuntime(store, executor, client)
        sid = rt.create({**{k: route[k] for k in ('connectionId', 'modelId')}, 'skills': [],
                         'maxSteps': 24, 'deadlineSeconds': 600})['id']
        executor.harness.add(sid)
        graph = wg.service(rt)
        session = store.get(sid)
        run = graph.create(session, {'goal': 'Thêm export_markdown giữ dấu tiếng Việt, ship nhánh run.',
                                     'flow': 'fix', 'nodes': build_nodes()[:1]})
        run['status'] = 'approved'
        run['executionRequested'] = True
        graph.set_repair_default(run)
        graph.save(run, 'probe_approved')
        node = run['nodes'][0]
        iso = await graph.ensure_isolation(session, run, {})
        workspace = await graph.ensure_workspace(run, node, sid)
        # Worktree do harness tạo nằm dưới WORKSPACE (`$PWD/<root>`), không phải dưới repo.
        node_worktree = folder / workspace['root']
        target = node_worktree / 'src' / 'export.py'
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('def export_markdown(text):\n    return text\n', encoding='utf-8')
        subprocess.run(['git', '-C', str(node_worktree), 'add', 'src/export.py'], check=True)
        subprocess.run(['git', '-C', str(node_worktree), '-c', 'user.name=fixture',
                        '-c', 'user.email=fixture@localhost', 'commit', '-qm', 'fixture handoff'], check=True)
        row['nodeRoot'] = workspace['root']
        meta = await handoff_artifact(graph, run, node,
                                     '# Bàn giao fixture\nĐã thêm src/export.py giữ nguyên chuỗi.\n'
                                     'Chạy đúng lệnh kiểm `python -m pytest -q` (đừng thêm ống/`echo` bao ngoài).\n', sid)
        row['artifact'] = meta['artifactId']
        # Lượt kiểm `tests` của nút Build là child THẬT (pytest trong worktree nút). Child hay chạy
        # lệnh kèm ống (`python -m pytest -q 2>&1 | tail -20`) nên `test_proof` — vốn đòi khớp ĐÚNG
        # câu lệnh — trả `unverified`; thử lại có giới hạn như sản phẩm vẫn cho phép, ghi từng lượt.
        for attempt in range(1, 4):
            node_result = await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'],
                'nodeId': node['id'], 'stage': 'execute', 'artifactId': meta['artifactId'],
                'checkIds': ['tests'], 'invocationId': uuid.uuid4().hex})
            node_doc = node_result['checks'][0]
            row.setdefault('nodeChecks', []).append({'kind': node_doc['kind'], 'status': node_doc['status'],
                'attempt': attempt, 'childId': node_doc.get('childId'), 'error': node_doc.get('error'),
                'commands': [item.get('args', {}).get('command') for item
                             in work_checks.observations(graph, node_doc.get('childId'))
                             if item.get('name') == 'terminal_exec'][:16]})
            if node_doc['status'] == 'pass':
                break
        row['nodeCheck'] = row['nodeChecks'][-1]
        node = graph.find_node(graph.get(run['runId']), node['id'])
        row['nodeStatus'] = node['stages']['execute']['status']
        if row['nodeStatus'] != 'accepted':
            raise AssertionError(f"WORK_NODE_NOT_ACCEPTED: {row['nodeStatus']} "
                                 f"attempts={[c['status'] for c in row['nodeChecks']]}")
        # Như `require_execution` thật: đọc lại run từ store trước khi hợp nhất/so cây.
        run = graph.get(run['runId'])
        merged = await graph.integrate_nodes(session, run)
        row['merged'] = merged
        row['isolationRow'] = {k: (run.get('isolation') or {}).get(k)
                               for k in ('mode', 'root', 'branch', 'baselineCommit')}
        probe_snap = await graph.worktrees.integration_snapshot(run, sid)
        row['integrationSnapshotProbe'] = {k: probe_snap.get(k)
                                           for k in ('hash', 'head', 'treeHash', 'branch', 'worktree')}
        built = await graph.build_integration(session, run)
        row['integrationBuilt'] = built
        run_doc = graph.get(run['runId'])
        row['integrationStage'] = {k: (run_doc.get('integration') or {}).get('stage', {}).get(k)
                                   for k in ('status', 'error')}
        # Cổng review hội tụ chỉ đọc artifact. Lượt chạy đầu cho thấy reviewer trả `revise` với
        # đúng một finding chặn: artifact tích hợp không kèm output test nào. Producer thật phải
        # kèm bằng chứng chạy thật, nên fixture chạy THẬT pytest trên worktree nhánh run rồi đưa
        # nguyên văn output vào artifact trước khi admit hai lượt kiểm của nút tổng hợp.
        run_doc = graph.get(run['runId'])
        integration = graph.integration_node(run_doc)
        state = integration['stages']['execute']
        if not state.get('artifact'):
            raise AssertionError(f"WORK_INTEGRATION_ARTIFACT_MISSING: built={built} "
                                 f"stage={row['integrationStage']}")
        ok, pytest_out = await graph.worktrees.sh(
            sid, f"cd {ww.q(run['isolation']['root'])} && python3 -m pytest -q 2>&1; echo \"EXIT=$?\"")
        row['pytestEvidence'] = {'ok': ok, 'tail': pytest_out[-200:]}
        stage_meta, stage_text = graph.artifacts.get(run['runId'], state['artifact']['artifactId'])
        evidence = (stage_text + '\n\n## Bằng chứng chạy test (nguyên văn, đúng worktree nhánh run)\n\n'
                    f'`cd {run["isolation"]["root"]} && python3 -m pytest -q`\n\n```\n{pytest_out[-3000:]}\n```\n')
        meta = await graph.artifacts.put(run_doc, ww.INTEGRATION_NODE, 'execute', evidence,
                                        stage_meta['binding'], True, None)
        state['artifact'] = meta
        graph.save(run_doc, 'probe_integration_evidence')
        row['integrationEvidence'] = {'artifactId': meta['artifactId'], 'chars': meta['chars']}
        for check_id in ('tests', 'code_review'):
            # Cổng `tests` đòi child chạy ĐÚNG lệnh bắt buộc (`test_proof` so khớp cả câu lệnh);
            # child thật có lượt chạy lệnh kèm `echo` bao ngoài nên không được tính. Thử lại có
            # giới hạn và ghi trung thực từng lượt, không nới quy tắc bằng chứng của sản phẩm.
            attempts = 3 if check_id == 'tests' else 1
            for attempt in range(1, attempts + 1):
                result = await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'],
                    'nodeId': ww.INTEGRATION_NODE, 'stage': 'execute', 'artifactId': meta['artifactId'],
                    'checkIds': [check_id], 'invocationId': uuid.uuid4().hex})
                doc = result['checks'][0]
                row.setdefault('checks', []).append({'kind': doc['kind'], 'status': doc['status'],
                    'attempt': attempt, 'childId': doc.get('childId'), 'error': doc.get('error'),
                    'commands': [item.get('args', {}).get('command') for item in work_checks.observations(graph, doc.get('childId'))
                                 if item.get('name') == 'terminal_exec'][:12]})
                if doc['status'] == 'pass':
                    break
        # Chờ cổng hội tụ ổn định (một lượt sửa có thể chạy nền trước khi quyết định).
        settle = time.monotonic() + 300
        while time.monotonic() < settle:
            run_doc = graph.get(run['runId'])
            stage_status = ((run_doc.get('integration') or {}).get('stage') or {}).get('status')
            if (run_doc.get('integration') or {}).get('status') == 'checked' or stage_status in ('failed', 'rejected'):
                break
            await asyncio.sleep(5)
        run_doc = graph.get(run['runId'])
        row['runStatus'] = run_doc['status']
        row['integration'] = {k: run_doc['integration'].get(k) for k in ('status', 'treeHash', 'head')}
        row['integrationRepairs'] = [dict(r) for r in
                                     ((run_doc['integration'].get('stage') or {}).get('repairs') or [])]
        if row['integration']['status'] != 'checked':
            raise AssertionError(f"WORK_REVIEW_NOT_CONVERGED: run={row['runStatus']} "
                                 f"integration={row['integration']} checks="
                                 f"{[(c['kind'], c['status']) for c in row['checks']]}")
        # Ship lần 1 (đẩy nhánh + PR nháp), rồi ship lần 2 (phải dùng lại bản ghi).
        first = await graph.ship(session, {'runId': run['runId']})
        row['ship'] = {k: first['ship'].get(k) for k in ('status', 'branch', 'pushed', 'prUrl', 'commit',
                                                         'treeHash', 'shipKey')}
        row['ownedPaths'] = first['ship'].get('ownedPaths')
        log_after_first = gh_log.read_text(encoding='utf-8').splitlines() if gh_log.exists() else []
        remote_refs = git(origin, 'show-ref', '--heads')
        pushed_tree = git(origin, 'ls-tree', '-r', '--name-only', first['ship']['branch'])
        pushed_commit = git(origin, 'rev-parse', first['ship']['branch'])
        run_doc = graph.get(run['runId'])
        run_doc['status'] = 'executed'  # ship đã đóng run; gọi lại để đo tính idempotent
        graph.save(run_doc, 'probe_reopen')
        second = await graph.ship(store.get(sid), {'runId': run['runId']})
        log_after_second = gh_log.read_text(encoding='utf-8').splitlines() if gh_log.exists() else []
        row['shipAgain'] = {k: second['ship'].get(k) for k in ('status', 'shipKey', 'prUrl', 'commit')}
        row['ghCalls'] = {'first': log_after_first, 'second': log_after_second}
        row['prBody'] = (folder / (first['ship'].get('prFile') or '')).read_text(encoding='utf-8')[:2000] \
            if first['ship'].get('prFile') else None
        row['ownerDirty'] = [line for line in git(repo, 'status', '--porcelain=v1').splitlines() if line]
        row['ownerHead'] = git(repo, 'rev-parse', 'HEAD')
        # --- oracle cơ chế ---
        row['mechanism'] = {
            'runIsExecuted': run_doc['status'] in ('executed', 'shipped') and row['integration']['status'] == 'checked',
            'pushedExactlyOnce': len(remote_refs.splitlines()) == 1
                                 and first['ship']['branch'] in remote_refs and first['ship']['pushed'] is True,
            'onePrCreated': sum(1 for line in log_after_first if line.startswith('pr create')) == 1
                            and (first['ship'].get('prUrl') or '').endswith('/pull/7'),
            'pushedTreeIsCheckedTree': pushed_commit == row['integration']['head']
                                        and pushed_tree == git(origin, 'ls-tree', '-r', '--name-only',
                                                               row['integration']['head']),
            'onlyRunOwnedPaths': sorted(row['ownedPaths'] or []) == ['src/export.py'],
            'ownerDirtyStaysOut': any('README.md' in line for line in row['ownerDirty'])
                                  and git(origin, 'show', f"{first['ship']['branch']}:README.md")
                                      == git(repo, 'show', f'{baseline}:README.md')
                                  and row['ownerHead'] == baseline,
            'prBodyNamesOwnedFiles': 'src/export.py' in (row['prBody'] or '')
                                     and 'Files owned by this run' in (row['prBody'] or ''),
            'secondShipIsIdempotent': row['shipAgain']['shipKey'] == row['ship']['shipKey']
                                      and log_after_second == log_after_first,
        }
        # --- oracle hành vi model ---
        # Đếm theo TỪNG lần thử, không gộp: child kiểm thử hay chạy lệnh kèm ống nên `test_proof`
        # (đòi khớp đúng câu lệnh) trả `unverified` ở lần đầu; oracle model ghi trung thực số lần
        # thử và kết quả CUỐI của từng lượt kiểm.
        attempts = {}
        final = {}
        for item in row.get('checks', []):
            attempts[item['kind']] = attempts.get(item['kind'], 0) + 1
            final[item['kind']] = item['status']
        row['integrationCheckAttempts'] = attempts
        row['model'] = {
            'nodeCheckPassed': (row.get('nodeCheck') or {}).get('status') == 'pass',
            'integrationChecksEventuallyPassed': final == {'tests': 'pass', 'code_review': 'pass'},
            'testerRanRealCommand': any('pytest' in (command or '') for command in
                                        [c for check in row.get('nodeChecks', []) for c in check['commands']]
                                        + ((row.get('checks') or [{}])[0].get('commands') or [])),
        }
        row['oracle'] = all(row['mechanism'].values()) and all(row['model'].values())
    except Exception as exc:
        row.update(oracle=False, error=f'{type(exc).__name__}: {exc}',
                   traceback=traceback.format_exc()[-2000:])
    row.update(calls=client.calls, latencySeconds=round(time.monotonic() - started, 3))
    if rt is not None and sid:
        await rt.stop(sid)
    store.db.close()
    (output / 'results.json').write_bytes((json.dumps({'branch': branch, 'commit': commit,
        'sourceManifest': frozen, 'rows': [row]}, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    print(json.dumps({k: row.get(k) for k in ('case', 'oracle', 'mechanism', 'model', 'error',
                                              'latencySeconds')}, ensure_ascii=False), flush=True)
    snapshot_source(frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    asyncio.run(main(parser.parse_args()))
