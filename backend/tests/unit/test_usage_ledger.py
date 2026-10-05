"""Fixture offline cho UsageLedger: SQLite tạm, không model, không mạng.

Mỗi test bám một bất biến trong H6: unknown ≠ 0, consent/ceiling fail closed,
idempotent theo call_key/invocation, reasoning/cache tách khe, settle/release và
reconcile không viết lại lịch sử, schema lạ bị từ chối.
"""
import json

import pytest

from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.usage_ledger import (
    CERTAINTIES, UsageLedger, clear_prices, price_snapshot, register_price, reserve_decision,
)
from agentbox.memory.session_store import SessionStore

OWNER = 'owner-1'


@pytest.fixture(autouse=True)
def _price_book():
    clear_prices()
    yield
    clear_prices()


@pytest.fixture
def ledger(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    yield store, UsageLedger(store)
    store.close()


def error(code, call):
    with pytest.raises(ContractError) as exc:
        call()
    assert exc.value.code == code
    return exc.value


def reserve(ledger, allocation_id='alloc-1', **updates):
    args = {'allocation_id': allocation_id, 'owner_id': OWNER, 'policy_revision': 1,
            'consent_ref': 'consent-1', 'reservation': {'amount': 1.0, 'ceiling': 2.0},
            'invocation_id': 'inv-' + allocation_id}
    args.update(updates)
    return ledger.reserve(**args)


def record(ledger, call_key='call-1', **usage):
    return ledger.record(call_key, OWNER, **usage)


def price(input_price=1.0, output_price=2.0, source='ping', **updates):
    value = {'source': source, 'input': input_price, 'output': output_price}
    value.update(updates)
    return value


def allocation_count(store):
    return store.db.execute('SELECT COUNT(*) FROM harness_allocations').fetchone()[0]


def usage_count(store):
    return store.db.execute('SELECT COUNT(*) FROM harness_usage').fetchone()[0]


# --- Bất biến 1: unknown là None, không bao giờ 0 -------------------------------------------

def test_certainties_are_exactly_three_states():
    assert CERTAINTIES == ('known', 'estimated', 'unknown')


def test_unknown_price_records_none_never_zero(ledger):
    store, ledger = ledger
    result = record(ledger, input_tokens=10, output_tokens=5)
    assert result['amount'] is None and result['certainty'] == 'unknown'
    assert result['priceSnapshot'] is None and result['currency'] is None
    row = store.db.execute('SELECT amount, certainty FROM harness_usage').fetchone()
    assert row['amount'] is None and row['certainty'] == 'unknown'


def test_free_price_needs_a_confirmed_source(ledger):
    store, ledger = ledger
    with pytest.raises(ContractError):
        record(ledger, input_tokens=10, output_tokens=5, price={'input': 0.0, 'output': 0.0})
    assert usage_count(store) == 0
    free = record(ledger, input_tokens=10, output_tokens=5,
                  price={'source': 'documented', 'input': 0.0, 'output': 0.0})
    assert free['amount'] == 0.0 and free['certainty'] == 'estimated'


def test_aggregate_keeps_unknown_separate_from_known_and_estimated(ledger):
    _, ledger = ledger
    record(ledger, 'call-known', amount=1.5, certainty='known')
    record(ledger, 'call-estimated', amount=0.5)
    record(ledger, 'call-unknown', input_tokens=7)
    report = ledger.aggregate(OWNER)
    groups = {(group['currency'], group['certainty']): group for group in report['groups']}
    assert groups[('USD', 'known')]['amount'] == 1.5
    assert groups[('USD', 'estimated')]['amount'] == 0.5
    assert groups[(None, 'unknown')]['amount'] is None
    assert report['calls'] == 3 and report['unknownCalls'] == 1


def test_aggregate_sums_per_currency(ledger):
    _, ledger = ledger
    record(ledger, 'call-usd', amount=1.0, certainty='known', currency='USD')
    record(ledger, 'call-eur', amount=2.0, certainty='known', currency='EUR')
    groups = {(group['currency'], group['certainty']): group for group in ledger.aggregate(OWNER)['groups']}
    assert groups[('USD', 'known')]['amount'] == 1.0
    assert groups[('EUR', 'known')]['amount'] == 2.0


# --- Bất biến 2: reserve_decision -----------------------------------------------------------

@pytest.mark.parametrize('unknown', [
    None, {}, {'input': 1.0, 'output': 2.0}, {'amount': 2.0},
    {'upperEstimate': {'amount': 2.0}}, {'upperEstimate': {'source': 'guess'}},
])
def test_reserve_decision_unknown_price_blocked(unknown):
    decision = reserve_decision(unknown, 5.0)
    assert decision['allowed'] is False and decision['reason'] == 'USAGE_PRICE_UNKNOWN'
    assert decision['amount'] is None


def test_reserve_decision_upper_estimate_with_source_allowed():
    decision = reserve_decision({'upperEstimate': {'amount': 2.0, 'source': 'vendor-page'}}, 3.0)
    assert decision['allowed'] is True and decision['reason'] == 'USAGE_UPPER_ESTIMATE'
    assert decision['certainty'] == 'estimated' and decision['amount'] == 2.0
    assert decision['basis'] == 'vendor-page' and decision['currency'] == 'USD'


def test_reserve_decision_none_ceiling_is_no_consent():
    assert reserve_decision(None, None)['reason'] == 'USAGE_NO_CONSENT'
    decision = reserve_decision({'amount': 1.0, 'source': 'manual'}, None)
    assert decision['allowed'] is False and decision['reason'] == 'USAGE_NO_CONSENT'
    assert decision['ceiling'] is None


def test_reserve_decision_ceiling_boundary_and_free_with_source():
    assert reserve_decision({'amount': 4.0, 'source': 'manual'}, 4.0)['allowed'] is True
    exceeded = reserve_decision({'amount': 4.01, 'source': 'manual'}, 4.0)
    assert exceeded['allowed'] is False and exceeded['reason'] == 'USAGE_CEILING_EXCEEDED'
    free = reserve_decision({'amount': 0.0, 'source': 'documented'}, 0.0)
    assert free['allowed'] is True and free['certainty'] == 'known' and free['amount'] == 0.0


# --- Bất biến 3: reserve atomic, idempotent, cần consent/ceiling ----------------------------

def test_reserve_requires_consent_and_ceiling(ledger):
    store, ledger = ledger
    error('USAGE_NO_CONSENT', lambda: reserve(ledger, consent_ref=None))
    error('USAGE_NO_CONSENT', lambda: reserve(ledger, reservation={'amount': 1.0}))
    error('USAGE_NO_CONSENT', lambda: reserve(ledger, reservation={'amount': 1.0, 'ceiling': None}))
    assert allocation_count(store) == 0


def test_reserve_idempotent_and_conflicts(ledger):
    store, ledger = ledger
    first = reserve(ledger)
    assert reserve(ledger) == first
    error('USAGE_ALLOCATION_CONFLICT', lambda: reserve(ledger, invocation_id='inv-other'))
    error('USAGE_ALLOCATION_CONFLICT',
          lambda: reserve(ledger, reservation={'amount': 0.5, 'ceiling': 2.0}))
    error('USAGE_ALLOCATION_CONFLICT', lambda: reserve(ledger, owner_id='owner-2'))
    assert allocation_count(store) == 1


def test_reserve_exceeding_ceiling_is_atomic(ledger):
    store, ledger = ledger
    error('USAGE_CEILING_EXCEEDED',
          lambda: reserve(ledger, reservation={'amount': 3.0, 'ceiling': 2.0}))
    assert allocation_count(store) == 0


def test_reserve_replays_from_a_second_connection(ledger, tmp_path):
    store, first = ledger
    other = SessionStore(tmp_path / 'sessions.db')
    try:
        second = UsageLedger(other)
        assert second.reserve('alloc-1', OWNER, 1, 'consent-1',
                              {'amount': 1.0, 'ceiling': 2.0}, 'inv-alloc-1') == first.reserve(
            'alloc-1', OWNER, 1, 'consent-1', {'amount': 1.0, 'ceiling': 2.0}, 'inv-alloc-1')
        assert allocation_count(store) == 1
    finally:
        other.close()


def test_child_reservation_draws_from_parent_remaining(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 10.0, 'ceiling': 10.0})
    child = reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
                    reservation={'amount': 6.0, 'ceiling': 6.0})
    assert child['consentRef'] == 'consent-1' and child['parentId'] == 'alloc-1'
    error('USAGE_CEILING_EXCEEDED',
          lambda: reserve(ledger, allocation_id='child-2', parent_id='alloc-1',
                          reservation={'amount': 6.0, 'ceiling': 6.0}))
    assert allocation_count(store) == 2


