/**
 * Khối trạng thái Research nằm TRONG ô soạn tin (mockup `composer-toggle-toolbar-pill.html`,
 * `exit-mode-prompt.html`, `background-run-indicator.html`).
 *
 * Ba trạng thái loại trừ nhau:
 * 1. server vừa trả 409 `RESEARCH_EXIT_CHOICE_REQUIRED` ⇒ lời hỏi thoát (không có mặc định);
 * 2. chế độ đang bật ⇒ dải "Research đang bật · run … · bước …" + nút Tắt;
 * 3. chế độ đã tắt mà còn run chạy nền ⇒ chỉ báo run chạy nền (kèm báo khi run xong).
 *
 * Mọi chữ lấy từ `research.*`; component không viết cứng tiếng Việt.
 */
import { useState } from 'react'
import { Microscope, Loader2, Pause, X } from 'lucide-react'
import { useT, type TKey } from '../../../i18n/context'
import { useUiStore } from '../../../store/uiStore'
import { useResearchStore } from '../../../store/researchStore'
import {
  activeJob,
  jobIsRunningInBackground,
  runLabel,
  stepForPhase,
  type ResearchJob,
} from '../../../lib/researchMode'
import { formatClock } from './format'
import { STEP_LABEL_KEY } from './steps'

type T = (key: TKey, vars?: Record<string, string | number>) => string

function stepLabel(t: T, job: ResearchJob | null): string {
  if (!job) return ''
  return t(STEP_LABEL_KEY[stepForPhase(job.phase)])
}

/** Dải trạng thái khi chế độ đang bật. */
function ModeStrip({ job }: { job: ResearchJob | null }) {
  const t = useT()
  const setMode = useResearchStore((s) => s.setMode)
  const done = job && (job.status === 'completed' || job.status === 'cancelled')
  return (
    <div
      data-testid="research-mode-strip"
      className="mb-2 flex items-center gap-2 rounded-lg border border-brand/30 bg-brand/5 px-2 py-1.5 text-[11px] text-brand"
    >
      <Microscope className="size-3 shrink-0" />
      <span className="font-medium">{t('research.stripRunning')}</span>
      {job && (
        <span className="truncate font-mono text-[10px] text-muted" title={job.researchId}>
          {done
            ? t('research.stripDone', { id: runLabel(job.researchId) })
            : t('research.stripRun', { id: runLabel(job.researchId), step: stepLabel(t, job) })}
        </span>
      )}
      <button
        type="button"
        data-testid="research-mode-strip-off"
        onClick={() => void setMode(false, 'toggle')}
        className="ml-auto shrink-0 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
      >
        {t('research.turnOff')}
      </button>
    </div>
  )
}

