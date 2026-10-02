"""W7.2 native probe — main tự sửa sai hình dạng đối số trong ≤1 lần thử lại.

Bơm lỗi có chủ đích vào lượt main thật (OpenCode Space Bunny), rồi đo cơ chế từ event log:
  F1 `work_report(action='status')` thiếu `runId`        → WORK_REPORT_FIELD_REQUIRED
  F2 `work_report(action='checkpoint', checkpoint=...)`  → WORK_REPORT_ACTION (main không có action này)
  F3 `work_artifact_read(artifactId=...)` thiếu `runId`  → WORK_ARTIFACT_RUN_REQUIRED
Mỗi lỗi phải tự sửa trong ≤1 lần gọi lại CÙNG công cụ và không được diễn giải thành bị chặn quyền
(đúng lỗi đã lưu ở Work-Graph-fix.md §33.11: main đọc `WORK_ARTIFACT_UNKNOWN` thành ACL).

Đây là probe CƠ CHẾ + hành vi model, tách riêng: oracle chỉ dựa trên mã lỗi/đối số thật trong log;
phần diễn giải của model được ghi lại để đối chiếu, không tự nhận là bằng chứng chất lượng.

Chạy:
    python3 scripts/eval/work_report_schema_probe.py --router http://127.0.0.1:36219 \\
        --output .tmp/w7-report-schema --manifest .tmp/w7-contracts-manifest.json --repeats 2
"""
import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/src'))
sys.path.insert(0, str(ROOT / 'scripts/eval'))

from agentbox.agent_core import work_graph as wg, work_policy
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore


NODE = {'id': 'R1', 'kind': 'research', 'title': 'Phương án xuất dữ liệu',
        'goal': 'So sánh hai phương án xuất dữ liệu kèm bằng chứng nguồn gốc',
        'acceptance': ['Nêu rõ nguồn cho từng khẳng định'], 'tests': [], 'files': [],
        'taskKind': 'lookup'}
BODY = ('# Phương án xuất dữ liệu\n\n- CSV giữ nguyên Unicode tiếng Việt khi mở lại.\n'
        '- JSON chỉ dùng cho API nội bộ, không dùng cho hồ sơ bệnh nhân.\n')

PROMPT = '''Bạn là main của BoxFox. Run {run_id} đã có artifact {artifact_id} (bản nháp nút R1).
Tôi đang kiểm thông điệp lỗi của harness, hãy làm ĐÚNG thứ tự sau, mỗi việc một lần:
1. Gọi work_report với action="status" nhưng KHÔNG truyền runId.
2. Gọi work_report với action="checkpoint" và checkpoint="nháp" (main không dùng action này).
3. Gọi work_artifact_read chỉ với artifactId="{artifact_id}" (không có runId).
Sau mỗi lỗi, đọc kỹ `error`, `field`, `hint`, `received` rồi SỬA ĐÚNG lời gọi đó và làm lại ngay
(không hỏi lại tôi). Cuối cùng trả lời ngắn: trạng thái run và hai gạch đầu dòng nội dung artifact.
'''


def branch():
    name = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert name == 'B' or name.startswith('vorflux/'), f'unexpected branch {name!r}'
    return name


def commit():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def source_manifest():
    files = ['backend/src/agentbox/agent_core/tool_arg_errors.py', 'backend/src/agentbox/agent_core/work_feedback.py',
             'backend/src/agentbox/agent_core/work_artifacts.py', 'backend/src/agentbox/agent_core/tool_contracts.py',
             'backend/src/agentbox/agent_core/runtime.py']
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}


class Client(RouterClient):
    """Full main tool set: this probe measures main's own correction, not a filtered toolbox."""

    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        assert route['modelId'] == 'space-bunny-free', 'probe is pinned to OpenCode Space Bunny'
        result = await super().complete(messages, tools, route, **kwargs)
        self.calls.append({'modelId': route['modelId'], 'usage': result.get('usage'),
                           'finishReason': result.get('choices', [{}])[0].get('finish_reason')})
        return result


class Executor:
    def __init__(self, folder):
        self.folder = folder

    async def execute(self, name, args, sid, **_identity):
        if name == 'file_write':
            path = self.folder / args['path']
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args['content'], encoding='utf-8')
            return {'path': args['path'], 'bytes': path.stat().st_size}
        if name == 'file_read':
            path = self.folder / args['path']
            if not path.is_file():
                return {'is_error': True, 'error': 'fixture path does not exist'}
            return {'content': path.read_text(encoding='utf-8'), 'path': args['path']}
        if name == 'terminal_exec':
            return {'content': 'probe fixture allows read-only inspection only', 'exit_code': 0, 'is_error': False}
        return {'content': 'probe fixture'}

    async def cleanup(self, sid):
        return None


def receipts(store, sid):
    """tool_start/tool_end pairs in order, joined by call id."""
    rows = [dict(r) for r in store.db.execute(
        "SELECT seq,kind,payload FROM events WHERE session_id=? AND kind IN ('tool_start','tool_end') ORDER BY seq",
        (sid,))]
    out = {}
    for row in rows:
        payload = json.loads(row['payload'])
        item = out.setdefault(payload.get('id'), {'callId': payload.get('id'), 'name': payload.get('name'),
                                                  'args': payload.get('args'), 'result': None, 'seq': row['seq']})
        if row['kind'] == 'tool_end':
            item['result'] = payload.get('result')
    return [out[key] for key in sorted(out, key=lambda k: out[k]['seq'])]


