"""Cổng cấu trúc của báo cáo + cổng chính sách thời gian — P2 (hợp đồng P2 §7.5–§7.6).

Bốn điều kiện nghiệm thu của §7 P2 được ghim ở đây:

* **mô-đun đã hứa mà thiếu** ⇒ `research-report-module-missing`;
* **nhận định chính không có `claimId`** ⇒ `research-report-claim-missing`;
* **mục "Chưa khảo sát" không khớp facet chưa bão hoà** ⇒ `research-report-unexplored-mismatch`;
* **nhận định hiện trạng chỉ đỡ bằng nguồn ngoài cửa sổ** ⇒ `research-stale-current-claim`.

Và mặt còn lại, để một luật quá tay cũng lộ ra: công tắc `BOXFOX_RESEARCH_STRUCTURED_REPORT=off` phải
trả cổng về đúng luật DÒ TIÊU ĐỀ cũ (`research-shape-missing`), còn `on` thì chấm **cấu trúc** — một
hồ sơ không có tiêu đề mục nào nhưng `report` đủ khung vẫn đi qua.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import agentbox.sandbox.worker as worker

from agentbox.agent_core import limits, research_facets, research_report, research_runtime
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

RUN = 'run-gate'
EXCERPT = ('Bộ chuẩn gồm 1 200 mẫu; mô hình đạt độ chính xác 92 phần trăm và sai số 3 điểm phần trăm '
           'trên tập kiểm tra độc lập. ') * 3
URL = 'https://moh.gov.vn/nghien-cuu/x'
MARKDOWN = f"""# Kết luận ngắn
Mô hình X đạt 92% trên bộ chuẩn [r1] ({URL}).

# Nguồn
- r1 — moh.gov.vn, tầng 1.
"""


class FixtureExecutor:
    """Box giả: ghi lại đúng tham số `dossier_write` (kể cả tệp phụ) và trả đường dẫn."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'relativePath': args['path'], 'version': 1, 'bytes': len(args['markdown'].encode()),
                'sha1': 'abc123', 'files': [args['path']]}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv(limits.RESEARCH_STRUCTURED_REPORT_ENV, raising=False)
    monkeypatch.delenv(limits.RESEARCH_TIME_POLICY_ENV, raising=False)
    monkeypatch.delenv('BOXFOX_RESEARCH_GATE', raising=False)
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, FixtureModel())
    runtime.search_db_path = tmp_path / 'search.sqlite'
    sid = runtime.create({'skills': []})['id']
    session = store.get(sid)
    session['config']['research'] = {
        'researchId': RUN, 'jobMode': 'v2', 'jobProfile': 'market', 'tier': 2,
        'dossierDir': research_runtime.dossier_dir_for(RUN)}
    store.update_config(sid, session['config'])
    store.research_job_save(RUN, sid, {
        'origin': 'mode', 'phase': 'researching', 'budgetSeconds': 1800, 'tier': 2, 'goal': 'Toàn cảnh',
        'questions': [{'id': 'q1', 'importance': 'high', 'status': 'answered'}],
        'scope': {'revision': 1, 'jobKinds': ['landscape'],
                  'questions': [{'id': 'q1', 'text': 'Độ chính xác?', 'importance': 'high',
                                 'status': 'answered'}],
                  'timePolicy': {'velocity': 'fast', 'reason': 'thị trường đổi nhanh',
                                 'status': 'assumed'},
                  'surveyDate': '2026-09-25'}}, status='researching')
    yield store, runtime, sid, executor
    store.close()


def seed_claim(runtime, sid, **overrides):
    """Ghim một dòng sổ cho khẳng định chính; trả `claimId` máy cấp."""
    args = {'claim': 'Mô hình X đạt độ chính xác 92% trên bộ chuẩn', 'url': URL, 'excerpt': EXCERPT}
    args.update(overrides)
    return research_runtime.source_add(runtime, runtime.store.get(sid), args)['claimId']


def valid_report(claim_id, **overrides):
    """Báo cáo đủ tám mục khung + mô-đun bắt buộc + một nhận định có `claimId`."""
    report = {'schemaVersion': 1, 'modules': ['M-landscape'],
              'sections': [section_id for section_id, _label in research_report.FRAME_SECTIONS],
              'claims': [{'claimId': claim_id, 'claimType': 'numeric', 'confidence': 'high'}],
              'unexplored': []}
    report.update(overrides)
    return report


def write(runtime, sid, report, **overrides):
    args = {'researchId': RUN, 'level': 2, 'profile': 'market', 'title': 'Toàn cảnh',
            'markdown': MARKDOWN, 'rows': [], 'report': report}
    args.update(overrides)
    return asyncio.run(research_runtime.dossier_write(runtime, runtime.store.get(sid), args))