def test_child_cannot_exceed_its_own_ceiling(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 10.0, 'ceiling': 10.0})
    error('USAGE_CEILING_EXCEEDED',
          lambda: reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
                          reservation={'amount': 5.0, 'ceiling': 3.0}))
    assert allocation_count(store) == 1


def test_child_inherits_consent_and_currency_must_match(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    child = reserve(ledger, allocation_id='child-1', parent_id='alloc-1', consent_ref=None,
                    reservation={'amount': 0.5})
    assert child['consentRef'] == 'consent-1'
    error('USAGE_FIELD_INVALID',
          lambda: reserve(ledger, allocation_id='child-2', parent_id='alloc-1',
                          reservation={'amount': 0.5, 'currency': 'EUR'}))
    assert allocation_count(store) == 2


def test_child_consent_must_match_parent(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    error('USAGE_FIELD_INVALID',
          lambda: reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
                          consent_ref='consent-2', reservation={'amount': 0.5}))
    assert allocation_count(store) == 1
    inherited = reserve(ledger, allocation_id='child-2', parent_id='alloc-1', consent_ref=None,
                        reservation={'amount': 0.5})
    assert inherited['consentRef'] == 'consent-1'
    repeated = reserve(ledger, allocation_id='child-3', parent_id='alloc-1',
                       reservation={'amount': 0.5})
    assert repeated['consentRef'] == 'consent-1'
    assert allocation_count(store) == 3


def test_child_of_closed_parent_rejected(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    ledger.settle('alloc-1', {'amount': 1.0})
    error('USAGE_ALLOCATION_CLOSED',
          lambda: reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
                          reservation={'amount': 0.1}))
    assert allocation_count(store) == 1


def test_reserve_runs_price_decision_and_requires_covering_bound(ledger):
    store, ledger = ledger
    error('USAGE_PRICE_UNKNOWN',
          lambda: reserve(ledger, reservation={'amount': 1.0, 'ceiling': 2.0,
                                               'price': {'input': 1.0, 'output': 2.0}}))
    allowed = reserve(ledger, reservation={'amount': 1.0, 'ceiling': 2.0,
                                           'price': {'upperEstimate': {'amount': 0.8,
                                                                       'source': 'estimate-note'}}})
    assert allowed['reservation']['price']['upperEstimate']['amount'] == 0.8
    error('USAGE_CEILING_EXCEEDED',
          lambda: reserve(ledger, allocation_id='alloc-2',
                          reservation={'amount': 0.5, 'ceiling': 2.0,
                                       'price': {'upperEstimate': {'amount': 0.8,
                                                                   'source': 'estimate-note'}}}))
    assert allocation_count(store) == 1


def test_get_allocation_view_and_unknown(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 2.0})
    view = ledger.get_allocation('alloc-1')
    assert view['state'] == 'reserved' and view['remaining'] == 1.0
    assert view['reservation']['ceiling'] == 2.0 and view['reservation']['amount'] == 1.0
    error('USAGE_ALLOCATION_UNKNOWN', lambda: ledger.get_allocation('missing'))
    error('USAGE_ALLOCATION_UNKNOWN', lambda: ledger.settle('missing', {'amount': 1.0}))
    error('USAGE_ALLOCATION_UNKNOWN', lambda: ledger.release('missing', 1.0, 'x'))


