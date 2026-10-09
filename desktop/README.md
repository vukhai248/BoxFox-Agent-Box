# BoxFox Desktop (Alpha)

Electron shell that runs the whole BoxFox stack — the web UI, the router and the agent
harness — as a normal Windows desktop app, without a developer checkout on the machine.
Plan: `/.plans/desktop-alpha-packaging.md` §6 PR-2 (work items D1–D3).

**Installing the alpha and testing it:** four documents, pick by role and language.

- End users, first install: `docs/plan/desktop-alpha-quickstart.md` (Vietnamese) and
  `docs/plan/desktop-alpha-quickstart.en.md` (English) — download, verify the SHA-256, run the installer,
  choose host/docker, where the profile lives, how to uninstall.
- Whoever accepts the build: `docs/plan/desktop-alpha-install.md` (Vietnamese) and
  `docs/plan/desktop-alpha-install.en.md` (English) — install, choosing host/docker mode, where the
  profile/logs live, how to export diagnostics, the host-mode warning and the 13-step acceptance
  checklist.

```
desktop/
  src/                 main process (TypeScript → dist/)
    main.ts            startup order: profile → lock → mode → services → gateway → window → tray
    preload.ts         the only bridge exposed to the UI (contextBridge, no nodeIntegration)
    profile.ts         per-user profile, port allocation, machine.json, admin token
    supervisor.ts      single-instance lock + child processes (router, harness) + health
    gateway.ts         loopback HTTP/WS gateway: serves the UI, proxies the three surfaces
    mode.ts            host | docker decision, docker probe, per-profile compose override
    paths.ts           where the bundled blocks live (packaged vs. checkout)
    tray.ts            the tray menu as data (labels, order, handlers) + show/hide rules
    desktop-control.ts the tray's "Trả quyền cho agent" / "Dừng khẩn" calls to the harness
    diagnostics.ts     service summary + the redacted support-bundle zip
    zip.ts             dependency-free ZIP writer for the support bundle
  scripts/
    fetch-runtime.mjs  downloads Node + CPython + wheels, verifies sha256, writes the lock
    build-app.mjs      stages build/ (ui, router, harness, runtime, docker-context)
    lib/               zip reader/writer, streaming downloads, hashes, the runtime lock
  test/                node:test — profile, gateway, supervisor, mode, tray, diagnostics, scripts
  build/               staged blocks (generated) + the committed icon.ico / tray.png / installer.nsh
  runtime-sources.json pinned runtime versions and digests
  runtime.lock.json    what was actually fetched (regenerate with fetch-runtime)
  THIRD-PARTY.md       generated licence inventory of the bundled runtime
  electron-builder.yml packaging (NSIS per-user, Windows x64)
```

## Building

Node 24 and npm are the only prerequisites on the build machine.

```bash
cd desktop
npm install                # electron + electron-builder + typescript
npm run fetch-runtime      # ~190 MB download → runtime/win-x64 + runtime.lock.json
npm run build-app          # stage build/ (needs a built frontend, see below)
npm run dist:win           # → release/BoxFox-Desktop-Alpha-0.1.0-Setup.exe
```

`build-app` needs a production frontend build. It reuses `frontend/dist` when that
exists, otherwise it runs `npm run build` in `frontend/` (which needs
`frontend/node_modules`). To use a UI built elsewhere, pass `--ui-dir <dir>`:

```bash
node scripts/build-app.mjs --ui-dir /path/to/built/ui
```

`.github/workflows/desktop-build.yml` runs exactly the steps above on a clean
`windows-latest` runner — manually (`workflow_dispatch`) or on a `desktop-v*` tag, never on
every push. It uploads the installer plus a `SHA256SUMS.txt` as a build artifact; it does
not publish a release (the installer is unsigned).

