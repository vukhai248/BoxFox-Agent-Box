"""write_plan: the sandbox picks the next free version and the harness reports it honestly.

Contract: docs/plan/next-batch-contract.md §1 (plan_written + ui_intent).
"""
import asyncio
import copy
import hashlib
import json

import pytest

import agentbox.sandbox.worker as worker
from agentbox.agent_core import plan_header, plan_registry
from agentbox.agent_core.runtime import HarnessRuntime, plan_identity, plan_slug, plan_title
from agentbox.memory.session_store import SessionStore

# A plan that passes the whole rubric the round-20 harness applies (plan_quality.py + plan_eval.py):
# every step carries a command and the result to expect, the acceptance criteria name a command, and
# the limits paragraph says honestly what could not be checked. The gate must never change what such
# a plan writes.
PLAN_MARKDOWN = """# Workspace plan

## Milestones
1. Chạy `.venv/bin/python -m pytest backend/tests -q`; mong đợi 9 passed.
2. Gọi `GET /api/agent/health` và xác nhận mã trả về là 200.

## Verification / Acceptance criteria
Run `.venv/bin/python -m pytest backend/tests -q`; expect only the 3 known environment failures.

## Risks / Limitations
- Giới hạn: chưa kiểm được hành vi khi box mất mạng vì môi trường này không mô phỏng được.
"""
# A revision must trace back to the version it revises: a v2 that says nothing about v1 is refused
# (`PLAN_EVAL_REJECTED: (revision-untraceable)`), so this one carries a "changes vs v1" section.
PLAN_MARKDOWN_V2 = PLAN_MARKDOWN.replace(
    '## Milestones',
    '## Thay đổi so với v1\nBản 2 thêm bước thứ hai và ghi rõ giới hạn đã biết.\n\n## Milestones')


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append(copy.deepcopy((messages, tools, route)))
        return next(self.responses)


JOURNAL_OPS = {'journal_append', 'session_ensure', 'checkpoint_write'}


class PlanFixtureExecutor:
    """Stands in for the sandbox worker: confirms the same metadata the real container returns.

    The worker returns no `identity`: the contract §1 forbids the `vN-`-qualified form there,
    and the harness derives the published `plan_written.identity` from the confirmed
    `relativePath` itself.
    """

    def __init__(self, versions=()):
        self.calls = []
        self.used = set(versions)

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name in JOURNAL_OPS:
            # A7 (đợt 20): một lần ghi plan thành công còn ghim một bản ghi `P:` — op nhật ký đi qua
            # cùng executor nên fixture phải trả khuôn thật, không được coi là "sai công cụ".
            return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1,
                    'relPath': f".session-history/journal.jsonl"}
        assert name == 'write_plan', 'write_plan must go through the sandbox executor'
        version = max(self.used or {0}) + 1
        self.used.add(version)
        return {'content': 'Written ' + args['slug'], 'version': version,
                'slug': args['slug'], 'relativePath': f".plans/v{version}-{args['slug']}.md",
                'bytes': len(args['markdown'].encode('utf-8'))}

    async def cleanup(self, sid):
        return None


class NestedPlanExecutor(PlanFixtureExecutor):
    """A sandbox that nests the plan under `.plans/<dir>/`, which plan_files.py groups as `dir/slug`."""

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name in JOURNAL_OPS:
            return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1}
        return {'content': 'Written docs/docs', 'version': 1, 'slug': 'docs',
                'relativePath': '.plans/docs/v1-docs.md', 'title': 'Docs',
                'bytes': len(args['markdown'].encode('utf-8'))}

    async def cleanup(self, sid):
        return None


class SilentExecutor(PlanFixtureExecutor):
    async def execute(self, name, args, sid):
        raise AssertionError('the sandbox must not be called: ' + name)


def events_of(store, sid, kind):
    return [event for event in store.events(sid) if event['type'] == kind]


def tool_results(store, sid):
    return [json.loads(message['content']) for message in store.get(sid)['messages'] if message['role'] == 'tool']


