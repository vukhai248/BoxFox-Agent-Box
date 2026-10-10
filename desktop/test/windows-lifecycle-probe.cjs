// Opt-in Windows integration probe; runs the real entry point with isolated data.
// Usage: electron test/windows-lifecycle-probe.cjs <absolute probe root>
const { app, BrowserWindow } = require('electron')
const fs = require('node:fs')
const path = require('node:path')
const { spawn } = require('node:child_process')
const root = path.resolve(process.argv[2])
fs.mkdirSync(root, { recursive: true })
app.setPath('userData', path.join(root, 'electron-data'))
process.env.LOCALAPPDATA = root
// LOCALAPPDATA alone does not isolate PermissionPolicy's user layer or Path.home().
const testHome = path.join(root, 'test-home')
fs.mkdirSync(testHome, { recursive: true })
process.env.USERPROFILE = testHome
process.env.HOME = testHome
const profile = path.join(root, 'BoxFoxDesktopAlpha')
const lockFile = path.join(profile, 'desktop.lock')
const second = process.argv.includes('--second')
const packagedResources = process.env.BOXFOX_PROBE_PACKAGED_RESOURCES
if (packagedResources) {
  Object.defineProperty(app, 'isPackaged', { value: true })
  Object.defineProperty(process, 'resourcesPath', { value: path.resolve(packagedResources) })
}
if (process.env.BOXFOX_PROBE_IMPORTTIME === '1') {
  const supervisor = require('../dist/supervisor.js')
  const buildSpecs = supervisor.buildServiceSpecs
  supervisor.buildServiceSpecs = (...args) => {
    const specs = buildSpecs(...args)
    specs.harness.args.unshift('-X', 'importtime')
    return specs
  }
}
if (!second) {
  fs.mkdirSync(profile, { recursive: true })
  // A live PID that does not own Electron's native lock must not prevent recovery.
  fs.writeFileSync(lockFile, JSON.stringify({ app: 'boxfox-desktop', pid: process.pid, startedAt: '2020-01-01' }))
}
require(packagedResources ? path.join(packagedResources, 'app.asar', 'dist', 'main.js') : '../dist/main.js')
if (!second) {
  const started = performance.now()
  const report = { startedAt: new Date().toISOString(), pid: process.pid, events: [], samples: [], servicePids: [], requests: [], rendererLatency: [] }
  app.on('web-contents-created', (_event, contents) => {
    contents.session.webRequest.onBeforeRequest((details, callback) => {
      const url = new URL(details.url)
      report.requests.push({ elapsedMs: Math.round(performance.now() - started), method: details.method, path: url.pathname })
      callback({})
    })
  })
  const mark = (phase, extra = {}) => report.events.push({ phase, elapsedMs: Math.round(performance.now() - started), ...extra })
  const save = () => fs.writeFileSync(path.join(root, 'lifecycle.json'), JSON.stringify(report, null, 2))
  const delay = ms => new Promise(resolve => setTimeout(resolve, ms))
  const waitFor = async predicate => {
    const deadline = Date.now() + 90000
    while (!predicate()) {
      if (Date.now() >= deadline) throw new Error('Probe timed out waiting for window/state')
      await delay(100)
    }
  }
  const sampler = setInterval(() => {
    report.samples.push({ elapsedMs: Math.round(performance.now() - started), metrics: app.getAppMetrics().map(m => ({ pid: m.pid, type: m.type, cpu: m.cpu.percentCPUUsage, memory: m.memory.workingSetSize })) })
  }, 500)
  app.on('quit', () => { clearInterval(sampler); mark('quit'); save() })
  // app.exit skips quit; process exit is also observed by the parent test runner.
  process.on('exit', () => { mark('process-exit', { lockExists: fs.existsSync(lockFile) }); save() })
  app.whenReady().then(async () => {
    try {
      await waitFor(() => BrowserWindow.getAllWindows().length > 0)
      const win = BrowserWindow.getAllWindows()[0]
      await waitFor(() => !win.webContents.isLoading())
      mark('ui-loaded', { windowCount: BrowserWindow.getAllWindows().length })
      const machine = JSON.parse(fs.readFileSync(path.join(profile, 'machine.json')))
      const health = await fetch(`http://127.0.0.1:${machine.ports.gateway}/api/desktop/health`).then(r => r.json())
      // Diagnostics are a text report, not a structured supervisor result.
      report.health = health.services
      report.servicePids = [...health.services.matchAll(/(?:router|harness)\s*: pid=(\d+)/g)].map(m => Number(m[1]))
      if (!/router\s*: .*healthy=true/.test(health.services) || !/harness\s*: .*healthy=true/.test(health.services)) throw new Error('Real services did not become healthy')
      if (process.env.BOXFOX_PROBE_PERMISSIONS === '1') {
        const origin = `http://127.0.0.1:${machine.ports.gateway}`
        const api = async (route, body, method = 'POST') => {
          const response = await fetch(origin + route, {
            headers: { Origin: origin, 'Content-Type': 'application/json' },
            ...(body ? { method, body: JSON.stringify(body) } : {}),
          })
          if (!response.ok) throw new Error(`Permission probe HTTP ${response.status}`)
          return response.json()
        }
        const initial = await api('/api/agent/permissions')
        const userLayer = initial.layers.find(layer => layer.layer === 'user')
        if (!userLayer || !path.resolve(userLayer.file).toLowerCase().startsWith(testHome.toLowerCase() + path.sep)) throw new Error('Probe user permission layer is not isolated; refusing writes')
        if (JSON.stringify(initial.modes) !== JSON.stringify(['ask', 'auto', 'trusted']) || !initial.scopeDerived) throw new Error('Packaged permission contract is stale')
        report.permissions = { modes: initial.modes, checks: [] }
        for (const mode of ['ask', 'auto', 'trusted']) {
          const snapshot = await api('/api/agent/permissions', { mode, network: 'restricted' }, 'PUT')
          if (snapshot.mode !== mode || snapshot.scope !== (mode === 'trusted' ? 'machine' : 'workspace')) throw new Error('Packaged level/scope mismatch')
          const decision = await api('/api/agent/permissions/decide', { tool: 'terminal_exec', args: { command: 'curl https://example.com' } })
          if (decision.outcome !== 'ask') throw new Error('Network choice was bypassed')
          const floor = await api('/api/agent/permissions/decide', { tool: 'terminal_exec', args: { command: 'format C:' } })
          if (floor.outcome !== 'deny') throw new Error('Safety floor was bypassed')
          report.permissions.checks.push({ mode, scope: snapshot.scope, network: decision.outcome, floor: floor.outcome })
        }
        await api('/api/agent/permissions', { mode: 'ask', network: 'restricted' }, 'PUT')
        await delay(1000)
        report.permissions.ui = await win.webContents.executeJavaScript(`(async () => {
          const chip = document.querySelector('[data-testid="composer-permission"]');
          if (!chip) throw new Error('Permission chip missing');
          chip.click(); await new Promise(r => setTimeout(r, 100));
          const labels = [...document.querySelectorAll('[role="menuitemradio"]')].map(b => b.innerText);
          const scopeChooser = !!document.querySelector('[data-testid="composer-permission-scope"]');
          chip.click(); return { labels, scopeChooser };
        })()`)
        if (report.permissions.ui.labels.length !== 5 || report.permissions.ui.scopeChooser || !report.permissions.ui.labels.some(label => label.startsWith('Request approval'))) throw new Error('Packaged permission UI mismatch')
        mark('packaged-permissions-verified')
      }
      if (process.env.BOXFOX_PROBE_CHAT === '1') {
        // Isolated profile only: never copy or modify the user's provider credentials.
        const origin = `http://127.0.0.1:${machine.ports.gateway}`
        const api = async (route, body) => {
          const response = await fetch(origin + route, {
            headers: { Origin: origin, 'Content-Type': 'application/json' },
            ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}),
            signal: AbortSignal.timeout(65000),
          })
          if (!response.ok) throw new Error(`Chat probe ${route.split('/').slice(0, 4).join('/')} HTTP ${response.status}`)
          return response.json()
        }
        const connection = await api('/api/router/connections', { providerId: 'opencode', apiKey: 'public',
          name: 'Isolated desktop regression probe' })
        await api(`/api/router/connections/${connection.id}/models/refresh`, {})
        const state = await api('/api/router/state')
        const model = state.connections.find(c => c.id === connection.id)?.models.find(m => m.id === 'mimo-v2.6-flash-free')
        if (!model) throw new Error('OpenCode MiMo model unavailable for live regression probe')
        const session = await api('/api/agent/sessions', { connectionId: connection.id, modelId: model.id,
          skills: [], tools: [], maxSteps: 1, maxTokens: 128 })
        report.chat = { routerPort: machine.ports.router, harnessPort: machine.ports.harness,
          model: model.id, sessionId: session.id, contextWindow: session.config.contextWindow,
          providerContextWindow: model.contextWindow ?? null }
        // Provider can omit context metadata; do not reject the runtime's existing fallback.
        if (model.contextWindow > 0 && session.config.contextWindow !== model.contextWindow) throw new Error('Harness metadata did not come from the app router')
        await api(`/api/agent/sessions/${session.id}/turns`, { prompt: 'Reply exactly: OK. Do not use tools.' })
        const deadline = Date.now() + 65000
        let result
        do {
          await delay(250)
          result = await api(`/api/agent/sessions/${session.id}`)
        } while (['idle', 'running', 'queued'].includes(result.status) && Date.now() < deadline)
        report.chat.status = result.status
        report.chat.content = result.events?.filter(e => e.type === 'assistant').at(-1)?.data?.text
        report.chat.journalDegraded = Boolean(result.journal?.degraded)
        if (result.status !== 'completed' || !report.chat.content?.includes('OK')) throw new Error(`Packaged chat did not complete: ${result.status}`)
        mark('packaged-chat-completed', { routerPort: machine.ports.router })
      }
      // User reports the freeze AFTER the UI appears; include delayed polls/watchdog.
      const steadyMs = Number(process.env.BOXFOX_PROBE_STEADY_MS ?? 2000)
      const until = performance.now() + steadyMs
      while (performance.now() < until) {
        const before = performance.now()
        await win.webContents.executeJavaScript('performance.now()')
        report.rendererLatency.push({ elapsedMs: Math.round(performance.now() - started), latencyMs: Math.round(performance.now() - before) })
        await delay(250)
      }
      mark('post-ui-observed', { steadyMs })
      win.close()
      await delay(250)
      if (win.isDestroyed() || win.isVisible()) throw new Error('Close did not hide live tray window')
      mark('close-hidden')
      const secondInstance = spawn(process.execPath, [__filename, root, '--second'], { windowsHide: true, stdio: 'ignore', env: process.env })
      const secondExit = new Promise((resolve, reject) => { secondInstance.once('exit', code => code === 0 ? resolve() : reject(new Error(`Second instance exit ${code}`))); secondInstance.once('error', reject) })
      await waitFor(() => win.isVisible())
      mark('second-instance-restored', { windowCount: BrowserWindow.getAllWindows().length })
      await secondExit
      mark('second-instance-exited')
      await delay(2000)
      mark('quit-requested')
      report.passed = true
      save()
      app.quit()
    } catch (error) {
      report.passed = false
      report.error = error.message
      save()
      app.quit()
    }
  })
}
