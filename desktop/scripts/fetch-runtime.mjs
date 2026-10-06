#!/usr/bin/env node
/**
 * Fetch the Windows x64 runtime bundle of BoxFox Desktop (Alpha) — plan §6 PR-2 / D1.
 *
 *   node desktop/scripts/fetch-runtime.mjs                 # download + verify + extract + lock
 *   node desktop/scripts/fetch-runtime.mjs --check         # verify an existing runtime against the lock
 *
 * What it downloads (never committed — `desktop/runtime/` is gitignored):
 *   - Node 24 win-x64 zip                  (sha256 checked against SHASUMS256.txt AND the pin)
 *   - CPython 3.13 embeddable win-x64 zip  (sha256 checked against the pin in runtime-sources.json)
 *   - every wheel of backend/requirements.runtime.txt for win_amd64 / cp313
 *     (`pip download --platform win_amd64 --python-version 3.13 --only-binary=:all:`),
 *     each wheel's sha256 checked against the digest PyPI publishes for that exact file
 *     (`https://pypi.org/pypi/<name>/<version>/json` → `urls[].digests.sha256`).
 *
 * The extracted layout is what the supervisor and electron-builder expect:
 *
 *   runtime/<target>/node/        Node distribution (node.exe at the root, no version dir)
 *   runtime/<target>/python/      CPython embeddable + Lib/site-packages (the wheels)
 *   runtime/<target>/wheels/      the .whl files themselves (re-installable)
 *
 * and it writes `desktop/runtime.lock.json` + `desktop/THIRD-PARTY.md`.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { downloadFile, fetchText } from './lib/download.mjs'
import { runCommand } from './lib/exec.mjs'
import { formatBytes, sha256File } from './lib/hash.mjs'
import {
  BLOCK_NAMES,
  buildRuntimeLock,
  readRuntimeLock,
  renderThirdParty,
  runtimePaths,
  verifyRuntime,
  writeRuntimeLock,
} from './lib/runtime-lock.mjs'
import { extractZipBuffer, extractZipFile, readZipEntryBuffer, stripPrefixMap, topLevelPrefix, zipEntryNames } from './lib/zip.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const DESKTOP_DIR = path.resolve(HERE, '..')
export const REPO_ROOT = path.resolve(DESKTOP_DIR, '..')

export const DEFAULT_SOURCES_FILE = path.join(DESKTOP_DIR, 'runtime-sources.json')
export const DEFAULT_LOCK_FILE = path.join(DESKTOP_DIR, 'runtime.lock.json')
export const DEFAULT_THIRD_PARTY_FILE = path.join(DESKTOP_DIR, 'THIRD-PARTY.md')

const PLACEHOLDER = 'PLACEHOLDER'

export function parseArgs(argv) {
  const options = {
    check: false,
    target: null,
    out: null,
    lock: DEFAULT_LOCK_FILE,
    sources: DEFAULT_SOURCES_FILE,
    pipPython: process.env.BOXFOX_PIP_PYTHON ?? (process.platform === 'win32' ? 'python' : 'python3'),
    keepDownloads: true,
    json: false,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--check') options.check = true
    else if (arg === '--json') options.json = true
    else if (arg === '--no-keep-downloads') options.keepDownloads = false
    else if (arg === '--target') options.target = argv[++index]
    else if (arg === '--out') options.out = argv[++index]
    else if (arg === '--lock') options.lock = path.resolve(argv[++index])
    else if (arg === '--sources') options.sources = path.resolve(argv[++index])
    else if (arg === '--pip-python') options.pipPython = argv[++index]
    else if (arg === '--help' || arg === '-h') options.help = true
    else throw new Error(`Unknown argument: ${arg}`)
  }
  return options
}

export function loadSources(file = DEFAULT_SOURCES_FILE) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

export function runtimeOutDir(sources, target, out) {
  return out ? path.resolve(out) : path.join(DESKTOP_DIR, 'runtime', target ?? sources.target)
}

function fillTemplate(template, version) {
  return template.replaceAll('{version}', version)
}

/** `SHASUMS256.txt` line of the requested archive → its published sha256. */
export function shasumsEntry(shasumsText, filename) {
  for (const line of shasumsText.split(/\r?\n/)) {
    const match = /^([0-9a-fA-F]{64})\s+\*?(.+)$/.exec(line.trim())
    if (match && match[2] === filename) return match[1].toLowerCase()
  }
  return null
}

