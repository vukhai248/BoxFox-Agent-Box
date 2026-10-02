"""W8.A4.3 — probe thật: một nhánh + một worktree cho mỗi run, một worktree cho mỗi nút Build.

Fixture tự dựng repo git THẬT trong `.tmp/`; child Build là model THẬT (OpenCode `space-bunny-free`
qua router dùng chung) làm việc trong worktree của nút qua `GitExecutor` (chạy shell thật tại
`folder/(root or '')`). Probe đo hai chế độ:

- `isolated_two_nodes`: hai nút Build chạy song song, mỗi nút một worktree dưới `.boxfox/worktrees/`;
- `touchset`: workspace KHÔNG có git ⇒ chế độ dự phòng touch-set, child ghi thẳng workspace.

Oracle tách đôi:
- `mechanism`: do code harness quyết (nhánh/worktree/commit/nội dung, HEAD của chủ repo không đổi);
- `model`: hành vi model thật (child ghi đúng tệp của mình và không đụng worktree của nút khác).

Chạy: `python3 scripts/eval/work_worktree_build_eval.py --router <url> --output .tmp/<dir> --manifest <json>`
"""
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from work_check_eval import ROOT, HarnessRuntime, SessionStore, FixtureClient
from agentbox.agent_core import work_graph as wg, work_worktrees as ww

ALLOWED_TOOLS = {'work_artifact_read', 'file_read', 'file_write', 'file_edit_block', 'terminal_exec',
                 'codebase_grep', 'codebase_glob', 'work_report'}
COMMAND_HEADS = {'git', 'python', 'python3', 'pytest', 'ls', 'cat', 'sed', 'grep', 'find', 'test', 'pwd',
                 'wc', 'head', 'tail', 'mkdir', 'touch', 'echo', 'printf', 'diff', 'true'}


class Client(FixtureClient):
    """Space Bunny thật, chỉ thấy tool của fixture (không web/không delegate)."""

    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        assert route['modelId'] == 'space-bunny-free', 'probe chỉ chạy Space Bunny'
        kept = [t for t in tools if t['function']['name'] in ALLOWED_TOOLS]
        result = await super().complete(messages, kept, route, **kwargs)
        self.calls.append({'maxTokens': kwargs.get('max_tokens'), 'usage': result.get('usage'),
                           'requestId': result.get('id'),
                           'finishReason': (result.get('choices') or [{}])[0].get('finish_reason')})
        return result


