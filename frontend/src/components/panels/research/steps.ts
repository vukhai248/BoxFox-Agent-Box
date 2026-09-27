/**
 * Nhãn của bảy bước run, ánh xạ `ResearchStepKey` → khoá i18n. Dùng chung cho dải trong ô soạn,
 * lời hỏi thoát chế độ, dòng thời gian và thẻ phạm vi — một nguồn chữ duy nhất.
 */
import type { TKey } from '../../../i18n/context'
import type { ResearchStepKey } from '../../../lib/researchMode'

export const STEP_LABEL_KEY: Record<ResearchStepKey, TKey> = {
  clarify: 'research.stepClarify',
  plan: 'research.stepPlan',
  search: 'research.stepSearch',
  read: 'research.stepRead',
  synthesize: 'research.stepSynthesize',
  critique: 'research.stepCritique',
  done: 'research.stepDone',
}
