"""P3 (§5.9/§8.2 M-12): kiểu việc của nhánh con và brief do RUNTIME dựng.

Hai điều được ghim ở đây:

* `taskKind` không phải một vai mới — nó là một trường của `delegate_task`, giá trị lạ bị TỪ CHỐI
  kèm mã `RESEARCH_TASK_KIND_INVALID` thay vì lặng lẽ thành `branch`.
* Yêu cầu của nhánh con do RUNTIME dựng từ `job.state.scope`: phần "đã xác nhận" chỉ nhận mục
  `status='confirmed'` VÀ `source.kind='user'`, mọi mục còn lại mang nhãn "GIẢ ĐỊNH (chưa xác
  nhận)". Khoá máy `brief_leaks_assumption` là thứ bài kiểm này dùng.
"""
import asyncio
import copy
import json

import pytest

from agentbox.agent_core import limits, research_review
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_contracts import SCHEMAS
from agentbox.memory.session_store import SessionStore

CONFIRMED_GOAL = 'Chọn công cụ thay thế cho hệ cũ trong quý này'
ASSUMED_PURPOSE = 'Giả định mục đích là giảm chi phí vận hành'


# --- hợp đồng lược đồ --------------------------------------------------------

def test_the_schema_offers_the_frozen_task_kind_enum_and_adds_no_required_field():
    schema = next(s for s in SCHEMAS if s['function']['name'] == 'delegate_task')['function']
    properties = schema['parameters']['properties']
    assert set(properties['taskKind']['enum']) == set(limits.RESEARCH_BRANCH_KINDS)
    assert properties['facetId']['type'] == 'string'
    assert schema['parameters']['required'] == ['role', 'goal'], \
        'lệnh gọi cũ `role`/`goal` phải đi nguyên: không trường mới nào được thành bắt buộc'


def test_the_branch_report_tool_is_advertised_with_its_own_shape():
    schemas = [s for s in SCHEMAS if s['function']['name'] == 'research_branch_report']
    assert len(schemas) == 1
    params = schemas[0]['function']['parameters']
    assert params['required'] == ['rows', 'claims']
    assert set(params['properties']['claims']['items']['required']) == {'text'}
    stance = params['properties']['claims']['items']['properties']['stanceOrigin']['enum']
    assert set(stance) == {'source-stated', 'agent-inference', 'agent-proposal'}


def test_the_issue_kind_vocabulary_and_the_dossier_report_field_are_frozen():
    verify = next(s for s in SCHEMAS if s['function']['name'] == 'research_verify')
    kinds = verify['function']['parameters']['properties']['issues']['items']['properties']['kind']
    assert set(kinds['enum']) == set(limits.RESEARCH_ISSUE_KINDS)
    assert 'kind' not in verify['function']['parameters']['properties']['issues']['items']['required'], \
        'kind là trường THÊM ĐƯỢC: phát hiện cũ không có nó vẫn hợp lệ'
    dossier = next(s for s in SCHEMAS if s['function']['name'] == 'dossier_write')
    assert dossier['function']['parameters']['properties']['report']['type'] == 'object'
    assert 'report' not in dossier['function']['parameters']['required']


# --- kiểu việc ---------------------------------------------------------------

def test_an_unknown_task_kind_is_refused_with_the_contract_code_and_a_missing_one_defaults():
    assert research_review.resolve_task_kind(None) == limits.RESEARCH_TASK_KIND_DEFAULT
    assert research_review.resolve_task_kind('') == limits.RESEARCH_TASK_KIND_DEFAULT
    for kind in limits.RESEARCH_BRANCH_KINDS:
        assert research_review.resolve_task_kind(kind) == kind
    with pytest.raises(ValueError) as caught:
        research_review.resolve_task_kind('review-everything')
    assert limits.RESEARCH_TASK_KIND_INVALID_CODE in str(caught.value)
    # Đường đọc THUẦN thì không ném, chỉ trả mặc định — dùng cho chỗ hiển thị.
    assert research_review.normalize_task_kind('review-everything') == limits.RESEARCH_TASK_KIND_DEFAULT


