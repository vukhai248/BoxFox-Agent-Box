"""Bản đồ bao phủ + bão hoà của P2 (plan v2 §5.5, hợp đồng P2 §7.3–§7.4).

Ba tính chất được ghim ở đây:

* **bão hoà là chuyện ĐO ĐƯỢC** — trạng thái facet đọc từ NHẬT KÝ TÌM (`search_store.search_log`),
  không phải từ việc quét từ khoá trong văn xuôi;
* **trạng thái do người quyết thì phép đo không ghi đè** — `blocked`/`out-of-scope` đứng yên;
* **cửa sổ thời gian do runtime cấp** — `surveyDate` không để mô hình tự đoán, `velocity` gõ sai thì
  giữ giá trị cũ + ghi chú, không ném (một lỗi gõ không được làm hỏng lượt ghi thẻ phạm vi).

Mọi ca chạy tất định: không mạng, không gọi mô hình thật.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import limits, research_evidence, research_facets, research_runtime, search_store
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

RUN = 'run-cov'


class FixtureExecutor:
    """Box giả — chỉ ghi lại lời gọi, không chạm đĩa."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args))
        return {'relativePath': args.get('path'), 'bytes': 0, 'sha1': 'x', 'files': []}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


def scope_job(store, sid, research_id=RUN, **state_overrides):
    """Một việc v2 đang ở pha làm việc — thẻ phạm vi có câu hỏi quan trọng."""
    state = {'origin': 'mode', 'phase': 'researching', 'budgetSeconds': 1800, 'tier': 2,
             'goal': 'Toàn cảnh X', 'questions': [{'id': 'q1', 'importance': 'high',
                                                   'status': 'researching', 'text': 'Độ chính xác?'}],
             'scope': {'revision': 1, 'questions': [{'id': 'q1', 'text': 'Độ chính xác?',
                                                     'importance': 'high', 'status': 'researching'}]}}
    state.update(state_overrides)
    return store.research_job_save(research_id, sid, state, status='researching')


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv(limits.RESEARCH_COVERAGE_ENV, raising=False)
    monkeypatch.delenv(limits.RESEARCH_TIME_POLICY_ENV, raising=False)
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    # Nhật ký tìm là ĐẦU VÀO của phép đo — bài kiểm ghim một kho riêng, không đụng máy chủ nhà.
    runtime.search_db_path = tmp_path / 'search.sqlite'
    sid = runtime.create({'skills': []})['id']
    scope_job(store, sid)
    yield store, runtime, sid
    store.close()


def log_row(runtime, facet_id, *, results=10, new_unique=None, relevant_new=None,
            created=1.0, research_id=RUN):
    """Ghi MỘT dòng nhật ký tìm ĐÚNG payload `search_pipeline.run_pipeline` gửi cho `log_search`.

    Chỉ `created` là do bài kiểm chèn thêm (kho tự điền khi thiếu) để thứ tự sóng tất định.
    """
    record = {'research_id': research_id, 'session_id': 'child-1', 'facet_id': facet_id,
              'query': 'truy vấn', 'variant_kind': 'query', 'engines': ['brave'],
              'results': results, 'new_unique': results if new_unique is None else new_unique,
              'latency_ms': 5, 'created': created}
    if relevant_new is not None:
        record['relevant_new'] = relevant_new
    search_store.connect(runtime.search_db_path).log_search(record)


def seed_facet(store, label, *, status='unexplored', seed='scope', note=''):
    facet = research_facets.new_facet(label, seed=seed, status=status, note=note)
    store.facet_save(RUN, facet)
    return facet['facetId']


# ------------------------------------------------------------------ bão hoà


def test_saturation_is_measured_from_the_search_log_not_from_the_prose(harness):
    store, runtime, sid = harness
    facet_id = seed_facet(store, 'Độ chính xác trên bộ chuẩn')
    log_row(runtime, facet_id, results=10, relevant_new=3, created=1.0)
    # Hai sóng cuối liên tiếp gần như không thêm gì mới ⇒ bão hoà (ngưỡng 0.10, hai sóng).
    log_row(runtime, facet_id, results=10, relevant_new=0, created=2.0)
    log_row(runtime, facet_id, results=10, relevant_new=0, created=3.0)
    coverage = research_runtime.coverage_refresh(runtime, RUN)
    measured = coverage['measured']['facets'][facet_id]
    assert measured == 'saturated'
    assert coverage['counts']['saturated'] == 1
    assert coverage['searchLogRows'] == 3
    stored = store.facet(RUN, facet_id)
    assert stored['status'] == 'saturated', 'phép đo được GHI LẠI, không chỉ nói suông'
    assert stored['lastNewRatio'] == 0.0


