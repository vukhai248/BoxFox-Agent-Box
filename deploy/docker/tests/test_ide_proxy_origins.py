"""Danh sách origin của ide-proxy: hai origin gốc luôn có, bản chạy thử thêm qua biến.

Bản chạy thử (frontend ở cổng khác, hoặc sau proxy xem trước) có origin khác
`http://localhost:3100`, nên `GET /__box/plans` bị 403 và tab Plan không đọc
được kế hoạch. `BOXFOX_UI_ORIGINS` mở đúng đường đó mà không nới lỏng mặc định.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest

DOCKER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_DIRECTORY))

SPEC = importlib.util.spec_from_file_location("ide_proxy_origins", DOCKER_DIRECTORY / "ide-proxy.py")
assert SPEC and SPEC.loader
ide_proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ide_proxy)

BASE_ORIGINS = ["http://localhost:3100", "http://127.0.0.1:3100",
                "http://localhost:8081", "http://127.0.0.1:8081"]


class ExtraUiOriginsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.previous = os.environ.get("BOXFOX_UI_ORIGINS")
        os.environ.pop("BOXFOX_UI_ORIGINS", None)

    def tearDown(self) -> None:
        if self.previous is None:
            os.environ.pop("BOXFOX_UI_ORIGINS", None)
        else:
            os.environ["BOXFOX_UI_ORIGINS"] = self.previous

    def test_default_allow_list_has_only_the_two_base_origins(self) -> None:
        self.assertEqual(ide_proxy.extra_ui_origins(), [])
        self.assertEqual(ide_proxy.ALLOWED_WS_ORIGINS, BASE_ORIGINS)

    def test_the_environment_adds_trial_origins_without_touching_the_base_ones(self) -> None:
        os.environ["BOXFOX_UI_ORIGINS"] = ("http://localhost:3110, https://preview.example.com/ "
                                           ",http://127.0.0.1:3110")
        self.assertEqual(ide_proxy.extra_ui_origins(),
                         ["http://localhost:3110", "https://preview.example.com", "http://127.0.0.1:3110"])

    def test_blank_entries_are_dropped(self) -> None:
        os.environ["BOXFOX_UI_ORIGINS"] = " , , "
        self.assertEqual(ide_proxy.extra_ui_origins(), [])

    def test_the_base_origins_stay_first_so_production_never_moves(self) -> None:
        os.environ["BOXFOX_UI_ORIGINS"] = "https://preview.example.com"
        merged = BASE_ORIGINS + ide_proxy.extra_ui_origins()
        self.assertEqual(merged[:4], BASE_ORIGINS)
        self.assertIn("https://preview.example.com", merged)


if __name__ == "__main__":
    unittest.main()
