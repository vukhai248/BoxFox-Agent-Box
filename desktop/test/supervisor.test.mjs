/**
 * supervisor.ts — single-instance lock, service environment, spawn specs and the
 * restart/stop behaviour. Plan §6 PR-2 / D2: "single-instance lock theo profile; spawn
 * router (node bundle) + harness (python bundle) với BOXFOX_* trỏ vào profile; health
 * poll; restart có backoff; dừng sạch theo cây tiến trình."
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import * as fs from 'node:fs'
import * as http from 'node:http'
import * as os from 'node:os'
import * as path from 'node:path'

import { ensureLayout, openProfile } from '../dist/profile.js'
import {
  AlreadyRunningError,
  Supervisor,
  acquireInstanceLock,
  backoffDelay,
  buildServiceSpecs,
  bundledNodeBinary,
  bundledPythonBinary,
  serviceEnv,
  stopProcessTree,
  waitForHttp,
} from '../dist/supervisor.js'

function tempDir(t, prefix = 'boxfox-supervisor-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

function alive(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return error.code === 'EPERM'
  }
}

async function deadPid() {
  const child = spawn(process.execPath, ['-e', 'process.exit(0)'], { stdio: 'ignore' })
  await new Promise((resolve) => child.on('exit', resolve))
  return child.pid
}

test('the instance lock is exclusive and releasable', (t) => {
  const dir = tempDir(t)
  const lockFile = path.join(dir, 'desktop.lock')
  const first = acquireInstanceLock(lockFile)
  assert.equal(first.pid, process.pid)
  assert.ok(fs.existsSync(lockFile))

  assert.throws(() => acquireInstanceLock(lockFile), (error) => {
    assert.ok(error instanceof AlreadyRunningError)
    assert.equal(error.code, 'ALREADY_RUNNING')
    assert.equal(error.pid, process.pid)
    assert.equal(error.lockFile, lockFile)
    return true
  })

  first.release()
  first.release() // idempotent
  assert.ok(!fs.existsSync(lockFile))
  const second = acquireInstanceLock(lockFile)
  second.release()
})

test('a lock left behind by a dead process is taken over', async (t) => {
  const dir = tempDir(t)
  const lockFile = path.join(dir, 'desktop.lock')
  const pid = await deadPid()
  fs.writeFileSync(lockFile, JSON.stringify({ app: 'boxfox-desktop', pid, startedAt: new Date().toISOString() }))

  const handle = acquireInstanceLock(lockFile)
  assert.equal(handle.pid, process.pid)
  assert.equal(JSON.parse(fs.readFileSync(lockFile, 'utf8')).pid, process.pid, 'the stale record is replaced')
  handle.release()
})

test('serviceEnv drops every inherited BOXFOX_* and points the services at the profile', async (t) => {
  const root = tempDir(t)
  const layout = ensureLayout(root)
  const { machine } = await openProfile({ root })
  const env = serviceEnv(
    { PATH: '/usr/bin', BOXFOX_API_KEY: 'leaked', BOXFOX_ROUTER_PORT: '3101', BOXFOX_AGENT_DATA_DIR: '/tmp/dev', KEEP: 'yes' },
    layout,
    machine,
    'host',
  )
  assert.equal(env.PATH, '/usr/bin')
  assert.equal(env.KEEP, 'yes')
  assert.equal(env.BOXFOX_DESKTOP_PROFILE, root)
  assert.equal(env.BOXFOX_API_KEY, machine.adminToken, 'the per-machine token replaces the development token')
  assert.equal(env.BOXFOX_EXECUTION_MODE, 'host')
  assert.equal(env.BOXFOX_ROUTER_PORT, undefined, 'inherited ports must not leak into the child')
  assert.equal(env.BOXFOX_AGENT_DATA_DIR, undefined)
  assert.equal(env.BOXFOX_UI_ORIGINS, `http://127.0.0.1:${machine.ports.gateway},http://localhost:${machine.ports.gateway}`)
  assert.equal(env.BOXFOX_ROUTER_URL, `http://127.0.0.1:${machine.ports.router}`)
  assert.equal(env.BOXFOX_BOX_URL, `http://127.0.0.1:${machine.ports.box}`)
})

test('buildServiceSpecs uses the bundled node/python and the profile directories', async (t) => {
  const root = tempDir(t)
  const layout = ensureLayout(root)
  const { machine } = await openProfile({ root })
  const resourcesDir = '/opt/boxfox/resources'
  const runtimeDir = path.join(resourcesDir, 'runtime')
  const specs = buildServiceSpecs({
    layout,
    machine,
    resourcesDir,
    runtimeDir,
    mode: 'docker',
    platform: 'win32',
    env: { PATH: 'C:\\Windows' },
  })

  assert.equal(specs.router.command, bundledNodeBinary(runtimeDir, 'win32'))
  assert.equal(specs.router.command, path.join(runtimeDir, 'node', 'node.exe'))
  assert.equal(specs.router.args[0], path.join(resourcesDir, 'router', 'src', 'main.mjs'))
  assert.ok(specs.router.args.includes('--production'))
  assert.equal(specs.router.cwd, path.join(resourcesDir, 'router'))
  assert.equal(specs.router.env.BOXFOX_ROUTER_PORT, String(machine.ports.router))
  assert.equal(specs.router.env.BOXFOX_ROUTER_DATA_DIR, layout.router)
  assert.equal(specs.router.healthUrl, `http://127.0.0.1:${machine.ports.router}/api/router/health`)

  assert.equal(specs.harness.command, bundledPythonBinary(runtimeDir, 'win32'))
  assert.equal(specs.harness.command, path.join(runtimeDir, 'python', 'python.exe'))
  assert.equal(specs.harness.args[0], path.join(resourcesDir, 'harness', 'scripts', 'run-harness.py'))
  assert.equal(specs.harness.cwd, path.join(resourcesDir, 'harness'))
  assert.equal(specs.harness.env.BOXFOX_HARNESS_PORT, String(machine.ports.harness))
  assert.equal(specs.harness.env.BOXFOX_AGENT_DATA_DIR, layout.harness)
  assert.equal(specs.harness.env.PYTHONPATH, path.join(resourcesDir, 'harness', 'backend', 'src'))
  assert.equal(specs.harness.env.PYTHONUTF8, '1')
  assert.equal(specs.harness.healthUrl, `http://127.0.0.1:${machine.ports.harness}/api/agent/health`)
  assert.equal(specs.harness.env.BOXFOX_EXECUTION_MODE, 'docker')
  assert.equal(bundledPythonBinary(runtimeDir, 'linux'), path.join(runtimeDir, 'python', 'bin', 'python3'))
})

test('backoffDelay grows exponentially and stops at the ceiling', () => {
  assert.equal(backoffDelay(0), 1000)
  assert.equal(backoffDelay(1), 2000)
  assert.equal(backoffDelay(2), 4000)
  assert.equal(backoffDelay(3, 1000, 5000), 5000)
  assert.equal(backoffDelay(30), 30_000)
})

test('waitForHttp resolves false instead of throwing when nothing answers', async (t) => {
  const server = http.createServer((_req, res) => res.writeHead(200).end('ok'))
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  t.after(
    () =>
      new Promise((resolve) => {
        server.closeAllConnections()
        server.close(resolve)
      }),
  )
  const port = server.address().port

  assert.equal(await waitForHttp(`http://127.0.0.1:${port}/health`, { timeoutMs: 2000, intervalMs: 50 }), true)
  const dead = http.createServer(() => {})
  await new Promise((resolve) => dead.listen(0, '127.0.0.1', resolve))
  const deadPort = dead.address().port
  await new Promise((resolve) => dead.close(resolve))
  assert.equal(await waitForHttp(`http://127.0.0.1:${deadPort}/health`, { timeoutMs: 300, intervalMs: 50 }), false)

  let calls = 0
  const flaky = await waitForHttp(`http://127.0.0.1:${port}/health`, {
    timeoutMs: 2000,
    intervalMs: 10,
    fetchImpl: async () => {
      calls += 1
      if (calls < 3) return { ok: false, status: 503, arrayBuffer: async () => new ArrayBuffer(0) }
      return { ok: true, status: 200, arrayBuffer: async () => new ArrayBuffer(0) }
    },
  })
  assert.equal(flaky, true)
  assert.equal(calls, 3, 'a not-yet-ready service is retried, not fatal')
})

test('stopProcessTree kills a child and its descendants', async (t) => {
  if (process.platform === 'win32') t.skip('POSIX process groups only')
  const marker = path.join(tempDir(t), 'grandchild.pid')
  const script = `const { spawn } = require('node:child_process'); const fs = require('node:fs');
const grandchild = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });
fs.writeFileSync(${JSON.stringify(marker)}, String(grandchild.pid));
setInterval(() => {}, 1000);`
  const child = spawn(process.execPath, ['-e', script], { stdio: 'ignore', detached: true })
  await new Promise((resolve) => setTimeout(resolve, 500))
  const grandchildPid = Number(fs.readFileSync(marker, 'utf8'))
  assert.ok(alive(grandchildPid), 'the grandchild should be running')

  await stopProcessTree(child, 500)
  await new Promise((resolve) => setTimeout(resolve, 300))
  assert.ok(!alive(grandchildPid), 'the grandchild must die with the service tree')
  assert.ok(!alive(child.pid), 'the service process must be gone')
})

/** Spawn a real HTTP server through a service spec, so the Supervisor is exercised end to end. */
function specFor(name, healthPath, port, logDir) {
  const script = `const http = require('node:http');
const server = http.createServer((req, res) => { res.writeHead(200, { 'content-type': 'application/json' }); res.end(JSON.stringify({ service: ${JSON.stringify(name)} })); });
server.listen(Number(process.env.PORT), '127.0.0.1', () => console.log('ready'));`
  return {
    name,
    command: process.execPath,
    args: ['-e', script],
    cwd: logDir,
    env: { PORT: String(port) },
    healthUrl: `http://127.0.0.1:${port}${healthPath}`,
  }
}

