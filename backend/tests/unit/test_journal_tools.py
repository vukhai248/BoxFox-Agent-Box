"""A3 — hai công cụ nhật ký mà AGENT tự gọi: `journal_write` và `journal_brief`.

Vì sao có bài này: phần A dựng bảng `journal` + tầng file trong box, nhưng ký ức chỉ
thành "ký ức" khi agent TỰ viết được và TỰ đọc lại được (mẫu MemGPT/Letta trong kế
hoạch). Bốn điều phải giữ, và mỗi điều có một ca ở đây:

1. Lời gọi sai bị từ chối bằng lỗi chỉ đúng chỗ sai, **không** để lại hàng rác.
2. Hàng SQLite ghi trước; tầng file hỏng thì câu trả lời nói `recorded: false` kèm
   `notice` `JOURNAL_DEGRADED` — không bao giờ nói đã ghi ra file khi chưa ghi.
3. Công cụ không có ở vai trò con (cha ghi hộ), và nằm trong bộ của orchestrator.
4. `journal_brief` trả khối ≤ 4000 ký tự và rỗng thì nói rõ là rỗng.
"""
from __future__ import annotations

import asyncio
import json

from agentbox.agent_core import journal
from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS, allowed_tools
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_contracts import SCHEMAS
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    """Sandbox giả: trả lời op `journal_append`; có công tắc để giả box hỏng."""

    def __init__(self, broken=False):
        self.calls = []
        self.broken = broken

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name == 'journal_append':
            if self.broken:
                raise OSError('container tắt')
            record = args.get('record') or {}
            return {'ok': True, 'id': record.get('id'), 'seq': 1,
                    'relPath': f'.session-history/{sid[:8]}/journal.jsonl'}
        return {'ok': True}

    async def cleanup(self, sid):
        return None


def runtime_for(tmp_path, name='journal-tools.db', broken=False):
    store = SessionStore(tmp_path / name)
    executor = FixtureExecutor(broken=broken)
    runtime = HarnessRuntime(store, executor, None)
    sid = runtime.create({'skills': []})['id']
    return store, executor, runtime, sid


def records(store, sid, kind=None):
    rows = store.journal_tail(sid, limit=50, kinds=[kind] if kind else None)
    return [(row['kind'], (row['payload'] or {}).get('record') or {}) for row in rows]


def test_the_two_journal_tools_are_advertised_and_held_by_the_orchestrator_only():
    names = {schema['function']['name'] for schema in SCHEMAS}
    assert {'journal_write', 'journal_brief'} <= names
    assert {'journal_write', 'journal_brief'} <= ORCHESTRATOR_TOOLS
    assert len(ORCHESTRATOR_TOOLS) == 38
    for role in ('build', 'explore', 'review', 'testing'):
        assert not ({'journal_write', 'journal_brief'} & allowed_tools(role)), \
            f'phiên con ({role}) không được cấp công cụ nhật ký — cha ghi hộ'


def test_journal_write_records_a_task_and_answers_with_its_id(tmp_path):
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path)
        answer = await runtime.journal_write(sid, {'kind': 'task', 'text': 'Đang dựng nhật ký phiên',
                                                   'status': 'doing'})

        assert answer['kind'] == 'task'
        assert answer['recorded'] is True
        assert answer['id'] == f"T:{sid[:8]}-1", 'mã bản ghi theo đúng khuôn `T:<sid8>-<n>`'
        assert journal.is_record_id(answer['id'])
        stored = records(store, sid, 'task')
        assert len(stored) == 1
        assert stored[0][1]['text'] == 'Đang dựng nhật ký phiên'
        assert stored[0][1]['status'] == 'doing'
        # Tầng file trong box cũng được gọi, và chỉ gọi một lần cho một bản ghi.
        assert [name for name, _, _ in executor.calls] == ['journal_append']
        store.close()

    asyncio.run(run())


def test_a_bad_call_is_refused_without_leaving_a_row(tmp_path):
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path)
        for bad in ({'kind': 'khong-co-kind-nay', 'text': 'x'},
                    {'kind': 'task', 'text': '   '},
                    {'kind': 'task', 'text': 'x' * 1001},
                    {'kind': 'task', 'text': 'ok', 'refs': 'T:khong-phai-list'}):
            try:
                await runtime.journal_write(sid, bad)
            except (ValueError, journal.JournalError):
                continue
            raise AssertionError(f'phải từ chối {bad!r}')

        assert records(store, sid) == [], 'lời gọi sai không được để lại hàng nào'
        assert executor.calls == [], 'và cũng không được chạm vào box'
        store.close()

    asyncio.run(run())


