"""Kiểm thử scanner và đọc file kế hoạch an toàn."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import plan_files
from plan_files import (
    InvalidPlanEncoding,
    InvalidPlanRequest,
    PlanNotFound,
    PlanTooLarge,
    read_plan,
    scan_plans,
    validate_identity,
    validate_version,
)


class PlanFilesTest(unittest.TestCase):
    """Kiểm thử hợp đồng quét và bảo vệ đọc file."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def write(self, relative_path: str, content: bytes | str = "# Plan\n") -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return path

    def test_groups_root_and_nested_identity_with_numeric_sort(self) -> None:
        self.write("v1-login.md")
        self.write("designs/v1-login.md")
        self.write("subplans/v1-login.md")
        self.write("subplans/v2-login.md")
        self.write("subplans/v10-login.md")

        manifest = scan_plans(self.root)

        self.assertEqual(
            [group.identity for group in manifest.plans],
            ["designs/login", "login", "subplans/login"],
        )
        nested = manifest.plans[2]
        self.assertEqual([item.version for item in nested.versions], [10, 2, 1])
        self.assertEqual([item.status for item in nested.versions], ["draft", "approved", "approved"])
        self.assertEqual(manifest.plans[1].versions[0].status, "approved")

    def test_ignores_summary_malformed_hidden_temporary_and_symlinks(self) -> None:
        self.write("v1-good.md")
        for name in (
            "v2-good-summary.md",
            "v01-good.md",
            "v1-Good.md",
            "v1-good.md.tmp",
            ".hidden/v1-hidden.md",
            "subplans/.v2-good.md",
            "notes.txt",
        ):
            self.write(name)
        outside = self.write("outside.md")
        os.symlink(outside, self.root / "v2-link.md")
        os.symlink(self.root / "subplans", self.root / "linked-directory")

        manifest = scan_plans(self.root)

        self.assertEqual([group.identity for group in manifest.plans], ["good"])
        self.assertGreaterEqual(manifest.ignored_count, 7)
        self.assertFalse(any("tóm tắt" in warning for warning in manifest.warnings))
        self.assertTrue(any("liên kết tượng trưng" in warning for warning in manifest.warnings))

    def test_rejects_invalid_identity_and_version(self) -> None:
        for identity in ("", "/login", "../login", "designs//login", "Login", "a_b"):
            with self.assertRaises(InvalidPlanRequest):
                validate_identity(identity)
        for version in (0, "01", "0", "-1", "abc", "12345678901", True):
            with self.assertRaises(InvalidPlanRequest):
                validate_version(version)

    def test_read_returns_metadata_and_rejects_traversal(self) -> None:
        self.write("subplans/v2-login.md", "# Đăng nhập\n")

        document = read_plan(self.root, "subplans/login", "2")

        self.assertEqual(document.relative_path, "subplans/v2-login.md")
        self.assertEqual(document.markdown, "# Đăng nhập\n")
        self.assertEqual(document.to_payload()["label"], "v2")
        with self.assertRaises(InvalidPlanRequest):
            read_plan(self.root, "../etc/passwd", 1)
        with self.assertRaises(PlanNotFound):
            read_plan(self.root, "subplans/login", 3)

    def test_does_not_list_or_read_version_with_more_than_ten_digits(self) -> None:
        self.write("v1234567890-limit.md")
        self.write("v12345678901-too-large.md")

        manifest = scan_plans(self.root)

        self.assertEqual([group.identity for group in manifest.plans], ["limit"])
        self.assertTrue(any("too-large" in warning for warning in manifest.warnings))
        with self.assertRaises(InvalidPlanRequest):
            read_plan(self.root, "too-large", "12345678901")

    def test_rejects_large_and_invalid_utf8_content(self) -> None:
        self.write("v1-large.md", b"x" * (plan_files.MAX_FILE_SIZE + 1))
        self.write("v1-invalid.md", b"\xff")

        with self.assertRaises(PlanTooLarge):
            read_plan(self.root, "large", 1)
        with self.assertRaises(InvalidPlanEncoding):
            read_plan(self.root, "invalid", 1)

    @unittest.skipIf(os.name == "nt", "Symlink tests require POSIX environment")
    def test_does_not_follow_file_or_directory_symlink_during_read(self) -> None:
        self.write("v1-safe.md")
        outside = self.write("outside.md", "bí mật")
        os.symlink(outside, self.root / "v1-escaped.md")
        os.symlink(self.root, self.root / "loop")

        with self.assertRaises(PlanNotFound):
            read_plan(self.root, "escaped", 1)
        self.assertEqual(read_plan(self.root, "safe", 1).markdown, "# Plan\n")

    @unittest.skipIf(os.name == "nt", "Symlink tests require POSIX environment")
    def test_symlink_swap_after_scan_cannot_be_read(self) -> None:
        target = self.write("v1-safe.md", "# An toàn\n")
        original_scan = plan_files.scan_plans

        def swap_then_scan(root: str | Path):
            manifest = original_scan(root)
            target.unlink()
            os.symlink("/etc/passwd", target)
            return manifest

        with patch.object(plan_files, "scan_plans", side_effect=swap_then_scan):
            with self.assertRaises(PlanNotFound):
                read_plan(self.root, "safe", 1)

    @unittest.skipIf(os.name == "nt", "Symlink tests require POSIX environment")
    def test_directory_symlink_swap_does_not_disclose_outside_metadata(self) -> None:
        self.write("plans/v1-safe.md")
        outside_tmp = tempfile.TemporaryDirectory()
        try:
            outside_directory = Path(outside_tmp.name) / "outside"
            outside_directory.mkdir()
            (outside_directory / "v1-secret.md").write_text("# Bí mật\n", encoding="utf-8")
            original_open = plan_files.os.open
            swapped = False

            def swap_before_open(name, flags, *args, **kwargs):
                nonlocal swapped
                if name == "plans" and kwargs.get("dir_fd") is not None and not swapped:
                    swapped = True
                    (self.root / "plans").rename(self.root / "plans-cu")
                    os.symlink(outside_directory, self.root / "plans")
                return original_open(name, flags, *args, **kwargs)

            with patch.object(plan_files.os, "open", side_effect=swap_before_open):
                manifest = scan_plans(self.root)

            self.assertEqual(manifest.plans, ())
            self.assertTrue(any("không thể mở thư mục an toàn" in warning for warning in manifest.warnings))
            self.assertNotIn("secret", " ".join(manifest.warnings))
        finally:
            outside_tmp.cleanup()

    def test_depth_and_entry_limits_return_warnings_without_hanging(self) -> None:
        deep = "/".join(["aaa"] * (plan_files.MAX_DEPTH + 1))
        self.write(f"{deep}/v1-too-deep.md")
        for index in range(plan_files.MAX_ENTRIES + 1):
            self.write(f"many/v1-item-{index}.md")

        manifest = scan_plans(self.root)

        self.assertTrue(any("độ sâu" in warning for warning in manifest.warnings))
        self.assertTrue(any("2000" in warning for warning in manifest.warnings))

    def test_collision_is_fail_closed(self) -> None:
        first = plan_files._Candidate(
            "login", "", "login", 1, "v1-login.md", 1, "2026-01-01T00:00:00Z"
        )
        second = plan_files._Candidate(
            "login", "", "login", 1, "other/v1-login.md", 1, "2026-01-01T00:00:00Z"
        )
        with patch.object(plan_files, "_walk_plan_entries", return_value=([first, second], 0, [])):
            manifest = scan_plans(self.root)

        self.assertEqual(manifest.plans, ())
        self.assertIn(("login", 1), manifest.collisions)
        self.assertEqual(manifest.ignored_count, 2)


if __name__ == "__main__":
    unittest.main()
