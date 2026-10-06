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
from . import work_repair
from .work_worktrees import INTEGRATION_NODE, IsolationError, Worktrees, git_mode
from . import work_worktrees

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
# Quyết định chủ nhà #6457 (03/10/2026): ngân sách MỖI LỜI GỌI nâng 72 → 256 con và
# 3600 → 21600 s (6 h) để việc dài kiểu Devin không bị cắt; trần vẫn giữ vì đây là trần CỦA
# MỘT LỜI GỌI, còn `lifetime` bên dưới đếm cộng dồn toàn đời run (chỉ báo cáo, chưa chặn —
# số thật sẽ chốt trần cứng ở W6.5.2).
WORK_CHILDREN_PER_RUN_CALL = 256
WORK_RUN_MAX_SECONDS = 21600.0
OUTPUT_MAX_CHARS = 20000
CONTEXT_MAX_CHARS = 15000
FINDINGS_MAX_CHARS = 3000
# #6474: trần token claim của `reviewedSet`. Chạm trần thì ghi lại `claimsTotal`/`claimsTruncated`
# thay vì cắt im lặng — badge không được nói "đã kiểm" cho một tập bị cắt mà không nói gì.
CLAIM_TOKENS_MAX = 600
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

# --- W6.2/W6.2.BIND: claim kỹ thuật trong câu trả lời -------------------------------------------------
CLAIM_PATH_RE = re.compile(r'(?:https?://[^\s`)\]]+|\b[\w.@-]+(?:/[\w.@-]+)+)')
CLAIM_CALL_RE = re.compile(r'\b[A-Za-z_][\w.]*\(\)')
CLAIM_CODE_RE = re.compile(r'\b[A-Z][A-Z0-9_]{5,}\b')
UNVERIFIED_LABEL_RE = re.compile(r"chưa kiểm|unverified|not verified", re.I)


def norm_claim(token):
    return re.sub(r'\s+', ' ', str(token or '').strip().lower()).rstrip('.,;:`')


def claim_tokens(text):
    """Path/URL, `name()`, số có đơn vị và mã lỗi `[A-Z_]{6,}` trong một đoạn văn."""
    body = str(text or '')
    tokens = [match.group(0) for match in CLAIM_PATH_RE.finditer(body)]
    tokens += [match.group(0) for match in CLAIM_CALL_RE.finditer(body)]
    tokens += [match.group(0) for match in CLAIM_CODE_RE.finditer(body)]
    tokens += [match.group(0) for match in work_checks.NUMERIC_CLAIM_RE.finditer(body)]
    return {token.strip() for token in tokens if token.strip()}


def final_claims_check(run, text):
    """Tokens kỹ thuật của câu tổng hợp cuối không nằm trong tài liệu đã phản biện.

    Chỉ ghi lại để eval/UI đọc; không chặn câu trả lời và không gọi reviewer. Token trong đoạn có
    nhãn "chưa kiểm/unverified" được bỏ qua — đó chính là cách khai báo hợp lệ.
    """
    known = set((run.get('reviewedSet') or {}).get('claims') or [])
    flagged, seen = [], set()
    for paragraph in re.split(r'\n\s*\n', str(text or '')):
        if UNVERIFIED_LABEL_RE.search(paragraph):
            continue
        for token in sorted(claim_tokens(paragraph)):
            key = norm_claim(token)
            if key in known or key in seen:
                continue
            seen.add(key)
            flagged.append(token)
    return flagged


