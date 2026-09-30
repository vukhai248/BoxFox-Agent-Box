/**
 * Work Graph — hợp đồng dữ liệu phía giao diện.
 *
 * Harness phát event `work_graph` mang ảnh chụp gọn của một lượt (`WorkGraph.view` ở backend):
 * các nút E/R/D/P/X/T, từng giai đoạn produce/execute với các vòng review, các đợt chạy song
 * song (`waves`), vòng review toàn plan, tài liệu đã ghi, thẻ duyệt và kết quả ship.
 * Ở đây chỉ có hàm THUẦN để dựng lại trạng thái từ `events[]` và hai lời gọi API.
 */
import { agentApi } from './agentApi'

export type WorkStageStatus =
  | 'pending'
  | 'running'
  | 'reviewing'
  | 'accepted'
  | 'rejected'
  | 'failed'
  | 'skipped'
  | string

export interface WorkKnowledge {
  role: string | null
  question: string | null
  childId: string | null
  status: string | null
}

export interface WorkRound {
  attempt: number | null
  producerId: string | null
  reviewerId: string | null
  producerRole: string | null
  reviewerRole: string | null
  verdict: string | null
  findings: string
  error: string | null
  knowledge: WorkKnowledge[]
}

export interface WorkStage {
  status: WorkStageStatus
  attempts: number
  preview: string
  error: string | null
  /** Open reviewer findings when an evidence node was accepted at the round cap. */
  caveats: string | null
  rounds: WorkRound[]
}

export interface WorkNode {
  id: string
  kind: string
  title: string
  goal: string
  dependsOn: string[]
  acceptance: string[]
  tests: string[]
  files: string[]
  stages: Record<string, WorkStage>
}

export interface WorkHistoryItem {
  at: number | null
  event: string
  detail: string | null
}

export interface WorkRunView {
  runId: string
  title: string
  goal: string
  flow: string
  status: string
  revision: number
  autopilot: boolean
  updatedAt: number | null
  nodes: WorkNode[]
  waves: string[][]
  issues: string[]
  review: { status: string | null; rounds: { childId: string | null; verdict: string | null; findings: string }[] }
  documents: string[]
  approval: Record<string, unknown> | null
  ship: Record<string, unknown> | null
  history: WorkHistoryItem[]
}

const str = (value: unknown): string => (typeof value === 'string' ? value : '')
const strOrNull = (value: unknown): string | null => (typeof value === 'string' && value.length > 0 ? value : null)
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)
const strList = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null

function parseRound(raw: unknown): WorkRound | null {
  const item = record(raw)
  if (!item) return null
  return {
    attempt: num(item.attempt),
    producerId: strOrNull(item.producerId),
    reviewerId: strOrNull(item.reviewerId),
    producerRole: strOrNull(item.producerRole),
    reviewerRole: strOrNull(item.reviewerRole),
    verdict: strOrNull(item.verdict),
    findings: str(item.findings),
    error: strOrNull(item.error),
    knowledge: (Array.isArray(item.knowledge) ? item.knowledge : [])
      .map(record)
      .filter((k): k is Record<string, unknown> => k !== null)
      .map((k) => ({
        role: strOrNull(k.role),
        question: strOrNull(k.question),
        childId: strOrNull(k.childId),
        status: strOrNull(k.status),
      })),
  }
}

function parseNode(raw: unknown): WorkNode | null {
  const item = record(raw)
  const id = item ? strOrNull(item.id) : null
  if (!item || !id) return null
  const stages: Record<string, WorkStage> = {}
  for (const [name, rawStage] of Object.entries(record(item.stages) ?? {})) {
    const stage = record(rawStage)
    if (!stage) continue
    stages[name] = {
      status: str(stage.status) || 'pending',
      attempts: num(stage.attempts) ?? 0,
      preview: str(stage.preview),
      error: strOrNull(stage.error),
      caveats: strOrNull(stage.caveats),
      rounds: (Array.isArray(stage.rounds) ? stage.rounds : [])
        .map(parseRound)
        .filter((round): round is WorkRound => round !== null),
    }
  }
  return {
    id,
    kind: str(item.kind) || 'plan',
    title: str(item.title) || id,
    goal: str(item.goal),
    dependsOn: strList(item.dependsOn),
    acceptance: strList(item.acceptance),
    tests: strList(item.tests),
    files: strList(item.files),
    stages,
  }
}