# --------------------------------------------------------------- cổng cấu trúc


def test_a_promised_module_that_is_missing_is_refused(harness):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid)
    result = write(runtime, sid, valid_report(claim_id, modules=['M-compare']))
    assert result['gate']['ok'] is False
    assert 'research-report-module-missing' in result['gate']['issues']


def test_a_claim_without_a_claim_id_is_refused(harness):
    store, runtime, sid, _executor = harness
    seed_claim(runtime, sid)
    result = write(runtime, sid, valid_report('c-missing',
                                              claims=[{'claimType': 'numeric', 'confidence': 'high'}]))
    assert 'research-report-claim-missing' in result['gate']['issues']


def test_a_claim_pointing_at_a_row_the_ledger_does_not_have_is_refused(harness):
    store, runtime, sid, _executor = harness
    seed_claim(runtime, sid)
    result = write(runtime, sid, valid_report('c-khong-co'))
    assert 'research-report-claim-unknown' in result['gate']['issues']


def test_the_unexplored_section_must_match_the_facets_that_are_not_saturated(harness):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid)
    open_facet = research_facets.new_facet('Hướng còn mở', seed='scope')
    closed = research_facets.new_facet('Hướng đã bão hoà', seed='survey', status='saturated')
    store.facet_save(RUN, open_facet)
    store.facet_save(RUN, closed)
    refused = write(runtime, sid, valid_report(claim_id, unexplored=[closed['label']]))
    assert 'research-report-unexplored-mismatch' in refused['gate']['issues']
    passed = write(runtime, sid, valid_report(claim_id, unexplored=[open_facet['label']]),
                   overwrite=True)
    assert 'research-report-unexplored-mismatch' not in passed['gate']['issues']


def test_the_structured_gate_replaces_the_heading_word_detection_when_on(harness):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid)
    # Không có tiêu đề mục nào: luật cũ (dò tiêu đề) sẽ từ chối, luật cấu trúc thì không.
    result = write(runtime, sid, valid_report(claim_id), markdown=f'Mô hình X đạt 92% [r1] ({URL}).\n')
    assert 'research-shape-missing' not in result['gate']['issues']
    assert result['gate']['ok'] is True


def test_the_switch_off_restores_the_heading_word_gate(harness, monkeypatch):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid)
    monkeypatch.setenv(limits.RESEARCH_STRUCTURED_REPORT_ENV, 'off')
    result = write(runtime, sid, valid_report(claim_id, modules=['M-compare']),
                   markdown='# Phát hiện\nMô hình X đạt 92% [r1]\n')
    assert 'research-report-module-missing' not in result['gate']['issues'], \
        'công tắc off ⇒ cổng không được đọc `report`'
    assert 'research-shape-missing' in result['gate']['issues'], \
        'công tắc off ⇒ quay về đúng luật dò tiêu đề'


# -------------------------------------------------------- cổng chính sách thời gian


def test_a_current_state_claim_supported_only_by_old_sources_is_refused(harness):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid, publishedAt='2015-01-01',
                          claim='Xu hướng mô hình X đang tăng trong năm nay')
    report = valid_report(claim_id, claims=[{'claimId': claim_id, 'claimType': 'current-fact',
                                             'confidence': 'high'}])
    result = write(runtime, sid, report)
    assert limits.RESEARCH_STALE_CURRENT_CLAIM_CODE in result['gate']['issues']
    assert result['gate']['ok'] is False
    assert claim_id in result['staleCurrentClaims'][0]


def test_a_current_state_claim_with_a_source_inside_the_window_passes(harness):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid, publishedAt='2026-06-01',
                          claim='Xu hướng mô hình X đang tăng trong năm nay')
    report = valid_report(claim_id, claims=[{'claimId': claim_id, 'claimType': 'current-fact',
                                             'confidence': 'high'}])
    result = write(runtime, sid, report)
    assert limits.RESEARCH_STALE_CURRENT_CLAIM_CODE not in result['gate']['issues']


def test_the_time_policy_switch_off_lets_an_old_only_current_claim_through(harness, monkeypatch):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid, publishedAt='2015-01-01',
                          claim='Xu hướng mô hình X đang tăng trong năm nay')
    report = valid_report(claim_id, claims=[{'claimId': claim_id, 'claimType': 'current-fact',
                                             'confidence': 'high'}])
    monkeypatch.setenv(limits.RESEARCH_TIME_POLICY_ENV, 'off')
    result = write(runtime, sid, report)
    assert limits.RESEARCH_STALE_CURRENT_CLAIM_CODE not in result['gate']['issues']


