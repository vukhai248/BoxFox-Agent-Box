/**
 * Electron entry point of BoxFox Desktop (Alpha).
 *
 * D2 scope: profile → single-instance lock → mode selection → supervisor (router +
 * harness) → same-origin gateway → BrowserWindow pointed at the gateway. The tray,
 * the diagnostics window, the emergency CUA stop and the installer refinements are
 * D3 and deliberately absent here.
 */

import { app, BrowserWindow, dialog, ipcMain } from 'electron'
import * as path from 'node:path'
import { collectDiagnostics, formatDiagnostics } from './diagnostics'
import { createGateway, type Gateway } from './gateway'
import { decideMode, ensureSandboxImage, probeDocker, startBoxContainer, stopBoxContainer, writeComposeOverride } from './mode'
import { dockerContextDir, harnessDir, readBuildManifest, resolveResourcesDir, runtimeDir, uiDir } from './paths'
import { openProfile, profileRoot, readDesktopSettings, type OpenProfileResult } from './profile'
import { acquireInstanceLock, AlreadyRunningError, buildServiceSpecs, Supervisor } from './supervisor'

interface DesktopState {
  profile: OpenProfileResult
  supervisor: Supervisor
  gateway: Gateway
  boxStarted: boolean
  resourcesDir: string
}

let state: DesktopState | null = null
let quitting = false

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
  void window.loadURL(url)
  return window
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
  state = { profile, supervisor, gateway, boxStarted, resourcesDir: resources }
  createWindow(gateway.url)
}

async function shutdown(): Promise<void> {
  const current = state
  state = null
  if (!current) return
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
  app.quit()
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
