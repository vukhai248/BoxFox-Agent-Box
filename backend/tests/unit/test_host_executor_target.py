"""C+D — đích CUA theo phiên trong `HostExecutor`: phân giải, chụp/tiêm đúng cửa sổ, thẻ duyệt.

Chạy trên `FakePlatform` nên kiểm được trên Linux. Trọng tâm là những luật dễ sai và khó thấy:

* `app`/`window` phân giải thành cửa sổ, và đích đó được GHI vào sổ phiên với `setBy='agent'`.
* Cửa sổ người dùng đã chọn nhận MỌI thao tác — kể cả `type`/`key` không kèm toạ độ.
* Cửa sổ chết ⇒ `TARGET_UNKNOWN` (`window_gone`), KHÔNG bắn vào cửa sổ khác.
* Thẻ duyệt CUA không có "Luôn cho phép"; lựa chọn thứ ba là "Theo app này".
* `resource_key` của CUA hẹp theo đích: đổi app là hỏi lại.
"""
from __future__ import annotations

import asyncio

import pytest
from win_fakes import FakePlatform, make_window, reset_win_state

from agentbox.agent_core import cua_target
from agentbox.agent_core import desktop_control as dc
from agentbox.agent_core import permissions as permissions_module
from agentbox.sandbox import host_executor as host_module

WORKSPACE = '/var/tmp/boxfox-cua-ws'


class FakeSessionStore:
    """Sổ phiên tối thiểu: đủ cho `SessionTargetStore` (get/update_config, `KeyError` như thật)."""

    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def get(self, sid):
        if sid not in self.rows:
            raise KeyError('Session not found')
        row = dict(self.rows[sid])
        row.setdefault('config', {})
        return row

    def update_config(self, sid, config):
        if sid not in self.rows:
            raise KeyError('Session not found')
        self.rows[sid]['config'] = dict(config)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    yield
    reset_win_state()


def build(tmp_path, *, windows=None, env=None, approver=None, trusted=True, targets=None,
          platform=None, desktop=True):
    fake = platform if platform is not None else FakePlatform(windows=windows)
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    control = dc.DesktopControl(profile_dir=profile, platform=fake) if desktop else None
    source = {'BOXFOX_PERMISSION_MODE': 'trusted', 'BOXFOX_PERMISSION_SCOPE': 'machine'}
    source.update(env or {})
    policy = permissions_module.PermissionPolicy(WORKSPACE, env=source, home=tmp_path)
    executor = host_module.HostExecutor(
        workspace=tmp_path / 'workspace', policy=policy, platform='win32', desktop=control,
        approver=approver, artifacts_dir=tmp_path / 'artifacts', trusted=trusted,
        targets=targets)
    return executor, fake


def run(executor, name, args=None, session='sess-1'):
    return asyncio.run(executor.execute(name, args or {}, session))


def store_with(target=None, rows=None):
    rows = dict(rows or {'sess-1': {}})
    store = FakeSessionStore(rows)
    if target is not None:
        store.rows['sess-1']['config'] = {'cuaTarget': target, 'cuaTargetRevision': 1,
                                          'cuaTargetSetBy': 'user'}
    return cua_target.SessionTargetStore(store)


NOTEPAD = make_window(hwnd=777, title='Untitled - Notepad', class_name='Notepad',
                      pid=4242, process_name='notepad.exe', rect=(10, 20, 640, 480),
                      extended_bounds=(10, 20, 640, 480))
CHROME = make_window(hwnd=888, title='Trang mới', class_name='Chrome_WidgetWin_1',
                     pid=5151, process_name='chrome.exe', rect=(0, 0, 1280, 800),
                     extended_bounds=(0, 0, 1280, 800))


# --------------------------------------------------------------- phân giải đích

def test_a_session_window_target_is_captured_instead_of_the_whole_screen(tmp_path):
    executor, fake = build(tmp_path, windows=[NOTEPAD],
                           targets=store_with(cua_target.window_entry(NOTEPAD)))
    payload = run(executor, 'computer_screen_capture')
    assert payload['target'] == {'kind': 'window', 'windowId': 777}
    assert payload['window']['windowId'] == 777
    assert payload['resolvedFrom'] == 'session'
    assert fake.called('bitblt_window') or fake.called('print_window')


