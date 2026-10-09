"""Đích CUA của một phiên — một cửa sổ, hay cả máy.

Quyết định thuần nằm ở đây: không ctypes, không mạng, không DB. Luật §1.2 của
`docs/architecture/host-desktop-control.md` nói lớp nền tảng phải mỏng và mọi quyết định phải kiểm
được bằng nền tảng giả — máy Linux vẫn chạy được toàn bộ tệp test của mô-đun này.

Vì sao cần "đích" chứ không chỉ `windowId` theo từng lời gọi: người dùng chọn trong panel "Màn hình
máy" một cửa sổ (hoặc cả máy) cho **cả phiên**, agent có thể xin cửa sổ khác bằng tên app, và panel
đi theo đích agent vừa đặt. Không có đích thì mỗi lời gọi lại rơi về "cửa sổ đang hoạt động" — đúng
thứ mà người dùng không kiểm soát được.
"""

from __future__ import annotations

import time
from typing import Any

#: Đích là một cửa sổ cụ thể.
KIND_WINDOW = 'window'
#: Đích là cả máy: agent làm việc với cửa sổ đang hoạt động (Codex gọi đây là "whole machine").
KIND_MACHINE = 'machine'
KINDS = (KIND_WINDOW, KIND_MACHINE)

#: Scope `workspace` không được nhắm cả máy (§7.2 hợp đồng).
MACHINE_SCOPE = 'machine'

TARGET_REQUIRED = 'TARGET_REQUIRED'
TARGET_UNKNOWN = 'TARGET_UNKNOWN'
TARGET_AMBIGUOUS = 'TARGET_AMBIGUOUS'
CUA_MACHINE_SCOPE_REQUIRED = 'CUA_MACHINE_SCOPE_REQUIRED'
TARGET_KIND_INVALID = 'TARGET_KIND_INVALID'

#: Trường được giữ của một cửa sổ. `windowId` (hwnd) sống lại sau khi khởi động lại tiến trình,
#: nhưng hwnd có thể bị Windows tái dùng cho tiến trình khác — nên `pid` là thứ kiểm lại trước khi
#: gửi input, và `processName`/`title` là đường tìm lại khi hwnd đã chết.
WINDOW_FIELDS = ('windowId', 'pid', 'title', 'processName', 'windowClass')