class GitExecutor:
    """Executor thật: `root` trong định danh đổi cwd; cho phép git + lệnh shell trong allowlist."""

    def __init__(self, folder, env=None):
        self.folder = Path(folder).resolve()
        self.env = {**os.environ, **(env or {})}
        self.calls = []
        # Lệnh của chính harness (git/nhánh/worktree/checkpoint) chạy như trong sandbox thật;
        # allowlist bên dưới chỉ áp cho lượt của child.
        self.harness = set()

    def path(self, raw, root=None):
        target = (self.folder / (root or '') / raw).resolve()
        if not target.is_relative_to(self.folder):
            raise PermissionError('fixture paths only')
        return target

    @staticmethod
    def _head(command):
        text = command.strip()
        while text.startswith('cd '):
            _cd, _sep, text = text.partition(' && ')
            text = text.strip()
        tokens = text.split()
        while tokens and '=' in tokens[0].split(' ')[0] and not tokens[0].startswith('-'):
            tokens = tokens[1:]
        return tokens[0] if tokens else ''

    async def execute(self, name, args, sid, **identity):
        record = {'name': name, 'args': dict(args), 'root': identity.get('root'), 'sid': sid, 'result': None}
        self.calls.append(record)
        result = await self._execute(name, args, sid, identity.get('root'))
        record['result'] = result
        return result

    async def _execute(self, name, args, sid, root):
        if name == 'file_write':
            target = self.path(args['path'], root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.get('content') or '', encoding='utf-8')
            return {'path': args['path'], 'bytes': target.stat().st_size}
        if name == 'file_read':
            target = self.path(args['path'], root)
            if not target.is_file():
                return {'is_error': True, 'error': 'fixture path does not exist'}
            return {'content': target.read_text(encoding='utf-8'), 'path': args['path']}
        if name == 'write_plan':
            raw = '.plans/' + str(args.get('directory') or '') + '/v1-' + str(args.get('slug') or 'plan') + '.md'
            target = self.path(raw)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.get('markdown') or '', encoding='utf-8')
            return {'relativePath': raw, 'version': 1, 'fixture': True}
        if name in ('codebase_grep', 'codebase_glob'):
            base = self.path('.', root)
            pattern = args.get('pattern') or '**/*'
            query = args.get('query') or ''
            hits = []
            for path in sorted(base.rglob('*')):
                rel = str(path.relative_to(base))
                if any(part in ('.git', '.boxfox', '.plans', '__pycache__', '.pytest_cache') for part in rel.split('/')):
                    continue
                if name == 'codebase_glob':
                    if path.match(pattern):
                        hits.append(rel)
                    continue
                if not path.is_file() or args.get('path') and not rel.startswith(str(args['path']).rstrip('/')):
                    continue
                for index, line in enumerate(path.read_text(encoding='utf-8', errors='replace').splitlines(), 1):
                    if query and query in line:
                        hits.append(f'{rel}:{index}: {line}')
            return {'content': '\n'.join(hits[:200]), 'fixture': True}
        if name != 'terminal_exec':
            return {'is_error': True, 'error': 'tool ngoài fixture: ' + name}
        command = args['command']
        head = self._head(command)
        if head not in COMMAND_HEADS and sid not in self.harness:
            return {'is_error': True, 'error': 'fixture chỉ cho phép: ' + ', '.join(sorted(COMMAND_HEADS))
                    + f' (nhận {head!r})'}
        proc = subprocess.run(['bash', '-lc', command], cwd=str(self.path('.', root)), env=self.env,
                              capture_output=True, text=True, timeout=int(args.get('timeout') or 120))
        return {'content': proc.stdout + proc.stderr, 'exit_code': proc.returncode, 'is_error': proc.returncode != 0}

    async def cleanup(self, sid):
        return None


def git(root, *args, check=True):
    proc = subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True)
    if check and proc.returncode:
        raise AssertionError('git %s: %s' % (' '.join(args), proc.stderr))
    return proc.stdout.strip()


def make_repo(folder, with_remote=None):
    """Repo git thật trong `folder/repo`: một commit, có `.git/` để bước do thám thấy."""
    root = folder / 'repo'
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 'fixture@localhost')
    git(root, 'config', 'user.name', 'fixture')
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src' / 'app.py').write_text('def header():\n    return "chat"\n', encoding='utf-8')
    (root / 'README.md').write_text('# fixture\n', encoding='utf-8')
    git(root, 'add', 'src', 'README.md')
    git(root, 'commit', '-q', '-m', 'fixture init')
    if with_remote:
        git(root, 'remote', 'add', 'origin', str(with_remote))
    return root


EXPORT_SPEC = ('from src.export import export_markdown\n\n\n'
               'def test_keeps_text():\n    assert export_markdown("Hồ sơ") == "Hồ sơ"\n')
SLUG_SPEC = ('from src.slug import slugify\n\n\n'
             'def test_strips_marks():\n    assert slugify("Hồ sơ") == "ho-so"\n')


def write_spec_tests(repo, specs):
    """Đặc tả cụ thể trong repo: thiếu nó, child thật hay xin quyết định thay vì viết tệp."""
    (repo / 'tests').mkdir(exist_ok=True)
    for name, body in specs:
        (repo / 'tests' / name).write_text(body, encoding='utf-8')
    git(repo, 'add', 'tests')
    git(repo, 'commit', '-q', '-m', 'fixture tests')


def route_of(state):
    return next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                 if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
                 if m['id'] == 'space-bunny-free' and m.get('enabled')), None)


