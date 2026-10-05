"""Per-context skill loading. No instructions are considered loaded after summarization."""
import json


class SkillLoader:
    def __init__(self, catalog, emit):
        self.catalog, self.emit = catalog, emit
        self.loaded = {}

    def reset(self, sid):
        self.loaded.pop(sid, None)

    def read(self, session, sid, file='SKILL.md', messages=None, *, _prepared=None):
        if sid not in session['config']['skills']:
            raise PermissionError('Skill is not enabled for this session')
        # H5 truyền ảnh nguồn đã admit để tránh đọc lại file khác giữa kiểm và load.
        payload = self.catalog.read(sid, file) if _prepared is None else dict(_prepared)
        if payload['id'] != sid or payload['file'] != file:
            raise ValueError('SKILL_SOURCE_MISMATCH: prepared source is for another skill file')
        if len(payload['content'].encode('utf-8')) // 3 > session['config']['contextWindow'] // 2:
            raise ValueError('SKILL_CONTEXT_LIMIT: full skill exceeds half the context budget')
        key = (sid, file, payload['sha256'])
        cache = self.loaded.setdefault(session['id'], set())
        # Dedup only against an actual full message still present in this request's context.
        present = messages is not None and any(payload['content'] in str(m.get('content', '')) or
            json.dumps(payload['content'], ensure_ascii=False)[1:-1] in str(m.get('content', '')) for m in messages)
        if key in cache and present:
            return {'id': sid, 'file': file, 'sha256': key[2], 'status': 'unchanged', 'content_returned': False}
        cache.add(key)
        self.emit(session['id'], 'skill_loaded', {'id': sid, 'file': file, 'sha256': key[2], 'basePath': payload['basePath']})
        return payload
