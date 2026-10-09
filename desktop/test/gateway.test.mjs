/**
 * gateway.ts — the loopback gateway the desktop window talks to.
 * Plan §6 PR-2 / D2: "phục vụ UI build; proxy /api/agent* → harness, /api/router* + /v1*
 * → router, bề mặt box /__box/* → box (docker) hoặc harness desktop API (host).
 * Allowlist Host/Origin, CSP, contextIsolation, không wildcard."
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as crypto from 'node:crypto'
import * as http from 'node:http'
import * as net from 'node:net'
import * as os from 'node:os'
import * as path from 'node:path'

import { createGateway, allowedHosts, allowedOrigins, contentSecurityPolicy, hostDesktopPath, routeFor } from '../dist/gateway.js'
import { freePort } from '../dist/profile.js'

function tempDir(t, prefix = 'boxfox-gateway-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

/** Upstream stub that reports the request it received as JSON. */
async function stubUpstream(t) {
  const server = http.createServer((req, res) => {
    const chunks = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => {
      res.writeHead(200, { 'content-type': 'application/json', 'x-upstream': 'stub', connection: 'keep-alive' })
      res.end(
        JSON.stringify({
          url: req.url,
          method: req.method,
          headers: req.headers,
          body: Buffer.concat(chunks).toString('utf8'),
        }),
      )
    })
  })
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve))
  t.after(() => new Promise((resolve) => server.close(resolve)))
  return { server, url: `http://127.0.0.1:${server.address().port}` }
}

async function startGateway(t, options = {}) {
  const port = await freePort()
  const uiDir = options.uiDir ?? tempDir(t)
  const harness = options.harness ?? (await stubUpstream(t))
  const router = options.router ?? (await stubUpstream(t))
  const box = options.box ?? (await stubUpstream(t))
  const gateway = createGateway({
    port,
    uiDir,
    mode: options.mode ?? 'host',
    upstreams: { harness: harness.url, router: router.url, box: box.url },
    identity: {
      app: 'boxfox-desktop',
      version: '0.1.0',
      mode: options.mode ?? 'host',
      ports: { gateway: port, router: 1, harness: 2, box: 3 },
      adminToken: 'a'.repeat(64),
    },
    status: () => ({ router: { healthy: true } }),
  })
  await gateway.listen()
  t.after(() => gateway.close())
  return { gateway, port, harness, router, box, uiDir }
}

/** Raw request so a foreign Host header can be sent. */
function raw({ port, path: requestPath = '/', method = 'GET', headers = {}, body = null }) {
  return new Promise((resolve, reject) => {
    const req = http.request(
      { host: '127.0.0.1', port, path: requestPath, method, headers: { host: `127.0.0.1:${port}`, ...headers } },
      (res) => {
        const chunks = []
        res.on('data', (chunk) => chunks.push(chunk))
        res.on('end', () => resolve({ status: res.statusCode, headers: res.headers, text: Buffer.concat(chunks).toString('utf8') }))
      },
    )
    req.on('error', reject)
    if (body !== null) req.write(body)
    req.end()
  })
}

test('the routing table maps every surface of the plan', () => {
  assert.equal(routeFor('/api/agent/health', 'host'), 'harness')
  assert.equal(routeFor('/api/agent', 'docker'), 'harness')
  assert.equal(routeFor('/api/router/health', 'host'), 'router')
  assert.equal(routeFor('/v1/chat/completions', 'docker'), 'router')
  assert.equal(routeFor('/api/desktop/identity', 'host'), 'desktop')
  assert.equal(routeFor('/__box/inspect-element', 'docker'), 'box')
  assert.equal(routeFor('/__box/inspect-element', 'host'), 'harness', 'host mode has no container')
  assert.equal(routeFor('/__tty/ws', 'docker'), 'box')
  assert.equal(routeFor('/__tty/ws', 'host'), 'unsupported')
  assert.equal(routeFor('/', 'host'), null, 'static UI is not an upstream')
  assert.equal(routeFor('/settings/agent', 'host'), null)
  assert.equal(routeFor('/api/unknown', 'host'), null)
  assert.equal(hostDesktopPath('/__box/desktop/screenshot'), '/api/agent/desktop/desktop/screenshot')
  assert.equal(hostDesktopPath('/__box/'), '/api/agent/desktop/')
})

