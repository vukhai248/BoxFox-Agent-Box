/**
 * Test (a): integrity_floor và confidentiality_ceiling.
 */
import { describe, it, expect } from 'vitest'
import { computeIntegrityFloor, computeConfidentialityCeiling } from './labels'
import type { ContextChunk } from '../types/context'
import { INTEGRITY, CONFIDENTIALITY } from '../types/labels'

function chunk(overrides: Partial<ContextChunk> = {}): ContextChunk {
  return {
    provenance: {
      label_id: 'L001',
      source_kind: 'user_input',
      source_uri: '',
      tool_name: 'ask_user',
      content_hash: 'abc',
      derived_from: [],
      created_at: new Date().toISOString(),
    },
    integrity: INTEGRITY.USER_AUTHORIZED,
    confidentiality: CONFIDENTIALITY.INTERNAL,
    content: '',
    step_count: 0,
    endorsed: false,
    ...overrides,
  }
}

describe('computeIntegrityFloor', () => {
  it('all clean → floor = USER_AUTHORIZED', () => {
    const result = computeIntegrityFloor([
      chunk({ integrity: INTEGRITY.USER_AUTHORIZED }),
      chunk({ integrity: INTEGRITY.USER_AUTHORIZED }),
    ])
    expect(result).toBe(INTEGRITY.USER_AUTHORIZED)
  })

  it('one dirty → floor = UNTRUSTED_DATA', () => {
    const result = computeIntegrityFloor([
      chunk({ integrity: INTEGRITY.USER_AUTHORIZED }),
      chunk({ integrity: INTEGRITY.UNTRUSTED_DATA }),
    ])
    expect(result).toBe(INTEGRITY.UNTRUSTED_DATA)
  })

  it('empty → floor = USER_AUTHORIZED', () => {
    expect(computeIntegrityFloor([])).toBe(INTEGRITY.USER_AUTHORIZED)
  })
})

describe('computeConfidentialityCeiling', () => {
  it('all PUBLIC → ceiling = PUBLIC', () => {
    const result = computeConfidentialityCeiling([
      chunk({ confidentiality: CONFIDENTIALITY.PUBLIC }),
      chunk({ confidentiality: CONFIDENTIALITY.PUBLIC }),
    ])
    expect(result).toBe(CONFIDENTIALITY.PUBLIC)
  })

  it('one SECRET → ceiling = SECRET', () => {
    const result = computeConfidentialityCeiling([
      chunk({ confidentiality: CONFIDENTIALITY.INTERNAL }),
      chunk({ confidentiality: CONFIDENTIALITY.SECRET }),
      chunk({ confidentiality: CONFIDENTIALITY.PUBLIC }),
    ])
    expect(result).toBe(CONFIDENTIALITY.SECRET)
  })

  it('empty → ceiling = PUBLIC', () => {
    expect(computeConfidentialityCeiling([])).toBe(CONFIDENTIALITY.PUBLIC)
  })
})
