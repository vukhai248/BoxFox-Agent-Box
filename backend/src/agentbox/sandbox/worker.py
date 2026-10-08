"""Executed ONLY inside the configured Docker sandbox as unprivileged agent.

The host sends this module through docker exec; no host workspace/tool fallback.
"""
import base64
import difflib
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import uuid

ROOT = Path('/home/agent/workspace').resolve()
# W8.A4.3: workspace cố định; `ROOT` chỉ đổi theo từng yêu cầu khi harness gửi worktree của run/node.
WORKSPACE = ROOT
# True khi yêu cầu hiện tại đã thu hẹp ROOT vào worktree của một run/node (W8.A4.3).
_SCOPED = False
WORKTREE_ROOT_RE = re.compile(r'^\.boxfox/worktrees/w-[0-9a-f]{10}/(main|n-[A-Za-z0-9_.-]{1,64})$')

# F6 (đợt 8): Xvnc chạy `-AcceptSetDesktopSize` nên client RFB kéo được framebuffer nhỏ
# đi (tester từng thấy 286x311) — toạ độ bấm sau đó trỏ sai mà không ai báo. Giữ auto-fit
# nhưng chặn SÀN: trước thao tác theo toạ độ, nếu màn hình nhỏ hơn cỡ cấu hình thì đặt lại.
SCREEN_ENV = 'BOX_SCREEN'
DEFAULT_SCREEN = (1280, 800)
VNC_OUTPUT = 'VNC-0'
DISPLAY_ENV = {**os.environ, 'DISPLAY': ':99'}


def desktop_target():
    """Cỡ màn hình cấu hình (`BOX_SCREEN` = `WxH` hoặc `WxHxD`), mặc định 1280x800."""
    match = re.match(r'^(\d{3,5})x(\d{3,5})', (os.environ.get(SCREEN_ENV) or '').strip())
    if not match:
        return DEFAULT_SCREEN
    return int(match.group(1)), int(match.group(2))


def screen_size():
    """(rộng, cao) thật của framebuffer, hoặc None khi không đọc được."""
    try:
        proc = subprocess.run(['xrandr', '--current'], env=DISPLAY_ENV, capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError):
        return None
    if proc.returncode:
        return None
    match = re.search(r'current (\d+) x (\d+)', proc.stdout.decode(errors='replace'))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def ensure_desktop_size():
    """Đặt lại framebuffer nếu nó bị kéo nhỏ hơn cỡ cấu hình.

    Trả `{'from': 'WxH', 'to': 'WxH'}` khi có đặt lại, `{'from': ..., 'warning': ...}`
    khi đặt lại thất bại (không ném lỗi — ảnh chụp vẫn là ảnh thật), `None` khi không cần.
    """
    current = screen_size()
    if not current:
        return None
    target = desktop_target()
    if current[0] >= target[0] and current[1] >= target[1]:
        return None
    mode = '%dx%d' % target
    try:
        proc = subprocess.run(['xrandr', '--output', VNC_OUTPUT, '--mode', mode], env=DISPLAY_ENV,
                              capture_output=True, timeout=10)
    except (subprocess.SubprocessError, OSError) as exc:
        return {'from': '%dx%d' % current, 'warning': 'xrandr failed: %s' % exc}
    if proc.returncode:
        detail = (proc.stderr or proc.stdout).decode(errors='replace').strip()[:200]
        return {'from': '%dx%d' % current, 'warning': 'xrandr exit %d: %s' % (proc.returncode, detail)}
    return {'from': '%dx%d' % current, 'to': mode}

# Plan filename rules, identical to deploy/docker/plan_files.py:18-22 (the reader that enforces them).
PLAN_FILENAME = re.compile(r'^v([1-9][0-9]{0,9})-([a-z0-9]+(-[a-z0-9]+)*)\.md$')
PLAN_SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+)*$')
PLAN_ROOM = '.plans'
PLAN_MAX_BYTES = 1048576

# Vòng 27 / C-2: hồ sơ nghiên cứu là ĐẦU RA của một lượt research nên nó phải là TỆP trong
# workspace, không phải một câu trả lời bị cắt ở 8 000 ký tự. `.research/<việc>/` là phòng riêng:
# hồ sơ + sổ nguồn + bảng + biên bản phản biện, hồ sơ mang số version `v<N>-<việc>.md`.
DOSSIER_ROOM = '.research'
DOSSIER_MAX_BYTES = 262144
# Trần 61 ký tự cho tên phòng (không phải 41): hợp đồng chốt phòng là `.research/<việc>/`, nhưng
# harness dựng phòng bằng `dossier_dir_for()` = `<slug>-<yyyymmdd-hhmm>` (slug ≤ 40 + 1 + 13 = 54)
# rồi trả nguyên văn về cho model qua `dossierDir` — hẹp hơn thì chính phòng THẬT của harness bị từ
# chối. Rộng hơn vẫn là MỘT đốt đường dẫn: không `..`, không `/`, đúng bảng ký tự.
DOSSIER_PATH_RE = re.compile(r'^\.research/[a-z0-9][a-z0-9._-]{0,60}/[a-zA-Z0-9][a-zA-Z0-9._-]{0,60}\.md$')
# Tên bảng đi thẳng vào đường dẫn (`tables/<tên>.md`) nên phải kiểm như một ĐOẠN đường dẫn: không
# `..`, không dấu `/`, không rỗng — cùng khuôn đoạn tên tệp của DOSSIER_PATH_RE.
DOSSIER_TABLE_NAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._-]{0,60}$')
# Tệp phụ của run (P2, §5.8): `v<N>-scope.json`, `extractions/<source_id>.json`, `changelog.md` —
# MỘT đốt đường dẫn, hoặc hai đốt khi đốt đầu là một thư mục con. Không `..`, không rỗng, không
# đốt thứ ba: tên tệp phụ đi thẳng vào đường dẫn nên phải kiểm như một đường dẫn, không như nhãn.
DOSSIER_SIDECAR_RE = re.compile(r'^(?:[A-Za-z0-9][A-Za-z0-9._-]{0,60}/)?'
                                r'[A-Za-z0-9][A-Za-z0-9._-]{0,60}$')
# Số version đọc từ tiền tố `v<N>-` của TÊN tệp hồ sơ, không đọc từ nội dung.
DOSSIER_VERSION_RE = re.compile(r'^v([1-9][0-9]{0,9})-')


def path(value):
    resolved = (ROOT / value).resolve()
    if not resolved.is_relative_to(ROOT):
        raise ValueError('Path Traversal Denied: outside sandbox workspace')
    return resolved


# A8 (đợt 22): `file_read` từng gọi thẳng `read_text` nên một tệp nhị phân người dùng vừa tải
# lên (`.png`, `.pdf`) làm lượt chết `UnicodeDecodeError` — mô hình không đọc được gì và người
# dùng không biết vì sao. Đuôi dưới đây là danh sách nhị phân, cộng phép dò byte `\x00` trong
# 8 KiB đầu (bắt cả tệp không có đuôi quen thuộc).
BINARY_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.ico', '.tif', '.tiff', '.pdf',
                     '.zip', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.docx', '.xlsx', '.pptx',
                     '.whl', '.so', '.bin', '.exe', '.dll', '.mp4', '.mov', '.avi', '.mp3', '.wav',
                     '.woff', '.woff2', '.ttf', '.otf', '.sqlite', '.db')
BINARY_SNIFF_BYTES = 8192
BINARY_READ_CHARS = 30000


