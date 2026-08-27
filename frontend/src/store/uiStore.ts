/**
 * Trạng thái THUẦN GIAO DIỆN: thanh bên thu gọn, tab nào đang mở, tỉ lệ hai
 * cột, file nào đang chọn, modal nguồn nào đang mở, và điều hướng Settings.
 */
import { create } from 'zustand'
import type { AuditQueryId } from '../types/session'
import type { SettingSectionId, SettingTabId } from '../types/harness'

export type PanelTabId =
  | 'plan'
  | 'sandbox'
  | 'ide'
  | 'terminal'
  | 'design'
  | 'decisions'
  | 'pull_requests'
  | 'labels'
  | 'audit'

export const ALL_PANEL_TABS: PanelTabId[] = [
  'plan',
  'sandbox',
  'ide',
  'terminal',
  'design',
  'decisions',
  'pull_requests',
  'labels',
  'audit',
]

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
  openTab: (tab: PanelTabId) => void
  closeTab: (tab: PanelTabId) => void
  closePanel: () => void

  panelFullscreen: boolean
  toggleFullscreen: () => void

  /** Bề rộng cột chat, tính theo phần của cả vùng làm việc (0,25 → 0,75). */
  splitRatio: number
  setSplitRatio: (ratio: number) => void

  selectedFilePath: string | null
  selectFile: (path: string) => void

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
  planVersion: string
  setPlanVersion: (version: string) => void
  showFeedbackBanner: boolean
  setShowFeedbackBanner: (show: boolean) => void

  // Autopilot toggle in chat bar
  autopilotEnabled: boolean
  setAutopilotEnabled: (enabled: boolean) => void
}

export const MIN_SPLIT = 0.36
export const MAX_SPLIT = 0.64

export const useUiStore = create<UiState>((set) => ({
  sidebarCollapsed: false,
  toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),

  accountMenuOpen: false,
  setAccountMenuOpen: (open) => set({ accountMenuOpen: open }),

  sessionTab: 'recent',
  setSessionTab: (tab) => set({ sessionTab: tab }),

  openTabs: [],
  activeTab: null,
  openTab: (tab) =>
    set((s) => ({
      openTabs: s.openTabs.includes(tab) ? s.openTabs : [...s.openTabs, tab],
      activeTab: tab,
    })),
  closeTab: (tab) =>
    set((s) => {
      const openTabs = s.openTabs.filter((item) => item !== tab)
      const activeTab = s.activeTab === tab ? (openTabs[0] ?? null) : s.activeTab
      return { openTabs, activeTab, panelFullscreen: openTabs.length ? s.panelFullscreen : false }
    }),
  closePanel: () => set({ activeTab: null, panelFullscreen: false }),

  panelFullscreen: false,
  toggleFullscreen: () => set((s) => ({ panelFullscreen: !s.panelFullscreen })),

  splitRatio: 0.46,
  setSplitRatio: (ratio) =>
    set({ splitRatio: Math.min(MAX_SPLIT, Math.max(MIN_SPLIT, ratio)) }),

  selectedFilePath: null,
  selectFile: (path) => set({ selectedFilePath: path }),

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
  editingHarnessId: null,
  openSettings: (tab = 'harness') =>
    set({ isSettingsOpen: true, settingsTab: tab, editingHarnessId: null }),
  closeSettings: () => set({ isSettingsOpen: false, editingHarnessId: null }),
  setSettingsTab: (tab, category) =>
    set((s) => ({
      settingsTab: tab,
      settingsCategory: category ?? s.settingsCategory,
      editingHarnessId: null,
    })),
  setEditingHarnessId: (id) => set({ editingHarnessId: id }),

  // Plan
  planViewMode: 'plan',
  setPlanViewMode: (mode) => set({ planViewMode: mode }),
  planSubTab: 'overview',
  setPlanSubTab: (tab) => set({ planSubTab: tab }),
  planVersion: 'v3',
  setPlanVersion: (version) => set({ planVersion: version }),
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

  // Autopilot
  autopilotEnabled: true,
  setAutopilotEnabled: (enabled) => set({ autopilotEnabled: enabled }),
}))
