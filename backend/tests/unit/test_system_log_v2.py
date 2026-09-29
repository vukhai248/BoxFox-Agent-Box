"""Bản v2 của nhật ký hệ thống: đường đọc, vòng đời "chạy mới ghi", và API chỉ đọc.

Ba thứ được kiểm ở đây, đúng theo `docs/plan/dev-system-log-plan.md` §3:

* đường đọc (`read_entries` / `SystemLog.read`) — lọc theo level/source/session/event/since,
  chặn trần `MAX_READ_LINES`, và **che bí mật lần thứ hai** trên đường ra: file có thể bị
  sửa tay hoặc do bản cũ ghi, nên API không được tin nội dung file;
* vòng đời của chủ dự án — *log chỉ ghi khi chạy, đóng boxfox thì reset*: tắt êm thì file
  đang ghi đổi tên thành `harness.previous.jsonl` (chỉ giữ đúng một file trước, đĩa không
  phình), còn bị kill cứng thì **không** mất gì;
* route `GET /api/agent/system-log` — thiếu file thì trả danh sách rỗng (không 500), tham số
  sai thì 400, và vẫn nằm sau đúng hàng rào `X-BoxFox-Admin` như mọi route `/api/agent/*`.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.api import server as api_server
from agentbox.api.server import MAX_READ_LINES, create_app
from agentbox.observability.system_log import (DEFAULT_READ_LINES, SystemLog, clamp_lines,
                                               read_entries, redact_entry, since_cutoff)

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
ROUTE = '/api/agent/system-log'


def _iso(seconds_ago: float = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return stamp.strftime('%Y-%m-%dT%H:%M:%S') + '.000Z'


def _log(tmp_path, **kwargs):
    return SystemLog(directory=tmp_path, source='harness', filename='harness.jsonl', **kwargs)


def _append(path, **entry):
    """Ghi thẳng vào file, KHÔNG qua writer — giả lập file bị sửa tay / do bản cũ ghi."""
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + '\n')


from agentbox.memory.session_store import SessionStore


class FixtureStore(SessionStore):
    def __init__(self):
        from pathlib import Path
        super().__init__(Path(':memory:'))


class FixtureRuntime:
    """Vừa đủ để `create_app` dựng lên: route nhật ký không chạm tới runtime."""

    def __init__(self):
        self.store = FixtureStore()
        self.tasks = {}

    async def stop(self, sid):
        return None


def _api(tmp_path, monkeypatch, run_id: str | None = None):
    """Trỏ app sang một instance nhật ký trong thư mục tạm (không đụng log thật)."""
    log = SystemLog(directory=tmp_path, source='harness', filename='harness.jsonl', run_id=run_id)
    monkeypatch.setattr(api_server, 'system_log', log)
    return log


# ------------------------------------------------------------------ đường đọc

def test_read_filters_by_level_source_event_and_session_prefix(tmp_path):
    log = _log(tmp_path)
    log.write('turn.start', session_id='deadbeef-1111', model='gemini')
    log.write('tool.end', session_id='deadbeef-1111', tool='terminal')
    log.write('turn.end', session_id='cafebabe-2222', status='completed')
    log.error('turn.failed', session_id='cafebabe-2222', code='DEADLINE', message='hết hạn')

    assert len(log.read()) == 4
    assert [entry['event'] for entry in log.read(level='error')] == ['turn.failed']
    assert log.read(event='tool.end')[0]['data']['tool'] == 'terminal'
    # session khớp theo TIỀN TỐ: panel và CLI đều chỉ hiện 8 ký tự đầu.
    assert [entry['sessionId'] for entry in log.read(session_id='deadbeef')] == ['deadbeef-1111'] * 2
    assert log.read(session_id='deadbeef-1111') == log.read(session_id='deadbeef')
    assert log.read(session_id='không-có') == []
    assert [entry['sessionId'] for entry in log.read(session_id='cafebabe', level='error')] == ['cafebabe-2222']


def test_read_filters_by_source_across_two_files(tmp_path):
    harness = _log(tmp_path)
    harness.write('turn.start', session_id='s1')
    router = SystemLog(directory=tmp_path, source='router', filename='router.jsonl')
    router.write('route.decided', session_id='s1', model='claude')
    _append(tmp_path / 'harness.jsonl', ts=_iso(-1), level='info', source='harness', event='turn.end', sessionId='s1')

    merged = read_entries([harness.path, router.path])
    # Gộp hai file rồi sắp theo `ts`, mới nhất ở cuối — đúng thứ tự CLI `--file all` in ra.
    assert [entry['event'] for entry in merged] == ['turn.start', 'route.decided', 'turn.end']
    assert sorted(entry['ts'] for entry in merged) == [entry['ts'] for entry in merged]
    assert [entry['event'] for entry in read_entries([harness.path, router.path], source='router')] == ['route.decided']


def test_read_returns_the_tail_and_clamps_lines(tmp_path):
    log = _log(tmp_path)
    for index in range(6):
        log.write('turn.end', session_id='s1', index=index)
    assert [entry['data']['index'] for entry in log.read(lines=2)] == [4, 5]
    assert len(log.read(lines=99999)) == 6  # trần chỉ chặn bên dưới, không bịa thêm dòng

    assert clamp_lines(None) == DEFAULT_READ_LINES == 100
    assert clamp_lines('') == 100
    assert clamp_lines('7') == 7
    assert clamp_lines(0) == 1, 'luôn có ít nhất một dòng'
    assert clamp_lines(99999) == MAX_READ_LINES == 500
    with pytest.raises(ValueError):
        clamp_lines('abc')


def test_read_since_accepts_minutes_and_iso_timestamps(tmp_path):
    path = tmp_path / 'harness.jsonl'
    _append(path, ts=_iso(7200), level='error', source='harness', event='turn.failed', code='CŨ')
    _append(path, ts=_iso(30), level='error', source='harness', event='turn.failed', code='MỚI')

    assert [entry['code'] for entry in read_entries([path], since='60')] == ['MỚI']
    assert [entry['code'] for entry in read_entries([path], since='100000')] == ['CŨ', 'MỚI']
    assert len(read_entries([path], since='2020-01-01T00:00:00')) == 2
    assert len(read_entries([path], since='2020-01-01 00:00')) == 2, 'dấu cách cũng được chấp nhận'
    assert read_entries([path], since='2999-01-01T00:00:00') == []
    assert since_cutoff(None) is None and since_cutoff('  ') is None
    with pytest.raises(ValueError):
        since_cutoff('hôm qua')
    with pytest.raises(ValueError):
        since_cutoff('-5')


def test_read_skips_unparseable_and_partial_lines(tmp_path):
    log = _log(tmp_path)
    log.write('turn.start', session_id='s1')
    path = tmp_path / 'harness.jsonl'
    with path.open('a', encoding='utf-8') as handle:
        handle.write('{"ts": "2026-01-01T00:00:00", "level": "info"')  # dòng dở dang
        handle.write('\nnot json at all\n["không phải object"]\n')
    log.write('turn.end', session_id='s1', status='completed')
    assert [entry['event'] for entry in log.read()] == ['turn.start', 'turn.end']


def test_read_never_raises_on_a_missing_file(tmp_path):
    assert read_entries([tmp_path / 'chưa-có.jsonl']) == []
    assert _log(tmp_path).read() == []


# ------------------------------------------------- che bí mật lần thứ hai (đường ra)

def test_read_redacts_secrets_that_the_writer_never_saw(tmp_path):
    """File có thể bị sửa tay hoặc do bản cũ ghi: đường ra phải tự che, không tin file."""
    path = tmp_path / 'harness.jsonl'
    _append(path, ts=_iso(), level='info', source='harness', event='chat.call',
            data={'apiKey': 'sk-live-leaked', 'headers': {'Authorization': 'Bearer abc', 'token': 't'},
                  'nested': [{'password': 'p'}], 'safe': 'giữ lại'})
    assert 'sk-live-leaked' in path.read_text(), 'đúng là bí mật có trong file'

    entry = read_entries([path])[0]
    assert entry['data']['apiKey'] == '[redacted]'
    assert entry['data']['headers']['Authorization'] == '[redacted]'
    assert entry['data']['headers']['token'] == '[redacted]'
    assert entry['data']['nested'][0]['password'] == '[redacted]'
    assert entry['data']['safe'] == 'giữ lại', 'không được che lây'
    assert 'sk-live-leaked' not in json.dumps(read_entries([path]), ensure_ascii=False)

    assert read_entries([path], redact=False)[0]['data']['apiKey'] == 'sk-live-leaked', 'giữ nguyên khi được yêu cầu'
    assert redact_entry({'apiKey': 'x', 'other': 1}) == {'apiKey': '[redacted]', 'other': 1}


# ------------------------------------------------------------------- vòng đời

def test_every_line_carries_the_run_id(tmp_path):
    log = _log(tmp_path)
    log.write('turn.start', session_id='s1')
    log.write('turn.end', session_id='s1')
    entries = log.read()
    assert {entry['runId'] for entry in entries} == {log.run_id}
    assert all('runId' in entry for entry in read_entries([log.path]))

    other = _log(tmp_path)
    assert other.run_id != log.run_id, 'hai lần chạy khác nhau phải phân biệt được'
    assert len(other.run_id.split('-')) == 3


def test_graceful_shutdown_resets_the_active_file(tmp_path):
    log = _log(tmp_path)
    log.write('turn.start', session_id='s1')
    log.error('turn.failed', session_id='s1', code='UPSTREAM_UNREACHABLE', message='mất kết nối')
    log.write('harness.stop', port=3102)

    previous = log.rotate_on_shutdown()
    assert previous == tmp_path / 'harness.previous.jsonl'
    assert previous.exists() and not (tmp_path / 'harness.jsonl').exists()
    saved = [json.loads(line) for line in previous.read_text().strip().split('\n')]
    assert [entry['event'] for entry in saved] == ['turn.start', 'turn.failed', 'harness.stop']

    # Lần chạy sau mở file mới, rỗng; file trước vẫn còn nguyên để tra cứu.
    log.write('turn.start', session_id='s2')
    assert [entry['sessionId'] for entry in log.read()] == ['s2']
    assert log.read()[0]['runId'] == log.run_id

    # Reset lần nữa: chỉ giữ ĐÚNG MỘT file trước, đĩa không phình theo số lần chạy.
    log.rotate_on_shutdown()
    assert sorted(path.name for path in tmp_path.glob('harness*.jsonl*')) == ['harness.previous.jsonl']
    assert 's2' in (tmp_path / 'harness.previous.jsonl').read_text()
    assert log.rotate_on_shutdown() is None, 'không còn file đang ghi thì không làm gì'


def test_a_hard_kill_never_loses_the_file(tmp_path):
    """Bị kill cứng thì không chạy được dòng reset nào — file phải còn nguyên."""
    log = _log(tmp_path)
    log.write('turn.start', session_id='s1')
    # Không gọi reset, và một instance mới (lần chạy sau) cũng không được tự ý dọn file.
    _log(tmp_path)
    assert (tmp_path / 'harness.jsonl').exists()
    assert not (tmp_path / 'harness.previous.jsonl').exists()
    assert [entry['sessionId'] for entry in read_entries([tmp_path / 'harness.jsonl'])] == ['s1']


def test_a_locked_directory_never_raises_on_reset(tmp_path, monkeypatch):
    log = _log(tmp_path)
    log.write('turn.start', session_id='s1')

    def boom(*args, **kwargs):
        raise OSError('ổ đĩa chỉ đọc')

    monkeypatch.setattr('pathlib.Path.replace', boom)
    assert log.rotate_on_shutdown() is None  # phải im lặng như mọi đường ghi khác


# ------------------------------------------------------------ route chỉ đọc

def _get_many(tmp_path, monkeypatch, queries, headers=None, run_id=None):
    """Gửi nhiều request trong MỘT server: đóng server là "tắt êm", mà tắt êm thì reset file."""
    async def run():
        _api(tmp_path, monkeypatch, run_id=run_id)
        answers = []
        async with TestServer(create_app(FixtureRuntime())) as server:
            async with ClientSession(headers=headers if headers is not None else HEADERS) as client:
                for query in queries:
                    async with client.get(str(server.make_url(ROUTE)) + query) as response:
                        answers.append((response.status, await response.json()))
        return answers

    return asyncio.run(run())


def _get(tmp_path, monkeypatch, query='', headers=None, run_id=None):
    return _get_many(tmp_path, monkeypatch, [query], headers=headers, run_id=run_id)[0]


def test_api_answers_an_empty_list_when_the_log_does_not_exist(tmp_path, monkeypatch):
    status, body = _get(tmp_path, monkeypatch)
    assert status == 200, 'thiếu file chỉ là "chưa chạy lần nào", không phải lỗi 500'
    assert body['entries'] == [] and body['count'] == 0
    assert body['exists'] is False
    assert body['file'] == 'harness.jsonl'
    assert body['lines'] == DEFAULT_READ_LINES and body['cap'] == MAX_READ_LINES
    assert body['runId'] and body['version'] == api_server.HARNESS_VERSION
    assert 'commit' in body


def test_api_serves_the_tail_filters_and_redaction(tmp_path, monkeypatch):
    log = _api(tmp_path, monkeypatch, run_id='run-1')
    log.write('turn.start', session_id='deadbeef-1111')
    log.error('turn.failed', session_id='deadbeef-1111', code='UPSTREAM_UNREACHABLE', message='mất kết nối')
    _append(tmp_path / 'harness.jsonl', ts=_iso(-2), level='error', source='harness', event='chat.call',
            sessionId='deadbeef-1111', code='BAD_KEY', data={'apiKey': 'sk-live-leaked'})

    (status, body), (status2, filtered), (status3, by_source) = _get_many(
        tmp_path, monkeypatch, ['', '?level=error&sessionId=deadbeef', '?source=router'], run_id='run-1')

    assert status == 200
    assert body['exists'] is True and body['count'] == 3
    assert body['runId'] == 'run-1'
    assert [entry['event'] for entry in body['entries']] == ['turn.start', 'turn.failed', 'chat.call']
    assert 'sk-live-leaked' not in json.dumps(body, ensure_ascii=False), 'che lần hai ngay trên đường ra'

    assert status2 == 200
    assert [entry['code'] for entry in filtered['entries']] == ['UPSTREAM_UNREACHABLE', 'BAD_KEY']
    assert [entry['event'] for entry in filtered['entries']] == ['turn.failed', 'chat.call']

    assert status3 == 200 and by_source['entries'] == []


def test_api_caps_lines_and_refuses_bad_filters(tmp_path, monkeypatch):
    log = _api(tmp_path, monkeypatch)
    for index in range(3):
        log.write('turn.end', session_id='s1', index=index)

    queries = ['?lines=99999', '?lines=2', '?level=trace', '?lines=abc', '?since=nope']
    answers = _get_many(tmp_path, monkeypatch, queries)
    (capped, capped_body), (trimmed, trimmed_body) = answers[0], answers[1]
    (bad_level, level_body), (bad_lines, lines_body), (bad_since, since_body) = answers[2:]

    assert capped == 200 and capped_body['lines'] == MAX_READ_LINES
    assert trimmed == 200 and trimmed_body['lines'] == 2
    assert [entry['data']['index'] for entry in trimmed_body['entries']] == [1, 2]

    assert (bad_level, bad_lines, bad_since) == (400, 400, 400)
    assert 'level must be one of' in level_body['error']
    assert 'lines must be a whole number' in lines_body['error']
    assert 'since must be' in since_body['error']


def test_api_stays_behind_the_admin_boundary(tmp_path, monkeypatch):
    """Nhật ký là thứ chỉ chủ máy đọc được: thiếu hàng rào local-admin thì 403."""
    log = _api(tmp_path, monkeypatch)
    log.write('turn.start', session_id='s1')

    status, body = _get(tmp_path, monkeypatch, headers={'Host': '127.0.0.1:3102'})
    assert status == 403
    assert 's1' not in json.dumps(body)

    status, body = _get(tmp_path, monkeypatch, headers={**HEADERS, 'Host': 'evil.example.com'})
    assert status == 403


def test_api_resets_on_a_graceful_shutdown(tmp_path, monkeypatch):
    """Đóng êm: `harness.stop` được ghi vào đúng file của lượt chạy rồi file được reset."""
    log = _api(tmp_path, monkeypatch)
    log.write('turn.start', session_id='s1')

    async def run():
        async with TestServer(create_app(FixtureRuntime())) as server:
            async with ClientSession(headers=HEADERS) as client:
                async with client.get(str(server.make_url(ROUTE))) as response:
                    assert response.status == 200
                    assert (await response.json())['exists'] is True
        return None

    asyncio.run(run())

    previous = tmp_path / 'harness.previous.jsonl'
    assert previous.exists(), 'tắt êm phải reset file đang ghi'
    assert not (tmp_path / 'harness.jsonl').exists()
    logged = [json.loads(line) for line in previous.read_text().strip().split('\n')]
    assert [entry['event'] for entry in logged] == ['turn.start', 'harness.stop']
    assert logged[-1]['data']['pid'] == os.getpid()
    assert {entry['runId'] for entry in logged} == {log.run_id}, 'dấu kết thúc phải thuộc đúng lượt chạy vừa rồi'
