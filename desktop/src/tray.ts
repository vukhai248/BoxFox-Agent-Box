/**
 * Tray behaviour of BoxFox Desktop (Alpha) — plan §6 PR-2 / D3.
 *
 * The tray is the app's permanent home: closing the window hides it (the agent keeps
 * running), left-clicking the icon toggles the window, and the context menu carries the
 * emergency actions. This module holds the parts that can be tested without Electron:
 * the menu template, the show/hide toggle and the close rule. `main.ts` owns the
 * Electron objects (`Tray`, `Menu`, `nativeImage`).
 */

import type { MenuItemConstructorOptions } from 'electron'

export const TRAY_TOOLTIP = 'BoxFox Desktop (Alpha)'

export interface TrayWindow {
  isVisible(): boolean
  isMinimized?(): boolean
  show(): void
  hide(): void
  focus?(): void
  restore?(): void
}

export interface TrayMenuHandlers {
  /** Show the window when hidden, hide it when visible. */
  toggleWindow(): void
  /** `POST /api/agent/desktop/lease {"action":"claim","reason":"tray"}`. */
  claimControl(): void
  /** `POST /api/agent/desktop/lease {"action":"stop"}`. */
  emergencyStop(): void
  /** Open the profile directory (sessions, logs, machine.json) in the file manager. */
  openDataFolder(): void
  /** Write a diagnostics ZIP and reveal it in the file manager. */
  exportDiagnostics(): void
  /** Leave the app for real (never reached by closing the window). */
  quit(): void
}

export interface TrayMenuState {
  windowVisible: boolean
}

/** Show the window (restoring a minimised one) or hide it. Returns the new visibility. */
export function toggleWindowVisibility(win: TrayWindow): boolean {
  if (win.isVisible()) {
    win.hide()
    return false
  }
  if (win.isMinimized?.()) win.restore?.()
  win.show()
  win.focus?.()
  return true
}

/**
 * Closing the window only hides it; a real quit must go through `app.quit()`.
 *
 * `trayActive` is the escape hatch: with no tray icon there is no way to bring the
 * window back, so the close goes through and the app quits (see `window-all-closed`).
 */
export function shouldHideOnClose(quitting: boolean, trayActive = true): boolean {
  return !quitting && trayActive
}

/** The tray context menu, as data so tests can click it without Electron. */
export function trayMenuTemplate(
  handlers: TrayMenuHandlers,
  state: TrayMenuState = { windowVisible: true },
): MenuItemConstructorOptions[] {
  return [
    { label: state.windowVisible ? 'Ẩn cửa sổ' : 'Hiện cửa sổ', click: () => handlers.toggleWindow() },
    { type: 'separator' },
    { label: 'Trả quyền cho agent', click: () => handlers.claimControl() },
    { label: 'Dừng khẩn', click: () => handlers.emergencyStop() },
    { type: 'separator' },
    { label: 'Mở thư mục dữ liệu', click: () => handlers.openDataFolder() },
    { label: 'Sao lưu chẩn đoán', click: () => handlers.exportDiagnostics() },
    { type: 'separator' },
    { label: 'Thoát', click: () => handlers.quit() },
  ]
}
