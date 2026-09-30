"""Isolated completion-budget probe; no production harness session or workspace writes.

This measures completion/coverage, not clinical validity or an independent semantic review.
Only the explicitly selected OpenCode space-bunny-free route is allowed in live mode.
"""
from __future__ import annotations

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

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/src'))
os.environ.setdefault('BOXFOX_SYSTEM_LOG_DIR', str(ROOT / '.tmp/output-budget/logs'))

from agentbox.agent_core.runtime import RouterClient

FACTS = """Bằng chứng fixture giả lập, chỉ dùng đo output:
F01: Đầu vào CSV/Word/text export HIS; không có ảnh, OCR nằm ngoài phạm vi.
F02: Bác sĩ dùng tóm tắt cho bàn giao ca/hội chẩn; người dùng xác nhận trước sử dụng.
F03: On-premise, 3.000 hồ sơ/ngày; 2 GPU 24 GB; không dùng dịch vụ cloud.
F04: Định danh bệnh nhân từ HIS; mỗi encounter có ID, thời điểm và document revision.
F05: Kết quả liên kết doc_id + revision + đoạn nguồn; không tự chẩn đoán/đề xuất điều trị.
F06: Cần quản lý mâu thuẫn, thiếu dữ kiện, thay đổi thuốc và timeline; thiếu nguồn thì từ chối kết luận.
F07: Dataset synthetic 600 encounter, có trường vàng và tóm tắt bác sĩ giả lập.
F08: Chia dữ liệu theo patient ID; không để cùng bệnh nhân qua các split.
F09: Repo fixture chưa có code; mọi path đề xuất phải đánh dấu planned.
F10: API async, retry/idempotency; quyền theo đơn vị; lưu audit, backup và rollback.
F11: Chưa kiểm chứng nguồn pháp lý/model/benchmark thật; không được bịa nguồn đã đọc.
F12: Stack/model là đề xuất; cần baseline, lý do/đánh đổi và cách đo trước production.
"""

CASES = {
    'research': [
        ('research-evaluation', ['Mục tiêu', 'Chỉ số', 'Bộ dữ liệu', 'Baseline', 'Bác sĩ chấm', 'Ngưỡng', 'Giới hạn'],
         'Nghiên cứu thiết kế bộ đánh giá tóm tắt bệnh án tiếng Việt từ F01–F12. '
         'Định nghĩa metric đo đúng/thiếu/hallucination, đơn vị đo và denominator; '
         'thiết kế split, rubric, hội đồng chấm, ngưỡng đề xuất cần hiệu chỉnh và cách xử lý dữ liệu không đủ.'),
        ('research-options', ['Mục tiêu', 'Phương án', 'Dữ liệu', 'Chi phí', 'Đánh giá', 'Khuyến nghị', 'Giới hạn'],
         'So sánh ba cách triển khai: extraction theo luật; extraction + LLM; LLM + retrieval theo encounter. '
         'Phân tích concurrency/VRAM bằng giả định minh bạch, CPU baseline, chi phí/latency và bằng chứng cần đo. '
         'Không nêu model/license/benchmark như facts đã xác minh; đưa quy trình kiểm chứng lựa chọn.'),
    ],
    'plan': [
        ('plan-medical', ['Sản phẩm', 'Kiến trúc', 'Dữ liệu', 'API', 'AI', 'Vận hành', 'Milestone', 'Nghiệm thu'],
         'Viết kế hoạch SWE/AI đầy đủ cho app trong F01–F12: components, stack/đánh đổi, schema, '
         'API input/output/errors, grounding, evaluation, triển khai/backup/rollback. '
         'Ít nhất 8 milestone M1–M8, mỗi mốc có phụ thuộc, planned paths, đầu ra, test và expected result.'),
        ('plan-tooling', ['Hiện trạng', 'Nguyên nhân', 'Hợp đồng', 'Thay đổi', 'Rủi ro', 'Milestone', 'Nghiệm thu'],
         'Repo fixture: Python tool runtime stringify slug sai kiểu, glob brace trả empty, '
         'stream EOF bị gán length, retry giảm nửa token, diagnostic nối URL. '
         'Lập plan sửa an toàn, không đổi UI/DAG/DB. Ít nhất 6 milestone M1–M6, '
         'input/output và mã lỗi, compatibility, regression/fault injection và rollback từng thay đổi.'),
    ],
    'design': [
        ('design-pipeline', ['Mục tiêu', 'Thành phần', 'Luồng', 'Schema', 'Hợp đồng', 'Lỗi', 'Vận hành', 'Kiểm chứng'],
         'Thiết kế kỹ thuật pipeline cho F01–F12. Mô tả trách nhiệm/boundary, sequence async, '
         'schema core, version/hash, idempotency/retry, quyền/audit và grounding từng claim. '
         'Có ít nhất 6 hợp đồng I1–I6, ví dụ payload và lỗi; không tạo giao diện hoặc code.'),
        ('design-evaluation', ['Mục tiêu', 'Thành phần', 'Luồng', 'Schema', 'Hợp đồng', 'Lỗi', 'Vận hành', 'Kiểm chứng'],
         'Thiết kế evaluation service cho F01–F12: ingest golden data, prediction snapshot, '
         'claim alignment, scoring đúng/thiếu/không có căn cứ, physician adjudication, gate report. '
         'Có ít nhất 6 hợp đồng I1–I6, state transitions, JSON examples, split isolation và failure recovery.'),
    ],
}