def read_int_arg(value, default):
    """Số nguyên KHÔNG ÂM từ `args` của model: `None`/`'abc'`/số âm/kiểu lạ ⇒ mặc định (A-5).

    `offset`/`limit` đến từ model nên không tin được: một chuỗi lạ lọt vào `text[offset:...]` là
    `TypeError` giữa lượt — đúng kiểu chết mà thông báo không nói được vì sao.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    try:
        number = int(value)
    except ValueError:
        return default
    return number if number >= 0 else default


def read_file_payload(target, offset=0, limit=BINARY_READ_CHARS):
    """Nội dung một tệp cho `file_read`: văn bản như cũ, nhị phân thì base64 (A8).

    Tệp nhị phân trả `encoding: 'base64'` để mô hình biết nó đang cầm một mẩu đã mã hoá chứ
    không phải văn bản, kèm `bytesRead`/`sizeBytes` để nó tự đối chiếu còn thiếu bao nhiêu.
    `truncated` nói SỰ THẬT của phép đọc (đủ hay thiếu byte), không phải "đây là tệp nhị phân":
    một tệp 1 KiB nằm trọn trong `content` mà bị gắn `truncated: True` sẽ khiến mô hình kết luận
    sai là nó chưa thấy hết tệp.

    Nhánh văn bản giữ nguyên hành vi cũ (30 000 ký tự đầu); chỉ thêm một đường lui: tệp có đuôi
    văn bản nhưng không giải mã được UTF-8 (ảnh chụp lưu sai tên, tệp nén đổi đuôi) đi tiếp
    bằng đường base64 thay vì làm lượt chết `UnicodeDecodeError`.

    A-5 (vòng 27): `offset`/`limit` chia một tệp dài thành nhiều mẩu đọc tiếp nhau; `nextOffset`
    là chỗ đọc tiếp (`None` khi mẩu này đã chạm cuối tệp — KHÔNG phải khi đọc hỏng). Nhánh base64
    làm tròn `offset` XUỐNG bội số 3 để khung giải mã thẳng hàng và nói rõ bằng `offsetAlignedTo`
    (không làm tròn thì mẩu giải ra lệch khung); `bytesRead` vẫn là số byte của CHÍNH lời gọi này,
    `nextOffset` mới là vị trí cộng dồn. `offset` quá cuối tệp trả `content: ''` +
    `truncated: False`: tệp đã hết, không phải dữ liệu bị thiếu.
    """
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
            # Tệp đuôi chữ nhưng không giải mã được UTF-8 (ảnh lưu sai tên, tệp nén đổi đuôi): rơi
            # xuống đường base64 ngay dưới đây thay vì làm lượt chết `UnicodeDecodeError`.
            pass
        else:
            chunk = text[offset:offset + limit]
            end = offset + len(chunk)
            return {'content': chunk, 'truncated': end < len(text), 'sizeChars': len(text),
                    'nextOffset': end if end < len(text) else None}
    # 30 000 ký tự base64 ≈ 22 500 byte thật; đọc đúng ngần ấy rồi mã hoá.
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


def process_marker(session):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', session):
        raise ValueError('Invalid session identifier')
    return Path('/tmp/boxfox-exec-' + session + '.json')


def shell(command, timeout=30, session='default'):
    proc = subprocess.Popen(['bash', '-lc', command], cwd=ROOT, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, start_new_session=True)
    marker = process_marker(session)
    marker.write_text(json.dumps({'pid': proc.pid, 'start': Path(f'/proc/{proc.pid}/stat').read_text().split()[21]}))
    try:
        output, _ = proc.communicate(timeout=min(120, max(1, timeout)))
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        raise ValueError('Command timed out; process group stopped')
    finally:
        marker.unlink(missing_ok=True)
    output = output.decode('utf-8', errors='replace')
    artifact = None
    if len(output) > 20000:
        # W8.A4.3: phần spill luôn nằm ở workspace người dùng (UI đọc được), không trong worktree.
        spilled = WORKSPACE / '.generated_artifacts/tools/' + uuid.uuid4().hex + '.txt'
        spilled.parent.mkdir(parents=True, exist_ok=True)
        spilled.write_text(output, encoding='utf-8')
        artifact = str(spilled.relative_to(WORKSPACE))
    return {'content': output[:15000] + ('\n[truncated; see artifact]' if artifact else ''),
            'exit_code': proc.returncode, 'is_error': proc.returncode != 0, 'artifact': artifact}


# --- W6.1.3: verify_exec — reviewer thử MỘT claim trong sandbox tạm --------------------------------
# Quyết định chủ máy 02/10 (duyệt #6423): reviewer được ĐỌC repo (read-only), ghi scratch và dùng MẠNG
# (theo công tắc firewall của box), nhưng KHÔNG được sửa repo. Vì vậy: bỏ --unshare-net, giữ các
# namespace còn lại, bỏ tmpfs che ROOT, giữ scratch = tmpfs /tmp + temp dir bind tại /tmp/work.
# Không có fallback chạy không cô lập: thiếu bwrap/userns thì fail closed VERIFY_EXEC_UNAVAILABLE.
VERIFY_OUTPUT_MAX = 8000
# Trần CỨNG mỗi luồng khi đọc kết quả: `communicate()` đọc tới EOF nên một snippet in vài trăm MB
# làm RSS của worker phình theo (đo được 20 MB → 920 MB); RLIMIT_FSIZE không áp cho pipe. Giữ phần
# đầu, vượt trần thì SIGKILL cả process group (review vòng 2, F2).
VERIFY_CAPTURE_MAX = 1 << 20
VERIFY_CAPTURE_CHUNK = 1 << 16
VERIFY_DRAIN_SECONDS = 2.0
VERIFY_TIMEOUT_DEFAULT, VERIFY_TIMEOUT_MAX = 10, 20
VERIFY_AS_BYTES = 512 << 20
VERIFY_DATA_BYTES = 2 << 30       # trần bộ nhớ cho node (RLIMIT_AS làm V8 không khởi động được)
VERIFY_FSIZE_BYTES = 8 << 20
VERIFY_NPROC = 64
VERIFY_WORKDIR = '/tmp/work'
VERIFY_SCRATCH_MAX = 20          # số file scratch báo trong receipt
VERIFY_SCRATCH_SCAN_MAX = 200    # trần số mục quét để snippet không làm treo phần thống kê
_VERIFY_PROBE = None


def _verify_digest(text):
    return 'sha256:' + hashlib.sha256((text or '').encode('utf-8', errors='replace')).hexdigest()


def _verify_interpreter(language):
    fixed = {'python': '/usr/bin/python3', 'node': '/opt/node/bin/node'}[language]
    found = fixed if os.access(fixed, os.X_OK) else shutil.which('python3' if language == 'python' else 'node')
    return found


def _verify_bwrap_argv(proc_mode, workdir=None):
    # Bỏ --unshare-net có chủ đích (quyết định 02/10): snippet dùng netns của box nên ra mạng được nếu
    # công tắc firewall của box đang mở; các namespace khác vẫn tách. Liệt kê tường minh thay cho
    # --unshare-all để không vô tình tách mạng trở lại khi bubblewrap đổi nghĩa cờ gộp.
    argv = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid', '--unshare-ipc',
            '--unshare-uts', '--unshare-cgroup', '--new-session', '--ro-bind', '/', '/', '--dev', '/dev']
    # Docker (seccomp/apparmor unconfined) cấm mount procfs mới trong userns lồng: khi đó che /proc bằng
    # tmpfs rỗng thay vì để lộ /proc của container (environ của các tiến trình cùng uid).
    argv += ['--proc', '/proc'] if proc_mode == 'proc' else ['--tmpfs', '/proc']
    argv += ['--tmpfs', '/tmp']
    if workdir is not None:
        # `/` chỉ-đọc nên không tạo được `/work`; điểm gắn nằm trong tmpfs `/tmp` mới (đã thử --dir,
        # --tmpfs và bind trước --ro-bind: đều lỗi "Can't mkdir /work: Read-only file system").
        argv += ['--bind', workdir, VERIFY_WORKDIR]
    # KHÔNG che ROOT nữa: reviewer phải đọc được repo (read-only) để đối chiếu trích dẫn nguồn.
    argv += ['--chdir', VERIFY_WORKDIR if workdir is not None else '/', '--']
    return argv


def _verify_scratch(workdir):
    """File snippet đã tạo trong scratch bind: ([{path, bytes}], overflow).

    Chỉ quét temp dir của CHÍNH lượt gọi (không quét cả /tmp). Có trần số mục để một snippet tạo cây
    file khổng lồ không làm treo phần thống kê; file chỉ tồn tại tới khi receipt được ghi.
    """
    items, seen = [], 0
    for dirpath, dirnames, filenames in os.walk(workdir):
        dirnames.sort()
        for name in sorted(filenames):
            seen += 1
            if seen > VERIFY_SCRATCH_SCAN_MAX:
                return items[:VERIFY_SCRATCH_MAX], seen
            full = os.path.join(dirpath, name)
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            items.append({'path': os.path.relpath(full, workdir), 'bytes': size})
    items.sort(key=lambda item: item['path'])
    return items[:VERIFY_SCRATCH_MAX], max(0, len(items) - VERIFY_SCRATCH_MAX)


def verify_probe(refresh=False):
    """Cached isolation probe: {available, reason, procMode}."""
    global _VERIFY_PROBE
    if _VERIFY_PROBE is not None and not refresh:
        return _VERIFY_PROBE
    if not shutil.which('bwrap'):
        _VERIFY_PROBE = {'available': False, 'reason': 'bwrap not installed', 'procMode': None}
        return _VERIFY_PROBE
    reason = None
    for mode in ('proc', 'tmpfs'):
        try:
            done = subprocess.run(_verify_bwrap_argv(mode) + ['true'], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            reason = str(exc)[:300]
            continue
        if done.returncode == 0:
            _VERIFY_PROBE = {'available': True, 'reason': None, 'procMode': mode}
            return _VERIFY_PROBE
        reason = (done.stderr or b'').decode('utf-8', errors='replace').strip()[:300] or f'exit {done.returncode}'
    _VERIFY_PROBE = {'available': False, 'reason': reason, 'procMode': None}
    return _VERIFY_PROBE


# Giới hạn đặt BÊN TRONG user namespace mới, ngay trước execv: RLIMIT_NPROC đặt ở ngoài sẽ đếm mọi
# thread cùng uid trên máy (trong Docker không thấy được qua /proc của container) và làm clone() của
# bwrap hỏng EAGAIN; trong namespace mới nó chỉ đếm tiến trình của snippet.
VERIFY_LAUNCHER = (
    'import os,resource,sys\n'
    'cpu,nproc,fsize,space,data=map(int,sys.argv[1:6])\n'
    'resource.setrlimit(resource.RLIMIT_NPROC,(nproc,nproc))\n'
    'resource.setrlimit(resource.RLIMIT_FSIZE,(fsize,fsize))\n'
    'resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu+1))\n'
    'space and resource.setrlimit(resource.RLIMIT_AS,(space,space))\n'
    'data and resource.setrlimit(resource.RLIMIT_DATA,(data,data))\n'
    'os.execv(sys.argv[6],sys.argv[6:])\n')


def _verify_launcher(language, timeout, interpreter, tail):
    launcher = _verify_interpreter('python')
    # V8 giữ trước vùng địa chỉ lớn nên node không khởi động dưới RLIMIT_AS 512 MiB; thay vào đó
    # python dùng RLIMIT_AS, còn node dùng RLIMIT_DATA (heap + buffer ngoài, đo được: 2 GiB chặn
    # `Buffer.alloc` 4 GiB trong khi snippet thường vẫn chạy — review vòng 2, F3).
    space = VERIFY_AS_BYTES if language == 'python' else 0
    data = 0 if language == 'python' else VERIFY_DATA_BYTES
    return [launcher, '-I', '-c', VERIFY_LAUNCHER, str(timeout), str(VERIFY_NPROC), str(VERIFY_FSIZE_BYTES),
            str(space), str(data), interpreter, *tail]


def _verify_version(interpreter):
    try:
        done = subprocess.run([interpreter, '--version'], capture_output=True, text=True, timeout=5)
        return ((done.stdout or '') + (done.stderr or '')).strip()[:80] or interpreter
    except (OSError, subprocess.TimeoutExpired):
        return interpreter


def _verify_stdin(proc, payload):
    """Ghi stdin (≤8000 ký tự, vừa một pipe buffer) rồi đóng để snippet thấy EOF."""
    try:
        if payload:
            proc.stdin.write(payload)
        proc.stdin.close()
    except (BrokenPipeError, OSError, ValueError):
        pass


def _verify_pump(selector, buffers, seen, deadline):
    """Đọc tới `deadline`; trả `(đã_đóng_hết, tràn_trần)`."""
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, False
        for key, _ in selector.select(remaining):
            chunk = os.read(key.fileobj.fileno(), VERIFY_CAPTURE_CHUNK)
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            seen[key.data] += len(chunk)
            room = VERIFY_CAPTURE_MAX - len(buffers[key.data])
            if room > 0:
                buffers[key.data] += chunk[:room]
            if seen[key.data] > VERIFY_CAPTURE_MAX:
                return False, True
    return True, False


def _verify_capture(proc, payload, timeout):
    """Đọc stdout/stderr có trần cứng; trả `(out, err, overflow, timed_out)`.

    Vượt trần hoặc quá hạn thì giết cả process group (bwrap + snippet) rồi hút nốt phần còn
    trong pipe; worker không bao giờ giữ nhiều hơn `VERIFY_CAPTURE_MAX` mỗi luồng.
    """
    buffers = {'out': bytearray(), 'err': bytearray()}
    seen = {'out': 0, 'err': 0}
    overflow = timed_out = False
    selector = selectors.DefaultSelector()
    for stream, name in ((proc.stdout, 'out'), (proc.stderr, 'err')):
        selector.register(stream, selectors.EVENT_READ, name)
    try:
        _verify_stdin(proc, payload)
        closed, overflow = _verify_pump(selector, buffers, seen, time.monotonic() + timeout)
        if not closed:
            timed_out = not overflow
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            _verify_pump(selector, buffers, seen, time.monotonic() + VERIFY_DRAIN_SECONDS)
    finally:
        selector.close()
        _verify_stdin(proc, b'')
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    return bytes(buffers['out']), bytes(buffers['err']), overflow, timed_out


def verify_exec(args):
    import tempfile
    language, code, claim = args.get('language'), args.get('code'), args.get('claim')
    stdin = args.get('stdin') or ''
    if language not in ('python', 'node'):
        raise ValueError('VERIFY_EXEC_INVALID: language must be one of python|node')
    for field, value, limit in (('code', code, 8000), ('claim', claim, 300)):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'VERIFY_EXEC_INVALID: {field} must be a non-empty string')
        if len(value) > limit:
            raise ValueError(f'VERIFY_EXEC_INVALID: {field} exceeds {limit} characters')
    if not isinstance(stdin, str) or len(stdin) > 8000:
        raise ValueError('VERIFY_EXEC_INVALID: stdin must be a string of at most 8000 characters')
    requested = args.get('timeoutSeconds') or VERIFY_TIMEOUT_DEFAULT
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise ValueError('VERIFY_EXEC_INVALID: timeoutSeconds must be an integer 1-20')
    timeout = min(VERIFY_TIMEOUT_MAX, requested)
    probe = verify_probe()
    if not probe['available']:
        return {'is_error': True, 'errorCode': 'VERIFY_EXEC_UNAVAILABLE',
                'error': 'VERIFY_EXEC_UNAVAILABLE: no working bubblewrap isolation in the box (' +
                         str(probe['reason']) + '); see README sandbox/bwrap. No unisolated fallback.'}
    interpreter = _verify_interpreter(language)
    if not interpreter:
        return {'is_error': True, 'errorCode': 'VERIFY_EXEC_UNAVAILABLE',
                'error': f'VERIFY_EXEC_UNAVAILABLE: {language} interpreter not found'}
    tail = ['-I', '-c', code] if language == 'python' else \
        ['--max-old-space-size=256', '--input-type=module', '-e', code]
    tmp = tempfile.mkdtemp(prefix='boxfox-verify-', dir='/tmp')
    started = time.monotonic()
    timed_out = False
    scratch, scratch_overflow = [], 0
    try:
        argv = _verify_bwrap_argv(probe['procMode'], tmp) + _verify_launcher(language, timeout, interpreter, tail)
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True,
                                env={'PATH': '/usr/bin:/bin:/opt/node/bin', 'LANG': 'C.UTF-8', 'HOME': VERIFY_WORKDIR})
        out, err, overflow, timed_out = _verify_capture(proc, stdin.encode('utf-8'), timeout)
        scratch, scratch_overflow = _verify_scratch(tmp)  # phải quét TRƯỚC khi finally xoá temp dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    duration = int((time.monotonic() - started) * 1000)
    stdout = out.decode('utf-8', errors='replace')
    stderr = err.decode('utf-8', errors='replace')
    truncated = overflow or len(stdout) > VERIFY_OUTPUT_MAX or len(stderr) > VERIFY_OUTPUT_MAX
    content = stdout[:VERIFY_OUTPUT_MAX]
    if stderr:
        content += ('\n' if content and not content.endswith('\n') else '') + '[stderr]\n' + stderr[:VERIFY_OUTPUT_MAX]
    exit_code = None if timed_out else proc.returncode
    receipt = {'kind': 'verify_exec', 'language': language, 'interpreter': _verify_version(interpreter),
               'codeHash': _verify_digest(code), 'stdinHash': _verify_digest(stdin),
               'outputHash': _verify_digest(content), 'exitCode': exit_code, 'durationMs': duration,
               'truncated': truncated, 'timedOut': timed_out, 'claim': claim, 'isolation': probe['procMode'],
               **({'outputOverflow': True} if overflow else {}),
               # Scratch để finding trích được file đã tạo; repo là read-only nhưng ĐỌC được, mạng dùng
               # netns của box (theo công tắc firewall).
               'scratchRoot': VERIFY_WORKDIR, 'scratch': scratch,
               **({'scratchOverflow': scratch_overflow} if scratch_overflow else {})}
    result = {'content': content, 'exit_code': exit_code, 'is_error': timed_out or overflow, 'receipt': receipt}
    if overflow:
        result.update(errorCode='VERIFY_EXEC_OUTPUT_OVERFLOW',
                      error=f'VERIFY_EXEC_OUTPUT_OVERFLOW: snippet produced more than {VERIFY_CAPTURE_MAX} '
                            'bytes on one stream; process group stopped and only the head was kept')
    if timed_out:
        # Hết giờ vẫn là một quan sát hợp lệ: is_error=true nhưng receipt được giữ.
        result.update(errorCode='VERIFY_EXEC_TIMEOUT',
                      error=f'VERIFY_EXEC_TIMEOUT: snippet exceeded {timeout}s; process group stopped')
    return result


def _pointer_move(x: int, y: int) -> None:
    """Đưa con trỏ tới (x, y) rồi CHỜ nó tới nơi — không dùng `mousemove --sync`.

    F8 (đợt 9): `xdotool mousemove --sync` treo đúng 15 giây khi con trỏ ĐÃ ở toạ độ
    đích (đo trong box: 15.16 s và 15.15 s, trong khi điểm mới mất 0.0 s), mà lệnh bị
    cắt ở `timeout=15` nên lần bấm thứ hai vào cùng một chỗ báo lỗi hết giờ. Đó chính
    là thứ làm lượt CUA nặng đốt 20/20 bước ở đợt 7. Ở đây di chuyển trước, rồi tự
    kiểm tra vị trí bằng `getmouselocation` — vẫn đảm bảo bấm đúng chỗ, không treo.
    """
    subprocess.run(['xdotool', 'mousemove', str(x), str(y)], env={**os.environ, 'DISPLAY': ':99'},
                   capture_output=True, timeout=10)
    for _ in range(20):
        probe = subprocess.run(['xdotool', 'getmouselocation', '--shell'],
                               env={**os.environ, 'DISPLAY': ':99'}, capture_output=True, timeout=10)
        out = probe.stdout.decode(errors='replace') if isinstance(probe.stdout, bytes) else str(probe.stdout or '')
        # So khớp theo DÒNG `X=<số>`; tìm chuỗi con thì `X=64` khớp luôn `X=640` và lần
        # kiểm tra đầu tiên sẽ đạt nhầm (vòng soát mã đợt 10 bắt được ở dòng này).
        seen = {}
        for line in out.splitlines():
            key, _, value = line.partition('=')
            if key in {'X', 'Y'}:
                seen[key] = value.strip()
        if seen.get('X') == str(x) and seen.get('Y') == str(y):
            return
        time.sleep(0.05)


def _pointer_click(args, *click_args) -> list:
    """Lệnh bấm chuột tại (x, y): di chuyển (không `--sync`) rồi bấm."""
    _pointer_move(int(args['x']), int(args['y']))
    return ['xdotool', 'click', *click_args]


#: Mã nút chuột của `xdotool` trong box.
BOX_MOUSE_BUTTONS = {'left': '1', 'middle': '2', 'right': '3'}

#: Khe hở sau khi NHẤN và trước khi NHẢ (giây). GTK/Cairo coi nhấn-rồi-nhả trong cùng một khung hình
#: là **cú bấm**, không phải cú kéo — thiếu khe hở thì kéo thành bấm.
BOX_GESTURE_SETTLE_SEC = 0.03

#: Nhịp giữa hai điểm dừng của cú kéo / nét vẽ (giây).
BOX_GESTURE_STEP_SEC = 0.01

#: Trần số bước của cú kéo và số điểm của nét vẽ trong box (mỗi bước là một tiến trình).
BOX_MAX_DRAG_STEPS = 60
BOX_MAX_STROKE_POINTS = 400


def _box_button(args) -> str:
    """Số hiệu nút chuột của X11, hoặc nói thẳng ra là tên nút sai.

    Bản X11/Windows từ chối tên nút lạ; ở đây cũng vậy. Trước đây tên sai im lặng thành chuột trái
    — một cú kéo bằng "nút giữa" gõ sai chính tả sẽ chạy như chuột trái và không ai biết.
    """
    name = str(args.get('button') or 'left').strip().lower()
    code = BOX_MOUSE_BUTTONS.get(name)
    if code is None:
        raise ValueError('nút chuột không hợp lệ: %r' % (name,))
    return code


def _drag_plan(args) -> list:
    """Kế hoạch kéo: nhấn ở điểm đầu, đi từng bước, nhả ở điểm cuối."""
    x, y = int(args['x']), int(args['y'])
    to_x, to_y = int(args['toX']), int(args['toY'])
    steps = max(1, min(BOX_MAX_DRAG_STEPS, int(args.get('steps') or 12)))
    code = _box_button(args)
    plan = [(['xdotool', 'mousemove', str(x), str(y)], 0.0),
            (['xdotool', 'mousedown', code], BOX_GESTURE_SETTLE_SEC)]
    for index in range(1, steps + 1):
        step_x = round(x + (to_x - x) * index / steps)
        step_y = round(y + (to_y - y) * index / steps)
        plan.append((['xdotool', 'mousemove', str(step_x), str(step_y)], BOX_GESTURE_STEP_SEC))
    plan.append((['xdotool', 'mouseup', code], BOX_GESTURE_SETTLE_SEC))
    return plan


def _hold_plan(args) -> list:
    """Kế hoạch giữ chuột: nhấn, chờ, nhả."""
    x, y = int(args['x']), int(args['y'])
    code = _box_button(args)
    try:
        seconds = max(0.05, min(5.0, float(args.get('seconds') or 1.0)))
    except (TypeError, ValueError):
        seconds = 1.0
    return [(['xdotool', 'mousemove', str(x), str(y)], 0.0),
            (['xdotool', 'mousedown', code], seconds),
            (['xdotool', 'mouseup', code], BOX_GESTURE_SETTLE_SEC)]


def _stroke_plan(args) -> list:
    """Kế hoạch vẽ nét: nhấn ở điểm đầu, đi qua từng điểm, nhả ở điểm cuối."""
    path = []
    for point in (args.get('path') or ()):
        try:
            px, py = point
            path.append((int(px), int(py)))
        except (TypeError, ValueError) as exc:
            raise ValueError('điểm của nét vẽ không hợp lệ: %r' % (point,)) from exc
    if len(path) < 2:
        raise ValueError('nét vẽ cần ít nhất hai điểm')
    if len(path) > BOX_MAX_STROKE_POINTS:
        raise ValueError('nét vẽ có %d điểm, quá trần %d' % (len(path), BOX_MAX_STROKE_POINTS))
    code = _box_button(args)
    plan = [(['xdotool', 'mousemove', str(path[0][0]), str(path[0][1])], 0.0),
            (['xdotool', 'mousedown', code], BOX_GESTURE_SETTLE_SEC)]
    for px, py in path[1:]:
        plan.append((['xdotool', 'mousemove', str(px), str(py)], BOX_GESTURE_STEP_SEC))
    plan.append((['xdotool', 'mouseup', code], BOX_GESTURE_SETTLE_SEC))
    return plan


# W9 (CDP attach): cổng 9222 mở KHÔNG có nghĩa CDP dùng được. Khi một tab đang chạy vòng lặp JS
# trên main thread, `connect_over_cdp` phải khởi tạo CHÍNH trang đó nên bị chặn cho tới khi vòng lặp
# kết thúc — đo trong box (`deploy/docker/tests/probe_cdp_attach.py`): vòng lặp 40 s giữ attach 59,2 s,
# nên trần 15 s cũ nổ "Timeout 15000ms exceeded" dù websocket đã kết nối (đúng chữ ký lỗi sweep
# W8-A4.1: `<ws connected> ws://127.0.0.1:9222/devtools/browser/...`). Ba lớp ở đây tách lỗi khỏi
# mạng: chờ `/json/version` trả JSON trước khi attach; attach theo NGÂN SÁCH có thử lại; quét marker
# từng trang bằng `wait_for_function` (có trần) để một trang treo không chặn cả lượt gọi.
CDP_PORT = 9222
CDP_ENDPOINT = 'http://127.0.0.1:9222'
# Trần chờ CDP trả JSON sau khi cổng mở (Chromium còn dựng profile/target khi cổng đã nghe).
# Đo trong box: khởi động lạnh trả `/json/version` sau 0,19 s, nên 15 s là rộng rãi.
CDP_READY_TIMEOUT = 15.0
# Mỗi lần attach 35 s, tối đa 2 lần. Trần 15 s cũ quá sát: khi có một tab bận JS, attach mất ĐÚNG
# ~59,2 s (đo 4 mức vòng lặp 10/20/40/90 s — không phụ thuộc độ dài vòng lặp, giống một trần phía
# Chromium), nên lần thử thứ hai bắt được ca đó. Tổng ngân sách: 15 (chờ CDP) + 70 (attach) + 25
# (`page.goto`) = 110 s, vẫn dưới trần 140 s của `docker exec` (`sandbox/executor.py`).
CDP_ATTACH_ATTEMPTS = 2
CDP_ATTACH_ATTEMPT_TIMEOUT_MS = 35000
# Trần cho một lần đọc `window.name` của một trang.
CDP_PAGE_MARKER_TIMEOUT_MS = 5000


def cdp_http_json(path, timeout=2.0):
    """JSON từ endpoint HTTP của CDP (`/json/version`, `/json/list`) — thuần stdlib."""
    with urllib.request.urlopen(CDP_ENDPOINT + path, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8', 'replace'))


def cdp_ready(deadline):
    """CDP đã trả JSON chưa (cổng TCP mở là chưa đủ để attach)."""
    while True:
        try:
            cdp_http_json('/json/version', timeout=1.0)
            return True
        except Exception:  # noqa: BLE001 - cổng chưa mở / Chromium còn dựng profile / HTTP chưa nghe
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)


def cdp_attach(pw):
    """`connect_over_cdp` theo ngân sách: thử lại một lần, lỗi nêu ĐÚNG bước đã hỏng.

    Trả `(browser, {'attempts', 'attachSec'})`. Không gán lỗi attach cho mạng: đo được nguyên nhân
    là một trang bận JS giữ quá trình khởi tạo trang, nên thử lại có ý nghĩa.
    """
    started = time.monotonic()
    last = None
    for attempt in range(1, CDP_ATTACH_ATTEMPTS + 1):
        try:
            client = pw.chromium.connect_over_cdp(CDP_ENDPOINT, timeout=CDP_ATTACH_ATTEMPT_TIMEOUT_MS)
        except Exception as exc:  # noqa: BLE001 - Playwright ném Error/TimeoutError khác nhau theo bản
            last = exc
            continue
        return client, {'attempts': attempt, 'attachSec': round(time.monotonic() - started, 3)}
    raise ValueError('BROWSER_CDP_ATTACH_TIMEOUT: connect_over_cdp ' + CDP_ENDPOINT + ' failed after '
                     + str(CDP_ATTACH_ATTEMPTS) + ' attempts x ' + str(CDP_ATTACH_ATTEMPT_TIMEOUT_MS // 1000)
                     + 's (a page blocked by a long-running script can hold this open; retry after it '
                       'finishes): ' + str(last)[:300])


def page_has_marker(page, marker):
    """`window.name` của trang có bằng marker của phiên không — CÓ TRẦN thời gian.

    `page.evaluate` không nhận `timeout` và không dùng `set_default_timeout`, nên một trang đang bận
    JS sẽ chặn cả lượt gọi cho tới khi harness cắt ở 140 s. `wait_for_function` có trần do driver
    Playwright giữ, nên trang treo chỉ bị coi là "không phải trang của phiên" rồi đi tiếp.
    """
    try:
        page.wait_for_function('(value) => window.name === value', arg=marker,
                               timeout=CDP_PAGE_MARKER_TIMEOUT_MS)
        return True
    except Exception:  # noqa: BLE001 - hết trần (trang bận) hoặc trang đã đóng
        return False


def page_set_marker(page, marker):
    """Đặt `window.name` của trang = marker, cũng CÓ TRẦN (lý do như `page_has_marker`).

    Hàm JS trả `true` ngay nên `wait_for_function` chỉ gọi nó một lần; hết trần (trang bận JS) thì
    trả False. Điều hướng trong cùng tab vốn giữ `window.name`, nên bước này chỉ để chống chệch.
    """
    try:
        page.wait_for_function('(value) => { window.name = value; return true; }', arg=marker,
                               timeout=CDP_PAGE_MARKER_TIMEOUT_MS)
        return True
    except Exception:  # noqa: BLE001 - hết trần (trang bận) hoặc trang đã đóng
        return False


def browser(args, session):
    from playwright.sync_api import sync_playwright
    action = args.get('action', 'snapshot')
    started = time.monotonic()
    try:
        with socket.create_connection(('127.0.0.1', CDP_PORT), timeout=1):
            pass
    except OSError:
        if action != 'navigate':
            raise ValueError('Sandbox browser is not running; navigate first')
        subprocess.Popen(['box-chromium', 'about:blank'], env={**os.environ, 'DISPLAY': ':99'},
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(40):
            try:
                with socket.create_connection(('127.0.0.1', CDP_PORT), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise ValueError('Sandbox Chromium failed to start CDP')
    if not cdp_ready(time.monotonic() + CDP_READY_TIMEOUT):
        raise ValueError('BROWSER_CDP_NOT_READY: port ' + str(CDP_PORT) + ' is open but /json/version did '
                         'not answer within ' + str(int(CDP_READY_TIMEOUT)) + 's')
    with sync_playwright() as pw:
        client, attach = cdp_attach(pw)
        attach['readySec'] = round(time.monotonic() - started, 3)
        context = client.contexts[0] if client.contexts else None
        if context is None:
            raise ValueError('BROWSER_CDP_NO_CONTEXT: Chromium has no browser context to use')
        marker = 'boxfox-harness-' + session
        page = next((p for p in context.pages if page_has_marker(p, marker)), None)
        if page is None:
            if action != 'navigate':
                raise ValueError('No browser page for this session. Navigate first.')
            page = context.new_page()
            if not page_set_marker(page, marker):
                raise ValueError('BROWSER_MARKER_FAILED: could not tag the new browser page for this session')
        page.set_default_timeout(10000)
        if action == 'navigate':
            url = args['url']
            if not url.startswith(('http://', 'https://')):
                raise ValueError('Only http/https browser URLs are allowed')
            page.goto(url, wait_until='domcontentloaded', timeout=25000)
            # KHÔNG `page.evaluate` ở đây: trang vừa điều hướng có thể đang bận JS (vòng lặp trên main
            # thread) và `evaluate` không có trần → giữ cả lượt gọi tới khi harness cắt ở 140 s. Hỏng
            # bước đặt lại marker cũng KHÔNG làm hỏng lượt điều hướng đã xong.
            attach['markerSet'] = page_set_marker(page, marker)
        elif action in {'click', 'fill'}:
            ref = args.get('ref', '')
            if not re.fullmatch(r'[a-f0-9]{8}-\d+', ref):
                raise ValueError('Use a ref from the latest snapshot')
            locator = page.locator('[data-boxfox-ref="' + ref + '"]')
            if locator.count() != 1:
                raise ValueError('Stale browser ref; take a new snapshot')
            if action == 'click':
                locator.click()
            else:
                locator.fill(args.get('text', ''))
        elif action == 'key':
            page.keyboard.press(args['key'])
        elif action == 'screenshot':
            output = path('.generated_artifacts/browser/' + uuid.uuid4().hex + '.png')
            output.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(output))
            return {'content': 'Browser screenshot captured', 'artifact': str(output.relative_to(ROOT)),
                    'image': base64.b64encode(output.read_bytes()).decode(), 'mime': 'image/png', 'attach': attach}
        elif action != 'snapshot':
            raise ValueError('Unknown browser action')
        nonce = uuid.uuid4().hex[:8]
        elements = page.locator('a,button,input,textarea,select,[role="button"]').evaluate_all('''(nodes, nonce) => nodes.slice(0,100).map((e,i) => {
            const ref = nonce + '-' + i; e.setAttribute('data-boxfox-ref',ref);
            return {ref,tag:e.tagName,text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').slice(0,180)};
        })''', nonce)
        return {'url': page.url, 'title': page.title(), 'content': page.locator('body').inner_text()[:12000],
                'elements': elements, 'attach': attach}


# P1.4 (đợt 23) — BẰNG CHỨNG TẠI GỐC: mỗi lần ghi tệp để lại một mảnh kiểm chứng được, sinh
# ngay tại chỗ ghi (diff + sha256 trước/sau + số dòng) chứ không suy lại từ sau. Chỗ rẻ nhất và
# thật nhất để sinh bằng chứng là CHÍNH công cụ đã sửa tệp — worker được harness gửi nội tuyến vào
# box ở mỗi lần gọi, nên sửa ở đây không cần dựng lại image. Mảnh bằng chứng nằm trong gốc captures
# nên `retention()` của box quét và dọn nó như mọi ảnh chụp khác.
EVIDENCE_ROOT = '.generated_artifacts/captures/evidence'
# Trần an toàn: tệp cũ dài hơn mức này thì KHÔNG diff — diff một tệp lớn vừa tốn RAM trong box vừa
# làm ngữ cảnh của model phình ra mà không ai đọc. Nội dung cũ vẫn được hash nên mảnh còn giá trị.
EVIDENCE_MAX_BYTES = 256 * 1024
# Trần `diff` trả về harness: bằng chứng phải ĐỌC ĐƯỢC, không phải để chở cả tệp.
EVIDENCE_DIFF_MAX_CHARS = 8000
EVIDENCE_SLUG_MAX_CHARS = 60
# Khuôn BOX-3 (`deploy/docker/capture.py:180`) giữ chữ thường và chỉ bốn nhóm ký tự này.
EVIDENCE_SLUG_CHARS = re.compile(r'[^a-z0-9._-]')


def sha256_of(raw):
    """sha256 hex của một khối byte — cùng đơn vị với `sha256sum` trong box."""
    return hashlib.sha256(raw).hexdigest()


def file_digest(target):
    """sha256 của tệp trên đĩa đọc theo khối: tệp lớn không bị nạp hết vào RAM."""
    digest = hashlib.sha256()
    with open(target, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def before_write(target):
    """Trạng thái CŨ của tệp ngay trước khi ghi: `(sha256, nội dung văn bản, lý do bỏ diff)`.

    `(None, None, None)` = tệp chưa tồn tại; mảnh bằng chứng nói thật `sha256Before: None`.
    Tệp quá trần ⇒ `(sha256, None, 'too_large')`. Tệp không giải mã được UTF-8 (ảnh, tệp nén)
    ⇒ `(sha256, None, 'binary')`: vẫn nói thật là tệp ĐÃ có và nội dung cũ hash ra sao, nhưng
    không bịa một diff từ dữ liệu không phải văn bản — và không bao giờ làm hỏng việc ghi.
    """
    if not target.is_file():
        return None, None, None
    if target.stat().st_size > EVIDENCE_MAX_BYTES:
        return file_digest(target), None, 'too_large'
    raw = target.read_bytes()
    try:
        return sha256_of(raw), raw.decode('utf-8'), None
    except UnicodeDecodeError:
        return sha256_of(raw), None, 'binary'


def step_number(value):
    """Số bước harness gửi kèm payload; không gửi (hoặc gửi giá trị lạ) thì `0`."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def evidence_step(value):
    """Bước thành token ba chữ số (`002`) — cùng khuôn `_step_token` của ảnh chụp trong box."""
    return f'{step_number(value):03d}'


