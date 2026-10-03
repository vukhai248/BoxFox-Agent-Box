"""W8.A4.5 — probe thật: check đỏ được phân loại, sửa CÓ ĐIỀU KIỆN, rồi hội tụ ở vòng hai.

Fixture: repo git thật trong `.tmp/` + executor chạy `bash -lc` tại worktree nút. Executor được
"lên cò" để **gieo đỏ THẬT** vào worktree nút ngay trước lệnh checkpoint của harness: nó hạ cấp
`src/export.py` xuống `return text.upper()`, rồi chính harness `git add -A` + commit bản đó thành
commit của lượt sản xuất. Nhờ vậy:

- lượt kiểm `tests` (child Space Bunny THẬT) đỏ và mang bằng chứng lệnh đỏ;
- harness phân loại (`clear` hay `unclassified`), ghi một mục sửa, và chỉ mở child Debug khi
  chưa phân loại được;
- child Build được đánh thức lại (cùng worktree) với findings, tự sửa tệp của nút;
- lượt kiểm thứ hai (child THẬT thứ hai) xanh ⇒ nút được nhận.

Oracle tách đôi: `mechanism` (định tuyến/phân loại/khoá code của harness) và `model` (child thật
báo đỏ rồi tự sửa rồi báo xanh).

Chạy: `python3 scripts/eval/work_repair_loop_eval.py --router <url> --output .tmp/<dir> --manifest <json>`
"""
import argparse
import asyncio
import collections
import hashlib
import json
import re
import shutil
import subprocess
import time
import traceback
import uuid
from pathlib import Path

from work_check_eval import ROOT, HarnessRuntime, SessionStore
from work_worktree_build_eval import Client, GitExecutor, git, make_repo, route_of, snapshot_source
from agentbox.agent_core import output_policy
from agentbox.agent_core import work_checks
from agentbox.agent_core import work_graph as wg
from agentbox.agent_core import work_worktrees

# Cờ FIXTURE của probe (W8.A4.5.N), không phải thay đổi sản phẩm:
# `output_policy.child_budget()` trả `None` cho vai build ⇒ con Build thừa hưởng mặc định 4096 token
# output. Đo thật 02/10/2026: Space Bunny tiêu 3958/4096 token vào reasoning rồi
# `PROVIDER_OUTPUT_TRUNCATED`; nút Build không hoàn tất draft nên checks từ chối mở
# (`WORK_CHECK_NOT_READY`) và vòng sửa không có gì để đo. Probe nâng trần cho RIÊNG con Build trong
# fixture này để đo được cơ chế phân loại/sửa/hội tụ; số đo 4096 giữ nguyên trong
# `/var/tmp/w8-probe-run1-4096/results.json` và trong `fixtureKnobs` của kết quả.
BUILD_CHILD_OUTPUT_TOKENS = 16000
# Trần phiên của engine (`limits.MAX_STEPS_MAX`/`DEADLINE_MAX_SECONDS`). Con `debug` nhận ngân sách
# `lookup_or_execution` = `min(CHILD_MAX_STEPS, trần bước của PHIÊN CHA)`, nên phiên cha 24 bước làm
# con chẩn đoán hết bước giữa chừng (đo ở lượt 15: `STEP_BUDGET_EXHAUSTED`, steps_used 22 ⇒
# `WORK_REPAIR_UNDIAGNOSED`). Từ #6457 engine là 400 bước/7200 s và con 200 bước/3600 s; fixture
# chạy ở ĐÚNG trần mới để phép đo không bị cắt bởi trần bước.
SESSION_MAX_STEPS = 400
SESSION_DEADLINE_SECONDS = 7200


def raise_build_child_output_budget():
    original = output_policy.child_budget

    def patched(role, work=None, task_kind=None):
        # `build` (bản sửa) và `debug` (chẩn đoán của vòng sửa) đều phải gửi một câu trả lời cuối DÀI;
        # mặc định 4096 token output làm câu trả lời bị `PROVIDER_OUTPUT_TRUNCATED` ⇒ `complete()` false
        # ⇒ sản phẩm trả `WORK_REPAIR_UNDIAGNOSED` và nút bị `rejected` (đo ở lượt 13). Đây là nút FIXTURE
        # đã ghi trong `fixtureKnobs`, không phải thay đổi sản phẩm.
        if role in ('build', 'debug') and (work or {}).get('purpose') == 'produce':
            return BUILD_CHILD_OUTPUT_TOKENS
        return original(role, work, task_kind)

    output_policy.child_budget = patched

