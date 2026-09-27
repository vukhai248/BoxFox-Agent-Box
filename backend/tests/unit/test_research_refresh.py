"""Làm mới một run đã có hồ sơ (§5.8, use case H): `action='refresh'` + `changelog.md`.

Ba thứ phải đúng cùng lúc, nên ca kiểm đo cả ba trên CÙNG một cây thật (store SQLite thật, runtime
thật): (1) run mới là run KHÁC, kế thừa sổ nguồn ở trạng thái `unverified` và ghim `refreshOf` /
`refreshSince` / `supersedes`; (2) `changelog.md` so NGUỒN với run gốc và đếm đúng bốn nhóm
mới/đổi/rút/giữ nguyên; (3) bốn cửa từ chối (công tắc `off`, chưa có hồ sơ, run gốc đang chạy, đã có
run làm mới đang chạy) đều trả MÃ HỢP ĐỒNG, không im lặng hạ cấp.
"""
from __future__ import annotations

import asyncio

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import limits, research_report, research_runtime
from agentbox.api.server import create_app
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'content': 'ok'}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None,
                       on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    yield store, runtime, sid, store.get(sid)
    store.close()


def run(store, sid, research_id, *, status='completed', scope=None, extra=None):
    """Run đã chốt thẻ phạm vi (mốc khảo sát cũ) — đúng khuôn `research_brief` để lại."""
    state = {'goal': 'mục tiêu', 'phase': 'done', 'question': 'Câu hỏi gốc của run',
             'tier': 2, 'budgetSeconds': 1800,
             'scope': {'revision': 3, 'goal': {'text': 'mục tiêu', 'status': 'confirmed'},
                       'questions': [{'text': 'Câu hỏi 1', 'importance': 'high'}],
                       'exclude': [], 'openQuestions': [],
                       'timePolicy': {'velocity': 'norm', 'status': 'confirmed'},
                       'surveyDate': '2026-01-05'}}
    state['scope'].update(scope or {})
    state.update(extra or {})
    return store.research_job_save(research_id, sid, state, status=status)


def source(store, sid, url, claim, *, status='ok', excerpt='x' * 120, access='snippet',
           tier=2, research_id='RS1', inherited_from=''):
    payload = {'inherited': True, 'inheritedFrom': inherited_from} if inherited_from else {}
    added = store.source_add(sid, {'claim': claim, 'url': url, 'host': url.split('/')[2],
                                   'tier': tier, 'excerpt': excerpt, 'status': status,
                                   'access_level': access, 'research_id': research_id,
                                   'payload': payload})
    store.evidence_link(sid, added['rowId'], claim, access_level=access, research_id=research_id)
    return added


def dossier(store, sid, research_id, version=3):
    return store.record_dossier(sid, research_id, version, f'.research/rs1-20260105-0900/v{version}.md',
                                profile='mixed', level=2, rows=4)


# --- `changelog.md` so nguồn -------------------------------------------------

def _four_groups(store, runtime, sid):
    """Run gốc có 4 nguồn, run làm mới đổi 1, rút 2, thêm 1, giữ 1."""
    run(store, sid, 'RS1')
    source(store, sid, 'https://a.example/1', 'Nguồn đổi', excerpt='x' * 120)
    source(store, sid, 'https://b.example/2', 'Nguồn rút vì trạng thái', status='gone')
    source(store, sid, 'https://c.example/3', 'Nguồn rút vì vắng mặt')
    source(store, sid, 'https://e.example/5', 'Nguồn giữ nguyên')
    run(store, sid, 'RS2', status='researching',
        extra={'refreshOf': 'RS1', 'refreshSince': '2026-01-05', 'supersedes': 3})
    source(store, sid, 'https://a.example/1', 'Nguồn đổi', excerpt='y' * 300,
           access='fulltext-read', research_id='RS2')
    source(store, sid, 'https://b.example/2', 'Nguồn rút vì trạng thái', status='gone',
           research_id='RS2')
    source(store, sid, 'https://d.example/4', 'Nguồn mới', research_id='RS2')
    source(store, sid, 'https://e.example/5', 'Nguồn giữ nguyên', research_id='RS2')
    return research_runtime.refresh_changelog(runtime, sid, 'RS1', 'RS2', version=1)


