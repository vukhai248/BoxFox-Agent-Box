/**
 * Diagnostics for BoxFox Desktop (Alpha) — the data behind the tray/diagnostics panel
 * (D3) and behind `GET /api/desktop/health`. Read-only: it never starts or stops
 * anything.
 */

import type { DockerProbe } from './mode'
import type { ExecutionMode, PortMap } from './profile'
import type { SupervisorStatus } from './supervisor'

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
