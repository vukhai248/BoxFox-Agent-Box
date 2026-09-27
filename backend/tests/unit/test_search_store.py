"""`search_store` (P0b §2): bộ đệm, chỉ mục FTS5, nhật ký tìm, sức khoẻ engine.

Mọi ca chạy trên DB trong `tmp_path`; không ca nào chạm mạng hay DB thật của máy.
"""
from __future__ import annotations

import time

import pytest

from agentbox.agent_core import search_store


@pytest.fixture
def store(tmp_path):
    return search_store.connect(tmp_path / 'search.sqlite')


# ------------------------------------------------------------------ đường mặc định

def test_default_path_prefers_the_explicit_env(monkeypatch, tmp_path):
    monkeypatch.setenv('BOXFOX_SEARCH_DB', str(tmp_path / 'x.sqlite'))
    assert search_store.default_path() == tmp_path / 'x.sqlite'


def test_default_path_falls_back_under_the_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv('BOXFOX_SEARCH_DB', raising=False)
    monkeypatch.setenv('BOXFOX_AGENT_DATA_DIR', str(tmp_path / 'data'))
    assert search_store.default_path() == tmp_path / 'data' / 'search.sqlite'


# ------------------------------------------------------------------ bộ đệm

def test_cache_round_trip_and_ttl(store):
    store.cache_put('k1', 'web', 'truy vấn', {'site': 'x'}, {'results': [1]}, ttl=60)
    assert store.cache_get('k1') == {'results': [1]}
    store.cache_put('k2', 'web', 'truy vấn', {}, {'results': []}, ttl=0)
    assert store.cache_get('k2') is None, 'TTL 0 là đã hết hạn ngay'
    assert store.cache_get('missing') is None


# ------------------------------------------------------------------ chỉ mục

def test_index_upsert_get_and_fts_search(store):
    store.index_upsert('https://a.example/doc', 'Retrieval augmented generation',
                       'RAG combines a retriever with a generator.', domain='a.example')
    got = store.index_get('https://a.example/doc')
    assert got['title'] == 'Retrieval augmented generation'
    assert got['domain'] == 'a.example'
    hits = store.index_search('retrieval generator', limit=5)
    assert hits and hits[0]['url'] == 'https://a.example/doc'
    assert store.index_search('zzz-không-có', limit=5) == []


def test_an_empty_index_search_is_empty_not_none(store):
    """Chỉ mục RỖNG trả `[]` — khác hẳn "gói không có chỉ mục" của `source_pack`."""
    assert store.index_search('bất kỳ', limit=5) == []


def test_index_upsert_replaces_the_fts_row(store):
    store.index_upsert('https://a.example/doc', 'bản một', 'nội dung cũ')
    store.index_upsert('https://a.example/doc', 'bản hai', 'nội dung mới')
    assert store.index_get('https://a.example/doc')['title'] == 'bản hai'
    assert store.index_search('mới', limit=5) and not store.index_search('cũ', limit=5)


# ------------------------------------------------------------------ nhật ký tìm

def test_search_log_records_and_filters(store):
    store.log_search({'research_id': 'r1', 'query': 'một', 'variant_kind': 'keywords',
                      'engines': ['brave', 'bing'], 'results': 3, 'latency_ms': 120})
    store.log_search({'research_id': 'r2', 'query': 'hai', 'results': 1})
    assert len(store.search_log()) == 2
    only = store.search_log(research_id='r1')
    assert len(only) == 1 and only[0]['engines'] == ['brave', 'bing'] and only[0]['latency_ms'] == 120
    assert store.search_log(since=time.time() + 1000) == []


# ------------------------------------------------------------------ sức khoẻ engine

def test_three_failures_suspend_an_engine_and_pick_excludes_it(store):
    for _ in range(3):
        store.record_engine_result('brave', ok=False, empty=False, blocked=True, timeout=False,
                                   latency_ms=100)
    rows = {row['engine']: row for row in store.engine_health()}
    assert rows['brave']['fails_streak'] == 3
    assert rows['brave']['suspended_until'] > time.time()
    picked = store.pick_engines(4, kind='web')
    assert 'brave' not in picked and picked, 'engine bị ngưng không được chọn, nhưng vẫn phải chọn được engine khác'


def test_backoff_grows_with_each_further_suspension(store):
    def health(engine):
        return {row['engine']: row for row in store.engine_health()}[engine]

    store.record_engine_result('bing', ok=False, empty=False, blocked=True, timeout=False, latency_ms=50)
    store.record_engine_result('bing', ok=True, empty=False, blocked=False, timeout=False, latency_ms=50)
    assert health('bing')['fails_streak'] == 0, 'thành công đặt lại chuỗi lỗi'
    assert health('bing')['suspended_until'] == 0

    for _ in range(3):
        store.record_engine_result('mojeek', ok=False, empty=False, blocked=False, timeout=True, latency_ms=1)
    first_until = health('mojeek')['suspended_until']
    assert first_until > time.time()
    for _ in range(3):
        store.record_engine_result('mojeek', ok=False, empty=False, blocked=True, timeout=False, latency_ms=1)
    # Lần ngưng thứ hai phải lùi XA HƠN lần đầu (300 s → 900 s).
    assert health('mojeek')['suspended_until'] > first_until


def test_pick_engines_returns_n_healthy_engines(store):
    picked = store.pick_engines(3, kind='web')
    assert len(picked) == 3 and len(set(picked)) == 3


def test_pick_engines_falls_back_when_all_are_suspended(store):
    for engine in search_store.DEFAULT_ENGINES_BY_KIND['web']:
        for _ in range(3):
            store.record_engine_result(engine, ok=False, empty=False, blocked=True, timeout=False,
                                       latency_ms=10)
    picked = store.pick_engines(2, kind='web')
    assert picked and all(engine in search_store.ENGINE_FALLBACK for engine in picked)


def test_boxfox_search_engines_overrides_the_web_set(monkeypatch, store):
    monkeypatch.setenv('BOXFOX_SEARCH_ENGINES', 'brave, bing')
    assert store.pick_engines(5, kind='web')[:2] == ['brave', 'bing']


def test_p50_and_p95_are_recorded(store):
    store.record_engine_result('qwant', ok=True, empty=False, blocked=False, timeout=False, latency_ms=200)
    row = store.engine_health()[0]
    assert row['p50_ms'] == 200 and row['p95_ms'] == 200
