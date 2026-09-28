"""Cổng NGUỒN (D-34): kế hoạch dựa vào dữ kiện ngoài phải có bằng chứng công cụ THẬT.

Chủ nhà chốt: *"bắt buộc khi kế hoạch dựa vào dữ kiện ngoài"*. Luật cũ chỉ đòi **có** mục
`Sources / Citations`; không ai kiểm nguồn đó có thật hay không, nên một kế hoạch viết "theo tài
liệu chính thức" mà chưa từng gọi công cụ nào vẫn được ghi (đo vòng 25). Cổng ở đây là lớp bằng
chứng: ba mã lỗi, ba cách hụt khác nhau —

* `sources-unproven` — chưa có phiên con `research`/`explore` nào: chưa ai đi tra;
* `sources-vague`    — có dòng nguồn nhưng không URL/`path:line`/lệnh cụ thể;
* `sources-unbacked` — host được viện dẫn nhưng không kết quả công cụ nào của cây phiên trả nó về.

Kế hoạch không viện dẫn dữ kiện ngoài thì cổng im lặng (cùng trigger với mục `sources` cũ).
Ba mức `BOXFOX_PLAN_SOURCES_GATE` = `enforce|warn|off`, đọc MỖI LƯỢT, giá trị lạ ⇒ `enforce` + nói ra.
"""
from __future__ import annotations

import asyncio
import copy
import json

from agentbox.agent_core import limits, runtime as runtime_module
from agentbox.agent_core.runtime import HarnessRuntime, tool_call_failed
from agentbox.memory.session_store import SessionStore
from agentbox.observability.system_log import SystemLog, read_entries

PLAIN_PLAN = """# Workspace plan

## Milestones
1. Build the workspace panel.

## Verification / Acceptance criteria
Run `pytest -q`; expect 3 passed.

## Risks / Limitations
- none known: the change is additive.
"""

SOURCED_PLAN = """# Plan backed by one source

## Milestones
1. Wire the retry helper.

## Verification / Acceptance criteria
Run `pytest -q`; expect 3 passed.

## Risks / Limitations
- none known: the change is additive.

## Sources / Citations
- https://docs.example.com/retry — the retry contract used by milestone 1.
"""

# Cùng hình dạng nhưng nguồn không có gì kiểm được: chỉ một câu chung chung.
VAGUE_PLAN = SOURCED_PLAN.replace(
    '- https://docs.example.com/retry — the retry contract used by milestone 1.',
    '- official documentation of the retry library').replace(
    '# Plan backed by one source', '# Plan that read the official docs')

# Host không ai trả về trong lượt này.
UNBACKED_PLAN = SOURCED_PLAN.replace('docs.example.com', 'blog.nowhere.example')


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