def test_a_session_window_target_receives_typing_without_coordinates(tmp_path):
    executor, fake = build(tmp_path, windows=[NOTEPAD],
                           targets=store_with(cua_target.window_entry(NOTEPAD)))
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'xin chào'})
    assert payload.get('is_error') is not True
    assert payload['window']['windowId'] == 777
    assert fake.sent_events, 'không có sự kiện nào được gửi'


def test_the_app_argument_wins_and_is_written_to_the_session_as_agent(tmp_path):
    store = store_with()
    executor, _fake = build(tmp_path, windows=[NOTEPAD], targets=store)
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'notepad'})
    assert payload['window']['windowId'] == 777
    assert payload['resolvedFrom'] == 'agent'
    meta = store.read_meta('sess-1')
    assert meta['target']['windowId'] == 777
    assert meta['requestedBy'] == 'agent'


def test_the_window_argument_matches_by_title(tmp_path):
    executor, _fake = build(tmp_path, windows=[NOTEPAD], targets=store_with())
    payload = run(executor, 'computer_screen_capture', {'window': 'Notepad'})
    assert payload['target'] == {'kind': 'window', 'windowId': 777}
    assert payload['resolvedFrom'] == 'agent'


def test_two_matching_windows_ask_the_model_to_choose(tmp_path):
    first = make_window(hwnd=1, title='A - Notepad', process_name='notepad.exe', pid=10)
    second = make_window(hwnd=2, title='B - Notepad', process_name='notepad.exe', pid=11)
    executor, _fake = build(tmp_path, windows=[first, second], targets=store_with())
    payload = run(executor, 'computer_screen_capture', {'app': 'notepad'})
    assert payload['errorCode'] == host_module.TARGET_AMBIGUOUS_CODE
    assert {item['windowId'] for item in payload['candidates']} == {1, 2}


def test_an_unknown_app_in_a_workspace_scope_is_refused(tmp_path):
    executor, _fake = build(tmp_path, windows=[NOTEPAD], targets=store_with(),
                            env={'BOXFOX_PERMISSION_SCOPE': 'workspace'})
    payload = run(executor, 'computer_screen_capture', {'app': 'photoshop'})
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE


def test_a_dead_target_window_is_reported_and_never_redirected(tmp_path):
    executor, _fake = build(tmp_path, windows=[NOTEPAD],
                            targets=store_with({'kind': 'window', 'windowId': 999,
                                                'pid': 1, 'processName': 'photoshop.exe',
                                                'title': 'Ảnh đang sửa'}))
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a'})
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE
    assert payload['reason'] == 'window_gone'


def test_no_target_with_a_workspace_scope_asks_the_user_to_choose(tmp_path):
    executor, _fake = build(tmp_path, windows=[NOTEPAD], targets=store_with(),
                            env={'BOXFOX_PERMISSION_SCOPE': 'workspace'})
    payload = run(executor, 'computer_screen_capture')
    assert payload['errorCode'] == host_module.TARGET_REQUIRED_CODE


def test_a_machine_target_needs_the_machine_scope(tmp_path):
    executor, _fake = build(tmp_path, windows=[NOTEPAD],
                            targets=store_with({'kind': 'machine'}),
                            env={'BOXFOX_PERMISSION_SCOPE': 'workspace'})
    payload = run(executor, 'computer_screen_capture')
    assert payload['errorCode'] == host_module.MACHINE_SCOPE_REQUIRED_CODE


def test_a_machine_target_captures_the_whole_screen(tmp_path):
    executor, _fake = build(tmp_path, windows=[NOTEPAD],
                            targets=store_with({'kind': 'machine'}))
    payload = run(executor, 'computer_screen_capture')
    assert payload['target'] == {'kind': 'screen'}
    assert payload['cuaTarget'] == {'kind': 'machine'}
    assert payload['resolvedFrom'] == 'session'
    assert payload['captureOrigin'] == {'x': 0, 'y': 0}
    assert payload['captureSize'] == {'width': 1920, 'height': 1080}


# ------------------------------------------------------- khởi chạy ứng dụng

def test_a_missing_app_is_launched_when_the_scope_allows_the_whole_machine(tmp_path):
    """Chưa có Notepad nào chạy, phạm vi cả máy + folder tin cậy ⇒ agent tự mở rồi làm việc."""
    platform = FakePlatform(windows=[CHROME])

    def launch(app):
        platform.notes.append('launch:%s' % app)
        platform.windows[777] = NOTEPAD          # mở xong thì cửa sổ xuất hiện
        return 42

    platform.launch_app = launch
    executor, _fake = build(tmp_path, windows=[CHROME], platform=platform, targets=store_with())
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'notepad'})
    assert payload.get('is_error') is not True, payload
    assert platform.notes == ['launch:notepad']
    assert payload['window']['windowId'] == 777
    assert payload['resolvedFrom'] == 'agent'


