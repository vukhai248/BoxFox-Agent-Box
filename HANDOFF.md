# HANDOFF DOCUMENTATION — BoxFox Agent Box

## 1. System Overview
BoxFox Agent Box is a self-hosted AI Computer environment combining:
- **Web UI (`frontend/`):** React 19 + TypeScript + Vite + Tailwind CSS with dark theme, responsive compact composer, and multi-panel layout (Chat, Plan, Sandbox Screen VNC, VS Code IDE).
- **Sandbox Container (`deploy/docker/`):** Ubuntu 24.04-based container with XFCE4, TigerVNC, Playwright Chromium, code-server (VS Code Web), and `ide-proxy.py`.
- **Security & IFC Architecture:** Root/non-root split, loopback isolation, no-store CORS headers, and safe path handling.

---

## 2. Recent Major Implementations

### A. Workspace Foundation (7 Core Dot Directories)
Upon container initialization (`box-entrypoint.sh`), the following directories are automatically created under `/home/agent/workspace/` with `0750` permissions and `agent:agent` ownership:
- `.generated_artifacts`
- `.plans`
- `.session-history`
- `.skills`
- `.trimmed-tool-output`
- `.uploaded_artifacts`
- `.virtual_views`

### B. Multi-version Plan Browser (`.plans/` Scanner)
- **Backend Scanner (`deploy/docker/plan_files.py`):**
  - Scans exclusively within `/home/agent/workspace/.plans/` (depth <= 16, entries <= 2000, size <= 1MB).
  - Matches filenames via regex `^v([1-9][0-9]*)-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$`.
  - Groups versions by slug identity, sorting descending `[v2, v1]`.
  - Top version is tagged `draft`, older versions tagged `approved`.
  - Enforces symlink rejection via `O_NOFOLLOW` / `dir_fd` on POSIX.
  - **Directory Mtime Cache:** Uses `os.stat(root).st_mtime` to cache the manifest metadata (0ms on repeat reads), automatically refreshing whenever a new plan file is created.
- **Proxy API Endpoints (`deploy/docker/ide-proxy.py`):**
  - `GET /__box/plans` ➔ Manifest JSON tree of all available plan documents (0ms cached).
  - `GET /__box/plans/content?identity={id}&version={v}` ➔ Direct, fast-path file stream (~1ms).
- **Frontend Integration (`PlanPanel.tsx` & `usePlanFiles.ts`):**
  - Custom Popover Dropdowns for Document selection and Version selection (`v1 (approved)`, `v2 (draft)`).
  - Fluid width container (`w-full min-w-0`) ensuring seamless stretching across large monitors without blank margins.
  - Sub-tabs:
    - `Detailed Plan`: Renders full Markdown with KaTeX math equations, GFM tables, interactive task lists, and syntax highlighting.
    - `Overview`: Architectural summary, file metadata, and navigation shortcut.
  - Action buttons: `[ Plan | Diff ]` toggle, `[ 🔗 Share ]`, `[ ❐ ]` copy, and `[ ✓ Approve Plan ]`.

### C. Responsive Chat Input Bar & Launcher Enhancements
- **Auto-collapsing Composer (`useCompactComposer`):**
  - Below 500px width: Shortens placeholder to `"Type..."` and collapses `Quick ask` / `Autopilot` to icon-only `[⚡]`.
  - Min chat column floor lowered to 400px with `min-w-0` overflow prevention.
- **Fast Docker Launcher (`scripts/start.bat` & `scripts/start.ps1`):**
  - Uses `docker compose up -d --build` with layer cache for instant startup (<0.5s when unchanged, 1-2s when docker config changes).
  - Full argument pass-through via `%*` (`start.bat -Rebuild`).

