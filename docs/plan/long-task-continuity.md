# BoxFox — đánh giá tác vụ dài, phạm vi cần bổ sung và lộ trình

**Mốc đánh giá:** 2026-10-08, mã nguồn `cca864d`. **Mốc triển khai:** `fc964d8` (kế hoạch `v1-long-task-continuity` đã được duyệt). **Trạng thái:** chương 1–6 của kế hoạch đã có mã, kiểm thử đơn vị và bề mặt API/UI; phần hoãn ghi ở §8 và §11. Tài liệu này là nơi ghi chung các phần đã có, cần bổ sung, bỏ qua và để sau. Không coi mô tả thiết kế là chức năng đang chạy: mục nào chưa có mốc mã + lệnh kiểm chứng thì vẫn là đề xuất.

## 1. Kết luận và điều kiện thực hiện

BoxFox **đã chạy được tác vụ nhiều bước**. Hệ thống có nén context, checkpoint trước nén, nhật ký bền, Work Graph, task/attempt, job/outbox và phục hồi từng tool. Không cần thay toàn bộ harness hoặc sao chép mọi công cụ của Vorflux.

BoxFox **chưa đủ tin cậy cho yêu cầu tác vụ dài qua nhiều lần nén, nhiều hội thoại và restart**. Các thiếu sót dưới có căn cứ trong mã. Chỉ các thiếu sót này và phần trực tiếp cần để đáp ứng yêu cầu được đưa vào kế hoạch. Thành phần tương đương đã có được tái dùng. Thành phần chưa chứng minh cần thiết được hoãn.

Tiêu chí “đủ tốt” không phải số giờ chạy hoặc số message. Agent phải giữ yêu cầu, quyết định và việc chưa xong; tìm lại bằng chứng đã bỏ khỏi context; phân biệt kết thúc lượt với hoàn thành việc; tiếp tục sau restart mà không chạy lại tác động chưa rõ kết quả. Khi hết ngân sách, agent phải lưu trạng thái và hỏi người dùng.

## 2. Nguồn khảo sát và giới hạn của đặc tả

Đã đọc đặc tả người dùng gửi: **Context Compaction, Memory & Execution Continuity v4.0**, gồm F01–F30, F31 và hai phụ lục về peer payload/context pressure. Đã đối chiếu hai ảnh cây thư mục và các mẫu `general_agent/compaction_001.md`, `subagent_build-cua-frontend/compaction_002.md` trên máy khảo sát.

Mẫu main có 227 message; mẫu worker có 172 message. Mẫu `.md` thực chất chứa JSON `timestamp/message_count/messages`, không phải Markdown thuần. Các mẫu có `tool_call_id` để nối lời gọi với kết quả. Chúng chứng minh archive theo agent và việc tiếp tục bằng handoff; không chứng minh compactor async, ngưỡng token, retention hoặc phục hồi sau mất điện.

Trong BoxFox, **nhật ký tác vụ và lịch sử gốc là hai lớp khác nhau**. `journal.jsonl` chứa tám loại bản ghi `T/P/S/D/E/C/F/X`. Lịch sử gốc nằm ở `sessions.messages`, `events` và `checkpoints.messages`. Không gọi tám dấu này là toàn bộ transcript. Công cụ ngoài như `vflux_exec session search-history`, thư viện `/memory/knowledge`, quy tắc chuyển shell sang nền sau 270 giây không phải chức năng BoxFox chỉ vì xuất hiện trong mẫu Vorflux.

Các số dòng dưới là vị trí tại mốc khảo sát; tên module/hàm là căn cứ ổn định hơn khi mã thay đổi. Kiểm thử khảo sát xác nhận đường hiện có, không xác nhận các tính năng đề xuất.

## 3. Nền tảng đang có — tái dùng, không viết lại