test('allowlists contain only loopback names, never a wildcard', () => {
  assert.deepEqual(allowedHosts(43123), ['127.0.0.1:43123', 'localhost:43123'])
  assert.deepEqual(allowedOrigins(43123), ['http://127.0.0.1:43123', 'http://localhost:43123'])
  const csp = contentSecurityPolicy(43123)
  assert.ok(!csp.includes('*'), `CSP must not contain a wildcard: ${csp}`)
  assert.ok(csp.includes("default-src 'self'"))
  assert.ok(csp.includes('ws://127.0.0.1:43123'))
  assert.ok(csp.includes("frame-ancestors 'none'"))
  assert.ok(csp.includes("object-src 'none'"))
})

test('a foreign Host header is rejected with 403', async (t) => {
  const { port } = await startGateway(t)
  const response = await raw({ port, path: '/api/desktop/identity', headers: { host: 'evil.example' } })
  assert.equal(response.status, 403)
  assert.match(response.text, /Host not allowed/)
})

test('a foreign Origin is rejected with 403 and the loopback origin is accepted', async (t) => {
  const { port } = await startGateway(t)
  const rejected = await raw({ port, path: '/api/desktop/identity', headers: { origin: 'http://evil.example' } })
  assert.equal(rejected.status, 403)
  assert.match(rejected.text, /Origin not allowed/)

  const accepted = await raw({ port, path: '/api/desktop/identity', headers: { origin: `http://127.0.0.1:${port}` } })
  assert.equal(accepted.status, 200)
})

test('state-changing requests without an Origin are rejected', async (t) => {
  const { port } = await startGateway(t)
  const response = await raw({ port, path: '/api/agent/desktop/click', method: 'POST', body: '{}', headers: { 'content-type': 'application/json' } })
  assert.equal(response.status, 403)
  assert.match(response.text, /Origin required/)
})

test('/api/desktop/identity and /api/desktop/health are served locally', async (t) => {
  const { port } = await startGateway(t)
  const identity = await raw({ port, path: '/api/desktop/identity' })
  assert.equal(identity.status, 200)
  const body = JSON.parse(identity.text)
  assert.equal(body.app, 'boxfox-desktop')
  assert.equal(body.mode, 'host')
  assert.equal(body.ports.gateway, port)
  assert.equal(body.adminToken, 'a'.repeat(64))

  const health = await raw({ port, path: '/api/desktop/health' })
  assert.equal(health.status, 200)
  assert.deepEqual(JSON.parse(health.text).services, { router: { healthy: true } })

  const unknown = await raw({ port, path: '/api/desktop/nope' })
  assert.equal(unknown.status, 404)
})

test('harness and router proxies inject the admin header and strip hop-by-hop headers', async (t) => {
  const { port, harness, router } = await startGateway(t)
  const agent = JSON.parse((await raw({ port, path: '/api/agent/health', headers: { connection: 'keep-alive', te: 'trailers' } })).text)
  assert.equal(agent.url, '/api/agent/health')
  assert.equal(agent.headers['x-boxfox-admin'], '1')
  assert.equal(agent.headers.host, new URL(harness.url).host, 'Host must be rewritten to the upstream')
  assert.equal(agent.headers.te, undefined, 'hop-by-hop headers must not be forwarded')
  // (`connection: keep-alive` on the upstream request is Node's own client header, not a forward.)

  const routerCall = JSON.parse((await raw({ port, path: '/v1/models' })).text)
  assert.equal(routerCall.url, '/v1/models')
  assert.equal(routerCall.headers['x-boxfox-admin'], '1')
  assert.equal(routerCall.headers.origin, new URL(router.url).origin, 'the router gets its own origin, not the caller’s')
})

test('the box proxy presents the per-machine admin token as the shared secret', async (t) => {
  const { port, box } = await startGateway(t, { mode: 'docker' })
  const call = JSON.parse((await raw({ port, path: '/__box/capture' })).text)
  assert.equal(call.url, '/__box/capture')
  assert.equal(call.headers['x-boxfox-api-key'], 'a'.repeat(64))
  assert.equal(call.headers['x-boxfox-admin'], undefined, 'the container API uses its own header')
})

