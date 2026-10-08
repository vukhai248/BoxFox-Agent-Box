"""Bốn thao tác cử chỉ trong box (08/10/2026): kế hoạch lệnh, và việc NHẢ chuột khi hỏng.

Cử chỉ khác cú bấm ở chỗ chúng giữ nút chuột qua NHIỀU lệnh `xdotool` liên tiếp, nên chúng không
phải một `argv` mà là một kế hoạch `(argv, giây nghỉ sau lệnh)`. Hai thứ dễ sai được khoá ở đây:

* thứ tự lệnh (nhấn → đi → nhả, và khe hở thật ở giữa để ứng dụng phân biệt kéo với bấm);
* nhả nút khi một bước hỏng — kể cả khi CHÍNH lệnh nhả là bước hỏng. Một nút còn giữ trong box là
  mọi cú bấm sau đó thành cú kéo.

Vòng soát mã đợt cử chỉ: ba kế hoạch này chưa có bài kiểm nào, mà phần dễ sai nhất (đường hỏng) thì
lại không nhìn thấy được bằng mắt.
"""
import subprocess

import pytest

from agentbox.sandbox import worker

CURRENT_OK = b"Screen 0: minimum 32 x 32, current 1280 x 800, maximum 32768 x 32768\n"
MOUSEUP = ["xdotool", "mouseup", "1"]


@pytest.fixture(autouse=True)
def _no_sleep(tmp_path, monkeypatch):
    """Đứng thay `time.sleep` để không ca nào thật sự phải chờ."""
    monkeypatch.setenv('BOXFOX_SYSTEM_LOG_DIR', str(tmp_path))
    monkeypatch.setattr(worker.time, "sleep", lambda _seconds: None)


class FakeRun:
    """Đứng thay `subprocess.run`: ghi lại lệnh, và làm hỏng những lệnh được chỉ định."""

    def __init__(self, fail_on=None):
        self.calls = []
        self.fail_on = fail_on or (lambda argv: False)

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        if argv[:2] == ["xrandr", "--current"]:
            return subprocess.CompletedProcess(argv, 0, CURRENT_OK, b"")
        if self.fail_on(list(argv)):
            return subprocess.CompletedProcess(argv, 1, b"", b"XTestFakeButtonEvent: BadValue")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    def verbs(self):
        return [call[1] for call in self.calls if call and call[0] == "xdotool"]

    def releases(self):
        return [call for call in self.calls if call == MOUSEUP]


# ------------------------------------------------------------------ kế hoạch lệnh

def test_a_drag_plan_presses_moves_in_steps_and_releases():
    plan = worker._drag_plan({'x': 10, 'y': 20, 'toX': 110, 'toY': 20, 'steps': 4})
    argv = [entry[0] for entry in plan]
    assert argv[0] == ['xdotool', 'mousemove', '10', '20']
    assert argv[1] == ['xdotool', 'mousedown', '1']
    assert argv[-1] == MOUSEUP
    assert argv[-2] == ['xdotool', 'mousemove', '110', '20'], 'bước cuối phải tới đúng điểm đích'
    assert len(plan) == 2 + 4 + 1
    assert plan[1][1] == worker.BOX_GESTURE_SETTLE_SEC, 'phải có khe hở thật giữa nhấn và lệnh kế'


def test_a_drag_plan_clamps_the_step_count():
    plan = worker._drag_plan({'x': 0, 'y': 0, 'toX': 10, 'toY': 0, 'steps': 9999})
    moves = [entry for entry in plan if entry[0][:2] == ['xdotool', 'mousemove']]
    assert len(moves) == worker.BOX_MAX_DRAG_STEPS + 1, 'điểm đầu + trần số bước'


def test_a_hold_plan_keeps_the_button_down_for_the_asked_time():
    plan = worker._hold_plan({'x': 5, 'y': 6, 'seconds': 2.5})
    assert [entry[0] for entry in plan] == [['xdotool', 'mousemove', '5', '6'],
                                            ['xdotool', 'mousedown', '1'], MOUSEUP]
    assert plan[1][1] == 2.5, 'thời gian giữ nằm ở lệnh nhấn'


