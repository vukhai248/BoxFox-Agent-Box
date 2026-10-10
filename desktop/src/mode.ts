/**
 * Execution-mode selection of BoxFox Desktop (Alpha) — plan §6 PR-2 / D2.
 *
 * Two modes:
 *   host   — the harness runs directly on this machine (default on first run, no Docker);
 *   docker — the agent runs inside the bundled sandbox container.
 *
 * Docker mode needs three facts, checked in this order: the Docker CLI exists, the
 * engine answers, and the sandbox image is present. On the alpha channel there is no
 * registry, so a missing image is built ONCE from the build context shipped with the
 * app (`build/docker-context`, a copy of `deploy/docker`) with streamed progress and
 * one retry.
 *
 * The container identity is per-profile: the compose override below gives the
 * container and the workspace volume a name derived from the profile, publishes the
 * box surface on the profile's box port, and hands the container the machine's admin
 * token and the gateway origin (never the committed development defaults).
 */

import { spawn } from 'node:child_process'
import * as fs from 'node:fs'
import * as path from 'node:path'
import type { ExecutionMode, PortMap } from './profile'

export const SANDBOX_IMAGE = 'agentbox-sandbox:latest'

export interface CommandResult {
  code: number | null
  stdout: string
  stderr: string
  timedOut: boolean
}

export interface RunOptions {
  timeoutMs?: number
  onLine?: (line: string, stream: 'stdout' | 'stderr') => void
}

export type CommandRunner = (command: string, args: string[], options?: RunOptions) => Promise<CommandResult>

/** Real command runner: never throws, always resolves with the outcome. */
export function runCommand(command: string, args: string[], options: RunOptions = {}): Promise<CommandResult> {
  const timeoutMs = options.timeoutMs ?? 120_000
  return new Promise((resolve) => {
    let stdout = ''
    let stderr = ''
    let timedOut = false
    let settled = false
    const child = spawn(command, args, { windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    const timer = setTimeout(() => {
      timedOut = true
      child.kill('SIGKILL')
    }, timeoutMs)
    const feed = (chunk: Buffer, stream: 'stdout' | 'stderr') => {
      const text = chunk.toString('utf8')
      if (stream === 'stdout') stdout += text
      else stderr += text
      if (options.onLine) {
        for (const line of text.split(/\r?\n/)) {
          if (line.trim() !== '') options.onLine(line, stream)
        }
      }
    }
    child.stdout?.on('data', (chunk: Buffer) => feed(chunk, 'stdout'))
    child.stderr?.on('data', (chunk: Buffer) => feed(chunk, 'stderr'))
    const finish = (code: number | null) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve({ code, stdout, stderr, timedOut })
    }
    child.on('error', (error) => {
      stderr += `${error.message}\n`
      finish(null)
    })
    child.on('close', (code) => finish(code))
  })
}

export interface DockerProbe {
  cli: boolean
  engine: boolean
  engineVersion: string | null
  image: boolean
  imageName: string
  /** Human-readable explanation of the first failing check. */
  detail: string
}

export interface ProbeDockerOptions {
  runner?: CommandRunner
  image?: string
  dockerPath?: string
  timeoutMs?: number
}

export async function probeDocker(options: ProbeDockerOptions = {}): Promise<DockerProbe> {
  const runner = options.runner ?? runCommand
  const image = options.image ?? SANDBOX_IMAGE
  const docker = options.dockerPath ?? 'docker'
  const timeoutMs = options.timeoutMs ?? 10_000
  const version = await runner(docker, ['--version'], { timeoutMs })
  if (version.code !== 0) {
    return { cli: false, engine: false, engineVersion: null, image: false, imageName: image, detail: 'Docker CLI not found.' }
  }
  const info = await runner(docker, ['info', '--format', '{{.ServerVersion}}'], { timeoutMs })
  if (info.code !== 0) {
    return {
      cli: true,
      engine: false,
      engineVersion: null,
      image: false,
      imageName: image,
      detail: 'Docker engine is not responding (is Docker Desktop running?).',
    }
  }
  const engineVersion = info.stdout.trim() || null
  const inspect = await runner(docker, ['image', 'inspect', image, '--format', '{{.Id}}'], { timeoutMs })
  if (inspect.code !== 0) {
    return { cli: true, engine: true, engineVersion, image: false, imageName: image, detail: `Sandbox image ${image} is missing.` }
  }
  return { cli: true, engine: true, engineVersion, image: true, imageName: image, detail: `Docker ${engineVersion ?? '?'} ready, ${image} present.` }
}

export interface EnsureImageOptions {
  contextDir: string
  runner?: CommandRunner
  image?: string
  dockerPath?: string
  onProgress?: (line: string) => void
  /** Extra attempts after the first failure (default 1 → two attempts total). */
  retries?: number
  timeoutMs?: number
}

export interface EnsureImageResult {
  image: string
  built: boolean
  attempts: number
  log: string[]
}

/** Build the sandbox image from the bundled context. Throws with the captured log. */
export async function ensureSandboxImage(options: EnsureImageOptions): Promise<EnsureImageResult> {
  const runner = options.runner ?? runCommand
  const image = options.image ?? SANDBOX_IMAGE
  const docker = options.dockerPath ?? 'docker'
  const attempts = 1 + Math.max(0, options.retries ?? 1)
  const log: string[] = []
  const emit = (line: string) => {
    log.push(line)
    options.onProgress?.(line)
  }
  if (!fs.existsSync(options.contextDir)) {
    throw new Error(`Docker build context is missing: ${options.contextDir}`)
  }
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    emit(`[mode] building ${image} from ${options.contextDir} (attempt ${attempt}/${attempts})`)
    const result = await runner(docker, ['build', '--tag', image, options.contextDir], {
      timeoutMs: options.timeoutMs ?? 30 * 60_000,
      onLine: (line) => emit(line),
    })
    if (result.code === 0) return { image, built: true, attempts: attempt, log }
    emit(`[mode] build attempt ${attempt} failed (exit ${result.code}${result.timedOut ? ', timed out' : ''})`)
  }
  throw new Error(`Could not build ${image} after ${attempts} attempt(s).\n${log.slice(-25).join('\n')}`)
}

