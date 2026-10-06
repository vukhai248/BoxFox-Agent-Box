/**
 * Per-machine profile of BoxFox Desktop (Alpha).
 *
 * The desktop app keeps everything it owns inside ONE directory, separate from the
 * repository checkout and from the development instance:
 *
 *   Windows : %LOCALAPPDATA%\BoxFoxDesktopAlpha
 *   Linux   : ~/.local/share/BoxFoxDesktopAlpha   ($XDG_DATA_HOME wins)
 *
 * Layout (plan §6 PR-2 / D2):
 *
 *   profile/{harness,router,ui}   runtime state of the two bundled services + UI cache
 *   logs/                         stdout/stderr of the supervised services
 *   recovery/                     quarantined files (corrupt machine.json, crash dumps)
 *   updates/                      reserved for auto-update payloads (alpha: unused)
 *   permissions/ audit/           host-mode permission rules and audit trail
 *   machine.json                  ports + per-machine admin token
 *   desktop-settings.json         mode selection and UI preferences
 *   desktop.lock                  single-instance lock (held while the app runs)
 *
 * Four loopback ports (gateway, router, harness, box) are allocated ONCE — on the
 * first run — and reused on every later run so the UI bookmarks/iframe state stay
 * valid. A persisted port that is busy (another app took it) is re-allocated alone
 * and the record is rewritten.
 */

import { randomBytes } from 'node:crypto'
import * as fs from 'node:fs'
import * as net from 'node:net'
import * as os from 'node:os'
import * as path from 'node:path'

export const PROFILE_DIR_NAME = 'BoxFoxDesktopAlpha'
export const MACHINE_FILE_VERSION = 1
export const LOOPBACK = '127.0.0.1'

/** The four ports the desktop app owns. Names are stable — they end up in machine.json. */
export const PORT_NAMES = ['gateway', 'router', 'harness', 'box'] as const
export type PortName = (typeof PORT_NAMES)[number]
export type PortMap = Record<PortName, number>

export interface MachineRecord {
  version: number
  createdAt: string
  updatedAt: string
  ports: PortMap
  /** Per-machine admin token (crypto.randomBytes). Never a shared/committed default. */
  adminToken: string
}

export type ExecutionMode = 'host' | 'docker'

export interface DesktopSettings {
  version: number
  executionMode: ExecutionMode
  updatedAt: string
}

export interface ProfileLayout {
  root: string
  profile: string
  harness: string
  router: string
  ui: string
  logs: string
  recovery: string
  updates: string
  permissions: string
  audit: string
  machineFile: string
  settingsFile: string
  lockFile: string
}

export interface OpenProfileOptions {
  root?: string
  env?: NodeJS.ProcessEnv
  platform?: NodeJS.Platform
  home?: string
  host?: string
  /** Test seam: skip the real port probe (used with an injected allocator). */
  allocatePortsImpl?: (count: number, host: string) => Promise<number[]>
  isPortFreeImpl?: (port: number, host: string) => Promise<boolean>
}

export interface OpenProfileResult {
  layout: ProfileLayout
  machine: MachineRecord
  /** Names whose persisted port was busy/invalid and got a fresh allocation. */
  reallocated: PortName[]
}

/** Root of the profile directory. Windows and Linux differ; both are per-user. */
export function profileRoot(
  env: NodeJS.ProcessEnv = process.env,
  platform: NodeJS.Platform = process.platform,
  home: string = os.homedir(),
): string {
  if (platform === 'win32') {
    const base = (env.LOCALAPPDATA || '').trim() || path.join(home, 'AppData', 'Local')
    return path.join(base, PROFILE_DIR_NAME)
  }
  const base = (env.XDG_DATA_HOME || '').trim() || path.join(home, '.local', 'share')
  return path.join(base, PROFILE_DIR_NAME)
}

