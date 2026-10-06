"""Test nhánh soi phần tử H6 — thứ tự dom → uia → desktop, 17 mã lý do, label (§4.1)."""
from __future__ import annotations

import json

import pytest
from win_fakes import (
    FakePlatform,
    FakeUiaAccessor,
    make_window,
    reset_win_state,
    uia_node,
)

from agentbox.agent_core import inspect_host
from agentbox.sandbox.win import capture, uia
from agentbox.sandbox.win.errors import (
    AMBIGUOUS_TARGET,
    CONTROL_BUSY,
    CDP_UNREACHABLE,
    EXTRACT_FAILED,
    FRAME_EXTENTS_UNKNOWN,
    INSPECT_MESSAGES,
    INSPECT_REASONS,
    NO_CDP_TARGET,
    NO_WINDOW_AT_POINT,
    OUTSIDE_VIEWPORT,
    UIA_NO_ELEMENT,
    UIA_TIMEOUT,
    UIA_UNAVAILABLE,
    UIA_UNAVAILABLE_REASON,
    VIEWPORT_ORIGIN_UNKNOWN,
    WINDOW_IDENTITY_UNAVAILABLE_REASON,
    PlatformError,
)
from agentbox.sandbox.win.windows_platform import SECURITY_MANDATORY_HIGH_RID

CHILD = {
    "targetId": "TARGET-ID",
    "frameId": "FRAME-1",
    "url": "https://example.test/page",
    "title": "Trang ví dụ",
    "tagName": "button",
    "selector": "#submit",
    "text": "Gửi",
    "attributes": {"id": "submit", "class": "primary"},
    "html": "<button id=\"submit\">Gửi</button>",
    "truncatedInPage": False,
    "cssBox": {"x": 10, "y": 20, "width": 100, "height": 30},
    "screenBox": {"x": 110, "y": 140, "width": 100, "height": 30},
    "notes": [],
    "shadowHostSelector": None,
    "viewport": {"originX": 100.0, "originY": 120.0, "dpr": 1.0, "innerWidth": 800, "innerHeight": 600},
}


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    inspect_host.set_cdp_inspector(None)
    uia.set_session(None)
    yield
    reset_win_state()
    inspect_host.set_cdp_inspector(None)
    uia.set_session(None)


def _chromium_platform(**kwargs):
    return FakePlatform(windows=[make_window(100)], uia_accessor=FakeUiaAccessor(**kwargs.pop("uia", {})))


def _inspector(child=None, error=None, calls=None):
    def run(request):
        if calls is not None:
            calls.append(request)
        if error is not None:
            raise error
        return dict(child or CHILD)

    return run


# ---------------------------------------------------------------------------
# Nhánh 1: dom
# ---------------------------------------------------------------------------
def test_dom_branch_wins_for_chromium_with_cdp():
    calls = []
    platform = _chromium_platform()
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector(calls=calls))
    assert result["type"] == "dom"
    assert result["selector"] == "#submit"
    assert result["url"] == "https://example.test/page"
    assert result["truncated"] is False
    assert result["screenBox"] == CHILD["screenBox"]
    assert calls[0]["window"]["w"] == 800
    assert calls[0]["window"]["title"] == "BoxFox Test Window"
    assert calls[0]["point"] == {"x": 150, "y": 160}


def test_dom_target_block_has_exactly_three_keys():
    platform = _chromium_platform()
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    assert set(result["target"]) == {"windowId", "windowTitle", "targetId"}
    assert result["target"]["targetId"] == "TARGET-ID"
    assert result["target"]["windowId"] == "100"


def test_websocket_debugger_url_never_leaks():
    child = dict(CHILD, webSocketDebuggerUrl="ws://127.0.0.1:9222/devtools/page/SECRET")
    platform = _chromium_platform()
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector(child))
    serialized = json.dumps(result)
    assert "SECRET" not in serialized
    assert "webSocketDebuggerUrl" not in serialized
    assert "ws://" not in serialized


def test_dom_branch_is_not_attempted_for_non_chromium():
    calls = []
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")],
        uia_accessor=FakeUiaAccessor(),
    )
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector(calls=calls))
    assert calls == []
    assert result["type"] == "uia"


