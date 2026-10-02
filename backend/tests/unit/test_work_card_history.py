"""Atomic cards/answers/jobs and historical repair, without a provider or UI."""
import asyncio
import json
import sqlite3

import pytest

from agentbox.agent_core import work_feedback
from test_work_feedback_w7 import setup, request, open_card


def cards(store, sid):
    return [e for e in store.events(sid) if e['type'] in ('decision_requested', 'decision_resolved')]


def fault(store, condition):
    store.db.execute("CREATE TRIGGER fail_card AFTER INSERT ON events WHEN " + condition +
                     " BEGIN SELECT RAISE(ABORT,'card write fault'); END")
    store.db.commit()


def drop_fault(store):
    store.db.execute('DROP TRIGGER fail_card')
    store.db.commit()


def legacy(store, graph, rid, *, delete=None):
    """Emulate an old DB with requests/receipts but no atomic history contract."""
    doc = graph.feedback.get(rid)
    doc.pop('cardHistory', None)
    with store.db:
        graph.feedback.save(doc)
        store.db.execute('DELETE FROM work_card_events')
        if delete:
            store.db.execute('DELETE FROM events WHERE ' + delete)


def test_publication_event_failure_rolls_back_request_and_retry_publishes_once(tmp_path):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid)
        fault(store, "NEW.kind='decision_requested'")
        with pytest.raises(Exception, match='card write fault'):
            open_card(rt, graph, sid, req)
        saved = graph.feedback.get(req['requestId'])
        assert saved['status'] == 'waiting_main' and 'cardHistory' not in saved
        assert not cards(store, sid) and not graph.feedback.pending(sid)
        assert not store.db.execute('SELECT * FROM work_card_events').fetchall()
        drop_fault(store)
        graph.feedback = work_feedback.Feedback(graph)
        first = open_card(rt, graph, sid, req)
        assert open_card(rt, graph, sid, req) == first
        assert len(cards(store, sid)) == 1
    asyncio.run(check())


@pytest.mark.parametrize('point', ['resolved', 'remaining', 'notice', 'outbox'])
def test_answer_failure_rolls_back_all_state_history_and_invocation(tmp_path, point):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        before = graph.feedback.get(req['requestId']); events = cards(store, sid)
        if point == 'outbox':
            store.db.execute("CREATE TRIGGER fail_job BEFORE INSERT ON work_feedback_outbox "
                             "BEGIN SELECT RAISE(ABORT,'card write fault'); END")
            store.db.commit()
        else:
            condition = ("NEW.kind='decision_resolved'" if point == 'resolved' else
                         "NEW.kind='decision_requested' AND json_extract(NEW.payload,'$.revision')=2" if point == 'remaining' else
                         "NEW.kind='work_feedback'")
            fault(store, condition)
        answers = [{'questionId': 'users', 'text': 'Bác sĩ'}] if point == 'remaining' else None
        choice = 'submit' if answers else 'decide'
        with pytest.raises(sqlite3.IntegrityError, match='card write fault'):
            rt.resolve_decision(sid, card['decisionId'], choice, answers=answers)
        assert graph.feedback.get(req['requestId']) == before
        assert cards(store, sid) == events
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_invocations').fetchone()[0] == 0
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0] == 0
        with store.db:
            store.db.execute('DROP TRIGGER ' + ('fail_job' if point == 'outbox' else 'fail_card'))
        result = rt.resolve_decision(sid, card['decisionId'], choice, answers=answers)
        assert rt.resolve_decision(sid, card['decisionId'], choice, answers=answers) == result
        assert len(cards(store, sid)) == (3 if answers else 2)
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0] == (0 if answers else 1)
    asyncio.run(check())