def test_the_agent_never_launches_an_app_the_user_did_not_ask_for(tmp_path):
    """Đích phiên là Notepad, không có tham số `app` ⇒ không mở gì thêm."""
    platform = FakePlatform(windows=[NOTEPAD])
    platform.launch_app = lambda app: platform.notes.append('launch:%s' % app) or 42
    executor, _fake = build(tmp_path, windows=[NOTEPAD], platform=platform,
                            targets=store_with(cua_target.window_entry(NOTEPAD)))
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a'})
    assert payload.get('is_error') is not True
    assert platform.notes == []


def test_launching_needs_a_trusted_project_folder(tmp_path):
    platform = FakePlatform(windows=[CHROME])
    platform.launch_app = lambda app: platform.notes.append('launch:%s' % app) or 42
    executor, _fake = build(tmp_path, windows=[CHROME], platform=platform, targets=store_with(),
                            trusted=False)
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'notepad'})
    assert payload.get('is_error') is True
    assert platform.notes == []


def test_a_path_shaped_app_name_is_never_launched(tmp_path):
    """`..\\..\\evil.exe` và `cmd /c ...` không phải tên ứng dụng — không được tới ShellExecute."""
    platform = FakePlatform(windows=[NOTEPAD])
    platform.launch_app = lambda app: platform.notes.append('launch:%s' % app) or 42
    executor, _fake = build(tmp_path, windows=[NOTEPAD], platform=platform, targets=store_with())
    for app in (r'..\..\evil.exe', 'cmd /c calc', 'C:\\Windows\\System32\\cmd.exe'):
        payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': app})
        assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE, app
    assert platform.notes == []


def test_a_launch_failure_is_reported_with_its_code(tmp_path):
    platform = FakePlatform(windows=[CHROME])

    def boom(app):
        raise host_module.PlatformError(host_module.LAUNCH_FAILED_CODE, 'không mở được')

    platform.launch_app = boom
    executor, _fake = build(tmp_path, windows=[CHROME], platform=platform, targets=store_with())
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'notepad'})
    assert payload['errorCode'] == host_module.LAUNCH_FAILED_CODE
    assert payload['app'] == 'notepad'


def test_a_launch_that_never_produces_a_window_times_out(tmp_path, monkeypatch):
    monkeypatch.setattr(host_module, 'LAUNCH_TIMEOUT_SEC', 0.05)
    platform = FakePlatform(windows=[CHROME])
    platform.launch_app = lambda app: 42
    executor, _fake = build(tmp_path, windows=[CHROME], platform=platform, targets=store_with())
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'calc'})
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE
    assert payload['reason'] == 'launch_timeout'


# --------------------------------------------------------------- thẻ duyệt

def test_the_cua_card_offers_app_scope_instead_of_always_allow():
    decision = permissions_module.ask('thao tác trên màn hình', 'cua', 'user')
    options = host_module.approval_options(decision, 'computer_use', {'app': 'notepad'})
    ids = [option['id'] for option in options]
    assert 'approve-always' not in ids
    assert ids == ['approve', 'approve-session', 'approve-app', 'reject']


def test_the_cua_card_hides_app_scope_when_no_app_is_known():
    decision = permissions_module.ask('thao tác trên màn hình', 'cua', 'user')
    ids = [option['id'] for option in host_module.approval_options(decision, 'computer_use', {})]
    assert ids == ['approve', 'approve-session', 'reject']


def test_a_non_cua_tool_keeps_the_always_allow_choice():
    decision = permissions_module.ask('ghi tệp', 'write', 'user')
    ids = [option['id'] for option in host_module.approval_options(decision, 'file_write', {})]
    assert ids == ['approve', 'approve-session', 'approve-always', 'reject']


