#!/usr/bin/env node
/**
 * Stage the BoxFox Desktop bundle (plan §6 PR-2 / D1).
 *
 *   node desktop/scripts/build-app.mjs [--skip-ui] [--ui-dir <dir>] [--out <dir>]
 *
 * Produces `desktop/build/` — the exact tree electron-builder copies into
 * `resources/` (`extraResources`), which is also the tree the app uses when it runs
 * from a checkout (`paths.ts` falls back to it):
 *
 *   build/ui/               production build of frontend/
 *   build/router/           router sources (node_modules-free by design)
 *   build/harness/          scripts/run-harness.py + backend/src + AGENT.md
 *   build/runtime/          desktop/runtime/<target>/ (bundled Node + CPython + wheels)
 *   build/docker-context/   deploy/docker (build context of the sandbox image)
 *   build/build-manifest.json
 *
 * Every block is summarised (files, bytes, sha256 of the manifest digest) in
 * `build-manifest.json`, which `diagnostics.ts` reads at runtime. Nothing here points
 * back at the checkout: the paths are relative to the staged tree.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'
import { fileURLToPath } from 'node:url'
import { runCommand } from './lib/exec.mjs'
import { blockSummary, formatBytes, manifestDigest } from './lib/hash.mjs'
import { readRuntimeLock } from './lib/runtime-lock.mjs'

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const DESKTOP_DIR = path.resolve(HERE, '..')
export const REPO_ROOT = path.resolve(DESKTOP_DIR, '..')
export const BUILD_DIR = path.join(DESKTOP_DIR, 'build')

/** Directories/files that never belong in the bundle. */
const EXCLUDED_NAMES = new Set([
  'node_modules',
  '.git',
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.venv',
  'venv',
  '.DS_Store',
  'Thumbs.db',
])

export function parseArgs(argv) {
  const options = { skipUi: false, uiDir: null, out: BUILD_DIR, target: null, lockFile: null, runtimeSource: null }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--skip-ui') options.skipUi = true
    else if (arg === '--ui-dir') options.uiDir = path.resolve(argv[++index])
    else if (arg === '--out') options.out = path.resolve(argv[++index])
    else if (arg === '--target') options.target = argv[++index]
    else if (arg === '--lock') options.lockFile = path.resolve(argv[++index])
    else if (arg === '--runtime-source') options.runtimeSource = path.resolve(argv[++index])
    else if (arg === '--help' || arg === '-h') options.help = true
    else throw new Error(`Unknown argument: ${arg}`)
  }
  return options
}

export function shouldCopy(source) {
  const name = path.basename(source)
  if (name.endsWith('.pyc') || name.endsWith('.log')) return false
  // Any excluded directory name anywhere in the path prunes the whole subtree
  // (`fs.cpSync` calls this filter for directories too).
  return !source.split(/[\\/]+/).some((segment) => EXCLUDED_NAMES.has(segment))
}

export function copyTree(source, dest, options = {}) {
  const filter = options.filter ?? shouldCopy
  fs.rmSync(dest, { recursive: true, force: true })
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  fs.cpSync(source, dest, { recursive: true, dereference: false, filter })
  return dest
}

async function readJson(file, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf8'))
  } catch {
    return fallback
  }
}

async function gitInfo(repoRoot) {
  const run = async (args) => {
    const result = await runCommand('git', args, { cwd: repoRoot, timeoutMs: 20_000 })
    return result.code === 0 ? result.stdout.trim() : null
  }
  return {
    commit: await run(['rev-parse', '--short=7', 'HEAD']),
    commitFull: await run(['rev-parse', 'HEAD']),
    branch: await run(['rev-parse', '--abbrev-ref', 'HEAD']),
    dirty: (await run(['status', '--porcelain'])) !== '',
  }
}

/**
 * Stage the web UI. Order of preference:
 *   1. `--ui-dir <dir>`     — copy a UI that was built elsewhere;
 *   2. `frontend/dist`      — reuse an existing production build;
 *   3. `npm run build` in `frontend/` when its node_modules are present.
 * The desktop bundle never installs frontend dependencies itself.
 */
