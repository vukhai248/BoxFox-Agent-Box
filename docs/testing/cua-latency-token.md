# Đo latency và token của CUA (Linux/X11)

Công cụ: `backend/tools/cua_bench.py`. Đây **không phải bài kiểm tự động** — nó cần một X server
thật (`DISPLAY=:1` trên máy này) và một cửa sổ để gõ vào. Mục đích: trả lời hai câu hỏi người dùng
đặt ra ngày 08/10/2026 — *CUA hiện tại có tối ưu không, hay vẫn chậm?* và *một việc CUA tốn bao
nhiêu token, mất bao lâu?*

## Chạy

```bash
cd backend
# 1) đo, ghi ra hai tệp (primitives và product là hai lượt khác nhau)
DISPLAY=:1 .venv/bin/python -u tools/cua_bench.py primitives --times 5 --json /var/tmp/bench-primitives.json
DISPLAY=:1 .venv/bin/python -u tools/cua_bench.py product    --times 3 --json /var/tmp/bench-product.json
DISPLAY=:1 .venv/bin/python -u tools/cua_bench.py case       --times 3 --json /var/tmp/bench-case.json
# 2) chốt trần: gộp ĐỦ các tệp, thiếu tệp nào là "KHÔNG ĐO ĐƯỢC" tệp đó
DISPLAY=:1 .venv/bin/python -u tools/cua_bench.py budget --baseline /var/tmp/bench-primitives.json \
                                                         --baseline /var/tmp/bench-product.json
```

| Lệnh | Đo gì |
| --- | --- |
| `primitives` | Tầng nền tảng: `get_foreground_window`, `get_cursor_pos`, `get_window_rect`, `window_from_point`, `window_properties`, `capture_window`, `capture_screen`, `press_key`, `click`, `type_text` (đúng 200 ký tự). Kèm **số tiến trình con** mỗi lần gọi. |
| `product` | Đúng đường sản phẩm (`HostExecutor.execute`): `key`, `click`, `type_text` qua `computer_use`, và `screenshot` qua `computer_screen_capture`. Kèm **token chữ** của payload JSON, và **token thị giác** cho ảnh (`computer_use` KHÔNG nhận `action='screenshot'` — đo ở đó là đo đường báo lỗi `UNSUPPORTED_ACTION`). |
| `case` | Latency đầu-cuối một việc CUA: mở `xfce4-terminal` → chụp cửa sổ → gõ lệnh → `Enter`. Tách riêng thời gian chờ hệ điều hành mở cửa sổ. |
| `budget` | So một lần chạy với trần trong `DEFAULT_BUDGET_MS`; in `VƯỢT TRẦN: …` và **thoát mã 1** khi vượt. Duyệt theo **danh sách trần**, nên thiếu số đo (hoặc số đo lỗi) cũng là VƯỢT và in `KHÔNG ĐO ĐƯỢC`. Dùng được như chốt chặn hồi quy. |

Tuỳ chọn: `--times N` (số lần lặp), `--window <tiêu đề>` (chọn cửa sổ đích), `--payload <văn bản>`
(văn bản cho `type_text`; harness lặp cho đủ 200 ký tự nên nhãn `*_200` luôn đúng kích thước),
`--json <tệp>`, `--list-budget`. `budget` nhận `--baseline` **lặp lại được** (primitives và product ghi hai tệp riêng; chốt so với cả danh sách trần nên phải gộp đủ).

`primitives` và `product` tự đưa cửa sổ đích lên trước (`set_foreground_window`) vì mọi thao tác
gõ/bấm đều bị chốt "cửa sổ đích phải đang có tiêu điểm". Phép đo nào không đặt được tiêu điểm sẽ
hiện `KHÔNG ĐO ĐƯỢC: …` và được ghi vào JSON là `{"n": 0, "error": …}` — không làm hỏng cả lượt đo.

## Cách quy đổi token

Hai hằng số ở đầu `cua_bench.py`, cả hai đều là **ước lượng**, không phải số đo từ API:

