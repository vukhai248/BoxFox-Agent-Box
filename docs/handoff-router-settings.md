# Handoff — BoxFox native Router Settings

## Trạng thái

- Branch: `vorflux/router-settings-ui`
- Pull request: https://github.com/q123w133/BoxFox-Agent-Box/pull/2
- BoxFox là router gốc. 9Router, OmniRoute, Claude Code Router và LiteLLM chỉ là nguồn tham khảo kiến trúc, không phải sản phẩm để người dùng kết nối.
- Giai đoạn hiện tại là giao diện hoàn chỉnh, contract TypeScript và luồng mock xác định trước. Chưa có backend router, OAuth thật hoặc request tới provider.

## Đã hoàn thành

- Thêm `Settings → Router` ngay dưới `LLM API Keys`.
- Catalog nguồn gồm Antigravity, Claude Code/Anthropic, Codex/OpenAI, Gemini CLI/Google, Cursor, Kiro, GitHub Copilot, Qwen, Cline, OpenCode và Custom endpoint.
- Có luồng mock cho:
  - account setup và login required;
  - authorization mô phỏng;
  - explicit endpoint consent và kiểm tra thành công/thất bại;
  - xác nhận gửi dữ liệu;
  - model inventory theo từng source;
  - chọn default route cho phiên mới;
  - adapter-required;
  - disconnect và xóa default liên quan.
- Store chỉ lưu metadata và opaque mock credential handle; không lưu API key hoặc token thô.
- Endpoint validation chặn userinfo, fragment, secret-like query, protocol không hợp lệ và địa chỉ metadata/link-local nguy hiểm.
- Verification và consent gắn với revision; thay endpoint làm mất kết quả/consent cũ.
- Settings có navigation responsive cho màn hình hẹp.
- Không có MITM, cài CA, system proxy, port scanning, token-file import hoặc OAuth thật.

## Kiểm tra đã đạt tại commit `8e3c38b`

Chạy trong `frontend/`:

```bash
npm run typecheck
npm test -- --run
npm run build
npm run lint
```

Kết quả gần nhất:

- Typecheck: đạt.
- Unit/component tests: 402/402 đạt.
- Build: đạt.
- Lint: đạt.
- `git diff --check`: đạt.

## Việc còn lại

### 0. Review blocker phải sửa trước merge

Re-review tại commit `8e3c38b` phát hiện các lỗi còn lại; PR chưa nên merge trước khi sửa:

1. Mobile Settings không có nút đóng vì `Back to app` bị ẩn dưới breakpoint `sm`. Thêm nút close/X trong mobile strip hoặc Escape handler ở `SettingsModal`.
2. Đổi tên route đang trim theo từng phím và dùng chung `updateDraft`, làm mất space, verification và setup progress. Tạo action rename riêng, chỉ trim khi commit/blur.
3. Store chỉ có một `verification` toàn cục; khi thao tác route B thì route A ở `ready_to_confirm` có thể bị dead-end. Đổi thành verification theo `routeId` hoặc cho phép verify lại rõ ràng.
4. IPv6 blocklist đang dùng `hostname.startsWith('fc'|'fd')` cho mọi hostname, gây false positive; chỉ áp dụng cho IPv6 literal. Thu hẹp secret query-key regex.
5. Viết test hydration thật bằng module reload/dynamic import, cùng component test cho RouterView và mobile close.

Các finding thấp hơn: default button cần `aria-current`/`aria-pressed`; tránh announce verification hai lần; retry cần giải thích consent lại; cân nhắc `CustomCheckbox`; cancel verification hiện chưa dùng.

### 1. Hoàn tất browser evidence

Vòng retest trên HEAD hiện tại đã xác nhận:

- Catalog desktop đạt; không có 9Router, OmniRoute, LiteLLM hoặc router bên ngoài trong lựa chọn người dùng.
- Custom endpoint thành công với consent bắt buộc trước khi test.
- `http://localhost:3001/v1` trả kết quả mock và model metadata; xác nhận sử dụng dữ liệu vẫn là bước tách riêng.
- Typecheck, lint, 402 test và production build đều đạt.

Agent tiếp theo cần kiểm phần còn lại:

