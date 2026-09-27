"""P3 — bốn op nguyên thuỷ của đường ghi có gác (`/design` mode, §6.5 + §8 P3).

Bài này chạy ĐÚNG cửa vào của worker (`worker.execute(name, args, session)`, thứ harness gửi
nội tuyến vào box mỗi lượt) trên một repo git THẬT dựng trong `tmp_path` — máy chủ nhà không có
`/home/agent/workspace` — và khoá những luật dễ vỡ nhất của đường ghi:

- `design_branch_create`: tạo nhánh từ `HEAD`, trả `{branch, base, head}`; chối tên `main`/`master`,
  tên sai khuôn (kể cả có `;`/`&&`), nhánh đã tồn tại, và workspace không phải repo git;
- `design_write`: `create` đòi tệp CHƯA tồn tại; `insert` đòi tệp ĐÃ tồn tại và một `anchor` khớp
  ĐÚNG MỘT lần (hoặc `position='append'`); chối ghi ngoài nhánh thiết kế (trừ `.design/**`) và
  đường dẫn thoát workspace;
- không có shell tự do: mọi lệnh git là danh sách tham số, `shell=False`; nội dung chứa `;`/`&&`
  được ghi NGUYÊN VĂN và không chạy gì;
- `design_diff`: đếm `added`/`removed` theo từng tệp và trả patch;
- `design_revert`: khôi phục tệp sửa đổi byte-identical, xoá tệp `new`, để lại cây làm việc SẠCH
  cho các đường dẫn đã hoàn tác và KHÔNG nhích `HEAD`.
"""
import hashlib
import subprocess
from pathlib import Path

import pytest

import agentbox.sandbox.worker as worker

INITIAL = 'alpha\nbeta\ngamma\n'


def _git(root, *args, check=True):
    proc = subprocess.run(['git', *args], cwd=str(root), capture_output=True, text=True)
    if check and proc.returncode:
        raise AssertionError('git %s failed: %s' % (' '.join(args), proc.stderr))
    return proc


def _repo(tmp_path):
    """Dựng repo git thật trong `tmp_path` và trỏ `ROOT` của worker vào đó (một commit, nhánh main)."""
    root = Path(tmp_path).resolve()
    worker.ROOT = root
    _git(root, 'init', '-q', '-b', 'main')
    _git(root, 'config', 'user.email', 'box@example.com')
    _git(root, 'config', 'user.name', 'Box')
    (root / 'app.txt').write_text(INITIAL, encoding='utf-8')
    _git(root, 'add', '.')
    _git(root, 'commit', '-q', '-m', 'init')
    return root


def _refused(name, args):
    """Lượt gọi bị từ chối: trả về ĐÚNG câu lỗi để bài kiểm đọc lý do, không nuốt mọi kiểu hỏng."""
    with pytest.raises(ValueError) as caught:
        worker.execute(name, args, 'session-1')
    return str(caught.value)


def _branch(root, name='design/ui'):
    return worker.execute('design_branch_create', {'name': name}, 'session-1')


# --- design_branch_create ---------------------------------------------------

def test_design_branch_create_tu_head_va_chuyen_sang_nhanh_moi(tmp_path):
    root = _repo(tmp_path)
    head = _git(root, 'rev-parse', 'HEAD').stdout.strip()
    result = worker.execute('design_branch_create', {'name': 'design/ui'}, 'session-1')

    assert result == {'branch': 'design/ui', 'base': head, 'head': head}
    assert _git(root, 'symbolic-ref', '--short', 'HEAD').stdout.strip() == 'design/ui'
    assert _git(root, 'rev-parse', 'HEAD').stdout.strip() == head, 'nhánh mới trỏ đúng commit cũ'


def test_design_branch_create_choi_nhanh_chinh(tmp_path):
    _repo(tmp_path)
    for name in ('main', 'master', 'HEAD'):
        message = _refused('design_branch_create', {'name': name})
        assert message.startswith('DESIGN_MAIN_BRANCH_FORBIDDEN'), message


@pytest.mark.parametrize('name', ['design/../up', 'design/x;rm -rf /', 'design/x&&y', 'design/UPPER',
                                  'design/ok/', 'design/ok/.', 'other/nh', '../design/x', ''])
def test_design_branch_create_choi_ten_sai_khuon(tmp_path, name):
    _repo(tmp_path)
    message = _refused('design_branch_create', {'name': name})
    assert 'nhánh thiết kế không hợp lệ' in message, message