# --- Bất biến 4: record idempotent theo call_key --------------------------------------------

def test_record_replay_and_conflict(ledger):
    store, ledger = ledger
    first = record(ledger, input_tokens=10, output_tokens=5, run_id='run-1')
    assert record(ledger, input_tokens=10, output_tokens=5, run_id='run-1') == first
    error('USAGE_CALL_CONFLICT',
          lambda: record(ledger, input_tokens=11, output_tokens=5, run_id='run-1'))
    error('USAGE_CALL_CONFLICT',
          lambda: ledger.record('call-1', 'owner-2', input_tokens=10, output_tokens=5, run_id='run-1'))
    assert usage_count(store) == 1


def test_repeated_call_does_not_double_count_aggregate(ledger):
    _, ledger = ledger
    record(ledger, amount=2.0, certainty='known')
    record(ledger, amount=2.0, certainty='known')
    report = ledger.aggregate(OWNER)
    assert report['calls'] == 1 and report['groups'][0]['amount'] == 2.0


def test_record_aliases_and_field_validation(ledger):
    store, ledger = ledger
    result = record(ledger, inputTokens=10, outputTokens=5, reasoningTokens=2, providerId='p',
                    modelId='m', routeRevision='r1', taskKey='t1', jobId='j1', attemptId='a1',
                    purpose='produce', requested={'maxTokens': 100}, effective={'maxTokens': 80})
    assert result['inputTokens'] == 10 and result['providerId'] == 'p'
    assert result['requested'] == {'maxTokens': 100} and result['effective'] == {'maxTokens': 80}
    error('USAGE_FIELD_INVALID', lambda: record(ledger, 'call-2', input_tokens=1, inputTokens=2))
    error('USAGE_FIELD_INVALID', lambda: record(ledger, 'call-3', tokens=5))
    error('USAGE_FIELD_INVALID', lambda: record(ledger, 'call-4', input_tokens=-1))
    error('USAGE_FIELD_INVALID', lambda: record(ledger, 'call-5', input_tokens=True))
    error('USAGE_FIELD_INVALID', lambda: record(ledger, 'call-6', amount=-0.1))
    error('USAGE_CERTAINTY_INVALID', lambda: record(ledger, 'call-7', certainty='known'))
    error('USAGE_CERTAINTY_INVALID', lambda: record(ledger, 'call-8', amount=1.0, certainty='unknown'))
    error('USAGE_CERTAINTY_INVALID', lambda: record(ledger, 'call-9', amount=1.0, certainty='guessed'))
    known = record(ledger, 'call-10', amount=1.0, certainty='known', currency='EUR')
    assert known['certainty'] == 'known' and known['currency'] == 'EUR'
    assert usage_count(store) == 2


