"""UI Automation qua comtypes (H5, kế hoạch §4.3 bậc 1 và §4.5).

Module này **import được trên Linux**: ``comtypes`` chỉ được nạp bên trong
:meth:`ComUiaAccessor.initialize`. Test trên Linux tiêm một accessor giả bằng
:func:`set_accessor` (hoặc để nền tảng giả cung cấp ``uia_accessor()``).

Ba cơ chế được cài đặt ở đây:

* **Watchdog mỗi lời gọi.** Lời gọi UIA chạy trong một thread riêng có hạn giờ;
  quá hạn thì thread bị bỏ rơi (daemon) và lời gọi kế tiếp trả về
  ``uia_provider_hang`` thay vì treo cả tiến trình. Thử lại ≤3 lần, cách nhau
  ~40 ms.
* **Hai bước BuildUpdatedCache.** ``ElementFromPoint`` rồi
  ``BuildUpdatedCache`` + ``FindAll(TreeScope_Subtree)`` — dạng hai lời gọi có
  chủ đích: dạng gộp ``ElementFromHandleBuildCache`` bị treo với một số nhà cung
  cấp (SAL).
* **Sổ đăng ký phần tử có giới hạn** (kế hoạch §4.5): khoá theo ``RuntimeId`` +
  ``generation``, ``fingerprint = hash(role, label)``, tối đa 5000 mục, và một
  tham chiếu chỉ hết hiệu lực khi **vắng mặt trong HAI snapshot liên tiếp**.
  Token có dạng ``s{snapshot_id:08x}:{index}``; token của snapshot cũ bị từ chối
  bằng ``ELEMENT_STALE`` và **không bao giờ được giải lại**.
"""
from __future__ import annotations

import hashlib
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import (
    ELEMENT_STALE,
    UIA_NO_ELEMENT,
    UIA_PROVIDER_HANG,
    UIA_TIMEOUT,
    UIA_UNAVAILABLE,
    PlatformError,
)
from .windows_platform import (
    COINIT_MULTITHREADED,
    RPC_E_CHANGED_MODE,
    S_OK,
    WindowsPlatform,
    get_platform,
)

#: Trần số mục trong sổ đăng ký phần tử (kế hoạch §4.5).
REGISTRY_CAPACITY = 5000
#: Số snapshot liên tiếp vắng mặt thì một tham chiếu hết hiệu lực.
EXPIRY_SNAPSHOTS = 2
#: Trần số phần tử đọc được trong một lần đi cây (chống cây khổng lồ).
MAX_SUBTREE_NODES = 2000
#: Hạn giờ mặc định cho một lời gọi UIA.
DEFAULT_TIMEOUT_SEC = 0.75
#: Số lần thử lại tối đa cho một lời gọi.
DEFAULT_ATTEMPTS = 3
#: Khoảng nghỉ giữa hai lần thử.
DEFAULT_BACKOFF_SEC = 0.04

TOKEN_PATTERN = re.compile(r"^s([0-9a-f]{8}):(\d+)$")

# --- hằng số UIA -----------------------------------------------------------
TreeScope_Subtree = 0x7
UIA_RuntimeIdPropertyId = 30000
UIA_BoundingRectanglePropertyId = 30001
UIA_ProcessIdPropertyId = 30002
UIA_ControlTypePropertyId = 30003
UIA_NamePropertyId = 30005
UIA_IsEnabledPropertyId = 30010
UIA_AutomationIdPropertyId = 30011
UIA_ClassNamePropertyId = 30012
UIA_HelpTextPropertyId = 30013
UIA_IsPasswordPropertyId = 30019
UIA_NativeWindowHandlePropertyId = 30020
UIA_IsOffscreenPropertyId = 30022
UIA_IsInvokePatternAvailablePropertyId = 30031
UIA_IsTogglePatternAvailablePropertyId = 30035
UIA_IsSelectionItemPatternAvailablePropertyId = 30038
UIA_IsValuePatternAvailablePropertyId = 30044
UIA_IsScrollItemPatternAvailablePropertyId = 30037
UIA_IsExpandCollapsePatternAvailablePropertyId = 30029
UIA_IsTextPatternAvailablePropertyId = 30040