def test_frame_extents_unknown_when_dwm_bounds_missing():
    calls = []
    platform = FakePlatform(
        windows=[make_window(100, extended_bounds=None)],
        uia_accessor=FakeUiaAccessor(),
    )
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector(calls=calls))
    assert result["type"] == "desktop"
    assert result["reason"] == FRAME_EXTENTS_UNKNOWN
    assert result["message"] == INSPECT_MESSAGES[FRAME_EXTENTS_UNKNOWN]
    assert calls == []


def test_cdp_failure_falls_through_to_uia_branch():
    platform = _chromium_platform()
    result = inspect_host.inspect_element(
        150, 160, platform=platform, cdp=_inspector(error=PlatformError(NO_CDP_TARGET))
    )
    # PlatformError không phải CdpError ⇒ extract_failed, nhưng vẫn rơi xuống UIA.
    assert result["type"] == "uia"


def test_cdp_reason_surfaces_when_uia_also_fails():
    platform = FakePlatform(
        windows=[make_window(100)], uia_accessor=FakeUiaAccessor(errors=5, exception=RuntimeError("boom"))
    )
    result = inspect_host.inspect_element(
        150, 160,
        platform=platform,
        cdp=_inspector(error=inspect_host.CdpError(OUTSIDE_VIEWPORT)),
    )
    assert result["type"] == "desktop"
    assert result["reason"] == OUTSIDE_VIEWPORT
    assert result["message"] == INSPECT_MESSAGES[OUTSIDE_VIEWPORT]


def test_ambiguous_target_carries_safe_tab_list_only():
    candidates = [
        {
            "targetId": "T1",
            "title": "Tab một",
            "url": "https://a.test",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/page/T1",
        }
    ]
    error = inspect_host.CdpError(AMBIGUOUS_TARGET, candidates=candidates)
    platform = FakePlatform(windows=[make_window(100)], uia_accessor=FakeUiaAccessor(errors=5))
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector(error=error))
    assert result["reason"] == AMBIGUOUS_TARGET
    assert result["tabs"] == [{"targetId": "T1", "title": "Tab một", "url": "https://a.test"}]
    assert "webSocketDebuggerUrl" not in json.dumps(result)


def test_default_inspector_reports_no_cdp_target_without_endpoint(monkeypatch):
    monkeypatch.setattr(inspect_host, "cdp_endpoint", lambda **kwargs: None)
    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host.default_cdp_inspector(
            {"point": {"x": 1, "y": 1}, "window": {"x": 0, "y": 0, "w": 800, "h": 600, "title": "t"}}
        )
    assert error.value.reason == NO_CDP_TARGET


def test_default_inspector_maps_connection_failure(monkeypatch):
    monkeypatch.setattr(inspect_host, "cdp_endpoint", lambda **kwargs: "http://127.0.0.1:1")
    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host.default_cdp_inspector(
            {"point": {"x": 1, "y": 1}, "window": {"x": 0, "y": 0, "w": 800, "h": 600, "title": "t"}}
        )
    assert error.value.reason == CDP_UNREACHABLE


# ---------------------------------------------------------------------------
# Nhánh 2: uia
# ---------------------------------------------------------------------------
def test_uia_branch_payload_fields():
    accessor = FakeUiaAccessor(
        nodes=[uia_node(name="Gửi", patterns=["Invoke", "Value"], bounds=(110, 140, 100, 30))]
    )
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")],
        uia_accessor=accessor,
    )
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert result["type"] == "uia"
    assert result["name"] == "Gửi"
    assert result["controlType"] == "Button"
    assert result["controlTypeId"] == 50000
    assert result["automationId"] == "okButton"
    assert result["className"] == "Button"
    assert result["helpText"] == ""
    assert result["isEnabled"] is True
    assert result["isOffscreen"] is False
    assert result["isPassword"] is False
    assert result["bounds"]["screenBox"] == {"x": 110, "y": 140, "width": 100, "height": 30}
    assert result["bounds"]["dpi"] == 96
    assert result["patterns"] == ["Invoke", "Value"]
    assert result["windowId"] == "100"
    assert result["pid"] == 1000
    assert result["processName"] == "notepad.exe"
    assert result["elementToken"] == "s00000001:0"
    assert result["generation"] == 1
    assert result["label"]["source_uri"] == "screen://element/100"


def test_uia_branch_uses_token_from_current_snapshot():
    accessor = FakeUiaAccessor()
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")], uia_accessor=accessor
    )
    result = inspect_host.inspect_element(150, 160, platform=platform)
    session = uia.get_session(platform)
    node = session.resolve(result["elementToken"])
    assert node.runtime_id == "42.1"
    assert session.registry.snapshot_id == 1


