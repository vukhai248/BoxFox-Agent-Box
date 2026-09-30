/**
 * Trạng thái THUẦN GIAO DIỆN: thanh bên thu gọn, tab nào đang mở, công tắc ẩn
 * bảng Workspace, tỉ lệ hai cột, file nào đang chọn, modal nguồn nào đang mở,
 * và điều hướng Settings.
 */
import { create } from 'zustand'
import type { AuditQueryId } from '../types/session'
import type { SettingSectionId, SettingTabId } from '../types/harness'
import type { Lang } from '../i18n/context'
import type { ExecutedWork } from '../lib/notifyEmail'
import { buildIdeUrl } from '../lib/ide/config'

/**
 * Trạng thái của một email mock "đã gửi" — lưu lại để hiển thị banner xem trước
 * sau khi phiên đạt trạng thái `xong`. `lang`/`title`/`work` được chốt tại thời
 * điểm gửi để banner không đổi theo locale hay kịch bản sau đó.
 */
export interface CompletionEmail {
  to: string
  at: string
  lang: Lang
  title: string
  work: ExecutedWork[]
}

export type PanelTabId =
  | 'plan'
  /** Work Graph: đồ thị việc của agent chính (nút, vòng review, DAG, duyệt, ship). */
  | 'work'
  | 'research'
  | 'sandbox'
  | 'subagents'
  | 'ide'
  | 'terminal'
  | 'design'
  | 'decisions'
  | 'pull_requests'
  | 'labels'
  | 'audit'
  | 'files'
  /** Bảng nhật ký hệ thống — công cụ DEV, chỉ hiện khi `import.meta.env.DEV` (App.tsx). */
  | 'system_log'

export const ALL_PANEL_TABS: PanelTabId[] = [
  'plan',
  'work',
  'research',
  'sandbox',
  'subagents',
  'ide',
  'terminal',
  'design',
  'decisions',
  'pull_requests',
  'labels',
  'audit',
  'files',
  'system_log',
]

/**
 * Ý định mở tab do agent phát ra (hợp đồng §1 `ui_intent`, §3 luật tự mở tab).
 * `target` là ngữ cảnh kèm theo: `{identity}` cho plan, `{requestId}` cho
 * decisions, `{path}` cho files, `{sessionId}` cho subagents.
 */
export interface TabIntent {
  tab: PanelTabId
  target?: Record<string, unknown> | null
  reason: string
}

/** Trạng thái lưu trữ Workspace Tabs của một phiên chat cụ thể. */
export interface SessionTabState {
  openTabs: PanelTabId[]
  activeTab: PanelTabId | null
  pinnedTab: PanelTabId | null
  tabIntentTargets: Partial<Record<PanelTabId, Record<string, unknown> | null>>
  workspaceHidden?: boolean
}

/** Cửa sổ "người dùng đang rảnh" của luật tự mở tab (hợp đồng §3). */
export const AUTO_OPEN_IDLE_MS = 15000

/** Trần số ý định chờ giữ lại; ý định cũ nhất bị bỏ trước (hợp đồng §3). */
export const MAX_PENDING_TAB_INTENTS = 20

/**
 * Hẹn một lần thử mở lại hàng đợi đúng lúc cửa sổ rảnh kết thúc (B12).
 *
 * Không giữ trạng thái ở cấp module: mỗi ý định bị chặn vì người dùng đang bận
 * tự hẹn một lần thử, và mỗi lần thử vẫn bị chặn sẽ hẹn tiếp cho hết cửa sổ
 * HIỆN TẠI — nhờ vậy dù người dùng tiếp tục gõ/cuộn thì ý định cũng không bị bỏ
 * quên (trước đây hàng đợi không có ai mở hộ). Số lần thử bị chặn là rất nhỏ
 * (tối đa 20 ý định trong hàng đợi, mỗi lần thử cách nhau trọn một cửa sổ rảnh).
 */
function armIntentFlush(get: () => UiState): void {
  const delay = Math.max(0, get().lastUserActivityAt + AUTO_OPEN_IDLE_MS - Date.now()) + 1
  setTimeout(() => {
    get().flushPendingIntents()
  }, delay)
}