test('the Supervisor starts both services, reports health and stops them cleanly', async (t) => {
  const root = tempDir(t)
  const layout = ensureLayout(root)
  const { machine } = await openProfile({ root })
  const specs = {
    router: specFor('router', '/api/router/health', machine.ports.router, root),
    harness: specFor('harness', '/api/agent/health', machine.ports.harness, root),
  }
  const supervisor = new Supervisor({
    layout,
    machine,
    mode: 'host',
    resourcesDir: root,
    runtimeDir: root,
    specs,
    readyTimeoutMs: 20_000,
  })
  const status = await supervisor.start()
  assert.equal(status.running, true)
  assert.equal(status.services.router.healthy, true)
  assert.equal(status.services.harness.healthy, true)
  assert.ok(status.services.router.pid > 0)
  assert.ok(fs.existsSync(path.join(layout.logs, 'router.stdout.log')), 'service output is captured under logs/')

  const pids = [status.services.router.pid, status.services.harness.pid]
  await supervisor.stop()
  const stopped = supervisor.status()
  assert.equal(stopped.running, false)
  for (const name of ['router', 'harness']) {
    assert.equal(stopped.services[name].pid, null, `${name} must have no pid after stop()`)
    assert.equal(stopped.services[name].healthy, false)
    assert.equal(stopped.services[name].lastExit.signal, 'SIGTERM')
    assert.equal(stopped.services[name].restarts, 0, 'an intentional stop must not count as a restart')
  }
  await new Promise((resolve) => setTimeout(resolve, 300))
  for (const pid of pids) assert.ok(!alive(pid), `service ${pid} must be stopped`)
})

