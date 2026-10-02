"""W7.1 — interview của main khi có run đang mở là một yêu cầu BỀN, không phải future trong RAM.

Card sống qua restart bằng CardHistory; main yield (không giữ lượt), và câu trả lời quay lại
thành một lượt main mới đọc bằng `work_report(action='read', requestId)`.
"""
import asyncio
import json

from agentbox.agent_core import work_graph
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_harness_runtime import FixtureExecutor, FixtureModel, answer, call
from test_work_feedback_w7 import QUESTIONS, setup


def pending_cards(rt, sid):
    return [c for c in rt.pending_for(sid) if c.get('durable')]


def test_active_run_interview_is_a_durable_card_that_survives_restart(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        card = await rt.work_tool(store.get(sid), 'interview', {'questions': QUESTIONS})
        assert card['durable'] is True and card['requiresMainYield'] is True
        assert card['runId'] == run['runId'] and card['workRequestId'].startswith('wr-')
        doc = graph.feedback.get(card['workRequestId'], sid)
        assert doc['kind'] == 'main_interview' and doc['status'] == 'needs_user' and doc['childId'] == sid
        assert [q['id'] for q in doc['questions']] == ['users', 'deploy']
        events = [e for e in store.events(sid) if e['type'] == 'decision_requested']
        assert len(events) == 1 and events[0]['data']['workRequestId'] == card['workRequestId']
        assert not rt.pending, 'không giữ future trong RAM cho lượt main'

        # Restart thật: mở lại cùng file DB bằng một runtime mới.
        store2 = SessionStore(tmp_path / 'sessions.db')
        rt2 = HarnessRuntime(store2, FixtureExecutor(), FixtureModel([]))
        graph2 = work_graph.service(rt2)
        assert [c['workRequestId'] for c in pending_cards(rt2, sid)] == [card['workRequestId']]
        first = rt2.resolve_decision(sid, card['decisionId'], 'submit',
                                     answers=[{'questionId': 'users', 'optionId': doc['questions'][0]['options'][0]['id']}])
        assert first['status'] == 'resolved' and first['remaining'] is True
        newer = pending_cards(rt2, sid)[0]
        assert newer['decisionId'].endswith('-r2') and len(newer['questions']) == 1
        again = rt2.resolve_decision(sid, newer['decisionId'], 'submit',
                                     answers=[{'questionId': 'deploy', 'text': 'Offline trên máy bệnh viện'}])
        assert again['remaining'] is False and again['answers'][0]['decidedBy'] == 'user'

        saved = graph2.feedback.get(card['workRequestId'], sid)
        assert saved['status'] == 'answered'
        interviews = graph2.current(run['runId'])['interviews']
        assert interviews and interviews[0]['requestId'] == card['workRequestId']
        assert [a['decidedBy'] for a in interviews[0]['answers']] == ['user', 'user']
        jobs = [json.loads(r['doc']) for r in store2.db.execute('SELECT doc FROM work_feedback_outbox').fetchall()]
        assert [j['action'] for j in jobs] == ['main_decision']
        assert card['workRequestId'] in jobs[0]['prompt']
        # Lượt main mới đọc lại đúng câu trả lời bằng work_report(action='read').
        read = await rt2.dispatch(store2.get(sid), 'work_report',
                                  {'action': 'read', 'requestId': card['workRequestId']})
        assert read['status'] == 'answered' and len(read['answers']) == 2
        store.close(); store2.close()
    asyncio.run(run())


def test_main_turn_yields_on_the_durable_card_without_a_second_question_round(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        class Model:
            async def complete(self, messages, tools, route, **kwargs):
                return answer('', calls=[call('interview', {'questions': QUESTIONS}, 'card-1')])
        rt.client = Model()
        await rt.start(sid, 'Hỏi người dùng phạm vi trước khi làm tiếp')
        assert store.get(sid)['status'] == 'completed'
        finish = [e for e in store.events(sid) if e['type'] == 'finish'][-1]
        assert finish['data']['needsUser'] is True
        cards = pending_cards(rt, sid)
        assert len(cards) == 1 and cards[0]['workRequestId'] == finish['data']['workRequestId']
        assert not rt.pending and not rt.run_budget, 'yield không giữ lượt hay future'
        assert len([e for e in store.events(sid) if e['type'] == 'decision_requested']) == 1
        store.close()
    asyncio.run(run())


def test_interview_without_an_active_run_keeps_the_legacy_future(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        run['status'] = 'shipped'
        graph.save(run)
        task = asyncio.ensure_future(rt.work_tool(store.get(sid), 'interview', {'questions': QUESTIONS[:1]}))
        for _ in range(100):
            if rt.pending_for(sid):
                break
            await asyncio.sleep(0.01)
        card = rt.pending_for(sid)[0]
        assert not card.get('durable') and rt.pending
        assert not store.db.execute("SELECT 1 FROM work_requests WHERE owner_id=? AND json_extract(doc,'$.kind')='main_interview'",
                                    (sid,)).fetchone()
        rt.resolve_decision(sid, card['decisionId'], 'decide')
        result = await task
        assert result['answers'][0]['decidedBy'] == 'agent'
        store.close()
    asyncio.run(run())


def test_answer_repairs_a_crash_between_the_answer_and_the_run_write(tmp_path):
    """Câu trả lời đã commit thì việc ghi `run['interviews']` không được mất; đọc lại là đủ."""
    async def run():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        card = await rt.work_tool(store.get(sid), 'interview', {'questions': QUESTIONS[:1]})
        doc = graph.feedback.get(card['workRequestId'], sid)
        answers = [rt.interview_answer(doc['questions'][0], {'text': 'Bác sĩ'})]
        doc.update(status='answered', answers=answers)  # mô phỏng: câu trả lời commit, run chưa kịp ghi
        with store.db:
            graph.feedback.save(doc)
        assert graph.current(run['runId']).get('interviews', []) == []
        read = await rt.dispatch(store.get(sid), 'work_report',
                                 {'action': 'read', 'requestId': card['workRequestId']})
        assert read['status'] == 'answered'
        interviews = graph.current(run['runId'])['interviews']
        assert interviews[0]['requestId'] == card['workRequestId']
        assert graph.feedback.card(graph.feedback.get(card['workRequestId'], sid))['resolved'] is False
        store.close()
    asyncio.run(run())