/** Create every directory of the layout (idempotent) and return the resolved paths. */
export function ensureLayout(root: string): ProfileLayout {
  const layout: ProfileLayout = {
    root,
    profile: path.join(root, 'profile'),
    harness: path.join(root, 'profile', 'harness'),
    router: path.join(root, 'profile', 'router'),
    ui: path.join(root, 'profile', 'ui'),
    logs: path.join(root, 'logs'),
    recovery: path.join(root, 'recovery'),
    updates: path.join(root, 'updates'),
    permissions: path.join(root, 'permissions'),
    audit: path.join(root, 'audit'),
    machineFile: path.join(root, 'machine.json'),
    settingsFile: path.join(root, 'desktop-settings.json'),
    lockFile: path.join(root, 'desktop.lock'),
  }
  for (const dir of [
    layout.root,
    layout.profile,
    layout.harness,
    layout.router,
    layout.ui,
    layout.logs,
    layout.recovery,
    layout.updates,
    layout.permissions,
    layout.audit,
  ]) {
    fs.mkdirSync(dir, { recursive: true })
  }
  return layout
}

/** One free loopback port: bind :0, read the assigned port, close. */
export function freePort(host: string = LOOPBACK): Promise<number> {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen({ port: 0, host, exclusive: true }, () => {
      const address = server.address()
      if (address === null || typeof address === 'string') {
        server.close(() => reject(new Error('Could not read the allocated port.')))
        return
      }
      const port = address.port
      server.close((error) => (error ? reject(error) : resolve(port)))
    })
  })
}

/** `count` distinct free loopback ports. */
export async function allocatePorts(count: number, host: string = LOOPBACK): Promise<number[]> {
  const ports = new Set<number>()
  while (ports.size < count) {
    ports.add(await freePort(host))
  }
  return [...ports]
}

/** True when the port can be bound on `host` right now. */
export function isPortFree(port: number, host: string = LOOPBACK): Promise<boolean> {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.unref()
    server.on('error', () => resolve(false))
    server.listen({ port, host, exclusive: true }, () => {
      server.close(() => resolve(true))
    })
  })
}

export function newAdminToken(): string {
  return randomBytes(32).toString('hex')
}

function isPortMap(value: unknown): value is PortMap {
  if (value === null || typeof value !== 'object') return false
  const record = value as Record<string, unknown>
  return PORT_NAMES.every((name) => {
    const port = record[name]
    return typeof port === 'number' && Number.isInteger(port) && port >= 1 && port <= 65535
  })
}

function parseMachine(raw: string): MachineRecord | null {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    return null
  }
  if (value === null || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  if (!isPortMap(record.ports)) return null
  if (typeof record.adminToken !== 'string' || record.adminToken.length < 32) return null
  return {
    version: typeof record.version === 'number' ? record.version : MACHINE_FILE_VERSION,
    createdAt: typeof record.createdAt === 'string' ? record.createdAt : new Date().toISOString(),
    updatedAt: typeof record.updatedAt === 'string' ? record.updatedAt : new Date().toISOString(),
    ports: record.ports,
    adminToken: record.adminToken,
  }
}

/**
 * Read machine.json. A corrupt file is quarantined into `recovery/` (never silently
 * overwritten) and `null` is returned so the caller re-creates a fresh record.
 */
export function readMachine(root: string): MachineRecord | null {
  const file = path.join(root, 'machine.json')
  let raw: string
  try {
    raw = fs.readFileSync(file, 'utf8')
  } catch {
    return null
  }
  const parsed = parseMachine(raw)
  if (parsed) return parsed
  try {
    const recovery = path.join(root, 'recovery')
    fs.mkdirSync(recovery, { recursive: true })
    const stamp = new Date().toISOString().replace(/[:.]/g, '-')
    fs.renameSync(file, path.join(recovery, `machine.json.${stamp}.corrupt`))
  } catch {
    // Quarantine is best effort; a fresh record is still written below.
  }
  return null
}

