"""Three approval levels: isolated paths, policy matrix and real Windows file/shell calls."""
import asyncio
import os
from pathlib import Path

import pytest

from agentbox.agent_core import permissions as perms
from agentbox.sandbox.host_executor import HostExecutor


@pytest.fixture
def policy(tmp_path):
    workspace = tmp_path / 'project'
    workspace.mkdir()
    return perms.PermissionPolicy(str(workspace), home=tmp_path / 'home',
                                  profile_dir=tmp_path / 'profile',
                                  install_dir=tmp_path / 'install', env={})


@pytest.mark.parametrize('mode,scope,write,exec_', [
    ('ask', 'workspace', 'ask', 'ask'), ('auto', 'workspace', 'allow', 'allow'),
    ('trusted', 'machine', 'allow', 'allow'),
])
def test_level_matrix(policy, mode, scope, write, exec_):
    policy.mode = mode
    snap = policy.snapshot()
    assert snap['modes'] == ['ask', 'auto', 'trusted']
    assert snap['scope'] == scope and snap['scopeDerived'] is True
    assert policy.decide('file_read', {'path': 'a.txt'}).allowed
    assert policy.decide('file_write', {'path': 'a.txt'}).outcome == write
    assert policy.decide('terminal_exec', {'command': 'npm run build'}).outcome == exec_
    assert policy.decide('terminal_exec', {'command': 'git status --short'}).allowed
    assert policy.decide('terminal_exec', {'command': 'format C:'}).outcome == 'deny'
    assert policy.decide('terminal_exec', {'command': 'git push --force origin main'}).layer == 'guarded'


@pytest.mark.parametrize('source', ['constructor', 'file', 'env'])
def test_legacy_plan_never_migrates_to_auto_or_full(policy, source):
    if source == 'constructor':
        policy.mode = 'plan'
    elif source == 'file':
        policy.layers[perms.LAYER_USER] = {'mode': 'plan', 'scope': 'machine'}
    else:
        policy.env['BOXFOX_PERMISSION_MODE'] = 'plan'
        policy.env['BOXFOX_PERMISSION_SCOPE'] = 'machine'
    assert policy.mode_value() == 'ask'
    assert policy.scope_value() == 'workspace'
    assert policy.decide('file_write', {'path': 'x'}).outcome == 'ask'


@pytest.mark.parametrize('mode', ['ask', 'auto', 'trusted'])
@pytest.mark.parametrize('network', ['restricted', 'enabled'])
def test_network_matrix(policy, mode, network):
    policy.mode = mode
    policy.env['BOXFOX_PERMISSION_NETWORK'] = network
    command = policy.decide('terminal_exec', {'command': 'curl https://example.com'})
    assert command.outcome == ('allow' if mode != 'ask' and network == 'enabled' else 'ask')


@pytest.mark.parametrize('command', [
    'Get-ChildItem', 'Get-Content -LiteralPath "a file.txt" -TotalCount 20',
    'Test-Path a.txt', 'Get-Item a.txt', 'pwd', 'git ls-files',
])
def test_recognised_inspection_runs_without_approval(policy, command):
    assert policy.decide('terminal_exec', {'command': command}).allowed


@pytest.mark.parametrize('command', [
    'Get-Content ../outside.txt', 'Get-Content a.txt > b.txt',
    'Get-Content a.txt; Remove-Item a.txt', 'Get-Content $env:USERPROFILE',
    'Get-Content a.txt | Invoke-Expression', 'python script.py', 'npm test',
    'powershell -Command "Get-Content a.txt"', 'git diff --ext-diff',
])
def test_unrecognised_or_mutating_commands_ask(policy, command):
    assert policy.decide('terminal_exec', {'command': command}).outcome == 'ask'


def test_auto_explicit_outside_command_asks(policy):
    policy.mode = 'auto'
    assert policy.decide('terminal_exec', {'command': 'Set-Content ../outside.txt x'}).outcome == 'ask'


def executor(policy, approver=None):
    return HostExecutor(policy.workspace, policy=policy, approver=approver,
                        env=dict(os.environ), artifacts_dir=policy.profile_dir / 'artifacts')


