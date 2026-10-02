"""Work Graph — the orchestration layer where main is the brain (lớp điều phối mới).

Main (the root orchestrator) turns a prompt, ticket or bug into a durable DAG of nodes:

    explore / research / design  →  plan sub-plans P1..Pn (tests + dependsOn)  →  whole-plan review
    →  owner approval (or Autopilot)  →  DAG-aware parallel execution  →  branch + commit + PR text

Invariants of this module (each one has a unit test):

* Only main delegates. A specialist that lacks knowledge writes a `## Knowledge requests` block;
  the HARNESS (not the specialist) asks `research`/`explore` and re-runs the specialist with the
  answers. Delegation depth stays 1.
* Producers return immutable draft references. Main dispatches minimum task/risk checks.
  Only completed, fully read snapshots with current required checks become accepted; repair
  is bounded and controlled by main. Simple evidence lookups/diagnoses need no default reviewer.
* A node runs only when its dependencies are accepted; independent nodes run in parallel, capped by
  the session fan-out limit. Plan→plan edges order EXECUTION, so sub-plans are written in parallel.
* Execution never starts without owner approval, unless the session Autopilot switch is on.
* SQLite owns the state (`work_runs`); the workspace Markdown under `.plans/work/<slug>/` is the
  artifact the Plan tab shows.
"""
import asyncio
import contextlib
import hashlib
import json
import os
import re
import time
import unicodedata
import uuid
from copy import deepcopy

from . import work_prompts, work_policy, work_artifacts, work_checks, work_feedback, work_grants, work_continuations, work_handoffs

WORK_GRAPH_ENV = 'BOXFOX_WORK_GRAPH'
MARKER = '=== WORK GRAPH ==='
END_MARKER = '=== END WORK GRAPH ==='
INTENT_CONFIG_KEY = 'workIntent'
AUTOPILOT_CONFIG_KEY = 'autopilot'

NODE_ID_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_-]{0,31}$')
DISCOVERY_KINDS = ('explore', 'research', 'design')
PLAN_KIND = 'plan'
EXECUTION_KINDS = ('build', 'debug', 'testing', 'simplify')
NODE_KINDS = DISCOVERY_KINDS + (PLAN_KIND,) + EXECUTION_KINDS
FLOWS = ('plan', 'research', 'design', 'fix', 'mixed')

# Who reviews whom. Review and verify are the same job: an independent child that did not produce
# the output reads it against the node acceptance and ends with one VERDICT line.
PRODUCE_REVIEWER = {'explore': 'review', 'research': 'research-review', 'design': 'plan-review',
                    'plan': 'plan-review'}
EXECUTE_ROLE = {'plan': 'build', 'build': 'build', 'debug': 'debug', 'testing': 'testing',
                'simplify': 'simplify'}
EXECUTE_REVIEWER = {'plan': 'testing', 'build': 'testing', 'debug': 'testing', 'simplify': 'testing',
                    'testing': 'review'}
FLOW_REVIEWER = {'research': 'research-review'}

MAX_NODES = 24
MAX_ROUNDS_DEFAULT = 3
MAX_ROUNDS_CEILING = 4
MAX_GRAPH_REVIEWS = 3
KNOWLEDGE_MAX = 3
WORK_CHILDREN_PER_RUN_CALL = 72
WORK_RUN_MAX_SECONDS = 3600.0
OUTPUT_MAX_CHARS = 20000
CONTEXT_MAX_CHARS = 15000
FINDINGS_MAX_CHARS = 3000
HISTORY_MAX = 120
WORK_SKILL = 'work-graph-planning'
REVIEW_MAX_STEPS = 14
DOCUMENT_MAX_TOKENS = 16000
# Run statuses where main still has a tool call to make before it may end the turn.
DRIVING_STATUSES = ('drafting', 'discovering', 'verifying', 'needs_revision', 'approved', 'executing',
                    'execute_failed')

TERMINAL_STATUSES = ('shipped', 'cancelled', 'rejected')
IN_FLIGHT_STAGE = ('running', 'reviewing', 'researching')
FANOUT_RETRY_SECONDS = 900.0
FANOUT_RETRY_PAUSE = 5.0


class WorkBudgetExhausted(ValueError):
    """The per-call child budget ran out: the node waits for the next `work_run`, it did not fail."""

VERDICT_RE = re.compile(r'^\s*\**\s*VERDICT\s*\**\s*:\s*\**\s*(ok|revise)\b', re.I | re.M)
LEGACY_VERDICT_RE = re.compile(r'\[(APPROVED|CHANGES REQUESTED)\]', re.I)
REVISE_NODE_RE = re.compile(r'^\s*[-*]?\s*REVISE\s+([A-Za-z][A-Za-z0-9_-]{0,31})\s*[:\-—]\s*(.+)$', re.M)
KNOWLEDGE_HEADER_RE = re.compile(r'^#{2,4}\s*Knowledge requests?\s*$', re.I | re.M)
KNOWLEDGE_LINE_RE = re.compile(r'^\s*[-*]\s*(research|explore)\s*[:\-—]\s*(.+)$', re.I)


def enabled():
    """`BOXFOX_WORK_GRAPH=off` returns every slash command and prompt to the legacy mode path."""
    return str(os.environ.get(WORK_GRAPH_ENV, 'on')).strip().lower() not in {'off', '0', 'false', 'no'}


def service(rt):
    found = getattr(rt, 'work_graph', None)
    if found is None:
        found = rt.work_graph = WorkGraph(rt)
    return found


def now():
    return round(time.time(), 3)


def slugify(text, limit=40):
    raw = str(text or '').replace('đ', 'd').replace('Đ', 'D')
    folded = unicodedata.normalize('NFKD', raw).encode('ascii', 'ignore').decode().lower()
    slug = re.sub(r'[^a-z0-9]+', '-', folded).strip('-')
    slug = re.sub(r'-{2,}', '-', slug)[:limit].strip('-')
    return slug or 'work'


SLASH_FLOWS = ('plan', 'research', 'design')


def grants_skill(session):
    """The root orchestrator always may open the Work Graph skill while the engine is on."""
    return enabled() and not session.get('parent_id') and session.get('role') == 'orchestrator'


def writes_document(work, role):
    """A plan/design producer writes a long document in its final answer."""
    return work.get('purpose') == 'produce' and work.get('stage') == 'produce' and role in ('plan', 'design')


def driving(rt, session):
    """True while the root session's active run still needs main's next tool call."""
    if not grants_skill(session):
        return False
    try:
        run = service(rt).active(session['id'])
    except Exception:  # the recap must never fail a turn
        return False
    return run is not None and run['status'] in DRIVING_STATUSES


def wrap_up_note(session):
    """Extra wrap-up line for a Work Graph reviewer: out of steps means `verdict now`, not a diagnosis."""
    work = (session.get('config') or {}).get('workBinding') or {}
    if work.get('purpose') != 'review':
        return ''
    return (' You are a Work Graph reviewer: write your review NOW from what you already checked — '
            '`## Blocking findings` (or `none`), then the final `VERDICT: ok` or `VERDICT: revise` line.')


def set_intent(rt, session, command, text):
    """`/plan|/research|/design <text>` → `config.workIntent`; the next main turn reads it."""
    intent = {'command': command, 'flow': command if command in FLOWS else 'mixed',
              'text': str(text or '').strip()[:4000], 'at': now()}
    config = session.setdefault('config', {})
    config[INTENT_CONFIG_KEY] = intent
    rt.store.update_config(session['id'], config)
    rt.store.emit(session['id'], 'work_intent', intent)
    return intent


def set_autopilot(rt, sid, on):
    """Session switch: `on` lets verified runs execute without waiting for the owner."""
    session = rt.store.get(sid)
    config = session.setdefault('config', {})
    config[AUTOPILOT_CONFIG_KEY] = bool(on)
    rt.store.update_config(sid, config)
    result = {'on': bool(on), 'sessionId': sid}
    if enabled():
        work = service(rt)
        run = work.active(sid)
        if run is not None:
            run = work.current(run['runId'])
            run['autopilot'] = bool(on)
            work.save(run, 'autopilot', 'on' if on else 'off')
            result['runId'] = run['runId']
            pending = [record for record in rt.pending_for(sid) if record.get('workRunId') == run['runId']]
            if on and pending:
                # An approval card is already waiting: Autopilot answers it for the owner.
                for record in pending:
                    rt.settle(record, 'approve', 'approved', 'autopilot', None)
    rt.store.emit(sid, 'autopilot', result)
    return result


def autopilot_on(session):
    return bool(((session or {}).get('config') or {}).get(AUTOPILOT_CONFIG_KEY))


# --------------------------------------------------------------------------- #
# Pure helpers (unit-tested without a runtime)
# --------------------------------------------------------------------------- #

def stages_for(kind):
    if kind in DISCOVERY_KINDS:
        return ('produce',)
    if kind == PLAN_KIND:
        return ('produce', 'execute')
    return ('execute',)


def new_stage():
    return {'status': 'pending', 'attempts': 0, 'rounds': [], 'output': '', 'outputChars': 0,
            'feedback': '', 'knowledge': [], 'error': None, 'startedAt': None, 'finishedAt': None}


def clean_list(value, field, limit=20, item_limit=600):
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        raise ValueError(f'WORK_NODE_INVALID: `{field}` must be a list of strings')
    if len(value) > limit:
        raise ValueError(f'WORK_NODE_INVALID: `{field}` allows at most {limit} items; split the assignment, do not drop criteria')
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f'WORK_NODE_INVALID: `{field}` must contain strings')
        text = item.strip()
        if len(text) > item_limit:
            raise ValueError(f'WORK_NODE_INVALID: `{field}` item exceeds {item_limit} characters; shorten explicitly')
        if text:
            out.append(text)
    return out


def normalize_node(raw, existing=None):
    """One node from the model → the stored shape. Errors name the field and the expected shape."""
    if not isinstance(raw, dict):
        raise ValueError('WORK_NODE_INVALID: each node must be an object {id, kind, title, goal, dependsOn, '
                         'acceptance, tests, files}')
    base = deepcopy(existing) if existing else {}
    node_id = str(raw.get('id') or base.get('id') or '').strip()
    if not NODE_ID_RE.fullmatch(node_id):
        raise ValueError(f'WORK_NODE_INVALID: id {node_id!r} must start with a letter and use only letters, '
                         'digits, - or _ (max 32), for example P1 or research-auth')
    kind = str(raw.get('kind') or base.get('kind') or '').strip().lower()
    if kind not in NODE_KINDS:
        raise ValueError(f'WORK_NODE_INVALID: node {node_id}: kind {kind!r} must be one of {list(NODE_KINDS)}')
    if existing and kind != existing['kind']:
        raise ValueError(f'WORK_NODE_INVALID: node {node_id}: kind cannot change ({existing["kind"]} → {kind}); '
                         'remove the node and add a new one')
    title = str(raw.get('title') or base.get('title') or '').strip()[:160]
    goal = str(raw.get('goal') or base.get('goal') or '').strip()[:6000]
    if not title:
        raise ValueError(f'WORK_NODE_INVALID: node {node_id}: `title` is required (a short name)')
    if len(goal) < 20:
        raise ValueError(f'WORK_NODE_INVALID: node {node_id}: `goal` must be a complete, self-contained '
                         'assignment (at least 20 characters)')
    for field, choices in (('taskKind', work_policy.TASKS), ('artifactKind', work_policy.ARTIFACTS), ('risk', work_policy.RISKS)):
        value = raw.get(field, base.get(field))
        if value is not None and value not in choices:
            raise ValueError(f'WORK_NODE_INVALID: {field} must be one of {choices}')
    node = {'id': node_id, 'kind': kind, 'title': title, 'goal': goal,
            'dependsOn': clean_list(raw.get('dependsOn', base.get('dependsOn')), 'dependsOn', 16, 32),
            'acceptance': clean_list(raw.get('acceptance', base.get('acceptance')), 'acceptance', 64),
            'tests': clean_list(raw.get('tests', base.get('tests')), 'tests'),
            'files': clean_list(raw.get('files', base.get('files')), 'files', 40, 300)}
    for field in ('taskKind', 'artifactKind', 'risk'):
        if raw.get(field, base.get(field)) is not None:
            node[field] = raw.get(field, base.get(field))
    if node_id in node['dependsOn']:
        raise ValueError(f'WORK_NODE_INVALID: node {node_id} cannot depend on itself')
    if kind == PLAN_KIND and not node['acceptance']:
        raise ValueError(f'WORK_NODE_INVALID: sub-plan {node_id} needs `acceptance` (observable checks)')
    if kind in (PLAN_KIND, 'build', 'debug') and not node['tests']:
        raise ValueError(f'WORK_NODE_INVALID: node {node_id} ({kind}) needs `tests`: the test cases or '
                         'commands that prove it works')
    stages = base.get('stages') or {}
    node['stages'] = {name: stages.get(name) or new_stage() for name in stages_for(kind)}
    return node


