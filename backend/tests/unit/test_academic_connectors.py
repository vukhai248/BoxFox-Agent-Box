"""Keyless academic connectors (contract §4) — parsing, politeness, fusion, citations, budget.

Every test here is offline: ``academic.polite_get`` (or the lower ``_urlopen`` seam) is
replaced with a fixture, so no socket is opened. The payloads below mirror the *real* response
shapes of each provider:

* Semantic Scholar Graph — ``{"data": [{…, "externalIds": {"DOI", "ArXiv"}}]}``
* Crossref — ``{"message": {"items": [...]}}`` (``issued.date-parts``, ``is-referenced-by-count``)
* arXiv — Atom XML with ``<entry>`` blocks
* Europe PMC — ``{"resultList": {"result": [...]}}``
* DBLP — ``{"result": {"hits": {"hit": [{"info": …}]}}}``
* OpenReview API v2 — ``{"notes": [{"content": {"title": {"value": …}}}]}``
* OpenCitations COCI — a JSON array of ``{"citing", "cited", "creation", …}``
* GitHub — ``{"items": [...]}``
* Hugging Face Hub — a bare JSON array of model objects
* OpenAlex — ``{"results": [{"publication_date": …}]}``
"""
from __future__ import annotations

import json
import urllib.error

import pytest

from agentbox.agent_core import academic

# --------------------------------------------------------------------------- fixtures

S2_PAPER = {
    'paperId': 'abc123', 'title': 'Deep Learning for Widgets', 'abstract': 'We propose a widget.',
    'url': 'https://www.semanticscholar.org/paper/abc123',
    'externalIds': {'DOI': '10.1234/abc', 'ArXiv': '2101.00001'},
    'venue': 'NeurIPS', 'year': 2021, 'citationCount': 42, 'publicationDate': '2021-06-01',
    'openAccessPdf': {'url': 'https://arxiv.org/pdf/2101.00001'},
}
S2_PAYLOAD = {'total': 1, 'data': [S2_PAPER]}

CROSSREF_PAYLOAD = {'message': {'items': [{
    'DOI': '10.5555/xyz', 'title': ['A Crossref Paper'], 'abstract': '<jats:p>Abstract body</jats:p>',
    'issued': {'date-parts': [[2020, 3, 1]]}, 'indexed': {'date-time': '2020-04-02T00:00:00Z'},
    'container-title': ['Journal of Tests'], 'is-referenced-by-count': 7,
    'URL': 'https://doi.org/10.5555/xyz', 'type': 'journal-article',
}]}}

ARXIV_XML = (
    '<feed xmlns="http://www.w3.org/2005/Atom">'
    '<entry><id>http://arxiv.org/abs/2101.00001v2</id>'
    '<updated>2021-02-01T00:00:00Z</updated><published>2021-01-01T00:00:00Z</published>'
    '<title>An arXiv Paper</title><summary>Summary of the preprint.</summary>'
    '<arxiv:primary_category term="cs.LG"/></entry></feed>'
)

EPMC_PAYLOAD = {'resultList': {'result': [{
    'id': '12345', 'source': 'MED', 'pmid': '12345', 'pmcid': 'PMC999', 'doi': '10.1000/epmc',
    'title': 'A Biomedical Paper', 'journalTitle': 'BMJ', 'pubYear': '2019', 'citedByCount': 3,
    'abstractText': 'An abstract.', 'isOpenAccess': 'Y', 'firstPublicationDate': '2019-05-05',
}]}}

DBLP_PAYLOAD = {'result': {'hits': {'hit': [{'info': {
    'title': 'A DBLP Paper', 'venue': 'SIGCOMM', 'year': '2018', 'doi': '10.1145/123',
    'ee': 'https://doi.org/10.1145/123', 'key': 'conf/x/Y18', 'type': 'Conference and Workshop Papers',
    'authors': {'author': [{'text': 'A One'}, {'text': 'B Two'}]},
}}]}}}

