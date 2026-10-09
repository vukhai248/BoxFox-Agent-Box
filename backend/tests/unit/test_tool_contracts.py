"""Hợp đồng giữa agent và **từ vựng mã lỗi**: câu gửi cho model + công cụ đo từ vựng đó.

Hai phần, cùng một câu hỏi "mã lỗi này nói được gì cho người đọc":

1. `tool_contracts.reflection_hint` — câu model nhận ngay sau một lỗi. Lỗi host/CUA **không** phải
   lỗi hình dạng đối số, nên câu phải là lời khuyên riêng của mã (chụp lại, chờ quyền, cài gói,
   sửa đích…), và ca "kết quả không mang mã" phải trỏ vào `content`/`exit_code`.
2. `backend/tools/tool_errors.py` — công cụ đo chỉ-đọc, chứng minh từ vựng phủ được mã thật và chỉ ra
   mã nào chưa khai. Test của nó nằm ở đây vì đợt này chỉ được sửa hai tệp test
   (`test_recovery_policy.py`, `test_tool_contracts.py`); nội dung vẫn là "hợp đồng lỗi".
"""
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from agentbox.agent_core import recovery_policy
from agentbox.agent_core.tool_contracts import reflection_hint
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox import host_executor as host_executor_module
from agentbox.sandbox.win import errors as win_errors

SCHEMA_SENTENCE = 'Fix only that input'

#: Cùng cách lấy như `test_recovery_policy.HOST_SURFACE_CODES`: từ mã nguồn, không gõ tay danh sách.
HOST_CODES = sorted(
    set(win_errors.ACTION_CODES) | set(win_errors.EMITTED_INSPECT_REASONS)
    | {value for name, value in vars(host_executor_module).items()
       if name.endswith('_CODE') and isinstance(value, str)}
    | {'TARGET_KIND_INVALID', 'INSPECT_FAILED', 'FILE_NOT_FOUND',
       'FILE_PERMISSION_DENIED', 'INSPECT_POINT_INVALID'})

#: Ba mã đại diện cho mỗi nhóm quyết định — câu gửi model phải khác nhau giữa các nhóm.
REPRESENTATIVE = {
    'HUMAN_HAS_CONTROL': 'chờ quyền trả lại',
    'PERMISSION_DENIED': 'xin chủ nhà',
    'ELEMENT_STALE': 'chụp lại',
    'CONTROL_BUSY': 'thử lại MỘT lần',
    'TARGET_REQUIRED': 'chọn một cửa sổ',
    'CUA_UNAVAILABLE': 'gói cần cài',
    'COMMAND_TIMEOUT': 'chia nhỏ',
    'COMMAND_EXIT_NONZERO': 'exit_code',
    'HOST_TOOL_FAILED': 'đổi cách',
    'FILE_NOT_FOUND': 'không tìm thấy tệp',
    'FILE_PERMISSION_DENIED': 'xin chủ nhà',
    'INSPECT_POINT_INVALID': 'vùng chụp',
}

TOOL_PATH = Path(__file__).resolve().parents[2] / 'tools' / 'tool_errors.py'


