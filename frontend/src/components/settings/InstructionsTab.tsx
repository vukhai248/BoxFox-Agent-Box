import { useEffect, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, Check, ClipboardCopy, Info, RotateCw, Save, Trash2, X } from 'lucide-react'
import { useT } from '../../i18n/context'
import {
  OWNER_DIRECTIVES_HEADING,
  cachedRuntimeInfo,
  formatCount,
  instructionsLimit,
  instructionsTone,
  loadRuntimeInfo,
} from '../../lib/ownerDirectives'
import { useOwnerSettingsStore } from '../../store/ownerSettingsStore'
import { useSessionRecordStore } from '../../store/sessionRecordStore'

/**
 * Bốn ví dụ của thiết kế: chèn thẳng vào ô tại vị trí con trỏ (không phải danh sách tài liệu giả).
 * Đây là văn bản người dùng sẽ gửi cho agent, nên viết thẳng tiếng Anh như bản vẽ.
 */
const EXAMPLES: Array<{ key: 'exampleTests' | 'exampleReadOnly' | 'exampleAsk' | 'exampleLanguage'; text: string }> = [
  { key: 'exampleTests', text: "Run the repository's own test command before you report a change as done, and paste the result." },
  { key: 'exampleReadOnly', text: 'Never edit anything under vendor/ or code-reference/: treat both as read-only.' },
  { key: 'exampleAsk', text: 'Ask me before you delete files, drop a database or push to a remote branch.' },
  { key: 'exampleLanguage', text: 'Write to me in English.' },
]

const clock = (value: number) =>
  new Date(value).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })

/** Đếm theo điểm mã để khớp `len()` của Python ở phía harness. */
const codePoints = (value: string) => [...value].length

function CardHead({ icon, title, tail }: { icon?: ReactNode; title: string; tail?: string }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      {icon ? <span className="text-muted">{icon}</span> : null}
      <h2 className="text-xs font-bold text-fg">{title}</h2>
      {tail ? <span className="text-[11px] text-muted">{tail}</span> : null}
    </div>
  )
}

