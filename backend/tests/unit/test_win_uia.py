"""Test tầng UI Automation + sổ đăng ký phần tử (H5, §4.3 bậc 1 và §4.5)."""
from __future__ import annotations

import pytest
from win_fakes import FakeUiaAccessor, reset_win_state, uia_node

from agentbox.sandbox.win import uia
from agentbox.sandbox.win.errors import (
    ELEMENT_STALE,
    UIA_NO_ELEMENT,
    UIA_PROVIDER_HANG,
    UIA_TIMEOUT,
    UIA_UNAVAILABLE,
    PlatformError,
)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    yield
    reset_win_state()


# ---------------------------------------------------------------------------
# Module import được trên Linux
# ---------------------------------------------------------------------------
def test_module_imports_without_comtypes():
    assert "comtypes" not in str(uia.ComUiaAccessor.__module__)
    # Không có comtypes trên Linux ⇒ lỗi có cấu trúc, không phải ImportError.
    with pytest.raises(PlatformError) as error:
        uia.ComUiaAccessor().initialize()
    assert error.value.code == UIA_UNAVAILABLE


def test_control_type_names_and_fingerprint():
    assert uia.control_type_name(50000) == "Button"
    assert uia.control_type_name(99999) == "ControlType_99999"
    assert uia.element_fingerprint("Button", "OK") == uia.element_fingerprint("Button", "OK")
    assert uia.element_fingerprint("Button", "OK") != uia.element_fingerprint("Button", "Cancel")
    assert len(uia.element_fingerprint("Button", "OK")) == 16


# ---------------------------------------------------------------------------
# Sổ đăng ký phần tử (§4.5)
# ---------------------------------------------------------------------------
def test_token_format_and_resolve():
    registry = uia.ElementRegistry()
    snapshot_id = registry.begin_snapshot()
    entry = registry.add(uia_node())
    registry.end_snapshot()
    token = registry.mint_token(entry)
    assert token == f"s{snapshot_id:08x}:0"
    assert uia.TOKEN_PATTERN.match(token)
    assert registry.resolve(token).runtime_id == "42.1"


def test_token_from_older_snapshot_is_refused():
    registry = uia.ElementRegistry()
    registry.begin_snapshot()
    entry = registry.add(uia_node())
    registry.end_snapshot()
    stale = registry.mint_token(entry)

    registry.begin_snapshot()  # snapshot mới: token cũ hết hiệu lực
    registry.add(uia_node(runtime_id="42.9", name="Other"))
    registry.end_snapshot()
    with pytest.raises(PlatformError) as error:
        registry.resolve(stale)
    assert error.value.code == ELEMENT_STALE
    assert error.value.details["token_snapshot"] == 1
    assert error.value.details["current_snapshot"] == 2


def test_malformed_token_is_refused():
    registry = uia.ElementRegistry()
    registry.begin_snapshot()
    with pytest.raises(PlatformError) as error:
        registry.resolve("element-1")
    assert error.value.code == ELEMENT_STALE


def test_reference_expires_only_after_two_consecutive_absences():
    registry = uia.ElementRegistry()
    registry.begin_snapshot()
    registry.add(uia_node())
    registry.end_snapshot()
    assert len(registry) == 1

    registry.begin_snapshot()  # vắng lần 1
    registry.end_snapshot()
    assert len(registry) == 1

    registry.begin_snapshot()  # vắng lần 2 liên tiếp ⇒ hết hiệu lực
    registry.end_snapshot()
    assert len(registry) == 0
    assert registry.expired == 1


def test_reference_survives_absence_when_seen_again_in_between():
    registry = uia.ElementRegistry()
    for present in (True, False, True, False, False):
        registry.begin_snapshot()
        if present:
            registry.add(uia_node())
        registry.end_snapshot()
    assert len(registry) == 0  # (vắng, có, vắng, vắng) ⇒ hết ở snapshot cuối
    registry.begin_snapshot()
    registry.add(uia_node())
    registry.end_snapshot()
    assert len(registry) == 1


def test_generation_increases_only_when_fingerprint_changes():
    registry = uia.ElementRegistry()
    registry.begin_snapshot()
    first = registry.add(uia_node())
    registry.end_snapshot()
    assert first.generation == 1

    registry.begin_snapshot()
    again = registry.add(uia_node())
    registry.end_snapshot()
    assert again.generation == 1  # cùng runtime_id + cùng fingerprint

    registry.begin_snapshot()
    renamed = registry.add(uia_node(name="Đổi tên"))
    registry.end_snapshot()
    assert renamed.generation == 2
    assert renamed.fingerprint != first.fingerprint


def test_registry_capacity_is_bounded():
    registry = uia.ElementRegistry(capacity=3)
    registry.begin_snapshot()
    for index in range(6):
        registry.add(uia_node(runtime_id=f"42.{index}"))
    registry.end_snapshot()
    assert len(registry) == 3
    assert registry.evictions == 3
    assert registry.stats()["capacity"] == 3