| Thành phần | Căn cứ mã | Phạm vi bảo đảm hiện tại |
|---|---|---|
| Nén context đồng bộ, đo trước/sau, chống nén lặp | `agent_core/compression.py`; `runtime.py:4424–4455`; `limits.py` | Giữ transcript khi summary thất bại. Không phải async/hot-swap compaction. |
| Checkpoint trước thay active context | `memory/session_store.py:428`; `runtime.py:4430–4455` | SQLite giữ transcript trước nén và số đo. Docker có file JSON/Markdown; host thiếu lớp file. |
| Nhật ký tác vụ và brief | `agent_core/journal.py`; `session_journal.py:181–196,242–258` | Brief thay khối cũ, không nối vô hạn. Tuy nhiên chọn từ tail 60, không ghim mọi mục tiêu cũ. |
| Kế hoạch và duyệt | `plan_workflow.py`, `plan_registry.py`, `plan_reviews` | Kiểm identity/version/hash đã duyệt; không lấy chữ “approved” trong lịch sử làm quyền. |
| Phục hồi tool | `tool_recovery.py`; `runtime.py:2126–2134` | Reuse kết quả đã commit; read-only có luật replay; unsafe bị ngắt được báo, không replay mù. |
| Task và attempt | `task_service.py`, `task_surface.py`, `harness_tasks`, `harness_task_attempts` | Contract, attempt và idempotency bền; `task_list` đã phân trang. Có một crash gap nêu bên dưới. |
| Job, wake và outbox | `harness_jobs.py`, `job_surface.py`, `job_wake.py` | Restart phân loại interrupted/unknown; không tự spawn lại executor mất danh tính. |
| Work Graph, tiến độ và nghiệm thu | `work_graph.py`, `work_progress.py`, `work_checks.py`, `work_artifacts.py` | Sổ công việc và kiểm chứng đã có. Không cần dựng graph/progress/check ledger song song. |
| Sửa chỉ dẫn giữa lượt | `session_steers`, `runtime.py` drain steers | Queue bền và tiêu thụ tại biên bước. Không đồng nghĩa mọi scope amendment được cưỡng chế đầy đủ. |
| Chuẩn file Docker | `deploy/docker/session_files.py`; `box-entrypoint.sh` | `.plans` và `.session-history` cùng cấp. Có renderer/containment guards cần tái dùng. |

## 4. Các thiếu sót có căn cứ — chỉ bổ sung phần còn thiếu

