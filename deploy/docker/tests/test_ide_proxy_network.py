"""Kiểm thử HTTP cho endpoint network/power của ide-proxy (Cách C).

Chứng minh lỗ hổng "process trong box giả mạo Origin để tự bật mạng" đã đóng:
/__box/network + /__box/power CHỈ nhận shared-secret `X-BoxFox-Api-Key`, không
nhận Origin. Các lần chạy box-firewall/box-power được mock qua `subprocess.run`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

DOCKER_DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DOCKER_DIRECTORY))

SPEC = importlib.util.spec_from_file_location("ide_proxy", DOCKER_DIRECTORY / "ide-proxy.py")
assert SPEC and SPEC.loader
ide_proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ide_proxy)

ORIGIN_OK = "http://localhost:3100"
ORIGIN_BAD = "https://malicious.example"
SECRET_OK = "box-secret-123"


class IdeProxyNetworkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.server = ide_proxy.ThreadingHTTPServer(("127.0.0.1", 0), ide_proxy.ProxyHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self._original_key = ide_proxy.BOXFOX_API_KEY
        ide_proxy.BOXFOX_API_KEY = SECRET_OK

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        ide_proxy.BOXFOX_API_KEY = self._original_key

    def _toggle(self, path: str, body: str, headers: dict) -> tuple[int, str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body.encode("utf-8"),
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    def _get(self, path: str, headers: dict) -> tuple[int, str]:
        request = urllib.request.Request(f"{self.base_url}{path}", method="GET", headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8")

    # --- _secret_ok: fail-closed / so khớp ---

    def test_secret_ok_fail_closed_when_key_empty(self) -> None:
        ide_proxy.BOXFOX_API_KEY = ""
        handler = ide_proxy.ProxyHandler
        instance = handler.__new__(handler)
        instance.headers = {}
        self.assertFalse(instance._secret_ok())

    def test_secret_ok_match_and_mismatch(self) -> None:
        handler = ide_proxy.ProxyHandler

        match = handler.__new__(handler)
        match.headers = {"X-BoxFox-Api-Key": SECRET_OK}
        self.assertTrue(match._secret_ok())

        mismatch = handler.__new__(handler)
        mismatch.headers = {"X-BoxFox-Api-Key": "wrong"}
        self.assertFalse(mismatch._secret_ok())

        absent = handler.__new__(handler)
        absent.headers = {}
        self.assertFalse(absent._secret_ok())

    # --- network: chỉ nhận secret, KHÔNG nhận Origin ---

    def test_network_no_secret_denied(self) -> None:
        status, body = self._toggle("/__box/network", "on", {})
        self.assertEqual(status, 403)
        self.assertIn("X-BoxFox-Api-Key", body)

    def test_network_wrong_secret_denied(self) -> None:
        status, _ = self._toggle("/__box/network", "on", {"X-BoxFox-Api-Key": "wrong"})
        self.assertEqual(status, 403)

    def test_network_origin_only_is_still_denied(self) -> None:
        """Điểm cốt lõi: chỉ Origin hợp lệ (process trong box giả mạo được) KHÔNG đủ."""
        status, _ = self._toggle("/__box/network", "on", {"Origin": ORIGIN_OK})
        self.assertEqual(status, 403)

    def test_network_foreign_origin_with_no_secret_denied(self) -> None:
        status, _ = self._toggle("/__box/network", "on", {"Origin": ORIGIN_BAD})
        self.assertEqual(status, 403)

    def test_network_correct_secret_calls_firewall(self) -> None:
        with patch("subprocess.run") as run, patch.object(
            ide_proxy, "read_net_state", return_value="on"
        ):
            ide_proxy.FIREWALL_BIN = "/usr/local/sbin/box-firewall"
            status, body = self._toggle(
                "/__box/network", "on", {"X-BoxFox-Api-Key": SECRET_OK}
            )
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"network": "on"})
        run.assert_called_once_with(["/usr/local/sbin/box-firewall", "on"], check=False)

    def test_network_correct_secret_with_forged_origin_still_works(self) -> None:
        """Secret đúng thắng cả khi Origin bị giả — nhưng chỉ secret mới mở được."""
        with patch("subprocess.run"), patch.object(
            ide_proxy, "read_net_state", return_value="off"
        ):
            status, _ = self._toggle(
                "/__box/network", "off", {"X-BoxFox-Api-Key": SECRET_OK, "Origin": ORIGIN_BAD}
            )
        self.assertEqual(status, 200)

    # --- power: cùng cơ chế ---

    def test_power_no_secret_denied(self) -> None:
        status, _ = self._toggle("/__box/power", "off", {})
        self.assertEqual(status, 403)

    def test_power_origin_only_denied(self) -> None:
        status, _ = self._toggle("/__box/power", "off", {"Origin": ORIGIN_OK})
        self.assertEqual(status, 403)

    def test_power_correct_secret_calls_power(self) -> None:
        with patch("subprocess.run") as run, patch.object(
            ide_proxy, "read_power_state", return_value="off"
        ):
            ide_proxy.POWER_BIN = "/usr/local/sbin/box-power"
            status, body = self._toggle("/__box/power", "off", {"X-BoxFox-Api-Key": SECRET_OK})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"power": "off"})
        run.assert_called_once_with(["/usr/local/sbin/box-power", "off"], check=False)

    # --- method + body validation ---

    def test_network_get_method_not_allowed(self) -> None:
        status, _ = self._get("/__box/network", {"X-BoxFox-Api-Key": SECRET_OK})
        self.assertEqual(status, 405)

    def test_network_bad_body_not_toggled(self) -> None:
        with patch("subprocess.run") as run:
            status, body = self._toggle(
                "/__box/network", "maybe", {"X-BoxFox-Api-Key": SECRET_OK}
            )
        self.assertEqual(status, 400)
        self.assertIn("'on'", body)
        run.assert_not_called()

    def test_network_invalid_content_length_not_toggled(self) -> None:
        request = urllib.request.Request(
            f"{self.base_url}/__box/network",
            data=b"on",
            method="POST",
            headers={"X-BoxFox-Api-Key": SECRET_OK, "Content-Length": "abc"},
        )
        with patch("subprocess.run") as run:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        run.assert_not_called()

    # --- status read-only giữ nguyên Origin gate ---

    def test_status_with_origin_ok(self) -> None:
        with patch.object(ide_proxy, "read_net_state", return_value="off"), patch.object(
            ide_proxy, "read_power_state", return_value="on"
        ):
            status, body = self._get("/__box/status", {"Origin": ORIGIN_OK})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"network": "off", "power": "on"})

    def test_status_without_origin_denied(self) -> None:
        status, _ = self._get("/__box/status", {})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
