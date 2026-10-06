/**
 * Electron entry point of BoxFox Desktop (Alpha).
 *
 * D2 scope: profile → single-instance lock → mode selection → supervisor (router +
 * harness) → same-origin gateway → BrowserWindow pointed at the gateway.
 *
 * D3 scope: the window lives in the tray. Closing it only hides it (the agent keeps
 * running); the tray menu carries the emergency controls (`POST /api/agent/desktop/lease`
 * through the harness), the data folder, the diagnostics bundle and the real quit.
 */

import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, shell, Tray } from 'electron'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { describeControlResult, requestDesktopControl, type DesktopControlAction } from './desktop-control'
import {
  collectDiagnostics,
  fetchHarnessHealth,
  formatDiagnostics,
  runtimeBundleFromManifest,
  writeDiagnosticsArchive,
} from './diagnostics'
import { createGateway, type Gateway } from './gateway'
import { decideMode, ensureSandboxImage, probeDocker, startBoxContainer, stopBoxContainer, writeComposeOverride, type DockerProbe } from './mode'
import { dockerContextDir, harnessDir, readBuildManifest, resolveResourcesDir, runtimeDir, trayIconPath, uiDir } from './paths'
import { openProfile, profileRoot, readDesktopSettings, type ExecutionMode, type OpenProfileResult } from './profile'
import { acquireInstanceLock, AlreadyRunningError, buildServiceSpecs, Supervisor, type ServiceSpec } from './supervisor'
import { shouldHideOnClose, toggleWindowVisibility, trayMenuTemplate, TRAY_TOOLTIP, type TrayMenuHandlers } from './tray'

interface DesktopState {
  profile: OpenProfileResult
  supervisor: Supervisor
  gateway: Gateway
  boxStarted: boolean
  resourcesDir: string
  specs: { router: ServiceSpec; harness: ServiceSpec }
  mode: ExecutionMode
  modeReason: string
  docker: DockerProbe | null
  window: BrowserWindow | null
  tray: Tray | null
  trayActive: boolean
}

let state: DesktopState | null = null
let quitting = false
let refreshTrayMenu: (() => void) | null = null

function log(line: string): void {
  process.stdout.write(`${line}\n`)
}

function createWindow(url: string): BrowserWindow {
  const window = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    title: 'BoxFox Desktop (Alpha)',
    backgroundColor: '#0b0d10',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      spellcheck: false,
    },
  })
  // X closes the window, not the app: the agent keeps running in the tray. Without a tray
  // there is no way back to the window, so there the close goes through.
  window.on('close', (event) => {
    if (shouldHideOnClose(quitting, state?.trayActive ?? false)) {
      event.preventDefault()
      window.hide()
    }
  })
  window.on('show', () => refreshTrayMenu?.())
  window.on('hide', () => refreshTrayMenu?.())
  void window.loadURL(url)
  return window
}

/** The live window, recreated when the old one was really destroyed. */
function ensureWindow(): BrowserWindow | null {
  const current = state
  if (!current) return null
  if (current.window && !current.window.isDestroyed()) return current.window
  current.window = createWindow(current.gateway.url)
  return current.window
}

function toggleWindow(): void {
  const window = ensureWindow()
  if (!window) return
  toggleWindowVisibility(window)
  refreshTrayMenu?.()
}

function showNotice(title: string, detail: string): void {
  try {
    void dialog.showMessageBox({ type: 'warning', title, message: title, detail, buttons: ['OK'] })
  } catch (error) {
    log(`[desktop] could not show a message box: ${(error as Error).message}`)
  }
}

async function runControlAction(action: DesktopControlAction): Promise<void> {
  const current = state
  if (!current) return
  const ports = current.profile.machine.ports
  const result = await requestDesktopControl({
    baseUrl: `http://127.0.0.1:${ports.harness}`,
    action,
    reason: 'tray',
    origin: `http://127.0.0.1:${ports.gateway}`,
  })
  log(`[desktop] ${describeControlResult(result)}`)
  if (!result.ok) {
    const title = action === 'claim' ? 'Không trả được quyền cho agent' : 'Không gửi được lệnh Dừng khẩn'
    showNotice(title, describeControlResult(result))
  }
}

