"""Keyless academic + code connectors used by the research search layer (P0b, contract §4).

Design source: ``/code/.plans/v2-research-mode-overhaul.md`` §5.4.3 (keyless source table),
§5.4.1 step 2/8 (10 s timeouts, provider date metadata) and the frozen interface contract
``/code/.plans/p0-interfaces.md`` §4.

Rules this module lives by (all frozen):

* **No API keys anywhere** (#6077). ``S2_API_KEY`` / ``GITHUB_TOKEN`` / ``OPENALEX_API_KEY``
  are deliberately *not read* even when present: the keyless budget is the whole budget.
* **No new dependency** — ``urllib`` (synchronous) only, reusing the ``web.py`` idioms
  (``USER_AGENT``, bounded snippets, ``system_log``) but staying self-contained so it does
  not import the heavy ``web`` module at import time.
* **A failing leg never escapes**: every public call returns ``[]`` and logs through
  ``agentbox.observability.system_log``.
* **Polite, per host, process-wide**: ``polite_get`` serialises calls per hostname and backs
  off 1/2/4 s on 429/503 with at most ``retries`` attempts (3 by default).

Normalised row shape (contract §4 / plan §5.4.4): ``url, title, snippet, provider, doi,
arxivId, publishedAt, updatedAt, venue, citedByCount, dateSource, accessLevel, sourceKind``.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..observability.system_log import system_log

# --------------------------------------------------------------------------- constants

ACCESS_LEVELS = ('snippet', 'abstract', 'fulltext-available', 'fulltext-read')

USER_AGENT = 'BoxFoxAgent/1.0 (host-side research tool; +https://boxfox.local)'
MAX_SNIPPET = 400
MAX_BODY_BYTES = 4_000_000
RRF_K = 60
_BACKOFF = (1.0, 2.0, 4.0)
_UNLIMITED = 10 ** 9
_BUDGET_FILE = 'academic_budget.json'

# The caller-supplied timeout default is frozen at 10.0; connectors resolve the live value
# through ``_timeout()`` so a peer can add ``ACADEMIC_TIMEOUT_SECONDS`` to ``limits.py``
# without this module breaking (contract §6, defensive import).
try:  # pragma: no cover - exercised by whichever limits.py the branch carries
    from .limits import ACADEMIC_TIMEOUT_SECONDS as _ACADEMIC_TIMEOUT_DEFAULT  # type: ignore
except Exception:  # pragma: no cover
    _ACADEMIC_TIMEOUT_DEFAULT = 10.0
try:  # pragma: no cover
    from .limits import OPENALEX_DAILY_CALLS_DEFAULT as _OPENALEX_CALLS_DEFAULT  # type: ignore
except Exception:  # pragma: no cover
    _OPENALEX_CALLS_DEFAULT = 50

_S2_BASE = 'https://api.semanticscholar.org/graph/v1'
_CROSSREF_BASE = 'https://api.crossref.org'
_ARXIV_QUERY = 'https://export.arxiv.org/api/query'
_EPMC_BASE = 'https://www.ebi.ac.uk/europepmc/webservices/rest'
_DBLP_QUERY = 'https://dblp.org/search/publ/api'
_OPENREVIEW_BASE = 'https://api2.openreview.net'
_OPENCI_BASE = 'https://opencitations.net/index/coci/api/v1'
_OPENALEX_BASE = 'https://api.openalex.org'
_GITHUB_BASE = 'https://api.github.com'
_HF_BASE = 'https://huggingface.co/api'

_MAILTO_DEFAULT = 'boxfox-agent@example.invalid'
_S2_FIELDS = ('title,abstract,url,externalIds,venue,year,citationCount,publicationDate,'
              'openAccessPdf,authors')
_OPENALEX_SELECT = ('id,doi,display_name,publication_date,publication_year,cited_by_count,'
                    'primary_location,best_oa_location,type')

_WHITESPACE = re.compile(r'\s+')
_TAGS = re.compile(r'<[^>]+>')
_DOI_RE = re.compile(r'^10\.\d{4,9}/\S+$', re.I)
_ARXIV_NEW_RE = re.compile(r'(\d{4}\.\d{4,5})(v\d+)?$')
_ARXIV_OLD_RE = re.compile(r'([a-z-]+(?:\.[A-Z]{2})?/\d{7})(v\d+)?$')
_S2_ID_RE = re.compile(r'^[0-9a-f]{40}$', re.I)
_WORK_ID_RE = re.compile(r'^[Ww]\d+$')
_WORD = re.compile(r'[a-z0-9]+')


class _Retryable(Exception):
    """Internal signal: the host asked us to come back later (429/503) or dropped the line."""

    def __init__(self, status: int = 0, message: str = ''):
        super().__init__(message or f'HTTP {status}')
        self.status = int(status or 0)


# ------------------------------------------------------------------------- logging

def _log(event: str, *, level: str = 'warn', message: str | None = None, **data) -> None:
    """Best-effort system log. Never carries query text — only a provider name and a code."""
    try:
        system_log.write(event, level=level, message=message, **data)
    except Exception:  # pragma: no cover - the log must never break a call
        pass


def _log_failure(provider: str, reason: str) -> None:
    _log('academic.connector_failed', provider=provider, code=reason,
         message=f'{provider}: {reason}')


# ------------------------------------------------------------------------ text utils

def _bounded(value, limit: int = MAX_SNIPPET) -> str:
    """Collapse whitespace, drop tags, cap length. Same idea as ``web._bounded_snippet``."""
    text = _TAGS.sub(' ', str(value or ''))
    text = _WHITESPACE.sub(' ', text).strip()
    return text[:limit]


def _clean(value) -> str:
    return _WHITESPACE.sub(' ', str(value or '')).strip()


def _terms(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item or '').strip()]
    if value in (None, ''):
        return []
    return [str(value)]


def _norm_doi(value) -> str:
    """A bare, lower-case DOI: strips ``https://doi.org/`` / ``doi:`` and the trailing slash."""
    text = _clean(value)
    if not text:
        return ''
    low = text.lower()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'doi:'):
        if low.startswith(prefix):
            text = text[len(prefix):]
            low = text.lower()
            break
    return text.rstrip('/').strip().lower()


def _looks_doi(value: str) -> bool:
    return bool(_DOI_RE.match(_clean(value).rstrip('/')))


def _norm_arxiv(value) -> str:
    """A bare arXiv id without version suffix or URL wrapper."""
    text = _clean(value)
    if not text:
        return ''
    text = re.sub(r'^https?://(www\.)?arxiv\.org/(abs|pdf)/', '', text, flags=re.I)
    text = re.sub(r'\.pdf$', '', text, flags=re.I)
    match = _ARXIV_NEW_RE.search(text) or _ARXIV_OLD_RE.search(text)
    if match:
        return match.group(1)
    return text.split('v')[0] if re.match(r'^\d{4}\.\d{4,5}', text) else text


