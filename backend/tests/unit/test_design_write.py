"""P3 — đường ghi có gác ở tầng harness (plan v1 §6.5 + §8 P3).

Mỗi bài chạy trên một repo git THẬT trong `tmp_path` (máy chủ nhà không có workspace của box), qua
ĐÚNG cửa vào `runtime.dispatch`, và với một executor mỏng gọi thẳng `sandbox.worker.execute` —
nghĩa là lớp gác của HARNESS và lớp gác của WORKER đều được chạy, không mô phỏng.

Bài khẳng định: ghi ngoài danh sách chạm bị chối; nhánh chính bị chối; `create` trên tệp đã có /
`insert` vào tệp chưa có bị chối; anchor khớp hai lần bị chối; tham số chứa `;`/`&&` không bao giờ
tới shell; tệp đã đổi kể từ lúc duyệt danh sách chạm bị chối `DESIGN_WRITE_STALE`.
"""
from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

import pytest

import agentbox.sandbox.worker as worker
from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

INITIAL = 'alpha\nbeta\ngamma\n'


def _git(root, *args, check=True):
    proc = subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True)
    if check and proc.returncode:
        raise AssertionError('git %s failed: %s' % (' '.join(args), proc.stderr))
    return proc


def _repo(tmp_path):
    root = Path(tmp_path).resolve()
    worker.ROOT = root
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'config', 'user.email', 'box@example.com')
    _git(root, 'config', 'user.name', 'Box')
    (root / 'app.txt').write_text(INITIAL, encoding='utf-8')
    (root / 'second.txt').write_text('one\ntwo\n', encoding='utf-8')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'init')
    return root


class WorkerExecutor:
    """Box giả gọi ĐÚNG cửa vào của worker, trên `worker.ROOT` đã trỏ vào repo tạm."""

    async def execute(self, name, args, sid, **_identity):
        return worker.execute(name, args, sid)

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    root = _repo(tmp_path)
    store = SessionStore(tmp_path / 'write.db')
    runtime = HarnessRuntime(store, WorkerExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1'})['id']
    yield store, runtime, sid, root
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
    revision = live['state']['touchList']['revision']
    return design_runtime.design_touch_list_approve(runtime, sid, live, revision)


def call(runtime, store, sid, name, args):
    async def run():
        return await runtime.dispatch(store.get(sid), name, args)
    return asyncio.run(run())


def make_branch(runtime, store, sid):
    return call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1200'})


def item(kind, path, **over):
    payload = {'kind': kind, 'path': path, 'reason': 'lý do', 'risk': 'low'}
    payload.update(over)
    return payload


def write(runtime, store, sid, **args):
    return call(runtime, store, sid, 'design_write', args)


# ---------------------------------------------------------------- gác đường dẫn


def test_write_outside_touch_list_refused(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'src/inside.txt')])
    make_branch(runtime, store, sid)

    with pytest.raises(ValueError, match=limits.DESIGN_PATH_NOT_APPROVED_CODE):
        write(runtime, store, sid, path='src/outside.txt', content='x\n', mode='create')
    assert not (root / 'src/outside.txt').exists()


def test_hard_forbidden_path_is_refused(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'package.json')])
    make_branch(runtime, store, sid)

    with pytest.raises(ValueError, match=limits.DESIGN_PATH_NOT_APPROVED_CODE):
        write(runtime, store, sid, path='package.json', content='{}\n', mode='create')
    assert not (root / 'package.json').exists()


def test_main_branch_is_forbidden(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('insert', 'app.txt')])
    make_branch(runtime, store, sid)
    # Nhánh thiết kế đã được ghi vào run; đưa git về nhánh chính sau lưng harness ⇒ lớp gác của
    # WORKER phải là thứ chặn, đúng câu hợp đồng.
    _git(root, 'checkout', '-q', 'main')
    with pytest.raises(ValueError, match=limits.DESIGN_MAIN_BRANCH_FORBIDDEN_CODE):
        write(runtime, store, sid, path='app.txt', content='BETA\n', mode='insert',
              position='append')
    assert (root / 'app.txt').read_text(encoding='utf-8') == INITIAL


