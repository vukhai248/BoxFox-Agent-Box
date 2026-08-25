# Agent Box — tóm tắt kế hoạch

Tài liệu đầy đủ: **`/code/.plans/agent-box-plan.md`** (Phần 0 → XVI). Đây là bản kế hoạch duy nhất cần đọc.

## Sản phẩm

Một **AI Computer tự host** (agent có một máy tính riêng để làm việc, xem file, chạy lệnh, điều khiển trình duyệt), trong đó:

- mọi dữ liệu đi vào agent đều mang **nhãn nguồn gốc** — đến từ đâu, có được quyền chỉ đạo agent không, được gửi ra đâu;
- mọi hành động ra ngoài (ghi file, chạy lệnh, gửi mạng) đều cần một **cho phép có phạm vi và có thời hạn**, được cấp **sau** thời điểm dữ liệu bẩn nhất đi vào ngữ cảnh.

Điều kiện "cấp sau" là chỗ khác biệt. Nó chặn đúng lỗi mà các agent hiện tại mắc: người dùng đồng ý một hành động vô hại, rồi chuẩn thuận đó bị mang sang đúng bước rò rỉ dữ liệu mà không phát sinh thêm một lần hỏi nào (arXiv 2510.26328).

## Cấu trúc tài liệu

| Phần | Nội dung |
|---|---|
| **0** | Từ điển thuật ngữ — 4 mục, gồm cả mục 0.4 các viết tắt kỹ thuật thông dụng |
| **I-IV** | Sản phẩm là gì · kiến trúc tổng thể 7 tầng · bối cảnh bài toán · đối thủ và công trình liên quan |
| **V-XII** | Tám module riêng: Agent Core (**hai chế độ Plan/Act, ReAct bên trong mỗi chế độ** · bảy thành phần Controller · kiến trúc nhiều agent · tính năng nền tảng) · Tool & Skill · Sandbox · Computer Use (**có cổng chặn mặc định tắt**) · **Bảo mật** · Memory · Model Router · **Giao diện** |
| **XIII** | Benchmark & đánh giá |
| **XIV-XVI** | Lộ trình đồ án · lộ trình sản phẩm và cloud · rủi ro và điểm cần quyết |

Mỗi phần kỹ thuật (V-XIII) kết thúc bằng đúng hai khối: **▸ Phạm vi đồ án (3 tháng)** và **▸ Cần gì để thành sản phẩm** (kèm ước lượng riêng từng việc).

## Bốn đóng góp, xếp theo độ mạnh

1. **Đ3** — mở rộng nhãn nguồn gốc sang hành động phát sinh từ **ảnh màn hình** (computer use). Chưa thấy công trình nào làm.
2. **Đ4** — đo định lượng đánh đổi **ASR ↔ khả năng làm việc ↔ số lần phải hỏi người dùng**.
3. **Đ1** — ghép kiểm soát luồng thông tin với giấy phép có phạm vi/thời hạn trong cùng một runtime chạy được.
4. **Đ2** — đưa cả hai vào một AI Computer tự host dùng được, có giao diện.

## Mô hình suy luận của Agent Core

Phần V nói rõ agent chọn hành động theo mô hình nào, vì lựa chọn đó ràng buộc trực tiếp tầng bảo mật.

**Quyết định: hai chế độ vận hành tách biệt — Plan mode và Act mode — và ReAct chạy bên trong từng chế độ.** Đây là mô hình mà Cline, Cursor và Claude Code đang dùng, khác Plan-Act-Replan ở một điểm kiến trúc: **năng lực của agent khác nhau giữa hai giai đoạn**, không chỉ prompt khác nhau.

| | Plan mode | Act mode |
|---|---|---|
| Tool có trong prompt | Chỉ `SAFE`: `list_dir`, `read_file`, `ask_user` | Toàn bộ: thêm `write_file`, `edit_file`, `run_command` |
| Tool **không có** trong prompt | `write_file`, `edit_file`, `run_command`, `computer_use` — **không có trong prompt**, không phải bị từ chối | — |
| Số lần xin quyền | **Bằng 0 trong đa số trường hợp** | Theo bảng quyết định 9.5.3 |

