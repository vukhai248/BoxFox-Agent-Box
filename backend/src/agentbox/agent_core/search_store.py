"""Bộ đệm bền + chỉ mục trang + nhật ký tìm + sức khoẻ engine cho lớp tìm 10 bước (P0b).

VÌ SAO một SQLite riêng: lớp tìm kiếm mới cần bốn thứ sống QUA khởi động lại mà bộ đệm trong
tiến trình của `web.py` (`_search_cache`) không giữ được —
  * `research_search_cache`  — bộ đệm truy vấn (bước 9), TTL theo loại truy vấn;
  * `research_page_index`    — chỉ mục toàn văn FTS5 của các trang ĐÃ TẢI, để nhánh sau không
                               phải tải lại, và chế độ gói nguồn (8.3) đọc chung chỉ mục này;
  * `research_search_log`    — dữ liệu cho bão hoà (5.5), mục "Cách tìm" của báo cáo và đo 8.7;
  * `search_engine_health`   — cầu dao engine (bước 7): 3 lỗi liên tiếp ⇒ ngưng 5'/15'/60'.

Hình dạng bảng và API là HỢP ĐỒNG (`/code/.plans/p0-interfaces.md` §2) — không đổi tên cột.
`CREATE TABLE IF NOT EXISTS` nên một DB sống từ trước vẫn mở được; WAL để đọc/ghi chồng nhau
giữa các luồng; `check_same_thread=False` vì `run_pipeline` chạy các chân song song.

Không bao giờ ném vì dữ liệu hỏng: một DB không ghi được (đĩa đầy, quyền) thì bộ đệm coi như
trượt (`None`) chứ không được làm chết một lượt tìm.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from . import reading
from .limits import SEARCH_ENGINE_FAIL_STREAK, SEARCH_ENGINE_SUSPEND_SECONDS

__all__ = ['default_path', 'connect', 'SearchStore', 'SearchStoreError',
           'ENGINE_FALLBACK', 'DEFAULT_ENGINES_BY_KIND']

# DB mặc định: `BOXFOX_SEARCH_DB` → `$BOXFOX_AGENT_DATA_DIR/search.sqlite` → `~/BoxFox/harness/`.
DB_PATH_ENV = 'BOXFOX_SEARCH_DB'
DATA_DIR_ENV = 'BOXFOX_AGENT_DATA_DIR'

_FTS_OK = True          # hạ khi bản SQLite thiếu FTS5 — `index_search` rơi về LIKE
_SCHEMA = '''
CREATE TABLE IF NOT EXISTS research_search_cache(
    key TEXT PRIMARY KEY, scope TEXT NOT NULL DEFAULT 'web', query TEXT NOT NULL,
    filters TEXT NOT NULL DEFAULT '{}', payload TEXT NOT NULL,
    created REAL NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS research_page_index(
    url TEXT PRIMARY KEY, domain TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '', published_at TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL, pack TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS research_search_log(
    id INTEGER PRIMARY KEY AUTOINCREMENT, research_id TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '', facet_id TEXT NOT NULL DEFAULT '',
    child_id TEXT NOT NULL DEFAULT '', turn INTEGER NOT NULL DEFAULT 0,
    query TEXT NOT NULL, variant_kind TEXT NOT NULL DEFAULT '',
    engines TEXT NOT NULL DEFAULT '[]', results INTEGER NOT NULL DEFAULT 0,
    new_unique INTEGER NOT NULL DEFAULT 0, relevant_new INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS search_engine_health(
    engine TEXT PRIMARY KEY, window_start REAL NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 0, empty INTEGER NOT NULL DEFAULT 0,
    blocked INTEGER NOT NULL DEFAULT 0, timeouts INTEGER NOT NULL DEFAULT 0,
    p50_ms INTEGER NOT NULL DEFAULT 0, p95_ms INTEGER NOT NULL DEFAULT 0,
    fails_streak INTEGER NOT NULL DEFAULT 0, suspended_until REAL NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS search_log_research ON research_search_log(research_id, id);
'''

# Bảng engine theo NHÓM (kế hoạch 5.4.2). `pick_engines` chọn con từ đây; chủ nhà ghi đè bằng
# `BOXFOX_SEARCH_ENGINES` (chỉ áp cho nhóm `web`, danh sách phẩy ngăn cách).
DEFAULT_ENGINES_BY_KIND: dict[str, tuple[str, ...]] = {
    'web': ('brave', 'duckduckgo', 'mojeek', 'qwant', 'startpage', 'bing', 'google'),
    'news': ('bing news', 'qwant news', 'google news'),
    'reference': ('wikipedia', 'wikidata'),
    'code': ('github',),
    'academic': ('google scholar',),
}
ENGINE_ROTATION_ENV = 'BOXFOX_SEARCH_ENGINES'
# Khi MỌI engine đều bị ngưng, vẫn phải có một danh sách để thử (bước 7 nói rõ "web chung suy
# giảm" chứ không bịa là đã tìm đủ): dùng thứ tự chất lượng, không đọc DB.
ENGINE_FALLBACK: tuple[str, ...] = ('brave', 'duckduckgo', 'bing', 'google')
# Trọng số CHẤT LƯỢNG engine (đo ở 8.7). Mặc định 1.0 cho engine không có mặt trong bảng.
ENGINE_QUALITY: dict[str, float] = {
    'brave': 1.0, 'google': 0.95, 'startpage': 0.8, 'bing': 0.8, 'duckduckgo': 0.75,
    'qwant': 0.65, 'mojeek': 0.6, 'wikipedia': 0.7, 'wikidata': 0.6, 'github': 0.7,
    'google scholar': 0.5, 'bing news': 0.7, 'qwant news': 0.6, 'google news': 0.7,
}


class SearchStoreError(RuntimeError):
    """DB không mở/ghi được — người gọi coi như bộ đệm trượt, KHÔNG được ném ra ngoài."""


def _data_dir() -> Path:
    base = (os.environ.get(DATA_DIR_ENV) or '').strip()
    if base:
        return Path(base)
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BoxFox' / 'harness'


def default_path() -> Path:
    """`BOXFOX_SEARCH_DB` nếu đặt; không thì dưới thư mục dữ liệu harness (mặc định `~/BoxFox/harness`)."""
    raw = (os.environ.get(DB_PATH_ENV) or '').strip()
    if raw:
        return Path(os.path.expanduser(raw))
    return _data_dir() / 'search.sqlite'


def _fold(value) -> str:
    """Bỏ dấu + hạ chữ để so khớp truy vấn chỉ mục — dùng chung `reading.fold_text`."""
    return reading.fold_text(str(value or ''))


def _tokens(text: str) -> list[str]:
    return [tok for tok in re.findall(r'[^\W_]+', _fold(text)) if len(tok) > 1]


def _fts_query(query: str) -> str:
    """Biểu thức FTS5 an toàn: mỗi token bọc trong nháy kép, nối bằng OR.

    VÌ SAO không đưa chuỗi thô vào MATCH: FTS5 hiểu `-`, `*`, `:`, `(` thành cú pháp và một truy
    vấn người dùng như `RAG (retrieval-augmented)` sẽ làm ném lỗi cú pháp (đo được: `fts5:
    syntax error`). Token hoá trước rồi bọc nháy là cách duy nhất không cần đoán.
    """
    toks = _tokens(query)
    return ' OR '.join(f'"{tok}"' for tok in toks)


class SearchStore:
    """Một kết nối SQLite dùng chung, có khoá luồng cho mọi thao tác ghi/đọc."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.fts = _FTS_OK
        with self._lock:
            try:
                self.db.execute('PRAGMA journal_mode=WAL')
            except sqlite3.DatabaseError:
                pass
            self.db.executescript(_SCHEMA)
            if self.fts:
                try:
                    # `remove_diacritics 2` để truy vấn bỏ dấu (`chuyen tuyen`) khớp văn bản có dấu
                    # (`chuyển tuyến`) — tokenizer mặc định giữ nguyên dấu nên tiếng Việt sẽ trượt.
                    self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS research_page_index_fts '
                                    'USING fts5(url UNINDEXED, title, text, '
                                    'tokenize="unicode61 remove_diacritics 2")')
                except sqlite3.OperationalError:
                    try:
                        self.db.execute('CREATE VIRTUAL TABLE IF NOT EXISTS research_page_index_fts '
                                        'USING fts5(url UNINDEXED, title, text)')
                    except sqlite3.OperationalError:
                        # Bản SQLite thiếu FTS5: `index_search` phải rơi về LIKE thay vì chết.
                        self.fts = False
            self.db.commit()

    # ------------------------------------------------------------------- cache
    def cache_get(self, key: str) -> dict | None:
        with self._lock:
            try:
                row = self.db.execute(
                    'SELECT payload, expires FROM research_search_cache WHERE key = ?', (str(key),)).fetchone()
            except sqlite3.DatabaseError:
                return None
        if row is None:
            return None
        if float(row['expires']) <= time.time():
            return None
        try:
            payload = json.loads(row['payload'])
        except (TypeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def cache_put(self, key: str, scope: str, query: str, filters: dict, payload: dict,
                  ttl: float) -> None:
        now = time.time()
        with self._lock:
            try:
                self.db.execute(
                    'INSERT OR REPLACE INTO research_search_cache'
                    '(key, scope, query, filters, payload, created, expires) VALUES(?,?,?,?,?,?,?)',
                    (str(key), str(scope or 'web'), str(query or ''),
                     json.dumps(filters or {}, ensure_ascii=False, sort_keys=True),
                     json.dumps(payload, ensure_ascii=False), now, now + max(0.0, float(ttl))))
                self.db.commit()
            except sqlite3.DatabaseError:
                pass

    # ------------------------------------------------------------------- index
    def index_upsert(self, url, title, text, *, domain='', published_at='', pack='') -> None:
        key = str(url or '').strip()
        if not key:
            return
        with self._lock:
            try:
                self.db.execute(
                    'INSERT OR REPLACE INTO research_page_index'
                    '(url, domain, title, text, published_at, fetched_at, pack) VALUES(?,?,?,?,?,?,?)',
                    (key, str(domain or ''), str(title or '')[:400], str(text or ''),
                     str(published_at or ''), time.time(), str(pack or '')))
                if self.fts:
                    self.db.execute('DELETE FROM research_page_index_fts WHERE url = ?', (key,))
                    self.db.execute('INSERT INTO research_page_index_fts(url, title, text) VALUES(?,?,?)',
                                    (key, str(title or ''), str(text or '')))
                self.db.commit()
            except sqlite3.DatabaseError:
                pass

    def index_search(self, query: str, limit: int = 10) -> list[dict]:
        """Tìm trong chỉ mục trang đã tải. Không có kết quả ⇒ `[]` (KHÁC với "không có chỉ mục")."""
        expr = _fts_query(query)
        limit = max(1, min(int(limit or 10), 100))
        if not expr:
            return []
        with self._lock:
            try:
                if self.fts:
                    rows = self.db.execute(
                        'SELECT i.url, i.domain, i.title, i.text, i.published_at, i.pack,'
                        '       snippet(research_page_index_fts, 2, "", "", "…", 12) AS snip,'
                        '       bm25(research_page_index_fts) AS rank'
                        ' FROM research_page_index_fts'
                        ' JOIN research_page_index i ON i.url = research_page_index_fts.url'
                        ' WHERE research_page_index_fts MATCH ? ORDER BY rank LIMIT ?',
                        (expr, limit)).fetchall()
                else:
                    like = '%' + _fold(query) + '%'
                    rows = self.db.execute(
                        'SELECT url, domain, title, text, published_at, pack,'
                        " '' AS snip, 0 AS rank FROM research_page_index"
                        ' WHERE lower(title) LIKE ? OR lower(text) LIKE ? LIMIT ?',
                        (like, like, limit)).fetchall()
            except sqlite3.DatabaseError:
                return []
        out = []
        for row in rows:
            out.append({'url': row['url'], 'domain': row['domain'] or '',
                        'title': row['title'] or '', 'snippet': row['snip'] or '',
                        'publishedAt': row['published_at'] or '', 'pack': row['pack'] or '',
                        'sourceKind': 'local-index'})
        return out

    def index_get(self, url: str) -> dict | None:
        key = str(url or '').strip()
        if not key:
            return None
        with self._lock:
            try:
                row = self.db.execute(
                    'SELECT url, domain, title, text, published_at, fetched_at, pack'
                    ' FROM research_page_index WHERE url = ?', (key,)).fetchone()
            except sqlite3.DatabaseError:
                return None
        if row is None:
            return None
        return {'url': row['url'], 'domain': row['domain'] or '', 'title': row['title'] or '',
                'text': row['text'] or '', 'publishedAt': row['published_at'] or '',
                'fetchedAt': row['fetched_at'], 'pack': row['pack'] or ''}

    # --------------------------------------------------------------- search log
    def log_search(self, record: dict) -> None:
        record = record or {}
        engines = record.get('engines')
        if not isinstance(engines, str):
            engines = json.dumps(list(engines or []), ensure_ascii=False)
        with self._lock:
            try:
                self.db.execute(
                    'INSERT INTO research_search_log'
                    '(research_id, session_id, facet_id, child_id, turn, query, variant_kind,'
                    ' engines, results, new_unique, relevant_new, latency_ms, created)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (str(record.get('research_id') or record.get('researchId') or ''),
                     str(record.get('session_id') or record.get('sessionId') or ''),
                     str(record.get('facet_id') or record.get('facetId') or ''),
                     str(record.get('child_id') or record.get('childId') or ''),
                     int(record.get('turn') or 0), str(record.get('query') or ''),
                     str(record.get('variant_kind') or record.get('variantKind') or ''),
                     engines, int(record.get('results') or 0),
                     int(record.get('new_unique') or record.get('newUnique') or 0),
                     int(record.get('relevant_new') or record.get('relevantNew') or 0),
                     int(record.get('latency_ms') or record.get('latencyMs') or 0),
                     float(record.get('created') or time.time())))
                self.db.commit()
            except sqlite3.DatabaseError:
                pass

    def search_log(self, *, research_id: str | None = None, since: float | None = None) -> list[dict]:
        clauses, params = [], []
        if research_id:
            clauses.append('research_id = ?')
            params.append(str(research_id))
        if since is not None:
            clauses.append('created >= ?')
            params.append(float(since))
        where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
        with self._lock:
            try:
                rows = self.db.execute(
                    'SELECT * FROM research_search_log' + where + ' ORDER BY id', params).fetchall()
            except sqlite3.DatabaseError:
                return []
        out = []
        for row in rows:
            item = dict(row)
            try:
                item['engines'] = json.loads(item.get('engines') or '[]')
            except (TypeError, ValueError):
                item['engines'] = []
            out.append(item)
        return out

    # ------------------------------------------------------------ engine health
    def engine_health(self) -> list[dict]:
        with self._lock:
            try:
                rows = self.db.execute('SELECT * FROM search_engine_health').fetchall()
            except sqlite3.DatabaseError:
                return []
        return [dict(row) for row in rows]

    def record_engine_result(self, engine, *, ok, empty, blocked, timeout, latency_ms) -> None:
        """Một kết quả của một engine: cập nhật đếm, p50/p95 (ước lượng), chuỗi lỗi và cầu dao.

        Cầu dao suy ra TỪ `fails_streak` thay vì thêm cột: cứ đủ `SEARCH_ENGINE_FAIL_STREAK` lỗi
        liên tiếp thì ngưng, mức lùi = số lần đã chạm ngưỡng (300 s → 900 s → 3600 s, kẹp ở cuối).
        Nhờ vậy bảng vẫn đúng các cột trong hợp đồng §2.
        """
        engine = str(engine or '').strip()
        if not engine:
            return
        failed = bool(blocked or timeout or (not ok and not empty))
        with self._lock:
            try:
                row = self.db.execute(
                    'SELECT * FROM search_engine_health WHERE engine = ?', (engine,)).fetchone()
                now = time.time()
                if row is None:
                    values = {'window_start': now, 'ok': 0, 'empty': 0, 'blocked': 0, 'timeouts': 0,
                              'p50_ms': 0, 'p95_ms': 0, 'fails_streak': 0, 'suspended_until': 0.0}
                else:
                    values = dict(row)
                if failed:
                    values['fails_streak'] = int(values.get('fails_streak') or 0) + 1
                else:
                    values['fails_streak'] = 0
                if ok:
                    values['ok'] = int(values.get('ok') or 0) + 1
                if empty:
                    values['empty'] = int(values.get('empty') or 0) + 1
                if blocked:
                    values['blocked'] = int(values.get('blocked') or 0) + 1
                if timeout:
                    values['timeouts'] = int(values.get('timeouts') or 0) + 1
                latency = max(0, int(latency_ms or 0))
                if latency:
                    old50 = int(values.get('p50_ms') or 0)
                    old95 = int(values.get('p95_ms') or 0)
                    values['p50_ms'] = latency if not old50 else round(old50 * 0.5 + latency * 0.5)
                    values['p95_ms'] = max(values['p50_ms'],
                                           latency if not old95 else round(old95 * 0.5 + latency * 0.5))
                streak = int(values['fails_streak'])
                if failed and streak and streak % SEARCH_ENGINE_FAIL_STREAK == 0:
                    level = min(streak // SEARCH_ENGINE_FAIL_STREAK - 1,
                                len(SEARCH_ENGINE_SUSPEND_SECONDS) - 1)
                    values['suspended_until'] = now + SEARCH_ENGINE_SUSPEND_SECONDS[level]
                elif not failed:
                    values['suspended_until'] = 0.0
                self.db.execute(
                    'INSERT OR REPLACE INTO search_engine_health(engine, window_start, ok, empty,'
                    ' blocked, timeouts, p50_ms, p95_ms, fails_streak, suspended_until)'
                    ' VALUES(?,?,?,?,?,?,?,?,?,?)',
                    (engine, float(values.get('window_start') or now), int(values.get('ok') or 0),
                     int(values.get('empty') or 0), int(values.get('blocked') or 0),
                     int(values.get('timeouts') or 0), int(values.get('p50_ms') or 0),
                     int(values.get('p95_ms') or 0), streak, float(values.get('suspended_until') or 0)))
                self.db.commit()
            except sqlite3.DatabaseError:
                pass

    def pick_engines(self, n: int = 4, *, kind: str = 'web') -> list[str]:
        """Chọn `n` engine khoẻ nhất theo `sức khoẻ × chất lượng`, bỏ engine đang bị ngưng.

        Truy vấn chỉ đi qua một tập con (bước 7) để mỗi engine nhận ít truy vấn hơn và ít bị chặn.
        Không có engine nào khoẻ ⇒ trả `ENGINE_FALLBACK` (vẫn thử, nhưng run phải ghi "suy giảm").
        """
        n = max(1, int(n or 1))
        candidates = list(_engines_for_kind(kind))
        now = time.time()
        health = {row['engine']: row for row in self.engine_health()}
        scored = []
        for engine in candidates:
            row = health.get(engine) or {}
            if float(row.get('suspended_until') or 0) > now:
                continue
            score = _health_score(row) * ENGINE_QUALITY.get(engine, 1.0)
            scored.append((score, engine))
        scored.sort(key=lambda item: item[0], reverse=True)
        chosen = [engine for _score, engine in scored[:n]]
        if chosen:
            return chosen
        return [engine for engine in ENGINE_FALLBACK][:n]


