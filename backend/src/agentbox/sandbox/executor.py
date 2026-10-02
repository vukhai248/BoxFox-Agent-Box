"""Host adapter for the existing BoxFox container and capture control plane."""
import asyncio
import base64
import json
import re
import subprocess
import unicodedata
from pathlib import Path
import httpx
from ..observability.system_log import system_log
from ..vendor.hermes.computer_backend import image_dimensions_from_bytes

WORKER_PATH = Path(__file__).with_name('worker.py')
WORKER = WORKER_PATH.read_text(encoding='utf-8')
CONTAINER_WORKER_PATH = '/tmp/boxfox-worker.py'

# Khoá `target` mà box THẬT SỰ đọc (`deploy/docker/capture.py: resolve_window` / `resolve_tab`).
# Khoá lạ KHÔNG được gửi xuống: box trả `_invalid` cho target nó không hiểu, nên gửi bừa một khoá
# model tự nghĩ ra là cách chắc nhất để làm hỏng một lần chụp đáng lẽ chạy được (P2.2).
CAPTURE_TARGET_STRING_KEYS = ('windowId', 'class', 'title', 'tabId', 'url')
CAPTURE_LABEL_MAX_CHARS = 40


def capture_label(caption):
    """Nhãn ASCII cho TÊN TỆP ảnh, sinh từ `caption` của model (P2.3).

    `capture.py._slug` thay mọi ký tự ngoài `[0-9A-Za-z_.-]` bằng `-`, nên để nguyên chữ có dấu
    ("Kiểm thử RAG") sẽ ra một chuỗi gạch ngang vô nghĩa: bỏ dấu ở ĐÂY, trước khi gửi xuống box.
    Nhãn đầy đủ (nguyên ngữ của model) không vào tên tệp — nó ở lại harness làm chú thích ảnh.
    """
    text = unicodedata.normalize('NFD', str(caption or ''))
    text = ''.join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r'[^0-9A-Za-z]+', '-', text).strip('-').lower()
    return text[:CAPTURE_LABEL_MAX_CHARS].strip('-')


def normalize_capture_target(args):
    """`(target, caption)` — `target` của model đã lọc về đúng thứ box hiểu (P2.2).

    Ba kind của box (`window`/`tab`/`screen`), chỉ khoá box đọc, `pid` phải là số nguyên; kind lạ
    hoặc thiếu ⇒ `screen` ĐÚNG NHƯ HÀNH VI CŨ (chỗ gọi không truyền `target` không đổi một byte).
    `caption` là nhãn của lần chụp: harness biến nó thành `label` ASCII đi cùng target; nó KHÔNG đi
    xuống box như một trường riêng.

    Nhập `tool_contracts` Ở TRONG HÀM: `agent_core/__init__` nhập `tools` → `system_media`
    → mô-đun này, nên nhập ở cấp mô-đun thành VÒNG (đo được: `from agentbox.sandbox.executor
    import …` đứng một mình thì chết vì `SandboxExecutor` chưa kịp định nghĩa).
    """
    from ..agent_core.tool_contracts import CAPTURE_CAPTION_MAX_CHARS, CAPTURE_TARGET_KINDS
    args = args if isinstance(args, dict) else {}
    raw = args.get('target') if isinstance(args.get('target'), dict) else {}
    kind = raw.get('kind')
    target = {'kind': kind if kind in CAPTURE_TARGET_KINDS else 'screen'}
    for key in CAPTURE_TARGET_STRING_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            target[key] = value.strip()
    pid = raw.get('pid')
    if isinstance(pid, int) and not isinstance(pid, bool):
        target['pid'] = pid
    caption = str(args.get('caption') or '').strip()[:CAPTURE_CAPTION_MAX_CHARS]
    if caption:
        # Nhãn rỗng sau khi bỏ dấu vẫn phải nói được "đây là một lần chụp": `shot`.
        target['label'] = capture_label(caption) or 'shot'
    return target, caption


def box_identity(session, step=None, tool_call_id=None):
    """Khoá định danh gửi kèm mỗi yêu cầu ra box (P1.4): phiên, bước, id lời gọi công cụ.

    Chỉ giá trị harness THẬT SỰ biết mới có mặt trên dây: chỗ gọi cũ (không truyền gì) phải
    nhận ĐÚNG thân yêu cầu cũ — box đã đọc `step`/`toolCallId` từ lâu
    (`deploy/docker/ide-proxy.py:284`) nhưng không được thấy khoá lạ khi harness không biết.
    """
    body = {'session': session}
    if step is not None:
        body['step'] = step
    if tool_call_id is not None:
        body['toolCallId'] = tool_call_id
    return body


