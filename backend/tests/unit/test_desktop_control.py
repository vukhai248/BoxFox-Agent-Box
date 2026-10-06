"""H7 — lease/epoch, phát hiện người thật, hàng rào stale, mutex, thang xác minh.

Toàn bộ chạy trên `FakePlatform` (nền tảng giả của `win_fakes.py`), nên kiểm được trên Linux. Không ca
nào chạm Windows, không ca nào ghi ra ngoài `tmp_path`.
"""
from __future__ import annotations

import json

from agentbox.agent_core import desktop_control as dc
from agentbox.sandbox.win import errors as win_errors

from win_fakes import FakePlatform, hook_event_dict


def control(tmp_path, platform=None, **kwargs):
    platform = platform if platform is not None else FakePlatform()
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    return dc.DesktopControl(profile_dir=profile, platform=platform, **kwargs), platform


def write_lease(tmp_path, data):
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    (profile / dc.LEASE_FILENAME).write_text(json.dumps(data), encoding='utf-8')
    return profile


# ------------------------------------------------------------------ lease

def test_a_missing_lease_file_lets_the_agent_hold_control(tmp_path):
    control_obj, _ = control(tmp_path)
    state = control_obj.snapshot()
    assert state['holder'] == dc.HOLDER_AGENT
    assert state['epoch'] == 0


def test_a_corrupt_lease_file_fails_closed_to_the_human(tmp_path):
    write_lease(tmp_path, {'holder': 'agent', 'epoch': 5})
    profile = tmp_path / 'profile'
    (profile / dc.LEASE_FILENAME).write_text('{ khong phai json', encoding='utf-8')
    control_obj, _ = control(tmp_path)
    state = control_obj.snapshot()
    assert state['holder'] == dc.HOLDER_HUMAN
    assert 'JSON' in state['reason']


def test_an_unknown_holder_counts_as_the_human(tmp_path):
    write_lease(tmp_path, {'holder': 'robot', 'epoch': 3})
    control_obj, _ = control(tmp_path)
    assert control_obj.snapshot()['holder'] == dc.HOLDER_HUMAN


def test_epoch_never_goes_backwards(tmp_path):
    profile = write_lease(tmp_path, {'holder': 'agent', 'epoch': 9})
    control_obj, _ = control(tmp_path)
    assert control_obj.snapshot()['epoch'] == 9
    # Tệp bị khôi phục từ backup (epoch thấp hơn) không được phép hạ epoch: hành động đã nhận từ epoch
    # 9 sẽ "hợp lệ" trở lại nếu ta chấp nhận con số cũ.
    (profile / dc.LEASE_FILENAME).write_text(json.dumps({'holder': 'agent', 'epoch': 2}), encoding='utf-8')
    assert control_obj.snapshot()['epoch'] == 9


def test_acquire_is_refused_while_the_human_holds_control(tmp_path):
    control_obj, _ = control(tmp_path)
    control_obj.release_to_human('người dùng đang gõ')
    ok, state, error = control_obj.agent_lease('agent xin quyền')
    assert ok is False
    assert state == win_errors.HUMAN_HAS_CONTROL
    assert error == ''


def test_acquire_with_force_moves_the_lease_to_the_agent(tmp_path):
    control_obj, _ = control(tmp_path)
    before = control_obj.release_to_human('người dùng đang gõ')[0]['epoch']
    ok, state, _ = control_obj.lease.acquire('nút Trả quyền cho agent', force=True)
    assert ok is True and state['holder'] == dc.HOLDER_AGENT and state['epoch'] > before


def test_release_to_human_bumps_the_epoch_even_when_the_human_already_holds_it(tmp_path):
    control_obj, _ = control(tmp_path)
    first = control_obj.release_to_human('lần một')[0]['epoch']
    second = control_obj.release_to_human('lần hai')[0]['epoch']
    assert second > first


# ------------------------------------------------------------------ hook: người thật

def test_hooks_are_refused_without_a_platform_that_supports_them(tmp_path):
    class NoHooks:
        pass

    control_obj, _ = control(tmp_path, platform=NoHooks())
    ok, code = control_obj.install_hooks()
    assert ok is False and code == win_errors.UNSUPPORTED_IN_HOST_MODE


def test_a_failed_hook_install_is_fail_closed(tmp_path):
    control_obj, platform = control(tmp_path, platform=FakePlatform(hook_ok=False))
    ok, code = control_obj.install_hooks()
    assert ok is False and code == win_errors.OS_PERMISSION_REQUIRED
    assert control_obj.hooks_installed is False


def test_injected_input_never_hands_control_back(tmp_path):
    control_obj, _ = control(tmp_path)
    assert control_obj.note_hook_event('mouse', hook_event_dict(injected=True, point=(5, 5))) is False
    assert control_obj.snapshot()['holder'] == dc.HOLDER_AGENT