def visible(store, sid):
    return [m.get('content') for m in store.get(sid)['messages']
            if m.get('role') == 'assistant' and isinstance(m.get('content'), str) and m['content'].strip()]


def classify(calls, name, error_code, predicate):
    """The injected fault, the retry that follows it, and whether the retry was correct."""
    for index, call in enumerate(calls):
        result = call.get('result') or {}
        if call['name'] != name or result.get('errorCode') != error_code:
            continue
        for follow in calls[index + 1:index + 3]:  # ≤1 retry = the next call of the same tool
            if follow['name'] != name:
                continue
            return {'fault': {'callId': call['callId'], 'args': call['args'], 'errorCode': error_code,
                              'error': str(result.get('error'))[:400], 'details':
                              {k: result.get(k) for k in ('field', 'action', 'hint', 'received') if k in result}},
                    'retry': {'callId': follow['callId'], 'args': follow['args'],
                              'errorCode': (follow.get('result') or {}).get('errorCode')},
                    'corrected': predicate(follow.get('args') or {}, follow.get('result') or {})}
        return {'fault': {'callId': call['callId'], 'args': call['args'], 'errorCode': error_code}, 'retry': None,
                'corrected': False}
    return {'fault': None, 'retry': None, 'corrected': False}


def interpretation(texts):
    """Any sentence that reads a shape error as a permission/ACL denial (the W6.2 misread)."""
    pattern = re.compile(r'(ACL|access[- ]control|không có quyền|không được phép|bị chặn quyền|'
                         r'permission denied|not (?:allowed|permitted) to (?:read|access))', re.I)
    return [line.strip()[:240] for text in texts for line in text.splitlines() if pattern.search(line)]


async def main(args):
    name, head, manifest = branch(), commit(), source_manifest()
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in frozen.items()), 'source drift'
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp'), 'write probe output under .tmp/'
    output.mkdir(parents=True, exist_ok=True)
    probe = Client(args.router)
    state = await probe.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                  if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
                  if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    rows = []
    for trial in range(1, args.repeats + 1):
        folder = output / f'trial-{trial}'
        folder.mkdir(parents=True, exist_ok=True)
        client = Client(args.router)
        store = SessionStore(folder / 'sessions.db')
        rt = HarnessRuntime(store, Executor(folder), client)
        sid = rt.create({**route, 'skills': []})['id']
        graph = wg.service(rt)
        run = graph.create(store.get(sid), {'goal': 'So sánh hai phương án xuất dữ liệu cho hồ sơ bệnh nhân',
                                            'flow': 'research', 'nodes': [NODE]})
        node = run['nodes'][0]
        binding = graph.checks.binding(run, node, 'produce')
        meta = await graph.artifacts.put(run, node['id'], 'produce', BODY, binding, True)
        row = {'trial': trial, 'runId': run['runId'], 'artifactId': meta['artifactId'], 'modelId': route['modelId']}
        started = time.monotonic()
        try:
            await rt.start(sid, PROMPT.format(run_id=run['runId'], artifact_id=meta['artifactId']))
            calls = receipts(store, sid)
            texts = visible(store, sid)
            row['faults'] = {
                'report_missing_runid': classify(calls, 'work_report', 'WORK_REPORT_FIELD_REQUIRED',
                                                 lambda a, r: bool(a.get('runId')) and not r.get('errorCode')),
                'report_forbidden_action': classify(calls, 'work_report', 'WORK_REPORT_ACTION',
                                                    lambda a, r: a.get('action') in ('status', 'read')
                                                    and not r.get('errorCode')),
                'artifact_missing_runid': classify(calls, 'work_artifact_read', 'WORK_ARTIFACT_RUN_REQUIRED',
                                                   lambda a, r: bool(a.get('runId')) and not r.get('errorCode')),
            }
            row['aclMisread'] = interpretation(texts)
            row['toolCalls'] = [{'name': c['name'], 'errorCode': (c.get('result') or {}).get('errorCode')}
                                for c in calls if c['name'] in ('work_report', 'work_artifact_read', 'work_graph')]
            row['artifactRead'] = any(c['name'] == 'work_artifact_read'
                                      and (c.get('result') or {}).get('content', '').find('CSV giữ nguyên Unicode') >= 0
                                      for c in calls)
            row['finalText'] = texts[-1][:600] if texts else ''
            row['oracle'] = (all(f['fault'] and f['corrected'] for f in row['faults'].values())
                             and row['artifactRead'] and not row['aclMisread'])
            row['status'] = store.get(sid)['status']
        except Exception as exc:
            row.update(oracle=False, error=f'{type(exc).__name__}: {exc}'[:400], status=store.get(sid)['status'])
        row.update(latencySeconds=round(time.monotonic() - started, 3), providerCalls=len(client.calls),
                   sourceManifest=manifest, branch=name, commit=head)
        rows.append(row)
        (output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        print(json.dumps({k: row.get(k) for k in ('trial', 'oracle', 'status', 'latencySeconds', 'error')},
                         ensure_ascii=False), flush=True)
        await rt.stop(sid)
        store.db.close()
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in frozen.items()), 'source drift'
    return all(r['oracle'] for r in rows)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    ok = asyncio.run(main(parser.parse_args()))
    raise SystemExit(0 if ok else 1)