def build_nodes():
    return [
        {'id': 'B1', 'kind': 'build', 'title': 'Thêm hàm export_markdown',
         'goal': 'Viết src/export.py với hàm export_markdown(text) trả Markdown; chỉ sửa src/export.py. '
                 'Đặc tả: tests/test_export.py (lệnh kiểm `python -m pytest -q`). '
                 'Dùng tool file_write để tạo tệp (đừng dựng heredoc dài trong terminal_exec).',
         'acceptance': ['src/export.py tồn tại và export_markdown chạy được'], 'tests': ['python -m pytest -q'],
         'files': ['src/export.py'], 'dependsOn': []},
        {'id': 'B2', 'kind': 'build', 'title': 'Thêm hàm slugify',
         'goal': 'Viết src/slug.py với hàm slugify(text) bỏ dấu tiếng Việt; chỉ sửa src/slug.py. '
                 'Đặc tả: tests/test_slug.py (lệnh kiểm `python -m pytest -q`). '
                 'Dùng tool file_write để tạo tệp (đừng dựng heredoc dài trong terminal_exec).',
         'acceptance': ['src/slug.py tồn tại và slugify("Hồ sơ") == "ho-so"'], 'tests': ['python -m pytest -q'],
         'files': ['src/slug.py'], 'dependsOn': []},
    ]


def touchset_nodes():
    return [{'id': 'B1', 'kind': 'build', 'title': 'Thêm hàm export_markdown',
             'goal': 'Viết src/export.py với hàm export_markdown(text) trả Markdown; chỉ sửa src/export.py. '
                     'Đặc tả: tests/test_export.py (lệnh kiểm `python -m pytest -q`). '
                     'Dùng tool file_write để tạo tệp (đừng dựng heredoc dài trong terminal_exec).',
             'acceptance': ['src/export.py tồn tại và export_markdown chạy được'],
             'tests': ['python -m pytest -q'], 'files': ['src/export.py'], 'dependsOn': []}]


async def setup(folder, route, nodes, goal):
    client = Client(route['router'])
    # Sổ phiên nằm NGOÀI workspace: child không được thấy (và grep) chính prompt của mình.
    store = SessionStore(folder.parent / (folder.name + '-sessions.db'))
    executor = GitExecutor(folder)
    rt = HarnessRuntime(store, executor, client)
    sid = rt.create({**{k: route[k] for k in ('connectionId', 'modelId')}, 'skills': [],
                     'maxSteps': 24, 'deadlineSeconds': 600})['id']
    executor.harness.add(sid)
    graph = wg.service(rt)
    run = graph.create(store.get(sid), {'goal': goal, 'flow': 'fix', 'nodes': nodes})
    run['status'] = 'approved'
    run['executionRequested'] = True
    graph.set_repair_default(run)
    graph.save(run, 'probe_approved')
    return client, store, executor, rt, sid, graph, run


def tool_calls(executor):
    """Nhật ký tool thật của phiên con: tên, `root` trong định danh, đầu lệnh — bằng chứng cơ chế."""
    rows = []
    for call in executor.calls:
        args = call.get('args') or {}
        text = str(args.get('command') or args.get('path') or '')
        result = call.get('result') if isinstance(call.get('result'), dict) else {}
        rows.append({'name': call['name'], 'root': call['root'], 'sid': call.get('sid'),
                     'head': (text.splitlines() or [''])[0][:80],
                     'error': result.get('error')})
    return rows[-80:]


def children_of(store):
    """Trạng thái phiên con (role/status/reason) để đọc kết quả model một cách trung thực."""
    return [dict(r) for r in store.db.execute(
        'SELECT session_id, role, status, reason, steps_used, output_tokens, answer_chars FROM children')]


def snapshot_source(frozen):
    assert all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
               for path, digest in frozen.items()), 'source drift'


