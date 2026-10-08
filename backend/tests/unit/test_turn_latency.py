"""Reader `tools/turn_latency.py` — đo MỘT LƯỢT CUA từ đề nghị đến trả lời (nhóm K của kế hoạch v2).

Fixture dựng SQLite tạm bằng đúng `CREATE TABLE` của `agentbox/memory/session_store.py:24-26`
(`events(seq, session_id, kind, payload, created)`) rồi ghi tay các hàng với `created` đặt lệch nhau
ĐÚNG số mong đợi — payload không mang mốc thời gian, nên mọi ms phải đọc từ cột `created`.

Sáu ca, theo K3 của kế hoạch:
1. lượt CUA hoàn tất: các phần cộng đúng bằng tổng;
2. lượt hỏng không có tool: dựng lại ĐÚNG hình dạng lượt thật trên máy này (UPSTREAM_HTTP_503);
3. lệch số: `wallMs` cách `harnessMs` 3 000 ms ⇒ có dòng `LỆCH`, `wallMs` vẫn là số chính;
4. thiếu mốc (lượt chưa đóng) và hàng cũ thiếu `turn` (gom theo dãy `seq` giữa hai `user`);
5. store rỗng / thiếu bảng / thiếu tệp: in `CHƯA ĐO ĐƯỢC`, thoát mã 2, không traceback;
6. alias `cua_bench turn` trả ĐÚNG số của reader (không tính lại theo cách khác).

Hai ca thêm sau soát 08/10/2026: đọc store WAL **không để lại dấu vết** trong thư mục sổ (kể cả thư mục
chỉ-đọc) — cả ba ca đó ĐỔ nếu quay lại mở thẳng tệp gốc bằng `?mode=ro` — và câu `chưa đo được lượt CUA
nào` phải nói rõ cửa sổ `--limit` khi ca CUA bị cắt khỏi báo cáo.
"""
import importlib.util
import json
import os
import pathlib
import sqlite3

import pytest

_TOOLS = pathlib.Path(__file__).resolve().parents[2] / 'tools'
_READER = _TOOLS / 'turn_latency.py'
_BENCH = _TOOLS / 'cua_bench.py'

#: Lược đồ y hệt `agentbox/memory/session_store.py:24-26`.
_SCHEMA = """
CREATE TABLE events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
    kind TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
"""

_BASE = 1_790_000_000.0
_SID = 'dac7c517-0000-0000-0000-000000000000'
_INVOCATION = '6b373920-c467-456b-bff0-812b2926e4b8'