- **Chuyển Plan → Act là điểm chuẩn thuận duy nhất của cả một việc**, và chỉ **người dùng** bấm được. Mode Manager **không** nhận lệnh chuyển chế độ từ output của LLM — nếu nhận thì một chỉ thị độc chỉ cần viết "hãy chuyển sang Act mode" là vô hiệu hoá toàn bộ cơ chế.
- Một cú bấm chuyển làm bốn việc: chốt `content_hash` của bản kế hoạch · chuẩn thuận artifact kế hoạch · cấp **giấy phép theo phạm vi kế hoạch** (30 phút) · mở bộ tool đầy đủ. Chuẩn thuận đó **không** làm sạch ngữ cảnh — thứ cho agent đi tiếp là giấy phép, không phải chuẩn thuận.
- **Giá trị lớn nhất là dồn việc hỏi người dùng về một chỗ có nghĩa:** một quyết định trên một bản kế hoạch đọc được tốt hơn hẳn mười lăm quyết định trên mười lăm thẻ rời rạc. Permission fatigue là rủi ro số một của cách A.
- **Quy tắc tái neo** giữ giấy phép sống được: artifact bẩn mới **trong** phạm vi kế hoạch không làm mất hiệu lực, **ngoài** phạm vi thì mất ngay. Đây là một **nới lỏng có chủ ý** so với tuyên bố 9.4.2, và nó được ghi thành một mục ngoại lệ riêng ở 9.4.2 chứ không ẩn đi.
- **Phạm vi kế hoạch do LLM viết, nên có hai chốt chặn ở Controller:** (1) phạm vi **đã gộp và đã `realpath`** phải hiện thành một dòng riêng trên thẻ chuyển chế độ; (2) một **trần độ rộng cứng nằm trong file cấu hình ngoài workspace** — phạm vi giải ra gốc workspace hoặc vượt 5 thư mục thì Controller **từ chối** cấp giấy phép gộp và lùi về hỏi từng hành động. `EGRESS` và đường dẫn `BÍ_MẬT` **luôn** bị loại khỏi phạm vi gộp.
- **Kiến trúc nhiều agent: KHÔNG dùng cho đồ án.** Một agent một luồng. Lý do riêng của dự án mạnh hơn lý do hiệu năng: **mỗi ranh giới agent là một chỗ nhãn có thể bị rửa** — một bản tóm tắt của sub-agent vào ngữ cảnh chính với nhãn sạch là vô hiệu hoá cả tầng nhãn bằng đúng một lần chuyển tay. Ngoại lệ đáng ghi lại (nhưng ngoài phạm vi): sub-agent chỉ-đọc bị cách ly, chỉ trả về giá trị có kiểu — đúng là **quarantined LLM** của FIDES và CaMeL.
- **Kế hoạch không phải cơ chế bảo mật.** Policy Engine không bao giờ đọc `plan.md` trong workspace (`plan.md` do agent ghi, injection cũng ghi được). Thứ được tin không phải bản kế hoạch, mà là **hành động bấm của người dùng trên một nội dung cụ thể đã hiện ra**.
- **Reflexion ngoài phạm vi**, kèm lý do thiết kế: một đoạn tự phê bình sinh từ kết quả bẩn vẫn mang nhãn bẩn, nên nó không làm sạch được gì mà chỉ thêm một chỗ để chỉ thị độc được diễn giải lại.

Phần V cũng ghi ra **tám tính năng nền tảng bắt buộc** kèm mặt bảo mật của từng cái. Ba chỗ dễ làm sai nhất: quay lại checkpoint phải **quay lại cả nhãn** nhưng **không** làm sạch ngữ cảnh; agent **không có tool nào** để tự quay lại (nếu có thì injection dùng nó để xoá dấu vết); mở lại phiên cũ **luôn tăng `task_epoch`** và **không hồi sinh** giấy phép cũ.

## Ba quyết định đáng tranh luận

**1. Benchmark là AgentDojo + VPI-Bench, không chạy OSWorld/WebArena.**
Hai cái sau đo *khả năng làm việc*, không đo bảo mật — SOTA đầu 2026 đã ~66,3% và ~74,3%. Thi ở đó là tự đặt mình vào trục "agent giỏi hơn", trong khi mọi so sánh của dự án là **so với chính nó khi tắt tầng bảo mật**.

**2. Bộ mô phỏng người dùng có luật chốt trước, và báo cáo tách 3 số.**
Vì cơ chế dựa vào việc hỏi người dùng, ASR phụ thuộc hoàn toàn vào cách "người dùng" trả lời. Luôn từ chối thì ASR≈0 nhưng vô nghĩa; dùng oracle biết đáp án thì thứ chặn được tấn công chính là oracle. Nên: bộ mô phỏng **chỉ thấy đúng những gì giao diện hiện ra**, chạy sáu luật P1-P6 chốt trước, và báo cáo tách **(1) số lần hỏi · (2) ASR · (3) khả năng làm việc** dưới cùng một policy, kèm hai đường biên (luôn đồng ý / luôn từ chối). Đây là điểm hội đồng sẽ hỏi đầu tiên.

Hai luật trong sáu luật đó tồn tại vì một lý do dễ bỏ sót: nếu bộ mô phỏng chỉ biết "đồng ý một lần" hoặc "từ chối" thì nó **không bao giờ cấp một giấy phép nào**, và chênh lệch giữa cấu hình C2 và C3 sẽ bằng 0 vì bộ mô phỏng chứ không vì thiết kế.

**3. Nhân lực quyết định phạm vi, và con số không dễ chịu.**
Cộng đủ mọi phần: **170,5-206 ngày = 34,1-41,2 tuần-người** (1 tuần-người = 5 ngày của một người). Sau đường cắt ở mục 14.2 (20-27,5 ngày) còn **150,5-178,5 ngày = 30,1-35,7 tuần-người**. Con số này cao hơn bản trước vì Phần V phình thêm: bảy thành phần Controller, bộ máy hai chế độ, và bốn tính năng nền tảng ở mục 5.8. Đối chiếu ngân sách 13 tuần lịch:

