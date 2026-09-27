"""`research_evidence` (P2 §5.6–5.7): luật thời gian, gốc nguồn, mức trần độ tin cậy.

Không mạng, không đĩa: tệp thuần nên test thuần.
"""
from __future__ import annotations

import pytest

from agentbox.agent_core import limits
from agentbox.agent_core import research_evidence as ev


def entry(**kwargs):
    base = {'sourceId': 's-1', 'claimId': 'c-1', 'rowId': 'r1', 'tier': 1,
            'accessLevel': 'snippet', 'originCluster': '', 'publishedAt': '', 'updatedAt': '',
            'sourceKind': 'page', 'sectionKind': ''}
    base.update(kwargs)
    return base


# --- ngày và cửa sổ ---------------------------------------------------------

@pytest.mark.parametrize('value,expected', [
    ('2026-03-02', '2026-03-02'),
    ('2026-03-02T10:00:00Z', '2026-03-02'),
    ('2 March 2026', '2026-03-02'),
    ('March 2, 2026', '2026-03-02'),
    ('Mar 2026', '2026-03-01'),
    ('2026-03', '2026-03-01'),
    ('2026', '2026-01-01'),
    (1772000000, '2026-02-25'),
    (1772000000000, '2026-02-25'),
    ('', ''),
    (None, ''),
    ('không rõ ngày', ''),
    ('2026-13-40', '2026-12-31'),  # tháng/ngày ngoài khoảng thì kẹp, không đoán bừa
])
def test_parse_date_normalises_and_never_guesses(value, expected):
    assert ev.parse_date(value) == expected


def test_survey_date_is_utc_and_model_cannot_guess_it():
    assert ev.survey_date(1772000000) == '2026-02-25'
    assert ev.survey_date('2026-01-02') == '2026-01-02'
    assert len(ev.survey_date()) == 10


@pytest.mark.parametrize('velocity,days', [('very-fast', 270), ('fast', 630), ('medium', 1460),
                                           ('slow', 3650), ('nhanh', 0), ('', 0), (None, 0)])
def test_window_days_follows_the_velocity_table(velocity, days):
    assert ev.window_days(velocity) == days


def test_window_bounds_walks_back_from_the_survey_date():
    bounds = ev.window_bounds('fast', as_of='2026-09-25')
    assert bounds == {'velocity': 'fast', 'days': 630, 'start': '2025-01-03', 'end': '2026-09-25'}
    assert ev.window_bounds('nope', as_of='2026-09-25')['days'] == 0


def test_window_bounds_of_a_period_shorter_than_270_days():
    assert ev.window_bounds('very-fast', as_of='2026-01-01')['start'] == '2025-04-06'


def test_date_in_window_needs_a_known_date_and_a_known_window():
    assert ev.date_in_window('2026-01-01', window_days=270, as_of='2026-09-25') is True
    assert ev.date_in_window('2020-01-01', window_days=270, as_of='2026-09-25') is False
    assert ev.date_in_window('', window_days=270, as_of='2026-09-25') is False
    assert ev.date_in_window('2026-01-01', window_days=0, as_of='2026-09-25') is False


def test_in_window_support_splits_and_counts():
    rows = [entry(claimId='c-in', publishedAt='2026-05-01'),
            entry(claimId='c-out', publishedAt='2019-01-01'),
            entry(claimId='c-none', publishedAt='')]
    support = ev.in_window_support(rows, window_days=630, as_of='2026-09-25')
    assert support['inWindow'] == ['c-in']
    assert support['outside'] == ['c-out']
    assert support['undated'] == ['c-none']
    assert support['counts'] == {'inWindow': 1, 'outside': 1, 'undated': 1, 'total': 3}


# --- gốc nguồn --------------------------------------------------------------

