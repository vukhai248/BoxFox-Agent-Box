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
import uuid
from pathlib import Path

from work_check_eval import ROOT, HarnessRuntime, SessionStore
from work_worktree_build_eval import Client, GitExecutor, git, make_repo, route_of, snapshot_source
from agentbox.agent_core import work_graph as wg

RED_TRACE = ('Traceback (most recent call last):\n'
             '  File "src/export.py", line 3, in export_markdown\n'
             '    return text.upper()\n'
             'AssertionError: assert "hồ sơ" == "Hồ sơ"\n'
             '1 failed, 1 passed in 0.11s\n')

TEST_FILE = '''from src.export import export_markdown


def test_keeps_unicode():
    assert export_markdown("Hồ sơ") == "Hồ sơ"
'''

NODE = {'id': 'B1', 'kind': 'build', 'title': 'Giữ dấu tiếng Việt khi export',
        'goal': 'Viết src/export.py sao cho export_markdown giữ nguyên dấu tiếng Việt; chỉ sửa src/export.py.',
        'acceptance': ['export_markdown("Hồ sơ") trả "Hồ sơ"'], 'tests': ['python -m pytest -q'],
        'files': ['src/export.py'], 'dependsOn': []}


class RepairExecutor(GitExecutor):
    """Như `GitExecutor`, nhưng có thể lên cò ĐÚNG `red` lệnh pytest kế tiếp."""

    def __init__(self, folder):
        super().__init__(folder)
        self.red = 0
        self.forced = 0

    def arm(self, count=1):
        self.red += count

    async def execute(self, name, args, sid, **identity):
        command = str((args or {}).get('command') or '')
        if name == 'terminal_exec' and self.red > 0 and 'pytest' in command:
            self.red -= 1
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
           'scope': 'Native: Build produce → kiểm tests THẬT (đỏ do fixture) → phân loại + sửa → kiểm lại xanh'}
    started = time.monotonic()
    store = SessionStore(folder.parent / 'repair_loop-sessions.db')
    client = Client(args.router)
    executor = RepairExecutor(folder)
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

        executor.arm(1)  # lượt kiểm thật sắp chạy sẽ thấy lệnh đỏ
        red = (await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'], 'nodeId': 'B1',
               'stage': 'execute', 'artifactId': first_artifact, 'checkIds': ['tests'],
               'invocationId': uuid.uuid4().hex}))
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

        second_artifact = (state.get('artifact') or {}).get('artifactId')
        green = (await graph.checks.tool(session, {'action': 'start', 'runId': run['runId'], 'nodeId': 'B1',
                 'stage': 'execute', 'artifactId': second_artifact, 'checkIds': ['tests'],
                 'invocationId': uuid.uuid4().hex}))
        green_doc = green['checks'][0]
        node = graph.find_node(graph.get(run['runId']), 'B1')
        state = node['stages']['execute']
        row['greenCheck'] = {'kind': green_doc['kind'], 'status': green_doc['status'], 'childId': green_doc.get('childId'),
                             'error': green_doc.get('error')}
        row['final'] = {'status': state['status'], 'attempts': state['attempts'],
                        'verdicts': [r.get('verdict') for r in state.get('rounds') or []],
                        'repairs': len(state.get('repairs') or [])}
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
            'secondCheckPassed': row['greenCheck']['status'] == 'pass',
            'nodeAccepted': row['final']['status'] == 'accepted',
        }
        row['oracle'] = all(row['mechanism'].values()) and all(row['model'].values())
    except Exception as exc:
        row.update(oracle=False, error=f'{type(exc).__name__}: {exc}')
    row.update(calls=client.calls, latencySeconds=round(time.monotonic() - started, 3))
    if rt is not None and sid:
        await rt.stop(sid)
    store.db.close()
    (output / 'results.json').write_bytes((json.dumps({'branch': branch, 'commit': commit,
        'sourceManifest': frozen, 'rows': [row]}, ensure_ascii=False, indent=2) + '\n').encode('utf8'))
    print(json.dumps({k: row.get(k) for k in ('case', 'oracle', 'mechanism', 'model', 'error',
                                              'latencySeconds')}, ensure_ascii=False), flush=True)
    snapshot_source(frozen)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    asyncio.run(main(parser.parse_args()))
