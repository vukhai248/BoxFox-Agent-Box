"""F6 (đợt soát 2026-09-27) — mã câu hỏi phỏng vấn của chế độ design là CỐ ĐỊNH.

Vì sao có tệp này: `design_scope(action='ask')` để mô hình tự đặt mã câu hỏi, mã ấy đi thẳng vào
`design_prompt_new`, và `QUESTION_FIELD` không có mục nào cho nó — chủ nhà trả lời xong thì nội dung
bị bỏ IM LẶNG. Đo sống ngày 2026-09-27: prompt `dp-a83c6c653759` mang mã `['doi-tuong',
'cach-dang-nhap','dau-ra']`, một prompt khác mang mã `approve-touch`.

Cách sửa: từ chối ngay tại cửa (`design_prompt_new`), kèm đúng danh sách mã hợp lệ để mô hình gọi
lại — chối một lần còn hơn nhận rồi bỏ. `kind='out-of-scope'` KHÔNG bị luật này chạm: nó tự đặt mã
riêng của mình.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế lại màn hình chat')
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    yield store, runtime, sid, store.design_job(job['design_id'])
    store.close()


def scope(runtime, store, sid, args):
    async def dispatch():
        return await runtime.dispatch(store.get(sid), 'design_scope', args)

    return asyncio.run(dispatch())


def prompts(store, job, kind=None):
    live = store.design_job(job['design_id'])
    return [row for row in live['state']['prompts'] if kind is None or row['kind'] == kind]


def prompt_ids(store, job, kind=None):
    return [row['promptId'] for row in prompts(store, job, kind)]


def test_the_question_ids_are_the_fixed_set_of_the_contract():
    assert limits.DESIGN_INTERVIEW_IDS == ('dq-screen', 'dq-platform', 'dq-project', 'dq-scope',
                                          'dq-style', 'dq-entry', 'dq-constraints')
    assert limits.DESIGN_INTERVIEW_IDS_UNKNOWN_CODE == 'DESIGN_INTERVIEW_IDS_UNKNOWN'


def test_a_free_question_id_is_refused_with_the_list_of_valid_ones(harness):
    """Mã tự đặt (`approve-touch`) bị chối kèm lỗi CHỈ ĐƯỜNG: đúng danh sách mã dùng được."""
    store, runtime, sid, job = harness
    before = prompt_ids(store, job, 'interview')
    with pytest.raises(ValueError) as excinfo:
        scope(runtime, store, sid, {'action': 'ask', 'questions': [
            {'id': 'approve-touch', 'text': 'thẻ này có đúng không?', 'required': True}]})

    message = str(excinfo.value)
    assert message.startswith(limits.DESIGN_INTERVIEW_IDS_UNKNOWN_CODE)
    assert 'approve-touch' in message
    for valid in limits.DESIGN_INTERVIEW_IDS:
        assert valid in message, f'lỗi phải nói ra mã hợp lệ {valid}'
    assert prompt_ids(store, job, 'interview') == before, 'bị chối thì KHÔNG được mở lời hỏi nào'


def test_a_question_that_is_not_a_mapping_is_refused_instead_of_crashing(harness):
    """Mục không phải từ điển (`["màn hình nào?"]`) cũng là mã lạ: chối bằng lỗi chỉ đường.

    Đo được của bản trước: biểu thức lọc bỏ qua mục ấy rồi `.get` gọi trên `str` ⇒ `AttributeError`
    thay cho `DESIGN_INTERVIEW_IDS_UNKNOWN` — một lời gọi méo hình dạng làm lượt chết vì lỗi lạ.
    """
    store, runtime, sid, job = harness
    before = prompt_ids(store, job, 'interview')
    with pytest.raises(ValueError) as excinfo:
        scope(runtime, store, sid, {'action': 'ask', 'questions': ['màn hình nào?']})

    message = str(excinfo.value)
    assert message.startswith(limits.DESIGN_INTERVIEW_IDS_UNKNOWN_CODE), message
    assert prompt_ids(store, job, 'interview') == before


def test_one_free_id_in_a_batch_is_enough_to_refuse_the_whole_batch(harness):
    """Ba câu, một mã lạ: chối cả lô, vì một lời hỏi không ghi được câu trả lời là một lời hỏi hỏng."""
    store, runtime, sid, job = harness
    before = prompt_ids(store, job, 'interview')
    with pytest.raises(ValueError) as excinfo:
        scope(runtime, store, sid, {'action': 'ask', 'questions': [
            {'id': 'dq-screen', 'text': 'màn hình nào?', 'required': True},
            {'id': 'doi-tuong', 'text': 'cho ai dùng?', 'required': True},
            {'id': 'dq-style', 'text': 'phong cách nào?', 'required': True}]})

    message = str(excinfo.value)
    assert message.startswith(limits.DESIGN_INTERVIEW_IDS_UNKNOWN_CODE)
    assert 'doi-tuong' in message
    assert design_runtime.INTERVIEW_ID_LIST in message, 'lỗi phải kể ĐÚNG những mã dùng được'
    assert all(valid in message for valid in limits.DESIGN_INTERVIEW_IDS)
    assert prompt_ids(store, job, 'interview') == before


def test_the_fixed_ids_open_the_prompt_and_map_to_brief_fields(harness):
    """Đường LÀNH: mã hợp lệ mở lời hỏi, và mỗi mã vẫn ánh xạ được sang một trường của brief."""
    store, runtime, sid, job = harness
    result = scope(runtime, store, sid, {'action': 'ask', 'questions': [
        {'id': 'dq-screen', 'text': 'màn hình nào?', 'required': True},
        {'id': 'dq-entry', 'text': 'vào bằng cách nào?', 'required': True}]})

    opened = [row for row in prompts(store, job, 'interview')
              if row['promptId'] == result['promptId']]
    assert len(opened) == 1, 'lời hỏi vừa mở phải tìm được bằng promptId'
    assert [row['id'] for row in opened[0]['questions']] == ['dq-screen', 'dq-entry']
    for row in opened[0]['questions']:
        assert row['id'] in design_runtime.QUESTION_FIELD, \
            'mã hỏi được thì phải có trường brief để ghi câu trả lời vào'


def test_the_default_question_set_still_uses_the_fixed_ids(harness):
    """Không truyền `questions`: bộ mặc định vẫn là mã cố định (không tự đặt mã nào)."""
    store, runtime, sid, job = harness
    result = scope(runtime, store, sid, {'action': 'ask'})
    opened = [row for row in prompts(store, job, 'interview')
              if row['promptId'] == result['promptId']]
    assert opened and all(row['id'] in limits.DESIGN_INTERVIEW_IDS for row in opened[0]['questions'])


def test_an_out_of_scope_prompt_keeps_its_own_id(harness):
    """`kind='out-of-scope'` là đường riêng: mã của nó do chế độ đặt, luật mã phỏng vấn không chạm."""
    store, runtime, sid, job = harness
    result = scope(runtime, store, sid, {'action': 'ask', 'kind': 'out-of-scope',
                                         'questions': [{'id': 'out-of-scope', 'text': 'ngoài phạm vi?',
                                                        'required': True}]})
    opened = [row for row in prompts(store, job, 'out-of-scope')
              if row['promptId'] == result['promptId']]
    assert opened and [row['id'] for row in opened[0]['questions']] == ['out-of-scope']


def test_the_tool_contract_names_the_ids_it_accepts():
    """Mô tả công cụ phải nói ra danh sách mã: mô hình gọi đúng ngay từ lần đầu, không đoán."""
    from agentbox.agent_core import tool_contracts

    text = str(tool_contracts.SCHEMAS)
    assert 'dq-screen' in text and 'dq-constraints' in text
