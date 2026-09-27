"""BoxFox command registry. Adapted from Hermes agent/skill_commands.py (MIT).

Resolution is pure: it never invokes a model, shell, or external CLI.
"""
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from ..agent_core.roles import ROLES
from .catalog import DEFAULT_SKILLS

ROLE_COMMANDS = {name: name for name in ROLES} | {'test': 'testing'}
ROLE_COMMANDS.pop('testing')
# P1 (§5.2, cửa 3): `/research` không còn là lệnh VAI. Nó là lệnh MODE (bật mode, mở run) khi
# BOXFOX_RESEARCH_MODE bật; khi công tắc tắt, `resolve` vẫn trả về hành vi lệnh vai cũ.
ROLE_COMMANDS.pop('research', None)
INFO = {'help', 'skills', 'agents', 'status', 'context'}
BUILTINS = INFO | set(ROLE_COMMANDS) | {'skill', 'compact', 'stop', 'claude-code', 'claude-design',
                                       'research'}
EXTERNAL = {'claude-code', 'codex', 'opencode'}
# P1 (§5.2): mô tả cho các lệnh MODE trong `/help`.
MODE_DESCRIPTIONS = {'research': 'Enable Research mode; `/research <task>` starts it right away, '
                                '`/research off` exits, `/research status` shows the run'}
# Default role per CLI command. The role is not tied to the executor: change these entries
# (or use a custom command with an explicit role) instead of hardcoding a role in the dispatcher.
CLI_DEFAULT_ROLES = {'claude-code': 'build', 'claude-design': 'orchestrator'}
ROLE_SKILLS = {
    'explore': {'codebase-inspection', 'ast-grep'},
    'plan': {'codebase-inspection', 'grill-me'},
    # Vòng 25 (D-33): người phản biện kế hoạch — vai read-only nên chỉ cần kỹ năng soi mã.
    'plan-review': {'codebase-inspection'},
    'design': {'design-md', 'claude-design', 'popular-web-designs', 'architecture-diagram'},
    'build': {'codebase-inspection', 'test-driven-development', 'claude-design', 'popular-web-designs', 'design-md'},
    'debug': {'systematic-debugging', 'codebase-inspection', 'test-driven-development'},
    'review': {'requesting-code-review', 'codebase-inspection'},
    'simplify': {'simplify-code', 'codebase-inspection'},
    'testing': {'test-driven-development', 'dogfood', 'claude-design'},
    'research': {'research-team', 'research-search', 'research-reading', 'research-evidence',
                 'grounded-citations', 'arxiv', 'blocked-page-recovery', 'codebase-inspection'},
    # Vòng 27 (đợt 6, D-36): người phản biện hồ sơ — vai chỉ-đọc, cùng bộ kỹ năng soi mã với
    # `plan-review`. Thiếu khoá này thì `delegate_task(role="research-review")` ném KeyError
    # ngay ở bước chọn kỹ năng cho con (đo sống: `TURN_FAILED_KEYERROR: KeyError: 'research-review'`).
    'research-review': {'codebase-inspection', 'research-critique', 'research-evidence',
                        'research-search', 'research-reading'},
}


def slug(value):
    return re.sub(r'-+', '-', re.sub(r'[^\w-]', '', value.lower().replace('_', '-').replace(' ', '-'))).strip('-')


def folded(value):
    return ''.join(c for c in unicodedata.normalize('NFD', value.lower()) if unicodedata.category(c) != 'Mn').replace('đ', 'd')


@dataclass
class Resolution:
    kind: str = 'message'
    command: str = ''
    prompt: str = ''
    role: str = 'orchestrator'
    executor: str = 'native'
    skills: list = field(default_factory=list)
    revision: int = 0
    reason: str = 'ordinary_message'