def _load_tool_errors():
    spec = importlib.util.spec_from_file_location('tool_errors_tool', TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool_errors = _load_tool_errors()


# --- 1. Câu gửi cho model: mã host/CUA nói đúng việc cần làm -------------------------------

@pytest.mark.parametrize('code', HOST_CODES)
def test_a_host_code_never_gets_the_argument_shape_wording(code):
    hint = reflection_hint('computer_use', code)
    assert code in hint
    assert SCHEMA_SENTENCE not in hint, f'{code} vẫn nhận câu dành cho lỗi sai tham số'
    assert 'names the field and the rule' not in hint
    assert 'Expected arguments' not in hint


@pytest.mark.parametrize('code', HOST_CODES)
def test_a_host_hint_repeats_the_policy_advice_instead_of_copying_wording(code):
    """Một nguồn chữ duy nhất: sửa `_HOST_ADVICE` là câu gửi model đổi theo, không chép tay."""
    hint = reflection_hint('computer_use', code)
    klass, action, reason = recovery_policy.advice(code)
    assert reason in hint, code
    assert klass in hint and action in hint, code
    assert 'Do not resend the identical call' in hint


@pytest.mark.parametrize('code,needle', sorted(REPRESENTATIVE.items()))
def test_representative_codes_advise_the_right_thing(code, needle):
    hint = reflection_hint('computer_use', code)
    assert needle in hint, hint


def test_the_no_code_case_is_not_an_argument_error():
    """Đo sống 2026-10-07: `terminal_exec` trả `content`/`exit_code` mà không có mã nào."""
    hint = reflection_hint('terminal_exec', None)
    assert hint.startswith('AUTONOMOUS_DIAGNOSIS: `terminal_exec` failed with an error. ')
    assert 'names the field and the rule' not in hint
    assert SCHEMA_SENTENCE not in hint
    assert 'carries no error code' in hint
    assert 'exit_code' in hint and 'content' in hint
    assert 'never resend identical arguments' in hint


def test_argument_errors_keep_the_schema_contract():
    """Không nới luật cũ: lỗi hình dạng đối số vẫn nhận đúng câu schema + hình dạng đối số."""
    for name, code in (('plan_scope', 'PLAN_BRIEF_INVALID'), ('web_fetch', 'WEB_URL_INVALID'),
                       ('delegate_task', 'TURN_FAILED_VALUEERROR')):
        hint = reflection_hint(name, code)
        assert SCHEMA_SENTENCE in hint, (name, code)
        assert 'required=' in hint, (name, code)


def test_delegate_task_without_a_code_keeps_its_own_recovery():
    hint = reflection_hint('delegate_task')
    assert 'last_error' in hint and SCHEMA_SENTENCE not in hint


def test_an_unknown_tool_without_a_code_still_names_the_tool():
    assert reflection_hint('no_such_tool').startswith('AUTONOMOUS_DIAGNOSIS: `no_such_tool`')


# --- 2. Công cụ đo: đọc sổ + nhật ký, không ghi gì ------------------------------------------

def _seed_store(path: Path) -> None:
    """Sổ tạm: một lỗi CÓ mã, một lỗi KHÔNG mã, và một hàng thành công (không được đếm)."""
    store = SessionStore(path)
    try:
        store.emit('sess-a', 'tool_end', {'id': 'c1', 'name': 'terminal_exec', 'args': {},
                                          'result': {'is_error': True, 'errorCode': 'PERMISSION_DENIED',
                                                     'error': 'chưa được cấp quyền'}})
        store.emit('sess-b', 'tool_end', {'id': 'c2', 'name': 'terminal_exec', 'args': {},
                                          'result': {'is_error': True, 'error': 'Exited with code 127',
                                                     'content': 'command not found', 'exit_code': 127}})
        store.emit('sess-c', 'tool_end', {'id': 'c3', 'name': 'file_read', 'args': {},
                                          'result': {'is_error': False, 'content': 'ok'}})
    finally:
        store.close()


def _seed_log(path: Path) -> None:
    """Đúng hình dạng `runtime.py` ghi: `errorCode`/`tool` nằm trong `data` (không phải khoá đầu)."""
    path.write_text('\n'.join([
        json.dumps({'ts': '2026-10-08T10:00:00.000Z', 'level': 'error', 'source': 'harness',
                    'event': 'tool.error', 'sessionId': 'sess-a',
                    'message': 'người thật đang giữ quyền',
                    'data': {'tool': 'computer_use', 'errorCode': 'HUMAN_HAS_CONTROL'}}),
        json.dumps({'ts': '2026-10-08T10:00:01.000Z', 'level': 'info', 'source': 'harness',
                    'event': 'tool.end', 'tool': 'terminal_exec'}),
    ]) + '\n', encoding='utf-8')


def test_the_tool_counts_each_code_and_marks_the_undeclared_ones(tmp_path, capsys):
    db = tmp_path / 'sessions.sqlite'
    _seed_store(db)
    log = tmp_path / 'harness.jsonl'
    _seed_log(log)
    report_path = tmp_path / 'report.json'

    assert tool_errors.main(['--db', str(db), '--log-dir', str(tmp_path), '--json', str(report_path)]) == 0
    out = capsys.readouterr().out
    assert 'PERMISSION_DENIED' in out and 'HUMAN_HAS_CONTROL' in out
    assert tool_errors.NO_CODE in out
    assert '1 mã đã gặp' not in out  # ba mã: PERMISSION_DENIED, HUMAN_HAS_CONTROL, (không có mã)
    assert '2 mã đã gặp; 0 mã chưa được khai' in out
    assert 'có' in out  # cột "lời khuyên riêng"

    report = json.loads(report_path.read_text(encoding='utf-8'))
    by_code = {row['code']: row for row in report['codes']}
    assert by_code['PERMISSION_DENIED']['count'] == 1
    assert by_code['PERMISSION_DENIED']['advice'] is True
    assert by_code['PERMISSION_DENIED']['declared'] is True
    assert by_code['HUMAN_HAS_CONTROL']['count'] == 1
    assert by_code['HUMAN_HAS_CONTROL']['tools'] == ['computer_use']  # đọc từ nhật ký, không phải sổ
    assert by_code[tool_errors.NO_CODE]['count'] == 1
    assert by_code[tool_errors.NO_CODE]['declared'] is False
    assert report['noCode'] == 1 and report['seen'] == 2 and report['undeclared'] == []
    assert report['storeRows'] == 3  # hàng thành công vẫn được đếm trong sổ, chỉ không vào bảng lỗi


def _header_store_path(out: str) -> Path:
    """Đường dẫn sổ in ở dòng `nguồn sổ:` — chính là tệp công cụ đã mở."""
    line = next(line for line in out.splitlines() if line.startswith('nguồn sổ:'))
    return Path(line.split('nguồn sổ:')[1].split(' (')[0].strip())


def test_the_header_names_the_store_that_was_actually_opened(tmp_path, capsys):
    """Dòng `nguồn sổ:` phải là tệp ĐÃ MỞ, không phải một tên suy ra từ thư mục.

    Đo được 2026-10-08 (review của chủ nhà): `--db /var/tmp/x.sqlite` in ra `/var/tmp/sessions.sqlite`
    — một tệp không tồn tại. Với công cụ đo, dòng đầu là thứ duy nhất truy được nguồn số liệu, nên nó
    không được phép chỉ sang tệp khác. Ca này ghim **cả hai** đường: `--db` và mặc định `--data-dir`.
    """
    # (a) `--db` trỏ tới tên tệp KHÁC `sessions.sqlite` — đúng ca đã sai.
    other = tmp_path / 'rev-live.sqlite'
    _seed_store(other)
    report_path = tmp_path / 'report.json'
    assert tool_errors.main(['--db', str(other), '--log-dir', str(tmp_path / 'khong-co'),
                             '--json', str(report_path)]) == 0
    out = capsys.readouterr().out
    assert _header_store_path(out) == other
    assert '3 hàng tool_end' in out          # đọc đúng sổ đó
    assert 'sessions.sqlite' not in out      # và không nhắc tới tệp nào khác
    report = json.loads(report_path.read_text(encoding='utf-8'))
    assert report['db'] == str(other)        # JSON cũng phải nói cùng một tệp
    assert 'dataDir' not in report, 'khoá `dataDir` cũ ghi thư mục, không phải tệp đã đọc'

    # (b) đường mặc định: không `--db` ⇒ tệp mở là `<data-dir>/sessions.sqlite`.
    data_dir = tmp_path / 'harness'
    data_dir.mkdir()
    _seed_store(data_dir / 'sessions.sqlite')
    assert tool_errors.main(['--data-dir', str(data_dir), '--log-dir', str(tmp_path / 'khong-co')]) == 0
    out = capsys.readouterr().out
    assert _header_store_path(out) == data_dir / 'sessions.sqlite'
    assert '3 hàng tool_end' in out


def test_the_tool_never_writes_to_the_store(tmp_path, capsys):
    db = tmp_path / 'sessions.sqlite'
    _seed_store(db)
    before = hashlib.sha256(db.read_bytes()).hexdigest()

    tool_errors.main(['--db', str(db), '--log-dir', str(tmp_path / 'khong-co')])

    capsys.readouterr()
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    sidecars = [p.name for p in tmp_path.iterdir() if p.name != db.name and p.name != 'harness.jsonl']
    assert sidecars == [], f'công cụ đã tạo tệp phụ: {sidecars}'
    with sqlite3.connect(db) as check:
        assert check.execute('SELECT COUNT(*) FROM events').fetchone()[0] == 3


def test_the_tool_reads_a_live_wal_store_without_leaving_a_trace(tmp_path, capsys):
    """Sổ đang mở ở chế độ WAL: công cụ phải đọc qua **bản sao**, không chạm `-shm` của chủ nhà.

    Đo được 2026-10-08: mở `?mode=ro` thẳng vào sổ WAL làm `sessions.sqlite-shm` đổi mtime mỗi lần
    chạy — nội dung sổ không đổi nhưng vẫn là dấu vết trong thư mục của chủ nhà. Ca này ghim bản sao.
    """
    db = tmp_path / 'sessions.sqlite'
    _seed_store(db)
    live = sqlite3.connect(db, isolation_level=None)  # giữ mở ⇒ `-wal`/`-shm` tồn tại thật
    try:
        assert live.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
        assert Path(str(db) + '-wal').exists()
        before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.iterdir()}

        assert tool_errors.main(['--db', str(db), '--log-dir', str(tmp_path / 'khong-co')]) == 0

        out = capsys.readouterr().out
        assert '3 hàng tool_end' in out  # vẫn đọc đúng hàng của sổ đang mở
        after = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in tmp_path.iterdir()}
        assert after == before, 'công cụ đã chạm vào thư mục của sổ (bản sao tạm bị rò)'
    finally:
        live.close()