UIA_InvokePatternId = 10000
UIA_TogglePatternId = 10015
UIA_SelectionItemPatternId = 10010
UIA_ValuePatternId = 10002
UIA_FocusPatternId = 10017

#: Thuộc tính đưa vào cache request — đọc một lần, không gọi liên tiến trình.
CACHED_PROPERTY_IDS: tuple[int, ...] = (
    UIA_RuntimeIdPropertyId,
    UIA_BoundingRectanglePropertyId,
    UIA_ProcessIdPropertyId,
    UIA_ControlTypePropertyId,
    UIA_NamePropertyId,
    UIA_IsEnabledPropertyId,
    UIA_AutomationIdPropertyId,
    UIA_ClassNamePropertyId,
    UIA_HelpTextPropertyId,
    UIA_IsPasswordPropertyId,
    UIA_NativeWindowHandlePropertyId,
    UIA_IsOffscreenPropertyId,
    UIA_IsInvokePatternAvailablePropertyId,
    UIA_IsTogglePatternAvailablePropertyId,
    UIA_IsSelectionItemPatternAvailablePropertyId,
    UIA_IsValuePatternAvailablePropertyId,
    UIA_IsScrollItemPatternAvailablePropertyId,
    UIA_IsExpandCollapsePatternAvailablePropertyId,
)

#: ``IsXxxPatternAvailable`` → tên pattern.
PATTERN_FLAGS: tuple[tuple[int, str], ...] = (
    (UIA_IsInvokePatternAvailablePropertyId, "Invoke"),
    (UIA_IsTogglePatternAvailablePropertyId, "Toggle"),
    (UIA_IsSelectionItemPatternAvailablePropertyId, "SelectionItem"),
    (UIA_IsValuePatternAvailablePropertyId, "Value"),
    (UIA_IsScrollItemPatternAvailablePropertyId, "ScrollItem"),
    (UIA_IsExpandCollapsePatternAvailablePropertyId, "ExpandCollapse"),
)

#: Mã control type → tên (UIA_*ControlTypeId). Thiếu thì trả ``ControlType_<id>``.
CONTROL_TYPE_NAMES: dict[int, str] = {
    50000: "Button",
    50001: "Calendar",
    50002: "CheckBox",
    50003: "ComboBox",
    50004: "Edit",
    50005: "Hyperlink",
    50006: "Image",
    50007: "ListItem",
    50008: "List",
    50009: "Menu",
    50010: "MenuBar",
    50011: "MenuItem",
    50012: "ProgressBar",
    50013: "RadioButton",
    50014: "ScrollBar",
    50015: "Slider",
    50016: "Spinner",
    50017: "StatusBar",
    50018: "Tab",
    50019: "TabItem",
    50020: "Text",
    50021: "ToolBar",
    50022: "ToolTip",
    50023: "Tree",
    50024: "TreeItem",
    50025: "Custom",
    50026: "Group",
    50027: "Thumb",
    50028: "DataGrid",
    50029: "DataItem",
    50030: "Document",
    50031: "SplitButton",
    50032: "Window",
    50033: "Pane",
    50034: "Header",
    50035: "HeaderItem",
    50036: "Table",
    50037: "TitleBar",
    50038: "Separator",
    50039: "SemanticZoom",
    50040: "AppBar",
}


def control_type_name(control_type: Any) -> str:
    try:
        value = int(control_type)
    except (TypeError, ValueError):
        return "Unknown"
    return CONTROL_TYPE_NAMES.get(value, f"ControlType_{value}")


def element_fingerprint(role: str, label: str) -> str:
    """``hash(role, label)`` — băm ổn định giữa các tiến trình (không dùng hash())."""
    digest = hashlib.sha256(f"{role}\x1f{label}".encode("utf-8", "replace")).hexdigest()
    return digest[:16]


