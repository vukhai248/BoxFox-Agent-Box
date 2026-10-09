# Phụ lục bàn giao research v2 — 2026-09-25

Tài liệu này bổ sung cho bản bàn giao gốc (nay ở `docs/handoff/archive/box-agent-handoff-2026-09.md`) và `docs/handoff/v29-keyring-handoff.md` (Handoff 2). Không thay đổi quyết định hay số đo lịch sử trong hai tài liệu đó. Chủ nhà yêu cầu dừng thử nghiệm sống để tiết kiệm token; mọi phiên thử dưới đây đã dừng. Agent cloud đang làm cùng nhiệm vụ cải tổ research nên cần đọc trạng thái cây làm việc trước khi sửa trùng.

## Phạm vi đang có trong working tree

Chưa commit và chưa tạo PR. Cải tổ research v2 đã được triển khai trong working tree: `backend/src/agentbox/agent_core/research_runtime.py`, `research_ledger.py`, `research_quality.py`, `research_profiles.py`, `web.py`, `reading.py`, `roles.py`, `tool_contracts.py`, `backend/src/agentbox/memory/session_store.py`, `backend/src/agentbox/api/server.py`, bảy skill `backend/src/agentbox/vendor/hermes/skills/research/research-{scoping,search,reading,evidence,synthesis,critique,to-plan}/`, `frontend/src/components/panels/ResearchPanel.tsx`, và các test/đánh giá liên quan. Mô tả cơ chế nằm ở `docs/research/v2-implementation.md`; giao thức đánh giá và bộ 12 tình huống ở `docs/research/v2-evaluation.md` và `scripts/eval/benchmarks/research-v2.json`.

V2 mở khi `research_brief` có goal/questions/methods. Nó giữ job và ngân sách bền vững, gắn nhánh với câu hỏi, lưu snapshot nguồn, tách nguồn/đoạn/khẳng định/đánh giá, kiểm review theo version và hash của dossier, lưu bản nháp khi gate chưa đạt, tiếp tục từ checkpoint, đánh dấu plan phụ thuộc cần review lại, có bảng Research trong workspace. Nguồn chuyên biệt hiện có OpenReview, repo và PDF theo cửa sổ trang. OCR ảnh scan chưa có; bộ 12 tình huống × 3 lần **chưa đo**.

Các thay đổi sau khi quan sát lượt sống: `research_brief` trả đúng ID `q1…` để delegate; delegate cập nhật trạng thái câu hỏi; sửa cổng plan để đọc mọi mục Verification thay vì chỉ mục đầu tiên; tính độc lập của nguồn DOI theo paper chứ không gom cả `doi.org`; mặc định v2 không chọn nhầm hồ sơ giá khi thiếu `jobProfile` mà dùng `mixed`; `reviewModes` bắt kiểm bằng chứng và phản biện cho job có nhiều câu hỏi quan trọng kể cả tier 2; test ReadStore dùng ref UUID thật thay vì `r1/r2`. Các thay đổi cuối cùng về `mixed`, `reviewModes` và test completion được thêm sát lúc chủ nhà yêu cầu dừng; **chưa chạy lại toàn bộ suite trên trạng thái cuối**.

## Hai lượt thử chuyển tuyến Việt Nam đã dừng theo yêu cầu

Cả hai lượt dùng cùng yêu cầu: nghiên cứu nhu cầu bệnh nhân/NVYT, quy trình và giấy tờ chuyển tuyến, giải pháp số, rủi ro pháp lý/an toàn rồi lập kế hoạch AI agent; chỉ nguồn công khai, không dữ liệu bệnh nhân, không thực nghiệm mô hình, ngân sách đề nghị khoảng 20 phút. Chúng chạy trên harness cách ly cổng 3103/3104, không phải app chính cổng 3100. Cả hai harness cách ly đã dừng.

| Lượt | Model và session | Quan sát trước khi dừng |
|---|---|---|
| 1 | OpenCode `muse-spark-1.3-contributor-free` high; `7d2e7659e8934e78ae2dd935724cc6e4` | Khoảng 900 giây sử dụng; 41 source rows; 4 nhánh research (1 thất bại do hết hạn lượt, 3 hoàn tất); dossier v1 `quality_ok=0`, `gate=warn`, chưa có research review; plan v2 đã ghi và có hai vòng plan-review. Job bị dừng ở trạng thái partial, không phải kết quả nghiên cứu đã kiểm. |
| 2 | Cùng model trên mã sửa sau lượt 1; `7d87d9bddc4f4b2ab1cf5a3c34b90b1b` | Khoảng 608 giây sử dụng; 20 source rows; 4 nhánh research (q3 thất bại), một plan-review thất bại; dossier v1 `quality_ok=0`, `gate=warn`, chưa có research review. Root session và job đều đã hủy theo yêu cầu. |

