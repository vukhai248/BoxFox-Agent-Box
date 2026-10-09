"""Bảng sổ nguồn trong `SessionStore` (vòng 27 đợt 3, B-1) — chỗ dữ liệu nằm.

Ba rủi ro thật của một bảng mới trong một CSDL đã có người dùng: (1) mở tệp `.db` CŨ phải tự thêm
bảng chứ không bắt chủ nhà xoá dữ liệu, (2) mã dòng do harness cấp và ghi lặp cùng mã phải trả hàng
CŨ (đường gọi lại sau lỗi mạng không được sinh dòng thứ hai), (3) xoá phiên KHÔNG được xoá sổ —
sổ là bằng chứng của hồ sơ đang nằm trên đĩa (cùng lựa chọn với `plan_verifications`, ADR-0003/0004).
"""
from __future__ import annotations

import pytest

from agentbox.memory.session_store import SessionStore


def legacy_store(tmp_path):
    """Một CSDL "đời cũ": mở store rồi bỏ đúng bảng mới để mô phỏng tệp `.db` trước vòng 27."""
    path = tmp_path / 'legacy.db'
    store = SessionStore(path)
    sid = store.create({'skills': []})['id']
    with store.db:
        store.db.execute('DROP TABLE source_ledger')
    store.close()
    return path, sid


