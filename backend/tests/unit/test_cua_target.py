"""Đích CUA theo phiên — quyết định thuần, chạy được trên Linux.

Máy này không phải Windows, nên đây là tầng chứng minh chính: mọi luật của tính năng "agent làm việc
trong cửa sổ nào" nằm ở `agent_core/cua_target.py` và được kiểm bằng dict cửa sổ, không cần ctypes.
"""
from __future__ import annotations

import pytest

from agentbox.agent_core import cua_target
from agentbox.agent_core.cua_target import SessionTargetStore, TargetError


def win(window_id=100, *, pid=1000, title='Untitled - Notepad', process='notepad.exe',
        window_class='Notepad'):
    return {'windowId': window_id, 'pid': pid, 'title': title,
            'processName': process, 'windowClass': window_class}


def chrome(window_id=200, *, pid=2000, title='BoxFox — Chrome'):
    return win(window_id, pid=pid, title=title, process='chrome.exe',
               window_class='Chrome_WidgetWin_1')


# --------------------------------------------------------------------------- chuẩn hoá


def test_normalize_keeps_the_identity_fields_and_drops_rubbish():
    assert cua_target.normalize({'kind': 'machine'}) == {'kind': 'machine'}
    entry = cua_target.normalize({'kind': 'window', 'windowId': '132754', 'pid': '8124',
                                  'title': 'Untitled - Notepad', 'processName': 'notepad.exe',
                                  'windowClass': 'Notepad', 'extra': 'bỏ'})
    assert entry == {'kind': 'window', 'windowId': 132754, 'pid': 8124,
                     'title': 'Untitled - Notepad', 'processName': 'notepad.exe',
                     'windowClass': 'Notepad'}


@pytest.mark.parametrize('raw', [None, {}, 'machine', {'kind': 'screen'}, {'kind': 'window'},
                                 {'kind': 'window', 'windowId': 'khong-phai-so'}])
def test_normalize_treats_broken_config_as_no_target(raw):
    assert cua_target.normalize(raw) is None


def test_describe_reads_like_a_sentence():
    assert cua_target.describe({'kind': 'machine'}) == 'cả máy'
    assert cua_target.describe(win()) == 'notepad.exe — Untitled - Notepad'
    assert cua_target.describe(None) == 'chưa chọn đích'


# --------------------------------------------------------------------------- khớp cửa sổ


def test_match_window_accepts_the_process_name_with_or_without_the_exe_suffix():
    windows = [win(), chrome()]
    assert cua_target.match_window(windows, app='notepad')['windowId'] == 100
    assert cua_target.match_window(windows, app='notepad.exe')['windowId'] == 100
    assert cua_target.match_window(windows, app='Notepad.EXE')['windowId'] == 100


def test_match_window_prefers_an_exact_title_over_a_substring():
    windows = [win(1, title='Notes'), win(2, title='Notes - Notepad')]
    assert cua_target.match_window(windows, window='Notes')['windowId'] == 1


def test_match_window_accepts_a_unique_substring():
    windows = [win(1, title='Untitled - Notepad'), chrome(2)]
    assert cua_target.match_window(windows, window='untitled')['windowId'] == 1
    assert cua_target.match_window(windows, app='chrome', window='boxfox')['windowId'] == 2


def test_match_window_refuses_to_guess_between_two_candidates():
    windows = [win(1, title='Untitled - Notepad'), win(2, title='Untitled - WordPad',
                                                      process='wordpad.exe')]
    with pytest.raises(TargetError) as caught:
        cua_target.match_window(windows, window='untitled')
    assert caught.value.code == 'TARGET_AMBIGUOUS'
    assert [item['windowId'] for item in caught.value.details['candidates']] == [1, 2]


def test_match_window_says_not_found_instead_of_picking_the_wrong_one():
    with pytest.raises(TargetError) as caught:
        cua_target.match_window([win()], app='excel')
    assert caught.value.code == 'TARGET_UNKNOWN'
    assert caught.value.details['reason'] == 'not_found'


