"""Executor của host mode — cùng hợp đồng với `SandboxExecutor`, chạy trên MÁY THẬT.

Vì sao là một executor thứ hai chứ không phải một kiến trúc mới
----------------------------------------------------------------

Harness đã chạy trên máy chủ nhà và chỉ *điều khiển* box qua HTTP; mọi công cụ đi qua một điểm nối
duy nhất (`api/server.py` dựng `SandboxExecutor`). Host mode = **cùng hợp đồng đó**, đổi chỗ thi
hành: `execute(name, args, session, turn, step, tool_call_id, root)` trả về đúng khuôn payload mà
`worker.py` trong box trả về, nên mọi thứ phía trên (work graph, bằng chứng, khôi phục) không phải
biết mình đang ở chế độ nào.

Ba ranh giới của bản v1
-----------------------

* **Quyền đi trước, thi hành sau.** Mọi lời gọi đi qua `PermissionPolicy.decide()`; `deny` ⇒ lỗi có
  mã, `ask` ⇒ hỏi qua `approver` (do `api/server.py` nối vào bề mặt duyệt sẵn có). Không có
  `approver` thì **fail closed** — thiếu đường hỏi không có nghĩa là được phép.
* **Công cụ chưa hỗ trợ trả lỗi CÓ MÃ, không ném.** `UNSUPPORTED_IN_HOST_MODE` để model biết nó
  đang ở chế độ nào thay vì đọc một traceback.
* **Không nội suy văn của model vào shell.** Trên Windows lệnh đi qua `powershell.exe -Command` với
  đối số dạng DANH SÁCH (không `shell=True`), nên dấu `;`/`|` là của PowerShell, không phải của
  `cmd.exe`; trên POSIX là `/bin/sh -c` đúng như box.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import platform as platform_module
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from ..agent_core import cua_target as cua_target_module
from ..agent_core import permissions as permissions_module
from .win.errors import PlatformError

#: Mã lỗi cho công cụ v1 chưa có trên host. Có mã để model phân biệt "chưa làm" với "hỏng".
UNSUPPORTED_CODE = 'UNSUPPORTED_IN_HOST_MODE'
PERMISSION_DENIED_CODE = 'PERMISSION_DENIED'
APPROVAL_REQUIRED_CODE = 'APPROVAL_REQUIRED'
APPROVAL_DENIAL_BREAKER_CODE = 'APPROVAL_DENIAL_BREAKER'
PATH_ESCAPE_CODE = 'PATH_OUTSIDE_WORKSPACE'
COMMAND_TIMEOUT_CODE = 'COMMAND_TIMEOUT'
#: Lệnh chạy xong nhưng thoát khác 0. Có mã riêng để tầng phân loại không rơi vào nhánh "chưa biết"
#: (đo được ở sổ thật: hàng `terminal_exec` chỉ có `exit_code`, thiếu `errorCode`, nên agent nhận lời
#: khuyên dành cho lỗi sai tham số trong khi việc cần làm là đọc đầu ra rồi sửa lệnh).
COMMAND_EXIT_NONZERO_CODE = 'COMMAND_EXIT_NONZERO'

# -- H7: mã lỗi của đường CUA (điều khiển desktop máy thật) --------------------
#: Host mode chạy nhưng KHÔNG có `DesktopControl` (thiếu nền tảng/cấu hình) ⇒ không có CUA.
CUA_UNAVAILABLE_CODE = 'CUA_UNAVAILABLE'
#: Người dùng đang giữ quyền điều khiển — agent phải dừng, không chen input.
HUMAN_HAS_CONTROL_CODE = 'HUMAN_HAS_CONTROL'
#: Cửa sổ/điểm đích không xác định được (không có cửa sổ tại toạ độ, hwnd lạ).
TARGET_UNKNOWN_CODE = 'TARGET_UNKNOWN'
#: Phiên chưa chọn đích mà phạm vi quyền lại là `workspace` — chưa biết làm việc ở đâu.
TARGET_REQUIRED_CODE = cua_target_module.TARGET_REQUIRED
#: Nhiều cửa sổ cùng khớp tên app/tiêu đề — model phải chọn lại bằng `windowId`.
TARGET_AMBIGUOUS_CODE = cua_target_module.TARGET_AMBIGUOUS
#: Đích "cả máy" khi phạm vi quyền không phải `machine` (§7.2 hợp đồng).
MACHINE_SCOPE_REQUIRED_CODE = cua_target_module.CUA_MACHINE_SCOPE_REQUIRED
#: Không mở được ứng dụng mà agent xin (`ShellExecuteW` lỗi).
LAUNCH_FAILED_CODE = 'LAUNCH_FAILED'
#: Thời gian chờ cửa sổ của ứng dụng vừa mở. Quá hạn ⇒ `TARGET_UNKNOWN` (`launch_timeout`), không
#: treo lượt: người dùng vẫn thấy lý do thay vì một lời gọi không bao giờ trả về.
LAUNCH_TIMEOUT_SEC = 10.0
#: Không lấy được mutex chuột/phím — tiến trình khác đang tiêm input.
CONTROL_BUSY_CODE = 'CONTROL_BUSY'
#: Cửa sổ đổi vị trí/kích thước/DPI sau khi agent đã soi — token cũ, phải soi lại.
SOURCE_CHANGED_CODE = 'SOURCE_CHANGED'
#: Hành động chưa có trên host.
UNSUPPORTED_ACTION_CODE = 'UNSUPPORTED_ACTION'

#: Hành động `computer_use` mà đường host gửi được. Danh sách này phải khớp `enum` trong
#: `tool_contracts.py`: thiếu một cái ở đây thì model gọi được mà máy trả `UNSUPPORTED_ACTION`.
CUA_ACTIONS = ('click', 'double_click', 'right_click', 'middle_click', 'type', 'key', 'scroll',
               'drag', 'hold', 'stroke')

#: Đường `/__box/*` chưa có bản host tương ứng (`HostExecutor.request`).
HOST_REQUEST_UNSUPPORTED_CODE = 'HOST_REQUEST_UNSUPPORTED'


class HostRequestUnsupported(RuntimeError):
    """`HostExecutor.request` gặp đường chưa có bản host — nói ra thay vì trả payload rỗng."""

    code = HOST_REQUEST_UNSUPPORTED_CODE

    def __init__(self, route):
        super().__init__(f'{HOST_REQUEST_UNSUPPORTED_CODE}: đường `{route}` chưa có bản host.')
        self.route = route


def _is_guarded(decision):
    """Quyết định thuộc nhóm LUÔN HỎI (`guarded:` của `permissions.py`) — một lần cho phép là một lần."""
    return str(getattr(decision, 'rule', '') or '').startswith('guarded:')


#: Hai lựa chọn "nhớ" của thẻ ⇒ verdict. Nhận cả gạch nối lẫn gạch dưới: `resolve_decision` slug hoá
#: id trước khi phát ra thẻ, nên `approve_session` tới đây thành `approve-session`.
_SESSION_CHOICES = frozenset({'approve-session', 'approve_session'})
_ALWAYS_CHOICES = frozenset({'approve-always', 'approve_always'})
#: Lựa chọn thứ ba của thẻ CUA: nhớ theo ỨNG DỤNG (exe + aumid), không theo lời gọi.
_APP_CHOICES = frozenset({'approve-app', 'approve_app'})


def _is_cua(tool):
    """Lời gọi này có phải công cụ điều khiển máy (CUA) không."""
    return str(tool or '') in CUA_TOOLS


def cua_app_hint(args):
    """Tên ứng dụng để thẻ CUA nói đúng thứ người dùng đang cho phép, hoặc `''`.

    Đọc từ chính lời gọi (`app` model xin, hoặc tên tiến trình của `windowId` đã phân giải) — thẻ
    duyệt không được hứa một phạm vi rộng hơn thứ nó ghi nhớ.
    """
    if not isinstance(args, dict):
        return ''
    app = str(args.get('app') or '').strip()
    if app:
        return app
    target = args.get('__target')
    if isinstance(target, dict):
        return str(target.get('processName') or '').strip()
    return ''


def approval_options(decision, tool='', args=None):
    """Lựa chọn hiện trên thẻ duyệt của host mode — MỘT nguồn cho cả hai đường nối `approver`.

    Nhóm "luôn hỏi" (`guarded:`) chỉ có một lựa chọn cho phép: nó không ghi nhớ được, nên mời
    "cả phiên"/"luôn cho phép" là hứa điều `HostExecutor` sẽ không làm.

    CUA (§7.2 hợp đồng) KHÔNG có "luôn cho phép": lựa chọn thứ ba là **theo app này** (exe + aumid),
    và chỉ hiện khi biết tên ứng dụng — thẻ không được mời một phạm vi mà nó không ghi nhớ được.

    `kind` của hai lựa chọn nhớ là `alternative`, KHÔNG phải `approve`: `normalize_decision_options`
    ép `id = kind` cho mọi lựa chọn `approve`/`reject`, nên ba lựa chọn `approve` biến thành
    `approve`, `approve-2`, `approve-3` — và `approval_verdict` không nhận ra hai id sau, tức người
    dùng bấm "Cho phép cả phiên" thì lệnh bị TỪ CHỐI (đo được trên harness thật). `alternative`
    không bị ép id, nên id slug hoá vẫn ổn định, và `resolve_decision` vẫn chốt nó là `approved`.
    """
    options = [{'id': 'approve', 'label': 'Cho phép một lần', 'kind': 'approve'}]
    if not _is_guarded(decision):
        options.append({'id': 'approve-session', 'label': 'Cho phép cả phiên',
                        'kind': 'alternative'})
        if _is_cua(tool):
            if cua_app_hint(args):
                options.append({'id': 'approve-app', 'label': 'Theo app này',
                                'kind': 'alternative'})
        else:
            options.append({'id': 'approve-always', 'label': 'Luôn cho phép',
                            'kind': 'alternative'})
    options.append({'id': 'reject', 'label': 'Từ chối', 'kind': 'reject'})
    return options


def approval_verdict(outcome, decision, tool=''):
    """`runtime.decision(...)` trả về gì ⇒ verdict của `HostExecutor`. Lạ ⇒ `deny` (fail closed)."""
    if not isinstance(outcome, dict) or outcome.get('status') != 'approved':
        return 'deny'
    choice = str(outcome.get('choice') or '')
    if choice == 'approve':
        return 'allow'
    if _is_guarded(decision):
        # Thẻ của nhóm luôn hỏi không có lựa chọn nhớ nào; id lạ ⇒ từ chối.
        return 'deny'
    if choice in _SESSION_CHOICES:
        return 'allow_session'
    if choice in _APP_CHOICES:
        # Thẻ CUA mới có id này. Công cụ khác gửi id đó là id lạ ⇒ từ chối.
        return 'allow_app' if _is_cua(tool) else 'deny'
    if choice in _ALWAYS_CHOICES:
        # CUA không bao giờ có luật vĩnh viễn: id "luôn cho phép" tới đây là id lạ.
        return 'deny' if _is_cua(tool) else 'allow_always'
    return 'deny'


def approval_reason(decision, tool='', args=None):
    """Câu lý do trên thẻ duyệt, kèm lời nhắc khi lệnh thuộc nhóm luôn hỏi hoặc là thao tác CUA."""
    reason = f'{decision.reason}. Lệnh chạy bằng tài khoản của bạn; không có sandbox OS.'
    if _is_guarded(decision):
        reason += ' Lệnh này thuộc nhóm luôn hỏi: chỉ cho phép một lần.'
    if _is_cua(tool):
        app = cua_app_hint(args)
        reason += (' Thao tác trên màn hình thật%s: không có luật vĩnh viễn, chỉ nhớ trong phiên.'
                   % (f' — ứng dụng `{app}`' if app else ''))
    return reason

#: Công cụ v1 chạy được trên host. Danh sách này là HỢP ĐỒNG với tài liệu `docs/plan/desktop-host-mode.md`.
HOST_TOOLS = ('file_read', 'codebase_glob', 'codebase_grep', 'file_write', 'file_edit_block',
              'terminal_exec')

#: Công cụ CUA CHỈ ĐỌC (H5/H6): chụp màn hình và soi phần tử. Vẫn cần lease, không cần mutex input.
CUA_OBSERVE_TOOLS = ('computer_screen_capture', 'inspect_element')
#: Công cụ CUA TIÊM INPUT (H7): mọi lời gọi đi qua lease + mutex + fence.
CUA_INPUT_TOOLS = ('computer_use',)
CUA_TOOLS = CUA_OBSERVE_TOOLS + CUA_INPUT_TOOLS
HOST_TOOLS = HOST_TOOLS + CUA_TOOLS

#: Công cụ tồn tại trong catalog nhưng CHƯA có trên host — trả lỗi có mã thay vì "unknown tool".
DEFERRED_TOOLS = ('browser_use', 'computer_screen_record', 'verify_exec', 'write_plan', 'dossier_write',
                  'design_write', 'design_diff', 'design_branch_create', 'design_file_sha',
                  'design_revert', 'session_ensure', 'journal_append', 'checkpoint_write',
                  'captures_prune', 'codebase_symbols')

BINARY_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.tif', '.tiff', '.pdf',
                     '.zip', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.docx', '.xlsx', '.pptx',
                     '.whl', '.so', '.bin', '.exe', '.dll', '.mp4', '.mov', '.avi', '.mp3', '.wav',
                     '.woff', '.woff2', '.ttf', '.otf', '.sqlite', '.db')
BINARY_SNIFF_BYTES = 8192
BINARY_READ_CHARS = 30000
READ_TRUNCATE_ARTIFACT_CHARS = 20000
OUTPUT_PREVIEW_CHARS = 15000
EVIDENCE_MAX_BYTES = 2 * 1024 * 1024
COMMAND_TIMEOUT_DEFAULT = 30
COMMAND_TIMEOUT_MAX = 120
GLOB_MAX_RESULTS = 500
GREP_MAX_RESULTS = 100
GREP_MAX_FILE_BYTES = 1_000_000


def unsupported_result(name):
    """Payload cho công cụ chưa hỗ trợ. KHÔNG BAO GIỜ ném: model đọc mã, người dùng đọc câu."""
    return {
        'is_error': True,
        'errorCode': UNSUPPORTED_CODE,
        'error': ('`%s` chưa chạy được ở chế độ máy thật (host mode). '
                  'Dùng box Docker nếu cần công cụ này.' % name),
        'tool': name,
        'mode': 'host',
    }


def error_result(code, message, **extra):
    payload = {'is_error': True, 'errorCode': code, 'error': message}
    # Trường `None` bị bỏ: payload lỗi chỉ mang dữ kiện thật, không mang khoá rỗng.
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def read_int_arg(value, default):
    """Số nguyên KHÔNG ÂM từ `args` của model — cùng quy tắc với worker trong box (A-5)."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def sha256_of(raw):
    return hashlib.sha256(raw).hexdigest()