1. Mobile khoảng 390 px không bị cắt ngang.
2. Claude: setup → login required → authorize mock → consent → enable → default → disconnect dialog.
3. Custom endpoint thất bại.
4. Antigravity/Cursor/Kiro/Cline/OpenCode hiển thị adapter-required, không hứa kết nối trực tiếp.
5. Disconnect dialog giữ focus và trả focus đúng trigger.
6. Kiểm `localStorage` không có API key, token, cookie hoặc secret URL.

Evidence hiện có:

- `/code/.generated_artifacts/images/router-retest-catalog.png`
- `/code/.generated_artifacts/images/router-retest-custom-success.png`
- `/code/.generated_artifacts/recordings/router-settings-retest.webm`

Preview gần nhất:

https://rhilxuggglu3.preview.us1.vorflux.com

### 2. Backend thật — chưa triển khai

Backend hiện là skeleton. Cần triển khai theo thứ tự:

1. `GET /api/router/sources`
2. `GET/POST /api/router/routes`
3. authorization attempt qua credential broker;
4. route verification có timeout, SSRF protection và stale-result rejection;
5. model discovery;
6. enable route với revision + verification + data-use confirmation;
7. default route;
8. disconnect/revoke binding.

Không đưa raw OAuth token, refresh token, cookie hoặc CLI credential vào frontend, agent sandbox, log hay artifact. Frontend chỉ nhận opaque credential handle và safe account label.

### 3. Provider adapter thật — cần xác minh riêng

- Anthropic, OpenAI và Gemini: chỉ dùng cơ chế authorization/API được nhà cung cấp hỗ trợ chính thức.
- Antigravity, Cursor, Kiro và Copilot: không dùng MITM, DNS rewrite hoặc CA interception ở bản mặc định.
- Cline và OpenCode là client, không phải inference provider; cần upstream thật hoặc BoxFox adapter rõ ràng.
- Không suy ra quyền dùng subscription chỉ vì CLI đang đăng nhập.

### 4. Tab "Web Search" — phần mở rộng của bề mặt Provider (PART 2, 2026-10-06)

`Settings → Provider` nay có **ba tab**: **API · Router · Web Search** (nhãn đúng như trên thanh tab). Tab Web Search không phải
một bề mặt mới: nó **mượn đúng cơ chế lưu khoá** mà tab API đã dùng (bảng `credentials`, một
dòng cho mỗi provider, AAD = id dòng) qua hai `kind` mới (`search_provider`, `search_config`), nên
đường suy luận mô hình không bị chạm tới và không có thay đổi schema/hàm mã hoá nào.

- Tám thẻ provider theo catalog của router (`SEARCH_PROVIDER_CATALOG`), đúng thứ tự hiển thị.
- Khoá thô **không bao giờ** vào snapshot, log hay phản hồi HTTP thường — chỉ `prefix` (6 ký tự đầu
  + `…`). Hai đường duy nhất trả khoá thô là nút **Hiện** của giao diện và `GET /api/router/search/resolve`
  (harness đọc qua loopback).
- Hợp đồng HTTP đầy đủ (7 route) nằm ở [`router/CONTRACT.md`](../../router/CONTRACT.md); cách chạy
  bốn tầng test và smoke test thủ công nằm ở
  [`docs/testing/search-provider-e2e.md`](../testing/search-provider-e2e.md).
- Mục "Mặc định" trong tab = đường built-in không khoá của PART 1 (`searxng` tự host). Chọn một mục
  thì nó đứng đầu chuỗi ưu tiên; xoá mục đang dùng thì về lại "Mặc định".

## File chính

- `frontend/src/components/settings/RouterView.tsx`
- `frontend/src/components/settings/SettingsSidebar.tsx`
- `frontend/src/components/settings/SettingsModal.tsx`
- `frontend/src/store/routerStore.ts`
- `frontend/src/store/routerStore.test.ts`
- `frontend/src/types/router.ts`
- `frontend/src/types/harness.ts`
- `frontend/src/components/settings/SettingsSidebar.test.tsx`

## Thiết kế và nghiên cứu

Thiết kế mock nằm ngoài repository tại:

- `/code/.plans/designs/design-plan.json`
- `/code/.plans/designs/router-design-contract.md`
- `/code/.plans/designs/router-*.html`

Tài liệu kiến trúc trong repository:

- `docs/architecture/model-router.md`
- `docs/architecture/security-model.md`
- `docs/research/model-router/`

## Lệnh bắt đầu nhanh

```bash
git switch vorflux/router-settings-ui
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

Sau đó mở Settings, chọn Router và chạy lại ma trận browser ở trên.