def test_match_window_needs_at_least_one_needle():
    with pytest.raises(TargetError) as caught:
        cua_target.match_window([win()])
    assert caught.value.code == 'TARGET_UNKNOWN'


# --------------------------------------------------------------------------- kiểm lại hwnd


def test_verify_window_returns_the_live_window_when_the_handle_survives():
    target = cua_target.window_entry(win())
    assert cua_target.verify_window(target, [win(), chrome()])['windowId'] == 100


def test_verify_window_re_finds_the_window_when_the_handle_died():
    target = cua_target.window_entry(win())
    moved = win(999, title='Untitled - Notepad')
    assert cua_target.verify_window(target, [moved])['windowId'] == 999


def test_verify_window_refuses_a_recycled_handle_with_another_process():
    """Windows tái dùng hwnd: cùng số nhưng khác pid ⇒ coi như mất, tìm lại theo tên."""
    target = cua_target.window_entry(win())
    impostor = win(100, pid=777, title='Ứng dụng khác', process='other.exe', window_class='Other')
    assert cua_target.verify_window(target, [impostor]) is None


def test_verify_window_is_none_when_the_window_is_gone():
    target = cua_target.window_entry(win())
    assert cua_target.verify_window(target, [chrome()]) is None
    assert cua_target.verify_window(None, [win()]) is None


# --------------------------------------------------------------------------- phân giải


def test_resolve_prefers_the_explicit_window_id():
    windows = [win(), chrome()]
    target, source = cua_target.resolve({'windowId': 200}, {'kind': 'window', 'windowId': 100},
                                       windows, 'machine')
    assert (target['windowId'], source) == (200, 'arg')


def test_resolve_explains_an_unknown_explicit_window_id():
    with pytest.raises(TargetError) as caught:
        cua_target.resolve({'windowId': 404}, None, [win()], 'machine')
    assert caught.value.code == 'TARGET_UNKNOWN'


def test_resolve_lets_the_agent_ask_for_an_app_and_marks_the_source():
    target, source = cua_target.resolve({'app': 'chrome'}, None, [win(), chrome()], 'machine')
    assert (target['windowId'], source) == (200, 'agent')


def test_resolve_uses_the_session_target_before_anything_else():
    target, source = cua_target.resolve({}, {'kind': 'window', 'windowId': 200},
                                       [win(), chrome()], 'machine')
    assert (target['windowId'], source) == (200, 'session')


def test_resolve_reports_a_session_window_that_is_gone():
    with pytest.raises(TargetError) as caught:
        cua_target.resolve({}, {'kind': 'window', 'windowId': 100}, [chrome()], 'machine')
    assert caught.value.code == 'TARGET_UNKNOWN'
    assert caught.value.details['reason'] == 'window_gone'


def test_resolve_keeps_the_old_whole_machine_default_for_the_machine_scope():
    target, source = cua_target.resolve({}, None, [win()], 'machine')
    assert target == {'kind': 'machine'} and source == 'default'


def test_resolve_requires_a_target_when_the_scope_is_the_project_folder():
    with pytest.raises(TargetError) as caught:
        cua_target.resolve({}, None, [win()], 'workspace')
    assert caught.value.code == 'TARGET_REQUIRED'


def test_resolve_refuses_the_whole_machine_outside_the_machine_scope():
    with pytest.raises(TargetError) as caught:
        cua_target.resolve({}, {'kind': 'machine'}, [win()], 'workspace')
    assert caught.value.code == 'CUA_MACHINE_SCOPE_REQUIRED'


def test_resolve_still_allows_a_single_window_in_the_project_scope():
    target, source = cua_target.resolve({'app': 'notepad'}, None, [win()], 'workspace')
    assert (target['windowId'], source) == (100, 'agent')


def test_scope_allows_machine_only_for_the_machine_scope():
    assert cua_target.scope_allows_machine('machine') is True
    assert cua_target.scope_allows_machine('MACHINE') is True
    assert cua_target.scope_allows_machine('workspace') is False
    assert cua_target.scope_allows_machine(None) is False


