"""W8.A4.3 — mỗi lần chạy một nhánh + worktree, mỗi nút Build một worktree, khoá touch-set dự phòng.

Bài này dựng một repo git THẬT trong `tmp_path` (máy chủ nhà không có `/home/agent/workspace`) và
một executor mỏng chạy lệnh bằng `bash -lc` tại workspace — đúng cách box chạy lệnh. Nhờ vậy nó
khoá được những luật chỉ đúng khi có git thật:

- `work_run phase=execute` cấp ĐÚNG MỘT nhánh `boxfox/<slug>-<id>` và MỘT worktree cho run, ghi
  lại `run['isolation']` kèm baseline; gọi lại lần nữa không tạo thêm nhánh/worktree;
- mỗi nút Build nhận một worktree RIÊNG dưới `.boxfox/worktrees/w-<run>/n-<node>` và mọi lượt con
  của nó (kể cả người kiểm thử/người phản biện) chạy với `root` = worktree đó;
- checkpoint chỉ commit đường dẫn của nút (`.plans`, `.generated_artifacts`, `.tmp`, `.boxfox`
  không bao giờ lọt vào commit của run);
- khi workspace không có repo git, chế độ `touchset` giữ nguyên hành vi cũ và khoá touch-set chặn
  hai nút cùng ghi một đường dẫn.
"""
import asyncio
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from agentbox.agent_core import work_graph as wg, work_worktrees as ww
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_work_graph import EXPLORE, PLAN, Model, ok_script, raw_tool, tool

BUILD = {'id': 'B1', 'kind': 'build', 'title': 'Add export button', 'goal': 'Implement the export button in the chat header',
         'dependsOn': ['P1'], 'acceptance': ['button exports markdown'], 'tests': ['vitest ChatHeader.test.tsx']}


def git(root, *args, check=True):
    proc = subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True)
    if check and proc.returncode:
        raise AssertionError('git %s: %s' % (' '.join(args), proc.stderr))
    return proc.stdout.strip()


def make_repo(workspace, name='repo'):
    """Repo git thật trong `<workspace>/<name>`: một commit, có `.git/` để bước do thám thấy."""
    root = Path(workspace) / name
    root.mkdir(parents=True, exist_ok=True)
    git(root, 'init', '-q', '-b', 'main')
    git(root, 'config', 'user.email', 'box@example.com')
    git(root, 'config', 'user.name', 'Box')
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src' / 'app.py').write_text('def header():\n    return "chat"\n', encoding='utf-8')
    git(root, 'add', '.')
    git(root, 'commit', '-q', '-m', 'init')
    return root