def test_write_plan_emits_plan_written_then_ui_intent(tmp_path):
    """The next free version is used and the two events are emitted in the contract's order."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = PlanFixtureExecutor()
        model = FixtureModel([
            answer('Viết plan', calls=[call('write_plan', {'slug': 'Workspace Plan', 'markdown': PLAN_MARKDOWN, 'title': ''})]),
            answer('Đã ghi plan'),
            # F3 (đợt soát 2026-09-27): lượt có `write_plan` mà chưa có phán quyết thì harness bơm
            # ĐÚNG MỘT bước nhắc giữa lượt, nên mỗi lượt plan tiêu thụ thêm một câu trả lời ở đây.
            answer('Ghi xong, chưa chạy phản biện.'),
            answer('Viết tiếp', calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN_V2})]),
            answer('Đã ghi bản 2'),
            answer('Ghi xong, chưa chạy phản biện.')])
        runtime = HarnessRuntime(store, executor, model)
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Lên plan')
        # `session_ensure` (A1) là op hạ tầng chạy trước cả công cụ — bỏ ra để dãy dưới đây còn nói
        # về đúng hợp đồng "ghi file trước, ghim nhật ký sau" của `write_plan`.
        calls = [(name, args, call_sid) for name, args, call_sid in executor.calls
                 if name != 'session_ensure']
        # A7: `write_plan` ghim luôn một bản ghi `P:` — thứ tự này chính là hợp đồng
        # "ghi file trước, ghim nhật ký sau", nên khoá lại bằng dãy chứ không bằng tập.
        assert [name for name, _, _ in calls] == ['write_plan'] + [name for name, _, _ in calls[1:]]
        assert calls[0][0] == 'write_plan' and all(name in JOURNAL_OPS for name, _, _ in calls[1:])
        name, args, call_sid = calls[0]
        assert args['slug'] == 'workspace-plan', 'the slug must be normalized before it reaches the sandbox'
        assert args['markdown'] == PLAN_MARKDOWN and call_sid == sid

        written = events_of(store, sid, 'plan_written')
        assert len(written) == 1
        assert set(written[0]['data']) == {'identity', 'version', 'slug', 'relativePath', 'title', 'bytes', 'contentHash'}
        assert written[0]['data'] == {'identity': 'workspace-plan', 'version': 1, 'slug': 'workspace-plan',
                                      'relativePath': '.plans/v1-workspace-plan.md', 'title': 'Workspace plan',
                                      'bytes': len(PLAN_MARKDOWN.encode('utf-8')),
                                      'contentHash': hashlib.sha256(PLAN_MARKDOWN.encode('utf-8')).hexdigest()}
        intent = events_of(store, sid, 'ui_intent')
        assert len(intent) == 1
        assert intent[0]['data'] == {'tab': 'plan', 'target': {'identity': 'workspace-plan', 'version': 1},
                                     'reason': 'plan_written'}
        assert intent[0]['seq'] == written[0]['seq'] + 1, 'ui_intent must follow plan_written immediately'

        seen = tool_results(store, sid)[-1]
        assert not seen.get('is_error')
        assert seen['relativePath'] == '.plans/v1-workspace-plan.md' and seen['version'] == 1
        assert seen['title'] == 'Workspace plan'

        # a second plan in the same session never reuses v1
        await runtime.start(sid, 'Lên plan bản 2')
        assert [event['data']['relativePath'] for event in events_of(store, sid, 'plan_written')] == \
            ['.plans/v1-workspace-plan.md', '.plans/v2-workspace-plan.md']
        assert [event['data']['target']['identity'] for event in events_of(store, sid, 'ui_intent')] == \
            ['workspace-plan', 'workspace-plan'], 'identity is the reader key, never version-qualified'
        assert [event['data']['target']['version'] for event in events_of(store, sid, 'ui_intent')] == [1, 2], \
            'the version disambiguates two writes of the same plan'
        assert [event['data']['identity'] for event in events_of(store, sid, 'plan_written')] == \
            ['workspace-plan', 'workspace-plan']
        assert store.get(sid)['status'] == 'completed'
        store.close()

    asyncio.run(run())


def test_nested_plan_target_uses_the_reader_identity_and_version(tmp_path):
    """A nested plan must be targetable by the (identity, version) pair `GET /__box/plans` returns."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, NestedPlanExecutor(), FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'docs', 'markdown': PLAN_MARKDOWN, 'title': 'Docs'})]),
            answer('Đã ghi plan'),
            NUDGE_ANSWER]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        written = events_of(store, sid, 'plan_written')
        assert written[0]['data'] == {'identity': 'docs/docs', 'version': 1, 'slug': 'docs',
                                      'relativePath': '.plans/docs/v1-docs.md', 'title': 'Docs',
                                      'bytes': len(PLAN_MARKDOWN.encode('utf-8')),
                                      'contentHash': hashlib.sha256(PLAN_MARKDOWN.encode('utf-8')).hexdigest()}
        assert events_of(store, sid, 'ui_intent')[0]['data'] == \
            {'tab': 'plan', 'target': {'identity': 'docs/docs', 'version': 1}, 'reason': 'plan_written'}
        assert tool_results(store, sid)[-1]['relativePath'] == '.plans/docs/v1-docs.md'
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_write_plan_rejects_an_unusable_slug(tmp_path):
    """A slug that cannot be a plan filename fails loudly and never reaches the sandbox."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([answer(calls=[call('write_plan', {'slug': '###', 'markdown': PLAN_MARKDOWN})]),
                              answer('Không ghi được plan')])
        runtime = HarnessRuntime(store, SilentExecutor(), model)
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        assert events_of(store, sid, 'plan_written') == []
        assert events_of(store, sid, 'ui_intent') == []
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'PLAN_SLUG_INVALID' in failures[0]['error']
        assert store.get(sid)['status'] == 'completed', 'the agent keeps going after a refused plan'
        store.close()

    asyncio.run(run())


@pytest.mark.parametrize('value', [None, '', '   ', 42, True, {'name': 'plan'}, ['plan']])
def test_plan_slug_requires_nonempty_string(value):
    with pytest.raises(ValueError, match='PLAN_SLUG_INVALID: slug.*non-empty string'):
        plan_slug(value)


@pytest.mark.parametrize('args,code', [
    ({'markdown': PLAN_MARKDOWN}, 'PLAN_SLUG_INVALID'),
    ({'slug': 42, 'markdown': PLAN_MARKDOWN}, 'PLAN_SLUG_INVALID'),
    ({'slug': 'valid-plan'}, 'PLAN_INVALID'),
])
def test_worker_plan_argument_errors_are_coded_and_write_nothing(tmp_path, monkeypatch, args, code):
    monkeypatch.setattr(worker, 'ROOT', tmp_path.resolve())
    with pytest.raises(ValueError, match=code):
        worker.write_plan(args)
    assert list(tmp_path.iterdir()) == []


def test_write_plan_refuses_a_lying_sandbox(tmp_path):
    """plan_written is never emitted unless the sandbox confirms a real plan path."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')

        class Lying(PlanFixtureExecutor):
            async def execute(self, name, args, sid):
                return {'content': 'ok'}

        runtime = HarnessRuntime(store, Lying(), FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN})]),
            answer('Bỏ qua')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        assert events_of(store, sid, 'plan_written') == []
        assert events_of(store, sid, 'ui_intent') == []
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'PLAN_WRITE_FAILED' in failures[0]['error']
        store.close()

        # a path the plan reader would ignore is not a plan: no identity can be derived from it, so refuse
        other = SessionStore(tmp_path / 'off-path.db')

        class OffPath(PlanFixtureExecutor):
            async def execute(self, name, args, sid):
                return {'content': 'ok', 'version': 1, 'relativePath': '.plans/Bad Dir/v1-x.md'}

        runtime = HarnessRuntime(other, OffPath(), FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'x', 'markdown': PLAN_MARKDOWN})]),
            answer('Bỏ qua')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        assert events_of(other, sid, 'plan_written') == []
        assert events_of(other, sid, 'ui_intent') == []
        assert 'PLAN_WRITE_FAILED' in [result['error'] for result in tool_results(other, sid)
                                       if result.get('is_error')][0]
        other.close()

    asyncio.run(run())


