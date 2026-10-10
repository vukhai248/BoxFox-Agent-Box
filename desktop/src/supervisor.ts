/**
 * Supervisor of the two bundled services (plan §6 PR-2 / D2).
 *
 * Responsibilities:
 *   - single-instance lock per profile (a second app instance on the same profile
 *     refuses to start instead of fighting over ports and SQLite files);
 *   - spawn the router (bundled Node, `router/src/main.mjs --production`) and the
 *     harness (bundled CPython, `scripts/run-harness.py`) with `BOXFOX_*` env pointing
 *     at the profile and the allocated ports;
 *   - health-poll both, restart with exponential backoff on an unexpected exit;
 *   - stop the whole process tree cleanly (taskkill /T on Windows, process group on
 *     POSIX) so no orphan python.exe/node.exe survives the app.
 *
 * Nothing here assumes the ports of the development instance (3100/3101/3102/8081):
 * every port comes from the profile.
 */

import { spawn, type ChildProcess, type SpawnOptions } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import * as fs from 'node:fs'
import * as path from 'node:path'
import type { MachineRecord, ProfileLayout } from './profile'
import { runCommand, type CommandRunner } from './mode'

export class AlreadyRunningError extends Error {
  readonly code = 'ALREADY_RUNNING'
  constructor(public readonly lockFile: string, public readonly pid: number | null) {
    super(`BoxFox Desktop is already running for this profile (${lockFile}${pid ? `, pid ${pid}` : ''}).`)
    this.name = 'AlreadyRunningError'
  }
}

export interface InstanceLockHandle {
  file: string
  pid: number
  release(): void
}

function processAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code
    // EPERM: the pid exists but belongs to another user — still "in use".
    return code === 'EPERM'
  }
}

/** Upgrade guard for pre-native-lock builds. A recycled PID is not a live BoxFox.
 * Native-lock records do not need a subprocess probe on subsequent starts.
 */
export async function checkLegacyInstance(lockFile: string, options: {
  platform?: NodeJS.Platform; executable?: string; runner?: CommandRunner; alive?: (pid: number) => boolean
} = {}): Promise<void> {
  if ((options.platform ?? process.platform) !== 'win32') return
  let record: { pid?: number; token?: string; startedAt?: string }
  try { record = JSON.parse(fs.readFileSync(lockFile, 'utf8')) } catch { return }
  if (record.token || !record.pid || !(options.alive ?? processAlive)(record.pid)) return
  const pid = record.pid
  if (!Number.isInteger(pid) || pid <= 0) return
  const powershell = path.join(process.env.SystemRoot ?? 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
  const result = await (options.runner ?? runCommand)(powershell, ['-NoProfile', '-NonInteractive', '-Command',
    `$targetProcess = Get-Process -Id ${pid} -ErrorAction SilentlyContinue; if ($targetProcess) { @{ path=$targetProcess.Path; startedAt=$targetProcess.StartTime.ToUniversalTime().ToString('o') } | ConvertTo-Json -Compress }`,
  ], { timeoutMs: 3000 })
  if (result.code !== 0) throw new Error('Could not verify the legacy BoxFox instance. Close the older app and try again.')
  if (!result.stdout.trim()) return // owner exited during the probe
  const owner = JSON.parse(result.stdout) as { path?: string; startedAt?: string }
  const name = path.win32.basename(owner.path ?? '').toLowerCase()
  const expected = path.win32.basename(options.executable ?? process.execPath).toLowerCase()
  if (name !== expected && name !== 'boxfox desktop (alpha).exe') return
  const startedAt = Date.parse(owner.startedAt ?? '')
  const recordedAt = Date.parse(record.startedAt ?? '')
  if (Number.isFinite(startedAt) && Number.isFinite(recordedAt) && startedAt > recordedAt + 1000) return
  throw new AlreadyRunningError(lockFile, pid)
}

/**
 * Take the single-instance lock. The lock file holds the owner pid; a stale file
 * (owner gone, e.g. a crash) is replaced. `release()` is idempotent.
 */
export function acquireInstanceLock(
  lockFile: string,
  pid: number = process.pid,
  options: { nativeLockHeld?: boolean } = {},
): InstanceLockHandle {
  fs.mkdirSync(path.dirname(lockFile), { recursive: true })
  // In Electron the kernel-backed single-instance lock is authoritative. The file
  // is diagnostic only: Windows can recycle its PID after a crash/reboot.
  if (options.nativeLockHeld) fs.rmSync(lockFile, { force: true })
  const token = randomUUID()
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const fd = fs.openSync(lockFile, 'wx')
      try {
        fs.writeSync(fd, `${JSON.stringify({ app: 'boxfox-desktop', pid, token, startedAt: new Date().toISOString() })}\n`)
      } finally {
        fs.closeSync(fd)
      }
      let released = false
      return {
        file: lockFile,
        pid,
        release: () => {
          if (released) return
          released = true
          try {
            const record = JSON.parse(fs.readFileSync(lockFile, 'utf8')) as { token?: unknown }
            if (record.token === token) fs.rmSync(lockFile, { force: true })
          } catch {
            // The lock is advisory; failing to remove it only delays the next start.
          }
        },
      }
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
      let owner: number | null = null
      try {
        const parsed = JSON.parse(fs.readFileSync(lockFile, 'utf8')) as { pid?: unknown }
        if (typeof parsed.pid === 'number') owner = parsed.pid
      } catch {
        owner = null
      }
      // A live owner always blocks — including this same pid, which would mean the lock
      // was acquired twice in one process (a bug, not a legitimate re-entry).
      if (owner !== null && processAlive(owner)) throw new AlreadyRunningError(lockFile, owner)
      try {
        fs.rmSync(lockFile, { force: true })
      } catch {
        // Retry below; the next open('wx') will surface the real error.
      }
    }
  }
  throw new AlreadyRunningError(lockFile, null)
}

