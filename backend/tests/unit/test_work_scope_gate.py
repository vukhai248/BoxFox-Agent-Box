"""W8.A4.2 — cổng phạm vi thi công do backend sở hữu: phản chứng của probe §33.11.

Probe cũ cho thấy root trong một run `flow=research`, `executionRequested=false` vẫn gọi thẳng
`file_write` và `terminal_exec "pip install"` tới executor. Bộ kiểm này đi qua `dispatch` THẬT (không
phải gọi hàm luật) và khẳng định executor KHÔNG nhận lời gọi nào. Lượt chat thường không gắn run
giữ nguyên hành vi cũ (phương án C của Q1 trong plan W8).
"""
import asyncio

import pytest

from agentbox.agent_core import work_graph as wg, work_scope
from agentbox.agent_core.failures import classify_failure
from test_work_checks import RESEARCH
from test_work_graph import build

BUILD = {'id': 'B1', 'kind': 'build', 'title': 'Exporter', 'goal': 'Fix exporter Unicode serialization',
         'acceptance': ['Preserve Unicode'], 'tests': ['vitest ChatHeader.test.tsx']}
WRITES = ('file_write', 'file_edit_block')


async def root(rt, sid, name, args):
    return await rt.dispatch(rt.store.get(sid), name, args)


async def created_run(rt, sid, flow='research', nodes=None, goal='Research exporter formats'):
    result = await root(rt, sid, 'work_graph', {'action': 'create', 'goal': goal, 'flow': flow,
                                                'nodes': nodes or [RESEARCH]})
    return wg.service(rt).get(result['runId'])


def execute_child(store, rt, sid, run_id, admission=None, role='build'):
    child = rt.create({'skills': []}, parent_id=sid, role=role,
                      parent_tools=store.get(sid)['config']['tools'])
    work = {'runId': run_id, 'nodeId': 'B1', 'stage': 'execute', 'purpose': 'produce',
            'taskKind': 'implementation'}
    if admission:
        work['progressAdmissionId'] = admission
    child['config']['workBinding'] = work
    store.update_config(child['id'], child['config'])
    return child['id']


def test_artifact_only_run_blocks_root_writes_and_install_before_the_executor(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid)
        assert run['executionRequested'] is False
        cases = (('file_write', {'path': 'src/a.py', 'content': 'x'}, 'WORK_SCOPE_ARTIFACT_ONLY'),
                 ('file_edit_block', {'path': 'src/a.py', 'old_text': 'a', 'new_text': 'b'},
                  'WORK_SCOPE_ARTIFACT_ONLY'),
                 ('terminal_exec', {'command': 'pip install requests'}, 'WORK_SCOPE_TERMINAL_MUTATING'),
                 ('terminal_exec', {'command': 'echo x > f'}, 'WORK_SCOPE_TERMINAL_MUTATING'),
                 # F1 (review): `git grep -O<cmd>` chạy `<cmd>` — phải bị chặn TRƯỚC executor, và
                 # N1: `tree -oout.txt` (dạng dính) cũng là ghi.
                 ('terminal_exec', {'command': "git grep -O'touch /var/tmp/gitpwn2/PWNED' foo"},
                  'WORK_SCOPE_TERMINAL_MUTATING'),
                 ('terminal_exec', {'command': 'tree -oout.txt .'}, 'WORK_SCOPE_TERMINAL_MUTATING'))
        for name, args, code in cases:
            with pytest.raises(PermissionError, match=code) as failure:
                await root(rt, sid, name, args)
            assert run['runId'] in str(failure.value)
            # Mã đi tới model/giao diện là mã của CỔNG, không phải TOOL_NOT_PERMITTED chung.
            assert classify_failure(failure.value) == (code, str(failure.value))
        assert not [call for call in executor.calls if call[0] in WRITES]
        assert not [call for call in executor.calls
                    if call[0] == 'terminal_exec' and 'pip install' in call[1]['command']]
        # Lệnh ĐỌC vẫn qua: main cần pwd/ls/git log để định hướng (đo sống §33.13).
        await root(rt, sid, 'terminal_exec', {'command': 'git log --oneline -5'})
        assert executor.calls[-1] == ('terminal_exec', {'command': 'git log --oneline -5'})
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'artifact_only'
    asyncio.run(check())


