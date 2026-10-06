"""PART 2 (task 4): nguồn tìm kiếm người dùng chọn đứng ĐẦU chuỗi `web_search`.

Router được thay bằng `search_credentials.active_source` giả (khuôn `test_web_search_multi.py`):
không ca nào gọi mạng. Hợp đồng phải giữ nguyên — không lựa chọn, không khoá ENV thì chuỗi **đúng
bằng** `GENERAL_PROVIDERS`, nên `test_searxng_is_the_first_general_provider` vẫn xanh.
"""
import json

import pytest

from agentbox.agent_core import web as web_module
from agentbox.agent_core.search_credentials import SearchSource
from agentbox.agent_core.web import WebError, WebTools

PUBLIC_IP = '93.184.216.34'
ENV_KEYS = ('BRAVE_API_KEY', 'BOXFOX_BRAVE_API_KEY', 'TAVILY_API_KEY', 'EXA_API_KEY',
            'PARALLEL_API_KEY', 'FIRECRAWL_API_KEY', 'BOXFOX_SEARXNG_URL')


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    monkeypatch.setattr(web_module.socket, 'getaddrinfo',
                        lambda host, port, **kwargs: [(2, 1, 6, '', (PUBLIC_IP, 0))])


@pytest.fixture(autouse=True)
def no_keys(monkeypatch):
    for name in ENV_KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(web_module.search_credentials.ROUTER_SEARCH_URL_ENV, raising=False)
    monkeypatch.delenv(web_module.search_credentials.REFRESH_ENV, raising=False)
    monkeypatch.delenv(web_module.WEB_TEST_ALLOW_LOOPBACK_ENV, raising=False)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    waits: list[float] = []
    monkeypatch.setattr(web_module.time, 'sleep', lambda seconds: waits.append(seconds))
    return waits


@pytest.fixture
def selection(monkeypatch):
    """Nguồn "đang chọn" không cần router: thay `active_source` của mô-đun credentials."""
    state: dict = {'source': None}

    def active_source(*, force=False):
        return state['source']

    monkeypatch.setattr(web_module.search_credentials, 'active_source', active_source)
    return state


@pytest.fixture
def tools(tmp_path, monkeypatch):
    import agentbox.observability.system_log as system_log_module
    monkeypatch.setattr(system_log_module.system_log, 'directory', tmp_path)
    monkeypatch.setattr(system_log_module.system_log, 'path', tmp_path / 'harness.jsonl')
    return WebTools()


def _select(selection, provider_id, **fields) -> None:
    selection['source'] = SearchSource(provider_id=provider_id, revision=fields.pop('revision', 7),
                                       api_key=fields.pop('api_key', None),
                                       account_id=fields.pop('account_id', None),
                                       endpoint=fields.pop('endpoint', None)) if provider_id else None


def _row(url: str, title: str = 'Tiêu đề', snippet: str = 'đoạn mô tả') -> dict:
    return {'title': title, 'url': url, 'snippet': snippet, 'provider': 'fake'}


def _names(chain) -> list[str]:
    return [str(fn.__name__).removeprefix('_provider_') for fn in chain]


# ------------------------------------------------------------------- thứ tự chuỗi

def test_no_selection_and_no_env_keeps_the_historical_provider_order(selection):
    _select(selection, None)
    assert web_module._search_chain() == web_module.GENERAL_PROVIDERS
    assert web_module.GENERAL_PROVIDERS[0] is web_module._provider_searxng, 'hợp đồng cũ không đổi'


def test_the_selected_source_runs_before_searxng_and_firecrawl(selection):
    _select(selection, 'brave', api_key='brave-key')
    assert _names(web_module._search_chain()) == ['brave', 'searxng', 'firecrawl', 'tavily',
                                                  'exa', 'parallel']
    _select(selection, 'tavily', api_key='tavily-key')
    assert _names(web_module._search_chain())[0] == 'tavily'


def test_an_env_key_outranks_the_builtin_searxng_leg(selection, monkeypatch):
    _select(selection, None)
    monkeypatch.setenv('BRAVE_API_KEY', 'env-brave')
    assert _names(web_module._search_chain())[0] == 'brave'
    monkeypatch.delenv('BRAVE_API_KEY')
    monkeypatch.setenv('FIRECRAWL_API_KEY', 'env-firecrawl')
    chain = _names(web_module._search_chain())
    assert chain[0] == 'firecrawl' and chain.index('searxng') > 0, 'khoá ENV kéo chân lên TRƯỚC SearXNG'