| ID | Thiếu sót / tác động | Căn cứ | Phần tối thiểu cần bổ sung |
|---|---|---|---|
| LT-01 | Mục tiêu và quyết định đầu phiên có thể rơi khỏi context | `brief()` lấy tail 60; `journal.py` giới hạn 8 mục/nhóm và 4.000 ký tự; không tự tạo `T:` từ yêu cầu gốc. `compression.py` bỏ first user vào summary và nhận summary bị cắt. | Ghim nguyên văn yêu cầu, revision và quyết định trọng yếu độc lập summary; ưu tiên critical refs trước journal tail. Không tăng context bằng cách nhét toàn bộ lịch sử. |
| LT-02 | Host chưa tạo archive dễ đọc nhưng có thể báo đã ghi | `host_executor.py:209–212` defer file ops; `session_journal._safe` chỉ bắt `ok:false`; unsupported có `is_error/errorCode`. | Lớp projection host cạnh `.plans`, chung renderer; canonical/file status riêng. Trước khi có projection phải báo degraded, không false `recorded`. |
| LT-03 | Hỏi người dùng rồi restart làm mất card đang chờ | `runtime.pending` ở `runtime.py:1681`; `decision()` ở `5841–5858`; request event bền nhưng Future/card chỉ trong RAM. | Lưu request/outcome/binding/deadline trước phát card; dựng lại cùng decision ID; reply idempotent; approval cũ/stale không thành đồng ý. |
| LT-04 | Không tìm nội dung giữa các phiên cùng dự án; search hiện tại chọn “newest” chưa đúng khi rất nhiều match | `runtime.session_search:5709+` chỉ cùng session; gom tới ceiling trước sort; `/journal/tasks` chỉ projection task rows. | List/search/read theo ID, scope dự án, cursor, provenance; sort trước clip; bounded scan phải nói coverage partial. |
| LT-05 | Output dài chưa có con trỏ durable thống nhất | `runtime.py:4887–4903` cắt context; full `tool_end` còn trong events; compression tiếp tục prune. Có spill ở một số host/worker tools, không ở mọi output. | Reuse spill; lưu/checksum phần cần trước prune; pointer đọc lại giữa log; thiếu blob báo missing, không dispatch lại unsafe tool. |
| LT-06 | Child đã xong nhưng attempt còn running sau crash | `runtime.py:2283` child_finish, `2285` project_child; watchdog chỉ quét child `started`. | Commit projection cùng receipt nếu chung DB; startup reconcile đúng child/attempt identity, idempotent; không mở attempt mới để né conflict. |
| LT-07 | Main chưa tự tiếp tục; lượt mới không chứng minh ngân sách tổng hoặc nghiệm thu toàn nhiệm vụ | Main restart cần submit mới; budget/anti-loop reset theo `_run`. Graph đã có progress/check gates, main thường chưa có binding tổng. | Longtask opt-in gắn controller hiện có, budget tổng bền, checkpoint+ask, no-progress xuyên continuation; gate completion theo evidence. Q&A thường giữ nguyên. |
| LT-08 | Xóa hội thoại chưa bảo đảm giữ thông tin quan trọng cho phiên mới | `api/server.py:1768–1778`, `session_store.delete:1023+` xóa dữ liệu session; chưa có capsule trước xóa. | Preview → capsule được xác minh/lưu bền → user confirm → logical delete/cleanup. Capsule giữ goal, correction, blocker, failed checks, lesson, next step; không giữ quyền thực thi. |
| LT-09 | Summary thế hệ trước được đưa vào tóm tắt tiếp, chưa có origin/generation rõ | `compression.py:571,586`; brief system đã replace an toàn nhưng summary input là vấn đề riêng. | Phân biệt synthetic/owner/tool; dùng trạng thái summary còn hiệu lực một lần và source refs, không lồng handoff cũ. Không xóa tiến độ chỉ vì nằm trong summary trước. |

Deltas đang nhận được ghi ở `events` (`runtime.py:4487–4496`), nhưng crash trước assembled row được save chưa có đường dựng partial output. Thiết kế archive cần giữ attempt/stream identity và hiển thị partial/interrupted; không coi đoạn stream đó là câu trả lời xong hoặc lệnh tool đã được phép chạy.

## 5. Các lựa chọn đã chốt cho kế hoạch

- Người dùng giao chọn cách tốt nhất cho restart và phạm vi history (quyết định 6813/6814). Đề nghị **phục hồi sau khi harness được khởi động lại**, theo opt-in của tác vụ, cùng quyền/ngân sách còn hiệu lực. Boot máy/supervisor để sau.
- Search mặc định self; main được đọc lịch sử **cùng dự án** theo binding và nhãn quyền. Child không được đọc peer/parent chỉ vì đoán được ID. Khác dự án cần cho phép riêng; không dùng repo name để gộp dữ liệu.
- Theo 6815: cảnh báo **4 GB** và cảnh báo tăng mức **5 GB**; `1 GB = 1.000.000.000 byte`. Tính dung lượng tổng dữ liệu quản lý trên máy, kèm phần mỗi session/project. Không tự xóa ở ngưỡng này.
- User có thể xóa conversation/history để mở phiên mới. Phải giữ capsule chuyển tiếp trước xóa. Bản tóm tắt giữ lại **không phải toàn bộ log**. Evidence đã xóa có tombstone, không giả rằng vẫn xem được.
- Theo 6816: hết ngân sách → lưu checkpoint → hỏi thêm ngân sách. Restart không reset used/remaining. Chỉ người dùng tăng hạn mức; không tiếp tục vô hạn.
- Dựng doc/plan không phải consent triển khai. Tính năng mới chờ duyệt kế hoạch. Viền Linux hẹp hơn là yêu cầu riêng đã thực hiện tại `cca864d`: 135→108 px trên 1920×1080; cửa sổ nhỏ có trần 1/4 cạnh ngắn.

