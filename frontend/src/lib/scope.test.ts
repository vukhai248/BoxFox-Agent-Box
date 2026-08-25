/**
 * Unit tests for scope line formatting and lease validation.
 */
import { describe, it, expect } from 'vitest'
import { formatResourceList, buildBundledScopeLine } from './scope'
import type { ModeSwitchProposal } from '../types/agent'

function proposal(overrides: Partial<ModeSwitchProposal> = {}): ModeSwitchProposal {
  return {
    plan: {
      label_id: 'L-plan',
      full_text: 'Plan content',
      steps: [],
      derived_from: [],
      content_hash: 'abc',
      created_at: new Date().toISOString(),
    },
    bundled_lease_rejected: false,
    proposed_lease: {
      canonical_resources: ['src/', 'tests/'],
      duration_minutes: 30,
    },
    ...overrides,
  }
}

describe('formatResourceList', () => {
  it('one resource', () => {
    expect(formatResourceList(['src/'])).toContain('`src/`')
  })

  it('two resources', () => {
    const line = formatResourceList(['src/', 'tests/'])
    expect(line).toContain('`src/`')
    expect(line).toContain('tests/')
    expect(line).toContain('and')
  })

  it('empty → empty string', () => {
    expect(formatResourceList([])).toBe('')
  })
})

describe('buildBundledScopeLine', () => {
  it('normal scope → includes resources and duration', () => {
    const line = buildBundledScopeLine(proposal())
    expect(line).toContain('src/')
    expect(line).toContain('30 minutes')
    expect(line).toContain('read & write access')
  })

  it('bundled_lease_rejected → warning message', () => {
    const line = buildBundledScopeLine(proposal({ bundled_lease_rejected: true }))
    expect(line).toContain('too broad')
    expect(line).toContain('individual approval')
  })

  it('null proposed_lease → warning message', () => {
    const line = buildBundledScopeLine(proposal({ proposed_lease: null }))
    expect(line).toContain('too broad')
  })
})
