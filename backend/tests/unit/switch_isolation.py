"""Hai helper cắt env công tắc, cho hai loại bài chốt khác nhau.

Từ v2 (quyết định #6599) mặc định đã đổi sang BẬT, nên "chốt mặc định" và "chốt hành vi cũ"
không còn là một:

- `isolate_default(...)` — cắt CẢ env thành viên LẪN khóa tổng `BOXFOX_REFORM`, để giá trị hiệu
  lực là MẶC ĐỊNH (từ v2: BẬT). Dùng cho bài chốt hành vi mặc định mới.
- `isolate_off(...)` — đặt TƯỜNG MINH từng công tắc nêu tên = `off`, để giá trị hiệu lực là TẮT
  (hành vi cũ). Dùng cho bài chốt đường legacy; nếu chỉ cắt env thì mặc định mới (BẬT) chen vào.

Cắt cả hai nguồn là điều kiện bắt buộc ở cả hai chiều: chỉ cắt env thành viên là còn hở (khóa
tổng quyết định), chỉ cắt khóa tổng cũng còn hở (env ambient của vòng chạy nhóm quyết định).
"""
from agentbox.agent_core import feature_switches


def isolate_default(monkeypatch, *switches):
    """Cắt mọi nguồn env của các công tắc đã nêu, để giá trị hiệu lực là MẶC ĐỊNH (BẬT từ v2)."""
    for name in switches:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(feature_switches.MASTER_SWITCH, raising=False)


def isolate_off(monkeypatch, *switches):
    """Chốt hành vi CŨ (công tắc TẮT) từ v2 — mặc định đã đổi sang BẬT.

    Đặt TƯỜNG MINH từng công tắc nêu tên = `off` (giá trị tường minh luôn thắng khóa tổng),
    và cắt `BOXFOX_REFORM` để env ambient của vòng chạy nhóm không chen vào.
    """
    monkeypatch.delenv(feature_switches.MASTER_SWITCH, raising=False)
    for name in switches:
        monkeypatch.setenv(name, 'off')