/** Atomic write (tmp + rename) with owner-only permissions. */
export function writeMachine(root: string, machine: MachineRecord): void {
  fs.mkdirSync(root, { recursive: true })
  const file = path.join(root, 'machine.json')
  const tmp = `${file}.tmp`
  fs.writeFileSync(tmp, `${JSON.stringify(machine, null, 2)}\n`, { mode: 0o600 })
  fs.renameSync(tmp, file)
  try {
    fs.chmodSync(file, 0o600)
  } catch {
    // Windows ignores POSIX modes; the file still lives inside the user profile.
  }
}

export const DEFAULT_DESKTOP_SETTINGS: DesktopSettings = {
  version: 1,
  executionMode: 'host',
  updatedAt: '1970-01-01T00:00:00.000Z',
}

export function readDesktopSettings(layout: ProfileLayout): DesktopSettings {
  try {
    const parsed = JSON.parse(fs.readFileSync(layout.settingsFile, 'utf8')) as Partial<DesktopSettings>
    const mode: ExecutionMode = parsed.executionMode === 'docker' ? 'docker' : 'host'
    return {
      version: typeof parsed.version === 'number' ? parsed.version : 1,
      executionMode: mode,
      updatedAt: typeof parsed.updatedAt === 'string' ? parsed.updatedAt : DEFAULT_DESKTOP_SETTINGS.updatedAt,
    }
  } catch {
    return { ...DEFAULT_DESKTOP_SETTINGS }
  }
}

export function writeDesktopSettings(layout: ProfileLayout, patch: Partial<DesktopSettings>): DesktopSettings {
  const next: DesktopSettings = {
    ...readDesktopSettings(layout),
    ...patch,
    version: 1,
    updatedAt: new Date().toISOString(),
  }
  const tmp = `${layout.settingsFile}.tmp`
  fs.writeFileSync(tmp, `${JSON.stringify(next, null, 2)}\n`, { mode: 0o600 })
  fs.renameSync(tmp, layout.settingsFile)
  return next
}

/**
 * Open the profile: create the layout, then reuse the persisted ports and admin
 * token or allocate/creates them on the first run. Ports that are busy get a fresh
 * allocation and the record is rewritten.
 */
export async function openProfile(options: OpenProfileOptions = {}): Promise<OpenProfileResult> {
  const root = options.root ?? profileRoot(options.env, options.platform, options.home)
  const host = options.host ?? LOOPBACK
  const allocate = options.allocatePortsImpl ?? allocatePorts
  const portFree = options.isPortFreeImpl ?? isPortFree
  const layout = ensureLayout(root)
  const now = new Date().toISOString()
  const reallocated: PortName[] = []
  let machine = readMachine(root)
  if (!machine) {
    const ports = await allocate(PORT_NAMES.length, host)
    machine = {
      version: MACHINE_FILE_VERSION,
      createdAt: now,
      updatedAt: now,
      ports: Object.fromEntries(PORT_NAMES.map((name, index) => [name, ports[index]])) as PortMap,
      adminToken: newAdminToken(),
    }
    writeMachine(root, machine)
    return { layout, machine, reallocated }
  }
  const taken = new Set<number>(Object.values(machine.ports))
  for (const name of PORT_NAMES) {
    const port = machine.ports[name]
    if (await portFree(port, host)) continue
    let replacement: number | null = null
    for (let attempt = 0; attempt < 50 && replacement === null; attempt += 1) {
      const candidate = (await allocate(1, host))[0]
      if (!taken.has(candidate)) replacement = candidate
    }
    if (replacement === null) throw new Error(`Could not allocate a free port for "${name}".`)
    taken.add(replacement)
    machine.ports[name] = replacement
    reallocated.push(name)
  }
  if (reallocated.length > 0) {
    machine.updatedAt = now
    writeMachine(root, machine)
  }
  return { layout, machine, reallocated }
}
