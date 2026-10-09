# HANDOFF — BoxFox Agent Box

**Đọc tệp này trước.** Đây là bản bàn giao hiện hành, viết cho agent (hoặc người) tiếp nhận công việc.
Mọi handoff cũ đã gom về [`docs/handoff/`](docs/handoff/README.md) — mục lục đầy đủ nằm ở
[`docs/handoff/README.md`](docs/handoff/README.md); không cần đi tìm ở chỗ khác.

- **Nhánh:** `vorflux/host-mode-web-transport` (HEAD `f2b1129`, 85 commit trên `main`, `main` không có
  gì mới hơn).
- **Pull request:** https://github.com/khaiv7221-ops/BoxFox-Agent-Box/pull/1 — **PR duy nhất** của repo,
  đang mở, không phải draft.
- **Cập nhật lần cuối:** 2026-10-09, sau đợt kiểm thử đầu-cuối tác vụ dài (34 lượt sống, hai pha).

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

## 3. Mười tám lỗi harness đã sửa trong nhánh

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

## 4. Việc còn mở (đã ghi nhận, chưa sửa)

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

## 5. Chạy lại môi trường (đã dùng cho đợt cuối)

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

## 6. Kiểm thử

- `backend/tests/unit/` — các tệp liên quan đợt này: `test_history_surface.py` (32 passed),
  `test_longtask_execution.py`, `test_await_children.py`, `test_work_budget_w65.py`.
- Router: `npm test` trong `router/` — **328 passed**.
- Báo cáo kiểm thử của phiên: mục "What was tested" (bản 16, `PARTIAL`, coverage `16/20`).
- Bản sửa F17 được kiểm chứng thêm bằng cách chạy lại trên **bản sao** DB sống: trước bản sửa
  `acceptanceSatisfied: False` kèm `LONGTASK_ACCEPTANCE_REQUIRED`; sau bản sửa `True`, `failedChecks: []`.

## 7. Những điều dễ vấp (đã tốn thời gian thật)

- **Đừng commit** ba tệp chưa theo dõi dùng cho preview: `deploy/docker/docker-compose.preview.yml`,
  `frontend/vite.preview.config.ts`, `router/package-lock.json`.
- **Cuối dòng hỗn hợp:** `plan_quality.py`, `test_plan_sources_gate.py`, `compression.py`,
  `test_compression_port.py`, `test_tail_and_summary_floors.py` là CRLF; `longtask_runtime.py`,
  `runtime.py`, `longtask_store.py`, `api/server.py`, `limits.py`, `test_longtask_execution.py`,
  `test_await_children.py`, `test_work_budget_w65.py` là LF; `router/src/engine.mjs` trộn 218 CRLF/225
  dòng — sửa bằng script giữ nguyên kiểu cuối dòng.
- **Thân PR không được chứa** đường dẫn `/code/...` (bước chuẩn bị media của `pr edit` sẽ từ chối) và
  không được chứa dấu quản lý `VORFLUX_AGENT_PR_BODY`.
- Đồ thị việc: **mọi** `work_graph action=update` làm reset toàn bộ stage ⇒ node đã `accepted` bị mở lại.
  Muốn thêm yêu cầu cho con thì dùng `action=verify` hoặc lệnh trong goal, đừng update định nghĩa node.
- `mimo-v2.6-flash-free` từng chết vì hạn 90 s (F15); nay đã sửa, nhưng nếu thấy `chat.failed TIMEOUT`
  thì nâng `max_tokens` ≥ 8.000 hoặc đổi model.

## 8. Việc nên làm tiếp

1. Sửa **X1** và **X3** (cổng nghiệm thu + nút nghiệm thu trên UI) — hai việc nhỏ, đóng được vòng
   nghiệm thu mà đợt cuối phải làm bằng tay.
2. Bốn ca A còn `not-triggered` (A3 hai hội thoại song song, A5 `task_send`, A7 phiên unbound/container,
   A8 đổi model giữa run) — dựng ca chủ động trên harness phụ như đã làm với V3/V6.
3. Cân nhắc `2ab` (ngân sách tính trọn bound) vì nó chạm trần ngân sách thật của mọi run fan-out.
4. Gộp/tách PR nếu cần: hiện chỉ có **một** PR (#1), 85 commit trên `main`.
