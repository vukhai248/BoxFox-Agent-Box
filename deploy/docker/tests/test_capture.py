"""Kiểm thử đơn vị cho capture.py + browser_capture.py (thuần stdlib, không X11)."""

from __future__ import annotations

import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browser_capture
import capture
from capture import CaptureError


class SelectableTest(unittest.TestCase):
    def test_ewmh_atoms_mark_not_selectable(self) -> None:
        self.assertFalse(capture._is_selectable(["_NET_WM_STATE_SKIP_TASKBAR"]))
        self.assertFalse(capture._is_selectable(["_NET_WM_STATE_HIDDEN"]))
        self.assertFalse(capture._is_selectable(
            ["_NET_WM_STATE_STICKY", "_NET_WM_STATE_SKIP_TASKBAR", "_NET_WM_STATE_FOCUSED"]
        ))

    def test_no_exclusion_is_selectable(self) -> None:
        self.assertTrue(capture._is_selectable([]))
        self.assertTrue(capture._is_selectable(["_NET_WM_STATE_FOCUSED"]))


class ParseWmctrlLineTest(unittest.TestCase):
    def test_parses_normal_line_with_spaces_in_title(self) -> None:
        line = "0x02400002  0 chromium-playwright.Chromium  boxfox  Trang cần fix"
        win = capture._parse_wmctrl_line(line)
        self.assertEqual(win["id"], "0x02400002")
        self.assertEqual(win["class"], "chromium-playwright.Chromium")
        self.assertEqual(win["host"], "boxfox")
        self.assertEqual(win["title"], "Trang cần fix")
        self.assertNotIn("x", win)  # hình học nay lấy riêng từ xwininfo

    def test_parses_empty_title(self) -> None:
        line = "0x02400002  0 xfdesktop.Xfdesktop  boxfox"
        win = capture._parse_wmctrl_line(line)
        self.assertEqual(win["title"], "")
        self.assertEqual(win["desktop"], "0")

    def test_rejects_non_window_and_too_few_columns(self) -> None:
        self.assertIsNone(capture._parse_wmctrl_line("not-a-window 0 class host title"))
        self.assertIsNone(capture._parse_wmctrl_line("0x02400002  0 class"))
        self.assertIsNone(capture._parse_wmctrl_line(""))


class XPropManyTest(unittest.TestCase):
    def test_parses_multiple_props(self) -> None:
        stdout = (
            "_NET_WM_STATE(ATOM) = _NET_WM_STATE_MAXIMIZED_VERT, _NET_WM_STATE_MAXIMIZED_HORZ\n"
            "_NET_WM_PID(CARDINAL) = 4242\n"
        )
        proc = subprocess.CompletedProcess([], 0, stdout, "")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            props = capture._xprop_many("0x1", ["_NET_WM_STATE", "_NET_WM_PID"])
        self.assertEqual(capture._parse_pid(props.get("_NET_WM_PID")), 4242)
        self.assertEqual(
            capture._parse_state(props.get("_NET_WM_STATE")),
            ["_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ"],
        )

    def test_parse_pid_invalid(self) -> None:
        self.assertIsNone(capture._parse_pid(None))
        self.assertIsNone(capture._parse_pid(""))
        self.assertIsNone(capture._parse_pid("abc"))

    def test_parse_state_empty(self) -> None:
        self.assertEqual(capture._parse_state(None), [])
        self.assertEqual(capture._parse_state(""), [])

    def test_xprop_many_missing_window_returns_empty(self) -> None:
        proc = subprocess.CompletedProcess([], 1, "", "xprop: error")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            self.assertEqual(capture._xprop_many("0x1", ["_NET_WM_PID"]), {})


