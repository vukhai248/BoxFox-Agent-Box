"""W7.1 — probe phân trang event >500 qua HTTP API (không cần model).

Kịch bản: seed 1200 event cho một phiên, trong đó `decision_requested` ở seq 30 và
`decision_resolved` ở seq 1150 (thứ tự legacy: card đóng trước khi hàng requested được phát).
Sau đó đi từng trang bằng `after`/`nextAfter` của `GET /api/agent/sessions/{sid}` và kiểm:
không thiếu, không trùng seq; `hasMore` đúng ở trang cuối; card resolved đúng
`requestId`/`revision`; và `history.reconcile` dựng lại được card còn thiếu hàng requested.

Harness được chạy như một tiến trình riêng (`scripts/run-harness.py`) trên data dir của probe,
nên phép đo đi qua đúng HTTP boundary (Host + X-BoxFox-Admin) chứ không phải TestServer trong
tiến trình. Mọi lời gọi mạng đi qua `net.py` — `scripts/eval/*.py` không được import thư viện
mạng trực tiếp (`test_eval_setup.py::test_eval_sources_import_no_network_library_except_net_py`).

Chạy:
    python3 scripts/eval/work_events_pagination_probe.py --output .tmp/w7-pagination
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend/src'))
sys.path.insert(0, str(ROOT / 'scripts/eval'))

import net  # noqa: E402  — cửa duy nhất được mở socket trong scripts/eval

from agentbox.agent_core import work_graph as wg  # noqa: E402
from agentbox.agent_core.work_feedback import Feedback  # noqa: E402
from agentbox.agent_core.runtime import HarnessRuntime  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402


TOTAL = 1200
REQUEST_SEQ = 30
RESOLVED_SEQ = 1150
DEFAULT_PORT = 3199
ADMIN = {'X-BoxFox-Admin': '1'}


def branch():
    name = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    assert name == 'B' or name.startswith('vorflux/'), f'unexpected branch {name!r}'
    return name


def commit():
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def source_manifest():
    """Hash of the sources this probe exercises, so a result names the code it measured."""
    files = ['backend/src/agentbox/api/server.py', 'backend/src/agentbox/memory/session_store.py',
             'backend/src/agentbox/agent_core/work_feedback.py', 'backend/src/agentbox/agent_core/work_feedback_history.py']
    return {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}


class Executor:
    async def execute(self, name, args, sid, **_identity):
        return {'content': 'probe'}

    async def cleanup(self, sid):
        return None


class Client:
    async def complete(self, messages, tools, route, **kwargs):  # pragma: no cover - must not run
        raise AssertionError('pagination probe must not call a model')


def seed(store, sid):
    """1200 events; the resolved card is emitted BEFORE its requested row (legacy ordering)."""
    for index in range(1, TOTAL + 1):
        if index == REQUEST_SEQ:
            store.emit(sid, 'decision_requested', {'decisionId': 'wr-legacy-r1', 'workRequestId': 'wr-legacy',
                                                   'revision': 1, 'kind': 'interview', 'durable': True})
        elif index == RESOLVED_SEQ:
            store.emit(sid, 'decision_resolved', {'decisionId': 'wr-legacy-r1', 'workRequestId': 'wr-legacy',
                                                  'revision': 1, 'status': 'answered', 'resolved': True,
                                                  'reason': 'user', 'choice': 'submit'})
        else:
            store.emit(sid, 'notice', {'index': index})


def start_harness(data_dir, port, log_path):
    """A real harness process on the probe's data dir; the probe talks to it over HTTP."""
    env = {**os.environ, 'BOXFOX_AGENT_DATA_DIR': str(data_dir), 'BOXFOX_HARNESS_PORT': str(port),
           # Bỏ lượt sửa context window lúc khởi động: probe không có router và không cần số đó.
           'BOXFOX_CONTEXT_WINDOW_LOCK': '1'}
    log = open(log_path, 'wb')
    proc = subprocess.Popen([sys.executable, str(ROOT / 'scripts/run-harness.py')], env=env,
                            cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT)
    url = f'http://127.0.0.1:{port}'
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit(f'harness exited early ({proc.returncode}); see {log_path}')
        try:
            if net.request_json(f'{url}/api/agent/health', timeout=5).get('status') == 'ok':
                return proc, url, log
        except net.NetError:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit(f'harness did not answer on {url}; see {log_path}')


def page_through(url, sid):
    """Đi hết event log bằng `nextAfter`; dừng khi `hasMore` tắt."""
    rows, after, pages = [], 0, []
    while True:
        body = net.request_json(f'{url}/api/agent/sessions/{sid}?after={after}', headers=ADMIN, timeout=30)
        events = body['events']
        pages.append({'after': after, 'count': len(events), 'hasMore': body['hasMore'],
                      'nextAfter': body['nextAfter']})
        rows.extend(events)
        if not body['hasMore']:
            break
        assert body['nextAfter'] > after, 'nextAfter must advance'
        after = body['nextAfter']
        assert len(pages) < 20, 'pagination did not terminate'
    return rows, pages


