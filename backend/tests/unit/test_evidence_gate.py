"""`evidence_gate` — bộ phán thuần cho cổng bằng chứng (vòng 22, P2.1-P2.3).

Không box, không model, không đọc tệp: mọi ca dưới đây dựng dữ liệu vào bằng tay, đúng hợp đồng
"thuần" của mô-đun. Ba nhóm:

- `classify_turn` — đọc VIỆC ĐÃ LÀM từ tool call, không đọc câu chữ (kể cả ca ghi thất bại và ca
  lệnh không xác định ⇒ phải dò box);
- `assess` — năm luật R1-R5, trong đó ca quan trọng nhất là **R5 không bao giờ hạ xuống
  `insufficient`** và **thiếu trường `evidence` ⇒ không bao giờ xanh** (đối chiếu với UI P4.2);
- `repair_message` — prompt vá chỉ mang tên tệp + số, tuyệt đối không mang nội dung tệp/diff.
"""
from __future__ import annotations

from pathlib import Path

from agentbox.agent_core import evidence_gate as gate
from agentbox.sandbox import output_refs


def write_call(path, ok=True, step=None, artifact=None, numbers=None):
    # Hình dạng THẬT của `sandbox/worker.py`: văn ở `content`, `numbers` KHÔNG mang `path` (đường
    # dẫn ở lại trong tệp bằng chứng). Bài kiểm dựng sai hình dạng thì khoá sai vẫn xanh.
    result = {'content': f'Written {path}'} if ok else {'is_error': True, 'error': 'permission denied'}
    if artifact:
        result['artifact'] = artifact
    if numbers:
        result['numbers'] = numbers
    call = {'name': 'file_write', 'args': {'path': path}, 'result': result}
    if step is not None:
        call['step'] = step
    return call


def diff_call(path='frontend/src/App.tsx', step=2):
    """Một lần ghi có sinh tệp diff — đúng hình dạng worker trả trên máy thật.

    `numbers` KHÔNG có `path`; đường dẫn workspace đến từ `args['path']` của chính lời gọi ghi.
    """
    return write_call(path, step=step,
                      artifact=f'.generated_artifacts/captures/evidence/abc/abc_{step}_x.diff',
                      numbers={'bytes': 812, 'sha256After': 'b' * 64})


def command_call(command, stdout='ok', exit_code=0, step=None, artifact=None):
    # Khoá thật của worker: `content` + `exit_code`.
    result = {'content': stdout, 'exit_code': exit_code}
    if artifact:
        result['artifact'] = artifact
    call = {'name': 'terminal_exec', 'args': {'command': command}, 'result': result}
    if step is not None:
        call['step'] = step
    return call


def capture_call(step=3, path=None):
    return {'name': 'computer_screen_capture', 'args': {}, 'step': step,
            'result': {'ok': True, 'artifact': path or
                       f'.generated_artifacts/captures/screen/abc/abc_{step}_x.png',
                       'image': 'base64…'}}


def evidence(*calls):
    """Đường THẬT từ tool call tới mảnh bằng chứng — không dựng dict bằng tay trong test."""
    return gate.artifacts_from_calls(list(calls))


# --------------------------------------------------------------------------- P2.1 classify_turn

def test_luot_chi_doc_khong_can_bang_chung():
    profile = gate.classify_turn([
        {'name': 'file_read', 'args': {'path': 'docs/x.md'}, 'result': {'content': 'x'}},
        command_call('grep -rn journal backend/src', stdout='2 dòng')])

    assert profile.read_only is True and profile.kind == 'none'
    assert profile.needs_probe is False, 'lệnh chỉ đọc thì không phải dò box'
    assert profile.read_commands == ('grep -rn journal backend/src',)
    assert profile.reads == ('docs/x.md',), 'đường dẫn đã ĐỌC là việc đã làm của lượt'


