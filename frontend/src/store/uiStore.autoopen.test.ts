/**
 * Luật tự mở tab — `docs/plan/next-batch-contract.md` §3.
 *
 * `ui_intent` (và các ý định suy ra từ `plan_written` / `decision_requested` /
 * `design_canvas`) chỉ là GỢI Ý: giao diện quyết định mở hay xếp hàng theo đúng
 * bốn điều kiện, dừng ở điều kiện đầu tiên vi phạm. Ý định bị chặn nằm trong
 * `pendingIntents` để tab đích hiện huy hiệu đếm, và mở tab đó sẽ tiêu thụ hết
 * hàng đợi của nó. Ý định bị chặn gần nhất còn ghi lại LÝ DO cổng vào
 * `pendingIntentNotice` — hàng thông báo cạnh khung soạn tin đọc giá trị này để
 * người dùng thấy vì sao chưa mở được (không chỉ thấy huy hiệu số).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AUTO_OPEN_IDLE_MS, MAX_PENDING_TAB_INTENTS, useUiStore } from './uiStore'

function resetStore() {
  localStorage.clear()
  useUiStore.setState({
    openTabs: [],
    activeTab: null,
    panelFullscreen: false,
    pendingIntents: [],
    pendingIntentNotice: null,
    workspaceHidden: false,
    pinnedTab: null,
    lastUserActivityAt: 0,
    autoOpenTabs: true,
    autoOpenOnlyWhenIdle: true,
    tabIntentTargets: {},
    planRevision: 0,
    sessionScrollOffsets: {},
  })
}

beforeEach(resetStore)

describe('uiStore — luật tự mở tab (hợp đồng §3)', () => {
  it('mở tab ngay khi người dùng đang rảnh', () => {
    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'plan', target: { identity: 'agent-box-plan' }, reason: 'plan_written' })

    expect(outcome).toBe('opened')
    expect(useUiStore.getState().activeTab).toBe('plan')
    expect(useUiStore.getState().openTabs).toContain('plan')
    expect(useUiStore.getState().tabIntentTargets.plan).toMatchObject({ identity: 'agent-box-plan' })
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('điều kiện 1 — công tắc tắt thì chỉ xếp hàng', () => {
    useUiStore.setState({ autoOpenTabs: false })
    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'decisions', target: { requestId: 'd1' }, reason: 'decision_requested' })

    expect(outcome).toBe('queued')
    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)
    expect(useUiStore.getState().pendingIntents[0]).toMatchObject({
      tab: 'decisions',
      target: { requestId: 'd1' },
      reason: 'decision_requested',
    })
  })

  it('điều kiện 2 — tab đã được người dùng ghim thì không cướp vị trí', () => {
    useUiStore.getState().openTab('decisions')
    useUiStore.getState().pinTab('decisions')

    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'decisions', target: { requestId: 'd2' }, reason: 'decision_requested' })

    expect(outcome).toBe('queued')
    expect(useUiStore.getState().activeTab).toBe('decisions')
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)
  })

  it('điều kiện 3 — vừa gõ phím/cuộn trong 15s thì chờ', () => {
    useUiStore.getState().noteUserActivity()
    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'plan', target: { identity: 'p' }, reason: 'plan_written' })

    expect(outcome).toBe('queued')
    expect(AUTO_OPEN_IDLE_MS).toBe(15000)

    // Rảnh trở lại → ý định mới được mở ngay.
    useUiStore.setState({ lastUserActivityAt: Date.now() - AUTO_OPEN_IDLE_MS - 1 })
    const second = useUiStore
      .getState()
      .requestTabIntent({ tab: 'plan', target: { identity: 'p' }, reason: 'plan_written' })
    expect(second).toBe('opened')
  })

  it('tắt "chỉ khi rảnh" thì mở ngay dù vừa có hoạt động', () => {
    useUiStore.setState({ autoOpenOnlyWhenIdle: false })
    useUiStore.getState().noteUserActivity()

    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'subagents', target: { sessionId: 'child-1' }, reason: 'child_started' })

    expect(outcome).toBe('opened')
    expect(useUiStore.getState().tabIntentTargets.subagents).toMatchObject({ sessionId: 'child-1' })
  })

  it('mở tab tiêu thụ hàng đợi của chính tab đó, giữ đích của ý định mới nhất', () => {
    useUiStore.setState({ autoOpenTabs: false })
    const { requestTabIntent } = useUiStore.getState()
    requestTabIntent({ tab: 'plan', target: { identity: 'v1-plan', version: 1 }, reason: 'plan_written' })
    requestTabIntent({ tab: 'decisions', target: { requestId: 'd1' }, reason: 'decision_requested' })
    requestTabIntent({ tab: 'plan', target: { identity: 'v2-plan', version: 2 }, reason: 'plan_written' })
    expect(useUiStore.getState().pendingIntents).toHaveLength(3)

    useUiStore.getState().openTab('plan')

    const state = useUiStore.getState()
    expect(state.activeTab).toBe('plan')
    expect(state.pendingIntents.map((intent) => intent.tab)).toEqual(['decisions'])
    expect(state.tabIntentTargets.plan).toMatchObject({ identity: 'v2-plan', version: 2 })
  })

  it('hàng đợi chỉ giữ 20 ý định gần nhất', () => {
    useUiStore.setState({ autoOpenTabs: false })
    for (let i = 0; i < MAX_PENDING_TAB_INTENTS + 5; i += 1) {
      useUiStore
        .getState()
        .requestTabIntent({ tab: 'plan', target: { identity: `p${i}` }, reason: 'plan_written' })
    }

    const pending = useUiStore.getState().pendingIntents
    expect(pending).toHaveLength(MAX_PENDING_TAB_INTENTS)
    // Mới nhất ở cuối, cũ nhất bị cắt.
    expect(pending.at(-1)?.target).toMatchObject({ identity: `p${MAX_PENDING_TAB_INTENTS + 4}` })
    expect(pending.some((intent) => intent.target?.identity === 'p0')).toBe(false)
  })

  it('đóng tab thì bỏ ghim của tab đó', () => {
    useUiStore.getState().openTab('plan')
    useUiStore.getState().pinTab('plan')
    expect(useUiStore.getState().pinnedTab).toBe('plan')

    useUiStore.getState().closeTab('plan')
    expect(useUiStore.getState().pinnedTab).toBeNull()
  })

  it('planRevision tăng khi agent ghi kế hoạch mới', () => {
    const before = useUiStore.getState().planRevision
    useUiStore.getState().bumpPlanRevision()
    expect(useUiStore.getState().planRevision).toBe(before + 1)
  })

  it('nhớ vị trí cuộn theo từng phiên', () => {
    useUiStore.getState().rememberSessionScroll('chat-a', 420)
    useUiStore.getState().rememberSessionScroll('chat-b', 12)
    expect(useUiStore.getState().sessionScrollOffsets).toMatchObject({ 'chat-a': 420, 'chat-b': 12 })
  })
})

/**
 * B12(b) — ý định bị xếp hàng vì CỬA SỔ RẢNH phải tự mở khi cửa sổ hết, không
 * được nằm chờ vô hạn (trước bản sửa chỉ `openTab` của người dùng mới tiêu thụ
 * hàng đợi). Đồng hồ giả để đo đúng mốc `AUTO_OPEN_IDLE_MS` mà không phải ngồi đợi.
 */
