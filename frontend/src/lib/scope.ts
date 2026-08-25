/**
 * Generates the bundled scope line for ModeSwitchCard (Section 12.5.1).
 * Pure function independent of runtime i18n for deterministic testing.
 */
import type { ModeSwitchProposal } from '../types/agent'

/**
 * Generates the bundled scope description from canonical_resources and proposed lease duration.
 * If bundled_lease_rejected is true, returns the standard warning message.
 */
export function buildBundledScopeLine(proposal: ModeSwitchProposal): string {
  if (proposal.bundled_lease_rejected || !proposal.proposed_lease) {
    return 'Plan scope is too broad for a bundled lease — each file write or command execution will require individual approval.'
  }
  const { canonical_resources, duration_minutes } = proposal.proposed_lease
  const resourceList = formatResourceList(canonical_resources)
  return `If approved, the agent will be granted read & write access to ${resourceList} for ${duration_minutes} minutes, with egress strictly restricted.`
}

/** Formats resource list: e.g. "`src/**`", "`src/**` and `tests/**`", or "`src/**`, `tests/**` and `docs/**`". */
export function formatResourceList(resources: readonly string[]): string {
  const quoted = resources.map((r) => `\`${r}\``)
  if (quoted.length === 0) return ''
  if (quoted.length === 1) return quoted[0]
  if (quoted.length === 2) return `${quoted[0]} and ${quoted[1]}`
  return `${quoted.slice(0, -1).join(', ')} and ${quoted[quoted.length - 1]}`
}
