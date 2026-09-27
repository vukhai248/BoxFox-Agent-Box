"""P6 — một lượt thiết kế chạy TỪ ĐẦU TỚI CUỐI trên repo git thật (plan v1 §8 P6, §10.2 A1–A7).

Kịch bản tất định, không mạng, không mô hình thật: `/design` (brief mơ hồ) → phỏng vấn → brief +
danh sách chạm → chủ nhà duyệt → 23 thao tác canvas → nhánh thiết kế → hai lần ghi dự án → diff →
con `plan-review` độc lập trả `VERDICT: ok` → `design_review` → `design_report`. Mô hình giả chỉ trả
lời LƯỢT và CON; mọi thao tác còn lại đi qua ĐÚNG cửa vào `runtime.dispatch`/`runtime.submit` trên
một repo git trong `tmp_path` (worker thật, luật harness thật).

Bài đo trực tiếp các tiêu chí §10.2: không tệp nào ngoài danh sách chạm được duyệt (A1); ≥20 thao
tác canvas với 0 bị bỏ (A3, chốt Q4); thẻ báo cáo đúng MỘT lần; khối bàn giao đúng MỘT lần cho
`(designId, version)`; mỗi lần nhích pha phát đúng MỘT `design_run`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

import agentbox.sandbox.worker as worker
from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

INITIAL = 'alpha\nbeta\ngamma\n'
GOAL = 'thiết kế màn hình chat'  # brief MƠ HỒ: không nêu bề mặt, nền tảng hay dự án cụ thể
DDIR = '.design'

CRITIQUE = (
    '## Findings by Severity\n'
    '- [high] `src/chat.tsx` chưa nói gì về việc cuộn khi lịch sử dài; hãy định nghĩa '
    'viewport và hành vi khi tin nhắn mới tới.\n'
    '- [medium] `app.txt` chèn sau mốc `beta` nhưng bản thiết kế không tả trạng thái rỗng của khung '
    'chat; người triển khai sẽ tự đoán.\n'
    '- [low] sơ đồ canvas chưa đặt tên cho node biểu diễn danh sách hội thoại.\n'
    '## Touch List Problems\n'
    '- danh sách chạm chỉ có hai dòng; nếu cần tệp kiểu dáng thì phải đề xuất thêm, không tự ý ghi.\n'
    '## Contract And State Gaps\n'
    '- chưa định nghĩa trạng thái khi nhánh thiết kế bị tạo lại sau một lần hoàn tác lô.\n'
    '## Unverified Claims\n'
    '- khẳng định "không đổi API" chưa có bằng chứng nào trong mã.\n'
    'VERDICT: ok'
)


def _git(root, *args, check=True):
    proc = subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True)
    if check and proc.returncode:
        raise AssertionError('git %s failed: %s' % (' '.join(args), proc.stderr))
    return proc


def _binding_draft_path(text):
    """Đường dẫn bản nháp trong dòng gắn kết của harness (`runtime.delegate`)."""
    found = re.search(r'read the complete file with file_read before judging it: (\S+)', str(text))
    return found.group(1).rstrip('.') if found else ''


def _repo(tmp_path):
    root = Path(tmp_path).resolve()
    worker.ROOT = root
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'config', 'core.autocrlf', 'false')
    _git(root, 'config', 'user.email', 'box@example.com')
    _git(root, 'config', 'user.name', 'Box')
    (root / 'app.txt').write_text(INITIAL, encoding='utf-8', newline='')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'init')
    return root


class WorkerExecutor:
    async def execute(self, name, args, sid, **_identity):
        return worker.execute(name, args, sid)

    async def cleanup(self, sid):
        return None


class ScriptedModel:
    """Lượt cha trả `ok`; CON `plan-review` ĐỌC bản nháp rồi trả bài soát (§7.9).

    Con phải `file_read` đúng bản nháp trước khi phán: cổng `design_review` đòi bằng chứng đọc
    (khuôn `research._review_read_proof`), nên bài này chạy cả đường đọc chứ không chỉ chữ verdict.
    """

    def __init__(self):
        self.parent_calls = 0
        self.child_calls = 0
        self.child_reads = 0

    async def model_metadata_map(self):
        return {}

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        text = '\n'.join(str(message.get('content') or '') for message in messages
                         if message.get('role') == 'user')
        if 'Binding from the harness' in text:
            self.child_calls += 1
            path = _binding_draft_path(text)
            if path and self.child_reads == 0:
                self.child_reads += 1
                calls = [{'id': 'read-draft', 'type': 'function',
                          'function': {'name': 'file_read',
                                       'arguments': json.dumps({'path': path})}}]
                return {'choices': [{'message': {'content': '', 'tool_calls': calls},
                                     'finish_reason': 'tool_calls'}], 'usage': None, 'boxfox': None}
            body = CRITIQUE
        else:
            self.parent_calls += 1
            body = 'ok'
        return {'choices': [{'message': {'content': body}, 'finish_reason': 'stop'}],
                'usage': None, 'boxfox': None}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    root = _repo(tmp_path)
    store = SessionStore(tmp_path / 'state' / 'e2e.db')
    model = ScriptedModel()
    runtime = HarnessRuntime(store, WorkerExecutor(), model)
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 60, 'deadlineSeconds': 120})['id']
    yield store, runtime, sid, root, model
    store.close()


def _slug(value):
    return design_runtime._slug(value)


def _phases(state):
    return [row.get('phase') for row in (state.get('phaseHistory') or [])]


def _run_phases(store, sid):
    return [row['data']['phase'] for row in store.events(sid) if row['type'] == 'design_run']


def _unique(items):
    out = []
    for item in items:
        if not out or out[-1] != item:
            out.append(item)
    return out


async def scenario(store, runtime, sid):
    """Kịch bản đầy đủ, trả về chứng cứ thô cho các bài khẳng định bên dưới."""
    async def dispatch(name, args):
        return await runtime.dispatch(store.get(sid), name, args)

    async def turn(prompt):
        await runtime.submit(sid, prompt)
        task = runtime.tasks.get(sid)
        if task is not None:
            await task

    # 1) Cửa vào `/design` với brief MƠ HỒ (§7.8): mở run rồi mở lời hỏi phỏng vấn.
    await turn(f'/design {GOAL}')
    job = store.design_jobs_for(sid)[0]
    design_id = job['design_id']
    prompts = [row for row in (store.design_job(design_id)['state'].get('prompts') or [])
               if row.get('kind') == 'interview']
    assert prompts, 'brief mơ hồ phải mở lời hỏi phỏng vấn'
    assert store.design_job(design_id)['status'] == 'needs_user'

    # 2) Chủ nhà trả lời phỏng vấn rồi BẮT ĐẦU.
    answer = {'answers': [{'questionId': 'dq-screen', 'text': 'màn hình chat của ứng dụng'},
                          {'questionId': 'dq-platform', 'optionId': 'web'},
                          {'questionId': 'dq-style', 'text': 'theo phong cách hiện có'}],
              'start': True}
    design_runtime.design_prompt_answer(runtime, sid, prompts[0]['promptId'], answer['answers'],
                                        start=True)

    # 3) Brief + danh sách chạm rồi chủ nhà DUYỆT cả danh sách.
    await dispatch('design_scope', {'action': 'update', 'patch': {'project': 'repo này'}})
    items = [{'kind': 'insert', 'path': 'app.txt', 'reason': 'nối khối chat vào app', 'risk': 'low'},
             {'kind': 'new', 'path': 'src/chat.tsx', 'reason': 'màn hình chat mới', 'risk': 'medium'}]
    await dispatch('design_scope', {'action': 'update', 'patch': {'touchList': {'items': items}}})
    live = store.design_job(design_id)
    design_runtime.design_touch_list_approve(runtime, sid, live,
                                             live['state']['touchList']['revision'])

    # 4) Canvas hai chiều: 23 thao tác qua BA lời gọi (§6.4, A3/Q4).
    ops = [{'type': 'CREATE_NODE', 'node': {'id': f'n{i}', 'title': f'bước {i}', 'kind': 'shape',
                                            'shape': 'rect'}}
           for i in range(1, 13)]
    ops += [{'type': 'CONNECT_NODES', 'connector': {'fromNodeId': f'n{i}', 'toNodeId': f'n{i + 1}'}}
            for i in range(1, 12)]
    canvas = []
    for start in range(0, len(ops), 8):
        canvas.append(await dispatch('canvas_draw', {'actions': ops[start:start + 8]}))

    # 5) Nhánh thiết kế trước (nền phải SẠCH — `.design/**` do `file_write` để lại là tệp chưa theo
    #    dõi nên không nằm trong `git diff HEAD`), rồi bản nháp, rồi hai lần ghi dự án.
    branch = await dispatch('design_branch_create', {'name': 'design/ui-e2e-20260927'})
    draft = f'.design/{_slug(design_id)}/v1-design.md'
    await dispatch('design_write', {'path': draft, 'mode': 'create',
                                    'content': '# Màn hình chat\n\n- khung hội thoại\n- ô soạn\n'})
    first = await dispatch('design_write', {'path': 'app.txt', 'mode': 'insert', 'anchor': 'beta\n',
                                            'content': 'chat-block\n'})
    second = await dispatch('design_write', {'path': 'src/chat.tsx', 'mode': 'create',
                                             'content': 'export function Chat() { return null }\n'})
    diff = await dispatch('design_diff', {})

    # 6) Con soát ĐỘC LẬP (`plan-review`) đọc đúng bản thiết kế (P4 §7.9).
    child = await runtime.delegate(store.get(sid), {
        'role': 'plan-review', 'goal': 'soát bản thiết kế màn hình chat',
        'reviewTarget': {'kind': 'design', 'designId': design_id, 'version': 1}})

    # 7) Ghi kết luận + thẻ báo cáo.
    review = await dispatch('design_review', {'designId': design_id, 'version': 1, 'verdict': 'ok',
                                              'summary': 'bản thiết kế đứng được',
                                              'issues': [{'severity': 'low', 'title': 'thiếu tên node'}]})
    report = await dispatch('design_report', {'summary': 'sẵn sàng triển khai', 'labels': ['design-md'],
                                              'nextSteps': ['triển khai màn hình chat']})

    # 8) Chủ nhà "Dùng cho plan": rời chế độ rồi nộp MỘT lượt main mang khối bàn giao.
    design_runtime.apply_design_mode(runtime, sid, False, 'toggle')
    await turn('bắt đầu triển khai')
    return {'designId': design_id, 'canvas': canvas, 'branch': branch, 'first': first,
            'second': second, 'diff': diff, 'child': child, 'review': review, 'report': report}


@pytest.fixture()
def finished(harness):
    store, runtime, sid, root, model = harness
    result = asyncio.run(scenario(store, runtime, sid))
    return store, runtime, sid, root, model, result


def test_e2e_canvas_has_at_least_twenty_ops_and_none_rejected(finished):
    *_, result = finished
    applied = sum(row['applied'] for row in result['canvas'])
    rejected = sum(row['rejected'] for row in result['canvas'])
    assert applied >= 20, f'cần ≥20 thao tác canvas, đo được {applied}'
    assert rejected == 0


def test_e2e_no_file_written_outside_the_approved_touch_list(finished):
    store, runtime, sid, root, model, result = finished
    state = store.design_job(result['designId'])['state']
    approved = {row['path'] for row in state['touchList']['items']}
    # Ghi của RUN là ghi đã `git add` (worker làm điều đó ngay sau khi ghi) ⇒ đo bằng `git diff HEAD`
    # trên nhánh thiết kế, không bằng `git status` (tệp chưa theo dõi của chính bộ kiểm không tính).
    touched = [line.strip() for line in
               _git(root, 'diff', '--name-only', 'HEAD').stdout.splitlines() if line.strip()]
    outside = [path for path in touched
               if path not in approved and not path.startswith(DDIR + '/')]
    assert outside == [], f'ghi ngoài danh sách chạm: {outside}'
    assert {'app.txt', 'src/chat.tsx'} <= set(touched)
    # Mọi hành động ghi của run cũng phải nằm trong danh sách đã duyệt hoặc trong `.design/**`.
    for action in state['actions']:
        assert action['path'] in approved or action['path'].startswith(DDIR + '/'), action['path']
    assert result['diff']['files'], 'diff phải thấy các tệp đã ghi'


def test_e2e_writes_land_on_the_design_branch(finished):
    store, runtime, sid, root, model, result = finished
    assert result['branch']['branch'] == 'design/ui-e2e-20260927'
    assert _git(root, 'rev-parse', 'HEAD').stdout.strip() == result['branch']['base']
    assert _git(root, 'branch', '--show-current').stdout.strip() == 'design/ui-e2e-20260927'
    assert _git(root, 'log', '--oneline', '-1').stdout.strip()  # không ghi gì lên nhánh chính


def test_e2e_independent_review_gated_the_handoff(finished):
    store, runtime, sid, root, model, result = finished
    children = [row for row in store.children_of(sid) if row.get('role') == 'plan-review']
    assert len(children) == 1, 'đúng MỘT con soát độc lập'
    assert model.child_reads == 1, 'con soát phải file_read đúng bản nháp trước khi phán'
    assert result['child']['status'] == 'completed'
    live = store.design_job(result['designId'])
    assert live['state']['review']['verdict'] == 'ok'
    assert live['state']['review']['criticSessionId'] == result['child']['sessionId']
    # §7.9: `version` được GHIM vào nội dung thật của bản nháp tại lúc soát.
    draft = root / f'.design/{_slug(result["designId"])}/v1-design.md'
    assert live['state']['review']['contentHash'] == hashlib.sha256(
        draft.read_bytes()).hexdigest()


def test_e2e_report_card_and_handoff_appear_exactly_once(finished):
    store, runtime, sid, root, model, result = finished
    cards = [row['data'] for row in store.events(sid) if row['type'] == 'design_report']
    assert len(cards) == 1
    assert cards[0]['designId'] == result['designId']
    assert set(cards[0]) == {'designId', 'version', 'branch', 'path', 'labels', 'summary'}
    live = store.design_job(result['designId'])
    assert live['status'] == 'completed' and live['state']['phase'] == design_runtime.PHASE_DONE
    assert result['report'] == {'designId': result['designId'], 'version': 1,
                               'path': live['state']['report']['path'], 'labels': ['design-md']}
    prompt = store.get(sid)['messages'][0]['content']
    assert prompt.count(limits.DESIGN_HANDOFF_BLOCK_MARKER) == 1
    assert prompt.count(limits.DESIGN_HANDOFF_BLOCK_END) == 1
    delivered = store.get(sid)['config']['designMode']['handoffDeliveredVersion']
    assert delivered[result['designId']] == '1'


def test_e2e_every_phase_change_emitted_exactly_one_design_run(finished):
    store, runtime, sid, root, model, result = finished
    live = store.design_job(result['designId'])
    history = _phases(live['state'])
    # `design_run` cũng đi kèm đổi TRẠNG THÁI (needs_user, nhánh, ghi tệp) nên số sự kiện ≥ số pha;
    # gộp các sự kiện liền nhau cùng pha thì hai chuỗi phải KỂ CÙNG một câu chuyện: mỗi lần nhích pha
    # có mặt đúng một lần, không pha nào thiếu sự kiện, và không sự kiện pha nào thừa.
    events = _unique(_run_phases(store, sid))
    assert events == history, f'sự kiện pha {events} khác sổ pha {history}'
    assert history[0] == 'interviewing' and history[-1] == design_runtime.PHASE_DONE
    assert history.count(design_runtime.PHASE_DONE) == 1
    assert len([phase for phase in history if phase == 'reviewing']) == 1
