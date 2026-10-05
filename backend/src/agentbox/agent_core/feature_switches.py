"""Khóa tổng của đợt cải tổ: `BOXFOX_REFORM`.

Chủ nhà chốt 05/10/2026 (quyết định #6599, v2): đợt bật dần đã xong tám bước, nên **mặc định
là BẬT**. Khóa tổng trở thành tay nắm để TẮT cả nhóm khi cần, không còn là điều kiện để bật:

- Thiếu `BOXFOX_REFORM` ⇒ cả bảy công tắc thành viên **BẬT** (mặc định mới, từ v2).
- `BOXFOX_REFORM=off` ⇒ tắt cả nhóm bằng MỘT lệnh (lối thoát hiểm một lệnh).
- `BOXFOX_REFORM=on` ⇒ giữ nguyên nghĩa cũ: nói rõ "bật cả nhóm" mà không cần env thành viên.
- Công tắc thành viên đặt TƯỜNG MINH luôn thắng khóa tổng: `BOXFOX_TASK_SURFACE=off` tắt riêng
  một bề mặt để điều tra sự cố trong khi phần còn lại vẫn chạy.

Lối thoát hiểm này KHÔNG bị xoá ở v2: nó là cách tổ chức để một agent sau quyết định giữ hay
xoá nhánh legacy, và quyết định đó cần bằng chứng chạy thật dài ngày trước.

Cách tổ chức công tắc, cách kiểm từng công tắc và điều kiện rollback:
`docs/plan/reform-execution/HANDOFF.md`.

`BOXFOX_PEER_MESH` KHÔNG thuộc nhóm này: nó là công tắc giết của mesh uỷ thác, có từ trước đợt
cải tổ, mặc định BẬT và vẫn đọc riêng ở `limits.peer_mesh_enabled`.
"""
import os

MASTER_SWITCH = 'BOXFOX_REFORM'

#: Giá trị của khóa tổng khi env trống: BẬT (v2, quyết định #6599). Tắt bằng
#: `BOXFOX_REFORM=off` — lối thoát hiểm giữ nguyên.
MASTER_DEFAULT = True

ON_VALUES = {'1', 'on', 'true', 'yes'}

#: Các công tắc của đợt cải tổ còn lại sau checkpoint xoá dần (H3–H8). Thứ tự này cũng là
#: thứ tự hiện trong `runtime-info`.
MEMBERS = (
    'BOXFOX_TASK_SURFACE',
    'BOXFOX_CONTROLLER_JOBS',
    'BOXFOX_USAGE_LEDGER',
    'BOXFOX_RESEARCH_GATEWAY',
    'BOXFOX_ADAPTIVE_HARNESS',
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