@pytest.mark.parametrize('entry_kwargs,expected', [
    ({'originCluster': 'arxiv:2401.1'}, 'arxiv:2401.1'),
    ({'payload': {'origin': 'Nature 2026'}}, 'nature 2026'),
    ({'payload': {'doi': '10.1234/AbC'}}, 'doi:10.1234/abc'),
    ({'payload': {'arxivId': '2401.12345v2'}}, 'arxiv:2401.12345v2'),
    ({'payload': {'pmid': '12345'}}, 'ncbi:12345'),
    ({'payload': {'openreview': 'abc123'}}, 'openreview:abc123'),
    ({'host': 'www.example.com'}, 'example.com'),
    ({'host': 'docs.example.co.uk'}, 'example.co.uk'),
    ({'host': 'a.b.c.example.com'}, 'example.com'),
    ({'url': 'https://www.nature.com/articles/x'}, 'nature.com'),
    ({'host': 'arxiv.org'}, 'arxiv.org'),
])
def test_origin_cluster_prefers_payload_then_registered_domain(entry_kwargs, expected):
    assert ev.origin_cluster(entry(**entry_kwargs)) == expected


def test_origin_cluster_of_a_bare_host_is_unknown():
    assert ev.origin_cluster(entry()) == ''
    assert ev.origin_cluster(None) == ''


def test_cluster_count_treats_same_origin_as_one_but_unknown_as_separate():
    rows = [entry(originCluster='arxiv:1'), entry(originCluster='arxiv:1'),
            entry(host='a.com'), entry(host='b.com'), entry()]
    assert ev.cluster_count(rows) == 4
    assert ev.clusters_of(rows) == ['arxiv:1', 'a.com', 'b.com', '']


# --- mức trần ---------------------------------------------------------------

def test_no_evidence_means_no_confidence():
    for claim_type in ('numeric', 'method', 'benchmark', 'trend', 'gap'):
        result = ev.confidence_cap(claim_type, [])
        assert result['cap'] == 'unknown'
        assert result['rule'] == 'no-evidence'


def test_inference_and_recommendation_carry_no_data_confidence():
    rows = [entry(tier=1, accessLevel='fulltext-read', publishedAt='2026-05-01')]
    for claim_type in ('inference', 'recommendation'):
        result = ev.confidence_cap(claim_type, rows)
        assert result['cap'] == 'unknown'
        assert result['rule'] == 'no-evidence-confidence'
        assert ev.is_inference(claim_type) is True


def test_two_independent_clusters_lift_a_number_to_high():
    rows = [entry(tier=2, accessLevel='abstract', originCluster='a.com'),
            entry(tier=2, accessLevel='abstract', originCluster='b.com')]
    result = ev.confidence_cap('numeric', rows)
    assert (result['cap'], result['rule']) == ('high', 'two-independent-clusters')
    assert result['basis']['clusters'] == 2


def test_one_rehashed_copy_is_still_one_source():
    rows = [entry(tier=2, accessLevel='abstract', originCluster='a.com', url='https://a.com/1'),
            entry(tier=2, accessLevel='abstract', originCluster='a.com', url='https://a.com/2')]
    result = ev.confidence_cap('numeric', rows)
    # Hai URL cùng một bài gốc: vẫn là một nguồn, trần không lên `high`.
    assert result['basis']['clusters'] == 1
    assert (result['cap'], result['rule']) == ('medium', 'abstract-only')


def test_primary_fulltext_beats_secondary_rule():
    rows = [entry(tier=1, accessLevel='fulltext-read', publishedAt='2026-05-01')]
    result = ev.confidence_cap('event', rows)
    assert (result['cap'], result['rule']) == ('high', 'primary-fulltext')


@pytest.mark.parametrize('rows,cap,rule', [
    ([entry(tier=2, accessLevel='abstract')], 'medium', 'abstract-only'),
    ([entry(tier=4, accessLevel='snippet')], 'low', 'tier4-only'),
    ([entry(tier=1, accessLevel='snippet')], 'low', 'snippet-only'),
])
def test_secondary_abstract_and_snippet_ladder(rows, cap, rule):
    result = ev.confidence_cap('current-fact', rows)
    assert (result['cap'], result['rule']) == (cap, rule)