class BoxRequestError(RuntimeError):
    """Lỗi của box, mang NGUYÊN VĂN thông điệp của nó (P2.4) + mã trạng thái HTTP.

    `httpx.raise_for_status()` nuốt thân JSON của box rồi thay bằng "Client error '409 Conflict' for
    url 'http://127.0.0.1:8081/__box/capture'", nên một lỗi tự sửa được của box ("Nhiều tab khớp
    target — chọn chính xác hơn") tới tay model thành "không chụp được". Giữ câu của box là điều
    kiện để model chọn lại target bằng `tabId`/`windowId` cho đúng.
    """

    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.message = str(message)
        self.status_code = status_code


def box_error_message(response):
    """Thông điệp box gửi kèm trong thân JSON, NGUYÊN VĂN; đọc không được thì câu mặc định.

    Box trả `{"error": "<câu>"}` (`deploy/docker/ide-proxy.py`), có nơi trả `message`/`detail`.
    Không nội suy gì thêm vào câu của box — nó là câu của box.
    """
    payload = None
    try:
        payload = response.json()
    except Exception:
        payload = None
    if isinstance(payload, dict):
        for key in ('message', 'error', 'detail'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return f'HTTP {response.status_code} from the sandbox box'


class SandboxExecutor:
    def __init__(self, container='agentbox-box', api_url='http://127.0.0.1:8081', api_key='boxfox-local-dev-token'):
        self.container = container
        self.api_url = api_url
        self.api_key = api_key
        self.recordings = {}
        # Physical desktop shared by sessions: media/input/browser serialize per action.
        self.visual_lock = asyncio.Lock()
        self._worker_synced = False

    def _sync_worker(self):
        """Đồng bộ worker.py vào container qua docker cp để tránh truyền mã nguồn qua CLI args."""
        try:
            res = subprocess.run(
                ['docker', 'cp', str(WORKER_PATH), f'{self.container}:{CONTAINER_WORKER_PATH}'],
                capture_output=True, timeout=10
            )
            if res.returncode == 0:
                self._worker_synced = True
        except Exception:
            pass

    async def request(self, path, body=None):
        async with httpx.AsyncClient(timeout=40, trust_env=False) as client:
            response = await client.request('POST' if body is not None else 'GET', self.api_url + path,
                json=body, headers={'X-BoxFox-Api-Key': self.api_key})
            if response.status_code >= 400:
                # P2.4 — lỗi của box đi lên NGUYÊN VĂN (xem `BoxRequestError`).
                raise BoxRequestError(box_error_message(response), status_code=response.status_code)
            return response.json()

    async def execute(self, name, args, session, turn=None, step=None, tool_call_id=None, root=None):
        # P1.4: `turn`/`step`/`tool_call_id` do HARNESS đặt (không lấy từ `args` của model). Chỉ
        # chuyển tiếp giá trị THẬT: chỗ gọi cũ không truyền gì thì `_execute` nhận đúng ba tham
        # số như trước (bài kiểm cũ thay `_execute` bằng một hàm ba tham số).
        context = {key: value for key, value in (('turn', turn), ('step', step),
                                                 ('tool_call_id', tool_call_id), ('root', root)) if value is not None}
        if name in {'computer_screen_capture', 'computer_screen_record', 'computer_use', 'browser_use', 'inspect_element'}:
            async with self.visual_lock:
                result = await self._execute(name, args, session, **context)
        else:
            result = await self._execute(name, args, session, **context)
        self._log_desktop_note(name, result, session)
        return result

    def _log_desktop_note(self, name, result, session):
        """Ghi lại việc màn hình bị kéo nhỏ (F6) vào nhật ký hệ thống cho DEV.

        F6 xảy ra ÂM THẦM: client RFB kéo framebuffer nhỏ đi là toạ độ CUA trỏ sai mà
        không lỗi nào nổi lên. Dòng log này là bằng chứng duy nhất khi truy lỗi về sau.
        """
        if not isinstance(result, dict):
            return
        note = result.get('desktopRestored') or result.get('desktopWarning')
        if not isinstance(note, dict):
            return
        restored = 'to' in note
        system_log.write(
            'box.desktop_restored' if restored else 'box.desktop_warning',
            level='info' if restored else 'warn',
            code='DESKTOP_RESTORED' if restored else 'DESKTOP_TOO_SMALL',
            message=(f"the sandbox desktop was {note.get('from')} and is back at {note.get('to')}"
                     if restored else
                     f"the sandbox desktop is smaller than configured ({note.get('from')}): {note.get('warning')}"),
            session_id=session,
            tool=name,
            **note,
        )

    async def _execute(self, name, args, session, turn=None, step=None, tool_call_id=None, retry=False, root=None):
        # `turn`/`step`/`tool_call_id` đi cùng yêu cầu (P1.4): hai route capture/ghi hình nhận
        # `step`/`toolCallId` (`deploy/docker/ide-proxy.py:284`), worker nhận cả ba trong payload.
        if name == 'inspect_element':
            return await self.request('/__box/inspect-element', {'x': int(args['x']), 'y': int(args['y'])})
        if name == 'computer_screen_capture':
            # A3 (đợt 20): gửi kèm `session` để ảnh mới nằm ở `captures/screen/<sid8>/` thay vì
            # đổ chung một thư mục phẳng (đo sống: 375 tệp / 113 MB, 123 tệp không payload nào
            # nhắc tới nên không biết của phiên nào). Box không có `session` thì giữ khuôn cũ.
            # Vòng 23 (P2.2): `target` do MODEL chọn (window/tab/screen + khoá box đọc), không còn
            # đóng đinh `screen`; `caption` thành nhãn ASCII trong tên tệp (P2.3) và ở lại payload
            # làm chú thích ảnh. `target` trả về cùng payload để mảnh bằng chứng biết ảnh chụp gì.
            target, caption = normalize_capture_target(args)
            data = await self.request('/__box/capture', {'target': target, 'output': 'base64',
                                                         **box_identity(session, step, tool_call_id)})
            raw = base64.b64decode(data.get('data', ''))
            dimensions = image_dimensions_from_bytes(raw)
            if not dimensions:
                raise ValueError('Sandbox returned no valid screenshot')
            payload = {'content': f'Sandbox screenshot {dimensions[0]}x{dimensions[1]}', 'artifact': data.get('path'),
                       'image': data['data'], 'mime': 'image/png', 'dimensions': dimensions,
                       'target': target}
            if caption:
                payload['caption'] = caption
            # F6: chuyển tiếp ghi chú kích thước desktop để `execute()` ghi vào nhật ký DEV.
            for key in ('desktopRestored', 'desktopWarning'):
                if key in data:
                    payload[key] = data[key]
            return payload
        if name == 'computer_screen_record':
            action = args['action']
            rid = self.recordings.get(session)
            if action == 'status':
                state = await self.request('/__box/record/status')
                return {'active': any(r.get('recordingId') == rid for r in state.get('active', [])), 'recordingId': rid}
            if action == 'start':
                if rid:
                    raise ValueError('Recording already owned by this session; stop first')
                # A3: ghi hình cũng theo phiên (xem `computer_screen_capture` ở trên).
                data = await self.request('/__box/record/start', {'target': {'kind': 'screen'},
                                                                **box_identity(session, step, tool_call_id)})
                self.recordings[session] = data['recordingId']
                return data
            if action == 'stop':
                if not rid:
                    raise ValueError('No recording owned by this session')
                data = await self.request('/__box/record/stop', {'recordingId': rid})
                self.recordings.pop(session, None)
                return data
            raise ValueError('Unknown recording action')
        # Worker executes inside Docker; no interpolation of model text into the host shell.
        if not self._worker_synced:
            self._sync_worker()
        # W8.A4.3: `root` là worktree của run/node (worker kiểm lại đường dẫn); không có thì giữ workspace.
        workdir = '/home/agent/workspace' + ('/' + root if root else '')
        proc = await asyncio.create_subprocess_exec('docker', 'exec', '-i', '--user', 'agent',
            '--workdir', workdir, self.container, '/opt/pw-driver/bin/python3', CONTAINER_WORKER_PATH,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            payload = {'name': name, 'args': args, 'session': session, 'turn': turn, 'step': step,
                       'toolCallId': tool_call_id, **({'root': root} if root else {})}
            out, err = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), timeout=140)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            if name == 'terminal_exec':
                await self._execute('__cancel', {}, session)
            raise
        if proc.returncode:
            err_msg = err.decode(errors='replace')
            if not retry and (CONTAINER_WORKER_PATH in err_msg or 'No such file' in err_msg or "can't open file" in err_msg):
                self._worker_synced = False
                self._sync_worker()
                return await self._execute(name, args, session, turn=turn, step=step, tool_call_id=tool_call_id,
                                           retry=True, **({'root': root} if root else {}))
            raise RuntimeError('Sandbox unavailable: ' + err_msg[:500])
        return json.loads(out)

    async def cleanup(self, session):
        if session in self.recordings:
            try:
                await self.execute('computer_screen_record', {'action': 'stop'}, session)
            except Exception:
                # Keep ownership for an explicit later stop; never report a saved artifact.
                return False
        return True