def test_plan_slug_and_title_helpers():
    assert plan_slug('  Workspace  Plan v2 ') == 'workspace-plan-v2'
    assert plan_slug('Kế hoạch') == 'k-ho-ch'
    for bad in ('', '   ', '###', '---'):
        with pytest.raises(ValueError, match='PLAN_SLUG_INVALID'):
            plan_slug(bad)
    assert plan_title('', PLAN_MARKDOWN, 'workspace-plan') == 'Workspace plan'
    assert plan_title('My own title', '# Ignored\n', 'workspace-plan') == 'My own title'
    assert plan_title('', 'no heading here', 'workspace-plan') == 'Workspace plan'


def test_plan_identity_helper_mirrors_the_plan_reader():
    """plan_files.py:315-321 identity: bare slug at the root of .plans/, `dir/slug` when nested, never `vN-`."""
    assert plan_identity('.plans/v2-workspace-plan.md') == 'workspace-plan'
    assert plan_identity('.plans/docs/v1-docs.md') == 'docs/docs'
    assert plan_identity('.plans/a/b/v7-pilot.md') == 'a/b/pilot'
    for reader_ignored in ('.plans/v1-Bad.md', '.plans/Bad Dir/v1-x.md', 'plans/v1-x.md', '.plans/v1-x.txt', '', None):
        assert plan_identity(reader_ignored) == '', 'a path the reader ignores has no identity: ' + repr(reader_ignored)
    assert 'v2-' not in plan_identity('.plans/v2-workspace-plan.md'), 'identity must never carry the version prefix'


