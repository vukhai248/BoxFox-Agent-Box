"""H7 — công cụ CUA trong `HostExecutor`: lease → quyền → mutex → fence → input.

Chạy trên `FakePlatform` (nền tảng giả của `win_fakes.py`) nên kiểm được trên Linux. Không ca nào
chạm Windows thật, không ca nào ghi ra ngoài `tmp_path`.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest
from win_fakes import FakePlatform, decode_events, make_window, reset_win_state

from agentbox.agent_core import desktop_control as dc
from agentbox.agent_core import permissions as permissions_module
from agentbox.sandbox import host_executor as host_module
from agentbox.sandbox.win import errors as win_errors

WORKSPACE = '/var/tmp/boxfox-cua-ws'


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    yield
    reset_win_state()


def build(tmp_path, *, platform=None, desktop=True, env=None, approver='allow', windows=None):
    """`(executor, control, platform)` — sẵn sàng cho một lời gọi CUA."""
    fake = platform if platform is not None else FakePlatform(windows=windows)
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    control = dc.DesktopControl(profile_dir=profile, platform=fake) if desktop else None
    source = {'BOXFOX_PERMISSION_MODE': 'ask'}
    source.update(env or {})
    # `home=tmp_path`: tầng `user` là `<home>/.boxfox/settings.json`. Không cô lập thì một máy đã
    # từng đổi mức quyền từ giao diện sẽ ghi đè biến môi trường của bài kiểm này.
    policy = permissions_module.PermissionPolicy(WORKSPACE, env=source, home=tmp_path)
    executor = host_module.HostExecutor(
        workspace=tmp_path / 'workspace', policy=policy, platform='win32', desktop=control,
        approver=(lambda name, args, decision, session_id=None: approver) if approver else None,
        artifacts_dir=tmp_path / 'artifacts')
    return executor, control, fake


def run(executor, name, args=None, session='sess-1'):
    return asyncio.run(executor.execute(name, args or {}, session))


# ------------------------------------------------------------------ hợp đồng

def test_the_three_cua_tools_are_declared_as_host_tools():
    for name in ('computer_screen_capture', 'inspect_element', 'computer_use'):
        assert name in host_module.HOST_TOOLS
        assert name not in host_module.DEFERRED_TOOLS


def test_cua_without_a_desktop_controller_returns_a_coded_error(tmp_path):
    executor, _control, _fake = build(tmp_path, desktop=False)
    payload = run(executor, 'computer_screen_capture')
    assert payload['is_error'] is True
    assert payload['errorCode'] == host_module.CUA_UNAVAILABLE_CODE


def test_cua_without_a_desktop_platform_is_unsupported(tmp_path, monkeypatch):
    """Không có nền tảng desktop nào (Linux không có X11, hệ điều hành lạ) ⇒ lỗi có mã."""
    executor, _control, _fake = build(tmp_path)
    monkeypatch.setattr(executor, '_desktop_platform', lambda: None)
    payload = run(executor, 'inspect_element', {'x': 1, 'y': 2})
    assert payload['errorCode'] == host_module.UNSUPPORTED_CODE


def test_a_linux_host_with_a_desktop_platform_passes_the_platform_gate(tmp_path):
    """Đổi hành vi có chủ ý (08/10/2026): Linux có X11 không còn bị chặn ở cổng nền tảng.

    Trước đây cổng này hỏi `sys.platform`, nên mọi máy `posix` đều trả `UNSUPPORTED_CODE`. Nay nó
    hỏi *có nền tảng desktop hay không* — `posix` + X11 là hợp lệ.
    """
    executor, _control, _fake = build(tmp_path)
    executor.platform = 'posix'
    payload = run(executor, 'inspect_element', {'x': 1, 'y': 2})
    assert payload.get('errorCode') != host_module.UNSUPPORTED_CODE


def test_a_human_holding_the_lease_blocks_every_cua_tool(tmp_path):
    executor, control, _fake = build(tmp_path)
    control.release_to_human('người dùng đang dùng máy')
    for name, args in (('computer_screen_capture', {}), ('inspect_element', {'x': 1, 'y': 2}),
                       ('computer_use', {'action': 'click', 'x': 1, 'y': 2})):
        payload = run(executor, name, args)
        assert payload['is_error'] is True, name
        assert payload['errorCode'] == host_module.HUMAN_HAS_CONTROL_CODE, name
        assert payload['holder'] == dc.HOLDER_HUMAN


def test_plan_mode_denies_cua_before_it_reaches_the_desktop(tmp_path):
    executor, control, fake = build(tmp_path, env={'BOXFOX_PERMISSION_MODE': 'plan'}, approver=None)
    payload = run(executor, 'computer_screen_capture')
    assert payload['errorCode'] == host_module.PERMISSION_DENIED_CODE
    assert fake.called('bitblt_screen') == []


def test_trusted_mode_needs_no_approver(tmp_path):
    executor, _control, _fake = build(tmp_path, env={'BOXFOX_PERMISSION_MODE': 'trusted'},
                                      approver=None)
    payload = run(executor, 'computer_screen_capture')
    assert payload.get('is_error') is not True
    assert payload['mime'] == 'image/png'


def test_a_denied_approval_never_reaches_the_desktop(tmp_path):
    executor, _control, fake = build(tmp_path, approver='deny')
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 5, 'y': 5})
    assert payload['errorCode'] == host_module.PERMISSION_DENIED_CODE
    assert fake.sent_events == []


# ------------------------------------------------------------ chụp màn hình

def test_capture_returns_the_same_payload_shape_as_the_box(tmp_path):
    executor, _control, _fake = build(tmp_path)
    payload = run(executor, 'computer_screen_capture', {'caption': 'màn hình lúc bắt đầu'})
    assert payload['content'].startswith('Host screenshot ')
    assert payload['dimensions'] == (1920, 1080)
    assert payload['mime'] == 'image/png'
    assert payload['target'] == {'kind': 'screen'}
    assert payload['caption'] == 'màn hình lúc bắt đầu'
    assert payload['label']['source_kind'] == 'screen_capture'
    assert payload['label']['integrity'] == 'khong_tin_duoc'
    assert payload['label']['content_hash'] == payload['sha256']
    raw = base64.b64decode(payload['image'])
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'
    assert payload['artifact'].endswith('.png')


def test_capture_writes_the_png_under_the_artifacts_directory(tmp_path):
    executor, _control, _fake = build(tmp_path)
    payload = run(executor, 'computer_screen_capture')
    written = tmp_path / 'artifacts' / 'captures' / payload['artifact'].split('/')[-1]
    assert payload['artifact'] == str(written)
    assert written.is_file()
    assert written.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'


def test_capture_of_a_window_names_the_window_in_the_target(tmp_path):
    window = make_window(hwnd=4242, title='Notepad')
    executor, _control, _fake = build(tmp_path, windows=[window])
    payload = run(executor, 'computer_screen_capture', {'windowId': 4242})
    assert payload['target'] == {'kind': 'window', 'windowId': 4242}
    assert '4242' in payload['artifact']


def test_capture_refuses_an_unknown_window_id(tmp_path):
    executor, _control, _fake = build(tmp_path)
    payload = run(executor, 'computer_screen_capture', {'windowId': 999999})
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE


def test_capture_does_not_take_the_input_mutex(tmp_path):
    executor, control, _fake = build(tmp_path)
    run(executor, 'computer_screen_capture')
    assert control.mutex.handle is None


# ------------------------------------------------------------ soi phần tử

def test_inspect_element_returns_the_element_payload(tmp_path, monkeypatch):
    executor, _control, fake = build(tmp_path)
    seen = {}

    def fake_inspect(x, y, *, platform=None, **kwargs):
        seen['point'] = (x, y)
        seen['platform'] = platform
        return {'windowId': 100, 'kind': 'dom', 'tag': 'button', 'text': 'Lưu'}

    monkeypatch.setattr('agentbox.agent_core.inspect_host.inspect_element', fake_inspect)
    payload = run(executor, 'inspect_element', {'x': 12, 'y': 34})
    assert payload['tag'] == 'button'
    assert seen['point'] == (12, 34)
    assert seen['platform'] is fake


def test_inspect_element_needs_integer_coordinates(tmp_path):
    executor, _control, _fake = build(tmp_path)
    payload = run(executor, 'inspect_element', {'x': 'không phải số', 'y': 1})
    assert payload['errorCode'] == 'TOOL_ARGUMENT_INVALID'


def test_inspect_element_reports_a_platform_error_with_its_code(tmp_path, monkeypatch):
    executor, _control, _fake = build(tmp_path)

    def boom(x, y, *, platform=None, **kwargs):
        raise win_errors.PlatformError(win_errors.ELEMENT_STALE, 'phần tử đã đổi')

    monkeypatch.setattr('agentbox.agent_core.inspect_host.inspect_element', boom)
    payload = run(executor, 'inspect_element', {'x': 1, 'y': 1})
    assert payload['errorCode'] == win_errors.ELEMENT_STALE


# ------------------------------------------------------------- tiêm input

def test_a_click_goes_through_send_input_and_marks_own_input(tmp_path):
    executor, control, fake = build(tmp_path)
    before = control._last_input_tick
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 20, 'y': 30})
    assert payload.get('is_error') is not True
    assert payload['route'] == 'send_input'
    assert payload['action'] == 'click'
    assert payload['effect'] == 'unverifiable'
    assert payload['verified'] is None
    assert payload['leaseEpoch'] == 0
    assert fake.sent_events, 'không có sự kiện nào được gửi'
    # Điểm chạm vào chính chuột/phím do agent gửi KHÔNG được tính là người dùng giành quyền.
    assert control._last_input_tick != before


def test_a_click_releases_the_mutex_when_it_is_done(tmp_path):
    executor, control, _fake = build(tmp_path)
    run(executor, 'computer_use', {'action': 'click', 'x': 20, 'y': 30})
    assert control.mutex.handle is None


def test_a_double_click_sends_two_clicks(tmp_path):
    executor, _control, fake = build(tmp_path)
    run(executor, 'computer_use', {'action': 'double_click', 'x': 20, 'y': 30})
    clicks = [event for event in decode_events(fake.sent_events) if event['kind'] == 'mouse']
    assert len(clicks) == 6, 'hai cú bấm = hai lần (move + down + up)'


def test_typing_uses_the_unicode_path(tmp_path):
    executor, _control, fake = build(tmp_path)
    payload = run(executor, 'computer_use', {'action': 'type', 'text': 'Xin chào'})
    assert payload['action'] == 'type_text'
    assert payload['chars'] == len('Xin chào')
    assert fake.sent_events


def test_a_named_key_is_pressed(tmp_path):
    executor, _control, fake = build(tmp_path)
    payload = run(executor, 'computer_use', {'action': 'key', 'key': 'enter'})
    assert payload['action'] == 'press_key'
    assert fake.sent_events


def test_an_unknown_action_is_refused_with_a_code(tmp_path):
    executor, _control, fake = build(tmp_path)
    payload = run(executor, 'computer_use', {'action': 'scroll', 'x': 1, 'y': 1})
    assert payload['errorCode'] == host_module.UNSUPPORTED_ACTION_CODE
    assert fake.sent_events == []


def test_a_click_without_a_target_window_is_refused(tmp_path):
    executor, _control, _fake = build(tmp_path, windows=[make_window(hwnd=100, rect=(0, 0, 10, 10))])
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 5000, 'y': 5000})
    assert payload['errorCode'] == host_module.TARGET_UNKNOWN_CODE


def test_a_click_finds_the_window_under_the_point(tmp_path):
    window = make_window(hwnd=777, rect=(0, 0, 400, 300))
    executor, _control, fake = build(tmp_path, windows=[window])
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 50, 'y': 60})
    assert payload.get('is_error') is not True
    assert payload['windowId'] == 777
    assert ('set_foreground_window', (777,)) in fake.calls


def test_a_busy_mutex_refuses_to_send_anything(tmp_path):
    executor, _control, fake = build(tmp_path, platform=FakePlatform(mutex_acquired=False))
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 20, 'y': 30})
    assert payload['errorCode'] == win_errors.CONTROL_BUSY
    assert fake.sent_events == []


def test_a_human_takeover_between_approval_and_send_cancels_the_input(tmp_path):
    executor, control, fake = build(tmp_path)
    real_begin = control.begin_action

    def begin_then_human_takes_over(action, target=None, **kwargs):
        token, code = real_begin(action, target, **kwargs)
        control.release_to_human('người dùng chạm chuột')
        return token, code

    control.begin_action = begin_then_human_takes_over
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 20, 'y': 30})
    assert payload['errorCode'] == win_errors.HUMAN_HAS_CONTROL
    assert fake.sent_events == [], 'input không được gửi sau khi quyền đổi tay'


def test_a_token_from_an_older_generation_is_fenced_out(tmp_path):
    executor, control, fake = build(tmp_path)
    real_begin = control.begin_action

    def begin_then_generation_bumps(action, target=None, **kwargs):
        token, code = real_begin(action, target, **kwargs)
        control.generation += 1      # ví dụ: nút Dừng vừa được bấm ở cửa sổ khác
        return token, code

    control.begin_action = begin_then_generation_bumps
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 20, 'y': 30})
    assert payload['errorCode'] == win_errors.HUMAN_TOOK_OVER
    assert fake.sent_events == []


def test_a_platform_error_from_input_keeps_its_code(tmp_path):
    executor, _control, fake = build(tmp_path)
    fake.accept_events = 0     # Windows nhận 0 sự kiện ⇒ INPUT_SHORT_SEND
    payload = run(executor, 'computer_use', {'action': 'click', 'x': 20, 'y': 30})
    assert payload['errorCode'] == win_errors.INPUT_SHORT_SEND


def test_input_sets_the_lease_epoch_it_ran_under(tmp_path):
    executor, control, _fake = build(tmp_path)
    control.release_to_human('bắt đầu phiên')
    control.agent_lease('agent xin lại quyền', force=True)
    payload = run(executor, 'computer_use', {'action': 'key', 'key': 'tab'})
    assert payload['leaseEpoch'] == control.snapshot()['epoch'] == 2


# -------------------------------------------------- nền tảng chưa sẵn sàng

def test_a_hook_that_cannot_be_installed_does_not_block_a_capture(tmp_path):
    # Hook là chuyện của việc PHÁT HIỆN người dùng; chụp màn hình chỉ cần lease. Thiếu hook ⇒
    # `install_hooks` fail-closed, nhưng không được kéo theo lỗi cho đường chỉ đọc.
    executor, control, _fake = build(tmp_path, platform=FakePlatform(hook_ok=False))
    ok, code = control.install_hooks()
    assert ok is False and code == win_errors.OS_PERMISSION_REQUIRED
    payload = run(executor, 'computer_screen_capture')
    assert payload.get('is_error') is not True


def test_prepare_reports_unsupported_without_a_desktop_platform(tmp_path, monkeypatch):
    executor, _control, _fake = build(tmp_path)
    monkeypatch.setattr(executor, '_desktop_platform', lambda: None)
    assert executor.prepare() == (False, host_module.UNSUPPORTED_CODE)


def test_prepare_succeeds_on_a_linux_host_with_a_desktop_platform(tmp_path):
    """`posix` không còn là lý do để `prepare()` từ chối — có X11 thì vẫn dùng được."""
    executor, _control, _fake = build(tmp_path)
    executor.platform = 'posix'
    assert executor.prepare() == (True, '')


def test_the_lease_file_lives_in_the_profile_directory(tmp_path):
    executor, control, _fake = build(tmp_path)
    assert control.lease.path == tmp_path / 'profile' / dc.LEASE_FILENAME
    run(executor, 'computer_use', {'action': 'key', 'key': 'tab'})
    assert control.snapshot()['holder'] == dc.HOLDER_AGENT
    # Chưa từng có ai tranh quyền thì chưa cần ghi tệp: thiếu tệp = agent giữ quyền.
    assert not control.lease.path.exists()
    control.release_to_human('người dùng quay lại')
    raw = json.loads(control.lease.path.read_text(encoding='utf-8'))
    assert raw['holder'] == dc.HOLDER_HUMAN
    assert raw['epoch'] == control.snapshot()['epoch'] == 1
