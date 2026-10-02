"""W7.2 — reconcile tool calls whose result was never committed to the transcript.

The event log is the commit point of a tool call: `tool_start` (with the replay label and an
args hash) is written before the tool runs, `tool_end` right after it returns, and only then the
transcript message. After a crash, Stop or restart the next turn reconciles every assistant tool
call without a tool message, in this order (pi durable ToolTask, `harness/tool.ts`):

1. a committed `tool_end` exists for the call id: reuse that exact result; no tool, no model call;
2. no `tool_start`: the call never began, so nothing ran; say so;
3. `tool_start` of a `safe` (read-only) tool: re-run the same args once at the start of the turn,
   marked `replayed: true`;
4. `tool_start` of an `unsafe` tool: never replay; write a `TOOL_INTERRUPTED_UNSAFE` receipt
   (tool message + `tool_end` with `interrupted: true`) so the model inspects state first.
"""
import json
import time

from . import work_policy
from .tool_contracts import replay_class

INTERRUPTED_UNSAFE = 'TOOL_INTERRUPTED_UNSAFE'
INTERRUPTED_MESSAGE = ('TOOL_INTERRUPTED_UNSAFE: Interrupted before result was committed; the tool may have '
                       'partially run. Inspect current state before retrying; do not assume success or replay blindly.')
NOT_STARTED_MESSAGE = ('TOOL_NOT_STARTED: Interrupted before this call started; nothing ran. Call it again only '
                       'if it is still needed.')
REPLAY_PENDING_MESSAGE = ('TOOL_REPLAY_PENDING: Interrupted before result was committed; this read-only call is '
                          're-run once at the start of the next step. If this text remains, inspect state and call again.')
RESULT_MAX_CHARS = 24000


def start_payload(call_id, name, args):
    """`tool_start` payload: the intent is committed before the tool runs."""
    return {'id': call_id, 'name': name, 'args': args, 'replay': replay_class(name, args),
            'argsHash': work_policy.digest(args if isinstance(args, (dict, list, str, int, float, bool)) or args is None
                                           else repr(args))}


def tool_content(name, result):
    """Same bounded JSON text the live tool loop writes to the transcript."""
    text = json.dumps(result, ensure_ascii=False)
    if name != 'skill_view' and len(text) > RESULT_MAX_CHARS:
        text = text[:20000] + '\n[Output bounded; original result retained in event log.]'
    return text


def step_seq(store, sid):
    """Seq of the last step boundary: one `usage` row follows every saved assistant row.

    Providers may reuse call ids across steps (`call_0`, `c1`); receipts of an older step with
    the same id must never be taken for the interrupted call.
    """
    return store.db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE session_id=? AND kind='usage'",
                            (sid,)).fetchone()[0]


def _receipts(store, sid, call_id, after=0):
    rows = store.db.execute(
        "SELECT kind,payload FROM events WHERE session_id=? AND seq>? AND kind IN ('tool_start','tool_end') "
        "AND json_extract(payload,'$.id')=? ORDER BY seq", (sid, after, call_id)).fetchall()
    start = end = None
    for row in rows:
        payload = json.loads(row['payload'])
        if row['kind'] == 'tool_start':
            start = payload
        else:
            end = payload
    return start, end