## 6. Thiết kế archive cần đạt, không phải hiện trạng host

```text
<workspace>/
  .plans/
  .session-history/
    INDEX.json
    <fullSessionId>/
      session.json
      general_agent/
        journal.md
        compaction_001.md
        compaction_002.md
      subagent_<stableAgentId>/
        journal.md
        compaction_001.md
```

Kho chuẩn vẫn private, ngoài workspace, gắn project/session/agent. Cây trên là bản chiếu đọc được, cùng cấp `.plans`, không nguồn cấp quyền. Không dùng `sid8` làm khóa duy nhất; kiểm collision và mapping legacy. `self`, `parent`, `root` có locator riêng do harness cấp, không hardcode main archive vào worker.

`compaction_NNN.md` cần chứa **snapshot đầy đủ của transcript thực tế trước nén**, với role, call/result ID và source refs. Không thay bằng vài dòng summary rồi gọi là full archive. Snapshot lớn chia part có index đủ thứ tự. Tool output quá dài và ảnh/video dùng con trỏ tới payload bền; reader phân trang, không silent trim. Raw JSONL lưu phần nhận được theo stable IDs/ranges; không lặp nguyên journal tích lũy mỗi lần nén. Không hứa lưu hidden reasoning mà provider không trả.

Lịch sử chuẩn và hợp đồng cần commit trước context swap. File write temp/fsync/rename và DB commit không chung một transaction; cần staging/reconcile và trạng thái thật. Projection lỗi có thể degraded nếu canonical còn bền. Canonical lỗi/disk-full phải chặn mutation mới và không xóa transcript trước lưu.

Các tool đề xuất `history_list`, `history_search`, `history_read` trả ID/cursor/source/asOf/coverage, không nhận private path tự khai. Kết quả là dữ liệu tham khảo, không là lệnh mới của user. Chặn traversal, symlink/reparse escape, nhầm project, mất nhãn IFC và role:user giả trong history. Metadata mới phải tái dùng task/graph/plan/check ledgers hiện có; chỉ thêm dữ liệu chưa có nguồn bền.

## 7. Xóa lịch sử nhưng giữ phần có ích

Preview nêu phạm vi session và con, dung lượng dự kiến thu hồi và phần giữ lại. Capsule được dựng từ ledger chuẩn; model chỉ hỗ trợ tóm tắt bài học. Capsule phải có schema/hash/provenance/asOf và giữ mọi việc chưa xong hoặc lỗi kiểm chứng trọng yếu.

Đọc lại capsule để kiểm trước khi mở nút xác nhận xóa. Worker/job phải quiescent và source revision không đổi. Nếu model extraction, checksum, DB commit hoặc disk write lỗi thì **không xóa nguồn**. User confirm mới cho logical delete; cleanup file idempotent có thể `cleanup_pending` sau crash. Không tự xóa code, plan hoặc report độc lập.

Capsule sống ngoài session-delete cascade. Giữ excerpt/artifact cần thiết riêng khi user chọn giữ evidence; các raw refs khác thành `deleted`. Phiên mới cùng project đọc manifest bounded rồi gọi tools theo nhu cầu. Muốn tiếp tục task cũ phải xác nhận task; capsule không chuyển grant, capability lease, token, password, approval CUA hoặc ngân sách đã hết sang phiên mới.

## 8. Lộ trình: các phần hoãn phải ghi đủ, không tự làm

