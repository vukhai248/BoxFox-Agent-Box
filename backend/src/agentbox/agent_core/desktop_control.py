"""Điều khiển desktop đồng thời giữa người và agent — lease, epoch, hàng rào stale (H7).

Module này là **logic thuần**: nó không gọi DLL, không đọc `ctypes`. Mọi thứ chạm hệ điều hành đi qua
`platform` được tiêm vào (xem `sandbox/win/windows_platform.py`), nên toàn bộ hành vi ở đây kiểm được
trên máy Linux bằng nền tảng giả — đúng cách H5/H6 đã làm.

Ba thứ module này giữ, theo ADR-0002 ("Đã chọn: kết hợp 1 + 2"):

1. **Lease có epoch** — ai đang điều khiển desktop. Tệp `desktop_lease.json` trong profile là nguồn sự
   thật; **không đọc được ⇒ fail-closed về tay người**, và epoch **không bao giờ lùi** (chống replay).
2. **Hàng rào epoch** — mỗi hành động nhận một token mang `epoch` + `generation`; trước khi gửi input và
   trước khi lưu ảnh chụp, `fence()` kiểm lại. Lệch ⇒ vứt kết quả, không gửi gì.
3. **Phát hiện người thật sự chạm máy** — hook chuột/bàn phím bỏ qua sự kiện có cờ injected (input do
   chính ta tiêm), `GetLastInputInfo` làm lưới đỡ; thấy người thật ⇒ tự động trả quyền về `human`.

Cộng thêm hai thứ mà "đã gửi" không được phép giả vờ là "đã thành công": **thang xác minh** (2 mẫu ổn
định liên tiếp) và **chống lặp ảnh** (`screen_unchanged`).
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..sandbox.win import errors as win_errors

LEASE_FILENAME = 'desktop_lease.json'
HOLDER_HUMAN = 'human'
HOLDER_AGENT = 'agent'
HOLDERS = (HOLDER_HUMAN, HOLDER_AGENT)

#: Tên mutex kernel — hai tiến trình BoxFox không được tiêm xen kẽ vào nhau.
MUTEX_NAME = 'Local\\BoxFoxDesktopInput-v1'

#: Nhịp lấy mẫu `GetLastInputInfo`. Rẻ (một lời gọi), không cần hook.
IDLE_POLL_SECONDS = 0.25

#: Số mẫu ổn định liên tiếp để coi một trạng thái là "đã xác minh".
STABLE_SAMPLES = 2

#: Trùng ảnh liên tiếp quá số này ⇒ gắn `screen_unchanged` để model không lặp vô hạn.
SCREEN_UNCHANGED_LIMIT = 2

#: Trần thời gian chờ mutex — không xếp hàng, không chờ dài.
MUTEX_TIMEOUT_MS = 0

#: Hành động đã gửi nhưng KHÔNG được phép tự thử lại.
NO_RETRY_EFFECTS = ('partial', 'unverifiable', 'suspected_noop')

EFFECTS = ('confirmed', 'partial', 'unverifiable', 'suspected_noop', 'refused')


def _now_iso():
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + 'Z'


def _read_json(path):
    """`(data, error)` — thiếu tệp là bình thường; hỏng thì trả lỗi đọc được."""
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


class DesktopLease:
    """`desktop_lease.json` — ai đang giữ quyền điều khiển, và đang ở epoch nào.

    Hai bất biến, cả hai đều có test:

    - **Fail-closed:** tệp **có mà không đọc được** (hỏng, thiếu trường, holder lạ) ⇒ `holder = human`.
      Chưa có tệp là chuyện khác: chưa ai xin quyền thì agent giữ mặc định — nếu không, agent không bao
      giờ lấy được quyền trên một máy mới.
    - **Epoch đơn điệu:** epoch chỉ tăng. Một tệp cũ (hoặc bị khôi phục từ backup) không được phép hạ
      epoch xuống, vì như vậy hành động đã nhận từ epoch cao sẽ "hợp lệ" trở lại.
    """

    def __init__(self, profile_dir, *, clock=_now_iso):
        self.path = Path(profile_dir) / LEASE_FILENAME
        self.clock = clock
        self._epoch = 0
        self._state = {'holder': HOLDER_AGENT, 'viewerId': None, 'since': None,
                       'reason': 'chưa có tệp lease — agent giữ mặc định', 'epoch': 0}

    # -- đọc ----------------------------------------------------------------

    def read(self):
        """Đọc tệp và trả snapshot đã chuẩn hoá. Không bao giờ ném."""
        exists = self.path.exists()
        data, error = _read_json(self.path)
        if error or (exists and not data):
            state = {'holder': HOLDER_HUMAN, 'viewerId': None, 'since': None,
                     'reason': error or 'tệp lease rỗng — coi như không đọc được', 'epoch': self._epoch}
            self._state = state
            return dict(state)
        if not exists:
            state = {'holder': HOLDER_AGENT, 'viewerId': None, 'since': None,
                     'reason': 'chưa có tệp lease — agent giữ mặc định', 'epoch': self._epoch}
            self._state = state
            return dict(state)
        holder = str(data.get('holder') or '').strip().lower()
        if holder not in HOLDERS:
            holder = HOLDER_HUMAN
        epoch = data.get('epoch')
        epoch = int(epoch) if isinstance(epoch, int) and epoch >= 0 else 0
        self._epoch = max(self._epoch, epoch)
        state = {
            'holder': holder,
            'viewerId': data.get('viewerId') or None,
            'since': data.get('since') or None,
            'reason': str(data.get('reason') or ''),
            'epoch': self._epoch,
        }
        self._state = state
        return dict(state)

    def snapshot(self):
        return self.read()

    # -- ghi ----------------------------------------------------------------

    def _commit(self, holder, reason, viewer_id=None):
        """Tăng epoch rồi ghi. Trả `(snapshot, error)`."""
        self.read()
        self._epoch += 1
        state = {'holder': holder, 'viewerId': viewer_id, 'since': self.clock(),
                 'reason': str(reason or ''), 'epoch': self._epoch}
        error = _write_json(self.path, state)
        self._state = state
        return dict(state), error

    def acquire(self, reason, *, viewer_id=None, force=False):
        """Xin quyền cho agent. Trả `(ok, snapshot_hoặc_mã_lỗi, error)`.

        Người đang giữ quyền thì **không** tự lấy được: chỉ `force=True` (nút "Trả quyền cho agent" của
        người dùng) mới chuyển được. Đây là lựa chọn 1 của ADR-0002 ở dạng nhìn thấy được.
        """
        state = self.read()
        if state['holder'] == HOLDER_AGENT:
            return True, state, ''
        if not force:
            return False, win_errors.HUMAN_HAS_CONTROL, ''
        state, error = self._commit(HOLDER_AGENT, reason, viewer_id)
        return True, state, error

    def release_to_human(self, reason, *, viewer_id=None):
        """Trả quyền về người. Tăng epoch, kể cả khi đang ở tay người (epoch phải tiến)."""
        state, error = self._commit(HOLDER_HUMAN, reason, viewer_id)
        return state, error

    def bump(self, reason):
        """Tăng epoch mà giữ nguyên người giữ — dùng cho huỷ khẩn cấp (mọi hành động đang chờ chết)."""
        state = self.read()
        state, error = self._commit(state['holder'], reason, state.get('viewerId'))
        return state, error

    def holder(self):
        return self.read()['holder']

    def epoch(self):
        return self.read()['epoch']


@dataclass
class ActionToken:
    """Phiếu cho một hành động đã được duyệt. Mang `epoch` + `generation` tại thời điểm cấp."""

    action: str
    target: dict = field(default_factory=dict)
    epoch: int = 0
    generation: int = 0
    geometry_revision: object = None
    mutex_held: bool = False
    issued_at: str = ''

    def as_dict(self):
        return {'action': self.action, 'target': self.target, 'epoch': self.epoch,
                'generation': self.generation, 'geometryRevision': self.geometry_revision,
                'mutexHeld': self.mutex_held, 'issuedAt': self.issued_at}


class InputMutex:
    """Mutex kernel đặt tên, chỉ giữ trong lúc hành động + dọn dẹp.

    Không xếp hàng: `WaitForSingleObject(handle, 0)` trả `WAIT_TIMEOUT` nghĩa là tiến trình BoxFox khác
    đang tiêm ⇒ `CONTROL_BUSY`. Nền tảng không hỗ trợ mutex cũng là `CONTROL_BUSY` (fail closed), không
    phải "cứ chạy tiếp".
    """

    def __init__(self, platform, *, name=MUTEX_NAME, timeout_ms=MUTEX_TIMEOUT_MS):
        self.platform = platform
        self.name = name
        self.timeout_ms = timeout_ms
        self.handle = None

    def acquire(self):
        """Trả `(ok, mã_lỗi)`. Giữ được thì `self.handle` khác `None`."""
        create = getattr(self.platform, 'create_mutex', None)
        wait = getattr(self.platform, 'acquire_mutex', None)
        if create is None or wait is None:
            return False, win_errors.CONTROL_BUSY
        handle = create(self.name)
        if not handle:
            return False, win_errors.CONTROL_BUSY
        if not wait(handle, self.timeout_ms):
            close = getattr(self.platform, 'close_handle', None)
            if close is not None:
                close(handle)
            return False, win_errors.CONTROL_BUSY
        self.handle = handle
        return True, ''

    def release(self):
        if self.handle is None:
            return
        release = getattr(self.platform, 'release_mutex', None)
        close = getattr(self.platform, 'close_handle', None)
        if release is not None:
            release(self.handle)
        if close is not None:
            close(self.handle)
        self.handle = None


class DesktopControl:
    """Bộ điều phối mà executor gọi: lease, hàng rào, phát hiện người, huỷ, xác minh.

    `platform` được tiêm; mọi phương thức ở đây chạy được trên nền tảng giả.
    """

    def __init__(self, *, profile_dir, platform, lease=None, clock=_now_iso, now=None):
        self.platform = platform
        self.lease = lease or DesktopLease(profile_dir, clock=clock)
        self.clock = clock
        self.now = now or (lambda: time.time())
        self.generation = 0
        self.mutex = InputMutex(platform)
        self.hooks_installed = False
        self.hook_notes = []
        self.last_idle = None
        self._screen_hashes = {}
        self._last_input_tick = 0

    # -- lease ---------------------------------------------------------------

    def snapshot(self):
        state = self.lease.snapshot()
        state['generation'] = self.generation
        state['hooksInstalled'] = self.hooks_installed
        state['mutexHeld'] = self.mutex.handle is not None
        state['mutexName'] = self.mutex.name
        return state

    def agent_lease(self, reason, *, viewer_id=None, force=False):
        """Điều kiện tiên quyết của MỌI thao tác CUA, kể cả chụp màn hình.

        `force=True` CHỈ dành cho nút "Trả quyền cho agent" của người dùng — không có đường nào
        để agent tự gọi nó. Mọi lời gọi khác để mặc định.
        """
        ok, state, error = self.lease.acquire(reason, viewer_id=viewer_id, force=force)
        if not ok:
            return False, state, error
        return True, state, error

    def release_to_human(self, reason, *, viewer_id=None):
        self.generation += 1
        return self.lease.release_to_human(reason, viewer_id=viewer_id)

    # -- phát hiện người thật sự chạm máy ------------------------------------

    def install_hooks(self):
        """Cài hook chuột + bàn phím. Thất bại ⇒ **fail-closed**, không cấp quyền điều khiển."""
        set_keyboard = getattr(self.platform, 'set_keyboard_hook', None)
        set_mouse = getattr(self.platform, 'set_mouse_hook', None)
        if set_keyboard is None or set_mouse is None:
            return False, win_errors.UNSUPPORTED_IN_HOST_MODE
        keyboard = set_keyboard(self._keyboard_hook())
        mouse = set_mouse(self._mouse_hook())
        if not keyboard or not mouse:
            return False, win_errors.OS_PERMISSION_REQUIRED
        self.hooks_installed = True
        return True, ''

    def uninstall_hooks(self):
        for name in ('unhook_keyboard', 'unhook_mouse'):
            unhook = getattr(self.platform, name, None)
            if unhook is not None:
                unhook()
        self.hooks_installed = False

    def _keyboard_hook(self):
        """Callback cho `WH_KEYBOARD_LL` — loại sự kiện được ghim ở đây, không đoán từ `wparam`."""
        return lambda code, wparam, lparam: self._on_hook('keyboard', code, wparam, lparam)

    def _mouse_hook(self):
        return lambda code, wparam, lparam: self._on_hook('mouse', code, wparam, lparam)

    def _on_hook(self, kind, code, wparam, lparam):
        """Callback của hook. **Luôn** gọi `CallNextHookEx` — không bao giờ nuốt phím của người dùng."""
        try:
            if code >= 0:
                parse = getattr(self.platform, 'hook_event', None)
                event = parse(kind, wparam, lparam) if parse is not None else {}
                if kind == 'keyboard' and self.check_escape(event):
                    return self._call_next(code, wparam, lparam)
                self.note_hook_event(kind, event)
        finally:
            return self._call_next(code, wparam, lparam)

    def _call_next(self, code, wparam, lparam):
        call_next = getattr(self.platform, 'call_next_hook', None)
        if call_next is None:
            return 0
        return call_next(code, wparam, lparam)

    def note_own_input(self):
        """Ghi nhận mốc input vừa được CHÍNH TA tiêm, để `poll_idle` không đọc nó là người thật."""
        read = getattr(self.platform, 'last_input_tick', None)
        if read is not None:
            self._last_input_tick = int(read() or 0)
        return self._last_input_tick

    def note_hook_event(self, kind, event):
        """Một sự kiện hook. Trả `True` khi đó là **người thật** (không có cờ injected).

        Input do chính ta tiêm luôn mang cờ injected, nên nó không được phép tự trả quyền về tay người —
        nếu không, mọi cú click của agent sẽ tự huỷ chính nó.
        """
        event = event or {}
        if event.get('injected'):
            return False
        self.release_to_human('người dùng chạm %s' % ('bàn phím' if kind == 'keyboard' else 'chuột'))
        return True

    def poll_idle(self):
        """Lưới đỡ khi hook không bắt được (hook chạy trên thread riêng).

        Trả `True` khi phát hiện người vừa tương tác: `GetLastInputInfo` tiến lên trong lúc ta đang chờ,
        mà lần tiêm cuối của ta thì cũ hơn mốc đó.
        """
        read = getattr(self.platform, 'last_input_tick', None)
        if read is None:
            return False
        tick = int(read() or 0)
        if not tick:
            return False
        previous = self._last_input_tick
        self._last_input_tick = tick
        idle_seconds = getattr(self.platform, 'idle_seconds', None)
        self.last_idle = idle_seconds() if idle_seconds is not None else None
        if not previous or tick == previous:
            return False
        if self.lease.holder() != HOLDER_AGENT:
            return False
        self.release_to_human('input hệ thống đổi trong lúc agent đang giữ quyền')
        return True

    def check_escape(self, event):
        """`VK_ESCAPE` không-injected ⇒ huỷ khẩn cấp. Trả `True` khi đã huỷ."""
        event = event or {}
        if event.get('injected'):
            return False
        if int(event.get('vkey') or 0) != 0x1B:
            return False
        self.emergency_stop('người dùng bấm Esc')
        return True

    # -- hàng rào ------------------------------------------------------------

    def begin_action(self, action, target=None, *, geometry_revision=None, take_mutex=True):
        """Cấp token cho một hành động đã qua cổng duyệt.

        Trả `(token, mã_lỗi)`. Lấy được mutex kernel thì token mang `mutexHeld = True`; không lấy được
        ⇒ `CONTROL_BUSY` và **không** có token.
        """
        ok, state, _ = self.agent_lease('agent bắt đầu %s' % action)
        if not ok:
            return None, win_errors.HUMAN_HAS_CONTROL
        if take_mutex:
            held, code = self.mutex.acquire()
            if not held:
                return None, code
        return ActionToken(action=action, target=dict(target or {}), epoch=state['epoch'],
                           generation=self.generation, geometry_revision=geometry_revision,
                           mutex_held=self.mutex.handle is not None, issued_at=self.clock()), ''

    def fence(self, token):
        """Kiểm lại NGAY trước khi gửi input / lưu ảnh. Trả `''` khi còn hợp lệ, hoặc mã lỗi.

        Đây là lựa chọn 2 của ADR-0002: cờ "perception fresh" ở client không đóng được cuộc đua giữa lần
        kiểm tra và lần gửi; chỉ lần kiểm tra **tại điểm hành động** mới đóng được.
        """
        state = self.lease.snapshot()
        if state['holder'] != HOLDER_AGENT:
            return win_errors.HUMAN_HAS_CONTROL
        if token is None:
            return win_errors.HUMAN_TOOK_OVER
        if state['epoch'] != token.epoch or self.generation != token.generation:
            return win_errors.HUMAN_TOOK_OVER
        return ''

    def end_action(self, token, *, effect='refused', verified=None, code='', note='',
                   escalation=None, route='refused'):
        """Đóng một hành động: nhả mutex, trả kết quả có cấu trúc.

        `ok` ở đây **chỉ** nghĩa "đã gửi được". `effect` mới là thứ nói hành động có tác dụng.
        """
        self.mutex.release()
        if route == 'send_input' and effect != 'refused':
            self.note_own_input()
        if effect not in EFFECTS:
            effect = 'unverifiable'
        return {
            'ok': effect not in ('refused',),
            'action': token.action if token else '',
            'target': token.target if token else {},
            'route': route,
            'effect': effect,
            'verified': verified,
            'escalation': escalation or {'recommended': 'none', 'reason': ''},
            'code': code,
            'note': note,
            'lease_epoch': token.epoch if token else 0,
            'geometry_revision': token.geometry_revision if token else None,
        }

    def emergency_stop(self, reason):
        """Nút Dừng / Esc: tăng epoch + generation, nhả input đang giữ, đưa lease về người."""
        self.generation += 1
        # `release_stuck_input` có thể nằm ở mô-đun `win/input.py` chứ không phải trên nền tảng; thiếu
        # nó không được phép làm hỏng cú Dừng.
        release = getattr(self.platform, 'release_stuck_input', None)
        released = 0
        if release is not None:
            try:
                released = int(release() or 0)
            except Exception:  # pragma: no cover - nhả input không được phép làm hỏng cú Dừng
                released = 0
        self.mutex.release()
        state, error = self.lease.release_to_human(reason)
        return {'stopped': True, 'reason': reason, 'released': released,
                'epoch': state['epoch'], 'generation': self.generation, 'error': error}

    # -- xác minh ------------------------------------------------------------

    def verify_state(self, sampler, expect):
        """Hai mẫu ổn định liên tiếp mới là `confirmed`.

        `sampler()` trả trạng thái đọc lại (qua UIA/AX). `expect(state)` trả `True`/`False`/`None`.
        Chỉ thoả ở mẫu cuối ⇒ `unknown` — không được phép gọi đó là thành công.
        """
        samples = []
        for _ in range(STABLE_SAMPLES):
            state = sampler()
            verdict = expect(state) if callable(expect) else state == expect
            samples.append({'state': state, 'verdict': verdict})
        verdicts = [sample['verdict'] for sample in samples]
        if all(item is True for item in verdicts):
            return {'verified': True, 'effect': 'confirmed', 'samples': samples}
        if any(item is None for item in verdicts) and not any(item is False for item in verdicts):
            return {'verified': None, 'effect': 'unverifiable', 'samples': samples}
        if all(item is False for item in verdicts):
            return {'verified': False, 'effect': 'suspected_noop', 'samples': samples}
        return {'verified': False, 'effect': 'partial', 'samples': samples}

    @staticmethod
    def may_retry(effect):
        """`partial`/`unverifiable`/`suspected_noop` **không bao giờ** tự thử lại."""
        return effect not in NO_RETRY_EFFECTS

    def screen_hash(self, data, target, *, session=''):
        """Băm ảnh theo (phiên, đích). Trùng liên tiếp > ngưỡng ⇒ `screen_unchanged`.

        Trả `(digest, unchanged)`; `unchanged = True` là tín hiệu để model đổi cách làm thay vì chụp lại
        mãi một khung hình.
        """
        digest = hashlib.sha256(bytes(data or b'')).hexdigest()
        key = '%s|%s' % (session, json.dumps(target or {}, sort_keys=True, ensure_ascii=False))
        previous, count = self._screen_hashes.get(key, (None, 0))
        if previous == digest:
            count += 1
        else:
            count = 1
        self._screen_hashes[key] = (digest, count)
        return digest, count > SCREEN_UNCHANGED_LIMIT