@pytest.mark.parametrize('rounds', ['pending', 'partial', 'done'])
def test_legacy_restart_repairs_missing_card_history_from_user_receipts(tmp_path, rounds):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        if rounds == 'partial':
            rt.resolve_decision(sid, card['decisionId'], 'submit', answers=[{'questionId': 'users', 'text': 'Bác sĩ'}])
        elif rounds == 'done':
            rt.resolve_decision(sid, card['decisionId'], 'decide')
        stored = graph.feedback.get(req['requestId'])
        count = store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0]
        legacy(store, graph, req['requestId'], delete="kind IN ('decision_requested','decision_resolved')")
        graph.feedback = work_feedback.Feedback(graph)
        repaired = cards(store, sid)
        assert [e['type'] for e in repaired] == (['decision_requested'] if rounds == 'pending' else
            ['decision_requested', 'decision_resolved', 'decision_requested'] if rounds == 'partial' else
            ['decision_requested', 'decision_resolved'])
        assert graph.feedback.get(req['requestId'])['answers'] == stored['answers']
        if rounds != 'pending':
            assert repaired[1]['data']['status'] == 'answered' and repaired[1]['data']['reason'] == 'user'
            assert len(repaired[1]['data']['questions']) == 2
        graph.feedback = work_feedback.Feedback(graph)
        graph.feedback.pending(sid)
        assert cards(store, sid) == repaired
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0] == count
        assert store.db.execute("SELECT COUNT(*) FROM events WHERE kind='user'").fetchone()[0] == 0
    asyncio.run(check())


def test_legacy_invocation_replay_repairs_events_without_new_job_or_answer(tmp_path):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        result = graph.feedback.answer(sid, card['decisionId'], 'decide', None, 'saved-answer')
        legacy(store, graph, req['requestId'], delete="kind='decision_resolved'")
        assert graph.feedback.answer(sid, card['decisionId'], 'decide', None, 'saved-answer') == result
        assert len(cards(store, sid)) == 2
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_invocations').fetchone()[0] == 1
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0] == 1
    asyncio.run(check())


@pytest.mark.parametrize('missing', ['receipt', 'provenance', 'timestamp', 'question', 'choice', 'invalid_receipt'])
def test_recovery_never_invents_user_confirmation(tmp_path, missing):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        graph.feedback.answer(sid, card['decisionId'], 'decide', None, 'real-answer')
        legacy(store, graph, req['requestId'], delete="kind IN ('decision_requested','decision_resolved')")
        doc = graph.feedback.get(req['requestId'])
        with store.db:
            if missing == 'receipt':
                store.db.execute('DELETE FROM work_feedback_invocations')
            elif missing == 'invalid_receipt':
                store.db.execute('UPDATE work_feedback_invocations SET result=?', ('null',))
            elif missing == 'choice':
                row = store.db.execute('SELECT result FROM work_feedback_invocations').fetchone()
                result = json.loads(row['result']); result['choice'] = 'timeout'
                store.db.execute('UPDATE work_feedback_invocations SET result=?', (json.dumps(result),))
            else:
                doc['answers'][0].update({'source': 'model'} if missing == 'provenance' else
                    {'confirmedAt': None} if missing == 'timestamp' else {'questionId': 'invented'})
                graph.feedback.save(doc)
        graph.feedback = work_feedback.Feedback(graph)
        assert not cards(store, sid)
        assert graph.feedback.get(req['requestId'])['answers'] == doc['answers']
    asyncio.run(check())


def test_old_resolved_status_is_corrected_without_deleting_history(tmp_path):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        rt.resolve_decision(sid, card['decisionId'], 'decide')
        legacy(store, graph, req['requestId'])
        with store.db:
            row = store.db.execute("SELECT seq,payload FROM events WHERE kind='decision_resolved'").fetchone()
            bad = json.loads(row['payload']); bad['status'] = 'resolved'
            store.db.execute('UPDATE events SET payload=? WHERE seq=?', (json.dumps(bad), row['seq']))
        graph.feedback = work_feedback.Feedback(graph)
        repaired = cards(store, sid)
        assert len(repaired) == 3 and repaired[-1]['data']['status'] == 'answered'
        assert repaired[1]['data']['status'] == 'resolved'
        graph.feedback = work_feedback.Feedback(graph)
        assert cards(store, sid) == repaired
    asyncio.run(check())


