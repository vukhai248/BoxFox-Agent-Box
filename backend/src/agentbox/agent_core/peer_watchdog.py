"""T10 đợt 2 — Watchdog sổ con: lưới an toàn cuối cùng cho phiên con.

Vì sao cần một vòng quét riêng thay vì tin vào đường logic: mọi đường dọn con hiện có (`reap_children`
lúc lượt cha đóng, callback của `delegate_task`, `stop` của người dùng) đều nằm TRONG tiến trình đang
chạy lượt. Khi chính tiến trình đó chết — bị giết, mất điện, hoặc một `await` không bao giờ trả về —
thì không đường nào chạy, và sổ con còn lại những hàng `status='started'` vĩnh viễn: giao diện hiển
thị "đang chạy" cho những phiên đã chết, và người chờ chúng (`await_children`) chờ một việc không tới.

Bốn luật:

1. `started` mà `now - started > CHILD_WALL_MAX_SECONDS` ⇒ huỷ task, ghi `failed/WATCHDOG_TIMEOUT`.
2. `started` mà phiên CHA không còn tồn tại, hoặc không còn `running`/`awaiting_decision` ⇒
   `failed/ORPHAN`. Cha đã xong thì không ai đọc kết quả của con nữa.
3. Hàng có `waiting_since` cũ hơn `PEER_WAIT_SAFETY_SECONDS + PEER_WAIT_FORCE_GRACE_SECONDS` ⇒
   ĐÁNH THỨC CƯỠNG BỨC người đang chờ. Người chờ chạy tiếp bình thường và lượt KHÔNG bị đánh
   `failed`: nó nhận một câu trả lời `timeout` với dữ liệu đang có. Đây là lưới thứ ba, sau lưới
   riêng của `wait_for_peers` (T9).
4. Nhịp quét ĐẦU TIÊN sau khởi động: mọi hàng `started` ⇒ `failed/RESTART`. Thao tác tool không
   được chạy lại, nên không hồi sinh — cùng luật với `UPDATE sessions SET status='interrupted'`
   lúc mở DB.

Mọi hành động đi qua `child_close_once`: một `UPDATE … WHERE session_id=? AND status='started'` và
CHỈ người nhận `rowcount == 1` mới phát event `child`. Hai watchdog chạy chồng (một tiến trình cũ
chưa chết hẳn), hoặc watchdog với callback của `delegate_task`, cùng gọi thì mỗi hàng vẫn chỉ có
đúng một event. Một nhịp KHÔNG gói trong một giao dịch dài: mỗi hàng là một giao dịch ngắn, nên
vòng quét không giữ khoá của SQLite dùng chung qua nhiều hàng.
"""

import asyncio
import time

from .limits import (CHILD_WALL_MAX_SECONDS, PEER_WAIT_FORCE_GRACE_SECONDS, PEER_WAIT_SAFETY_SECONDS,
                     WATCHDOG_ORPHAN_REASON, WATCHDOG_RESTART_REASON, WATCHDOG_TICK_SECONDS,
                     WATCHDOG_TIMEOUT_REASON)
from ..observability.system_log import system_log

# Phiên cha còn sống thì con của nó còn có người đọc kết quả. `idle` KHÔNG nằm trong đây: một phiên
# `idle` là phiên đang chờ người dùng, không phải một lượt đang chạy — con của nó đã bị `reap_children`
# dọn lúc lượt đóng.
PARENT_ALIVE_STATES = frozenset({'running', 'awaiting_decision'})


