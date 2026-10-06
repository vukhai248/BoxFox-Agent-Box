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

from ..agent_core import permissions as permissions_module

#: Mã lỗi cho công cụ v1 chưa có trên host. Có mã để model phân biệt "chưa làm" với "hỏng".
UNSUPPORTED_CODE = 'UNSUPPORTED_IN_HOST_MODE'
PERMISSION_DENIED_CODE = 'PERMISSION_DENIED'
APPROVAL_REQUIRED_CODE = 'APPROVAL_REQUIRED'
APPROVAL_DENIAL_BREAKER_CODE = 'APPROVAL_DENIAL_BREAKER'
PATH_ESCAPE_CODE = 'PATH_OUTSIDE_WORKSPACE'
COMMAND_TIMEOUT_CODE = 'COMMAND_TIMEOUT'

#: Công cụ v1 chạy được trên host. Danh sách này là HỢP ĐỒNG với tài liệu `docs/plan/desktop-host-mode.md`.
HOST_TOOLS = ('file_read', 'codebase_glob', 'codebase_grep', 'file_write', 'file_edit_block',
              'terminal_exec')

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
    payload.update(extra)
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

    def __init__(self, workspace=None, *, policy=None, platform=None, approver=None, env=None,
                 artifacts_dir=None, root=None):
        source = os.environ if env is None else env
        self.env = source
        self.workspace = Path(workspace or source.get('BOXFOX_HOST_WORKSPACE')
                              or Path.home() / 'BoxFox' / 'workspace').expanduser().resolve()
        self.policy = policy if policy is not None else permissions_module.PermissionPolicy(
            str(self.workspace), env=source)
        self.platform = platform or ('win32' if os.name == 'nt' else 'posix')
        #: `approver(tool, args, decision)` ⇒ `'allow'` | `'allow_session'` | `'allow_always'` | `'deny'`.
        #: Không có ⇒ mọi lời gọi cần hỏi đều bị từ chối (fail closed).
        self.approver = approver
        self.root = root
        self.artifacts_dir = Path(artifacts_dir) if artifacts_dir else self.workspace / '.generated_artifacts'
        #: Giữ cùng tên thuộc tính với `SandboxExecutor` để chỗ gọi cũ không phải rẽ nhánh.
        self.visual_lock = asyncio.Lock()
        self.processes = {}      # session ⇒ process group đang chạy (để `cleanup` dừng được)
        self.permission_hook = None   # `api/server.py` gắn hàm ghi audit/thẻ duyệt nếu cần

    # -- hợp đồng ------------------------------------------------------------

    async def execute(self, name, args, session, turn=None, step=None, tool_call_id=None, root=None):
        """Cùng hợp đồng `SandboxExecutor.execute`: trả dict, KHÔNG ném vì công cụ chưa hỗ trợ."""
        name = str(name or '')
        args = args if isinstance(args, dict) else {}
        if name not in HOST_TOOLS:
            return unsupported_result(name)
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
            key = self.policy.session_key(name, args, cwd=self._cwd(root))
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

    async def cleanup(self, session):
        """Dừng tiến trình còn chạy của phiên (tương ứng `SandboxExecutor.cleanup`)."""
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
            verdict = self.approver(name, args, decision)
            if asyncio.iscoroutine(verdict):
                verdict = await verdict
        except Exception:
            return 'deny'
        return verdict if verdict in ('allow', 'allow_session', 'allow_always', 'deny') else 'deny'

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
        return {'content': preview, 'exit_code': process.returncode, 'is_error': process.returncode != 0,
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
