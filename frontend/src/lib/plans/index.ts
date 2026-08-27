import { resolveBoxApiUrl } from '../boxApi'
import { SandboxPlanRepository } from './http'
import { MockPlanRepository } from './mock'
import type { PlanRepository } from './types'

export * from './types'
export { PlanRepositoryHttpError } from './http'

export type PlanSource = 'sandbox' | 'mock'

/** Sandbox là mặc định; mock chỉ bật tường minh trong test hoặc demo. */
export function createPlanRepository(env: ImportMetaEnv = import.meta.env): PlanRepository {
  const source = env.VITE_PLAN_SOURCE?.trim().toLowerCase()
  if (source === 'mock') return new MockPlanRepository()
  return new SandboxPlanRepository(resolveBoxApiUrl(env))
}
