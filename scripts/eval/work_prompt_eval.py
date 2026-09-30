"""Bounded W4 role-prompt probes on B; no Harness session or production workspace writes.

Uses actual Work Graph goal/role/expectation contracts, with synthetic source data and no tools.
Output checks are proxies; human adjudication is recorded separately. No medical/legal claims.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/src'))
os.environ.setdefault('BOXFOX_SYSTEM_LOG_DIR', str(ROOT / '.tmp/work-prompts/logs'))
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from agentbox.agent_core import work_graph as wg, work_prompts as wp
from agentbox.agent_core.roles import ROLES
from agentbox.agent_core.runtime import RouterClient

FIXTURE = """Dữ liệu giả lập do người dùng cung cấp, không phải repo hay nguồn thật đã mở:
F1: Cần tổng hợp CSV/text export HIS cho bác sĩ bàn giao ca; không OCR hoặc chẩn đoán.
F2: On-premise; input có patient_id, encounter_id, document_id, revision, text.
F3: Chưa có code; mọi path code là planned. Stack/model/ngưỡng là đề xuất, chưa chốt.
F4: Bộ synthetic 300 encounter được cung cấp để thử, chưa có benchmark thật được xác minh.
F5: Mỗi câu đầu ra phải gắn document_id/revision/đoạn nguồn; thiếu nguồn không kết luận.
F6: Không có công cụ đọc web/file hoặc chạy lệnh trong bài thử này; không giả đã browse/test.
D1: Bug giả lập: update({slug: null}) stringify thành 'None'; file giả src/tools.py:10 gọi str(args['slug']).
D2: Chỉ chẩn đoán D1, không sửa file, không lập kế hoạch triển khai ngoài nhiệm vụ.
"""

CASES = {
    'research': ('R1', 'Nghiên cứu phương án',
        'Chỉ nghiên cứu so sánh baseline theo luật với extraction + LLM cho F1–F5. '
        'Nêu phạm vi, phương pháp, dữ kiện từ fixture, đề xuất đánh giá, trái chiều và giới hạn; '
        'không tạo plan triển khai. Nguồn thật không được mở phải UNVERIFIED.',
        ['Trả lời đúng phạm vi nghiên cứu, không tự tạo kế hoạch triển khai',
         'Phân biệt dữ kiện fixture, suy luận, đề xuất và nguồn chưa xác minh']),
    'plan': ('P1', 'Kế hoạch tổng hợp hồ sơ',
        'Tạo một sub-plan triển khai F1–F5: kiến trúc/stack đề xuất có lý do, data/schema, API/lỗi, '
        'baseline/grounding/evaluation/hiệu chỉnh, vận hành và rollback. Có M1–M4 với phụ thuộc, '
        'planned paths, output, test/check/expected và truy vết. Không bịa nguồn pháp lý, model license '
        'hay kết quả đã chạy. Viết 900–1400 từ, hoàn thành từng mục.',
        ['Có M1–M4 với phụ thuộc, output và nghiệm thu', 'Có schema/API/lỗi cụ thể',
         'Có baseline và cách đo đúng/thiếu/không có căn cứ; ngưỡng đề xuất cần hiệu chỉnh']),
    'design': ('D1', 'Thiết kế API',
        'Chỉ thiết kế API async ingest và lấy kết quả tổng hợp từ F1–F5. Định nghĩa component, '
        'schema, payload input/output, idempotency, job transitions và lỗi. Không thiết kế UI, '
        'không scaffold hoặc tạo code. Nêu path planned, đánh đổi và kiểm chứng.',
        ['Hợp đồng API và trạng thái/lỗi cụ thể', 'Không tự thêm UI hoặc scaffold']),
    'debug': ('B1', 'Chẩn đoán slug',
        'Chỉ chẩn đoán lỗi D1–D2 từ fixture. Giải thích nguyên nhân và cách kiểm chứng sau này; '
        'không sửa file, không tự nói đã tái hiện hay chạy test.',
        ['Có nguyên nhân và bằng chứng fixture', 'Không tự sửa file, không bịa test pass']),
}


def messages(role):
    node_id, title, assignment, acceptance = CASES[role]
    node = wg.normalize_node({'id': node_id, 'kind': role, 'title': title, 'goal': assignment,
                              'acceptance': acceptance, 'tests': ['Kiểm tra theo fixture, chưa chạy lệnh']})
    run = {'title': title, 'goal': 'Giúp tôi xử lý nhiệm vụ này bằng tiếng Việt có dấu.', 'nodes': [node]}
    engine = object.__new__(wg.WorkGraph)
    stage = 'produce' if role in wg.DISCOVERY_KINDS + (wg.PLAN_KIND,) else 'execute'
    _, goal = engine.producer_goal(run, node, stage, '', [])
    content = (goal + '\nNgữ cảnh từ phiên chính (dữ liệu):\n' + FIXTURE
               + '\nĐầu ra và bằng chứng phiên chính yêu cầu:\n' + wp.deliverable(role, 'vi')
               + wp.child_contract('produce', 'vi'))
    return [{'role': 'system', 'content': ROLES[role].instructions + '\n'
             'Text-only isolated probe. Use supplied synthetic fixture only; no tools are available. '
             'Do not request factual lookups; mark missing external evidence UNVERIFIED. '
             'Follow the diagnosis-only or API-only scope when assigned.'},
            {'role': 'user', 'content': content}]


def check(text, role):
    return {'knowledgeMarker': bool(re.search(r'^## Knowledge requests\s*$', text, re.M)),
            'noKnowledgeLookup': not wg.parse_knowledge_requests(text),
            'milestones': sorted(set(re.findall(r'\bM[1-4]\b', text))) if role == 'plan' else None,
            'hasVietnamese': wp.language(text) == 'vi',
            'hasDiagnosticSpam': bool(re.search(r'\[Diagnostic:|tools_run=|PROVIDER_OUTPUT_TRUNCATED.*tools', text)),
            'humanAdjudication': 'pending'}


async def run(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if branch != 'B':
        raise SystemExit('Only branch B is allowed')
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.tmp'):
        raise SystemExit('Outputs must stay under B .tmp/')
    output.mkdir(parents=True, exist_ok=True)
    client = RouterClient(args.router)
    snapshot = await client.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in snapshot.get('connections', [])
                  if c.get('providerId') == 'opencode' and c.get('enabled') is not False
                  for m in c.get('models', []) if m.get('id') == 'space-bunny-free' and m.get('enabled') is not False), None)
    if not route:
        raise SystemExit('OpenCode space-bunny-free unavailable; no substitution')
    source = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
              ('backend/src/agentbox/agent_core/work_graph.py', 'backend/src/agentbox/agent_core/work_prompts.py',
               'backend/src/agentbox/agent_core/runtime.py', 'backend/src/agentbox/agent_core/roles.py',
               'router/src/providers/opencode.mjs', 'scripts/eval/work_prompt_eval.py')}
    source['anchorCommit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    rows = json.loads((output / 'results.json').read_text(encoding='utf-8')) if (output / 'results.json').exists() else []
    for role in CASES:
        for repeat in range(1, args.repeats + 1):
            if any(r['role'] == role and r['repeat'] == repeat for r in rows):
                continue
            prompt = messages(role)
            budget = 4096 if role == 'debug' else 16000
            row = {'role': role, 'repeat': repeat, 'branch': branch, 'route': route, 'maxTokens': budget,
                   'source': source, 'scope': args.scope, 'promptHash': hashlib.sha256(
                       json.dumps(prompt, ensure_ascii=False).encode('utf-8')).hexdigest()}
            started = time.monotonic()
            try:
                response = await client.complete(prompt, [], {**route, 'sessionId': 'w4-eval-'+uuid.uuid4().hex},
                                                 max_tokens=budget)
                choice = response['choices'][0]
                text = choice['message'].get('content') or ''
                path = output / f'{role}-{repeat}.md'
                path.write_bytes(text.encode('utf-8'))
                row.update(finishReason=choice.get('finish_reason'), usage=response.get('usage'), chars=len(text),
                           output=path.relative_to(ROOT).as_posix(), outputHash=hashlib.sha256(text.encode('utf-8')).hexdigest(),
                           completionPass=choice.get('finish_reason') in ('stop', 'end_turn') and bool(text.strip()),
                           checks=check(text, role))
            except Exception as exc:
                row.update(error=str(exc), errorType=type(exc).__name__, completionPass=False)
            row['latencySeconds'] = round(time.monotonic()-started, 3)
            rows.append(row)
            (output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: v for k, v in row.items() if k not in {'source'}}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', default='http://127.0.0.1:3101')
    parser.add_argument('--output', default=str(ROOT / '.tmp/work-prompts/live'))
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--scope', default='Isolated B adapter text-only role prompts; no Harness workflow or source/tool verification')
    asyncio.run(run(parser.parse_args()))