test('a service that dies unexpectedly is restarted with backoff', async (t) => {
  const root = tempDir(t)
  const layout = ensureLayout(root)
  const { machine } = await openProfile({ root })
  const counter = path.join(root, 'starts.txt')
  const script = `const fs = require('node:fs'); fs.appendFileSync(${JSON.stringify(counter)}, 'x'); process.exit(1);`
  const specs = {
    router: {
      name: 'router',
      command: process.execPath,
      args: ['-e', script],
      cwd: root,
      env: {},
      healthUrl: `http://127.0.0.1:${machine.ports.router}/api/router/health`,
    },
    harness: specFor('harness', '/api/agent/health', machine.ports.harness, root),
  }
  const supervisor = new Supervisor({
    layout,
    machine,
    mode: 'host',
    resourcesDir: root,
    runtimeDir: root,
    specs,
    readyTimeoutMs: 300,
    baseDelayMs: 50,
    maxDelayMs: 200,
    log: () => undefined,
  })
  await supervisor.start().catch(() => null)
  const status = supervisor.status()
  assert.equal(status.services.router.healthy, false)
  assert.ok(status.services.router.restarts >= 1, 'the crash is scheduled for a restart')
  await new Promise((resolve) => setTimeout(resolve, 600))
  assert.ok(fs.readFileSync(counter, 'utf8').length >= 2, 'the service is actually respawned')
  assert.ok(supervisor.status().services.router.lastExit, 'the failure is reported, not swallowed')
  await supervisor.stop()
})