class WinInfoGeometryTest(unittest.TestCase):
    def test_parses_absolute_geometry_and_size(self) -> None:
        stdout = (
            "xwininfo: Window id: 0x2400002 \"Trang cần fix\"\n"
            "  Absolute upper-left X:  100\n"
            "  Absolute upper-left Y:  200\n"
            "  Relative upper-left X:  100\n"
            "  Width: 800\n"
            "  Height: 600\n"
        )
        proc = subprocess.CompletedProcess([], 0, stdout, "")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            self.assertEqual(
                capture._wininfo_geometry("0x1"),
                {"x": 100, "y": 200, "w": 800, "h": 600},
            )

    def test_returns_none_on_partial_output(self) -> None:
        proc = subprocess.CompletedProcess([], 0, "Width: 800\n", "")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            self.assertIsNone(capture._wininfo_geometry("0x1"))

    def test_returns_none_on_missing_window(self) -> None:
        proc = subprocess.CompletedProcess([], 1, "", "xwininfo: error: no such window")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            self.assertIsNone(capture._wininfo_geometry("0xdead"))


class ClassMatchesTest(unittest.TestCase):
    def test_matches_instance_class_or_substring(self) -> None:
        self.assertTrue(capture._class_matches("chromium-playwright.Chromium", "Chromium"))
        self.assertTrue(capture._class_matches("chromium-playwright.Chromium", "chromium-playwright"))
        self.assertTrue(capture._class_matches("chromium-playwright.Chromium", "chromium"))
        self.assertFalse(capture._class_matches("chromium-playwright.Chromium", "firefox"))
        self.assertFalse(capture._class_matches("", "chromium"))


class SizeCheckTest(unittest.TestCase):
    def test_rejects_oversized_root(self) -> None:
        with self.assertRaises(CaptureError) as caught:
            capture._check_size(32768, 32768)
        self.assertEqual(caught.exception.status_code, 413)

    def test_accepts_reasonable_size(self) -> None:
        capture._check_size(1280, 800)
        capture._check_size(4096, 4096)


class ResolveWindowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.windows = [
            {"id": "0x02400002", "desktop": "0", "class": "chromium-playwright.Chromium",
             "title": "Trang cần fix", "pid": 111, "state": [], "selectable": True,
             "x": 0, "y": 0, "w": 800, "h": 600},
            {"id": "0x03a00007", "desktop": "0", "class": "xfce4-terminal.Xfce4-terminal",
             "title": "Terminal", "pid": 222, "state": [], "selectable": True,
             "x": 0, "y": 0, "w": 500, "h": 300},
            {"id": "0x02c0000a", "desktop": "0", "class": "chromium-playwright.Chromium",
             "title": "Tab khác", "pid": 111, "state": ["SKIP_TASKBAR"], "selectable": False,
             "x": 0, "y": 0, "w": 800, "h": 600},
        ]

    def test_prefers_exact_window_id(self) -> None:
        with patch.object(capture, "list_windows", return_value=self.windows):
            self.assertEqual(capture.resolve_window({"windowId": "0x03A00007"})["id"], "0x03a00007")

    def test_matches_by_pid_filters_state(self) -> None:
        with patch.object(capture, "list_windows", return_value=self.windows):
            # pid 111 có 2 cửa sổ nhưng chỉ 1 cửa sổ selectable → chọn cửa sổ đó
            self.assertEqual(capture.resolve_window({"pid": 111})["id"], "0x02400002")

    def test_matches_by_title(self) -> None:
        with patch.object(capture, "list_windows", return_value=self.windows):
            self.assertEqual(capture.resolve_window({"title": "cần fix"})["id"], "0x02400002")

    def test_ambiguous_raises_409(self) -> None:
        windows = [w for w in self.windows if w["selectable"]] + [
            {"id": "0x04f00001", "desktop": "0", "class": "chromium-playwright.Chromium",
             "title": "Cũng cần fix", "pid": 333, "state": [], "selectable": True,
             "x": 0, "y": 0, "w": 800, "h": 600},
        ]
        with patch.object(capture, "list_windows", return_value=windows):
            with self.assertRaises(CaptureError) as caught:
                capture.resolve_window({"class": "chromium"})
            self.assertEqual(caught.exception.status_code, 409)

    def test_not_found_raises_404(self) -> None:
        with patch.object(capture, "list_windows", return_value=self.windows):
            with self.assertRaises(CaptureError) as caught:
                capture.resolve_window({"title": "không tồn tại"})
            self.assertEqual(caught.exception.status_code, 404)

    def test_missing_selector_raises_400(self) -> None:
        with patch.object(capture, "list_windows", return_value=self.windows):
            with self.assertRaises(CaptureError) as caught:
                capture.resolve_window({})
            self.assertEqual(caught.exception.status_code, 400)


class ResolveTabTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tabs = [
            {"id": "ABC", "url": "https://example.com/", "title": "Example",
             "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/ABC"},
            {"id": "DEF", "url": "https://example.org/", "title": "Org",
             "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/DEF"},
        ]

    def test_resolves_by_tab_id(self) -> None:
        with patch.object(capture, "list_tabs", return_value=self.tabs):
            self.assertEqual(capture.resolve_tab({"tabId": "DEF"})["id"], "DEF")

    def test_resolves_by_url_substring(self) -> None:
        with patch.object(capture, "list_tabs", return_value=self.tabs):
            self.assertEqual(capture.resolve_tab({"url": "example.org"})["id"], "DEF")

    def test_ambiguous_raises_409(self) -> None:
        tabs = self.tabs + [
            {"id": "GHI", "url": "https://example.com/x", "title": "Example 2",
             "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/GHI"},
        ]
        with patch.object(capture, "list_tabs", return_value=tabs):
            with self.assertRaises(CaptureError) as caught:
                capture.resolve_tab({"url": "example.com"})
            self.assertEqual(caught.exception.status_code, 409)

    def test_missing_selector_raises_400(self) -> None:
        with patch.object(capture, "list_tabs", return_value=self.tabs):
            with self.assertRaises(CaptureError) as caught:
                capture.resolve_tab({})
            self.assertEqual(caught.exception.status_code, 400)


class PublicTabsTest(unittest.TestCase):
    def test_public_tab_drops_only_ws_url(self) -> None:
        tab = {"id": "A", "type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1/secret"}
        self.assertEqual(capture._public_tab(tab), {"id": "A", "type": "page"})

    def test_dispatch_list_tabs_strips_ws_url(self) -> None:
        tabs = [
            {"id": "A", "url": "x", "title": "t", "type": "page",
             "webSocketDebuggerUrl": "ws://127.0.0.1/devtools/page/A"},
        ]
        with patch.object(capture, "list_tabs", return_value=tabs):
            result = capture.dispatch_list_tabs()
        self.assertNotIn("webSocketDebuggerUrl", result["tabs"][0])
        self.assertEqual(result["tabs"][0]["id"], "A")


class DispatchTest(unittest.TestCase):
    def test_capture_dispatches_by_kind_and_validates_format(self) -> None:
        with patch.object(capture, "_capture_window", return_value={"kind": "window"}) as win, \
             patch.object(capture, "_capture_screen", return_value={"kind": "screen"}) as scr, \
             patch.object(capture, "_capture_tab", return_value={"kind": "tab"}) as tab:
            self.assertEqual(capture.capture({"kind": "window", "windowId": "0x1"})["kind"], "window")
            self.assertEqual(capture.capture({"kind": "screen"})["kind"], "screen")
            self.assertEqual(capture.capture({"kind": "tab", "tabId": "ABC"})["kind"], "tab")
            win.assert_called_once()
            scr.assert_called_once()
            tab.assert_called_once()

    def test_capture_rejects_bad_format_and_kind(self) -> None:
        with self.assertRaises(CaptureError) as caught:
            capture.capture({"kind": "screen", "format": "gif"})
        self.assertEqual(caught.exception.status_code, 400)
        with self.assertRaises(CaptureError) as caught:
            capture.capture({"kind": "bogus", "format": "png"})
        self.assertEqual(caught.exception.status_code, 400)


