/**
 * Store duy nhất của giao diện (zustand).
 *
 * LUẬT: store chỉ biết `ServerEvent` và `ClientCommand`. Nó KHÔNG biết dữ liệu
 * đến từ mock, WebSocket hay WebRTC — xem `src/lib/transport/index.ts`.
 *
 * Hai đại lượng `integrity_floor` và `confidentiality_ceiling` được TÍNH LẠI
 * từ toàn bộ danh sách mảnh ngữ cảnh mỗi lần có mảnh mới. Vì mảnh chỉ được
 * THÊM chứ không bị xoá, `integrity_floor` không bao giờ tự sạch lại trong
 * một task_epoch — đúng nguyên tắc N5. Đừng "dọn" ngữ cảnh để nó sạch lại.
 */
import { create } from 'zustand'
import { CONFIDENTIALITY, INTEGRITY } from '../types/labels'
import type { ContextState } from '../types/context'
import type { Lease } from '../types/lease'
import type { AgentMode, ModeSwitchProposal, PermissionRequest, PlanArtifact } from '../types/agent'
import type { ChatMessage, FileNode, TerminalLine } from '../types/ui'
import type { AuditRecord, Budget, ScreenState, SessionSummary } from '../types/session'
import type { ClientCommand, ServerEvent } from '../types/transport'
import { computeConfidentialityCeiling, computeIntegrityFloor } from '../lib/labels'
import { createTransport, type AgentTransport, type TransportStatus } from '../lib/transport'
import { ACTIVE_SESSION_ID, MOCK_SESSIONS } from '../lib/mock/sessions'
import { SCENARIO_TOTAL } from '../lib/mock/scenario'

const EMPTY_CONTEXT: ContextState = {
  chunks: [],
  integrity_floor: INTEGRITY.USER_AUTHORIZED,
  confidentiality_ceiling: CONFIDENTIALITY.PUBLIC,
}

export interface AgentState {
  transportKind: 'mock' | 'live'
  transportStatus: TransportStatus
  isBusy: boolean

  mode: AgentMode
  taskEpoch: number
  budget: Budget

  messages: ChatMessage[]
  requests: Record<string, PermissionRequest>
  proposal: ModeSwitchProposal | null

  context: ContextState
  leases: Lease[]

  files: FileNode[]
  terminal: TerminalLine[]
  screen: ScreenState | null
  planWorkspace: PlanArtifact | null
  planEndorsed: PlanArtifact | null
  audit: AuditRecord[]

  sessions: SessionSummary[]
  activeSessionId: string

  scenarioIndex: number
  scenarioTotal: number
  rejectBundle: boolean

  init: () => void
  teardown: () => void
  applyEvent: (event: ServerEvent) => void
  sendCommand: (command: ClientCommand) => void
  setRejectBundle: (value: boolean) => void
  resetScenario: () => void
}

let transport: AgentTransport | null = null
let unsubscribers: (() => void)[] = []

const initialState = () => ({
  transportKind: 'mock' as 'mock' | 'live',
  transportStatus: 'disconnected' as TransportStatus,
  isBusy: false,
  mode: 'PLAN' as AgentMode,
  taskEpoch: 1,
  budget: { steps: 0, tokens: 0, costUsd: 0, capUsd: 0.5 } satisfies Budget,
  messages: [] as ChatMessage[],
  requests: {} as Record<string, PermissionRequest>,
  proposal: null as ModeSwitchProposal | null,
  context: EMPTY_CONTEXT,
  leases: [] as Lease[],
  files: [] as FileNode[],
  terminal: [] as TerminalLine[],
  screen: null as ScreenState | null,
  planWorkspace: null as PlanArtifact | null,
  planEndorsed: null as PlanArtifact | null,
  audit: [] as AuditRecord[],
  sessions: MOCK_SESSIONS,
  activeSessionId: ACTIVE_SESSION_ID,
  scenarioIndex: 0,
  scenarioTotal: SCENARIO_TOTAL,
  rejectBundle: false,
})

