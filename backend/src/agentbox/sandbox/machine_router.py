"""Web IDE/Docker selection. Session bindings are durable and never follow a UI toggle."""
import asyncio
import hashlib
import json
import os
import subprocess
import time
import uuid
from pathlib import Path

from ..agent_core.permissions import PermissionPolicy
from .host_executor import HostExecutor, error_result


class MachineError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class MachineRegistry:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS web_machine_settings (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1),
                revision INTEGER NOT NULL, mode TEXT NOT NULL, project_id TEXT);
            INSERT OR IGNORE INTO web_machine_settings VALUES (1,1,'docker',NULL);
            CREATE TABLE IF NOT EXISTS web_machine_projects (
                id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                trusted INTEGER NOT NULL DEFAULT 0);
        ''')
        self.db.commit()

    def project(self, project_id):
        row = self.db.execute('SELECT * FROM web_machine_projects WHERE id=?', (project_id,)).fetchone()
        if not row:
            raise MachineError('PROJECT_NOT_FOUND', 'Chọn lại folder dự án.', 404)
        return {**dict(row), 'trusted': bool(row['trusted'])}

    def state(self):
        row = dict(self.db.execute('SELECT * FROM web_machine_settings WHERE singleton=1').fetchone())
        return {'revision': row['revision'], 'mode': row['mode'], 'projectId': row['project_id'],
                'projects': [{**dict(p), 'trusted': bool(p['trusted'])} for p in
                             self.db.execute('SELECT * FROM web_machine_projects ORDER BY name,path')]}

    def register(self, path):
        candidate = Path(str(path or '')).expanduser()
        if not path or not candidate.is_absolute() or not candidate.is_dir():
            raise MachineError('PROJECT_PATH_INVALID', 'Cần đường dẫn tuyệt đối tới folder đang tồn tại.')
        candidate = candidate.resolve(strict=True)
        if candidate == Path(candidate.anchor):
            raise MachineError('PROJECT_ROOT_TOO_BROAD', 'Chọn folder dự án, không chọn toàn bộ ổ đĩa.')
        canonical = os.path.normcase(str(candidate))
        project_id = hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:24]
        self.db.execute('INSERT OR IGNORE INTO web_machine_projects(id,path,name) VALUES(?,?,?)',
                        (project_id, canonical, candidate.name))
        self.db.commit()
        return self.project(project_id)

    def update(self, values):
        current = self.state()
        if type(values.get('revision')) is not int or values['revision'] != current['revision']:
            raise MachineError('MACHINE_REVISION_CONFLICT', 'Cấu hình đã đổi; tải lại trước khi lưu.', 409)
        mode = values.get('mode')
        if mode not in ('host', 'docker'):
            raise MachineError('MACHINE_MODE_INVALID', 'Chỉ hỗ trợ IDE hoặc Docker.')
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
        # Existing web sessions retain their Docker environment.
        return {'mode': 'docker', 'revision': 1, 'projectId': None, 'workspace': '/home/agent/workspace'}


def pick_folder():
    """Explicit UI action, on the server's Windows desktop. No browser upload/copy."""
    if os.name != 'nt':
        raise MachineError('FOLDER_PICKER_UNAVAILABLE', 'Nhập đường dẫn folder trên máy chạy BoxFox.')
    script = '''[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new();
Add-Type -AssemblyName System.Windows.Forms;
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;
$dialog.Description = 'BoxFox - Choose project folder';
$dialog.ShowNewFolderButton = $false;
try { if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  @{path=$dialog.SelectedPath} | ConvertTo-Json -Compress
} else { @{cancelled=$true} | ConvertTo-Json -Compress } } finally { $dialog.Dispose() }
'''
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-STA', '-WindowStyle', 'Hidden',
                                 '-Command', script], capture_output=True, encoding='utf-8', timeout=180)
        if result.returncode != 0:
            raise MachineError('FOLDER_PICKER_UNAVAILABLE', 'Không mở được picker; dùng đường dẫn folder.')
        return json.loads(result.stdout.strip().lstrip('\ufeff'))
    except subprocess.TimeoutExpired:
        return {'cancelled': True}


class SessionMachineExecutor:
    def __init__(self, legacy, registry, profile_dir):
        self.legacy, self.registry = legacy, registry
        self.profile_dir = Path(profile_dir)
        self.runtime = None
        self.hosts = {}
        self.visual_lock = legacy.visual_lock

    def __getattr__(self, key):
        return getattr(self.legacy, key)

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
            policy = PermissionPolicy(project['path'], mode='ask', scope='workspace',
                                      profile_dir=self.profile_dir / 'host-permissions' / sid)
            async def approve(name, args, decision):
                session = self.registry.store.get(sid)
                if not self.runtime:
                    return 'deny'
                while session.get('parent_id'):
                    session = self.registry.store.get(session['parent_id'])
                previous_status = session['status']
                outcome = await self.runtime.decision(session, 'request_approval', {
                    'action': f'IDE [{sid}]: {name} {json.dumps(args, ensure_ascii=False)[:1500]}',
                    'reason': f'{decision.reason}. Lệnh chạy bằng tài khoản Windows của bạn; không có sandbox OS.',
                    'options': [{'id': 'approve', 'label': 'Cho phép một lần', 'kind': 'approve'},
                                {'id': 'reject', 'label': 'Từ chối', 'kind': 'reject'}]})
                if session['id'] != sid and self.registry.store.get(session['id'])['status'] == 'awaiting_decision':
                    current = self.registry.store.get(session['id'])
                    self.registry.store.save(session['id'], current['messages'], previous_status)
                return 'allow' if outcome.get('status') == 'approved' and outcome.get('choice') == 'approve' else 'deny'
            self.hosts[sid] = HostExecutor(project['path'], policy=policy, approver=approve,
                                           artifacts_dir=self.profile_dir / 'host-artifacts' / project['id'] / sid)
        return self.hosts[sid], project

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

    async def cleanup(self, sid):
        if sid in self.hosts:
            await self.hosts.pop(sid).cleanup(sid)
        else:
            await self.legacy.cleanup(sid)


def attach(runtime, profile_dir):
    registry = MachineRegistry(runtime.store)
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
                result = registry.register(value.get('path'))
            elif op == 'pick-folder':
                async with picker_lock:
                    result = await asyncio.to_thread(pick_folder)
                    if result.get('path'):
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
