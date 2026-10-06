; BoxFox Desktop (Alpha) — NSIS hooks (plan §6 PR-2 / D3).
;
; electron-builder picks this file up automatically (buildResources = build/, so it looks
; for build/installer.nsh) and inserts the macros below only if they exist, so every hook
; here is optional. Keep it that way: the default electron-builder behaviour already
; covers the shortcuts, the uninstall entry and the "app is running" check.
;
; Per-user install (perMachine: false): shortcuts and data live in the installing user's
; profile, and the installer never asks for administrator rights.

!macro customInstall
  ; Create the per-user data directory up front so the first launch can write logs/,
  ; machine.json and the diagnostics folder without racing directory creation.
  ; %LOCALAPPDATA%\BoxFoxDesktopAlpha is the profile root (see profile.ts).
  SetShellVarContext current
  CreateDirectory "$LOCALAPPDATA\BoxFoxDesktopAlpha"
!macroend

!macro customUnInstall
  ; Deliberately empty: uninstalling removes the program files and the shortcuts, but
  ; NEVER %LOCALAPPDATA%\BoxFoxDesktopAlpha. That folder holds the profile — machine.json
  ; (the per-machine admin token and the four loopback ports), settings.json, logs/,
  ; diagnostics/, recovery/ and audit/. Deleting it would lock the user out of their own
  ; history and orphan the sandbox container, so the data survives an uninstall and a
  ; reinstall picks it up again.
  ; `deleteAppDataOnUninstall` stays false in electron-builder.yml for the same reason.
!macroend