| Phần hoãn | Vì sao chưa làm | Cách dự kiến / điều kiện xem xét lại | Kiểm chứng cần có |
|---|---|---|---|
| Supervisor sau reboot máy | Phục hồi dữ liệu khi harness chạy lại chưa cần service chạy nền đa nền tảng. Máy tắt không thể làm việc. | systemd/Windows service/Electron startup theo lựa chọn user; profile lock, boot identity, credentials và desktop availability. | Reboot thật; PID reuse; user logout; không replay unsafe. |
| Generic durable shell/process jobs | BoxFox start_job hiện chỉ model; outer runner 270s không phải cơ chế trong repo. | Adapter start/inspect/cancel, bootId/PID/start identity hoặc container epoch; output/exit receipt, scope và budget. | Executor mất, cancel chưa ack, PID/container đổi; giữ unknown thay giả running. |
| Vector search / embeddings / reranker | ID/index/literal search đủ cho gap hiện tại; chưa có số đo cần vector service. | Benchmark truy vấn history thật; thử FTS trước; giữ ACL/provenance trước retrieval. | Đo recall/latency/dung lượng và leak giữa dự án. |
| Async compaction / hot-swap / model compactor riêng | Nén đồng bộ hiện có số đo/fallback; đặc tả không chứng minh async. | Chỉ xem xét khi đo được nút thắt; versioned snapshot và atomic context boundary. | Steer/tool/result tới lúc compact, stale swap, summary fail, không mất receipt. |
| Auto-delete hoặc retention theo thời hạn | Trái lựa chọn warning + user confirm. | Chỉ thêm sau user chọn policy; bảo vệ active tasks, capsule và referenced blobs. | Không xóa task đang chạy; không mất critical evidence; rollback/cancel rõ. |
| Memory global / tìm liên dự án | Dễ trộn mục tiêu và dữ liệu. Chưa cần cho cùng dự án. | Explicit allowlist và project binding; memory không cấp quyền. | Guessed IDs, secret labels, forged project path, consent revocation. |
| Knowledge library lớn/tự promotion | Capsule nhỏ đã đáp ứng chuyển tiếp; chưa cần hệ thống tri thức riêng. | Optional fact/problem/lesson có conditions, asOf, verified evidence và supersedes; hypothesis là candidate. | Live evidence khác mốc cũ; raw bị xóa; không biến lesson thành command. |
| Sync/backup nhiều máy và power-loss guarantee | Chưa kiểm storage/PRAGMA/filesystem cho cam kết này. | Export/import có hash, ACL, version và restore rehearsal; remote sync cần thiết kế riêng. | Mất điện/storage fault, conflict nhiều writer, recovery từ backup, data isolation. |
| Path ACL/file lock tổng quát cho peer | Contract/claim không chứng minh OS isolation; registry đã có cursor. | Nếu cần, executor scope enforcement/platform isolation riêng; claim chỉ advisory. | Concurrent writes, escape qua shell, lock expiry, stale holder. |
| Dashboard, PR connector và report service mới | F16/F17 outer tools không cần clone để giữ refs. | Tái dùng UI hiện có và work checks/ships; chỉ mở rộng khi có nhu cầu riêng. | Không tạo report/PR lặp qua restart; state không nhầm với chat finish. |
| Lossless hidden CoT / exactly-once external effects | Không thể suy từ log có reasoning hoặc unique DB index. | Không hứa; lưu provider-visible output và committed receipts, ambiguous effects cần user inspect. | Fault injection quanh tool_start/tool_end; không chạy effect lần hai để “thử”. |

Nếu người dùng không duyệt phần longtask opt-in, giữ manual resume. Kế hoạch đã được duyệt nên phần budget tổng/completion adapter đã có mã (§11); phần chưa nối vào bộ điều khiển nào vẫn phải giữ ở dạng báo `needs_user` kèm lý do, không được đoán. Các sửa hardening cũng phải tuân phạm vi kế hoạch được duyệt.

