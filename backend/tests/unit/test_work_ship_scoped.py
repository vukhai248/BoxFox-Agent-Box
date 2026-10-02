"""W8.A4.4 — ảnh chụp theo phạm vi (worktree nút + base) và chỉ ship phần thay đổi của run.

Repo git THẬT trong `tmp_path` (có `origin` trỏ về một bare repo) + executor chạy `bash -lc` tại
workspace. Bài này khoá:

- `snapshot(root, base)` đo ĐÚNG cây của một nút và nhớ `root`/`base`; đổi một nút không làm ảnh
  chụp của nút khác thành cũ (`snapshot_of` đọc lại đúng cây đó);
- `work_ship` ở chế độ git đẩy đúng nhánh của run lên `origin`, chỉ mở MỘT PR nháp, và thân PR nêu
  nhánh + danh sách tệp thuộc run;
- ship lần hai trên cùng một cây là idempotent: không đẩy lại, không mở PR thứ hai;
- cây đổi sau khi kiểm xong ⇒ `WORK_SHIP_STALE`; cây bẩn ⇒ `worktree_dirty` (không ship nửa vời);
- chế độ cũ (legacy) vẫn đòi `paths` để không commit cả workspace.
"""
import asyncio
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

import pytest

from agentbox.agent_core import work_checks, work_graph as wg, work_worktrees as ww
from test_work_worktree import BUILD, EXPLORE, PLAN, RealExecutor, build, execute_run, git, make_repo


class WritingModel(__import__('test_work_graph').Model):
    """Model giả có GHI tệp thật: mỗi lượt sản xuất tạo một tệp mới trong worktree của nút."""

    def __init__(self, script=None):
        from test_work_graph import ok_script
        super().__init__(script or ok_script)
        self.writes = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        result = await super().complete(messages, tools, route, max_tokens, on_thought, on_content)
        first = next((str(m.get('content') or '') for m in messages if m.get('role') == 'user'), '')
        done = any(m.get('name') == 'file_write' for m in messages if m.get('role') == 'tool')
        calls = result['choices'][0]['message'].get('tool_calls') or []
        producing = first.startswith('Work Graph run "') and re.search(r'\((?:build|plan|debug|simplify), execute\)', first)
        if calls and not done and producing:
            name = 'src/out-%d.py' % (len(self.writes) + 1)
            self.writes.append(name)
            self.prompts_at_write = getattr(self, 'prompts_at_write', []) + [first.splitlines()[0][:70]]
            calls.append({'id': 'write%d' % len(self.writes), 'type': 'function',
                          'function': {'name': 'file_write',
                                       'arguments': json.dumps({'path': name, 'content': '# %s\n' % name})}})
        return result


def build_writing(tmp_path):
    """`build` + model biết ghi tệp; executor cũng ghi thật theo `root` của lượt gọi."""
    store, runtime, model, executor, sid, workspace = build(tmp_path, model=WritingModel())
    return store, runtime, model, executor, sid, workspace


def with_remote(workspace, tmp_path):
    """Repo thật + bare remote `origin`; trả về (repo, remote)."""
    repo = make_repo(workspace)
    remote = Path(tmp_path) / 'remote.git'
    subprocess.run(['git', 'init', '-q', '--bare', str(remote)], check=True, capture_output=True)
    git(repo, 'remote', 'add', 'origin', str(remote))
    return repo, remote


def gh_shim(tmp_path, pr_url=None):
    """`gh` giả trên PATH: `pr view` trả PR cũ nếu có, `pr create` trả URL mới."""
    binary = Path(tmp_path) / 'bin'
    binary.mkdir(exist_ok=True)
    script = binary / 'gh'
    script.write_text('#!/bin/sh\n'
                      'case "$1 $2" in\n'
                      '  "auth status") exit 0;;\n'
                      f'  "pr view") echo "{pr_url or ""}"; exit {0 if pr_url else 1};;\n'
                      '  "pr create") echo "https://github.com/acme/repo/pull/7"; exit 0;;\n'
                      'esac\nexit 0\n', encoding='utf-8')
    script.chmod(0o755)
    return str(binary)


