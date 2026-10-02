"""Native two-question partial/restart/continuation probe, B / Space Bunny only.

Human selections are synthetic. This checks backend history and same-child
continuation; it does not certify a browser render, full main, or medical plans.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from work_check_eval import ROOT, HarnessRuntime, RouterClient, SessionStore, wg
from work_feedback_eval import FeedbackFixtureExecutor
from work_knowledge_eval import visible
from agentbox.agent_core import work_feedback


class Client(RouterClient):
    """Record provider metadata without the research-check fixture's tool filter."""
    def __init__(self, router):
        super().__init__(router)
        self.calls = []

    async def complete(self, messages, tools, route, **kwargs):
        started = time.monotonic()
        result = await super().complete(messages, tools, route, **kwargs)
        self.calls.append({'native': True, 'maxTokens': kwargs.get('max_tokens'),
            'latencySeconds': round(time.monotonic()-started, 3), 'requestId': result.get('id'),
            'finishReason': result.get('choices', [{}])[0].get('finish_reason'), 'usage': result.get('usage'),
            'advertisedTools': [t['function']['name'] for t in tools]})
        return result


async def main(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp')
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p, h in frozen.items())
    client = Client(args.router)
    state = await client.snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in state['connections']
        if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
        if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    records = []
    for repeat in range(1, args.repeats + 1):
        client = Client(args.router)
        folder = output / str(repeat)
        (folder/'docs').mkdir(parents=True)
        source = 'Exporter chỉ xuất CSV, giữ Unicode. Người dùng mục tiêu và nơi triển khai chưa chốt.\n'
        (folder/'docs/source.md').write_text(source, encoding='utf8')
        store = SessionStore(folder/'sessions.db')
        rt = HarnessRuntime(store, FeedbackFixtureExecutor(folder), client)
        sid = rt.create({**route, 'skills': [], 'maxSteps': 16, 'deadlineSeconds': 300})['id']
        graph = wg.service(rt)
        run = graph.create(store.get(sid), {'flow': 'research',
            'goal': 'Mô tả exporter CSV theo người dùng và nơi triển khai được xác nhận; chỉ báo cáo, không viết mã.',
            'nodes': [{'id': 'R1', 'kind': 'research', 'taskKind': 'lookup', 'title': 'Mô tả exporter',
                'goal': 'Ca kiểm thử lớp bảo vệ hiếm: đọc docs/source.md, giữ CSV/Unicode. Thiếu hai quyết định của user: '
                        'ai dùng (Bác sĩ/Điều dưỡng) và nơi triển khai (Offline/Cloud). Gọi work_report action=needs_user '
                        'với ĐÚNG HAI câu hỏi trong cùng card, decisionKeys=["users","deploy"], lưu checkpoint nguồn đã đọc. '
                        'Không tự chọn. Khi được tiếp tục, đọc work_report action=read bằng requestId được giao để lấy '
                        'câu trả lời đã lưu; không hỏi lại và không nghiên cứu lại định dạng. Final dưới 200 từ, '
                        'báo đúng hai lựa chọn và CSV/Unicode, dẫn docs/source.md. Không triển khai mã.',
                'acceptance': ['Đọc nguồn, báo đúng hai lựa chọn được xác nhận, giữ CSV và Unicode'], 'dependsOn': []}]})
        graph.grants.action(store.get(sid), {'action': 'grant', 'runId': run['runId'], 'revision': run['revision'],
            'nodeId': 'R1', 'decisionKeys': ['users', 'deploy'], 'publishInterview': True,
            'resumeOnAnswers': True, 'invocationId': 'native-card-rights'})
        started = time.monotonic()
        row = {'repeat': repeat, 'route': route, 'sourceManifest': frozen, 'fixtureSource': source,
               'scope': 'Native child/questions; synthetic human selections; no root model/CUA/full DAG'}
        try:
            row['first'] = await graph.run(store.get(sid), {'phase': 'discover'})
            reqs = graph.feedback.records(run['runId'])
            assert len(reqs) == 1 and reqs[0]['status'] == 'needs_user', reqs
            req = reqs[0]; cid = req['childId']; card = rt.pending_for(sid)[0]
            assert len(card['questions']) == 2 and req['decisionKeys'] == ['users', 'deploy'], card
            users, deploy = card['questions']
            option = next(o['id'] for o in users['options'] if 'Điều dưỡng'.lower() in o['label'].lower())
            supplied = [{'questionId': users['id'], 'optionId': option}]
            first = rt.resolve_decision(sid, card['decisionId'], 'submit', answers=supplied)
            assert first['remaining']
            assert rt.resolve_decision(sid, card['decisionId'], 'submit', answers=supplied) == first
            before = [dict(r) for r in store.db.execute("SELECT * FROM events WHERE session_id=? AND "
                "kind IN ('decision_requested','decision_resolved') ORDER BY seq", (sid,))]
            assert not store.db.execute('SELECT * FROM work_feedback_outbox').fetchall()
            store.db.close()
            # Reopen SQLite as a new runtime; no RAM pending map carries the answer.
            store = SessionStore(folder/'sessions.db')
            rt = HarnessRuntime(store, FeedbackFixtureExecutor(folder), client); graph = wg.service(rt)
            after = [dict(r) for r in store.db.execute("SELECT * FROM events WHERE session_id=? AND "
                "kind IN ('decision_requested','decision_resolved') ORDER BY seq", (sid,))]
            assert after == before
            remaining = rt.pending_for(sid)[0]
            assert [q['id'] for q in remaining['questions']] == [deploy['id']]
            assert remaining['answers'] == first['answers']
            option = next(o['id'] for o in remaining['questions'][0]['options'] if 'offline' in o['label'].lower())
            supplied = [{'questionId': deploy['id'], 'optionId': option}]
            second = rt.resolve_decision(sid, remaining['decisionId'], 'submit', answers=supplied)
            assert rt.resolve_decision(sid, remaining['decisionId'], 'submit', answers=supplied) == second
            await work_feedback.pump(rt)
            tasks = list(graph.continuations.tasks.values())
            assert tasks, 'Expected direct continuation without main model relay'
            await asyncio.gather(*tasks)
            state = graph.get(run['runId'])['nodes'][0]['stages']['produce']
            output_text = state.get('output', '')
            saved = graph.feedback.get(req['requestId'])
            events = [dict(r) for r in store.db.execute("SELECT * FROM events WHERE session_id=? AND "
                "kind IN ('decision_requested','decision_resolved') ORDER BY seq", (sid,))]
            row.update(childId=cid, request=saved, status=state['status'], output=output_text,
                firstAnswer=first, secondAnswer=second, beforeRestart=before, afterRestart=after,
                finalCardEvents=events, outbox=[dict(r) for r in store.db.execute('SELECT * FROM work_feedback_outbox')],
                rootCompletionAttempts=store.db.execute("SELECT COUNT(*) FROM events WHERE session_id=? AND kind='completion_attempt'", (sid,)).fetchone()[0],
                childCount=len(store.children_of(sid)), activeSlots=store.live_children(sid),
                telemetry=store.child_usage_from_events(cid), pendingCards=rt.pending_for(sid))
            row['oracle'] = (state['status'] == 'accepted' and state['rounds'][-1]['producerId'] == cid and
                row['childCount'] == 1 and row['rootCompletionAttempts'] == 0 and len(events) == 4 and
                len(row['outbox']) == 1 and row['outbox'][0]['status'] == 'completed' and
                not row['activeSlots'] and not row['pendingCards'] and len(saved['answers']) == 2 and
                'Điều dưỡng'.lower() in output_text.lower() and 'offline' in output_text.lower())
        except Exception as exc:
            row.update(status='error', error=str(exc), oracle=False)
        row.update(latencySeconds=round(time.monotonic()-started, 3), visibleOutputs=visible(store, sid),
                   providerCalls=client.calls, wordCount=len(row.get('output', '').split()))
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == h for p, h in frozen.items()), 'source drift'
        records.append(row)
        (output/'results.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
        print(json.dumps({k: row.get(k) for k in ('repeat', 'status', 'oracle', 'latencySeconds', 'error')}, ensure_ascii=False), flush=True)
        store.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    asyncio.run(main(parser.parse_args()))
