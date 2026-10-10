/**
 * profile.ts — port allocation, persistence and the machine.json quarantine.
 * Plan §6 PR-2 / D2: "Cấp 4 cổng loopback trống lần đầu, lưu vào machine.json,
 * giữ nguyên các lần sau" + "Token admin riêng cho từng máy".
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as net from 'node:net'
import * as os from 'node:os'
import * as path from 'node:path'

import {
  PORT_NAMES,
  allocatePorts,
  ensureLayout,
  freePort,
  isPortFree,
  newAdminToken,
  openProfile,
  profileRoot,
  readDesktopSettings,
  readMachine,
  writeDesktopSettings,
  writeMachine,
} from '../dist/profile.js'

function tempDir(t, prefix = 'boxfox-profile-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

function listen(port = 0, host = '127.0.0.1') {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.listen(port, host, () => resolve({ server, port: server.address().port }))
  })
}

function close(server) {
  return new Promise((resolve) => server.close(() => resolve()))
}

test('profileRoot is per-user on both platforms', () => {
  assert.equal(profileRoot({ LOCALAPPDATA: 'C:\\Users\\ada\\AppData\\Local' }, 'win32'), path.join('C:\\Users\\ada\\AppData\\Local', 'BoxFoxDesktopAlpha'))
  assert.equal(profileRoot({}, 'win32', '/home/ada'), path.join('/home/ada', 'AppData', 'Local', 'BoxFoxDesktopAlpha'))
  assert.equal(profileRoot({ XDG_DATA_HOME: '/data' }, 'linux'), path.join('/data', 'BoxFoxDesktopAlpha'))
  assert.equal(profileRoot({}, 'linux', '/home/ada'), path.join('/home/ada', '.local', 'share', 'BoxFoxDesktopAlpha'))
})

test('ensureLayout creates the profile, logs, recovery, updates, permissions and audit directories', (t) => {
  const root = tempDir(t)
  const layout = ensureLayout(root)
  for (const dir of [layout.profile, layout.harness, layout.router, layout.ui, layout.logs, layout.recovery, layout.updates, layout.permissions, layout.audit]) {
    assert.ok(fs.statSync(dir).isDirectory(), `${dir} should be a directory`)
  }
  assert.equal(layout.machineFile, path.join(root, 'machine.json'))
  assert.equal(layout.lockFile, path.join(root, 'desktop.lock'))
})

test('first open allocates four distinct ports and a per-machine admin token', async (t) => {
  const root = tempDir(t)
  const { machine, reallocated } = await openProfile({ root })
  assert.deepEqual(reallocated, [])
  const ports = PORT_NAMES.map((name) => machine.ports[name])
  assert.equal(new Set(ports).size, 4, 'ports must be distinct')
  for (const port of ports) assert.ok(port >= 1 && port <= 65535)
  assert.match(machine.adminToken, /^[0-9a-f]{64}$/)
  assert.equal(readMachine(root).adminToken, machine.adminToken)
})

test('a second open keeps the persisted ports and token', async (t) => {
  const root = tempDir(t)
  const first = await openProfile({ root })
  const second = await openProfile({ root })
  assert.deepEqual(second.machine.ports, first.machine.ports)
  assert.equal(second.machine.adminToken, first.machine.adminToken)
  assert.deepEqual(second.reallocated, [])
})

test('a busy persisted port is re-allocated on its own and the record is rewritten', async (t) => {
  const root = tempDir(t)
  const first = await openProfile({ root })
  const busy = first.machine.ports.gateway
  const holder = await listen(busy)
  t.after(() => close(holder.server))

  const second = await openProfile({ root })
  assert.deepEqual(second.reallocated, ['gateway'])
  assert.notEqual(second.machine.ports.gateway, busy)
  for (const name of ['router', 'harness', 'box']) {
    assert.equal(second.machine.ports[name], first.machine.ports[name], `${name} must keep its port`)
  }
  assert.equal(new Set(PORT_NAMES.map((name) => second.machine.ports[name])).size, 4)
  assert.equal(readMachine(root).ports.gateway, second.machine.ports.gateway)
  assert.equal(second.machine.adminToken, first.machine.adminToken, 'the token must survive a port change')
})

test('a corrupt machine.json is quarantined into recovery/ instead of being overwritten', async (t) => {
  const root = tempDir(t)
  ensureLayout(root)
  fs.writeFileSync(path.join(root, 'machine.json'), '{"ports": {"gateway": "nope"}')

  assert.equal(readMachine(root), null)
  const quarantined = fs.readdirSync(path.join(root, 'recovery')).filter((name) => name.endsWith('.corrupt'))
  assert.equal(quarantined.length, 1, 'the corrupt record must be kept for recovery')
  assert.equal(fs.readFileSync(path.join(root, 'recovery', quarantined[0]), 'utf8'), '{"ports": {"gateway": "nope"}')

  const opened = await openProfile({ root })
  assert.equal(new Set(PORT_NAMES.map((name) => opened.machine.ports[name])).size, 4)
  assert.match(opened.machine.adminToken, /^[0-9a-f]{64}$/)
})

test('a machine.json with a too-short admin token is treated as corrupt', (t) => {
  const root = tempDir(t)
  ensureLayout(root)
  writeMachine(root, {
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ports: { gateway: 41100, router: 41101, harness: 41102, box: 41103 },
    adminToken: 'short',
  })
  assert.equal(readMachine(root), null)
  assert.equal(fs.readdirSync(path.join(root, 'recovery')).length, 1)
})

test('machine.json is written owner-only and atomically (no .tmp left behind)', (t) => {
  const root = tempDir(t)
  ensureLayout(root)
  writeMachine(root, {
    version: 1,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    ports: { gateway: 41200, router: 41201, harness: 41202, box: 41203 },
    adminToken: newAdminToken(),
  })
  assert.ok(!fs.existsSync(path.join(root, 'machine.json.tmp')))
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(path.join(root, 'machine.json')).mode & 0o777, 0o600)
  }
})

test('freePort/allocatePorts/isPortFree agree with a real listener', async (t) => {
  const holder = await listen()
  t.after(() => close(holder.server))
  assert.equal(await isPortFree(holder.port), false)
  // localhost can resolve to ::1 on Windows. Probe a listener on that same
  // hostname rather than assuming an IPv4-only listener occupies both stacks.
  const namedHolder = await listen(0, 'localhost')
  t.after(() => close(namedHolder.server))
  assert.equal(await isPortFree(namedHolder.port, 'localhost'), false)

  const ports = await allocatePorts(4)
  assert.equal(ports.length, 4)
  assert.equal(new Set(ports).size, 4)
  for (const port of ports) assert.equal(await isPortFree(port), true)
  const single = await freePort()
  assert.ok(single > 0)
})

test('desktop-settings.json defaults to host mode and can be switched to docker', (t) => {
  const root = tempDir(t)
  const layout = ensureLayout(root)
  assert.equal(readDesktopSettings(layout).executionMode, 'host')
  const written = writeDesktopSettings(layout, { executionMode: 'docker' })
  assert.equal(written.executionMode, 'docker')
  assert.equal(readDesktopSettings(layout).executionMode, 'docker')
  assert.equal(readDesktopSettings(layout).version, 1)
})
