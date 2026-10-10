/**
 * Kiểu dữ liệu cho tab Settings → Machines → Machine & Permissions (host mode).
 *
 * Nguồn là động cơ quyền ở harness (`backend/src/agentbox/agent_core/permissions.py`)
 * và hàng rào điều khiển desktop (`agent_core/desktop_control.py`) — hai hợp đồng đã
 * chốt ở `docs/plan/desktop-host-mode.md` §3–§4. Gõ tay ở bước này vì repo chưa có
 * bộ sinh kiểu; khi có thì thay bằng bản sinh tự động để hai phía không lệch.
 *
 * Chế độ `docker` KHÔNG có động cơ quyền: mọi route quyền/desktop trả 409 với mã
 * `PERMISSIONS_UNAVAILABLE` / `DESKTOP_CONTROL_UNAVAILABLE` — giao diện phải đọc
 * được các mã đó, không được vỡ.
 */

/** Three approval levels. Legacy `plan` is migrated to `ask` by the backend. */
export type PermissionMode = 'ask' | 'auto' | 'trusted'

/** Phạm vi: `machine` là toàn máy, `workspace` siết thêm cho đường dẫn ngoài workspace. */
export type PermissionScope = 'workspace' | 'machine'

/**
 * Trục mạng (Codex `NetworkAccess`): `restricted` hỏi trước các lệnh ra mạng khi chế độ
 * sẽ chạy chúng im lặng (ở mọi mức); `enabled` không thêm câu hỏi mạng. Đây là danh sách hỏi, không phải
 * tường lửa — lệnh không khớp danh sách vẫn chạy, và tiến trình con không bị chặn.
 */
export type PermissionNetwork = 'restricted' | 'enabled'

/** Bốn tầng luật, theo thứ tự đọc của harness (managed thắng tất cả). */
export type PermissionLayer = 'managed' | 'profile' | 'user' | 'project'

export type RuleKind = 'deny' | 'ask' | 'allow'

/** Giá trị năng lực: `true`/`false` hoặc `'allow'`/`'ask'` (bảng `MODE_CAPABILITIES`). */
export type CapabilityValue = boolean | 'allow' | 'ask'

export interface PermissionCapabilities {
  read: CapabilityValue
  write: CapabilityValue
  exec: CapabilityValue
  cua: CapabilityValue
}

/** Snapshot lease của H7 — `GET/POST /api/agent/desktop/lease`. */
export interface DesktopLease {
  holder: 'agent' | 'human'
  epoch: number
  generation: number
  hooksInstalled: boolean
  mutexHeld: boolean
  mutexName: string | null
  since: string | null
  reason: string
}

/**
 * Khối `execution` của `GET /api/agent/health` (và của snapshot quyền).
 * `policy: false` + `cuaEnabled: null` nghĩa là máy này không có động cơ quyền (docker).
 */
export interface ExecutionStatus {
  mode: 'docker' | 'host'
  modeDefault: string
  modes: string[]
  configured: string
  scope: string | null
  permissionMode: string | null
  network?: string | null
  policy: boolean
  cuaEnabled: boolean | null
  lease: DesktopLease | null
  hardlineHits: number
  workspace: string | null
}

/** Một tầng luật kèm tệp đang đọc. */
export interface PermissionLayerInfo {
  layer: PermissionLayer
  file: string
  present: boolean
  error: string
}

/** Một luật hợp nhất kèm tệp nguồn — UI hiện cột "tệp nguồn" từ đây. */
export interface PermissionRuleSource {
  rule: string
  layer: PermissionLayer
  file: string
}

/** `GET /api/agent/permissions` — snapshot đầy đủ. */
export interface PermissionSnapshot {
  mode: PermissionMode
  modeDefault: PermissionMode
  modes: PermissionMode[]
  capabilities: PermissionCapabilities
  scope: PermissionScope
  scopeDerived?: boolean
  cuaScope?: PermissionScope
  scopeDefault: PermissionScope
  scopes: PermissionScope[]
  network: PermissionNetwork
  networkDefault: PermissionNetwork
  networks: PermissionNetwork[]
  workspace: string | null
  layers: PermissionLayerInfo[]
  rules: Record<RuleKind, string[]>
  ruleSources: Record<RuleKind, PermissionRuleSource[]>
  hardlineCount: number
  hardlineHits: number
  denialBreakerLimit: number
  auditFile: string
  sessionRuleCount: number
  execution?: ExecutionStatus
}

/** `GET /api/agent/permissions/rules` — luật + tệp nguồn + bốn tầng. */
export interface PermissionRulesSnapshot {
  rules: Record<RuleKind, string[]>
  sources: Record<RuleKind, PermissionRuleSource[]>
  layers: PermissionLayerInfo[]
}

/** Một thẻ duyệt đang chờ — `GET /api/agent/permissions/pending`. */
export interface PendingApproval {
  id: string
  tool: string
  args: Record<string, unknown>
  reason: string
  sessionId: string | null
  createdAt: string
}

export interface PendingApprovalsSnapshot {
  pending: PendingApproval[]
}

/** Bốn câu trả lời của thẻ duyệt; `allow_always` mới ghi luật xuống đĩa. */
export type PermissionDecision = 'allow' | 'allow_session' | 'allow_always' | 'deny'

/** `POST /api/agent/permissions/decide`. */
export interface PermissionDecideResult {
  tool: string
  sessionId: string | null
  outcome: string
  reason: string
  rule: string
  layer: string
  decision?: PermissionDecision
  saved?: boolean
  saveCode?: string
  saveMessage?: string
  rules?: string[]
  breaker?: boolean
}

/** Ba hành động của băng điều khiển desktop. */
export type DesktopLeaseAction = 'claim' | 'release' | 'stop'
