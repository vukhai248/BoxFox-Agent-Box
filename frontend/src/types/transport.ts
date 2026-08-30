/**
 * Giao thức giữa giao diện và backend (mục 12.4).
 *
 * Đây là HỢP ĐỒNG duy nhất giữa hai phía. Store chỉ biết hai kiểu này —
 * nó không biết dữ liệu đến từ kịch bản mock, từ WebSocket thật, hay từ
 * WebRTC. Xem `src/lib/transport/index.ts`.
 *
 * ⚠️ Sinh từ schema backend về sau — xem ghi chú đầu file `labels.ts`.
 */
import type { Confidentiality, Integrity } from './labels'
import type { ContextChunk } from './context'
import type { InspectedElementContext } from './inspect'
import type { Lease, LeaseStatus, ToolName } from './lease'
import type {
  AgentMode,
  ModeSwitchProposal,
  PermissionDecisionKind,
  PermissionRequest,
  PermissionRequestStatus,
  PlanArtifact,
} from './agent'
import type { FileNode, TerminalLine, ReferencedFile } from './ui'
import type { AuditRecord, Budget, ScreenState } from './session'
import type { PermissionButtonId } from '../lib/permissions'

/** Ba trục nhãn gọn lại cho một mảnh nội dung hiện ở giao diện. */
export interface LabelTriple {
  label_id: string
  integrity: Integrity
  confidentiality: Confidentiality
}

/** Mức ngắt của người dùng (mục 5.8.2). */
export type InterruptLevel = 'tam_dung' | 'huy_buoc_hien_tai' | 'dung_han_va_thu_hoi'

/** Sự kiện backend → giao diện. */
export type ServerEvent =
  | { type: 'step_started'; step_id: string; task_epoch: number }
  | { type: 'agent_thought'; step_id: string; thought: string }
  | { type: 'tool_called'; step_id: string; tool_name: ToolName; params: Record<string, string> }
  | {
      type: 'tool_result'
      step_id: string
      result_preview: string
      truncated_lines?: number
      label: LabelTriple
    }
  /**
   * Tin nhắn trả lời của Agent, có thể kèm danh sách file liên quan (`files`).
   * Backend thật khi phân tích hoặc sửa code xong chỉ cần gửi mảng `files: [{ path, name, size_bytes, content }]`.
   */
  | {
      type: 'agent_message'
      message_id: string
      text: string
      files?: ReferencedFile[]
      label: LabelTriple
    }
  /**
   * Sự kiện ảnh chụp màn hình sandbox/trình duyệt của Agent.
   * Backend thật gửi ảnh base64 hoặc URL trực tiếp kèm `source_url` trang đang duyệt.
   */
  | {
      type: 'screenshot'
      message_id: string
      image_url: string
      caption?: string
      source_url?: string
      width?: number
      height?: number
      label?: LabelTriple
    }
  | {
      type: 'screen_recording'
      message_id: string
      video_url: string
      poster_url?: string
      caption?: string
      source_url?: string
      duration_seconds?: number
      width?: number
      height?: number
      label?: LabelTriple
    }
  | { type: 'system_note'; message_id: string; text: string }
  | { type: 'user_message_echo'; message_id: string; text: string }
  | { type: 'permission_requested'; request: PermissionRequest }
  | {
      type: 'permission_resolved'
      request_id: string
      decision: PermissionDecisionKind
      status: PermissionRequestStatus
    }
  | { type: 'mode_switch_proposed'; proposal: ModeSwitchProposal }
  | { type: 'mode_switched'; mode: AgentMode; task_epoch: number }
  | { type: 'label_added'; chunk: ContextChunk }
  | { type: 'lease_granted'; lease: Lease }
  | { type: 'lease_invalidated'; lease_id: string; status: LeaseStatus; reason: string }
  | { type: 'budget_updated'; budget: Budget }
  | { type: 'terminal_line'; line: TerminalLine }
  | { type: 'files_updated'; files: FileNode[] }
  | { type: 'screen_frame'; screen: ScreenState }
  | { type: 'audit_appended'; record: AuditRecord }
  | { type: 'plan_updated'; workspace: PlanArtifact | null; endorsed: PlanArtifact | null }
  | { type: 'task_finished'; reason: string }
  /** Tiến độ kịch bản mock — bản chạy thật không phát sự kiện này. */
  | { type: 'scenario_progress'; index: number; total: number }
  /** Ba sự kiện signaling WebRTC, đi chung một WebSocket với mọi sự kiện khác. */
  | { type: 'screen_offer'; sdp: string }
  | { type: 'screen_answer'; sdp: string }
  | { type: 'screen_ice'; candidate: string }

/** Lệnh giao diện → backend. */
export type ClientCommand =
  | {
      type: 'user_message'
      text: string
      /**
       * Phần tử người dùng đính kèm từ khung ④ (Element Selector, quyết định D3
       * — `v1-element-selector.md` §4.2).
       *
       * ⚠️ Đây là nội dung màn hình máy ⇒ KHÔNG TIN ĐƯỢC. Backend PHẢI nạp mỗi
       * phần tử thành một `ContextChunk` riêng với `integrity: 'khong_tin_duoc'`
       * và `source_kind: 'screen_capture'`, rồi phát `label_added`. TUYỆT ĐỐI
       * KHÔNG nối nội dung này vào `text`: `text` là kênh chỉ thị của người
       * dùng, còn đây là dữ liệu (mục 8.5, kênh tấn công A3 mục 14.5).
       *
       * ⚠️ Ở chế độ `live` (`VITE_TRANSPORT=live`), trường này CHƯA có nơi tiêu
       * thụ — `backend/` chưa có runtime nào phát `label_added` cho nó. Phase 1
       * chỉ giao hợp đồng truyền tải; demo đầy đủ chỉ có ở `VITE_TRANSPORT=mock`
       * (xem `lib/transport/mock.ts`).
       */
      elements?: InspectedElementContext[]
    }
  /**
   * Đúng MỘT nút trong bốn nút của mục 9.5.2 — không có giá trị nào diễn đạt
   * "luôn cho phép", và không được thêm.
   */
  | { type: 'permission_response'; request_id: string; button: PermissionButtonId }
  /** Người dùng bấm công tắc sang Act → yêu cầu backend dựng thẻ chuyển chế độ. */
  | { type: 'mode_switch_request' }
  /** Người dùng đã đọc thẻ và quyết định. */
  | { type: 'mode_switch_confirm'; accepted: boolean }
  | { type: 'interrupt'; level: InterruptLevel }
  /** Người dùng bấm "Thu hồi" ở bảng Nhãn & Giấy phép. */
  | { type: 'revoke_lease'; lease_id: string }
  /** Hai lệnh chỉ dành cho MockTransport. */
  | { type: 'scenario_step' }
  | { type: 'scenario_reset' }
  | { type: 'scenario_set_reject_bundle'; value: boolean }
  | { type: 'screen_offer'; sdp: string }
  | { type: 'screen_answer'; sdp: string }
  | { type: 'screen_ice'; candidate: string }