export type ServiceName = 'router' | 'harness'

export interface ServiceSpec {
  name: ServiceName
  command: string
  args: string[]
  cwd: string
  env: NodeJS.ProcessEnv
  healthUrl: string
}

export interface ServiceState {
  pid: number | null
  healthy: boolean
  restarts: number
  lastExit: { code: number | null; signal: NodeJS.Signals | null; at: string } | null
  lastError: string | null
}

export interface SupervisorStatus {
  running: boolean
  services: Record<ServiceName, ServiceState>
}

export interface BuildSpecsInput {
  layout: ProfileLayout
  machine: MachineRecord
  /** Directory holding router/, harness/, ui/, runtime/ (app resources or desktop/). */
  resourcesDir: string
  /** Root of the bundled runtime; defaults to `<resourcesDir>/runtime`. */
  runtimeDir?: string
  /** Override the bundled executables (Linux smoke test / developer runs). */
  nodeBinary?: string
  pythonBinary?: string
  mode?: 'host' | 'docker'
  platform?: NodeJS.Platform
  env?: NodeJS.ProcessEnv
}

export function bundledNodeBinary(runtimeDir: string, platform: NodeJS.Platform = process.platform): string {
  return platform === 'win32'
    ? path.join(runtimeDir, 'node', 'node.exe')
    : path.join(runtimeDir, 'node', 'bin', 'node')
}

export function bundledPythonBinary(runtimeDir: string, platform: NodeJS.Platform = process.platform): string {
  if (platform === 'win32') return path.join(runtimeDir, 'python', 'python.exe')
  for (const candidate of [path.join(runtimeDir, 'python', 'bin', 'python3'), path.join(runtimeDir, 'python', 'python3')]) {
    if (fs.existsSync(candidate)) return candidate
  }
  return path.join(runtimeDir, 'python', 'bin', 'python3')
}

/**
 * Environment shared by both services. It is deliberately explicit: the app must
 * never inherit `BOXFOX_*` from whatever shell launched it.
 */