def test_no_branch_is_required_before_writing(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'src/new.txt')])
    with pytest.raises(ValueError, match=limits.DESIGN_BRANCH_REQUIRED_CODE):
        write(runtime, store, sid, path='src/new.txt', content='x\n', mode='create')


# ---------------------------------------------------------------- create / insert


def test_create_over_existing_refused(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'app.txt')])
    make_branch(runtime, store, sid)

    with pytest.raises(ValueError, match=limits.DESIGN_WRITE_EXISTS_CODE):
        write(runtime, store, sid, path='app.txt', content='x\n', mode='create')
    assert (root / 'app.txt').read_text(encoding='utf-8') == INITIAL


def test_insert_into_missing_file_refused(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('insert', 'nope.txt')])
    make_branch(runtime, store, sid)

    with pytest.raises(ValueError, match=limits.DESIGN_WRITE_MISSING_CODE):
        write(runtime, store, sid, path='nope.txt', content='x\n', mode='insert',
              position='append')
    assert not (root / 'nope.txt').exists()


def test_anchor_must_be_unique(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('insert', 'app.txt')])
    make_branch(runtime, store, sid)
    (root / 'app.txt').write_text('beta\nbeta\n', encoding='utf-8')

    with pytest.raises(ValueError, match=limits.DESIGN_ANCHOR_NOT_UNIQUE_CODE):
        write(runtime, store, sid, path='app.txt', content='x\n', mode='insert', anchor='beta')
    assert (root / 'app.txt').read_text(encoding='utf-8') == 'beta\nbeta\n'


def test_a_valid_write_records_the_action_and_flips_the_item(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('insert', 'app.txt', sha256=hashlib.sha256(
        INITIAL.encode('utf-8')).hexdigest())])
    make_branch(runtime, store, sid)

    result = write(runtime, store, sid, path='app.txt', content='BETA\n', mode='insert',
                   anchor='beta\n')
    assert result['path'] == 'app.txt' and result['mode'] == 'insert'
    assert result['sha256'] and result['bytes'] == len('alpha\nbeta\nBETA\ngamma\n'.encode('utf-8'))
    assert (root / 'app.txt').read_text(encoding='utf-8') == 'alpha\nbeta\nBETA\ngamma\n'

    live = store.design_job(job['design_id'])['state']
    entry = next(row for row in live['touchList']['items'] if row['path'] == 'app.txt')
    assert entry['status'] == 'written' and entry['sha256'] == result['sha256']
    assert live['actions'] and live['actions'][-1]['path'] == 'app.txt'
    assert '.design/' in live['actions'][-1]['logPath']


# ---------------------------------------------------------------- stale + shell


def test_stale_file_is_refused(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('insert', 'app.txt', sha256=hashlib.sha256(
        INITIAL.encode('utf-8')).hexdigest())])
    make_branch(runtime, store, sid)
    # Tệp đổi sau khi danh sách chạm được duyệt (băm đã ghim) ⇒ phải từ chối trước khi gọi worker.
    (root / 'app.txt').write_text('alpha\nBETA\ngamma\n', encoding='utf-8')

    with pytest.raises(ValueError, match=limits.DESIGN_WRITE_STALE_CODE):
        write(runtime, store, sid, path='app.txt', content='X\n', mode='insert', anchor='beta\n')
    assert (root / 'app.txt').read_text(encoding='utf-8') == 'alpha\nBETA\ngamma\n'


def test_parameters_with_shell_meta_never_reach_a_shell(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'note.txt')])

    with pytest.raises(ValueError, match='nhánh thiết kế không hợp lệ'):
        call(runtime, store, sid, 'design_branch_create',
             {'name': 'design/x; touch canary.txt'})
    make_branch(runtime, store, sid)

    canary = root / 'canary.txt'
    payload = 'hello; touch canary.txt && echo $(id) `id`\n'
    result = write(runtime, store, sid, path='note.txt', content=payload, mode='create')
    assert result['path'] == 'note.txt'
    assert (root / 'note.txt').read_text(encoding='utf-8') == payload, 'nội dung ghi NGUYÊN VĂN'
    assert not canary.exists(), 'không lệnh nào được chạy'