def evidence_slug(target):
    """Tên tệp thành `slug` của khuôn BOX-3: chỉ `[a-z0-9._-]`, tối đa 60 ký tự.

    Bỏ dấu `.`/`-` ở ĐẦU: `<slug>` đứng ngay sau `_`, để nguyên dấu chấm thì tệp bằng chứng
    của một tệp ẩn (`.env`) cũng thành tệp ẩn — người mở thư mục bằng `ls` sẽ không thấy nó.
    """
    slug = EVIDENCE_SLUG_CHARS.sub('-', target.name.lower())[:EVIDENCE_SLUG_MAX_CHARS].lstrip('.-')
    return slug or 'file'


def session_key(session):
    """`<sid8>` = 8 ký tự đầu của session id; `''` khi không có định danh để đặt tên tệp."""
    return re.sub(r'[^0-9a-z]', '', str(session or '').strip().lower())[:8]


def evidence_entry(target, content, before, capture):
    """Mảnh bằng chứng của MỘT lần ghi: `(payload, diff)`.

    `payload` là khối `key: value` ghi vào tệp bằng chứng — thứ tự khoá là thứ tự ĐỌC: đường dẫn,
    hai hash, số dòng thêm/bớt, số dòng và số byte SAU khi ghi, rồi định danh lượt. `diff` rỗng
    khi không có gì để so (tệp cũ bằng tệp mới, hoặc `before_write` đã nói lý do bỏ diff).
    """
    relative = target.relative_to(ROOT).as_posix()
    sha_before, text_before, skipped = before
    encoded = content.encode('utf-8')
    payload = {
        'path': relative,
        'sha256Before': sha_before,
        'sha256After': sha256_of(encoded),
        'added': 0,
        'removed': 0,
        'lines': len(content.splitlines()),
        'bytes': len(encoded),
        'session': str(capture.get('session') or ''),
        'step': step_number(capture.get('step')),
        'tool': str(capture.get('tool') or ''),
        'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    diff = ''
    if skipped is not None:
        payload['diffSkipped'] = skipped
    else:
        old_lines = [] if text_before is None else text_before.splitlines()
        lines = list(difflib.unified_diff(old_lines, content.splitlines(), fromfile='a/' + relative,
                                          tofile='b/' + relative, lineterm=''))
        # Bỏ ĐÚNG hai dòng đầu `---`/`+++` khi đếm: một dòng nội dung cũng có thể bắt đầu bằng
        # `+`/`-` (`+++x` là một dòng THÊM), nên lọc theo tiền tố sẽ đếm sai.
        body = lines[2:] if len(lines) >= 2 and lines[0].startswith('---') and lines[1].startswith('+++') else lines
        payload['added'] = sum(1 for line in body if line.startswith('+'))
        payload['removed'] = sum(1 for line in body if line.startswith('-'))
        diff = '\n'.join(lines)
    if len(diff) > EVIDENCE_DIFF_MAX_CHARS:
        diff = diff[:EVIDENCE_DIFF_MAX_CHARS]
        payload['diffTruncated'] = True
    return payload, diff


def evidence_document(payload, diff):
    """Nội dung tệp bằng chứng: diff (nếu có) rồi tới khối `key: value` của lần ghi đó."""
    block = '\n'.join(f'{key}: {value}' for key, value in payload.items())
    return (diff + '\n\n' + block + '\n') if diff else (block + '\n')


def write_evidence(target, payload, diff, capture):
    """Ghi tệp bằng chứng theo khuôn BOX-3 và trả đường dẫn TƯƠNG ĐỐI của nó.

    `.generated_artifacts/captures/evidence/<sid8>/<sid8>_<step>_<slug>.<ext>`, `<ext>` là `diff`
    khi có diff, ngược lại `txt`. Không có `session` ⇒ trả `None`: lượt gọi ngoài phiên vẫn nhận
    `diff`/`numbers` nhưng KHÔNG được đổ rác vào workspace (P1.4 mục 5). Tệp đã tồn tại thì thêm
    hậu tố đếm — bằng chứng cũ đã phát tán trong event stream nên không bao giờ bị ghi đè.
    """
    sid8 = session_key(capture.get('session'))
    if not sid8:
        return None
    directory = path(EVIDENCE_ROOT + '/' + sid8)
    directory.mkdir(parents=True, exist_ok=True)
    extension = 'diff' if diff else 'txt'
    stem = f'{sid8}_{evidence_step(capture.get("step"))}_{evidence_slug(target)}'
    candidate = directory / f'{stem}.{extension}'
    index = 2
    while candidate.exists() and index < 1000:
        candidate = directory / f'{stem}-{index}.{extension}'
        index += 1
    if candidate.exists():
        candidate = directory / f'{stem}-{time.time_ns()}.{extension}'
    candidate.write_text(evidence_document(payload, diff), encoding='utf-8')
    return candidate.relative_to(ROOT).as_posix()


def write_text(target, content, exclusive=False, capture=None):
    """Ghi tệp; khi chỗ gọi yêu cầu thì dựng LUÔN mảnh bằng chứng của lần ghi đó (P1.4).

    Đọc nội dung CŨ trước khi ghi (không đoán lại sau khi tệp đã đổi), rồi tính `sha256` trước/
    sau, `difflib.unified_diff` (nhãn `a/<rel>` → `b/<rel>`) và số dòng. Trả `(target, evidence)`:
    `evidence` là `None` khi không ai yêu cầu, ngược lại là khối `{'diff', 'numbers', 'artifact'}`
    mà op ghi trả thẳng cho harness.

    `capture` do `execute()` dựng từ payload của HARNESS (`session`/`step`/`tool`) — không bao giờ
    lấy từ `args` của model, vì `args` là văn của model.
    """
    before = before_write(target) if capture is not None else None
    target.parent.mkdir(parents=True, exist_ok=True)
    if exclusive:
        with open(target, 'x', encoding='utf-8') as handle:
            handle.write(content)
    else:
        target.write_text(content, encoding='utf-8')
    if capture is None:
        return target, None
    payload, diff = evidence_entry(target, content, before, capture)
    return target, {'diff': diff, 'artifact': write_evidence(target, payload, diff, capture),
                    'numbers': {key: value for key, value in payload.items() if key != 'path'}}


def plan_directory(args):
    """Thư mục nhóm bên trong `.plans` (`''` = gốc) — mỗi đoạn phải đúng quy tắc slug.

    Harness chọn thư mục (nó sở hữu identity `dir/slug`), sandbox chỉ ghi đúng chỗ.
    """
    value = args.get('directory')
    if value in (None, ''):
        return ''
    if not isinstance(value, str):
        raise ValueError('PLAN_SLUG_INVALID: directory must be a string of slug segments, e.g. designs')
    segments = value.strip().strip('/').split('/')
    if not all(PLAN_SLUG.fullmatch(segment) for segment in segments):
        raise ValueError('PLAN_SLUG_INVALID: directory must be lowercase words separated by single dashes, e.g. designs')
    return '/'.join(segments)


def plan_version(value):
    """Số phiên bản do harness quyết; `None` nghĩa là "harness không đọc được chỉ mục"."""
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('PLAN_INVALID: version must be a positive integer decided by the harness, e.g. 3')
    if not re.fullmatch(r'[1-9][0-9]{0,9}', str(value).strip()):
        raise ValueError('PLAN_INVALID: version must be a positive integer decided by the harness, e.g. 3')
    return int(str(value).strip())


def write_plan(args):
    """Write .plans[/dir]/vN-slug.md.

    `version` (tuỳ chọn) là số harness đã quyết từ chỉ mục `GET /__box/plans/index`:
    file đã tồn tại → từ chối bằng `PLAN_VERSION_TAKEN` (KHÔNG tự tăng số — tự tăng là
    mầm của lỗi "v5 rồi v6 cho hai chủ đề mới" ở vòng 20). Không truyền `version`
    (harness không đọc được chỉ mục) thì giữ nguyên hành vi cũ: lấy số trống kế tiếp.
    """
    slug = args.get('slug')
    if not isinstance(slug, str) or not slug.strip():
        raise ValueError('PLAN_SLUG_INVALID: slug is required and must be a non-empty string, e.g. workspace-plan')
    slug = slug.strip()
    if not PLAN_SLUG.fullmatch(slug):
        raise ValueError('PLAN_SLUG_INVALID: slug must be lowercase words separated by single dashes, e.g. workspace-plan')
    content = args.get('markdown')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('PLAN_INVALID: markdown must be a non-empty string')
    size = len(content.encode('utf-8'))
    if size > PLAN_MAX_BYTES:
        raise ValueError('Plan exceeds the 1 MiB plan-file limit')
    directory = plan_directory(args)
    room = path(PLAN_ROOM + '/' + directory if directory else PLAN_ROOM)
    room.mkdir(parents=True, exist_ok=True)
    if not room.is_dir():
        raise ValueError(PLAN_ROOM + ' is not a directory')
    # Chỉ đếm file CÙNG slug trong CÙNG thư mục: số version là của nhóm, không của cả `.plans`.
    used = {int(match.group(1)) for match in (PLAN_FILENAME.fullmatch(item.name) for item in room.iterdir())
            if match and match.group(2) == slug and (room / match.group(0)).is_file()}
    version = plan_version(args.get('version'))
    if version is None:
        version = max(used or {0}) + 1
    elif version in used:
        raise ValueError('PLAN_VERSION_TAKEN: v%d-%s.md already exists; the harness must pick the next version'
                         % (version, slug))
    target = room / f'v{version}-{slug}.md'
    try:
        write_text(target, content, exclusive=True)
    except FileExistsError:
        # Đua ghi hiếm gặp: harness đọc lại chỉ mục rồi thử lần hai (PLAN_WRITE_CONFLICT nếu vẫn kẹt).
        raise ValueError('PLAN_VERSION_TAKEN: v%d-%s.md already exists; the harness must pick the next version'
                         % (version, slug))
    relative = target.relative_to(ROOT).as_posix()
    # KHÔNG trả `identity` ở đây: hợp đồng §1 cấm dạng kèm tiền tố `vN-` (identity là
    # khoá mà `GET /__box/plans` dùng để nhóm, tức slug trần / `dir/slug`). Bên gọi
    # tự suy ra từ `relativePath` đã được xác nhận.
    return {'content': 'Written ' + relative, 'version': version,
            'slug': slug, 'relativePath': relative, 'title': str(args.get('title') or '')[:120],
            'bytes': size}


def dossier_version(target):
    """Số version đọc từ tiền tố `v<N>-` của tên tệp hồ sơ; tên không đánh số ⇒ `0`.

    Hợp đồng §4 đặt tên hồ sơ là `v<N>-<slug>.md`; `0` là câu trả lời THẬT cho một tệp không mang
    số version (regex vẫn nhận, ví dụ một tệp nháp) — không bịa ra `1` cho một tệp chưa từng có số.
    """
    match = DOSSIER_VERSION_RE.match(target.name)
    return int(match.group(1)) if match else 0


def dossier_row_dict(entry):
    """Một hàng của `rows` thành dict: dữ liệu đến từ model nên phải chịu được thứ không phải dict.

    Mỗi dòng của `sources.jsonl` phải là MỘT ĐỐI TƯỢNG JSON (hợp đồng §4), nên `None` thành `{}`
    chứ không thành dòng `null` — bên đọc `json.loads` từng dòng sẽ vấp ngay ở dòng đó.
    """
    if isinstance(entry, dict):
        return entry
    if entry is None:
        return {}
    return {'claim': str(entry)}


def dossier_row_field(row, keys, default):
    """Một trường của hàng sổ nguồn, KHÔNG BAO GIỜ ném: thiếu khoá hoặc khoá rỗng ⇒ `default`."""
    for key in keys:
        value = row.get(key)
        if value not in (None, ''):
            return str(value).strip()
    return default


def dossier_host(url):
    """Host của một URL cho `sources.md`; URL lạ ⇒ `''` (không ném)."""
    match = re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)', str(url or '').strip())
    return match.group(1).lower() if match else ''