/** Một ảnh chụp `work_graph`; trả `null` khi thiếu `runId` (không bịa lượt). */
export function parseWorkRun(raw: unknown): WorkRunView | null {
  const item = record(raw)
  const runId = item ? strOrNull(item.runId) : null
  if (!item || !runId) return null
  const review = record(item.review) ?? {}
  return {
    runId,
    title: str(item.title) || str(item.goal) || runId,
    goal: str(item.goal),
    flow: str(item.flow) || 'mixed',
    status: str(item.status) || 'drafting',
    revision: num(item.revision) ?? 0,
    autopilot: item.autopilot === true,
    updatedAt: num(item.updatedAt),
    nodes: (Array.isArray(item.nodes) ? item.nodes : []).map(parseNode).filter((n): n is WorkNode => n !== null),
    waves: (Array.isArray(item.waves) ? item.waves : []).map(strList).filter((wave) => wave.length > 0),
    issues: strList(item.issues),
    review: {
      status: strOrNull(review.status),
      rounds: (Array.isArray(review.rounds) ? review.rounds : [])
        .map(record)
        .filter((r): r is Record<string, unknown> => r !== null)
        .map((r) => ({ childId: strOrNull(r.childId), verdict: strOrNull(r.verdict), findings: str(r.findings) })),
    },
    documents: (Array.isArray(item.documents) ? item.documents : [])
      .map((doc) => (typeof doc === 'string' ? doc : str(record(doc)?.path)))
      .filter((path) => path.length > 0),
    approval: record(item.approval),
    ship: record(item.ship),
    history: (Array.isArray(item.history) ? item.history : [])
      .map(record)
      .filter((h): h is Record<string, unknown> => h !== null)
      .map((h) => ({ at: num(h.at), event: str(h.event), detail: strOrNull(h.detail) })),
  }
}

/**
 * Các lượt Work Graph của một phiên, mới nhất trước. Ảnh chụp có `revision` cao hơn thắng —
 * `extra` (kết quả `GET /work`) và `events[]` gộp chung được theo đúng luật đó.
 */
export function collectWorkRuns(
  events: { type: string; data: Record<string, unknown> }[],
  extra: WorkRunView[] = [],
): WorkRunView[] {
  const byId = new Map<string, WorkRunView>()
  const order: string[] = []
  const put = (run: WorkRunView) => {
    const previous = byId.get(run.runId)
    if (!previous) order.push(run.runId)
    if (!previous || run.revision >= previous.revision) byId.set(run.runId, run)
  }
  for (const run of extra) put(run)
  for (const event of events) {
    if (event.type !== 'work_graph') continue
    const run = parseWorkRun(event.data)
    if (run) put(run)
  }
  return order
    .map((id) => byId.get(id)!)
    .sort((a, b) => (b.updatedAt ?? 0) - (a.updatedAt ?? 0))
}

/** Công tắc Autopilot hiện tại: event `autopilot` mới nhất thắng cấu hình phiên. */
export function autopilotFrom(
  events: { type: string; data: Record<string, unknown> }[],
  fallback: boolean,
): boolean {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index]
    if (event.type === 'autopilot' && typeof event.data.on === 'boolean') return event.data.on
  }
  return fallback
}

/** Nhóm màu cho trạng thái giai đoạn/lượt — một sự thật cho cả bảng. */
export function statusTone(status: string | null | undefined): 'ok' | 'warn' | 'bad' | 'run' | 'idle' {
  switch (status) {
    case 'accepted':
    case 'ok':
    case 'verified':
    case 'approved':
    case 'executed':
    case 'shipped':
    case 'answered':
      return 'ok'
    case 'running':
    case 'reviewing':
    case 'researching':
    case 'discovering':
    case 'verifying':
    case 'executing':
      return 'run'
    case 'revise':
    case 'needs_revision':
    case 'awaiting_approval':
    case 'blocked':
      return 'warn'
    case 'rejected':
    case 'failed':
    case 'cancelled':
      return 'bad'
    default:
      return 'idle'
  }
}

export interface WorkRunsResponse {
  enabled: boolean
  autopilot: boolean
  runs: WorkRunView[]
}

export async function fetchWorkRuns(sessionId: string): Promise<WorkRunsResponse> {
  const body = await agentApi<{ enabled?: unknown; autopilot?: unknown; runs?: unknown }>(
    `/sessions/${sessionId}/work`,
  )
  return {
    enabled: body.enabled !== false,
    autopilot: body.autopilot === true,
    runs: (Array.isArray(body.runs) ? body.runs : []).map(parseWorkRun).filter((r): r is WorkRunView => r !== null),
  }
}

export async function setAutopilot(sessionId: string, on: boolean): Promise<{ on: boolean }> {
  const body = await agentApi<{ on?: unknown }>(`/sessions/${sessionId}/autopilot`, { on }, 'PUT')
  return { on: body.on === true }
}
