"""Reproduce the observed nested-list false pass with native plan reviewers.

Disposable fixtures, real OpenCode Space Bunny; no implementation or CUA.
Both reports differ by one expression only. Read/coverage is not semantic proof.
"""
import argparse
import asyncio
import hashlib
import json
import subprocess
import time
import uuid
from pathlib import Path

from work_quality_eval import Client, FixtureExecutor, HarnessRuntime, ROOT, SessionStore, wg, work_policy


REPORT = '''# P1 — Kế hoạch sửa exporter CSV giữ tiếng Việt
## Phạm vi và hiện trạng
Chỉ lập kế hoạch sửa một hàm; không thực thi, không JSON/UI hoặc dependency mới.
Đã có src/export.py:3 xoá ký tự ngoài ASCII. tests/test_export.py:4 kiểm tiếng Việt;
docs/source.md chốt một chuỗi vào, một bản ghi CSV ra. Không tuyên bố test đã chạy.
## Kiến trúc, dữ liệu và hợp đồng
Giữ csv chuẩn vì nó xử lý delimiter/quote/newline; nối tay không bảo đảm round-trip.
Input value: str, output str; không có lưu trữ/migration. Giữ excel dialect và
StringIO(newline=''). Sau khi bỏ lossy encode, bất biến dự kiến:
`list(csv.reader(io.StringIO(export(value), newline=''))) == INVARIANT`.
Chuỗi rỗng: output '""\\r\\n', reader trả một record có một trường rỗng: [['']].
None ngoài hợp đồng str. Các số liệu dưới đây là mục tiêu, chưa đo.
## Milestones
M1: bỏ dòng 3 của src/export.py, giữ writer; python -m pytest -q dự kiến test_unicode xanh.
M2 phụ thuộc M1: thêm test vào tests/test_export.py cho 'Hồ sơ', 'a,b', 'a"b',
'a\\nb' và ''; expected là đọc lại đúng một record [value], giữ mọi ký tự.
M3 phụ thuộc M2: chạy python -m pytest -q, mọi test trên phải xanh; đọc output thật,
không hứa số passed khi chưa viết bộ test. Chỉ hai file đã nêu được sửa khi execute.
## Rủi ro và rollback
Test sai nesting có thể loại code đúng; kiểm cả kiểu row và giá trị. Giữ newline=''
để không dịch CR/LF. Rollback hoàn tác riêng dòng 3 và các test mới; trở về lỗi
mất dấu cũ, không triển khai service. Không có secret/deploy/backup trong hàm thuần này.
'''


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
    sources = list((ROOT / 'backend/src/agentbox/agent_core').glob('work_*.py')) + [Path(__file__).resolve()]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    rows = []
    for case, invariant, expected in [('correct_nested_rows', '[[value]]', 'pass'),
                                       ('false_flat_rows', '[value]', 'revise')]:
        for repeat in range(1, args.repeats + 1):
            folder = out / f'{case}-{repeat}'
            folder.mkdir()
            for name, content in {
                'docs/source.md': 'Chỉ CSV, không JSON/UI. Input một chuỗi, output một bản ghi CSV; giữ nguyên Unicode.\n',
                'src/export.py': "import csv, io\ndef export(value):\n    value = value.encode('ascii', errors='ignore').decode()\n    s = io.StringIO(newline='')\n    csv.writer(s).writerow([value])\n    return s.getvalue()\n",
                'tests/test_export.py': "import csv, io\nfrom src.export import export\ndef test_unicode():\n    assert next(csv.reader(io.StringIO(export('Hồ sơ')))) == ['Hồ sơ']\n",
            }.items():
                p = folder / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(content.encode('utf-8'))
            store = SessionStore(folder / 'sessions.db')
            rt = HarnessRuntime(store, FixtureExecutor(folder), client)
            session = rt.create({**route, 'skills': [], 'maxSteps': 40, 'deadlineSeconds': 600})
            graph = wg.service(rt)
            run = graph.create(session, {'goal': 'Chỉ lập plan sửa exporter giữ tiếng Việt; không thực thi.',
                'flow': 'plan', 'nodes': [{'id': 'P1', 'kind': 'plan', 'title': 'CSV one-field contract',
                    'goal': 'Kiểm kế hoạch một hàm: kiểu row, bất biến round-trip và expected chuỗi rỗng chính xác; không mở rộng app.',
                    'tests': ['python -m pytest -q (dự kiến sau execute, chưa chạy)'],
                    'acceptance': ['Hiện trạng/file và đề xuất thay đổi được phân biệt, không bịa test đã chạy',
                                   'Biểu thức list(csv.reader(...)) đúng hình dạng record và giữ cả chuỗi rỗng',
                                   'M1–M3 có phụ thuộc, test/expected và rollback theo quy mô']} ]})
            node = run['nodes'][0]
            text = REPORT.replace('INVARIANT', invariant)
            policy = work_policy.derive(run, node, 'produce', text)
            meta = await graph.artifacts.put(run, 'P1', 'produce', text,
                graph.checks.binding(run, node, 'produce') | {'policyHash': policy['hash']}, True)
            node['stages']['produce'].update(status='needs_checks', attempts=1, artifact=meta, policy=policy, output=text,
                rounds=[{'attempt': 1, 'producerRole': 'plan', 'at': time.time()}])
            graph.save(run)
            started = time.monotonic()
            error = None
            try:
                result = await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'], 'nodeId': 'P1',
                    'stage': 'produce', 'artifactId': meta['artifactId'], 'checkIds': ['plan_review'], 'invocationId': uuid.uuid4().hex})
                doc = result['checks'][0]
            except Exception as exc:
                error = f'{type(exc).__name__}: {exc}'
                records = graph.checks.records(run['runId'])
                doc = records[-1] if records else {'status': 'error'}
            correct_coverage = expected == 'pass' or any(c['id'] == 'A2' and c['status'] == 'revise'
                and c.get('target') == 'artifact' for c in doc.get('coverage', []))
            rows.append({'case': case, 'repeat': repeat, 'expected': expected, 'status': doc['status'],
                'oracle': not error and doc['status'] == expected and correct_coverage and not doc.get('inputConflicts'),
                'error': error,
                'semanticAdjudication': 'pending; inspect every finding independently',
                'answer': graph.child_answer(doc.get('childId')), 'check': doc, 'artifact': meta,
                'commit': commit, 'sourceHashes': hashes, 'latencySeconds': round(time.monotonic() - started, 3)})
            (out / 'results.json').write_bytes(json.dumps(rows, ensure_ascii=False, indent=2).encode('utf-8'))
            print(json.dumps({k: rows[-1][k] for k in ('case', 'repeat', 'status', 'oracle', 'latencySeconds')}, ensure_ascii=False), flush=True)
            store.db.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--router', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--repeats', type=int, default=2)
    asyncio.run(run(p.parse_args()))
