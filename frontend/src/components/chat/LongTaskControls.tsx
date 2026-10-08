import { continuityInvocation } from '../../lib/continuityInvocation'
import { useState } from 'react'
import { useT, type TKey } from '../../i18n/context'
import { agentApi } from '../../lib/agentApi'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'

const button = 'rounded-lg border border-line px-3 py-1.5 disabled:opacity-40 hover:bg-panel2'
/** Trạng thái kết thúc của run: backend cho lập run MỚI cho cùng phiên, nên form thiết lập mở lại. */
const TERMINAL_STATES = ['completed', 'cancelled', 'failed']
/**
 * `blockedReason` của run → câu chữ. Chỉ mã backend thật sự đặt làm lý do chặn mới có bản dịch; mã
 * lạ (kể cả mã lỗi lượt mà backend giữ nguyên thay cho `TURN_FAILED_<CLASS>`) hiện nguyên văn để còn
 * tra cứu, không đoán bừa.
 */
const REASON_KEY: Record<string, TKey> = {
  LONGTASK_BUDGET_TOO_SMALL: 'continuity.reasonBudgetTooSmall',
  LONGTASK_BUDGET_EXHAUSTED: 'continuity.reasonBudgetExhausted',
  LONGTASK_STALE: 'continuity.reasonStale',
  LONGTASK_NO_PROGRESS: 'continuity.reasonNoProgress',
  LONGTASK_TURN_FAILED: 'continuity.reasonTurnFailed',
  LONGTASK_PENDING_DECISION: 'continuity.reasonPendingDecision',
  LONGTASK_WALL_DEADLINE: 'continuity.reasonWallDeadline',
  LONGTASK_DISABLED: 'continuity.reasonDisabled',
  LONGTASK_LEASE_BUSY: 'continuity.reasonLeaseBusy',
  LONGTASK_UNSAFE_INTERRUPTION: 'continuity.reasonUnsafeInterruption',
}
export function LongTaskControls({ chatId }: { chatId: string }) {
  const t = useT()
  const run = useHarnessChatStore(s => s.sessions[chatId])
  const [open, setOpen] = useState(false)
  const [policy, setPolicy] = useState('')
  const [steps, setSteps] = useState('')
  const [minutes, setMinutes] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const task = run?.longtask
  const budget = task?.budget
  if (!run?.id || run.longtask === undefined) return null
  const terminal = !!task && TERMINAL_STATES.includes(task.state)
  // Chưa có run, hoặc run trước đã kết thúc → được thiết lập run mới.
  const canConfigure = !task || terminal
  // Run mới ghim vào revision mục tiêu HIỆN TẠI của phiên; bản ghim cũ của run đã xong có thể đã cũ.
  const goalRevision = canConfigure ? run.goalRevision : task?.goalRevision
  const canonicalGoal = Number.isSafeInteger(run.goalRevision) && Number(run.goalRevision) > 0
  // Đúng ca run dừng vì yêu cầu của chính chủ đã đổi hợp đồng: còn đường ghim lại, không phải bế tắc.
  const stalePin = task?.state === 'needs_user' && task.blockedReason === 'LONGTASK_STALE'
  const valid = Number.isSafeInteger(goalRevision) && Number(goalRevision) > 0 && !!policy && Number.isSafeInteger(Number(steps)) && Number(steps) > 0
    && Number.isFinite(Number(minutes)) && Number(minutes) > 0 && Number.isSafeInteger(Number(minutes) * 60000)
  const reasonText = (code: string) => { const key = REASON_KEY[code]; return key ? t(key) : code }
  const submit = async (action?: 'resume' | 'pause' | 'cancel' | 'repin') => {
    if (busy) return
    setBusy(true); setNotice(null)
    try {
      const id = run.id
      if (action === 'repin' && task) {
        // Ghim lại vào hợp đồng hiện tại, KHÔNG gửi ngân sách: backend giữ phần đã tiêu và từ chối
        // đổi hạn mức trực tiếp (`LONGTASK_CONSENT_REQUIRED`).
        await agentApi(`/sessions/${id}/longtask`, { enabled: true, goalRevision: run.goalRevision,
          contractRef: run.contractRef ?? null, expectedRevision: task.revision,
          invocationId: continuityInvocation([id, task.runId, task.revision, 'repin', run.goalRevision]) }, 'PUT')
      } else if (action && task) {
        await agentApi(`/sessions/${id}/longtask/actions`, { runId: task.runId, action,
          expectedRevision: task.revision, invocationId: continuityInvocation([id, task.runId, task.revision, action]) })
      } else {
        // `task?.runId` nằm trong khoá idempotency: hai lần lập run khác nhau có thể trùng body (cùng
        // expectedRevision và cùng số bước), mà cùng invocationId + cùng body thì backend trả kết quả
        // đã lưu thay vì lập run mới.
        await agentApi(`/sessions/${id}/longtask`, { enabled: true, resumePolicy: policy,
          expectedRevision: task?.revision ?? 0,
          invocationId: continuityInvocation([id, task?.runId ?? 'first', task?.revision ?? 0, policy, steps, minutes]),
          goalRevision, contractRef: run.contractRef ?? null,
          budget: { totalStepLimit: Number(steps), activeTimeLimitMs: Number(minutes) * 60000 } }, 'PUT')
      }
      setNotice(t('continuity.accepted'))
      await useHarnessChatStore.getState().refresh(chatId)
    } catch (error) {
      setNotice(String(error))
      await useHarnessChatStore.getState().refresh(chatId)
    } finally { setBusy(false) }
  }
  return <section data-testid="longtask-controls" className="border-t border-line bg-panel2/60 px-4 py-3 text-xs space-y-2">
    {task && <>
      <div className="flex flex-wrap gap-3"><strong>{t('continuity.task')}: {task.state}</strong><span>{t('continuity.turn')}: {run.status}</span><span>{task.resumePolicy}</span></div>
      {budget && <div className="text-muted">
        {t('continuity.steps')}: {budget.totalStepsUsed} / {budget.totalStepLimit} · {t('continuity.remaining')}: {task.remainingBudget?.steps ?? '—'} · {t('continuity.activeMinutes')}: {(budget.activeTimeUsedMs / 60000).toFixed(1)} / {(budget.activeTimeLimitMs / 60000).toFixed(1)}
      </div>}
      {task.checkpointRef && <div>{t('continuity.checkpoint')}: <code>{typeof task.checkpointRef === 'string' ? task.checkpointRef : JSON.stringify(task.checkpointRef)}</code></div>}
      {task.blockedReason && <p className="text-amber-400">{reasonText(task.blockedReason)}</p>}
      {task.state === 'budget_exhausted' && <p>{task.checkpointRef ? t('continuity.budgetCheckpoint') : t('continuity.checkpointUnconfirmed')}</p>}
      <div className="flex flex-wrap gap-2">
        {/* completed/cancelled/failed là trạng thái kết thúc: backend từ chối resume (`LONGTASK_BLOCKED`)
            và pause/cancel trên run đã xong chỉ đổi nhãn lịch sử, nên không bày nút giả. */}
        {(['resume', 'pause', 'cancel'] as const).map(action => <button key={action} className={button} disabled={busy || terminal || (action === 'resume' && task.state === 'budget_exhausted')} onClick={() => void submit(action)}>{t(`continuity.${action}`)}</button>)}
        {stalePin && <button className={button} disabled={busy || !canonicalGoal} onClick={() => void submit('repin')}>{t('continuity.repin')}</button>}
        {(task.pendingDecisionIds?.length || task.state === 'budget_exhausted') ? <button className={button} onClick={() => useUiStore.getState().showTab('decisions')}>{t('continuity.decisions')}</button> : null}
      </div>
    </>}
    {canConfigure && <>
      <button className={button} onClick={() => setOpen(!open)} aria-expanded={open}>{t('continuity.enable')}</button>
      {open && <div className="space-y-2">
        <p className="text-muted">{t('continuity.optInHint')}</p>
        {!goalRevision && <p className="text-amber-400">{t('continuity.contractMissing')}</p>}
        <label className="block">{t('continuity.policy')} <select className="bg-panel border border-line rounded p-1" value={policy} onChange={e => setPolicy(e.target.value)}><option value="">{t('continuity.choose')}</option><option value="manual">{t('continuity.manual')}</option><option value="safe_auto">{t('continuity.safeAuto')}</option></select></label>
        <div className="flex flex-wrap gap-3">
          <label>{t('continuity.steps')} <input className="w-24 bg-panel border border-line rounded p-1" type="number" min="1" step="1" value={steps} onChange={e => setSteps(e.target.value)} /></label>
          <label>{t('continuity.activeMinutes')} <input className="w-24 bg-panel border border-line rounded p-1" type="number" min="1" value={minutes} onChange={e => setMinutes(e.target.value)} /></label>
          <button className={button} disabled={busy || !valid} onClick={() => void submit()}>{t('continuity.confirmOptIn')}</button>
        </div>
      </div>}
    </>}
    {notice && <p role="status" className="text-amber-400">{notice}</p>}
  </section>
}
