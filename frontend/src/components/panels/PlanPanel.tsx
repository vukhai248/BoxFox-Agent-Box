/**
 * Khung ② — Kế hoạch (Plan Panel) phong cách BoxFox / Devin.
 * Cập nhật: Thay toàn bộ native select bằng Custom Dark Dropdown Popover, nút Approve tone trắng xám sang trọng.
 */
import { useState, useMemo, useRef, useEffect } from 'react'
import {
  Link,
  Copy,
  Check,
  Sparkles,
  ChevronDown,
  ChevronRight,
  X,
  FileCode,
  Shield,
  ArrowRight,
  ArrowLeft,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { PlainText } from '../ui'
import { MarkdownRenderer } from '../chat/MarkdownRenderer'
import { usePlanFiles } from '../../hooks/usePlanFiles'
import type { DiffLine } from '../../types/agent'

const PLAN_VERSIONS = ['v3 (latest)', 'v2', 'v1']

export function PlanPanel() {
  const mode = useAgentStore((s) => s.mode)
  const workspace = useAgentStore((s) => s.planWorkspace)
  const endorsed = useAgentStore((s) => s.planEndorsed)
  const proposal = useAgentStore((s) => s.proposal)
  const sendCommand = useAgentStore((s) => s.sendCommand)

  const planViewMode = useUiStore((s) => s.planViewMode)
  const setPlanViewMode = useUiStore((s) => s.setPlanViewMode)
  const planSubTab = useUiStore((s) => s.planSubTab)
  const setPlanSubTab = useUiStore((s) => s.setPlanSubTab)
  const planVersion = useUiStore((s) => s.planVersion)
  const setPlanVersion = useUiStore((s) => s.setPlanVersion)
  const showFeedbackBanner = useUiStore((s) => s.showFeedbackBanner)
  const setShowFeedbackBanner = useUiStore((s) => s.setShowFeedbackBanner)

  /** Nguồn plan từ filesystem sandbox (đọc-only). */
  const planFiles = usePlanFiles()
  const selectedPlan = planFiles.manifest?.plans.find((p) => p.identity === planFiles.selection?.identity)
  const selectedFileVersion = selectedPlan?.versions.find((v) => v.version === planFiles.selection?.version)

  /** Danh sách version để render trong dropdown: file thật nếu có, ngược lại dùng mock. */
  const versionItems = selectedPlan?.versions.length
    ? selectedPlan.versions.map((v) => ({
        key: v.version,
        label: `${v.label} (${v.status})`,
        isCurrent: v.version === planFiles.selection?.version,
        onSelect: () => planFiles.selectVersion(v.version),
      }))
    : PLAN_VERSIONS.map((v) => {
        const val = v.split(' ')[0]
        return {
          key: val,
          label: v,
          isCurrent: planVersion === val,
          onSelect: () => setPlanVersion(val),
        }
      })

  const [copied, setCopied] = useState(false)
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  const [identityMenuOpen, setIdentityMenuOpen] = useState(false)
  const [versionMenuOpen, setVersionMenuOpen] = useState(false)
  const identityMenuRef = useRef<HTMLDivElement>(null)
  const versionMenuRef = useRef<HTMLDivElement>(null)

  const currentPlan = mode === 'ACT' && endorsed ? endorsed : workspace

  const diffChunks: DiffLine[] = useMemo(() => {
    // Return empty diff when no modifications are present
    return []
  }, [])

  const selectedStep = useMemo(() => {
    if (!currentPlan?.steps || !selectedStepId) return null
    return currentPlan.steps.find((s) => s.id === selectedStepId) ?? null
  }, [currentPlan, selectedStepId])

  // Click outside to close popovers
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node
      if (identityMenuRef.current && !identityMenuRef.current.contains(target)) {
        setIdentityMenuOpen(false)
      }
      if (versionMenuRef.current && !versionMenuRef.current.contains(target)) {
        setVersionMenuOpen(false)
      }
    }
    if (identityMenuOpen || versionMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [identityMenuOpen, versionMenuOpen])

  const handleApprove = () => {
    if (proposal) {
      sendCommand({
        type: 'mode_switch_confirm',
        accepted: true,
      })
    } else if (mode === 'PLAN') {
      sendCommand({ type: 'scenario_step' })
    }
  }

  const handleCopy = () => {
    const text = planFiles.document?.markdown ?? currentPlan?.full_text
    if (text) {
      void navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleNavigateStep = (direction: 'prev' | 'next') => {
    if (!currentPlan?.steps || !selectedStepId) return
    const currentIndex = currentPlan.steps.findIndex((s) => s.id === selectedStepId)
    if (currentIndex === -1) return
    const nextIndex = direction === 'next' ? currentIndex + 1 : currentIndex - 1
    if (nextIndex >= 0 && nextIndex < currentPlan.steps.length) {
      setSelectedStepId(currentPlan.steps[nextIndex].id)
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-panel select-text">
      {/* Sub-Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel px-4 py-2">
        <div className="flex items-center gap-2.5">
          {/* Document Title Selector — dùng danh sách plan từ sandbox khi có */}
          <div className="relative min-w-0" ref={identityMenuRef}>
            <button
              type="button"
              onClick={() => setIdentityMenuOpen((o) => !o)}
              disabled={!planFiles.manifest?.plans.length}
              className="flex max-w-56 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-fg transition hover:bg-panel2 disabled:cursor-default disabled:text-muted cursor-pointer"
              title={selectedPlan?.identity ?? 'Agent Box — Plan Document'}
            >
              <span className="truncate">{selectedPlan?.identity ?? 'Agent Box — Plan Document'}</span>
              <ChevronDown className="size-3 shrink-0 text-muted" />
            </button>
            {identityMenuOpen && planFiles.manifest && (
              <div className="absolute left-0 top-full z-40 mt-1 max-h-64 w-56 overflow-y-auto rounded-lg border border-line bg-panel2 p-1 shadow-xl animate-in fade-in zoom-in-95 duration-100">
                {planFiles.manifest.plans.map((plan) => {
                  const isCurrent = plan.identity === planFiles.selection?.identity
                  return (
                    <button
                      key={plan.identity}
                      type="button"
                      onClick={() => {
                        planFiles.selectIdentity(plan.identity)
                        setIdentityMenuOpen(false)
                      }}
                      className={`flex w-full items-center justify-between gap-2 rounded px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                        isCurrent ? 'bg-panel font-medium text-fg' : 'text-muted hover:bg-panel hover:text-fg'
                      }`}
                    >
                      <span className="truncate">{plan.identity}</span>
                      {isCurrent && <Check className="size-3 shrink-0 text-brand" />}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Custom Sleek Version Dropdown Popover */}
          <div className="relative inline-block" ref={versionMenuRef}>
            <button
              type="button"
              onClick={() => setVersionMenuOpen(!versionMenuOpen)}
              className="flex items-center gap-1.5 rounded-md border border-line bg-panel2 px-2.5 py-1 text-xs font-medium text-fg outline-hidden transition hover:border-zinc-500 cursor-pointer"
            >
              <span>
                {selectedFileVersion
                  ? `${selectedFileVersion.label} (${selectedFileVersion.status})`
                  : planVersion}
              </span>
              <ChevronDown className="size-3 text-muted" />
            </button>

            {versionMenuOpen && (
              <div className="absolute left-0 top-full z-40 mt-1 w-36 overflow-hidden rounded-lg border border-line bg-panel2 p-1 shadow-xl animate-in fade-in zoom-in-95 duration-100">
                {versionItems.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      item.onSelect()
                      setVersionMenuOpen(false)
                    }}
                    className={`flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                      item.isCurrent ? 'bg-panel font-medium text-fg' : 'text-muted hover:bg-panel hover:text-fg'
                    }`}
                  >
                    <span>{item.label}</span>
                    {item.isCurrent && <Check className="size-3 text-brand" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Plan | Diff Toggle */}
          <div className="flex items-center rounded-md border border-line bg-panel2 p-0.5">
            <button
              type="button"
              onClick={() => setPlanViewMode('plan')}
              className={`rounded px-2.5 py-0.5 text-xs font-medium transition cursor-pointer ${
                planViewMode === 'plan'
                  ? 'bg-panel text-fg shadow-xs'
                  : 'text-muted hover:text-fg'
              }`}
            >
              Plan
            </button>
            <button
              type="button"
              onClick={() => setPlanViewMode('diff')}
              className={`rounded px-2.5 py-0.5 text-xs font-medium transition cursor-pointer ${
                planViewMode === 'diff'
                  ? 'bg-panel text-fg shadow-xs'
                  : 'text-muted hover:text-fg'
              }`}
            >
              Diff
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Share Button */}
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
          >
            <Link className="size-3" />
            <span>Share</span>
          </button>

          {/* Copy Button */}
          <button
            type="button"
            onClick={handleCopy}
            className="rounded-md border border-line p-1 text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
            title="Copy plan text"
          >
            {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
          </button>

          {/* Approve Button in Sleek Solid Tone */}
          <button
            type="button"
            onClick={handleApprove}
            disabled={mode === 'ACT'}
            className={`flex items-center gap-1.5 rounded-md px-3.5 py-1 text-xs font-semibold transition shadow-xs cursor-pointer ${
              mode === 'ACT'
                ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                : 'bg-zinc-100 text-zinc-900 hover:bg-white active:scale-98'
            }`}
          >
            <Check className="size-3.5" />
            <span>{mode === 'ACT' ? 'Approved (ACT)' : 'Approve Plan'}</span>
          </button>
        </div>
      </div>

      {/* Sub-tabs: Overview | Detailed Plan (when in Plan view) */}
      {planViewMode === 'plan' && (
        <div className="flex items-center gap-1 border-b border-line bg-panel2/20 px-4 py-0.5">
          <button
            type="button"
            onClick={() => setPlanSubTab('overview')}
            className={`border-b-2 px-3 py-1.5 text-xs font-medium transition cursor-pointer ${
              planSubTab === 'overview'
                ? 'border-brand text-fg'
                : 'border-transparent text-muted hover:text-fg'
            }`}
          >
            Overview
          </button>
          <button
            type="button"
            onClick={() => setPlanSubTab('detailed')}
            className={`border-b-2 px-3 py-1.5 text-xs font-medium transition cursor-pointer ${
              planSubTab === 'detailed'
                ? 'border-brand text-fg'
                : 'border-transparent text-muted hover:text-fg'
            }`}
          >
            Detailed Plan
          </button>
        </div>
      )}

      {/* Inline Comment Suggestion Banner */}
      {showFeedbackBanner && (
        <div className="flex items-center justify-between border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-muted">
          <div className="flex items-center gap-2">
            <Sparkles className="size-3.5 text-brand" />
            <span>Select text to ask a follow-up or add an inline comment</span>
          </div>
          <button
            type="button"
            onClick={() => setShowFeedbackBanner(false)}
            className="rounded p-0.5 text-muted hover:text-fg cursor-pointer"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* Main Content Area */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {planViewMode === 'diff' ? (
          /* Diff View */
          diffChunks.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center text-muted">
              <FileCode className="size-8 text-muted/40 mb-2" />
              <p className="text-xs font-semibold text-fg">No file diff available</p>
              <p className="text-[11px] text-muted mt-0.5">Diff comparisons will appear once files are modified in Act mode.</p>
            </div>
          ) : (
            <div className="h-full overflow-y-auto p-6 space-y-3">
              <div className="flex items-center justify-between border-b border-line pb-2">
                <span className="font-mono text-xs font-semibold text-fg flex items-center gap-1.5">
                  <FileCode className="size-3.5 text-brand" />
                  Workspace Diff Changes
                </span>
              </div>
              <div className="overflow-x-auto rounded-md border border-line bg-bg p-3.5 font-mono text-xs leading-relaxed">
                {diffChunks.map((line, i) => (
                  <div
                    key={i}
                    className={`px-2 py-0.5 ${
                      line.kind === 'them'
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : line.kind === 'bot'
                          ? 'bg-rose-500/15 text-rose-300 line-through'
                          : 'text-muted'
                    }`}
                  >
                    <span className="mr-3 select-none text-[10px] opacity-40">
                      {line.kind === 'them' ? '+' : line.kind === 'bot' ? '-' : ' '}
                    </span>
                    {line.text}
                  </div>
                ))}
              </div>
            </div>
          )
        ) : !currentPlan && !planFiles.document ? (
          /* Empty State */
          <div className="flex h-full items-center justify-center p-8 text-center">
            <p className="text-xs text-muted">No plan artifact generated yet.</p>
          </div>
        ) : planSubTab === 'overview' ? (
          /* Overview View (Split view if step selected) */
          <div className="flex h-full min-h-0">
            {/* Left Side: Summary & Compact Step List */}
            <div
              className={`h-full overflow-y-auto p-6 transition-all duration-200 ${
                selectedStep ? 'w-1/2 border-r border-line' : 'w-full max-w-3xl'
              }`}
            >
              <div className="space-y-5">
                <div>
                  <h1 className="text-base font-semibold text-fg">
                    {planFiles.document ? planFiles.document.identity : 'Agent Plan Summary'}
                  </h1>
                  <p className="mt-0.5 text-xs text-muted">
                    {planFiles.document ? (
                      <>
                        File location: <code className="text-brand font-mono text-[11px]">.plans/{planFiles.document.relativePath}</code>
                      </>
                    ) : (
                      <>
                        Full architectural blueprint: <code className="text-brand font-mono text-[11px]">/docs/plan/agent-box-plan.md</code>
                      </>
                    )}
                  </p>
                </div>

                {/* Overview Highlights Card */}
                <div className="rounded-lg border border-line bg-panel2/30 p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <h2 className="text-[11px] font-semibold text-fg uppercase tracking-wider">
                      {planFiles.document ? 'Plan Metadata & Status' : 'Architecture Scope'}
                    </h2>
                    {planFiles.document && (
                      <span className="rounded bg-panel px-2 py-0.5 text-[10px] font-mono text-brand border border-line">
                        {planFiles.document.label} • {planFiles.document.status}
                      </span>
                    )}
                  </div>
                  {planFiles.document ? (
                    <div className="space-y-2 text-xs text-muted">
                      <p className="leading-relaxed">
                        Tài liệu kế hoạch được tải trực tiếp từ máy ảo sandbox.
                      </p>
                      <div className="grid grid-cols-2 gap-2 pt-1 font-mono text-[11px]">
                        <div>Dung lượng: <span className="text-fg">{(planFiles.document.sizeBytes / 1024).toFixed(1)} KB</span></div>
                        <div>Cập nhật: <span className="text-fg">{new Date(planFiles.document.modifiedAt).toLocaleTimeString()}</span></div>
                      </div>
                      <div className="pt-2">
                        <button
                          type="button"
                          onClick={() => setPlanSubTab('detailed')}
                          className="inline-flex items-center gap-1.5 rounded-md bg-panel border border-line px-2.5 py-1 text-xs font-medium text-fg hover:bg-panel2 hover:border-zinc-500 transition cursor-pointer"
                        >
                          <span>Xem toàn bộ chi tiết Markdown</span>
                          <ArrowRight className="size-3 text-brand" />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-xs leading-relaxed text-muted">
                        Self-hosted <strong>AI Computer</strong> with runtime Information-Flow Control (IFC).
                      </p>
                      <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">
                        <li>All inputs tagged with provenance labels (Integrity, Confidentiality).</li>
                        <li>Outbound actions gated by scoped, time-bound leases (30-min plan lease).</li>
                      </ul>
                    </>
                  )}
                </div>

                {/* Compact Steps List */}
                {currentPlan?.steps && currentPlan.steps.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between pb-1 text-xs font-semibold text-fg">
                      <span>Execution Steps ({currentPlan.steps.length})</span>
                      <span className="text-[11px] font-normal text-muted">Click step to inspect</span>
                    </div>

                    <div className="space-y-1">
                      {currentPlan.steps.map((step) => {
                        const isSelected = selectedStepId === step.id
                        const isDone = step.status === 'xong'
                        return (
                          <div
                            key={step.id}
                            onClick={() => setSelectedStepId(isSelected ? null : step.id)}
                            className={`group flex items-center justify-between rounded-md border p-2.5 text-xs transition cursor-pointer ${
                              isSelected
                                ? 'border-zinc-500 bg-panel2/80 shadow-xs'
                                : 'border-line bg-panel hover:bg-panel2 hover:border-zinc-700'
                            }`}
                          >
                            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                              <span
                                className={`flex size-5 shrink-0 items-center justify-center rounded font-mono text-[10px] font-bold ${
                                  isDone
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                    : 'bg-panel2 text-brand border border-line'
                                }`}
                              >
                                {step.id}
                              </span>
                              <span className="truncate font-medium text-fg">{step.description}</span>
                            </div>

                            <div className="flex items-center gap-2 ml-2 shrink-0">
                              <span className="rounded bg-panel2 px-1.5 py-0.2 text-[10px] font-mono text-muted border border-line">
                                {step.risk_level}
                              </span>
                              <span
                                className={`rounded px-1.5 py-0.2 text-[10px] font-medium uppercase tracking-wider ${
                                  isDone
                                    ? 'bg-emerald-500/15 text-emerald-400'
                                    : 'bg-panel2 text-muted'
                                }`}
                              >
                                {isDone ? 'DONE' : 'PENDING'}
                              </span>
                              <ChevronRight
                                className={`size-3.5 text-muted transition group-hover:translate-x-0.5 ${
                                  isSelected ? 'rotate-90 text-brand' : ''
                                }`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right Side: Step Inspector Split Drawer */}
            {selectedStep && (
              <div className="w-1/2 h-full overflow-y-auto bg-panel2/20 p-5 flex flex-col justify-between border-l border-line animate-in fade-in slide-in-from-right-4 duration-150">
                <div className="space-y-4">
                  {/* Inspector Header */}
                  <div className="flex items-center justify-between border-b border-line pb-3">
                    <div className="flex items-center gap-2">
                      <span className="flex size-6 items-center justify-center rounded-md bg-panel2 font-mono text-xs font-bold text-brand border border-line">
                        {selectedStep.id}
                      </span>
                      <h3 className="text-xs font-semibold text-fg">Step Details & Trace</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedStepId(null)}
                      className="rounded p-1 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
                      title="Close Inspector"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>

                  {/* Step Metadata Card */}
                  <div className="rounded-lg border border-line bg-panel p-3.5 space-y-3">
                    <div>
                      <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Goal</span>
                      <p className="mt-1 text-xs text-fg font-medium leading-relaxed">{selectedStep.description}</p>
                    </div>

                    <div className="grid grid-cols-2 gap-3 pt-2 border-t border-line/60">
                      <div>
                        <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Target Resources</span>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {selectedStep.resources.map((res, i) => (
                            <span key={i} className="rounded bg-panel2 px-1.5 py-0.5 text-[11px] font-mono text-fg border border-line">
                              {res}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div>
                        <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Security Policy</span>
                        <div className="mt-1 flex items-center gap-1.5">
                          <Shield className="size-3 text-brand" />
                          <span className="text-xs font-medium text-fg">{selectedStep.risk_level}</span>
                          <span className="text-[10px] text-muted">({selectedStep.out_of_scope ? 'Out of lease' : 'In plan lease'})</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Execution Trace / Output Mock */}
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Resource Trace / Diff</span>
                    <div className="rounded-md border border-line bg-bg p-3 font-mono text-[11px] leading-relaxed text-zinc-300 overflow-x-auto">
                      <div className="text-muted pb-1">// Target: {selectedStep.resources.join(', ')}</div>
                      <div className="text-emerald-400">+ Integrity: VERIFIED_CLEAN</div>
                      <div className="text-zinc-400">+ Confidentiality: RESTRICTED_WORKSPACE</div>
                      <div className="text-muted pt-1">// Status: {selectedStep.status === 'xong' ? 'Completed successfully' : 'Queued for execution'}</div>
                    </div>
                  </div>
                </div>

                {/* Footer Step Navigation */}
                <div className="flex items-center justify-between border-t border-line pt-3 mt-4">
                  <button
                    type="button"
                    onClick={() => handleNavigateStep('prev')}
                    className="flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                  >
                    <ArrowLeft className="size-3" />
                    <span>Previous</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleNavigateStep('next')}
                    className="flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                  >
                    <span>Next</span>
                    <ArrowRight className="size-3" />
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Detailed Plan View — file sandbox nếu có, ngược lại dùng store */
          <div className="h-full overflow-y-auto p-6 max-w-3xl space-y-4">
            {planFiles.document ? (
              <MarkdownRenderer content={planFiles.document.markdown} variant="document" />
            ) : currentPlan ? (
              <div className="text-xs leading-relaxed">
                <PlainText text={currentPlan.full_text} />
              </div>
            ) : null}
            {mode === 'ACT' && endorsed && (
              <div className="mt-4 rounded-md border border-zinc-700 bg-panel2/50 p-3 text-xs text-muted">
                Plan endorsed by user at {endorsed.created_at}. 30-minute plan-scoped lease is active.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
