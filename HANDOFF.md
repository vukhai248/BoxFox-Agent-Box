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
- **Proxy API Endpoints (`deploy/docker/ide-proxy.py`):**
  - `GET /__box/plans` ➔ Manifest JSON tree of all available plan documents.
  - `GET /__box/plans/content?identity={id}&version={v}` ➔ Fetches markdown content.
- **Frontend Integration (`PlanPanel.tsx` & `usePlanFiles.ts`):**
  - Custom Popover Dropdowns for Document selection and Version selection (`v1 (approved)`, `v2 (draft)`).
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

---

## 3. Verification & Test Suite
- **Frontend (Vitest):** `127 / 127 tests passed` across 18 test files (`npm run test`).
- **Frontend Typecheck & Lint:** `0 errors` (`npm run typecheck`, `npm run lint`).
- **Python Unit Tests:** `13 / 13 tests passed` (`conda run -n DL python -m unittest discover -s deploy/docker/tests -p "test_*.py"`).