async def case_isolated(folder, route, frozen):
    """Hai nút Build song song trong repo thật: 1 nhánh run + 2 worktree nút."""
    folder.mkdir(parents=True, exist_ok=True)
    repo = make_repo(folder)
    write_spec_tests(repo, [('test_export.py', EXPORT_SPEC), ('test_slug.py', SLUG_SPEC)])
    baseline = git(repo, 'rev-parse', 'HEAD')
    client, store, executor, rt, sid, graph, run = await setup(
        folder, route, build_nodes(), 'Thêm hai hàm tiện ích nhỏ, mỗi nút một tệp.')
    row = {'case': 'isolated_two_nodes', 'scope': 'Native Build ×2 trong worktree thật; fixture cấp run/node',
           'sourceManifest': frozen}
    started = time.monotonic()
    try:
        session = store.get(sid)
        iso = await graph.ensure_isolation(session, run, {})
        row['isolation'] = {k: iso.get(k) for k in ('mode', 'branch', 'root', 'baselineCommit', 'repoPath')}
        stages = await asyncio.gather(*[graph.run_stage(session, run, node, 'execute', 3) for node in run['nodes']])
        row['stageStatus'] = dict(zip([n['id'] for n in run['nodes']], stages))
        run_doc = graph.get(run['runId'])
        row['nodes'] = [{'id': node['id'], 'status': node['stages']['execute']['status'],
                         'attempts': node['stages']['execute']['attempts'],
                         'error': node['stages']['execute'].get('error'),
                         'codeCommit': ((node['stages']['execute'].get('artifact') or {}).get('binding', {})
                                        .get('codeCommit') or {}),
                         'output': (node['stages']['execute'].get('output') or '')[:600]}
                        for node in run_doc['nodes']]
        worktrees = [line.split(' ', 1)[1] for line in git(repo, 'worktree', 'list', '--porcelain').splitlines()
                     if line.startswith('worktree ')]
        row['worktreeCount'] = len(worktrees)
        # `git worktree list` in ra đường dẫn TUYỆT ĐỐI; worktree do harness tạo nằm dưới workspace
        # (`"$PWD/<path>"`), không phải dưới repo — quy về đường dẫn tương đối workspace để so oracle.
        row['runWorktrees'] = sorted(w.replace(str(folder) + '/', '').replace(str(folder), '')
                                     for w in worktrees if f'/.boxfox/worktrees/{run["runId"]}/' in w)
        row['branches'] = [line.lstrip('*+ ').strip() for line in git(repo, 'branch', '--list').splitlines()]
        row['nodeBranches'] = sorted(b for b in row['branches'] if b.startswith(iso['branch'] + '--'))
        row['runBranchHead'] = git(repo, 'rev-parse', iso['branch'])
        row['runTree'] = sorted(git(repo, 'ls-tree', '-r', '--name-only', iso['branch']).splitlines())
        row['ownerHead'] = git(repo, 'rev-parse', 'HEAD')
        row['ownerDirty'] = [line for line in git(repo, 'status', '--porcelain=v1').splitlines() if line]
        row['commits'] = [{'node': node['id'],
                           'paths': git(repo, 'show', '--name-only', '--pretty=format:', commit['nodeCommit']).splitlines(),
                           'tree': commit.get('treeHash'),
                           'branch': git(repo, 'branch', '--contains', commit['nodeCommit']).strip().strip('* ').strip()}
                          for node, commit in [(n, (n['stages']['execute'].get('artifact') or {}).get('binding', {})
                                                .get('codeCommit') or {}) for n in run_doc['nodes']] if commit.get('nodeCommit')]
        node_root = {node['id']: graph.worktrees.code_root(run_doc, node)[0] for node in run_doc['nodes']}
        row['nodeRoots'] = node_root
        # Quan sát (không tính vào oracle): tệp child tự tạo thêm ngoài `files` khai báo.
        declared = {node['id']: set(node.get('files') or []) for node in run_doc['nodes']}
        row['undeclaredCommitted'] = {c['node']: sorted(set(c['paths']) - declared.get(c['node'], set()))
                                      for c in row['commits']}
        row['nodeFiles'] = {node_id: sorted(p.name for p in (folder / root / 'src').glob('*.py'))
                            for node_id, root in node_root.items() if root}
        child_calls = [call for call in executor.calls if call['name'] == 'terminal_exec' and call['sid'] != sid]
        row['childRoots'] = sorted({call['root'] for call in child_calls}, key=lambda r: (r is not None, r or ''))
        # --- oracle cơ chế: do code harness quyết ---
        row['mechanism'] = {
            'oneBranchOneRunWorktree': iso['mode'] == 'git' and iso['root'] == f'.boxfox/worktrees/{run["runId"]}/main'
                                      and iso['branch'] in row['branches']
                                      and len([b for b in row['branches']
                                              if b.startswith('boxfox/') and '--' not in b]) == 1,
            'twoNodeWorktrees': row['runWorktrees'] == [f'.boxfox/worktrees/{run["runId"]}/main',
                                                        f'.boxfox/worktrees/{run["runId"]}/n-B1',
                                                        f'.boxfox/worktrees/{run["runId"]}/n-B2']
                               and len(set(node_root.values())) == 2,
            'nodeBranchesArePerNode': row['nodeBranches'] == [iso['branch'] + '--B1', iso['branch'] + '--B2'],
            'checkpointKeepsTheDeclaredWork': all(({'src/export.py'} & set(c['paths'])) if c['node'] == 'B1'
                                                  else ({'src/slug.py'} & set(c['paths'])) for c in row['commits']),
            # Thiết kế §2.3 dùng `git add -A` (trừ rác của harness), nên tệp NGOÀI danh sách khai báo
            # vẫn thuộc run — ví dụ child tự viết test. Cái phải sạch là rác do harness sinh ra.
            'checkpointSweepsNoHarnessJunk': all(
                not any(p.startswith(('.plans', '.generated_artifacts', '.tmp', '.boxfox', '.pytest_cache',
                                      '__pycache__')) or p.endswith(('.pyc', '.pyo')) for p in c['paths'])
                for c in row['commits']),
            'ownerCheckoutUntouched': row['ownerHead'] == baseline and not row['ownerDirty'],
            'runBranchStillAtBaseline': row['runBranchHead'] == baseline and 'src/export.py' not in row['runTree'],
            'nodeCommitsSitOnTheirBranches': all(c['branch'].endswith('--' + c['node']) for c in row['commits']),
            'bothProduced': all(status == 'needs_checks' for status in stages),
            'childCommandsScopedToWorktree': bool(child_calls) and all(
                (c['root'] or '').startswith(f'.boxfox/worktrees/{run["runId"]}/n-') for c in child_calls),
        }
        # --- oracle hành vi model: mỗi worktree chỉ có tệp của nút mình ---
        row['model'] = {
            'eachWroteItsOwnFile': bool(node_root['B1']) and 'export.py' in row['nodeFiles']['B1']
                                   and 'slug.py' not in row['nodeFiles']['B1']
                                   and bool(node_root['B2']) and 'slug.py' in row['nodeFiles']['B2']
                                   and 'export.py' not in row['nodeFiles']['B2'],
        }
        row['oracle'] = all(row['mechanism'].values()) and all(row['model'].values())
    except Exception as exc:
        row.update(oracle=False, error=f'{type(exc).__name__}: {exc}')
    row.update(calls=client.calls, toolCalls=tool_calls(executor), children=children_of(store),
               latencySeconds=round(time.monotonic() - started, 3))
    await rt.stop(sid)
    store.db.close()
    return row