def test_the_tool_does_not_create_the_shm_of_a_wal_store(tmp_path, capsys):
    """Sổ từng ở chế độ WAL (còn `-wal`, chưa có `-shm`): công cụ **không** được tạo tệp ở thư mục đó.

    Đây đúng dạng đo được trên máy chủ nhà 2026-10-08 (`sessions.sqlite-wal` 0 byte): mở chỉ-đọc thẳng
    vào sổ WAL làm SQLite tạo/cập nhật `sessions.sqlite-shm` — một dấu vết mới trong thư mục dữ liệu
    của chủ nhà. Ca này ghim đường đọc qua bản sao (`_snapshot`).
    """
    db = tmp_path / 'sessions.sqlite'
    _seed_store(db)
    Path(str(db) + '-wal').write_bytes(b'')  # dấu vết còn lại của một phiên WAL trước
    before = sorted(p.name for p in tmp_path.iterdir())

    assert tool_errors.main(['--db', str(db), '--log-dir', str(tmp_path / 'khong-co')]) == 0

    out = capsys.readouterr().out
    assert '3 hàng tool_end' in out
    assert sorted(p.name for p in tmp_path.iterdir()) == before, 'công cụ đã tạo tệp trong thư mục sổ'


def test_an_undeclared_code_is_reported_as_such(tmp_path, capsys):
    db = tmp_path / 'sessions.sqlite'
    store = SessionStore(db)
    try:
        store.emit('s1', 'tool_end', {'id': 'c1', 'name': 'terminal_exec', 'args': {},
                                      'result': {'is_error': True, 'errorCode': 'NEW_UNKNOWN_CODE',
                                                 'error': 'lạ'}})
    finally:
        store.close()

    tool_errors.main(['--db', str(db), '--log-dir', str(tmp_path / 'khong-co')])
    out = capsys.readouterr().out
    assert 'NEW_UNKNOWN_CODE' in out
    assert 'CHƯA' in out
    assert "1 mã đã gặp; 1 mã chưa được khai ⇒ agent nhận câu 'không rõ loại lỗi'" in out


def test_a_missing_store_is_not_a_crash(tmp_path, capsys):
    assert tool_errors.main(['--db', str(tmp_path / 'chua-co.sqlite'),
                             '--log-dir', str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert 'chưa có sổ' in out
    assert 'chưa đo được trên dữ liệu sống' in out


def test_an_empty_store_prints_the_cap_and_says_it_measured_nothing(tmp_path, capsys):
    db = tmp_path / 'sessions.sqlite'
    SessionStore(db).close()  # sổ có bảng, không có hàng nào

    assert tool_errors.main(['--db', str(db), '--log-dir', str(tmp_path), '--limit', '7']) == 0
    out = capsys.readouterr().out
    assert 'trần đọc: 7 hàng sự kiện' in out
    assert '0 hàng tool_end' in out
    assert 'chưa đo được trên dữ liệu sống' in out
