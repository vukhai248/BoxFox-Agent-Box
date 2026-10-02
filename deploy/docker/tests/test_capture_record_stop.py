"""W9: dừng/kiểm bản ghi `record_stop` (moov atom not found) — mock subprocess, không X11.

Chữ ký lỗi đã lưu trong sweep: stop trả `ok`, `durationSec` ≈ 22–24 s cho một lần quay 2 s
(wall-clock sau SIGINT→chờ 20 s→SIGKILL), ffprobe báo `moov atom not found`. Probe trong box
(`probe_recorder.py`, ca `hang`) dựng lại đúng chữ ký đó. Các test dưới đây khoá hành vi mới:
stop chỉ báo hoàn tất khi file probe được, leo thang SIGINT→SIGTERM→SIGKILL có ghi lại, và
MP4 phân mảnh để file bị kill vẫn đọc được.
"""

from __future__ import annotations

import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import capture  # noqa: E402
from capture import CaptureError  # noqa: E402

MOOV_ERR = ("[mov,mp4,m4a,3gp,3g2,mj2 @ 0x5ef7e11e3ac0] moov atom not found\n"
            "/tmp/x.mp4: Invalid data found when processing input")


class FakeProc:
    """Popen giả: `exit_on` = tín hiệu đầu tiên làm tiến trình thoát (None = không bao giờ)."""

    def __init__(self, exit_on=signal.SIGINT, exit_code=255, already_exited=False):
        self.pid = 4242
        self.exit_on = exit_on
        self.exit_code = exit_code
        self.returncode = 0 if already_exited else None
        self.sent: list[int] = []

    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self.sent.append(sig)
        if sig == signal.SIGKILL:
            self.returncode = -signal.SIGKILL
        elif self.exit_on is not None and sig == self.exit_on:
            self.returncode = self.exit_code

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("ffmpeg", timeout)
        return self.returncode


