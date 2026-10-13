import { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  Cpu,
  Layers,
  Sparkles,
  Database,
  Terminal,
  ShieldCheck,
  X,
  Compass,
  Code2,
  Bug,
  Zap,
  Boxes,
  Workflow,
  Search,
} from 'lucide-react'
import { useHarnessStore, AVAILABLE_MODELS } from '../../store/harnessStore'
import { useSkillsStore } from '../../store/skillsStore'
import { useRouterStore } from '../../store/routerStore'
import { useProviderStore } from '../../store/providerStore'
import { routerChatOptions } from '../../lib/routeOptions'
import { useRuntimeInfoStore } from '../../store/runtimeInfoStore'

export interface NodeDetails {
  title: string
  description: string
  role?: string
  modelAssigned?: string
  inheritedFrom?: string
  toolsAllowed?: string[]
  toolsUnavailable?: boolean
  meta?: Record<string, string | undefined>
}

export interface FlowNode {
  id: string
  label: string
  category: 'context' | 'brain' | 'subagent' | 'skills' | 'tools' | 'memory'
  sublabel?: string
  badge?: string
  icon: React.ComponentType<{ className?: string }>
  x: number
  y: number
  width: number
  height: number
  color: string
  borderColor: string
  glowColor?: string
  phaseNumber?: number
  enabled?: boolean
  details?: NodeDetails
}

export interface FlowEdge {
  id: string
  from: string
  to: string
  label?: string
  color?: string
  animated?: boolean
  style?: 'solid' | 'dashed'
  customPath?: string
}

/**
 * Hàm sinh đường nối vuông góc 90 độ (Orthogonal Step Routing) với bo góc mềm mại
 */
function makeOrthogonalPath(
  sx: number,
  sy: number,
  ex: number,
  ey: number,
  midY?: number,
  radius = 6,
): string {
  const yBreak = midY !== undefined ? midY : (sy + ey) / 2
  const dx = ex - sx
  const dy = ey - sy

  // Đường thẳng đứng hoàn toàn
  if (Math.abs(dx) < 2) {
    return `M ${sx} ${sy} L ${ex} ${ey}`
  }

  // Đường thẳng ngang hoàn toàn
  if (Math.abs(dy) < 2) {
    return `M ${sx} ${sy} L ${ex} ${ey}`
  }

  const dirX = dx > 0 ? 1 : -1
  const dirY1 = yBreak > sy ? 1 : -1
  const dirY2 = ey > yBreak ? 1 : -1
  const r = Math.min(radius, Math.abs(dx) / 2, Math.abs(yBreak - sy) / 2, Math.abs(ey - yBreak) / 2)

  return [
    `M ${sx} ${sy}`,
    `L ${sx} ${yBreak - dirY1 * r}`,
    `Q ${sx} ${yBreak}, ${sx + dirX * r} ${yBreak}`,
    `L ${ex - dirX * r} ${yBreak}`,
    `Q ${ex} ${yBreak}, ${ex} ${yBreak + dirY2 * r}`,
    `L ${ex} ${ey}`,
  ].join(' ')
}

const ROLE_META_PRESETS: Record<
  string,
  {
    roleId: string
    titlePrefix: string
    phaseNumber?: number
    icon: React.ComponentType<{ className?: string }>
    color: string
    borderColor: string
    glowColor: string
    roleDesc: string
  }