def test_the_ledger_table_is_added_without_dropping_an_older_database(tmp_path):
    path, sid = legacy_store(tmp_path)
    store = SessionStore(path)
    tables = {row[0] for row in store.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'source_ledger' in tables
    assert store.source_row(sid, 'r1') is None
    assert store.source_count(sid) == 0, 'bảng mới thêm vào, phiên cũ vẫn đọc được'
    store.close()


def test_a_ledger_row_keeps_its_payload_and_reports_the_tier(tmp_path):
    store = SessionStore(tmp_path / 's.db')
    sid = store.create({'skills': []})['id']
    row = store.source_add(sid, {'claim': 'mức hưởng', 'url': 'https://moh.gov.vn/a',
                                 'host': 'moh.gov.vn', 'tier': 1, 'excerpt': 'x' * 250,
                                 'payload': {'docNumber': '75/2023/NĐ-CP'}, 'child_id': None})
    assert row['rowId'] == 'r1'
    assert row['payload']['docNumber'] == '75/2023/NĐ-CP'
    assert 'id' not in row and 'session_id' not in row, 'view không lộ cột nội bộ'
    second = store.source_add(sid, {'row_id': 'r1', 'claim': 'khác', 'url': 'https://x.vn/b',
                                    'host': 'x.vn', 'tier': 3, 'excerpt': 'y'})
    assert second['rowId'] == 'r1' and second['claim'] == 'mức hưởng', 'ghi lặp cùng mã ⇒ hàng cũ'
    assert store.source_count(sid) == 1
    assert store.next_source_row_id(sid) == 'r2'
    store.close()


def test_the_ledger_survives_a_session_delete_like_the_plan_ledgers_do(tmp_path):
    store = SessionStore(tmp_path / 's.db')
    sid = store.create({'skills': []})['id']
    store.source_add(sid, {'claim': 'x', 'url': 'https://moh.gov.vn/a', 'host': 'moh.gov.vn',
                           'tier': 1, 'excerpt': 'x' * 250})
    # Đường xoá duy nhất còn lại: preview → capsule đã xác minh → confirm.
    history = store.history
    history.critical_snapshot = lambda ids: {'decisions': [], 'blockers': [], 'failedChecks': [],
                                             'tasks': [], 'jobs': [], 'budget': {}, 'plans': []}
    history.quiescence = lambda ids: True
    preview = history.deletion_preview(sid)
    assert history.delete_with_capsule(sid, operation_id=preview['operationId'],
                                       expected_revision=preview['expectedRevision'],
                                       confirm=True)['status'] == 'deleted'
    with pytest.raises(KeyError):
        store.get(sid)
    assert store.source_count(sid) == 1, 'sổ là bằng chứng của hồ sơ trên đĩa — không xoá theo phiên'
    store.close()


def test_a_ledger_read_can_ask_for_one_turn_or_one_branch(tmp_path):
    store = SessionStore(tmp_path / 's.db')
    sid = store.create({'skills': []})['id']
    for index in range(3):
        store.source_add(sid, {'claim': f'c{index}', 'url': f'https://a.vn/{index}', 'host': 'a.vn',
                               'tier': 2, 'excerpt': 'x' * 250, 'turn': 1 if index < 2 else 2,
                               'child_id': 'child-a' if index == 0 else None})
    assert [row['rowId'] for row in store.source_rows(sid, turn=1)] == ['r1', 'r2']
    assert [row['rowId'] for row in store.source_rows(sid, child_id='child-a')] == ['r1']
    assert {row['rowId'] for row in store.source_rows(sid, tier=2)} == {'r1', 'r2', 'r3'}
    assert [row['rowId'] for row in store.source_rows(sid, limit=1, newest_first=True)] == ['r3']
    assert store.source_counts_by_child(sid) == {'child-a': 1, '': 2}
    store.close()


def test_verifying_a_row_updates_the_row_not_a_copy(tmp_path):
    store = SessionStore(tmp_path / 's.db')
    sid = store.create({'skills': []})['id']
    store.source_add(sid, {'claim': 'x', 'url': 'https://moh.gov.vn/a', 'host': 'moh.gov.vn',
                           'tier': 1, 'excerpt': 'x' * 250, 'payload': {'docNumber': '75/2023'}})
    store.source_status_set(sid, 'r1', 'ok', matched=True)
    row = store.source_row(sid, 'r1')
    assert row['status'] == 'ok'
    assert row['payload']['verify']['matched'] is True
    assert row['payload']['docNumber'] == '75/2023', 'kiểm chứng không dẫm lên trường hồ sơ'
    store.source_status_set(sid, 'r1', 'unverified', matched=False)
    assert store.source_row(sid, 'r1')['payload']['verify']['matched'] is False
    store.close()


def test_two_branches_writing_at_once_do_not_collide_on_a_row_id(tmp_path):
    """Hai nhánh con ghi CÙNG LÚC: `UNIQUE(session_id,row_id)` biến "hai dòng cùng mã" thành
    chuyện không-thể, và đường ghi phải TỰ LẤY mã mới chứ không làm hỏng lượt của nhánh kia."""
    store = SessionStore(tmp_path / 's.db')
    sid = store.create({'skills': []})['id']
    store.source_add(sid, {'claim': 'a', 'url': 'https://a.vn/1', 'host': 'a.vn',
                           'tier': 2, 'excerpt': 'x'})
    original = store.next_source_row_id
    calls = []

    def collide(session_id):
        calls.append(session_id)
        return 'r1' if len(calls) == 1 else original(session_id)

    store.next_source_row_id = collide
    row = store.source_add(sid, {'claim': 'b', 'url': 'https://a.vn/2', 'host': 'a.vn',
                                 'tier': 2, 'excerpt': 'y'})
    assert row['rowId'] == 'r2', 'lần thử đầu đụng mã cũ ⇒ lần hai lấy mã mới'
    assert len(calls) == 2
    assert store.source_count(sid) == 2
    store.close()


def test_a_row_remembers_every_branch_that_used_it(tmp_path):
    """Dòng sổ nhớ đủ các nhánh đã mở nguồn ấy: luật idempotent giữ MỘT dòng cho một nguồn."""
    store = SessionStore(tmp_path / 'state.db')
    sid = store.create({'skills': []})['id']
    store.source_add(sid, {'claim': 'c', 'url': 'https://moh.gov.vn/a', 'excerpt': 'x' * 90,
                           'child_id': 'branch-a'})
    row_id = store.source_rows(sid)[0]['rowId']
    # Luật idempotent theo (URL, đoạn trích) nằm ở tầng TOOL (`source_add`); ở tầng bảng, mã hàng do
    # người gọi cấp — ghim lại cùng mã thì trả hàng cũ.
    again = store.source_add(sid, {'row_id': row_id, 'claim': 'c', 'url': 'https://moh.gov.vn/a',
                                   'excerpt': 'x' * 90, 'child_id': 'branch-a'})
    assert again['rowId'] == row_id and store.source_count(sid) == 1
    linked = store.source_link_branch(sid, row_id, 'branch-b')
    assert linked['branches'] == ['branch-b']
    assert store.source_link_branch(sid, row_id, 'branch-b')['branches'] == ['branch-b'], 'ghim lại không nhân đôi'
    assert store.source_link_branch(sid, row_id, 'branch-a')['branches'] == ['branch-b'], 'nhánh đầu đã ở cột child_id'
    # Nhánh thứ hai đọc được dòng ấy bằng chính mã của mình.
    assert [item['rowId'] for item in store.source_rows_for(sid, ['branch-b'])] == [row_id]
    assert [item['rowId'] for item in store.source_rows_for(sid, ['branch-a'])] == [row_id]


def test_the_payload_of_a_reused_row_can_be_filled_in(tmp_path):
    store = SessionStore(tmp_path / 'state.db')
    sid = store.create({'skills': []})['id']
    store.source_add(sid, {'claim': 'c', 'url': 'https://moh.gov.vn/a', 'excerpt': 'x' * 90,
                           'payload': {'docNumber': '15/2026/TT-BYT'}})
    row_id = store.source_rows(sid)[0]['rowId']
    updated = store.source_payload_merge(sid, row_id, {'docNumber': '15/2026/TT-BYT', 'validity': 'in_force'})
    assert updated['payload'] == {'docNumber': '15/2026/TT-BYT', 'validity': 'in_force'}
    assert store.source_payload_merge(sid, 'r99', {'a': 1}) is None, 'dòng không có ⇒ không tạo hàng mới'
