/**
 * Thẻ phạm vi (mockup `scope-card-blocking.html` và `scope-card-proceeding.html`).
 *
 * Hai biến thể, cùng một dữ liệu `scope` (store ở `research_jobs.state.scope`):
 * - **chặn**: còn câu hỏi chặn chưa trả lời (run ở `needs_user`) ⇒ tiêu đề "Chờ bạn trả lời — N điểm
 *   mơ hồ", kèm lời hỏi nhiều câu và hai nút "Bắt đầu" / "Sửa phạm vi";
 * - **đang chạy**: tiêu đề "Yêu cầu đủ rõ — research đã bắt đầu, không chờ xác nhận", mỗi dòng có "Sửa".
 *
 * Hai danh sách LUÔN tách bạch: "Bạn đã xác nhận" lấy mục `status='confirmed'`, "Giả định của agent"
 * lấy mục `status='assumed'` (bảng 4.8). Mỗi lần sửa gửi kèm `revision` đang thấy để server từ chối
 * khi thẻ đã đổi dưới chân người dùng.
 *
 * F1: mỗi dòng có giá trị HIỂN THỊ (`value`) và giá trị THÔ để sửa (`editValue`) — ô sửa KHÔNG bao
 * giờ nạp chữ đã định dạng rồi phân tích ngược. Dòng ngân sách đi qua `action:'budget'` (trần cứng
 * được thực thi) chứ không nhét `budget.proposedSeconds` vào patch phạm vi.
 */
import { useState, type ReactNode } from 'react'
import { Pencil } from 'lucide-react'
import { useT, type TKey } from '../../../i18n/context'
import { useResearchStore } from '../../../store/researchStore'
import {
  assumedItems,
  blockingOpenQuestions,
  confirmedItems,
  jobIsSuspendable,
  jobStatusKey,
  jobStatusTone,
  runLabel,
  STATUS_TONE_CLASS,
  type ResearchJob,
  type ResearchPrompt,
  type ResearchScope,
} from '../../../lib/researchMode'
import { formatClock, formatMinutes } from './format'
import { ResearchPromptCard } from './ResearchPromptCard'

/** Tốc độ khảo sát hợp lệ của server (`research_evidence.TIME_VELOCITIES`). */
const VELOCITIES = ['very-fast', 'fast', 'medium', 'slow'] as const
const VELOCITY_KEY: Record<string, TKey> = {
  'very-fast': 'research.velocityVeryFast',
  fast: 'research.velocityFast',
  medium: 'research.velocityMedium',
  slow: 'research.velocitySlow',
}
/** Độ sâu hợp lệ (`scope.depth`). */
const DEPTHS = ['quick', 'standard', 'deep'] as const
const DEPTH_KEY: Record<string, TKey> = {
  quick: 'research.depthQuick',
  standard: 'research.depthStandard',
  deep: 'research.depthDeep',
}
/** Mức của thẻ (`scope.tier`). */
const TIERS = [1, 2, 3] as const

const SELECT_CLASS =
  'w-full rounded border border-line bg-bg px-1.5 py-0.5 text-[11px] text-fg outline-hidden focus:border-brand'

/**
 * Một dòng sửa được: nhãn + giá trị + nút "Sửa" mở ô nhập ngay tại chỗ.
 *
 * `value` là chữ NGƯỜI ĐỌC thấy; `editValue` là dữ liệu MÁY đọc được nạp vào ô sửa. Hai thứ này phải
 * khác nhau: nếu nạp `value` vào ô sửa thì nhãn đã định dạng sẽ bị phân tích ngược thành giá trị rác.
 */