# --- brief dựng từ scope -----------------------------------------------------

def _scope():
    return {
        'goal': {'text': CONFIRMED_GOAL, 'status': 'confirmed', 'source': {'kind': 'user'}},
        'purpose': {'text': ASSUMED_PURPOSE, 'status': 'assumed', 'source': {'kind': 'agent'}},
        # Mô hình tự khai `confirmed` nhưng nguồn là agent ⇒ VẪN là giả định.
        'exclusions': [{'text': 'Bỏ phương án thuê ngoài', 'status': 'confirmed',
                        'source': {'kind': 'agent'}}],
        'timePolicy': {'velocity': 'fast', 'status': 'confirmed', 'source': {'kind': 'user'}},
        'questions': [{'id': 'q1', 'text': 'Công cụ nào rẻ hơn?', 'importance': 'high'}],
    }


def test_a_confirmed_item_is_user_sourced_and_everything_else_is_a_labelled_assumption():
    brief = research_review.build_child_brief(_scope(), question='So sánh ba phương án',
                                              task_kind='deep-read')
    assert CONFIRMED_GOAL in brief['confirmed']
    assert ASSUMED_PURPOSE in brief['assumed']
    assert 'Bỏ phương án thuê ngoài' in brief['assumed'], \
        'confirmed do agent tự khai không được thành yêu cầu đã xác nhận'
    assert brief['taskKind'] == 'deep-read'
    assert 'CÂU HỎI CỦA NHÁNH: So sánh ba phương án' in brief['text']
    assert research_review.brief_leaks_assumption(brief) == []


def test_the_machine_key_catches_an_assumption_written_as_a_confirmed_statement():
    brief = research_review.build_child_brief(_scope(), question='x', task_kind='branch')
    leaked = dict(brief)
    leaked['confirmed'] = list(brief['confirmed']) + [ASSUMED_PURPOSE]
    leaked['lines'] = list(brief['lines']) + [f'YÊU CẦU ĐÃ XÁC NHẬN: {ASSUMED_PURPOSE}']
    assert research_review.brief_leaks_assumption(leaked) == [ASSUMED_PURPOSE]
    # Bỏ nhãn khỏi dòng giả định cũng là rò rỉ.
    unlabelled = dict(brief, lines=[line for line in brief['lines']
                                    if research_review.ASSUMPTION_LABEL not in line]
                      + [ASSUMED_PURPOSE])
    assert ASSUMED_PURPOSE in research_review.brief_leaks_assumption(unlabelled)


def test_a_brief_with_no_confirmed_item_says_so_instead_of_inventing_one():
    brief = research_review.build_child_brief(
        {'goal': {'text': 'Mục tiêu chưa xác nhận', 'status': 'assumed'}}, question='x')
    assert brief['confirmed'] == []
    assert 'YÊU CẦU ĐÃ XÁC NHẬN' not in brief['text']
    assert research_review.brief_leaks_assumption(brief) == []


# --- tích hợp: runtime dựng brief, không để mô hình tự viết -------------------

