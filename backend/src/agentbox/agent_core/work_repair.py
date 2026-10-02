"""W8.A4.5: conditional repair after a red check, and the converged-review gate.

A red test on an isolated run is not an automatic blind re-run. The harness classifies it:
a *clear* failure (a required command really exited non-zero with a traceback/assertion
pointing at a file in the node worktree) resumes the SAME Build child with the findings;
an *unclassified* one first gets a read-only Debug diagnosis whose opened evidence is
handed to Build. After `maxRepairs` the node stops and main gets a decision (c). The
retest reuses the previous tester through `Checks.retest_candidate`.

Legacy runs (no isolation record) keep the old auto-revise loop in `work_run`.
"""
import json
import re
import time

from . import work_checks, work_prompts, work_worktrees

DEBUG_MODES = ('never', 'when_unclassified', 'always_first')
DEFAULT = {'maxRepairs': 2, 'debug': 'when_unclassified', 'source': 'default', 'revision': 1}
TRACE_RE = re.compile(r'Traceback \(most recent call last\)|AssertionError|assert |FAILED |Error:|error TS\d+', re.I)
PATH_RE = re.compile(r'File "([^"]+)", line \d+|(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.(?:py|js|ts|tsx|jsx|mjs|go|rs|rb|java)):\d+')


def routed(run):
    """Repair routing needs a node worktree to classify and repair in (W8.A4.3 git mode).

    Touch-set and legacy runs keep the previous auto-revise loop in `work_run`: without a
    worktree there is no isolated tree to point the findings at.
    """
    return work_worktrees.git_mode(run)


def default_policy(max_rounds=3, source='default'):
    return DEFAULT | {'maxRepairs': max(0, min(DEFAULT['maxRepairs'], int(max_rounds) - 1)), 'source': source}


def policy(run):
    return run.get('repairPolicy') or default_policy()


def set_policy(run, args, max_rounds=3):
    """`work_graph action=set_repair`: root only (caller), CAS on revision, idempotent per invocation."""
    current = policy(run)
    invocation = str(args.get('invocationId') or '').strip()
    if not 1 <= len(invocation) <= 120:
        raise ValueError('WORK_REPAIR_POLICY_INVALID: unique invocationId required (1..120 chars)')
    if invocation in current.get('invocations', []):
        return current
    if args.get('revision') != current['revision']:
        raise ValueError(f'WORK_REPAIR_POLICY_STALE: current revision is {current["revision"]}')
    debug = args.get('debug', current['debug'])
    if debug not in DEBUG_MODES:
        raise ValueError('WORK_REPAIR_POLICY_INVALID: debug must be one of ' + ', '.join(DEBUG_MODES))
    limit = args.get('maxRepairs', current['maxRepairs'])
    if not isinstance(limit, int) or isinstance(limit, bool) or not 0 <= limit <= max(0, int(max_rounds) - 1):
        raise ValueError(f'WORK_REPAIR_POLICY_INVALID: maxRepairs must be an integer 0..{max(0, int(max_rounds) - 1)}'
                         ' (maxRounds-1)')
    updated = {'maxRepairs': limit, 'debug': debug, 'source': 'main', 'revision': current['revision'] + 1,
               'invocations': (current.get('invocations', []) + [invocation])[-20:]}
    node_id = args.get('nodeId')
    if node_id:
        if not any(n['id'] == node_id for n in run['nodes']):
            raise ValueError('WORK_NODE_UNKNOWN: node not in run')
        updated = current | {'revision': current['revision'] + 1, 'source': 'main',
                             'invocations': updated['invocations'],
                             'nodes': current.get('nodes', {}) | {node_id: {'maxRepairs': limit, 'debug': debug}}}
    run['repairPolicy'] = updated
    return updated


def node_policy(run, node):
    pol = policy(run)
    return pol | pol.get('nodes', {}).get(node['id'], {})


def repairs_used(state):
    return len(state.get('repairs') or [])


def adjudicate(doc, coverage, observations):
    """Hook for W6 (`validate_findings`): downgrade uncited blocking findings. Identity for now."""
    return doc


