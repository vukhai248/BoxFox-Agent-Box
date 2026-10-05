"""Cắt env công tắc cho những bài chốt MẶC ĐỊNH (bật dần bước 8, 2026-10-05).

Bước "bật dần" chạy cả bộ unit với công tắc BẬT — kể cả khóa tổng `BOXFOX_REFORM=on`.
Bài nào khẳng định hành vi MẶC ĐỊNH (công tắc TẮT) thì phải cắt CẢ env thành viên LẪN khóa
tổng; chỉ cắt env thành viên là còn hở: khóa tổng vẫn quyết định giá trị hiệu lực.

Dùng: `isolate_default(monkeypatch, task_surface.SWITCH)`.
"""
from agentbox.agent_core import feature_switches


def isolate_default(monkeypatch, *switches):
    """Cắt mọi nguồn env của các công tắc đã nêu, để giá trị hiệu lực là MẶC ĐỊNH."""
    for name in switches:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv(feature_switches.MASTER_SWITCH, raising=False)