def test_uia_dpi_key_is_dropped_when_unknown():
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")], uia_accessor=FakeUiaAccessor()
    )
    platform.get_dpi_for_window = lambda hwnd: None
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert "dpi" not in result["bounds"]


# ---------------------------------------------------------------------------
# Nhánh 3: desktop + 17 mã lý do
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "code,reason",
    [
        (UIA_NO_ELEMENT, UIA_NO_ELEMENT),
        (UIA_UNAVAILABLE, UIA_UNAVAILABLE_REASON),
        ("lạ_hoắc", UIA_UNAVAILABLE_REASON),
    ],
)
def test_uia_failure_reasons_map_to_desktop_branch(code, reason):
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")],
        uia_accessor=FakeUiaAccessor(errors=5, exception=PlatformError(code, "x")),
    )
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert result["type"] == "desktop"
    assert result["reason"] == reason
    assert result["message"] == INSPECT_MESSAGES[reason]


def test_uia_timeout_maps_to_uia_timeout_with_a_single_attempt():
    accessor = FakeUiaAccessor(errors=1, exception=PlatformError(UIA_TIMEOUT, "treo"))
    session = uia.UiaSession(accessor, attempts=1, backoff=0)
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")]
    )
    result = inspect_host.inspect_element(150, 160, platform=platform, session=session)
    assert result["reason"] == "uia_timeout"
    assert result["message"] == INSPECT_MESSAGES["uia_timeout"]


def test_repeated_uia_timeouts_become_provider_hang():
    accessor = FakeUiaAccessor(errors=9, exception=PlatformError(UIA_TIMEOUT, "treo"))
    session = uia.UiaSession(accessor, attempts=3, backoff=0)
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")]
    )
    result = inspect_host.inspect_element(150, 160, platform=platform, session=session)
    assert result["reason"] == "uia_provider_hang"
    assert result["message"] == INSPECT_MESSAGES["uia_provider_hang"]


def test_desktop_branch_keeps_identity_fields():
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", title="Ghi chú", process_name="notepad.exe")],
        uia_accessor=FakeUiaAccessor(empty=True),
    )
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert result["type"] == "desktop"
    assert result["reason"] == UIA_NO_ELEMENT
    assert result["appName"] == "Notepad"
    assert result["windowClass"] == "Notepad"
    assert result["windowTitle"] == "Ghi chú"
    assert result["windowId"] == "100"
    assert result["position"] == {"x": 0, "y": 0}
    assert result["size"] == {"width": 800, "height": 600}
    assert result["pid"] == 1000


def test_not_chromium_reason_drops_reason_and_message():
    payload = inspect_host._desktop_response(make_window(100, class_name="Notepad", process_name="notepad.exe"), "not_chromium")
    assert "reason" not in payload
    assert "message" not in payload
    assert payload["type"] == "desktop"


def test_app_name_and_pid_are_dropped_when_absent():
    window = make_window(100, class_name="", pid=None)
    payload = inspect_host._desktop_response(window, UIA_NO_ELEMENT)
    assert "appName" not in payload
    assert "pid" not in payload
    assert payload["windowClass"] == ""


def test_no_window_at_point():
    platform = FakePlatform(windows=[make_window(100)])
    platform.window_from_point = lambda x, y: None
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert result["type"] == "desktop"
    assert result["reason"] == NO_WINDOW_AT_POINT
    assert result["windowId"] == ""
    assert result["position"] == {"x": 150, "y": 160}
    assert result["sourceId"] == "screen"
    assert result["label"]["source_uri"] == "screen://element/"


def test_window_identity_unavailable():
    platform = FakePlatform(windows=[make_window(100)])

    def boom(hwnd, **kwargs):
        raise PlatformError("CAPTURE_FAILED", "không đọc được")

    platform.describe_window = boom
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert result["type"] == "desktop"
    assert result["reason"] == WINDOW_IDENTITY_UNAVAILABLE_REASON


def test_reason_vocabulary_has_17_codes_and_16_messages():
    assert len(INSPECT_REASONS) == 17
    assert len(set(INSPECT_REASONS)) == 17
    assert "not_chromium" in INSPECT_REASONS
    assert set(INSPECT_MESSAGES) == set(INSPECT_REASONS) - {"not_chromium"}
    assert len(INSPECT_MESSAGES) == 16


