import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { usePlanStore } from '../../../store/planStore'
import type { PlanAnswer, PlanRun } from '../../../lib/planApi'

function phases(t: ReturnType<typeof useT>): Record<string, string> {
  return { scoping: t('plan.workflow.phaseScoping'), investigating: t('plan.workflow.phaseInvestigating'), interviewing: t('plan.workflow.phaseInterviewing'), drafting: t('plan.workflow.phaseDrafting'), reviewing: t('plan.workflow.phaseReviewing'), ready: t('plan.workflow.phaseReady'), approved: t('plan.workflow.phaseApproved') }
}
function fields(t: ReturnType<typeof useT>): Record<string, string> {
  return { goal: t('plan.workflow.fieldGoal'), users: t('plan.workflow.fieldUsers'), workflow: t('plan.workflow.fieldWorkflow'), scope: t('plan.workflow.fieldScope'), data: t('plan.workflow.fieldData'), constraints: t('plan.workflow.fieldConstraints'), success: t('plan.workflow.fieldSuccess') }
}
function statuses(t: ReturnType<typeof useT>): Record<string, string> {
  return { active: t('plan.workflow.statusActive'), needs_user: t('plan.workflow.statusNeedsUser'), paused: t('plan.workflow.statusPaused'), blocked: t('plan.workflow.statusBlocked'), cancelled: t('plan.workflow.statusCancelled'), executing: t('plan.workflow.statusExecuting'), user: t('plan.workflow.sourceUser'), observed: t('plan.workflow.sourceObserved'), proposed: t('plan.workflow.sourceProposed'), unresolved: t('plan.workflow.sourceUnresolved') }
}

export function PlanComposerStatus() {
  const t = useT()
  const mode = usePlanStore(s => s.mode)
  const run = usePlanStore(s => s.runs.find(r => r.runId === s.mode.activeRunId))
  const error = usePlanStore(s => s.error)
  if (!mode.on && !error) return null
  return <div className="flex items-center gap-2 text-xs text-muted" data-testid="plan-mode-status">
    {mode.on && <><span>{t('plan.workflow.active')} · {run ? `${phases(t)[run.phase] ?? run.phase} · ${statuses(t)[run.status] ?? run.status}` : t('plan.workflow.waitGoal')}</span>
      <button type="button" onClick={() => void usePlanStore.getState().toggle(false)}>{t('plan.workflow.pause')}</button></>}
    {error && <span role="alert" className="text-rose-400">{error}</span>}
  </div>
}

export function PlanInterview({ run }: { run: PlanRun }) {
  const t = useT()
  const [answers, setAnswers] = useState<Record<string, PlanAnswer>>({})
  const saving = usePlanStore(s => s.saving)
  const questions = run.questions.filter(q => q.status === 'open')
  const filled = questions.map(q => answers[q.id]).filter((a): a is PlanAnswer => !!a && !!(a.text?.trim() || a.optionId))
  const submit = async () => {
    if (await usePlanStore.getState().answer(run, filled)) setAnswers({})
  }
  if (!questions.length) return null
  return <section className="rounded-xl border border-line bg-panel p-4 space-y-4" aria-label={t('plan.workflow.interview')} data-testid="plan-interview">
    <p className="text-sm font-medium">{t('plan.workflow.interview')}</p>
    {questions.map(q => <fieldset key={q.id} className="space-y-2">
      <legend className="text-sm font-medium">{q.text}</legend>
      {q.why && <p className="text-xs text-muted">{q.why}</p>}
      <div className="flex flex-wrap gap-2">{q.options.map(o => <label key={o.id} className="rounded border border-line p-2 text-sm cursor-pointer">
        <input type="radio" name={`${run.runId}-${q.id}`} checked={answers[q.id]?.optionId === o.id}
          onChange={() => setAnswers(prev => ({ ...prev, [q.id]: { questionId: q.id, optionId: o.id } }))} /> {o.label}
        {o.tradeoff && <span className="block text-xs text-muted">{o.tradeoff}</span>}
      </label>)}</div>
      <textarea aria-label={`${q.text} — ${t('plan.workflow.freeText')}`} placeholder={t('plan.workflow.freeText')}
        value={answers[q.id]?.text ?? ''} className="w-full rounded border border-line bg-bg p-2 text-sm"
        onChange={e => setAnswers(prev => ({ ...prev, [q.id]: { questionId: q.id, text: e.target.value } }))} />
    </fieldset>)}
    <button type="button" className="rounded bg-fg text-bg px-3 py-2 text-sm disabled:opacity-50" disabled={saving || !filled.length || ['paused', 'cancelled', 'executing'].includes(run.status)} onClick={() => void submit()}>
      {saving ? t('plan.workflow.saving') : filled.length < questions.length ? t('plan.workflow.savePartial') : t('plan.workflow.continue')}
    </button>
    <p className="text-xs text-muted">{t('plan.workflow.durableWait')}</p>
  </section>
}

