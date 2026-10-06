#!/usr/bin/env python3
"""E2E xuyên hệ thống cho "Web Search API" (PART 2, task 6) — chạy KHÔNG cần khoá thật.

Chuỗi được kiểm: **router tạm (3199) → harness (tiến trình này) → máy chủ provider giả**.
Không ca nào chạm Internet: mọi endpoint của provider được trỏ về `fake_search_providers.py`
bằng các hook `BOXFOX_<ID>_SEARCH_URL` + `BOXFOX_WEB_TEST_ALLOW_LOOPBACK=1`.

Cách chạy (không cần biến khoá nào):

```
cd backend && TMPDIR=/var/tmp PYTHONPATH=src /var/tmp/boxfox-venv/bin/python \\
  ../scripts/e2e/search_provider_e2e.py
```

Script tự mở router con (dữ liệu riêng trong `BOXFOX_E2E_DIR`, mặc định `/var/tmp/boxfox-e2e`),
tự dọn khi xong, và trả mã khác 0 nếu bất kỳ kịch bản nào hỏng.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(HERE))

from fake_search_providers import FakeSearchProviders       # noqa: E402

ROUTER_PORT = int(os.environ.get('BOXFOX_E2E_ROUTER_PORT', '3199'))
ROUTER_URL = f'http://127.0.0.1:{ROUTER_PORT}'
E2E_DIR = Path(os.environ.get('BOXFOX_E2E_DIR', '/var/tmp/boxfox-e2e'))
ADMIN = {'x-boxfox-admin': '1', 'Origin': 'http://localhost:3100'}   # đúng origin mà Vite proxy gửi tới
BRAVE_KEY = 'E2E-BRAVE-KEY'
CF_KEY = 'E2E-CLOUDFLARE-KEY'
CUSTOM_KEY = 'E2E-CUSTOM-KEY'


# --------------------------------------------------------------------- HTTP router

def router_request(method: str, path: str, body: dict | None = None, *, admin: bool = True,
                   timeout: float = 10.0):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    headers = {'Content-Type': 'application/json'} if data else {}
    if admin:
        headers.update(ADMIN)
    request = urllib.request.Request(ROUTER_URL + path, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
            return response.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8')
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {'raw': raw}


def _dead_loopback_url() -> str:
    """Một URL loopback trỏ vào cổng vừa đóng: kết nối bị từ chối, không chạm Internet."""
    import socket
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()
    return f'http://127.0.0.1:{port}/'


def wait_for_router(deadline: float = 30.0) -> None:
    end = time.time() + deadline
    while time.time() < end:
        try:
            status, _ = router_request('GET', '/api/router/health', admin=False, timeout=2)
            if status < 500:
                return
        except Exception:
            pass
        time.sleep(0.25)                     # router trả 5xx cũng phải chờ, không quay CPU
    raise RuntimeError(f'router không lên được ở {ROUTER_URL}')


class RouterProcess:
    def __init__(self, extra_env: dict | None = None) -> None:
        self.data_dir = E2E_DIR / 'router'
        shutil.rmtree(self.data_dir, ignore_errors=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, BOXFOX_ROUTER_PORT=str(ROUTER_PORT),
                   BOXFOX_ROUTER_DATA_DIR=str(self.data_dir),
                   BOXFOX_MODEL_SYNC_MS='86400000')
        # Nút "Kiểm tra" của tab chạy trong router ⇒ router cũng phải trỏ vào máy giả.
        env.update(extra_env or {})
        self.log = open(E2E_DIR / 'router.log', 'wb')
        self.proc = subprocess.Popen(['node', str(REPO / 'router' / 'src' / 'main.mjs')],
                                     cwd=str(REPO / 'router'), env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT)

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGTERM)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.log.close()


# --------------------------------------------------------------------- harness

def search(query: str, count: int = 3) -> dict:
    """Một lời gọi `web_search` thật của harness (cùng đường mà agent dùng)."""
    from agentbox.agent_core import search_credentials
    from agentbox.agent_core.web import WebTools
    search_credentials.invalidate()
    tools = WebTools()
    return tools.search({'query': query, 'count': count})


# --------------------------------------------------------------------- kịch bản

SCENARIOS: list[tuple[str, str, object]] = []


def scenario(name: str, title: str):
    def wrap(fn):
        SCENARIOS.append((name, title, fn))
        return fn
    return wrap


@scenario('default_choice_uses_the_builtin_path',
          'không cấu hình gì ⇒ dùng đường built-in, không gọi Brave')
def _default(fake: FakeSearchProviders) -> None:
    fake.reset()
    result = search('mặc định không khoá')
    assert result['results'], f'phải có kết quả từ built-in, nhận {result}'
    assert not fake.calls('brave'), 'không được gọi Brave khi chưa cấu hình'
    assert fake.calls('searxng'), 'built-in phải đi qua SearXNG tự host'


@scenario('a_saved_brave_key_is_resolved_and_used',
          'lưu khoá Brave + chọn dùng ⇒ harness gọi Brave, gửi đúng header, không rò khoá')
def _brave(fake: FakeSearchProviders) -> None:
    status, view = router_request('POST', '/api/router/search/providers',
                                  {'providerId': 'brave', 'apiKey': BRAVE_KEY})
    assert status == 201, f'POST provider phải 201, nhận {status} {view}'
    status, active = router_request('PUT', '/api/router/search/active', {'providerId': 'brave'})
    assert status == 200 and active['activeProviderId'] == 'brave', active
    fake.reset()
    result = search('truy vấn brave')
    assert result['results'], result
    assert result['results'][0]['provider'] == 'brave', result['results'][0]
    calls = fake.calls('brave')
    assert len(calls) == 1, f'đúng một lời gọi Brave, nhận {len(calls)}'
    assert calls[0]['authHeaders'].get('X-Subscription-Token') == '<present>', calls[0]
    assert not fake.calls('searxng'), 'nguồn đã chọn phải đứng đầu, không gọi SearXNG'
    assert BRAVE_KEY not in json.dumps(result), 'khoá thô không được vào payload'


@scenario('the_router_state_endpoint_never_leaks_the_key',
          'GET /api/router/state chỉ chứa prefix, không chứa khoá thô')
def _state(fake: FakeSearchProviders) -> None:
    status, state = router_request('GET', '/api/router/state')
    assert status == 200, status
    raw = json.dumps(state)
    assert BRAVE_KEY not in raw, 'khoá thô rò ra /api/router/state'
    search_section = state.get('search') or {}
    brave = next((row for row in search_section.get('providers', []) if row['id'] == 'brave'), None)
    assert brave, f'state phải có mục brave: {search_section}'
    assert brave['prefix'] and brave['prefix'].endswith('…'), brave


@scenario('a_broken_selected_key_falls_through_to_the_builtin_path',
          'khoá đã chọn hỏng (401) ⇒ vẫn có kết quả built-in; mọi bậc hỏng thì câu lỗi nêu tên nguồn')
def _broken(fake: FakeSearchProviders) -> None:
    from agentbox.agent_core.web import WebError

    # Giữ NGUYÊN giá trị gốc để trả lại: `fake.url('searxng')` trả `…/searxng/search` (đường ĐẦY ĐỦ),
    # còn biến môi trường phải là GỐC `…/searxng` — trả nhầm là mọi kịch bản sau mất bậc built-in.
    original = {name: os.environ.get(name, '') for name in
                ('BOXFOX_BRAVE_SEARCH_URL', 'BOXFOX_SEARXNG_URL', 'BOXFOX_FIRECRAWL_SEARCH_URL')}
    os.environ['BOXFOX_BRAVE_SEARCH_URL'] = fake.url('brave', status=401)
    fake.reset()
    try:
        result = search('truy vấn brave hỏng')
        assert result['results'], 'phải rơi xuống bậc tiếp theo và vẫn có kết quả'
        # Hai khẳng định dưới đây giữ cho kịch bản KHÔNG rỗng: thiếu chúng thì nó vẫn xanh khi
        # tính năng "nguồn đang chọn" biến mất, hoặc khi hook ghi đè URL không được áp dụng và
        # lời gọi đi thẳng ra api.search.brave.com thật.
        assert fake.calls('brave'), 'nguồn ĐÃ CHỌN phải được gọi trước bậc built-in'
        assert fake.calls('searxng'), 'bậc built-in phải chạy sau khi nguồn chọn hỏng'

        # Vế thứ hai của tên kịch bản: khi MỌI bậc hỏng, câu lỗi phải nói tên nguồn đang chọn,
        # nếu không người dùng chỉ thấy các chân built-in hỏng và không hiểu vì sao.
        # SearXNG nhận GỐC rồi harness tự nối `/search?q=…`, nên không gắn `?status=` vào gốc được:
        # trỏ nó vào một cổng vừa đóng (kết nối bị từ chối, vẫn kín mạng).
        os.environ['BOXFOX_SEARXNG_URL'] = _dead_loopback_url()
        os.environ['BOXFOX_FIRECRAWL_SEARCH_URL'] = fake.url('firecrawl', status=503)
        try:
            search('truy vấn mọi bậc hỏng')
        except WebError as exc:
            assert "selected source 'brave'" in str(exc), str(exc)
        else:
            raise AssertionError('mọi bậc đều hỏng mà không ném WebError')
    finally:
        for name, value in original.items():
            os.environ[name] = value
        # Lượt tìm hỏng vừa rồi có thể đã đánh dấu SearXNG là không dùng được; xoá dấu đó để các
        # kịch bản sau vẫn thấy đúng trạng thái sạch.
        from agentbox.agent_core import search_pipeline
        search_pipeline.reset_autodetect()


@scenario('the_cloudflare_entry_needs_account_and_key_and_maps_items',
          'Cloudflare cần đủ accountId + token và map đúng items[]')
def _cloudflare(fake: FakeSearchProviders) -> None:
    status, body = router_request('POST', '/api/router/search/providers',
                                  {'providerId': 'cloudflare', 'apiKey': CF_KEY})
    assert status == 400, f'thiếu accountId phải 400, nhận {status} {body}'
    status, view = router_request('POST', '/api/router/search/providers',
                                  {'providerId': 'cloudflare', 'apiKey': CF_KEY, 'accountId': 'acct-123'})
    assert status == 201, f'{status} {view}'
    router_request('PUT', '/api/router/search/active', {'providerId': 'cloudflare'})
    fake.reset()
    result = search('truy vấn cloudflare')
    assert result['results'] and result['results'][0]['provider'] == 'cloudflare', result['results'][:1]
    assert fake.calls('cloudflare'), 'phải gọi endpoint Cloudflare giả'
    assert not fake.calls('searxng'), 'nguồn đã chọn phải chặn các bậc sau'


@scenario('the_custom_entry_posts_the_query_with_the_stored_key',
          'custom endpoint nhận POST + Bearer và chuẩn hoá results[]')
def _custom(fake: FakeSearchProviders) -> None:
    status, view = router_request('POST', '/api/router/search/providers',
                                  {'providerId': 'custom', 'endpoint': fake.url('custom'),
                                   'apiKey': CUSTOM_KEY})
    assert status == 201, f'{status} {view}'
    router_request('PUT', '/api/router/search/active', {'providerId': 'custom'})
    fake.reset()
    result = search('truy vấn custom')
    assert result['results'] and result['results'][0]['provider'] == 'custom', result['results'][:1]
    calls = fake.calls('custom')
    assert calls and calls[0]['method'] == 'POST', calls
    assert calls[0]['authHeaders'].get('Authorization') == '<present>', calls[0]
    assert not calls[0]['hasSecretInBody'], 'khoá thô không được nằm trong thân bài'


@scenario('removing_the_active_provider_returns_to_the_builtin_path',
          'xoá mục đang dùng ⇒ activeProviderId = null và tìm kiếm về built-in')
def _remove(fake: FakeSearchProviders) -> None:
    status, _ = router_request('DELETE', '/api/router/search/providers/custom')
    assert status == 200, status
    status, state = router_request('GET', '/api/router/search')
    assert status == 200 and state['activeProviderId'] is None, state
    fake.reset()
    result = search('sau khi xoá nguồn chọn')
    assert result['results'], result
    assert fake.calls('searxng'), 'phải quay lại đường built-in'


@scenario('the_ui_contract_shapes_match',
          'tám route của hợp đồng UI trả đúng hình dạng đã chốt')
def _contract(fake: FakeSearchProviders) -> None:
    status, listing = router_request('GET', '/api/router/search')
    assert status == 200, status
    for key in ('activeProviderId', 'revision', 'providers'):
        assert key in listing, f'GET /api/router/search thiếu {key}: {listing}'
    provider_keys = {'id', 'name', 'requires', 'optional', 'envKeys', 'icon', 'credentialPresent',
                     'hasSecret', 'prefix', 'endpoint', 'accountId', 'lastTestedAt', 'lastTest'}
    for row in listing['providers']:
        missing = provider_keys - set(row)
        assert not missing, f'mục {row.get("id")} thiếu khoá {sorted(missing)}'
    status, created = router_request('POST', '/api/router/search/providers',
                                     {'providerId': 'tavily', 'apiKey': 'E2E-TAVILY-KEY'})
    assert status == 201, f'{status} {created}'
    assert 'E2E-TAVILY-KEY' not in json.dumps(created), 'view không được chứa khoá thô'
    status, patched = router_request('PATCH', '/api/router/search/providers/tavily',
                                     {'apiKey': 'E2E-TAVILY-KEY-2'})
    assert status == 200, f'{status} {patched}'
    status, revealed = router_request('POST', '/api/router/search/providers/tavily/reveal')
    assert status == 200 and revealed.get('key') == 'E2E-TAVILY-KEY-2', revealed
    status, tested = router_request('POST', '/api/router/search/providers/tavily/test')
    assert status == 200 and set(tested) >= {'ok', 'providerId', 'status', 'latencyMs', 'code',
                                             'message', 'sample'}, tested
    assert tested['ok'] is True, f'nút Kiểm tra phải chạm endpoint giả và xanh, nhận {tested}'
    assert fake.calls('tavily'), 'probe phải đi qua hook BOXFOX_TAVILY_SEARCH_URL, không ra Internet thật'
    status, resolved = router_request('GET', '/api/router/search/resolve')
    assert status == 200 and 'revision' in resolved and 'active' in resolved, resolved
    status, active = router_request('PUT', '/api/router/search/active', {'providerId': 'tavily'})
    assert status == 200 and active.get('activeProviderId') == 'tavily', active
    assert active.get('revision', 0) > resolved.get('revision', 0), 'đổi lựa chọn phải đẩy revision lên'
    router_request('PUT', '/api/router/search/active', {'providerId': None})
    status, denied = router_request('GET', '/api/router/search', admin=False)
    assert status == 403, f'thiếu header admin phải 403, nhận {status} {denied}'
    router_request('DELETE', '/api/router/search/providers/tavily')


@scenario('a_real_key_smoke_test_is_manual_and_optional',
          'smoke test với khoá thật là thủ công (chỉ in hướng dẫn)')
def _manual(fake: FakeSearchProviders) -> None:
    print('      ↳ thủ công: mở Settings → Provider → Web Search, dán khoá thật, bấm "Kiểm tra";')
    print('        kỳ vọng ok: true, và log harness có dòng "selected source \'<id>\'".')


# --------------------------------------------------------------------- điều khiển

#: Kịch bản CHỈ in hướng dẫn (cần khoá thật) — không tính vào số kịch bản tự động đã kiểm.
MANUAL_SCENARIOS = {'a_real_key_smoke_test_is_manual_and_optional'}


def main() -> int:
    E2E_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('BOXFOX_SEARCH_REFRESH', '1')
    os.environ.setdefault('BOXFOX_ROUTER_SEARCH_URL', ROUTER_URL + '/api/router/search/resolve')
    os.environ.setdefault('BOXFOX_SEARCH_SOURCE_TTL', '0')
    # Bậc built-in gọi `record_response_health` ⇒ DB engine THẬT. Không trỏ nó vào thư mục tạm thì
    # mỗi lần chạy E2E lại gieo hàng sức khoẻ giả cho bing/brave/... vào `~/BoxFox/harness/search.sqlite`,
    # và những hàng đó nuôi cầu dao ngắt engine (3 lỗi liên tiếp ⇒ tạm dừng 5/15/60 phút).
    os.environ['BOXFOX_SEARCH_DB'] = str(E2E_DIR / 'search.sqlite')

    with FakeSearchProviders(log_path=str(E2E_DIR / 'fake-calls.jsonl')) as fake:
        os.environ.update(fake.env())
        router = RouterProcess(fake.env())
        try:
            wait_for_router()
            failures: list[str] = []
            checked = 0
            for index, (name, title, fn) in enumerate(SCENARIOS, start=1):
                manual = name in MANUAL_SCENARIOS
                print(f'[{index}/{len(SCENARIOS)}] {name} — {title}', flush=True)
                try:
                    fn(fake)
                    if not manual:
                        checked += 1
                    print('      PASS' + (' (thủ công)' if manual else ''), flush=True)
                except Exception as exc:                        # noqa: BLE001 — kịch bản nào hỏng cũng ghi lại
                    print(f'      FAIL: {exc.__class__.__name__}: {exc}', flush=True)
                    failures.append(name)
            manual_total = len(MANUAL_SCENARIOS & {name for name, _, _ in SCENARIOS})
            if failures:
                print(f'\n{len(failures)}/{len(SCENARIOS)} kịch bản HỎNG: {", ".join(failures)}')
                return 1
            print(f'\n{checked}/{len(SCENARIOS) - manual_total} kịch bản tự động XANH'
                  f' (+{manual_total} thủ công, chỉ in hướng dẫn)')
            return 0
        finally:
            router.stop()


if __name__ == '__main__':
    sys.exit(main())
