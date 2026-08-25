# Backend — `agentbox`

FastAPI + Python. Đây là toàn bộ phần chạy trên máy chủ: agent, tầng bảo mật, sandbox, và API cho giao diện.

Tài liệu kiến trúc: [`../docs/plan/agent-box-plan.md`](../docs/plan/agent-box-plan.md).

## Bản đồ thư mục ↔ tầng kiến trúc

Bảy tầng ở mục 2.1 của bản kế hoạch được chia thành các package dưới đây. **Thứ tự trong bảng là thứ tự một hành động đi qua hệ thống.**

| Package | Tầng | Phần trong kế hoạch | Nhét file gì vào đây |
|---|---|---|---|
| `api/` | 1 — Giao diện | Phần XII | FastAPI routes, WebSocket handler, schema request/response, kiểm `Origin` |
| `controller/` | 2 — Controller | Phần V, mục 5.2.1 | **Bảy thành phần con, mỗi cái một file:** `task_manager.py`, `mode_manager.py`, `permission_broker.py`, `tool_gatekeeper.py`, `budget_keeper.py`, `checkpoint_manager.py`, `event_bus.py`, cộng `controller.py` gộp lại |
| `agent_core/` | 3 — Agent Core | Phần V | Vòng lặp ReAct (`loop.py`), hai chế độ Plan/Act (`modes.py`), prompt hệ thống (`prompts.py`), parse + kiểm schema output LLM (`schema.py`) |
| `memory/` | 3 — Memory & Context | Phần X | `ContextChunk`/`Context` (mục 10.2), nén ngữ cảnh (mục 10.4), cắt kết quả tool (mục 10.5), interface `MemoryBackend` |
| `router/` | 3 — Model Router | Phần XI | Định tuyến theo `Confidentiality` (mục 11.2), tích hợp LiteLLM và Ollama |
| `security/` | **4 — Cổng kiểm soát** | **Phần IX** | `policy_engine.py`, `label_store.py`, `lease_store.py`, `secret_manager.py`, `audit_ledger.py`, và `labels.py` cho ba trục nhãn ở mục 9.3 |
| `tools/` | 5 — Tool & Skill | Phần VI | Tám tool ở bảng 6.2, mỗi tool một file, cộng `spec.py` cho `ToolSpec` |
| `sandbox/` | 6 — Sandbox | Phần VII | Docker runtime, sáu quy tắc container ở mục 7.4, quản lý mount theo từng lần gọi |
| `computer_use/` | 6 — Computer Use | Phần VIII | `ComputerAction` (mục 8.4), hai chế độ `a11y`/`vision`, gán nhãn M1 cho ảnh màn hình (mục 8.5), cổng chặn ở mục 8.7 |
| `config/` | — | Mục 11.4 | Đọc `~/.agentbox/config.toml`. **File cấu hình nằm NGOÀI workspace của agent** — đây là nơi giữ trần độ rộng phạm vi kế hoạch và các danh sách mà chỉ thị độc không được sửa |

## Hai luật không được vi phạm khi viết code ở đây

1. **`controller/` và `security/` không bao giờ gọi LLM.** Nếu một file trong hai package này `import` một client model thì thiết kế đã sai. Lý do ở nguyên tắc **N2** mục 2.2: LLM không phải thành phần được tin.
2. **Mọi hành động ra ngoài đi qua đúng một cổng.** Không có đường nào từ `agent_core/` gọi thẳng vào `sandbox/` mà không qua `security/policy_engine`. Nguyên tắc **N1**.

## Kiểm thử

| Thư mục | Nội dung |
|---|---|
| `tests/unit/` | Test từng thành phần. Ưu tiên `security/` — đây là đường găng của cả đồ án |
| `tests/integration/` | Test một hành động đi hết bảy tầng. Ca quan trọng nhất là **phản ví dụ ở mục 9.5.2**: giấy phép cấp lúc ngữ cảnh sạch không được dùng sau khi ngữ cảnh bẩn |

Bộ ca tấn công và bộ ca lành tính **không** nằm ở đây — chúng ở [`../benchmark/`](../benchmark/) vì chúng là thí nghiệm có số liệu, không phải test pass/fail.
