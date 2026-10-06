"""`source_add` / `source_list` — luật của ENGINE (vòng 27 đợt 3, B-1).

Dòng sổ là thứ biến một câu trả lời thành thứ kiểm được: URL thật, đoạn trích NGUYÊN VĂN, tầng
nguồn, ngày lấy. Ca kiểm ghim bốn chuyện dễ hỏng: mã dòng do harness cấp (`r1`, `r2`), ghi lặp là
idempotent (một khẳng định KHÔNG được thành hai dòng), tầng/host do `source_tiers` quyết chứ không
phải do model khai, và `source_list` trả số nguồn ĐỘC LẬP chứ không phải số URL.
"""
from __future__ import annotations

import pytest

from agentbox.agent_core import limits, research_quality, research_runtime
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


LONG = ('Hồ sơ chuyển tuyến bảo hiểm y tế gồm bốn loại giấy tờ theo quy định hiện hành, '
        'kèm mức hưởng và tuyến chuyên môn. ') * 2
#: Một bản tin KHÁC HẲN — dùng để phân biệt "hai nguồn độc lập" với "một bản tin đăng lại".
OTHER = ('Mức thu phí khám chữa bệnh tại bệnh viện công lập được điều chỉnh theo từng tuyến, '
         'người bệnh đúng tuyến trả phần nhỏ hơn. ') * 2


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'content': 'ok'}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    yield store, runtime, sid, store.get(sid)
    store.close()


def add(runtime, session, **args):
    """Gọi THẲNG engine `source_add`: biên dispatch của main đã bị Research gateway đóng
    (`RESEARCH_MAIN_READ_ONLY`) — biên ấy được ghim ở `tests/unit/test_research_gateway.py`.
    """
    payload = {'claim': 'mức hưởng khi chuyển tuyến đúng tuyến',
               'url': 'https://vanban.chinhphu.vn/?pageid=27160&docid=1', 'excerpt': LONG}
    payload.update(args)
    return research_runtime.source_add(runtime, session, payload)


def test_a_source_row_gets_a_harness_row_id_and_a_tier_from_the_host(harness):
    store, runtime, sid, session = harness
    first = add(runtime, session)
    assert first['rowId'] == 'r1'
    assert (first['tier'], first['host']) == (1, 'vanban.chinhphu.vn')
    assert first['counts']['rows'] == 1
    second = add(runtime, session, url='https://nhandan.vn/bai-viet-1.html',
                 claim='báo nói mức hưởng thay đổi từ 2026')
    assert second['rowId'] == 'r2'
    assert second['tier'] == 2
    assert second['note'], 'nguồn không phải tầng 0–1 thì phải có câu nhắc'


def test_a_second_write_of_the_same_claim_is_idempotent(harness):
    store, runtime, sid, session = harness
    first = add(runtime, session)
    again = add(runtime, session, rowId=first['rowId'])
    assert again['rowId'] == first['rowId']
    assert store.source_count(sid) == 1, 'hai lời gọi cùng một dòng sổ ⇒ vẫn một hàng'


def test_a_row_needs_claim_url_and_a_verbatim_excerpt(harness):
    store, runtime, sid, session = harness
    with pytest.raises(ValueError, match='SOURCE_INVALID'):
        research_runtime.source_add(runtime, session, {'claim': '', 'url': 'https://a.vn',
                                                       'excerpt': LONG})
    with pytest.raises(ValueError, match='SOURCE_INVALID'):
        research_runtime.source_add(runtime, session, {'claim': 'x', 'url': '', 'excerpt': LONG})
    with pytest.raises(ValueError, match='SOURCE_INVALID'):
        research_runtime.source_add(runtime, session, {'claim': 'x', 'url': 'https://moh.gov.vn/a',
                                                       'excerpt': '  '})
    assert store.source_count(sid) == 0, 'lời gọi hỏng không để lại hàng rác'


def test_a_short_excerpt_is_accepted_but_the_answer_warns(harness):
    store, runtime, sid, session = harness
    answer = research_runtime.source_add(runtime, session,
                                         {'claim': 'x', 'url': 'https://moh.gov.vn/a',
                                          'excerpt': 'quá ngắn'})
    assert answer['warning']
    assert str(limits.RESEARCH_MIN_EXCERPT_CHARS) in answer['warning']
    stored = store.source_row(sid, answer['rowId'])
    assert stored['fingerprint'] == '', 'đoạn trích dưới sàn vân tay ⇒ không sinh vân tay giả'