def _reader():
    spec = importlib.util.spec_from_file_location('turn_latency_under_test', _READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bench():
    spec = importlib.util.spec_from_file_location('cua_bench_under_test', _BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _store(tmp_path, rows, *, session_id=_SID, name='sessions.sqlite'):
    """Ghi các hàng `(kind, payload, created)` vào một store SQLite tạm; trả đường dẫn."""
    db = tmp_path / name
    con = sqlite3.connect(db)
    con.executescript(_SCHEMA)
    for kind, payload, created in rows:
        con.execute('INSERT INTO events (session_id, kind, payload, created) VALUES (?,?,?,?)',
                    (session_id, kind, json.dumps(payload), created))
    con.commit()
    con.close()
    return db


def _wal_store(tmp_path, rows, *, wal=b'', shm=None):
    """Store ở chế độ WAL, kèm dấu vết sidecar còn lại (`-wal` 0 byte như máy chủ nhà 08/10/2026)."""
    db = _store(tmp_path, rows)
    con = sqlite3.connect(db, isolation_level=None)
    try:
        assert con.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
    finally:
        con.close()
    if wal is not None:
        pathlib.Path(str(db) + '-wal').write_bytes(wal)
    if shm is not None:
        pathlib.Path(str(db) + '-shm').write_bytes(shm)
    return db


def _completed_rows():
    """Lượt CUA hoàn tất: bước 1 500 ms, hai lời gọi tool 120 + 80 ms, trả lời ở 1 720 ms.

    Con số trong kế hoạch §K3.1: `toolMs == 200`, model = khoảng bước − tool, `unaccountedMs == 0`,
    `wallMs` khớp hằng số. Fixture đặt `deadlineUsedMs` = khoảng bước (1 500 ms) nên ba phần
    `model + vòng lặp` + `tool` + `thân harness` cộng đúng bằng `harnessMs` — đó là bất biến được ghim.
    """
    return [
        ('user', {'text': 'Mở Notepad và gõ "xin chào"', 'turn': 1, 'invocationId': _INVOCATION},
         _BASE),
        ('turn_start', {'turn': 1, 'step': 1, 'modelId': 'zen/free', 'contextWindow': 256000,
                        'threshold': 176332, 'contextEstimate': 25766}, _BASE + 0.2),
        ('tool_start', {'id': 'call-1', 'name': 'computer_use', 'args': {'action': 'type'}}, _BASE + 0.25),
        ('tool_end', {'id': 'call-1', 'name': 'computer_use', 'args': {'action': 'type'},
                      'result': {'ok': True}}, _BASE + 0.37),
        ('tool_start', {'id': 'call-2', 'name': 'computer_screen_capture', 'args': {}}, _BASE + 0.4),
        ('tool_end', {'id': 'call-2', 'name': 'computer_screen_capture', 'args': {},
                      'result': {'ok': True}}, _BASE + 0.48),
        ('turn_end', {'turn': 1, 'step': 1, 'status': 'completed', 'finishReason': 'stop',
                      'toolCalls': 2, 'contextEstimate': 26000, 'stepsUsed': 2, 'toolsRun': 2,
                      'deadlineUsedMs': 1500}, _BASE + 1.7),
        ('assistant', {'text': 'Xong.', 'thought': '', 'final': True}, _BASE + 1.72),
        ('finish', {'status': 'completed', 'turn': 1, 'steps': 2, 'waitedMs': 0,
                    'extensionMs': 0}, _BASE + 1.74),
    ]


def _failed_rows():
    """ĐÚNG hình dạng lượt thật trên máy này (đo 08/10/2026): hỏng ở tầng định tuyến, 0 tool."""
    return [
        ('command_resolved', {'kind': 'message', 'command': '', 'prompt': 'Summarize the quarterly '
                              'report and flag any risks', 'role': 'orchestrator', 'executor': 'native',
                              'skills': [], 'revision': 0, 'reason': 'ordinary_message',
                              'invocationId': _INVOCATION}, 1791385152.8823133),
        ('user', {'text': 'Summarize the quarterly report and flag any risks', 'turn': 1,
                  'invocationId': _INVOCATION}, 1791385152.901688),
        ('notice', {'code': 'JOURNAL_DEGRADED', 'message': 'JOURNAL_DEGRADED: ...',
                    'op': 'session_ensure'}, 1791385152.9284132),
        ('step', {'turn': 1, 'iteration': 1, 'contextEstimate': 25766}, 1791385152.9328473),
        ('turn_start', {'turn': 1, 'step': 1, 'modelId': None, 'contextWindow': 256000,
                        'threshold': 176332, 'contextEstimate': 25766}, 1791385152.9365199),
        ('harness_usage', {'callKey': 'call-4fb2f43e628945558e3a096fdcfa13ac', 'purpose': 'completion',
                           'amount': None, 'certainty': 'unknown'}, 1791385153.0371907),
        ('recovery_decision', {'code': 'UPSTREAM_HTTP_503', 'class': 'transport',
                               'action': 'retry_backoff', 'replay': False, 'keepsPartial': False,
                               'checkpoint': False, 'reason': 'lỗi tạm thời: backoff rồi thử lại'},
         1791385153.042719),
        ('turn_end', {'turn': 1, 'step': 1, 'status': 'error', 'finishReason': None, 'toolCalls': 0,
                      'contextEstimate': 25766, 'stepsUsed': 1, 'toolsRun': 0,
                      'deadlineUsedMs': 142}, 1791385153.0474362),
        ('error', {'message': 'UPSTREAM_HTTP_503: the model router answered Router HTTP 503',
                   'code': 'UPSTREAM_HTTP_503'}, 1791385153.0555313),
    ]


def test_a_completed_cua_turn_splits_into_parts_that_add_up(tmp_path):
    reader = _reader()
    db = _store(tmp_path, _completed_rows())
    report = reader.read_turns(db)

    assert set(report) == {'generatedAt', 'db', 'sessions', 'turns', 'cases', 'notes'}
    assert len(report['turns']) == 1
    turn = report['turns'][0]

    assert turn['cua'] is True, 'hai tool CUA phải đánh dấu lượt là ca CUA'
    assert turn['toolMs'] == 200.0, 'hai lời gọi 120 + 80 ms'
    assert turn['modelMs'] == 1300.0, 'model + vòng lặp = khoảng bước (1500) − tool (200)'
    assert turn['harnessMs'] == 1500.0
    assert turn['unaccountedMs'] == 0.0, 'fixture đặt deadlineUsedMs = khoảng bước nên không dư'
    assert turn['wallMs'] == 1720.0
    assert turn['closedMs'] == 1740.0
    assert turn['outsideMs'] == 220.0
    assert (turn['stepsUsed'], turn['toolsRun']) == (2, 2)
    assert (turn['status'], turn['finishReason']) == ('completed', 'stop')
    assert turn['notes'] == [], 'lượt sạch thì không có ghi chú LỆCH nào'
    assert 'chưa đo được lượt CUA nào' not in report['notes']

    # Bất biến của phép chia: ba phần cộng đúng bằng harness, thêm ngoài lượt là đúng bằng wall.
    assert round(turn['modelMs'] + turn['toolMs'] + turn['unaccountedMs'], 1) == turn['harnessMs']
    assert round(turn['harnessMs'] + turn['outsideMs'], 1) == turn['wallMs']

    assert len(report['cases']) == 1
    case = report['cases'][0]
    assert case['wallMs'] == 1720.0 and case['toolMs'] == 200.0
    assert case['toolsRun'] == 2 and case['stepsUsed'] == 2 and case['status'] == 'completed'
    assert case['label'].startswith('Mở Notepad') and case['label'].endswith(_INVOCATION[:8])


def test_a_failed_turn_without_tools_is_not_a_cua_case(tmp_path, capsys):
    reader = _reader()
    db = _store(tmp_path, _failed_rows())
    report = reader.read_turns(db)

    assert len(report['turns']) == 1
    turn = report['turns'][0]
    assert turn['cua'] is False and turn['toolsRun'] == 0
    assert turn['status'] == 'error' and turn['stepsUsed'] == 1
    assert turn['harnessMs'] == 142.0
    # `user.created` → `turn_end.created` = 145,7 ms (đo thật); `deadlineUsedMs` = 142 ms.
    assert turn['wallMs'] == 145.7
    assert turn['modelMs'] == 110.9, 'khoảng bước 110,9 ms, không có tool nào'
    assert turn['unaccountedMs'] == round(142.0 - 110.9, 1)
    assert turn['outsideMs'] == 3.7
    assert round(turn['modelMs'] + turn['toolMs'] + turn['unaccountedMs'], 1) == turn['harnessMs']
    assert round(turn['harnessMs'] + turn['outsideMs'], 1) == turn['wallMs']

    assert report['cases'] == [], 'lượt hỏng ở định tuyến không phải ca CUA'
    assert report['notes'][0] == 'chưa đo được lượt CUA nào', \
        'không có ca CUA nào ở BẤT KỲ lượt nào thì giữ nguyên câu cũ (không thêm "trong N lượt")'

    code = reader.main(['--db', str(db)])
    out = capsys.readouterr().out
    assert code == 0
    assert 'chưa đo được lượt CUA nào' in out
    assert 'wall 145.7 ms' in out and 'harness 142.0 ms (deadlineUsedMs' in out


def test_disagreeing_wall_and_harness_are_reported_not_hidden(tmp_path):
    reader = _reader()
    rows = [
        ('user', {'text': 'Việc dài', 'turn': 1, 'invocationId': _INVOCATION}, _BASE),
        ('turn_start', {'turn': 1, 'step': 1, 'modelId': None}, _BASE + 0.1),
        ('turn_end', {'turn': 1, 'step': 1, 'status': 'completed', 'finishReason': 'stop',
                      'toolCalls': 0, 'stepsUsed': 1, 'toolsRun': 0, 'deadlineUsedMs': 500},
         _BASE + 0.6),
        ('assistant', {'text': 'Xong.', 'thought': '', 'final': True}, _BASE + 4.1),
    ]
    db = _store(tmp_path, rows)
    turn = reader.read_turns(db)['turns'][0]

    assert turn['wallMs'] == 4100.0, 'wallMs vẫn là số chính dù lệch'
    assert turn['harnessMs'] == 500.0
    assert turn['outsideMs'] == 3600.0
    assert any('LỆCH' in note for note in turn['notes']), 'lệch > 1000 ms phải có dòng LỆCH'
    note = next(note for note in turn['notes'] if 'LỆCH' in note)
    assert 'wall 4100.0 ms' in note and 'deadlineUsedMs 500.0 ms' in note


def test_an_open_turn_reports_no_wall_instead_of_inventing_one(tmp_path):
    reader = _reader()
    rows = [
        ('user', {'text': 'Việc đang chạy', 'turn': 1, 'invocationId': _INVOCATION}, _BASE),
        ('turn_start', {'turn': 1, 'step': 1, 'modelId': None}, _BASE + 0.2),
        ('tool_start', {'id': 'call-1', 'name': 'computer_use', 'args': {}}, _BASE + 0.3),
    ]
    db = _store(tmp_path, rows)
    report = reader.read_turns(db)

    turn = report['turns'][0]
    assert turn['wallMs'] is None and turn['closedMs'] is None
    assert turn['harnessMs'] is None and turn['unaccountedMs'] is None
    assert turn['cua'] is True, 'lời gọi CUA đã bắt đầu nhưng lượt chưa đóng'
    assert any('chưa đóng' in note for note in turn['notes'])
    assert report['cases'][0]['wallMs'] is None


def test_old_rows_without_turn_group_between_user_rows(tmp_path):
    reader = _reader()
    rows = [
        ('user', {'text': 'Lượt cũ không có số turn', 'invocationId': _INVOCATION}, _BASE),
        ('turn_start', {'step': 1, 'modelId': None}, _BASE + 0.2),
        ('turn_end', {'step': 1, 'status': 'completed', 'stepsUsed': 1, 'toolsRun': 0,
                      'deadlineUsedMs': 300}, _BASE + 0.5),
        ('assistant', {'text': 'Xong.', 'final': True}, _BASE + 0.6),
        ('finish', {'status': 'completed'}, _BASE + 0.62),
    ]
    db = _store(tmp_path, rows)
    report = reader.read_turns(db)

    assert len(report['turns']) == 1, 'hàng thiếu `turn` vẫn phải gom được theo mốc `user`'
    turn = report['turns'][0]
    assert turn['turn'] == 1 and turn['harnessMs'] == 300.0 and turn['wallMs'] == 600.0


def test_the_reader_does_not_create_the_shm_of_a_wal_store(tmp_path, capsys):
    """Sổ WAL còn `-wal` 0 byte (đúng dạng đo được trên máy chủ nhà): KHÔNG được tạo tệp trong thư mục sổ.

    Mở thẳng `?mode=ro` vào sổ này làm SQLite tạo `sessions.sqlite-shm` — một dấu vết mới của công cụ
    đo trong thư mục dữ liệu (đo 08/10/2026). Ca này ghim đường đọc qua bản sao tạm; nó ĐỔ nếu quay lại
    mở thẳng tệp gốc.
    """
    reader = _reader()
    db = _wal_store(tmp_path, _completed_rows(), wal=b'')
    before = sorted(path.name for path in tmp_path.iterdir())

    assert reader.main(['--db', str(db)]) == 0

    out = capsys.readouterr().out
    assert 'wall 1720.0 ms' in out, 'vẫn phải đọc đúng hàng của sổ WAL'
    assert sorted(path.name for path in tmp_path.iterdir()) == before, \
        'công cụ đã tạo tệp trong thư mục của sổ'


def test_the_reader_does_not_rewrite_the_shm_of_a_wal_store(tmp_path, capsys):
    """Sổ WAL còn `-shm`: KHÔNG được viết lại nó (đo được: 0 → 32 768 byte, mtime mới mỗi lần chạy)."""
    reader = _reader()
    db = _wal_store(tmp_path, _completed_rows(), wal=b'', shm=b'')
    before = {path.name: (path.stat().st_size, path.stat().st_mtime_ns)
              for path in tmp_path.iterdir()}

    assert reader.main(['--db', str(db)]) == 0

    out = capsys.readouterr().out
    assert 'wall 1720.0 ms' in out
    after = {path.name: (path.stat().st_size, path.stat().st_mtime_ns)
             for path in tmp_path.iterdir()}
    assert after == before, 'công cụ đã chạm vào thư mục của sổ (bản sao tạm bị rò)'


def test_the_reader_still_works_when_the_store_directory_is_read_only(tmp_path, capsys):
    """Thư mục store chỉ-đọc: vẫn đọc được, KHÔNG cần quyền ghi vào đó.

    Mở thẳng `?mode=ro` trong thư mục chỉ-đọc thì SQLite báo `attempt to write a readonly database`
    (đo 08/10/2026) vì nó cần tạo `-shm`; đọc qua bản sao tạm không chạm thư mục gốc. Ca này ĐỔ với
    đường mở thẳng.
    """
    reader = _reader()
    db = _wal_store(tmp_path, _completed_rows(), wal=b'')
    for path in tmp_path.iterdir():
        os.chmod(path, 0o444)
    os.chmod(tmp_path, 0o555)
    try:
        assert reader.main(['--db', str(db)]) == 0
        out = capsys.readouterr().out
        assert '1 ca CUA' in out and 'wall 1720.0 ms' in out
    finally:
        os.chmod(tmp_path, 0o755)
        for path in tmp_path.iterdir():
            os.chmod(path, 0o644)


def test_the_cua_note_says_which_window_when_a_cua_turn_is_outside_the_limit(tmp_path, capsys):
    """Cửa sổ `--limit` cắt mất ca CUA cũ: câu "chưa đo được" phải nói rõ "trong N lượt gần nhất".

    Không được để câu cũ khiến người đọc tưởng cả store không có ca CUA nào (soát 08/10/2026).
    """
    reader = _reader()
    rows = _completed_rows() + [
        ('user', {'text': 'Việc sau, không CUA', 'turn': 2, 'invocationId': _INVOCATION}, _BASE + 10),
        ('turn_start', {'turn': 2, 'step': 1, 'modelId': None}, _BASE + 10.1),
        ('turn_end', {'turn': 2, 'step': 1, 'status': 'completed', 'finishReason': 'stop',
                      'toolCalls': 0, 'stepsUsed': 1, 'toolsRun': 0, 'deadlineUsedMs': 300},
         _BASE + 10.3),
        ('assistant', {'text': 'Xong.', 'final': True}, _BASE + 10.4),
    ]
    db = _store(tmp_path, rows)

    windowed = reader.read_turns(db, limit=1)
    assert windowed['cases'] == [], 'lượt gần nhất không phải ca CUA'
    note = windowed['notes'][0]
    assert note.startswith('chưa đo được lượt CUA nào trong 1 lượt gần nhất'), note
    assert '1 lượt CUA cũ hơn' in note and '--limit 0' in note

    code = reader.main(['--db', str(db), '--limit', '1'])
    out = capsys.readouterr().out
    assert code == 0 and note in out, 'dòng đầu báo cáo phải là câu đã nói rõ cửa sổ'

    everything = reader.read_turns(db, limit=0)
    assert len(everything['cases']) == 1, '`--limit 0` phải thấy ca CUA cũ'
    assert not any(n.startswith('chưa đo được lượt CUA nào') for n in everything['notes'])


@pytest.mark.parametrize('kind', ['empty', 'no_table', 'missing_file'])
def test_an_unreadable_store_says_chua_do_duoc_and_exits_2(tmp_path, capsys, kind):
    reader = _reader()
    if kind == 'empty':
        db = _store(tmp_path, [])
    elif kind == 'no_table':
        db = tmp_path / 'other.sqlite'
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE other (x INTEGER)')
        con.commit()
        con.close()
    else:
        db = tmp_path / 'does-not-exist.sqlite'

    with pytest.raises(reader.StoreUnavailable):
        reader.read_turns(db)

    code = reader.main(['--db', str(db)])
    out = capsys.readouterr().out
    assert code == 2, 'store không đọc được phải thoát mã 2, không được thoát 0'
    assert 'CHƯA ĐO ĐƯỢC' in out
    assert 'chưa đo được lượt CUA nào' not in out


def test_the_gate_trips_on_a_turn_over_the_ceiling(tmp_path, capsys):
    reader = _reader()
    db = _store(tmp_path, _completed_rows())

    assert reader.main(['--db', str(db), '--max-total-ms', '2000']) == 0
    capsys.readouterr()
    assert reader.main(['--db', str(db), '--max-total-ms', '1000']) == 1
    out = capsys.readouterr().out
    assert 'VƯỢT TRẦN' in out and 'wall 1720.0 ms > 1000 ms' in out


def test_cua_bench_turn_alias_returns_the_readers_numbers(tmp_path):
    """K4.2: hai tệp JSON phải giống nhau ở khối `turn` — alias không được tính lại theo cách khác."""
    reader, bench = _reader(), _bench()
    db = _store(tmp_path, _completed_rows())
    out = tmp_path / 'bench-turn.json'

    assert bench.main(['turn', '--db', str(db), '--json', str(out)]) == 0
    payload = json.loads(out.read_text())
    direct = reader.read_turns(db)

    assert payload['turn']['turns'] == direct['turns']
    assert payload['turn']['cases'] == direct['cases']
    assert payload['turn']['sessions'] == direct['sessions']
    assert payload['turn']['db'] == direct['db']
    assert payload['notes'] == direct['notes']