def test_auto_outside_file_requires_actual_approval(policy, tmp_path):
    policy.mode = 'auto'
    outside = tmp_path / 'outside.txt'
    args = {'path': str(outside), 'content': 'new'}
    result = asyncio.run(executor(policy).execute('file_write', args, 's1'))
    assert result['errorCode'] == 'PERMISSION_DENIED' and not outside.exists()
    calls = []
    def approve(tool, args, decision, session_id=None):
        calls.append((tool, args['path'], session_id))
        return 'allow'
    result = asyncio.run(executor(policy, approve).execute('file_write', args, 's1'))
    assert not result.get('is_error') and outside.read_text() == 'new'
    assert calls == [('file_write', str(outside.resolve()), 's1')]


def test_full_access_reads_writes_and_edits_outside_project(policy, tmp_path):
    policy.mode = 'trusted'
    outside = tmp_path / 'outside.txt'
    host = executor(policy)
    assert not asyncio.run(host.execute('file_write', {'path': str(outside), 'content': 'old'}, 's1')).get('is_error')
    assert asyncio.run(host.execute('file_read', {'path': str(outside)}, 's1'))['content'] == 'old'
    assert not asyncio.run(host.execute('file_edit_block', {'path': str(outside), 'old_text': 'old', 'new_text': 'new'}, 's1')).get('is_error')
    assert outside.read_text() == 'new'
    policy.layers[perms.LAYER_USER] = {'deny': ['file_read(//%s)' % str(outside).replace('\\', '/')]}
    assert asyncio.run(host.execute('file_read', {'path': str(outside)}, 's1'))['errorCode'] == 'PERMISSION_DENIED'


def test_full_access_never_overrides_explicit_child_root(policy):
    policy.mode = 'trusted'
    child = Path(policy.workspace) / 'child'
    child.mkdir()
    result = asyncio.run(executor(policy).execute('file_write', {'path': '../escape.txt', 'content': 'x'}, 's1', root='child'))
    assert result['errorCode'] == 'PATH_OUTSIDE_WORKSPACE'
    assert not (Path(policy.workspace) / 'escape.txt').exists()


def test_mode_change_invalidates_session_approval_key(policy):
    args = {'path': 'x.txt'}
    key = policy.session_key('file_write', args, session_id='s1')
    policy.remember(key, perms.allow('', 'user'))
    policy.mode = 'auto'
    assert key != policy.session_key('file_write', args, session_id='s1')


def test_file_level_does_not_rewrite_existing_cua_boundary(policy):
    policy.layers[perms.LAYER_USER] = {'scope': 'workspace'}
    policy.mode = 'trusted'
    assert policy.scope_value() == 'machine'
    assert policy.cua_scope_value() == 'workspace'
    policy.layers[perms.LAYER_USER] = {}
    policy.mode = 'ask'
    assert policy.scope_value() == 'workspace'
    assert policy.cua_scope_value() == 'machine'
    assert policy.decide('computer_use', {'action': 'click'}).outcome == 'ask'


def test_invalid_inspection_path_asks_instead_of_throwing(policy):
    assert not policy.inspection_command('Get-Content "bad\x00path"')


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows PowerShell execution')
def test_windows_inspection_then_mutation_approval(policy):
    target = Path(policy.workspace) / 'a file.txt'
    target.write_text('native inspection', encoding='utf-8')
    host = executor(policy)
    result = asyncio.run(host.execute('terminal_exec', {'command': 'Get-Content -LiteralPath "a file.txt"'}, 's1'))
    assert result['exit_code'] == 0 and 'native inspection' in result['content']
    result = asyncio.run(host.execute('terminal_exec', {'command': 'Set-Content "a file.txt" changed'}, 's1'))
    assert result['errorCode'] == 'PERMISSION_DENIED'
    assert target.read_text() == 'native inspection'


@pytest.mark.skipif(os.name != 'nt', reason='Real Windows junction')
def test_junction_outside_target_is_not_auto_approved(policy, tmp_path):
    import subprocess
    outside = tmp_path / 'outside-dir'
    outside.mkdir()
    (outside / 'secret.txt').write_text('secret')
    link = Path(policy.workspace) / 'linked'
    created = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(link), str(outside)], capture_output=True)
    assert created.returncode == 0
    try:
        policy.mode = 'auto'
        result = asyncio.run(executor(policy).execute('file_read', {'path': 'linked/secret.txt'}, 's1'))
        assert result['errorCode'] == 'PERMISSION_DENIED'
        policy.mode = 'trusted'
        assert asyncio.run(executor(policy).execute('file_read', {'path': 'linked/secret.txt'}, 's1'))['content'] == 'secret'
    finally:
        link.rmdir()  # Remove the junction itself, never its target.
