"""Desktop and web must send metadata and chat to their own router."""
import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import TestServer

from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore


def test_web_default_without_router_override(monkeypatch):
    monkeypatch.delenv('BOXFOX_ROUTER_URL', raising=False)
    assert RouterClient().url == 'http://127.0.0.1:3101'


def test_desktop_endpoint_from_environment(monkeypatch):
    monkeypatch.setenv('BOXFOX_ROUTER_URL', '  http://127.0.0.1:64558/  ')
    assert RouterClient().url == 'http://127.0.0.1:64558'


def test_explicit_endpoint_takes_precedence(monkeypatch):
    monkeypatch.setenv('BOXFOX_ROUTER_URL', 'http://127.0.0.1:64558')
    assert RouterClient('http://127.0.0.1:40001/').url == 'http://127.0.0.1:40001'


def test_empty_environment_preserves_web_default(monkeypatch):
    monkeypatch.setenv('BOXFOX_ROUTER_URL', '   ')
    assert RouterClient().url == 'http://127.0.0.1:3101'


def test_default_runtime_routes_metadata_and_stream_to_bound_router(monkeypatch, tmp_path):
    async def run():
        received = []

        def router(label):
            app = web.Application()

            async def state(request):
                assert request.headers['x-boxfox-admin'] == '1'
                received.append((label, 'state'))
                return web.json_response({'connections': [{'id': label, 'models': [
                    {'id': 'fixture', 'contextWindow': 64000}]}]})

            async def chat(request):
                assert request.headers['x-boxfox-admin'] == '1'
                body = await request.json()
                assert body['stream'] is True
                assert body['connectionId'] == label
                received.append((label, 'chat'))
                chunk = {'choices': [{'index': 0, 'delta': {'content': label},
                                      'finish_reason': 'stop'}]}
                return web.Response(text='data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n',
                                    content_type='text/event-stream')

            app.router.add_get('/api/router/state', state)
            app.router.add_post('/api/router/chat', chat)
            return app

        async with TestServer(router('desktop')) as desktop, TestServer(router('web')) as browser:
            desktop_url = str(desktop.make_url('')).rstrip('/')
            web_url = str(browser.make_url('')).rstrip('/')
            assert desktop.port != 3101 and browser.port != 3101
            store = SessionStore(tmp_path / 'sessions.db')
            try:
                monkeypatch.setenv('BOXFOX_ROUTER_URL', desktop_url)
                # Match server.main: no explicit client is injected into HarnessRuntime.
                runtime = HarnessRuntime(store, object())
                assert runtime.client.url == desktop_url
                assert (await runtime.client.model_metadata('desktop', 'fixture'))['contextWindow'] == 64000
                result = await runtime.client.complete([{'role': 'user', 'content': 'hello'}], [],
                                                       {'connectionId': 'desktop', 'modelId': 'fixture'})
                assert result['choices'][0]['message']['content'] == 'desktop'
                assert result['choices'][0]['finish_reason'] == 'stop'

                # A separate web client must not change the existing desktop binding.
                monkeypatch.setenv('BOXFOX_ROUTER_URL', web_url)
                client = RouterClient()
                assert (await client.model_metadata('web', 'fixture'))['contextWindow'] == 64000
                result = await client.complete([{'role': 'user', 'content': 'hello'}], [],
                                               {'connectionId': 'web', 'modelId': 'fixture'})
                assert result['choices'][0]['message']['content'] == 'web'
                assert runtime.client.url == desktop_url
                assert received == [('desktop', 'state'), ('desktop', 'chat'),
                                    ('web', 'state'), ('web', 'chat')]
            finally:
                store.close()

    asyncio.run(run())