def _looks_arxiv(value: str) -> bool:
    text = _clean(value)
    if text.lower().startswith('arxiv:'):
        text = text.split(':', 1)[1]
    text = re.sub(r'^https?://(www\.)?arxiv\.org/(abs|pdf)/', '', text, flags=re.I)
    return bool(_ARXIV_NEW_RE.search(text) or _ARXIV_OLD_RE.search(text))


def _date_only(value) -> str:
    """``YYYY`` / ``YYYY-MM`` / ``YYYY-MM-DD`` from an ISO-ish string, else ``''``."""
    text = _clean(value)
    match = re.match(r'(\d{4})-(\d{2})-(\d{2})', text)
    if match:
        return match.group(0)
    match = re.match(r'(\d{4})-(\d{2})', text)
    if match:
        return match.group(1)
    match = re.match(r'(\d{4})', text)
    if match:
        return match.group(1)
    return ''


def _date_parts(node) -> str:
    """Crossref ``{"date-parts":[[Y,M,D]]}`` / ``{"date-time":"…"}`` → ``YYYY[-MM[-DD]]``."""
    if not isinstance(node, dict):
        return ''
    parts = node.get('date-parts')
    if isinstance(parts, list) and parts and isinstance(parts[0], list):
        nums: list[int] = []
        for value in parts[0][:3]:
            try:
                nums.append(int(value))
            except (TypeError, ValueError):
                break
        if nums:
            if len(nums) >= 3:
                return f'{nums[0]:04d}-{nums[1]:02d}-{nums[2]:02d}'
            if len(nums) == 2:
                return f'{nums[0]:04d}-{nums[1]:02d}'
            return f'{nums[0]:04d}'
    return _date_only(node.get('date-time'))


def _epoch_ms_to_date(value) -> str:
    try:
        seconds = int(value) / 1000.0
    except (TypeError, ValueError):
        return ''
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return ''


def _int_or_zero(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _hostname(url: str) -> str:
    return (urllib.parse.urlsplit(str(url or '')).hostname or '').lower()


# ------------------------------------------------------------------- polite transport

_STATE_LOCK = threading.Lock()
_HOST_STATE: dict[str, dict] = {}
_CLOCK = time.monotonic      # tests monkeypatch these two for a fast, deterministic clock
_SLEEP = time.sleep
_urlopen = urllib.request.urlopen


def _reset_host_state() -> None:
    """Test seam: forget every per-host slot and timestamp."""
    with _STATE_LOCK:
        _HOST_STATE.clear()


def _host_state(host: str) -> dict:
    with _STATE_LOCK:
        state = _HOST_STATE.get(host)
        if state is None:
            state = {'lock': threading.Lock(), 'next_at': 0.0}
            _HOST_STATE[host] = state
        return state


def _reserve_slot(host: str, rps: float) -> None:
    """Block until this process is allowed to speak to ``host`` again.

    The slot is keyed by hostname (NOT by call), so two connectors pointing at the same
    domain queue behind one another. Sleeping happens while holding the per-host lock, which
    is what serialises the calls; ``rps <= 0`` disables the limiter.
    """
    if not host or not rps or float(rps) <= 0:
        return
    interval = 1.0 / float(rps)
    state = _host_state(host)
    with state['lock']:
        now = _CLOCK()
        if now < state['next_at']:
            _SLEEP(state['next_at'] - now)
            now = _CLOCK()
        state['next_at'] = max(now, state['next_at']) + interval


def _request(url: str, headers: dict | None, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(str(url), method='GET')
    request.add_header('User-Agent', USER_AGENT)
    request.add_header('Accept', 'application/json, application/atom+xml;q=0.9, */*;q=0.5')
    # Identity: we do not inflate here, and none of these APIs need gzip to answer.
    request.add_header('Accept-Encoding', 'identity')
    for key, value in (headers or {}).items():
        request.add_header(str(key), str(value))
    try:
        with _urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed public hosts
            status = int(getattr(response, 'status', 200) or 200)
            raw = response.read(MAX_BODY_BYTES)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, 'code', 0) or 0)
        if code in (429, 503):
            raise _Retryable(code) from exc
        return code, ''
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise _Retryable(0, type(exc).__name__) from exc
    text = raw.decode('utf-8', 'replace') if isinstance(raw, (bytes, bytearray)) else str(raw or '')
    if status in (429, 503):
        raise _Retryable(status)
    return status, text


def polite_get(host: str, url: str, *, rps: float = 1.0, headers: dict | None = None,
               timeout: float = 10.0, retries: int = 3) -> tuple[int, str]:
    """Rate-limited GET. Returns ``(status, body)`` and NEVER raises past the caller.

    Per-host politeness is process-wide (see ``_reserve_slot``). On 429/503 (and dropped
    connections) it backs off ``1, 2, 4`` seconds and makes at most ``retries`` attempts
    (3 by default). When every attempt fails it returns ``(status, '')`` — status ``0`` for a
    transport failure — after logging through ``system_log``.
    """
    hostname = _clean(host).lower() or _hostname(url)
    attempts = max(1, int(retries or 1))
    last_status = 0
    for attempt in range(attempts):
        if attempt:
            _SLEEP(_BACKOFF[min(attempt - 1, len(_BACKOFF) - 1)])
        _reserve_slot(hostname, rps)
        try:
            return _request(url, headers, float(timeout))
        except _Retryable as exc:
            last_status = exc.status
            _log_failure(hostname, f'HTTP {exc.status}' if exc.status else str(exc))
        except Exception as exc:  # pragma: no cover - defensive: nothing may escape
            _log_failure(hostname, type(exc).__name__)
            return 0, ''
    return last_status, ''


def _timeout(options: dict | None = None) -> float:
    options = options or {}
    raw = options.get('timeout')
    if raw is not None:
        try:
            return max(1.0, float(raw))
        except (TypeError, ValueError):
            pass
    try:
        return float(_ACADEMIC_TIMEOUT_DEFAULT)
    except (TypeError, ValueError):  # pragma: no cover
        return 10.0


# ------------------------------------------------------------------ normalised rows

def _row(*, url: str = '', title: str = '', snippet: str = '', provider: str = '', doi: str = '',
         arxivId: str = '', publishedAt: str = '', updatedAt: str = '', venue: str = '',
         citedByCount: int = 0, dateSource: str = 'unknown', accessLevel: str = 'snippet',
         sourceKind: str = 'paper') -> dict:
    return {
        'url': str(url or '').strip(),
        'title': _bounded(title),
        'snippet': _bounded(snippet),
        'provider': str(provider or '').strip(),
        'doi': _norm_doi(doi),
        'arxivId': _norm_arxiv(arxivId),
        'publishedAt': str(publishedAt or '').strip(),
        'updatedAt': str(updatedAt or '').strip(),
        'venue': _clean(venue),
        'citedByCount': _int_or_zero(citedByCount),
        'dateSource': dateSource if dateSource in ('provider', 'page-meta', 'url', 'text', 'unknown') else 'unknown',
        'accessLevel': accessLevel if accessLevel in ACCESS_LEVELS else 'snippet',
        'sourceKind': str(sourceKind or 'paper').strip() or 'paper',
    }


