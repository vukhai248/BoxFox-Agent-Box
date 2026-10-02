"""W9: `record_stop` báo hỏng thì harness phải mang `is_error` ra ngoài, không im lặng coi là xong.

Trước đây box luôn trả `ok` và lấy `durationSec` theo ĐỒNG HỒ TREO TƯỜNG, nên một tệp 48 byte
không có `moov` (ffprobe: "moov atom not found") vẫn đi tiếp như một video đã lưu — đúng chữ ký
hai lần sweep W7-A3.3/W8-A4.1 (`record_stop` ok, `durationSec` 22–24 s cho bản ghi 2 s).
`capture.py` giờ trả `ok: False` + `errorCode: RECORDING_INCOMPLETE`; bài này khoá mắt nối cuối
cùng ở tầng harness: `SandboxExecutor` phải đổi nó thành `is_error`.
"""
from __future__ import annotations

import asyncio

from agentbox.sandbox.executor import SandboxExecutor

SID = 'a1b2c3d4e5f60718293a4b5c6d7e8f90'
INCOMPLETE = {'recordingId': 'rec-1', 'active': False, 'ok': False,
              'errorCode': 'RECORDING_INCOMPLETE', 'durationSec': None,
              'error': 'moov atom not found', 'verified': True, 'exitCode': -9,
              'forcedKill': True, 'sizeBytes': 48}


class BoxExecutor(SandboxExecutor):
    """Chặn ở `request`: trả đúng khuôn mà `/__box/record/stop` trả về."""

    def __init__(self, stop_payload):
        super().__init__()
        self.stop_payload = stop_payload

    async def request(self, path, body=None):
        if path == '/__box/record/start':
            return {'recordingId': 'rec-1', 'active': True}
        if path == '/__box/record/stop':
            return dict(self.stop_payload)
        return {}


def _stop(stop_payload):
    executor = BoxExecutor(stop_payload)
    asyncio.run(executor.execute('computer_screen_record', {'action': 'start'}, SID))
    return executor, asyncio.run(executor.execute('computer_screen_record', {'action': 'stop'}, SID))


def test_incomplete_recording_becomes_an_error_for_the_model():
    """Tệp không probe được: `is_error` phải bật, và lý do (mã + chẩn đoán) giữ nguyên."""
    _, result = _stop(INCOMPLETE)
    assert result['is_error'] is True
    assert result['errorCode'] == 'RECORDING_INCOMPLETE'
    assert result['error'] == 'moov atom not found'
    assert result['durationSec'] is None
    assert result['forcedKill'] is True


def test_a_healthy_recording_is_not_marked_as_error():
    """Bản ghi bình thường không được mọc thêm `is_error` (client cũ đọc khuôn cũ y nguyên)."""
    _, result = _stop({'recordingId': 'rec-1', 'active': False, 'ok': True, 'durationSec': 2.0,
                       'verified': True, 'exitCode': 255})
    assert 'is_error' not in result
    assert result['durationSec'] == 2.0


def test_stop_ownership_is_cleared_even_when_the_recording_is_broken():
    """Dù hỏng, phiên vẫn phải quên `recordingId` — nếu không, lần `start` sau bị chặn oan."""
    executor, _ = _stop(INCOMPLETE)
    assert SID not in executor.recordings