# ---------------------------------------------------------------------------
# Sổ đăng ký phần tử
# ---------------------------------------------------------------------------
@dataclass
class ElementEntry:
    runtime_id: str
    fingerprint: str
    generation: int
    payload: dict[str, Any]
    bounds: dict[str, Any]
    patterns: list[str]
    role: str
    label: str
    pid: int | None = None
    handle: Any = None
    snapshot_id: int = 0
    index: int = -1
    misses: int = 0
    last_seen: int = 0
    seen_at: float = field(default_factory=time.time)


class ElementRegistry:
    """Sổ phần tử có giới hạn, hết hiệu lực sau hai snapshot vắng mặt."""

    def __init__(
        self,
        capacity: int = REGISTRY_CAPACITY,
        expiry_snapshots: int = EXPIRY_SNAPSHOTS,
    ) -> None:
        self.capacity = int(capacity)
        self.expiry_snapshots = int(expiry_snapshots)
        self.snapshot_id = 0
        self._entries: dict[str, ElementEntry] = {}
        self._current: list[ElementEntry] = []
        self._current_keys: set[str] = set()
        self.evictions = 0
        self.expired = 0

    # -- snapshot ----------------------------------------------------------
    def begin_snapshot(self) -> int:
        self.snapshot_id += 1
        self._current = []
        self._current_keys = set()
        return self.snapshot_id

    def add(self, node: dict[str, Any], *, snapshot_id: int | None = None) -> ElementEntry:
        """Thêm/khôi phục một mục; giữ nguyên ``generation`` nếu fingerprint không đổi."""
        snapshot = self.snapshot_id if snapshot_id is None else int(snapshot_id)
        runtime_id = str(node.get("runtime_id") or "")
        role = str(node.get("control_type_name") or control_type_name(node.get("control_type")))
        label = str(node.get("name") or "")
        fingerprint = element_fingerprint(role, label)
        entry = self._entries.get(runtime_id)
        if entry is None or entry.fingerprint != fingerprint:
            generation = 1 if entry is None else entry.generation + 1
            entry = ElementEntry(
                runtime_id=runtime_id,
                fingerprint=fingerprint,
                generation=generation,
                payload=dict(node.get("payload") or {}),
                bounds=dict(node.get("bounds") or {}),
                patterns=list(node.get("patterns") or []),
                role=role,
                label=label,
                pid=node.get("pid"),
                handle=node.get("handle"),
            )
            self._entries[runtime_id] = entry
        else:
            entry.payload = dict(node.get("payload") or {})
            entry.bounds = dict(node.get("bounds") or {})
            entry.patterns = list(node.get("patterns") or [])
            entry.pid = node.get("pid")
            entry.handle = node.get("handle")
        entry.snapshot_id = snapshot
        entry.index = len(self._current)
        entry.misses = 0
        entry.last_seen = snapshot
        entry.seen_at = time.time()
        self._current.append(entry)
        self._current_keys.add(runtime_id)
        self._enforce_capacity()
        return entry

    def end_snapshot(self) -> None:
        """Tăng số lần vắng mặt và loại các mục đã vắng đủ ngưỡng."""
        for key in list(self._entries):
            entry = self._entries[key]
            if key in self._current_keys:
                continue
            entry.misses += 1
            if entry.misses >= self.expiry_snapshots:
                del self._entries[key]
                self.expired += 1

    # -- token -------------------------------------------------------------
    def mint_token(self, entry: ElementEntry) -> str:
        return f"s{entry.snapshot_id:08x}:{entry.index}"

    def resolve(self, token: str) -> ElementEntry:
        """Token cũ ⇒ ``ELEMENT_STALE``; không bao giờ giải lại theo runtime id."""
        match = TOKEN_PATTERN.match(str(token or ""))
        if not match:
            raise PlatformError(ELEMENT_STALE, "Token phần tử không hợp lệ.", token=str(token))
        snapshot_id = int(match.group(1), 16)
        index = int(match.group(2))
        if snapshot_id != self.snapshot_id:
            raise PlatformError(
                ELEMENT_STALE,
                "Token thuộc snapshot cũ — hãy soi lại phần tử trước khi thao tác.",
                token=str(token),
                token_snapshot=snapshot_id,
                current_snapshot=self.snapshot_id,
            )
        for entry in self._current:
            if entry.index == index:
                return entry
        raise PlatformError(ELEMENT_STALE, "Token không còn trong snapshot hiện tại.", token=str(token))

    # -- nội bộ ------------------------------------------------------------
    def _enforce_capacity(self) -> None:
        overflow = len(self._entries) - self.capacity
        if overflow <= 0:
            return
        # Ưu tiên loại mục KHÔNG thuộc snapshot hiện tại, vắng mặt nhiều nhất, cũ
        # nhất. Nếu chính snapshot này vượt trần thì buộc phải loại cả mục mới
        # (token vẫn giải được trong snapshot nhờ `_current`, nhưng sổ bị chặn trần).
        candidates = sorted(
            self._entries.values(),
            key=lambda item: (item.runtime_id in self._current_keys, -item.misses, item.last_seen),
        )
        for entry in candidates[:overflow]:
            del self._entries[entry.runtime_id]
            self.evictions += 1

    def __len__(self) -> int:
        return len(self._entries)

    def stats(self) -> dict[str, Any]:
        return {
            "size": len(self._entries),
            "snapshotId": self.snapshot_id,
            "capacity": self.capacity,
            "evictions": self.evictions,
            "expired": self.expired,
        }