export function serviceEnv(
  base: NodeJS.ProcessEnv,
  layout: ProfileLayout,
  machine: MachineRecord,
  mode: 'host' | 'docker',
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...base }
  for (const key of Object.keys(env)) {
    if (key.startsWith('BOXFOX_')) delete env[key]
  }
  env.BOXFOX_DESKTOP_PROFILE = layout.root
  env.BOXFOX_API_KEY = machine.adminToken
  env.BOXFOX_EXECUTION_MODE = mode
  env.BOXFOX_UI_ORIGINS = `http://127.0.0.1:${machine.ports.gateway},http://localhost:${machine.ports.gateway}`
  env.BOXFOX_ROUTER_URL = `http://127.0.0.1:${machine.ports.router}`
  env.BOXFOX_ROUTER_SEARCH_URL = `${env.BOXFOX_ROUTER_URL}/api/router/search/resolve`
  env.BOXFOX_BOX_URL = `http://127.0.0.1:${machine.ports.box}`
  return env
}

export function buildServiceSpecs(input: BuildSpecsInput): { router: ServiceSpec; harness: ServiceSpec } {
  const platform = input.platform ?? process.platform
  const runtimeDir = input.runtimeDir ?? path.join(input.resourcesDir, 'runtime')
  const mode = input.mode ?? 'host'
  const baseEnv = input.env ?? process.env
  const env = serviceEnv(baseEnv, input.layout, input.machine, mode)
  const node = input.nodeBinary ?? bundledNodeBinary(runtimeDir, platform)
  const python = input.pythonBinary ?? bundledPythonBinary(runtimeDir, platform)
  const routerDir = path.join(input.resourcesDir, 'router')
  const harnessDir = path.join(input.resourcesDir, 'harness')
  return {
    router: {
      name: 'router',
      command: node,
      args: [path.join(routerDir, 'src', 'main.mjs'), '--production'],
      cwd: routerDir,
      env: {
        ...env,
        BOXFOX_ROUTER_PORT: String(input.machine.ports.router),
        BOXFOX_ROUTER_DATA_DIR: input.layout.router,
      },
      healthUrl: `http://127.0.0.1:${input.machine.ports.router}/api/router/health`,
    },
    harness: {
      name: 'harness',
      command: python,
      args: [path.join(harnessDir, 'scripts', 'run-harness.py')],
      cwd: harnessDir,
      env: {
        ...env,
        BOXFOX_HARNESS_PORT: String(input.machine.ports.harness),
        BOXFOX_AGENT_DATA_DIR: input.layout.harness,
        PYTHONPATH: path.join(harnessDir, 'backend', 'src'),
        PYTHONUNBUFFERED: '1',
        PYTHONUTF8: '1',
        PYTHONDONTWRITEBYTECODE: '1',
      },
      healthUrl: `http://127.0.0.1:${input.machine.ports.harness}/api/agent/health?readiness=1`,
    },
  }
}

export interface HealthOptions {
  timeoutMs?: number
  intervalMs?: number
  fetchImpl?: typeof fetch
}

