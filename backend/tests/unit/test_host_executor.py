"""`HostExecutor` (H3): hợp đồng payload, cổng quyền, đường dẫn, shell, timeout, dọn phiên.

Mọi ca chạy trong `tmp_path` với `platform='posix'`; không ca nào chạm máy thật ngoài `/bin/sh`.
Nền tảng Windows kiểm bằng `shell_argv()` (hàm thuần), không cần máy Windows.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from agentbox.agent_core import permissions as perms
from agentbox.sandbox import host_executor as host


def make_executor(tmp_path, **kwargs):
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    env = dict(os.environ)
    env['BOXFOX_AGENT_DATA_DIR'] = str(profile)
    policy = kwargs.pop('policy', None) or perms.PermissionPolicy(
        str(workspace), mode='trusted', profile_dir=profile, env=env)
    executor = host.HostExecutor(str(workspace), policy=policy, platform='posix', env=env, **kwargs)
    return executor


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------------ hợp đồng

def test_deferred_tools_return_a_coded_error_instead_of_raising(tmp_path):
    executor = make_executor(tmp_path)
    for name in ('browser_use', 'computer_screen_record', 'verify_exec', 'unknown_tool'):
        result = run(executor.execute(name, {}, 's1'))
        assert result['is_error'] is True
        assert result['errorCode'] == host.UNSUPPORTED_CODE
        assert name in result['error']


def test_deferred_tool_list_is_covered_by_the_same_contract(tmp_path):
    executor = make_executor(tmp_path)
    for name in host.DEFERRED_TOOLS:
        assert run(executor.execute(name, {}, 's1'))['errorCode'] == host.UNSUPPORTED_CODE


def test_executor_keeps_the_visual_lock_attribute(tmp_path):
    executor = make_executor(tmp_path)
    assert isinstance(executor.visual_lock, asyncio.Lock), 'chỗ gọi cũ không phải rẽ nhánh theo chế độ'


# ------------------------------------------------------------------ cổng quyền

def test_denied_call_returns_permission_denied(tmp_path):
    executor = make_executor(tmp_path)
    executor.policy.mode = 'plan'
    result = run(executor.execute('terminal_exec', {'command': 'git status'}, 's1'))
    assert result['errorCode'] == host.PERMISSION_DENIED_CODE


def test_hardline_is_refused_even_when_trusted(tmp_path):
    executor = make_executor(tmp_path)
    result = run(executor.execute('terminal_exec', {'command': 'format C:'}, 's1'))
    assert result['errorCode'] == host.PERMISSION_DENIED_CODE
    assert result['layer'] == 'hardline'


def test_ask_without_approver_fails_closed(tmp_path):
    executor = make_executor(tmp_path)
    executor.policy.mode = 'ask'
    result = run(executor.execute('terminal_exec', {'command': 'git status'}, 's1'))
    assert result['errorCode'] == host.PERMISSION_DENIED_CODE, 'thiếu đường hỏi KHÔNG phải là được phép'


def test_approver_allow_session_removes_the_second_question(tmp_path):
    calls = []

    def approver(tool, args, decision, session_id=None):
        calls.append((tool, args.get('command'), session_id))
        return 'allow_session'

    executor = make_executor(tmp_path, approver=approver)
    executor.policy.mode = 'ask'
    first = run(executor.execute('terminal_exec', {'command': 'echo xin-chao'}, 's1'))
    assert first.get('exit_code') == 0
    second = run(executor.execute('terminal_exec', {'command': 'echo xin-chao'}, 's1'))
    assert second.get('exit_code') == 0
    assert len(calls) == 1, 'phiên đã nhớ quyết định'


def test_approver_allow_always_writes_a_rule(tmp_path):
    executor = make_executor(tmp_path, approver=lambda tool, args, decision, session_id=None: 'allow_always')
    executor.policy.mode = 'ask'
    run(executor.execute('terminal_exec', {'command': 'echo mot-lan'}, 's1'))
    saved = executor.policy.paths[perms.LAYER_PROJECT]
    assert saved.is_file()
    assert 'terminal_exec(echo mot-lan)' in saved.read_text(encoding='utf-8')


def test_denied_approvals_trip_the_breaker(tmp_path):
    executor = make_executor(tmp_path, approver=lambda tool, args, decision, session_id=None: 'deny')
    executor.policy.mode = 'ask'
    for _ in range(perms.DENIAL_BREAKER_LIMIT):
        run(executor.execute('terminal_exec', {'command': 'echo a'}, 's1'))
    result = run(executor.execute('terminal_exec', {'command': 'echo b'}, 's1'))
    assert result['errorCode'] == host.APPROVAL_DENIAL_BREAKER_CODE


def test_approver_exception_is_a_denial(tmp_path):
    def approver(tool, args, decision, session_id=None):
        raise RuntimeError('giao diện hỏng')

    executor = make_executor(tmp_path, approver=approver)
    executor.policy.mode = 'ask'
    assert run(executor.execute('terminal_exec', {'command': 'echo a'}, 's1'))['is_error'] is True


# ------------------------------------------------------------------ tệp

def test_file_read_matches_the_box_shape(tmp_path):
    executor = make_executor(tmp_path)
    target = executor.workspace / 'a.txt'
    target.write_text('xin chào', encoding='utf-8')
    payload = run(executor.execute('file_read', {'path': 'a.txt'}, 's1'))
    assert payload['content'] == 'xin chào'
    assert payload['truncated'] is False
    assert payload['sizeChars'] == 8
    assert payload['nextOffset'] is None


def test_file_read_honours_offset_and_limit(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'a.txt').write_text('0123456789', encoding='utf-8')
    payload = run(executor.execute('file_read', {'path': 'a.txt', 'offset': 2, 'limit': 3}, 's1'))
    assert payload['content'] == '234'
    assert payload['truncated'] is True
    assert payload['nextOffset'] == 5


def test_file_read_binary_comes_back_as_base64(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'a.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 8)
    payload = run(executor.execute('file_read', {'path': 'a.png'}, 's1'))
    assert payload['encoding'] == 'base64'
    assert payload['sizeBytes'] == 16


def test_file_write_returns_evidence_the_work_graph_reads(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('file_write', {'path': 'sub/dir/a.txt', 'content': 'noi dung'}, 's1'))
    assert payload['relativePath'] == 'sub/dir/a.txt'
    assert payload['created'] is True
    assert payload['sha256Before'] is None
    assert payload['bytesWritten'] == len('noi dung'.encode('utf-8'))
    assert (executor.workspace / 'sub/dir/a.txt').read_text(encoding='utf-8') == 'noi dung'
    second = run(executor.execute('file_write', {'path': 'sub/dir/a.txt', 'content': 'khac'}, 's1'))
    assert second['created'] is False and second['sha256Before']


def test_file_edit_block_requires_a_unique_match(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'a.txt').write_text('mot hai mot', encoding='utf-8')
    payload = run(executor.execute('file_edit_block',
                                   {'path': 'a.txt', 'old_text': 'mot', 'new_text': 'ba'}, 's1'))
    assert payload['errorCode'] == 'TOOL_ARGUMENT_INVALID'
    fixed = run(executor.execute('file_edit_block',
                                 {'path': 'a.txt', 'old_text': 'hai', 'new_text': 'bon'}, 's1'))
    assert fixed['content'].startswith('Updated')
    assert (executor.workspace / 'a.txt').read_text(encoding='utf-8') == 'mot bon mot'


def test_missing_file_is_a_coded_error_not_a_traceback(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('file_read', {'path': 'khong-co.txt'}, 's1'))
    assert payload['errorCode'] == 'FILE_NOT_FOUND'


# ------------------------------------------------------------------ thoát workspace

def test_dotdot_escape_is_refused(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('file_read', {'path': '../outside.txt'}, 's1'))
    assert payload['errorCode'] == host.PATH_ESCAPE_CODE


def test_absolute_path_outside_workspace_is_refused(tmp_path):
    executor = make_executor(tmp_path)
    outside = tmp_path / 'outside.txt'
    outside.write_text('bi mat', encoding='utf-8')
    payload = run(executor.execute('file_read', {'path': str(outside)}, 's1'))
    assert payload['errorCode'] == host.PATH_ESCAPE_CODE


def test_symlink_escape_is_refused(tmp_path):
    executor = make_executor(tmp_path)
    outside = tmp_path / 'outside.txt'
    outside.write_text('bi mat', encoding='utf-8')
    link = executor.workspace / 'link.txt'
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):        # pragma: no cover - hệ tệp không cho symlink
        pytest.skip('hệ tệp không tạo được symlink')
    payload = run(executor.execute('file_read', {'path': 'link.txt'}, 's1'))
    assert payload['errorCode'] == host.PATH_ESCAPE_CODE


def test_write_outside_workspace_is_refused_before_touching_disk(tmp_path):
    executor = make_executor(tmp_path)
    outside = tmp_path / 'outside.txt'
    payload = run(executor.execute('file_write', {'path': str(outside), 'content': 'x'}, 's1'))
    assert payload['errorCode'] == host.PATH_ESCAPE_CODE
    assert not outside.exists()


def test_root_argument_scopes_paths_to_a_subdirectory(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'wt').mkdir()
    payload = run(executor.execute('file_write', {'path': 'a.txt', 'content': 'trong worktree'},
                                   's1', root='wt'))
    assert payload['relativePath'] == 'wt/a.txt'
    escaped = run(executor.execute('file_read', {'path': '../ngoai.txt'}, 's1', root='wt'))
    assert escaped['errorCode'] == host.PATH_ESCAPE_CODE


# ------------------------------------------------------------------ tìm mã

def test_codebase_glob_returns_relative_paths(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'src').mkdir()
    (executor.workspace / 'src' / 'a.py').write_text('x', encoding='utf-8')
    (executor.workspace / 'src' / 'b.txt').write_text('x', encoding='utf-8')
    payload = run(executor.execute('codebase_glob', {'pattern': 'src/*.py'}, 's1'))
    assert payload['content'] == 'src/a.py'


def test_codebase_glob_rejects_brace_expansion(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('codebase_glob', {'pattern': '**/*.{py,ts}'}, 's1'))
    assert payload['errorCode'] == 'TOOL_ARGUMENT_INVALID'


def test_codebase_grep_reports_path_line_and_text(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'src').mkdir()
    (executor.workspace / 'src' / 'a.py').write_text('mot\nhai\nba\n', encoding='utf-8')
    payload = run(executor.execute('codebase_grep', {'query': 'hai'}, 's1'))
    assert payload['content'] == 'src/a.py:2:hai'


def test_codebase_grep_skips_binary_files(tmp_path):
    executor = make_executor(tmp_path)
    (executor.workspace / 'a.bin').write_bytes(b'\xff\xfe\x00hai')
    (executor.workspace / 'b.txt').write_text('hai\n', encoding='utf-8')
    payload = run(executor.execute('codebase_grep', {'query': 'hai'}, 's1'))
    assert payload['content'] == 'b.txt:1:hai'


# ------------------------------------------------------------------ lệnh

def test_terminal_exec_runs_in_the_workspace(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('terminal_exec', {'command': 'pwd'}, 's1'))
    assert payload['exit_code'] == 0
    assert payload['is_error'] is False
    assert Path(payload['content'].strip()).resolve() == executor.workspace


def test_terminal_exec_marks_nonzero_exit_as_error(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('terminal_exec', {'command': 'exit 3'}, 's1'))
    assert payload['exit_code'] == 3
    assert payload['is_error'] is True


def test_terminal_exec_timeout_stops_the_process_group(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('terminal_exec', {'command': 'sleep 30', 'timeout': 1}, 's1'))
    assert payload['errorCode'] == host.COMMAND_TIMEOUT_CODE
    assert payload['timeout'] == 1


def test_terminal_exec_spills_long_output_to_an_artifact(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('terminal_exec',
                                   {'command': 'for i in $(seq 1 4000); do echo dong-$i; done'}, 's1'))
    assert payload['artifact'], 'output dài phải có tệp đầy đủ cho UI'
    artifact = executor.workspace / payload['artifact']
    assert artifact.is_file()
    assert 'dong-4000' in artifact.read_text(encoding='utf-8')
    assert payload['content'].endswith('[truncated; see artifact]')


def test_terminal_exec_requires_a_command(tmp_path):
    executor = make_executor(tmp_path)
    payload = run(executor.execute('terminal_exec', {'command': '   '}, 's1'))
    assert payload['errorCode'] == 'TOOL_ARGUMENT_INVALID'


def test_shell_argv_posix_uses_sh(tmp_path):
    executor = make_executor(tmp_path)
    assert executor.shell_argv('echo hi') == ['/bin/sh', '-c', 'echo hi']


def test_shell_argv_windows_uses_powershell_without_profile(tmp_path):
    executor = make_executor(tmp_path)
    executor.platform = 'win32'
    argv = executor.shell_argv('Get-ChildItem')
    assert argv[0].endswith('powershell.exe')
    assert argv[1:5] == ['-NoProfile', '-NonInteractive', '-OutputFormat', 'Text']
    assert argv[-1] == 'Get-ChildItem'


def test_cleanup_stops_a_running_command(tmp_path):
    executor = make_executor(tmp_path)

    async def scenario():
        task = asyncio.create_task(executor.execute('terminal_exec',
                                                    {'command': 'sleep 30', 'timeout': 30}, 's1'))
        await asyncio.sleep(0.4)
        await executor.cleanup('s1')
        return await asyncio.wait_for(task, timeout=10)

    payload = asyncio.run(scenario())
    assert payload['exit_code'] != 0


def test_child_env_forces_utf8(tmp_path):
    executor = make_executor(tmp_path)
    env = executor._child_env()
    assert env['PYTHONIOENCODING'] == 'utf-8'
    assert env['PYTHONUTF8'] == '1'


# ------------------------------------------- thẻ duyệt của host mode (slice 1b)

def test_approver_receives_the_session(tmp_path):
    seen = []

    def approver(tool, args, decision, session_id=None):
        seen.append(session_id)
        return 'allow'

    executor = make_executor(tmp_path, approver=approver)
    executor.policy.mode = 'ask'
    run(executor.execute('terminal_exec', {'command': 'echo xin-chao'}, 's1'))
    assert seen == ['s1']


def test_approve_session_remembers_and_approve_always_writes_a_rule(tmp_path):
    executor = make_executor(tmp_path, approver=lambda t, a, d, session_id=None: 'allow_session')
    executor.policy.mode = 'ask'
    run(executor.execute('terminal_exec', {'command': 'echo ca-phien'}, 's1'))
    key = executor.policy.session_key('terminal_exec', {'command': 'echo ca-phien'},
                                      cwd=executor.policy.workspace, session_id='s1')
    assert key in executor.policy.session_rules
    assert not executor.policy.paths[perms.LAYER_PROJECT].exists()

    other = make_executor(tmp_path, approver=lambda t, a, d, session_id=None: 'allow_always')
    other.policy.mode = 'ask'
    run(other.execute('terminal_exec', {'command': 'echo luon-cho'}, 's1'))
    assert 'terminal_exec(echo luon-cho)' in other.policy.paths[perms.LAYER_PROJECT].read_text(encoding='utf-8')


def test_prompt_choices_map_to_verdicts():
    """Bốn lựa chọn trên thẻ ⇒ verdict của executor; chữ tự nhập ⇒ từ chối."""
    ask_decision = perms.ask('cần hỏi', '', 'mode')
    guarded = perms.ask('nhóm luôn hỏi', 'guarded:git_force_push', 'guarded')
    approved = lambda choice: {'status': 'approved', 'choice': choice}
    assert host.approval_verdict(approved('approve'), ask_decision) == 'allow'
    assert host.approval_verdict(approved('approve_session'), ask_decision) == 'allow_session'
    assert host.approval_verdict(approved('approve_always'), ask_decision) == 'allow_always'
    assert host.approval_verdict(approved('reject'), ask_decision) == 'deny'
    assert host.approval_verdict(approved('chắc là được'), ask_decision) == 'deny'
    assert host.approval_verdict({'status': 'rejected'}, ask_decision) == 'deny'
    assert host.approval_verdict(approved('approve_session'), guarded) == 'deny'
    assert [item['id'] for item in host.approval_options(guarded)] == ['approve', 'reject']


def test_free_text_verdict_is_a_denial(tmp_path):
    executor = make_executor(tmp_path, approver=lambda t, a, d, session_id=None: 'chắc là được')
    executor.policy.mode = 'ask'
    result = run(executor.execute('terminal_exec', {'command': 'echo x'}, 's1'))
    assert result['errorCode'] == host.PERMISSION_DENIED_CODE


def test_guarded_command_stays_single_shot(tmp_path):
    calls = []

    def approver(tool, args, decision, session_id=None):
        calls.append(decision.rule)
        return 'allow_session'

    executor = make_executor(tmp_path, approver=approver)
    executor.policy.mode = 'trusted'
    for _ in range(2):
        run(executor.execute('terminal_exec', {'command': 'git push --force origin main'}, 's1'))
    assert len(calls) == 2, 'nhóm luôn hỏi không được ghi nhớ'
    assert all(rule.startswith('guarded:') for rule in calls)
    assert executor.policy.session_rules == {}


def test_approver_options_match_the_prompt_contract(tmp_path):
    seen = {}

    def approver(tool, args, decision, session_id=None):
        seen['options'] = host.approval_options(decision)
        return 'deny'

    executor = make_executor(tmp_path, approver=approver)
    executor.policy.mode = 'ask'
    run(executor.execute('terminal_exec', {'command': 'echo x'}, 's1'))
    assert [item['id'] for item in seen['options']] == ['approve', 'approve_session', 'approve_always', 'reject']

    run(executor.execute('terminal_exec', {'command': 'git push --force'}, 's1'))
    assert [item['id'] for item in seen['options']] == ['approve', 'reject']