export function InstructionsTab() {
  const t = useT()
  const instructions = useOwnerSettingsStore((s) => s.instructions)
  const revision = useOwnerSettingsStore((s) => s.revision)
  const draft = useOwnerSettingsStore((s) => s.draft)
  const status = useOwnerSettingsStore((s) => s.status)
  const error = useOwnerSettingsStore((s) => s.error)
  const loadError = useOwnerSettingsStore((s) => s.loadError)
  const loaded = useOwnerSettingsStore((s) => s.loaded)
  const loadedAt = useOwnerSettingsStore((s) => s.loadedAt)
  const setDraft = useOwnerSettingsStore((s) => s.setDraft)
  const load = useOwnerSettingsStore((s) => s.load)
  const save = useOwnerSettingsStore((s) => s.save)
  const discard = useOwnerSettingsStore((s) => s.discard)
  const reset = useOwnerSettingsStore((s) => s.reset)
  const isDirty = draft !== instructions

  const latestRecordId = useSessionRecordStore((s) => s.order[s.order.length - 1])
  const latestRecord = useSessionRecordStore((s) => (latestRecordId ? s.records[latestRecordId] : undefined))

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!cachedRuntimeInfo()) void loadRuntimeInfo().then(() => setTick((n) => n + 1))
    if (!useOwnerSettingsStore.getState().loaded) load().catch(() => undefined)
  }, [load])

  const info = cachedRuntimeInfo()
  const limit = instructionsLimit(info)
  const used = codePoints(draft)
  const tone = instructionsTone(used, limit)
  const warnAt = Math.min(11000, Math.max(0, limit - 1000))
  const canSave = isDirty && !(draft === '' && instructions === '') && status !== 'saving'
  const isEmptyState = !loaded && !loadError && !instructions && !draft

  const insertExample = (snippet: string) => {
    const element = textareaRef.current
    const start = element?.selectionStart ?? draft.length
    const end = element?.selectionEnd ?? draft.length
    const lead = start > 0 && !draft.slice(0, start).endsWith('\n') ? '\n' : ''
    const inserted = `${lead}${snippet}`
    setDraft(`${draft.slice(0, start)}${inserted}${draft.slice(end)}`)
    requestAnimationFrame(() => {
      element?.focus()
      element?.setSelectionRange(start + inserted.length, start + inserted.length)
    })
  }

  const copyDraft = () => {
    void navigator.clipboard?.writeText(draft)
  }

  const counterClass =
    tone === 'over' ? 'text-rose-600 dark:text-rose-400 font-semibold' : tone === 'warn' ? 'text-amber-700 dark:text-amber-300 font-medium' : 'text-muted'

  return (
    <div className="p-8 max-w-4xl select-text">
      <div className="mb-4 flex items-start gap-3">
        <div>
          <h1 className="text-lg font-bold mb-1 text-fg">{t('instructions.title')}</h1>
          <p className="text-xs text-muted">{t('instructions.subtitle')}</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {isDirty ? (
            <span
              data-testid="settings-instructions-dirty"
              className="rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-amber-700 dark:text-amber-300"
            >
              {t('instructions.unsaved')}
            </span>
          ) : null}
          {status === 'failed' ? (
            <span
              data-testid="settings-instructions-failed"
              className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-rose-600 dark:text-rose-400"
            >
              {t('instructions.notSaved')}
            </span>
          ) : null}
        </div>
      </div>

      {/* Chỉ dẫn áp dụng ở đâu — đọc từ runtime, không phải lời hứa của trang này. */}
      <div className="rounded-xl border border-line bg-panel p-5">
        <CardHead
          icon={<Info className="size-3.5" />}
          title={t('instructions.appliesTitle')}
          tail={t('instructions.appliesTail')}
        />
        <ul className="space-y-2 text-[11px] text-muted">
          <li className="flex gap-2">
            <Check className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
            <span>
              <b className="text-fg">{t('instructions.appliesEvery')}</b> {t('instructions.appliesEveryBody')}
            </span>
          </li>
          <li className="flex gap-2">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
            <span>
              <b className="text-fg">{t('instructions.appliesRoles')}</b> {t('instructions.appliesRolesBody')}
            </span>
          </li>
          <li className="flex gap-2">
            <RotateCw className="mt-0.5 size-3.5 shrink-0 text-[#b45309]" />
            <span>
              <b className="text-fg">{t('instructions.appliesRunning')}</b> {t('instructions.appliesRunningBody')}
            </span>
          </li>
        </ul>
      </div>

      {/* Ô nhập thật: có value, có onChange, có testid — gõ là store đổi. */}
      <div className="mt-4 rounded-xl border border-line bg-panel p-5">
        <CardHead title={t('instructions.ownerTitle')} tail={t('instructions.ownerTail')} />
        <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-wide text-muted" htmlFor="owner-directives">
          {t('instructions.editorLabel')}
        </label>
        <textarea
          id="owner-directives"
          ref={textareaRef}
          data-testid="settings-instructions"
          aria-label={t('instructions.editorLabel')}
          aria-describedby="owner-directives-counter"
          aria-busy={status === 'saving'}
          rows={8}
          value={draft}
          disabled={!loaded}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t('instructions.editorPlaceholder')}
          className="w-full rounded-md border border-line bg-panel2 p-3 text-xs text-fg outline-hidden focus:border-brand font-mono leading-relaxed disabled:opacity-60"
        />
        <div className="mt-2 flex items-center gap-2 text-[11px]">
          <span id="owner-directives-counter" data-testid="settings-instructions-counter" data-tone={tone} className={counterClass}>
            {t('instructions.counter', { n: formatCount(used), limit: formatCount(limit) })}
          </span>
          <span className="text-muted">· {t('instructions.storedAsTyped')}</span>
          <span className="flex-1" />
          <button
            type="button"
            data-testid="settings-instructions-copy"
            onClick={copyDraft}
            className="flex items-center gap-1 text-muted transition hover:text-fg cursor-pointer"
          >
            <ClipboardCopy className="size-3" />
            {t('instructions.copy')}
          </button>
          <button
            type="button"
            data-testid="settings-instructions-clear"
            onClick={reset}
            className="flex items-center gap-1 text-muted transition hover:text-fg cursor-pointer"
          >
            <X className="size-3" />
            {t('instructions.clear')}
          </button>
        </div>
        <p className="mt-2 text-[11px] leading-4 text-muted">
          {t('instructions.counterHint', { limit: formatCount(limit), warn: formatCount(warnAt) })}
        </p>
        {tone === 'over' ? (
          <p data-testid="settings-instructions-overcut" className="mt-2 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-[11px] leading-4 text-rose-700 dark:text-rose-300">
            <b>{t('instructions.overCutTitle', { limit: formatCount(limit) })}</b> {t('instructions.overCutBody')}
          </p>
        ) : null}
        {loadError ? (
          <div data-testid="settings-instructions-load-failed" className="mt-3 rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-[11px] leading-4 text-rose-700 dark:text-rose-300">
            <b>{t('instructions.loadFailedTitle')}</b> {t('instructions.loadFailedBody')}
            <span className="mt-1 block font-mono">{loadError}</span>
            <button type="button" onClick={() => void load().catch(() => undefined)} className="mt-2 rounded-md border border-line bg-panel px-2 py-1 text-[11px] text-fg cursor-pointer">
              {t('instructions.reload')}
            </button>
          </div>
        ) : null}
      </div>

      {/* Ví dụ: chèn tại con trỏ. */}
      <div className="mt-4 rounded-xl border border-line bg-panel p-5">
        <CardHead title={t('instructions.examplesTitle')} tail={t('instructions.examplesTail')} />
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <button
              key={example.key}
              type="button"
              onClick={() => insertExample(example.text)}
              className="rounded-full border border-line bg-panel2 px-3 py-1 text-[11px] text-fg transition hover:border-brand/40 cursor-pointer"
            >
              {t(`instructions.${example.key}`)}
            </button>
          ))}
        </div>
      </div>

      {/* Hàng lưu: Save / Discard / Reset + biên nhận. */}
      <div className="mt-4 flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          data-testid="settings-instructions-save"
          onClick={() => void save()}
          disabled={!canSave}
          aria-busy={status === 'saving'}
          className="flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-brandfg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
        >
          <Save className="size-3.5" />
          {t('instructions.save')}
        </button>
        <button
          type="button"
          data-testid="settings-instructions-discard"
          onClick={discard}
          disabled={!isDirty || status === 'saving'}
          className="rounded-md border border-line bg-panel px-3 py-1.5 text-xs text-fg transition hover:border-brand/40 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer"
        >
          {t('instructions.discard')}
        </button>
        <button
          type="button"
          data-testid="settings-instructions-reset"
          onClick={reset}
          className="flex items-center gap-1.5 rounded-md border border-rose-500/40 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-600 dark:text-rose-400 transition hover:border-rose-500/60 cursor-pointer"
        >
          <Trash2 className="size-3.5" />
          {t('instructions.reset')}
        </button>
        <span className="flex-1" />
        <span aria-live="polite" data-testid="settings-instructions-receipt" className="text-[11px] text-muted">
          {status === 'saving'
            ? t('instructions.saving')
            : loadedAt
              ? t('instructions.receipt', { time: clock(loadedAt), n: String(revision) })
              : null}
        </span>
      </div>
      {status === 'saving' ? (
        <p className="mt-1.5 text-[11px] text-muted">
          {t('instructions.savingDetail', { count: formatCount(used), from: String(revision), to: String(revision + 1) })}
        </p>
      ) : null}
      {status === 'saved' ? (
        <p className="mt-1.5 text-[11px] text-muted">
          {t('instructions.receiptFresh', { time: clock(loadedAt ?? Date.now()) })} ·{' '}
          {t('instructions.revisionDetail', { n: String(revision), count: formatCount(codePoints(instructions)) })}
        </p>
      ) : null}
      {status === 'failed' ? (
        <div data-testid="settings-instructions-save-failed" className="mt-3 rounded-xl border border-rose-500/30 bg-rose-500/10 p-4">
          <p className="text-xs font-semibold text-rose-700 dark:text-rose-300">{t('instructions.saveFailed')}</p>
          <p className="mt-1 text-[11px] leading-4 text-rose-700 dark:text-rose-300">
            {t('instructions.saveFailedBody', { error: error ?? '', revision: String(revision) })}
          </p>
          <div className="mt-2 flex gap-2">
            <button
              type="button"
              data-testid="settings-instructions-retry"
              onClick={() => void save()}
              className="rounded-md border border-line bg-panel px-2.5 py-1 text-[11px] text-fg cursor-pointer"
            >
              {t('instructions.retry')}
            </button>
            <button
              type="button"
              data-testid="settings-instructions-copy-text"
              onClick={copyDraft}
              className="rounded-md border border-line bg-panel px-2.5 py-1 text-[11px] text-fg cursor-pointer"
            >
              {t('instructions.copyText')}
            </button>
            <button
              type="button"
              onClick={discard}
              className="rounded-md border border-line bg-panel px-2.5 py-1 text-[11px] text-fg cursor-pointer"
            >
              {t('instructions.discard')}
            </button>
          </div>
        </div>
      ) : null}

      {isEmptyState ? (
        <p data-testid="settings-instructions-empty" className="mt-3 text-[11px] leading-4 text-muted">
          <b className="text-fg">{t('instructions.emptyTitle')}</b> {t('instructions.emptyBody')} {t('instructions.emptySaveHint')}
        </p>
      ) : null}

      {/* Chat đang chạy: đọc từ sổ ghi phiên, không đoán. */}
      <div className="mt-5 rounded-xl border border-line bg-panel p-5">
        <CardHead title={t('instructions.thisChatTitle')} tail={t('instructions.thisChatTail')} />
        {latestRecord ? (
          <>
            {latestRecord.directivesSkipped ? (
              <p data-testid="settings-instructions-directives-skipped" className="mb-1 text-[11px] text-amber-700 dark:text-amber-300">
                {t('instructions.directivesSkipped', { error: latestRecord.directivesSkipped })}
              </p>
            ) : null}
            <p data-testid="settings-instructions-this-chat" className="text-[11px] text-fg">
              {t('instructions.thisChatBody', {
                id: latestRecord.sessionId.slice(0, 8),
                time: clock(latestRecord.startedAt),
                count: formatCount(latestRecord.instructionsChars),
              })}
            </p>
            <p className="mt-1 text-[11px] leading-4 text-muted">{t('instructions.thisChatHint')}</p>
            {latestRecord.instructionsChars > 0 ? (
              <span
                data-testid="settings-instructions-in-use"
                className="mt-2 inline-block rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-brand"
              >
                {t('instructions.inUse')}
              </span>
            ) : null}
          </>
        ) : (
          <p data-testid="settings-instructions-not-recorded" className="text-[11px] text-muted">
            {t('instructions.thisChatNotRecorded')}
          </p>
        )}
      </div>

      {/* Văn bản nằm ở đâu trong prompt — chuỗi lấy từ hằng số dùng chung với harness. */}
      <div className="mt-4 rounded-xl border border-line bg-panel p-5">
        <CardHead title={t('instructions.promptTitle')} tail={t('instructions.promptTail')} />
        <pre className="overflow-x-auto rounded-lg border border-line bg-panel2 p-3 text-[11px] leading-4 text-muted font-mono">
{`{agent identity — read from AGENT.md}
=== ASSIGNED ROLE: ORCHESTRATOR ===
{role instructions — managed by the harness}
=== ENABLED SKILLS (Load full content via skill_view before executing complex workflows) ===
- codebase-inspection: map a repository and locate symbols without modifying files.
- systematic-debugging: reproduce a failure before changing code.
- test-driven-development: write the failing test first, then the fix.`}
          <span data-testid="settings-instructions-tail" className="mt-1 block rounded bg-brand/10 px-1 text-fg">
            {OWNER_DIRECTIVES_HEADING}
          </span>
          <span className="block px-1 text-fg">
            {codePoints(draft) ? draft.split('\n').slice(0, 2).join('\n') : t('instructions.emptyTitle')}
          </span>
        </pre>
        <p className="mt-2 text-[11px] leading-4 text-muted">{t('instructions.promptHint')}</p>
      </div>
    </div>
  )
}