def test_a_hold_plan_clamps_the_duration_and_survives_a_bad_value():
    assert worker._hold_plan({'x': 1, 'y': 1, 'seconds': 99})[1][1] == 5.0
    assert worker._hold_plan({'x': 1, 'y': 1, 'seconds': 'lâu'})[1][1] == 1.0


def test_a_stroke_plan_walks_the_path_in_order():
    plan = worker._stroke_plan({'path': [[1, 2], [3, 4], [5, 6]]})
    assert [entry[0] for entry in plan] == [['xdotool', 'mousemove', '1', '2'],
                                            ['xdotool', 'mousedown', '1'],
                                            ['xdotool', 'mousemove', '3', '4'],
                                            ['xdotool', 'mousemove', '5', '6'], MOUSEUP]


def test_a_stroke_plan_refuses_a_path_that_is_too_short_or_too_long():
    with pytest.raises(ValueError):
        worker._stroke_plan({'path': [[1, 2]]})
    with pytest.raises(ValueError):
        worker._stroke_plan({'path': [[1, 2]] * (worker.BOX_MAX_STROKE_POINTS + 1)})
    with pytest.raises(ValueError):
        worker._stroke_plan({'path': [[1, 2], ['x', 'y']]})


def test_every_button_name_maps_to_its_x11_number_and_an_unknown_one_is_refused():
    assert worker._box_button({}) == '1'
    assert worker._box_button({'button': 'Middle'}) == '2'
    assert worker._box_button({'button': 'right'}) == '3'
    with pytest.raises(ValueError):
        # Tên sai phải bị TỪ CHỐI, không im lặng thành chuột trái (một cú kéo "nút giữa" gõ sai
        # chính tả sẽ chạy như chuột trái và không ai biết).
        worker._box_button({'button': 'midden'})


# ------------------------------------------------------------------ đường hỏng

def test_a_gesture_that_fails_in_the_middle_still_releases_the_button(monkeypatch):
    fake = FakeRun(fail_on=lambda argv: argv[:2] == ['xdotool', 'mousemove'] and argv[-2:] == ['30', '30'])
    monkeypatch.setattr(worker.subprocess, 'run', fake)
    with pytest.raises(ValueError):
        worker.execute('computer_use', {'action': 'stroke', 'path': [[10, 10], [30, 30], [50, 50]]},
                       'sess-cu-chi')
    assert fake.releases(), 'nút chuột PHẢI được nhả dù bước giữa hỏng'


def test_a_release_command_that_fails_is_sent_again(monkeypatch):
    """`xdotool mouseup` thoát khác 0 vẫn là nút còn giữ — và nó là bước CUỐI của kế hoạch.

    Bản cũ chỉ nhả lại khi `sent < len(plan)`, nên đúng ca này (lệnh nhả hỏng) không được nhả lại.
    """
    fake = FakeRun(fail_on=lambda argv: argv == MOUSEUP)
    monkeypatch.setattr(worker.subprocess, 'run', fake)
    with pytest.raises(ValueError):
        worker.execute('computer_use', {'action': 'hold', 'x': 10, 'y': 10, 'seconds': 0.1},
                       'sess-cu-chi')
    assert len(fake.releases()) == 2, 'lệnh nhả hỏng phải được gửi lại một lần nữa'


def test_a_gesture_that_works_sends_the_release_exactly_once(monkeypatch):
    fake = FakeRun()
    monkeypatch.setattr(worker.subprocess, 'run', fake)
    worker.execute('computer_use', {'action': 'drag', 'x': 10, 'y': 10, 'toX': 60, 'toY': 40,
                                    'steps': 3}, 'sess-cu-chi')
    assert len(fake.releases()) == 1
    assert fake.verbs().count('mousedown') == 1
