"""`research_facets` (P2 §5.5): khoá facet, từ khoá có nguồn gốc, bão hoà đọc từ nhật ký, điểm dừng."""
from __future__ import annotations

from agentbox.agent_core import limits
from agentbox.agent_core import research_facets as rf


def log(results, relevant_new, created=0.0, facet_id='f-1', research_id='R1'):
    """Một dòng nhật ký tìm ĐÚNG hình dạng `search_store.search_log()` trả về (camelCase, có số đo)."""
    return {'facetId': facet_id, 'researchId': research_id, 'results': results,
            'newUnique': relevant_new, 'relevantNew': relevant_new, 'created': created}


def unmeasured(results, created=0.0, facet_id='f-1', research_id='R1'):
    """Dòng KHÔNG mang số đo lợi suất (`relevant_*`) — nhà ghi khác/dòng cũ, phải là \"chưa đo\"."""
    return {'facetId': facet_id, 'researchId': research_id, 'results': results,
            'newUnique': results, 'created': created}


# --- khoá và chuẩn hoá ------------------------------------------------------

def test_facet_id_is_stable_and_ignores_case_accents_and_spacing():
    first = rf.facet_id_for('Retrieval Augmented Generation')
    assert first == rf.facet_id_for('  retrieval   augmented generation ')
    assert first == rf.facet_id_for('Retrieval Augmented Generátion'.replace('á', 'a'))
    assert first.startswith('f-') and len(first) == 14
    assert rf.facet_id_for('Hướng A') == rf.facet_id_for('huong a')
    assert rf.facet_id_for('A') != rf.facet_id_for('B')
    assert rf.facet_id_for('') == rf.facet_id_for(None)


def test_new_facet_carries_the_seed_source_everywhere():
    facet = rf.new_facet('Agent memory', kind='direction', seed='survey', question_id='q1',
                         terms=['memory', {'text': 'state', 'source': 'scope'}])
    assert facet['facetId'] == rf.facet_id_for('Agent memory')
    assert facet['seedSource'] == 'survey'
    assert facet['questionId'] == 'q1'
    assert facet['status'] == 'unexplored'
    assert [term['text'] for term in facet['terms']] == ['memory', 'state']
    assert [term['source'] for term in facet['terms']] == ['survey', 'scope']


def test_normalize_facet_falls_back_on_unknown_values():
    facet = rf.normalize_facet({'label': 'X', 'kind': 'lạ', 'status': 'LẠ', 'seedSource': 'lạ',
                                'priority': 'urgent', 'terms': 'không phải list',
                                'evidenceCount': 'n/a', 'lastNewRatio': None})
    assert facet['kind'] == 'direction'
    assert facet['status'] == 'unexplored'
    assert facet['seedSource'] == 'agent'
    assert facet['priority'] == 'medium'
    assert facet['terms'] == [{'text': 'không phải list', 'source': 'agent'}]
    assert facet['evidenceCount'] == 0
    assert facet['lastNewRatio'] == -1.0
    assert rf.normalize_facet(None)['facetId'] == rf.facet_id_for('')


def test_merge_terms_keeps_provenance_and_reports_what_is_new():
    facet = rf.new_facet('X', seed='scope', terms=['a'])
    merged = rf.merge_terms(facet, ['a', {'text': 'b', 'source': 'survey'}])
    assert [term['text'] for term in merged['terms']] == ['a', 'b']
    assert [term['text'] for term in merged['addedTerms']] == ['b']
    again = rf.merge_terms(merged, ['a', 'b'])
    assert again['addedTerms'] == []
    assert len(again['terms']) == 2
    assert rf.merge_terms(None, ['x'])['terms'][0]['text'] == 'x'


# --- bão hoà ----------------------------------------------------------------

def test_saturation_needs_two_consecutive_quiet_waves():
    quiet = [log(20, 0, 1.0), log(20, 1, 2.0)]
    assert rf.saturation_state(quiet) == {'status': 'saturated', 'waves': 2, 'ratios': [0.0, 0.05],
                                          'lastRatio': 0.05}
    busy = [log(10, 0, 1.0), log(10, 9, 2.0)]
    state = rf.saturation_state(busy)
    assert state['status'] == 'searched'
    assert state['waves'] == 0
    assert state['lastRatio'] == 0.9


def test_saturation_of_an_untouched_facet_and_of_a_single_wave():
    assert rf.saturation_state([]) == {'status': 'unexplored', 'waves': 0, 'ratios': [],
                                       'lastRatio': -1.0}
    assert rf.saturation_state([log(10, 0, 1.0)])['status'] == 'searched'
    assert rf.saturation_state([log(20, 0)])['waves'] == 1


