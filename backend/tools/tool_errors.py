"""Đo **mã lỗi thật** của đường host/CUA — công cụ cho câu "kiểm thử toàn diện".

Chạy được trên máy không có X server, **không** ghi gì vào sổ, **không** chạy lại công cụ nào:

    cd backend && .venv/bin/python tools/tool_errors.py
    cd backend && .venv/bin/python tools/tool_errors.py --data-dir ~/BoxFox/harness --json /var/tmp/tool-errors.json
    cd backend && .venv/bin/python tools/tool_errors.py --data-dir .tmp/verify-20261007/host-harness2

Hai nguồn **độc lập**, nên có hai cờ riêng:

* `--data-dir` — thư mục dữ liệu harness, đúng luật `api/server.py` (`BOXFOX_AGENT_DATA_DIR`, mặc
  định `~/BoxFox/harness` trên Linux, `%LOCALAPPDATA%\\BoxFox\\harness` trên Windows); đọc bảng
  `events` của `sessions.sqlite`, các hàng `kind='tool_end'` có `result.is_error`
  — mã lỗi nằm ở `result.errorCode`. Đây là **bản ghi đầy đủ** của từng lời gọi công cụ. Sổ được đọc
  trên **bản sao tạm**: mở chỉ-đọc một sổ WAL vẫn để lại tệp `-shm` trong thư mục chủ nhà, nên công cụ
  không bao giờ mở tệp gốc (xem `_snapshot`).
* `--log-dir` — nhật ký dev (`BOXFOX_SYSTEM_LOG_DIR`, mặc định `~/BoxFox/logs`); đọc các dòng
  `tool.error` của `harness.jsonl`. Nhật ký **thiếu** hàng thành công, nên hai nguồn không thay nhau
  được: sổ cho tỉ lệ, nhật ký cho ca đã bị nén/xoay vòng.

Câu hỏi công cụ trả lời, theo đúng thứ tự cần:

1. Mã nào **đã gặp thật** (không phải mã trong tài liệu), bao nhiêu lần, ở công cụ/phiên nào.
2. Với mỗi mã, agent **hôm nay** được cho lớp gì, hành động gì, lý do gì — và mã ấy đã có **lời khuyên
   riêng** chưa (`recovery_policy.advice`). Mã chưa khai ⇒ agent nhận đúng một câu
   "không rõ loại lỗi: dừng ở checkpoint và hỏi chủ nhà".
3. Hàng **không mang mã** (`(không có mã)`) đếm riêng: đây là ca "đỏ mà không có gì để sửa", nguyên
   nhân của những lần agent nghĩ lại rồi thử lại vô ích.

Trần an toàn: đọc tối đa `--limit` hàng sự kiện (mặc định 20 000) và **in ra** con số trần đó, để một
sổ lớn không bao giờ làm công cụ treo. Kết luận một dòng ở cuối: bao nhiêu mã đã gặp, bao nhiêu mã chưa
được khai.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import pathname2url

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from agentbox.agent_core import recovery_policy  # noqa: E402

#: Trần đọc mặc định cho mỗi nguồn (hàng sự kiện / dòng nhật ký).
DEFAULT_LIMIT = 20_000

#: Nhãn của hàng `is_error` mà kết quả không mang `errorCode` — đếm riêng, không phải một "mã".
NO_CODE = '(không có mã)'

#: Câu lý do mà mọi mã chưa khai đều nhận (khớp `recovery_policy.decision`).
UNKNOWN_REASON = 'không rõ loại lỗi'


def harness_data_dir() -> Path:
    """Thư mục dữ liệu harness, theo đúng luật của `api/server.py`."""
    override = os.environ.get('BOXFOX_AGENT_DATA_DIR')
    if override:
        return Path(override).expanduser()
    if os.name == 'nt':
        return Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'BoxFox' / 'harness'
    return Path.home() / 'BoxFox' / 'harness'


def default_log_dir() -> Path:
    """Thư mục nhật ký dev, theo đúng luật của `observability/system_log.py`."""
    override = os.environ.get('BOXFOX_SYSTEM_LOG_DIR')
    return Path(override).expanduser() if override else Path.home() / 'BoxFox' / 'logs'


def _when(created: float) -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(created))


def _observation(code: str, tool: str, session: str, when: str, source: str) -> dict:
    return {'code': code or NO_CODE, 'tool': tool or '?', 'session': session or '?',
            'when': when or '?', 'source': source}


def _snapshot(db_path: Path) -> Path:
    """Bản sao tạm của sổ (kèm `-wal`/`-shm` nếu có) để đọc mà **không để lại dấu vết** ở thư mục gốc.

    Vì sao không mở thẳng bằng `?mode=ro`: SQLite vẫn tạo/cập nhật `-shm` cho một sổ WAL ngay cả khi
    kết nối chỉ-đọc, tức là ghi vào thư mục của chủ nhà (đo được 2026-10-08: `-shm` đổi mtime mỗi lần
    chạy). Bản sao đẩy dấu vết đó vào thư mục tạm của chính công cụ. Bản sao có thể lệch nếu tiến trình
    ghi đang chạy — SQLite sẽ **báo lỗi rõ ràng** chứ không im lặng trả dữ liệu sai.
    """
    tmp = Path(tempfile.mkdtemp(prefix='tool-errors-'))
    for suffix in ('', '-wal', '-shm'):
        source = Path(str(db_path) + suffix)
        if source.exists():
            shutil.copy2(source, tmp / (db_path.name + suffix))
    return tmp / db_path.name


def read_store(db_path: Path, limit: int):
    """Hàng `tool_end` **đang lỗi** trong sổ phiên. Trả `(quan sát, tổng hàng lỗi, ghi chú)`.

    Đọc trên bản sao tạm: công cụ đo không bao giờ mở tệp gốc — không tạo, không sửa, không migrate sổ.
    """
    observations: list[dict] = []
    if not db_path.exists():
        return observations, None, 'chưa có sổ'
    snapshot = _snapshot(db_path)
    try:
        uri = 'file:' + pathname2url(str(snapshot)) + '?mode=ro'
        try:
            db = sqlite3.connect(uri, uri=True)
        except sqlite3.Error as exc:
            return observations, None, f'không mở được sổ: {exc}'
        try:
            db.row_factory = sqlite3.Row
            total = db.execute("SELECT COUNT(*) FROM events WHERE kind = 'tool_end'").fetchone()[0]
            rows = db.execute('SELECT session_id, payload, created FROM events '
                              "WHERE kind = 'tool_end' ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        except sqlite3.Error as exc:
            return observations, None, f'không đọc được sổ: {exc}'
        finally:
            db.close()
    finally:
        shutil.rmtree(snapshot.parent, ignore_errors=True)
    skipped = 0
    for row in reversed(rows):  # DESC để lấy hàng mới nhất khi chạm trần, đảo lại thành thứ tự thời gian
        try:
            payload = json.loads(row['payload'] or '{}')
        except (TypeError, ValueError):
            skipped += 1
            continue
        result = payload.get('result') if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            skipped += 1
            continue
        if result.get('is_error') is not True:
            continue  # hàng thành công không mang mã lỗi — không đếm vào bảng lỗi
        code = str(result.get('errorCode') or '').strip()
        observations.append(_observation(code, str(payload.get('name') or ''),
                                         str(row['session_id'] or ''), _when(float(row['created'] or 0)),
                                         'sổ'))
    note = f'{skipped} hàng không đọc được' if skipped else ''
    return observations, total, note


def read_log(log_path: Path, limit: int):
    """Dòng `tool.error` của nhật ký dev. Trả `(quan sát, số dòng đã đọc, ghi chú)`."""
    observations: list[dict] = []
    if not log_path.exists():
        return observations, 0, 'chưa có nhật ký'
    lines = skipped = 0
    with log_path.open('r', encoding='utf-8', errors='replace') as handle:
        for line in handle:
            if lines >= limit:
                break
            lines += 1
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(entry, dict) or entry.get('event') != 'tool.error':
                continue
            data = entry.get('data') if isinstance(entry.get('data'), dict) else {}
            code = str(entry.get('code') or data.get('errorCode') or '').strip()
            observations.append(_observation(code, str(data.get('tool') or ''),
                                             str(entry.get('sessionId') or ''),
                                             str(entry.get('ts') or ''), 'nhật ký'))
    note = f'{skipped} dòng không đọc được' if skipped else ''
    return observations, lines, note


def aggregate(observations: list[dict]) -> list[dict]:
    """Gộp theo mã: số lần · công cụ · phiên · lần đầu/cuối · lớp/hành động/lý do **hôm nay**."""
    table: dict[str, dict] = {}
    for item in observations:
        row = table.setdefault(item['code'], {'code': item['code'], 'count': 0, 'tools': [],
                                              'sessions': [], 'first': item['when'], 'last': item['when']})
        row['count'] += 1
        if item['tool'] not in row['tools']:
            row['tools'].append(item['tool'])
        if item['session'] not in row['sessions']:
            row['sessions'].append(item['session'])
        row['first'] = min(row['first'], item['when'])
        row['last'] = max(row['last'], item['when'])
    for row in table.values():
        decision = recovery_policy.decision('' if row['code'] == NO_CODE else row['code'])
        row['class'] = decision['class']
        row['action'] = decision['action']
        row['reason'] = decision['reason']
        # "Có lời khuyên riêng" = mã nằm trong bảng host/CUA, tức câu gửi model nói đúng việc cần làm
        # thay vì khuôn lỗi-schema.
        row['advice'] = recovery_policy.advice(row['code']) is not None
        row['declared'] = decision['class'] != 'unknown'
    return sorted(table.values(), key=lambda row: (-row['count'], row['code']))


def _join(values: list[str]) -> str:
    if len(values) <= 2:
        return ','.join(values)
    return ','.join(values[:2]) + f'+{len(values) - 2}'


def print_table(rows: list[dict], *, data_dir: Path, store_note: str, store_total, log_path: Path,
                log_note: str, log_lines: int, limit: int) -> None:
    print('=== mã lỗi host/CUA đo được trên máy này ===')
    print(f'trần đọc: {limit} hàng sự kiện (mỗi nguồn)')
    total = '' if store_total is None else f'{store_total} hàng tool_end'
    print(f'nguồn sổ:   {data_dir / "sessions.sqlite"} {("(" + total + ")") if total else ""}'
          f'{(" — " + store_note) if store_note else ""}')
    print(f'nguồn nhật ký: {log_path} ({log_lines} dòng đã đọc)'
          f'{(" — " + log_note) if log_note else ""}')
    if not rows:
        print()
        print('chưa đo được trên dữ liệu sống: không có hàng `tool_end` lỗi nào trong sổ và không có dòng '
              '`tool.error` nào trong nhật ký.')
        return
    header = ('mã', 'lần', 'công cụ', 'phiên', 'lần đầu/cuối', 'lớp hôm nay', 'hành động',
              'lý do hôm nay', 'lời khuyên riêng')
    body = []
    for row in rows:
        body.append((row['code'], str(row['count']), _join(row['tools']),
                     f"{len(row['sessions'])} phiên",
                     f"{row['first'][5:16]} → {row['last'][5:16]}", row['class'], row['action'],
                     row['reason'], 'có' if row['advice'] else 'CHƯA'))
    widths = [max(len(header[i]), *(len(line[i]) for line in body)) for i in range(len(header))]
    widths[7] = min(max(widths[7], 24), 78)
    print()
    print('  '.join(header[i].ljust(widths[i]) for i in range(len(header))))
    print('  '.join('-' * widths[i] for i in range(len(header))))
    for line in body:
        print('  '.join(line[i].ljust(widths[i]) if i != 7 else line[i][:widths[7]].ljust(widths[7])
                        for i in range(len(header))))
    undeclared = [row for row in rows if not row['declared'] and row['code'] != NO_CODE]
    if undeclared:
        print()
        print('mã CHƯA được khai trong chính sách (agent nhận câu "không rõ loại lỗi"):')
        for row in undeclared:
            print(f"  {row['code']}  ({row['count']} lần, {_join(row['tools'])})")
    no_code = next((row for row in rows if row['code'] == NO_CODE), None)
    if no_code is not None:
        print()
        print(f"hàng `{NO_CODE}`: {no_code['count']} lần — kết quả `is_error` không mang mã nào. "
              'Cột lớp/hành động ở trên là cái agent NHẬN ĐƯỢC; `host_executor` nay gắn '
              '`COMMAND_EXIT_NONZERO`/`HOST_TOOL_FAILED` cho ca này nên hàng không mã phải biến mất.')
    seen = [row for row in rows if row['code'] != NO_CODE]
    missing = [row for row in seen if not row['declared']]
    print()
    print(f"{len(seen)} mã đã gặp; {len(missing)} mã chưa được khai "
          f"⇒ agent nhận câu '{UNKNOWN_REASON}'")
    if no_code is not None:
        print(f"(cộng {no_code['count']} hàng không mang mã — đếm riêng, xem ghi chú ở trên)")


def build_report(rows: list[dict], *, data_dir: Path, log_dir: Path, limit: int) -> dict:
    seen = [row for row in rows if row['code'] != NO_CODE]
    return {
        'dataDir': str(data_dir),
        'logDir': str(log_dir),
        'limit': limit,
        'codes': [{key: row[key] for key in ('code', 'count', 'tools', 'sessions', 'first', 'last',
                                             'class', 'action', 'reason', 'advice', 'declared')}
                  for row in rows],
        'seen': len(seen),
        'undeclared': [row['code'] for row in seen if not row['declared']],
        'noCode': sum(row['count'] for row in rows if row['code'] == NO_CODE),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Đo mã lỗi thật của đường host/CUA (chỉ đọc).')
    parser.add_argument('--data-dir', default=None,
                        help='thư mục dữ liệu harness (mặc định: BOXFOX_AGENT_DATA_DIR hoặc ~/BoxFox/harness)')
    parser.add_argument('--db', default=None, help='đường dẫn thẳng tới sessions.sqlite (thay cho --data-dir)')
    parser.add_argument('--log-dir', default=None,
                        help='thư mục nhật ký dev (mặc định: BOXFOX_SYSTEM_LOG_DIR hoặc ~/BoxFox/logs)')
    parser.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help=f'trần đọc mỗi nguồn (mặc định {DEFAULT_LIMIT})')
    parser.add_argument('--json', default=None, help='ghi bảng này ra tệp JSON để lần sau so lại')
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else harness_data_dir()
    db_path = Path(args.db).expanduser() if args.db else data_dir / 'sessions.sqlite'
    log_dir = Path(args.log_dir).expanduser() if args.log_dir else default_log_dir()
    log_path = log_dir / 'harness.jsonl'
    limit = max(1, int(args.limit))

    store_observations, store_total, store_note = read_store(db_path, limit)
    log_observations, log_lines, log_note = read_log(log_path, limit)
    rows = aggregate(store_observations + log_observations)
    print_table(rows, data_dir=data_dir if not args.db else db_path.parent, store_note=store_note,
                store_total=store_total, log_path=log_path, log_note=log_note, log_lines=log_lines,
                limit=limit)
    if args.json:
        report = build_report(rows, data_dir=data_dir, log_dir=log_dir, limit=limit)
        report['db'] = str(db_path)
        report['storeRows'] = store_total
        report['logLines'] = log_lines
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(f'\nđã ghi {args.json}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
