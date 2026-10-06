"""Kiểm thử `box-power on` khi tệp trạng thái không còn đúng sự thật.

BUG đã đo (06/10/2026): `/run/box-power-state` nằm trên lớp ghi của container nên
sống qua `docker restart`. Entrypoint gọi `box-power on`, đọc thấy "on" cũ và bỏ
qua việc chạy `box-services.sh` ⇒ Xvnc/code-server/tty-bridge đều chết trong khi
giao diện vẫn hiện "Machine ON". Tab IDE báo
`Proxy error: <urlopen error [Errno 111] Connection refused>`, tab Terminal báo
`NOT CONNECTED`.

Ca test chạy chính script thật (`deploy/docker/box-power`) trong thư mục tạm, với
`pgrep`/`pkill`/`gosu` giả đặt trước trong PATH — nhờ vậy kiểm được cả hai chiều:
"trạng thái ON + dịch vụ sống" (bỏ qua, giữ nguyên hành vi cũ) và "trạng thái ON +
dịch vụ chết" (phải khởi động lại).
"""

from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

DOCKER_DIRECTORY = Path(__file__).resolve().parents[1]
BOX_POWER = DOCKER_DIRECTORY / "box-power"
BOX_ENTRYPOINT = DOCKER_DIRECTORY / "box-entrypoint.sh"
STATE_FILE_IN_BOX = "/run/box-power-state"


class BoxPowerStaleStateTest(unittest.TestCase):
    """`box-power on` chỉ được tin tệp trạng thái khi dịch vụ còn sống."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name)
        self.state = self.root / "box-power-state"
        self.marker = self.root / "services-started"
        self.pkill_log = self.root / "pkill.log"
        self.bin = self.root / "bin"
        self.bin.mkdir()

        # Dịch vụ giả: ghi dấu vết rồi ngủ để tiến trình còn sống như thật.
        self.services = self.root / "box-services.sh"
        self._write_executable(
            self.services,
            "#!/bin/sh\n"
            f"echo started >> {self.marker}\n"
            "sleep 30\n",
        )

        # `gosu agent <lệnh>` → bỏ tham số user rồi chạy lệnh.
        self._write_executable(
            self.bin / "gosu",
            '#!/bin/sh\nshift\nexec "$@"\n',
        )

        # `pgrep` giả: đọc kết quả mong muốn từ BOX_POWER_TEST_ALIVE.
        self._write_executable(
            self.bin / "pgrep",
            '#!/bin/sh\n[ "${BOX_POWER_TEST_ALIVE:-0}" = "1" ]\n',
        )

        # `pkill` giả: ghi lại pattern đã gọi, luôn thành công.
        self._write_executable(
            self.bin / "pkill",
            f'#!/bin/sh\necho "$@" >> {self.pkill_log}\nexit 0\n',
        )

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _run_box_power(self, action: str, *, alive: bool) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "PATH": f"{self.bin}:{environment['PATH']}",
                "HOME": str(self.root),
                "BOX_POWER_STATE_FILE": str(self.state),
                "BOX_POWER_SERVICES_BIN": str(self.services),
                "BOX_POWER_GOSU_BIN": str(self.bin / "gosu"),
                "BOX_POWER_AGENT_HOME": str(self.root),
                "BOX_POWER_TEST_ALIVE": "1" if alive else "0",
            }
        )
        return subprocess.run(
            ["/bin/sh", str(BOX_POWER), action],
            capture_output=True,
            text=True,
            env=environment,
            timeout=30,
            check=False,
        )

    def _started_services(self) -> int:
        if not self.marker.exists():
            return 0
        return len(self.marker.read_text(encoding="utf-8").splitlines())

    def _wait_for_started_services(self, expected: int, timeout: float = 5.0) -> int:
        """`box-power on` thả box-services.sh vào nền ⇒ chờ dấu vết thay vì đoán."""
        deadline = time.monotonic() + timeout
        started = self._started_services()
        while started < expected and time.monotonic() < deadline:
            time.sleep(0.05)
            started = self._started_services()
        return started

    def _stop_leftover_services(self) -> None:
        for process in subprocess.run(
            ["pgrep", "-f", str(self.services)],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.split():
            subprocess.run(["kill", process], check=False)

    # ------------------------------------------------------------------ #
    # Ca chính: tái hiện đúng chuỗi sự kiện đã làm chết IDE/Terminal.
    # ------------------------------------------------------------------ #

    def test_state_says_on_but_services_are_dead_restarts_them(self) -> None:
        self.state.write_text("on\n", encoding="utf-8")

        result = self._run_box_power("on", alive=False)
        self.addCleanup(self._stop_leftover_services)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("bỏ qua", result.stdout)
        self.assertIn("khởi động lại", result.stdout)
        self.assertEqual(self._wait_for_started_services(1), 1, "phải chạy box-services.sh một lần")
        self.assertTrue(self.pkill_log.exists(), "phải dọn tiến trình cũ trước khi khởi động")
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "on")

    def test_state_says_on_and_services_alive_skips_start(self) -> None:
        self.state.write_text("on\n", encoding="utf-8")

        result = self._run_box_power("on", alive=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("đã ON từ trước — bỏ qua", result.stdout)
        self.assertEqual(self._started_services(), 0, "không được khởi động lại khi máy đang chạy")

    def test_missing_state_file_starts_services(self) -> None:
        result = self._run_box_power("on", alive=False)
        self.addCleanup(self._stop_leftover_services)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._wait_for_started_services(1), 1)
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "on")

    def test_power_off_writes_state_and_stops_services(self) -> None:
        self.state.write_text("on\n", encoding="utf-8")

        result = self._run_box_power("off", alive=True)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "off")
        self.assertTrue(self.pkill_log.exists())

    def test_unknown_action_exits_two(self) -> None:
        result = self._run_box_power("sideways", alive=False)

        self.assertEqual(result.returncode, 2)

    # ------------------------------------------------------------------ #
    # Entrypoint: container vừa khởi động thì không dịch vụ nào đang chạy.
    # ------------------------------------------------------------------ #

    def test_entrypoint_clears_power_state_before_starting_services(self) -> None:
        entrypoint = BOX_ENTRYPOINT.read_text(encoding="utf-8")
        remove_at = entrypoint.find(f"rm -f {STATE_FILE_IN_BOX}")
        power_at = entrypoint.find("box-power \"${BOX_DEFAULT_POWER:-on}\"")

        self.assertNotEqual(remove_at, -1, f"entrypoint phải xoá {STATE_FILE_IN_BOX} khi container khởi động")
        self.assertNotEqual(power_at, -1, "entrypoint phải gọi box-power")
        self.assertLess(remove_at, power_at, "phải xoá dấu vết trước khi gọi box-power")


if __name__ == "__main__":
    unittest.main()