def test_every_emitted_reason_produces_a_message():
    platform = FakePlatform(
        windows=[make_window(100)],
        uia_accessor=FakeUiaAccessor(errors=10 ** 6, exception=RuntimeError("x")),
    )
    for reason in (OUTSIDE_VIEWPORT, VIEWPORT_ORIGIN_UNKNOWN, AMBIGUOUS_TARGET, EXTRACT_FAILED):
        result = inspect_host.inspect_element(
            150, 160, platform=platform, cdp=_inspector(error=inspect_host.CdpError(reason))
        )
        assert result["reason"] == reason
        assert result["message"] == INSPECT_MESSAGES[reason]


# ---------------------------------------------------------------------------
# Neo phiên bản + label
# ---------------------------------------------------------------------------
def test_identity_anchors_present_on_every_branch():
    dom = inspect_host.inspect_element(150, 160, platform=_chromium_platform(), cdp=_inspector())
    assert dom["sourceId"] == "win:100:1000"
    assert dom["frameId"] == "FRAME-1"
    assert dom["geometryRevision"] == 1

    uia_result = inspect_host.inspect_element(
        150, 160,
        platform=FakePlatform(windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")], uia_accessor=FakeUiaAccessor()),
    )
    assert uia_result["sourceId"] == "win:100:1000"
    assert uia_result["frameId"] == "win:100:1000"
    assert uia_result["geometryRevision"] == 1


def test_geometry_revision_increases_when_window_moves():
    platform = _chromium_platform()
    first = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    second = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    assert first["geometryRevision"] == second["geometryRevision"] == 1

    moved = make_window(100, rect=(50, 50, 850, 650), extended_bounds=(50, 50, 850, 650))
    platform.windows[100] = moved
    third = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    assert third["geometryRevision"] == 2


def test_label_content_hash_covers_payload_without_label():
    platform = _chromium_platform()
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    label = result.pop("label")
    assert label == {
        "integrity": "khong_tin_duoc",
        "confidentiality": "noi_bo",
        "source_kind": "screen_capture",
        "source_uri": "screen://element/100",
        "tool_name": "inspect_element",
        "content_hash": inspect_host._canonical_payload_hash(result),
    }
    # source_uri không bao giờ nhúng selector.
    assert "#submit" not in label["source_uri"]


def test_content_hash_changes_when_payload_changes():
    platform = _chromium_platform()
    first = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    other = dict(CHILD, text="Khác")
    second = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector(other))
    assert first["label"]["content_hash"] != second["label"]["content_hash"]


def test_uia_result_has_no_label_in_hash_input():
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")], uia_accessor=FakeUiaAccessor()
    )
    result = inspect_host.inspect_element(150, 160, platform=platform)
    label = result.pop("label")
    assert label["content_hash"] == inspect_host._canonical_payload_hash(result)
    assert "elementToken" in result


# ---------------------------------------------------------------------------
# Đầu vào + tiện ích
# ---------------------------------------------------------------------------
def test_validate_point_rejects_non_integers_and_out_of_screen():
    platform = FakePlatform()
    for bad in ((1.5, 2), (True, 2), ("1", 2)):
        with pytest.raises(ValueError):
            inspect_host.inspect_element(bad[0], bad[1], platform=platform)
    with pytest.raises(ValueError):
        inspect_host.inspect_element(5000, 10, platform=platform)


def test_validate_point_accepts_negative_virtual_origin():
    window = make_window(100, rect=(-1920, 0, -1120, 600), extended_bounds=(-1920, 0, -1120, 600))
    platform = FakePlatform(virtual_screen=(-1920, 0, 3840, 1080), windows=[window])
    result = inspect_host.inspect_element(-1500, 50, platform=platform, cdp=_inspector())
    assert result["type"] == "dom"
    assert result["target"]["windowId"] == "100"
    # Toạ độ âm vẫn đi qua nguyên vẹn (desktop ảo nhiều màn hình).
    assert result["screenBox"] == {"x": 110, "y": 140, "width": 100, "height": 30}


