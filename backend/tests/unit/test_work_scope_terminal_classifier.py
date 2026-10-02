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
    # Đối chứng cho F1/N1: tuỳ chọn dài KHÔNG được khớp tiền tố (--prefix/--pretty không phải --pre),
    # và tuỳ chọn ngắn không bị cấm vẫn là đọc.
    'git grep -n foo',
    'git log --pretty=oneline -3',
    'rg --prefix-check foo',
    'tree -L 2 .',
    'tree .',
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
    # F1 — dạng DÍNH LIỀN của tuỳ chọn ngắn: `git grep -O<cmd>` CHẠY `<cmd>`; `tree -o<file>` ghi file.
    "git grep -O'touch f' foo",
    'git grep -Orm foo',
    'git grep -O rm foo',
    'git grep --open-files-in-pager=rm foo',
    'git grep --open-files-in-pager rm foo',
    'git -ccore.x=y status',
    'tree -oout.txt .',
    'tree -o out.txt .',
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