def graph_issues(nodes):
    """Structural problems of the DAG, as short sentences (empty list = valid)."""
    issues = []
    ids = [node['id'] for node in nodes]
    seen = set()
    for node_id in ids:
        if node_id in seen:
            issues.append(f'duplicate node id {node_id}')
        seen.add(node_id)
    by_id = {node['id']: node for node in nodes}
    for node in nodes:
        for dep in node['dependsOn']:
            target = by_id.get(dep)
            if target is None:
                issues.append(f'{node["id"]} depends on unknown node {dep}')
                continue
            if node['kind'] in DISCOVERY_KINDS + (PLAN_KIND,) and target['kind'] in EXECUTION_KINDS:
                issues.append(f'{node["id"]} ({node["kind"]}) cannot depend on execution node {dep} '
                              f'({target["kind"]}); planning must not wait for code')
    cycle = find_cycle(nodes)
    if cycle:
        issues.append('dependency cycle: ' + ' → '.join(cycle))
    return issues


def check_graph(nodes):
    issues = graph_issues(nodes)
    if issues:
        raise ValueError('WORK_GRAPH_INVALID: ' + '; '.join(issues))


def find_cycle(nodes):
    by_id = {node['id']: node for node in nodes}
    state = {}
    stack = []

    def visit(node_id):
        state[node_id] = 1
        stack.append(node_id)
        for dep in by_id[node_id]['dependsOn']:
            if dep not in by_id:
                continue
            if state.get(dep) == 1:
                return stack[stack.index(dep):] + [dep]
            if state.get(dep) is None:
                found = visit(dep)
                if found:
                    return found
        stack.pop()
        state[node_id] = 2
        return None

    for node in nodes:
        if state.get(node['id']) is None:
            found = visit(node['id'])
            if found:
                return found
    return None


def execution_waves(nodes):
    """Topological layers for the execution DAG (what runs together). Plan + execution nodes only."""
    runnable = [node for node in nodes if 'execute' in node['stages']]
    ids = {node['id'] for node in runnable}
    remaining = {node['id']: {dep for dep in node['dependsOn'] if dep in ids} for node in runnable}
    waves = []
    while remaining:
        layer = sorted(node_id for node_id, deps in remaining.items() if not deps)
        if not layer:
            break
        waves.append(layer)
        for node_id in layer:
            remaining.pop(node_id)
        for deps in remaining.values():
            deps.difference_update(layer)
    return waves


def stage_done(node, stage):
    state = node['stages'].get(stage)
    return bool(state) and state['status'] == 'accepted' and state.get('artifact', {}).get('status') == 'finalized'


def gate_stage(node, dep, stage):
    """Which stage of `dep` gates `node`'s `stage` (None: the edge does not gate it)."""
    if stage == 'execute':
        return 'execute' if 'execute' in dep['stages'] else 'produce'
    if node['kind'] == PLAN_KIND and dep['kind'] == PLAN_KIND:
        return None  # plan→plan orders execution; sub-plans are written in parallel
    return 'produce'


def dependency_satisfied(node, dep, stage):
    """Is `dep` far enough along for `node`'s `stage` to start?"""
    gate = gate_stage(node, dep, stage)
    return gate is None or stage_done(dep, gate)


def ready_nodes(run, stage, only=None):
    by_id = {node['id']: node for node in run['nodes']}
    ready = []
    for node in run['nodes']:
        state = node['stages'].get(stage)
        if not state or state['status'] not in ('pending', 'revise'):
            continue
        if only and node['id'] not in only:
            continue
        if all(dep in by_id and dependency_satisfied(node, by_id[dep], stage) for dep in node['dependsOn']):
            ready.append(node)
    return ready


def blocked_nodes(run, stage):
    """Nodes that can never start because a dependency ended rejected/failed."""
    by_id = {node['id']: node for node in run['nodes']}
    dead = set()
    changed = True
    while changed:
        changed = False
        for node in run['nodes']:
            state = node['stages'].get(stage)
            if not state or node['id'] in dead:
                continue
            if state['status'] in ('rejected', 'failed'):
                dead.add(node['id'])
                changed = True
                continue
            if state['status'] in ('pending', 'revise'):
                for dep in node['dependsOn']:
                    target = by_id.get(dep)
                    if target is None:
                        continue
                    dep_stage = gate_stage(node, target, stage)
                    if dep_stage is None or dep_stage not in target['stages']:
                        continue
                    if dep in dead or target['stages'][dep_stage]['status'] in ('rejected', 'failed'):
                        dead.add(node['id'])
                        changed = True
                        break
    return sorted(node_id for node_id in dead
                  if by_id[node_id]['stages'].get(stage, {}).get('status') in ('pending', 'revise'))


def parse_verdict(text):
    """(`ok` | `revise` | None, findings). The LAST verdict line wins; `[APPROVED]` is the legacy form."""
    raw = str(text or '')
    matches = VERDICT_RE.findall(raw)
    verdict = matches[-1].lower() if matches else None
    if verdict is None:
        legacy = LEGACY_VERDICT_RE.findall(raw)
        if legacy:
            verdict = 'ok' if legacy[-1].upper() == 'APPROVED' else 'revise'
    findings = VERDICT_RE.sub('', raw).strip()
    return verdict, findings[:FINDINGS_MAX_CHARS]


BLOCKING_RE = re.compile(r'^[\s#*]*(?:Blocking findings|Vấn đề chặn)\b[\s*]*(.*)$', re.I | re.M)
SECTION_END_RE = re.compile(r'^[\s#*]*(#{1,4}\s|Non-blocking|Ghi chú không chặn)', re.I | re.M)
NONE_WORDS = ('none', 'no blocking findings', 'no blocking finding', 'nothing blocking', 'n/a',
              'không', 'không có', 'không có vấn đề chặn')


def has_no_blocking_findings(findings):
    """True when the review's `Blocking findings` section says `none` (a `revise` then counts as `ok`)."""
    raw = str(findings or '')
    match = BLOCKING_RE.search(raw)
    if not match:
        return False
    body = raw[match.end():]
    end = SECTION_END_RE.search(body)
    text = f'{match.group(1)} {body[:end.start()] if end else body}'
    return text.strip(' \t\r\n:.-*`_—()').lower() in NONE_WORDS


def parse_knowledge_requests(text):
    """`## Knowledge requests` block → [{role, question}] (max 3). `- none` means no request."""
    raw = str(text or '')
    match = KNOWLEDGE_HEADER_RE.search(raw)
    if not match:
        return []
    block = raw[match.end():]
    end = re.search(r'^#{1,4}\s', block, re.M)
    if end:
        block = block[:end.start()]
    requests = []
    for line in block.splitlines():
        found = KNOWLEDGE_LINE_RE.match(line)
        if not found:
            continue
        question = found.group(2).strip()
        if question.lower().rstrip('.') in {'none', 'không', 'khong', 'n/a'} or len(question) < 8:
            continue
        requests.append({'role': found.group(1).lower(), 'question': question[:600]})
        if len(requests) >= KNOWLEDGE_MAX:
            break
    return requests


def parse_revise_targets(text, ids):
    """`REVISE P2: reason` lines of a whole-plan review → {nodeId: reason} for known ids."""
    targets = {}
    for node_id, reason in REVISE_NODE_RE.findall(str(text or '')):
        if node_id in ids:
            targets[node_id] = (targets.get(node_id, '') + '\n' + reason.strip()).strip()[:FINDINGS_MAX_CHARS]
    return targets


def bounded(text, limit):
    raw = str(text or '')
    return raw if len(raw) <= limit else raw[:limit] + f'\n[... bounded at {limit} characters]'


# --------------------------------------------------------------------------- #
# Prompts: deliverable templates per node kind and review rubrics
# --------------------------------------------------------------------------- #

# English aliases preserve callers inspecting the existing prompt constants.
KNOWLEDGE_CONTRACT = work_prompts.KNOWLEDGE['en']
DELIVERABLES = work_prompts.DELIVERABLES_EN
REVIEW_RUBRICS = work_prompts.RUBRICS_EN
REVIEW_TAIL = work_prompts.REVIEW_TAIL_EN
WORK_NODE_CONTRACT = work_prompts.child_contract('produce')
REVIEW_CONTRACT = work_prompts.child_contract('review')


def work_child_contract(purpose, language='en'):
    return work_prompts.child_contract(purpose, language)


# --------------------------------------------------------------------------- #
# Service
# --------------------------------------------------------------------------- #