def test_a_facet_whose_last_waves_kept_finding_new_pages_is_only_searched(harness):
    store, runtime, sid = harness
    facet_id = seed_facet(store, 'Hướng còn mới')
    log_row(runtime, facet_id, results=10, relevant_new=5, created=1.0)
    log_row(runtime, facet_id, results=10, relevant_new=4, created=2.0)
    coverage = research_runtime.coverage_refresh(runtime, RUN)
    assert coverage['measured']['facets'][facet_id] == 'searched'
    assert coverage['counts']['searched'] == 1


def test_a_facet_that_keeps_yielding_from_the_real_log_payload_never_saturates(harness):
    """Đầu-cuối: bao phủ ghi từ payload THẬT của `search_pipeline` không bão hoà một facet còn đất."""
    store, runtime, sid = harness
    facet_id = seed_facet(store, 'Hướng còn nhiều đất')
    for created in (1.0, 2.0, 3.0):
        log_row(runtime, facet_id, results=10, new_unique=6, relevant_new=6, created=created)
    coverage = research_runtime.coverage_refresh(runtime, RUN)
    assert coverage['measured']['facets'][facet_id] == 'searched'
    assert coverage['counts']['saturated'] == 0
    stored = store.facet(RUN, facet_id)
    assert stored['status'] == 'searched'
    assert stored['lastNewRatio'] == 0.6


def test_a_genuinely_exhausted_facet_still_saturates_from_the_real_log_payload(harness):
    store, runtime, sid = harness
    facet_id = seed_facet(store, 'Hướng đã cạn')
    log_row(runtime, facet_id, results=10, new_unique=0, relevant_new=0, created=1.0)
    log_row(runtime, facet_id, results=10, new_unique=0, relevant_new=0, created=2.0)
    coverage = research_runtime.coverage_refresh(runtime, RUN)
    assert coverage['measured']['facets'][facet_id] == 'saturated'
    assert coverage['counts']['saturated'] == 1
    assert store.facet(RUN, facet_id)['status'] == 'saturated'


def test_the_measurement_never_overwrites_blocked_or_out_of_scope(harness):
    store, runtime, sid = harness
    blocked = seed_facet(store, 'Chặn vì tường phí', status='blocked', note='cần tài khoản')
    out = seed_facet(store, 'Ngoài phạm vi', status='out-of-scope')
    for facet_id in (blocked, out):
        log_row(runtime, facet_id, results=10, relevant_new=0, created=1.0)
        log_row(runtime, facet_id, results=10, relevant_new=0, created=2.0)
    research_runtime.coverage_refresh(runtime, RUN)
    assert store.facet(RUN, blocked)['status'] == 'blocked'
    assert store.facet(RUN, out)['status'] == 'out-of-scope'


def test_stop_checks_report_open_facets_and_high_questions_as_blockers(harness):
    store, runtime, sid = harness
    seed_facet(store, 'Hướng chưa chạm')
    stop = research_runtime.coverage_stop(runtime, RUN)
    codes = {item['code'] for item in stop['blockers']}
    assert stop['ready'] is False
    assert 'research-facet-open' in codes
    assert 'research-question-open' in codes, 'câu hỏi quan trọng chưa trả lời vẫn chặn kết luận'


def test_stop_checks_are_ready_once_every_facet_is_closed(harness):
    store, runtime, sid = harness
    seed_facet(store, 'Hướng đã xong', status='saturated')
    scope_job(store, sid, questions=[{'id': 'q1', 'importance': 'high', 'status': 'answered'}],
              scope={'revision': 1, 'questions': [{'id': 'q1', 'text': 'Độ chính xác?',
                                                   'importance': 'high', 'status': 'answered'}]})
    stop = research_runtime.coverage_stop(runtime, RUN)
    assert stop['ready'] is True and stop['blockers'] == []


# ------------------------------------------------------- dựng bản đồ ban đầu