class RecordTest(unittest.TestCase):
    def test_stop_unknown_record_404(self) -> None:
        with self.assertRaises(CaptureError) as caught:
            capture.record_stop("rec-khong-ton-tai")
        self.assertEqual(caught.exception.status_code, 404)

    def test_record_tab_not_supported_501(self) -> None:
        with patch.object(capture, "_count_active_records", return_value=0):
            with self.assertRaises(CaptureError) as caught:
                capture.record_start({"kind": "tab", "tabId": "ABC"})
            self.assertEqual(caught.exception.status_code, 501)

    def test_record_start_rejects_bad_max_duration(self) -> None:
        with patch.object(capture, "_reap_finished_records"):
            with self.assertRaises(CaptureError) as caught:
                capture.record_start({"kind": "screen", "maxDurationSec": "abc"})
        self.assertEqual(caught.exception.status_code, 400)


class RecordReapTest(unittest.TestCase):
    def setUp(self) -> None:
        self._records = dict(capture._RECORDS)
        self._finished = dict(capture._FINISHED_RECORDS)
        capture._RECORDS.clear()
        capture._FINISHED_RECORDS.clear()

    def tearDown(self) -> None:
        capture._RECORDS.clear()
        capture._RECORDS.update(self._records)
        capture._FINISHED_RECORDS.clear()
        capture._FINISHED_RECORDS.update(self._finished)

    def _entry(self, record_id: str, poll_result):
        proc = MagicMock()
        proc.poll.return_value = poll_result
        proc.pid = 12345
        return {
            "recordingId": record_id,
            "kind": "screen",
            "target": {"kind": "screen"},
            "path": f"/tmp/{record_id}.mp4",
            "process": proc,
            "pid": proc.pid,
            "startedAt": time.time() - 10,
        }

    def test_reap_promotes_exited_process_out_of_active(self) -> None:
        capture._RECORDS["rec-dead"] = self._entry("rec-dead", 0)
        capture._RECORDS["rec-alive"] = self._entry("rec-alive", None)
        with patch.object(capture, "_file_size", return_value=999):
            status = capture.record_status()
        active_ids = {entry["recordingId"] for entry in status["active"]}
        self.assertEqual(active_ids, {"rec-alive"})
        finished_ids = {entry["recordingId"] for entry in status["finished"]}
        self.assertIn("rec-dead", finished_ids)
        dead = next(e for e in status["finished"] if e["recordingId"] == "rec-dead")
        self.assertTrue(dead["finished"])
        self.assertEqual(dead["sizeBytes"], 999)


class RecordFinishedEntryTest(unittest.TestCase):
    """durationSec phải lấy từ thời lượng video THỰC (ffprobe), không dùng wall-clock."""

    def setUp(self) -> None:
        self.entry = {
            "recordingId": "rec-x",
            "kind": "screen",
            "target": {"kind": "screen"},
            "path": "/tmp/rec-x.mp4",
            "startedAt": time.time() - 100,  # wall-clock ~100s, ffprobe phải thắng
        }

    def test_prefers_ffprobe_duration(self) -> None:
        proc = subprocess.CompletedProcess([], 0, "5.00\n", "")
        with patch.object(capture, "_run_as_agent", return_value=proc), \
             patch.object(capture, "_file_size", return_value=1):
            result = capture._record_finished_entry(self.entry)
        self.assertEqual(result["durationSec"], 5.0)

    def test_falls_back_to_wall_clock_when_ffprobe_unavailable(self) -> None:
        with patch.object(capture, "_run_as_agent", side_effect=OSError("gosu missing")), \
             patch.object(capture, "_file_size", return_value=1):
            result = capture._record_finished_entry(self.entry)
        self.assertGreater(result["durationSec"], 90.0)

    def test_video_duration_none_on_bad_output(self) -> None:
        proc = subprocess.CompletedProcess([], 0, "khong-phai-so\n", "")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            self.assertIsNone(capture._video_duration_sec("/tmp/x.mp4"))


