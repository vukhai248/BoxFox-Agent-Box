"""`source_pack` (P0b §3): tìm/đọc từ gói nguồn, KHÔNG gọi mạng.

Điểm phải giữ đúng: `None` (gói không có `search_index.jsonl` ⇒ người gọi rơi về đường thật)
KHÁC `[]` (gói có chỉ mục nhưng không dòng nào khớp ⇒ gói trả lời "không có gì").
"""
from __future__ import annotations

import json

import pytest

from agentbox.agent_core import source_pack


def _make_pack(root, *, with_index=True):
    (root / 'pages').mkdir(parents=True, exist_ok=True)
    (root / 'pack.json').write_text(json.dumps({
        'scenarioId': 's1', 'builtAt': '2026-09-25T00:00:00Z',
        'sources': [
            {'url': 'https://a.example/rag', 'title': 'RAG overview', 'date': '2026-03-01',
             'kind': 'page', 'accessLevel': 'fulltext-read', 'file': 'rag.html'},
            {'url': 'https://b.example/rag2', 'title': 'RAG two', 'date': '',
             'kind': 'page', 'accessLevel': 'abstract', 'file': 'rag2.txt'},
        ]}), encoding='utf-8')
    (root / 'pages' / 'rag.html').write_text(
        '<html><head><title>RAG overview</title></head>'
        '<body><p>Retrieval augmented generation combines a retriever with a generator.</p>'
        '</body></html>', encoding='utf-8')
    (root / 'pages' / 'rag2.txt').write_text('plain text about RAG', encoding='utf-8')
    if with_index:
        lines = [
            json.dumps({'query': 'retrieval augmented generation',
                        'urls': [{'url': 'https://a.example/rag', 'rank': 1, 'snippet': 'RAG ...'},
                                 {'url': 'https://b.example/rag2', 'rank': 2, 'snippet': 'two'}]}),
            json.dumps({'query': 'thị trường xe điện',
                        'urls': [{'url': 'https://a.example/rag', 'rank': 1, 'snippet': 'x'}]}),
        ]
        (root / 'search_index.jsonl').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return root


def test_active_pack_is_none_without_the_env(monkeypatch):
    monkeypatch.delenv('BOXFOX_WEB_PACK', raising=False)
    assert source_pack.active_pack() is None


