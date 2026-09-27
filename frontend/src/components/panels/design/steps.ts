/**
 * Nhãn của bảy bước run Design, ánh xạ `DesignStepKey` → khoá i18n. Dùng chung cho dải trong ô soạn
 * tin, lời hỏi thoát chế độ và dòng thời gian — một nguồn chữ duy nhất.
 */
import type { TKey } from '../../../i18n/context'
import type { DesignStepKey } from '../../../lib/designMode'

export const STEP_LABEL_KEY: Record<DesignStepKey, TKey> = {
  clarify: 'design.stepClarify',
  brief: 'design.stepBrief',
  approve: 'design.stepApprove',
  draw: 'design.stepDraw',
  write: 'design.stepWrite',
  review: 'design.stepReview',
  handoff: 'design.stepHandoff',
}