def test_verdicts_map_app_scope_only_for_cua():
    decision = permissions_module.ask('thao tác', 'cua', 'user')
    assert host_module.approval_verdict({'status': 'approved', 'choice': 'approve-app'},
                                        decision, 'computer_use') == 'allow_app'
    assert host_module.approval_verdict({'status': 'approved', 'choice': 'approve-app'},
                                        decision, 'file_write') == 'deny'
    assert host_module.approval_verdict({'status': 'approved', 'choice': 'approve-always'},
                                        decision, 'computer_use') == 'deny'
    assert host_module.approval_verdict({'status': 'approved', 'choice': 'approve-always'},
                                        decision, 'file_write') == 'allow_always'


def test_the_cua_reason_names_the_app_and_says_there_is_no_permanent_rule():
    decision = permissions_module.ask('thao tác', 'cua', 'user')
    reason = host_module.approval_reason(decision, 'computer_use', {'app': 'notepad'})
    assert 'notepad' in reason
    assert 'vĩnh viễn' in reason


# --------------------------------------------------------------- khoá quyền

def test_the_resource_key_of_a_cua_call_follows_the_target_not_the_session():
    policy = permissions_module.PermissionPolicy(WORKSPACE, home='/tmp/none')
    notepad = policy.resource_key('computer_use', {'__target': {'kind': 'window', 'windowId': 5,
                                                                'pid': 10,
                                                                'processName': 'notepad.exe'}})
    chrome = policy.resource_key('computer_use', {'__target': {'kind': 'window', 'windowId': 6,
                                                               'pid': 11,
                                                               'processName': 'chrome.exe'}})
    machine = policy.resource_key('computer_use', {'__target': {'kind': 'machine'}})
    assert notepad == 'cua:app:notepad'
    assert chrome == 'cua:app:chrome'
    assert machine == 'cua:machine'
    assert len({notepad, chrome, machine}) == 3


def test_the_app_spelling_does_not_change_the_resource_key():
    """`notepad`, `Notepad.exe` và `processName` của Windows phải cho cùng một khoá."""
    policy = permissions_module.PermissionPolicy(WORKSPACE, home='/tmp/none')
    keys = {
        policy.resource_key('computer_use', {'app': 'notepad'}),
        policy.resource_key('computer_use', {'app': 'Notepad.EXE'}),
        policy.resource_key('computer_use', {'__target': {'kind': 'window', 'windowId': 5,
                                                          'pid': 10,
                                                          'processName': 'notepad.exe'}}),
    }
    assert keys == {'cua:app:notepad'}


def test_app_scope_remembers_the_app_so_the_next_call_does_not_ask_again(tmp_path):
    """Bấm "Theo app này" rồi gọi lại cùng app ⇒ không hỏi lại; app khác ⇒ vẫn hỏi."""
    seen = []

    def approver(name, args, decision, session_id=None):
        seen.append(permissions_module.PermissionPolicy.resource_key(
            executor.policy, name, args))
        return 'allow_app' if len(seen) == 1 else 'deny'

    executor, fake = build(tmp_path, windows=[NOTEPAD], targets=store_with(),
                           env={'BOXFOX_PERMISSION_MODE': 'ask'}, approver=approver)
    # `launch_app` phải có: `_launchable_app` chỉ cho mở ứng dụng khi NỀN TẢNG mở được (Windows
    # `ShellExecuteW`, Linux `execv`). Thiếu nó thì lời gọi bị chặn TRƯỚC thẻ duyệt — mà bài này
    # kiểm chính chuyện thẻ duyệt có hỏi lại hay không.
    fake.launch_app = lambda app: 42
    first = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'notepad'})
    assert first.get('is_error') is not True
    assert len(seen) == 1
    second = run(executor, 'computer_use', {'action': 'type', 'text': 'b', 'app': 'notepad'})
    assert second.get('is_error') is not True
    assert len(seen) == 1, 'lần thứ hai không được hỏi lại'
    third = run(executor, 'computer_use', {'action': 'type', 'text': 'c', 'app': 'chrome'})
    assert third.get('is_error') is True
    assert len(seen) == 2, 'app khác phải hỏi lại'


# --------------------------------------------------------------- overlay

def test_cua_activity_tells_the_overlay_which_window_is_being_driven(tmp_path):
    from agentbox.agent_core.cua_overlay import CuaOverlay
    from test_cua_overlay import FakeOverlaySurface
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    executor, _fake = build(tmp_path, windows=[NOTEPAD],
                            targets=store_with(cua_target.window_entry(NOTEPAD)))
    executor.overlay = overlay
    run(executor, 'computer_use', {'action': 'type', 'text': 'a'})
    assert overlay.snapshot()['visible'] is True
    assert surface.calls[0][1][0] == {'x': 10, 'y': 20, 'width': 640, 'height': 480}