# W8.A4.5.N — "cò đỏ THẬT" (owner duyệt 03/10/2026). Bản cũ trả traceback CẮM SẴN cho mọi lệnh
# chứa chuỗi 'pytest' (kể cả `echo "hello pytest world"`): model phát hiện đúng là kết quả bịa,
# tự chạy pytest bằng đường khác, thấy xanh thật rồi báo đạt — nên luật `test_proof` không bao
# giờ cho lượt kiểm đầu tự đỏ và `oracle` của W8.A4.5.N không thể đạt (7 lượt probe 02/10).
#
# Nay fixture hạ cấp THẬT `src/export.py` trong worktree nút NGAY TRƯỚC lệnh checkpoint của
# harness, để chính harness commit bản lỗi đó thành commit của lượt sản xuất:
#   - bản ghi của harness (commit + `codeSnapshot`) mang đúng lỗi đã gieo ⇒ lượt kiểm đầu KHÔNG
#     bị `superseded` ("Code changed before check") mà đỏ vì chạy pytest THẬT trên cây thật;
#   - traceback trỏ vào tệp đã track ⇒ bộ phân loại thấy 'trace into tracked files' → `revise`;
#   - vòng sửa chỉ còn một đường: sửa `src/export.py` rồi kiểm lại xanh.
REAL_RED_SOURCE = 'def export_markdown(text):\n    return text.upper()\n'
# Lệnh checkpoint của harness: `cd '<root>' && git add -A … commit … -m 'boxfox(<runId>): B1 attempt 1'`
CHECKPOINT_MARK = re.compile(r"boxfox\((?P<run>[^)]+)\): (?P<node>[^ ]+) attempt (?P<attempt>\d+)")
CD_PREFIX = re.compile(r"^cd (?P<root>'(?:[^']*)'|\S+) && ")

TEST_FILE = '''from src.export import export_markdown


def test_keeps_unicode():
    assert export_markdown("Hồ sơ") == "Hồ sơ"
'''

# Chín tiêu chí nghiệm thu: `work_budget` cấp ngân sách long-check (24 bước) khi criterionCount > 8.
# Lượt kiểm tests đỏ cần thời gian điều tra thật; ngân sách short-check (14 bước) làm child hết bước
# giữa chừng và check trả `error` thay vì `revise` (đo được ở lượt chạy trước của probe này).
ACCEPTANCE = ['export_markdown("Hồ sơ") trả "Hồ sơ"',
              'export_markdown("") trả ""',
              'export_markdown giữ nguyên ký tự xuống dòng trong văn bản nhiều dòng',
              'export_markdown không thêm tiêu đề hay khung bao ngoài nội dung',
              'export_markdown nhận None và trả chuỗi rỗng thay vì lỗi',
              'export_markdown giữ nguyên khoảng trắng bên trong một dòng',
              'export_markdown bỏ khoảng trắng thừa ở đầu và cuối mỗi dòng',
              'export_markdown giữ nguyên chữ số và dấu câu của văn bản gốc',
              'export_markdown là hàm thuần, gọi hai lần cho cùng kết quả']
NODE = {'id': 'B1', 'kind': 'build', 'title': 'Giữ dấu tiếng Việt khi export',
        'goal': 'Viết src/export.py sao cho export_markdown giữ nguyên dấu tiếng Việt; chỉ sửa src/export.py.',
        'acceptance': ACCEPTANCE, 'tests': ['python -m pytest -q'],
        'files': ['src/export.py'], 'dependsOn': []}