def failing_runs(graph, doc, tests):
    calls = [o for o in work_checks.observations(graph, doc.get('childId'), after=doc.get('admissionSeq'))
             if o.get('name') == 'terminal_exec']
    wanted = {str(t).strip() for t in tests or []}
    red = []
    for item in calls:
        result = item.get('result') or {}
        code = result.get('exit_code', result.get('exitCode'))
        command = str((item.get('args') or {}).get('command') or '').strip()
        if command in wanted and (result.get('is_error') or code not in (0, None)):
            red.append({'command': command, 'exitCode': code,
                        'output': str(result.get('content') or result.get('output') or '')[-4000:]})
    return red


async def classify(graph, run, node, doc, root, sid):
    """`clear` only with a real red required command whose trace points into the node worktree."""
    if doc.get('kind') == 'code_review':
        return 'clear', {'reason': 'blocking review findings name the defect'}
    red = failing_runs(graph, doc, node.get('tests'))
    if not red:
        return 'unclassified', {'reason': 'no failing required command event'}
    candidates = []
    for item in red:
        if not TRACE_RE.search(item['output']):
            continue
        for match in PATH_RE.finditer(item['output']):
            raw = (match.group(1) or match.group(2) or '').strip()
            if root and '/' + root + '/' in raw:
                raw = raw.split('/' + root + '/', 1)[1]
            raw = raw.lstrip('./')
            if raw and not raw.startswith('/') and '..' not in raw.split('/'):
                candidates.append(raw)
    candidates = list(dict.fromkeys(candidates))[:20]
    if not candidates or not root:
        return 'unclassified', {'reason': 'failure output has no traceback into the worktree', 'red': red[:2]}
    from .work_worktrees import q
    ok, out = await graph.worktrees.sh(sid, f'cd {q(root)} && git ls-files -- ' + ' '.join(q(p) for p in candidates))
    tracked = [line for line in out.splitlines() if line] if ok else []
    if tracked:
        return 'clear', {'reason': 'required command failed with a trace into tracked files', 'paths': tracked[:8],
                         'red': red[:2]}
    return 'unclassified', {'reason': 'trace paths are not files of the node worktree', 'red': red[:2]}


def findings_text(run, node, docs, detail, debug=None):
    lang = work_prompts.language(run['goal'])
    pick = lambda en, vi: work_prompts.choose(lang, en, vi)
    lines = [pick(f'# Repair input for {node["id"]}', f'# Đầu vào sửa cho {node["id"]}'), '']
    for doc in docs:
        lines += [f'## {doc.get("kind")} ({doc.get("checkId")})', '', str(doc.get('findings') or '')[:6000], '']
    for item in detail.get('red', []):
        lines += [pick('## Failing command', '## Lệnh đỏ'), '', f'`{item["command"]}` exit {item["exitCode"]}', '',
                  '```', item['output'][-3000:], '```', '']
    if debug:
        lines += [pick('## Debug diagnosis (read-only)', '## Chẩn đoán Debug (chỉ đọc)'), '', debug[:6000], '']
    return '\n'.join(lines)