def test_snapshot_is_scoped_to_one_worktree_and_remembers_its_base(tmp_path):
    store, runtime, model, executor, sid, workspace = build(tmp_path)
    repo = make_repo(workspace)
    service = wg.service(runtime)
    base = git(repo, 'rev-parse', 'HEAD')

    async def run():
        first = service.worktrees
        run_doc = {'runId': 'w-0123456789', 'nodes': [], 'slug': 'demo'}
        iso = await first.ensure_run(run_doc, {}, sid)
        assert iso['mode'] == 'git' and iso['repoPath'] == 'repo' and iso['baselineCommit'] == base
        one = {'id': 'B1', 'files': []}
        two = {'id': 'B2', 'files': []}
        # Hai worktree của hai nút, cùng base.
        for node in (one, two):
            await first.ensure_node(run_doc, node, sid)
        assert (workspace / first.code_root(run_doc, one)[0] / 'src' / 'app.py').is_file()
        start = await work_checks.snapshot(service, sid, first.code_root(run_doc, one)[0], base)
        assert start['root'] == first.code_root(run_doc, one)[0] and start['base'] == base
        # Ghi trong worktree của nút 1: ảnh chụp của nút 1 đổi, của nút 2 thì không.
        (workspace / first.code_root(run_doc, one)[0] / 'src' / 'new.py').write_text('x = 1\n', encoding='utf-8')
        changed = await work_checks.snapshot(service, sid, *first.code_root(run_doc, one))
        untouched = await work_checks.snapshot(service, sid, *first.code_root(run_doc, two))
        assert changed['hash'] != start['hash'] and untouched['hash'] == start['hash']
        # `snapshot_of` đọc lại ĐÚNG cây đã lưu, không rơi về workspace chung.
        assert (await work_checks.snapshot_of(service, sid, changed))['hash'] == changed['hash']
        assert (await work_checks.snapshot_of(service, sid, {'root': first.code_root(run_doc, two)[0],
                                                            'base': base}))['hash'] == start['hash']
        # Đường dẫn/base sai khuôn thì không đo — trả None thay vì đo nhầm cây.
        assert await work_checks.snapshot(service, sid, '/etc', base) is None
        assert await work_checks.snapshot(service, sid, first.code_root(run_doc, one)[0], 'HEAD') is None
        return start, changed

    start, changed = asyncio.run(run())
    assert start['hash'] != changed['hash']


def test_ship_pushes_the_run_branch_and_opens_one_draft_pr(tmp_path, monkeypatch):
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        shipped = await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})
        return result, shipped

    result, shipped = asyncio.run(run())
    run_doc = wg.service(runtime).get(result['runId'])
    iso = run_doc['isolation']
    assert shipped['ship']['status'] == 'pr_opened' and shipped['status'] == 'shipped'
    assert shipped['ship']['branch'] == iso['branch'] and shipped['ship']['pushed'] is True
    assert shipped['ship']['prUrl'] == 'https://github.com/acme/repo/pull/7'
    # Chỉ phần thay đổi của run được đẩy: tệp do model ghi trong worktree của nút, không hơn.
    assert shipped['ship']['ownedPaths'] == sorted(model.writes)
    pushed = git(remote, 'ls-tree', '-r', '--name-only', iso['branch']).splitlines()
    assert sorted(model.writes) == sorted(path for path in pushed if path.startswith('src/out-'))
    # Thân PR nêu nhánh và danh sách tệp thuộc run (chủ sở hữu đọc được trước khi merge).
    body = (workspace / shipped['ship']['prFile']).read_text(encoding='utf-8')
    assert iso['branch'] in body and '## Files owned by this run' in body and model.writes[0] in body
    # Checkout chung của chủ sở hữu không bị nhích: HEAD cũ, cây sạch, không thấy tệp của run.
    assert git(repo, 'rev-parse', 'HEAD') == iso['baselineCommit']
    assert git(repo, 'status', '--porcelain') == ''
    assert not (repo / 'src' / model.writes[0].split('/')[-1]).exists()


