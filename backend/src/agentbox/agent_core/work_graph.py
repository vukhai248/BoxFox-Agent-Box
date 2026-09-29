"""Work Graph — the orchestration layer where main is the brain (lớp điều phối mới).

Main (the root orchestrator) turns a prompt, ticket or bug into a durable DAG of nodes:

    explore / research / design  →  plan sub-plans P1..Pn (tests + dependsOn)  →  whole-plan review
    →  owner approval (or Autopilot)  →  DAG-aware parallel execution  →  branch + commit + PR text

Invariants of this module (each one has a unit test):

* Only main delegates. A specialist that lacks knowledge writes a `## Knowledge requests` block;
  the HARNESS (not the specialist) asks `research`/`explore` and re-runs the specialist with the
  answers. Delegation depth stays 1.
* Every specialist output is judged by an independent reviewer child that ends with
  `VERDICT: ok|revise`. On `revise` the harness re-runs the same node with the findings, up to
  `maxRounds`. Main only sees an output as `accepted` after `ok`.
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
    out = []
    for item in value[:limit]:
        text = str(item or '').strip()
        if text:
            out.append(text[:item_limit])
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
    node = {'id': node_id, 'kind': kind, 'title': title, 'goal': goal,
            'dependsOn': clean_list(raw.get('dependsOn', base.get('dependsOn')), 'dependsOn', 16, 32),
            'acceptance': clean_list(raw.get('acceptance', base.get('acceptance')), 'acceptance'),
            'tests': clean_list(raw.get('tests', base.get('tests')), 'tests'),
            'files': clean_list(raw.get('files', base.get('files')), 'files', 40, 300)}
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
    return bool(state) and state['status'] == 'accepted'


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

KNOWLEDGE_CONTRACT = """## Knowledge requests — only when a missing FACT blocks you. One line each, max 3:
- research: <external question, for example a library API, a standard, a version>
- explore: <repository question, for example where X is defined or who calls Y>
Write `- none` when you need nothing. You cannot delegate; the harness asks for you and runs you again with the answers."""

DELIVERABLES = {
    'explore': """Deliverable (Markdown, in the owner's language):
## Findings — what exists today, most important first, each with `path:line`.
## Evidence table — | Claim | path:line | quoted line |.
## Contracts & call sites — functions, data shapes, routes, events the work will touch.
## Risks & unknowns — what you could not confirm.""",
    'research': """Deliverable (Markdown, in the owner's language):
## Answer — the direct answer to the question, 3-8 sentences.
## Verified facts — each fact with the exact URL or path you opened and a short verbatim quote.
## Options compared — a table when there is a choice to make (option, pros, cons, cost, fit).
## Contrary evidence & gaps — what disagrees, what you could not open (mark UNVERIFIED).
## Recommendation — one choice and why.""",
    'design': """Deliverable (Markdown, in the owner's language):
## Design goal & users — what the screen/API/flow must let the user do.
## Structure — components or modules and their responsibility; data contracts as TypeScript/Python types.
## States & flows — normal, empty, loading, error, permission states; step-by-step interaction.
## Touch list — the exact files to add or change, grounded in files you read.
## Alternatives & tradeoffs — at least one alternative and why it lost.
## Acceptance — observable checks that prove the design was built.""",
    'plan': """Deliverable: ONE sub-plan in Markdown (the owner's language), at the level of a senior engineer's design doc:
## Mục tiêu / Goal — the outcome of this sub-plan and what is explicitly out of scope.
## Evidence — table | Fact | path:line or URL | what it means for the change |; only facts you or a dependency verified.
## Decisions — table | # | Decision | Chosen | Alternatives | Why |.
## Contracts — data shapes, function signatures, API/route payloads, events, migrations, with types.
## Work items — numbered, each with the exact files and the edit; mark `[song song]` or `[sau P#]` dependencies.
## Tests — each test case with its file, the command to run it, and the expected result (unit + integration/UI).
## Acceptance — observable checks, one per line.
## Risks & rollback — failure modes, their detection, and how to undo.
## Out of scope / do not do — explicit non-goals.""",
    'build': """Deliverable (Markdown):
## Changes — every file changed and what changed.
## Test run — the exact commands you ran and the real observed output (pass/fail counts).
## Deviations — anything you did differently from the sub-plan and why.
## Remaining risk — what is not verified yet.""",
    'debug': """Deliverable (Markdown):
## Reproduction — command and observed failure before the fix.
## Root cause — path:line and why.
## Fix — files changed.
## Proof — the same command after the fix, with output; regression tests run.""",
    'testing': """Deliverable (Markdown):
## Test matrix — each case, how it was run, result.
## Evidence — commands and real output, screenshots when UI.
## Failures — raw error output for every failure.""",
    'simplify': """Deliverable (Markdown):
## Simplifications — files and patterns simplified.
## Behavior proof — the test commands you ran before and after, with output.""",
}