def test_the_list_returns_independent_sources_not_urls(harness):
    store, runtime, sid, session = harness
    add(runtime, session, url='https://vanban.chinhphu.vn/a.html', excerpt=LONG)       # tầng 1
    add(runtime, session, url='https://nhandan.vn/a.html', excerpt=OTHER)             # tầng 2
    listed = research_runtime.source_list(runtime, session, {})
    assert listed['counts']['total'] == 2
    assert listed['counts']['byTier'] == {'1': 1, '2': 1}
    assert listed['counts']['independent'] == 2
    # Cùng bản tin (cùng đoạn trích) ở báo thứ hai ⇒ ba dòng, vẫn HAI nguồn độc lập.
    add(runtime, session, url='https://tuoitre.vn/a.html', excerpt=OTHER)
    merged = research_runtime.source_list(runtime, session, {})
    assert merged['counts']['total'] == 3
    assert merged['counts']['byTier'] == {'1': 1, '2': 2}
    assert merged['counts']['independent'] == 2
    assert [row['rowId'] for row in listed['rows']] == ['r2', 'r1'], 'mới nhất lên trước'
    assert listed['window']['limit'] == limits.SOURCE_ROW_LIMIT_DEFAULT
    trimmed = research_runtime.source_list(runtime, session, {'limit': 1, 'tier': 2})
    assert [row['rowId'] for row in trimmed['rows']] == ['r3']
    assert trimmed['counts']['total'] == 3, 'cắt cửa sổ KHÔNG đổi tổng số dòng'
    assert trimmed['counts']['independent'] == 2, 'và không đổi số nguồn độc lập'


def test_a_child_row_records_which_branch_read_it(harness):
    store, runtime, sid, session = harness
    child = runtime.create({'skills': []}, parent_id=sid, role='research')
    research_runtime.source_add(runtime, store.get(child['id']),
                                {'claim': 'x', 'url': 'https://moh.gov.vn/a', 'excerpt': LONG})
    assert store.source_counts_by_child(sid).get(child['id']) == 1
    listed = research_runtime.source_list(runtime, session, {'childId': child['id']})
    assert listed['counts']['byChild'][child['id']] == 1


def test_a_second_branch_that_reuses_the_row_gets_its_own_credit_and_its_fields_kept(harness):
    """Nhánh B mở CÙNG nguồn với đoạn trích y hệt nhánh A: dùng lại dòng, nhưng không mất gì.

    Đo được trước khi vá: `source_add` trả `reused` rồi **nuốt** `payload` của lời gọi thứ hai (trường
    hồ sơ hard gửi lên biến mất) và giữ `child_id` của nhánh A, nên nhánh B bị chấm
    `research-lineage-missing` mà không có cách nào gỡ — cổng chất lượng từ chối hồ sơ vì lỗi của
    chính harness.
    """
    store, runtime, sid, session = harness
    first = add(runtime, session)                                  # nhánh đầu: chính main
    row_id = first['rowId']
    assert store.source_count(sid) == 1
    a = runtime.create({'skills': [], 'tools': ['source_add']}, parent_id=sid, role='research')
    b = runtime.create({'skills': [], 'tools': ['source_add']}, parent_id=sid, role='research')
    branch_b = store.get(b['id'])
    again = research_runtime.source_add(runtime, branch_b, {
        'claim': 'mức hưởng chuyển tuyến', 'url': 'https://vanban.chinhphu.vn/?pageid=27160&docid=1',
        'excerpt': LONG, 'payload': {'docNumber': '15/2026/TT-BYT', 'effectiveDate': '2026-07-01'}})
    assert again['rowId'] == row_id and again['reused'] is True
    assert store.source_count(sid) == 1, 'một nguồn, một dòng'
    assert again['branchLinked'] is True
    assert sorted(again['payloadMerged']) == ['docNumber', 'effectiveDate'], 'trường gửi lên không bị nuốt'
    row = store.source_row(sid, row_id)
    assert row['payload'] == {'docNumber': '15/2026/TT-BYT', 'effectiveDate': '2026-07-01'}
    assert row['branches'] == [str(b['id'])]
    # Nhánh B đếm được là nhánh ĐÃ để lại dòng, và cổng chất lượng không còn oan cho nó.
    assert store.source_counts_by_child(sid).get(str(b['id'])) is None, 'cột child_id vẫn của nhánh đầu'
    demo = research_quality.annotate_child_answer('Kết luận [r1] theo https://vanban.chinhphu.vn/x.',
                                                 rows=[research_runtime._row_of(row)], child_id=str(b['id']))
    assert 'research-lineage-missing' not in demo['issues']
    # Nhánh A vẫn giữ dòng của chính nó (không bị nhánh B lấy mất).
    assert [item['rowId'] for item in store.source_rows_for(sid, [str(b['id'])])] == [row_id]


def test_a_field_with_a_different_value_keeps_the_old_one_and_says_so(harness):
    store, runtime, sid, session = harness
    add(runtime, session, payload={'docNumber': '15/2026/TT-BYT'})
    child = store.get(runtime.create({'skills': [], 'tools': ['source_add']}, parent_id=sid,
                                     role='research')['id'])
    again = research_runtime.source_add(runtime, child, {
        'claim': 'mức hưởng chuyển tuyến', 'url': 'https://vanban.chinhphu.vn/?pageid=27160&docid=1',
        'excerpt': LONG, 'payload': {'docNumber': '99/2026/TT-BYT'}})
    assert again['payloadKept'] == ['docNumber'] and 'giữ giá trị CŨ' in again['note']
    assert store.source_row(sid, again['rowId'])['payload'] == {'docNumber': '15/2026/TT-BYT'}