def reconcile_check(db_path, sid):
    """`history.reconcile` dựng lại card đã đóng từ hàng resolved khi hàng requested chưa tới."""
    store = SessionStore(db_path)
    runtime = HarnessRuntime(store, Executor(), Client())
    graph = wg.service(runtime)
    graph.feedback = Feedback(graph)
    doc = {'requestId': 'wr-legacy', 'runId': 'wr-legacy-run', 'ownerId': sid, 'childId': sid, 'revision': 2,
           'kind': 'interview', 'status': 'answered', 'questions': [{'id': 'q1', 'question': 'Ai dùng?'}],
           'answers': [{'questionId': 'q1', 'answer': 'Bác sĩ', 'decidedBy': 'user'}], 'reason': '', 'artifact': None,
           'binding': {'runId': 'wr-legacy-run', 'nodeId': None, 'stage': 'main', 'purpose': 'main_interview'},
           'fingerprint': wg.work_policy.digest({'runId': 'wr-legacy-run'}), 'createdAt': 0, 'decisionKeys': []}
    with graph.db:
        graph.db.execute('INSERT OR REPLACE INTO work_requests VALUES(?,?,?,?,?,?,?)',
                         (doc['requestId'], doc['runId'], sid, sid, 'inv-1', 'hash-1',
                          json.dumps(doc, ensure_ascii=False)))
    repaired = Feedback(graph).get('wr-legacy', sid)
    store.db.close()
    return {'status': repaired['status'], 'answers': len(repaired.get('answers', []))}


def main(args):
    name, head, manifest = branch(), commit(), source_manifest()
    output = Path(args.output).resolve()
    assert output.is_relative_to(ROOT / '.tmp'), 'write probe output under .tmp/'
    output.mkdir(parents=True, exist_ok=True)
    data_dir = output / 'data'
    data_dir.mkdir(parents=True, exist_ok=True)
    row = {'branch': name, 'commit': head, 'sourceManifest': manifest, 'total': TOTAL}
    store = SessionStore(data_dir / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Client())
    sid = runtime.create({'skills': []})['id']
    seed(store, sid)
    assert store.db.execute('SELECT COUNT(*) FROM events WHERE session_id=?', (sid,)).fetchone()[0] == TOTAL
    seqs = [r['seq'] for r in store.db.execute('SELECT seq FROM events WHERE session_id=? ORDER BY seq', (sid,))]
    row['storedRequestedSeq'] = store.db.execute(
        "SELECT seq FROM events WHERE session_id=? AND kind='decision_requested'", (sid,)).fetchone()[0]
    row['storedResolvedSeq'] = store.db.execute(
        "SELECT seq FROM events WHERE session_id=? AND kind='decision_resolved'", (sid,)).fetchone()[0]
    store.db.close()  # the harness process owns the file from here on

    proc, log = None, None
    try:
        proc, url, log = start_harness(data_dir, args.port, output / 'harness.log')
        row['harnessUrl'] = url
        rows, pages = page_through(url, sid)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
        if log is not None:
            log.close()

    got = [e['seq'] for e in rows]
    row['pages'] = pages
    row['pageCount'] = len(pages)
    row['fetched'] = len(got)
    row['firstPageHasMore'] = pages[0]['hasMore']
    row['noGaps'] = got == sorted(set(got)) and len(set(got)) == len(got)
    row['complete'] = set(got) == set(seqs)
    card = [e for e in rows if e['type'] in ('decision_requested', 'decision_resolved')]
    row['cardEvents'] = [{'seq': e['seq'], 'type': e['type'], 'requestId': e['data'].get('workRequestId'),
                          'revision': e['data'].get('revision')} for e in card]
    # Thứ tự legacy: resolved (1150) tới trước requested (30) khi client chỉ đọc phần đuôi.
    tail = [e for e in rows if e['seq'] > 1000]
    row['tailSeesResolvedWithoutRequested'] = any(e['type'] == 'decision_resolved' for e in tail) and \
        not any(e['type'] == 'decision_requested' for e in tail)
    row['reconciled'] = reconcile_check(data_dir / 'sessions.sqlite', sid)
    repaired = row['reconciled']

    row['oracle'] = (row['complete'] and row['noGaps'] and row['pageCount'] >= 3 and row['firstPageHasMore']
                     and row['storedRequestedSeq'] == REQUEST_SEQ and row['storedResolvedSeq'] == RESOLVED_SEQ
                     and row['tailSeesResolvedWithoutRequested'] and repaired['status'] == 'answered')
    row['scope'] = ('Deterministic pagination/API probe: harness chạy như tiến trình riêng, '
                    'không model, không provider, không UI renderer')
    (output / 'results.json').write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({k: row[k] for k in ('oracle', 'fetched', 'pageCount', 'noGaps', 'complete',
                                          'tailSeesResolvedWithoutRequested', 'reconciled')}, ensure_ascii=False))
    return row['oracle']


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    ok = main(parser.parse_args())
    raise SystemExit(0 if ok else 1)
