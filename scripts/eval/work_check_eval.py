"""Real W6 reviewer tool loops on synthetic immutable artifacts, B / Space Bunny only.

Not a live full DAG benchmark: fixtures isolate coverage, contradiction and code-test
gates. All model tool calls go through HarnessRuntime; source/commands are restricted
to the disposable fixture workspace, without production sessions or provider changes.
"""
import argparse
import asyncio
import hashlib
import json
import os
import fnmatch
import re
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/src'))
os.environ.setdefault('BOXFOX_SYSTEM_LOG_DIR', str(ROOT / '.tmp/work-checks/logs'))
sys.stdout.reconfigure(encoding='utf-8')

from agentbox.agent_core import work_graph as wg, work_policy, work_checks
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore


class FixtureClient(RouterClient):
    async def complete(self, messages, tools, route, **kwargs):
        allowed = {'work_artifact_read', 'file_read', 'codebase_grep', 'codebase_glob', 'terminal_exec'}
        return await super().complete(messages, [t for t in tools if t['function']['name'] in allowed], route, **kwargs)


class FixtureExecutor:
    def __init__(self, folder):
        self.folder = folder

    def path(self, raw):
        target = (self.folder / raw).resolve()
        if not target.is_relative_to(self.folder):
            raise PermissionError('fixture paths only')
        return target

    async def execute(self, name, args, sid, **identity):
        if name == 'write_plan':
            # Publication fixture only; production Docker writer is covered by unit contracts.
            raw = '.plans/' + args['directory'] + '/v1-' + args['slug'] + '.md'
            path = self.path(raw)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args['markdown'], encoding='utf-8')
            return {'relativePath': raw, 'version': 1, 'fixture': True}
        if name == 'file_write':
            path = self.path(args['path'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(args['content'].encode('utf-8'))
            return {'path': args['path'], 'bytes': path.stat().st_size}
        if name == 'file_read':
            path = self.path(args['path'])
            if not path.is_file():
                return {'is_error': True, 'error': 'fixture path does not exist'}
            content = path.read_text(encoding='utf-8')
            return {'content': content, 'path': args['path'], 'fixture': True}
        if name in ('codebase_grep', 'codebase_glob'):
            files = ['src/export.py', 'docs/source.md', 'tests/test_export.py']
            if name == 'codebase_glob':
                matches = [path for path in files if fnmatch.fnmatch(path, args.get('pattern', '**/*'))]
            else:
                pattern = args.get('pattern', '')
                matches = [f'{path}:{index}: {line}' for path in files
                           for index, line in enumerate(self.path(path).read_text(encoding='utf-8').splitlines(), 1)
                           if re.search(pattern, line)]
            return {'content': '\n'.join(matches), 'fixture': True}
        if name == 'terminal_exec':
            command = args['command'].strip()
            if command == work_checks.SNAPSHOT_COMMAND:
                proc = await asyncio.create_subprocess_exec(sys.executable, '-c', work_checks.SNAPSHOT_SCRIPT,
                    cwd=self.folder, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            elif command == 'python -m pytest -q':
                proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'pytest', '-q',
                    cwd=self.folder, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            else:
                return {'is_error': True, 'error': 'Fixture permits exactly python -m pytest -q; no shell commands'}
            out, err = await proc.communicate()
            return {'content': (out + err).decode('utf-8', errors='replace'), 'exit_code': proc.returncode,
                    'is_error': proc.returncode != 0}
        return {'is_error': True, 'error': 'Tool not part of disposable fixture: ' + name}

    async def cleanup(self, sid):
        pass


CASES = {
    'research_scope': ('research', 'evidence', 'Nghiên cứu xuất dữ liệu CSV, không thêm định dạng khác.',
        '# Nghiên cứu\nNguồn docs/source.md: “Chỉ xuất CSV; không JSON.”\n'
        'Khuyến nghị thêm JSON vì linh hoạt hơn.\nĐây là fixture giả lập, không nguồn web thật.\n',
        ['Giữ phạm vi chỉ CSV; không tự thêm JSON', 'Trích đúng đoạn nguồn']),
    'plan_missing_contract': ('plan', 'plan_review', 'Lập kế hoạch API xuất CSV với lỗi và quyền truy cập cụ thể.',
        '# Kế hoạch\n## M1\nTạo endpoint export.\n## M2\nXử lý lỗi và bảo mật.\n'
        'Chạy test sau khi code xong.\n', ['Có payload API, lỗi cụ thể, phân quyền', 'Mỗi milestone có input/output, test và expected']),
    'design_tail': ('design', 'design_review', 'Thiết kế job API; DONE luôn có result_url, FAILED không có result_url.',
        '# Thiết kế fixture\n' + ('## Đoạn dữ liệu tham khảo\nDONE có result_url; FAILED không có result_url.\n' * 430)
        + '\n## Hợp đồng cuối\nGET /jobs/{id}: khi FAILED trả result_url bắt buộc; khi DONE không có result_url.\n',
        ['Các trạng thái và payload cuối file phải thống nhất']),
    'patch_failing_test': ('build', 'tests', 'Sửa exporter để giữ dấu tiếng Việt.',
        '# Handoff fixture\nSửa src/export.py; cần chạy python -m pytest -q.\n'
        'Chưa chạy test, không tuyên bố pass.\n', ['Giữ dấu trong dữ liệu xuất, đối chiếu test thật']),
    'research_valid': ('research', 'evidence', 'Nghiên cứu phạm vi xuất CSV theo nguồn được cung cấp, không thêm JSON.',
        '# Nghiên cứu phạm vi fixture\n## Câu trả lời\nPhạm vi theo ghi chú cung cấp là CSV; không thêm JSON.\n'
        '## Dữ kiện\nNguồn docs/source.md:1: “Chỉ xuất CSV; không JSON.” Đây chỉ là ghi chú phạm vi của fixture, không phải chứng nhận chất lượng mã.\n'
        '## Phương án\nGiữ CSV phù hợp ghi chú. JSON bị loại vì vượt phạm vi.\n'
        '## Giới hạn\nGhi chú không quy định delimiter, encoding hay header; chưa có bằng chứng web hoặc pháp lý. '
        'Không kết luận exporter đã triển khai đúng hay test đã pass; các việc đó cần kiểm chứng riêng.\n'
        '## Khuyến nghị\nĐề xuất giữ phạm vi CSV theo ghi chú; không suy ra hợp đồng API hoặc chất lượng implementation từ một dòng nguồn.\n',
        ['Giữ phạm vi chỉ CSV', 'Trích đúng đoạn nguồn và nêu giới hạn fixture']),
    'patch_passing_test': ('build', 'tests', 'Sửa exporter để giữ dấu tiếng Việt.',
        '# Handoff fixture\nHàm src/export.py giữ nguyên chuỗi đầu vào.\n'
        'Cần kiểm chứng bằng python -m pytest -q; chưa tuyên bố test đã chạy.\n',
        ['Giữ dấu trong dữ liệu xuất, đối chiếu test thật']),
    'plan_many_findings': ('plan', 'plan_review', 'Lập kế hoạch API xuất CSV bất đồng bộ, giữ Unicode, không JSON, không tự triển khai.',
        '# Kế hoạch fixture\n## Kiến trúc\nClient gọi POST /exports không có body. Worker đồng bộ trả jobId số; bảng jobs dùng uuid.\n'
        '## Dữ liệu\nChỉ có cột id và status. Endpoint GET /jobs dùng exportId string. DONE không có result_url; FAILED có result_url bắt buộc.\n'
        '## M1\nTạo API trong src/new_api.py (planned). Thêm JSON cho linh hoạt. Chưa chọn encoding.\n'
        '## M2\nXử lý lỗi sau; retry vô hạn; không cần idempotency. Ghi nguyên credential vào log.\n'
        '## M3\nDùng production làm test; xóa DB khi rollback; không migration; test chỉ kiểm file tồn tại.\n'
        '## Ngưỡng\nTất cả chỉ số đạt 99% vì tôi nghĩ vậy. Không baseline hay dataset.\n',
        ['Giữ phạm vi chỉ CSV', 'Giữ tiếng Việt đầy đủ', 'POST payload cụ thể', 'GET payload cụ thể',
         'Định danh API và DB thống nhất', 'Schema đủ phục vụ job', 'State transitions hợp lệ', 'DONE có result_url',
         'FAILED không có result_url', 'Error codes cụ thể', 'Giới hạn retry cụ thể', 'Idempotency cho request trùng',
         'Secrets không được ghi log', 'Test không dùng production', 'Migration rõ ràng', 'Rollback giữ dữ liệu',
         'Milestone có đầu vào/đầu ra', 'Test kiểm hành vi thay vì tồn tại file', 'Lệnh test chạy được',
         'Ngưỡng có cơ sở hoặc ghi đề xuất', 'Baseline rõ ràng', 'Dữ liệu đánh giá rõ ràng',
         'Đường dẫn planned phân biệt existing', 'Các phần nhất quán và đủ để triển khai']),
}


async def main(args):
    if subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() != 'B':
        raise SystemExit('Only branch B permitted')
    if args.budget:
        os.environ['BOXFOX_WORK_CHECK_OUTPUT_TOKENS'] = str(args.budget)
        os.environ['BOXFOX_REVIEW_OUTPUT_TOKENS'] = str(args.budget)
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.tmp'):
        raise SystemExit('Output must be under B .tmp')
    output.mkdir(parents=True, exist_ok=True)
    client = FixtureClient(args.router)
    state = await client.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                  if c['providerId'] == 'opencode' and c.get('enabled')
                  for m in c['models'] if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no model substitution')
    results_path = output / 'results.json'
    rows = json.loads(results_path.read_text(encoding='utf-8')) if results_path.exists() else []
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in [ROOT/'backend/src/agentbox/agent_core'/name for name in
                                  ('work_graph.py', 'work_checks.py', 'work_policy.py', 'work_artifacts.py', 'work_prompts.py', 'runtime.py', 'output_policy.py')]}
    for case, (role, cid, goal, text, acceptance) in CASES.items():
        if args.cases and case not in args.cases:
            continue
        for repeat in range(1, args.repeats + 1):
            if any(r['case'] == case and r['repeat'] == repeat for r in rows):
                continue
            folder = output / f'{case}-{repeat}'
            folder.mkdir(exist_ok=True)
            (folder/'docs').mkdir(exist_ok=True)
            (folder/'src').mkdir(exist_ok=True)
            (folder/'tests').mkdir(exist_ok=True)
            (folder/'docs/source.md').write_text('Chỉ xuất CSV; không JSON.\n', encoding='utf-8')
            strip = "    value = value.encode('ascii', errors='ignore').decode()\n" if case == 'patch_failing_test' else ''
            source = "import csv, io\ndef export(value):\n" + strip + "    stream = io.StringIO(newline='')\n    csv.writer(stream).writerow([value])\n    return stream.getvalue()\n"
            (folder/'src/export.py').write_text(source, encoding='utf-8')
            (folder/'tests/test_export.py').write_text("import csv, io\nfrom src.export import export\ndef test_unicode():\n    assert next(csv.reader(io.StringIO(export('Hồ sơ')))) == ['Hồ sơ']\n", encoding='utf-8')
            subprocess.run(['git', 'init', '-q'], cwd=folder, check=True)
            subprocess.run(['git', 'add', 'src', 'docs', 'tests'], cwd=folder, check=True)
            subprocess.run(['git','-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','fixture'], cwd=folder, check=True)
            store = SessionStore(folder/'sessions.db')
            rt = HarnessRuntime(store, FixtureExecutor(folder), client)
            session = rt.create({**route, 'skills': [], 'maxSteps': 18, 'deadlineSeconds': 300, 'maxTokens': 4096})
            sid = session['id']
            node = wg.normalize_node({'id': 'N1', 'kind': role, 'title': case, 'goal': goal,
                'acceptance': acceptance, 'tests': ['python -m pytest -q'] if role == 'build' else ['Dự kiến, chưa chạy']})
            graph = wg.service(rt)
            run = graph.create(session, {'goal': goal, 'flow': 'fix' if role == 'build' else role, 'nodes': [node]})
            node = run['nodes'][0]
            stage = 'execute' if role == 'build' else 'produce'
            policy = work_policy.derive(run, node, stage, text, changed=role == 'build')
            binding = graph.checks.binding(run, node, stage) | {'policyHash': policy['hash']}
            if role == 'build':
                # Database/artifact files are deliberately gitignored, so test runs do not alter source snapshot.
                (folder/'.gitignore').write_text('sessions.db*\n.plans/\n.pytest_cache/\n**/__pycache__/\n', encoding='utf-8')
                binding['codeSnapshot'] = await work_checks.snapshot(graph, sid)
            meta = await graph.artifacts.put(run, node['id'], stage, text, binding, True)
            node['stages'][stage].update(status='needs_checks', attempts=1, output=text, artifact=meta, policy=policy,
                rounds=[{'attempt': 1, 'producerRole': role, 'at': time.time()}])
            graph.save(run)
            started = time.monotonic()
            record = {'case': case, 'repeat': repeat, 'route': route, 'branch': 'B', 'sourceHashes': source_hashes,
                      'requestedProfile': args.budget or work_checks.work_policy.VERSION,
                      'artifactChars': len(text), 'artifactHash': meta['contentHash'],
                      'expected': ['pass'] if case in ('research_valid', 'patch_passing_test') else ['revise', 'unverified'] if case == 'design_tail' else ['revise'],
                      'scope': 'live reviewer/tool loop on synthetic fixture; no production DAG or UI'}
            try:
                result = await graph.checks.tool(store.get(sid), {'action':'start','runId':run['runId'],
                    'nodeId':node['id'],'stage':stage,'artifactId':meta['artifactId'],'checkIds':[cid],
                    'invocationId':uuid.uuid4().hex})
                doc = result['checks'][0]
                record.update(status=doc['status'], check=doc, oracle=doc['status'] in record['expected'])
                child = doc.get('childId')
                record['answer'] = graph.child_answer(child)
                record['toolNames'] = [r['name'] for r in work_checks.observations(graph, child)]
                record['turns'] = [json.loads(r['payload']) for r in store.db.execute(
                    "SELECT payload FROM events WHERE session_id=? AND kind='turn_end'", (child,))]
                if args.whole and role == 'research' and doc['status'] == 'pass':
                    whole = await graph.verify(store.get(sid), {'runId': run['runId']})
                    whole_check = graph.checks.records(run['runId'])[-1]
                    record['whole'] = {'status': whole['status'], 'verdict': whole['verdict'], 'check': whole_check,
                                      'documents': whole['documents']}
                    record['oracle'] = record['oracle'] and whole['status'] == 'verified'
                children = [a['childId'] for a in doc.get('attempts', [])]
                if record.get('whole'):
                    children.extend(a['childId'] for a in record['whole']['check'].get('attempts', []))
                record['completionAttempts'] = [json.loads(r['payload']) for c in children if c for r in store.db.execute(
                    "SELECT payload FROM events WHERE session_id=? AND kind='completion_attempt'", (c,))]
            except Exception as exc:
                record.update(status='error', error=str(exc), oracle=False)
            record['latencySeconds'] = round(time.monotonic()-started, 3)
            rows.append(record)
            results_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: record.get(k) for k in ('case','repeat','status','oracle','latencySeconds')},ensure_ascii=False),flush=True)
            store.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', default=str(ROOT/'.tmp/work-checks/live'))
    parser.add_argument('--repeats', type=int, default=1)
    parser.add_argument('--cases', nargs='+', choices=list(CASES), help='Only selected cases; use a fresh output directory to keep prior failures.')
    parser.add_argument('--whole', action='store_true', help='After a passed research check, exercise live whole verification and fixture publication.')
    parser.add_argument('--budget', type=int, choices=[8192, 16000], help='Reviewer profile for controlled 8k/16k comparison.')
    asyncio.run(main(parser.parse_args()))