- `CHARS_PER_TOKEN = 4` — token chữ theo tỉ lệ quen dùng 4 ký tự/token.
- `PIXELS_PER_VISION_TOKEN = 750` — token ảnh theo công thức quen dùng của các API thị giác (một
  token cho mỗi ~750 điểm ảnh).

Vì sao vẫn hữu ích dù là ước lượng: phần đắt nhất của một thao tác CUA là **ảnh**, và ảnh lớn gấp
đôi thì token ảnh cũng gấp đôi — tỉ lệ đó đúng bất kể hằng số chính xác là bao nhiêu. Con số tuyệt
đối chỉ để so sánh giữa các phương án (ví dụ: chụp cửa sổ so với chụp cả màn hình).

## Số đo ngày 08/10/2026 (XFCE 1920×1080, p50, máy ảo)

`primitives` (cửa sổ terminal 971×395):

| Phép đo | Trước đợt vá | Sau đợt vá |
| --- | --- | --- |
| `get_foreground_window` | 1,2 ms | 1,2 ms |
| `get_cursor_pos` | 2,9 ms | 2,7 ms |
| `get_window_rect` | 1,0 ms (1 tiến trình) | **0,0 ms (0 tiến trình)** |
| `window_from_point` | 7,1 ms (7 tiến trình) | **1,3 ms (1 tiến trình)** |
| `window_properties` | 2,0 ms | 2,0 ms |
| `capture_window` | 67 ms (42 tiến trình) | **41 ms (14 tiến trình)** |
| `capture_screen` | 48 ms | 50 ms |
| `press_key` | 152 ms | **26 ms** |
| `click` | 252 ms | **23 ms** |
| `type_text` (200 ký tự) | 1 487 ms | 1 330 ms |

`product` (qua `HostExecutor`): `key` 57 ms (31 tiến trình con), `click` 65 ms (35),
`type_text` 200 ký tự 1 359 ms (47), `screenshot` (`computer_screen_capture`, 1920×1080) **128 ms**
(21 tiến trình con). Token chữ mỗi payload 95–103 token; một ảnh cửa sổ 1 015×483 ≈ **653 token thị
giác**, một ảnh cả màn hình 1920×1080 ≈ **2 764 token thị giác**.

Đừng đếm token của payload ảnh theo ký tự base64: một ảnh 1,4 MP thành ~27 000 "token chữ" — con số
vô nghĩa. Với ảnh, dùng `điểm ảnh / 750`.

`case` (giao việc → xong, 3 lượt): **395–408 ms**, trong đó chờ hệ điều hành mở cửa sổ 154–157 ms và
ba thao tác CUA 220–235 ms (chụp 18–27 ms, gõ 155 ms, `Enter` 47–54 ms).

### Bốn thao tác cử chỉ (thêm 08/10/2026)

Đo qua đường sản phẩm trên cửa sổ Chrome 1920×1039, 3 lượt mỗi phép đo:

| Thao tác | p50 | p95 | Tiến trình con | Token payload |
| --- | --- | --- | --- | --- |
| `scroll` 5 bước | 115,0 ms | 116,2 ms | 35 | 117 |
| `drag` 12 bước | 251,1 ms | 255,1 ms | 51 | 123 |
| `hold` 0,5 giây | 567,9 ms | 568,4 ms | 45 | 116 |
| `stroke` 61 điểm | 709,2 ms | 711,4 ms | 105 | 124 |

Đọc bảng này theo hai ý:

1. **Cử chỉ không đắt hơn một cú bấm là bao.** `scroll` 115 ms so với `click` 67 ms; phần tăng thêm
   là một lệnh `xdotool click --repeat` (một tiến trình con cho cả loạt bước) cộng việc di chuyển con
   trỏ vào đúng cửa sổ trước. `hold` gồm **cả thời gian giữ** — 0,5 giây giữ thì 568 ms là hợp lý,
   không phải chậm.