function EditableRow({
  row,
  label,
  value,
  editValue,
  multiline,
  onSave,
  editor,
}: {
  /** Định danh dòng (`data-row`) để bài kiểm chọn đúng ô. */
  row: string
  label: string
  value: string
  editValue: string
  multiline?: boolean
  onSave: (next: string) => Promise<boolean>
  /** Điều khiển tuỳ biến (chọn tốc độ/mức, số phút…) thay cho ô chữ. */
  editor?: (draft: string, setDraft: (next: string) => void) => ReactNode
}) {
  const t = useT()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(editValue)
  const [busy, setBusy] = useState(false)

  async function save() {
    setBusy(true)
    const ok = await onSave(draft)
    setBusy(false)
    if (ok) setEditing(false)
  }

  return (
    <div data-row={row} className="flex items-start gap-2 border-b border-line/60 py-1 last:border-b-0">
      <span className="w-28 shrink-0 text-muted">{label}</span>
      {editing ? (
        <div className="min-w-0 flex-1">
          {editor ? (
            editor(draft, setDraft)
          ) : multiline ? (
            <textarea
              aria-label={label}
              rows={3}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="w-full rounded border border-line bg-bg px-1.5 py-0.5 text-[11px] text-fg outline-hidden focus:border-brand"
            />
          ) : (
            <input
              aria-label={label}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className="w-full rounded border border-line bg-bg px-1.5 py-0.5 text-[11px] text-fg outline-hidden focus:border-brand"
            />
          )}
          <div className="mt-0.5 flex gap-1.5">
            <button
              type="button"
              disabled={busy}
              data-testid="research-scope-save"
              onClick={() => void save()}
              className="rounded bg-zinc-100 px-2 py-0.5 text-zinc-900 transition hover:bg-white disabled:opacity-40 cursor-pointer"
            >
              {t('research.save')}
            </button>
            <button
              type="button"
              onClick={() => {
                setDraft(editValue)
                setEditing(false)
              }}
              className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
            >
              {t('research.cancel')}
            </button>
          </div>
        </div>
      ) : (
        <span className="min-w-0 flex-1 text-fg">{value || '—'}</span>
      )}
      {!editing && (
        <button
          type="button"
          data-testid="research-scope-edit"
          onClick={() => {
            setDraft(editValue)
            setEditing(true)
          }}
          className="inline-flex shrink-0 items-center gap-1 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          <Pencil className="size-2.5" />
          {t('research.edit')}
        </button>
      )}
    </div>
  )
}