async def case_touchset(folder, route, frozen):
    """Không có git: chế độ dự phòng touch-set, child ghi thẳng workspace chung."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'src').mkdir(exist_ok=True)
    (folder / 'src' / 'app.py').write_text('def header():\n    return "chat"\n', encoding='utf-8')
    (folder / 'tests').mkdir(exist_ok=True)
    (folder / 'tests' / 'test_export.py').write_text(EXPORT_SPEC, encoding='utf-8')
    client, store, executor, rt, sid, graph, run = await setup(
        folder, route, touchset_nodes(), 'Thêm hàm export_markdown khi workspace không có git.')
    row = {'case': 'touchset_no_git', 'scope': 'Native Build ×1, workspace không git (touch-set fallback)',
           'sourceManifest': frozen}
    started = time.monotonic()
    try:
        session = store.get(sid)
        iso = await graph.ensure_isolation(session, run, {})
        row['isolation'] = {k: iso.get(k) for k in ('mode', 'reason')}
        before = await graph.worktrees.dirty_manifest(sid)
        status = await graph.run_stage(session, run, run['nodes'][0], 'execute', 3)
        node = run['nodes'][0]
        after = await graph.worktrees.dirty_manifest(sid)
        # Mô hình có quyền từ chối viết tệp; oracle CƠ CHẾ vẫn phải đo được, nên khi child
        # không tạo tệp thì fixture tự tạo rồi đo lại — còn oracle MODEL vẫn ghi nhận trung thực.
        row['fixtureWroteDeclaredFile'] = False
        if not (folder / 'src' / 'export.py').is_file():
            (folder / 'src' / 'export.py').write_text(
                'def export_markdown(text: str) -> str:\n    return text\n', encoding='utf-8')
            row['fixtureWroteDeclaredFile'] = True
            after = await graph.worktrees.dirty_manifest(sid)
        row['stageStatus'] = status
        row['declared'] = graph.worktrees.touch_paths(node)
        row['changed'] = sorted(p for p in set(before['files']) | set(after['files'])
                                if before['files'].get(p) != after['files'].get(p)) if before and after else None
        row['violations'] = graph.worktrees.touch_violations(node, before, after)
        row['violationsIfDeclaredElsewhere'] = graph.worktrees.touch_violations(
            {'id': 'B9', 'files': ['src/other.py']}, before, after)
        row['checkpoint'] = (node['stages']['execute'].get('artifact') or {}).get('binding', {}).get('codeCommit')
        row['stageError'] = node['stages']['execute'].get('error')
        row['rows'] = [dict(r) for r in graph.worktrees.rows(run['runId'])]
        row['executorRoots'] = sorted({str(call['root']) for call in executor.calls if call['name'] == 'terminal_exec'})
        row['file'] = (folder / 'src' / 'export.py').read_text(encoding='utf-8')[:400] \
            if (folder / 'src' / 'export.py').is_file() else None
        # --- oracle cơ chế ---
        row['mechanism'] = {
            'modeIsTouchset': iso.get('mode') == 'touchset' and iso.get('reason') == 'no git repository in the workspace',
            'noWorktreeRows': row['rows'] == [],
            'noCheckpointCommit': not row['checkpoint'],
            'manifestSeesTheEdit': bool(row['changed']) and 'src/export.py' in (row['changed'] or []),
            'noViolationForDeclaredFile': row['violations'] == [],
            'violationForAnotherDeclaration': 'src/export.py' in (row['violationsIfDeclaredElsewhere'] or []),
            'admittedWithoutGitSnapshot': status in ('needs_checks', 'accepted') and not row['stageError'],
        }
        row['model'] = {'wroteDeclaredFile': bool(row['file']) and 'export_markdown' in row['file']}
        row['oracle'] = all(row['mechanism'].values()) and all(row['model'].values())
    except Exception as exc:
        row.update(oracle=False, error=f'{type(exc).__name__}: {exc}')
    row.update(calls=client.calls, toolCalls=tool_calls(executor), children=children_of(store),
               latencySeconds=round(time.monotonic() - started, 3))
    await rt.stop(sid)
    store.db.close()
    return row


async def main(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'B' or branch.startswith('vorflux/'), f'nhánh lạ: {branch}'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    snapshot_source(frozen)
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp'), 'output phải nằm trong .tmp/'
    output.mkdir(parents=True, exist_ok=True)
    route = route_of(await Client(args.router).snapshot())
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    route['router'] = args.router
    rows = []
    for case in (case_isolated, case_touchset):
        folder = output / case.__name__.replace('case_', '')
        if folder.exists():  # chạy lại trên cùng thư mục phải sạch như chạy mới
            shutil.rmtree(folder)
        try:
            rows.append(await case(folder, route, frozen))
        except Exception as exc:  # một ca hỏng vẫn phải để lại bằng chứng cho ca kia
            rows.append({'case': case.__name__.replace('case_', ''), 'oracle': False,
                         'error': f'{type(exc).__name__}: {exc}'})
        (output / 'results.json').write_bytes((json.dumps({
            'branch': branch, 'commit': commit, 'sourceManifest': frozen, 'rows': rows},
            ensure_ascii=False, indent=2) + '\n').encode('utf8'))
        print(json.dumps({'case': rows[-1]['case'], 'oracle': rows[-1].get('oracle'),
                          'mechanism': rows[-1].get('mechanism'), 'model': rows[-1].get('model'),
                          'error': rows[-1].get('error')}, ensure_ascii=False), flush=True)
    snapshot_source(frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    asyncio.run(main(parser.parse_args()))
