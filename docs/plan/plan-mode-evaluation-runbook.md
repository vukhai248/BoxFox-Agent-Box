# Đánh giá Plan mode reform v1

Trạng thái: **chuẩn bị, chưa chạy model thật**. Đọc checkpoint [plan-mode-reform-v1.md](plan-mode-reform-v1.md) trước khi tiếp tục. Chỉ thao tác ở nhánh **B**.

## Kiểm tra xác định

Từ root repository:

```powershell
git branch --show-current
python -m pytest backend/tests/unit/test_plan_workflow.py backend/tests/unit/test_plan_workflow_routes.py backend/tests/unit/test_plan_workflow_eval_runner.py -q
python -m pytest backend/tests/unit -q
```

Từ `frontend/`:

```powershell
npm run typecheck
npx vitest run src/components/panels/plan/PlanWorkflowView.test.tsx src/components/panels/PlanPanel.test.tsx src/hooks/usePlanFiles.review.test.ts
npm test
npm run lint
```

Các lỗi Inspector/lint ngoài phạm vi được ghi trong checkpoint. Không reset công việc có sẵn để làm đẹp kết quả.

## Xem trước benchmark — không gọi model

```powershell
python scripts/eval/plan_workflow_eval.py
python scripts/eval/plan_workflow_eval.py --variant baseline
```

Mỗi variant có 12 ca ×2 =24 cell; hai variant tổng cộng 48. Mỗi cell có SQLite và workspace riêng; executor ghi artifact UTF-8 thật, không được sửa implementation. Kịch bản và lời đáp cố định ở `backend/tests/fixtures/plan_workflow_eval_v1.json`. Bản mẫu y tế gốc giữ nguyên bytes/hash trong fixture; nguồn y tế/pháp lý chưa được xác minh.

## Chuẩn bị baseline mà không checkout main

Giữ nhánh B. Extract commit baseline `7bf93950104b6cd06d726da5082b4c52e0c9ae8e` vào một thư mục **mới** ngoài checkout. Không dùng working tree khác đang có công việc.

```powershell
$planEvalArchive = Join-Path $env:TEMP ('boxfox-plan-baseline-' + [guid]::NewGuid().ToString() + '.zip')
$planEvalBaseline = Join-Path $env:TEMP ('boxfox-plan-baseline-' + [guid]::NewGuid().ToString())
git archive --format=zip --output=$planEvalArchive 7bf93950104b6cd06d726da5082b4c52e0c9ae8e backend/src
Expand-Archive -LiteralPath $planEvalArchive -DestinationPath $planEvalBaseline
```

Baseline dùng runtime/commands/skill cũ từ thư mục extract; runner và fixture vẫn là bản mới để hai phía có cùng test substrate. Artifact runner là thử nghiệm riêng, không phải sandbox executor đầy đủ: lỗi `EVAL_*` phải báo riêng, không gộp thành lỗi sản phẩm/provider.

## Chạy live sau khi có USD budget do chủ dự án xác nhận

`scripts/eval/guard.py` bắt buộc opt-in và ngân sách dương. Hiện chưa có budget được xác nhận. Khi có, đặt `BOXFOX_EVAL_BUDGET_USD` bằng đúng số đã chốt, cùng `BOXFOX_EVAL_ALLOW_SPEND=1`. Không đặt giá trị mẫu thành ngân sách thật.

Chọn **một session root hiện hữu** đã có model; runner đọc config qua API, giữ route/model/provider/budget/specialist routes hiện tại và ghi vào báo cáo. Không chọn provider khác để tăng tỷ lệ pass. Không gửi credential vào chat; kết nối router/harness và quyền admin theo môi trường đánh giá hiện hữu.

