"""Coverage measurement must accept content under nested Markdown headings."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('output_budget_eval',
    Path(__file__).resolve().parents[3] / 'scripts/eval/output_budget_eval.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


def test_nested_sections_are_counted():
    text = '## Mục tiêu\n### Chi tiết\n' + 'a'*100 + '\n## Giới hạn\n' + 'b'*100 + '\nEND_REPORT'
    assert evaluator.coverage(text, ('fixture',['Mục tiêu','Giới hạn'],''))['missingSections'] == []


def test_empty_and_missing_sections_fail():
    report = evaluator.coverage('## Mục tiêu\nshort\nEND_REPORT', ('fixture',['Mục tiêu','Giới hạn'],''))
    assert report['missingSections'] == ['Mục tiêu','Giới hạn']
    assert report['endMarker'] is True
