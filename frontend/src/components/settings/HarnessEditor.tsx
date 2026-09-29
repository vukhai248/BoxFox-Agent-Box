import { useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { AlertTriangle, ChevronDown, ChevronUp, Lock, Plus } from 'lucide-react'
import { useHarnessStore } from '../../store/harnessStore'
import { useProviderStore } from '../../store/providerStore'
import { useUiStore } from '../../store/uiStore'
import { RUNTIME_INFO_UNAVAILABLE, useRuntimeInfoStore } from '../../store/runtimeInfoStore'
import type { RuntimeToolGroup } from '../../store/runtimeInfoStore'
import type { Harness, SubagentConfig } from '../../types/harness'
import { CustomCheckbox } from './CustomCheckbox'
import { HarnessDuplicateDialog } from './HarnessDuplicateDialog'
import { useT } from '../../i18n/context'

interface HarnessEditorProps {
  harnessId: string
}

/** Câu giải thích vì sao built-in bị khoá — đi kèm cả `title` lẫn `aria-describedby`. */
const LOCKED_REASON = 'Built-in harnesses are read-only. Duplicate and edit.'
const LOCKED_REASON_ID = 'builtin-locked-reason'

/** Mức thinking: '' là "Auto", để engine tự lấy mức đầu tiên mà model công bố. */
const THINKING_LEVELS = ['', 'low', 'medium', 'high', 'max']

/** Tên nhóm công cụ là chữ hiển thị, khoá `key` vẫn là dữ liệu thật của engine. */
const TOOL_GROUP_LABELS: Record<string, string> = {
  repositoryReading: 'Repository reading',
  skills: 'Skills',
  filesTerminal: 'Files & terminal',
  screenBrowser: 'Screen & browser',
  webResearch: 'Web research',
  delegationPlans: 'Delegation & plans',
  peerMesh: 'Peer mesh',
  workGraph: 'Work Graph',
  questionsApprovals: 'Questions & approvals',
}

const TOOL_GROUP_NOTES: Record<string, string> = {
  skills: "reads a skill's full text on demand",
  filesTerminal: 'off means the agent can only read',
  webResearch:
    'web_search · web_fetch run on the host and see the real Internet; the sandbox has none, so browser_use only reaches box-local pages.',
  peerMesh:
    "a child reads a peer's work stream and waits for the result it delivers; off means children cannot see each other",
  workGraph:
    'work_graph · work_run · work_ship — main plans, reviews and runs sub-agents as a DAG; off returns to the legacy slash-mode path.',
  questionsApprovals:
    'always on. The agent cannot be silenced on the things it must ask you about.',
}

function groupLabel(key: string): string {
  if (TOOL_GROUP_LABELS[key]) return TOOL_GROUP_LABELS[key]
  const spaced = key.replace(/([A-Z])/g, ' $1').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Nhãn model đang lưu, bỏ tiền tố định tuyến cho dễ đọc. */
function modelLabel(value: string): string {
  if (!value || value === 'default') return 'Default router / selected Single Model'
  if (value.startsWith('model:')) return value.slice('model:'.length)
  if (value.startsWith('alias:')) return value.slice('alias:'.length)
  return value
}

function harnessCopy(harness: Harness | undefined, harnessId: string): Harness {
  if (harness) return JSON.parse(JSON.stringify(harness)) as Harness
  return {
    id: harnessId,
    name: 'New Custom Harness',
    description: '',
    isBuiltIn: false,
    mainModel: 'default',
    subagents: [],
  }
}

function Card({ title, hint, badge, children }: { title: string; hint?: string; badge?: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-panel p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold text-fg">{title}</h2>
          {hint && <p className="mt-1 text-xs text-muted">{hint}</p>}
        </div>
        {badge && (
          <span className="rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-muted">
            {badge}
          </span>
        )}
      </div>
      <div className="mt-4 space-y-4">{children}</div>
    </section>
  )
}

export function HarnessEditor({ harnessId }: HarnessEditorProps) {
  const t = useT()

  const harnesses = useHarnessStore((s) => s.harnesses)
  const getHarnessById = useHarnessStore((s) => s.getHarnessById)
  const saveHarness = useHarnessStore((s) => s.saveHarness)
  const setHarnessTuning = useHarnessStore((s) => s.setHarnessTuning)
  const thinkingLevel = useHarnessStore((s) => s.thinkingLevel)
  const setThinkingLevel = useHarnessStore((s) => s.setThinkingLevel)

  const setEditingHarnessId = useUiStore((s) => s.setEditingHarnessId)
  // Luật tự mở tab: công tắc toàn cục, lưu trong localStorage cạnh `boxfox_theme`.
  const autoOpenTabs = useUiStore((s) => s.autoOpenTabs)
  const setAutoOpenTabs = useUiStore((s) => s.setAutoOpenTabs)
  const autoOpenOnlyWhenIdle = useUiStore((s) => s.autoOpenOnlyWhenIdle)
  const setAutoOpenOnlyWhenIdle = useUiStore((s) => s.setAutoOpenOnlyWhenIdle)

  const snapshot = useProviderStore((s) => s.snapshot)
  const providerError = useProviderStore((s) => s.error)
  const providerLoading = useProviderStore((s) => s.loading)
  const loadProviders = useProviderStore((s) => s.load)
  useEffect(() => {
    void loadProviders().catch(() => {})
  }, [loadProviders])

  const runtimeInfo = useRuntimeInfoStore((s) => s.info)
  const loadRuntimeInfo = useRuntimeInfoStore((s) => s.load)
  useEffect(() => {
    void loadRuntimeInfo()
  }, [loadRuntimeInfo])

  const initialHarness = getHarnessById(harnessId)
  const readOnly = Boolean(initialHarness?.isBuiltIn)

  const [form, setForm] = useState<Harness>(() => harnessCopy(initialHarness, harnessId))
  const [baseline, setBaseline] = useState(() => JSON.stringify(harnessCopy(initialHarness, harnessId)))
  const [nameError, setNameError] = useState(false)
  const [duplicateOpen, setDuplicateOpen] = useState(false)
  const [receipt, setReceipt] = useState<string | null>(null)
  const [expandedSubagents, setExpandedSubagents] = useState<Record<string, boolean>>({})

  // Đổi harness (kể cả sau khi nhân bản) thì nạp lại bản nháp từ record thật.
  useEffect(() => {
    const next = harnessCopy(useHarnessStore.getState().getHarnessById(harnessId), harnessId)
    setForm(next)
    setBaseline(JSON.stringify(next))
    setNameError(false)
  }, [harnessId])

  /**
   * Danh sách model lấy từ catalogue SỐNG của router (`/api/router/state`), mỗi
   * dòng mang đúng giá trị định tuyến `model:<connectionId>:<modelId>` — dạng duy
   * nhất router chạy được. Danh sách tĩnh cũ đã bỏ: nó lưu một tên hiển thị và
   * router trả `404 MODEL_NOT_FOUND`.
   */
  const modelChoices = useMemo(() => {
    const choices: { value: string; label: string }[] = []
    for (const connection of snapshot?.connections ?? []) {
      if (!connection.enabled || connection.discoveryState !== 'ready') continue
      for (const model of connection.models) {
        if (!model.enabled || model.health === 'unavailable') continue
        choices.push({ value: `model:${connection.id}:${model.id}`, label: `${connection.name} · ${model.name}` })
      }
    }
    for (const alias of snapshot?.aliases ?? []) {
      if (!alias.enabled) continue
      choices.push({ value: `alias:${alias.id}`, label: `${alias.name} · alias` })
    }
    return choices
  }, [snapshot])

  const catalogueLoaded = snapshot !== null
  const modelOutOfCatalogue = form.mainModel !== 'default' && !modelChoices.some((c) => c.value === form.mainModel)

  const limits = runtimeInfo?.limits ?? null
  const retry = runtimeInfo?.retry ?? null
  const allTools = runtimeInfo ? (runtimeInfo.tools.length > 0 ? runtimeInfo.tools : runtimeInfo.toolGroups.flatMap((g) => g.tools)) : []
  const toolsKnown = allTools.length > 0
  const toolsOn = form.tools ?? allTools
  const toolCount = toolsKnown ? toolsOn.length : null
  const enabledRoles = form.subagents.filter((s) => s.enabled).length
  const appendedPrompts = form.subagents.filter((s) => s.enabled && s.systemPromptAppended.trim().length > 0).length
  const dirty = JSON.stringify(form) !== baseline

  const handleSave = () => {
    if (!form.name.trim()) {
      setNameError(true)
      return
    }
    // Bước/thời gian/công cụ đi qua `setHarnessTuning` để store tự kẹp theo trần thật
    // của engine và tự bỏ những tên công cụ engine không biết.
    // `?? null` = XOÁ trường khi ô trống / khi bật lại đủ bộ công cụ: đó là cách
    // duy nhất quay về mặc định của engine sau khi đã đặt một con số (lỗi #3).
    const { maxSteps, deadlineSeconds, tools, ...identity } = form
    saveHarness(identity)
    setHarnessTuning(harnessId, {
      maxSteps: maxSteps ?? null,
      deadlineSeconds: deadlineSeconds ?? null,
      tools: tools ?? null,
    })
    const stored = useHarnessStore.getState().getHarnessById(harnessId)
    if (stored) {
      const next = harnessCopy(stored, harnessId)
      setForm(next)
      setBaseline(JSON.stringify(next))
    }
    setNameError(false)
  }

  const handleCancel = () => {
    setEditingHarnessId(null)
  }

  /** Nhân bản xong: mở bản sao nếu người dùng muốn, còn không thì nói rõ nó đang ở đâu. */
  const handleDuplicated = (newId: string, name: string, openInEditor: boolean) => {
    setDuplicateOpen(false)
    if (openInEditor) {
      setEditingHarnessId(newId)
      return
    }
    // Ở lại màn chỉ-đọc: biên nhận phải trả lời hai câu người dùng tự hỏi — bản gốc còn
    // nguyên không, và bản sao đã nắm quyền chưa. Biên nhận nằm ngay trên banner (không
    // phải cuối trang dài), nếu không nó vô hình với người vừa bấm `Duplicate`.
    setReceipt(
      `${name} created · built-in untouched. It is at the end of the Harness list, marked NEW, and is not in charge of any chat until you pick it there.`
    )
  }

  const handleModelChange = (modelName: string) => {
    setForm((f) => ({ ...f, mainModel: modelName, modelWarning: '' }))
  }

  const handleUpdateSubagent = (subId: string, updates: Partial<SubagentConfig>) => {
    setForm((f) => ({
      ...f,
      subagents: f.subagents.map((s) => (s.id === subId ? { ...s, ...updates } : s)),
    }))
  }

  const toggleExpand = (subId: string) => {
    setExpandedSubagents((prev) => ({ ...prev, [subId]: !(prev[subId] ?? false) }))
  }

  /** Bật/tắt cả một nhóm công cụ; bật lại đủ bộ thì ghi `undefined` = engine tự quyết. */
  const toggleToolGroup = (group: RuntimeToolGroup, on: boolean) => {
    const enabled = new Set(toolsOn)
    for (const tool of group.tools) {
      if (on) enabled.add(tool)
      else enabled.delete(tool)
    }
    const next = allTools.filter((tool) => enabled.has(tool))
    setForm((f) => ({ ...f, tools: next.length === allTools.length ? undefined : next }))
  }

  const handleNumbers = (field: 'maxSteps' | 'deadlineSeconds', raw: string) => {
    const trimmed = raw.trim()
    const parsed = Number.parseInt(trimmed, 10)
    setForm((f) => ({ ...f, [field]: trimmed.length === 0 || Number.isNaN(parsed) ? undefined : parsed }))
  }

  return (
    <div className="mx-auto max-w-4xl px-8 py-7 select-text">
      {/* Breadcrumbs */}
      <div className="mb-4 flex items-center gap-1.5 text-xs text-muted">
        <span>Settings</span>
        <span className="text-muted/60">›</span>
        <span>Agents</span>
        <span className="text-muted/60">›</span>
        <button
          type="button"
          onClick={handleCancel}
          className="text-muted hover:text-fg hover:underline cursor-pointer"
        >
          Harness
        </button>
        <span className="text-muted/60">›</span>
        <span className="font-medium text-fg">{readOnly ? 'Read-only' : 'Editor'}</span>
      </div>

      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-lg font-semibold text-fg">{readOnly ? form.name : 'Edit harness'}</h1>
            {readOnly ? (
              <>
                <span className="flex items-center gap-1 rounded border border-line bg-panel2 px-1.5 py-0.5 text-[10px] font-mono text-muted">
                  <Lock className="size-3" />
                  BUILT-IN
                </span>
                <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 text-[10px] font-mono text-muted">
                  READ-ONLY
                </span>
              </>
            ) : (
              dirty && (
                <span className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
                  Unsaved changes
                </span>
              )
            )}
          </div>
          <p className="mt-1 text-[11px] text-muted">
            {readOnly
              ? `ships with BoxFox · ${enabledRoles} specialists · ${
                  toolCount === null ? `tools ${RUNTIME_INFO_UNAVAILABLE}` : `${toolCount} tools`
                }`
              : `${form.name} · custom${form.duplicatedFrom ? ', started as a copy of a built-in' : ''}`}
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleCancel}
            className="rounded-md border border-line bg-panel px-3.5 py-1.5 text-xs font-medium text-fg transition hover:bg-panel2 cursor-pointer"
          >
            {readOnly ? 'Close' : 'Cancel'}
          </button>
          {readOnly ? (
            <button
              type="button"
              onClick={() => setDuplicateOpen(true)}
              className="rounded-md bg-brand px-4 py-1.5 text-xs font-semibold text-brandfg shadow-xs transition hover:opacity-90 active:scale-98 cursor-pointer"
            >
              Duplicate and edit
            </button>
          ) : (
            <button
              type="button"
              onClick={handleSave}
              className="rounded-md bg-brand px-4 py-1.5 text-xs font-semibold text-brandfg shadow-xs transition hover:opacity-90 active:scale-98 cursor-pointer"
            >
              Save changes
            </button>
          )}
        </div>
      </div>

      {readOnly && (
        <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 p-4">
          <div className="flex gap-2.5">
            <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="text-xs">
              <p className="font-semibold">This harness is part of the product, so it cannot be edited here</p>
              <p className="mt-1 leading-5 text-muted">
                Everything below is exactly what it runs — nothing is hidden, only locked. Duplicate it
                and the copy is yours to change; the built-in keeps working as the reference other
                people compare against.
              </p>
              <p id={LOCKED_REASON_ID} className="mt-2 font-medium">
                {LOCKED_REASON}
              </p>
              <p className="mt-1 text-muted">Duplicate and edit takes one click · no typing if you keep the suggested name.</p>
            </div>
          </div>
        </div>
      )}

      {/* Biên nhận nhân bản — chỉ màn chỉ-đọc mới tạo bản sao, nên nó nằm ngay trên banner. */}
      {receipt && (
        <p id="harness-receipt" role="status" className="mb-4 text-xs text-emerald-600 dark:text-emerald-400">
          {receipt}
        </p>
      )}

      {/* Form Fields */}
      <div className="space-y-5">
        <Card title="Identity" hint="Shown in the list and in the composer's picker" badge={readOnly ? 'Locked' : 'Reads and writes the record'}>
          <div>
            <label htmlFor="harness-name" className="mb-1.5 block text-xs font-medium text-muted">
              Name
            </label>
            <input
              id="harness-name"
              type="text"
              value={form.name}
              disabled={readOnly}
              title={readOnly ? LOCKED_REASON : undefined}
              aria-describedby={readOnly ? LOCKED_REASON_ID : undefined}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              className="w-full rounded-md border border-line bg-panel px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-70"
              placeholder="Harness name"
            />
            {nameError && (
              <p role="alert" className="mt-2 text-[11px] text-red-600 dark:text-red-400">
                Name cannot be empty — a blank row would be impossible to tell apart in the composer's picker.
              </p>
            )}
          </div>

          <div>
            <label htmlFor="harness-description" className="mb-1.5 block text-xs font-medium text-muted">
              Description
            </label>
            <textarea
              id="harness-description"
              rows={3}
              value={form.description}
              disabled={readOnly}
              title={readOnly ? LOCKED_REASON : undefined}
              aria-describedby={readOnly ? LOCKED_REASON_ID : undefined}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              className="w-full rounded-md border border-line bg-panel px-3 py-2 text-xs leading-relaxed text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-70"
              placeholder="Describe what this harness configuration does..."
            />
          </div>
        </Card>

        <Card title="Main agent" hint="One model for the orchestrator" badge={readOnly ? 'Locked' : undefined}>
          <div>
            <label htmlFor="harness-main-model" className="mb-1.5 block text-xs font-medium text-muted">
              Model
            </label>
            <div className="relative">
              <select
                id="harness-main-model"
                value={form.mainModel}
                disabled={readOnly || !catalogueLoaded}
                title={
                  readOnly
                    ? LOCKED_REASON
                    : !catalogueLoaded
                      ? 'The live model catalogue has not loaded, so this list is not offered.'
                      : undefined
                }
                aria-describedby={readOnly ? LOCKED_REASON_ID : !catalogueLoaded ? 'catalogue-not-loaded' : undefined}
                onChange={(e) => handleModelChange(e.target.value)}
                className="w-full appearance-none rounded-md border border-line bg-panel px-3 py-2 text-xs font-medium text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand disabled:cursor-not-allowed disabled:opacity-70"
              >
                <option value="default">Default router / selected Single Model</option>
                {modelChoices.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
                {readOnly && form.mainModel !== 'default' && (
                  <option value={form.mainModel}>{modelLabel(form.mainModel)}</option>
                )}
                {!readOnly && modelOutOfCatalogue && (
                  <option value={form.mainModel}>{modelLabel(form.mainModel)} · not in the live catalogue</option>
                )}
              </select>
              <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-3.5 text-muted" />
            </div>

            {!readOnly && !catalogueLoaded && (
              <p id="catalogue-not-loaded" className="mt-2 text-[11px] leading-4 text-amber-600 dark:text-amber-400">
                The live model catalogue has not loaded{providerLoading ? ' yet' : ''}, so the picker is
                disabled instead of falling back to a static list.
                {providerError ? ` Router answered: ${providerError}` : ''}
              </p>
            )}

            <p className="mt-2 text-[11px] leading-4 text-muted">
              {readOnly
                ? "The built-in record is normalised to the router default, so this is what the harness really runs — even when the description promises a specific model."
                : "Applies to new sessions only. A chat that is already open keeps the model it started with. Every specialist left on Inherit parent model follows this choice; a specialist pinned to its own model keeps it even when this line changes."}
            </p>
            {form.mainModel !== 'default' && (
              <p className="mt-1 text-[11px] text-muted">
                Stored as <code className="font-mono text-fg">{form.mainModel}</code> — the routing value
                the composer sends.
              </p>
            )}

            {form.modelWarning && (
              <div className="mt-3 flex items-start gap-2.5 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
                <AlertTriangle className="size-4 shrink-0 text-amber-400 mt-0.5" />
                <div>
                  <p className="font-semibold text-amber-200">Some models in this harness do not support images</p>
                  <p className="mt-0.5 text-amber-300/80 leading-relaxed text-[11px]">{form.modelWarning}</p>
                </div>
              </div>
            )}
          </div>
        </Card>

        <Card
          title="Turn limits"
          hint="Caps the harness enforces on every turn"
          badge={readOnly ? 'Engine defaults' : undefined}
        >
          {readOnly ? (
            <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs">
              <div title={LOCKED_REASON} aria-describedby={LOCKED_REASON_ID} className="rounded-lg border border-line bg-panel2 p-3">
                <dt className="text-muted">Steps per turn</dt>
                <dd className="mt-1 font-medium">
                  {limits ? `${limits.maxStepsDefault} of ${limits.maxStepsMax} allowed` : RUNTIME_INFO_UNAVAILABLE}
                </dd>
              </div>
              <div title={LOCKED_REASON} aria-describedby={LOCKED_REASON_ID} className="rounded-lg border border-line bg-panel2 p-3">
                <dt className="text-muted">Turn deadline</dt>
                <dd className="mt-1 font-medium">
                  {limits ? `${limits.deadlineDefaultSeconds} of ${limits.deadlineMaxSeconds} allowed` : RUNTIME_INFO_UNAVAILABLE}
                </dd>
              </div>
            </dl>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="harness-max-steps" className="mb-1.5 block text-xs font-medium text-muted">
                  Steps per turn
                </label>
                <div className="relative">
                  <input
                    id="harness-max-steps"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={limits?.maxStepsMax}
                    value={form.maxSteps ?? ''}
                    placeholder={limits ? String(limits.maxStepsDefault) : 'engine default'}
                    onChange={(e) => handleNumbers('maxSteps', e.target.value)}
                    className="w-full rounded-md border border-line bg-panel px-3 py-2 pr-14 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
                  />
                  <span className="pointer-events-none absolute right-3 top-2.5 text-[10px] uppercase tracking-wide text-muted">
                    steps
                  </span>
                </div>
                <p id="harness-max-steps-hint" className="mt-1.5 text-[11px] text-muted">
                  {limits
                    ? `allowed 1 – ${limits.maxStepsMax} · engine default ${limits.maxStepsDefault}`
                    : `range and engine default are ${RUNTIME_INFO_UNAVAILABLE} until the engine answers`}
                </p>
              </div>

              <div>
                <label htmlFor="harness-deadline" className="mb-1.5 block text-xs font-medium text-muted">
                  Turn deadline
                </label>
                <div className="relative">
                  <input
                    id="harness-deadline"
                    type="number"
                    inputMode="numeric"
                    min={5}
                    max={limits?.deadlineMaxSeconds}
                    value={form.deadlineSeconds ?? ''}
                    placeholder={limits ? String(limits.deadlineDefaultSeconds) : 'engine default'}
                    onChange={(e) => handleNumbers('deadlineSeconds', e.target.value)}
                    className="w-full rounded-md border border-line bg-panel px-3 py-2 pr-14 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
                  />
                  <span className="pointer-events-none absolute right-3 top-2.5 text-[10px] uppercase tracking-wide text-muted">
                    seconds
                  </span>
                </div>
                <p id="harness-deadline-hint" className="mt-1.5 text-[11px] text-muted">
                  {limits
                    ? `allowed 5 – ${limits.deadlineMaxSeconds} · engine default ${limits.deadlineDefaultSeconds}`
                    : `range and engine default are ${RUNTIME_INFO_UNAVAILABLE} until the engine answers`}
                </p>
              </div>
            </div>
          )}

          <p className="text-[11px] leading-4 text-muted">
            {limits
              ? `A delegated specialist is capped harder on purpose: it gets the smaller of ${limits.childMaxSteps} steps and this number, and the smaller of ${limits.childDeadlineSeconds} s and this deadline.`
              : `A delegated specialist is capped harder on purpose — the engine's child ceiling is ${RUNTIME_INFO_UNAVAILABLE} until runtime-info answers.`}
            {limits ? ` Raising the deadline above ${limits.deadlineDefaultSeconds} s also raises how long a decision request can hold a turn.` : ''}
          </p>
        </Card>

        <Card title="Thinking level" hint="Handled per model, at send time" badge="Travels with the model">
          <div>
            <label htmlFor="harness-thinking-level" className="mb-1.5 block text-xs font-medium text-muted">
              Preferred level
            </label>
            {readOnly ? (
              <p title={LOCKED_REASON} aria-describedby={LOCKED_REASON_ID} className="rounded-md border border-line bg-panel2 px-3 py-2 text-xs">
                Auto — let the provider decide
              </p>
            ) : (
              <div className="relative">
                <select
                  id="harness-thinking-level"
                  value={thinkingLevel}
                  onChange={(e) => setThinkingLevel(e.target.value)}
                  className="w-full appearance-none rounded-md border border-line bg-panel px-3 py-2 text-xs font-medium text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
                >
                  {THINKING_LEVELS.map((level) => (
                    <option key={level || 'auto'} value={level}>
                      {level === '' ? 'Auto — let the provider decide' : level}
                    </option>
                  ))}
                  {!THINKING_LEVELS.includes(thinkingLevel) && <option value={thinkingLevel}>{thinkingLevel}</option>}
                </select>
                <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-3.5 text-muted" />
              </div>
            )}
            <p className="mt-2 text-[11px] leading-4 text-muted">
              The level travels with the model, not with the harness. Each turn sends the level your
              composer shows; if the model publishes no levels (ids that already carry one in their
              name), the value is dropped rather than refused. A level the model does not publish is
              refused with <code className="font-mono">THINKING_LEVEL_UNSUPPORTED</code> instead of
              being stored as if applied.
            </p>
            {readOnly && (
              <p className="mt-1 text-[11px] text-muted">
                The composer's own level still applies to a chat that uses this harness; the harness
                only holds a preference for when you leave it on Auto.
              </p>
            )}
          </div>
        </Card>

        <Card title="Tool access" hint="Narrow what the engine may run" badge={readOnly ? 'Locked' : undefined}>
          <p className="text-xs font-semibold">
            {toolCount === null
              ? `Tools ${RUNTIME_INFO_UNAVAILABLE}`
              : `${toolCount} of ${allTools.length} tools on${form.tools === undefined ? ' · nothing narrowed' : ''}`}
          </p>

          {runtimeInfo === null ? (
            <div className="rounded-lg border border-line bg-panel2 p-3 text-[11px] text-muted">
              <p>
                The engine has not answered, so the tool list cannot be shown. Nothing here is guessed
                from a hard-coded list.
              </p>
              <button
                type="button"
                onClick={() => void loadRuntimeInfo(true)}
                className="mt-2 rounded-md border border-line px-2.5 py-1.5 text-[11px] font-semibold hover:bg-panel cursor-pointer"
              >
                Try again
              </button>
            </div>
          ) : (
            <div className="space-y-2">
              {runtimeInfo.toolGroups.map((group) => {
                const groupOn = toolsKnown && group.tools.every((tool) => toolsOn.includes(tool))
                return (
                  <div key={group.key} className="rounded-lg border border-line bg-panel2 p-3">
                    <div className="flex flex-wrap items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-xs font-semibold">{groupLabel(group.key)}</p>
                        <p className="mt-1 text-[11px] leading-4 text-muted">
                          {group.tools.join(' · ')}
                          {TOOL_GROUP_NOTES[group.key] ? ` — ${TOOL_GROUP_NOTES[group.key]}` : ''}
                        </p>
                        {group.alwaysOn && (
                          <p id="always-on-reason" className="mt-1 text-[11px] text-muted">
                            Always on in every role: the engine does not let the agent stay silent on the
                            things it must ask you about.
                          </p>
                        )}
                      </div>
                      <div className="flex items-center gap-2">
                        <span className="rounded border border-line bg-panel px-1.5 py-0.5 text-[10px] font-mono text-muted">
                          {group.tools.length}
                        </span>
                        {readOnly ? (
                          <span
                            title={LOCKED_REASON}
                            aria-describedby={LOCKED_REASON_ID}
                            className="text-[10px] font-semibold uppercase tracking-wide text-muted"
                          >
                            {group.alwaysOn ? 'Always on' : groupOn ? 'On' : 'Off'}
                          </span>
                        ) : (
                          <input
                            id={`tool-group-${group.key}`}
                            type="checkbox"
                            checked={groupOn}
                            disabled={group.alwaysOn || !toolsKnown}
                            title={group.alwaysOn ? 'Always on in every role.' : undefined}
                            aria-describedby={group.alwaysOn ? 'always-on-reason' : undefined}
                            aria-label={`${groupLabel(group.key)} tools`}
                            onChange={(e) => toggleToolGroup(group, e.target.checked)}
                            className="size-4 accent-blue-500 disabled:cursor-not-allowed"
                          />
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <p className="text-[11px] leading-4 text-muted">
            You can only take tools away. Asking the engine for a tool the role does not have is refused
            with <code className="font-mono">Tool not permitted for this role</code>, so the checkboxes
            never promise access that does not exist.
          </p>
        </Card>

        <Card title="Retries" hint="Shared by every harness, stored in the engine" badge="Engine-wide">
          {retry ? (
            <>
              <dl className="grid grid-cols-1 gap-3 text-xs sm:grid-cols-3">
                <div className="rounded-lg border border-line bg-panel2 p-3">
                  <dt className="text-muted">Retries after the first call</dt>
                  <dd className="mt-1 font-medium">{retry.maxRetries}</dd>
                </div>
                <div className="rounded-lg border border-line bg-panel2 p-3">
                  <dt className="text-muted">Ceiling for a rate limit</dt>
                  <dd className="mt-1 font-medium">{retry.rateLimitMaxSeconds} s</dd>
                </div>
                <div className="rounded-lg border border-line bg-panel2 p-3">
                  <dt className="text-muted">Budget per turn</dt>
                  <dd className="mt-1 font-medium">{retry.budgetSeconds} s</dd>
                </div>
              </dl>
              <p className="text-[11px] leading-4 text-muted">
                Waits between attempts are {retry.backoffSeconds.map((seconds) => `${seconds} s`).join(' → ')}{' '}
                with ±{Math.round(retry.jitter * 100)}% jitter; a 429 waits what the provider asked for,
                capped by the ceiling above and never past the turn budget. Timeouts and rejected requests
                are never retried — a second identical call cannot fix them.
              </p>
            </>
          ) : (
            <p className="text-[11px] text-muted">
              The retry policy is {RUNTIME_INFO_UNAVAILABLE} until runtime-info answers. It is not stored
              per harness, so there is nothing here to guess.
            </p>
          )}
          <p className="text-[11px] leading-4 text-muted">
            These three numbers live in the harness engine and apply to every harness. They sit here
            because a turn budget is easier to read in one place; the heading says "engine-wide" rather
            than implying a per-harness policy the engine does not have.
          </p>
        </Card>

        <Card
          title="Subagents"
          hint="Nine built-in specialist roles"
          badge={readOnly ? 'Locked, shown so you can see what you get in a copy' : undefined}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-semibold">
              {enabledRoles} of {form.subagents.length} enabled · {appendedPrompts} carry an appended prompt
            </p>
            <button
              type="button"
              disabled
              title="v0 supports the nine built-in specialist roles"
              className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 py-1 text-xs font-medium text-fg transition hover:bg-panel2 cursor-pointer disabled:cursor-not-allowed disabled:opacity-60"
            >
              <Plus className="size-3" />
              <span>Add Custom Subagent</span>
            </button>
          </div>

          {readOnly ? (
            <div className="space-y-2">
              {form.subagents.map((role) => (
                <div
                  key={role.id}
                  title={LOCKED_REASON}
                  aria-describedby={LOCKED_REASON_ID}
                  className="rounded-lg border border-line bg-panel2 p-3 text-xs"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-medium">{role.name}</span>
                    <span className="text-[11px] text-muted">
                      {role.enabled ? 'enabled' : 'disabled'} ·{' '}
                      {role.model === 'inherit' ? 'inherit parent model' : modelLabel(role.model)}
                    </span>
                  </div>
                  {role.systemPromptAppended.trim().length > 0 && (
                    <p className="mt-1 text-[11px] leading-4 text-muted">{role.systemPromptAppended}</p>
                  )}
                </div>
              ))}
              <p className="text-[11px] leading-4 text-muted">
                {appendedPrompts === 0
                  ? "No appended prompt is set on any role in this harness, which is why a duplicate starts as a blank canvas for prompts rather than inheriting someone else's wording."
                  : `${appendedPrompts} role(s) carry an appended prompt; a copy starts from that text.`}
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {form.subagents.map((role) => {
                const isExpanded = expandedSubagents[role.id] ?? role.systemPromptAppended.trim().length > 0
                return (
                  <div key={role.id} className="overflow-hidden rounded-lg border border-line bg-panel transition">
                    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel2/40 px-3.5 py-2.5">
                      <div className="flex items-center gap-2.5">
                        <CustomCheckbox
                          checked={role.enabled}
                          onChange={() => handleUpdateSubagent(role.id, { enabled: !role.enabled })}
                          label={role.name}
                        />
                        <span className="rounded border border-line bg-panel2 px-1.5 py-0.5 text-[10px] font-mono text-muted">
                          {role.id}
                        </span>
                      </div>

                      <div className="flex items-center gap-2.5">
                        <select
                          value={role.model}
                          aria-label={`${role.name} model`}
                          onChange={(e) => handleUpdateSubagent(role.id, { model: e.target.value })}
                          className="appearance-none rounded border border-line bg-panel px-2 py-1 text-[11px] text-fg outline-hidden transition hover:border-muted focus:border-brand"
                        >
                          <option value="inherit">inherit parent model</option>
                          {modelChoices.map((choice) => (
                            <option key={choice.value} value={choice.value}>
                              {choice.label}
                            </option>
                          ))}
                          {role.model !== 'inherit' && !modelChoices.some((c) => c.value === role.model) && (
                            <option value={role.model}>{modelLabel(role.model)} · not in the live catalogue</option>
                          )}
                        </select>

                        <button
                          type="button"
                          onClick={() => toggleExpand(role.id)}
                          aria-label={`${isExpanded ? 'Hide' : 'Show'} ${role.name} prompt`}
                          className="rounded p-1 text-muted hover:bg-panel2 hover:text-fg transition cursor-pointer"
                        >
                          {isExpanded ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                        </button>
                      </div>
                    </div>

                    {isExpanded && (
                      <div className="p-3.5">
                        <label htmlFor={`role-${role.id}-prompt`} className="text-xs font-medium text-fg">
                          System prompt (appended)
                        </label>
                        <p className="mb-2 mt-1 text-[11px] leading-4 text-muted">
                          Appended to this role's own instructions and sent as the role's directive block
                          when the main agent delegates. It does not inherit the text on the Instructions
                          tab.
                        </p>
                        <textarea
                          id={`role-${role.id}-prompt`}
                          rows={3}
                          value={role.systemPromptAppended}
                          onChange={(e) => handleUpdateSubagent(role.id, { systemPromptAppended: e.target.value })}
                          placeholder="Enter specialized custom instructions for this subagent..."
                          className="w-full rounded-md border border-line bg-panel2/50 p-2.5 font-mono text-xs leading-relaxed text-fg placeholder:text-muted/50 outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
                        />
                      </div>
                    )}
                  </div>
                )
              })}
              <p className="text-[11px] leading-4 text-muted">
                A role switched off cannot be delegated: the engine answers{' '}
                <code className="font-mono">Specialist is disabled or unknown</code>, and the picker in
                the chat stops offering it.
              </p>
            </div>
          )}
        </Card>

        {/* Luật tự mở tab (hợp đồng §3) — hai công tắc đọc/ghi thẳng uiStore. */}
        <Card title={t('autoOpen.sectionTitle')} hint="App-wide, not part of the harness record" badge="Still yours to change">
          <div className="space-y-2.5">
            <div className="rounded-lg border border-line bg-panel2 p-4">
              <CustomCheckbox
                checked={autoOpenTabs}
                onChange={() => setAutoOpenTabs(!autoOpenTabs)}
                label={t('autoOpen.toggleLabel')}
                description={t('autoOpen.toggleDesc')}
                className="items-start"
              />
            </div>
            <div className="rounded-lg border border-line bg-panel2 p-4">
              <CustomCheckbox
                checked={autoOpenOnlyWhenIdle}
                onChange={() => setAutoOpenOnlyWhenIdle(!autoOpenOnlyWhenIdle)}
                label={t('autoOpen.idleLabel')}
                description={t('autoOpen.idleDesc')}
                className="items-start"
              />
            </div>
          </div>
          <p className="text-[11px] leading-4 text-muted">
            Kept live on purpose: this switch is not part of the harness record, so locking it here
            would be theatre.
          </p>
        </Card>
      </div>

      {readOnly && (
        <p className="mt-6 rounded-lg border border-line bg-panel2 p-3 text-[11px] leading-4 text-muted">
          Read-only preview — changes in a copy apply to chats you start afterwards, never to a chat
          already running.
        </p>
      )}

      {duplicateOpen && initialHarness && (
        <HarnessDuplicateDialog
          source={initialHarness}
          harnesses={harnesses}
          onCancel={() => setDuplicateOpen(false)}
          onDone={handleDuplicated}
        />
      )}
    </div>
  )
}