### D. Built-in Keyless Web Search (PART 1, 2026-10-06)
- `web_search` now works **out of the box, no API key required**: a self-hosted SearXNG on `127.0.0.1:8888` is auto-detected (`BOXFOX_SEARXNG_AUTODETECT`, 30s positive / 15s negative cache) and used as the default keyless leg; the 10-step pipeline defaults to `BOXFOX_SEARCH_PIPELINE=auto`. Start it with `bash deploy/searxng/up.sh` (see `deploy/searxng/README.md`).
- Failures are classified (`searchFailure.kind` = `config` / `infra` / `source`): infrastructure and config errors now say **"not a query problem"** instead of telling the agent to retry the query (fixes F05); an empty result set is a separate code (`WEB_SEARCH_EMPTY`).
- Decision record and **PART 2 interface contract (§4)**: `docs/plan/builtin-search-default.md`; three test tiers (unit / stub / live) and the latency bench: `docs/testing/builtin-search-e2e.md`.

---

## 3. High-Performance Architecture Reference
For handling heavy streaming data, large log files, or rich documents (>2,000 lines) at 60 FPS without UI jank, refer to the established 3-tier architecture guide:
- 📖 **Architecture Playbook:** [`docs/architecture/high-performance-rendering.md`](file:///d:/create/BoxFox-Agent-Box/docs/architecture/high-performance-rendering.md) (covers Backend Mtime cache, React AST memoization, and CSS `content-visibility: auto` layout virtualization).

---

## 4. Verification & Test Suite
- **Frontend (Vitest):** `127 / 127 tests passed` across 18 test files (`npm run test`).
- **Frontend Typecheck & Lint:** `0 errors` (`npm run typecheck`, `npm run lint`).
- **Python Unit Tests:** `13 / 13 tests passed` (`conda run -n DL python -m unittest discover -s deploy/docker/tests -p "test_*.py"`).

---

## 5. Chẩn Đoán & Kiến Trúc: Xử Lý `/claude-code` & Cơ Chế Nạp Skill BoxFox

### 5.1. Vấn Đề Hiện Tại Với `/claude-code`
- **Triệu chứng:** Khi người dùng gửi lệnh có tag `/claude-code` (ví dụ: `/claude-code day la test`), hệ thống lập tức mở sub-agent `Build Specialist` [FAILED 🔴], đồng thời chat chính báo lỗi:
  `CHILD_FAILED: inspect child events for setup/error details`.
- **Nguyên nhân gốc rễ:**
  1. **Ép cứng vai trò (Hardcoded Role & Executor):** Trong [`backend/src/agentbox/skills/commands.py`](file:///d:/create/BoxFox-Agent-Box/backend/src/agentbox/skills/commands.py) (dòng 172-175):
     ```python
     elif key in {'claude-code', 'claude-design'}:
         result.kind, result.skills = 'task', [key]
         result.executor = 'claude-code' if key == 'claude-code' else 'native'
         result.role = 'build' if key == 'claude-code' else 'orchestrator'
     ```
     Lệnh `/claude-code` bị gán cứng vào vai trò `build` và ép executor sang `claude-code` CLI.
  2. **Thiếu kiểm tra tiền khả thi (Pre-flight Check Failure):** Khi executor là `claude-code`, backend gọi [`ClaudeExecutor`](file:///d:/create/BoxFox-Agent-Box/backend/src/agentbox/sandbox/claude_executor.py) thực thi lệnh docker vào container `agentbox-box`. Nếu container chưa chạy, hoặc binary `claude` chưa được cài đặt / chưa đăng nhập (`claude auth login`) bên trong sandbox:
     - Worker ném ngoại lệ `setup_required: Check sandbox login, CLI version...`
     - Backend bắt lỗi, đánh dấu session con thất bại và ném `CHILD_FAILED`, làm sập toàn bộ luồng xử lý của Main Agent mà không có hướng dẫn thân thiện cho người dùng.

### 5.2. Giải Pháp Kiến Trúc: Luồng Riêng Cho Claude Code
1. **Tách biệt Executor khỏi Role:**
   - Không ép `/claude-code` thành vai trò `build`. Cho phép người dùng hoặc Orchestrator chỉ định vai trò linh hoạt (`explore`, `review`, `build`, v.v.).
2. **Cơ chế Kiểm Tra Tiền Khả Thi & Graceful Fallback:**
   - Trước khi dispatch sang docker CLI, hệ thống thực hiện probe trạng thái:
     - Trạng thái Docker container (`agentbox-box` có đang active?).
     - Trạng thái CLI binary & Authentication (`claude auth status`).
   - **Nếu chưa sẵn sàng:** Không tạo sub-agent lỗi để làm bẩn pipeline. Trả về thông điệp hướng dẫn rõ ràng trên UI:
     - Hướng dẫn mở Terminal Sandbox để chạy `claude auth login`.
     - Hoặc cung cấp tùy chọn chuyển đổi tự động sang **Native Claude Model** (sử dụng API Anthropic qua BoxFox Router thay vì phụ thuộc CLI bên trong docker).

### 5.3. Cơ Chế Nạp Skill Riêng Biệt Cho BoxFox & Phân Bổ Sub-Agent
- **Thực trạng nạp Skill:**
  - Hiện tại [`SkillCatalog`](file:///d:/create/BoxFox-Agent-Box/backend/src/agentbox/skills/catalog.py) chỉ quét thư mục `vendor/hermes/skills`.
  - Thư mục `.skills/` của BoxFox (chứa các skill chuyên biệt: `browser-testing`, `electron-testing`, `web-preview`, `planning-workflow`, `canvas-spec`, `secrets-catalog`...) chưa được tự động tích hợp vào catalog.
  - Bảng `ROLE_SKILLS` đang gán tĩnh danh sách skill Hermes cho từng role, không linh hoạt.
- **Chiến lược nâng cấp:**
  1. **Dual-source Skill Catalog:** Mở rộng `SkillCatalog` để quét cả `d:\create\BoxFox-Agent-Box\.skills` và `/home/agent/workspace/.skills`, gán namespace `source: 'boxfox'`.
  2. **Sub-agent với Model & Skill Riêng Biệt:**
     - Cho phép từng Specialist trong `Specialists Pipeline` được cấu hình model độc lập (ví dụ: `Explore` dùng model nhẹ/rẻ như `gemini-2.5-flash`, `Build` dùng `claude-3.7-sonnet`, `Review` dùng `deepseek-r1`).
     - Cho phép gắn thẻ kỹ năng (skill tags) phù hợp cho từng vai trò:
       - `Testing Specialist` ➔ nạp `browser-testing`, `web-preview`, `electron-testing`.
       - `Plan Specialist` ➔ nạp `planning-workflow`, `canvas-spec`.
       - `Review Specialist` ➔ nạp `git-pr-workflow`, `pr-description`.

---

## 6. Phân Tích & Chiến Lược Chuẩn Hóa Thinking Levels Cho Từng Model & Provider

### 6.1. Thực Trạng Hiện Tại (Mock / Hardcode)
- Trong [`router/src/providers/common.mjs`](file:///d:/create/BoxFox-Agent-Box/router/src/providers/common.mjs) và [`router/src/service.mjs`](file:///d:/create/BoxFox-Agent-Box/router/src/service.mjs), hệ thống dùng regex kiểm tra tên model (nếu có chứa `r1`, `o1`, `think`, `reason`...) rồi gán cứng:
  `thinkingLevels: ['low', 'medium', 'high']`
- Điều này dẫn đến sự vô lý khi:
  - Một số model không hỗ trợ thay đổi mức độ suy nghĩ (như DeepSeek R1 luôn bật, không có 3 mức).
  - Một số model không có tính năng suy nghĩ nhưng vẫn hiển thị selector.
  - Các provider sử dụng định dạng tham số hoàn toàn khác nhau nhưng bị ép chung một danh sách tĩnh.

### 6.2. Ma Trận Thinking Giữa Các Provider
| Provider | Đại diện Model | Cơ chế Thinking | Tham số API Thực Tế | Mức độ hỗ trợ |
| :--- | :--- | :--- | :--- | :--- |
| **OpenAI** | `o1`, `o3-mini`, `gpt-5` | Discrete Effort | `reasoning_effort: 'low' \| 'medium' \| 'high'` | Chuẩn 3 mức |
| **Anthropic** | `claude-3-7-sonnet` | Token Budget | `thinking: { type: 'enabled', budget_tokens: <number> }` hoặc `type: 'disabled'` | Budget linh hoạt (1024 - 128k), có thể tắt |
| **Google Gemini** | `gemini-2.5-flash`, `gemini-2.5-pro` | Token Budget | `generationConfig.thinkingConfig = { thinkingBudget: <number> }` (0 để tắt, -1 auto) | Budget số nguyên, có thể tắt |
| **Google DeepMind (Antigravity)** | `gemini-3.8-flash-high`, `gemini-3.8-pro` | Tier / Effort | `generationConfig.thinkingConfig = { thinkingLevel: 'low' \| 'medium' \| 'high' }` | Mức phân cấp theo tier định danh |
| **DeepSeek** | `deepseek-reasoner` (R1) | Inherent Reasoning | Luôn sinh `reasoning_content`, không có tham số bật/tắt hoặc điều chỉnh mức | Cố định (`fixed`), không chọn mức |

### 6.3. Chiến Lược Chuẩn Hóa Kiến Trúc
1. **Phân loại Model Thinking Capability (Capability Registry):**
   Thay vì regex chung chung, mỗi model metadata sẽ có cấu trúc năng lực rõ ràng:
   - `thinkingType`:
     - `'effort'`: Hỗ trợ các mức định danh (`['low', 'medium', 'high']`).
     - `'budget'`: Hỗ trợ cấu hình số lượng token (`budget_tokens` hoặc `thinkingBudget`).
     - `'fixed'`: Luôn suy nghĩ, không cho phép đổi mức (ví dụ DeepSeek R1).
     - `'none'`: Model thông thường không có reasoning.
   - `defaultThinking`: Mức mặc định khi kích hoạt.
2. **Translation Layer Tại Từng Provider Adapter:**
   - Adapter của Provider chịu trách nhiệm dịch mức quy ước từ UI (`low`, `medium`, `high`, `off`) thành payload chính xác của Upstream:
     - Anthropic Adapter: `low` ➔ `2048`, `medium` ➔ `8192`, `high` ➔ `16384`, `off` ➔ `{ type: 'disabled' }`.
     - Gemini Adapter: `low` ➔ `1024`, `medium` ➔ `4096`, `high` ➔ `16384`, `off` ➔ `thinkingBudget: 0`.
     - OpenAI Adapter: Chuyển trực tiếp sang `reasoning_effort`.
     - DeepSeek Adapter: Bỏ qua trường reasoning_effort (không gửi tham số không hợp lệ).
3. **Đồng Bộ Lên Giao Diện (Frontend):**
   - Chỉ hiển thị bộ chọn Thinking khi `m.thinkingLevels` có giá trị hợp lệ từ provider metadata thực tế.
   - Ẩn hoàn toàn thanh chọn Thinking đối với model `thinkingType: 'fixed'` hoặc `thinkingType: 'none'`.

---

## 7. Vấn Đề Tồn Đọng Với CUA (Computer Use Agent)
- CUA (Computer Use Agent) hiện tại chưa hoạt động đúng.

---

## Phụ lục mới 2026-09-25: research v2 và lượt thử chuyển tuyến

Phần bổ sung này không sửa nội dung các mục trước. Chủ nhà yêu cầu dừng các lượt test sống để tiết kiệm token. Trạng thái code, số đo test, các lỗi quan sát được ở bài toán y tế, giới hạn route Muse/Gemini và việc cần soát tiếp được ghi trong [phụ lục research v2](docs/handoff/research-v2-live-addendum-2026-09-25.md). Lượt sống đã hủy; dossier còn nháp và benchmark chất lượng 12×3 chưa đo.
