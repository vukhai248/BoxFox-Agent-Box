"""W7.2 — per-action schema của `work_report` và thông điệp lỗi tự-chỉnh.

Bộ kiểm này chốt ba việc:
1. Sai hình dạng đối số phải nói ĐÚNG tên field, action và gợi ý sửa (không phải lỗi quyền).
2. `WORK_ARTIFACT_UNKNOWN` phải nói rõ "không phải ACL" để model không đọc nhầm thành bị chặn.
3. Envelope lỗi mang `received` (đã cắt) để model thấy chính đối số mình vừa gửi.
"""
import asyncio
import json

import pytest

from agentbox.agent_core import work_artifacts, work_checks, work_graph
from agentbox.agent_core.tool_arg_errors import ToolFieldError, received_args
from agentbox.agent_core.tool_contracts import reflection_hint
from agentbox.agent_core.work_feedback import FeedbackError, check_action_fields
from test_work_feedback_w7 import setup


QUESTIONS = [{'id': 'users', 'question': 'Who uses the output?', 'options': ['Doctors', 'Nurses']}]


def test_status_without_runid_names_field_and_hint():
    with pytest.raises(FeedbackError) as err:
        check_action_fields({'action': 'status'}, 'main')
    assert err.value.code == 'WORK_REPORT_FIELD_REQUIRED'
    assert err.value.status == 400
    assert err.value.details['field'] == 'runId'
    assert err.value.details['action'] == 'status'
    assert 'work_graph' in err.value.details['hint']
    assert 'runId' in str(err.value)


def test_checkpoint_with_questions_is_forbidden():
    with pytest.raises(FeedbackError) as err:
        check_action_fields({'action': 'checkpoint', 'checkpoint': 'x', 'questions': QUESTIONS}, 'child')
    assert err.value.code == 'WORK_REPORT_FIELD_FORBIDDEN'
    assert err.value.details['field'] == 'questions'
    assert 'needs_user' in err.value.details['hint']


def test_needs_user_requires_decision_keys(tmp_path):
    """`decisionKeys` không bắt buộc (mặc định lấy id câu hỏi), nhưng gửi sai thì phải báo đúng mã.

    Thiết kế §5 liệt kê `decisionKeys` như trường bắt buộc của `needs_user`; mã hiện tại suy ra
    mặc định từ id câu hỏi nên ở đây chốt phần kiểm giá trị: sai kiểu/độ dài → `WORK_DECISION_KEYS_INVALID`,
    không im lặng bỏ qua rồi mở card thiếu khoá quyết định.
    """
    assert check_action_fields({'action': 'needs_user', 'checkpoint': 'x', 'questions': QUESTIONS,
                                'decisionKeys': ['users']}, 'child') is None

    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        for bad in ('users', ['users', 'users'], ['1bad']):
            with pytest.raises(FeedbackError, match='WORK_DECISION_KEYS_INVALID'):
                await graph.feedback.report(store.get(cid), {'action': 'needs_user', 'checkpoint': 'Cần chốt phạm vi',
                    'questions': QUESTIONS, 'decisionKeys': bad, 'invocationId': 'k-' + str(bad)}, 'tool-k')
    asyncio.run(run_test())


def test_no_blind_request_alias_when_single_request_open():
    """`needs_user` đòi `checkpoint` thật; không có alias ngầm cho checkpoint đang mở."""
    with pytest.raises(FeedbackError) as err:
        check_action_fields({'action': 'needs_user', 'questions': QUESTIONS}, 'child')
    assert err.value.code == 'WORK_REPORT_FIELD_REQUIRED'
    assert err.value.details['field'] == 'checkpoint'


def test_main_cannot_resume_a_main_interview(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        card = graph.feedback.open_main_interview(store.get(sid), {'questions': QUESTIONS}, 'call-1', run['runId'])
        with pytest.raises(FeedbackError) as err:
            graph.feedback.main_action(store.get(sid), {'action': 'resume', 'requestId': card['workRequestId'],
                                                        'revision': 1})
        assert err.value.code == 'WORK_REPORT_ACTION'
        assert 'read' in str(err.value)
    asyncio.run(run_test())


def test_artifact_read_root_without_runid_is_run_required_not_unknown(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        service = work_artifacts.Artifacts(graph)
        with pytest.raises(ToolFieldError) as err:
            service.read(store.get(sid), {'artifactId': 'art-deadbeef'})
        assert err.value.code == 'WORK_ARTIFACT_RUN_REQUIRED'
        assert err.value.details['field'] == 'runId'
        assert 'not an access-control denial' in str(err.value)
        assert 'work_graph' in err.value.details['hint']
    asyncio.run(run_test())


def test_unknown_artifact_message_says_not_acl(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        service = work_artifacts.Artifacts(graph)
        with pytest.raises(ValueError, match='not an access-control denial') as err:
            service.get(run['runId'], 'art-deadbeef')
        assert str(err.value).startswith('WORK_ARTIFACT_UNKNOWN')
    asyncio.run(run_test())


def test_error_envelope_contains_received_args_truncated():
    args = {'action': 'status', 'note': 'x' * 900}
    with pytest.raises(FeedbackError) as err:
        check_action_fields(args, 'main')
    received = err.value.details['received']
    assert received.startswith('{') and received.endswith('…[truncated]')
    assert len(received) <= 520
    assert json.loads(received_args({'a': 1})) == {'a': 1}


def test_reflection_hint_tells_shape_errors_apart_from_permission():
    hint = reflection_hint('work_report', 'WORK_REPORT_FIELD_REQUIRED')
    assert 'argument-shape' in hint and 'permission denial' in hint
    unknown = reflection_hint('work_artifact_read', 'WORK_ARTIFACT_UNKNOWN')
    assert 'Not an access-control denial' in unknown
    revoked = reflection_hint('terminal_exec', 'WORK_CAPABILITY_REVOKED')
    assert 'removed this capability' in revoked


def test_tool_contract_description_lists_the_action_fields():
    from agentbox.agent_core.tool_contracts import SCHEMAS
    description = next(s['function']['description'] for s in SCHEMAS if s['function']['name'] == 'work_report')
    assert 'runId' in description and 'requestId' in description
    assert 'needs_user' in description and 'resume' in description
