/**
 * Luồng quyết định thật — `docs/plan/next-batch-contract.md` §1 (event),
 * §2 (`POST /api/agent/sessions/{sid}/decisions`), §4 (seam frontend).
 *
 * Ba việc được kiểm ở đây:
 *  1. `parseDecisions` dựng đúng hàng từ `decision_requested` / `decision_resolved`.
 *  2. `dispatchTabIntents` chỉ xử lý event MỚI (theo `seq`) nên vòng poll 1200ms
 *     không mở lại tab cho đúng một event; và nó mang theo `version` của bản kế
 *     hoạch vừa ghi (identity trần như `GET /__box/plans` trả về).
 *  3. `answerDecision` gọi đúng route, cập nhật chỗ chứa NGAY (không chờ poll) và
 *     để lỗi của route đi theo đường lỗi sẵn có (`sessions[id].error`).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type FakeEvent = { seq: number; type: string; data: Record<string, unknown>; created: number }

const sessions: Record<string, { id: string; status: string; events: FakeEvent[] }> = {}
const postCalls: Array<{ path: string; body: unknown; method?: string }> = []
let decisionRoute: { ok: boolean; payload: unknown; error?: string } = {
  ok: true,
  payload: { status: 'resolved', decisionId: 'd1', choice: 'approve', outcome: 'approved' },
}

vi.mock('../lib/agentApi', () => ({
  agentApi: async (path: string, body?: unknown, method?: string) => {
    if (path.includes('/decisions')) {
      // `agentApi` mặc định POST khi có body — ghi lại đúng phương thức hiệu dụng.
      postCalls.push({ path, body, method: method ?? (body === undefined ? 'GET' : 'POST') })
      if (!decisionRoute.ok) throw new Error(decisionRoute.error ?? 'Harness HTTP 409')
      return decisionRoute.payload
    }
    const id = path.split('?')[0].split('/').pop() as string
    const session = sessions[id]
    if (!session) throw new Error('Harness HTTP 404: Not found')
    return session
  },
}))

import {
  dispatchTabIntents,
  parseDecisions,
  pendingDecisions,
  useHarnessChatStore,
} from './harnessChatStore'
import { useUiStore } from './uiStore'

const CHAT = 'chat-decisions'

const requested = (seq: number, id: string, extra: Record<string, unknown> = {}): FakeEvent => ({
  seq,
  type: 'decision_requested',
  data: {
    decisionId: id,
    kind: 'question',
    question: 'Chỉ mục phiên nên nằm ở đâu?',
    options: [
      { id: 'in-harness', label: 'Giữ trong harness', kind: 'approve' },
      { id: 'in-router', label: 'Chuyển vào router', kind: 'alternative' },
      { id: 'reject', label: 'Không chọn gì', kind: 'reject' },
    ],
    deadline: 1_758_300_000.5,
    defaultChoice: 'reject',
    toolCallId: 'call-1',
    ...extra,
  },
  created: seq,
})

const resolved = (seq: number, id: string, extra: Record<string, unknown> = {}): FakeEvent => ({
  seq,
  type: 'decision_resolved',
  data: {
    decisionId: id,
    choice: 'reject',
    status: 'rejected',
    note: '',
    reason: 'timeout',
    resolvedAt: 1_758_299_000,
    ...extra,
  },
  created: seq,
})

beforeEach(() => {
  postCalls.length = 0
  decisionRoute = {
    ok: true,
    payload: { status: 'resolved', decisionId: 'd1', choice: 'approve', outcome: 'approved' },
  }
  for (const key of Object.keys(sessions)) delete sessions[key]
  useHarnessChatStore.setState({ sessions: {}, decisions: {}, intentSeq: {} })
  useUiStore.setState({
    openTabs: [],
    activeTab: null,
    pendingIntents: [],
    pinnedTab: null,
    lastUserActivityAt: 0,
    autoOpenTabs: true,
    autoOpenOnlyWhenIdle: false,
    tabIntentTargets: {},
    planRevision: 0,
  })
})

afterEach(() => {
  useHarnessChatStore.setState({ sessions: {}, decisions: {}, intentSeq: {} })
})

describe('parseDecisions', () => {
  it('dựng hàng đang chờ từ `decision_requested`', () => {
    const [entry] = parseDecisions([requested(4, 'd1')])

    expect(entry).toMatchObject({
      id: 'd1',
      kind: 'question',
      question: 'Chỉ mục phiên nên nằm ở đâu?',
      deadline: 1_758_300_000.5,
      defaultChoice: 'reject',
      status: 'pending',
      choice: null,
    })
    expect(entry.options.map((option) => option.id)).toEqual(['in-harness', 'in-router', 'reject'])
    expect(pendingDecisions([entry])).toHaveLength(1)
  })

  it('đánh dấu đã xong từ `decision_resolved` (kể cả khi hết hạn)', () => {
    const [entry] = parseDecisions([requested(4, 'd1'), resolved(9, 'd1')])

    expect(entry.status).toBe('rejected')
    expect(entry.choice).toBe('reject')
    expect(entry.resolvedReason).toBe('timeout')
    expect(pendingDecisions([entry])).toEqual([])
  })

  it('giữ kết cục `answered` của chữ tự nhập, không hoá thành `approved` (P4)', () => {
    // P4 (vá vòng soát) — `decision_resolved` mang `status: 'answered'`: hàng phải đọc ra đúng
    // chữ ấy, nếu không nó rơi vào nhánh mặc định và hiện như một lời duyệt.
    const [entry] = parseDecisions([
      requested(4, 'd1', {
        options: [
          { id: 'reject', label: 'Không chọn gì', kind: 'reject' },
          { id: 'other', label: 'Khác (tự nhập)', kind: 'alternative', allowFreeText: true },
        ],
      }),
      resolved(9, 'd1', { status: 'answered', choice: 'other', note: 'Không đồng ý, sửa lại phần X', reason: 'user' }),
    ])

    expect(entry.status).toBe('answered')
    expect(entry.choice).toBe('other')
    expect(entry.note).toBe('Không đồng ý, sửa lại phần X')
    expect(pendingDecisions([entry])).toEqual([])
  })

  it('bỏ qua lựa chọn hỏng nhưng giữ hàng lại', () => {
    const [entry] = parseDecisions([
      requested(4, 'd1', { options: [{ id: 1, label: 2 }, { id: 'ok', label: 'Được', kind: 'approve' }] }),
    ])

    expect(entry.options).toEqual([{ id: 'ok', label: 'Được', kind: 'approve' }])
  })

  it('giữ cờ `allowFreeText` của lựa chọn tự nhập (P4)', () => {
    const [entry] = parseDecisions([
      requested(5, 'd1', {
        options: [
          { id: 'in-harness', label: 'Giữ trong harness', kind: 'approve' },
          { id: 'other', label: 'Khác (tự nhập)', kind: 'alternative', allowFreeText: true },
        ],
      }),
    ])

    expect(entry.options).toEqual([
      { id: 'in-harness', label: 'Giữ trong harness', kind: 'approve' },
      { id: 'other', label: 'Khác (tự nhập)', kind: 'alternative', allowFreeText: true },
    ])
  })

  it('`request_approval` giữ nguyên kind, action và lý do', () => {
    const [entry] = parseDecisions([
      requested(2, 'a1', {
        kind: 'approval',
        question: null,
        action: 'write_file(path=/workspace/.plans/v1-pilot.md)',
        reason: 'Đường dẫn ngoài vùng tôi được ghi tự do',
      }),
    ])

    expect(entry.kind).toBe('approval')
    expect(entry.action).toContain('write_file')
    expect(entry.reason).toContain('ngoài vùng')
  })
})

describe('dispatchTabIntents', () => {
  it('chỉ xử lý event mới — poll lại cùng `seq` không mở lại tab', () => {
    const events = [requested(3, 'd1')]

    const first = dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })
    expect(first).toBe(3)
    expect(useUiStore.getState().pendingIntents).toEqual([])
    expect(useUiStore.getState().activeTab).toBe('decisions')

    // Vòng poll sau: cùng event (seq ≤ mốc đã xử lý) → không có ý định nào.
    useUiStore.setState({ activeTab: null, openTabs: [], tabIntentTargets: {} })
    const second = dispatchTabIntents({ allEvents: events, freshEvents: [], lastSeq: first, firstHydration: false })
    expect(second).toBe(3)
    expect(useUiStore.getState().activeTab).toBeNull()
  })

  it('kế hoạch vừa ghi → tăng planRevision và mở tab Plan đúng (identity, version)', () => {
    const events: FakeEvent[] = [
      { seq: 7, type: 'plan_written', data: { identity: 'agent-box-plan', version: 2, slug: 'agent-box-plan', relativePath: 'agent-box-plan/v2-agent-box-plan.md' }, created: 7 },
    ]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(useUiStore.getState().planRevision).toBe(1)
    expect(useUiStore.getState().activeTab).toBe('plan')
    // Identity trần như `GET /__box/plans` trả về — không kèm `vN-`, và version
    // là số nguyên riêng.
    expect(useUiStore.getState().tabIntentTargets.plan).toMatchObject({
      identity: 'agent-box-plan',
      version: 2,
    })
  })

  it('lần nạp đầu của một phiên có sẵn không mở lại tab Plan cho kế hoạch cũ', () => {
    const events: FakeEvent[] = [
      { seq: 1, type: 'plan_written', data: { identity: 'old-plan', version: 1 }, created: 1 },
    ]

    const next = dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: true })

    expect(next).toBe(1)
    expect(useUiStore.getState().planRevision).toBe(0)
    expect(useUiStore.getState().activeTab).toBeNull()
  })

  it('quyết định đã được trả lời trước đó thì không mở lại tab Decisions', () => {
    const events: FakeEvent[] = [requested(2, 'd9'), resolved(5, 'd9', { reason: 'user', status: 'approved' })]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('nạp lại trang một phiên có quyết định cũ thì không mở tab Decisions', () => {
    // Hàng `ui_intent` thật nằm ngay sau `decision_requested` trong event log nên khi
    // nạp lại trang nó vẫn còn nguyên: giống tab Plan, lần nạp đầu phải bỏ qua nó,
    // nếu không tab Decisions tự mở và huy hiệu đếm đầy ý định ảo (tối đa 20).
    const past = (base: number, id: string): FakeEvent[] => [
      requested(base, id),
      {
        seq: base + 1,
        type: 'ui_intent',
        data: { tab: 'decisions', target: { requestId: id }, reason: 'decision_requested' },
        created: base + 1,
      },
      resolved(base + 2, id, { reason: 'user', status: 'approved' }),
    ]
    const events: FakeEvent[] = [...past(1, 'd1'), ...past(4, 'd2'), ...past(7, 'd3')]

    const next = dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: true })

    expect(next).toBe(9)
    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().openTabs).toEqual([])
    expect(useUiStore.getState().pendingIntents).toEqual([])
    expect(useUiStore.getState().tabIntentTargets.decisions).toBeUndefined()
  })

  it('lần nạp đầu vẫn mở tab cho quyết định CÒN chờ (không bị bỏ qua như hàng `ui_intent`)', () => {
    const events: FakeEvent[] = [
      requested(2, 'd-live'),
      {
        seq: 3,
        type: 'ui_intent',
        data: { tab: 'decisions', target: { requestId: 'd-live' }, reason: 'decision_requested' },
        created: 3,
      },
    ]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: true })

    expect(useUiStore.getState().activeTab).toBe('decisions')
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('`ui_intent` đi kèm không nhân đôi ý định của event gốc (tab, đích)', () => {
    useUiStore.setState({ autoOpenOnlyWhenIdle: true, lastUserActivityAt: Date.now() })
    const events: FakeEvent[] = [
      { seq: 4, type: 'plan_written', data: { identity: 'agent-box-plan', version: 2 }, created: 4 },
      {
        seq: 5,
        type: 'ui_intent',
        data: { tab: 'plan', target: { version: 2, identity: 'agent-box-plan' }, reason: 'plan_written' },
        created: 5,
      },
    ]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    const queued = useUiStore.getState().pendingIntents
    expect(queued).toHaveLength(1)
    expect(queued[0].tab).toBe('plan')
  })

  it('`ui_intent` không có event gốc vẫn được tôn trọng (tab Files)', () => {
    const events: FakeEvent[] = [
      {
        seq: 6,
        type: 'ui_intent',
        data: { tab: 'files', target: { path: 'reports/summary.md' }, reason: 'file_written' },
        created: 6,
      },
    ]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBe('files')
    expect(useUiStore.getState().tabIntentTargets.files).toEqual({ path: 'reports/summary.md' })
  })

  it('`ui_intent` cho tab lạ thì bỏ qua', () => {
    const events: FakeEvent[] = [
      { seq: 7, type: 'ui_intent', data: { tab: 'terminal', reason: 'whatever' }, created: 7 },
    ]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })
})

describe('refresh — chỗ chứa quyết định', () => {
  it('đọc quyết định thật từ event của phiên', async () => {
    sessions['sid-d'] = { id: 'sid-d', status: 'awaiting_decision', events: [requested(1, 'd1')] }
    useHarnessChatStore.setState({ sessions: { [CHAT]: { id: 'sid-d', status: 'running', events: [], error: null } } })

    await useHarnessChatStore.getState().refresh(CHAT)

    const decisions = useHarnessChatStore.getState().decisions[CHAT]
    expect(decisions).toHaveLength(1)
    expect(decisions[0].id).toBe('d1')
    expect(useHarnessChatStore.getState().sessions[CHAT].status).toBe('awaiting_decision')
  })

  it('vòng poll muộn không kéo một mục vừa trả lời về `pending`', async () => {
    sessions['sid-e'] = { id: 'sid-e', status: 'running', events: [requested(1, 'd1')] }
    useHarnessChatStore.setState({ sessions: { [CHAT]: { id: 'sid-e', status: 'running', events: [], error: null } } })
    await useHarnessChatStore.getState().refresh(CHAT)

    await useHarnessChatStore.getState().answerDecision(CHAT, 'd1', 'in-harness')
    expect(useHarnessChatStore.getState().decisions[CHAT][0].status).toBe('approved')

    await useHarnessChatStore.getState().refresh(CHAT)
    expect(useHarnessChatStore.getState().decisions[CHAT][0].status).toBe('approved')
  })
})

describe('answerDecision', () => {
  beforeEach(async () => {
    sessions['sid-a'] = { id: 'sid-a', status: 'awaiting_decision', events: [requested(1, 'd1')] }
    useHarnessChatStore.setState({ sessions: { [CHAT]: { id: 'sid-a', status: 'awaiting_decision', events: [], error: null } } })
    await useHarnessChatStore.getState().refresh(CHAT)
  })

  it('gọi đúng route rồi cập nhật NGAY, không chờ poll', async () => {
    // Hợp đồng §2: 200 trả lại đúng `choice` đã gửi.
    decisionRoute = {
      ok: true,
      payload: { status: 'resolved', decisionId: 'd1', choice: 'in-harness', outcome: 'approved' },
    }

    await useHarnessChatStore.getState().answerDecision(CHAT, 'd1', 'in-harness', 'gọn hơn')

    expect(postCalls).toHaveLength(1)
    expect(postCalls[0].path).toBe('/sessions/sid-a/decisions')
    expect(postCalls[0].method).toBe('POST')
    expect(postCalls[0].body).toEqual({ decisionId: 'd1', choice: 'in-harness', note: 'gọn hơn' })

    const entry = useHarnessChatStore.getState().decisions[CHAT][0]
    expect(entry).toMatchObject({
      status: 'approved',
      choice: 'in-harness',
      note: 'gọn hơn',
      resolvedReason: 'user',
    })
    expect(entry.resolvedAt).toBeTypeOf('number')
  })

  it('chữ tự nhập (`outcome: answered`) không bị ghi thành `approved` ngay tại chỗ', async () => {
    decisionRoute = {
      ok: true,
      payload: { status: 'resolved', decisionId: 'd1', choice: 'other', outcome: 'answered' },
    }

    await useHarnessChatStore.getState().answerDecision(CHAT, 'd1', 'other', 'Không đồng ý, sửa lại phần X')

    const entry = useHarnessChatStore.getState().decisions[CHAT][0]
    expect(entry.status).toBe('answered')
    expect(entry.note).toBe('Không đồng ý, sửa lại phần X')
  })

  it('route trả về thiếu `choice` thì vẫn lấy lựa chọn vừa gửi', async () => {
    decisionRoute = { ok: true, payload: { status: 'resolved', decisionId: 'd1', outcome: 'approved' } }

    await useHarnessChatStore.getState().answerDecision(CHAT, 'd1', 'in-router')

    expect(useHarnessChatStore.getState().decisions[CHAT][0].choice).toBe('in-router')
  })

  it('lỗi của route hiện qua đường lỗi sẵn có và hàng vẫn đang chờ', async () => {
    decisionRoute = { ok: false, payload: {}, error: 'DECISION_ALREADY_RESOLVED: đã trả lời' }

    await useHarnessChatStore.getState().answerDecision(CHAT, 'd1', 'in-harness')

    expect(useHarnessChatStore.getState().sessions[CHAT].error).toContain('DECISION_ALREADY_RESOLVED')
    expect(useHarnessChatStore.getState().decisions[CHAT][0].status).toBe('pending')
  })

  it('không có phiên harness thì báo lỗi rõ ràng, không gửi gì', async () => {
    await useHarnessChatStore.getState().answerDecision('chat-chua-co-phien', 'd1', 'in-harness')

    expect(postCalls).toHaveLength(0)
    expect(useHarnessChatStore.getState().sessions['chat-chua-co-phien'].error).toContain(
      'DECISION_UNKNOWN_SESSION',
    )
  })
})
