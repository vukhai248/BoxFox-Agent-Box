"""Isolated live main/producer/checker evaluation; B, OpenCode Space Bunny only.

Local executor substitutes Docker transport. No production sessions, CUA, PR or
medical/legal truth benchmark. Retains failed runs and full transcripts.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from work_check_eval import ROOT, FixtureExecutor

from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore


class Client(RouterClient):
    async def complete(self, messages, tools, route, **kwargs):
        allowed = {'work_graph', 'work_run', 'work_check', 'work_artifact_read',
                   'file_read', 'codebase_glob', 'codebase_grep', 'terminal_exec', 'web_fetch', 'read_source'}
        return await super().complete(messages, [t for t in tools if t['function']['name'] in allowed], route, **kwargs)


PROMPTS = {
    'research': 'Chỉ nghiên cứu so sánh hai lựa chọn CSV và JSON dựa trên docs/source.md. '
        'Người dùng đã chốt chỉ xuất CSV cho bản đầu; nêu lý do, đánh đổi và giới hạn. '
        'Không tạo plan triển khai, không hỏi thêm thông tin ngoài nghiên cứu. '
        'Main tự điều phối Research và checks, kiểm bản tổng hợp bằng Work Graph trước khi trả kết quả.',
    'plan': 'Lập plan chi tiết sửa exporter src/export.py để giữ tiếng Việt theo docs/source.md. '
        'Không thực thi thay đổi. Khảo sát code/tests, giao sub-plan; bản plan có data/hợp đồng CSV, '
        'M1–M3, phụ thuộc, file sửa và test/expected cụ thể, rủi ro/rollback theo quy mô. '
        'Không đổi sang JSON hay tạo giao diện. Review/verify bản kế hoạch qua Work Graph, chỉ tóm tắt trong chat.',
    'design': 'Chỉ thiết kế hợp đồng hàm export(value) -> CSV string dựa trên docs/source.md, '
        'src/export.py và tests/test_export.py. Giữ tiếng Việt, escaping CSV, định nghĩa input/output/lỗi '
        'và kiểm chứng; không tạo UI, API server hoặc sửa code. '
        'Main giao Design và kiểm bản tổng hợp bằng Work Graph trước khi trả kết quả.',
}


async def run(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT / '.tmp')
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.router)
    state = await client.snapshot()
    route = next({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                 if c['providerId'] == 'opencode' and c.get('enabled')
                 for m in c['models'] if m['id'] == 'space-bunny-free' and m.get('enabled'))
    source_paths = list((ROOT/'backend/src/agentbox/agent_core').glob('work_*.py')) + [
        ROOT/'backend/src/agentbox/agent_core/runtime.py', ROOT/'backend/src/agentbox/agent_core/roles.py',
        ROOT/'backend/src/agentbox/memory/session_store.py', Path(__file__).resolve()]
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    source_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    def events(store, sid):
        return [{'seq': e['seq'], 'type': e['kind'], 'data': json.loads(e['payload']), 'created': e['created']}
                for e in store.db.execute("SELECT * FROM events WHERE session_id=? AND kind NOT IN "
                    "('thought_delta','assistant_delta') ORDER BY seq", (sid,))]
    rows = []
    for case in args.cases:
        for repeat in range(1, args.repeats + 1):
            folder = out / f'{case}-{repeat}'
            folder.mkdir()
            for name in ('docs', 'src', 'tests'):
                (folder / name).mkdir()
            (folder/'docs/source.md').write_text('Người dùng chốt chỉ xuất CSV, không JSON; giữ nguyên tiếng Việt. '
                'Đầu vào một chuỗi, đầu ra một dòng CSV hợp lệ. Các trường chứa dấu phẩy/newline phải được csv.reader đọc lại đúng. '
                'Dữ liệu là synthetic trong bài thử; không xác nhận code đã đạt nếu chưa chạy test.\n', encoding='utf-8')
            (folder/'src/export.py').write_text("import csv, io\ndef export(value):\n    value = value.encode('ascii', errors='ignore').decode()\n    s = io.StringIO(newline='')\n    csv.writer(s).writerow([value])\n    return s.getvalue()\n", encoding='utf-8')
            (folder/'tests/test_export.py').write_text("import csv, io\nfrom src.export import export\ndef test_unicode():\n    assert next(csv.reader(io.StringIO(export('Hồ sơ')))) == ['Hồ sơ']\n", encoding='utf-8')
            store = SessionStore(folder/'sessions.db')
            rt = HarnessRuntime(store, FixtureExecutor(folder), client)
            sid = rt.create({**route, 'skills': [], 'maxSteps': args.steps, 'deadlineSeconds': args.deadline, 'maxTokens': 16000,
                'instructions': 'Isolated evaluation. Only the local fixture exists. Use Work Graph tools; '
                'no Build/PR, no production resources. Owner decisions in docs/source.md are synthetic supplied data.'})['id']
            started = time.monotonic()
            try:
                await rt.start(sid, PROMPTS[case])
            except Exception as exc:
                error = str(exc)
            else:
                error = None
            graph = getattr(rt, 'work_graph', None)
            work = graph.active(sid) if graph else None
            children = [store.get(c['session_id']) for c in store.children_of(sid)]
            main_events = events(store, sid)
            main_ends = [e['data'] for e in main_events if e['type'] == 'turn_end']
            main_execution = main_ends[-1].get('status') if main_ends else None
            main_reason = rt.partial_turn(sid)
            answer = next((m.get('content') for m in reversed(store.get(sid)['messages'])
                           if m['role'] == 'assistant' and m.get('content')), '')
            record = {'case': case, 'repeat': repeat, 'sessionId': sid, 'route': route,
                'commit': source_commit, 'sourceHashes': source_hashes,
                'ownerSteps': args.steps, 'ownerDeadline': args.deadline,
                'status': store.get(sid)['status'], 'mainExecutionStatus': main_execution,
                'mainPartialReason': main_reason, 'work': work, 'error': error,
                'latencySeconds': round(time.monotonic()-started, 3), 'mainAnswer': answer,
                'children': [{'id': c['id'], 'role': c['role'], 'status': c['status'], 'messages': c['messages'],
                    'events': events(store, c['id'])} for c in children], 'events': main_events,
                'oracle': bool(main_execution == 'completed' and not main_reason
                    and work and work['status'] == 'verified' and children
                    and not any(c['role'] in ('build', 'simplify') for c in children)),
                'semanticAdjudication': 'pending; verified runtime status alone is not semantic proof',
                'scope': 'live main/producer/checks, disposable fixture executor; not Docker/CUA/full benchmark'}
            rows.append(record)
            (out/'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k:record[k] for k in ('case','repeat','status','oracle','latencySeconds')}, ensure_ascii=False), flush=True)
            store.db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--router', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--cases', nargs='+', choices=list(PROMPTS), default=list(PROMPTS))
    p.add_argument('--repeats', type=int, default=2)
    p.add_argument('--steps', type=int, default=60)
    p.add_argument('--deadline', type=int, default=900)
    asyncio.run(run(p.parse_args()))