def prompt(role, case):
    name, sections, goal = case
    headings = '\n'.join('## ' + s for s in sections)
    return [
        {'role': 'system', 'content': 'Bạn là specialist ' + role + '. Viết tiếng Việt có dấu. '
         'Chỉ dùng facts fixture được cung cấp; phân biệt đề xuất với facts. Không giả vờ browse, '
         'chạy test hay review. Hoàn thành báo cáo cụ thể, không chỉ liệt kê tiêu đề.'},
        {'role': 'user', 'content': FACTS + '\nNhiệm vụ: ' + goal + '\n'
         'Bao phủ rõ F01–F12 khi liên quan. Dùng đúng các tiêu đề sau, mỗi mục có nội dung kỹ thuật:\n' + headings + '\n'
         'Viết khoảng 1.800–2.600 từ nếu cần để giải quyết đủ hợp đồng/đánh đổi/test; '
         'không kéo dài bằng lặp lại. Kết thúc bằng dòng END_REPORT.'},
    ]


def coverage(text, case):
    _, sections, _ = case
    missing = []
    for heading in sections:
        match = re.search(r'^##\s+' + re.escape(heading) + r'[^\n]*\n(.*?)(?=^##\s|\Z)', text, re.M | re.S)
        if not match or len(match[1].strip()) < 80:
            missing.append(heading)
    return {'missingSections': missing, 'endMarker': text.rstrip().endswith('END_REPORT'),
            'milestones': len(set(re.findall(r'\bM[1-8]\b', text))),
            'contracts': len(set(re.findall(r'\bI[1-6]\b', text)))}


async def run(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    if args.live and branch != 'B':
        raise SystemExit('Live eval must run from branch B')
    client = RouterClient(args.router)
    snapshot = await client.snapshot() if args.live else None
    route = None
    for connection in (snapshot or {}).get('connections', []):
        if connection.get('providerId') != 'opencode' or connection.get('enabled') is False:
            continue
        for model in connection.get('models', []):
            if model.get('id') == 'space-bunny-free' and model.get('enabled') is not False:
                route = {'connectionId': connection['id'], 'modelId': model['id']}
                break
        if route:
            break
    if args.live and not route:
        raise SystemExit('OpenCode space-bunny-free unavailable; no provider substitution')
    output = Path(args.output).resolve()
    if not output.is_relative_to(ROOT / '.tmp'):
        raise SystemExit('Eval outputs must stay under this checkout .tmp/')
    output.mkdir(parents=True, exist_ok=True)
    source = {'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'runtimeSha256': hashlib.sha256((ROOT/'backend/src/agentbox/agent_core/runtime.py').read_bytes()).hexdigest(),
              'evaluatorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'opencodeAdapterSha256': hashlib.sha256((ROOT/'router/src/providers/opencode.mjs').read_bytes()).hexdigest(),
              'routerRelay': args.router, 'outputCeiling': 'unknown for space-bunny-free',
              'scope': args.scope}
    rows = json.loads((output/'results.json').read_text(encoding='utf-8')) if (output/'results.json').exists() else []
    for role in args.roles:
        budgets = args.research_budgets if role == 'research' else args.document_budgets
        for budget in budgets:
            for case in CASES[role]:
                for repeat in range(args.repeats):
                    if any(row['role'] == role and row['case'] == case[0] and row['requestedMaxTokens'] == budget
                           and row['repeat'] == repeat+1 for row in rows):
                        continue
                    messages = prompt(role, case)
                    key = f'{role}-{case[0]}-{budget}-{repeat+1}'
                    record = {'case': case[0], 'role': role, 'requestedMaxTokens': budget, 'repeat': repeat+1,
                              'promptHash': hashlib.sha256(json.dumps(messages, ensure_ascii=False).encode()).hexdigest(),
                              'branch': branch, 'route': route, 'live': args.live, 'source': source}
                    if args.live:
                        started = time.monotonic()
                        try:
                            response = await client.complete(messages, [], {**route, 'sessionId': 'w3-eval-'+uuid.uuid4().hex}, max_tokens=budget)
                            choice = response['choices'][0]
                            text = choice['message'].get('content') or ''
                            checks = coverage(text, case)
                            record.update(finishReason=choice.get('finish_reason'), usage=response.get('usage'),
                                          chars=len(text), **checks)
                            record['completionPass'] = choice.get('finish_reason') in ('stop', 'end_turn') and checks['endMarker']
                            record['coveragePass'] = not checks['missingSections'] and (role != 'plan' or checks['milestones'] >= (8 if case[0] == 'plan-medical' else 6)) and (role != 'design' or checks['contracts'] >= 6)
                            (output / (key+'.md')).write_text(text, encoding='utf-8')
                        except Exception as exc:
                            record.update(error=str(exc), errorType=type(exc).__name__, completionPass=False, coveragePass=False)
                        record['latencySeconds'] = round(time.monotonic()-started, 3)
                    rows.append(record)
                    (output/'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(json.dumps(record, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--router', default='http://127.0.0.1:3101')
    parser.add_argument('--scope', default='B RouterClient via existing router relay; no harness workflow or semantic review')
    parser.add_argument('--output', default=str(ROOT/'.tmp/output-budget/live'))
    parser.add_argument('--roles', nargs='+', choices=list(CASES), default=list(CASES))
    parser.add_argument('--research-budgets', nargs='+', type=int, default=[4096, 8192])
    parser.add_argument('--document-budgets', nargs='+', type=int, default=[16000])
    parser.add_argument('--repeats', type=int, default=2)
    options = parser.parse_args()
    if not 1 <= options.repeats <= 3 or any(not 1 <= b <= 32000 for b in options.research_budgets+options.document_budgets):
        parser.error('bounded repeats/budgets required')
    asyncio.run(run(options))
