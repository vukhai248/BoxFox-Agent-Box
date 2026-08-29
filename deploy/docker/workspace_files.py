#!/usr/bin/env python3
"""Duyệt/đọc/ghi an toàn file trong ``/home/agent/workspace`` (mặt box).

Mô-đun thuần stdlib, KHÔNG chứa HTTP — được ``ide-proxy.py`` (chạy root) import
và gọi trực tiếp, giống ``plan_files.py``/``capture.py``. Mọi lỗi ném ra là
``WorkspaceFileError`` có sẵn ``status_code`` + ``public_message`` để ide-proxy
ánh xạ thẳng thành HTTP status.

Hai idiom được tái dùng nguyên trạng:
- Chứa đường dẫn an toàn của ``plan_files.py``: ``os.scandir``, mở từng segment
  bằng ``os.open(seg, O_RDONLY|O_DIRECTORY|O_NOFOLLOW, dir_fd=current)``, từ chối
  symlink, ``MAX_DEPTH``/``MAX_ENTRIES``/``MAX_FILE_SIZE``.
- Hạ quyền của ``capture.py``: ``AGENT_UID``/``AGENT_GID`` = 1000, ghi file qua
  ``fchown``/``fchmod`` (ide-proxy chạy root); thumbnail chạy ``convert``/``ffmpeg``
  dưới ``gosu agent`` qua ``_run_binary_as_agent`` (binary, ``text=False``).
"""

from __future__ import annotations

from datetime import datetime, timezone
import errno
import hashlib
import io
import mimetypes
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import zipfile

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------
WORKSPACE_ROOT = Path(os.environ.get("AGENT_WORKSPACE", "/home/agent/workspace"))
AGENT_UID = 1000
AGENT_GID = 1000
AGENT_USER = "agent"
AGENT_HOME = "/home/agent"

MAX_DEPTH = 16
MAX_ENTRIES = 2_000
MAX_FILE_SIZE = 1 * 1024 * 1024
MAX_UPLOAD_SIZE = 256 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 256 * 1024 * 1024
MAX_UNZIP_TOTAL_BYTES = 256 * 1024 * 1024
MAX_ZIP_PATHS = 200

# Cache thumbnail nằm dưới thư mục máy sinh — cũng là thư mục bị ẩn khỏi listing.
THUMBNAIL_DIR = WORKSPACE_ROOT / ".generated_artifacts" / "thumbnails"

# Các segment đánh dấu "không tin được" (placeholder heuristic — xem integrity_for).
_UNTRUSTED_SEGMENTS = frozenset(
    {"vendor", "node_modules", ".venv", "dist", "build", ".cache"}
)
# Basename khớp các mẫu này → confidentiality "bi_mat".
_SECRET_BASENAME_RES = (
    re.compile(r"^\.env"),          # .env, .env.local, .env.production ...
    re.compile(r"\.key$"),          # *.key
    re.compile(r"\.pem$"),          # *.pem
    re.compile(r"^id_rsa"),         # id_rsa, id_rsa.pub ...
    re.compile(r"^id_ed25519"),     # id_ed25519, id_ed25519.pub ...
)

EXT_LANGUAGE = {
    "ts": "typescript", "tsx": "typescript", "mts": "typescript", "cts": "typescript",
    "js": "javascript", "jsx": "javascript", "mjs": "javascript", "cjs": "javascript",
    "py": "python", "json": "json", "css": "css",
    "md": "markdown", "mdx": "markdown",
    "html": "html", "htm": "html", "sh": "shell",
}

# Bảng ext→mime dùng khi mimetypes.guess_type trả None (tsx/mjs/mdx/sh …).
_EXT_MIME_FALLBACK = {
    "ts": "text/typescript", "tsx": "text/typescript", "mts": "text/typescript", "cts": "text/typescript",
    "js": "text/javascript", "jsx": "text/javascript", "mjs": "text/javascript", "cjs": "text/javascript",
    "py": "text/x-python", "json": "application/json",
    "md": "text/markdown", "mdx": "text/markdown",
    "css": "text/css", "html": "text/html", "htm": "text/html", "sh": "text/x-sh",
    "txt": "text/plain", "env": "text/plain", "yaml": "text/yaml", "yml": "text/yaml",
    "toml": "text/plain", "ini": "text/plain", "log": "text/plain",
}

IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "webp"})
VIDEO_EXTS = frozenset({"mp4", "webm"})
AUDIO_EXTS = frozenset({"mp3", "wav", "m4a", "weba", "ogg", "flac", "aac"})
PDF_EXTS = frozenset({"pdf"})

_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


# ---------------------------------------------------------------------------
# Lỗi
# ---------------------------------------------------------------------------
class WorkspaceFileError(Exception):
    """Lỗi xử lý file workspace, mang sẵn HTTP status + thông báo công khai."""

    status_code = 500
    public_message = "Lỗi xử lý file workspace."

    def __init__(self, public_message: str | None = None, *, status_code: int | None = None):
        message = public_message or self.public_message
        super().__init__(message)
        if public_message is not None:
            self.public_message = public_message
        if status_code is not None:
            self.status_code = status_code


class InvalidWorkspacePath(WorkspaceFileError):
    status_code = 400
    public_message = "Đường dẫn workspace không hợp lệ."


class WorkspaceNotFound(WorkspaceFileError):
    status_code = 404
    public_message = "Không tìm thấy file/thư mục workspace."


class WorkspaceConflict(WorkspaceFileError):
    status_code = 409
    public_message = "Xung đột thư mục/file workspace."


class WorkspaceTooLarge(WorkspaceFileError):
    status_code = 413
    public_message = "File workspace vượt quá giới hạn kích thước."


class WorkspaceEncoding(WorkspaceFileError):
    status_code = 422
    public_message = "File workspace không phải UTF-8 hợp lệ."


class WorkspaceRangeNotSatisfiable(WorkspaceFileError):
    status_code = 416
    public_message = "Range không thỏa mãn."


