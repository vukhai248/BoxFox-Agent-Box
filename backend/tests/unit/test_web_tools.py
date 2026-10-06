"""`web_search` / `web_fetch`: công cụ web chạy ở tầng HOST cho vai research.

Vì sao chúng ở host: firewall của box để `iptables OUTPUT` là `DROP` (chỉ loopback và
các cổng dịch vụ đi được), nên `browser_use` trong box chỉ tới được trang trong box.
Mọi thứ đi ra Internet phải qua host, và chỉ phần văn bản đã cắt mới vào ngữ cảnh.

Các ca dưới đây không gọi mạng thật: `web.http_request` và `socket.getaddrinfo` đều
được thay bằng fixture.
"""
import asyncio
import json

import pytest

from agentbox.agent_core import web as web_module
from agentbox.agent_core.failures import classify_failure
from agentbox.agent_core.roles import allowed_tools
from agentbox.agent_core.tool_contracts import SCHEMAS, schemas_for
from agentbox.agent_core.web import UNTRUSTED_NOTE, WebError, WebTools, assert_public_url, html_to_text

PUBLIC_IP = '93.184.216.34'


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Mặc định mọi tên phân giải ra một địa chỉ công cộng; ca SSRF tự đổi fixture này."""
    monkeypatch.setattr(web_module.socket, 'getaddrinfo',
                        lambda host, port, **kwargs: [(2, 1, 6, '', (PUBLIC_IP, 0))])


@pytest.fixture
def tools(tmp_path, monkeypatch):
    # `system_log` là instance dùng chung, đọc thư mục lúc khởi tạo: trỏ nó vào tmp_path.
    import agentbox.observability.system_log as system_log_module
    monkeypatch.setattr(system_log_module.system_log, 'directory', tmp_path)
    monkeypatch.setattr(system_log_module.system_log, 'path', tmp_path / 'harness.jsonl')
    return WebTools()


# ------------------------------------------------------------------ thẩm quyền

def test_research_and_orchestrator_hold_the_web_tools():
    research = allowed_tools('research')
    assert {'web_search', 'web_fetch'} <= research
    assert {'web_search', 'web_fetch'} <= allowed_tools('orchestrator')
    for role in ('explore', 'plan', 'plan-review', 'review', 'simplify', 'build', 'debug', 'testing'):
        assert not ({'web_search', 'web_fetch'} & allowed_tools(role)), role


def test_schemas_are_advertised_with_the_required_arguments():
    names = {entry['function']['name'] for entry in SCHEMAS}
    assert {'web_search', 'web_fetch'} <= names
    exposed = {entry['function']['name']: entry for entry in schemas_for({'web_search', 'web_fetch'})}
    assert exposed['web_search']['function']['parameters']['required'] == ['query']
    assert exposed['web_fetch']['function']['parameters']['required'] == ['url']
    assert set(exposed['web_search']['function']['parameters']['properties']['source']['enum']) == {
        'web', 'wikipedia', 'stackoverflow', 'github', 'papers', 'openreview'}


def test_failures_keep_the_web_prefix():
    code, message = classify_failure(WebError('WEB_URL_FORBIDDEN', 'loopback is not public'))
    assert code == 'WEB_URL_FORBIDDEN'
    assert 'loopback is not public' in message


# ----------------------------------------------------------------------- SSRF

@pytest.mark.parametrize('url', [
    'http://127.0.0.1:3101/api/router/health',
    'http://localhost:8081/__box/capture',
    'http://169.254.169.254/latest/meta-data/',
    'file:///etc/passwd',
    'ftp://example.com/x',
    'http://[::1]:3102/api/agent/sessions',
    'http://metadata.google.internal/computeMetadata/v1/',
])
def test_private_and_broken_targets_are_refused(url):
    with pytest.raises(WebError) as caught:
        assert_public_url(url)
    assert caught.value.code in {'WEB_URL_INVALID', 'WEB_URL_FORBIDDEN'}


def test_a_public_name_that_resolves_private_is_refused(monkeypatch):
    """DNS rebinding: tên công cộng nhưng địa chỉ là mạng trong — vẫn phải chặn."""
    monkeypatch.setattr(web_module.socket, 'getaddrinfo',
                        lambda host, port, **kwargs: [(2, 1, 6, '', ('10.1.2.3', 0))])
    with pytest.raises(WebError) as caught:
        assert_public_url('https://router.example.com/api/router/models')
    assert caught.value.code == 'WEB_URL_FORBIDDEN'
    assert '10.1.2.3' in str(caught.value)


def test_a_public_url_passes():
    assert assert_public_url('https://vi.wikipedia.org/wiki/Trang_ch%E1%BB%A7').hostname == 'vi.wikipedia.org'


# ---------------------------------------------------------------- trích văn bản

def test_html_becomes_readable_text():
    title, text, links = html_to_text(
        '<html><head><title>  Bệnh án  </title><style>p{color:red}</style></head>'
        '<body><nav>menu</nav><h1>Tiêu đề</h1><p>Một  <b>đoạn</b> văn.</p>'
        '<script>alert(1)</script><a href="https://example.com/x">nguồn</a></body></html>')
    assert title == 'Bệnh án'
    assert '## Tiêu đề' in text
    assert 'Một đoạn văn.' in text
    assert 'menu' not in text and 'alert' not in text and 'color:red' not in text
    assert links == ['https://example.com/x nguồn']


def test_a_body_wrapped_in_a_form_is_still_read():
    """ĐO ĐƯỢC 2026-09-23: trang ASP.NET của `vanban.chinhphu.vn` bọc TOÀN BỘ thân bài trong
    `<form id="form1">`; khi `form` còn nằm trong danh sách bỏ thì một trang 81 KB trả về
    đúng 2 ký tự — bản đọc thật biến mất mà không có lỗi nào."""
    html = ('<html><body><form method="post" action="/?pageid=27160">'
            '<div>Điều 1. Phạm vi điều chỉnh của Luật Khám bệnh, chữa bệnh.</div>'
            '<input type="hidden" name="__VIEWSTATE" value="tSnAoQbT3Xtfc1cVvjyu" />'
            '</form></body></html>')
    _, text, _ = html_to_text(html)
    assert 'Phạm vi điều chỉnh' in text


def test_malformed_markup_still_yields_what_was_parsed():
    _, text, _ = html_to_text('<p>còn đọc được<div><span>')
    assert 'còn đọc được' in text


# --------------------------------------------------------------------- tìm kiếm

def _firecrawl_payload(count=2):
    return json.dumps({'success': True, 'data': [
        {'url': f'https://example.com/{index}', 'title': f'Kết quả {index}',
         'description': 'đoạn mô tả ' + 'x' * 600}
        for index in range(count)]})


def test_general_search_parses_the_keyless_provider(tools, monkeypatch):
    calls = []

    def fake(url, **kwargs):
        calls.append((url, kwargs))
        return 200, 'application/json', _firecrawl_payload(), url
    monkeypatch.setattr(web_module, 'http_request', fake)
    result = tools.search({'query': 'bệnh án điện tử', 'count': 2})
    assert result['count'] == 2 and result['source'] == 'web'
    assert result['results'][0]['url'] == 'https://example.com/0'
    assert len(result['results'][0]['snippet']) == web_module.MAX_SNIPPET
    assert result['untrusted'] is True and result['note'] == UNTRUSTED_NOTE
    assert calls[0][0] == 'https://api.firecrawl.dev/v1/search'
    assert calls[0][1]['method'] == 'POST'


def test_count_is_capped_and_defaulted(tools, monkeypatch):
    seen = {}

    def fake(url, *, method='GET', body=None, **kwargs):
        seen['limit'] = json.loads(body.decode())['limit']
        return 200, 'application/json', _firecrawl_payload(1), url
    monkeypatch.setattr(web_module, 'http_request', fake)
    tools.search({'query': 'x', 'count': 999})
    assert seen['limit'] == web_module.MAX_RESULTS
    tools.search({'query': 'x'})
    assert seen['limit'] == web_module.DEFAULT_RESULTS


def test_a_refused_provider_falls_through_to_the_next_one(tools, monkeypatch):
    def fake(url, **kwargs):
        if 'firecrawl' in url:
            raise WebError('WEB_SEARCH_UNAVAILABLE', 'refused')
        return 200, 'application/json', json.dumps({'web': {'results': [
            {'url': 'https://example.com/brave', 'title': 'Brave', 'description': 'ok'}]}}), url
    monkeypatch.setattr(web_module, 'http_request', fake)
    monkeypatch.setenv('BRAVE_API_KEY', 'unit-test-key')
    result = tools.search({'query': 'x'})
    assert result['results'][0]['provider'] == 'brave'


def test_every_provider_failing_is_one_clear_error(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (_ for _ in ()).throw(WebError('WEB_FETCH_FAILED', 'mạng đứt')))
    for key in ('FIRECRAWL_API_KEY', 'BRAVE_API_KEY', 'TAVILY_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(WebError) as caught:
        tools.search({'query': 'x'})
    assert caught.value.code == 'WEB_SEARCH_UNAVAILABLE'
    # F05: lỗi cấu hình phải nói thẳng là vấn đề cấu hình, KHÔNG xui đổi truy vấn/nguồn.
    assert 'not a query problem' in str(caught.value)
    assert 'Every provider was refused or empty' not in str(caught.value)
    assert caught.value.details['searchFailure']['kind'] == 'config'


def test_a_dead_leg_with_a_configured_backend_reports_infra(tools, monkeypatch):
    monkeypatch.setenv('BOXFOX_SEARXNG_URL', 'http://127.0.0.1:8888')
    monkeypatch.setattr(web_module.search_pipeline, 'searxng_search',
                        lambda *a, **kw: {'results': [], 'engines': ['bing'], 'unresponsive': [],
                                          'error': 'ConnectionRefusedError: refused', 'latencyMs': 3})
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (_ for _ in ()).throw(
                            WebError('WEB_FETCH_FAILED', 'mạng đứt')))
    for key in ('FIRECRAWL_API_KEY', 'BRAVE_API_KEY', 'TAVILY_API_KEY', 'EXA_API_KEY',
                'PARALLEL_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(WebError) as caught:
        tools.search({'query': 'x'})
    assert caught.value.details['searchFailure']['kind'] == 'infra'
    assert 'backend problem, not a query problem' in str(caught.value)
    assert 'do not retry the same search' in str(caught.value)


def test_wikipedia_search_uses_vietnamese_for_diacritics(tools, monkeypatch):
    seen = {}

    def fake(url, **kwargs):
        seen['url'] = url
        return 200, 'application/json', json.dumps({'query': {'search': [
            {'title': 'Bệnh án', 'snippet': 'hồ sơ <b>y tế</b>'}]}}), url
    monkeypatch.setattr(web_module, 'http_request', fake)
    result = tools.search({'query': 'bệnh án điện tử', 'source': 'wikipedia'})
    assert seen['url'].startswith('https://vi.wikipedia.org/w/api.php')
    assert result['results'][0]['url'].endswith('/wiki/B%E1%BB%87nh_%C3%A1n')
    assert result['results'][0]['snippet'] == 'hồ sơ y tế'


def test_stackoverflow_search_reports_the_answer_state(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request', lambda url, **kwargs: (
        200, 'application/json', json.dumps({'items': [
            {'title': 'q', 'link': 'https://stackoverflow.com/q/1', 'body_markdown': 'body',
             'is_answered': True, 'score': 7}]}), url))
    result = tools.search({'query': 'httpx timeout', 'source': 'stackoverflow'})
    assert result['results'][0]['answered'] is True and result['results'][0]['score'] == 7


def test_unknown_source_is_rejected(tools):
    with pytest.raises(WebError) as caught:
        tools.search({'query': 'x', 'source': 'bing'})
    assert caught.value.code == 'WEB_URL_INVALID'
    with pytest.raises(WebError):
        tools.search({'query': ''})


# ------------------------------------------------------------------- lấy trang

HTML_PAGE = ('<html><head><title>Tài liệu</title></head><body>' + '<p>Nội dung thật</p>' * 80 + '</body></html>')


def test_fetch_returns_bounded_text_and_the_untrusted_envelope(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (200, 'text/html', HTML_PAGE, url))
    result = tools.fetch({'url': 'https://example.com/doc', 'maxChars': 600})
    assert result['host'] == 'example.com' and result['status'] == 200
    assert result['title'] == 'Tài liệu'
    assert len(result['text']) == 600 and result['truncated'] is True
    assert result['text'].startswith('Nội dung thật') and 'Nội dung thật' in result['text']
    assert result['textChars'] > 600 and result['reader'] is None
    assert result['untrusted'] is True and result['note'] == UNTRUSTED_NOTE
    assert 'Nội dung thật' in result['text']


def test_json_is_passed_through_untouched(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (200, 'application/json', '{"a": 1, "b": "x y"}', url))
    result = tools.fetch({'url': 'https://example.com/data.json'})
    assert result['text'] == '{"a": 1, "b": "x y"}' and result['contentType'] == 'application/json'


def test_a_thin_page_is_read_through_the_reader(tools, monkeypatch):
    calls = []

    def fake(url, **kwargs):
        calls.append(url)
        if url.startswith('https://r.jina.ai/'):
            return 200, 'text/plain', 'Title: X\nMarkdown Content:\n' + 'văn bản đọc được ' * 40, url
        return 200, 'text/html', '<html><body><div id="app"></div></body></html>', url
    monkeypatch.setattr(web_module, 'http_request', fake)
    result = tools.fetch({'url': 'https://example.com/spa'})
    assert result['reader'] == 'r.jina.ai'
    assert 'văn bản đọc được' in result['text']
    assert calls == ['https://example.com/spa', 'https://r.jina.ai/https://example.com/spa']


def test_a_page_without_text_is_an_explicit_error(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (200, 'text/html', '<html><body></body></html>', url))
    with pytest.raises(WebError) as caught:
        tools.fetch({'url': 'https://example.com/empty'})
    assert caught.value.code == 'WEB_FETCH_EMPTY'


def test_an_http_error_is_reported_with_its_status(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (_ for _ in ()).throw(
                            WebError('WEB_FETCH_FAILED', 'https://example.com/x answered HTTP 404: Not Found')))
    with pytest.raises(WebError) as caught:
        tools.fetch({'url': 'https://example.com/x'})
    assert 'HTTP 404' in str(caught.value)


def test_max_chars_is_bounded(tools, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (200, 'text/plain', 'y' * 100000, url))
    huge = tools.fetch({'url': 'https://example.com/big', 'maxChars': 10 ** 9})
    assert huge['textChars'] == 100000 and len(huge['text']) == web_module.MAX_TEXT_HARD
    small = tools.fetch({'url': 'https://example.com/big', 'maxChars': 1})
    assert len(small['text']) == 500


# ------------------------------------------------------------------ ghi nhật ký

def test_the_dev_log_records_the_call_without_content(tools, tmp_path, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (200, 'application/json', _firecrawl_payload(1), url))
    asyncio.run(tools.run('web_search', {'query': 'bí mật nội bộ'}, 'sess-web'))
    lines = [json.loads(line) for line in (tmp_path / 'harness.jsonl').read_text().splitlines()]
    assert lines[-1]['event'] == 'web.search' and lines[-1]['sessionId'] == 'sess-web'
    assert lines[-1]['data']['resultCount'] == 1
    assert 'bí mật nội bộ' not in json.dumps(lines[-1]), 'nội dung truy vấn không được vào nhật ký'


def test_a_failed_call_never_writes_the_query_or_the_url(tools, tmp_path, monkeypatch):
    """Dòng `web.error` chỉ được mang số đếm và mã lỗi.

    Vòng soát mã đợt 10 tìm ra: nhánh lỗi ghi nguyên `str(exc)`, mà câu đó có cả truy vấn
    (`no result for '<truy vấn>'`) lẫn URL đầy đủ — nút "Copy diagnostics" của bảng nhật ký
    sẽ mang nội dung người dùng ra khỏi máy. Đo lại ở đây, cả hai đường.
    """
    for key in ('FIRECRAWL_API_KEY', 'BRAVE_API_KEY', 'TAVILY_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    secret = 'hồ sơ bệnh nhân Nguyễn Văn A'
    monkeypatch.setattr(web_module, 'http_request', lambda url, **kwargs: (_ for _ in ()).throw(
        WebError('WEB_FETCH_FAILED', f'{url} answered HTTP 500: boom')))
    with pytest.raises(WebError):
        asyncio.run(tools.run('web_search', {'query': secret}, 'sess-web'))
    monkeypatch.setattr(web_module, 'http_request', lambda url, **kwargs: (_ for _ in ()).throw(
        WebError('WEB_FETCH_FAILED', f'{url} answered HTTP 500: boom')))
    with pytest.raises(WebError):
        asyncio.run(tools.run('web_fetch', {'url': 'https://example.com/tim?q=so-benh-an-nguyen-van-a'},
                              'sess-web'))
    raw = (tmp_path / 'harness.jsonl').read_text()
    assert secret not in raw, 'nội dung truy vấn không được vào nhật ký'
    assert 'so-benh-an-nguyen-van-a' not in raw, 'URL (kèm tham số) không được vào nhật ký'
    lines = [json.loads(line) for line in raw.splitlines()]
    # A-7 thử lại một chân lỗi 500, nên có thêm dòng `web.retry` — cũng chỉ số đếm.
    assert [line['event'] for line in lines if line['event'] != 'web.retry'] == ['web.error', 'web.error']
    retries = [line for line in lines if line['event'] == 'web.retry']
    assert retries and all(set(line['data']) <= {'attempt', 'code'} for line in retries)
    errors = [line for line in lines if line['event'] == 'web.error']
    assert errors[0]['data']['queryChars'] == len(secret)
    assert errors[1]['data']['host'] == 'example.com'
    assert 'request failed' in errors[1]['message'] or 'HTTP 500' in errors[1]['message']


def test_the_provider_chain_survives_a_challenge_page(tools, monkeypatch):
    """Một nhà cung cấp trả 200 nhưng không phải JSON thì phải nhường lượt cho nhà kế tiếp.

    Đo sống 2026-09-20: front-end HTML trả trang "Just a moment…" với 200, và chuỗi dừng ngay
    ở đó (chỉ firecrawl được gọi) dù Brave đã có khoá.
    """
    calls = []

    def firecrawl(query, count, options=None):
        calls.append('firecrawl')
        json.loads('<html>Just a moment…</html>')  # giống hệt một trang chặn thật

    def brave(query, count, options=None):
        calls.append('brave')
        return [{'title': 'kết quả thật', 'url': 'https://example.com/ok', 'snippet': 'x', 'source': 'brave'}]

    monkeypatch.setenv('BRAVE_API_KEY', 'brave-key')
    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (firecrawl, brave))
    result = tools.search({'query': 'httpx timeout', 'count': 1})
    assert calls == ['firecrawl', 'brave'] and result['results'][0]['title'] == 'kết quả thật'


def test_a_failed_call_is_logged_as_a_warning(tools, tmp_path, monkeypatch):
    monkeypatch.setattr(web_module, 'http_request',
                        lambda url, **kwargs: (_ for _ in ()).throw(WebError('WEB_FETCH_FAILED', 'mạng đứt')))
    for key in ('FIRECRAWL_API_KEY', 'BRAVE_API_KEY', 'TAVILY_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(WebError):
        asyncio.run(tools.run('web_search', {'query': 'x'}, 'sess-web'))
    lines = [json.loads(line) for line in (tmp_path / 'harness.jsonl').read_text().splitlines()]
    assert lines[-1]['event'] == 'web.error' and lines[-1]['level'] == 'warn'
    assert lines[-1]['code'] == 'WEB_SEARCH_UNAVAILABLE'


def test_the_dispatcher_sends_web_tools_to_the_host_not_the_box():
    """`web_search` không bao giờ được rơi xuống `executor` của box."""
    from agentbox.agent_core.runtime import HarnessRuntime
    sent = {}

    class FixtureWeb:
        async def run(self, name, args, sid, *, scope_id=None):
            sent.update(name=name, args=args, sid=sid, scope_id=scope_id)
            return {'content': 'host-side'}

    class FixtureExecutor:
        async def execute(self, name, args, sid):
            raise AssertionError('box executor không được nhận web_search')

        async def cleanup(self, sid):
            return None

    runtime = HarnessRuntime.__new__(HarnessRuntime)
    runtime.web = FixtureWeb()
    runtime.root_session_id = lambda sid: sid
    session = {'id': 's1', 'role': 'orchestrator', 'config': {'tools': {'web_search'}}}
    from types import SimpleNamespace
    runtime.store = SimpleNamespace(get=lambda sid: session)
    result = asyncio.run(HarnessRuntime.dispatch(runtime, session, 'web_search', {'query': 'x'}))
    assert result == {'content': 'host-side'}
    assert sent == {'name': 'web_search', 'args': {'query': 'x'}, 'sid': 's1', 'scope_id': 's1'}
