"""Decimal 4/5 GB warnings, separate logical attribution from physical measurement."""
import os
import time
from pathlib import Path

WARNING_BYTES = 4_000_000_000
ELEVATED_BYTES = 5_000_000_000


def level(size):
    return 'elevated' if size >= ELEVATED_BYTES else 'warning' if size >= WARNING_BYTES else 'normal'


class StorageUsage:
    def __init__(self, history):
        self.history = history
        self.db = history.db
        self.db.execute('CREATE TABLE IF NOT EXISTS history_storage_warning(id INTEGER PRIMARY KEY CHECK(id=1),level TEXT)')
        self.db.commit()

    def measure(self, projection_roots=()):
        seen, total, complete = set(), 0, True
        roots = [self.history.root / 'history', self.history.root / 'memory', *map(Path, projection_roots)]
        def count(path):
            nonlocal total, complete
            try:
                st = path.lstat()
                if path.is_symlink():
                    complete = False
                    return
                identity = (st.st_dev, st.st_ino)
                if identity not in seen:
                    seen.add(identity); total += st.st_size
            except OSError:
                complete = False
        for suffix in ('', '-wal', '-shm'):
            path = Path(str(self.history.store.path) + suffix)
            if path.exists():
                count(path)
        def failed(exc):
            nonlocal complete
            complete = False
        for root in roots:
            if not root.exists():
                continue
            if root.is_symlink():
                complete = False; continue
            for folder, dirs, files in os.walk(root, onerror=failed, followlinks=False):
                for name in dirs:
                    if (Path(folder) / name).is_symlink():
                        complete = False
                for name in files:
                    count(Path(folder) / name)
        projects, sessions, reclaimable = {}, {}, 0
        for row in self.db.execute("SELECT project_id,session_id,SUM(bytes) bytes FROM history_records WHERE evidence_state!='deleted' GROUP BY project_id,session_id"):
            projects[row['project_id'] or 'legacy_self_only'] = projects.get(row['project_id'] or 'legacy_self_only', 0) + row['bytes']
            sessions[row['session_id']] = row['bytes']; reclaimable += row['bytes']
        retained = sum(p.stat().st_size for p in (self.history.root / 'memory').rglob('capsule_*') if p.is_file() and not p.is_symlink())
        return {'bytes': total, 'totalGB': total / 1_000_000_000, 'unit': 'GB',
                'warningAtBytes': WARNING_BYTES, 'elevatedAtBytes': ELEVATED_BYTES, 'level': level(total),
                'byProject': projects, 'bySession': sessions, 'reclaimableBytes': reclaimable,
                'retainedBytes': retained, 'measuredAt': time.time(), 'measurementComplete': complete}

    def warning_transition(self, size):
        current = level(size)
        row = self.db.execute('SELECT level FROM history_storage_warning WHERE id=1').fetchone()
        previous = row[0] if row else 'normal'
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO history_storage_warning VALUES(1,?)', (current,))
        return {'level': current, 'bytes': size, 'threshold': ELEVATED_BYTES if current == 'elevated' else WARNING_BYTES} if current != previous and current != 'normal' else None
