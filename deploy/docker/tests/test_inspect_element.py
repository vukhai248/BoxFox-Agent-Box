"""Kiểm thử đơn vị cho `inspect_element.py` + các hàm CDP thuần của
`browser_capture.py` phục vụ element-selector (Phase 1).

Chạy được KHÔNG cần X server, KHÔNG cần Chromium thật: mọi lời gọi
`_run_as_agent`/socket CDP đều bị mock/giả (FakeWebSocket).
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import browser_capture
import capture
import inspect_element
from capture import CaptureError


# ---------------------------------------------------------------------------
# Giả lập WebSocket CDP — script các response theo ĐÚNG thứ tự lệnh gọi.
# ---------------------------------------------------------------------------
class FakeWebSocket:
    """`script`: list[(expected_method|None, response_dict_hoặc_Exception)].

    Method `None` nghĩa là không kiểm khớp tên lệnh (khoan dung), nhưng mọi
    test khẳng định THỨ TỰ đều truyền tên thật để bắt lệch chuỗi CDP.
    """

    def __init__(self, script, ws_url: str = "ws://127.0.0.1:9222/devtools/page/FAKE"):
        self.script = list(script)
        self.calls: list[tuple[str, dict | None]] = []
        self.ws_url = ws_url
        self.closed = False

    def connect(self) -> None:
        pass

    def call(self, method: str, params: dict | None = None) -> dict:
        self.calls.append((method, params))
        if not self.script:
            raise AssertionError(f"FakeWebSocket: hết script, bị gọi thừa {method}")
        expected_method, response = self.script.pop(0)
        if expected_method is not None and expected_method != method:
            raise AssertionError(f"FakeWebSocket: mong lệnh {expected_method}, nhận {method}")
        if isinstance(response, Exception):
            raise response
        return response

    def close(self) -> None:
        self.closed = True

    def call_names(self) -> list[str]:
        return [name for name, _ in self.calls]


def _eval_result(value: dict) -> dict:
    return {"result": {"result": {"value": value}}}


def _viewport(dpr=1.0, inner_w=1000, inner_h=700, outer_w=1010, outer_h=780, url="http://x/", title="X"):
    return _eval_result({
        "dpr": dpr, "innerWidth": inner_w, "innerHeight": inner_h,
        "outerWidth": outer_w, "outerHeight": outer_h, "screenX": 0, "screenY": 0,
        "url": url, "title": title,
    })


# ===========================================================================
# 1. Hàm thuần hình học của browser_capture.py — dpr=1 VÀ dpr=2
# ===========================================================================
class GeometryPureFunctionsTest(unittest.TestCase):
    def test_content_origin_dpr1_bottom_anchored_centered(self) -> None:
        win_geom = {"x": 100, "y": 200, "w": 800, "h": 600}
        metrics = {"dpr": 1.0, "innerWidth": 780, "innerHeight": 550}
        origin_x, origin_y = browser_capture.content_origin(win_geom, metrics)
        self.assertAlmostEqual(origin_x, 100 + (800 - 780) / 2.0)
        self.assertAlmostEqual(origin_y, 200 + 600 - 550)

    def test_content_origin_dpr2_scales_inner_size(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 1600, "h": 1200}
        metrics = {"dpr": 2.0, "innerWidth": 780, "innerHeight": 550}
        origin_x, origin_y = browser_capture.content_origin(win_geom, metrics)
        self.assertAlmostEqual(origin_x, (1600 - 780 * 2) / 2.0)
        self.assertAlmostEqual(origin_y, 1200 - 550 * 2)

    def test_screen_to_css_roundtrip_dpr1(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 800, "h": 600}
        metrics = {"dpr": 1.0, "innerWidth": 800, "innerHeight": 550}
        css_x, css_y = browser_capture.screen_to_css(400, 300, win_geom, metrics)
        self.assertAlmostEqual(css_x, 400)
        self.assertAlmostEqual(css_y, 250)

    def test_screen_to_css_roundtrip_dpr2(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 1600, "h": 1200}
        metrics = {"dpr": 2.0, "innerWidth": 800, "innerHeight": 550}
        origin_x, origin_y = browser_capture.content_origin(win_geom, metrics)
        css_x, css_y = browser_capture.screen_to_css(origin_x + 20, origin_y + 40, win_geom, metrics)
        self.assertAlmostEqual(css_x, 10)
        self.assertAlmostEqual(css_y, 20)

    def test_point_in_viewport_half_open_bounds(self) -> None:
        metrics = {"innerWidth": 100, "innerHeight": 50}
        self.assertTrue(browser_capture.point_in_viewport(0, 0, metrics))
        self.assertTrue(browser_capture.point_in_viewport(99, 49, metrics))
        self.assertFalse(browser_capture.point_in_viewport(100, 0, metrics))
        self.assertFalse(browser_capture.point_in_viewport(-1, 0, metrics))

    def test_quad_to_css_box_axis_aligned(self) -> None:
        quad = [10, 20, 30, 20, 30, 40, 10, 40]
        box = browser_capture.quad_to_css_box(quad)
        self.assertEqual(box, {"x": 10, "y": 20, "width": 20, "height": 20})

    def test_css_box_to_screen_box_dpr1(self) -> None:
        css_box = {"x": 5, "y": 10, "width": 20, "height": 30}
        screen_box = browser_capture.css_box_to_screen_box(css_box, 100, 200, 1.0)
        self.assertEqual(screen_box, {"x": 105, "y": 210, "width": 20, "height": 30})

    def test_css_box_to_screen_box_dpr2_scales_all(self) -> None:
        css_box = {"x": 5, "y": 10, "width": 20, "height": 30}
        screen_box = browser_capture.css_box_to_screen_box(css_box, 100, 200, 2.0)
        self.assertEqual(screen_box, {"x": 110, "y": 220, "width": 40, "height": 60})

    def test_bounds_score_zero_when_identical(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 800, "h": 600}
        bounds = {"left": 0, "top": 0, "width": 800, "height": 600}
        self.assertEqual(browser_capture._bounds_score(bounds, win_geom), 0.0)

    def test_bounds_score_sums_abs_differences(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 800, "h": 600}
        bounds = {"left": 10, "top": 5, "width": 790, "height": 590}
        self.assertEqual(browser_capture._bounds_score(bounds, win_geom), 10 + 5 + 10 + 10)

    def test_viewport_origin_plausible_dpr1_within_thresholds(self) -> None:
        win_geom = {"w": 800, "h": 700}
        metrics = {"dpr": 1.0, "innerWidth": 790, "innerHeight": 600}
        self.assertTrue(browser_capture._viewport_origin_plausible(win_geom, metrics))

    def test_viewport_origin_plausible_dpr2_within_thresholds(self) -> None:
        win_geom = {"w": 1600, "h": 1400}
        metrics = {"dpr": 2.0, "innerWidth": 790, "innerHeight": 600}
        self.assertTrue(browser_capture._viewport_origin_plausible(win_geom, metrics))

    def test_viewport_origin_implausible_side_slack_too_large(self) -> None:
        # MAX_SIDE_SLACK_PX = 24 — side panel Chrome (>= 300px) phải bị chặn.
        win_geom = {"w": 1100, "h": 700}
        metrics = {"dpr": 1.0, "innerWidth": 790, "innerHeight": 600}
        self.assertFalse(browser_capture._viewport_origin_plausible(win_geom, metrics))

    def test_viewport_origin_implausible_chrome_height_too_large(self) -> None:
        # MAX_CHROME_HEIGHT_PX = 200 — DevTools docked-mỏng giả lập chiều cao > 200.
        win_geom = {"w": 800, "h": 900}
        metrics = {"dpr": 1.0, "innerWidth": 790, "innerHeight": 600}
        self.assertFalse(browser_capture._viewport_origin_plausible(win_geom, metrics))

    def test_viewport_origin_implausible_negative_slack(self) -> None:
        win_geom = {"w": 800, "h": 600}
        metrics = {"dpr": 1.0, "innerWidth": 790, "innerHeight": 650}  # innerHeight > h
        self.assertFalse(browser_capture._viewport_origin_plausible(win_geom, metrics))


# ===========================================================================
# 2. viewport_metrics(ws) — hợp đồng dữ liệu Runtime.evaluate
# ===========================================================================
class ViewportMetricsTest(unittest.TestCase):
    def test_valid_metrics_roundtrip(self) -> None:
        ws = FakeWebSocket([("Runtime.evaluate", _viewport(dpr=2.0))])
        metrics = browser_capture.viewport_metrics(ws)
        self.assertEqual(metrics["dpr"], 2.0)
        self.assertEqual(metrics["innerWidth"], 1000)

    def test_non_dict_value_raises(self) -> None:
        ws = FakeWebSocket([("Runtime.evaluate", _eval_result("khong_phai_object"))])
        with self.assertRaises(browser_capture.WebSocketError):
            browser_capture.viewport_metrics(ws)

    def test_missing_required_key_raises(self) -> None:
        value = {"dpr": 1.0, "innerWidth": 100}  # thiếu innerHeight
        ws = FakeWebSocket([("Runtime.evaluate", _eval_result(value))])
        with self.assertRaises(browser_capture.WebSocketError):
            browser_capture.viewport_metrics(ws)


# ===========================================================================
# 3. _select_target — chọn CDP target khi có nhiều ứng viên
# ===========================================================================
class SelectTargetTest(unittest.TestCase):
    def test_single_candidate_auto_selected_no_ws_needed(self) -> None:
        candidates = [{"targetId": "T1"}]
        selected, reason = browser_capture._select_target(None, candidates, {"w": 800, "h": 600})
        self.assertIs(selected, candidates[0])
        self.assertIsNone(reason)

    def test_multi_candidate_scored_within_tolerance_picks_best(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 800, "h": 600, "title": "Trang A"}
        candidates = [{"targetId": "T1"}, {"targetId": "T2"}]
        # T1 khớp gần đúng (lệch 5px tổng) — trong ngưỡng WINDOW_MATCH_TOLERANCE_PX=80.
        # T2 lệch xa (400px) — không nằm trong ngưỡng.
        ws = FakeWebSocket([
            ("Browser.getWindowForTarget", {"result": {"bounds": {"left": 5, "top": 0, "width": 800, "height": 600}}}),
            ("Browser.getWindowForTarget", {"result": {"bounds": {"left": 400, "top": 0, "width": 800, "height": 600}}}),
        ])
        selected, reason = browser_capture._select_target(ws, candidates, win_geom)
        self.assertEqual(selected["targetId"], "T1")
        self.assertIsNone(reason)

    def test_ws_browser_none_with_multiple_candidates_is_ambiguous(self) -> None:
        win_geom = {"w": 800, "h": 600, "title": ""}
        candidates = [{"targetId": "T1"}, {"targetId": "T2"}]
        selected, reason = browser_capture._select_target(None, candidates, win_geom)
        self.assertIsNone(selected)
        self.assertEqual(reason, "ambiguous_target")

    def test_title_prefix_fallback_when_scoring_inconclusive(self) -> None:
        win_geom = {"x": 0, "y": 0, "w": 800, "h": 600, "title": "Trang A - Chromium"}
        candidates = [{"targetId": "T1", "title": "Trang A"}, {"targetId": "T2", "title": "Trang B"}]
        # Cả hai đều lệch xa ngưỡng -> rơi xuống dự phòng tiêu đề.
        ws = FakeWebSocket([
            ("Browser.getWindowForTarget", {"result": {"bounds": {"left": 500, "top": 0, "width": 800, "height": 600}}}),
            ("Browser.getWindowForTarget", {"result": {"bounds": {"left": 500, "top": 0, "width": 800, "height": 600}}}),
        ])
        selected, reason = browser_capture._select_target(ws, candidates, win_geom)
        self.assertEqual(selected["targetId"], "T1")
        self.assertIsNone(reason)

    def test_all_scored_candidates_error_falls_through_to_ambiguous(self) -> None:
        win_geom = {"w": 800, "h": 600, "title": ""}
        candidates = [{"targetId": "T1"}, {"targetId": "T2"}]
        ws = FakeWebSocket([
            ("Browser.getWindowForTarget", browser_capture.WebSocketError("loi")),
            ("Browser.getWindowForTarget", browser_capture.WebSocketError("loi")),
        ])
        selected, reason = browser_capture._select_target(ws, candidates, win_geom)
        self.assertIsNone(selected)
        self.assertEqual(reason, "ambiguous_target")


# ===========================================================================
# 4. _devtools_docked — chốt chặn tất định #1 (§7-B2)
# ===========================================================================
class DevtoolsDockedTest(unittest.TestCase):
    def test_no_devtools_targets_never_needs_ws(self) -> None:
        self.assertFalse(browser_capture._devtools_docked(None, "PAGE1", []))

    def test_ws_browser_none_with_devtools_targets_fails_closed_true(self) -> None:
        self.assertTrue(browser_capture._devtools_docked(None, "PAGE1", ["DT1"]))

    def test_matching_window_id_is_docked(self) -> None:
        ws = FakeWebSocket([
            ("Browser.getWindowForTarget", {"result": {"windowId": 7}}),
            ("Browser.getWindowForTarget", {"result": {"windowId": 7}}),
        ])
        self.assertTrue(browser_capture._devtools_docked(ws, "PAGE1", ["DT1"]))

    def test_different_window_id_is_not_docked(self) -> None:
        ws = FakeWebSocket([
            ("Browser.getWindowForTarget", {"result": {"windowId": 7}}),
            ("Browser.getWindowForTarget", {"result": {"windowId": 9}}),
        ])
        self.assertFalse(browser_capture._devtools_docked(ws, "PAGE1", ["DT1"]))

    def test_error_looking_up_page_window_fails_closed_true(self) -> None:
        ws = FakeWebSocket([("Browser.getWindowForTarget", browser_capture.WebSocketError("loi"))])
        self.assertTrue(browser_capture._devtools_docked(ws, "PAGE1", ["DT1"]))

    def test_error_looking_up_devtools_window_fails_closed_true(self) -> None:
        ws = FakeWebSocket([
            ("Browser.getWindowForTarget", {"result": {"windowId": 7}}),
            ("Browser.getWindowForTarget", browser_capture.WebSocketError("loi")),
        ])
        self.assertTrue(browser_capture._devtools_docked(ws, "PAGE1", ["DT1"]))


# ===========================================================================
# 5. extract_at — thứ tự lệnh CDP trên MỘT kết nối cấp page (hợp đồng có test khoá)
# ===========================================================================
def _happy_win_geom() -> dict:
    return {"x": 0, "y": 0, "w": 1000, "h": 750}


def _happy_metrics_response() -> dict:
    return _viewport(dpr=1.0, inner_w=1000, inner_h=700, url="http://x/", title="X")


def _happy_extract_script(extracted_value: dict) -> list:
    return [
        ("Runtime.evaluate", _happy_metrics_response()),
        ("DOM.enable", {"result": {}}),
        ("DOM.getDocument", {"result": {}}),
        ("DOM.getNodeForLocation", {"result": {"backendNodeId": 55}}),
        ("DOM.resolveNode", {"result": {"object": {"objectId": "obj-1"}}}),
        ("Runtime.callFunctionOn", {"result": {"result": {"objectId": "obj-1"}}}),
        ("Runtime.callFunctionOn", _eval_result(extracted_value)),
        ("DOM.getOuterHTML", {"result": {"outerHTML": "<div id=\"foo\">hi</div>"}}),
        ("DOM.getBoxModel", {"result": {"model": {"content": [0, 0, 10, 0, 10, 10, 0, 10]}}}),
    ]


class ExtractAtTest(unittest.TestCase):
    def test_full_command_order_happy_path(self) -> None:
        extracted = {
            "tagName": "div", "selector": "#foo", "text": "hi", "textTruncated": False,
            "attributes": {"id": "foo"}, "attrsTruncated": False, "notes": [], "shadowHostSelector": None,
        }
        ws = FakeWebSocket(_happy_extract_script(extracted))
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["tagName"], "div")
        self.assertEqual(result["selector"], "#foo")
        self.assertEqual(
            ws.call_names(),
            [
                "Runtime.evaluate", "DOM.enable", "DOM.getDocument", "DOM.getNodeForLocation",
                "DOM.resolveNode", "Runtime.callFunctionOn", "Runtime.callFunctionOn",
                "DOM.getOuterHTML", "DOM.getBoxModel",
            ],
        )
        self.assertEqual(result["cssBox"], {"x": 0, "y": 0, "width": 10, "height": 10})
        self.assertEqual(result["screenBox"], {"x": 0, "y": 50, "width": 10, "height": 10})

    def test_outside_viewport_short_circuits_before_dom_enable(self) -> None:
        ws = FakeWebSocket([("Runtime.evaluate", _happy_metrics_response())])
        result = browser_capture.extract_at(
            ws, {"x": 5000, "y": 5000}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "outside_viewport")
        self.assertNotIn("DOM.enable", ws.call_names())

    def test_viewport_origin_unknown_short_circuits_before_dom_enable(self) -> None:
        # w=1300 -> slack_x = 1300 - 1000 = 300 > MAX_SIDE_SLACK_PX(24).
        ws = FakeWebSocket([("Runtime.evaluate", _happy_metrics_response())])
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, {"x": 0, "y": 0, "w": 1300, "h": 750}, {}, {"targetId": "T1"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "viewport_origin_unknown")
        self.assertEqual(ws.call_names(), ["Runtime.evaluate"])

    def test_no_node_at_point_when_no_backend_node_id(self) -> None:
        ws = FakeWebSocket([
            ("Runtime.evaluate", _happy_metrics_response()),
            ("DOM.enable", {"result": {}}),
            ("DOM.getDocument", {"result": {}}),
            ("DOM.getNodeForLocation", {"result": {}}),  # không có backendNodeId
        ])
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_node_at_point")

    def test_no_node_at_point_when_no_object_id(self) -> None:
        ws = FakeWebSocket([
            ("Runtime.evaluate", _happy_metrics_response()),
            ("DOM.enable", {"result": {}}),
            ("DOM.getDocument", {"result": {}}),
            ("DOM.getNodeForLocation", {"result": {"backendNodeId": 55}}),
            ("DOM.resolveNode", {"result": {"object": {}}}),  # không có objectId
        ])
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_node_at_point")

    def test_extract_failed_on_bad_shape_from_extract_fn(self) -> None:
        script = [
            ("Runtime.evaluate", _happy_metrics_response()),
            ("DOM.enable", {"result": {}}),
            ("DOM.getDocument", {"result": {}}),
            ("DOM.getNodeForLocation", {"result": {"backendNodeId": 55}}),
            ("DOM.resolveNode", {"result": {"object": {"objectId": "obj-1"}}}),
            ("Runtime.callFunctionOn", {"result": {"result": {"objectId": "obj-1"}}}),
            ("Runtime.callFunctionOn", _eval_result({"error": "not_element"})),
        ]
        ws = FakeWebSocket(script)
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "extract_failed")

    def test_extract_failed_on_cdp_error_mid_sequence(self) -> None:
        script = [
            ("Runtime.evaluate", _happy_metrics_response()),
            ("DOM.enable", browser_capture.WebSocketError("mat ket noi")),
        ]
        ws = FakeWebSocket(script)
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "extract_failed")

    def test_missing_box_model_still_ok_with_none_boxes(self) -> None:
        extracted = {
            "tagName": "div", "selector": "#foo", "text": "hi", "textTruncated": False,
            "attributes": {}, "attrsTruncated": False, "notes": [], "shadowHostSelector": None,
        }
        script = [
            ("Runtime.evaluate", _happy_metrics_response()),
            ("DOM.enable", {"result": {}}),
            ("DOM.getDocument", {"result": {}}),
            ("DOM.getNodeForLocation", {"result": {"backendNodeId": 55}}),
            ("DOM.resolveNode", {"result": {"object": {"objectId": "obj-1"}}}),
            ("Runtime.callFunctionOn", {"result": {"result": {"objectId": "obj-1"}}}),
            ("Runtime.callFunctionOn", _eval_result(extracted)),
            ("DOM.getOuterHTML", {"result": {"outerHTML": "<div>hi</div>"}}),
            ("DOM.getBoxModel", browser_capture.WebSocketError("khong co model")),
        ]
        ws = FakeWebSocket(script)
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertTrue(result["ok"])
        self.assertIsNone(result["cssBox"])
        self.assertIsNone(result["screenBox"])

    def test_text_node_promoted_via_element_of_fn_uses_new_object_id(self) -> None:
        # ELEMENT_OF_FN trả objectId khác khi node là text node -> callFunctionOn
        # (EXTRACT_FN) tiếp theo PHẢI dùng objectId mới, không phải object_id gốc.
        extracted = {
            "tagName": "span", "selector": None, "text": "hi", "textTruncated": False,
            "attributes": {}, "attrsTruncated": False, "notes": [], "shadowHostSelector": None,
        }
        script = [
            ("Runtime.evaluate", _happy_metrics_response()),
            ("DOM.enable", {"result": {}}),
            ("DOM.getDocument", {"result": {}}),
            ("DOM.getNodeForLocation", {"result": {"backendNodeId": 55}}),
            ("DOM.resolveNode", {"result": {"object": {"objectId": "text-obj"}}}),
            ("Runtime.callFunctionOn", {"result": {"result": {"objectId": "parent-elem"}}}),
            ("Runtime.callFunctionOn", _eval_result(extracted)),
            ("DOM.getOuterHTML", {"result": {"outerHTML": "<span>hi</span>"}}),
            ("DOM.getBoxModel", {"result": {"model": {}}}),  # model rỗng, không có "content"
        ]
        ws = FakeWebSocket(script)
        result = browser_capture.extract_at(
            ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"}
        )
        self.assertTrue(result["ok"])
        self.assertIsNone(result["cssBox"])


# ===========================================================================
# 6. inspect_point — orchestrate lựa target + kiểm docked + extract, đếm số
#    WebSocket được MỞ trong từng nhánh (đúng theo §7-B2).
# ===========================================================================
def _patch_websocket_sequence(instances: list):
    iterator = iter(instances)

    def factory(url, timeout=30.0):
        try:
            return next(iterator)
        except StopIteration:
            raise AssertionError(f"WebSocket() bị gọi thừa với url={url!r}")

    return patch.object(browser_capture, "WebSocket", side_effect=factory)


class InspectPointOrchestrationTest(unittest.TestCase):
    def test_no_cdp_target_never_opens_any_websocket(self) -> None:
        request = {"point": {"x": 1, "y": 1}, "window": {"w": 800, "h": 600}, "candidates": []}
        with _patch_websocket_sequence([]):
            result = browser_capture.inspect_point(request)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_cdp_target")

    def test_single_candidate_no_devtools_opens_only_page_ws(self) -> None:
        extracted = {
            "tagName": "div", "selector": "#foo", "text": "hi", "textTruncated": False,
            "attributes": {}, "attrsTruncated": False, "notes": [], "shadowHostSelector": None,
        }
        page_ws = FakeWebSocket(_happy_extract_script(extracted))
        request = {
            "point": {"x": 500, "y": 350},
            "window": _happy_win_geom(),
            "candidates": [{"targetId": "T1", "webSocketDebuggerUrl": "ws://x/page/T1"}],
            "devtoolsTargetIds": [],
            "browserWebSocketUrl": "ws://x/browser",
        }
        with _patch_websocket_sequence([page_ws]) as ws_ctor:
            result = browser_capture.inspect_point(request)
        self.assertTrue(result["ok"])
        self.assertEqual(ws_ctor.call_count, 1)
        self.assertTrue(page_ws.closed)

    def test_devtools_docked_returns_before_opening_page_ws(self) -> None:
        browser_ws = FakeWebSocket([
            ("Browser.getWindowForTarget", {"result": {"windowId": 7}}),
            ("Browser.getWindowForTarget", {"result": {"windowId": 7}}),
        ])
        request = {
            "point": {"x": 500, "y": 350},
            "window": _happy_win_geom(),
            "candidates": [{"targetId": "T1", "webSocketDebuggerUrl": "ws://x/page/T1"}],
            "devtoolsTargetIds": ["DT1"],
            "browserWebSocketUrl": "ws://x/browser",
        }
        with _patch_websocket_sequence([browser_ws]) as ws_ctor:
            result = browser_capture.inspect_point(request)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "devtools_docked")
        self.assertEqual(ws_ctor.call_count, 1)  # chỉ browser ws, KHÔNG mở page ws
        self.assertTrue(browser_ws.closed)

    def test_need_browser_ws_but_no_browser_url_is_cdp_unreachable(self) -> None:
        request = {
            "point": {"x": 500, "y": 350},
            "window": _happy_win_geom(),
            "candidates": [{"targetId": "T1"}, {"targetId": "T2"}],
            "devtoolsTargetIds": [],
            "browserWebSocketUrl": "",
        }
        with _patch_websocket_sequence([]):
            result = browser_capture.inspect_point(request)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "cdp_unreachable")

    def test_ambiguous_target_never_opens_page_ws(self) -> None:
        browser_ws = FakeWebSocket([
            ("Browser.getWindowForTarget", browser_capture.WebSocketError("loi")),
            ("Browser.getWindowForTarget", browser_capture.WebSocketError("loi")),
        ])
        request = {
            "point": {"x": 500, "y": 350},
            "window": {"w": 800, "h": 600, "title": ""},
            "candidates": [{"targetId": "T1"}, {"targetId": "T2"}],
            "devtoolsTargetIds": [],
            "browserWebSocketUrl": "ws://x/browser",
        }
        with _patch_websocket_sequence([browser_ws]) as ws_ctor:
            result = browser_capture.inspect_point(request)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "ambiguous_target")
        self.assertEqual(ws_ctor.call_count, 1)

    def test_selected_candidate_missing_page_ws_url_is_no_cdp_target(self) -> None:
        request = {
            "point": {"x": 500, "y": 350},
            "window": _happy_win_geom(),
            "candidates": [{"targetId": "T1", "webSocketDebuggerUrl": ""}],
            "devtoolsTargetIds": [],
        }
        with _patch_websocket_sequence([]):
            result = browser_capture.inspect_point(request)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_cdp_target")


# ===========================================================================
# 7. Hàm thuần của inspect_element.py — hit-test hình học
# ===========================================================================
class NormalizeWinIdTest(unittest.TestCase):
    def test_hex_string_with_prefix(self) -> None:
        self.assertEqual(inspect_element._normalize_win_id("0x1e00003"), 0x1E00003)

    def test_hex_string_zero_padded_matches_unpadded(self) -> None:
        self.assertEqual(
            inspect_element._normalize_win_id("0x01e00003"),
            inspect_element._normalize_win_id("0x1e00003"),
        )

    def test_none_and_garbage_return_none(self) -> None:
        self.assertIsNone(inspect_element._normalize_win_id(None))
        self.assertIsNone(inspect_element._normalize_win_id("khong-phai-hex-gi-ca"))


class ContainsTest(unittest.TestCase):
    def test_half_open_rectangle_bounds(self) -> None:
        geom = {"x": 10, "y": 20, "w": 100, "h": 50}
        self.assertTrue(inspect_element._contains(geom, 10, 20))
        self.assertTrue(inspect_element._contains(geom, 109, 69))
        self.assertFalse(inspect_element._contains(geom, 110, 20))
        self.assertFalse(inspect_element._contains(geom, 10, 70))
        self.assertFalse(inspect_element._contains(geom, 9, 20))


class ExpandByExtentsTest(unittest.TestCase):
    def test_expands_client_geom_by_frame_extents(self) -> None:
        client_geom = {"x": 100, "y": 100, "w": 800, "h": 600}
        ext = {"left": 2, "right": 2, "top": 30, "bottom": 4}
        frame_geom = inspect_element._expand_by_extents(client_geom, ext)
        self.assertEqual(frame_geom, {"x": 98, "y": 70, "w": 804, "h": 634})


class ProbeZoneTest(unittest.TestCase):
    def test_expands_by_decoration_constants(self) -> None:
        client_geom = {"x": 100, "y": 100, "w": 800, "h": 600}
        zone = inspect_element._probe_zone(client_geom)
        side = inspect_element.MAX_DECORATION_SIDE_PX
        top = inspect_element.MAX_DECORATION_TOP_PX
        self.assertEqual(zone, {
            "x": 100 - side, "y": 100 - top,
            "w": 800 + 2 * side, "h": 600 + top + side,
        })


# ===========================================================================
# 9. _is_chromium / _app_name
# ===========================================================================
class IsChromiumAppNameTest(unittest.TestCase):
    def test_is_chromium_matches_hints_case_insensitive(self) -> None:
        self.assertTrue(inspect_element._is_chromium({"class": "chromium-browser.Chromium"}))
        self.assertTrue(inspect_element._is_chromium({"class": "Google-chrome.Google-chrome"}))
        self.assertFalse(inspect_element._is_chromium({"class": "gnome-terminal.Gnome-terminal"}))
        self.assertFalse(inspect_element._is_chromium({"class": ""}))
        self.assertFalse(inspect_element._is_chromium({}))

    def test_app_name_from_dotted_class(self) -> None:
        self.assertEqual(inspect_element._app_name("chromium-browser.Chromium"), "Chromium")

    def test_app_name_from_class_without_dot(self) -> None:
        self.assertEqual(inspect_element._app_name("Chromium"), "Chromium")

    def test_app_name_empty_for_empty_class(self) -> None:
        self.assertEqual(inspect_element._app_name(""), "")
        self.assertEqual(inspect_element._app_name(None), "")


# ===========================================================================
# 8. window_at_point — hit-test THIẾT KẾ ĐÃ SỬA: KHÔNG fallback khi stacking
#    rỗng, DỪNG quét ngay khi rơi vào dải nghi vấn frame_extents_unknown.
# ===========================================================================
def _wmctrl_line(win_id_hex: str, klass: str, title: str) -> str:
    return f"{win_id_hex} 0 {klass} host {title}"


class WindowAtPointTest(unittest.TestCase):
    def _patches(self, *, stacking, wmctrl_lines, probes, xprops, extents):
        """`probes`/`xprops`/`extents`: dict[win_id_hex] -> giá trị trả về."""
        return (
            patch.object(capture, "client_list_stacking", return_value=stacking),
            patch.object(capture, "_wmctrl_list", return_value="\n".join(wmctrl_lines)),
            patch.object(capture, "_wininfo_probe", side_effect=lambda win_id, **kw: probes.get(win_id)),
            patch.object(capture, "_xprop_many", side_effect=lambda win_id, props, **kw: xprops.get(win_id, {})),
            patch.object(capture, "frame_extents", side_effect=lambda win_id, **kw: extents.get(win_id)),
        )

    def test_empty_stacking_is_404_with_no_fallback(self) -> None:
        with patch.object(capture, "client_list_stacking", return_value=[]):
            with self.assertRaises(CaptureError) as caught:
                inspect_element.window_at_point(10, 10, inspect_element._deadline())
        self.assertEqual(caught.exception.status_code, 404)

    def test_hit_in_client_geom(self) -> None:
        patches = self._patches(
            stacking=[1],
            wmctrl_lines=[_wmctrl_line("0x00000001", "chromium-browser.Chromium", "Trang A")],
            probes={"0x00000001": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"}},
            xprops={"0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"}},
            extents={},
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            win = inspect_element.window_at_point(100, 100, inspect_element._deadline())
        self.assertEqual(win["_hitZone"], "client")
        self.assertEqual(win["pid"], 111)
        self.assertEqual(win["x"], 0)

    def test_hit_in_decoration_via_known_frame_extents(self) -> None:
        patches = self._patches(
            stacking=[1],
            wmctrl_lines=[_wmctrl_line("0x00000001", "chromium-browser.Chromium", "Trang A")],
            probes={"0x00000001": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"}},
            xprops={"0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"}},
            extents={"0x00000001": {"left": 5, "right": 5, "top": 30, "bottom": 5}},
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            win = inspect_element.window_at_point(802, 10, inspect_element._deadline())
        self.assertEqual(win["_hitZone"], "decoration")

    def test_frame_extents_unknown_in_probe_zone_stops_scan_immediately(self) -> None:
        # Cửa sổ TRÊN (id=2) có frame_extents lỗi đọc, điểm bấm rơi vào dải nghi
        # vấn quanh nó -> PHẢI dừng ngay ở cửa sổ trên, KHÔNG rơi xuống cửa sổ
        # dưới (id=1) dù cửa sổ dưới CŨNG khớp điểm bấm này trong client_geom.
        patches = self._patches(
            stacking=[1, 2],  # dưới->trên: 1 dưới, 2 trên cùng
            wmctrl_lines=[
                _wmctrl_line("0x00000001", "chromium-browser.Chromium", "Duoi"),
                _wmctrl_line("0x00000002", "chromium-browser.Chromium", "Tren"),
            ],
            probes={
                "0x00000001": {"x": -20, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"},
                "0x00000002": {"x": 100, "y": 100, "w": 800, "h": 600, "mapState": "IsViewable"},
            },
            xprops={
                "0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"},
                "0x00000002": {"_NET_WM_STATE": "", "_NET_WM_PID": "222"},
            },
            extents={"0x00000001": {"left": 0, "right": 0, "top": 0, "bottom": 0}},  # id=2: None (lỗi đọc)
        )
        # Điểm (90, 110): ngoài client id=2 ([100,900)x[100,700)) nhưng trong
        # probe_zone của id=2 (mở rộng SIDE=16/TOP=64) -> dừng tại id=2.
        # Điểm này CŨNG nằm trong client id=1 ([-20,780)x[0,600)) nếu bị quét tới.
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            win = inspect_element.window_at_point(90, 110, inspect_element._deadline())
        self.assertEqual(win["_hitZone"], "frame_extents_unknown")
        self.assertEqual(win["id"], "0x00000002")  # PHẢI là cửa sổ TRÊN, không rơi xuống id=1

    def test_frame_extents_unknown_outside_probe_zone_continues_to_window_below(self) -> None:
        patches = self._patches(
            stacking=[1, 2],
            wmctrl_lines=[
                _wmctrl_line("0x00000001", "chromium-browser.Chromium", "Duoi"),
                _wmctrl_line("0x00000002", "chromium-browser.Chromium", "Tren"),
            ],
            probes={
                "0x00000001": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"},
                "0x00000002": {"x": 2000, "y": 2000, "w": 800, "h": 600, "mapState": "IsViewable"},
            },
            xprops={
                "0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"},
                "0x00000002": {"_NET_WM_STATE": "", "_NET_WM_PID": "222"},
            },
            extents={},  # cả hai: None (lỗi đọc)
        )
        # Điểm bấm (100, 100) nằm rất xa cửa sổ trên (id=2 ở 2000,2000) -> ngoài
        # cả probe_zone của nó -> quét tiếp xuống id=1, khớp client id=1.
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            win = inspect_element.window_at_point(100, 100, inspect_element._deadline())
        self.assertEqual(win["id"], "0x00000001")
        self.assertEqual(win["_hitZone"], "client")

    def test_skips_non_viewable_window(self) -> None:
        patches = self._patches(
            stacking=[1, 2],
            wmctrl_lines=[
                _wmctrl_line("0x00000001", "chromium-browser.Chromium", "Duoi"),
                _wmctrl_line("0x00000002", "chromium-browser.Chromium", "Tren"),
            ],
            probes={
                "0x00000001": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"},
                "0x00000002": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsUnmapped"},
            },
            xprops={"0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"}},
            extents={},
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            win = inspect_element.window_at_point(100, 100, inspect_element._deadline())
        self.assertEqual(win["id"], "0x00000001")

    def test_skips_hidden_non_hittable_window(self) -> None:
        patches = self._patches(
            stacking=[1, 2],
            wmctrl_lines=[
                _wmctrl_line("0x00000001", "chromium-browser.Chromium", "Duoi"),
                _wmctrl_line("0x00000002", "chromium-browser.Chromium", "Tren"),
            ],
            probes={
                "0x00000001": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"},
                "0x00000002": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"},
            },
            xprops={
                "0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"},
                "0x00000002": {"_NET_WM_STATE": "_NET_WM_STATE_HIDDEN", "_NET_WM_PID": "222"},
            },
            extents={},
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            win = inspect_element.window_at_point(100, 100, inspect_element._deadline())
        self.assertEqual(win["id"], "0x00000001")

    def test_no_window_matches_after_scan_is_404(self) -> None:
        patches = self._patches(
            stacking=[1],
            wmctrl_lines=[_wmctrl_line("0x00000001", "chromium-browser.Chromium", "A")],
            probes={"0x00000001": {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"}},
            xprops={"0x00000001": {"_NET_WM_STATE": "", "_NET_WM_PID": "111"}},
            extents={},
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaises(CaptureError) as caught:
                inspect_element.window_at_point(5000, 5000, inspect_element._deadline())
        self.assertEqual(caught.exception.status_code, 404)

    def test_deadline_exhausted_mid_scan_is_504(self) -> None:
        patches = self._patches(
            stacking=[1],
            wmctrl_lines=[_wmctrl_line("0x00000001", "chromium-browser.Chromium", "A")],
            probes={},
            xprops={},
            extents={},
        )
        past_deadline = time.monotonic() - 1.0
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with self.assertRaises(CaptureError) as caught:
                inspect_element.window_at_point(100, 100, past_deadline)
        self.assertEqual(caught.exception.status_code, 504)


# ===========================================================================
# 10. _cdp_candidates — danh sách target thô /json/list (KHÔNG lọc như list_tabs())
# ===========================================================================
class _FakeHTTPResponse:
    def __init__(self, payload: bytes):
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None


class CdpCandidatesTest(unittest.TestCase):
    def test_splits_page_and_devtools_targets(self) -> None:
        targets = [
            {"id": "P1", "type": "page", "title": "Trang 1", "url": "http://a/",
             "webSocketDebuggerUrl": "ws://x/page/P1"},
            {"id": "DT1", "type": "other", "title": "DevTools", "url": "devtools://devtools/bundled/x.html"},
            {"id": "W1", "type": "worker", "title": "", "url": "http://a/worker.js"},
        ]
        payload = json.dumps(targets).encode("utf-8")
        with patch.object(capture, "browser_debugger_url", return_value="ws://x/browser"):
            with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(payload)):
                browser_ws_url, page_candidates, devtools_ids = inspect_element._cdp_candidates(
                    inspect_element._deadline()
                )
        self.assertEqual(browser_ws_url, "ws://x/browser")
        self.assertEqual(len(page_candidates), 1)
        self.assertEqual(page_candidates[0]["targetId"], "P1")
        self.assertEqual(devtools_ids, ["DT1"])

    def test_devtools_ids_unfiltered_by_query_string(self) -> None:
        # Lệch có ý so với văn bản kế hoạch: KHÔNG lọc theo targetId trong query
        # của URL devtools:// — thu thập MỌI target devtools:// (xem ghi chú lệch
        # trong báo cáo cuối). `_devtools_docked` mới là nơi khớp thật qua windowId.
        targets = [
            {"id": "DT1", "type": "other", "url": "devtools://devtools/bundled/x.html?ws=khac-hoan-toan"},
        ]
        payload = json.dumps(targets).encode("utf-8")
        with patch.object(capture, "browser_debugger_url", return_value="ws://x/browser"):
            with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(payload)):
                _, _, devtools_ids = inspect_element._cdp_candidates(inspect_element._deadline())
        self.assertEqual(devtools_ids, ["DT1"])

    def test_urlopen_error_raises_capture_error_502(self) -> None:
        with patch.object(capture, "browser_debugger_url", return_value="ws://x/browser"):
            with patch("urllib.request.urlopen", side_effect=OSError("ket noi tu choi")):
                with self.assertRaises(CaptureError) as caught:
                    inspect_element._cdp_candidates(inspect_element._deadline())
        self.assertEqual(caught.exception.status_code, 502)

    def test_no_page_candidates_when_only_devtools_targets(self) -> None:
        targets = [{"id": "DT1", "type": "other", "url": "devtools://devtools/bundled/x.html"}]
        payload = json.dumps(targets).encode("utf-8")
        with patch.object(capture, "browser_debugger_url", return_value="ws://x/browser"):
            with patch("urllib.request.urlopen", return_value=_FakeHTTPResponse(payload)):
                _, page_candidates, _ = inspect_element._cdp_candidates(inspect_element._deadline())
        self.assertEqual(page_candidates, [])


# ===========================================================================
# 11. _run_inspect_subprocess — spawn browser_capture.py qua STDIN (KHÔNG argv)
# ===========================================================================
class _FakeProc:
    def __init__(self, *, stdout="", stderr="", returncode=0, timeout_error=False):
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._timeout_error = timeout_error
        self.killed = False
        self.communicate_calls = 0

    def communicate(self, input=None, timeout=None):
        self.communicate_calls += 1
        if self._timeout_error and self.communicate_calls == 1:
            raise subprocess.TimeoutExpired(cmd="browser_capture.py", timeout=timeout)
        return self._stdout, self._stderr

    def kill(self) -> None:
        self.killed = True


class RunInspectSubprocessTest(unittest.TestCase):
    def test_happy_path_returns_parsed_json(self) -> None:
        proc = _FakeProc(stdout=json.dumps({"ok": True, "tagName": "div"}))
        with patch.object(capture, "_popen_as_agent", return_value=proc):
            result = inspect_element._run_inspect_subprocess({"a": 1}, timeout=5.0)
        self.assertEqual(result["tagName"], "div")

    def test_timeout_expired_propagates_and_kills_process(self) -> None:
        proc = _FakeProc(timeout_error=True)
        with patch.object(capture, "_popen_as_agent", return_value=proc):
            with self.assertRaises(subprocess.TimeoutExpired):
                inspect_element._run_inspect_subprocess({"a": 1}, timeout=0.01)
        self.assertTrue(proc.killed)
        self.assertEqual(proc.communicate_calls, 2)  # gọi lần 2 để rút hết ống dẫn sau kill

    def test_nonzero_exit_raises_subprocess_error(self) -> None:
        proc = _FakeProc(stderr="loi X11", returncode=1)
        with patch.object(capture, "_popen_as_agent", return_value=proc):
            with self.assertRaises(subprocess.SubprocessError):
                inspect_element._run_inspect_subprocess({"a": 1}, timeout=5.0)

    def test_bad_json_stdout_raises_value_error(self) -> None:
        proc = _FakeProc(stdout="khong-phai-json{{{")
        with patch.object(capture, "_popen_as_agent", return_value=proc):
            with self.assertRaises(ValueError):
                inspect_element._run_inspect_subprocess({"a": 1}, timeout=5.0)

    def test_request_sent_via_stdin_not_argv(self) -> None:
        # `webSocketDebuggerUrl` (bí mật) PHẢI đi qua STDIN, KHÔNG BAO GIỜ qua argv
        # (argv hiện trong ps/`/proc/<pid>/cmdline` của MỌI tiến trình trong container).
        secret_request = {"browserWebSocketUrl": "ws://x/browser/SECRET_TOKEN_ABC"}
        proc = _FakeProc(stdout=json.dumps({"ok": True}))
        captured_argv = []

        def fake_popen(args):
            captured_argv.extend(args)
            return proc

        with patch.object(capture, "_popen_as_agent", side_effect=fake_popen):
            inspect_element._run_inspect_subprocess(secret_request, timeout=5.0)
        self.assertNotIn("SECRET_TOKEN_ABC", " ".join(captured_argv))


# ===========================================================================
# 12. Cắt bớt dữ liệu — MAX_HTML_BYTES / MAX_TEXT_BYTES / MAX_ATTRS / MAX_ATTR_VALUE_BYTES
# ===========================================================================
class TruncateTest(unittest.TestCase):
    def test_truncate_text_below_limit_untouched(self) -> None:
        text, truncated = inspect_element._truncate_text("xin chao", 100)
        self.assertEqual(text, "xin chao")
        self.assertFalse(truncated)

    def test_truncate_text_utf8_boundary_safe(self) -> None:
        # "à" mã hoá 2 byte UTF-8 — cắt ngay giữa byte của "à" không được vỡ chuỗi.
        text = "a" * 9 + "à"  # byte 10-11 là ký tự đa byte
        truncated_text, was_truncated = inspect_element._truncate_text(text, 10)
        self.assertTrue(was_truncated)
        # Kết quả PHẢI decode được (không lỗi) — không assert nội dung cụ thể vì
        # errors="ignore" có thể bỏ byte lẻ cuối cùng.
        truncated_text.encode("utf-8")  # không raise là đủ

    def test_truncate_text_handles_none(self) -> None:
        text, truncated = inspect_element._truncate_text(None, 10)
        self.assertEqual(text, "")
        self.assertFalse(truncated)

    def test_truncate_attributes_enforces_max_attrs(self) -> None:
        attrs = {f"attr-{i}": "gia-tri" for i in range(inspect_element.MAX_ATTRS + 1)}
        result, truncated = inspect_element._truncate_attributes(attrs)
        self.assertTrue(truncated)
        self.assertEqual(len(result), inspect_element.MAX_ATTRS)

    def test_truncate_attributes_enforces_max_attr_value_bytes(self) -> None:
        long_value = "x" * (inspect_element.MAX_ATTR_VALUE_BYTES + 100)
        attrs = {"data-x": long_value}
        result, truncated = inspect_element._truncate_attributes(attrs)
        self.assertTrue(truncated)
        self.assertLessEqual(len(result["data-x"].encode("utf-8")), inspect_element.MAX_ATTR_VALUE_BYTES)

    def test_truncate_attributes_non_dict_returns_empty(self) -> None:
        result, truncated = inspect_element._truncate_attributes("khong-phai-dict")
        self.assertEqual(result, {})
        self.assertFalse(truncated)

    def test_dom_response_html_and_text_truncation_flags(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        child = {
            "html": "<div>" + "a" * inspect_element.MAX_HTML_BYTES + "</div>",
            "text": "b" * (inspect_element.MAX_TEXT_BYTES + 10),
            "attributes": {}, "targetId": "T1",
        }
        payload = inspect_element._dom_response(win, child)
        self.assertTrue(payload["truncated"])
        self.assertLessEqual(len(payload["html"].encode("utf-8")), inspect_element.MAX_HTML_BYTES)
        self.assertLessEqual(len(payload["text"].encode("utf-8")), inspect_element.MAX_TEXT_BYTES)

    def test_dom_response_propagates_truncated_in_page_flag(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        child = {"html": "ok", "text": "ok", "attributes": {}, "targetId": "T1", "truncatedInPage": True}
        payload = inspect_element._dom_response(win, child)
        self.assertTrue(payload["truncated"])


# ===========================================================================
# 13. Hash + label — dữ liệu KHÔNG TIN ĐƯỢC trên CẢ HAI nhánh (§5.4)
# ===========================================================================
class HashLabelTest(unittest.TestCase):
    def test_hash_is_deterministic_regardless_of_key_order(self) -> None:
        payload_a = {"type": "desktop", "windowId": "1", "extra": {"a": 1, "b": 2}}
        payload_b = {"extra": {"b": 2, "a": 1}, "windowId": "1", "type": "desktop"}
        self.assertEqual(
            inspect_element._canonical_payload_hash(payload_a),
            inspect_element._canonical_payload_hash(payload_b),
        )

    def test_hash_has_sha256_prefix(self) -> None:
        digest = inspect_element._canonical_payload_hash({"a": 1})
        self.assertTrue(digest.startswith("sha256:"))
        self.assertEqual(len(digest), len("sha256:") + 64)

    def test_label_has_fixed_untrusted_internal_values(self) -> None:
        label = inspect_element._label("0x1", "sha256:abc")
        self.assertEqual(label["integrity"], "khong_tin_duoc")
        self.assertEqual(label["confidentiality"], "noi_bo")
        self.assertEqual(label["source_kind"], "screen_capture")
        self.assertEqual(label["tool_name"], "inspect_element")
        self.assertEqual(label["content_hash"], "sha256:abc")

    def test_source_uri_format_has_no_selector_embedded(self) -> None:
        label = inspect_element._label("0x1e00003", "sha256:abc")
        self.assertEqual(label["source_uri"], "screen://element/0x1e00003")
        self.assertNotIn("selector", label["source_uri"])

    def test_hash_computed_before_label_attached_no_self_reference(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "x", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win)
        # Hash lại KHÔNG có khoá label -> phải khớp với content_hash đã gắn.
        without_label = {k: v for k, v in payload.items() if k != "label"}
        self.assertEqual(
            inspect_element._canonical_payload_hash(without_label),
            payload["label"]["content_hash"],
        )


# ===========================================================================
# 14. _desktop_response
# ===========================================================================
class DesktopResponseTest(unittest.TestCase):
    def test_not_chromium_omits_reason_and_message(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "gnome-terminal.Gnome-terminal", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win, "not_chromium")
        self.assertNotIn("reason", payload)
        self.assertNotIn("message", payload)
        self.assertEqual(payload["type"], "desktop")

    def test_real_reason_includes_message(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win, "cdp_timeout", inspect_element.MSG["cdp_timeout"])
        self.assertEqual(payload["reason"], "cdp_timeout")
        self.assertEqual(payload["message"], inspect_element.MSG["cdp_timeout"])

    def test_pid_omitted_when_none(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "x", "x": 0, "y": 0, "w": 1, "h": 1, "pid": None}
        payload = inspect_element._desktop_response(win)
        self.assertNotIn("pid", payload)

    def test_pid_included_when_present(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "x", "x": 0, "y": 0, "w": 1, "h": 1, "pid": 999}
        payload = inspect_element._desktop_response(win)
        self.assertEqual(payload["pid"], 999)

    def test_app_name_omitted_when_empty_class(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win)
        self.assertNotIn("appName", payload)

    def test_app_name_present_for_known_class(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win)
        self.assertEqual(payload["appName"], "Chromium")

    def test_unknown_reason_falls_back_to_extract_failed_message_via_dispatch(self) -> None:
        # Đường đi thật: dispatch dùng MSG.get(reason, MSG['extract_failed']) khi
        # message rỗng và reason không có sẵn message soạn trước.
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win, "mot_reason_la_gi_do")
        self.assertEqual(payload["message"], inspect_element.MSG["extract_failed"])


# ===========================================================================
# 15. _dom_response
# ===========================================================================
class DomResponseTest(unittest.TestCase):
    def test_builds_full_payload_with_target_allow_list(self) -> None:
        win = {"id": "0x1e00003", "title": "Trang cua so", "class": "chromium-browser.Chromium",
               "x": 0, "y": 0, "w": 1, "h": 1}
        child = {
            "html": "<div id=\"foo\">hi</div>", "text": "hi", "attributes": {"id": "foo"},
            "targetId": "T1", "selector": "#foo", "url": "http://x/", "title": "X",
            "tagName": "div", "cssBox": {"x": 1}, "screenBox": {"x": 2}, "notes": [],
            "shadowHostSelector": None,
        }
        payload = inspect_element._dom_response(win, child)
        self.assertEqual(payload["type"], "dom")
        self.assertEqual(payload["selector"], "#foo")
        self.assertEqual(
            payload["target"],
            {"windowId": "0x1e00003", "windowTitle": "Trang cua so", "targetId": "T1"},
        )
        self.assertIn("label", payload)

    def test_notes_default_to_empty_list(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        child = {"html": "", "text": "", "attributes": {}, "targetId": "T1"}
        payload = inspect_element._dom_response(win, child)
        self.assertEqual(payload["notes"], [])


# ===========================================================================
# 16. _validate_point
# ===========================================================================
class ValidatePointTest(unittest.TestCase):
    def test_accepts_valid_in_range_point(self) -> None:
        with patch.object(capture, "screen_size", return_value=(1920, 1080)):
            x, y = inspect_element._validate_point(100, 200)
        self.assertEqual((x, y), (100, 200))

    def test_rejects_bool_even_though_bool_is_int_subclass(self) -> None:
        with patch.object(capture, "screen_size", return_value=(1920, 1080)):
            with self.assertRaises(CaptureError) as caught:
                inspect_element._validate_point(True, 200)
        self.assertEqual(caught.exception.status_code, 400)

    def test_rejects_non_int(self) -> None:
        with patch.object(capture, "screen_size", return_value=(1920, 1080)):
            with self.assertRaises(CaptureError):
                inspect_element._validate_point(100.5, 200)
            with self.assertRaises(CaptureError):
                inspect_element._validate_point("100", 200)

    def test_rejects_negative(self) -> None:
        with patch.object(capture, "screen_size", return_value=(1920, 1080)):
            with self.assertRaises(CaptureError):
                inspect_element._validate_point(-1, 200)

    def test_rejects_out_of_range(self) -> None:
        with patch.object(capture, "screen_size", return_value=(1920, 1080)):
            with self.assertRaises(CaptureError):
                inspect_element._validate_point(1920, 200)
            with self.assertRaises(CaptureError):
                inspect_element._validate_point(100, 1080)


# ===========================================================================
# 17. Semaphore đồng thời — MAX_CONCURRENT_INSPECTS = 2
# ===========================================================================
class DispatchSemaphoreTest(unittest.TestCase):
    def test_third_concurrent_call_is_429(self) -> None:
        acquired = []
        try:
            for _ in range(inspect_element.MAX_CONCURRENT_INSPECTS):
                self.assertTrue(inspect_element._INSPECT_SEMAPHORE.acquire(blocking=False))
                acquired.append(True)
            with self.assertRaises(CaptureError) as caught:
                inspect_element.dispatch_inspect_element(1, 1)
            self.assertEqual(caught.exception.status_code, 429)
        finally:
            for _ in acquired:
                inspect_element._INSPECT_SEMAPHORE.release()


# ===========================================================================
# 18. Ngân sách thời gian không bao giờ vượt REQUEST_BUDGET_SEC
# ===========================================================================
class DeadlineNeverExceedsBudgetTest(unittest.TestCase):
    def test_subprocess_timeout_cap_exceeds_budget_but_is_never_hit(self) -> None:
        # Hằng SUBPROCESS_TIMEOUT_SEC (10s) LỚN HƠN REQUEST_BUDGET_SEC (8s) một
        # cách CÓ Ý — nó chỉ là lưới an toàn, KHÔNG BAO GIỜ là timeout thật dùng.
        self.assertGreater(inspect_element.SUBPROCESS_TIMEOUT_SEC, inspect_element.REQUEST_BUDGET_SEC)

    def test_sub_timeout_never_exceeds_remaining_budget(self) -> None:
        deadline = inspect_element._deadline()
        sub_timeout = inspect_element._sub_timeout(deadline)
        self.assertLessEqual(sub_timeout, inspect_element.REQUEST_BUDGET_SEC + 0.01)

    def test_sub_timeout_floors_at_50ms_when_budget_almost_gone(self) -> None:
        almost_gone = time.monotonic() + 0.001
        self.assertEqual(inspect_element._sub_timeout(almost_gone), 0.05)

    def test_clamped_timeout_never_negative(self) -> None:
        past_deadline = time.monotonic() - 100
        self.assertEqual(inspect_element._clamped_timeout(past_deadline, 5), 0.05)


# ===========================================================================
# 19. _dispatch_inspect_element_locked — orchestration đầy đủ ở tầng inspect_element.py
#     (khác `browser_capture.inspect_point` — đây là tầng box, mock window_at_point
#     + _cdp_candidates + _run_inspect_subprocess để đi hết các nhánh desktop/dom).
# ===========================================================================
def _chromium_win(hit_zone: str = "client") -> dict:
    return {
        "id": "0x1e00003", "title": "Trang X", "class": "chromium-browser.Chromium",
        "x": 0, "y": 0, "w": 800, "h": 600, "pid": 111, "_hitZone": hit_zone,
    }


class DispatchLockedTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(capture, "screen_size", return_value=(1920, 1080))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_decoration_hit_zone_is_desktop_outside_viewport(self) -> None:
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win("decoration")):
            result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["type"], "desktop")
        self.assertEqual(result["reason"], "outside_viewport")

    def test_frame_extents_unknown_hit_zone_checked_before_is_chromium(self) -> None:
        win = _chromium_win("frame_extents_unknown")
        win["class"] = "gnome-terminal.Gnome-terminal"  # KHÔNG phải Chromium
        with patch.object(inspect_element, "window_at_point", return_value=win):
            result = inspect_element._dispatch_inspect_element_locked(1, 1)
        # PHẢI vẫn là frame_extents_unknown (kiểm tra trước _is_chromium), KHÔNG
        # rơi xuống not_chromium — áp dụng bất kể loại cửa sổ.
        self.assertEqual(result["reason"], "frame_extents_unknown")

    def test_non_chromium_window_is_desktop_not_chromium(self) -> None:
        win = _chromium_win("client")
        win["class"] = "gnome-terminal.Gnome-terminal"
        with patch.object(inspect_element, "window_at_point", return_value=win):
            result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["type"], "desktop")
        self.assertNotIn("reason", result)

    def test_no_page_candidates_is_desktop_no_cdp_target(self) -> None:
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(inspect_element, "_cdp_candidates", return_value=(None, [], [])):
                result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["reason"], "no_cdp_target")

    def test_cdp_candidates_capture_error_is_cdp_unreachable(self) -> None:
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(inspect_element, "_cdp_candidates", side_effect=CaptureError("loi", status_code=502)):
                result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["reason"], "cdp_unreachable")

    def test_subprocess_timeout_expired_is_cdp_timeout_not_subprocess_error(self) -> None:
        # PHẢI bắt TimeoutExpired TRƯỚC SubprocessError (nó là lớp con) -> reason
        # đúng là cdp_timeout, KHÔNG rơi vào cdp_unreachable.
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(
                inspect_element, "_cdp_candidates",
                return_value=("ws://x/browser", [{"targetId": "T1"}], []),
            ):
                with patch.object(
                    inspect_element, "_run_inspect_subprocess",
                    side_effect=subprocess.TimeoutExpired(cmd="x", timeout=8.0),
                ):
                    result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["reason"], "cdp_timeout")

    def test_subprocess_error_is_cdp_unreachable(self) -> None:
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(
                inspect_element, "_cdp_candidates",
                return_value=("ws://x/browser", [{"targetId": "T1"}], []),
            ):
                with patch.object(
                    inspect_element, "_run_inspect_subprocess",
                    side_effect=subprocess.SubprocessError("loi"),
                ):
                    result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["reason"], "cdp_unreachable")

    def test_child_not_ok_maps_reason_through_msg_table(self) -> None:
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(
                inspect_element, "_cdp_candidates",
                return_value=("ws://x/browser", [{"targetId": "T1"}], []),
            ):
                with patch.object(
                    inspect_element, "_run_inspect_subprocess",
                    return_value={"ok": False, "reason": "devtools_docked"},
                ):
                    result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["reason"], "devtools_docked")
        self.assertEqual(result["message"], inspect_element.MSG["devtools_docked"])

    def test_child_ok_true_returns_dom_response(self) -> None:
        child = {
            "ok": True, "html": "<div>hi</div>", "text": "hi", "attributes": {},
            "targetId": "T1", "selector": "#foo", "url": "http://x/", "title": "X", "tagName": "div",
        }
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(
                inspect_element, "_cdp_candidates",
                return_value=("ws://x/browser", [{"targetId": "T1"}], []),
            ):
                with patch.object(inspect_element, "_run_inspect_subprocess", return_value=child):
                    result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["type"], "dom")
        self.assertEqual(result["selector"], "#foo")

    def test_deadline_already_exhausted_before_cdp_is_cdp_timeout(self) -> None:
        past_deadline = time.monotonic() - 1.0
        with patch.object(inspect_element, "_deadline", return_value=past_deadline):
            with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
                result = inspect_element._dispatch_inspect_element_locked(1, 1)
        self.assertEqual(result["reason"], "cdp_timeout")


# ===========================================================================
# 20. SecretLeakTest — bài kiểm QUAN TRỌNG NHẤT trong toàn kế hoạch (§10.1):
#     `webSocketDebuggerUrl` / `devtoolsFrontendUrl` KHÔNG BAO GIỜ được xuất
#     hiện ở BẤT KỲ ĐỘ SÂU nào trong response — cả nhánh `dom` VÀ `desktop`,
#     kể cả trên đường lỗi. Rò 1 lần là mất TCB (Chromium bị điều khiển toàn quyền).
# ===========================================================================
_SECRET_TOKENS = (
    "SECRET_WS_TOKEN_9f8a7b6c",
    "SECRET_DEVTOOLS_FRONTEND_TOKEN",
)


def _assert_no_secret_anywhere(testcase: unittest.TestCase, payload) -> None:
    # 1) Tìm chuỗi con trên toàn bộ payload đã serialize — bắt rò ở BẤT KỲ khoá nào.
    dumped = json.dumps(payload, default=str, ensure_ascii=False)
    for token in _SECRET_TOKENS:
        testcase.assertNotIn(token, dumped, f"Rò bí mật '{token}' trong JSON đã serialize")

    # 2) Duyệt đệ quy TOÀN BỘ khoá + giá trị — kỹ hơn tìm chuỗi con (bắt cả khi
    #    default=str hoặc kiểu dữ liệu lạ làm (1) bỏ lỡ).
    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                for token in _SECRET_TOKENS:
                    testcase.assertNotIn(
                        token, str(key), f"Rò bí mật '{token}' trong KHOÁ tại {path}.{key}"
                    )
                walk(value, f"{path}.{key}")
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
        else:
            text = str(node)
            for token in _SECRET_TOKENS:
                testcase.assertNotIn(token, text, f"Rò bí mật '{token}' trong GIÁ TRỊ tại {path}")

    walk(payload, "$")


class SecretLeakTest(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.object(capture, "screen_size", return_value=(1920, 1080))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_dom_response_direct_never_leaks_even_if_child_carries_secret_keys(self) -> None:
        # Cố ý nhồi các khoá bí mật vào `child` như thể browser_capture.py có lỗi
        # để lộ — `_dom_response` PHẢI vẫn không rò vì nó chỉ đọc field cụ thể,
        # KHÔNG BAO GIỜ `{**child}`.
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        child = {
            "html": "<div>hi</div>", "text": "hi", "attributes": {}, "targetId": "T1",
            "webSocketDebuggerUrl": f"ws://127.0.0.1:9222/devtools/page/{_SECRET_TOKENS[0]}",
            "devtoolsFrontendUrl": f"devtools://devtools/bundled/inspector.html?{_SECRET_TOKENS[1]}",
        }
        payload = inspect_element._dom_response(win, child)
        _assert_no_secret_anywhere(self, payload)

    def test_desktop_response_direct_never_leaks(self) -> None:
        win = {"id": "0x1", "title": "T", "class": "chromium-browser.Chromium", "x": 0, "y": 0, "w": 1, "h": 1}
        payload = inspect_element._desktop_response(win, "cdp_timeout", inspect_element.MSG["cdp_timeout"])
        _assert_no_secret_anywhere(self, payload)

    def test_full_dispatch_dom_success_never_leaks(self) -> None:
        candidates = [{"targetId": "T1", "webSocketDebuggerUrl": f"ws://x/page/{_SECRET_TOKENS[0]}"}]
        child = {
            "ok": True, "html": "<div>hi</div>", "text": "hi", "attributes": {}, "targetId": "T1",
            "selector": "#foo", "url": "http://x/", "title": "X", "tagName": "div",
            # Phòng vệ sâu: dù browser_capture.py lỡ để lọt các khoá này vào child,
            # _dom_response cũng KHÔNG BAO GIỜ dùng chúng.
            "webSocketDebuggerUrl": f"ws://x/page/{_SECRET_TOKENS[0]}",
        }
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(
                inspect_element, "_cdp_candidates",
                return_value=(f"ws://x/browser/{_SECRET_TOKENS[0]}", candidates, []),
            ):
                with patch.object(inspect_element, "_run_inspect_subprocess", return_value=child):
                    result = inspect_element._dispatch_inspect_element_locked(1, 1)
        _assert_no_secret_anywhere(self, result)

    def test_full_dispatch_error_paths_never_leak(self) -> None:
        candidates = [{"targetId": "T1", "webSocketDebuggerUrl": f"ws://x/page/{_SECRET_TOKENS[0]}"}]
        for reason in ("devtools_docked", "viewport_origin_unknown", "no_node_at_point", "extract_failed"):
            with self.subTest(reason=reason):
                with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
                    with patch.object(
                        inspect_element, "_cdp_candidates",
                        return_value=(f"ws://x/browser/{_SECRET_TOKENS[0]}", candidates, []),
                    ):
                        with patch.object(
                            inspect_element, "_run_inspect_subprocess",
                            return_value={"ok": False, "reason": reason},
                        ):
                            result = inspect_element._dispatch_inspect_element_locked(1, 1)
                _assert_no_secret_anywhere(self, result)

    def test_cdp_unreachable_path_never_leaks(self) -> None:
        with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
            with patch.object(
                inspect_element, "_cdp_candidates",
                side_effect=CaptureError(f"loi ket noi {_SECRET_TOKENS[0]}", status_code=502),
            ):
                result = inspect_element._dispatch_inspect_element_locked(1, 1)
        # KHÔNG assert public_message của CaptureError (đó là kênh lỗi khác, không
        # phải payload trả về người dùng cuối) — chỉ assert PAYLOAD trả ra.
        _assert_no_secret_anywhere(self, result)

    def test_public_inspect_target_allow_list_drops_websocket_key_even_if_present(self) -> None:
        win = {"id": "0x1", "title": "T"}
        tab = {"targetId": "T1", "webSocketDebuggerUrl": f"ws://x/{_SECRET_TOKENS[0]}"}
        target = capture._public_inspect_target(win, tab)
        _assert_no_secret_anywhere(self, target)
        self.assertEqual(set(target.keys()), {"windowId", "windowTitle", "targetId"})


# ===========================================================================
# 21. NoPointerMoveTest — đảm bảo đường thanh tra KHÔNG BAO GIỜ di/click chuột
#     (bấm [X] của Chrome trong lúc thanh tra không được đóng thật Chrome).
# ===========================================================================
class NoPointerMoveTest(unittest.TestCase):
    def test_window_at_point_never_shells_out_to_xdotool(self) -> None:
        recorded_argv: list[list[str]] = []

        def fake_run_as_agent(args, *, timeout=30):
            recorded_argv.append(list(args))
            raise AssertionError("khong nen goi _run_as_agent trong test nay (da mock cac ham cap cao hon)")

        win = {"x": 0, "y": 0, "w": 800, "h": 600, "mapState": "IsViewable"}
        with patch.object(capture, "_run_as_agent", side_effect=fake_run_as_agent):
            with patch.object(capture, "client_list_stacking", return_value=[1]):
                with patch.object(
                    capture, "_wmctrl_list",
                    return_value=_wmctrl_line("0x00000001", "chromium-browser.Chromium", "A"),
                ):
                    with patch.object(capture, "_wininfo_probe", return_value=win):
                        with patch.object(
                            capture, "_xprop_many",
                            return_value={"_NET_WM_STATE": "", "_NET_WM_PID": "111"},
                        ):
                            with patch.object(capture, "frame_extents", return_value=None):
                                result = inspect_element.window_at_point(100, 100, inspect_element._deadline())
        self.assertEqual(result["_hitZone"], "client")
        self.assertEqual(recorded_argv, [])  # KHÔNG hề gọi _run_as_agent thật nào

    def test_extract_at_command_sequence_contains_no_mouse_input(self) -> None:
        extracted = {
            "tagName": "div", "selector": "#foo", "text": "hi", "textTruncated": False,
            "attributes": {}, "attrsTruncated": False, "notes": [], "shadowHostSelector": None,
        }
        ws = FakeWebSocket(_happy_extract_script(extracted))
        browser_capture.extract_at(ws, {"x": 500, "y": 350}, _happy_win_geom(), {}, {"targetId": "T1"})
        for name in ws.call_names():
            self.assertNotIn("Input.", name)
            self.assertNotIn("mousemove", name.lower())
            self.assertNotIn("click", name.lower())
        self.assertNotIn("Input.dispatchMouseEvent", ws.call_names())

    def test_full_dispatch_never_touches_xdotool_or_raise_window(self) -> None:
        # `capture._raise_window` (dùng wmctrl -ia / xdotool windowactivate/raise)
        # là hàm CHỈ dùng cho capture()/dispatch_capture — đường inspect_element
        # KHÔNG BAO GIỜ được gọi tới nó.
        child = {
            "ok": True, "html": "<div>hi</div>", "text": "hi", "attributes": {}, "targetId": "T1",
            "selector": "#foo", "url": "http://x/", "title": "X", "tagName": "div",
        }
        with patch.object(capture, "screen_size", return_value=(1920, 1080)):
            with patch.object(capture, "_raise_window") as raise_mock:
                with patch.object(inspect_element, "window_at_point", return_value=_chromium_win()):
                    with patch.object(
                        inspect_element, "_cdp_candidates",
                        return_value=("ws://x/browser", [{"targetId": "T1"}], []),
                    ):
                        with patch.object(inspect_element, "_run_inspect_subprocess", return_value=child):
                            inspect_element.dispatch_inspect_element(1, 1)
        raise_mock.assert_not_called()
