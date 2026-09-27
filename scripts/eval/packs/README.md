# Gói nguồn cho đo chất lượng (§8.3)

Gói nguồn là bản chụp cục bộ của những trang mà một tình huống được phép dùng. Khi
`BOXFOX_WEB_PACK` trỏ tới một gói, `web_search`/`web_fetch` đọc từ gói và **không gọi
mạng**, nên phép so sánh giữa các cấu hình chỉ còn mô hình là nguồn nhiễu (#6079).

Định dạng này là **hợp đồng P0 §3**. B3 (`scripts/eval/**`) sinh ra; B1
(`backend/src/agentbox/agent_core/source_pack.py`) đọc vào.

```
<pack>/pack.json          {"scenarioId","builtAt","sources":[{"url","title","date","kind",
                           "accessLevel","file"}]}
<pack>/pages/<file>       thân trang: .html | .txt | .json | .pdf
<pack>/search_index.jsonl mỗi dòng {"query","urls":[{"url","rank","snippet"}]}
<pack>/meta.json          {"queries":[...]}   (tuỳ chọn)
```

* `accessLevel` ∈ `open | abstract | paywalled | metadata` — tình huống #9 (§8.1) cần
  ít nhất một nguồn `abstract` để đo "không được gắn độ tin cậy cao cho abstract".
* `file` là đường dẫn tương đối trong gói (`pages/…`).
* `search_index.jsonl` khớp theo **tiền tố chuẩn hoá**: khớp chính xác trước, rồi dòng mà
  mọi token đều có trong truy vấn. Gói **không** có tệp này ⇒ `pack_search` trả `None` và
  `web.py` rơi về đường thật; có tệp nhưng không dòng nào khớp ⇒ trả `[]`.

## Dựng một gói

`build_pack.py` gom trang đã thu thập + manifest nguồn thành gói đúng định dạng trên:

```bash
python3 scripts/eval/packs/build_pack.py \
    --manifest <nguồn.json> --out <thư mục gói> [--queries <kết-quả-tìm.jsonl>] [--force]
python3 scripts/eval/packs/build_pack.py --validate <thư mục gói>
```

`<nguồn.json>`:

```json
{
  "scenarioId": "S1",
  "sources": [
    {"url": "https://example.org/a", "title": "…", "date": "2025-03-01",
     "kind": "web", "accessLevel": "open", "file": "captured/a.html"}
  ]
}
```

`--queries` nhận JSONL mỗi dòng `{"query": "…", "results": [{"url": "…", "rank": 1,
"snippet": "…"}]}` (dạng `searxng_search` trả về) để dựng `search_index.jsonl`.

Mô-đun này chỉ đọc/ghi tệp cục bộ — không mở socket.

## Còn thiếu: gói cho 13 tình huống (§8.1)

**Chưa có gói nguồn thật nào.** Mười ba tình huống bắt buộc cần gói theo bảng dưới; cột
"Ghi chú" nói cái gì phải cấy vào gói để tình huống đo được. Việc thu thập cần mạng, nên
nằm ngoài phần scaffolding offline này và phải do người có thẩm quyền chạy.

| # | Tình huống | Ghi chú nội dung gói |
|---|---|---|
| 1 | Yêu cầu research đủ | vài trang thuộc một chủ đề hẹp, `open` |
| 2 | Yêu cầu rỗng / mơ hồ | không cần gói (không có lượt) |
| 3 | Main gặp câu đáng research, mode tắt | không cần gói (test tất định) |
| 4 | Trả lời phỏng vấn / sửa thẻ / đào sâu | gói nhỏ, tách được hai nhánh |
| 5 | Tạm dừng / tiếp tục / huỷ / tắt mode | không cần gói (test tất định) |
| 6 | Lĩnh vực đổi nhanh | trang có `date` trong cửa sổ hiện tại **và** trang cũ |
| 7 | Tài liệu cũ nhưng nền tảng | bài nền tảng có `date` cũ, chất lượng cao |
| 8 | Nguồn mâu thuẫn | hai trang phản bác nhau về cùng một dữ kiện |
| 9 | Chỉ có abstract | ≥1 nguồn `accessLevel=abstract`, không có full text |
| 10 | Không có code chính thức | paper không có repo; một repo bên thứ ba |
| 11 | Paper + repo + thị trường | ba nhóm nguồn: paper, repo, tin thị trường |
| 12 | Cập nhật báo cáo cũ | gói cũ + gói mới có thay đổi cấy sẵn |
| 13 | Sót nhánh lớn | thiếu hẳn một hướng "must" của bản đồ tham chiếu |

Khi dựng xong, ghim đường dẫn gói vào `scenario.pack` của bộ chạy (§7) và băm gói vào
manifest bằng `runner.pack_hash()`.