class RecordStopTest(unittest.TestCase):
    def setUp(self) -> None:
        self._records = dict(capture._RECORDS)
        self._finished = dict(capture._FINISHED_RECORDS)
        capture._RECORDS.clear()
        capture._FINISHED_RECORDS.clear()
        self.patches = [
            patch.object(capture, "_index_record"),
            patch.object(capture, "_file_size", return_value=1048624),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self) -> None:
        for item in self.patches:
            item.stop()
        capture._RECORDS.clear()
        capture._RECORDS.update(self._records)
        capture._FINISHED_RECORDS.clear()
        capture._FINISHED_RECORDS.update(self._finished)

    def _register(self, proc, record_id="rec-w9"):
        capture._RECORDS[record_id] = {
            "recordingId": record_id, "kind": "screen", "target": {"kind": "screen"},
            "path": "/tmp/x.mp4", "process": proc, "pid": proc.pid,
            "startedAt": time.time() - 24,  # wall-clock 24 s: không được thành durationSec
        }
        return record_id

    @staticmethod
    def _ffprobe(stdout="2.000000\n", returncode=0, stderr=""):
        return patch.object(capture, "_run_as_agent",
                            return_value=subprocess.CompletedProcess([], returncode, stdout, stderr))

    def test_graceful_sigint_reports_probed_duration(self) -> None:
        proc = FakeProc(exit_on=signal.SIGINT)
        rid = self._register(proc)
        with self._ffprobe():
            result = capture.record_stop(rid)
        self.assertEqual(proc.sent, [signal.SIGINT])
        self.assertTrue(result["ok"])
        self.assertEqual(result["durationSec"], 2.0)
        self.assertTrue(result["verified"])
        self.assertEqual([s["signal"] for s in result["stopSignals"]], ["SIGINT"])
        self.assertNotIn("forcedKill", result)
        self.assertNotIn(rid, capture._RECORDS)
        self.assertIn(rid, capture._FINISHED_RECORDS)

    def test_sigint_ignored_escalates_to_sigterm(self) -> None:
        proc = FakeProc(exit_on=signal.SIGTERM)
        rid = self._register(proc)
        with self._ffprobe():
            result = capture.record_stop(rid)
        self.assertEqual(proc.sent, [signal.SIGINT, signal.SIGTERM])
        self.assertTrue(result["ok"])

    def test_killed_unplayable_file_is_recording_incomplete_not_ok(self) -> None:
        """Đúng chữ ký sweep: SIGKILL + moov atom not found ⇒ KHÔNG được trả ok/wall-clock."""
        proc = FakeProc(exit_on=None)
        rid = self._register(proc)
        with self._ffprobe(stdout="", returncode=1, stderr=MOOV_ERR):
            result = capture.record_stop(rid)
        self.assertEqual(proc.sent, [signal.SIGINT, signal.SIGTERM, signal.SIGKILL])
        self.assertIs(result["ok"], False)
        self.assertEqual(result["errorCode"], "RECORDING_INCOMPLETE")
        self.assertIsNone(result["durationSec"])
        self.assertIn("moov atom not found", result["error"])
        self.assertEqual(result["exitCode"], -signal.SIGKILL)
        self.assertEqual(capture._FINISHED_RECORDS[rid]["errorCode"], "RECORDING_INCOMPLETE")

    def test_killed_but_fragmented_file_playable_is_ok_with_forced_kill(self) -> None:
        proc = FakeProc(exit_on=None)
        rid = self._register(proc)
        with self._ffprobe(stdout="1.933333\n"):
            result = capture.record_stop(rid)
        self.assertTrue(result["ok"])
        self.assertTrue(result["forcedKill"])
        self.assertEqual(result["durationSec"], 1.93)

    def test_unkillable_process_raises_500(self) -> None:
        proc = FakeProc(exit_on=None)
        proc.send_signal = lambda sig: None  # không tín hiệu nào có tác dụng
        rid = self._register(proc)
        with self.assertRaises(CaptureError) as caught:
            capture.record_stop(rid)
        self.assertEqual(caught.exception.status_code, 500)

    def test_stop_waits_fit_inside_harness_http_timeout(self) -> None:
        budget = (capture.RECORD_STOP_SIGINT_WAIT + capture.RECORD_STOP_SIGTERM_WAIT
                  + capture.RECORD_STOP_SIGKILL_WAIT + 10)  # +10: ffprobe timeout
        self.assertLess(budget, 40)  # httpx timeout=40 ở sandbox/executor.py

    def test_already_exited_process_gets_no_signal(self) -> None:
        proc = FakeProc(already_exited=True)
        rid = self._register(proc)
        with self._ffprobe(stdout="5.000000\n"):
            result = capture.record_stop(rid)
        self.assertEqual(proc.sent, [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["durationSec"], 5.0)

    def test_stop_after_auto_exit_reap_returns_finished_not_404(self) -> None:
        proc = FakeProc(already_exited=True)
        rid = self._register(proc)
        with self._ffprobe(stdout="5.000000\n"):
            capture._reap_finished_records()
            result = capture.record_stop(rid)
        self.assertTrue(result["ok"])
        self.assertTrue(result["alreadyFinished"])
        self.assertEqual(result["durationSec"], 5.0)

    def test_reaped_unplayable_record_is_marked_incomplete(self) -> None:
        proc = FakeProc(already_exited=True)
        rid = self._register(proc)
        with self._ffprobe(stdout="", returncode=1, stderr=MOOV_ERR):
            capture._reap_finished_records()
        self.assertIs(capture._FINISHED_RECORDS[rid]["ok"], False)
        self.assertEqual(capture._FINISHED_RECORDS[rid]["errorCode"], "RECORDING_INCOMPLETE")

    def test_ffmpeg_log_tail_attached_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "rec.log"
            log.write_text("[x11grab @ 0x1] Cannot get the image data\n", encoding="utf-8")
            proc = FakeProc(exit_on=None)
            rid = self._register(proc)
            capture._RECORDS[rid]["ffmpegLog"] = str(log)
            with self._ffprobe(stdout="", returncode=1, stderr=MOOV_ERR):
                result = capture.record_stop(rid)
        self.assertIn("Cannot get the image data", result["ffmpegLog"])


class RecordArgvTest(unittest.TestCase):
    def _start(self, spec: dict) -> tuple[list, dict]:
        fake_proc = MagicMock()
        fake_proc.pid = 999
        with patch.object(capture, "_count_active_records", return_value=0), \
             patch.object(capture, "_reap_finished_records"), \
             patch.object(capture, "resolve_window",
                          return_value={"id": "0x1", "w": 800, "h": 600, "selectable": True}), \
             patch.object(capture, "screen_size", return_value=(1280, 800)), \
             patch.object(capture, "_check_size"), \
             patch.object(capture, "_new_path", return_value=Path("/tmp/x.mp4")), \
             patch.object(capture, "_raise_window"), \
             patch.object(capture, "_spawn_ffmpeg", return_value=fake_proc) as spawn, \
             patch.object(capture, "_new_record_id", return_value="rec-argv"), \
             patch.object(capture, "_register") as register:
            capture.record_start(spec)
        return spawn.call_args, register.call_args[0][1]

    def test_screen_and_window_use_fragmented_mp4_with_short_gop(self) -> None:
        for spec in ({"kind": "screen", "framerate": 15}, {"kind": "window", "windowId": "0x1"}):
            call, entry = self._start(spec)
            args = call[0][0]
            self.assertEqual(args[args.index("-movflags") + 1], capture.RECORD_MOVFLAGS)
            self.assertIn("empty_moov", capture.RECORD_MOVFLAGS)
            self.assertEqual(args[args.index("-g") + 1], "30")
            self.assertEqual(args[args.index("-flush_packets") + 1], "1")
            self.assertEqual(args[-1], "/tmp/x.mp4")
            self.assertEqual(call[0][1], capture.FFMPEG_LOG_DIR / "rec-argv.log")
            self.assertEqual(entry["ffmpegLog"], str(capture.FFMPEG_LOG_DIR / "rec-argv.log"))

    def test_spawn_ffmpeg_sends_stderr_to_log_and_disables_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "sub" / "rec.log"
            with patch.object(capture.subprocess, "Popen") as popen:
                capture._spawn_ffmpeg(["-f", "x11grab"], log)
            argv = popen.call_args[0][0]
            kwargs = popen.call_args[1]
            self.assertEqual(argv[argv.index("ffmpeg") + 1], "-nostdin")
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertEqual(Path(kwargs["stderr"].name), log)
            self.assertTrue(log.parent.is_dir())

    def test_spawn_ffmpeg_without_log_uses_devnull(self) -> None:
        with patch.object(capture.subprocess, "Popen") as popen:
            capture._spawn_ffmpeg(["-f", "x11grab"])
        self.assertIs(popen.call_args[1]["stderr"], subprocess.DEVNULL)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "cần ffmpeg/ffprobe thật")
