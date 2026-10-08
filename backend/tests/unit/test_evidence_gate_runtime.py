"""Vòng 22 đợt 3 — cổng bằng chứng sống ở ĐƯỜNG THẬT của một lượt (P3.1–P3.6).

`test_evidence_gate.py` kiểm bộ phán THUẦN (không box, không model). Bài này kiểm chỗ nối: một lượt
chạy qua `HarnessRuntime._run` với model giả và executor giả, rồi đọc lại **event** và **nhật ký** —
đúng hai mặt mà giao diện và người đọc dùng.

Sáu nhóm, mỗi nhóm khoá một tính chất sống còn:

- **P3.1** cổng chạy sau câu trả lời cuối và số của nó vào `turn_end` + `assistant.evidence`;
- **P3.2** phép dò box bằng ĐÚNG một lệnh cố định, tự loại trừ hai gốc mà harness tự ghi;
- **P3.3** vòng vá có trần: ba ca (đủ ngân sách / hết ngân sách / vòng vá hết giờ) đều phải CÓ câu
  trả lời — đây là rủi ro lớn nhất của cả đợt;
- **P3.4** một hàng `E:` mỗi lượt, có `turn`/`step`; cổng tự hỏng thì một hàng `X:` và văn đi nguyên;
- **P3.5** công tắc `BOXFOX_EVIDENCE_GATE`, kể cả giá trị lạ;
- **P3.6/D-4** câu trả lời quá dài: cảnh báo thì giữ văn, quá trần thì cắt + toàn văn nằm ở tệp đọc được.
"""
from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

from agentbox.agent_core import evidence_gate as gate
from agentbox.agent_core.limits import (ANSWER_LENGTH_WARN_CODE, ANSWER_MAX_CHARS, ANSWER_TOO_LONG_CODE,
                                        ANSWER_WARN_CHARS, EVIDENCE_GATE_ENV, EVIDENCE_GATE_FAILED_CODE,
                                        EVIDENCE_INSUFFICIENT_CODE, EVIDENCE_MODE_UNKNOWN_CODE,
                                        EVIDENCE_PRUNE_EVERY, EVIDENCE_REPAIR_MAX_TOKENS)
from agentbox.agent_core.runtime import HarnessRuntime, answer_truncation_tail
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.worker import SESSION_OP_NAMES

EVIDENCE_DIR = '.generated_artifacts/captures/evidence'
ARTIFACT = f'{EVIDENCE_DIR}/abc/abc_001_app.py.diff'


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append({'messages': copy.deepcopy(messages), 'tools': copy.deepcopy(tools),
                              'max_tokens': max_tokens})
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