def dossier_sources_jsonl(rows):
    """`sources.jsonl` — bản MÁY đọc: một đối tượng JSON mỗi dòng, giữ NGUYÊN khoá hàng gửi vào.

    `ensure_ascii=False` để đoạn trích tiếng Việt còn đọc được trong tệp; giá trị `None` giữ nguyên
    thành `null` — JSON vẫn hợp lệ, nên KHÔNG bỏ khoá nào (bỏ khoá là sửa dữ liệu của chủ nhà).
    `default=str` chỉ để một giá trị lạ không giết cả lần ghi.
    """
    return ''.join(json.dumps(dossier_row_dict(entry), ensure_ascii=False, default=str) + '\n'
                   for entry in rows)


def dossier_sources_markdown(rows):
    """`sources.md` — bản NGƯỜI đọc của sổ nguồn: mỗi hàng một dòng có tầng, host, khẳng định, URL
    và ngày, dưới dòng đó là đoạn trích NGUYÊN VĂN (người kiểm đọc lại được đúng câu đã lấy)."""
    lines = ['# Nguồn', '']
    if not rows:
        return '\n'.join(lines + ['(chưa có nguồn nào)']) + '\n'
    for entry in rows:
        row = dossier_row_dict(entry)
        url = dossier_row_field(row, ('url',), '—')
        lines.append('- [%s] %s — %s · %s · %s' % (
            dossier_row_field(row, ('tier',), '—'),
            dossier_row_field(row, ('host',), '') or dossier_host(url) or '—',
            dossier_row_field(row, ('claim',), '(không có khẳng định)'),
            url,
            dossier_row_field(row, ('fetchedAt', 'date', 'at'), '—')))
        excerpt = dossier_row_field(row, ('excerpt', 'quote'), '')
        if excerpt:
            lines.append('  > ' + excerpt)
    return '\n'.join(lines) + '\n'


