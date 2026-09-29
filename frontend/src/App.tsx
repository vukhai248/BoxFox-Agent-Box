/**
 * Main App Layout — BoxFox / Devin Professional Workspace.
 * VS Code-style tab system with 'Open Workspace' TopBar menu and rich workspace panels.
 */
import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  FileText,
  Monitor,
  Code2,
  Terminal,
  Shapes,
  Tag,
  ScrollText,
  GitPullRequest,
  ShieldAlert,
  X,
  FolderOpen,
  BrainCircuit,
  Microscope,
  MoreHorizontal,
  Power,
  Wifi,
  Workflow,
} from 'lucide-react'
import { useT } from './i18n/context'
import { useAgentStore } from './store/agentStore'
import { useUiStore, ALL_PANEL_TABS, type PanelTabId } from './store/uiStore'
import { Sidebar } from './components/shell/Sidebar'
import { isCompactViewport, useViewportWidth } from './components/shell/useViewportWidth'
import { Resizer } from './components/shell/Resizer'
import { ChatPanel } from './components/panels/ChatPanel'
import { PlanPanel } from './components/panels/PlanPanel'
import { ResearchPanel } from './components/panels/ResearchPanel'
import { DecisionsPanel } from './components/panels/DecisionsPanel'
import { WorkGraphPanel } from './components/panels/work/WorkGraphPanel'
import { TerminalPanel } from './components/panels/TerminalPanel'
import { SandboxScreenPanel } from './components/panels/SandboxScreenPanel'
import { SubagentInspectorPanel } from './components/panels/SubagentInspectorPanel'
import { IdePanel } from './components/panels/IdePanel'
import { LabelsLeasesPanel } from './components/panels/LabelsLeasesPanel'
import { ModeSwitchCard } from './components/ModeSwitchCard'
import { DesignPanel } from './components/panels/design/DesignPanel'
import { AuditPanel } from './components/panels/AuditPanel'
import { PullRequestsPanel } from './components/panels/PullRequestsPanel'
import { WorkspaceFilesPanel } from './components/panels/workspace/WorkspaceFilesPanel'
import { SystemLogPanel } from './components/panels/SystemLogPanel'
import { SettingsModal } from './components/settings/SettingsModal'
import { CompletionEmailNotice } from './components/CompletionEmailNotice'
import { SearchSessionsModal } from './components/shell/SearchSessionsModal'
import { useCompletionEmail } from './hooks/useCompletionEmail'
import { useBoxState } from './hooks/useBoxState'
import { ContextUsageBar, formatTokenCount } from './components/panels/ContextUsageBar'
import { formatClock } from './components/panels/research/format'

const TAB_LABEL_KEY: Record<PanelTabId, string> = {
  plan: 'tabs.plan',
  work: 'tabs.work',
  // P4: tab Research có nhãn riêng — trước đây dùng nhờ `tabs.plan`.
  research: 'tabs.research',
  sandbox: 'tabs.sandbox',
  subagents: 'tabs.subagents',
  ide: 'tabs.ide',
  terminal: 'tabs.terminal',
  design: 'tabs.design',
  decisions: 'tabs.decisions',
  pull_requests: 'tabs.pull_requests',
  labels: 'tabs.labels',
  audit: 'tabs.audit',
  files: 'tabs.files',
  system_log: 'tabs.system_log',
}

export const TAB_ICON: Record<PanelTabId, React.ComponentType<{ className?: string }>> = {
  plan: FileText,
  work: Workflow,
  research: Microscope,
  sandbox: Monitor,
  subagents: BrainCircuit,
  ide: Code2,
  terminal: Terminal,
  design: Shapes,
  decisions: ShieldAlert,
  pull_requests: GitPullRequest,
  labels: Tag,
  audit: ScrollText,
  files: FolderOpen,
  system_log: Activity,
}

/**
 * Đồng hồ của epoch hiện tại, tính bằng giây. Bộ đếm chỉ nhích khi agent đang
 * chạy (`running`) và đặt lại về 0 khi `taskEpoch` đổi — nghỉ thì con số đứng
 * yên, không tự cộng thêm thời gian người dùng không nhìn agent làm gì.
 *
 * Table 4.8 dòng 11 cần chỗ cho "thời gian" này ở thanh trên: route đánh giá
 * miễn phí chỉ có token + thời gian, không có USD (#6079).
 */
