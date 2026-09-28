"""A7 — ghim `P:` khi ghi kế hoạch và `D:` khi một quyết định được chốt.

Hai chỗ này nối **file trên đĩa** với **nhật ký**: hỏi "bản kế hoạch này ra đời ở phiên nào, đã
duyệt chưa" phải trả lời được từ nhật ký, không phải bằng cách quét `.plans/` rồi đoán theo giờ sửa.
Bản ghi `D:` giữ cả `choice`, vì phát hiện đợt 4 cho thấy một lựa chọn `alternative` từng bị ghi
thành `approved` trơ — đọc lại không biết người dùng chốt phương án nào.
"""
from __future__ import annotations

import asyncio

from agentbox.agent_core import session_journal
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

# Một kế hoạch qua được cả thang điểm (plan_quality.py + plan_eval.py) — chép đúng khuôn mà
# `test_write_plan.py` dùng, vì cổng chất lượng chạy TRƯỚC khi sandbox ghi file: kế hoạch thiếu
# bước/tiêu chí sẽ bị từ chối và không có gì để ghim.
PLAN_MARKDOWN = """# Workspace plan

## Milestones
1. Chạy `.venv/bin/python -m pytest backend/tests -q`; mong đợi 9 passed.
2. Gọi `GET /api/agent/health` và xác nhận mã trả về là 200.

## Verification / Acceptance criteria
Run `.venv/bin/python -m pytest backend/tests -q`; expect only the 3 known environment failures.

## Risks / Limitations
- Giới hạn: chưa kiểm được hành vi khi box mất mạng vì môi trường này không mô phỏng được.
"""


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return next(self.responses)


