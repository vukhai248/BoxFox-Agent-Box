"""Mặc định của bộ unit test sau v2 (#6599): công tắc BẬT, trừ khi file khai ngược lại.

Từ v2, env trống nghĩa là **cả nhóm cải tổ BẬT** (`BOXFOX_REFORM` mặc định `True`). Nhiều tệp
test được viết cho cấu hình TRƯỚC v2 (công tắc TẮT) và chốt hành vi cũ — chúng vẫn phải có bằng
chứng, vì đó là ĐƯỜNG ROLLBACK. Cách làm ở đây: file nào chốt đường cũ thì khai báo tường minh
`pytestmark = pytest.mark.legacy_path`, và fixture dưới đây pin `BOXFOX_REFORM=off` cho mọi bài
trong file đó.

Vì sao pin CẢ khóa tổng lẫn mọi thành viên còn lại: env thành viên đặt tường minh luôn thắng khóa
tổng, nên chỉ `BOXFOX_REFORM=off` là không kín — một shell đang có `BOXFOX_RESEARCH_GATEWAY=on`
(đúng cách đợt bật dần từng bước đã chạy) sẽ lọt vào "đường cũ" và bài test không còn chốt cấu
hình trước v2. Pin cả nhóm thành viên giữ phép kiểm kín, và khóa tổng `off` vẫn là lối thoát hiểm một lệnh thật
(vì fixture chỉ chạm tới file khai `legacy_path`). Bài nào cần chạy đường mới trong file legacy thì
đặt env thành viên TƯỜNG MINH sau fixture (`monkeypatch.setenv('BOXFOX_X', 'on')`).

File KHÔNG khai báo gì thì chạy đúng thứ người dùng mới nhận được (mặc định BẬT).
"""
import pytest

from agentbox.agent_core import feature_switches


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'legacy_path: chốt hành vi TRƯỚC v2 — pin `BOXFOX_REFORM=off` cho mọi bài trong file',
    )


@pytest.fixture(autouse=True)
def legacy_path_switch(request, monkeypatch):
    """File khai `legacy_path` chạy đúng cấu hình trước v2; file khác giữ mặc định hiện hành."""
    if request.node.get_closest_marker('legacy_path'):
        monkeypatch.setenv(feature_switches.MASTER_SWITCH, 'off')
        for name in feature_switches.MEMBERS:
            monkeypatch.setenv(name, 'off')