@dataclass
class UiaNode:
    """Một phần tử UIA đã đăng ký — thứ mà tầng trên nhìn thấy."""

    token: str
    runtime_id: str
    generation: int
    fingerprint: str
    role: str
    label: str
    payload: dict[str, Any]
    bounds: dict[str, Any]
    patterns: list[str]
    pid: int | None = None
    handle: Any = None


# ---------------------------------------------------------------------------
# Accessor: giao diện mà UiaSession cần (giả được trong test)
# ---------------------------------------------------------------------------
class UiaAccessor:
    """Giao diện tối thiểu cho UIA. Bản thật: :class:`ComUiaAccessor`."""

    name = "accessor"

    def initialize(self) -> str:
        raise NotImplementedError

    def element_from_point(self, x: int, y: int) -> Any:
        raise NotImplementedError

    def build_subtree(self, element: Any) -> list[dict[str, Any]]:
        raise NotImplementedError

    def invoke(self, handle: Any, pattern: str) -> bool:
        raise NotImplementedError

    def focus(self, handle: Any) -> bool:
        raise NotImplementedError

    def reset(self) -> None:
        """Bỏ trạng thái COM sau một lần treo (tuỳ chọn)."""


class ComUiaAccessor(UiaAccessor):
    """Bản thật qua comtypes — nạp lười, **chưa kiểm chứng trên Windows**."""

    name = "comtypes"

    def __init__(self, platform: WindowsPlatform | None = None) -> None:
        self._platform = platform
        self._uia: Any = None
        self._client: Any = None
        self._cache_request: Any = None
        self._condition: Any = None
        self._apartment: str | None = None
        self._module: Any = None

    # -- khởi tạo ----------------------------------------------------------
    def initialize(self) -> str:
        if self._uia is not None:
            return self._apartment or "mta"
        platform = self._platform or get_platform()
        try:
            import comtypes  # noqa: F401  (chỉ có trên Windows)
            import comtypes.client
        except Exception as exc:  # pragma: no cover - Linux/không có comtypes
            raise PlatformError(
                UIA_UNAVAILABLE,
                "Không nạp được comtypes — UI Automation không khả dụng.",
                error=repr(exc),
            ) from exc
        self._apartment = self._coinitialize(platform)
        try:
            self._module = comtypes.client.GetModule("UIAutomationCore.dll")
            uiautomation = comtypes.client.CreateObject(self._module.CUIAutomation)
            self._uia = uiautomation.QueryInterface(self._module.IUIAutomation)
            self._condition = self._uia.CreateTrueCondition()
            request = self._uia.CreateCacheRequest()
            for property_id in CACHED_PROPERTY_IDS:
                request.AddProperty(property_id)
            self._cache_request = request
        except PlatformError:
            raise
        except Exception as exc:  # pragma: no cover - chỉ chạy trên Windows
            raise PlatformError(
                UIA_UNAVAILABLE,
                "Không khởi tạo được UI Automation (COM).",
                error=repr(exc),
            ) from exc
        return self._apartment

    def _coinitialize(self, platform: WindowsPlatform) -> str:
        """MTA là bắt buộc: thread watchdog không được chia sẻ apartment STA."""
        try:
            result = platform.ole32.CoInitializeEx(None, COINIT_MULTITHREADED)
        except Exception:  # pragma: no cover - chỉ chạy trên Windows
            return "unknown"
        if result in (S_OK, 1):  # S_OK / S_FALSE (đã khởi tạo trước đó)
            return "mta"
        if result == RPC_E_CHANGED_MODE:
            return "sta"
        return f"hresult_{result}"

    # -- đọc ---------------------------------------------------------------
    def element_from_point(self, x: int, y: int) -> Any:
        self.initialize()
        return self._uia.ElementFromPoint(_point(x, y))

    def build_subtree(self, element: Any) -> list[dict[str, Any]]:
        """Hai bước có chủ đích: BuildUpdatedCache rồi FindAll(TreeScope_Subtree)."""
        self.initialize()
        cached = element.BuildUpdatedCache(self._cache_request)
        found = cached.FindAll(TreeScope_Subtree, self._condition)
        nodes: list[dict[str, Any]] = []
        for index in range(min(found.Length, MAX_SUBTREE_NODES)):
            nodes.append(self._normalize(found.GetElement(index)))
        return nodes

    def _normalize(self, element: Any) -> dict[str, Any]:
        cached = True
        control_type = _read_property(element, UIA_ControlTypePropertyId, cached)
        role = control_type_name(control_type)
        name = str(_read_property(element, UIA_NamePropertyId, cached) or "")
        bounds = _rect_from(_read_property(element, UIA_BoundingRectanglePropertyId, cached))
        patterns = [
            pattern
            for property_id, pattern in PATTERN_FLAGS
            if _truthy(_read_property(element, property_id, cached))
        ]
        pid = _read_property(element, UIA_ProcessIdPropertyId, cached)
        runtime_id = _runtime_id(_read_property(element, UIA_RuntimeIdPropertyId, cached))
        payload = {
            "name": name,
            "controlType": role,
            "controlTypeId": _int_or_none(control_type),
            "automationId": str(_read_property(element, UIA_AutomationIdPropertyId, cached) or ""),
            "className": str(_read_property(element, UIA_ClassNamePropertyId, cached) or ""),
            "helpText": str(_read_property(element, UIA_HelpTextPropertyId, cached) or ""),
            "isEnabled": bool(_truthy(_read_property(element, UIA_IsEnabledPropertyId, cached))),
            "isOffscreen": bool(_truthy(_read_property(element, UIA_IsOffscreenPropertyId, cached))),
            "isPassword": bool(_truthy(_read_property(element, UIA_IsPasswordPropertyId, cached))),
            "patterns": patterns,
        }
        return {
            "runtime_id": runtime_id,
            "name": name,
            "control_type": _int_or_none(control_type),
            "control_type_name": role,
            "bounds": bounds,
            "patterns": patterns,
            "pid": _int_or_none(pid),
            "payload": payload,
            "handle": element,
        }

    # -- hành động ---------------------------------------------------------
    def invoke(self, handle: Any, pattern: str) -> bool:
        self.initialize()
        pattern_id = {
            "Invoke": UIA_InvokePatternId,
            "Toggle": UIA_TogglePatternId,
            "SelectionItem": UIA_SelectionItemPatternId,
        }.get(pattern)
        if pattern_id is None:
            raise PlatformError(UIA_UNAVAILABLE, f"Pattern không hỗ trợ: {pattern}", pattern=pattern)
        interface = {
            "Invoke": "IUIAutomationInvokePattern",
            "Toggle": "IUIAutomationTogglePattern",
            "SelectionItem": "IUIAutomationSelectionItemPattern",
        }[pattern]
        method = {"Invoke": "Invoke", "Toggle": "Toggle", "SelectionItem": "Select"}[pattern]
        import ctypes

        pointer = handle.GetCurrentPattern(pattern_id)
        if not pointer:
            raise PlatformError(UIA_UNAVAILABLE, f"Phần tử không cung cấp pattern {pattern}.", pattern=pattern)
        typed = ctypes.cast(pointer, ctypes.POINTER(getattr(self._module, interface))).contents
        getattr(typed, method)()
        return True

    def focus(self, handle: Any) -> bool:
        self.initialize()
        handle.SetFocus()
        return True

    def reset(self) -> None:
        self._uia = None
        self._cache_request = None
        self._condition = None


