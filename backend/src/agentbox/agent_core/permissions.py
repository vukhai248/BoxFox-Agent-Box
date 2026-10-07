"""Động cơ quyền của host mode — luật `Tool(specifier)`, ba tầng, sàn cứng.

Vì sao mô-đun này tồn tại
------------------------

Ở chế độ Docker, mọi công cụ chạy trong box nên "phạm vi" là cả box: không có gì để hỏi. Host mode
đụng vào **máy thật của chủ nhà**, nên câu hỏi "công cụ này được phép làm gì" trở thành câu hỏi
trung tâm. `docs/plan/desktop-host-mode.md` chốt hợp đồng; mô-đun này là bản thực hiện.

Ba quyết định thiết kế, và lý do:

* **Ngữ pháp luật sao chép Claude Code** (`Tool` hoặc `Tool(specifier)`) — người dùng đã biết nó,
  tài liệu sẵn có, và nó đủ diễn đạt cả đường dẫn (gitignore), lệnh (glob), lẫn domain.
* **Hai trục độc lập** (`scope` × `mode`) đúng như Codex tách `SandboxMode` khỏi `AskForApproval`:
  "toàn máy" và "hỏi hay không hỏi" là hai câu hỏi khác nhau, gộp chúng thành một thang là ngõ cụt.
* **Sàn cứng nằm trong code, không nằm trong tệp cấu hình** — luật `deny` của người dùng có thể bị
  sửa tay, còn một lệnh xoá sạch ổ đĩa thì không được phép "quên". `hardline_reason()` chạy TRƯỚC
  mọi danh sách, kể cả `trusted`.

Thứ tự áp dụng (không đổi): sàn cứng → `deny` → `ask` → `allow` → mặc định theo `mode`/`scope`.
`deny` ở bất kỳ tầng nào cũng thắng `allow` ở mọi tầng; trong CÙNG một danh sách thì khớp đầu tiên thắng.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

MODE_PLAN, MODE_ASK, MODE_AUTO, MODE_TRUSTED = 'plan', 'ask', 'auto', 'trusted'
MODES = (MODE_PLAN, MODE_ASK, MODE_AUTO, MODE_TRUSTED)
MODE_DEFAULT = MODE_ASK

SCOPE_WORKSPACE, SCOPE_MACHINE = 'workspace', 'machine'
SCOPES = (SCOPE_WORKSPACE, SCOPE_MACHINE)
SCOPE_DEFAULT = SCOPE_MACHINE

#: Trục thứ ba (Codex `NetworkAccess`): `restricted` = lệnh ra mạng phải hỏi trước khi chúng được
#: chạy im lặng (`auto`); `enabled` = không hỏi. Đây là DANH SÁCH HỎI, không phải tường lửa.
NETWORK_RESTRICTED, NETWORK_ENABLED = 'restricted', 'enabled'
NETWORKS = (NETWORK_RESTRICTED, NETWORK_ENABLED)
NETWORK_DEFAULT = NETWORK_RESTRICTED

OUTCOME_ALLOW, OUTCOME_ASK, OUTCOME_DENY = 'allow', 'ask', 'deny'

LAYER_MANAGED, LAYER_USER, LAYER_PROJECT, LAYER_PROFILE = 'managed', 'user', 'project', 'profile'
LAYER_ORDER = (LAYER_MANAGED, LAYER_PROFILE, LAYER_USER, LAYER_PROJECT)

#: Công cụ v1 đi qua động cơ quyền. CUA (`computer_use`, `computer_screen_capture`,
#: `inspect_element`) KHÔNG có specifier ở v1 và KHÔNG BAO GIỜ sinh luật vĩnh viễn (§4.7 của kế
#: hoạch) — chúng vẫn đi qua đây để lấy quyết định, nhưng chỉ ở dạng tên trần.
SCOPED_TOOLS = ('file_read', 'file_write', 'file_edit_block', 'terminal_exec', 'web_fetch')
BARE_TOOLS = ('computer_use', 'computer_screen_capture', 'inspect_element')

#: Chế độ nào cho phép nhóm hành động nào. Đây là bảng duy nhất: `decide()` đọc nó, tài liệu và
#: `/api/agent/permissions` cũng đọc nó, nên không có bản sao thứ hai để lệch.
MODE_CAPABILITIES = {
    MODE_PLAN: {'read': True, 'write': False, 'exec': False, 'cua': False},
    MODE_ASK: {'read': True, 'write': 'ask', 'exec': 'ask', 'cua': 'ask'},
    MODE_AUTO: {'read': True, 'write': 'allow', 'exec': 'allow', 'cua': 'ask'},
    MODE_TRUSTED: {'read': True, 'write': 'allow', 'exec': 'allow', 'cua': 'allow'},
}

READ_TOOLS = ('file_read', 'codebase_glob', 'codebase_grep', 'web_fetch')
WRITE_TOOLS = ('file_write', 'file_edit_block')
EXEC_TOOLS = ('terminal_exec',)

#: Tiền tố bị CẤM khi lưu một luật `allow` vĩnh viễn (§3.3.3, rào của Codex + Hermes): một luật
#: như `terminal_exec(powershell -Command *)` không hẹp hơn "cho phép mọi thứ" là bao.
FORBIDDEN_RULE_PREFIXES = (
    'cmd', 'cmd /c', 'cmd.exe', 'powershell', 'powershell -command', 'pwsh', 'pwsh -c',
    'bash', 'bash -c', 'wsl', 'wsl.exe', 'node -e', 'python -c', 'python3 -c',
)

#: Sàn cứng (§3.3.4). Mỗi mục là `(regex, mã)` — regex chạy trên lệnh ĐÃ chuẩn hoá chữ thường và
#: đã bỏ khoảng trắng thừa; mã là thứ hiện cho người dùng và ghi vào audit.
HARDLINE = (
    (r'^format(\.com)?(\s|$)', 'format_drive'),
    (r'^diskpart(\s|$)', 'diskpart'),
    (r'^bcdedit(\s|$)', 'bcdedit'),
    (r'^vssadmin\s+delete\s+shadows', 'delete_shadow_copies'),
    (r'^remove-item\b[^|;]*(-recurse|-r\b)[^|;]*(-force|-f\b)[^|;]*\s[a-z]:\\?(\s|$|\*)', 'delete_drive_root'),
    (r'^remove-item\b[^|;]*(-recurse|-r\b)[^|;]*(-force|-f\b)[^|;]*\s[a-z]:\\windows', 'delete_windows_dir'),
    (r'^(reg\s+add|set-itemproperty|new-itemproperty)[^|;]*(hklm|hkey_local_machine)', 'write_hklm'),
    (r'^shutdown(\.exe)?\s+/(r|s|p|h|fw)', 'shutdown'),
    (r'^set-mppreference[^|;]*-disablerealtimemonitoring', 'disable_defender'),
    (r'^netsh\s+advfirewall\s+set[^|;]*state\s+off', 'disable_firewall'),
    # POSIX: cùng nhóm "xoá cả ổ" như `format`/`diskpart` của Windows. `canonicalize_command` đổi
    # `rm` thành `remove-item` (bảng alias PowerShell), nên mẫu phải nhận CẢ HAI tên.
    (r'^(rm|remove-item)\s+[^|;]*\s/(\s|$|\*)', 'delete_root'),
    (r'^mkfs(\.\w+)?(\s|$)', 'format_filesystem'),
    (r'^dd\b[^|;]*of=/dev/', 'overwrite_device'),
)

#: Nhóm "LUÔN HỎI" (§6.1): chạy được ở mọi chế độ, kể cả `trusted`, và **không bao giờ ghi nhớ** —
#: một lần cho phép là một lần. Đây là các lệnh đổi trạng thái hệ thống hoặc đưa mã lạ vào máy.
GUARDED = (
    (r'\bgit\s+push\b[^|;]*(\s-f(\s|$)|\s--force(-with-lease)?(\s|$))', 'git_force_push'),
    (r'\|\s*(sh|bash|zsh|iex|invoke-expression|powershell|pwsh|cmd)(\.exe)?(\s|$)', 'pipe_to_shell'),
    (r'-encodedcommand\b', 'encoded_command'),
    (r'^reg(\.exe)?\s+(add|delete)\b', 'registry_write'),
    (r'^schtasks(\.exe)?\s+/(create|change|delete)\b', 'scheduled_task'),
    (r'^runas\b', 'runas'),
    (r'^net(\.exe)?\s+(user|localgroup)\b', 'account_change'),
    (r'^(takeown|icacls)(\.exe)?\b[^|;]*\s([a-z]:\\|%windir%|%systemroot%|/etc|/usr|/bin|/boot)',
     'acl_change'),
)

#: Lệnh RA MẠNG (§6.1) — chỉ hỏi khi chế độ sẽ chạy im lặng (`auto`) và trục mạng là `restricted`.
EGRESS = (
    (r'\b(curl|wget|nc|netcat|telnet|ssh|scp|sftp|ftp)\b', 'remote_shell_or_fetch'),
    (r'\b(invoke-webrequest|iwr|invoke-restmethod|irm)\b', 'remote_fetch'),
    (r'\bgit\s+(push|pull|clone|fetch|ls-remote)\b', 'git_remote'),
    (r'\b(npm|pnpm|yarn|bun|pip|pip3|poetry|cargo|go|dotnet|nuget|gem)\s+(install|add|i|ci|get|update|publish|restore)\b',
     'package_install'),
    (r'\bdocker\s+(pull|push|login|run|build)\b', 'container_registry'),
    (r'\b(az|aws|gcloud|gh)\s+(login|auth|configure)\b', 'cloud_login'),
)

#: Fork bomb không có "lệnh con" nào để soi (nó là một khối `:|:&`), nên khớp trên TOÀN VĂN.
FORK_BOMB = re.compile(r':\(\)\s*\{\s*:\|:\s*&?\s*\}\s*;?\s*:')

#: Alias cmdlet PowerShell ⇒ tên đầy đủ. Chỉ những alias PHỔ BIẾN và chỉ những cái đổi nghĩa khi
#: so khớp (`ls` khác `Get-ChildItem` về ngữ nghĩa luật nếu không chuẩn hoá). Bảng nhỏ là cố ý:
#: mỗi dòng thừa là một cách để luật người dùng khớp sai.
POWERSHELL_ALIASES = {
    'ls': 'get-childitem', 'dir': 'get-childitem', 'gci': 'get-childitem',
    'cd': 'set-location', 'sl': 'set-location', 'chdir': 'set-location',
    'cat': 'get-content', 'type': 'get-content', 'gc': 'get-content',
    'cp': 'copy-item', 'copy': 'copy-item', 'cpi': 'copy-item',
    'mv': 'move-item', 'move': 'move-item', 'mi': 'move-item',
    'rm': 'remove-item', 'del': 'remove-item', 'erase': 'remove-item', 'ri': 'remove-item',
    'echo': 'write-output', 'write': 'write-output',
    'ps': 'get-process', 'kill': 'stop-process', 'spps': 'stop-process',
    'sleep': 'start-sleep', 'curl': 'invoke-webrequest', 'wget': 'invoke-webrequest',
    'iwr': 'invoke-webrequest', 'irm': 'invoke-restmethod',
    'ni': 'new-item', 'md': 'new-item', 'mkdir': 'new-item',
    'select': 'select-object', 'where': 'where-object', 'foreach': 'for-eachobject',
    'measure': 'measure-object', 'sort': 'sort-object', 'tee': 'tee-object',
    'gi': 'get-item', 'gp': 'get-itemproperty', 'sp': 'set-itemproperty',
    'gps': 'get-process', 'gv': 'get-variable', 'sv': 'set-variable',
}

#: Toán tử tách lệnh. `&` một mình là toán tử gọi (call operator) trong PowerShell, nhưng cũng là
#: dấu phân tách trong `cmd`; tách ở cả hai nghĩa là hành vi AN TOÀN hơn (một lệnh ghép bị tách sẽ
#: phải khớp từng phần, không phải khớp cả chuỗi).
COMMAND_OPERATORS = ('|', ';', '&&', '||', '&')

#: Wrapper bóc trước khi so khớp: `powershell -Command "npm run build"` phải khớp luật
#: `terminal_exec(npm run *)` chứ không phải trượt rồi rơi vào "hỏi".
_WRAPPER_PATTERNS = (
    re.compile(r'^(?:powershell|pwsh)(?:\.exe)?\s+(?:-[a-z]+\s+)*-command\s+(.*)$', re.I | re.S),
    re.compile(r'^(?:powershell|pwsh)(?:\.exe)?\s+(?:-command|-c)\s+(.*)$', re.I | re.S),
    re.compile(r'^cmd(?:\.exe)?\s+/c\s+(.*)$', re.I | re.S),
    re.compile(r'^bash\s+-c\s+(.*)$', re.I | re.S),
    re.compile(r'^sh\s+-c\s+(.*)$', re.I | re.S),
    re.compile(r'^(?:timeout|nice|nohup)\s+[^&|;]*?\s+(.*)$', re.I | re.S),
)

MAX_SUBCOMMAND_RULES = 5
DENIAL_BREAKER_LIMIT = 3
AUDIT_FILENAME = 'permissions-audit.jsonl'
AUDIT_MAX_CHARS = 2000


@dataclass(frozen=True)
class Decision:
    """Kết quả một lần hỏi động cơ quyền. `layer`/`rule` để UI nói ĐƯỢC vì sao."""

    outcome: str
    reason: str = ''
    rule: str = ''
    layer: str = ''

    @property
    def allowed(self):
        return self.outcome == OUTCOME_ALLOW

    def as_dict(self):
        payload = {'outcome': self.outcome}
        if self.reason:
            payload['reason'] = self.reason
        if self.rule:
            payload['rule'] = self.rule
        if self.layer:
            payload['layer'] = self.layer
        return payload


def allow(rule='', layer='') -> Decision:
    return Decision(OUTCOME_ALLOW, '', rule, layer)


def ask(reason, rule='', layer='') -> Decision:
    return Decision(OUTCOME_ASK, reason, rule, layer)


def deny(reason, rule='', layer='') -> Decision:
    return Decision(OUTCOME_DENY, reason, rule, layer)


# --- Chuẩn hoá lệnh ---------------------------------------------------------

def strip_wrappers(command):
    """Bóc lớp gọi lồng (`powershell -Command …`, `cmd /c …`, `timeout …`) — lặp tới khi hết."""
    text = str(command or '').strip()
    for _ in range(4):
        for pattern in _WRAPPER_PATTERNS:
            match = pattern.match(text)
            if not match:
                continue
            inner = match.group(1).strip()
            # Bỏ cặp nháy/kép bao ngoài mà wrapper để lại.
            if len(inner) >= 2 and inner[0] == inner[-1] and inner[0] in '"\'':
                inner = inner[1:-1].strip()
            if inner and inner != text:
                text = inner
                break
        else:
            break
    return text


def split_commands(command):
    """Tách một dòng lệnh thành các lệnh con theo toán tử shell.

    Không phải một bộ parse PowerShell đầy đủ — cố ý. Mục đích là để một luật `allow` KHÔNG BAO
    GIỜ phê duyệt cả một chuỗi `a; b` chỉ vì `a` khớp: mỗi lệnh con phải khớp riêng.
    """
    text = str(command or '')
    parts, current = [], []
    index, length = 0, len(text)
    while index < length:
        char = text[index]
        if char in ('"', "'"):
            quote, current = char, current + [char]
            index += 1
            while index < length and text[index] != quote:
                current.append(text[index])
                index += 1
            if index < length:
                current.append(text[index])
                index += 1
            continue
        if char in ('|', ';', '&', '\n', '\r'):
            operator = char
            if index + 1 < length and text[index + 1] == char and char in '|&':
                operator = char * 2
                index += 1
            parts.append(''.join(current))
            current = []
            index += 1
            continue
        current.append(char)
        index += 1
    parts.append(''.join(current))
    return [part.strip() for part in parts if part.strip()]


def canonicalize_command(command):
    """Lệnh về dạng dùng để SO KHỚP: bóc wrapper, gộp khoảng trắng, chuẩn hoá alias cmdlet.

    Không đổi nghĩa lệnh — chỉ đổi cách viết. `Get-ChildItem` và `gci` phải khớp cùng một luật,
    nếu không thì luật người dùng dạy hôm nay sẽ trượt vào ngày mai khi model viết tắt.
    """
    text = strip_wrappers(command)
    text = re.sub(r'\s+', ' ', text).strip()
    if not text:
        return ''
    tokens = text.split(' ')
    head = tokens[0]
    lowered = head.lower()
    # Tên có đuôi `.exe`/`.cmd`/`.ps1` vẫn là cùng một lệnh.
    for suffix in ('.exe', '.cmd', '.bat', '.ps1', '.com'):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
            break
    replacement = POWERSHELL_ALIASES.get(lowered)
    if replacement:
        tokens[0] = replacement
    return ' '.join(tokens).strip()


def command_tokens(command):
    """Token của lệnh đã chuẩn hoá, đã bỏ nháy — dùng cho luật glob từng phần."""
    text = canonicalize_command(command)
    return [token.strip('"\'') for token in text.split(' ') if token]


# --- Khớp mẫu ---------------------------------------------------------------

def match_command_pattern(pattern, command):
    """Khớp một specifier lệnh với toàn văn lệnh, sau khi CHUẨN HOÁ CẢ HAI PHÍA.

    Ba dạng, đúng ngữ pháp Claude Code:

    * `ls:*` — hậu tố `:*` tương đương ` *` ở cuối (tiền tố + mọi thứ phía sau);
    * `npm run *` — `*` khớp mọi văn bản kể cả dấu cách;
    * `git status` — khớp chính xác toàn văn.

    Chuẩn hoá cả hai phía là điều kiện để luật viết hôm nay không trượt vào ngày mai: `gci` phải
    khớp `Get-ChildItem`, và `npm run *` phải khớp `npm run build` viết hoa/thường tuỳ ý.
    """
    spec = str(pattern or '').strip()
    if not spec:
        return False
    canonical = canonicalize_command(command).lower()
    if not canonical:
        return False
    if spec.endswith(':*'):
        spec = spec[:-2].strip() + ' *'
    if not spec.endswith('*'):
        return canonical == canonicalize_command(spec).lower()
    prefix = canonicalize_command(spec[:-1].rstrip()).lower()
    return bool(prefix) and (canonical == prefix or canonical.startswith(prefix + ' '))


def match_path_pattern(pattern, path, *, cwd=None, source=None, home=None):
    """Khớp specifier đường dẫn kiểu gitignore với bốn neo (§3.3.1).

    | Neo | Nghĩa |
    |---|---|
    | `//abs` | đường dẫn tuyệt đối |
    | `~/path` | trong thư mục nhà |
    | `/path` | tính từ GỐC của nguồn (workspace đang mở) |
    | `path` / `./path` | tính từ `cwd` |

    Đường dẫn của lời gọi được `_collapse()` (bỏ `.`/`..`, gộp `/`) TRƯỚC khi so, nên `..` và
    symlink không lách qua được; mẫu cũng đi qua cùng hàm đó, nên hai phía luôn cùng một dạng.
    """
    spec = str(pattern or '').strip().replace('\\', '/')
    raw = str(path or '').strip().replace('\\', '/')
    if not spec or not raw:
        return False
    candidate = _collapse(_expand_home(raw, home))
    anchored = []
    if spec.startswith('//'):
        anchored.append(spec[1:])
    elif spec.startswith('~'):
        anchored.append(_expand_home(spec, home))
    elif spec.startswith('/'):
        base = str(source or '').strip().replace('\\', '/').rstrip('/')
        if base:
            anchored.append(base + spec)
        anchored.append(spec)
    else:
        base = str(cwd or source or '').strip().replace('\\', '/').rstrip('/')
        if base:
            anchored.append(base + '/' + spec.lstrip('./'))
        anchored.append(spec)
    return any(_match_one(item, candidate) for item in anchored)


def _expand_home(text, home=None):
    if not text.startswith('~'):
        return text
    base = str(home or Path.home()).replace('\\', '/').rstrip('/')
    return base + text[1:] if text != '~' else base


def _collapse(text):
    """`..`/`.` về dạng chuẩn `/<phần>/<phần>` — một hàm cho CẢ đường dẫn lẫn mẫu."""
    parts = []
    for piece in str(text or '').replace('\\', '/').split('/'):
        if piece in ('', '.'):
            continue
        if piece == '..':
            if parts:
                parts.pop()
            continue
        parts.append(piece)
    return '/' + '/'.join(parts)


def _match_one(spec, candidate):
    """Khớp một mẫu gitignore rút gọn: `**` xuyên thư mục, `*`/`?` trong một tầng."""
    spec = _collapse(spec)
    candidate = _collapse(candidate)
    if spec.endswith('/**'):
        head = spec[:-3].rstrip('/')
        return candidate == head or candidate.startswith(head + '/')
    if not any(char in spec for char in '*?'):
        # Không có ký tự đại diện: khớp chính xác hoặc là thư mục cha của đường dẫn.
        return candidate == spec or candidate.startswith(spec.rstrip('/') + '/')
    # `**` xuyên `/`, `*` và `?` thì không.
    regex = ''
    index = 0
    while index < len(spec):
        char = spec[index]
        if char == '*':
            if spec[index:index + 2] == '**':
                regex += '.*'
                index += 2
                continue
            regex += '[^/]*'
        elif char == '?':
            regex += '[^/]'
        else:
            regex += re.escape(char)
        index += 1
    return re.fullmatch(regex, candidate) is not None


def match_domain_pattern(pattern, url_or_host):
    """`web_fetch(domain:example.com)` — khớp hostname, wildcard chỉ giữa hai dấu chấm."""
    spec = str(pattern or '').strip().lower()
    if not spec.startswith('domain:'):
        return False
    spec = spec[len('domain:'):].strip().rstrip('.')
    host = str(url_or_host or '').strip().lower()
    if not host:
        return False
    if '://' in host:
        host = host.split('://', 1)[1]
    host = host.split('/', 1)[0].split('?', 1)[0].rstrip('.').split('@')[-1]
    if ':' in host and not host.startswith('['):
        host = host.split(':', 1)[0]
    if not spec:
        return False
    if '*' not in spec:
        return host == spec
    # Wildcard chỉ được ở giữa hai dấu chấm: `*.example.com` khớp `a.example.com`, KHÔNG khớp
    # `example.com` (đúng như tài liệu Claude Code mô tả).
    regex = '^' + re.escape(spec).replace(r'\*', '[^.]*') + '$'
    return re.fullmatch(regex, host) is not None


# --- Luật ------------------------------------------------------------------

@dataclass
class Rule:
    tool: str
    specifier: str = ''
    layer: str = ''
    raw: str = ''

    @property
    def text(self):
        return self.raw or (self.tool if not self.specifier else '%s(%s)' % (self.tool, self.specifier))


def parse_rule(text, layer=''):
    """`Tool` hoặc `Tool(specifier)` ⇒ `Rule`. Dấu ngoặc bên trong specifier là ký tự thường."""
    raw = str(text or '').strip()
    if not raw:
        return None
    if '(' not in raw:
        return Rule(raw, '', layer, raw)
    head, _, rest = raw.partition('(')
    specifier = rest[:-1] if rest.endswith(')') else rest
    return Rule(head.strip(), specifier.strip(), layer, raw)


def rule_matches(rule, tool, args, *, cwd=None, source=None, home=None):
    """Luật có phê duyệt ĐÚNG lời gọi này không. Không có specifier ⇒ luật trần khớp cả công cụ."""
    if rule is None or rule.tool != tool:
        return False
    if not rule.specifier:
        return True
    specifier = rule.specifier
    if tool == 'terminal_exec':
        command = _command_from_args(args)
        return bool(command) and match_command_pattern(specifier, command)
    if tool == 'web_fetch':
        target = ''
        if isinstance(args, dict):
            target = args.get('url') or args.get('domain') or ''
        return match_domain_pattern(specifier, target)
    if tool in ('file_read', 'file_write', 'file_edit_block', 'codebase_glob', 'codebase_grep'):
        path = ''
        if isinstance(args, dict):
            path = args.get('path') or args.get('file_path') or args.get('pattern') or ''
        return match_path_pattern(specifier, path, cwd=cwd, source=source, home=home)
    # Công cụ CUA: chỉ tên trần ở v1, specifier bị bỏ qua (và không bao giờ được LƯU).
    return True


def _command_from_args(args):
    if isinstance(args, str):
        return args
    if isinstance(args, dict):
        for key in ('command', 'cmd', 'script', 'input'):
            value = args.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ''


def _path_arg(args):
    """Tham số đường dẫn của một lời gọi (`path`/`file_path`), rỗng nếu không có.

    Cố ý KHÔNG nhận `pattern`/`query`: `codebase_glob` không có đường dẫn nền, còn `codebase_grep`
    có `path` tuỳ chọn — nhận `pattern` làm đường dẫn sẽ biến `**/*.py` thành một "đường dẫn" giả.
    """
    if not isinstance(args, dict):
        return ''
    return str(args.get('path') or args.get('file_path') or '').strip()


def _canonical_text(command):
    """Một dòng để so khớp mẫu: bỏ wrapper, chuẩn hoá alias, gộp khoảng trắng, viết thường."""
    return re.sub(r'\s+', ' ', canonicalize_command(str(command or '')).lower()).strip()


def _list_reason(patterns, command):
    """Mã của mẫu ĐẦU TIÊN khớp trong `patterns` (danh sách `(regex, mã)`), hoặc chuỗi rỗng.

    Soi cả toàn văn lẫn từng lệnh con: mẫu `| sh` chỉ thấy được ở toàn văn (toán tử bị tách khi
    chia lệnh), còn `^reg add` chỉ thấy được ở từng phần.
    """
    raw = str(command or '')
    if not raw.strip():
        return ''
    texts = [_canonical_text(raw)]
    texts.extend(_canonical_text(part) for part in (split_commands(raw) or []))
    for text in texts:
        if not text:
            continue
        for pattern, code in patterns:
            if re.search(pattern, text):
                return code
    return ''


# --- Kiểm tra phạm vi trước khi lưu (§3.3.3) --------------------------------

def forbidden_prefix_reason(command):
    """Luật này có mở cả một trình thông dịch không.

    Soi CẢ dạng thô lẫn dạng đã bóc wrapper: bóc trước rồi mới soi thì `powershell -Command x`
    hoá thành `x` và lọt lưới — đúng thứ rào này sinh ra để chặn.
    """
    raw = re.sub(r'\s+', ' ', str(command or '')).strip().lower()
    canonical = canonicalize_command(command).lower()
    for prefix in FORBIDDEN_RULE_PREFIXES:
        for value in (raw, canonical):
            if value == prefix or value.startswith(prefix + ' '):
                return ('luật này cho phép cả một trình thông dịch (`%s`) — hãy thu hẹp về đúng lệnh cần dùng'
                        % prefix)
    return ''


def too_broad_reason(command, samples=None):
    """Mô phỏng "would approve everything": một luật khớp quá nhiều họ lệnh khác nhau thì từ chối."""
    canonical = canonicalize_command(command)
    if not canonical:
        return 'luật rỗng'
    if canonical in ('*', ':*'):
        return 'luật `*` phê duyệt mọi lệnh'
    probe = list(samples or ())
    probe += [
        'git status', 'npm run build', 'python -m pytest', 'rm -rf /', 'curl http://example.com',
        'Get-ChildItem C:\\', 'Remove-Item -Recurse -Force C:\\Windows', 'docker ps',
    ]
    families = set()
    for sample in probe:
        if match_command_pattern(command, sample):
            families.add(sample.split(' ')[0].lower())
    if len(families) >= 3:
        return ('luật này phê duyệt %d họ lệnh khác nhau — hãy thu hẹp tiền tố' % len(families))
    return ''


# --- Chính sách: ba tầng tệp + phiên + audit --------------------------------

def default_profile_dir(env=None):
    """Thư mục hồ sơ — CÙNG công thức với `search_store`/`academic` để chỉ có một chỗ khai."""
    source = os.environ if env is None else env
    explicit = str(source.get('BOXFOX_AGENT_DATA_DIR') or '').strip()
    if explicit:
        return Path(explicit)
    local = str(source.get('LOCALAPPDATA') or '').strip()
    if local:
        return Path(local) / 'BoxFox' / 'harness'
    return Path.home() / 'BoxFox' / 'harness'


def settings_paths(workspace=None, *, env=None, home=None, install_dir=None):
    """Bốn tầng cấu hình, theo thứ tự THẮNG dần: managed → profile → user → project."""
    source = os.environ if env is None else env
    home_dir = Path(home) if home else Path.home()
    explicit_home = str(source.get('BOXFOX_HOME_DIR') or '').strip()
    if explicit_home:
        home_dir = Path(explicit_home)
    explicit_install = install_dir or str(source.get('BOXFOX_INSTALL_DIR') or '').strip()
    install = Path(explicit_install) if explicit_install else Path(__file__).resolve().parents[2]
    profile = default_profile_dir(source)
    paths = {
        LAYER_MANAGED: install / 'managed-settings.json',
        LAYER_PROFILE: profile / 'permissions.json',
        LAYER_USER: home_dir / '.boxfox' / 'settings.json',
    }
    if workspace:
        paths[LAYER_PROJECT] = Path(workspace) / '.boxfox' / 'settings.local.json'
    return paths


class PermissionPolicy:
    """Đọc luật bốn tầng, quyết định một lời gọi, ghi nhớ phiên, ghi audit.

    Đối tượng này KHÔNG chạy gì cả: nó chỉ trả lời. Việc hỏi người dùng nằm ở bề mặt quyết định sẵn
    có (`request_approval`), còn việc thi hành nằm ở `HostExecutor`.
    """

    def __init__(self, workspace=None, *, mode=None, scope=None, profile_dir=None, env=None,
                 home=None, install_dir=None):
        source = os.environ if env is None else env
        self.env = source
        self.home = Path(home) if home else Path.home()
        self.workspace = str(workspace) if workspace else ''
        self.mode = mode if mode in MODES else None
        self.scope = scope if scope in SCOPES else None
        self.profile_dir = Path(profile_dir) if profile_dir else default_profile_dir(source)
        self.paths = settings_paths(workspace, env=source, home=home, install_dir=install_dir)
        if profile_dir:
            self.paths[LAYER_PROFILE] = Path(profile_dir) / 'permissions.json'
        self.layers = {}
        self.errors = {}
        self.session_rules = {}          # key ⇒ Decision (once/session)
        self.session_rules_lifetime = {}  # key ⇒ 'once' | 'session'
        self.denials = {}                # session_id ⇒ số lần từ chối liên tiếp
        self.pending = []                # thẻ duyệt đang chờ (H4 đọc)
        self.hardline_hits = 0
        self.reload()

    # -- đọc ----------------------------------------------------------------

    def reload(self):
        """Đọc lại bốn tầng từ đĩa. Tệp hỏng ⇒ tầng đó rỗng và ghi vào `errors`, không bao giờ ném."""
        self.layers = {}
        self.errors = {}
        for layer, path in self.paths.items():
            data, error = _read_json(path)
            if error:
                self.errors[layer] = error
                self.layers[layer] = {}
                continue
            self.layers[layer] = data or {}
        return self.snapshot()

    def mode_value(self):
        if self.mode:
            return self.mode
        for layer in reversed(LAYER_ORDER):
            value = str((self.layers.get(layer) or {}).get('mode') or '').strip().lower()
            if value in MODES:
                return value
        raw = str(self.env.get('BOXFOX_PERMISSION_MODE') or '').strip().lower()
        return raw if raw in MODES else MODE_DEFAULT

    def scope_value(self):
        if self.scope:
            return self.scope
        for layer in reversed(LAYER_ORDER):
            value = str((self.layers.get(layer) or {}).get('scope') or '').strip().lower()
            if value in SCOPES:
                return value
        raw = str(self.env.get('BOXFOX_PERMISSION_SCOPE') or '').strip().lower()
        return raw if raw in SCOPES else SCOPE_DEFAULT

    def network_value(self):
        """Trục mạng — cùng thứ tự tầng như `mode`/`scope` (tầng trên thắng)."""
        for layer in reversed(LAYER_ORDER):
            value = str((self.layers.get(layer) or {}).get('network') or '').strip().lower()
            if value in NETWORKS:
                return value
        raw = str(self.env.get('BOXFOX_PERMISSION_NETWORK') or '').strip().lower()
        return raw if raw in NETWORKS else NETWORK_DEFAULT

    def rules(self, layer=None):
        """Danh sách `Rule` của một tầng (hoặc cả bốn), kèm tệp nguồn để UI hiện được."""
        out = []
        for name in (LAYER_ORDER if layer is None else (layer,)):
            data = self.layers.get(name) or {}
            for key in ('deny', 'ask', 'allow'):
                for raw in data.get(key) or ():
                    rule = parse_rule(raw, name)
                    if rule is None:
                        continue
                    rule.specifier = rule.specifier
                    out.append((key, rule))
        return out

    def rules_for_layer(self, layer):
        return [item for item in self.rules(layer) if item[1].layer == layer]

    def snapshot(self):
        """Hình dạng cho `GET /api/agent/permissions` — chỉ dữ liệu, không đường dẫn bí mật."""
        merged = {'deny': [], 'ask': [], 'allow': []}
        sources = {}
        for key, rule in self.rules():
            merged[key].append(rule.text)
            sources.setdefault(key, []).append({'rule': rule.text, 'layer': rule.layer,
                                                'file': str(self.paths.get(rule.layer) or '')})
        return {
            'mode': self.mode_value(),
            'modeDefault': MODE_DEFAULT,
            'modes': list(MODES),
            'capabilities': MODE_CAPABILITIES[self.mode_value()],
            'scope': self.scope_value(),
            'scopeDefault': SCOPE_DEFAULT,
            'scopes': list(SCOPES),
            'network': self.network_value(),
            'networkDefault': NETWORK_DEFAULT,
            'networks': list(NETWORKS),
            'workspace': self.workspace,
            'layers': [
                {'layer': layer, 'file': str(self.paths.get(layer) or ''),
                 'present': (self.layers.get(layer) or {}) != {},
                 'error': self.errors.get(layer, '')}
                for layer in LAYER_ORDER if layer in self.paths
            ],
            'rules': merged,
            'ruleSources': sources,
            'hardlineCount': len(HARDLINE),
            'hardlineHits': self.hardline_hits,
            'denialBreakerLimit': DENIAL_BREAKER_LIMIT,
            'auditFile': str(self.profile_dir / AUDIT_FILENAME),
            'sessionRuleCount': len(self.session_rules),
        }

    # -- quyết định ---------------------------------------------------------

    def hardline_reason(self, command):
        """Lệnh có nằm trong sàn cứng không. Chạy TRƯỚC mọi danh sách, kể cả `trusted`.

        Soi TỪNG LỆNH CON và neo mẫu ở ĐẦU lệnh: `echo shutdown /r` là văn bản vô hại, còn
        `git status && shutdown /r` phải chặn. Một lệnh ghép bị tách thì mọi phần đều phải qua được.
        """
        raw = str(command or '')
        if not raw.strip():
            return ''
        if FORK_BOMB.search(raw):
            return 'fork_bomb'
        for part in (split_commands(raw) or [raw]):
            text = _canonical_text(part)
            if not text:
                continue
            for pattern, code in HARDLINE:
                if re.search(pattern, text):
                    return code
        return ''

    def guarded_reason(self, command):
        """Lệnh thuộc nhóm LUÔN HỎI (§6.1) — trả mã, hoặc chuỗi rỗng. Không có ngoại lệ cho `trusted`."""
        return _list_reason(GUARDED, command)

    def egress_reason(self, command):
        """Lệnh RA MẠNG (§6.1) — trả mã khi khớp danh sách hỏi, hoặc chuỗi rỗng."""
        return _list_reason(EGRESS, command)

    def decide(self, tool, args, *, cwd=None, session_id=None, actor='agent', remember=None):
        """Trả `Decision` cho một lời gọi. Không bao giờ ném, không bao giờ tự hỏi người dùng."""
        tool = str(tool or '').strip()
        command = _command_from_args(args) if tool in EXEC_TOOLS else ''
        if command:
            code = self.hardline_reason(command)
            if code:
                self.hardline_hits += 1
                decision = deny('lệnh nằm trong sàn cứng `%s` — không có chế độ nào bỏ qua được' % code,
                                'hardline:%s' % code, 'hardline')
                self.record(tool=tool, command=command, decision=decision, actor=actor,
                            session_id=session_id, scope=self.scope_value())
                return decision
            guard = self.guarded_reason(command)
            if guard:
                # Chạy TRƯỚC danh sách luật và trước `session_rules`: một lần cho phép là một lần,
                # nên đã cho phép trước đó (hay ở phiên khác) cũng không bỏ qua được bước hỏi này.
                decision = ask('lệnh thuộc nhóm luôn hỏi `%s` — chỉ cho phép một lần' % guard,
                               'guarded:%s' % guard, 'guarded')
                self.record(tool=tool, command=command, decision=decision, actor=actor,
                            session_id=session_id, scope=self.scope_value())
                return decision

        cwd_value = str(cwd or self.workspace or '')
        key = self.session_key(tool, args, cwd=cwd_value, session_id=session_id)

        for key_name in ('deny', 'ask', 'allow'):
            for rule_key, rule in self.rules():
                if rule_key != key_name:
                    continue
                if not rule_matches(rule, tool, args, cwd=cwd_value, source=self.workspace,
                                    home=self.home):
                    continue
                if key_name == 'deny':
                    decision = deny('luật `%s` cấm lời gọi này' % rule.text, rule.text, rule.layer)
                    self.record(tool=tool, command=command, decision=decision, actor=actor,
                                session_id=session_id, scope=self.scope_value())
                    return decision
                if key_name == 'ask':
                    remembered = self.session_rules.get(key)
                    if remembered is not None:
                        # Phiên này đã quyết rồi: cho phép ⇒ rơi xuống danh sách `allow`; từ chối ⇒
                        # giữ nguyên lời từ chối cũ thay vì hỏi lại.
                        if remembered.allowed:
                            break
                        self.record(tool=tool, command=command, decision=remembered, actor=actor,
                                    session_id=session_id, scope=self.scope_value())
                        return remembered
                    decision = ask('luật `%s` yêu cầu hỏi trước' % rule.text, rule.text, rule.layer)
                    self.record(tool=tool, command=command, decision=decision, actor=actor,
                                session_id=session_id, scope=self.scope_value())
                    return decision
                if key_name == 'allow':
                    remembered = self.session_rules.get(key)
                    if remembered is not None and not remembered.allowed:
                        decision = deny('phiên này đã từ chối lời gọi tương tự',
                                        remembered.rule, 'session')
                        self.record(tool=tool, command=command, decision=decision, actor=actor,
                                    session_id=session_id, scope=self.scope_value())
                        return decision
                    decision = allow(rule.text, rule.layer)
                    self.record(tool=tool, command=command, decision=decision, actor=actor,
                                session_id=session_id, scope=self.scope_value())
                    return decision

        remembered = self.session_rules.get(key)
        if remembered is not None:
            self.record(tool=tool, command=command, decision=remembered, actor=actor,
                        session_id=session_id, scope=self.scope_value())
            return remembered

        decision = self.default_decision(tool, args)
        self.record(tool=tool, command=command, decision=decision, actor=actor,
                    session_id=session_id, scope=self.scope_value())
        return decision

    def default_decision(self, tool, args):
        """Mặc định theo `mode` × `scope` (× `network` cho lệnh chạy) khi không luật nào khớp."""
        mode = self.mode_value()
        scope = self.scope_value()
        caps = MODE_CAPABILITIES[mode]
        if tool in READ_TOOLS:
            if scope == SCOPE_WORKSPACE and not self.in_workspace(args):
                # `codebase_glob`/`codebase_grep` không có tham số đường dẫn thì executor đã neo chúng
                # vào gốc dự án — hỏi ở đây chỉ thêm tiếng ồn mà không thêm ràng buộc nào.
                if tool in ('codebase_glob', 'codebase_grep') and not _path_arg(args):
                    return allow('', 'mode')
                return ask('ngoài workspace mà phạm vi đang là `workspace`', '', 'mode')
            return allow('', 'mode')
        if tool in WRITE_TOOLS:
            inside = self.in_workspace(args)
            if not inside and scope == SCOPE_WORKSPACE:
                return ask('ghi ngoài workspace', '', 'mode')
            return _from_capability(caps['write'], 'write', mode)
        if tool in EXEC_TOOLS:
            decision = _from_capability(caps['exec'], 'exec', mode)
            if decision.outcome == OUTCOME_ALLOW and mode != MODE_TRUSTED \
                    and self.network_value() == NETWORK_RESTRICTED:
                # Chỉ hỏi khi chế độ sẽ chạy IM LẶNG: `ask` đã hỏi mọi lệnh, `plan` từ chối, còn
                # `trusted` là toàn quyền (tương đương Full Access của Codex) — ghi rõ trong tài liệu.
                code = self.egress_reason(_command_from_args(args))
                if code:
                    return ask('lệnh ra mạng `%s` khi mức mạng là `restricted`' % code,
                               'network:%s' % code, 'network')
            return decision
        if tool in BARE_TOOLS:
            return _from_capability(caps['cua'], 'cua', mode)
        # Công cụ lạ: không có luật ⇒ hỏi, trừ khi mode là plan (đọc/không làm gì).
        if mode == MODE_PLAN:
            return deny('chế độ `plan` chỉ cho phép đọc', '', 'mode')
        return ask('công cụ không nằm trong bảng quyền v1', '', 'mode')

    def absolute_path(self, value):
        """Đường dẫn tuyệt đối đã chuẩn hoá (tương đối ⇒ neo vào workspace); rỗng nếu không có."""
        text = _expand_home(str(value or '').replace('\\', '/'), self.home).strip()
        if not text:
            return ''
        root = _collapse(str(self.workspace).replace('\\', '/')) if self.workspace else ''
        if not (text.startswith('/') or (len(text) > 1 and text[1] == ':')):
            if not root:
                return text.lstrip('./')
            text = root + '/' + text.lstrip('./')
        return _collapse(text)

    def in_workspace(self, args):
        if not self.workspace:
            return False
        path = _path_arg(args)
        if not path:
            return False
        candidate = self.absolute_path(path)
        root = _collapse(str(self.workspace).replace('\\', '/'))
        return bool(candidate) and (candidate == root or candidate.startswith(root.rstrip('/') + '/'))

    # -- phiên --------------------------------------------------------------

    def resource_key(self, tool, args):
        """Tài nguyên mà lời gọi nhắm tới: đường dẫn tuyệt đối, lệnh canonical, hoặc truy vấn."""
        if tool in EXEC_TOOLS:
            return canonicalize_command(_command_from_args(args))
        if tool == 'codebase_grep':
            query = args.get('query') if isinstance(args, dict) else args
            return str(query or '').strip()
        value = _path_arg(args) or (args.get('pattern') if isinstance(args, dict) else '')
        return self.absolute_path(value)

    def session_key(self, tool, args, *, cwd=None, session_id=None):
        """Key phiên = `{phiên, tool, tài nguyên, cwd, scope, mode}`.

        Có mã phiên và tài nguyên vì "ghi nhớ" phải HẸP: cho phép `file_write a.txt` không được
        cho phép `file_write b.txt`, và quyết định của phiên này không được rò sang phiên khác
        (DA1 của bản bàn giao). `HostExecutor` gọi CÙNG hàm này khi ghi nhớ — không có bản thứ hai.
        """
        return '|'.join((str(session_id or ''), str(tool), self.resource_key(tool, args),
                         str(cwd or ''), self.scope_value(), self.mode_value()))

    def remember(self, key, decision, lifetime='session'):
        """Ghi nhớ quyết định cho phiên (`session`) hoặc cho đúng một lần (`once`)."""
        if lifetime == 'once':
            return
        self.session_rules[key] = decision
        self.session_rules_lifetime[key] = lifetime

    def forget_session(self, session_id=None):
        """Bỏ quyết định đã nhớ. Có mã phiên ⇒ chỉ bỏ của phiên đó; không có ⇒ bỏ hết."""
        if session_id is None:
            self.session_rules.clear()
            self.session_rules_lifetime.clear()
            self.denials.clear()
            return
        prefix = str(session_id) + '|'
        for key in [key for key in self.session_rules if key.startswith(prefix)]:
            self.session_rules.pop(key, None)
            self.session_rules_lifetime.pop(key, None)
        self.denials.pop(str(session_id), None)

    def note_denial(self, session_id=None):
        """3 lần từ chối liên tiếp ⇒ ngắt mạch. Trả `True` khi ĐÃ ngắt."""
        key = str(session_id or '')
        self.denials[key] = self.denials.get(key, 0) + 1
        return self.denials[key] >= DENIAL_BREAKER_LIMIT

    def note_approval(self, session_id=None):
        self.denials.pop(str(session_id or ''), None)

    def breaker_decision(self):
        return deny('đã bị từ chối %d lần liên tiếp — dừng hỏi và báo lại cho người dùng'
                    % DENIAL_BREAKER_LIMIT, 'APPROVAL_DENIAL_BREAKER', 'session')

    # -- thẻ duyệt đang chờ --------------------------------------------------

    def register_pending(self, request_id, tool, args, decision, *, session_id=None):
        item = {'id': request_id, 'tool': tool, 'args': args, 'reason': decision.reason,
                'sessionId': session_id, 'createdAt': _now()}
        self.pending.append(item)
        return item

    def resolve_pending(self, request_id):
        for index, item in enumerate(self.pending):
            if item.get('id') == request_id:
                return self.pending.pop(index)
        return None

    def pending_items(self):
        return list(self.pending)

    # -- lưu luật -----------------------------------------------------------

    def target_layer(self, layer=None):
        """Đích auto-save của "Cho phép và đừng hỏi lại" — project-local khi có workspace."""
        if layer in self.paths:
            return layer
        return LAYER_PROJECT if LAYER_PROJECT in self.paths else LAYER_PROFILE

    def save_rule(self, tool, args, *, layer=None, scope='always', session_id=None, actor='user'):
        """Lưu một luật `allow` (hoặc `deny`) sau khi đã kiểm tra phạm vi.

        Trả `(ok, mã, thông báo, danh sách luật đã ghi)`. Lệnh ghép bị tách thành luật con (≤ 5);
        quá 5 thì KHÔNG lưu vĩnh viễn mà chỉ nhớ theo phiên.
        """
        tool = str(tool or '').strip()
        target = self.target_layer(layer)
        if tool in BARE_TOOLS:
            return False, 'CUA_NOT_PERSISTED', ('CUA không bao giờ sinh luật vĩnh viễn — chỉ nhớ theo phiên'), []
        specifiers = self._rule_specifiers(tool, args)
        if not specifiers:
            return False, 'EMPTY_RULE', 'không rút được luật nào từ lời gọi này', []
        if len(specifiers) > MAX_SUBCOMMAND_RULES:
            return False, 'COMPOUND_TOO_WIDE', ('lệnh ghép quá %d phần — chỉ nhớ theo phiên'
                                                % MAX_SUBCOMMAND_RULES), []
        for specifier in specifiers:
            reason = forbidden_prefix_reason(specifier) if tool in EXEC_TOOLS else ''
            if reason:
                return False, 'FORBIDDEN_PREFIX', reason, []
            broad = too_broad_reason(specifier) if tool in EXEC_TOOLS else ''
            if broad:
                return False, 'TOO_BROAD', broad, []
        rules = ['%s(%s)' % (tool, specifier) for specifier in specifiers]
        data = dict(self.layers.get(target) or {})
        existing = list(data.get('allow') or [])
        for rule in rules:
            if rule not in existing:
                existing.append(rule)
        data['allow'] = existing
        error = _write_json(self.paths[target], data)
        if error:
            return False, 'WRITE_FAILED', error, []
        self.reload()
        self.record(tool=tool, command=_command_from_args(args),
                    decision=allow(','.join(rules), target), actor=actor, session_id=session_id,
                    scope=self.scope_value())
        return True, 'OK', 'đã lưu %d luật vào %s' % (len(rules), self.paths[target]), rules

    def revoke_rule(self, rule_text, layer=None):
        """Xoá một luật khỏi tầng của nó (mặc định: tầng project-local)."""
        target = self.target_layer(layer)
        data = dict(self.layers.get(target) or {})
        removed = 0
        for key in ('deny', 'ask', 'allow'):
            values = [value for value in (data.get(key) or []) if value != rule_text]
            removed += len(data.get(key) or []) - len(values)
            if values:
                data[key] = values
            else:
                data.pop(key, None)
        if not removed:
            return False, 'NOT_FOUND', 'không tìm thấy luật trong %s' % self.paths[target]
        error = _write_json(self.paths[target], data)
        if error:
            return False, 'WRITE_FAILED', error
        self.reload()
        return True, 'OK', 'đã xoá %d mục' % removed

    def _rule_specifiers(self, tool, args):
        """Rút specifier hẹp nhất phê duyệt ĐÚNG lời gọi này (và không rộng hơn)."""
        if tool in EXEC_TOOLS:
            command = _command_from_args(args)
            if not command:
                return []
            parts = [part for part in split_commands(command) if part.strip()]
            return [part.strip() for part in parts] if parts else []
        if tool in ('file_read', 'file_write', 'file_edit_block', 'codebase_glob', 'codebase_grep'):
            path = ''
            if isinstance(args, dict):
                path = args.get('path') or args.get('file_path') or args.get('pattern') or ''
            path = str(path or '').strip()
            if not path:
                return []
            normalized = path.replace('\\', '/')
            # Đường dẫn tuyệt đối lưu ở neo `//abs`: luật chỉ phê duyệt ĐÚNG tệp đã hiện trên thẻ,
            # không phê duyệt cả cây (đó là việc của một luật do người dùng tự viết).
            return ['//' + normalized.lstrip('/') if normalized.startswith('/') else normalized]
        if tool == 'web_fetch':
            target = ''
            if isinstance(args, dict):
                target = args.get('url') or args.get('domain') or ''
            host = str(target or '').strip()
            if not host:
                return []
            if '://' in host:
                host = host.split('://', 1)[1]
            host = host.split('/', 1)[0].split('?', 1)[0].split('@')[-1].rstrip('.')
            if ':' in host and not host.startswith('['):
                host = host.split(':', 1)[0]
            return ['domain:' + host] if host else []
        return []

    # -- audit --------------------------------------------------------------

    def record(self, *, tool, command, decision, actor='agent', session_id=None, scope=None):
        """Một dòng audit. Ghi hỏng KHÔNG được làm hỏng lượt gọi (best-effort như system_log)."""
        entry = {
            'ts': _now(),
            'tool': tool,
            'command': str(command or '')[:400],
            'decision': decision.outcome,
            'rule': decision.rule,
            'layer': decision.layer,
            'scope': scope or self.scope_value(),
            'mode': self.mode_value(),
            'actor': actor,
            'sessionId': session_id or '',
        }
        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            line = json.dumps(entry, ensure_ascii=False)
            if len(line) > AUDIT_MAX_CHARS:
                entry['command'] = entry['command'][:120]
                line = json.dumps(entry, ensure_ascii=False)
            with (self.profile_dir / AUDIT_FILENAME).open('a', encoding='utf-8') as handle:
                handle.write(line + '\n')
        except Exception:
            pass
        return entry


def _from_capability(capability, family, mode=None):
    """Bảng `MODE_CAPABILITIES` nói `True`/`False`/`'allow'`/`'ask'` ⇒ quyết định. Một chỗ, không chép lại."""
    label = mode or 'hiện tại'
    if capability is True or capability == 'allow':
        return allow('', 'mode')
    if capability is False:
        return deny('chế độ `%s` không cho phép %s' % (label, family), '', 'mode')
    return ask('chế độ `%s` yêu cầu hỏi trước khi %s' % (label, family), '', 'mode')


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _read_json(path):
    """`(data, error)` — thiếu tệp là bình thường (trả `({}, '')`), hỏng thì trả lỗi đọc được."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except FileNotFoundError:
        return {}, ''
    except OSError as exc:
        return {}, 'không đọc được: %s' % exc
    if not text.strip():
        return {}, ''
    try:
        data = json.loads(text)
    except ValueError as exc:
        return {}, 'JSON hỏng: %s' % exc
    return (data if isinstance(data, dict) else {}), ''


def _write_json(path, data):
    """Ghi nguyên tử; trả chuỗi lỗi (rỗng = thành công)."""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_suffix(target.suffix + '.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temp, target)
    except OSError as exc:
        return 'không ghi được %s: %s' % (target, exc)
    return ''