class PlanExecutor:
    """Sandbox giả: nói ra ĐÚNG thứ nó được gọi, để bài kiểm chứng minh được cả "không gọi"."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name == 'write_plan':
            version = args.get('version') or 1
            return {'content': 'Written ' + args['slug'], 'version': version, 'slug': args['slug'],
                    'relativePath': f".plans/v{version}-{args['slug']}.md", 'title': args.get('title') or '',
                    'bytes': len(args['markdown'].encode('utf-8'))}
        # `journal_append`/`checkpoint_write`: khuôn thật mà harness vẫn nhận.
        return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1,
                'relPath': '.session-history/journal.jsonl'}

    async def cleanup(self, sid):
        return None


def research_child(store, sid, output, *, role='research', status='completed', result=None):
    """Một phiên con THẬT trong cây, có một kết quả công cụ mang `output`."""
    child = store.create({'skills': []}, role=role, parent_id=sid)['id']
    store.child_start(child, sid, 1, 2, role, 'look up the retry contract')
    payload = {'id': 'c-call', 'name': 'web_search', 'args': {'query': 'retry contract'},
               'result': result if result is not None else {'content': output}}
    store.emit(child, 'tool_end', payload)
    store.child_finish(child, status, reason=None, steps_used=3, answer_chars=len(output))
    return child


def run_write(tmp_path, markdown, seed=None, step_response=None, timeout=10.0):
    """Một lượt thật: model gọi `write_plan`, rồi trả lời. Trả `(store, executor, sid)`.

    Lượt này cần BA câu trả lời từ 2026-09-27: bản kế hoạch ghi ra chưa có phán quyết phản biện nên
    F3 bơm thêm một bước nhắc. Thiếu câu thứ ba thì iterator cạn, lượt chết, mà phép kiểm dưới đây
    chỉ đọc mặt ghi nên vẫn xanh — vì thế `go()` chốt luôn trạng thái lượt.
    """
    async def go():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = PlanExecutor()
        model = FixtureModel([
            step_response or answer('Viết plan', calls=[call('write_plan', {
                'slug': 'Source Plan', 'markdown': markdown, 'title': ''})]),
            answer('Xong lượt.'),
            answer('Chưa chạy phản biện, dừng ở đây.')])
        runtime = HarnessRuntime(store, executor, model)
        sid = runtime.create({'skills': []})['id']
        if seed is not None:
            seed(store, sid)
        await asyncio.wait_for(runtime.start(sid, 'Lên kế hoạch'), timeout)
        assert store.get(sid)['status'] == 'completed', \
            'lượt ghi plan phải đóng trọn vẹn (fixture cạn câu trả lời ⇒ lượt chết âm thầm)'
        return store, executor, sid

    return asyncio.run(go())


def tool_end_result(store, sid):
    rows = [event['data']['result'] for event in store.events(sid) if event['type'] == 'tool_end']
    assert rows, 'lượt này phải có ít nhất một kết quả công cụ'
    return rows[0]


def events_of(store, sid, kind):
    return [event['data'] for event in store.events(sid) if event['type'] == kind]


def written(store, sid):
    return events_of(store, sid, 'plan_written')


SOURCE_NOTICE_CODES = ('PLAN_SOURCES_UNBACKED', limits.PLAN_SOURCES_MODE_UNKNOWN_CODE,
                       limits.PLAN_SOURCES_REJECTED_CODE)


def source_notices(store, sid):
    """Chỉ `notice` của cổng nguồn: `TURN_EXTENDED` cũng là notice và không thuộc bài này."""
    return [row for row in events_of(store, sid, 'notice') if row.get('code') in SOURCE_NOTICE_CODES]


def write_plan_calls(executor):
    return [args for name, args, _sid in executor.calls if name == 'write_plan']


def evaluation_rows(store):
    return store.db.execute('SELECT COUNT(*) AS n FROM plan_evaluations').fetchone()['n']


def test_a_plan_that_leans_on_outside_facts_without_a_child_is_refused(tmp_path):
    """Chưa ai đi tra: cổng từ chối TRƯỚC khi chạm đĩa, và nói rõ mã `sources-unproven`."""
    store, executor, sid = run_write(tmp_path, SOURCED_PLAN)

    result = tool_end_result(store, sid)
    assert result.get('is_error'), result
    assert result['errorCode'] == 'PLAN_QUALITY_REJECTED'
    assert '(sources-unproven)' in result['error']
    assert 'sources gate refused it' in result['error']
    assert write_plan_calls(executor) == [], 'cổng chặn trước khi sandbox ghi bất cứ thứ gì'
    assert written(store, sid) == []
    assert evaluation_rows(store) == 0, 'không có hàng chấm điểm cho một bản không được ghi'


def test_a_research_child_that_returned_the_host_lets_the_plan_through(tmp_path):
    """Có con `research` và kết quả công cụ THẬT mang host đó: kế hoạch được ghi như thường."""
    store, executor, sid = run_write(
        tmp_path, SOURCED_PLAN,
        seed=lambda s, sid: research_child(s, sid, 'fetched https://docs.example.com/retry page'))

    result = tool_end_result(store, sid)
    assert not result.get('is_error'), result
    assert len(write_plan_calls(executor)) == 1
    rows = written(store, sid)
    assert len(rows) == 1, rows
    assert rows[0]['identity'] and rows[0]['version'] == 1
    assert source_notices(store, sid) == []


# Host bắt đầu bằng `w` — đúng loại bị `lstrip('www.')` cắt cụt (H2).
W_HOST_PLAN = SOURCED_PLAN.replace('https://docs.example.com/retry', 'https://web.dev/retry')

# Bằng chứng mang tiền tố `www.`, kế hoạch viện dẫn host trần (và ngược lại ở ca dưới).
WWW_PLAN = SOURCED_PLAN


def test_a_cited_host_that_starts_with_w_is_not_cut_by_a_character_set_strip(tmp_path):
    """H2 (hậu kiểm): chuẩn hoá host là `startswith('www.')`, KHÔNG phải `lstrip('www.')`.

    `str.lstrip` cắt theo TẬP ký tự, nên bản đầu của cổng biến `web.dev` thành `eb.dev` (và `w3.org`
    thành `3.org`): một kế hoạch viện dẫn ĐÚNG cái host mà lời gọi công cụ vừa trả về vẫn bị
    `sources-unbacked` chặn — cổng từ chối một kế hoạch CÓ bằng chứng thật, và lượt không ghi được gì.
    """
    # Mức hàm thuần trước: đây là chỗ DUY NHẤT của cổng chuẩn hoá host hai lần, nên nó phải tự đứng
    # được một mình (không nhờ đường so khớp đường dẫn cứu).
    plan_quality = runtime_module.plan_quality
    assert plan_quality.cited_hosts(W_HOST_PLAN) == ['web.dev', 'docs.example.com'] or \
        'web.dev' in plan_quality.cited_hosts(W_HOST_PLAN)
    assert plan_quality.sources_issues(
        W_HOST_PLAN, children=[{'role': 'research', 'status': 'completed'}],
        hosts=['web.dev'], paths=[]) == [], 'host trần `web.dev` trong bằng chứng phải trả lời được dòng viện dẫn'
    assert plan_quality.sources_issues(
        W_HOST_PLAN, children=[{'role': 'research', 'status': 'completed'}],
        hosts=['www.web.dev'], paths=[]) == [], 'bằng chứng mang `www.` cũng phải trả lời được'

    # Rồi tới đường sống: kết quả công cụ trả host `web.dev` **không kèm đường dẫn** (không có gì để
    # đường so khớp đường dẫn cứu), kế hoạch phải được ghi.
    store, executor, sid = run_write(
        tmp_path, W_HOST_PLAN,
        seed=lambda s, sid: research_child(s, sid, 'request to https://web.dev returned 200'))

    result = tool_end_result(store, sid)
    assert not result.get('is_error'), result
    assert len(write_plan_calls(executor)) == 1
    assert len(written(store, sid)) == 1
    assert source_notices(store, sid) == []
    store.close()


def test_a_www_prefixed_evidence_host_backs_a_bare_citation(tmp_path):
    """Hai chỗ chuẩn hoá host phải nói CÙNG một chuyện: bằng chứng `www.docs.example.com` trả lời được
    cho dòng viện dẫn `docs.example.com` (trước hậu kiểm, hai chỗ dùng hai cách cắt khác nhau)."""
    store, _executor, sid = run_write(
        tmp_path, WWW_PLAN,
        seed=lambda s, sid: research_child(s, sid, 'fetched https://www.docs.example.com/retry page'))

    result = tool_end_result(store, sid)
    assert not result.get('is_error'), result
    assert len(written(store, sid)) == 1
    assert source_notices(store, sid) == []
    store.close()


def test_a_cited_host_that_no_tool_call_returned_is_refused(tmp_path):
    """Con đã chạy nhưng chưa từng trả host được viện dẫn: `sources-unbacked`, không ghi."""
    store, executor, sid = run_write(
        tmp_path, UNBACKED_PLAN,
        seed=lambda s, sid: research_child(s, sid, 'fetched https://docs.example.com/retry page'))

    result = tool_end_result(store, sid)
    assert result.get('is_error') and result['errorCode'] == 'PLAN_QUALITY_REJECTED'
    assert '(sources-unbacked)' in result['error']
    assert '(sources-unproven)' not in result['error'], 'con đã chạy thì không còn là "chưa ai tra"'
    assert written(store, sid) == []


def test_a_failed_tool_call_does_not_prove_a_source(tmp_path):
    """Lời gọi HỎNG không phải bằng chứng: `is_error` nằm trong `result`, không ở vỏ event."""
    failed = {'content': 'https://docs.example.com/retry (request timed out)', 'is_error': True}
    store, _executor, sid = run_write(
        tmp_path, SOURCED_PLAN,
        seed=lambda s, sid: research_child(s, sid, 'x', result=failed))

    result = tool_end_result(store, sid)
    assert result.get('is_error') and '(sources-unbacked)' in result['error'], result
    assert written(store, sid) == []
    # Cùng luật đó, kiểm ở mức hàm thuần: vỏ event thiếu cờ vẫn phải bị đọc là hỏng.
    assert tool_call_failed({'result': failed}) is True
    assert tool_call_failed({'result': {'content': 'ok'}}) is False


def test_a_sources_line_with_nothing_concrete_is_refused(tmp_path):
    """Có dòng nguồn nhưng không URL/`path:line`/lệnh: `sources-vague`."""
    store, _executor, sid = run_write(
        tmp_path, VAGUE_PLAN,
        seed=lambda s, sid: research_child(s, sid, 'fetched https://docs.example.com/retry page'))

    result = tool_end_result(store, sid)
    assert result.get('is_error') and result['errorCode'] == 'PLAN_QUALITY_REJECTED'
    assert '(sources-vague)' in result['error']
    assert written(store, sid) == []


def test_warn_mode_writes_the_plan_and_says_what_is_unbacked(tmp_path, monkeypatch):
    """`warn`: ghi được, nhưng phải để lại `notice` mang danh sách mã lỗi + dòng nhật ký hệ thống."""
    monkeypatch.setenv(limits.PLAN_SOURCES_ENV, 'warn')
    log = SystemLog(directory=tmp_path, source='harness', filename='harness.jsonl')
    monkeypatch.setattr(runtime_module, 'system_log', log)
    store, executor, sid = run_write(tmp_path, SOURCED_PLAN)

    result = tool_end_result(store, sid)
    assert not result.get('is_error'), result
    notices = source_notices(store, sid)
    assert [row['code'] for row in notices] == ['PLAN_SOURCES_UNBACKED'], notices
    assert notices[0]['issues'] == ['sources-unproven', 'sources-unbacked'], notices
    assert notices[0]['mode'] == 'warn'
    assert len(write_plan_calls(executor)) == 1
    rows = log.read() or read_entries([log.previous_path()])
    marked = [row for row in rows if row.get('code') == limits.PLAN_SOURCES_REJECTED_CODE]
    assert len(marked) == 1 and marked[0]['level'] == 'warn', rows
    assert marked[0]['data']['issues'] == ['sources-unproven', 'sources-unbacked'], marked


def test_off_mode_does_not_check_at_all(tmp_path, monkeypatch):
    """`off` — công tắc hạ xuống: không đo, không `notice`, kế hoạch ghi như trước vòng 25."""
    monkeypatch.setenv(limits.PLAN_SOURCES_ENV, 'off')
    store, executor, sid = run_write(tmp_path, SOURCED_PLAN)

    result = tool_end_result(store, sid)
    assert not result.get('is_error'), result
    assert source_notices(store, sid) == []
    assert len(write_plan_calls(executor)) == 1 and written(store, sid)


def test_a_plan_without_outside_facts_is_not_gated(tmp_path):
    """Cổng chỉ chạy khi kế hoạch viện dẫn dữ kiện ngoài — cùng trigger với mục `sources` cũ."""
    store, executor, sid = run_write(tmp_path, PLAIN_PLAN)

    result = tool_end_result(store, sid)
    assert not result.get('is_error'), result
    assert source_notices(store, sid) == []
    assert len(write_plan_calls(executor)) == 1 and written(store, sid)


def test_an_unknown_sources_mode_falls_back_to_enforce_and_says_so(tmp_path, monkeypatch):
    """Giá trị lạ không được hạ cấp cổng trong im lặng: `enforce` + `notice` nói ra giá trị lạ."""
    monkeypatch.setenv(limits.PLAN_SOURCES_ENV, 'lỏng-lẻo')
    store, _executor, sid = run_write(tmp_path, SOURCED_PLAN)

    notices = source_notices(store, sid)
    assert [row['code'] for row in notices] == [limits.PLAN_SOURCES_MODE_UNKNOWN_CODE]
    assert notices[0]['value'] == 'lỏng-lẻo'
    result = tool_end_result(store, sid)
    assert result['errorCode'] == 'PLAN_QUALITY_REJECTED'
    assert written(store, sid) == []


def test_a_title_that_contains_the_word_source_does_not_shadow_the_section(tmp_path):
    """H1 có chữ "source" không được che mục nguồn thật ở dưới.

    Đo được khi viết bộ này: `_find` khớp tiêu đề ĐẦU TIÊN, nên một H1 "Plan backed by one source"
    (thân bài rỗng) che mất `## Sources / Citations` thật; cổng cũ báo "thiếu mục nguồn" trong khi
    mục đó có mặt, và model sửa mãi không qua. Ca này ghim bản sửa, ở cả hai tầng: hàm thuần và
    đường ghi thật.
    """
    from agentbox.agent_core import plan_quality

    assert SOURCED_PLAN.splitlines()[0] == '# Plan backed by one source'
    assert plan_quality.plan_quality_issues(SOURCED_PLAN) == []
    assert plan_quality.source_lines(SOURCED_PLAN) == [
        '- https://docs.example.com/retry — the retry contract used by milestone 1.']

    # Một tiêu đề TRỐNG khớp khoá vẫn không thắng một mục có thân bài ở dưới.
    shadowed = (PLAIN_PLAN.replace('# Workspace plan',
                                   '# Notes on citations — checked the official docs')
                + '\n## Sources / Citations\n- `pytest -q` in docs/plan.md\n')
    assert plan_quality.plan_quality_issues(shadowed) == []
    assert plan_quality.source_lines(shadowed) == ['- `pytest -q` in docs/plan.md']

    # Không có mục nguồn nào có thân bài thì vẫn là thiếu (không được nới luật).
    assert 'sources-section' in plan_quality.plan_quality_issues(
        '# Plan backed by one source — checked the official docs\n\n## Sources\n')

def test_a_host_the_model_named_only_in_its_own_call_args_is_not_evidence(tmp_path):
    """Host chỉ có trong ARGS của lời gọi do CHÍNH model viết ⇒ vẫn là `sources-unbacked`.

    Lỗ thật đo ở vòng kiểm thử độc lập (H7): `plan_sources_evidence` quét **cả** payload `tool_end`
    nên một host model tự đặt vào tham số của một lời gọi THÀNH CÔNG (kết quả không hề nhắc host)
    được tính là "công cụ đã trả về" — trái câu từ chối của cổng (*cite a host a real tool call
    returned*) và trái docstring của chính hàm. Bản vá: cổng chỉ đọc `result`.
    """
    def seed(store, sid):
        child = research_child(store, sid, 'looked at the retry contract, no link to print')
        # Lời gọi THÀNH CÔNG nhưng host nằm ở tham số; kết quả thì không có host nào.
        store.emit(child, 'tool_end', {
            'id': 'c-args', 'name': 'web_search',
            'args': {'query': 'https://blog.nowhere.example/retry contract'},
            'result': {'content': 'nothing about that host in the answer'}})

    store, _executor, sid = run_write(tmp_path, UNBACKED_PLAN, seed=seed)

    result = tool_end_result(store, sid)
    assert result.get('is_error') and result['errorCode'] == 'PLAN_QUALITY_REJECTED', result
    assert '(sources-unbacked)' in result['error']
    assert written(store, sid) == []