# --- Bất biến 5: reasoning và cache tách khe ------------------------------------------------

def test_reasoning_tokens_stored_separately_not_double_counted(ledger):
    _, ledger = ledger
    result = record(ledger, input_tokens=100, output_tokens=20, reasoning_tokens=500)
    assert (result['inputTokens'], result['outputTokens'], result['reasoningTokens']) == (100, 20, 500)
    group = ledger.aggregate(OWNER)['groups'][0]
    assert group['inputTokens'] == 100 and group['outputTokens'] == 20
    assert group['reasoningTokens'] == 500
    assert group['inputTokens'] + group['outputTokens'] == 120


def test_cached_tokens_read_and_write_stay_separate(ledger):
    _, ledger = ledger
    result = record(ledger, input_tokens=100, output_tokens=20,
                    cached_tokens={'read': 30, 'write': 10})
    assert result['cachedTokens'] == {'read': 30, 'write': 10}
    group = ledger.aggregate(OWNER)['groups'][0]
    assert group['cachedReadTokens'] == 30 and group['cachedWriteTokens'] == 10
    alias = record(ledger, 'call-2', input_tokens=1,
                   cached_tokens={'cache_read_input_tokens': 4, 'cache_creation_input_tokens': 2})
    assert alias['cachedTokens'] == {'read': 4, 'write': 2}
    error('USAGE_FIELD_INVALID',
          lambda: record(ledger, 'call-3', cached_tokens={'read': 1, 'cached': 2}))


def test_amount_computed_from_price_tokens_and_cache(ledger):
    _, ledger = ledger
    plain = record(ledger, 'call-1', input_tokens=1_000_000, output_tokens=500_000,
                   price=price(1.0, 2.0))
    assert plain['amount'] == 2.0 and plain['certainty'] == 'estimated'
    assert plain['currency'] == 'USD'
    cached = record(ledger, 'call-2', input_tokens=1_000_000, output_tokens=0,
                    cached_tokens={'read': 250_000},
                    price=price(1.0, 2.0, cachedInput=0.5))
    # 750k miss × 1.0 + 250k cache read × 0.5 = 0.875 USD
    assert cached['amount'] == 0.875


def test_known_price_with_missing_tokens_stays_unknown(ledger):
    _, ledger = ledger
    result = record(ledger, price=price())
    assert result['amount'] is None and result['certainty'] == 'unknown'
    assert result['priceSnapshot']['source'] == 'ping'


# --- Bất biến 6: settle/release/reconcile ---------------------------------------------------