def test_ship_is_idempotent_for_the_same_tree(tmp_path, monkeypatch):
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        first = await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})
        service = wg.service(runtime)
        # Mô phỏng lần ship trước đã xong nhưng bản ghi run không kịp lưu trạng thái `shipped`.
        run_doc = service.get(result['runId'])
        run_doc['status'] = 'executed'
        service.save(run_doc, 'ship_recovered', 'fixture')
        second = await runtime.work_tool(runtime.store.get(sid), 'work_ship', {'runId': result['runId']})
        return first, second

    first, second = asyncio.run(run())
    assert first['ship']['shipKey'] == second['ship']['shipKey']
    # Trả lại ĐÚNG kết quả đã lưu: không đẩy lại, không mở PR thứ hai, mốc thời gian không đổi.
    assert second['ship']['at'] == first['ship']['at'] and second['ship']['status'] == 'pr_opened'
    assert git(remote, 'log', '--format=%H', first['ship']['branch']).splitlines()[0] == first['ship']['commit'] \
        or first['ship']['commit'] in git(remote, 'log', '--format=%H', first['ship']['branch'])


def test_ship_refuses_while_another_ship_owns_the_same_tree(tmp_path, monkeypatch):
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        service = wg.service(runtime)
        run_doc = service.get(result['runId'])
        key = f'ship-{run_doc["runId"]}-{run_doc["integration"]["treeHash"]}'
        assert service.worktrees.ship_claim(key, run_doc['runId'], {'branch': run_doc['isolation']['branch']})
        with pytest.raises(ValueError, match='WORK_SHIP_IN_PROGRESS'):
            await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})
        return run_doc

    run_doc = asyncio.run(run())
    assert git(remote, 'branch', '--list').strip() == ''
    assert wg.service(runtime).get(run_doc['runId'])['status'] == 'executed'


def test_ship_refuses_a_tree_that_moved_after_the_checks(tmp_path, monkeypatch):
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        run_doc = wg.service(runtime).get(result['runId'])
        root = workspace / run_doc['isolation']['root']
        (root / 'src' / 'sneaky.py').write_text('y = 2\n', encoding='utf-8')
        git(root, 'add', '-A')
        git(root, '-c', 'user.name=Box', '-c', 'user.email=box@example.com', 'commit', '-qm', 'moved after checks')
        return result

    result = asyncio.run(run())

    async def ship():
        return await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})

    with pytest.raises(ValueError, match='WORK_(CODE|SHIP)_STALE'):
        asyncio.run(ship())
    # Nhánh chưa từng được đẩy lên remote.
    assert git(remote, 'branch', '--list').strip() == ''


def test_ship_isolated_refuses_a_tree_that_no_longer_matches_the_checked_snapshot(tmp_path, monkeypatch):
    """Lớp gác thứ hai: kể cả khi đã qua `require_code_current`, cây phải khớp ảnh chụp đã kiểm."""
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        service = wg.service(runtime)
        run_doc = service.get(result['runId'])
        run_doc['integration']['treeHash'] = 'f' * 40
        with pytest.raises(ValueError, match='WORK_SHIP_STALE'):
            await service.ship_isolated(runtime.store.get(sid), run_doc, {})
        return run_doc

    run_doc = asyncio.run(run())
    assert git(remote, 'branch', '--list').strip() == ''
    assert wg.service(runtime).get(run_doc['runId'])['status'] == 'executed'


def test_ship_refuses_a_dirty_run_worktree_without_pushing(tmp_path, monkeypatch):
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        service = wg.service(runtime)
        run_doc = service.get(result['runId'])
        (workspace / run_doc['isolation']['root'] / 'src' / 'dirty.py').write_text('z = 3\n', encoding='utf-8')
        # Đường đầy đủ (`work_ship`) từ chối ngay ở cổng cây-còn-nguyên: cây đã khác ảnh chụp đã kiểm.
        with pytest.raises(ValueError, match='WORK_(CODE|SHIP)_STALE'):
            await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})
        # Lớp gác riêng của ship cũng từ chối và nói rõ vì sao (tệp nào bẩn).
        return await service.ship_isolated(runtime.store.get(sid), run_doc, {})

    shipped = asyncio.run(run())
    assert shipped['ship']['status'] == 'worktree_dirty' and shipped['ship']['dirty'] == ['?? src/dirty.py']
    assert 'pushed' not in shipped['ship'] and git(remote, 'branch', '--list').strip() == ''


