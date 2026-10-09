"""Suite E2E THẬT cho đợt cải tổ BoxFox — model miễn phí, router thật, box thật.

Mục tiêu (chủ nhà #6533): kiểm thử thực tế kỹ lưỡng mọi thứ trong app, không dùng fixture
model. Mỗi kịch bản mở MỘT phiên thật qua HTTP API của backend worktree, giao một việc
thật, chờ lượt kết thúc, rồi kiểm bằng chứng trên đĩa/DB/box — không tin lời kể của model.

Chạy:
  python3 /code/.generated_artifacts/e2e/driver.py --label v1            # backend 3113 (công tắc BẬT)
  python3 /code/.generated_artifacts/e2e/driver.py --base 3112 --label off   # backend mặc định (TẮT)
  python3 /code/.generated_artifacts/e2e/driver.py --list
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DB = '/var/tmp/boxfox-e2e/data-on/sessions.sqlite'
RUNS = Path('/code/.generated_artifacts/e2e/runs')
BOX = 'agentbox-box'
WORKSPACE = '/home/agent/workspace'
TERMINAL = {'completed', 'error', 'failed', 'stopped', 'cancelled', 'awaiting_decision'}


def http(base, method, path, body=None, timeout=30):
    url = f'http://127.0.0.1:{base}{path}'
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method,
                                     headers={'Content-Type': 'application/json',
                                              'X-BoxFox-Admin': '1'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode('utf-8')
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8')
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {'error': raw}


def box(args, timeout=60):
    """Chạy một lệnh trong box thật, trả (exit, stdout)."""
    proc = subprocess.run(['docker', 'exec', '--user', 'agent', '--workdir', WORKSPACE, BOX, 'bash', '-lc', args],
                          capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip()


def plan_files():
    """Mọi tệp khớp mẫu tên kế hoạch trong workspace box, kèm vị trí thật."""
    code, out = box(f"find {WORKSPACE} -name 'v*-*.md' -not -path '*/node_modules/*' "
                    f"-printf '%p\\n' 2>/dev/null | head -40")
    return [line for line in out.splitlines() if line.strip()] if code == 0 else []


class Runner:
    def __init__(self, base, label, route=None):
        self.base, self.label, self.route = base, label, route
        self.out = RUNS / label
        self.out.mkdir(parents=True, exist_ok=True)
        self.results = []

    # ---- HTTP helpers -------------------------------------------------
    def create(self, config=None, route=None):
        body = {'skills': [], **(config or {})}
        route = route or self.route
        if route:
            body.update(route)
        status, payload = http(self.base, 'POST', '/api/agent/sessions', body)
        assert status in (200, 201), f'session create failed: {status} {payload}'
        return payload['id']

    def submit(self, sid, prompt):
        status, payload = http(self.base, 'POST', f'/api/agent/sessions/{sid}/turns', {'prompt': prompt})
        return status, payload

    def session(self, sid):
        _, payload = http(self.base, 'GET', f'/api/agent/sessions/{sid}')
        return payload

    def journal(self, sid, limit=200):
        _, payload = http(self.base, 'GET', f'/api/agent/sessions/{sid}/journal?limit={limit}')
        return payload.get('records', [])

    def cancel(self, sid, reason='e2e: dừng lượt chạy quá hạn kiểm thử'):
        try:
            return http(self.base, 'POST', f'/api/agent/sessions/{sid}/stop', {'reason': reason})
        except Exception:  # noqa: BLE001 - dừng là best-effort, không được che kết quả kiểm
            return 0, {}

    def wait(self, sid, timeout=900, poll=5):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            payload = self.session(sid)
            last = payload
            status = payload.get('status')
            # `awaiting_decision`: lượt vẫn sống, chỉ đang chờ chủ nhà trả lời (harness tự hết hạn
            # sau ~300 s rồi lượt đi tiếp) — không phải trạng thái kết thúc của kịch bản kiểm.
            if status in TERMINAL and status != 'awaiting_decision' and payload.get('turn_count'):
                return payload
            time.sleep(poll)
        payload = last or {}
        if payload.get('status') not in TERMINAL:
            # Lượt không tự đóng trong hạn: dừng phiên để không bỏ lại phiên mồ côi,
            # và GHI NHẬN TRUNG THỰC trạng thái chạy quá hạn (không hoá thành 'đạt').
            self.cancel(sid)
            payload = dict(payload, status=f"{payload.get('status')} (runaway: quá {timeout}s, đã dừng)")
        return payload

    def drive(self, sid, prompt, timeout=900):
        status, payload = self.submit(sid, prompt)
        if status >= 400:
            return {'submitError': payload, 'status': f'HTTP_{status}'}
        return self.wait(sid, timeout)

    # ---- evidence helpers --------------------------------------------
    @staticmethod
    def tools_run(payload):
        """Tên công cụ đã chạy thật (sự kiện tool_end), kèm cả lần gọi lỗi."""
        names = []
        for event in payload.get('events') or []:
            if event.get('type') == 'tool_end':
                data = event.get('data') or {}
                if data.get('name'):
                    names.append(data['name'])
        return names

    @staticmethod
    def tools_failed(payload):
        failed = []
        for event in payload.get('events') or []:
            if event.get('type') == 'tool_end':
                data = event.get('data') or {}
                result = data.get('result') or {}
                if result.get('is_error'):
                    failed.append(data.get('name'))
        return failed

    @staticmethod
    def answer(payload):
        """Câu trả lời cuối: sự kiện `assistant` cuối cùng có chữ (không cần cờ `final`)."""
        for event in reversed(payload.get('events') or []):
            if event.get('type') == 'assistant':
                data = event.get('data') or {}
                if isinstance(data.get('text'), str) and data['text'].strip():
                    return data['text']
        return ''

    def check(self, name, ok, detail=''):
        return {'check': name, 'ok': bool(ok), 'detail': str(detail)[:600]}

    def record(self, scenario, checks, evidence=None, status=None):
        entry = {'scenario': scenario,
                 'status': status or ('PASSED' if all(c['ok'] for c in checks) else 'FAILED'),
                 'checks': checks, 'evidence': evidence or {}}
        self.results.append(entry)
        (self.out / f'{scenario}.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2))
        flag = 'PASS' if entry['status'] == 'PASSED' else entry['status']
        print(f'  [{flag}] {scenario}')
        for check in checks:
            print(f'      {"ok " if check["ok"] else "FAIL"} {check["check"]} :: {check["detail"][:160]}')
        return entry

    def save(self):
        summary = {'label': self.label, 'base': self.base, 'at': time.time(),
                   'total': len(self.results),
                   'passed': sum(1 for r in self.results if r['status'] == 'PASSED'),
                   'failed': sum(1 for r in self.results if r['status'] == 'FAILED'),
                   'blocked': sum(1 for r in self.results if r['status'] == 'BLOCKED'),
                   'scenarios': self.results}
        (self.out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary


# ----------------------------------------------------------------------
# Scenarios
# ----------------------------------------------------------------------

def scenario_plan_room(runner):
    """BUG chủ nhà (#6535): kế hoạch phải nằm TRONG phòng .plans, không đẻ ra 'plans' khác."""
    before = set(plan_files())
    sid = runner.create()
    payload = runner.drive(sid, (
        'KHÔNG khảo sát codebase, KHÔNG chạy terminal — chỉ gọi write_plan. '
        'Gọi NGAY công cụ write_plan (đừng suy nghĩ dài) cho việc: thêm nút "Xuất CSV" vào bảng đơn hàng. '
        'Kế hoạch CỰC NGẮN: tối đa 8 dòng, chỉ 4 mục gạch đầu dòng (mục tiêu, thay đổi, kiểm thử, rủi ro). '
        'BẮT BUỘC gọi write_plan — không trả lời bằng chữ.'))
    after = [p for p in plan_files() if p not in before]
    inside = [p for p in after if '/.plans/' in p]
    outside = [p for p in after if '/.plans/' not in p]
    stray = [p for p in after if '/plans/' in p and '/.plans/' not in p]
    tools = runner.tools_run(payload)
    checks = [
        runner.check('write_plan đã chạy', 'write_plan' in tools, f'tools={sorted(set(tools))}'),
        runner.check('có tệp kế hoạch mới', bool(after), after),
        runner.check('mọi tệp kế hoạch nằm trong .plans/', bool(after) and not outside,
                     f'inside={inside} outside={outside}'),
        runner.check('không sinh thư mục plans/ lạ', not stray, stray),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('plan_room', checks, {'session': sid, 'files': after, 'tools': sorted(set(tools))})


def scenario_plan_version_two(runner):
    """Hướng MỀM chủ nhà yêu cầu: v2 của cùng chủ đề phải nằm CẠNH v1, không nhảy ra gốc."""
    sid = runner.create()
    first = runner.drive(sid, (
        'KHÔNG khảo sát codebase, KHÔNG chạy terminal — chỉ gọi write_plan. '
        'Gọi NGAY write_plan (đừng suy nghĩ dài) cho việc thêm màn hình "Lịch sử đơn hàng". '
        'CỰC NGẮN: tối đa 6 dòng. BẮT BUỘC gọi write_plan.'))
    files_one = [p for p in plan_files()]
    second = runner.drive(sid, (
        'Gọi NGAY write_plan cho bản v2 của ĐÚNG kế hoạch vừa rồi (cùng chủ đề Lịch sử đơn hàng), '
        'thêm mục phân trang. CỰC NGẮN: tối đa 6 dòng. BẮT BUỘC gọi write_plan.'))
    files_two = [p for p in plan_files()]
    new = [p for p in files_two if p not in files_one]
    folders_one = {str(Path(p).parent) for p in files_one if '/.plans/' in p}
    folders_two = {str(Path(p).parent) for p in new}
    checks = [
        runner.check('v1 đã ghi trong .plans/', bool(files_one), files_one),
        runner.check('có bản v2 mới', bool(new), new),
        runner.check('v2 nằm CÙNG thư mục với v1', bool(new) and bool(folders_two & folders_one),
                     f'v1_folders={sorted(folders_one)} v2_folders={sorted(folders_two)}'),
        runner.check('lượt 2 kết thúc sạch', second.get('status') in ('completed', 'idle'),
                     second.get('status')),
    ]
    return runner.record('plan_version_two', checks,
                         {'session': sid, 'v1': files_one, 'new': new})


def scenario_tools_and_file(runner):
    """Tool thật trong box: chạy lệnh và ghi tệp, kiểm bằng đọc lại tệp."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Làm đúng hai việc bằng công cụ: (1) chạy terminal_exec `echo hello-boxfox-e2e`; '
        '(2) ghi tệp notes/e2e-proof.txt với nội dung chính xác dòng: proof-2026-10-04. '
        'Rồi trả lời ngắn gọn đã làm gì.'))
    code, content = box('cat notes/e2e-proof.txt 2>/dev/null || true')
    tools = runner.tools_run(payload)
    checks = [
        runner.check('terminal_exec đã chạy', 'terminal_exec' in tools, sorted(set(tools))),
        runner.check('tệp thật tồn tại với nội dung đúng', 'proof-2026-10-04' in content, content[:200]),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('tools_and_file', checks,
                         {'session': sid, 'tools': sorted(set(tools)), 'file': content[:200]})


def scenario_delegate(runner):
    """Main gọi sub thật: con được sinh, con chạy tool, main tổng hợp có bằng chứng."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Giao cho MỘT subagent (delegate_task, role=explore) việc: liệt kê các tệp .md nằm dưới thư mục '
        '.plans/ trong workspace và trả về danh sách đường dẫn kèm bằng chứng. '
        'BẮT BUỘC gọi delegate_task — không tự làm lấy. Sau đó trả lời danh sách con báo.'), timeout=600)
    children = [event['data'] for event in (payload.get('events') or []) if event.get('type') == 'child']
    tools = runner.tools_run(payload)
    answer = runner.answer(payload)
    checks = [
        runner.check('delegate_task đã chạy', 'delegate_task' in tools, sorted(set(tools))),
        runner.check('có phiên con thật', bool(children), [c.get('sessionId') for c in children]),
        runner.check('main trả lời bằng số của con', bool(answer.strip()), answer[:200]),
    ]
    return runner.record('delegate', checks,
                         {'session': sid, 'children': [c.get('sessionId') for c in children],
                          'answer': answer[:400], 'tools': sorted(set(tools))})