def test_a_selected_provider_without_a_key_falls_back_to_the_builtin_path(tools, selection, monkeypatch):
    _select(selection, 'brave')                     # chọn brave nhưng KHÔNG có khoá
    seen: list[str] = []

    def searxng(query, count, options=None):
        seen.append(query)
        return [_row('https://example.com/searxng')]

    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (searxng,))
    result = tools.search({'query': 'x'})
    assert _names(web_module._search_chain()) == ['brave', 'searxng'], 'chân brave vẫn đứng đầu'
    assert seen == ['x'] and result['count'] == 1
    assert result['results'][0]['url'] == 'https://example.com/searxng'


# ------------------------------------------------------------------- hai chân mới

def test_the_selected_cloudflare_leg_is_first_and_maps_the_items_array(tools, selection, monkeypatch):
    _select(selection, 'cloudflare', api_key='cf-key', account_id='acct-1')
    calls: list[dict] = []

    def fake(url, **kwargs):
        calls.append({'url': url, 'headers': kwargs.get('headers'), 'body': json.loads(kwargs['body'])})
        return 200, 'application/json', json.dumps({'items': [
            {'title': 'Kết quả CF', 'url': 'https://example.com/cf', 'description': 'mô tả CF'}]}), url

    monkeypatch.setattr(web_module, 'http_request', fake)
    assert web_module._search_chain()[0] is web_module._provider_cloudflare
    result = tools.search({'query': 'tin tức', 'count': 3})
    assert calls[0]['url'] == 'https://api.cloudflare.com/client/v4/accounts/acct-1/ai/websearch/'
    assert calls[0]['headers']['Authorization'] == 'Bearer cf-key'
    assert calls[0]['body']['provider'] == 'ceramic' and calls[0]['body']['limit'] == 3
    assert result['results'][0] == {'title': 'Kết quả CF', 'url': 'https://example.com/cf',
                                    'snippet': 'mô tả CF', 'provider': 'cloudflare'}


def test_the_selected_custom_leg_posts_the_query_and_normalises_results(tools, selection, monkeypatch):
    _select(selection, 'custom', api_key='custom-key', endpoint='https://search.example.com/api')
    calls: list[dict] = []

    def fake(url, **kwargs):
        calls.append({'url': url, 'headers': kwargs.get('headers'), 'body': json.loads(kwargs['body'])})
        return 200, 'application/json', json.dumps({'results': [
            {'title': 'Kết quả riêng', 'url': 'https://example.com/rieng', 'snippet': 'mô tả riêng'}]}), url

    monkeypatch.setattr(web_module, 'http_request', fake)
    assert web_module._search_chain()[0] is web_module._provider_custom
    result = tools.search({'query': 'hồ sơ', 'count': 2})
    assert calls[0]['url'] == 'https://search.example.com/api'
    assert calls[0]['body'] == {'query': 'hồ sơ', 'count': 2}
    assert calls[0]['headers']['Authorization'] == 'Bearer custom-key'
    assert result['results'][0]['url'] == 'https://example.com/rieng'


def test_the_custom_leg_accepts_the_items_shape_and_survives_a_missing_key(selection, monkeypatch):
    _select(selection, 'custom', endpoint='https://search.example.com/api')
    monkeypatch.setattr(web_module, 'http_request', lambda url, **kwargs: (
        200, 'application/json', json.dumps({'items': [{'url': 'https://example.com/i'}]}), url))
    rows = web_module._provider_custom('x', 1)
    assert rows[0]['url'] == 'https://example.com/i'
    _select(selection, 'custom')                    # không endpoint ⇒ nói rõ, không gọi mạng
    with pytest.raises(WebError) as caught:
        web_module._provider_custom('x', 1)
    assert caught.value.code == 'WEB_SEARCH_UNAVAILABLE' and 'endpoint' in str(caught.value)


def test_a_custom_endpoint_still_has_to_be_public(selection):
    _select(selection, 'custom', endpoint='http://127.0.0.1:9/search')
    with pytest.raises(WebError) as caught:
        web_module._provider_custom('x', 1)
    assert caught.value.code == 'WEB_URL_FORBIDDEN', 'lựa chọn không được mở cổng SSRF'


