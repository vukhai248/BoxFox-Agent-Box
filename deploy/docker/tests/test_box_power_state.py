"""Kiểm thử `box-power on` khi tệp trạng thái không còn đúng sự thật.

BUG đã đo (06/10/2026): `/run/box-power-state` nằm trên lớp ghi của container nên
sống qua `docker restart`. Entrypoint gọi `box-power on`, đọc thấy "on" cũ và bỏ
qua việc chạy `box-services.sh` ⇒ Xvnc/code-server/tty-bridge đều chết trong khi
giao diện vẫn hiện "Machine ON". Tab IDE báo
`Proxy error: <urlopen error [Errno 111] Connection refused>`, tab Terminal báo
`NOT CONNECTED`.

Ca test chạy chính script thật (`deploy/docker/box-power`) trong thư mục tạm, với
`pgrep`/`pkill`/`gosu` giả đặt trước trong PATH. Hai cái giả đó KHÔNG trả lời một
cờ chung: `pgrep` giả khớp theo từng mẫu và ghi lại mọi lượt hỏi, `pkill` giả ghi
lại mọi mẫu đã hạ — nhờ vậy bỏ sót một nhóm dịch vụ trong `services_alive` hay
trong `stop_services` đều làm đỏ test, thay vì lọt qua.
"""

from __future__ import annotations

import fcntl
import os
import shutil
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

# Bản sao có chủ ý của mẫu trong `box-power`: đổi mẫu ở script mà quên đổi ở đây
# thì test đỏ ngay, không im lặng cho qua.
XVNC = "^Xvnc :99"
CODE_SERVER = "^/opt/code-server/.*--bind-addr"
TTY_BRIDGE = "^/usr/bin/python3 /usr/local/bin/tty-bridge\\.py"
WEBSOCKIFY = "^(/usr/bin/python3 )?(/usr/bin/)?websockify 6080"
XFCE = "^(dbus-launch --exit-with-session )?xfce4-session$"
ALL_SERVICE_PATTERNS = (XVNC, WEBSOCKIFY, XFCE, CODE_SERVER, TTY_BRIDGE)