def test_design_branch_create_choi_nhanh_da_ton_tai(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    _git(root, 'checkout', '-q', 'main')
    message = _refused('design_branch_create', {'name': 'design/ui'})
    assert 'DESIGN_BRANCH_EXISTS' in message, message


def test_design_branch_create_choi_workspace_khong_phai_repo(tmp_path):
    worker.ROOT = Path(tmp_path).resolve()
    message = _refused('design_branch_create', {'name': 'design/ui'})
    assert 'DESIGN_WORKSPACE_NOT_REPO' in message, message


# --- design_write: create / insert -----------------------------------------

def test_design_write_create_ghi_tep_moi_va_tra_bam(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    result = worker.execute('design_write', {'path': 'src/new.txt', 'content': 'xin chào\n',
                                             'mode': 'create'}, 'session-1')

    assert result['path'] == 'src/new.txt' and result['mode'] == 'create'
    written = (root / 'src/new.txt').read_text(encoding='utf-8')
    assert written == 'xin chào\n'
    assert result['bytes'] == len(written.encode('utf-8'))
    assert result['sha256'] == hashlib.sha256(written.encode('utf-8')).hexdigest()


def test_design_write_create_choi_tep_da_ton_tai(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    message = _refused('design_write', {'path': 'app.txt', 'content': 'x', 'mode': 'create'})
    assert 'DESIGN_WRITE_EXISTS' in message, message
    assert (root / 'app.txt').read_text(encoding='utf-8') == INITIAL, 'không được đụng tệp đã có'


def test_design_write_insert_choi_tep_chua_ton_tai(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    message = _refused('design_write', {'path': 'nope.txt', 'content': 'x', 'mode': 'insert',
                                        'position': 'append'})
    assert 'DESIGN_WRITE_MISSING' in message, message
    assert not (root / 'nope.txt').exists()


def test_design_write_anchor_khop_hai_lan_thi_choi(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    (root / 'app.txt').write_text('beta\nbeta\n', encoding='utf-8')
    message = _refused('design_write', {'path': 'app.txt', 'content': 'x', 'mode': 'insert',
                                        'anchor': 'beta'})
    assert 'DESIGN_ANCHOR_NOT_UNIQUE' in message, message
    assert (root / 'app.txt').read_text(encoding='utf-8') == 'beta\nbeta\n'


def test_design_write_anchor_khop_mot_lan_thi_chen_sau_moc(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    result = worker.execute('design_write', {'path': 'app.txt', 'content': 'BETA\n', 'mode': 'insert',
                                             'anchor': 'beta\n'}, 'session-1')
    assert result['mode'] == 'insert'
    assert (root / 'app.txt').read_text(encoding='utf-8') == 'alpha\nbeta\nBETA\ngamma\n'


def test_design_write_position_append_noi_vao_cuoi(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    worker.execute('design_write', {'path': 'app.txt', 'content': 'delta\n', 'mode': 'insert',
                                    'position': 'append'}, 'session-1')
    assert (root / 'app.txt').read_text(encoding='utf-8') == 'alpha\nbeta\ngamma\ndelta\n'


def test_design_write_insert_thieu_anchor_va_append_thi_choi(tmp_path):
    root = _repo(tmp_path)
    _branch(root)
    message = _refused('design_write', {'path': 'app.txt', 'content': 'x', 'mode': 'insert'})
    assert 'insert' in message.lower() or 'chèn' in message.lower(), message
    assert (root / 'app.txt').read_text(encoding='utf-8') == INITIAL


def test_design_write_choi_khi_o_nhanh_chinh(tmp_path):
    _repo(tmp_path)
    message = _refused('design_write', {'path': 'app.txt', 'content': 'x', 'mode': 'insert',
                                        'position': 'append'})
    assert 'DESIGN_MAIN_BRANCH_FORBIDDEN' in message, message


def test_design_write_cho_khi_o_nhanh_khac_khong_phai_design(tmp_path):
    root = _repo(tmp_path)
    _git(root, 'checkout', '-q', '-b', 'feature/khac')
    message = _refused('design_write', {'path': 'app.txt', 'content': 'x', 'mode': 'insert',
                                        'position': 'append'})
    assert 'DESIGN_BRANCH_REQUIRED' in message, message


def test_design_write_cho_phep_ghi_duoi_design_khi_o_main(tmp_path):
    root = _repo(tmp_path)
    result = worker.execute('design_write', {'path': '.design/run1/report.md', 'content': '# B\n',
                                             'mode': 'create'}, 'session-1')
    assert result['path'] == '.design/run1/report.md'
    assert (root / '.design/run1/report.md').read_text(encoding='utf-8') == '# B\n'


@pytest.mark.parametrize('bad', ['../outside.txt', '../../etc/passwd', '/etc/passwd'])
def test_design_write_choi_duong_dan_thoat_workspace(tmp_path, bad):
    _repo(tmp_path)
    _branch(worker.ROOT)
    message = _refused('design_write', {'path': bad, 'content': 'x', 'mode': 'create'})
    assert 'Path Traversal Denied' in message, message


# --- không có shell tự do ----------------------------------------------------

def test_ky_tu_meta_khong_bao_gio_toi_shell(tmp_path):
    root = _repo(tmp_path)
    canary = root / 'canary.txt'
    message = _refused('design_branch_create', {'name': 'design/x; touch canary.txt'})
    assert 'nhánh thiết kế không hợp lệ' in message, message

    _branch(root)
    payload = 'hello; touch canary.txt && echo $(id) `id`\n'
    worker.execute('design_write', {'path': 'note.txt', 'content': payload, 'mode': 'create'},
                   'session-1')

    assert (root / 'note.txt').read_text(encoding='utf-8') == payload, 'nội dung ghi NGUYÊN VĂN'
    assert not canary.exists(), 'không lệnh nào được chạy'


def test_moi_lenh_git_dung_danh_sach_tham_so(tmp_path, monkeypatch):
    _repo(tmp_path)
    seen = []
    real_run = worker.subprocess.run

    def spy(cmd, *args, **kwargs):
        seen.append((cmd, kwargs.get('shell', False)))
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(worker.subprocess, 'run', spy)
    _branch(worker.ROOT, 'design/ui')

    assert seen, 'phải có ít nhất một lệnh git'
    for command, shell in seen:
        assert isinstance(command, list), 'lệnh phải là danh sách tham số: %r' % (command,)
        assert shell is False, 'không bao giờ bật shell: %r' % (command,)


# --- design_diff -------------------------------------------------------------

def test_design_diff_dem_them_bot_va_tra_patch(tmp_path):
    root = _repo(tmp_path)
    base = _branch(root)['base']
    worker.execute('design_write', {'path': 'app.txt', 'content': 'BETA\n', 'mode': 'insert',
                                    'anchor': 'beta\n'}, 'session-1')
    worker.execute('design_write', {'path': 'added.txt', 'content': 'mot\nhai\n', 'mode': 'create'},
                   'session-1')

    result = worker.execute('design_diff', {'base': base}, 'session-1')
    rows = {row['path']: row for row in result['files']}

    assert rows['app.txt']['status'] == 'modified'
    assert rows['app.txt']['added'] == 1 and rows['app.txt']['removed'] == 0
    assert rows['added.txt']['status'] == 'added'
    assert rows['added.txt']['added'] == 2 and rows['added.txt']['removed'] == 0
    assert 'added.txt' in result['patch'] and 'app.txt' in result['patch']
    assert result['patch'].startswith('diff --git')


def test_design_diff_chi_so_cac_duong_dan_duoc_loc(tmp_path):
    root = _repo(tmp_path)
    base = _branch(root)['base']
    worker.execute('design_write', {'path': 'app.txt', 'content': 'BETA\n', 'mode': 'insert',
                                    'anchor': 'beta\n'}, 'session-1')
    worker.execute('design_write', {'path': 'added.txt', 'content': 'mot\n', 'mode': 'create'},
                   'session-1')

    result = worker.execute('design_diff', {'base': base, 'paths': ['app.txt']}, 'session-1')

    assert [row['path'] for row in result['files']] == ['app.txt']


# --- design_revert -----------------------------------------------------------

def test_design_revert_khoi_phuc_byte_identical_va_xoa_tep_new(tmp_path):
    root = _repo(tmp_path)
    before = (root / 'app.txt').read_bytes()
    head = _git(root, 'rev-parse', 'HEAD').stdout.strip()
    base = _branch(root)['base']
    worker.execute('design_write', {'path': 'app.txt', 'content': 'BETA\n', 'mode': 'insert',
                                    'anchor': 'beta\n'}, 'session-1')
    worker.execute('design_write', {'path': 'new/added.txt', 'content': 'new\n', 'mode': 'create'},
                   'session-1')
    assert (root / 'app.txt').read_bytes() != before

    result = worker.execute('design_revert', {'base': base, 'paths': ['app.txt', 'new/added.txt'],
                                              'mode': 'file'}, 'session-1')

    assert result['reverted'] == ['app.txt']
    assert result['deleted'] == ['new/added.txt']
    assert (root / 'app.txt').read_bytes() == before, 'khôi phục byte-identical'
    assert not (root / 'new/added.txt').exists(), 'tệp `new` bị xoá'
    status = _git(root, 'status', '--porcelain', '--untracked-files=all', '--',
                  'app.txt', 'new/added.txt').stdout.strip()
    assert status == '', 'cây làm việc sạch cho các đường dẫn đã hoàn tác: %r' % status
    assert _git(root, 'rev-parse', 'HEAD').stdout.strip() == head, 'HEAD không được nhích'


def test_design_revert_batch_hoan_tac_ca_lo(tmp_path):
    root = _repo(tmp_path)
    before = (root / 'app.txt').read_bytes()
    base = _branch(root)['base']
    worker.execute('design_write', {'path': 'app.txt', 'content': 'BETA\n', 'mode': 'insert',
                                    'anchor': 'beta\n'}, 'session-1')
    worker.execute('design_write', {'path': 'new/added.txt', 'content': 'new\n', 'mode': 'create'},
                   'session-1')

    result = worker.execute('design_revert', {'base': base, 'mode': 'batch'}, 'session-1')

    assert result['reverted'] == ['app.txt']
    assert result['deleted'] == ['new/added.txt']
    assert (root / 'app.txt').read_bytes() == before
    assert not (root / 'new/added.txt').exists()
    assert _git(root, 'status', '--porcelain', '--untracked-files=all').stdout.strip() == ''
