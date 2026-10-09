import { resolveBoxApiUrl } from '../boxApi'
import { MachinePlanRepository, PlanRepositoryHttpError, SandboxPlanRepository } from './http'
import { MockPlanRepository } from './mock'
import type { PlanRepository } from './types'

export * from './types'
export { PlanRepositoryHttpError } from './http'

// Trạng thái duyệt thật + bản chấm P1–P8: đọc từ sổ của harness, không phải từ box.
export {
  DEFAULT_PLAN_GATE,
  EVAL_DIMENSIONS,
  HarnessPlanStatusClient,
  PLAN_GATE_MODES,
  PLAN_MAX_CHARS,
  PLAN_REVIEW_STATES,
  PLAN_VERIFICATION_STATES,
  PLAN_WAKE_STATES,
  PLAN_WARN_CHARS,
  PlanReviewBlockedError,
  createPlanStatusClient,
  planCount,
  planMeasure,
  planMeasureText,
  planStamp,
  readPlanEvaluation,
  readPlanGate,
  readPlanStatus,
  readPlanStatusReview,
  readPlanVerification,
  readPlanWake,
} from './planState'
export type {
  PlanDecision,
  PlanEvalDimension,
  PlanEvalLayer,
  PlanEvalLevel,
  PlanEvalVerdict,
  PlanEvaluation,
  PlanGate,
  PlanGateMode,
  PlanIssueSeverity,
  PlanOwnership,
  PlanReviewOutcome,
  PlanReviewState,
  PlanStatusClient,
  PlanStatusReport,
  PlanStatusReview,
  PlanVerification,
  PlanVerificationIssue,
  PlanVerificationState,
  PlanWake,
  PlanWakeState,
} from './planState'
export { planRejection } from './rejection'
export type { PlanRejection } from './rejection'

export type PlanSource = 'sandbox' | 'mock'

/** Nơi lấy manifest/nội dung plan: box (Docker) hay folder dự án của phiên host. */
export interface PlanTransport {
  mode: 'host' | 'docker'
  projectId: string | null
}

/** Sandbox là mặc định; mock chỉ bật tường minh trong test hoặc demo. */
export function createPlanRepository(
  env: ImportMetaEnv = import.meta.env,
  target?: PlanTransport,
): PlanRepository {
  const source = env.VITE_PLAN_SOURCE?.trim().toLowerCase()
  if (source === 'mock') return new MockPlanRepository()
  if (target?.mode === 'host') {
    if (!target.projectId) {
      return new UnavailablePlanRepository('Select a host project folder to load plan files.')
    }
    return new MachinePlanRepository(target.projectId)
  }
  return new SandboxPlanRepository(resolveBoxApiUrl(env))
}

/** Không có nguồn nào để đọc (host mode chưa chọn folder): mọi lượt đọc trả đúng một câu lỗi. */
class UnavailablePlanRepository implements PlanRepository {
  constructor(private readonly message: string) {}

  async list(): Promise<never> {
    throw new PlanRepositoryHttpError(0, this.message)
  }

  async read(): Promise<never> {
    throw new PlanRepositoryHttpError(0, this.message)
  }
}