def test_saturation_threshold_is_the_limits_constant():
    # Ngưỡng là "dưới 10%", không phải "10% trở xuống".
    assert rf.saturation_state([log(100, 9), log(100, 9)])['status'] == 'saturated'
    assert rf.saturation_state([log(100, 10), log(100, 10)])['status'] == 'searched'
    assert limits.RESEARCH_SATURATION_WAVES == 2
    assert limits.RESEARCH_SATURATION_NEW_RATIO == 0.10


def test_a_row_without_a_yield_measurement_is_unmeasured_not_zero():
    """Dòng thiếu `relevant_*` KHÔNG được đọc thành 0 — nếu không mọi facet bão hoà sau hai sóng."""
    mixed = rf.saturation_state([log(20, 0, 1.0), unmeasured(20, 2.0), unmeasured(20, 3.0)])
    assert mixed['status'] == 'searched', 'hai sóng CHƯA ĐO không được kết luận bão hoà'
    # `waves` đếm sóng ĐO ĐƯỢC liên tiếp cuối cùng: ba dòng vào nhưng chỉ một dòng có số đo.
    assert mixed['waves'] == 1
    assert mixed['ratios'] == [0.0]
    assert mixed['lastRatio'] == 0.0
    never = rf.saturation_state([unmeasured(10, 1.0), unmeasured(10, 2.0), unmeasured(10, 3.0)])
    assert never['status'] == 'searched' and never['ratios'] == [] and never['lastRatio'] == -1.0
    assert never['waves'] == 0, 'không có sóng nào đo được thì không có sóng lặng nào để đếm'
    assert rf.saturation_state([unmeasured(10, 1.0)])['status'] == 'searched'
    assert rf.saturation_state([])['status'] == 'unexplored'


def test_two_genuinely_low_yield_measured_waves_still_saturate():
    rows = [log(20, 12, 1.0), log(10, 0, 2.0), log(10, 0, 3.0)]
    state = rf.saturation_state(rows)
    assert state['status'] == 'saturated'
    assert state['waves'] == 2
    assert state['ratios'] == [0.6, 0.0, 0.0]
    # Dòng CHƯA ĐO chen giữa cũng không cản hai sóng ĐO ĐƯỢC cuối cùng bão hoà.
    mixed = rf.saturation_state([log(10, 0, 1.0), unmeasured(10, 2.0), log(10, 0, 3.0)])
    assert mixed['status'] == 'saturated' and mixed['ratios'] == [0.0, 0.0]


def test_saturation_ignores_order_of_arrival_and_reads_both_key_styles():
    rows = [log(10, 0, created=2.0), log(10, 0, created=1.0)]
    assert rf.saturation_state(rows)['status'] == 'saturated'
    snake = [{'facet_id': 'f-1', 'research_id': 'R1', 'results': 8, 'relevant_new': 0, 'created': 1.0},
             {'facet_id': 'f-1', 'research_id': 'R1', 'results': 8, 'relevant_new': 0, 'created': 2.0}]
    assert rf.saturation_from_log(snake)['facets']['f-1']['status'] == 'saturated'


def test_zero_results_is_not_counted_as_a_catch():
    state = rf.saturation_state([log(0, 0), log(0, 0)])
    # Lượt tìm không trả kết quả nào không phải là "hết đất": ratio 0 nhưng vẫn là sóng lặng,
    # nên facet được coi là bão hoà chỉ khi có lượt tìm thật sự thu về ít mới.
    assert state['status'] == 'saturated'
    assert state['ratios'] == [0.0, 0.0]


def test_saturation_from_log_groups_by_facet_and_filters_by_run():
    rows = [log(20, 0, 1.0, facet_id='f-1'), log(20, 0, 2.0, facet_id='f-1'),
            log(10, 9, 3.0, facet_id='f-2'), log(20, 0, 9.0, facet_id='f-3', research_id='R2'),
            log(20, 0, 4.0, facet_id='')]
    payload = rf.saturation_from_log(rows, research_id='R1')
    assert sorted(payload['facets']) == ['f-1', 'f-2']
    assert payload['facets']['f-1']['status'] == 'saturated'
    assert payload['facets']['f-2']['status'] == 'searched'
    assert payload['facetIds'] == ['f-1', 'f-2']
    assert payload['overall']['ratios'] == [0.0, 0.0, 0.9, 0.0]  # f-1 ×2, không facet, f-2
    assert rf.saturation_from_log(None)['facets'] == {}


