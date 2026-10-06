/**
 * The build scripts: ZIP reader/writer, verified downloads, the runtime lock and the
 * bundle manifest. Plan §6 PR-2 / D1: "tải … kiểm sha256, giải nén …, ghi
 * desktop/runtime.lock.json + THIRD-PARTY.md" and "ghi build-manifest.json (version,
 * commit, thời điểm, sha256 từng khối)". Kiểm D1: "test script kiểm lock/manifest".
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'

import { downloadFile, fetchText } from '../scripts/lib/download.mjs'
import { blockSummary, fileManifest, formatBytes, manifestDigest, sha256Buffer, sha256File } from '../scripts/lib/hash.mjs'
import {
  BLOCK_NAMES,
  buildRuntimeLock,
  readRuntimeLock,
  renderThirdParty,
  runtimePaths,
  verifyRuntime,
  writeRuntimeLock,
} from '../scripts/lib/runtime-lock.mjs'
import {
  extractZipBuffer,
  extractZipFile,
  readZipEntries,
  stripPrefixMap,
  topLevelPrefix,
  writeZipFile,
  zipEntryNames,
} from '../scripts/lib/zip.mjs'
import { bundledNodeBinary, bundledPythonBinary } from '../dist/supervisor.js'
import { copyTree, parseArgs as parseBuildArgs, shouldCopy } from '../scripts/build-app.mjs'
import { parseArgs as parseFetchArgs, parseWheelFilename, patchPth, shasumsEntry, wheelEntryTarget } from '../scripts/fetch-runtime.mjs'

const DESKTOP_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function tempDir(t, prefix = 'boxfox-scripts-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

test('the zip writer and reader round-trip, and extraction restores the executable bit', async (t) => {
  const dir = tempDir(t)
  const zip = path.join(dir, 'bundle.zip')
  const entries = [
    { name: 'node/node.exe', data: Buffer.from('binary'), mode: 0o755 },
    { name: 'node/README.md', data: Buffer.from('docs'), mode: 0o644 },
    { name: 'dir/nested/file.txt', data: Buffer.from('nested'), mode: 0o644 },
  ]
  await writeZipFile(zip, entries, { compress: true })

  const buffer = fs.readFileSync(zip)
  assert.deepEqual(zipEntryNames(buffer), ['node/node.exe', 'node/README.md', 'dir/nested/file.txt'])
  const out = path.join(dir, 'out')
  const result = extractZipFile(zip, out)
  assert.equal(result.files, 3)
  assert.equal(fs.readFileSync(path.join(out, 'node', 'node.exe'), 'utf8'), 'binary')
  assert.equal(fs.readFileSync(path.join(out, 'dir', 'nested', 'file.txt'), 'utf8'), 'nested')
  if (process.platform !== 'win32') {
    assert.equal(fs.statSync(path.join(out, 'node', 'node.exe')).mode & 0o111, 0o111)
    assert.equal(fs.statSync(path.join(out, 'node', 'README.md')).mode & 0o111, 0)
  }
})

test('a nested distribution archive is detected and can be flattened', async (t) => {
  const dir = tempDir(t)
  const nested = path.join(dir, 'nested.zip')
  await writeZipFile(nested, [
    { name: 'node-v24.9.0-win-x64/node.exe', data: Buffer.from('exe') },
    { name: 'node-v24.9.0-win-x64/npm/bin/npm-cli.js', data: Buffer.from('npm') },
  ])
  const nestedBuffer = fs.readFileSync(nested)
  assert.equal(topLevelPrefix(nestedBuffer), 'node-v24.9.0-win-x64/')

  const out = path.join(dir, 'out')
  extractZipBuffer(nestedBuffer, out, { map: stripPrefixMap(out, 'node-v24.9.0-win-x64/') })
  assert.equal(fs.readFileSync(path.join(out, 'node.exe'), 'utf8'), 'exe')
  assert.equal(fs.readFileSync(path.join(out, 'npm', 'bin', 'npm-cli.js'), 'utf8'), 'npm')

  const flat = path.join(dir, 'flat.zip')
  await writeZipFile(flat, [
    { name: 'python.exe', data: Buffer.from('exe') },
    { name: 'python313._pth', data: Buffer.from('.') },
  ])
  assert.equal(topLevelPrefix(fs.readFileSync(flat)), null, 'a flat archive must not be flattened again')
})

test('extraction refuses entries that escape the destination', async (t) => {
  const dir = tempDir(t)
  const zip = path.join(dir, 'evil.zip')
  await writeZipFile(zip, [{ name: '../escape.txt', data: Buffer.from('nope') }])
  assert.throws(() => extractZipFile(zip, path.join(dir, 'out')), /Unsafe zip entry/)
  assert.ok(!fs.existsSync(path.join(dir, 'escape.txt')))
})

test('a remap function can redirect entries (used for wheel .data/ directories)', async (t) => {
  const dir = tempDir(t)
  const zip = path.join(dir, 'wheel.zip')
  await writeZipFile(zip, [
    { name: 'pkg/__init__.py', data: Buffer.from('a') },
    { name: 'pkg-1.0.data/scripts/tool.py', data: Buffer.from('b') },
    { name: 'pkg-1.0.data/headers/pkg.h', data: Buffer.from('c') },
  ])
  const out = path.join(dir, 'out')
  const scripts = path.join(dir, 'Scripts')
  extractZipBuffer(fs.readFileSync(zip), out, {
    map: (name) => (name.endsWith('.data/scripts/tool.py') ? path.join(scripts, 'tool.py') : name.includes('.data/headers/') ? null : path.join(out, name)),
  })
  assert.equal(fs.readFileSync(path.join(out, 'pkg', '__init__.py'), 'utf8'), 'a')
  assert.equal(fs.readFileSync(path.join(scripts, 'tool.py'), 'utf8'), 'b')
  assert.ok(!fs.existsSync(path.join(out, 'pkg-1.0.data')))
})

test('downloadFile verifies the hash, deletes a mismatching .part and keeps the cache', async (t) => {
  const dir = tempDir(t)
  const payload = Buffer.from('boxfox-runtime-artifact')
  const good = sha256Buffer(payload)
  const response = () => ({ ok: true, status: 200, headers: new Headers({ 'content-length': String(payload.length) }), body: ReadableStreamFrom(payload) })

  const dest = path.join(dir, 'artifact.bin')
  const ok = await downloadFile('http://example.invalid/artifact.bin', dest, { expectedSha256: good, fetchImpl: async () => response() })
  assert.equal(ok.sha256, good)
  assert.equal(fs.readFileSync(dest).toString('utf8'), 'boxfox-runtime-artifact')
  assert.ok(!fs.existsSync(`${dest}.part`), 'the partial file is renamed, not left behind')

  let calls = 0
  const cached = await downloadFile('http://example.invalid/artifact.bin', dest, {
    expectedSha256: good,
    fetchImpl: async () => {
      calls += 1
      return response()
    },
  })
  assert.equal(cached.cached, true)
  assert.equal(calls, 0, 'an artifact that already matches the pin is not downloaded again')

  const bad = path.join(dir, 'bad.bin')
  await assert.rejects(
    () => downloadFile('http://example.invalid/bad.bin', bad, { expectedSha256: 'f'.repeat(64), fetchImpl: async () => response() }),
    /SHA-256 mismatch/,
  )
  assert.ok(!fs.existsSync(bad), 'a mismatching artifact is never written')
  assert.ok(!fs.existsSync(`${bad}.part`), 'the partial download is deleted')

  await assert.rejects(() => downloadFile('http://example.invalid/x', path.join(dir, 'x'), { fetchImpl: async () => ({ ok: false, status: 404 }) }), /HTTP 404/)
  await assert.rejects(() => fetchText('http://example.invalid/x', { fetchImpl: async () => ({ ok: false, status: 500 }) }), /HTTP 500/)
})

/** Minimal web ReadableStream from a Buffer (Node 24 has `ReadableStream` globally). */
function ReadableStreamFrom(buffer) {
  return new ReadableStream({
    start(controller) {
      controller.enqueue(new Uint8Array(buffer))
      controller.close()
    },
  })
}

