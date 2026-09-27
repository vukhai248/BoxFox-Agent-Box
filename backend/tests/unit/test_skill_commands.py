import asyncio
import copy
import json
from pathlib import Path
import pytest
from agentbox.skills.commands import CommandRegistry, BUILTINS, ROLE_COMMANDS, ROLE_SKILLS
from agentbox.skills.catalog import SkillCatalog
from agentbox.skills.lifecycle import SkillLoader
from agentbox.memory.session_store import SessionStore
from agentbox.agent_core.runtime import HarnessRuntime

INTENTS = json.loads((Path(__file__).parents[1] / 'fixtures/skill_intents_v1.json').read_text(encoding='utf-8'))


@pytest.fixture
def registry(tmp_path):
    store = SessionStore(tmp_path / 'commands.sqlite')
    registry = CommandRegistry(store, SkillCatalog())
    registry.configure({'enabled': list(registry.catalog.items), 'revision': 0})
    yield registry
    store.close()


@pytest.mark.parametrize('prompt,expected', INTENTS)
def test_intent_policy(registry, prompt, expected):
    if expected in {'unavailable', 'conflict'}:
        with pytest.raises(ValueError, match='ADAPTER_UNAVAILABLE' if expected == 'unavailable' else 'EXECUTOR_CONFLICT'):
            registry.resolve(prompt)
        return
    result = registry.resolve(prompt)
    # P1 (§5.2, cửa 3): `/research` giờ là lệnh MODE (`kind='mode'`) khi công tắc bật; ghim thẳng
    # `kind` cho nó thay vì suy ra `role` (mode không có vai con).
    actual = result.kind if result.kind in {'message', 'control', 'mode'} else result.skills[0] if result.command in {'claude-code', 'claude-design', 'skill'} or result.reason == 'explicit_use_intent' else result.role
    assert actual == expected


@pytest.mark.parametrize('key', sorted(BUILTINS))
def test_reserved_names(registry, key):
    with pytest.raises(ValueError, match='COLLISION'):
        registry.save({'slug': key, 'template': '$ARGUMENTS'})


@pytest.mark.parametrize('key,role', ROLE_COMMANDS.items())
def test_role_commands_never_expand_capabilities(registry, key, role):
    resolved = registry.resolve('/' + key + ' inspect', subagents=[{'id': role}])
    assert resolved.role == role and set(resolved.skills) <= ROLE_SKILLS[role]
    with pytest.raises(ValueError, match='ROLE_DISABLED'):
        registry.resolve('/' + key + ' inspect', subagents=[])


@pytest.mark.parametrize('bad', ['/.plan hi', '/unknown hi', '/plan', '/help extra', '/plan /build hi', '/skill', '/skill missing hi'])
def test_invalid_commands_are_not_sent_to_model(registry, bad):
    with pytest.raises(ValueError):
        registry.resolve(bad)


@pytest.mark.parametrize('prompt', ['/skill codebase-inspection', '/codebase-inspection'])
def test_missing_task_after_skill_command_carries_stable_code(registry, prompt):
    """`/skill <id>` (và alias kỹ năng) thiếu task phải có mã lỗi ổn định cho UI.

    Trước đây nhánh này chỉ ném `Include a task after the command` trần, nên UI
    không hiển thị dòng `Mã lỗi: …` như các nhánh UNKNOWN_COMMAND / SKILL_DISABLED.
    """
    with pytest.raises(ValueError, match=r'^SKILL_TASK_REQUIRED: Include a task after the command$'):
        registry.resolve(prompt)


def test_missing_task_after_role_command_carries_stable_code(registry):
    with pytest.raises(ValueError, match=r'^MISSING_TASK: Include a task after the command$'):
        registry.resolve('/build')


def test_custom_revision_literal_arguments_and_restart(registry):
    c = registry.save({'slug': 'fix-custom', 'template': 'Fix $ARGUMENTS', 'skills': ['systematic-debugging'], 'role': 'debug'})
    resolved = registry.resolve('/fix-custom $(whoami); /build more')
    assert resolved.prompt == 'Fix $(whoami); /build more'
    assert resolved.revision == c['revision']
    with pytest.raises(ValueError, match='REVISION'):
        registry.save(c | {'revision': 0}, c['slug'])
    updated = registry.save(c | {'enabled': False}, c['slug'])
    with pytest.raises(ValueError, match='DISABLED'):
        registry.resolve('/fix-custom task')
    reopened = CommandRegistry(registry.store, registry.catalog)
    assert reopened.custom()[0]['revision'] == 2
    registry.delete(c['slug'], updated['revision'])
    assert not registry.custom()


def test_import_once_and_disabled_skill(registry):
    original = registry.settings()
    assert registry.configure({'enabled': [], 'importLegacy': True}) == original
    registry.configure({'enabled': [], 'revision': original['revision']})
    with pytest.raises(ValueError, match='SKILL_DISABLED'):
        registry.resolve('/claude-code hello')