async function exportDiagnosticsBundle(): Promise<void> {
  const current = state
  if (!current) return
  const { profile, resourcesDir, supervisor, specs } = current
  const ports = profile.machine.ports
  const origin = `http://127.0.0.1:${ports.gateway}`
  const health = await fetchHarnessHealth({ baseUrl: `http://127.0.0.1:${ports.harness}`, origin })
  const manifest = readBuildManifest(resourcesDir)
  const archive = writeDiagnosticsArchive({
    layout: profile.layout,
    version: app.getVersion(),
    commit: typeof manifest?.commit === 'string' ? manifest.commit : null,
    mode: current.mode,
    modeReason: current.modeReason,
    ports,
    runtime: { node: specs.router.command, python: specs.harness.command },
    dataPaths: { harness: profile.layout.harness, router: profile.layout.router, ui: profile.layout.ui },
    runtimeDir: runtimeDir(resourcesDir),
    runtimeBundle: runtimeBundleFromManifest(manifest),
    health,
    services: supervisor.status(),
    docker: current.docker,
  })
  log(`[desktop] diagnostics: ${archive.zipPath} (${archive.entries.length} files, ${archive.bytes} bytes)`)
  shell.showItemInFolder(archive.zipPath)
}

function createTray(window: BrowserWindow, resourcesDir: string): Tray | null {
  const handlers: TrayMenuHandlers = {
    toggleWindow,
    claimControl: () => void runControlAction('claim'),
    emergencyStop: () => void runControlAction('stop'),
    openDataFolder: () => {
      const root = state?.profile.layout.root
      if (root) void shell.openPath(root)
    },
    exportDiagnostics: () => void exportDiagnosticsBundle(),
    quit: () => {
      quitting = true
      app.quit()
    },
  }
  try {
    const iconFile = trayIconPath(resourcesDir)
    const image = fs.existsSync(iconFile) ? nativeImage.createFromPath(iconFile) : nativeImage.createEmpty()
    const tray = new Tray(image)
    tray.setToolTip(TRAY_TOOLTIP)
    refreshTrayMenu = () => {
      tray.setContextMenu(Menu.buildFromTemplate(trayMenuTemplate(handlers, { windowVisible: window.isVisible() })))
    }
    refreshTrayMenu()
    tray.on('click', () => toggleWindow())
    return tray
  } catch (error) {
    refreshTrayMenu = null
    log(`[desktop] tray unavailable: ${(error as Error).message}`)
    return null
  }
}