class WorkGraph:
    def __init__(self, rt):
        self.rt = rt
        self.store = rt.store
        self.db = rt.store.db
        self.locks = {}
        self.child_budget = {}
        self.live = {}  # runId -> the dict `work_run` is mutating; other writers must edit THAT copy
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_runs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
                revision INTEGER NOT NULL, doc TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS work_runs_session ON work_runs(session_id, updated);
        ''')
        self.artifacts = work_artifacts.Artifacts(self)
        self.checks = work_checks.Checks(self)
        self.feedback = work_feedback.Feedback(self)
        self.grants = work_grants.Grants(self)
        self.handoffs = work_handoffs.Handoffs(self)
        from .work_decisions import Decisions
        self.decisions = Decisions(self)
        self.recover()
        self.continuations = work_continuations.Continuations(self)

    def recover(self):
        """A new process owns no child: reset in-flight stages so the next `work_run` re-runs them."""
        rows = self.db.execute('SELECT id FROM work_runs WHERE status NOT IN (%s)'
                               % ','.join('?' * len(TERMINAL_STATUSES)), TERMINAL_STATUSES).fetchall()
        for row in rows:
            try:
                run = self.get(row['id'])
            except (ValueError, json.JSONDecodeError):
                continue
            changed = False
            for request in self.feedback.records(run['runId']):
                if request['status'] == 'resuming':
                    request['status'] = 'interrupted'
                    with self.db:
                        self.feedback.save(request)
                    node = next((n for n in run['nodes'] if n['id'] == request['binding'].get('nodeId')), None)
                    if node and request['binding']['purpose'] == 'produce':
                        node['stages'][request['binding']['stage']].update(status='needs_user', requestId=request['requestId'],
                            checkpoint=request, error='WORK_RESUME_INTERRUPTED: inspect saved child before continuing; do not replace silently')
                    changed = True
            for node in run['nodes']:
                for state in node['stages'].values():
                    if state['status'] in IN_FLIGHT_STAGE:
                        state['status'] = 'revise' if state.get('rounds') else 'pending'
                        state['attempts'] = max(0, int(state.get('attempts') or 0) - 1)
                        state['error'] = 'interrupted by a restart'
                        changed = True
            status = {'executing': 'approved', 'verifying': 'discovering'}.get(run['status'])
            if status:
                run['status'] = status
                changed = True
            if changed:
                self.save(run, 'recovered', 'in-flight work was reset after a restart')

    def current(self, run_id):
        """The live copy while `work_run` holds the run, else the stored one (no lost updates)."""
        return self.live.get(run_id) or self.get(run_id)

    def busy(self, run):
        lock = self.locks.get(run['runId'])
        return lock is not None and lock.locked()

    # ---- storage --------------------------------------------------------------------------- #

    def get(self, run_id):
        row = self.db.execute('SELECT * FROM work_runs WHERE id=?', (str(run_id or ''),)).fetchone()
        if row is None:
            raise ValueError(f'WORK_RUN_UNKNOWN: no Work Graph run {run_id!r}')
        return json.loads(row['doc']) | {'revision': row['revision']}

    def runs(self, sid, limit=20):
        rows = self.db.execute('SELECT id FROM work_runs WHERE session_id=? ORDER BY updated DESC LIMIT ?',
                               (sid, int(limit))).fetchall()
        return [self.get(row['id']) for row in rows]

    def active(self, sid):
        row = self.db.execute(
            'SELECT id FROM work_runs WHERE session_id=? AND status NOT IN (%s) ORDER BY updated DESC LIMIT 1'
            % ','.join('?' * len(TERMINAL_STATUSES)), (sid, *TERMINAL_STATUSES)).fetchone()
        return self.get(row['id']) if row else None

    def resolve(self, sid, run_id=None):
        if run_id:
            run = self.get(run_id)
            if run['sessionId'] != sid:
                raise ValueError('WORK_RUN_UNKNOWN: that run belongs to another session')
            return run
        run = self.active(sid)
        if run is None:
            raise ValueError('WORK_RUN_REQUIRED: no active Work Graph run — call work_graph action=create first')
        return run

    def save(self, run, event=None, detail=None):
        run['updatedAt'] = now()
        if event:
            run.setdefault('history', []).append({'at': run['updatedAt'], 'event': event,
                                                  **({'detail': str(detail)[:400]} if detail else {})})
            run['history'] = run['history'][-HISTORY_MAX:]
        revision = int(run.get('revision') or 0) + 1
        run['revision'] = revision
        doc = {key: value for key, value in run.items() if key != 'revision'}
        with self.db:
            self.db.execute(
                'INSERT INTO work_runs(id, session_id, status, revision, doc, created, updated) '
                'VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status, '
                'revision=excluded.revision, doc=excluded.doc, updated=excluded.updated',
                (run['runId'], run['sessionId'], run['status'], revision, json.dumps(doc, ensure_ascii=False),
                 run.get('createdAt') or run['updatedAt'], run['updatedAt']))
            self.handoffs.enqueue(run)
        self.emit(run)
        if hasattr(self, 'continuations'):
            self.handoffs.dispatch(run['runId'])
        return run

    def emit(self, run):
        try:
            self.store.emit(run['sessionId'], 'work_graph', self.view(run))
        except Exception:  # pragma: no cover - an event must never break the engine
            pass

    def view(self, run):
        """Bounded snapshot for events, the API and the UI (outputs cut to a preview)."""
        nodes = []
        for node in run['nodes']:
            stages = {}
            for name, state in node['stages'].items():
                stages[name] = {key: state.get(key) for key in ('status', 'attempts', 'outputChars', 'error',
                                                                 'startedAt', 'finishedAt')}
                stages[name]['artifact'] = state.get('artifact')
                stages[name]['checkpoint'] = state.get('checkpoint')
                stages[name]['policy'] = state.get('policy')
                stages[name]['preview'] = bounded(state.get('output'), 1200)
                stages[name]['caveats'] = bounded(state.get('caveats'), 900) if state.get('caveats') else None
                stages[name]['rounds'] = [{key: item.get(key) for key in (
                    'attempt', 'producerId', 'reviewerId', 'verdict', 'error', 'at', 'reviewerRole',
                    'producerRole', 'execution')} | {'findings': bounded(item.get('findings'), 900),
                                        'knowledge': [{'role': k.get('role'), 'question': k.get('question'),
                                                       'childId': k.get('childId'), 'status': k.get('status'),
                                                       'artifact': k.get('artifact'), 'execution': k.get('execution')}
                                                      for k in item.get('knowledge') or []]}
                    for item in state.get('rounds') or []]
            nodes.append({key: node[key] for key in ('id', 'kind', 'title', 'goal', 'dependsOn', 'acceptance',
                                                     'tests', 'files')} | {'stages': stages})
        return {'runId': run['runId'], 'sessionId': run['sessionId'], 'title': run.get('title'),
                'goal': run['goal'], 'flow': run['flow'], 'status': run['status'], 'revision': run['revision'],
                'autopilot': bool(run.get('autopilot')), 'createdAt': run.get('createdAt'),
                'updatedAt': run.get('updatedAt'), 'nodes': nodes, 'waves': execution_waves(run['nodes']),
                'issues': graph_issues(run['nodes']),
                'review': {'status': (run.get('review') or {}).get('status'),
                           'rounds': [{key: item.get(key) for key in ('childId', 'verdict', 'at', 'error')}
                                      | {'findings': bounded(item.get('findings'), 1500)}
                                      for item in (run.get('review') or {}).get('rounds', [])]},
                'verificationVersion': run.get('verificationVersion', 'legacy'),
                'checks': self.checks.records(run['runId']),
                'requests': self.feedback.records(run['runId']),
                'grants': self.grants.records(run['runId']),
                'handoffs': self.handoffs.records(run['runId']),
                'handoffActions': [json.loads(r['doc']) | {'status': r['status']} for r in self.handoffs.actions(run['runId'])],
                'mainDecisions': self.decisions.records(run['runId']),
                'documents': run.get('documents') or [], 'approval': run.get('approval'),
                'interviews': [{key: item.get(key) for key in ('decisionId', 'status', 'answers', 'at')}
                               for item in run.get('interviews') or []],
                'ship': run.get('ship'), 'history': (run.get('history') or [])[-30:]}

    # ---- graph editing ----------------------------------------------------------------------- #

    def create(self, session, args):
        sid = session['id']
        goal = str(args.get('goal') or '').strip()
        intent = (session.get('config') or {}).get(INTENT_CONFIG_KEY) or {}
        if not goal:
            goal = str(intent.get('text') or '').strip()
        if len(goal) < 5:
            raise ValueError('WORK_GOAL_REQUIRED: pass `goal` — the owner request in their own words')
        flow = str(args.get('flow') or intent.get('flow') or 'mixed').strip().lower()
        if flow not in FLOWS:
            raise ValueError(f'WORK_FLOW_INVALID: flow must be one of {list(FLOWS)}')
        current = self.active(sid)
        if current is not None and self.busy(current):
            raise ValueError('WORK_RUN_BUSY: wait for the active run/check before creating another run')
        if current is not None and current['status'] != 'executed':
            current['status'] = 'cancelled'
            self.save(current, 'superseded', 'a new run was created')
        run = {'runId': 'w-' + uuid.uuid4().hex[:10], 'sessionId': sid, 'goal': goal[:4000],
               'title': str(args.get('title') or goal).strip()[:120], 'flow': flow, 'status': 'drafting',
               'slug': slugify(args.get('title') or goal), 'autopilot': autopilot_on(session),
               'createdAt': now(), 'nodes': [], 'review': {'status': None, 'rounds': []}, 'documents': [],
               'approval': None, 'interviews': [], 'ship': None, 'history': [], 'revision': 0,
               'originTurn': self.rt.active_turn.get(sid),
               'intent': intent or None, 'verificationVersion': work_policy.VERSION,
               'executionRequested': flow in ('fix', 'mixed') and intent.get('command') not in SLASH_FLOWS}
        run['artifactNamespace'] = self.artifacts.new_namespace(run)
        run['executionRequested'] = self.execution_requested(session, run)
        if args.get('nodes'):
            self.apply_nodes(run, args['nodes'], replace=False)
        self.clear_intent(session)
        return self.save(run, 'created', f'flow={flow}')

    def execution_requested(self, session, run):
        if run['flow'] not in ('fix', 'mixed') or (run.get('intent') or {}).get('command') in SLASH_FLOWS:
            return False
        owner_text = next((m.get('content') for m in reversed(session.get('messages', [])) if m.get('role') == 'user' and isinstance(m.get('content'), str)), run['goal'])
        folded = unicodedata.normalize('NFKD', owner_text.replace('đ','d')).encode('ascii','ignore').decode().lower()
        artifact_request = re.search(r'\b(plan|research|design|ke hoach|nghien cuu|thiet ke)\b', folded)
        explicit_execute = re.search(r'^\s*(?:(?:ok|please|help me|giup toi|hay)[,. ]*)?(?:implement|build|fix|ship|thuc hien|code|sua|trien khai)\b', folded)
        return not artifact_request or bool(explicit_execute)

    def clear_intent(self, session):
        config = session.get('config') or {}
        if config.pop(INTENT_CONFIG_KEY, None) is not None:
            self.store.update_config(session['id'], config)

    def apply_nodes(self, run, raw_nodes, replace):
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError('WORK_NODE_INVALID: `nodes` must be a non-empty list')
        by_id = {node['id']: node for node in run['nodes']}
        changed_any = not replace
        for raw in raw_nodes:
            node_id = str((raw or {}).get('id') or '').strip() if isinstance(raw, dict) else ''
            existing = by_id.get(node_id)
            if existing is not None and not replace:
                raise ValueError(f'WORK_NODE_EXISTS: node {node_id} already exists — use action=update')
            if existing is None and replace:
                raise ValueError(f'WORK_NODE_UNKNOWN: node {node_id} does not exist — use action=add')
            node = normalize_node(raw, existing)
            if existing is not None:
                changed = work_policy.definition(existing) != work_policy.definition(node)
                if changed:
                    changed_any = True
                    for name, state in node['stages'].items():
                        if state['status'] not in IN_FLIGHT_STAGE:
                            for record in self.checks.records(run['runId']):
                                if record.get('artifactId') == state.get('artifact', {}).get('artifactId'):
                                    record.update(previousStatus=record['status'], status='superseded')
                                    self.checks.save(record)
                            node['stages'][name] = new_stage() | {'feedback': 'Node definition changed by main.',
                                                                 'rounds': state.get('rounds', [])}
                            # A title/file edit must not erase a conflict in an
                            # unchanged acceptance requirement (nor may reordering it).
                            conflicts = [item | {'id': f'A{node["acceptance"].index(item["requirement"]) + 1}'}
                                         for item in state.get('inputConflicts', [])
                                         if item['requirement'] in node['acceptance']]
                            if conflicts:
                                node['stages'][name]['inputConflicts'] = conflicts
            by_id[node_id] = node
        nodes = list(by_id.values())
        if len(nodes) > MAX_NODES:
            raise ValueError(f'WORK_GRAPH_TOO_LARGE: at most {MAX_NODES} nodes; merge related work')
        check_graph(nodes)
        run['nodes'] = nodes
        self.refresh(run)
        if changed_any:
            # A changed graph earns fresh whole-plan reviews; the old rounds judged another plan.
            if run.get('review', {}).get('rounds'):
                run.setdefault('reviewHistory', []).append(run['review'])
            run['review'] = {'status': None, 'rounds': []}
        if run['status'] in ('verified', 'awaiting_approval', 'approved', 'execute_failed') and changed_any:
            run['status'] = 'drafting'
            run['approval'] = None

    def graph(self, session, args):
        action = str(args.get('action') or 'status').strip().lower()
        if action in ('assign_handoff', 'revoke_handoff'):
            return self.handoffs.action(session, args)
        if action in ('grant','revoke'):
            return self.grants.action(session,args)
        if action == 'create':
            run = self.create(session, args)
            return self.result(run, 'Work Graph run created. Add nodes, then call work_run phase=discover.')
        run = self.resolve(session['id'], args.get('runId'))
        if action == 'status':
            return self.result(run)
        if run['status'] in TERMINAL_STATUSES:
            raise ValueError(f'WORK_RUN_CLOSED: run {run["runId"]} is {run["status"]}; create a new run')
        if action in ('add', 'update', 'remove', 'retry', 'cancel') and self.busy(run):
            raise ValueError('WORK_RUN_BUSY: work_run is running for this run; wait for it to return')
        if action in ('add', 'update'):
            self.apply_nodes(run, args.get('nodes'), replace=action == 'update')
            return self.result(self.save(run, action, ','.join(str((n or {}).get('id')) for n in args['nodes']
                                                                if isinstance(n, dict))))
        if action == 'remove':
            ids = set(clean_list(args.get('nodeIds'), 'nodeIds', 24, 32))
            if not ids:
                raise ValueError('WORK_NODE_INVALID: pass `nodeIds` to remove')
            users = [node['id'] for node in run['nodes'] if node['id'] not in ids and set(node['dependsOn']) & ids]
            if users:
                raise ValueError('WORK_GRAPH_INVALID: nodes ' + ', '.join(users) + ' still depend on the removed '
                                 'nodes; update their dependsOn first')
            run['nodes'] = [node for node in run['nodes'] if node['id'] not in ids]
            self.refresh(run)
            return self.result(self.save(run, 'remove', ','.join(sorted(ids))))
        if action == 'retry':
            return self.result(self.retry(run, set(clean_list(args.get('nodeIds'), 'nodeIds', 24, 32))))
        if action == 'validate':
            return self.result(run) | {'valid': not graph_issues(run['nodes'])}
        if action == 'cancel':
            run['status'] = 'cancelled'
            return self.result(self.save(run, 'cancelled'))
        raise ValueError(f'WORK_ACTION_INVALID: action {action!r} is not supported here')

    def retry(self, run, ids):
        """Re-open rejected/failed stages (all, or `ids`) with their last findings as feedback."""
        reset = []
        for node in run['nodes']:
            if ids and node['id'] not in ids:
                continue
            for name, state in node['stages'].items():
                if state['status'] in ('rejected', 'failed'):
                    feedback = state.get('feedback') or state.get('error') or ''
                    node['stages'][name] = new_stage() | {'feedback': ('Retry after: ' + feedback)[:FINDINGS_MAX_CHARS],
                                                          'feedbackSource': state.get('feedbackSource') if state.get('feedback') else 'execution',
                                                          'rounds': state.get('rounds') or []}
                    reset.append(f'{node["id"]}:{name}')
        if not reset:
            raise ValueError('WORK_NOTHING_TO_RETRY: no rejected or failed stage'
                             + (' among ' + ', '.join(sorted(ids)) if ids else ''))
        if run['status'] == 'execute_failed':
            run['status'] = 'approved'
        elif run['status'] == 'needs_revision':
            run['status'] = 'discovering'
        return self.save(run, 'retry', ','.join(reset))

    def refresh(self, run):
        """Invalidate consumed snapshots transitively without deleting historical checks."""
        changed = True
        while changed:
            changed = False
            for node in run['nodes']:
                for stage, state in node['stages'].items():
                    if state.get('artifact') and state['status'] in ('accepted', 'needs_checks', 'revise'):
                        binding = self.checks.binding(run, node, stage)
                        if any(state['artifact']['binding'].get(k) != v for k, v in binding.items()):
                            node['stages'][stage] = new_stage() | {'rounds': state['rounds'], 'feedback': 'Consumed snapshot changed.'}
                            for record in self.checks.records(run['runId']):
                                if record.get('artifactId') == state['artifact']['artifactId']:
                                    record.update(previousStatus=record['status'], status='superseded')
                                    self.checks.save(record)
                            changed = True
                        elif (state['status'] == 'accepted' and state.get('policy', {}).get('required')
                              and not self.checks.valid(run, node, stage)):
                            # Keep the immutable output and historical verdict, but
                            # don't let stage_done release dependents on an old gate.
                            state.update(status='needs_checks', error='WORK_CHECKS_STALE: '
                                         'historical checks do not satisfy the current input contract')
        review = run.get('review') or {}
        if review.get('binding') and review['binding'] != self.whole_binding(run):
            run.setdefault('reviewHistory', []).append(review)
            run['review'] = {'status': None, 'rounds': []}
            run['approval'] = None
            if run['status'] in ('verified', 'awaiting_approval', 'approved', 'executing', 'executed', 'execute_failed'):
                run['status'] = 'drafting'
        return run

    def result(self, run, message=None):
        view = self.view(run)
        summary = [{'id': node['id'], 'kind': node['kind'], 'title': node['title'], 'dependsOn': node['dependsOn'],
                    'stages': {name: state['status'] for name, state in node['stages'].items()},
                    'artifacts': {name: run['nodes'][i]['stages'][name].get('artifact') for name in node['stages']},
                    'policies': {name: run['nodes'][i]['stages'][name].get('policy') for name in node['stages']}}
                   for i, node in enumerate(view['nodes'])]
        out = {'runId': run['runId'], 'status': run['status'], 'flow': run['flow'], 'revision': run['revision'],
               'autopilot': view['autopilot'], 'nodes': summary, 'waves': view['waves'], 'issues': view['issues'],
               'documents': view['documents'], 'handoffs': view['handoffs'],
               'handoffActions': view['handoffActions'], 'next': self.next_step(run)}
        if message:
            out['message'] = message
        return out

    def next_step(self, run):
        waiting = [r for r in self.feedback.records(run['runId']) if r['status'] in ('waiting_main', 'needs_user', 'ready', 'interrupted')]
        if waiting:
            return ('Read work_report action=status. Open needs_user requests with interview(workRequestId,revision), '
                    'or supply newly opened evidenceRefs for needs_evidence/checkpoint. Once ready, work_run/work_check '
                    'continues the same child with fresh budget for new input; preserve its investigation and failure history.')
        """One sentence telling main what the harness expects next (keeps weak models on the path)."""
        status = run['status']
        conflicts = [(n['id'], stage, s['inputConflicts']) for n in run['nodes']
                     for stage, s in n['stages'].items() if s.get('inputConflicts')]
        if conflicts:
            return ('Main: correct the conflicting node goal/acceptance with work_graph action=update before '
                    'retrying checks or production. Preserve facts in the artifact; the assignment needs correction: '
                    + str(conflicts))
        needs = [(n['id'], stage, s['artifact']['artifactId']) for n in run['nodes'] for stage, s in n['stages'].items() if s['status'] == 'needs_checks' and s.get('artifact')]
        if needs:
            return 'Main: inspect draft refs, then call work_check action=start with nodeId, stage, current artifactId, checkIds and unique invocationId: ' + str(needs)
        if not run['nodes']:
            return 'Add nodes with work_graph action=add (explore first, then research/design when needed, then plan sub-plans).'
        blocked = set(blocked_nodes(run, 'produce'))
        pending_discovery = [node['id'] for node in run['nodes'] if node['stages'].get('produce', {}).get('status')
                             in ('pending', 'revise') and node['id'] not in blocked]
        if pending_discovery and status not in ('approved', 'executing'):
            return f'Call work_run phase=discover (pending: {", ".join(pending_discovery)}).'
        if status in ('drafting', 'discovering', 'needs_revision'):
            bad = [node['id'] for node in run['nodes'] if node['stages'].get('produce', {}).get('status')
                   in ('rejected', 'failed')]
            if bad or blocked:
                return (f'Nodes {", ".join(bad + sorted(blocked))} were not accepted or are blocked; update their goal/acceptance with work_graph '
                        'action=update (it resets them) or remove them, then work_run again.')
            if any(node['kind'] == PLAN_KIND for node in run['nodes']) or run['flow'] in ('research', 'design'):
                return 'Call work_graph action=verify to review the whole plan and write the documents.'
            return 'Call work_graph action=submit to ask the owner to approve execution.'
        if status == 'verified':
            has_exec = any('execute' in node['stages'] for node in run['nodes'])
            if has_exec and run.get('executionRequested'):
                return 'Call work_graph action=submit so the owner approves execution (Autopilot approves itself).'
            return ('Answer the owner with the document paths and a short summary of the checked artifacts. '
                    'The review covers those snapshots only; do not add new technical claims or imply '
                    'that proposed tests were executed. New consequential conclusions need a revised artifact and check.')
        if status == 'awaiting_approval':
            return 'Wait for the owner decision.'
        if status == 'execute_failed':
            bad = [node['id'] for node in run['nodes'] if node['stages'].get('execute', {}).get('status')
                   in ('rejected', 'failed')]
            return (f'Execution nodes {", ".join(bad) or "?"} were not accepted (read lastFindings). Call '
                    'work_graph action=retry nodeIds=[...] to run them again with the findings, or '
                    'action=update to change the plan (then verify and approval again), or report to the owner.')
        if status in ('approved', 'executing'):
            return 'Call work_run phase=execute.'
        if status == 'executed':
            return 'Call work_ship to create the branch, commit and PR description, then report.'
        return 'Report the result to the owner.'

    # ---- child plumbing ---------------------------------------------------------------------- #

    def child_answer(self, child_id):
        """The child's LAST final answer (not bounded by the 500-event window of `store.events`)."""
        if not child_id:
            return ''
        try:
            admission = (self.store.get(child_id)['config'].get('workBinding') or {}).get('admissionSeq', 0)
        except KeyError:
            return ''
        rows = self.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='assistant' AND seq>? "
                               'ORDER BY seq DESC LIMIT 50', (child_id, admission)).fetchall()
        for row in rows:
            try:
                data = json.loads(row['payload'])
            except (TypeError, ValueError):
                continue
            if data.get('final'):
                return data.get('text') or ''
        return ''

    async def spawn(self, session, run, node, stage, purpose, role, goal, context, expect, attempt, extra_binding=None):
        """One child through the normal `delegate` path (events, slots, budgets, UI) + full answer."""
        budget = self.child_budget.get(run['runId'])
        if budget is not None:
            if budget[0] <= 0:
                raise WorkBudgetExhausted('WORK_CHILD_BUDGET: this work_run call already started '
                                          f'{WORK_CHILDREN_PER_RUN_CALL} children; call work_run again')
            budget[0] -= 1
        work = {'runId': run['runId'], 'nodeId': node['id'] if node else None, 'stage': stage,
                'purpose': purpose, 'attempt': attempt}
        if node:
            work['taskKind'] = node.get('taskKind')
        refs = []
        if node:
            refs = [n['stages'].get(gate_stage(node, n, stage) or 'produce', {}).get('artifact', {}).get('artifactId') for n in run['nodes'] if n['id'] in node['dependsOn']]
            if stage == 'execute' and node['kind'] == PLAN_KIND:
                refs.append(node['stages']['produce'].get('artifact', {}).get('artifactId'))
        work['artifactIds'] = [ref for ref in refs if ref]
        work.update(extra_binding or {})
        if node and purpose == 'produce' and node['kind'] == 'debug':
            work['diagnosticOnly'] = node.get('taskKind', 'diagnostic') == 'diagnostic'
        args = {'role': role, 'goal': goal, 'context': bounded(context, 16000), 'expect': expect}
        lang = work_prompts.language(run['goal'])
        rights = [g for g in self.grants.records(run['runId']) if self.grants.valid(g,run,work)]
        if rights:
            args['context'] += '\n' + work_prompts.choose(lang,
                'Interview rights assigned by main (only intent decisions; technical facts need evidence first):',
                'Quyền phỏng vấn do phiên chính giao (chỉ hỏi ý định người dùng; dữ kiện kỹ thuật cần kiểm chứng trước):') + '\n' + json.dumps(
                [{k:g[k] for k in ('grantId','decisionKeys','publishInterview','resumeOnAnswers')} for g in rights],ensure_ascii=False)
            args['context'] += '\n' + work_prompts.choose(lang,
                'When blocked use work_report needs_user with 1..3 questions and matching decisionKeys. Do not ask outside these keys.',
                'Khi thiếu quyết định trong phạm vi, dùng work_report needs_user với 1–3 câu và decisionKeys tương ứng. Không hỏi ngoài các nhóm đã giao.')
        request = self.feedback.ready(work)
        resume_id = request['childId'] if request else work.pop('resumeChildId', None)
        waited = time.monotonic()
        while True:
            try:
                if resume_id:
                    prompt = goal + '\n' + args['context']
                    if request:
                        prompt += '\n' + work_prompts.choose(lang,
                            'Read work_report(action="read", requestId=...) for saved answers/context; read checkpoint artifact by ref. Do not treat proposals as confirmed:',
                            'Đọc work_report(action="read", requestId=...) để lấy câu trả lời/ngữ cảnh đã lưu; đọc artifact checkpoint bằng ref. Không gán đề xuất thành quyết định đã xác nhận:') + '\n' + json.dumps(
                            {k: request.get(k) for k in ('requestId', 'artifact', 'revision')}, ensure_ascii=False)
                        work['artifactIds'] = list(dict.fromkeys(work.get('artifactIds', []) + [request['artifact']['artifactId']]))
                    result = await work_feedback.resume_child(self.rt, session, resume_id, prompt, work, request)
                else:
                    result = await self.rt.delegate(session, dict(args), work=work)
                break
            except ValueError as exc:
                # Parallel nodes and their knowledge requests share the fan-out slots: queue, do not fail.
                if not str(exc).startswith('FANOUT_BUSY') or time.monotonic() - waited > FANOUT_RETRY_SECONDS:
                    raise
                await asyncio.sleep(FANOUT_RETRY_PAUSE)
        answer = self.child_answer(result.get('sessionId')) or str(result.get('summary') or '')
        return result, answer

    # ---- node execution with the review loop ------------------------------------------------- #

    def dependency_context(self, run, node, stage):
        refs = []
        for dep_id in node['dependsOn']:
            dep = next(n for n in run['nodes'] if n['id'] == dep_id)
            chosen = gate_stage(node, dep, stage) or 'produce'
            meta = dep['stages'].get(chosen, {}).get('artifact')
            if meta:
                refs.append({k: meta[k] for k in ('artifactId', 'nodeId', 'stage', 'version', 'contentHash', 'path', 'chars', 'status')})
        if stage == 'execute' and node['kind'] == PLAN_KIND:
            meta = node['stages']['produce'].get('artifact')
            if meta:
                refs.insert(0, {k: meta[k] for k in ('artifactId', 'nodeId', 'stage', 'version', 'contentHash', 'path', 'chars', 'status')})
        return json.dumps({'runId': run['runId'], 'acceptedDependencySnapshots': refs}, ensure_ascii=False)

    def interview_context(self, run):
        lines = []
        for item in run.get('interviews') or []:
            for answer in item.get('answers') or []:
                lines.append(f'- {answer.get("question")}: {answer.get("answer")}')
        heading = work_prompts.choose(work_prompts.language(run['goal']), 'Owner decisions from the interview:',
                                     'Quyết định của người dùng qua phỏng vấn:')
        return (heading + '\n' + '\n'.join(lines)) if lines else ''

    def producer_goal(self, run, node, stage, feedback, knowledge):
        lang = work_prompts.language(run['goal'])
        pick = lambda en, vi: work_prompts.choose(lang, en, vi)
        role = node['kind'] if stage == 'produce' else EXECUTE_ROLE[node['kind']]
        lines = [pick(f'Work Graph run "{run["title"]}" — node {node["id"]} ({node["kind"]}, {stage}).',
                      f'Work Graph "{run["title"]}" — nút {node["id"]} ({node["kind"]}, {stage}).'),
                 pick('Overall owner goal: ', 'Mục tiêu của người dùng: ') + run['goal'], '',
                 pick('Your assignment: ', 'Nhiệm vụ của bạn: ') + node['goal']]
        if node['acceptance']:
            lines += ['', pick('Acceptance (the reviewer checks each item):', 'Nghiệm thu (reviewer kiểm từng mục):')] + [f'- {item}' for item in node['acceptance']]
        if node['tests']:
            lines += ['', pick('Required tests (planned checks in produce; actual results in execute):',
                               'Kiểm thử bắt buộc (dự kiến khi produce; kết quả thực khi execute):')] + [f'- {item}' for item in node['tests']]
        if node['files']:
            lines += ['', pick('Expected touch list: ', 'Vị trí dự kiến tác động: ') + ', '.join(node['files'])]
        if node['dependsOn']:
            lines += ['', pick('Depends on: ', 'Phụ thuộc: ') + ', '.join(node['dependsOn'])]
        if stage == 'execute' and role == 'build':
            lines += ['', pick('Implement the sub-plan completely, write the tests it names, run them, and report the real output. Do not start other sub-plans.',
                               'Thực hiện đầy đủ sub-plan, viết test được nêu, chạy và báo output thực. Không làm sub-plan khác.')]
        if feedback:
            reviewed = node['stages'][stage].get('feedbackSource') == 'checks'
            lines += ['', pick('The previous attempt was REJECTED by the reviewer. Fix every blocking finding:'
                               if reviewed else 'Context for the next draft (changed assignment, dependency or execution issue):',
                               'Lượt trước bị reviewer yêu cầu sửa. Xử lý từng vấn đề chặn:'
                               if reviewed else 'Ngữ cảnh cho bản tiếp theo (đổi nhiệm vụ, dependency hoặc lỗi thực thi):'), feedback]
        if knowledge:
            lines += ['', pick('Lookup artifacts for your knowledge requests. Read assigned refs; opened evidence is not a semantic approval:',
                               'Artifact trả lời yêu cầu tra cứu. Đọc ref được giao; có bằng chứng đã mở không đồng nghĩa nội dung đã được nghiệm thu:')]
            for item in knowledge:
                lines.append(json.dumps({k:item.get(k) for k in ('role', 'question', 'status', 'error')}, ensure_ascii=False))
            lines.append(json.dumps({'snapshots': [{k:item['artifact'][k] for k in ('artifactId', 'version', 'contentHash', 'path', 'chars')}
                for item in knowledge if item.get('artifact', {}).get('status') == 'finalized']}, ensure_ascii=False))
        if stage == 'produce' and node['kind'] == PLAN_KIND:
            siblings = [f'{item["id"]}: {item["title"]}' for item in run['nodes']
                        if item['kind'] == PLAN_KIND and item['id'] != node['id']]
            if siblings:
                lines += ['', pick('Sibling sub-plans (do not duplicate their scope): ', 'Sub-plan cùng cấp (không trùng phạm vi): ') + '; '.join(siblings)]
        return role, '\n'.join(lines)

    def reviewer_goal(self, run, node, stage, output, budget_steps=None):
        lang = work_prompts.language(run['goal'])
        pick = lambda en, vi: work_prompts.choose(lang, en, vi)
        kind = node['kind'] if stage == 'produce' else ('build' if node['kind'] == PLAN_KIND else node['kind'])
        lines = [pick(f'Independent review of Work Graph node {node["id"]} ({node["kind"]}, {stage}) in run "{run["title"]}".',
                      f'Phản biện độc lập nút Work Graph {node["id"]} ({node["kind"]}, {stage}) trong "{run["title"]}".'),
                 pick('Owner goal: ', 'Mục tiêu của người dùng: ') + run['goal'],
                 pick('Node assignment: ', 'Nhiệm vụ của nút: ') + node['goal']]
        if node['acceptance']:
            lines += [pick('Acceptance to check one by one:', 'Nghiệm thu cần kiểm từng mục:')] + [f'- {item}' for item in node['acceptance']]
        if node['tests']:
            lines += [pick('Required tests:', 'Kiểm thử bắt buộc:')] + [f'- {item}' for item in node['tests']]
        budget_steps = REVIEW_MAX_STEPS if budget_steps is None else budget_steps
        lines += ['', pick(f'Budget: {budget_steps} model steps; batch tools and reserve steps to write the review.',
                           f'Ngân sách: {budget_steps} vòng model; gom tool và dành bước cuối viết phản biện.'),
                  '', pick('Rubric: ', 'Tiêu chí phản biện: ') + work_prompts.rubric(kind, lang),
                  '', pick('The output to review is in the context below.', 'Đầu ra cần phản biện nằm trong ngữ cảnh bên dưới.'),
                  '', work_prompts.review_tail(lang)]
        heading = pick(f'Output of {node["id"]} to review', f'Đầu ra {node["id"]} cần phản biện')
        return '\n'.join(lines), f'### {heading}\n{bounded(output, 14000)}'

    async def answer_knowledge(self, session, run, node, stage, requests, attempt, controller_action=None):
        async def one(item):
            lang = work_prompts.language(run['goal'])
            goal = work_prompts.choose(lang,
                    f'Knowledge request from Work Graph node {node["id"]} ({node["kind"]}) in run "{run["title"]}". Answer precisely with evidence (path:line or URL + quote): ',
                    f'Yêu cầu tra cứu từ nút Work Graph {node["id"]} ({node["kind"]}) trong "{run["title"]}". Trả lời đúng câu hỏi với bằng chứng (path:line hoặc URL + trích ngắn): ') + item['question']
            result = None
            try:
                result, answer = await self.spawn(session, run, node, stage, 'knowledge', item['role'], goal,
                    work_prompts.choose(lang, 'Owner goal: ', 'Mục tiêu của người dùng: ') + run['goal'], None, attempt,
                    extra_binding={'controllerAction': controller_action, 'helperRole': item['role']} if controller_action else None)
                reads = work_checks.good_reads(self, result.get('sessionId'))
                evidenced = work_checks.complete(result) and bool(answer.strip()) and bool(reads)
                proofs = [work_feedback.evidence_signature(read) or {'kind': read['name'],
                    'ref': 'search:' + work_policy.digest(read.get('args', {})),
                    'contentHash': work_policy.digest(read['result']), 'args': read.get('args', {})} for read in reads]
                binding = self.checks.binding(run, node, stage) | {'purpose': 'knowledge', 'lookupRole': item['role'],
                    'question': item['question'], 'observedEvidence': proofs, 'verification': 'unreviewed',
                    'execution': work_budget.receipt(result)}
                meta = await self.artifacts.put(run, node['id'], 'knowledge', answer, binding,
                                                evidenced, result.get('sessionId'))
                return item | {'childId': result.get('sessionId'), 'status': result.get('status') if evidenced else 'unverified',
                    'artifact': meta, 'execution': work_budget.receipt(result),
                    'error': None if evidenced else 'UNVERIFIED: incomplete lookup or no opened original evidence; do not rely on it'}
            except Exception as exc:
                return item | {'childId': (result or {}).get('sessionId'), 'status': 'failed',
                    'execution': work_budget.receipt(result or {}), 'error': f'UNAVAILABLE: {exc}'[:500]}
        from . import work_budget
        if controller_action:
            tasks = [self.continuations.helper_task(session['id'], controller_action, item['role'],
                                                    lambda item=item: one(item)) for item in requests]
        else:
            tasks = [asyncio.create_task(one(item)) for item in requests]
        try:
            return list(await asyncio.gather(*tasks))
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run_stage(self, session, run, node, stage, max_rounds, controller_owned=False, controller_action=None):
        """Produce ONE draft; main dispatches checks and chooses the repair/routing step."""
        from . import work_budget
        state = node['stages'][stage]
        continuing = state.get('requestId') and self.feedback.get(state['requestId'])['status'] == 'ready'
        state.update(status='running', error=None, maxRounds=max_rounds)
        state['startedAt'] = state['startedAt'] or now()
        if state['attempts'] >= max_rounds and not continuing:
            state.update(status='rejected', error='WORK_REPAIR_EXHAUSTED: checkpoint; change scope before another attempt.')
            self.save(run, 'node_rejected', node['id'])
            return state['status']
        if not continuing:
            state['attempts'] += 1
        # A failed replacement must not leave an older rejected artifact as the current draft.
        state.pop('artifact', None)
        state.pop('policy', None)
        state.pop('checkpoint', None)
        attempt = state['attempts']
        entry = {'attempt': attempt, 'producerRole': node['kind'], 'at': now(), 'knowledge': []}
        state['rounds'].append(entry)
        self.save(run, 'node_started', f'{node["id"]}:{stage}')
        try:
            before = await work_checks.snapshot(self, run['sessionId']) if stage == 'execute' else None
            role, goal = self.producer_goal(run, node, stage, state.get('feedback'), [])
            context = '\n\n'.join(p for p in (self.interview_context(run), self.dependency_context(run, node, stage)) if p)
            expect = work_prompts.deliverable(node['kind'] if stage == 'produce' else role, work_prompts.language(run['goal']))
            produced, output = await self.spawn(session, run, node, stage, 'produce', role, goal, context, expect, attempt,
                extra_binding={'controllerAction': controller_action} if controller_action else
                              {'controllerOwned': True} if controller_owned else None)
            entry['producerId'] = produced.get('sessionId')
            if produced.get('request'):
                request = produced['request']
                state.update(status='needs_user', requestId=request['requestId'], checkpoint=request,
                             error=None, outputChars=request['artifact']['chars'])
                entry['execution'] = work_budget.receipt(produced)
                self.save(run, 'node_needs_user', node['id'])
                return state['status']
            requests = parse_knowledge_requests(output) if work_checks.complete(produced) else []
            if requests:
                entry['initialProducerId'] = produced.get('sessionId')
                checkpoint = await self.artifacts.put(run, node['id'], stage, output,
                    self.checks.binding(run, node, stage) | {'checkpoint': True}, False, entry['initialProducerId'])
                state['checkpoint'] = {'childId': entry['initialProducerId'], 'artifact': checkpoint,
                                       'remaining': 'Lookup requested; partial is not accepted.'}
                self.save(run, 'node_lookup_requested', node['id'])
                answers = await self.answer_knowledge(session, run, node, stage, requests, attempt, controller_action)
                entry['knowledge'] = answers
                lookup_refs = [a['artifact']['artifactId'] for a in answers if a.get('artifact', {}).get('status') == 'finalized']
                if not lookup_refs:
                    state.update(status='failed', artifact=checkpoint, output=output, outputChars=len(output),
                                 error='WORK_LOOKUP_UNVERIFIED: no fresh evidenced helper output; main must choose another strategy.')
                    self.save(run, 'node_lookup_unverified', node['id'])
                    return state['status']
                role, goal = self.producer_goal(run, node, stage, state.get('feedback'), answers)
                refs = list(dict.fromkeys((produced.get('work') or {}).get('artifactIds', []) + lookup_refs))
                produced, output = await self.spawn(session, run, node, stage, 'produce', role, goal, context, expect, attempt,
                    extra_binding={'resumeChildId': entry['initialProducerId'], 'artifactIds': refs,
                        'inputReadId': 'lookup-' + uuid.uuid4().hex,
                        **({'controllerAction': controller_action} if controller_action else
                           {'controllerOwned': True} if controller_owned else {})})
                entry['producerId'] = produced.get('sessionId')
                entry['lookupContinuation'] = True
                if produced.get('request'):
                    request = produced['request']
                    state.update(status='needs_user', requestId=request['requestId'], checkpoint=request,
                                 error=None, outputChars=request['artifact']['chars'])
                    entry['execution'] = work_budget.receipt(produced)
                    self.save(run, 'node_needs_user', node['id'])
                    return state['status']
            entry['execution'] = work_budget.receipt(produced)
            after = await work_checks.snapshot(self, run['sessionId']) if stage == 'execute' else None
            changed = before is not None and after is not None and before != after
            declared_sensitive = any(re.search(r'api|schema|auth|migration|contract|concurr|lock', path, re.I) for path in node['files'])
            policy = work_policy.derive(run, node, stage, output, changed,
                                       code_risk=stage == 'execute' and bool((after or {}).get('criticalChanges') or declared_sensitive))
            state['policy'] = policy
            binding = self.checks.binding(run, node, stage) | {'policyHash': policy['hash']}
            if entry.get('lookupContinuation'):
                binding['lookupArtifactIds'] = lookup_refs
            if stage == 'execute':
                binding['codeSnapshot'] = after
            finalized = work_checks.complete(produced) and bool(output.strip()) and not parse_knowledge_requests(output)
            meta = await self.artifacts.put(run, node['id'], stage, output, binding, finalized, entry['producerId'])
            state.update(artifact=meta, output=output, outputChars=len(output))
            if not finalized:
                state.update(status='failed', error='WORK_PRODUCER_INCOMPLETE: partial retained; retry/update before checks.')
                state['checkpoint'] = {'childId': entry['producerId'], 'artifactId': meta['artifactId'],
                    'execution': entry['execution'], 'remaining': 'Producer incomplete; draft is not verifiable. '
                    'Inspect reason, owner ceiling and saved draft before retrying; same-child resume is not available yet.'}
            elif entry.get('lookupContinuation') and not all(self.artifacts.covered(
                    (produced.get('work') or {}).get('inputReadId'), self.artifacts.get(run['runId'], aid)[0],
                    entry['producerId']) for aid in lookup_refs):
                state.update(status='failed', error='WORK_LOOKUP_INPUT_UNREAD: producer did not read the new assigned lookup artifacts.')
            elif stage == 'execute' and (before is None or after is None):
                state.update(status='failed', error='WORK_CODE_SNAPSHOT_REQUIRED: could not verify source changes.')
            elif policy['required']:
                state['status'] = 'needs_checks'
            elif node['kind'] == 'testing' and not work_checks.test_proof(self, entry['producerId'], node['tests']):
                state.update(status='failed', error='WORK_TEST_EVIDENCE_REQUIRED: actual successful command events missing.')
            elif not work_checks.good_reads(self, entry['producerId'], retained_checkpoint=bool(continuing and stage == 'produce')):
                state.update(status='failed', error='WORK_EVIDENCE_REQUIRED: lookup/diagnosis needs actual opened evidence.')
            else:
                state.update(status='accepted', feedback='')
        except WorkBudgetExhausted as exc:
            state.update(status='pending', error=str(exc))
            state['attempts'] = max(0, state['attempts'] - 1)
        except asyncio.CancelledError:
            request = self.feedback.get(state['requestId']) if state.get('requestId') else None
            state.update(status='needs_user' if request and request['status'] in ('cancelled', 'interrupted', 'stale') else 'pending',
                         error='interrupted; main must inspect saved request' if request else 'interrupted')
            self.save(run, 'node_interrupted', node['id'])
            raise
        except Exception as exc:
            state.update(status='failed', error=str(exc)[:500])
        state['finishedAt'] = now()
        self.save(run, 'artifact_ready' if state['status'] == 'needs_checks' else 'node_' + state['status'], node['id'])
        return state['status']

    async def run(self, session, args):
        sid = session['id']
        run = self.resolve(sid, args.get('runId'))
        phase = str(args.get('phase') or 'discover').strip().lower()
        if phase not in ('discover', 'execute'):
            raise ValueError('WORK_PHASE_INVALID: phase must be discover or execute')
        stage = 'produce' if phase == 'discover' else 'execute'
        if run['status'] in TERMINAL_STATUSES:
            raise ValueError(f'WORK_RUN_CLOSED: run {run["runId"]} is {run["status"]}')
        check_graph(run['nodes'])
        if run.get('verificationVersion') != work_policy.VERSION:
            run['legacyReview'] = run.get('review')
            run['review'] = {'status': None, 'rounds': []}
            for n in run['nodes']:
                n['stages'] = {k: new_stage() | {'rounds': v.get('rounds', []), 'feedback': 'Legacy review is not current verification.'} for k,v in n['stages'].items()}
            run.update(verificationVersion=work_policy.VERSION, status='drafting', approval=None,
                       executionRequested=self.execution_requested(session, run))
        self.refresh(run)
        for node in run['nodes']:
            for state in node['stages'].values():
                if state.get('requestId') and state['status'] == 'needs_user':
                    request = self.feedback.get(state['requestId'])
                    if request['status'] == 'ready':
                        self.feedback.validate(request)
                        state['status'] = 'pending'
        only = set(clean_list(args.get('nodeIds'), 'nodeIds', 24, 32))
        conflicts = [{'nodeId': n['id'], 'stage': stage, 'findings': n['stages'][stage]['inputConflicts']}
                     for n in run['nodes'] if stage in n['stages'] and (not only or n['id'] in only)
                     and n['stages'][stage].get('inputConflicts')]
        if conflicts:
            return self.result(run) | {'inputConflicts': conflicts}
        if stage == 'execute':
            self.require_execution(run)
            self.require_planning_current(run)
            await self.require_code_current(run)
            if run['status'] == 'execute_failed':
                raise ValueError('WORK_EXECUTE_FAILED: some execution nodes were not accepted; call work_graph '
                                 'action=retry (or update) first')
            if run['status'] not in ('approved', 'executing', 'executed'):
                if autopilot_on(self.store.get(sid)) and run['status'] == 'verified':
                    self.approve_by_autopilot(run)
                else:
                    raise ValueError('WORK_APPROVAL_REQUIRED: execution needs owner approval — call work_graph '
                                     'action=verify then action=submit (Autopilot skips the wait)')
            run['status'] = 'executing'
        elif run['status'] in ('approved', 'executing', 'executed', 'execute_failed'):
            raise ValueError('WORK_PHASE_INVALID: the plan is approved; run phase=execute, or update nodes to re-plan')
        else:
            run['status'] = 'discovering'
        max_rounds = max(1, min(MAX_ROUNDS_CEILING, int(args.get('maxRounds') or MAX_ROUNDS_DEFAULT)))
        lock = self.locks.setdefault(run['runId'], asyncio.Lock())
        if lock.locked():
            raise ValueError('WORK_RUN_BUSY: work_run is already running for this run')
        async with lock:
            self.live[run['runId']] = run
            self.save(run, 'run_started', phase)
            self.child_budget[run['runId']] = [WORK_CHILDREN_PER_RUN_CALL]
            limit = max(1, int(self.rt.fanout_limit(session.get('config'))))
            try:
                with self.budget_paused(sid):
                    return await self.schedule_nodes(session, run, stage, max_rounds, only, limit)
            finally:
                self.child_budget.pop(run['runId'], None)
                self.live.pop(run['runId'], None)

    def require_execution(self, run):
        if not run.get('executionRequested'):
            raise ValueError('WORK_REQUIREMENTS_ONLY: owner requested an artifact, not code execution; Autopilot cannot expand scope.')

    def require_planning_current(self, run):
        producers = [n for n in run['nodes'] if 'produce' in n['stages']]
        if producers and (any(n['stages']['produce']['status'] != 'accepted'
                              or not self.checks.valid(run, n, 'produce') for n in producers)
                          or (run.get('review') or {}).get('binding') != self.whole_binding(run)
                          or (run.get('review') or {}).get('status') != 'ok'):
            raise ValueError('WORK_NOT_VERIFIED: owner decisions, artifacts or graph checks are stale/missing')

    async def require_code_current(self, run):
        current = None
        for node in run['nodes']:
            state = node['stages'].get('execute', {})
            if state.get('status') == 'accepted':
                if current is None:
                    current = await work_checks.snapshot(self, run['sessionId'])
                expected = state.get('artifact', {}).get('binding', {}).get('codeSnapshot')
                if not current or expected != current or not self.checks.valid(run, node, 'execute'):
                    state.update(status='revise', feedback='Integrated source changed: preserve valid changes, inspect current code and produce a fresh handoff for testing.',
                                 error='WORK_CODE_STALE: re-produce/re-test the current integrated snapshot.')
                    run['status'] = 'approved'
                    self.save(run, 'code_checks_stale', node['id'])
                    raise ValueError('WORK_CODE_STALE: code or required checks changed; no execute/ship until rechecked.')

    def approve_by_autopilot(self, run):
        self.require_execution(run)
        run['approval'] = {'status': 'approved', 'by': 'autopilot', 'at': now()}
        run['status'] = 'approved'

    @contextlib.contextmanager
    def budget_paused(self, sid):
        """Pause main's turn deadline while children work (same rule as `wait_for_decision`)."""
        budget = self.rt.run_budget.get(sid)
        paused = budget.when() if budget is not None else None
        started = time.monotonic()
        if paused is not None:
            try:
                budget.reschedule(None)
            except RuntimeError:
                paused = None
        try:
            yield
        finally:
            if paused is not None:
                try:
                    budget.reschedule(paused + (time.monotonic() - started))
                except RuntimeError:
                    pass

    async def schedule_nodes(self, session, run, stage, max_rounds, only, limit):
        started = time.monotonic()
        running = {}
        dispatched = set()
        timed_out = False
        self.continuations.schedulers[run['runId']] = stage
        wake = self.continuations.wakes.setdefault(run['runId'], asyncio.Event())
        try:
            while True:
                wake.clear()
                remaining = WORK_RUN_MAX_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                budget = self.child_budget.get(run['runId'])
                if budget is None or budget[0] > 0:
                    self.continuations.inject(session, run, stage, only, running, limit)
                    dispatched.update(running)
                    for node in ready_nodes(run, stage, only or None):
                        if node['id'] in dispatched or len(running) >= limit:
                            continue
                        dispatched.add(node['id'])
                        running[node['id']] = asyncio.ensure_future(
                            self.run_stage(session, run, node, stage, max_rounds))
                if not running:
                    break
                signal = asyncio.create_task(wake.wait())
                try:
                    done, _ = await asyncio.wait([*running.values(), signal], timeout=remaining,
                                                 return_when=asyncio.FIRST_COMPLETED)
                finally:
                    signal.cancel()
                    await asyncio.gather(signal, return_exceptions=True)
                for node_id in [key for key, task in running.items() if task in done]:
                    task = running.pop(node_id)
                    if task.cancelled():
                        continue
                    if task.exception() is not None:
                        node = next(item for item in run['nodes'] if item['id'] == node_id)
                        node['stages'][stage].update({'status': 'failed', 'error': str(task.exception())[:500]})
        finally:
            self.continuations.schedulers.pop(run['runId'], None)
            for task in running.values():
                task.cancel()
            if running:
                await asyncio.gather(*running.values(), return_exceptions=True)
        blocked = blocked_nodes(run, stage)
        statuses = {node['id']: node['stages'][stage]['status'] for node in run['nodes'] if stage in node['stages']}
        if stage == 'execute':
            if all(value == 'accepted' for value in statuses.values()):
                run['status'] = 'executed'
            elif any(value in ('rejected', 'failed') for value in statuses.values()):
                run['status'] = 'execute_failed'
            else:
                run['status'] = 'approved'  # timed out or out of budget: work_run phase=execute continues
        else:
            run['status'] = 'needs_revision' if any(value in ('rejected', 'failed') for value in statuses.values()) \
                else 'discovering'
        run['autopilot'] = autopilot_on(self.store.get(session['id']))  # the switch may move mid-run
        self.save(run, 'run_finished', json.dumps(statuses)[:300])
        out = self.result(run)
        out['phase'] = 'discover' if stage == 'produce' else 'execute'
        out['timedOut'] = timed_out
        out['blocked'] = blocked
        budget = self.child_budget.get(run['runId'])
        out['budgetExhausted'] = bool(budget is not None and budget[0] <= 0)
        out['outputs'] = [{'id': node['id'], 'kind': node['kind'], 'status': node['stages'][stage]['status'],
                           'attempts': node['stages'][stage]['attempts'],
                           'verdicts': [item.get('verdict') for item in node['stages'][stage]['rounds']],
                           'output': bounded(node['stages'][stage]['output'], 3000),
                           'lastFindings': bounded(node['stages'][stage].get('feedback'), 1200),
                           'acceptedWithCaveats': bool(node['stages'][stage].get('caveats'))}
                          for node in run['nodes'] if stage in node['stages']
                          and (not only or node['id'] in only)]
        for item in out['outputs']:
            state = next(n for n in run['nodes'] if n['id'] == item['id'])['stages'][stage]
            item['artifact'] = state.get('artifact')
            item['policy'] = state.get('policy')
            item['checkpoint'] = state.get('checkpoint')
        return out

    # ---- whole-plan review, documents, approval --------------------------------------------- #

    def master_document(self, run, documents=None):
        # Only freshly confirmed writer results can supply file references. No path is guessed.
        documents = documents or []
        lang = work_prompts.language(run['goal'])
        pick = lambda en, vi: work_prompts.choose(lang, en, vi)
        lines = [f'# {run["title"]}', '', f'> Work Graph `{run["runId"]}` · flow `{run["flow"]}` · '
                 + pick('generated ', 'tạo lúc ') + time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime()), '',
                 pick('## Goal', '## Mục tiêu'), '', run['goal'], '']
        interview = self.interview_context(run)
        if interview:
            lines += [pick('## Owner decisions', '## Quyết định của người dùng'), '', interview.split('\n', 1)[-1], '']
        discovery = [node for node in run['nodes'] if node['kind'] in DISCOVERY_KINDS]
        if discovery:
            lines += [pick('## Discovery (accepted after review)', '## Khảo sát (được chấp nhận sau phản biện)'), '']
            for node in discovery:
                state = node['stages']['produce']
                lines += [f'### {node["id"]} · {node["kind"]} · {node["title"]}', '',
                          pick(f'Status: `{state["status"]}` after {state["attempts"]} round(s).',
                               f'Trạng thái: `{state["status"]}` sau {state["attempts"]} vòng.'), '',
                          'Full snapshot: `' + (state.get('artifact') or {}).get('path', 'legacy') + '`',
                          state.get('output') or '', '']
        plans = [node for node in run['nodes'] if node['kind'] == PLAN_KIND]
        execs = [node for node in run['nodes'] if node['kind'] in EXECUTION_KINDS]
        if plans or execs:
            lines += [pick('## Work DAG', '## Đồ thị công việc'), '', pick('| Node | Kind | Title | Depends on | Tests | Review |',
                         '| Nút | Loại | Tiêu đề | Phụ thuộc | Kiểm thử | Phản biện |'),
                      '|---|---|---|---|---|---|']
            for node in plans + execs:
                state = node['stages'].get('produce') or node['stages'].get('execute')
                verdicts = ' → '.join(item.get('verdict') or '?' for item in state['rounds']) or pick('not run', 'chưa chạy')
                lines.append(f'| {node["id"]} | {node["kind"]} | {node["title"]} | '
                             f'{", ".join(node["dependsOn"]) or "—"} | {len(node["tests"])} | {verdicts} |')
            waves = execution_waves(run['nodes'])
            if waves:
                lines += ['', pick('### Execution waves', '### Thứ tự thực thi'), '']
                lines += [f'{index + 1}. ' + ' ‖ '.join(wave) + (pick(' (parallel)', ' (song song)') if len(wave) > 1 else '')
                          for index, wave in enumerate(waves)]
            lines.append('')
        for node in plans:
            identity = f'work/{run["slug"]}/{self.subplan_name(node)}'
            saved = next((item for item in documents if item.get('identity') == identity), None)
            reference = pick('not saved yet', 'chưa lưu file')
            if saved:
                # BoxFox paths are workspace-relative, not relative to this Markdown document.
                # The Plan panel has no file-link callback: publish a copyable path, not a broken link.
                reference = f'v{saved["version"]} · `{saved["path"]}`'
            lines += [f'## Sub-plan {node["id"]} — {node["title"]}', '',
                      pick('Depends on: ', 'Phụ thuộc: ') + (', '.join(node['dependsOn']) or '—') + f' · file: {reference}',
                      '', pick('**Acceptance**', '**Nghiệm thu**'), ''] + [f'- {item}' for item in node['acceptance']] + \
                     ['', pick('**Tests**', '**Kiểm thử**'), ''] + [f'- {item}' for item in node['tests']] + ['']
        review = run.get('review') or {}
        if review.get('rounds'):
            lines += [pick('## Review record', '## Lịch sử phản biện'), '']
            for index, item in enumerate(review['rounds']):
                label = pick('Whole-plan review', 'Phản biện toàn kế hoạch')
                lines.append(f'- {label} {index + 1}: `{item.get("verdict")}`')
            for node in run['nodes']:
                for name, state in node['stages'].items():
                    for item in state['rounds']:
                        lines.append(f'- {node["id"]}/{name} ' + pick('round ', 'vòng ') + f'{item["attempt"]}: {item.get("producerRole")} → '
                                     f'{item.get("reviewerRole")} `{item.get("verdict")}`')
            lines.append('')
        return '\n'.join(lines).strip() + '\n'

    def subplan_name(self, node):
        return f'{node["id"].lower()}-{slugify(node["title"], 32)}'

    def subplan_document(self, run, node):
        state = node['stages']['produce']
        lang = work_prompts.language(run['goal'])
        header = [f'# {node["id"]} — {node["title"]}', '',
                  work_prompts.choose(lang, f'> Sub-plan of `{run["title"]}` (Work Graph `{run["runId"]}`) · depends on ',
                                      f'> Sub-plan thuộc `{run["title"]}` (Work Graph `{run["runId"]}`) · phụ thuộc ')
                  + (', '.join(node['dependsOn']) or '—') + work_prompts.choose(lang, ' · review `', ' · phản biện `')
                  + (state['rounds'][-1].get('verdict') if state['rounds'] else work_prompts.choose(lang, 'not run', 'chưa chạy'))
                  + '` ' + work_prompts.choose(lang, 'after ', 'sau ') + str(state['attempts'])
                  + work_prompts.choose(lang, ' round(s)', ' vòng'), '']
        return '\n'.join(header) + '\n' + (state.get('output') or '').strip() + '\n'

    async def write_document(self, sid, run, slug, markdown, title):
        args = {'slug': slug, 'markdown': markdown, 'title': title[:120], 'directory': f'work/{run["slug"]}'}
        async with self.rt.writer_lock:
            written = await self.rt.executor.execute('write_plan', args, sid)
        if not isinstance(written, dict) or written.get('is_error') or not written.get('relativePath'):
            detail = (written.get('error') or written) if isinstance(written, dict) else written
            raise ValueError('WORK_DOCUMENT_FAILED: the sandbox did not write '
                             f'{slug}: {str(detail)[:300]}')
        relative = written['relativePath']
        identity = f'work/{run["slug"]}/{slug}'
        payload = {'identity': identity, 'version': written.get('version'), 'slug': slug,
                   'relativePath': relative, 'title': title[:120], 'bytes': len(markdown.encode('utf-8')),
                   'contentHash': hashlib.sha256(markdown.encode('utf-8')).hexdigest(), 'workRunId': run['runId']}
        self.store.emit(sid, 'plan_written', payload)
        return {'path': relative, 'identity': identity, 'version': written.get('version'), 'title': title[:120]}

    async def verify(self, session, args):
        sid = session['id']
        run = self.resolve(sid, args.get('runId'))
        if run.get('verificationVersion') != work_policy.VERSION:
            raise ValueError('WORK_LEGACY_CHECKS_REQUIRED: old documents remain readable; call work_run to import/recheck')
        self.refresh(run)
        if self.busy(run):
            raise ValueError('WORK_RUN_BUSY: another run/check operation is active')
        if run['status'] in ('approved', 'executing', 'executed', 'execute_failed') + TERMINAL_STATUSES:
            raise ValueError(f'WORK_PHASE_INVALID: run is {run["status"]}; verify happens before approval')
        produce = [n for n in run['nodes'] if 'produce' in n['stages']]
        if not produce:
            raise ValueError('WORK_NOT_READY: no producer node to verify')
        unfinished = [n['id'] for n in produce if n['stages']['produce']['status'] != 'accepted'
                      or not self.checks.valid(run, n, 'produce')]
        if unfinished:
            raise ValueError('WORK_NOT_READY: required checks not passed: ' + ', '.join(unfinished))
        review = run.setdefault('review', {'status': None, 'rounds': []})
        if len(review['rounds']) >= MAX_GRAPH_REVIEWS and review.get('status') != 'ok':
            raise ValueError('WORK_REVIEW_EXHAUSTED: checkpoint with unresolved findings; change scope before retry')
        lock = self.locks.setdefault(run['runId'], asyncio.Lock())
        async with lock:
            run['status'] = 'verifying'
            self.save(run, 'verify_started')
            whole_binding = self.whole_binding(run)
            try:
                master = await self.artifacts.put(run, 'whole', 'verify', self.master_document(run),
                                                  {'graphHash': whole_binding}, True)
            except BaseException:
                run['status'] = 'needs_revision'
                self.save(run, 'verify_artifact_failed')
                raise
            metas = [master] + [n['stages']['produce']['artifact'] for n in produce]
            spec = {'id': 'whole', 'executorRole': FLOW_REVIEWER.get(run['flow'], 'plan-review')}
            criteria = {'G1': 'Owner scope/decisions fully covered; no imported old assumptions.',
                        'G2': 'Cross-node contracts/dependencies/order agree.',
                        'G3': 'Acceptance/tests prove the owner goal; risks/rollback proportional.'}
            if work_prompts.language(run['goal']) == 'vi':
                criteria = {'G1': 'Bao phủ mục tiêu/quyết định người dùng; không kế thừa giả định cũ.',
                            'G2': 'Hợp đồng, phụ thuộc và thứ tự giữa các nút thống nhất.',
                            'G3': 'Nghiệm thu/test chứng minh mục tiêu; rủi ro/rollback tương xứng.'}
            if work_policy.research_only(run):
                criteria['G3'] = work_prompts.choose(work_prompts.language(run['goal']),
                    'Sources support the research conclusions; uncertainty, contrary evidence and limitations are honest. '
                    'No implementation, API contract, rollout or executed tests required unless the owner requested them.',
                    'Nguồn hỗ trợ kết luận nghiên cứu; ghi trung thực độ bất định, trái chiều và giới hạn. '
                    'Không đòi triển khai, hợp đồng API, rollout hoặc test đã chạy nếu người dùng chưa yêu cầu.')
            criteria.update({f'{n["id"]}.A{i+1}': item for n in produce for i,item in enumerate(n['acceptance'])})
            doc = {'checkId': 'c-' + uuid.uuid4().hex, 'runId': run['runId'], 'nodeId': 'whole',
                   'stage': 'verify', 'artifactId': master['artifactId'], 'policyHash': work_policy.VERSION,
                   'kind': 'whole', 'status': 'running', 'binding': {'graphHash': whole_binding}, 'startedAt': now()}
            with self.db:
                self.db.execute('INSERT INTO work_checks VALUES(?,?,?,?,?)',
                                (doc['checkId'], run['runId'], doc['checkId'], whole_binding, json.dumps(doc)))
            self.child_budget[run['runId']] = [2]
            try:
                with self.budget_paused(sid):
                    doc = await self.checks.judge(session, run, None, 'verify', spec, metas, criteria, doc, whole=True)
            except BaseException as exc:
                doc.update(status='error', error=str(exc)[:500])
                self.checks.save(doc)
                run['status'] = 'needs_revision'
                self.save(run, 'verify_error')
                raise
            finally:
                self.child_budget.pop(run['runId'], None)
            self.checks.save(doc)
            verdict = 'ok' if doc['status'] == 'pass' else 'revise' if doc['status'] == 'revise' else None
            findings = doc.get('findings', '')
            review['rounds'].append({'childId': doc.get('childId'), 'checkId': doc['checkId'],
                'verdict': verdict or 'unreviewed', 'findings': findings, 'at': now(), 'error': doc.get('error')})
            review.update(status=verdict, binding=whole_binding)
            return await self.finish_verify(sid, run, review, produce, verdict, findings, doc.get('coverage', []))

    def whole_binding(self, run):
        return work_policy.digest({'goal': run['goal'], 'interviews': run.get('interviews'),
            'checkInputsVersion': work_checks.INPUTS_VERSION,
            'nodes': [{k: v for k,v in n.items() if k != 'stages'} for n in run['nodes']],
            'artifacts': [n['stages']['produce'].get('artifact', {}).get('artifactId') for n in run['nodes'] if 'produce' in n['stages']]})

    async def finish_verify(self, sid, run, review, produce, verdict, findings, coverage=()):
        targets = parse_revise_targets(findings, {node['id'] for node in run['nodes']}) if verdict == 'revise' else {}
        if verdict == 'revise':
            for item in coverage:
                match = re.fullmatch(r'(.+)\.A\d+', item['id'])
                if match and item['status'] == 'revise' and match[1] in {n['id'] for n in produce}:
                    targets.setdefault(match[1], item['evidence'])
        if verdict == 'ok':
            documents = []
            try:
                for node in produce:
                    if node['kind'] == PLAN_KIND:
                        documents.append(await self.write_document(sid, run, self.subplan_name(node),
                                                                   self.subplan_document(run, node),
                                                                   f'{node["id"]} — {node["title"]}'))
                documents.insert(0, await self.write_document(sid, run, 'plan', self.master_document(run, documents),
                                                              run['title']))
            except Exception as exc:
                run['documents'] = documents
                run['status'] = 'needs_revision'
                self.save(run, 'documents_failed', str(exc))
                raise
            run['documents'] = documents
            run['status'] = 'verified'
            self.save(run, 'verified')
        else:
            for node_id, reason in targets.items():
                node = next(item for item in run['nodes'] if item['id'] == node_id)
                state = node['stages'].get('produce')
                if state is not None:
                    state.update({'status': 'revise', 'feedback': 'Whole-plan review: ' + reason,
                                  'feedbackSource': 'checks',
                                  'attempts': max(0, state['attempts'] - 1)})
                    state['inputConflicts'] = [{'id': item['id'].split('.', 1)[1],
                        'requirement': node['acceptance'][int(item['id'].split('.A', 1)[1]) - 1],
                        'evidence': item['evidence']} for item in coverage
                        if item.get('target') == 'criterion' and item['id'].startswith(node_id + '.A')]
            run['status'] = 'needs_revision'
            self.save(run, 'verify_revise', ','.join(targets) or 'structural')
        out = self.result(run)
        out.update({'verdict': verdict or 'unreviewed', 'findings': bounded(findings, 4000),
                    'reviseNodes': sorted(targets)})
        return out

    async def submit(self, session, args, call_id=None):
        sid = session['id']
        run = self.resolve(sid, args.get('runId'))
        check_graph(run['nodes'])
        self.require_execution(run)
        self.refresh(run)
        self.require_planning_current(run)
        if run['status'] == 'awaiting_approval':
            if any(record.get('workRunId') == run['runId'] for record in self.rt.pending_for(sid)):
                raise ValueError('WORK_RUN_BUSY: the approval card is already waiting for the owner')
            run['status'] = 'verified'  # the card was lost (restart): ask again
        has_produce = any('produce' in node['stages'] for node in run['nodes'])
        if has_produce and run['status'] != 'verified':
            raise ValueError('WORK_NOT_VERIFIED: call work_graph action=verify first; only a verified plan is '
                             'presented to the owner')
        if not any('execute' in node['stages'] for node in run['nodes']):
            raise ValueError('WORK_NOTHING_TO_EXECUTE: this run has no plan or execution node; answer the owner '
                             'with the verified documents instead')
        summary = str(args.get('summary') or '').strip()
        waves = execution_waves(run['nodes'])
        wave_text = ' → '.join('[' + ' ‖ '.join(wave) + ']' for wave in waves)
        if autopilot_on(self.store.get(sid)):
            self.approve_by_autopilot(run)
            self.save(run, 'approved', 'autopilot')
            return self.result(run, 'Autopilot is on: execution approved without waiting. Call work_run phase=execute.')
        run['status'] = 'awaiting_approval'
        self.save(run, 'approval_requested')
        docs = ', '.join(item['path'] for item in run.get('documents') or []) or 'no document'
        outcome = await self.rt.decision(session, 'request_approval', {
            'action': f'Thực thi kế hoạch "{run["title"]}" theo thứ tự {wave_text}',
            'reason': (summary or f'Kế hoạch đã qua vòng review độc lập. Tài liệu: {docs}.')[:1500],
            'options': [{'id': 'approve', 'label': 'Duyệt và chạy', 'kind': 'approve'},
                        {'id': 'reject', 'label': 'Chưa chạy', 'kind': 'reject'},
                        {'id': 'revise', 'label': 'Cần sửa kế hoạch', 'kind': 'alternative', 'allowFreeText': True}],
            'deadlineSeconds': int(args.get('deadlineSeconds') or 1800), 'workRunId': run['runId']}, call_id)
        run = self.get(run['runId'])
        outcome = outcome or {}
        decision = outcome.get('decision')
        choice = outcome.get('choice')
        if decision == 'approved' and choice != 'revise':
            run['approval'] = {'status': 'approved', 'by': 'owner', 'at': now(),
                               'decisionId': outcome.get('decisionId')}
            run['status'] = 'approved'
            self.save(run, 'approved', 'owner')
            message = 'The owner approved. Call work_run phase=execute.'
        else:
            run['approval'] = {'status': 'changes_requested' if outcome.get('note') else 'rejected',
                               'by': 'owner', 'at': now(), 'note': outcome.get('note'),
                               'decisionId': outcome.get('decisionId')}
            run['status'] = 'needs_revision' if outcome.get('note') else 'verified'
            self.save(run, 'approval_' + run['approval']['status'])
            message = ('The owner did not approve. Read `note`, update the nodes, run and verify again.'
                       if outcome.get('note') else 'The owner did not approve execution. Do not execute.')
        out = self.result(run, message)
        out['decision'] = {key: outcome.get(key) for key in ('decision', 'choice', 'status', 'note')}
        return out

    # ---- ship ---------------------------------------------------------------------------------- #

    async def ship(self, session, args):
        sid = session['id']
        run = self.resolve(sid, args.get('runId'))
        self.require_execution(run)
        self.refresh(run)
        self.require_planning_current(run)
        await self.require_code_current(run)
        if run['status'] != 'executed':
            raise ValueError(f'WORK_NOT_EXECUTED: run is {run["status"]}; ship only after every execution node '
                             'is accepted')
        branch = str(args.get('branch') or f'boxfox/{run["slug"]}').strip()
        if not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', branch) or '..' in branch or branch.startswith('-'):
            raise ValueError('WORK_BRANCH_INVALID: branch may use letters, digits, ., _, / and - only')
        title = str(args.get('title') or run['title']).strip()[:120]
        body = str(args.get('body') or '').strip() or self.pr_body(run)
        doc = await self.write_document(sid, run, 'pull-request', f'# {title}\n\n{body}\n', f'PR — {title}')
        message = title.replace("'", "'\\''")
        repo = str(args.get('repoPath') or '').strip().strip('/') if args.get('repoPath') else ''
        if args.get('repoPath') and (str(args['repoPath']).strip().startswith('/') or not repo
                                     or not re.fullmatch(r'[A-Za-z0-9._/ -]{1,200}', repo)
                                     or '..' in repo.split('/')):
            raise ValueError('WORK_REPO_PATH_INVALID: repoPath must be a relative directory inside the workspace')
        prefix = f"cd '{repo}' && " if repo else ''
        # The PR file path is workspace-relative; commands run inside repoPath.
        body_file = '../' * len([part for part in repo.split('/') if part not in ('', '.')]) + doc['path']
        steps = []

        async def sh(command, timeout=120):
            result = await self.rt.executor.execute('terminal_exec', {'command': prefix + command,
                                                                      'timeout': timeout}, sid)
            text = str((result or {}).get('content') or (result or {}).get('output') or '')
            code = (result or {}).get('exitCode', (result or {}).get('exit_code'))
            failed = bool((result or {}).get('is_error')) or (code not in (None, 0))
            steps.append({'command': command.split(' && ')[0][:160], 'ok': not failed, 'output': text[-600:]})
            return not failed, text

        def not_shipped(status, message):
            # The run stays `executed`: main can fix the input (repoPath, branch) and ship again.
            run['ship'] = {'status': status, 'branch': branch, 'prFile': doc['path'], 'steps': steps, 'at': now()}
            self.save(run, 'ship_' + status)
            return self.result(run, message) | {'ship': run['ship']}

        async with self.rt.writer_lock:
            ok, _ = await sh('git rev-parse --is-inside-work-tree')
            if not ok:
                return not_shipped('no_git', f'{repo or "The workspace"} is not a git repository (or does not '
                                             'exist). Call work_ship with repoPath=<the repository directory inside '
                                             'the workspace>, or report the PR description file to the owner.')
            # Reuse an existing branch instead of resetting it (`-B` would orphan its commits).
            ok, _ = await sh(f"git rev-parse --verify --quiet 'refs/heads/{branch}' >/dev/null "
                             f"&& git checkout '{branch}' || git checkout -b '{branch}'")
            if not ok:
                return not_shipped('checkout_failed', f'git could not switch to branch {branch}; read ship.steps, '
                                                      'fix the working tree, and call work_ship again.')
            ok, _ = await sh("git add -A -- . ':(exclude).plans/work'")
            if not ok:
                return not_shipped('add_failed', 'git add failed; read ship.steps and call work_ship again.')
            committed, commit_out = await sh(f"git -c user.name='BoxFox' -c user.email='boxfox@localhost' "
                                             f"commit -m '{message}' -m 'Work Graph {run['runId']}'")
            if not committed and 'nothing to commit' not in commit_out:
                return not_shipped('commit_failed', 'git commit failed (a hook or config?); read ship.steps, '
                                                    'fix it, and call work_ship again.')
            _, sha = await sh('git rev-parse --short HEAD')
            pushed, pr_url = False, None
            has_remote, _ = await sh('git remote get-url origin')
            if has_remote and args.get('push', True):
                pushed, _ = await sh(f"GIT_TERMINAL_PROMPT=0 git push -u origin '{branch}'", timeout=180)
                if pushed:
                    has_gh, _ = await sh('command -v gh && gh auth status')
                    if has_gh:
                        created, out = await sh(f"gh pr create --draft --title '{message}' --body-file "
                                                f"'{body_file}' --head '{branch}'", timeout=180)
                        match = re.search(r'https://\S+/pull/\d+', out)
                        pr_url = match.group(0) if created and match else None
        run['ship'] = {'status': 'pr_opened' if pr_url else ('pushed' if pushed else 'local'),
                       'branch': branch, 'commit': sha.strip()[-12:] if committed else None,
                       'nothingToCommit': (not committed) and 'nothing to commit' in commit_out,
                       'pushed': pushed, 'prUrl': pr_url, 'prFile': doc['path'], 'steps': steps, 'at': now()}
        run['status'] = 'shipped'
        self.save(run, 'shipped', run['ship']['status'])
        return self.result(run, 'Shipped: ' + run['ship']['status']) | {'ship': run['ship']}

    def pr_body(self, run):
        lines = ['## Summary', '', run['goal'], '', '## Work Graph', '']
        for node in run['nodes']:
            stage = node['stages'].get('execute') or node['stages'].get('produce')
            verdicts = ' → '.join(item.get('verdict') or '?' for item in stage['rounds']) or 'not run'
            lines.append(f'- **{node["id"]}** ({node["kind"]}) {node["title"]} — `{stage["status"]}` ({verdicts})')
        lines += ['', '## Testing', '']
        for node in run['nodes']:
            for test in node['tests']:
                lines.append(f'- [{node["id"]}] {test}')
        documents = run.get('documents') or []
        if documents:
            lines += ['', '## Plan documents', ''] + [f'- `{item["path"]}`' for item in documents]
        return '\n'.join(lines)

    # ---- prompt block -------------------------------------------------------------------------- #

    def prompt_block(self, session):
        if session.get('parent_id') or not enabled():
            return ''
        config = session.get('config') or {}
        intent = config.get(INTENT_CONFIG_KEY) or {}
        run = self.active(session['id'])
        lines = [MARKER]
        if intent:
            flow = intent.get('flow') or 'mixed'
            lines.append(f'The owner typed /{intent.get("command") or flow}: this request goes through the Work '
                         f'Graph (flow `{flow}`). ' + {
                             'plan': 'Explore first, interview only on real ambiguity, then write sub-plans with '
                                     'tests and dependencies, verify, and ask for approval. Do not execute before '
                                     'approval.',
                             'research': 'FAST PATH: when the request is one fact, one version or a yes/no question, '
                                         'answer it yourself with web_search/web_fetch and cite the sources; do not '
                                         'create a run. Otherwise build research nodes (plus explore when the '
                                         'repository matters), run them with review, verify, and answer with the '
                                         'verified findings.',
                             'design': 'Explore the current UI/code, build design nodes, run them with review, '
                                       'verify, and present the verified design.'}.get(flow, ''))
            lines.append(f'Owner request: {bounded(intent.get("text"), 1500)}')
        if run is not None:
            counts = {}
            for node in run['nodes']:
                for name, state in node['stages'].items():
                    counts[state['status']] = counts.get(state['status'], 0) + 1
            lines.append(f'Active run {run["runId"]} "{run["title"]}" flow={run["flow"]} status={run["status"]} '
                         f'nodes={len(run["nodes"])} stages={json.dumps(counts, ensure_ascii=False)} '
                         f'autopilot={"on" if autopilot_on(session) else "off"}.')
            lines.append('Next: ' + self.next_step(run))
            if run['status'] in DRIVING_STATUSES:
                lines.append('Keep this turn going: make the next tool call now. End the turn only for an '
                             'interview, the approval card, or the final answer.')
        if len(lines) == 1:
            return ''
        lines.append(END_MARKER)
        return '\n'.join(lines)
