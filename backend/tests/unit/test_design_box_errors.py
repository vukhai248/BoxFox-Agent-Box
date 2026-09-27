"""Chối của worker QUA BOX THẬT phải ra mã hợp đồng `DESIGN_*`, không phải `KeyError`.

`sandbox/executor.py` `_execute` trả payload của worker NGUYÊN VĂN: một op bị chối quay về host dưới
dạng `{'is_error': True, 'error': 'MÃ: câu'}` chứ KHÔNG ném. Các bài trong `test_design_write.py` và
`test_design_revert.py` dùng executor gọi thẳng `worker.execute` (ném `ValueError`) nên không bao giờ
chạm ranh giới ấy — đó là lý do lỗi `KeyError` không hiện trong suite cũ.

Ở đây box giả trả ĐÚNG payload `is_error` của worker. Bài khẳng định `runtime.dispatch` ném một
`ValueError` mang mã hợp đồng (không phải `KeyError`), giữ câu `DESIGN_ERROR_TEXT`, và
`failures.classify_failure` đọc ra đúng mã ấy cho lượt (khuôn `WEB_`).
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.failures import classify_failure
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class RefusingBox:
    """Box giả trả payload worker NGUYÊN VĂN; `refusals` ánh xạ op → câu lỗi của worker."""

    def __init__(self, refusals=None):
        self.refusals = dict(refusals or {})
        self.calls = []

    async def execute(self, name, args, sid, **_identity):
        self.calls.append((name, dict(args)))
        if name in self.refusals:
            return {'is_error': True, 'error': self.refusals[name]}
        if name == 'design_file_sha':
            return {'path': args.get('path'), 'sha256': 'a' * 64, 'sizeChars': 3}
        if name == 'design_branch_create':
            return {'branch': args.get('name'), 'base': 'b' * 40, 'head': 'b' * 40}
        if name == 'design_write':
            return {'path': args.get('path'), 'mode': args.get('mode'), 'sha256': 'c' * 64,
                    'bytes': 42}
        if name == 'design_diff':
            return {'files': [], 'patch': ''}
        if name == 'design_revert':
            return {'reverted': [], 'deleted': []}
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'box-errors.db')
    executor = RefusingBox()
    runtime = HarnessRuntime(store, executor, FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1'})['id']
    yield store, runtime, sid, executor
    store.close()


def open_run(runtime, store, sid):
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế lại màn hình chat')
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    return store.design_job(job['design_id'])


def approve(runtime, store, sid, job, items):
    live = store.design_job(job['design_id'])
    design_runtime.design_touch_list_store(runtime, sid, live, items)
    live = store.design_job(job['design_id'])
    return design_runtime.design_touch_list_approve(runtime, sid, live,
                                                    live['state']['touchList']['revision'])


def item(kind, path):
    return {'kind': kind, 'path': path, 'reason': 'lý do', 'risk': 'low'}


def call(runtime, store, sid, name, args):
    async def run():
        return await runtime.dispatch(store.get(sid), name, args)

    return asyncio.run(run())


def prepare(runtime, store, sid):
    """Mode + run + danh sách chạm đã duyệt + một nhánh thiết kế (box giả nhận hết)."""
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job,
            [item('new', 'src/inside.txt'), item('insert', 'app.txt')])
    call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1200'})
    return store.design_job(job['design_id'])


def test_a_refused_design_write_surfaces_the_contract_code(harness):
    """Gốc BUG-A: box thật trả `{'is_error': True, ...}` cho `design_write` ⇒ mã hợp đồng, không KeyError."""
    store, runtime, sid, executor = harness
    prepare(runtime, store, sid)
    executor.refusals['design_write'] = (
        "DESIGN_WRITE_EXISTS: Tệp đã tồn tại; dùng kiểu 'chèn' thay vì 'tạo mới'.")

    with pytest.raises(ValueError) as raised:
        call(runtime, store, sid, 'design_write',
             {'path': 'src/inside.txt', 'content': 'x\n', 'mode': 'create'})

    assert not isinstance(raised.value, KeyError), 'chối của worker không được thành KeyError'
    assert str(raised.value).startswith(limits.DESIGN_WRITE_EXISTS_CODE)
    assert limits.DESIGN_ERROR_TEXT[limits.DESIGN_WRITE_EXISTS_CODE] in str(raised.value)
    # Lượt đọc mã này: `DESIGN_` là tiền tố đã biết nên lỗi ra đúng mã hợp đồng, không phải
    # `TURN_FAILED_VALUEERROR`.
    assert classify_failure(raised.value)[0] == limits.DESIGN_WRITE_EXISTS_CODE


def test_a_refused_design_write_missing_file_surfaces_its_code(harness):
    store, runtime, sid, executor = harness
    prepare(runtime, store, sid)
    executor.refusals['design_write'] = (
        "DESIGN_WRITE_MISSING: Tệp chưa tồn tại; dùng kiểu 'tạo mới' thay vì 'chèn'.")

    with pytest.raises(ValueError, match=limits.DESIGN_WRITE_MISSING_CODE):
        call(runtime, store, sid, 'design_write',
             {'path': 'src/inside.txt', 'content': 'x\n', 'mode': 'insert', 'position': 'append'})


def test_a_refused_design_branch_create_surfaces_the_contract_code(harness):
    """Cùng hình dạng cho `design_branch_create` (mã có trong `DESIGN_ERROR_TEXT`)."""
    store, runtime, sid, executor = harness
    open_run(runtime, store, sid)
    executor.refusals['design_branch_create'] = (
        'DESIGN_BRANCH_EXISTS: Tên nhánh thiết kế đã tồn tại.')

    with pytest.raises(ValueError, match=limits.DESIGN_BRANCH_EXISTS_CODE):
        call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1200'})


def test_a_refused_design_revert_keeps_the_worker_message(harness):
    """Mã worker KHÔNG có trong `DESIGN_ERROR_TEXT` ⇒ giữ NGUYÊN VĂN câu của worker (không nuốt)."""
    store, runtime, sid, executor = harness
    prepare(runtime, store, sid)
    executor.refusals['design_revert'] = (
        'DESIGN_REVERT_FAILED: không khôi phục được app.txt: boom')

    with pytest.raises(ValueError) as raised:
        call(runtime, store, sid, 'design_revert', {'paths': ['app.txt'], 'mode': 'file'})

    assert str(raised.value) == 'DESIGN_REVERT_FAILED: không khôi phục được app.txt: boom'
    assert classify_failure(raised.value)[0] == 'DESIGN_REVERT_FAILED'


def test_a_refused_design_diff_without_a_code_keeps_the_message(harness):
    """Worker `design_diff` chối bằng câu KHÔNG có mã ⇒ câu ấy đi lên nguyên vẹn."""
    store, runtime, sid, executor = harness
    prepare(runtime, store, sid)
    executor.refusals['design_diff'] = 'Không so được với mốc `base`: boom'

    with pytest.raises(ValueError) as raised:
        call(runtime, store, sid, 'design_diff', {})

    assert str(raised.value) == 'Không so được với mốc `base`: boom'


def test_a_missing_box_file_still_reads_as_none(harness):
    """`_box_file_sha` giữ nguyên nghĩa: chối của worker (tệp thiếu) ⇒ `None`, không ném."""
    store, runtime, sid, executor = harness
    prepare(runtime, store, sid)
    executor.refusals['design_file_sha'] = (
        "DESIGN_WRITE_MISSING: Tệp chưa tồn tại; dùng kiểu 'tạo mới' thay vì 'chèn'.")

    async def read():
        return await design_runtime._box_file_sha(runtime, sid, 'missing.txt')

    assert asyncio.run(read()) is None
    executor.refusals.pop('design_file_sha')
    assert asyncio.run(read()) == 'a' * 64
