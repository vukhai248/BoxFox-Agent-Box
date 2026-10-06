# BoxFox Desktop (Alpha)

Electron shell that runs the whole BoxFox stack — the web UI, the router and the agent
harness — as a normal Windows desktop app, without a developer checkout on the machine.
Plan: `/.plans/desktop-alpha-packaging.md` §6 PR-2 (work items D1 and D2).

```
desktop/
  src/                 main process (TypeScript → dist/)
    main.ts            startup order: profile → lock → mode → services → gateway → window
    preload.ts         the only bridge exposed to the UI (contextBridge, no nodeIntegration)
    profile.ts         per-user profile, port allocation, machine.json, admin token
    supervisor.ts      single-instance lock + child processes (router, harness) + health
    gateway.ts         loopback HTTP/WS gateway: serves the UI, proxies the three surfaces
    mode.ts            host | docker decision, docker probe, per-profile compose override
    paths.ts           where the bundled blocks live (packaged vs. checkout)
    diagnostics.ts     the data behind "Trạng thái dịch vụ"
  scripts/
    fetch-runtime.mjs  downloads Node + CPython + wheels, verifies sha256, writes the lock
    build-app.mjs      stages build/ (ui, router, harness, runtime, docker-context)
    lib/               zip reader/writer, streaming downloads, hashes, the runtime lock
  test/                node:test — profile, gateway, supervisor, mode, build scripts
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

Cross-building the Windows installer on Linux works (Wine is used for the NSIS step):
`DISPLAY=:1 npx electron-builder --win nsis --x64`. `npm run pack:linux` produces an
unpacked Linux tree for smoke tests, but it still bundles the Windows runtime, so the
supervisor only starts there once a Linux runtime exists (see "Known limitations").

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

## Known limitations (alpha)

- **Unsigned installer.** SmartScreen will warn; there is no code signing identity yet.
- **No auto-update.** `updates/` exists in the profile but nothing writes to it yet.
- **Windows only.** The bundled runtime is `win-x64`; a Linux/macOS bundle needs its own
  entry in `runtime-sources.json` (and wheels for that platform).
- **`build/icon.ico` is a placeholder** (the packaging step needs *some* icon). The real
  brand icon, the tray, the installer NSIS script and the diagnostics UI are work item D3.
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
the host/docker decision and the build scripts (zip round-trip, verified downloads,
runtime lock, staged manifest).
