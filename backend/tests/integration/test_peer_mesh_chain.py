"""T16 — chuỗi đầu-cuối của mesh con: `main → testing → review`, chạy trên runtime THẬT.

Đây là L1 của kế hoạch đợt 2, nguyên văn: trong **một** lượt cha, `main` sinh `testing` và
`review`; `review` khai giao kết quả cho `main` **và** cho `testing`; `testing` chạy một bước
thật (`terminal_exec`) rồi `await_children(targets=['role:review'])` **không truyền thời hạn**;
`main` chờ `testing`. Bốn tệp unit của đợt này (`test_peer_registry`, `test_delivery_routing`,
`test_delivery_injection`, `test_await_children`) mỗi tệp khẳng định một mảnh; tệp này khẳng định
chuỗi đã nối thật, trên cùng một sổ, trong cùng một lượt:

(a) `testing` đọc được bản soát của `review` ở **bước kế tiếp**, không phải gọi `peer_read` lại;
(b) đúng hai event `child` khởi đầu và hai event `child` kết thúc, mỗi hàng mang `turn` của lượt sinh;
(c) đúng **hai** biên nhận cho `review` (một `main`, một peer) và đúng **một** `peer_delivery`
    trong luồng `testing`;
(d) đúng một cặp `peer_wait`/`peer_wait_end` ở tầng gọi, với `waitsUntilDelivery: true`;
(e) câu trả lời cuối của `testing` trích được bản soát, và bước cuối của nó đã đọc hàng đã bơm;
(f) không lượt nào trong chuỗi `failed`, và không event `error` nào trong luồng cha.

Hai biến thể nữa: một biến thể `timeoutSeconds=1` (lưới an toàn — chờ hụt vẫn là lượt XONG, không
phải lượt hỏng), và một biến thể **opt-in** chạy đúng kịch bản trên qua harness SỐNG
(`BOXFOX_LIVE_PEER_MESH=1`), đọc lại sổ thật `~/BoxFox/harness/sessions.sqlite` — T17 dùng lại nó
để thu bằng chứng sống.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sqlite3
import sys
import time
import urllib.request

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / 'src'))

from agentbox.agent_core.runtime import HarnessRuntime  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402

TEST_GOAL = 'chạy bộ kiểm thử đầy đủ cho thay đổi đang xét'
REVIEW_GOAL = 'soát lại thay đổi trước khi giao'
REVIEW_TEXT = 'Bản soát: thiếu kiểm tra biên ở bước đọc tệp và một dòng log bị lặp.'
TEST_FINAL = 'Bộ kiểm đã chạy. Bản soát nói thiếu kiểm tra biên ở bước đọc tệp.'


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    """Mỗi con có hàng trả lời RIÊNG, chọn theo goal — hai con chạy xen kẽ nên hàng chung sẽ gán sai."""

    def __init__(self, parent_responses, child_responses=()):
        self.parent_responses = iter(parent_responses)
        self.calls = []
        self.by_goal = {}
        for goal, responses in dict(child_responses or {}).items():
            self.by_goal[goal] = iter([item if isinstance(item, dict) else answer(item)
                                       for item in responses])

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        # BẢN SAO SÂU: runtime giữ đúng một list `messages` cho cả lượt và sửa tại chỗ, nên ghi lại
        # tham chiếu thì mọi lời gọi đều đọc ra transcript CUỐI — mọi khẳng định về thứ tự thành vô nghĩa.
        self.calls.append(json.loads(json.dumps(messages, ensure_ascii=False)))
        first_user = next((str(message.get('content') or '') for message in messages
                           if message.get('role') == 'user'), '')
        for goal, responses in self.by_goal.items():
            if goal in first_user:
                return next(responses)
        return next(self.parent_responses)


class FixtureExecutor:
    """`slow` là khe để vòng lặp xếp lịch cho con: cha `await asyncio.sleep` thì task con mới chạy."""

    def __init__(self, slow=(), seconds=2.0):
        self.slow = set(slow)
        self.seconds = seconds

    async def execute(self, name, args, sid, **_identity):
        if name in self.slow:
            await asyncio.sleep(self.seconds)
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def build(tmp_path, parent_answers, child_answers, slow=(), seconds=2.0):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(slow, seconds),
                             FixtureModel(parent_answers, child_answers))
    sid = runtime.create({'skills': []})['id']
    return store, runtime, sid


def run_turn(runtime, sid, prompt):
    async def run():
        runtime.start(sid, prompt)
        await runtime.tasks[sid]

    asyncio.run(run())


def chain_script(testing_wait_args, final_text):
    """Kịch bản bốn vai dùng chung cho cả hai biến thể.

    `main`: sinh `testing`, sinh `review` (khai giao cho `main` **và** `testing`), rồi chờ `testing`.
    `testing`: một bước thật (`terminal_exec`), rồi chờ `review`, rồi trả lời.
    `review`: một bước đọc tệp (chậm — để `testing` THẬT SỰ phải đứng chờ), rồi trả lời.
    """
    parent = [
        answer(calls=[call('delegate_task', {'role': 'testing', 'goal': TEST_GOAL,
                                             'wait': False}, 'c1')]),
        answer(calls=[call('delegate_task', {'role': 'review', 'goal': REVIEW_GOAL, 'wait': False,
                                             'deliverTo': ['main', 'role:testing']}, 'c2')]),
        answer(calls=[call('await_children', {'targets': ['role:testing'], 'mode': 'all'}, 'c3')]),
        answer('đã xong chuỗi'),
    ]
    children = {
        TEST_GOAL: [answer(calls=[call('terminal_exec', {'command': 'pytest -q'}, 'a1')]),
                    answer(calls=[call('await_children', testing_wait_args, 'a2')]),
                    answer(final_text)],
        REVIEW_GOAL: [answer(calls=[call('file_read', {'path': 'xem diff'}, 'b1')]),
                      answer(REVIEW_TEXT)],
    }
    return parent, children


def child_rows(store, sid):
    return {row['role']: row for row in store.children_of(sid)}


def events_of(store, sid, kind):
    return [event['data'] for event in store.events(sid) if event['type'] == kind]


def injected_blocks(store, sid):
    return [message['content'] for message in store.get(sid)['messages']
            if message['role'] == 'user' and '[Kết quả từ chuyên gia' in str(message.get('content'))]


def calls_of(session_goal, calls):
    """Những lời gọi model thuộc về một con, nhận ra bằng goal nằm trong prompt đầu tiên."""
    picked = []
    for messages in calls:
        first_user = next((str(message.get('content') or '') for message in messages
                           if message.get('role') == 'user'), '')
        if session_goal in first_user:
            picked.append(messages)
    return picked


def tool_results(store, sid):
    return [json.loads(message['content']) for message in store.get(sid)['messages']
            if message['role'] == 'tool']


# --------------------------------------------------------------------------- #
# Biến thể chính: chờ tới lúc bạn GIAO (không truyền thời hạn)
# --------------------------------------------------------------------------- #
def test_chuoi_main_testing_review_mot_luot_that(tmp_path):
    parent, children = chain_script({'targets': ['role:review'], 'mode': 'all'}, TEST_FINAL)
    store, runtime, sid = build(tmp_path, parent, children, slow={'file_read'}, seconds=2.0)

    started = time.monotonic()
    run_turn(runtime, sid, 'chạy review rồi testing trong cùng một lượt')
    elapsed = time.monotonic() - started

    rows = child_rows(store, sid)
    assert set(rows) == {'testing', 'review'}, 'đúng hai con, sinh trong cùng một lượt'
    testing, review = rows['testing']['session_id'], rows['review']['session_id']

    # (f) lượt không bao giờ `failed`, và không event `error` nào trong luồng cha.
    assert store.get(sid)['status'] == 'completed'
    assert rows['testing']['status'] == 'completed' and rows['review']['status'] == 'completed'
    assert events_of(store, sid, 'error') == []
    assert events_of(store, testing, 'error') == [] and events_of(store, review, 'error') == []
    assert not any(result.get('is_error') for child in (testing, review)
                   for result in tool_results(store, child))
    assert elapsed < 60, f'chuỗi bốn vai chạy mất {elapsed:.1f}s'

    # (b) hai cặp event `child`, mỗi hàng mang `turn` của lượt sinh.
    starts = [item for item in events_of(store, sid, 'child') if item['status'] == 'started']
    ends = [item for item in events_of(store, sid, 'child') if item['status'] != 'started']
    assert len(starts) == 2 and len(ends) == 2, (starts, ends)
    assert {item['turn'] for item in starts + ends} == {1}
    assert {item['role'] for item in starts} == {'testing', 'review'}
    assert {item['sessionId'] for item in ends} == {testing, review}
    assert all(item['status'] == 'completed' for item in ends)

    # (c) biên nhận: một `main`, một peer — và đúng một mũi tên trong luồng `testing`.
    receipts = store.deliveries_of(review)
    assert sorted(row['kind'] for row in receipts) == ['main', 'peer'], receipts
    assert {row['state'] for row in receipts} == {'injected'}
    peer_receipt = next(row for row in receipts if row['kind'] == 'peer')
    assert peer_receipt['recipient'] == testing and peer_receipt['recipient_turn'] == 1

    arrows = events_of(store, testing, 'peer_delivery')
    assert len(arrows) == 1, arrows
    assert arrows[0]['from'] == review and arrows[0]['role'] == 'review'
    # Event mũi tên phát đúng lúc GIAO (`pending`: hàng vừa vào sổ, bước kế tiếp của người nhận sẽ
    # hút); còn biên nhận trong event `child` kết thúc mới là ảnh chụp sau khi khép (`injected`).
    assert arrows[0]['turn'] == 1 and arrows[0]['state'] == 'pending'
    close_event = next(item for item in ends if item['sessionId'] == review)
    # Ảnh chụp trong event `child` là ảnh chụp ĐÚNG LÚC đóng sổ: biên nhận của cha khép ngay (cha
    # đã đọc kết quả qua event), còn biên nhận peer còn `pending` cho tới khi người nhận hút nó ở
    # bước kế tiếp (T12). Bảng sống (`store.deliveries_of`) lúc này đã là `injected` cả hai — hàng
    # trong event là dấu vết lịch sử, không phải trạng thái hiện tại.
    snapshot = {row['recipient']: row['state'] for row in close_event['deliveries']}
    assert snapshot == {sid: 'injected', testing: 'pending'}, close_event['deliveries']
    assert [row['chars'] for row in close_event['deliveries'] if row['recipient'] == testing] \
        == [len(REVIEW_TEXT)], 'biên nhận mang theo số ký tự đã giao'

    # (d) đúng một cặp chờ ở tầng gọi, và nó chờ tới lúc GIAO (`waitsUntilDelivery`), không hạn riêng.
    waits = [item for item in events_of(store, testing, 'peer_wait')]
    wait_ends = [item for item in events_of(store, testing, 'peer_wait_end')]
    assert len(waits) == 1 and len(wait_ends) == 1, (waits, wait_ends)
    assert waits[0]['waitsUntilDelivery'] is True and waits[0]['mode'] == 'all'
    assert wait_ends[0]['status'] == 'done' and wait_ends[0]['pending'] == []
    assert wait_ends[0]['forced'] is False and wait_ends[0]['extensionExhausted'] is False
    assert wait_ends[0]['waitedMs'] >= 300, wait_ends[0]['waitedMs']

    # Lời gọi `await_children` của `testing` KHÔNG có `timeoutSeconds` — chờ tới lúc bạn giao.
    wait_call = next(event['data'] for event in store.events(testing)
                     if event['type'] == 'tool_start' and event['data']['name'] == 'await_children')
    assert 'timeoutSeconds' not in wait_call['args'], wait_call

    # (a) kết quả tool của `testing` mang bản soát của `review`...
    results = [item for item in tool_results(store, testing) if 'status' in item and 'pending' in item]
    assert len(results) == 1, results
    assert results[0]['status'] == 'done' and results[0]['pending'] == []
    assert results[0]['done'][0]['summary'] == REVIEW_TEXT
    assert results[0]['done'][0]['status'] == 'completed'

    # ...và bước kế tiếp của nó đã đọc hàng đã bơm (T12), đúng một lần.
    blocks = injected_blocks(store, testing)
    assert len(blocks) == 1 and REVIEW_TEXT in blocks[0]
    assert '[Muốn đọc thêm: peer_read(' in blocks[0]

    testing_calls = calls_of(TEST_GOAL, runtime.client.calls)
    assert len(testing_calls) == 3, 'terminal_exec → await_children → câu trả lời cuối'
    assert not any(REVIEW_TEXT in json.dumps(messages, ensure_ascii=False)
                   for messages in testing_calls[:-1]), \
        'bản soát chỉ tới ở ranh giới bước SAU cơn chờ, không sớm hơn'
    assert REVIEW_TEXT in json.dumps(testing_calls[-1], ensure_ascii=False)

    # (e) câu trả lời cuối của `testing` trích được bản soát.
    final = [event['data']['text'] for event in store.events(testing)
             if event['type'] == 'assistant' and event['data'].get('final')]
    assert final[-1] == TEST_FINAL and 'thiếu kiểm tra biên' in final[-1]

    # Cha cũng chờ `testing` tới lúc nó đóng sổ, và cha có hàng biên nhận của con ruột hay không
    # đều không quan trọng: kết quả của con tới cha bằng event `child`.
    parent_waits = events_of(store, sid, 'peer_wait_end')
    assert len(parent_waits) == 1 and parent_waits[0]['status'] == 'done'
    assert store.deliveries_of(testing) == []
    store.close()


# --------------------------------------------------------------------------- #
# Biến thể lưới an toàn: hạn của chính người gọi, trong lúc bạn CÒN ĐANG CHẠY
# --------------------------------------------------------------------------- #
def test_chuoi_voi_han_nguoi_goi_thi_luot_van_xong(tmp_path):
    """`testing` tự đặt hạn 1 s trong lúc `review` còn chạy ⇒ `timeout` kèm `pending`, không lỗi.

    Đây là nửa còn lại của hợp đồng T9: chờ bạn không bao giờ được biến thành lượt hỏng, và chỗ gọi
    phải nhìn thấy rõ ai chưa giao để chạy tiếp với dữ liệu đang có (`peer_read` là đường đọc thêm).
    """
    parent, children = chain_script({'targets': ['role:review'], 'mode': 'all',
                                     'timeoutSeconds': 1},
                                    'chưa có bản soát, ghi lại việc còn thiếu')
    store, runtime, sid = build(tmp_path, parent, children, slow={'file_read'}, seconds=3.0)

    run_turn(runtime, sid, 'chờ có hạn rồi chạy tiếp')

    rows = child_rows(store, sid)
    testing = rows['testing']['session_id']
    assert store.get(sid)['status'] == 'completed'
    assert rows['testing']['status'] == 'completed'
    assert events_of(store, sid, 'error') == []
    assert not any(result.get('is_error') for child in rows.values()
                   for result in tool_results(store, child['session_id']))

    wait_ends = events_of(store, testing, 'peer_wait_end')
    assert len(wait_ends) == 1, wait_ends
    assert wait_ends[0]['status'] == 'timeout'
    assert [row['role'] for row in wait_ends[0]['pending']] == ['review']
    assert wait_ends[0]['done'] == []
    assert wait_ends[0]['forced'] is False, 'hạn của chính người gọi, không phải watchdog cắt'
    assert wait_ends[0]['extensionExhausted'] is False
    assert wait_ends[0]['waitedMs'] >= 900, wait_ends[0]['waitedMs']

    results = [item for item in tool_results(store, testing) if 'status' in item and 'pending' in item]
    assert results[0]['status'] == 'timeout' and results[0]['done'] == []
    assert [row['role'] for row in results[0]['pending']] == ['review']

    # Lượt vẫn xong và vẫn có câu trả lời cuối: chờ hụt KHÔNG làm lượt hỏng.
    final = [event['data']['text'] for event in store.events(testing)
             if event['type'] == 'assistant' and event['data'].get('final')]
    assert final[-1] == 'chưa có bản soát, ghi lại việc còn thiếu'
    # Cha chờ con ruột: con đóng sổ (dù chưa giao cho cha hàng nào) là cha được giải phóng.
    parent_waits = events_of(store, sid, 'peer_wait_end')
    assert len(parent_waits) == 1 and parent_waits[0]['status'] == 'done'
    store.close()


# --------------------------------------------------------------------------- #
# Biến thể opt-in: chạy đúng kịch bản trên qua harness SỐNG (T17 dùng lại)
# --------------------------------------------------------------------------- #
HARNESS_URL = os.environ.get('BOXFOX_HARNESS_URL', 'http://127.0.0.1:3102')
LIVE_DB = pathlib.Path(os.environ.get('BOXFOX_LIVE_DB', '~/BoxFox/harness/sessions.sqlite')).expanduser()
LIVE_CONNECTION = os.environ.get('BOXFOX_LIVE_CONNECTION_ID', '7c59f6b5-d0ee-4206-9d04-bc19936b0681')
LIVE_MODEL = os.environ.get('BOXFOX_LIVE_MODEL_ID', 'muse-spark-1.3-contributor-free')
LIVE_PROMPT = (
    'Làm đúng ba việc này trong MỘT lượt, không hỏi lại:\n'
    '1. `delegate_task` cho vai `testing`, wait=false, goal: "chạy đúng một lệnh `printf xong` bằng '
    'terminal_exec rồi trả lời một dòng".\n'
    '2. `delegate_task` cho vai `review`, wait=false, deliverTo=["main","role:testing"], goal: '
    '"trả lời ngay đúng một dòng, không gọi công cụ nào".\n'
    '3. `await_children` với targets=["role:testing"], mode="all", KHÔNG truyền timeoutSeconds.\n'
    'Sau đó trả lời ngắn: đã chạy hay chưa.'
)


def live_call(method, path, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f'{HARNESS_URL}{path}', data=body, method=method,
        headers={'X-BoxFox-Admin': '1', 'Origin': 'http://localhost:3100',
                 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw or '{}')


def live_rows(sql, args=()):
    db = sqlite3.connect(f'file:{LIVE_DB}?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in db.execute(sql, args)]
    finally:
        db.close()


@pytest.mark.skipif(os.environ.get('BOXFOX_LIVE_PEER_MESH') != '1',
                    reason='biến thể sống: bật bằng BOXFOX_LIVE_PEER_MESH=1')
def test_chuoi_tren_harness_song(capsys):
    """Chạy L1 qua harness sống rồi đọc lại SỔ THẬT — bằng chứng sống của đợt 2.

    Không dựng lại runtime trong tiến trình kiểm thử: cái được đo là đường HTTP thật + mô hình thật
    + SQLite thật của harness. Khẳng định ở đây cố ý thô (số con, có cặp chờ, có biên nhận, không
    lượt nào `failed`, không con nào bị cắt) vì mô hình sống có quyền chọn cách làm khác; phần in ra
    là bằng chứng để T17 chép vào nhật ký vòng. Cơn chờ đọc ở **luồng của cha** — `peer_wait` là
    chuyện của người chờ, không phải của con.
    """
    assert LIVE_DB.exists(), f'không thấy sổ sống: {LIVE_DB}'
    created = live_call('POST', '/api/agent/sessions',
                        {'skills': [], 'connectionId': LIVE_CONNECTION, 'modelId': LIVE_MODEL,
                         'peerWaitMax': 60})
    sid = created['id']
    live_call('POST', f'/api/agent/sessions/{sid}/turns', {'prompt': LIVE_PROMPT})

    deadline = time.monotonic() + 300
    status = 'running'
    while time.monotonic() < deadline:
        status = live_call('GET', f'/api/agent/sessions/{sid}')['status']
        if status not in ('running', 'awaiting_decision'):
            break
        time.sleep(2)
    assert status == 'completed', f'lượt sống kết thúc ở trạng thái {status!r}'

    children = live_rows('SELECT * FROM children WHERE parent_id=? ORDER BY started', (sid,))
    events = {}
    for session_id in [sid] + [row['session_id'] for row in children]:
        rows = live_rows('SELECT * FROM events WHERE session_id=? ORDER BY seq', (session_id,))
        events[session_id] = [json.loads(row['payload']) for row in rows]
    receipts = live_rows('SELECT * FROM child_deliveries WHERE child_id IN '
                         f'({",".join("?" for _ in children)})',
                         tuple(row['session_id'] for row in children)) if children else []

    parent_waits = [item for item in events[sid] if item.get('waitsUntilDelivery')]
    parent_ends = [item for item in events[sid] if 'extensionExhausted' in item]
    finish = [item for item in events[sid] if item.get('childCount') is not None]

    with capsys.disabled():
        print(f'\n[SỐNG] phiên {sid} — {status}, {len(children)} con, {len(receipts)} biên nhận')
        for row in children:
            print(f'  con {row["role"]:9s} lượt {row["parent_turn"]} bước {row["spawn_step"]} '
                  f'→ {row["status"]:9s} steps={row["steps_used"]} tokens={row["output_tokens"]}')
        for row in receipts:
            print(f'  biên nhận {row["kind"]:4s} → {row["recipient"][:8]} {row["state"]}')
        for item in parent_waits:
            print(f'  cha chờ: {item.get("targets")} mode={item.get("mode")} '
                  f'hạn-an-toàn={item.get("safetySeconds")}s')
        for item in parent_ends:
            print(f'  hết chờ: {item.get("status")} chờ={item.get("waitedMs")}ms '
                  f'còn-lại={[t.get("role") for t in item.get("pending") or []]}')
        for item in finish:
            print('  chốt lượt: ' + json.dumps({k: item[k] for k in
                  ('status', 'turn', 'steps', 'waitedMs', 'childCount', 'childSteps',
                   'childTokens', 'childDeliveries') if k in item}, ensure_ascii=False))

    assert children, 'lượt sống phải sinh ít nhất một con'
    assert all(row['parent_turn'] == 1 for row in children), children
    assert parent_waits, 'cha phải thật sự chờ bạn (peer_wait có waitsUntilDelivery)'
    assert [item for item in parent_ends if item.get('status') == 'done'], \
        f'cơn chờ phải khép bằng `done`: {parent_ends}'
    assert any(row['state'] == 'injected' for row in receipts), \
        f'phải có ít nhất một biên nhận đã bơm: {[dict(row) for row in receipts]}'
    assert not [item for item in events[sid] if item.get('status') == 'failed'], \
        'lượt sống không được có mục nào `failed`'
    assert not [item for item in events[sid] if item.get('reaped')], \
        'lượt sống không được cắt con giữa đường (PARENT_TURN_ENDED)'