# ------------------------------------------------- mức tin cậy máy chấm + tệp phụ


def test_the_machine_caps_the_confidence_and_the_model_cannot_raise_it(harness):
    store, runtime, sid, _executor = harness
    # Một dòng sổ ở tầng 1, chỉ mới có bản toàn văn "đã có đường tới" (chưa đọc) ⇒ trần `medium`.
    claim_id = seed_claim(runtime, sid, accessLevel='fulltext-available')
    report = valid_report(claim_id, claims=[{'claimId': claim_id, 'claimType': 'numeric',
                                             'confidence': 'high'}])
    write(runtime, sid, report)
    meta = store.claim_meta(RUN, claim_id)
    assert meta['confidenceCap'] == 'medium'
    assert meta['confidence'] == 'medium', 'mô hình khai `high` đã bị hạ xuống trần'
    assert meta['claimType'] == 'numeric' and meta['asOf'] == '2026-09-25'
    assert meta['basis']['rule'] == 'single-secondary'


def test_the_model_can_lower_the_confidence_below_the_machine_cap(harness):
    store, runtime, sid, _executor = harness
    claim_id = seed_claim(runtime, sid, accessLevel='fulltext-available')
    report = valid_report(claim_id, claims=[{'claimId': claim_id, 'claimType': 'numeric',
                                             'confidence': 'low'}])
    write(runtime, sid, report)
    meta = store.claim_meta(RUN, claim_id)
    assert meta['confidence'] == 'low' and meta['confidenceCap'] == 'medium'


def test_the_dossier_write_sends_the_run_sidecars_with_names_from_the_report_module(harness):
    store, runtime, sid, executor = harness
    claim_id = seed_claim(runtime, sid)
    write(runtime, sid, valid_report(claim_id))
    _name, args, _sid = executor.calls[-1]
    names = [item['name'] for item in args['sidecars']]
    assert names == list(research_report.sidecar_names(1, job_types=('landscape',)))
    assert any(name.endswith('-coverage.json') for name in names)
    assert not any(name == 'changelog.md' for name in names), 'chỉ kiểu việc `refresh` mới có nhật ký'


def test_a_refresh_job_also_writes_the_changelog_sidecar(harness):
    store, runtime, sid, executor = harness
    claim_id = seed_claim(runtime, sid)
    job = store.research_job(RUN)
    job['state']['scope']['jobKinds'] = ['refresh']
    store.research_job_save(RUN, sid, job['state'], status='researching')
    write(runtime, sid, valid_report(claim_id))
    _name, args, _sid = executor.calls[-1]
    names = [item['name'] for item in args['sidecars']]
    assert 'changelog.md' in names


# ------------------------------------------------ tệp phụ do worker ghi (§7.7)

def test_the_worker_writes_the_run_sidecars_including_one_level_of_folder(tmp_path, monkeypatch):
    # `monkeypatch` trả `ROOT` về giá trị cũ sau bài kiểm — không để rò rỉ sang bài khác.
    monkeypatch.setattr(worker, 'ROOT', Path(tmp_path).resolve())
    result = worker.execute('dossier_write', {
        'path': '.research/run-gate/v1-run-gate.md', 'markdown': '# Hồ sơ\nNội dung ngắn.\n',
        'title': 'Toàn cảnh',
        'sidecars': [{'name': 'v1-coverage.json', 'content': '{"counts": {}}'},
                     {'name': 'extractions/s-1.json', 'content': '{"sourceId": "s-1"}'}]},
        'session-1')
    assert result['files'] == ['.research/run-gate/v1-run-gate.md',
                               '.research/run-gate/sources.jsonl',
                               '.research/run-gate/sources.md',
                               '.research/run-gate/v1-coverage.json',
                               '.research/run-gate/extractions/s-1.json']
    assert (Path(tmp_path) / '.research/run-gate/extractions/s-1.json').is_file()


def test_the_worker_refuses_a_sidecar_name_that_is_a_path_and_writes_nothing(tmp_path, monkeypatch):
    root = Path(tmp_path).resolve()
    monkeypatch.setattr(worker, 'ROOT', root)
    with pytest.raises(ValueError, match='DOSSIER_SIDECAR_INVALID'):
        worker.execute('dossier_write', {
            'path': '.research/run-gate/v1-run-gate.md', 'markdown': '# Hồ sơ\nNội dung.\n',
            'title': 'Toàn cảnh',
            'sidecars': [{'name': '../thoat-ra.json', 'content': '{}'}]}, 'session-1')
    assert [item.relative_to(root).as_posix() for item in root.rglob('*') if item.is_file()] == []