# --------------------------------------------------------------------------- lưu theo phiên


class FakeStore:
    """`SessionStore` tối thiểu: một hàng config, có cha/con như thật."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get(self, sid):
        if sid not in self.rows:
            raise KeyError('Session not found')
        return {'id': sid, 'config': dict(self.rows[sid].get('config') or {}),
                'parent_id': self.rows[sid].get('parent_id')}

    def update_config(self, sid, config):
        self.rows[sid]['config'] = dict(config)


def test_store_writes_reads_and_bumps_the_revision():
    store = SessionTargetStore(FakeStore({'a': {}}))
    first = store.write('a', {'kind': 'machine'}, set_by='user')
    assert first['revision'] == 1 and first['requestedBy'] == 'user'
    assert store.read_own('a') == {'kind': 'machine'}
    second = store.write('a', cua_target.window_entry(win()), set_by='agent')
    assert second['revision'] == 2 and second['requestedBy'] == 'agent'
    assert store.read('a')['windowId'] == 100


def test_store_clear_forgets_the_target_and_bumps_the_revision():
    store = SessionTargetStore(FakeStore({'a': {}}))
    store.write('a', {'kind': 'machine'})
    cleared = store.clear('a')
    assert cleared['target'] is None and cleared['revision'] == 2
    assert store.read('a') is None


def test_child_sessions_inherit_the_parent_target_until_they_choose_their_own():
    rows = {'parent': {}, 'child': {'parent_id': 'parent'}}
    store = SessionTargetStore(FakeStore(rows))
    store.write('parent', cua_target.window_entry(win()), set_by='user')
    meta = store.read_meta('child')
    assert meta['target']['windowId'] == 100 and meta['inheritedFrom'] == 'parent'
    store.write('child', {'kind': 'machine'}, set_by='user')
    # Phiên con KHÔNG có hàng riêng: ghi của nó đi vào phiên GỐC (một máy, một đích cho cả cây),
    # nên `inheritedFrom` vẫn là `parent` — điều đổi là giá trị đích.
    assert store.read_meta('child')['target'] == {'kind': 'machine'}
    assert store.read_meta('child')['inheritedFrom'] == 'parent'
    assert store.read_own('parent') == {'kind': 'machine'}
    assert store.read_own('child') is None


def test_store_never_loops_on_a_broken_parent_chain():
    rows = {'a': {'parent_id': 'b'}, 'b': {'parent_id': 'a'}}
    store = SessionTargetStore(FakeStore(rows))
    assert store.read('a') is None
    assert store.read_meta('a')['revision'] == 0


def test_store_survives_a_missing_row():
    store = SessionTargetStore(FakeStore())
    assert store.read('khong-co') is None
    assert store.read_meta('khong-co')['target'] is None


def test_write_rejects_an_invalid_target():
    store = SessionTargetStore(FakeStore({'a': {}}))
    with pytest.raises(TargetError) as caught:
        store.write('a', {'kind': 'screen'})
    assert caught.value.code == 'TARGET_KIND_INVALID'


def test_agent_target_is_written_only_when_it_really_changed():
    """Mỗi lần ghi là một `revision` mới, mà panel coi đó là "agent vừa chuyển cửa sổ"."""
    store = SessionTargetStore(FakeStore({'a': {}}))
    target = cua_target.window_entry(win())
    cua_target.apply_agent_target(store, 'a', target, 'agent')
    assert store.read_meta('a')['revision'] == 1
    cua_target.apply_agent_target(store, 'a', target, 'agent')
    assert store.read_meta('a')['revision'] == 1, 'cùng cửa sổ thì không ghi lại'
    cua_target.apply_agent_target(store, 'a', cua_target.window_entry(chrome()), 'agent')
    assert store.read_meta('a')['revision'] == 2


def test_apply_agent_target_ignores_other_sources():
    store = SessionTargetStore(FakeStore({'a': {}}))
    cua_target.apply_agent_target(store, 'a', {'kind': 'machine'}, 'session')
    assert store.read_own('a') is None