/** Cờ bật/tắt của người dùng, lưu cùng chỗ với `boxfox_theme`. */
function getInitialFlag(key: string, fallback: boolean): boolean {
  if (typeof window === 'undefined') return fallback
  const saved = localStorage.getItem(key)
  if (saved === 'true') return true
  if (saved === 'false') return false
  return fallback
}

export const AUTO_OPEN_TABS_KEY = 'boxfox_auto_open_tabs'
export const AUTO_OPEN_IDLE_ONLY_KEY = 'boxfox_auto_open_only_when_idle'
/** Bảng Workspace đang bị ẩn bằng công tắc trên thanh trên (Kế hoạch E2). */
export const WORKSPACE_HIDDEN_KEY = 'boxfox_workspace_hidden'

/** Đọc cờ ẩn bảng lúc khởi tạo store — cùng chỗ với `boxfox_theme`. */
function getInitialWorkspaceHidden(): boolean {
  if (typeof window === 'undefined') return false
  return localStorage.getItem(WORKSPACE_HIDDEN_KEY) === '1'
}

/**
 * Ghi cờ ẩn bảng: `'1'` khi ẩn, **xoá khoá** khi hiện.
 *
 * Xoá thay vì ghi `'0'` để "chưa từng bấm" và "đã hiện lại" là cùng một trạng
 * thái trên đĩa — đúng cách `boxfox_theme` đang làm (chỉ có một giá trị được
 * ghi khi người dùng thật sự đổi).
 */
function persistWorkspaceHidden(hidden: boolean): void {
  if (typeof localStorage === 'undefined') return
  if (hidden) localStorage.setItem(WORKSPACE_HIDDEN_KEY, '1')
  else localStorage.removeItem(WORKSPACE_HIDDEN_KEY)
}


function getInitialTheme(): 'light' | 'dark' | 'system' {
  if (typeof window === 'undefined') return 'dark'
  const saved = localStorage.getItem('boxfox_theme') as 'light' | 'dark' | 'system' | null
  if (saved === 'light' || saved === 'dark' || saved === 'system') return saved
  return 'dark'
}

function applyDomTheme(theme: 'light' | 'dark' | 'system') {
  if (typeof document === 'undefined') return
  const isDark =
    theme === 'dark' ||
    (theme === 'system' && typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches)
  if (isDark) {
    document.documentElement.classList.add('dark')
  } else {
    document.documentElement.classList.remove('dark')
  }
}

// Khởi chạy ngay khi nạp store
if (typeof window !== 'undefined') {
  applyDomTheme(getInitialTheme())
}

