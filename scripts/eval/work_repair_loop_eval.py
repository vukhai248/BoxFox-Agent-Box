"""W8.A4.5 — probe thật: check đỏ được phân loại, sửa CÓ ĐIỀU KIỆN, rồi hội tụ ở vòng hai.

Fixture: repo git thật trong `.tmp/` + executor chạy `bash -lc` tại worktree nút. Executor được
"lên cò" đúng MỘT lệnh pytest đỏ (kèm traceback trỏ vào `src/export.py` đã track) ngay trước lượt
kiểm thật của nút Build. Nhờ vậy:

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
import json
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


def raise_build_child_output_budget():
    original = output_policy.child_budget

    def patched(role, work=None, task_kind=None):
        if role == 'build' and (work or {}).get('purpose') == 'produce':
            return BUILD_CHILD_OUTPUT_TOKENS
        return original(role, work, task_kind)

    output_policy.child_budget = patched

RED_TRACE = ('Traceback (most recent call last):\n'
             '  File "src/export.py", line 3, in export_markdown\n'
             '    return text.upper()\n'
             'AssertionError: assert "hồ sơ" == "Hồ sơ"\n'
             '1 failed, 1 passed in 0.11s\n')

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
    """Như `GitExecutor`, nhưng khi được bật thì trả ĐỎ mọi lệnh pytest của child KIỂM THỬ.

    Cò phải nhắm theo VAI của phiên, không theo chuỗi lệnh: chính lệnh checkpoint của harness có
    `':(exclude).pytest_cache'` nên khớp thô theo chuỗi 'pytest' sẽ bắn nhầm vào checkpoint
    (`WORK_WORKTREE_CHECKPOINT_FAILED`) và bịt luôn đường sửa — đo được ở lượt chạy trước của probe
    này. Child Build (vai `build`) vẫn chạy pytest THẬT nên tự kiểm được bản sửa của mình.
    """

    def __init__(self, folder, store=None):
        super().__init__(folder)
        self.store = store
        self.armed = False
        self.roles = {}
        self.forced = 0

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

    async def execute(self, name, args, sid, **identity):
        command = str((args or {}).get('command') or '')
        if name == 'terminal_exec' and self.armed and 'pytest' in command and self.role(sid) == 'testing':
            self.forced += 1
            self.calls.append({'name': name, 'args': dict(args), 'root': identity.get('root'),
                               'forcedRed': True})
            return {'content': RED_TRACE, 'exit_code': 1, 'is_error': True}
        return await super().execute(name, args, sid, **identity)


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
                            'why': 'con Build mặc định 4096 token output; lượt chạy 4096 đo được '
                                   'PROVIDER_OUTPUT_TRUNCATED (3958 token reasoning) nên draft không hoàn tất',
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
                         'maxSteps': 24, 'deadlineSeconds': 600})['id']
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
        row['firstStatus'] = await graph.run_stage(session, run, node, 'execute', 3)
        node = graph.find_node(graph.get(run['runId']), 'B1')
        first_artifact = (node['stages']['execute'].get('artifact') or {}).get('artifactId')
        row['firstArtifact'] = first_artifact
        row['firstProducer'] = (node['stages']['execute'].get('rounds') or [{}])[-1].get('producerId')
        row['pytestBeforeCheck'] = executor.forced

        executor.arm()  # mọi lệnh pytest của lượt kiểm thật đều thấy lệnh đỏ
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
        row['redCheck'] = {'kind': red_doc['kind'], 'status': red_doc['status'], 'childId': red_doc.get('childId'),
                           'error': red_doc.get('error'), 'repairAction': repair.get('action')}
        row['repair'] = entry
        node = graph.find_node(graph.get(run['runId']), 'B1')
        state = node['stages']['execute']
        row['afterRepair'] = {'status': state['status'], 'attempts': state['attempts'],
                              'artifactId': (state.get('artifact') or {}).get('artifactId'),
                              'verdicts': [r.get('verdict') for r in state.get('rounds') or []],
                              'repairs': state.get('repairs')}
        resumed_child = entry.get('buildChildId')
        child = store.get(resumed_child) if resumed_child else {}
        row['resumedChild'] = {'id': resumed_child, 'parent': child.get('parent_id'),
                               'tools': [item.get('name') for item in tool_events(store, resumed_child)][:20],
                               'wroteExport': any(
                                   item.get('name') in ('file_write', 'file_edit_block')
                                   and 'export.py' in json.dumps(item.get('args') or {}, ensure_ascii=False)
                                   or item.get('name') == 'terminal_exec'
                                   and 'export.py' in str((item.get('args') or {}).get('command') or '')
                                   for item in tool_events(store, resumed_child)),
                               'sawFindings': bool(entry.get('findingsArtifactId')) and entry['findingsArtifactId']
                                   in json.dumps(child.get('config') or {}, ensure_ascii=False)}

        executor.disarm()  # đã có vòng sửa: lượt kiểm thứ hai chạy pytest THẬT
        second_artifact = (state.get('artifact') or {}).get('artifactId')
        if not second_artifact:
            raise AssertionError(f'WORK_REPAIR_NO_DRAFT: status={state["status"]} error={state.get("error")}')
        # `test_proof` đòi child chạy ĐÚNG câu lệnh bắt buộc; child thật hay bọc ống/`echo` nên lượt
        # đầu có thể `unverified`. Thử lại có giới hạn và ghi trung thực từng lượt, không nới luật.
        for attempt in range(1, 4):
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
                # Đo thật: sản phẩm trả về không có check nào — ghi nguyên văn rồi dừng vòng,
                # không che bằng một IndexError khó đọc.
                row.setdefault('greenChecks', []).append({'attempt': attempt, 'empty': True,
                                                          'keys': sorted(green), 'raw': json.loads(json.dumps(
                                                              {k: v for k, v in green.items() if k != 'checks'},
                                                              ensure_ascii=False, default=str))})
                break
            green_doc = green['checks'][0]
            row.setdefault('greenChecks', []).append({
                'kind': green_doc['kind'], 'status': green_doc['status'], 'attempt': attempt,
                'childId': green_doc.get('childId'), 'error': green_doc.get('error'),
                'commands': [item.get('args', {}).get('command') for item
                             in work_checks.observations(graph, green_doc.get('childId'))
                             if item.get('name') == 'terminal_exec'][:12]})
            if green.get('repair'):
                # W8.A4.5: lượt kiểm thứ hai cũng có thể tự `revise` và được định tuyến sửa — ghi lại
                # nguyên văn vì đây chính là cơ chế cần đo.
                row.setdefault('greenRepairs', []).append(json.loads(json.dumps(green['repair'],
                                                                                ensure_ascii=False, default=str)))
            if green_doc['status'] == 'pass':
                break
        node = graph.find_node(graph.get(run['runId']), 'B1')
        state = node['stages']['execute']
        row['greenCheck'] = row['greenChecks'][-1]
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
                # của probe là ảnh chụp cũ nên `build_integration` sẽ thấy B1 còn `needs_checks` và trả
                # False. Đọc lại bản mới nhất trước khi dựng node tổng hợp (lỗi phép đo, không phải lỗi sản phẩm).
                run = graph.get(run['runId'])
                integration_row['executeStatuses'] = {n['id']: n['stages']['execute']['status']
                                                      for n in run['nodes'] if 'execute' in n['stages']}
                built = await graph.build_integration(session, run)
                run = graph.get(run['runId'])
                inode = graph.find_node(run, work_worktrees.INTEGRATION_NODE)
                istate = inode['stages']['execute'] if inode else {}
                ipolicy = istate.get('policy') or {}
                integration_row.update(built=bool(built), status=istate.get('status'),
                                       required=[r['id'] for r in ipolicy.get('required', [])],
                                       artifactId=(istate.get('artifact') or {}).get('artifactId'))
                if built:
                    iartifact = integration_row['artifactId']
                    for attempt in range(1, 4):
                        started_check = time.monotonic()
                        out = await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'],
                            'nodeId': work_worktrees.INTEGRATION_NODE, 'stage': 'execute',
                            'artifactId': iartifact, 'checkIds': ['tests'],
                            'invocationId': uuid.uuid4().hex})
                        if not out.get('checks'):
                            # Cùng lý do như vòng xanh: `checks.tool` có thể trả danh sách rỗng
                            # (đường replay/`inputConflicts`); ghi lại nguyên văn thay vì IndexError.
                            integration_row.setdefault('checks', []).append(
                                {'attempt': attempt, 'empty': True, 'keys': sorted(out)})
                            continue
                        idoc = out['checks'][0]
                        integration_row.setdefault('checks', []).append({
                            'kind': idoc['kind'], 'status': idoc['status'], 'attempt': attempt,
                            'childId': idoc.get('childId'), 'error': idoc.get('error'),
                            'seconds': round(time.monotonic() - started_check, 3),
                            'commands': [item.get('args', {}).get('command') for item
                                         in work_checks.observations(graph, idoc.get('childId'))
                                         if item.get('name') == 'terminal_exec'][:12]})
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

        row['forcedRedCommands'] = executor.forced
        row['ownerHead'] = git(repo, 'rev-parse', 'HEAD')
        # --- oracle cơ chế: do code harness quyết ---
        entry = row['repair'] or {}
        row['mechanism'] = {
            'oneRepairEntry': len(state.get('repairs') or []) == 1 and entry.get('n') == 1,
            'classified': entry.get('class') in ('clear', 'unclassified'),
            'debugOnlyWhenUnclassified': bool(entry.get('debugChildId')) == (entry.get('class') == 'unclassified'),
            'resumedSameChild': entry.get('resumed') is True and entry.get('buildChildId') == row['firstProducer'],
            'freshArtifactAfterRepair': bool(entry.get('buildChildId'))
                                        and row['afterRepair']['artifactId'] not in (None, first_artifact)
                                        and entry.get('status') in ('needs_checks', 'accepted'),
            'findingsBoundToChild': bool(row['resumedChild']['sawFindings']),
            'codeHashPinned': bool(entry.get('codeHash')),
            'redCheckIsRevise': row['redCheck']['status'] == 'revise' and bool(row['redCheck']['childId']),
        }
        # --- oracle hành vi model ---
        row['model'] = {
            'testerSawTheRedCommand': row['pytestBeforeCheck'] < row['forcedRedCommands'],
            'buildChildTouchedItsFile': bool(row['resumedChild']['wroteExport']),
            # Lượt ghi cuối có thể là một lượt bị sản phẩm TỪ CHỐI mở kiểm (không có `status`);
            # đọc theo `.get` để không nổ `KeyError` khi phép đo gặp đúng hàng rào của sản phẩm.
            'secondCheckPassed': (row['greenCheck'] or {}).get('status') == 'pass',
            'nodeAccepted': row['final']['status'] == 'accepted',
        }
        # --- oracle node tổng hợp (W8.A4.5.N): dựng snapshot hợp nhất + child Testing THẬT xanh trên đó ---
        row['integrationNative'] = {
            'built': bool(integration_row.get('built')),
            'hasRealChild': any(c.get('childId') for c in (integration_row.get('checks') or [])),
            'testsPassedOnMergedTree': bool((integration_row.get('checks') or [{}])[-1].get('status') == 'pass'),
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