def answer(text='child done', calls=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None,
                       on_content=None):
        self.requests.append(copy.deepcopy((messages, tools, route)))
        return next(self.responses)


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def _run_delegate(tmp_path, args, *, scope=None, questions=None):
    """Gọi thẳng `runtime.delegate` trên một việc v2 đã có thẻ phạm vi."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([answer('child final answer')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid = runtime.create({'skills': []})['id']
        session = store.get(sid)
        session['config']['research'] = {'researchId': 'seed-run', 'jobMode': 'v2', 'tier': 2}
        store.update_config(sid, session['config'])
        store.research_job_save('seed-run', sid,
                               {'budgetSeconds': 1800, 'tier': 2,
                                'scope': scope if scope is not None else _scope(),
                                'questions': questions if questions is not None else [
                                    {'id': 'q1', 'text': 'Công cụ nào rẻ hơn?',
                                     'importance': 'high', 'status': 'unexplored'}]},
                               status='researching')
        runtime.active_turn[sid] = 1
        session = store.get(sid)
        events = []
        try:
            result = await runtime.delegate(session, args)
        except ValueError as error:
            runtime.active_turn.pop(sid, None)
            children = store.children_of(sid)
            store.close()
            return {'error': str(error), 'children': children, 'prompt': ''}
        child_id = result.get('sessionId')
        child = store.get(child_id)
        prompt = [m['content'] for m in child['messages'] if m['role'] == 'user'][-1]
        events = [event['data'] for event in store.events(sid) if event['type'] == 'child']
        runtime.active_turn.pop(sid, None)
        store.close()
        return {'result': result, 'child': child, 'prompt': prompt, 'events': events}

    return asyncio.run(run())


def test_the_runtime_builds_the_child_brief_and_the_model_does_not_write_requirements(tmp_path):
    args = {'role': 'research', 'goal': 'So sánh ba phương án', 'questionId': 'q1',
            'taskKind': 'deep-read', 'facetId': 'f-cost',
            'context': 'Ghi chú của cha.', 'expect': 'Bảng ba cột.'}
    outcome = _run_delegate(tmp_path, args)
    prompt = outcome['prompt']
    assert CONFIRMED_GOAL in prompt, 'yêu cầu đã xác nhận phải tới con'
    assumptions = [line for line in prompt.splitlines()
                   if research_review.ASSUMPTION_LABEL in line]
    assert any(ASSUMED_PURPOSE in line for line in assumptions), \
        'giả định phải tới con KÈM nhãn'
    assert ASSUMED_PURPOSE not in prompt.replace(
        f'{research_review.ASSUMPTION_LABEL}: {ASSUMED_PURPOSE}', ''), \
        'giả định không được xuất hiện ở chỗ nào khác mà không có nhãn'
    assert outcome['child']['config']['taskKind'] == 'deep-read'
    assert outcome['child']['config']['facetId'] == 'f-cost'
    assert outcome['events'][0]['taskKind'] == 'deep-read'
    assert 'Ghi chú của cha.' in prompt and 'Bảng ba cột.' in prompt


def test_an_unknown_task_kind_refuses_before_a_child_session_is_created(tmp_path):
    outcome = _run_delegate(tmp_path, {'role': 'research', 'goal': 'x', 'questionId': 'q1',
                                       'taskKind': 'not-a-kind'})
    assert limits.RESEARCH_TASK_KIND_INVALID_CODE in outcome['error']
    assert outcome['children'] == [], 'không được có hàng `sessions` mồ côi cho một lệnh sai'


def test_without_a_task_kind_the_default_kind_is_recorded(tmp_path):
    outcome = _run_delegate(tmp_path, {'role': 'research', 'goal': 'So sánh', 'questionId': 'q1'})
    assert outcome['child']['config']['taskKind'] == limits.RESEARCH_TASK_KIND_DEFAULT


def test_the_branch_report_switch_off_gives_back_the_old_free_form_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.RESEARCH_BRANCH_REPORT_ENV, 'off')
    outcome = _run_delegate(tmp_path, {'role': 'research', 'goal': 'So sánh ba phương án',
                                       'questionId': 'q1'})
    prompt = outcome['prompt']
    assert 'YÊU CẦU ĐÃ XÁC NHẬN' not in prompt and research_review.ASSUMPTION_LABEL not in prompt
    assert 'So sánh ba phương án' in prompt


def test_the_fixture_harness_reaches_the_model_with_the_child_prompt(tmp_path):
    """Khoá đường ống: brief được dựng ở runtime, không phải do mô hình gõ vào `goal`."""
    outcome = _run_delegate(tmp_path, {'role': 'research', 'goal': 'So sánh ba phương án',
                                       'questionId': 'q1'})
    assert outcome['prompt'] not in (None, '')
    assert json.dumps(outcome['child']['config'], ensure_ascii=False)  # cấu hình ghi được