/** Lời hỏi thoát chế độ — neo ngay trên ô nhập, hai lựa chọn không có mặc định. */
function ExitPrompt() {
  const t = useT()
  const exitChoice = useResearchStore((s) => s.exitChoice)
  const jobs = useResearchStore((s) => s.jobs)
  const mode = useResearchStore((s) => s.mode)
  const resolveExit = useResearchStore((s) => s.resolveExit)
  const clearExitChoice = useResearchStore((s) => s.clearExitChoice)
  const dismissPrompt = useResearchStore((s) => s.dismissPrompt)
  const job = activeJob(jobs, exitChoice?.prompt.researchId || mode.activeRunId)
  if (!exitChoice) return null
  // Luật "không mặc định": chỉ vẽ `background` khi server còn mời nó. Khi
  // `background_runs_enabled()` tắt, server ép `'pause'` (không tạo lời hỏi này), nhưng nếu một lời
  // hỏi cũ chỉ còn `pause` thì giao diện cũng chỉ được hiện `pause`.
  const options = exitChoice.prompt.questions[0]?.options ?? []
  const showBackground = options.length === 0 || options.some((option) => option.id === 'background')
  return (
    <div
      data-testid="research-exit-prompt"
      role="alertdialog"
      aria-label={t('research.exitTitle')}
      className="mb-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px]"
    >
      <p className="font-medium text-amber-300">{t('research.exitTitle')}</p>
      {job ? (
        <p className="mt-0.5 text-muted">
          {t('research.exitBody', {
            id: runLabel(job.researchId),
            step: stepLabel(t, job),
            used: formatClock(job.usedSeconds),
            budget: formatClock(job.budgetSeconds),
            sources: job.evidence.length,
          })}
        </p>
      ) : (
        <p className="mt-0.5 text-muted">{exitChoice.prompt.questions[0]?.text ?? ''}</p>
      )}
      <div className="mt-1.5 space-y-1">
        <button
          type="button"
          data-testid="research-exit-pause"
          onClick={() => void resolveExit('pause')}
          className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand cursor-pointer"
        >
          <span className="font-medium text-fg">{t('research.exitPause')}</span>
          <span className="ml-1 text-muted">{t('research.exitPauseHint')}</span>
        </button>
        {showBackground && (
          <button
            type="button"
            data-testid="research-exit-background"
            onClick={() => void resolveExit('background')}
            className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand cursor-pointer"
          >
            <span className="font-medium text-fg">{t('research.exitBackground')}</span>
            <span className="ml-1 text-muted">{t('research.exitBackgroundHint')}</span>
          </button>
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <button
          type="button"
          data-testid="research-exit-cancel"
          onClick={() => {
            // Đóng lời hỏi ở SERVER rồi mới ẩn: nếu chỉ ẩn cục bộ, vòng đồng bộ kế tiếp lại suy ra nó
            // từ lời hỏi còn mở và thẻ bật lại ngay.
            void dismissPrompt(exitChoice.prompt.promptId)
            clearExitChoice()
          }}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('research.exitCancel')}
        </button>
        <span className="text-muted">{t('research.exitNoDefault')}</span>
      </div>
    </div>
  )
}

/** Chỉ báo run chạy nền khi chế độ đã tắt. */
function BackgroundStrip({ job }: { job: ResearchJob }) {
  const t = useT()
  const [hidden, setHidden] = useState<string | null>(null)
  const showTab = useUiStore((s) => s.showTab)
  const updateJob = useResearchStore((s) => s.updateJob)
  if (hidden === job.researchId) return null
  const finished = job.status === 'completed'
  return (
    <div
      data-testid="research-background-strip"
      className={`mb-2 flex items-center gap-2 rounded-lg border px-2 py-1.5 text-[11px] ${
        finished ? 'border-emerald-500/40 bg-emerald-500/5 text-emerald-300' : 'border-line bg-panel2 text-fg'
      }`}
    >
      {finished ? <Microscope className="size-3 shrink-0" /> : <Loader2 className="size-3 shrink-0 animate-spin" />}
      <span className="font-medium">
        {finished ? t('research.backgroundDone', { id: runLabel(job.researchId) }) : t('research.backgroundRunning')}
      </span>
      <span className="truncate text-muted">
        {finished
          ? t('research.backgroundDoneDetail', {
              version: job.dossier?.version ?? 0,
              used: formatClock(job.usedSeconds),
              sources: job.evidence.length,
            })
          : t('research.stripRun', { id: runLabel(job.researchId), step: stepLabel(t, job) })}
      </span>
      <div className="ml-auto flex shrink-0 items-center gap-1.5">
        <button
          type="button"
          onClick={() => showTab('research')}
          className="rounded border border-line px-1.5 py-0.5 transition hover:border-brand cursor-pointer"
        >
          {t('research.openPanel')}
        </button>
        {!finished && (
          <button
            type="button"
            onClick={() => void updateJob(job.researchId, { action: 'pause', revision: job.revision })}
            className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 transition hover:border-brand cursor-pointer"
          >
            <Pause className="size-3" />
            {t('research.pauseRun')}
          </button>
        )}
        <button
          type="button"
          data-testid="research-background-hide"
          aria-label={t('research.hide')}
          onClick={() => setHidden(job.researchId)}
          className="text-muted transition hover:text-fg cursor-pointer"
        >
          <X className="size-3" />
        </button>
      </div>
    </div>
  )
}

/** Toàn bộ khối trạng thái trong ô soạn tin. */
export function ResearchComposerStatus() {
  const mode = useResearchStore((s) => s.mode)
  const jobs = useResearchStore((s) => s.jobs)
  const exitChoice = useResearchStore((s) => s.exitChoice)
  if (exitChoice) return <ExitPrompt />
  if (mode.on) return <ModeStrip job={activeJob(jobs, mode.activeRunId)} />
  const background = jobs.find(jobIsRunningInBackground)
  if (background) return <BackgroundStrip job={background} />
  return null
}

/** Thẻ thông báo trong dòng hội thoại khi chế độ đang bật (§4.2) — luôn nói cách thoát. */
export function ResearchModeBanner() {
  const t = useT()
  const mode = useResearchStore((s) => s.mode)
  const jobs = useResearchStore((s) => s.jobs)
  const setMode = useResearchStore((s) => s.setMode)
  if (!mode.on) return null
  const job = activeJob(jobs, mode.activeRunId)
  return (
    <div
      data-testid="research-mode-banner"
      className="mb-2 flex items-start gap-2 rounded-lg border border-brand/30 bg-brand/5 px-2.5 py-2 text-[11px] text-brand"
    >
      <Microscope className="mt-0.5 size-3 shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{t('research.bannerTitle')}</p>
        <p className="text-muted">{t('research.bannerBody', { id: runLabel(mode.activeRunId || job?.researchId || '') })}</p>
      </div>
      <button
        type="button"
        onClick={() => void setMode(false, 'toggle')}
        className="shrink-0 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
      >
        {t('research.bannerExit')}
      </button>
    </div>
  )
}