test('the manifest digest changes when a file, byte or name changes', async (t) => {
  const dir = tempDir(t)
  fs.writeFileSync(path.join(dir, 'a.txt'), 'a')
  fs.mkdirSync(path.join(dir, 'sub'))
  fs.writeFileSync(path.join(dir, 'sub', 'b.txt'), 'b')
  const before = await blockSummary(dir)
  assert.equal(before.files, 2)
  assert.equal(before.bytes, 2)
  assert.equal(before.sha256, manifestDigest(await fileManifest(dir)))
  assert.equal(before.sha256, (await blockSummary(dir)).sha256, 'the digest is stable')

  fs.writeFileSync(path.join(dir, 'sub', 'b.txt'), 'bb')
  const after = await blockSummary(dir)
  assert.notEqual(after.sha256, before.sha256)
  assert.equal(after.bytes, 3)

  fs.rmSync(path.join(dir, 'sub', 'b.txt'))
  const removed = await blockSummary(dir)
  assert.notEqual(removed.sha256, before.sha256)
  assert.equal(removed.files, 1)
  assert.equal(formatBytes(1024), '1.0 KiB')
})

test('the runtime lock verifies an intact runtime and reports a tampered one', async (t) => {
  const outDir = path.join(tempDir(t), 'win-x64')
  const paths = runtimePaths(outDir)
  for (const name of BLOCK_NAMES) fs.mkdirSync(paths[name], { recursive: true })
  fs.writeFileSync(path.join(paths.node, 'node.exe'), 'node')
  fs.writeFileSync(path.join(paths.python, 'python.exe'), 'python')
  fs.writeFileSync(path.join(paths.python, 'python313._pth'), 'python313.zip\n.')
  fs.writeFileSync(path.join(paths.wheels, 'aiohttp-3.14.4-cp313-cp313-win_amd64.whl'), 'whl')

  const lock = await buildRuntimeLock({
    target: 'win-x64',
    sources: { node: { version: '24.9.0' }, python: { version: '3.13.7' } },
    artifacts: [{ name: 'Node.js 24.9.0 (win-x64)', version: '24.9.0', url: 'https://nodejs.org/…', sha256: 'a'.repeat(64), bytes: 123, license: 'MIT', verifiedBy: 'SHASUMS256.txt + pin' }],
    wheels: [{ name: 'aiohttp', version: '3.14.4', filename: 'aiohttp-3.14.4-cp313-cp313-win_amd64.whl', sha256: 'b'.repeat(64), license: 'Apache-2.0', verifiedBy: 'PyPI digests.sha256' }],
    outDir,
  })
  const lockFile = path.join(outDir, 'runtime.lock.json')
  writeRuntimeLock(lockFile, lock)
  const reread = readRuntimeLock(lockFile)
  assert.equal(reread.target, 'win-x64')
  assert.equal(reread.version, 1)
  assert.match(reread.createdAt, /^\d{4}-\d{2}-\d{2}T/)

  const clean = await verifyRuntime(reread, outDir)
  assert.equal(clean.ok, true)
  for (const result of clean.results) assert.equal(result.detail, 'matches the lock')

  fs.writeFileSync(path.join(paths.python, 'python.exe'), 'python-tampered')
  const tampered = await verifyRuntime(reread, outDir)
  assert.equal(tampered.ok, false)
  assert.deepEqual(
    tampered.results.filter((result) => !result.ok).map((result) => result.name),
    ['python'],
  )
  assert.match(tampered.results.find((result) => result.name === 'python').detail, /manifest digest/)

  fs.rmSync(paths.wheels, { recursive: true, force: true })
  const missing = await verifyRuntime(reread, outDir)
  assert.equal(missing.results.find((result) => result.name === 'wheels').detail, 'directory is missing')

  const rendered = renderThirdParty(reread)
  assert.match(rendered, /# Third-party software bundled with BoxFox Desktop \(Alpha\)/)
  assert.match(rendered, /aiohttp/)
  assert.match(rendered, /PyPI digests\.sha256|Apache-2\.0/)
})

test('the embeddable CPython ._pth is patched to import from Lib/site-packages', (t) => {
  const pythonDir = tempDir(t)
  const pth = path.join(pythonDir, 'python313._pth')
  fs.writeFileSync(pth, 'python313.zip\n.\n# Uncomment to run site.main() automatically\n#import site\n')
  const patched = patchPth(pythonDir)
  assert.equal(patched, pth)
  const lines = fs
    .readFileSync(pth, 'utf8')
    .split('\n')
    .filter((line) => line !== '' && !line.startsWith('#'))
  assert.deepEqual(lines, ['python313.zip', '.', 'Lib\\site-packages', 'import site'])
  assert.ok(!fs.readFileSync(pth, 'utf8').includes('\n#import site'))
  assert.equal(patchPth(pythonDir), pth, 'patching twice is a no-op')
  assert.equal(patchPth(pythonDir), pth)
  assert.ok(fs.readFileSync(pth, 'utf8').endsWith('Lib\\site-packages\nimport site\n'))
  const empty = tempDir(t, 'boxfox-nopth-')
  assert.throws(() => patchPth(empty), /No \._pth file/)
})

test('wheel filenames and .data/ targets are resolved the way pip installs them', () => {
  assert.deepEqual(parseWheelFilename('aiohttp-3.14.4-cp313-cp313-win_amd64.whl'), { name: 'aiohttp', version: '3.14.4' })
  assert.deepEqual(parseWheelFilename('charset_normalizer-3.5.2-cp313-cp313-win_amd64.whl'), { name: 'charset-normalizer', version: '3.5.2' })
  assert.throws(() => parseWheelFilename('nope.whl'), /Not a wheel filename/)

  const python = path.join('rt', 'python')
  const sitePackages = path.join(python, 'Lib', 'site-packages')
  const paths = { python, sitePackages }
  assert.equal(wheelEntryTarget('aiohttp/__init__.py', paths), path.join(sitePackages, 'aiohttp', '__init__.py'))
  assert.equal(wheelEntryTarget('pkg-1.0.data/purelib/pkg/x.py', paths), path.join(sitePackages, 'pkg', 'x.py'))
  assert.equal(wheelEntryTarget('pkg-1.0.data/platlib/pkg/y.py', paths), path.join(sitePackages, 'pkg', 'y.py'))
  assert.equal(wheelEntryTarget('pkg-1.0.data/scripts/tool.exe', paths), path.join(python, 'Scripts', 'tool.exe'))
  assert.equal(wheelEntryTarget('pkg-1.0.data/data/share/z', paths), path.join(python, 'share', 'z'))
  assert.equal(wheelEntryTarget('pkg-1.0.data/headers/pkg.h', paths), null)
})

test('SHASUMS256.txt parsing accepts the published Node line format', () => {
  const arm64 = 'b'.repeat(64)
  const text = [
    `${'a'.repeat(64)}  node-v24.9.0-darwin-arm64.tar.gz`,
    '6873514c3e6a012917cc6f95ce48a6289253370d025f1b69db290d70feebfa6e  node-v24.9.0-win-x64.zip',
    `${arm64} *node-v24.9.0-win-arm64.zip`,
  ].join('\n')
  assert.equal(shasumsEntry(text, 'node-v24.9.0-win-x64.zip'), '6873514c3e6a012917cc6f95ce48a6289253370d025f1b69db290d70feebfa6e')
  assert.equal(shasumsEntry(text, 'node-v24.9.0-win-arm64.zip'), arm64, 'the binary-mode marker is optional')
  assert.equal(shasumsEntry(text, 'missing.zip'), null)
})

test('both scripts parse their flags', () => {
  const fetchOptions = parseFetchArgs(['--check', '--target', 'win-x64', '--out', '/tmp/rt', '--pip-python', 'python3.13'])
  assert.equal(fetchOptions.check, true)
  assert.equal(fetchOptions.target, 'win-x64')
  assert.equal(fetchOptions.out, '/tmp/rt')
  assert.equal(fetchOptions.pipPython, 'python3.13')
  assert.throws(() => parseFetchArgs(['--nope']), /Unknown argument/)

  const buildOptions = parseBuildArgs(['--skip-ui', '--out', '/tmp/build', '--lock', '/tmp/runtime.lock.json'])
  assert.equal(buildOptions.skipUi, true)
  assert.equal(buildOptions.out, '/tmp/build')
  assert.equal(buildOptions.lockFile, '/tmp/runtime.lock.json')
  assert.throws(() => parseBuildArgs(['--nope']), /Unknown argument/)
})

test('copyTree keeps the bundle free of caches, logs and node_modules', (t) => {
  const source = tempDir(t)
  fs.mkdirSync(path.join(source, 'node_modules', 'left-pad'), { recursive: true })
  fs.writeFileSync(path.join(source, 'node_modules', 'left-pad', 'index.js'), 'x')
  fs.mkdirSync(path.join(source, '__pycache__'))
  fs.writeFileSync(path.join(source, '__pycache__', 'mod.pyc'), 'x')
  fs.writeFileSync(path.join(source, 'run.log'), 'x')
  fs.writeFileSync(path.join(source, 'keep.txt'), 'x')
  const dest = path.join(tempDir(t), 'out')
  copyTree(source, dest)
  assert.deepEqual(fs.readdirSync(dest), ['keep.txt'])
  assert.equal(shouldCopy('/a/node_modules/b'), false)
  assert.equal(shouldCopy('/a/mod.pyc'), false)
  assert.equal(shouldCopy('/a/run.log'), false)
  assert.equal(shouldCopy('/a/keep.py'), true)
})

test('the staged bundle carries a manifest with the version, commit and every block digest', async (t) => {
  // A tiny stand-in runtime so the test does not depend on the ~190 MB download.
  const runtime = tempDir(t, 'boxfox-fake-runtime-')
  fs.mkdirSync(path.join(runtime, 'node'))
  fs.mkdirSync(path.join(runtime, 'python'))
  fs.mkdirSync(path.join(runtime, 'wheels'))
  fs.writeFileSync(path.join(runtime, 'node', 'node.exe'), 'node')
  fs.writeFileSync(path.join(runtime, 'python', 'python.exe'), 'python')
  const lock = await buildRuntimeLock({ target: 'win-x64', sources: {}, artifacts: [], wheels: [], outDir: runtime })
  const lockFile = path.join(runtime, 'runtime.lock.json')
  writeRuntimeLock(lockFile, lock)

  const out = path.join(tempDir(t), 'build')
  const uiDir = tempDir(t, 'boxfox-ui-')
  fs.writeFileSync(path.join(uiDir, 'index.html'), '<!doctype html>')
  const manifest = await (await import('../scripts/build-app.mjs')).buildApp(
    { skipUi: false, uiDir, out, lockFile, runtimeSource: runtime },
    { log: () => undefined },
  )

  assert.equal(manifest.version, '0.1.0')
  assert.equal(manifest.productName, 'BoxFox Desktop (Alpha)')
  assert.equal(manifest.runtimeTarget, 'win-x64')
  assert.match(manifest.builtAt, /^\d{4}-\d{2}-\d{2}T/)
  assert.equal(manifest.commit.length, 7)
  assert.equal(typeof manifest.dirty, 'boolean')
  assert.deepEqual(Object.keys(manifest.blocks).sort(), ['docker-context', 'harness', 'router', 'runtime', 'ui'])
  for (const block of Object.values(manifest.blocks)) {
    assert.ok(block.files > 0)
    assert.match(block.sha256, /^[0-9a-f]{64}$/)
  }
  assert.equal(manifest.totals.files, Object.values(manifest.blocks).reduce((sum, block) => sum + block.files, 0))
  assert.match(manifest.digest, /^[0-9a-f]{64}$/)

  const written = JSON.parse(fs.readFileSync(path.join(out, 'build-manifest.json'), 'utf8'))
  assert.deepEqual(written, manifest)

  // The bundle must not point back at the checkout: everything it needs is staged.
  assert.ok(fs.existsSync(path.join(out, 'ui', 'index.html')))
  assert.ok(fs.existsSync(path.join(out, 'router', 'src', 'main.mjs')))
  assert.ok(fs.existsSync(path.join(out, 'harness', 'scripts', 'run-harness.py')))
  assert.ok(fs.existsSync(path.join(out, 'harness', 'backend', 'src', 'agentbox', 'api', 'server.py')))
  assert.ok(fs.existsSync(path.join(out, 'harness', 'AGENT.md')))
  assert.ok(fs.existsSync(path.join(out, 'runtime', 'node', 'node.exe')))
  assert.ok(fs.existsSync(path.join(out, 'docker-context', 'docker-compose.yml')))
  assert.ok(!fs.existsSync(path.join(out, 'router', 'node_modules')))
})

test('a fetched runtime has the layout the supervisor looks for', async (t) => {
  const lockFile = path.join(DESKTOP_DIR, 'runtime.lock.json')
  if (!fs.existsSync(lockFile)) {
    t.skip('the runtime has not been fetched on this machine')
    return
  }
  const lock = readRuntimeLock(lockFile)
  const runtimeDir = path.join(DESKTOP_DIR, 'runtime', lock.target)
  if (!fs.existsSync(runtimeDir)) {
    t.skip(`the runtime for ${lock.target} is not on disk`)
    return
  }
  const report = await verifyRuntime(lock, runtimeDir)
  assert.equal(report.ok, true, `the fetched runtime must match the lock: ${JSON.stringify(report.results)}`)

  // The supervisor resolves the binaries relative to the runtime root; a distribution
  // archive that keeps its version directory would break every start.
  for (const [name, binary] of [
    ['node', bundledNodeBinary(runtimeDir, 'win32')],
    ['python', bundledPythonBinary(runtimeDir, 'win32')],
  ]) {
    assert.ok(fs.existsSync(binary), `${name} binary must be at ${binary}`)
  }
  assert.equal(bundledPythonBinary(runtimeDir, 'linux'), path.join(runtimeDir, 'python', 'bin', 'python3'))
  const sitePackages = runtimePaths(runtimeDir).sitePackages
  const packages = fs.readdirSync(sitePackages)
  assert.ok(packages.includes('aiohttp'), 'the wheels must be installed into Lib/site-packages')
  assert.ok(packages.includes('comtypes'), 'the UIA dependency must be part of the runtime')
  assert.equal(packages.filter((entry) => entry.endsWith('.dist-info')).length, lock.wheels.length)
})

test('build-app refuses to stage without a runtime or a UI', async (t) => {
  const { buildApp } = await import('../scripts/build-app.mjs')
  const out = path.join(tempDir(t), 'build')
  const uiDir = tempDir(t, 'boxfox-ui-')
  fs.writeFileSync(path.join(uiDir, 'index.html'), '<!doctype html>')

  await assert.rejects(
    () => buildApp({ skipUi: false, out, uiDir, lockFile: path.join(DESKTOP_DIR, 'nope.json') }, { log: () => undefined }),
    /No runtime lock/,
  )

  const runtime = tempDir(t, 'boxfox-empty-runtime-')
  for (const name of BLOCK_NAMES) fs.mkdirSync(path.join(runtime, name))
  const lock = await buildRuntimeLock({ target: 'win-x64', sources: {}, artifacts: [], wheels: [], outDir: runtime })
  const lockFile = path.join(runtime, 'runtime.lock.json')
  writeRuntimeLock(lockFile, lock)
  const staged = path.join(tempDir(t), 'staged')
  await assert.rejects(() => buildApp({ skipUi: true, out: staged, lockFile, runtimeSource: runtime }, { log: () => undefined }), /--skip-ui was given/)
  await assert.rejects(
    () => buildApp({ skipUi: false, out, uiDir: tempDir(t, 'boxfox-not-a-ui-'), lockFile, runtimeSource: runtime }, { log: () => undefined }),
    /no index.html/,
  )
})
