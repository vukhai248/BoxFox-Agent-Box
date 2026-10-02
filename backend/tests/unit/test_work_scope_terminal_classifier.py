"""W8.A4.2 — bộ phân loại lệnh terminal: mặc định là `mutate`, chỉ allowlist mới là `read`."""
import pytest

from agentbox.agent_core.work_scope import classify_command

READ = [
    'pwd',
    'ls -la',
    'git log --oneline -5',
    'cd repo && git status',
    'rg foo | head',
    'cat README.md',
    'git diff --stat',
    'git branch --show-current',
    'git remote -v',
    'find . -name "*.py"',
    'wc -l backend/src/agentbox/agent_core/work_scope.py',
    'grep -n classify backend/src/agentbox/agent_core/work_scope.py | head -3',
    'cd backend && ls',
    'git show --stat HEAD',
]

MUTATE = [
    'pip install requests',
    'echo x > f',
    'git -c core.x=y status',
    'find . -delete',
    'X=1 ls',
    'ls $(rm f)',
    'echo `rm f`',
    'python -c "print(1)"',
    'npm test',
    'git checkout -b feature',
    'ls; rm f',
    'make build',
    'cat a > b',
    'echo a && rm f',
    'ls & rm f',
    'sudo ls',
    'node -e 1',
    'pytest -q',
    'git diff --output=out.patch',
    'git log\nrm f',
    'rg --pre=./hook foo',
    '',
    None,
    'ls "unterminated',
]


@pytest.mark.parametrize('command', READ)
def test_read_only_commands_are_allowed(command):
    assert classify_command(command) == 'read'


@pytest.mark.parametrize('command', MUTATE)
def test_everything_else_is_a_mutation(command):
    assert classify_command(command) == 'mutate'