def test_worker_write_plan_picks_the_next_free_version(tmp_path, monkeypatch):
    """The sandbox writer never overwrites a version and only produces names plan_files.py accepts."""
    monkeypatch.setattr(worker, 'ROOT', tmp_path)

    first = worker.execute('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN}, 'session')
    assert first['relativePath'] == '.plans/v1-workspace-plan.md'
    # the worker payload carries NO `identity`: contract §1 forbids the `vN-`-qualified form
    # (the harness publishes plan_identity(relativePath), i.e. the bare reader grouping key)
    assert 'identity' not in first
    assert first['version'] == 1 and first['slug'] == 'workspace-plan'
    assert first['bytes'] == len(PLAN_MARKDOWN.encode('utf-8'))
    assert (tmp_path / '.plans' / 'v1-workspace-plan.md').read_text(encoding='utf-8') == PLAN_MARKDOWN

    second = worker.execute('write_plan', {'slug': 'workspace-plan', 'markdown': 'second body'}, 'session')
    assert second['relativePath'] == '.plans/v2-workspace-plan.md'

    # an existing higher version (from anywhere) pushes the next free number, and is left untouched
    (tmp_path / '.plans' / 'v5-other.md').write_text('other plan', encoding='utf-8')
    third = worker.execute('write_plan', {'slug': 'other', 'markdown': 'third body'}, 'session')
    assert third['relativePath'] == '.plans/v6-other.md'
    assert (tmp_path / '.plans' / 'v5-other.md').read_text(encoding='utf-8') == 'other plan'
    assert (tmp_path / '.plans' / 'v1-workspace-plan.md').read_text(encoding='utf-8') == PLAN_MARKDOWN
    assert sorted(item.name for item in (tmp_path / '.plans').iterdir()) == \
        ['v1-workspace-plan.md', 'v2-workspace-plan.md', 'v5-other.md', 'v6-other.md']
    assert worker.PLAN_FILENAME.fullmatch('v6-other.md'), 'names must match deploy/docker/plan_files.py:18-22'


def test_worker_write_plan_takes_the_harness_version_and_never_self_increments(tmp_path, monkeypatch):
    """§3.4: version là của TỪNG nhóm, harness quyết số; đã có thì từ chối chứ không tự tăng."""

    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    (tmp_path / '.plans').mkdir()
    # File của slug KHÁC không được đẩy số của nhóm này (lỗi v5→v6 của vòng 20).
    (tmp_path / '.plans' / 'v9-other.md').write_text('other plan', encoding='utf-8')

    first = worker.execute('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN}, 'session')
    assert first['relativePath'] == '.plans/v1-workspace-plan.md'
    assert first['version'] == 1

    # Harness quyết số từ chỉ mục: dùng ĐÚNG số đó (kể cả khi nó nhảy cách quãng).
    third = worker.execute('write_plan', {'slug': 'workspace-plan', 'version': 3,
                                          'markdown': PLAN_MARKDOWN}, 'session')
    assert third['relativePath'] == '.plans/v3-workspace-plan.md'
    with pytest.raises(ValueError, match='^PLAN_VERSION_TAKEN'):
        worker.execute('write_plan', {'slug': 'workspace-plan', 'version': 3,
                                      'markdown': PLAN_MARKDOWN}, 'session')
    assert (tmp_path / '.plans' / 'v3-workspace-plan.md').read_text(encoding='utf-8') == PLAN_MARKDOWN

    # Không truyền version (harness không đọc được chỉ mục) → giữ hành vi cũ trong nhóm này.
    fourth = worker.execute('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN}, 'session')
    assert fourth['relativePath'] == '.plans/v4-workspace-plan.md'

    # Thư mục nhóm do harness quyết (identity `dir/slug`), và đếm số theo đúng thư mục đó.
    nested = worker.execute('write_plan', {'slug': 'docs', 'directory': 'subplans', 'version': 1,
                                           'markdown': PLAN_MARKDOWN}, 'session')
    assert nested['relativePath'] == '.plans/subplans/v1-docs.md'
    assert worker.execute('write_plan', {'slug': 'docs', 'directory': 'subplans', 'markdown': PLAN_MARKDOWN},
                          'session')['relativePath'] == '.plans/subplans/v2-docs.md'
    # cùng slug nhưng khác thư mục là NHÓM khác: số đếm riêng, không dùng chung
    assert worker.execute('write_plan', {'slug': 'docs', 'markdown': PLAN_MARKDOWN},
                          'session')['relativePath'] == '.plans/v1-docs.md'

    for bad in ({'directory': 'Sub Plans'}, {'version': 'v3'}, {'version': True}):
        with pytest.raises(ValueError, match='^PLAN_(SLUG_INVALID|INVALID)'):
            worker.execute('write_plan', {'slug': 'docs', 'markdown': PLAN_MARKDOWN, **bad}, 'session')


def test_worker_write_plan_refuses_bad_slug_and_empty_content(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='slug'):
        worker.execute('write_plan', {'slug': 'Bad Slug', 'markdown': PLAN_MARKDOWN}, 'session')
    with pytest.raises(ValueError, match='empty'):
        worker.execute('write_plan', {'slug': 'good-slug', 'markdown': '   '}, 'session')
    with pytest.raises(ValueError, match='1 MiB'):
        worker.execute('write_plan', {'slug': 'good-slug', 'markdown': 'x' * 1048577}, 'session')
    assert not (tmp_path / '.plans').exists(), 'a refused plan must not create the folder'
# ---------------------------------------------------------------- đợt 20 §3–§5: chỉ mục + thang điểm
# Các ca dưới đây khoá **đường ghi mới**: chỉ mục box đọc được thì harness tự quyết
# identity/version/parent, ghép khối header của chính nó, chấm P1–P8 rồi mới cho sandbox ghi.
# Vì sao phải có: trước vòng 20 `plan_eval.py` không có chỗ gọi nào trong mã chạy thật (mọi
# fixture executor đều thiếu `request`), nên điểm P1–P8 không bao giờ xuất hiện trên máy thật.

def index_entry(version, slug, directory=''):
    """Một version của `GET /__box/plans/index` — khoá camelCase đúng như `plan_files.py` công bố."""
    prefix = f'{directory}/' if directory else ''
    return {'version': version, 'relativePath': f'.plans/{prefix}v{version}-{slug}.md',
            'sizeBytes': 120, 'modifiedAt': '2026-09-21T00:00:00Z', 'status': 'draft',
            'headerStatus': 'legacy'}


def index_group(identity, versions, slug=None):
    return {'identity': identity, 'slug': slug or (identity.rpartition('/')[2] or identity),
            'versions': list(versions)}


class BoxIndexExecutor(PlanFixtureExecutor):
    """Sandbox có chỉ mục đọc được: `write_plan` phải tự quyết số version rồi gửi số đó xuống.

    `race=True` mô phỏng hai người ghi cùng lúc: người kia chiếm mất số vừa chọn ngay trước khi op
    ghi chạy, nên box trả `PLAN_VERSION_TAKEN` đúng khuôn thật — `worker.py::__main__` **không** ném
    lỗi, nó trả `{'is_error': True, 'error': …}`.
    """

    def __init__(self, plans=(), race=False):
        super().__init__()
        self.plans = copy.deepcopy(list(plans))
        self.race = race
        self.raced = False
        self.index_reads = 0

    async def request(self, path, body=None):
        assert path == plan_registry.INDEX_PATH, 'chỉ chỉ mục plan được đọc bằng GET'
        self.index_reads += 1
        return {'plans': copy.deepcopy(self.plans)}

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name in JOURNAL_OPS:
            return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1}
        assert name == 'write_plan', 'write_plan must go through the sandbox executor'
        if self.race and not self.raced:
            self.raced = True
            # Người kia ghi THẲNG vào nhóm đang có (không phải một nhóm thứ hai cùng tên).
            entry = index_entry(args['version'], args['slug'], str(args.get('directory') or ''))
            group = next((item for item in self.plans if item['identity'] == args['slug']), None)
            if group is None:
                self.plans.append(index_group(args['slug'], [entry]))
            else:
                group['versions'] = sorted(list(group['versions']) + [entry], key=lambda item: item['version'])
            return {'is_error': True, 'error': f"PLAN_VERSION_TAKEN: v{args['version']}-{args['slug']}.md "
                                               'already exists; the harness must pick the next version'}
        version = args.get('version')
        if version is None:  # nhánh suy giảm: box tự chọn số, y như trước vòng 20
            version = max(self.used or {0}) + 1
            self.used.add(version)
        directory = str(args.get('directory') or '').strip('/')
        prefix = f'{directory}/' if directory else ''
        return {'content': 'Written', 'version': version, 'slug': args['slug'],
                'relativePath': f'.plans/{prefix}v{version}-{args["slug"]}.md',
                'title': str(args.get('title') or '')[:120],
                'bytes': len(args['markdown'].encode('utf-8'))}


def scored(store, sid):
    return events_of(store, sid, 'plan_evaluated')


#: F3 (đợt soát 2026-09-27): lượt ghi plan mà chưa có phán quyết phản biện bị nhắc ĐÚNG MỘT bước,
#: nên mỗi lượt ghi thành công cần thêm một câu trả lời. Thiếu nó thì iterator của fixture cạn, lượt
#: chết `TURN_FAILED_RUNTIMEERROR`, mà các phép kiểm ở đây chỉ đọc mặt ghi nên vẫn xanh — vì thế mỗi
#: bài dưới còn chốt cả `status` của phiên.
NUDGE_ANSWER = answer('Chưa chạy phản biện, dừng ở đây.')

def op_calls(executor):
    """Các op THẬT SỰ đi xuống box (bỏ `session_ensure`/`journal_append` — hạ tầng, không phải công cụ)."""
    return [(name, args) for name, args, _ in executor.calls if name not in JOURNAL_OPS]


def test_the_index_decides_the_version_and_the_write_is_scored(tmp_path):
    """Lần ghi đầu của một chủ đề mới: box nhận `version: 1` + header harness, và có một bản chấm."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor()
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi plan'),
            NUDGE_ANSWER]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        name, args = op_calls(executor)[0]
        assert name == 'write_plan'
        assert args['version'] == 1 and args['directory'] == '' and args['slug'] == 'workspace-plan'
        header = plan_header.build_plan_header(1, 'workspace-plan', None, None)
        assert args['markdown'].startswith('<!-- boxfox-plan\nVersion: v1\nIdentity: workspace-plan\n'
                                           'Parent: none\n-->\n')
        assert args['markdown'][len(header):] == PLAN_MARKDOWN, 'thân bài của model phải nguyên vẹn'

        written = events_of(store, sid, 'plan_written')
        assert len(written) == 1
        data = written[0]['data']
        assert data['identity'] == 'workspace-plan' and data['version'] == 1
        assert data['parentVersion'] is None, 'bản đầu của nhóm không có cha'
        assert data['headerSource'] == 'synthesized', 'model không viết header → harness chèn'
        assert data['identityMatchedBy'] == 'none' and data['identityForcedNew'] is False
        assert data['state'] == 'none', 'nhóm chưa có bản nào thì trạng thái là none'

        events = scored(store, sid)
        assert len(events) == 1, 'đúng MỘT sự kiện cho mỗi bản được chấm'
        assert events[0]['data']['written'] is True and events[0]['data']['total'] == 14
        assert events[0]['data']['verdict'] == 'pass' and events[0]['data']['levels']['P1'] == 1
        assert events[0]['seq'] == written[0]['seq'] + 1, 'bản chấm đi ngay sau plan_written'
        row = store.plan_evaluation('workspace-plan', 1)
        assert row['total'] == 14 and row['verdict'] == 'pass' and row['payload']['written'] is True
        assert tool_results(store, sid)[-1]['rubric']['total'] == 14
        assert executor.index_reads == 1, 'một lần ghi chỉ đọc chỉ mục một lần'
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_a_revision_must_name_the_version_it_revises(tmp_path):
    """§4.3 R1 + cổng cứng P2: bản sửa không nhắc `vN` bị từ chối, và **không** có byte nào bị ghi."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor([index_group('workspace-plan',
                                                [index_entry(1, 'workspace-plan')])])
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN})]),
            answer('Ghi lại cho đúng'),
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN_V2})]),
            answer('Đã ghi bản 2'),
            NUDGE_ANSWER]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Sửa plan')
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'PLAN_EVAL_REJECTED: (revision-untraceable)' in failures[0]['error']
        assert failures[0]['errorCode'] == 'PLAN_EVAL_REJECTED'
        assert op_calls(executor) == [], 'cổng cứng trượt thì sandbox không được chạm đĩa'
        assert events_of(store, sid, 'plan_written') == [] and events_of(store, sid, 'ui_intent') == []
        rejected = scored(store, sid)
        assert len(rejected) == 1 and rejected[0]['data']['written'] is False
        assert rejected[0]['data']['rejected'] == 'revision-untraceable'
        assert rejected[0]['data']['verdict'] == 'fail', 'bản không ghi được thì kết luận phải là fail'
        row = store.plan_evaluation('workspace-plan', 2)
        assert row['payload']['written'] is False, 'hàng điểm là bằng chứng vì sao không có file mới'

        # Lần thứ hai: đúng bản sửa có mục "thay đổi so với v1" → v2 với `Parent: v1`.
        await runtime.start(sid, 'Sửa plan lần hai')
        name, args = op_calls(executor)[0]
        assert name == 'write_plan' and args['version'] == 2 and args['directory'] == ''
        assert args['markdown'].startswith('<!-- boxfox-plan\nVersion: v2\nIdentity: workspace-plan\n'
                                           'Parent: v1\n-->\n')
        written = events_of(store, sid, 'plan_written')
        assert len(written) == 1 and written[0]['data']['parentVersion'] == 1
        assert len(scored(store, sid)) == 2, 'bản bị từ chối cũng có sự kiện; bản ghi được có thêm một cái'
        assert store.plan_evaluation('workspace-plan', 2)['payload']['written'] is True
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_a_header_the_model_wrote_that_disagrees_with_the_harness_is_refused(tmp_path):
    """§3.1: model không chọn được số version — khối nó viết chỉ được phép khớp con số harness quyết."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor([index_group('workspace-plan',
                                                [index_entry(1, 'workspace-plan')])])
        lying = ('<!-- boxfox-plan\nVersion: v3\nIdentity: workspace-plan\nParent: v1\n-->\n'
                 + PLAN_MARKDOWN_V2)
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': lying})]),
            answer('Thôi được')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'PLAN_EVAL_REJECTED: (header-mismatch)' in failures[0]['error']
        assert op_calls(executor) == [] and events_of(store, sid, 'plan_written') == []
        store.close()

    asyncio.run(run())


def test_an_ambiguous_slug_is_refused_with_the_argument_to_pass(tmp_path):
    """Dải `0.5 ≤ j < 0.75`: harness không tự đoán nhóm, và câu từ chối nói đúng tham số cần gọi lại."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor([
            index_group('research-patient-record-lookup', [index_entry(1, 'research-patient-record-lookup')])])
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'patient-record-lookup-history',
                                              'markdown': PLAN_MARKDOWN})]),
            answer('Chọn nhóm đi')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan mơ hồ')
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'PLAN_EVAL_REJECTED: (identity-ambiguous)' in failures[0]['error']
        assert 'identity: "research-patient-record-lookup"' in failures[0]['error']
        assert 'relatesTo: "none"' in failures[0]['error']
        assert op_calls(executor) == [] and scored(store, sid) == [], 'chưa chấm điểm khi chưa biết nhóm'
        store.close()

    asyncio.run(run())