def test_method_rules_need_the_method_section_in_full_text():
    fulltext = ev.confidence_cap('method', [entry(tier=1, accessLevel='fulltext-read',
                                                  sectionKind='method')])
    assert (fulltext['cap'], fulltext['rule']) == ('high', 'method-fulltext')
    abstract = ev.confidence_cap('method', [entry(tier=2, accessLevel='abstract')])
    assert (abstract['cap'], abstract['rule']) == ('medium', 'method-abstract')
    secondary = ev.confidence_cap('method', [entry(tier=3, accessLevel='snippet')])
    assert (secondary['cap'], secondary['rule']) == ('low', 'method-secondary')


def test_method_full_text_is_a_property_of_the_same_read():
    """Mục phương pháp ở hàng A và mức toàn văn ở hàng B KHÔNG phải \"đã đọc mục phương pháp\"."""
    mixed = [entry(claimId='c-section', sectionKind='method', accessLevel='abstract'),
             entry(claimId='c-read', sectionKind='', accessLevel='fulltext-read')]
    assert ev.confidence_cap('method', mixed)['rule'] != 'method-fulltext'
    single = [entry(claimId='c-1', sectionKind='method', accessLevel='fulltext-read')]
    assert ev.confidence_cap('method', single)['rule'] == 'method-fulltext'


def test_benchmark_needs_conditions_and_a_second_source_for_high():
    plain = [entry(tier=1, accessLevel='fulltext-read', sectionKind='results', sourceKind='paper')]
    assert ev.confidence_cap('benchmark', plain)['rule'] == 'benchmark-author-reported'
    strong = [entry(tier=1, accessLevel='fulltext-read', sectionKind='results', sourceKind='paper',
                    recordedConditions=True, independentReplication=True)]
    assert ev.confidence_cap('benchmark', strong)['rule'] == 'benchmark-conditions+replication'
    blog = ev.confidence_cap('benchmark', [entry(tier=4, sourceKind='blog')])
    assert (blog['cap'], blog['rule']) == ('low', 'benchmark-third-party-numbers')


def test_benchmark_high_needs_conditions_and_the_table_in_the_same_read():
    mixed = [entry(claimId='c-conditions', recordedConditions=True),
             entry(claimId='c-section', sectionKind='results', accessLevel='fulltext-read'),
             entry(claimId='c-replication', independentReplication=True, originCluster='c.com'),
             entry(claimId='c-access', accessLevel='fulltext-read', originCluster='d.com')]
    result = ev.confidence_cap('benchmark', mixed)
    assert result['rule'] != 'benchmark-conditions+replication'
    assert result['cap'] != 'high'
    single = [entry(claimId='c-1', sectionKind='results', accessLevel='fulltext-read',
                    recordedConditions=True, independentReplication=True)]
    assert ev.confidence_cap('benchmark', single)['rule'] == 'benchmark-conditions+replication'
    # Hai cụm vẫn là số hạng GỘP được, miễn là CÙNG một lần đọc đã có bảng + điều kiện.
    two_clusters = [entry(claimId='c-1', sectionKind='results', accessLevel='fulltext-read',
                          recordedConditions=True, originCluster='a.com'),
                    entry(claimId='c-2', originCluster='b.com')]
    assert ev.confidence_cap('benchmark', two_clusters)['rule'] == 'benchmark-conditions+replication'


def test_trend_uses_the_window_and_a_nearby_survey():
    rows = [entry(claimId='c-1', publishedAt='2026-05-01', originCluster='a.com', survey=True),
            entry(claimId='c-2', publishedAt='2026-06-01', originCluster='b.com')]
    high = ev.confidence_cap('trend', rows, window_days=630, as_of='2026-09-25')
    assert (high['cap'], high['rule']) == ('high', 'trend-window+survey')
    stale = ev.confidence_cap('trend', [entry(claimId='c-1', publishedAt='2019-01-01',
                                              originCluster='a.com'),
                                        entry(claimId='c-2', publishedAt='2019-02-01',
                                              originCluster='b.com')],
                              window_days=630, as_of='2026-09-25')
    assert stale['rule'] == 'trend-two-clusters'
    one = ev.confidence_cap('trend', [entry(originCluster='a.com')])
    assert (one['cap'], one['rule']) == ('low', 'trend-one-cluster')