def test_an_inherited_row_counts_as_kept_even_though_its_status_reset(harness):
    """Dòng chép từ run gốc CỐ Ý mang `unverified` — nhóm "đổi" nói về nguồn, không về cờ nội bộ."""
    store, runtime, sid, _session = harness
    run(store, sid, 'RS1')
    source(store, sid, 'https://a.example/1', 'Nguồn cũ')
    run(store, sid, 'RS2', status='researching', extra={'refreshOf': 'RS1'})
    source(store, sid, 'https://a.example/1', 'Nguồn cũ', status='unverified', research_id='RS2',
           inherited_from='RS1')
    body = research_runtime.refresh_changelog(runtime, sid, 'RS1', 'RS2')
    assert '## Nguồn giữ nguyên (1)' in body
    assert '## Nguồn đổi (0)' in body and '## Nguồn rút (0)' in body


def test_the_changelog_groups_sources_and_counts_them_exactly(harness):
    store, runtime, sid, _session = harness
    body = _four_groups(store, runtime, sid)
    assert '## Nguồn mới (1)' in body and 'https://d.example/4' in body
    assert '## Nguồn đổi (1)' in body and 'https://a.example/1' in body
    assert '## Nguồn rút (2)' in body
    assert 'https://b.example/2' in body and 'https://c.example/3' in body
    assert '## Nguồn giữ nguyên (1)' in body and 'https://e.example/5' in body
    # Dòng changelog phải nói được TẠI SAO nguồn đáng soi: mức truy cập và độ dài đoạn trích.
    assert '· fulltext-read ·' in body
    assert 'đoạn trích 300 ký tự' in body


def test_the_changelog_header_carries_both_runs_and_the_frozen_anchor(harness):
    store, runtime, sid, _session = harness
    body = _four_groups(store, runtime, sid)
    assert '- Run gốc: `RS1`' in body
    assert '- Run làm mới: `RS2`' in body
    assert '- Mốc khảo sát cũ: 2026-01-05' in body
    assert '- Bản hồ sơ: v1' in body


def test_a_row_is_changed_when_only_its_excerpt_moves(harness):
    """Nguồn "đổi" không chỉ vì `status`: dòng sổ đọc lại được thêm chữ cũng là một thay đổi."""
    store, runtime, sid, _session = harness
    run(store, sid, 'RS1')
    source(store, sid, 'https://a.example/1', 'Nhận định', excerpt='x' * 100)
    run(store, sid, 'RS2', status='researching', extra={'refreshOf': 'RS1'})
    source(store, sid, 'https://a.example/1', 'Nhận định', excerpt='x' * 101, research_id='RS2')
    body = research_runtime.refresh_changelog(runtime, sid, 'RS1', 'RS2')
    assert '## Nguồn đổi (1)' in body
    assert '## Nguồn giữ nguyên (0)' in body


def test_a_run_without_rows_on_either_side_is_not_a_crash(harness):
    store, runtime, sid, _session = harness
    run(store, sid, 'RS1')
    run(store, sid, 'RS2', status='researching', extra={'refreshOf': 'RS1'})
    body = research_runtime.refresh_changelog(runtime, sid, 'RS1', 'RS2')
    assert '## Nguồn mới (0)' in body and '## Nguồn rút (0)' in body


def test_changelog_body_switches_to_the_source_diff_only_for_a_refresh_run(harness):
    store, runtime, sid, _session = harness
    run(store, sid, 'RS1')
    store.record_dossier(sid, 'RS1', 1, '.research/rs1/v1.md')
    plain = research_runtime._changelog_body(runtime, 'RS1', 2)
    assert '- bản v1' in plain and '- bản v2 (bản này)' in plain
    source(store, sid, 'https://a.example/1', 'Nhận định')
    run(store, sid, 'RS2', status='researching', extra={'refreshOf': 'RS1'})
    source(store, sid, 'https://d.example/4', 'Nguồn mới', research_id='RS2')
    frozen = research_runtime._changelog_body(runtime, 'RS2', 1)
    assert '## Nguồn mới (1)' in frozen and '- bản v2 (bản này)' not in frozen


def test_sidecar_names_add_changelog_for_a_refresh_job():
    names = research_report.sidecar_names(2, job_types=('refresh',))
    assert 'changelog.md' in names
    assert 'changelog.md' not in research_report.sidecar_names(2, job_types=('decide',))


# --- mở run làm mới ---------------------------------------------------------

def refresh(runtime, session, research_id='RS1', payload=None):
    job = runtime.store.research_job(research_id)
    return asyncio.run(research_runtime.refresh_run(runtime, session, job, payload))


def events(store, sid, kind):
    return [row['data'] for row in store.events(sid) if row['type'] == kind]


