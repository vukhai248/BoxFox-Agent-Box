"""Kịch bản bổ sung: hướng "MỀM" của chủ nhà (#6535) — đích do người dùng chỉ định.

Chủ nhà nói: "ghi theo user chỉ bảo vào đâu, nếu k có, thử tìm folder plan xem ghi vào,
với từng việc ... lưu các bản v1 v2 v3 vào trong đó". Kịch bản này kiểm đúng đường đó:

1. `plan_declared_folder` — model gọi write_plan với `directory` khai tường minh
   (ví dụ `designs/login`): tệp phải nằm trong `.plans/designs/login/`, không phải
   ở gốc phòng, và càng không được thoát ra ngoài `.plans/`.
2. `plan_folder_continue` — bản tiếp theo CÙNG chủ đề nhưng KHÔNG khai `directory`:
   phải nằm CẠNH bản cũ (nhận thư mục của nhóm), không nhảy về gốc phòng.

Chạy: python3 /code/.generated_artifacts/e2e/driver_folder.py --base 3113 --label folders
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from driver import Runner, box, plan_files  # noqa: E402

FOLDER = 'designs/login'
SLUG = 'dang-nhap-sso'


def _files_under(prefix):
    return [p for p in plan_files() if prefix in p]


def scenario_plan_declared_folder(runner):
    """Đích khai tường minh phải được tôn trọng (đã kẹp trong .plans/)."""
    before = set(plan_files())
    sid = runner.create()
    payload = runner.drive(sid, (
        'KHÔNG khảo sát codebase, KHÔNG chạy terminal, KHÔNG gọi delegate_task/peer_read. '
        'Gọi NGAY write_plan với tham số directory="designs/login", slug="dang-nhap-sso", '
        'nội dung CỰC NGẮN (tối đa 6 dòng, có mục "Verification / Acceptance criteria" kèm một lệnh '
        'và kết quả mong đợi, và mục "Risks / Limitations") cho việc: thêm đăng nhập SSO. '
        'Sau khi write_plan trả về, CHỈ trả lời một câu ngắn — không phản biện, không hỏi lại.'))
    # Chỉ soi các tệp của ĐÚNG chủ đề này: phiên khác (ví dụ lượt kiểm giao diện
    # chạy song song trên cùng box) có thể ghi kế hoạch khác trong lúc chờ.
    after = [p for p in plan_files() if p not in before and SLUG in p]
    inside_folder = [p for p in after if f'/.plans/{FOLDER}/' in p]
    tools = runner.tools_run(payload)
    checks = [
        runner.check('write_plan đã chạy', 'write_plan' in tools, sorted(set(tools))),
        runner.check('có tệp kế hoạch mới', bool(after), after),
        runner.check(f'tệp nằm trong .plans/{FOLDER}/', bool(inside_folder),
                     f'trong_thư_mục={inside_folder} tất_cả={after}'),
        runner.check('không tệp nào thoát khỏi .plans/', all('/.plans/' in p for p in after), after),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('plan_declared_folder', checks,
                         {'session': sid, 'files': after, 'tools': sorted(set(tools))})


def scenario_plan_folder_continue(runner):
    """Bản sau cùng chủ đề, KHÔNG khai đích → phải nhận thư mục của nhóm cũ."""
    before = set(plan_files())
    sid = runner.create()
    payload = runner.drive(sid, (
        'KHÔNG khảo sát codebase, KHÔNG chạy terminal, KHÔNG gọi delegate_task/peer_read. '
        f'Gọi NGAY write_plan cho bản tiếp theo của ĐÚNG kế hoạch "{SLUG}" (chủ đề đăng nhập SSO, '
        f'đang nằm trong thư mục .plans/{FOLDER}/), slug="{SLUG}", thêm mục "khoá tài khoản sau 5 lần sai". '
        'KHÔNG truyền tham số directory và KHÔNG truyền identity — để harness tự tìm thư mục của nhóm cũ. '
        'CỰC NGẮN: tối đa 6 dòng. Sau khi write_plan trả về, CHỈ trả lời một câu ngắn.'))
    after = [p for p in plan_files() if p not in before and SLUG in p]
    in_folder = [p for p in after if f'/.plans/{FOLDER}/' in p]
    in_root = [p for p in after if p.startswith('/home/agent/workspace/.plans/v')]
    checks = [
        runner.check('có bản mới', bool(after), after),
        runner.check('bản mới nhận thư mục của nhóm cũ', bool(in_folder),
                     f'trong_thư_mục={in_folder} tất_cả={after}'),
        runner.check('KHÔNG nhảy về gốc phòng', not in_root, f'ở_gốc={in_root}'),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('plan_folder_continue', checks, {'session': sid, 'files': after})


def scenario_plan_declared_folder_internal(runner):
    """Như `plan_declared_folder` nhưng chủ đề KHÔNG có sự kiện bên ngoài.

    Lượt `folders3` cho thấy cổng chất lượng (`PLAN_QUALITY_REJECTED`) từ chối kế hoạch SSO vì nó
    dựa vào sự kiện ngoài workspace (IdP/OIDC) mà phiên không có tool call nào chứng minh — tệp
    không được ghi, nên phép kiểm "có tệp mới" đỏ dù đường thư mục đã đúng. Kịch bản này giữ đúng
    phép kiểm thư mục nhưng chọn một việc thuần trong repo, không URL, không host ngoài, kèm mục
    "Verification / Acceptance criteria" có kết quả mong đợi để qua cổng chất lượng.
    """
    before = set(plan_files())
    sid = runner.create()
    payload = runner.drive(sid, (
        'KHÔNG khảo sát codebase, KHÔNG chạy terminal, KHÔNG gọi delegate_task/peer_read. '
        'Gọi NGAY write_plan với tham số directory="designs/login", slug="dang-nhap-sso", '
        'nội dung CỰC NGẮN (tối đa 8 dòng) cho việc THUẦN TRONG REPO: "thêm một mục vào tài liệu '
        'nội bộ mô tả cách chạy bộ test phòng kế hoạch". TUYỆT ĐỐI KHÔNG nêu URL, KHÔNG nêu '
        'host/dịch vụ bên ngoài, KHÔNG nêu IdP/OIDC, KHÔNG trích dẫn nguồn ngoài. Bắt buộc có mục '
        '"Verification / Acceptance criteria" nêu một lệnh cụ thể (ví dụ `pytest '
        'backend/tests/unit/test_plan_room.py -q`) KÈM KẾT QUẢ MONG ĐỢI (ví dụ "tất cả test xanh, '
        '0 lỗi"), và mục "Risks / Limitations" nêu một rủi ro cụ thể. '
        'Sau khi write_plan trả về, CHỈ trả lời một câu ngắn — không phản biện, không hỏi lại.'))
    after = [p for p in plan_files() if p not in before and SLUG in p]
    inside_folder = [p for p in after if f'/.plans/{FOLDER}/' in p]
    tools = runner.tools_run(payload)
    checks = [
        runner.check('write_plan đã chạy', 'write_plan' in tools, sorted(set(tools))),
        runner.check('có tệp kế hoạch mới', bool(after), after),
        runner.check(f'tệp nằm trong .plans/{FOLDER}/', bool(inside_folder),
                     f'trong_thư_mục={inside_folder} tất_cả={after}'),
        runner.check('không tệp nào thoát khỏi .plans/', all('/.plans/' in p for p in after), after),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('plan_declared_folder_internal', checks,
                         {'session': sid, 'files': after, 'tools': sorted(set(tools))})


def scenario_plan_bare_identity_keeps_folder(runner):
    """Khai identity TRẦN (không kèm thư mục) cho nhóm đã ở thư mục con: phải ở lại thư mục đó.

    Đo sống 2026-10-04 (lượt `folders2`): v1 ở `.plans/designs/login/`, model khai
    `identity="dang-nhap-sso"` (một đoạn) nên bản v2 rơi về `.plans/` — cùng một chủ đề nằm hai
    chỗ, bản sau trỏ `Parent: v1` của tệp trong thư mục con. Vá `ad3b5f8`: nhận thư mục của nhóm
    cũ khi nhóm đó chỉ có ĐÚNG một chỗ.
    """
    before = set(plan_files())
    sid = runner.create()
    payload = runner.drive(sid, (
        'KHÔNG khảo sát codebase, KHÔNG chạy terminal, KHÔNG gọi delegate_task/peer_read. '
        f'Gọi NGAY write_plan cho bản tiếp theo của chủ đề "{SLUG}" với identity="{SLUG}" '
        '(CHỈ identity trần, TUYỆT ĐỐI KHÔNG truyền tham số directory), slug="' + SLUG + '", '
        'thêm mục "ghi log kiểm toán cho mỗi lần đăng nhập". CỰC NGẮN (tối đa 8 dòng), thuần trong '
        'repo, KHÔNG nêu URL/host ngoài. Bắt buộc có mục "Thay đổi so với v1", mục "Verification / '
        'Acceptance criteria" (một lệnh cụ thể KÈM kết quả mong đợi) và mục "Risks / Limitations". '
        'Sau khi write_plan trả về, CHỈ trả lời một câu ngắn.'))
    after = [p for p in plan_files() if p not in before and SLUG in p]
    inside_folder = [p for p in after if f'/.plans/{FOLDER}/' in p]
    in_root = [p for p in after if p.startswith('/home/agent/workspace/.plans/v')]
    tools = runner.tools_run(payload)
    checks = [
        runner.check('write_plan đã chạy', 'write_plan' in tools, sorted(set(tools))),
        runner.check('có bản mới', bool(after), after),
        runner.check('bản mới ở lại thư mục của nhóm', bool(inside_folder) and not in_root,
                     f'trong_thư_mục={inside_folder} ở_gốc={in_root}'),
        runner.check('lượt kết thúc sạch', payload.get('status') in ('completed', 'idle'),
                     payload.get('status')),
    ]
    return runner.record('plan_bare_identity_keeps_folder', checks,
                         {'session': sid, 'files': after, 'tools': sorted(set(tools))})


SCENARIOS = {'plan_declared_folder': scenario_plan_declared_folder,
             'plan_declared_folder_internal': scenario_plan_declared_folder_internal,
             'plan_folder_continue': scenario_plan_folder_continue,
             'plan_bare_identity_keeps_folder': scenario_plan_bare_identity_keeps_folder}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='3113')
    parser.add_argument('--label', default='folders')
    parser.add_argument('--only', default='')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--timeout', type=int, default=900)
    args = parser.parse_args()
    if args.list:
        print('\n'.join(sorted(SCENARIOS)))
        return 0
    if args.timeout != 900:
        _orig_drive = Runner.drive

        def _drive(self, sid, prompt, timeout=args.timeout):
            return _orig_drive(self, sid, prompt, timeout)

        Runner.drive = _drive
    runner = Runner(args.base, args.label)
    for name in (args.only.split(',') if args.only else sorted(SCENARIOS)):
        if not name:
            continue
        print(f'== {name}')
        try:
            SCENARIOS[name](runner)
        except Exception as exc:  # noqa: BLE001
            runner.record(name, [runner.check('kịch bản chạy được', False, f'{type(exc).__name__}: {exc}')])
    summary = runner.save()
    print(json.dumps({k: summary[k] for k in ('label', 'total', 'passed', 'failed', 'blocked')},
                     ensure_ascii=False))
    return 0 if summary['failed'] == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
