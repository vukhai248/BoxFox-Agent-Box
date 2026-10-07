import { describe, expect, it, vi } from 'vitest'
import { createPlanRepository } from './index'
import { MachinePlanRepository, PlanRepositoryHttpError, SandboxPlanRepository } from './http'
import { MockPlanRepository } from './mock'

const env = { VITE_PLAN_SOURCE: 'sandbox', VITE_BOX_API_URL: 'http://box.test' } as unknown as ImportMetaEnv

describe('createPlanRepository', () => {
  it('keeps the sandbox (box) source when no target is given', () => {
    expect(createPlanRepository(env)).toBeInstanceOf(SandboxPlanRepository)
    expect(createPlanRepository(env, { mode: 'docker', projectId: null })).toBeInstanceOf(SandboxPlanRepository)
  })

  it('reads a host session from its project folder instead of the box', () => {
    expect(createPlanRepository(env, { mode: 'host', projectId: 'p1' })).toBeInstanceOf(MachinePlanRepository)
  })

  it('says a folder is missing instead of showing an empty plan list', async () => {
    const repository = createPlanRepository(env, { mode: 'host', projectId: null })

    const failure = await repository.list().catch((error) => error)

    expect(failure).toBeInstanceOf(PlanRepositoryHttpError)
    expect(failure.message).toMatch(/project folder/i)
  })

  it('still honours the explicit mock source', () => {
    vi.stubEnv('VITE_PLAN_SOURCE', 'mock')
    expect(createPlanRepository(import.meta.env, { mode: 'host', projectId: 'p1' })).toBeInstanceOf(MockPlanRepository)
    vi.unstubAllEnvs()
  })
})