export async function stageUi(options, log) {
  const uiOut = path.join(options.out, 'ui')
  const frontend = path.join(REPO_ROOT, 'frontend')
  const dist = path.join(frontend, 'dist')
  if (options.uiDir) {
    if (!fs.existsSync(path.join(options.uiDir, 'index.html'))) {
      throw new Error(`--ui-dir ${options.uiDir} has no index.html — that is not a built UI.`)
    }
    copyTree(options.uiDir, uiOut)
    log(`[build] ui ← ${options.uiDir}`)
    return uiOut
  }
  if (fs.existsSync(path.join(dist, 'index.html'))) {
    copyTree(dist, uiOut)
    log(`[build] ui ← frontend/dist (existing production build)`)
    return uiOut
  }
  if (!fs.existsSync(path.join(frontend, 'node_modules'))) {
    throw new Error(
      [
        'The frontend is not built and frontend/node_modules is missing.',
        'Run `npm ci` in frontend/ (or pass --ui-dir <built-ui>) and retry.',
      ].join(' '),
    )
  }
  log('[build] ui: npm run build (frontend)')
  const result = await runCommand('npm', ['run', 'build'], {
    cwd: frontend,
    timeoutMs: 15 * 60_000,
    onLine: (line) => log(`[vite] ${line}`),
  })
  if (result.code !== 0) throw new Error(`frontend build failed (exit ${result.code}).`)
  if (!fs.existsSync(path.join(dist, 'index.html'))) throw new Error('frontend build produced no dist/index.html.')
  copyTree(dist, uiOut)
  return uiOut
}