OPENREVIEW_PAYLOAD = {'count': 1, 'notes': [{
    'id': 'or123', 'cdate': 1600000000000, 'pdate': 1600000000000,
    'content': {'title': {'value': 'An OpenReview Paper'}, 'abstract': {'value': 'Abstract OR'},
                'venue': {'value': 'ICLR 2021'}, 'venueid': {'value': 'ICLR.cc/2021/Conference'}},
}]}

OPENCITATIONS_PAYLOAD = [{'citing': '10.2000/citing1', 'cited': '10.1000/orig',
                          'creation': '2022-02-02', 'timespan': 'P1Y', 'journal_sc': 'no',
                          'author_sc': 'no'}]

GITHUB_PAYLOAD = {'items': [{
    'full_name': 'acme/lib', 'html_url': 'https://github.com/acme/lib', 'description': 'A lib',
    'stargazers_count': 123, 'pushed_at': '2024-01-02T03:04:05Z', 'created_at': '2020-01-01T00:00:00Z',
    'updated_at': '2024-01-02T03:04:05Z', 'language': 'Python', 'license': {'spdx_id': 'MIT'},
}]}

HF_PAYLOAD = [{'id': 'bert-base-uncased', 'modelId': 'bert-base-uncased', 'likes': 100,
               'downloads': 1000, 'pipeline_tag': 'fill-mask', 'tags': ['pytorch', 'bert'],
               'createdAt': '2019-01-01T00:00:00Z', 'lastModified': '2023-03-01T00:00:00Z'}]

OPENALEX_PAYLOAD = {'results': [{
    'id': 'https://openalex.org/W123', 'doi': 'https://doi.org/10.7777/oa',
    'display_name': 'An OpenAlex Paper', 'publication_date': '2021-07-07', 'publication_year': 2021,
    'cited_by_count': 9, 'primary_location': {'source': {'display_name': 'Nature'}},
    'best_oa_location': {'pdf_url': 'https://example.org/x.pdf'}, 'type': 'article',
}]}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body.encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self._body


def fake_get(mapping: dict, default=(404, '')):
    """A ``polite_get`` stand-in that answers by URL substring."""
    def _fake(host, url, **kwargs):
        for needle, response in mapping.items():
            if needle in url:
                return response
        return default
    return _fake


