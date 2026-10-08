"""Private durable files. Paths are minted here, never accepted from tools."""
import hashlib
import json
import os
import re
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


def directory(root, components):
    """Walk with no-follow directory handles, including the root's ancestors."""
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
