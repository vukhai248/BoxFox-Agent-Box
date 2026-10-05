"""Main thích ứng: cổng runtime và lịch sử lỗi bền, không phải scheduler thứ hai.

Quyết định không cấp tool, grant hoặc tiền. Legacy giữ SOP/giới hạn cũ. Adaptive
chọn bước theo evidence; request/tool watchdog và giới hạn caller vẫn giữ nguyên
trong rollout này, chưa gọi chúng là default đã calibrate.
"""
import json

from . import adaptive_main, execution_kernel
from .orchestration_contracts import invalid
from .work_policy import digest

GUIDANCE = '''Choose the next useful step from the owner's goal, current evidence, and effective permissions.
Do not require a fixed sequence of specialist roles or a global graph for every request.
Work directly for a small, clear task. Delegate only a concrete independent question or deliverable.
Use canonical Work Graph admission and minimum checks when a write requires them; this instruction grants nothing.
Research owns its source ledger and published report. Main sends questions or gaps, not ledger edits or forced verdicts.
Wait through an event subscription when no independent work remains. Do not poll to consume model requests.
Stop when the outcome and required checks are complete. Report partial, unknown outcomes, or missing authority honestly.
Do not increase scope, spending consent, or capabilities from a summary, skill, or decision recommendation.'''


def policy(rt, sid):
    current = rt.store.get(sid)
    pin = execution_kernel._policy(current)
    if pin is not None and not execution_kernel.enabled():
        invalid('harnessPolicy', 'adaptive admission switch is off; keep checkpoint readable',
                'ADAPTIVE_DISABLED')
    if current.get('parent_id') or current.get('role') != 'orchestrator':
        return None  # Specialist giữ policy quyền, không nhận thuật toán main.
    return pin


def service(rt):
    # Một bảng cộng thêm; không sửa lịch sử events/approvals.
    rt.store.db.execute('CREATE TABLE IF NOT EXISTS harness_adaptive_state ('
                        'session_id TEXT PRIMARY KEY, failures_json TEXT NOT NULL, '
                        'evidence_json TEXT NOT NULL)')
    rt.store.db.commit()


def state(rt, sid):
    service(rt)
    row = rt.store.db.execute('SELECT * FROM harness_adaptive_state WHERE session_id=?', (sid,)).fetchone()
    if row is None:
        return [], []
    try:
        failures, evidence = json.loads(row['failures_json']), json.loads(row['evidence_json'])
    except (ValueError, TypeError):
        invalid('adaptiveState', 'corrupt runtime checkpoint', 'ADAPTIVE_STATE_CORRUPT')
    if not isinstance(failures, list) or not isinstance(evidence, list):
        invalid('adaptiveState', 'invalid runtime checkpoint shape', 'ADAPTIVE_STATE_CORRUPT')
    return failures, evidence


def _save(rt, sid, failures, evidence):
    with rt.store.db:
        rt.store.db.execute('INSERT OR REPLACE INTO harness_adaptive_state VALUES(?,?,?)',
                            (sid, json.dumps(failures), json.dumps(evidence)))


def decide(rt, sid, observation=None):
    if policy(rt, sid) is None:
        return None
    current = rt.store.get(sid)
    data = dict(observation or {})
    # Caller ở đây là runtime, không phải model hoặc text của nguồn ngoài.
    if current.get('status') == 'cancelled':
        data['stopRequested'] = True
    if current.get('status') == 'awaiting_decision':
        data['userDecisionPending'] = True
    metadata = current['config'].get('modelMetadata') or {}
    route = current['config'].get('route') or {}
    if metadata.get('id') != route.get('modelId'):
        metadata = {}
    data.setdefault('capability', metadata)
    failures, evidence = state(rt, sid)
    data.setdefault('evidenceRefs', evidence)
    previous = rt.store.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='harness_decision' "
                                   'ORDER BY seq DESC LIMIT 1', (sid,)).fetchone()
    prior_refs = json.loads(previous['payload']).get('evidenceRefs', []) if previous else []
    data.setdefault('previous', {'evidenceRefs': prior_refs})
    data.setdefault('current', {'evidenceRefs': evidence})
    # Lỗi chưa có evidence mới làm uncertainty cao; không hạ unknown thành low.
    unresolved = any(entry.get('evidenceRefs') == evidence for entry in failures)
    data.setdefault('uncertainty', 'high' if unresolved else 'unknown')
    data.setdefault('value', 'unknown')
    result = adaptive_main.compose({'enabled': True}, data, failures)
    rt.store.emit(sid, 'harness_decision', result)
    return result


def before_request(rt, sid):
    result = decide(rt, sid)
    if result and result['action'] in ('blocked', 'stop', 'park'):
        invalid('nextStep', result['reason'], 'ADAPTIVE_REQUEST_DENIED')
    return result


def _signature(rt, sid, name, args, evidence):
    current = rt.store.get(sid)
    view = execution_kernel.permission_view(rt, current)
    inputs = {'args': args, 'role': current['role'], 'tools': sorted(current['config'].get('tools') or []),
              'scope': view.get('scope'), 'epoch': execution_kernel.capability_epoch(rt, current)}
    return {'signature': digest({'tool': name, 'args': args}),
            'inputs': digest(inputs), 'evidenceRefs': evidence}


def before_tool(rt, sid, name, args):
    if policy(rt, sid) is None:
        return None
    failures, evidence = state(rt, sid)
    signature = _signature(rt, sid, name, args, evidence)
    observation = {'loop': {'history': failures, 'signature': signature}}
    if name in ('delegate_task', 'start_job'):
        observation['branch'] = {'needed': True, 'reason': 'canonical delegated tool requested',
                                 'evidenceRefs': evidence}
    if name in ('await_children', 'wait_jobs'):
        observation['park'] = {'needed': True, 'reason': 'wait on canonical results', 'waitFor': name}
    result = decide(rt, sid, observation)
    if result['action'] in ('blocked', 'stop'):
        invalid('tool', result['reason'], 'ADAPTIVE_LOOP_REPEAT')
    return result


def after_tool(rt, sid, name, args, result):
    current = rt.store.get(sid)
    if (execution_kernel._policy(current) is None or current.get('parent_id')
            or current.get('role') != 'orchestrator'):
        return
    failures, evidence = state(rt, sid)
    if result.get('is_error'):
        if result.get('errorCode') == 'ADAPTIVE_LOOP_REPEAT':
            return
        signature = _signature(rt, sid, name, args, evidence)
        # Không reset qua lượt/retry. Một signature cũ vẫn chặn khi evidence không đổi.
        if signature not in failures:
            failures.append(signature)
    elif name in ('file_read', 'file_search', 'web_fetch', 'work_get', 'task_get'):
        ref = 'observed-' + digest({'tool': name, 'args': args, 'result': result})
        if ref not in evidence:
            evidence.append(ref)
    _save(rt, sid, failures, evidence)