export const useAgentStore = create<AgentState>((set, get) => ({
  ...initialState(),

  init: () => {
    if (transport) return
    transport = createTransport()
    set({ transportKind: transport.kind })
    unsubscribers = [
      transport.subscribe((event) => get().applyEvent(event)),
      transport.onStatusChange((status) => set({ transportStatus: status })),
    ]
    void transport.connect(get().activeSessionId)
  },

  teardown: () => {
    for (const off of unsubscribers) off()
    unsubscribers = []
    transport?.disconnect()
    transport = null
  },

  sendCommand: (command) => {
    if (command.type === 'scenario_reset') {
      const rejectBundle = get().rejectBundle
      set({ ...initialState(), rejectBundle, transportKind: transport?.kind ?? 'mock' })
    }
    if (command.type === 'user_message') {
      set({ isBusy: true })
    } else if (command.type === 'interrupt') {
      set({ isBusy: false })
    }
    transport?.send(command)
  },

  setRejectBundle: (value) => {
    set({ rejectBundle: value })
    transport?.send({ type: 'scenario_set_reject_bundle', value })
  },

  resetScenario: () => {
    get().sendCommand({ type: 'scenario_reset' })
  },

  applyEvent: (event) => set((state) => reduce(state, event)),
}))

/** Reducer thuần — tách khỏi store để test được mà không cần React. */
export function reduce(state: AgentState, event: ServerEvent): Partial<AgentState> {
  switch (event.type) {
    case 'user_message_echo':
      return {
        isBusy: true,
        messages: [
          ...state.messages,
          { id: event.message_id, kind: 'user_text', text: event.text, created_at: nowIso() },
        ],
      }

    case 'system_note':
      return {
        isBusy: false,
        messages: [
          ...state.messages,
          { id: event.message_id, kind: 'system_note', text: event.text, created_at: nowIso() },
        ],
      }

    // ── Phản hồi của Agent (hỗ trợ kèm danh sách Referenced Files) ──
    case 'agent_message':
      return {
        isBusy: false,
        messages: [
          ...state.messages,
          {
            id: event.message_id,
            kind: 'agent_text',
            text: event.text,
            files: event.files,
            label_id: event.label.label_id,
            integrity: event.label.integrity,
            confidentiality: event.label.confidentiality,
            created_at: nowIso(),
          },
        ],
      }

    // ── Ảnh chụp màn hình từ sandbox/browser của Agent (hỗ trợ Lightbox) ──
    case 'screenshot':
      return {
        messages: [
          ...state.messages,
          {
            id: event.message_id,
            kind: 'screenshot',
            image_url: event.image_url,
            caption: event.caption,
            source_url: event.source_url,
            width: event.width,
            height: event.height,
            label_id: event.label?.label_id,
            integrity: event.label?.integrity,
            confidentiality: event.label?.confidentiality,
            created_at: nowIso(),
          },
        ],
      }

    // ── Video quay màn hình phiên làm việc từ sandbox/browser của Agent (hỗ trợ Media Lightbox) ──
    case 'screen_recording':
      return {
        messages: [
          ...state.messages,
          {
            id: event.message_id,
            kind: 'screen_recording',
            video_url: event.video_url,
            poster_url: event.poster_url,
            caption: event.caption,
            source_url: event.source_url,
            duration_seconds: event.duration_seconds,
            width: event.width,
            height: event.height,
            label_id: event.label?.label_id,
            integrity: event.label?.integrity,
            confidentiality: event.label?.confidentiality,
            created_at: nowIso(),
          },
        ],
      }

    case 'step_started':
      return {
        isBusy: true,
        taskEpoch: event.task_epoch,
        messages: [
          ...state.messages,
          { id: event.step_id, kind: 'agent_step', thought: '', created_at: nowIso() },
        ],
      }

    case 'agent_thought':
      return { messages: patchStep(state.messages, event.step_id, { thought: event.thought }) }

    case 'tool_called':
      return {
        messages: patchStep(state.messages, event.step_id, {
          tool_name: event.tool_name,
          params: event.params,
        }),
      }

    case 'tool_result':
      return {
        messages: patchStep(state.messages, event.step_id, {
          result_preview: event.result_preview,
          truncated_lines: event.truncated_lines,
          label_id: event.label.label_id,
          integrity: event.label.integrity,
          confidentiality: event.label.confidentiality,
        }),
      }

    case 'permission_requested':
      return {
        isBusy: false,
        requests: { ...state.requests, [event.request.request_id]: event.request },
        messages: [
          ...state.messages,
          {
            id: `pr-${event.request.request_id}`,
            kind: 'permission_request',
            request_id: event.request.request_id,
            created_at: nowIso(),
          },
        ],
      }

    case 'permission_resolved': {
      const existing = state.requests[event.request_id]
      if (!existing) return {}
      return {
        requests: {
          ...state.requests,
          [event.request_id]: { ...existing, status: event.status, decision: event.decision },
        },
      }
    }

    case 'mode_switch_proposed':
      return {
        isBusy: false,
        proposal: event.proposal,
        messages: [
          ...state.messages,
          { id: `ms-${state.messages.length}`, kind: 'mode_switch', created_at: nowIso() },
        ],
      }

    case 'mode_switched':
      return {
        mode: event.mode,
        taskEpoch: event.task_epoch,
        sessions: patchActiveSession(state, { mode: event.mode }),
      }

    case 'label_added': {
      const chunks = [...state.context.chunks, event.chunk]
      return {
        context: {
          chunks,
          // Tính lại từ TOÀN BỘ danh sách. Mảnh chỉ được thêm, nên floor không
          // bao giờ tự tốt lên — nguyên tắc N5.
          integrity_floor: computeIntegrityFloor(chunks),
          confidentiality_ceiling: computeConfidentialityCeiling(chunks),
        },
      }
    }

    case 'lease_granted': {
      const others = state.leases.filter((lease) => lease.lease_id !== event.lease.lease_id)
      const leases = [...others, event.lease]
      return { leases, sessions: patchActiveSession(state, { active_lease_count: countActive(leases) }) }
    }

    case 'lease_invalidated': {
      const leases = state.leases.map((lease) =>
        lease.lease_id === event.lease_id
          ? {
              ...lease,
              status: event.status,
              revoked: event.status === 'bi_thu_hoi',
              granted_reason: `${lease.granted_reason} — ${event.reason}`,
            }
          : lease,
      )
      return { leases, sessions: patchActiveSession(state, { active_lease_count: countActive(leases) }) }
    }

    case 'budget_updated':
      return { budget: event.budget }

    case 'terminal_line':
      return { terminal: [...state.terminal, event.line] }

    case 'files_updated':
      return { files: event.files }

    case 'screen_frame':
      return { screen: event.screen }

    case 'audit_appended':
      // Sổ audit CHỈ THÊM, không sửa, không xoá (mục 9.7).
      return { audit: [...state.audit, event.record] }

    case 'plan_updated':
      return { planWorkspace: event.workspace, planEndorsed: event.endorsed }

    case 'task_finished':
      return {
        sessions: patchActiveSession(state, {
          status: event.reason === 'reset' ? 'dang_chay' : 'xong',
        }),
      }

    case 'scenario_progress':
      return { scenarioIndex: event.index, scenarioTotal: event.total }

    case 'screen_offer':
    case 'screen_answer':
    case 'screen_ice':
      // Signaling WebRTC không thay đổi state — `WebRtcScreenTransport` xử lý.
      return {}
  }
}

function nowIso(): string {
  return new Date().toISOString()
}

function countActive(leases: readonly Lease[]): number {
  return leases.filter((lease) => lease.status === 'con_hieu_luc').length
}

function patchActiveSession(state: AgentState, patch: Partial<SessionSummary>): SessionSummary[] {
  return state.sessions.map((session) =>
    session.session_id === state.activeSessionId ? { ...session, ...patch } : session,
  )
}

/** Cập nhật một bước ReAct đang mở, giữ nguyên các bước khác. */
function patchStep(
  messages: readonly ChatMessage[],
  stepId: string,
  patch: Partial<Extract<ChatMessage, { kind: 'agent_step' }>>,
): ChatMessage[] {
  return messages.map((message) =>
    message.kind === 'agent_step' && message.id === stepId ? { ...message, ...patch } : message,
  )
}
