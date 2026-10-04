"""Phòng kế hoạch: kế hoạch chỉ ghi được trong `.plans/`, mọi chỗ chỉ định đều bị kẹp vào phòng.

Chủ nhà đo sống 2026-10-04: một lượt ghi ra ngoài `.plans` khiến tab Plan không thấy bản vừa ghi
và sinh thêm một thư mục `plans` khác trong workspace. Hai hàng rào được ghim ở đây:

* `file_write`/`file_edit_block` không ghi được tệp mang tên kế hoạch (`v<N>-<slug>.md`) ở ngoài
  phòng — lời gọi bị từ chối kèm việc phải làm (dùng `write_plan`);
* `write_plan` kẹp "chỗ chỉ định" vào phòng: `.plans/tao-ui`, `plans/tao-ui` và `tao-ui` là cùng
  một thư mục, nên bản `v2` nằm cạnh `v1` trong `.plans/tao-ui/`.
"""
import asyncio

import pytest

from agentbox.agent_core import plan_registry
from test_work_graph import build


def test_plan_write_outside_the_room_is_refused_before_the_sandbox_runs(tmp_path):
    _, rt, _, executor, sid = build(tmp_path)

    async def run():
        for path in ('v1-login-page.md', 'plans/v1-login-page.md', 'plans/sub/v1-login-page.md',
                     'docs/v1-login-page.md'):
            with pytest.raises(ValueError, match='PLAN_OUTSIDE_ROOM'):
                await rt.dispatch(rt.store.get(sid), 'file_write', {'path': path, 'content': '# x'})
        with pytest.raises(ValueError, match='PLAN_OUTSIDE_ROOM'):
            await rt.dispatch(rt.store.get(sid), 'file_edit_block',
                              {'path': 'plans/v1-login-page.md', 'old_text': 'a', 'new_text': 'b'})
        # Không có lời gọi nào chạm tới sandbox: cổng chặn TRƯỚC khi ghi.
        assert [name for name, _ in executor.calls if name in {'file_write', 'file_edit_block'}] == []
        # Đường đúng vẫn đi qua: ghi trong phòng không bị chặn.
        inside = await rt.dispatch(rt.store.get(sid), 'file_write',
                                   {'path': '.plans/notes.md', 'content': '# notes'})
        assert inside

    asyncio.run(run())


def empty_index(executor, plans=()):
    """Cho executor giả trả được `GET /__box/plans/index` (không có nó là nhánh suy giảm)."""
    async def request(path, body=None):
        assert path == plan_registry.INDEX_PATH
        return {'plans': list(plans), 'ignoredCount': 0, 'warnings': []}
    executor.request = request
    return executor


def test_plan_destination_is_clamped_into_the_room_for_every_spelling(tmp_path):
    _, rt, _, executor, sid = build(tmp_path)
    empty_index(executor)

    async def run():
        for directory in ('tao-ui', '.plans/tao-ui', 'plans/tao-ui', '.plans/plans/tao-ui', '../tao-ui'):
            registration = await rt.plan_registration_for(
                rt.store.get(sid), 'login-page', {'directory': directory, 'identity': None}, None)
            assert registration.directory == 'tao-ui', directory
            assert registration.identity == 'tao-ui/login-page', directory

    asyncio.run(run())
    assert executor.calls == []


def test_same_slug_group_in_a_work_folder_is_continued_there(tmp_path):
    """Không chỉ định chỗ ghi: bản v2 nối tiếp trong thư mục của bản v1, không rơi về gốc phòng."""
    _, rt, _, executor, sid = build(tmp_path)
    empty_index(executor, [{
        'identity': 'tao-ui/login-page', 'slug': 'login-page', 'relativeDirectory': 'tao-ui',
        'versions': [{'version': 1, 'relativePath': 'tao-ui/v1-login-page.md', 'sizeBytes': 10,
                      'modifiedAt': '2026-10-01T00:00:00Z', 'status': 'draft', 'headerStatus': 'ok',
                      'headerVersion': 1, 'headerIdentity': 'tao-ui/login-page',
                      'declaredParent': None, 'declaredSlug': None}],
    }])

    async def run():
        registration = await rt.plan_registration_for(
            rt.store.get(sid), 'login-page', {'directory': None, 'identity': None}, None)
        assert registration.directory == 'tao-ui'
        assert registration.identity == 'tao-ui/login-page'
        assert registration.version == 2

    asyncio.run(run())


def test_bad_destination_is_refused_with_the_room_rule(tmp_path):
    _, rt, _, _, sid = build(tmp_path)

    async def run():
        with pytest.raises(plan_registry.PlanRegistrationError) as caught:
            await rt.plan_registration_for(rt.store.get(sid), 'login-page',
                                           {'directory': 'Tao UI', 'identity': None}, None)
        assert caught.value.code == 'directory-invalid'
        assert str(caught.value).startswith('PLAN_EVAL_REJECTED: (directory-invalid)')

    asyncio.run(run())


def test_degraded_index_still_keeps_the_declared_folder(tmp_path):
    """Chỉ mục hỏng ⇒ sandbox tự chọn số (hành vi cũ), nhưng KHÔNG được mất thư mục đã chỉ."""
    _, rt, _, _, sid = build(tmp_path)  # executor không trả chỉ mục ⇒ nhánh suy giảm
    registration = asyncio.run(rt.plan_registration_for(
        rt.store.get(sid), 'login-page', {'directory': '.plans/tao-ui', 'identity': None}, None))
    assert registration.degraded
    args, evaluation = rt.plan_write_args('# Plan\n\nNội dung.\n', 'login-page', 'Login page', registration)
    assert args['directory'] == 'tao-ui' and 'version' not in args and evaluation is None
