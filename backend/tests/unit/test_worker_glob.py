"""W1: an unsupported glob must not become evidence of an empty repository."""
import pytest

from agentbox.agent_core.failures import classify_failure
from agentbox.sandbox import worker


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'ROOT', tmp_path.resolve())
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src' / 'app.py').write_text('pass', encoding='utf-8')
    (tmp_path / 'src' / 'app.ts').write_text('export {}', encoding='utf-8')
    return tmp_path


@pytest.mark.parametrize('pattern', ['**/*.{py,ts}', '**/{src,tests}/*.py', '**/file{1..3}.py'])
def test_brace_glob_is_an_actionable_error_instead_of_empty_content(workspace, pattern):
    with pytest.raises(ValueError, match='GLOB_PATTERN_INVALID') as caught:
        worker.execute('codebase_glob', {'pattern': pattern}, 's1')
    assert classify_failure(caught.value)[0] == 'GLOB_PATTERN_INVALID'
    assert 'separate' in str(caught.value) and '**/*.py' in str(caught.value)


@pytest.mark.parametrize('pattern', [None, '', [], 123])
def test_invalid_glob_shape_names_the_field(workspace, pattern):
    with pytest.raises(ValueError, match='GLOB_PATTERN_INVALID: pattern'):
        worker.execute('codebase_glob', {'pattern': pattern}, 's1')


def test_supported_globs_and_genuinely_empty_matches_keep_the_contract(workspace):
    assert worker.execute('codebase_glob', {'pattern': '**/*.py'}, 's1') == {'content': 'src/app.py'}
    assert set(worker.execute('codebase_glob', {}, 's1')['content'].splitlines()) == {'src/app.py', 'src/app.ts'}
    assert worker.execute('codebase_glob', {'pattern': '**/*.sql'}, 's1') == {'content': ''}


def test_literal_braces_and_glob_character_classes_are_not_expansion(workspace):
    (workspace / '{notes}.md').write_text('notes', encoding='utf-8')
    assert worker.execute('codebase_glob', {'pattern': '{notes}.md'}, 's1')['content'] == '{notes}.md'
    (workspace / '{a,b}.md').write_text('notes', encoding='utf-8')
    assert worker.execute('codebase_glob', {'pattern': '[{]a,b[}].md'}, 's1')['content'] == '{a,b}.md'


def test_glob_workspace_boundary_and_result_cap_are_unchanged(workspace):
    with pytest.raises(ValueError, match='outside sandbox workspace'):
        worker.execute('codebase_glob', {'pattern': '../*.py'}, 's1')
    for i in range(505):
        (workspace / f'file{i}.txt').write_text('x', encoding='utf-8')
    assert len(worker.execute('codebase_glob', {'pattern': '*.txt'}, 's1')['content'].splitlines()) == 500