def _point(x: int, y: int) -> Any:
    """``tagPOINT`` mà comtypes chấp nhận (khởi tạo lười để import được trên Linux)."""
    import ctypes

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    return POINT(int(x), int(y))


def _read_property(element: Any, property_id: int, cached: bool) -> Any:
    try:
        if cached:
            return element.GetCachedPropertyValue(property_id)
        return element.GetCurrentPropertyValue(property_id)
    except Exception:
        try:
            return element.GetCurrentPropertyValue(property_id)
        except Exception:
            return None


def _runtime_id(value: Any) -> str:
    if value is None:
        return ""
    try:
        return ".".join(str(int(part)) for part in value)
    except Exception:
        return str(value)


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return bool(value)


def _rect_from(value: Any) -> dict[str, Any]:
    """``BoundingRectangle`` là mảng double[4] (left, top, width, height)."""
    left = top = width = height = 0.0
    if value is None:
        return {"x": 0, "y": 0, "width": 0, "height": 0}
    try:
        left, top, width, height = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    except Exception:
        for attribute, target in (("left", "left"), ("top", "top"), ("right", "width"), ("bottom", "height")):
            if hasattr(value, attribute):
                setattr(value, target, getattr(value, attribute))
        left = float(getattr(value, "left", 0.0) or 0.0)
        top = float(getattr(value, "top", 0.0) or 0.0)
        width = float(getattr(value, "width", 0.0) or 0.0)
        height = float(getattr(value, "height", 0.0) or 0.0)
    return {
        "x": int(round(left)),
        "y": int(round(top)),
        "width": max(0, int(round(width))),
        "height": max(0, int(round(height))),
    }