def test_ship_ignores_bytecode_and_test_cache_left_in_the_run_worktree(tmp_path, monkeypatch):
    """Lượt chạy nào chạy test cũng để lại `__pycache__`/`.pytest_cache`; chúng không phải code
    của run nên không được chặn ship (và không được lọt vào nhánh đã đẩy)."""
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo, remote = with_remote(workspace, tmp_path)
    monkeypatch.setenv('PATH', gh_shim(tmp_path) + os.pathsep + os.environ['PATH'])
    wg.set_autopilot(runtime, sid, True)

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, PLAN, BUILD])
        run_doc = wg.service(runtime).get(result['runId'])
        root = workspace / run_doc['isolation']['root']
        (root / 'src' / '__pycache__').mkdir(parents=True, exist_ok=True)
        (root / 'src' / '__pycache__' / 'out.cpython-312.pyc').write_bytes(b'\x00pyc')
        (root / 'stray.pyc').write_bytes(b'\x00pyc')
        (root / '.pytest_cache').mkdir(exist_ok=True)
        (root / '.pytest_cache' / 'state').write_text('{}', encoding='utf-8')
        assert ww.junk('?? src/__pycache__/out.cpython-312.pyc')
        assert ww.junk('?? .pytest_cache/state') and ww.junk('?? stray.pyc')
        assert not ww.junk('?? src/dirty.py') and not ww.junk(' M src/out-1.py')
        return result, await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})

    result, shipped = asyncio.run(run())
    assert shipped['ship']['status'] == 'pr_opened', shipped['ship']
    pushed = git(remote, 'ls-tree', '-r', '--name-only', shipped['ship']['branch']).splitlines()
    assert not any(path.endswith(('.pyc', '.pyo')) or '__pycache__' in path or '.pytest_cache' in path
                   for path in pushed)
    assert shipped['ship']['ownedPaths'] == sorted(model.writes)


def test_ship_in_legacy_mode_requires_the_owned_paths(tmp_path, monkeypatch):
    """Chế độ cũ (không worktree) phải khai `paths`, nếu không sẽ commit cả workspace."""
    monkeypatch.setenv(ww.ISOLATION_ENV, '0')
    store, runtime, model, executor, sid, workspace = build_writing(tmp_path)
    repo = make_repo(workspace, name='.')
    wg.set_autopilot(runtime, sid, True)

    # Chế độ cũ dùng chung một cây: chỉ MỘT nút ghi (nhiều nút ghi nối tiếp là cây đã đổi — luật cũ).
    solo = dict(BUILD) | {'dependsOn': []}

    async def run():
        result = await execute_run(runtime, sid, [EXPLORE, solo])
        assert wg.service(runtime).get(result['runId'])['isolation']['mode'] == 'legacy'
        with pytest.raises(ValueError, match='WORK_SHIP_LEGACY_SCOPE_REQUIRED'):
            await runtime.work_tool(runtime.store.get(sid), 'work_ship', {})
        with pytest.raises(ValueError, match='WORK_SHIP_LEGACY_SCOPE_REQUIRED'):
            await runtime.work_tool(runtime.store.get(sid), 'work_ship', {'paths': ['src/../etc']})
        return await runtime.work_tool(runtime.store.get(sid), 'work_ship', {'paths': ['src']})

    shipped = asyncio.run(run())
    assert shipped['ship']['status'] == 'local' and shipped['ship']['commit']
    committed = git(repo, 'show', '--name-only', '--format=', 'HEAD').splitlines()
    assert committed and all(path.startswith('src/') for path in committed)
    assert '.plans/work' not in committed