2. **Nét vẽ tốn ~11,6 ms mỗi điểm** (`stroke` 61 điểm = 709 ms). Đây là chỗ đắt nhất trong bốn thao
   tác, và cũng là chỗ dễ tối ưu nhất: mỗi điểm hiện là một lệnh `mousemove` riêng (61 điểm = 61
   tiến trình con, xem cột "tiến trình con" = 105). Gộp nhiều điểm vào một lệnh `xdotool` (nó nhận
   cả dãy lệnh trong một tiến trình) sẽ cắt phần lớn con số này; giữ nguyên nhịp `STROKE_STEP_SEC`
   để ứng dụng kịp vẽ.

Trần trong `cua_bench.py` (`DEFAULT_BUDGET_MS`) đặt theo bảng trên: `scroll_5` 400 ms, `drag_12`
700 ms, `hold_0_5` 1 000 ms (thời gian giữ + 500 ms), `stroke_61` 1 600 ms. Lượt chốt trần ngày
08/10/2026 (gộp ba tệp đo) báo **ĐẠT**, mã thoát 0.

## Chỗ còn chậm (tính đến 08/10/2026)

0. **Mỗi cú bấm tốn thêm một `xwininfo`** để đọc lại hình học cửa sổ đích ngay trước khi soi điểm
   (`check_point_ownership` gọi `get_window_rect(..., fresh=True)`). Bộ đệm 0,5 s rất rẻ, nhưng nếu
   người dùng vừa di chuyển cửa sổ thì hình học cũ vẫn chứa điểm bấm và chốt sẽ cho qua một cú bấm
   rơi vào cửa sổ khác — đổi một tiến trình con lấy điều đó là rẻ.

1. **Gõ chữ là phần đắt nhất**: ~6,6 ms mỗi ký tự, do `TYPE_DELAY_MS = 12` trong
   `sandbox/x11/input.py`. Một đoạn 200 ký tự tốn 1,33 s — chiếm gần hết thời gian của một việc CUA
   thật. Đây là đánh đổi có chủ ý: giảm `--delay` xuống 0 đo được 0,04 s cho 200 ký tự, nhưng
   `--delay 0` từng làm mất ký tự ở các ứng dụng chậm, nên phải đo lại độ trung thực trước khi hạ.
2. **Mỗi thao tác sản phẩm cộng thêm ~30 ms** so với tầng nền tảng (`key` 26 → 53 ms,
   `click` 23 → 54 ms): phần lớn là `restore_context` (hai vòng gọi thêm) và việc dựng payload.
3. **Mỗi thao tác X11 là vài tiến trình con** (`xdotool`, `xwininfo`, `xprop`, `import`). Đã giảm
   mạnh nhờ đệm hình học 0,5 s và ghép hộp thoại, nhưng `import` vẫn là 14 tiến trình mỗi ảnh.
4. **Token**: một ảnh chụp cửa sổ ≈ 653 token ảnh — gấp ~7 lần phần chữ của cùng một thao tác. Muốn
   tiết kiệm token thì phải giảm kích thước ảnh hoặc tần suất chụp, không phải rút gọn JSON.

Người dùng đã ghi nhận (08/10/2026) rằng model đã tự báo token vào/ra, và **đo token có thể hoãn
lại**; việc cần đo trước là **latency từ lúc giao một việc CUA đến lúc hoàn tất** — đó chính là
`case`. Phần token ở đây là giàn giáo để so sánh phương án, không phải hoá đơn.

## Một lượt trọn vẹn — `turn_latency.py` và `cua_bench turn` (thêm 08/10/2026)

`case` ở trên đo một việc CUA do chính công cụ giao. Câu hỏi *"thời gian CUA từ lúc user ra đề nghị
đến khi xong task và trả lời user"* cần con số của **một lượt thật**, nên có thêm một reader đọc sổ
`events` của harness (nguồn chân lý — không cần X server):