test('host mode maps /__box/* onto the harness desktop API and refuses /__tty', async (t) => {
  const { port, harness } = await startGateway(t, { mode: 'host' })
  const call = JSON.parse((await raw({ port, path: '/__box/inspect-element?x=1' })).text)
  assert.equal(call.url, '/api/agent/desktop/inspect-element?x=1')
  assert.equal(new URL(harness.url).host, call.headers.host)

  const tty = await raw({ port, path: '/__tty/ws' })
  assert.equal(tty.status, 501)
  assert.match(tty.text, /not available in host mode/)
})

test('the gateway serves the built UI with a CSP and an SPA fallback', async (t) => {
  const uiDir = tempDir(t)
  fs.writeFileSync(path.join(uiDir, 'index.html'), '<!doctype html><title>BoxFox</title>')
  fs.mkdirSync(path.join(uiDir, 'assets'))
  fs.writeFileSync(path.join(uiDir, 'assets', 'app.js'), 'console.log(1)')
  fs.writeFileSync(path.join(uiDir, 'secret.txt'), 'secret')
  const { port } = await startGateway(t, { uiDir })

  const shell = await raw({ port, path: '/' })
  assert.equal(shell.status, 200)
  assert.match(shell.headers['content-security-policy'], /default-src 'self'/)
  assert.equal(shell.headers['x-content-type-options'], 'nosniff')
  assert.equal(shell.headers['x-frame-options'], 'DENY')
  assert.equal(shell.headers['referrer-policy'], 'no-referrer')
  assert.equal(shell.headers['cache-control'], 'no-store')
  assert.match(shell.text, /BoxFox/)

  const asset = await raw({ port, path: '/assets/app.js' })
  assert.equal(asset.status, 200)
  assert.equal(asset.headers['content-type'], 'text/javascript; charset=utf-8')
  assert.match(asset.headers['cache-control'], /max-age/)

  const spa = await raw({ port, path: '/settings/agent' })
  assert.equal(spa.status, 200, 'unknown extension-less paths fall back to the app shell')
  assert.match(spa.text, /BoxFox/)

  const missingAsset = await raw({ port, path: '/assets/missing.js' })
  assert.equal(missingAsset.status, 404)

  // Encoded traversal must not escape the UI root (`new URL` would silently normalise a
  // literal `/../secret.txt`, so the encoded form is the one that reaches the handler).
  const traversal = await raw({ port, path: '/..%2fsecret.txt' })
  assert.equal(traversal.status, 403, 'a path outside the UI bundle is refused')
  assert.match(traversal.text, /outside the UI bundle/)
  const nested = await raw({ port, path: '/assets/..%2f..%2fsecret.txt' })
  assert.equal(nested.status, 403)
  assert.ok(!nested.text.includes('secret'))
})

test('a missing UI bundle is reported instead of crashing', async (t) => {
  const uiDir = tempDir(t)
  const { port } = await startGateway(t, { uiDir })
  const response = await raw({ port, path: '/' })
  assert.equal(response.status, 404)
  assert.match(response.text, /run build-app/)
})

test('an unreachable upstream answers 502 instead of hanging', async (t) => {
  const dead = await freePort()
  const { port } = await startGateway(t, { harness: { url: `http://127.0.0.1:${dead}` } })
  const response = await raw({ port, path: '/api/agent/health' })
  assert.equal(response.status, 502)
  assert.match(response.text, /harness upstream unavailable/)
})

test('websocket upgrades check Host and Origin before tunnelling', async (t) => {
  const { port } = await startGateway(t)
  const { connect } = await import('node:net')
  const attempt = (headers) =>
    new Promise((resolve) => {
      const socket = connect(port, '127.0.0.1', () => {
        socket.write(`GET /api/agent/health HTTP/1.1\r\nhost: 127.0.0.1:${port}\r\nupgrade: websocket\r\nconnection: Upgrade\r\n${headers}\r\n\r\n`)
      })
      let data = ''
      socket.on('data', (chunk) => {
        data += chunk.toString('utf8')
        socket.destroy()
      })
      socket.on('close', () => resolve(data))
      socket.on('error', () => resolve(data))
    })
  const foreign = await attempt('origin: http://evil.example\r\n')
  assert.equal(foreign, '', 'a foreign Origin must be dropped without an HTTP response')
  const tunneled = await attempt(`origin: http://127.0.0.1:${port}\r\n`)
  assert.match(tunneled, /HTTP\/1\.1 200/, 'an allowed Origin is tunnelled to the harness stub')
})

