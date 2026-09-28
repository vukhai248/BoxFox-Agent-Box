/**
 * Kiểm thử tính năng liên kết và khôi phục Workspace Tabs theo từng session.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { useUiStore } from './uiStore'

function resetStore() {
  localStorage.clear()
  useUiStore.setState({
    openTabs: [],
    activeTab: null,
    currentSessionId: null,
    sessionWorkspaceTabs: {},
    panelFullscreen: false,
    pendingIntents: [],
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

describe('uiStore — lưu và khôi phục Workspace Tabs theo từng session', () => {
  it('session mới chưa có dữ liệu thì mặc định chưa mở tab nào', () => {
    const store = useUiStore.getState()

    store.switchSessionTabs(null, 'session-brand-new')
    expect(useUiStore.getState().openTabs).toEqual([])
    expect(useUiStore.getState().activeTab).toBeNull()
  })

  it('session 1 mở IDE, chuyển qua session 2 không mở IDE mà giữ trạng thái của session 2', () => {
    const store = useUiStore.getState()

    // 1. Vào session-1, ban đầu chưa mở tab nào
    store.switchSessionTabs(null, 'session-1')
    expect(useUiStore.getState().openTabs).toEqual([])

    // Mở các tab IDE, Terminal
    store.openTab('ide')
    store.openTab('terminal')

    expect(useUiStore.getState().openTabs).toEqual(['ide', 'terminal'])
    expect(useUiStore.getState().activeTab).toBe('terminal')

    // 2. Chuyển sang session-2 (mới toanh)
    useUiStore.getState().switchSessionTabs('session-1', 'session-2')

    // Session 2 chưa từng mở gì -> tabs rỗng, KHÔNG mang IDE hay Terminal của session 1
    expect(useUiStore.getState().openTabs).toEqual([])
    expect(useUiStore.getState().activeTab).toBeNull()

    // 3. Trong session-2, người dùng mở Decisions
    useUiStore.getState().openTab('decisions')
    expect(useUiStore.getState().openTabs).toEqual(['decisions'])
    expect(useUiStore.getState().activeTab).toBe('decisions')

    // 4. Quay lại session-1 -> khôi phục đúng IDE và Terminal của session-1
    useUiStore.getState().switchSessionTabs('session-2', 'session-1')
    expect(useUiStore.getState().openTabs).toEqual(['ide', 'terminal'])
    expect(useUiStore.getState().activeTab).toBe('terminal')

    // 5. Quay lại session-2 -> khôi phục đúng Decisions của session-2
    useUiStore.getState().switchSessionTabs('session-1', 'session-2')
    expect(useUiStore.getState().openTabs).toEqual(['decisions'])
    expect(useUiStore.getState().activeTab).toBe('decisions')
  })

  it('đóng tab ở session này không làm ảnh hưởng tới tabs của session khác', () => {
    const store = useUiStore.getState()

    store.switchSessionTabs(null, 'session-A')
    store.setWorkspaceHidden(false)
    store.openTab('ide')
    store.openTab('subagents')

    store.switchSessionTabs('session-A', 'session-B')
    store.setWorkspaceHidden(false)
    store.openTab('ide')

    // Session B đóng tab ide
    useUiStore.getState().closeTab('ide')
    expect(useUiStore.getState().openTabs).not.toContain('ide')

    // Quay lại session A -> tab ide vẫn còn nguyên
    useUiStore.getState().switchSessionTabs('session-B', 'session-A')
    expect(useUiStore.getState().openTabs).toContain('ide')
    expect(useUiStore.getState().openTabs).toContain('subagents')
  })
})