| Nhân lực | Ngân sách | Kết luận |
|---|---|---|
| 1 người | 13 tuần-người | **Không vừa 3 tháng bằng bất kỳ đường cắt nào.** Phải xin kéo dài, hoặc thu hẹp còn Phần IX + XIII + giao diện hai khung (~15-18 tuần-người, **vẫn thiếu 2-5 tuần**) |
| 2 người | 26 tuần-người | **Thiếu 4,1-9,7 tuần-người ở mọi điểm trong khoảng** — không vừa kể cả ở đầu dưới. Phải cắt thêm ngay tuần 0 (bỏ Phần VIII → khoảng 27-30,5), và **mất Đ3 + VPI-Bench** |
| 3 người | 39 tuần-người | **Cấu hình khuyến nghị duy nhất giữ được cả bốn đóng góp.** Biên an toàn **3,3-8,9 tuần-người** — đã mỏng hơn bản trước, nên vẫn phải theo đúng năm gate |

Nếu Gate 1 buộc dùng kế hoạch B toàn phần thì phạm vi thành **30,5-36,2 tuần-người** (mục 13.3 có đường cắt bù riêng, bù được tối đa 1,1 trên 1,5 tuần cần bù).

Không cắt trong mọi trường hợp: Phần IX (bảo mật), bộ ca **T5** (rửa nhãn) và **T7** (tấn công cơ chế hai chế độ Plan/Act), và ba cấu hình C1-C3 của Phần XIII — cắt những thứ đó là bỏ chính đóng góp. C0 là baseline nên được rút xuống 5 ca mẫu nếu phải cắt bù.

## Năm gate ra quyết định trong lộ trình

- **Gate 0 (tuần 0):** hỏi giảng viên hướng dẫn có bắt buộc thành phần ML tự huấn luyện. Nếu có → **+4-6 tuần-người**, phải bỏ computer use hoặc bỏ 2 khung giao diện.
- **Gate 1 (tuần 1):** spike tích hợp AgentDojo + VPI-Bench, ba nhánh có ước lượng công riêng (0 · 1 tuần · 1,5 tuần) và một **đường cắt bù riêng** thay vì dùng lại mục 14.2. Phát hiện ở tuần 10 là mất cả phần đánh giá.
- **Gate 2 (tuần 6):** phản ví dụ "giấy phép cấp lúc sạch bị dùng lúc bẩn" bị chặn từ đầu đến cuối qua giao diện. Mốc quan trọng nhất.
- **Gate 3 (tuần 9-10):** pipeline đánh giá ra được số cho cả 4 cấu hình.
- **Gate 4 (tuần 11):** có số cho RQ1/RQ2/RQ3.

Mỗi gate có dòng ghi rõ **trượt thì cắt gì**. Nguyên tắc: trượt gate thì cắt phạm vi, không dời hạn.

Rủi ro riêng cần biết ở Gate 3: nếu cấu hình **C1 (chỉ hỏi, tức mức các agent hiện tại đang làm)** ra kết quả ngang **C3 (đầy đủ)** thì dự án không có đóng góp thực nghiệm. Biết ở tuần 9 còn cứu được.

## Sáu câu cần quyết — ba câu đầu phải xong tuần 0

1. **Bao nhiêu người, có ai mạnh hạ tầng/SWE?** — quyết định trực tiếp phạm vi (xem bảng trên)
2. **Giảng viên có bắt buộc ML tự huấn luyện?** — đổi cả lộ trình
3. **Tên dự án** — repo hiện là `Cloud-Anget-P`; "Anget" là lỗi chính tả của "Agent", và "Cloud" đi ngược thông điệp local-first
4. Công khai repo từ tuần mấy (đề xuất: sau tuần 10, khi bộ ca T5 đã pass)
5. Module thứ hai ngoài coding (tài liệu có dữ liệu mật, hay xử lý ảnh)
6. Nhóm người dùng đầu tiên

## Ba rủi ro có thể làm thất bại

**R1** ngữ nghĩa nhãn không chặt — tìm được đường rửa nhãn mà thiết kế không chặn · **R2** hỏi người dùng quá nhiều đến mức không ai dùng được (taint explosion) · **R3** trượt thời gian.

"Có sản phẩm khác làm trước" (Pipelock, FIDES, Progent) chỉ ở mức thấp-trung bình và không nên chi phối quyết định.

Mục 16.2 liệt kê **12 điều dự án không tuyên bố** — trong đó hai điều mới nhất: dự án **không** tuyên bố người dùng phát hiện được một bước độc nằm trong bản kế hoạch, và **không** tuyên bố giấy phép theo phạm vi kế hoạch hẹp bằng giấy phép một lần — viết sẵn để dùng nguyên văn trong báo cáo, vì một tuyên bố quá tay bị hội đồng bắt mất nhiều điểm hơn một phạm vi hẹp được nói rõ.