def test_an_unreadable_index_falls_back_and_invents_nothing(tmp_path):
    """Chỉ mục box chết: hành vi cũ (box tự chọn số, không header) và **không** bịa điểm/cha."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = PlanFixtureExecutor()  # không có `request` → chỉ mục không đọc được
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi plan'),
            NUDGE_ANSWER]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        name, args = op_calls(executor)[0]
        assert name == 'write_plan' and 'version' not in args and 'directory' not in args
        assert args['markdown'] == PLAN_MARKDOWN, 'không có header nào được ghép ở nhánh suy giảm'
        data = events_of(store, sid, 'plan_written')[0]['data']
        assert set(data) == {'identity', 'version', 'slug', 'relativePath', 'title', 'bytes', 'contentHash'}, \
            'nhánh suy giảm không được thêm `parentVersion`/`headerSource` — hai giá trị đó chưa ai biết'
        assert scored(store, sid) == [] and store.plan_evaluation('workspace-plan', 1) is None
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_a_taken_version_is_retried_once_with_a_fresh_index(tmp_path):
    """Hai người ghi cùng lúc: đọc lại chỉ mục đúng MỘT lần rồi ghi lại, không ghi đè ai.

    Người kia chiếm `v1` ngay trước khi op ghi chạy. Lần ghi lại phải dùng `v2` đọc từ chỉ mục mới,
    và bản chấm phải thuộc về version **đã ghi được** — không phải version bị chiếm.
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor(race=True)
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': PLAN_MARKDOWN_V2})]),
            answer('Đã ghi plan'),
            NUDGE_ANSWER]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan đua')
        versions = [args.get('version') for name, args in op_calls(executor)]
        assert versions == [1, 2], 'lần thứ hai phải dùng số vừa đọc lại, không phải số cũ'
        assert executor.index_reads == 2, 'đọc lại đúng một lần'
        written = events_of(store, sid, 'plan_written')
        assert len(written) == 1 and written[0]['data']['version'] == 2
        assert written[0]['data']['parentVersion'] == 1 and written[0]['data']['headerSource'] == 'synthesized'
        assert written[0]['data']['relativePath'] == '.plans/v2-workspace-plan.md'
        assert [event['data']['version'] for event in scored(store, sid)] == [2], \
            'lần ghi bị chiếm số không được để lại hàng điểm'
        assert store.plan_evaluation('workspace-plan', 2)['payload']['written'] is True
        assert store.plan_evaluation('workspace-plan', 1) is None
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_the_refusal_line_tells_the_model_what_to_change(tmp_path):
    """Câu từ chối phải là câu khắc phục của **chiều vừa trượt**, không phải câu chung.

    Lỗi bắt được ở lượt chạy sống 2026-09-21 (session `00042bab…`): `plan_eval` có bảng khắc phục
    riêng, nhưng `PlanRegistrationError` dựng lại câu bằng bảng của `plan_registry` — model nhận
    đúng một dòng "không thoả luật của harness" rồi phải tự đoán. Bài này chốt câu chữ ở tầng công cụ.
    """
    prose_steps = PLAN_MARKDOWN.replace(
        '1. Chạy `.venv/bin/python -m pytest backend/tests -q`; mong đợi 9 passed.\n'
        '2. Gọi `GET /api/agent/health` và xác nhận mã trả về là 200.',
        '1. Viết tài liệu cho người dùng.\n2. Xem lại lần cuối.')

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor()
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': prose_steps})]),
            answer('Viết lại cho có neo')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan thiếu neo')
        failure = [result for result in tool_results(store, sid) if result.get('is_error')][0]
        assert failure['errorCode'] == 'PLAN_EVAL_REJECTED'
        assert 'steps-unanchored' in failure['error'] and 'chỉ 0/2 bước' in failure['error']
        assert 'thêm lệnh/kết quả vào từng bước' in failure['error']
        assert 'không thoả luật của harness' not in failure['error']
        assert op_calls(executor) == [] and events_of(store, sid, 'plan_written') == []
        store.close()

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# C4 (đợt 22, quyết định D-3) — dải mơ hồ để lại một VÉ dùng đúng một lần
#
# Dải `0.5 ≤ j < 0.75` trước đây chặn vĩnh viễn: model gửi lại y nguyên vẫn mơ hồ, nên chủ đề
# không bao giờ thành kế hoạch. Nay lời từ chối ghim một hàng dữ kiện `F:` mang vé
# (`data.identityAmbiguityTicket`, khớp theo `(slug, directory)`, và vé chỉ dùng được khi slug
# CHƯA có nhóm) — gửi lại nguyên văn lần đầu thì nhận là kế hoạch mới, có dấu trên hàng `P:`.
# --------------------------------------------------------------------------- #