def test_settle_then_release_for_cancelled_child(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 2.0, 'ceiling': 2.0})
    reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
            reservation={'amount': 1.0, 'ceiling': 1.0})
    settled = ledger.settle('child-1', {'amount': 0.3, 'usage': {'output_tokens': 10}})
    assert settled['state'] == 'settled' and settled['consumed']['amount'] == 0.3
    assert settled['remaining'] == 0.7
    released = ledger.release('child-1', 0.7, 'child cancelled')
    assert released['state'] == 'released' and released['consumed']['releasedAmount'] == 0.7
    assert released['remaining'] == 0.0
    assert ledger.get_allocation('alloc-1')['state'] == 'reserved'
    assert allocation_count(store) == 2


def test_settle_and_release_idempotent_by_invocation(ledger):
    _, ledger = ledger
    reserve(ledger)
    ledger.settle('alloc-1', {'amount': 0.3}, invocation_id='settle-1')
    replay = ledger.settle('alloc-1', {'amount': 0.3}, invocation_id='settle-1')
    assert replay['consumed']['amount'] == 0.3
    error('USAGE_INVOCATION_CONFLICT',
          lambda: ledger.settle('alloc-1', {'amount': 0.4}, invocation_id='settle-1'))
    ledger.release('alloc-1', 0.7, 'done', invocation_id='release-1')
    assert ledger.release('alloc-1', 0.7, 'done', invocation_id='release-1')['state'] == 'released'
    error('USAGE_INVOCATION_CONFLICT',
          lambda: ledger.release('alloc-1', 0.1, 'done', invocation_id='release-1'))


def test_settle_replays_any_earlier_invocation(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    ledger.settle('alloc-1', {'amount': 0.4}, invocation_id='settle-A')
    ledger.settle('alloc-1', {'amount': 0.6}, invocation_id='settle-B')
    replay = ledger.settle('alloc-1', {'amount': 0.4}, invocation_id='settle-A')
    assert replay['consumed']['amount'] == 0.4      # không viết lại số đã chốt
    assert replay['consumed']['lateAmount'] == 0.2
    error('USAGE_INVOCATION_CONFLICT',
          lambda: ledger.settle('alloc-1', {'amount': 0.5}, invocation_id='settle-A'))
    assert ledger.get_allocation('alloc-1')['consumed']['amount'] == 0.4


def test_release_replays_any_earlier_invocation(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    ledger.release('alloc-1', 0.4, 'first', invocation_id='release-A')
    ledger.release('alloc-1', 0.2, 'second', invocation_id='release-B')
    replay = ledger.release('alloc-1', 0.4, 'first', invocation_id='release-A')
    assert replay['consumed']['releasedAmount'] == 0.6
    assert len(replay['consumed']['releases']) == 2
    error('USAGE_INVOCATION_CONFLICT',
          lambda: ledger.release('alloc-1', 0.3, 'first', invocation_id='release-A'))
    assert ledger.get_allocation('alloc-1')['consumed']['releasedAmount'] == 0.6


def test_parent_settle_rejects_while_child_holds_budget(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 10.0, 'ceiling': 10.0})
    reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
            reservation={'amount': 6.0, 'ceiling': 6.0})
    error('USAGE_SETTLE_EXCEEDS', lambda: ledger.settle('alloc-1', {'amount': 10.0}))
    row = store.db.execute('SELECT consumed_json, state FROM harness_allocations '
                           'WHERE allocation_id=?', ('alloc-1',)).fetchone()
    stored = json.loads(row['consumed_json'])
    assert stored['amount'] is None and stored['releasedAmount'] == 0.0
    assert stored['invocations'] == {} and stored['releases'] == []
    assert row['state'] == 'reserved'
    error('USAGE_SETTLE_EXCEEDS', lambda: ledger.settle('alloc-1', {'amount': 4.01}))
    root = ledger.settle('alloc-1', {'amount': 4.0})
    assert root['consumed']['amount'] == 4.0 and root['remaining'] == 0.0
    child = ledger.settle('child-1', {'amount': 6.0})
    assert child['consumed']['amount'] == 6.0
    error('USAGE_SETTLE_EXCEEDS', lambda: ledger.settle('alloc-1', {'amount': 4.01}))