@pytest.mark.parametrize('control', ['cancel', 'stale'])
def test_cancellation_and_staleness_event_failures_are_atomic(tmp_path, control):
    async def check():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); open_card(rt, graph, sid, req)
        before = graph.feedback.get(req['requestId'])
        if control == 'stale':
            run['nodes'][0]['goal'] = 'A changed assignment'; graph.save(run)
        fault(store, "NEW.kind='decision_resolved'")
        with pytest.raises(Exception, match='card write fault'):
            graph.feedback.cancel(sid) if control == 'cancel' else graph.feedback.validate(graph.feedback.get(req['requestId']))
        assert graph.feedback.get(req['requestId']) == before
        assert len(cards(store, sid)) == 1
        drop_fault(store)
        if control == 'cancel':
            graph.feedback.cancel(sid); graph.feedback.cancel(sid)
        else:
            with pytest.raises(work_feedback.FeedbackError, match='STALE'):
                graph.feedback.validate(graph.feedback.get(req['requestId']))
        assert len(cards(store, sid)) == 2
        assert cards(store, sid)[1]['data']['status'] == 'cancelled'
        assert not graph.feedback.get(req['requestId'])['answers']
    asyncio.run(check())


def test_new_card_history_repairs_deleted_events_on_restart_without_duplicate_answers(tmp_path):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        rt.resolve_decision(sid, card['decisionId'], 'submit', answers=[{'questionId': 'users', 'text': 'Bác sĩ'}])
        saved = graph.feedback.get(req['requestId'])
        with store.db:
            store.db.execute("DELETE FROM events WHERE kind IN ('decision_requested','decision_resolved')")
        graph.feedback = work_feedback.Feedback(graph)
        assert len(cards(store, sid)) == 3
        assert graph.feedback.get(req['requestId']) == saved
        assert len(graph.feedback.pending(sid)) == 1
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_invocations').fetchone()[0] == 1
        assert not store.db.execute('SELECT * FROM work_feedback_outbox').fetchall()
    asyncio.run(check())


def test_later_receipt_cannot_confirm_an_earlier_missing_round(tmp_path):
    async def check():
        store, rt, graph, _, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        rt.resolve_decision(sid, card['decisionId'], 'submit', answers=[{'questionId': 'users', 'text': 'Bác sĩ'}])
        newer = graph.feedback.pending(sid)[0]
        rt.resolve_decision(sid, newer['decisionId'], 'decide')
        legacy(store, graph, req['requestId'], delete="kind IN ('decision_requested','decision_resolved')")
        with store.db:
            store.db.execute("DELETE FROM work_feedback_invocations WHERE json_extract(result,'$.decisionId')=?", (card['decisionId'],))
        graph.feedback = work_feedback.Feedback(graph)
        assert not cards(store, sid)
        assert len(graph.feedback.get(req['requestId'])['answers']) == 2
    asyncio.run(check())


def test_actual_sqlite_restart_retains_partial_questions_answers_and_one_continuation(tmp_path):
    from agentbox.agent_core.runtime import HarnessRuntime
    from agentbox.memory.session_store import SessionStore
    from test_work_graph import Executor, Model, ok_script
    from agentbox.agent_core import work_graph

    async def check():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        req = await request(rt, graph, cid); card = open_card(rt, graph, sid, req)
        first = rt.resolve_decision(sid, card['decisionId'], 'submit', answers=[{'questionId': 'users', 'text': 'Bác sĩ'}])
        before = cards(store, sid); store.db.close()
        store = SessionStore(tmp_path / 'sessions.db')
        rt = HarnessRuntime(store, Executor(), Model(ok_script)); graph = work_graph.service(rt)
        assert cards(store, sid) == before
        assert graph.feedback.get(req['requestId'])['childId'] == cid
        pending = rt.pending_for(sid)[0]
        assert [q['id'] for q in pending['questions']] == ['deploy']
        assert pending['answers'] == first['answers']
        result = rt.resolve_decision(sid, pending['decisionId'], 'submit', answers=[{'questionId': 'deploy', 'text': 'Offline'}])
        assert not result['remaining'] and not rt.pending_for(sid)
        assert len(cards(store, sid)) == 4
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0] == 1
        graph.feedback = work_feedback.Feedback(graph)
        assert len(cards(store, sid)) == 4
    asyncio.run(check())
