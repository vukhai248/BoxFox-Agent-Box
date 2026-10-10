# HANDOFF — BoxFox Agent Box

**Đọc tệp này trước.** Đây là bản bàn giao hiện hành, viết cho agent (hoặc người) tiếp nhận công việc.
Mọi handoff cũ đã gom về [`docs/handoff/`](docs/handoff/README.md) — mục lục đầy đủ nằm ở
[`docs/handoff/README.md`](docs/handoff/README.md); không cần đi tìm ở chỗ khác.

- **Nhánh bàn giao:** `main`, repo `https://github.com/vukhai248/BoxFox-Agent-Box.git`.
  Checkpoint local được làm trên `codex/desktop-startup-fix`; owner yêu cầu đưa lên main.
  Baseline main trước đợt local: `ff59af8f` (merge PR #13).
- **Commit cần đọc:** `b9b0d60f` (web history), `d5ad6139` (stream), `dc60c43f`
  (3 mức quyền), `2e686820` / `4871791f` (router/cổng), `1d1ef528` (startup/lock/hooks).
- **Pull request lịch sử của cloud:** https://github.com/khaiv7221-ops/BoxFox-Agent-Box/pull/1.
  Metadata nhánh/PR trong các mục 1–9 phía dưới là bối cảnh đợt cloud 2026-10-09,
  không phải trạng thái Git hiện tại. Xác minh branch/HEAD thật trước khi làm.
- **Cập nhật lần cuối:** 2026-10-10 (UTC+7), sau khi owner báo lỗi vẫn còn và sub đứng.

## 0. Bàn giao local mới nhất — ưu tiên đọc trước

### Trạng thái: CHƯA NGHIỆM THU luồng sub-agent

Owner thử **web dùng chung backend desktop** tại `http://localhost:3110/` sau
`b9b0d60f`, báo rằng **vẫn bug, và sau bản sửa sub-agent đứng, không hiện output**.
Không được diễn giải 217 test xanh thành đã sửa xong ca chạy thật.
Agent tiếp nhận cần kiểm từ request/provider → runtime/tool → event bền → API phân trang
→ store/poll → panel; tách lỗi thực thi khỏi lỗi quan sát trước khi kết luận.

**Phạm vi owner hiện tại:** tối ưu bản web trước, chưa build bộ cài mới. Long task
được bàn giao cloud làm riêng; phần setup bằng tay chưa được local sửa. Không thay
kiến trúc điều phối/quyền để chữa lỗi hiển thị. App giữ tiếng Anh.

### Phải đọc file chi tiết trước khi quyết định hoặc sửa

| Tài liệu | Dùng để hiểu |
| --- | --- |
| [`docs/plan/web-subagent-history-fix-2026-10-10.md`](docs/plan/web-subagent-history-fix-2026-10-10.md) | Bản sửa `b9b0d60f`, bằng chứng đọc event, cách chạy web chung gateway, giới hạn phép kiểm và báo lỗi mới của owner. |
| [`docs/plan/desktop-stream-duplication-fix-2026-10-10.md`](docs/plan/desktop-stream-duplication-fix-2026-10-10.md) | `d5ad6139`: delta/snapshot/canonical thought/text, phân biệt duplicate receipt với hai bước model thật. |
| [`docs/plan/desktop-router-port-fix-2026-10-10.md`](docs/plan/desktop-router-port-fix-2026-10-10.md) | Ping Settings và chat lệch endpoint; profile router/cổng và bằng chứng packaged-path. |
| [`docs/plan/desktop-permission-levels-2026-10-10.md`](docs/plan/desktop-permission-levels-2026-10-10.md) | 3 mức Request approval / Auto approve / Full access; Network độc lập; project trust và CUA riêng. |
| [`docs/plan/desktop-startup-fix-2026-10-10.md`](docs/plan/desktop-startup-fix-2026-10-10.md) | Lock stale/PID reuse, close/tray/Quit, hook Windows và lag sau khi UI hiện. |
| [`docs/handoff/desktop-host-mode-handoff.md`](docs/handoff/desktop-host-mode-handoff.md) + các plan nó trỏ tới | Kiến trúc host/Docker, CUA và phần còn mở; mô tả quyền cũ bị checkpoint 3 mức thay thế. |
| Các mục 4–9 bên dưới + source/tests/evidence được trỏ tới | Lỗi harness/long task cloud đã sửa và việc chưa xong; không coi đường dẫn `/var/tmp` là đã có ở clone mới. |

### Các lỗi đã thấy và trạng thái bàn giao

| Mã local | Triệu chứng / yêu cầu | Đã làm và việc còn lại |
| --- | --- | --- |
| L01 | Mới mở laptop, app báo đã chạy (`desktop.lock`, PID có thể cũ); close/reopen không đúng kỳ vọng. | Có patch `1d1ef528` và probe; xem docs startup. Owner báo lỗi cũ có vẻ tạm mất; chưa gọi là nghiệm thu mọi lifecycle/upgrade. X chỉ ẩn/tray khác Quit. |
| L02 | UI hiện rồi khoảng 5 giây mới lag chuột/có thể toàn máy, delay 6–7 giây. | Đã xử lý/đo hook và startup trong checkpoint trên. Chưa chứng minh nguyên nhân duy nhất hay hiệu năng mọi máy; không gộp với thời gian chờ mở app. |
| L03 | Ping model trong Settings được, chat lỗi `UPSTREAM_UNREACHABLE`; đóng app sang Windows có cổng/config khác web/cloud. | Patch router `2e686820`, probe `4871791f`; đọc report đúng commit. Không mặc định quy mọi lỗi mới cho quota/provider. |
| L04 | `JOURNAL_DEGRADED … PROJECT_TRUST_REQUIRED` vẫn hiện khi chọn Full access. | Chưa sửa journal. Mức duyệt, trust folder, root lưu nội bộ và catalog journal là các tầng riêng. Cần trace `session_ensure`/journal/checkpoint tới executor và project/session binding; không tự trust mọi folder hay bỏ guard. |
| L05 | Thought/text bị lặp; người dùng thấy hai khối giống nhau. | Patch `d5ad6139` giảm publication lặp và reconcile theo model step; có fixtures. Nội dung giống ở hai step thật không được xóa. Nghiệm thu live tổng thể vẫn mở. |
| L06 | Sub trả kết quả nhưng internal feedback/reasoning không hiện, hiển thị thiếu; main nhận lượt 2 thì mất tiếp. | `b9b0d60f` sửa phân trang, cache, poll race, receipt cùng child và giữ reasoning đang mở. **Owner báo vẫn bug**, chưa giải quyết trọn vẹn; cần tái lập thật, không chỉ test fixture. |
| L07 | Sau patch L06, owner thấy sub đứng, chỉ còn placeholder processing và RUNNING. | **MỚI, CHƯA XÁC ĐỊNH NGUYÊN NHÂN.** Đọc chi tiết ngay bên dưới; kiểm regression trước khi thêm patch. |
| L08 | Long task phải bấm Set up long task / nhập recovery/budget bằng tay, chưa đúng kỳ vọng main tự điều phối. | Local chưa đụng; owner giao cloud. Đọc plan/source và các vấn đề long task dưới đây; thay đổi workflow/quyền cần trình owner duyệt. |
| L09 | Harness nói Explore thiếu `terminal_exec`, child bị cancelled sau ít bước dù main giao maxSteps 18/20. | Đây là báo cáo của model, không phải nguyên nhân đã xác minh. Kiểm role catalog thực nhận, parent/child budget/deadline/cancel receipts và path/caller identity. Không tự mở shell cho Explore hoặc tin cancelled là đã dùng hết bước. |

### L07 — ảnh mới của owner, thông tin để tái lập

- Ảnh ngày 2026-10-10: web `localhost:3110`, Host/IDE, project
  `agentic-RAG-for-e-commerce`, UI session prefix `5d4454af`, model hiển thị
  `step-5-preview-f…` (ảnh không cho toàn bộ model ID).
- Ba hàng Explore Specialist đều hiển thị **lượt 1 · bước 5**. Hàng thứ hai được chọn;
  Output chỉ có `Specialist is processing instructions autonomously in the sandbox…`,
  footer `RUNNING`, không có nội dung tool/thought/result. Nhãn sandbox ở Host cũng
  cần rà độ chính xác, nhưng không dùng nhãn đó để suy executor thực tế.
- Main có receipt `work_graph create`, run `w-49bc13ec17`, trạng thái `drafting`,
  `autopilot: false`, `nodes: []`, `waves: []`; trên UI có Running commands (3).
  Đây là trạng thái nhìn thấy trong ảnh, không chứng minh scheduler/provider deadlock.
- Một lần đọc danh sách session qua web 3110 khi viết handoff không thấy prefix
  `5d4454af`. Chưa đối chiếu được UI chat ID với harness ID / profile / giới hạn listing.
  Không coi việc không tìm được prefix là bằng chứng session không tồn tại hay mất DB.
- Owner nói đứng **sau** patch; quan hệ nhân quả chưa được chứng minh. So sánh
  `b9b0d60f` với trước patch `0a19597b` và trước stream patch `02dc2df4` trên
  profile/fixture riêng. Không rollback/xóa dữ liệu đang dùng để tạo một ca đẹp.

### Cloud cần kiểm tiếp theo

1. Xác minh commit/source **đang chạy** của UI, gateway, harness, router; local web
   nạp source mới nhưng backend từ app đã cài. Dùng cùng source/backend/profile cho
   ca đối chiếu. Clone mới không có app/profile/evidence riêng của Windows owner.
2. Map UI chat ID → harness ID → child IDs/run/turn. Lấy hai snapshot có timestamp,
   event cursor và liveness để biết thực sự không tiến triển hay UI không tải được.
   Kiểm Network/Console: request bị abort liên tục, HTTP error, cursor loop, polling
   bị dừng, exception render; không giấu lỗi dưới placeholder processing.
3. Đối chiếu child durable events (đầy đủ mọi trang), assistant/thought/tool receipts,
   status/updateSeq, resume cùng child qua lượt 2, main `await_children`/handoff receipt,
   caller binding, runtime task registry, provider stream và deadline/budget/cancel.
   Có event mà UI thiếu ⇒ sửa reader; chưa có event ⇒ trace execution/provider trước.
4. Audit `b9b0d60f`: effect phụ thuộc receipt, abort/restart fetch, cursor validation,
   cache, selected/pinned turn, stale refresh guard và hydration dài hơn nhịp poll.
   Audit `d5ad6139`: step boundary, delta/tail/snapshot/final reconciliation. Không
   xóa reasoning thật hoặc đổi quyền/DAG để làm UI trông đã hoàn thành.
5. Regression cần có ca model/tool thật: main + fan-out 3 children → deliver cuối →
   đọc reasoning → gửi lượt 2 → resume cùng child; thêm lịch sử >500 event, đổi child,
   slow request/abort/API lỗi. Ghi source/commit/model/OS/config, expected/actual,
   log/event refs và failures. Test Linux/DOM không thay nghiệm thu Windows/owner.
6. Không gọi cloud có đủ tool là đã đủ bằng chứng: thiếu bundle/profile/runtime hoặc
   không tái lập được phải báo rõ. Không commit API key, admin token, DB/session content.
   Đọc DB bằng SQLite **mode=ro**, không khởi tạo SessionStore trên DB sống.

### Đường chạy và bằng chứng local

- `scripts/start-web-desktop.ps1 -WebPort 3110` đọc gateway từ machine.json của desktop,
  không in token. Ở lần đo trước: 3110 → gateway 64557 → router 64558 / harness 64559.
  Desktop phải còn mở. 3100 là stack standalone khác; không dùng 3100 để khẳng định
  cùng profile với desktop. Cổng kể trên là số đo, không phải cấu hình cứng.
- `b9b0d60f`: **217 test / 22 file + typecheck + lint đạt**, HTTP đọc cùng events và
  cursor qua web/gateway. Parent cũ `7379d11f…` có 7.421 event/15 trang; hai child
  trong ảnh cũ vẫn lưu reasoning cuối 400/150 ký tự. Không phải evidence của L07.
- Không chạy model sống hay nghiệm thu browser thật ở checkpoint đó; browser tool
  không khởi tạo được. Không dựng installer mới sau patch web. Vì owner đã tái hiện
  lỗi, trạng thái acceptance hiện tại là **OPEN / FAILED theo báo cáo owner**.
- Bộ cài trước đó tới 0.1.4 và các SHA/hash/giới hạn kiểm nằm trong docs tương ứng;
  installer, `.tmp` log, profile và DB local **không được đưa lên Git**. Cloud thiếu
  những bằng chứng đó phải nói thiếu, không đoán nội dung.

---

**Các mục 1–9 dưới đây giữ bối cảnh và kết quả cloud 2026-10-09.** Mục 0 trên là
checkpoint hiện hành và thay kết luận "xong" nếu mâu thuẫn với lỗi owner mới báo.

---

## 1. Nhánh này làm gì

Một lớp "host mode" cho BoxFox: harness chạy ngay trên máy chủ thay vì trong container, kèm

- API điều khiển máy (`/api/agent/machine/*`), quyền theo phiên, đích CUA theo phiên (chọn cửa sổ hoặc
  cả máy), viền báo vùng đang bị điều khiển trên X11;
- lớp **tác vụ dài** (long task): một run ghim vào hợp đồng của phiên, ngân sách bước/phút, checkpoint,
  work graph (discover → approve → execute → ship), cổng nghiệm thu của chủ;
- router model: khoá OAuth/API key, chọn model theo alias, hạn chót request theo kích thước thật;
- nén context giữ được việc đang dở qua nhiều thế hệ nén.

## 2. Trạng thái đã xác minh (đợt cuối, 2026-10-09)

Một lượt chạy sống thật, hai pha, đề bài "QC dược":

| Hạng mục | Kết quả |
| --- | --- |
| Phiên chủ | `72106f67490847a9be5b179a5cc92a6c`, 34 lượt, trạng thái `completed` |
| Long task run | `lt-d0422232cc124fe9ae12ca847decb76b` — `completed` rev 163, `blockedReason: null`, 891/4800 bước, 734,1/1920 phút |
| Work graph pha 2 | `w-45bc1f889e` — `executed`, cả hai node `B1` và `T1` **accepted** |
| Sản phẩm pha 2 trên đĩa | `data/spec_registry.json` (3.440 B), `tests/test_spec_registry.py` (1.613 B) trong `/var/tmp/lt-longtask2/ws` |
| Test chạy được | `python3 -m unittest discover -s tests -v` → 4/4 đạt, exit 0 (artifact `a-0790e163407344faaf96e9fe1cae8068` v23) |
| Phán quyết phản biện độc lập | con `3be338ffd4d14334b74d56afec4c72c0` (role `review`), 2 bước, kết `VERDICT: ok` |
| Kiểm thử độc lập | báo cáo `testing` — **PARTIAL, 16/20 dòng**; 12/12 dòng V đạt; A3/A5/A7/A8 và Q2 `not-triggered` |

Báo cáo kiểm thử đầy đủ (34 KB) và cây bằng chứng:
`/code/.generated_artifacts/longtask-e2e/report.md` (mục 5 liệt kê `db/`, `events/`, `files/`, `logs/`,
`matrix/`, `session-history/`, `active-cases-3118/`).

> **Lưu ý về agent kiểm thử:** tiến trình `e2e-verify-chang-b` **hết thời gian chờ 7.200 s** và bị đánh
> dấu `error` **sau khi** đã ghi xong báo cáo và ma trận; phần còn lại không kiểm được là bốn ca A và Q2
> nói trên.

## 3. Bộ cài Windows Desktop (dựng 2026-10-09)

`desktop/` là shell Electron đóng gói cả UI + router + harness + runtime (Node 24.9.0, CPython 3.13.7)
thành một bộ cài NSIS. Bộ cài dưới đây dựng từ chính nhánh này (commit `eba9aad`), nên nó mang đủ F01–F17.

| Hạng mục | Giá trị |
| --- | --- |
| Tệp | `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` — 167.123.853 B, Windows x64, **chưa ký số** |
| SHA-256 | `fa2b965ca102e0797cc93048ce94750b5370f5828281b3a9d2b4938a0a4a077f` |
| Gói bên trong | 5.189 tệp, khớp từng đường dẫn và kích thước với `desktop/release/win-unpacked` |
| Hướng dẫn cài | `docs/plan/desktop-alpha-quickstart.md` + `.en.md` (bản nhanh cho người dùng cuối) và
`docs/plan/desktop-alpha-install.md` + `.en.md` (bản đầy đủ, checklist 13 bước) — mỗi bản có tiếng Việt và tiếng Anh |

Dựng lại (máy Linux vẫn cross-build được):

```bash
cd desktop
npm install
npm run fetch-runtime      # ~190 MB: Node + CPython + wheel win_amd64, kiểm sha256 từng mục
npm run build-app          # cần frontend/dist; tự dựng UI nếu chưa có
DISPLAY=:1 npm run dist:win
```

- **Wine phải chạy được nhị phân 32-bit** (`wine` + `wine32:i386` trên Ubuntu). Thiếu 32-bit thì
  electron-builder dừng ở bước đóng gói uninstaller với `wine process failed ENOENT`, và tệp `Setup.exe`
  để lại chỉ là stub ~167 KB — **không phải** bộ cài thật. Đã ghi vào `desktop/README.md`.
- `npm test` trong `desktop/`: **73/73 đạt**; `npm run fetch-runtime:check`: runtime khớp lock.
- Thư mục cài mặc định là `%LOCALAPPDATA%\Programs\boxfox-desktop`, không phải tên sản phẩm
  (`productName` có ngoặc đơn nên electron-builder dùng `name`); hai tài liệu cài đã sửa cho đúng.
- **Chưa chạy cài đặt thật trên Windows**: máy này là Linux, và workflow `desktop-build.yml` (chạy trên
  `windows-latest`) không gọi được vì token GitHub của phiên không có quyền Actions (dispatch trả 404).
  Bộ cài đã được kiểm tới mức Linux cho phép: giải nén kho NSIS rồi so khớp byte với cây ứng dụng, và chạy
  wizard dưới Wine (wizard hiện đúng; bước giải nén bị chặn bởi cảnh báo "cannot be closed" — dương tính
  giả của `nsProcess` dưới Wine, không tái hiện trên Windows).

## 4. Mười tám lỗi harness đã sửa trong nhánh

Mọi lỗi dưới đây đều tái hiện được trước khi sửa (test đỏ trước, hoặc số đo sống) và đều có ca hồi quy
trừ khi ghi chú khác.

| Mã | Triệu chứng | Commit |
| --- | --- | --- |
| F01 | Lời gọi tool đang chạy tự chặn chính nó bằng ý định của mình (`LONGTASK_UNSAFE_INTERRUPTION`) | `c67ef47` |
| F02 | Con bị từ chối bởi lời gọi đang chạy của cha; rồi run chết `LONGTASK_STALE` | `f7ddaf9` |
| F03 | Fan-out: lời gọi của phiên gốc bị con cháu từ chối oan | `f7ddaf9` |
| F04 | Lời gọi tool bị cắt được phát lại nguyên trạng cho nhà cung cấp → `UPSTREAM_HTTP_400` giết ba lượt | `e90c72e` |
| F05 | Cổng nguồn của plan chỉ đọc trang cũ nhất (500 event) → từ chối plan có nguồn thật | `35830f6` |
| F06 | Mục "Nguồn dữ liệu đầu vào" che mục nguồn thật → `sources-vague` | `03cc20f` |
| F07 | Con của node plan bị giết `ORPHAN` vì hàng phiên cha bị ghi đè giữa lượt | `9020247` |
| F08 | Transcript quá trần 200 message của nhà cung cấp (nén chỉ theo token) | `458b42b` |
| F09 | Bookkeeping của runner (con đóng) giết lượt đang chạy của chủ | `054b432` |
| F10/F11 | `inspect` của chủ bị chính lượt nó mở khoá làm mất hiệu lực | `e1f801d` |
| F12 | Trần tóm tắt nén 4.096 token giết bản nén tác vụ dài | `0011b47` |
| F13a/b | Tắt máy êm bị ghi thành lệnh dừng của chủ; `resume` giữ lại lý do chặn | `c0e04b5` |
| F14 | `await_children` nhận session id trần → cha quay ~100 bước vô ích | `1bfb677` |
| F15 | Hạn 90 s áp cho cả request lớn chỉ vì `max_tokens` nhỏ → hai lượt chủ chết `PROVIDER_STREAM_INTERRUPTED` | `d5c5e69` |
| F16 | `extend` trả run về `ready` nhưng để lại `blockedReason: LONGTASK_BUDGET_EXHAUSTED` | `d9f0293` |
| F17 | Cổng nghiệm thu chỉ nhận `ok|passed`, work graph ghi `pass` → **không** check nào qua được cổng | `f2b1129` |

## 5. Việc còn mở (đã ghi nhận, chưa sửa)

| Mã | Việc | Gợi ý |
| --- | --- | --- |
| X1 | `accept` bị chặn khi run đang `waiting_children` — chủ phải `resume` trước, UI không nói | thêm `waiting_children`-không-con-sống vào tập state hợp lệ, hoặc trả lỗi nói rõ |
| X3 | UI không có nút nghiệm thu (`accept`); cả bốn lệnh nghiệm thu trong lượt đều gọi API tay | thêm nút "Nghiệm thu" + danh sách ref đủ điều kiện |
| 2ab | `reserve_segment` tính trọn `bound_ms` trước; một lời gọi model giữ 120 phút ⇒ con bị từ chối `LONGTASK_BUDGET_EXHAUSTED` trong khi UI ghi 724/960 | trừ dần theo thời gian thật, hoặc không tính bound của lời gọi đang chạy vào hạn mức |
| 2ae | Lượt kết `partial` + `PROVIDER_STREAM_INTERRUPTED` để run đỗ `waiting_children` dù không còn con sống | dọn trạng thái khi lượt kết `partial` |
| 2z | Lượt chết `OUTPUT_CONTEXT_EXHAUSTED` (219.641/256.000); harness không tự nén | tự nén khi vượt ngưỡng (UI đã cảnh báo 86%) |
| 2aa | Router khoá **6 khoá** `opencode` cho một model (`step-5-preview-free`) tới ~6 h | khoá theo khoá, hoặc hạ trần `retryAfterMs` |
| 2y | Panel Decisions đếm lệch server | đọc cùng một nguồn |
| 2t | Cổng `test_proof` so lệnh **byte-for-byte** (thêm `; echo "EXIT=$?"` là fail cứng) | so sau khi chuẩn hoá |
| 2u | Role `review` không chạy được gì trong host mode (`verify_exec` ∈ `DEFERRED_TOOLS`) | hoặc cho phép, hoặc ghi rõ trong hợp đồng |
| 2v | `WORK_SCOPE_TERMINAL_MUTATING` chặn lệnh `;`-ghép chỉ-đọc | nhận diện lệnh ghép |
| 2w | Sửa định nghĩa node làm reset toàn bộ stage của đồ thị | chỉ reset stage liên quan |
| 2ac | Producer chỉ chạy `terminal_exec` không qua được `good_reads` | đã có mẹo ở `acceptance`; nên sửa gốc |
| X17 | Preview tool cắt ở 1.200 ký tự trong khi artifact 1.325 ký tự | nâng trần hoặc nói rõ |

Danh sách đầy đủ (F01–X18) nằm trong mục **Out-of-Scope Feedback** của PR #1 và trong báo cáo kiểm thử.

## 6. Chạy lại môi trường (đã dùng cho đợt cuối)

```bash
# harness (host mode) — cổng 3116, dữ liệu và workspace riêng
bash /var/tmp/lt-longtask2/restart-3116.sh      # BOXFOX_* env ở đầu tệp
# router: cổng 3101 · UI dev: cổng 3117 · UI desktop app: 3100
```

- `/api/agent/*` (trừ `/health`) cần hai header: `X-BoxFox-Admin: 1` và `Origin: http://localhost:3117`.
- Gửi lượt: `POST /api/agent/sessions/{sid}/turns` body `{prompt, route, invocationId}`.
- Thao tác long task: `POST /api/agent/sessions/{sid}/longtask/actions` body
  `{action, runId, expectedRevision, invocationId}` (thêm `confirm: true` + `evidenceRefs` cho `accept`).
- **Đọc DB sống thì mở read-only** (`sqlite3.connect('file:…?mode=ro', uri=True)`); **không** mở bằng
  `SessionStore` từ script dò — hàm khởi tạo của nó quét phục hồi và đánh dấu phiên `running` thành
  `interrupted`. `sqlite3` CLI không có trên máy này; dùng `backend/.venv/bin/python`.
- Model: `step-5-preview-free` và `longcat-2.5-preview-free` có thể bị khoá theo khoá/quota; thứ tự
  thay thế: `mimo-v2.6-flash-free` → `muse-spark-1.3-contributor-free` → `nemotron-3.5-lightning-free`
  → `ling-1.13-free` → `space-bunny-free`. Mọi lượt phải mang đủ `route`
  (`connectionId f6eef1e6-5fc3-47a9-bf14-34fa02e434a8`).

## 7. Kiểm thử

- `backend/tests/unit/` — các tệp liên quan đợt này: `test_history_surface.py` (32 passed),
  `test_longtask_execution.py`, `test_await_children.py`, `test_work_budget_w65.py`.
- Router: `npm test` trong `router/` — **328 passed**.
- Báo cáo kiểm thử của phiên: mục "What was tested" (bản 16, `PARTIAL`, coverage `16/20`).
- Bản sửa F17 được kiểm chứng thêm bằng cách chạy lại trên **bản sao** DB sống: trước bản sửa
  `acceptanceSatisfied: False` kèm `LONGTASK_ACCEPTANCE_REQUIRED`; sau bản sửa `True`, `failedChecks: []`.

## 8. Những điều dễ vấp (đã tốn thời gian thật)

- **Đừng commit** ba tệp chưa theo dõi dùng cho preview: `deploy/docker/docker-compose.preview.yml`,
  `frontend/vite.preview.config.ts`, `router/package-lock.json`.
- **Cuối dòng hỗn hợp:** `plan_quality.py`, `test_plan_sources_gate.py`, `compression.py`,
  `test_compression_port.py`, `test_tail_and_summary_floors.py` là CRLF; `longtask_runtime.py`,
  `runtime.py`, `longtask_store.py`, `api/server.py`, `limits.py`, `test_longtask_execution.py`,
  `test_await_children.py`, `test_work_budget_w65.py` là LF; `router/src/engine.mjs` trộn 218 CRLF/225
  dòng — sửa bằng script giữ nguyên kiểu cuối dòng.
- **Cross-build bộ cài Windows trên Linux cần wine 32-bit** — xem mục 3; thiếu nó thì `dist:win` báo
  thành công giả với một stub 167 KB.
- **Thân PR không được chứa** đường dẫn `/code/...` (bước chuẩn bị media của `pr edit` sẽ từ chối) và
  không được chứa dấu quản lý `VORFLUX_AGENT_PR_BODY`.
- Đồ thị việc: **mọi** `work_graph action=update` làm reset toàn bộ stage ⇒ node đã `accepted` bị mở lại.
  Muốn thêm yêu cầu cho con thì dùng `action=verify` hoặc lệnh trong goal, đừng update định nghĩa node.
- `mimo-v2.6-flash-free` từng chết vì hạn 90 s (F15); nay đã sửa, nhưng nếu thấy `chat.failed TIMEOUT`
  thì nâng `max_tokens` ≥ 8.000 hoặc đổi model.

## 9. Việc nên làm tiếp

1. Sửa **X1** và **X3** (cổng nghiệm thu + nút nghiệm thu trên UI) — hai việc nhỏ, đóng được vòng
   nghiệm thu mà đợt cuối phải làm bằng tay.
2. Bốn ca A còn `not-triggered` (A3 hai hội thoại song song, A5 `task_send`, A7 phiên unbound/container,
   A8 đổi model giữa run) — dựng ca chủ động trên harness phụ như đã làm với V3/V6.
3. Cân nhắc `2ab` (ngân sách tính trọn bound) vì nó chạm trần ngân sách thật của mọi run fan-out.
4. Chạy bộ cài trên Windows thật (hoặc bật workflow `desktop-build.yml` trong tab Actions) để đóng
   checklist 13 bước của `docs/plan/desktop-alpha-install.md` — đây là phần duy nhất của bộ cài chưa
   được kiểm trên hệ điều hành đích.
5. Gộp/tách PR nếu cần: hiện chỉ có **một** PR (#1), 87 commit trên `main`.
