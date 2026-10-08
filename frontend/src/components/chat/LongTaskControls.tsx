import { continuityInvocation } from '../../lib/continuityInvocation'
import { useState } from 'react'
import { useT } from '../../i18n/context'
import { agentApi } from '../../lib/agentApi'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'

const button = 'rounded-lg border border-line px-3 py-1.5 disabled:opacity-40 hover:bg-panel2'
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
  const budget = task?.budget ?? task?.remainingBudget
  if (!run?.id || run.longtask === undefined) return null
  const goalRevision = task?.goalRevision ?? run?.goalRevision
  const valid = Number.isSafeInteger(goalRevision) && Number(goalRevision) > 0 && !!policy && Number.isSafeInteger(Number(steps)) && Number(steps) > 0
    && Number.isFinite(Number(minutes)) && Number(minutes) > 0 && Number.isSafeInteger(Number(minutes) * 60000)
  const submit = async (action?: 'resume' | 'pause' | 'cancel') => {
    if (busy) return
    setBusy(true); setNotice(null)
    try {
      const id = run.id
      if (action && task) {
        await agentApi(`/sessions/${id}/longtask/actions`, { runId: task.runId, action,
          expectedRevision: task.revision, invocationId: continuityInvocation([id, task.runId, task.revision, action]) })
      } else {
        await agentApi(`/sessions/${id}/longtask`, { enabled: true, resumePolicy: policy,
          expectedRevision: task?.revision ?? 0, invocationId: continuityInvocation([id, task?.revision ?? 0, policy, steps, minutes]),
          goalRevision, contractRef: task?.contractRef ?? run.contractRef ?? null,
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
    {task ? <>
      <div className="flex flex-wrap gap-3"><strong>{t('continuity.task')}: {task.state}</strong><span>{t('continuity.turn')}: {run.status}</span><span>{task.resumePolicy}</span></div>
      {budget && <div className="text-muted">
        {t('continuity.steps')}: {budget.totalStepsUsed ?? '—'} / {budget.totalStepLimit ?? '—'} · {t('continuity.remaining')}: {task.remainingBudget?.steps ?? task.remainingBudget?.remainingSteps ?? '—'} · {t('continuity.activeMinutes')}: {budget.activeTimeUsedMs === undefined ? '—' : (budget.activeTimeUsedMs / 60000).toFixed(1)} / {budget.activeTimeLimitMs === undefined ? '—' : (budget.activeTimeLimitMs / 60000).toFixed(1)}
      </div>}
      {task.checkpointRef && <div>{t('continuity.checkpoint')}: <code>{typeof task.checkpointRef === 'string' ? task.checkpointRef : JSON.stringify(task.checkpointRef)}</code></div>}
      {task.blockedReason && <p className="text-amber-400">{task.blockedReason}</p>}
      {task.state === 'budget_exhausted' && <p>{task.checkpointRef ? t('continuity.budgetCheckpoint') : t('continuity.checkpointUnconfirmed')}</p>}
      <div className="flex flex-wrap gap-2">
        {/* completed/cancelled/failed là trạng thái kết thúc: backend từ chối resume (`LONGTASK_BLOCKED`)
            và pause/cancel trên run đã xong chỉ đổi nhãn lịch sử, nên không bày nút giả. */}
        {(['resume', 'pause', 'cancel'] as const).map(action => <button key={action} className={button} disabled={busy || ['completed', 'cancelled', 'failed'].includes(task.state) || (action === 'resume' && task.state === 'budget_exhausted')} onClick={() => void submit(action)}>{t(`continuity.${action}`)}</button>)}
        {(task.pendingDecisionIds?.length || task.state === 'budget_exhausted') ? <button className={button} onClick={() => useUiStore.getState().showTab('decisions')}>{t('continuity.decisions')}</button> : null}
      </div>
    </> : <>
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