```bash
cd backend
.venv/bin/python tools/turn_latency.py --db ~/BoxFox/harness/sessions.sqlite --json /var/tmp/turn-latency.json
.venv/bin/python tools/cua_bench.py turn  --db ~/BoxFox/harness/sessions.sqlite --json /var/tmp/turn.json   # cùng số
```

Reader chỉ **đọc** store (`sqlite3` mở `mode=ro`). Payload `turn_start`/`turn_end` **không** mang mốc
thời gian — mọi ms đọc từ cột `created`, trừ `deadlineUsedMs`. Vì thế `wallMs` là số chính cho "chủ
nhà chờ bao lâu" (thời gian tường thật, gồm cả phần trước `_run`), còn `deadlineUsedMs` là số chính
cho "lượt đã tiêu bao nhiêu ngân sách"; lệch quá 1 000 ms thì in dòng `LỆCH` và **vẫn** lấy `wallMs`
làm số chính — không "sửa" số nào.

Một lượt được chia thành các phần **cộng đúng bằng tổng**:
`wall = model + vòng lặp + tool + thân harness + ngoài lượt`. Hai nhãn không được đọc sai:
**`model + vòng lặp`** không phải thời gian model thuần (nó gồm dựng request, kiểm cổng bằng chứng,
thử lại — muốn tách thật phải nối nhật ký router vào phiên, K5 chưa làm), và **`chờ bạn`** (`waitedMs`)
là số báo kèm, không trừ vào phần nào vì nó chồng lấn với `model + vòng lặp`.

### Số đo trên máy này (08/10/2026)

```text
$ cd backend && .venv/bin/python tools/turn_latency.py --db /home/ubuntu/BoxFox/harness/sessions.sqlite
store: /home/ubuntu/BoxFox/harness/sessions.sqlite
1 phiên · 1 lượt · 0 ca CUA
chưa đo được lượt CUA nào

lượt 1 · phiên dac7c517 · Summarize the quarterly report and flag any risks · 6b373920
  wall 145.7 ms (đề nghị → trả lời; đọc từ cột `created` — số chính) · đóng sổ 153.8 ms
  harness 142.0 ms (deadlineUsedMs — số ngân sách) · 1 bước · 0 tool · status error · finishReason —
  chia lượt: model+vòng lặp 110.9 ms + tool 0.0 ms + thân harness 31.1 ms = harness 142.0 ms; + ngoài lượt 3.7 ms = wall 145.7 ms
  chờ bạn: —
```

**Chưa đo được lượt CUA nào trên máy này**: store chỉ có đúng một lượt và lượt ấy **hỏng ở tầng định
tuyến** (`turn_end.status: 'error'`, `toolsRun: 0`, `recovery_decision.code: UPSTREAM_HTTP_503`,
`turn_start.modelId: null`) trước khi chạm tool nào (`tool_start` = 0 hàng trong cả store). Vì thế con
số "một lượt CUA từ đề nghị đến trả lời" **chưa tồn tại**; mọi số trong bảng cử chỉ ở trên là **từng
thao tác**, không phải một lượt. Reader in thẳng `chưa đo được lượt CUA nào` thay vì suy diễn — hành vi
đó được ghim bằng test (`tests/unit/test_turn_latency.py`).

Alias `cua_bench turn` ghi cùng số vào khối `turn` của báo cáo JSON: chạy hai lệnh trên rồi so hai tệp
thì `db`/`sessions`/`turns`/`cases`/`notes` phải giống nhau (khác duy nhất `generatedAt` — hai lần chạy
khác thời điểm). `--max-total-ms N` là cổng tuỳ chọn: lượt nào vượt trần thì in `VƯỢT TRẦN` và thoát
mã 1. Trần lượt **không** nằm trong `DEFAULT_BUDGET_MS`: `check_budget()` duyệt theo danh sách trần nên
một khoá mới ở đó sẽ làm mọi lần `budget --baseline` cũ báo `KHÔNG ĐO ĐƯỢC` cho lượt.