REVIEW_RUBRICS = {
    'explore': 'Check every claim against the repository: open the cited path:line. Reject invented paths, '
               'missing call sites the goal obviously needs, and claims without a location.',
    'research': 'Open the cited URLs/paths when you can. Reject facts without a source, a quote that does not '
                'support the claim, a single source for a decision-critical number, and a recommendation that '
                'ignores contrary evidence. Mark what you could not verify as UNVERIFIED.',
    'design': 'Check the touch list against the repository, that every state (empty, loading, error, '
              'permission) and flow is defined, that contracts are typed, and that acceptance checks could '
              'prove the design was built.',
    'plan': 'Judge the sub-plan as a senior engineer would before approving a design doc: evidence with real '
            'path:line (open them), decisions with alternatives, typed contracts, work items with exact files, '
            'tests that are concrete (file + command + expected result) and cover the acceptance, dependencies '
            'that are right (it must not need a sibling it does not declare), risks with rollback, and no scope '
            'creep beyond the goal.',
    'build': 'Verify the change: read the changed files, run the tests the sub-plan names with terminal_exec, '
             'and check each acceptance item. Do NOT edit source files. Reject when a test fails, a required '
             'test is missing, or an acceptance item is not met.',
    'testing': 'Check that the reported test results are real (commands and output present), cover the '
               'acceptance and include edge cases.',
}
REVIEW_RUBRICS['debug'] = REVIEW_RUBRICS['build']
REVIEW_RUBRICS['simplify'] = REVIEW_RUBRICS['build'] + ' Behavior must be unchanged.'

REVIEW_TAIL = """Output (Markdown):
## Blocking findings — numbered; each names the acceptance item or section, the evidence (path:line, URL, command output) and the exact fix. Write `none` when there are none.
## Non-blocking notes — optional.
END with exactly one final line: `VERDICT: ok` (acceptable as written) or `VERDICT: revise` (it must change). No text after that line. A review without the VERDICT line is discarded."""

WORK_NODE_CONTRACT = """

Result contract (Work Graph node). The harness reviews your answer against the acceptance list; an independent reviewer decides `ok` or `revise`, and on `revise` you are run again with the findings.
- Put the full deliverable in your final answer; nothing else reaches the reviewer.
- Every claim needs evidence (path:line, URL with quote, command with real output). Mark unverified items UNVERIFIED.
- Do not do other nodes' work and do not widen the scope.
""" + KNOWLEDGE_CONTRACT

REVIEW_CONTRACT = """

Result contract (Work Graph review). You are the independent reviewer; you did not produce this output. Read the evidence yourself before judging. Your answer must end with the single VERDICT line."""


