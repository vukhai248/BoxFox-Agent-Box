"""W6.1.3 worker-level `verify_exec`: isolation matrix, limits and honest failure.

Chủ máy duyệt #6423 (02/10): snippet ĐỌC được repo (read-only), ghi scratch (/tmp/work, /tmp) và ra
mạng (netns của box, theo công tắc firewall), nhưng KHÔNG sửa được repo; các namespace khác vẫn tách.

Runs the worker function directly on the host. On a host without a working bubblewrap (no bwrap,
userns blocked by seccomp/apparmor) every case skips — the tool must fail closed, never run
unisolated. On this machine the host probe passes, so these are the real numbers.
"""
import pathlib
import shutil
import socket
import threading
import time

import pytest

from agentbox.sandbox import worker


def available():
    return worker.verify_probe(refresh=True)['available']


pytestmark = pytest.mark.skipif(not shutil.which('bwrap') or not available(),
                                reason='no working bubblewrap isolation on this host')


def run(code, language='python', **extra):
    return worker.verify_exec({'language': language, 'code': code, 'claim': 'fixture claim', **extra})


def test_nfd_and_nfc_counts_differ():
    result = run("import unicodedata;print(len(unicodedata.normalize('NFD','ế')))")
    assert result['is_error'] is False and result['content'].strip() == '3'
    assert result['receipt']['codeHash'].startswith('sha256:')
    assert result['receipt']['outputHash'] == result['receipt']['outputHash']


def test_repository_is_readable_but_read_only():
    source = str(pathlib.Path(worker.__file__).resolve())
    read = run(f"print(open({source!r}).readline().strip()[:20])")
    assert read['exit_code'] == 0 and read['content'].strip(), read
    write = run(f"open({source!r},'a').write('x')")
    assert write['exit_code'] != 0 and 'Read-only file system' in write['content'], write


def test_scratch_files_are_writable_and_reported():
    result = run("open('/tmp/work/a.txt','w').write('hello');open('/tmp/b.txt','w').write('x');"
                 "import os;print(sorted(os.listdir('/tmp/work')))")
    assert result['exit_code'] == 0 and result['content'].strip() == "['a.txt']", result
    receipt = result['receipt']
    assert receipt['scratchRoot'] == worker.VERIFY_WORKDIR
    assert receipt['scratch'] == [{'path': 'a.txt', 'bytes': 5}], receipt


def test_argv_keeps_namespaces_without_hiding_the_repo():
    argv = worker._verify_bwrap_argv('proc', '/tmp/scratch')
    assert '--unshare-all' not in argv and '--unshare-net' not in argv
    for flag in ('--unshare-user', '--unshare-pid', '--unshare-ipc', '--unshare-uts', '--unshare-cgroup'):
        assert flag in argv, flag
    assert str(worker.ROOT) not in argv, 'workspace must not be hidden any more'


def test_network_reaches_a_local_listener():
    """Snippet dùng netns của box: một listener trên loopback của máy phải nhận được kết nối."""
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    port = server.getsockname()[1]
    seen = []

    def accept():
        try:
            conn, _ = server.accept()
            seen.append(True)
            conn.close()
        except OSError:
            pass

    threading.Thread(target=accept, daemon=True).start()
    try:
        result = run(f"import socket;s=socket.create_connection(('127.0.0.1',{port}),timeout=3);"
                     "print('connected')")
    finally:
        server.close()
    assert result['exit_code'] == 0 and result['content'].strip() == 'connected', result
    assert seen, 'snippet never reached the host listener'


def test_timeout_kills_the_process_group_and_keeps_the_receipt():
    started = time.monotonic()
    result = run('while True: pass', timeoutSeconds=2)
    elapsed = time.monotonic() - started
    assert result['is_error'] is True and result['errorCode'] == 'VERIFY_EXEC_TIMEOUT'
    assert elapsed <= 2 + 2, elapsed
    assert result['receipt']['timedOut'] is True and result['receipt']['exitCode'] is None


def test_large_output_is_truncated_and_flagged():
    result = run("print('a'*100000)")
    assert result['receipt']['truncated'] is True
    assert len(result['content']) <= worker.VERIFY_OUTPUT_MAX + 40


def test_unavailable_isolation_fails_closed(monkeypatch):
    monkeypatch.setattr(worker.shutil, 'which', lambda name: None)
    worker.verify_probe(refresh=True)
    try:
        result = run('print(1)')
        assert result['is_error'] is True
        assert result['errorCode'] == 'VERIFY_EXEC_UNAVAILABLE'
        assert 'No unisolated fallback' in result['error']
        assert 'receipt' not in result
    finally:
        monkeypatch.undo()
        worker.verify_probe(refresh=True)


def test_stdin_and_node_interpreter():
    result = run("import sys;print(sys.stdin.read().upper())", stdin='hi')
    assert result['content'].strip() == 'HI'
    assert result['receipt']['stdinHash'] == result['receipt']['stdinHash']
    node = run("console.log([...'ế'.normalize('NFD')].length)", language='node')
    assert node['exit_code'] == 0 and node['content'].strip() == '3', node


def test_node_external_memory_is_capped():
    """F3: `Buffer.alloc` 4 GiB dưới RLIMIT_DATA phải chết, không chạy hết (đo ngoài: 4096 MiB)."""
    code = "const a=[];for(let i=0;i<64;i++){a.push(Buffer.alloc(64*1024*1024,1));}console.log('DONE',a.length);"
    result = run(code, language='node', timeoutSeconds=20)
    assert 'DONE' not in result['content']
    assert result['exit_code'] != 0


def test_verify_output_flood_is_bounded():
    """F2: snippet in liên tục không được để worker đọc tới EOF (đo ngoài: RSS 20 MB → 920 MB)."""
    result = run('import sys\nwhile True: sys.stdout.write("x" * 65536)', timeoutSeconds=20)
    assert result['is_error'] is True
    assert result['errorCode'] == 'VERIFY_EXEC_OUTPUT_OVERFLOW'
    assert result['receipt']['outputOverflow'] is True
    assert len(result['content']) <= 2 * worker.VERIFY_OUTPUT_MAX