def test_active_pack_reads_a_directory(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.active_pack() == tmp_path


def test_no_index_file_returns_none(monkeypatch, tmp_path):
    _make_pack(tmp_path, with_index=False)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.pack_search('retrieval augmented generation', 5, {}) is None


def test_exact_index_match_returns_rows_with_metadata(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    rows = source_pack.pack_search('retrieval augmented generation', 5, {})
    assert [row['url'] for row in rows] == ['https://a.example/rag', 'https://b.example/rag2']
    first = rows[0]
    assert first['provider'] == 'pack' and first['engines'] == ['pack']
    assert first['title'] == 'RAG overview' and first['publishedAt'] == '2026-03-01'
    assert first['dateSource'] == 'provider'
    assert first['accessLevel'] == 'fulltext-read'


def test_token_match_accepts_a_wider_query(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    rows = source_pack.pack_search('what is retrieval augmented generation exactly', 5, {})
    assert rows and rows[0]['url'] == 'https://a.example/rag'


def test_index_present_but_no_match_returns_empty(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.pack_search('chủ đề hoàn toàn khác', 5, {}) == []


def test_count_caps_the_rows(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    rows = source_pack.pack_search('retrieval augmented generation', 1, {})
    assert len(rows) == 1


def test_pack_fetch_reads_html_and_txt(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    html = source_pack.pack_fetch('https://a.example/rag')
    assert html['contentType'] == 'text/html' and 'Retrieval augmented generation' in html['text']
    assert html['title'] == 'RAG overview' and html['dateSource'] == 'provider'
    txt = source_pack.pack_fetch('https://b.example/rag2')
    assert txt['contentType'] == 'text/plain' and txt['text'] == 'plain text about RAG'
    assert txt['dateSource'] == 'unknown'


def test_pack_fetch_missing_url_is_none(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.pack_fetch('https://missing.example/nope') is None


def test_pack_pages_lists_the_manifest(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    pages = source_pack.pack_pages()
    assert [page['url'] for page in pages] == ['https://a.example/rag', 'https://b.example/rag2']


def test_trailing_slash_urls_match(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.pack_fetch('https://a.example/rag/')['title'] == 'RAG overview'


def test_access_level_uses_one_vocabulary_across_pack_rows(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    manifest = json.loads((tmp_path / 'pack.json').read_text(encoding='utf-8'))
    # Từ vựng §3 của gói (`open|abstract|paywalled|metadata`) quy về từ vựng dùng chung.
    manifest['sources'][0]['accessLevel'] = 'open'
    manifest['sources'][1]['accessLevel'] = 'paywalled'
    (tmp_path / 'pack.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    rows = source_pack.pack_search('retrieval augmented generation', 5, {})
    assert rows[0]['accessLevel'] == 'fulltext-available'
    assert rows[1]['accessLevel'] == 'snippet'
    # Giá trị đã đúng từ vựng chung thì giữ nguyên, không quy đổi vòng.
    assert source_pack._access_level('fulltext-read') == 'fulltext-read'
    assert source_pack._access_level('') == 'snippet'
    assert source_pack._access_level(None) == 'snippet'
    assert all(level in source_pack.ACCESS_LEVELS for level in
               ('fulltext-available', 'snippet', 'abstract', 'fulltext-read'))


def test_pack_fetch_refuses_a_file_outside_the_pack_tree(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    outside = tmp_path.parent / 'outside.html'
    outside.write_text('<p>secret</p>', encoding='utf-8')
    manifest = json.loads((tmp_path / 'pack.json').read_text(encoding='utf-8'))
    manifest['sources'].append({'url': 'https://evil.example/x', 'title': 'X', 'date': '',
                                'kind': 'page', 'accessLevel': 'open',
                                'file': f'../{outside.name}'})
    (tmp_path / 'pack.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.pack_fetch('https://evil.example/x') is None


def test_pack_fetch_refuses_an_absolute_file(monkeypatch, tmp_path):
    _make_pack(tmp_path)
    manifest = json.loads((tmp_path / 'pack.json').read_text(encoding='utf-8'))
    manifest['sources'].append({'url': 'https://evil.example/y', 'title': 'Y', 'date': '',
                                'kind': 'page', 'accessLevel': 'open', 'file': '/etc/hostname'})
    (tmp_path / 'pack.json').write_text(json.dumps(manifest), encoding='utf-8')
    monkeypatch.setenv('BOXFOX_WEB_PACK', str(tmp_path))
    assert source_pack.pack_fetch('https://evil.example/y') is None


def test_a_pack_written_by_the_shipped_builder_is_readable(monkeypatch, tmp_path):
    """Vòng soát 2 (lỗ B-1): cặp GHI (`scripts/eval/packs/build_pack.py`) — ĐỌC (`pack_fetch`) phải
    được kiểm với nhau. Bản đầu chỉ ghép `pages/` vào `file`, mà `build_pack` đã ghi `pages/<tệp>`
    theo đúng hợp đồng §3, nên MỌI gói thật đọc trượt (`<gói>/pages/pages/<tệp>`) và `web_fetch`
    báo "không có trong gói" — phá đúng phép so sánh ngoại tuyến mà gói tồn tại vì nó.
    """
    import sys
    from pathlib import Path as _Path

    eval_dir = _Path(__file__).resolve().parents[3] / 'scripts' / 'eval'
    sys.path.insert(0, str(eval_dir / 'packs'))
    try:
        import build_pack
    finally:
        sys.path.pop(0)

    page = tmp_path / 'nguon' / 'rag.html'
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text('<html><body><p>Retrieval augmented generation.</p></body></html>',
                    encoding='utf-8')
    manifest = tmp_path / 'sources.json'
    manifest.write_text(json.dumps({'scenarioId': 's-roundtrip', 'sources': [
        {'url': 'https://a.example/rag', 'title': 'RAG', 'date': '2026-03-01', 'kind': 'page',
         # `build_pack` kiểm theo từ vựng của GÓI (`open|abstract|paywalled|metadata`); tầng ra
         # cho mô hình mới là từ vựng chung của harness — hai từ vựng, một chiều ánh xạ.
         'accessLevel': 'open', 'file': 'nguon/rag.html'}]}), encoding='utf-8')
    queries = tmp_path / 'queries.jsonl'
    queries.write_text(json.dumps({'query': 'retrieval augmented generation',
                                   'results': [{'url': 'https://a.example/rag', 'rank': 1,
                                                'snippet': 'RAG'}]}) + '\n', encoding='utf-8')
    pack_dir = tmp_path / 'pack'
    built = build_pack.build_pack(manifest, pack_dir, queries_path=queries,
                                  built_at='2026-09-25T00:00:00Z')
    assert built['files'] == ['pages/a-example-rag.html']

    monkeypatch.setenv('BOXFOX_WEB_PACK', str(pack_dir))
    found = source_pack.pack_search('retrieval augmented generation', 5, {})
    assert found and found[0]['url'] == 'https://a.example/rag'
    page_body = source_pack.pack_fetch('https://a.example/rag')
    assert page_body and 'Retrieval augmented generation' in page_body['text']
