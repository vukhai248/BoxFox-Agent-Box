"""Chốt trần hồi quy của `tools/cua_bench.py` phải ĐÓNG khi thiếu số đo.

Chốt này tồn tại để bắt hồi quy latency. Bản đầu duyệt theo *số đo* nên một phép đo biến mất hoặc
lỗi (``n = 0``) bị bỏ qua — đúng lúc cần chốt nhất (ví dụ `click` hỏng hẳn thì không còn số đo nào
để so, và chốt in "ĐẠT"). Duyệt theo *trần* thì thiếu số đo cũng là VƯỢT.
"""
import importlib.util
import pathlib

import pytest

_BENCH = pathlib.Path(__file__).resolve().parents[2] / 'tools' / 'cua_bench.py'


def _bench():
    spec = importlib.util.spec_from_file_location('cua_bench_under_test', _BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_missing_measurement_is_a_failure_not_a_pass():
    bench = _bench()
    over = bench.check_budget({})
    assert over, 'thiếu hết số đo mà chốt vẫn im lặng là chốt vô dụng'
    assert all('KHÔNG ĐO ĐƯỢC' in item for item in over)


def test_an_errored_measurement_is_a_failure():
    bench = _bench()
    measurements = {name: {'n': 5, 'p95': 1.0} for name in bench.DEFAULT_BUDGET_MS}
    measurements['product.click'] = {'n': 0, 'error': 'SOURCE_CHANGED: cửa sổ đích không có tiêu điểm'}
    over = bench.check_budget(measurements)
    assert len(over) == 1
    assert over[0].startswith('product.click: KHÔNG ĐO ĐƯỢC')
    assert 'SOURCE_CHANGED' in over[0], 'phải giữ lại lý do để còn đọc được'


def test_a_genuine_overflow_is_still_reported():
    bench = _bench()
    measurements = {name: {'n': 5, 'p95': 1.0} for name in bench.DEFAULT_BUDGET_MS}
    measurements['primitives.capture_window'] = {'n': 5, 'p95': 9999.0}
    over = bench.check_budget(measurements)
    assert over == ['primitives.capture_window: p95 9999.0 ms > %s ms'
                    % bench.DEFAULT_BUDGET_MS['primitives.capture_window']]


def test_a_clean_run_reports_nothing():
    bench = _bench()
    measurements = {name: {'n': 5, 'p95': 1.0} for name in bench.DEFAULT_BUDGET_MS}
    assert bench.check_budget(measurements) == []


@pytest.mark.parametrize('name', ['product.screenshot', 'product.click', 'primitives.click'])
def test_every_budgeted_name_is_actually_measured_by_the_tool(name):
    """Trần cho một tên mà công cụ không hề đo thì mãi mãi "KHÔNG ĐO ĐƯỢC" — phải khớp nhau."""
    source = _BENCH.read_text()
    assert "timed('%s'" % name in source or "timed('primitives.%s'" % name.split('.', 1)[1] in source, \
        'trần có tên %s nhưng công cụ không đo tên đó' % name