interface UiState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void

  accountMenuOpen: boolean
  setAccountMenuOpen: (open: boolean) => void

  sessionTab: 'recent' | 'groups'
  setSessionTab: (tab: 'recent' | 'groups') => void

  openTabs: PanelTabId[]
  activeTab: PanelTabId | null
  /** ID của phiên chat hiện tại đang mở Workspace. */
  currentSessionId: string | null
  /** Bộ nhớ lưu trạng thái Workspace Tabs theo từng session. */
  sessionWorkspaceTabs: Record<string, SessionTabState>
  /** Chuyển phiên chat: lưu tabs phiên cũ và khôi phục tabs phiên mới. */
  switchSessionTabs: (fromSessionId: string | null, toSessionId: string) => void
  /**
   * Bảng Workspace (cột phải) đang bị ẩn bằng công tắc trên thanh trên.
   *
   * Một boolean, KHÔNG phải enum layout mode (Kế hoạch E2): màn Máy và bảng
   * Workspace vốn là cùng một cột, nên "ẩn bảng" chỉ có nghĩa là không dựng cột
   * đó nữa — `splitRatio` không bị đụng, hiện lại là về đúng tỉ lệ cũ.
   */
  workspaceHidden: boolean
  setWorkspaceHidden: (hidden: boolean) => void
  toggleWorkspace: () => void
  /**
   * Đường "người dùng vừa bấm một thứ cần bảng": hiện bảng + ghim tab + mở tab.
   * Dùng cho menu `+ Open Workspace` và các link trong chat — bấm là thấy bảng,
   * khác với ý định do agent đẩy tới (đang ẩn thì xếp hàng).
   */
  showTab: (tab: PanelTabId, target?: Record<string, unknown> | null) => void
  /**
   * Mở + kích hoạt tab. `target` (tuỳ chọn) là ngữ cảnh của ý định đang mở
   * (ví dụ `{identity}` cho plan) — panel đọc lại qua `tabIntentTargets`.
   */
  openTab: (tab: PanelTabId, target?: Record<string, unknown> | null) => void
  closeTab: (tab: PanelTabId) => void
  closePanel: () => void

  // ── Luật tự mở tab (hợp đồng §3) ───────────────────────────────────────
  /** Tab người dùng tự bấm trên thanh tab; ý định trúng tab này chỉ xếp hàng. */
  pinnedTab: PanelTabId | null
  pinTab: (tab: PanelTabId) => void
  /** Mốc hoạt động gần nhất của người dùng (keydown trong khung soạn tin, cuộn chat). */
  lastUserActivityAt: number
  noteUserActivity: () => void
  autoOpenTabs: boolean
  setAutoOpenTabs: (enabled: boolean) => void
  autoOpenOnlyWhenIdle: boolean
  setAutoOpenOnlyWhenIdle: (enabled: boolean) => void
  /** Ý định bị chặn, mới nhất ở cuối; tab đích hiện huy hiệu đếm. */
  pendingIntents: TabIntent[]
  requestTabIntent: (intent: TabIntent) => 'opened' | 'queued'
  /**
   * Mở lại các ý định đang xếp hàng khi điều kiện chặn đã hết (B12): hết cửa sổ
   * rảnh, hoặc người dùng vừa bật lại công tắc. Vẫn đi qua ĐÚNG luật §3 tại thời
   * điểm gọi (tab bị ghim thì ở lại hàng đợi), và chỉ xoá những ý định thật sự
   * được mở.
   */
  flushPendingIntents: () => void
  /** Ngữ cảnh của lần mở tab gần nhất, cho panel tự chọn đúng mục. */
  tabIntentTargets: Partial<Record<PanelTabId, Record<string, unknown> | null>>

  /** Tăng khi agent ghi một plan mới (`plan_written`) — `usePlanFiles` nghe số này. */
  planRevision: number
  bumpPlanRevision: () => void

  /** Vị trí cuộn đã nhớ của từng phiên chat, khôi phục khi quay lại phiên đó. */
  sessionScrollOffsets: Record<string, number>
  rememberSessionScroll: (sessionId: string, offset: number) => void

  panelFullscreen: boolean
  toggleFullscreen: () => void

  /** Bề rộng cột chat, tính theo phần của cả vùng làm việc (0,25 → 0,75). */
  splitRatio: number
  setSplitRatio: (ratio: number) => void

  selectedFilePath: string | null
  selectFile: (path: string) => void
  /** Xóa `selectedFilePath` sau khi panel Files đã tiêu thụ (mở file). */
  clearSelectedFile: () => void

  /**
   * URL code-server mà tab IDE sẽ nhúng khi mở theo yêu cầu "Mở trong VS Code
   * Web" từ tab Files. `null` ⇒ dùng mặc định (gốc workspace). `useIdeFrame`
   * theo dõi giá trị này để iframe tải đúng thư mục.
   */
  ideLaunchUrl: string | null
  /** Đặt `ideLaunchUrl` mở đúng `filePath` nhưng giữ gốc workspace rồi mở tab IDE. */
  openFileInIde: (filePath: string) => void

  sourceLabelId: string | null
  openSource: (labelId: string) => void
  closeSource: () => void

  labelsTab: 'context' | 'leases'
  setLabelsTab: (tab: 'context' | 'leases') => void

  auditQuery: AuditQueryId | 'all'
  setAuditQuery: (query: AuditQueryId | 'all') => void

  // Theme
  theme: 'light' | 'dark' | 'system'
  setTheme: (theme: 'light' | 'dark' | 'system') => void

  // Settings state
  isSettingsOpen: boolean
  settingsCategory: SettingSectionId
  settingsTab: SettingTabId
  providerInitialTab: 'api' | 'router'
  editingHarnessId: string | null
  openSettings: (tab?: SettingTabId) => void
  closeSettings: () => void
  setSettingsTab: (tab: SettingTabId, category?: SettingSectionId) => void
  setEditingHarnessId: (id: string | null) => void

  // Plan tab controls
  planViewMode: 'plan' | 'diff'
  setPlanViewMode: (mode: 'plan' | 'diff') => void
  planSubTab: 'overview' | 'detailed'
  setPlanSubTab: (tab: 'overview' | 'detailed') => void
  showFeedbackBanner: boolean
  setShowFeedbackBanner: (show: boolean) => void

  // Command palette / Quick search
  searchOpen: boolean
  openSearch: () => void
  closeSearch: () => void

  // Email notifications (mock)
  userEmail: string
  setUserEmail: (email: string) => void
  notifyOnComplete: boolean
  setNotifyOnComplete: (enabled: boolean) => void
  completionEmail: CompletionEmail | null
  setCompletionEmail: (email: CompletionEmail | null) => void
}