## 9. Kiểm chứng bắt buộc trước khi gọi là tác vụ dài tin cậy

1. Ít nhất 20 lần nén cho main và worker; thêm >60 journal rows; mục tiêu/decision đầu phiên và failed evidence giữa log vẫn truy xuất đúng.
2. Summary bị cắt hoặc thất bại không làm mất contract gốc, revision mới nhất hoặc việc chưa xong. Synthetic history không trở thành user instruction.
3. Search >200 match nhiều nguồn trả thứ tự đúng, cursor không bỏ/lặp, self/project scope và full ID collision đúng.
4. Kill harness ở khe hỏi/đáp, child_finish/project_child, tool_start/tool_end/save, budget exhausted và continuation admission. Receipt/decision phục hồi đúng, unsafe không tự replay.
5. Hết budget qua nhiều lượt/child/retry/restart không reset; chỉ một card; user cộng delta đúng một lần.
6. Model trả final khi việc còn runnable/blocked hoặc tests failed/stale không làm task completed. Plan-only không bị ép commit/deploy.
7. Tạo capsule rồi xóa/restart/mở phiên mới: critical state và lesson còn; raw refs đã xóa trả tombstone; không carry approvals.
8. Disk-full/checksum/commit/extraction fail trước verified capsule không xóa raw hoặc báo stored giả. Cleanup sau confirm đúng operation.
9. Kiểm ngưỡng byte sát 4 GB và 5 GB; DB/WAL/projection/capsule counted rõ; warning không tự xóa. SQLite freelist không đồng nghĩa đã thu hồi physical bytes.
10. Matrix host/Docker/standard cùng semantics; Windows/Wayland/process reattach không được báo verified chỉ từ fixture Linux.

Khảo sát đã chạy các nhóm test hiện có: runtime audit 43 + 519 + 44; worker audit 212 + 143 + 161 + 86. Có suite giao nhau; **không cộng thành coverage độc lập** hoặc gọi đó là kiểm thử tính năng đề xuất. Lỗi baseline phải tách khỏi regression mới. Test phục hồi dùng subprocess/DB/workspace tạm, không kill dịch vụ đang phục vụ người dùng.

## 10. Bản đồ F01–F31 để tránh bỏ sót hoặc sao chép quá mức

| Đặc tả | Quyết định |
|---|---|
| F01/F02 | Reuse checkpoint; bổ sung host/full-readable projection và raw refs ở nơi thiếu. |
| F03/F04 | Reuse structured summary/brief; bổ sung critical pins và provenance, không clone continuation user message. |
| F05/F06 | Phân biệt raw với task journal; reuse call/result IDs và receipts. |
| F07/F08/F09 | Bổ sung project search/range read/spill pointers; reuse output/artifact đã có. |
| F10/F11 | Reuse plan-review gates; bổ sung pending decision durability và critical decision refs. |
| F12/F18 | Reuse workspace binding/tool recovery; revalidate live state trước safe continuation. |
| F13/F14 | Reuse task/job registry; sửa orphan attempt. Process-start generic để sau. |
| F15 | Reuse artifacts; định nghĩa retained/deleted/missing và dung lượng rõ. |
| F16/F17 | Giữ check/PR IDs, refs và phiên bản; không clone outer services. |
| F19/F20 | Archive đúng agent; reuse child task contract, thêm owner revision pins nơi cần. |
| F21 | Task list đã phân trang; không tái tạo response peer khổng lồ hoặc giả claim là lock. |
| F22/F23 | Giữ lỗi/pending/evidence và tools đọc lại; không dùng lời “đã xong” thay nghiệm thu. |
| F24/F25 | Đây là rủi ro phải tránh: sai namespace và handoff echo, không phải feature để sao chép. |
| F26/F27 | Reuse steers; provenance/revision và conflict gate, không coi mọi message cuối là authority. |
| F28/F29 | Evidence có asOf/hash/environment; test không làm gián đoạn service; module khác live. |
| F30 | Reuse durable job semantics; output refs thống nhất; không clone foreground270s. |
| F31 | Capsule lesson nhỏ là cần; knowledge library rộng là optional/hoãn. |