> = {
  explore: {
    roleId: 'explore',
    titlePrefix: '1. Explore',
    phaseNumber: 1,
    icon: Compass,
     color: '#b45309',
     borderColor: 'var(--color-amber-500, #b45309)',
     glowColor: 'rgba(180, 83, 9, 0.25)',
    roleDesc: 'Khảo sát codebase, grep tìm biểu tượng, lập bản đồ kiến trúc mà không thay đổi file.',
  },
  plan: {
    roleId: 'plan',
    titlePrefix: '2. Plan & Design',
    phaseNumber: 2,
    icon: Workflow,
     color: '#a3612c',
     borderColor: 'var(--color-amber-500, #a3612c)',
     glowColor: 'rgba(163, 97, 44, 0.25)',
    roleDesc: 'Thiết kế kiến trúc, lập bản kế hoạch thực thi, xác định ranh giới an toàn trước khi code.',
  },
  design: {
    roleId: 'design',
    titlePrefix: 'Architecture Design',
    icon: Boxes,
     color: '#92400e',
     borderColor: 'var(--color-amber-500, #92400e)',
     glowColor: 'rgba(146, 64, 14, 0.25)',
    roleDesc: 'Thiết kế chi tiết giao diện và cấu trúc module, chuẩn hoá hợp đồng API và kiểu dữ liệu.',
  },
  'plan-review': {
    roleId: 'plan-review',
    titlePrefix: 'Plan Review Gate',
    icon: ShieldCheck,
     color: '#9f1239',
     borderColor: 'var(--color-rose-500, #9f1239)',
     glowColor: 'rgba(159, 18, 57, 0.25)',
    roleDesc: 'Phản biện độc lập kế hoạch: đọc kỹ bản kế hoạch, tìm rủi ro hồi quy và trả phán quyết.',
  },
  research: {
    roleId: 'research',
    titlePrefix: 'Deep Research',
    icon: Search,
     color: '#8a6d1f',
     borderColor: 'var(--color-amber-500, #8a6d1f)',
     glowColor: 'rgba(138, 109, 31, 0.25)',
    roleDesc: 'Tra cứu tài liệu API ngoài, tổng hợp kiến thức chuyên sâu và tiêu chuẩn kỹ thuật.',
  },
  'research-review': {
    roleId: 'research-review',
    titlePrefix: 'Research Review',
    icon: ShieldCheck,
     color: '#a3392e',
     borderColor: 'var(--color-rose-500, #a3392e)',
     glowColor: 'rgba(163, 57, 46, 0.25)',
    roleDesc: 'Phản biện hồ sơ nghiên cứu, kiểm chứng tài liệu tham khảo và trả phán quyết pass/revise.',
  },
  code: {
    roleId: 'build',
    titlePrefix: '3. Build & Code',
    phaseNumber: 3,
    icon: Code2,
     color: '#5b7a35',
     borderColor: 'var(--color-emerald-500, #5b7a35)',
     glowColor: 'rgba(91, 122, 53, 0.25)',
    roleDesc: 'Sinh mã nguồn chất lượng cao, thực thi thay đổi chính xác theo hợp đồng và tiêu chuẩn dự án.',
  },
  build: {
    roleId: 'build',
    titlePrefix: '3. Build & Code',
    phaseNumber: 3,
    icon: Code2,
     color: '#5b7a35',
     borderColor: 'var(--color-emerald-500, #5b7a35)',
     glowColor: 'rgba(91, 122, 53, 0.25)',
    roleDesc: 'Sinh mã nguồn chất lượng cao, thực thi thay đổi chính xác theo hợp đồng và tiêu chuẩn dự án.',
  },
  debug: {
    roleId: 'testing',
    titlePrefix: 'Debug & Fix',
    icon: Bug,
     color: '#c2820c',
     borderColor: 'var(--color-amber-500, #c2820c)',
     glowColor: 'rgba(194, 130, 12, 0.25)',
    roleDesc: 'Điều tra stacktrace, phân tích nguyên nhân gốc lỗi và sửa chữa cục bộ an toàn.',
  },
  simplify: {
    roleId: 'build',
    titlePrefix: 'Refactor & Simplify',
    icon: Zap,
     color: '#6b8e23',
     borderColor: 'var(--color-lime-500, #6b8e23)',
     glowColor: 'rgba(107, 142, 35, 0.25)',
    roleDesc: 'Tối giản mã nguồn, loại bỏ logic thừa và làm sạch cấu trúc sau khi hoàn thành tính năng.',
  },
  test: {
    roleId: 'testing',
    titlePrefix: '4. Testing & Debug',
    phaseNumber: 4,
    icon: Bug,
     color: '#b8860b',
     borderColor: 'var(--color-amber-500, #b8860b)',
     glowColor: 'rgba(184, 134, 11, 0.25)',
    roleDesc: 'Chạy thử nghiệm (Vitest, Pytest), chẩn đoán log lỗi, xác thực hành vi trong sandbox.',
  },
  testing: {
    roleId: 'testing',
    titlePrefix: '4. Testing & Debug',
    phaseNumber: 4,
    icon: Bug,
     color: '#b8860b',
     borderColor: 'var(--color-amber-500, #b8860b)',
     glowColor: 'rgba(184, 134, 11, 0.25)',
    roleDesc: 'Chạy thử nghiệm (Vitest, Pytest), chẩn đoán log lỗi, xác thực hành vi trong sandbox.',
  },
  review: {
    roleId: 'review',
    titlePrefix: '5. Review & Verify',
    phaseNumber: 5,
    icon: ShieldCheck,
     color: '#b03a2e',
     borderColor: 'var(--color-rose-500, #b03a2e)',
     glowColor: 'rgba(176, 58, 46, 0.25)',
    roleDesc: 'Rà soát mã nguồn lần cuối, đối chiếu diff với yêu cầu, kiểm tra an toàn trước khi hoàn thành.',
  },
}