def write_dossier_file(target, content):
    """Ghi MỘT tệp hồ sơ qua tên TẠM cùng thư mục rồi `os.replace` vào chỗ.

    Hồ sơ gồm nhiều tệp và người đọc ngoài (panel Tệp) có thể mở đúng lúc: một tệp dở dang do
    tiến trình chết giữa lúc ghi là thứ không được để lại, nên ghi ra tên tạm rồi thay thế.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.' + uuid.uuid4().hex[:8] + '.tmp')
    try:
        temporary.write_text(content, encoding='utf-8')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def dossier_table_writes(folder, tables):
    """Cặp `(đường dẫn, nội dung)` cho từng `tables/<tên>.md` — nhận CẢ HAI hình dạng đang lưu hành.

    Lược đồ công bố là DANH SÁCH `[{'name': …, 'markdown': …}]`, nhưng đường gửi thật của harness
    chỉ chuyển tiếp được dạng MAPPING `{tên: markdown}` (mọi hình dạng khác bị đổi thành `{}` trước
    khi tới đây). Cả hai đều là dữ liệu thật của chủ nhà, nên op nhận cả hai thay vì để một hình
    dạng lạ giết CẢ lần ghi hồ sơ; rỗng (`None`, `''`, `{}`, `[]`) nghĩa là không có bảng nào.
    """
    if isinstance(tables, dict):
        items = [{'name': name, 'markdown': body} for name, body in tables.items()]
    elif isinstance(tables, list):
        items = tables
    else:
        items = [] if tables in (None, '') else [tables]
    writes = []
    for entry in items:
        table = entry if isinstance(entry, dict) else {}
        name = str(table.get('name') or '').strip()
        if not DOSSIER_TABLE_NAME_RE.fullmatch(name):
            raise ValueError('DOSSIER_TABLE_INVALID: name must be one file name, e.g. gia-theo-quy')
        body = table.get('markdown')
        if not isinstance(body, str):
            raise ValueError('DOSSIER_TABLE_INVALID: markdown must be a string')
        writes.append((folder + '/tables/' + name + '.md', body))
    return writes


def dossier_sidecar_writes(folder, sidecars):
    """Cặp `(đường dẫn, nội dung)` cho từng tệp PHỤ của run (P2 §5.8) — nhận cả hai hình dạng.

    Lược đồ công bố là DANH SÁCH `[{'name': …, 'content': …}]` (tên do
    `research_report.sidecar_names()` cấp ở phía harness), nhưng đường gửi thật chỉ chuyển tiếp được
    dạng MAPPING `{tên: nội dung}`; nhận cả hai để một hình dạng lạ không giết CẢ lần ghi hồ sơ.
    Tên đi thẳng vào đường dẫn nên phải qua `DOSSIER_SIDECAR_RE`; vắng tham số ⇒ không tệp nào.
    """
    if isinstance(sidecars, dict):
        items = [{'name': name, 'content': content} for name, content in sidecars.items()]
    elif isinstance(sidecars, list):
        items = sidecars
    else:
        items = [] if sidecars in (None, '') else [sidecars]
    writes = []
    for entry in items:
        item = entry if isinstance(entry, dict) else {}
        name = str(item.get('name') or item.get('path') or '').strip()
        if not DOSSIER_SIDECAR_RE.fullmatch(name):
            raise ValueError('DOSSIER_SIDECAR_INVALID: name must be e.g. v2-scope.json or '
                             'extractions/s-1.json')
        body = item.get('content')
        if body is None:
            body = item.get('markdown')
        if not isinstance(body, str):
            raise ValueError('DOSSIER_SIDECAR_INVALID: content must be a string')
        writes.append((folder + '/' + name, body))
    return writes


def dossier_write_payload(args):
    """Ghi TRỌN một hồ sơ nghiên cứu vào `.research/<việc>/` (C-2, vòng 27).

    Một lời gọi ghi CẢ BỘ tệp của hồ sơ chứ không chỉ tệp markdown — hồ sơ là đầu ra thật của một
    lượt research, và nó phải sống sót qua trần câu trả lời của con (8 000 ký tự):

    - tệp hồ sơ tại `path` (`markdown` đã kèm khối `<!-- boxfox-research … -->` do harness dựng);
    - `sources.jsonl` (một đối tượng JSON mỗi hàng của `rows`) + `sources.md` (bản người đọc);
    - `tables/<tên>.md` cho từng mục của `tables`; `review.md` khi `review` không rỗng.
    - tệp PHỤ của run khi `sidecars` có mặt (`v<N>-scope.json`, `v<N>-coverage.json`,
      `v<N>-claims.jsonl`, `v<N>-report.json`, `extractions/<source_id>.json`, `changelog.md`) —
      P2, §5.8; tên do phía harness cấp, op chỉ kiểm khuôn đường dẫn.

    Ghi là TẤT CẢ hoặc KHÔNG GÌ: mọi nội dung được dựng trước, mọi kích thước bị kiểm trước (trần
    `DOSSIER_MAX_BYTES` cho TỪNG tệp), tệp hồ sơ đã tồn tại thì từ chối khi chưa cho phép ghi đè
    (`overwrite`) — nên một lời gọi hỏng không để lại hồ sơ nửa vời. Chỉ ghi trong `.research/`:
    mọi đường dẫn đi qua `path()` (cổng chặn thoát workspace) và `path` của hồ sơ phải khớp
    `DOSSIER_PATH_RE`.

    `worker.py` đi nguyên văn vào box theo `executor.py` nên thêm op này KHÔNG cần dựng lại box và
    `deploy/docker/` không phải đổi gì.
    """
    relative = str(args.get('path') or '').strip()
    # Cổng cũ chạy TRƯỚC: `../../etc/passwd` phải nhận đúng câu 'Path Traversal Denied' của
    # `path()`, không phải một câu về regex — người đọc lỗi cần biết mình vừa đụng cổng nào.
    target = path(relative)
    relative = target.relative_to(ROOT).as_posix()
    if not DOSSIER_PATH_RE.fullmatch(relative):
        raise ValueError('DOSSIER_PATH_INVALID: .research/<việc>/<tên>.md')
    content = args.get('markdown')
    if not isinstance(content, str) or not content.strip():
        raise ValueError('Dossier markdown must not be empty')
    rows = args.get('rows')
    if not isinstance(rows, list):
        rows = [] if rows in (None, '') else [rows]
    folder = relative.rsplit('/', 1)[0]
    writes = [(relative, content),
              (folder + '/sources.jsonl', dossier_sources_jsonl(rows)),
              (folder + '/sources.md', dossier_sources_markdown(rows))]
    writes.extend(dossier_table_writes(folder, args.get('tables')))
    # P2 (§7.7): tệp phụ của run (phạm vi, bao phủ, nhận định, báo cáo cấu trúc, trích xuất,
    # nhật ký thay đổi). Vắng tham số ⇒ không ghi gì thêm, đường cũ giữ nguyên từng tệp.
    writes.extend(dossier_sidecar_writes(folder, args.get('sidecars')))
    review = args.get('review')
    if isinstance(review, str) and review.strip():
        writes.append((folder + '/review.md', review))
    # Kiểm HẾT mọi kích thước trước khi ghi BẤT KỲ tệp nào: một tệp quá trần phải chặn cả hồ sơ,
    # không được để lại nửa bộ tệp rồi mới báo hỏng.
    for item, text in writes:
        if len(text.encode('utf-8')) > DOSSIER_MAX_BYTES:
            raise ValueError('DOSSIER_TOO_LARGE: %s exceeds %d bytes' % (item, DOSSIER_MAX_BYTES))
    # Số version là CỦA TỆP HỒ SƠ: `sources.jsonl`/`sources.md` là tệp của cả thư mục việc nên bản
    # v2 ghi lại chúng (chủ ý), còn hồ sơ cùng tên đã có nghĩa là số đó đã dùng rồi.
    if not args.get('overwrite') and target.is_file():
        raise ValueError('DOSSIER_VERSION_TAKEN: %s already exists; write the next version' % relative)
    files = []
    for item, text in writes:
        write_dossier_file(path(item), text)
        files.append(item)
    encoded = content.encode('utf-8')
    return {'content': 'Written ' + relative, 'relativePath': relative,
            'version': dossier_version(target), 'slug': relative.split('/')[1],
            'title': str(args.get('title') or '')[:120], 'bytes': len(encoded),
            # Khoá tên `sha1` theo hợp đồng đã chốt, giá trị lấy từ CHÍNH hàm băm của mô-đun
            # (`sha256_of`) — cùng đơn vị với mảnh bằng chứng của mọi lần ghi khác.
            'sha1': sha256_of(encoded), 'files': files,
            'writtenAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}


# ---------------------------------------------------------------------------
# P3 — bốn op nguyên thuỷ của đường ghi có gác (§6.5, §8 P3).
# Worker chỉ dựng ĐÚNG lệnh `git` cần thiết từ tham số đã kiểm: mọi lời gọi là
# danh sách tham số (`shell=False`), tên nhánh/đường dẫn qua regex/`path()` trước
# khi chạm tới `git`; không có đường nào chạy chuỗi của model.
# ---------------------------------------------------------------------------
DESIGN_OWNED_PREFIX = '.design/'
DESIGN_BRANCH_RE = re.compile(r'^design/[a-z0-9._/-]+$')
DESIGN_MAIN_BRANCHES = ('main', 'master', 'HEAD')
# `base` là revision do harness cấp (mã sha/tên ref): chặn tham số bắt đầu bằng `-`
# để không bao giờ lọt thành một tuỳ chọn của `git`.
DESIGN_BASE_RE = re.compile(r'^[0-9A-Za-z][0-9A-Za-z._/~^-]{0,200}$')
DESIGN_WRITE_MODES = ('create', 'insert')
DESIGN_REVERT_MODES = ('file', 'batch')
DESIGN_GIT_TIMEOUT = 60


def git_run(args, timeout=DESIGN_GIT_TIMEOUT):
    """Chạy MỘT lệnh `git` từ danh sách tham số đã kiểm — KHÔNG bao giờ qua shell.

    Trả `subprocess.CompletedProcess` (text, UTF-8 thay thế). Không tự ném khi git thoát
    khác 0: chỗ gọi quyết định câu lỗi tiếng Việt theo đúng việc nó đang làm. Workspace
    không phải repo git (hoặc git không chạy được) ⇒ câu lỗi đã chốt của hợp đồng.
    """
    try:
        return subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=timeout, shell=False)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('DESIGN_WORKSPACE_NOT_REPO: Workspace trong box không phải một repo git.')


def design_require_repo():
    """Workspace phải là repo git; không thì từ chối bằng câu đã chốt."""
    if git_run(['rev-parse', '--git-dir']).returncode:
        raise ValueError('DESIGN_WORKSPACE_NOT_REPO: Workspace trong box không phải một repo git.')


def design_current_branch():
    """Nhánh hiện tại; `''` khi detached HEAD hoặc repo chưa có commit."""
    proc = git_run(['symbolic-ref', '--short', '-q', 'HEAD'])
    return proc.stdout.strip() if not proc.returncode else ''


def design_relative_path(value):
    """`(đường dẫn tương đối posix, Path)` cho một tham số `path` của model.

    Mọi đường dẫn đi qua `path()` (cổng chặn thoát workspace) TRƯỚC, nên `../` và đường
    dẫn tuyệt đối nhận đúng câu 'Path Traversal Denied' của mô-đun; rỗng/gốc workspace bị
    chối tại đây vì op ghi là thao tác trên MỘT tệp.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError('DESIGN_PATH_INVALID: cần một đường dẫn tệp tương đối trong workspace.')
    target = path(value)
    relative = target.relative_to(ROOT).as_posix()
    if relative in ('', '.'):
        raise ValueError('DESIGN_PATH_INVALID: cần một đường dẫn tệp tương đối trong workspace.')
    return relative, target


