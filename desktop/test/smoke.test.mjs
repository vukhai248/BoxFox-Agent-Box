/**
 * Layout smoke test (plan §6 PR-2 / D2: "smoke chạy bản Linux cùng layout").
 *
 * Drives the whole D2 stack on the staged layout the installer ships — profile →
 * bundled node/python binaries → Supervisor → Gateway — using the real interpreter
 * binaries (the Windows runtime cannot execute here, so the runtime directory is
 * populated with symlinks to the local node/python).
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import { createGateway } from '../dist/gateway.js'
import { openProfile } from '../dist/profile.js'
import { Supervisor, buildServiceSpecs } from '../dist/supervisor.js'

const PYTHON = ['/usr/bin/python3', '/usr/local/bin/python3'].find((candidate) => fs.existsSync(candidate))

function tempDir(t, prefix = 'boxfox-smoke-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

/** Minimal POSIX harness: answers /api/agent/health and echoes the boundary headers. */
const HARNESS_STUB = `import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({
            'status': 'ok',
            'path': self.path,
            'admin': self.headers.get('X-BoxFox-Admin'),
            'apiKey': os.environ.get('BOXFOX_API_KEY'),
            'dataDir': os.environ.get('BOXFOX_AGENT_DATA_DIR'),
            'pythonPath': os.environ.get('PYTHONPATH'),
            'utf8': os.environ.get('PYTHONUTF8'),
        }).encode()
        self.send_response(200)
        self.send_header('content-type', 'application/json')
        self.send_header('content-length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass

HTTPServer(('127.0.0.1', int(os.environ['BOXFOX_HARNESS_PORT'])), Handler).serve_forever()
`

const ROUTER_STUB = `import http from 'node:http'
const port = Number(process.env.BOXFOX_ROUTER_PORT)
http
  .createServer((req, res) => {
    const body = JSON.stringify({
      status: 'ok',
      path: req.url,
      dataDir: process.env.BOXFOX_ROUTER_DATA_DIR,
      admin: req.headers['x-boxfox-admin'],
      origin: req.headers.origin,
      mode: process.env.BOXFOX_EXECUTION_MODE,
    })
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(body)
  })
  .listen(port, '127.0.0.1', () => console.log('router stub ready'))
`