class FixtureExecutor:
    """Executor giả GHI THẬT vào `<root>/workspace` — nên "tệp có tồn tại" kiểm được bằng đọc tệp.

    `with_evidence=False` dựng lại hình dạng worker TRƯỚC P1.4 (`file_write` chỉ trả `content`):
    lượt ghi tệp mà không có mảnh bằng chứng nào — đúng ca R1 phải bắt.
    """

    def __init__(self, root, *, with_evidence=True, probe_stdout='', probe_raises=False,
                 prune_ok=True):
        self.root = Path(root)
        self.with_evidence = with_evidence
        self.probe_stdout = probe_stdout
        self.probe_raises = probe_raises
        self.prune_ok = prune_ok
        self.calls = []

    # --- tiện ích cho test -------------------------------------------------
    def named(self, name):
        return [item for item in self.calls if item['name'] == name]

    def probe_commands(self):
        return [item['args'].get('command') for item in self.named('terminal_exec')]

    def written(self, path):
        return self.root / 'workspace' / str(path)

    # --- hợp đồng executor -------------------------------------------------
    async def execute(self, name, args, sid, **_identity):
        self.calls.append({'name': name, 'args': copy.deepcopy(args), 'session': sid})
        if name == 'file_write':
            relative = str(args.get('path') or '')
            target = self.written(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(args.get('content') or '')
            target.write_text(content, encoding='utf-8')
            # Hình dạng THẬT của worker sau P1.4: `numbers` KHÔNG mang `path` — đường dẫn
            # workspace chỉ còn trong `args` của lời gọi ghi (và trong tệp bằng chứng).
            result = {'content': f'Written {relative}'}
            if self.with_evidence:
                result['numbers'] = {'bytes': len(content)}
            if self.with_evidence and EVIDENCE_DIR not in relative:
                result.update({'diff': f'--- a/{relative}\n+++ b/{relative}\n@@ -1 +1 @@\n+x\n',
                               'artifact': ARTIFACT})
            return result
        if name == 'terminal_exec':
            if self.probe_raises:
                raise RuntimeError('box down')
            # Khoá thật của worker: `content` (văn đầu ra) + `exit_code`.
            return {'content': self.probe_stdout, 'exit_code': 0}
        if name == 'computer_screen_capture':
            # Vòng 23 (P2.2): payload thật mang `target`/`caption`, ảnh nằm ở `captures/<kind>/<sid8>/`.
            # KHÔNG mang `image`: `_run` ghi `turn_calls` từ bản `safe` đã bỏ khoá ảnh, nên ca này
            # chứng minh cổng nhận ảnh qua TÊN CÔNG CỤ chứ không qua khoá `image`.
            capture_target = args.get('target') if isinstance(args.get('target'), dict) else {'kind': 'screen'}
            kind = str(capture_target.get('kind') or 'screen')
            step_token = f"{(_identity.get('step') or 0):03d}"
            shot = {'content': 'Sandbox screenshot 1280x800', 'dimensions': (1280, 800),
                    'artifact': f'.generated_artifacts/captures/{kind}/abc/abc_{step_token}_x.png',
                    'target': dict(capture_target)}
            if args.get('caption'):
                shot['caption'] = args['caption']
            return shot
        if name == 'captures_prune':
            if not self.prune_ok:
                return {'ok': False, 'error': 'SESSION_OPS_UNAVAILABLE'}
            return {'ok': True, 'removedFiles': 0, 'removedBytes': 0, 'pinned': []}
        if name in SESSION_OP_NAMES:
            # Op nhật ký của box (A1/A7) trả `{ok, …}` như worker thật: thiếu `ok` thì
            # `session_journal._safe` coi là CHƯA ghi được và ghim `JOURNAL_DEGRADED`.
            return {'ok': True}
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def events_of(store, sid, kind):
    return [e['data'] for e in store.events(sid) if e['type'] == kind]


def notices(store, sid, code=None):
    rows = events_of(store, sid, 'notice')
    return [row for row in rows if code is None or row.get('code') == code]


def journal_rows(store, sid, kind=None):
    rows = [row['payload']['record'] for row in store.journal_tail(sid, limit=50)]
    return [row for row in rows if kind is None or row.get('kind') == kind]


def run_turns(tmp_path, client, prompts, *, executor=None, values=None, name='gate.db'):
    store = SessionStore(tmp_path / name)
    runtime = HarnessRuntime(store, executor or FixtureExecutor(tmp_path), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash',
                              **(values or {})})
    sid = session['id']

    async def run():
        for prompt in prompts:
            await runtime.submit(sid, prompt)
            await runtime.tasks[sid]

    asyncio.run(run())
    return store, runtime, session


# ---------------------------------------------------------------- P3.1 chèn cổng

