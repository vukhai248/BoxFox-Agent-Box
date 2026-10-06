"""Cổng chất lượng research qua ĐƯỜNG THẬT của runtime (vòng 27 đợt 4, A5/B-3b).

Ba câu hỏi của chủ nhà ở đây là ba câu hỏi về đường đi, không phải về luật thuần:

* công tắc `BOXFOX_RESEARCH_GATE` đọc ở **thời điểm gọi**, và `runtime_info` nói ĐÚNG mức engine áp;
* `enforce` từ chối **trước khi chạm đĩa**, `warn` ghi rồi mới kể lỗi — thứ tự ba bước là hợp đồng;
* nhánh con mang vai `research` kết thúc lượt thì câu trả lời của nó được **chú thích** (không bị
  viết lại, không đổi `status`) khi nhánh đó không để lại dòng sổ nào.

Ba ca "phải qua" của plan (tệp chủ nhà tầng 0, luật tầng 1 một nguồn, hồ sơ paper) nằm ở
`test_research_quality.py`; ở đây là ba ca "phải bị từ chối" chạy qua `dossier_write`.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import research_header, research_quality, research_runtime
from agentbox.agent_core.limits import RESEARCH_GATE_ENV
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

EXCERPT = ('Người bệnh đúng tuyến được hưởng 80% chi phí khám chữa bệnh, hồ sơ chuyển tuyến gồm '
           'giấy chuyển tuyến và bản tóm tắt điều trị theo quy định. ') * 3
PAYLOAD = {'docNumber': '75/2023/NĐ-CP', 'effectiveDate': '2023-12-01', 'validity': 'in_force',
           'issuingBody': 'Chính phủ',
           'appliesTo': 'người bệnh có thẻ BHYT chuyển tuyến đúng tuyến'}
URL = 'https://vanban.chinhphu.vn/?docid=75-2023'

MARKDOWN = f"""# Câu hỏi
Mức hưởng khi chuyển tuyến đúng tuyến là bao nhiêu?

## Phát hiện
Người bệnh đúng tuyến hưởng 80% chi phí khám chữa bệnh [r1] ({URL}).

## Nguồn
- r1 — vanban.chinhphu.vn, tầng 1.

## Mâu thuẫn còn lại
Không thấy mâu thuẫn giữa các nguồn đã mở.