function useEpochElapsedSeconds(taskEpoch: number, running: boolean): number {
  const [startedAt, setStartedAt] = useState(() => Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    setStartedAt(Date.now())
    setNow(Date.now())
  }, [taskEpoch])
  useEffect(() => {
    if (!running) return
    const id = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [running, taskEpoch])
  return Math.max(0, Math.floor((now - startedAt) / 1000))
}

// Icon của mỗi mục lấy từ `TAB_ICON` — icon tab là MỘT sự thật (TabBar và menu cùng vẽ nó),
// nên đổi icon chỉ phải đổi ở một chỗ (#6108).
const AVAILABLE_PANEL_TABS: { id: PanelTabId; label: string; desc: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: 'plan', label: 'Plan Document', desc: 'Architecture blueprint & step review', icon: TAB_ICON.plan },
  { id: 'work', label: 'Work Graph', desc: 'Nodes, review loops, DAG waves, approval & ship', icon: TAB_ICON.work },
  { id: 'research', label: 'Research', desc: 'Questions, evidence gaps & budget', icon: TAB_ICON.research },
  { id: 'sandbox', label: 'Sandbox Machine', desc: 'Live container vision & browser frame', icon: TAB_ICON.sandbox },
  { id: 'subagents', label: 'Sub-agents Console', desc: 'Autonomous specialists activity & thinking', icon: TAB_ICON.subagents },
  { id: 'ide', label: 'IDE (VS Code Web)', desc: 'code-server running inside the box', icon: TAB_ICON.ide },
  { id: 'terminal', label: 'Integrated Terminal', desc: 'Interactive shell in sandbox container', icon: TAB_ICON.terminal },
  { id: 'design', label: 'Design Canvas', desc: 'Interactive UI canvas, visual flow & mockup editor', icon: TAB_ICON.design },
  { id: 'decisions', label: 'Decisions & Approvals', desc: 'Security permission requests & design choices', icon: TAB_ICON.decisions },
  { id: 'pull_requests', label: 'Pull Requests', desc: 'Git branches, PR diffs & CI checks', icon: TAB_ICON.pull_requests },
  { id: 'labels', label: 'Labels & Leases', desc: 'IFC security provenance & active leases', icon: TAB_ICON.labels },
  { id: 'audit', label: 'Audit Logs', desc: 'Immutable security action ledger', icon: TAB_ICON.audit },
  { id: 'files', label: 'Workspace Files', desc: 'Browse, preview & manage workspace files', icon: TAB_ICON.files },
  { id: 'system_log', label: 'System Log', desc: 'Dev log written on the host, outside the box', icon: TAB_ICON.system_log },
]

/** Phím tắt điều hướng nhanh tương ứng từng Workspace view (Devin Style). */
const WORKSPACE_SHORTCUTS: Partial<Record<PanelTabId, string[]>> = {
  plan: ['Ctrl', 'Shift', 'P'],
  ide: ['Ctrl', 'Shift', 'I'],
  terminal: ['Ctrl', 'Shift', 'X'],
  pull_requests: ['Ctrl', 'Shift', 'O'],
}

/**
 * Tab CHỈ dành cho chế độ phát triển. Bảng Nhật ký hệ thống là công cụ của dev
 * (việc 5, bản v2): nó đọc log của harness trên host qua `/api/agent/system-log`,
 * nên bản dựng sản phẩm không hiện nó ở menu "Open Workspace" và cũng không mở
 * được tab đó. `import.meta.env.DEV` là chế độ dev có sẵn của ứng dụng — không
 * thêm cờ mới.
 */
const DEV_ONLY_PANEL_TABS: ReadonlySet<PanelTabId> = new Set<PanelTabId>(['system_log'])

export function isPanelTabAvailable(id: PanelTabId, env: ImportMetaEnv = import.meta.env): boolean {
  return Boolean(env.DEV) || !DEV_ONLY_PANEL_TABS.has(id)
}

/** Danh sách tab của menu "Open Workspace", đã lọc theo chế độ dev. */
export function availablePanelTabs(env: ImportMetaEnv = import.meta.env) {
  return AVAILABLE_PANEL_TABS.filter((tab) => isPanelTabAvailable(tab.id, env))
}

