# BoxFox Desktop (Alpha) — install, run modes and acceptance checklist

> **End users who only want to install and use the app:** read the short version
> [desktop-alpha-quickstart.en.md](desktop-alpha-quickstart.en.md) first. This document is the full
> version for whoever accepts the build. Vietnamese: [desktop-alpha-install.md](desktop-alpha-install.md).
>
> **Status:** install guide plus a 13-step checklist for the owner to accept D4. This is the document of
> work items D3/D4 in `desktop-alpha-packaging.md` (§6 PR-2, §8) and §17.3 of
> `v1-machine-environments-roadmap.md`.
>
> **Date:** 2026-10-06 (install directory and build notes updated 2026-10-09). **Branch:**
> `vorflux/desktop-alpha`, installer also built from `vorflux/host-mode-web-transport` (commit
> `eba9aad`). **Installer:** `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (Windows x64, **not
> Authenticode-signed**).
>
> **Not accepted yet:** this document is a guide for a human to run on Windows 11 x64. No test result in
> here counts as passed; the "expected result" rows are criteria, not a record.

## 1. What the installer contains

- **NSIS per-user** — installs into `%LOCALAPPDATA%\Programs\boxfox-desktop`, **never asks for admin**,
  installs no service and writes nothing into `Program Files`. (The default folder name comes from `name`
  in `package.json`: `productName` contains parentheses, so it cannot be used as a folder name. The user
  can change it on the "Choose Install Location" page.)
- **Bundled runtime** — Node 24.9.0 + CPython 3.13.7 + pinned wheels (`runtime.lock.json`). The target
  machine needs **no** Node, Python, Conda or npm.
- **The whole stack** — the pre-built UI, the router, the harness, and `docker-context/` for building the
  sandbox image when needed.
- **Shortcuts** — Desktop + Start Menu, named `BoxFox Desktop (Alpha)`.
- **It does not launch itself after install** (`runAfterFinish: false`) and it **does not enable
  autostart**: the app runs only when the user opens it.
- **Uninstall keeps the data** — see §6.

SmartScreen warns because the installer is unsigned: **More info → Run anyway**. Check the hash before
running:

```powershell
Get-FileHash .\BoxFox-Desktop-Alpha-0.1.0-Setup.exe -Algorithm SHA256
# or: certutil -hashfile BoxFox-Desktop-Alpha-0.1.0-Setup.exe SHA256
```

Compare it against the `SHA256SUMS.txt` shipped next to the installer. For the 2026-10-09 build:
`fa2b965ca102e0797cc93048ce94750b5370f5828281b3a9d2b4938a0a4a077f` (167,123,853 bytes).

## 2. Install

1. Run `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (click through the SmartScreen warning).
2. Choose the install folder (default above) and leave the shortcut options as they are.
3. When the wizard finishes the app does **not** open. Open it from Start Menu → `BoxFox Desktop (Alpha)`.
4. The first launch takes a few seconds because the app creates the profile and allocates four loopback
   ports.

Reinstalling the same version over an existing one is safe: the installer keeps
`%LOCALAPPDATA%\BoxFoxDesktopAlpha` and reuses the same profile.

## 3. Choosing the run mode (host / docker)