export function PlanWorkflowView({ document }: { document?: { identity: string; version: number } | null }) {
  const t = useT()
  const mode = usePlanStore(s => s.mode)
  const run = usePlanStore(s => document
    ? s.runs.find(r => r.document?.identity === document.identity && r.document?.version === document.version)
    : s.runs.find(r => r.runId === s.mode.activeRunId))
  const saving = usePlanStore(s => s.saving)
  const error = usePlanStore(s => s.error)
  const [showBrief, setShowBrief] = useState(false)
  if (!run) return null
  return <div className="p-3 space-y-3" data-testid="plan-workflow">
    <div className="flex items-center gap-3 flex-wrap text-sm">
      <strong>{phases(t)[run.phase] ?? run.phase}</strong><span className="text-muted">{statuses(t)[run.status] ?? run.status}</span>
      <button type="button" onClick={() => setShowBrief(!showBrief)}>{t('plan.workflow.brief')}</button>
      {run.status === 'paused' || run.status === 'blocked' ? <button type="button" disabled={saving} onClick={() => void usePlanStore.getState().action(run, 'resume')}>{t('plan.workflow.continue')}</button> : null}
      {run.switchAnswer && ['new', 'current'].includes(run.switchAnswer) && <button type="button" disabled={saving} onClick={() => void usePlanStore.getState().action(run, run.switchAnswer!)}>{t('plan.workflow.continue')}</button>}
      {run.phase === 'approved' && run.status !== 'executing' && <button type="button" data-testid="plan-execute" disabled={saving} className="rounded bg-fg text-bg px-3 py-1" onClick={() => void usePlanStore.getState().execute(run)}>{t('plan.workflow.execute')} v{run.document?.version}</button>}
      {!mode.on && run.status === 'executing' && <span>{t('plan.workflow.executionQueued')}{run.executionStatus ? ` · ${run.executionStatus}` : ''}</span>}
    </div>
    {run.blocker && <p className="text-sm text-amber-400">{run.blocker}</p>}
    {error && <p role="alert" className="text-sm text-rose-400">{error}</p>}
    {(showBrief || run.questions.some(q => q.status === 'open' && q.field === '__confirm__')) && <div className="space-y-2 text-sm">
      {Object.entries(run.brief).map(([key, value]) => <div key={key}><strong>{fields(t)[key] ?? key}: </strong>{value.text} <span className="text-xs text-muted">({statuses(t)[value.status] ?? value.status})</span>{value.reason && <p>{value.reason}</p>}</div>)}
      {run.decisions.map(d => <p key={d.id}><strong>{d.id}: </strong>{d.text} <span className="text-muted">({statuses(t)[d.status] ?? d.status})</span> {d.reason}</p>)}
    </div>}
    <PlanInterview key={run.runId} run={run} />
    {run.review && <details className="text-sm"><summary>{t('plan.workflow.review')} · {run.review.verdict}</summary>
      {Object.entries(run.review.dimensions).map(([key, value]) => <p key={key} className="mt-1"><strong>{key}: {value.status}</strong> — {value.evidence}</p>)}
      {run.review.findings?.map((finding, index) => <p key={index} className="mt-2 text-amber-400">{finding.severity} — {finding.evidence}</p>)}
    </details>}
  </div>
}
