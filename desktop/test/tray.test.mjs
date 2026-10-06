/**
 * tray.ts + desktop-control.ts — the tray menu, the hide-on-close rule and the two
 * harness lease calls (plan §6 PR-2 / D3).
 *
 * Everything here runs on Linux with no Electron: the tray module returns the menu as
 * data and the control module talks plain HTTP to a local stub harness.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import * as http from 'node:http'

import { DESKTOP_LEASE_PATH, describeControlResult, requestDesktopControl } from '../dist/desktop-control.js'
import { shouldHideOnClose, toggleWindowVisibility, trayMenuTemplate, TRAY_TOOLTIP } from '../dist/tray.js'

function fakeWindow({ visible = true, minimized = false } = {}) {
  const calls = []
  const window = {
    calls,
    isVisible: () => visible,
    isMinimized: () => minimized,
    show: () => {
      visible = true
      calls.push('show')
    },
    hide: () => {
      visible = false
      calls.push('hide')
    },
    focus: () => calls.push('focus'),
    restore: () => calls.push('restore'),
  }
  return window
}

function recordingHandlers() {
  const calls = []
  return {
    calls,
    handlers: {
      toggleWindow: () => calls.push('toggleWindow'),
      claimControl: () => calls.push('claimControl'),
      emergencyStop: () => calls.push('emergencyStop'),
      openDataFolder: () => calls.push('openDataFolder'),
      exportDiagnostics: () => calls.push('exportDiagnostics'),
      quit: () => calls.push('quit'),
    },
  }
}

function startServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler)
    server.listen(0, '127.0.0.1', () => {
      resolve({ server, baseUrl: `http://127.0.0.1:${server.address().port}` })
    })
  })
}

function closeServer(server) {
  server.closeAllConnections?.()
  return new Promise((resolve) => server.close(() => resolve()))
}

test('the tray menu carries every D3 action, in order', () => {
  const { calls, handlers } = recordingHandlers()
  const menu = trayMenuTemplate(handlers, { windowVisible: true })
  const labels = menu.filter((item) => item.type !== 'separator').map((item) => item.label)
  assert.deepEqual(labels, [
    'Ẩn cửa sổ',
    'Trả quyền cho agent',
    'Dừng khẩn',
    'Mở thư mục dữ liệu',
    'Sao lưu chẩn đoán',
    'Thoát',
  ])
  assert.deepEqual(
    menu.map((item) => item.type ?? 'normal'),
    ['normal', 'separator', 'normal', 'normal', 'separator', 'normal', 'normal', 'separator', 'normal'],
  )
  for (const item of menu) item.click?.()
  assert.deepEqual(calls, ['toggleWindow', 'claimControl', 'emergencyStop', 'openDataFolder', 'exportDiagnostics', 'quit'])
})

test('the first menu entry follows the window visibility', () => {
  const { handlers } = recordingHandlers()
  assert.equal(trayMenuTemplate(handlers, { windowVisible: true })[0].label, 'Ẩn cửa sổ')
  assert.equal(trayMenuTemplate(handlers, { windowVisible: false })[0].label, 'Hiện cửa sổ')
  assert.equal(TRAY_TOOLTIP, 'BoxFox Desktop (Alpha)')
})

test('toggling the window hides a visible one and restores a minimised one', () => {
  const visible = fakeWindow({ visible: true })
  assert.equal(toggleWindowVisibility(visible), false)
  assert.deepEqual(visible.calls, ['hide'])

  const hidden = fakeWindow({ visible: false })
  assert.equal(toggleWindowVisibility(hidden), true)
  assert.deepEqual(hidden.calls, ['show', 'focus'])

  const minimised = fakeWindow({ visible: false, minimized: true })
  assert.equal(toggleWindowVisibility(minimised), true)
  assert.deepEqual(minimised.calls, ['restore', 'show', 'focus'])
})

test('closing the window hides it, except while the app is really quitting', () => {
  assert.equal(shouldHideOnClose(false), true)
  assert.equal(shouldHideOnClose(true), false)
  // No tray: hiding the window would leave no way back to it, so the close goes through.
  assert.equal(shouldHideOnClose(false, false), false)
  assert.equal(shouldHideOnClose(true, false), false)
})

test('a claim posts the lease action to the harness with the admin marker and origin', async (t) => {
  const requests = []
  const { server, baseUrl } = await startServer((req, res) => {
    let body = ''
    req.on('data', (chunk) => {
      body += chunk
    })
    req.on('end', () => {
      requests.push({ method: req.method, url: req.url, headers: req.headers, body })
      res.writeHead(200, { 'content-type': 'application/json' })
      res.end(JSON.stringify({ ok: true, holder: 'agent' }))
    })
  })
  t.after(() => closeServer(server))

  const result = await requestDesktopControl({
    baseUrl,
    action: 'claim',
    reason: 'tray',
    origin: 'http://127.0.0.1:9999',
  })
  assert.equal(result.ok, true)
  assert.equal(result.status, 200)
  assert.deepEqual(result.body, { ok: true, holder: 'agent' })
  assert.equal(requests.length, 1)
  assert.equal(requests[0].method, 'POST')
  assert.equal(requests[0].url, DESKTOP_LEASE_PATH)
  assert.equal(requests[0].headers['x-boxfox-admin'], '1')
  assert.equal(requests[0].headers.origin, 'http://127.0.0.1:9999')
  assert.deepEqual(JSON.parse(requests[0].body), { action: 'claim', reason: 'tray' })
})

test('a 409 (docker mode) is reported, never thrown', async (t) => {
  const { server, baseUrl } = await startServer((_req, res) => {
    res.writeHead(409, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ code: 'CONTROL_BUSY', error: 'CONTROL_BUSY: the container holds the pointer' }))
  })
  t.after(() => closeServer(server))

  const result = await requestDesktopControl({ baseUrl, action: 'stop', reason: 'tray' })
  assert.equal(result.ok, false)
  assert.equal(result.status, 409)
  assert.equal(result.error, 'CONTROL_BUSY')
  assert.match(describeControlResult(result), /409/)
  assert.match(describeControlResult(result), /docker/)
})

test('a 404 (harness without the lease route) names the missing CUA layer', async (t) => {
  const { server, baseUrl } = await startServer((_req, res) => {
    res.writeHead(404, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ detail: 'Not Found' }))
  })
  t.after(() => closeServer(server))

  const result = await requestDesktopControl({ baseUrl, action: 'claim' })
  assert.equal(result.ok, false)
  assert.equal(result.status, 404)
  assert.match(describeControlResult(result), /404/)
  assert.match(describeControlResult(result), /CUA/)
})

test('an unreachable harness is reported, never thrown', async () => {
  // Bind and immediately release a port so nothing is listening there.
  const { server, baseUrl } = await startServer((_req, res) => res.end())
  await closeServer(server)

  const result = await requestDesktopControl({ baseUrl, action: 'claim', timeoutMs: 1000 })
  assert.equal(result.ok, false)
  assert.equal(result.status, null)
  assert.ok(result.error && result.error.length > 0)
  assert.match(describeControlResult(result), /không thực hiện được/)
})

test('a hanging harness is cut off by the timeout', async (t) => {
  const { server, baseUrl } = await startServer(() => {
    // Never answers: the request must time out.
  })
  t.after(() => closeServer(server))

  const result = await requestDesktopControl({ baseUrl, action: 'stop', timeoutMs: 150 })
  assert.equal(result.ok, false)
  assert.equal(result.status, null)
  assert.ok(result.error && result.error.length > 0)
})

test('a successful claim is described as sent to the harness', async (t) => {
  const { server, baseUrl } = await startServer((_req, res) => {
    res.writeHead(204)
    res.end()
  })
  t.after(() => closeServer(server))

  const result = await requestDesktopControl({ baseUrl, action: 'claim' })
  assert.equal(result.ok, true)
  assert.equal(result.status, 204)
  assert.equal(result.body, null)
  assert.match(describeControlResult(result), /đã gửi tới harness/)
})