# --- bản đồ bao phủ ---------------------------------------------------------

def test_coverage_payload_counts_statuses_and_questions():
    facets = [rf.new_facet('A', status='saturated'), rf.new_facet('B', status='thin', note='ít bài'),
              rf.new_facet('C'), rf.new_facet('D', status='blocked')]
    questions = [{'questionId': 'q1', 'importance': 'high', 'state': 'answered'},
                 {'questionId': 'q2', 'importance': 'high', 'state': 'open'},
                 {'questionId': 'q3', 'importance': 'low', 'state': 'open'}]
    payload = rf.coverage_payload(facets, questions=questions, citations={'rounds': 2, 'stalledRounds': 1})
    assert payload['counts']['saturated'] == 1
    assert payload['counts']['thin'] == 1
    assert payload['counts']['unexplored'] == 1
    assert payload['counts']['blocked'] == 1
    assert payload['counts']['total'] == 4
    assert payload['unexplored'] == ['C']
    assert payload['thin'] == ['B']
    assert payload['blocked'] == ['D']
    assert payload['questions'] == {'high': 2, 'open': ['q2']}
    assert payload['citationChase'] == {'rounds': 2, 'stalledRounds': 1, 'stopRounds': 3}
    assert rf.coverage_payload([])['counts']['total'] == 0


def test_coverage_payload_handles_garbage():
    payload = rf.coverage_payload([None, 'x', {}, rf.new_facet('Thật')], questions=[None],
                                  citations='không')
    # Facet không có nhãn bị bỏ: hàng rác không được kể vào bao phủ.
    assert payload['counts']['total'] == 1
    assert payload['facets'][0]['label'] == 'Thật'
    assert payload['citationChase']['rounds'] == 0
    assert payload['questions'] == {'high': 0, 'open': []}


# --- điểm dừng --------------------------------------------------------------

def test_stop_checks_blocks_on_open_high_questions_and_open_facets():
    facets = [rf.new_facet('A', status='searched'), rf.new_facet('B', status='saturated')]
    questions = [{'questionId': 'q1', 'importance': 'high', 'state': 'open'}]
    report = rf.stop_checks(facets, questions)
    assert report['ready'] is False
    codes = [item['code'] for item in report['blockers']]
    assert codes == ['research-question-open', 'research-facet-open']
    assert report['counts']['openFacets'] == 1
    assert any('A' in item['detail'] for item in report['blockers'])


def test_stop_checks_accepts_closed_facets_and_resolved_questions():
    facets = [rf.new_facet('A', status='saturated'), rf.new_facet('B', status='thin', note='chỉ 2 bài'),
              rf.new_facet('C', status='blocked'), rf.new_facet('D', status='out-of-scope')]
    questions = [{'questionId': 'q1', 'importance': 'high', 'state': 'answered'},
                 {'questionId': 'q2', 'importance': 'high', 'state': 'contested'},
                 {'questionId': 'q3', 'importance': 'high', 'state': 'blocked', 'reason': 'trả phí'},
                 {'questionId': 'q4', 'importance': 'low', 'state': 'open'}]
    report = rf.stop_checks(facets, questions)
    assert report['ready'] is True
    assert report['blockers'] == []
    assert report['reasons']


def test_thin_without_a_note_still_blocks_and_blocked_without_reason_blocks():
    thin = rf.stop_checks([rf.new_facet('A', status='thin')], [])
    assert thin['ready'] is False
    blocked = rf.stop_checks([], [{'questionId': 'q1', 'importance': 'high', 'state': 'blocked'}])
    assert [item['code'] for item in blocked['blockers']] == ['research-question-open']


def test_stop_checks_reports_partial_run_without_treating_it_as_ready():
    budget = rf.stop_checks([], [], budget={'exhausted': True})
    assert budget['partial'] is True
    assert budget['ready'] is True  # hết ngân sách không phải lỗi cổng, chỉ là run `partial`
    assert any('partial' in reason for reason in budget['reasons'])
    stalled = rf.stop_checks([], [], stalled_waves=2)
    assert stalled['partial'] is True
    assert stalled['stalledWaves'] == 2
    assert rf.stop_checks([], [], stalled_waves=1)['partial'] is False
    assert rf.stop_checks([], [], budget={'hard_ceiling': True})['partial'] is True


