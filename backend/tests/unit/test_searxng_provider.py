"""Nối dây `web.py` ↔ ống tìm (P0b §5) và chân SearXNG; KHÔNG gọi mạng.

Điểm then chốt: khi `BOXFOX_SEARCH_PIPELINE` TẮT và không có gói nguồn, đường cũ phải chạy y như
trước (không khoá `pipeline`/`pack` trong payload); khi bật, ống/gói đứng trước và không gọi mạng.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agentbox.agent_core import search_pipeline as sp
from agentbox.agent_core import web as web_module
from agentbox.agent_core.web import WebError, WebTools

PUBLIC_IP = '93.184.216.34'


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(web_module.socket, 'getaddrinfo',
                        lambda host, port, **kwargs: [(2, 1, 6, '', (PUBLIC_IP, 0))])
    monkeypatch.setenv('BOXFOX_SEARCH_DB', str(tmp_path / 'search.sqlite'))
    monkeypatch.delenv('BOXFOX_SEARCH_PIPELINE', raising=False)
    monkeypatch.delenv('BOXFOX_SEARXNG_URL', raising=False)
    monkeypatch.delenv('BOXFOX_WEB_PACK', raising=False)
    sp.reset_store()
    yield
    sp.reset_store()


@pytest.fixture
def tools(tmp_path, monkeypatch):
    import agentbox.observability.system_log as system_log_module
    monkeypatch.setattr(system_log_module.system_log, 'directory', tmp_path)
    monkeypatch.setattr(system_log_module.system_log, 'path', tmp_path / 'harness.jsonl')
    return WebTools()


def _row(url='https://example.com/a', title='Tiêu đề', snippet='đoạn mô tả'):
    return {'title': title, 'url': url, 'snippet': snippet, 'provider': 'fake'}


def _fake_pack(root, *, with_index=True):
    (root / 'pages').mkdir(parents=True, exist_ok=True)
    (root / 'pack.json').write_text(json.dumps({'scenarioId': 's', 'sources': [
        {'url': 'https://a.example/rag', 'title': 'RAG', 'date': '2026-03-01',
         'accessLevel': 'fulltext-read', 'file': 'rag.html'}]}), encoding='utf-8')
    (root / 'pages' / 'rag.html').write_text(
        '<html><head><title>RAG</title></head><body><p>Retrieval augmented generation.</p></body></html>',
        encoding='utf-8')
    if with_index:
        (root / 'search_index.jsonl').write_text(json.dumps({
            'query': 'retrieval augmented generation',
            'urls': [{'url': 'https://a.example/rag', 'rank': 1, 'snippet': 'RAG'}]}) + '\n',
            encoding='utf-8')
    return root


# ------------------------------------------------------------------ chân SearXNG

def test_searxng_is_the_first_general_provider():
    assert web_module.GENERAL_PROVIDERS[0] is web_module._provider_searxng
    assert web_module.SOURCE_PROVIDERS['papers'][0] is web_module._provider_papers_first


def test_the_searxng_leg_names_the_missing_variable():
    with pytest.raises(WebError) as caught:
        web_module._provider_searxng('q', 5)
    assert caught.value.code == 'WEB_SEARCH_UNAVAILABLE'
    assert 'BOXFOX_SEARXNG_URL' in str(caught.value)


def test_the_searxng_leg_maps_rows_and_keeps_the_engine(monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARXNG_URL', 'http://127.0.0.1:8888')
    monkeypatch.setattr(sp, 'searxng_search', lambda query, **kwargs: {
        'results': [{'url': 'https://x.example/1', 'title': 'X', 'snippet': 's', 'engine': 'brave'}],
        'engines': ['brave'], 'unresponsive': [], 'error': None, 'latencyMs': 5})
    rows = web_module._provider_searxng('q', 5)
    assert rows[0]['provider'] == 'searxng' and rows[0]['engines'] == ['brave']


def test_the_searxng_leg_raises_when_the_instance_refuses(monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARXNG_URL', 'http://127.0.0.1:8888')
    monkeypatch.setattr(sp, 'searxng_search', lambda query, **kwargs: {
        'results': [], 'engines': [], 'unresponsive': [], 'error': 'connection refused',
        'latencyMs': 1})
    with pytest.raises(WebError) as caught:
        web_module._provider_searxng('q', 5)
    assert caught.value.code == 'WEB_SEARCH_UNAVAILABLE'


# ------------------------------------------------------------------ search: ba nhánh

def test_search_keeps_the_old_path_when_everything_is_off(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (lambda query, count, options=None: [_row()],))
    payload = tools.search({'query': 'đường cũ'})
    assert payload['results'][0]['url'] == 'https://example.com/a'
    assert 'pipeline' not in payload and 'pack' not in payload, 'đường cũ không được thêm khoá mới'


def test_search_uses_the_pipeline_when_enabled(tools, monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARCH_PIPELINE', 'on')
    calls = {}

    def fake_run(queries, **kwargs):
        calls['queries'] = queries
        return {'query': queries[0], 'queries': queries, 'source': kwargs['source'],
                'results': [_row()], 'count': 1, 'pipeline': {'pack': False, 'steps': {}}}

    monkeypatch.setattr(sp, 'run_pipeline', fake_run)
    payload = tools.search({'query': 'qua ống'})
    assert calls['queries'] == ['qua ống']
    assert payload['pipeline']['pack'] is False


def test_search_serves_the_pack_without_touching_the_network(tools, monkeypatch, tmp_path):
    _fake_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS',
                        (lambda query, count, options=None: pytest.fail('không được gọi mạng'),))
    payload = tools.search({'query': 'retrieval augmented generation'})
    assert payload['pack'] is True and payload['results'][0]['url'] == 'https://a.example/rag'


def test_search_reports_an_empty_pack_answer_truthfully(tools, monkeypatch, tmp_path):
    _fake_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS',
                        (lambda query, count, options=None: pytest.fail('không được gọi mạng'),))
    payload = tools.search({'query': 'chủ đề không có trong gói'})
    assert payload['pack'] is True and payload['results'] == []


def test_search_falls_through_when_the_pack_has_no_index(tools, monkeypatch, tmp_path):
    _fake_pack(tmp_path, with_index=False)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (lambda query, count, options=None: [_row()],))
    payload = tools.search({'query': 'gói không có chỉ mục'})
    assert payload['results'][0]['url'] == 'https://example.com/a'
    assert 'pack' not in payload
    # Lời gọi này ĐÃ chạm mạng dù đang bật gói: payload phải nói rõ, không im lặng (§1/§8.3).
    assert 'search_index.jsonl' in payload['packWarning']


# ------------------------------------------------------------------ fetch trong chế độ gói

def test_fetch_reads_a_page_of_the_pack(tools, monkeypatch, tmp_path):
    _fake_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    payload = tools.fetch({'url': 'https://a.example/rag'})
    assert payload['pack'] is True and payload['readerReason'] == 'source-pack'
    assert payload['contentType'] == 'text/html' and 'Retrieval augmented generation' in payload['text']


def test_fetch_outside_the_pack_fails_loudly(tools, monkeypatch, tmp_path):
    _fake_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    with pytest.raises(WebError) as caught:
        tools.fetch({'url': 'https://missing.example/x'})
    assert caught.value.code == 'WEB_FETCH_FAILED'


# ------------------------------------------------------------------ nhóm papers

def test_papers_leg_delegates_to_the_old_chain_when_the_pipeline_is_off(monkeypatch):
    sentinel = [_row('https://openalex.example/1')]
    monkeypatch.setattr(web_module, '_provider_papers',
                        lambda query, count, options=None: sentinel)
    assert web_module._provider_papers_first('q', 5) is sentinel


def test_papers_leg_prefers_the_academic_group_when_enabled(monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARCH_PIPELINE', 'on')
    rows = [_row('https://s2.example/1')]
    monkeypatch.setattr(web_module, '_academic_module', lambda: SimpleNamespace(
        papers_search=lambda queries, count=5, options=None: rows))
    assert web_module._provider_papers_first('q', 5) == rows


def test_papers_leg_reports_an_empty_academic_group(monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARCH_PIPELINE', 'on')
    monkeypatch.setattr(web_module, '_academic_module', lambda: SimpleNamespace(
        papers_search=lambda queries, count=5, options=None: []))
    with pytest.raises(WebError):
        web_module._provider_papers_first('q', 5)


# ------------------------------------------------------------------ săn trích dẫn

def test_paper_citations_uses_the_academic_chase_when_enabled(tools, monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARCH_PIPELINE', 'on')
    seen = {}

    def fake_chase(identifier, *, direction, limit, options):
        seen.update(identifier=identifier, direction=direction, limit=limit)
        return [{'title': 'Được trích dẫn', 'url': 'https://s2.example/1'}]

    monkeypatch.setattr(web_module, '_academic_module', lambda: SimpleNamespace(citation_chase=fake_chase))
    payload = tools.paper_citations({'doi': '10.1000/x', 'direction': 'forward', 'limit': 5})
    assert seen['identifier'] == '10.1000/x' and seen['limit'] == 5
    assert payload['source'] == 'academic' and payload['count'] == 1


def test_paper_citations_keeps_openalex_when_the_pipeline_is_off(tools, monkeypatch):
    monkeypatch.setenv('BOXFOX_WEB_PACK', '')  # chỉ để chắc chắn không bật gói
    monkeypatch.setattr(web_module, '_openalex_json', lambda params, ident=None: {
        'results': [{'id': 'https://openalex.org/W2', 'display_name': 'Bài hai'}],
        'meta': {'count': 1}})
    payload = tools.paper_citations({'workId': 'W123', 'direction': 'forward', 'limit': 5})
    assert payload['source'] == 'openalex' and payload['count'] == 1