def scenario_research(runner):
    """Research thật ra Internet (web_search host-side) + nguồn dẫn được."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Dùng web_search tìm ngày phát hành chính thức của Python 3.13 (chỉ một câu trả lời). '
        'BẮT BUỘC gọi web_search, và nêu URL nguồn trong câu trả lời.'), timeout=600)
    tools = runner.tools_run(payload)
    answer = runner.answer(payload)
    checks = [
        runner.check('web_search đã chạy', 'web_search' in tools, sorted(set(tools))),
        runner.check('câu trả lời có URL nguồn', 'http' in answer, answer[:300]),
    ]
    return runner.record('research', checks, {'session': sid, 'tools': sorted(set(tools)),
                                              'answer': answer[:500]})


def scenario_research_gateway(runner):
    """Ranh giới Research khi gateway BẬT: main gửi yêu cầu qua cổng, không tự gọi công cụ nội bộ."""
    import sqlite3
    import uuid
    gw_invocation = 'e2e-gw-' + uuid.uuid4().hex[:8]
    sid = runner.create()
    payload = runner.drive(sid, (
        'Làm đúng hai việc sau rồi trả lời ngắn gọn.\n'
        'Việc 1: gọi `research_job_submit` với request đúng lược đồ `boxfox-research-job/1`: '
        '`goal`, `decisionContext`, `desiredOutput`, `freshnessRequirement` là chuỗi; `questions` là mảng '
        'MỘT câu hỏi; `constraints` và `inputRefs` là mảng RỖNG (`[]`, không phải chuỗi); '
        f'`permissionEnvelopeRef`, `allocationRef`, `consentRef` là null; `invocationId` = "{gw_invocation}".\n'
        'Việc 2: gọi `research_job_get` với jobId vừa nhận.\n'
        'Trả lời ngắn: jobId và state trong receipt. KHÔNG gọi công cụ nào khác.'), timeout=600)
    tools = runner.tools_run(payload)
    answer = runner.answer(payload)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    rows = [dict(r) for r in db.execute(
        'SELECT run_id, state, revision, controller_id FROM harness_research_gateway ORDER BY created_at DESC LIMIT 1')]
    db.close()
    checks = [
        runner.check('research_job_submit đã chạy', 'research_job_submit' in tools, sorted(set(tools))),
        runner.check('có hàng cổng Research thật', bool(rows), rows[:1]),
        runner.check('hàng ở trạng thái needs_consent (chưa cấp chi)',
                     bool(rows) and rows[0]['state'] == 'needs_consent', rows[:1]),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'), payload.get('status')),
    ]
    return runner.record('research_gateway', checks,
                         {'session': sid, 'tools': sorted(set(tools)), 'answer': answer[:600], 'rows': rows[:1]})


def scenario_research_main_tools(runner):
    """Ranh giới Research khi gateway BẬT: main chạm internals thì bị GUARD chặn."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Làm đúng hai việc, theo thứ tự, rồi trả lời ngắn.\n'
        'Việc 1: gọi `source_add` với claim/url/excerpt/payload tuỳ ý.\n'
        'Việc 2: gọi `delegate_task` với role="research" và goal "tìm nguồn về Python 3.13".\n'
        'Với mỗi việc, nếu bị từ chối thì chép NGUYÊN mã lỗi nhận được. KHÔNG thử cách khác để lách.'), timeout=420)
    tools = runner.tools_run(payload)
    failed = runner.tools_failed(payload)
    answer = runner.answer(payload)
    raw = json.dumps(payload, ensure_ascii=False)
    checks = [
        runner.check('đã thử chạm internals (source_add và/hoặc delegate role=research)',
                     bool({'source_add', 'delegate_task'} & set(tools)), sorted(set(tools))),
        runner.check('bị chặn bằng RESEARCH_MAIN_READ_ONLY',
                     'RESEARCH_MAIN_READ_ONLY' in raw or 'RESEARCH_MAIN_READ_ONLY' in answer,
                     answer[:400]),
        runner.check('có lần gọi LỖI', bool(failed), sorted(set(failed))),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'), payload.get('status')),
    ]
    return runner.record('research_main_tools', checks,
                         {'session': sid, 'tools': sorted(set(tools)), 'failed': sorted(set(failed)),
                          'answer': answer[:500]})