@pytest.mark.parametrize('role', ['plan', 'review', 'research', 'explore'])
def test_readonly_role_rejects_writing_workflow(registry, role):
    with pytest.raises(ValueError, match='ROLE_SKILL_CONFLICT'):
        registry.save({'slug': 'bad-role', 'template': '$ARGUMENTS', 'skills': ['claude-design'], 'role': role})


class Executor:
    async def cleanup(self, sid): pass
    async def execute(self, *args): raise AssertionError('No effects expected')


class Model:
    def __init__(self): self.requests = []
    async def complete(self, messages, tools, route, **kwargs):
        self.requests.append(copy.deepcopy(messages))
        return {'choices': [{'message': {'content': 'verified fixture result'}, 'finish_reason': 'stop'}]}


def test_command_child_plan_idempotency_and_skill_snapshot(registry):
    async def run():
        model = Model()
        runtime = HarnessRuntime(registry.store, Executor(), model, registry.catalog)
        parent = runtime.create({'skills': []})
        first = await runtime.submit(parent['id'], '/plan Inspect the system', invocation_id='invocation-1')
        same = await runtime.submit(parent['id'], '/plan Inspect the system', invocation_id='invocation-1')
        assert first == same
        await runtime.tasks[parent['id']]
        children = registry.store.db.execute('SELECT id FROM sessions WHERE parent_id=?', (parent['id'],)).fetchall()
        assert len(children) == 1
        child = registry.store.get(children[0]['id'])
        assert child['role'] == 'plan'
        assert 'file_write' not in child['config']['tools']
        assert child['status'] == 'completed'
        with pytest.raises(ValueError, match='INVOCATION_CONFLICT'):
            await runtime.submit(parent['id'], '/build change scope', invocation_id='invocation-1')
    asyncio.run(run())


def test_busy_controls_never_start_second_model_call(registry, monkeypatch):
    """Lượt đang chạy: lệnh điều khiển vẫn chạy, và lời nhắn của chủ nhà KHÔNG mở lượt thứ hai.

    Vòng 27 (đợt 7, D-43) đổi kết cục của lời nhắn giữa lượt từ `SESSION_BUSY` thành một chỉ thị
    chờ bơm — nhưng bất biến cũ giữ nguyên: đúng MỘT lượt model sống tại một thời điểm. Tắt công
    tắc (`BOXFOX_STEER=off`) phải trả về đúng hành vi cũ.
    """
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = {'n': 0}
        class Waiting(Model):
            async def complete(self, *args, **kwargs):
                calls['n'] += 1
                started.set(); await finish.wait()
                return await super().complete(*args, **kwargs)
        runtime = HarnessRuntime(registry.store, Executor(), Waiting(), registry.catalog)
        sid = runtime.create({'skills': []})['id']
        await runtime.submit(sid, 'hello')
        await started.wait()
        assert calls['n'] == 1
        assert (await runtime.submit(sid, '/status'))['status'] == 'running'
        steered = await runtime.submit(sid, 'đổi hướng: chỉ đọc tầng 1')
        assert steered['status'] == 'steered' and steered['steerId']
        assert steered['pending'] == 1
        assert calls['n'] == 1, 'chỉ thị không được mở lượt model thứ hai'
        assert runtime.store.pending_steer_count(sid) == 1
        monkeypatch.setenv('BOXFOX_STEER', 'off')
        with pytest.raises(ValueError, match='SESSION_BUSY'):
            await runtime.submit(sid, '/plan task')
        assert calls['n'] == 1
        await runtime.submit(sid, '/stop')
        assert runtime.store.get(sid)['status'] == 'cancelled'
    asyncio.run(run())


def test_a_child_session_still_refuses_a_message_mid_turn(registry):
    """Con không nói chuyện với chủ nhà (#5961): con đang chạy thì lời nhắn vẫn là `SESSION_BUSY`."""
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        class Waiting(Model):
            async def complete(self, *args, **kwargs):
                started.set(); await finish.wait()
                return await super().complete(*args, **kwargs)
        runtime = HarnessRuntime(registry.store, Executor(), Waiting(), registry.catalog)
        sid = runtime.create({'skills': []})['id']
        child = runtime.create({'skills': []}, parent_id=sid, role='research')
        await runtime.submit(child['id'], 'việc con')
        await started.wait()
        with pytest.raises(ValueError, match='SESSION_BUSY'):
            await runtime.submit(child['id'], 'nói thêm')
        assert runtime.store.pending_steer_count(child['id']) == 0
        await runtime.submit(child['id'], '/stop')
    asyncio.run(run())