function ScopeEntryList({ title, hint, items, empty }: {
  title: string
  hint?: string
  items: { text: string; status: string }[]
  empty: string
}) {
  return (
    <section className="mt-1.5">
      <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">
        {title}
        {hint && <span className="ml-1 normal-case">{hint}</span>}
      </h4>
      {items.length === 0 ? (
        <p className="text-muted">{empty}</p>
      ) : (
        <ul className="mt-0.5 space-y-0.5">
          {items.map((item, index) => (
            <li key={`${item.text}-${index}`} className="flex items-start gap-1.5 text-fg">
              <span className="text-muted">•</span>
              <span>{item.text}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

function depthLabel(t: (key: TKey, vars?: Record<string, string | number>) => string, tier: number, depth: string): string {
  const key: TKey = depth === 'quick' ? 'research.depthQuick' : depth === 'deep' ? 'research.depthDeep' : 'research.depthStandard'
  return `${t('research.depthValue', { tier, depth: t(key) })}${tier >= 2 ? ` · ${t('research.critiqueFromTier2')}` : ''}`
}

function windowLabel(t: (key: TKey, vars?: Record<string, string | number>) => string, scope: ResearchScope): string {
  const days = scope.window?.days ?? null
  if (!days) return t('research.timeUnlimited')
  return t('research.timeRecent', { months: Math.max(1, Math.round(days / 30)) })
}

export function ScopeCard({
  job,
  scope,
  prompt,
}: {
  job: ResearchJob
  scope: ResearchScope
  /** Lời hỏi chặn đang mở của run (nếu có) — hiện ngay trong thẻ khi thẻ đang chặn. */
  prompt?: ResearchPrompt | null
}) {
  const t = useT()
  const updateJob = useResearchStore((s) => s.updateJob)
  const blocking = blockingOpenQuestions(scope)
  const blocked = blocking.length > 0 || job.status === 'needs_user'
  const suspendable = jobIsSuspendable(job)
  const budget = scope.budget
  const budgetText = budget?.proposedSeconds
    ? `${t('research.budgetProposed', { minutes: formatMinutes(budget.proposedSeconds) })}${
        budget.hardCeilingSeconds
          ? ` ${t('research.budgetCeiling', { tier: scope.tier, minutes: formatMinutes(budget.hardCeilingSeconds) })}`
          : ''
      }`
    : '—'
  const used = job.usedSeconds > 0 ? ` ${t('research.budgetUsed', { used: formatClock(job.usedSeconds) })}` : ''
  // Trần cứng ĐƯỢC THỰC THI là `state.budgetSeconds` (hàng job), không phải `scope.budget.proposedSeconds`.
  const capSeconds = job.budgetSeconds || budget?.proposedSeconds || 0
  const answered = scope.openQuestions.filter((item) => item.answer)

  const patch = (scopePatch: Record<string, unknown>) =>
    updateJob(job.researchId, { action: 'scope', revision: scope.revision, scope: scopePatch })

  return (
    <section
      data-testid="research-scope-card"
      data-variant={blocked ? 'blocking' : 'proceeding'}
      className="rounded-lg border border-line bg-panel p-2 text-[11px]"
    >
      <header className="flex items-center gap-2">
        <span className="font-medium text-fg">{t('research.scopeTitle', { id: runLabel(job.researchId) })}</span>
        <span className="rounded border border-line px-1 py-px text-[10px] text-muted">
          {t('research.rev', { n: scope.revision })}
        </span>
        <span
          data-testid="research-scope-status-badge"
          data-status={job.status}
          className={`ml-auto shrink-0 rounded px-1 py-px text-[10px] font-medium ${STATUS_TONE_CLASS[jobStatusTone(job)]}`}
        >
          {t(jobStatusKey(job))}
        </span>
      </header>
      <p className="mt-0.5 text-muted">
        {blocked
          ? t('research.scopeBlocking', { count: Math.max(1, blocking.length) })
          : t('research.scopeProceeding')}
      </p>

      {/* D-3 (§4.1 dòng ~210): run tạm dừng phải HỎI "Tiếp tục run X?" ngay trên thẻ trạng thái —
          run tạm dừng không tự chạy lại, người dùng phải bấm nút gửi `action:'resume'`. */}
      {suspendable && (
        <div
          data-testid="research-scope-resume-ask"
          className="mt-1.5 flex flex-wrap items-center gap-1.5 rounded border border-brand/30 bg-brand/5 px-2 py-1"
        >
          <span className="text-brand">{t('research.resumeAsk', { id: runLabel(job.researchId) })}</span>
          <button
            type="button"
            data-testid="research-scope-resume"
            onClick={() => void updateJob(job.researchId, { action: 'resume', revision: job.revision })}
            className="rounded bg-zinc-100 px-2 py-0.5 text-zinc-900 transition hover:bg-white cursor-pointer"
          >
            {t('research.resumeRun')}
          </button>
        </div>
      )}

      <div className="mt-1.5" data-testid="research-scope-rows">
        <EditableRow
          row="goal"
          label={t('research.fieldGoal')}
          value={scope.goal?.text ?? ''}
          editValue={scope.goal?.text ?? ''}
          multiline
          onSave={(text) => patch({ goal: { text, status: 'confirmed' } })}
        />
        <EditableRow
          row="questions"
          label={t('research.fieldQuestions')}
          value={`${t('research.questionsCount', { count: scope.questions.length })}${
            scope.questions.length ? `: ${scope.questions.map((item) => item.text).join(' · ')}` : ''
          }`}
          editValue={scope.questions.map((item) => item.text).join('\n')}
          multiline
          onSave={(text) => {
            // Mỗi DÒNG là một câu hỏi; giữ `id` cũ theo vị trí để server không dựng lại câu hỏi mới.
            const lines = text.split('\n').map((line) => line.trim()).filter(Boolean)
            return patch({
              questions: lines.map((line, index) => ({ id: scope.questions[index]?.id ?? `q${index + 1}`, text: line })),
            })
          }}
        />
        <EditableRow
          row="time"
          label={t('research.fieldTime')}
          value={windowLabel(t, scope)}
          editValue={scope.timePolicy?.velocity ?? ''}
          editor={(draft, setDraft) => (
            <select
              aria-label={t('research.fieldTime')}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className={SELECT_CLASS}
            >
              <option value="">{t('research.timeUnlimited')}</option>
              {VELOCITIES.map((velocity) => (
                <option key={velocity} value={velocity}>{t(VELOCITY_KEY[velocity])}</option>
              ))}
            </select>
          )}
          onSave={(text) => patch({ timePolicy: { velocity: text.trim().toLowerCase(), status: 'confirmed' } })}
        />
        <EditableRow
          row="depth"
          label={t('research.fieldDepth')}
          value={depthLabel(t, scope.tier, scope.depth)}
          // Hai lựa chọn của một dòng: `mức::độ sâu` (dấu `::` chỉ để gói hai giá trị trong một draft).
          editValue={`${scope.tier}::${scope.depth}`}
          editor={(draft, setDraft) => {
            const [tierRaw, depthRaw] = draft.split('::')
            return (
              <div className="flex gap-1.5">
                <select
                  aria-label={t('research.fieldTier')}
                  value={tierRaw}
                  onChange={(event) => setDraft(`${event.target.value}::${depthRaw ?? ''}`)}
                  className={SELECT_CLASS}
                >
                  {TIERS.map((tier) => (
                    <option key={tier} value={tier}>{t('research.tierOption', { tier })}</option>
                  ))}
                </select>
                <select
                  aria-label={t('research.fieldDepth')}
                  value={depthRaw}
                  onChange={(event) => setDraft(`${tierRaw}::${event.target.value}`)}
                  className={SELECT_CLASS}
                >
                  {DEPTHS.map((depth) => (
                    <option key={depth} value={depth}>{t(DEPTH_KEY[depth])}</option>
                  ))}
                </select>
              </div>
            )
          }}
          onSave={(text) => {
            const [tierRaw, depthRaw] = text.split('::')
            const tier = Number(tierRaw)
            const body: Record<string, unknown> = {}
            if (Number.isFinite(tier) && tier > 0) body.tier = tier
            if (depthRaw) body.depth = depthRaw
            return Object.keys(body).length ? patch(body) : Promise.resolve(false)
          }}
        />
        <EditableRow
          row="budget"
          label={t('research.fieldBudget')}
          value={`${budgetText}${used}`}
          editValue={String(Math.max(1, Math.round(capSeconds / 60)))}
          editor={(draft, setDraft) => (
            <input
              type="number"
              min={1}
              max={1440}
              aria-label={t('research.fieldBudget')}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              className={SELECT_CLASS}
            />
          )}
          onSave={(text) => {
            const minutes = Number(text)
            const seconds = Math.round(minutes * 60)
            // `action:'budget'` là đường DUY NHẤT đổi trần cứng được thực thi (60..86400 giây).
            if (!Number.isFinite(minutes) || minutes <= 0 || seconds < 60 || seconds > 86400) return Promise.resolve(false)
            return updateJob(job.researchId, { action: 'budget', budgetSeconds: seconds })
          }}
        />
        <EditableRow
          row="outputs"
          label={t('research.fieldOutputs')}
          value={scope.outputs.join(' · ')}
          editValue={scope.outputs.join('\n')}
          multiline
          onSave={(text) => patch({ outputs: text.split('\n').map((line) => line.trim()).filter(Boolean) })}
        />
      </div>

      {scope.timePolicy?.note && <p className="mt-1 text-amber-300">{scope.timePolicy.note}</p>}

      <ScopeEntryList
        title={t('research.confirmedTitle')}
        items={confirmedItems(scope)}
        empty={t('research.confirmedEmpty')}
      />
      <ScopeEntryList
        title={t('research.assumedTitle')}
        hint={t('research.assumedHint')}
        items={assumedItems(scope)}
        empty={t('research.assumedEmpty')}
      />

      {/* F8: câu hỏi mở đã được trả lời phải hiện như một QUYẾT ĐỊNH, không nằm im trong dữ liệu. */}
      {answered.length > 0 && (
        <section className="mt-1.5" data-testid="research-scope-answered">
          <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.promptAnswered')}</h4>
          <ul className="mt-0.5 space-y-0.5">
            {answered.map((item) => (
              <li key={item.id} className="flex items-start gap-1.5 text-fg">
                <span className="text-muted">•</span>
                <span><span className="text-muted">{item.text}: </span>{item.answer}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {blocked && (
        <div className="mt-1.5">
          {prompt && prompt.status === 'open' ? (
            <ResearchPromptCard prompt={prompt} />
          ) : (
            <p className="text-muted">{t('research.promptNote')}</p>
          )}
        </div>
      )}

      <footer className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted">
        {!blocked && !suspendable && (
          <>
            <span>{t('research.applyNextWave')}</span>
            <button
              type="button"
              data-testid="research-run-pause"
              onClick={() => void updateJob(job.researchId, { action: 'pause', revision: job.revision })}
              className="rounded border border-line px-1.5 py-0.5 transition hover:text-fg cursor-pointer"
            >
              {t('research.pauseRun')}
            </button>
            <span>{t('research.scopeOnly')}</span>
          </>
        )}
      </footer>
    </section>
  )
}