class FragmentedMp4SurvivesKillTest(unittest.TestCase):
    """Bằng chứng thật cho cờ muxer: SIGKILL giữa chừng vẫn để lại file ffprobe đọc được.

    Nguồn `lavfi testsrc` thay cho x11grab (không cần X11); encoder/muxer/cờ y như record.
    Đối chứng: cùng lệnh nhưng MP4 thường ⇒ `moov atom not found`.
    """

    def _record_and_kill(self, out: Path, fragmented: bool) -> subprocess.CompletedProcess:
        tail = capture._record_output_args(15, 600, out)
        if not fragmented:
            index = tail.index("-movflags")
            del tail[index:index + 2]
        proc = subprocess.Popen(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-re", "-f", "lavfi",
             "-i", "testsrc=size=320x240:rate=15", *tail],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3.5)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        return subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                               "-of", "csv=p=0", str(out)], capture_output=True, text=True)

    def test_killed_fragmented_record_is_playable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            probe = self._record_and_kill(Path(tmp) / "frag.mp4", fragmented=True)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertGreaterEqual(float(probe.stdout.strip()), 1.0)

    def test_killed_plain_mp4_loses_moov(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            probe = self._record_and_kill(Path(tmp) / "plain.mp4", fragmented=False)
        self.assertNotEqual(probe.returncode, 0)
        self.assertIn("moov atom not found", probe.stderr)


if __name__ == "__main__":
    unittest.main()