@pytest.mark.parametrize('sid', ['codebase-inspection', 'systematic-debugging', 'requesting-code-review', 'simplify-code', 'test-driven-development', 'grounded-citations', 'final-report', 'planning'])
@pytest.mark.parametrize('scenario', ['full', 'dedup', 'compression', 'new-child', 'disabled'])
def test_skill_lifecycle(registry, sid, scenario):
    runtime = HarnessRuntime(registry.store, Executor(), Model(), registry.catalog)
    session = runtime.create({'skills': [sid], 'contextWindow': 200000})
    loader = SkillLoader(registry.catalog, registry.store.emit)
    first = loader.read(session, sid)
    assert first['content'] == registry.catalog.items[sid]['_path'].read_text(encoding='utf-8')
    assert first['basePath'].startswith('/opt/boxfox-skills/')
    messages = [{'role': 'tool', 'content': json.dumps(first, ensure_ascii=False)}]
    if scenario == 'dedup':
        assert loader.read(session, sid, messages=messages)['status'] == 'unchanged'
    elif scenario == 'compression':
        loader.reset(session['id'])
        assert loader.read(session, sid, messages=[])['content'] == first['content']
    elif scenario == 'new-child':
        child = runtime.create({'skills': [sid], 'contextWindow': 200000}, parent_id=session['id'])
        assert loader.read(child, sid, messages=messages)['content'] == first['content']
    elif scenario == 'disabled':
        session['config']['skills'] = []
        with pytest.raises(PermissionError): loader.read(session, sid)


def test_skill_change_and_linked_file_path(tmp_path):
    root = tmp_path / 'skills' / 'demo'
    root.mkdir(parents=True)
    (root / 'SKILL.md').write_text('---\nname: demo\n---\nfirst', encoding='utf-8')
    (root / 'ref.md').write_text('evidence', encoding='utf-8')
    catalog = SkillCatalog(tmp_path)
    session = {'id': 'one', 'config': {'skills': ['demo'], 'contextWindow': 32768}}
    loader = SkillLoader(catalog, lambda *args: None)
    first = loader.read(session, 'demo')
    (root / 'SKILL.md').write_text('changed', encoding='utf-8')
    assert loader.read(session, 'demo')['sha256'] != first['sha256']
    assert loader.read(session, 'demo', 'ref.md')['content'] == 'evidence'
    with pytest.raises(ValueError): loader.read(session, 'demo', '../../escape')


@pytest.mark.parametrize('key,value', [
    ('slug', ''), ('slug', '/custom'), ('slug', '../file'), ('slug', 'UPPER'), ('slug', 'one two'), ('slug', 'x'),
    ('template', ''), ('template', None), ('template', 'x' * 12001), ('template', []),
    ('skills', ['unknown']), ('skills', 'debug'), ('skills', [None]), ('skills', ['codex']), ('skills', ['opencode']),
    ('skills', ['claude-code']), ('skills', ['claude-code', 'codex']),
    ('executor', 'codex'), ('executor', 'opencode'), ('executor', 'shell'), ('executor', ''),
    ('role', 'admin'), ('role', 'orchestrator'), ('role', ''), ('role', 'test'),
    ('enabled', 'yes'), ('enabled', 1), ('enabled', None),
    ('description', []), ('description', None), ('description', 'x' * 501),
])
def test_custom_invalid_contracts(registry, key, value):
    with pytest.raises(ValueError):
        registry.save({'slug': 'valid-custom', 'template': '$ARGUMENTS', key: value})


@pytest.mark.parametrize('argument', ['$(cat secret)', '`whoami`', '${TOKEN}', '!`date`', '/plan more'])
def test_custom_template_never_executes_or_reparses(registry, argument):
    registry.save({'slug': 'literal-task', 'template': 'Inspect: $ARGUMENTS', 'skills': [], 'role': 'explore'})
    if argument.startswith('/'):
        with pytest.raises(ValueError): registry.resolve('/literal-task ' + argument)
    else:
        assert registry.resolve('/literal-task ' + argument).prompt == 'Inspect: ' + argument


ATTACHMENT_ROW = {'name': 'báo cáo.md', 'path': '.uploaded_artifacts/7.md', 'sizeBytes': 12288}
BLOCK_HEADER = '[Tệp đính kèm đã lưu trong box]'