test('the staged layout runs end to end: bundled binaries, supervisor, gateway', async (t) => {
  // `t.skip()` chỉ ĐÁNH DẤU bài kiểm tra là bỏ qua, nó không dừng thân hàm: thiếu `return` thì
  // phần còn lại vẫn chạy và có thể nổ ở môi trường không có python3 (DA8 của bản bàn giao).
  if (process.platform === 'win32') {
    t.skip('the smoke layout uses POSIX binary paths')
    return
  }
  if (!PYTHON) {
    t.skip('no system python3 available for the harness stub')
    return
  }

  const resources = tempDir(t, 'boxfox-resources-')
  fs.mkdirSync(path.join(resources, 'router', 'src'), { recursive: true })
  fs.mkdirSync(path.join(resources, 'harness', 'scripts'), { recursive: true })
  fs.mkdirSync(path.join(resources, 'harness', 'backend', 'src'), { recursive: true })
  fs.mkdirSync(path.join(resources, 'ui'), { recursive: true })
  fs.mkdirSync(path.join(resources, 'runtime', 'node', 'bin'), { recursive: true })
  fs.mkdirSync(path.join(resources, 'runtime', 'python', 'bin'), { recursive: true })
  fs.writeFileSync(path.join(resources, 'router', 'src', 'main.mjs'), ROUTER_STUB)
  fs.writeFileSync(path.join(resources, 'harness', 'scripts', 'run-harness.py'), HARNESS_STUB)
  fs.writeFileSync(path.join(resources, 'ui', 'index.html'), '<!doctype html><title>BoxFox smoke</title>')
  fs.symlinkSync(process.execPath, path.join(resources, 'runtime', 'node', 'bin', 'node'))
  fs.symlinkSync(PYTHON, path.join(resources, 'runtime', 'python', 'bin', 'python3'))

  const root = tempDir(t, 'boxfox-smoke-profile-')
  const { layout, machine } = await openProfile({ root })
  const runtimeDir = path.join(resources, 'runtime')
  const specs = buildServiceSpecs({
    layout,
    machine,
    resourcesDir: resources,
    runtimeDir,
    mode: 'host',
    platform: 'linux',
    env: { PATH: process.env.PATH ?? '' },
  })
  assert.equal(specs.router.command, path.join(runtimeDir, 'node', 'bin', 'node'))
  assert.equal(specs.harness.command, path.join(runtimeDir, 'python', 'bin', 'python3'))

  const supervisor = new Supervisor({ layout, machine, mode: 'host', resourcesDir: resources, runtimeDir, specs, readyTimeoutMs: 30_000, log: () => undefined })
  const started = await supervisor.start()
  t.after(() => supervisor.stop())
  assert.equal(started.running, true, 'both services must become healthy')
  assert.equal(started.services.router.healthy, true)
  assert.equal(started.services.harness.healthy, true)

  const gateway = createGateway({
    port: machine.ports.gateway,
    uiDir: path.join(resources, 'ui'),
    mode: 'host',
    upstreams: {
      harness: `http://127.0.0.1:${machine.ports.harness}`,
      router: `http://127.0.0.1:${machine.ports.router}`,
      box: `http://127.0.0.1:${machine.ports.box}`,
    },
    identity: { app: 'boxfox-desktop', version: '0.1.0', mode: 'host', ports: machine.ports, adminToken: machine.adminToken },
    status: () => supervisor.status(),
  })
  await gateway.listen()
  t.after(() => gateway.close())
  assert.equal(gateway.url, `http://127.0.0.1:${machine.ports.gateway}`)

  const get = async (requestPath) => {
    const response = await fetch(`${gateway.url}${requestPath}`)
    return { status: response.status, body: await response.text() }
  }

  const identity = await get('/api/desktop/identity')
  assert.equal(identity.status, 200)
  assert.equal(JSON.parse(identity.body).adminToken, machine.adminToken)

  const health = await get('/api/desktop/health')
  assert.equal(JSON.parse(health.body).services.running, true, 'the gateway reports live service state')

  const harness = JSON.parse((await get('/api/agent/health')).body)
  assert.equal(harness.status, 'ok')
  assert.equal(harness.path, '/api/agent/health')
  assert.equal(harness.admin, '1', 'the gateway presents the admin header to the harness')
  assert.equal(harness.apiKey, machine.adminToken, 'the harness runs with the per-machine token')
  assert.equal(harness.dataDir, layout.harness, 'the harness data directory is inside the profile')
  assert.equal(harness.pythonPath, path.join(resources, 'harness', 'backend', 'src'))
  assert.equal(harness.utf8, '1')

  const router = JSON.parse((await get('/api/router/health')).body)
  assert.equal(router.status, 'ok')
  assert.equal(router.dataDir, layout.router)
  assert.equal(router.admin, '1')
  assert.equal(router.origin, `http://127.0.0.1:${machine.ports.router}`, 'the router sees its own origin')
  assert.equal(router.mode, 'host')

  const box = JSON.parse((await get('/__box/inspect-element')).body)
  assert.equal(box.path, '/api/agent/desktop/inspect-element', 'host mode maps the box surface onto the harness')

  const ui = await get('/')
  assert.equal(ui.status, 200)
  assert.match(ui.body, /BoxFox smoke/)

  const tty = await get('/__tty/ws')
  assert.equal(tty.status, 501)

  await gateway.close()
  await supervisor.stop()
  const stopped = supervisor.status()
  assert.equal(stopped.running, false)
  assert.equal(stopped.services.harness.healthy, false)
})