class RecordDurationTest(unittest.TestCase):
    """MAX_RECORD_SECONDS phải được thực thi bằng flag `-t` của ffmpeg."""

    def _start(self, spec: dict, win: dict):
        from unittest.mock import MagicMock
        fake_proc = MagicMock()
        fake_proc.pid = 999
        with patch.object(capture, "_count_active_records", return_value=0), \
             patch.object(capture, "resolve_window", return_value=win), \
             patch.object(capture, "screen_size", return_value=(1280, 800)), \
             patch.object(capture, "_check_size"), \
             patch.object(capture, "_new_path", return_value=Path("/tmp/x.mp4")), \
             patch.object(capture, "_raise_window"), \
             patch.object(capture, "_spawn_ffmpeg", return_value=fake_proc) as spawn, \
             patch.object(capture, "_new_record_id", return_value="rec-test"), \
             patch.object(capture, "_register"):
            capture.record_start(spec)
        return spawn.call_args[0][0]

    def test_window_record_passes_t_flag(self) -> None:
        win = {"id": "0x1", "w": 800, "h": 600, "selectable": True}
        args = self._start({"kind": "window", "windowId": "0x1", "maxDurationSec": 42}, win)
        self.assertIn("-t", args)
        self.assertEqual(args[args.index("-t") + 1], "42")

    def test_screen_record_passes_t_flag(self) -> None:
        win = {"id": "0x1", "w": 800, "h": 600, "selectable": True}
        args = self._start({"kind": "screen", "maxDurationSec": 7}, win)
        self.assertIn("-t", args)
        self.assertEqual(args[args.index("-t") + 1], "7")

    def test_defaults_to_max_record_seconds(self) -> None:
        win = {"id": "0x1", "w": 800, "h": 600, "selectable": True}
        args = self._start({"kind": "screen"}, win)
        self.assertIn("-t", args)
        self.assertEqual(args[args.index("-t") + 1], str(capture.MAX_RECORD_SECONDS))


class ScreenSizeTest(unittest.TestCase):
    def test_parses_current_resolution(self) -> None:
        stdout = "Screen 0: minimum 32 x 32, current 1280 x 800, maximum 32768 x 32768\n"
        proc = subprocess.CompletedProcess([], 0, stdout, "")
        with patch.object(capture, "_run_as_agent", return_value=proc):
            self.assertEqual(capture.screen_size(), (1280, 800))


class BrowserCaptureFrameTest(unittest.TestCase):
    def test_apply_mask_roundtrip(self) -> None:
        mask = b"\x01\x02\x03\x04"
        data = b"hello world"
        masked = browser_capture.apply_mask(data, mask)
        self.assertNotEqual(masked, data)
        self.assertEqual(browser_capture.apply_mask(masked, mask), data)

    def test_make_frame_short_payload(self) -> None:
        frame = browser_capture.make_frame(0x1, b"abc", masked=True)
        # byte 0: FIN|opcode; byte 1: MASK|length
        self.assertEqual(frame[0], 0x81)
        self.assertEqual(frame[1], 0x80 | 3)

    def test_make_frame_126_boundary(self) -> None:
        for length in (126, 65536):
            frame = browser_capture.make_frame(0x1, b"x" * length, masked=True)
            self.assertEqual(frame[0], 0x81)

    def test_websocket_rejects_non_ws_scheme(self) -> None:
        with self.assertRaises(browser_capture.WebSocketError):
            browser_capture.WebSocket("http://127.0.0.1:9222/devtools/page/X").connect()


if __name__ == "__main__":
    unittest.main()