class RealExecutor:
    """Chạy lệnh thật tại workspace; `root` trong định danh đổi cwd như `select_root` của worker."""

    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.calls = []

    def roots(self, name='terminal_exec'):
        return [identity.get('root') for tool_name, args, identity in self.calls if tool_name == name]

    async def execute(self, name, args, sid, **identity):
        self.calls.append((name, dict(args), dict(identity)))
        if name == 'write_plan':
            room = self.workspace / '.plans' / (args.get('directory') or '')
            room.mkdir(parents=True, exist_ok=True)
            version = int(args.get('version') or (len(list(room.glob('v*-' + args['slug'] + '.md'))) + 1))
            target = room / f"v{version}-{args['slug']}.md"
            target.write_text(args.get('markdown') or '', encoding='utf-8')
            return {'relativePath': str(target.relative_to(self.workspace)), 'version': version}
        if name == 'file_write':
            target = self.workspace / identity['root'] / args['path'] if identity.get('root') \
                else self.workspace / args['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(args.get('content') or '', encoding='utf-8')
            return {'path': args['path'], 'bytes': len(args.get('content') or '')}
        if name != 'terminal_exec':
            return {'content': 'observed fixture result'}
        cwd = self.workspace / identity['root'] if identity.get('root') else self.workspace
        command = args['command']
        # Lệnh của dự án (không có trên máy chủ nhà) trả về như box giả của các bài cũ.
        if command.split(' ', 1)[0] in ('vitest', 'npm', 'npx', 'pnpm', 'yarn'):
            return {'content': 'ok', 'exit_code': 0, 'is_error': False}
        proc = subprocess.run(['bash', '-lc', command], cwd=str(cwd), capture_output=True, text=True)
        return {'content': proc.stdout, 'exit_code': proc.returncode, 'is_error': proc.returncode != 0}

    async def cleanup(self, sid):
        return None


def build(tmp_path, script=ok_script, model=None):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    store = SessionStore(tmp_path / 'sessions.db')
    model = model if model is not None else Model(script)
    executor = RealExecutor(workspace)
    runtime = HarnessRuntime(store, executor, model)
    sid = runtime.create({'skills': []})['id']
    return store, runtime, model, executor, sid, workspace


async def execute_run(runtime, sid, nodes=None):
    """Duyệt đồ thị, tự chạy kiểm cho mọi nút (kể cả nút tổng hợp) rồi chạy pha execute."""
    await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button'})
    await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': nodes or [EXPLORE, PLAN]})
    await tool(runtime, sid, 'work_run', {'phase': 'discover'})
    await tool(runtime, sid, 'work_graph', {'action': 'verify'})
    await tool(runtime, sid, 'work_graph', {'action': 'submit'})
    executed = await tool(runtime, sid, 'work_run', {'phase': 'execute'})
    service = wg.service(runtime)
    for _ in range(8):
        run = service.get(executed['runId'])
        node = service.integration_node(run)
        state = node['stages']['execute']
        if state.get('status') in ('needs_checks', 'revise'):
            passed = {kind for kind, doc in service.checks.latest(run, node, 'execute').items()
                      if doc['status'] == 'pass'}
            todo = [r['id'] for r in state['policy']['required'] if r['id'] not in passed]
            await raw_tool(runtime, sid, 'work_check', {'action': 'start', 'runId': run['runId'],
                                                        'nodeId': ww.INTEGRATION_NODE, 'stage': 'execute',
                                                        'artifactId': state['artifact']['artifactId'],
                                                        'checkIds': todo[:1], 'invocationId': uuid.uuid4().hex})
            continue
        if (run.get('integration') or {}).get('status') == 'checked':
            break
        executed = await tool(runtime, sid, 'work_run', {'phase': 'execute'})
    return service.get(executed['runId'])


def test_run_gets_one_branch_and_one_worktree(tmp_path):
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    repo = make_repo(workspace)
    wg.set_autopilot(runtime, sid, True)

    async def run():
        return await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])

    result = asyncio.run(run())
    service = wg.service(runtime)
    run_doc = service.get(result['runId'])
    iso = run_doc['isolation']
    assert iso['mode'] == 'git' and iso['repoPath'] == 'repo'
    assert iso['branch'] == f"boxfox/{run_doc['slug']}-{run_doc['runId'][2:8]}"
    assert iso['baselineCommit'] == git(repo, 'rev-parse', 'HEAD')
    assert iso['root'] == f".boxfox/worktrees/{run_doc['runId']}/main"
    assert (workspace / iso['root']).is_dir() and (workspace / iso['root'] / '.git').is_file()
    # Nhánh của run tồn tại THẬT trong repo và worktree đã đăng ký với git.
    assert iso['branch'] in git(repo, 'branch', '--list', '--format=%(refname:short)').splitlines()
    assert str(workspace / iso['root']) in git(repo, 'worktree', 'list', '--porcelain')
    # Nút Build có worktree riêng; con của nó chạy đúng trong đó.
    node_root = service.workspace_of(run_doc, run_doc['nodes'][-1])['root']
    assert node_root == f".boxfox/worktrees/{run_doc['runId']}/n-B1"
    assert (workspace / node_root / '.git').is_file()
    assert node_root in executor.roots()
    # Nút tổng hợp kiểm trên cây đã hợp nhất của nhánh run, không phải cây của nút nào.
    integration = run_doc['integration']
    assert integration['status'] == 'checked'
    assert integration['head'] == git(repo, 'rev-parse', iso['branch'])
    assert integration['nodes'] == {node['id']: node['stages']['execute']['artifact']['binding']['codeCommit']['nodeCommit']
                                    for node in run_doc['nodes'] if 'execute' in node['stages']}
    meta = service.integration_node(run_doc)['stages']['execute']['artifact']
    assert meta['binding']['workspace']['root'] == iso['root']
    assert iso['root'] in executor.roots()
    assert run_doc['status'] == 'executed'
    # Mọi lệnh do harness phát (không mang `root`) chạy tại workspace gốc, không phải worktree.
    assert None in executor.roots()