def _engines_for_kind(kind: str) -> tuple[str, ...]:
    """Danh sách engine của một nhóm; `BOXFOX_SEARCH_ENGINES` ghi đè nhóm `web` khi có."""
    if kind == 'web':
        raw = (os.environ.get(ENGINE_ROTATION_ENV) or '').strip()
        if raw:
            override = tuple(part.strip() for part in raw.split(',') if part.strip())
            if override:
                return override
    return DEFAULT_ENGINES_BY_KIND.get(kind) or DEFAULT_ENGINES_BY_KIND['web']


def _health_score(row: dict) -> float:
    """Sức khoẻ 0..1: tỉ lệ thành công, phạt `empty` một nửa (rỗng vẫn là engine trả lời được)."""
    ok = float(row.get('ok') or 0)
    empty = float(row.get('empty') or 0)
    blocked = float(row.get('blocked') or 0)
    timeouts = float(row.get('timeouts') or 0)
    total = ok + empty + blocked + timeouts
    if total <= 0:
        return 1.0                      # chưa có số đo ⇒ coi là trung tính, không phạt engine mới
    return max(0.0, min(1.0, (ok + 0.5 * empty) / total))


def connect(path: Path | None = None) -> SearchStore:
    """Mở (và tạo nếu thiếu) DB bộ đệm; lỗi mở ⇒ `SearchStoreError` cho người gọi xử lý."""
    try:
        return SearchStore(path or default_path())
    except (OSError, sqlite3.DatabaseError) as exc:  # pragma: no cover - đường lỗi đĩa/quyền
        raise SearchStoreError(f'cannot open search store at {path or default_path()}: {exc}') from exc