export default function App() {
  const t = useT()
  const init = useAgentStore((s) => s.init)
  const teardown = useAgentStore((s) => s.teardown)
  useEffect(() => {
    init()
    return () => teardown()
  }, [init, teardown])

  useCompletionEmail()


  const mode = useAgentStore((s) => s.mode)
  const taskEpoch = useAgentStore((s) => s.taskEpoch)
  const budget = useAgentStore((s) => s.budget)
  // Thời gian của epoch hiện tại (Table 4.8 dòng 11). Đồng hồ chỉ nhích khi agent
  // đang chạy, nên con số đứng yên lúc nghỉ thay vì tự cộng thêm.
  const elapsedSeconds = useEpochElapsedSeconds(taskEpoch, mode === 'ACT')
  const proposal = useAgentStore((s) => s.proposal)
  const rejectBundle = useAgentStore((s) => s.rejectBundle)
  const context = useAgentStore((s) => s.context)
  const sessions = useAgentStore((s) => s.sessions)
  const activeSessionId = useAgentStore((s) => s.activeSessionId)
  const activeSession = sessions.find((s) => s.session_id === activeSessionId)
  const sessionTitle = activeSession?.title || 'New Session'

  // Đồng bộ và khôi phục các tab Workspace riêng cho từng phiên chat
  const previousSessionIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (!activeSessionId) return
    const prevId = previousSessionIdRef.current
    if (prevId !== activeSessionId) {
      previousSessionIdRef.current = activeSessionId
      useUiStore.getState().switchSessionTabs(prevId, activeSessionId)
    }
  }, [activeSessionId])

  const rawOpenTabs = useUiStore((s) => s.openTabs)
  // Bảng nhật ký hệ thống là tab DEV: ở bản dựng sản phẩm nó không mở được, kể cả
  // khi trạng thái tab còn sót lại từ trước.
  const openTabs = rawOpenTabs.filter((tab) => ALL_PANEL_TABS.includes(tab) && isPanelTabAvailable(tab))
  const activeTab = useUiStore((s) => s.activeTab)
  const openTab = useUiStore((s) => s.openTab)
  const closeTab = useUiStore((s) => s.closeTab)
  const closePanel = useUiStore((s) => s.closePanel)
  const splitRatio = useUiStore((s) => s.splitRatio)
  const workspaceHidden = useUiStore((s) => s.workspaceHidden)
  // Dưới ~768px cột chat phải chiếm trọn bề ngang: cột chat 120px ở 390px là
  // không dùng được (BUG-23). Sidebar tự thu về thanh biểu tượng ở <1024px.
  const compactLayout = isCompactViewport(useViewportWidth())
  // Cơ chế đóng/mở Workspace tự động như Devin: khi không có tab nào mở thì
  // ẩn luôn bảng Workspace; cột chat chiếm 100% bề ngang.
  const paneHidden = workspaceHidden || openTabs.length === 0 || compactLayout

  const containerRef = useRef<HTMLDivElement>(null)
  const showModeSwitch = proposal !== null

  const requests = useAgentStore((s) => s.requests)
  const pendingRequestsCount = Object.values(requests).filter((r) => r.status === 'dang_cho').length
  // Người dùng tự bấm tab nào thì tab đó được "ghim": ý định tự mở của agent
  // nhắm đúng tab ấy sẽ chỉ xếp hàng (hợp đồng §3).
  const pinTab = useUiStore((s) => s.pinTab)
  const pendingIntents = useUiStore((s) => s.pendingIntents)
  const intentCountFor = (tab: PanelTabId) =>
    pendingIntents.filter((intent) => intent.tab === tab).length

  function renderActiveTab() {
    if (showModeSwitch && activeTab === 'plan') {
      return <ModeSwitchCard proposal={proposal!} rejectBundle={rejectBundle} />
    }
    switch (activeTab) {
      case 'plan':
        return <PlanPanel />
      case 'work':
        return <WorkGraphPanel />
      case 'research':
        return <ResearchPanel />
      case 'sandbox':
        return <SandboxScreenPanel />
      case 'subagents':
        return <SubagentInspectorPanel />
      case 'ide':
        return <IdePanel />

      case 'terminal':
        return <TerminalPanel />
      case 'design':
        // P5: tab Design là vỏ năm ngăn (Canvas mặc định + Brief/Nhánh/Soát/Báo cáo).
        return <DesignPanel />
      case 'decisions':
        return <DecisionsPanel />
      case 'pull_requests':
        return <PullRequestsPanel />
      case 'labels':
        return <LabelsLeasesPanel />
      case 'audit':
        return <AuditPanel />
      case 'files':
        return <WorkspaceFilesPanel />
      case 'system_log':
        // Cùng một hàng rào với menu: trạng thái tab sót lại từ trước cũng không mở
        // được bảng này ở bản dựng sản phẩm.
        return isPanelTabAvailable('system_log') ? <SystemLogPanel /> : null
      default:
        return null
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-fg select-none">
      <Sidebar />

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Cleaned TopBar Header with Devin-style More (...) Menu */}
        <TopBar
          title={sessionTitle}
          mode={mode}
          taskEpoch={taskEpoch}
          budget={budget}
          elapsedSeconds={elapsedSeconds}
          context={context}
        />

        <div ref={containerRef} className="flex min-h-0 flex-1">
          {/* Left Column — Chat & Prompt Input Bar.
              min-w-0 (không còn min-w-[480px]): sàn thật do Resizer chốt
              bằng pixel (clampSplitRatio), nên tổng min-content không bao
              giờ vượt viewport và không còn bị overflow-hidden cắt panel
              còn lại. */}
          <div
            data-testid="chat-column"
            className="flex min-h-0 min-w-0 flex-col overflow-hidden border-r border-line"
            style={paneHidden
              ? { flex: '1 1 0%', width: 'auto' }
              : { flex: `${splitRatio} 0 0%`, width: `${splitRatio * 100}%` }}
          >
            <div className="min-h-0 flex-1 overflow-hidden">
              <ChatPanel />
            </div>
          </div>

          {!paneHidden && <Resizer containerRef={containerRef} />}

          {/* Right Column — VS Code-style Workspace Tabs (cùng lý do min-w-0 như trên).
              Ẩn khi màn hẹp (<768px) HOẶC khi người dùng tắt công tắc bảng
              Workspace; cả thanh tab lẫn tab đang chọn đều nằm trong cột này. */}
          {!paneHidden && (
          <div
            data-testid="workspace-pane"
            className="flex min-h-0 min-w-0 flex-col overflow-hidden bg-panel"
            style={{ flex: `${1 - splitRatio} 0 0%`, width: `${(1 - splitRatio) * 100}%` }}
          >
            {/* Top Workspace Tab Bar */}
            <div className="flex items-center border-b border-line bg-panel px-1.5 pt-1 relative">
              {/* Chrome-like flexible tab list with horizontal scroll */}
              <div
                className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto scroll-smooth py-0.5"
                onWheel={(e) => {
                  if (e.deltaY !== 0) {
                    e.currentTarget.scrollLeft += e.deltaY
                  }
                }}
              >
                {openTabs.map((tab) => {
                  const Icon = TAB_ICON[tab]
                  const isActive = activeTab === tab
                  // Huy hiệu đếm = yêu cầu mock đang chờ (tab Decisions) + số ý định
                  // tự mở đang xếp hàng cho tab này.
                  const badgeCount = intentCountFor(tab) + (tab === 'decisions' ? pendingRequestsCount : 0)
                  const isDecisionsWithPending = badgeCount > 0
                  const tabLabel = tab === 'decisions' ? 'Decisions' : tab === 'subagents' ? 'Sub-agents' : t(TAB_LABEL_KEY[tab] as 'tabs.plan')

                  return (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => {
                        pinTab(tab)
                        openTab(tab)
                      }}
                      aria-selected={isActive}
                      title={tabLabel}
                      className={`group flex min-w-[34px] max-w-[180px] flex-1 shrink items-center justify-between gap-1.5 rounded-t-md border-t border-x px-2 py-1.5 text-xs font-medium transition cursor-pointer overflow-hidden ${isActive
                          ? 'border-line bg-panel2 text-fg shadow-xs'
                          : 'border-transparent text-muted hover:text-fg hover:bg-panel2/40'
                        }`}
                    >
                      <div className="flex min-w-0 items-center gap-1.5 flex-1">
                        <Icon
                          className={`size-3.5 shrink-0 ${isDecisionsWithPending
                              ? 'text-amber-400 animate-pulse'
                              : isActive
                                ? 'text-brand'
                                : 'text-muted'
                            }`}
                        />
                        <span className="truncate text-left leading-none min-w-0 flex-1">
                          {tabLabel}
                        </span>
                      </div>

                      {isDecisionsWithPending && (
                        <span
                          data-testid={`tab-badge-${tab}`}
                          className="shrink-0 flex size-4 items-center justify-center rounded-full bg-amber-500/20 font-mono text-[9px] font-bold text-amber-300"
                        >
                          {badgeCount}
                        </span>
                      )}
                      <span
                        role="button"
                        tabIndex={0}
                        onClick={(e) => {
                          e.stopPropagation()
                          closeTab(tab)
                        }}
                        className="shrink-0 ml-0.5 rounded p-0.5 text-muted opacity-0 group-hover:opacity-100 hover:bg-panel hover:text-fg cursor-pointer transition"
                        aria-label="Close tab"
                      >
                        <X className="size-2.5" />
                      </span>
                    </button>
                  )
                })}
              </div>

              {/* Close entire panel button - pinned on right */}
              {openTabs.length > 0 && (
                <div className="shrink-0 flex items-center pl-1 pr-1 bg-panel border-l border-line/40 z-10">
                  <button
                    type="button"
                    onClick={closePanel}
                    className="rounded p-1 text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                    title="Close workspace panel"
                  >
                    <X className="size-3.5" />
                  </button>
                </div>
              )}
            </div>

            {/* Tab Content */}
            <div className="min-h-0 flex-1 overflow-hidden">
              {activeTab && (
                <div
                  className={
                    activeTab === 'sandbox' || activeTab === 'ide'
                      ? 'flex h-full flex-col overflow-hidden'
                      : 'h-full overflow-auto'
                  }
                >
                  {renderActiveTab()}
                </div>
              )}
            </div>
          </div>
          )}
        </div>
      </div>

      {/* Global Full-Screen Settings Modal */}
      <SettingsModal />

      {/* Mock email preview banner (dismissible) */}
      <CompletionEmailNotice />
    </div>
  )
}

