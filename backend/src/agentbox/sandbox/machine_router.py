"""Web IDE/Docker selection. Session bindings are durable and never follow a UI toggle."""
import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import time
import uuid
from pathlib import Path

from ..agent_core.permissions import PermissionPolicy
from .host_executor import (HostExecutor, approval_options, approval_reason, approval_verdict,
                            error_result)


class MachineError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class MachineRegistry:
    def __init__(self, store, *, default_mode=None, default_workspace=None):
        self.store = store
        self.db = store.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS web_machine_settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                revision INTEGER NOT NULL, mode TEXT NOT NULL, project_id TEXT);
            CREATE TABLE IF NOT EXISTS web_machine_projects (
                id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                trusted INTEGER NOT NULL DEFAULT 0);
        ''')
        # CSDL tạo trước commit `63fed3e` chưa có cột `trusted`: `CREATE TABLE IF NOT EXISTS` không
        # thêm cột cho bảng đã tồn tại, nên phải tự vá (cùng cách `session_store`).
        self._add_missing_columns('web_machine_projects', {'trusted': 'INTEGER NOT NULL DEFAULT 0'})
        # Bản desktop chạy tiến trình ở chế độ host và không có box nào để trỏ tới, nên cấu hình
        # mặc định phải là host NGAY TỪ DÒNG ĐẦU TIÊN — nếu không, giao diện mở ra đã nói "Docker"
        # trong khi mọi công cụ chạy trên máy thật (DA3 của bản bàn giao).
        # Chỉ áp cho CSDL MỚI (`INSERT OR IGNORE`): cấu hình người dùng đã lưu không bị đổi.
        self.process_mode = 'host' if default_mode == 'host' else 'docker'
        # Chỉ dựng folder mặc định khi CSDL CHƯA có cấu hình. Người dùng đã chạy một lần rồi xoá
        # folder đó thì lần mở sau không được tạo lại sau lưng họ.
        project_id = None
        first_run = self.db.execute('SELECT 1 FROM web_machine_settings WHERE singleton=1').fetchone() is None
        if first_run and self.process_mode == 'host' and default_workspace:
            project_id = self._bootstrap_project(default_workspace)
        self.db.execute('INSERT OR IGNORE INTO web_machine_settings VALUES (1,1,?,?)',
                        (self.process_mode, project_id))
        self.db.commit()

    def _add_missing_columns(self, table, columns):
        """Thêm cột còn thiếu vào bảng đã tồn tại (bản cài cũ). Hỏng thì bỏ qua, không chặn khởi động."""
        try:
            have = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
        except sqlite3.DatabaseError:
            return
        for name, kind in columns.items():
            if name in have:
                continue
            try:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
            except sqlite3.DatabaseError:
                continue
        self.db.commit()

    def _bootstrap_project(self, path):
        """Đăng ký sẵn folder mặc định của bản desktop (tạo nếu chưa có); lỗi thì để trống."""
        try:
            candidate = Path(str(path)).expanduser()
            candidate.mkdir(parents=True, exist_ok=True)
            return self.register(str(candidate))['id']
        except (OSError, MachineError):
            return None

    def project(self, project_id):
        row = self.db.execute('SELECT * FROM web_machine_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise MachineError('PROJECT_NOT_FOUND', 'Chọn lại folder dự án.', 404)
        return {**dict(row), 'trusted': bool(row['trusted'])}

    def state(self):
        row = dict(self.db.execute('SELECT * FROM web_machine_settings WHERE singleton=1').fetchone())
        return {'revision': row['revision'], 'mode': row['mode'], 'projectId': row['project_id'],
                # Chế độ của TIẾN TRÌNH, khác `mode` (lựa chọn của người dùng). Giao diện dùng nó để
                # không mời chuyển sang Docker khi bản này không có box nào (xem `update`).
                'processMode': self.process_mode,
                'projects': [{**dict(p), 'trusted': bool(p['trusted'])} for p in
                             self.db.execute('SELECT * FROM web_machine_projects ORDER BY name,path')]}

    def active_project(self):
        """Folder dự án đang chọn, hoặc `None`. Không bao giờ ném — người gọi cần một giá trị để trả lời."""
        project_id = self.state().get('projectId')
        if not project_id:
            return None
        try:
            return self.project(project_id)
        except MachineError:
            return None

    def register(self, path, name=None):
        if name is not None and (not isinstance(name, str) or not name.strip() or len(name.strip()) > 120 or any(ord(char) < 32 for char in name)):
            raise MachineError('PROJECT_NAME_INVALID', 'Tên dự án cần 1–120 ký tự, không có ký tự điều khiển.')
        candidate = Path(str(path or '')).expanduser()
        if not path or not candidate.is_absolute() or not candidate.is_dir():
            raise MachineError('PROJECT_PATH_INVALID', 'Cần đường dẫn tuyệt đối tới folder đang tồn tại.')
        candidate = candidate.resolve(strict=True)
        if candidate == Path(candidate.anchor):
            raise MachineError('PROJECT_ROOT_TOO_BROAD', 'Chọn folder dự án, không chọn toàn bộ ổ đĩa.')
        canonical = os.path.normcase(str(candidate))
        project_id = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]
        self.db.execute('INSERT OR IGNORE INTO web_machine_projects(id,path,name) VALUES(?,?,?)',
                        (project_id, canonical, name.strip() if name is not None else candidate.name))
        self.db.commit()
        return self.project(project_id)

    def update(self, values):
        current = self.state()
        if type(values.get('revision')) is not int or values['revision'] != current['revision']:
            raise MachineError('MACHINE_REVISION_CONFLICT', 'Cấu hình đã đổi; tải lại trước khi lưu.', 409)
        mode = values.get('mode')
        if mode not in ('host', 'docker'):
            raise MachineError('MACHINE_MODE_INVALID', 'Chỉ hỗ trợ IDE hoặc Docker.')
        # Tiến trình host không có box nào để trỏ tới: nhận `docker` ở đây sẽ tạo phiên nói "Docker"
        # nhưng công cụ vẫn chạy trên máy thật — đúng thứ bản bàn giao cấm (DA3/DA4).
        if mode == 'docker' and self.process_mode == 'host':
            raise MachineError('MACHINE_MODE_UNAVAILABLE',
                               'Bản này chạy trực tiếp trên máy (IDE), không có Docker box để chuyển sang.',
                               409)
        project_id = values.get('projectId') if mode == 'host' else None
        if project_id:
            self.project(project_id)
        result = self.db.execute('UPDATE web_machine_settings SET mode=?,project_id=?,revision=revision+1 '
                                 'WHERE singleton=1 AND revision=?', (mode, project_id, current['revision']))
        if result.rowcount != 1:
            raise MachineError('MACHINE_REVISION_CONFLICT', 'Cấu hình đã đổi.', 409)
        self.db.commit()
        return self.state()

    def trust(self, project_id, value):
        self.project(project_id)
        if type(value) is not bool:
            raise MachineError('PROJECT_TRUST_INVALID', 'trusted phải là boolean.')
        self.db.execute('UPDATE web_machine_projects SET trusted=? WHERE id=?', (int(value), project_id))
        self.db.commit()
        return self.project(project_id)

    def new_binding(self, values, parent_id=None):
        if parent_id:
            return self.binding(parent_id)  # Never accept a child/model override.
        selected = values.get('machineSelection')
        if selected is None:
            selected = self.state()
        if not isinstance(selected, dict) or selected.get('mode') not in ('host', 'docker'):
            raise MachineError('MACHINE_MODE_INVALID', 'Cấu hình môi trường không hợp lệ.')
        mode, project_id = selected['mode'], selected.get('projectId')
        if mode == 'docker':
            return {'mode': 'docker', 'revision': 1, 'projectId': None, 'workspace': '/home/agent/workspace'}
        # Chat with no project is allowed. Repository tools fail closed until a new session has a folder.
        project = self.project(project_id) if project_id else None
        return {'mode': 'host', 'revision': 1, 'projectId': project_id,
                'workspace': project['path'] if project else None}

    def binding(self, sid):
        session = self.store.get(sid) if sid else None
        if not session:
            raise MachineError('SESSION_NOT_FOUND', 'Không tìm thấy phiên.', 404)
        binding = session['config'].get('machineBinding')
        if binding:
            return dict(binding)
        if session.get('parent_id'):
            return self.binding(session['parent_id'])
        # Phiên web cũ giữ nguyên môi trường Docker của nó. Riêng tiến trình host (bản desktop) không
        # có box nào để giữ, nên phiên thiếu binding đi theo cấu hình đang chọn — đúng thứ mà công cụ
        # thật sự chạy trên đó.
        if self.process_mode == 'host':
            return self.new_binding({})
        return {'mode': 'docker', 'revision': 1, 'projectId': None, 'workspace': '/home/agent/workspace'}


FOLDER_PICKER_SCRIPT = r'''[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new();
$ErrorActionPreference = 'Stop';
Add-Type -AssemblyName System.Windows.Forms;
[System.Windows.Forms.Application]::EnableVisualStyles();
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class BoxFoxFolderDialog {
  [ComImport, Guid("42F85136-DB7E-439C-85F1-E4075D135FC8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IFileDialog {
    [PreserveSig] int Show(IntPtr owner);
    void SetFileTypes(uint count, IntPtr types);
    void SetFileTypeIndex(uint index);
    void GetFileTypeIndex(out uint index);
    void Advise(IntPtr events, out uint cookie);
    void Unadvise(uint cookie);
    void SetOptions(uint options);
    void GetOptions(out uint options);
    void SetDefaultFolder(IShellItem item);
    void SetFolder(IShellItem item);
    void GetFolder(out IShellItem item);
    void GetCurrentSelection(out IShellItem item);
    void SetFileName([MarshalAs(UnmanagedType.LPWStr)] string name);
    void GetFileName(out IntPtr name);
    void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string title);
    void SetOkButtonLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
    void SetFileNameLabel([MarshalAs(UnmanagedType.LPWStr)] string text);
    void GetResult(out IShellItem item);
  }
  [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
  interface IShellItem {
    void BindToHandler(IntPtr context, ref Guid handler, ref Guid iid, out IntPtr result);
    void GetParent(out IShellItem parent);
    void GetDisplayName(uint kind, out IntPtr name);
    void GetAttributes(uint mask, out uint attributes);
    void Compare(IShellItem other, uint hint, out int order);
  }
  public static string Pick(IntPtr owner) {
    var dialog = (IFileDialog)Activator.CreateInstance(Type.GetTypeFromCLSID(new Guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")));
    try {
      uint options; dialog.GetOptions(out options);
      // PICKFOLDERS, FORCEFILESYSTEM, PATHMUSTEXIST, NOCHANGEDIR, DONTADDTORECENT.
      dialog.SetOptions(options | 0x20u | 0x40u | 0x800u | 0x8u | 0x02000000u);
      dialog.SetTitle("BoxFox - Select Project Folder");
      int hr = dialog.Show(owner);
      if (hr == unchecked((int)0x800704C7)) return null;
      Marshal.ThrowExceptionForHR(hr);
      IShellItem item; dialog.GetResult(out item);
      try {
        IntPtr name; item.GetDisplayName(0x80058000u, out name);
        try { return Marshal.PtrToStringUni(name); } finally { Marshal.FreeCoTaskMem(name); }
      } finally { Marshal.ReleaseComObject(item); }
    } finally { Marshal.ReleaseComObject(dialog); }
  }
}
'@;
$owner = New-Object System.Windows.Forms.Form;
$owner.Text = 'BoxFox - Choose project folder';
$owner.ShowInTaskbar = $false;
$owner.TopMost = $true;
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen;
$owner.Size = New-Object System.Drawing.Size(1,1);
$owner.Opacity = 0;
try {
  # A hidden helper still needs an explicit foreground/topmost owner for its modal UI.
  $owner.Show();
  $owner.Activate();
  $selectedPath = [BoxFoxFolderDialog]::Pick($owner.Handle);
  if ($null -ne $selectedPath) {
  @{path=$selectedPath} | ConvertTo-Json -Compress
  } else { @{cancelled=$true} | ConvertTo-Json -Compress }
} finally { $owner.Dispose() }
'''


def pick_folder():
    """Explicit UI action, on the server's Windows desktop. No browser upload/copy."""
    if os.name != 'nt':
        raise MachineError('FOLDER_PICKER_UNAVAILABLE', 'Nhập đường dẫn folder trên máy chạy BoxFox.')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-WindowStyle', 'Hidden',
                                 '-Command', FOLDER_PICKER_SCRIPT], capture_output=True, encoding='utf-8', timeout=180)
        if result.returncode != 0:
            raise MachineError('FOLDER_PICKER_UNAVAILABLE', 'Không mở được picker; dùng đường dẫn folder.')
        value = json.loads(result.stdout.strip().lstrip('\ufeff'))
        if not isinstance(value, dict) or not (isinstance(value.get('path'), str) and value['path'].strip() or value.get('cancelled') is True):
            raise MachineError('FOLDER_PICKER_UNAVAILABLE', 'Picker không trả về đường dẫn hoặc thao tác hủy hợp lệ.')
        return value
    except subprocess.TimeoutExpired:
        raise MachineError('FOLDER_PICKER_TIMEOUT', 'Hộp chọn folder hết thời gian chờ. Chọn lại hoặc nhập đường dẫn trong Configuration.', 408) from None
    except (OSError, ValueError):
        raise MachineError('FOLDER_PICKER_UNAVAILABLE', 'Không mở được picker; dùng đường dẫn folder.') from None


class SessionMachineExecutor:
    def __init__(self, legacy, registry, profile_dir):
        self.legacy, self.registry = legacy, registry
        self.profile_dir = Path(profile_dir)
        self.runtime = None
        self.hosts = {}
        # Chính sách quyền dùng chung cho các route `/api/agent/permissions*` — xem `permissions_policy`.
        self.policies = {}
        self.visual_lock = legacy.visual_lock

    def __getattr__(self, key):
        return getattr(self.legacy, key)

    def policy_for(self, project=None):
        """`PermissionPolicy` dùng cho các ROUTE quyền (`GET/PUT /api/agent/permissions`).

        Chế độ (`plan`/`ask`/`auto`/`trusted`) và phạm vi (`workspace`/`machine`) KHÔNG được ghim ở
        đây: chúng đọc từ bốn tầng luật (`PermissionPolicy.mode_value()`), nên nút chọn quyền ở thanh
        chat và tab Settings → Machines có hiệu lực thật. Trước đây policy của phiên bị ghim
        `mode='ask'` ⇒ mọi thay đổi của người dùng bị bỏ qua.

        Đối tượng này CHỈ để đọc/ghi cấu hình. Phiên chạy tool có policy riêng
        (`session_policy`) để `session_rules` không rò giữa các phiên.
        """
        selected = project or self.registry.active_project() or {}
        workspace = str(selected.get('path') or '')
        key = str(selected.get('id') or 'default')
        policy = self.policies.get(key)
        if policy is None:
            policy = PermissionPolicy(workspace, profile_dir=self.profile_dir / 'host-permissions')
            self.policies[key] = policy
        return policy

    def session_policy(self, project, sid):
        """Policy RIÊNG của một phiên: cùng tầng luật trên đĩa, nhưng `session_rules` tách biệt.

        Dùng chung một đối tượng policy cho mọi phiên trong cùng folder sẽ khiến một lần "cho phép
        trong phiên này" của phiên A có hiệu lực luôn ở phiên B — phiên là ranh giới của quyết định.
        """
        return PermissionPolicy(str(project['path']),
                                profile_dir=self.profile_dir / 'host-permissions' / sid)

    def permissions_policy(self):
        """Policy cho các route quyền, kể cả khi tiến trình đang chạy ở chế độ docker.

        Bản desktop có thể chạy tiến trình ở chế độ docker trong khi máy được cấu hình host; khi đó
        `runtime.executor.policy` là `None` và mọi route quyền trả 409 dù phiên host vẫn chạy được.
        Đọc lại từ đĩa mỗi lần gọi: người dùng vừa đổi mode ở thanh chat thì lần đọc sau phải thấy.
        """
        policy = self.policy_for()
        policy.reload()
        return policy

    def host(self, sid):
        binding = self.registry.binding(sid)
        if binding['mode'] != 'host':
            raise MachineError('HOST_SESSION_REQUIRED', 'Phiên này sử dụng Docker.', 409)
        if not binding.get('projectId'):
            raise MachineError('PROJECT_REQUIRED', 'Chọn folder và mở phiên IDE mới trước khi dùng tool dự án.')
        project = self.registry.project(binding['projectId'])
        if project['path'] != binding['workspace'] or not Path(project['path']).is_dir():
            raise MachineError('PROJECT_UNAVAILABLE', 'Folder dự án không còn đúng binding.', 409)
        if sid not in self.hosts:
            policy = self.session_policy(project, sid)
            async def approve(name, args, decision, session_id=None):
                session = self.registry.store.get(session_id or sid)
                if not session or not self.runtime:
                    return 'deny'
                while session.get('parent_id'):
                    session = self.registry.store.get(session['parent_id'])
                previous_status = session['status']
                outcome = await self.runtime.decision(session, 'request_approval', {
                    'action': f'IDE [{sid}]: {name} {json.dumps(args, ensure_ascii=False)[:1500]}',
                    'reason': approval_reason(decision),
                    'options': approval_options(decision)})
                if session['id'] != sid and self.registry.store.get(session['id'])['status'] == 'awaiting_decision':
                    current = self.registry.store.get(session['id'])
                    self.registry.store.save(session['id'], current['messages'], previous_status)
                return approval_verdict(outcome, decision)
            self.hosts[sid] = HostExecutor(project['path'], policy=policy, approver=approve,
                                           artifacts_dir=self.profile_dir / 'host-artifacts' / project['id'] / sid)
        executor = self.hosts[sid]
        # Người dùng có thể đổi chế độ quyền giữa hai lượt (thanh chat hoặc Settings → Machines):
        # đọc lại bốn tầng luật trước mỗi lời gọi tool để lượt sau không dùng bản cũ.
        executor.policy.reload()
        return executor, project

    async def execute(self, name, args, session, **identity):
        if not session:
            return await self.legacy.execute(name, args, session, **identity)
        if self.registry.store.get(session) is None:
            # Existing admin readiness/index callers use synthetic identifiers, not sessions.
            return await self.legacy.execute(name, args, session, **identity)
        try:
            binding = self.registry.binding(session)
            if binding['mode'] == 'docker':
                return await self.legacy.execute(name, args, session, **identity)
            host, project = self.host(session)
            if name not in ('file_read', 'codebase_glob', 'codebase_grep') and not project['trusted']:
                return error_result('PROJECT_TRUST_REQUIRED', 'Xác nhận tin cậy folder trước khi sửa/chạy lệnh.')
            if name.startswith('computer_') or name == 'inspect_element':
                return error_result('HOST_CUA_NOT_ENABLED', 'CUA host chưa bật trong checkpoint web hai mode.')
            root = identity.get('root')
            if root:
                target = Path(root)
                target = (target if target.is_absolute() else Path(project['path']) / target).resolve()
                if not target.is_relative_to(Path(project['path'])):
                    return error_result('PATH_OUTSIDE_WORKSPACE', 'Root nằm ngoài folder đã chọn.')
            return await host.execute(name, args, session, **identity)
        except MachineError as exc:
            return error_result(exc.code, str(exc))

    async def request(self, path, body=None, session=None):
        """`/__box/*` theo ĐÚNG chế độ của phiên: host ⇒ `.plans` trong folder dự án của phiên.

        Trước đây `request` chỉ được `__getattr__` chuyển tiếp thẳng xuống `legacy`, nên ở host mode
        mọi lượt đọc chỉ mục plan đều nhắm vào box (không có) và tab Plan mất số liệu. Chỗ gọi cũ
        không truyền `session` (ví dụ chỉ mục của luồng ghi plan) vẫn đi đường cũ.
        """
        if session:
            # `binding` tự ném `SESSION_NOT_FOUND` cho mã phiên không có trong sổ (chỗ gọi admin
            # dùng mã tổng hợp), nên chỉ cần bắt `MachineError` là đủ để quay về đường box.
            try:
                binding = self.registry.binding(session)
            except MachineError:
                binding = None
            if binding is not None and binding['mode'] == 'host':
                host, _project = self.host(session)
                return await host.request(path, body=body, session=session)
        return await self.legacy.request(path, body=body, session=session)

    async def cleanup(self, sid):
        if sid in self.hosts:
            await self.hosts.pop(sid).cleanup(sid)
        else:
            await self.legacy.cleanup(sid)


def attach(runtime, profile_dir, *, default_mode=None, default_workspace=None):
    registry = MachineRegistry(runtime.store, default_mode=default_mode,
                               default_workspace=default_workspace)
    executor = SessionMachineExecutor(runtime.executor, registry, profile_dir)
    runtime.executor = executor
    runtime.machine_registry = registry
    executor.runtime = runtime
    return registry


def register_routes(app, runtime):
    from aiohttp import web
    registry = runtime.machine_registry
    async def handler(request):
        try:
            op = request.match_info['op']
            if op == 'configuration':
                result = registry.state() if request.method == 'GET' else registry.update(await request.json())
            elif op == 'projects':
                value = await request.json()
                result = registry.register(value.get('path'), value.get('name'))
            elif op == 'pick-folder':
                value = await request.json()
                if picker_lock.locked():
                    raise MachineError('FOLDER_PICKER_BUSY', 'Một hộp chọn folder đang mở. Chọn hoặc hủy hộp đó trước.', 409)
                async with picker_lock:
                    result = await asyncio.to_thread(pick_folder)
                    if result.get('path') and value.get('selectOnly') is not True:
                        result = registry.register(result['path'])
            elif op == 'trust':
                value = await request.json()
                result = registry.trust(value.get('projectId'), value.get('trusted'))
            return web.json_response(result)
        except MachineError as exc:
            return web.json_response({'error': f'{exc.code}: {exc}', 'code': exc.code}, status=exc.status)
    picker_lock = asyncio.Lock()
    app.router.add_get('/api/agent/machines/{op:configuration}', handler)
    app.router.add_put('/api/agent/machines/{op:configuration}', handler)
    app.router.add_post('/api/agent/machines/{op:projects|pick-folder|trust}', handler)

    async def workspace(request):
        try:
            project = registry.project(request.match_info['pid'])
            if not Path(project['path']).is_dir():
                raise MachineError('PROJECT_UNAVAILABLE', 'Folder không còn tồn tại.', 409)
            policy = PermissionPolicy(project['path'], mode='ask', scope='workspace',
                                      profile_dir=runtime.executor.profile_dir / 'host-ui-permissions' / project['id'])
            host = HostExecutor(project['path'], policy=policy)
            op = request.match_info['op']
            if request.method == 'GET':
                target = host._resolve(request.query.get('path') or '.')
                if op == 'files':
                    if not target.is_dir():
                        raise MachineError('FOLDER_NOT_FOUND', 'Không tìm thấy folder.', 404)
                    entries = []
                    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
                        if len(entries) == 500:
                            break
                        try:
                            host._resolve(str(entry))
                        except ValueError:
                            continue
                        entries.append({'name': entry.name, 'path': entry.relative_to(Path(project['path'])).as_posix(), 'directory': entry.is_dir()})
                    result = {'path': target.relative_to(Path(project['path'])).as_posix(), 'entries': entries}
                else:
                    if not target.is_file() or target.stat().st_size > 1024 * 1024:
                        raise MachineError('FILE_UNSUPPORTED', 'Editor chỉ mở file UTF-8 tối đa 1 MiB.')
                    raw = target.read_bytes()
                    if b'\x00' in raw:
                        raise MachineError('FILE_BINARY', 'File nhị phân không mở bằng editor văn bản.')
                    result = {'path': request.query.get('path'), 'content': raw.decode('utf-8'), 'hash': hashlib.sha256(raw).hexdigest()}
            else:
                if not project['trusted']:
                    raise MachineError('PROJECT_TRUST_REQUIRED', 'Xác nhận tin cậy folder trước khi sửa/chạy lệnh.', 403)
                values = await request.json()
                if op == 'file':
                    target = host._resolve(values.get('path'))
                    raw = target.read_bytes()
                    if values.get('hash') != hashlib.sha256(raw).hexdigest():
                        raise MachineError('FILE_CHANGED', 'File đã đổi bên ngoài; tải lại trước khi lưu.', 409)
                    content = values.get('content')
                    if not isinstance(content, str) or len(content.encode('utf-8')) > 1024 * 1024:
                        raise MachineError('FILE_CONTENT_INVALID', 'Nội dung file tối đa 1 MiB.')
                    result = host._file_write({'path': str(target), 'content': content})
                    result['hash'] = hashlib.sha256(content.encode('utf-8')).hexdigest()
                else:
                    command = values.get('command')
                    if not isinstance(command, str) or not command.strip() or len(command) > 8000:
                        raise MachineError('COMMAND_INVALID', 'Cần lệnh hợp lệ.')
                    decision = policy.decide('terminal_exec', {'command': command}, session_id='ui:' + project['id'])
                    if decision.outcome == 'deny':
                        raise MachineError('PERMISSION_DENIED', decision.reason, 403)
                    # Explicit user action in the command panel; never reused as agent approval.
                    result = await host._terminal_exec({'command': command, 'timeout': 30}, 'ui:' + project['id'])
            return web.json_response(result)
        except MachineError as exc:
            return web.json_response({'error': f'{exc.code}: {exc}', 'code': exc.code}, status=exc.status)
        except (ValueError, OSError, UnicodeError) as exc:
            return web.json_response({'error': f'HOST_RESOURCE_INVALID: {exc}', 'code': 'HOST_RESOURCE_INVALID'}, status=400)
    app.router.add_get('/api/agent/machines/projects/{pid}/{op:files|file}', workspace)
    app.router.add_post('/api/agent/machines/projects/{pid}/{op:file|command}', workspace)

    # Chỉ mục + nội dung `.plans` của một folder host. CÙNG payload với `/__box/plans` của box
    # (một nguồn đọc: `deploy/docker/plan_files.py`), nên tab Plan không phải rẽ nhánh theo chế độ.
    async def plans_response(request, *, content):
        try:
            project = registry.project(request.match_info['pid'])
            if not Path(project['path']).is_dir():
                raise MachineError('PROJECT_UNAVAILABLE', 'Folder không còn tồn tại.', 409)
            from . import host_plans
            try:
                if content:
                    result = await asyncio.to_thread(host_plans.plan_document, project['path'],
                                                     request.query.get('identity', ''),
                                                     request.query.get('version', ''))
                else:
                    result = await asyncio.to_thread(host_plans.plan_manifest, project['path'])
            except host_plans.HostPlanReaderUnavailable as exc:
                raise MachineError('PLAN_READER_UNAVAILABLE', str(exc), 501) from None
            except Exception as exc:
                # Lỗi của bộ đọc giữ nguyên mã HTTP của nó (404 thiếu bản, 400 identity sai...).
                status, message = host_plans.error_status(exc)
                raise MachineError('PLAN_REQUEST_INVALID' if status < 500 else 'PLAN_READ_FAILED',
                                   message, status) from None
            return web.json_response(result)
        except MachineError as exc:
            return web.json_response({'error': f'{exc.code}: {exc}', 'code': exc.code}, status=exc.status)

    async def plans(request):
        return await plans_response(request, content=False)

    async def plans_content(request):
        return await plans_response(request, content=True)

    app.router.add_get('/api/agent/machines/projects/{pid}/plans', plans)
    app.router.add_get('/api/agent/machines/projects/{pid}/plans/content', plans_content)

    # User-selected snapshot preview only. No hooks, input, personal browser attachment or auto capture.
    previews = {}
    async def screen(request):
        try:
            from .win import capture, windows_platform
            platform = windows_platform.get_platform()
            if request.method == 'GET':
                return web.json_response({'windows': capture.list_windows(platform=platform)})
            values = await request.json()
            if values.get('consent') is not True:
                raise MachineError('SCREEN_CONSENT_REQUIRED', 'Cấp quyền xem đúng cửa sổ trước khi chụp.', 403)
            hwnd, pid = int(values.get('windowId')), int(values.get('pid'))
            if platform.get_window_pid(hwnd) != pid:
                raise MachineError('SCREEN_TARGET_CHANGED', 'Cửa sổ đã đổi; chọn lại.', 409)
            capture.set_dpi_awareness(platform=platform)
            window = platform.describe_window(hwnd)
            fingerprint = (pid, tuple(window.bounds), platform.get_dpi_for_window(hwnd))
            if values.get('action') == 'inspect':
                preview = previews.get(values.get('snapshotId'))
                if not preview or preview['expires'] < time.monotonic() or preview['fingerprint'] != fingerprint:
                    raise MachineError('SCREEN_SNAPSHOT_STALE', 'Ảnh/cửa sổ đã đổi; chụp lại trước khi chọn.', 409)
                if preview['hwnd'] != hwnd:
                    raise MachineError('SCREEN_TARGET_CHANGED', 'Snapshot thuộc cửa sổ khác.', 409)
                x, y = values.get('x'), values.get('y')
                if type(x) is not int or type(y) is not int or not (0 <= x < window.bounds[2] and 0 <= y < window.bounds[3]):
                    raise MachineError('INSPECT_POINT_INVALID', 'Điểm nằm ngoài cửa sổ.')
                # Read-only window metadata fallback. No SendInput, CDP attach or activation.
                left, top, width, height = window.bounds
                sx, sy = left + x, top + y
                point_window = platform.window_from_point(sx, sy)
                if not point_window or platform.get_ancestor_root(point_window) != hwnd:
                    raise MachineError('SCREEN_OCCLUDED', 'Cửa sổ tại điểm chọn không còn khớp snapshot.', 409)
                payload = {'type': 'desktop', 'reason': 'host_window_metadata', 'windowId': str(hwnd),
                           'windowTitle': window.title, 'windowClass': window.class_name,
                           'appName': window.process_name, 'pid': pid,
                           'position': {'x': left, 'y': top}, 'size': {'width': width, 'height': height}}
                payload['label'] = {'integrity': 'khong_tin_duoc', 'confidentiality': 'noi_bo',
                                    'source_kind': 'screen_capture', 'source_uri': f'window://{hwnd}/{pid}',
                                    'tool_name': 'inspect_element', 'content_hash': hashlib.sha256(json.dumps(payload, sort_keys=True).encode('utf-8')).hexdigest()}
                return web.json_response({'result': payload, 'point': {'x': sx, 'y': sy},
                                          'snapshotId': values['snapshotId'], 'snapshotHash': preview['hash']})
            shot = capture.capture_window(hwnd, platform=platform)
            if shot.occluded:
                raise MachineError('SCREEN_OCCLUDED', 'Cửa sổ bị che; quan sát lại khi cửa sổ hiển thị.', 409)
            import base64
            png = capture.encode_png(shot)
            if platform.get_window_pid(hwnd) != pid or tuple(platform.describe_window(hwnd).bounds) != fingerprint[1]:
                raise MachineError('SCREEN_TARGET_CHANGED', 'Cửa sổ đổi trong lúc chụp; chọn lại.', 409)
            snapshot_id = uuid.uuid4().hex
            for key in list(previews):
                if previews[key]['expires'] < time.monotonic():
                    previews.pop(key)
            while len(previews) >= 32:
                previews.pop(next(iter(previews)))
            previews[snapshot_id] = {'hwnd': hwnd, 'fingerprint': fingerprint, 'expires': time.monotonic() + 60,
                                     'hash': hashlib.sha256(png).hexdigest()}
            return web.json_response({'image': base64.b64encode(png).decode('ascii'), 'mime': 'image/png',
                                      'width': shot.width, 'height': shot.height, 'windowId': hwnd, 'pid': pid,
                                      'hash': hashlib.sha256(png).hexdigest(), 'snapshotId': snapshot_id, 'untrusted': True})
        except MachineError as exc:
            return web.json_response({'error': f'{exc.code}: {exc}', 'code': exc.code}, status=exc.status)
        except Exception as exc:
            return web.json_response({'error': f'HOST_SCREEN_UNAVAILABLE: {exc}', 'code': 'HOST_SCREEN_UNAVAILABLE'}, status=409)
    app.router.add_get('/api/agent/machines/screen', screen)
    app.router.add_post('/api/agent/machines/screen', screen)
