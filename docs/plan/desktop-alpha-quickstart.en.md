# Installing BoxFox Desktop (Alpha) on Windows — quick start

> **Who this is for:** end users installing the app for the first time. Read it and follow the steps.
> The full version — architecture, environment variables, the host-mode warning and the 13-step
> acceptance checklist — is in [desktop-alpha-install.en.md](desktop-alpha-install.en.md)
> (Vietnamese: [desktop-alpha-quickstart.md](desktop-alpha-quickstart.md)).
>
> **Installer:** `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (Windows x64, **not Authenticode-signed**), 167 MB.
> **SHA-256:** `fa2b965ca102e0797cc93048ce94750b5370f5828281b3a9d2b4938a0a4a077f`
> **Built from:** commit `eba9aad` on branch `vorflux/host-mode-web-transport` (2026-10-09), bundling
> Node 24.9.0 and CPython 3.13.7.

## 0. Before you start

| You need | Note |
|---|---|
| Windows 10 or 11, **64-bit** | the installer is x64 only |
| Administrator rights | **not required** — the installer writes into your own user folder |
| Node, Python, npm, Conda | **not required** — the app carries its own runtime |
| Docker Desktop | only if you want to run in `docker` mode |

## 1. Check the downloaded file

Open PowerShell in the folder that holds the file and run:

```powershell
Get-FileHash .\BoxFox-Desktop-Alpha-0.1.0-Setup.exe -Algorithm SHA256
```

The string it prints must **match exactly** the SHA-256 at the top of this page. If it does not, do not
run the file — download it again.

## 2. Install — four steps

1. Double-click `BoxFox-Desktop-Alpha-0.1.0-Setup.exe`.
2. Windows shows **"Windows protected your PC"** because the alpha is unsigned. Click **More info** →
   **Run anyway**.
3. Select **Only for me**, click **Next**, keep the default install folder and click **Next** again.
4. Click **Install** and wait a few minutes (the file is ~167 MB). When it finishes the app does **not**
   open by itself — click **Finish**.

After the install you have:

- The application in `%LOCALAPPDATA%\Programs\boxfox-desktop` (you can change this on the folder page)
- A Desktop and Start Menu shortcut named `BoxFox Desktop (Alpha)`
- An entry named `BoxFox Desktop (Alpha)` under **Settings → Apps → Installed apps**

## 3. First launch

1. Press Start, type `BoxFox`, and select **BoxFox Desktop (Alpha)**.
2. The first launch takes a few seconds: the app creates its profile and allocates internal ports for the
   router and the harness.
3. The window shows the web UI. A **tray** icon also appears at the right end of the taskbar.
4. Type a question into the chat box. A reply means the router and the harness are running.

No command-line window opens, and you do not have to install anything else.

## 4. Choose the run mode: `host` or `docker`

- **The default is `host`**: it runs immediately, with no Docker.
- To use **Docker** (sandbox in a container): open
  `%LOCALAPPDATA%\BoxFoxDesktopAlpha\desktop-settings.json`, change `"executionMode": "host"` to
  `"docker"`, save, then quit and reopen the app. Docker Desktop must be running.
- If Docker is not ready, the app **falls back to `host`** and writes the reason into the log and the
  diagnostics file. The app never reports a fake `docker`.

| Mode | Requires | Where the agent runs |
|---|---|---|
| `host` | nothing | Directly on Windows, under your own account |
| `docker` | Docker Desktop running | In the container `boxfox-desktop-<profile>` |

## 5. Where your data lives

Everything sits in **one** folder, not scattered into `Program Files` or the registry:

```
%LOCALAPPDATA%\BoxFoxDesktopAlpha\
  machine.json            internal ports + the token of this machine
  desktop-settings.json   run mode (host | docker)
  profile\                harness, router and UI data (including chat history)
  logs\                   router and harness logs
  diagnostics\            the "Export diagnostics" zip files
```

## 6. When you need support

Click the tray icon → **Sao lưu chẩn đoán** (Export diagnostics). The app collects everything into **one**
zip file under `%LOCALAPPDATA%\BoxFoxDesktopAlpha\diagnostics\` and opens Explorer with it selected. Send
that zip when you report a problem. The file contains **no** token or API key (every line containing
`key`, `token`, `secret`, `authorization` or `password` is replaced with `[REDACTED]`).

## 7. Uninstall

1. **Settings → Apps → Installed apps** → `BoxFox Desktop (Alpha)` → **Uninstall**.
2. The program and the shortcuts disappear. **Your data is kept** in `%LOCALAPPDATA%\BoxFoxDesktopAlpha`.
3. Installing again later reuses the same profile.
4. To remove everything, delete the folder `%LOCALAPPDATA%\BoxFoxDesktopAlpha` by hand.

## 8. Four things to know before you use it

1. **Alpha, unsigned.** Windows SmartScreen will warn you; that is expected. There is no auto-update yet.
2. **`host` mode has no operating-system-level sandbox.** The agent runs under your Windows account:
   anything you can read or write, the agent can read or write. Commands really run on your machine; the
   app leaves the default permission level at **ask first**.
3. **CUA (mouse/keyboard/screen) is OFF by default.** If you turn it on yourself, the agent drives your
   real mouse and keyboard, and screen captures are sent to the model provider. Do not leave sensitive
   windows open while CUA is on.
4. **The way out:** tray → **Dừng khẩn** (Emergency stop) stops the pending action and returns control to you.

## 9. Quick troubleshooting

| Symptom | What to do |
|---|---|
| SmartScreen blocks the Setup file | **More info** → **Run anyway** |
| No tray icon | The app is still running: reopen it from the Start Menu. If the log has `[desktop] no tray; closing the window will quit the app.`, then closing the window quits the app |
| The app opens but chat does not answer | Open `logs\harness.stderr.log`; attach the diagnostics file when you report the problem |
| You want to change the run mode | Edit `desktop-settings.json` and reopen the app (section 4) |
| It is installed but something still asks for Node/Python | Nothing to install: the runtime is inside `resources\runtime\`. Send the diagnostics file if the app reports it missing |
| Reinstalling the same version | Safe: the installer keeps the existing profile and does not reissue ports or tokens |
