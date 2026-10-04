"""Khóa tổng của đợt cải tổ: `BOXFOX_REFORM`.

Chủ nhà chốt 04/10/2026: các công tắc được **bật DẦN**, từng cái một, sau khi cái trước đã có
bằng chứng chạy thật. Vì vậy khóa tổng ở đây chỉ là một tay nắm cho cả nhóm, không đổi mặc định:

- Thiếu `BOXFOX_REFORM` ⇒ giữ nguyên hành vi cũ: cả bảy công tắc thành viên TẮT.
- `BOXFOX_REFORM=on` ⇒ bật cả nhóm bằng MỘT lệnh (dùng khi đã bật dần xong và muốn chạy cả cụm).
- `BOXFOX_REFORM=off` ⇒ tắt cả nhóm bằng một lệnh (lối thoát hiểm).
- Công tắc thành viên đặt TƯỜNG MINH luôn thắng khóa tổng, nên vẫn bật dần từng cái được.

Thứ tự bật dần, cách kiểm từng công tắc và điều kiện rollback: `docs/plan/reform-execution/HANDOFF.md`.

`BOXFOX_PEER_MESH` KHÔNG thuộc nhóm này: nó là công tắc giết của mesh uỷ thác, có từ trước đợt
cải tổ, mặc định BẬT và vẫn đọc riêng ở `limits.peer_mesh_enabled`.
"""
import os

MASTER_SWITCH = 'BOXFOX_REFORM'

#: Giá trị của khóa tổng khi env trống: GIỮ NGUYÊN hành vi cũ (bật dần từng công tắc).
MASTER_DEFAULT = False

ON_VALUES = {'1', 'on', 'true', 'yes'}

#: Bảy công tắc của đợt cải tổ (H3–H8). Thứ tự này cũng là thứ tự hiện trong `runtime-info`.
MEMBERS = (
    'BOXFOX_TASK_SURFACE',
    'BOXFOX_CONTEXT_SURFACE',
    'BOXFOX_CONTROLLER_JOBS',
    'BOXFOX_USAGE_LEDGER',
    'BOXFOX_RESEARCH_GATEWAY',
    'BOXFOX_ADAPTIVE_HARNESS',
    'BOXFOX_RECOVERY_POLICY',
)


def _value(raw):
    """`True`/`False` cho một giá trị env; `None` khi env thiếu hoặc trống."""
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip().lower() in ON_VALUES


def master(value=None):
    """Khóa tổng đang có hiệu lực (mặc định `MASTER_DEFAULT` khi env trống)."""
    raw = os.environ.get(MASTER_SWITCH) if value is None else value
    resolved = _value(raw)
    return MASTER_DEFAULT if resolved is None else resolved


def member_switch(name):
    """Công tắc thành viên: đặt tường minh > khóa tổng > `MASTER_DEFAULT`."""
    explicit = _value(os.environ.get(name))
    if explicit is not None:
        return explicit
    return master()


def source(name):
    """Nguồn của giá trị đang có hiệu lực: `explicit`, `master` hay `default`."""
    if _value(os.environ.get(name)) is not None:
        return 'explicit'
    if _value(os.environ.get(MASTER_SWITCH)) is not None:
        return 'master'
    return 'default'


def snapshot():
    """Khối `switches` cho `/api/agent/runtime-info`: nhìn một chỗ biết đang bật gì, vì đâu."""
    raw_master = _value(os.environ.get(MASTER_SWITCH))
    return {
        'master': {'name': MASTER_SWITCH, 'on': master(),
                   'source': 'explicit' if raw_master is not None else 'default'},
        'members': {name: {'on': member_switch(name), 'source': source(name)} for name in MEMBERS},
    }