def _access_level(*, fulltext: bool = False, abstract: str = '') -> str:
    if fulltext:
        return 'fulltext-available'
    return 'abstract' if _clean(abstract) else 'snippet'


def _date_source(published: str, updated: str = '') -> str:
    return 'provider' if (published or updated) else 'unknown'


# ------------------------------------------------------------------------- parsers

def _parse_s2_paper(item: dict, provider: str = 'semantic_scholar', source_kind: str = 'paper') -> dict | None:
    if not isinstance(item, dict):
        return None
    external = item.get('externalIds') or {}
    if not isinstance(external, dict):
        external = {}
    doi = _norm_doi(external.get('DOI'))
    arxiv = _norm_arxiv(external.get('ArXiv'))
    title = _clean(item.get('title'))
    url = _clean(item.get('url'))
    if not url:
        url = f'https://doi.org/{doi}' if doi else (f'https://arxiv.org/abs/{arxiv}' if arxiv else '')
    if not (title or url or doi or arxiv):
        return None
    abstract = item.get('abstract') or ''
    pdf = item.get('openAccessPdf') or {}
    published = _date_only(item.get('publicationDate')) or _date_only(item.get('year'))
    return _row(url=url, title=title, snippet=abstract, provider=provider, doi=doi, arxivId=arxiv,
                publishedAt=published, updatedAt='', venue=item.get('venue'),
                citedByCount=item.get('citationCount'), dateSource=_date_source(published),
                accessLevel=_access_level(fulltext=bool(pdf.get('url') if isinstance(pdf, dict) else pdf),
                                          abstract=abstract),
                sourceKind=source_kind)


def _parse_crossref_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    doi = _norm_doi(item.get('DOI'))
    title = _clean(' '.join(_terms(item.get('title'))))
    url = _clean(item.get('URL')) or (f'https://doi.org/{doi}' if doi else '')
    if not (doi or title or url):
        return None
    abstract = item.get('abstract') or ''
    published = _date_parts(item.get('published')) or _date_parts(item.get('issued')) \
        or _date_parts(item.get('created'))
    updated = _date_parts(item.get('indexed')) or _date_parts(item.get('created'))
    venue = _clean(' '.join(_terms(item.get('container-title'))))
    return _row(url=url, title=title or doi, snippet=abstract, provider='crossref', doi=doi,
                publishedAt=published, updatedAt=updated, venue=venue,
                citedByCount=item.get('is-referenced-by-count'),
                dateSource=_date_source(published, updated),
                accessLevel=_access_level(abstract=abstract),
                sourceKind='paper')


_ARXIV_ENTRY = re.compile(r'(?s)<entry>(.*?)</entry>')
_ARXIV_TITLE = re.compile(r'(?s)<title>(.*?)</title>')
_ARXIV_ID = re.compile(r'(?s)<id>(.*?)</id>')
_ARXIV_PUBLISHED = re.compile(r'<published>(.*?)</published>')
_ARXIV_UPDATED = re.compile(r'<updated>(.*?)</updated>')
_ARXIV_SUMMARY = re.compile(r'(?s)<summary>(.*?)</summary>')
_ARXIV_CATEGORY = re.compile(r'<arxiv:primary_category[^>]*term="([^"]+)"')


def _parse_arxiv_entry(block: str) -> dict | None:
    found_id = _ARXIV_ID.search(block)
    raw_id = _clean(found_id.group(1)) if found_id else ''
    if not raw_id:
        return None
    arxiv = _norm_arxiv(raw_id)
    published = _date_only(_clean(_ARXIV_PUBLISHED.search(block).group(1)) if _ARXIV_PUBLISHED.search(block) else '')
    updated = _date_only(_clean(_ARXIV_UPDATED.search(block).group(1)) if _ARXIV_UPDATED.search(block) else '')
    found_title = _ARXIV_TITLE.search(block)
    category = _ARXIV_CATEGORY.search(block)
    venue = 'arXiv' + (f' [{category.group(1)}]' if category else '')
    return _row(url=f'https://arxiv.org/abs/{arxiv}', title=_clean(found_title.group(1)) if found_title else arxiv,
                snippet=_clean(_ARXIV_SUMMARY.search(block).group(1)) if _ARXIV_SUMMARY.search(block) else '',
                provider='arxiv', arxivId=arxiv, publishedAt=published, updatedAt=updated,
                venue=venue, dateSource=_date_source(published, updated),
                accessLevel='fulltext-available', sourceKind='preprint')


def _parse_europepmc_item(hit: dict) -> dict | None:
    if not isinstance(hit, dict):
        return None
    raw_doi = hit.get('doi')
    doi_list = raw_doi if isinstance(raw_doi, list) else [raw_doi]
    doi = ''
    for candidate in doi_list:
        if _norm_doi(candidate):
            doi = _norm_doi(candidate)
            break
    pmid = _clean(hit.get('pmid'))
    pmcid = _clean(hit.get('pmcid'))
    if doi:
        url = f'https://doi.org/{doi}'
    elif pmid:
        url = f'https://europepmc.org/article/MED/{pmid}'
    elif pmcid:
        url = f'https://europepmc.org/article/PMC/{pmcid}'
    else:
        url = ''
    title = _clean(hit.get('title'))
    if not (title or url):
        return None
    abstract = hit.get('abstractText') or ''
    published = _date_only(hit.get('firstPublicationDate')) or _date_only(hit.get('pubYear'))
    open_access = str(hit.get('isOpenAccess') or '').strip().upper() == 'Y'
    return _row(url=url, title=title, snippet=abstract, provider='europepmc', doi=doi,
                publishedAt=published, updatedAt='', venue=hit.get('journalTitle'),
                citedByCount=hit.get('citedByCount'), dateSource=_date_source(published),
                accessLevel=_access_level(fulltext=bool(open_access and pmcid), abstract=abstract),
                sourceKind='paper')


def _parse_dblp_hit(hit: dict) -> dict | None:
    if not isinstance(hit, dict):
        return None
    info = hit.get('info') or {}
    if not isinstance(info, dict):
        return None
    title = _clean(info.get('title'))
    doi = _norm_doi(info.get('doi'))
    ee = _clean(info.get('ee'))
    key = _clean(info.get('key'))
    url = ee or (f'https://doi.org/{doi}' if doi else (f'https://dblp.org/rec/{key}.html' if key else ''))
    if not (title or url):
        return None
    arxiv = _norm_arxiv(ee) if _looks_arxiv(ee) else ''
    published = _date_only(info.get('year'))
    authors = info.get('authors') or {}
    names = _terms((authors or {}).get('author') if isinstance(authors, dict) else authors)
    snippet = ' · '.join(part for part in (_clean(info.get('venue')), _clean(info.get('year')),
                                           ', '.join(names[:3])) if part)
    return _row(url=url, title=title, snippet=snippet, provider='dblp', doi=doi, arxivId=arxiv,
                publishedAt=published, updatedAt='', venue=info.get('venue'),
                dateSource=_date_source(published), accessLevel='snippet', sourceKind='paper')


