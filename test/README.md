# `test/` — bộ kiểm thử cấp repo

Thư mục này chứa các bài test **cắt ngang hệ thống**: những thứ không thuộc riêng
frontend hay riêng box, mà kiểm tra *giao ước giữa con người, LLM và sandbox*.

```
test/
├── README.md                  ← bạn đang đọc file này
├── requirements.txt           ← google-genai, websockets
├── .env.example               ← khuôn mẫu để tạo test/.env (chứa GEMINI_API_KEY)
│
├── llm/                       ← LLM có hiểu ĐÚNG quy trình BoxFox không?
│   ├── run_tests.py           ← điểm chạy chính (CLI)
│   ├── generate_basic.py      ← snippet gọi Gemini tối giản, để thử tay
│   ├── _harness/              ← khung chạy: client, nạp case, chấm điểm, báo cáo
│   ├── contract/              ← BẢN GIAO ƯỚC đưa cho model (system instruction)
│   ├── fixtures/              ← dữ liệu JSON giả lập kết quả inspect-element
│   ├── cases/                 ← các ca test, chia theo 6 nhóm (xem llm/README.md)
│   └── reports/               ← báo cáo sinh ra khi chạy (đã .gitignore)
│
└── chat-bridge/               ← cầu nối WebSocket ⇄ Gemini để test giao diện chat
    ├── bridge.py
    └── README.md
```

## Hai mục đích khác nhau, đừng lẫn

| Thư mục | Trả lời câu hỏi | Cách chạy | Có tự động không |
|---|---|---|---|
| `llm/` | *LLM có nắm đúng quy trình, nhãn, và có chống được tiêm nhiễm không?* | `python3 test/llm/run_tests.py` | Có — chấm điểm bằng luật tất định, ra mã thoát 0/1 |
| `chat-bridge/` | *Giao diện chat có chạy thật với một LLM thật không?* | `python3 test/chat-bridge/bridge.py` rồi mở app | Không — dùng để **thử tay** |

`chat-bridge` **không phải backend, không phải agent**: nó không có công cụ nào,
không đọc/ghi file, không chạy lệnh. Nó chỉ nói chuyện và dán nhãn. Xem
`chat-bridge/README.md`.

## Cài đặt một lần

```bash
pip install -r test/requirements.txt      # xem ghi chú trong file nếu pip từ chối
cp test/.env.example test/.env            # rồi điền GEMINI_API_KEY vào test/.env
set -a && . test/.env && set +a           # nạp biến vào shell hiện tại
```

`test/.env` đã bị `.gitignore` chặn (`.env` và `.env.*`). **Không bao giờ** dán
API key trực tiếp vào bất kỳ file nào trong repo.

Kiểm tra nhanh không cần key:

```bash
python3 test/llm/run_tests.py --dry-run    # xác thực toàn bộ case/contract/fixture
```

## Vì sao các test cũ KHÔNG được dọn vào đây

Bạn yêu cầu "các bài test cho vào thư mục test riêng". Chúng tôi làm đúng điều đó
cho **các bài test mới**, nhưng **cố ý giữ nguyên vị trí** hai nhóm test đã có:

| Nhóm test đã có | Ở đâu | Vì sao giữ nguyên |
|---|---|---|
| Vitest của frontend (33 file, 251 test) | `frontend/src/**/*.test.ts(x)` — nằm cạnh file nó kiểm tra | Vitest quét theo `include` trong `vite.config.ts` và các test import theo đường dẫn tương đối (`./fit`, `../store/agentStore`). Dời ra `test/` sẽ làm vỡ cả việc quét lẫn hàng trăm import, mà không thu được gì. Đặt test cạnh mã nguồn cũng là quy ước chuẩn của Vitest. |
| Unittest của box (Python) | `deploy/docker/tests/*.py` | `python3 -m unittest discover -s tests` chạy *bên trong* thư mục `deploy/docker`, và các test này `import capture`, `import inspect_element` — tức là chúng phải nằm cạnh mã box. Quan trọng hơn: `deploy/docker/` là thứ được `COPY` vào ảnh Docker, nên test đi cùng ảnh. |

Nói ngắn: `test/` là nơi cho **test cắt ngang** (LLM, giao ước, cầu nối). Test
đơn vị của một thành phần vẫn sống cạnh thành phần đó. Đây là cách chia phổ biến
và giữ được cả ba lệnh `npm run test`, `unittest discover`, và `run_tests.py`
đều chạy độc lập.

## Toàn bộ lệnh kiểm thử của repo

```bash
# 1. Frontend — kiểu, lint, unit test
cd frontend && npm run typecheck && npm run lint && npm run test

# 2. Box — unit test Python
cd deploy/docker && python3 -m unittest discover -s tests -v

# 3. Box — smoke test trong container (cần Docker)
cd deploy/docker && bash smoke-test.sh

# 4. LLM — bộ test quy trình (cần GEMINI_API_KEY)
python3 test/llm/run_tests.py
```