def reconcile(rt, sid, messages):
    """Append a tool message for every uncommitted call; return the safe calls to re-run.

    Synchronous on purpose: it runs in `start()` before the new user message is appended, so the
    transcript keeps every tool result directly after its assistant call.
    """
    pending, latest = {}, set()
    for message in messages:
        if message.get('role') == 'assistant':
            calls = message.get('tool_calls') or []
            for call in calls:
                pending[call['id']] = call
            if calls:
                latest = {call['id'] for call in calls}
        elif message.get('role') == 'tool':
            pending.pop(message.get('tool_call_id'), None)
    replays = []
    after = step_seq(rt.store, sid) if pending else 0
    for cid, call in pending.items():
        name = (call.get('function') or {}).get('name', '')
        if cid not in latest:
            # An older step cannot be matched to receipts reliably: keep the conservative receipt.
            result = {'is_error': True, 'errorCode': INTERRUPTED_UNSAFE, 'error': INTERRUPTED_MESSAGE, 'interrupted': True}
            messages.append({'role': 'tool', 'tool_call_id': cid, 'name': name, 'content': tool_content(name, result)})
            continue
        start, end = _receipts(rt.store, sid, cid, after)
        if end is not None:
            result = end.get('result') if isinstance(end.get('result'), dict) else {}
            messages.append({'role': 'tool', 'tool_call_id': cid, 'name': name, 'content': tool_content(name, result)})
            continue
        if start is None:
            result = {'is_error': True, 'errorCode': 'TOOL_NOT_STARTED', 'error': NOT_STARTED_MESSAGE}
            messages.append({'role': 'tool', 'tool_call_id': cid, 'name': name, 'content': tool_content(name, result)})
            continue
        args = start.get('args') if isinstance(start.get('args'), dict) else {}
        label = start.get('replay') or replay_class(name, args)
        if label == 'safe':
            result = {'is_error': True, 'errorCode': 'TOOL_REPLAY_PENDING', 'error': REPLAY_PENDING_MESSAGE}
            messages.append({'role': 'tool', 'tool_call_id': cid, 'name': name, 'content': tool_content(name, result)})
            replays.append({'id': cid, 'name': name, 'args': args, 'argsHash': start.get('argsHash')})
            continue
        result = {'is_error': True, 'errorCode': INTERRUPTED_UNSAFE, 'error': INTERRUPTED_MESSAGE, 'interrupted': True}
        messages.append({'role': 'tool', 'tool_call_id': cid, 'name': name, 'content': tool_content(name, result)})
        # The receipt must exist in the event log too: progress/finish and main read it there.
        rt.store.emit(sid, 'tool_end', {'id': cid, 'name': name, 'args': args, 'result': result,
                                        'interrupted': True, 'recoveredAt': time.time()})
    return replays


async def replay_safe(rt, session, messages, replays, allowed_tools):
    """Re-run read-only calls exactly once, replacing their placeholder message in place."""
    sid = session['id']
    for item in replays:
        cid, name, args = item['id'], item['name'], item['args']
        if name not in allowed_tools:
            result = {'is_error': True, 'errorCode': 'WORK_CAPABILITY_REVOKED',
                      'error': 'WORK_CAPABILITY_REVOKED: ' + name + ' is no longer permitted; the interrupted call was not re-run'}
        else:
            try:
                result = await rt.dispatch(session, name, args, cid)
                result = result if isinstance(result, dict) else {'result': result}
            except Exception as exc:  # the replay must never kill the turn
                from .failures import classify_failure
                code, text = classify_failure(exc)
                result = {'is_error': True, 'error': text, 'errorCode': code}
                if isinstance(getattr(exc, 'details', None), dict):
                    result.update(exc.details)
        safe = {k: v for k, v in result.items() if k not in {'image', 'base64'}} | {'replayed': True}
        rt.store.emit(sid, 'tool_end', {'id': cid, 'name': name, 'args': args, 'result': safe, 'replayed': True})
        for message in messages:
            if message.get('role') == 'tool' and message.get('tool_call_id') == cid:
                message['content'] = tool_content(name, safe)
                break
    if replays:
        rt.store.save(sid, messages)


def interrupted_calls(store, sid, after_seq=0):
    """`tool_start` rows after a seq whose call has no `tool_end`, with their replay label."""
    rows = store.db.execute(
        "SELECT kind,payload FROM events WHERE session_id=? AND seq>? AND kind IN ('tool_start','tool_end') ORDER BY seq",
        (sid, after_seq)).fetchall()
    started, ended = {}, set()
    for row in rows:
        payload = json.loads(row['payload'])
        if row['kind'] == 'tool_start':
            started[payload.get('id')] = payload
        else:
            ended.add(payload.get('id'))
    return [p | {'replay': p.get('replay') or replay_class(p.get('name'), p.get('args'))}
            for cid, p in started.items() if cid not in ended]


def owner_tools(store, session):
    """The tools this session may still use, recomputed from the owner's CURRENT switches.

    A child's set is the role's set intersected with the owner's, so lowering the owner switch
    must revoke it here; the root's own `config.tools` is the switchboard itself.
    """
    config = session.get('config') or {}
    if not session.get('parent_id'):
        return set(config.get('tools') or [])
    try:
        parent = store.get(session['parent_id'])['config'].get('tools') or []
    except KeyError:
        return set(config.get('tools') or [])
    from .roles import allowed_tools, work_check_tools
    binding = config.get('workBinding') or {}
    if binding.get('checkId'):
        return set(work_check_tools(session.get('role'), parent))
    return set(allowed_tools(session.get('role'), parent)) | {'work_artifact_read', 'work_report'}
