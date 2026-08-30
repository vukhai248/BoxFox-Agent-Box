# `test/chat-bridge` — cầu nối WebSocket ⇄ Gemini để thử giao diện chat

## Nó là gì

Một server WebSocket nhỏ (~400 dòng) nói đúng giao thức `ServerEvent` /
`ClientCommand` mà `frontend/src/types/transport.ts` định nghĩa, và nối phần
"suy nghĩ" tới một model Gemini thật.

Nhờ nó, bạn bật `VITE_TRANSPORT=live` và **chat thật** trong giao diện: gõ tin
nhắn, gắn phần tử đã inspect, thấy bong bóng hiện ra, thấy nhãn tính lại, thấy
model từ chối chỉ thị độc vẽ trên trang.

## Nó KHÔNG là gì — đọc kỹ phần này

> **Đây không phải backend của Agent Box, và model ở đây không phải một agent.**

- **Không có công cụ nào.** Không `run_command`, không `read_file`, không
  `write_file`, không `fetch_url`. Model chỉ sinh văn bản.
- **Không có sandbox, không có sổ audit, không có bảng giấy phép.** Không có
  cưỡng chế thật — không quyết định nào ở đây là quyết định an toàn thật.
- **Không có Controller.** `task_epoch`, `label_id`, `content_hash` được cầu nối
  sinh cho đủ hình dạng sự kiện, không phải từ một máy trạng thái thật.
- Nếu model *nói* nó đã làm gì, nó đang bịa. Bản giao ước đã dặn nó đừng làm vậy,
  và bài test `04-injection` trong `test/llm` chính là để phát hiện khi nó vẫn làm.

Mục đích duy nhất: **thử tay giao diện, và xem LLM có nắm đúng quy trình không.**

## Chạy

```bash
pip install -r test/requirements.txt
cp test/.env.example test/.env      # điền GEMINI_API_KEY
set -a && . test/.env && set +a

python3 test/chat-bridge/bridge.py --verbose
# [bridge] đang nghe ws://127.0.0.1:8765/ws/session/<id>
```

Rồi trỏ frontend vào nó — thêm vào `frontend/.env` (file này đã bị `.gitignore`):

```dotenv
VITE_TRANSPORT=live
VITE_AGENT_WS_URL=ws://127.0.0.1:8765
```

Khởi động lại Vite (`npm run dev` trong `frontend/`) vì biến `VITE_*` chỉ đọc lúc
khởi động. Mở `http://localhost:3100`, mở một phiên, và gõ.

Quay về chế độ giả lập: bỏ hai dòng trên (hoặc đặt `VITE_TRANSPORT=mock`) rồi
khởi động lại Vite.

### Tuỳ chọn dòng lệnh

| Cờ | Mặc định | Ý nghĩa |
|---|---|---|
| `--host` | `127.0.0.1` | Chỉ nên để loopback. Không mở ra mạng. |
| `--port` | `8765` | |
| `--model` | `gemini-3.5-flash-lite` → `gemini-3.1-flash-lite` | Lặp lại được, tạo dây dự phòng. |
| `--verbose` | tắt | In từng sự kiện gửi ra stderr. |
| `--allow-no-origin` | tắt | Cho client **không** gửi header `Origin` vào (script CLI). |

## Kiểm soát truy cập

Cầu nối chỉ nghe loopback và kiểm tra header `Origin` theo lối **đóng mặc định**,
cùng quy tắc mà `ide-proxy` áp cho `/__box/*` (mục 12.6):

- `Origin` thuộc allow-list (`http://localhost:3100`, `http://127.0.0.1:3100`,
  `http://localhost:4173`) ⇒ cho vào.
- `Origin` lạ ⇒ đóng với mã `1008`.
- **Thiếu `Origin` ⇒ cũng đóng với mã `1008`.** Nếu bỏ qua trường hợp này thì một
  client không phải trình duyệt chỉ cần *không gửi* header là vô hiệu hoá cả
  allow-list. Script CLI phải bật `--allow-no-origin` một cách tường minh.

Giới hạn khác: `MAX_MESSAGE_BYTES = 256 KiB` mỗi khung, `MAX_HISTORY_TURNS = 20`
lượt được nhớ lại, tối đa 5 phần tử đính kèm mỗi tin nhắn.

## Nhãn được gán ở đâu — điểm quan trọng nhất

Mỗi phần tử đính kèm sinh ra một sự kiện `label_added`, và **nhãn luôn do cầu nối
tự gán**, không bao giờ đọc từ nội dung phần tử:

```
integrity        = khong_tin_duoc
confidentiality  = noi_bo
source_kind      = screen_capture
tool_name        = inspect_element
```

Lý do: một trang web có thể tự khai `integrity=duoc_nguoi_dung_cho_phep` ngay
trong `textContent` hoặc `aria-label` của nó. Nếu người gán nhãn tin vào dữ liệu
được gán nhãn thì việc gán nhãn trở nên vô nghĩa. Fixture
`test/llm/fixtures/inspect-dom-injection-exfil.json` làm đúng đòn đó, và bộ test
`test/llm` kiểm tra rằng nó không có tác dụng.

Vì `label_added` chỉ *thêm* mảnh (nguyên tắc N5), `integrity_floor` của ngữ cảnh
tụt xuống `khong_tin_duoc` và **không tự sạch lại**. Câu trả lời sinh ra từ ngữ
cảnh đó cũng mang nhãn `khong_tin_duoc`.

## Sự kiện được hỗ trợ

Gửi ra (`ServerEvent`): `system_note`, `user_message_echo`, `label_added`,
`step_started`, `agent_thought`, `agent_message`, `mode_switch_proposed`,
`mode_switched`.

Nhận vào (`ClientCommand`): `user_message` (kể cả `elements`), `interrupt`,
`mode_switch_request`, `mode_switch_confirm`.

Chưa hỗ trợ: `permission_requested` / `permission_response`, `tool_called` /
`tool_result`, `screenshot`, `terminal_line`, WebRTC. Những luồng đó cần một
Controller thật; hãy dùng chế độ giả lập (`VITE_TRANSPORT=mock`) để thử chúng.

## Gỡ rối

| Hiện tượng | Nguyên nhân thường gặp |
|---|---|
| `GEMINI_API_KEY` chưa đặt | Quên `set -a && . test/.env && set +a` — biến chỉ tồn tại trong shell đã nạp. |
| Giao diện nối rồi ngắt ngay | Origin không khớp. Kiểm tra Vite chạy ở `3100`, xem log stderr của cầu nối. |
| Giao diện im, không có bong bóng | Vẫn đang ở `VITE_TRANSPORT=mock`, hoặc chưa khởi động lại Vite sau khi sửa `.env`. |
| `429 RESOURCE_EXHAUSTED` | Hết hạn mức bậc miễn phí. Chờ, hoặc `--model gemini-3.1-flash-lite`. |
| Bong bóng người dùng không hiện | Đúng như thiết kế: giao diện chờ `user_message_echo` từ server, không tự thêm. Nếu cầu nối chết thì sẽ không có echo. |