class TargetError(Exception):
    """Lỗi có mã của đường phân giải đích (tầng trên đổi thẳng thành payload công cụ)."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details


def _text(value: Any) -> str:
    return str(value or '').strip()


def _fold(value: Any) -> str:
    return _text(value).casefold()


def _bare_process(name: Any) -> str:
    """`notepad.exe` và `notepad` là cùng một ứng dụng với người dùng."""
    text = _fold(name)
    return text[:-4] if text.endswith('.exe') else text


def as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def window_entry(window: Any) -> dict:
    """Gói một `WindowInfo` (hoặc dict của `list_windows`) thành đích cửa sổ chuẩn hoá."""
    def read(key, default=None):
        if isinstance(window, dict):
            return window.get(key, default)
        return getattr(window, key, default)

    hwnd = as_int(read('windowId', read('hwnd')))
    if hwnd is None:
        raise TargetError(TARGET_UNKNOWN, 'cửa sổ không có windowId')
    entry = {'kind': KIND_WINDOW, 'windowId': hwnd}
    pid = as_int(read('pid'))
    if pid:
        entry['pid'] = pid
    title = _text(read('title'))
    if title:
        entry['title'] = title
    process = _text(read('processName', read('process_name')))
    if process:
        entry['processName'] = process
    window_class = _text(read('windowClass', read('class_name')))
    if window_class:
        entry['windowClass'] = window_class
    return entry


def normalize(raw: Any) -> dict | None:
    """Đích đã lưu (từ config phiên) → dạng chuẩn; rác thì trả `None` chứ không ném.

    Config là dữ liệu người dùng chạm được (và bản cũ có thể thiếu trường), nên đường đọc phải
    khoan dung: một đích hỏng nghĩa là "chưa chọn gì", không phải sập lượt.
    """
    if not isinstance(raw, dict):
        return None
    kind = _text(raw.get('kind')).lower()
    if kind == KIND_MACHINE:
        return {'kind': KIND_MACHINE}
    if kind != KIND_WINDOW:
        return None
    hwnd = as_int(raw.get('windowId'))
    if hwnd is None:
        return None
    entry = {'kind': KIND_WINDOW, 'windowId': hwnd}
    pid = as_int(raw.get('pid'))
    if pid:
        entry['pid'] = pid
    for field in ('title', 'processName', 'windowClass'):
        value = _text(raw.get(field))
        if value:
            entry[field] = value
    return entry


def is_machine(target: Any) -> bool:
    return isinstance(target, dict) and _text(target.get('kind')).lower() == KIND_MACHINE


def is_window(target: Any) -> bool:
    return isinstance(target, dict) and _text(target.get('kind')).lower() == KIND_WINDOW


def describe(target: Any) -> str:
    """Chuỗi người đọc được cho thẻ duyệt và log — `cả máy` hay `Notepad — Untitled`.

    Khoan dung với đầu vào thô (dict của `list_windows` hay `WindowInfo` chưa qua `normalize`) vì
    tầng gọi dùng hàm này cho cả đích đã lưu lẫn cửa sổ vừa tìm được.
    """
    entry = normalize(target)
    if entry is None and isinstance(target, dict) and target.get('windowId') is not None:
        try:
            entry = window_entry(target)
        except TargetError:
            entry = None
    if entry is None:
        return 'chưa chọn đích'
    if is_machine(entry):
        return 'cả máy'
    title = _text(entry.get('title')) or 'không tiêu đề'
    process = _text(entry.get('processName'))
    return '%s — %s' % (process, title) if process else title


def scope_allows_machine(scope: Any) -> bool:
    """Cả máy chỉ mở khi phạm vi quyền là `machine` (§7.2)."""
    return _text(scope).lower() == MACHINE_SCOPE


def _candidates(windows: list, needle: str, field: str) -> list:
    """Khớp chính xác trước (bỏ `.exe`), rồi mới khớp chuỗi con — và chỉ nhận chuỗi con DUY NHẤT."""
    exact = [item for item in windows if _fold(item.get(field)) == needle]
    if not exact and field == 'processName':
        exact = [item for item in windows if _bare_process(item.get(field)) == needle]
    if exact:
        return exact
    return [item for item in windows if needle and needle in _fold(item.get(field))]


def match_window(windows: list, *, app: Any = None, window: Any = None) -> dict:
    """Tìm cửa sổ theo tên tiến trình (`app`) và/hoặc tiêu đề (`window`).

    0 kết quả ⇒ `TARGET_UNKNOWN` (`reason: not_found`); nhiều kết quả ⇒ `TARGET_AMBIGUOUS` kèm
    danh sách ứng viên để model chọn lại bằng `windowId`. Không đoán bừa: bắn input vào cửa sổ
    đoán sai nguy hiểm hơn một lỗi rõ ràng.
    """
    items = [item for item in (windows or []) if isinstance(item, dict)]
    if app in (None, '') and window in (None, ''):
        raise TargetError(TARGET_UNKNOWN, 'cần `app` hoặc `window` để tìm cửa sổ', reason='not_found')
    found = items
    for value, field in ((app, 'processName'), (window, 'title')):
        if value in (None, ''):
            continue
        needle = _fold(value)
        found = _candidates(found, needle, field)
        if not found:
            break
    if not found:
        raise TargetError(TARGET_UNKNOWN, 'không thấy cửa sổ nào khớp', reason='not_found',
                          app=_text(app) or None, window=_text(window) or None)
    if len(found) > 1:
        raise TargetError(TARGET_AMBIGUOUS, 'nhiều cửa sổ cùng khớp — chọn bằng windowId',
                          app=_text(app) or None, window=_text(window) or None,
                          candidates=[window_entry(item) for item in found[:8]])
    return window_entry(found[0])


def verify_window(target: dict, windows: list) -> dict | None:
    """Đích cửa sổ còn sống không? Trả cửa sổ đang tồn tại, hoặc `None`.

    Hai bẫy thật của Windows: hwnd chết sau khi app đóng, và hwnd **bị tái dùng** cho tiến trình
    khác. Cùng hwnd nhưng khác `pid` ⇒ coi như mất, tìm lại theo tên; tìm lại cũng không thấy ⇒
    `None` (tầng gọi trả `TARGET_UNKNOWN`, không bắn vào cửa sổ khác).
    """
    entry = normalize(target)
    if entry is None:
        return None
    items = [item for item in (windows or []) if isinstance(item, dict)]
    hwnd = entry['windowId']
    pid = entry.get('pid')
    for item in items:
        if as_int(item.get('windowId')) == hwnd:
            if pid and as_int(item.get('pid')) not in (None, pid):
                break                       # hwnd bị tái dùng: rơi xuống đường tìm theo tên
            return window_entry(item)
    by_name = {}
    if entry.get('processName'):
        by_name['app'] = entry['processName']
    if entry.get('title'):
        by_name['window'] = entry['title']
    if not by_name:
        return None
    try:
        return match_window(items, **by_name)
    except TargetError:
        return None


def resolve(args: dict, session_target: Any, windows: list, scope: Any) -> tuple[dict, str]:
    """Đích cho một lời gọi CUA, theo thứ tự: `windowId` → `app`/`window` → đích phiên → mặc định.

    Trả `(đích, nguồn)` với `nguồn ∈ {'arg', 'agent', 'session', 'default'}`. `nguồn == 'agent'`
    nghĩa là đích phiên vừa đổi và panel phải đi theo.
    """
    args = args if isinstance(args, dict) else {}
    items = [item for item in (windows or []) if isinstance(item, dict)]
    raw_window = args.get('windowId')
    if raw_window in (None, '') and isinstance(args.get('target'), dict):
        raw_window = args['target'].get('windowId')
    if raw_window not in (None, ''):
        hwnd = as_int(raw_window)
        for item in items:
            if as_int(item.get('windowId')) == hwnd:
                return window_entry(item), 'arg'
        raise TargetError(TARGET_UNKNOWN, 'không thấy cửa sổ %s' % raw_window, reason='not_found')

    app, window = args.get('app'), args.get('window')
    if app not in (None, '') or window not in (None, ''):
        return match_window(items, app=app, window=window), 'agent'

    stored = normalize(session_target)
    if stored is not None:
        if is_machine(stored):
            if not scope_allows_machine(scope):
                raise TargetError(CUA_MACHINE_SCOPE_REQUIRED,
                                  'đích cả máy cần phạm vi quyền `machine`', scope=_text(scope) or None)
            return stored, 'session'
        alive = verify_window(stored, items)
        if alive is None:
            raise TargetError(TARGET_UNKNOWN, 'cửa sổ đích không còn tồn tại',
                              reason='window_gone', target=stored)
        return alive, 'session'

    if scope_allows_machine(scope):
        # Chưa chọn gì mà phạm vi là cả máy: giữ hành vi cũ (cửa sổ đang hoạt động).
        return {'kind': KIND_MACHINE}, 'default'
    raise TargetError(TARGET_REQUIRED, 'chọn cửa sổ cho agent trong panel Màn hình máy trước')


def apply_agent_target(store: Any, sid: str, target: dict, source: str) -> dict:
    """Ghi đích vừa phân giải vào phiên khi agent tự xin (`nguồn == 'agent'`).

    Chỉ ghi khi đổi thật: mỗi lần ghi là một `revision` mới, và panel coi `revision` đổi là "agent
    vừa chuyển cửa sổ" — ghi vô điều kiện sẽ làm panel nhảy liên tục.
    """
    if source != 'agent' or store is None or not sid:
        return target
    if normalize(store.read(sid)) == normalize(target):
        return target
    store.write(sid, target, set_by='agent')
    return target


class SessionTargetStore:
    """Đích CUA đọc/ghi trong `sessions.config.cuaTarget` (một hàng, không bảng mới).

    Đi lên phiên gốc khi phiên con chưa chọn gì: subagent chạy trong cùng một máy và cùng một
    folder, nên nó phải thấy đúng cửa sổ mà phiên cha đã chọn.
    """

    KEY = 'cuaTarget'
    REVISION_KEY = 'cuaTargetRevision'

    def __init__(self, store) -> None:
        self.store = store

    def _config(self, sid: str) -> dict:
        try:
            session = self.store.get(sid)
        except KeyError:
            return {}
        config = session.get('config') or {}
        return config if isinstance(config, dict) else {}

    def read_own(self, sid: str) -> dict | None:
        return normalize(self._config(sid).get(self.KEY))

    def read(self, sid: str) -> dict | None:
        """Đích hiệu lực: của chính phiên, hoặc của phiên gốc gần nhất đã chọn."""
        seen = set()
        current = sid
        while current and current not in seen:
            seen.add(current)
            own = self.read_own(current)
            if own is not None:
                return own
            try:
                parent = self.store.get(current).get('parent_id')
            except KeyError:
                return None
            current = parent
        return None

    def root(self, sid: str) -> str:
        """Phiên gốc của chuỗi `parent_id` — nơi MỌI lần ghi đi vào.

        Subagent chạy trên cùng máy và cùng folder với phiên gốc; nếu nó ghi đích vào hàng của
        chính nó thì phiên gốc không thấy, còn người dùng thì thấy hai đích khác nhau cho một máy.
        """
        seen = set()
        current = sid
        while current and current not in seen:
            seen.add(current)
            try:
                parent = self.store.get(current).get('parent_id')
            except KeyError:
                return current
            if not parent:
                return current
            current = parent
        return sid

    def read_meta(self, sid: str) -> dict:
        """`{target, requestedBy, revision, at, inheritedFrom}` — thứ panel đọc để đi theo agent.

        Một hàng ĐÃ GHI nhưng đích là `None` (người dùng vừa xoá) vẫn là câu trả lời: nó chặn việc
        đi tiếp lên phiên cha và giữ đúng `revision`, nếu không thì `DELETE` xong `revision` tụt về 0
        và lần `PUT` sau đó với `expectedRevision` cũ sẽ hỏng mãi.
        """
        seen = set()
        current = sid
        while current and current not in seen:
            seen.add(current)
            config = self._config(current)
            if self.KEY in config:
                target = normalize(config.get(self.KEY))
                return {'target': target,
                        'requestedBy': _text(config.get('cuaTargetSetBy')) or 'user',
                        'revision': as_int(config.get(self.REVISION_KEY)) or 0,
                        'at': config.get('cuaTargetAt'),
                        'inheritedFrom': None if (current == sid or target is None) else current}
            try:
                current = self.store.get(current).get('parent_id')
            except KeyError:
                break
        return {'target': None, 'requestedBy': None, 'revision': 0, 'at': None, 'inheritedFrom': None}

    def write(self, sid: str, target: dict, *, set_by: str = 'user') -> dict:
        """Ghi đích + tăng `revision` vào PHIÊN GỐC. Trả bản ghi vừa ghi (cùng hình dạng `read_meta`)."""
        entry = normalize(target)
        if entry is None:
            raise TargetError(TARGET_KIND_INVALID, 'đích không hợp lệ')
        root = self.root(sid)
        config = dict(self._config(root))
        revision = (as_int(config.get(self.REVISION_KEY)) or 0) + 1
        config[self.KEY] = entry
        config['cuaTargetSetBy'] = set_by
        config[self.REVISION_KEY] = revision
        config['cuaTargetAt'] = time.time()
        self.store.update_config(root, config)
        return {'target': entry, 'requestedBy': set_by, 'revision': revision,
                'at': config['cuaTargetAt'], 'inheritedFrom': None}

    def clear(self, sid: str) -> dict:
        root = self.root(sid)
        config = dict(self._config(root))
        revision = (as_int(config.get(self.REVISION_KEY)) or 0) + 1
        config[self.KEY] = None
        config['cuaTargetSetBy'] = 'user'
        config[self.REVISION_KEY] = revision
        config['cuaTargetAt'] = time.time()
        self.store.update_config(root, config)
        return {'target': None, 'requestedBy': 'user', 'revision': revision,
                'at': config['cuaTargetAt'], 'inheritedFrom': None}