def test_the_cloudflare_leg_names_the_missing_field(selection):
    _select(selection, 'cloudflare', api_key='cf-key')
    with pytest.raises(WebError) as caught:
        web_module._provider_cloudflare('x', 1)
    assert 'accountId' in str(caught.value)


# --------------------------------------------------------------- rơi tiếp, cache, cổng

def test_a_broken_selected_key_falls_through_to_the_builtin_path_and_says_so(tools, selection, monkeypatch):
    _select(selection, 'brave', api_key='broken-key')
    good = _row('https://example.com/searxng')

    def fake(url, **kwargs):
        if 'brave' in url:
            raise WebError('WEB_FETCH_FAILED', f'{url} answered HTTP 401: unauthorized')
        return 200, 'application/json', json.dumps({'results': []}), url

    monkeypatch.setattr(web_module, 'http_request', fake)
    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (lambda query, count, options=None: [good],))
    assert tools.search({'query': 'x'})['count'] == 1, 'nguồn chọn hỏng KHÔNG được làm mất kết quả'

    def broken(query, count, options=None):
        raise WebError('WEB_SEARCH_UNAVAILABLE', 'the keyless search provider refused the query (HTTP 500)')

    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (broken,))
    with pytest.raises(WebError) as caught:
        tools.search({'query': 'x khác'})
    message = str(caught.value)
    assert "the selected source 'brave' failed first" in message
    assert 'Settings → Provider → Web Search' in message
    assert caught.value.details['searchFailure']['selected'] == 'brave'


def test_switching_the_source_changes_the_search_cache_key(tools, selection, monkeypatch):
    calls: list[str] = []

    def stub(query, count, options=None):
        calls.append(query)
        return [_row('https://example.com/a')]

    monkeypatch.setattr(web_module, '_search_chain', lambda: (stub,))
    _select(selection, 'brave', api_key='brave-key', revision=5)
    tools.search({'query': 'x'})
    tools.search({'query': 'x'})
    assert calls == ['x'], 'cùng nguồn ⇒ lượt hai đọc từ cache'
    _select(selection, 'tavily', api_key='tavily-key', revision=6)
    tools.search({'query': 'x'})
    assert calls == ['x', 'x'], 'đổi nguồn ⇒ khoá cache đổi ⇒ KHÔNG dùng lại kết quả nguồn cũ'


def test_the_loopback_test_hook_is_off_by_default(tools, monkeypatch):
    with pytest.raises(WebError) as caught:
        web_module.assert_public_url('http://127.0.0.1:9/')
    assert caught.value.code == 'WEB_URL_FORBIDDEN', 'mặc định vẫn chặn loopback'
    monkeypatch.setenv(web_module.WEB_TEST_ALLOW_LOOPBACK_ENV, '1')
    assert web_module.assert_public_url('http://127.0.0.1:9/')
    assert web_module.assert_public_url('http://localhost:9/')
    with pytest.raises(WebError):
        web_module.assert_public_url('http://169.254.169.254/latest/meta-data/')   # metadata vẫn chặn


def test_the_searxng_leg_uses_the_url_from_settings_when_present(selection, monkeypatch):
    _select(selection, 'searxng', endpoint='http://127.0.0.1:9999')
    seen: list[dict] = []
    monkeypatch.setattr(web_module.search_pipeline, 'pick_engines', lambda *a, **k: ['google'])
    monkeypatch.setattr(web_module.search_pipeline, 'record_response_health', lambda *a, **k: None)
    monkeypatch.setattr(web_module.search_pipeline, 'searxng_url', lambda: '')

    def searxng_search(query, **kwargs):
        seen.append(kwargs)
        return {'results': [{'title': 'T', 'url': 'https://example.com/s', 'snippet': 'm', 'engine': 'google'}]}

    monkeypatch.setattr(web_module.search_pipeline, 'searxng_search', searxng_search)
    rows = web_module._provider_searxng('x', 1)
    assert seen[0]['base_url'] == 'http://127.0.0.1:9999', 'URL lấy từ Settings, không phải env/tự dò'
    assert rows[0]['url'] == 'https://example.com/s' and rows[0]['engines'] == ['google']