describe('uiStore — hàng đợi tự mở khi hết cửa sổ rảnh (B12)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  /** Đẩy đồng hồ giả qua `ms` và để mọi hẹn giờ đã tới hạn chạy. */
  function tick(ms: number) {
    vi.advanceTimersByTime(ms)
  }

  it('ý định bị chặn lúc đang bận sẽ tự mở khi hết 15 giây rảnh', () => {
    useUiStore.getState().noteUserActivity()
    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'decisions', target: { requestId: 'd1' }, reason: 'decision_requested' })
    expect(outcome).toBe('queued')
    expect(useUiStore.getState().activeTab).toBeNull()

    // `+10` vì bộ hẹn giờ cố tình nằm SAU mốc cửa sổ 1ms (tránh hụt biên).
    tick(AUTO_OPEN_IDLE_MS + 10)

    const state = useUiStore.getState()
    expect(state.activeTab).toBe('decisions')
    expect(state.openTabs).toContain('decisions')
    expect(state.pendingIntents).toEqual([])
    expect(state.tabIntentTargets.decisions).toMatchObject({ requestId: 'd1' })
  })

  it('cửa sổ bị gia hạn (người dùng còn bận) thì hàng đợi chờ tiếp, không mất', () => {
    useUiStore.getState().noteUserActivity()
    useUiStore.getState().requestTabIntent({ tab: 'plan', target: { identity: 'p' }, reason: 'plan_written' })

    // Người dùng vẫn đang gõ: hết 10s lại có hoạt động mới.
    tick(10000)
    useUiStore.getState().noteUserActivity()
    expect(useUiStore.getState().activeTab).toBeNull()

    // Lần tỉnh đầu tiên (mốc cũ, T0+15s) thấy cửa sổ MỚI còn hiệu lực ⇒ tự hẹn
    // lại cho hết cửa sổ hiện tại thay vì mở sớm hay làm mất ý định.
    tick(AUTO_OPEN_IDLE_MS - 10000 + 1)
    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)

    // Hết cửa sổ MỚI (T0+10s+15s) thì mở.
    tick(AUTO_OPEN_IDLE_MS)
    expect(useUiStore.getState().activeTab).toBe('plan')
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('tab đang được ghim thì bản tự mở cũng không cướp', () => {
    useUiStore.getState().openTab('decisions')
    useUiStore.getState().pinTab('decisions')

    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'decisions', target: { requestId: 'd2' }, reason: 'decision_requested' })
    expect(outcome).toBe('queued')

    // Người dùng rảnh hẳn — luật vẫn không cho cướp tab đã ghim.
    useUiStore.setState({ lastUserActivityAt: Date.now() - AUTO_OPEN_IDLE_MS - 1 })
    tick(AUTO_OPEN_IDLE_MS * 2)
    expect(useUiStore.getState().activeTab).toBe('decisions')
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)
  })

  it('công tắc "chỉ khi rảnh" tắt → hàng đợi mở ngay, không chờ hết cửa sổ', () => {
    useUiStore.getState().noteUserActivity()
    expect(
      useUiStore.getState().requestTabIntent({ tab: 'subagents', target: { sessionId: 'c1' }, reason: 'child_started' }),
    ).toBe('queued')

    useUiStore.getState().setAutoOpenOnlyWhenIdle(false)

    expect(useUiStore.getState().activeTab).toBe('subagents')
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('bật lại công tắc tổng → hàng đợi cũng được mở', () => {
    useUiStore.setState({ autoOpenTabs: false })
    expect(
      useUiStore.getState().requestTabIntent({ tab: 'plan', target: { identity: 'p' }, reason: 'plan_written' }),
    ).toBe('queued')

    useUiStore.getState().setAutoOpenTabs(true)

    expect(useUiStore.getState().activeTab).toBe('plan')
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('công tắc tổng vẫn tắt thì hết cửa sổ cũng không mở (điều kiện 1 thắng)', () => {
    useUiStore.getState().noteUserActivity()
    useUiStore.setState({ autoOpenTabs: false })
    useUiStore.getState().requestTabIntent({ tab: 'plan', target: { identity: 'p' }, reason: 'plan_written' })

    tick(AUTO_OPEN_IDLE_MS * 3)

    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)
  })

  it('nhiều ý định chờ: mở hết tab liên quan trong một lần tỉnh, giữ cap', () => {
    useUiStore.getState().noteUserActivity()
    useUiStore.setState({ autoOpenTabs: false })
    const { requestTabIntent } = useUiStore.getState()
    requestTabIntent({ tab: 'plan', target: { identity: 'p1', version: 1 }, reason: 'plan_written' })
    requestTabIntent({ tab: 'decisions', target: { requestId: 'd1' }, reason: 'decision_requested' })
    requestTabIntent({ tab: 'plan', target: { identity: 'p2', version: 2 }, reason: 'plan_written' })
    expect(useUiStore.getState().pendingIntents).toHaveLength(3)

    // Người dùng rảnh hẳn, công tắc tổng bật lại ⇒ cả hàng đợi mở trong một lần.
    useUiStore.setState({ lastUserActivityAt: Date.now() - AUTO_OPEN_IDLE_MS - 1 })
    useUiStore.getState().setAutoOpenTabs(true)

    expect(useUiStore.getState().pendingIntents).toEqual([])
    // Mỗi tab mở đúng MỘT lần dù có hai ý định cho `plan`.
    expect([...useUiStore.getState().openTabs].sort()).toEqual(['decisions', 'plan'])
    // Đích của ý định MỚI NHẤT của tab plan, không phải bản cũ.
    expect(useUiStore.getState().tabIntentTargets.plan).toMatchObject({ identity: 'p2', version: 2 })
  })

  it('hết cửa sổ rảnh thì hàng đợi tự mở và hàng thông báo tự biến mất', () => {
    useUiStore.getState().noteUserActivity()
    expect(
      useUiStore.getState().requestTabIntent({ tab: 'design', target: { designId: 'd1' }, reason: 'canvas_drawn' }),
    ).toBe('queued')
    expect(useUiStore.getState().pendingIntentNotice).toMatchObject({ tab: 'design', reason: 'user busy' })

    tick(AUTO_OPEN_IDLE_MS + 10)

    expect(useUiStore.getState().activeTab).toBe('design')
    expect(useUiStore.getState().pendingIntentNotice).toBeNull()
  })

  it('hàng đợi rỗng thì không hẹn giờ nào (không rò rỉ timer)', () => {
    tick(AUTO_OPEN_IDLE_MS * 2)
    expect(vi.getTimerCount()).toBe(0)
    expect(useUiStore.getState().activeTab).toBeNull()
  })
})

/**
 * N2 — ý định xếp hàng phải NHÌN THẤY ĐƯỢC, không chỉ huy hiệu số: mỗi cổng §3
 * ghi lại LÝ DO vào `pendingIntentNotice`, và hàng đợi tiêu thụ thì thông báo tự
 * biến mất. Cùng tinh thần với B12: "có gì đó đang chờ" mà không nói vì sao thì
 * người dùng phải tự đoán.
 */
describe('uiStore — hàng thông báo ý định xếp hàng (hợp đồng §3)', () => {
  it('mở được ngay thì không có thông báo nào', () => {
    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'design', target: { designId: 'd1' }, reason: 'canvas_drawn' })

    expect(outcome).toBe('opened')
    expect(useUiStore.getState().pendingIntentNotice).toBeNull()
  })

  it.each([
    ['tabs off', () => useUiStore.setState({ autoOpenTabs: false })],
    ['workspace hidden', () => useUiStore.setState({ workspaceHidden: true })],
    [
      'tab pinned',
      () => {
        useUiStore.getState().openTab('design')
        useUiStore.getState().pinTab('design')
      },
    ],
    ['user busy', () => useUiStore.getState().noteUserActivity()],
  ] as const)('cổng "%s" → xếp hàng + thông báo mang đúng lý do', (reason, arrange) => {
    arrange()

    const outcome = useUiStore
      .getState()
      .requestTabIntent({ tab: 'design', target: { designId: 'd1' }, reason: 'canvas_drawn' })

    expect(outcome).toBe('queued')
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)
    const notice = useUiStore.getState().pendingIntentNotice
    expect(notice).toMatchObject({ tab: 'design', reason })
    expect(typeof notice?.at).toBe('number')
  })

  it('mở tab bằng tay tiêu thụ hàng đợi và xoá thông báo', () => {
    useUiStore.setState({ autoOpenTabs: false })
    useUiStore
      .getState()
      .requestTabIntent({ tab: 'design', target: { designId: 'd1' }, reason: 'canvas_drawn' })
    expect(useUiStore.getState().pendingIntentNotice?.tab).toBe('design')

    useUiStore.getState().openTab('design')

    expect(useUiStore.getState().pendingIntentNotice).toBeNull()
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('mở tab KHÁC không xoá thông báo của tab đang chờ', () => {
    useUiStore.setState({ autoOpenTabs: false })
    const { requestTabIntent } = useUiStore.getState()
    requestTabIntent({ tab: 'design', target: { designId: 'd1' }, reason: 'canvas_drawn' })
    requestTabIntent({ tab: 'plan', target: { identity: 'p' }, reason: 'plan_written' })
    // Thông báo luôn là ý định MỚI NHẤT — ở đây là plan.
    expect(useUiStore.getState().pendingIntentNotice?.tab).toBe('plan')

    useUiStore.getState().openTab('design')

    expect(useUiStore.getState().pendingIntentNotice?.tab).toBe('plan')
    expect(useUiStore.getState().pendingIntents.map((intent) => intent.tab)).toEqual(['plan'])
  })

  it('bỏ qua chỉ xoá thông báo — hàng đợi và huy hiệu vẫn còn', () => {
    useUiStore.setState({ autoOpenTabs: false })
    useUiStore
      .getState()
      .requestTabIntent({ tab: 'design', target: { designId: 'd1' }, reason: 'canvas_drawn' })

    useUiStore.getState().clearPendingIntentNotice()

    expect(useUiStore.getState().pendingIntentNotice).toBeNull()
    expect(useUiStore.getState().pendingIntents).toHaveLength(1)
  })
})