def test_a_refresh_run_is_a_new_run_that_inherits_the_old_ledger(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    source(store, sid, 'https://a.example/1', 'Nguồn cũ')
    answer = refresh(runtime, session, 'RS1')
    new_id = answer['researchId']
    assert new_id != 'RS1'
    assert answer['refreshOf'] == 'RS1'
    assert answer['sinceDate'] == '2026-01-05'  # mốc khảo sát CŨ, không phải hôm nay
    assert answer['inheritedRows'] == 1
    assert answer['supersedes'] == 3
    # Dòng chép sang nằm ở SỔ, KHÔNG vào cặp (nhận định, đoạn trích): nó chưa qua `source_verify`,
    # nên chưa được đỡ một nhận định "hiện trạng" nào của run mới.
    assert store.evidence_claims(sid, new_id) == []
    inherited = store.source_rows(sid, research_id=new_id)
    assert inherited and inherited[0]['status'] == limits.RESEARCH_REFRESH_INHERITED_STATUS
    assert inherited[0]['payload'].get('inherited') is True
    assert inherited[0]['payload'].get('inheritedFrom') == 'RS1'
    fresh = store.research_job(new_id)
    assert fresh['state']['refreshOf'] == 'RS1'
    assert fresh['state']['refreshSince'] == '2026-01-05'
    assert fresh['state']['supersedes'] == 3
    assert 'refresh' in fresh['state']['scope']['jobKinds']
    assert fresh['state']['scope']['surveyDate'] >= '2026-01-05'


def test_the_source_run_is_never_read_back_as_the_new_one(harness):
    """Brief của phiên đang trỏ vào run gốc ⇒ run mới phải mang mã KHÁC (§5.3) và run gốc không đổi."""
    store, runtime, sid, _session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    store.update_config(sid, {'research': {'researchId': 'RS1', 'tier': 2}})
    before = store.research_job('RS1')['state']
    answer = refresh(runtime, store.get(sid), 'RS1')
    assert answer['researchId'] != 'RS1'
    kept = store.research_job('RS1')['state']
    assert 'refreshOf' not in kept and kept['scope']['surveyDate'] == before['scope']['surveyDate']


def test_the_natural_slug_cannot_make_the_new_run_reuse_the_old_id(harness):
    """Mã run = slug của câu hỏi, mà câu hỏi giữ nguyên ⇒ phải ghim mã riêng, không ghi đè run gốc."""
    store, runtime, sid, session = harness
    run(store, sid, 'cau-hoi-goc-cua-run')
    dossier(store, sid, 'cau-hoi-goc-cua-run')
    source(store, sid, 'https://a.example/1', 'Nguồn cũ', research_id='cau-hoi-goc-cua-run')
    answer = refresh(runtime, session, 'cau-hoi-goc-cua-run')
    assert answer['researchId'] != 'cau-hoi-goc-cua-run'
    assert store.research_job(answer['researchId'])['state']['refreshOf'] == 'cau-hoi-goc-cua-run'
    assert 'refreshOf' not in store.research_job('cau-hoi-goc-cua-run')['state']
    assert store.research_job(answer['researchId'])['state']['supersedes'] == 3


def briefed_run(store, runtime, sid, session, question='Câu hỏi gốc của run'):
    """Run đi qua `research_brief` THẬT rồi chốt hồ sơ — chỉ khi ấy nhánh tự sinh hậu tố mới chạy.

    `run()` ở trên ghi thẳng hàng job nên `config['research']` rỗng: `new_run and existing` sai, nhánh
    hậu tố `-r{n}` không chạy, và lỗi D-2 (mã chủ nhà chỉ định bị cộng hậu tố LẦN HAI) không lộ ra.
    """
    asyncio.run(runtime.dispatch(session, 'research_brief', {
        'tier': 2, 'question': question, 'rationale': 'vì cần nguồn mới',
        'goal': 'mục tiêu', 'methods': ['web'],
        'questions': [{'text': 'Câu hỏi 1', 'importance': 'high'}]}))
    run_id = research_runtime.research_config(store.get(sid))['researchId']
    job = store.research_job(run_id)
    store.research_job_save(run_id, sid, job['state'], status='completed')
    store.record_dossier(sid, run_id, 3, f'.research/{run_id}-20260105-0900/v3.md',
                         profile='mixed', level=2, rows=1)
    return run_id


def test_a_named_id_survives_a_briefed_session_without_a_second_suffix(harness):
    """D-2 (vòng kiểm thử P2–P5): mã gõ tay từng bị đổi thành `r-3-explicit-test-r4`."""
    store, runtime, sid, session = harness
    source_id = briefed_run(store, runtime, sid, session)
    answer = refresh(runtime, store.get(sid), source_id, {'researchId': 'rs1-lam-moi'})
    assert answer['researchId'] == 'rs1-lam-moi'
    assert store.research_job('rs1-lam-moi') is not None


def test_without_a_named_id_the_new_run_still_gets_its_own_code(harness):
    """Đường tự sinh vẫn phải KHÁC run gốc — bản vá D-2 không được nới luật cũ."""
    store, runtime, sid, session = harness
    source_id = briefed_run(store, runtime, sid, session)
    answer = refresh(runtime, store.get(sid), source_id)
    assert answer['researchId'] != source_id
    assert answer['researchId'].startswith(source_id[:30].rstrip('-'))


def test_a_named_id_that_names_the_source_run_is_refused_before_any_write(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    before = store.research_job('RS1')['state']
    with pytest.raises(ValueError) as error:
        refresh(runtime, session, 'RS1', {'researchId': 'RS1'})
    assert 'RESEARCH_BRIEF_INVALID' in str(error.value)
    assert store.research_job('RS1')['state'] == before
    assert [item['research_id'] for item in store.research_jobs_for(sid)] == ['RS1']


def test_the_same_named_id_cannot_be_claimed_twice(harness):
    """Nhánh hậu tố tự sinh không còn che mã trùng: lần thứ hai phải bị TỪ CHỐI trước mọi ghi.

    Cửa cũ chỉ chặn mã trùng RUN GỐC (`refresh_run`); mã đã dùng ở một run khác từng lọt qua nhánh
    `-r{n}` của `research_brief`. Bản vá D-2 đặt cửa thứ hai: mã chủ nhà chỉ định là mã RIÊNG.
    """
    store, runtime, sid, session = harness
    source_id = briefed_run(store, runtime, sid, session)
    first = refresh(runtime, store.get(sid), source_id, {'researchId': 'rs1-lam-moi'})
    assert first['researchId'] == 'rs1-lam-moi'
    job = store.research_job('rs1-lam-moi')
    store.research_job_save('rs1-lam-moi', sid, job['state'], status='completed')
    before = sorted(item['research_id'] for item in store.research_jobs_for(sid))
    with pytest.raises(ValueError) as error:
        refresh(runtime, store.get(sid), source_id, {'researchId': 'rs1-lam-moi'})
    assert 'RESEARCH_BRIEF_INVALID' in str(error.value)
    assert sorted(item['research_id'] for item in store.research_jobs_for(sid)) == before


def test_the_refresh_event_and_answer_agree_on_the_counts(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    source(store, sid, 'https://a.example/1', 'Nguồn cũ')
    answer = refresh(runtime, session, 'RS1')
    assert [item['inheritedRows'] for item in events(store, sid, 'research_refresh')] == \
        [answer['inheritedRows']]
    assert events(store, sid, 'research_refresh')[0]['refreshOf'] == 'RS1'
    # Chưa có kế hoạch nào dựa vào run cũ ⇒ không có lời nhắc `RESEARCH_REFRESH_PLANS`.
    assert not [item for item in events(store, sid, 'notice')
                if item.get('code') == 'RESEARCH_REFRESH_PLANS']
    assert 'changelog' in answer and answer['changelog'].startswith('# Nhật ký thay đổi')


def test_a_refresh_run_answers_with_a_stable_custom_id_when_the_owner_names_one(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    answer = refresh(runtime, session, 'RS1', {'researchId': 'RS1-lam-moi'})
    assert answer['researchId'] == 'rs1-lam-moi'  # mã run đi qua `slug_from_question`
    assert store.research_job('rs1-lam-moi') is not None


def test_a_dependent_plan_earns_a_notice_with_its_code(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    store.plan_research_link('plan-9', 2, [{'researchId': 'RS1', 'version': 3,
                                            'contentHash': 'hash-9'}])
    answer = refresh(runtime, session, 'RS1')
    assert answer['dependentPlans'] == 1
    notices = [item for item in events(store, sid, 'notice')
               if item.get('code') == 'RESEARCH_REFRESH_PLANS']
    assert notices and 'RS1' in notices[0]['message']


# --- bốn cửa từ chối --------------------------------------------------------

def refusal(store, runtime, session, research_id, message, payload=None):
    job = store.research_job(research_id)
    with pytest.raises(ValueError) as error:
        asyncio.run(research_runtime.refresh_run(runtime, session, job, payload))
    assert message in str(error.value)
    return str(error.value)


def test_the_switch_off_turns_the_route_off(harness, monkeypatch):
    store, runtime, sid, session = harness
    monkeypatch.setenv(limits.RESEARCH_REFRESH_ENV, 'off')
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    assert limits.research_refresh_enabled() is False
    refusal(store, runtime, session, 'RS1', limits.RESEARCH_REFRESH_DISABLED_CODE)
    # Công tắc off: KHÔNG run mới nào được ghi.
    assert [item['research_id'] for item in store.research_jobs_for(sid)] == ['RS1']


def test_an_unknown_switch_value_is_noticed_and_keeps_the_default(harness, monkeypatch):
    store, runtime, sid, session = harness
    monkeypatch.setenv(limits.RESEARCH_REFRESH_ENV, 'có lẽ')
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    answer = refresh(runtime, session, 'RS1')
    assert answer['researchId'] != 'RS1'  # giá trị lạ ⇒ về mặc định `on`, có nói ra
    assert [item['code'] for item in events(store, sid, 'notice')].count(
        limits.RESEARCH_REFRESH_MODE_UNKNOWN_CODE) == 1


def test_a_run_without_a_dossier_has_nothing_to_refresh(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    refusal(store, runtime, session, 'RS1', limits.RESEARCH_REFRESH_NO_DOSSIER_CODE)


def test_a_running_source_run_refuses_a_refresh(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1', status='researching')
    dossier(store, sid, 'RS1')
    refusal(store, runtime, session, 'RS1', limits.RESEARCH_REFRESH_SOURCE_ACTIVE_CODE)


def test_a_second_refresh_of_the_same_run_waits_for_the_first(harness):
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    first = refresh(runtime, session, 'RS1')
    store.research_job_save(first['researchId'], sid, store.research_job(first['researchId'])['state'],
                            status='researching')
    refusal(store, runtime, session, 'RS1', limits.RESEARCH_REFRESH_RUN_ACTIVE_CODE)


def test_a_finished_refresh_leaves_the_door_open(harness):
    """Run làm mới đã xong thì run gốc lại làm mới được — cửa từ chối chỉ đóng khi nó ĐANG chạy."""
    store, runtime, sid, session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    first = refresh(runtime, session, 'RS1')
    run(store, sid, first['researchId'], status='completed',
        extra={'refreshOf': 'RS1', 'refreshSince': '2026-01-05'})
    second = refresh(runtime, session, 'RS1')
    assert second['researchId'] not in ('RS1', first['researchId'])


# --- tuyến HTTP mà giao diện gọi -------------------------------------------

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


def patch_job(store, research_id, payload):
    """Gọi ĐÚNG tuyến mà nút "Cập nhật" của giao diện gọi, trên một runtime thật.

    Trả `(status, body, job đã ghi của run mới)`: `create_app` đóng store lúc dừng server nên hàng
    phải được đọc NGAY TRONG luồng, không đọc sau khi `close()`.
    """
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())

    async def flow():
        server = TestServer(create_app(runtime))
        await server.start_server()
        try:
            async with ClientSession() as http:
                answer = await http.patch(server.make_url(f'/api/agent/research/jobs/{research_id}'),
                                          json=payload, headers=HEADERS)
                status, body = answer.status, await answer.json()
            new_id = str(body.get('researchId') or '')
            return status, body, (store.research_job(new_id) if new_id else None)
        finally:
            await server.close()

    return asyncio.run(flow())


def test_the_refresh_action_is_accepted_by_the_job_route(harness):
    store, _runtime, sid, _session = harness
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    source(store, sid, 'https://a.example/1', 'Nguồn cũ')
    status, body, created = patch_job(store, 'RS1', {'action': 'refresh'})
    assert status == 200, body
    assert body['refreshOf'] == 'RS1'
    assert body['researchId'] != 'RS1'
    assert body['sinceDate'] == '2026-01-05'
    assert created is not None and created['state']['refreshOf'] == 'RS1'
    assert body['inheritedRows'] == 1 and created['state']['supersedes'] == 3


def test_the_refresh_action_answers_409_when_the_switch_is_off(harness, monkeypatch):
    store, _runtime, sid, _session = harness
    monkeypatch.setenv(limits.RESEARCH_REFRESH_ENV, 'off')
    run(store, sid, 'RS1')
    dossier(store, sid, 'RS1')
    status, body, _created = patch_job(store, 'RS1', {'action': 'refresh'})
    assert status == 409, body
    assert body['code'] == limits.RESEARCH_REFRESH_DISABLED_CODE
    assert body['error'].count(limits.RESEARCH_REFRESH_DISABLED_CODE) == 1


def test_a_refresh_without_a_dossier_answers_a_clean_409(harness):
    store, _runtime, sid, _session = harness
    run(store, sid, 'RS1')
    status, body, _created = patch_job(store, 'RS1', {'action': 'refresh'})
    assert status == 409, body
    assert body['code'] == limits.RESEARCH_REFRESH_NO_DOSSIER_CODE