def test_an_undeclared_time_window_never_lifts_a_trend_to_high():
    """`window_days = 0` (velocity chưa xác nhận) KHÔNG được coi là \"mọi hàng đều trong cửa sổ\"."""
    rows = [entry(claimId='c-2015', publishedAt='2015-06-01', originCluster='a.com', survey=True),
            entry(claimId='c-2016', publishedAt='2016-06-01', originCluster='b.com')]
    undeclared = ev.confidence_cap('trend', rows)
    declared = ev.confidence_cap('trend', rows, window_days=630, as_of='2026-09-25')
    assert undeclared['rule'] != 'trend-window+survey'
    assert undeclared['cap'] != 'high'
    # Chưa khai cửa sổ thì trần KHÔNG được tốt hơn trần khi đã khai (nguồn đều quá cũ).
    assert ev.CONFIDENCE_RANK[undeclared['cap']] <= ev.CONFIDENCE_RANK[declared['cap']]
    assert declared['rule'] == 'trend-two-clusters'


def test_gap_is_never_high():
    narrow = ev.confidence_cap('gap', [entry(sourceKind='blog')])
    assert (narrow['cap'], narrow['rule']) == ('low', 'gap-narrow')
    systematic = ev.confidence_cap('gap', [entry(systematicSearch=True)])
    assert (systematic['cap'], systematic['rule']) == ('medium', 'gap-systematic')


def test_market_ladder_caps_at_the_lowest_credible_step():
    assert ev.market_rank('marketing') == 3
    assert ev.market_rank('independent-report') == 5
    assert ev.market_rank('hồ sơ pháp lý') == 6
    assert ev.market_rank('không rõ') == 0
    assert ev.market_cap([entry(ladder='marketing')])['cap'] == 'low'
    assert ev.market_cap([entry(ladder='case-study')])['cap'] == 'medium'
    assert ev.market_cap([entry(ladder='legal')])['cap'] == 'high'
    assert ev.market_cap([])['rule'] == 'no-evidence'


def test_conflicting_evidence_is_contested_not_majority():
    rows = [entry(tier=1, accessLevel='fulltext-read'), entry(tier=1, accessLevel='fulltext-read')]
    result = ev.confidence_cap('numeric', rows, conflict=True)
    assert result['cap'] == 'contested'
    assert result['rule'] == 'contested-counter-evidence'


def test_apply_cap_only_lowers_and_keeps_contested():
    assert ev.apply_cap('high', 'low') == 'low'
    assert ev.apply_cap('low', 'high') == 'low'
    assert ev.apply_cap('unknown', 'high') == 'unknown'
    assert ev.apply_cap('high', 'contested') == 'contested'
    assert ev.apply_cap('contested', 'high') == 'contested'
    assert ev.apply_cap('lạ', 'medium') == 'unknown'


def test_undated_source_does_not_support_a_current_claim_at_high_confidence():
    rows = [entry(tier=1, accessLevel='fulltext-read', publishedAt='')]
    result = ev.confidence_cap('current-fact', rows, window_days=630, as_of='2026-09-25')
    assert result['basis']['inWindow'] == 0
    assert result['basis']['undated'] == 1
    assert result['rule'] == 'primary-fulltext'  # trần là full-text tầng 1, nhưng cửa sổ trống


# --- nhận định hiện trạng cũ ------------------------------------------------