def ok(payload) -> tuple[int, str]:
    return 200, json.dumps(payload)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Keep the OpenAlex budget file inside tmp_path and freeze the budget day."""
    monkeypatch.setenv('BOXFOX_AGENT_DATA_DIR', str(tmp_path))
    monkeypatch.delenv('BOXFOX_OPENALEX_DAILY_CALLS', raising=False)
    monkeypatch.setattr(academic, '_today', lambda: '2026-09-25')
    academic._reset_host_state()
    yield


# ------------------------------------------------------------------- connector catalog

def test_connectors_catalog_covers_all_keyless_sources():
    catalog = academic.connectors()
    assert set(catalog) == {'semantic_scholar', 'crossref', 'arxiv', 'europepmc', 'dblp',
                            'openreview', 'opencitations', 'github', 'huggingface', 'openalex'}
    for name, meta in catalog.items():
        assert meta['needsKey'] is False, name
        assert meta['rps'] > 0, name
        assert meta['host'], name
    assert catalog['semantic_scholar']['main'] is True
    assert catalog['openalex']['dailyBudget'] is True


# ------------------------------------------------------------------ per-connector parsing

def test_semantic_scholar_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'paper/search': ok(S2_PAYLOAD)}))
    rows = academic.connector_search('semantic_scholar', 'widgets', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['doi'] == '10.1234/abc'
    assert row['arxivId'] == '2101.00001'
    assert row['publishedAt'] == '2021-06-01'
    assert row['citedByCount'] == 42
    assert row['venue'] == 'NeurIPS'
    assert row['accessLevel'] == 'fulltext-available'  # openAccessPdf is present
    assert row['dateSource'] == 'provider'
    assert row['sourceKind'] == 'paper'


def test_crossref_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'crossref.org/works': ok(CROSSREF_PAYLOAD)}))
    rows = academic.connector_search('crossref', 'paper', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['doi'] == '10.5555/xyz'
    assert row['title'] == 'A Crossref Paper'
    assert row['publishedAt'] == '2020-03-01'
    assert row['updatedAt'] == '2020-04-02'
    assert row['citedByCount'] == 7
    assert row['venue'] == 'Journal of Tests'
    assert row['accessLevel'] == 'abstract'
    assert row['dateSource'] == 'provider'


def test_arxiv_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'arxiv.org/api/query': (200, ARXIV_XML)}))
    rows = academic.connector_search('arxiv', 'electron', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['arxivId'] == '2101.00001'
    assert row['publishedAt'] == '2021-01-01'
    assert row['updatedAt'] == '2021-02-01'
    assert row['accessLevel'] == 'fulltext-available'
    assert row['sourceKind'] == 'preprint'
    assert row['venue'] == 'arXiv [cs.LG]'
    assert row['dateSource'] == 'provider'


def test_europepmc_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'europepmc/webservices/rest/search': ok(EPMC_PAYLOAD)}))
    rows = academic.connector_search('europepmc', 'covid', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['doi'] == '10.1000/epmc'
    assert row['publishedAt'] == '2019-05-05'
    assert row['citedByCount'] == 3
    assert row['accessLevel'] == 'fulltext-available'
    assert row['dateSource'] == 'provider'


def test_dblp_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'dblp.org/search/publ/api': ok(DBLP_PAYLOAD)}))
    rows = academic.connector_search('dblp', 'sigcomm', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['doi'] == '10.1145/123'
    assert row['publishedAt'] == '2018'
    assert row['venue'] == 'SIGCOMM'
    assert row['accessLevel'] == 'snippet'
    assert row['dateSource'] == 'provider'


def test_openreview_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'openreview.net/notes/search': ok(OPENREVIEW_PAYLOAD)}))
    rows = academic.connector_search('openreview', 'transformers', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['url'] == 'https://openreview.net/forum?id=or123'
    assert row['title'] == 'An OpenReview Paper'
    assert row['publishedAt'] == '2020-09-13'
    assert row['venue'] == 'ICLR 2021'
    assert row['accessLevel'] == 'abstract'
    assert row['dateSource'] == 'provider'


def test_opencitations_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'opencitations.net/index/coci': ok(OPENCITATIONS_PAYLOAD)}))
    rows = academic.connector_search('opencitations', '10.1000/orig', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['doi'] == '10.2000/citing1'          # incoming citation → the citing DOI
    assert row['publishedAt'] == '2022-02-02'
    assert row['accessLevel'] == 'snippet'
    assert row['dateSource'] == 'provider'


def test_github_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'api.github.com/search/repositories': ok(GITHUB_PAYLOAD)}))
    rows = academic.connector_search('github', 'lib', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['url'] == 'https://github.com/acme/lib'
    assert row['publishedAt'] == '2020-01-01'
    assert row['updatedAt'] == '2024-01-02'
    assert row['citedByCount'] == 123
    assert row['sourceKind'] == 'code'
    assert row['accessLevel'] == 'snippet'
    assert row['dateSource'] == 'provider'


def test_huggingface_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'huggingface.co/api/models': ok(HF_PAYLOAD)}))
    rows = academic.connector_search('huggingface', 'bert', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['url'] == 'https://huggingface.co/models/bert-base-uncased'
    assert row['publishedAt'] == '2019-01-01'
    assert row['updatedAt'] == '2023-03-01'
    assert row['citedByCount'] == 100
    assert row['sourceKind'] == 'model'
    assert row['accessLevel'] == 'snippet'
    assert row['dateSource'] == 'provider'


def test_openalex_parsing(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({'api.openalex.org/works': ok(OPENALEX_PAYLOAD)}))
    rows = academic.connector_search('openalex', 'widgets', count=5)
    assert len(rows) == 1
    row = rows[0]
    assert row['doi'] == '10.7777/oa'
    assert row['publishedAt'] == '2021-07-07'
    assert row['citedByCount'] == 9
    assert row['venue'] == 'Nature'
    assert row['accessLevel'] == 'fulltext-available'
    assert row['dateSource'] == 'provider'


CONNECTOR_CASES = {
    'semantic_scholar': ('paper/search', ok(S2_PAYLOAD), 'widgets'),
    'crossref': ('crossref.org/works', ok(CROSSREF_PAYLOAD), 'paper'),
    'arxiv': ('arxiv.org/api/query', (200, ARXIV_XML), 'electron'),
    'europepmc': ('europepmc/webservices/rest/search', ok(EPMC_PAYLOAD), 'covid'),
    'dblp': ('dblp.org/search/publ/api', ok(DBLP_PAYLOAD), 'sigcomm'),
    'openreview': ('openreview.net/notes/search', ok(OPENREVIEW_PAYLOAD), 'transformers'),
    'opencitations': ('opencitations.net/index/coci', ok(OPENCITATIONS_PAYLOAD), '10.1000/orig'),
    'github': ('api.github.com/search/repositories', ok(GITHUB_PAYLOAD), 'lib'),
    'huggingface': ('huggingface.co/api/models', ok(HF_PAYLOAD), 'bert'),
    'openalex': ('api.openalex.org/works', ok(OPENALEX_PAYLOAD), 'widgets'),
}


@pytest.mark.parametrize('name', sorted(CONNECTOR_CASES))
def test_every_row_carries_date_source_and_access_level(name, monkeypatch):
    needle, response, query = CONNECTOR_CASES[name]
    monkeypatch.setattr(academic, 'polite_get', fake_get({needle: response}))
    rows = academic.connector_search(name, query, count=5)
    assert rows, name
    for row in rows:
        assert set(row) >= {'url', 'title', 'snippet', 'provider', 'doi', 'arxivId',
                            'publishedAt', 'updatedAt', 'venue', 'citedByCount', 'dateSource',
                            'accessLevel', 'sourceKind'}
        assert row['dateSource'] in ('provider', 'page-meta', 'url', 'text', 'unknown')
        assert row['accessLevel'] in academic.ACCESS_LEVELS


def test_connector_search_is_offline_safe(monkeypatch):
    """Unknown name, empty query and provider failure must all yield ``[]``, never raise."""
    monkeypatch.setattr(academic, 'polite_get', fake_get({}))
    assert academic.connector_search('nope', 'x') == []
    assert academic.connector_search('crossref', '   ') == []

    def boom(host, url, **kwargs):
        raise RuntimeError('provider exploded')

    monkeypatch.setattr(academic, 'polite_get', boom)
    assert academic.connector_search('crossref', 'x') == []


def test_github_never_sends_a_token(monkeypatch):
    """#6077: a present GITHUB_TOKEN must be ignored — keyless only."""
    seen = {}

    def capture(host, url, **kwargs):
        seen['headers'] = kwargs.get('headers') or {}
        return ok(GITHUB_PAYLOAD)

    monkeypatch.setenv('GITHUB_TOKEN', 'super-secret')
    monkeypatch.setattr(academic, 'polite_get', capture)
    academic.connector_search('github', 'lib', count=3)
    assert 'Authorization' not in seen['headers']
    assert all('secret' not in str(value) for value in seen['headers'].values())