def _openreview_value(content: dict, name: str) -> str:
    value = (content or {}).get(name) or ''
    if isinstance(value, dict):
        value = value.get('value') or ''
    if isinstance(value, list):
        value = ', '.join(str(item) for item in value)
    return _clean(value)


def _parse_openreview_note(note: dict) -> dict | None:
    if not isinstance(note, dict):
        return None
    ident = _clean(note.get('id'))
    content = note.get('content') or {}
    if not isinstance(content, dict):
        content = {}
    title = _openreview_value(content, 'title')
    if not (ident or title):
        return None
    published = _epoch_ms_to_date(note.get('pdate') or note.get('cdate'))
    venue = _openreview_value(content, 'venue') or _openreview_value(content, 'venueid')
    return _row(url=f'https://openreview.net/forum?id={urllib.parse.quote(ident)}' if ident else '',
                title=title or ident, snippet=_openreview_value(content, 'abstract'),
                provider='openreview', publishedAt=published, updatedAt='', venue=venue,
                dateSource=_date_source(published),
                accessLevel=_access_level(abstract=_openreview_value(content, 'abstract')),
                sourceKind='paper')


def _parse_opencitations_item(item: dict, *, direction: str, cited: str) -> dict | None:
    """COCI returns ``[{"citing": …, "cited": …, "creation": …}]`` (one row per citation)."""
    if not isinstance(item, dict):
        return None
    citing = _norm_doi(item.get('citing'))
    target = _norm_doi(item.get('cited')) or _norm_doi(cited)
    picked = target if direction == 'backward' else citing
    if not picked:
        return None
    published = _date_only(item.get('creation'))
    other = citing if direction == 'backward' else target
    return _row(url=f'https://doi.org/{picked}', title=picked, provider='opencitations', doi=picked,
                snippet=f'OpenCitations · {picked} ↔ {other}' if other else f'OpenCitations · {picked}',
                publishedAt=published, updatedAt='', dateSource=_date_source(published),
                accessLevel='snippet', sourceKind='paper')