export interface ModeDecision {
  mode: ExecutionMode
  reason: string
}

/** Host startup must not wake/probe Docker at all. Docker selection retains its policy. */
export async function selectStartupMode(preferred: ExecutionMode, options: ProbeDockerOptions = {}): Promise<{
  decision: ModeDecision; probe: DockerProbe | null
}> {
  if (preferred === 'host') return { decision: { mode: 'host', reason: 'host mode selected.' }, probe: null }
  const probe = await probeDocker(options)
  return { decision: decideMode(preferred, probe), probe }
}

/** Never silently switches: the reason string is shown in diagnostics and logs. */
export function decideMode(preferred: ExecutionMode, probe: DockerProbe): ModeDecision {
  if (preferred === 'host') return { mode: 'host', reason: 'host mode selected.' }
  if (!probe.cli) return { mode: 'host', reason: `${probe.detail} Falling back to host mode.` }
  if (!probe.engine) return { mode: 'host', reason: `${probe.detail} Falling back to host mode.` }
  if (!probe.image) return { mode: 'host', reason: `${probe.detail} Falling back to host mode.` }
  return { mode: 'docker', reason: probe.detail }
}

export interface ComposeOverrideInput {
  /** Short profile key (hex) used for container/volume names. */
  profileKey: string
  ports: PortMap
  adminToken: string
  /** Absolute path of the read-only skills mount inside the harness bundle. */
  skillsDir: string
}

/** Docker compose override: per-profile container/volume identity + ports + secrets. */
export function composeOverrideYaml(input: ComposeOverrideInput): string {
  const container = `boxfox-desktop-${input.profileKey}`
  const volume = `boxfox-desktop-${input.profileKey}-workspace`
  const origins = `http://127.0.0.1:${input.ports.gateway},http://localhost:${input.ports.gateway}`
  return [
    '# Generated by BoxFox Desktop (Alpha) — do not edit by hand.',
    'services:',
    '  box:',
    `    container_name: ${container}`,
    '    ports:',
    '      - "127.0.0.1:5900:5900"',
    '      - "127.0.0.1:6080:6080"',
    '      - "127.0.0.1:8080:8080"',
    `      - "127.0.0.1:${input.ports.box}:8081"`,
    '    environment:',
    `      BOXFOX_API_KEY: "${input.adminToken}"`,
    `      BOXFOX_UI_ORIGINS: "${origins}"`,
    '    volumes:',
    `      - ${volume}:/home/agent/workspace`,
    `      - ${input.skillsDir}:/opt/boxfox-skills:ro`,
    'volumes:',
    `  ${volume}:`,
    `    name: ${volume}`,
    '',
  ].join('\n')
}

export function writeComposeOverride(profileDir: string, input: ComposeOverrideInput): string {
  const file = path.join(profileDir, 'docker-compose.override.yml')
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, composeOverrideYaml(input), 'utf8')
  return file
}

export interface ComposeBoxOptions {
  composeFile: string
  overrideFile: string
  runner?: CommandRunner
  dockerPath?: string
  onProgress?: (line: string) => void
}

function composeArgs(options: ComposeBoxOptions, action: 'up' | 'down'): string[] {
  const args = ['compose', '-f', options.composeFile, '-f', options.overrideFile]
  return action === 'up' ? [...args, 'up', '-d'] : [...args, 'down']
}

export async function startBoxContainer(options: ComposeBoxOptions): Promise<CommandResult> {
  const runner = options.runner ?? runCommand
  return runner(options.dockerPath ?? 'docker', composeArgs(options, 'up'), {
    timeoutMs: 5 * 60_000,
    onLine: (line) => options.onProgress?.(line),
  })
}

export async function stopBoxContainer(options: ComposeBoxOptions): Promise<CommandResult> {
  const runner = options.runner ?? runCommand
  return runner(options.dockerPath ?? 'docker', composeArgs(options, 'down'), { timeoutMs: 120_000 })
}
