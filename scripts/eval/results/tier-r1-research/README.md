# Kết quả thô — tầng R, bộ ca research R1–R12 (oracle máy)

**Ví dụ dựng tay, KHÔNG phải lượt thật:** dòng duy nhất trong `scores.jsonl` sinh từ
`fixture-workspace/` (tên miền `.example`), không phải kết quả của một lượt research.
**CHƯA CHẠY một lượt research thật nào và CHƯA CHẠY một lượt benchmark research nào** — bất biến
F19. Muốn có số **đo được** thì phải có một máy có model + box: một lượt research thật sinh
`.research/**`, rồi chạy `research_scores.py` trên phòng hồ sơ đó. Đường `--execute` nay đã gọi
`runner.run_scenario` thật (P0a), nhưng **chưa lượt nào được chạy**; xem `scripts/eval/README.md`.

Bộ ca và oracle là việc của `docs/plan/v27/subplans/flow.md` §7 (C-7) cộng bốn ca R8–R12 của
`docs/plan/v27/research-rework.md` §5; năm số của mỗi ca ở flow §7.3.

| Tệp | Nội dung |
|---|---|
| `manifest.json` | ghim commit BoxFox, trạng thái cây làm việc, sha256 của oracle/rubric/fixtureset + 12 fixture, phiên bản runtime — chưa ghim provider/model (không có lượt gọi model nào) |
| `cases.jsonl` | 12 ca R1–R12 lấy thẳng từ `scripts/eval/fixtures/R*.json`: mạng, trần bước, oracle máy của ca, tên năm số. **Đây là danh sách ca, không phải kết quả**: không dòng nào có `passed`/`failed` vì chưa chạy lượt nào |
| `scores.jsonl` | **một** dòng điểm, `source` ghi rõ `ví dụ dựng tay (không phải lượt thật)`, đo trên phòng hồ sơ giả bên dưới |
| `fixture-workspace/` | ví dụ dựng tay: `.research/bao-hiem-y-te-ho-gia-dinh/` với `v1-…md` + `sources.jsonl` + `sources.md`, đúng hình dạng op `dossier_write` ghi ra (`backend/src/agentbox/sandbox/worker.py`) |

## Chạy lại được

```bash
./.venv/bin/python -m pytest backend/tests/unit/test_research_checks.py -q -p no:randomly
./.venv/bin/python scripts/eval/run_eval.py --plan --fixtures R1 --tier tier-r1
python3 scripts/eval/research_scores.py --help
python3 scripts/eval/research_scores.py \
    --workspace scripts/eval/results/tier-r1-research/fixture-workspace \
    --case R1 --checks --append --source 'ví dụ dựng tay (không phải lượt thật)'
```

Lệnh thứ tư **ghi nối** một dòng vào `scores.jsonl`; muốn thử mà không đụng sổ điểm thì trỏ
`--out /var/tmp/<tên>.jsonl --append`. Không lệnh nào trong đây gọi model hay mở mạng.

## Dòng điểm có gì (và không có gì)

Mỗi dòng: `case`, `level` + `levelSource` (mức lấy từ `--level` hay từ `Level:` trong header),
`measuredAt` (UTC), `command` (nguyên văn argv), `source` (nhãn nguồn), `workspace`, `log`,
`workspaceFiles`, `checks` (danh sách `{name, ok, detail}` của oracle máy đã chạy, hoặc `null`),
và `numbers` — năm số của flow §7.3, mỗi số kèm `basis` nói số ấy lấy từ đâu:

| Số | Lấy từ | Ví dụ dựng tay |
|---|---|---|
| `factual_accuracy` | khẳng định có nguồn / tổng khẳng định trong `sources.jsonl` | 1.0 (1/1) |
| `citation_precision` | nguồn mở được **và** có đoạn trích đọc lại được / tổng nguồn | 1.0 (1/1) |
| `coverage` | nhánh có kết luận / nhánh mở (event `child`; không có thì đếm thư mục hồ sơ) | 1.0 (1/1) |
| `source_quality` | phân bố tầng 1–4 của sổ nguồn (`distribution` kèm theo) | 1.0 (tầng 1: 1) |
| `efficiency` | giây đã dùng / trần của mức, kèm số bước | **`null`** — không có nhật ký nên chưa đổi được bước ra giây |

Số nào chưa đo được thì `value` là `null` kèm lý do trong `basis`/`detail`: **không ghi 0 thay cho
"chưa biết"** (0 là một phép đo, `null` là một chỗ trống). `efficiency` ở dòng ví dụ là chỗ trống
đó — ví dụ cố ý không kèm nhật ký để thấy rõ luật này.

## Cái gì chưa có (nói thẳng)

- **Chưa chạy lượt thật nào**: `scores.jsonl` có đúng một dòng, và dòng đó là ví dụ dựng tay.
- **Chưa có URL thật**: phòng ví dụ dùng tên miền dành riêng cho ví dụ (`baohiem.example`) nên
  mọi con số ở đây chỉ minh hoạ hình dạng hồ sơ, không phải kết quả tra cứu.
- `manifest.json` để `provider`/`model`/`seed`/`temperature` là `null` **vì không có lượt gọi model
  nào**, không phải vì quên đo.
- Nhóm offline của C-7 (R1+R3+R6+R7 trên lượt thật) **chưa chạy**; dòng điểm thứ hai trở đi chỉ
  xuất hiện khi có lượt thật.