def test_parent_release_cannot_free_held_child_budget(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 10.0, 'ceiling': 10.0})
    reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
            reservation={'amount': 6.0, 'ceiling': 6.0})
    error('USAGE_RELEASE_EXCEEDS', lambda: ledger.release('alloc-1', 4.01, 'too much'))
    released = ledger.release('alloc-1', 4.0, 'parent shrink')
    assert released['consumed']['releasedAmount'] == 4.0 and released['remaining'] == 0.0
    error('USAGE_RELEASE_EXCEEDS', lambda: ledger.release('alloc-1', 0.01, 'again'))
    # con trả lại phần chưa dùng thì cha mở lại đúng phần đó, không hơn
    ledger.settle('child-1', {'amount': 2.0})
    ledger.release('child-1', 4.0, 'child done')
    assert ledger.get_allocation('alloc-1')['remaining'] == 4.0
    closed = ledger.release('alloc-1', 4.0, 'parent done')
    assert closed['remaining'] == 0.0
    error('USAGE_RELEASE_EXCEEDS', lambda: ledger.release('alloc-1', 0.01, 'again'))


def test_view_remaining_matches_child_reserve_admission(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 10.0, 'ceiling': 10.0})
    reserve(ledger, allocation_id='child-1', parent_id='alloc-1',
            reservation={'amount': 6.0, 'ceiling': 6.0})
    assert ledger.get_allocation('alloc-1')['remaining'] == 4.0
    admitted = reserve(ledger, allocation_id='child-2', parent_id='alloc-1',
                       reservation={'amount': 4.0, 'ceiling': 4.0})
    assert admitted['remaining'] == 4.0
    assert ledger.get_allocation('alloc-1')['remaining'] == 0.0
    error('USAGE_CEILING_EXCEEDED',
          lambda: reserve(ledger, allocation_id='child-3', parent_id='alloc-1',
                          reservation={'amount': 0.01}))


