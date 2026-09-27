"""P3 — hoàn tác byte-identical và `HEAD` đứng yên (plan v1 §6.5 + §8 P3).

Repo git THẬT trong `tmp_path`, executor mỏng gọi thẳng `sandbox.worker.execute`; bài chạy qua
`runtime.dispatch` và tuyến `PATCH /api/agent/design/runs/{id}` (`action:'revert-batch'`). Bằng
chứng cuối cùng: `main` không nhích, cây làm việc trở lại đúng byte của `base`, và `git status
--porcelain` sạch.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

import agentbox.sandbox.worker as worker
from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
INITIAL = 'alpha\nbeta\ngamma\n'
A_BODY = 'export const a = 1;\n'
B_BODY = 'export const b = 2;\n'


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
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'init')
    return root


class WorkerExecutor:
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
    store = SessionStore(tmp_path / 'revert.db')
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
    return design_runtime.design_touch_list_approve(runtime, sid, live,
                                                    live['state']['touchList']['revision'])


def call(runtime, store, sid, name, args):
    async def run():
        return await runtime.dispatch(store.get(sid), name, args)
    return asyncio.run(run())


def item(kind, path, **over):
    payload = {'kind': kind, 'path': path, 'reason': 'lý do', 'risk': 'low'}
    payload.update(over)
    return payload


def porcelain(root):
    return [line for line in _git(root, 'status', '--porcelain').stdout.splitlines() if line.strip()]


def test_batch_revert_restores_tree_and_never_moves_head(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job,
            [item('new', 'src/a.ts'), item('new', 'src/b.ts'), item('insert', 'app.txt')])
    call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1200'})
    main_before = _git(root, 'rev-parse', 'main').stdout.strip()

    call(runtime, store, sid, 'design_write', {'path': 'src/a.ts', 'content': A_BODY,
                                               'mode': 'create'})
    call(runtime, store, sid, 'design_write', {'path': 'src/b.ts', 'content': B_BODY,
                                               'mode': 'create'})
    call(runtime, store, sid, 'design_write', {'path': 'app.txt', 'content': 'DELTA\n',
                                               'mode': 'insert', 'position': 'append'})
    assert (root / 'app.txt').read_text(encoding='utf-8') == INITIAL + 'DELTA\n'

    # `design_diff` thấy cả ba tệp và trả một patch.
    diff = call(runtime, store, sid, 'design_diff', {'paths': ['src/a.ts', 'src/b.ts', 'app.txt']})
    touched = {row['path'] for row in diff['files']}
    assert {'src/a.ts', 'src/b.ts', 'app.txt'} <= touched
    assert diff['designId'] == job['design_id'] and diff['patchPath'].endswith('/diff.patch')
    assert '+++ ' in (root / diff['patchPath']).read_text(encoding='utf-8')

    async def revert_via_route():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                async with http.patch(
                        str(server.make_url(f'/api/agent/design/runs/{job["design_id"]}')),
                        json={'action': 'revert-batch'}) as resp:
                    assert resp.status == 200, await resp.text()
                    return await resp.json()

    result = asyncio.run(revert_via_route())
    assert {'src/a.ts', 'src/b.ts', 'app.txt'} <= set(result['result']['reverted']
                                                      + result['result'].get('deleted', []))

    # Byte-identical với `base`, `main` đứng yên; cây DỰ ÁN sạch — chỉ còn đồ của RUN (`.design/`)
    # và db của phiên, KHÔNG bị quét theo lô (§6.5: hoàn tác chỉ trong phạm vi lô đã ghim).
    assert (root / 'app.txt').read_text(encoding='utf-8') == INITIAL
    assert not (root / 'src/a.ts').exists() and not (root / 'src/b.ts').exists()
    assert _git(root, 'rev-parse', 'main').stdout.strip() == main_before
    assert not [line for line in porcelain(root) if 'src/' in line or 'app.txt' in line]
    assert (root / '.design').exists(), 'đồ của run không nằm trong lô nên không bị hoàn tác'


def test_batch_revert_leaves_a_file_outside_the_batch_alone(harness):
    """Lô chỉ gồm `src/a.ts`; sửa tay ở `src/manual.ts` và `second.txt` phải SỐNG SÓT (§6.5)."""
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job,
            [item('new', 'src/a.ts'), item('insert', 'second.txt')])
    call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1400'})

    call(runtime, store, sid, 'design_write', {'path': 'src/a.ts', 'content': A_BODY,
                                               'mode': 'create'})
    # Lô = diff SAU lần ghi đầu ⇒ `src/a.ts` là lô đã ghim.
    diff = call(runtime, store, sid, 'design_diff', {})
    assert 'src/a.ts' in {row['path'] for row in diff['files']}
    # Sửa tay NGOÀI lô (chủ nhà tự thêm tệp, và tự sửa một tệp khác của repo).
    (root / 'src').mkdir(exist_ok=True)
    (root / 'src/manual.ts').write_text('export const manual = true;\n', encoding='utf-8')
    (root / 'second.txt').write_text('one\nTWO\n', encoding='utf-8')

    result = call(runtime, store, sid, 'design_revert', {'mode': 'batch'})
    assert result['reverted'] == ['src/a.ts']
    assert not (root / 'src/a.ts').exists(), 'tệp TRONG lô được hoàn tác'
    assert (root / 'src/manual.ts').read_text(encoding='utf-8') == 'export const manual = true;\n'
    assert (root / 'second.txt').read_text(encoding='utf-8') == 'one\nTWO\n'


def test_single_file_revert_leaves_other_files_alone(harness):
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'src/a.ts'), item('new', 'src/b.ts')])
    call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1300'})
    main_before = _git(root, 'rev-parse', 'main').stdout.strip()

    call(runtime, store, sid, 'design_write', {'path': 'src/a.ts', 'content': A_BODY,
                                               'mode': 'create'})
    call(runtime, store, sid, 'design_write', {'path': 'src/b.ts', 'content': B_BODY,
                                               'mode': 'create'})

    result = call(runtime, store, sid, 'design_revert', {'paths': ['src/a.ts'], 'mode': 'file'})
    assert result['reverted'] == ['src/a.ts']
    assert not (root / 'src/a.ts').exists()
    assert (root / 'src/b.ts').read_text(encoding='utf-8') == B_BODY
    assert _git(root, 'rev-parse', 'main').stdout.strip() == main_before


@pytest.mark.parametrize('path', ['.design/../src/outside.ts', '.design/../package.json',
                                  '.design/../.git/config', '..', '/etc/passwd'])
def test_file_revert_refuses_dotdot_and_absolute_paths(harness, path):
    """Hoàn tác MỘT tệp cũng phải chuẩn hoá đường dẫn như đường ghi (§6.5)."""
    store, runtime, sid, root = harness
    job = open_run(runtime, store, sid)
    approve(runtime, store, sid, job, [item('new', 'src/a.ts')])
    call(runtime, store, sid, 'design_branch_create', {'name': 'design/ui-20260927-1500'})
    call(runtime, store, sid, 'design_write', {'path': 'src/a.ts', 'content': A_BODY,
                                               'mode': 'create'})
    git_config = (root / '.git' / 'config').read_bytes()

    with pytest.raises(ValueError, match=limits.DESIGN_PATH_NOT_APPROVED_CODE):
        call(runtime, store, sid, 'design_revert', {'paths': [path], 'mode': 'file'})
    assert (root / 'src/a.ts').read_text(encoding='utf-8') == A_BODY, 'không hoàn tác gì'
    assert (root / '.git' / 'config').read_bytes() == git_config