class CommandRegistry:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        store.db.executescript('''
            CREATE TABLE IF NOT EXISTS skill_settings (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS custom_commands (slug TEXT PRIMARY KEY, value TEXT NOT NULL, revision INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS command_invocations (session_id TEXT NOT NULL, id TEXT NOT NULL, request TEXT NOT NULL, result TEXT NOT NULL, PRIMARY KEY(session_id,id));
        ''')
        store.db.commit()

    def settings(self):
        row = self.store.db.execute('SELECT value,revision FROM skill_settings WHERE id=1').fetchone()
        return {'enabled': json.loads(row[0]) if row else sorted(DEFAULT_SKILLS & self.catalog.items.keys()),
                'revision': row[1] if row else 0, 'initialized': bool(row)}

    def configure(self, value):
        current = self.settings()
        if value.get('importLegacy') and current['initialized']:
            return current
        if not value.get('importLegacy') and value.get('revision') != current['revision']:
            raise ValueError('REVISION_CONFLICT: reload skill settings')
        enabled = value.get('enabled')
        if not isinstance(enabled, list) or any(not isinstance(s, str) or s not in self.catalog.items for s in enabled):
            raise ValueError('Unknown skills selection')
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO skill_settings VALUES(1,?,?)',
                                  (json.dumps(sorted(set(enabled))), current['revision'] + 1))
        return self.settings()

    def custom(self):
        return [json.loads(r[0]) | {'revision': r[1]} for r in self.store.db.execute('SELECT value,revision FROM custom_commands ORDER BY slug')]

    def aliases(self):
        aliases = {}
        for sid, item in self.catalog.items.items():
            key = slug(item['name'])
            if key and key not in BUILTINS and key not in aliases:
                aliases[key] = sid
        return aliases

    def list(self):
        enabled = set(self.settings()['enabled'])
        rows = [{'slug': key, 'description': MODE_DESCRIPTIONS.get(key) or (('Use ' + ROLE_COMMANDS[key] + ' specialist') if key in ROLE_COMMANDS else key.replace('-', ' ')),
                 'kind': 'builtin', 'enabled': key not in {'claude-code', 'claude-design'} or key in enabled} for key in sorted(BUILTINS)]
        rows += [{'slug': key, 'description': self.catalog.items[sid]['description'], 'kind': 'skill',
                  'enabled': sid in enabled and sid not in {'codex', 'opencode'}, 'skillId': sid,
                  'reason': 'adapter_unavailable' if sid in {'codex', 'opencode'} else ''} for key, sid in self.aliases().items()]
        rows += [dict(c, kind='custom') for c in self.custom()]
        return rows

    def validate_skills(self, skills, enabled=None, executor='native', role='orchestrator'):
        if not isinstance(skills, list) or any(not isinstance(s, str) or s not in self.catalog.items for s in skills):
            raise ValueError('Unknown skill')
        external = set(skills) & EXTERNAL
        if len(external | ({executor} if executor != 'native' else set())) > 1:
            raise ValueError('EXECUTOR_CONFLICT: choose one CLI executor')
        if external & {'codex', 'opencode'}:
            raise ValueError('ADAPTER_UNAVAILABLE: Codex/OpenCode packages remain available for inspection')
        if 'claude-code' in external and executor != 'claude-code':
            raise ValueError('EXECUTOR_CONFLICT: claude-code skill requires its CLI executor')
        if enabled is not None and set(skills) - set(enabled):
            raise ValueError('SKILL_DISABLED: enable the requested skill in Settings')
        if role in {'explore', 'plan', 'review', 'research'}:
            if set(skills) - ROLE_SKILLS[role] - EXTERNAL:
                raise ValueError('ROLE_SKILL_CONFLICT: workflow requires a different specialist')
        return list(dict.fromkeys(skills))

    def save(self, value, key=None):
        name = value.get('slug', '')
        if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9-]{1,63}', name):
            raise ValueError('Command slug must use 2–64 lowercase letters, digits or hyphens')
        if name in BUILTINS or name in self.aliases():
            raise ValueError('COMMAND_COLLISION: this name is reserved')
        current = next((c for c in self.custom() if c['slug'] == name), None)
        if key and key != name:
            raise ValueError('Command slug cannot change; create a new command')
        if (current and (not key or value.get('revision') != current['revision'])) or (key and not current):
            raise ValueError('REVISION_CONFLICT: reload commands')
        role, executor = value.get('role', 'build'), value.get('executor', 'native')
        if role not in ROLES or executor not in {'native', 'claude-code'}:
            raise ValueError('Invalid role or executor')
        skills = value.get('skills', [])
        if executor == 'claude-code' and 'claude-code' not in skills:
            skills = [*skills, 'claude-code']
        skills = self.validate_skills(skills, executor=executor, role=role)
        template, description = value.get('template', ''), value.get('description', '')
        if not isinstance(template, str) or not template.strip() or len(template) > 12000:
            raise ValueError('Prompt template must contain 1–12000 characters')
        if not isinstance(description, str) or len(description) > 500 or not isinstance(value.get('enabled', True), bool):
            raise ValueError('Invalid command metadata')
        row = dict(slug=name, description=description, template=template, skills=skills,
                   role=role, executor=executor, enabled=value.get('enabled', True))
        revision = (current['revision'] if current else 0) + 1
        with self.store.db:
            self.store.db.execute('INSERT OR REPLACE INTO custom_commands VALUES(?,?,?)', (name, json.dumps(row), revision))
        return row | {'revision': revision}

    def delete(self, key, revision):
        with self.store.db:
            cursor = self.store.db.execute('DELETE FROM custom_commands WHERE slug=? AND revision=?', (key, revision))
            if not cursor.rowcount:
                raise ValueError('REVISION_CONFLICT: reload commands')

    def resolve(self, prompt, enabled=None, subagents=None):
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Prompt is required')
        enabled = self.settings()['enabled'] if enabled is None else enabled
        result = Resolution(prompt=prompt)
        match = re.match(r'^/([\w.-]+)(?:\s+(.*))?$', prompt.strip(), re.S)
        if match:
            key, args = match.group(1).lower().replace('_', '-'), (match.group(2) or '').strip()
            if re.match(r'^/[\w.-]+(?:\s|$)', args):
                raise ValueError('Use one command per message; combine skills in a custom command')
            result.command, result.prompt, result.reason = key, args, 'explicit_command'
            if key in INFO | {'stop', 'compact'}:
                if args:
                    raise ValueError('This command takes no arguments')
                result.kind = 'control'
                return result
            if key == 'research':
                from ..agent_core.runtime import research_mode_available
                if research_mode_available():
                    # Lệnh MODE: `/research` (rỗng) bật mode, `/research <text>` bật + nộp lượt,
                    # `/research off` và `/research status` là hai từ khoá điều khiển.
                    result.kind, result.command, result.reason = 'mode', 'research', 'mode_command'
                    low = args.strip().lower()
                    result.prompt = '' if low in ('', 'on') else (low if low in ('off', 'status')
                                                                  else args.strip())
                    self.validate_skills(result.skills, enabled, result.executor, result.role)
                    return result
                # Công tắc tắt ⇒ giữ nguyên hành vi cũ: lệnh vai research.
                result.kind, result.role = 'task', 'research'
                result.skills = sorted(set(enabled) & ROLE_SKILLS['research'])
            elif key in ROLE_COMMANDS:
                result.kind, result.role = 'task', ROLE_COMMANDS[key]
                result.skills = sorted(set(enabled) & ROLE_SKILLS[result.role])
            elif key in {'claude-code', 'claude-design'}:
                result.kind, result.skills = 'task', [key]
                # The executor is a transport choice; the role decides tools and instructions.
                # Change CLI_DEFAULT_ROLES to retarget a CLI without touching the dispatch path,
                # and custom commands can already carry any role with this executor.
                result.executor = 'claude-code' if key == 'claude-code' else 'native'
                result.role = CLI_DEFAULT_ROLES.get(key, 'build')
            elif key == 'skill' or key in self.aliases():
                if key == 'skill':
                    parts = args.split(None, 1)
                    sid, result.prompt = parts[0] if parts else '', parts[1] if len(parts) > 1 else ''
                else:
                    sid = self.aliases()[key]
                result.kind, result.skills = 'task', [sid]
                if sid in EXTERNAL:
                    result.executor, result.role = sid, 'build'
            else:
                custom = next((c for c in self.custom() if c['slug'] == key), None)
                if not custom:
                    raise ValueError('UNKNOWN_COMMAND: use /help or /skill <id>')
                if not custom['enabled']:
                    raise ValueError('COMMAND_DISABLED')
                result = Resolution(kind='task', command=key, prompt=custom['template'].replace('$ARGUMENTS', args),
                                    role=custom['role'], executor=custom['executor'], skills=custom['skills'],
                                    revision=custom['revision'], reason='custom_command')
        else:
            text = folded(prompt)
            # Explicit use intent only; mentioning a product in documentation/comparisons is inert.
            mentions = []
            for sid, pattern in [('claude-code', r'claude[ -]code'), ('codex', r'codex'), ('opencode', r'open[ -]?code'), ('claude-design', r'claude[ -]design')]:
                if re.search(r'(?:\buse\b|\busing\b|\brun\b|\bdelegate to\b|\bdung\b|\bsu dung\b|\bchay\b)\s+(?:the\s+)?' + pattern + r'\b', text):
                    mentions.append(sid)
            if not re.search(r"\b(don.t|do not|never|khong|dung co|compare|difference|so sanh|khac nhau)\b", text) and mentions:
                result.kind, result.skills, result.reason = 'task', mentions, 'explicit_use_intent'
                cli = set(mentions) & EXTERNAL
                if len(cli) > 1:
                    raise ValueError('EXECUTOR_CONFLICT: choose one CLI executor')
                if cli:
                    result.executor, result.role = next(iter(cli)), 'build'
        self.validate_skills(result.skills, enabled, result.executor, result.role)
        if result.executor not in {'native', 'claude-code'}:
            raise ValueError('ADAPTER_UNAVAILABLE')
        if result.kind == 'task' and not result.prompt:
            # Mã lỗi ổn định cho UI (`Mã lỗi: <CODE>`), cùng quy ước với
            # UNKNOWN_COMMAND / COMMAND_DISABLED / SKILL_DISABLED. Thiếu task sau
            # `/skill <id>` (hoặc alias kỹ năng) là SKILL_TASK_REQUIRED; các lệnh
            # vai trò/CLI còn lại là MISSING_TASK. Phần văn bản giữ nguyên.
            code = 'SKILL_TASK_REQUIRED' if result.command == 'skill' or result.command in self.aliases() else 'MISSING_TASK'
            raise ValueError(f'{code}: Include a task after the command')
        if subagents is not None and result.role != 'orchestrator' and not any(r['id'] == result.role and r.get('enabled', True) for r in subagents):
            raise ValueError('ROLE_DISABLED: enable this specialist in the harness')
        if 'claude-design' in result.skills and result.role == 'orchestrator' and subagents is not None:
            if not {'design', 'build', 'testing'} <= {r['id'] for r in subagents if r.get('enabled', True)}:
                raise ValueError('ROLE_DISABLED: claude-design requires Design, Build and Testing')
        return result

    def preview(self, prompt):
        return asdict(self.resolve(prompt))