def test_prepare_reports_dpi_and_uia_state():
    platform = FakePlatform(uia_accessor=FakeUiaAccessor())
    state = inspect_host.prepare(platform)
    assert state["dpiAwareness"] == "per_monitor_v2"
    assert state["uiaApartment"] == "mta"

    capture.reset_dpi_awareness()
    broken = FakePlatform(dpi_v2=False, dpi_shcore=False)
    broken.uia_accessor = lambda: (_ for _ in ()).throw(PlatformError(UIA_UNAVAILABLE, "không có"))
    state = inspect_host.prepare(broken)
    assert state["dpiAwareness"] == "unavailable"
    assert state["uiaApartment"] == "unavailable"
    assert state["uiaCode"] == UIA_UNAVAILABLE


def test_pick_reason_prefers_specific_codes():
    assert inspect_host._pick_reason(NO_CDP_TARGET, UIA_NO_ELEMENT) == NO_CDP_TARGET
    assert inspect_host._pick_reason("not_chromium", UIA_NO_ELEMENT) == UIA_NO_ELEMENT
    assert inspect_host._pick_reason("not_chromium", None) == "not_chromium"
    assert inspect_host._pick_reason(None, None) == EXTRACT_FAILED


def test_is_chromium_detects_class_and_process():
    assert inspect_host._is_chromium(make_window(1, class_name="Chrome_WidgetWin_1")) is True
    assert inspect_host._is_chromium(make_window(1, class_name="", process_name="brave.exe")) is True
    assert inspect_host._is_chromium(make_window(1, class_name="Notepad", process_name="notepad.exe")) is False


def test_window_from_point_requires_higher_integrity_targets_to_be_untouched():
    # Chốt UIPI thuộc tầng input, nhưng nhánh soi không được tự nâng quyền:
    # một cửa sổ elevated vẫn soi được (chỉ đọc), và điều đó không đổi quyền của ta.
    platform = FakePlatform(
        windows=[make_window(100, class_name="Notepad", process_name="notepad.exe")],
        integrity_by_pid={1000: SECURITY_MANDATORY_HIGH_RID},
        uia_accessor=FakeUiaAccessor(),
    )
    result = inspect_host.inspect_element(150, 160, platform=platform)
    assert result["type"] == "uia"


def test_capture_module_geometry_tracker_is_shared():
    platform = _chromium_platform()
    result = inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
    assert capture.current_geometry_revision(result["sourceId"]) == result["geometryRevision"]


# ---------------------------------------------------------------------------
# Cắt gọt dữ liệu + allow-list
# ---------------------------------------------------------------------------
def test_truncate_text_counts_bytes_not_characters():
    text, truncated = inspect_host._truncate_text("á" * 2000, 100)
    assert truncated is True
    assert len(text.encode("utf-8")) <= 100
    assert text == "á" * 50  # 'á' là 2 byte UTF-8 ⇒ 50 ký tự


def test_truncate_text_keeps_short_values():
    assert inspect_host._truncate_text("Gửi", 100) == ("Gửi", False)
    assert inspect_host._truncate_text(None, 100) == ("", False)


def test_truncate_attributes_caps_count_and_value_size():
    attributes = {f"a{index}": "x" for index in range(40)}
    attributes["a0"] = "y" * 900
    result, truncated = inspect_host._truncate_attributes(attributes)
    assert truncated is True
    assert len(result) == inspect_host.MAX_ATTRS
    assert len(result["a0"].encode("utf-8")) <= inspect_host.MAX_ATTR_VALUE_BYTES
    assert inspect_host._truncate_attributes("không phải dict") == ({}, False)


def test_safe_tab_list_keeps_three_keys_and_truncates():
    raw = [
        {"targetId": "T" * 100, "title": "x" * 300, "url": "y" * 500, "secret": "ws://..."},
    ] * 20
    tabs = inspect_host._safe_tab_list(raw)
    assert len(tabs) == inspect_host.MAX_TABS_IN_PAYLOAD
    assert set(tabs[0]) == {"targetId", "title", "url"}
    assert len(tabs[0]["targetId"]) == 64
    assert len(tabs[0]["title"]) == 120
    assert len(tabs[0]["url"]) == 300
    assert inspect_host._safe_tab_list("không phải list") == []
    assert inspect_host._safe_tab_list([1, 2]) == []


def test_app_name_strips_namespace_prefix():
    assert inspect_host._app_name("ApplicationFrameWindow") == "ApplicationFrameWindow"
    assert inspect_host._app_name("Chrome_WidgetWin_1") == "Chrome_WidgetWin_1"
    assert inspect_host._app_name("Windows.UI.Core.CoreWindow") == "CoreWindow"
    assert inspect_host._app_name("") == ""