def design_paths_arg(value):
    """Danh sách đường dẫn đã kiểm của `design_diff`/`design_revert`; rỗng ⇒ `None`."""
    if value in (None, '', []):
        return None
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        raise ValueError('Danh sách đường dẫn không hợp lệ.')
    relatives = [design_relative_path(item)[0] for item in items]
    return relatives or None


def design_base_arg(value):
    """Revision `base` đã kiểm; chặn tham số bắt đầu bằng `-` lọt thành tuỳ chọn của git."""
    text = value.strip() if isinstance(value, str) else ''
    if not DESIGN_BASE_RE.fullmatch(text):
        raise ValueError('DESIGN_BASE_INVALID: cần một revision git hợp lệ (mã sha hoặc tên ref).')
    return text


def design_branch_create(args):
    """Tạo nhánh thiết kế từ `HEAD` hiện tại rồi chuyển sang nó; trả `{branch, base, head}`.

    Chối `main`/`master`/`HEAD` TRƯỚC khi kiểm khuôn (câu lỗi phải là "nhánh chính", không phải
    "sai khuôn"); tên phải đúng `^design/[a-z0-9._/-]+$` — nhờ vậy `;`, `&&`, khoảng trắng,
    chữ hoa và `..` không bao giờ tới được `git`.
    """
    raw = args.get('name')
    name = raw.strip() if isinstance(raw, str) else ''
    if name in DESIGN_MAIN_BRANCHES:
        raise ValueError('DESIGN_MAIN_BRANCH_FORBIDDEN: Không bao giờ ghi vào nhánh chính.')
    if (not DESIGN_BRANCH_RE.fullmatch(name) or '..' in name or '//' in name
            or name.endswith('/') or name.endswith('.lock') or '/.' in name):
        raise ValueError('Tên nhánh thiết kế không hợp lệ; dùng dạng design/<slug> chỉ gồm '
                         'chữ thường, số, ., _, - và /.')
    design_require_repo()
    if git_run(['show-ref', '--verify', '--quiet', 'refs/heads/' + name]).returncode == 0:
        raise ValueError('DESIGN_BRANCH_EXISTS: Tên nhánh thiết kế đã tồn tại.')
    head = git_run(['rev-parse', 'HEAD'])
    if head.returncode:
        raise ValueError('DESIGN_WORKSPACE_NOT_REPO: Repo git trong workspace chưa có commit (HEAD trống).')
    sha = head.stdout.strip()
    created = git_run(['checkout', '-b', name])
    if created.returncode:
        raise ValueError('DESIGN_BRANCH_EXISTS: Tên nhánh thiết kế đã tồn tại.')
    return {'branch': name, 'base': sha, 'head': sha}