/** Make the embeddable CPython able to import from `Lib/site-packages`. */
export function patchPth(pythonDir) {
  const candidates = fs.readdirSync(pythonDir).filter((name) => name.endsWith('._pth'))
  if (candidates.length === 0) throw new Error(`No ._pth file found in ${pythonDir} — is this the embeddable distribution?`)
  const file = path.join(pythonDir, candidates[0])
  const original = fs.readFileSync(file, 'utf8')
  const lines = original.split(/\r?\n/)
  const wanted = ['Lib\\site-packages', 'import site']
  const next = []
  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed === '#import site') continue
    if (trimmed === '') continue
    next.push(line)
  }
  for (const line of wanted) {
    if (!next.some((existing) => existing.trim() === line)) next.push(line)
  }
  const patched = `${next.join('\n')}\n`
  if (patched !== original) fs.writeFileSync(file, patched, 'utf8')
  return file
}

/** Destination of one wheel entry: `.data/{purelib,platlib,scripts,data}` are remapped. */
export function wheelEntryTarget(name, paths) {
  const segments = name.split('/')
  const dataIndex = segments.findIndex((segment) => segment.endsWith('.data'))
  if (dataIndex >= 0 && segments.length > dataIndex + 2) {
    const kind = segments[dataIndex + 1]
    const rest = segments.slice(dataIndex + 2)
    if (kind === 'scripts') return path.join(paths.python, 'Scripts', ...rest)
    if (kind === 'data') return path.join(paths.python, ...rest)
    if (kind === 'headers') return null
    return path.join(paths.sitePackages, ...rest)
  }
  return path.join(paths.sitePackages, ...segments)
}

/** `dist-1.2.3-cp313-cp313-win_amd64.whl` → `{ name: 'dist', version: '1.2.3' }`. */
export function parseWheelFilename(filename) {
  const stem = filename.replace(/\.whl$/i, '')
  const parts = stem.split('-')
  if (parts.length < 3) throw new Error(`Not a wheel filename: ${filename}`)
  return { name: parts[0].replace(/_/g, '-').toLowerCase(), version: parts[1] }
}

/**
 * The sha256 PyPI publishes for a wheel, from the JSON API
 * (`https://pypi.org/pypi/<name>/<version>/json` → `urls[].digests.sha256`).
 * Returns `null` when the file is not listed (e.g. an alternate index).
 */
export async function pypiWheelDigest(filename, options = {}) {
  const { name, version } = parseWheelFilename(filename)
  const json = JSON.parse(await fetchText(`https://pypi.org/pypi/${name}/${version}/json`, options))
  const entry = (json.urls ?? []).find((item) => item.filename === filename)
  return entry?.digests?.sha256 ? entry.digests.sha256.toLowerCase() : null
}

export async function runPipDownload({ pipPython, requirements, dest, platform, pythonVersion, onLine }) {
  const args = [
    '-m',
    'pip',
    'download',
    '--disable-pip-version-check',
    '--only-binary=:all:',
    '--platform',
    platform,
    '--python-version',
    pythonVersion,
    '--dest',
    dest,
    '-r',
    requirements,
  ]
  onLine(`[fetch] ${pipPython} ${args.join(' ')}`)
  const result = await runCommand(pipPython, args, { timeoutMs: 30 * 60_000, onLine })
  if (result.code !== 0) {
    throw new Error(`pip download failed (exit ${result.code}).\n${result.stderr.split('\n').slice(-15).join('\n')}`)
  }
  return fs.readdirSync(dest).filter((name) => name.toLowerCase().endsWith('.whl')).sort()
}