**Nguyên tắc cập nhật:** khi một mục triển khai/kiểm chứng, ghi mốc mã, command/evidence và giới hạn thực tế. Khi bỏ qua, giữ lý do và điều kiện xem xét lại. Không đổi “đề xuất” thành “đã có” chỉ vì kế hoạch được duyệt.

## 11. Trạng thái triển khai tại `fc964d8`

Bốn commit trên nhánh `vorflux/host-mode-web-transport`: `b28cade` (kho lịch sử), `9743ba8` (chạy/khôi phục tác vụ dài), `cd2daf4` (bề mặt API), `fc964d8` (giao diện). Kiểm cục bộ: `pytest` 333 passed cho 14 tệp đơn vị liên quan (gồm `test_history_store.py`, `test_history_surface.py`, `test_longtask_execution.py`), `deploy/docker/tests/test_session_files.py` 32 passed, `tsc -b --noEmit` 0 lỗi và 20 ca continuity phía frontend.

| Thiếu sót | Trạng thái | Mốc mã / bằng chứng | Giới hạn còn lại |
|---|---|---|---|
| LT-01 ghim mục tiêu/decision | Đã có | `memory/history_store.py` (`owner_contract_revisions`, `contract()`, `critical_pins()`), `agent_core/session_journal.py` (`critical_pins_block`, ghép TRƯỚC khối ký ức), `history_surface._critical_snapshot` | Khối ghim chỉ dựng khi `BOXFOX_LONGTASK_CONTINUITY=1` (cờ tắt ⇒ prompt y như cũ). Trần 1.200 ký tự: yêu cầu gốc ≤600, các revision sau ≤160 kèm `recordId` để đọc đầy đủ bằng `history_read`. Neo canonical cần ít nhất một yêu cầu chủ đã ghi (revision ≥ 1); phiên chưa từng nhận yêu cầu thì không có mốc nào để ghim. |
| LT-02 archive host đọc được | Một phần | `memory/history_projection.py`, `history_files.py`; `history_surface.export_projection` | Chưa có ai gọi `export_projection` từ runtime; workspace Docker/chưa ghim trả `projectionStored: false` thay vì ghi sai. |
| LT-03 card hỏi đáp bền | Đã có | `agent_core/decision_store.py`, `runtime.hydrate_decisions/pending_decisions/resolve_decision`, route `GET/POST .../decisions` | Chưa kiểm với provider thật; idempotency theo `invocationId` + `expectedRevision`. |
| LT-04 tìm giữa các phiên | Đã có | `history_store.query_history/list_sessions`, route `GET /history/sessions|search`, `scope_target` | Cursor ký theo filter; coverage `partial` khi bị cắt. Chưa đo recall trên >200 match thật. |
| LT-05 con trỏ output dài | Đã có | blob + segment có sha256 trong `history_store`; `history_read` phân trang | Chỉ giữ excerpt text đã checksum trong capsule; artifact nhị phân không được sao chép. |
| LT-06 child xong mà attempt còn mở | Đã có | `task_service._close_attempt_locked`, `task_surface.reconcile_startup/finish_child`, `peer_watchdog` | Chưa có ca kill thật ở khe `child_finish`; chỉ mô phỏng ở mức đơn vị. |
| LT-07 main tự tiếp tục | Đã có (opt-in) | `agent_core/longtask_store.py`, `longtask_runtime.py`, `runtime.configure_longtask/longtask_action/recover_longtasks/pump_longtasks` | Bật bằng `BOXFOX_LONGTASK_CONTINUITY=1`; run gắn plan/work chưa có seam `controller_continue` nên dừng ở `needs_user` + `LONGTASK_CONTROLLER_UNAVAILABLE`. |
| LT-08 xoá có mang theo | Đã có | `history_store.deletion_preview/delete_with_capsule`, `history_surface.settle_deleted_runs`, route preview/confirm, `DELETE` cũ trả 409 | `settle_deleted_runs` chạy trước cổng quiescent, nên ca `DELETE_NOT_QUIESCENT` vẫn đã huỷ run; cần đảo thứ tự ở vòng sau. |
| LT-09 summary lồng nhau | Một phần | `history_store.prepare_compaction/commit_compaction` + manifest theo `source_key`, `agent_id`; `restore_compaction` | **Chưa nối vào đường nén sống**: `runtime.py` vẫn chỉ ghi checkpoint cũ, nên manifest chỉ sinh trong ca kiểm. Đây là lựa chọn có ý thức của đợt này (đổi đường ghi canonical giữa lượt nén cần một vòng kiểm riêng, không vá ở cuối chu kỳ). Chưa đo trên chuỗi >20 lần nén thật ở host; ca đơn vị đã phủ ≥20 lần. |