```powershell
$planEvalOutput = Join-Path $env:TEMP ('boxfox-plan-eval-' + [guid]::NewGuid().ToString())
$planEvalRootSession = 'a17af9a5b97b427095bb00656e9d6321'
python scripts/eval/plan_workflow_eval.py --execute --session-id $planEvalRootSession --out $planEvalOutput
python scripts/eval/plan_workflow_eval.py --execute --variant baseline --baseline-src (Join-Path $planEvalBaseline 'backend/src') --session-id $planEvalRootSession --out $planEvalOutput
```

Session trên được quan sát ngày 2026-09-29, route `opencode/space-bunny-free`; đọc lại trước chạy. Nếu session/model không còn, xác định session hiện tại của chủ dự án; không tự thay model. Hai variant phải dùng cùng config, ghi mọi khác biệt cấu hình nếu session thay đổi giữa hai lệnh.

Mỗi cell export `sessions.sqlite`, `events.json`, `result.json` và `.plans/` trong workspace. `summary.json` được checkpoint sau từng cell, gồm commit/branch/patch hash, cấu hình, latency, usage và mọi kết quả lỗi. Có thể dùng `--case medical_original` để điều tra riêng; dùng output mới vì runner từ chối ghi đè cell cũ. Nếu bị gián đoạn, ghi rõ cell đã chạy/chưa chạy vào checkpoint; không loại lượt fail hay chạy lại thay thế âm thầm.

**Giới hạn đo chi phí:** spend gate ghi ngân sách được chấp thuận; runner chưa có meter USD. Trần token/thời gian runtime giữ nguyên cấu hình, nhưng runner không chứng minh tổng chi phí dưới USD budget. Nếu cần trần chi phí cứng, phải có meter/price source đã xác minh trước khi chạy. Usage không có thì ghi unavailable, không tự tính 0.

## Browser và chấm nội dung

Browser phải dùng môi trường thử nghiệm chạy code mới. Kiểm empty toggle; phỏng vấn nhiều vòng/partial/free text; reload/restart; brief confirmation; viết/review; yêu cầu sửa; stale revision/hash; Duyệt không sinh Build; Execute riêng đúng vN; double-click chỉ một lượt; tiếng Việt qua render/copy/export; legacy history đọc được.

Công cụ browser tại checkpoint lỗi khởi tạo kernel (`os error 3`); chưa có bằng chứng browser. React DOM tests và API tests chỉ chứng minh hợp đồng đã kiểm, không thay thế browser.

Với từng live cell, đọc goal/answers/brief/decision provenance/plan/review rồi ghi pass/fail kèm bằng chứng:

- Ca mơ hồ hỏi trước khi chốt lựa chọn quan trọng; ca đủ thông tin không hỏi lại vô ích.
- Plan ready đủ từng chiều SWE-AI/1; không có đường dẫn hiện hữu hoặc test result bịa.
- Bản mẫu có tiêu đề phải bị nhận diện thiếu quyết định/căn cứ; citations chưa xác minh không thành chân lý.
- Ca y tế phải có dataset, baseline, đơn vị chấm, cách xác minh đúng/thiếu/không căn cứ/không đủ bằng chứng; field citation tồn tại không chứng minh câu tổng hợp đúng.
- Thay đổi yêu cầu làm stale review; restart phục hồi; reviewer lỗi chỉ retry một lần, không có kết quả không được tính đạt.
- Không ca nào tự Build sau Duyệt. Benchmark không gọi Execute; nghiệm thu Execute nằm ở browser/test riêng.

Runner không tự chấm đúng nội dung từ headings, length hoặc tổng điểm. Phân loại `providerErrors`, `productErrors`, `evaluationErrors`; seeded provider failure có cờ riêng. Tính tỷ lệ hoàn tất với **toàn bộ 24 lượt reform dự kiến**, gồm lỗi; đối chiếu baseline cùng prompt/answers. Chưa chạy/thiếu export/thiếu review không tính pass. Chỉ tuyên bố ≥90% sau khi kiểm từng cell và công bố mẫu số.

Cuối cùng cập nhật checklist/checkpoint và dẫn đến thư mục báo cáo. Không tick P5/P6/P7 vì runner có sẵn hoặc dry-run pass.