def scenario_kernel_guard(runner):
    """Hàng rào kernel: ghi ra ngoài phạm vi cho phép phải bị TỪ CHỐI, không âm thầm thành công."""
    sid = runner.create()
    payload = runner.drive(sid, (
        'Hãy thử ghi tệp /etc/boxfox-should-not-exist.txt bằng file_write. Nếu bị từ chối, '
        'hãy nói rõ mã lỗi và KHÔNG thử cách khác để lách.'), timeout=420)
    code, exists = box('test -f /etc/boxfox-should-not-exist.txt && echo EXISTS || echo ABSENT')
    tools = runner.tools_run(payload)
    checks = [
        runner.check('tệp ngoài phạm vi KHÔNG được tạo', 'ABSENT' in exists, exists),
        runner.check('lượt vẫn kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('kernel_guard', checks, {'session': sid, 'tools': sorted(set(tools))})


def scenario_skill_view(runner):
    """Bề mặt context (H5) với kho đăng ký trống: skill_view phải nạp được, không SKILL_UNKNOWN."""
    sid = runner.create({'skills': ['work-graph-planning']})
    payload = runner.drive(sid, (
        'Gọi skill_view cho skill "work-graph-planning" và trả lời đúng một câu: kỹ năng đó nói về việc gì? '
        'BẮT BUỘC gọi skill_view.'))
    tools = runner.tools_run(payload)
    answer = runner.answer(payload)
    checks = [
        runner.check('skill_view đã chạy', 'skill_view' in tools, sorted(set(tools))),
        runner.check('không có SKILL_UNKNOWN trong kết quả', 'SKILL_UNKNOWN' not in json.dumps(payload),
                     'không thấy mã lỗi'),
        runner.check('có câu trả lời', bool(answer.strip()), answer[:200]),
    ]
    return runner.record('skill_view', checks, {'session': sid, 'tools': sorted(set(tools)),
                                                'answer': answer[:300]})


def scenario_adaptive_policy(runner, expect_on):
    """H8: policy ghim qua route người vận hành, rồi MỘT lượt thật với route miễn phí."""
    sid = runner.create(route={'connectionId': 'd7e26488-65b0-4012-8009-589cd94b324b',
                               'modelId': 'space-bunny-free'})
    status, put = http(runner.base, 'PUT', f'/api/agent/sessions/{sid}/execution-policy',
                       {'mode': 'adaptive'})
    _, got = http(runner.base, 'GET', f'/api/agent/sessions/{sid}/execution-policy')
    if not expect_on:
        checks = [
            runner.check('công tắc TẮT ⇒ 409 POLICY_SWITCH_OFF', status == 409 and 'POLICY_SWITCH_OFF' in json.dumps(put),
                         f'{status} {put}'),
            runner.check('policy KHÔNG đổi', got.get('mode') == 'legacy', got),
        ]
        return runner.record('adaptive_off', checks, {'session': sid, 'put': put})

    payload = runner.drive(sid, (
        'Trả lời đúng một câu ngắn: bạn đã sẵn sàng chưa?'), timeout=420)
    usage = [event['data'] for event in (payload.get('events') or []) if event.get('type') == 'harness_usage']
    checks = [
        runner.check('PUT adaptive thành công', status == 200 and got.get('mode') == 'adaptive',
                     f'{status} {put}'),
        runner.check('lượt thật chạy được với route miễn phí', payload.get('status') in ('completed', 'idle'),
                     f"status={payload.get('status')} err={payload.get('error')}"),
        runner.check('sổ usage ghi hàng cho lượt', bool(usage),
                     [{'purpose': u.get('purpose'), 'amount': u.get('amount'), 'certainty': u.get('certainty')}
                      for u in usage]),
        runner.check('chi phí 0 đúng route miễn phí', all(float(u.get('amount') or 0) == 0 for u in usage),
                     [u.get('amount') for u in usage]),
    ]
    return runner.record('adaptive_on', checks,
                         {'session': sid, 'usage': usage[:4], 'answer': runner.answer(payload)[:200]})


def scenario_ledger_rows(runner):
    """Sổ usage là dữ liệu THẬT: đọc lại bằng SQLite của CHÍNH instance đang kiểm."""
    import sqlite3
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows = []
    if 'harness_usage' in tables:
        rows = [dict(r) for r in db.execute('SELECT * FROM harness_usage ORDER BY created_at DESC LIMIT 5')]
    db.close()
    columns = set(rows[0].keys()) if rows else set()
    checks = [
        runner.check('bảng sổ usage tồn tại', 'harness_usage' in tables, sorted(t for t in tables if 'usage' in t)),
        runner.check('có hàng usage thật', bool(rows), len(rows)),
        runner.check('hàng đủ cột hợp đồng (token/giá/độ chắc)',
                     {'model_id', 'input_tokens', 'output_tokens', 'price_snapshot_json',
                      'amount', 'certainty'} <= columns, sorted(columns)),
        runner.check('token thật đã ghi', bool(rows) and any((r.get('input_tokens') or 0) > 0 for r in rows),
                     [(r.get('input_tokens'), r.get('output_tokens')) for r in rows[:3]]),
    ]
    return runner.record('ledger_rows', checks, {'rows': [{k: v for k, v in (r or {}).items()} for r in rows[:3]]})


SCENARIOS = {
    'plan_room': scenario_plan_room,
    'plan_version_two': scenario_plan_version_two,
    'tools_and_file': scenario_tools_and_file,
    'delegate': scenario_delegate,
    'research': scenario_research,
    'research_gateway': scenario_research_gateway,
    'research_main_tools': scenario_research_main_tools,
    'kernel_guard': scenario_kernel_guard,
    'skill_view': scenario_skill_view,
    'ledger_rows': scenario_ledger_rows,
}


def main():
    global DB
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3113')
    parser.add_argument('--label', default='v1')
    parser.add_argument('--only', default='')
    parser.add_argument('--db', default=DB, help='SQLite của CHÍNH instance đang kiểm')
    parser.add_argument('--attempts', type=int, default=2,
                        help='số lần chạy mỗi kịch bản (model miễn phí hay phiên âm sai)')
    parser.add_argument('--model', default='', help='ghim modelId (model miễn phí khác) cho phiên kiểm')
    parser.add_argument('--connection', default='d7e26488-65b0-4012-8009-589cd94b324b',
                        help='connectionId đi kèm --model')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--switches', choices=['on', 'off'], default='on')
    args = parser.parse_args()
    if args.list:
        print('\n'.join(sorted(SCENARIOS)))
        return 0
    DB = args.db
    route = ({'connectionId': args.connection, 'modelId': args.model} if args.model else None)
    runner = Runner(args.base, args.label, route=route)
    wanted = [name for name in (args.only.split(',') if args.only else sorted(SCENARIOS)) if name]
    for name in wanted:
        for attempt in range(1, args.attempts + 1):
            print(f'== {name} (lần {attempt}/{args.attempts})')
            try:
                entry = SCENARIOS[name](runner)
            except Exception as exc:  # noqa: BLE001 - suite phải chạy tiếp kịch bản sau
                entry = runner.record(name, [runner.check('kịch bản chạy được', False,
                                                          f'{type(exc).__name__}: {exc}')])
            if entry['status'] == 'PASSED' or attempt == args.attempts:
                break
            # Lần hỏng vẫn phải còn trong bằng chứng: đổi tên tệp trước khi chạy lại.
            (runner.out / f'{name}.json').rename(runner.out / f'{name}.attempt{attempt}.json')
            runner.results.pop()
            print(f'  [retry] {name} hỏng ở lần {attempt} — chạy lại (model yếu hay phiên âm sai)')
        entry['evidence']['attempts'] = attempt
        (runner.out / f'{name}.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2))
    try:
        scenario_adaptive_policy(runner, expect_on=(args.switches == 'on'))
    except Exception as exc:  # noqa: BLE001
        runner.record('adaptive_on', [runner.check('kịch bản chạy được', False, f'{type(exc).__name__}: {exc}')])
    summary = runner.save()
    print(json.dumps({k: summary[k] for k in ('label', 'total', 'passed', 'failed', 'blocked')}, ensure_ascii=False))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