# ---------------------------------------------------------------------------
# Phiên UIA
# ---------------------------------------------------------------------------
class UiaSession:
    """Bọc một accessor bằng watchdog, thử lại và sổ đăng ký phần tử."""

    def __init__(
        self,
        accessor: UiaAccessor | None = None,
        *,
        registry: ElementRegistry | None = None,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        attempts: int = DEFAULT_ATTEMPTS,
        backoff: float = DEFAULT_BACKOFF_SEC,
    ) -> None:
        self.accessor = accessor or ComUiaAccessor()
        self.registry = registry or ElementRegistry()
        self.timeout = float(timeout)
        self.attempts = max(1, int(attempts))
        self.backoff = max(0.0, float(backoff))
        self._consecutive_timeouts = 0
        self._apartment: str | None = None
        self._lock = threading.Lock()
        self._initialized = False

    # -- khởi tạo ----------------------------------------------------------
    def initialize(self) -> str:
        if self._initialized:
            return self._apartment or "unknown"
        apartment = self._call("initialize", lambda: self.accessor.initialize())
        self._apartment = str(apartment or "unknown")
        self._initialized = True
        return self._apartment

    # -- watchdog ----------------------------------------------------------
    def _run_with_timeout(self, what: str, fn: Callable[[], Any]) -> Any:
        box: dict[str, Any] = {}

        def target() -> None:
            try:
                box["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - chuyển nguyên lỗi sang thread chính
                box["error"] = exc

        thread = threading.Thread(target=target, name=f"uia-{what}", daemon=True)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            # Thread bị bỏ rơi: không thể huỷ một lời gọi COM đang treo.
            raise PlatformError(
                UIA_TIMEOUT,
                f"UI Automation không trả lời trong {self.timeout:.2f}s ({what}).",
                stage=what,
                timeout=self.timeout,
            )
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def _call(self, what: str, fn: Callable[[], Any]) -> Any:
        last_error: PlatformError | None = None
        for attempt in range(self.attempts):
            try:
                with self._lock:
                    value = self._run_with_timeout(what, fn)
                self._consecutive_timeouts = 0
                return value
            except PlatformError as exc:
                if exc.code != UIA_TIMEOUT:
                    raise
                self._consecutive_timeouts += 1
                last_error = exc
            except Exception as exc:
                if attempt + 1 >= self.attempts:
                    raise PlatformError(
                        UIA_UNAVAILABLE,
                        f"Lời gọi UI Automation thất bại ({what}): {exc}",
                        stage=what,
                        error=repr(exc),
                    ) from exc
                self._reset_accessor()
            if attempt + 1 < self.attempts and self.backoff:
                time.sleep(self.backoff)
        if self._consecutive_timeouts >= 2:
            raise PlatformError(
                UIA_PROVIDER_HANG,
                (
                    "Nhà cung cấp UI Automation của ứng dụng đích bị treo "
                    f"({self._consecutive_timeouts} lần quá hạn liên tiếp)."
                ),
                stage=what,
                consecutive_timeouts=self._consecutive_timeouts,
            )
        raise last_error or PlatformError(UIA_TIMEOUT, "UI Automation quá hạn.", stage=what)

    def _reset_accessor(self) -> None:
        reset = getattr(self.accessor, "reset", None)
        if callable(reset):
            try:
                reset()
            except Exception:
                pass

    # -- snapshot ----------------------------------------------------------
    def snapshot(self, x: int, y: int) -> list[UiaNode]:
        """Chụp cây phần tử quanh điểm; mở/đóng một snapshot trong sổ đăng ký."""
        accessor = self.accessor
        element = self._call("element_from_point", lambda: accessor.element_from_point(int(x), int(y)))
        if element is None:
            self.registry.begin_snapshot()
            self.registry.end_snapshot()
            return []
        nodes = self._call("build_subtree", lambda: accessor.build_subtree(element)) or []
        snapshot_id = self.registry.begin_snapshot()
        out: list[UiaNode] = []
        for raw in nodes[:MAX_SUBTREE_NODES]:
            entry = self.registry.add(raw, snapshot_id=snapshot_id)
            out.append(self._to_node(entry))
        self.registry.end_snapshot()
        return out

    def _to_node(self, entry: ElementEntry) -> UiaNode:
        return UiaNode(
            token=self.registry.mint_token(entry),
            runtime_id=entry.runtime_id,
            generation=entry.generation,
            fingerprint=entry.fingerprint,
            role=entry.role,
            label=entry.label,
            payload=dict(entry.payload),
            bounds=dict(entry.bounds),
            patterns=list(entry.patterns),
            pid=entry.pid,
            handle=entry.handle,
        )

    def element_at_point(self, x: int, y: int, *, pid: int | None = None) -> UiaNode:
        """Phần tử trên cùng tại điểm; lọc theo tiến trình khi ``pid`` được đưa vào."""
        nodes = self.snapshot(x, y)
        if not nodes:
            raise PlatformError(UIA_NO_ELEMENT, "UI Automation không trả về phần tử nào.", x=x, y=y)
        node = nodes[0]
        if pid is not None and node.pid is not None and int(node.pid) != int(pid):
            raise PlatformError(
                UIA_NO_ELEMENT,
                "Phần tử tại điểm thuộc tiến trình khác (cửa sổ bị che).",
                x=x,
                y=y,
                element_pid=node.pid,
                window_pid=int(pid),
            )
        return node

    # -- hành động ---------------------------------------------------------
    def resolve(self, token: str) -> UiaNode:
        return self._to_node(self.registry.resolve(token))

    def invoke(self, token: str, pattern: str | None = None) -> dict[str, Any]:
        node = self.resolve(token)
        available = list(node.patterns)
        chosen = pattern or next((name for name in ("Invoke", "Toggle", "SelectionItem") if name in available), None)
        if chosen is None:
            raise PlatformError(
                UIA_UNAVAILABLE,
                "Phần tử không cung cấp pattern hành động nào (Invoke/Toggle/SelectionItem).",
                element_token=token,
                patterns=available,
            )
        if chosen not in available:
            raise PlatformError(
                UIA_UNAVAILABLE,
                f"Phần tử không cung cấp pattern {chosen}.",
                element_token=token,
                patterns=available,
            )
        accessor = self.accessor
        self._call("invoke", lambda: accessor.invoke(node.handle, chosen))
        return {
            "pattern": chosen,
            "elementToken": token,
            "runtimeId": node.runtime_id,
            "generation": node.generation,
        }

    def focus(self, token: str) -> dict[str, Any]:
        node = self.resolve(token)
        accessor = self.accessor
        self._call("focus", lambda: accessor.focus(node.handle))
        return {"elementToken": token, "runtimeId": node.runtime_id}

    def stats(self) -> dict[str, Any]:
        return {
            "apartment": self._apartment,
            "accessor": getattr(self.accessor, "name", "unknown"),
            "consecutiveTimeouts": self._consecutive_timeouts,
            **self.registry.stats(),
        }


# ---------------------------------------------------------------------------
# Điểm vào cấp module
# ---------------------------------------------------------------------------
_accessor_override: UiaAccessor | None = None
_session: UiaSession | None = None


def set_accessor(accessor: UiaAccessor | None) -> None:
    """Tiêm accessor (test, hoặc bản khác của UIA) và bỏ phiên đang có."""
    global _accessor_override, _session
    _accessor_override = accessor
    _session = None


def set_session(session: UiaSession | None) -> None:
    """Tiêm thẳng một phiên (test)."""
    global _session
    _session = session


def get_session(platform: WindowsPlatform | None = None) -> UiaSession:
    """Phiên dùng chung cho một accessor — đổi nền tảng/accessor thì tạo phiên mới."""
    global _session
    accessor = _accessor_override
    if accessor is None:
        p = platform or get_platform()
        getter = getattr(p, "uia_accessor", None)
        if callable(getter):
            try:
                accessor = getter()
            except PlatformError:
                accessor = None
    if accessor is None:
        accessor = ComUiaAccessor(platform)
    if _session is None or _session.accessor is not accessor:
        _session = UiaSession(accessor)
    return _session


def element_at_point(
    x: int,
    y: int,
    *,
    window: Any = None,
    pid: int | None = None,
    platform: WindowsPlatform | None = None,
    session: UiaSession | None = None,
) -> UiaNode:
    """Phần tử UIA tại điểm (ném ``PlatformError`` với mã lý do của tầng soi)."""
    target = session or get_session(platform)
    if pid is None and window is not None:
        pid = getattr(window, "pid", None)
    return target.element_at_point(int(x), int(y), pid=pid)


def resolve(token: str, *, platform: WindowsPlatform | None = None, session: UiaSession | None = None) -> UiaNode:
    return (session or get_session(platform)).resolve(token)


def invoke(
    token: str,
    *,
    platform: WindowsPlatform | None = None,
    session: UiaSession | None = None,
    pattern: str | None = None,
) -> dict[str, Any]:
    return (session or get_session(platform)).invoke(token, pattern)


def focus(token: str, *, platform: WindowsPlatform | None = None, session: UiaSession | None = None) -> dict[str, Any]:
    return (session or get_session(platform)).focus(token)


def node_payload(node: UiaNode) -> dict[str, Any]:
    """Payload ``type='uia'`` (chưa có ``elementToken``/``windowId``/``label``)."""
    payload = dict(node.payload)
    payload["bounds"] = dict(node.bounds)
    payload["patterns"] = list(node.patterns)
    if node.pid is not None:
        payload["pid"] = node.pid
    return payload