def test_ghi_tep_va_ghi_duoi_frontend_la_hai_mat_khac_nhau():
    code = gate.classify_turn([write_call('backend/src/x.py')])
    assert code.writes == ('backend/src/x.py',) and code.kind == 'code' and code.read_only is False
    assert code.ui_paths == ()

    ui = gate.classify_turn([write_call('frontend/src/components/App.tsx')])
    assert ui.kind == 'ui' and ui.ui_paths == ('frontend/src/components/App.tsx',)
    assert ui.needs_probe is False, 'write tool đã nói rõ nó ghi gì — không cần dò'

    mixed = gate.classify_turn([write_call('frontend/src/App.tsx'),
                               write_call('backend/src/app.py')])
    assert mixed.kind == 'mixed'


def test_lenh_ghi_lenh_kiem_chung_va_lenh_la():
    changes = gate.classify_turn([command_call('npm run build > build.log')])
    assert changes.changes_commands == ('npm run build > build.log',)
    assert changes.needs_probe is False

    verify = gate.classify_turn([command_call('npx vitest run src/store')])
    assert verify.verify_commands == ('npx vitest run src/store',) and verify.read_only is True

    unknown = gate.classify_turn([command_call('python3 scripts/deploy.py')])
    assert unknown.uncertain is True and unknown.needs_probe is True
    assert unknown.read_only is True, 'chưa biết nó có ghi hay không — phép dò box sẽ phán'


def test_ghi_that_bai_khong_tinh_la_doi_va_van_bat_phai_do():
    profile = gate.classify_turn([write_call('backend/src/x.py', ok=False)])

    assert profile.writes == (), 'ghi hỏng thì không đổi gì'
    assert profile.uncertain is True and profile.needs_probe is True
    assert profile.failed == ('file_write',) and 'write_failed' in profile.notes


def test_giao_viec_cho_phien_con_khong_phai_lenh_khong_xac_dinh():
    profile = gate.classify_turn([{'name': 'delegate_task', 'args': {'role': 'testing'},
                                   'result': {'status': 'completed'}},
                                  {'name': 'file_read', 'args': {'path': 'a'}, 'result': {}}])

    assert profile.delegated == ('testing',)
    assert profile.uncertain is False and profile.needs_probe is False
    assert profile.read_only is False, 'có giao việc thì lượt không còn là "chỉ đọc"'


def test_tool_la_thi_coi_nhu_co_the_ghi():
    profile = gate.classify_turn([{'name': 'some_future_tool', 'args': {}, 'result': {}}])
    assert profile.uncertain is True and profile.needs_probe is True


def test_write_plan_khong_bi_cong_nay_phat_lai():
    profile = gate.classify_turn([{'name': 'write_plan', 'args': {'markdown': '# x'},
                                   'result': {'ok': True}}])
    assert profile.plan is True and profile.kind == 'plan' and profile.needs_probe is False


# ---------------------------------------------------------------------- P2.1b artifacts_from_calls

def test_manh_bang_chung_giu_ca_tep_bang_chung_lan_tep_da_doi():
    fragments = evidence(
        diff_call('frontend/src/App.tsx', step=2),
        command_call('npx vitest run', step=3,
                     artifact='/home/agent/workspace/.generated_artifacts/tools/u1.txt'),
        capture_call(step=4),
        {'name': 'delegate_task', 'args': {'role': 'testing'}, 'result': {'status': 'completed'}})

    assert [f['kind'] for f in fragments] == ['diff', 'command', 'image', 'child']
    assert fragments[0]['changed'] == 'frontend/src/App.tsx', 'tệp ĐÃ ĐỔI, không phải tệp diff'
    assert fragments[0]['sha256'] == 'b' * 64 and fragments[0]['bytes'] == 812
    assert fragments[1]['exitCode'] == 0
    assert fragments[1]['artifact'] == '.generated_artifacts/tools/u1.txt'


