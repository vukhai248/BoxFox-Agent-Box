"""C4 — khối `search` của `/api/agent/health` và `runtime-info`: rẻ, thật, và không làm chết route.

Ba luật được khoá ở đây: (1) health thường KHÔNG gọi mạng (đo bằng bộ đếm trên `probe_searxng`);
(2) `?probe=search` gọi dò ĐÚNG một lần và xoá cache trước để phán quyết là của lần này;
(3) một trạng thái hỏng trả `{'error', 'reason'}` chứ không kéo route xuống 500.
"""
from __future__ import annotations

import asyncio

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import search_pipeline, web
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'ok': True}

    async def cleanup(self, sid):
        return None


def run(tmp_path, coro_factory):
    """Route THẬT qua aiohttp, DB tìm kiếm trỏ vào tmp (không đọc DB thật của máy chạy)."""
    async def main():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), None)
        runtime.create({'skills': []})
        search_pipeline.reset_store()
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                results = await coro_factory(client, runtime)
        store.close()
        search_pipeline.reset_store()
        return results

    return asyncio.run(main())


def test_the_health_route_reports_the_search_block_without_touching_the_network(tmp_path, monkeypatch):
    calls: list[str] = []

    def counting_probe(url, *, timeout=None):
        calls.append(str(url))
        return False

    monkeypatch.setattr(search_pipeline, 'probe_searxng', counting_probe)
    monkeypatch.setenv('BOXFOX_SEARCH_DB', str(tmp_path / 'never-created.sqlite'))
    # BẬT tự dò cho bài này: fixture chung pin `AUTODETECT=off`, mà khi tắt thì cả đường dò lẫn
    # health đều không thể gọi `probe_searxng` — `calls == []` sẽ đúng một cách vô nghĩa.
    monkeypatch.setenv(search_pipeline.SEARXNG_AUTODETECT_ENV, 'on')
    search_pipeline.reset_autodetect()

    async def scenario(client, runtime):
        response = await client.get('/api/agent/health', headers=HEADERS)
        return response.status, await response.json()

    status, body = run(tmp_path, scenario)
    assert status == 200
    block = body['search']
    assert set(block) >= {'searxng', 'pipeline', 'engines', 'keys', 'selected', 'source', 'fallback'}
    assert set(block['searxng']) == {'url', 'origin', 'reachable', 'checkedAt'}
    assert block['pipeline']['mode'] in ('off', 'on', 'auto')
    assert block['engines'] == []
    assert calls == [], 'health thường phải rẻ: không được dò SearXNG'
    assert not (tmp_path / 'never-created.sqlite').exists(), 'health không được tạo DB tìm kiếm'


def test_desktop_readiness_never_waits_for_search_diagnostics(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError('readiness tried to resolve search/provider diagnostics')
    monkeypatch.setattr(web, 'search_status', forbidden)
    async def scenario(client, runtime):
        response = await client.get('/api/agent/health?readiness=1', headers=HEADERS)
        return response.status, await response.json()
    status, body = run(tmp_path, scenario)
    assert status == 200 and body['status'] == 'ok'
    assert 'search' not in body and body['service'] == 'boxfox-harness'


def test_the_search_probe_only_runs_when_asked(tmp_path, monkeypatch):
    calls: list[str] = []

    def counting_probe(url, *, timeout=None):
        calls.append(str(url))
        return False

    monkeypatch.setattr(search_pipeline, 'probe_searxng', counting_probe)

    async def scenario(client, runtime):
        plain = await client.get('/api/agent/health', headers=HEADERS)
        plain_body = await plain.json()
        probed = await client.get('/api/agent/health?probe=search', headers=HEADERS)
        probed_body = await probed.json()
        return plain_body, probed_body

    plain_body, probed_body = run(tmp_path, scenario)
    assert calls == [search_pipeline.autodetect_url()], 'dò đúng MỘT lần, đúng đích tự dò'
    # Lần dò vừa rồi trả `False` ⇒ cache âm: health thường vẫn không dò lại, và nói thật là "không tới được".
    assert plain_body['search']['searxng']['reachable'] is None
    assert probed_body['search']['searxng']['reachable'] is False
    assert probed_body['search']['searxng']['origin'] == ''
    assert probed_body['search']['searxng']['checkedAt']


def test_a_probe_that_finds_searxng_reports_it_as_reachable(tmp_path, monkeypatch):
    monkeypatch.setattr(search_pipeline, 'probe_searxng', lambda url, *, timeout=None: True)

    async def scenario(client, runtime):
        await client.get('/api/agent/health?probe=search', headers=HEADERS)
        return await (await client.get('/api/agent/health', headers=HEADERS)).json()

    body = run(tmp_path, scenario)
    block = body['search']
    assert block['searxng']['reachable'] is True
    assert block['searxng']['origin'] == 'autodetect'
    assert block['searxng']['url'] == search_pipeline.autodetect_url()
    # `auto` + có SearXNG + không cấu hình tường minh ⇒ ống 10 bước chính là đường chạy.
    assert block['pipeline']['applies'] is True
    assert block['source'] == 'searxng'


def test_a_broken_status_never_takes_the_health_route_down(tmp_path, monkeypatch):
    def broken():
        raise RuntimeError('bảng sức khoẻ hỏng')

    monkeypatch.setattr(web, 'search_status', broken)

    async def scenario(client, runtime):
        response = await client.get('/api/agent/health', headers=HEADERS)
        return response.status, await response.json()

    status, body = run(tmp_path, scenario)
    assert status == 200
    assert body['status'] == 'ok'
    assert body['search'] == {'error': 'RuntimeError', 'reason': 'bảng sức khoẻ hỏng'}


def test_the_runtime_info_block_lists_the_search_knobs(tmp_path):
    async def scenario(client, runtime):
        response = await client.get('/api/agent/runtime-info', headers=HEADERS)
        return response.status, await response.json()

    status, body = run(tmp_path, scenario)
    assert status == 200
    block = body['limits']['search']
    assert block['pipelineDefault'] == 'auto'
    assert block['pipelineModes'] == ['off', 'on', 'auto']
    assert block['pipelineMode'] in block['pipelineModes']
    assert block['autodetectEnv'] == 'BOXFOX_SEARXNG_AUTODETECT'
    assert block['autodetectUrl'] == 'http://127.0.0.1:8888'
    assert block['engineRotation'] == 4 and block['topK'] == 8
    assert block['cacheTtlSeconds'] == 300 and block['searxngTimeoutSeconds'] == 8.0
    # Khối `web` cũ vẫn nguyên chỗ (đây là THÊM, không phải thay).
    assert 'readerMode' in body['limits']['web']