class RepairExecutor(GitExecutor):
    """Như `GitExecutor`, nhưng khi được bật thì GIEO đỏ THẬT vào worktree nút lúc harness checkpoint.

    Mọi lệnh của child vẫn chạy THẬT (không còn kết quả cắm sẵn): lượt kiểm đỏ vì `python -m
    pytest -q` thật sự thất bại trên cây đã bị hạ cấp. Việc gieo chỉ xảy ra MỘT lần và chỉ đúng
    lúc harness `git add -A` + commit lượt sản xuất, nên nó nằm trong `codeSnapshot` của artifact
    — nếu gieo sau đó, sản phẩm sẽ trả `superseded` ("Code changed before check") chứ không đỏ.
    """

    def __init__(self, folder, store=None):
        super().__init__(folder)
        self.store = store
        self.armed = False
        self.seeded = 0
        self.seeds = []
        self.seedErrors = []
        self.roles = {}
        self.pytestByRole = collections.Counter()

    def arm(self):
        self.armed = True

    def disarm(self):
        self.armed = False

    def role(self, sid):
        if sid not in self.roles:
            row = self.store.db.execute('SELECT role FROM sessions WHERE id=?', (sid,)).fetchone() \
                if self.store is not None else None
            self.roles[sid] = row['role'] if row else None
        return self.roles[sid]

    def seed_real_red(self, command, sid):
        """Hạ cấp `src/export.py` trong worktree nút rồi để checkpoint của harness commit nó.

        `work_worktrees` ghi `path` của worktree dưới dạng TƯƠNG ĐỐI (`.boxfox/worktrees/...`), nên
        phải giải theo gốc fixture — lượt chạy đầu của bản này gieo hụt vì `Path(tương đối)` trỏ
        vào gốc repo (không có tệp) rồi `return` im lặng; nay ghi lại lỗi thay vì bỏ qua.
        """
        match = CD_PREFIX.match(command)
        if not match:
            self.seedErrors.append({'why': 'không đọc được thư mục worktree từ lệnh checkpoint',
                                    'command': command[:200]})
            return
        raw = match.group('root').strip("'")
        root = Path(raw) if Path(raw).is_absolute() else (self.folder / raw).resolve()
        target = root / 'src' / 'export.py'
        if not target.is_file():
            self.seedErrors.append({'why': 'không thấy src/export.py trong worktree nút',
                                    'root': str(root), 'path': str(target)})
            return
        before = target.read_text(encoding='utf-8')
        target.write_text(REAL_RED_SOURCE, encoding='utf-8')
        proof = subprocess.run(['bash', '-lc', 'python -m pytest -q'], cwd=str(root),
                               capture_output=True, text=True, timeout=300)
        self.seeded += 1
        self.seeds.append({'root': str(root), 'path': str(target), 'sid': sid,
                           'role': self.role(sid),
                           'before': before, 'after': REAL_RED_SOURCE,
                           'sha256': hashlib.sha256(REAL_RED_SOURCE.encode()).hexdigest(),
                           'proof': {'exitCode': proof.returncode,
                                     'tail': (proof.stdout + proof.stderr).strip().splitlines()[-4:]},
                           'at': round(time.time(), 3)})

    async def execute(self, name, args, sid, **identity):
        command = str((args or {}).get('command') or '')
        if name == 'terminal_exec' and self.armed and not self.seeded \
                and CHECKPOINT_MARK.search(command):
            self.seed_real_red(command, sid)
        if name == 'terminal_exec' and 'pytest' in command and self.role(sid) in ('build', 'testing'):
            self.pytestByRole[self.role(sid)] += 1
        return await super().execute(name, args, sid, **identity)


def check_commands(graph, child_id, limit=12):
    return [item.get('args', {}).get('command') for item
            in work_checks.observations(graph, child_id)
            if item.get('name') == 'terminal_exec'][:limit]


def child_summary(store, entry):
    """Tóm tắt con đã được resume để sửa: công cụ đã dùng, có đụng `export.py`, có thấy findings."""
    child_id = (entry or {}).get('buildChildId')
    child = store.get(child_id) if child_id else {}
    events = tool_events(store, child_id)
    return {'id': child_id, 'parent': child.get('parent_id'),
            'tools': [item.get('name') for item in events][:20],
            'wroteExport': any(
                item.get('name') in ('file_write', 'file_edit_block')
                and 'export.py' in json.dumps(item.get('args') or {}, ensure_ascii=False)
                or item.get('name') == 'terminal_exec'
                and 'export.py' in str((item.get('args') or {}).get('command') or '')
                for item in events),
            'sawFindings': bool((entry or {}).get('findingsArtifactId'))
                and (entry or {})['findingsArtifactId'] in json.dumps(child.get('config') or {}, ensure_ascii=False)}


def tool_events(store, child_id):
    if not child_id:
        return []
    rows = store.db.execute('SELECT kind, payload FROM events WHERE session_id=? AND kind=? ORDER BY seq',
                            (child_id, 'tool_start')).fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row['payload']))
        except (TypeError, ValueError):
            continue
    return out


async def adjudicate_input_conflicts(graph, session, run, conflicts):
    """Đóng vai main xử lý xung đột đầu vào theo đúng đường sản phẩm chỉ định.

    Sản phẩm không có hành động "bác xung đột": `next` của `work_graph` chỉ nói main phải sửa lại
    nhiệm vụ bằng `action=update`, và đó cũng là đường DUY NHẤT xoá `state['inputConflicts']`
    (`work_graph.py:886-890`). Đổi định nghĩa nút làm stage reset (mất bản nháp đã sửa) nên probe
    ghi nguyên văn xung đột + tiêu chí cũ/mới rồi mới đổi, và ghi rõ đây là bước do driver làm thay
    owner (duyệt lại), không phải sản phẩm tự làm.
    """
    live = graph.get(run['runId'])
    node = graph.find_node(live, 'B1')
    acceptance = list(node['acceptance'])
    fixed = []
    for item in conflicts:
        requirement = item.get('requirement')
        if requirement in acceptance:
            index = acceptance.index(requirement)
            acceptance[index] = f'{requirement} (giữ nguyên cả chữ hoa/thường)'
            fixed.append({'id': item.get('id'), 'was': requirement, 'now': acceptance[index],
                          'evidence': item.get('evidence')})
    if not fixed:
        return {'done': False, 'reason': 'không tiêu chí nào trong xung đột khớp danh sách nghiệm thu',
                'conflicts': conflicts, 'acceptance': acceptance}
    nodes = [json.loads(json.dumps(n, ensure_ascii=False)) for n in live['nodes']]
    for item in nodes:
        if item['id'] == 'B1':
            item['acceptance'] = acceptance
    try:
        graph.graph(session, {'action': 'update', 'runId': run['runId'], 'nodes': nodes})
    except ValueError as exc:
        return {'done': False, 'reason': f'action=update bị từ chối: {exc}', 'fixed': fixed}
    after = graph.get(run['runId'])
    after['status'] = 'approved'          # driver làm thay bước owner duyệt lại sau khi sửa nhiệm vụ
    after['executionRequested'] = True
    graph.set_repair_default(after)
    graph.save(after, 'probe_readjudicated')
    node = graph.find_node(after, 'B1')
    produced = await graph.run_stage(session, after, node, 'execute', 3)
    return {'done': True, 'fixed': fixed, 'conflicts': conflicts, 'acceptance': acceptance,
            'productionStatus': produced,
            'state': {k: node['stages']['execute'].get(k) for k in ('status', 'attempts', 'error')}}


