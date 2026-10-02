"""W6.1.3 worker-level `verify_exec` — trần đọc kết quả (review vòng 2, F2).

`communicate()` đọc tới EOF nên một snippet in vài trăm MB từng làm RSS của worker phình theo
(đo được 20 MB → 920 MB); `RLIMIT_FSIZE` không áp cho pipe. Các bài ở đây chạy trên tiến trình
thật, không cần bwrap, nên không bị skip theo `pytestmark` của `test_sandbox_verify_exec`.
"""
import subprocess
import sys

from agentbox.sandbox import worker


def spawn(code):
    return subprocess.Popen([sys.executable, '-c', code], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)


def test_capture_keeps_the_head_and_delivers_stdin():
    proc = spawn('import sys; data = sys.stdin.read(); print("got:" + data)')
    out, err, overflow, timed_out = worker._verify_capture(proc, b'hello', 10)
    assert b'got:hello' in out and err == b''
    assert overflow is False and timed_out is False


def test_capture_stops_a_flooding_process_and_bounds_memory():
    proc = spawn('import sys\nwhile True: sys.stdout.write("x" * 65536)')
    out, err, overflow, timed_out = worker._verify_capture(proc, b'', 10)
    assert overflow is True and timed_out is False
    assert len(out) <= worker.VERIFY_CAPTURE_MAX
    assert proc.returncode is not None, 'process group must be stopped and reaped'


def test_capture_kills_a_runaway_process_at_the_deadline():
    proc = spawn('import time\nprint("start", flush=True)\ntime.sleep(30)')
    out, err, overflow, timed_out = worker._verify_capture(proc, b'', 1)
    assert timed_out is True and overflow is False
    assert b'start' in out and proc.returncode is not None


def test_launcher_gives_python_as_and_node_data():
    """F3: python bị chặn bằng RLIMIT_AS; node (V8 không khởi động dưới AS 512 MiB) bằng RLIMIT_DATA."""
    python_argv = worker._verify_launcher('python', 10, '/usr/bin/python3', ['-c', 'print(1)'])
    assert python_argv[python_argv.index(str(worker.VERIFY_AS_BYTES)) + 1] == '0'
    node_argv = worker._verify_launcher('node', 10, '/usr/bin/node', ['-e', 'console.log(1)'])
    assert node_argv[node_argv.index('0') + 1] == str(worker.VERIFY_DATA_BYTES)
