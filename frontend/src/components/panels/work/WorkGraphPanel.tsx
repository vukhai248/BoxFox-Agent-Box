/**
 * Bảng Work Graph — nơi chủ nhà xem agent chính điều phối việc.
 *
 * Mọi dữ liệu là ảnh chụp thật do harness phát (`work_graph`) hoặc trả về (`GET /work`):
 * các nút theo nhóm (khám phá → plan con → thực thi), thứ tự chạy theo DAG, từng vòng
 * produce ↔ review kèm verdict và nhận xét, yêu cầu tri thức, review toàn plan, tài liệu
 * đã ghi, thẻ duyệt và kết quả ship. Công tắc Autopilot gọi `PUT /autopilot`.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  FileText,
  GitBranch,
  LoaderCircle,
  RotateCcw,
  ShieldCheck,
  Workflow,
  XCircle,
} from 'lucide-react'
import { useT } from '../../../i18n/context'
import { useAgentStore } from '../../../store/agentStore'
import { useHarnessChatStore } from '../../../store/harnessChatStore'
import { useUiStore } from '../../../store/uiStore'
import {
  autopilotFrom,
  collectWorkRuns,
  fetchWorkRuns,
  setAutopilot,
  statusTone,
  type WorkNode,
  type WorkRound,
  type WorkRunsResponse,
  type WorkRunView,
  type WorkStage,
} from '../../../lib/workGraph'

const TONE_CLASS: Record<ReturnType<typeof statusTone>, string> = {
  ok: 'bg-emerald-500/15 text-emerald-400',
  run: 'bg-sky-500/15 text-sky-300',
  warn: 'bg-amber-500/15 text-amber-300',
  bad: 'bg-rose-500/15 text-rose-400',
  idle: 'bg-zinc-500/15 text-zinc-400',
}

const KIND_CLASS: Record<string, string> = {
  explore: 'bg-sky-500/15 text-sky-300',
  research: 'bg-violet-500/15 text-violet-300',
  design: 'bg-pink-500/15 text-pink-300',
  plan: 'bg-brand/15 text-brand',
  build: 'bg-emerald-500/15 text-emerald-300',
  debug: 'bg-orange-500/15 text-orange-300',
  testing: 'bg-teal-500/15 text-teal-300',
  simplify: 'bg-zinc-500/15 text-zinc-300',
}

const GROUPS: { id: string; kinds: string[] }[] = [
  { id: 'discover', kinds: ['explore', 'research', 'design'] },
  { id: 'plan', kinds: ['plan'] },
  { id: 'execute', kinds: ['build', 'debug', 'testing', 'simplify'] },
]

function StatusPill({ status, testId }: { status: string | null | undefined; testId?: string }) {
  return (
    <span
      data-testid={testId}
      className={`rounded px-1.5 py-px font-mono text-[10px] font-semibold uppercase ${TONE_CLASS[statusTone(status)]}`}
    >
      {status ?? '—'}
    </span>
  )
}

function StatusIcon({ status }: { status: string | null | undefined }) {
  const tone = statusTone(status)
  if (tone === 'ok') return <CheckCircle2 className="size-3.5 shrink-0 text-emerald-400" />
  if (tone === 'bad') return <XCircle className="size-3.5 shrink-0 text-rose-400" />
  if (tone === 'run') return <LoaderCircle className="size-3.5 shrink-0 animate-spin text-sky-300" />
  if (tone === 'warn') return <RotateCcw className="size-3.5 shrink-0 text-amber-300" />
  return <CircleDashed className="size-3.5 shrink-0 text-zinc-500" />
}

/** Trạng thái tổng của một nút: giai đoạn đang chạy/cuối cùng quyết định. */
export function nodeStatus(node: WorkNode): string {
  const stages = Object.values(node.stages)
  const active = stages.find((stage) => ['running', 'reviewing', 'researching'].includes(stage.status))
  if (active) return active.status
  const bad = stages.find((stage) => ['rejected', 'failed'].includes(stage.status))
  if (bad) return bad.status
  const started = stages.filter((stage) => stage.status !== 'pending')
  return started.length ? started[started.length - 1].status : 'pending'
}