def test_execute_is_idempotent_and_never_recreates_the_worktree(tmp_path):
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    repo = make_repo(workspace)
    wg.set_autopilot(runtime, sid, True)

    async def run():
        first = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        service = wg.service(runtime)
        run_doc = service.get(first['runId'])
        created = git(repo, 'worktree', 'list', '--porcelain')
        again = await raw_tool(runtime, sid, 'work_run', {'phase': 'execute', 'runId': first['runId']})
        return run_doc, created, service.get(first['runId']), again

    run_doc, created, after, again = asyncio.run(run())
    assert after['isolation'] == run_doc['isolation']
    assert git(repo, 'worktree', 'list', '--porcelain') == created
    branches = git(repo, 'branch', '--list', '--format=%(refname:short)').splitlines()
    assert branches.count(run_doc['isolation']['branch']) == 1
    assert len([name for name in branches if name.startswith(run_doc['isolation']['branch'])]) == 3
    assert again['status'] == 'executed'


def test_checkpoint_keeps_plan_and_artifact_files_out_of_the_run_commit(tmp_path):
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    repo = make_repo(workspace)
    wg.set_autopilot(runtime, sid, True)

    async def run():
        return await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])

    result = asyncio.run(run())
    run_doc = wg.service(runtime).get(result['runId'])
    root = workspace / run_doc['isolation']['root']
    # Thư mục điều khiển của BoxFox là rác của máy chủ, không phải sản phẩm của run.
    (root / '.plans' / 'work').mkdir(parents=True, exist_ok=True)
    (root / '.plans' / 'work' / 'note.md').write_text('host state\n', encoding='utf-8')
    (root / '.generated_artifacts').mkdir(exist_ok=True)
    (root / '.generated_artifacts' / 'log.txt').write_text('host log\n', encoding='utf-8')
    (root / 'src' / 'new.py').write_text('x = 1\n', encoding='utf-8')
    # Rác của chính lượt chạy (bytecode, cache test) cũng không phải sản phẩm của run.
    (root / 'src' / '__pycache__').mkdir(exist_ok=True)
    (root / 'src' / '__pycache__' / 'new.cpython-312.pyc').write_bytes(b'\x00\x01')
    (root / 'stray.pyc').write_bytes(b'\x00\x02')
    (root / '.pytest_cache').mkdir(exist_ok=True)
    (root / '.pytest_cache' / 'state').write_text('cache\n', encoding='utf-8')

    async def commit():
        service = wg.service(runtime)
        return await service.worktrees.checkpoint(run_doc, service.integration_node(run_doc), 1, sid)

    checkpoint = asyncio.run(commit())
    files = git(repo, 'show', '--name-only', '--format=', checkpoint['nodeCommit']).splitlines()
    assert 'src/new.py' in files
    assert not [path for path in files if path.startswith(('.plans/', '.generated_artifacts/', '.boxfox/',
                                                           '.pytest_cache/'))
                or path.endswith('.pyc') or '__pycache__' in path], files


def test_touchset_mode_locks_one_path_per_node(tmp_path, monkeypatch):
    """Không có repo git: chế độ dự phòng vẫn tuần tự hoá hai nút ghi cùng một đường dẫn."""
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    monkeypatch.setattr(ww, 'TOUCH_WAIT_SECONDS', 0.3)
    monkeypatch.setattr(ww, 'TOUCH_POLL_SECONDS', 0.05)
    service = wg.service(runtime)
    run = {'runId': 'w-0123456789'}
    first = {'id': 'B1', 'files': ['src/app.py']}
    second = {'id': 'B2', 'files': ['src/app.py']}
    other = {'id': 'B3', 'files': ['src/other.py']}

    async def locks():
        assert service.worktrees.touch_paths({'files': ['/src/app.py/', 'src/app.py']}) == ['src/app.py']
        assert await service.worktrees.lock_touchset(run, first) == ['src/app.py']
        assert await service.worktrees.lock_touchset(run, other) == ['src/other.py']
        with pytest.raises(ww.IsolationError, match='WORK_TOUCHSET_BUSY'):
            await service.worktrees.lock_touchset(run, second)
        service.worktrees.release_touchset(run, first)
        return await service.worktrees.lock_touchset(run, second)

    assert asyncio.run(locks()) == ['src/app.py']