def test_artifact_ngoai_workspace_giu_duong_tuyet_doi_mo_duoc(tmp_path):
    """Host mode ghi artifact vào profile của app (ngoài workspace chủ): mảnh phải mang ĐÚNG đường
    của ref, không phải bản đã bị cắt mất dấu `/` đầu.

    Đây là ca `machine_router` dựng thật (`artifacts_dir=self.profile_dir / 'host-artifacts' / …`).
    ``_clean_path`` biến `/var/tmp/…/tools/x.txt` thành `var/tmp/…/tools/x.txt` — một đường tương
    đối không mở được, và ref có cấu trúc (F30) là nguồn đúng cho cả `artifact` lẫn `path`.
    """
    root = tmp_path / 'ws'
    root.mkdir()
    text = 'v' * (output_refs.SPILL_THRESHOLD_CHARS + 1)
    _, ref = output_refs.spill(root, text, target_dir=tmp_path / 'profile' / 'tools')
    assert Path(ref['path']).is_absolute(), 'điều kiện dựng ca: ref ngoài workspace phải tuyệt đối'

    fragment, = evidence({'name': 'terminal_exec', 'args': {'command': 'seq 1 5000'}, 'step': 1,
                          'result': {'content': 'v' * 32, 'exit_code': 0,
                                     'artifact': ref['path'], 'outputRef': ref}})

    assert fragment['artifact'] == ref['path']
    assert Path(fragment['artifact']).is_file(), 'đường trong mảnh phải mở được'
    assert fragment['sha256'] == ref['contentHash'] and fragment['bytes'] == ref['bytes']


def test_manh_anh_ngoai_workspace_cung_giu_duong_tuyet_doi(tmp_path):
    """Cùng luật cho khoá `path` của mảnh tệp: đường ngoài workspace đi nguyên vào mảnh."""
    outside = tmp_path / 'profile' / 'captures' / 'shot.png'
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b'png')

    fragment, = evidence({'name': 'computer_screen_capture', 'args': {}, 'step': 2,
                          'result': {'ok': True, 'image': 'base64…', 'artifact': str(outside)}})

    assert fragment['kind'] == 'image'
    assert fragment['path'] == str(outside)


def test_khoa_cua_worker_duoc_doc_dung_ten():
    """Hợp đồng khoá với `sandbox/worker.py`: `content`/`exit_code`, không phải `stdout`/`exitCode`.

    Đọc sai tên khoá là lỗi im lặng: mọi mảnh `command` mang `exit None`, phép dò không thấy tệp nào.
    """
    assert gate.box_exit_code({'exit_code': 3, 'exitCode': 7}) == 3, 'khoá thật thắng'
    assert gate.box_exit_code({'exitCode': 7}) == 7, 'khoá cũ vẫn đọc được'
    assert gate.box_exit_code({'content': 'x'}) is None
    assert gate.box_exit_code({'exit_code': 'x'}) is None, 'mã thoát phải là số nguyên'
    assert gate.box_output_tail({'content': 'hello'}) == 'hello'
    assert gate.box_output_tail({'stdout': 'hello'}) == 'hello'
    assert gate.box_output_tail({'content': 'abcdef'}, 3) == 'def'
    assert gate.box_output_tail({'content': 'abcdef'}, None) == 'abcdef'
    assert gate.box_output_tail({}) == ''


def test_manh_lenh_mang_ma_thoat_va_duoi_van_that():
    fragment = gate.artifacts_from_calls(
        [command_call('npx vitest run', stdout='12 passed', exit_code=0)])[0]
    assert fragment['exitCode'] == 0 and fragment['stdoutTail'] == '12 passed'


def test_ghi_hong_thi_khong_co_manh_bang_chung_nao():
    assert evidence(write_call('backend/src/x.py', ok=False, step=1)) == [], \
        'không có bằng chứng nào để đưa ra cho một lần ghi hỏng'


# --------------------------------------------------------------------------------- P2.2 assess

def test_r2_luot_chi_doc_la_du():
    profile = gate.classify_turn([{'name': 'file_read', 'args': {'path': 'a.md'},
                                   'result': {'content': 'x'}}])
    verdict = gate.assess('Đã đọc `a.md` và tóm tắt nội dung.', profile, None, [])

    assert verdict['verdict'] == 'sufficient' and verdict['missing'] == []
    assert 'read_only' in verdict['notes']


def test_r1_ghi_ma_khong_co_manh_nao_la_chua_kiem_chung():
    profile = gate.classify_turn([write_call('backend/src/x.py')])
    verdict = gate.assess('Đã sửa xong `backend/src/x.py`.', profile, None, [])

    assert verdict['verdict'] == 'insufficient'
    assert verdict['missing'][0]['reason'] == 'no_evidence_for_tools'
    assert verdict['changedFiles'][0]['path'] == 'backend/src/x.py'


