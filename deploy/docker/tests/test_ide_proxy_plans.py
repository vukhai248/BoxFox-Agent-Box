"""Kiểm thử HTTP cho endpoint plan của ide-proxy."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

DOCKER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_DIRECTORY))

SPEC = importlib.util.spec_from_file_location("ide_proxy", DOCKER_DIRECTORY / "ide-proxy.py")
assert SPEC and SPEC.loader
ide_proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ide_proxy)


class IdeProxyPlansTest(unittest.TestCase):
    """Xác minh CORS, mã lỗi và payload của API chỉ-đọc."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        (self.root / "v1-demo.md").write_bytes(b"# Demo\n")
        self.previous_root = ide_proxy.PLAN_ROOT
        ide_proxy.PLAN_ROOT = str(self.root)
        self.server = ide_proxy.ThreadingHTTPServer(("127.0.0.1", 0), ide_proxy.ProxyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        ide_proxy.PLAN_ROOT = self.previous_root
        self.temporary_directory.cleanup()

    def request(self, path: str, method: str = "GET", origin: str = "http://localhost:3100"):
        request = urllib.request.Request(
            f"{self.base_url}{path}", method=method, headers={"Origin": origin}
        )
        return urllib.request.urlopen(request)

    def test_lists_and_reads_plan_with_no_store_cors(self) -> None:
        with self.request("/__box/plans") as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "http://localhost:3100")
            self.assertEqual(response.headers.get_content_type(), "application/json")
            self.assertIn('"identity": "demo"', body)

        with self.request("/__box/plans/content?identity=demo&version=1") as response:
            body = response.read().decode("utf-8")
            self.assertEqual(response.status, 200)
            self.assertIn('"markdown": "# Demo\\n"', body)
            self.assertIn('"label": "v1"', body)
            self.assertNotIn(str(self.root), body)

    def test_rejects_invalid_requests_and_foreign_origin(self) -> None:
        for path, method, expected_status in (
            ("/__box/plans?path=/etc/passwd", "GET", 400),
            ("/__box/plans/content?identity=../etc&version=1", "GET", 400),
            ("/__box/plans/content?identity=demo&version=1", "POST", 405),
        ):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request(path, method)
            self.assertEqual(caught.exception.code, expected_status)
            self.assertEqual(caught.exception.headers["Cache-Control"], "no-store")

        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/__box/plans", origin="https://malicious.example")
        self.assertEqual(caught.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
