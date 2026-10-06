"""Nhãn `legacy_path` là dấu LỊCH SỬ, không còn kèm env nào.

Bước B5 (HANDOFF §10.3) đã xoá khóa tổng `BOXFOX_REFORM` cùng nhóm công tắc thành viên (nhóm nay
rỗng vì cả bảy bề mặt đã xoá), nên nhãn này KHÔNG còn điều khiển cấu hình chạy: file khai
`pytestmark = pytest.mark.legacy_path` chỉ ghi lại rằng nội dung của nó được viết cho cấu hình
TRƯỚC v2 (#6599). Không còn nhánh legacy nào để bật hay tắt, nên không còn gì để pin.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        'markers',
        'legacy_path: nội dung viết cho cấu hình TRƯỚC v2 (#6599) — nhãn lịch sử, không kèm env',
    )


@pytest.fixture(autouse=True)
def searxng_autodetect_off(monkeypatch):
    """Unit test phải KÍN MẠNG: máy chạy test có thể đang có SearXNG thật ở `127.0.0.1:8888`.

    Từ v1 cải tổ web search, `search_pipeline.searxng_url()` tự dò instance cục bộ khi
    `BOXFOX_SEARXNG_URL` trống — nếu không pin, bài test nào vô tình đi qua chân SearXNG sẽ gọi ra
    dịch vụ thật của máy. Bài nào KIỂM tự dò thì tự bật tường minh trong bài đó
    (`monkeypatch.setenv('BOXFOX_SEARXNG_AUTODETECT', 'on')` + `reset_autodetect()`).
    """
    monkeypatch.setenv('BOXFOX_SEARXNG_AUTODETECT', 'off')
    try:
        from agentbox.agent_core import search_pipeline
        search_pipeline.reset_autodetect()
    except Exception:  # pragma: no cover - mô-đun chưa nhập được thì cũng chẳng có cache để xoá
        pass
    yield


#: Sáu biến khoá tìm kiếm mà `web._explicit_search_config` đọc. Máy dev có thể đang giữ một khoá
#: thật (Brave/Tavily/…): khi đó `_pipeline_applies('web')` trả False và các bài chốt "ống auto"
#: đỏ dù mã đúng. Bộ unit phải KÍN với môi trường — bài nào muốn thử khoá thì tự đặt tường minh.
SEARCH_KEY_VARS = ('BRAVE_API_KEY', 'BOXFOX_BRAVE_API_KEY', 'TAVILY_API_KEY', 'EXA_API_KEY',
                   'PARALLEL_API_KEY', 'FIRECRAWL_API_KEY')


@pytest.fixture(autouse=True)
def searxng_no_api_keys(monkeypatch):
    for name in SEARCH_KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    yield