/** Poll an HTTP health endpoint until it answers 2xx. Never throws. */
export async function waitForHttp(url: string, options: HealthOptions = {}): Promise<boolean> {
  const timeoutMs = options.timeoutMs ?? 60_000
  const intervalMs = options.intervalMs ?? 250
  const fetchImpl = options.fetchImpl ?? fetch
  const deadline = Date.now() + timeoutMs
  for (;;) {
    try {
      const response = await fetchImpl(url, { signal: AbortSignal.timeout(Math.max(1000, intervalMs * 4)) })
      if (response.ok) {
        await response.arrayBuffer().catch(() => undefined)
        return true
      }
    } catch {
      // Not up yet.
    }
    if (Date.now() >= deadline) return false
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

export function backoffDelay(attempt: number, baseDelayMs = 1000, maxDelayMs = 30_000): number {
  const exponential = baseDelayMs * 2 ** Math.max(0, attempt)
  return Math.min(exponential, maxDelayMs)
}

export interface SupervisorOptions {
  layout: ProfileLayout
  machine: MachineRecord
  resourcesDir: string
  runtimeDir?: string
  mode?: 'host' | 'docker'
  platform?: NodeJS.Platform
  nodeBinary?: string
  pythonBinary?: string
  /** Where service stdout/stderr go; defaults to `<layout>/logs`. */
  logsDir?: string
  /** Test seam: use these specs instead of the bundled layout. */
  specs?: { router: ServiceSpec; harness: ServiceSpec }
  spawnImpl?: typeof spawn
  fetchImpl?: typeof fetch
  log?: (line: string) => void
  maxRestarts?: number
  baseDelayMs?: number
  maxDelayMs?: number
  readyTimeoutMs?: number
  /** Re-check interval for the health of a running service. 0 disables the watchdog. */
  watchdogIntervalMs?: number
}

interface ChildRecord {
  name: ServiceName
  spec: ServiceSpec
  child: ChildProcess | null
  state: ServiceState
  restartTimer: NodeJS.Timeout | null
  expectedExit: boolean
}

/** Stop a child process and everything it spawned. */
export async function stopProcessTree(child: ChildProcess, graceMs = 5000): Promise<void> {
  const pid = child.pid
  if (pid === undefined || child.exitCode !== null || child.signalCode !== null) return
  const exited = new Promise<void>((resolve) => child.once('exit', () => resolve()))
  const force = () => {
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
      } else {
        process.kill(-pid, 'SIGKILL')
      }
    } catch {
      try {
        child.kill('SIGKILL')
      } catch {
        // Already gone.
      }
    }
  }
  try {
    if (process.platform === 'win32') {
      spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { stdio: 'ignore', windowsHide: true })
    } else {
      process.kill(-pid, 'SIGTERM')
    }
  } catch {
    try {
      child.kill('SIGTERM')
    } catch {
      // Already gone.
    }
  }
  const timer = setTimeout(force, graceMs)
  await exited
  clearTimeout(timer)
}

export class Supervisor {
  private readonly records: Record<ServiceName, ChildRecord>
  private readonly log: (line: string) => void
  private readonly spawnImpl: typeof spawn
  private readonly fetchImpl: typeof fetch
  private readonly maxRestarts: number
  private readonly baseDelayMs: number
  private readonly maxDelayMs: number
  private readonly readyTimeoutMs: number
  private readonly watchdogIntervalMs: number
  private readonly logsDir: string
  private watchdog: NodeJS.Timeout | null = null
  private stopping = false
  private started = false

  constructor(options: SupervisorOptions) {
    const specs = options.specs ?? buildServiceSpecs(options)
    const makeRecord = (spec: ServiceSpec): ChildRecord => ({
      name: spec.name,
      spec,
      child: null,
      state: { pid: null, healthy: false, restarts: 0, lastExit: null, lastError: null },
      restartTimer: null,
      expectedExit: false,
    })
    this.records = { router: makeRecord(specs.router), harness: makeRecord(specs.harness) }
    this.log = options.log ?? (() => undefined)
    this.spawnImpl = options.spawnImpl ?? spawn
    this.fetchImpl = options.fetchImpl ?? fetch
    this.maxRestarts = options.maxRestarts ?? 3
    this.baseDelayMs = options.baseDelayMs ?? 1000
    this.maxDelayMs = options.maxDelayMs ?? 30_000
    this.readyTimeoutMs = options.readyTimeoutMs ?? 90_000
    this.watchdogIntervalMs = options.watchdogIntervalMs ?? 0
    this.logsDir = options.logsDir ?? options.layout.logs
    fs.mkdirSync(this.logsDir, { recursive: true })
  }

  status(): SupervisorStatus {
    return {
      running: this.started && !this.stopping,
      services: {
        router: { ...this.records.router.state },
        harness: { ...this.records.harness.state },
      },
    }
  }