class FixtureExecutor:
    """Sandbox giả: trả lời `write_plan` và mọi op nhật ký như box thật."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name == 'write_plan':
            return {'content': 'Written v1', 'version': 1, 'slug': args['slug'],
                    'relativePath': f".plans/v1-{args['slug']}.md", 'title': args.get('title') or 'Kế hoạch',
                    'bytes': len(args['markdown'].encode('utf-8'))}
        if name == 'journal_append':
            record = args.get('record') or {}
            return {'ok': True, 'id': record.get('id'), 'seq': 1, 'relPath': '.session-history/a1b2c3d4/journal.jsonl'}
        return {'ok': True}

    async def cleanup(self, sid):
        return None


def answer(text='xong', calls=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args):
    return {'id': 'c1', 'type': 'function', 'function': {'name': name, 'arguments': __import__('json').dumps(args)}}


def records(store, sid, kind=None):
    rows = store.journal_tail(sid, limit=50, kinds=[kind] if kind else None)
    return [(row['kind'], (row['payload'] or {}).get('record') or {}) for row in rows]


def write_one_plan(store, session_id, executor):
    runtime = HarnessRuntime(store, executor, FixtureModel([
        answer(calls=[call('write_plan', {'slug': 'nhat-ky-phien', 'markdown': PLAN_MARKDOWN})]),
        answer('Đã ghi kế hoạch')]))
    store.update_config(session_id, {}) if hasattr(store, 'update_config') else None
    return runtime


def test_a_written_plan_is_pinned_once_with_its_identity_and_version(tmp_path):
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = FixtureExecutor()
        # F3 (2026-09-27): lượt ghi plan mà chưa có phán quyết phản biện bị nhắc ĐÚNG MỘT bước, nên
        # fixture cần thêm câu trả lời cho bước ấy; thiếu nó thì lượt chết mà mặt ghim vẫn xanh.
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'nhat-ky-phien', 'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi kế hoạch'),
            answer('Chưa chạy phản biện, dừng ở đây.')]))
        sid = runtime.create({'skills': []})['id']
        await runtime.start(sid, 'Lên kế hoạch nhật ký')

        plans = [item for item in records(store, sid, 'plan')]
        assert len(plans) == 1, 'một lần ghi kế hoạch = đúng một bản ghi `P:`'
        kind, record = plans[0]
        assert record['id'] == 'P:nhat-ky-phien@v1'
        assert record['status'] == 'draft'
        assert record['data']['relativePath'] == '.plans/v1-nhat-ky-phien.md'
        assert record['kind'] == 'plan'
        assert record['sid8'] == sid[:8], 'bản ghi phải nói nó thuộc phiên nào'
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN — fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_the_plan_pin_points_at_the_open_task_when_the_session_has_one(tmp_path):
    """`refs` là tham chiếu, không phải mã bịa: chỉ xuất hiện khi có `T:` đang mở."""
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = FixtureExecutor()
        # F3 (2026-09-27): lượt ghi plan mà chưa có phán quyết phản biện bị nhắc ĐÚNG MỘT bước, nên
        # fixture cần thêm câu trả lời cho bước ấy; thiếu nó thì lượt chết mà mặt ghim vẫn xanh.
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'nhat-ky-phien', 'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi kế hoạch'),
            answer('Chưa chạy phản biện, dừng ở đây.')]))
        sid = runtime.create({'skills': []})['id']

        # Không có `T:` nào ⇒ không có `refs` (đường thường gặp trước khi agent gọi journal_write).
        first = runtime.open_task_refs(sid)
        assert first == []

        # Đường thật: `session_journal.append` ghi hàng SQLite rồi mới cấp mã `T:` (vì mã cần `seq`
        # mà SQLite chỉ trả về sau khi chèn).
        await session_journal.append(executor, store, sid, 'task', 'việc: kế hoạch nhật ký',
                                     status='doing')
        await runtime.start(sid, 'Lên kế hoạch nhật ký')

        pinned = [record for _, record in records(store, sid, 'plan')][0]
        assert pinned['refs'], 'bản kế hoạch phải trỏ về việc nó phục vụ'
        assert pinned['refs'][0].startswith('T:'), pinned['refs']
        # Bản ghi `T:` còn mở ⇒ tham chiếu trỏ đúng nó (tra lại từ chính bảng, không so với chuỗi tự viết).
        tasks = [row['payload']['record'] for row in store.journal_tail(sid, limit=50, kinds=['task'])]
        assert tasks and tasks[0]['id'].startswith('T:') and tasks[0]['status'] == 'doing'
        assert pinned['refs'] == [tasks[0]['id']]
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN — fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_a_resolved_decision_is_pinned_with_the_choice_not_just_approved(tmp_path):
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = FixtureExecutor()
        runtime = HarnessRuntime(store, executor, FixtureModel([answer('chờ chốt')]))
        sid = runtime.create({'skills': []})['id']

        # Hàng đợi quyết định: bản ghi thật trong `runtime.pending` (không dựng lại khuôn trong test).
        record = {'sessionId': sid, 'decisionId': 'dec-1', 'resolved': False,
                  'options': [{'id': 'a', 'label': 'Bản đầy đủ', 'kind': 'approve'},
                              {'id': 'b', 'label': 'Bản tối thiểu', 'kind': 'alternative'},
                              {'id': 'c', 'label': 'Dừng lại', 'kind': 'reject'}],
                  'future': asyncio.get_running_loop().create_future()}
        runtime.pending['dec-1'] = record

        result = runtime.resolve_decision(sid, 'dec-1', 'b', note='chọn bản tối thiểu')
        await runtime.pin_decision(sid, result)

        decisions = [record for _, record in records(store, sid, 'decision')]
        assert len(decisions) == 1
        pinned = decisions[0]
        assert pinned['status'] == 'approved', 'phương án thay thế vẫn là ĐỒNG Ý'
        assert pinned['data']['choice'] == 'b'
        assert pinned['data']['choiceLabel'] == 'Bản tối thiểu', 'phải đọc được đã chốt phương án nào'
        assert pinned['data']['alternatives'] == ['a', 'c']
        assert pinned['data']['note'] == 'chọn bản tối thiểu'
        store.close()

    asyncio.run(run())


def test_a_rejected_decision_is_pinned_as_rejected(tmp_path):
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer('chờ chốt')]))
        sid = runtime.create({'skills': []})['id']
        runtime.pending['dec-2'] = {
            'sessionId': sid, 'decisionId': 'dec-2', 'resolved': False,
            'options': [{'id': 'yes', 'label': 'Có', 'kind': 'approve'},
                        {'id': 'no', 'label': 'Không', 'kind': 'reject'}],
            'future': asyncio.get_running_loop().create_future()}

        result = runtime.resolve_decision(sid, 'dec-2', 'no')
        await runtime.pin_decision(sid, result)

        pinned = [record for _, record in records(store, sid, 'decision')][0]
        assert pinned['status'] == 'rejected'
        assert pinned['data']['choiceLabel'] == 'Không'
        store.close()

    asyncio.run(run())


def test_a_failing_journal_layer_never_breaks_the_plan_write(tmp_path):
    """Tầng file hỏng ⇒ một `notice`, còn kế hoạch vẫn được ghi và vẫn có bản ghi `P:` trong DB."""

    class BrokenJournal(FixtureExecutor):
        async def execute(self, name, args, sid):
            self.calls.append((name, args, sid))
            if name == 'write_plan':
                return await super().execute(name, args, sid)
            raise RuntimeError('box đóng rồi')

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, BrokenJournal(), FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'nhat-ky-phien', 'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi kế hoạch'),
            # F3 (đợt soát 2026-09-27): lượt ghi kế hoạch mà chưa có phán quyết thì harness bơm ĐÚNG
            # MỘT bước nhắc, nên lượt này tiêu thụ thêm một câu trả lời.
            answer('Ghi xong, chưa chạy phản biện.')]))
        sid = runtime.create({'skills': []})['id']
        await runtime.start(sid, 'Lên kế hoạch nhật ký')

        assert store.get(sid)['status'] == 'completed', 'nhật ký hỏng không được giết lượt'
        assert [event['data']['relativePath'] for event in store.events(sid) if event['type'] == 'plan_written'] \
            == ['.plans/v1-nhat-ky-phien.md']
        assert len([record for _, record in records(store, sid, 'plan')]) == 1, \
            'hàng SQLite là nguồn của khối ký ức nên vẫn phải có'
        notices = [event for event in store.events(sid) if event['type'] == 'notice']
        assert any(event['data'].get('code') == 'JOURNAL_DEGRADED' for event in notices), notices
        store.close()

    asyncio.run(run())