def test_a_real_mouse_event_hands_control_back_to_the_human(tmp_path):
    control_obj, _ = control(tmp_path)
    before = control_obj.snapshot()
    assert control_obj.note_hook_event('mouse', hook_event_dict(injected=False, point=(5, 5))) is True
    after = control_obj.snapshot()
    assert after['holder'] == dc.HOLDER_HUMAN
    assert after['epoch'] > before['epoch']


def test_the_hook_callback_always_calls_the_next_hook(tmp_path):
    control_obj, platform = control(tmp_path)
    platform.hook_events = [hook_event_dict(injected=False, vkey=0x41)]
    ok, _ = control_obj.install_hooks()
    assert ok is True
    assert platform.keyboard_callback(0, 256, 0) == 0
    assert ('call_next_hook', (0, 256, 0)) in platform.calls


def test_a_real_escape_press_stops_everything(tmp_path):
    control_obj, _ = control(tmp_path)
    control_obj.begin_action('click')
    assert control_obj.check_escape(hook_event_dict(injected=False, vkey=0x1B)) is True
    assert control_obj.snapshot()['holder'] == dc.HOLDER_HUMAN


def test_an_injected_escape_is_ignored(tmp_path):
    control_obj, _ = control(tmp_path)
    assert control_obj.check_escape(hook_event_dict(injected=True, vkey=0x1B)) is False
    assert control_obj.snapshot()['holder'] == dc.HOLDER_AGENT


# ------------------------------------------------------------------ hook: lưới đỡ nhàn rỗi

def test_a_tick_change_while_the_agent_holds_control_hands_it_back(tmp_path):
    platform = FakePlatform(input_tick=1000)
    control_obj, _ = control(tmp_path, platform=platform)
    control_obj.poll_idle()
    platform.input_tick = 1400
    assert control_obj.poll_idle() is True
    assert control_obj.snapshot()['holder'] == dc.HOLDER_HUMAN


def test_our_own_injection_does_not_hand_control_back(tmp_path):
    platform = FakePlatform(input_tick=1000)
    control_obj, _ = control(tmp_path, platform=platform)
    control_obj.poll_idle()
    # Ta vừa tiêm input: mốc nhảy, nhưng nó là CỦA TA.
    platform.input_tick = 1400
    control_obj.note_own_input()
    assert control_obj.poll_idle() is False
    assert control_obj.snapshot()['holder'] == dc.HOLDER_AGENT


def test_an_unknown_tick_never_hands_control_back(tmp_path):
    control_obj, _ = control(tmp_path, platform=FakePlatform(input_tick=0))
    assert control_obj.poll_idle() is False
    assert control_obj.snapshot()['holder'] == dc.HOLDER_AGENT


# ------------------------------------------------------------------ mutex

def test_a_busy_mutex_refuses_the_action(tmp_path):
    control_obj, _ = control(tmp_path, platform=FakePlatform(mutex_acquired=False))
    token, code = control_obj.begin_action('click')
    assert token is None and code == win_errors.CONTROL_BUSY


def test_a_missing_mutex_api_is_busy_not_allowed(tmp_path):
    class NoMutex:
        def set_keyboard_hook(self, callback):
            return 1

        def set_mouse_hook(self, callback):
            return 2

        def last_input_tick(self):
            return 0

    control_obj, _ = control(tmp_path, platform=NoMutex())
    token, code = control_obj.begin_action('click')
    assert token is None and code == win_errors.CONTROL_BUSY


def test_an_action_takes_and_releases_the_mutex(tmp_path):
    control_obj, platform = control(tmp_path)
    token, code = control_obj.begin_action('click', {'windowId': 1})
    assert code == '' and token.mutex_held is True
    control_obj.end_action(token, effect='confirmed', verified=True, route='uia_pattern')
    assert control_obj.mutex.handle is None
    assert platform.called('release_mutex')


# ------------------------------------------------------------------ hàng rào

def test_a_fresh_token_passes_the_fence(tmp_path):
    control_obj, _ = control(tmp_path)
    token, _ = control_obj.begin_action('click')
    assert control_obj.fence(token) == ''


def test_the_fence_refuses_after_the_human_took_over(tmp_path):
    control_obj, _ = control(tmp_path)
    token, _ = control_obj.begin_action('click')
    control_obj.release_to_human('người dùng chạm chuột')
    assert control_obj.fence(token) == win_errors.HUMAN_HAS_CONTROL


def test_the_fence_refuses_a_token_from_an_older_generation(tmp_path):
    control_obj, _ = control(tmp_path)
    token, _ = control_obj.begin_action('click')
    # Huỷ khẩn cấp tăng `generation` mà (giả sử) lease vẫn ở tay agent: hành động đã nhận phải chết.
    control_obj.generation += 1
    assert control_obj.fence(token) == win_errors.HUMAN_TOOK_OVER


