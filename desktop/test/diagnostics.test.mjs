/**
 * diagnostics.ts — the redaction rules, the runtime inventory, the harness health probe
 * and the support bundle (plan §6 PR-2 / D3).
 *
 * The bundle is read back with the same zip reader the build scripts use, so the test
 * proves the archive is a real ZIP and not just bytes on disk.
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import * as fs from 'node:fs'
import * as http from 'node:http'
import * as os from 'node:os'
import * as path from 'node:path'

import {
  LOG_TAIL_LINES,
  REDACTED,
  diagnosticsDir,
  fetchHarnessHealth,
  isSecretName,
  listRuntimeFiles,
  readLogTail,
  redactLine,
  redactValue,
  runtimeBundleFromManifest,
  writeDiagnosticsArchive,
} from '../dist/diagnostics.js'
import { ensureLayout } from '../dist/profile.js'
import { readZipEntryBuffer, zipEntryNames } from '../scripts/lib/zip.mjs'

function tempDir(t, prefix = 'boxfox-diagnostics-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

function emptyServices() {
  const service = { pid: null, healthy: false, restarts: 0, lastExit: null, lastError: null }
  return { running: false, services: { router: { ...service }, harness: { ...service } } }
}

function startServer(handler) {
  return new Promise((resolve) => {
    const server = http.createServer(handler)
    server.listen(0, '127.0.0.1', () => resolve({ server, baseUrl: `http://127.0.0.1:${server.address().port}` }))
  })
}

function closeServer(server) {
  server.closeAllConnections?.()
  return new Promise((resolve) => server.close(() => resolve()))
}

test('secret names are recognised case-insensitively', () => {
  for (const name of ['apiKey', 'API_KEY', 'BOXFOX_API_KEY', 'adminToken', 'Authorization', 'password', 'client_secret']) {
    assert.equal(isSecretName(name), true, `${name} must count as a secret name`)
  }
  for (const name of ['mode', 'ports', 'profileRoot', 'username', 'generatedAt', 'runtime']) {
    assert.equal(isSecretName(name), false, `${name} must not count as a secret name`)
  }
})

test('redactValue walks nested objects and arrays by key name', () => {
  const redacted = redactValue({
    mode: 'host',
    apiKey: 'sk-live-123',
    nested: { password: 'hunter2', keep: 1 },
    list: [{ token: 'abc' }, { ok: true }],
  })
  assert.deepEqual(redacted, {
    mode: 'host',
    apiKey: REDACTED,
    nested: { password: REDACTED, keep: 1 },
    list: [{ token: REDACTED }, { ok: true }],
  })
})

test('redactLine masks assignments and bearer tokens but keeps normal lines', () => {
  assert.equal(redactLine('BOXFOX_API_KEY=deadbeef'), `BOXFOX_API_KEY=${REDACTED}`)
  assert.equal(redactLine('"token": "abc123"'), `"token": "${REDACTED}"`)
  assert.equal(redactLine('Authorization: Bearer abc.def.ghi'), `Authorization: Bearer ${REDACTED}`)
  assert.equal(redactLine('password = s3cr3t'), `password = ${REDACTED}`)
  const clean = 'mode: host — host mode selected.'
  assert.equal(redactLine(clean), clean)
})

test('runtimeBundleFromManifest reads the staged manifest, tolerating null', () => {
  assert.equal(runtimeBundleFromManifest(null), null)
  const bundle = runtimeBundleFromManifest({
    runtimeTarget: 'win-x64',
    runtime: { artifacts: [{ name: 'Node.js 24.9.0 (win-x64)', version: '24.9.0' }, 'junk'] },
  })
  assert.deepEqual(bundle, {
    target: 'win-x64',
    artifacts: [{ name: 'Node.js 24.9.0 (win-x64)', version: '24.9.0' }],
  })
})

test('listRuntimeFiles reports path, size and sha256, sorted', (t) => {
  const root = tempDir(t)
  fs.mkdirSync(path.join(root, 'node', 'bin'), { recursive: true })
  fs.writeFileSync(path.join(root, 'node', 'bin', 'node.exe'), 'node-binary')
  fs.writeFileSync(path.join(root, 'python.exe'), 'python-binary')

  const files = listRuntimeFiles(root)
  assert.deepEqual(files.map((file) => file.path), ['node/bin/node.exe', 'python.exe'])
  assert.equal(files[0].bytes, 'node-binary'.length)
  assert.equal(files[0].sha256, createHash('sha256').update('node-binary').digest('hex'))
  assert.deepEqual(listRuntimeFiles(path.join(root, 'missing')), [])
})

test('readLogTail keeps the last 200 lines', (t) => {
  const root = tempDir(t)
  const file = path.join(root, 'harness.stdout.log')
  fs.writeFileSync(file, Array.from({ length: 300 }, (_, index) => `line ${index + 1}`).join('\n'))
  const tail = readLogTail(file).split('\n')
  assert.equal(tail.length, LOG_TAIL_LINES)
  assert.equal(tail[0], 'line 101')
  assert.equal(tail[LOG_TAIL_LINES - 1], 'line 300')
  assert.equal(readLogTail(path.join(root, 'missing.log')), '')
})

test('the support bundle carries the manifest, the health JSON, the log tails and the runtime inventory', (t) => {
  const root = tempDir(t, 'boxfox-diag-profile-')
  const layout = ensureLayout(root)
  const runtimeDir = path.join(tempDir(t, 'boxfox-diag-runtime-'), 'runtime')
  fs.mkdirSync(path.join(runtimeDir, 'node'), { recursive: true })
  fs.writeFileSync(path.join(runtimeDir, 'node', 'node.exe'), 'node-binary')

  fs.writeFileSync(path.join(layout.logs, 'harness.stdout.log'), 'starting\nBOXFOX_API_KEY=super-secret\nready\n')
  fs.writeFileSync(path.join(layout.logs, 'router.stderr.log'), 'warning: nothing to do\n')

  const health = {
    ok: true,
    status: 200,
    error: null,
    body: { status: 'ok', execution: { mode: 'host', cua_enabled: false }, apiKey: 'sk-live-123' },
  }
  const result = writeDiagnosticsArchive({
    layout,
    version: '0.1.0',
    commit: 'f8f33b3',
    mode: 'host',
    modeReason: 'host mode selected.',
    ports: { gateway: 41001, router: 41002, harness: 41003, box: 41004 },
    runtime: { node: '/runtime/node/node.exe', python: '/runtime/python/python.exe' },
    dataPaths: { harness: layout.harness, router: layout.router, ui: layout.ui },
    runtimeDir,
    runtimeBundle: { target: 'win-x64', artifacts: [{ name: 'Node.js 24.9.0 (win-x64)', version: '24.9.0' }] },
    health,
    services: emptyServices(),
    docker: null,
    now: new Date('2026-10-06T12:00:00.000Z'),
  })

  assert.equal(path.dirname(result.zipPath), diagnosticsDir(root))
  assert.match(path.basename(result.zipPath), /^boxfox-diagnostics-.*\.zip$/)
  assert.ok(fs.statSync(result.zipPath).isFile())

  const buffer = fs.readFileSync(result.zipPath)
  const names = zipEntryNames(buffer)
  assert.deepEqual(names, ['manifest.json', 'health.json', 'summary.txt', 'logs/harness.stdout.log', 'logs/router.stderr.log'])

  const manifestRaw = readZipEntryBuffer(buffer, 'manifest.json').toString('utf8')
  const manifest = JSON.parse(manifestRaw)
  assert.equal(manifest.version, '0.1.0')
  assert.equal(manifest.commit, 'f8f33b3')
  assert.equal(manifest.mode, 'host')
  assert.deepEqual(manifest.ports, { gateway: 41001, router: 41002, harness: 41003, box: 41004 })
  assert.equal(manifest.paths.profileRoot, root)
  assert.equal(manifest.paths.data.harness, layout.harness)
  assert.equal(manifest.runtimeBundle.target, 'win-x64')
  assert.deepEqual(manifest.runtimeBundle.files, [
    { path: 'node/node.exe', bytes: 'node-binary'.length, sha256: createHash('sha256').update('node-binary').digest('hex') },
  ])
  assert.equal(manifest.health.ok, true)
  assert.equal(manifest.health.status, 200)

  const healthJson = JSON.parse(readZipEntryBuffer(buffer, 'health.json').toString('utf8'))
  assert.equal(healthJson.status, 'ok')
  assert.equal(healthJson.execution.mode, 'host')
  assert.equal(healthJson.apiKey, REDACTED)

  const harnessLog = readZipEntryBuffer(buffer, 'logs/harness.stdout.log').toString('utf8')
  assert.match(harnessLog, /ready/)
  assert.ok(!harnessLog.includes('super-secret'), 'the API key from the log must not reach the bundle')
  assert.match(harnessLog, /BOXFOX_API_KEY=\[REDACTED\]/)

  assert.ok(!manifestRaw.includes('super-secret'))
  assert.ok(!manifestRaw.includes('sk-live-123'))
})

test('fetchHarnessHealth parses the JSON answer and never throws', async (t) => {
  const { server, baseUrl } = await startServer((req, res) => {
    res.writeHead(200, { 'content-type': 'application/json' })
    res.end(JSON.stringify({ status: 'ok', path: req.url }))
  })
  t.after(() => closeServer(server))

  const health = await fetchHarnessHealth({ baseUrl })
  assert.equal(health.ok, true)
  assert.equal(health.status, 200)
  assert.deepEqual(health.body, { status: 'ok', path: '/api/agent/health' })

  const { server: dead, baseUrl: deadUrl } = await startServer((_req, res) => res.end())
  await closeServer(dead)
  const failed = await fetchHarnessHealth({ baseUrl: deadUrl, timeoutMs: 1000 })
  assert.equal(failed.ok, false)
  assert.equal(failed.status, null)
  assert.ok(failed.error)
})
