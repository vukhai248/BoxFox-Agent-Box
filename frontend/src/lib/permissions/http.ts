/**
 * Adapter HTTP cho bề mặt quyền + điều khiển desktop ở host mode.
 *
 * Vì sao có lớp này thay vì gọi `agentApi` rải rác trong view: đường dẫn, phương thức
 * và body của tám route là hợp đồng chung với harness (`docs/plan/desktop-host-mode.md`
 * §4) — gom một chỗ để khi hợp đồng đổi thì chỉ sửa một tệp, và để view chỉ còn việc
 * hiển thị. Mọi lời gọi đi qua `agentApi` (đã tự thêm `X-BoxFox-Admin: 1` và giữ
 * nguyên `status`/`code` trong `ApiError`) — không dựng `fetch` riêng.
 *
 * Chế độ docker không có động cơ quyền: các route dưới đây trả 409 kèm mã
 * `PERMISSIONS_UNAVAILABLE` / `DESKTOP_CONTROL_UNAVAILABLE`. Lớp này KHÔNG nuốt lỗi —
 * view bắt `ApiError.code` để hiện thông báo đọc được thay vì vỡ.
 */
import { agentApi } from '../agentApi'
import type {
  DesktopLease,
  DesktopLeaseAction,
  ExecutionStatus,
  PendingApprovalsSnapshot,
  PermissionDecision,
  PermissionDecideResult,
  PermissionLayer,
  PermissionMode,
  PermissionRulesSnapshot,
  PermissionScope,
  PermissionSnapshot,
} from '../../types/machinePermissions'

/** `GET /api/agent/health` — chỉ đọc khối `execution` (rẻ, không chạm đĩa/mạng). */
export interface HarnessHealth {
  execution?: ExecutionStatus
}

export function getExecutionStatus(): Promise<HarnessHealth> {
  return agentApi<HarnessHealth>('/health')
}

export function getPermissionSnapshot(): Promise<PermissionSnapshot> {
  return agentApi<PermissionSnapshot>('/permissions')
}

/** `PUT /api/agent/permissions` — đổi `mode`/`scope`, ghi xuống tầng `user` (mặc định của UI). */
export function updatePermissions(patch: {
  mode?: PermissionMode
  scope?: PermissionScope
  layer?: PermissionLayer
}): Promise<PermissionSnapshot> {
  return agentApi<PermissionSnapshot>('/permissions', patch, 'PUT')
}

export function getPermissionRules(): Promise<PermissionRulesSnapshot> {
  return agentApi<PermissionRulesSnapshot>('/permissions/rules')
}

/** `DELETE /api/agent/permissions/rules` — thu hồi đúng một luật (kèm tầng của nó). */
export function revokePermissionRule(
  rule: string,
  layer?: PermissionLayer,
): Promise<{ ok: boolean; message: string }> {
  return agentApi<{ ok: boolean; message: string }>(
    '/permissions/rules',
    layer ? { rule, layer } : { rule },
    'DELETE',
  )
}

export function getPendingApprovals(): Promise<PendingApprovalsSnapshot> {
  return agentApi<PendingApprovalsSnapshot>('/permissions/pending')
}

/** `POST /api/agent/permissions/decide` — chốt một thẻ duyệt (actor luôn là người dùng). */
export function decidePermission(body: {
  tool: string
  args: Record<string, unknown>
  sessionId?: string | null
  decision: PermissionDecision
}): Promise<PermissionDecideResult> {
  return agentApi<PermissionDecideResult>('/permissions/decide', { ...body, actor: 'user' })
}

export function getDesktopLease(): Promise<DesktopLease> {
  return agentApi<DesktopLease>('/desktop/lease')
}

/** `POST /api/agent/desktop/lease` — chỉ nút của NGƯỜI DÙNG gọi được; agent không có đường tự gọi. */
export function actOnDesktopLease(action: DesktopLeaseAction): Promise<DesktopLease> {
  return agentApi<DesktopLease>('/desktop/lease', { action })
}
