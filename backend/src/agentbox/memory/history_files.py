"""Private durable files. Paths are minted here, never accepted from tools.

Hai nhánh, một hợp đồng. Trên POSIX tầng này đi bằng **handle thư mục** (`dir_fd` + `O_NOFOLLOW`),
nên không có khe TOCTOU giữa lúc kiểm và lúc mở. Windows không có `dir_fd`/`O_DIRECTORY`/
`O_NOFOLLOW`, nên nhánh còn lại đi bằng đường dẫn với ba chốt bù lại: allowlist thành phần đã có
sẵn, **từ chối mọi thành phần là symlink** (kiểm bằng `lstat` ở từng bước), và ghi kiểu
temp + `os.replace` rồi đọc lại đối chiếu sha256. Đổi lại: trên Windows khe TOCTOU giữa `lstat` và
`open` vẫn còn — nói thẳng ở đây thay vì giả là tương đương, và đây là lý do F02 ghi rõ Windows
yếu hơn POSIX chứ không phải "đã hỗ trợ như nhau".
"""
import hashlib
import json
import os
import re
import stat
import uuid
from pathlib import Path


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('HISTORY_ID_INVALID')
    return value


def _component(name, code):
    """Một thành phần đường dẫn hợp lệ: không `.`/`..`, không ký tự ngoài allowlist."""
    if not re.fullmatch(r'[A-Za-z0-9_.-]{1,180}', name) or name in ('.', '..'):
        raise ValueError(code)
    return name


def _parts(relative):
    return [_component(part, 'HISTORY_PATH_INVALID') for part in relative.split('/')]


#: POSIX handle path is the strong one; Windows (no dir_fd/O_NOFOLLOW) uses the portable path.
_HANDLES = os.name == 'posix' and hasattr(os, 'O_DIRECTORY') and hasattr(os, 'O_NOFOLLOW')
_NOFOLLOW = getattr(os, 'O_NOFOLLOW', 0)
_BINARY = getattr(os, 'O_BINARY', 0)


def _portable_component(parent, name):
    """Một bước đường dẫn ở nhánh portable: tạo nếu thiếu, và **từ chối symlink**."""
    child = parent / name
    try:
        info = child.lstat()
    except FileNotFoundError:
        try:
            os.mkdir(child, 0o700)
        except FileExistsError:
            pass
        info = child.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ValueError('HISTORY_PATH_INVALID')
    return child


def _portable_directory(root, components):
    """Đi từ gốc ổ đĩa xuống, y như nhánh handle — chỉ khác là bằng đường dẫn, không bằng fd."""
    base = Path(root).absolute()
    current = Path(base.anchor or os.sep)
    for name in base.parts[1:]:
        current = _portable_component(current, name)
    for name in components:
        current = _portable_component(current, _component(name, 'HISTORY_PATH_INVALID'))
    return current


def _portable_target(base, name):
    """Tên đích trong một thư mục đã kiểm: không được là symlink hay thứ không phải tệp."""
    target = base / name
    try:
        info = target.lstat()
    except FileNotFoundError:
        return target
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError('HISTORY_PATH_INVALID')
    return target


def _portable_write(root, components, name, data):
    _component(name, 'HISTORY_FILENAME_INVALID')
    base = _portable_directory(root, components)
    _portable_target(base, name)
    temp = base / ('tmp_' + uuid.uuid4().hex)
    try:
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _BINARY, 0o600)
        with os.fdopen(out, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, base / name)
    finally:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
    return '/'.join((*components, name))


def _portable_read(root, parts):
    base = _portable_directory(root, parts[:-1])
    target = _portable_target(base, parts[-1])
    with open(target, 'rb') as stream:
        return stream.read()


def _portable_unlink(root, parts):
    base = _portable_directory(root, parts[:-1])
    target = _portable_target(base, parts[-1])
    try:
        os.unlink(target)
    except FileNotFoundError:
        pass


def _portable_read_unverified(root, components, name, limit):
    base = _portable_directory(root, components)
    target = _portable_target(base, name)
    with open(target, 'rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError('HISTORY_MARKER_TOO_LARGE')
    return data


def directory(root, components):
    """Walk with no-follow directory handles, including the root's ancestors."""
    if not _HANDLES:
        return _portable_directory(root, components)
    path = Path(root).absolute()
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for name in (*path.parts[1:], *components):
            if name in components:
                _component(name, 'HISTORY_PATH_INVALID')
            try:
                os.mkdir(name, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def write(root, components, name, data):
    if not _HANDLES:
        return _portable_write(root, components, name, data)
    _component(name, 'HISTORY_FILENAME_INVALID')
    fd = directory(root, components)
    temp = 'tmp_' + uuid.uuid4().hex
    try:
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(out, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temp, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)
    return '/'.join((*components, name))


def read(root, relative, checksum):
    parts = _parts(relative)
    if not _HANDLES:
        data = _portable_read(root, parts)
        if digest(data) != checksum:
            raise ValueError('HISTORY_CHECKSUM_MISMATCH')
        return data
    fd = directory(root, parts[:-1])
    try:
        inp = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(inp, 'rb') as stream:
            data = stream.read()
        if digest(data) != checksum:
            raise ValueError('HISTORY_CHECKSUM_MISMATCH')
        return data
    finally:
        os.close(fd)


def unlink(root, relative):
    parts = _parts(relative)
    if not _HANDLES:
        return _portable_unlink(root, parts)
    fd = directory(root, parts[:-1])
    try:
        try:
            os.unlink(parts[-1], dir_fd=fd)
        except FileNotFoundError:
            pass
        os.fsync(fd)
    finally:
        os.close(fd)


def read_unverified(root, components, name, limit=1000000):
    """Read ownership markers only as a refusal guard, never as canonical metadata."""
    _component(name, 'HISTORY_FILENAME_INVALID')
    if not _HANDLES:
        return _portable_read_unverified(root, components, name, limit)
    fd = directory(root, components)
    try:
        inp = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        with os.fdopen(inp, 'rb') as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ValueError('HISTORY_MARKER_TOO_LARGE')
        return data
    finally:
        os.close(fd)