def test_r1_ghi_co_diff_la_du():
    profile = gate.classify_turn([write_call('frontend/src/App.tsx', step=2)])
    verdict = gate.assess('Đã sửa `frontend/src/App.tsx`, diff kèm theo.',
                          profile, None, evidence(diff_call(step=2), capture_call(step=3)))

    assert verdict['verdict'] == 'sufficient' and verdict['missing'] == []
    assert verdict['checked'] == 2


def test_r1_anh_chup_truoc_thay_doi_khong_tinh():
    profile = gate.classify_turn([write_call('frontend/src/App.tsx', step=5)])
    after = capture_call(step=6)

    without_after = gate.assess('Đã đổi giao diện.', profile, None,
                                evidence(diff_call(step=5), capture_call(step=1)))
    assert without_after['verdict'] == 'insufficient'
    assert [item['reason'] for item in without_after['missing']] == ['ui_change_without_capture']

    with_after = gate.assess('Đã đổi giao diện, ảnh chụp sau khi sửa.',
                             profile, None, evidence(diff_call(step=5), capture_call(step=1), after))
    assert with_after['verdict'] == 'sufficient'


def test_r1_phat_hien_qua_phep_do_box():
    profile = gate.classify_turn([command_call('python3 scripts/deploy.py')])
    probe = {'ok': True, 'files': [{'path': 'dist/app.js', 'bytes': 10}]}

    verdict = gate.assess('Đã chạy deploy.', profile, probe, [])
    assert verdict['verdict'] == 'insufficient'
    assert verdict['missing'][0]['reason'] == 'change_without_verification'

    accepted = gate.assess('Đã chạy deploy, exit 0.', profile, probe,
                           evidence(command_call('python3 scripts/deploy.py')))
    assert accepted['verdict'] == 'sufficient', 'lệnh + exit code + phép dò xác nhận là đủ'


def test_r5_thang_r3_khi_phep_do_box_hong():
    """§2.3 — phép dò hỏng thì harness không còn dữ liệu về box: không được kết tội câu trả lời.

    Cùng một câu trả lời, cùng một hồ sơ: phép dò chết ⇒ `not_measurable`; phép dò sống ⇒ khẳng
    định về đường dẫn không có trong lượt bị ghim đúng mã.
    """
    profile = gate.classify_turn([command_call('python3 scripts/migrate.py')])
    assert profile.needs_probe and not profile.writes
    text = 'Đã chạy migrate, số liệu nằm ở `db/out.json`.'

    dead = gate.assess(text, profile, {'ok': False, 'error': 'unreachable', 'files': []}, [])
    assert dead['verdict'] == 'not_measurable'
    assert [item['reason'] for item in dead['missing']] == ['box_probe_failed']

    alive = gate.assess(text, profile, {'ok': True, 'files': []}, [])
    assert alive['verdict'] == 'insufficient'
    assert [item['reason'] for item in alive['missing']] == ['claim_path_not_in_turn']


def test_r3_cau_tra_loi_neu_tep_khong_co_trong_luot():
    profile = gate.classify_turn([write_call('backend/src/x.py', step=1)])
    # R3 chỉ kết tội khi harness CÓ dữ liệu box (R5 thắng R3 khi phép dò hỏng — xem ca riêng).
    verdict = gate.assess('Đã sửa `backend/src/x.py` và cả `docs/khong-he-ton-tai.md`.',
                          profile, {'ok': True, 'files': []},
                          evidence(diff_call('backend/src/x.py', step=1)))

    assert verdict['verdict'] == 'insufficient'
    assert [item['reason'] for item in verdict['missing']] == ['claim_path_not_in_turn']
    assert [claim['backed'] for claim in verdict['claims']] == [True, False]


def test_r3_khong_phat_tep_chi_duoc_nhac_qua():
    profile = gate.classify_turn([write_call('backend/src/x.py', step=1)])
    verdict = gate.assess('Xem thêm docs/khong-he-ton-tai.md để biết bối cảnh.',
                          profile, None, evidence(diff_call('backend/src/x.py', step=1)))

    assert verdict['verdict'] == 'sufficient', 'câu chỉ nhắc tên tệp thì không phải lời khẳng định'