Vết hữu ích: main tự chia ba nhánh ban đầu và tiếp tục nhánh tiếp theo; nó tìm nguồn pháp lý, paper và sản phẩm, ghi nguồn và phần không chắc. Nhưng cả hai lượt tự chọn **tier 2** vì cho rằng 20 phút không đủ tier 3, nên bản đang chạy không buộc kiểm bằng chứng/phản biện research. Lượt 2 còn bỏ `jobProfile`, khiến logic cũ mặc định **price** cho dossier y tế. Dossier vẫn thiếu căn cứ/gắn nguồn theo gate; plan được viết khi dossier còn nháp. Một số tuyên bố pháp lý, ngày hiệu lực và số liệu trong bản nháp chưa được kiểm độc lập, không được dùng như tư vấn pháp lý hoặc y khoa. Agent cloud cần đánh giá chất lượng từng claim với văn bản gốc trước khi coi kế hoạch có căn cứ.

Nguồn `web_search source=web` trong lượt sống thường thất bại: Firecrawl trả 403, các provider Brave/Tavily/Exa/Parallel chưa có key, khiến agent dựa nhiều vào chỉ mục paper, Wikipedia và URL đoán trước. Probe keyless Bing RSS cho kết quả không liên quan truy vấn; Google HTML nhanh chóng trả 429; không nên coi chúng là fallback đã xác nhận. Đây là **điểm chặn lớn đối với deep research** và cần xử lý trong hệ thống tìm nguồn, không bù bằng nhiều agent hay kéo dài thời gian.

## Route model đã thử và đã hoàn nguyên

- OpenCode `muse-spark-1.3` bản thường vốn tắt. Bật tạm rồi chạy probe thật trả **402 Insufficient account funds**; đã hoàn nguyên danh sách model bật.
- OpenRouter `meta/muse-spark-1.3` bật tạm, probe trả **403** vì tài khoản cần xác nhận 18+ trên OpenRouter; đã hoàn nguyên.
- TokenHarbor `muse-spark-1-3` bật tạm, probe trả **402**, số dư $0; đã hoàn nguyên.
- Antigravity `gemini-3.8-flash-high` có metadata và trả lời một bước, sau đó router trả **429** sau retry dù bảng quota còn số; lượt High thất bại. Lượt Medium mới mở đã hủy ngay khi chủ nhà yêu cầu chuyển Muse.
- Vì vậy lượt Muse nghiên cứu sống thực sự dùng route **Contributor Free** của OpenCode. Không được ghi nhầm là bản thường. Không đổi key, số dư, xác nhận tài khoản hoặc cấu hình model còn lưu sau các probe.

## Số đo test và giới hạn xác nhận

- Một lần chạy `python -m pytest backend/tests/unit -q` trước các chỉnh cuối: **1674 passed, 2 failed, 18 skipped** trong 427 giây. Hai ca đỏ ở `test_web_read_store.py` giả định ref cũ `r1/r2` trong khi runtime nay dùng UUID để tránh trùng sau restart. Test đã sửa theo ref trả về; riêng file đó **20 passed**.
- Sau sửa `mixed` và khởi đầu `reviewModes`, ba file `test_research_profiles.py`, `test_research_brief.py`, `test_research_job_v2.py` đạt **49 passed**. Sau mốc đó có thêm thay đổi ở completion gate và một test mới; **chưa chạy test trên trạng thái cuối** vì chủ nhà yêu cầu dừng.
- `test_plan_quality.py` đạt **16 passed** sau sửa lỗi nhiều mục Verification. Frontend build đã đạt ở lượt trước; chưa chạy lại sau yêu cầu dừng. Không có benchmark chất lượng research 12×3 hay đánh giá web sống hoàn chỉnh.

## Việc agent cloud nên kiểm tiếp khi được phép

1. Đọc diff hiện tại trước khi sửa trùng. Soát `reviewModes` xuyên suốt `research_brief → dossier_write → research_verify → research_status → research_update`, nhất là publication của tier 2. Chạy lại focused và full suite khi chủ nhà cho tiếp tục thử.
2. Sửa đường tìm kiếm web công khai hoặc cấu hình một provider có key; kiểm khả năng tìm văn bản chính thức và nguồn phản chứng. Không tự nhận đã đọc toàn văn từ abstract/URL không mở được.
3. Kiểm dossier y tế theo từng khẳng định, ngày hiệu lực và bản sửa đổi; đừng mang số liệu/tuyên bố chưa xác minh từ bản nháp thành quyết định sản phẩm.
4. Đánh giá lại mặc định `mixed` và cách áp mẫu metadata theo **từng loại bằng chứng**. Mẫu trung lập tránh lỗi `price` nhưng chưa tự kiểm đủ trường của từng văn bản pháp luật/paper.
5. Đo một lượt hoàn tất thật sau khi đường tìm nguồn và review ổn định, rồi mới chấm 12 tình huống × 3 lần. Hiện không đủ bằng chứng để nói hệ thống đã deep research đạt chất lượng.

Trạng thái cuối: **đã dừng thử nghiệm theo yêu cầu; chưa chạy thêm test; working tree giữ nguyên để agent cloud soát và tiếp tục**.
