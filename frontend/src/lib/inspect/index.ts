/**
 * Factory của gói `lib/inspect/` — theo đúng khuôn `lib/plans/index.ts`.
 * Sandbox là mặc định; `VITE_ELEMENT_INSPECT_SOURCE=mock` chỉ dùng cho test/demo.
 */
import { resolveBoxApiKey, resolveBoxApiUrl } from '../boxApi'
import { SandboxInspectRepository } from './http'
import { MockInspectRepository } from './mock'
import type { InspectRepository } from './types'

export * from './types'

export type InspectSource = 'sandbox' | 'mock'

export function createInspectRepository(env: ImportMetaEnv = import.meta.env): InspectRepository {
  const source = env.VITE_ELEMENT_INSPECT_SOURCE?.trim().toLowerCase()
  if (source === 'mock') return new MockInspectRepository()
  return new SandboxInspectRepository(resolveBoxApiUrl(env), resolveBoxApiKey(env))
}