def test_seed_facets_records_where_each_direction_came_from(harness):
    store, runtime, sid = harness
    seeded = research_runtime.seed_facets(
        runtime, RUN, {'questions': [{'id': 'q1', 'text': 'Độ chính xác?', 'importance': 'high'}]},
        survey=[{'title': 'Bản đồ tổng quan'}], citation_clusters=[{'label': 'Cụm trích dẫn A'}])
    assert seeded == 3
    by_seed = {item['seedSource'] for item in store.facet_list(RUN)}
    assert by_seed == {'survey', 'scope', 'citation-cluster'}
    again = research_runtime.seed_facets(
        runtime, RUN, {'questions': [{'id': 'q1', 'text': 'Độ chính xác?', 'importance': 'high'}]},
        survey=[{'title': 'Bản đồ tổng quan'}], citation_clusters=[{'label': 'Cụm trích dẫn A'}])
    assert again == 3 and len(store.facet_list(RUN)) == 3, 'dựng lại không được nhân đôi hàng'


def test_the_scope_card_seeds_the_map_and_carries_the_runtime_survey_date(harness):
    store, runtime, sid = harness
    session = store.get(sid)
    answer = asyncio.run(runtime.dispatch(session, 'research_scope', {
        'action': 'propose', 'researchId': RUN,
        'patch': {'questions': [{'id': 'q1', 'text': 'Độ chính xác?', 'importance': 'high'}]},
        'survey': [{'title': 'Bản đồ tổng quan'}], 'citationClusters': ['Cụm trích dẫn A']}))
    assert answer['facetsSeeded'] == 3
    assert answer['coverage']['counts']['total'] == 3
    assert len(answer['scope']['surveyDate']) == 10, 'mốc khảo sát do runtime cấp (YYYY-MM-DD)'
    assert answer['scope']['window']['days'] == 0, 'chưa khai velocity ⇒ chưa có cửa sổ'


def test_the_time_policy_takes_the_velocity_and_derives_the_window(harness):
    store, runtime, sid = harness
    session = store.get(sid)
    answer = asyncio.run(runtime.dispatch(session, 'research_scope', {
        'action': 'update', 'researchId': RUN,
        'patch': {'timePolicy': {'velocity': 'fast', 'reason': 'thị trường đổi nhanh'}}}))
    scope = answer['scope']
    assert scope['timePolicy']['velocity'] == 'fast'
    assert scope['window']['days'] == research_evidence.VELOCITY_WINDOW_DAYS['fast']
    assert scope['window']['start'] < scope['window']['end']
    assert scope['timePolicy']['status'] == 'assumed', 'agent đề xuất ⇒ giả định, không phải xác nhận'
    assert scope['timePolicy']['reason'] == 'thị trường đổi nhanh'


def test_a_misspelled_velocity_keeps_the_old_value_and_notes_it(harness):
    store, runtime, sid = harness
    session = store.get(sid)
    asyncio.run(runtime.dispatch(session, 'research_scope', {
        'action': 'update', 'researchId': RUN, 'patch': {'timePolicy': {'velocity': 'fast'}}}))
    answer = asyncio.run(runtime.dispatch(session, 'research_scope', {
        'action': 'update', 'researchId': RUN, 'patch': {'timePolicy': {'velocity': 'nhanh-lam'}}}))
    policy = answer['scope']['timePolicy']
    assert policy['velocity'] == 'fast', 'giá trị sai KHÔNG được xoá giá trị đúng đang có'
    assert 'nhanh-lam' in policy['note']
    assert answer['scope']['window']['days'] == research_evidence.VELOCITY_WINDOW_DAYS['fast'], \
        'cửa sổ giữ nguyên theo velocity cũ'


# ------------------------------------------------------------ mặt đọc ra ngoài


def test_research_status_publishes_the_coverage_block(harness):
    store, runtime, sid = harness
    facet_id = seed_facet(store, 'Độ chính xác trên bộ chuẩn')
    log_row(runtime, facet_id, results=10, relevant_new=0, created=1.0)
    log_row(runtime, facet_id, results=10, relevant_new=0, created=2.0)
    answer = research_runtime.research_status(runtime, store.get(sid), {'researchId': RUN})
    assert answer['coverage']['counts']['saturated'] == 1
    assert answer['stop']['ready'] is False, 'còn câu hỏi quan trọng chưa xong'
    assert facet_id in answer['coverage']['measured']['facets']


def test_the_coverage_switch_off_returns_nothing(harness, monkeypatch):
    store, runtime, sid = harness
    seed_facet(store, 'Hướng chưa chạm')
    monkeypatch.setenv(limits.RESEARCH_COVERAGE_ENV, 'off')
    assert research_runtime.coverage_refresh(runtime, RUN) == {}
    answer = research_runtime.research_status(runtime, store.get(sid), {'researchId': RUN})
    assert 'coverage' not in answer and 'stop' not in answer