export function WorkGraphPanel() {
  const t = useT()
  const chatId = useAgentStore((s) => s.activeSessionId)
  const session = useHarnessChatStore((s) => s.sessions[chatId])
  const target = useUiStore((s) => s.tabIntentTargets.work)
  const selectFile = useUiStore((s) => s.selectFile)
  const sessionId = session?.id ?? null
  const events = useMemo(() => session?.events ?? [], [session?.events])

  const [fetched, setFetched] = useState<WorkRunsResponse | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [autopilotOverride, setAutopilotOverride] = useState<boolean | null>(null)
  const [autopilotBusy, setAutopilotBusy] = useState(false)
  const [autopilotError, setAutopilotError] = useState<string | null>(null)
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [openNode, setOpenNode] = useState<string | null>(null)

  useEffect(() => {
    setFetched(null)
    setAutopilotOverride(null)
    setLoadError(null)
    setSelectedRunId(null)
    setOpenNode(null)
    if (!sessionId) return
    let cancelled = false
    fetchWorkRuns(sessionId)
      .then((body) => {
        if (!cancelled) setFetched(body)
      })
      .catch((error) => {
        if (!cancelled) setLoadError(String(error))
      })
    return () => {
      cancelled = true
    }
  }, [sessionId])

  const runs = useMemo(() => collectWorkRuns(events, fetched?.runs ?? []), [events, fetched?.runs])
  const eventAutopilot = autopilotFrom(events, fetched?.autopilot ?? false)
  const autopilot = autopilotOverride ?? eventAutopilot
  useEffect(() => setAutopilotOverride(null), [eventAutopilot])

  const targetRunId = typeof target?.runId === 'string' ? target.runId : null
  // A new tab intent (a new run, or a run that waits for approval) wins over an earlier manual pick.
  useEffect(() => setSelectedRunId(null), [target])
  const run = runs.find((item) => item.runId === (selectedRunId ?? targetRunId)) ?? runs[0] ?? null

  const toggleAutopilot = useCallback(async () => {
    if (!sessionId) return
    setAutopilotBusy(true)
    setAutopilotError(null)
    try {
      const result = await setAutopilot(sessionId, !autopilot)
      setAutopilotOverride(result.on)
    } catch (error) {
      setAutopilotError(String(error))
    } finally {
      setAutopilotBusy(false)
    }
  }, [autopilot, sessionId])

  return (
    <div className="flex h-full min-h-0 flex-col bg-bg text-fg" data-testid="work-graph-panel">
      <header className="flex flex-wrap items-center gap-3 border-b border-line px-4 py-3">
        <Workflow className="size-4 text-brand" />
        <div className="min-w-0 flex-1">
          <h2 className="text-[13px] font-semibold">{t('work.title')}</h2>
          <p className="truncate text-[11px] text-muted">{t('work.subtitle')}</p>
        </div>
        <label
          className="flex cursor-pointer items-center gap-2 text-[12px]"
          title={autopilot ? t('work.autopilotOn') : t('work.autopilotOff')}
        >
          <span className="font-medium">{t('work.autopilot')}</span>
          <button
            type="button"
            role="switch"
            aria-checked={autopilot}
            data-testid="work-autopilot-toggle"
            disabled={!sessionId || autopilotBusy}
            onClick={() => void toggleAutopilot()}
            className={`relative h-5 w-9 rounded-full transition disabled:opacity-50 ${
              autopilot ? 'bg-brand' : 'bg-zinc-600'
            }`}
          >
            <span
              className={`absolute top-0.5 size-4 rounded-full bg-white transition ${autopilot ? 'left-[18px]' : 'left-0.5'}`}
            />
          </button>
        </label>
      </header>
      {autopilotError && (
        <p className="border-b border-line px-4 py-2 text-[11px] text-rose-400" data-testid="work-autopilot-error">
          {t('work.autopilotFailed', { error: autopilotError })}
        </p>
      )}
      <p className="border-b border-line px-4 py-1.5 text-[11px] text-muted" data-testid="work-autopilot-state">
        {autopilot ? t('work.autopilotOn') : t('work.autopilotOff')}
      </p>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3 select-text">
        {loadError && runs.length === 0 && (
          <p className="text-[12px] text-rose-400">{t('work.loadFailed', { error: loadError })}</p>
        )}
        {!run && !loadError && (
          <p className="text-[12px] text-muted" data-testid="work-empty">
            {fetched && !fetched.enabled ? t('work.emptyOff') : t('work.empty')}
          </p>
        )}
        {run && (
          <RunView
            run={run}
            runs={runs}
            onSelectRun={setSelectedRunId}
            openNode={openNode}
            onToggleNode={(id) => setOpenNode((current) => (current === id ? null : id))}
            onOpenDocument={selectFile}
          />
        )}
      </div>
    </div>
  )
}