def test_settle_exceeds_reservation_blocked(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    error('USAGE_SETTLE_EXCEEDS', lambda: ledger.settle('alloc-1', {'amount': 1.5}))
    assert ledger.get_allocation('alloc-1')['state'] == 'reserved'
    assert allocation_count(store) == 1


def test_settle_unknown_usage_keeps_unsettled_liability(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    result = ledger.settle('alloc-1', {'amount': None})
    assert result['state'] == 'unsettled' and result['consumed']['amount'] is None
    assert result['remaining'] is None
    error('USAGE_UNSETTLED', lambda: ledger.release('alloc-1', 0.5, 'free it'))
    assert ledger.unsettled(OWNER)[0]['liability'] == {'amount': None, 'reason': 'usage_unknown'}
    late = ledger.settle('alloc-1', {'amount': 0.4})
    assert late['state'] == 'settled' and late['consumed']['amount'] == 0.4


def test_late_usage_reconciles_without_rewriting_history(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    ledger.settle('alloc-1', {'amount': 0.3})
    late = ledger.settle('alloc-1', {'amount': 0.5})
    assert late['consumed']['amount'] == 0.3        # không viết lại số đã chốt
    assert late['consumed']['lateAmount'] == 0.2
    report = ledger.reconcile(OWNER)
    assert report['lateAmount'] == 0.2
    assert report['unsettledAmount'] == 0.9         # 0.7 chưa release + 0.2 đến muộn
    stored = store.db.execute('SELECT consumed_json FROM harness_allocations').fetchone()['consumed_json']
    ledger.reconcile(OWNER)
    ledger.reconcile(OWNER)
    assert store.db.execute('SELECT consumed_json FROM harness_allocations').fetchone()['consumed_json'] == stored
    assert ledger.get_allocation('alloc-1')['state'] == 'settled'


def test_late_usage_smaller_than_settled_rejected(ledger):
    _, ledger = ledger
    reserve(ledger)
    ledger.settle('alloc-1', {'amount': 0.5})
    error('USAGE_SETTLE_CONFLICT', lambda: ledger.settle('alloc-1', {'amount': 0.4}))
    assert ledger.get_allocation('alloc-1')['consumed']['amount'] == 0.5


def test_release_exceeds_and_full_release_closes(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    error('USAGE_RELEASE_EXCEEDS', lambda: ledger.release('alloc-1', 1.5, 'too much'))
    partial = ledger.release('alloc-1', 0.4, 'shrink')
    assert partial['state'] == 'reserved' and partial['consumed']['releasedAmount'] == 0.4
    full = ledger.release('alloc-1', 0.6, 'cancel')
    assert full['state'] == 'released'
    error('USAGE_RELEASE_EXCEEDS', lambda: ledger.release('alloc-1', 0.1, 'again'))


def test_reconcile_reports_unknown_usage_never_free(ledger):
    _, ledger = ledger
    record(ledger, 'call-unknown', input_tokens=5)
    record(ledger, 'call-known', amount=1.0, certainty='known')
    report = ledger.reconcile(OWNER)
    assert report['unknownCalls'] == 1
    assert report['unknownUsage'][0]['callKey'] == 'call-unknown'
    assert report['unknownUsage'][0]['amount'] is None
    assert report['unsettledAmount'] == 0.0


def test_unsettled_lists_reserved_and_late_allocations(ledger):
    _, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    items = ledger.unsettled(OWNER)
    assert items[0]['liability'] == {'amount': 1.0, 'reason': 'unsettled_reservation'}
    ledger.settle('alloc-1', {'amount': 0.2})
    assert ledger.unsettled(OWNER)[0]['liability'] == {'amount': 0.8, 'reason': 'unreleased_remainder'}
    ledger.release('alloc-1', 0.8, 'done')
    assert ledger.unsettled(OWNER) == []


# --- Bất biến 7: lịch sử giá không bị viết lại ----------------------------------------------

def test_new_price_does_not_rewrite_stored_snapshot_or_amount(ledger):
    store, ledger = ledger
    first = record(ledger, 'call-1', input_tokens=1_000_000, output_tokens=0, price=price(1.0, 2.0))
    second = record(ledger, 'call-2', input_tokens=1_000_000, output_tokens=0, price=price(9.0, 2.0))
    assert first['amount'] == 1.0 and second['amount'] == 9.0
    register_price('opencode', 'm1', price(50.0, 60.0), recorded_at=99)
    stored = ledger.calls(OWNER, limit=1)['items'][0]
    assert stored['priceSnapshot']['input'] == 1.0 and stored['amount'] == 1.0


def test_price_snapshot_history_and_unknown():
    register_price('opencode', 'm1', price(1.0, 2.0, asOf='2026-01-01'), recorded_at=1000)
    register_price('opencode', 'm1', price(2.0, 4.0, asOf='2026-06-01'), recorded_at=2000)
    assert price_snapshot('opencode', 'm1')['input'] == 2.0
    assert price_snapshot('opencode', 'm1', as_of='2026-03-01')['input'] == 1.0
    assert price_snapshot('opencode', 'm1', as_of=1500)['input'] == 1.0
    assert price_snapshot('opencode', 'm1', as_of=500) is None
    assert price_snapshot('opencode', 'm2') is None
    snapshot = price_snapshot('opencode', 'm1')
    assert snapshot['source'] == 'ping' and snapshot['known'] is True
    assert snapshot['unit'] == 'per_million_tokens' and snapshot['currency'] == 'USD'
    snapshot['input'] = 999.0
    assert price_snapshot('opencode', 'm1')['input'] == 2.0
    register_price('opencode', 'm1', price(9.0, 9.0, source='manual'), route_revision='route-b',
                   recorded_at=3000)
    assert price_snapshot('opencode', 'm1', route_revision='route-b')['input'] == 9.0
    assert price_snapshot('opencode', 'm1')['input'] == 2.0
    with pytest.raises(ContractError):
        price_snapshot('opencode', 'm1', as_of='not-a-date')


def test_price_snapshot_never_invents_free_price():
    with pytest.raises(ContractError):
        register_price('opencode', 'free', {'input': 0.0, 'output': 0.0})
    assert price_snapshot('opencode', 'free') is None
    register_price('opencode', 'free', {'source': 'documented', 'input': 0.0, 'output': 0.0})
    snapshot = price_snapshot('opencode', 'free')
    assert snapshot['input'] == 0.0 and snapshot['source'] == 'documented'


# --- Bất biến 8 + phân trang + schema fail closed -------------------------------------------

def test_calls_pagination_and_filters(ledger):
    _, ledger = ledger
    for index in range(5):
        record(ledger, f'call-{index}', run_id='run-1' if index < 3 else 'run-2', amount=0.1)
    page = ledger.calls(OWNER, limit=2)
    assert [item['callKey'] for item in page['items']] == ['call-0', 'call-1']
    assert page['hasMore'] is True and page['nextCursor'] == 'call-1'
    second = ledger.calls(OWNER, cursor=page['nextCursor'], limit=2)
    assert [item['callKey'] for item in second['items']] == ['call-2', 'call-3']
    third = ledger.calls(OWNER, cursor=second['nextCursor'], limit=2)
    assert [item['callKey'] for item in third['items']] == ['call-4'] and third['hasMore'] is False
    assert len(ledger.calls(OWNER, run_id='run-2')['items']) == 2
    assert ledger.calls('owner-2')['items'] == []
    with pytest.raises(ContractError):
        ledger.calls(OWNER, limit=0)
    with pytest.raises(ContractError):
        ledger.calls(OWNER, limit=101)
    with pytest.raises(ContractError):
        ledger.calls(OWNER, cursor='../bad')


def test_corrupt_allocation_json_fails_closed(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    store.db.execute("UPDATE harness_allocations SET consumed_json='not-json' "
                     "WHERE allocation_id='alloc-1'")
    error('USAGE_RECORD_CORRUPT', lambda: ledger.get_allocation('alloc-1'))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.unsettled(OWNER))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.settle('alloc-1', {'amount': 0.1}))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.release('alloc-1', 0.1, 'x'))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.reconcile(OWNER))
    store.db.execute("UPDATE harness_allocations SET consumed_json='{}', reservation_json='not-json' "
                     "WHERE allocation_id='alloc-1'")
    error('USAGE_RECORD_CORRUPT', lambda: ledger.get_allocation('alloc-1'))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.settle('alloc-1', {'amount': 0.1}))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.release('alloc-1', 0.1, 'x'))


