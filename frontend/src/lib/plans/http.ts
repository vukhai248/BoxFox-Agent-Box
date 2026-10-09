import { agentApi, ApiError } from '../agentApi'
import { withPresentationStatuses } from './types'
import type { PlanDocument, PlanManifest, PlanRepository } from './types'

/** Adapter HTTP cho hai endpoint read-only của ide-proxy. */
export class SandboxPlanRepository implements PlanRepository {
  constructor(private readonly baseUrl: string) {}

  async list(signal?: AbortSignal): Promise<PlanManifest> {
    const manifest = await requestJson<PlanManifest>(`${this.baseUrl.replace(/\/$/, '')}/__box/plans`, signal)
    return withPresentationStatuses(manifest)
  }

  async read(identity: string, version: number, signal?: AbortSignal): Promise<PlanDocument> {
    const params = new URLSearchParams({ identity, version: String(version) })
    return requestJson<PlanDocument>(`${this.baseUrl.replace(/\/$/, '')}/__box/plans/content?${params}`, signal)
  }
}

/**
 * Adapter cho host mode: `.plans` nằm trong folder dự án của máy thật, không có box nào để gọi
 * `/__box`. Harness đọc cùng bộ đọc với box (`deploy/docker/plan_files.py`) nên payload y hệt —
 * tab Plan không phải rẽ nhánh khi render, chỉ khác đường đi.
 */
export class MachinePlanRepository implements PlanRepository {
  constructor(private readonly projectId: string) {}

  async list(signal?: AbortSignal): Promise<PlanManifest> {
    const manifest = await harnessJson<PlanManifest>(this.path('plans'), signal)
    return withPresentationStatuses(manifest)
  }

  async read(identity: string, version: number, signal?: AbortSignal): Promise<PlanDocument> {
    const params = new URLSearchParams({ identity, version: String(version) })
    return harnessJson<PlanDocument>(`${this.path('plans/content')}?${params}`, signal)
  }

  private path(route: string): string {
    return `/machines/projects/${encodeURIComponent(this.projectId)}/${route}`
  }
}

/** Lỗi của harness giữ nguyên `status`/câu lỗi, nhưng đổi sang kiểu lỗi của tab Plan. */
async function harnessJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  try {
    return await agentApi<T>(path, undefined, undefined, signal)
  } catch (cause) {
    if (cause instanceof ApiError) {
      throw new PlanRepositoryHttpError(cause.status, cause.message)
    }
    throw cause
  }
}

async function requestJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  if (!response.ok) {
    throw new PlanRepositoryHttpError(response.status, `Unable to load plan files (${response.status}).`)
  }
  try {
    const payload: unknown = await response.json()
    if (!payload || typeof payload !== 'object') {
      throw new Error('The plan service returned an invalid response.')
    }
    return payload as T
  } catch (cause) {
    if (cause instanceof Error && cause.message === 'The plan service returned an invalid response.') throw cause
    throw new Error('The plan service returned an invalid response.', { cause })
  }
}

export class PlanRepositoryHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'PlanRepositoryHttpError'
  }
}