class PeerWatchdog:
    """Vòng quét sổ con. `runtime` là tuỳ chọn: thiếu nó thì vẫn quét được (chỉ không huỷ task được)."""

    def __init__(self, store, runtime=None, tick=WATCHDOG_TICK_SECONDS,
                 wall_max=CHILD_WALL_MAX_SECONDS, now=time.time):
        self.store, self.runtime = store, runtime
        self.tick, self.wall_max = tick, wall_max
        self.now = now                # tiêm được đồng hồ ⇒ test không phải chờ 900 giây
        self.first_scan = True
        self.sweeps = 0
        self.stopping = False
        self.task = None

    # ------------------------------------------------------------------ vòng lặp
    async def run(self):
        """Quét một lần rồi lặp mỗi `tick`. Không bao giờ ném: một nhịp hỏng không được giết vòng."""
        while not self.stopping:
            try:
                self.sweep()
            except Exception as exc:  # pragma: no cover - chốt chặn cuối của vòng quét
                system_log.write('watchdog.sweep_failed', level='warn', message=str(exc)[:300])
            try:
                await asyncio.sleep(self.tick)
            except asyncio.CancelledError:
                return

    def start(self):
        """Dựng task vòng quét. Gọi hai lần thì lần thứ hai vô hại."""
        if self.task is None or self.task.done():
            self.stopping = False
            self.task = asyncio.ensure_future(self.run())
        return self.task

    async def stop(self):
        """Dừng vòng quét và chờ nó đóng hẳn — `on_cleanup` không được để lại task mồ côi."""
        self.stopping = True
        task, self.task = self.task, None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except BaseException:  # noqa: BLE001 - đóng là đóng, kể cả khi chính nó đang lỗi
                pass

    # ------------------------------------------------------------------ một nhịp
    def sweep(self):
        """Một nhịp quét. Trả bản gọn `{'timeout','orphan','restart','forced'}` cho log và test."""
        self.sweeps += 1
        first, self.first_scan = self.first_scan, False
        now = self.now()
        report = {'timeout': [], 'orphan': [], 'restart': [], 'forced': []}
        for row in self.store.live_children():
            child_id = row['session_id']
            if first:
                # Luật 4 đứng TRƯỚC ba luật kia: hàng còn `started` từ lần chạy trước là chết vì
                # tiến trình, không phải vì quá hạn — và lý do phải nói đúng chuyện đã xảy ra.
                if self._close(child_id, row, WATCHDOG_RESTART_REASON):
                    report['restart'].append(child_id)
                continue
            if row['waiting_since'] is not None and \
                    float(row['waiting_since']) < now - (PEER_WAIT_SAFETY_SECONDS
                                                         + PEER_WAIT_FORCE_GRACE_SECONDS):
                # Đang chờ thì chưa phải mồ côi, kể cả khi hàng đã cũ: nó có việc để làm ngay khi
                # được đánh thức. Chỉ cần đánh thức cưỡng bức, KHÔNG đóng hàng.
                if self._force_wake(child_id):
                    report['forced'].append(child_id)
                continue
            if float(row['started'] or 0) < now - self.wall_max:
                if self._close(child_id, row, WATCHDOG_TIMEOUT_REASON, cancel=True):
                    report['timeout'].append(child_id)
                continue
            graph = getattr(self.runtime, 'work_graph', None)
            controller = getattr(graph, 'continuations', None)
            owned = bool(controller and controller.owns_child(child_id))
            if owned:
                try:
                    self.store.get(row['parent_id'])
                except KeyError:
                    owned = False
            if not owned and not self._parent_alive(row['parent_id']):
                if self._close(child_id, row, WATCHDOG_ORPHAN_REASON, cancel=True):
                    report['orphan'].append(child_id)
        if any(report.values()):
            system_log.write('watchdog.sweep', level='warn', sweeps=self.sweeps,
                             timeout=len(report['timeout']), orphan=len(report['orphan']),
                             restart=len(report['restart']), forced=len(report['forced']))
        return report

    # ------------------------------------------------------------------ ba hành động
    def _close(self, child_id, row, reason, cancel=False):
        """Đóng MỘT hàng sổ con còn `started`. `False` nghĩa là người khác đã đóng trước."""
        # Cùng lý do như T7: con bị cắt giữa đường không có `finish`, chi phí đã tiêu đọc từ luồng
        # của nó để bộ số theo lượt của cha không đếm thiếu.
        steps, tokens = self.store.child_usage_from_events(child_id)
        closed = self.store.child_close_once(child_id, 'failed', reason=reason, steps_used=steps,
                                             output_tokens=tokens)
        if closed is None:
            return False
        if cancel:
            self._cancel_task(child_id)
        session = self.store.get(child_id)
        if session and session.get('status') in ('running', 'idle'):
            self.store.save(child_id, session['messages'], 'cancelled')
        parent_id = row.get('parent_id')
        if parent_id:
            self.store.emit(parent_id, 'child', {
                'sessionId': child_id, 'role': row.get('role'), 'status': 'failed',
                'turn': row.get('parent_turn'), 'step': row.get('spawn_step'), 'goal': row.get('goal'),
                'reason': reason, 'watchdog': True, 'is_error': True, 'answerChars': 0,
                'stepsUsed': steps, 'outputTokens': tokens})
        system_log.write('watchdog.child_closed', level='warn', session_id=child_id,
                         parent=parent_id, reason=reason, sweeps=self.sweeps)
        return True

    def _cancel_task(self, child_id):
        """Huỷ task của con rồi nhả slot fan-out của cha nó — NHẢ THEO CON, nên chỉ một lần.

        Slot mua một lần cho mỗi con nhưng có hai đường nhả (đây và callback lúc task đóng), nên
        `release_child_slot` phải nhận `child_id`. Bản trước gọi `release_child_slot(parent_id)`
        trần: `asyncio.Semaphore` nhận lần nhả thừa, và cả trần toàn cục lẫn trần theo cha bị vượt
        trong im lặng (BUG-53).
        """
        if self.runtime is None:
            return
        parent_id = None
        try:
            task = self.runtime.tasks.pop(child_id, None)
            if task is not None and not task.done():
                task.cancel()
            parent_id = (self.store.child(child_id) or {}).get('parent_id')
        except Exception as exc:  # pragma: no cover - không được để một task lạ giết nhịp quét
            system_log.write('watchdog.cancel_failed', level='warn', session_id=child_id,
                             message=str(exc)[:200])
            return
        if parent_id:
            try:
                self.runtime.release_child_slot(parent_id, child_id)
            except Exception:  # pragma: no cover
                pass

    def _parent_alive(self, parent_id):
        """Cha còn cơ hội đọc kết quả của con không — `runtime.py` giữ từ vựng trạng thái."""
        if not parent_id:
            return False
        try:
            parent = self.store.get(parent_id)
        except KeyError:
            return False
        return bool(parent) and parent.get('status') in PARENT_ALIVE_STATES

    def _force_wake(self, child_id):
        """Đánh thức người đang chờ (luật 3). Không có runtime thì thôi, hàng còn nguyên."""
        if self.runtime is None:
            return False
        self.runtime.peer_force_wake.add(child_id)
        woken = self.runtime.notify_peer_delivery(child_id)
        system_log.write('watchdog.wait_forced', level='warn', session_id=child_id, waiters=woken,
                         sweeps=self.sweeps)
        return True
