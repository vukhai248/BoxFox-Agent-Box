/**
 * Diagnostics for BoxFox Desktop (Alpha) — the data behind the tray/diagnostics panel
 * (D3) and behind `GET /api/desktop/health`. Read-only: it never starts or stops
 * anything.
 *
 * Two layers:
 *   - `collectDiagnostics` / `formatDiagnostics` — the in-memory summary used by the
 *     gateway and by the window title bar;
 *   - `writeDiagnosticsArchive` — the support bundle: ONE zip with `manifest.json`,
 *     `health.json`, `summary.txt` and the last 200 lines of every file in `logs/`,
 *     plus the runtime file inventory (path + size + sha256).
 *
 * The bundle must never carry a secret. Every value written passes through the
 * redaction below, keyed on the words `key`, `token`, `secret`, `authorization` and
 * `password` (case-insensitive).
 */

import { createHash } from 'node:crypto'
import * as fs from 'node:fs'
import * as path from 'node:path'
import type { DockerProbe } from './mode'
import type { ExecutionMode, PortMap, ProfileLayout } from './profile'
import type { SupervisorStatus } from './supervisor'
import { writeZipFile, type ZipEntryInput } from './zip'

export interface DiagnosticsInput {
  version: string
  commit: string | null
  mode: ExecutionMode
  modeReason: string
  profileRoot: string
  ports: PortMap
  node: string
  python: string
  services: SupervisorStatus
  docker: DockerProbe | null
  /** `execution` block of the harness health payload when the harness exposes one. */
  harnessExecution?: unknown
}

export interface Diagnostics {
  app: string
  version: string
  commit: string | null
  mode: ExecutionMode
  modeReason: string
  profileRoot: string
  ports: PortMap
  runtime: { node: string; python: string }
  services: SupervisorStatus
  docker: DockerProbe | null
  cua: { reported: boolean; detail: unknown }
}

export function collectDiagnostics(input: DiagnosticsInput): Diagnostics {
  const reported = input.harnessExecution !== undefined && input.harnessExecution !== null
  return {
    app: 'BoxFox Desktop (Alpha)',
    version: input.version,
    commit: input.commit,
    mode: input.mode,
    modeReason: input.modeReason,
    profileRoot: input.profileRoot,
    ports: input.ports,
    runtime: { node: input.node, python: input.python },
    services: input.services,
    docker: input.docker,
    cua: reported
      ? { reported: true, detail: input.harnessExecution }
      : { reported: false, detail: 'The harness did not report an execution block (host-mode CUA lands with PR-1).' },
  }
}

/** Plain-text rendering used in logs and in the "copy diagnostics" button (D3). */
export function formatDiagnostics(diagnostics: Diagnostics): string {
  const lines = [
    `${diagnostics.app} ${diagnostics.version} (commit ${diagnostics.commit ?? 'unknown'})`,
    `mode      : ${diagnostics.mode} — ${diagnostics.modeReason}`,
    `profile   : ${diagnostics.profileRoot}`,
    `ports     : gateway=${diagnostics.ports.gateway} router=${diagnostics.ports.router} harness=${diagnostics.ports.harness} box=${diagnostics.ports.box}`,
    `runtime   : node=${diagnostics.runtime.node} python=${diagnostics.runtime.python}`,
    `router    : pid=${diagnostics.services.services.router.pid ?? '-'} healthy=${diagnostics.services.services.router.healthy} restarts=${diagnostics.services.services.router.restarts}`,
    `harness   : pid=${diagnostics.services.services.harness.pid ?? '-'} healthy=${diagnostics.services.services.harness.healthy} restarts=${diagnostics.services.services.harness.restarts}`,
  ]
  if (diagnostics.docker) {
    lines.push(
      `docker    : cli=${diagnostics.docker.cli} engine=${diagnostics.docker.engine} image=${diagnostics.docker.image} (${diagnostics.docker.imageName})`,
    )
  }
  lines.push(`cua       : ${diagnostics.cua.reported ? 'reported by harness' : 'not reported'}`)
  return lines.join('\n')
}

// ---------------------------------------------------------------------------
// Redaction
// ---------------------------------------------------------------------------

export const SECRET_KEYWORDS = ['key', 'token', 'secret', 'authorization', 'password'] as const

export const REDACTED = '[REDACTED]'

/** True when a field name looks like it carries a credential. */
export function isSecretName(name: string): boolean {
  const lower = name.toLowerCase()
  return SECRET_KEYWORDS.some((keyword) => lower.includes(keyword))
}

/** Deep copy with every credential-looking key replaced by `[REDACTED]`. */
export function redactValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => redactValue(item))
  if (value === null || typeof value !== 'object') return value
  const output: Record<string, unknown> = {}
  for (const [name, item] of Object.entries(value as Record<string, unknown>)) {
    output[name] = isSecretName(name) ? REDACTED : redactValue(item)
  }
  return output
}

