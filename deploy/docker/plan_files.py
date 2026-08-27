#!/usr/bin/env python3
"""Quét và đọc an toàn các file kế hoạch chỉ-đọc trong ``.plans``."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import errno
import os
from pathlib import Path
import re
import stat

MAX_DEPTH = 16
MAX_ENTRIES = 2_000
MAX_FILE_SIZE = 1_024 * 1_024

_SLUG = r"[a-z0-9]+(?:-[a-z0-9]+)*"
_VERSION = r"[1-9][0-9]{0,9}"
_FILENAME_RE = re.compile(rf"^v({_VERSION})-({_SLUG})\.md$")
_IDENTITY_RE = re.compile(rf"^(?:{_SLUG}/)*{_SLUG}$")

_O_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


class PlanFileError(Exception):
    """Lỗi có mã HTTP xác định khi xử lý file kế hoạch."""

    status_code = 500
    public_message = "Không thể đọc file kế hoạch."


class InvalidPlanRequest(PlanFileError):
    status_code = 400
    public_message = "Yêu cầu file kế hoạch không hợp lệ."


class PlanNotFound(PlanFileError):
    status_code = 404
    public_message = "Không tìm thấy file kế hoạch."


class PlanCollision(PlanFileError):
    status_code = 409
    public_message = "Phiên bản kế hoạch đang bị xung đột."


class PlanTooLarge(PlanFileError):
    status_code = 413
    public_message = "File kế hoạch vượt quá giới hạn kích thước."


class InvalidPlanEncoding(PlanFileError):
    status_code = 422
    public_message = "File kế hoạch không phải UTF-8 hợp lệ."


@dataclass(frozen=True)
class PlanVersion:
    """Metadata của một phiên bản file kế hoạch."""

    version: int
    relative_path: str
    size_bytes: int
    modified_at: str
    status: str

    def to_payload(self) -> dict[str, object]:
        return {
            "version": self.version,
            "label": f"v{self.version}",
            "relativePath": self.relative_path,
            "sizeBytes": self.size_bytes,
            "modifiedAt": self.modified_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class PlanGroup:
    """Một identity và các phiên bản hợp lệ của nó."""

    identity: str
    relative_directory: str
    slug: str
    versions: tuple[PlanVersion, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "identity": self.identity,
            "relativeDirectory": self.relative_directory,
            "slug": self.slug,
            "versions": [version.to_payload() for version in self.versions],
        }


@dataclass(frozen=True)
class PlanManifest:
    """Kết quả quét xác định, không chứa đường dẫn tuyệt đối."""

    plans: tuple[PlanGroup, ...]
    ignored_count: int
    warnings: tuple[str, ...]
    collisions: frozenset[tuple[str, int]]

    def to_payload(self) -> dict[str, object]:
        return {
            "plans": [plan.to_payload() for plan in self.plans],
            "ignoredCount": self.ignored_count,
            "warnings": list(self.warnings),
        }

    def version_for(self, identity: str, version: int) -> PlanVersion | None:
        for group in self.plans:
            if group.identity == identity:
                return next(
                    (item for item in group.versions if item.version == version), None
                )
        return None


@dataclass(frozen=True)
class PlanDocument:
    """Nội dung Markdown và metadata của một file kế hoạch."""

    identity: str
    version: int
    relative_path: str
    markdown: str
    size_bytes: int
    modified_at: str
    status: str

    def to_payload(self) -> dict[str, object]:
        return {
            "identity": self.identity,
            "version": self.version,
            "label": f"v{self.version}",
            "relativePath": self.relative_path,
            "markdown": self.markdown,
            "sizeBytes": self.size_bytes,
            "modifiedAt": self.modified_at,
            "status": self.status,
        }


@dataclass(frozen=True)
class _Candidate:
    identity: str
    relative_directory: str
    slug: str
    version: int
    relative_path: str
    size_bytes: int
    modified_at: str


def validate_identity(identity: str) -> tuple[str, str]:
    """Kiểm tra identity và trả về thư mục tương đối cùng slug cuối."""

    if not isinstance(identity, str) or not _IDENTITY_RE.fullmatch(identity):
        raise InvalidPlanRequest
    parts = identity.split("/")
    return "/".join(parts[:-1]), parts[-1]


def validate_version(version: object) -> int:
    """Kiểm tra version dương với nhiều nhất mười chữ số."""

    if isinstance(version, bool):
        raise InvalidPlanRequest
    value = str(version)
    if not re.fullmatch(_VERSION, value):
        raise InvalidPlanRequest
    return int(value)


def _modified_at(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")


def _is_temporary_name(name: str) -> bool:
    return (
        name.endswith("~")
        or name.startswith(".#")
        or name.startswith("~$")
        or name.endswith((".tmp", ".swp", ".bak"))
    )


def _warning(relative_path: Path, reason: str) -> str:
    return f"Đã bỏ qua «{relative_path.as_posix()}»: {reason}."


def _walk_plan_entries(root_input: int | Path) -> tuple[list[_Candidate], int, list[str]]:
    candidates: list[_Candidate] = []
    ignored_count = 0
    warnings: list[str] = []
    total_entries = 0

    def walk(target: int | Path, relative_directory: Path, depth: int) -> bool:
        nonlocal ignored_count, total_entries
        try:
            entries = sorted(os.scandir(target), key=lambda item: item.name)
        except OSError:
            ignored_count += 1
            warnings.append(_warning(relative_directory, "không thể đọc thư mục"))
            return True

        for entry in entries:
            total_entries += 1
            relative_path = (
                Path(entry.name)
                if relative_directory == Path()
                else relative_directory / entry.name
            )
            if total_entries > MAX_ENTRIES:
                warnings.append(
                    f"Đã chạm ngưỡng tối đa {MAX_ENTRIES} mục; các file còn lại bị bỏ qua."
                )
                ignored_count += 1
                return False

            if entry.name.startswith("."):
                ignored_count += 1
                warnings.append(_warning(relative_path, "segment ẩn"))
                continue
            if _is_temporary_name(entry.name):
                ignored_count += 1
                warnings.append(_warning(relative_path, "file tạm hoặc bản sao lưu"))
                continue
            try:
                if entry.is_symlink():
                    ignored_count += 1
                    warnings.append(_warning(relative_path, "liên kết tượng trưng"))
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_DEPTH:
                        ignored_count += 1
                        warnings.append(_warning(relative_path, "vượt quá độ sâu 16"))
                        continue
                    if not re.fullmatch(_SLUG, entry.name):
                        ignored_count += 1
                        warnings.append(_warning(relative_path, "tên thư mục không hợp lệ"))
                        continue
                    if isinstance(target, int) and os.name != "nt":
                        try:
                            child_fd = os.open(
                                entry.name,
                                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                                dir_fd=target,
                            )
                        except OSError:
                            ignored_count += 1
                            warnings.append(_warning(relative_path, "không thể mở thư mục an toàn"))
                            continue
                        try:
                            if not walk(child_fd, relative_path, depth + 1):
                                return False
                        finally:
                            os.close(child_fd)
                    else:
                        if not walk(Path(entry.path), relative_path, depth + 1):
                            return False
                    continue
                if not entry.is_file(follow_symlinks=False):
                    ignored_count += 1
                    warnings.append(_warning(relative_path, "không phải file thường"))
                    continue
                if entry.name.endswith("-summary.md"):
                    continue
                match = _FILENAME_RE.fullmatch(entry.name)
                if not match:
                    ignored_count += 1
                    warnings.append(_warning(relative_path, "tên file không hợp lệ"))
                    continue
                metadata = entry.stat(follow_symlinks=False)
            except OSError:
                ignored_count += 1
                warnings.append(_warning(relative_path, "không thể đọc metadata"))
                continue

            version = int(match.group(1))
            slug = match.group(2)
            relative_directory_text = relative_directory.as_posix()
            identity = (
                slug
                if relative_directory_text == "."
                else f"{relative_directory_text}/{slug}"
            )
            candidates.append(
                _Candidate(
                    identity=identity,
                    relative_directory="" if relative_directory_text == "." else relative_directory_text,
                    slug=slug,
                    version=version,
                    relative_path=relative_path.as_posix(),
                    size_bytes=metadata.st_size,
                    modified_at=_modified_at(metadata.st_mtime),
                )
            )
        return True

    if isinstance(root_input, int) and os.name != "nt":
        walk(root_input, Path(), 0)
    else:
        walk(Path(root_input), Path(), 0)
    return candidates, ignored_count, warnings


def _open_root_fd(root: str | Path) -> int | Path | None:
    if os.name == "nt":
        p = Path(root)
        if not p.is_dir():
            if not p.exists():
                return None
            raise PlanFileError
        return p
    try:
        return os.open(root, os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise PlanFileError from error


def scan_plans(root: str | Path) -> PlanManifest:
    """Quét file hợp lệ dưới root với sort và xử lý collision xác định."""

    root_target = _open_root_fd(root)
    if root_target is None:
        return PlanManifest((), 0, (), frozenset())
    try:
        candidates, ignored_count, warnings = _walk_plan_entries(root_target)
    finally:
        if isinstance(root_target, int):
            os.close(root_target)

    by_key: dict[tuple[str, int], list[_Candidate]] = {}
    for candidate in candidates:
        by_key.setdefault((candidate.identity, candidate.version), []).append(candidate)

    collisions = frozenset(key for key, items in by_key.items() if len(items) > 1)
    if collisions:
        for identity, version in sorted(collisions):
            paths = sorted(candidate.relative_path for candidate in by_key[(identity, version)])
            warnings.append(
                f"Đã bỏ qua phiên bản xung đột {identity}@v{version}: {', '.join(paths)}."
            )
            ignored_count += len(by_key[(identity, version)])

    grouped: dict[str, list[_Candidate]] = {}
    for key, items in by_key.items():
        if key not in collisions:
            grouped.setdefault(key[0], []).append(items[0])

    plans: list[PlanGroup] = []
    for identity in sorted(grouped):
        versions = sorted(grouped[identity], key=lambda item: item.version, reverse=True)
        plans.append(
            PlanGroup(
                identity=identity,
                relative_directory=versions[0].relative_directory,
                slug=versions[0].slug,
                versions=tuple(
                    PlanVersion(
                        version=item.version,
                        relative_path=item.relative_path,
                        size_bytes=item.size_bytes,
                        modified_at=item.modified_at,
                        status=(
                            "draft"
                            if len(versions) > 1 and index == 0
                            else "approved"
                        ),
                    )
                    for index, item in enumerate(versions)
                ),
            )
        )
    return PlanManifest(tuple(plans), ignored_count, tuple(warnings), collisions)


def _open_document_fd(root: str | Path, relative_directory: str, filename: str) -> int:
    if os.name == "nt":
        full_path = Path(root) / relative_directory / filename
        if not full_path.is_file():
            raise PlanNotFound
        return os.open(str(full_path), os.O_RDONLY | getattr(os, "O_BINARY", 0))
    root_fd = _open_root_fd(root)
    if root_fd is None or not isinstance(root_fd, int):
        raise PlanNotFound
    directory_fds = [root_fd]
    try:
        current_fd = root_fd
        for segment in filter(None, relative_directory.split("/")):
            next_fd = os.open(
                segment,
                os.O_RDONLY | _O_DIRECTORY | _O_NOFOLLOW,
                dir_fd=current_fd,
            )
            directory_fds.append(next_fd)
            current_fd = next_fd
        return os.open(filename, os.O_RDONLY | _O_NOFOLLOW, dir_fd=current_fd)
    finally:
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def _read_open_file(descriptor: int) -> tuple[bytes, os.stat_result]:
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PlanNotFound
        if metadata.st_size > MAX_FILE_SIZE:
            raise PlanTooLarge
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, MAX_FILE_SIZE + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_FILE_SIZE:
                raise PlanTooLarge
        return b"".join(chunks), metadata
    finally:
        os.close(descriptor)


def read_plan(root: str | Path, identity: str, version: object) -> PlanDocument:
    """Quét lại rồi đọc một file qua directory FD chống traversal và race."""

    relative_directory, slug = validate_identity(identity)
    parsed_version = validate_version(version)
    manifest = scan_plans(root)
    key = (identity, parsed_version)
    if key in manifest.collisions:
        raise PlanCollision
    selected = manifest.version_for(identity, parsed_version)
    if selected is None:
        raise PlanNotFound

    try:
        descriptor = _open_document_fd(
            root, relative_directory, f"v{parsed_version}-{slug}.md"
        )
        content, metadata = _read_open_file(descriptor)
    except PlanFileError:
        raise
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ENOTDIR, errno.ELOOP):
            raise PlanNotFound from error
        raise PlanFileError from error

    try:
        markdown = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidPlanEncoding from error

    return PlanDocument(
        identity=identity,
        version=parsed_version,
        relative_path=selected.relative_path,
        markdown=markdown,
        size_bytes=metadata.st_size,
        modified_at=_modified_at(metadata.st_mtime),
        status=selected.status,
    )