def design_insert_content(current, content, anchor, position):
    """Nội dung MỚI của kiểu `insert`: nối cuối khi `position='append'`, ngược lại chèn NGAY SAU
    mốc `anchor` khớp đúng một lần (mốc giữ nguyên, nội dung theo sau nó)."""
    if position == 'append':
        return current + content
    if position not in (None, ''):
        raise ValueError("DESIGN_WRITE_INVALID: position chỉ nhận 'append'.")
    if not isinstance(anchor, str) or not anchor:
        raise ValueError("DESIGN_WRITE_INVALID: kiểu 'insert' cần `anchor` khớp đúng một lần "
                         "hoặc `position='append'`.")
    if current.count(anchor) != 1:
        raise ValueError('DESIGN_ANCHOR_NOT_UNIQUE: Mốc chèn không khớp đúng một lần trong tệp.')
    return current.replace(anchor, anchor + content, 1)


def design_write_branch_gate(relative):
    """Ghi vào dự án chỉ khi đang ở nhánh thiết kế; `.design/**` là ngoại lệ do run sở hữu."""
    design_require_repo()
    if relative == '.design' or relative.startswith(DESIGN_OWNED_PREFIX):
        return
    branch = design_current_branch()
    if branch in ('main', 'master'):
        raise ValueError('DESIGN_MAIN_BRANCH_FORBIDDEN: Không bao giờ ghi vào nhánh chính.')
    if not branch or not DESIGN_BRANCH_RE.fullmatch(branch):
        raise ValueError('DESIGN_BRANCH_REQUIRED: Chưa có nhánh thiết kế cho run này.')


def design_write(args):
    """Ghi MỘT tệp theo kiểu `create`/`insert`; trả `{path, mode, sha256, bytes}`.

    `create` đòi tệp CHƯA tồn tại; `insert` đòi tệp ĐÃ tồn tại và xác định vị trí bằng `anchor`
    khớp đúng một lần hoặc `position='append'`. Tệp được `git add` ngay sau khi ghi để
    `design_diff`/`design_revert` nhìn thấy tệp mới bằng chính `git diff` (tệp chưa theo dõi
    không bao giờ xuất hiện trong `git diff`).
    """
    relative, target = design_relative_path(args.get('path'))
    content = args.get('content')
    if not isinstance(content, str):
        raise ValueError('DESIGN_WRITE_INVALID: nội dung ghi phải là chuỗi.')
    mode = args.get('mode')
    if mode not in DESIGN_WRITE_MODES:
        raise ValueError("DESIGN_WRITE_INVALID: kiểu ghi phải là 'create' hoặc 'insert'.")
    design_write_branch_gate(relative)
    if mode == 'create':
        if target.exists():
            raise ValueError("DESIGN_WRITE_EXISTS: Tệp đã tồn tại; dùng kiểu 'chèn' thay vì 'tạo mới'.")
        new_content = content
    else:
        if not target.is_file():
            raise ValueError("DESIGN_WRITE_MISSING: Tệp chưa tồn tại; dùng kiểu 'tạo mới' thay vì 'chèn'.")
        try:
            current = target.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            raise ValueError('DESIGN_WRITE_INVALID: tệp hiện tại không phải văn bản UTF-8.')
        new_content = design_insert_content(current, content, args.get('anchor'), args.get('position'))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(new_content, encoding='utf-8', newline='')
    encoded = new_content.encode('utf-8')
    staged = git_run(['add', '-f', '--', relative])
    if staged.returncode:
        raise ValueError('DESIGN_WRITE_INVALID: không đưa được tệp vào chỉ mục git: %s'
                         % staged.stderr.strip()[:200])
    return {'path': relative, 'mode': mode, 'sha256': sha256_of(encoded), 'bytes': len(encoded)}


def design_file_sha(args):
    """Băm TOÀN BỘ tệp theo byte (`design_file_sha`) — cổng `DESIGN_WRITE_STALE` đọc ở đây.

    `file_read` cắt ở 30 000 ký tự nên băm của `content` không bao giờ khớp băm full-file mà
    `design_write` ghim cho tệp dài — cổng cũ từ chối OAN mọi lần `insert` sau lần ghi đầu. Op
    này trả băm của CẢ tệp (cùng đơn vị `sha256sum`), đi qua `path()` như mọi op ghi, và chối
    khi tệp chưa tồn tại.
    """
    relative, target = design_relative_path(args.get('path'))
    if not target.is_file():
        raise ValueError("DESIGN_WRITE_MISSING: Tệp chưa tồn tại; dùng kiểu 'tạo mới' thay vì 'chèn'.")
    try:
        size_chars = len(target.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, OSError):
        size_chars = None
    return {'path': relative, 'sha256': file_digest(target), 'sizeChars': size_chars}


def design_status_map(base, paths):
    """`{đường dẫn: ký tự trạng thái}` của `git diff --name-status <base>`; tệp đổi tên lấy đích."""
    args = ['diff', '--name-status', base]
    if paths:
        args += ['--', *paths]
    proc = git_run(args)
    if proc.returncode:
        raise ValueError('Không so được với mốc `%s`: %s' % (base, proc.stderr.strip()[:200]))
    statuses = {}
    for line in proc.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        code = parts[0][:1]
        path_value = parts[-1] if code in ('R', 'C') and len(parts) >= 3 else parts[1]
        statuses[path_value] = code
    return statuses


def design_numstat_map(base, paths):
    """`{đường dẫn: (added, removed)}` của `git diff --numstat <base>`; tệp nhị phân (`-`) đếm 0."""
    args = ['diff', '--numstat', base]
    if paths:
        args += ['--', *paths]
    proc = git_run(args)
    if proc.returncode:
        raise ValueError('Không so được với mốc `%s`: %s' % (base, proc.stderr.strip()[:200]))
    counts = {}
    for line in proc.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        added = 0 if parts[0] == '-' else read_int_arg(parts[0], 0)
        removed = 0 if parts[1] == '-' else read_int_arg(parts[1], 0)
        counts[parts[2]] = (added, removed)
    return counts


def design_diff(args):
    """So cây làm việc với `base`: số dòng thêm/bớt mỗi tệp + patch hợp nhất.

    Chỉ chạy `git diff` với tham số đã kiểm (`base` khớp `DESIGN_BASE_RE`, đường dẫn qua
    `path()`); `--` luôn đứng trước danh sách đường dẫn nên không có nội suy shell.
    """
    base = design_base_arg(args.get('base'))
    paths = design_paths_arg(args.get('paths'))
    design_require_repo()
    statuses = design_status_map(base, paths)
    counts = design_numstat_map(base, paths)
    patch = git_run(['diff', base] + (['--', *paths] if paths else []))
    if patch.returncode:
        raise ValueError('Không so được với mốc `%s`: %s' % (base, patch.stderr.strip()[:200]))
    names = {'A': 'added', 'D': 'deleted'}
    files = []
    for path_value, code in statuses.items():
        added, removed = counts.get(path_value, (0, 0))
        files.append({'path': path_value, 'status': names.get(code, 'modified'),
                      'added': added, 'removed': removed})
    return {'files': files, 'patch': patch.stdout}


def design_untracked_paths(paths):
    """Các đường dẫn CHƯA được git theo dõi (`??`) — chúng không xuất hiện trong `git diff`."""
    args = ['status', '--porcelain', '--untracked-files=all']
    if paths:
        args += ['--', *paths]
    found = []
    for line in git_run(args).stdout.splitlines():
        if len(line) >= 4 and line[:2] == '??':
            found.append(line[3:].strip())
    return found


def design_existed_at_base(base, relative):
    """Tệp có tồn tại ở `base` không (`git cat-file -e <base>:<path>`)."""
    return git_run(['cat-file', '-e', base + ':' + relative]).returncode == 0


def design_revert(args):
    """Hoàn tác thay đổi so với `base`: `mode='batch'` cả lô, `mode='file'` các đường dẫn đã nêu.

    Tệp CÓ ở `base` được khôi phục byte-identical bằng `git checkout <base> -- <đường dẫn>`;
    tệp KHÔNG có ở `base` (mục `new`) bị xoá và bỏ khỏi chỉ mục. Vì chỉ dùng `checkout <base>`
    (không checkout nhánh, không commit) nên `HEAD` không bao giờ nhích.
    """
    base = design_base_arg(args.get('base'))
    mode = args.get('mode') or 'file'
    if mode not in DESIGN_REVERT_MODES:
        raise ValueError("DESIGN_REVERT_INVALID: kiểu hoàn tác phải là 'file' hoặc 'batch'.")
    design_require_repo()
    paths = design_paths_arg(args.get('paths'))
    if mode == 'file' and not paths:
        return {'reverted': [], 'deleted': []}
    # `paths` (danh sách LÔ đã ghim ở tầng harness) là phạm vi hoàn tác cho CẢ hai mode; chỉ
    # `None` mới quét cả cây — nếu không, `revert-batch` nuốt luôn sửa tay của chủ nhà.
    scope = paths
    changed = design_status_map(base, scope)
    for untracked in design_untracked_paths(scope):
        changed.setdefault(untracked, '?')
    reverted = []
    deleted = []
    for relative in sorted(changed):
        if design_existed_at_base(base, relative):
            restored = git_run(['checkout', base, '--', relative])
            if restored.returncode:
                raise ValueError('DESIGN_REVERT_FAILED: không khôi phục được %s: %s'
                                 % (relative, restored.stderr.strip()[:200]))
            reverted.append(relative)
        else:
            path(relative).unlink(missing_ok=True)
            git_run(['rm', '--cached', '-q', '--ignore-unmatch', '--', relative])
            deleted.append(relative)
    return {'reverted': reverted, 'deleted': deleted}

try:  # pragma: no cover - đường dẫn chỉ tồn tại khi worker chạy TRONG box
    sys.path.insert(0, '/usr/local/bin')
    import session_ops as _session_ops
except ImportError:  # box chưa re-stage hai tệp nhật ký: xem `SESSION_OPS_UNAVAILABLE` bên dưới
    _session_ops = None

SESSION_OP_NAMES = ('session_ensure', 'journal_append', 'checkpoint_write', 'captures_prune',
                    'uploads_prune')
# Gán mặc định TRƯỚC nhánh có điều kiện: `importlib.reload` chạy lại thân mô-đun trong chính
# namespace cũ, nên một biến chỉ được gán trong nhánh `if` sẽ giữ giá trị cũ khi nhánh đó không chạy.
SESSION_OPS = ()

if _session_ops is not None:
    SESSION_OPS = tuple(_session_ops.OPS)


