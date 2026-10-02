"""Native Space Bunny main consumes a synthetic sub interview by immutable ref.

Producer checkpoint/questions are synthetic; no human answer is supplied. This
isolates root admission/publication, not a full main/sub medical or SWE benchmark.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

from work_check_eval import ROOT, HarnessRuntime, SessionStore, wg
from work_card_history_eval import Client
from work_feedback_eval import FeedbackFixtureExecutor
from work_knowledge_eval import visible
from agentbox.agent_core import work_feedback


async def main(args):
    assert subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip() == 'B'
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp')
    output.mkdir(parents=True, exist_ok=False)
    frozen = json.loads(Path(args.manifest).read_text(encoding='utf8'))
    assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in frozen.items())
    state = await Client(args.router).snapshot()
    route = next(({'connectionId': c['id'], 'modelId': m['id']} for c in (state or {}).get('connections', [])
        if c['providerId'] == 'opencode' and c.get('enabled') for m in c['models']
        if m['id'] == 'space-bunny-free' and m.get('enabled')), None)
    if not route:
        raise SystemExit('OpenCode Space Bunny unavailable; no substitute')
    rows = []
    questions = [
        {'id': 'users', 'question': 'Ai sử dụng bản xuất CSV?', 'rationale': 'Chốt người dùng mục tiêu, nguồn không nói.',
         'options': [{'id': 'doctors', 'label': 'Bác sĩ', 'description': 'Bác sĩ dùng kết quả'},
                     {'id': 'nurses', 'label': 'Điều dưỡng', 'description': 'Điều dưỡng dùng kết quả'}]},
        {'id': 'deploy', 'question': 'Bản xuất được sử dụng ở đâu?', 'rationale': 'Chốt ràng buộc triển khai.',
         'options': [{'id': 'offline', 'label': 'Offline', 'description': 'Không cần mạng khi sử dụng'},
                     {'id': 'cloud', 'label': 'Cloud', 'description': 'Dùng máy chủ có mạng'}]}]
    for repeat in range(1, args.repeats + 1):
        folder = output / str(repeat); (folder / 'docs').mkdir(parents=True)
        source = 'Chỉ xuất CSV, giữ nguyên Unicode. Chưa chốt ai sử dụng hoặc nơi triển khai.\n'
        (folder / 'docs/source.md').write_text(source, encoding='utf8')
        client = Client(args.router)
        store = SessionStore(folder / 'sessions.db')
        executor = FeedbackFixtureExecutor(folder)
        rt = HarnessRuntime(store, executor, client)
        sid = rt.create({**route, 'skills': [], 'maxSteps': 16, 'deadlineSeconds': 300})['id']
        graph = wg.service(rt)
        run = graph.create(store.get(sid), {'flow': 'research',
            'goal': 'Chỉ nghiên cứu bản xuất CSV/Unicode, chưa chốt người dùng và triển khai. '
                    'Cần hỏi chủ dự án, giữ nguyên bảng hỏi sub đã soạn; không làm mã hoặc chốt thay.',
            'nodes': [{'id': 'R1', 'kind': 'research', 'taskKind': 'lookup', 'title': 'Người dùng và triển khai',
                'goal': 'Đọc docs/source.md và hỏi chủ dự án về ai sử dụng, nơi triển khai; không tự chốt.',
                'acceptance': ['Giữ CSV/Unicode và hỏi đúng hai quyết định chưa chốt']}]})
        child = rt.create({'skills': []}, parent_id=sid, role='research', parent_tools=store.get(sid)['config']['tools'])
        config = child['config']; config['workBinding'] = {'runId': run['runId'], 'nodeId': 'R1',
            'stage': 'produce', 'purpose': 'produce', 'artifactIds': []}
        store.update_config(child['id'], config)
        request = await graph.feedback.report(store.get(child['id']), {'action': 'needs_user', 'questions': questions,
            'decisionKeys': ['users', 'deploy'], 'checkpoint': source + 'Hai câu hỏi đã lưu; main chỉ cần mở bằng request ref.',
            'invocationId': 'synthetic-sub-report'}, 'synthetic-sub-report')
        # Lose the notification and restart SQLite. The request remains canonical.
        store.db.execute("DELETE FROM events WHERE kind='work_feedback'"); store.db.commit(); store.db.close()
        store = SessionStore(folder / 'sessions.db'); rt = HarnessRuntime(store, executor, client); graph = wg.service(rt)
        started = time.monotonic()
        row = {'repeat': repeat, 'route': route, 'sourceManifest': frozen, 'fixtureSource': source,
               'syntheticRequest': request, 'scope': 'Native root; synthetic child/questions; no user answers/CUA/full DAG'}
        try:
            await work_feedback.pump(rt)
            assert sid in rt.tasks, 'Expected one decision admission for idle main'
            await rt.tasks[sid]; await asyncio.sleep(0)
            before = len(client.calls)
            await work_feedback.pump(rt); await work_feedback.pump(rt)
            cards = rt.pending_for(sid)
            saved = graph.feedback.get(request['requestId'])
            root_events = [dict(r) for r in store.db.execute("SELECT * FROM events WHERE session_id=? ORDER BY seq", (sid,))]
            kinds = [json.loads(r['payload'])['name'] for r in store.db.execute("SELECT payload FROM events WHERE kind='tool_start'")]
            calls = [json.loads(r['payload']) for r in store.db.execute("SELECT payload FROM events WHERE kind='tool_end'")]
            row.update(cards=cards, savedRequest=saved, mainDecisions=graph.decisions.records(),
                batches=[dict(r) for r in store.db.execute('SELECT * FROM work_main_batches')], rootEvents=root_events,
                toolNames=kinds, toolResults=calls, replayAddedProviderCalls=len(client.calls)-before)
            row['oracle'] = (len(cards) == 1 and cards[0]['questions'] == request['questions']
                and saved['status'] == 'needs_user' and not saved['answers']
                and row['replayAddedProviderCalls'] == 0 and not graph.get(run['runId'])['executionRequested']
                and len([r for r in root_events if r['kind'] == 'user']) == 1
                and not any(k in kinds for k in ('terminal_exec', 'file_write', 'delegate_task')))
            row['status'] = 'pass' if row['oracle'] else 'failed_oracle'
        except Exception as exc:
            row.update(status='error', error=str(exc), oracle=False)
        row.update(latencySeconds=round(time.monotonic()-started, 3), visibleOutputs=visible(store, sid), providerCalls=client.calls)
        assert all(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() == h for p, h in frozen.items()), 'source drift'
        rows.append(row)
        (output / 'results.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
        print(json.dumps({k: row.get(k) for k in ('repeat', 'status', 'oracle', 'latencySeconds', 'error')}, ensure_ascii=False), flush=True)
        await rt.stop(sid); store.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--repeats', type=int, default=2)
    asyncio.run(main(parser.parse_args()))