def test_command_child_receives_the_attachment_block(registry):
    """A7 (soát F3): tệp đính kèm phải tới được MÔ HÌNH LÀM VIỆC — phiên con của lệnh.

    Triệu chứng BUG-40 là mô hình không có đường đọc tệp; trên đường command/skill mô hình làm
    việc thật là con, nên khối đường dẫn phải nằm trong thân của CON, không chỉ trong bản lưu
    của phiên cha.
    """
    async def run():
        model = Model()
        runtime = HarnessRuntime(registry.store, Executor(), model, registry.catalog)
        parent = runtime.create({'skills': []})
        await runtime.submit(parent['id'], '/plan Inspect the system',
                             attachments=[ATTACHMENT_ROW], invocation_id='invocation-a7')
        await runtime.tasks[parent['id']]
        children = registry.store.db.execute('SELECT id FROM sessions WHERE parent_id=?',
                                             (parent['id'],)).fetchall()
        child = registry.store.get(children[0]['id'])
        stored = json.dumps(child['messages'], ensure_ascii=False)
        assert BLOCK_HEADER in stored
        assert '- /home/agent/workspace/.uploaded_artifacts/7.md (báo cáo.md, 12 KB)' in stored
        seen = json.dumps(model.requests, ensure_ascii=False)
        assert BLOCK_HEADER in seen, 'thân gửi mô hình của con cũng mang khối'
        assert '/home/agent/workspace/.uploaded_artifacts/7.md' in seen
    asyncio.run(run())


@pytest.mark.parametrize('row,code', [
    ({'name': 'x', 'path': '../etc/passwd', 'sizeBytes': 1}, 'ATTACHMENTS_INVALID'),
    ({'name': 'x', 'path': '.uploaded_artifacts/9.md', 'sizeBytes': float('inf')}, 'ATTACHMENTS_INVALID'),
    ({'name': 'x', 'path': '.uploaded_artifacts/9.md', 'sizeBytes': 10 ** 400}, 'ATTACHMENTS_INVALID'),
])
def test_a_refused_file_list_leaves_no_admission_row(registry, row, code):
    """Soát F8: danh sách tệp sai là 400 TRƯỚC khi ghi hàng admission — không hàng `running` mắc kẹt."""
    async def run():
        runtime = HarnessRuntime(registry.store, Executor(), Model(), registry.catalog)
        parent = runtime.create({'skills': []})
        with pytest.raises(ValueError, match=code):
            await runtime.submit(parent['id'], '/plan task', invocation_id='invocation-bad',
                                 attachments=[row])
        rows = registry.store.db.execute('SELECT id FROM command_invocations WHERE session_id=?',
                                         (parent['id'],)).fetchall()
        assert [one['id'] for one in rows] == [], 'lượt bị từ chối không để lại hàng admission'
        assert runtime.store.get(parent['id'])['status'] != 'running'
    asyncio.run(run())


def test_command_child_inherits_the_session_time_budget(registry):
    """Con của lệnh phải có cùng ngân sách thời gian với phiên, không phải mặc định 180 giây.

    Đo sống 2026-09-20: phiên đặt 600 giây vẫn kết thúc `DEADLINE` ở lượt `/claude-code`, vì
    con của lệnh không được truyền `deadlineSeconds` nên rơi về mặc định 180 giây.
    """
    async def run():
        runtime = HarnessRuntime(registry.store, Executor(), Model(), registry.catalog)
        # Phiên chốt trần 600 giây (create_session), nên so với chính giá trị đã lưu của phiên.
        parent = runtime.create({'skills': [], 'deadlineSeconds': 600})
        await runtime.submit(parent['id'], '/plan Inspect the system', invocation_id='invocation-2')
        await runtime.tasks[parent['id']]
        children = registry.store.db.execute('SELECT id FROM sessions WHERE parent_id=?', (parent['id'],)).fetchall()
        child = registry.store.get(children[0]['id'])
        budget = registry.store.get(parent['id'])['config']['deadlineSeconds']
        assert budget == 600
        assert child['config']['deadlineSeconds'] == budget, 'con lấy đúng ngân sách của phiên'
    asyncio.run(run())


def test_command_child_never_gets_more_steps_than_the_session(registry):
    """Soát engine #2: đường lệnh/kỹ năng không truyền `maxSteps`, nên con rộng hơn cha.

    `delegate()` tự kẹp con của nó, nhưng con của lệnh được dựng bằng `create()` với
    `deadlineSeconds` của phiên và **không** có `maxSteps` ⇒ rơi về mặc định 40 bước: phiên đặt
    12 bước sinh ra con 40 bước. Luật "con không rộng hơn cha" giờ nằm trong `create()`.
    """
    async def run():
        runtime = HarnessRuntime(registry.store, Executor(), Model(), registry.catalog)
        parent = runtime.create({'skills': [], 'maxSteps': 12, 'deadlineSeconds': 600})
        await runtime.submit(parent['id'], '/plan Inspect the system', invocation_id='invocation-4')
        await runtime.tasks[parent['id']]
        children = registry.store.db.execute('SELECT id FROM sessions WHERE parent_id=?', (parent['id'],)).fetchall()
        assert len(children) == 1
        child = registry.store.get(children[0]['id'])
        assert child['config']['maxSteps'] == 12, 'con phải kẹp theo cha, không phải mặc định 40'
        assert child['config']['deadlineSeconds'] <= 600
    asyncio.run(run())