function readWheelMetadata(wheelFile) {
  const buffer = fs.readFileSync(wheelFile)
  const metadataName = zipEntryNames(buffer).find((name) => name.endsWith('.dist-info/METADATA'))
  if (!metadataName) return { name: path.basename(wheelFile), version: 'unknown', license: null }
  const text = readZipEntryBuffer(buffer, metadataName)?.toString('utf8') ?? ''
  const fields = {}
  for (const line of text.split(/\r?\n/)) {
    const match = /^([A-Za-z-]+):\s*(.*)$/.exec(line)
    if (match && fields[match[1].toLowerCase()] === undefined) fields[match[1].toLowerCase()] = match[2].trim()
  }
  return {
    name: fields.name ?? path.basename(wheelFile),
    version: fields.version ?? 'unknown',
    license: fields.license && fields.license !== 'UNKNOWN' ? fields.license : null,
  }
}

export async function fetchRuntime(options, io = console) {
  const log = (line) => io.log(line)
  const sources = loadSources(options.sources)
  const target = options.target ?? sources.target
  const outDir = runtimeOutDir(sources, target, options.out)
  const paths = runtimePaths(outDir)
  const downloads = path.join(DESKTOP_DIR, 'runtime', '.downloads')
  fs.mkdirSync(paths.root, { recursive: true })
  fs.mkdirSync(downloads, { recursive: true })
  const artifacts = []

  // --- Node -----------------------------------------------------------------
  const nodeUrl = fillTemplate(sources.node.url, sources.node.version)
  const nodeShasumsUrl = fillTemplate(sources.node.shasumsUrl, sources.node.version)
  let nodeExpected = sources.node.sha256 && sources.node.sha256 !== PLACEHOLDER ? sources.node.sha256.toLowerCase() : null
  try {
    const published = shasumsEntry(await fetchText(nodeShasumsUrl), sources.node.zip)
    if (published === null) log(`[fetch] warning: ${sources.node.zip} is not listed in ${nodeShasumsUrl}`)
    else if (nodeExpected !== null && published !== nodeExpected) {
      throw new Error(`Pinned Node hash does not match the published SHASUMS256.txt entry for ${sources.node.zip}.`)
    } else {
      nodeExpected = published
      log(`[fetch] Node hash confirmed by SHASUMS256.txt: ${published}`)
    }
  } catch (error) {
    if (nodeExpected === null) throw error
    log(`[fetch] warning: could not check SHASUMS256.txt (${error.message}); using the pinned hash.`)
  }
  const nodeZip = path.join(downloads, sources.node.zip)
  log(`[fetch] node ${sources.node.version}: ${nodeUrl}`)
  const nodeArtifact = await downloadFile(nodeUrl, nodeZip, {
    expectedSha256: nodeExpected,
    onProgress: (bytes, total) => io.progress?.('node', bytes, total),
  })
  log(`[fetch] node zip sha256=${nodeArtifact.sha256} (${formatBytes(nodeArtifact.bytes)})`)
  artifacts.push({
    name: `Node.js ${sources.node.version} (win-x64)`,
    version: sources.node.version,
    url: nodeUrl,
    sha256: nodeArtifact.sha256,
    bytes: nodeArtifact.bytes,
    license: 'MIT',
    verifiedBy: nodeExpected === null ? 'downloaded hash (pin it in runtime-sources.json)' : 'SHASUMS256.txt + pin',
  })
  fs.rmSync(paths.node, { recursive: true, force: true })
  // The Node distribution nests everything under `node-v<version>-win-x64/`; the
  // supervisor expects `<runtime>/node/node.exe`, so the prefix is stripped.
  const nodeBuffer = fs.readFileSync(nodeZip)
  const nodePrefix = topLevelPrefix(nodeBuffer)
  if (nodePrefix) log(`[fetch] stripping the ${nodePrefix} prefix from the Node archive`)
  extractZipBuffer(nodeBuffer, paths.node, nodePrefix ? { map: stripPrefixMap(paths.node, nodePrefix) } : {})
  log(`[fetch] extracted Node → ${paths.node}`)

  // --- CPython --------------------------------------------------------------
  const pythonUrl = fillTemplate(sources.python.url, sources.python.version)
  const pythonExpected = sources.python.sha256 && sources.python.sha256 !== PLACEHOLDER ? sources.python.sha256.toLowerCase() : null
  const pythonZip = path.join(downloads, sources.python.zip)
  log(`[fetch] python ${sources.python.version}: ${pythonUrl}`)
  const pythonArtifact = await downloadFile(pythonUrl, pythonZip, {
    expectedSha256: pythonExpected,
    onProgress: (bytes, total) => io.progress?.('python', bytes, total),
  })
  if (pythonExpected === null) {
    log(`[fetch] WARNING: pin python.sha256 = "${pythonArtifact.sha256}" in runtime-sources.json`)
  }
  log(`[fetch] python zip sha256=${pythonArtifact.sha256} (${formatBytes(pythonArtifact.bytes)})`)
  artifacts.push({
    name: `CPython ${sources.python.version} (embeddable, win-x64)`,
    version: sources.python.version,
    url: pythonUrl,
    sha256: pythonArtifact.sha256,
    bytes: pythonArtifact.bytes,
    license: sources.python.license ?? 'PSF-2.0',
    verifiedBy: pythonExpected === null ? 'downloaded hash (pin it in runtime-sources.json)' : 'pin in runtime-sources.json',
  })
  fs.rmSync(paths.python, { recursive: true, force: true })
  extractZipFile(pythonZip, paths.python)
  const pth = patchPth(paths.python)
  log(`[fetch] extracted CPython → ${paths.python} (patched ${path.basename(pth)})`)

  // --- wheels ---------------------------------------------------------------
  const requirements = path.resolve(REPO_ROOT, sources.wheels.requirements)
  if (!fs.existsSync(requirements)) throw new Error(`Requirements file is missing: ${requirements}`)
  const wheelDest = path.join(downloads, 'wheels')
  fs.rmSync(wheelDest, { recursive: true, force: true })
  fs.mkdirSync(wheelDest, { recursive: true })
  const wheelFiles = await runPipDownload({
    pipPython: options.pipPython,
    requirements,
    dest: wheelDest,
    platform: sources.wheels.platform,
    pythonVersion: sources.wheels.pythonVersion,
    onLine: (line) => log(`[pip] ${line}`),
  })
  fs.rmSync(paths.wheels, { recursive: true, force: true })
  fs.rmSync(paths.sitePackages, { recursive: true, force: true })
  fs.mkdirSync(paths.wheels, { recursive: true })
  fs.mkdirSync(paths.sitePackages, { recursive: true })
  const wheelRecords = []
  for (const filename of wheelFiles) {
    const source = path.join(wheelDest, filename)
    const sha256 = await sha256File(source)
    let published = null
    try {
      published = await pypiWheelDigest(filename)
    } catch (error) {
      log(`[fetch] warning: could not read the PyPI digest for ${filename} (${error.message})`)
    }
    if (published === null) {
      log(`[fetch] WARNING: ${filename} is not listed on PyPI; trusting the local hash ${sha256}`)
    } else if (published !== sha256) {
      throw new Error(`SHA-256 mismatch for ${filename}\n  PyPI     ${published}\n  download ${sha256}`)
    }
    const metadata = readWheelMetadata(source)
    fs.copyFileSync(source, path.join(paths.wheels, filename))
    const buffer = fs.readFileSync(source)
    extractZipBuffer(buffer, paths.sitePackages, { map: (name) => wheelEntryTarget(name, paths) })
    wheelRecords.push({
      name: metadata.name,
      version: metadata.version,
      filename,
      sha256,
      license: metadata.license,
      verifiedBy: published === null ? 'local hash (not listed on PyPI)' : 'PyPI digests.sha256',
    })
    log(`[fetch] wheel ${filename} (${metadata.name} ${metadata.version}) ${published === null ? 'unverified' : 'verified'}`)
  }
  wheelRecords.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
  log(`[fetch] installed ${wheelRecords.length} wheels into ${paths.sitePackages}`)

  // --- lock + third party ---------------------------------------------------
  const lock = await buildRuntimeLock({ target, sources, artifacts, wheels: wheelRecords, outDir })
  writeRuntimeLock(options.lock, lock)
  const thirdParty = renderThirdParty(lock)
  fs.writeFileSync(DEFAULT_THIRD_PARTY_FILE, thirdParty, 'utf8')
  log(`[fetch] wrote ${options.lock}`)
  log(`[fetch] wrote ${DEFAULT_THIRD_PARTY_FILE}`)
  for (const name of BLOCK_NAMES) {
    const block = lock.blocks[name]
    log(`[fetch] block ${name}: ${block.files} files, ${formatBytes(block.bytes)}, sha256 ${block.sha256.slice(0, 16)}…`)
  }
  if (!options.keepDownloads) fs.rmSync(downloads, { recursive: true, force: true })
  return lock
}