def test_stale_current_claim_flags_only_out_of_window_current_facts():
    rows = [entry(publishedAt='2018-01-01'), entry(publishedAt='2019-01-01')]
    result = ev.stale_current_claim('current-fact', rows, window_days=630, as_of='2026-09-25')
    assert result == {'stale': True, 'rule': 'stale-current-claim', 'inWindow': 0, 'outside': 2,
                      'undated': 0}
    mixed = ev.stale_current_claim('current-fact', [entry(publishedAt='2026-05-01')],
                                   window_days=630, as_of='2026-09-25')
    assert mixed['stale'] is False
    assert ev.stale_current_claim('method', rows, window_days=630, as_of='2026-09-25')['stale'] is False
    assert ev.stale_current_claim('current-fact', [], window_days=630, as_of='2026-09-25')['stale'] is False
    assert ev.stale_current_claim('current-fact', [entry(publishedAt='')],
                                  window_days=630, as_of='2026-09-25')['stale'] is False


def test_stale_current_claim_short_circuits_when_the_window_is_undeclared():
    """Chưa khai cửa sổ thì không có \"ngoài cửa sổ\" nào để nói — không phán bừa `stale`."""
    rows = [entry(publishedAt='2018-01-01'), entry(publishedAt='2019-01-01')]
    unknown = ev.stale_current_claim('current-fact', rows, window_days=0, as_of='2026-09-25')
    assert unknown['stale'] is False
    assert unknown['rule'] == ''
    assert ev.stale_current_claim('current-fact', rows, window_days=-1)['stale'] is False
    declared = ev.stale_current_claim('current-fact', rows, window_days=630, as_of='2026-09-25')
    assert declared['stale'] is True and declared['rule'] == 'stale-current-claim'


# --- chuẩn hoá và gói basis -------------------------------------------------

@pytest.mark.parametrize('value,expected', [
    ('numeric', 'numeric'), ('current_fact', 'current-fact'), ('Statistic', 'numeric'),
    ('survey', 'trend'), ('lạ', 'inference'), (None, 'inference'),
])
def test_normalize_claim_type(value, expected):
    assert ev.normalize_claim_type(value) == expected
    assert ev.normalize_claim_type(expected) == expected


@pytest.mark.parametrize('value,expected', [
    ('', 'snippet'), (None, 'snippet'), ('ABSTRACT', 'abstract'), ('full-text-read', 'fulltext-read'),
    ('open', 'fulltext-available'), ('paywalled', 'snippet'), ('lạ', 'snippet'),
])
def test_normalize_access_level(value, expected):
    assert ev.normalize_access_level(value) == expected


def test_basis_payload_keeps_the_trail_for_the_claim_meta_row():
    rows = [entry(claimId='c-1', originCluster='a.com', tier=1, accessLevel='fulltext-read'),
            entry(claimId='c-2', originCluster='b.com', tier=2, accessLevel='abstract')]
    basis = ev.basis_payload('numeric', rows, rule='two-independent-clusters', extra={'run': 'R1'})
    assert basis['rule'] == 'two-independent-clusters'
    assert basis['clusters'] == 2
    assert basis['bestAccess'] == 'fulltext-read'
    assert basis['sources'] == 2
    assert basis['run'] == 'R1'
    assert basis['groups'] == {'a.com': ['c-1'], 'b.com': ['c-2']}
    assert len(ev.basis_payload('numeric', rows, rule='x')['groups']) == 2


def test_evidence_entries_never_raise_on_garbage():
    for bad in (None, 7, 'x', [None, 7, 'x'], {'claimId': 'c-1'}):
        assert isinstance(ev.entries(bad), list)
    assert ev.confidence_cap('numeric', 'rác')['cap'] == 'unknown'
    assert ev.cluster_count(None) == 0
    assert ev.in_window_support('rác', window_days=10)['counts']['total'] == 0
    assert ev.entry_date(None) == ''
    assert ev.normalize_source_kind('github') == 'repo'
    assert ev.normalize_stance('agent_proposal') == 'agent-proposal'
    assert ev.normalize_stance('lạ') == 'agent-inference'


