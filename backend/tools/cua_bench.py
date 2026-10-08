"""Đo **latency** và **token** của CUA trên Linux/X11 — công cụ để tìm chỗ chưa tối ưu.

Chạy trên máy có X server (không phải bài kiểm tự động; xem `docs/testing/cua-latency-token.md`):

    cd backend && DISPLAY=:1 .venv/bin/python tools/cua_bench.py primitives --json /var/tmp/bench.json
    cd backend && DISPLAY=:1 .venv/bin/python tools/cua_bench.py product --json /var/tmp/bench.json
    cd backend && DISPLAY=:1 .venv/bin/python tools/cua_bench.py budget --baseline /var/tmp/bench.json

Ba nhóm số đo, theo đúng ba câu hỏi cần trả lời:

1. **Latency từng thao tác** — nguyên thuỷ (tầng nền tảng) và qua đúng đường sản phẩm
   (``HostExecutor.execute``). Kèm **số tiến trình con** mỗi thao tác: trên X11 mỗi lời gọi
   `xwininfo`/`xprop`/`xdotool`/`import` là một tiến trình, nên đếm nó là cách rẻ nhất để thấy
   chỗ nào đang ngốn CPU.
2. **Latency đầu-cuối một việc CUA** — từ lúc giao việc đến lúc xong (``case``), vì người dùng
   cảm nhận con số này chứ không cảm nhận từng thao tác.
3. **Token** — kích thước payload mà model nhận sau mỗi thao tác (JSON + ảnh), quy ra token ước
   lượng. Ảnh chụp cửa sổ là phần đắt nhất, nên harness tách riêng "token chữ" và "token ảnh".

Ngân sách (`budget`) so một lần chạy với một lần chạy trước và **thoát mã 1** khi vượt trần, để
dùng được như một chốt chặn hồi quy trong CI hoặc trước khi phát hành.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from agentbox.sandbox.x11 import capture as xc          # noqa: E402
from agentbox.sandbox.x11 import input as xi            # noqa: E402
from agentbox.sandbox.x11 import platform as xp         # noqa: E402
from agentbox.sandbox.host_executor import HostExecutor  # noqa: E402

#: Ước lượng token cho phần chữ: ~4 ký tự một token (đúng cho JSON/tiếng Anh, rộng rãi cho tiếng Việt).
CHARS_PER_TOKEN = 4

#: Ước lượng token cho ảnh: công thức quen dùng của các API thị giác (một token mỗi ~750 điểm ảnh).
PIXELS_PER_VISION_TOKEN = 750

#: Trần mặc định cho `budget` (ms, p95). Vượt trần nào là in ra và thoát mã 1.
#:
#: Đặt khoảng 3 lần p95 đo được ngày 08/10/2026 trên XFCE 1920x1080 (số trong ngoặc): đủ rộng cho
#: nhiễu của máy ảo, đủ chặt để bắt một hồi quy thật — các lỗi đã đo được trong đợt này đều vượt
#: trần rõ ràng (bấm bị chốt chờ: 5 000 ms; `click` trước khi vá: 252 ms).
DEFAULT_BUDGET_MS = {
    'primitives.get_foreground_window': 10,          # 1,3
    'primitives.get_cursor_pos': 10,                 # 2,8
    'primitives.get_window_rect': 10,                # 0,0 (đã có đệm hình học)
    'primitives.window_from_point': 10,              # 1,3
    'primitives.window_properties': 10,              # 2,0
    'primitives.capture_window': 150,                # 42
    'primitives.capture_screen': 150,                # 52
    'primitives.press_key': 100,                     # 26
    'primitives.click': 100,                         # 23
    'primitives.type_text_200': 2500,                # 1 339 (trần thấp hơn sẽ đỏ vì máy ảo chậm)
    'product.key': 150,                              # 54
    'product.click': 150,                            # 55
    'product.type_text_200': 2500,                   # 1 365
    'product.screenshot': 150,                       # 20
    # Bốn thao tác cử chỉ (08/10/2026). `hold` gồm cả thời gian giữ, nên trần = thời gian giữ + 500 ms.
    'product.scroll_5': 400,                         # 112
    'product.drag_12': 700,                          # 258
    'product.hold_0_5': 1000,                        # ~564 (500 ms là thời gian giữ)
    'product.stroke_61': 1600,                       # 727
}


def text_tokens(text: str) -> int:
    """Token ước lượng cho một đoạn chữ (làm tròn lên, tối thiểu 1)."""
    return max(1, -(-len(text) // CHARS_PER_TOKEN))


def image_tokens(width: int, height: int) -> int:
    """Token ước lượng cho một ảnh chụp."""
    return max(1, int(width * height / PIXELS_PER_VISION_TOKEN))


def _image_size(payload) -> tuple[int, int] | None:
    """Kích thước ảnh trong payload công cụ, nếu payload có ảnh.

    Payload chụp màn hình của sản phẩm ghi kích thước ở ``captureSize`` (dict) và ``dimensions``
    (mảng ``[w, h]``); lớp nền tảng ghi ``width``/``height``. Đọc cả ba để không phải sửa lại khi
    payload đổi chỗ.
    """
    if not isinstance(payload, dict):
        return None
    data = payload.get('data') if isinstance(payload.get('data'), dict) else payload
    for width_key, height_key in (('width', 'height'), ('imageWidth', 'imageHeight')):
        width, height = data.get(width_key), data.get(height_key)
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return int(width), int(height)
    size = data.get('captureSize')
    if isinstance(size, dict) and size.get('width') and size.get('height'):
        return int(size['width']), int(size['height'])
    dimensions = data.get('dimensions')
    if isinstance(dimensions, (list, tuple)) and len(dimensions) == 2:
        width, height = dimensions
        if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
            return int(width), int(height)
    return None


def summarise(samples: list[float]) -> dict:
    """min/p50/p95/max của một dãy số đo (ms)."""
    if not samples:
        return {'n': 0}
    ordered = sorted(samples)
    def pick(fraction: float) -> float:
        index = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
        return ordered[index]
    return {'n': len(ordered), 'min': round(ordered[0], 1), 'p50': round(pick(0.5), 1),
            'p95': round(pick(0.95), 1), 'max': round(ordered[-1], 1)}


def check_budget(measurements: dict) -> list[str]:
    """Danh sách các mục vượt trần (hoặc **không đo được**), dạng ``'tên: p95 350.0 ms > 300 ms'``.

    Duyệt theo TRẦN chứ không theo số đo: một phép đo biến mất hoặc lỗi (``n = 0``) là đúng loại
    hồi quy mà chốt này sinh ra để bắt (ví dụ `click` hỏng hẳn thì không còn số đo nào), nên thiếu
    số đo cũng là VƯỢT. Duyệt theo số đo thì chốt sẽ im lặng cho qua đúng lúc cần nó nhất.
    """
    over: list[str] = []
    for name, limit in DEFAULT_BUDGET_MS.items():
        stats = measurements.get(name) or {}
        if not stats.get('n'):
            over.append('%s: KHÔNG ĐO ĐƯỢC (%s)' % (name, stats.get('error') or 'thiếu số đo'))
            continue
        if stats['p95'] > limit:
            over.append('%s: p95 %.1f ms > %s ms' % (name, stats['p95'], limit))
    return over


class ChildCounter:
    """Đếm số tiến trình con mà tầng nền tảng sinh ra (một lời gọi công cụ X11 = một tiến trình)."""

    def __init__(self, platform) -> None:
        self.platform = platform
        self.count = 0

    def __enter__(self):
        self._run, self._raw = self.platform._run, self.platform.run_raw

        def counting_run(argv, **kwargs):
            self.count += 1
            return self._run(argv, **kwargs)

        def counting_raw(argv, **kwargs):
            self.count += 1
            return self._raw(argv, **kwargs)

        self.platform._run, self.platform.run_raw = counting_run, counting_raw
        return self

    def __exit__(self, *exc) -> None:
        self.platform._run, self.platform.run_raw = self._run, self._raw


def list_windows(platform) -> list[dict]:
    """Cửa sổ đang hiện, dạng dict gọn (cùng cách đọc mà lớp panel dùng: `enum_windows` + `describe_window`)."""
    out: list[dict] = []
    for hwnd in platform.enum_windows():
        try:
            info = platform.describe_window(hwnd)
        except Exception:
            continue
        # `WindowInfo.bounds` là (x, y, w, h) — không phải (left, top, right, bottom). Trừ lần nữa
        # là ra kích thước sai (đo được: terminal 715×141 thành 671×33, panel thành 1632×-998) và
        # mọi điểm bấm tính từ đó đều lệch.
        left, top, width, height = info.bounds
        out.append({'windowId': int(hwnd), 'title': info.title, 'class': info.class_name,
                    'position': {'x': int(left), 'y': int(top)},
                    'size': {'width': int(width), 'height': int(height)}})
    return out


#: Cửa sổ không nên đo: panel, desktop, và mọi thứ nhỏ hơn một cửa sổ ứng dụng thật.
#: So KHÔNG phân biệt hoa/thường: `WM_CLASS` thật là `Xfce4-panel`, `Xfdesktop` (chữ hoa đầu) nên
#: danh sách viết thường cũ đã bỏ sót đúng hai cửa sổ cần bỏ sót nhất.
_SKIP_CLASSES = ('xfce4-panel', 'xfdesktop', 'desktop', 'plasmashell', 'gnome-shell')

#: Dấu hiệu nhận ra terminal — nơi an toàn nhất để bấm và gõ thử.
_TERMINAL_HINTS = ('terminal', 'xterm', 'konsole', 'alacritty', 'kitty', 'wezterm', 'tilix',
                   'urxvt', 'rxvt', 'gnome-term', 'ptyxis', 'foot')


def pick_target_window(platform, wanted: str | None = None, *, for_input: bool = False):
    """Cửa sổ để đo: ưu tiên terminal (gõ vào đó là an toàn), hoặc ``wanted`` theo tiêu đề.

    Bỏ qua panel/desktop: bấm vào đó vừa vô nghĩa vừa bị chốt "điểm bấm bị che" từ chối.
    ``for_input=True`` (đo bấm/gõ) KHÔNG chấp nhận nhánh dự phòng "cửa sổ lớn nhất": nhánh đó có
    thể gõ thử vào trình duyệt hay trình soạn thảo đang mở dở của người dùng.
    """
    windows = [info for info in list_windows(platform)
               if (info.get('class') or '').lower() not in _SKIP_CLASSES
               and info['size']['width'] > 200 and info['size']['height'] > 100]
    for info in windows:
        title = info.get('title') or ''
        if wanted and wanted in title:
            return info
    for info in windows:
        haystack = ((info.get('title') or '') + ' ' + (info.get('class') or '')).lower()
        if 'ubuntu@' in haystack or any(hint in haystack for hint in _TERMINAL_HINTS):
            return info
    if not for_input:
        return max(windows, key=lambda info: info['size']['width'] * info['size']['height'],
                   default=None)
    # Đo INPUT mà không chỉ rõ cửa sổ thì phải từ chối: nhánh dự phòng cũ chọn cửa sổ LỚN NHẤT trên
    # màn hình rồi bấm vào giữa và gõ thử vào đó — có thể là trình duyệt hay trình soạn thảo đang
    # mở dở của người dùng. Thà báo lỗi còn hơn gõ bậy.
    print('  không thấy cửa sổ nào giống terminal để đo input; hãy mở một terminal hoặc dùng '
          '--window <id>', flush=True)
    return None


def measure(platform, call, times: int, *, warmup: int = 1) -> dict:
    """Gọi ``call()`` nhiều lần, trả thống kê ms (kèm số tiến trình con mỗi lần)."""
    for _ in range(warmup):
        call()
    samples: list[float] = []
    children = 0
    for _ in range(times):
        with ChildCounter(platform) as counter:
            started = time.perf_counter()
            call()
            samples.append((time.perf_counter() - started) * 1000.0)
            children += counter.count
    stats = summarise(samples)
    stats['child_processes'] = round(children / max(1, times), 1)
    return stats


def exactly(text: str, size: int) -> str:
    """Lặp ``text`` cho đủ ``size`` ký tự — nhãn ``*_200`` phải đo đúng 200 ký tự."""
    if not text:
        return 'a' * size
    return (text * (size // len(text) + 1))[:size]


def run_primitives(platform, window, times: int, *, payload: str) -> dict:
    """Đo tầng nền tảng: đọc trạng thái, chụp ảnh, gửi input."""
    from agentbox.sandbox.x11 import input as xi

    hwnd = int(window['windowId'])
    centre = (int(window['position']['x']) + int(window['size']['width']) // 2,
              int(window['position']['y']) + int(window['size']['height']) // 2)
    results: dict[str, dict] = {}

    def timed(name, call):
        try:
            stats = measure(platform, call, times)
        except Exception as exc:                       # thiếu tiêu điểm, cửa sổ bị che…
            results[name] = {'n': 0, 'error': str(exc)[:160]}
            print('  %-34s KHÔNG ĐO ĐƯỢC: %s' % (name, str(exc)[:90]), flush=True)
            return
        results[name] = stats
        print('  %-34s %s' % (name, _format(stats)), flush=True)

    # Gõ/bấm chỉ đo được khi cửa sổ đích đang có tiêu điểm: đưa lên trước rồi mới đo.
    platform.set_foreground_window(hwnd)

    timed('primitives.get_foreground_window', lambda: platform.get_foreground_window())
    timed('primitives.get_cursor_pos', lambda: platform.get_cursor_pos())
    timed('primitives.get_window_rect', lambda: platform.get_window_rect(hwnd))
    timed('primitives.window_from_point', lambda: platform.window_from_point(*centre))
    timed('primitives.window_properties', lambda: platform.window_properties(hwnd))
    timed('primitives.capture_window', lambda: xc.capture_window(hwnd, platform=platform))
    timed('primitives.capture_screen', lambda: xc.capture_screen(platform=platform))
    timed('primitives.press_key', lambda: xi.press_key('End', window=hwnd, platform=platform))
    timed('primitives.click', lambda: xi.click(*centre, window=hwnd, platform=platform, restore=False))
    typed = exactly(payload, 200)
    print('  (type_text đo %d ký tự)' % len(typed), flush=True)
    timed('primitives.type_text_200', lambda: xi.type_text(typed, window=hwnd, platform=platform))
    return results


def build_executor(platform, session: str):
    from agentbox.agent_core.desktop_control import DesktopControl
    control = DesktopControl(profile_dir=Path('/var/tmp/cua-bench-profile'), platform=platform)
    return HostExecutor(desktop=control, approver=lambda *a, **k: 'allow_always'), session


def run_product(platform, window, times: int, *, payload: str) -> dict:
    """Đo qua đúng đường sản phẩm (``HostExecutor.execute``) và đếm token payload trả về."""
    executor, session = build_executor(platform, 'cua-bench')
    hwnd = int(window['windowId'])
    centre = (int(window['position']['x']) + int(window['size']['width']) // 2,
              int(window['position']['y']) + int(window['size']['height']) // 2)
    results: dict[str, dict] = {}
    tokens: dict[str, int] = {}

    platform.set_foreground_window(hwnd)

    def timed(name, action, *, tool='computer_use', **extra):
        def call():
            args = {'action': action, 'windowId': hwnd, **extra} if tool == 'computer_use' else dict(extra)
            return asyncio.new_event_loop().run_until_complete(
                executor.execute(tool, args, session))

        try:
            stats = measure(platform, call, times)
        except Exception as exc:
            results[name] = {'n': 0, 'error': str(exc)[:160]}
            print('  %-34s KHÔNG ĐO ĐƯỢC: %s' % (name, str(exc)[:90]), flush=True)
            return
        results[name] = stats
        print('  %-34s %s' % (name, _format(stats)), flush=True)
        payload_json = json.dumps(call(), ensure_ascii=False)
        tokens[name] = text_tokens(payload_json)
        print('      payload %d byte' % len(payload_json), flush=True)
        # Ảnh trả về ở dạng base64: đếm token theo ký tự base64 là vô nghĩa (một ảnh 1,4 MP thành
        # ~27 000 "token chữ"). Với ảnh, con số có nghĩa là token THỊ GIÁC = điểm ảnh / 750.
        box = _image_size(call())
        if box:
            width, height = box
            tokens[name] = image_tokens(width, height)
            print('      ảnh %dx%d ≈ %d token thị giác' % (width, height, tokens[name]), flush=True)
        else:
            print('      ≈ %d token chữ' % tokens[name], flush=True)

    timed('product.key', 'key', key='End')
    timed('product.click', 'click', x=centre[0], y=centre[1])
    timed('product.type_text_200', 'type', text=exactly(payload, 200))
    # `computer_use` KHÔNG nhận `action='screenshot'` (trả `UNSUPPORTED_ACTION` trước khi chụp) — đo
    # ở đó là đo đường báo lỗi, không phải đường chụp ảnh thật. Đường chụp thật của sản phẩm là
    # `computer_screen_capture`.
    timed('product.screenshot', '', tool='computer_screen_capture')
    # Bốn thao tác cử chỉ. Đo trên chính cửa sổ đích: cú kéo sẽ kéo nội dung trong cửa sổ đó, nên
    # chạy trên cửa sổ nào cũng được — con số cần đo là thời gian gửi sự kiện, không phải kết quả.
    timed('product.scroll_5', 'scroll', x=centre[0], y=centre[1], direction='down', steps=5)
    timed('product.drag_12', 'drag', x=centre[0], y=centre[1],
          toX=centre[0] + 120, toY=centre[1] + 40, steps=12)
    timed('product.hold_0_5', 'hold', x=centre[0], y=centre[1], seconds=0.5)
    path = [[centre[0] - 200 + index * 8, centre[1] + int(60 * math.sin(index / 4))] for index in range(61)]
    timed('product.stroke_61', 'stroke', path=path)
    return results, tokens


def _wait_for_window(platform, known: set[int], timeout: float = 12.0):
    """Chờ cửa sổ mới hiện ra, thay vì ngủ một khoảng cố định (đo được: ngủ 2,5 s là phần lớn
    "latency đầu-cuối" trong khi thời gian mở ứng dụng thật chỉ vài chục ms)."""
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        for info in list_windows(platform):
            if int(info['windowId']) not in known:
                return info
        time.sleep(0.05)
    return None


def run_case(platform, kind: str, times: int = 1) -> dict:
    """Latency đầu-cuối: giao một việc CUA và đo tới lúc xong (mở ứng dụng → gõ → Enter).

    Đây là con số người dùng yêu cầu: từ lúc một việc CUA được giao tới lúc hoàn tất. Phần chờ cửa
    sổ hiện ra được tách riêng để không trộn chi phí của hệ điều hành vào chi phí của BoxFox.
    """
    if kind != 'terminal':
        raise SystemExit('chưa có ca dùng nào khác ngoài `terminal`')
    executor, session = build_executor(platform, 'cua-bench-case')
    runs: list[dict] = []
    for attempt in range(max(1, times)):
        started = time.perf_counter()
        steps: list[tuple[str, float]] = []
        before = {int(info['windowId']) for info in list_windows(platform)}

        def step(name, action, **extra):
            at = time.perf_counter()
            asyncio.new_event_loop().run_until_complete(
                executor.execute('computer_use', {'action': action, **extra}, session))
            steps.append((name, (time.perf_counter() - at) * 1000.0))
            print('  %-34s %7.0f ms' % (name, steps[-1][1]), flush=True)

        app = 'xfce4-terminal'
        pid = platform.launch_app(app)
        at = time.perf_counter()
        window = _wait_for_window(platform, before)
        launch_ms = (time.perf_counter() - at) * 1000.0
        print('  mở %s (pid %s) chờ cửa sổ hiện: %.0f ms' % (app, pid, launch_ms), flush=True)
        if window is None:
            raise SystemExit('không thấy cửa sổ nào để đo')
        hwnd = int(window['windowId'])
        step('chụp cửa sổ', 'screenshot', windowId=hwnd)
        step('gõ lệnh', 'type', windowId=hwnd, text='echo boxfox-bench')
        step('Enter', 'key', windowId=hwnd, key='Return')
        total = (time.perf_counter() - started) * 1000.0
        product_ms = sum(ms for _name, ms in steps)
        print('  %-34s %7.0f ms  (3 thao tác: %.0f ms)' % ('TỔNG (giao → xong)', total,
                                                           product_ms), flush=True)
        runs.append({'run': attempt + 1, 'total_ms': round(total, 1),
                     'actions_ms': round(product_ms, 1), 'launch_wait_ms': round(launch_ms, 1),
                     'steps': {name: round(ms, 1) for name, ms in steps}})
        try:
            platform._run([platform._tool('xdotool'), 'windowkill', str(hwnd)])
        except Exception:            # pragma: no cover - dọn dẹp là việc phụ
            pass
    totals = [run['total_ms'] for run in runs]
    actions = [run['actions_ms'] for run in runs]
    return {'case': kind, 'runs': runs,
            'total': summarise(totals), 'actions': summarise(actions)}


def _format(stats: dict) -> str:
    if not stats.get('n'):
        return 'không đo được'
    return 'p50 %7.1f | p95 %7.1f | max %7.1f ms | %4.1f tiến trình/lần' % (
        stats['p50'], stats['p95'], stats['max'], stats.get('child_processes', 0))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Đo latency và token của CUA trên X11.')
    parser.add_argument('command', choices=('primitives', 'product', 'case', 'budget'))
    parser.add_argument('--times', type=int, default=5, help='số lần lặp mỗi phép đo (mặc định 5)')
    parser.add_argument('--window', help='tiêu đề cửa sổ đích (mặc định: terminal đầu tiên)')
    parser.add_argument('--case', default='terminal', help='việc CUA cho `case` (mặc định terminal)')
    parser.add_argument('--payload', default='a = 2\nb = 3\nprint(a + b)\n',
                        help='văn bản để đo `type_text`')
    parser.add_argument('--json', help='ghi kết quả ra tệp JSON')
    parser.add_argument('--baseline', action='append',
                        help='tệp JSON của lần chạy trước, cho `budget`; lặp lại được '
                             '(primitives và product ghi hai tệp riêng)')
    parser.add_argument('--list-budget', action='store_true',
                        help='in danh sách trần rồi thoát')
    args = parser.parse_args(argv)

    if args.list_budget:
        for name, limit in DEFAULT_BUDGET_MS.items():
            print('%-36s %s ms (p95)' % (name, limit))
        return 0

    if args.command == 'budget':
        if not args.baseline:
            print('cần --baseline <tệp JSON> (lặp lại được)', file=sys.stderr)
            return 2
        # Gộp nhiều tệp: `primitives` và `product` là hai lượt đo khác nhau, mỗi lượt một tệp, mà
        # chốt thì so với CẢ danh sách trần — thiếu tệp nào là "KHÔNG ĐO ĐƯỢC" tệp đó.
        measurements: dict = {}
        for path in args.baseline:
            measurements.update(json.loads(Path(path).read_text()).get('measurements', {}))
        over = check_budget(measurements)
        for line in over:
            print('VƯỢT TRẦN: %s' % line)
        print('ngân sách: %s' % ('ĐẠT' if not over else '%d mục vượt trần' % len(over)))
        return 0 if not over else 1

    platform = xp.get_platform()
    if platform is None:
        print('máy này không có X11 (thiếu DISPLAY hoặc thiếu công cụ).', file=sys.stderr)
        return 2

    report: dict = {'display': platform.display, 'platform': platform.name}
    if args.command == 'case':
        report['case'] = run_case(platform, args.case, args.times)
    else:
        window = pick_target_window(platform, args.window, for_input=True)
        if window is None:
            print('không thấy cửa sổ nào để đo.', file=sys.stderr)
            return 2
        print('cửa sổ đích: %s "%s" %sx%s @ %s,%s' % (
            window['windowId'], (window['title'] or '')[:40], window['size']['width'],
            window['size']['height'], window['position']['x'], window['position']['y']), flush=True)
        if args.command == 'primitives':
            report['measurements'] = run_primitives(platform, window, args.times, payload=args.payload)
        else:
            measurements, tokens = run_product(platform, window, args.times, payload=args.payload)
            report['measurements'] = measurements
            report['tokens'] = tokens
            shot = xc.capture_window(int(window['windowId']), platform=platform)
            report['capture'] = {'width': shot.width, 'height': shot.height,
                                 'bytes': len(shot.pixels),
                                 'image_tokens': image_tokens(shot.width, shot.height)}

    report['notes'] = platform.notes()
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print('đã ghi %s' % args.json)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