def test_a_missing_token_is_stale_not_allowed(tmp_path):
    control_obj, _ = control(tmp_path)
    assert control_obj.fence(None) == win_errors.HUMAN_TOOK_OVER


# ------------------------------------------------------------------ kết quả hành động

def test_a_sent_action_is_not_automatically_a_success(tmp_path):
    control_obj, _ = control(tmp_path)
    token, _ = control_obj.begin_action('click')
    result = control_obj.end_action(token, effect='unverifiable', verified=None, route='send_input')
    assert result['ok'] is True and result['effect'] == 'unverifiable'
    assert result['verified'] is None


def test_a_refused_action_reports_not_ok(tmp_path):
    control_obj, _ = control(tmp_path)
    result = control_obj.end_action(None, effect='refused', code=win_errors.HUMAN_HAS_CONTROL)
    assert result['ok'] is False and result['code'] == win_errors.HUMAN_HAS_CONTROL


def test_an_unknown_effect_is_downgraded_to_unverifiable(tmp_path):
    control_obj, _ = control(tmp_path)
    token, _ = control_obj.begin_action('click')
    assert control_obj.end_action(token, effect='chac-chan-thanh-cong')['effect'] == 'unverifiable'


def test_the_never_retry_rule(tmp_path):
    assert dc.DesktopControl.may_retry('confirmed') is True
    for effect in ('partial', 'unverifiable', 'suspected_noop'):
        assert dc.DesktopControl.may_retry(effect) is False


# ------------------------------------------------------------------ huỷ khẩn cấp

def test_emergency_stop_releases_input_and_returns_control(tmp_path):
    control_obj, platform = control(tmp_path)
    control_obj.begin_action('type')
    stopped = control_obj.emergency_stop('nút Dừng')
    assert stopped['stopped'] is True and stopped['released'] == 0
    assert control_obj.snapshot()['holder'] == dc.HOLDER_HUMAN
    assert control_obj.generation >= 1
    assert control_obj.mutex.handle is None


# ------------------------------------------------------------------ thang xác minh

def test_two_stable_samples_confirm(tmp_path):
    control_obj, _ = control(tmp_path)
    answer = control_obj.verify_state(lambda: {'text': 'Xong'}, lambda state: state['text'] == 'Xong')
    assert answer['verified'] is True and answer['effect'] == 'confirmed'
    assert len(answer['samples']) == dc.STABLE_SAMPLES


def test_a_state_that_never_matches_is_a_suspected_noop(tmp_path):
    control_obj, _ = control(tmp_path)
    answer = control_obj.verify_state(lambda: {'text': 'Cu'}, lambda state: state['text'] == 'Moi')
    assert answer['verified'] is False and answer['effect'] == 'suspected_noop'


def test_an_unreadable_state_is_unverifiable_not_success(tmp_path):
    control_obj, _ = control(tmp_path)
    answer = control_obj.verify_state(lambda: None, lambda state: None)
    assert answer['verified'] is None and answer['effect'] == 'unverifiable'


def test_a_flapping_state_is_partial(tmp_path):
    control_obj, _ = control(tmp_path)
    states = iter([{'ok': True}, {'ok': False}])
    answer = control_obj.verify_state(lambda: next(states), lambda state: state['ok'])
    assert answer['effect'] == 'partial'


# ------------------------------------------------------------------ chống lặp ảnh

def test_repeating_the_same_frame_raises_screen_unchanged(tmp_path):
    control_obj, _ = control(tmp_path)
    target = {'windowId': 7}
    first, unchanged = control_obj.screen_hash(b'khung-hinh', target, session='s1')
    assert unchanged is False
    second, unchanged = control_obj.screen_hash(b'khung-hinh', target, session='s1')
    assert unchanged is False
    third, unchanged = control_obj.screen_hash(b'khung-hinh', target, session='s1')
    assert unchanged is True
    assert len(first) == 64 and second == first


def test_a_changed_frame_resets_the_counter(tmp_path):
    control_obj, _ = control(tmp_path)
    target = {'windowId': 7}
    for _ in range(dc.SCREEN_UNCHANGED_LIMIT + 1):
        control_obj.screen_hash(b'cu', target)
    _, unchanged = control_obj.screen_hash(b'moi', target)
    assert unchanged is False


def test_a_different_target_has_its_own_counter(tmp_path):
    control_obj, _ = control(tmp_path)
    for _ in range(dc.SCREEN_UNCHANGED_LIMIT + 1):
        control_obj.screen_hash(b'x', {'windowId': 1})
    _, unchanged = control_obj.screen_hash(b'x', {'windowId': 2})
    assert unchanged is False
