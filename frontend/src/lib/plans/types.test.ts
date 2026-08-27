import { describe, expect, it } from 'vitest'
import { reconcilePlanSelection, withPresentationStatuses } from './types'
import type { PlanManifest } from './types'

const manifest: PlanManifest = {
  plans: [
    {
      identity: 'designs/login',
      relativeDirectory: 'designs',
      slug: 'login',
      versions: [
        { version: 2, label: 'v2', relativePath: 'designs/v2-login.md', sizeBytes: 2, modifiedAt: '2026-01-01T00:00:00Z', status: 'draft' },
        { version: 1, label: 'v1', relativePath: 'designs/v1-login.md', sizeBytes: 1, modifiedAt: '2026-01-01T00:00:00Z', status: 'approved' },
      ],
    },
    {
      identity: 'subplans/login',
      relativeDirectory: 'subplans',
      slug: 'login',
      versions: [
        { version: 1, label: 'v1', relativePath: 'subplans/v1-login.md', sizeBytes: 1, modifiedAt: '2026-01-01T00:00:00Z', status: 'draft' },
      ],
    },
  ],
  ignoredCount: 0,
  warnings: [],
}

describe('reconcilePlanSelection', () => {
  it('uses the first identity and newest version initially', () => {
    expect(reconcilePlanSelection(manifest, null)).toEqual({ identity: 'designs/login', version: 2 })
  })

  it('keeps a valid identity and version across refresh', () => {
    expect(reconcilePlanSelection(manifest, { identity: 'designs/login', version: 1 })).toEqual({
      identity: 'designs/login',
      version: 1,
    })
  })

  it('falls back to the newest version when the selected version disappears', () => {
    expect(reconcilePlanSelection(manifest, { identity: 'designs/login', version: 9 })).toEqual({
      identity: 'designs/login',
      version: 2,
    })
  })

  it('falls back to the first identity when the selected identity disappears', () => {
    expect(reconcilePlanSelection(manifest, { identity: 'missing/login', version: 1 })).toEqual({
      identity: 'designs/login',
      version: 2,
    })
  })

  it('clears the selection for an empty manifest', () => {
    expect(reconcilePlanSelection({ ...manifest, plans: [] }, null)).toBeNull()
  })
})

describe('withPresentationStatuses', () => {
  it('marks a single version approved and only the newest multi-version plan draft', () => {
    const next = withPresentationStatuses(manifest)
    expect(next.plans[0]!.versions.map((version) => version.status)).toEqual(['draft', 'approved'])
    expect(next.plans[1]!.versions.map((version) => version.status)).toEqual(['approved'])
  })
})