# ---------------------------------------------------------------------------
# Chọn tab + chốt DevTools docked
# ---------------------------------------------------------------------------
def test_page_candidates_splits_pages_and_devtools():
    targets = [
        {"type": "page", "id": "P1", "url": "https://a.test", "webSocketDebuggerUrl": "ws://p1"},
        {"type": "page", "id": "D1", "url": "devtools://devtools/bundled/inspector.html"},
        {"type": "browser", "id": "B1", "url": ""},
        {"type": "page", "id": "P2", "url": "https://b.test"},  # thiếu ws ⇒ bỏ
    ]
    pages, devtools_ids = inspect_host._page_candidates(targets)
    assert [page["id"] for page in pages] == ["P1"]
    assert devtools_ids == ["D1"]


def test_select_target_uses_single_candidate_then_title_match():
    single = {"id": "P1", "title": "Bất kỳ"}
    assert inspect_host._select_target([single], "khác") is single

    candidates = [{"id": "P1", "title": "Tab A"}, {"id": "P2", "title": "Tab B"}]
    assert inspect_host._select_target(candidates, "Tab B")["id"] == "P2"

    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host._select_target(candidates, "Không khớp")
    assert error.value.reason == AMBIGUOUS_TARGET
    assert len(error.value.details["candidates"]) == 2

    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host._select_target([], "x")
    assert error.value.reason == NO_CDP_TARGET


def test_select_target_partial_match_must_be_unique():
    candidates = [{"id": "P1", "title": "Trang A"}, {"id": "P2", "title": "Trang B"}]
    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host._select_target(candidates, "Trang")
    assert error.value.reason == AMBIGUOUS_TARGET


def test_ambiguous_candidate_list_is_capped():
    candidates = [{"id": f"P{index}", "title": f"T{index}"} for index in range(30)]
    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host._select_target(candidates, "không khớp")
    assert len(error.value.details["candidates"]) == inspect_host.MAX_AMBIGUOUS_CANDIDATES


class _FakeWs:
    def __init__(self, responses: dict, error: Exception | None = None) -> None:
        self.responses = responses
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    def call(self, method: str, params: dict | None = None) -> dict:
        self.calls.append((method, params or {}))
        if self.error is not None:
            raise self.error
        return {"result": {"windowId": self.responses[params["targetId"]]}}


def test_devtools_docked_returns_false_without_devtools_targets():
    assert inspect_host._devtools_docked(None, "P1", []) is False


def test_devtools_docked_fails_closed_without_browser_ws():
    assert inspect_host._devtools_docked(None, "P1", ["D1"]) is True


def test_devtools_docked_detects_shared_window_and_separate_window():
    shared = _FakeWs({"P1": 10, "D1": 10})
    assert inspect_host._devtools_docked(shared, "P1", ["D1"]) is True

    separate = _FakeWs({"P1": 10, "D1": 11})
    assert inspect_host._devtools_docked(separate, "P1", ["D1"]) is False


def test_devtools_docked_fails_closed_on_read_error():
    broken = _FakeWs({}, error=inspect_host.WebSocketError("đứt"))
    assert inspect_host._devtools_docked(broken, "P1", ["D1"]) is True


# ---------------------------------------------------------------------------
# Toán khung nhìn + chốt gốc viewport
# ---------------------------------------------------------------------------
WINDOW_GEOM = {"x": 100, "y": 120, "w": 800, "h": 600}


def test_content_origin_prefers_screen_coordinates_times_dpr():
    metrics = {"screenX": 100, "screenY": 120, "dpr": 2.0, "innerWidth": 400, "innerHeight": 300}
    assert inspect_host.content_origin(WINDOW_GEOM, metrics) == (200.0, 240.0)


def test_content_origin_falls_back_to_bottom_aligned_assumption():
    metrics = {"dpr": 1.0, "innerWidth": 800, "innerHeight": 550}
    # Không có screenX/screenY ⇒ sát đáy, căn giữa ngang.
    assert inspect_host.content_origin(WINDOW_GEOM, metrics) == (100.0, 170.0)


def test_screen_to_css_and_point_in_viewport():
    metrics = {"screenX": 100, "screenY": 120, "dpr": 2.0, "innerWidth": 400, "innerHeight": 300}
    assert inspect_host.screen_to_css(300, 340, WINDOW_GEOM, metrics) == (50.0, 50.0)
    assert inspect_host.point_in_viewport(0, 0, metrics) is True
    assert inspect_host.point_in_viewport(399.9, 299.9, metrics) is True
    assert inspect_host.point_in_viewport(400, 10, metrics) is False
    assert inspect_host.point_in_viewport(10, -1, metrics) is False