export async function buildApp(options = {}, io = console) {
  const log = (line) => io.log(line)
  const out = options.out ?? BUILD_DIR
  fs.mkdirSync(out, { recursive: true })
  const pkg = (await readJson(path.join(DESKTOP_DIR, 'package.json'), {})) ?? {}
  const blocks = {}

  if (options.skipUi) {
    if (!fs.existsSync(path.join(out, 'ui', 'index.html'))) throw new Error(`--skip-ui was given but ${out}/ui is not staged.`)
    log('[build] ui: reusing the staged copy')
  } else {
    await stageUi(options, log)
  }

  copyTree(path.join(REPO_ROOT, 'router'), path.join(out, 'router'))
  log('[build] router ← router/')

  const harness = path.join(out, 'harness')
  fs.rmSync(harness, { recursive: true, force: true })
  fs.mkdirSync(path.join(harness, 'scripts'), { recursive: true })
  fs.copyFileSync(path.join(REPO_ROOT, 'scripts', 'run-harness.py'), path.join(harness, 'scripts', 'run-harness.py'))
  copyTree(path.join(REPO_ROOT, 'backend', 'src'), path.join(harness, 'backend', 'src'))
  // `agent_core/runtime.py` and `api/server.py` read `parents[4] / AGENT.md` — keep it four
  // levels above the package so the packaged harness resolves the same file as in a checkout.
  const agentMd = path.join(REPO_ROOT, 'AGENT.md')
  if (fs.existsSync(agentMd)) fs.copyFileSync(agentMd, path.join(harness, 'AGENT.md'))
  log('[build] harness ← scripts/run-harness.py + backend/src + AGENT.md')

  const lockFile = options.lockFile ?? path.join(DESKTOP_DIR, 'runtime.lock.json')
  const lock = fs.existsSync(lockFile) ? readRuntimeLock(lockFile) : null
  if (!lock) {
    throw new Error(`No runtime lock at ${lockFile}. Run \`npm run fetch-runtime\` in desktop/ first.`)
  }
  const runtimeSource = options.runtimeSource ?? path.join(DESKTOP_DIR, 'runtime', options.target ?? lock.target)
  if (!fs.existsSync(runtimeSource)) {
    throw new Error(`The runtime is not fetched: ${runtimeSource}. Run \`npm run fetch-runtime\` in desktop/ first.`)
  }
  // The runtime is copied verbatim (no pruning): it must stay byte-identical to the
  // verified fetch, so the shipped bytes are exactly the ones whose sha256 is pinned.
  copyTree(runtimeSource, path.join(out, 'runtime'), { filter: () => true })
  log(`[build] runtime ← ${path.relative(REPO_ROOT, runtimeSource)} (${lock.target})`)

  const dockerContext = path.join(REPO_ROOT, 'deploy', 'docker')
  if (!fs.existsSync(dockerContext)) throw new Error(`Missing docker build context: ${dockerContext}`)
  copyTree(dockerContext, path.join(out, 'docker-context'))
  log('[build] docker-context ← deploy/docker')

  for (const name of ['ui', 'router', 'harness', 'runtime', 'docker-context']) {
    blocks[name] = await blockSummary(path.join(out, name))
  }

  // The staged runtime must match the lock block by block; a mismatch means the copy or
  // the fetch is stale, and shipping it would put unverified bytes on the user's disk.
  for (const name of ['node', 'python', 'wheels']) {
    const expected = lock.blocks?.[name]?.sha256
    if (!expected) continue
    const actual = (await blockSummary(path.join(out, 'runtime', name))).sha256
    if (actual !== expected) {
      throw new Error(
        `The staged runtime block "${name}" does not match runtime.lock.json\n  lock   ${expected}\n  staged ${actual}\nRe-run \`npm run fetch-runtime\` and build again.`,
      )
    }
  }

  const git = await gitInfo(REPO_ROOT)
  const manifest = {
    schema: 1,
    version: pkg.version ?? '0.0.0',
    productName: pkg.productName ?? 'BoxFox Desktop (Alpha)',
    builtAt: new Date().toISOString(),
    ...git,
    runtimeTarget: lock.target,
    blocks,
    totals: Object.values(blocks).reduce(
      (totals, block) => ({ files: totals.files + block.files, bytes: totals.bytes + block.bytes }),
      { files: 0, bytes: 0 },
    ),
    runtime: {
      lockCreatedAt: lock.createdAt,
      artifacts: (lock.artifacts ?? []).map(({ name, version, sha256 }) => ({ name, version, sha256 })),
      wheels: (lock.wheels ?? []).map(({ name, version, sha256 }) => ({ name, version, sha256 })),
    },
  }
  manifest.digest = manifestDigest(
    Object.entries(blocks).map(([name, block]) => ({ path: name, sha256: block.sha256 })),
  )
  const manifestFile = path.join(out, 'build-manifest.json')
  fs.writeFileSync(manifestFile, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  log(`[build] wrote ${path.relative(REPO_ROOT, manifestFile)}`)
  for (const [name, block] of Object.entries(blocks)) {
    log(`[build] ${name.padEnd(14)} ${String(block.files).padStart(6)} files  ${formatBytes(block.bytes).padStart(10)}  ${block.sha256.slice(0, 12)}…`)
  }
  log(`[build] total ${manifest.totals.files} files, ${formatBytes(manifest.totals.bytes)}`)
  return manifest
}

async function main() {
  const options = parseArgs(process.argv.slice(2))
  if (options.help) {
    process.stdout.write(
      [
        'Usage: node desktop/scripts/build-app.mjs [options]',
        '',
        '  --skip-ui            reuse the already staged build/ui',
        '  --ui-dir <dir>       copy a pre-built frontend instead of building it',
        '  --out <dir>          staging directory (default: desktop/build)',
        '  --target <name>      runtime target (default: the target in runtime.lock.json)',
        '  --lock <file>        runtime lock (default: desktop/runtime.lock.json)',
        '  --runtime-source <d> fetched runtime directory (default: desktop/runtime/<target>)',
        '',
      ].join('\n'),
    )
    return 0
  }
  await buildApp(options, { log: (line) => process.stdout.write(`${line}\n`) })
  return 0
}

const invokedDirectly = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
if (invokedDirectly) {
  main()
    .then((code) => {
      process.exitCode = code
    })
    .catch((error) => {
      process.stderr.write(`build-app failed: ${error.message}\n`)
      process.exitCode = 1
    })
}
