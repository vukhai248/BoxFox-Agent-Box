"""Hai nhánh của tầng tệp riêng: POSIX handle và nhánh portable cho Windows.

Nhánh portable được chạy thật trên Linux bằng cách ghim `_HANDLES = False`, nên hợp đồng của nó
(allowlist thành phần, từ chối symlink, checksum, trần marker) có bằng chứng chạy được — không chỉ
là một nhánh `if` chưa ai chạy tới.
"""
import os

import pytest

from agentbox.memory import history_files
from agentbox.memory.history_files import digest, read, read_unverified, unlink, write


@pytest.fixture(params=[True, False], ids=['handles', 'portable'])
def branch(request, monkeypatch):
    """Chạy cùng một hợp đồng trên cả hai nhánh."""
    if not request.param:
        if not history_files._HANDLES:
            pytest.skip('host vốn đã ở nhánh portable')
        monkeypatch.setattr(history_files, '_HANDLES', False)
    return request.param


def test_write_read_and_unlink_agree_on_both_branches(tmp_path, branch):
    root = tmp_path / 'private'
    data = 'nội dung'.encode()
    path = write(root, ('history', 'session1'), 'blob_1', data)
    assert path == 'history/session1/blob_1'
    assert read(root, path, digest(data)) == data
    assert read_unverified(root, ('history', 'session1'), 'blob_1') == data
    unlink(root, path)
    with pytest.raises(FileNotFoundError):
        read(root, path, digest(data))
    unlink(root, path)  # xoá lần hai là no-op, không ném


def test_a_wrong_checksum_is_refused_on_both_branches(tmp_path, branch):
    root = tmp_path / 'private'
    path = write(root, ('history',), 'blob_1', b'payload')
    with pytest.raises(ValueError, match='HISTORY_CHECKSUM_MISMATCH'):
        read(root, path, digest(b'other'))


def test_path_traversal_components_are_refused_on_both_branches(tmp_path, branch):
    root = tmp_path / 'private'
    for bad in ('..', '.', 'a/b', '', 'a b', 'x' * 200):
        with pytest.raises(ValueError, match='HISTORY_PATH_INVALID'):
            write(root, ('history', bad), 'blob_1', b'x')
    with pytest.raises(ValueError, match='HISTORY_FILENAME_INVALID'):
        write(root, ('history',), '../escape', b'x')


def test_the_marker_reader_stops_at_its_limit_on_both_branches(tmp_path, branch):
    root = tmp_path / 'private'
    write(root, ('history',), 'identity.json', b'x' * 40)
    assert read_unverified(root, ('history',), 'identity.json', limit=40) == b'x' * 40
    with pytest.raises(ValueError, match='HISTORY_MARKER_TOO_LARGE'):
        read_unverified(root, ('history',), 'identity.json', limit=39)


def test_a_symlinked_component_is_never_followed(tmp_path, branch):
    root = tmp_path / 'private'
    outside = tmp_path / 'outside'
    outside.mkdir()
    root.mkdir()
    (root / 'history').symlink_to(outside, target_is_directory=True)
    with pytest.raises((OSError, ValueError)):
        write(root, ('history', 'session1'), 'blob_1', b'x')
    assert list(outside.iterdir()) == [], 'không được ghi xuyên qua symlink'


def test_the_portable_branch_refuses_a_symlinked_target_file(tmp_path, monkeypatch):
    monkeypatch.setattr(history_files, '_HANDLES', False)
    root = tmp_path / 'private'
    write(root, ('history',), 'blob_1', b'first')
    outside = tmp_path / 'outside.txt'
    outside.write_bytes(b'second')
    target = root / 'history' / 'blob_1'
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(ValueError, match='HISTORY_PATH_INVALID'):
        write(root, ('history',), 'blob_1', b'third')
    with pytest.raises(ValueError, match='HISTORY_PATH_INVALID'):
        read(root, 'history/blob_1', digest(b'second'))
    assert outside.read_bytes() == b'second', 'tệp ngoài không được chạm tới'


def test_the_written_file_is_owner_only_on_the_handles_branch(tmp_path):
    if not history_files._HANDLES:
        pytest.skip('nhánh portable không hứa quyền POSIX')
    root = tmp_path / 'private'
    write(root, ('history',), 'blob_1', b'x')
    assert os.stat(root / 'history' / 'blob_1').st_mode & 0o777 == 0o600


def test_the_portable_branch_creates_missing_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(history_files, '_HANDLES', False)
    root = tmp_path / 'deep' / 'private'
    write(root, ('history', 'session1', 'sub'), 'blob_1', b'x')
    assert (root / 'history' / 'session1' / 'sub' / 'blob_1').read_bytes() == b'x'