def _parse_github_repo(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    url = _clean(item.get('html_url'))
    name = _clean(item.get('full_name'))
    if not (url or name):
        return None
    license_id = ((item.get('license') or {}) or {}).get('spdx_id') if isinstance(item.get('license'), dict) else ''
    published = _date_only(item.get('created_at'))
    updated = _date_only(item.get('pushed_at')) or _date_only(item.get('updated_at'))
    description = _clean(item.get('description'))
    snippet = ' — '.join(part for part in (
        description,
        f"{_int_or_zero(item.get('stargazers_count'))} stars",
        _clean(item.get('language')),
        f'license {license_id}' if license_id else '',
    ) if part)
    return _row(url=url or name, title=name or url, snippet=snippet, provider='github',
                publishedAt=published, updatedAt=updated,
                venue=_clean(item.get('language')), citedByCount=item.get('stargazers_count'),
                dateSource=_date_source(published, updated), accessLevel='snippet',
                sourceKind='code')


def _parse_huggingface_item(item: dict, *, kind: str = 'model') -> dict | None:
    if not isinstance(item, dict):
        return None
    ident = _clean(item.get('modelId') or item.get('id'))
    if not ident:
        return None
    base = 'datasets' if kind == 'dataset' else 'models'
    published = _date_only(item.get('createdAt'))
    updated = _date_only(item.get('lastModified'))
    tags = ', '.join(_terms(item.get('tags'))[:3])
    snippet = ' — '.join(part for part in (
        _clean(item.get('pipeline_tag')), tags,
        f"{_int_or_zero(item.get('likes'))} likes",
        f"{_int_or_zero(item.get('downloads'))} downloads",
    ) if part)
    return _row(url=f'https://huggingface.co/{base}/{ident}', title=ident, snippet=snippet,
                provider='huggingface', publishedAt=published, updatedAt=updated,
                venue=_clean(item.get('pipeline_tag')), citedByCount=item.get('likes'),
                dateSource=_date_source(published, updated), accessLevel='snippet',
                sourceKind='dataset' if kind == 'dataset' else 'model')


def _parse_openalex_item(item: dict) -> dict | None:
    if not isinstance(item, dict):
        return None
    doi = _norm_doi(item.get('doi'))
    title = _clean(item.get('title') or item.get('display_name'))
    url = f'https://doi.org/{doi}' if doi else _clean(item.get('id'))
    if not (title or url or doi):
        return None
    venue = ((item.get('primary_location') or {}).get('source') or {}).get('display_name') \
        if isinstance(item.get('primary_location'), dict) else ''
    published = _date_only(item.get('publication_date')) or _date_only(item.get('publication_year'))
    fulltext = bool(item.get('best_oa_location'))
    ids = item.get('ids') or {}
    arxiv = _norm_arxiv((ids or {}).get('arxiv')) if isinstance(ids, dict) else ''
    return _row(url=url, title=title, snippet=f"{_clean(venue)} · {published}".strip(' ·'),
                provider='openalex', doi=doi, arxivId=arxiv, publishedAt=published, updatedAt='',
                venue=venue, citedByCount=item.get('cited_by_count'),
                dateSource=_date_source(published),
                accessLevel=_access_level(fulltext=fulltext), sourceKind='paper')


# ------------------------------------------------------------------ connector search

def _payload(body: str):
    try:
        return json.loads(body or '')
    except (ValueError, TypeError):
        return None


def _search_semantic_scholar(query: str, count: int, options: dict) -> list[dict]:
    params = {'query': query, 'limit': count, 'fields': _S2_FIELDS}
    if options.get('year'):
        params['year'] = options['year']
    url = _S2_BASE + '/paper/search?' + urllib.parse.urlencode(params)
    status, body = polite_get('api.semanticscholar.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    if not isinstance(payload, dict):
        return []
    rows = []
    for item in (payload.get('data') or [])[:count]:
        row = _parse_s2_paper(item)
        if row and (row['url'] or row['doi'] or row['title']):
            rows.append(row)
    return rows


def _search_crossref(query: str, count: int, options: dict) -> list[dict]:
    mailto = _clean(options.get('mailto')) or _MAILTO_DEFAULT
    params = {'query.bibliographic': query, 'rows': count, 'mailto': mailto}
    if options.get('year'):
        params['filter'] = f'from-pub-date:{options["year"]}-01-01'
    url = _CROSSREF_BASE + '/works?' + urllib.parse.urlencode(params)
    status, body = polite_get('api.crossref.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    items = ((payload or {}).get('message') or {}).get('items') if isinstance(payload, dict) else None
    rows = []
    for item in (items or [])[:count]:
        row = _parse_crossref_item(item)
        if row:
            rows.append(row)
    return rows


def _search_arxiv(query: str, count: int, options: dict) -> list[dict]:
    params = {'search_query': f'all:{query}', 'max_results': count,
              'sortBy': 'submittedDate', 'sortOrder': 'descending'}
    url = _ARXIV_QUERY + '?' + urllib.parse.urlencode(params)
    status, body = polite_get('export.arxiv.org', url, rps=1.0, timeout=_timeout(options),
                              headers={'Accept': 'application/atom+xml'})
    if status != 200 or not body:
        return []
    rows = []
    for block in _ARXIV_ENTRY.findall(body)[:count]:
        row = _parse_arxiv_entry(block)
        if row:
            rows.append(row)
    return rows


def _bmc_hint(text: str) -> bool:
    low = text.lower()
    return any(token in low for token in ('bio', 'med', 'medical', 'clinical', 'health', 'gene',
                                          'protein', 'patient', 'covid', 'drug', 'disease',
                                          'pubmed', 'europepmc', 'neuro', 'cell'))


def _search_europepmc(query: str, count: int, options: dict) -> list[dict]:
    params = {'query': query, 'format': 'json', 'pageSize': count, 'resultType': 'core'}
    url = _EPMC_BASE + '/search?' + urllib.parse.urlencode(params)
    status, body = polite_get('www.ebi.ac.uk', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    hits = ((payload or {}).get('resultList') or {}).get('result') if isinstance(payload, dict) else None
    rows = []
    for hit in (hits or [])[:count]:
        row = _parse_europepmc_item(hit)
        if row:
            rows.append(row)
    return rows


def _search_dblp(query: str, count: int, options: dict) -> list[dict]:
    params = {'q': query, 'format': 'json', 'h': count, 'f': 0}
    url = _DBLP_QUERY + '?' + urllib.parse.urlencode(params)
    status, body = polite_get('dblp.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    hits = ((payload or {}).get('result') or {}).get('hits') if isinstance(payload, dict) else None
    raw = (hits or {}).get('hit') if isinstance(hits, dict) else None
    if isinstance(raw, dict):
        raw = [raw]
    rows = []
    for hit in (raw or [])[:count]:
        row = _parse_dblp_hit(hit)
        if row:
            rows.append(row)
    return rows


def _search_openreview(query: str, count: int, options: dict) -> list[dict]:
    params = {'term': query, 'source': 'forum', 'limit': count,
              'offset': int(options.get('cursor') or 0), 'count': 'true'}
    url = _OPENREVIEW_BASE + '/notes/search?' + urllib.parse.urlencode(params)
    status, body = polite_get('api2.openreview.net', url, rps=1.0, timeout=_timeout(options),
                              headers={'Accept': 'application/json'})
    if status != 200:
        return []
    payload = _payload(body)
    notes = (payload or {}).get('notes') if isinstance(payload, dict) else None
    rows = []
    for note in (notes or [])[:count]:
        row = _parse_openreview_note(note)
        if row:
            rows.append(row)
    return rows


def _search_opencitations(query: str, count: int, options: dict) -> list[dict]:
    """COCI has no full-text search: the query is a DOI and we return its incoming citations."""
    doi = _norm_doi(query)
    if not _looks_doi(doi):
        return []
    url = f'{_OPENCI_BASE}/citations/{urllib.parse.quote(doi)}'
    status, body = polite_get('opencitations.net', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload[:count]:
        row = _parse_opencitations_item(item, direction='forward', cited=doi)
        if row:
            rows.append(row)
    return rows


def _search_github(query: str, count: int, options: dict) -> list[dict]:
    # #6077: never send GITHUB_TOKEN even when it is exported — keyless only.
    params = {'q': query, 'per_page': count}
    url = _GITHUB_BASE + '/search/repositories?' + urllib.parse.urlencode(params)
    status, body = polite_get('api.github.com', url, rps=1.0, timeout=_timeout(options),
                              headers={'Accept': 'application/vnd.github+json'})
    if status != 200:
        return []
    payload = _payload(body)
    items = (payload or {}).get('items') if isinstance(payload, dict) else None
    rows = []
    for item in (items or [])[:count]:
        row = _parse_github_repo(item)
        if row:
            rows.append(row)
    return rows


def _search_huggingface(query: str, count: int, options: dict) -> list[dict]:
    kind = 'dataset' if str(options.get('hfKind') or '').lower() == 'dataset' else 'model'
    params = {'search': query, 'limit': count, 'full': 'false'}
    url = f'{_HF_BASE}/{kind + "s"}?' + urllib.parse.urlencode(params)
    status, body = polite_get('huggingface.co', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload[:count]:
        row = _parse_huggingface_item(item, kind=kind)
        if row:
            rows.append(row)
    return rows


def _search_openalex(query: str, count: int, options: dict) -> list[dict]:
    if not _use_budget('openalex'):
        return []
    params = {'search': query, 'per-page': count, 'select': _OPENALEX_SELECT}
    if options.get('year'):
        params['filter'] = f'from_publication_date:{options["year"]}-01-01'
    url = _OPENALEX_BASE + '/works?' + urllib.parse.urlencode(params)
    status, body = polite_get('api.openalex.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    results = (payload or {}).get('results') if isinstance(payload, dict) else None
    rows = []
    for item in (results or [])[:count]:
        row = _parse_openalex_item(item)
        if row:
            rows.append(row)
    return rows


_SEARCHERS = {
    'semantic_scholar': _search_semantic_scholar,
    'crossref': _search_crossref,
    'arxiv': _search_arxiv,
    'europepmc': _search_europepmc,
    'dblp': _search_dblp,
    'openreview': _search_openreview,
    'opencitations': _search_opencitations,
    'github': _search_github,
    'huggingface': _search_huggingface,
    'openalex': _search_openalex,
}


def connectors() -> dict[str, dict]:
    """Metadata for every keyless connector: rate, whether it needs a key, and its role."""
    return {
        'semantic_scholar': {'rps': 1.0, 'needsKey': False, 'host': 'api.semanticscholar.org',
                             'kind': 'papers', 'sourceKind': 'paper', 'main': True,
                             'timeout': _timeout()},
        'crossref': {'rps': 1.0, 'needsKey': False, 'host': 'api.crossref.org',
                     'kind': 'papers', 'sourceKind': 'paper', 'main': True, 'timeout': _timeout()},
        'arxiv': {'rps': 1.0, 'needsKey': False, 'host': 'export.arxiv.org',
                  'kind': 'papers', 'sourceKind': 'preprint', 'main': True, 'timeout': _timeout()},
        'europepmc': {'rps': 1.0, 'needsKey': False, 'host': 'www.ebi.ac.uk',
                      'kind': 'biomedical', 'sourceKind': 'paper', 'main': False,
                      'timeout': _timeout()},
        'dblp': {'rps': 1.0, 'needsKey': False, 'host': 'dblp.org', 'kind': 'computer-science',
                 'sourceKind': 'paper', 'main': False, 'timeout': _timeout()},
        'openreview': {'rps': 1.0, 'needsKey': False, 'host': 'api2.openreview.net',
                       'kind': 'machine-learning', 'sourceKind': 'paper', 'main': False,
                       'timeout': _timeout()},
        'opencitations': {'rps': 1.0, 'needsKey': False, 'host': 'opencitations.net',
                          'kind': 'citations', 'sourceKind': 'paper', 'main': False,
                          'timeout': _timeout()},
        'github': {'rps': 1.0, 'needsKey': False, 'host': 'api.github.com', 'kind': 'code',
                   'sourceKind': 'code', 'main': False, 'timeout': _timeout()},
        'huggingface': {'rps': 1.0, 'needsKey': False, 'host': 'huggingface.co', 'kind': 'artifacts',
                        'sourceKind': 'model', 'main': False, 'timeout': _timeout()},
        'openalex': {'rps': 1.0, 'needsKey': False, 'host': 'api.openalex.org',
                     'kind': 'enrichment', 'sourceKind': 'paper', 'main': False,
                     'dailyBudget': True, 'timeout': _timeout()},
    }


def connector_search(name: str, query: str, *, count: int = 10, options: dict | None = None) -> list[dict]:
    """Search one connector. Unknown name / empty query / any failure ⇒ ``[]`` (never raises)."""
    searcher = _SEARCHERS.get(str(name or '').strip().lower())
    if searcher is None:
        return []
    query = str(query or '').strip()
    if not query:
        return []
    try:
        wanted = max(1, min(int(count or 10), 100))
    except (TypeError, ValueError):
        wanted = 10
    try:
        rows = searcher(query, wanted, options or {})
    except Exception as exc:  # connector_search must never raise
        _log_failure(str(name), type(exc).__name__)
        return []
    provider = str(name).strip().lower()
    cleaned: list[dict] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        row.setdefault('provider', provider)
        cleaned.append(row)
    return cleaned[:wanted]


# ------------------------------------------------------------------- papers fusion

def _norm_url_key(url: str) -> str:
    text = _clean(url)
    if not text:
        return ''
    split = urllib.parse.urlsplit(text)
    host = (split.hostname or '').lower()
    if host.startswith('www.'):
        host = host[4:]
    path = split.path.rstrip('/')
    return f'{host}{path}'.lower()


def _title_fingerprint(value: str) -> str:
    tokens = [token for token in _WORD.findall(_clean(value).lower()) if len(token) > 2]
    if not tokens:
        return ''
    return ' '.join(tokens[:10])


def _dedupe_key(row: dict) -> str:
    doi = _norm_doi(row.get('doi'))
    if doi:
        return 'doi:' + doi
    arxiv = _norm_arxiv(row.get('arxivId'))
    if arxiv and re.match(r'^(\d{4}\.\d{4,5}|[a-z-]+/\d{7})$', arxiv):
        return 'arxiv:' + arxiv
    fingerprint = _title_fingerprint(row.get('title'))
    if fingerprint:
        return 'title:' + fingerprint
    url = _norm_url_key(row.get('url'))
    return 'url:' + url if url else ''


def rrf_fuse(legs: list[dict], *, k: int = RRF_K) -> list[dict]:
    """Internal Reciprocal Rank Fusion. ``legs`` = ``[{'name', 'weight', 'rows'}]``.

    A row is identified by DOI → arXiv id → title fingerprint. Every leg contributes, so a
    result found by one provider is never dropped — it just scores lower than one seen by
    several. Field values from the first leg that has them win; later legs fill the gaps.
    """
    scores: dict[str, float] = {}
    merged: dict[str, dict] = {}
    order: dict[str, int] = {}
    for leg in legs or []:
        weight = float(leg.get('weight') or 1.0)
        for rank, row in enumerate(leg.get('rows') or [], start=1):
            if not isinstance(row, dict):
                continue
            key = _dedupe_key(row)
            if not key:
                continue
            if key not in merged:
                merged[key] = dict(row)
                order[key] = len(order)
            else:
                for field, value in row.items():
                    if not merged[key].get(field) and value:
                        merged[key][field] = value
            scores[key] = scores.get(key, 0.0) + weight / (k + rank)
    fused = []
    for key, row in merged.items():
        copy = dict(row)
        copy['rrf'] = round(scores.get(key, 0.0), 6)
        fused.append((key, copy))
    fused.sort(key=lambda item: (-scores.get(item[0], 0.0), order.get(item[0], 0)))
    return [row for _key, row in fused]


def _papers_legs(queries: list[str], count: int, options: dict) -> list[str]:
    text = ' '.join(queries) + ' ' + ' '.join(
        _clean(options.get(key)) for key in ('domain', 'kind', 'field', 'fields', 'category'))
    explicit = options.get('legs')
    if isinstance(explicit, list) and explicit:
        return [str(name) for name in explicit if str(name) in _SEARCHERS]
    legs = ['semantic_scholar', 'crossref', 'arxiv']
    low = text.lower()
    if _bmc_hint(low):
        legs.append('europepmc')
    if any(token in low for token in ('algorithm', 'compiler', 'distributed', 'database',
                                      'software', 'programming', 'computer science', 'security',
                                      'network', 'dblp')):
        legs.append('dblp')
    if any(token in low for token in ('machine learning', 'deep learning', 'neural', 'transformer',
                                      'llm', 'language model', 'reinforcement', 'openreview',
                                      'iclr', 'neurips', 'icml')):
        legs.append('openreview')
    if any(token in low for token in ('code', 'library', 'framework', 'github', 'implementation',
                                      'toolkit', 'repository', 'repo')):
        legs.append('github')
    if options.get('openalex') and daily_budget_left('openalex') > 0:
        legs.append('openalex')
    deduped: list[str] = []
    for name in legs:
        if name not in deduped:
            deduped.append(name)
    return deduped


def papers_search(queries: list[str], *, count: int = 10, options: dict | None = None) -> list[dict]:
    """Multi-leg keyless paper search: no first-provider-wins, RRF fusion, failing legs skipped.

    Legs: Semantic Scholar + Crossref + arXiv always; Europe PMC when the query looks
    biomedical; DBLP for computer science; OpenReview for ML; GitHub for code. OpenAlex is a
    budget-gated enrichment leg, off unless ``options['openalex']`` is set.
    """
    options = options or {}
    try:
        wanted = max(1, min(int(count or 10), 100))
    except (TypeError, ValueError):
        wanted = 10
    cleaned = [str(query).strip() for query in (queries or []) if str(query or '').strip()]
    if not cleaned:
        return []
    leg_names = _papers_legs(cleaned, wanted, options)
    leg_count = wanted
    try:
        leg_count = max(1, min(int(options.get('legCount') or wanted), 100))
    except (TypeError, ValueError):
        leg_count = wanted
    legs: list[dict] = []
    for name in leg_names:
        for query in cleaned:
            try:
                rows = connector_search(name, query, count=leg_count, options=options)
            except Exception as exc:  # pragma: no cover - connector_search already guards
                _log_failure(name, type(exc).__name__)
                rows = []
            if rows:
                legs.append({'name': name, 'weight': 1.0, 'rows': rows})
    if not legs:
        return []
    return rrf_fuse(legs)[:wanted]


# --------------------------------------------------------------------- citation chase

def _bare_identifier(value: str) -> str:
    """Gỡ vỏ URL khỏi một định danh: `https://openalex.org/W…` → `W…`, `openalex:W…` → `W…`.

    Đường cũ nhận URL trần và trả rỗng; giữ nguyên URL thì `_s2_ref`/`_openalex_citation` không
    phân loại được định danh (low: `citation_chase` phải chuẩn hoá như bản cũ).
    """
    text = _clean(value)
    if not text:
        return ''
    text = re.sub(r'^(?:https?://)?(?:www\.)?openalex\.org/', '', text, flags=re.I)
    text = re.sub(r'^openalex:', '', text, flags=re.I)
    return text


def _s2_ref(identifier: str) -> str:
    text = _bare_identifier(identifier)
    if not text:
        return ''
    doi = _norm_doi(text)
    if _looks_doi(text) or _looks_doi(doi):
        return 'DOI:' + doi
    low = text.lower()
    if low.startswith('arxiv:'):
        return 'ARXIV:' + _norm_arxiv(text)
    if _looks_arxiv(text):
        return 'ARXIV:' + _norm_arxiv(text)
    if low.startswith('corpusid:'):
        return text
    if _S2_ID_RE.match(text):
        return text
    if _WORK_ID_RE.match(text):
        return ''  # an OpenAlex id: S2 does not resolve it
    return text


def _parse_s2_citation_row(item: dict, *, direction: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    paper = item.get('citingPaper' if direction == 'forward' else 'citedPaper')
    if not isinstance(paper, dict):
        return None
    return _parse_s2_paper(paper)


def _s2_citation(identifier: str, *, direction: str, limit: int, options: dict) -> list[dict]:
    ref = _s2_ref(identifier)
    if not ref:
        return []
    path = 'citations' if direction == 'forward' else 'references'
    url = (f'{_S2_BASE}/paper/{urllib.parse.quote(ref, safe="")}/{path}?'
           + urllib.parse.urlencode({'limit': limit, 'fields': _S2_FIELDS}))
    status, body = polite_get('api.semanticscholar.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    data = (payload or {}).get('data') if isinstance(payload, dict) else None
    rows = []
    for item in (data or [])[:limit]:
        row = _parse_s2_citation_row(item, direction=direction)
        if row:
            rows.append(row)
    return rows


def _opencitations_citation(doi: str, *, direction: str, limit: int, options: dict) -> list[dict]:
    doi = _norm_doi(doi)
    if not _looks_doi(doi):
        return []
    path = 'references' if direction == 'backward' else 'citations'
    url = f'{_OPENCI_BASE}/{path}/{urllib.parse.quote(doi)}'
    status, body = polite_get('opencitations.net', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    if not isinstance(payload, list):
        return []
    rows = []
    for item in payload[:limit]:
        row = _parse_opencitations_item(item, direction=direction, cited=doi)
        if row:
            rows.append(row)
    return rows


def _crossref_references(doi: str, *, limit: int, options: dict) -> list[dict]:
    doi = _norm_doi(doi)
    if not _looks_doi(doi):
        return []
    mailto = _clean(options.get('mailto')) or _MAILTO_DEFAULT
    url = f'{_CROSSREF_BASE}/works/{urllib.parse.quote(doi)}?' + urllib.parse.urlencode({'mailto': mailto})
    status, body = polite_get('api.crossref.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    message = (payload or {}).get('message') if isinstance(payload, dict) else None
    references = (message or {}).get('reference') if isinstance(message, dict) else None
    rows = []
    for reference in (references or [])[:limit]:
        if not isinstance(reference, dict):
            continue
        ref_doi = _norm_doi(reference.get('DOI'))
        title = _clean(reference.get('article-title')) or _clean(reference.get('unstructured')) \
            or _clean(reference.get('key'))
        url_out = f'https://doi.org/{ref_doi}' if ref_doi else ''
        if not (title or url_out):
            continue
        published = _date_only(reference.get('year'))
        rows.append(_row(url=url_out, title=title, snippet='Crossref reference', provider='crossref',
                         doi=ref_doi, publishedAt=published, venue=reference.get('journal-title'),
                         dateSource=_date_source(published), accessLevel='snippet', sourceKind='paper'))
    return rows


def _europepmc_lookup(identifier: str, options: dict) -> tuple[str, str]:
    """``(source, id)`` for the Europe PMC citation endpoints, or ``('', '')``."""
    text = _clean(identifier)
    if not text:
        return '', ''
    if text.upper().startswith('PMC'):
        return 'PMC', text.upper().replace('PMC', '', 1)
    if text.isdigit():
        return 'MED', text
    doi = _norm_doi(text)
    if not _looks_doi(doi):
        return '', ''
    params = {'query': f'DOI:"{doi}"', 'format': 'json', 'pageSize': 1, 'resultType': 'core'}
    url = _EPMC_BASE + '/search?' + urllib.parse.urlencode(params)
    status, body = polite_get('www.ebi.ac.uk', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return '', ''
    payload = _payload(body)
    hits = ((payload or {}).get('resultList') or {}).get('result') if isinstance(payload, dict) else None
    if not hits:
        return '', ''
    hit = hits[0] or {}
    return _clean(hit.get('source')) or 'MED', _clean(hit.get('id'))


def _europepmc_citation(identifier: str, *, direction: str, limit: int, options: dict) -> list[dict]:
    source, ident = _europepmc_lookup(identifier, options)
    if not (source and ident):
        return []
    path = 'references' if direction == 'backward' else 'citations'
    url = (f'{_EPMC_BASE}/{urllib.parse.quote(source)}/{urllib.parse.quote(ident)}/{path}?'
           + urllib.parse.urlencode({'format': 'json', 'pageSize': limit}))
    status, body = polite_get('www.ebi.ac.uk', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    if not isinstance(payload, dict):
        return []
    node = payload.get('citationList' if direction == 'forward' else 'referenceList') or {}
    items = node.get('citation' if direction == 'forward' else 'reference') if isinstance(node, dict) else None
    rows = []
    for item in (items or [])[:limit]:
        row = _parse_europepmc_item(item)
        if row:
            rows.append(row)
    return rows


def _openalex_work_id_from_doi(doi: str, options: dict) -> str:
    if not _use_budget('openalex'):
        return ''
    url = f'{_OPENALEX_BASE}/works/doi:{urllib.parse.quote(_norm_doi(doi))}?' \
        + urllib.parse.urlencode({'select': 'id'})
    status, body = polite_get('api.openalex.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return ''
    payload = _payload(body)
    work_id = _clean((payload or {}).get('id')) if isinstance(payload, dict) else ''
    return work_id.rstrip('/').rsplit('/', 1)[-1] if work_id else ''


def _openalex_citation(identifier: str, *, direction: str, limit: int, options: dict) -> list[dict]:
    text = _bare_identifier(identifier)
    work_id = text if _WORK_ID_RE.match(text) else ''
    if not work_id:
        doi = _norm_doi(text)
        if not _looks_doi(doi):
            return []
        work_id = _openalex_work_id_from_doi(doi, options)
    if not work_id:
        return []
    if direction == 'forward':
        if not _use_budget('openalex'):
            return []
        url = f'{_OPENALEX_BASE}/works?' + urllib.parse.urlencode(
            {'filter': f'cites:{work_id}', 'per-page': limit, 'select': _OPENALEX_SELECT})
        status, body = polite_get('api.openalex.org', url, rps=1.0, timeout=_timeout(options))
        if status != 200:
            return []
        payload = _payload(body)
        results = (payload or {}).get('results') if isinstance(payload, dict) else None
        return [row for row in (_parse_openalex_item(item) for item in (results or [])[:limit]) if row]
    if not _use_budget('openalex'):
        return []
    url = f'{_OPENALEX_BASE}/works/{urllib.parse.quote(work_id)}?' \
        + urllib.parse.urlencode({'select': f'{_OPENALEX_SELECT},referenced_works'})
    status, body = polite_get('api.openalex.org', url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    refs = (payload or {}).get('referenced_works') if isinstance(payload, dict) else None
    ids = [str(item).rstrip('/').rsplit('/', 1)[-1] for item in (refs or [])][:limit]
    if not ids:
        return []
    if not _use_budget('openalex'):
        return []
    resolve_url = f'{_OPENALEX_BASE}/works?' + urllib.parse.urlencode(
        {'filter': 'openalex_id:' + '|'.join(ids), 'per-page': min(len(ids), 50),
         'select': _OPENALEX_SELECT})
    status, body = polite_get('api.openalex.org', resolve_url, rps=1.0, timeout=_timeout(options))
    if status != 200:
        return []
    payload = _payload(body)
    results = (payload or {}).get('results') if isinstance(payload, dict) else None
    return [row for row in (_parse_openalex_item(item) for item in (results or [])[:limit]) if row]


def _biomedical_identifier(identifier: str, doi: str, options: dict) -> bool:
    ident = _clean(identifier)
    if ident.upper().startswith('PMC') or ident.isdigit():
        return True
    text = ' '.join(_clean(value) for value in (identifier, options.get('domain'), options.get('kind')))
    return _bmc_hint(text) or bool(doi and options.get('biomedical'))


def citation_chase(identifier: str, *, direction: str, limit: int = 25,
                   options: dict | None = None) -> list[dict]:
    """Forward/backward citation chase. Semantic Scholar first, then keyless fallbacks.

    ``direction`` must be ``'forward'`` or ``'backward'``; invalid input returns ``[]``.
    Fallbacks are tried only while earlier legs come back empty: OpenCitations by DOI,
    Crossref for the backward direction, Europe PMC for biomedical ids, and OpenAlex while
    its daily budget lasts.
    """
    options = options or {}
    identifier = _bare_identifier(identifier)
    direction = _clean(direction).lower()
    if not identifier or direction not in ('forward', 'backward'):
        return []
    try:
        wanted = max(1, min(int(limit or 25), 100))
    except (TypeError, ValueError):
        wanted = 25
    doi = _norm_doi(identifier)
    legs = [_s2_citation]
    if direction == 'forward':
        legs.append(_opencitations_citation)
        legs.append(_openalex_citation)
        if _biomedical_identifier(identifier, doi, options):
            legs.append(_europepmc_citation)
    else:
        legs.append(_opencitations_citation)
        legs.append(_crossref_references)
        if _biomedical_identifier(identifier, doi, options):
            legs.append(_europepmc_citation)
        legs.append(_openalex_citation)
    for leg in legs:
        try:
            if leg is _opencitations_citation:
                rows = leg(doi, direction=direction, limit=wanted, options=options)
            elif leg is _crossref_references:
                rows = leg(doi, limit=wanted, options=options)
            else:
                rows = leg(identifier, direction=direction, limit=wanted, options=options)
        except Exception as exc:  # pragma: no cover - defensive
            _log_failure(getattr(leg, '__name__', 'citation'), type(exc).__name__)
            rows = []
        if rows:
            return rows[:wanted]
    return []


# ------------------------------------------------------------------- OpenAlex budget

_UNLIMITED_NAMES = ('openalex',)  # only OpenAlex is budget-counted; everything else is free


def _data_dir() -> Path:
    override = _clean(os.environ.get('BOXFOX_AGENT_DATA_DIR'))
    if override:
        return Path(override)
    local = _clean(os.environ.get('LOCALAPPDATA'))
    base = Path(local) if local else Path.home()
    return base / 'BoxFox' / 'harness'


def _budget_path() -> Path:
    return _data_dir() / _BUDGET_FILE


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _budget_limit(name: str):
    if name not in _UNLIMITED_NAMES:
        return None
    raw = os.environ.get('BOXFOX_OPENALEX_DAILY_CALLS')
    if raw is None or not str(raw).strip():
        return int(_OPENALEX_CALLS_DEFAULT)
    try:
        return max(0, int(str(raw).strip()))
    except (TypeError, ValueError):
        return int(_OPENALEX_CALLS_DEFAULT)


_BUDGET_LOCK = threading.Lock()


def _read_budget() -> dict:
    try:
        data = json.loads(_budget_path().read_text('utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_budget(state: dict) -> None:
    try:
        path = _budget_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
    except Exception:  # pragma: no cover - a budget that cannot persist must not break a call
        pass


def daily_budget_left(name: str) -> int:
    """Remaining calls for a budgeted connector today (OpenAlex keyless, default 50).

    Unbudgeted names return a large sentinel (``10**9``). The counter resets when the UTC
    date changes and lives in ``academic_budget.json`` under the harness data dir.
    """
    name = _clean(name).lower()
    limit = _budget_limit(name)
    if limit is None:
        return _UNLIMITED
    with _BUDGET_LOCK:
        record = _read_budget().get(name) or {}
        if not isinstance(record, dict) or record.get('date') != _today():
            return limit
        return max(0, limit - _int_or_zero(record.get('used')))


def _use_budget(name: str) -> bool:
    """Consume one call. ``True`` when allowed (and consumed), ``False`` when exhausted."""
    name = _clean(name).lower()
    limit = _budget_limit(name)
    if limit is None:
        return True
    with _BUDGET_LOCK:
        state = _read_budget()
        record = state.get(name) or {}
        if not isinstance(record, dict) or record.get('date') != _today():
            record = {'date': _today(), 'used': 0}
        used = _int_or_zero(record.get('used'))
        if used >= limit:
            _log('academic.budget_exhausted', provider=name,
                 message=f'{name}: daily call budget exhausted')
            return False
        record['used'] = used + 1
        state[name] = record
        _write_budget(state)
        return True


__all__ = ['ACCESS_LEVELS', 'connectors', 'polite_get', 'connector_search', 'papers_search',
           'citation_chase', 'daily_budget_left', 'rrf_fuse']