class BoxPowerStaleStateTest(unittest.TestCase):
    """`box-power on` chỉ được tin tệp trạng thái khi dịch vụ còn sống."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.root = Path(self._temporary_directory.name)
        self.state = self.root / "box-power-state"
        self.marker = self.root / "services-started"
        self.pkill_log = self.root / "pkill.log"
        self.pgrep_log = self.root / "pgrep.log"
        self.alive_patterns = self.root / "alive-patterns"
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
        self.services_script_pattern = f"^/bin/sh {self.services}$"

        # `gosu agent <lệnh>` → bỏ tham số user rồi chạy lệnh.
        self._write_executable(
            self.bin / "gosu",
            '#!/bin/sh\nshift\nexec "$@"\n',
        )

        # `pgrep` giả: mẫu nào có trong tệp "alive-patterns" thì coi là đang sống;
        # mọi lượt hỏi đều được ghi lại để test kiểm được "có hỏi nhóm nào không".
        self._write_executable(
            self.bin / "pgrep",
            "#!/bin/sh\n"
            'pattern="$2"\n'
            f'echo "$pattern" >> {self.pgrep_log}\n'
            f'grep -Fxq -- "$pattern" {self.alive_patterns}\n',
        )

        # `pkill` giả: ghi lại mẫu đã hạ, luôn thành công.
        self._write_executable(
            self.bin / "pkill",
            f'#!/bin/sh\necho "$2" >> {self.pkill_log}\nexit 0\n',
        )

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def _set_alive(self, patterns: tuple[str, ...]) -> None:
        self.alive_patterns.write_text("\n".join(patterns) + "\n", encoding="utf-8")

    def _run_box_power(self, action: str) -> subprocess.CompletedProcess[str]:
        environment = dict(os.environ)
        environment.update(
            {
                "PATH": f"{self.bin}:{environment['PATH']}",
                "HOME": str(self.root),
                "BOX_POWER_STATE_FILE": str(self.state),
                "BOX_POWER_SERVICES_BIN": str(self.services),
                "BOX_POWER_AGENT_HOME": str(self.root),
                "BOX_POWER_LOCK_FILE": str(self.root / "box-power.lock"),
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

    def _logged(self, path: Path) -> list[str]:
        if not path.exists():
            return []
        return [line for line in path.read_text(encoding="utf-8").splitlines() if line]

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
        self._set_alive(())  # không dịch vụ nào sống — đúng cảnh sau container restart

        result = self._run_box_power("on")
        self.addCleanup(self._stop_leftover_services)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("bỏ qua", result.stdout)
        self.assertIn("khởi động lại", result.stdout)
        self.assertEqual(self._wait_for_started_services(1), 1, "phải chạy box-services.sh một lần")
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "on")
        killed = self._logged(self.pkill_log)
        self.assertIn(self.services_script_pattern, killed, "phải hạ box-services.sh đang chạy dở")
        for pattern in ALL_SERVICE_PATTERNS:
            self.assertIn(pattern, killed, f"phải dọn tiến trình khớp {pattern!r}")

    def test_each_dead_service_group_forces_a_restart(self) -> None:
        """Thiếu BẤT KỲ nhóm nào (IDE, Terminal, Machine) cũng phải khởi động lại."""
        self.state.write_text("on\n", encoding="utf-8")

        for missing in (CODE_SERVER, TTY_BRIDGE, XVNC, WEBSOCKIFY, XFCE):
            with self.subTest(missing=missing):
                self.marker.unlink(missing_ok=True)
                self._set_alive(tuple(p for p in ALL_SERVICE_PATTERNS if p != missing))

                result = self._run_box_power("on")
                self.addCleanup(self._stop_leftover_services)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("bỏ qua", result.stdout, f"{missing!r} chết mà vẫn bỏ qua")
                self.assertEqual(self._wait_for_started_services(1), 1)

    def test_state_says_on_and_all_services_alive_skips_start(self) -> None:
        self.state.write_text("on\n", encoding="utf-8")
        self._set_alive(ALL_SERVICE_PATTERNS)

        result = self._run_box_power("on")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("đã ON từ trước — bỏ qua", result.stdout)
        self.assertEqual(self._started_services(), 0, "không được khởi động lại khi máy đang chạy")
        self.assertEqual(self._logged(self.pkill_log), [], "đường bỏ qua không được hạ gì")
        self.assertEqual(
            set(self._logged(self.pgrep_log)),
            set(ALL_SERVICE_PATTERNS),
            "phải hỏi đủ năm nhóm dịch vụ trước khi kết luận là đang ON",
        )

    def test_missing_state_file_starts_services(self) -> None:
        self._set_alive(ALL_SERVICE_PATTERNS)

        result = self._run_box_power("on")
        self.addCleanup(self._stop_leftover_services)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._wait_for_started_services(1), 1)
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "on")

    def test_state_off_with_services_alive_still_starts_them(self) -> None:
        """Tệp ghi "off" mà dịch vụ vẫn sống: `on` phải dọn rồi dựng lại."""
        self.state.write_text("off\n", encoding="utf-8")
        self._set_alive(ALL_SERVICE_PATTERNS)

        result = self._run_box_power("on")
        self.addCleanup(self._stop_leftover_services)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._wait_for_started_services(1), 1)
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "on")

    @unittest.skipUnless(shutil.which("flock"), "cần flock (util-linux) để kiểm chốt khoá")
    def test_second_on_does_not_block_while_services_are_starting(self) -> None:
        """Khoá không được theo chân dịch vụ xuống nền — nếu không, `off` sau đó chờ vô hạn."""
        self._set_alive(())
        first = self._run_box_power("on")
        self.addCleanup(self._stop_leftover_services)
        self.assertEqual(first.returncode, 0, first.stderr)

        started = time.monotonic()
        second = self._run_box_power("on")

        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertLess(time.monotonic() - started, 10.0, "lượt `on` thứ hai bị chặn bởi khoá còn giữ")
        self.assertTrue((self.root / "box-power.lock").exists(), "khoá phải được tạo thật")

    @unittest.skipUnless(shutil.which("flock"), "cần flock (util-linux) để kiểm chốt khoá")
    def test_lock_held_elsewhere_does_not_hang_forever(self) -> None:
        """Chờ khoá phải CÓ HẠN: ide-proxy gọi box-power không timeout, treo là treo nút nguồn."""
        self._set_alive(ALL_SERVICE_PATTERNS)
        lock_path = self.root / "box-power.lock"

        with lock_path.open("w") as holder:
            fcntl.flock(holder, fcntl.LOCK_EX)

            environment = dict(os.environ)
            environment.update(
                {
                    "PATH": f"{self.bin}:{environment['PATH']}",
                    "HOME": str(self.root),
                    "BOX_POWER_STATE_FILE": str(self.state),
                    "BOX_POWER_SERVICES_BIN": str(self.services),
                    "BOX_POWER_AGENT_HOME": str(self.root),
                    "BOX_POWER_LOCK_FILE": str(lock_path),
                    "BOX_POWER_LOCK_WAIT": "1",
                }
            )
            started = time.monotonic()
            result = subprocess.run(
                ["/bin/sh", str(BOX_POWER), "off"],
                capture_output=True,
                text=True,
                env=environment,
                timeout=15,
                check=False,
            )
            elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("không lấy được khoá", result.stderr)
        self.assertLess(elapsed, 10.0, "phải bỏ cuộc sau thời gian chờ có hạn, không treo")

    def test_power_off_writes_state_and_stops_services(self) -> None:
        self.state.write_text("on\n", encoding="utf-8")
        self._set_alive(ALL_SERVICE_PATTERNS)

        result = self._run_box_power("off")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.state.read_text(encoding="utf-8").strip(), "off")
        killed = self._logged(self.pkill_log)
        self.assertIn(self.services_script_pattern, killed)
        for pattern in ALL_SERVICE_PATTERNS:
            self.assertIn(pattern, killed, f"OFF phải hạ tiến trình khớp {pattern!r}")

    def test_unknown_action_exits_two(self) -> None:
        result = self._run_box_power("sideways")

        self.assertEqual(result.returncode, 2)

    # ------------------------------------------------------------------ #
    # Entrypoint: container vừa khởi động thì không dịch vụ nào đang chạy.
    # ------------------------------------------------------------------ #

    def test_entrypoint_clears_power_state_before_starting_services(self) -> None:
        lines = [
            line.strip()
            for line in BOX_ENTRYPOINT.read_text(encoding="utf-8").splitlines()
        ]
        remove_at = lines.index(f"rm -f {STATE_FILE_IN_BOX}") if f"rm -f {STATE_FILE_IN_BOX}" in lines else -1
        power_at = next(
            (index for index, line in enumerate(lines) if line.startswith('box-power "${BOX_DEFAULT_POWER')),
            -1,
        )

        self.assertNotEqual(remove_at, -1, f"entrypoint phải xoá {STATE_FILE_IN_BOX} khi container khởi động")
        self.assertNotEqual(power_at, -1, "entrypoint phải gọi box-power")
        self.assertLess(remove_at, power_at, "phải xoá dấu vết trước khi gọi box-power")


if __name__ == "__main__":
    unittest.main()