def select_root(root, name):
    """W8.A4.3: một yêu cầu chỉ thấy đúng worktree được giao; mọi `path()` kiểm theo ROOT này."""
    global ROOT, _SCOPED
    if root is None:
        # Chỉ trả ROOT về workspace khi yêu cầu TRƯỚC đã thu hẹp nó — nhờ vậy các bài kiểm
        # cũ (trỏ `worker.ROOT` vào tmp) và các op không theo worktree vẫn chạy y như trước.
        if _SCOPED:
            ROOT, _SCOPED = WORKSPACE, False
        return
    if not isinstance(root, str) or not WORKTREE_ROOT_RE.fullmatch(root):
        raise ValueError('WORK_SCOPE_OUTSIDE_WORKTREE: root is not a BoxFox run/node worktree')
    target = (WORKSPACE / root).resolve()
    if not target.is_relative_to(WORKSPACE) or not (target / '.git').is_file():
        raise ValueError('WORK_SCOPE_OUTSIDE_WORKTREE: worktree is missing or not a git worktree')
    if name.startswith('design_') or name == 'write_plan':
        raise ValueError('WORK_SCOPE_OUTSIDE_WORKTREE: ' + name + ' is not available inside a run worktree')
    ROOT, _SCOPED = target, True


def execute(name, args, session, turn=None, step=None, tool_call_id=None, root=None):
    """Cửa vào DUY NHẤT của worker: một op, một payload JSON vào, một kết quả JSON ra.

    `turn`/`step`/`tool_call_id` do **harness** đặt trong payload (P1.4) — KHÔNG bao giờ
    lấy từ `args` của model. `step` đi vào mảnh bằng chứng của op ghi tệp (số bước trong
    `numbers` và trong tên tệp); `turn`/`tool_call_id` đi cùng payload để worker và hai
    route capture/ghi hình dùng chung một hợp đồng định danh (`deploy/docker/ide-proxy.py`).
    """
    select_root(root, name)
    capture = {'session': session, 'step': step, 'tool': name}
    if name == '__skill_readiness':
        package = Path(args['basePath']).resolve()
        base = Path('/opt/boxfox-skills').resolve()
        if not package.is_relative_to(base):
            raise ValueError('Invalid skill package')
        requirements = args.get('requirements', {})
        def names(items):
            return [v if isinstance(v, str) else v.get('name', '') for v in items if isinstance(v, (str, dict)) and not (isinstance(v, dict) and v.get('optional'))]
        commands = names(requirements.get('commands', []))
        environment = names(requirements.get('environment', []))
        files = names(requirements.get('files', []))
        missing = {'commands': [n for n in commands if not shutil.which(n)],
                   'environment': [n for n in environment if not os.environ.get(n)],
                   'files': [n for n in files if not Path(os.path.expandvars(n)).expanduser().is_file()]}
        supported = not args.get('platforms') or 'linux' in args['platforms']
        return {'status': 'ready' if package.is_dir() and supported and not any(missing.values()) else 'setup_required',
                'packageMounted': package.is_dir(), 'platformSupported': supported, 'missing': missing}
    if name == '__cancel':
        marker = process_marker(session)
        if marker.exists():
            entry = json.loads(marker.read_text())
            stat = Path('/proc/' + str(entry['pid']) + '/stat')
            if stat.exists() and stat.read_text().split()[21] == entry['start']:
                os.killpg(entry['pid'], signal.SIGKILL)
            marker.unlink(missing_ok=True)
        return {'content': 'Session subprocess cleanup complete'}
    if name == 'file_read':
        return read_file_payload(path(args['path']), args.get('offset'), args.get('limit'))
    if name == 'file_write':
        target = path(args['path'])
        target, evidence = write_text(target, args['content'], capture=capture)
        return {'content': 'Written ' + target.relative_to(ROOT).as_posix(), **evidence}
    if name == 'write_plan':
        return write_plan(args)
    if name == 'dossier_write':
        return dossier_write_payload(args)
    if name == 'design_branch_create':
        return design_branch_create(args)
    if name == 'design_write':
        return design_write(args)
    if name == 'design_file_sha':
        return design_file_sha(args)
    if name == 'design_diff':
        return design_diff(args)
    if name == 'design_revert':
        return design_revert(args)
    if name == 'file_edit_block':
        target = path(args['path'])
        content = target.read_text(encoding='utf-8')
        if not args['old_text'] or content.count(args['old_text']) != 1:
            raise ValueError('old_text must match exactly once; read file first')
        target, evidence = write_text(target, content.replace(args['old_text'], args['new_text'], 1),
                                      capture=capture)
        return {'content': 'Updated ' + target.relative_to(ROOT).as_posix(), **evidence}
    if name == 'codebase_glob':
        pattern = args.get('pattern', '**/*')
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError('GLOB_PATTERN_INVALID: pattern must be a non-empty relative glob string, e.g. **/*.py')
        # pathlib does not expand shell braces. Do not return an empty match as evidence
        # that the workspace has no code. Character classes can still quote literal braces.
        unquoted = re.sub(r'\[[^]]*\]', '', pattern)
        if re.search(r'\{[^{}]*(?:,|\.\.)[^{}]*\}', unquoted):
            raise ValueError('GLOB_PATTERN_INVALID: pattern uses unsupported brace expansion; '
                             'make separate codebase_glob calls, e.g. **/*.py and **/*.ts')
        path(pattern)
        found = []
        for item in ROOT.glob(pattern):
            if item.is_file() and item.resolve().is_relative_to(ROOT):
                found.append(item.relative_to(ROOT).as_posix())
            if len(found) >= 500:
                break
        return {'content': '\n'.join(found)}
    if name == 'codebase_grep':
        needle = args['query']
        results = []
        for item in path(args.get('path', '.')).rglob('*'):
            if not item.is_file() or not item.resolve().is_relative_to(ROOT) or item.stat().st_size > 1000000:
                continue
            try:
                for n, line in enumerate(item.read_text(encoding='utf-8').splitlines(), 1):
                    if needle in line:
                        results.append(f'{item.relative_to(ROOT)}:{n}:{line[:300]}')
                    if len(results) >= 100:
                        return {'content': '\n'.join(results)}
            except (UnicodeError, PermissionError):
                continue
        return {'content': '\n'.join(results)}
    if name == 'terminal_exec':
        return shell(args['command'], args.get('timeout', 30), session)
    if name == 'verify_exec':
        return verify_exec(args)
    if name == 'verify_exec_probe':
        return {'content': 'verify_exec isolation probe', **verify_probe(refresh=bool(args.get('refresh')))}
    if name == 'browser_use':
        return browser(args, session)
    if name == 'computer_use':
        action = args['action']
        commands = {
            'click': lambda: _pointer_click(args, '1'),
            'double_click': lambda: _pointer_click(args, '--repeat', '2', '--delay', '100', '1'),
            'right_click': lambda: _pointer_click(args, '3'),
            'middle_click': lambda: _pointer_click(args, '2'),
            'type': lambda: ['xdotool', 'type', '--clearmodifiers', '--', args['text']],
            'key': lambda: ['xdotool', 'key', '--clearmodifiers', args['key']],
            'scroll': lambda: ['xdotool', 'click', '--repeat', str(min(20, max(1, int(args.get('steps', 3))))), '5' if args.get('direction') == 'down' else '4'],
        }
        # Cử chỉ cần NHIỀU lệnh liên tiếp (nhấn → đi → nhả), nên chúng là một kế hoạch chứ không phải
        # một lệnh: mỗi phần tử là `(argv, giây nghỉ sau lệnh)`.
        gestures = {
            'drag': lambda: _drag_plan(args),
            'hold': lambda: _hold_plan(args),
            'stroke': lambda: _stroke_plan(args),
        }
        if action not in commands and action not in gestures:
            raise ValueError('Unknown computer action')
        # F6: các thao tác theo toạ độ phải chạy trên framebuffer đúng cỡ cấu hình.
        desktop_note = ensure_desktop_size() if action != 'type' and action != 'key' else None
        # F4 (đợt 7): bàn phím chỉ tới cửa sổ ĐANG được focus. Không có cửa sổ nào thì
        # `xdotool` vẫn thoát 0, nên phải nói rõ là chưa gửi được thay vì báo đã gửi.
        if action in {'type', 'key'}:
            focused = subprocess.run(['xdotool', 'getactivewindow'], env={**os.environ, 'DISPLAY': ':99'},
                                     capture_output=True, timeout=15)
            if focused.returncode:
                raise ValueError('No focused window: click the target window first, then send keys.')
        if action in commands:
            plan = [(commands[action](), 0.0)]
        else:
            plan = gestures[action]()
        # Nút chuột phải được nhả kể cả khi một bước giữa hỏng: một nút còn giữ là cả màn hình trong
        # box không dùng được nữa (mọi cú bấm sau đó thành kéo).
        release = next((argv for argv, _ in plan if argv[:2] == ['xdotool', 'mouseup']), None)
        released = release is None      # không có bước nhả thì không có gì phải nhả lại
        try:
            for argv, sleep_after in plan:
                proc = subprocess.run(argv, env={**os.environ, 'DISPLAY': ':99'}, capture_output=True, timeout=15)
                if proc.returncode:
                    raise ValueError(proc.stderr.decode(errors='replace'))
                # Đánh dấu theo KẾT QUẢ chứ không theo thứ tự: lệnh nhả chạy tới nơi mà thoát khác 0
                # vẫn là nút còn giữ, và khi đó nó là bước CUỐI nên `sent < len(plan)` không bắt được.
                if argv == release:
                    released = True
                # F3 (đợt 7): `xdotool key NotARealKey` in 'No such key name ... Ignoring it.' ra
                # stdout rồi thoát 0. Coi cảnh báo đó là thất bại, kèm tên phím sai.
                noisy = (proc.stdout + proc.stderr).decode(errors='replace')
                if 'No such key name' in noisy or 'Ignoring it' in noisy:
                    raise ValueError('Unsupported key name: ' + str(args.get('key', '')) + '. Use an X keysym such as Return, Tab, ctrl+c.')
                if sleep_after:
                    time.sleep(sleep_after)
        except BaseException:
            # `BaseException` chứ không phải `Exception`: lượt bị huỷ (`CancelledError`) cũng phải nhả
            # nút, vì một nút còn giữ là mọi cú bấm sau đó trong box thành cú kéo.
            if not released:
                try:
                    subprocess.run(release, env={**os.environ, 'DISPLAY': ':99'}, capture_output=True, timeout=15)
                except Exception:  # noqa: BLE001 - nhả là best-effort; lỗi thật đang trên đường ra
                    pass
            raise
        payload = {'content': 'Input delivered; capture the screen to verify the effect.'}
        if desktop_note:
            payload['desktopRestored' if 'to' in desktop_note else 'desktopWarning'] = desktop_note
        return payload
    if name in SESSION_OP_NAMES:
        # A1 — bốn op phiên/nhật ký (`session_ensure`, `journal_append`, `checkpoint_write`,
        # `captures_prune`) do `session_ops.py` trong box phục vụ. Tệp đó phải được staged vào
        # `/usr/local/bin` (cùng chỗ `capture.py`); chưa staged thì op trả một lỗi **có mã** để
        # chỗ gọi hạ xuống `notice` — nhật ký không ghi được không bao giờ được giết một lượt.
        if _session_ops is None:
            return {'is_error': True,
                    'error': 'SESSION_OPS_UNAVAILABLE: session_files.py/session_ops.py chưa được '
                             'staged vào /usr/local/bin trong box (xem deploy/docker/backfill_history.py --stage)'}
        answer = _session_ops.run_op(name, args)
        if isinstance(answer, dict) and answer.get('ok') is False and 'is_error' not in answer:
            # `run_op` không bao giờ ném (thiết kế của nó) — nhưng worker phải trả về đúng khuôn
            # lỗi mà `execute()` của harness đã hiểu, nếu không lỗi ghi nhật ký sẽ thành công.
            return {'is_error': True, 'error': f"{answer.get('code') or 'SESSION_FILES_ERROR'}: "
                                               f"{answer.get('error') or 'op nhật ký hỏng'}"}
        return answer
    raise ValueError('Unsupported sandbox tool: ' + name)


if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        print(json.dumps(execute(request['name'], request['args'], request['session'],
                                 turn=request.get('turn'), step=request.get('step'),
                                 tool_call_id=request.get('toolCallId'), root=request.get('root')),
                         ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'is_error': True, 'error': str(exc)}))