def test_r3_lenh_khong_he_chay_trong_luot():
    profile = gate.classify_turn([write_call('backend/src/x.py', step=1)])
    verdict = gate.assess('Đã chạy `pytest backend/tests -q` và mọi thứ xanh.',
                          profile, None, evidence(diff_call('backend/src/x.py', step=1)))

    assert verdict['verdict'] == 'insufficient'
    assert 'answer_references_unknown_command' in [item['reason'] for item in verdict['missing']]


def test_r3_lenh_da_chay_ma_viet_trong_dau_backtick_khong_bi_phat_oan():
    """BUG-67: dấu backtick là dấu trang trí, không phải một ký tự của lệnh.

    Đo sống trước khi sửa: cùng một lượt, câu trả lời viết `` `git status --short` `` bị chấm
    `insufficient` kèm `answer_references_unknown_command` (mã lệnh lưu ra là ``"`git"``), còn câu
    không backtick thì `sufficient` — cổng phạt đúng câu trả lời trung thực vì kiểu trình bày.
    """
    profile = gate.classify_turn([command_call('git status --short', stdout='clean', exit_code=0)])

    for text in ('Đã xem trạng thái bằng `git status --short` ở cuối câu.',
                 'Đã xem trạng thái bằng `git status --short`.',
                 'Đã xem trạng thái bằng git status --short.'):
        verdict = gate.assess(text, profile, None, evidence(command_call(
            'git status --short', stdout='clean', exit_code=0)))
        assert verdict['verdict'] == 'sufficient', text
        assert verdict['missing'] == [], text
        command_claims = [claim for claim in verdict['claims'] if claim.get('command')]
        assert [claim['backed'] for claim in command_claims] == [True], text


def test_r3_cau_chi_dan_buoc_tiep_khong_bi_tinh_la_lenh_bia():
    """Soát cổng: câu chẩn đoán MỘT dòng có "Đã làm:" ở đầu và `pytest` ở cuối.

    Trước luật theo đoạn, cả dòng là một câu khẳng định nên lệnh trong mục "Thử gì tiếp" bị tính là
    lệnh bịa — đúng ca lượt chốt của B3/B4 gặp, vì prompt chẩn đoán BẮT BUỘC phải có mục đó. Mục
    "đã làm" vẫn là khẳng định, mục "thử gì tiếp" thì không.
    """
    profile = gate.classify_turn([{'name': 'file_read', 'args': {'path': 'backend/src/x.py'}}])
    verdict = gate.assess('Đã làm: đọc xong tệp. Còn lại: chưa chạy test. '
                          'Thử gì tiếp: chạy `pytest backend/tests/unit -q` rồi đọc lỗi đầu tiên.',
                          profile, None, [])

    assert verdict['verdict'] == 'sufficient', 'lời ĐỀ NGHỊ không phải lời khẳng định'
    assert [item['reason'] for item in verdict['missing']] == []


def test_r3_moi_doan_mot_nhan_thi_van_bat_duoc_ca_hai_khang_dinh():
    """Cùng luật, mặt ngược lại: chia đoạn KHÔNG được làm cổng mù trước lời khẳng định thật.

    Hai lời khẳng định trong cùng một dòng, mỗi đoạn có nhãn "đã" riêng ⇒ cả hai đều bị đối chiếu.
    """
    profile = gate.classify_turn([write_call('backend/src/x.py', step=1)])
    verdict = gate.assess('Đã sửa `backend/src/x.py`. Nhưng cũng đã tạo `docs/khong-he-ton-tai.md`.',
                          profile, None, evidence(diff_call('backend/src/x.py', step=1)))

    assert verdict['verdict'] == 'insufficient'
    assert [claim['backed'] for claim in verdict['claims']] == [True, False]
    assert [item['reason'] for item in verdict['missing']] == ['claim_path_not_in_turn']


def test_r3_dong_ngay_sau_nhan_van_thuoc_nhan_do():
    """Nhãn "Đã sửa:" đứng riêng một dòng thì đường dẫn ở dòng NGAY SAU vẫn là khẳng định."""
    profile = gate.classify_turn([write_call('backend/src/x.py', step=1)])
    verdict = gate.assess('Đã sửa:\ndocs/khong-he-ton-tai.md', profile, None,
                          evidence(diff_call('backend/src/x.py', step=1)))

    assert verdict['verdict'] == 'insufficient'
    assert [item['reason'] for item in verdict['missing']] == ['claim_path_not_in_turn']