def test_a_human_holding_the_lease_pauses_the_overlay(tmp_path):
    from agentbox.agent_core.cua_overlay import CuaOverlay
    from test_cua_overlay import FakeOverlaySurface
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    executor, _fake = build(tmp_path, windows=[NOTEPAD], targets=store_with())
    executor.overlay = overlay
    control = dc.DesktopControl(profile_dir=tmp_path / 'profile', platform=FakePlatform())
    control.release_to_human('người dùng đang dùng máy')
    executor.desktop = control
    payload = run(executor, 'computer_screen_capture')
    assert payload['errorCode'] == host_module.HUMAN_HAS_CONTROL_CODE
    assert overlay.snapshot()['paused'] == 'human_has_control'


# ------------------------------------------------- đích giả mạo & hwnd tái sử dụng

def test_a_smuggled_target_cannot_narrow_the_approval_key(tmp_path):
    """`__target` là kênh NỘI BỘ: giá trị model gửi kèm phải bị bỏ trước khi hỏi quyền.

    Đường MỞ ỨNG DỤNG là chỗ hở: app còn chưa chạy nên chưa có đích nào để executor ghi đè, và
    `__target` giả mạo sẽ thành khoá duyệt. Không có chốt này, một phiên được duyệt cho Notepad có
    thể mở Chrome dưới đúng khoá `cua:app:notepad` — lựa chọn "theo app này" của người dùng bị dùng
    cho một ứng dụng khác.
    """
    platform = FakePlatform(windows=[NOTEPAD])       # Notepad đang chạy, Chrome thì chưa

    def launch(app):
        platform.notes.append('launch:%s' % app)
        platform.windows[888] = CHROME               # mở xong thì cửa sổ Chrome xuất hiện
        return 42

    platform.launch_app = launch
    executor, _fake = build(tmp_path, platform=platform, targets=store_with(),
                            env={'BOXFOX_PERMISSION_MODE': 'ask'},
                            approver=lambda *args, **kwargs: 'allow_session')
    smuggled = {'kind': 'window', 'windowId': 777, 'pid': 4242, 'processName': 'notepad.exe'}
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a', 'app': 'chrome',
                                             '__target': smuggled})
    assert payload.get('is_error') is not True, payload
    assert platform.notes == ['launch:chrome']
    assert payload['window']['windowId'] == 888
    keys = list(executor.policy.session_rules)
    assert any('cua:app:chrome' in key for key in keys), keys
    assert not any('cua:app:notepad' in key for key in keys), keys


def _reused_window():
    """Cùng hwnd 777 nhưng đã thuộc tiến trình khác — hwnd bị Windows cấp lại."""
    return make_window(hwnd=777, title='Ứng dụng khác', class_name='Other', pid=9999,
                       process_name='other.exe', rect=(0, 0, 300, 200),
                       extended_bounds=(0, 0, 300, 200))


def _approver_that_replaces_the_window(fake):
    """Đổi chủ cửa sổ ĐÚNG lúc thẻ duyệt còn mở: khe thời gian thật giữa `verify_window` và lúc chụp."""
    def approver(name, args, decision, session_id=None):
        fake.windows[777] = _reused_window()
        return 'allow'
    return approver


def test_a_window_that_changes_owner_before_the_capture_is_refused(tmp_path):
    executor, fake = build(tmp_path, windows=[NOTEPAD],
                           targets=store_with(cua_target.window_entry(NOTEPAD)),
                           env={'BOXFOX_PERMISSION_MODE': 'ask'}, approver=None)
    executor.approver = _approver_that_replaces_the_window(fake)
    payload = run(executor, 'computer_screen_capture')
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE
    assert payload['reason'] == 'window_reused'
    assert not fake.called('bitblt_window') and not fake.called('print_window')


def test_input_is_refused_when_the_window_changes_owner(tmp_path):
    executor, fake = build(tmp_path, windows=[NOTEPAD],
                           targets=store_with(cua_target.window_entry(NOTEPAD)),
                           env={'BOXFOX_PERMISSION_MODE': 'ask'}, approver=None)
    executor.approver = _approver_that_replaces_the_window(fake)
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'a'})
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE
    assert payload['reason'] == 'window_reused'
    assert not fake.sent_events, 'không được gửi sự kiện nào vào cửa sổ đã đổi chủ'