def claim_sources(answer, reads):
    """Path/URL được nhắc trong câu trả lời nhưng không khớp một nguồn đã mở có nội dung."""
    opened = set()
    for read in reads or []:
        proof = work_feedback.evidence_signature(read)
        if not proof:
            continue
        ref = norm_claim(proof['ref'])
        opened.add(ref)
        opened.add(ref.split(':', 1)[0])  # `docs/a.md:12` và `docs/a.md` là cùng một nguồn
    unsourced = []
    for match in CLAIM_PATH_RE.finditer(str(answer or '')):
        token = match.group(0).strip()
        key = norm_claim(token)
        if key in opened or key.split(':', 1)[0] in opened:
            continue
        unsourced.append(token)
    return unsourced


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
    for field, choices in (('taskKind', work_policy.TASKS), ('artifactKind', work_policy.ARTIFACTS),
                           ('risk', work_policy.RISKS), ('depth', work_policy.DEPTHS)):
        value = raw.get(field, base.get(field))
        if value is not None and value not in choices:
            raise ValueError(f'WORK_NODE_INVALID: {field} must be one of {choices}')
    node = {'id': node_id, 'kind': kind, 'title': title, 'goal': goal,
            'dependsOn': clean_list(raw.get('dependsOn', base.get('dependsOn')), 'dependsOn', 16, 32),
            'acceptance': clean_list(raw.get('acceptance', base.get('acceptance')), 'acceptance', 64),
            'tests': clean_list(raw.get('tests', base.get('tests')), 'tests'),
            'files': clean_list(raw.get('files', base.get('files')), 'files', 40, 300)}
    for field in ('taskKind', 'artifactKind', 'risk', 'depth'):
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
            if state['status'] in ('rejected', 'failed') or (state['status'] == 'needs_user'
                    and str(state.get('error') or '').startswith('RESEARCH_NEEDS_MAIN')):
                # Nút `research` do main dựng không còn đường đóng nào khác (bề mặt 7 đã xoá), nên nó là
                # nút CHẾT: nút phụ thuộc phải được báo `blocked` thay vì im lặng chờ mãi.
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
        self.worktrees = Worktrees(self)
        from .work_progress import Progress
        self.progress = Progress(self)
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

    # ---- nodes (W8.A4.4: the run branch is one extra, virtual node) --------------------------- #

    def all_nodes(self, run):
        """Real nodes plus the virtual `__integration__` node of a git-isolated run."""
        nodes = list(run['nodes'])
        if git_mode(run) and isinstance(run.get('integration'), dict):
            nodes.append(self.integration_node(run))
        return nodes

    def find_node(self, run, node_id):
        for node in run['nodes']:
            if node['id'] == node_id:
                return node
        if node_id == INTEGRATION_NODE and git_mode(run) and isinstance(run.get('integration'), dict):
            return self.integration_node(run)
        return None

    def integration_node(self, run):
        """The merged run branch as a node: `execute` checks the integration snapshot, never a worktree."""
        integration = run.setdefault('integration', {'nodes': {}, 'checkIds': []})
        state = integration.setdefault('stage', new_stage())
        integration.setdefault('nodes', {})
        accepted = [n['id'] for n in run['nodes']
                    if n['stages'].get('execute', {}).get('status') in ('accepted', 'revise')]
        # `kind` is a real kind: a repair round on the run branch runs a Build child, so every
        # role/prompt/derive lookup must find 'build' here (there is no 'integrate' role).
        return {'id': INTEGRATION_NODE, 'kind': 'build', 'title': 'Integrated run branch',
                'goal': 'Verify the merged changes of this run on one exact snapshot of the run branch.',
                'acceptance': ['Every required test passes on the integrated snapshot.'],
                'tests': sorted({t for n in run['nodes'] for t in (n.get('tests') or [])}),
                'files': [], 'dependsOn': accepted, 'risk': 'normal', 'taskKind': None,
                'artifactKind': 'patch', 'depth': 'standard', 'stages': {'execute': state}}

    def workspace_of(self, run, node):
        """`{root, branch, base}` of the node worktree, or None outside git isolation."""
        if not git_mode(run):
            return None
        root, base = self.worktrees.code_root(run, node)
        if not root:
            return None
        row = self.worktrees.row(self.worktrees.node_ident(run, node))
        return {'root': root, 'branch': (row or {}).get('branch'), 'base': base}

    def raise_issue(self, run, kind, node_id, stage, message, extra=None):
        """Queue a durable main decision (source c). It records a reference; it never starts work."""
        node = self.find_node(run, node_id) if node_id else None
        state = ((node or {}).get('stages') or {}).get(stage) or {}
        identity = {'kind': kind, 'nodeId': node_id, 'stage': stage, 'revision': run.get('revision'),
                    'artifactId': (state.get('artifact') or {}).get('artifactId'),
                    'repairs': len(state.get('repairs') or []),
                    'status': state.get('status'),
                    'treeHash': (run.get('integration') or {}).get('treeHash')}
        payload = {'kind': kind, 'nodeId': node_id, 'stage': stage,
                   'reason': str(message)[:1000], **(extra or {})}
        ident = self.decisions.enqueue(run['sessionId'], run['runId'], kind,
                                      f'{node_id or "run"}:{stage}:{kind}', identity, payload, time.time())
        self.save(run, 'main_decision', kind)
        return ident

    def execute_status(self, run):
        """`executed` needs every execute node accepted AND the integration record checked."""
        stages = [n['stages']['execute'] for n in run['nodes'] if 'execute' in n['stages']]
        if not stages or not all(s['status'] == 'accepted' for s in stages):
            return None
        if not git_mode(run):
            return 'executed'
        integration = run.get('integration') or {}
        return 'executed' if integration.get('status') == 'checked' else 'approved'

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
                'progressAdmissions': self.progress.records(run['runId'], limit=30),
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
        if action in ('add', 'update', 'remove', 'retry', 'cancel', 'resolve') and self.busy(run):
            raise ValueError('WORK_RUN_BUSY: work_run is running for this run; wait for it to return')
        if action in ('add', 'update'):
            self.apply_nodes(run, args.get('nodes'), replace=action == 'update')
            return self.result(self.save(run, action, ','.join(str((n or {}).get('id')) for n in args['nodes']
                                                                if isinstance(n, dict))))
        if action == 'resolve':
            return self.resolve_conflicts(run, args)
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
        if action == 'set_repair':
            policy = work_repair.set_policy(run, args, MAX_ROUNDS_CEILING)
            self.save(run, 'repair_policy', work_repair.describe(run))
            return self.result(run, 'Repair policy: ' + work_repair.describe(run)) | {'repairPolicy': policy}
        if action == 'cancel':
            run['status'] = 'cancelled'
            return self.result(self.save(run, 'cancelled'))
        raise ValueError(f'WORK_ACTION_INVALID: action {action!r} is not supported here')

    def resolve_conflicts(self, run, args):
        """#6456(b): xác nhận/xoá xung đột đầu vào mà KHÔNG phá bản nháp.

        `action=update` xoá được xung đột nhưng đặt lại stage (`new_stage()`), tức mất
        artifact/policy/bản nháp vừa sửa — đo ở W8.A4.5.N lượt 9/12: chỉ cần con kiểm dán nhãn
        `criterion` là cả vòng sửa bị chặn, rồi công sửa cũng mất. Đường này giữ nguyên trạng thái
        stage, chỉ bỏ danh sách xung đột (có ghi nhật ký) để lượt kiểm/sản xuất kế tiếp chạy tiếp
        trên chính bản nháp đó. Sản phẩm không tự phán tiêu chí đúng hay sai: nếu artifact vẫn vi
        phạm, lượt kiểm sau đỏ lại và vòng sửa tiếp tục.
        """
        only_stage = str(args.get('stage') or '').strip() or None
        ids = set(clean_list(args.get('nodeIds'), 'nodeIds', MAX_NODES, 32))
        note = str(args.get('note') or '').strip()[:500]
        cleared = []
        for node in run['nodes']:
            if ids and node['id'] not in ids:
                continue
            names = [only_stage] if only_stage else list(node['stages'])
            for stage in names:
                state = node['stages'].get(stage)
                if not state or not state.get('inputConflicts'):
                    continue
                cleared.append({'nodeId': node['id'], 'stage': stage, 'conflicts': state['inputConflicts']})
                state['inputConflicts'] = []
                # Ghi vết lên chính hồ sơ lượt kiểm: nếu không, lượt kiểm kế tiếp của một loại khác
                # dựng lại hàng rào từ bản ghi cũ và `resolve` coi như bị hoàn tác.
                self.checks.mark_conflicts_resolved(run['runId'], node['id'], stage, note)
        # W10: hàng rào "mã đã đổi" cũng phải có đường xoá. Khi mọi lượt kiểm của stage đều bị từ
        # chối (`superseded`) vì cây mã đổi, stage bị kẹt ở needs_checks: `work_run` không chạy lại
        # (chỉ chạy stage pending/revise), `retry` từ chối (nút không rejected/failed), và chỉ còn
        # `action=update` — đường duy nhất xoá luôn bản nháp. Đường này giữ bản nháp, trả stage về
        # sản xuất để dựng bản mới trên cây hiện tại.
        for node in run['nodes']:
            if ids and node['id'] not in ids:
                continue
            names = [only_stage] if only_stage else list(node['stages'])
            for stage in names:
                state = node['stages'].get(stage)
                if not state or state['status'] not in ('needs_checks', 'revise'):
                    continue
                latest = [doc for doc in self.checks.latest(run, node, stage).values() if doc]
                if not latest or any(doc.get('status') != 'superseded' for doc in latest):
                    continue
                cleared.append({'nodeId': node['id'], 'stage': stage, 'conflicts': state.get('inputConflicts') or [],
                                'codeMoved': state.get('codeMoved')})
                state['inputConflicts'] = []
                state.update(status='pending', error=None)
                self.checks.mark_conflicts_resolved(run['runId'], node['id'], stage, note or 'code moved')
        if not cleared:
            raise ValueError('WORK_NO_CONFLICT: no input conflict or refused-check barrier to resolve for the '
                             'given nodes/stage')
        self.save(run, 'input_conflicts_resolved', json.dumps(cleared, ensure_ascii=False)[:600])
        message = ('Cleared %d input conflict(s) and %d refused-check barrier(s); the draft is kept. '
                   % (sum(len(item['conflicts']) for item in cleared),
                      sum(1 for item in cleared if item.get('codeMoved') is not None))) + \
            ('A stage that is still open (needs_checks/revise) continues with the next work_run/check; '
             'a stage returned to pending needs work_run phase=execute to produce a fresh draft on the '
             'current code; a rejected/failed stage needs work_graph action=retry first.') + \
            (f' Note: {note}' if note else '')
        return self.result(run, message) | {'resolved': cleared}

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
            # W10: nút kẹt ở needs_checks vì mã đã đổi KHÔNG phải lỗi "không có gì để chạy lại" —
            # thông báo cũ để main hết đường và rò mã nội bộ ra chủ sở hữu (đo ở W10.F ca S12).
            stuck = [(node['id'], name) for node in run['nodes'] for name, state in node['stages'].items()
                     if state.get('codeMoved') is not None or state.get('status') in ('needs_checks', 'revise')]
            raise ValueError('WORK_NOTHING_TO_RETRY: no rejected or failed stage'
                             + (' among ' + ', '.join(sorted(ids)) if ids else '')
                             + '. A stage that is open or blocked by a moved tree has two paths: '
                               'work_graph action=resolve (clears the barrier and returns the stage to '
                               'production, keeping the draft) or work_run phase=execute (produce again on '
                               'the current code). Open stages now: ' + str(stuck[:6]))
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
               'handoffActions': view['handoffActions'], 'next': self.next_step(run),
               'reviewedSet': run.get('reviewedSet'), 'stale': self.stale_review(run)}
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
            return ('Main: settle the assignment question first. If the node goal/acceptance really is wrong, '
                    'correct it with work_graph action=update (new draft, fresh checks). If the label was wrong '
                    'and the current draft stands, clear the barrier with work_graph action=resolve — it keeps the '
                    'draft, its artifact and its history. Then retry checks or production: ' + str(conflicts))
        moved = [(n['id'], stage, s.get('codeMoved')) for n in self.all_nodes(run) for stage, s in n['stages'].items()
                 if s.get('codeMoved') is not None and s['status'] in ('pending', 'needs_checks', 'revise')]
        if moved:
            return ('Main: the tree moved inside these nodes\' declared files, so their current drafts cannot be '
                    'checked: ' + str(moved[:4]) + '. Call work_graph action=resolve to clear the barrier (the draft '
                    'and its history are kept), then work_run phase=execute to produce a fresh draft on the current code.')
        parked = [(n['id'], stage) for n in self.all_nodes(run) for stage, s in n['stages'].items()
                  if s['status'] == 'needs_user' and str(s.get('error') or '').startswith('RESEARCH_NEEDS_MAIN')]
        if parked:
            return ('Main: the Research boundary owns research work, so these nodes stay parked: ' + str(parked[:4]) +
                    '. Send the question with research_job_submit, read the published report with '
                    'research_job_result, then remove or replace the parked node (work_graph action=remove, or '
                    'action=update with a kind main can produce) before running the rest of the graph.')
        needs = [(n['id'], stage, s['artifact']['artifactId']) for n in self.all_nodes(run) for stage, s in n['stages'].items() if s['status'] == 'needs_checks' and s.get('artifact')]
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
            if git_mode(run):
                integration = run.get('integration') or {}
                if integration.get('status') == 'conflict':
                    return ('Main: the run branch has an integration conflict; repair the named node on the new base '
                            '(work_graph action=retry) or change the plan, then work_run phase=execute again.')
                pending = [n['id'] for n in run['nodes'] if n['stages'].get('execute', {}).get('status')
                           in ('pending', 'revise')]
                if pending:
                    return f'Call work_run phase=execute (pending: {", ".join(pending)}).'
                return ('Call work_check action=start with nodeId="__integration__" and the artifactId from work_graph '
                        'status to test/review the integrated run branch, then work_ship.')
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

    def lifetime(self, run, calls=0, children=0, seconds=0.0, childSeconds=0.0):
        """Bộ đếm cộng dồn của cả đời run (W6.5.2, quyết định #6457) — chỉ để đo, KHÔNG chặn.

        `work_run` đặt lại `child_budget` ở MỖI lời gọi (72 con cũ, 256 con mới) và đồng hồ
        `WORK_RUN_MAX_SECONDS` cũng đo theo từng lời gọi, nên tổng đời run có thể vượt cả hai mà
        không có lỗi nào. Bộ đếm này ghi lại số thật (số lời gọi, số con, tổng giây) vào chính
        tài liệu run để lượt sau đọc được; nó không chặn và không làm hỏng lượt chạy nào.

        `children`/`childSeconds` được đếm ở `spawn()` — cửa duy nhất sinh con của run — nên con
        của `work_check`/`work_repair` cũng vào sổ, không chỉ con trong lời gọi `work_run`
        (finding #10). `seconds` là giây của chính các lời gọi vào graph; `childSeconds` là giây
        của các con, cộng riêng để không trộn hai phép đo.
        """
        lifetime = run.setdefault('lifetime', {'calls': 0, 'children': 0, 'seconds': 0.0,
                                               'childSeconds': 0.0})
        lifetime.setdefault('childSeconds', 0.0)
        lifetime['calls'] += int(calls)
        lifetime['children'] += int(children)
        lifetime['seconds'] = round(lifetime['seconds'] + float(seconds), 3)
        lifetime['childSeconds'] = round(lifetime['childSeconds'] + float(childSeconds), 3)
        return lifetime

    async def spawn(self, session, run, node, stage, purpose, role, goal, context, expect, attempt, extra_binding=None):
        """One child through the normal `delegate` path (events, slots, budgets, UI) + full answer.

        Cửa duy nhất sinh con của run (produce/kiểm/knowledge/debug), nên đây cũng là chỗ duy nhất
        ghi sổ `lifetime`: mỗi con cộng một lượt và giây chạy thật của nó. Nhờ vậy con sinh từ
        `work_check`/`work_repair` cũng được đếm (finding #10), không chỉ con trong `work_run`.
        """
        child_started = time.monotonic()
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
        # W1.P: a disabled/missing role or revoked required tool is reported before any reservation,
        # so the producer never spends a turn and no retry is consumed.
        unavailable = work_checks.capability_preflight(self.rt.store.get(session['id']),
                                                       work_checks.producer_need(role, stage, purpose))
        if unavailable:
            raise ValueError(unavailable)
        request = self.feedback.ready(work)
        resume_id = request['childId'] if request else work.pop('resumeChildId', None)
        progress_id = await self.progress.reserve(session['id'], work, resume_id, request)
        work['progressAdmissionId'] = progress_id
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
                text = str(exc)
                # Design A4.5: child cũ không resume được (đang chạy / đã yield / hết tiến triển) thì
                # hạ cấp sang child MỚI giữ nguyên worktree, và `run_stage` ghi `repairChildReason`.
                # Trước đây lỗi này rơi xuống `run_stage` và đóng node `failed`.
                if resume_id and text.startswith('WORK_RESUME_'):
                    resume_id, request = None, None
                    work.pop('resumeChildId', None)
                    continue
                # Parallel nodes and their knowledge requests share the fan-out slots: queue, do not fail.
                if not text.startswith('FANOUT_BUSY') or time.monotonic() - waited > FANOUT_RETRY_SECONDS:
                    self.progress.finish(progress_id, interrupted=True)
                    raise
                await asyncio.sleep(FANOUT_RETRY_PAUSE)
            except BaseException:
                self.progress.finish(progress_id, interrupted=True)
                raise
        answer = self.child_answer(result.get('sessionId')) or str(result.get('summary') or '')
        receipt = self.progress.finish(progress_id, result, answer)
        result['progress'] = {k: receipt.get(k) for k in ('admissionId', 'streak', 'progressed', 'blocked')}
        if receipt.get('blocked'):
            result.update(status='partial', is_error=True, reason='WORK_NO_PROGRESS')
        self.lifetime(run, children=1, childSeconds=time.monotonic() - child_started)
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
                    extra_binding={'helperRole': item['role'], 'lookupQuestion': item['question'],
                        **({'controllerAction': controller_action} if controller_action else {})})
                reads = work_checks.good_reads(self, result.get('sessionId'))
                unsourced = claim_sources(answer, reads)
                evidenced = (work_checks.complete(result) and bool(answer.strip()) and bool(reads)
                             and not unsourced)
                proofs = [work_feedback.evidence_signature(read) or {'kind': read['name'],
                    'ref': 'search:' + work_policy.digest(read.get('args', {})),
                    'contentHash': work_policy.digest(read['result']), 'args': read.get('args', {})} for read in reads]
                binding = self.checks.binding(run, node, stage) | {'purpose': 'knowledge', 'lookupRole': item['role'],
                    'question': item['question'], 'observedEvidence': proofs,
                    'verification': 'unverified' if unsourced else 'unreviewed',
                    'execution': work_budget.receipt(result)}
                meta = await self.artifacts.put(run, node['id'], 'knowledge', answer, binding,
                                                evidenced, result.get('sessionId'))
                return item | {'childId': result.get('sessionId'), 'status': result.get('status') if evidenced else 'unverified',
                    'artifact': meta, 'execution': work_budget.receipt(result),
                    'error': ('WORK_CLAIM_UNSOURCED: ' + unsourced[0]) if unsourced else
                             None if evidenced else 'UNVERIFIED: incomplete lookup or no opened original evidence; do not rely on it'}
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

    async def run_stage(self, session, run, node, stage, max_rounds, controller_owned=False, controller_action=None,
                        repair=None):
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
        touchset = (run.get('isolation') or {}).get('mode') == 'touchset' and stage == 'execute'
        dirty_before = None
        dirty_after = None
        try:
            workspace = None
            if stage == 'execute':
                workspace = await self.ensure_workspace(run, node, session['id'])
                if touchset:
                    await self.worktrees.lock_touchset(run, node)
                    dirty_before = await self.worktrees.dirty_manifest(session['id'])
            root = (workspace or {}).get('root')
            base = (workspace or {}).get('base')
            before = await self.code_identity(run, run['sessionId'], root, base) if stage == 'execute' else None
            role, goal = self.producer_goal(run, node, stage, state.get('feedback'), [])
            context = '\n\n'.join(p for p in (self.interview_context(run), self.dependency_context(run, node, stage)) if p)
            expect = work_prompts.deliverable(node['kind'] if stage == 'produce' else role,
                                              work_prompts.language(run['goal']), node.get('taskKind'),
                                              node.get('depth'))
            repair_binding = {}
            if repair:
                # W8.A4.5: a clear red test resumes the SAME Build child in the SAME worktree.
                repair_binding['repairOf'] = repair.get('repairOf')
                if repair.get('resumeChildId'):
                    repair_binding['resumeChildId'] = repair['resumeChildId']
                if repair.get('extraArtifactIds'):
                    repair_binding['artifactIds'] = list(dict.fromkeys(repair['extraArtifactIds']))
                if repair.get('debugOnly'):
                    repair_binding['diagnosticOnly'] = True
            # W8.A4.3: every execute admission names the tree it writes in, so `reserve` can
            # snapshot the same root; repair/controller flags layer on top instead of replacing it.
            extra = ({'workspace': workspace} if workspace else {})
            if repair:
                extra.update(repair_binding)
            elif controller_action:
                extra['controllerAction'] = controller_action
            elif controller_owned:
                extra['controllerOwned'] = True
            produced, output = await self.spawn(session, run, node, stage, 'produce', role, goal, context, expect, attempt,
                extra_binding=extra or None)
            if repair:
                entry['repairOf'] = repair.get('repairOf')
                if repair.get('resumeChildId') and produced.get('sessionId') != repair['resumeChildId']:
                    entry['repairChildReason'] = 'previous child was not resumable; a fresh child kept the same worktree'
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
                        **({'workspace': workspace} if workspace else {}),
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
            commit = None
            if workspace:
                # W8.A4.3: commit the producer's work in its own worktree; the owner's checkout is untouched.
                commit = await self.worktrees.checkpoint(run, node, attempt, session['id'])
                if node['id'] == INTEGRATION_NODE:
                    integration = run.setdefault('integration', {})
                    integration.update(head=commit['nodeCommit'], treeHash=commit['treeHash'],
                                       status='pending', snapshot=None, needsTests=True, at=now())
            if touchset:
                dirty_after = await self.worktrees.dirty_manifest(session['id'])
                if dirty_after:
                    # W10: ghim phần cây nút này sở hữu để lượt kiểm sau biết mã đổi trong hay ngoài phạm vi.
                    dirty_after = dirty_after | {'declared': work_checks.declared_map(self, node, dirty_after)}
                violations = self.worktrees.touch_violations(node, dirty_before, dirty_after)
                if violations:
                    state.update(status='failed', touchViolation=violations[:20],
                                 error='WORK_TOUCHSET_VIOLATION: this run has no git repository, so it may only '
                                       'change its declared files. Outside the touch set: ' + ', '.join(violations[:8])
                                       + '. Main decides keep or revert.')
                    self.raise_issue(run, 'touchset_violation', node['id'], stage, state['error'],
                                     {'paths': violations[:20], 'allowed': self.worktrees.touch_paths(node)})
                    self.save(run, 'node_failed', node['id'])
                    return state['status']
            after = await self.code_identity(run, run['sessionId'], root, base) if stage == 'execute' else None
            if touchset and after and (dirty_after or {}).get('declared'):
                # W10: bản ghim giữ phần khai báo của nút để quyết định ghim lại/không ở lượt kiểm.
                after['declared'] = dirty_after['declared']
            # So theo schema+hash: bản ghim W10 mang thêm phần `declared` nên so cả dict sẽ luôn "đổi".
            changed = (before is not None and after is not None
                       and not work_checks.same_identity(before, after))
            declared_sensitive = any(re.search(r'api|schema|auth|migration|contract|concurr|lock', path, re.I) for path in node['files'])
            # The virtual integration node keeps its own (converged) policy after a repair.
            policy = (work_policy.integration(run) if node['id'] == INTEGRATION_NODE else
                      work_policy.derive(run, node, stage, output, changed,
                                         code_risk=stage == 'execute' and bool((after or {}).get('criticalChanges') or declared_sensitive)))
            state['policy'] = policy
            binding = self.checks.binding(run, node, stage) | {'policyHash': policy['hash']}
            if entry.get('lookupContinuation'):
                binding['lookupArtifactIds'] = lookup_refs
            if stage == 'execute':
                binding['codeSnapshot'] = after
                if commit:
                    binding['codeCommit'] = commit
                    binding['workspace'] = workspace
            finalized = work_checks.complete(produced) and bool(output.strip()) and not parse_knowledge_requests(output)
            meta = await self.artifacts.put(run, node['id'], stage, output, binding, finalized, entry['producerId'])
            state.update(artifact=meta, output=output, outputChars=len(output))
            if not finalized:
                state.update(status='failed', error=('WORK_NO_PROGRESS: inspect saved admissions and checkpoint; main must choose a new input/strategy.'
                    if (produced.get('progress') or {}).get('blocked') else
                    'WORK_PRODUCER_INCOMPLETE: partial retained; retry/update before checks.'))
                state['checkpoint'] = {'childId': entry['producerId'], 'artifactId': meta['artifactId'],
                    'execution': entry['execution'], 'remaining': 'Producer incomplete; draft is not verifiable. '
                    'Inspect reason, owner ceiling and saved draft before retrying; same-child resume is not available yet.'}
            elif entry.get('lookupContinuation') and not all(self.artifacts.covered(
                    (produced.get('work') or {}).get('inputReadId'), self.artifacts.get(run['runId'], aid)[0],
                    entry['producerId']) for aid in lookup_refs):
                state.update(status='failed', error='WORK_LOOKUP_INPUT_UNREAD: producer did not read the new assigned lookup artifacts.')
            elif stage == 'execute' and not touchset and (before is None or after is None):
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
            if isinstance(exc, PermissionError) and str(exc).startswith('RESEARCH_MAIN_READ_ONLY'):
                # #6599: the Research boundary owns research work; main submits through the envelope and
                # brings the published report back. This is a decision for the owner, not a failed node.
                state.update(status='needs_user', error='RESEARCH_NEEDS_MAIN: the independent Research boundary '
                             'executes research work, so main cannot produce this node. Send the question with '
                             'research_job_submit, read the published report with research_job_result, then remove or '
                             'replace this node (work_graph action=remove, or action=update with a kind main can '
                             'produce) before running the rest of the graph.')
            else:
                state.update(status='failed', error=str(exc)[:500])
        finally:
            if touchset:
                self.worktrees.release_touchset(run, node)
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
            await self.ensure_isolation(session, run, args)
            # W8.A4.4: hợp nhất nốt những nút đã nghiệm thu ở lượt trước TRƯỚC khi so cây —
            # nếu không, một nút vừa được duyệt sẽ bị coi là "cây đã đổi" ngay lượt sau.
            if git_mode(run) and await self.integrate_nodes(session, run):
                await self.build_integration(session, run)
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
            self.lifetime(run, calls=1)
            limit = max(1, int(self.rt.fanout_limit(session.get('config'))))
            try:
                with self.budget_paused(sid):
                    return await self.schedule_nodes(session, run, stage, max_rounds, only, limit)
            finally:
                self.child_budget.pop(run['runId'], None)
                self.live.pop(run['runId'], None)

    async def ensure_workspace(self, run, node, sid):
        """`{root, branch, base}` for this node, or None when the run is not git-isolated."""
        if not git_mode(run):
            return None
        workspace = await self.worktrees.ensure_node(run, node, sid)
        await self.worktrees.recover_merges(run, sid)
        return workspace

    def require_execution(self, run):
        if not run.get('executionRequested'):
            raise ValueError('WORK_REQUIREMENTS_ONLY: owner requested an artifact, not code execution; Autopilot cannot expand scope.')

    async def code_identity(self, run, sid, root=None, base=None):
        """W8.A4.3: a touch-set run is identified by the shared dirty manifest, a git run by its
        scoped worktree snapshot. A workspace that answers neither yields None; the caller decides
        (`run_stage` keeps going, an execution admission refuses)."""
        # W10: một đầu đọc duy nhất (`work_checks.identity_of`) để bản ghim và mọi cổng so sánh
        # luôn cùng schema — trước đây binding `work-dirty/1` bị đem so với ảnh chụp git.
        return await work_checks.identity_of(self, sid, None, (run.get('isolation') or {}).get('mode'),
                                             root=root, base=base)

    async def rebind_artifact(self, run, node, stage, meta, current, trail):
        """W10 quyết định A: ghim lại bản nháp vào cây hiện tại khi mã chỉ đổi NGOÀI file của nút.

        Bản nháp, policy và lịch sử được giữ; vết `codeRebound` nằm ngay trên artifact nên người
        duyệt sau thấy được vì sao hash đổi. Không có đường này thì nút đứng mãi ở `needs_checks`.
        """
        state = node['stages'][stage]
        binding = meta.setdefault('binding', {})
        binding['codeSnapshot'] = current
        binding['codeRebound'] = trail
        self.artifacts.update(meta)
        if (state.get('artifact') or {}).get('artifactId') == meta.get('artifactId'):
            state['artifact'] = meta
        self.save(run, 'artifact_rebound',
                  f'{node["id"]}:{stage} {str(trail.get("from"))[:12]}→{str(trail.get("to"))[:12]}')

    def stage_needs_rebuild(self, run, node, stage, moved):
        """W10: mã đổi ĐÚNG vào file nút khai báo ⇒ trả stage về sản xuất, giữ lịch sử vòng.

        Không xoá gì: artifact cũ vẫn đọc được trong registry, `rounds` còn nguyên. Chỉ trạng thái
        đổi để `work_run phase=execute` dựng bản nháp mới trên cây hiện tại.
        """
        state = node['stages'][stage]
        state.update(status='pending', codeMoved=sorted(moved or [])[:20] or ['<unmeasurable>'],
                     error='WORK_CHECK_CODE_MOVED: the tree moved inside this node\'s declared files; '
                           'produce a fresh draft on the current code (work_run phase=execute).')
        self.save(run, 'code_moved', f'{node["id"]}:{stage} ' + ', '.join(state['codeMoved'][:6]))

    async def ensure_isolation(self, session, run, args):
        """W8.A4.3: resolve the repository and create the run worktree once per execution run."""
        try:
            isolation = await self.worktrees.ensure_run(run, args, session['id'])
        except IsolationError as exc:
            message = str(exc)
            if message.startswith('WORK_REPO_AMBIGUOUS'):
                self.raise_issue(run, 'repo_ambiguous', None, 'execute', message,
                                 {'repoPath': args.get('repoPath'), 'next': 'work_run phase=execute repoPath=...'})
                self.save(run, 'repo_ambiguous')
            raise
        if isolation.get('mode') == 'git' and (isolation.get('userDirty') or {}).get('count'):
            self.save(run, 'owner_changes_outside_run',
                      f'{isolation["userDirty"]["count"]} uncommitted owner file(s) stay outside this run')
        return isolation

    def require_planning_current(self, run):
        producers = [n for n in run['nodes'] if 'produce' in n['stages']]
        if producers and (any(n['stages']['produce']['status'] != 'accepted'
                              or not self.checks.valid(run, n, 'produce') for n in producers)
                          or (run.get('review') or {}).get('binding') != self.whole_binding(run)
                          or (run.get('review') or {}).get('status') != 'ok'):
            raise ValueError('WORK_NOT_VERIFIED: owner decisions, artifacts or graph checks are stale/missing')

    async def require_code_current(self, run):
        if git_mode(run):
            # W8.A4.4: the run branch, not the owner's checkout, is what checks are bound to.
            integration = run.setdefault('integration', {'nodes': {}, 'checkIds': []})
            for node in run['nodes']:
                state = node['stages'].get('execute', {})
                if state.get('status') != 'accepted':
                    continue
                commit = ((state.get('artifact') or {}).get('binding', {}).get('codeCommit') or {}).get('nodeCommit')
                if not commit or integration.get('nodes', {}).get(node['id']) != commit:
                    integration.update(status='stale', snapshot=None, at=now())
                    raise ValueError('WORK_CODE_STALE: an accepted node is not integrated into the run branch; '
                                     'call work_run phase=execute to finish integration, then re-check.')
            if not integration.get('snapshot'):
                return
            current = await self.worktrees.integration_snapshot(run, run['sessionId'])
            if (not current.get('hash') or current['hash'] != integration['snapshot'].get('hash')
                    or current.get('treeHash') != integration.get('treeHash')):
                integration.update(status='stale', at=now())
                self.save(run, 'code_checks_stale', 'integration')
                raise ValueError('WORK_CODE_STALE: the run branch changed after its checks; re-run the '
                                 'integration check before execute/ship.')
            return
        current = None
        mode = (run.get('isolation') or {}).get('mode')
        for node in run['nodes']:
            state = node['stages'].get('execute', {})
            if state.get('status') == 'accepted':
                if current is None:
                    current = await work_checks.identity_of(self, run['sessionId'], None, mode)
                expected = state.get('artifact', {}).get('binding', {}).get('codeSnapshot')
                if not current or not work_checks.same_identity(expected, current) \
                        or not self.checks.valid(run, node, 'execute'):
                    state.update(status='revise', feedback='Integrated source changed: preserve valid changes, inspect current code and produce a fresh handoff for testing.',
                                 error='WORK_CODE_STALE: re-produce/re-test the current integrated snapshot.')
                    run['status'] = 'approved'
                    self.save(run, 'code_checks_stale', node['id'])
                    raise ValueError('WORK_CODE_STALE: code or required checks changed; no execute/ship until rechecked.')

    def approve_by_autopilot(self, run):
        self.require_execution(run)
        run['approval'] = {'status': 'approved', 'by': 'autopilot', 'at': now()}
        run['status'] = 'approved'
        self.set_repair_default(run)

    def set_repair_default(self, run):
        """W8.A4.5: the bounded repair policy is fixed at approval, not by a red test."""
        if not run.get('repairPolicy'):
            run['repairPolicy'] = work_repair.default_policy(MAX_ROUNDS_DEFAULT, 'default')

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

    def touchset_busy(self, run, node, stage, running):
        """W8.A4.3 fallback: without git, overlapping declared files run one after another."""
        if stage != 'execute' or (run.get('isolation') or {}).get('mode') != 'touchset':
            return False
        mine = self.worktrees.touch_paths(node)
        if not mine:
            return False
        for other in running:
            theirs = self.worktrees.touch_paths(next(n for n in run['nodes'] if n['id'] == other))
            if any(a == b or a.startswith(b + '/') or b.startswith(a + '/') for a in mine for b in theirs):
                return True
        return False

    async def integrate_nodes(self, session, run):
        """W8.A4.4: merge every accepted execute node into the run branch under one lock."""
        changed = False
        for node in run['nodes']:
            state = node['stages'].get('execute', {})
            if state.get('status') != 'accepted':
                continue
            commit = ((state.get('artifact') or {}).get('binding', {}).get('codeCommit') or {}).get('nodeCommit')
            if not commit or (run.get('integration') or {}).get('nodes', {}).get(node['id']) == commit:
                continue
            try:
                await self.worktrees.integrate(run, node, session['id'])
                changed = True
            except IsolationError as exc:
                state.update(status='integration_conflict', error=str(exc)[:500])
                self.raise_issue(run, 'integration_conflict', node['id'], 'execute', str(exc),
                                 {'paths': self.worktrees.touch_paths(node),
                                  'next': 'repair the node on the new run-branch base (work_graph action=retry) '
                                          'or change the plan'})
                self.save(run, 'integration_conflict', node['id'])
        return changed

    async def integration_artifact(self, run, snapshot, policy, session):
        """W8.A4.5: the artifact the converged gate reviews must publish the tree it claims.

        The review child is read-only (no terminal) and the run worktree sits under a git-excluded
        path, so a reviewer cannot re-run the tests or browse the merged files by itself. The
        producer therefore publishes the identity of the merged tree, the files this run owns, the
        diff stat, and the verbatim output of every required test command. Best effort: a blocked or
        failing command is reported exactly as it came back instead of failing the integration.
        """
        sid = session.get('id')
        lines = ['Integrated run branch ' + str(snapshot['head'])[:12] + ' (tree ' + str(snapshot['treeHash'])[:12] + ')',
                 '', '### Merged tree identity', '',
                 f"- run branch: `{snapshot['branch']}`", f"- head: `{snapshot['head']}`",
                 f"- tree: `{snapshot['treeHash']}`", f"- worktree: `{snapshot['worktree']}`"]
        owned = await self.worktrees.owned_paths(run, sid)
        lines.append('- files owned by this run: ' + (', '.join(f'`{path}`' for path in owned) if owned else '(none)'))
        stat, _ = await self.worktrees.diff_text(run, sid)
        if stat.strip():
            lines += ['', '### Diff stat', '', '```', stat.strip()[-3000:], '```']
        for command in [str(item).strip() for item in (policy.get('tests') or []) if str(item).strip()]:
            proof = f'cd {snapshot["worktree"]} && {command} 2>&1; echo "EXIT=$?"'
            ok, out = await self.worktrees.sh(sid, proof, 900)
            code = out.rsplit('EXIT=', 1)[-1].strip() if 'EXIT=' in out else 'unknown'
            lines += ['', f'### Verbatim test evidence — `{command}`', '',
                      f'`{proof}` → exit `{code}` (executor ok={ok})', '', '```', out[-4000:], '```']
        return '\n'.join(lines)

    async def build_integration(self, session, run):
        """W8.A4.4/A4.5: one converged check on the merged run branch before `executed`."""
        integration = run.setdefault('integration', {'nodes': {}, 'checkIds': []})
        stages = [n['stages']['execute'] for n in run['nodes'] if 'execute' in n['stages']]
        if not stages or not all(s['status'] == 'accepted' for s in stages):
            return False
        node = self.integration_node(run)
        state = node['stages']['execute']
        if state.get('status') in ('accepted', 'needs_checks', 'revise'):
            return False
        snapshot = await self.worktrees.integration_snapshot(run, session['id'])
        if not snapshot.get('hash') or not snapshot.get('treeHash'):
            state.update(status='failed', error='WORK_CODE_SNAPSHOT_REQUIRED: cannot read the integrated run branch')
            return False
        policy = work_policy.integration(run)
        binding = self.checks.binding(run, node, 'execute') | {'policyHash': policy['hash'],
            'codeSnapshot': snapshot['snapshot'],
            'workspace': {'root': snapshot['worktree'], 'branch': snapshot['branch'],
                          'base': run['isolation']['baselineCommit']}}
        meta = await self.artifacts.put(run, INTEGRATION_NODE, 'execute',
            await self.integration_artifact(run, snapshot, policy, session), binding, True, None)
        state.update(status='needs_checks' if policy['required'] else 'accepted', attempts=max(1, state['attempts']),
                     artifact=meta, policy=policy, rounds=state.get('rounds') or [{'attempt': 1, 'producerRole': 'build',
                     'at': now(), 'knowledge': [], 'producerId': None}],
                     output='', outputChars=0, error=None, startedAt=state.get('startedAt') or now())
        integration.update(status='checking' if policy['required'] else 'checked', head=snapshot['head'],
                           treeHash=snapshot['treeHash'], snapshot=snapshot['snapshot'], at=now())
        self.save(run, 'integration_ready', str(snapshot['treeHash'])[:12])
        return True

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
                        if stage == 'execute' and git_mode(run) and node['stages'][stage]['status'] == 'revise' \
                                and node['stages'][stage].get('repairs'):
                            continue  # W8.A4.5: a routed repair already owns the next round.
                        if self.touchset_busy(run, node, stage, running):
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
            if git_mode(run):
                await self.integrate_nodes(session, run)
                await self.build_integration(session, run)
            if all(value == 'accepted' for value in statuses.values()):
                run['status'] = self.execute_status(run) or 'approved'
            elif any(value in ('rejected', 'failed', 'integration_conflict') for value in statuses.values()):
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
        # W6.5.2 (#6457): bộ đếm CỘNG DỒN toàn đời run. Chỉ báo cáo — không chặn gì; số thật ở
        # đây là đầu vào để chốt một trần cứng sau (plan cấm tự chọn trần mới khi chưa đo).
        # `children`/`childSeconds` do `spawn()` cộng (finding #10), nên không cộng lại ở đây.
        out['lifetime'] = dict(self.lifetime(run, seconds=time.monotonic() - started))
        self.save(run, 'run_lifetime', json.dumps(out['lifetime'])[:300])
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

    def reviewed_set(self, run):
        """W6.2.BIND — tài liệu đã được whole-pass chứng nhận, kèm hash tại thời điểm đó.

        `claims` là TẬP TOKEN kỹ thuật của đúng bộ tài liệu đã phản biện, không phải bản chứng
        nhận ngữ nghĩa/đơn vị/phiên bản: badge chỉ nói "token này có mặt trong tài liệu đã kiểm".
        Chạm trần `CLAIM_TOKENS_MAX` thì ghi `claimsTotal`/`claimsTruncated` để lượt đọc sau biết
        tập đã bị cắt (#6474) — trước đây cắt im lặng ở 600.
        """
        produce = [n for n in run['nodes'] if 'produce' in n['stages']]
        artifacts, claims = [], set()
        for node in produce:
            meta = node['stages']['produce'].get('artifact')
            if not meta:
                continue
            artifacts.append({'artifactId': meta['artifactId'], 'contentHash': meta['contentHash']})
            try:
                _, text = self.artifacts.get(run['runId'], meta['artifactId'])
            except (KeyError, ValueError, TypeError):
                continue
            claims |= {norm_claim(token) for token in claim_tokens(text)}
        # `claims` là token kỹ thuật của đúng bộ tài liệu đã phản biện: `final_claims_check` là hàm
        # thuần, không đọc DB ở cuối lượt main (W6.2.BIND).
        return {'wholeBinding': self.whole_binding(run), 'artifacts': artifacts,
                'claims': sorted(claims)[:CLAIM_TOKENS_MAX], 'claimsTotal': len(claims),
                'claimsTruncated': len(claims) > CLAIM_TOKENS_MAX,
                'reviewedAt': now(), 'verdict': 'ok'}

    def stale_review(self, run):
        """True when the reviewed set no longer matches the live graph or a reviewed artifact changed."""
        reviewed = run.get('reviewedSet')
        if not reviewed:
            return False
        if reviewed.get('wholeBinding') != self.whole_binding(run):
            return True
        for item in reviewed.get('artifacts') or []:
            try:
                meta, _ = self.artifacts.get(run['runId'], item['artifactId'])
            except (KeyError, ValueError, TypeError):
                return True
            if meta.get('contentHash') != item.get('contentHash') or meta.get('status') != 'finalized':
                return True
        return False

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
            run['reviewedSet'] = self.reviewed_set(run)
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
            self.set_repair_default(run)
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
        if git_mode(run):
            return await self.ship_isolated(session, run, args)
        return await self.ship_legacy(session, run, args)

    async def ship_isolated(self, session, run, args):
        """W8.A4.4: push the run branch only. The owner's checkout and dirty files are never touched."""
        sid, iso = session['id'], run['isolation']
        integration = run.get('integration') or {}
        if integration.get('status') != 'checked':
            raise ValueError('WORK_SHIP_STALE: the integrated run branch has no passing check yet; call work_check '
                             'action=start with nodeId="__integration__" first')
        branch = str(args.get('branch') or iso['branch']).strip()
        if not re.fullmatch(r'[A-Za-z0-9._/-]{1,100}', branch) or '..' in branch or branch.startswith('-'):
            raise ValueError('WORK_BRANCH_INVALID: branch may use letters, digits, ., _, / and - only')
        title = str(args.get('title') or run['title']).strip()[:120]
        # W8.A4.4: danh sách tệp thuộc run phải có TRƯỚC khi dựng thân PR (nó nằm trong thân).
        owned = await self.worktrees.owned_paths(run, sid)
        body = str(args.get('body') or '').strip() or self.pr_body(run, owned)
        doc = await self.write_document(sid, run, 'pull-request', f'# {title}\n\n{body}\n', f'PR — {title}')
        steps = []

        async def sh(command, timeout=180):
            result = await self.rt.executor.execute('terminal_exec', {'command': command, 'timeout': timeout}, sid)
            text = str((result or {}).get('content') or (result or {}).get('output') or '')
            code = (result or {}).get('exitCode', (result or {}).get('exit_code'))
            failed = bool((result or {}).get('is_error')) or (code not in (None, 0))
            steps.append({'command': command.split(' && ')[0][:160], 'ok': not failed, 'output': text[-600:]})
            return not failed, text

        def not_shipped(status, message, extra=None):
            run['ship'] = {'status': status, 'branch': branch, 'prFile': doc['path'], 'steps': steps,
                           'worktree': iso['root'], 'treeHash': integration.get('treeHash'), 'at': now()} | (extra or {})
            self.save(run, 'ship_' + status)
            return self.result(run, message) | {'ship': run['ship']}

        ok, dirty = await self.worktrees.git(sid, iso['root'], 'status --porcelain=v1 --untracked-files=all')
        # Bỏ qua đúng loại rác mà `snapshot()` bỏ qua: lượt chạy nào chạy test cũng để lại
        # `__pycache__/`/`.pytest_cache/`, nếu tính là bẩn thì không run nào ship được.
        dirty = '\n'.join(line for line in dirty.splitlines() if line and not work_worktrees.junk(line))
        if not ok or dirty:
            return not_shipped('worktree_dirty', 'The run worktree has uncommitted changes; ship would not match the '
                                                 'checked tree. Run work_run phase=execute (or clean it) and re-check.',
                               {'dirty': dirty.splitlines()[:20]})
        current = await self.worktrees.integration_snapshot(run, sid)
        if (not current.get('treeHash') or current['treeHash'] != integration.get('treeHash')
                or current.get('hash') != (integration.get('snapshot') or {}).get('hash')):
            raise ValueError('WORK_SHIP_STALE: the run branch no longer matches the checked snapshot; re-run the '
                             'integration check before shipping.')
        key = f'ship-{run["runId"]}-{integration["treeHash"]}'
        record = self.worktrees.ship_record(key)
        if record and record['status'] == 'done' and record.get('result'):
            run['ship'] = record['result']
            run['status'] = 'shipped'
            self.save(run, 'shipped', 'idempotent')
            return self.result(run, 'Shipped (already done for this tree): ' + run['ship']['status']) | {'ship': run['ship']}
        if record and record['status'] == 'started':
            raise ValueError('WORK_SHIP_IN_PROGRESS: another work_ship call owns this exact tree; read work_graph '
                             'status for its result instead of shipping twice')
        claim = {'branch': branch, 'head': current.get('head'), 'treeHash': integration['treeHash'],
                 'ownedPaths': owned, 'pushed': False, 'prUrl': None, 'steps': [], 'startedAt': now()}
        if not self.worktrees.ship_claim(key, run['runId'], claim):
            raise ValueError('WORK_SHIP_IN_PROGRESS: another work_ship call owns this exact tree; read work_graph '
                             'status for its result instead of shipping twice')
        pushed, pr_url, sha = False, None, str(current.get('head'))[:12]
        async with self.rt.writer_lock:
            # An interrupted ship may already have pushed or opened the PR: never repeat those steps.
            has_remote, _ = await sh(f"git -C '{iso['root']}' remote get-url origin")
            if has_remote and args.get('push', True):
                _, remote_ref = await sh(f"git -C '{iso['root']}' ls-remote origin refs/heads/{branch}")
                already = str(current.get('head')) in remote_ref
                if already:
                    pushed = True
                else:
                    pushed, out = await sh(f"GIT_TERMINAL_PROMPT=0 git -C '{iso['root']}' push -u origin "
                                           f"HEAD:refs/heads/{branch}")
                    if not pushed:
                        self.worktrees.ship_finish(key, 'failed', claim | {'steps': steps, 'finishedAt': now()})
                        return not_shipped('push_failed', 'git push failed; read ship.steps, fix the remote or the '
                                                          'branch, and call work_ship again.', {'pushed': False})
                has_gh, _ = await sh('command -v gh && gh auth status')
                if has_gh:
                    existing, out = await sh(f"gh pr view '{branch}' --json url --jq .url")
                    match = re.search(r'https://\S+/pull/\d+', out)
                    if existing and match:
                        pr_url = match.group(0)
                    else:
                        created, out = await sh(f"gh pr create --draft --title '{title.replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}' "
                                                f"--body-file '{doc['path']}' --head '{branch}' "
                                                f"--base '{iso.get('baselineBranch') or 'HEAD'}'")
                        match = re.search(r'https://\S+/pull/\d+', out)
                        pr_url = match.group(0) if created and match else None
        run['ship'] = {'status': 'pr_opened' if pr_url else ('pushed' if pushed else 'local'),
                       'branch': branch, 'commit': sha, 'pushed': pushed, 'prUrl': pr_url, 'prFile': doc['path'],
                       'ownedPaths': owned, 'treeHash': integration['treeHash'], 'shipKey': key,
                       'worktree': iso['root'], 'steps': steps, 'at': now()}
        run['status'] = 'shipped'
        self.worktrees.ship_finish(key, 'done', claim | {'result': run['ship'], 'steps': steps, 'finishedAt': now()})
        self.save(run, 'shipped', run['ship']['status'])
        return self.result(run, 'Shipped: ' + run['ship']['status']) | {'ship': run['ship']}

    async def ship_legacy(self, session, run, args):
        """Pre-isolation runs (and touch-set runs) keep the shared checkout, with an explicit path scope."""
        sid = session['id']
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
        # A legacy run shares the owner's checkout: it must name the paths it owns (no `-A`, no globs).
        legacy = (run.get('isolation') or {}).get('mode') == 'legacy'
        paths = [str(p).strip().strip('/') for p in (args.get('paths') or []) if str(p).strip().strip('/')]
        if legacy and not paths:
            raise ValueError('WORK_SHIP_LEGACY_SCOPE_REQUIRED: this run was created before worktree isolation, so '
                             'its changes live in the shared checkout. Call work_ship with paths=[the files this '
                             'run owns] (relative, no globs) so unrelated owner changes are never committed.')
        for path in paths:
            if path.startswith('/') or '..' in path.split('/') or any(c in path for c in '*?['):
                raise ValueError('WORK_SHIP_LEGACY_SCOPE_REQUIRED: paths must be relative files without globs')
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
            ok, _ = await sh("git add -- " + ' '.join("'" + path + "'" for path in paths) if legacy
                             else "git add -A -- . ':(exclude).plans/work'")
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

    def pr_body(self, run, owned=None):
        lines = ['## Summary', '', run['goal'], '', '## Work Graph', '']
        for node in run['nodes']:
            stage = node['stages'].get('execute') or node['stages'].get('produce')
            verdicts = ' → '.join(item.get('verdict') or '?' for item in stage['rounds']) or 'not run'
            lines.append(f'- **{node["id"]}** ({node["kind"]}) {node["title"]} — `{stage["status"]}` ({verdicts})')
        iso = run.get('isolation') or {}
        if iso.get('mode') == 'git':
            lines += ['', '## Branch', '', f'- Branch: `{iso.get("branch")}` from `{iso.get("baselineBranch")}` '
                      f'({str(iso.get("baselineCommit"))[:12]})', f'- Worktree: `{iso.get("root")}`',
                      '- The owner\'s uncommitted changes are not part of this branch.']
            owned = owned if owned is not None else (run.get('ship') or {}).get('ownedPaths')
            if owned:
                lines += ['', '## Files owned by this run', ''] + [f'- `{path}`' for path in owned[:200]]
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
                                          'create a run. Otherwise do NOT build research nodes — main cannot produce them, '
                                          'because the independent Research boundary owns research work: build explore nodes when '
                                          'the repository matters, submit the questions with research_job_submit and wait for '
                                          'the owner consent; read the published report with research_job_result and answer '
                                          'with the verified findings.',
                             'design': 'Explore the current UI/code, build design nodes, run them with review, '
                                       'verify, and present the verified design.'}.get(flow, ''))
            lines.append(f'Owner request: {bounded(intent.get("text"), 1500)}')
        if run is not None:
            counts = {}
            for node in self.all_nodes(run):
                for name, state in node['stages'].items():
                    counts[state['status']] = counts.get(state['status'], 0) + 1
            lines.append(f'Active run {run["runId"]} "{run["title"]}" flow={run["flow"]} status={run["status"]} '
                         f'nodes={len(run["nodes"])} stages={json.dumps(counts, ensure_ascii=False)} '
                         f'autopilot={"on" if autopilot_on(session) else "off"}.')
            iso = run.get('isolation') or {}
            if iso.get('mode') == 'git':
                lines.append(f'Isolation: this run builds in branch `{iso["branch"]}` at worktree `{iso["root"]}`. '
                             'Paths in assignments and tests are relative to the repository root (`'
                             f'{iso.get("repoPath") or "."}`), never to the owner checkout. Commit/push is done by '
                             'the harness; do not run git add/commit in the owner checkout.')
                if (iso.get('userDirty') or {}).get('count'):
                    lines.append(f'The owner has {iso["userDirty"]["count"]} uncommitted file(s): your uncommitted '
                                 'changes are not part of this run, and the run never commits them.')
            elif iso.get('mode') == 'touchset':
                lines.append('Isolation: no git repository in the workspace, so this run writes to the shared '
                             'workspace and may only change the files its nodes declare.')
            lines.append('Next: ' + self.next_step(run))
            if run['status'] in DRIVING_STATUSES:
                lines.append('Keep this turn going: make the next tool call now. End the turn only for an '
                             'interview, the approval card, or the final answer.')
        if len(lines) == 1:
            return ''
        lines.append(END_MARKER)
        return '\n'.join(lines)