function RunView({
  run,
  runs,
  onSelectRun,
  openNode,
  onToggleNode,
  onOpenDocument,
}: {
  run: WorkRunView
  runs: WorkRunView[]
  onSelectRun: (runId: string) => void
  openNode: string | null
  onToggleNode: (id: string) => void
  onOpenDocument: (path: string) => void
}) {
  const t = useT()
  const byId = useMemo(() => new Map(run.nodes.map((node) => [node.id, node])), [run.nodes])
  const [historyOpen, setHistoryOpen] = useState(false)

  return (
    <div className="flex flex-col gap-4" data-testid="work-run" data-run-id={run.runId} data-run-status={run.status}>
      <section className="rounded-lg border border-line bg-panel p-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[13px] font-semibold">{run.title}</span>
          <StatusPill status={run.status} testId="work-run-status" />
          <span className="rounded bg-panel2 px-1.5 py-px text-[10px] font-medium uppercase text-muted">
            {t('work.flow')}: {run.flow}
          </span>
          <span className="text-[10px] text-muted">{t('work.revision', { revision: String(run.revision) })}</span>
          {runs.length > 1 && (
            <select
              className="ml-auto rounded border border-line bg-panel2 px-1.5 py-0.5 text-[11px]"
              value={run.runId}
              onChange={(event) => onSelectRun(event.target.value)}
              data-testid="work-run-select"
            >
              {runs.map((item) => (
                <option key={item.runId} value={item.runId}>
                  {item.title.slice(0, 60)} · {item.status}
                </option>
              ))}
            </select>
          )}
        </div>
        {run.goal && (
          <p className="mt-2 whitespace-pre-wrap text-[12px] text-muted">
            <span className="font-medium text-fg">{t('work.goal')}: </span>
            {run.goal}
          </p>
        )}
        {run.issues.length > 0 && (
          <div className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 p-2" data-testid="work-issues">
            <p className="text-[11px] font-semibold text-amber-300">{t('work.issues')}</p>
            <ul className="mt-1 list-disc pl-4 text-[11px] text-amber-200">
              {run.issues.map((issue) => (
                <li key={issue}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
      </section>

      {run.waves.length > 0 && (
        <section data-testid="work-waves">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">{t('work.waves')}</h3>
          <div className="flex items-stretch gap-2 overflow-x-auto pb-1">
            {run.waves.map((wave, index) => (
              <div key={index} className="flex items-stretch gap-2">
                {index > 0 && <ChevronRight className="size-4 self-center text-muted" />}
                <div className="min-w-[120px] rounded-lg border border-line bg-panel p-2" data-testid="work-wave">
                  <p className="mb-1 text-[10px] font-semibold uppercase text-muted">
                    {t('work.wave', { index: String(index + 1) })}
                    {wave.length > 1 ? ` · ${t('work.parallel')}` : ''}
                  </p>
                  <div className="flex flex-col gap-1">
                    {wave.map((id) => {
                      const node = byId.get(id)
                      return (
                        <button
                          key={id}
                          type="button"
                          onClick={() => onToggleNode(id)}
                          className="flex items-center gap-1.5 rounded bg-panel2 px-1.5 py-1 text-left text-[11px] hover:bg-brand/10"
                        >
                          <StatusIcon status={node ? nodeStatus(node) : null} />
                          <span className="font-mono font-semibold">{id}</span>
                          <span className="truncate text-muted">{node?.title}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {GROUPS.map((group) => {
        const nodes = run.nodes.filter((node) => group.kinds.includes(node.kind))
        if (nodes.length === 0) return null
        return (
          <section key={group.id} data-testid={`work-group-${group.id}`}>
            <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
              {group.kinds.map((kind) => t(`work.kind.${kind}` as 'work.kind.plan')).join(' / ')}
            </h3>
            <div className="flex flex-col gap-2">
              {nodes.map((node) => (
                <NodeCard key={node.id} node={node} open={openNode === node.id} onToggle={() => onToggleNode(node.id)} />
              ))}
            </div>
          </section>
        )
      })}

      {run.review.rounds.length > 0 && (
        <section className="rounded-lg border border-line bg-panel p-3" data-testid="work-whole-review">
          <div className="mb-2 flex items-center gap-2">
            <ShieldCheck className="size-4 text-brand" />
            <h3 className="text-[12px] font-semibold">{t('work.wholeReview')}</h3>
            <StatusPill status={run.review.status} />
          </div>
          <ol className="flex flex-col gap-2">
            {run.review.rounds.map((round, index) => (
              <li key={index} className="rounded bg-panel2 p-2">
                <div className="flex items-center gap-2 text-[11px]">
                  <span className="font-semibold">{t('work.round', { attempt: String(index + 1) })}</span>
                  <StatusPill status={round.verdict} />
                  {round.childId && <span className="font-mono text-muted">{round.childId}</span>}
                </div>
                {round.findings && (
                  <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap text-[11px] text-muted">
                    {round.findings}
                  </pre>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      {run.documents.length > 0 && (
        <section data-testid="work-documents">
          <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">{t('work.documents')}</h3>
          <ul className="flex flex-col gap-1">
            {run.documents.map((path) => (
              <li key={path}>
                <button
                  type="button"
                  onClick={() => onOpenDocument(path)}
                  className="flex items-center gap-1.5 text-[12px] text-brand hover:underline"
                >
                  <FileText className="size-3.5" />
                  <span className="font-mono">{path}</span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {(run.approval || run.ship) && (
        <section className="grid gap-2 sm:grid-cols-2">
          {run.approval && <FactsCard title={t('work.approval')} facts={run.approval} testId="work-approval" />}
          {run.ship && <FactsCard title={t('work.ship')} facts={run.ship} testId="work-ship" icon />}
        </section>
      )}

      {run.history.length > 0 && (
        <section>
          <button
            type="button"
            onClick={() => setHistoryOpen((open) => !open)}
            className="flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-muted"
          >
            {historyOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            {t('work.history')} ({run.history.length})
          </button>
          {historyOpen && (
            <ol className="mt-1 flex flex-col gap-0.5 font-mono text-[10px] text-muted" data-testid="work-history">
              {run.history.map((item, index) => (
                <li key={index}>
                  {item.at ? new Date(item.at * 1000).toLocaleTimeString() : ''} · {item.event}
                  {item.detail ? ` — ${item.detail}` : ''}
                </li>
              ))}
            </ol>
          )}
        </section>
      )}
    </div>
  )
}

function FactsCard({
  title,
  facts,
  testId,
  icon = false,
}: {
  title: string
  facts: Record<string, unknown>
  testId: string
  icon?: boolean
}) {
  const entries = Object.entries(facts).filter(([, value]) => value !== null && value !== undefined && value !== '')
  return (
    <div className="rounded-lg border border-line bg-panel p-3" data-testid={testId}>
      <div className="mb-1 flex items-center gap-1.5 text-[12px] font-semibold">
        {icon && <GitBranch className="size-3.5 text-brand" />}
        {title}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]">
        {entries.map(([key, value]) => (
          <div key={key} className="contents">
            <dt className="text-muted">{key}</dt>
            <dd className="truncate font-mono" title={typeof value === 'string' ? value : JSON.stringify(value)}>
              {typeof value === 'string' ? value : JSON.stringify(value)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

function NodeCard({ node, open, onToggle }: { node: WorkNode; open: boolean; onToggle: () => void }) {
  const t = useT()
  const status = nodeStatus(node)
  const rounds = Object.values(node.stages).reduce((sum, stage) => sum + stage.rounds.length, 0)
  return (
    <div
      className="rounded-lg border border-line bg-panel"
      data-testid="work-node"
      data-node-id={node.id}
      data-node-status={status}
    >
      <button type="button" onClick={onToggle} className="flex w-full items-center gap-2 px-3 py-2 text-left">
        {open ? <ChevronDown className="size-3.5 text-muted" /> : <ChevronRight className="size-3.5 text-muted" />}
        <StatusIcon status={status} />
        <span className="font-mono text-[11px] font-bold">{node.id}</span>
        <span
          className={`rounded px-1.5 py-px text-[10px] font-semibold uppercase ${KIND_CLASS[node.kind] ?? KIND_CLASS.simplify}`}
        >
          {t(`work.kind.${node.kind}` as 'work.kind.plan')}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12px]">{node.title}</span>
        {node.dependsOn.length > 0 && (
          <span className="hidden text-[10px] text-muted sm:inline">← {node.dependsOn.join(', ')}</span>
        )}
        {rounds > 0 && <span className="text-[10px] text-muted">{rounds}×</span>}
        <StatusPill status={status} />
      </button>
      {open && (
        <div className="flex flex-col gap-3 border-t border-line px-3 py-3" data-testid="work-node-detail">
          {node.goal && <p className="whitespace-pre-wrap text-[12px] text-muted">{node.goal}</p>}
          <FactList label={t('work.dependsOn')} items={node.dependsOn} mono />
          <FactList label={t('work.acceptance')} items={node.acceptance} />
          <FactList label={t('work.tests')} items={node.tests} mono />
          <FactList label={t('work.files')} items={node.files} mono />
          {Object.entries(node.stages).map(([name, stage]) => (
            <StageView key={name} name={name} stage={stage} />
          ))}
        </div>
      )}
    </div>
  )
}

function FactList({ label, items, mono = false }: { label: string; items: string[]; mono?: boolean }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase text-muted">{label}</p>
      <ul className={`mt-0.5 list-disc pl-4 text-[11px] ${mono ? 'font-mono' : ''}`}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

function StageView({ name, stage }: { name: string; stage: WorkStage }) {
  const t = useT()
  const [previewOpen, setPreviewOpen] = useState(false)
  return (
    <div className="rounded border border-line bg-panel2/50 p-2" data-testid={`work-stage-${name}`}>
      <div className="flex items-center gap-2 text-[11px]">
        <span className="font-semibold">{t(`work.stage.${name}` as 'work.stage.produce')}</span>
        <StatusPill status={stage.status} />
        <span className="text-muted">
          {t('work.rounds')}: {stage.rounds.length}
        </span>
        {stage.preview && (
          <button
            type="button"
            className="ml-auto text-[11px] text-brand hover:underline"
            onClick={() => setPreviewOpen((open) => !open)}
          >
            {t('work.preview')}
          </button>
        )}
      </div>
      {stage.error && <p className="mt-1 text-[11px] text-rose-400">{stage.error}</p>}
      {stage.caveats && (
        <p className="mt-1 whitespace-pre-wrap text-[11px] text-amber-400" data-testid="work-caveats">
          {t('work.caveats')}: {stage.caveats}
        </p>
      )}
      {previewOpen && stage.preview && (
        <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-bg p-2 text-[11px] text-muted">
          {stage.preview}
        </pre>
      )}
      {stage.rounds.length === 0 ? (
        <p className="mt-1 text-[11px] text-muted">{t('work.noRounds')}</p>
      ) : (
        <ol className="mt-2 flex flex-col gap-1.5">
          {stage.rounds.map((round, index) => (
            <RoundView key={index} round={round} index={index} />
          ))}
        </ol>
      )}
    </div>
  )
}

function RoundView({ round, index }: { round: WorkRound; index: number }) {
  const t = useT()
  const [open, setOpen] = useState(round.verdict === 'revise')
  return (
    <li className="rounded bg-bg p-2" data-testid="work-round" data-verdict={round.verdict ?? ''}>
      <button type="button" className="flex w-full items-center gap-2 text-left text-[11px]" onClick={() => setOpen((v) => !v)}>
        <span className="font-semibold">{t('work.round', { attempt: String(round.attempt ?? index + 1) })}</span>
        <StatusPill status={round.verdict ?? round.error ?? 'pending'} />
        <span className="truncate text-muted">
          {t('work.producer')}: {round.producerRole ?? '?'}
          {round.producerId ? ` (${round.producerId.slice(0, 8)})` : ''} → {t('work.reviewer')}:{' '}
          {round.reviewerRole ?? '?'}
          {round.reviewerId ? ` (${round.reviewerId.slice(0, 8)})` : ''}
        </span>
      </button>
      {open && (
        <div className="mt-1 flex flex-col gap-1">
          {round.error && <p className="text-[11px] text-rose-400">{round.error}</p>}
          {round.findings && (
            <>
              <p className="text-[10px] font-semibold uppercase text-muted">{t('work.findings')}</p>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap text-[11px] text-muted">{round.findings}</pre>
            </>
          )}
          {round.knowledge.length > 0 && (
            <>
              <p className="text-[10px] font-semibold uppercase text-muted">{t('work.knowledge')}</p>
              <ul className="list-disc pl-4 text-[11px]">
                {round.knowledge.map((item, position) => (
                  <li key={position}>
                    <span className="font-semibold">{item.role}</span>: {item.question}{' '}
                    <StatusPill status={item.status} />
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
    </li>
  )
}