**Default on first run: `host`** — it runs without Docker (the plan's "the machine that installs is the
easiest machine" decision).

To change the mode:

1. Open `%LOCALAPPDATA%\BoxFoxDesktopAlpha\desktop-settings.json`.
2. Set `"executionMode": "docker"` (or `"host"`).
3. Restart the app.

```json
{ "version": 1, "executionMode": "host", "updatedAt": "..." }
```

| Mode | Requires | Where the agent runs | Note |
|---|---|---|---|
| `host` | nothing | Directly on Windows, under the user account | No OS-level sandbox — see §5 |
| `docker` | Docker Desktop running | In the container `boxfox-desktop-<profile>` | Uses the image `agentbox-sandbox:latest` |

- `docker` is selected only when **all three** hold: the `docker` CLI exists, the engine is alive, and the
  image is available. If any of them is missing the app **falls back to `host` and states the reason** in
  the log and the diagnostics file; it never reports a fake `docker`.
- When the image is missing the app builds it once from the bundled `docker-context/` (the alpha has no
  registry — a deliberate deviation from §15.5 of the roadmap).
- The alpha **has no Settings → run mode tab** (that is frontend work item D4); the only way to change the
  mode today is to edit `desktop-settings.json` and restart.
- The reason for the chosen mode always appears in `summary.txt` of the diagnostics file and in the
  `[desktop] mode: ...` log line.

## 4. Environment variables

The app **clears every inherited `BOXFOX_*`** before it sets the variables for its two child processes
(router, harness). That means: setting the variables below in Windows Environment Variables **has no
effect** — they are the app's output, not a control. The source of truth is `machine.json` +
`desktop-settings.json`.

| Variable | Set by the app for | Meaning |
|---|---|---|
| `BOXFOX_EXECUTION_MODE` | both | `host` or `docker` — the mode chosen for this run |
| `BOXFOX_DESKTOP_PROFILE` | both | The profile folder (`%LOCALAPPDATA%\BoxFoxDesktopAlpha`) |
| `BOXFOX_API_KEY` | both | The admin token **of this machine** (`machine.json`, `crypto.randomBytes(32)`) |
| `BOXFOX_AGENT_DATA_DIR` | harness | `<profile>\profile\harness` — harness data/sessions |
| `BOXFOX_ROUTER_DATA_DIR` | router | `<profile>\profile\router` — router data |
| `BOXFOX_HARNESS_PORT`, `BOXFOX_ROUTER_PORT` | harness / router | The loopback ports allocated in `machine.json` |
| `BOXFOX_UI_ORIGINS` | harness | The gateway's origin allowlist (no wildcard) |
| `BOXFOX_ROUTER_URL`, `BOXFOX_BOX_URL` | harness | Addresses of the router and the box/sandbox |

Two names that appear in the plan, `BOXFOX_HOST_WORKSPACE` and `BOXFOX_PROFILE_DIR`, **do not exist in
the current code** (no file reads them). Do not set them and expect an effect; the real names are the
table above.

## 5. Where the data, logs and diagnostics live

All of it in **one** folder, nothing spread into the registry or `Program Files`:

```
%LOCALAPPDATA%\BoxFoxDesktopAlpha\
  machine.json            gateway/router/harness/box ports + admin token (chmod 0600)
  desktop-settings.json   executionMode (host|docker)
  desktop.lock            pid of the running instance (prevents double launches)
  profile\
    harness\              harness data (sessions, history)
    router\               router data
    ui\                   UI helper data
  logs\                   router.stdout.log, router.stderr.log,
                          harness.stdout.log, harness.stderr.log
  diagnostics\            the "Export diagnostics" .zip files
  recovery\               a corrupt machine.json is quarantined here (never silently overwritten)
  updates\                reserved for auto-update (unused in the alpha)
  permissions\ audit\     reserved for permission rules + audit (once the permission layer exists)
```

## 6. Diagnostics export

**Tray → Sao lưu chẩn đoán** (Export diagnostics). The app collects everything into **one** zip file under
`diagnostics\` and opens Explorer with that file selected:

```
%LOCALAPPDATA%\BoxFoxDesktopAlpha\diagnostics\boxfox-diagnostics-<YYYY-MM-DDTHH-MM-SS-mmmZ>.zip
  manifest.json   app version, build commit, mode + reason, ports, profile/data/logs paths,
                  runtimeBundle (target, artifact, runtime file list with size + sha256),
                  health, services, Docker identity
  health.json     the raw JSON of GET /api/agent/health
  summary.txt     a human-readable summary
  logs\*          the last 200 lines of EVERY file in logs\
```

Attach this zip when you report a problem. **It carries no API key or token**: every key and every log
line passes through a filter on the words `key`, `token`, `secret`, `authorization` and `password`
(case-insensitive) and is replaced with `[REDACTED]` before it is written.

## 7. Straight warning about host mode

Read this before you turn it on. There is no softer way to put it:

- **The agent runs under your Windows account.** Host mode has no OS-level sandbox (restricted token /
  AppContainer / WFP — Codex has one, this alpha does **not**). Anything your account can read or write,
  the agent can read or write, including files outside the project folder.
- **Commands really run on your machine.** There is no container underneath. The alpha leaves the default
  permission level at **ask first** (`ask`), and the **hardline floor** is a list that is refused even
  after you grant full permissions.
- **CUA (mouse/keyboard/screen) is OFF by default.** When you turn it on yourself, the agent drives your
  **real mouse and keyboard**: it can click into windows you have open, type into the focused field, and
  **every screenshot the agent takes goes into the conversation turn and is sent to the model provider**.
  Do not leave windows with sensitive data (banking, passwords, private chats) open while CUA is on.
- **Emergency stop** (tray → `Dừng khẩn`) is the way out: it stops the pending action, releases any held
  keys/buttons and returns control to the user. `Trả quyền cho agent` (Return control to the agent) is
  the opposite direction.
- The alpha **does not have** the CUA/host-mode layer in the harness if PR-1 (H5–H7) is not in the build.
  In that case steps 5–11 of the checklist **must report "not supported" clearly** — never pretend to
  succeed.

## 8. The 13-step acceptance checklist

Conditions: Windows 11 x64, **without** Node/Python/Conda installed; the machine does **not** have Docker
running for steps 1–7. Record the version/commit of the build while you run it.

| Step | How | Expected result |
|---|---|---|
| 1. Install | Run `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (through the SmartScreen warning), keep the default folder | Installed under `%LOCALAPPDATA%\Programs\boxfox-desktop` (the installer's default name); Desktop + Start Menu shortcuts exist; an entry `BoxFox Desktop (Alpha)` in Apps & features; `%LOCALAPPDATA%\BoxFoxDesktopAlpha\` created; the app does **not** open by itself after install |
| 2. Launch | Start Menu → `BoxFox Desktop (Alpha)` | The window shows the real web UI; the tray icon appears; `logs\router.stdout.log` and `logs\harness.stdout.log` get new lines; it does **not** ask for Node/Python/Docker; no terminal opens |
| 3. Choose the run mode | Open `desktop-settings.json`, change `executionMode`, restart; read the `[desktop] mode:` log line | `host` works on a machine **without** Docker; `docker` is accepted only while Docker Desktop is running; missing Docker ⇒ falls back to host **with a clear reason** in the log + diagnostics, and never shows a fake sandbox |
| 4. Run one conversation turn | Type a simple request in the chat box, wait for the answer, then Ctrl+R | The answer comes from the real backend (not a mock); the session/history survives the reload; the service status reflects the processes that are actually running |
| 5. Look at the permissions tab | Open the **Quyết định** (Decisions) panel — the list of permission approval requests | The list reads directly from real `decision_requested` / `decision_resolved`; pending rows are distinguishable from handled ones; there is **no** demo data and no invented deadline |
| 6. A command inside the hardline floor | Ask the agent to run a command on the hard block list (for example a session-lock / secure-desktop operation) | **Refused with a reason code**, even at the widest permission level; nothing is executed; the event lands in the audit log |
| 7. Reject an approval card | Click **reject** on a pending permission card | The row turns "rejected"; the agent receives the rejection and does **not** run the action; three rejections in a row trip the breaker and the agent stops asking (code `APPROVAL_DENIAL_BREAKER`) |
| 8. Turn on host mode (CUA) | Go to **Settings → CUA**, flip the switch and confirm separately | CUA was **off** before; turning it on requires its own confirmation; the permission banner changes to "Agent is in control"; the lease shows who holds it |
| 9. Screenshot | Ask the agent to take a screenshot | The image lands in the right conversation turn and is sent to the model; if CUA is off ⇒ a clear refusal instead of a fake image; note that the image contains everything on the screen |
| 10. Inspect element | In the Machine screen preview, select an element → **Add to Chat** | The selector carries the right source and coordinates; the data stays in the chat after sending; if the element or the coordinates change ⇒ `ELEMENT_STALE`/`SOURCE_CHANGED`, it does **not** resolve to a different element |
| 11. Emergency stop | Tray → **Dừng khẩn** | The pending action stops; every held key/button is released; the lease returns to the user; the app states clearly what it sent to the harness; in docker mode, if the container holds control, it reports **409** instead of staying silent |
| 12. Diagnostics export | Tray → **Sao lưu chẩn đoán** | A new ZIP in `diagnostics\` with Explorer already open; it contains `manifest.json`, `health.json`, `summary.txt`, the last 200 lines of each log and the runtime inventory with sha256; it contains **no** API key or token |
| 13. Uninstall | Apps & features → `BoxFox Desktop (Alpha)` → Uninstall | Program and shortcuts disappear; `%LOCALAPPDATA%\BoxFoxDesktopAlpha` **stays** (machine.json, sessions, logs); reinstalling finds the same profile and does not issue new ports or a new token |

Steps 5–11 need the host-mode/CUA layer of PR-1 (H5–H7) in the build; if the build does not have it, the
correct result is **report "not supported"** and say so explicitly instead of marking the step as passed.

## 9. Known limitations of the alpha

- The installer is **unsigned** (SmartScreen warns); there is no auto-update.
- Only a **Windows x64** installer exists; the bundled runtime is `win-x64`.
- **No OS-level sandbox** in host mode (see §7).
- No **host screen recording** (`computer_screen_record`) yet — it needs `ffmpeg`; inside the box it still
  works.
- The tray is optional: if the environment cannot create one, the app logs
  `[desktop] no tray; closing the window will quit the app.` and closing the window quits it — there is no
  hidden tray.
- `build/icon.ico` is still a placeholder icon; the tray icon is `build/tray.png` (32×32).
- Uninstall does **not** delete the profile: to remove everything you must delete
  `%LOCALAPPDATA%\BoxFoxDesktopAlpha` by hand.
- Cross-building the installer on Linux needs a Wine that can run 32-bit binaries (`wine` +
  `wine32:i386`); otherwise the NSIS step stops and leaves a ~167 KB stub that is not an installer. See
  `desktop/README.md`.
