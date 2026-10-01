import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('w6_eval', root / 'scripts/eval/work_check_eval.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
sys.stdout.reconfigure(encoding='utf-8')

async def main():
    assert subprocess.check_output(['git','branch','--show-current'],cwd=root,text=True).strip() == 'B'
    output = (root / (sys.argv[2] if len(sys.argv) > 2 else '.tmp/work-checks/direct-reviews-final')).resolve()
    if not output.is_relative_to(root / '.tmp'):
        raise SystemExit('Output must be under B .tmp')
    output.mkdir(exist_ok=True)
    rows = []
    client = fixture.FixtureClient(sys.argv[1])
    for role in ('review','plan-review','research-review'):
        folder = output / role
        folder.mkdir(exist_ok=True)
        (folder / 'docs').mkdir(exist_ok=True)
        (folder / 'docs/source.md').write_text('Chỉ xuất CSV; không JSON.\n',encoding='utf-8')
        (folder / 'report.md').write_text('# Báo cáo fixture\nNguồn docs/source.md: Chỉ xuất CSV; không JSON.\nKhuyến nghị thêm JSON vào phạm vi.\n',encoding='utf-8')
        (folder / 'src').mkdir(exist_ok=True)
        (folder / 'tests').mkdir(exist_ok=True)
        (folder / 'src/export.py').write_text('def export(value):\n    return value\n',encoding='utf-8')
        (folder / 'tests/test_export.py').write_text('def test_unicode():\n    assert "Hồ sơ" == "Hồ sơ"\n',encoding='utf-8')
        store = fixture.SessionStore(folder / 'sessions.db')
        rt = fixture.HarnessRuntime(store,fixture.FixtureExecutor(folder),client)
        session = rt.create({'connectionId':'w6-isolated-opencode','modelId':'space-bunny-free',
                             'maxSteps':18,'deadlineSeconds':300,'skills':[],'maxTokens':4096})
        report_hash = hashlib.sha256((folder / 'report.md').read_bytes()).hexdigest()
        target = {}
        if role == 'plan-review':
            store.emit(session['id'],'plan_written',{'identity':'fixture-review','version':1,
                'relativePath':'report.md','contentHash':report_hash})
            target = {'reviewTarget':{'kind':'plan','identity':'fixture-review','version':1}}
        elif role == 'research-review':
            store.record_dossier(session['id'],'fixture-review',1,'report.md',content_hash=report_hash)
            target = {'reviewTarget':{'kind':'research','researchId':'fixture-review','version':1,'mode':'critique'}}
        start = time.monotonic()
        result = await rt.delegate(session,{'role':role,
            'goal':'Phản biện report.md theo phạm vi người dùng: chỉ CSV, không JSON. Mở report.md và docs/source.md. Đây là fixture phạm vi đơn giản, không cần thiết kế app hay nguồn web. Chỉ kiểm khuyến nghị có tuân thủ phạm vi không. Câu trả lời cuối tiếng Việt có dấu; cuối cùng VERDICT: ok hoặc VERDICT: revise.',
            'expect':'Một finding cụ thể nếu vượt phạm vi, tham chiếu nguồn đã mở, một dòng VERDICT cuối.',**target})
        child = result.get('sessionId')
        answer = fixture.wg.service(rt).child_answer(child)
        attempts = [json.loads(r['payload']) for r in store.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='completion_attempt'",(child,))]
        rows.append({'role':role,'model':'opencode/space-bunny-free','status':result.get('status'),
            'latencySeconds':round(time.monotonic()-start,3),'answer':answer,'completionAttempts':attempts,
            'oracle':result.get('status')=='completed' and answer.strip().endswith('VERDICT: revise')})
        (output/'results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:rows[-1][k] for k in ('role','status','oracle','latencySeconds')},ensure_ascii=False),flush=True)
        store.db.close()

asyncio.run(main())