  private startService(name: ServiceName): void {
    const record = this.records[name]
    if (this.stopping) return
    const stdout = fs.openSync(path.join(this.logsDir, `${name}.stdout.log`), 'a')
    const stderr = fs.openSync(path.join(this.logsDir, `${name}.stderr.log`), 'a')
    const spawnOptions: SpawnOptions = {
      cwd: record.spec.cwd,
      env: record.spec.env,
      stdio: ['ignore', stdout, stderr],
      windowsHide: true,
      detached: process.platform !== 'win32',
    }
    this.log(`[supervisor] starting ${name}: ${record.spec.command} ${record.spec.args.join(' ')}`)
    let child: ChildProcess
    try {
      child = this.spawnImpl(record.spec.command, record.spec.args, spawnOptions)
    } catch (error) {
      this.log(`[supervisor] ${name} failed to spawn: ${(error as Error).message}`)
      record.state.lastError = (error as Error).message
      this.scheduleRestart(name)
      return
    }
    record.child = child
    record.expectedExit = false
    record.state.pid = child.pid ?? null
    record.state.healthy = false
    record.state.lastError = null
    child.on('error', (error) => {
      this.log(`[supervisor] ${name} error: ${error.message}`)
      record.state.lastError = error.message
    })
    child.on('exit', (code, signal) => {
      this.log(`[supervisor] ${name} exited (code=${code}, signal=${signal})`)
      record.state.healthy = false
      record.state.pid = null
      record.state.lastExit = { code, signal, at: new Date().toISOString() }
      if (!record.expectedExit && !this.stopping) this.scheduleRestart(name)
    })
  }

  private scheduleRestart(name: ServiceName): void {
    const record = this.records[name]
    if (this.stopping || record.restartTimer) return
    if (record.state.restarts >= this.maxRestarts) {
      record.state.lastError = `${name} exceeded ${this.maxRestarts} restarts; giving up.`
      this.log(`[supervisor] ${record.state.lastError}`)
      return
    }
    const delay = backoffDelay(record.state.restarts, this.baseDelayMs, this.maxDelayMs)
    record.state.restarts += 1
    this.log(`[supervisor] restarting ${name} in ${delay} ms (attempt ${record.state.restarts}/${this.maxRestarts})`)
    record.restartTimer = setTimeout(() => {
      record.restartTimer = null
      this.startService(name)
      void this.checkService(name)
    }, delay)
    record.restartTimer.unref?.()
  }

  private async checkService(name: ServiceName): Promise<boolean> {
    const record = this.records[name]
    if (!record.child) return false
    const healthy = await waitForHttp(record.spec.healthUrl, {
      timeoutMs: 500,
      intervalMs: 200,
      fetchImpl: this.fetchImpl,
    })
    record.state.healthy = healthy
    return healthy
  }

  /** Spawn both services and wait until both answer their health endpoint. */
  async start(): Promise<SupervisorStatus> {
    if (this.started) return this.status()
    this.stopping = false
    this.started = true
    this.startService('router')
    this.startService('harness')
    const names: ServiceName[] = ['router', 'harness']
    const startedAt = performance.now()
    await Promise.all(
      names.map(async (name) => {
        const ok = await waitForHttp(this.records[name].spec.healthUrl, {
          timeoutMs: this.readyTimeoutMs,
          intervalMs: 300,
          fetchImpl: this.fetchImpl,
        })
        this.records[name].state.healthy = ok
        if (ok) this.log(`[supervisor] ${name} healthy after ${Math.round(performance.now() - startedAt)}ms`)
        if (!ok) this.log(`[supervisor] ${name} did not become healthy in ${this.readyTimeoutMs} ms`)
      }),
    )
    if (this.watchdogIntervalMs > 0) {
      this.watchdog = setInterval(() => {
        void Promise.all(names.map((name) => this.checkService(name)))
      }, this.watchdogIntervalMs)
      this.watchdog.unref?.()
    }
    return this.status()
  }

  async stop(): Promise<void> {
    this.stopping = true
    if (this.watchdog) {
      clearInterval(this.watchdog)
      this.watchdog = null
    }
    const children: ChildProcess[] = []
    for (const name of ['router', 'harness'] as ServiceName[]) {
      const record = this.records[name]
      if (record.restartTimer) {
        clearTimeout(record.restartTimer)
        record.restartTimer = null
      }
      if (record.child) {
        record.expectedExit = true
        children.push(record.child)
      }
    }
    await Promise.all(children.map((child) => stopProcessTree(child)))
    for (const name of ['router', 'harness'] as ServiceName[]) {
      const record = this.records[name]
      record.child = null
      record.state.pid = null
      record.state.healthy = false
    }
    this.started = false
  }
}