AMBIGUOUS_SLUG = 'patient-record-lookup-history'   # j = 0.6 với nhóm bên dưới
AMBIGUOUS_OTHER = 'research-record-patient-notes'  # cũng 0.6, slug khác
MATCHED_IDENTITY = 'research-patient-record-lookup'
AMBIGUITY_MARK = {'score': 0.6, 'nearestIdentity': MATCHED_IDENTITY}


def index_with_the_matched_group():
    return [index_group(MATCHED_IDENTITY, [index_entry(1, MATCHED_IDENTITY)])]


def ticket_rows(store, sid):
    """Các hàng `F:` mang vé mơ hồ của một phiên, kèm chính hàng đó (đọc từ SQLite)."""
    found = []
    for row in store.journal_tail(sid, kinds=['fact']):
        record = row['payload']['record']
        ticket = (record.get('data') or {}).get(plan_registry.AMBIGUITY_TICKET_KEY)
        if ticket:
            found.append((record, ticket))
    return found


class GrowingIndexExecutor(BoxIndexExecutor):
    """Chỉ mục biết cập nhật sau mỗi lần ghi: `plan_files.py` làm đúng việc này.

    Không có nó thì lần gửi lại thứ hai không phân biệt được "vé đã tiêu" với "vé dùng lại được":
    chỉ khi nhóm đã có mặt trong chỉ mục thì `ambiguity_ticket_usable` mới thật sự từ chối đường vé.
    """

    async def execute(self, name, args, sid):
        result = await super().execute(name, args, sid)
        if name == 'write_plan' and not result.get('is_error'):
            directory = str(args.get('directory') or '').strip('/')
            identity = f'{directory}/{args["slug"]}' if directory else args['slug']
            entry = index_entry(result['version'], args['slug'], directory)
            group = next((item for item in self.plans if item['identity'] == identity), None)
            if group is None:
                self.plans.append(index_group(identity, [entry]))
            elif not [item for item in group['versions'] if item['version'] == result['version']]:
                group['versions'].append(entry)
        return result


