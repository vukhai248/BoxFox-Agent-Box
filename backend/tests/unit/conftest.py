"""Nhãn `legacy_path` là dấu LỊCH SỬ, không còn kèm env nào.

Bước B5 (HANDOFF §10.3) đã xoá khóa tổng `BOXFOX_REFORM` cùng nhóm công tắc thành viên (nhóm nay
rỗng vì cả bảy bề mặt đã xoá), nên nhãn này KHÔNG còn điều khiển cấu hình chạy: file khai
`pytestmark = pytest.mark.legacy_path` chỉ ghi lại rằng nội dung của nó được viết cho cấu hình
TRƯỚC v2 (#6599). Không còn nhánh legacy nào để bật hay tắt, nên không còn gì để pin.
"""


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'legacy_path: nội dung viết cho cấu hình TRƯỚC v2 (#6599) — nhãn lịch sử, không kèm env',
    )