test('a websocket upgrade reaches the upstream as a real 101 handshake (DA5)', async (t) => {
  // Upstream that only answers 101 when the tunnel kept the handshake headers, then echoes bytes.
  // A stub that answers 200 hides the bug: `proxyHeaders` drops `Connection`/`Upgrade` (hop-by-hop),
  // so a real WebSocket server would refuse the upgrade.
  const upstream = net.createServer((socket) => {
    let buffer = ''
    const onData = (chunk) => {
      buffer += chunk.toString('latin1')
      if (!buffer.includes('\r\n\r\n')) return
      socket.off('data', onData)
      const head = buffer.slice(0, buffer.indexOf('\r\n\r\n'))
      const headers = new Map(
        head
          .split('\r\n')
          .slice(1)
          .map((line) => {
            const at = line.indexOf(':')
            return [line.slice(0, at).trim().toLowerCase(), line.slice(at + 1).trim()]
          }),
      )
      const key = headers.get('sec-websocket-key')
      const ok =
        String(headers.get('connection') || '').toLowerCase() === 'upgrade' &&
        String(headers.get('upgrade') || '').toLowerCase() === 'websocket' &&
        Boolean(key)
      if (!ok) {
        socket.end('HTTP/1.1 400 Bad Request\r\ncontent-length: 0\r\nconnection: close\r\n\r\n')
        return
      }
      const accept = crypto.createHash('sha1').update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest('base64')
      socket.write(
        `HTTP/1.1 101 Switching Protocols\r\nupgrade: websocket\r\nconnection: Upgrade\r\nsec-websocket-accept: ${accept}\r\n\r\n`,
      )
      // Sau handshake: đường hầm phải hai chiều — trả lại đúng những gì nhận được.
      socket.on('data', (chunk) => socket.write(chunk))
    }
    socket.on('data', onData)
  })
  await new Promise((resolve) => upstream.listen(0, '127.0.0.1', resolve))
  t.after(() => upstream.close())
  const upstreamPort = upstream.address().port

  const { port } = await startGateway(t, { harness: { url: `http://127.0.0.1:${upstreamPort}` } })
  const key = 'dGhlIHNhbXBsZSBub25jZQ=='
  const handshake = await new Promise((resolve) => {
    let data = ''
    let sent = false
    let done = false
    const finish = () => {
      if (done) return
      done = true
      socket.destroy()
      resolve(data)
    }
    const socket = net.connect(port, '127.0.0.1', () => {
      socket.write(
        `GET /api/agent/health HTTP/1.1\r\nhost: 127.0.0.1:${port}\r\norigin: http://127.0.0.1:${port}\r\nupgrade: websocket\r\nconnection: Upgrade\r\nsec-websocket-key: ${key}\r\nsec-websocket-version: 13\r\n\r\n`,
      )
    })
    socket.on('data', (chunk) => {
      data += chunk.toString('latin1')
      // Gửi đúng một lần: nếu gửi ở mỗi chunk thì upstream echo lại và vòng lặp không dừng.
      if (!sent && data.includes('\r\n\r\n')) {
        sent = true
        socket.write('ping-from-client')
        setTimeout(finish, 60)
      }
    })
    socket.on('error', finish)
    socket.on('close', finish)
    // Chốt thời gian đặt NGAY khi mở socket: một upstream từ chối handshake có thể không bao giờ
    // trả byte nào, và bài kiểm tra phải KỂ RA câu trả lời sai thay vì treo.
    setTimeout(finish, 2000)
  })

  assert.match(handshake, /^HTTP\/1\.1 101 Switching Protocols/, 'the upstream must switch protocols')
  const accept = crypto
    .createHash('sha1')
    .update(`${key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`)
    .digest('base64')
  // So bằng chuỗi, không bằng RegExp: base64 có `+` và `/` là ký tự đặc biệt của biểu thức chính quy.
  assert.ok(
    handshake.toLowerCase().includes(`sec-websocket-accept: ${accept.toLowerCase()}`),
    'the key must survive the tunnel',
  )
  assert.match(handshake, /ping-from-client/, 'the tunnel must carry bytes in both directions')
})