def test_corrupt_child_json_fails_closed_through_parent_hold(ledger):
    store, ledger = ledger
    reserve(ledger, reservation={'amount': 1.0, 'ceiling': 1.0})
    reserve(ledger, allocation_id='child-1', parent_id='alloc-1', reservation={'amount': 0.5})
    store.db.execute("UPDATE harness_allocations SET reservation_json='not-json' "
                     "WHERE allocation_id='child-1'")
    error('USAGE_RECORD_CORRUPT', lambda: ledger.get_allocation('child-1'))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.get_allocation('alloc-1'))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.unsettled(OWNER))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.reconcile(OWNER))


def test_corrupt_usage_json_fails_closed(ledger):
    store, ledger = ledger
    record(ledger, 'call-1', input_tokens=1, cached_tokens={'read': 2})
    store.db.execute("UPDATE harness_usage SET requested_json='not-json' WHERE call_key='call-1'")
    error('USAGE_RECORD_CORRUPT', lambda: ledger.calls(OWNER))
    error('USAGE_RECORD_CORRUPT', lambda: ledger.reconcile(OWNER))
    error('USAGE_RECORD_CORRUPT',
          lambda: record(ledger, 'call-1', input_tokens=1, cached_tokens={'read': 2}))
    store.db.execute("UPDATE harness_usage SET requested_json=NULL, cached_tokens_json='not-json' "
                     "WHERE call_key='call-1'")
    error('USAGE_RECORD_CORRUPT', lambda: ledger.aggregate(OWNER))


def test_missing_columns_fail_closed(tmp_path):
    usage = SessionStore(tmp_path / 'usage.db')
    usage.db.execute('CREATE TABLE harness_usage (call_key TEXT PRIMARY KEY, schema_version INTEGER)')
    with pytest.raises(ContractError) as exc:
        UsageLedger(usage)
    assert exc.value.code == 'USAGE_SCHEMA_UNSUPPORTED'
    usage.close()
    allocations = SessionStore(tmp_path / 'allocations.db')
    allocations.db.execute('CREATE TABLE harness_allocations (allocation_id TEXT PRIMARY KEY, '
                           'schema_version INTEGER)')
    with pytest.raises(ContractError) as exc:
        UsageLedger(allocations)
    assert exc.value.code == 'USAGE_SCHEMA_UNSUPPORTED'
    allocations.close()


def test_unsupported_row_schema_fails_closed(ledger):
    store, ledger = ledger
    store.db.execute("INSERT INTO harness_usage (call_key, schema_version, owner_id, certainty, "
                     "created_at) VALUES ('call-x', 99, 'owner-1', 'unknown', 1.0)")
    error('USAGE_SCHEMA_UNSUPPORTED', lambda: ledger.calls(OWNER))
    store.db.execute("INSERT INTO harness_allocations (allocation_id, schema_version, owner_id, "
                     "policy_revision, consent_ref, reservation_json, consumed_json, state, "
                     "created_at, updated_at) VALUES ('alloc-x', 99, 'owner-1', 1, 'consent-1', "
                     "'{}', '{}', 'reserved', 1.0, 1.0)")
    error('USAGE_SCHEMA_UNSUPPORTED', lambda: ledger.get_allocation('alloc-x'))
    error('USAGE_SCHEMA_UNSUPPORTED', lambda: ledger.unsettled(OWNER))