# ------------------------------------------------------------------------ politeness

def test_rate_limiter_spaces_calls_per_host(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(academic, '_CLOCK', fake.clock)
    monkeypatch.setattr(academic, '_SLEEP', fake.sleep)
    academic._reset_host_state()
    academic._reserve_slot('example.org', 1.0)
    academic._reserve_slot('example.org', 1.0)
    academic._reserve_slot('example.org', 1.0)
    assert fake.sleeps == [1.0, 1.0]
    # a different host has its own slot and never waits
    academic._reserve_slot('other.example', 1.0)
    assert fake.sleeps == [1.0, 1.0]


def test_polite_get_applies_the_rate_limit(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(academic, '_CLOCK', fake.clock)
    monkeypatch.setattr(academic, '_SLEEP', fake.sleep)
    monkeypatch.setattr(academic, '_urlopen', lambda req, timeout=None: FakeResponse(200, 'ok'))
    academic._reset_host_state()
    assert academic.polite_get('api.example.org', 'https://api.example.org/a', rps=1.0) == (200, 'ok')
    assert academic.polite_get('api.example.org', 'https://api.example.org/b', rps=1.0) == (200, 'ok')
    assert fake.sleeps == [1.0]


def test_polite_get_backs_off_on_429_then_succeeds(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(academic, '_CLOCK', fake.clock)
    monkeypatch.setattr(academic, '_SLEEP', fake.sleep)
    academic._reset_host_state()
    calls = {'n': 0}

    def flaky(req, timeout=None):
        calls['n'] += 1
        if calls['n'] < 3:
            raise urllib.error.HTTPError(req.full_url, 429, 'Too Many Requests', {}, None)
        return FakeResponse(200, '{"ok": true}')

    monkeypatch.setattr(academic, '_urlopen', flaky)
    status, body = academic.polite_get('api.example.org', 'https://api.example.org/x', rps=0)
    assert (status, body) == (200, '{"ok": true}')
    assert calls['n'] == 3
    assert fake.sleeps == [1.0, 2.0]  # 1/2/4 s backoff schedule, only two gaps in three tries


def test_polite_get_never_raises(monkeypatch):
    monkeypatch.setattr(academic, '_SLEEP', lambda seconds: None)
    monkeypatch.setattr(academic, '_CLOCK', lambda: 0.0)
    academic._reset_host_state()

    monkeypatch.setattr(academic, '_urlopen',
                        lambda req, timeout=None: (_ for _ in ()).throw(urllib.error.URLError('down')))
    assert academic.polite_get('h.example', 'https://h.example/x', rps=0) == (0, '')

    def refused(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 403, 'Forbidden', {}, None)

    monkeypatch.setattr(academic, '_urlopen', refused)
    assert academic.polite_get('h.example', 'https://h.example/x', rps=0) == (403, '')


# ------------------------------------------------------------------------------ fusion

def _fusion_payloads():
    s2 = {'data': [
        {'paperId': 'A', 'title': 'Paper A', 'externalIds': {'DOI': '10.1111/d1'}, 'year': 2020,
         'abstract': 'a'},
        {'paperId': 'B', 'title': 'Paper B', 'externalIds': {'DOI': '10.1111/d2'}, 'year': 2019,
         'abstract': 'b'},
    ]}
    crossref = {'message': {'items': [
        {'DOI': '10.1111/d1', 'title': ['Paper A'], 'issued': {'date-parts': [[2020]]}},
    ]}}
    arxiv = ('<feed><entry><id>http://arxiv.org/abs/2109.00002v1</id>'
             '<published>2021-09-01T00:00:00Z</published><title>Paper C</title>'
             '<summary>c</summary></entry></feed>')
    return {'paper/search': ok(s2), 'crossref.org/works': ok(crossref),
            'arxiv.org/api/query': (200, arxiv)}


def test_papers_search_fuses_legs_and_dedupes_by_doi(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get(_fusion_payloads()))
    rows = academic.papers_search(['quantum widget'], count=10)
    titles = [row['title'] for row in rows]
    assert titles == ['Paper A', 'Paper C', 'Paper B']   # A seen by two legs ranks first
    assert titles.count('Paper A') == 1                  # deduped by DOI
    assert rows[0]['doi'] == '10.1111/d1'
    assert rows[0]['provider'] == 'semantic_scholar'     # first leg that saw it wins
    assert rows[2]['sourceKind'] == 'paper'
    assert rows[1]['sourceKind'] == 'preprint'
    assert 'rrf' in rows[0]


def test_papers_search_dedupes_by_arxiv_id(monkeypatch):
    s2 = {'data': [{'paperId': 'X', 'title': 'Preprint One', 'externalIds': {'ArXiv': '2101.00001'},
                    'abstract': 'x'}]}
    arxiv = ('<feed><entry><id>http://arxiv.org/abs/2101.00001v1</id>'
             '<published>2021-01-01T00:00:00Z</published><title>Preprint One</title>'
             '<summary>x</summary></entry></feed>')
    monkeypatch.setattr(academic, 'polite_get', fake_get(
        {'paper/search': ok(s2), 'crossref.org/works': (200, '{"message":{"items":[]}}'),
         'arxiv.org/api/query': (200, arxiv)}))
    rows = academic.papers_search(['quantum widget'], count=10)
    assert len(rows) == 1
    assert rows[0]['arxivId'] == '2101.00001'


def test_papers_search_dedupes_by_title_fingerprint(monkeypatch):
    s2 = {'data': [{'paperId': 'T', 'title': 'The Same Title Here', 'abstract': 't'}]}
    crossref = {'message': {'items': [
        {'DOI': '', 'title': ['The same title here!'], 'issued': {'date-parts': [[2020]]}}]}}
    monkeypatch.setattr(academic, 'polite_get', fake_get(
        {'paper/search': ok(s2), 'crossref.org/works': ok(crossref),
         'arxiv.org/api/query': (200, '<feed></feed>')}))
    rows = academic.papers_search(['quantum widget'], count=10)
    assert len(rows) == 1


def test_papers_search_skips_failing_legs_and_needs_one_success(monkeypatch):
    mapping = {'paper/search': ok(S2_PAYLOAD), 'crossref.org/works': (429, ''),
               'arxiv.org/api/query': (503, '')}
    monkeypatch.setattr(academic, 'polite_get', fake_get(mapping))
    rows = academic.papers_search(['quantum widget'], count=10)
    assert [row['provider'] for row in rows] == ['semantic_scholar']

    monkeypatch.setattr(academic, 'polite_get', fake_get({}))
    assert academic.papers_search(['quantum widget'], count=10) == []
    assert academic.papers_search([], count=10) == []


# -------------------------------------------------------------------- citation chase

def _s2_citation_row(doi: str, arxiv: str = '') -> dict:
    return {'citingPaper': {'paperId': doi, 'title': f'Citing {doi}',
                            'externalIds': {'DOI': doi, 'ArXiv': arxiv}, 'abstract': 'c',
                            'publicationDate': '2022-01-01'}}


def test_citation_chase_forward_uses_semantic_scholar_first(monkeypatch):
    payload = {'data': [_s2_citation_row('10.1234/citing'), {'citingPaper': {'paperId': 'z'}}]}
    monkeypatch.setattr(academic, 'polite_get', fake_get({'/citations': ok(payload)}))
    rows = academic.citation_chase('10.1234/orig', direction='forward', limit=10)
    assert [row['doi'] for row in rows] == ['10.1234/citing']
    assert rows[0]['provider'] == 'semantic_scholar'
    assert rows[0]['dateSource'] == 'provider'


def test_citation_chase_backward_falls_back_to_crossref(monkeypatch):
    crossref = {'message': {'reference': [
        {'DOI': '10.9999/ref', 'article-title': 'Ref Title', 'year': '2015', 'journal-title': 'J'},
    ]}}
    monkeypatch.setattr(academic, 'polite_get', fake_get(
        {'semanticscholar.org': (429, ''),                      # main leg fails
         'opencitations.net': (200, '[]'),  # empty fallback
         'crossref.org/works/': ok(crossref)}))
    rows = academic.citation_chase('10.1234/orig', direction='backward', limit=10)
    assert [row['doi'] for row in rows] == ['10.9999/ref']
    assert rows[0]['provider'] == 'crossref'


def test_citation_chase_opencitations_direction_handling(monkeypatch):
    item = [{'citing': '10.2/citing', 'cited': '10.1234/orig', 'creation': '2021-03-03'}]

    def dispatch(host, url, **kwargs):
        if 'references' in url:
            return 200, json.dumps([{'citing': '10.2/citing', 'cited': '10.9999/referenced',
                                     'creation': '2020-01-01'}])
        return 200, json.dumps(item)

    monkeypatch.setattr(academic, 'polite_get', dispatch)
    fwd = academic.citation_chase('10.1234/orig', direction='forward', limit=5)
    assert [row['doi'] for row in fwd] == ['10.2/citing']       # forward → the citing DOI
    bwd = academic.citation_chase('10.1234/orig', direction='backward', limit=5)
    assert [row['doi'] for row in bwd] == ['10.9999/referenced']   # backward → the cited DOI


def test_citation_chase_rejects_bad_input(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({}))
    assert academic.citation_chase('10.1234/orig', direction='sideways') == []
    assert academic.citation_chase('', direction='forward') == []


# ------------------------------------------------------------------------ OpenAlex budget

def test_openalex_daily_budget_exhaustion_and_reset(monkeypatch):
    monkeypatch.setenv('BOXFOX_OPENALEX_DAILY_CALLS', '2')
    calls = {'n': 0}

    def fake(host, url, **kwargs):
        calls['n'] += 1
        return ok(OPENALEX_PAYLOAD)

    monkeypatch.setattr(academic, 'polite_get', fake)
    assert academic.daily_budget_left('openalex') == 2
    assert len(academic.connector_search('openalex', 'widgets', count=3)) == 1
    assert academic.daily_budget_left('openalex') == 1
    assert len(academic.connector_search('openalex', 'widgets', count=3)) == 1
    assert academic.daily_budget_left('openalex') == 0

    seen = calls['n']
    assert academic.connector_search('openalex', 'widgets', count=3) == []
    assert calls['n'] == seen  # exhausted ⇒ no HTTP at all

    monkeypatch.setattr(academic, '_today', lambda: '2026-09-26')
    assert academic.daily_budget_left('openalex') == 2


def test_unbudgeted_connectors_report_unlimited():
    assert academic.daily_budget_left('github') == academic._UNLIMITED
    assert academic.daily_budget_left('semantic_scholar') == academic._UNLIMITED


def test_openalex_budget_default_is_fifty(monkeypatch, tmp_path):
    monkeypatch.setenv('BOXFOX_AGENT_DATA_DIR', str(tmp_path / 'fresh'))
    assert academic.daily_budget_left('openalex') == 50


def test_bare_identifier_strips_the_openalex_wrapper():
    assert academic._bare_identifier('https://openalex.org/W123456') == 'W123456'
    assert academic._bare_identifier('http://www.openalex.org/W123456/') == 'W123456/'
    assert academic._bare_identifier('openalex:W123456') == 'W123456'
    assert academic._bare_identifier('  W123456  ') == 'W123456'
    assert academic._bare_identifier('') == ''
    # DOI trần đi qua nguyên vẹn để `_norm_doi` xử lý ở tầng dưới.
    assert academic._s2_ref('https://doi.org/10.1234/abc') == 'DOI:10.1234/abc'
    assert academic._s2_ref('https://openalex.org/W123456') == ''  # S2 không giải một id OpenAlex


def test_citation_chase_accepts_an_openalex_url_identifier(monkeypatch):
    payload = {'results': [{'id': 'https://openalex.org/W999', 'display_name': 'Citing work',
                            'publication_date': '2023-04-05',
                            'doi': 'https://doi.org/10.5/citing'}]}
    seen: dict[str, str] = {}

    def dispatch(host, url, **kwargs):
        if 'api.openalex.org' in str(host):
            seen['url'] = url
            return ok(payload)
        return 200, '[]'

    monkeypatch.setattr(academic, 'polite_get', dispatch)
    rows = academic.citation_chase('https://openalex.org/W123456', direction='forward', limit=5)
    # Id đi vào chân OpenAlex ở dạng TRẦN (`W…`), không phải nguyên URL.
    assert 'filter=cites' in seen['url'] and 'W123456' in seen['url']
    assert 'openalex.org/W123456' not in seen['url']
    assert [row['doi'] for row in rows] == ['10.5/citing']


def test_citation_chase_still_rejects_an_empty_identifier(monkeypatch):
    monkeypatch.setattr(academic, 'polite_get', fake_get({}))
    assert academic.citation_chase('   ', direction='forward') == []
