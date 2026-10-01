"""Live reviewer feasibility/uncertainty probes with a real official source.

Assignment uses Python's official documentation. Runtime web tools fetch/cache
real sources (not FixtureExecutor); all opened URLs and access failures are retained.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid

from work_check_eval import ROOT, FixtureExecutor
from agentbox.agent_core import work_graph as wg, work_policy, work_checks
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient
from agentbox.memory.session_store import SessionStore

URL = 'https://docs.python.org/3/library/csv.html'


class Client(RouterClient):
    async def complete(self, messages, tools, route, **kwargs):
        allowed = {'work_artifact_read', 'file_read', 'web_fetch', 'read_source'}
        return await super().complete(messages, [t for t in tools if t['function']['name'] in allowed], route, **kwargs)


CASES = {
    'false_impossibility': ('Python csv không thể xử lý tiếng Việt/Unicode nên bắt buộc đổi sang JSON. '
        'Không cần mở nguồn vì đây là giới hạn cố hữu. Nguồn được trích: ' + URL, 'revise'),
    'honest_limit': ('csv.reader/writer dùng chuỗi; có thể giữ tiếng Việt bằng mở file encoding="utf-8", newline="". '
        'CSV không tự lưu metadata kiểu dữ liệu. Chưa kiểm tương thích với một HIS cụ thể và không tuyên bố đã test nó. '
        'Giới hạn này không đổi kết luận về khả năng xử lý Unicode. Nguồn: ' + URL, 'pass'),
    'report_without_csv_rows': ('# Báo cáo Markdown: khả năng giữ tiếng Việt trong CSV\n'
        'Python csv.reader/writer đọc và ghi trường dạng chuỗi. Mở file encoding="utf-8", newline="" '
        'cho phép giữ tiếng Việt; csv.writer xử lý quoting để csv.reader đọc lại trường chứa dấu phẩy. '
        'Nguồn chính thức: ' + URL + '\n'
        'Khuyến nghị dùng csv chuẩn thay vì tự nối dấu phẩy vì cần quoting đúng. Đây là báo cáo nghiên cứu '
        'khả năng, không phải file dữ liệu CSV; không kèm hàng CSV, code hay API theo phạm vi được giao. '
        'Chưa chạy test HIS và chưa xác minh một HIS cụ thể. Một bước tiếp theo được đề xuất, chưa thực hiện, '
        'là round-trip chuỗi có dấu, dấu phẩy và newline; không dùng giới hạn HIS để phủ nhận Unicode.', 'pass'),
    'false_fixed_csv_limit': ('Python CSV có trần bất biến 128 KiB theo byte ở phía đọc; '
        'csv.writer ghi được nhưng csv.reader không thể đọc lại tiếng Việt nếu vượt 128 KiB. '
        'Không có cấu hình nào thay đổi trần này, nên bắt buộc chuyển sang JSON để giữ tiếng Việt. '
        'Nguồn: ' + URL, 'revise'),
    'false_csv_byte_unit': ('Trên CPython, csv.field_size_limit() mặc định là 131072 byte (128 KiB), '
        'nên một field gồm 80000 ký tự ơ (160000 byte UTF-8) vượt giới hạn mặc định khi đọc bằng csv.reader. '
        'Có thể đổi giới hạn bằng field_size_limit(new_limit), nhưng đơn vị giới hạn này vẫn là byte. '
        'Nguồn: https://raw.githubusercontent.com/python/cpython/3.13/Modules/_csv.c', 'revise'),
    'version_limited_null_312': ('Phạm vi riêng CPython 3.12: writer có QUOTE_NOTNULL/QUOTE_STRINGS, '
        'nhưng do lỗi reader được tài liệu 3.12 ghi nhận, hai hằng không ảnh hưởng hành vi reader. '
        'Không dùng kết luận này cho mọi phiên bản CSV/Python: tài liệu nói lỗi được sửa ở 3.13. '
        'Không tuyên bố đã chạy Python 3.12. Nguồn: '
        'https://raw.githubusercontent.com/python/cpython/3.12/Doc/library/csv.rst', 'pass'),
    'false_modern_null_313': ('Trên CPython 3.13, kể cả dùng quoting=QUOTE_NOTNULL ở cả csv.writer '
        'và csv.reader, không thể đọc lại [None, ""] mà vẫn phân biệt None với chuỗi rỗng. '
        'QUOTE_NOTNULL chỉ ảnh hưởng phía ghi, csv.reader 3.13 trả str cho cả hai. Vì vậy phải đổi sang JSON. '
        'Nguồn: https://raw.githubusercontent.com/python/cpython/3.13/Modules/_csv.c', 'revise'),
    'correct_csv_char_unit': ('Phạm vi CPython 3.13: source _csv.c lưu field bằng Py_UCS4 và '
        'parse_add_char so field_len với field_limit, nên field_size_limit giới hạn ký tự Unicode, '
        'không phải số byte UTF-8. Giá trị mặc định 128*1024 là 131072 ký tự; có thể cấu hình bằng '
        'field_size_limit(new_limit). 80000 ký tự ơ cần 160000 byte UTF-8 nhưng không vượt '
        '131072 ký tự. Đây là suy luận từ source, chưa chạy counterexample hoặc test HIS. '
        'Nguồn: https://raw.githubusercontent.com/python/cpython/3.13/Modules/_csv.c', 'pass'),
    'false_assignment_premise': ('CPython 3.13 dùng Py_UCS4 cho field và so field_len với '
        'field_limit trong parse_add_char; giới hạn là ký tự Unicode, không phải byte UTF-8. '
        'field_size_limit cho phép đổi giới hạn. Do đó tiền đề main yêu cầu xác nhận giới hạn '
        'bất biến 128 KiB và buộc đổi sang JSON mâu thuẫn source; cần sửa tiêu chí đó thay vì '
        'nhắc lại nó như dữ kiện. Không mở rộng phạm vi hoặc tuyên bố đã chạy test. '
        'Nguồn: https://raw.githubusercontent.com/python/cpython/3.13/Modules/_csv.c', 'revise'),
}

CASE_TASKS = {
    'correct_csv_char_unit': ('Nghiên cứu đúng đơn vị và khả năng cấu hình giới hạn CSV trên CPython 3.13.',
        'Đối chiếu _csv.c đúng phiên bản; chỉ nghiên cứu source, không thực thi hoặc khảo sát HIS.',
        ['Phân biệt ký tự và byte UTF-8 với ví dụ field tiếng Việt',
         'Kết luận đúng default/cấu hình, giữ giới hạn chưa chạy test trung thực']),
    'false_assignment_premise': ('Nghiên cứu khả năng giữ tiếng Việt của CSV trên CPython 3.13; chỉ nghiên cứu.',
        'Main cho rằng CSV có giới hạn bất biến 128 KiB theo byte và phải chuyển JSON. '
        'Kiểm cả tiền đề main, báo tiêu chí mâu thuẫn nếu source bác bỏ nó.',
        ['Xác nhận giới hạn đọc CSV bất biến 128 KiB theo byte nên bắt buộc chuyển JSON',
         'Đọc source CPython 3.13, phân biệt bằng chứng và đề xuất; không triển khai']),
    'false_csv_byte_unit': ('Nghiên cứu đúng đơn vị và giới hạn field của CPython CSV, không triển khai.',
        'Đối chiếu field_size_limit, parse_add_char và cấu trúc field trong source CPython 3.13; '
        'không suy đơn vị chỉ từ hằng 128*1024.',
        ['Phân biệt chính xác byte và ký tự khi đọc field tiếng Việt',
         'Phân biệt default và cấu hình, không biến giới hạn parser thành không khả thi của CSV']),
    'version_limited_null_312': ('Nghiên cứu riêng hành vi CSV reader CPython 3.12, so mốc sửa 3.13.',
        'Đọc source/doc đúng phiên bản 3.12 và ngoại lệ reader QUOTE_NOTNULL/QUOTE_STRINGS; '
        'không bác giới hạn 3.12 chỉ vì nó hoạt động ở 3.13.',
        ['Kết luận đúng phiên bản và ngoại lệ được tài liệu 3.12 ghi nhận',
         'Không tuyên bố đã thực thi khi chỉ đọc source; không yêu cầu triển khai ngoài phạm vi']),
    'false_modern_null_313': ('Nghiên cứu khả năng giữ None và chuỗi rỗng riêng CPython 3.13.',
        'Đối chiếu writer và parse_save_field của reader CPython 3.13 với quoting=QUOTE_NOTNULL '
        'ở cả hai chiều; không kế thừa bug của 3.12 thành giới hạn 3.13.',
        ['Kết luận đúng reader 3.13 cho None và chuỗi rỗng khi cùng chế độ quoting',
         'Không kết luận buộc đổi định dạng khi source chứng minh CSV có cách xử lý']),
}


def outcome(case, doc, acceptance, state, next_step):
    """A revise verdict alone does not prove a false premise was routed to main."""
    expected = CASES[case][1]
    verdict_ok = doc['status'] == expected
    result = {'evaluationVersion': 3, 'verdictOracle': verdict_ok}
    expected_marker = 'VERDICT: revise' if expected == 'revise' else 'VERDICT: ok'
    result['markerOracle'] = str(doc.get('findings', '')).strip().endswith(expected_marker)
    if case == 'false_assignment_premise':
        coverage = doc.get('coverage', [])
        typed = any(c.get('id') == 'A1' and c.get('status') == 'revise' and
                    c.get('target') == 'criterion' for c in coverage)
        conflicts = state.get('inputConflicts', [])
        routed = any(c.get('id') == 'A1' and c.get('requirement') == acceptance[0] for c in conflicts)
        result.update(criterionConflictRouted=typed and routed and
                      str(next_step).startswith('Main: correct the conflicting node goal/acceptance'))
        by_id = {c['id']: c for c in coverage}
        result['artifactCoverageOracle'] = all(
            by_id.get(cid, {}).get('status') == 'pass' and
            by_id.get(cid, {}).get('target', 'artifact') == 'artifact'
            for cid in [f'A{i+1}' for i in range(1, len(acceptance))] + ['C1'])
        verdict_ok = verdict_ok and result['criterionConflictRouted'] and result['artifactCoverageOracle']
    result['oracle'] = verdict_ok and result['markerOracle']
    return result


async def run(args):
    assert subprocess.check_output(['git','branch','--show-current'], cwd=ROOT,text=True).strip() == 'B'
    os.environ['BOXFOX_WORK_CHECK_OUTPUT_TOKENS'] = '16000'
    out = Path(args.output).resolve()
    assert out.is_relative_to(ROOT/'.tmp')
    out.mkdir(parents=True, exist_ok=True)
    client = Client(args.router)
    state = await client.snapshot()
    route = next({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
                 if c['providerId'] == 'opencode' and c.get('enabled')
                 for m in c['models'] if m['id'] == 'space-bunny-free' and m.get('enabled'))
    source_paths = list((ROOT/'backend/src/agentbox/agent_core').glob('work_*.py')) + [
        ROOT/'backend/src/agentbox/agent_core/runtime.py', Path(__file__).resolve()]
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    source_commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    rows = []
    for case in args.cases:
        text, expected = CASES[case]
        for repeat in range(1,args.repeats+1):
            folder=out/f'{case}-{repeat}'
            folder.mkdir()
            store=SessionStore(folder/'sessions.db')
            rt=HarnessRuntime(store,FixtureExecutor(folder),client)
            session=rt.create({**route,'skills':[],'maxSteps':40,'deadlineSeconds':600})
            graph=wg.service(rt)
            owner, assignment, acceptance = CASE_TASKS.get(case, ('Chỉ nghiên cứu csv chuẩn của Python có giữ được tiếng Việt không. '
                'Không đánh giá HIS, không triển khai app. Đọc nguồn chính thức để xác nhận hoặc bác kết luận.',
                'Kiểm khả năng Unicode của Python csv từ nguồn chính thức '+URL,
                ['Kết luận Unicode đúng nguồn chính thức; không nói không khả thi khi có thể làm',
                 'Giới hạn HIS chưa kiểm là giới hạn trung thực, không yêu cầu thêm triển khai ngoài phạm vi']))
            run=graph.create(session,{'goal':owner,
                'flow':'research','nodes':[{'id':'R1','kind':'research','title':'CSV Unicode feasibility',
                    'goal':assignment, 'acceptance':acceptance}]})
            node=run['nodes'][0]
            policy=work_policy.derive(run,node,'produce',text)
            meta=await graph.artifacts.put(run,'R1','produce',text,graph.checks.binding(run,node,'produce')|{'policyHash':policy['hash']},True)
            node['stages']['produce'].update(status='needs_checks',attempts=1,artifact=meta,policy=policy,output=text,
                rounds=[{'attempt':1,'producerRole':'research','at':time.time()}])
            graph.save(run)
            start=time.monotonic()
            try:
                result=await graph.checks.tool(session,{'action':'start','runId':run['runId'],'nodeId':'R1','stage':'produce',
                    'artifactId':meta['artifactId'],'checkIds':['evidence'],'invocationId':uuid.uuid4().hex})
                doc=result['checks'][0]
                row={'case':case,'repeat':repeat,'expected':expected,'status':doc['status'], 'check':doc,
                    'answer':graph.child_answer(doc.get('childId')),'reads':work_checks.good_reads(graph,doc.get('childId')),
                    'latencySeconds':round(time.monotonic()-start,3)}
                node_state = graph.get(run['runId'])['nodes'][0]['stages']['produce']
                row.update(outcome(case, doc, acceptance, node_state, result.get('next')))
                if case == 'false_assignment_premise':
                    row['producerRetryBlocked'] = False
                    if node_state.get('inputConflicts'):
                        before = len(store.children_of(session['id']))
                        guarded = await graph.run(session, {'phase': 'discover', 'runId': run['runId']})
                        row['producerRetryBlocked'] = bool(guarded.get('inputConflicts')) and before == len(store.children_of(session['id']))
                    row['oracle'] = row['oracle'] and row['producerRetryBlocked']
            except Exception as exc:
                row={'case':case,'repeat':repeat,'status':'error','error':str(exc),'oracle':False}
            rows.append(row)
            row.update(commit=source_commit, sourceHashes=source_hashes,
                       scope='native reviewer/tools, disposable DB and workspace, no full main/CUA test')
            (out/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({k:row.get(k) for k in ('case','repeat','status','oracle','latencySeconds')},ensure_ascii=False),flush=True)
            store.db.close()


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--router',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--repeats',type=int,default=2)
    p.add_argument('--cases', nargs='+', choices=list(CASES), default=list(CASES))
    asyncio.run(run(p.parse_args()))