/** `apiKey=abc` / `"token": "abc"` / `Authorization: Bearer abc` inside free text. */
const SECRET_ASSIGNMENT = /([A-Za-z0-9_.[\]-]*(?:key|token|secret|authorization|password)[A-Za-z0-9_.[\]-]*)(\s*["']?\s*[:=]\s*["']?)([^\s"',;]+)/gi
/** `Authorization: Bearer <token>` — the credential runs to the end of the line. */
const AUTH_SCHEME_ASSIGNMENT = /([A-Za-z0-9_.[\]-]*(?:key|token|secret|authorization|password)[A-Za-z0-9_.[\]-]*)(\s*["']?\s*[:=]\s*["']?(?:bearer|basic|digest|apikey)\s+)[^\n]*/gi
const AUTH_SCHEME_WORD = /^(?:bearer|basic|digest|apikey)$/i
const BEARER_TOKEN = /(\b(?:bearer|basic|digest)\s+)[A-Za-z0-9._~+/=-]+/gi

/** Redact credential-looking assignments inside one free-text line (a log line). */
export function redactLine(line: string): string {
  return line
    .replace(AUTH_SCHEME_ASSIGNMENT, `$1$2${REDACTED}`)
    .replace(SECRET_ASSIGNMENT, (match, name: string, separator: string, value: string) =>
      AUTH_SCHEME_WORD.test(value) ? match : `${name}${separator}${REDACTED}`,
    )
    .replace(BEARER_TOKEN, `$1${REDACTED}`)
}

export function redactText(text: string): string {
  return text.split('\n').map((line) => redactLine(line)).join('\n')
}

// ---------------------------------------------------------------------------
// Runtime inventory
// ---------------------------------------------------------------------------

export interface RuntimeFileInfo {
  /** POSIX-style path relative to the runtime root. */
  path: string
  bytes: number
  sha256: string
}

export function sha256File(file: string): string {
  return createHash('sha256').update(fs.readFileSync(file)).digest('hex')
}

/** Every file under `root`, sorted by path, with size and sha256. */
export function listRuntimeFiles(root: string): RuntimeFileInfo[] {
  const files: RuntimeFileInfo[] = []
  const walk = (dir: string, prefix: string): void => {
    let entries: fs.Dirent[]
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const absolute = path.join(dir, entry.name)
      const relative = prefix === '' ? entry.name : `${prefix}/${entry.name}`
      if (entry.isDirectory()) walk(absolute, relative)
      else if (entry.isFile()) {
        try {
          files.push({ path: relative, bytes: fs.statSync(absolute).size, sha256: sha256File(absolute) })
        } catch {
          // A file that vanished mid-walk (or is locked) must not fail the bundle.
        }
      }
    }
  }
  walk(root, '')
  return files
}

// ---------------------------------------------------------------------------
// Harness health
// ---------------------------------------------------------------------------

export interface HealthSnapshot {
  ok: boolean
  status: number | null
  body: unknown
  error: string | null
}

export interface HealthRequest {
  baseUrl: string
  origin?: string
  fetchImpl?: typeof fetch
  timeoutMs?: number
}

/** `GET /api/agent/health`, never throws. */
export async function fetchHarnessHealth(input: HealthRequest): Promise<HealthSnapshot> {
  const fetchImpl = input.fetchImpl ?? fetch
  const url = `${input.baseUrl.replace(/\/+$/, '')}/api/agent/health`
  const headers: Record<string, string> = {}
  if (input.origin) headers.origin = input.origin
  try {
    const response = await fetchImpl(url, { headers, signal: AbortSignal.timeout(input.timeoutMs ?? 5_000) })
    const text = await response.text().catch(() => '')
    let body: unknown = text
    if (text.trim() !== '') {
      try {
        body = JSON.parse(text)
      } catch {
        body = text
      }
    }
    return { ok: response.ok, status: response.status, body, error: response.ok ? null : `HTTP ${response.status}` }
  } catch (error) {
    return { ok: false, status: null, body: null, error: (error as Error).message }
  }
}

// ---------------------------------------------------------------------------
// The support bundle
// ---------------------------------------------------------------------------

export const LOG_TAIL_LINES = 200
const LOG_TAIL_MAX_BYTES = 256 * 1024

export interface RuntimeBundleInfo {
  target: string | null
  artifacts: Array<{ name: string; version: string }>
}

export interface DiagnosticsArchiveInput {
  layout: ProfileLayout
  version: string
  commit: string | null
  mode: ExecutionMode
  modeReason: string
  ports: PortMap
  runtime: { node: string; python: string }
  /** Where the two services keep their data. */
  dataPaths: { harness: string; router: string; ui: string }
  runtimeDir: string
  runtimeBundle?: RuntimeBundleInfo | null
  health: HealthSnapshot
  services: SupervisorStatus
  docker: DockerProbe | null
  now?: Date
}

export interface DiagnosticsArchiveResult {
  zipPath: string
  entries: string[]
  bytes: number
  manifest: Record<string, unknown>
}

export function diagnosticsDir(profileRoot: string): string {
  return path.join(profileRoot, 'diagnostics')
}

/** `build-manifest.json` → the "runtime bundle version" shown in the archive. */
export function runtimeBundleFromManifest(manifest: Record<string, unknown> | null): RuntimeBundleInfo | null {
  if (manifest === null) return null
  const target = typeof manifest.runtimeTarget === 'string' ? manifest.runtimeTarget : null
  const runtime = manifest.runtime
  const rawArtifacts = runtime !== null && typeof runtime === 'object' ? (runtime as Record<string, unknown>).artifacts : null
  const artifacts: Array<{ name: string; version: string }> = []
  if (Array.isArray(rawArtifacts)) {
    for (const item of rawArtifacts) {
      if (item === null || typeof item !== 'object') continue
      const record = item as Record<string, unknown>
      artifacts.push({
        name: typeof record.name === 'string' ? record.name : 'unknown',
        version: typeof record.version === 'string' ? record.version : 'unknown',
      })
    }
  }
  return { target, artifacts }
}

/** Last `maxLines` lines of a text file, reading at most the tail of a huge log. */
export function readLogTail(file: string, maxLines = LOG_TAIL_LINES): string {
  let text: string
  try {
    const stat = fs.statSync(file)
    const start = Math.max(0, stat.size - LOG_TAIL_MAX_BYTES)
    const length = stat.size - start
    const handle = fs.openSync(file, 'r')
    try {
      const buffer = Buffer.alloc(length)
      fs.readSync(handle, buffer, 0, length, start)
      text = buffer.toString('utf8')
    } finally {
      fs.closeSync(handle)
    }
  } catch {
    return ''
  }
  const lines = text.split(/\r?\n/)
  if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop()
  return lines.slice(-maxLines).join('\n')
}

function logFiles(logsDir: string): string[] {
  const files: string[] = []
  const walk = (dir: string, prefix: string): void => {
    let entries: fs.Dirent[]
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true })
    } catch {
      return
    }
    for (const entry of entries.sort((a, b) => a.name.localeCompare(b.name))) {
      const absolute = path.join(dir, entry.name)
      const relative = prefix === '' ? entry.name : `${prefix}/${entry.name}`
      if (entry.isDirectory()) walk(absolute, relative)
      else if (entry.isFile()) files.push(relative)
    }
  }
  walk(logsDir, '')
  return files
}