export function TopBar({
  title: _title,
  mode: _mode,
  taskEpoch: _taskEpoch,
  budget,
  elapsedSeconds,
  context: _context,
}: {
  title?: string
  mode?: string
  taskEpoch?: number
  budget: { steps: number; tokens: number; costUsd: number; capUsd: number }
  elapsedSeconds: number
  context?: { integrity_floor: string; confidentiality_ceiling: string }
  workspaceHidden?: boolean
  workspaceToggleDisabled?: boolean
  hiddenIntentCount?: number
  queuedViewLabel?: string
  onToggleWorkspace?: () => void
}) {
  const t = useT()
  const box = useBoxState()
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const moreMenuRef = useRef<HTMLDivElement>(null)
  const openTabs = useUiStore((s) => s.openTabs)
  const showTab = useUiStore((s) => s.showTab)

  // Đóng menu khi bấm ra ngoài
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (moreMenuRef.current && !moreMenuRef.current.contains(e.target as Node)) {
        setMoreMenuOpen(false)
      }
    }
    if (moreMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [moreMenuOpen])

  return (
    <div className="flex h-10 shrink-0 items-center justify-between border-b border-line bg-panel px-3.5 select-none">
      {/* Left: Context Window & Usage Controls */}
      <div className="flex min-w-0 items-center gap-3">
        <ContextUsageBar variant="topbar" />
        <span
          data-testid="topbar-budget"
          className="hidden"
          aria-hidden="true"
        >
          {budget.costUsd > 0
            ? t(
                budget.capUsd > 0 ? 'shell.budgetTokensTimeCapped' : 'shell.budgetTokensTimeCost',
                {
                  tokens: formatTokenCount(budget.tokens),
                  time: formatClock(elapsedSeconds),
                  cost: budget.costUsd.toFixed(2),
                  cap: budget.capUsd.toFixed(2),
                },
              )
            : t('shell.budgetTokensTime', {
                tokens: formatTokenCount(budget.tokens),
                time: formatClock(elapsedSeconds),
              })}
        </span>
      </div>

      {/* Right: More Options (...) Button (Devin Style) */}
      <div className="flex items-center gap-1.5">
        <div className="relative inline-block" ref={moreMenuRef}>
          <button
            type="button"
            onClick={() => setMoreMenuOpen(!moreMenuOpen)}
            className={`flex size-7 items-center justify-center rounded-md text-muted transition cursor-pointer ${
              moreMenuOpen ? 'bg-panel2 text-fg shadow-2xs' : 'hover:bg-panel2 hover:text-fg'
            }`}
            title="Workspaces & Controls"
            aria-label="Workspaces & Controls"
            aria-expanded={moreMenuOpen}
            data-testid="workspace-more-btn"
          >
            <MoreHorizontal className="size-4" />
          </button>

          {/* Dropdown Popup Menu (Devin Style) */}
          {moreMenuOpen && (
            <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-xl border border-zinc-200/90 dark:border-line bg-white dark:bg-panel p-1.5 shadow-2xl shadow-black/10 dark:shadow-black/50 animate-in fade-in zoom-in-95 duration-100 select-none">
              {/* Section 1: Workspaces */}
              <div className="px-2.5 py-1 text-[11px] font-medium text-zinc-400 dark:text-zinc-500">
                Workspaces
              </div>
              <div className="space-y-0.5 mt-0.5">
                {availablePanelTabs().map((tabItem) => {
                  const Icon = tabItem.icon
                  const isAlreadyOpen = openTabs.includes(tabItem.id)
                  const shortcut = WORKSPACE_SHORTCUTS[tabItem.id]
                  return (
                    <button
                      key={tabItem.id}
                      type="button"
                      onClick={() => {
                        showTab(tabItem.id)
                        setMoreMenuOpen(false)
                      }}
                      className={`group flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                        isAlreadyOpen
                          ? 'bg-zinc-100 dark:bg-panel2/80 text-zinc-900 dark:text-fg font-medium'
                          : 'text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100/80 dark:hover:bg-panel2/60 hover:text-zinc-900 dark:hover:text-fg'
                      }`}
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Icon
                          className={`size-3.5 shrink-0 transition ${
                            isAlreadyOpen
                              ? 'text-zinc-900 dark:text-fg'
                              : 'text-zinc-500 dark:text-zinc-400 group-hover:text-zinc-800 dark:group-hover:text-zinc-200'
                          }`}
                        />
                        <span className="truncate">{tabItem.label}</span>
                      </div>
                      {shortcut && (
                        <div className="flex items-center gap-1 shrink-0 ml-2">
                          {shortcut.map((key) => (
                            <kbd
                              key={key}
                              className="rounded border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-panel2 px-1 py-0.5 text-[9px] font-mono text-zinc-400 dark:text-zinc-400 leading-none"
                            >
                              {key}
                            </kbd>
                          ))}
                        </div>
                      )}
                    </button>
                  )
                })}
              </div>

              {/* Section 2: Sandbox Machine & Network Controls */}
              <div className="my-1.5 border-t border-zinc-100 dark:border-line/40" />
              <div className="px-2.5 py-1 text-[11px] font-medium text-zinc-400 dark:text-zinc-500">
                Sandbox Controls
              </div>
              <div className="space-y-0.5 mt-0.5">
                <button
                  type="button"
                  onClick={() => box.togglePower()}
                  className="group flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100/80 dark:hover:bg-panel2/60 hover:text-zinc-900 dark:hover:text-fg transition cursor-pointer"
                >
                  <div className="flex items-center gap-2.5">
                    <Power className={`size-3.5 ${box.power === 'on' ? 'text-emerald-500' : 'text-zinc-400 dark:text-zinc-500'}`} />
                    <span className="font-medium">Machine</span>
                  </div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wider ${
                      box.power === 'on'
                        ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                        : 'bg-zinc-100 dark:bg-zinc-800/80 text-zinc-500 dark:text-zinc-400'
                    }`}
                  >
                    {box.power === 'on' ? 'ON' : 'OFF'}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => box.toggleNetwork()}
                  className="group flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100/80 dark:hover:bg-panel2/60 hover:text-zinc-900 dark:hover:text-fg transition cursor-pointer"
                >
                  <div className="flex items-center gap-2.5">
                    <Wifi className={`size-3.5 ${box.network === 'on' ? 'text-emerald-500' : 'text-zinc-400 dark:text-zinc-500'}`} />
                    <span className="font-medium">Network</span>
                  </div>
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wider ${
                      box.network === 'on'
                        ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400'
                        : 'bg-zinc-100 dark:bg-zinc-800/80 text-zinc-500 dark:text-zinc-400'
                    }`}
                  >
                    {box.network === 'on' ? 'ON' : 'OFF'}
                  </span>
                </button>
              </div>
            </div>
          )}
        </div>

        <SearchSessionsModal />
      </div>
    </div>
  )
}