export const MIN_SPLIT = 0.36
export const MAX_SPLIT = 0.64

export const useUiStore = create<UiState>((set, get) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  accountMenuOpen: false,
  setAccountMenuOpen: (open) => set({ accountMenuOpen: open }),

  sessionTab: 'recent',
  setSessionTab: (tab) => set({ sessionTab: tab }),

  openTabs: [],
  activeTab: null,
  currentSessionId: null,
  sessionWorkspaceTabs: {},
  switchSessionTabs: (fromSessionId, toSessionId) =>
    set((s) => {
      const nextMap = { ...s.sessionWorkspaceTabs }
      if (fromSessionId) {
        nextMap[fromSessionId] = {
          openTabs: s.openTabs,
          activeTab: s.activeTab,
          pinnedTab: s.pinnedTab,
          tabIntentTargets: s.tabIntentTargets,
          workspaceHidden: s.workspaceHidden,
        }
      }
      const existing = nextMap[toSessionId]
      if (existing) {
        return {
          currentSessionId: toSessionId,
          openTabs: existing.openTabs,
          activeTab: existing.activeTab,
          pinnedTab: existing.pinnedTab,
          tabIntentTargets: existing.tabIntentTargets,
          workspaceHidden: existing.workspaceHidden ?? false,
          sessionWorkspaceTabs: nextMap,
        }
      }
      // Phiên mới chưa có lưu trữ: nếu là phiên đầu tiên khi store mới nạp thì giữ nguyên
      // openTabs hiện có (để giữ tương thích test); còn nếu là phiên mới thì mặc định
      // chưa mở tab nào (theo yêu cầu user).
      const isInitialTest = fromSessionId === null && s.openTabs.length > 0
      const defaultState: SessionTabState = {
        openTabs: isInitialTest ? s.openTabs : [],
        activeTab: isInitialTest ? s.activeTab : null,
        pinnedTab: isInitialTest ? s.pinnedTab : null,
        tabIntentTargets: isInitialTest ? s.tabIntentTargets : {},
        workspaceHidden: isInitialTest ? s.workspaceHidden : false,
      }
      nextMap[toSessionId] = defaultState
      return {
        currentSessionId: toSessionId,
        openTabs: defaultState.openTabs,
        activeTab: defaultState.activeTab,
        pinnedTab: defaultState.pinnedTab,
        tabIntentTargets: defaultState.tabIntentTargets,
        workspaceHidden: defaultState.workspaceHidden,
        sessionWorkspaceTabs: nextMap,
      }
    }),
  // Mở tab cũng là "đã tiêu thụ" mọi ý định đang xếp hàng cho tab đó: huy hiệu
  // tắt, và ngữ cảnh của ý định cuối cùng trở thành ngữ cảnh của lần mở này.
  openTab: (tab, target) =>
    set((s) => {
      const queued = s.pendingIntents.filter((intent) => intent.tab === tab)
      const queuedTarget = queued.length ? (queued[queued.length - 1].target ?? null) : null
      const nextTarget = target ?? queuedTarget
      const pendingIntents = s.pendingIntents.filter((intent) => intent.tab !== tab)
      const openTabs = s.openTabs.includes(tab) ? s.openTabs : [...s.openTabs, tab]
      const activeTab = tab
      const tabIntentTargets = nextTarget
        ? { ...s.tabIntentTargets, [tab]: nextTarget }
        : s.tabIntentTargets
      const sessionWorkspaceTabs = s.currentSessionId
        ? {
            ...s.sessionWorkspaceTabs,
            [s.currentSessionId]: {
              openTabs,
              activeTab,
              pinnedTab: s.pinnedTab,
              tabIntentTargets,
              workspaceHidden: s.workspaceHidden,
            },
          }
        : s.sessionWorkspaceTabs
      return {
        openTabs,
        activeTab,
        pendingIntents,
        tabIntentTargets,
        sessionWorkspaceTabs,
      }
    }),
  closeTab: (tab) =>
    set((s) => {
      const openTabs = s.openTabs.filter((item) => item !== tab)
      const activeTab = s.activeTab === tab ? (openTabs[0] ?? null) : s.activeTab
      const pinnedTab = s.pinnedTab === tab ? null : s.pinnedTab
      const sessionWorkspaceTabs = s.currentSessionId
        ? {
            ...s.sessionWorkspaceTabs,
            [s.currentSessionId]: {
              openTabs,
              activeTab,
              pinnedTab,
              tabIntentTargets: s.tabIntentTargets,
              workspaceHidden: s.workspaceHidden,
            },
          }
        : s.sessionWorkspaceTabs
      return {
        openTabs,
        activeTab,
        pinnedTab,
        panelFullscreen: openTabs.length ? s.panelFullscreen : false,
        sessionWorkspaceTabs,
      }
    }),
  closePanel: () =>
    set((s) => {
      const sessionWorkspaceTabs = s.currentSessionId
        ? {
            ...s.sessionWorkspaceTabs,
            [s.currentSessionId]: {
              openTabs: [],
              activeTab: null,
              pinnedTab: s.pinnedTab,
              tabIntentTargets: s.tabIntentTargets,
              workspaceHidden: s.workspaceHidden,
            },
          }
        : s.sessionWorkspaceTabs
      return { openTabs: [], activeTab: null, panelFullscreen: false, sessionWorkspaceTabs }
    }),

  // ── Công tắc bảng Workspace (Kế hoạch E2) ──────────────────────────────
  workspaceHidden: getInitialWorkspaceHidden(),
  setWorkspaceHidden: (hidden) => {
    persistWorkspaceHidden(hidden)
    const s = get()
    const sessionWorkspaceTabs = s.currentSessionId
      ? {
          ...s.sessionWorkspaceTabs,
          [s.currentSessionId]: {
            openTabs: s.openTabs,
            activeTab: s.activeTab,
            pinnedTab: s.pinnedTab,
            tabIntentTargets: s.tabIntentTargets,
            workspaceHidden: hidden,
          },
        }
      : s.sessionWorkspaceTabs
    set({ workspaceHidden: hidden, sessionWorkspaceTabs })
    // Hiện bảng là điều kiện thứ tư của luật xếp hàng: hàng đợi đóng băng lúc
    // ẩn phải được xả ngay — cũ-trước, và vẫn qua ĐÚNG luật §3 tại thời điểm
    // gọi (tab bị ghim thì ở lại hàng đợi).
    if (!hidden) get().flushPendingIntents()
  },
  toggleWorkspace: () => get().setWorkspaceHidden(!get().workspaceHidden),
  showTab: (tab, target) => {
    get().setWorkspaceHidden(false)
    get().pinTab(tab)
    get().openTab(tab, target ?? null)
  },

  // ── Luật tự mở tab (hợp đồng §3). Thứ tự ba điều kiện là phần hợp đồng:
  // dừng ở điều kiện đầu tiên vi phạm và xếp hàng thay vì mở.
  pinnedTab: null,
  pinTab: (tab) =>
    set((s) => {
      const sessionWorkspaceTabs = s.currentSessionId
        ? {
            ...s.sessionWorkspaceTabs,
            [s.currentSessionId]: {
              openTabs: s.openTabs,
              activeTab: s.activeTab,
              pinnedTab: tab,
              tabIntentTargets: s.tabIntentTargets,
              workspaceHidden: s.workspaceHidden,
            },
          }
        : s.sessionWorkspaceTabs
      return { pinnedTab: tab, sessionWorkspaceTabs }
    }),

  lastUserActivityAt: 0,
  noteUserActivity: () => set({ lastUserActivityAt: Date.now() }),

  autoOpenTabs: getInitialFlag(AUTO_OPEN_TABS_KEY, true),
  setAutoOpenTabs: (enabled) => {
    if (typeof localStorage !== 'undefined') localStorage.setItem(AUTO_OPEN_TABS_KEY, String(enabled))
    set({ autoOpenTabs: enabled })
    // Công tắc là điều kiện 1 của §3: bật lại thì hàng đợi phải được mở, không
    // để nó nằm đó chờ người dùng tình cờ bấm đúng tab (B12).
    if (enabled) get().flushPendingIntents()
  },
  autoOpenOnlyWhenIdle: getInitialFlag(AUTO_OPEN_IDLE_ONLY_KEY, true),
  setAutoOpenOnlyWhenIdle: (enabled) => {
    if (typeof localStorage !== 'undefined') localStorage.setItem(AUTO_OPEN_IDLE_ONLY_KEY, String(enabled))
    set({ autoOpenOnlyWhenIdle: enabled })
    // Tắt "chỉ khi rảnh" là điều kiện 3 hết chặn → mở luôn hàng đợi.
    if (!enabled) get().flushPendingIntents()
  },

  pendingIntents: [],
  requestTabIntent: (intent) => {
    const state = get()
    const queue = () => {
      set((s) => ({
        pendingIntents: [...s.pendingIntents, intent].slice(-MAX_PENDING_TAB_INTENTS),
      }))
      return 'queued' as const
    }
    if (!state.autoOpenTabs) return queue()
    // Điều kiện 4 (Kế hoạch E2): bảng đang ẩn ⇒ mở tab là vô nghĩa (người dùng
    // không thấy gì), nên xếp hàng và không cướp tab đã ghim. KHÔNG hẹn flush:
    // chỉ người dùng hiện bảng mới xả hàng đợi này.
    if (state.workspaceHidden) return queue()
    if (state.pinnedTab === intent.tab) return queue()
    if (state.autoOpenOnlyWhenIdle && Date.now() - state.lastUserActivityAt < AUTO_OPEN_IDLE_MS) {
      // Chỉ bị chặn vì người dùng đang bận → hẹn mở lại khi cửa sổ rảnh kết thúc.
      armIntentFlush(get)
      return queue()
    }
    state.openTab(intent.tab, intent.target ?? null)
    return 'opened' as const
  },
  flushPendingIntents: () => {
    const state = get()
    if (state.pendingIntents.length === 0) return
    // Điều kiện 4: bảng đang ẩn — hàng đợi ĐÓNG BĂNG, không xả (xem
    // `setWorkspaceHidden`: hiện bảng mới là lúc xả).
    if (state.workspaceHidden) return
    // Điều kiện 1: công tắc tắt — không có gì để làm, hàng đợi chờ lần bật lại.
    if (!state.autoOpenTabs) return
    // Điều kiện 3: người dùng vừa hoạt động lại → hẹn tiếp cho hết cửa sổ hiện
    // tại (nếu không, một lần thử trượt là ý định bị bỏ quên vĩnh viễn).
    if (state.autoOpenOnlyWhenIdle && Date.now() - state.lastUserActivityAt < AUTO_OPEN_IDLE_MS) {
      armIntentFlush(get)
      return
    }
    // Điều kiện 2: tab người dùng đã ghim thì KHÔNG bao giờ bị cướp — ý định của
    // nó ở lại hàng đợi (mở tab đó bằng tay vẫn là cách tiêu thụ nó).
    const openable: PanelTabId[] = []
    for (const intent of state.pendingIntents) {
      if (intent.tab === state.pinnedTab) continue
      if (!openable.includes(intent.tab)) openable.push(intent.tab)
    }
    // `openTab` tự lấy đích của ý định MỚI NHẤT của tab đó và tự xoá hàng đợi của
    // đúng tab ấy — nên chỉ những ý định thật sự được mở mới biến mất.
    for (const tab of openable) get().openTab(tab)
  },
  tabIntentTargets: {},

  planRevision: 0,
  bumpPlanRevision: () => set((s) => ({ planRevision: s.planRevision + 1 })),

  sessionScrollOffsets: {},
  rememberSessionScroll: (sessionId, offset) =>
    set((s) => ({ sessionScrollOffsets: { ...s.sessionScrollOffsets, [sessionId]: offset } })),

  panelFullscreen: false,
  toggleFullscreen: () => set((s) => ({ panelFullscreen: !s.panelFullscreen })),

  splitRatio: 0.46,
  setSplitRatio: (ratio) =>
    set({ splitRatio: Math.min(MAX_SPLIT, Math.max(MIN_SPLIT, ratio)) }),

  selectedFilePath: null,
  // Định tuyến lại: chọn file → mở tab Files (panel Workspace Files tiêu thụ
  // `selectedFilePath` rồi mở file đó, không mở song song cả tab IDE nữa).
  //
  // `selectFile` CHỈ có một người gọi: nút [👁 View] trong chat — một cú bấm của
  // người dùng. Nên nó đi qua `showTab` (hiện bảng nếu đang ẩn), không phải
  // `openTab`: bấm View lúc bảng Workspace đang ẩn mà không hiện gì là một cú
  // bấm im lặng (lỗi b18-review #2), trong khi `openTab` cố ý không chạm
  // `workspaceHidden`.
  selectFile: (path) => {
    set({ selectedFilePath: path })
    get().showTab('files')
  },
  clearSelectedFile: () => set({ selectedFilePath: null }),

  ideLaunchUrl: null,
  openFileInIde: (filePath) => {
    set({ ideLaunchUrl: buildIdeUrl(import.meta.env, '', filePath) })
    get().openTab('ide')
  },

  sourceLabelId: null,
  openSource: (labelId) => set({ sourceLabelId: labelId }),
  closeSource: () => set({ sourceLabelId: null }),

  labelsTab: 'context',
  setLabelsTab: (tab) => set({ labelsTab: tab }),

  auditQuery: 'all',
  setAuditQuery: (query) => set({ auditQuery: query }),

  // Settings
  isSettingsOpen: false,
  settingsCategory: 'AGENTS',
  settingsTab: 'harness',
  providerInitialTab: 'router',
  editingHarnessId: null,
  openSettings: (tab = 'harness') =>
    set((s) => ({ isSettingsOpen: true, settingsTab: tab === 'llm_api_keys' || tab === 'router' ? 'provider' : tab, providerInitialTab: tab === 'llm_api_keys' ? 'api' : tab === 'router' ? 'router' : s.providerInitialTab, editingHarnessId: null })),
  closeSettings: () => set({ isSettingsOpen: false, editingHarnessId: null }),
  setSettingsTab: (tab, category) =>
    set((s) => ({
      settingsTab: tab === 'llm_api_keys' || tab === 'router' ? 'provider' : tab,
      providerInitialTab: tab === 'llm_api_keys' ? 'api' : tab === 'router' ? 'router' : s.providerInitialTab,
      settingsCategory: category ?? s.settingsCategory,
      editingHarnessId: null,
    })),
  setEditingHarnessId: (id) => set({ editingHarnessId: id }),

  // Plan
  planViewMode: 'plan',
  setPlanViewMode: (mode) => set({ planViewMode: mode }),
  planSubTab: 'overview',
  setPlanSubTab: (tab) => set({ planSubTab: tab }),
  showFeedbackBanner: true,
  setShowFeedbackBanner: (show) => set({ showFeedbackBanner: show }),

  // Theme
  theme: getInitialTheme(),
  setTheme: (theme) => {
    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('boxfox_theme', theme)
    }
    applyDomTheme(theme)
    set({ theme })
  },

  // Search modal
  searchOpen: false,
  openSearch: () => set({ searchOpen: true }),
  closeSearch: () => set({ searchOpen: false }),

  // Email notifications (mock)
  userEmail: '',
  setUserEmail: (email) => set({ userEmail: email }),
  notifyOnComplete: false,
  setNotifyOnComplete: (enabled) => set({ notifyOnComplete: enabled }),
  completionEmail: null,
  setCompletionEmail: (completionEmail) => set({ completionEmail }),
}))