### 11.1 Giới hạn đã biết sau đợt soát mã

Ghi lại đúng những gì **chưa** làm, để vòng sau không phải suy lại từ đầu:

| Việc | Vì sao hoãn | Điều kiện xem xét lại |
|---|---|---|
| Nối `prepare_compaction`/`commit_compaction` vào đường nén sống | Đổi bản ghi canonical của mọi lần nén; cần vòng kiểm riêng + đo dung lượng trên phiên thật | Trước khi bật `safe_auto` cho phiên dài thật |
| `export_projection` (archive host đọc được) | Chưa có người gọi; workspace Docker trả `projectionStored: false` thay vì ghi sai — trung thực nhưng chưa dùng được | Cùng vòng với việc nối compaction |
| Nhãn IFC: `_allowed` truyền `labels` cho hook, hook đang bỏ qua và runtime chưa từng gắn nhãn | Chưa có nguồn nhãn thật; gắn nhãn rỗng là giả vờ có kiểm soát | Khi có nguồn nhãn (dự án/người dùng) |
| `recover()` không thử lại khi khởi động lỗi tạm thời | Hỏng lúc boot thì `pump()` từ chối nhận continuation; chủ vẫn chạy tay được | Khi có ca thật cần tự chạy tiếp ngay sau boot |
| `search_text` giữ nguyên văn payload cạnh blob (ba bản cho output lớn) | Đo dung lượng đã có; chưa phải điểm nghẽn trên máy chủ nhà | Khi cảnh báo dung lượng bắt đầu nổ |
| `history_files.py` chỉ chạy POSIX (`O_DIRECTORY`/`dir_fd`/`O_NOFOLLOW`) | Host Windows là nền chính của bản desktop; ở đó ghi lịch sử hỏng và `history_ingest` bỏ qua ⇒ tính năng chết ở tầng file | Trước khi phát hành tính năng này cho host Windows |
| `work_feedback.py` vẫn đóng child không nguyên tử (`child_finish` + `project_child` hai bước) | Ngoài phạm vi đợt này; khe hở đã có reconcile lúc khởi động/bơm | Cùng vòng với LT-06 ở bề mặt work |
| `ProfileWriterGuard` chỉ bật cùng cờ tác vụ dài | Chế độ mặc định giữ nguyên hành vi cũ (không khoá profile) | Khi làm supervisor sau reboot (§8) |

Phần hoãn giữ nguyên như §8: supervisor sau reboot, durable shell/process job tổng quát, vector search, async compaction, auto-delete theo hạn, memory liên dự án, knowledge library lớn, sync nhiều máy, path ACL tổng quát, dashboard/PR connector, lossless CoT. Windows/Wayland vẫn chỉ có kiểm đơn vị với platform giả.