def test_touchset_violations_name_only_paths_outside_the_declared_files(tmp_path):
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    service = wg.service(runtime)
    node = {'id': 'B1', 'files': ['src/app.py']}
    before = {'files': {'src/app.py': 'a', 'src/other.py': 'b'}, 'head': 'x'}
    after = {'files': {'src/app.py': 'z', 'src/other.py': 'b', 'docs/readme.md': 'c'}, 'head': 'x'}
    assert service.worktrees.touch_violations(node, before, after) == ['docs/readme.md']
    assert service.worktrees.touch_violations(node, before, before) == []
    # Không đo được (thiếu một phía) thì không kết luận — cổng snapshot mới là nguồn phán quyết.
    assert service.worktrees.touch_violations(node, None, after) is None
    assert service.worktrees.touch_violations(node, before, {'files': {}, 'head': 'y'}) == ['src/other.py', '<HEAD moved>']


def test_isolation_is_off_with_the_environment_switch(tmp_path, monkeypatch):
    """`BOXFOX_WORK_ISOLATION=0`: không nhánh, không worktree, cây làm việc chung như trước."""
    monkeypatch.setenv(ww.ISOLATION_ENV, '0')
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    repo = make_repo(workspace, name='.')
    wg.set_autopilot(runtime, sid, True)

    async def run():
        return await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])

    result = asyncio.run(run())
    run_doc = wg.service(runtime).get(result['runId'])
    assert run_doc['isolation']['mode'] == 'legacy'
    assert git(repo, 'worktree', 'list', '--porcelain').count('worktree') == 1
    assert git(repo, 'branch', '--list', '--format=%(refname:short)') == 'main'
    assert not (workspace / '.boxfox').exists()
    assert run_doc['status'] == 'executed'


class WriteOne(Model):
    """Model giả GHI một tệp thật ở mỗi lượt sản xuất (dùng cho chế độ touch-set, không có git)."""

    def __init__(self, name):
        super().__init__(ok_script)
        self.name = name

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        result = await super().complete(messages, tools, route, max_tokens, on_thought, on_content)
        first = next((str(m.get('content') or '') for m in messages if m.get('role') == 'user'), '')
        done = any(m.get('name') == 'file_write' for m in messages if m.get('role') == 'tool')
        calls = result['choices'][0]['message'].get('tool_calls') or []
        producing = first.startswith('Work Graph run "') and re.search(r'\((?:build|plan|debug|simplify), execute\)', first)
        if calls and not done and producing:
            calls.append({'id': 'touchset-write', 'type': 'function',
                          'function': {'name': 'file_write',
                                       'arguments': json.dumps({'path': self.name, 'content': '# touchset\n'})}})
        return result