async function start(): Promise<void> {
  const profile = await openProfile({ root: profileRoot() })
  const lock = acquireInstanceLock(profile.layout.lockFile)
  app.on('will-quit', () => lock.release())
  if (profile.reallocated.length > 0) {
    log(`[desktop] re-allocated busy port(s): ${profile.reallocated.join(', ')}`)
  }
  const resources = resolveResourcesDir({
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    appDir: __dirname,
  })
  const settings = readDesktopSettings(profile.layout)
  const probe = await probeDocker({})
  const decision = decideMode(settings.executionMode, probe)
  log(`[desktop] mode: ${decision.mode} — ${decision.reason}`)
  let boxStarted = false
  if (decision.mode === 'docker') {
    if (!probe.image) {
      await ensureSandboxImage({
        contextDir: dockerContextDir(resources),
        onProgress: (line) => log(line),
      })
    }
    const override = writeComposeOverride(profile.layout.profile, {
      profileKey: profile.machine.adminToken.slice(0, 12),
      ports: profile.machine.ports,
      adminToken: profile.machine.adminToken,
      skillsDir: path.join(harnessDir(resources), 'backend', 'src', 'agentbox', 'vendor', 'hermes'),
    })
    const result = await startBoxContainer({
      composeFile: path.join(dockerContextDir(resources), 'docker-compose.yml'),
      overrideFile: override,
      onProgress: (line) => log(`[box] ${line}`),
    })
    boxStarted = result.code === 0
    if (!boxStarted) log(`[desktop] could not start the sandbox container (exit ${result.code}); box surface unavailable.`)
  }
  const specs = buildServiceSpecs({
    layout: profile.layout,
    machine: profile.machine,
    resourcesDir: resources,
    runtimeDir: runtimeDir(resources),
    mode: decision.mode,
  })
  const supervisor = new Supervisor({
    layout: profile.layout,
    machine: profile.machine,
    resourcesDir: resources,
    runtimeDir: runtimeDir(resources),
    mode: decision.mode,
    specs,
    log,
    watchdogIntervalMs: 15_000,
  })
  const status = await supervisor.start()
  if (!status.services.router.healthy || !status.services.harness.healthy) {
    log('[desktop] a service failed to become healthy; opening the window anyway so logs are reachable.')
  }
  const manifest = readBuildManifest(resources)
  const gateway = createGateway({
    port: profile.machine.ports.gateway,
    uiDir: uiDir(resources),
    mode: decision.mode,
    upstreams: {
      harness: `http://127.0.0.1:${profile.machine.ports.harness}`,
      router: `http://127.0.0.1:${profile.machine.ports.router}`,
      box: `http://127.0.0.1:${profile.machine.ports.box}`,
    },
    identity: {
      app: 'BoxFox Desktop (Alpha)',
      version: app.getVersion(),
      mode: decision.mode,
      ports: profile.machine.ports,
      adminToken: profile.machine.adminToken,
    },
    status: () =>
      formatDiagnostics(
        collectDiagnostics({
          version: app.getVersion(),
          commit: typeof manifest?.commit === 'string' ? manifest.commit : null,
          mode: decision.mode,
          modeReason: decision.reason,
          profileRoot: profile.layout.root,
          ports: profile.machine.ports,
          node: specs.router.command,
          python: specs.harness.command,
          services: supervisor.status(),
          docker: probe,
        }),
      ),
    log,
  })
  await gateway.listen()
  ipcMain.handle('boxfox:identity', () => ({
    app: 'BoxFox Desktop (Alpha)',
    version: app.getVersion(),
    mode: decision.mode,
    ports: profile.machine.ports,
    adminToken: profile.machine.adminToken,
  }))
  state = {
    profile,
    supervisor,
    gateway,
    boxStarted,
    resourcesDir: resources,
    specs,
    mode: decision.mode,
    modeReason: decision.reason,
    docker: probe,
    window: null,
    tray: null,
    trayActive: false,
  }
  const window = createWindow(gateway.url)
  state.window = window
  const tray = createTray(window, resources)
  state.tray = tray
  state.trayActive = tray !== null
  if (tray === null) log('[desktop] no tray; closing the window will quit the app.')
}

async function shutdown(): Promise<void> {
  const current = state
  state = null
  refreshTrayMenu = null
  if (!current) return
  current.tray?.destroy()
  try {
    await current.gateway.close()
  } catch (error) {
    log(`[desktop] gateway shutdown failed: ${(error as Error).message}`)
  }
  try {
    await current.supervisor.stop()
  } catch (error) {
    log(`[desktop] supervisor shutdown failed: ${(error as Error).message}`)
  }
  if (current.boxStarted) {
    await stopBoxContainer({
      composeFile: path.join(dockerContextDir(current.resourcesDir), 'docker-compose.yml'),
      overrideFile: path.join(current.profile.layout.profile, 'docker-compose.override.yml'),
      onProgress: (line) => log(`[box] ${line}`),
    })
  }
}

void app.whenReady().then(async () => {
  try {
    await start()
  } catch (error) {
    if (error instanceof AlreadyRunningError) {
      dialog.showErrorBox('BoxFox Desktop is already running', error.message)
      app.exit(0)
      return
    }
    dialog.showErrorBox('BoxFox Desktop could not start', (error as Error).message)
    app.exit(1)
  }
})

app.on('window-all-closed', () => {
  // With a tray the app stays alive (the agent keeps running). Without one, closing the
  // last window must still quit — otherwise the process would be unkillable.
  if (state === null || !state.trayActive) app.quit()
})

app.on('before-quit', (event) => {
  if (quitting || state === null) return
  event.preventDefault()
  quitting = true
  void (async () => {
    try {
      await shutdown()
    } finally {
      app.exit(0)
    }
  })()
})

export { start as startDesktop, shutdown as shutdownDesktop }