# ---------------------------------------------------------------------------
# Watchdog + thử lại
# ---------------------------------------------------------------------------
def test_timeout_maps_to_uia_timeout_with_single_attempt():
    accessor = FakeUiaAccessor(delay=0.2)
    session = uia.UiaSession(accessor, timeout=0.02, attempts=1, backoff=0)
    with pytest.raises(PlatformError) as error:
        session.snapshot(1, 1)
    assert error.value.code == UIA_TIMEOUT
    assert error.value.details["stage"] == "element_from_point"


def test_repeated_timeouts_map_to_provider_hang():
    accessor = FakeUiaAccessor(delay=0.2)
    session = uia.UiaSession(accessor, timeout=0.02, attempts=3, backoff=0)
    with pytest.raises(PlatformError) as error:
        session.snapshot(1, 1)
    assert error.value.code == UIA_PROVIDER_HANG
    assert error.value.details["consecutive_timeouts"] >= 2


def test_transient_errors_are_retried_up_to_three_times():
    accessor = FakeUiaAccessor(errors=2)
    session = uia.UiaSession(accessor, timeout=1.0, attempts=3, backoff=0)
    nodes = session.snapshot(1, 1)
    assert len(nodes) == 1
    attempts = [call for call in accessor.calls if call[0] == "element_from_point"]
    assert len(attempts) == 3


def test_persistent_errors_become_uia_unavailable():
    accessor = FakeUiaAccessor(errors=5)
    session = uia.UiaSession(accessor, timeout=1.0, attempts=3, backoff=0)
    with pytest.raises(PlatformError) as error:
        session.snapshot(1, 1)
    assert error.value.code == UIA_UNAVAILABLE
    assert error.value.details["stage"] == "element_from_point"


def test_platform_error_from_accessor_is_not_retried():
    accessor = FakeUiaAccessor(errors=1, exception=PlatformError(UIA_UNAVAILABLE, "không có UIA"))
    session = uia.UiaSession(accessor, timeout=1.0, attempts=3, backoff=0)
    with pytest.raises(PlatformError) as error:
        session.snapshot(1, 1)
    assert error.value.code == UIA_UNAVAILABLE
    assert len([call for call in accessor.calls if call[0] == "element_from_point"]) == 1


# ---------------------------------------------------------------------------
# Snapshot + điểm vào
# ---------------------------------------------------------------------------
def test_snapshot_mints_tokens_in_order_and_node_payload():
    accessor = FakeUiaAccessor(
        nodes=[uia_node(runtime_id="1", name="A"), uia_node(runtime_id="2", name="B")]
    )
    session = uia.UiaSession(accessor)
    nodes = session.snapshot(5, 6)
    assert [node.token for node in nodes] == ["s00000001:0", "s00000001:1"]
    assert accessor.calls[0] == ("element_from_point", "5", "6")
    assert ("build_subtree",) in accessor.calls

    payload = uia.node_payload(nodes[0])
    assert payload["name"] == "A"
    assert payload["controlType"] == "Button"
    assert payload["patterns"] == ["Invoke"]
    assert payload["bounds"] == {"x": 10, "y": 20, "width": 100, "height": 40}
    assert "handle" not in payload


def test_snapshot_without_element_returns_empty():
    accessor = FakeUiaAccessor(empty=True)
    session = uia.UiaSession(accessor)
    assert session.snapshot(1, 1) == []
    assert session.registry.snapshot_id == 1


def test_element_at_point_raises_uia_no_element_when_pid_differs():
    accessor = FakeUiaAccessor(nodes=[uia_node(pid=2000)])
    session = uia.UiaSession(accessor)
    with pytest.raises(PlatformError) as error:
        session.element_at_point(1, 1, pid=1000)
    assert error.value.code == UIA_NO_ELEMENT


def test_element_at_point_returns_topmost_node():
    accessor = FakeUiaAccessor(nodes=[uia_node(runtime_id="1", name="Top"), uia_node(runtime_id="2")])
    session = uia.UiaSession(accessor)
    node = session.element_at_point(1, 1, pid=1000)
    assert node.label == "Top"


def test_invoke_uses_requested_pattern_and_refuses_missing_one():
    accessor = FakeUiaAccessor(nodes=[uia_node(patterns=["Invoke", "Toggle"])])
    session = uia.UiaSession(accessor)
    token = session.snapshot(1, 1)[0].token
    assert session.invoke(token)["pattern"] == "Invoke"
    assert session.invoke(token, "Toggle")["pattern"] == "Toggle"
    with pytest.raises(PlatformError) as error:
        session.invoke(token, "Value")
    assert error.value.code == UIA_UNAVAILABLE


def test_module_level_session_injection():
    accessor = FakeUiaAccessor()
    uia.set_accessor(accessor)
    session = uia.get_session()
    assert session.accessor is accessor
    node = uia.element_at_point(3, 4)
    assert node.label == "OK"
    assert uia.resolve(node.token).runtime_id == "42.1"
    assert uia.invoke(node.token)["pattern"] == "Invoke"
    assert uia.focus(node.token)["elementToken"] == node.token
    assert session.stats()["accessor"] == "fake-uia"


def test_session_uses_platform_accessor_when_no_override():
    from win_fakes import FakePlatform

    accessor = FakeUiaAccessor()
    platform = FakePlatform(uia_accessor=accessor)
    session = uia.get_session(platform)
    assert session.accessor is accessor