export function HarnessFlowVisualizer() {
  const {
    harnesses,
    activeHarnessId,
    activeType,
    activeModelId,
    setActiveType,
    setActiveHarness,
    setActiveModel,
    getHarnessById,
  } = useHarnessStore()

  const skills = useSkillsStore((s) => s.skills)
  const activeSkills = useMemo(() => skills.filter((sk) => sk.enabled), [skills])
  const routerRoutes = useRouterStore((s) => s.routes)
  const providerSnapshot = useProviderStore((s) => s.snapshot)
  const liveRouteOptions = useMemo(() => routerChatOptions(providerSnapshot), [providerSnapshot])

  const runtimeInfo = useRuntimeInfoStore((s) => s.info)
  const loadRuntimeInfo = useRuntimeInfoStore((s) => s.load)
  useEffect(() => {
    void loadRuntimeInfo()
  }, [loadRuntimeInfo])

  const roleTools = useMemo(() => {
    const byRole = new Map((runtimeInfo?.roles ?? []).map((role) => [role.id, role.tools]))
    return (roleId: string) => byRole.get(roleId)
  }, [runtimeInfo])

  const allAvailableModels = useMemo(() => {
    const list: { id: string; name: string; provider: string }[] = []

    for (const route of routerRoutes) {
      for (const m of route.models || []) {
        if (!list.some((item) => item.id === m.id)) {
          list.push({
            id: m.id,
            name: m.name || m.id,
            provider: route.displayName || route.sourceId,
          })
        }
      }
    }

    for (const m of AVAILABLE_MODELS) {
      if (!list.some((item) => item.id === m.id)) {
        list.push({ id: m.id, name: m.name, provider: m.provider })
      }
    }

    const defaults = [
      { id: 'gemini-3.6-flash-high', name: 'Gemini 3.6 Flash (High Reasoning)', provider: 'Antigravity' },
      { id: 'gemini-3.8-flash', name: 'Gemini 3.8 Flash', provider: 'Antigravity' },
      { id: 'claude-3.7-sonnet', name: 'Claude 3.7 Sonnet', provider: 'Anthropic' },
      { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', provider: 'DeepSeek' },
    ]
    for (const d of defaults) {
      if (!list.some((item) => item.id === d.id)) {
        list.push(d)
      }
    }

    return list
  }, [routerRoutes])

  const getModelDisplayName = (modelId: string) => {
    const found = allAvailableModels.find((m) => m.id === modelId)
    if (found) return found.name
    const live = liveRouteOptions.find((option) => option.value === modelId)
    return live ? live.label : modelId
  }

  const activeHarness = useMemo(() => {
    return (
      getHarnessById(activeHarnessId) ??
      harnesses[0] ?? {
        id: 'default',
        name: 'Open Model Harness',
        description: 'Multi-step autonomous reasoning pipeline',
        isBuiltIn: true,
        mainModel: 'DeepSeek V4 Pro (Global) 1M High',
        subagents: [],
      }
    )
  }, [getHarnessById, activeHarnessId, harnesses])

  const isSingleModelMode = activeType === 'model'
  const activeSingleModelName = getModelDisplayName(activeModelId || 'gemini-3.6-flash-high')

  // Pan & Zoom state (với Ref tối ưu 60 FPS không gây re-render liên tục khi pan)
  const [zoom, setZoom] = useState(0.95)
  const [pan, setPan] = useState({ x: 0, y: -10 })
  const [isDragging, setIsDragging] = useState(false)
  const [selectedNode, setSelectedNode] = useState<FlowNode | null>(null)

  const panRef = useRef({ x: 0, y: -10 })
  const dragStartRef = useRef({ x: 0, y: 0 })
  const transformLayerRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const rafRef = useRef<number | null>(null)

  // Zoom controls
  const handleZoomIn = () => setZoom((z) => Math.min(1.8, +(z + 0.15).toFixed(2)))
  const handleZoomOut = () => setZoom((z) => Math.max(0.45, +(z - 0.15).toFixed(2)))
  const handleReset = () => {
    setZoom(0.95)
    setPan({ x: 0, y: -10 })
    panRef.current = { x: 0, y: -10 }
    if (transformLayerRef.current) {
      transformLayerRef.current.style.transform = `translate(0px, -10px) scale(0.95)`
    }
  }

  // Smooth dragging handlers with zero-lag direct transform
  const onMouseDown = (e: React.MouseEvent) => {
    if (
      (e.target as HTMLElement).closest('.flow-node') ||
      (e.target as HTMLElement).closest('.flow-controls') ||
      (e.target as HTMLElement).closest('.flow-header') ||
      (e.target as HTMLElement).closest('[data-drawer]')
    ) {
      return
    }
    setIsDragging(true)
    dragStartRef.current = {
      x: e.clientX - panRef.current.x,
      y: e.clientY - panRef.current.y,
    }
  }

  const onMouseMove = (e: React.MouseEvent) => {
    if (!isDragging) return
    const nextX = Math.round(e.clientX - dragStartRef.current.x)
    const nextY = Math.round(e.clientY - dragStartRef.current.y)
    panRef.current = { x: nextX, y: nextY }

    if (rafRef.current) cancelAnimationFrame(rafRef.current)
    rafRef.current = requestAnimationFrame(() => {
      if (transformLayerRef.current) {
        transformLayerRef.current.style.transform = `translate(${nextX}px, ${nextY}px) scale(${zoom})`
      }
    })
  }

  const onMouseUp = () => {
    if (!isDragging) return
    setIsDragging(false)
    setPan(panRef.current)
  }

  const onWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault()
      const delta = e.deltaY > 0 ? -0.06 : 0.06
      setZoom((z) => {
        const next = Math.min(1.8, Math.max(0.45, +(z + delta).toFixed(2)))
        return next
      })
    },
    [],
  )

  useEffect(() => {
    panRef.current = pan
    if (transformLayerRef.current) {
      transformLayerRef.current.style.transform = `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`
    }
  }, [pan, zoom])

  // Cấu trúc Data-driven Flow Nodes phản ánh chính xác Harness hiện tại
  const { nodes, edges } = useMemo(() => {
    const effectiveMainModel = isSingleModelMode
      ? activeSingleModelName
      : activeHarness.mainModel === 'default'
      ? 'Claude 3.7 Sonnet / Antigravity'
      : activeHarness.mainModel

    const getSubagentModel = (subagentModel?: string) => {
      if (isSingleModelMode) return activeSingleModelName
      if (!subagentModel || subagentModel === 'inherit' || subagentModel === 'default') {
        return `Inherit: ${effectiveMainModel}`
      }
      return subagentModel
    }

    const flowNodes: FlowNode[] = []
    const flowEdges: FlowEdge[] = []

    // 1. TẦNG 1 (Top: y = -215): 3-Tier Context Engine
    flowNodes.push({
      id: 'context-engine',
      label: '3-Tier Context Engine',
      category: 'context',
      sublabel: 'Hierarchical Prompt Caching & Grounding',
      badge: 'Tier 1 • 2 • 3',
      icon: Layers,
      x: 0,
      y: -215,
      width: 270,
      height: 60,
      color: '#b45309',
      borderColor: 'var(--color-amber-500, #b45309)',
      glowColor: 'rgba(180, 83, 9, 0.2)',
      details: {
        title: '3-Tier Context Engine (Prompt Hierarchical Caching)',
        role: 'Context Layer Manager',
        description:
          'Quản lý ngữ cảnh phân tầng nhằm tối ưu hoá tỷ lệ prompt-caching LLM và cung cấp nền tảng grounding sandbox thời gian thực.',
        meta: {
          'Tier 1 (Stable)': 'Identity, Coding Principles & Anti-Loop Constraints',
          'Tier 2 (Environment)': 'OS Windows, Workspace Directory Snapshot & Git Status',
          'Tier 3 (Dynamic)': 'User Goal, Active Skills Injected & Current Lineage',
          'Active Skills Injected': `${activeSkills.length} disciplines enabled`,
        },
      },
    })

    // 2. TẦNG 2 (Orchestrator Brain: y = -90)
    flowNodes.push({
      id: 'orchestrator-brain',
      label: 'Orchestrator Brain',
      category: 'brain',
      sublabel: effectiveMainModel,
      badge: isSingleModelMode ? 'Single Model Mode (Active)' : 'Harness Orchestrator',
      icon: Cpu,
      x: 0,
      y: -90,
      width: 290,
      height: 70,
      color: '#c2410c',
      borderColor: 'var(--color-amber-500, #c2410c)',
      glowColor: 'rgba(194, 65, 12, 0.3)',
      details: {
        title: `Orchestrator Brain (${isSingleModelMode ? 'Single Model Mode' : activeHarness.name})`,
        role: 'Central Dispatcher & Task Decomposition',
        modelAssigned: effectiveMainModel,
        inheritedFrom: isSingleModelMode ? 'User Single Model Selection' : 'Harness Architecture Config',
        description:
          'Bộ não trung tâm phụ trách lập luận multi-step, phân rã nhiệm vụ và điều phối các Subagents chuyên biệt.',
        meta: {
          'Selected Model': effectiveMainModel,
          'Execution Engine': 'Hermes Cognitive Core Loop (Async Delegation)',
          'Anti-Loop Guard': 'Active',
          'Status': isSingleModelMode ? 'Direct Override Active' : 'Multi-Agent Topology Active',
        },
      },
    })

    // Đường nối thẳng đứng từ Context Engine -> Orchestrator Brain
    flowEdges.push({
      id: 'e-ctx-brain',
      from: 'context-engine',
      to: 'orchestrator-brain',
      label: 'Context Injection',
      color: '#b45309',
      animated: true,
      customPath: 'M 0 -185 L 0 -125',
    })

    // 3. TẦNG 3 (Subagents Execution Pipeline: 2-Stage Compact Layout)
    // Lấy danh sách subagents động từ activeHarness, nếu rỗng thì fallback chuẩn 5 subagent
    const subagentsSource: Array<{ id: string; name: string; enabled?: boolean; model?: string }> =
      Array.isArray(activeHarness.subagents) && activeHarness.subagents.length > 0
        ? activeHarness.subagents
        : [
            { id: 'explore', name: 'Explore', enabled: true, model: 'default' },
            { id: 'plan', name: 'Plan & Design', enabled: true, model: 'default' },
            { id: 'build', name: 'Build & Code', enabled: true, model: 'default' },
            { id: 'testing', name: 'Testing & Debug', enabled: true, model: 'default' },
            { id: 'review', name: 'Review & Verify', enabled: true, model: 'default' },
          ]

    // Phân bổ subagents thành 2 giai đoạn hợp lý (Stage 1 & Stage 2) để không bị kéo dãn bề ngang
    const STAGE_1_KEYS = new Set(['explore', 'plan', 'design', 'plan-review', 'research'])
    let stage1List = subagentsSource.filter((s) => STAGE_1_KEYS.has(s.id))
    let stage2List = subagentsSource.filter((s) => !STAGE_1_KEYS.has(s.id))

    // Fallback chia đều nếu một bên rỗng
    if (stage1List.length === 0 || stage2List.length === 0) {
      const mid = Math.ceil(subagentsSource.length / 2)
      stage1List = subagentsSource.slice(0, mid)
      stage2List = subagentsSource.slice(mid)
    }

    const cardWidth = 190
    const cardHeight = 70
    const spacingX = 215

    // Stage 1 Nodes (Analysis, Architecture & Research: y = 35)
    const stage1Nodes: FlowNode[] = []
    const startX1 = -((stage1List.length - 1) * spacingX) / 2

    stage1List.forEach((sub, idx) => {
      const preset = ROLE_META_PRESETS[sub.id] || {
        roleId: sub.id,
        titlePrefix: sub.name || `Subagent ${idx + 1}`,
        phaseNumber: idx + 1,
        icon: Workflow,
        color: '#a3612c',
        borderColor: '#92400e',
        glowColor: 'rgba(163, 97, 44, 0.2)',
        roleDesc: 'Subagent chuyên biệt trong quy trình điều phối.',
      }

      const assignedModel = getSubagentModel(sub.model)
      const xPos = Math.round(startX1 + idx * spacingX)
      const yPos = 35
      const nodeKey = `subagent-${sub.id}`
      const isEnabled = sub.enabled !== false

      const node: FlowNode = {
        id: nodeKey,
        label: preset.titlePrefix,
        category: 'subagent',
        phaseNumber: preset.phaseNumber ?? idx + 1,
        sublabel: assignedModel,
        badge: isSingleModelMode
          ? 'Single Override'
          : isEnabled
          ? 'Active Agent'
          : 'Disabled',
        icon: preset.icon,
        x: xPos,
        y: yPos,
        width: cardWidth,
        height: cardHeight,
        color: preset.color,
        borderColor: preset.borderColor,
        glowColor: preset.glowColor,
        enabled: isEnabled,
        details: {
          title: `${preset.titlePrefix} (${sub.name || sub.id})`,
          role: preset.roleDesc,
          modelAssigned: assignedModel,
          description: preset.roleDesc,
          toolsAllowed: roleTools(preset.roleId),
          toolsUnavailable: roleTools(preset.roleId) === undefined,
          meta: {
            Status: isEnabled ? 'Enabled in Harness' : 'Disabled in Harness',
            AssignedModel: assignedModel,
          },
        },
      }

      flowNodes.push(node)
      stage1Nodes.push(node)

      // Nối vuông góc từ Orchestrator Brain đáy (y = -55) -> Stage 1 đỉnh (y = 0) qua rãnh y = -25
      const branchPath = makeOrthogonalPath(0, -55, xPos, 0, -25, 6)
      flowEdges.push({
        id: `e-brain-${sub.id}`,
        from: 'orchestrator-brain',
        to: nodeKey,
        color: isEnabled ? preset.color : '#78716c',
        animated: isEnabled,
        style: isEnabled ? 'solid' : 'dashed',
        customPath: branchPath,
      })
    })

    // Nối tuần tự trong Stage 1 (Left to Right)
    for (let i = 0; i < stage1Nodes.length - 1; i++) {
      const curr = stage1Nodes[i]
      const next = stage1Nodes[i + 1]
      const rightPortX = curr.x + curr.width / 2
      const leftPortX = next.x - next.width / 2
      flowEdges.push({
        id: `e-pipe-s1-${curr.id}-${next.id}`,
        from: curr.id,
        to: next.id,
        color: curr.color,
        animated: true,
        customPath: `M ${rightPortX} ${curr.y} L ${leftPortX} ${curr.y}`,
      })
    }

    // Stage 2 Nodes (Implementation, Testing & Verification: y = 155)
    const stage2Nodes: FlowNode[] = []
    const startX2 = -((stage2List.length - 1) * spacingX) / 2

    stage2List.forEach((sub, idx) => {
      const preset = ROLE_META_PRESETS[sub.id] || {
        roleId: sub.id,
        titlePrefix: sub.name || `Subagent ${stage1List.length + idx + 1}`,
        phaseNumber: stage1List.length + idx + 1,
        icon: Workflow,
        color: '#a3612c',
        borderColor: '#92400e',
        glowColor: 'rgba(163, 97, 44, 0.2)',
        roleDesc: 'Subagent chuyên biệt trong quy trình thực thi & kiểm thử.',
      }

      const assignedModel = getSubagentModel(sub.model)
      const xPos = Math.round(startX2 + idx * spacingX)
      const yPos = 155
      const nodeKey = `subagent-${sub.id}`
      const isEnabled = sub.enabled !== false

      const node: FlowNode = {
        id: nodeKey,
        label: preset.titlePrefix,
        category: 'subagent',
        phaseNumber: preset.phaseNumber ?? stage1List.length + idx + 1,
        sublabel: assignedModel,
        badge: isSingleModelMode
          ? 'Single Override'
          : isEnabled
          ? 'Active Agent'
          : 'Disabled',
        icon: preset.icon,
        x: xPos,
        y: yPos,
        width: cardWidth,
        height: cardHeight,
        color: preset.color,
        borderColor: preset.borderColor,
        glowColor: preset.glowColor,
        enabled: isEnabled,
        details: {
          title: `${preset.titlePrefix} (${sub.name || sub.id})`,
          role: preset.roleDesc,
          modelAssigned: assignedModel,
          description: preset.roleDesc,
          toolsAllowed: roleTools(preset.roleId),
          toolsUnavailable: roleTools(preset.roleId) === undefined,
          meta: {
            Status: isEnabled ? 'Enabled in Harness' : 'Disabled in Harness',
            AssignedModel: assignedModel,
          },
        },
      }

      flowNodes.push(node)
      stage2Nodes.push(node)
    })

    // Nối tuần tự trong Stage 2 (Left to Right)
    for (let i = 0; i < stage2Nodes.length - 1; i++) {
      const curr = stage2Nodes[i]
      const next = stage2Nodes[i + 1]
      const rightPortX = curr.x + curr.width / 2
      const leftPortX = next.x - next.width / 2
      flowEdges.push({
        id: `e-pipe-s2-${curr.id}-${next.id}`,
        from: curr.id,
        to: next.id,
        color: curr.color,
        animated: true,
        customPath: `M ${rightPortX} ${curr.y} L ${leftPortX} ${curr.y}`,
      })
    }

    // Chuyển giao giữa Stage 1 và Stage 2 (Design Handoff connector)
    if (stage1Nodes.length > 0 && stage2Nodes.length > 0) {
      const lastStage1 = stage1Nodes[stage1Nodes.length - 1]
      const firstStage2 = stage2Nodes[0]
      const s1Bottom = lastStage1.y + lastStage1.height / 2 // 35 + 35 = 70
      const s2Top = firstStage2.y - firstStage2.height / 2 // 155 - 35 = 120
      const midHandoffY = 95
      const handoffPath = makeOrthogonalPath(
        lastStage1.x,
        s1Bottom,
        firstStage2.x,
        s2Top,
        midHandoffY,
        6,
      )
      flowEdges.push({
        id: 'e-handoff-s1-s2',
        from: lastStage1.id,
        to: firstStage2.id,
        label: 'Design Handoff',
        color: '#a3612c',
        animated: true,
        customPath: handoffPath,
      })
    }

    // 4. TẦNG 4 (Bottom Infrastructure: y = 270)
    // Khối Trái: Skills Pool
    flowNodes.push({
      id: 'skills-pool',
      label: 'Active Skills Pool',
      category: 'skills',
      sublabel: `${activeSkills.length} Hermes Disciplines Injected`,
      badge: `${activeSkills.length} Skills`,
      icon: Sparkles,
      x: -240,
      y: 270,
      width: 200,
      height: 60,
      color: '#b45309',
      borderColor: 'var(--color-amber-500, #b45309)',
      details: {
        title: 'Active Hermes & Antigravity Skills Pool',
        role: 'Specialized Prompt Disciplines',
        description:
          'Các bộ quy chuẩn và kỹ năng chuyên sâu được nạp động vào Tier 3 Context để định hướng tác phong làm việc của các subagents.',
        meta: {
          'Active Count': `${activeSkills.length} skills active`,
          'Selected Skills': activeSkills.map((s) => s.name).join(', ') || 'None',
        },
      },
    })

    // Khối Giữa: Memory Ledger
    flowNodes.push({
      id: 'memory-ledger',
      label: 'Memory Ledger',
      category: 'memory',
      sublabel: 'SQLite Durable Turns & Lineage',
      badge: 'Durable Storage',
      icon: Database,
      x: 0,
      y: 270,
      width: 200,
      height: 60,
      color: '#8a6d1f',
      borderColor: 'var(--color-amber-500, #8a6d1f)',
      details: {
        title: 'Multi-Turn Memory Ledger (SQLite & Checkpoints)',
        role: 'Durable State & Lineage Persistence',
        description:
          'Lưu trữ toàn bộ lịch sử hội thoại, sự kiện công cụ, dấu vết phân rã subagent và checkpoint phục hồi sau khi restart.',
        meta: {
          'Storage Backend': 'SQLite Database (Durable Tables)',
          'Recovery Guarantee': 'Durable Lineage Tracking & Auto Compaction',
        },
      },
    })

    // Khối Phải: Core Tools Suite
    flowNodes.push({
      id: 'tools-suite',
      label: 'Core Tools Suite',
      category: 'tools',
      sublabel: 'Docker Sandbox & Native Tooling',
      badge: 'Sandbox APIs',
      icon: Terminal,
      x: 240,
      y: 270,
      width: 200,
      height: 60,
      color: '#5b7a35',
      borderColor: 'var(--color-emerald-500, #5b7a35)',
      details: {
        title: 'Core Tools Suite & Execution Runtimes',
        role: 'Sandboxed Tool Providers',
        description:
          'Hệ thống công cụ thực thi mạnh mẽ được cách ly trong sandbox và bảo vệ bằng cơ chế phân quyền theo vai trò.',
        meta: {
          'File Ops': 'file_read, file_write, file_edit_block, codebase_grep',
          'Terminal': 'terminal_exec inside isolated sandbox',
        },
      },
    })

    // Đường kết nối vuông vức từ Tầng 4 (Hạ tầng đáy)
    // 1) Memory Ledger kết nối với rãnh giữa:
    flowEdges.push({
      id: 'e-mem-ledger',
      from: 'memory-ledger',
      to: 'orchestrator-brain',
      color: '#8a6d1f',
      animated: true,
      customPath: makeOrthogonalPath(0, 240, 0, 190, 215, 6),
    })

    const leftBoundaryX = Math.min(startX1, startX2) - 110
    const rightBoundaryX = Math.max(
      startX1 + (stage1List.length - 1) * spacingX,
      startX2 + (stage2List.length - 1) * spacingX,
    ) + 110

    // 2) Skills Pool kết nối rãnh ngoài bên trái chạy lên Context Engine:
    flowEdges.push({
      id: 'e-skills-bus',
      from: 'skills-pool',
      to: 'context-engine',
      color: '#b45309',
      style: 'dashed',
      customPath: [
        'M -240 240',
        'L -240 215',
        `L ${leftBoundaryX} 215`,
        `L ${leftBoundaryX} -215`,
        'L -135 -215',
      ].join(' '),
    })

    // 3) Tools Suite kết nối rãnh ngoài bên phải:
    flowEdges.push({
      id: 'e-tools-bus',
      from: 'tools-suite',
      to: 'orchestrator-brain',
      color: '#5b7a35',
      style: 'dashed',
      customPath: [
        'M 240 240',
        'L 240 215',
        `L ${rightBoundaryX} 215`,
        `L ${rightBoundaryX} -90`,
        'L 145 -90',
      ].join(' '),
    })

    return { nodes: flowNodes, edges: flowEdges }
  }, [
    isSingleModelMode,
    activeSingleModelName,
    activeHarness,
    activeSkills,
    roleTools,
  ])

  // Map vị trí của các Nodes để fallback
  const nodeMap = useMemo(() => {
    const map = new Map<string, FlowNode>()
    for (const n of nodes) map.set(n.id, n)
    return map
  }, [nodes])

  return (
    <div className="relative flex h-[680px] w-full flex-col overflow-hidden rounded-2xl border border-line bg-panel select-none shadow-sm transition-colors">
      {/* Background Dot Grid tinh tế theo theme BoxFox */}
      <svg className="absolute inset-0 size-full pointer-events-none opacity-40">
        <defs>
          <pattern id="harness-dot-grid" width="24" height="24" patternUnits="userSpaceOnUse">
            <circle cx="2" cy="2" r="1" className="fill-muted/40" />
          </pattern>
        </defs>
        <rect width="100%" height="100%" fill="url(#harness-dot-grid)" />
      </svg>

      {/* Top Header Interactive Toolbar & Status Overlay */}
      <div className="flow-header absolute top-4 left-4 right-4 z-20 flex flex-wrap items-center justify-between gap-3 pointer-events-auto">
        {/* Left: Mode Title & Realtime Badge */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 rounded-xl border border-line bg-panel2/95 px-3.5 py-2 shadow-sm backdrop-blur-xs">
            <div className="size-2 rounded-full bg-[#5b7a35] ring-4 ring-[#5b7a35]/20" />
            <span className="text-xs font-bold text-fg tracking-tight">BoxFox Topology Flow</span>
            <span className="text-xs text-muted/60">|</span>
            <div className="flex items-center gap-1.5 text-xs">
              <span className="text-muted text-[11px]">Mode:</span>
              <span
                className={`font-semibold font-mono text-[11px] px-2 py-0.5 rounded-md border ${
                  isSingleModelMode
                    ? 'border-[#5b7a35]/40 bg-[#5b7a35]/10 text-[#5b7a35] dark:text-[#a3b86b]'
                    : 'border-brand/40 bg-brand/10 text-brand'
                }`}
              >
                {isSingleModelMode ? 'Single Model Mode' : 'Multi-Agent Harness'}
              </span>
            </div>
          </div>
        </div>

        {/* Right: Quick Switcher Bar */}
        <div className="flex items-center gap-2 rounded-xl border border-line bg-panel2/95 p-1 shadow-sm backdrop-blur-xs">
          <button
            type="button"
            onClick={() => setActiveType('harness')}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition cursor-pointer ${
              !isSingleModelMode
                ? 'bg-brand text-brandfg shadow-xs'
                : 'text-muted hover:text-fg'
            }`}
          >
            <Boxes className="size-3.5" />
            <span>Harness Topology</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveType('model')}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-semibold transition cursor-pointer ${
              isSingleModelMode
                ? 'bg-[#5b7a35] text-white shadow-xs'
                : 'text-muted hover:text-fg'
            }`}
          >
            <Zap className="size-3.5" />
            <span>Single Model</span>
          </button>

          <div className="h-4 w-px bg-line mx-1" />

          {isSingleModelMode ? (
            <div className="flex items-center gap-1.5 pl-1">
              <span className="text-[11px] font-medium text-muted">Active Model:</span>
              <select
                value={activeModelId}
                onChange={(e) => setActiveModel(e.target.value)}
                className="appearance-none rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-mono font-medium text-[#5b7a35] dark:text-[#a3b86b] outline-none hover:border-[#5b7a35]/60 focus:border-[#5b7a35] cursor-pointer max-w-[200px] truncate"
              >
                {allAvailableModels.map((m) => (
                  <option key={m.id} value={m.id} className="bg-panel text-fg">
                    {m.name} ({m.provider})
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 pl-1">
              <span className="text-[11px] font-medium text-muted">Harness:</span>
              <select
                value={activeHarnessId}
                onChange={(e) => setActiveHarness(e.target.value)}
                className="appearance-none rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-semibold text-brand outline-none hover:border-brand/60 focus:border-brand cursor-pointer max-w-[200px] truncate"
              >
                {harnesses.map((h) => (
                  <option key={h.id} value={h.id} className="bg-panel text-fg">
                    {h.name}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Interactive Drag & Zoom Canvas (Tối ưu 60 FPS không giật lag) */}
      <div
        ref={containerRef}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        onWheel={onWheel}
        className="relative flex-1 cursor-grab active:cursor-grabbing overflow-hidden"
      >
        <div
          ref={transformLayerRef}
          className="absolute left-1/2 top-1/2 origin-center"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            willChange: isDragging ? 'transform' : 'auto',
          }}
        >
          {/* SVG Orthogonal Connection Lines */}
          <svg
            className="absolute left-0 top-0 pointer-events-none overflow-visible"
            style={{ width: 1, height: 1 }}
          >
            <defs>
              <marker
                id="flow-arrow-brand"
                viewBox="0 0 10 10"
                refX="7"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 2 L 7 5 L 0 8 z" fill="#c2410c" />
              </marker>
              <marker
                id="flow-arrow-cyan"
                viewBox="0 0 10 10"
                refX="7"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 2 L 7 5 L 0 8 z" fill="#b45309" />
              </marker>
              <marker
                id="flow-arrow-emerald"
                viewBox="0 0 10 10"
                refX="7"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 2 L 7 5 L 0 8 z" fill="#5b7a35" />
              </marker>
              <marker
                id="flow-arrow-indigo"
                viewBox="0 0 10 10"
                refX="7"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 2 L 7 5 L 0 8 z" fill="#8a6d1f" />
              </marker>
              <marker
                id="flow-arrow-purple"
                viewBox="0 0 10 10"
                refX="7"
                refY="5"
                markerWidth="6"
                markerHeight="6"
                orient="auto-start-reverse"
              >
                <path d="M 0 2 L 7 5 L 0 8 z" fill="#a3612c" />
              </marker>
            </defs>

            {edges.map((edge) => {
              const fromNode = nodeMap.get(edge.from)
              const toNode = nodeMap.get(edge.to)
              if (!fromNode || (!toNode && !edge.customPath)) return null

              let pathData = edge.customPath
              if (!pathData && fromNode && toNode) {
                pathData = makeOrthogonalPath(
                  fromNode.x,
                  fromNode.y,
                  toNode.x,
                  toNode.y,
                )
              }

              if (!pathData) return null

              const isSelected =
                selectedNode?.id === fromNode?.id || selectedNode?.id === toNode?.id
              const edgeColor = isSelected ? '#c2410c' : edge.color || 'var(--color-line)'

              const markerId =
                edgeColor === '#b45309'
                  ? 'cyan'
                  : edgeColor === '#5b7a35'
                  ? 'emerald'
                  : edgeColor === '#8a6d1f'
                  ? 'indigo'
                  : edgeColor === '#a3612c'
                  ? 'purple'
                  : 'brand'

              return (
                <g key={edge.id}>
                  {/* Đường nền shadow nhẹ tạo độ nổi */}
                  <path
                    d={pathData}
                    fill="none"
                    stroke="var(--color-bg, #090a0f)"
                    strokeWidth={isSelected ? 4 : 3}
                    strokeOpacity={0.6}
                  />

                  {/* Đường nối vuông góc chính */}
                  <path
                    d={pathData}
                    fill="none"
                    stroke={edgeColor}
                    strokeWidth={isSelected ? 2.5 : 1.75}
                    strokeDasharray={
                      edge.style === 'dashed'
                        ? '5 4'
                        : edge.animated
                        ? '6 4'
                        : undefined
                    }
                    strokeOpacity={isSelected ? 1 : 0.75}
                    markerEnd={`url(#flow-arrow-${markerId})`}
                  />
                </g>
              )
            })}
          </svg>

          {/* Render Flow Nodes (Clean Cards đồng bộ Theme) */}
          {nodes.map((node) => {
            const Icon = node.icon
            const isBrain = node.category === 'brain'
            const isContext = node.category === 'context'
            const isSelected = selectedNode?.id === node.id

            return (
              <div
                key={node.id}
                onClick={(e) => {
                  e.stopPropagation()
                  setSelectedNode(node)
                }}
                className={`flow-node absolute transform -translate-x-1/2 -translate-y-1/2 cursor-pointer select-none ${
                  isBrain ? 'z-30' : isContext ? 'z-25' : 'z-20'
                }`}
                style={{
                  left: `${node.x}px`,
                  top: `${node.y}px`,
                  width: `${node.width}px`,
                }}
              >
                <div
                  className={`group relative flex flex-col rounded-xl border p-3 transition-all duration-150 ${
                    isSelected
                      ? 'border-brand bg-panel2 ring-2 ring-brand/30 shadow-md'
                      : 'border-line bg-panel2/90 hover:border-brand/60 hover:bg-panel2 shadow-xs'
                  } ${node.enabled === false ? 'opacity-50' : ''}`}
                  style={{
                    borderLeftWidth: '3px',
                    borderLeftColor: node.color,
                  }}
                >
                  {/* Top: Icon + Label + Badge */}
                  <div className="flex items-center justify-between gap-1.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <div
                        className="flex size-6 shrink-0 items-center justify-center rounded-lg border"
                        style={{
                          borderColor: `${node.color}40`,
                          backgroundColor: `${node.color}15`,
                          color: node.color,
                        }}
                      >
                        <Icon className="size-3.5" />
                      </div>
                      <span
                        className={`truncate font-bold tracking-tight text-fg ${
                          isBrain ? 'text-xs' : 'text-[11px]'
                        }`}
                      >
                        {node.label}
                      </span>
                    </div>

                    {node.badge && (
                      <span
                        className={`rounded px-1.5 py-0.5 text-[9px] font-mono font-medium uppercase tracking-wider shrink-0 ${
                          isSingleModelMode && isBrain
                            ? 'bg-[#5b7a35]/15 text-[#5b7a35] dark:text-[#a3b86b] border border-[#5b7a35]/30'
                            : 'bg-panel text-muted border border-line'
                        }`}
                      >
                        {node.badge}
                      </span>
                    )}
                  </div>

                  {/* Sublabel / Model Name */}
                  {node.sublabel && (
                    <div className="mt-2 flex items-center gap-1.5 border-t border-line/50 pt-1.5">
                      {isBrain && (
                        <div
                          className={`size-1.5 shrink-0 rounded-full ${
                            isSingleModelMode ? 'bg-[#5b7a35] dark:bg-[#a3b86b]' : 'bg-brand'
                          }`}
                        />
                      )}
                      <span
                        className={`truncate text-[11px] font-mono ${
                          isSingleModelMode && (isBrain || node.category === 'subagent')
                            ? 'text-[#5b7a35] dark:text-[#a3b86b] font-semibold'
                            : 'text-muted'
                        }`}
                        title={node.sublabel}
                      >
                        {node.sublabel}
                      </span>
                    </div>
                  )}

                  {/* Phase number indicator */}
                  {node.phaseNumber && (
                    <div className="absolute -top-2 -left-2 flex size-4 items-center justify-center rounded-full bg-panel border border-line text-[9px] font-mono text-muted font-bold shadow-xs">
                      {node.phaseNumber}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Floating Bottom-Left Zoom Toolbar */}
      <div className="flow-controls absolute bottom-4 left-4 z-20 flex items-center gap-1 rounded-xl border border-line bg-panel2/95 p-1 shadow-sm backdrop-blur-xs">
        <button
          type="button"
          onClick={handleZoomIn}
          title="Zoom In"
          className="rounded-lg p-1.5 text-muted hover:bg-panel hover:text-fg transition cursor-pointer"
        >
          <ZoomIn className="size-3.5" />
        </button>
        <button
          type="button"
          onClick={handleZoomOut}
          title="Zoom Out"
          className="rounded-lg p-1.5 text-muted hover:bg-panel hover:text-fg transition cursor-pointer"
        >
          <ZoomOut className="size-3.5" />
        </button>
        <div className="h-4 w-px bg-line" />
        <button
          type="button"
          onClick={handleReset}
          title="Reset View"
          className="rounded-lg p-1.5 text-muted hover:bg-panel hover:text-fg transition cursor-pointer"
        >
          <Maximize2 className="size-3.5" />
        </button>
        <span className="px-1.5 text-[11px] font-mono text-muted">{Math.round(zoom * 100)}%</span>
      </div>

      {/* Floating Bottom-Right Legend Indicator */}
      <div className="absolute bottom-4 right-4 z-20 hidden md:flex items-center gap-4 rounded-xl border border-line bg-panel2/95 px-3.5 py-1.5 shadow-sm backdrop-blur-xs text-[11px] text-muted">
        <div className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-[#b45309]" />
          <span>Context & Explore</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-[#c2410c]" />
          <span>Orchestrator</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-[#5b7a35]" />
          <span>Build & Code</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="size-2 rounded-full bg-[#b03a2e]" />
          <span>Review Gate</span>
        </div>
      </div>

      {/* Selected Node Details Side Drawer */}
      {selectedNode && (
        <div
          data-drawer="true"
          className="absolute right-4 top-16 bottom-4 z-30 w-84 rounded-2xl border border-line bg-panel p-5 shadow-xl overflow-y-auto space-y-4 animate-slide-in-right"
        >
          <div className="flex items-start justify-between gap-3 border-b border-line pb-3">
            <div className="flex items-center gap-2">
              <div
                className="flex size-8 items-center justify-center rounded-lg border p-1"
                style={{
                  borderColor: `${selectedNode.color}40`,
                  backgroundColor: `${selectedNode.color}15`,
                  color: selectedNode.color,
                }}
              >
                <selectedNode.icon className="size-4" />
              </div>
              <div>
                <h3 className="text-xs font-bold text-fg">{selectedNode.label}</h3>
                {selectedNode.details?.role && (
                  <span className="text-[11px] text-muted font-medium block">
                    {selectedNode.details.role}
                  </span>
                )}
              </div>
            </div>
            <button
              type="button"
              onClick={() => setSelectedNode(null)}
              className="rounded-lg p-1 text-muted hover:bg-panel2 hover:text-fg transition cursor-pointer"
            >
              <X className="size-4" />
            </button>
          </div>

          {selectedNode.details && (
            <div className="space-y-3.5 text-xs">
              {/* Description */}
              <div>
                <span className="text-[11px] font-bold text-brand uppercase tracking-wider">
                  Mô Tả & Trách Nhiệm
                </span>
                <p className="mt-1 text-muted leading-relaxed text-[11px]">
                  {selectedNode.details.description}
                </p>
              </div>

              {/* Model Assignment Info */}
              {selectedNode.details.modelAssigned && (
                <div className="rounded-xl border border-line bg-panel2 p-2.5 space-y-1">
                  <span className="text-[11px] font-semibold text-muted uppercase block">
                    Model Được Gán
                  </span>
                  <span className="text-xs font-mono font-semibold text-[#5b7a35] dark:text-[#a3b86b] block break-words">
                    {selectedNode.details.modelAssigned}
                  </span>
                  {selectedNode.details.inheritedFrom && (
                    <span className="text-[11px] text-muted/80 block">
                      Nguồn: {selectedNode.details.inheritedFrom}
                    </span>
                  )}
                </div>
              )}

              {/* Tools Allowed */}
              {(selectedNode.details.toolsAllowed || selectedNode.details.toolsUnavailable) && (
                <div className="space-y-1.5 border-t border-line pt-3">
                  <span className="text-[11px] font-bold text-muted uppercase tracking-wider">
                    Tools Được Phép Thực Thi
                  </span>
                  {(selectedNode.details.toolsAllowed?.length ?? 0) > 0 ? (
                    <div className="flex flex-wrap gap-1 mt-1">
                      {(selectedNode.details.toolsAllowed ?? []).map((t) => (
                        <span
                          key={t}
                          className="rounded-md border border-line bg-panel2 px-2 py-0.5 text-[11px] font-mono text-[#8a6d1f] dark:text-[#c9a227]"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="mt-1 text-[11px] text-muted">
                      Danh sách công cụ đang unavailable — engine chưa trả lời. Sơ đồ không đoán tên công cụ.
                    </p>
                  )}
                </div>
              )}

              {/* Meta Specifications */}
              {selectedNode.details.meta && (
                <div className="space-y-2 border-t border-line pt-3">
                  <span className="text-[11px] font-bold text-muted uppercase tracking-wider">
                    Thông Số Kỹ Thuật
                  </span>
                  {Object.entries(selectedNode.details.meta).map(([key, value]) => (
                    <div key={key} className="rounded-xl border border-line bg-panel2 p-2">
                      <span className="text-[11px] font-semibold text-muted uppercase block">
                        {key}
                      </span>
                      <span className="text-[11px] font-medium text-fg break-words">{value}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