## Việc chưa làm
Chưa mở được bản tiếng Anh của văn bản.
"""


class FixtureExecutor:
    """Box giả: chỉ ghi lại lời gọi, để khẳng định `enforce` KHÔNG chạm đĩa."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'relativePath': args['path'], 'version': 1, 'bytes': len(args['markdown'].encode('utf-8')),
                'sha1': 'abc123', 'files': [args['path']]}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    """Model giả — lượt con research trả một câu trả lời đọc được, không gọi tool nào."""

    def __init__(self, answer=''):
        self.answer = answer
        self.calls = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls.append(messages)
        return {'choices': [{'message': {'content': self.answer or 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv(RESEARCH_GATE_ENV, raising=False)
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, FixtureModel())
    sid = runtime.create({'skills': []})['id']
    yield store, runtime, sid, store.get(sid), executor
    store.close()


# Bề mặt 7 (RESEARCH_GATEWAY) đã xoá: main KHÔNG còn đi được qua `dispatch` tới các công cụ
# research nội bộ (`RESEARCH_MAIN_READ_ONLY`), và không còn công tắc `BOXFOX_RESEARCH_GATEWAY`
# để tắt. Tệp này đo ENGINE (cổng chất lượng đọc ở thời điểm gọi), nên gọi thẳng hàm engine —
# cửa dispatch của main được ghim ở `test_research_gateway.py`.


def seed_row(runtime, session, **overrides):
    args = {'claim': 'quy định chuyển tuyến đúng tuyến', 'url': URL, 'excerpt': EXCERPT,
            'payload': PAYLOAD}
    args.update(overrides)
    return research_runtime.source_add(runtime, session, args)


def write(runtime, session, **overrides):
    args = {'researchId': 'chuyen-tuyen-2026', 'level': 2, 'profile': 'health',
            'markdown': MARKDOWN, 'title': 'Chuyển tuyến 2026'}
    args.update(overrides)
    return asyncio.run(research_runtime.dossier_write(runtime, session, args))


# --- 1. Công tắc đọc ở thời điểm gọi, và bảng Nút vặn nói đúng mức đó ------


def test_the_gate_reads_the_mode_missing_env_as_the_default(harness, monkeypatch):
    """Thiếu env ⇒ mức MẶC ĐỊNH của engine, và đó cũng là mức `dossier_write` áp."""
    store, runtime, sid, session, executor = harness
    assert research_quality.gate_mode()[0] == research_quality.RESEARCH_GATE_DEFAULT_MODE
    seed_row(runtime, session)
    answer = write(runtime, session)
    assert answer['gate']['mode'] == research_quality.RESEARCH_GATE_DEFAULT_MODE
    assert answer['gate']['ok'] is True


def test_the_gate_mode_is_readable_from_runtime_info(tmp_path, monkeypatch):
    """`gate.researchGate` là mức ĐANG ÁP, đọc lại mỗi lần gọi — khuôn `evidenceMode`."""
    monkeypatch.setenv(RESEARCH_GATE_ENV, 'warn')
    assert research_runtime.research_quality.gate_mode()[0] == 'warn'
    store = SessionStore(tmp_path / 'info.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    from agentbox.api.server import create_app
    from aiohttp import ClientSession
    from aiohttp.test_utils import TestServer

    async def run():
        async with TestServer(create_app(runtime)) as server:
            headers = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
            async with ClientSession(headers=headers) as http:
                async with http.get(str(server.make_url('/api/agent/runtime-info'))) as resp:
                    assert resp.status == 200
                    payload = await resp.json()
        return payload

    info = asyncio.run(run())
    assert info['limits']['gate']['researchGate']['mode'] == 'warn'
    assert info['limits']['gate']['researchTiers']['tiers']['1'] == 'primary-official'
    store.close()


def test_an_unknown_gate_value_keeps_the_default_and_says_so_once(harness, monkeypatch):
    """Giá trị lạ ⇒ mặc định `enforce`, một notice mã `RESEARCH_GATE_MODE_UNKNOWN`, không hạ cấp im lặng."""
    store, runtime, sid, session, executor = harness
    monkeypatch.setenv(RESEARCH_GATE_ENV, 'chặt-vừa-thôi')
    seed_row(runtime, session)
    with pytest.raises(ValueError) as exc:
        write(runtime, session, markdown='# Câu hỏi\nKhông nguồn.\n')
    assert research_quality.RESEARCH_QUALITY_PREFIX in str(exc.value)
    notices = [event['data'].get('code') for event in store.events(sid) if event['type'] == 'notice']
    assert research_quality.MODE_UNKNOWN_CODE in notices


# --- 2. Ba ca phải bị từ chối, và thứ tự ba bước ---------------------------


def test_a_dossier_with_claims_and_no_ledger_row_is_refused_before_the_disk(harness):
    store, runtime, sid, session, executor = harness
    with pytest.raises(ValueError, match='research-sources-missing'):
        write(runtime, session)
    assert executor.calls == [], 'cổng từ chối ⇒ KHÔNG có tệp nào được ghi'
    assert store.dossier_versions('chuyen-tuyen-2026') == []


def test_a_row_without_a_verbatim_excerpt_is_refused(harness):
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session, excerpt='quá ngắn')
    with pytest.raises(ValueError, match='research-excerpt-missing'):
        write(runtime, session)
    assert executor.calls == []


CLAIM = 'phí chuyển tuyến 2026 là 300.000 đồng'


def markdown_citing(url, claim=CLAIM):
    """Hồ sơ trỏ ĐÚNG URL đã có dòng sổ — nếu không, lỗi đầu tiên là `research-sources-unproven`."""
    return MARKDOWN.replace(URL, url).replace(
        'Người bệnh đúng tuyến hưởng 80% chi phí khám chữa bệnh',
        f'{claim}: người bệnh đúng tuyến hưởng 80% chi phí khám chữa bệnh')


def test_a_key_claim_published_at_two_hosts_of_one_story_is_refused(harness):
    """Hai host vẫn có thể là MỘT nguồn: hai báo đăng lại cùng bản tin ⇒ khẳng định chưa đủ hai nguồn.

    Chủ nhà đã khai `origin` (nguồn tin gốc) nên luật `research-origin-undeclared` không còn là lỗi
    duy nhất — thứ bị bắt ở đây là **số nguồn ĐỘC LẬP**: một đơn vị gốc, hai host.
    """
    store, runtime, sid, session, executor = harness
    first, second = 'https://vnexpress.net/a', 'https://baochinhphu.vn/b'
    seed_row(runtime, session, url=first, claim=CLAIM, excerpt=EXCERPT, origin='TTXVN')
    seed_row(runtime, session, url=second, claim=CLAIM, excerpt=EXCERPT)
    with pytest.raises(ValueError, match='research-claim-single-source'):
        write(runtime, session, markdown=markdown_citing(first))
    assert executor.calls == []


def test_a_tier_one_source_alone_is_enough_for_a_key_claim(harness):
    """Luật #5985/#5996: một nguồn **tầng 1** là đủ cho khẳng định then chốt — không đòi hai nguồn."""
    store, runtime, sid, session, executor = harness
    seed_row(runtime, session, url='https://moh.gov.vn/a', claim=CLAIM, excerpt=EXCERPT, origin='TTXVN')
    seed_row(runtime, session, url='https://dantri.com.vn/b', claim=CLAIM, excerpt=EXCERPT)
    answer = write(runtime, session, markdown=markdown_citing('https://moh.gov.vn/a'))
    assert 'research-claim-single-source' not in answer['gate']['issues']


def test_warn_writes_the_dossier_and_then_says_what_is_missing(harness, monkeypatch):
    """`warn`: cổng không giữ chỗ từ chối — hồ sơ được ghi, kèm notice và nhãn `warn` ở header."""
    store, runtime, sid, session, executor = harness
    monkeypatch.setenv(RESEARCH_GATE_ENV, 'warn')
    seed_row(runtime, session, excerpt='quá ngắn')
    answer = write(runtime, session)
    assert executor.calls[0][0] == 'dossier_write'
    assert answer['gate']['mode'] == 'warn' and answer['gate']['ok'] is False
    assert answer['gate']['issues'], 'warn vẫn phải kể từng mục còn thiếu'
    assert 'research-excerpt-missing' in answer['gate']['issues']
    assert store.dossier_versions('chuyen-tuyen-2026') == [1]
    notices = [event['data'].get('code') for event in store.events(sid) if event['type'] == 'notice']
    assert research_quality.NOTICE_CODE in notices


def test_off_writes_without_inspecting_and_the_header_never_says_clear(harness, monkeypatch):
    store, runtime, sid, session, executor = harness
    monkeypatch.setenv(RESEARCH_GATE_ENV, 'off')
    answer = write(runtime, session)
    assert answer['gate']['ok'] is True and answer['gate']['mode'] == 'off'
    written = executor.calls[-1][1]['markdown']
    parsed = research_header.parse_research_header(written)
    assert parsed.status == 'ok' and parsed.gate == 'unbacked', \
        'hồ sơ không ai chấm KHÔNG được mang nhãn `clear`'


# --- 3. Tầng con: chú thích, không viết lại, không đổi status -------------
#
# Ba ca dưới chạy qua ĐƯỜNG THẬT: `runtime.submit` một lượt cha, cha gọi `delegate_task(role='research')`,
# con chạy xong rồi lượt cha chốt. Chú thích phải nằm trên payload event `child` — nơi giao diện đọc.

CHILD_ANSWER = (f'# Câu hỏi\nPhí chuyển tuyến 2026 là bao nhiêu?\n\n## Phát hiện\n'
                f'Theo {URL} thì phí tăng 20%.\n\n## Nguồn\n- {URL}\n')


def answer_of(text='xong', calls=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def tool_call(name, args, cid='c1'):
    import json
    return {'id': cid, 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}


class ScriptedModel(FixtureModel):
    """Model giả có kịch bản: lượt cha, lượt con, lượt cha chốt."""

    def __init__(self, script):
        super().__init__('')
        self.script = list(script)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls.append(messages)
        item = self.script.pop(0) if self.script else self.answer or 'ok'
        return item


BRANCH_REQUEST = {'schema': 'boxfox-research-job/1', 'goal': 'Tra phí chuyển tuyến 2026.',
                  'decisionContext': 'Chốt chi phí trước khi tư vấn.', 'questions': ['Phí chuyển tuyến 2026?'],
                  'constraints': ['Không thí nghiệm mạng hoặc chi tiêu sống.'], 'inputRefs': [],
                  'desiredOutput': 'Bản tổng hợp có nguồn.', 'freshnessRequirement': 'as-of request',
                  'permissionEnvelopeRef': None, 'allocationRef': None, 'consentRef': None}


def run_research_child(tmp_path, worker_script):
    """Chạy MỘT nhánh `research` của lead đã admit rồi đọc event `child` ở phiên lead.

    Bề mặt 7 đã xoá nên main không còn `delegate_task role=research`; đường còn lại — và cũng là
    đường THẬT của sản phẩm — là worker của lead Research. Ở đây lead được admit bằng hook
    admission của fixture (không phải consent sống), rồi lượt của lead tự gọi `delegate_task`
    đúng như một lead thật; dòng sổ của nhánh do chính nhánh ghim qua `source_add`.
    """
    store = SessionStore(tmp_path / 'child.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), ScriptedModel(
        [DELEGATE_RESEARCH, *worker_script, answer_of('xong rồi')]))
    root = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash'})
    lead = {}

    async def run():
        receipt = await runtime.dispatch(root, 'research_job_submit',
                                         {'request': BRANCH_REQUEST, 'invocationId': 'branch-submit'})
        lead['session'] = store.get(receipt['ownerControllerId'])
        runtime.prepare_research_admission = None
        runtime.research_admission = lambda actor, req: actor['id'] == lead['session']['id']
        await runtime.dispatch(root, 'research_job_control', {
            'jobId': receipt['researchJobId'], 'expectedRevision': receipt['revision'],
            'invocationId': 'branch-resume', 'action': 'resume', 'reason': 'Fixture admission.'})
        await runtime.tasks[lead['session']['id']]

    asyncio.run(run())
    rows = [event['data'] for event in store.events(lead['session']['id']) if event['type'] == 'child']
    assert rows, 'lead phải nhận một event `child`'
    return store, lead['session'], rows[-1]


DELEGATE_RESEARCH = answer_of(calls=[tool_call('delegate_task', {
    'role': 'research', 'goal': 'tra phí chuyển tuyến 2026', 'questionId': 'q1', 'wait': True})])


def test_a_research_child_that_never_touched_the_ledger_is_annotated_on_its_answer(
        tmp_path, monkeypatch):
    """Nhánh `research` kết thúc mà không để lại dòng sổ ⇒ payload `child` mang `researchGate`."""
    monkeypatch.delenv(RESEARCH_GATE_ENV, raising=False)
    store, session, child = run_research_child(tmp_path, [answer_of(CHILD_ANSWER)])
    gate = child['researchGate']
    assert gate['mode'] == 'note' and gate['rows'] == 0
    assert 'research-lineage-missing' in gate['issues'], 'con không để lại dòng sổ nào'
    assert gate['notice'].startswith(research_quality.NOTICE_CODE)
    assert child['status'] == 'completed', 'chú thích KHÔNG đổi status'
    assert CHILD_ANSWER[:30] in child['summary'], 'câu trả lời của con KHÔNG bị viết lại (I2/D-18)'
    codes = [event['data'].get('code') for event in store.events(session['id'])
             if event['type'] == 'notice']
    assert research_runtime.RESEARCH_GATE_NOTE_CODE in codes, 'chú thích đi kèm một notice'
    store.close()


def test_a_url_the_branch_never_registered_is_reported_as_unproven(tmp_path, monkeypatch):
    """Nhánh CÓ dòng sổ nhưng câu trả lời trỏ một URL khác ⇒ `research-sources-unproven` cho URL ấy."""
    monkeypatch.delenv(RESEARCH_GATE_ENV, raising=False)
    store, session, child = run_research_child(tmp_path, [
        answer_of(calls=[tool_call('source_add', {'claim': 'phí chuyển tuyến 2026',
                                                  'url': 'https://vnexpress.net/khac',
                                                  'excerpt': EXCERPT})]),
        answer_of(CHILD_ANSWER)])
    gate = child['researchGate']
    assert gate['rows'] == 1, 'dòng sổ của nhánh khác URL trong câu trả lời'
    assert 'research-lineage-missing' not in gate['issues']
    assert 'research-sources-unproven' in gate['issues']
    assert any(item['detail'] == URL for item in gate['missing']), gate['missing']
    store.close()


def test_a_research_child_that_did_leave_a_row_keeps_its_row_out_of_the_notes(tmp_path, monkeypatch):
    """Con để lại dòng sổ ⇒ không còn `research-lineage-missing` cho URL ấy."""
    monkeypatch.delenv(RESEARCH_GATE_ENV, raising=False)
    store, session, child = run_research_child(tmp_path, [
        answer_of(calls=[tool_call('source_add', {'claim': 'phí chuyển tuyến 2026',
                                                  'url': URL, 'excerpt': EXCERPT})]),
        answer_of(CHILD_ANSWER)])
    gate = child['researchGate']
    assert gate['rows'] == 1, 'dòng sổ của con nằm ở phiên giữ brief'
    assert 'research-lineage-missing' not in gate['issues'], 'nhánh ĐÃ để lại dòng sổ'
    assert 'research-sources-unproven' not in gate['issues'], 'URL ấy đã có dòng sổ'
    store.close()