# ---------------------------------------------------------------------------
# Tiện ích thời gian / đường dẫn
# ---------------------------------------------------------------------------
def _iso_utc(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def validate_rel_path(path: object) -> str:
    """Chuẩn hóa đường dẫn tương đối thành POSIX; từ chối absolute/drive/`..`/NUL/depth."""

    if not isinstance(path, str):
        raise InvalidWorkspacePath("Đường dẫn phải là chuỗi.")
    if "\x00" in path:
        raise InvalidWorkspacePath("Đường dẫn chứa ký tự NUL.")
    if path.startswith("/"):
        raise InvalidWorkspacePath("Đường dẫn tuyệt đối không được phép.")
    if _DRIVE_RE.match(path):
        raise InvalidWorkspacePath("Đường dẫn dạng drive không được phép.")
    # Lọc segment rỗng (double/trailing slash) và "." (current dir) — an toàn vì
    # chúng không đổi nghĩa đường dẫn. Segment ".." phải bị từ chối thẳng.
    segments = [seg for seg in path.split("/") if seg not in ("", ".")]
    if any(seg == ".." for seg in segments):
        raise InvalidWorkspacePath("Đường dẫn chứa segment '..'.")
    if len(segments) > MAX_DEPTH:
        raise InvalidWorkspacePath(f"Đường dẫn vượt quá độ sâu {MAX_DEPTH}.")
    return "/".join(segments)


def split_segments(path: object) -> list[str]:
    """Trả danh sách segment đã chuẩn hóa; rỗng cho thư mục gốc."""

    normalized = validate_rel_path(path)
    return normalized.split("/") if normalized else []


def _split_rel(rel: str) -> tuple[str, str]:
    """Tách rel thành (thư mục cha, tên file). Từ chối root."""

    segments = split_segments(rel)
    if not segments:
        raise WorkspaceNotFound("Thư mục gốc không phải file.")
    return "/".join(segments[:-1]), segments[-1]


def _validate_filename(name: object) -> str:
    """Kiểm tra tên file đơn (SAU URL-decode+strip): không rỗng/`.`/`..`, không `/`/`\\`/NUL."""

    if not isinstance(name, str):
        raise InvalidWorkspacePath("Tên file không hợp lệ.")
    name = name.strip()
    if name in ("", ".", ".."):
        raise InvalidWorkspacePath("Tên file không hợp lệ.")
    if "/" in name or "\\" in name or "\x00" in name:
        raise InvalidWorkspacePath("Tên file chứa ký tự không hợp lệ.")
    if "./" in name or ".." in name.split("/"):
        raise InvalidWorkspacePath("Tên file chứa segment không hợp lệ.")
    return name


# ---------------------------------------------------------------------------
# Mở an toàn qua directory FD (mirror plan_files)
# ---------------------------------------------------------------------------
def _open_root_fd() -> int | None:
    try:
        return os.open(str(WORKSPACE_ROOT), os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        # Không trả `str(error)` ra ngoài — nó chứa đường dẫn tuyệt đối của box.
        print(f"workspace_files: không mở được thư mục workspace: {error}", file=sys.stderr)
        raise WorkspaceFileError("Không mở được thư mục workspace.") from error


def _open_dir_fd(rel: str) -> int:
    """Mở thư mục rel qua dir_fd từng segment, từ chối symlink; trả fd của thư mục đích."""

    segments = split_segments(rel)
    root_fd = _open_root_fd()
    if root_fd is None:
        raise WorkspaceNotFound("Thư mục workspace không tồn tại.")
    opened = [root_fd]
    current = root_fd
    try:
        for seg in segments:
            try:
                nxt = os.open(seg, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=current)
            except FileNotFoundError:
                raise WorkspaceNotFound("Không tìm thấy thư mục.")
            except NotADirectoryError:
                raise WorkspaceNotFound("Đường dẫn không phải thư mục.")
            except OSError as error:
                if error.errno == errno.ELOOP:
                    raise WorkspaceConflict("Đường dẫn chứa liên kết tượng trưng.") from error
                print(f"workspace_files: không mở được thư mục {seg!r}: {error}", file=sys.stderr)
                raise WorkspaceFileError("Không mở được thư mục.") from error
            opened.append(nxt)
            current = nxt
    except WorkspaceFileError:
        for descriptor in reversed(opened):
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    # Đóng các fd trung gian (kể cả root), giữ lại fd của thư mục đích cho caller.
    for descriptor in opened[:-1]:
        try:
            os.close(descriptor)
        except OSError:
            pass
    return current


def _open_file_fd(dir_rel: str, name: str) -> tuple[int, int, float]:
    """Mở file ``name`` dưới ``dir_rel`` qua dir_fd; kiểm regular; trả (fd, size, mtime)."""

    dir_fd = _open_dir_fd(dir_rel)
    try:
        try:
            fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW, dir_fd=dir_fd)
        except FileNotFoundError:
            raise WorkspaceNotFound("Không tìm thấy file.")
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise WorkspaceConflict("File đích là liên kết tượng trưng.") from error
            print(f"workspace_files: không mở được file {name!r}: {error}", file=sys.stderr)
            raise WorkspaceFileError("Không mở được file.") from error
    finally:
        os.close(dir_fd)
    try:
        metadata = os.fstat(fd)
    except OSError as error:
        os.close(fd)
        print(f"workspace_files: không đọc metadata file {name!r}: {error}", file=sys.stderr)
        raise WorkspaceFileError("Không đọc được metadata file.") from error
    if not stat.S_ISREG(metadata.st_mode):
        os.close(fd)
        raise WorkspaceNotFound("Đường dẫn không phải file thường.")
    return fd, metadata.st_size, metadata.st_mtime


# ---------------------------------------------------------------------------
# Mapping file / provenance (placeholder heuristic — đồng bộ mock frontend)
# ---------------------------------------------------------------------------
def ext_of(name: str) -> str | None:
    if "." in name:
        ext = name.rsplit(".", 1)[1].lower()
        return ext or None
    return None


def language_of(name: str) -> str | None:
    return EXT_LANGUAGE.get(ext_of(name))


def is_image(name: str) -> bool:
    return ext_of(name) in IMAGE_EXTS


def is_video(name: str) -> bool:
    return ext_of(name) in VIDEO_EXTS


def is_audio(name: str) -> bool:
    return ext_of(name) in AUDIO_EXTS


def is_pdf(name: str) -> bool:
    return ext_of(name) in PDF_EXTS


def _is_media(name: str) -> bool:
    return is_image(name) or is_video(name) or is_audio(name) or is_pdf(name)


def integrity_for(rel: str) -> str:
    """Placeholder heuristic: không tin nếu nằm trong vendor/node_modules/… hoặc là plan.md.

    LUẬT TẠM — thống nhất với ``frontend/src/lib/mock/workspace.ts``: backend thật
    sẽ quyết định theo ``source_kind`` chứ không theo đường dẫn.
    """

    segments = split_segments(rel)
    if any(seg in _UNTRUSTED_SEGMENTS for seg in segments):
        return "khong_tin_duoc"
    if segments and segments[-1] == "plan.md":
        return "khong_tin_duoc"
    return "duoc_nguoi_dung_cho_phep"


def confidentiality_for(name: str) -> str:
    """Placeholder heuristic: bi_mat cho .env*/*.key/*.pem/id_rsa*/id_ed25519*, còn lại cong_khai."""

    for pattern in _SECRET_BASENAME_RES:
        if pattern.search(name):
            return "bi_mat"
    return "cong_khai"


# ---------------------------------------------------------------------------
# Liệt kê
# ---------------------------------------------------------------------------
def _breadcrumb(rel: str) -> list[dict[str, str]]:
    crumbs = [{"name": "workspace", "path": ""}]
    walked = ""
    for seg in split_segments(rel):
        walked = f"{walked}/{seg}" if walked else seg
        crumbs.append({"name": seg, "path": walked})
    return crumbs


def list_directory(rel: object) -> dict:
    """Liệt kê MỘT thư mục: dir-before-file + theo tên, bỏ symlink và `.generated_artifacts`."""

    normalized = validate_rel_path(rel)
    dir_fd = _open_dir_fd(normalized)
    entries: list[dict] = []
    truncated = False
    total = 0
    try:
        with os.scandir(dir_fd) as iterator:
            for entry in iterator:
                name = entry.name
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        if name == ".generated_artifacts":
                            continue  # ẩn cache máy sinh khỏi explorer
                        metadata = entry.stat(follow_symlinks=False)
                        entries.append({
                            "name": name,
                            "kind": "dir",
                            "sizeBytes": 0,
                            "mtime": _iso_utc(metadata.st_mtime),
                            "integrity": None,
                            "confidentiality": None,
                            "ext": None,
                            "language": None,
                        })
                    elif entry.is_file(follow_symlinks=False):
                        metadata = entry.stat(follow_symlinks=False)
                        child_rel = f"{normalized}/{name}" if normalized else name
                        entries.append({
                            "name": name,
                            "kind": "file",
                            "sizeBytes": metadata.st_size,
                            "mtime": _iso_utc(metadata.st_mtime),
                            "integrity": integrity_for(child_rel),
                            "confidentiality": confidentiality_for(name),
                            "ext": ext_of(name),
                            "language": language_of(name),
                        })
                    # device/socket/pipe → bỏ qua
                except OSError:
                    continue
                total += 1
                if total >= MAX_ENTRIES:
                    truncated = True
                    break
    finally:
        os.close(dir_fd)

    entries.sort(key=lambda item: (item["kind"] != "dir", item["name"]))
    result: dict = {
        "breadcrumb": _breadcrumb(normalized),
        "entries": entries,
    }
    if truncated:
        result["truncated"] = True
    return result


# ---------------------------------------------------------------------------
# Đọc nội dung text
# ---------------------------------------------------------------------------
def _guess_mime(name: str) -> str:
    guessed = mimetypes.guess_type(name)[0]
    if guessed:
        return guessed
    return _EXT_MIME_FALLBACK.get(ext_of(name), "application/octet-stream")


def read_content(rel: object) -> dict:
    """Đọc file text/code/md/json; 413 quá lớn, 422 không phải UTF-8."""

    normalized = validate_rel_path(rel)
    dir_rel, name = _split_rel(normalized)
    fd, size, _mtime = _open_file_fd(dir_rel, name)
    try:
        if size > MAX_FILE_SIZE:
            raise WorkspaceTooLarge(f"File vượt giới hạn {MAX_FILE_SIZE} byte.")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, MAX_FILE_SIZE + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise WorkspaceTooLarge(f"File vượt giới hạn {MAX_FILE_SIZE} byte.")
        raw = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceEncoding("File không phải UTF-8 hợp lệ.") from error
    return {
        "content": content,
        "sizeBytes": size,
        "mime": _guess_mime(name),
        "language": language_of(name),
        "binary": False,
    }


# ---------------------------------------------------------------------------
# Media / Range
# ---------------------------------------------------------------------------
def media_stat(rel: object) -> tuple[int, float, str, str]:
    """Trả (size, mtime, content_type, name) cho file media/download."""

    normalized = validate_rel_path(rel)
    dir_rel, name = _split_rel(normalized)
    fd, size, mtime = _open_file_fd(dir_rel, name)
    os.close(fd)
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return size, mtime, content_type, name


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """Phân tích Range header. None khi thiếu (→ 200 full); raise 416 khi sai cú pháp."""

    if not header:
        return None
    match = re.match(r"^\s*bytes\s*=\s*(.*)$", header, re.IGNORECASE)
    if not match:
        raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
    spec = match.group(1).strip()
    if spec == "":
        raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
    if spec.startswith("-"):
        # suffix bytes=-N (N byte cuối)
        try:
            n = int(spec[1:])
        except ValueError:
            raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
        if n <= 0:
            raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
        if size <= 0:
            raise WorkspaceRangeNotSatisfiable("Range không thỏa mãn.")
        start = max(0, size - n)
        return start, size - 1
    if "-" not in spec:
        raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
    start_text, end_text = spec.split("-", 1)
    try:
        start = int(start_text)
    except ValueError:
        raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
    if start < 0 or start >= size:
        raise WorkspaceRangeNotSatisfiable("Range không thỏa mãn.")
    if end_text.strip() == "":
        end = size - 1  # open-ended bytes=s-
    else:
        try:
            end = int(end_text)
        except ValueError:
            raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
        if end < start:
            raise WorkspaceRangeNotSatisfiable("Range không hợp lệ.")
        if end >= size:
            end = size - 1
    return start, end


def iter_file_chunks(rel: object, start: int, end: int):
    """Sinh chunk 64 KiB trong khoảng [start, end] — không nạp cả file vào bộ nhớ."""

    normalized = validate_rel_path(rel)
    dir_rel, name = _split_rel(normalized)
    fd, _size, _mtime = _open_file_fd(dir_rel, name)
    try:
        os.lseek(fd, start, os.SEEK_SET)
        remaining = end - start + 1
        while remaining > 0:
            chunk = os.read(fd, min(64 * 1024, remaining))
            if not chunk:
                break
            yield chunk
            remaining -= len(chunk)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# Thumbnail (binary demote — convert/ffmpeg qua gosu agent, ghi file cache rồi đọc lại)
# ---------------------------------------------------------------------------
def _run_binary_as_agent(args: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess:
    """Chạy binary dưới user agent. Root+gosu → hạ quyền; không root → chạy trực tiếp."""

    if os.geteuid() == 0 and shutil.which("gosu"):
        argv = ["gosu", AGENT_USER, "env", f"HOME={AGENT_HOME}", *args]
    else:
        argv = list(args)
    return subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=timeout, check=False)


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def make_thumbnail(rel: object) -> bytes | None:
    """Sinh JPEG thumbnail cho ảnh/video, cache theo sha256(rel|mtime|size). Trả None nếu không phải media."""

    normalized = validate_rel_path(rel)
    dir_rel, name = _split_rel(normalized)
    ext = ext_of(name)
    if ext is None or ext == "svg":
        return None
    is_img = ext in IMAGE_EXTS
    is_vid = ext in VIDEO_EXTS
    if not is_img and not is_vid:
        return None
    fd, size, mtime = _open_file_fd(dir_rel, name)
    os.close(fd)

    in_path = str(WORKSPACE_ROOT / normalized)
    cache_dir = WORKSPACE_ROOT / ".generated_artifacts" / "thumbnails"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chown(cache_dir, AGENT_UID, AGENT_GID)
            os.chmod(cache_dir, 0o750)
        except (PermissionError, OSError):
            pass
    except OSError:
        return None
    key = hashlib.sha256(f"{normalized}|{mtime}|{size}".encode()).hexdigest()
    cache_file = cache_dir / f"{key}.jpg"
    if cache_file.exists():
        try:
            return cache_file.read_bytes()
        except OSError:
            return None

    # Phòng TOCTOU thứ hai ngay trước khi giao đường dẫn cho convert/ffmpeg (chạy
    # qua gosu agent): xác nhận lại file vẫn là regular non-symlink. Cửa sổ còn
    # lại là cực nhỏ và blast-radius bị giới hạn bởi việc chạy dưới user agent.
    recheck_fd, _recheck_size, _recheck_mtime = _open_file_fd(dir_rel, name)
    os.close(recheck_fd)

    if is_img:
        ext_args = ["convert", f"{in_path}[0]", "-resize", "512x512>", "-strip",
                    "-quality", "85"]
    else:
        ext_args = ["ffmpeg", "-y", "-ss", "0", "-i", in_path, "-frames:v", "1",
                    "-vf", "scale=512:-2", "-q:v", "3", "-vcodec", "mjpeg"]
    # Ghi vào file tạm rồi os.replace để tránh reader gặp JPEG viết dở (cache race).
    tmp_file = cache_dir / f".{key}.{os.getpid()}.tmp"
    _safe_unlink(tmp_file)
    proc = _run_binary_as_agent([*ext_args, str(tmp_file)], timeout=60)
    if proc.returncode != 0 or not tmp_file.exists():
        _safe_unlink(tmp_file)
        return None
    try:
        os.replace(tmp_file, cache_file)
    except OSError:
        _safe_unlink(tmp_file)
        return None
    try:
        return cache_file.read_bytes()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Ghi file (hạ quyền về agent)
# ---------------------------------------------------------------------------
def _write_full(fd: int, chunk: bytes) -> None:
    """Ghi hết ``chunk``; xử lý short-write/EINTR, ánh xạ ENOSPC → WorkspaceTooLarge."""

    view = memoryview(chunk)
    offset = 0
    while offset < len(view):
        try:
            written = os.write(fd, view[offset:])
        except InterruptedError:
            continue
        except OSError as error:
            if error.errno == errno.ENOSPC:
                raise WorkspaceTooLarge("Hết dung lượng đĩa khi ghi file.") from error
            print(f"workspace_files: lỗi ghi file: {error}", file=sys.stderr)
            raise WorkspaceFileError("Không ghi được file.") from error
        if written <= 0:
            raise WorkspaceFileError("Ghi file thất bại (zero-byte write).")
        offset += written


def write_as_agent(dir_rel: object, name: object, data_or_iter, *, max_bytes: int = MAX_UPLOAD_SIZE) -> int:
    """Mở file qua dir_fd, ghi, fchown(1000,1000), fchmod(0o640). Trả số byte đã ghi."""

    safe_name = _validate_filename(name)
    safe_dir = validate_rel_path(dir_rel)
    dir_fd = _open_dir_fd(safe_dir)
    try:
        try:
            fd = os.open(safe_name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW, dir_fd=dir_fd)
        except OSError as error:
            if error.errno == errno.ELOOP:
                raise WorkspaceConflict("Đích là liên kết tượng trưng — không ghi đè.") from error
            if error.errno in (errno.EACCES, errno.EISDIR):
                raise WorkspaceConflict("Không ghi được vào đích.") from error
            print(f"workspace_files: không mở được {safe_name!r} để ghi: {error}", file=sys.stderr)
            raise WorkspaceFileError("Không mở được file để ghi.") from error
    finally:
        os.close(dir_fd)

    written = 0
    try:
        if isinstance(data_or_iter, (bytes, bytearray)):
            chunks = [bytes(data_or_iter)]
        else:
            chunks = data_or_iter
        for chunk in chunks:
            if not isinstance(chunk, (bytes, bytearray)):
                raise InvalidWorkspacePath("Dữ liệu ghi phải là bytes.")
            if written + len(chunk) > max_bytes:
                raise WorkspaceTooLarge(f"Dung lượng vượt giới hạn {max_bytes} byte.")
            _write_full(fd, chunk)
            written += len(chunk)
        try:
            os.fchown(fd, AGENT_UID, AGENT_GID)
        except (PermissionError, OSError):
            pass
        try:
            os.fchmod(fd, 0o640)
        except OSError:
            pass
    finally:
        os.close(fd)
    return written


def write_upload(target_dir_rel: object, filename: object, body_iter, size_hint: int) -> dict:
    """Stream ghi file tải lên vào ``target_dir_rel``; trả {path, sizeBytes}."""

    name = _validate_filename(filename)
    target_dir = validate_rel_path(target_dir_rel)
    if size_hint and size_hint > MAX_UPLOAD_SIZE:
        raise WorkspaceTooLarge(f"Dung lượng vượt giới hạn {MAX_UPLOAD_SIZE} byte.")
    written = write_as_agent(target_dir, name, body_iter, max_bytes=MAX_UPLOAD_SIZE)
    joined = f"{target_dir}/{name}" if target_dir else name
    return {"path": joined, "sizeBytes": written}


# ---------------------------------------------------------------------------
# ZIP — dựng
# ---------------------------------------------------------------------------
def _read_all(fd: int, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = max(0, size)
    while remaining > 0:
        chunk = os.read(fd, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _walk_dir_fd(rel_prefix: str, dir_fd: int, depth: int = 0):
    """Duyệt đệ quy thư mục qua dir_fd, sinh (arcname, bytes) cho file thường, bỏ symlink."""

    if depth > MAX_DEPTH:
        return
    try:
        with os.scandir(dir_fd) as iterator:
            entries = list(iterator)
    except OSError:
        return
    for entry in entries:
        name = entry.name
        if name == ".generated_artifacts":
            continue
        try:
            if entry.is_symlink():
                continue
            child_rel = f"{rel_prefix}/{name}" if rel_prefix else name
            if entry.is_dir(follow_symlinks=False):
                child_fd = os.open(name, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=dir_fd)
                try:
                    yield from _walk_dir_fd(child_rel, child_fd, depth + 1)
                finally:
                    os.close(child_fd)
            elif entry.is_file(follow_symlinks=False):
                metadata = entry.stat(follow_symlinks=False)
                fd = os.open(name, os.O_RDONLY | _O_NOFOLLOW, dir_fd=dir_fd)
                try:
                    data = _read_all(fd, metadata.st_size)
                finally:
                    os.close(fd)
                yield child_rel, data
        except OSError:
            continue


def _iter_regular_files(rel: str):
    """Sinh (arcname, bytes) cho một path: file đơn hoặc đệ quy thư mục."""

    if rel == "":
        root_fd = _open_root_fd()
        if root_fd is None:
            raise WorkspaceNotFound("Thư mục workspace không tồn tại.")
        try:
            yield from _walk_dir_fd("", root_fd)
        finally:
            os.close(root_fd)
        return
    try:
        dir_fd = _open_dir_fd(rel)
    except WorkspaceNotFound:
        # có thể là file đơn
        dir_rel, name = _split_rel(rel)
        fd, size, _mtime = _open_file_fd(dir_rel, name)
        try:
            yield rel, _read_all(fd, size)
        finally:
            os.close(fd)
        return
    try:
        yield from _walk_dir_fd(rel, dir_fd)
    finally:
        os.close(dir_fd)


def build_zip(paths: object) -> bytes:
    """Nén nhiều đường dẫn thành zip bytes. 400 path sai, 404 thiếu, 413 quá lớn."""

    if not isinstance(paths, list):
        raise InvalidWorkspacePath("Body 'paths' phải là danh sách.")
    if len(paths) > MAX_ZIP_PATHS:
        raise InvalidWorkspacePath(f"Số đường dẫn vượt giới hạn {MAX_ZIP_PATHS}.")
    rels = [validate_rel_path(p) for p in paths]
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in rels:
            for arcname, data in _iter_regular_files(rel):
                if total + len(data) > MAX_ZIP_TOTAL_BYTES:
                    raise WorkspaceTooLarge(
                        f"Tổng dung lượng zip vượt giới hạn {MAX_ZIP_TOTAL_BYTES} byte."
                    )
                zf.writestr(arcname, data)
                total += len(data)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# ZIP — giải nén (zip-slip defense bắt buộc, không dùng extractall)
# ---------------------------------------------------------------------------
def _validate_zip_member(member: str) -> None:
    """Từ chối member tuyệt đối/`..`/rỗng/backslash/drive → WorkspaceConflict (409)."""

    if not isinstance(member, str) or member == "":
        raise WorkspaceConflict("Tên member zip rỗng.")
    if "\x00" in member:
        raise WorkspaceConflict("Tên member zip chứa NUL.")
    if member.startswith("/") or member.startswith("\\"):
        raise WorkspaceConflict("Tên member zip tuyệt đối không được phép.")
    if _DRIVE_RE.match(member):
        raise WorkspaceConflict("Tên member zip dạng drive không được phép.")
    if "\\" in member:
        raise WorkspaceConflict("Tên member zip chứa ký tự không hợp lệ.")
    stripped = member[:-1] if member.endswith("/") else member
    if stripped == "":
        raise WorkspaceConflict("Tên member zip rỗng.")
    for seg in stripped.split("/"):
        if seg == "" or seg == "..":
            raise WorkspaceConflict("Tên member zip chứa segment không hợp lệ.")


def _join_rel(base: str, member: str) -> str:
    return f"{base}/{member}" if base else member


def _ensure_dirs(base_rel: str, segments: list[str]) -> None:
    """Tạo chuỗi thư mục con dưới ``base_rel`` qua dir_fd, chown thư mục mới về 1000:1000."""

    if not segments:
        return
    current_fd = _open_dir_fd(base_rel)
    try:
        for seg in segments:
            try:
                nxt = os.open(seg, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=current_fd)
            except FileNotFoundError:
                try:
                    os.mkdir(seg, 0o750, dir_fd=current_fd)
                except OSError as error:
                    raise WorkspaceConflict(f"Không tạo được thư mục «{seg}».") from error
                try:
                    nxt = os.open(seg, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW, dir_fd=current_fd)
                except OSError as error:
                    raise WorkspaceFileError(f"Không mở được thư mục mới «{seg}».") from error
                try:
                    os.fchown(nxt, AGENT_UID, AGENT_GID)
                except (PermissionError, OSError):
                    pass
            except NotADirectoryError:
                raise WorkspaceConflict(f"«{seg}» đang là file, không tạo thư mục được.")
            os.close(current_fd)
            current_fd = nxt
    finally:
        os.close(current_fd)


def _path_exists(dir_rel: str, name: str) -> bool:
    if dir_rel == "":
        dir_fd = _open_root_fd()
    else:
        dir_fd = _open_dir_fd(dir_rel)
    if dir_fd is None:
        return False
    try:
        try:
            os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
    finally:
        os.close(dir_fd)


def _chunk_stream(stream, chunk_size: int = 64 * 1024):
    """Sinh chunk bytes từ luồng zip — không nạp cả member vào bộ nhớ (chống zip-bomb)."""

    while True:
        chunk = stream.read(chunk_size)
        if not chunk:
            break
        yield chunk


def extract_zip(zip_rel: object) -> dict:
    """Giải nén vào thư mục cha của zip, chống zip-slip, skip file trùng. Trả {extracted,skipped,warnings}."""

    normalized = validate_rel_path(zip_rel)
    segments = split_segments(normalized)
    if not segments:
        raise InvalidWorkspacePath("Đường dẫn zip không hợp lệ.")
    base_rel = "/".join(segments[:-1])
    dir_rel, name = _split_rel(normalized)
    fd, _size, _mtime = _open_file_fd(dir_rel, name)

    extracted = 0
    skipped = 0
    warnings: list[str] = []
    total_bytes = 0
    total_entries = 0
    # fd do file_handle sở hữu từ đây; ZipFile không đóng file object do caller truyền,
    # nên ta tự đóng trong finally.
    file_handle = os.fdopen(fd, "rb")
    try:
        try:
            zf = zipfile.ZipFile(file_handle)
        except zipfile.BadZipFile as error:
            raise WorkspaceEncoding("Archive zip hỏng.") from error
        with zf:
            for info in zf.infolist():
                total_entries += 1
                if total_entries > MAX_ENTRIES:
                    raise WorkspaceTooLarge(f"Số entry vượt giới hạn {MAX_ENTRIES}.")
                member = info.filename
                _validate_zip_member(member)
                if member.endswith("/"):
                    continue  # bỏ qua entry thư mục
                # member đã validate (không ".."/absolute/backslash/NUL); lọc "." nếu có.
                member_segments = [seg for seg in member.split("/") if seg not in ("", ".")]
                if not member_segments:
                    continue  # member chỉ là "."/"./" — entry thư mục, bỏ qua an toàn
                target_name = member_segments[-1]
                parent_under_base = member_segments[:-1]  # thư mục cần tạo, tính từ base
                if parent_under_base:
                    target_parent = _join_rel(base_rel, "/".join(parent_under_base))
                else:
                    target_parent = base_rel
                _ensure_dirs(base_rel, parent_under_base)
                if _path_exists(target_parent, target_name):
                    skipped += 1
                    warnings.append(f"Đã bỏ qua «{target_parent}/{target_name}» vì đã tồn tại.")
                    continue
                remaining = MAX_UNZIP_TOTAL_BYTES - total_bytes
                if info.file_size > remaining:
                    raise WorkspaceTooLarge(
                        f"Tổng dung lượng giải nén vượt giới hạn {MAX_UNZIP_TOTAL_BYTES} byte."
                    )
                try:
                    member_stream = zf.open(info)
                except (zipfile.BadZipFile, OSError) as error:
                    raise WorkspaceEncoding("Archive zip hỏng.") from error
                with member_stream:
                    written = write_as_agent(
                        target_parent, target_name,
                        _chunk_stream(member_stream), max_bytes=remaining,
                    )
                total_bytes += written
                extracted += 1
    finally:
        file_handle.close()
    return {"extracted": extracted, "skipped": skipped, "warnings": warnings}
