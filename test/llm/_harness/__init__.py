"""Bộ khung chạy bài test LLM cho BoxFox Agent Box.

Không phải test agent — agent chưa tích hợp. Bộ này chỉ trả lời MỘT câu hỏi:
**LLM có nhận đúng quy trình của BoxFox hay không** khi ta đưa cho nó bản hợp
đồng quy trình (`contract/`) cùng dữ liệu có nhãn (`fixtures/`).

Nguyên tắc thiết kế, để kết quả có thể tin được:

* **Chấm điểm tất định.** Mọi bài buộc model trả JSON theo `response_schema`,
  rồi khẳng định trên từng trường. Không có LLM nào đi chấm điểm LLM khác.
* **Nhiệt độ 0** và `repeat` > 1 cho các bài an toàn: một lần đúng có thể là
  may, ba lần đúng thì mới tính là hiểu.
* **Tách hợp đồng khỏi bài test.** `contract/*.md` là thứ đem đi thử;
  `cases/**/*.json` là câu hỏi + tiêu chí đậu. Sửa quy trình chỉ sửa một chỗ.
* **Không nuốt lỗi.** 429/503 thì lùi rồi thử lại, hết cách thì bài đó ghi
  `ERROR` — không bao giờ ghi PASS cho một lần gọi thất bại.
"""