def test_vocabulary_is_shared_with_the_limits_module():
    # Từ vựng đọc thẳng từ `source_pack.ACCESS_LEVELS` để cổng và sổ không lệch nhau.
    from agentbox.agent_core.source_pack import ACCESS_LEVELS
    assert ev.ACCESS_LEVELS == tuple(ACCESS_LEVELS)
    assert limits.RESEARCH_STALE_CURRENT_CLAIM_CODE == 'research-stale-current-claim'


# --- tầng lưu trữ của P2: sổ mở rộng, claim meta -----------------------------

@pytest.fixture()
def store(tmp_path):
    from agentbox.memory.session_store import SessionStore
    return SessionStore(tmp_path / 'sessions.sqlite')


def ledger_row(store, sid='S1', url='https://arxiv.org/abs/2401.00001', **extra):
    values = {'claim': 'Một nhận định', 'url': url, 'host': 'arxiv.org', 'tier': 1,
              'excerpt': 'x' * 120, 'research_id': 'R1'}
    values.update(extra)
    return store.source_add(sid, values)


def test_source_add_and_source_view_round_trip_the_new_columns(store):
    row = ledger_row(store, published_at='2026-01-02', source_kind='paper',
                     access_level='fulltext-read', section_kind='method', version_label='v3',
                     event_date='2026-01-05', origin_cluster='arxiv:2401.00001')
    assert row['publishedAt'] == '2026-01-02'
    assert row['sourceKind'] == 'paper'
    assert row['accessLevel'] == 'fulltext-read'
    assert row['sectionKind'] == 'method'
    assert row['versionLabel'] == 'v3'
    assert row['eventDate'] == '2026-01-05'
    assert row['originCluster'] == 'arxiv:2401.00001'
    assert row['researchId'] == 'R1'
    # Tên camelCase của harness cũng phải nhận (`publishedAt`…) — đường gọi cũ không đổi.
    other = ledger_row(store, url='https://a.example/x', publishedAt='2026-02-02',
                       sourceKind='blog', accessLevel='snippet')
    assert (other['publishedAt'], other['sourceKind']) == ('2026-02-02', 'blog')
    default = store.source_evidence_meta('S1', other['rowId'])
    assert default['accessLevel'] == 'snippet'


def test_evidence_link_enriches_an_existing_source_row(store):
    row = ledger_row(store, row_id='r1')
    store.evidence_link('S1', row['rowId'], 'Một nhận định', access_level='abstract',
                        origin_cluster='arxiv:2401.00001', research_id='R1')
    assert store.source_evidence_meta('S1', row['rowId'])['accessLevel'] == 'abstract'
    assert store.source_evidence_meta('S1', row['rowId'])['originCluster'] == 'arxiv:2401.00001'
    # Cùng nguồn, lượt đọc sau sâu hơn: hàng cũ đọc lại thấy mức CAO NHẤT đã biết của nguồn.
    later = ledger_row(store, row_id='r2', excerpt='z' * 120, access_level='fulltext-read')
    store.evidence_link('S1', later['rowId'], 'Nhận định khác', access_level='fulltext-read')
    enriched = store.source_evidence_meta('S1', row['rowId'])
    assert enriched['accessLevel'] == 'fulltext-read'
    assert enriched['originCluster'] == 'arxiv:2401.00001'


def test_evidence_claims_joins_claims_passages_and_sources(store):
    row = ledger_row(store, published_at='2026-03-02', source_kind='paper',
                     access_level='fulltext-read')
    link = store.evidence_link('S1', row['rowId'], 'Nhận định A', section_kind='results')
    store.source_add('S2', {'claim': 'Ngoài run', 'url': 'https://b.example/y', 'host': 'b.example',
                            'tier': 2, 'excerpt': 'y' * 120, 'research_id': 'R2'})
    other = store.evidence_link('S2', 'r1', 'Nhận định B')
    assert other['claimId'] != link['claimId']
    mine = store.evidence_claims('S1', 'R1')
    assert [item['claimId'] for item in mine] == [link['claimId']]
    assert mine[0]['sourceId'] == link['sourceId']
    assert mine[0]['tier'] == 1
    assert mine[0]['publishedAt'] == '2026-03-02'
    assert mine[0]['sectionKind'] == 'results'
    assert store.evidence_claims('S1', 'R2') == []
    assert store.evidence_claims('S1') and len(store.evidence_claims('S1')) == 1