def test_turn_profile_drops_write_tools_but_keeps_terminal(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        await created_run(rt, sid)
        profile = rt.turn_profile(store.get(sid))
        assert 'file_write' not in profile['tools'] and 'file_edit_block' not in profile['tools']
        assert 'terminal_exec' in profile['tools'] and 'work_graph' in profile['tools']
        assert work_scope.BLOCK_MARKER in profile['promptBlock']
        assert work_scope.BLOCK_END in profile['promptBlock']
    asyncio.run(check())


def test_new_user_turn_without_a_run_keeps_legacy_writes(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        await created_run(rt, sid)
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        # `runtime_commands._next_turn_skills` gọi hàm này cho MỌI lượt người dùng mới.
        work_scope.reset_user_turn(rt, sid)
        assert 'file_write' in rt.turn_profile(store.get(sid))['tools']
        await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        assert executor.calls[-1] == ('file_write', {'path': 'a.py', 'content': 'x'})
    asyncio.run(check())


def test_slash_intent_blocks_writes_from_the_start_of_the_turn(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        wg.set_intent(rt, store.get(sid), 'plan', 'plan the export button')
        profile = rt.turn_profile(store.get(sid))
        assert 'file_write' not in profile['tools'] and 'terminal_exec' in profile['tools']
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        assert not executor.calls
    asyncio.run(check())


def test_slash_intent_is_spent_by_its_turn_and_clears_on_the_next_user_turn(tmp_path):
    """§1.2 — ý định slash chỉ thuộc MỘT lượt; lượt tiêu nó mà không ra run thì lượt sau về `legacy`."""
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        wg.set_intent(rt, store.get(sid), 'research', 'nghiên cứu định dạng xuất')
        # Thứ tự THẬT của `/research <text>`: ghi ý định → `_next_turn_skills` (reset) → `start`.
        work_scope.reset_user_turn(rt, sid)
        assert (store.get(sid)['config'] or {}).get('workIntent'), \
            'ý định vừa đặt trong chính lượt này không được xoá'
        work_scope.begin_turn(rt, sid, 1)
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'artifact_only'
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        # Lượt người dùng kế tiếp: ý định đã tiêu mà không ra run ⇒ hết hiệu lực, ghi lại được.
        work_scope.reset_user_turn(rt, sid)
        assert 'workIntent' not in (store.get(sid)['config'] or {})
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'legacy'
        assert 'file_write' in rt.turn_profile(store.get(sid))['tools']
        await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        assert executor.calls[-1] == ('file_write', {'path': 'a.py', 'content': 'x'})
    asyncio.run(check())


def test_intent_that_produced_a_run_keeps_the_gate_via_the_run_binding(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        wg.set_intent(rt, store.get(sid), 'research', 'nghiên cứu định dạng xuất')
        work_scope.begin_turn(rt, sid, 1)
        run = await created_run(rt, sid, goal='Research export formats')
        # `create` tiêu ý định; cổng còn lại là binding theo RUN, không nhờ ý định.
        assert 'workIntent' not in (store.get(sid)['config'] or {})
        assert work_scope.turn_binding(rt, store.get(sid))['runId'] == run['runId']
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        # Lượt chat thường kế tiếp không gắn run (phương án C) — nhưng lượt gắn LẠI run thì vẫn bị khoá.
        work_scope.reset_user_turn(rt, sid)
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'legacy'
        work_scope.begin_turn(rt, sid, 2)
        work_scope.bind_tool(rt, store.get(sid), 'work_graph', {'action': 'status'},
                             {'runId': run['runId']})
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'artifact_only'
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        assert not [call for call in executor.calls if call[0] in WRITES]
    asyncio.run(check())


def test_next_turn_skills_does_not_resurrect_the_spent_intent(tmp_path):
    """N2 (soát W8.A4.2): `_next_turn_skills` ghi lại config cũ SAU `reset_user_turn`.

    Đo sống: nếu nó không đọc lại config thì `workIntent` vừa bị bỏ sống lại y nguyên, và mọi lượt
    người dùng sau một `/research <text>` không ra run đều bị khoá ghi vĩnh viễn.
    """
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        wg.set_intent(rt, store.get(sid), 'research', 'nghiên cứu định dạng xuất')
        # Lượt mang ý định: đúng đường thật — `_next_turn_skills` (reset) rồi `start`/`begin_turn`.
        rt._next_turn_skills(store.get(sid), [], None, '/research nghiên cứu định dạng xuất')
        work_scope.begin_turn(rt, sid, 1)
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'artifact_only'
        # Lượt người dùng kế tiếp đi qua CÙNG đường đó: ý định phải biến mất, không được sống lại.
        rt._next_turn_skills(store.get(sid), [], None, 'giờ viết code đi')
        assert 'workIntent' not in (store.get(sid)['config'] or {}), \
            '`_next_turn_skills` không được trả lại ý định đã tiêu'
        work_scope.begin_turn(rt, sid, 2)
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'legacy'
        assert 'file_write' in rt.turn_profile(store.get(sid))['tools']
    asyncio.run(check())


def test_execution_run_needs_approval_and_root_still_never_edits(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid, flow='fix', nodes=[BUILD], goal='Fix the Unicode export behavior')
        assert run['executionRequested'] is True
        with pytest.raises(PermissionError, match='WORK_SCOPE_APPROVAL_REQUIRED'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        graph = wg.service(rt)
        graph.approve_by_autopilot(run)
        graph.save(run, 'approved', 'autopilot')
        with pytest.raises(PermissionError, match='WORK_SCOPE_ROOT_DELEGATES'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        # Lệnh terminal đi theo mã của BỘ PHÂN LOẠI (§7); lý do vẫn nói run đã duyệt và sửa mã phải
        # qua Build node, nên model không đọc nó thành "đổi lệnh rồi thử lại".
        with pytest.raises(PermissionError, match='WORK_SCOPE_TERMINAL_MUTATING') as failure:
            await root(rt, sid, 'terminal_exec', {'command': 'pip install requests'})
        assert 'Build nodes' in str(failure.value) and run['runId'] in str(failure.value)
        assert not [call for call in executor.calls if call[0] in WRITES]
    asyncio.run(check())


def test_approval_inside_an_artifact_only_run_does_not_grant_build(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid)
        graph = wg.service(rt)
        with pytest.raises(ValueError, match='WORK_REQUIREMENTS_ONLY'):
            graph.approve_by_autopilot(run)
        run['status'] = 'approved'
        run['approval'] = {'status': 'approved', 'by': 'owner', 'at': 0}
        graph.save(run, 'approved', 'owner')
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await root(rt, sid, 'file_write', {'path': 'a.py', 'content': 'x'})
        assert not [call for call in executor.calls if call[0] in WRITES]
    asyncio.run(check())


def test_a_run_of_another_session_grants_nothing(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        other = rt.create({'skills': []})['id']
        foreign = wg.service(rt).create(store.get(other), {'goal': 'Research another session formats',
                                                          'flow': 'research', 'nodes': [RESEARCH]})
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'legacy'
        with pytest.raises(ValueError, match='WORK_RUN_UNKNOWN'):
            await root(rt, sid, 'work_graph', {'action': 'status', 'runId': foreign['runId']})
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'legacy'
        child_id = execute_child(store, rt, sid, foreign['runId'])
        assert work_scope.resolve(rt, store.get(child_id))['mode'] == 'artifact_only'
        with pytest.raises(PermissionError, match='WORK_SCOPE_ARTIFACT_ONLY'):
            await rt.dispatch(store.get(child_id), 'file_write', {'path': 'a.py', 'content': 'x'})
        assert not [call for call in executor.calls if call[0] in WRITES]
    asyncio.run(check())


def test_run_cancelled_mid_turn_closes_the_scope(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid)
        graph = wg.service(rt)
        run['status'] = 'cancelled'
        graph.save(run, 'cancelled')
        for name, args in (('file_write', {'path': 'a.py', 'content': 'x'}),
                           ('terminal_exec', {'command': 'pip install requests'})):
            with pytest.raises(PermissionError, match='WORK_SCOPE_RUN_CLOSED'):
                await root(rt, sid, name, args)
        assert not executor.calls
    asyncio.run(check())


def test_execution_child_writes_only_while_its_admission_is_live(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid, flow='fix', nodes=[BUILD], goal='Fix the Unicode export behavior')
        graph = wg.service(rt)
        graph.approve_by_autopilot(run)
        graph.save(run, 'approved', 'autopilot')
        admission = await graph.progress.reserve(sid, {'runId': run['runId'], 'nodeId': 'B1',
                                                       'stage': 'execute', 'purpose': 'produce',
                                                       'taskKind': 'implementation'})
        child_id = execute_child(store, rt, sid, run['runId'], admission)
        assert work_scope.resolve(rt, store.get(child_id))['mode'] == 'run_execute'
        await rt.dispatch(store.get(child_id), 'file_write', {'path': 'src/a.py', 'content': 'x'})
        assert executor.calls[-1] == ('file_write', {'path': 'src/a.py', 'content': 'x'})
        # Stop/thu hồi admission: lời gọi đang chờ không được chạy.
        graph.progress.cancel(sid)
        with pytest.raises(PermissionError, match='WORK_SCOPE_REVOKED'):
            await rt.dispatch(store.get(child_id), 'file_write', {'path': 'src/b.py', 'content': 'y'})
        assert [call for call in executor.calls if call[0] in WRITES] == [
            ('file_write', {'path': 'src/a.py', 'content': 'x'})]
    asyncio.run(check())


def test_restart_rechecks_sqlite_and_a_fresh_admission_reopens_execution(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        run = await created_run(rt, sid, flow='fix', nodes=[BUILD], goal='Fix the Unicode export behavior')
        graph = wg.service(rt)
        graph.approve_by_autopilot(run)
        graph.save(run, 'approved', 'autopilot')
        admission = await graph.progress.reserve(sid, {'runId': run['runId'], 'nodeId': 'B1',
                                                       'stage': 'execute', 'purpose': 'produce',
                                                       'taskKind': 'implementation'})
        child_id = execute_child(store, rt, sid, run['runId'], admission)
        assert work_scope.resolve(rt, store.get(child_id))['mode'] == 'run_execute'
        await rt.stop(sid)
        # Restart: tiến trình mới không giữ ký ức nào; cổng đọc SQLite.
        rt.work_graph = wg.WorkGraph(rt)
        with pytest.raises(PermissionError, match='WORK_SCOPE_REVOKED'):
            await rt.dispatch(store.get(child_id), 'file_write', {'path': 'a.py', 'content': 'x'})
        assert not [call for call in executor.calls if call[0] in WRITES]
        fresh = await rt.work_graph.progress.reserve(sid, {'runId': run['runId'], 'nodeId': 'B1',
                                                           'stage': 'execute', 'purpose': 'produce',
                                                           'taskKind': 'implementation'})
        second_id = execute_child(store, rt, sid, run['runId'], fresh)
        await rt.dispatch(store.get(second_id), 'file_write', {'path': 'b.py', 'content': 'y'})
        assert executor.calls[-1] == ('file_write', {'path': 'b.py', 'content': 'y'})
    asyncio.run(check())


def test_check_child_keeps_the_read_only_gate_and_may_still_run_commands(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        child = rt.create({'skills': []}, parent_id=sid, role='testing',
                          parent_tools=store.get(sid)['config']['tools'])
        child['config']['workBinding'] = {'runId': 'w-unknown', 'nodeId': 'B1', 'stage': 'execute',
                                          'purpose': 'review', 'checkId': 'c-1'}
        store.update_config(child['id'], child['config'])
        assert work_scope.resolve(rt, store.get(child['id']))['mode'] == 'read_only_check'
        with pytest.raises(PermissionError, match='WORK_CHECK_READ_ONLY'):
            await rt.dispatch(store.get(child['id']), 'file_write', {'path': 'a.py', 'content': 'x'})
        await rt.dispatch(store.get(child['id']), 'terminal_exec', {'command': 'vitest ChatHeader.test.tsx'})
        assert executor.calls[-1][0] == 'terminal_exec'
    asyncio.run(check())