def file_digest(target):
    digest = hashlib.sha256()
    with open(target, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def before_write(target):
    """`(sha256, văn bản cũ, lý do bỏ diff)` — cùng khuôn `worker.before_write`."""
    if not target.is_file():
        return None, None, None
    if target.stat().st_size > EVIDENCE_MAX_BYTES:
        return file_digest(target), None, 'too_large'
    raw = target.read_bytes()
    try:
        return sha256_of(raw), raw.decode('utf-8'), None
    except UnicodeDecodeError:
        return sha256_of(raw), None, 'binary'


def read_file_payload(target, offset=0, limit=BINARY_READ_CHARS):
    """Nội dung một tệp cho `file_read`: văn bản, nhị phân thì base64 — y hệt box (A8, A-5)."""
    offset = read_int_arg(offset, 0)
    limit = read_int_arg(limit, BINARY_READ_CHARS)
    binary = target.suffix.lower() in BINARY_EXTENSIONS
    if not binary:
        with open(target, 'rb') as handle:
            binary = b'\x00' in handle.read(BINARY_SNIFF_BYTES)
    if not binary:
        try:
            text = target.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            pass
        else:
            chunk = text[offset:offset + limit]
            end = offset + len(chunk)
            return {'content': chunk, 'truncated': end < len(text), 'sizeChars': len(text),
                    'nextOffset': end if end < len(text) else None}
    size = target.stat().st_size
    aligned = offset - offset % 3
    with open(target, 'rb') as handle:
        handle.seek(aligned)
        raw = handle.read(BINARY_READ_CHARS * 3 // 4)
    end = aligned + len(raw)
    payload = {'content': base64.b64encode(raw).decode('ascii')[:BINARY_READ_CHARS],
               'encoding': 'base64', 'truncated': end < size, 'bytesRead': len(raw),
               'sizeBytes': size, 'nextOffset': end if end < size else None}
    if aligned != offset:
        payload['offsetAlignedTo'] = 3
    return payload


def _slug(text):
    return re.sub(r'[^0-9A-Za-z._-]+', '-', str(text or '')).strip('-')[:60] or 'command'


class HostExecutor:
    """Thi hành công cụ v1 trên máy thật. Mọi quyết định quyền đi qua `policy`."""

    #: Chế độ thi hành của lớp này — `machine_router` đọc để biết một phiên host có box hay không.
    execution_mode = 'host'

    def __init__(self, workspace=None, *, policy=None, platform=None, approver=None, env=None,
                 artifacts_dir=None, root=None, desktop=None, targets=None, trusted=False,
                 overlay=None):
        source = os.environ if env is None else env
        self.env = source
        self.workspace = Path(workspace or source.get('BOXFOX_HOST_WORKSPACE')
                              or Path.home() / 'BoxFox' / 'workspace').expanduser().resolve()
        self.policy = policy if policy is not None else permissions_module.PermissionPolicy(
            str(self.workspace), env=source)
        self.platform = platform or ('win32' if os.name == 'nt' else 'posix')
        #: `approver(tool, args, decision, session)` ⇒ `'allow'` | `'allow_session'` | `'allow_always'`
        #: | `'deny'`. Không có ⇒ mọi lời gọi cần hỏi đều bị từ chối (fail closed).
        self.approver = approver
        self.root = root
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else self.workspace / '.generated_artifacts'
        #: Giữ cùng tên thuộc tính với `SandboxExecutor` để chỗ gọi cũ không phải rẽ nhánh.
        self.visual_lock = asyncio.Lock()
        self.processes = {}      # session ⇒ process group đang chạy (để `cleanup` dừng được)
        self.permission_hook = None   # `api/server.py` gắn hàm ghi audit/thẻ duyệt nếu cần
        #: H7 — bộ điều khiển desktop (`DesktopControl`). `None` ⇒ CUA trả `CUA_UNAVAILABLE`
        #: thay vì ném: host mode vẫn chạy được các công cụ tệp/lệnh.
        self.desktop = desktop
        #: Đích CUA theo phiên (`SessionTargetStore`). `None` ⇒ chưa nối sổ phiên (test/đường cũ).
        self.targets = targets
        #: Folder dự án đã được người dùng xác nhận tin cậy. Chỉ đường `computer_use` và việc MỞ
        #: ứng dụng mới cần nó; chụp/soi (chỉ đọc) chạy được trong folder chưa tin cậy.
        self.trusted = bool(trusted)
        #: Viền báo vùng đang bị điều khiển trên màn hình thật (`CuaOverlay`), `None` ⇒ không vẽ.
        self.overlay = overlay
        self._prepared = False
        self._capture_module = None

    # -- CUA: chuẩn bị nền tảng (H5) -----------------------------------------

    def prepare(self):
        """Bật DPI awareness + nạp bảng phần tử một lần cho tiến trình host.

        Gọi lúc khởi động host mode (`api/server.py`); gọi lại là vô hại. Trả `(ok, code)` để
        chỗ gọi ghi log mà không phải bắt ngoại lệ — máy không điều khiển desktop được (không có
        X11, thiếu công cụ) vẫn khởi động được.

        Chọn mô-đun theo `sys.platform`: Windows dùng GDI + UIA, Linux dùng X11 + ImageMagick. Không
        dùng `self.platform` (chuỗi `'win32'`/`'posix'` dành cho shell) vì đây là chuyện của **nền
        tảng desktop**, không phải của shell.
        """
        if self._prepared:
            return True, ''
        capture_module = self._load_capture()
        # `_load_capture()` chỉ nạp MÔ-ĐUN; máy còn phải có một nền tảng thật đứng sau nó (X server
        # trả lời, hoặc Windows). Không có nền tảng thì `prepare()` phải nói "chưa điều khiển được",
        # nếu không panel sẽ báo CUA sẵn sàng trên một máy chẳng chụp được gì.
        if capture_module is None or self._desktop_platform() is None:
            return False, UNSUPPORTED_CODE
        try:
            capture_module.set_dpi_awareness()
        except Exception:
            pass
        try:
            from ..agent_core import inspect_host

            inspect_host.prepare()
        except Exception:
            pass
        self._prepared = True
        return True, ''

    # -- hợp đồng request (`/__box/*`) ---------------------------------------

    async def request(self, path, body=None, session=None):
        """Cùng hợp đồng `SandboxExecutor.request`, đổi chỗ đọc: **workspace của phiên**.

        Harness đọc chỉ mục plan qua đúng một điểm nối này (`plan_registry.read_plan_index`), nên
        host mode chỉ cần trả đúng ba payload của box là tab Plan chạy được y như Docker:

        * `GET /__box/plans`, `GET /__box/plans/index` → `scan_plans(<workspace>/.plans)`;
        * `GET /__box/plans/content?identity=&version=` → `read_plan(...)`;
        * `POST /__box/plans/review` → `write_review(...)` (bản hiển thị; sổ duyệt của harness vẫn
          là nguồn chân lý).

        Đường chưa có ⇒ `HostRequestUnsupported`. Lỗi của bộ đọc giữ nguyên `status_code`/
        `public_message` để tầng HTTP trả đúng mã, KHÔNG nuốt thành "rỗng".
        """
        from urllib.parse import parse_qs, urlsplit

        from . import host_plans

        parsed = urlsplit(str(path or ''))
        route = parsed.path.rstrip('/') or '/'
        query = parse_qs(parsed.query)
        if route in ('/__box/plans', '/__box/plans/index'):
            if body is not None:
                raise HostRequestUnsupported(route)
            return await asyncio.to_thread(host_plans.plan_manifest, self.workspace)
        if route == '/__box/plans/content':
            if body is not None:
                raise HostRequestUnsupported(route)
            return await asyncio.to_thread(host_plans.plan_document, self.workspace,
                                           query.get('identity', [''])[0], query.get('version', [''])[0])
        if route == '/__box/plans/review':
            payload = body if isinstance(body, dict) else {}
            return await asyncio.to_thread(host_plans.write_plan_review, self.workspace,
                                           payload.get('identity'), payload.get('decision'),
                                           payload.get('note', ''), payload.get('version'))
        raise HostRequestUnsupported(route)

    # -- hợp đồng ------------------------------------------------------------

    async def execute(self, name, args, session, turn=None, step=None, tool_call_id=None, root=None):
        """Cùng hợp đồng `SandboxExecutor.execute`: trả dict, KHÔNG ném vì công cụ chưa hỗ trợ."""
        name = str(name or '')
        args = args if isinstance(args, dict) else {}
        if name not in HOST_TOOLS:
            return unsupported_result(name)
        # `__target` là kênh NỘI BỘ do executor tự gắn để `resource_key` thấy đích đã phân giải.
        # Model gửi kèm khoá này là giả mạo: nó sẽ khiến thẻ duyệt và `resource_key` nói về một đích
        # khác với đích thật sự bị chạm vào (ví dụ xin quyền theo `cua:app:notepad` rồi mở Chrome).
        # Bỏ giá trị đi vào, chỉ nhận giá trị do chính `_plan_target` tạo ra.
        if '__target' in args:
            args = {key: value for key, value in args.items() if key != '__target'}
        cua_plan = None
        if name in CUA_TOOLS:
            # Đích CUA được phân giải TRƯỚC khi hỏi quyền: thẻ duyệt phải nói đúng cửa sổ/app mà
            # lời gọi sắp chạm vào, và `resource_key` nhờ đó hẹp theo đích thay vì theo cả phiên.
            cua_plan, failure = self._plan_target(args, session)
            if failure is not None:
                return failure
            if cua_plan.get('target') is not None:
                args = dict(args, __target=cua_plan['target'])
        decision = self.policy.decide(name, args, cwd=self._cwd(root), session_id=session)
        if decision.outcome == permissions_module.OUTCOME_DENY:
            return error_result(PERMISSION_DENIED_CODE, decision.reason or 'bị chính sách quyền từ chối',
                                rule=decision.rule, layer=decision.layer)
        if decision.outcome == permissions_module.OUTCOME_ASK:
            verdict = await self._ask(name, args, decision, session)
            if verdict == 'deny':
                if self.policy.note_denial(session):
                    breaker = self.policy.breaker_decision()
                    return error_result(APPROVAL_DENIAL_BREAKER_CODE, breaker.reason)
                return error_result(PERMISSION_DENIED_CODE,
                                    decision.reason or 'người dùng đã từ chối lời gọi này')
            self.policy.note_approval(session)
            # Nhóm "luôn hỏi" (`guarded:`) là một lần cho một lần: không ghi nhớ phiên, không lưu luật.
            if not _is_guarded(decision):
                if verdict == 'allow_app':
                    # "Theo app này" nhớ theo ỨNG DỤNG, không theo cửa sổ vừa phân giải: cửa sổ đóng
                    # rồi mở lại (pid khác) vẫn phải khớp, nếu không lựa chọn này vô nghĩa.
                    app = cua_app_hint(args)
                    key_args = {'app': app} if app else args
                    key = self.policy.session_key(name, key_args, cwd=self._cwd(root),
                                                  session_id=session)
                    self.policy.remember(key, permissions_module.allow('', 'user'), 'session')
                else:
                    key = self.policy.session_key(name, args, cwd=self._cwd(root), session_id=session)
                    if verdict == 'allow_session':
                        self.policy.remember(key, permissions_module.allow('', 'user'), 'session')
                    elif verdict == 'allow_always':
                        self.policy.remember(key, permissions_module.allow('', 'user'), 'session')
                        self.policy.save_rule(name, args, actor='user', session_id=session)
        try:
            if name == 'file_read':
                return self._file_read(args, root=root)
            if name == 'file_write':
                return self._file_write(args, root=root)
            if name == 'file_edit_block':
                return self._file_edit_block(args, root=root)
            if name == 'codebase_glob':
                return self._codebase_glob(args, root=root)
            if name == 'codebase_grep':
                return self._codebase_grep(args, root=root)
            if name == 'terminal_exec':
                return await self._terminal_exec(args, session, root=root)
            if name in CUA_TOOLS:
                return await self._cua(name, args, session, cua_plan)
        except _PathEscape as exc:
            return error_result(PATH_ESCAPE_CODE, str(exc))
        except FileNotFoundError as exc:
            return error_result('FILE_NOT_FOUND', 'không tìm thấy: %s' % exc)
        except PermissionError as exc:
            return error_result('FILE_PERMISSION_DENIED', 'hệ điều hành từ chối: %s' % exc)
        except ValueError as exc:
            return error_result('TOOL_ARGUMENT_INVALID', str(exc))
        except Exception as exc:                      # phòng thủ: một công cụ không được giết lượt
            return error_result('HOST_TOOL_FAILED', '%s: %s' % (type(exc).__name__, exc))
        return unsupported_result(name)

    # -- CUA: chụp màn hình, soi phần tử, tiêm input (H5–H7) ------------------

    async def _cua(self, name, args, session, plan=None):
        """Cổng chung của mọi công cụ CUA: lease trước, rồi mới đọc/tiêm.

        Ba tầng phòng thủ, theo thứ tự: (1) `DesktopControl` phải tồn tại; (2) lease phải thuộc
        agent — người dùng chạm chuột/phím là quyền về tay người ngay; (3) với công cụ tiêm input,
        mutex liên tiến trình + `fence()` ngay trước khi gửi. Chỉ tầng (2) là đủ cho hai công cụ
        chỉ đọc, vì chúng không đổi trạng thái máy.
        """
        if self.desktop is None:
            return error_result(CUA_UNAVAILABLE_CODE,
                                'host mode chưa bật điều khiển desktop (thiếu DesktopControl)')
        if self._load_capture() is None or self._desktop_platform() is None:
            return error_result(UNSUPPORTED_CODE,
                                'máy này chưa có nền tảng desktop điều khiển được '
                                '(Windows, hoặc Linux có X11)')
        self.prepare()
        granted, state, _error = self.desktop.agent_lease('agent gọi %s' % name)
        if not granted:
            snapshot = self.desktop.snapshot() or {}
            holder = snapshot.get('holder') or (state if isinstance(state, str) else 'human')
            self._overlay_pause('human_has_control')
            return error_result(HUMAN_HAS_CONTROL_CODE,
                                'người dùng đang điều khiển máy — agent chưa có quyền, '
                                'không gửi thao tác nào', holder=holder)
        self._overlay_resume()
        if name == 'inspect_element':
            return self._inspect_element(args)
        # Đích đã phân giải trước khi hỏi quyền (nếu có) được dùng lại; nếu lúc đó chưa xác định
        # được vì app chưa mở, giờ mới mở rồi phân giải lại — quyền đã được duyệt ở bước trên.
        target, source, failure = await self._target_for_call(args, session, plan)
        if failure is not None:
            return failure
        if source == 'agent':
            # Model tự chọn đích: ghi vào sổ phiên để panel hiện ra ngay (chỉ khi giá trị đổi).
            cua_target_module.apply_agent_target(self.targets, session, target, source)
        if name == 'computer_screen_capture':
            return self._capture_screen(args, session, target, source)
        return await self._computer_use(args, session, target, source)

    # -- đích CUA theo phiên: chọn cửa sổ / cả máy ---------------------------

    def window_list(self, *, include_minimized=True):
        """Cửa sổ cấp cao nhất để phân giải đích. Nền tảng không đọc được ⇒ danh sách rỗng.

        `include_minimized=True` cho đường PHÂN GIẢI: cửa sổ đang thu nhỏ vẫn là một đích hợp lệ
        (`capture_window`/`SendInput` tự đưa nó lên trước), nhưng danh sách cho panel gọi với
        `False` để người dùng chỉ thấy thứ họ nhìn thấy được.
        """
        capture = self.desktop_capture()
        if capture is None:
            return []
        try:
            return capture.list_windows(platform=self._desktop_platform(),
                                        include_minimized=include_minimized)
        except Exception:
            return []

    def desktop_capture(self):
        """Mô-đun chụp của nền tảng đang chạy (Windows: GDI; Linux: X11), hoặc `None`.

        Điểm nối công khai cho tầng route (`machine_router`) — route phải dùng **cùng** nền tảng với
        executor, nếu không panel sẽ chụp bằng một nền tảng khác với thứ agent đang điều khiển.
        """
        return self._load_capture()

    def desktop_platform(self):
        """Đối tượng nền tảng desktop đang dùng, hoặc `None` khi máy không có nền tảng nào."""
        return self._desktop_platform()

    def session_target(self, session):
        """Đích người dùng/model đã chọn cho phiên, hoặc `None`."""
        if self.targets is None or not session:
            return None
        return self.targets.read(session)

    def _plan_target(self, args, session):
        """→ `({'target': …, 'source': …}, None)` hoặc `(None, payload_lỗi)` cho bước HỎI QUYỀN.

        Chỉ đọc: không mở ứng dụng, không ghi sổ phiên. Một app chưa mở mà MỞ ĐƯỢC thì không phải
        lỗi ở bước này — thẻ duyệt vẫn phải hiện để người dùng quyết định, việc mở xảy ra sau khi
        duyệt (`_target_for_call`).
        """
        target, source, failure = self._resolve_target(args, session)
        if failure is not None:
            # CHỈ "không thấy cửa sổ nào của app" mới được coi là "sẽ mở sau khi duyệt". Nhiều cửa sổ
            # cùng khớp (`TARGET_AMBIGUOUS`) là câu hỏi cho model, không phải lý do mở thêm một bản sao.
            if failure.get('reason') == 'not_found' and self._launchable_app(args):
                return {'target': None, 'source': '', 'launch': self._launchable_app(args)}, None
            return None, failure
        return {'target': target, 'source': source, 'launch': ''}, None

    def _resolve_target(self, args, session):
        """→ `(target, source, payload_lỗi)`. Không chạm input, không mở ứng dụng."""
        windows = self.window_list()
        try:
            target, source = cua_target_module.resolve(args, self.session_target(session), windows,
                                                       self.policy.scope_value())
        except cua_target_module.TargetError as exc:
            return None, '', error_result(exc.code, exc.message, **exc.details)
        return target, source, None

    async def _target_for_call(self, args, session, plan=None):
        """Đích THẬT SỰ dùng cho lời gọi này, mở ứng dụng nếu cần. `(target, source, lỗi)`."""
        plan = plan or {}
        planned = plan.get('target')
        if planned is not None:
            return planned, plan.get('source', ''), None
        app = plan.get('launch') or self._launchable_app(args)
        if app:
            target, failure = await self._launch_and_wait(app)
            if failure is not None:
                return None, '', failure
            return target, 'agent', None
        target, source, failure = self._resolve_target(args, session)
        return target, source, failure

    def _launchable_app(self, args):
        """Tên ứng dụng ĐƯỢC PHÉP mở cho lời gọi này, hoặc `''`.

        Ba điều kiện, theo §7.2: phạm vi quyền là `machine`, folder dự án đã được người dùng xác
        nhận tin cậy, và tên app là một tên tệp đơn giản — không đường dẫn, không ký tự điều khiển
        shell. Mở ứng dụng là quyền của "cả máy"; folder chưa tin cậy thì agent không tự mở gì.

        Điều kiện nền tảng hỏi thẳng nền tảng desktop (`launch_app`) chứ không so `sys.platform`:
        Windows mở bằng `ShellExecuteW`, Linux mở bằng `execv` trong session riêng.
        """
        if not self.trusted:
            return ''
        platform = self._desktop_platform()
        if platform is None or getattr(platform, 'launch_app', None) is None:
            return ''
        if not cua_target_module.scope_allows_machine(self.policy.scope_value()):
            return ''
        app = str((args or {}).get('app') or '').strip()
        if not app or not re.fullmatch(r'[A-Za-z0-9._+-]{1,64}', app):
            return ''
        return app

    async def _launch_and_wait(self, app):
        """Mở `app` rồi chờ cửa sổ của nó (≤ `LAUNCH_TIMEOUT_SEC`). `(target, lỗi)`."""
        platform = self._desktop_platform()
        launcher = getattr(platform, 'launch_app', None)
        if launcher is None:
            return None, error_result(CUA_UNAVAILABLE_CODE, 'nền tảng không mở được ứng dụng')
        try:
            launcher(app)
        except Exception as exc:
            code = getattr(exc, 'code', None) or LAUNCH_FAILED_CODE
            return None, error_result(code, 'không mở được `%s`: %s' % (app, exc), app=app)
        deadline = time.monotonic() + LAUNCH_TIMEOUT_SEC
        while True:
            try:
                entry = cua_target_module.match_window(self.window_list(), app=app)
            except cua_target_module.TargetError:
                entry = None
            if entry is not None:
                return entry, None
            if time.monotonic() >= deadline:
                return None, error_result(TARGET_UNKNOWN_CODE,
                                          'đã mở `%s` nhưng chưa thấy cửa sổ nào của nó' % app,
                                          reason='launch_timeout', app=app)
            await asyncio.sleep(0.25)

    # -- viền báo vùng đang bị điều khiển ------------------------------------

    def _overlay_note(self, window):
        if self.overlay is not None and window is not None:
            self.overlay.note(window)

    def _screen_window(self):
        """Cửa sổ tổng hợp phủ toàn màn hình ảo cho đích CUA "cả máy", hoặc `None`.

        Đích "cả máy" cũng phải có viền (chủ nhà nói "CUA **máy** hoặc app"), nhưng nó không có
        `hwnd` nào để bám. Dùng `hwnd = 0` (⇒ `snapshot()['windowId']` là `None`) và hộp màn hình ảo
        làm vùng viền. Đọc kích thước hỏng ⇒ trả `None`: viền là tính năng phụ, KHÔNG được làm hỏng
        kết quả chụp.
        """
        try:
            platform = self._desktop_platform()
            bounds = platform.virtual_screen_bounds() if platform is not None else None
        except Exception:
            return None
        try:
            width, height = int(bounds[2]), int(bounds[3])
        except (TypeError, ValueError, IndexError):
            return None
        if width <= 0 or height <= 0:
            return None
        from ..agent_core import cua_overlay as cua_overlay_module

        return cua_overlay_module.screen_window(bounds)

    def _overlay_pause(self, reason):
        if self.overlay is not None:
            self.overlay.pause(reason)

    def _overlay_resume(self):
        if self.overlay is not None:
            self.overlay.resume()

    # ``inspect_element`` — chỉ đọc, không cần mutex input.
    def _inspect_element(self, args):
        from ..agent_core import inspect_host
        try:
            x, y = int(args.get('x')), int(args.get('y'))
        except (TypeError, ValueError):
            return error_result('TOOL_ARGUMENT_INVALID', 'cần toạ độ nguyên (x, y)')
        try:
            payload = inspect_host.inspect_element(x, y, platform=self._desktop_platform())
        except Exception as exc:
            code = getattr(exc, 'code', None) or 'INSPECT_FAILED'
            return error_result(code, str(exc))
        return payload if isinstance(payload, dict) else {'content': str(payload)}

    # ``computer_screen_capture`` — cùng khuôn payload với box (`SandboxExecutor`), để tầng trên
    # không phải biết ảnh đến từ đâu.
    def _capture_screen(self, args, session, target=None, source=''):
        capture_module = self._load_capture()
        if capture_module is None:
            return error_result(CUA_UNAVAILABLE_CODE, 'máy này không có mô-đun chụp màn hình cho nền tảng đang chạy')
        payload_target = {'kind': 'screen'}
        window = None
        # `_cua` luôn đưa đích ĐÃ phân giải xuống đây (windowId → app/window → đích phiên → mặc định),
        # nên `windowId` trong args chỉ có thể lặp lại đúng giá trị đó. Một nguồn sự thật duy nhất.
        raw_window = target.get('windowId') if cua_target_module.is_window(target) else None
        if raw_window not in (None, ''):
            try:
                window = self._window_for(int(raw_window))
            except (TypeError, ValueError):
                window = None
            if window is None:
                return error_result(TARGET_UNKNOWN_CODE, 'không thấy cửa sổ %s' % raw_window,
                                    reason='window_gone')
            reused = self._window_reused(target, window, raw_window)
            if reused is not None:
                return reused
            payload_target = {'kind': 'window', 'windowId': int(raw_window)}
        try:
            win_platform = self._desktop_platform()
            shot = (capture_module.capture_window(int(raw_window), platform=win_platform)
                    if window is not None
                    else capture_module.capture_screen(platform=win_platform))
            data = capture_module.encode_png(shot)
        except Exception as exc:
            code = getattr(exc, 'code', None) or 'CAPTURE_FAILED'
            return error_result(code, str(exc))
        dimensions = (int(shot.width), int(shot.height))
        # Gốc của ảnh trên màn hình ảo (toạ độ vật lý). Cửa sổ có thể nằm ở màn hình phụ với gốc âm;
        # panel cần gốc này để đặt viền/điểm soi đúng chỗ trên ảnh chụp.
        bounds = getattr(shot, 'bounds', None)
        origin = {'x': int(bounds[0]), 'y': int(bounds[1])} if bounds else {'x': 0, 'y': 0}
        payload = {
            'content': 'Host screenshot %dx%d' % dimensions,
            'image': base64.b64encode(data).decode('ascii'),
            'mime': 'image/png',
            'dimensions': dimensions,
            'target': payload_target,
            'captureOrigin': origin,
            'captureSize': {'width': dimensions[0], 'height': dimensions[1]},
            'sha256': sha256_of(data),
            'label': {'integrity': 'khong_tin_duoc', 'confidentiality': 'noi_bo',
                      'source_kind': 'screen_capture',
                      'source_uri': 'screen://capture/%s' % (payload_target.get('windowId') or 'screen'),
                      'tool_name': 'computer_screen_capture', 'content_hash': sha256_of(data)},
        }
        if cua_target_module.is_machine(target):
            # Đích "cả máy": ảnh là toàn bộ màn hình ảo. `target` giữ từ vựng của box
            # (`screen`/`window` — hợp đồng `CAPTURE_TARGET_KINDS`); đích CUA nói riêng ở `cuaTarget`
            # để hai hợp đồng không đè lên nhau trong cùng một khoá.
            payload['cuaTarget'] = {'kind': 'machine'}
        if source:
            payload['resolvedFrom'] = source
        if window is not None:
            payload['window'] = cua_target_module.window_entry(window)
            self._overlay_note(window)
        elif cua_target_module.is_machine(target):
            # Đích "cả máy": viền phủ toàn màn hình ảo qua cửa sổ tổng hợp (J0.6). `_screen_window()`
            # đã tự nuốt lỗi đọc kích thước màn hình nên nhánh này không bao giờ làm hỏng ảnh chụp.
            self._overlay_note(self._screen_window())
        if shot.occluded:
            payload['occluded'] = True
        caption = args.get('caption')
        if isinstance(caption, str) and caption.strip():
            payload['caption'] = caption.strip()[:200]
        try:
            target_dir = Path(self.artifacts_dir) / 'captures'
            target_dir.mkdir(parents=True, exist_ok=True)
            path = target_dir / self._capture_name(payload_target, session)
            path.write_bytes(data)
            payload['artifact'] = str(path)
        except Exception as exc:            # ảnh vẫn dùng được dù không ghi được tệp
            payload['artifactError'] = '%s: %s' % (type(exc).__name__, exc)
        return payload

    def _capture_name(self, target, session):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        suffix = '-%s' % target.get('windowId') if target.get('windowId') else ''
        prefix = _slug(session)[:24] if session else 'host'
        return '%s-capture-%s%s.png' % (prefix, stamp, suffix)

    def _desktop_family(self):
        """``'windows'`` | ``'x11'`` — họ nền tảng desktop của máy đang chạy.

        Hỏi `self.platform` (chuỗi `'win32'`/`'posix'`, đã tách khỏi `sys.platform` đúng để test bơm
        được nền tảng giả) chứ không hỏi `sys.platform`: máy chạy test là Linux nhưng bài test dựng
        một host Windows giả, và chính chuỗi đó đã là câu trả lời cho "máy này có phải Windows".
        """
        return 'windows' if self.platform == 'win32' else 'x11'

    def _load_capture(self):
        """Mô-đun chụp của nền tảng đang chạy — Windows: GDI; Linux: X11 + ImageMagick.

        `None` nghĩa là máy này không chụp được: chỗ gọi trả `CUA_UNAVAILABLE`/`UNSUPPORTED`, không
        ném. Cùng một cái tên cho cả hai nền tảng để `_capture_screen` không phải rẽ nhánh.
        """
        if self._capture_module is not None:
            return self._capture_module
        try:
            if self._desktop_family() == 'windows':
                from .win import capture as platform_capture
            else:
                from .x11 import capture as platform_capture
        except Exception:
            return None
        self._capture_module = platform_capture
        return platform_capture

    # ``computer_use`` — tiêm input thật, có lease + mutex + fence.
    async def _computer_use(self, args, session, target=None, source=''):
        input_module = self._load_input()
        if input_module is None:
            return error_result(CUA_UNAVAILABLE_CODE, 'máy này không có mô-đun tiêm input cho nền tảng đang chạy')
        action = str(args.get('action') or '').strip().lower()
        if action not in CUA_ACTIONS:
            return error_result(UNSUPPORTED_ACTION_CODE,
                                'hành động %r chưa có trên host (nhận: %s)'
                                % (action or '', ', '.join(CUA_ACTIONS)))
        window, code, why = self._input_target(args, target)
        if window is None:
            return error_result(code, 'không xác định được cửa sổ đích cho %s' % action,
                                reason=why or None)
        hwnd = int(getattr(window, 'hwnd', 0) or 0)
        token, code = self.desktop.begin_action('computer_use:%s' % action, {'windowId': hwnd})
        if token is None:
            return error_result(code, 'không lấy được quyền điều khiển desktop')
        try:
            stale = self.desktop.fence(token)
            if stale:
                return error_result(stale, 'quyền điều khiển đã đổi tay — thao tác bị huỷ')
            outcome = self._send_input(input_module, action, args, window,
                                       pinned=bool(cua_target_module.is_window(target)))
        except Exception as exc:
            self.desktop.end_action(token, effect='failed', verified=False, route='send_input',
                                    note='%s: %s' % (type(exc).__name__, exc))
            code = getattr(exc, 'code', None) or 'INPUT_FAILED'
            return error_result(code, str(exc))
        result = self.desktop.end_action(token, effect='unverifiable', verified=None,
                                         route='send_input', note=action)
        self._overlay_note(window)
        payload = {'content': 'Host input %s → window %s' % (action, hwnd)}
        if isinstance(outcome, dict):
            payload.update(outcome)
        payload.update({'leaseEpoch': result.get('lease_epoch'), 'effect': result.get('effect'),
                        'verified': result.get('verified')})
        payload['window'] = cua_target_module.window_entry(window)
        if source:
            payload['resolvedFrom'] = source
        return payload

    def _send_input(self, input_module, action, args, window, *, pinned=True):
        """Gửi một hành động qua mô-đun input của nền tảng đang chạy.

        ``pinned`` cho biết đích của phiên là **một cửa sổ đã chọn**. Cú kéo cần biết điều đó: đích
        là một cửa sổ thì cả điểm đầu lẫn điểm cuối phải nằm trong cửa sổ đó, còn đích là **cả máy**
        thì kéo từ cửa sổ này sang cửa sổ khác là việc hợp lệ (thả tệp sang ứng dụng khác).
        """
        win_platform = self._desktop_platform()
        if action == 'type':
            return input_module.type_text(str(args.get('text') or ''), window=window,
                                          platform=win_platform)
        if action == 'key':
            modifiers = args.get('modifiers') or args.get('keys') or ()
            if isinstance(modifiers, str):
                modifiers = [part for part in re.split(r'[+,]', modifiers) if part]
            return input_module.press_key(str(args.get('key') or ''), modifiers=tuple(modifiers),
                                          window=window, platform=win_platform)
        if action == 'stroke':
            # `stroke` đi theo CẢ danh sách điểm, nên nó không cần một cặp (x, y) mở đầu — nhưng nó
            # là một cú kéo nhiều điểm, nên nó nhận cùng chốt điểm cuối như `drag`.
            return self._gesture(input_module, 'stroke', window=window, points=args.get('path') or (),
                                 button=self._button_arg(args), guard_end=pinned,
                                 platform=win_platform)
        try:
            x, y = int(args.get('x')), int(args.get('y'))
        except (TypeError, ValueError):
            raise ValueError('cần toạ độ nguyên (x, y) cho %s' % action)
        if action == 'scroll':
            return self._gesture(input_module, 'scroll', x, y, window=window,
                                 direction=str(args.get('direction') or 'down').strip().lower(),
                                 steps=args.get('steps') or None, platform=win_platform)
        if action == 'drag':
            return self._gesture(input_module, 'drag', x, y, window=window,
                                 to_x=self._int_arg(args, 'toX', 'cần toạ độ đích (toX, toY)'),
                                 to_y=self._int_arg(args, 'toY', 'cần toạ độ đích (toX, toY)'),
                                 button=self._button_arg(args), steps=args.get('steps') or None,
                                 guard_end=pinned, platform=win_platform)
        if action == 'hold':
            return self._gesture(input_module, 'hold', x, y, window=window,
                                 button=self._button_arg(args),
                                 seconds=args.get('seconds') or None, platform=win_platform)
        button = {'click': 'left', 'double_click': 'left', 'right_click': 'right',
                  'middle_click': 'middle'}[action]
        outcome = input_module.click(x, y, window=window, button=button, platform=win_platform)
        if action == 'double_click':
            outcome = input_module.click(x, y, window=window, button=button, platform=win_platform)
        return outcome

    def _gesture(self, input_module, name, *args, **kwargs):
        """Gọi một thao tác cử chỉ (cuộn/kéo/giữ/vẽ) — thiếu thì nói rõ, không vỡ bằng `AttributeError`.

        Hai mô-đun của `_load_input` hiện có đủ bốn thao tác, nên nhánh dưới chỉ chạy khi thêm một
        nền tảng mới còn thiếu thao tác: lúc đó trả `UNSUPPORTED_ACTION` kèm tên nền tảng, để chỗ gỡ
        lỗi biết là máy không làm được chứ không phải tham số sai.
        """
        action = getattr(input_module, name, None)
        if action is None:
            raise PlatformError(
                UNSUPPORTED_ACTION_CODE,
                'nền tảng %s chưa có thao tác `%s`.' % (self._desktop_family(), name),
            )
        return action(*args, **kwargs)

    @staticmethod
    def _int_arg(args, key, message):
        try:
            return int(args.get(key))
        except (TypeError, ValueError):
            raise ValueError(message)

    @staticmethod
    def _button_arg(args):
        return str(args.get('button') or 'left').strip().lower()

    def _load_input(self):
        """Mô-đun tiêm input của nền tảng đang chạy — Windows: SendInput; Linux: XTEST."""
        try:
            if self._desktop_family() == 'windows':
                from .win import input as platform_input
            else:
                from .x11 import input as platform_input
        except Exception:
            return None
        return platform_input

    def _window_for(self, hwnd):
        """`WindowInfo` của một hwnd, hoặc `None`. Nền tảng ném lỗi ⇒ coi như không có cửa sổ."""
        platform = self._desktop_platform()
        describe = getattr(platform, 'describe_window', None)
        if describe is None:
            return None
        try:
            return describe(int(hwnd))
        except Exception:
            return None

    def _target_pid_ok(self, target, window):
        """Cửa sổ này có đúng là tiến trình mà đích đã chốt không?

        `verify_window` chỉ chạy TRƯỚC thẻ duyệt. Giữa lúc thẻ còn mở và lúc gửi input, cửa sổ có
        thể đóng rồi hwnd được cấp cho tiến trình khác — lúc đó `describe_window` vẫn trả một cửa sổ
        hợp lệ và input sẽ đi sai chỗ. Nên phải soát `pid` ngay trước khi chạm vào cửa sổ.
        """
        pid = cua_target_module.as_int((target or {}).get('pid'))
        if not pid or window is None:
            return True
        live = getattr(window, 'pid', None)
        return live is None or int(live) == pid

    def _window_reused(self, target, window, raw_window):
        """Lỗi `TARGET_UNKNOWN` khi hwnd đã đổi chủ, hoặc `None` khi còn đúng."""
        if self._target_pid_ok(target, window):
            return None
        return error_result(TARGET_UNKNOWN_CODE, 'cửa sổ %s đã đổi chủ; chọn lại đích' % raw_window,
                            reason='window_reused')

    def _input_target(self, args, target=None):
        """Cửa sổ đích: `windowId` model đưa → ĐÍCH PHIÊN (cửa sổ đã chọn) → cửa sổ chứa điểm (x, y)
        → cửa sổ đang hoạt động.

        Đích "cả máy" cố ý KHÔNG ghim một cửa sổ: nó giữ nguyên hành vi cũ — điểm (x, y) quyết định
        cửa sổ nào, `type`/`key` đi vào cửa sổ đang hoạt động. Chốt cuối vẫn phải qua
        `check_preconditions` của tầng input.

        Trả `(window, code, reason)`: `reason` nói VÌ SAO không có cửa sổ, để chỗ gọi phân biệt được
        "cửa sổ đã đóng" với "hwnd đã đổi chủ" — hai chuyện khác nhau với người đang gỡ lỗi.
        """
        raw_window = args.get('windowId') if 'windowId' in args else (args.get('target') or {}).get('windowId')
        if raw_window not in (None, ''):
            try:
                window = self._window_for(int(raw_window))
            except (TypeError, ValueError):
                window = None
            return (window, '', '') if window is not None else (None, TARGET_UNKNOWN_CODE, 'window_gone')
        if cua_target_module.is_window(target):
            # Cửa sổ người dùng đã chọn cho phiên: MỌI thao tác đi vào đó, kể cả `type`/`key` không
            # kèm toạ độ — nếu không, "đích theo phiên" chỉ đúng với một nửa công cụ.
            window = self._window_for(int(target.get('windowId')))
            if window is None:
                return None, TARGET_UNKNOWN_CODE, 'window_gone'
            if not self._target_pid_ok(target, window):
                return None, TARGET_UNKNOWN_CODE, 'window_reused'
            return window, '', ''
        if args.get('x') is None or args.get('y') is None:
            platform = self._desktop_platform()
            foreground = getattr(platform, 'get_foreground_window', None)
            hwnd = foreground() if foreground is not None else None
            window = self._window_for(hwnd) if hwnd else None
            return (window, '', '') if window is not None else (None, TARGET_UNKNOWN_CODE, 'window_gone')
        try:
            x, y = int(args.get('x')), int(args.get('y'))
        except (TypeError, ValueError):
            return None, TARGET_UNKNOWN_CODE, 'point_invalid'
        platform = self._desktop_platform()
        window = None
        finder = getattr(platform, 'window_from_point', None)
        if finder is not None:
            try:
                hwnd = finder(x, y)
            except Exception:
                hwnd = None
            if hwnd:
                window = self._window_for(hwnd)
        return (window, '', '') if window is not None else (None, TARGET_UNKNOWN_CODE, 'window_gone')

    def _desktop_platform(self):
        """Nền tảng desktop đang dùng: của `DesktopControl` nếu có, không thì tự dựng theo hệ điều hành.

        Đường dự phòng quan trọng cho các lời gọi CHỈ ĐỌC (`window_list`, `_window_for`) khi chưa có
        `DesktopControl` — chúng cần một đối tượng nền tảng thật, không cần lease.
        """
        if self.desktop is not None and getattr(self.desktop, 'platform', None) is not None:
            return self.desktop.platform
        try:
            if self._desktop_family() == 'windows':
                from .win import windows_platform

                return windows_platform.get_platform()
            from .x11 import platform as x11_platform

            return x11_platform.get_platform()
        except Exception:
            return None

    async def cleanup(self, session):
        """Dừng tiến trình còn chạy của phiên (tương ứng `SandboxExecutor.cleanup`)."""
        # Viền báo vùng đang bị điều khiển phải tắt cùng phiên: để lại một vòng xanh quanh cửa sổ
        # sau khi phiên kết thúc là nói dối người dùng rằng agent còn đang làm việc ở đó.
        if self.overlay is not None:
            self.overlay.hide('session_cleanup')
        process = self.processes.pop(session, None)
        if process is not None and process.returncode is None:
            _kill_group(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    # -- quyền ---------------------------------------------------------------

    async def _ask(self, name, args, decision, session):
        if self.approver is None:
            return 'deny'
        try:
            # `session` đi kèm để bề mặt duyệt biết thẻ này thuộc phiên nào (nhiều phiên cùng folder).
            verdict = self.approver(name, args, decision, session)
            if asyncio.iscoroutine(verdict):
                verdict = await verdict
        except Exception:
            return 'deny'
        return verdict if verdict in ('allow', 'allow_session', 'allow_always', 'allow_app',
                                      'deny') else 'deny'

    # -- đường dẫn -----------------------------------------------------------

    def _cwd(self, root=None):
        base = self.workspace
        if root:
            try:
                base = self._resolve(root)
            except _PathEscape:
                return str(self.workspace)
        return str(base)

    def _resolve(self, value, *, root=None):
        """Đường dẫn tuyệt đối TRONG workspace. `..` và symlink bị chặn bằng `resolve()`."""
        text = str(value or '').strip()
        if not text:
            raise ValueError('PATH_REQUIRED: thiếu `path`')
        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            candidate = Path(self._cwd(root)) / candidate
        try:
            resolved = candidate.resolve()
        except OSError as exc:
            raise ValueError('PATH_INVALID: %s' % exc)
        base = Path(self._cwd(root)).resolve()
        if resolved != base and not resolved.is_relative_to(base):
            raise _PathEscape('đường dẫn `%s` nằm ngoài workspace (`%s`)' % (value, base))
        return resolved

    def _relative(self, target):
        try:
            return target.relative_to(self.workspace).as_posix()
        except ValueError:
            return str(target)

    # -- công cụ tệp ---------------------------------------------------------

    def _file_read(self, args, *, root=None):
        target = self._resolve(args.get('path'), root=root)
        if not target.is_file():
            return error_result('FILE_NOT_FOUND', 'không phải tệp: %s' % args.get('path'))
        return read_file_payload(target, args.get('offset'), args.get('limit'))

    def _write(self, target, content):
        """Ghi tệp + mảnh bằng chứng tối thiểu mà work graph cần (`relativePath`, sha256 hai đầu)."""
        before_digest, _text, _reason = before_write(target)
        existed = target.is_file()
        target.parent.mkdir(parents=True, exist_ok=True)
        raw = content.encode('utf-8')
        target.write_bytes(raw)
        return {
            'relativePath': self._relative(target),
            'sha256Before': before_digest,
            'sha256After': sha256_of(raw),
            'bytesWritten': len(raw),
            'created': not existed,
        }

    def _file_write(self, args, *, root=None):
        target = self._resolve(args.get('path'), root=root)
        content = args.get('content')
        if not isinstance(content, str):
            raise ValueError('CONTENT_REQUIRED: `content` phải là chuỗi')
        evidence = self._write(target, content)
        return {'content': 'Written ' + self._relative(target), **evidence}

    def _file_edit_block(self, args, *, root=None):
        target = self._resolve(args.get('path'), root=root)
        old_text = args.get('old_text')
        new_text = args.get('new_text')
        if not isinstance(old_text, str) or not isinstance(new_text, str):
            raise ValueError('EDIT_ARGUMENTS_REQUIRED: cần `old_text` và `new_text` dạng chuỗi')
        content = target.read_text(encoding='utf-8')
        if not old_text or content.count(old_text) != 1:
            raise ValueError('old_text must match exactly once; read file first')
        evidence = self._write(target, content.replace(old_text, new_text, 1))
        return {'content': 'Updated ' + self._relative(target), **evidence}

    # -- tìm trong mã --------------------------------------------------------

    def _codebase_glob(self, args, *, root=None):
        pattern = args.get('pattern', '**/*')
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError('GLOB_PATTERN_INVALID: pattern must be a non-empty relative glob string, e.g. **/*.py')
        unquoted = re.sub(r'\[[^]]*\]', '', pattern)
        if re.search(r'\{[^{}]*(?:,|\.\.)[^{}]*\}', unquoted):
            raise ValueError('GLOB_PATTERN_INVALID: pattern uses unsupported brace expansion; '
                             'make separate codebase_glob calls, e.g. **/*.py and **/*.ts')
        base = Path(self._cwd(root)).resolve()
        if base != self.workspace and not base.is_relative_to(self.workspace):
            raise _PathEscape('gốc tìm kiếm nằm ngoài workspace')
        found = []
        for item in sorted(base.glob(pattern)):
            if item.is_file() and item.resolve().is_relative_to(self.workspace):
                found.append(item.relative_to(self.workspace).as_posix())
            if len(found) >= GLOB_MAX_RESULTS:
                break
        return {'content': '\n'.join(found)}

    def _codebase_grep(self, args, *, root=None):
        needle = args.get('query')
        if not isinstance(needle, str) or not needle:
            raise ValueError('GREP_QUERY_REQUIRED: cần `query` dạng chuỗi')
        base = Path(self._cwd(root)).resolve()
        results = []
        for item in sorted(base.rglob('*')):
            if not item.is_file() or not item.resolve().is_relative_to(self.workspace):
                continue
            try:
                if item.stat().st_size > GREP_MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            try:
                lines = item.read_text(encoding='utf-8').splitlines()
            except (UnicodeError, PermissionError, OSError):
                continue
            for number, line in enumerate(lines, 1):
                if needle in line:
                    results.append('%s:%d:%s' % (item.relative_to(self.workspace).as_posix(), number,
                                                 line[:300]))
                if len(results) >= GREP_MAX_RESULTS:
                    return {'content': '\n'.join(results)}
        return {'content': '\n'.join(results)}

    # -- lệnh ----------------------------------------------------------------

    def shell_argv(self, command):
        """Đối số tiến trình cho một lệnh. Windows: `pwsh.exe` → `powershell.exe`; POSIX: `/bin/sh -c`."""
        if self.platform == 'win32':
            shell = self._windows_shell()
            return [shell, '-NoProfile', '-NonInteractive', '-OutputFormat', 'Text', '-Command', command]
        return ['/bin/sh', '-c', command]

    def _windows_shell(self):
        for candidate in ('pwsh.exe', 'powershell.exe'):
            for directory in (self.env.get('PATH') or os.environ.get('PATH') or '').split(os.pathsep):
                if directory and (Path(directory) / candidate).is_file():
                    return candidate
            if candidate == 'powershell.exe':
                return candidate
        return 'powershell.exe'

    async def _terminal_exec(self, args, session, *, root=None):
        command = args.get('command')
        if not isinstance(command, str) or not command.strip():
            raise ValueError('COMMAND_REQUIRED: cần `command` dạng chuỗi')
        timeout = min(COMMAND_TIMEOUT_MAX, max(1, read_int_arg(args.get('timeout'), COMMAND_TIMEOUT_DEFAULT)))
        cwd = self._cwd(root)
        process = await asyncio.create_subprocess_exec(
            *self.shell_argv(command), cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL, env=self._child_env(),
            **({'start_new_session': True} if self.platform != 'win32' else {}))
        self.processes[session] = process
        try:
            output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            _kill_group(process)
            await process.wait()
            self.processes.pop(session, None)
            return error_result(COMMAND_TIMEOUT_CODE,
                                'lệnh vượt %d s và đã bị dừng (cả nhóm tiến trình)' % timeout,
                                timeout=timeout)
        finally:
            if self.processes.get(session) is process and process.returncode is not None:
                self.processes.pop(session, None)
        text = output.decode('utf-8', errors='replace')
        artifact = None
        if len(text) > READ_TRUNCATE_ARTIFACT_CHARS:
            artifact = self._spill(text)
        preview = text[:OUTPUT_PREVIEW_CHARS] + ('\n[truncated; see artifact]' if artifact else '')
        if process.returncode != 0:
            # Lỗi phải MANG MÃ (L4): thiếu mã thì `recovery_policy` xếp vào nhánh "chưa biết" và
            # `reflection_hint` gửi cho model câu dành cho lỗi sai tham số — sai việc cần làm.
            return error_result(
                COMMAND_EXIT_NONZERO_CODE,
                'lệnh thoát với mã %d; mã đó cũng nằm ở `exit_code`, đầu ra đầy đủ ở `content`%s' % (
                    process.returncode, ' và tệp đính kèm' if artifact else ''),
                exit_code=process.returncode, content=preview, artifact=artifact)
        return {'content': preview, 'exit_code': process.returncode, 'is_error': False,
                'artifact': artifact}

    def _child_env(self):
        env = dict(self.env if self.env is not None else os.environ)
        env.setdefault('PYTHONIOENCODING', 'utf-8')
        env.setdefault('PYTHONUTF8', '1')
        return env

    def _spill(self, text):
        """Phần output vượt trần nằm ở `.generated_artifacts/tools/` — chỗ UI đọc được (W8.A4.3)."""
        try:
            target = self.artifacts_dir / 'tools' / (uuid.uuid4().hex + '.txt')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding='utf-8')
            return self._relative(target)
        except OSError:
            return None


class _PathEscape(ValueError):
    """Đường dẫn thoát khỏi workspace — một lớp riêng để `execute()` dịch thành mã có cấu trúc."""


def _kill_group(process):
    """Dừng cả NHÓM tiến trình: một lệnh `npm run dev` để lại con cháu nếu chỉ kill cha."""
    if process.returncode is not None:
        return
    try:
        if os.name == 'posix':
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:                                        # pragma: no cover - Windows
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(process.pid)], capture_output=True)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            process.kill()
        except ProcessLookupError:
            pass


def detect_platform():
    """`'win32'` | `'posix'` — tách khỏi `sys.platform` để test bơm được nền tảng giả."""
    return 'win32' if sys.platform.startswith('win') else 'posix'