def test_claim_meta_is_per_run_and_only_lowers_the_saved_ceiling(store):
    assert store.claim_meta('R1', 'c-1') == {}
    saved = store.claim_meta_save('R1', 'c-1', claimType='numeric', stanceOrigin='source-stated',
                                  confidence='high', confidenceCap='medium',
                                  basis={'rule': 'two-independent-clusters'}, asOf='2026-09-25')
    assert saved['claimId'] == 'c-1'
    assert saved['claimType'] == 'numeric'
    assert saved['confidenceCap'] == 'medium'
    assert saved['basis'] == {'rule': 'two-independent-clusters'}
    assert saved['asOf'] == '2026-09-25'
    # Trường không truyền giữ nguyên giá trị cũ (mô hình hạ mức là lần ghi khác).
    lowered = store.claim_meta_save('R1', 'c-1', confidence='low')
    assert lowered['confidence'] == 'low'
    assert lowered['confidenceCap'] == 'medium'
    assert lowered['basis'] == {'rule': 'two-independent-clusters'}
    same = store.claim_meta_save('R1', 'c-1')
    assert same['confidence'] == 'low'
    listed = store.claim_meta_list('R1')
    assert [item['claimId'] for item in listed] == ['c-1']
    assert {key: value for key, value in listed[0].items() if key != 'updated'} == (
        {key: value for key, value in lowered.items() if key != 'updated'})
    assert store.claim_meta_list('R2') == []


def test_claim_meta_upsert_many_skips_items_without_a_claim_id(store):
    written = store.claim_meta_upsert_many('R1', [{'claimId': 'c-1', 'claimType': 'event'},
                                                  {'claim_id': 'c-2', 'confidence': 'low'},
                                                  {'khong': 'co claim id'}, 'rác', None])
    assert written == 2
    assert [item['claimId'] for item in store.claim_meta_list('R1')] == ['c-1', 'c-2']
    assert store.claim_meta('R1', 'c-2')['claimType'] == 'inference'


def test_claim_meta_save_refuses_a_row_without_a_key(store):
    with pytest.raises(ValueError) as error:
        store.claim_meta_save('', 'c-1')
    assert str(error.value) == 'RESEARCH_CLAIM_META_KEY'
    with pytest.raises(ValueError):
        store.claim_meta_save('R1', '')


def test_evidence_link_still_refuses_an_unknown_row(store):
    with pytest.raises(ValueError) as error:
        store.evidence_link('S1', 'r-không-có', 'Nhận định')
    assert str(error.value) == 'RESEARCH_EVIDENCE_ROW_UNKNOWN'
    assert store.source_evidence_meta('S1', 'r-không-có') == {}


def test_a_claim_keeps_its_own_depth_and_the_source_keeps_the_best(store):
    """Trần độ tin cậy tính theo ĐOẠN mà nhận định dựa vào, không theo lượt đọc sâu nhất của nguồn."""
    shallow = ledger_row(store, row_id='r1', excerpt='a' * 120, access_level='abstract')
    store.evidence_link('S1', shallow['rowId'], 'Nhận định A', access_level='abstract')
    deep = ledger_row(store, row_id='r2', excerpt='b' * 120, access_level='fulltext-read')
    store.evidence_link('S1', deep['rowId'], 'Nhận định B', access_level='fulltext-read')
    levels = {item['text']: (item['accessLevel'], item['sourceAccessLevel'])
              for item in store.evidence_claims('S1', 'R1')}
    assert levels['Nhận định A'] == ('abstract', 'fulltext-read')
    assert levels['Nhận định B'] == ('fulltext-read', 'fulltext-read')
    assert store.source_evidence_meta('S1', shallow['rowId'])['accessLevel'] == 'fulltext-read'