async def main(args):
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert branch == 'B' or branch.startswith('vorflux/'), f'nhánh lạ: {branch}'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    snapshot_source(frozen)
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp'), 'output phải nằm trong .tmp/'
    output.mkdir(parents=True, exist_ok=True)
    route = route_of(await Client(args.router).snapshot())
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    route['router'] = args.router

    folder = output / 'repair_loop'
    if folder.exists():  # chạy lại trên cùng thư mục phải sạch như chạy mới
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    repo = make_repo(folder)
    (repo / 'tests').mkdir(exist_ok=True)
    (repo / 'tests' / 'test_export.py').write_text(TEST_FILE, encoding='utf-8')
    (repo / 'src' / 'export.py').write_text('def export_markdown(text):\n    return text\n', encoding='utf-8')
    git(repo, 'add', '.')
    git(repo, 'commit', '-q', '-m', 'fixture export + test')
    baseline = git(repo, 'rev-parse', 'HEAD')

    row = {'case': 'repair_loop_red_then_green', 'sourceManifest': frozen,
           'scope': 'Native: Build produce → kiểm tests THẬT (đỏ do fixture) → phân loại + sửa → kiểm lại xanh',
           'fixtureKnobs': {'buildChildOutputTokens': BUILD_CHILD_OUTPUT_TOKENS,
                            'sessionMaxSteps': SESSION_MAX_STEPS, 'sessionDeadlineSeconds': SESSION_DEADLINE_SECONDS,
                            'why': 'con Build mặc định 4096 token output; lượt chạy 4096 đo được '
                                   'PROVIDER_OUTPUT_TRUNCATED (3958 token reasoning) nên draft không hoàn tất. '
                                   'Lượt 15 đo thêm: con `debug` hết TRẦN BƯỚC (24) giữa chừng ⇒ '
                                   'STEP_BUDGET_EXHAUSTED ⇒ `complete()` false ⇒ WORK_REPAIR_UNDIAGNOSED ⇒ nút '
                                   '`rejected`; nút fixture nâng phiên lên trần engine hiện hành (từ #6457: 400 bước/7200 s, con 200 bước/3600 s) '
                                   'để đo cơ chế sửa thay vì đo trần bước.',
                            'unpatchedRun': '/var/tmp/w8-probe-run1-4096/results.json'}}
    raise_build_child_output_budget()
    started = time.monotonic()
    store = SessionStore(folder.parent / 'repair_loop-sessions.db')
    client = Client(args.router)
    executor = RepairExecutor(folder, store)
    rt = sid = None
    try:
        rt = HarnessRuntime(store, executor, client)
        sid = rt.create({**{k: route[k] for k in ('connectionId', 'modelId')}, 'skills': [],
                         'maxSteps': SESSION_MAX_STEPS, 'deadlineSeconds': SESSION_DEADLINE_SECONDS})['id']
        executor.harness.add(sid)
        graph = wg.service(rt)
        session = store.get(sid)
        run = graph.create(session, {'goal': 'Giữ dấu tiếng Việt khi export Markdown.', 'flow': 'fix', 'nodes': [NODE]})
        run['status'] = 'approved'
        run['executionRequested'] = True
        graph.set_repair_default(run)
        graph.save(run, 'probe_approved')
        iso = await graph.ensure_isolation(session, run, {})
        row['isolation'] = {k: iso.get(k) for k in ('mode', 'branch', 'root')}
        node = run['nodes'][0]
        # W8.A4.5.N — lên cò TRƯỚC lượt sản xuất: đỏ được gieo vào đúng lúc harness checkpoint lượt
        # sản xuất, nên nó nằm trong `codeSnapshot` của artifact (gieo sau đó ⇒ `superseded`).
        executor.arm()
        row['firstStatus'] = await graph.run_stage(session, run, node, 'execute', 3)
        executor.disarm()
        node = graph.find_node(graph.get(run['runId']), 'B1')
        first_artifact = (node['stages']['execute'].get('artifact') or {}).get('artifactId')
        row['firstArtifact'] = first_artifact
        row['firstProducer'] = (node['stages']['execute'].get('rounds') or [{}])[-1].get('producerId')
        row['realRed'] = {'seeded': executor.seeded, 'seeds': executor.seeds,
                          'errors': executor.seedErrors}
        if executor.seeded != 1:
            # Cò đỏ là điều kiện tiên quyết của phép đo: gieo hụt thì mọi số phía sau vô nghĩa,
            # dừng ngay thay vì đốt thêm chục phút để ra một `oracle=false` không nói lên gì.
            raise AssertionError('FIXTURE_RED_NOT_SEEDED: ' + json.dumps(
                {'seeded': executor.seeded, 'errors': executor.seedErrors},
                ensure_ascii=False)[:300])
        row['pytestRuns'] = dict(executor.pytestByRole)
        # Số lệnh pytest THẬT child Build tự chạy trước lượt kiểm (không phải lệnh cắm sẵn như bản cũ).
        row['pytestBeforeCheck'] = sum(executor.pytestByRole.values())

        try:
            red = (await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'], 'nodeId': 'B1',
                   'stage': 'execute', 'artifactId': first_artifact, 'checkIds': ['tests'],
                   'invocationId': uuid.uuid4().hex}))
        except ValueError as exc:
            # Sản phẩm có thể từ chối mở kiểm (ví dụ `WORK_CHECK_STALE`/`WORK_CHECK_NOT_READY`); ghi
            # nguyên văn rồi kết thúc lượt thay vì để traceback khó đọc.
            row['redCheck'] = {'raised': str(exc)[:300]}
            red = {}
        if not red.get('checks'):
            row['redCheck'] = {'empty': True, 'keys': sorted(red),
                               'raw': json.loads(json.dumps({k: v for k, v in red.items() if k != 'checks'},
                                                            ensure_ascii=False, default=str))}
            raise AssertionError(f'WORK_CHECK_NOT_ADMITTED: {json.dumps(row["redCheck"], ensure_ascii=False)[:300]}')
        red_doc = red['checks'][0]
        repair = red.get('repair') or {}
        entry = repair.get('entry') or {}
        # Lượt kiểm ĐẦU có thể chỉ `unverified` (findings bị hạ vì thiếu receipt) rồi lượt sau mới
        # `revise`; giữ nguyên văn lượt đầu ở `firstCheck` và chỉ nhận "lượt đỏ" khi có mục sửa.
        row['firstCheck'] = {'kind': red_doc['kind'], 'status': red_doc['status'], 'childId': red_doc.get('childId'),
                             'error': red_doc.get('error'), 'repairAction': repair.get('action'),
                             'commands': check_commands(graph, red_doc.get('childId'))}
        row['redCheck'] = dict(row['firstCheck']) if entry else {}
        row['repair'] = entry
        node = graph.find_node(graph.get(run['runId']), 'B1')
        state = node['stages']['execute']
        row['afterRepair'] = {'status': state['status'], 'attempts': state['attempts'],
                              'artifactId': (state.get('artifact') or {}).get('artifactId'),
                              'verdicts': [r.get('verdict') for r in state.get('rounds') or []],
                              'repairs': state.get('repairs')}
        row['resumedChild'] = child_summary(store, entry)

        second_artifact = (state.get('artifact') or {}).get('artifactId')
        if not second_artifact:
            raise AssertionError(f'WORK_REPAIR_NO_DRAFT: status={state["status"]} error={state.get("error")}')
        adjudicated = False
        # `test_proof` đòi child chạy ĐÚNG câu lệnh bắt buộc; child thật hay bọc ống/`echo` nên lượt
        # đầu có thể `unverified`. Thử lại có giới hạn và ghi trung thực từng lượt, không nới luật.
        for attempt in range(1, 5):
            # Lượt trước có thể đã `revise` và được định tuyến sửa ⇒ artifact đổi. Đọc lại artifact hiện
            # hành từng lượt (đối tượng `run` của probe là ảnh chụp cũ) để không bị `WORK_CHECK_STALE`.
            live = graph.find_node(graph.get(run['runId']), 'B1')['stages']['execute']
            current_artifact = (live.get('artifact') or {}).get('artifactId')
            if current_artifact and current_artifact != second_artifact:
                row.setdefault('greenArtifacts', []).append({'attempt': attempt, 'was': second_artifact,
                                                             'now': current_artifact})
                second_artifact = current_artifact
            try:
                green = (await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'], 'nodeId': 'B1',
                         'stage': 'execute', 'artifactId': second_artifact, 'checkIds': ['tests'],
                         'invocationId': uuid.uuid4().hex}))
            except ValueError as exc:
                row.setdefault('greenChecks', []).append({'attempt': attempt, 'raised': str(exc)[:300]})
                break
            if not green.get('checks'):
                conflicts = green.get('inputConflicts') or []
                if conflicts and not adjudicated:
                    # Xung đột đầu vào: lượt kiểm đỏ đã ghi "tiền đề của tiêu chí A* bị bác bỏ" và sản
                    # phẩm chặn mọi lượt kiểm/sản xuất tiếp cho tới khi main sửa lại nhiệm vụ
                    # (`work_checks.py:1076`). Đây là đường có thật, không phải lỗi phép đo; probe đóng
                    # vai main đi đúng đường đó rồi đo tiếp.
                    row['adjudication'] = await adjudicate_input_conflicts(graph, session, run, conflicts)
                    adjudicated = True
                    continue
                # Đo thật: sản phẩm trả về không có check nào — ghi nguyên văn rồi dừng vòng,
                # không che bằng một IndexError khó đọc.
                row.setdefault('greenChecks', []).append({'attempt': attempt, 'empty': True,
                                                          'keys': sorted(green), 'raw': json.loads(json.dumps(
                                                              {k: v for k, v in green.items() if k != 'checks'},
                                                              ensure_ascii=False, default=str))})
                break
            green_doc = green['checks'][0]
            record = {'kind': green_doc['kind'], 'status': green_doc['status'], 'attempt': attempt,
                      'childId': green_doc.get('childId'), 'error': green_doc.get('error'),
                      'artifactId': second_artifact,
                      'commands': check_commands(graph, green_doc.get('childId'))}
            row.setdefault('greenChecks', []).append(record)
            if green.get('repair'):
                # W8.A4.5: lượt kiểm có thể tự `revise` và được định tuyến sửa — ghi lại nguyên văn vì
                # đây chính là cơ chế cần đo.
                repair_doc = json.loads(json.dumps(green['repair'], ensure_ascii=False, default=str))
                row.setdefault('greenRepairs', []).append(repair_doc)
                if not row.get('repair'):
                    # Lượt ĐỎ thật đầu tiên. Đo theo lượt thật sự mở vòng sửa, không theo lượt kiểm
                    # đầu tiên: lượt đầu có thể chỉ `unverified` (findings bị hạ vì thiếu receipt).
                    row['repair'] = repair_doc.get('entry') or {}
                    row['redCheck'] = dict(record, repairAction=repair_doc.get('action'))
                    live_state = graph.find_node(graph.get(run['runId']), 'B1')['stages']['execute']
                    row['afterRepair'] = {'status': live_state['status'], 'attempts': live_state['attempts'],
                                          'artifactId': (live_state.get('artifact') or {}).get('artifactId'),
                                          'verdicts': [r.get('verdict') for r in live_state.get('rounds') or []],
                                          'repairs': live_state.get('repairs')}
                    row['resumedChild'] = child_summary(store, row['repair'])
            if green_doc['status'] == 'pass':
                break
        node = graph.find_node(graph.get(run['runId']), 'B1')
        state = node['stages']['execute']
        # Vòng xanh có thể rỗng (chưa từng mở được lượt kiểm nào) — đọc theo `.get`.
        row['greenCheck'] = (row.get('greenChecks') or [{}])[-1]
        row['final'] = {'status': state['status'], 'attempts': state['attempts'],
                        'verdicts': [r.get('verdict') for r in state.get('rounds') or []],
                        'repairs': len(state.get('repairs') or [])}
        # --- W8.A4.5.N: đo native node tổng hợp `__integration__` trên CHÍNH run này.
        # Trước lượt này node ảo chưa từng được đo native; chỉ có code + policy. Đo bằng đường thật:
        # `build_integration` dựng snapshot hợp nhất, rồi `checks.tool` mở child Testing THẬT trên
        # đúng snapshot đó. Không tự sửa fixture để làm xanh.
        integration_row = {'attempted': False, 'reason': None}
        row['integration'] = integration_row
        if state['status'] == 'accepted':
            integration_row['attempted'] = True
            try:
                # `checks.tool`/`run_stage` làm việc trên bản sao đọc từ DB rồi ghi lại; đối tượng `run`
                # của probe là ảnh chụp cũ nên đọc lại bản mới nhất trước khi hợp nhất.
                run = graph.get(run['runId'])
                integration_row['executeStatuses'] = {n['id']: n['stages']['execute']['status']
                                                      for n in run['nodes'] if 'execute' in n['stages']}
                # Sản phẩm CHỈ hợp nhất nút đã nghiệm thu vào nhánh run trong `work_graph
                # action=run phase=execute` (`integrate_nodes` → `build_integration`), và chính nó có
                # hàng rào `WORK_CODE_STALE: an accepted node is not integrated into the run branch`.
                # Gọi thẳng `build_integration` (đo ở lượt 12) dựng artifact trên cây CHƯA hợp nhất nên
                # node tổng hợp kiểm nhầm cây nền — lỗi phép đo, không phải lỗi sản phẩm. Đi đúng
                # đường main: gọi `work_graph action=run phase=execute`, ghi nguyên văn nếu bị chặn.
                try:
                    run_out = await graph.run(session, {'phase': 'execute', 'runId': run['runId']})
                    integration_row['runCall'] = {'status': (run_out or {}).get('status')}
                except Exception as exc:
                    integration_row['runCall'] = {'raised': f'{type(exc).__name__}: {exc}'[:300]}
                run = graph.get(run['runId'])
                integration = run.get('integration') or {}
                accepted = {n['id']: ((n['stages']['execute'].get('artifact') or {}).get('binding', {})
                                      .get('codeCommit') or {}).get('nodeCommit')
                            for n in run['nodes'] if 'execute' in n['stages']}
                branch_root = folder / str((run.get('isolation') or {}).get('root') or '')
                integration_row['merge'] = {
                    'nodes': dict(integration.get('nodes') or {}), 'head': integration.get('head'),
                    'treeHash': integration.get('treeHash'), 'status': integration.get('status'),
                    'baseline': (run.get('isolation') or {}).get('baselineCommit'), 'acceptedCommits': accepted,
                    'branchHead': (git(str(branch_root), 'rev-parse', 'HEAD', check=False) or None)
                    if branch_root.is_dir() else None}
                inode = graph.find_node(run, work_worktrees.INTEGRATION_NODE)
                istate = inode['stages']['execute'] if inode else {}
                ipolicy = istate.get('policy') or {}
                built = (istate.get('status') in ('needs_checks', 'accepted')
                         and bool((istate.get('artifact') or {}).get('artifactId')))
                integration_row.update(built=bool(built), status=istate.get('status'),
                                       required=[r['id'] for r in ipolicy.get('required', [])],
                                       artifactId=(istate.get('artifact') or {}).get('artifactId'))
                if built:
                    iartifact = integration_row['artifactId']
                    # Sản phẩm đòi THỨ TỰ trên node tổng hợp: `tests` phải xanh trên đúng snapshot hợp
                    # nhất TRƯỚC, rồi mới mở `code_review` trên cùng artifact (`WORK_REVIEW_NOT_CONVERGED`
                    # khi mở cả hai cùng lượt — đo được ở lượt 11). Vì vậy mở lần lượt theo `required`.
                    for cid in (integration_row.get('required') or ['tests']):
                        for attempt in range(1, 4):
                            started_check = time.monotonic()
                            try:
                                out = await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'],
                                    'nodeId': work_worktrees.INTEGRATION_NODE, 'stage': 'execute',
                                    'artifactId': iartifact, 'checkIds': [cid],
                                    'invocationId': uuid.uuid4().hex})
                            except ValueError as exc:
                                integration_row.setdefault('checks', []).append(
                                    {'kind': cid, 'attempt': attempt, 'raised': str(exc)[:300]})
                                break
                            if not out.get('checks'):
                                # Cùng lý do như vòng xanh: `checks.tool` có thể trả danh sách rỗng
                                # (đường replay/`inputConflicts`); ghi lại nguyên văn thay vì IndexError.
                                integration_row.setdefault('checks', []).append(
                                    {'kind': cid, 'attempt': attempt, 'empty': True, 'keys': sorted(out)})
                                continue
                            idoc = out['checks'][0]
                            integration_row.setdefault('checks', []).append({
                                'kind': idoc['kind'], 'status': idoc['status'], 'attempt': attempt,
                                'childId': idoc.get('childId'), 'error': idoc.get('error'),
                                'seconds': round(time.monotonic() - started_check, 3),
                                'commands': check_commands(graph, idoc.get('childId'))})
                            if idoc['status'] == 'pass':
                                break
                    run = graph.get(run['runId'])
                    inode = graph.find_node(run, work_worktrees.INTEGRATION_NODE)
                    istate = inode['stages']['execute']
                    integration = run.get('integration') or {}
                    integration_row['final'] = {'status': istate.get('status'),
                                                'integrationStatus': integration.get('status'),
                                                'checkIds': integration.get('checkIds'),
                                                'head': integration.get('head'),
                                                'treeHash': integration.get('treeHash'),
                                                'runStatus': run.get('status')}
            except Exception as exc:  # đo thật, ghi thật; không che lỗi
                integration_row.update(error=f'{type(exc).__name__}: {exc}')
        else:
            integration_row['reason'] = f'node chưa accepted (status={state["status"]}); bỏ qua node tổng hợp'

        row['redSeeds'] = executor.seeded
        row['pytestRuns'] = dict(executor.pytestByRole)
        row['ownerHead'] = git(repo, 'rev-parse', 'HEAD')
        # --- oracle cơ chế: do code harness quyết ---
        entry = row['repair'] or {}
        # Lượt kiểm đỏ có thể KHÔNG tồn tại (child trả coverage sai hợp đồng ⇒ `error`, không mở
        # vòng sửa) nên `redCheck` là `{}`; đọc theo `.get` để phép đo ghi đúng "không có lượt đỏ"
        # thay vì nổ `KeyError` và che mất kết cục thật của lượt chạy.
        red_check = row.get('redCheck') or {}
        row['mechanism'] = {
            'oneRepairEntry': len(state.get('repairs') or []) == 1 and entry.get('n') == 1,
            'classified': entry.get('class') in ('clear', 'unclassified'),
            'debugOnlyWhenUnclassified': bool(entry.get('debugChildId')) == (entry.get('class') == 'unclassified'),
            'resumedSameChild': entry.get('resumed') is True and entry.get('buildChildId') == row['firstProducer'],
            'freshArtifactAfterRepair': bool(entry.get('buildChildId'))
                                        and row['afterRepair']['artifactId'] not in (None, first_artifact)
                                        and entry.get('status') in ('needs_checks', 'accepted'),
            'findingsBoundToChild': bool((row.get('resumedChild') or {}).get('sawFindings')),
            'codeHashPinned': bool(entry.get('codeHash')),
            'redCheckIsRevise': red_check.get('status') == 'revise' and bool(red_check.get('childId')),
        }
        # --- oracle hành vi model ---
        real_red = row.get('realRed') or {}
        seeds = real_red.get('seeds') or []
        row['model'] = {
            # Cò đỏ phải là THẬT: đúng một lần gieo, và chính lượt chạy `python -m pytest -q` ngay
            # sau khi gieo phải thất bại (không còn traceback cắm sẵn).
            'seedIsRealRed': bool(real_red.get('seeded') == 1 and seeds
                                  and (seeds[0].get('proof') or {}).get('exitCode') not in (0, None)),
            'testerSawTheRedCommand': any('pytest' in str(command)
                                          for command in (red_check.get('commands') or [])),
            'buildChildTouchedItsFile': bool((row.get('resumedChild') or {}).get('wroteExport')),
            # Lượt ghi cuối có thể là một lượt bị sản phẩm TỪ CHỐI mở kiểm (không có `status`);
            # đọc theo `.get` để không nổ `KeyError` khi phép đo gặp đúng hàng rào của sản phẩm.
            'secondCheckPassed': (row.get('greenCheck') or {}).get('status') == 'pass',
            'nodeAccepted': (row.get('final') or {}).get('status') == 'accepted',
        }
        # --- oracle node tổng hợp (W8.A4.5.N): hợp nhất thật + child Testing THẬT xanh trên cây đó ---
        row['integrationNative'] = {
            # Nút tổng hợp chỉ có nghĩa khi nhánh run THẬT SỰ chứa commit của nút đã nghiệm thu.
            'mergedIntoRunBranch': bool((integration_row.get('merge') or {}).get('nodes')),
            'built': bool(integration_row.get('built')),
            'hasRealChild': any(c.get('childId') for c in (integration_row.get('checks') or [])),
            'testsPassedOnMergedTree': any(c.get('kind') == 'tests' and c.get('status') == 'pass'
                                            for c in (integration_row.get('checks') or [])),
            'integrationChecked': (integration_row.get('final') or {}).get('integrationStatus') == 'checked',
        }
        row['oracle'] = (all(row['mechanism'].values()) and all(row['model'].values())
                         and all(row['integrationNative'].values()))
    except Exception as exc:
        row.update(oracle=False, error=f'{type(exc).__name__}: {exc}',
                   traceback=traceback.format_exc()[-3000:])
    row.update(calls=client.calls, latencySeconds=round(time.monotonic() - started, 3))
    if rt is not None and sid:
        await rt.stop(sid)
    store.db.close()
    (output / 'results.json').write_bytes((json.dumps({'branch': branch, 'commit': commit,
        'sourceManifest': frozen, 'rows': [row]}, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    print(json.dumps({k: row.get(k) for k in ('case', 'oracle', 'mechanism', 'model',
                                              'integrationNative', 'error', 'latencySeconds')},
                     ensure_ascii=False), flush=True)
    snapshot_source(frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    asyncio.run(main(parser.parse_args()))