async def route(graph, session, run, node, docs, max_rounds):
    """Choose the next repair step for a red execute node on an isolated run."""
    state = node['stages']['execute']
    pol = node_policy(run, node)
    used = repairs_used(state)
    red = [d for d in docs if d.get('status') == 'revise']
    check_id = red[-1]['checkId'] if red else None
    if used >= pol['maxRepairs'] or not red:
        state.update(status='rejected', error=f'WORK_REPAIR_LIMIT: {used}/{pol["maxRepairs"]} repairs used; main decides')
        graph.raise_issue(run, 'repair_decision_required', node['id'], 'execute', state['error'],
                          {'checkIds': [d['checkId'] for d in red], 'repairs': state.get('repairs', [])})
        return {'action': 'main', 'reason': 'WORK_REPAIR_LIMIT'}
    root, _ = graph.worktrees.code_root(run, node)
    cls, detail = await classify(graph, run, node, red[-1], root, session['id'])
    debug_first = pol['debug'] == 'always_first' or (cls == 'unclassified' and pol['debug'] == 'when_unclassified')
    entry = {'n': used + 1, 'checkId': check_id, 'class': cls, 'reason': detail.get('reason'),
             'debugChildId': None, 'debugArtifactId': None, 'buildChildId': None, 'resumed': None,
             'codeHash': None, 'at': time.time()}
    state.setdefault('repairs', []).append(entry)
    binding = graph.checks.binding(run, node, 'execute')
    workspace = graph.workspace_of(run, node)
    debug_text = None
    if debug_first:
        lang = work_prompts.language(run['goal'])
        goal = work_prompts.choose(lang,
            f'Work Graph repair diagnosis for node {node["id"]}: find the root cause of the failing check. '
            'Read code and run read-only commands only; do NOT edit files. Cite the files/lines you opened.',
            f'Chẩn đoán sửa lỗi Work Graph cho nút {node["id"]}: tìm nguyên nhân gốc của check đỏ. '
            'Chỉ đọc mã và chạy lệnh chỉ đọc; KHÔNG sửa tệp. Ghi tệp/dòng đã mở.') + '\n\n' + findings_text(run, node, red, detail)
        result, text = await graph.spawn(session, run, node, 'execute', 'produce', 'debug', goal,
                                         graph.dependency_context(run, node, 'execute'), None, state['attempts'],
                                         extra_binding={'diagnosticOnly': True, 'repairDebug': True,
                                                        'repairOf': check_id, 'workspace': workspace})
        child = result.get('sessionId')
        if not work_checks.complete(result) or not work_checks.good_reads(graph, child):
            state.update(status='rejected', error='WORK_REPAIR_UNDIAGNOSED: Debug opened no evidence; main decides')
            entry['debugChildId'] = child
            graph.raise_issue(run, 'repair_decision_required', node['id'], 'execute', state['error'],
                              {'checkIds': [check_id], 'debugChildId': child})
            return {'action': 'main', 'reason': 'WORK_REPAIR_UNDIAGNOSED'}
        debug_text = text
        entry['debugChildId'] = child
    note = await graph.artifacts.put(run, node['id'], 'execute', findings_text(run, node, red, detail, debug_text),
                                     binding | {'purpose': 'repair_findings', 'repairOf': check_id}, True, None)
    entry['findingsArtifactId'] = note['artifactId']
    if debug_text:
        entry['debugArtifactId'] = note['artifactId']
    last = next((r.get('producerId') for r in reversed(state.get('rounds') or []) if r.get('producerId')), None)
    status = await graph.run_stage(session, run, node, 'execute', max_rounds,
                                   repair={'resumeChildId': last, 'extraArtifactIds': [note['artifactId']],
                                           'repairOf': check_id})
    round_ = (state.get('rounds') or [{}])[-1]
    entry.update(buildChildId=round_.get('producerId'), resumed=bool(last and round_.get('producerId') == last),
                 codeHash=((state.get('artifact') or {}).get('binding', {}).get('codeSnapshot') or {}).get('hash'),
                 repairChildReason=round_.get('repairChildReason'), status=status)
    return {'action': 'retest' if status == 'needs_checks' else 'stopped', 'status': status, 'entry': entry}


def converged(node, policy_doc, ids, latest):
    """W8.A4.5: `code_review` on the integration node runs only after its `tests` are green there."""
    if node['id'] != work_worktrees.INTEGRATION_NODE or 'code_review' not in ids:
        return
    if not any(r['id'] == 'tests' for r in policy_doc.get('required', [])):
        return
    tests = latest.get('tests')
    if not tests or tests['status'] != 'pass':
        raise ValueError('WORK_REVIEW_NOT_CONVERGED: the integrated run branch must pass its tests on this exact '
                         'snapshot before code_review; start tests first, then review the same artifact.')


def describe(run):
    return json.dumps({k: policy(run).get(k) for k in ('maxRepairs', 'debug', 'source', 'revision')})
