"""Host mode đọc `.plans` trong folder dự án — CÙNG payload với `/__box/plans` của box.

Vì sao ghim ở đây: tab Plan chỉ có một đường render, nên hai chế độ phải trả cùng hình dạng dữ
liệu. Bộ đọc thật là `deploy/docker/plan_files.py` (một nguồn), còn bài kiểm này ghim phần nối:
đường dẫn, hợp đồng `request`, và cách báo lỗi (không bao giờ biến "không đọc được" thành "rỗng").
"""
import asyncio
from pathlib import Path

import pytest

from agentbox.sandbox import host_plans
from agentbox.sandbox.host_executor import HostExecutor, HostRequestUnsupported


def write_plan(workspace, slug='login-page', version=1, markdown='# Kế hoạch\n', directory=''):
    room = Path(workspace) / '.plans' / directory
    room.mkdir(parents=True, exist_ok=True)
    path = room / f'v{version}-{slug}.md'
    path.write_text(markdown, encoding='utf-8')
    return path


def test_reader_is_found_in_the_checkout():
    """Bộ đọc nằm trong bản checkout (`deploy/docker/plan_files.py`) — không cần cấu hình gì."""
    assert host_plans.plan_reader().__name__ == 'boxfox_host_plan_files'


def test_manifest_and_document_use_the_box_shape(tmp_path):
    workspace = tmp_path / 'Dự án có dấu'
    write_plan(workspace, markdown='# Bản một\n')

    manifest = host_plans.plan_manifest(workspace)
    assert manifest['plans'][0]['identity'] == 'login-page'
    assert manifest['plans'][0]['versions'][0]['version'] == 1
    assert manifest['ignoredCount'] == 0

    # `version` đi vào như chuỗi query của box (`?version=1`) vẫn đọc đúng.
    document = host_plans.plan_document(workspace, 'login-page', '1')
    assert document['markdown'] == '# Bản một\n'
    assert document['relativePath'] == 'v1-login-page.md'


def test_nested_identity_maps_to_a_subdirectory(tmp_path):
    workspace = tmp_path / 'ws'
    write_plan(workspace, slug='login', directory='designs')

    assert host_plans.plan_manifest(workspace)['plans'][0]['identity'] == 'designs/login'
    assert host_plans.plan_document(workspace, 'designs/login', 1)['markdown'] == '# Kế hoạch\n'


def test_review_is_written_where_the_box_writes_it(tmp_path):
    workspace = tmp_path / 'ws'
    write_plan(workspace)

    payload = host_plans.write_plan_review(workspace, 'login-page', 'approved', 'ổn', 1)

    assert payload['decision'] == 'approved'
    assert (Path(workspace) / '.plans' / '.reviews' / 'login-page.json').is_file()
    assert host_plans.plan_manifest(workspace)['plans'][0]['review']['decision'] == 'approved'


def test_missing_reader_is_an_error_not_an_empty_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(host_plans, 'reader_candidates', lambda: ())
    monkeypatch.setattr(host_plans, '_CACHE', None)
    with pytest.raises(host_plans.HostPlanReaderUnavailable):
        host_plans.plan_manifest(tmp_path)


def test_reader_errors_keep_their_status(tmp_path):
    """404 của bộ đọc (thiếu bản) phải đi lên nguyên mã, kèm câu người đọc tra được."""
    with pytest.raises(Exception) as caught:
        host_plans.plan_document(tmp_path, 'khong-co', 1)
    status, message = host_plans.error_status(caught.value)
    assert status == 404
    assert message


def test_executor_request_serves_plans_from_its_workspace(tmp_path):
    workspace = tmp_path / 'ws'
    write_plan(workspace, markdown='# Qua executor\n')
    executor = HostExecutor(str(workspace))

    async def run():
        index = await executor.request('/__box/plans/index')
        assert index['plans'][0]['identity'] == 'login-page'
        document = await executor.request('/__box/plans/content?identity=login-page&version=1')
        assert document['markdown'] == '# Qua executor\n'
        review = await executor.request('/__box/plans/review',
                                        {'identity': 'login-page', 'version': 1,
                                         'decision': 'changes_requested', 'note': 'sửa P3'})
        assert review['decision'] == 'changes_requested'

    asyncio.run(run())


def test_executor_request_says_which_route_is_missing(tmp_path):
    executor = HostExecutor(str(tmp_path))

    async def run():
        with pytest.raises(HostRequestUnsupported) as caught:
            await executor.request('/__box/terminal/ws')
        assert caught.value.code == 'HOST_REQUEST_UNSUPPORTED'
        assert caught.value.route == '/__box/terminal/ws'

    asyncio.run(run())


def test_reader_is_never_loaded_from_the_working_directory(tmp_path, monkeypatch):
    """Chỉ nạp bộ đọc từ chỗ thuộc bản cài — không theo `cwd` hay thư mục cha của gói.

    `plan_files.py` được `exec` trong tiến trình harness, nên một file đặt ở thư mục làm việc (nơi
    người khác ghi được) sẽ là đường chạy mã lạ.
    """
    planted = tmp_path / 'deploy' / 'docker' / 'plan_files.py'
    planted.parent.mkdir(parents=True)
    planted.write_text('MARKER = "planted"\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(host_plans, '_CACHE', None)

    candidates = host_plans.reader_candidates()

    assert planted not in candidates
    assert not [path for path in candidates if tmp_path in path.parents]
    assert getattr(host_plans.plan_reader(), 'MARKER', None) != 'planted'


def test_broken_candidate_is_skipped_for_the_next_one(tmp_path, monkeypatch):
    """Ứng viên hỏng (file rác, thiếu phụ thuộc) không được chặn bộ đọc thật ở chỗ kế tiếp."""
    broken = tmp_path / 'broken' / 'plan_files.py'
    broken.parent.mkdir()
    broken.write_text('raise RuntimeError("hỏng")\n', encoding='utf-8')
    good = tmp_path / 'good' / 'plan_files.py'
    good.parent.mkdir()
    good.write_text('MARKER = "good"\n', encoding='utf-8')
    monkeypatch.setattr(host_plans, 'reader_candidates', lambda: (broken, good))
    monkeypatch.setattr(host_plans, '_CACHE', None)

    assert host_plans.plan_reader().MARKER == 'good'


def test_all_candidates_broken_reports_why(tmp_path, monkeypatch):
    broken = tmp_path / 'broken' / 'plan_files.py'
    broken.parent.mkdir()
    broken.write_text('raise RuntimeError("hỏng")\n', encoding='utf-8')
    monkeypatch.setattr(host_plans, 'reader_candidates', lambda: (broken,))
    monkeypatch.setattr(host_plans, '_CACHE', None)

    with pytest.raises(host_plans.HostPlanReaderUnavailable) as caught:
        host_plans.plan_reader()

    assert 'hỏng' in str(caught.value)
