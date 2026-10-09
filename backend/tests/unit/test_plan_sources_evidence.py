"""F05 — lượt chạy sống 2026-10-09: bằng chứng nguồn không được là MỘT TRANG của bảng `events`.

Cổng nguồn của `write_plan` thu host/đường dẫn từ `tool_end` của cây phiên. Nó đọc
`store.events(pid)` — mà `events()` cắt ở `EVENTS_PAGE` (500) hàng và trả về trang CŨ NHẤT.
Trên phiên của lượt chạy sống (16 186 hàng), 500 hàng đầu không có một `tool_end` nào, nên
mọi host mà kế hoạch viện dẫn đều bị coi là không bằng chứng: `write_plan` trả
`PLAN_QUALITY_REJECTED … (sources-unbacked)`, và lời khuyên "cite a host a real tool call
returned" là bất khả thi — kế hoạch không thể ghi trong bất kỳ phiên dài nào.
"""
import pytest

from agentbox.agent_core import plan_quality
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

pytestmark = pytest.mark.legacy_path

PLAN = """# Kế hoạch QC Copilot

## Nghiệm thu
- Chạy `pytest -q` và thấy 12 passed.

## Rủi ro
- Ghi đè hồ sơ lô; giới hạn ở quyền đọc.

## Nguồn / Trích dẫn
- 21 CFR Part 11 — https://ecfr.gov/current/title-21/part-11
"""


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed'}

    async def cleanup(self, sid):
        return None


def build(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), None)
    session = runtime.create({'skills': []})
    return store, runtime, session['id']


def test_a_tool_result_after_the_first_page_is_still_evidence(tmp_path):
    store, runtime, sid = build(tmp_path)
    for _ in range(600):
        store.emit(sid, 'thought', {'text': 'x'})
    store.emit(sid, 'tool_end', {'id': 'c1', 'name': 'web_fetch', 'args': {'url': 'https://ecfr.gov/x'},
                                 'result': {'content': '21 CFR Part 11 — https://ecfr.gov/current/title-21'}})
    assert len(store.events(sid)) == SessionStore.EVENTS_PAGE, 'trang đầu vẫn bị cắt ở 500 hàng'

    evidence = runtime.plan_sources_evidence(sid)
    assert 'ecfr.gov' in evidence['hosts'], 'kết quả công cụ nằm ngoài trang đầu vẫn là bằng chứng'
    issues = plan_quality.sources_issues(PLAN, **evidence)
    assert 'sources-unbacked' not in issues, 'host có bằng chứng công cụ thật thì không bị chặn'
    store.close()


def test_a_failed_call_never_becomes_evidence(tmp_path):
    store, runtime, sid = build(tmp_path)
    store.emit(sid, 'tool_end', {'id': 'c2', 'name': 'web_fetch', 'args': {},
                                 'result': {'is_error': True, 'error': 'https://example.com/x'}})
    evidence = runtime.plan_sources_evidence(sid)
    assert 'example.com' not in evidence['hosts']
    assert 'sources-unbacked' in plan_quality.sources_issues(PLAN, **evidence), \
        'kế hoạch viện dẫn host không có bằng chứng thì vẫn bị chặn'
    store.close()


def test_tool_results_returns_every_row_in_order(tmp_path):
    store, runtime, sid = build(tmp_path)
    for index in range(3):
        store.emit(sid, 'tool_end', {'id': 'c%d' % index, 'name': 'web_search', 'args': {},
                                     'result': {'content': 'https://host%d.example/x' % index}})
    rows = store.tool_results(sid)
    assert [row['data']['id'] for row in rows] == ['c0', 'c1', 'c2']
    assert all(row['type'] == 'tool_end' for row in rows)
    store.close()