function stamp(date: Date): string {
  return date.toISOString().replace(/[:.]/g, '-')
}

/**
 * Write the support bundle. Returns the zip path plus the manifest it contains, so the
 * caller can log a one-liner without re-reading the archive.
 */
export function writeDiagnosticsArchive(input: DiagnosticsArchiveInput): DiagnosticsArchiveResult {
  const now = input.now ?? new Date()
  const runtimeFiles = listRuntimeFiles(input.runtimeDir)
  const manifest = redactValue({
    app: 'BoxFox Desktop (Alpha)',
    schema: 1,
    version: input.version,
    commit: input.commit,
    generatedAt: now.toISOString(),
    mode: input.mode,
    modeReason: input.modeReason,
    ports: input.ports,
    paths: {
      profileRoot: input.layout.root,
      data: input.dataPaths,
      logs: input.layout.logs,
      runtime: input.runtimeDir,
    },
    runtimeBundle: {
      target: input.runtimeBundle?.target ?? null,
      artifacts: input.runtimeBundle?.artifacts ?? [],
      files: runtimeFiles,
    },
    health: { ok: input.health.ok, status: input.health.status, error: input.health.error },
    services: input.services,
    docker: input.docker,
  }) as Record<string, unknown>

  const summary = redactText(
    formatDiagnostics(
      collectDiagnostics({
        version: input.version,
        commit: input.commit,
        mode: input.mode,
        modeReason: input.modeReason,
        profileRoot: input.layout.root,
        ports: input.ports,
        node: input.runtime.node,
        python: input.runtime.python,
        services: input.services,
        docker: input.docker,
        harnessExecution: (input.health.body as { execution?: unknown } | null)?.execution,
      }),
    ),
  )

  const entries: ZipEntryInput[] = [
    { name: 'manifest.json', data: `${JSON.stringify(manifest, null, 2)}\n` },
    { name: 'health.json', data: `${JSON.stringify(redactValue(input.health.body) ?? null, null, 2)}\n` },
    { name: 'summary.txt', data: `${summary}\n` },
  ]
  for (const relative of logFiles(input.layout.logs)) {
    const tail = redactText(readLogTail(path.join(input.layout.logs, relative)))
    entries.push({ name: `logs/${relative}`, data: `${tail}\n` })
  }

  const zipPath = path.join(diagnosticsDir(input.layout.root), `boxfox-diagnostics-${stamp(now)}.zip`)
  writeZipFile(zipPath, entries, { date: now })
  return { zipPath, entries: entries.map((entry) => entry.name), bytes: fs.statSync(zipPath).size, manifest }
}