def test_the_kinds_the_harness_owns_are_refused_by_the_tool(tmp_path):
    """`plan`/`checkpoint` là việc của harness: để model tự viết là mời nó tạo mã `P:`/`C:` giả.

    Schema cũ còn mời gọi `kind="plan"`, mà đường đó **luôn** hỏng (`journal.record` cần tham số
    `plan` = kết quả `write_plan`) — một lượt của model bị đốt vô ích mỗi lần thử.
    """
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path)
        for kind in ('plan', 'checkpoint'):
            try:
                await runtime.journal_write(sid, {'kind': kind, 'text': 'thử'})
            except ValueError as exc:
                assert 'recorded by the harness' in str(exc)
                continue
            raise AssertionError(f'phải từ chối kind={kind!r}')
        assert records(store, sid) == []
        assert executor.calls == []
        # Schema không được mời gọi thứ công cụ từ chối.
        write = next(schema for schema in SCHEMAS if schema['function']['name'] == 'journal_write')
        kinds = write['function']['parameters']['properties']['kind']['enum']
        assert 'plan' not in kinds and 'checkpoint' not in kinds
        store.close()

    asyncio.run(run())


def test_a_row_that_cannot_be_written_is_not_answered_with_someone_elses_id(tmp_path):
    """Chèn hỏng thì câu trả lời phải là `recorded: false`, **không** mượn mã của bản ghi trước.

    Bản 0.1 đọc lại hàng cuối cùng để lấy mã, nên khi hàng mới không vào được nó trả về mã của
    lượt trước — một bản ghi khác hẳn, mà người đọc tin là của mình.
    """
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path)
        first = await runtime.journal_write(sid, {'kind': 'task', 'text': 'việc thứ nhất'})

        class DeafStore:
            def __getattr__(self, name):
                return getattr(store, name)

            def journal_add(self, *args, **kwargs):
                raise RuntimeError('database is locked')

        runtime.store = DeafStore()
        answer = await runtime.journal_write(sid, {'kind': 'task', 'text': 'việc thứ hai'})

        assert answer['recorded'] is False
        assert answer['id'] is None, 'không được trả mã của bản ghi khác'
        assert 'journal_brief will not show it' in answer['content'], \
            'phải nói rõ phần nào thiếu: dòng đã vào file trong box, hàng cho khối ký ức thì chưa'
        assert [row['text'] for row in store.journal_tail(sid)] == ['việc thứ nhất']
        store.close()

    asyncio.run(run())


def test_a_broken_box_layer_keeps_the_row_and_says_the_file_is_missing(tmp_path):
    """Tầng file hỏng KHÔNG được làm lượt đỏ, và không được nói dối là đã ghi file."""
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path, broken=True)
        answer = await runtime.journal_write(sid, {'kind': 'fact', 'text': 'Cửa sổ 32 768 gộp ở 20 070'})

        assert answer['recorded'] is False, 'file trong box không ghi được thì phải nói thật'
        assert 'JOURNAL_DEGRADED' in answer['content']
        stored = records(store, sid, 'fact')
        assert len(stored) == 1 and stored[0][1]['id'] == answer['id'], 'hàng vẫn phải còn'
        notices = [event for event in store.events(sid) if event['type'] == 'notice']
        assert any('JOURNAL_DEGRADED' in json.dumps(event['data']) for event in notices), \
            'mã lỗi phải được ghim vào nhật ký sự kiện'
        store.close()

    asyncio.run(run())


def test_the_evidence_list_and_the_brief_round_trip(tmp_path):
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path)
        await runtime.journal_write(sid, {'kind': 'task', 'text': 'Việc đang mở', 'status': 'open'})
        await runtime.journal_write(sid, {'kind': 'evidence', 'text': 'Đã chạy 446 bài deploy',
                                         'evidence': [{'type': 'command', 'path': 'deploy/docker/tests',
                                                       'note': 'unittest discover'}]})

        stored = records(store, sid, 'evidence')
        evidence = stored[0][1]['evidence'][0]
        assert (evidence['type'], evidence['path']) == ('command', 'deploy/docker/tests'), \
            'bằng chứng là con trỏ kiểm chứng được (loại + đường dẫn), không phải câu mô tả'

        brief = runtime.journal_brief(sid, {})
        assert brief['empty'] is False
        assert 'Việc đang mở' in brief['content']
        assert len(brief['content']) <= 4000, 'khối ký ức có trần 4000 ký tự'

        empty = runtime.journal_brief(runtime.create({'skills': []})['id'], {})
        assert empty['empty'] is True and 'empty' in empty['content']
        store.close()

    asyncio.run(run())


def test_the_tools_reach_the_model_through_dispatch(tmp_path):
    """Cổng cuối: `dispatch()` thật phải rẽ hai tên này (không chỉ method tồn tại)."""
    async def run():
        store, executor, runtime, sid = runtime_for(tmp_path)
        session = store.get(sid)
        written = await runtime.dispatch(session, 'journal_write',
                                        {'kind': 'blocker', 'text': 'Chờ khoá API của nhà cung cấp'})
        assert written['kind'] == 'blocker'
        read = await runtime.dispatch(session, 'journal_brief', {})
        assert 'Chờ khoá API' in read['content']
        assert records(store, sid, 'blocker')[0][1]['status'] == 'blocked', \
            'bản ghi `X:` mặc định là đang chặn'
        store.close()

    asyncio.run(run())
