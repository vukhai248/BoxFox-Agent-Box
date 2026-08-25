/**
 * Kiểu dữ liệu ở mức phiên: danh sách phiên ở thanh bên, ngân sách, sổ audit,
 * và trạng thái màn hình sandbox.
 *
 * ⚠️ `AuditRecord` và `Budget` phải sinh từ schema backend về sau — xem ghi
 * chú đầu file `labels.ts`. `SessionSummary` và `ScreenState` là kiểu giao
 * diện, backend chỉ cần cung cấp đủ trường.
 */
import type { Confidentiality, Integrity } from './labels'
import type { AgentMode, PermissionDecisionKind } from './agent'
import type { ToolName } from './lease'

/** Trạng thái một phiên hiện ở thanh bên trái. */
export type SessionStatus =
  | 'dang_chay'
  | 'cho_nguoi_dung'
  | 'xong'
  | 'da_tu_choi'
  | 'het_ngan_sach'

export interface SessionSummary {
  session_id: string
  /** Hai chữ cái đầu để vẽ avatar — không tải ảnh từ ngoài (mục 12.6). */
  initials: string
  title: string
  /** Thời gian tương đối đã dựng sẵn, ví dụ "3 phút". */
  relative_time: string
  status: SessionStatus
  /**
   * Chế độ của phiên đó. Hiện ngay ở danh sách phiên là thứ Devin/OpenHands
   * không có — trạng thái bảo mật mọi phiên nhìn thấy được từ một chỗ.
   */
  mode: AgentMode
  /** Số giấy phép CÒN HIỆU LỰC của phiên đó. */
  active_lease_count: number
}

export interface Budget {
  steps: number
  tokens: number
  costUsd: number
  capUsd: number
}

/** Một bản ghi trong sổ audit (mục 9.7). */
export interface AuditRecord {
  record_id: string
  task_epoch: number
  step_index: number
  tool_name: ToolName
  /** Tham số ĐÃ che phần bí mật — sổ audit không được chứa giá trị bí mật. */
  params_masked: string
  decision: PermissionDecisionKind | 'khong_can_hoi'
  lease_id: string | null
  /** Các label_id đã ảnh hưởng tới quyết định này — trả lời câu hỏi 3 mục 9.7. */
  label_ids: string[]
  /** Tên miền dữ liệu đã rời máy (null nếu không có) — trả lời câu hỏi 1 mục 9.7. */
  destination: string | null
  created_at: string
}

/** Ba câu truy vấn viết sẵn của mục 9.7. */
export type AuditQueryId = 'du_lieu_da_roi_may' | 'vi_sao_duoc_phep' | 'bat_nguon_tu_du_lieu_nao'

export interface ScreenLabel {
  label_id: string
  integrity: Integrity
  confidentiality: Confidentiality
}

export interface ScreenState {
  /** Cách agent "nhìn" màn hình (mục 8.4). */
  view_mode: 'a11y' | 'vision'
  /** true khi khung hình đến từ WebRTC thật; false = màn hình mô phỏng. */
  live: boolean
  /** Tiêu đề cửa sổ giả lập. */
  window_title: string
  /** Chỉ thị độc vẽ trên trang — kênh tấn công A3 (mục 14.5). */
  injection_banner: string
  /** Nội dung trang giả lập, văn bản thuần. */
  body_lines: string[]
  /** Cây khả năng truy cập khi view_mode = 'a11y'. */
  a11y_tree: string[]
  /**
   * Nhãn của khung hình gần nhất. LUÔN `khong_tin_duoc` bất kể WebRTC thật
   * hay mô phỏng — quy tắc M1 mục 8.5, không có ngoại lệ.
   */
  label: ScreenLabel
}
