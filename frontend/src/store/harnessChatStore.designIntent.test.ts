/**
 * Ý định mở tab Design suy ra từ event gốc `design_canvas` — hợp đồng
 * `docs/plan/next-batch-contract.md` §1 (`design_canvas` mang `designId` +
 * `actor`) và §3 (luật tự mở tab).
 *
 * Vì sao không có producer `ui_intent {tab:'design'}` thứ hai: `design_canvas`
 * đã mang `designId`, nên nhánh trong `dispatchTabIntents` là nguồn duy nhất —
 * một gợi ý song song là bản sao thứ hai của cùng một sự thật, và là chỗ trôi
 * thứ hai khi một trong hai bên đổi.
 *
 * Bốn hành vi được ghim ở đây:
 *  1. lần vẽ ĐẦU của một `designId` → mở tab Design kèm `{designId}`;
 *  2. lần vẽ sau cùng `designId` → chỉ cập nhật, không cướp tab;
 *  3. nạp lịch sử (`firstHydration`) → không mở lại canvas cũ;
 *  4. cảnh do chính chủ nhà gửi (`actor: 'user'`) → không mở.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/agentApi', () => ({ agentApi: vi.fn() }))

import { dispatchTabIntents, type HarnessEvent } from './harnessChatStore'
import { useUiStore } from './uiStore'

const canvas = (seq: number, designId: string, extra: Record<string, unknown> = {}): HarnessEvent => ({
  seq,
  type: 'design_canvas',
  data: { designId, actor: 'agent', ...extra },
  created: seq,
})

function resetUi() {
  localStorage.clear()
  useUiStore.setState({
    openTabs: [],
    activeTab: null,
    pendingIntents: [],
    pendingIntentNotice: null,
    pinnedTab: null,
    lastUserActivityAt: 0,
    autoOpenTabs: true,
    autoOpenOnlyWhenIdle: false,
    tabIntentTargets: {},
    planRevision: 0,
  })
}

beforeEach(resetUi)

describe('dispatchTabIntents — tab Design mở ở lần vẽ đầu của mỗi designId', () => {
  it('lần vẽ đầu tiên của một designId → mở tab Design với đúng designId', () => {
    const events = [canvas(4, 'design-a')]

    const next = dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(next).toBe(4)
    expect(useUiStore.getState().activeTab).toBe('design')
    expect(useUiStore.getState().openTabs).toContain('design')
    expect(useUiStore.getState().tabIntentTargets.design).toMatchObject({ designId: 'design-a' })
  })

  it('lần vẽ thứ hai cùng designId chỉ là cập nhật trạng thái — không mở lại', () => {
    const first = canvas(4, 'design-a')
    dispatchTabIntents({ allEvents: [first], freshEvents: [first], lastSeq: 0, firstHydration: false })
    // Người dùng đã rời tab (hoặc đóng nó) trước khi agent vẽ tiếp.
    useUiStore.setState({ activeTab: null, openTabs: [], tabIntentTargets: {} })

    const second = canvas(9, 'design-a')
    dispatchTabIntents({ allEvents: [first, second], freshEvents: [second], lastSeq: 4, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().openTabs).toEqual([])
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('designId khác là một artifact mới → mở', () => {
    const first = canvas(4, 'design-a')
    dispatchTabIntents({ allEvents: [first], freshEvents: [first], lastSeq: 0, firstHydration: false })
    useUiStore.setState({ activeTab: null, openTabs: [], tabIntentTargets: {} })

    const second = canvas(9, 'design-b')
    dispatchTabIntents({ allEvents: [first, second], freshEvents: [second], lastSeq: 4, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBe('design')
    expect(useUiStore.getState().tabIntentTargets.design).toMatchObject({ designId: 'design-b' })
  })

  it('nạp lịch sử lần đầu (firstHydration) không mở lại canvas cũ', () => {
    const events = [canvas(4, 'design-a')]

    const next = dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: true })

    expect(next).toBe(4)
    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().openTabs).toEqual([])
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it("cảnh do chính chủ nhà gửi (actor: 'user') không cướp tab", () => {
    const events = [canvas(4, 'design-a', { actor: 'user' })]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('event thiếu designId bị bỏ qua', () => {
    const events: HarnessEvent[] = [
      { seq: 4, type: 'design_canvas', data: { actor: 'agent' }, created: 4 },
    ]

    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    expect(useUiStore.getState().activeTab).toBeNull()
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('vòng poll lại (freshEvents rỗng) không mở lại tab', () => {
    const events = [canvas(4, 'design-a')]
    const first = dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })
    expect(first).toBe(4)

    useUiStore.setState({ activeTab: null, openTabs: [], tabIntentTargets: {} })
    const second = dispatchTabIntents({ allEvents: events, freshEvents: [], lastSeq: first, firstHydration: false })

    expect(second).toBe(4)
    expect(useUiStore.getState().activeTab).toBeNull()
  })

  it('cổng §3 chặn (tab bị ghim) → ý định xếp hàng kèm lý do, không cướp tab', () => {
    useUiStore.getState().openTab('design')
    useUiStore.getState().pinTab('design')

    const events = [canvas(4, 'design-a')]
    dispatchTabIntents({ allEvents: events, freshEvents: events, lastSeq: 0, firstHydration: false })

    const state = useUiStore.getState()
    expect(state.pendingIntents.map((intent) => intent.tab)).toEqual(['design'])
    expect(state.pendingIntentNotice).toMatchObject({ tab: 'design', reason: 'tab pinned' })
  })
})