def test_luot_ghi_tep_khong_co_manh_bang_chung_thi_cong_phat_chua_kiem_chung(tmp_path):
    """P3.1 — lượt có ĐỔI mà không có mảnh bằng chứng nào ⇒ `insufficient`, và số của cổng vào cả
    event `assistant` lẫn `turn_end` lẫn nhật ký."""
    executor = FixtureExecutor(tmp_path, with_evidence=False)
    client = FixtureModel([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                           answer('Đã sửa xong `src/app.py` và chạy thử.')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',), executor=executor)
    sid = session['id']

    payload = events_of(store, sid, 'assistant')[-1]
    assert payload['evidence']['verdict'] == 'insufficient'
    assert payload['evidence']['mode'] == 'warn', 'mặc định là `warn`: ghim nhãn, không sửa văn'
    assert payload['evidence']['missing'][0]['reason'] == 'no_evidence_for_tools'
    assert payload['text'] == 'Đã sửa xong `src/app.py` và chạy thử.', 'cổng không viết lại văn'
    assert payload['evidence']['changedFiles'] == ['src/app.py']
    assert payload['evidence']['journalSeq'] == 1, 'số của hàng `E:` ghim vào event'

    rows = notices(store, sid, EVIDENCE_INSUFFICIENT_CODE)
    assert len(rows) == 1 and rows[0]['partial'] is False
    last_end = events_of(store, sid, 'turn_end')[-1]
    assert last_end['evidenceVerdict'] == 'insufficient' and last_end['gateMode'] == 'warn'
    assert last_end['status'] == 'completed', 'cổng không đổi kết cục của lượt'

    row = journal_rows(store, sid, 'evidence')[0]
    assert row['turn'] == 1, 'hàng `E:` mang `turn` để UI gom đúng lượt'
    assert row['step'] == last_end['step'], 'số bước của bằng chứng là bước PHÁT câu trả lời'
    assert row['data']['verdict'] == 'insufficient' and row['data']['changedFiles'] == ['src/app.py']
    store.close()


def test_luot_ghi_co_diff_thi_duoc_danh_da_kiem_chung(tmp_path):
    """Cùng lượt, khác mảnh bằng chứng: worker P1.4 trả `artifact` + `diff` ⇒ `sufficient`."""
    executor = FixtureExecutor(tmp_path)
    client = FixtureModel([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                           answer('Đã sửa `src/app.py`.')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',), executor=executor)
    sid = session['id']

    info = events_of(store, sid, 'assistant')[-1]['evidence']
    assert info['verdict'] == 'sufficient' and info['checked'] == 1
    pointer = info['artifacts'][0]
    assert pointer['kind'] == 'diff' and pointer['path'] == ARTIFACT
    assert pointer['changed'] == 'src/app.py', 'con trỏ mang CẢ tệp bằng chứng lẫn tệp đã đổi'
    assert notices(store, sid, EVIDENCE_INSUFFICIENT_CODE) == []
    row = journal_rows(store, sid, 'evidence')[0]
    assert row['evidence'][0]['path'] == ARTIFACT and row['status'] != 'failed'
    store.close()


def test_cong_tu_hong_thi_cau_tra_loi_di_nguyen_van(tmp_path, monkeypatch):
    """§3.7 — cổng hỏng KHÔNG được giết lượt: văn nguyên văn, một hàng `X:`, nhãn `chưa đo được`."""
    def boom(_calls):
        raise RuntimeError('gate exploded')

    monkeypatch.setattr(gate, 'classify_turn', boom)
    client = FixtureModel([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                           answer('Đã sửa `src/app.py`.')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',))
    sid = session['id']

    assert store.get(sid)['status'] == 'completed', 'hỏng cổng mà lượt thành `failed` là hồi quy'
    assert events_of(store, sid, 'assistant')[-1]['text'] == 'Đã sửa `src/app.py`.'
    failed = [row for row in notices(store, sid) if row.get('code') == EVIDENCE_GATE_FAILED_CODE]
    assert len(failed) == 1 and 'gate exploded' in failed[0]['error']
    row = journal_rows(store, sid, 'blocker')[0]
    assert row['status'] == 'failed' and row['data']['code'] == EVIDENCE_GATE_FAILED_CODE
    assert events_of(store, sid, 'turn_end')[-1]['evidenceVerdict'] == 'not_measurable'
    store.close()


def test_cong_hong_sau_khi_phan_thi_moi_mat_doc_noi_chua_do_duoc(tmp_path, monkeypatch):
    """§3.7 — ghim hàng `E:` hỏng SAU khi đã phán: mọi mặt đọc phải nói "chưa đo được".

    Trước đây `info` giữ phán thật trong khi hàng `X:` và notice nói "cổng tự hỏng" — cùng một
    lượt, hai kết luận (event `assistant` nói `sufficient`, sổ nói chưa đo được).
    """
    def boom(self, *_args, **_kwargs):
        raise RuntimeError('journal pin exploded')

    monkeypatch.setattr(HarnessRuntime, 'pin_evidence', boom)
    client = FixtureModel([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                           answer('Đã sửa `src/app.py`.')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',))
    sid = session['id']

    info = events_of(store, sid, 'assistant')[-1]['evidence']
    assert info['verdict'] == 'not_measurable', 'mặt đọc không được giữ phán thật khi cổng tự hỏng'
    assert [item['reason'] for item in info['missing']] == ['gate_error']
    assert events_of(store, sid, 'turn_end')[-1]['evidenceVerdict'] == 'not_measurable'
    failed = [row for row in notices(store, sid) if row.get('code') == EVIDENCE_GATE_FAILED_CODE]
    assert len(failed) == 1, 'cổng tự hỏng vẫn phải để lại một notice'
    store.close()


def test_cong_tat_off_thi_khong_do_gi_va_khong_co_truong_evidence(tmp_path, monkeypatch):
    """P3.5 — `off` là "không đo", không phải "đo ra rỗng": event `assistant` không có `evidence`."""
    monkeypatch.setenv(EVIDENCE_GATE_ENV, 'off')
    client = FixtureModel([answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
                           answer('Đã sửa `src/app.py`.')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',))
    sid = session['id']

    payload = events_of(store, sid, 'assistant')[-1]
    assert 'evidence' not in payload, 'giao diện giữ mặc định "chưa kiểm chứng" khi cổng tắt'
    assert notices(store, sid) == [], 'tắt cổng thì không có notice nào'
    assert events_of(store, sid, 'turn_end')[-1]['gateMode'] == 'off'
    store.close()


def test_gia_tri_cong_tac_la_thi_roi_ve_mac_dinh_va_noi_ra(tmp_path, monkeypatch):
    """P3.5 — giá trị lạ không được biến thành một mức không tồn tại, và phải NÓI RA."""
    monkeypatch.setenv(EVIDENCE_GATE_ENV, 'chặt-vừa-thôi')
    client = FixtureModel([answer('xong')])
    store, _runtime, session = run_turns(tmp_path, client, ('chào',))
    sid = session['id']

    rows = notices(store, sid, EVIDENCE_MODE_UNKNOWN_CODE)
    assert len(rows) == 1 and rows[0]['value'] == 'chặt-vừa-thôi'
    assert rows[0]['partial'] is False
    assert events_of(store, sid, 'turn_end')[-1]['gateMode'] == 'warn'
    store.close()


# ---------------------------------------------------------------- P3.2 phép dò box

def test_phep_do_box_di_dung_lenh_co_dinh_va_khong_tu_bao_minh_doi(tmp_path):
    """P3.2 — lệnh dò do harness soạn: epoch của lượt, và hai gốc harness tự ghi bị loại trừ."""
    probe = '1700000000.5 12 ./src/app.py\n1700000001.5 3 ./docs/x.md\n'
    executor = FixtureExecutor(tmp_path, probe_stdout=probe)
    client = FixtureModel([answer('', calls=[call('run_script', {'path': 'scripts/migrate.py'})]),
                           answer('Đã chạy `scripts/migrate.py`.')])
    store, _runtime, session = run_turns(tmp_path, client, ('chạy script lạ',), executor=executor)
    sid = session['id']

    commands = [command for command in executor.probe_commands() if command and 'find .' in command]
    assert len(commands) == 1, 'một lượt = một phép dò'
    assert '-newermt "@' in commands[0] and '-not -path \'./.generated_artifacts/*\'' in commands[0]
    assert "-printf '%T@ %s %p\\n'" in commands[0], 'khuôn dòng cố định mà `parse_probe_output` đọc'

    step = events_of(store, sid, 'turn_end')[-1]['step']
    artifact = executor.written(f'{EVIDENCE_DIR}/{sid[:8]}/{sid[:8]}_{step}_changes.txt')
    assert artifact.exists() and 'src/app.py' in artifact.read_text(encoding='utf-8'), \
        'bản thô của phép dò phải để lại tệp đọc được'

    info = events_of(store, sid, 'assistant')[-1]['evidence']
    assert info['verdict'] == 'insufficient'
    assert info['missing'][0]['reason'] == 'change_without_verification', \
        'phép dò THẤY tệp đổi mà không có mảnh nào chứng minh ⇒ nói đúng mã đó'
    assert info['changedFiles'] == ['src/app.py', 'docs/x.md'], \
        'danh sách đã đổi đọc từ phép dò, không từ câu chữ của model'
    store.close()


def test_phep_do_ghi_tep_tho_ngoai_phien_de_khong_sinh_tep_rac(tmp_path):
    """BUG-71 — tệp thô của phép dò do CHÍNH harness ghi, không cần worker ghim lại lần nữa.

    Lượt gọi này không phải một bước của model. Mang `session` vào thì tầng ghi bằng chứng của worker
    sinh thêm một tệp `.diff` (tên mang bước `000`) bên cạnh bản đọc được, mà không mảnh cổng nào
    trỏ tới. Đo sống trước khi sửa: mỗi lượt `needs_probe` để lại ĐÚNG HAI tệp trong thư mục phiên
    (`4987d659`, `1c65d2e7` — §6.27). Không có `session` thì worker im lặng, còn tệp thô vẫn nằm
    đúng chỗ vì đường dẫn do harness dựng sẵn.
    """
    executor = FixtureExecutor(tmp_path, probe_stdout='1700000000.5 12 ./src/app.py\n')
    client = FixtureModel([answer('', calls=[call('run_script', {'path': 'scripts/migrate.py'})]),
                           answer('Đã chạy `scripts/migrate.py`.')])
    store, _runtime, session = run_turns(tmp_path, client, ('chạy script lạ',), executor=executor)
    sid = session['id']

    writes = executor.named('file_write')
    assert len(writes) == 1, 'lượt này chỉ có một lần ghi: chính tệp thô của phép dò'
    assert writes[0]['session'] is None, \
        'ghi nội bộ phải NGOÀI phiên, nếu không worker ghim thêm một tệp .diff rác (BUG-71)'

    step = events_of(store, sid, 'turn_end')[-1]['step']
    artifact = executor.written(f'{EVIDENCE_DIR}/{sid[:8]}/{sid[:8]}_{step}_changes.txt')
    assert artifact.exists() and 'src/app.py' in artifact.read_text(encoding='utf-8'), \
        'bỏ định danh không được làm mất bản thô của phép dò'
    siblings = sorted(item.name for item in artifact.parent.iterdir())
    assert siblings == [artifact.name], f'đúng một tệp bằng chứng cho lượt dò, thấy {siblings}'
    store.close()


def test_phep_do_box_chet_thi_noi_chua_do_duoc_chu_khong_phat(tmp_path):
    """R5 — box chết ⇒ `not_measurable` + `box_probe_failed`; không hạ xuống `insufficient`."""
    executor = FixtureExecutor(tmp_path, probe_raises=True)
    client = FixtureModel([answer('', calls=[call('run_script', {'path': 'scripts/migrate.py'})]),
                           answer('Đã chạy `scripts/migrate.py` xong.')])
    store, _runtime, session = run_turns(tmp_path, client, ('chạy script lạ',), executor=executor)
    sid = session['id']

    info = events_of(store, sid, 'assistant')[-1]['evidence']
    assert info['verdict'] == 'not_measurable'
    assert info['missing'][0]['reason'] == 'box_probe_failed'
    assert notices(store, sid, EVIDENCE_INSUFFICIENT_CODE) == [], 'chưa đo được thì không phạt'
    assert events_of(store, sid, 'turn_end')[-1]['evidenceVerdict'] == 'not_measurable'
    store.close()


# ---------------------------------------------------------------- P3.3 vòng vá có trần

def _insufficient_turn_calls():
    """Ba phản hồi: gọi `file_write` (không có mảnh bằng chứng) rồi câu trả lời cuối.

    Cố ý tách khỏi vòng vá: danh sách phản hồi của test tự nối thêm phần vòng vá của nó.
    """
    return [answer('', calls=[call('file_write', {'path': 'src/app.py', 'content': 'x'})]),
            answer('Đã sửa `src/app.py`.')]


def test_vong_va_chay_dung_mot_lan_khi_con_ngan_sach(tmp_path, monkeypatch):
    """P3.3 (a) — `enforce` + `insufficient` + còn ngân sách ⇒ ĐÚNG MỘT vòng model, không tool schema."""
    monkeypatch.setenv(EVIDENCE_GATE_ENV, 'enforce')
    executor = FixtureExecutor(tmp_path, with_evidence=False)
    client = FixtureModel(_insufficient_turn_calls() + [answer('Đã sửa `src/app.py`; chưa chạy test.')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',), executor=executor)
    sid = session['id']

    assert len(client.requests) == 3, 'bước tool + câu trả lời + ĐÚNG MỘT vòng vá'
    repair = client.requests[-1]
    assert repair['tools'] == [], 'vòng vá không được gửi tool schema'
    assert repair['max_tokens'] == EVIDENCE_REPAIR_MAX_TOKENS
    assert any('bằng chứng' in (m.get('content') or '') for m in repair['messages'][-1:] if m['role'] == 'user')
    payload = events_of(store, sid, 'assistant')[-1]
    assert payload['text'] == 'Đã sửa `src/app.py`; chưa chạy test.', 'văn của vòng vá được phát'
    assert payload['evidence']['repair'] is True
    assert journal_rows(store, sid, 'evidence')[0]['data']['repair'] is True
    store.close()


def test_het_ngan_sach_thi_bo_vong_va_van_tra_cau_tra_loi(tmp_path, monkeypatch):
    """P3.3 (b) — còn dưới `EVIDENCE_REPAIR_MIN_REMAINING_SECONDS` ⇒ BỎ vá, vẫn có câu trả lời."""
    monkeypatch.setenv(EVIDENCE_GATE_ENV, 'enforce')
    monkeypatch.setattr(HarnessRuntime, 'seconds_left', staticmethod(lambda budget: 5.0))
    executor = FixtureExecutor(tmp_path, with_evidence=False)
    client = FixtureModel(_insufficient_turn_calls() + [answer('bản vá không được phép chạy')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',), executor=executor)
    sid = session['id']

    assert len(client.requests) == 2, 'hết ngân sách thì KHÔNG gọi model thêm lần nào (2 = bước tool + câu trả lời)'
    payload = events_of(store, sid, 'assistant')[-1]
    assert payload['text'] == 'Đã sửa `src/app.py`.', 'văn gốc của model đi ra nguyên vẹn'
    assert payload['evidence']['repair'] is False
    assert store.get(sid)['status'] == 'completed'
    store.close()


def test_vong_va_het_gio_thi_giu_nguyen_van_va_luot_van_xong(tmp_path, monkeypatch):
    """P3.3 (c) — vòng vá ném/timeout ⇒ giữ văn cũ. Rủi ro lớn nhất của đợt là mất lượt ở đây."""
    monkeypatch.setenv(EVIDENCE_GATE_ENV, 'enforce')
    monkeypatch.setattr(HarnessRuntime, 'seconds_left', staticmethod(lambda budget: 60.0))
    executor = FixtureExecutor(tmp_path, with_evidence=False)
    client = FixtureModel(_insufficient_turn_calls() + [asyncio.TimeoutError()])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',), executor=executor)
    sid = session['id']

    assert len(client.requests) == 3, 'vòng vá đã được GỌI (khác ca hết ngân sách)'
    assert store.get(sid)['status'] == 'completed'
    payload = events_of(store, sid, 'assistant')[-1]
    assert payload['text'] == 'Đã sửa `src/app.py`.', 'vòng vá hỏng thì văn cũ ở lại'
    assert payload['evidence']['verdict'] == 'insufficient' and payload['evidence']['repair'] is False
    assert events_of(store, sid, 'turn_end')[-1]['status'] == 'completed'
    store.close()


def test_vong_va_tra_ve_rong_thi_giu_nguyen_van(tmp_path, monkeypatch):
    """P3.3 (d) — bản vá RỖNG là một lần vá hỏng: giữ văn cũ, không phát một câu trả lời trống."""
    monkeypatch.setenv(EVIDENCE_GATE_ENV, 'enforce')
    executor = FixtureExecutor(tmp_path, with_evidence=False)
    client = FixtureModel(_insufficient_turn_calls() + [answer('   ')])
    store, _runtime, session = run_turns(tmp_path, client, ('sửa app',), executor=executor)
    sid = session['id']

    payload = events_of(store, sid, 'assistant')[-1]
    assert payload['text'] == 'Đã sửa `src/app.py`.'
    assert payload['evidence']['repair'] is False
    store.close()


# ---------------------------------------------------------------- P3.6 / D-4

def test_cau_tra_loi_70k_chi_bi_canh_bao_va_giu_nguyen_van(tmp_path):
    """P3.6 — `ANSWER_WARN_CHARS` ⇒ notice `ANSWER_LONG`, không đổi một ký tự, không ghi tệp."""
    text = 'a' * (ANSWER_WARN_CHARS + 10_000)
    client = FixtureModel([answer(text)])
    executor = FixtureExecutor(tmp_path)
    store, _runtime, session = run_turns(tmp_path, client, ('viết dài',), executor=executor,
                                         name='gate-long.db')
    sid = session['id']

    assert [row.get('code') for row in notices(store, sid)] == [ANSWER_LENGTH_WARN_CODE]
    assert store.get(sid)['messages'][-1]['content'] == text
    assert [item for item in executor.named('file_write')] == [], 'chưa quá trần thì không ghi tệp'
    store.close()


def test_cau_tra_loi_200k_bi_cat_va_toan_van_nam_trong_tep(tmp_path):
    """P3.6 — quá `ANSWER_MAX_CHARS`: phát bản cắt, notice NÊU ĐƯỜNG DẪN, toàn văn đọc được."""
    text = 'b' * (ANSWER_MAX_CHARS + 50_000)
    client = FixtureModel([answer(text)])
    executor = FixtureExecutor(tmp_path)
    store, _runtime, session = run_turns(tmp_path, client, ('viết dài',), executor=executor,
                                         name='gate-long2.db')
    sid = session['id']

    row = notices(store, sid, ANSWER_TOO_LONG_CODE)[0]
    relative = f'{EVIDENCE_DIR}/{sid[:8]}/{sid[:8]}_1_answer.md'
    assert row['path'] == relative and relative in row['message'], 'notice phải nói chỗ lấy bản đầy đủ'
    stash = executor.written(relative)
    assert stash.exists() and stash.read_text(encoding='utf-8') == text, 'toàn văn, không phải bản cắt'
    kept = store.get(sid)['messages'][-1]['content']
    assert len(kept) == ANSWER_MAX_CHARS + len(answer_truncation_tail())
    assert events_of(store, sid, 'turn_end')[-1]['status'] == 'partial'
    assert journal_rows(store, sid, 'blocker')[0]['data']['path'] == relative
    store.close()


# ---------------------------------------------------------------- P1.5 dọn thư mục bằng chứng

def test_don_thu_muc_bang_chung_moi_hai_muoi_luot(tmp_path):
    """P1.5 — việc dọn chạy đúng nhịp `EVIDENCE_PRUNE_EVERY`, mang `session` + `sid8`, và không
    làm hỏng lượt nào (kể cả khi box từ chối op)."""
    executor = FixtureExecutor(tmp_path, prune_ok=False)
    client = FixtureModel([answer(f'lượt {index}') for index in range(EVIDENCE_PRUNE_EVERY)])
    store, _runtime, session = run_turns(tmp_path, client, [f'việc {i}' for i in range(EVIDENCE_PRUNE_EVERY)],
                                         executor=executor, name='gate-prune.db')
    sid = session['id']

    prunes = executor.named('captures_prune')
    assert len(prunes) == 1, 'hai mươi lượt = đúng một lượt dọn'
    assert prunes[0]['args']['session'] == sid
    assert prunes[0]['args']['sid8'] == sid[:8]
    assert store.get(sid)['status'] == 'completed'
    assert [e['data'].get('code') for e in store.events(sid) if e['type'] == 'notice'
            and e['data'].get('code')], 'box từ chối op thì notice nói ra, lượt đi tiếp'
    store.close()


# ------------------------------------------- P3.3 (vòng 23) dữ liệu đo phải sống nguyên

def test_anh_chup_tab_va_du_lieu_do_cua_cong_van_phat_nguyen_ven(tmp_path):
    """P3.3 — vòng 23 bỏ khối/huy hiệu bằng chứng quanh câu trả lời, nhưng DỮ LIỆU ĐO phải sống:
    `assistant.data.evidence` + số của `turn_end` + hàng `E:` là chỗ vòng "agent tự verify" sau này
    đọc lại. Ảnh của một TAB qua cổng như ảnh cũ, và mảnh/con trỏ mang `target` + `caption`.
    """
    executor = FixtureExecutor(tmp_path)
    client = FixtureModel([
        answer('', calls=[call('file_write', {'path': 'frontend/src/App.tsx', 'content': 'x'})]),
        answer('', calls=[call('computer_screen_capture',
                               {'target': {'kind': 'tab', 'url': '127.0.0.1:5173'},
                                'caption': 'RAG flow'}, cid='c2')]),
        answer('Đã đổi giao diện, ảnh chụp tab kèm theo.')])
    store, _runtime, session = run_turns(tmp_path, client, ('đổi giao diện',), executor=executor,
                                         name='gate-p33.db')
    sid = session['id']

    payload = events_of(store, sid, 'assistant')[-1]
    info = payload['evidence']
    assert set(info) >= {'verdict', 'mode', 'repair', 'checked', 'missing', 'artifacts',
                         'changedFiles', 'journalSeq'}
    assert info['verdict'] == 'sufficient' and info['checked'] == 2
    assert payload['text'] == 'Đã đổi giao diện, ảnh chụp tab kèm theo.', 'cổng không viết lại văn'
    assert notices(store, sid, EVIDENCE_INSUFFICIENT_CODE) == []

    pointer = [item for item in info['artifacts'] if item['kind'] == 'image'][0]
    assert set(pointer) >= {'kind', 'path', 'step', 'tool'}
    assert pointer['target'] == 'tab:127.0.0.1:5173'
    assert pointer['caption'] == 'RAG flow'
    assert pointer['tool'] == 'computer_screen_capture' and pointer['step'] == 2

    end = events_of(store, sid, 'turn_end')[-1]
    assert end['evidenceVerdict'] == 'sufficient' and end['gateMode'] == 'warn'
    row = journal_rows(store, sid, 'evidence')[0]
    assert 'image' in [item['type'] for item in row['evidence']]
    assert row['data']['verdict'] == 'sufficient'
    store.close()