def test_r5_thieu_du_lieu_thi_noi_chua_do_duoc_chu_khong_phat():
    profile = gate.classify_turn([command_call('python3 scripts/maybe_writes.py')])

    unreachable = gate.assess('Xong.', profile, None, [])
    assert unreachable['verdict'] == 'not_measurable'
    assert unreachable['missing'] == [{'reason': 'box_unreachable', 'detail': 'no probe result'}]

    failed = gate.assess('Xong.', profile, {'ok': False, 'error': 'timeout'}, [])
    assert failed['verdict'] == 'not_measurable'
    assert failed['missing'][0]['reason'] == 'box_probe_failed'


def test_r5_khong_bao_gio_ha_mot_luot_da_biet_la_co_doi():
    profile = gate.classify_turn([write_call('backend/src/x.py'),
                                  command_call('python3 scripts/deploy.py')])
    verdict = gate.assess('Đã sửa và deploy.', profile, {'ok': False, 'error': 'timeout'}, [])

    assert verdict['verdict'] == 'insufficient', 'biết chắc có đổi thì phải phán, không được nói chưa đo'


def test_r4_cau_tra_loi_qua_tran_do_dai():
    profile = gate.classify_turn([{'name': 'file_read', 'args': {}, 'result': {}}])
    verdict = gate.assess('x' * 150_001, profile, None, [])

    assert verdict['verdict'] == 'insufficient'
    assert 'answer_too_long' in [item['reason'] for item in verdict['missing']]


def test_cong_tat_off_thi_khong_do_gi():
    profile = gate.classify_turn([write_call('backend/src/x.py')])
    verdict = gate.assess('Đã sửa.', profile, None, [], mode='off')

    assert verdict['verdict'] == 'not_measurable' and verdict['missing'] == []
    assert 'gate_off' in verdict['notes']


def test_giao_viec_con_chua_dong_thi_chua_do_duoc():
    calls = [{'name': 'delegate_task', 'args': {'role': 'testing'},
              'result': {'status': 'completed'}}]
    profile = gate.classify_turn(calls)

    open_child = gate.assess('Đã giao cho phiên con testing.', profile, None, [])
    assert open_child['verdict'] == 'not_measurable'
    assert open_child['missing'][0]['reason'] == 'no_evidence_for_tools'

    closed = gate.assess('Đã giao cho testing, kết quả đã về.', profile, None, evidence(*calls))
    assert closed['verdict'] == 'sufficient'


# --------------------------------------------------------------------------- P2.3 repair_message

def test_prompt_va_chi_mang_ten_tep_va_so_khong_mang_noi_dung():
    profile = gate.classify_turn([write_call('frontend/src/App.tsx', step=2)])
    verdict = gate.assess('Đã đổi giao diện.', profile, None, [])
    message = gate.repair_message(verdict, profile, None)

    assert message['role'] == 'user' and len(message['content']) <= 1200
    assert 'frontend/src/App.tsx' in message['content'], 'phải nêu việc đã làm'
    assert 'ghi tệp' in message['content'] and 'ảnh/ghi hình' in message['content']
    assert gate.missing_reason('ui_change_without_capture') in message['content']
    assert 'diff --git' not in message['content'] and '@@' not in message['content']


def test_missing_reason_dich_moi_ma_va_giu_chi_tiet():
    for reason in gate.REASONS:
        text = gate.missing_reason(reason, 'chi tiết')
        assert text and 'chi tiết' in text
    assert set(gate.REASONS) == set(gate.REASON_TEXT), 'mã và lời dịch phải khớp một-một'


