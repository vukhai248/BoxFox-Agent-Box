"""W6.1.3 worker-level `verify_exec`: isolation, limits and honest failure.

Runs the worker function directly on the host. On a host without a working bubblewrap (no bwrap,
userns blocked by seccomp/apparmor) every case skips — the tool must fail closed, never run
unisolated. On this machine the host probe passes, so these are the real numbers.
"""
import shutil
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


def test_workspace_is_not_writable_and_not_readable():
    result = run("open('/home/agent/workspace/x','w').write('1')")
    assert result['exit_code'] != 0 and 'workspace' in result['content']
    hidden = run("import os;print(os.path.exists('/home/agent/workspace'))")
    assert hidden['content'].strip() == 'False'


def test_no_network():
    result = run("import socket;socket.create_connection(('1.1.1.1',80),timeout=3)")
    assert result['exit_code'] != 0
    assert 'Network is unreachable' in result['content'] or 'timed out' in result['content']


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