def work_child_contract(purpose):
    """Contract appended to a Work Graph child prompt; `None` keeps the generic child contract."""
    if purpose == 'review':
        return REVIEW_CONTRACT
    if purpose == 'produce':
        return WORK_NODE_CONTRACT
    return None


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
        self.recover()

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
        self.emit(run)
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
                stages[name]['preview'] = bounded(state.get('output'), 1200)
                stages[name]['rounds'] = [{key: item.get(key) for key in (
                    'attempt', 'producerId', 'reviewerId', 'verdict', 'error', 'at', 'reviewerRole',
                    'producerRole')} | {'findings': bounded(item.get('findings'), 900),
                                        'knowledge': [{'role': k.get('role'), 'question': k.get('question'),
                                                       'childId': k.get('childId'), 'status': k.get('status')}
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
        if current is not None and current['status'] != 'executed':
            current['status'] = 'cancelled'
            self.save(current, 'superseded', 'a new run was created')
        run = {'runId': 'w-' + uuid.uuid4().hex[:10], 'sessionId': sid, 'goal': goal[:4000],
               'title': str(args.get('title') or goal).strip()[:120], 'flow': flow, 'status': 'drafting',
               'slug': slugify(args.get('title') or goal), 'autopilot': autopilot_on(session),
               'createdAt': now(), 'nodes': [], 'review': {'status': None, 'rounds': []}, 'documents': [],
               'approval': None, 'interviews': [], 'ship': None, 'history': [], 'revision': 0,
               'intent': intent or None}
        if args.get('nodes'):
            self.apply_nodes(run, args['nodes'], replace=False)
        self.clear_intent(session)
        return self.save(run, 'created', f'flow={flow}')

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
                changed = any(existing[key] != node[key] for key in ('goal', 'acceptance', 'tests', 'dependsOn'))
                if changed:
                    changed_any = True
                    for name, state in node['stages'].items():
                        if state['status'] in ('accepted', 'rejected', 'failed'):
                            node['stages'][name] = new_stage() | {'feedback': 'Node definition changed by main.'}
            by_id[node_id] = node
        nodes = list(by_id.values())
        if len(nodes) > MAX_NODES:
            raise ValueError(f'WORK_GRAPH_TOO_LARGE: at most {MAX_NODES} nodes; merge related work')
        check_graph(nodes)
        run['nodes'] = nodes
        if changed_any:
            # A changed graph earns fresh whole-plan reviews; the old rounds judged another plan.
            run['review'] = {'status': None, 'rounds': []}
        if run['status'] in ('verified', 'awaiting_approval', 'approved', 'execute_failed') and changed_any:
            run['status'] = 'drafting'
            run['approval'] = None

    def graph(self, session, args):
        action = str(args.get('action') or 'status').strip().lower()
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

    def result(self, run, message=None):
        view = self.view(run)
        summary = [{'id': node['id'], 'kind': node['kind'], 'title': node['title'], 'dependsOn': node['dependsOn'],
                    'stages': {name: state['status'] for name, state in node['stages'].items()}}
                   for node in view['nodes']]
        out = {'runId': run['runId'], 'status': run['status'], 'flow': run['flow'], 'revision': run['revision'],
               'autopilot': view['autopilot'], 'nodes': summary, 'waves': view['waves'], 'issues': view['issues'],
               'documents': view['documents'], 'next': self.next_step(run)}
        if message:
            out['message'] = message
        return out

    def next_step(self, run):
        """One sentence telling main what the harness expects next (keeps weak models on the path)."""
        status = run['status']
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
            if has_exec:
                return 'Call work_graph action=submit so the owner approves execution (Autopilot approves itself).'
            return 'Answer the owner with the verified result and the document paths.'
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
        rows = self.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='assistant' "
                               'ORDER BY seq DESC LIMIT 50', (child_id,)).fetchall()
        for row in rows:
            try:
                data = json.loads(row['payload'])
            except (TypeError, ValueError):
                continue
            if data.get('final'):
                return data.get('text') or ''
        return ''

    async def spawn(self, session, run, node, stage, purpose, role, goal, context, expect, attempt):
        """One child through the normal `delegate` path (events, slots, budgets, UI) + full answer."""
        budget = self.child_budget.get(run['runId'])
        if budget is not None:
            if budget[0] <= 0:
                raise WorkBudgetExhausted('WORK_CHILD_BUDGET: this work_run call already started '
                                          f'{WORK_CHILDREN_PER_RUN_CALL} children; call work_run again')
            budget[0] -= 1
        work = {'runId': run['runId'], 'nodeId': node['id'] if node else None, 'stage': stage,
                'purpose': purpose, 'attempt': attempt}
        args = {'role': role, 'goal': goal, 'context': bounded(context, 16000), 'expect': expect}
        waited = time.monotonic()
        while True:
            try:
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
        by_id = {item['id']: item for item in run['nodes']}
        parts = []
        room = CONTEXT_MAX_CHARS
        for dep in node['dependsOn']:
            target = by_id.get(dep)
            if target is None:
                continue
            chosen = gate_stage(node, target, stage) or 'produce'
            state = target['stages'].get(chosen) or {}
            if not state.get('output'):
                continue
            piece = bounded(state['output'], max(1500, room // max(1, len(node['dependsOn']))))
            parts.append(f'### Accepted output of {dep} ({target["kind"]}: {target["title"]})\n{piece}')
            room -= len(piece)
        if stage == 'execute' and node['kind'] == PLAN_KIND:
            own = node['stages']['produce'].get('output') or ''
            parts.insert(0, f'### The approved sub-plan {node["id"]} you must implement\n{bounded(own, 9000)}')
        return '\n\n'.join(parts)

    def interview_context(self, run):
        lines = []
        for item in run.get('interviews') or []:
            for answer in item.get('answers') or []:
                lines.append(f'- {answer.get("question")}: {answer.get("answer")}')
        return ('Owner decisions from the interview:\n' + '\n'.join(lines)) if lines else ''

    def producer_goal(self, run, node, stage, feedback, knowledge):
        role = node['kind'] if stage == 'produce' else EXECUTE_ROLE[node['kind']]
        lines = [f'Work Graph run "{run["title"]}" — node {node["id"]} ({node["kind"]}, {stage}).',
                 f'Overall owner goal: {run["goal"]}', '', f'Your assignment: {node["goal"]}']
        if node['acceptance']:
            lines += ['', 'Acceptance (the reviewer checks each item):'] + [f'- {item}' for item in node['acceptance']]
        if node['tests']:
            lines += ['', 'Tests that must exist and pass:'] + [f'- {item}' for item in node['tests']]
        if node['files']:
            lines += ['', 'Expected touch list: ' + ', '.join(node['files'])]
        if node['dependsOn']:
            lines += ['', 'Depends on: ' + ', '.join(node['dependsOn'])]
        if stage == 'execute' and role == 'build':
            lines += ['', 'Implement the sub-plan completely, write the tests it names, run them, and report the '
                          'real output. Do not start other sub-plans.']
        if feedback:
            lines += ['', 'The previous attempt was REJECTED by the reviewer. Fix every blocking finding:', feedback]
        if knowledge:
            lines += ['', 'Answers to your knowledge requests (from the harness):']
            for item in knowledge:
                lines.append(f'- [{item["role"]}] {item["question"]}\n  {bounded(item.get("answer"), 2500)}')
        if stage == 'produce' and node['kind'] == PLAN_KIND:
            siblings = [f'{item["id"]}: {item["title"]}' for item in run['nodes']
                        if item['kind'] == PLAN_KIND and item['id'] != node['id']]
            if siblings:
                lines += ['', 'Sibling sub-plans (do not duplicate their scope): ' + '; '.join(siblings)]
        return role, '\n'.join(lines)

    def reviewer_goal(self, run, node, stage, output):
        kind = node['kind'] if stage == 'produce' else ('build' if node['kind'] == PLAN_KIND else node['kind'])
        lines = [f'Independent review of Work Graph node {node["id"]} ({node["kind"]}, {stage}) in run '
                 f'"{run["title"]}".', f'Owner goal: {run["goal"]}', f'Node assignment: {node["goal"]}']
        if node['acceptance']:
            lines += ['Acceptance to check one by one:'] + [f'- {item}' for item in node['acceptance']]
        if node['tests']:
            lines += ['Required tests:'] + [f'- {item}' for item in node['tests']]
        lines += ['', 'Rubric: ' + REVIEW_RUBRICS.get(kind, REVIEW_RUBRICS['plan']),
                  '', 'The output to review is in the context below.', '', REVIEW_TAIL]
        return '\n'.join(lines), f'### Output of {node["id"]} to review\n{bounded(output, 14000)}'

    async def answer_knowledge(self, session, run, node, stage, requests, attempt):
        async def one(item):
            goal = (f'Knowledge request from Work Graph node {node["id"]} ({node["kind"]}) in run '
                    f'"{run["title"]}". Answer precisely with evidence (path:line or URL + quote): '
                    f'{item["question"]}')
            try:
                result, answer = await self.spawn(session, run, node, stage, 'knowledge', item['role'], goal,
                                                  f'Owner goal: {run["goal"]}', None, attempt)
                return item | {'childId': result.get('sessionId'), 'status': result.get('status'),
                               'answer': bounded(answer, 4000)}
            except Exception as exc:
                return item | {'childId': None, 'status': 'failed', 'answer': f'UNAVAILABLE: {exc}'[:500]}
        return list(await asyncio.gather(*(one(item) for item in requests)))

    async def run_stage(self, session, run, node, stage, max_rounds):
        state = node['stages'][stage]
        state['status'] = 'running'
        state['startedAt'] = state['startedAt'] or now()
        state['error'] = None
        self.save(run, 'node_started', f'{node["id"]}:{stage}')
        reviewer_role = PRODUCE_REVIEWER[node['kind']] if stage == 'produce' else EXECUTE_REVIEWER[node['kind']]
        try:
            while state['attempts'] < max_rounds:
                state['attempts'] += 1
                attempt = state['attempts']
                role, goal = self.producer_goal(run, node, stage, state.get('feedback'), [])
                context = '\n\n'.join(part for part in (self.interview_context(run),
                                                        self.dependency_context(run, node, stage)) if part)
                expect = DELIVERABLES.get(node['kind'] if stage == 'produce' else role)
                entry = {'attempt': attempt, 'producerRole': role, 'reviewerRole': reviewer_role, 'at': now(),
                         'knowledge': []}
                state['rounds'].append(entry)
                produced, output = await self.spawn(session, run, node, stage, 'produce', role, goal, context,
                                                    expect, attempt)
                entry['producerId'] = produced.get('sessionId')
                requests = parse_knowledge_requests(output)
                if requests:
                    state['status'] = 'researching'
                    self.save(run, 'knowledge_requested', f'{node["id"]}: {len(requests)}')
                    answers = await self.answer_knowledge(session, run, node, stage, requests, attempt)
                    entry['knowledge'] = answers
                    state['knowledge'] = (state.get('knowledge') or []) + answers
                    state['status'] = 'running'
                    role, goal = self.producer_goal(run, node, stage, state.get('feedback'), answers)
                    goal += ('\n\nYou already asked your knowledge requests; the answers are above. Deliver the '
                             'full result now and write `- none` under Knowledge requests.')
                    produced, output = await self.spawn(session, run, node, stage, 'produce', role, goal, context,
                                                        expect, attempt)
                    entry['producerId'] = produced.get('sessionId')
                if produced.get('is_error') and not output.strip():
                    entry['error'] = str(produced.get('last_error') or produced.get('status'))[:400]
                    state['error'] = entry['error']
                    if attempt >= max_rounds:
                        state['status'] = 'failed'
                        break
                    state['feedback'] = f'The previous attempt failed ({entry["error"]}). Finish within budget.'
                    continue
                state['output'] = bounded(output, OUTPUT_MAX_CHARS)
                state['outputChars'] = len(output)
                state['status'] = 'reviewing'
                self.save(run, 'node_reviewing', f'{node["id"]}:{stage}#{attempt}')
                review_goal, review_context = self.reviewer_goal(run, node, stage, output)
                verdict, findings, reviewer_id = None, '', None
                for _ in range(2):  # one retry when the reviewer forgets the VERDICT line or fails
                    reviewed, review_text = await self.spawn(session, run, node, stage, 'review', reviewer_role,
                                                             review_goal, review_context, None, attempt)
                    reviewer_id = reviewed.get('sessionId')
                    verdict, findings = parse_verdict(review_text)
                    if verdict:
                        break
                entry.update({'reviewerId': reviewer_id, 'verdict': verdict or 'unreviewed',
                              'findings': findings, 'at': now()})
                if verdict == 'ok':
                    state['status'] = 'accepted'
                    state['feedback'] = ''
                    break
                state['feedback'] = findings or 'The reviewer did not return a verdict; tighten evidence.'
                state['status'] = 'revise' if attempt < max_rounds else 'rejected'
                self.save(run, 'node_revise', f'{node["id"]}:{stage}#{attempt}')
                if state['status'] == 'rejected':
                    break
                state['status'] = 'running'
            else:
                state['status'] = 'rejected'
        except asyncio.CancelledError:
            state['status'] = 'pending'
            state['error'] = 'cancelled'
            self.save(run, 'node_cancelled', node['id'])
            raise
        except WorkBudgetExhausted as exc:
            # This attempt never finished: give it back and wait for the next work_run call.
            if state['rounds'] and not state['rounds'][-1].get('verdict'):
                state['rounds'].pop()
            state['attempts'] = max(0, state['attempts'] - 1)
            state['status'] = 'revise' if state['rounds'] else 'pending'
            state['error'] = str(exc)[:500]
        except Exception as exc:
            state['status'] = 'failed'
            state['error'] = str(exc)[:500]
        state['finishedAt'] = now()
        self.save(run, 'node_' + state['status'], f'{node["id"]}:{stage}')
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
        if stage == 'execute':
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
        only = set(clean_list(args.get('nodeIds'), 'nodeIds', 24, 32))
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

    def approve_by_autopilot(self, run):
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
        timed_out = False
        try:
            while True:
                remaining = WORK_RUN_MAX_SECONDS - (time.monotonic() - started)
                if remaining <= 0:
                    timed_out = True
                    break
                budget = self.child_budget.get(run['runId'])
                if budget is None or budget[0] > 0:
                    for node in ready_nodes(run, stage, only or None):
                        if node['id'] in running or len(running) >= limit:
                            continue
                        running[node['id']] = asyncio.ensure_future(
                            self.run_stage(session, run, node, stage, max_rounds))
                if not running:
                    break
                done, _ = await asyncio.wait(list(running.values()), timeout=remaining,
                                             return_when=asyncio.FIRST_COMPLETED)
                for node_id in [key for key, task in running.items() if task in done]:
                    task = running.pop(node_id)
                    if task.cancelled():
                        continue
                    if task.exception() is not None:
                        node = next(item for item in run['nodes'] if item['id'] == node_id)
                        node['stages'][stage].update({'status': 'failed', 'error': str(task.exception())[:500]})
        finally:
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
                           'lastFindings': bounded(node['stages'][stage].get('feedback'), 1200)}
                          for node in run['nodes'] if stage in node['stages']
                          and (not only or node['id'] in only)]
        return out

    # ---- whole-plan review, documents, approval --------------------------------------------- #

    def master_document(self, run):
        lines = [f'# {run["title"]}', '', f'> Work Graph `{run["runId"]}` · flow `{run["flow"]}` · '
                 f'generated {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}', '',
                 '## Mục tiêu / Goal', '', run['goal'], '']
        interview = self.interview_context(run)
        if interview:
            lines += ['## Quyết định của chủ nhà / Owner decisions', '', interview.split('\n', 1)[-1], '']
        discovery = [node for node in run['nodes'] if node['kind'] in DISCOVERY_KINDS]
        if discovery:
            lines += ['## Khảo sát / Discovery (accepted after review)', '']
            for node in discovery:
                state = node['stages']['produce']
                lines += [f'### {node["id"]} · {node["kind"]} · {node["title"]}', '',
                          f'Status: `{state["status"]}` after {state["attempts"]} round(s).', '',
                          bounded(state.get('output'), 6000), '']
        plans = [node for node in run['nodes'] if node['kind'] == PLAN_KIND]
        execs = [node for node in run['nodes'] if node['kind'] in EXECUTION_KINDS]
        if plans or execs:
            lines += ['## Đồ thị việc / Work DAG', '', '| Node | Kind | Title | Depends on | Tests | Review |',
                      '|---|---|---|---|---|---|']
            for node in plans + execs:
                state = node['stages'].get('produce') or node['stages'].get('execute')
                verdicts = ' → '.join(item.get('verdict') or '?' for item in state['rounds']) or 'not run'
                lines.append(f'| {node["id"]} | {node["kind"]} | {node["title"]} | '
                             f'{", ".join(node["dependsOn"]) or "—"} | {len(node["tests"])} | {verdicts} |')
            waves = execution_waves(run['nodes'])
            if waves:
                lines += ['', '### Thứ tự thực thi / Execution waves', '']
                lines += [f'{index + 1}. ' + ' ‖ '.join(wave) + (' (song song)' if len(wave) > 1 else '')
                          for index, wave in enumerate(waves)]
            lines.append('')
        for node in plans:
            lines += [f'## Sub-plan {node["id"]} — {node["title"]}', '',
                      f'Depends on: {", ".join(node["dependsOn"]) or "none"} · file: `{self.subplan_name(node)}`',
                      '', '**Acceptance**', ''] + [f'- {item}' for item in node['acceptance']] + \
                     ['', '**Tests**', ''] + [f'- {item}' for item in node['tests']] + ['']
        review = run.get('review') or {}
        if review.get('rounds'):
            lines += ['## Review record', '']
            for index, item in enumerate(review['rounds']):
                lines.append(f'- Whole-plan review {index + 1}: `{item.get("verdict")}`')
            for node in run['nodes']:
                for name, state in node['stages'].items():
                    for item in state['rounds']:
                        lines.append(f'- {node["id"]}/{name} round {item["attempt"]}: {item.get("producerRole")} → '
                                     f'{item.get("reviewerRole")} `{item.get("verdict")}`')
            lines.append('')
        return '\n'.join(lines).strip() + '\n'

    def subplan_name(self, node):
        return f'{node["id"].lower()}-{slugify(node["title"], 32)}'

    def subplan_document(self, run, node):
        state = node['stages']['produce']
        header = [f'# {node["id"]} — {node["title"]}', '',
                  f'> Sub-plan of `{run["title"]}` (Work Graph `{run["runId"]}`) · depends on '
                  f'{", ".join(node["dependsOn"]) or "none"} · review `'
                  f'{(state["rounds"][-1].get("verdict") if state["rounds"] else "not run")}` after '
                  f'{state["attempts"]} round(s)', '']
        return '\n'.join(header) + '\n' + (state.get('output') or '').strip() + '\n'

    async def write_document(self, sid, run, slug, markdown, title):
        args = {'slug': slug, 'markdown': markdown, 'title': title[:120], 'directory': f'work/{run["slug"]}'}
        async with self.rt.writer_lock:
            written = await self.rt.executor.execute('write_plan', args, sid)
        if not isinstance(written, dict) or written.get('is_error') or not written.get('relativePath'):
            raise ValueError('WORK_DOCUMENT_FAILED: the sandbox did not write '
                             f'{slug}: {str((written or {}).get("error") or written)[:300]}')
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
        if run['status'] in ('approved', 'executing', 'executed', 'execute_failed') + TERMINAL_STATUSES:
            raise ValueError(f'WORK_PHASE_INVALID: run is {run["status"]}; verify happens before approval')
        produce = [node for node in run['nodes'] if 'produce' in node['stages']]
        if not produce:
            raise ValueError('WORK_NOT_READY: the graph has no explore/research/design/plan node to verify')
        unfinished = [node['id'] for node in produce if node['stages']['produce']['status'] != 'accepted']
        if unfinished:
            raise ValueError('WORK_NOT_READY: nodes not accepted yet: ' + ', '.join(unfinished)
                             + ' — run work_run phase=discover or update/remove them')
        review = run.setdefault('review', {'status': None, 'rounds': []})
        if len(review['rounds']) >= MAX_GRAPH_REVIEWS and review.get('status') != 'ok':
            raise ValueError(f'WORK_REVIEW_EXHAUSTED: {MAX_GRAPH_REVIEWS} whole-plan reviews did not pass; '
                             'report the findings to the owner and ask how to proceed')
        run['status'] = 'verifying'
        self.save(run, 'verify_started')
        master = self.master_document(run)
        bodies = '\n\n'.join(f'=== {node["id"]} ({node["kind"]}) ===\n{bounded(node["stages"]["produce"]["output"], 5000)}'
                             for node in produce if node['kind'] == PLAN_KIND) or '\n\n'.join(
            f'=== {node["id"]} ({node["kind"]}) ===\n{bounded(node["stages"]["produce"]["output"], 6000)}'
            for node in produce)
        reviewer = FLOW_REVIEWER.get(run['flow'], 'plan-review')
        goal = '\n'.join([
            f'Whole-plan review of Work Graph run "{run["title"]}" before the owner approves it.',
            f'Owner goal: {run["goal"]}', '',
            'Check, as a senior engineer would: (1) COVERAGE — every part of the owner goal and every owner '
            'decision is covered by some node; nothing is out of scope; (2) DEPENDENCIES — each sub-plan declares '
            'the siblings it really needs, there is no hidden coupling, and contracts agree across sub-plans; '
            '(3) ORDER — the execution waves are safe (a wave never needs output from a later wave); (4) TESTS — '
            'every sub-plan has concrete tests and the union proves the goal; (5) RISK — rollout and rollback are '
            'defined for risky parts.',
            'For each sub-plan that must change write a line `REVISE <nodeId>: <what to fix>`. Structural problems '
            '(a missing sub-plan, a wrong dependency) go under Blocking findings.', '', REVIEW_TAIL])
        context = f'### Master document\n{bounded(master, 7000)}\n\n### Sub-plans / outputs\n{bodies}'
        self.child_budget[run['runId']] = [4]
        try:
            with self.budget_paused(sid):
                verdict, findings, child_id, error = await self.verify_review(session, run, reviewer, goal, context,
                                                                              len(review['rounds']) + 1)
        finally:
            self.child_budget.pop(run['runId'], None)
        review['rounds'].append({'childId': child_id, 'verdict': verdict or 'unreviewed', 'findings': findings,
                                 'at': now(), 'error': error})
        review['status'] = verdict
        return await self.finish_verify(sid, run, review, produce, verdict, findings)

    async def verify_review(self, session, run, reviewer, goal, context, attempt):
        """Whole-plan reviewer child; one retry when it fails or forgets the VERDICT line."""
        verdict, findings, child_id, error = None, '', None, None
        for _ in range(2):
            try:
                result, text = await self.spawn(session, run, None, 'verify', 'review', reviewer, goal, context,
                                                None, attempt)
            except Exception as exc:
                error = str(exc)[:400]
                continue
            child_id = result.get('sessionId')
            verdict, findings = parse_verdict(text)
            if verdict:
                break
        return verdict, findings, child_id, error

    async def finish_verify(self, sid, run, review, produce, verdict, findings):
        targets = parse_revise_targets(findings, {node['id'] for node in run['nodes']}) if verdict == 'revise' else {}
        if verdict == 'ok':
            documents = []
            try:
                for node in produce:
                    if node['kind'] == PLAN_KIND:
                        documents.append(await self.write_document(sid, run, self.subplan_name(node),
                                                                   self.subplan_document(run, node),
                                                                   f'{node["id"]} — {node["title"]}'))
                documents.insert(0, await self.write_document(sid, run, 'plan', self.master_document(run),
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
                                  'attempts': max(0, state['attempts'] - 1)})
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
            lines.append(f'The owner typed /{intent.get("command") or flow}: this request MUST go through the Work '
                         f'Graph (flow `{flow}`). ' + {
                             'plan': 'Explore first, interview only on real ambiguity, then write sub-plans with '
                                     'tests and dependencies, verify, and ask for approval. Do not execute before '
                                     'approval.',
                             'research': 'Build research nodes (plus explore when the repository matters), run them '
                                         'with review, verify, and answer with the verified findings.',
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
        if len(lines) == 1:
            return ''
        lines.append(END_MARKER)
        return '\n'.join(lines)