def test_an_ambiguous_refusal_leaves_a_one_shot_ticket(tmp_path):
    """Lời từ chối vì mơ hồ ghim đúng một hàng `F:` mang vé — không phải hàng `P:`."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor(index_with_the_matched_group())
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_SLUG, 'markdown': PLAN_MARKDOWN})]),
            answer('Chọn nhóm đi')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan mơ hồ')
        failures = [result for result in tool_results(store, sid) if result.get('is_error')]
        assert failures and 'PLAN_EVAL_REJECTED: (identity-ambiguous)' in failures[0]['error']

        rows = ticket_rows(store, sid)
        assert len(rows) == 1, 'một lần từ chối = một vé'
        record, ticket = rows[0]
        assert record['kind'] == 'fact' and record['status'] == 'info'
        assert record['text'].startswith('PLAN_IDENTITY_AMBIGUOUS:')
        assert ticket == {'slug': AMBIGUOUS_SLUG, 'directory': '', 'matchedIdentity': MATCHED_IDENTITY,
                          'score': 0.6, 'candidates': [{'identity': MATCHED_IDENTITY, 'score': 0.6}]}
        assert 'relativePath' not in ticket, \
            'vé không được giữ kế hoạch nào: cổng xoá `--delete-orphan` chỉ đọc hàng `P:`'
        # Hàng `E:` (cổng bằng chứng, đợt 3 vòng 22) nằm cùng nhật ký và không liên quan tới phép
        # kiểm này: thứ phải VẮNG là hàng kế hoạch `P:`, nên lọc `E:` ra rồi mới so — nếu một hàng
        # `P:` lọt vào thì phép khẳng định vẫn đỏ.
        assert [row['kind'] for row in store.journal_tail(sid) if row['kind'] != 'evidence'] == ['fact'], \
            'bản bị từ chối không để lại hàng `P:` nào'
        assert op_calls(executor) == [] and events_of(store, sid, 'plan_written') == []
        store.close()

    asyncio.run(run())


def test_resending_the_same_plan_verbatim_is_accepted_once(tmp_path):
    """Gửi lại nguyên văn: nhận là kế hoạch MỚI, và hàng `P:` mang dấu dải mơ hồ."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = GrowingIndexExecutor(index_with_the_matched_group())
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_SLUG, 'markdown': PLAN_MARKDOWN})]),
            answer('Chọn nhóm đi'),
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_SLUG, 'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi bản mới'),
            NUDGE_ANSWER,
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_SLUG, 'markdown': PLAN_MARKDOWN_V2})]),
            answer('Đã ghi bản 2'),
            NUDGE_ANSWER]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan mơ hồ')
        await runtime.start(sid, 'Gửi lại nguyên văn')
        await runtime.start(sid, 'Sửa lại lần nữa')

        writes = op_calls(executor)
        assert [args['version'] for name, args in writes] == [1, 2], \
            'lần gửi lại nhận là nhóm mới ở v1; lần thứ ba đi theo chỉ mục (v2), không mở nhóm thứ ba'
        assert {args['slug'] for name, args in writes} == {AMBIGUOUS_SLUG}
        assert {args.get('directory') for name, args in writes} == {''}
        assert writes[0][1]['markdown'].startswith('<!-- boxfox-plan\nVersion: v1\nIdentity: '
                                                   f'{AMBIGUOUS_SLUG}\nParent: none\n-->')

        written = events_of(store, sid, 'plan_written')
        assert [event['data']['version'] for event in written] == [1, 2]
        first = written[0]['data']
        assert first['identityMatchedBy'] == plan_registry.AMBIGUITY_MATCHED_BY
        assert first['identityForcedNew'] is False
        assert first['identityAmbiguity'] == AMBIGUITY_MARK, 'hàng `P:` phải đọc được vì sao bản này ra đời'
        assert written[1]['data']['identityMatchedBy'] == 'similarity'
        assert 'identityAmbiguity' not in written[1]['data'], 'vé đã tiêu: bản sau đi theo chỉ mục'

        pinned = store.journal_tail(sid, kinds=['plan'])
        assert [row['payload']['record']['data']['version'] for row in pinned] == [1, 2]
        assert pinned[0]['payload']['record']['data']['identityAmbiguity'] == AMBIGUITY_MARK
        assert 'identityAmbiguity' not in pinned[1]['payload']['record']['data']
        assert store.get(sid)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())