def test_quad_and_css_box_conversion():
    quad = [10.0, 20.0, 110.0, 20.0, 10.0, 50.0, 110.0, 50.0]
    assert inspect_host.quad_to_css_box(quad) == {"x": 10.0, "y": 20.0, "width": 100.0, "height": 30.0}
    box = inspect_host.css_box_to_screen_box({"x": 10, "y": 20, "width": 100, "height": 30}, 200, 240, 2.0)
    assert box == {"x": 220, "y": 280, "width": 200, "height": 60}


@pytest.mark.parametrize(
    "metrics,plausible",
    [
        ({"dpr": 1.0, "innerWidth": 800, "innerHeight": 600}, True),   # khít
        ({"dpr": 1.0, "innerWidth": 776, "innerHeight": 400}, True),   # slackX=24, slackY=200
        ({"dpr": 1.0, "innerWidth": 775, "innerHeight": 400}, False),  # slackX=25
        ({"dpr": 1.0, "innerWidth": 776, "innerHeight": 399}, False),  # slackY=201
        ({"dpr": 1.0, "innerWidth": 900, "innerHeight": 600}, False),  # viewport rộng hơn cửa sổ
    ],
)
def test_viewport_origin_plausibility_thresholds(metrics, plausible):
    assert inspect_host._viewport_origin_plausible(WINDOW_GEOM, metrics) is plausible


def test_viewport_metrics_refuses_junk():
    class _JunkWs:
        def call(self, method, params=None):
            return {"result": {"result": {"value": {"innerWidth": 0}}}}

    with pytest.raises(inspect_host.CdpError) as error:
        inspect_host.viewport_metrics(_JunkWs())
    assert error.value.reason == VIEWPORT_ORIGIN_UNKNOWN


# ---------------------------------------------------------------------------
# WebSocket: mặt nạ + khung
# ---------------------------------------------------------------------------
def test_apply_mask_is_symmetric():
    data = "nội dung giả".encode("utf-8")
    mask = b"\x01\x02\x03\x04"
    masked = inspect_host._apply_mask(data, mask)
    assert masked != data
    assert inspect_host._apply_mask(masked, mask) == data
    assert inspect_host._apply_mask(data, b"") == data


@pytest.mark.parametrize("length", [0, 5, 125, 126, 70000])
def test_make_frame_lengths_round_trip(length):
    payload = b"x" * length
    frame = inspect_host._make_frame(0x1, payload, masked=False)
    assert frame[0] == 0x81
    header = 2 if length < 126 else (4 if length < 65536 else 10)
    assert len(frame) == header + length
    assert frame[header:] == payload


def test_make_frame_masks_payload():
    frame = inspect_host._make_frame(0x1, b"abcd", masked=True)
    assert frame[1] & 0x80  # bit mask
    assert frame[6:] != b"abcd"
    assert inspect_host._apply_mask(frame[6:], frame[2:6]) == b"abcd"


# ---------------------------------------------------------------------------
# Khoá tương tranh + gộp payload
# ---------------------------------------------------------------------------
def test_control_busy_when_two_inspects_already_running():
    platform = FakePlatform(windows=[make_window(100)])
    assert inspect_host._INSPECT_SEMAPHORE.acquire(blocking=False) is True
    assert inspect_host._INSPECT_SEMAPHORE.acquire(blocking=False) is True
    try:
        with pytest.raises(PlatformError) as error:
            inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())
        assert error.value.code == CONTROL_BUSY
        assert error.value.details["limit"] == inspect_host.MAX_CONCURRENT_INSPECTS
    finally:
        inspect_host._INSPECT_SEMAPHORE.release()
        inspect_host._INSPECT_SEMAPHORE.release()
    # Nhả xong thì soi lại được.
    assert inspect_host.inspect_element(150, 160, platform=platform, cdp=_inspector())["type"] == "dom"


def test_finalize_attaches_label_after_hashing():
    payload = {"type": "desktop", "windowId": "100"}
    result = inspect_host._finalize(dict(payload), "100")
    label = result["label"]
    assert label["content_hash"] == inspect_host._canonical_payload_hash(payload)
    assert label["source_uri"] == "screen://element/100"
    assert result["windowId"] == "100"
