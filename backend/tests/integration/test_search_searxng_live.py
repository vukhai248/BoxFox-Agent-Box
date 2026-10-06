"""D3 tầng 3 — SearXNG THẬT (container cục bộ): chứng minh "không khoá vẫn tìm được".

Bộ này tự `skip` khi không thấy container, nên chạy được cả trên máy chưa dựng SearXNG:
`bash deploy/searxng/up.sh` rồi chạy lại (xem `docs/testing/builtin-search-e2e.md`).

Mọi bài ở đây XOÁ SẠCH mọi khoá tìm kiếm trước khi chạy: nếu một bài xanh vì có khoá thì nó
không chứng minh được điều cần chứng minh.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import pytest

from agentbox.agent_core import search_pipeline as sp
from agentbox.agent_core.web import WebError, WebTools

#: Đích của container thật; đổi được để thử nhánh `skip` (ví dụ `http://127.0.0.1:9`).
LIVE_URL = (os.environ.get('BOXFOX_SEARXNG_LIVE_URL') or 'http://127.0.0.1:8888').rstrip('/')
SKIP_REASON = ('SearXNG chưa chạy: bash deploy/searxng/up.sh '
               '(xem docs/testing/builtin-search-e2e.md)')
API_KEY_VARS = ('BRAVE_API_KEY', 'BOXFOX_BRAVE_API_KEY', 'TAVILY_API_KEY', 'EXA_API_KEY',
                'PARALLEL_API_KEY', 'FIRECRAWL_API_KEY')


def _alive(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip('/') + sp.SEARXNG_HEALTH_PATH, timeout=2) as answer:
            return answer.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


@pytest.fixture()
def live(monkeypatch, tmp_path):
    """SearXNG thật, môi trường đã sạch khoá, DB tìm kiếm riêng cho bài này."""
    if not _alive(LIVE_URL):
        pytest.skip(SKIP_REASON)
    for name in API_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(sp.SEARXNG_URL_ENV, LIVE_URL)
    monkeypatch.delenv(sp.PIPELINE_ENV, raising=False)
    monkeypatch.setenv('BOXFOX_SEARCH_DB', str(tmp_path / 'search.sqlite'))
    sp.reset_autodetect()
    sp.reset_store()
    try:
        yield LIVE_URL
    finally:
        sp.reset_autodetect()
        sp.reset_store()


def test_web_search_returns_results_with_no_api_key(live):
    payload = WebTools().search({'query': 'hướng dẫn điều trị tăng huyết áp', 'count': 5})
    assert payload['count'] >= 1, payload
    assert all(str(row['url']).startswith('http') for row in payload['results'])
    assert payload['pipeline']['steps']['results'] >= 1, 'ống 10 bước phải là đường đã chạy'
    assert payload['pipeline']['enginesUsed'], 'phải nói được engine nào đã trả hàng'
    assert sp.pipeline_mode() == 'auto', 'mặc định phải là auto, không phải off'


def test_the_same_search_works_with_the_pipeline_off(live, monkeypatch):
    """Chân `_provider_searxng` một mình cũng đủ — ống 10 bước không phải điều kiện sống còn."""
    monkeypatch.setenv(sp.PIPELINE_ENV, 'off')
    payload = WebTools().search({'query': 'hướng dẫn điều trị tăng huyết áp', 'count': 5})
    assert payload['count'] >= 1, payload
    assert 'pipeline' not in payload, 'pipeline off ⇒ payload phải sạch khối ống'
    assert payload['results'][0]['provider'] == 'searxng', payload['results'][0]


def test_a_dead_searxng_url_falls_back_instead_of_failing(live, monkeypatch):
    """URL chết: hoặc rơi xuống chân sau (có `searchFallback`), hoặc lỗi phân loại `infra`."""
    monkeypatch.setenv(sp.SEARXNG_URL_ENV, 'http://127.0.0.1:9')
    try:
        payload = WebTools().search({'query': 'hướng dẫn điều trị tăng huyết áp', 'count': 3})
    except WebError as exc:
        assert exc.details['searchFailure']['kind'] in ('infra', 'config'), exc.details
        assert 'not a query problem' in str(exc)
        return
    assert payload['count'] >= 1
    assert payload.get('searchFallback'), 'rơi chân mà không nói rơi chân ⇒ người đọc không biết'


def test_the_engine_health_table_learns_from_a_real_search(live):
    WebTools().search({'query': 'hướng dẫn điều trị tăng huyết áp', 'count': 5})
    status = sp.search_status()
    assert status['searxng']['url'] == LIVE_URL
    assert status['engines'], 'một lời gọi thật phải để lại ít nhất một hàng sức khoẻ engine'
    assert any(row.get('ok') or row.get('empty') for row in status['engines'])


def test_probe_json_of_the_ops_script_agrees_with_the_harness(live):
    """`probe.py --json` (kịch bản vận hành) và harness phải nói cùng một sự thật."""
    import pathlib
    import subprocess
    import sys
    script = pathlib.Path(__file__).resolve().parents[3] / 'deploy' / 'searxng' / 'probe.py'
    assert script.exists(), f'không thấy {script}'
    answer = subprocess.run([sys.executable, script, '--json', '--url', LIVE_URL],
                            capture_output=True, text=True, timeout=60)
    assert answer.returncode in (0, 2), answer.stderr
    body = json.loads(answer.stdout)
    assert body['verdict'] in ('results', 'empty')
    assert body['exit_code'] == answer.returncode