def test_the_ticket_does_not_leak_to_another_slug_or_session(tmp_path):
    """Vé khớp theo `(slug, directory)` VÀ theo phiên: slug khác vẫn bị từ chối, phiên khác cũng vậy."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = BoxIndexExecutor(index_with_the_matched_group())
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_SLUG, 'markdown': PLAN_MARKDOWN})]),
            answer('Chọn nhóm đi'),
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_OTHER, 'markdown': PLAN_MARKDOWN})]),
            answer('Slug này cũng mơ hồ'),
            answer(calls=[call('write_plan', {'slug': AMBIGUOUS_SLUG, 'markdown': PLAN_MARKDOWN})]),
            answer('Phiên này chưa từng bị từ chối')]))
        first = runtime.create({'skills': []})['id']
        second = runtime.create({'skills': []})['id']

        await runtime.start(first, 'Ghi plan mơ hồ')
        await runtime.start(first, 'Ghi slug khác cũng mơ hồ')
        await runtime.start(second, 'Gửi lại nguyên văn ở phiên khác')

        rows = ticket_rows(store, first)
        assert [ticket['slug'] for _record, ticket in rows] == [AMBIGUOUS_SLUG, AMBIGUOUS_OTHER], \
            'mỗi lần từ chối có vé riêng, khớp theo (slug, directory)'
        facts = store.journal_tail(first, kinds=['fact'])
        assert plan_registry.ticket_from_rows(facts, slug=AMBIGUOUS_OTHER)['slug'] == AMBIGUOUS_OTHER
        assert plan_registry.ticket_from_rows(facts, slug='workspace-plan') is None
        second_rows = ticket_rows(store, second)
        assert len(second_rows) == 1 and second_rows[0][1]['slug'] == AMBIGUOUS_SLUG
        assert events_of(store, second, 'plan_written') == [], 'vé của phiên khác không dùng được'
        assert events_of(store, first, 'plan_written') == [] and op_calls(executor) == []
        store.close()

    asyncio.run(run())


def test_a_plan_written_by_a_delegated_session_belongs_to_the_root_session(tmp_path):
    """Vòng 25 (D-36): sổ sở hữu phải trỏ về phiên GỐC, vì chỉ phiên gốc mở được trong khung chat.

    Đo vòng 25: ba cú bấm ở tab Plan đều ghi được hàng duyệt nhưng `plan_reviews.session_id` là
    `NULL`, nên không có phiên nào để đánh thức. Con `plan` ghi kế hoạch hộ cây là chuyện thường —
    đường về phải là phiên gốc, không phải phiên con (phiên con không có chat để hiện lượt mới).
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = PlanFixtureExecutor()
        model = FixtureModel([
            answer('Viết plan', calls=[call('write_plan', {'slug': 'Workspace Plan',
                                                           'markdown': PLAN_MARKDOWN})]),
            answer('Đã ghi plan'),
            NUDGE_ANSWER])
        runtime = HarnessRuntime(store, executor, model)
        root = runtime.create({'skills': []})['id']
        # Con thật trong cây: cùng cấu hình đã chuẩn hoá của phiên gốc, khác `parent_id`.
        child = store.create(store.get(root)['config'], role='plan', parent_id=root)['id']

        await runtime.start(child, 'Viết plan hộ phiên gốc')

        owner = store.plan_owner('workspace-plan')
        assert owner is not None, 'ghi kế hoạch phải để lại hàng sở hữu'
        assert owner['session_id'] == root, 'phiên sở hữu là phiên GỐC, không phải phiên con'
        assert owner['first_session_id'] == root
        assert owner['relative_path'] == '.plans/v1-workspace-plan.md'
        assert events_of(store, child, 'plan_written'), 'bản ghi vẫn thuộc phiên đã viết nó'

        # Ghi từ chính phiên gốc: vẫn cùng một hàng, không nhân đôi theo người viết.
        model.responses = iter([answer('Viết tiếp', calls=[call('write_plan', {
            'slug': 'Workspace Plan', 'markdown': PLAN_MARKDOWN_V2})]), answer('Đã ghi bản 2')])
        await runtime.start(root, 'Viết bản 2')
        rows = store.db.execute('SELECT COUNT(*) AS total FROM plan_owners').fetchone()['total']
        assert rows == 1
        assert store.plan_owner('workspace-plan')['session_id'] == root
        assert store.plan_owner('workspace-plan')['first_session_id'] == root
        assert store.get(child)['status'] == 'completed', \
            'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
        store.close()

    asyncio.run(run())
