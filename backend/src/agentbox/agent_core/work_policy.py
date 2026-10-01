"""Minimum verification policy. Roles route work; they cannot waive artifact checks."""
import hashlib
import json
import re

from . import work_prompts

VERSION = 'work-checks/2'
TASKS = ('lookup', 'diagnostic', 'deliverable', 'implementation')
ARTIFACTS = ('knowledge', 'diagnostic', 'research', 'design', 'plan', 'patch', 'test_report')
RISKS = ('normal', 'consequential')
CONSEQUENTIAL = re.compile(
    r'medical|clinical|health|legal|security|auth|migration|production|irreversible|'
    r'y tế|bệnh án|pháp lý|bảo mật|xác thực|di trú|mất dữ liệu', re.I)
PLAN_CONTENT = re.compile(r'^#{1,4}\s+.*(?:milestones|implementation plan|sub-plan|'
                          r'kế hoạch triển khai|mốc triển khai|lộ trình triển khai)', re.I | re.M)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def definition(node):
    return digest({k: v for k, v in node.items() if k != 'stages'})


def research_only(run):
    producers = [n for n in run['nodes'] if 'produce' in n['stages']]
    return run['flow'] == 'research' and bool(producers) and all(
        n['stages']['produce'].get('policy', {}).get('artifactKind') in ('knowledge', 'research')
        for n in producers)


def derive(run, node, stage, text='', changed=False, code_risk=False):
    kind = node['kind']
    artifact = node.get('artifactKind') or {
        'explore': 'knowledge', 'debug': 'diagnostic', 'testing': 'test_report'
    }.get(kind, kind if kind in ARTIFACTS else 'patch')
    if kind == 'research' and node.get('taskKind') == 'lookup' and not node.get('artifactKind'):
        artifact = 'knowledge'
    # Execution of a plan is code, even if the producer describes it as a report.
    if changed or (stage == 'execute' and (kind in ('plan', 'build', 'simplify')
                                          or kind == 'debug' and node.get('taskKind') == 'implementation')):
        artifact = 'patch'
    elif kind == 'plan' or artifact == 'plan' or PLAN_CONTENT.search(text):
        artifact = 'plan'
    elif kind == 'design':
        artifact = 'design'
    elif kind == 'research' and node.get('taskKind') != 'lookup':
        artifact = 'research'
    risk = 'consequential' if code_risk or node.get('risk') == 'consequential' or CONSEQUENTIAL.search(
        run.get('goal', '') + ' ' + node['goal']) else 'normal'
    checks = []

    def add(cid, role, criterion):
        translations = {
            'tests': 'Chạy từng lệnh test bắt buộc trên đúng snapshot mã; báo lỗi trung thực.',
            'code_review': 'Kiểm hành vi, hợp đồng, an toàn dữ liệu và ca biên trong thay đổi thực.',
            'plan_review': 'Plan SWE/AI cụ thể: kiến trúc, dữ liệu, hợp đồng, milestone, test; không bịa dữ kiện hoặc quyết định người dùng.',
            'design_review': 'Kiểm đúng loại thiết kế, thống nhất hợp đồng/trạng thái/lỗi và phạm vi người dùng.',
            'evidence': 'Mở nguồn gốc quan trọng; kiểm nguồn hỗ trợ khẳng định/trích dẫn hoặc nguyên nhân, phạm vi, trái chiều và giới hạn.',
            'critique': 'Phản biện suy luận/khuyến nghị theo ràng buộc người dùng; citation hợp lệ chưa chứng minh khuyến nghị đúng.',
        }
        criterion = work_prompts.choose(work_prompts.language(run.get('goal', '')), criterion, translations[cid])
        checks.append({'id': cid, 'executorRole': role, 'criterion': criterion})

    if artifact == 'patch':
        add('tests', 'testing', 'Execute every required test on this exact code snapshot; report failures honestly.')
        if risk == 'consequential':
            add('code_review', 'review', 'Review behavior, contracts, data safety and edge cases in the actual patch.')
    elif artifact == 'plan':
        add('plan_review', 'plan-review', 'Professional SWE/AI plan: concrete architecture/data/contracts/milestones/tests; no invented facts or owner decisions.')
    elif artifact == 'design':
        add('design_review', 'plan-review', 'Check assigned design subtype, contracts/state/error consistency and owner scope.')
    elif artifact == 'research':
        add('evidence', 'research-review', 'Open critical original sources; check claim/quote entailment, scope, contrary evidence and limitations.')
    elif artifact in ('knowledge', 'diagnostic') and risk == 'consequential':
        add('evidence', 'research-review' if kind == 'research' else 'review',
            'Independently verify decision-critical facts/causal evidence against original sources.')
    if risk == 'consequential' and artifact in ('research', 'knowledge', 'diagnostic', 'plan', 'design'):
        add('critique', 'research-review' if kind == 'research' else 'plan-review',
            'Challenge inference and recommendation against owner constraints; valid citations alone do not establish correctness.')
    policy = {'version': VERSION, 'artifactKind': artifact, 'risk': risk,
              'rationale': 'Minimum from task/artifact, owner goal and observed source changes.',
              'required': checks}
    policy['hash'] = digest(policy)
    return policy