def test_coverage_issues_block_until_resolved():
    issue = {'kind': 'missing-direction', 'detail': 'thiếu hướng X', 'resolved': False}
    blocked = rf.stop_checks([], [], coverage_issues=[issue])
    assert [item['code'] for item in blocked['blockers']] == ['research-coverage-open']
    assert blocked['blockers'][0]['detail'] == 'thiếu hướng X'
    assert rf.stop_checks([], [], coverage_issues=[dict(issue, resolved=True)])['ready'] is True
    assert rf.stop_checks([], [], coverage_issues=[dict(issue, status='closed')])['ready'] is True


# --- facet từ tổng quan -----------------------------------------------------

def test_facet_from_survey_takes_the_classification_from_the_survey():
    facet = rf.facet_from_survey({'title': 'Retrieval-Augmented Generation', 'kind': 'direction',
                                  'questionId': 'q1', 'url': 'https://arxiv.org/abs/1'})
    assert facet['seedSource'] == 'survey'
    assert facet['label'] == 'Retrieval-Augmented Generation'
    assert facet['terms'][0] == {'text': 'Retrieval-Augmented Generation', 'source': 'survey'}
    assert 'https://arxiv.org/abs/1' in facet['note']
    assert facet['status'] == 'unexplored'
    empty = rf.facet_from_survey(None)
    assert empty['label'] == '' and empty['seedSource'] == 'survey'
    assert rf.facet_from_survey({'heading': 'Ứng dụng y tế', 'kind': 'application',
                                 'terms': ['y tế', 'lâm sàng'], 'note': 'từ mục 4'})['kind'] == 'application'


# --- tầng lưu trữ (P2 §4): hàng facet đọc/ghi được, khoá tính từ nhãn ---------

def store(tmp_path):
    from agentbox.memory.session_store import SessionStore
    return SessionStore(tmp_path / 'sessions.sqlite')


def test_facet_save_derives_the_key_from_the_label_when_it_is_missing(tmp_path):
    db = store(tmp_path)
    saved = db.facet_save('R1', {'label': 'Retrieval Augmented Generation', 'kind': 'direction',
                                 'status': 'searched', 'seedSource': 'survey',
                                 'terms': [{'text': 'RAG', 'source': 'survey'}], 'lastNewRatio': 0.4})
    assert saved['facetId'] == rf.facet_id_for('Retrieval Augmented Generation')
    assert saved['label'] == 'Retrieval Augmented Generation'
    assert saved['terms'] == [{'text': 'RAG', 'source': 'survey'}]
    assert saved['lastNewRatio'] == 0.4
    # Cùng nhãn khác cách viết ⇒ CÙNG hàng, không sinh hàng thứ hai.
    again = db.facet_save('R1', {'label': '  retrieval   augmented   generation ', 'status': 'thin'})
    assert again['facetId'] == saved['facetId']
    assert [item['facetId'] for item in db.facet_list('R1')] == [saved['facetId']]
    assert again['status'] == 'thin'
    assert again['terms'] == saved['terms']


def test_facet_save_refuses_a_row_without_label_or_key(tmp_path):
    db = store(tmp_path)
    import pytest
    with pytest.raises(ValueError) as error:
        db.facet_save('R1', {'kind': 'direction'})
    assert str(error.value) == 'RESEARCH_FACET_KEY'
    with pytest.raises(ValueError):
        db.facet_save('R1', {})
    assert db.facet_list('R1') == []


def test_facet_list_is_per_run_and_delete_reports_whether_a_row_was_removed(tmp_path):
    db = store(tmp_path)
    db.facet_save('R1', {'label': 'Hướng A'})
    db.facet_save('R2', {'label': 'Hướng A'})
    key = rf.facet_id_for('Hướng A')
    assert [item['label'] for item in db.facet_list('R1')] == ['Hướng A']
    assert db.facet_delete('R1', key) is True
    assert db.facet_delete('R1', key) is False
    assert db.facet_list('R1') == []
    assert [item['label'] for item in db.facet_list('R2')] == ['Hướng A']


def test_facets_survive_reopening_the_store(tmp_path):
    from agentbox.memory.session_store import SessionStore
    first = SessionStore(tmp_path / 'sessions.sqlite')
    first.facet_save('R1', {'label': 'Hướng A', 'status': 'saturated', 'lastNewRatio': 0.05,
                            'terms': ['alpha']})
    second = SessionStore(tmp_path / 'sessions.sqlite')
    row = second.facet('R1', rf.facet_id_for('Hướng A'))
    assert row['status'] == 'saturated'
    assert row['lastNewRatio'] == 0.05
    assert row['terms'] == ['alpha']
    assert second.facet('R1', 'f-không-có') == {}