Cross-building the Windows installer on Linux works (Wine is used for the NSIS step):
`DISPLAY=:1 npx electron-builder --win nsis --x64`. **Wine must be able to run 32-bit binaries**
(`wine` + `wine32:i386` on Debian/Ubuntu). electron-builder builds the uninstaller by running the
installer stub under Wine, and that stub is a 32-bit PE: with a 64-bit-only Wine the build stops at
`wine process failed ENOENT` (or `failed to load sysroot\...\ntdll.dll error c0000135`) *after*
`win-unpacked/` is written, and the `Setup.exe` left behind is a ~167 KB stub, not an installer.
`npm run pack:linux` produces an unpacked Linux tree for smoke tests, but it still bundles the
Windows runtime, so the supervisor only starts there once a Linux runtime exists (see "Known
limitations").

## Verifying the runtime

`runtime.lock.json` records the sha256 of every block (node, python, wheels) plus each
downloaded artifact and wheel. The runtime is never committed — verify a fetched copy
in place, without network access:

```bash
npm run fetch-runtime:check     # exit 0 when the runtime matches the lock
```

Every download is checked while streaming: Node against the published `SHASUMS256.txt`
*and* the pin in `runtime-sources.json`, CPython against its pin, each wheel against the
digest PyPI publishes for that exact file (`https://pypi.org/pypi/<name>/<version>/json`).
A mismatch deletes the `.part` file and aborts; nothing is ever extracted unverified.

## How the app runs

1. **Profile** — `%LOCALAPPDATA%\BoxFoxDesktopAlpha\` (Windows) or
   `~/.local/share/BoxFoxDesktopAlpha` (Linux): `profile/{harness,router,ui}`,
   `logs/`, `recovery/`, `updates/`, `permissions/`, `audit/`. Four loopback ports and a
   per-machine admin token (`crypto.randomBytes(32)`) are allocated on first run and
   stored in `machine.json`; later runs reuse them. A port that is busy is re-allocated
   on its own and the record is rewritten. A corrupt `machine.json` is moved to
   `recovery/` — never silently overwritten.
2. **Single instance** — `desktop.lock` holds the owner pid; a lock left by a dead
   process (a crash) is taken over, a live owner makes the second start exit.
3. **Mode** — `docker` only when the Docker CLI, the engine and the `agentbox-sandbox:latest`
   image are all available; otherwise `host`, always with an explicit reason that is shown
   in diagnostics and written to the logs. The image is built once from the bundled
   `docker-context/` when it is missing.
4. **Services** — the bundled Node runs `router/src/main.mjs --production`, the bundled
   CPython runs `harness/scripts/run-harness.py`. Every inherited `BOXFOX_*` variable is
   dropped first, then the child gets the profile paths, its own port and the machine
   token. Health endpoints are polled; a crash is restarted with exponential backoff
   (3 attempts); stopping kills the whole process tree.
5. **Gateway** — one loopback HTTP+WS server serves the built UI and proxies
   `/api/agent*` → harness, `/api/router*` + `/v1*` → router, `/__box/*` → the box
   container (docker) or the harness desktop API (host). `Host` and `Origin` must be the
   gateway's own loopback names, state-changing requests must carry an `Origin`, and the
   UI is served with a CSP that contains no wildcard.
6. **Window and tray** — the window points at the gateway. Closing it (`X`) **hides it to
   the tray**; the app only exits from the tray's `Thoát`, `before-quit` or when no tray
   could be created. The tray menu carries `Hiện/Ẩn cửa sổ`, `Trả quyền cho agent`,
   `Dừng khẩn`, `Mở thư mục dữ liệu`, `Sao lưu chẩn đoán` and `Thoát`; the two control
   entries POST `{"action":"claim"|"stop"}` to the harness lease route and report the
   result (a `409` means docker mode keeps the pointer inside the container — that is
   reported, not hidden).
7. **Diagnostics bundle** — `Sao lưu chẩn đoán` writes one zip into
   `<profile>/diagnostics/`: `manifest.json` (version, commit, mode + reason, ports, paths,
   runtime file inventory with sha256), `health.json` (`GET /api/agent/health`),
   `summary.txt` and the last 200 lines of every file in `logs/`. Every value passes
   through a keyword filter (`key`, `token`, `secret`, `authorization`, `password`) before
   it is written, so the bundle never carries the machine token or an API key.

## Known limitations (alpha)

- **Unsigned installer.** SmartScreen will warn; there is no code signing identity yet.
- **No auto-update.** `updates/` exists in the profile but nothing writes to it yet.
- **Windows only.** The bundled runtime is `win-x64`; a Linux/macOS bundle needs its own
  entry in `runtime-sources.json` (and wheels for that platform).
- **`build/icon.ico` is a placeholder** (the packaging step needs *some* icon); the tray
  icon (`build/tray.png`, 32×32) is committed next to it. The real brand icon is still to
  come; `build/installer.nsh` holds the NSIS hooks (per-user data directory, and an
  uninstaller that deliberately keeps the profile).
- **Tray is best-effort.** If no tray can be created, the app logs
  `[desktop] no tray; closing the window will quit the app.` and `X` quits.
- **`/__tty` is unavailable in host mode** — the terminal bridge is a container feature.
- Uninstalling keeps `%LOCALAPPDATA%\BoxFoxDesktopAlpha` (sessions, logs, machine.json)
  on purpose.

## Tests

```bash
npm test          # tsc build + node --test "test/**/*.test.mjs"
npm run typecheck # tsc --noEmit
```

The suite covers the profile/port/token logic, the gateway allowlists and proxies (against
stub upstreams), the supervisor (locks, service environment, restart, process-tree stop),
the host/docker decision, the tray menu/show-hide rules, the lease calls (against a stub
harness, including `409` and timeouts), the diagnostics redaction rules and support-bundle
zip, and the build scripts (zip round-trip, verified downloads, runtime lock, staged
manifest).
