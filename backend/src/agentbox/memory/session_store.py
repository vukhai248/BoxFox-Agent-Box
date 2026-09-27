"""Durable session checkpoints/events, adapted from Hermes persistence and OpenCode admission.

Running work is marked interrupted after restart; tool side effects are never replayed.
"""
import json
import hashlib
import sqlite3
import time
import uuid
from pathlib import Path


class SessionStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, parent_id TEXT, role TEXT NOT NULL,
                config TEXT NOT NULL, messages TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'idle', updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS checkpoints (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, messages TEXT NOT NULL,
                reason TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS journal (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                kind TEXT NOT NULL, text TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS event_session ON events(session_id, seq);
            CREATE INDEX IF NOT EXISTS journal_session ON journal(session_id, seq);
        ''')
        # N4 — bốn cột số đo cho hàng checkpoint. Đo trên máy chủ nhà 2026-09-21: 22 hàng
        # `checkpoints` (17 967 616 B) **không có một con số nào** — cột chỉ có
        # `id, session_id, messages, reason, created`, nên muốn biết lần nén đó chạy ở cửa sổ nào,
        # ngưỡng bao nhiêu, phải mò sang `events.payload` (33 hàng `kind='compression'`, mà 8 hàng
        # trong đó không mang số). Thêm cột là **thuần cộng thêm**: hàng cũ `NULL` vẫn đọc được, và
        # `ALTER TABLE` chỉ chạy khi cột còn thiếu (DB sống đã có bảng từ trước).
        # Vòng 27 đợt 8: `branches` — danh sách nhánh con ĐÃ dùng dòng sổ này làm bằng chứng. Một
        # dòng sổ là chuyện của CẢ VIỆC, không phải của riêng nhánh ghim nó: hai nhánh mở cùng một
        # trang, cùng đoạn trích thì luật idempotent (BUG-92) giữ MỘT dòng, và nếu dòng ấy chỉ nhớ
        # nhánh A thì nhánh B bị `research-lineage-missing` mà không có cách nào gỡ (vòng 27, đợt 8).
        self._add_missing_columns('source_ledger', {'branches': "TEXT NOT NULL DEFAULT '[]'"})
        # P1 (§5.3): `research_id` — sổ nguồn gắn theo PHIÊN, nhưng một phiên có nhiều RUN. Cột
        # này cho `source_list`/cổng hồ sơ/đếm bằng chứng lọc theo đúng run đang mở.
        self._add_missing_columns('source_ledger', {'research_id': "TEXT NOT NULL DEFAULT ''"})
        self._add_missing_columns('checkpoints', {
            'before_estimate': 'INTEGER', 'after_estimate': 'INTEGER',
            'context_window': 'INTEGER', 'model_id': 'TEXT',
        })
        # Sổ duyệt plan + điểm đánh giá plan (vòng 20, §4.1/§5 của plan). Bảng ở đây là
        # NGUỒN CHÂN LÝ: `.reviews/<identity>.json` trong workspace chỉ là bản hiển thị, và
        # không bao giờ là căn cứ để cho phép hay từ chối một lần ghi plan (file nằm trong
        # tầm tay của agent). Khoá chính `(identity, version)` nên quyết định mới cùng bản
        # ghi đè quyết định cũ của ĐÚNG bản đó — duyệt v1 không bao giờ chạm tới v2.
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS plan_reviews (
                identity TEXT NOT NULL, version INTEGER NOT NULL,
                decision TEXT NOT NULL CHECK(decision IN ('approved','changes_requested')),
                note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'plan-tab',
                session_id TEXT, decided_at REAL NOT NULL,
                content_size INTEGER, content_modified_at TEXT,
                PRIMARY KEY (identity, version));
            CREATE TABLE IF NOT EXISTS plan_evaluations (
                identity TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                total INTEGER NOT NULL, verdict TEXT NOT NULL, evaluated_at REAL NOT NULL,
                PRIMARY KEY (identity, version));
        ''')
        # Vòng 25 (D-33) — hai sổ của VÒNG LẶP KẾ HOẠCH. `plan_verifications` là phán quyết của
        # người phản biện độc lập cho ĐÚNG một bản ghi: không có hàng ở đây thì cổng duyệt
        # (`PLAN_APPROVAL_UNVERIFIED`) từ chối lời xin duyệt của bản đó. `plan_owners` giữ đường
        # từ nhóm kế hoạch về phiên đã ghi nó — thứ mà tab Plan cần để mở một lượt thật thay vì
        # chỉ ghi sổ rồi im lặng (BUG-2 đo được: `plan_reviews.session_id` toàn `NULL`).
        # `resumed` là cột cộng thêm của hàng duyệt: nó nói lượt đã được mở lại thật hay chưa.
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS plan_verifications (
                identity TEXT NOT NULL, version INTEGER NOT NULL,
                verdict TEXT NOT NULL CHECK(verdict IN ('ok','revise')),
                issues TEXT NOT NULL DEFAULT '[]', summary TEXT NOT NULL DEFAULT '',
                critic_session_id TEXT, critic_answer_chars INTEGER, critic_verdict TEXT,
                created REAL NOT NULL,
                PRIMARY KEY (identity, version));
            CREATE TABLE IF NOT EXISTS plan_owners (
                identity TEXT PRIMARY KEY, session_id TEXT NOT NULL, first_session_id TEXT NOT NULL,
                slug TEXT NOT NULL DEFAULT '', relative_path TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1, created REAL NOT NULL, updated REAL NOT NULL);
        ''')
        self._add_missing_columns('plan_reviews', {'resumed': 'INTEGER NOT NULL DEFAULT 0'})
        # Vòng 22 (peer mesh) T1 — sổ con + bảng giao hàng. Hai bảng này là NGUỒN CHÂN LÝ cho
        # "phiên này sinh con nào, ở lượt nào, đã giao kết quả cho ai": `runtime.delegate` ghi,
        # `peer_read`/`await_children` đọc, watchdog quét. Khoá `UNIQUE(child_id, recipient,
        # recipient_turn)` biến "không giao hai lần" thành chuyện KHÔNG-THỂ, không phải một lời hứa.
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS children (
                session_id TEXT PRIMARY KEY, parent_id TEXT NOT NULL,
                parent_turn INTEGER NOT NULL DEFAULT 0, spawn_step INTEGER NOT NULL DEFAULT 0,
                role TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'started',
                reason TEXT,
                deliveries TEXT NOT NULL DEFAULT '[]',
                waiting_for TEXT NOT NULL DEFAULT '[]',
                waiting_since REAL, started REAL NOT NULL, finished REAL,
                steps_used INTEGER, output_tokens INTEGER, answer_chars INTEGER);
            CREATE INDEX IF NOT EXISTS children_parent ON children(parent_id, parent_turn);
            CREATE TABLE IF NOT EXISTS child_deliveries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                child_id TEXT NOT NULL, recipient TEXT NOT NULL, recipient_turn INTEGER NOT NULL DEFAULT 0,
                kind TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                chars INTEGER NOT NULL DEFAULT 0, truncated INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL, injected REAL, skip_reason TEXT,
                UNIQUE(child_id, recipient, recipient_turn));
        ''')
        # Vòng 27 (đợt 3, B-1) — SỔ NGUỒN: mỗi khẳng định của một hồ sơ research gắn một dòng ở
        # đây (URL thật + đoạn trích nguyên văn + ngày lấy + tầng + nguồn tin gốc). `UNIQUE(session_id,
        # row_id)` biến "hai dòng cùng mã" thành chuyện KHÔNG-THỂ, và `row_id` do harness cấp (`r12`)
        # nên hồ sơ trỏ được vào đúng dòng mà không cần biết id tự tăng.
        # `research_dossiers` là chỉ mục các bản hồ sơ đã ghi trong workspace (`.research/<slug>/vN-<slug>.md`).
        # `session_steers` là hàng đợi chỉ thị giữa lượt của chủ nhà (vòng 27 đợt 7, D-43): `claim_steers`
        # giành MỘT lần rồi bơm vào transcript ở ranh giới bước, y như `child_deliveries`.
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS source_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                child_id TEXT,
                job TEXT,
                row_id TEXT NOT NULL,
                claim TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                host TEXT NOT NULL DEFAULT '',
                tier INTEGER NOT NULL DEFAULT 4,
                type TEXT NOT NULL DEFAULT 'normal',
                excerpt TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL DEFAULT '',
                origin TEXT,
                method TEXT,
                source_row_id TEXT,
                status TEXT NOT NULL DEFAULT 'unverified',
                fingerprint TEXT NOT NULL DEFAULT '',
                payload TEXT NOT NULL DEFAULT '{}',
                branches TEXT NOT NULL DEFAULT '[]',
                research_id TEXT NOT NULL DEFAULT '',
                turn INTEGER NOT NULL DEFAULT 0,
                step INTEGER,
                created REAL NOT NULL,
                UNIQUE(session_id, row_id));
            CREATE INDEX IF NOT EXISTS source_ledger_session ON source_ledger(session_id, id);
            CREATE TABLE IF NOT EXISTS research_dossiers (
                research_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                profile TEXT NOT NULL DEFAULT '',
                level INTEGER NOT NULL DEFAULT 0,
                critique TEXT NOT NULL DEFAULT 'none',
                gate TEXT NOT NULL DEFAULT 'clear',
                rows INTEGER NOT NULL DEFAULT 0,
                bytes INTEGER NOT NULL DEFAULT 0,
                content_hash TEXT NOT NULL DEFAULT '',
                quality_ok INTEGER NOT NULL DEFAULT 0,
                created REAL NOT NULL,
                PRIMARY KEY (research_id, version));
            CREATE TABLE IF NOT EXISTS session_steers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                turn INTEGER NOT NULL DEFAULT 0,
                text TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                created REAL NOT NULL,
                injected REAL);
            CREATE INDEX IF NOT EXISTS session_steers_pending ON session_steers(session_id, state, id);
            CREATE TABLE IF NOT EXISTS research_verifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                research_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                verdict TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'critique',
                issues TEXT NOT NULL DEFAULT '[]',
                summary TEXT NOT NULL DEFAULT '',
                critic_session_id TEXT,
                critic_answer_chars INTEGER NOT NULL DEFAULT 0,
                critic_verdict TEXT,
                created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS research_verifications_job ON research_verifications(research_id, id);
            CREATE TABLE IF NOT EXISTS research_jobs (
                research_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'scoping',
                revision INTEGER NOT NULL DEFAULT 1,
                created REAL NOT NULL,
                updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS research_jobs_session ON research_jobs(session_id, updated);
            CREATE TABLE IF NOT EXISTS research_sources (
                source_id TEXT NOT NULL, session_id TEXT NOT NULL,
                url TEXT NOT NULL, normalized_url TEXT NOT NULL,
                host TEXT NOT NULL DEFAULT '', origin TEXT,
                PRIMARY KEY(session_id, source_id), UNIQUE(session_id, normalized_url));
            CREATE TABLE IF NOT EXISTS research_passages (
                passage_id TEXT NOT NULL, session_id TEXT NOT NULL,
                source_id TEXT NOT NULL, excerpt TEXT NOT NULL,
                excerpt_hash TEXT NOT NULL, locator TEXT NOT NULL DEFAULT '{}',
                extraction_method TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(session_id, passage_id),
                UNIQUE(session_id, source_id, excerpt_hash));
            CREATE TABLE IF NOT EXISTS research_claims (
                claim_id TEXT NOT NULL, session_id TEXT NOT NULL,
                text TEXT NOT NULL, text_hash TEXT NOT NULL,
                PRIMARY KEY(session_id, claim_id), UNIQUE(session_id, text_hash));
            CREATE TABLE IF NOT EXISTS research_relations (
                session_id TEXT NOT NULL, row_id TEXT NOT NULL,
                passage_id TEXT NOT NULL, claim_id TEXT NOT NULL,
                proposed_by TEXT,
                PRIMARY KEY(session_id, passage_id, claim_id));
            CREATE TABLE IF NOT EXISTS research_assessments (
                session_id TEXT NOT NULL, passage_id TEXT NOT NULL,
                claim_id TEXT NOT NULL, reviewer_id TEXT NOT NULL,
                content_hash TEXT NOT NULL, relation TEXT NOT NULL,
                rationale TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(session_id, passage_id, claim_id, reviewer_id, content_hash));
            CREATE TABLE IF NOT EXISTS research_snapshots (
                ref TEXT PRIMARY KEY, scope_id TEXT NOT NULL,
                normalized_url TEXT NOT NULL, entry TEXT NOT NULL,
                created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS research_snapshots_url
                ON research_snapshots(scope_id, normalized_url, created);
            CREATE TABLE IF NOT EXISTS plan_research_dependencies (
                identity TEXT NOT NULL, version INTEGER NOT NULL,
                research_id TEXT NOT NULL, research_version INTEGER NOT NULL,
                research_hash TEXT NOT NULL, created REAL NOT NULL,
                PRIMARY KEY(identity, version, research_id));
        ''')
        # P2 (§5.5, §5.7): hai bảng MỚI của mô hình bằng chứng. Vì sao bảng mới chứ không sửa bảng cũ:
        # `research_claims.claim_id` là băm của VĂN BẢN và dùng chung giữa các phiên, nên không được
        # nhét mức tin cậy của MỘT run vào đó; `research_facets` thì chỉ có nghĩa trong một run.
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS research_claim_meta (
                research_id TEXT NOT NULL, claim_id TEXT NOT NULL,
                question_id TEXT NOT NULL DEFAULT '', facet_id TEXT NOT NULL DEFAULT '',
                claim_type TEXT NOT NULL DEFAULT 'inference',
                stance_origin TEXT NOT NULL DEFAULT 'agent-inference',
                confidence TEXT NOT NULL DEFAULT 'unknown',
                confidence_cap TEXT NOT NULL DEFAULT 'unknown',
                basis TEXT NOT NULL DEFAULT '{}', as_of TEXT NOT NULL DEFAULT '',
                updated REAL NOT NULL,
                PRIMARY KEY(research_id, claim_id));
            CREATE INDEX IF NOT EXISTS research_claim_meta_run
                ON research_claim_meta(research_id, claim_type);
            CREATE TABLE IF NOT EXISTS research_facets (
                research_id TEXT NOT NULL, facet_id TEXT NOT NULL,
                question_id TEXT NOT NULL DEFAULT '', label TEXT NOT NULL DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'direction', terms TEXT NOT NULL DEFAULT '[]',
                priority TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'unexplored',
                seed_source TEXT NOT NULL DEFAULT 'agent', evidence_count INTEGER NOT NULL DEFAULT 0,
                origin_clusters INTEGER NOT NULL DEFAULT 0, last_new_ratio REAL NOT NULL DEFAULT -1.0,
                note TEXT NOT NULL DEFAULT '', updated REAL NOT NULL,
                PRIMARY KEY(research_id, facet_id));
            CREATE INDEX IF NOT EXISTS research_facets_status
                ON research_facets(research_id, status);
        ''')
        # P2: cột mới của sổ nguồn (ngày, phiên bản, loại nguồn, cụm gốc, mức truy cập). Cột cộng
        # thêm: hàng cũ đọc ra `''`/`'snippet'`, và cổng thời gian coi `''` là "không rõ ngày".
        self._add_missing_columns('source_ledger', {
            'published_at': "TEXT NOT NULL DEFAULT ''", 'updated_at': "TEXT NOT NULL DEFAULT ''",
            'version_label': "TEXT NOT NULL DEFAULT ''", 'source_kind': "TEXT NOT NULL DEFAULT ''",
            'origin_cluster': "TEXT NOT NULL DEFAULT ''",
            'access_level': "TEXT NOT NULL DEFAULT 'snippet'",
            'section_kind': "TEXT NOT NULL DEFAULT ''", 'event_date': "TEXT NOT NULL DEFAULT ''"})
        self._add_missing_columns('research_sources', {
            'published_at': "TEXT NOT NULL DEFAULT ''", 'updated_at': "TEXT NOT NULL DEFAULT ''",
            'version_label': "TEXT NOT NULL DEFAULT ''", 'source_kind': "TEXT NOT NULL DEFAULT ''",
            'origin_cluster': "TEXT NOT NULL DEFAULT ''",
            'access_level_max': "TEXT NOT NULL DEFAULT 'snippet'",
            'research_id': "TEXT NOT NULL DEFAULT ''"})
        self._add_missing_columns('research_passages', {
            'access_level': "TEXT NOT NULL DEFAULT 'snippet'", 'section_kind': "TEXT NOT NULL DEFAULT ''",
            'event_date': "TEXT NOT NULL DEFAULT ''", 'research_id': "TEXT NOT NULL DEFAULT ''"})
        self._add_missing_columns('research_dossiers', {'content_hash': "TEXT NOT NULL DEFAULT ''"})
        self._add_missing_columns('research_dossiers', {'quality_ok': 'INTEGER NOT NULL DEFAULT 0'})
        self._add_missing_columns('research_verifications', {'mode': "TEXT NOT NULL DEFAULT 'critique'"})
        # Bộ đếm lượt của phiên (T2 đọc nó để mọi event mang `turn`). Cột thêm kiểu cộng thêm:
        # phiên cũ đọc ra `0` rồi lượt kế tiếp bắt đầu từ 1.
        self._add_missing_columns('sessions', {'turn_count': 'INTEGER NOT NULL DEFAULT 0'})
        self.db.execute("UPDATE sessions SET status='interrupted' WHERE status IN ('running','awaiting_decision')")
        self.db.commit()

    def _add_missing_columns(self, table, columns):
        """Thêm cột còn thiếu, không bao giờ làm sập khởi động.

        Một lượt sửa lỗi hỏng (file DB khoá, đĩa đầy) không được biến cả harness thành không khởi
        động được: hàm này ghi lại việc bỏ qua và để `checkpoint()` tự chọn câu INSERT khớp với
        cột thật đang có.
        """
        try:
            have = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
        except sqlite3.DatabaseError:
            self._missing_columns = set(columns)
            return
        for name, kind in columns.items():
            if name in have:
                continue
            try:
                self.db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
            except sqlite3.DatabaseError:
                continue
        return None

    def create(self, config, role='orchestrator', parent_id=None):
        sid = uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT INTO sessions(id,parent_id,role,config,updated) VALUES(?,?,?,?,?)',
                            (sid, parent_id, role, json.dumps(config), time.time()))
        return self.get(sid)

    def get(self, sid):
        row = self.db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
        if row is None:
            raise KeyError('Session not found')
        result = dict(row)
        result['messages'] = json.loads(result['messages'])
        result['config'] = json.loads(result['config'])
        return result

    def save(self, sid, messages, status=None):
        with self.db:
            self.db.execute('UPDATE sessions SET messages=?,status=COALESCE(?,status),updated=? WHERE id=?',
                            (json.dumps(messages, ensure_ascii=False), status, time.time(), sid))

    def update_config(self, sid, config):
        with self.db:
            self.db.execute('UPDATE sessions SET config=?,updated=? WHERE id=?',
                            (json.dumps(config, ensure_ascii=False), time.time(), sid))

    def all_configs(self):
        """`{session id: config}` của mọi phiên đã lưu, kể cả phiên con.

        Dùng cho lượt sửa lúc khởi động (cửa sổ ngữ cảnh của các phiên cũ): một
        phiên giữ nguyên con số harness ghi lúc nó được tạo, còn router có thể đã
        biết con số đúng hơn. Một dòng config hỏng bị bỏ qua chứ không làm sập cả
        lượt đọc — hàng đợi sửa lỗi không được phép biến một dòng cũ thành lỗi khởi động.
        """
        result = {}
        for row in self.db.execute('SELECT id, config FROM sessions'):
            try:
                result[row['id']] = json.loads(row['config'])
            except (TypeError, ValueError):
                continue
        return result

    def emit(self, sid, kind, payload):
        with self.db:
            cur = self.db.execute('INSERT INTO events(session_id,kind,payload,created) VALUES(?,?,?,?)',
                                  (sid, kind, json.dumps(payload, ensure_ascii=False), time.time()))
        return cur.lastrowid

    def events(self, sid, after=0):
        self.get(sid)
        return [{'seq': r['seq'], 'type': r['kind'], 'data': json.loads(r['payload']), 'created': r['created']}
                for r in self.db.execute('SELECT * FROM events WHERE session_id=? AND seq>? ORDER BY seq LIMIT 500', (sid, after))]

    def events_tail(self, sid, limit=500):
        self.get(sid)
        rows = self.db.execute('SELECT * FROM events WHERE session_id=? ORDER BY seq DESC LIMIT ?',
                               (sid, int(limit))).fetchall()
        return [{'seq': r['seq'], 'type': r['kind'], 'data': json.loads(r['payload']),
                 'created': r['created']} for r in reversed(rows)]

    def list(self, limit=50):
        rows = self.db.execute(
            'SELECT id, role, config, status, updated FROM sessions WHERE parent_id IS NULL ORDER BY updated DESC LIMIT ?',
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            item = dict(r)
            try:
                item['config'] = json.loads(item['config'])
            except Exception:
                pass
            result.append(item)
        return result

    def checkpoint(self, sid, messages, reason, numbers=None):
        """Ghi một hàng checkpoint, kèm số đo khi có (N4).

        `numbers` là `{'before_estimate', 'after_estimate', 'context_window', 'model_id'}` — thiếu
        khoá nào thì cột đó `NULL`. Không có `numbers` thì câu INSERT y hệt bản cũ, nên mọi caller
        cũ và mọi test cũ giữ nguyên hành vi.
        """
        with self.db:
            if numbers:
                columns = [name for name in ('before_estimate', 'after_estimate', 'context_window', 'model_id')
                           if name in self._checkpoint_columns()]
                self.db.execute(
                    f'INSERT INTO checkpoints(session_id,messages,reason,created,{",".join(columns)}) '
                    f'VALUES(?,?,?,?,{",".join("?" for _ in columns)})',
                    (sid, json.dumps(messages, ensure_ascii=False), reason, time.time(),
                     *[numbers.get(name) for name in columns]))
                return
            self.db.execute('INSERT INTO checkpoints(session_id,messages,reason,created) VALUES(?,?,?,?)',
                            (sid, json.dumps(messages, ensure_ascii=False), reason, time.time()))

    def _checkpoint_columns(self):
        """Tên cột thật của bảng `checkpoints` (cache một lần cho mỗi kết nối)."""
        cached = getattr(self, '_checkpoint_column_cache', None)
        if cached is None:
            try:
                cached = {row['name'] for row in self.db.execute('PRAGMA table_info(checkpoints)')}
            except sqlite3.DatabaseError:
                cached = {'session_id', 'messages', 'reason', 'created'}
            self._checkpoint_column_cache = cached
        return cached

    def checkpoints(self, sid, limit=200):
        """Các hàng checkpoint của một phiên, cũ nhất trước — có kèm số đo nếu hàng đó có."""
        self.get(sid)
        rows = self.db.execute('SELECT * FROM checkpoints WHERE session_id=? ORDER BY id LIMIT ?',
                               (sid, limit)).fetchall()
        return [{**dict(row), 'messages': json.loads(row['messages'])} for row in rows]

    def journal_add(self, sid, kind, text, payload=None):
        """Một bản ghi nhật ký (A2). Chỉ ghi thêm: không sửa, không xoá, không đánh số lại."""
        with self.db:
            cur = self.db.execute(
                'INSERT INTO journal(session_id,kind,text,payload,created) VALUES(?,?,?,?,?)',
                (sid, kind, text, json.dumps(payload or {}, ensure_ascii=False), time.time()))
        return cur.lastrowid

    def journal_patch(self, sid, seq, payload):
        """Gán mã đã mint cho một hàng vừa tạo trong **cùng một lượt ghi** (`journal_add` → đây).

        Nhật ký là bản chỉ-ghi-thêm, nên hàm này cố ý chỉ sửa được `payload` (nơi giữ mã) và chỉ
        dành cho hàng vừa tạo: mã `T:<sid8>-<n>` cần số `seq` mà SQLite chỉ trả về *sau* khi chèn.
        """
        with self.db:
            self.db.execute('UPDATE journal SET payload=? WHERE session_id=? AND seq=?',
                            (json.dumps(payload or {}, ensure_ascii=False), sid, seq))

    def journal_tail(self, sid, limit=50, kinds=None):
        """`limit` bản ghi mới nhất của một phiên, đọc theo thứ tự cũ → mới."""
        self.get(sid)
        sql = 'SELECT * FROM journal WHERE session_id=?'
        args = [sid]
        if kinds:
            sql += f' AND kind IN ({",".join("?" for _ in kinds)})'
            args += list(kinds)
        sql += ' ORDER BY seq DESC LIMIT ?'
        args.append(limit)
        rows = self.db.execute(sql, args).fetchall()
        result = []
        for row in reversed(rows):
            item = dict(row)
            try:
                item['payload'] = json.loads(item['payload'])
            except (TypeError, ValueError):
                item['payload'] = {}
            result.append(item)
        return result

    # ------------------------------------------------------------------
    # Vòng 22 (peer mesh) T1 — sổ con, biên nhận giao hàng, bộ đếm lượt
    #
    # Ba thứ này đi cùng nhau vì cùng trả lời một câu: "phiên này đã sinh con nào, ở lượt nào, và
    # kết quả của con đã tới tay ai". Hàng `sessions` vẫn là nguồn chân lý cho phiên; hai bảng
    # dưới đây chỉ THÊM, không thay thế hàng nào.
    # ------------------------------------------------------------------
    def begin_turn(self, sid):
        """Số lượt kế tiếp của phiên (một chiều, không bao giờ lùi).

        Đọc–tăng–ghi trong **một** transaction, nên hai lượt không thể nhận cùng một số.
        """
        with self.db:
            row = self.db.execute('SELECT turn_count FROM sessions WHERE id=?', (sid,)).fetchone()
            if row is None:
                raise KeyError('Session not found')
            turn = int(row['turn_count'] or 0) + 1
            self.db.execute('UPDATE sessions SET turn_count=? WHERE id=?', (turn, sid))
        return turn

    def child_start(self, child_id, parent_id, turn, step, role, goal=''):
        """Ghi hàng sổ con lúc con được sinh; gọi lại thì cập nhật chỗ sinh chứ không nhân hàng."""
        with self.db:
            self.db.execute(
                'INSERT INTO children(session_id,parent_id,parent_turn,spawn_step,role,goal,status,started)'
                        ' VALUES(?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(session_id) DO UPDATE SET parent_id=excluded.parent_id,'
                ' parent_turn=excluded.parent_turn, spawn_step=excluded.spawn_step,'
                ' role=excluded.role, goal=excluded.goal, started=excluded.started',
                (child_id, parent_id, int(turn or 0), int(step or 0), role, str(goal or ''),
                 'started', time.time()))
        return self.child(child_id)

    def child_finish(self, child_id, status, reason=None, steps_used=None, output_tokens=None,
                     answer_chars=None):
        """Đóng hàng sổ con. Chỉ hàng còn `started` mới đổi được ⇒ lần gọi thứ hai không đổi gì."""
        with self.db:
            self.db.execute(
                "UPDATE children SET status=?, reason=?, finished=?, steps_used=?, output_tokens=?,"
                " answer_chars=?, waiting_for='[]', waiting_since=NULL"
                " WHERE session_id=? AND status='started'",
                (status, reason, time.time(), steps_used, output_tokens, answer_chars, child_id))
        return self.child(child_id)

    def child_usage_from_events(self, child_id):
        """Số bước/token một phiên con ĐÃ tiêu, đọc từ chính luồng của nó: `(steps, tokens)`.

        Đường đóng sổ bình thường (`finish` của con) tự mang bộ số này; hai đường còn lại — T7 dọn
        con khi lượt cha đóng và T10 watchdog cắt con quá hạn — đóng một phiên con **đang chạy**,
        nên không có `finish` nào để đọc. Bỏ qua chúng thì `childSteps`/`childTokens` của lượt cha
        (T13) đếm thiếu đúng phần con đã tiêu trước khi bị cắt: đo được thì phải ghi được.
        `stepsUsed` trong `turn_end` là số luỹ kế của lượt ⇒ lấy `max`; `outputTokens` là của từng
        bước ⇒ cộng.
        """
        steps = tokens = 0
        for row in self.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='turn_end'",
                                   (child_id,)):
            try:
                data = json.loads(row['payload'])
            except ValueError:
                continue
            steps = max(steps, int(data.get('stepsUsed') or 0))
            tokens += int(data.get('outputTokens') or 0)
        return steps, tokens

    def child_close_once(self, child_id, status, reason=None, steps_used=None, output_tokens=None):
        """Đóng hàng sổ con và CHỈ trả hàng khi chính NGƯỜI GỌI NÀY vừa đóng nó.

        `child_finish` nói kết quả cuối cùng; hàm này nói AI đã đóng. Hai đường cùng đóng một hàng
        (callback của `delegate_task` với watchdog T10, hoặc hai watchdog) thì đúng một bên nhận
        `rowcount == 1`, nên đúng một event `child` được phát và người đọc không thấy hai lý do
        khác nhau cho cùng một cái chết.
        """
        with self.db:
            cursor = self.db.execute(
                "UPDATE children SET status=?, reason=?, finished=?, waiting_for='[]', waiting_since=NULL,"
                " steps_used=COALESCE(?, steps_used), output_tokens=COALESCE(?, output_tokens)"
                " WHERE session_id=? AND status='started'",
                (status, reason, time.time(), steps_used, output_tokens, child_id))
            if cursor.rowcount != 1:
                return None
        return self.child(child_id)

    def child(self, child_id):
        """Một hàng sổ con (đã giải JSON), hoặc `None` khi chưa có hàng nào."""
        row = self.db.execute('SELECT * FROM children WHERE session_id=?', (child_id,)).fetchone()
        return self._child_view(row) if row is not None else None

    @staticmethod
    def _child_view(row):
        item = dict(row)
        for key in ('deliveries', 'waiting_for'):
            try:
                item[key] = json.loads(item[key] or '[]')
            except (TypeError, ValueError):
                item[key] = []
        return item

    def children_of(self, parent_id, turn=None):
        """Con của một cha (lọc theo `parent_turn` khi có), cũ → mới."""
        sql = 'SELECT * FROM children WHERE parent_id=?'
        args = [parent_id]
        if turn is not None:
            sql += ' AND parent_turn=?'
            args.append(int(turn))
        sql += ' ORDER BY started, session_id'
        return [self._child_view(r) for r in self.db.execute(sql, args).fetchall()]

    def live_children(self, parent_id=None):
        """Hàng sổ con còn `started` — mọi cha khi `parent_id=None` (watchdog quét đường này)."""
        if parent_id is None:
            rows = self.db.execute("SELECT * FROM children WHERE status='started' ORDER BY started").fetchall()
        else:
            rows = self.db.execute("SELECT * FROM children WHERE parent_id=? AND status='started'"
                                   ' ORDER BY started', (parent_id,)).fetchall()
        return [self._child_view(r) for r in rows]

    def children_summary(self, parent_id, turn=None):
        """Số con của một cha trong MỘT truy vấn (T13) — `turn` để đo theo LƯỢT, `None` là cả phiên.

        Hai người đọc, hai câu hỏi: `session_metrics` hỏi "phiên này đã sinh bao nhiêu con" (cả
        phiên), còn `peer_turn_cost` hỏi "LƯỢT này tốn bao nhiêu" và phải lọc `parent_turn` —
        không lọc thì payload `finish` của lượt thứ ba báo số luỹ kế (BUG-56).

        Vì sao một truy vấn chứ không phải đếm bằng vòng lặp: `session_metrics` được gọi ở mỗi lần
        mở một phiên, còn một vòng lặp là một truy vấn cho mỗi con. `failed` gom mọi trạng thái cuối
        KHÔNG phải `completed`/`partial` — kể cả `cancelled`/`interrupted`/`not_found` — vì câu hỏi
        của người đọc là "bao nhiêu con không trả được kết quả", còn chi tiết nằm ở cột `reason`.
        """
        where, args = 'parent_id=?', [parent_id]
        if turn is not None:
            where += ' AND parent_turn=?'
            args.append(int(turn))
        row = self.db.execute(
            'SELECT COUNT(*) AS spawned,'
            " SUM(CASE WHEN status='started' THEN 1 ELSE 0 END) AS running,"
            " SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) AS completed,"
            " SUM(CASE WHEN status='partial' THEN 1 ELSE 0 END) AS partial,"
            " SUM(CASE WHEN status NOT IN ('started','completed','partial') THEN 1 ELSE 0 END) AS failed,"
            ' SUM(COALESCE(steps_used,0)) AS steps, SUM(COALESCE(output_tokens,0)) AS tokens,'
            ' SUM(COALESCE(answer_chars,0)) AS answerChars,'
            ' (SELECT COUNT(*) FROM child_deliveries WHERE child_id IN'
            f'  (SELECT session_id FROM children WHERE {where})) AS deliveries'
            f' FROM children WHERE {where}', tuple(args + args)).fetchone()
        numbers = {key: int(row[key] or 0) for key in
                   ('spawned', 'running', 'completed', 'partial', 'failed', 'steps', 'tokens',
                    'answerChars', 'deliveries')}
        return {'spawned': numbers['spawned'], 'running': numbers['running'],
                'completed': numbers['completed'], 'partial': numbers['partial'],
                'failed': numbers['failed'], 'childSteps': numbers['steps'],
                'childTokens': numbers['tokens'], 'childAnswerChars': numbers['answerChars'],
                'deliveries': numbers['deliveries']}

    def child_wait(self, child_id, targets=None, since=None):
        """Ghi/bỏ trạng thái "đang chờ" của một con.

        `waiting_for` là bản ghi trong DB (giao diện KHÔNG đọc: nó vẽ theo event `peer_wait` của
        luồng đang mở), `waiting_since` là mốc thời gian watchdog luật 3 đọc để đánh thức cưỡng bức.
        """
        with self.db:
            self.db.execute('UPDATE children SET waiting_for=?, waiting_since=? WHERE session_id=?',
                            (json.dumps(list(targets or []), ensure_ascii=False), since, child_id))
        return self.child(child_id)

    def child_set_deliveries(self, child_id, receipts):
        """Ghim danh sách biên nhận (`[{recipient,state,chars,truncated}]`) vào hàng sổ con."""
        with self.db:
            self.db.execute('UPDATE children SET deliveries=? WHERE session_id=?',
                            (json.dumps(list(receipts or []), ensure_ascii=False), child_id))
        return self.child(child_id)

    def queue_delivery(self, child_id, recipient, recipient_turn, kind, chars=0, truncated=False):
        """Ghi một biên nhận `pending`; giao lặp trả **hàng cũ** thay vì ghi thêm.

        `IntegrityError` ở đây là chuyện bình thường (đường kết thúc bình thường và watchdog cùng
        gọi), không phải lỗi — nên bắt rồi trả hàng đã có.
        """
        turn = int(recipient_turn or 0)
        try:
            with self.db:
                cur = self.db.execute(
                    'INSERT INTO child_deliveries(child_id,recipient,recipient_turn,kind,state,chars,'
                    ' truncated,created) VALUES(?,?,?,?,?,?,?,?)',
                    (child_id, recipient, turn, kind, 'pending', int(chars or 0),
                     1 if truncated else 0, time.time()))
            return self.delivery(cur.lastrowid)
        except sqlite3.IntegrityError:
            row = self.db.execute('SELECT * FROM child_deliveries WHERE child_id=? AND recipient=?'
                                  ' AND recipient_turn=?', (child_id, recipient, turn)).fetchone()
            return dict(row) if row is not None else None

    def delivery(self, delivery_id):
        """Một hàng biên nhận, hoặc `None`."""
        row = self.db.execute('SELECT * FROM child_deliveries WHERE id=?', (delivery_id,)).fetchone()
        return dict(row) if row is not None else None

    def pending_deliveries(self, sid, limit=4):
        """Biên nhận đang chờ bơm vào transcript của `sid` (cũ → mới, có trần)."""
        rows = self.db.execute("SELECT * FROM child_deliveries WHERE recipient=? AND state='pending'"
                               ' ORDER BY id LIMIT ?', (sid, int(limit))).fetchall()
        return [dict(r) for r in rows]

    def claim_deliveries(self, recipient, limit=4):
        """Giành các biên nhận `pending` của một phiên để bơm vào transcript — **một lần**.

        `UPDATE … WHERE state='pending'` là chỗ chốt chống bơm hai lần: hàng nào đã bị
        người khác giành thì `rowcount == 0` và không nằm trong kết quả. Đọc và đổi nằm
        trong **một** transaction, nên không có cửa sổ nào để hai nhịp cùng thấy một hàng.
        """
        claimed = []
        with self.db:
            rows = self.db.execute(
                "SELECT * FROM child_deliveries WHERE recipient=? AND state='pending'"
                ' ORDER BY id LIMIT ?', (recipient, int(limit))).fetchall()
            for row in rows:
                cursor = self.db.execute("UPDATE child_deliveries SET state='injected', injected=?"
                                         " WHERE id=? AND state='pending'", (time.time(), row['id']))
                if cursor.rowcount == 1:
                    claimed.append(dict(row))
        return claimed

    def mark_delivered(self, delivery_id, state='injected', skip_reason=None):
        """Chuyển `pending` → `injected`/`skipped` trong một transaction; trả hàng sau khi đổi."""
        if state not in ('injected', 'skipped'):
            raise ValueError("state must be 'injected' or 'skipped'")
        with self.db:
            self.db.execute("UPDATE child_deliveries SET state=?, injected=?, skip_reason=?"
                            " WHERE id=? AND state='pending'",
                            (state, time.time(), skip_reason, int(delivery_id)))
        return self.delivery(delivery_id)

    def deliveries_of(self, child_id):
        """Mọi biên nhận của một con, cũ → mới (đường đọc cho event và cho sổ con)."""
        rows = self.db.execute('SELECT * FROM child_deliveries WHERE child_id=? ORDER BY id',
                               (child_id,)).fetchall()
        return [dict(r) for r in rows]

    def child_delivery_receipts(self, child_id):
        """Biên nhận gọn để nhét vào dict kết quả/event: `{recipient,state,chars,truncated}`."""
        receipts = []
        for row in self.deliveries_of(child_id):
            receipt = {'recipient': row['recipient'], 'state': row['state'],
                       'chars': row['chars'], 'truncated': bool(row['truncated'])}
            if row['state'] == 'skipped' and row['skip_reason']:
                # Lý do bỏ qua phải tới được người đọc: "không giao" mà im lặng thì không
                # phân biệt được với "giao rồi".
                receipt['reason'] = row['skip_reason']
            receipts.append(receipt)
        return receipts

    # ------------------------------------------------------------------
    # Sổ duyệt plan (vòng 20 §4.1) + điểm đánh giá P1–P8 (§5)
    #
    # Hai đường ghi vào `plan_reviews`, đúng hai đường của plan:
    #   * UI: route `POST /api/agent/plans/review` (api/server.py) gọi `record_plan_review(..., source='plan-tab')`;
    #   * runtime: `settle()` gọi một lần khi quyết định mang `planIdentity`/`planVersion`:
    #         self.store.record_plan_review(identity, version,
    #             decision='approved' if status == 'approved' else 'changes_requested',
    #             note=(note or ''), source='approval', session_id=record['sessionId'])
    #     (chỉ khi record có đủ hai khoá — một `request_approval` cũ không mang chúng thì không ghi).
    # `plan_evaluations` do harness ghi sau mỗi lần chấm P1–P8, kể cả lần bị từ chối
    # (`written: false`) — đó là bằng chứng vì sao không có file nào xuất hiện.
    # ------------------------------------------------------------------
    PLAN_REVIEW_DECISIONS = ('approved', 'changes_requested')
    PLAN_REVIEW_SOURCES = ('plan-tab', 'approval')

    def record_plan_review(self, identity, version, decision, note='', source='plan-tab',
                           session_id=None, content_size=None, content_modified_at=None):
        """Ghi quyết định duyệt cho ĐÚNG một bản `(identity, version)`; trả hàng đã lưu.

        `content_size`/`content_modified_at` là số đo lúc duyệt: sau này chỉ mục của box
        báo số khác thì bản duyệt đó đã cũ (`reviewStale`) và KHÔNG còn được coi là đồng ý.
        """
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('plan review needs a non-empty identity')
        version = int(version)
        if version < 1:
            raise ValueError('plan review needs a positive version')
        if decision not in self.PLAN_REVIEW_DECISIONS:
            raise ValueError("decision must be one of: " + ', '.join(self.PLAN_REVIEW_DECISIONS))
        if source not in self.PLAN_REVIEW_SOURCES:
            raise ValueError("source must be one of: " + ', '.join(self.PLAN_REVIEW_SOURCES))
        with self.db:
            self.db.execute(
                'INSERT OR REPLACE INTO plan_reviews'
                '(identity,version,decision,note,source,session_id,decided_at,content_size,content_modified_at)'
                ' VALUES(?,?,?,?,?,?,?,?,?)',
                (identity, version, decision, str(note or ''), source, session_id, time.time(),
                 None if content_size is None else int(content_size), content_modified_at))
        return self.plan_review(identity, version)

    def plan_review(self, identity, version):
        """Hàng sổ duyệt của một bản, hoặc `None` khi chưa ai quyết."""
        row = self.db.execute('SELECT * FROM plan_reviews WHERE identity=? AND version=?',
                              (identity, int(version))).fetchone()
        return dict(row) if row is not None else None

    def plan_reviews_for(self, identity):
        """Mọi quyết định của một identity, xếp theo version tăng dần (máy trạng thái đọc)."""
        rows = self.db.execute('SELECT * FROM plan_reviews WHERE identity=? ORDER BY version',
                               (identity,)).fetchall()
        return [dict(row) for row in rows]

    def record_plan_evaluation(self, identity, version, payload, total, verdict):
        """Ghi kết quả chấm P1-P8 của một bản; `payload` là JSON đã dựng ở harness."""
        with self.db:
            self.db.execute(
                'INSERT OR REPLACE INTO plan_evaluations(identity,version,payload,total,verdict,evaluated_at)'
                ' VALUES(?,?,?,?,?,?)',
                (identity, int(version), json.dumps(payload, ensure_ascii=False), int(total),
                 str(verdict), time.time()))
        return self.plan_evaluation(identity, version)

    def plan_evaluation(self, identity, version):
        """Kết quả chấm của một bản (payload đã giải JSON), hoặc `None` khi chưa chấm."""
        row = self.db.execute('SELECT * FROM plan_evaluations WHERE identity=? AND version=?',
                              (identity, int(version))).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item['payload'] = json.loads(item['payload'])
        except (TypeError, ValueError):
            item['payload'] = {}
        return item

    # ------------------------------------------------------------------
    # Vòng 25 (D-33) — sổ PHẢN BIỆN kế hoạch + sổ SỞ HỮU kế hoạch
    #
    # `plan_verifications` là phán quyết của người phản biện độc lập cho ĐÚNG một bản ghi.
    # Cổng duyệt (`PLAN_APPROVAL_UNVERIFIED`, runtime) đọc nó; giao diện đọc nó qua
    # `plan_verification_view`. Khoá `(identity, version)` nên phán quyết của bản mới KHÔNG
    # bao giờ ghi đè bản cũ — cùng luật với `plan_reviews`.
    # `plan_owners` giữ đường từ nhóm kế hoạch về PHIÊN GỐC đã ghi nó: đó là thứ tab Plan cần
    # để mở một lượt thật (`plan_reviews.session_id` đo được toàn `NULL` ở vòng 25).
    # ------------------------------------------------------------------

    def record_plan_verification(self, identity, version, verdict, issues=(), summary='',
                                 critic_session_id=None, critic_answer_chars=None, critic_verdict=None):
        """Ghi phán quyết phản biện cho một bản; trả hàng đã lưu.

        `critic_*` là DẤU VẾT: phiên phản biện nào, câu trả lời dài bao nhiêu, và verdict đọc
        được từ văn bản của chính nó. Cổng provenance đã kiểm trước khi gọi hàm này, nhưng hàng
        sổ vẫn phải giữ được bằng chứng — người đọc sau không chạy lại được lần đo đó.
        """
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('plan verification needs a non-empty identity')
        version = int(version)
        if version < 1:
            raise ValueError('plan verification needs a positive version')
        if verdict not in ('ok', 'revise'):
            raise ValueError("verdict must be 'ok' or 'revise'")
        rows = []
        for item in (issues or ()):
            if not isinstance(item, dict):
                continue
            rows.append({'severity': str(item.get('severity') or 'medium')[:16],
                         'text': str(item.get('text') or ''),
                         'fix': str(item.get('fix') or '')})
        with self.db:
            self.db.execute(
                'INSERT OR REPLACE INTO plan_verifications'
                '(identity,version,verdict,issues,summary,critic_session_id,critic_answer_chars,'
                ' critic_verdict,created) VALUES(?,?,?,?,?,?,?,?,?)',
                (identity, version, verdict, json.dumps(rows, ensure_ascii=False), str(summary or '')[:2000],
                 critic_session_id, None if critic_answer_chars is None else int(critic_answer_chars),
                 None if critic_verdict is None else str(critic_verdict), time.time()))
        return self.plan_verification(identity, version)

    def plan_verification(self, identity, version):
        """Hàng phán quyết của một bản (đã giải `issues`), hoặc `None` khi chưa ai phản biện."""
        row = self.db.execute('SELECT * FROM plan_verifications WHERE identity=? AND version=?',
                              (identity, int(version))).fetchone()
        if row is None:
            return None
        item = dict(row)
        try:
            item['issues'] = json.loads(item['issues'])
        except (TypeError, ValueError):
            item['issues'] = []
        return item

    def record_plan_owner(self, identity, session_id, slug='', relative_path='', version=1):
        """Ghi phiên GỐC sở hữu một nhóm kế hoạch; gọi lại thì cập nhật, không nhân hàng.

        `first_session_id` và `created` là dấu vết của lần ghi ĐẦU TIÊN và không bao giờ bị ghi
        đè: một kế hoạch được sửa từ phiên con vẫn phải mở lại được ở phiên gốc.
        """
        if not isinstance(identity, str) or not identity.strip():
            raise ValueError('plan owner needs a non-empty identity')
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('plan owner needs a session id')
        now = time.time()
        with self.db:
            self.db.execute(
                'INSERT INTO plan_owners(identity,session_id,first_session_id,slug,relative_path,'
                'version,created,updated) VALUES(?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(identity) DO UPDATE SET session_id=excluded.session_id,'
                ' slug=excluded.slug, relative_path=excluded.relative_path,'
                ' version=excluded.version, updated=excluded.updated',
                (identity, session_id, session_id, str(slug or ''), str(relative_path or ''),
                 int(version), now, now))
        return self.plan_owner(identity)

    def plan_owner(self, identity):
        """Hàng sở hữu của một nhóm kế hoạch, hoặc `None` khi harness chưa biết."""
        row = self.db.execute('SELECT * FROM plan_owners WHERE identity=?', (identity,)).fetchone()
        return dict(row) if row is not None else None

    def plan_written_at(self, session_ids, identity, version):
        """Epoch của hàng `plan_written` MỚI NHẤT khớp `(identity, version)` trong tập phiên.

        Đây là mốc thời gian của cổng provenance (M3): một phê bình chỉ có giá trị nếu phiên
        phản biện chạy SAU khi chính bản đó được ghi. Trả `None` khi không có hàng nào — và
        `None` làm cổng từ chối, không phải làm nó bỏ qua.
        """
        ids = [sid for sid in (session_ids or ()) if isinstance(sid, str) and sid]
        if not ids:
            return None
        marks = ','.join('?' * len(ids))
        rows = self.db.execute(
            f"SELECT payload, created FROM events WHERE kind='plan_written' "
            f"AND session_id IN ({marks}) ORDER BY seq", tuple(ids)).fetchall()
        found = None
        for row in rows:
            try:
                payload = json.loads(row['payload'])
            except (TypeError, ValueError):
                continue  # hàng hỏng bị BỎ QUA, không làm hỏng cả phép tìm
            if not isinstance(payload, dict):
                continue
            if payload.get('identity') != identity:
                continue
            try:
                row_version = int(payload.get('version'))
            except (TypeError, ValueError):
                continue
            if row_version == int(version):
                found = float(row['created'])
        return found

    def plan_written_record(self, session_ids, identity, version):
        """The exact saved plan event, including its content hash when available."""
        found = None
        for sid in session_ids:
            rows = self.db.execute("SELECT payload,created FROM events WHERE session_id=? "
                                   "AND kind='plan_written' ORDER BY seq", (sid,))
            for row in rows:
                try:
                    data = json.loads(row['payload'])
                except (TypeError, ValueError):
                    continue
                if data.get('identity') == identity and data.get('version') == version:
                    found = {**data, 'created': row['created'], 'sessionId': sid}
        return found

    def last_turn_status(self, sid):
        """Bộ số của hàng `turn_end` MỚI NHẤT: `{'turn','status','partial','code','at'}`.

        `sessions.status` là trạng thái của PHIÊN (một lượt dở vẫn để phiên `completed` — bất
        biến #1). Muốn nói được "lượt này dở" thì phải đọc chính hàng `turn_end`, và mã lý do
        nằm ở hàng `notice` bền (`partial: true`) mà `finish_partial` phát sau đó.
        """
        row = self.db.execute(
            "SELECT payload, created FROM events WHERE session_id=? AND kind='turn_end' "
            "ORDER BY seq DESC LIMIT 1", (sid,)).fetchone()
        if row is None:
            return None
        try:
            payload = json.loads(row['payload'])
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        status = str(payload.get('status') or '')
        partial = status == 'partial' or bool(payload.get('partial'))
        code = None
        if partial:
            notices = self.db.execute(
                "SELECT payload FROM events WHERE session_id=? AND kind='notice' ORDER BY seq DESC LIMIT 20",
                (sid,)).fetchall()
            for notice_row in notices:
                try:
                    notice = json.loads(notice_row['payload'])
                except (TypeError, ValueError):
                    continue
                if isinstance(notice, dict) and notice.get('partial'):
                    code = notice.get('code')
                    break
        return {'turn': payload.get('turn'), 'status': status, 'partial': partial, 'code': code,
                'at': float(row['created'])}

    def turn_boundary_epoch(self, sid):
        """Epoch bắt đầu LƯỢT đang chạy: hàng `events` `kind='user'` mới nhất.

        `start()` phát hàng `user` trước khi chạy lượt, nên đây là ranh giới lượt mà không cần
        thêm trạng thái trong bộ nhớ và không cần đồng hồ thứ hai (M3 đếm vòng `revise` từ đây).
        """
        row = self.db.execute(
            "SELECT created FROM events WHERE session_id=? AND kind='user' ORDER BY seq DESC LIMIT 1",
            (sid,)).fetchone()
        return None if row is None else float(row['created'])

    def set_plan_review_resumed(self, identity, version, resumed=True):
        """Đánh dấu hàng duyệt đã mở được lượt thật (`resumed`) — giao diện đọc để nói sự thật."""
        with self.db:
            self.db.execute('UPDATE plan_reviews SET resumed=? WHERE identity=? AND version=?',
                            (1 if resumed else 0, identity, int(version)))
        return self.plan_review(identity, version)

    def delete(self, sid):
        with self.db:
            child_rows = self.db.execute('SELECT id FROM sessions WHERE parent_id=?', (sid,)).fetchall()
            all_sids = [sid] + [r['id'] for r in child_rows]
            placeholders = ','.join('?' for _ in all_sids)
            self.db.execute(f'DELETE FROM checkpoints WHERE session_id IN ({placeholders})', all_sids)
            self.db.execute(f'DELETE FROM events WHERE session_id IN ({placeholders})', all_sids)
            self.db.execute(f'DELETE FROM sessions WHERE id IN ({placeholders})', all_sids)
            # Vòng 22 (T1): sổ con và biên nhận đi theo phiên — xoá phiên mà để lại hàng sổ con
            # thì watchdog sẽ đi tìm một phiên không còn tồn tại (và bắn event vào luồng đã xoá).
            self.db.execute(f'DELETE FROM children WHERE session_id IN ({placeholders})', all_sids)
            self.db.execute(f'DELETE FROM children WHERE parent_id IN ({placeholders})', all_sids)
            self.db.execute(f'DELETE FROM child_deliveries WHERE child_id IN ({placeholders})', all_sids)
            self.db.execute(f'DELETE FROM child_deliveries WHERE recipient IN ({placeholders})', all_sids)
            # Vòng 25 (D-33): HAI SỔ CỦA VÒNG LẶP KẾ HOẠCH **CỐ Ý** không nằm trong cascade này.
            # `plan_verifications`/`plan_owners` nói về một NHÓM KẾ HOẠCH, không về một phiên: cùng
            # một kế hoạch có thể được sửa ở phiên khác, và xoá phiên cũ mà làm biến mất phán quyết
            # phản biện của bản đang nằm trên đĩa thì cổng duyệt sẽ từ chối một bản đã được phản
            # biện thật. Xoá hàng `.plans/` mới là cách kết thúc vòng đời của một kế hoạch.
            #
            # Vòng 27 (đợt 3, B-1): `source_ledger`, `research_dossiers`, `session_steers` cũng **CỐ Ý**
            # KHÔNG nằm trong cascade — cùng một lý do. Sổ nguồn là BẰNG CHỨNG của một hồ sơ đang nằm
            # trên đĩa (`.research/<slug>/vN-<slug>.md` + `sources.jsonl`): hồ sơ vẫn đọc được sau khi
            # phiên bị xoá, và một sổ nguồn biến mất trong im lặng sẽ biến hồ sơ ấy thành lời nói suông
            # — đúng thứ mà cả vòng 27 dựng lên để chặn. Dọn `.research/` là cách kết thúc vòng đời.
            pass
        return True

    # ------------------------------------------------------------------
    # Sổ nguồn (vòng 27 đợt 3, B-1) — bằng chứng của một hồ sơ research
    #
    # Vì sao là BẢNG chứ không phải một tệp JSON: `source_add` chạy từ nhiều phiên con CÙNG LÚC, và
    # `UNIQUE(session_id, row_id)` là chỗ biến "không ghi hai dòng cùng mã" thành chuyện KHÔNG-THỂ.
    # Vì sao `payload` giữ `TEXT` chứ không cột rời: luật hồ sơ đổi theo usecase (`docNumber`,
    # `price`, `captureAt`…); đổi cột theo từng luật mới là đổi schema theo từng ý chủ nhà.

    SOURCE_FIELDS = ('child_id', 'job', 'claim', 'url', 'host', 'tier', 'type', 'excerpt', 'fetched_at',
                     'origin', 'method', 'source_row_id', 'status', 'fingerprint', 'payload', 'turn', 'step',
                     'research_id', 'published_at', 'updated_at', 'version_label', 'source_kind',
                     'origin_cluster', 'access_level', 'section_kind', 'event_date')

    def next_source_row_id(self, sid):
        """Mã dòng kế tiếp của phiên: `r1`, `r2`… — đọc từ mã LỚN NHẤT, không từ số hàng."""
        row = self.db.execute("SELECT MAX(CAST(SUBSTR(row_id, 2) AS INTEGER)) AS top"
                              ' FROM source_ledger WHERE session_id=?', (sid,)).fetchone()
        return 'r%d' % (int((row['top'] if row else 0) or 0) + 1)

    def source_add(self, sid, row):
        """Ghim một dòng sổ. Trả hàng đã ghi (kèm `row_id` harness cấp).

        Ghi lặp cùng `row_id` ⇒ trả **hàng cũ** (idempotent), đúng khuôn `queue_delivery`: đường gọi
        lại sau một lỗi mạng không được sinh ra dòng thứ hai cho cùng một khẳng định.

        Mã TỰ CẤP mà đụng mã của nhánh khác thì **thử lại với mã mới**, không trả hàng của nhánh kia:
        hai phiên con ghi cùng lúc là chuyện thường, và trả nhầm hàng thì hồ sơ sẽ trỏ bằng chứng
        của người khác.
        """
        values = dict(row or {})
        given = str(values.get('row_id') or values.get('rowId') or '').strip()
        row_id = given
        last_error = None
        for _attempt in range(3):
            if not row_id:
                row_id = self.next_source_row_id(sid)
            try:
                with self.db:
                    cursor = self.db.execute(
                        'INSERT INTO source_ledger(session_id,row_id,child_id,job,claim,url,host,tier,type,'
                        ' excerpt,fetched_at,origin,method,source_row_id,status,fingerprint,payload,branches,'
                        ' turn,step,created,research_id,published_at,updated_at,version_label,source_kind,'
                        ' origin_cluster,access_level,section_kind,event_date)'
                        ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (sid, row_id, values.get('child_id'), values.get('job'),
                         str(values.get('claim') or ''), str(values.get('url') or ''),
                         str(values.get('host') or ''),
                         int(values['tier'] if values.get('tier') is not None else 4),
                         str(values.get('type') or 'normal'), str(values.get('excerpt') or ''),
                         str(values.get('fetched_at') or ''), values.get('origin'), values.get('method'),
                         values.get('source_row_id'), str(values.get('status') or 'unverified'),
                         str(values.get('fingerprint') or ''),
                         json.dumps(values.get('payload') or {}, ensure_ascii=False),
                         json.dumps(list(values.get('branches') or []), ensure_ascii=False),
                         int(values.get('turn') or 0),
                         None if values.get('step') is None else int(values.get('step')),
                         time.time(), str(values.get('research_id') or values.get('researchId') or ''),
                         str(values.get('published_at') or values.get('publishedAt') or ''),
                         str(values.get('updated_at') or values.get('updatedAt') or ''),
                         str(values.get('version_label') or values.get('versionLabel') or ''),
                         str(values.get('source_kind') or values.get('sourceKind') or ''),
                         str(values.get('origin_cluster') or values.get('originCluster') or ''),
                         str(values.get('access_level') or values.get('accessLevel') or 'snippet'),
                         str(values.get('section_kind') or values.get('sectionKind') or ''),
                         str(values.get('event_date') or values.get('eventDate') or '')))
                return self.source_row(sid, row_id)
            except sqlite3.IntegrityError as exc:
                last_error = exc
                if given:
                    existing = self.source_row(sid, row_id)
                    if existing is not None:
                        return existing
                row_id = ''
        raise last_error or sqlite3.IntegrityError('source_ledger: row id not available')

    def source_row(self, sid, row_id):
        """Một dòng sổ theo mã, hoặc `None`."""
        row = self.db.execute('SELECT * FROM source_ledger WHERE session_id=? AND row_id=?',
                              (sid, str(row_id))).fetchone()
        return self._source_view(row) if row is not None else None

    def source_rows(self, sid, child_id=None, turn=None, tier=None, limit=None, newest_first=False,
                    research_id=None):
        """Các dòng sổ của một phiên, cũ → mới (hoặc mới → cũ), có trần."""
        sql = 'SELECT * FROM source_ledger WHERE session_id=?'
        params = [sid]
        if child_id:
            sql += ' AND child_id=?'
            params.append(child_id)
        if research_id is not None:
            sql += ' AND research_id=?'
            params.append(str(research_id))
        if turn is not None:
            sql += ' AND turn=?'
            params.append(int(turn))
        if tier is not None:
            sql += ' AND tier=?'
            params.append(int(tier))
        sql += ' ORDER BY id DESC' if newest_first else ' ORDER BY id'
        if limit:
            sql += ' LIMIT ?'
            params.append(int(limit))
        return [self._source_view(row) for row in self.db.execute(sql, params).fetchall()]

    def source_count(self, sid):
        """Số dòng sổ của phiên (đếm ở SQL, không kéo hàng về)."""
        row = self.db.execute('SELECT COUNT(*) AS total FROM source_ledger WHERE session_id=?',
                              (sid,)).fetchone()
        return int((row['total'] if row else 0) or 0)

    def evidence_link(self, sid, row_id, claim, *, proposed_by=None, published_at='', updated_at='',
                      version_label='', source_kind='', origin_cluster='', access_level='',
                      section_kind='', event_date='', research_id=''):
        """Normalize a legacy ledger row into source, passage, claim and relation.

        P2 (§5.7): nhận thêm siêu dữ liệu của nguồn/đoạn trích. Cột mới chỉ ghi khi có giá trị, nên
        đường gọi cũ (không truyền gì) giữ nguyên hành vi `6eb2fd8`.
        """
        from ..agent_core.reading import normalize_url
        row = self.source_row(sid, row_id)
        if row is None:
            raise ValueError('RESEARCH_EVIDENCE_ROW_UNKNOWN')
        normalized = normalize_url(row['url'])
        source_id = 's-' + hashlib.sha256(normalized.encode()).hexdigest()[:20]
        excerpt = row['excerpt']
        excerpt_hash = hashlib.sha256(excerpt.encode()).hexdigest()
        passage_id = 'p-' + hashlib.sha256((source_id + excerpt_hash).encode()).hexdigest()[:20]
        claim = str(claim).strip()
        claim_hash = hashlib.sha256(claim.casefold().encode()).hexdigest()
        claim_id = 'c-' + claim_hash[:20]
        payload = row.get('payload') or {}
        locator = {key: payload[key] for key in ('page', 'section', 'line', 'locator', 'commit')
                   if key in payload}
        # Mức truy cập chỉ ĐI LÊN: lượt ghi sau biết nhiều hơn (đã đọc toàn văn) thì hàng cũ nhận,
        # còn lượt ghi sau chỉ có đoạn trích ngắn thì không kéo hàng cũ xuống. Mức của đoạn trích
        # không thấp hơn mức dòng sổ đã khai (`row['accessLevel']`), vì đoạn trích lấy từ chính nó.
        access = self._best_access(access_level, row.get('accessLevel'))
        was_source = self.db.execute('SELECT access_level_max FROM research_sources '
                                     'WHERE session_id=? AND source_id=?',
                                     (sid, source_id)).fetchone()
        source_access = self._best_access(
            access, (was_source['access_level_max'] if was_source is not None else ''))
        was_passage = self.db.execute('SELECT access_level FROM research_passages '
                                      'WHERE session_id=? AND passage_id=?',
                                      (sid, passage_id)).fetchone()
        passage_access = self._best_access(
            access, (was_passage['access_level'] if was_passage is not None else ''))
        with self.db:
            # `DO UPDATE` (không `OR IGNORE`): lượt `source_add` sau mang thêm ngày/phiên bản/mức
            # truy cập thì hàng đã có phải NHẬN, nếu không thì `access_level_max` mãi là giá trị của
            # lần ghi đầu và luật trần độ tin cậy đọc phải dữ liệu cũ.
            self.db.execute('INSERT INTO research_sources '
                            '(source_id,session_id,url,normalized_url,host,origin,published_at,'
                            ' updated_at,version_label,source_kind,origin_cluster,access_level_max,'
                            ' research_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) '
                            'ON CONFLICT(session_id,source_id) DO UPDATE SET '
                            'published_at=COALESCE(NULLIF(excluded.published_at,\'\'),published_at),'
                            'updated_at=COALESCE(NULLIF(excluded.updated_at,\'\'),updated_at),'
                            'version_label=COALESCE(NULLIF(excluded.version_label,\'\'),version_label),'
                            'source_kind=COALESCE(NULLIF(excluded.source_kind,\'\'),source_kind),'
                            'origin_cluster=COALESCE(NULLIF(excluded.origin_cluster,\'\'),origin_cluster),'
                            'access_level_max=excluded.access_level_max,'
                            'research_id=COALESCE(NULLIF(excluded.research_id,\'\'),research_id)',
                            (source_id, sid, row['url'], normalized, row['host'], row.get('origin'),
                             str(published_at or row.get('publishedAt') or ''),
                             str(updated_at or row.get('updatedAt') or ''),
                             str(version_label or row.get('versionLabel') or ''),
                             str(source_kind or row.get('sourceKind') or ''),
                             str(origin_cluster or row.get('originCluster') or ''),
                             source_access,
                             str(research_id or row.get('researchId') or '')))
            self.db.execute('INSERT INTO research_passages '
                            '(passage_id,session_id,source_id,excerpt,excerpt_hash,locator,extraction_method,'
                            ' access_level,section_kind,event_date,research_id) '
                            'VALUES(?,?,?,?,?,?,?,?,?,?,?) '
                            'ON CONFLICT(session_id,passage_id) DO UPDATE SET '
                            'access_level=excluded.access_level,'
                            'section_kind=COALESCE(NULLIF(excluded.section_kind,\'\'),section_kind),'
                            'event_date=COALESCE(NULLIF(excluded.event_date,\'\'),event_date),'
                            'research_id=COALESCE(NULLIF(excluded.research_id,\'\'),research_id)',
                            (passage_id, sid, source_id, excerpt, excerpt_hash,
                             json.dumps(locator, ensure_ascii=False), row.get('method') or '',
                             passage_access,
                             str(section_kind or row.get('sectionKind') or ''),
                             str(event_date or row.get('eventDate') or ''),
                             str(research_id or row.get('researchId') or '')))
            self.db.execute('INSERT OR IGNORE INTO research_claims '
                            '(claim_id,session_id,text,text_hash) VALUES(?,?,?,?)',
                            (claim_id, sid, claim, claim_hash))
            self.db.execute('INSERT OR IGNORE INTO research_relations '
                            '(session_id,row_id,passage_id,claim_id,proposed_by) VALUES(?,?,?,?,?)',
                            (sid, row_id, passage_id, claim_id, proposed_by))
        return {'sourceId': source_id, 'passageId': passage_id, 'claimId': claim_id}

    def evidence_graph(self, sid, limit=100):
        rows = self.db.execute('SELECT r.row_id,r.passage_id,r.claim_id,c.text AS claim,'
                               'p.excerpt,p.locator,p.extraction_method,s.url,s.origin '
                               'FROM research_relations r '
                               'JOIN research_claims c ON c.session_id=r.session_id AND c.claim_id=r.claim_id '
                               'JOIN research_passages p ON p.session_id=r.session_id AND p.passage_id=r.passage_id '
                               'JOIN research_sources s ON s.session_id=r.session_id AND s.source_id=p.source_id '
                               'WHERE r.session_id=? ORDER BY r.row_id LIMIT ?', (sid, int(limit))).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item['locator'] = json.loads(item['locator'])
            item['excerpt'] = item['excerpt'][:500]
            item['assessments'] = [dict(a) for a in self.db.execute(
                'SELECT reviewer_id,content_hash,relation,rationale,created '
                'FROM research_assessments WHERE session_id=? AND passage_id=? AND claim_id=? '
                'ORDER BY created', (sid, item['passage_id'], item['claim_id'])).fetchall()]
            out.append(item)
        return out

    def evidence_assess(self, sid, passage_id, claim_id, reviewer_id, content_hash,
                        relation, rationale):
        linked = self.db.execute('SELECT 1 FROM research_relations WHERE session_id=? '
                                 'AND passage_id=? AND claim_id=?',
                                 (sid, passage_id, claim_id)).fetchone()
        if linked is None:
            raise ValueError('RESEARCH_RELATION_UNKNOWN')
        with self.db:
            self.db.execute('INSERT INTO research_assessments '
                            '(session_id,passage_id,claim_id,reviewer_id,content_hash,relation,rationale,created) '
                            'VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(session_id,passage_id,claim_id,reviewer_id,content_hash) '
                            'DO UPDATE SET relation=excluded.relation,rationale=excluded.rationale,created=excluded.created',
                            (sid, passage_id, claim_id, reviewer_id, content_hash,
                             relation, rationale, time.time()))
        return {'passageId': passage_id, 'claimId': claim_id, 'relation': relation,
                'reviewerId': reviewer_id, 'contentHash': content_hash}

    # ------------------------------------------------------------------
    # P2 (§5.5, §5.7): siêu dữ liệu bằng chứng, nhận định và bản đồ bao phủ
    # ------------------------------------------------------------------

    #: Cột của `research_claim_meta`, tên trả ra (camel) → tên cột.
    CLAIM_META_FIELDS = {'questionId': 'question_id', 'facetId': 'facet_id', 'claimType': 'claim_type',
                         'stanceOrigin': 'stance_origin', 'confidence': 'confidence',
                         'confidenceCap': 'confidence_cap', 'basis': 'basis', 'asOf': 'as_of'}
    #: Cột của `research_facets`, tên trả ra (camel) → tên cột.
    FACET_FIELDS = {'questionId': 'question_id', 'label': 'label', 'kind': 'kind', 'terms': 'terms',
                    'priority': 'priority', 'status': 'status', 'seedSource': 'seed_source',
                    'evidenceCount': 'evidence_count', 'originClusters': 'origin_clusters',
                    'lastNewRatio': 'last_new_ratio', 'note': 'note'}

    @staticmethod
    def _best_access(*levels):
        """Mức truy cập cao nhất trong các mức đã biết; thứ tự đọc từ `source_pack.ACCESS_LEVELS`."""
        from ..agent_core.source_pack import ACCESS_LEVELS
        best = ''
        for level in levels:
            level = str(level or '')
            if level not in ACCESS_LEVELS:
                continue
            if not best or ACCESS_LEVELS.index(level) > ACCESS_LEVELS.index(best):
                best = level
        return best or 'snippet'

    @staticmethod
    def _first(*values):
        """Giá trị khác rỗng ĐẦU TIÊN; dùng khi hàng dòng sổ thiếu mà hàng nguồn đã biết."""
        for value in values:
            value = str(value or '')
            if value:
                return value
        return ''

    def source_evidence_meta(self, sid, row_id):
        """Siêu dữ liệu P2 của MỘT dòng sổ (ngày, phiên bản, loại nguồn, cụm gốc, mức truy cập).

        Hàng dòng sổ là nơi ghi TRƯỚC, hàng nguồn (`research_sources`, khoá theo URL) là nơi biết
        NHIỀU HƠN: một lượt `evidence_link` sau khi đọc toàn văn nâng mức truy cập của cả nguồn, và
        cụm gốc thì đúng cho mọi dòng của cùng một URL. Vì vậy: giá trị của dòng sổ thắng, hàng
        nguồn chỉ ĐIỀN CHỖ TRỐNG, riêng mức truy cập lấy mức cao nhất đã biết.
        """
        row = self.source_row(sid, row_id)
        if row is None:
            return {}
        linked = self.db.execute('SELECT access_level_max,published_at,updated_at,version_label,'
                                 'source_kind,origin_cluster,research_id FROM research_sources '
                                 'WHERE session_id=? AND url=?', (sid, row['url'])).fetchone()
        other = dict(linked) if linked is not None else {}

        def known(name, *columns):
            return self._first(*[row.get(column) or '' for column in columns]) or self._first(
                *[other.get(column) or '' for column in columns])

        return {'publishedAt': known('publishedAt', 'publishedAt', 'published_at'),
                'updatedAt': known('updatedAt', 'updatedAt', 'updated_at'),
                'versionLabel': known('versionLabel', 'versionLabel', 'version_label'),
                'sourceKind': known('sourceKind', 'sourceKind', 'source_kind'),
                'originCluster': known('originCluster', 'originCluster', 'origin_cluster'),
                'accessLevel': self._best_access(row.get('accessLevel'), other.get('access_level_max')),
                'sectionKind': known('sectionKind', 'sectionKind', 'section_kind'),
                'eventDate': known('eventDate', 'eventDate', 'event_date'),
                'researchId': known('researchId', 'researchId', 'research_id')}

    def evidence_claims(self, sid, research_id=None):
        """Mọi cặp (nhận định, đoạn trích, nguồn) của phiên, kèm siêu dữ liệu P2.

        Lọc theo `research_id` khi được hỏi: cột `research_id` có ở CẢ nguồn và dòng sổ, nên nhận
        hàng khớp ở một trong hai (dòng sổ ghi trước P1 chưa mang `research_id` vẫn phải đọc ra).
        """
        sql = ('SELECT r.row_id,c.claim_id,c.text,p.passage_id,p.access_level,p.section_kind,'
               'p.event_date,p.excerpt,s.url,s.source_id,l.tier,s.host,s.origin,s.source_kind,s.published_at,'
               's.updated_at,s.access_level_max,s.origin_cluster,s.research_id,'
               'l.id AS row_seq,l.status,'
               # Quan hệ ĐÃ SOÁT của cặp (đoạn trích, nhận định): phán quyết mới nhất của người soát
               # (`research_assessments`), vì `research_relations` chỉ giữ liên kết chứ không giữ quan hệ.
               '(SELECT a.relation FROM research_assessments a WHERE a.session_id=r.session_id'
               ' AND a.passage_id=r.passage_id AND a.claim_id=r.claim_id'
               ' ORDER BY a.created DESC LIMIT 1) AS judged_relation '
               'FROM research_relations r '
               'JOIN research_claims c ON c.session_id=r.session_id AND c.claim_id=r.claim_id '
               'JOIN research_passages p ON p.session_id=r.session_id AND p.passage_id=r.passage_id '
               'JOIN research_sources s ON s.session_id=r.session_id AND s.source_id=p.source_id '
               'LEFT JOIN source_ledger l ON l.session_id=r.session_id AND l.row_id=r.row_id '
               'WHERE r.session_id=?')
        params = [sid]
        if research_id:
            sql += (' AND (s.research_id=? OR r.row_id IN'
                    ' (SELECT row_id FROM source_ledger WHERE session_id=? AND research_id=?))')
            params += [str(research_id), sid, str(research_id)]
        sql += ' ORDER BY r.row_id'
        out = []
        for row in self.db.execute(sql, params).fetchall():
            item = dict(row)
            access = item.get('access_level') or item.get('access_level_max') or 'snippet'
            out.append({'rowId': item['row_id'], 'claimId': item['claim_id'], 'text': item['text'],
                        'sourceId': item.get('source_id') or '',
                        'tier': int(item.get('tier') or 0),
                        'passageId': item['passage_id'], 'accessLevel': access,
                        # Mức của NGUỒN, để người đọc soi lại: mức của đoạn trích mới là thứ nhận
                        # định dựa vào, còn đây là thứ đã đọc được của cả nguồn.
                        'sourceAccessLevel': self._best_access(item.get('access_level'),
                                                               item.get('access_level_max')),
                        'sectionKind': item.get('section_kind') or '',
                        'eventDate': item.get('event_date') or '', 'excerpt': item.get('excerpt') or '',
                        'url': item['url'], 'host': item['host'], 'origin': item.get('origin') or '',
                        'sourceKind': item.get('source_kind') or '',
                        'publishedAt': item.get('published_at') or '',
                        'updatedAt': item.get('updated_at') or '',
                        'originCluster': item.get('origin_cluster') or '',
                        'researchId': item.get('research_id') or '',
                        # Thứ tự ghi trong sổ (0 khi dòng sổ đã biến mất) — nơi gọi sắp theo thứ tự này
                        # thay vì so chuỗi `row_id` (`r10` đứng trước `r2` nếu so chuỗi).
                        'rowSeq': int(item.get('row_seq') or 0),
                        'status': item.get('status') or '',
                        'relation': item.get('judged_relation') or ''})
        return out

    @staticmethod
    def _claim_meta_view(row):
        item = dict(row)
        basis = item.get('basis') or '{}'
        try:
            basis = json.loads(basis)
        except (TypeError, ValueError):
            basis = {}
        return {'researchId': item.get('research_id') or '', 'claimId': item.get('claim_id') or '',
                'questionId': item.get('question_id') or '', 'facetId': item.get('facet_id') or '',
                'claimType': item.get('claim_type') or 'inference',
                'stanceOrigin': item.get('stance_origin') or 'agent-inference',
                'confidence': item.get('confidence') or 'unknown',
                'confidenceCap': item.get('confidence_cap') or 'unknown',
                'basis': basis if isinstance(basis, dict) else {}, 'asOf': item.get('as_of') or '',
                'updated': item.get('updated')}

    def claim_meta(self, research_id, claim_id):
        """Một hàng `research_claim_meta`, hoặc `{}` khi chưa có (chưa chấm thì chưa có mức trần)."""
        row = self.db.execute('SELECT * FROM research_claim_meta WHERE research_id=? AND claim_id=?',
                              (str(research_id or ''), str(claim_id or ''))).fetchone()
        return self._claim_meta_view(row) if row is not None else {}

    def claim_meta_save(self, research_id, claim_id, **fields):
        """Ghi (thêm hoặc cập nhật) mức tin cậy của MỘT nhận định trong MỘT run.

        Trường không truyền giữ nguyên giá trị cũ — máy tính mức trần rồi mô hình hạ xuống là hai
        lần ghi khác nhau trên cùng một hàng.
        """
        research_id, claim_id = str(research_id or ''), str(claim_id or '')
        if not research_id or not claim_id:
            raise ValueError('RESEARCH_CLAIM_META_KEY')
        current = self.claim_meta(research_id, claim_id)
        merged = {key: current.get(key) for key in self.CLAIM_META_FIELDS}
        merged['claimType'] = merged.get('claimType') or 'inference'
        merged['stanceOrigin'] = merged.get('stanceOrigin') or 'agent-inference'
        merged['confidence'] = merged.get('confidence') or 'unknown'
        merged['confidenceCap'] = merged.get('confidenceCap') or 'unknown'
        merged['basis'] = dict(merged.get('basis') or {})
        reverse = {value: key for key, value in self.CLAIM_META_FIELDS.items()}
        for key, value in (fields or {}).items():
            camel = key if key in self.CLAIM_META_FIELDS else reverse.get(key)
            if camel is None or value is None:
                continue
            merged[camel] = dict(value) if camel == 'basis' and isinstance(value, dict) else value
        with self.db:
            self.db.execute(
                'INSERT INTO research_claim_meta(research_id,claim_id,question_id,facet_id,claim_type,'
                ' stance_origin,confidence,confidence_cap,basis,as_of,updated) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(research_id,claim_id) DO UPDATE SET question_id=excluded.question_id,'
                ' facet_id=excluded.facet_id,claim_type=excluded.claim_type,'
                ' stance_origin=excluded.stance_origin,confidence=excluded.confidence,'
                ' confidence_cap=excluded.confidence_cap,basis=excluded.basis,as_of=excluded.as_of,'
                ' updated=excluded.updated',
                (research_id, claim_id, str(merged.get('questionId') or ''), str(merged.get('facetId') or ''),
                 str(merged.get('claimType') or 'inference'),
                 str(merged.get('stanceOrigin') or 'agent-inference'),
                 str(merged.get('confidence') or 'unknown'), str(merged.get('confidenceCap') or 'unknown'),
                 json.dumps(merged.get('basis') or {}, ensure_ascii=False), str(merged.get('asOf') or ''),
                 time.time()))
        return self.claim_meta(research_id, claim_id)

    def claim_meta_list(self, research_id):
        """Mọi hàng của một run, xếp theo `claim_id` (thứ tự ổn định cho test và giao diện)."""
        rows = self.db.execute('SELECT * FROM research_claim_meta WHERE research_id=? ORDER BY claim_id',
                               (str(research_id or ''),)).fetchall()
        return [self._claim_meta_view(row) for row in rows]

    def claim_meta_upsert_many(self, research_id, items):
        """Ghi nhiều hàng một lượt; trả về số hàng đã ghi (bỏ qua mục không có `claimId`)."""
        written = 0
        for item in items or ():
            if not isinstance(item, dict):
                continue
            claim_id = str(item.get('claimId') or item.get('claim_id') or '')
            if not claim_id:
                continue
            extra = {key: value for key, value in item.items()
                     if key not in ('claimId', 'claim_id', 'researchId', 'research_id')}
            self.claim_meta_save(research_id, claim_id, **extra)
            written += 1
        return written

    @staticmethod
    def _facet_view(row):
        item = dict(row)
        terms = item.get('terms') or '[]'
        try:
            terms = json.loads(terms)
        except (TypeError, ValueError):
            terms = []
        return {'researchId': item.get('research_id') or '', 'facetId': item.get('facet_id') or '',
                'questionId': item.get('question_id') or '', 'label': item.get('label') or '',
                'kind': item.get('kind') or 'direction',
                'terms': [term for term in (terms if isinstance(terms, list) else []) if term],
                'priority': item.get('priority') or 'medium', 'status': item.get('status') or 'unexplored',
                'seedSource': item.get('seed_source') or 'agent',
                'evidenceCount': int(item.get('evidence_count') or 0),
                'originClusters': int(item.get('origin_clusters') or 0),
                'lastNewRatio': float(item.get('last_new_ratio')
                                      if item.get('last_new_ratio') is not None else -1.0),
                'note': item.get('note') or '', 'updated': item.get('updated')}

    def facet(self, research_id, facet_id):
        row = self.db.execute('SELECT * FROM research_facets WHERE research_id=? AND facet_id=?',
                              (str(research_id or ''), str(facet_id or ''))).fetchone()
        return self._facet_view(row) if row is not None else {}

    def facet_list(self, research_id):
        rows = self.db.execute('SELECT * FROM research_facets WHERE research_id=? ORDER BY facet_id',
                               (str(research_id or ''),)).fetchall()
        return [self._facet_view(row) for row in rows]

    def facet_save(self, research_id, facet):
        """Ghi (thêm hoặc cập nhật) MỘT facet. Trường không truyền giữ nguyên giá trị cũ."""
        research_id = str(research_id or '')
        facet_id = str((facet or {}).get('facetId') or (facet or {}).get('facet_id') or '')
        if not facet_id and (facet or {}).get('label'):
            # Nhãn không phải khoá: băm ra cùng công thức với `research_facets.facet_id_for` để
            # đường gọi chỉ có nhãn vẫn ghi được, mà khoá vẫn ổn định giữa các lượt.
            from ..agent_core.research_facets import facet_id_for
            facet_id = facet_id_for(facet.get('label'))
        if not research_id or not facet_id:
            raise ValueError('RESEARCH_FACET_KEY')
        current = self.facet(research_id, facet_id)
        merged = {key: current.get(key) for key in self.FACET_FIELDS}
        merged['kind'] = merged.get('kind') or 'direction'
        merged['status'] = merged.get('status') or 'unexplored'
        merged['seedSource'] = merged.get('seedSource') or 'agent'
        merged['priority'] = merged.get('priority') or 'medium'
        if merged.get('lastNewRatio') is None:
            merged['lastNewRatio'] = -1.0
        reverse = {value: key for key, value in self.FACET_FIELDS.items()}
        for key, value in (facet or {}).items():
            camel = key if key in self.FACET_FIELDS else reverse.get(key)
            if camel is None or value is None:
                continue
            merged[camel] = value
        terms = merged.get('terms')
        if isinstance(terms, str):
            try:
                terms = json.loads(terms)
            except (TypeError, ValueError):
                terms = []
        with self.db:
            self.db.execute(
                'INSERT INTO research_facets(research_id,facet_id,question_id,label,kind,terms,priority,'
                ' status,seed_source,evidence_count,origin_clusters,last_new_ratio,note,updated) '
                'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(research_id,facet_id) DO UPDATE SET question_id=excluded.question_id,'
                ' label=excluded.label,kind=excluded.kind,terms=excluded.terms,priority=excluded.priority,'
                ' status=excluded.status,seed_source=excluded.seed_source,'
                ' evidence_count=excluded.evidence_count,origin_clusters=excluded.origin_clusters,'
                ' last_new_ratio=excluded.last_new_ratio,note=excluded.note,updated=excluded.updated',
                (research_id, facet_id, str(merged.get('questionId') or ''), str(merged.get('label') or ''),
                 str(merged.get('kind') or 'direction'),
                 json.dumps(list(terms or []), ensure_ascii=False),
                 str(merged.get('priority') or 'medium'), str(merged.get('status') or 'unexplored'),
                 str(merged.get('seedSource') or 'agent'), int(merged.get('evidenceCount') or 0),
                 int(merged.get('originClusters') or 0),
                 float(merged.get('lastNewRatio') if merged.get('lastNewRatio') is not None else -1.0),
                 str(merged.get('note') or ''), time.time()))
        return self.facet(research_id, facet_id)

    def facet_delete(self, research_id, facet_id):
        """Xoá một facet; trả `True` khi có hàng bị xoá."""
        with self.db:
            cursor = self.db.execute('DELETE FROM research_facets WHERE research_id=? AND facet_id=?',
                                     (str(research_id or ''), str(facet_id or '')))
        return bool(cursor.rowcount)

    def research_snapshot_save(self, scope_id, normalized_url, entry):
        """Persist the full bounded reader copy for a root research session."""
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO research_snapshots '
                            '(ref,scope_id,normalized_url,entry,created) VALUES(?,?,?,?,?)',
                            (entry['ref'], scope_id, normalized_url,
                             json.dumps(entry, ensure_ascii=False), time.time()))

    def research_snapshot_ref(self, scope_id, ref):
        row = self.db.execute('SELECT entry FROM research_snapshots WHERE scope_id=? AND ref=?',
                              (scope_id, ref)).fetchone()
        return json.loads(row['entry']) if row else None

    def research_snapshot_url(self, scope_id, normalized_url):
        row = self.db.execute('SELECT entry FROM research_snapshots '
                              'WHERE scope_id=? AND normalized_url=? ORDER BY created DESC LIMIT 1',
                              (scope_id, normalized_url)).fetchone()
        return json.loads(row['entry']) if row else None

    def plan_research_link(self, identity, version, dependencies):
        with self.db:
            for item in dependencies:
                self.db.execute('INSERT OR REPLACE INTO plan_research_dependencies '
                                '(identity,version,research_id,research_version,research_hash,created) '
                                'VALUES(?,?,?,?,?,?)',
                                (identity, int(version), item['researchId'], int(item['version']),
                                 item['contentHash'], time.time()))

    def plan_research_dependencies(self, identity, version):
        rows = self.db.execute('SELECT research_id,research_version,research_hash FROM '
                               'plan_research_dependencies WHERE identity=? AND version=? '
                               'ORDER BY research_id', (identity, int(version))).fetchall()
        result = []
        for row in rows:
            latest = self.dossier_latest(row['research_id'])
            stale = (latest is None or latest['version'] != row['research_version'] or
                     latest['content_hash'] != row['research_hash'])
            result.append({'researchId': row['research_id'], 'version': row['research_version'],
                           'contentHash': row['research_hash'], 'latestVersion':
                           latest['version'] if latest else None, 'stale': stale})
        return result

    def research_dependent_plans(self, research_id):
        rows = self.db.execute('SELECT identity,version FROM plan_research_dependencies '
                               'WHERE research_id=? ORDER BY created DESC', (research_id,)).fetchall()
        return [{'identity': row['identity'], 'version': row['version'],
                 'dependencies': self.plan_research_dependencies(row['identity'], row['version'])}
                for row in rows]

    def source_counts_by_child(self, sid):
        """`{child_id: số dòng}` — luật "mỗi nhánh con phải để lại một dòng" đọc từ đây."""
        rows = self.db.execute('SELECT child_id, COUNT(*) AS total FROM source_ledger'
                               ' WHERE session_id=? GROUP BY child_id', (sid,)).fetchall()
        return {str(row['child_id'] or ''): int(row['total'] or 0) for row in rows}

    def source_payload_merge(self, sid, row_id, payload):
        """Ghi lại `payload` của một dòng sổ đã có (chỉ dùng cho đường DÙNG LẠI dòng).

        `source_add` gọi hàm này khi lời gọi thứ hai mang trường hồ sơ mà dòng cũ chưa có: bỏ qua
        chúng là biến một nguồn đã mở thành nguồn thiếu trường, và hồ sơ sẽ bị từ chối ở cổng chất
        lượng vì lỗi thuộc về chính harness. Dòng đã đổi ⇒ trả hàng hiện tại.
        """
        current = self.source_row(sid, row_id)
        if current is None:
            return None
        with self.db:
            self.db.execute('UPDATE source_ledger SET payload=? WHERE session_id=? AND row_id=?',
                            (json.dumps(dict(payload or {}), ensure_ascii=False), sid, str(row_id)))
        return self.source_row(sid, row_id)

    def source_link_branch(self, sid, row_id, child_id):
        """Ghi thêm một nhánh con vào dòng sổ đã có. Dòng đã đổi ⇒ trả hàng hiện tại.

        Đây là chỗ gỡ `research-lineage-missing` cho nhánh thứ hai mở CÙNG một nguồn với đoạn trích
        y hệt: luật idempotent giữ một dòng, và dòng ấy nhớ đủ cả hai nhánh.
        """
        branch = str(child_id or '').strip()
        current = self.source_row(sid, row_id)
        if current is None or not branch:
            return current
        branches = [str(item) for item in (current.get('branches') or []) if str(item)]
        if str(current.get('childId') or '') == branch or branch in branches:
            return current
        branches.append(branch)
        with self.db:
            self.db.execute('UPDATE source_ledger SET branches=? WHERE session_id=? AND row_id=?',
                            (json.dumps(branches, ensure_ascii=False), sid, str(row_id)))
        return self.source_row(sid, row_id)

    def source_rows_for(self, sid, child_ids):
        """Mọi dòng sổ thuộc một tập con (`child_ids`) — cổng chất lượng đọc theo nhánh."""
        wanted = [str(item) for item in (child_ids or []) if str(item)]
        if not wanted:
            return []
        placeholders = ','.join('?' for _ in wanted)
        # Nhánh ĐẦU tiên ghim dòng nằm ở cột `child_id`; các nhánh sau mở cùng nguồn nằm trong
        # `branches` (JSON) — đọc cả hai chỗ, nếu không nhánh thứ hai mất bằng chứng của chính nó.
        like = ' OR '.join('branches LIKE ?' for _ in wanted)
        rows = self.db.execute(
            f'SELECT * FROM source_ledger WHERE session_id=? AND (child_id IN ({placeholders}) OR {like})'
            ' ORDER BY id', [sid] + wanted + ['%"' + item + '"%' for item in wanted]).fetchall()
        return [self._source_view(row) for row in rows]

    def source_status_set(self, sid, row_id, status, matched=None):
        """Ghim kết luận `source_verify` vào dòng: `status` + `payload.verify`.

        Dòng đã đổi (hoặc phiên đã xoá) ⇒ trả hàng HIỆN TẠI, không tự tạo hàng mới.
        """
        current = self.source_row(sid, row_id)
        if current is None:
            return None
        payload = dict(current.get('payload') or {})
        payload['verify'] = {'matched': bool(matched) if matched is not None else None,
                             'at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
        with self.db:
            self.db.execute('UPDATE source_ledger SET status=?, payload=? WHERE session_id=? AND row_id=?',
                            (str(status or 'unverified'), json.dumps(payload, ensure_ascii=False), sid, str(row_id)))
        return self.source_row(sid, row_id)

    @staticmethod
    def _source_view(row):
        """Hàng DB → dict dùng được ở tầng trên (`payload` đã giải JSON, `steps` không lộ id nội bộ)."""
        item = dict(row)
        try:
            item['payload'] = json.loads(item.get('payload') or '{}')
        except (TypeError, ValueError):
            item['payload'] = {}
        try:
            item['branches'] = [str(entry) for entry in json.loads(item.get('branches') or '[]')]
        except (TypeError, ValueError):
            item['branches'] = []
        item['rowId'] = item.pop('row_id', '')
        item['fetchedAt'] = item.pop('fetched_at', '')
        item['childId'] = item.pop('child_id', None)
        item['sourceRowId'] = item.pop('source_row_id', None)
        item['researchId'] = item.pop('research_id', '') or ''
        item['publishedAt'] = item.pop('published_at', '') or ''
        item['updatedAt'] = item.pop('updated_at', '') or ''
        item['versionLabel'] = item.pop('version_label', '') or ''
        item['sourceKind'] = item.pop('source_kind', '') or ''
        item['originCluster'] = item.pop('origin_cluster', '') or ''
        item['accessLevel'] = item.pop('access_level', '') or ''
        item['sectionKind'] = item.pop('section_kind', '') or ''
        item['eventDate'] = item.pop('event_date', '') or ''
        item.pop('id', None)
        item.pop('session_id', None)
        return item

    # ------------------------------------------------------------------
    # Hồ sơ research (vòng 27 đợt 4, C-2) — chỉ mục các bản đã ghi trong `.research/`

    def record_dossier(self, sid, research_id, version, relative_path, profile='', level=0,
                       critique='none', gate='clear', rows=0, bytes=0, content_hash='', quality_ok=False):
        """Ghim một bản hồ sơ đã ghi (khoá `(research_id, version)` — ghi đè cùng version là KHÔNG-THỂ)."""
        with self.db:
            self.db.execute(
                'INSERT INTO research_dossiers(research_id,version,session_id,relative_path,profile,level,'
                ' critique,gate,rows,bytes,content_hash,quality_ok,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)'
                ' ON CONFLICT(research_id, version) DO UPDATE SET session_id=excluded.session_id,'
                ' relative_path=excluded.relative_path, profile=excluded.profile, level=excluded.level,'
                ' critique=excluded.critique, gate=excluded.gate, rows=excluded.rows, bytes=excluded.bytes,'
                ' content_hash=excluded.content_hash,quality_ok=excluded.quality_ok',
                (str(research_id), int(version), sid, str(relative_path), str(profile or ''), int(level or 0),
                 str(critique or 'none'), str(gate or 'clear'), int(rows or 0), int(bytes or 0),
                 str(content_hash or ''), int(bool(quality_ok)), time.time()))
        return self.dossier(research_id, version)

    def dossier(self, research_id, version):
        """Một bản hồ sơ, hoặc `None`."""
        row = self.db.execute('SELECT * FROM research_dossiers WHERE research_id=? AND version=?',
                              (str(research_id), int(version))).fetchone()
        return dict(row) if row is not None else None

    def research_job(self, research_id):
        row = self.db.execute('SELECT * FROM research_jobs WHERE research_id=?',
                              (str(research_id),)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item['state'] = json.loads(item['state'])
        return item

    def research_jobs_for(self, session_id):
        rows = self.db.execute('SELECT research_id FROM research_jobs WHERE session_id=? '
                               'ORDER BY updated DESC', (session_id,)).fetchall()
        return [self.research_job(row['research_id']) for row in rows]

    def research_job_by_prompt(self, prompt_id):
        """Job chứa một `promptId` (§5.12) — tuyến `answer` chỉ có id lời hỏi, không có phiên.

        Quét thô bằng LIKE rồi xác nhận trên `state` đã giải JSON: LIKE chỉ là cách thu hẹp hàng,
        không phải căn cứ để trả lời.
        """
        wanted = str(prompt_id)
        rows = self.db.execute('SELECT research_id FROM research_jobs WHERE state LIKE ?',
                               (f'%{wanted}%',)).fetchall()
        for row in rows:
            job = self.research_job(row['research_id'])
            if any(str(item.get('promptId')) == wanted for item in (job['state'].get('prompts') or [])
                   if isinstance(item, dict)):
                return job
        return None

    def research_jobs_active(self):
        rows = self.db.execute("SELECT research_id FROM research_jobs WHERE status IN "
                               "('scoping','researching','verifying','synthesizing','critiquing') "
                               'ORDER BY updated').fetchall()
        return [self.research_job(row['research_id']) for row in rows]

    def research_job_save(self, research_id, session_id, state, status=None, revision=None):
        """One SQLite transaction for checkpoint and optimistic user edits."""
        allowed = {'scoping', 'researching', 'verifying', 'synthesizing', 'critiquing',
                   'needs_user', 'completed', 'partial', 'paused', 'cancelled'}
        current = self.research_job(research_id)
        if current and current['session_id'] != session_id:
            raise ValueError('RESEARCH_JOB_OWNER_MISMATCH')
        if revision is not None and current and current['revision'] != revision:
            raise ValueError('RESEARCH_JOB_REVISION_CONFLICT')
        selected = status or (current['status'] if current else 'scoping')
        if selected not in allowed:
            raise ValueError('RESEARCH_JOB_STATUS_INVALID')
        now = time.time()
        with self.db:
            self.db.execute('INSERT INTO research_jobs '
                            '(research_id,session_id,state,status,revision,created,updated) '
                            'VALUES(?,?,?,?,?,?,?) ON CONFLICT(research_id) DO UPDATE SET '
                            'state=excluded.state,status=excluded.status,revision=excluded.revision,'
                            'updated=excluded.updated',
                            (research_id, session_id, json.dumps(state, ensure_ascii=False), selected,
                             (current['revision'] + 1 if current else 1),
                             current['created'] if current else now, now))
        return self.research_job(research_id)

    def research_job_phase(self, research_id, session_id, phase, reason, at, *, force=False):
        """Ghim `phase`/`phaseHistory` của một run mà KHÔNG nhích `revision` (§5.3).

        Đổi pha là việc của harness đi kèm một tool call khác, không phải một bản ghi mới của run:
        nhích `revision` ở đây sẽ làm `research_update(revision=…)` của model va chạm giả
        (`RESEARCH_JOB_REVISION_CONFLICT`) ngay sau khi hồ sơ vừa được ghi.

        LUẬT CỦA PHA NẰM Ở ĐÂY, trên hàng ĐỌC LẠI NGAY TRƯỚC KHI GHI: người gọi cầm một bản chụp
        job đã cũ — một lượt chạy song song có thể vừa thêm hàng lịch sử (chủ nhà tạm dừng giữa
        lượt) hoặc vừa đóng run — nên cả hai quyết định ("có gì để ghi không", "ghép lịch sử thế
        nào") phải tính từ hàng TƯƠI. Trả về hàng sau khi ghi, hoặc `None` khi không có gì để
        ghi: pha đang đứng, hay run đã ở pha ĐÓNG `done` mà không có `force` (chủ nhà bấm Tiếp
        tục một run đã đóng, xem `research_runtime.PHASE_DONE`).

        `at` do người gọi cấp (`agent_core.journal.utc_now_iso()`): lớp này không import mô-đun
        `agent_core` (vòng import chạy ngược), và mốc thời gian phải cùng khuôn với mọi hàng
        `phaseHistory` khác.
        """
        job = self.research_job(research_id)
        if job is None or job['session_id'] != session_id:
            raise ValueError('RESEARCH_JOB_UNKNOWN')
        state = dict(job['state'] or {})
        current = str(state.get('phase') or '')
        if str(phase) == current:
            return None
        if current == 'done' and not force:
            return None
        history = list(state.get('phaseHistory') or [])
        history.append({'phase': str(phase), 'at': str(at or ''), 'reason': str(reason or '')})
        state['phase'] = str(phase)
        state['phaseHistory'] = history
        with self.db:
            self.db.execute('UPDATE research_jobs SET state=?, updated=? WHERE research_id=?',
                            (json.dumps(state, ensure_ascii=False), time.time(), str(research_id)))
        return self.research_job(research_id)

    def research_job_used_seconds(self, session_id, research_id=None):
        """Cumulative main-turn wall time from persisted events; retries cannot reset it."""
        used: dict[int, float] = {}
        tags: dict[int, set[str]] = {}
        rows = self.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='turn_end'",
                               (session_id,))
        for row in rows:
            try:
                event = json.loads(row['payload'])
                turn = int(event.get('turn') or 0)
                ms = float(event.get('deadlineUsedMs') or 0)
            except (TypeError, ValueError):
                continue
            used[turn] = max(used.get(turn, 0), ms)
            if event.get('researchId'):
                tags.setdefault(turn, set()).add(str(event['researchId']))
        return round(sum(ms for turn, ms in used.items()
                         if research_id is None or str(research_id) in tags.get(turn, set())) / 1000, 1)

    def dossier_versions(self, research_id):
        """Số version đang có của một việc, tăng dần."""
        rows = self.db.execute('SELECT version FROM research_dossiers WHERE research_id=? ORDER BY version',
                               (str(research_id),)).fetchall()
        return [int(row['version']) for row in rows]

    def dossier_latest(self, research_id):
        """Bản mới nhất của một việc, hoặc `None`."""
        row = self.db.execute('SELECT * FROM research_dossiers WHERE research_id=? ORDER BY version DESC LIMIT 1',
                              (str(research_id),)).fetchone()
        return dict(row) if row is not None else None

    def dossiers_for(self, research_id):
        """Mọi bản của một việc, cũ → mới."""
        rows = self.db.execute('SELECT * FROM research_dossiers WHERE research_id=? ORDER BY version',
                               (str(research_id),)).fetchall()
        return [dict(row) for row in rows]

    def dossiers_recent(self, sid, limit=10):
        """Các bản hồ sơ gần đây của một phiên (cho `research_status` khi chưa biết `researchId`)."""
        rows = self.db.execute('SELECT * FROM research_dossiers WHERE session_id=?'
                               ' ORDER BY created DESC LIMIT ?', (sid, int(limit))).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Chỉ thị giữa lượt (vòng 27 đợt 7, D-43) — hàng đợi của chủ nhà

    def queue_steer(self, sid, text, turn=0):
        """Xếp một chỉ thị giữa lượt. Trần `STEER_MAX_PENDING` do tầng gọi giữ, không phải bảng."""
        body = str(text or '').strip()
        if not body:
            raise ValueError('steer text must not be empty')
        with self.db:
            cursor = self.db.execute('INSERT INTO session_steers(session_id,turn,text,state,created)'
                                     ' VALUES(?,?,?,?,?)', (sid, int(turn or 0), body, 'pending', time.time()))
        return self.steer(cursor.lastrowid)

    def steer(self, steer_id):
        """Một hàng chỉ thị, hoặc `None`."""
        row = self.db.execute('SELECT * FROM session_steers WHERE id=?', (int(steer_id),)).fetchone()
        return dict(row) if row is not None else None

    def pending_steer_count(self, sid):
        """Số chỉ thị đang chờ bơm (hàng `pending`)."""
        row = self.db.execute("SELECT COUNT(*) AS total FROM session_steers WHERE session_id=? AND state='pending'",
                              (sid,)).fetchone()
        return int((row['total'] if row else 0) or 0)

    def claim_steers(self, sid, limit=3):
        """Giành các chỉ thị `pending` để bơm vào transcript — **một lần**, y như `claim_deliveries`.

        `UPDATE … WHERE state='pending'` là chỗ chốt: hàng đã bị nhịp khác giành thì `rowcount == 0`.
        """
        claimed = []
        with self.db:
            rows = self.db.execute("SELECT * FROM session_steers WHERE session_id=? AND state='pending'"
                                   ' ORDER BY id LIMIT ?', (sid, int(limit))).fetchall()
            for row in rows:
                cursor = self.db.execute("UPDATE session_steers SET state='injected', injected=?"
                                         " WHERE id=? AND state='pending'", (time.time(), row['id']))
                if cursor.rowcount == 1:
                    claimed.append(dict(row))
        return claimed

    def requeue_steer(self, steer_id):
        """`injected` → `pending`: transcript ghi hỏng thì chỉ thị phải quay lại hàng chờ.

        `mark_steer` chỉ chạm hàng `pending`, nên nó không gỡ được một hàng đã bị `claim_steers`
        đánh dấu `injected` — đúng trạng thái cần lùi lại khi bước bơm thất bại.
        """
        with self.db:
            self.db.execute("UPDATE session_steers SET state='pending', injected=NULL"
                            " WHERE id=? AND state='injected'", (int(steer_id),))
        return self.steer(steer_id)

    def mark_steer(self, steer_id, state='dropped'):
        """`pending` → `dropped` (chủ nhà đổi ý, hoặc quá hạn lượt): trả hàng sau khi đổi."""
        with self.db:
            self.db.execute("UPDATE session_steers SET state=?, injected=? WHERE id=? AND state='pending'",
                            (str(state or 'dropped'), time.time(), int(steer_id)))
        return self.steer(steer_id)

    # ------------------------------------------------------------------
    # Phán quyết phản biện hồ sơ (vòng 27 đợt 6, #5968) — khuôn `record_plan_verification`

    def record_research_verification(self, research_id, version, session_id, verdict, issues=None,
                                     summary='', critic_session_id=None, critic_answer_chars=0,
                                     critic_verdict=None, mode='critique'):
        """Ghim MỘT phán quyết cho `(research_id, version)`. Trả hàng vừa ghi."""
        with self.db:
            cursor = self.db.execute(
                'INSERT INTO research_verifications(research_id,version,session_id,verdict,mode,issues,summary,'
                ' critic_session_id,critic_answer_chars,critic_verdict,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (str(research_id), int(version), session_id, str(verdict),
                 str(mode), json.dumps(list(issues or []), ensure_ascii=False), str(summary or ''),
                 critic_session_id, int(critic_answer_chars or 0), critic_verdict, time.time()))
        row = self.db.execute('SELECT * FROM research_verifications WHERE id=?',
                              (int(cursor.lastrowid),)).fetchone()
        return self._verification_view(row)

    def research_verifications(self, research_id, version=None, limit=20):
        """Phán quyết của một việc (mới → cũ), lọc theo bản khi có `version`."""
        sql = 'SELECT * FROM research_verifications WHERE research_id=?'
        params = [str(research_id)]
        if version is not None:
            sql += ' AND version=?'
            params.append(int(version))
        sql += ' ORDER BY id DESC LIMIT ?'
        params.append(int(limit))
        return [self._verification_view(row) for row in self.db.execute(sql, params).fetchall()]

    def research_verification_latest(self, research_id, version=None):
        """Phán quyết MỚI NHẤT của một việc (hoặc của một bản), hay `None`."""
        rows = self.research_verifications(research_id, version=version, limit=1)
        return rows[0] if rows else None

    def research_verification_count(self, research_id, verdict=None):
        """Số phán quyết của một việc — có `verdict` thì đếm đúng loại (`revise` để đếm vòng)."""
        sql = 'SELECT COUNT(*) AS total FROM research_verifications WHERE research_id=?'
        params = [str(research_id)]
        if verdict is not None:
            sql += ' AND verdict=?'
            params.append(str(verdict))
        row = self.db.execute(sql, params).fetchone()
        return int((row['total'] if row else 0) or 0)

    def dossier_critique_set(self, research_id, version, critique):
        """Ghi nhãn phản biện lên chính hàng hồ sơ: `none` → `ok`/`revise`."""
        with self.db:
            self.db.execute('UPDATE research_dossiers SET critique=? WHERE research_id=? AND version=?',
                            (str(critique or 'none'), str(research_id), int(version)))
        return self.dossier(research_id, version)

    @staticmethod
    def _verification_view(row):
        """Hàng DB → dict dùng được ở tầng trên (`issues` đã giải JSON)."""
        item = dict(row)
        try:
            item['issues'] = json.loads(item.get('issues') or '[]')
        except (TypeError, ValueError):
            item['issues'] = []
        item['researchId'] = item.pop('research_id', '')
        item['sessionId'] = item.pop('session_id', '')
        item['criticSessionId'] = item.pop('critic_session_id', None)
        item['criticAnswerChars'] = int(item.pop('critic_answer_chars', 0) or 0)
        item['criticVerdict'] = item.pop('critic_verdict', None)
        item.pop('id', None)
        return item

    def close(self):
        self.db.close()