export async function checkRuntime(options, io = console) {
  const log = (line) => io.log(line)
  const lock = readRuntimeLock(options.lock)
  const sources = fs.existsSync(options.sources) ? loadSources(options.sources) : null
  const outDir = runtimeOutDir(lock, options.target ?? lock.target, options.out)
  const report = await verifyRuntime(lock, outDir)
  const lines = [
    `[check] target ${report.target} in ${outDir}`,
    `[check] lock ${options.lock} (created ${lock.createdAt})`,
  ]
  for (const result of report.results) {
    lines.push(`[check] ${result.ok ? 'OK  ' : 'FAIL'} ${result.name.padEnd(7)} ${result.detail}`)
  }
  if (sources) {
    if (sources.node?.version && lock.sources?.node?.version && sources.node.version !== lock.sources.node.version) {
      lines.push(`[check] WARN the lock was built from Node ${lock.sources.node.version}, runtime-sources.json pins ${sources.node.version}`)
    }
    if (sources.python?.version && lock.sources?.python?.version && sources.python.version !== lock.sources.python.version) {
      lines.push(`[check] WARN the lock was built from CPython ${lock.sources.python.version}, runtime-sources.json pins ${sources.python.version}`)
    }
  }
  lines.push(report.ok ? '[check] runtime matches the lock.' : '[check] runtime does NOT match the lock.')
  for (const line of lines) log(line)
  return report
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help) {
    process.stdout.write(
      [
        'Usage: node desktop/scripts/fetch-runtime.mjs [options]',
        '',
        '  --check                verify an existing runtime against runtime.lock.json',
        '  --target <name>        runtime target directory (default: runtime-sources.json target)',
        '  --out <dir>            extract into this directory instead of desktop/runtime/<target>',
        '  --lock <file>          lock file (default: desktop/runtime.lock.json)',
        '  --sources <file>       pinned sources (default: desktop/runtime-sources.json)',
        '  --pip-python <exe>     interpreter used for `pip download` (default: python3 / python)',
        '  --no-keep-downloads    delete the download cache afterwards',
        '',
      ].join('\n'),
    )
    return 0
  }
  const io = {
    log: (line) => process.stdout.write(`${line}\n`),
    progress: (name, bytes, total) => {
      if (total > 0 && bytes % (8 * 1024 * 1024) < 64 * 1024) {
        process.stdout.write(`\r[fetch] ${name} ${Math.round((bytes / total) * 100)}%   `)
      }
    },
  }
  if (options.check) {
    const report = await checkRuntime(options, io)
    return report.ok ? 0 : 1
  }
  await fetchRuntime(options, io)
  process.stdout.write('\n')
  return 0
}

const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (invokedDirectly) {
  main()
    .then((code) => {
      process.exitCode = code
    })
    .catch((error) => {
      process.stderr.write(`fetch-runtime failed: ${error.message}\n`)
      process.exitCode = 1
    })
}