def test_hang_so_dong_bang_va_nhan_tieng_viet():
    assert gate.VERDICTS == ('sufficient', 'insufficient', 'not_measurable')
    labels = {verdict: gate.verdict_label(verdict) for verdict in gate.VERDICTS}
    assert labels == {'sufficient': 'đã kiểm chứng', 'insufficient': 'chưa kiểm chứng',
                      'not_measurable': 'chưa đo được'}
    assert gate.verdict_label('lạ') == 'chưa đo được', 'giá trị lạ không bao giờ thành "đã kiểm chứng"'
    assert gate.EVIDENCE_ROOT_REL == '.generated_artifacts/captures/evidence'
    assert gate.WRITE_TOOLS == ('file_write', 'file_edit_block')
    # Vòng 23 (D-18/D-20): cổng KHÔNG được thêm luật nào về cấu trúc/ngôn ngữ của câu trả lời và
    # không thêm kind bằng chứng — mọi thay đổi của vòng này là kỹ thuật (P3.1).
    assert gate.CAPTURE_ARTIFACT_KINDS == ('image', 'record')
    assert gate.REASONS == ('no_change', 'change_without_verification', 'claim_path_not_in_turn',
                            'claim_path_missing', 'ui_change_without_capture',
                            'answer_references_unknown_command', 'no_evidence_for_tools',
                            'box_unreachable', 'box_probe_failed', 'gate_error', 'answer_too_long')


# ------------------------------------------------------- P3.1 ảnh chụp có `target` (vòng 23)

def targeted_capture_call(kind='tab', step=3, url=None, caption=None, window_id='0x400003'):
    """Một lần chụp CÓ `target` — hình dạng thật sau vòng 23: model khai `target`, executor trả
    `target`/`caption` trong payload (`sandbox/executor.py`)."""
    target = {'kind': kind}
    if kind == 'tab':
        target['url'] = url or '127.0.0.1:5173'
    if kind == 'window':
        target['windowId'] = window_id
    args = {'target': target}
    if caption:
        args['caption'] = caption
    result = {'ok': True, 'artifact': f'.generated_artifacts/captures/{kind}/abc/abc_{step}_x.png',
              'dimensions': (1280, 800), 'target': dict(target)}
    if caption:
        result['caption'] = caption
    return {'name': 'computer_screen_capture', 'args': args, 'step': step, 'result': result}


def test_anh_chup_tab_van_la_anh_chup_cua_luot_va_giu_ngu_canh():
    """P3.1(a,b) — ảnh của một TAB/WINDOW vẫn là mảnh `image` (không rơi khỏi
    `CAPTURE_ARTIFACT_KINDS`), và mảnh nói được nó chụp cái gì + nhãn của lần chụp đó."""
    fragments = evidence(targeted_capture_call(kind='tab', step=3, caption='RAG flow'))
    assert fragments[0]['kind'] == 'image'
    assert fragments[0]['target'] == 'tab:127.0.0.1:5173'
    assert fragments[0]['caption'] == 'RAG flow'
    assert gate._capture_after_change(fragments, [2]) is fragments[0]

    window = evidence(targeted_capture_call(kind='window', step=4))[0]
    assert window['kind'] == 'image' and window['target'] == 'window:0x400003'
    assert 'caption' not in window, 'không có nhãn thì không bịa một nhãn'


def test_luot_giao_dien_chup_tab_la_du_bang_chung():
    """P3.1(a) — luật `ui_change_without_capture` phải nhận ảnh TAB: trước vòng 23 mọi ảnh đều là
    `kind=screen`, nên một lượt chụp tab đúng cách vẫn bị phạt oan."""
    profile = gate.classify_turn([write_call('frontend/src/App.tsx', step=2)])
    verdict = gate.assess('Đã đổi giao diện, ảnh chụp tab sau khi sửa.',
                          profile, None,
                          evidence(diff_call(step=2), targeted_capture_call(kind='tab', step=4)))
    assert verdict['verdict'] == 'sufficient' and verdict['missing'] == []


def test_anh_chup_tab_truoc_thay_doi_van_khong_tinh():
    """Luật thứ tự KHÔNG bị nới vì `kind` mới: ảnh chụp trước khi sửa vẫn không phải bằng chứng."""
    profile = gate.classify_turn([write_call('frontend/src/App.tsx', step=5)])
    verdict = gate.assess('Đã đổi giao diện.', profile, None,
                          evidence(diff_call(step=5), targeted_capture_call(kind='tab', step=1)))
    assert verdict['verdict'] == 'insufficient'
    assert [item['reason'] for item in verdict['missing']] == ['ui_change_without_capture']