def touchset_stage(tmp_path, written, declared):
    """Chạy đúng MỘT lượt execute của nút B1 trong workspace KHÔNG có git."""
    folder = tmp_path / ('touchset-' + written.replace('/', '-'))
    folder.mkdir()
    (folder / 'src').mkdir()
    (folder / 'src' / 'app.py').write_text('def header():\n    return "chat"\n', encoding='utf-8')
    # Sổ phiên nằm NGOÀI workspace: chỉ tệp của dự án mới tính vào touch-set.
    store = SessionStore(tmp_path / ('store-' + written.replace('/', '-') + '.db'))
    runtime = HarnessRuntime(store, RealExecutor(folder), WriteOne(written))
    sid = runtime.create({'skills': []})['id']
    service = wg.service(runtime)
    session = store.get(sid)

    async def run():
        doc = service.create(session, {'goal': 'Thêm export_markdown khi workspace không có git.', 'flow': 'fix',
            'nodes': [{'id': 'B1', 'kind': 'build', 'title': 'Export',
                       'goal': 'Viết tệp xuất markdown trong src/ và báo lại đường dẫn đã ghi.',
                       'acceptance': ['tệp xuất tồn tại'], 'tests': ['vitest export.test.ts'], 'files': declared}]})
        doc['status'] = 'approved'
        doc['executionRequested'] = True
        service.set_repair_default(doc)
        service.save(doc, 'probe_approved')
        iso = await service.ensure_isolation(session, doc, {})
        node = service.find_node(doc, 'B1')
        status = await service.run_stage(session, doc, node, 'execute', 3)
        service.save(doc, 'probe_stage')
        return iso, node['stages']['execute'], status

    return asyncio.run(run())


def test_touchset_fallback_admits_declared_files_without_git(tmp_path, monkeypatch):
    """A4.3 fallback: không có git thì manifest bẩn là định danh code — tệp khai báo đi tiếp được."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    iso, state, status = touchset_stage(tmp_path, 'src/out-1.py', ['src/out-1.py'])
    assert iso['mode'] == 'touchset' and not (tmp_path / 'touchset-src-out-1.py' / '.boxfox').exists()
    assert status in ('needs_checks', 'accepted'), state.get('error')
    assert (tmp_path / 'touchset-src-out-1.py' / 'src' / 'out-1.py').is_file(), 'touch-set ghi thẳng workspace'


def test_touchset_fallback_blocks_an_undeclared_file(tmp_path, monkeypatch):
    """A4.3 fallback: nút ghi tệp ngoài khai báo ⇒ lượt execute dừng ở `failed` kèm đường dẫn lạ."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    iso, state, status = touchset_stage(tmp_path, 'src/sneaky.py', ['src/out-1.py'])
    assert iso['mode'] == 'touchset'
    assert status == 'failed' and 'WORK_TOUCHSET_VIOLATION' in (state.get('error') or '')
    assert state['touchViolation'] == ['src/sneaky.py'], 'lỗi phải nêu ĐÚNG tệp ngoài khai báo'


def test_evidence_probe_measures_the_node_worktree(tmp_path):
    """Cổng bằng chứng phải dò ĐÚNG cây của lượt: node ghi trong worktree, không phải workspace chung.

    Dò ở workspace chung thì mọi thay đổi thật của node nằm ngoài tầm nhìn (hoặc hiện ra với đường
    dẫn `.boxfox/worktrees/...` không khớp tệp đã khai), nên cổng kết luận sai là "không đổi gì".
    """
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'shared.py').write_text('shared\n', encoding='utf-8')
    root = '.boxfox/worktrees/w-abc12345/n-B1'
    (workspace / root / 'src').mkdir(parents=True)
    (workspace / root / 'src' / 'export.py').write_text('def export_markdown():\n    return 1\n', encoding='utf-8')
    store = SessionStore(tmp_path / 'sessions.db')
    executor = RealExecutor(workspace)
    runtime = HarnessRuntime(store, executor, Model(ok_script))
    sid = runtime.create({'skills': []})['id']
    store.update_config(sid, dict(store.get(sid)['config'], workBinding={'workspace': {'root': root}}))

    # Đúng cách `_run` gọi: root lấy từ `workBinding.workspace` của phiên.
    binding = (store.get(sid)['config'] or {}).get('workBinding') or {}
    asyncio.run(runtime.probe_workspace(sid, time.time() - 5,
                                        root=(binding.get('workspace') or {}).get('root')))
    terminal = [call for call in executor.calls if call[0] == 'terminal_exec'][-1]
    assert terminal[2]['root'] == root, 'lệnh dò phải chạy trong worktree của nút'
    assert f'cd /home/agent/workspace/{root} ' in terminal[1]['command'], terminal[1]['command']
    # Box thật ánh xạ `/home/agent/workspace` sang workspace của nó; chạy đúng câu lệnh đó với tiền
    # tố đổi sang workspace thật để chứng minh phép dò chỉ thấy tệp của worktree (không thấy shared.py).
    command = terminal[1]['command'].replace('/home/agent/workspace', str(workspace), 1)
    out = subprocess.run(['bash', '-lc', command], cwd=str(workspace), capture_output=True, text=True).stdout
    assert [item['path'] for item in runtime.parse_probe_output(out)] == ['src/export.py'], out
    # Máy chủ nhà không có `/home/agent/workspace` nên chính phép dò trả `ok=False`; thứ bài này
    # khoá là ĐÍCH ĐO: câu lệnh và `root` trong định danh, cùng kết quả khi box ánh xạ đường dẫn.


