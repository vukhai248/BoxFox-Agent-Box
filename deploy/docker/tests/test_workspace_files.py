"""Kiểm thử module ``workspace_files`` (mặt box) trên thư mục tạm.

Đặt ``AGENT_WORKSPACE`` TRƯỚC khi import để module đọc đúng root; mỗi test lại
dùng một thư mục tạm riêng và patch ``WORKSPACE_ROOT`` để cô lập.
"""

from __future__ import annotations

import atexit
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import zipfile

DOCKER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_DIRECTORY))

# Đặt env TRƯỚC import — workspace_files đọc AGENT_WORKSPACE lúc import. Mọi test
# đều patch WORKSPACE_ROOT cho thư mục tạm riêng, nên thư mục boot này chỉ là giá
# trị mặc định an toàn (dọn qua atexit, tránh ResourceWarning của TemporaryDirectory).
_BOOT_DIR = tempfile.mkdtemp(prefix="wf-boot-")
os.environ["AGENT_WORKSPACE"] = _BOOT_DIR
atexit.register(shutil.rmtree, _BOOT_DIR, ignore_errors=True)

import workspace_files  # noqa: E402
from workspace_files import (  # noqa: E402
    InvalidWorkspacePath,
    WorkspaceConflict,
    WorkspaceEncoding,
    WorkspaceNotFound,
    WorkspaceRangeNotSatisfiable,
    WorkspaceTooLarge,
    build_zip,
    confidentiality_for,
    extract_zip,
    integrity_for,
    list_directory,
    parse_range,
    read_content,
    validate_rel_path,
    write_as_agent,
    write_upload,
)


class WorkspaceFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self._previous_root = workspace_files.WORKSPACE_ROOT
        workspace_files.WORKSPACE_ROOT = self.root

    def tearDown(self) -> None:
        workspace_files.WORKSPACE_ROOT = self._previous_root
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, content: bytes | str = b"data") -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
        return path

    # --- validate_rel_path ---
    def test_validate_rel_path_rejects_unsafe(self) -> None:
        for bad in ("/etc/passwd", "../secret", "a/../b", "a/../../b", "C:\\x", "a\x00b"):
            with self.assertRaises(InvalidWorkspacePath):
                validate_rel_path(bad)

    def test_validate_rel_path_accepts_root_and_normalizes(self) -> None:
        self.assertEqual(validate_rel_path(""), "")
        self.assertEqual(validate_rel_path("a/./b/"), "a/b")
        self.assertEqual(validate_rel_path("src/parser.py"), "src/parser.py")

    def test_validate_rel_path_rejects_too_deep(self) -> None:
        deep = "/".join(["d"] * (workspace_files.MAX_DEPTH + 1))
        with self.assertRaises(InvalidWorkspacePath):
            validate_rel_path(deep)

    # --- list_directory ---
    def test_list_directory_sort_and_skip_symlink_and_generated(self) -> None:
        self.write("zfile.txt", "z")
        self.write("afile.py", "a")
        (self.root / "zdir").mkdir()
        (self.root / "adir").mkdir()
        (self.root / ".generated_artifacts").mkdir()  # phải bị ẩn
        (self.root / ".generated_artifacts" / "thumbnails").mkdir()
        os.symlink(self.write("real.txt", "real"), self.root / "link.txt")
        self.write(".env", "secret")  # file dot thật phải hiện

        listing = list_directory("")
        names = [entry["name"] for entry in listing["entries"]]
        kinds = [entry["kind"] for entry in listing["entries"]]
        # dir trước file, rồi theo tên (so sánh chuỗi: '.env' < 'afile.py' < 'real.txt' < 'zfile.txt')
        self.assertEqual(names, ["adir", "zdir", ".env", "afile.py", "real.txt", "zfile.txt"])
        self.assertEqual(kinds[:2], ["dir", "dir"])
        self.assertNotIn(".generated_artifacts", names)
        self.assertNotIn("link.txt", names)  # symlink bị bỏ

    def test_list_directory_breadcrumb_and_dir_labels(self) -> None:
        (self.root / "frontend" / "src").mkdir(parents=True)
        self.write("frontend/src/App.tsx", "x")
        listing = list_directory("frontend/src")
        self.assertEqual(
            [crumb["path"] for crumb in listing["breadcrumb"]],
            ["", "frontend", "frontend/src"],
        )
        file_entry = next(e for e in listing["entries"] if e["name"] == "App.tsx")
        self.assertEqual(file_entry["kind"], "file")
        self.assertEqual(file_entry["language"], "typescript")
        self.assertEqual(file_entry["ext"], "tsx")
        self.assertEqual(file_entry["integrity"], "duoc_nguoi_dung_cho_phep")
        self.assertEqual(file_entry["confidentiality"], "cong_khai")

    def test_list_directory_truncates_at_max_entries(self) -> None:
        for index in range(workspace_files.MAX_ENTRIES + 5):
            self.write(f"f{index:04d}.txt", b"x")
        listing = list_directory("")
        self.assertTrue(listing.get("truncated"))
        self.assertEqual(len(listing["entries"]), workspace_files.MAX_ENTRIES)

    # --- read_content ---
    def test_read_content_too_large_raises_413(self) -> None:
        self.write("big.txt", b"x" * (workspace_files.MAX_FILE_SIZE + 1))
        with self.assertRaises(WorkspaceTooLarge) as caught:
            read_content("big.txt")
        self.assertEqual(caught.exception.status_code, 413)

    def test_read_content_non_utf8_raises_422(self) -> None:
        self.write("bin.dat", b"\xff\xfe\x00bad")
        with self.assertRaises(WorkspaceEncoding) as caught:
            read_content("bin.dat")
        self.assertEqual(caught.exception.status_code, 422)

    def test_read_content_returns_text(self) -> None:
        self.write("a.py", "print('hi')\n")
        payload = read_content("a.py")
        self.assertEqual(payload["content"], "print('hi')\n")
        self.assertEqual(payload["language"], "python")
        self.assertFalse(payload["binary"])
        self.assertEqual(payload["sizeBytes"], len("print('hi')\n"))

    def test_read_content_not_a_regular_file_raises_404(self) -> None:
        (self.root / "sub").mkdir()
        with self.assertRaises(WorkspaceNotFound):
            read_content("sub")

    # --- provenance heuristic ---
    def test_integrity_for_vendor_and_plan(self) -> None:
        self.assertEqual(integrity_for("vendor/lib/README.md"), "khong_tin_duoc")
        self.assertEqual(integrity_for("node_modules/x/index.js"), "khong_tin_duoc")
        self.assertEqual(integrity_for("dist/main.js"), "khong_tin_duoc")
        self.assertEqual(integrity_for("plan.md"), "khong_tin_duoc")
        # basename == plan.md ở bất kỳ thư mục nào cũng không tin (theo heuristic)
        self.assertEqual(integrity_for("docs/plan.md"), "khong_tin_duoc")
        self.assertEqual(integrity_for("src/parser.py"), "duoc_nguoi_dung_cho_phep")

    def test_confidentiality_for_secret_basenames(self) -> None:
        self.assertEqual(confidentiality_for(".env"), "bi_mat")
        self.assertEqual(confidentiality_for(".env.local"), "bi_mat")
        self.assertEqual(confidentiality_for("server.key"), "bi_mat")
        self.assertEqual(confidentiality_for("cert.pem"), "bi_mat")
        self.assertEqual(confidentiality_for("id_rsa"), "bi_mat")
        self.assertEqual(confidentiality_for("id_ed25519"), "bi_mat")
        self.assertEqual(confidentiality_for("README.md"), "cong_khai")
        # .env giữ integrity tin cậy nhưng confidentiality bí mật (khớp mock)
        self.assertEqual(integrity_for(".env"), "duoc_nguoi_dung_cho_phep")
        self.assertEqual(confidentiality_for(".env"), "bi_mat")

    # --- zip roundtrip + zip-slip ---
    def test_build_zip_and_extract_zip_roundtrip(self) -> None:
        self.write("a.txt", "hello")
        (self.root / "zips").mkdir()
        (self.root / "sub").mkdir()
        self.write("sub/b.txt", "world")
        data = build_zip(["a.txt", "sub"])
        # zip phải là archive hợp lệ và chứa đúng arcname tương đối
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertIn("a.txt", zf.namelist())
            self.assertIn("sub/b.txt", zf.namelist())

        (self.root / "zips" / "round.zip").write_bytes(data)
        result = extract_zip("zips/round.zip")  # giải nén vào "zips"
        self.assertEqual(result["extracted"], 2)
        self.assertEqual((self.root / "zips" / "a.txt").read_text(), "hello")
        self.assertEqual((self.root / "zips" / "sub" / "b.txt").read_text(), "world")

    def test_extract_zip_skips_existing_files(self) -> None:
        (self.root / "zips").mkdir()
        # File đích đã tồn tại sẵn → extract phải SKIP, không ghi đè.
        (self.root / "zips" / "note.txt").write_text("PREEXISTING")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("note.txt", "NEW")
        (self.root / "zips" / "dup.zip").write_bytes(buf.getvalue())
        result = extract_zip("zips/dup.zip")
        self.assertEqual(result["extracted"], 0)
        self.assertEqual(result["skipped"], 1)
        # Nội dung cũ được giữ nguyên (không bị ghi đè)
        self.assertEqual((self.root / "zips" / "note.txt").read_text(), "PREEXISTING")

    def test_extract_zip_rejects_zip_slip(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("../evil.txt", "pwned")
        (self.root / "zips").mkdir()
        (self.root / "zips" / "evil.zip").write_bytes(buf.getvalue())
        with self.assertRaises(WorkspaceConflict) as caught:
            extract_zip("zips/evil.zip")
        self.assertEqual(caught.exception.status_code, 409)
        # fileescape không thoát ra ngoài
        self.assertFalse((self.root / "evil.txt").exists())

    def test_extract_zip_rejects_absolute_member(self) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("/etc/evil.txt", "pwned")
        (self.root / "zips").mkdir()
        (self.root / "zips" / "abs.zip").write_bytes(buf.getvalue())
        with self.assertRaises(WorkspaceConflict):
            extract_zip("zips/abs.zip")

    def test_build_zip_rejects_bad_path(self) -> None:
        with self.assertRaises(InvalidWorkspacePath):
            build_zip(["../etc/passwd"])
        with self.assertRaises(InvalidWorkspacePath):
            build_zip(["/etc/passwd"])
        with self.assertRaises(WorkspaceNotFound):
            build_zip(["missing.txt"])

    # --- parse_range ---
    def test_parse_range_valid_forms(self) -> None:
        size = 1000
        self.assertEqual(parse_range("bytes=0-99", size), (0, 99))
        self.assertEqual(parse_range("bytes=0-", size), (0, 999))
        self.assertEqual(parse_range("bytes=-16", size), (984, 999))
        self.assertEqual(parse_range("bytes=500-2000", size), (500, 999))  # end kẹp về size-1
        self.assertIsNone(parse_range(None, size))
        self.assertIsNone(parse_range("", size))

    def test_parse_range_invalid_raises_416(self) -> None:
        size = 32
        with self.assertRaises(WorkspaceRangeNotSatisfiable):
            parse_range("bytes=100-200", size)  # start >= size
        with self.assertRaises(WorkspaceRangeNotSatisfiable):
            parse_range("bytes=abc", size)
        with self.assertRaises(WorkspaceRangeNotSatisfiable):
            parse_range("bytes=-0", size)
        with self.assertRaises(WorkspaceRangeNotSatisfiable):
            parse_range("bytes=10-5", size)  # end < start

    # --- write_upload / write_as_agent ---
    def test_write_upload_creates_file_with_mode_and_returns_path(self) -> None:
        result = write_upload("", "uploaded.txt", [b"hello world"], 11)
        self.assertEqual(result, {"path": "uploaded.txt", "sizeBytes": 11})
        path = self.root / "uploaded.txt"
        self.assertTrue(path.exists())
        self.assertEqual(path.read_text(), "hello world")
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        if os.geteuid() == 0:
            self.assertEqual(path.stat().st_uid, workspace_files.AGENT_UID)
            self.assertEqual(path.stat().st_gid, workspace_files.AGENT_GID)

    def test_write_upload_into_subdir(self) -> None:
        (self.root / "sub").mkdir()
        result = write_upload("sub", "x.bin", [b"\x00\x01"], 2)
        self.assertEqual(result["path"], "sub/x.bin")
        self.assertEqual((self.root / "sub" / "x.bin").read_bytes(), b"\x00\x01")

    def test_write_upload_rejects_bad_filename(self) -> None:
        for bad in ("", ".", "..", "a/b", "a\\b", "a\x00b", "./x"):
            with self.assertRaises(InvalidWorkspacePath):
                write_upload("", bad, [b"x"], 1)

    def test_write_upload_missing_target_dir_raises_404(self) -> None:
        with self.assertRaises(WorkspaceNotFound):
            write_upload("nope", "x.txt", [b"x"], 1)

    def test_write_as_agent_refuses_symlink_target(self) -> None:
        os.symlink(self.write("real.txt", "r"), self.root / "link.txt")
        with self.assertRaises(WorkspaceConflict):
            write_as_agent("", "link.txt", [b"pwned"])

    def test_write_upload_enforces_size_hint(self) -> None:
        with self.assertRaises(WorkspaceTooLarge):
            write_upload("", "big.txt", [b"x"], workspace_files.MAX_UPLOAD_SIZE + 1)


if __name__ == "__main__":
    unittest.main()
