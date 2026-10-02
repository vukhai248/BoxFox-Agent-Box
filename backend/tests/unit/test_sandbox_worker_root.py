"""W8.A4.3 — worker chỉ thấy đúng worktree được giao: `root` do harness đặt, không do model.

Box không có `/home/agent/workspace`, nên bài này dựng workspace + repo git THẬT trong `tmp_path`
rồi trỏ `WORKSPACE`/`ROOT` của worker vào đó. Nó khoá bốn luật:

- `root=None` (mọi lượt cũ) không đổi `ROOT` — kể cả khi lượt trước đã bị thu hẹp;
- `root` hợp lệ trỏ đúng worktree: đọc/ghi chỉ thấy cây đó, không thấy checkout chung;
- `root` ra ngoài khuôn `.boxfox/worktrees/w-<10 hex>/{main|n-<id>}` bị chối thẳng, kể cả
  đường dẫn thoát (`../`), đường dẫn tuyệt đối, và thư mục không phải worktree git;
- trong worktree của run thì `design_*`/`write_plan` (ghi vào trạng thái của chủ sở hữu) bị chối.
"""
import subprocess
from pathlib import Path

import pytest

import agentbox.sandbox.worker as worker

RUN_ROOT = '.boxfox/worktrees/w-0123456789/main'
NODE_ROOT = '.boxfox/worktrees/w-0123456789/n-B1'


def _git(root, *args):
    proc = subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True)
    if proc.returncode:
        raise AssertionError('git %s: %s' % (' '.join(args), proc.stderr))
    return proc.stdout.strip()


def _workspace(tmp_path, monkeypatch):
    """Workspace thật + repo `app/` + hai worktree của một run, rồi trỏ worker vào workspace."""
    root = Path(tmp_path).resolve() / 'workspace'
    root.mkdir()
    repo = root / 'app'
    repo.mkdir()
    _git(repo, 'init', '-q', '-b', 'main')
    _git(repo, 'config', 'user.email', 'box@example.com')
    _git(repo, 'config', 'user.name', 'Box')
    (repo / 'shared.txt').write_text('shared\n', encoding='utf-8')
    _git(repo, 'add', '.')
    _git(repo, 'commit', '-q', '-m', 'init')
    for name in (RUN_ROOT, NODE_ROOT):
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(repo, 'worktree', 'add', '-q', str(target), 'HEAD')
        (target / 'own.txt').write_text(name + '\n', encoding='utf-8')
    monkeypatch.setattr(worker, 'WORKSPACE', root)
    monkeypatch.setattr(worker, 'ROOT', root)
    monkeypatch.setattr(worker, '_SCOPED', False)
    return root


def _refused(name, args, root=None):
    with pytest.raises(ValueError) as caught:
        worker.execute(name, args, 'session-1', root=root)
    return str(caught.value)


def test_a_request_without_a_root_keeps_the_workspace_untouched(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    assert worker.execute('file_read', {'path': 'app/shared.txt'}, 'session-1')['content'] == 'shared\n'
    assert worker.ROOT == root
    # Lượt bị thu hẹp rồi lượt sau không có `root`: ROOT phải trở về workspace, không dính lại.
    assert worker.execute('file_read', {'path': 'own.txt'}, 'session-1', root=RUN_ROOT)['content'].startswith(RUN_ROOT)
    assert worker.ROOT == root / RUN_ROOT
    worker.execute('file_read', {'path': 'app/shared.txt'}, 'session-1')
    assert worker.ROOT == root


def test_a_scoped_request_only_sees_its_own_worktree(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    scoped = worker.execute('file_read', {'path': 'own.txt'}, 'session-1', root=NODE_ROOT)
    assert scoped['content'] == NODE_ROOT + '\n'
    assert worker.ROOT == root / NODE_ROOT
    # Tệp chỉ có ở checkout chung (chưa commit) không nhìn thấy từ trong worktree.
    (root / 'app' / 'host-only.txt').write_text('host\n', encoding='utf-8')
    assert worker.execute('file_read', {'path': 'app/host-only.txt'}, 'session-1')['content'] == 'host\n'
    with pytest.raises(FileNotFoundError):
        worker.execute('file_read', {'path': 'app/host-only.txt'}, 'session-1', root=NODE_ROOT)
    # Không có đường vòng qua `../` hay đường dẫn tuyệt đối.
    assert 'Path Traversal Denied' in _refused('file_read', {'path': '../../app/host-only.txt'}, root=NODE_ROOT)
    assert 'Path Traversal Denied' in _refused('file_write', {'path': '/etc/passwd', 'content': 'x'}, root=NODE_ROOT)
    # Ghi trong worktree của mình thì được, và tệp chỉ nằm ở đó.
    worker.execute('file_write', {'path': 'new.txt', 'content': 'node work\n'}, 'session-1', root=NODE_ROOT)
    assert (root / NODE_ROOT / 'new.txt').read_text(encoding='utf-8') == 'node work\n'
    assert not (root / RUN_ROOT / 'new.txt').exists()


@pytest.mark.parametrize('root', ['', '.', '.boxfox/worktrees/w-0123456789', '../workspace',
                                  '/home/agent/workspace', '.boxfox/worktrees/w-0123456789/../../main',
                                  'app', '.boxfox/worktrees/w-0123456789/main/../../main',
                                  '.boxfox/worktrees/nothex/main', '.boxfox/worktrees/w-0123456789/other'])
def test_a_root_outside_the_run_worktrees_is_refused(tmp_path, monkeypatch, root):
    _workspace(tmp_path, monkeypatch)
    assert 'WORK_SCOPE_OUTSIDE_WORKTREE' in _refused('file_read', {'path': 'own.txt'}, root=root)


def test_a_directory_that_is_not_a_git_worktree_is_refused(tmp_path, monkeypatch):
    root = _workspace(tmp_path, monkeypatch)
    plain = root / '.boxfox/worktrees/w-0123456789/main/nested'
    plain.mkdir()
    assert 'WORK_SCOPE_OUTSIDE_WORKTREE' in _refused('file_read', {'path': 'own.txt'},
                                                    root='.boxfox/worktrees/w-0123456789/main/nested')


def test_owner_state_tools_are_unavailable_inside_a_worktree(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    assert 'WORK_SCOPE_OUTSIDE_WORKTREE' in _refused('write_plan', {'directory': 'work', 'slug': 'x'}, root=RUN_ROOT)
    assert 'WORK_SCOPE_OUTSIDE_WORKTREE' in _refused('design_write', {'path': 'a.txt', 'content': 'x'}, root=RUN_ROOT)