def test_touchset_manifest_stays_inside_a_workspace_that_sits_in_a_bigger_repo(tmp_path, monkeypatch):
    """Touch-set: manifest bẩn chỉ đo cây CỦA workspace — repo cha phía trên không được lọt vào.

    `git status` trong thư mục con vẫn thấy repo cha và trả đường dẫn tính từ gốc repo cha, nên
    manifest sẽ báo nhầm tệp của người khác và bỏ sót tệp thật của run.
    """
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    outer = tmp_path / 'outer'
    outer.mkdir()
    git(outer, 'init', '-q', '-b', 'main')
    git(outer, 'config', 'user.email', 'box@example.com')
    git(outer, 'config', 'user.name', 'Box')
    (outer / 'README.md').write_text('outer\n', encoding='utf-8')
    git(outer, 'add', '.')
    git(outer, 'commit', '-q', '-m', 'outer init')
    workspace = outer / 'workspace'
    (workspace / 'src').mkdir(parents=True)
    (workspace / 'src' / 'app.py').write_text('def header():\n    return "chat"\n', encoding='utf-8')
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, RealExecutor(workspace), Model(ok_script))
    sid = runtime.create({'skills': []})['id']
    service = wg.service(runtime)
    (outer / 'README.md').write_text('outer edited\n', encoding='utf-8')      # thay đổi của repo CHA
    (workspace / 'src' / 'out.py').write_text('def out():\n    return 1\n', encoding='utf-8')

    manifest = asyncio.run(service.worktrees.dirty_manifest(sid))
    assert manifest and manifest['schema'] == 'work-dirty/1'
    assert set(manifest['files']) == {'src/app.py', 'src/out.py'}, manifest['files']
    assert manifest['head'] == '', 'workspace không phải gốc repo thì không có HEAD của ai cả'


def test_workspace_inside_a_bigger_repo_isolates_the_workspace_repo(tmp_path):
    """Workspace là thư mục con của một repo khác: run cô lập trong repo CỦA workspace, không đụng repo cha."""
    outer = tmp_path / 'outer'
    outer.mkdir()
    git(outer, 'init', '-q', '-b', 'main')
    git(outer, 'config', 'user.email', 'box@example.com')
    git(outer, 'config', 'user.name', 'Box')
    (outer / 'README.md').write_text('outer\n', encoding='utf-8')
    git(outer, 'add', '.')
    git(outer, 'commit', '-q', '-m', 'outer init')
    workspace = outer / 'workspace'
    workspace.mkdir()
    repo = make_repo(workspace)
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, RealExecutor(workspace), Model(ok_script))
    sid = runtime.create({'skills': []})['id']
    service = wg.service(runtime)

    async def run():
        doc = service.create(store.get(sid), {'goal': 'Thêm export_markdown trong repo của workspace.',
            'flow': 'fix', 'nodes': [dict(BUILD, dependsOn=[])]})
        doc['status'] = 'approved'
        doc['executionRequested'] = True
        service.set_repair_default(doc)
        service.save(doc, 'probe_approved')
        return await service.ensure_isolation(store.get(sid), doc, {})

    iso = asyncio.run(run())
    assert iso['mode'] == 'git' and iso['repoPath'] == 'repo'
    assert iso['baselineCommit'] == git(repo, 'rev-parse', 'HEAD')
    assert git(outer, 'branch', '--list', '--format=%(refname:short)') == 'main'
    assert not (outer / '.boxfox').exists()
