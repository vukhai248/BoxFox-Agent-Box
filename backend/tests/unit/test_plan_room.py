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
    async def request(path, body=None, session=None):
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

def _write_plan_schema():
    from agentbox.agent_core.tool_contracts import SCHEMAS
    return next(tool for tool in SCHEMAS if tool['function']['name'] == 'write_plan')


def test_write_plan_schema_declares_the_destination_folder():
    """Model sống chỉ biết tham số NẰM TRONG schema: chỗ ghi phải được khai, không chỉ được đọc.

    Hướng "mềm" của chủ nhà (2026-10-04): ghi theo chỗ người dùng chỉ, và bản sau nối tiếp trong
    thư mục của nhóm. Runtime đã kẹp `directory` từ `79f024b`, nhưng schema không khai tham số này —
    lượt kiểm thử thật với model miễn phí đã báo đúng như vậy ("write_plan không có tham số
    `directory`") nên hướng mềm không thể chạm tới từ model. Ca này ghim lời khai đó.
    """
    schema = _write_plan_schema()
    properties = schema['function']['parameters']['properties']
    description = properties['directory'].get('description', '')
    assert 'tao-ui' in description and '.plans/' in description
    assert 'designs/login' in description and 'nest' in description  # thư mục lồng nhau phải nói rõ
    # Không khai thêm required: chỗ ghi vẫn là tuỳ chọn, mặc định là gốc phòng.
    assert schema['function']['parameters']['required'] == ['slug', 'markdown']


def test_declared_folder_keeps_the_model_facing_name_and_the_clamped_path(tmp_path):
    """`directory` + `slug` phải cho ra đúng `.plans/<directory>/vN-<slug>.md` (không nuốt slug)."""
    _, rt, _, executor, sid = build(tmp_path)
    empty_index(executor)

    async def run():
        registration = await rt.plan_registration_for(
            rt.store.get(sid), 'dang-nhap-sso',
            {'directory': 'designs/login', 'identity': None}, None)
        assert registration.directory == 'designs/login'
        assert registration.identity == 'designs/login/dang-nhap-sso'
        assert registration.slug == 'dang-nhap-sso'
        args, _ = rt.plan_write_args('# Kế hoạch\n', 'dang-nhap-sso', 'Đăng nhập SSO', registration)
        assert args['directory'] == 'designs/login'

    asyncio.run(run())


def test_nested_folder_identity_is_journal_mintable(tmp_path):
    """Đo sống 2026-10-04: identity lồng hai cấp ghi được tệp rồi vỡ ở bước ghim `P:`.

    `directory="designs/login"` + `slug="dang-nhap-sso"` cho ra identity ba đoạn. Người đọc
    (`plan_files.py`), khối header và `runtime.PLAN_PATH_RE` đều nhận độ sâu bất kỳ, nhưng
    `journal.PLAN_IDENTITY_RE` bản cũ chỉ nhận hai đoạn: tệp `.plans/designs/login/v1-…md` đã nằm
    trên đĩa mà lượt hỏng (`TURN_FAILED_JOURNALERROR`). Ca này ghim cả chuỗi: chỗ ghi → identity →
    mã `P:` sinh ra → đọc lại mã đó.
    """
    from agentbox.agent_core import journal
    from agentbox.agent_core.runtime import plan_identity

    _, rt, _, executor, sid = build(tmp_path)
    empty_index(executor)

    async def run():
        registration = await rt.plan_registration_for(
            rt.store.get(sid), 'dang-nhap-sso', {'directory': 'designs/login'}, None)
        assert registration.identity == 'designs/login/dang-nhap-sso'
        # Cùng một identity khi đi từ đường dẫn tệp thật mà bộ đọc trả về.
        assert plan_identity('.plans/designs/login/v1-dang-nhap-sso.md') == registration.identity
        plan_id = journal.mint_id('plan', 'ab12cd34', 1,
                                  {'identity': registration.identity, 'version': registration.version})
        assert plan_id == 'P:designs/login/dang-nhap-sso@v1'
        parsed = journal.PLAN_ID_RE.match(plan_id)
        assert parsed is not None and parsed.group('slug') == registration.identity

    asyncio.run(run())


def test_declared_plain_identity_adopts_the_existing_group_folder(tmp_path):
    """Khai identity trần cho chủ đề đã có nhóm trong thư mục con: KHÔNG mở nhóm thứ hai ở gốc phòng.

    Đo sống 2026-10-04: v1 ở `.plans/designs/login/`, model khai `identity: "login"` (một đoạn) nên
    bản v2 rơi về `.plans/` — cùng chủ đề nằm hai chỗ. Ca này ghim luật nhận thư mục của nhóm cũ.
    """
    _, rt, _, executor, sid = build(tmp_path)
    empty_index(executor, [{
        'identity': 'designs/login', 'slug': 'login', 'relativeDirectory': 'designs',
        'versions': [{'version': 1, 'relativePath': 'designs/v1-login.md', 'sizeBytes': 10,
                      'modifiedAt': '2026-10-01T00:00:00Z', 'status': 'draft', 'headerStatus': 'ok',
                      'headerVersion': 1, 'headerIdentity': 'designs/login',
                      'declaredParent': None, 'declaredSlug': None}],
    }])

    async def run():
        registration = await rt.plan_registration_for(
            rt.store.get(sid), 'login', {'identity': 'login'}, None)
        assert registration.directory == 'designs'
        assert registration.identity == 'designs/login'
        assert registration.version == 2

    asyncio.run(run())
