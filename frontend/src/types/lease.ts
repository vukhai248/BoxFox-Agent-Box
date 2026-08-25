/**
 * Giấy phép có hạn (capability lease) — mục 9.5.
 *
 * ⚠️ Sinh từ schema backend về sau — xem ghi chú đầu file `labels.ts`.
 */
import type { Confidentiality, Integrity } from './labels'

/** Bốn loại cho phép, không được gộp (mục 9.5.2). */
export type LeaseKind =
  | 'mot_lan' // Cho phép một lần
  | 'chuan_thuan_artifact' // Chuẩn thuận artifact
  | 'giay_phep_thuong' // Giấy phép thường
  | 'giay_phep_ngu_canh_ban' // Giấy phép cho ngữ cảnh bẩn (bao gồm giấy phép theo phạm vi kế hoạch)

export type LeaseStatus =
  | 'con_hieu_luc'
  | 'het_han'
  | 'bi_thu_hoi'
  /** Mất hiệu lực vì có artifact bẩn mới ngoài phạm vi (quy tắc tái neo, mục 5.3.4.1). */
  | 'mat_hieu_luc_tai_neo'

export type ToolName =
  | 'list_dir'
  | 'read_file'
  | 'write_file'
  | 'edit_file'
  | 'run_command'
  | 'fetch_url'
  | 'ask_user'
  | 'computer_use'

/** Mức nguy hiểm của một tool — quyết định có cần xin quyền hay không. */
export type RiskLevel = 'SAFE' | 'WRITE' | 'EXEC' | 'EGRESS'

export interface Lease {
  lease_id: string
  kind: LeaseKind
  /** DO CONTROLLER TẠO. LLM không sinh, không sửa được (nguyên tắc N3). */
  task_epoch: number
  tool_name: ToolName // đúng một tool, không phải mẫu mơ hồ
  canonical_resources: string[] // đường dẫn ĐÃ giải quyết symlink + realpath
  destinations: string[] // tên miền được phép (cho EGRESS) — luôn [] cho giấy phép theo phạm vi kế hoạch
  operation: 'read' | 'write' | 'append' | 'exec'
  /** integrity_floor phải >= mức này mới dùng được giấy phép. */
  minimum_integrity: Integrity
  /** Trần bảo mật của các tài nguyên mà hành động này chạm — không phải trần của ngữ cảnh. */
  max_confidentiality: Confidentiality
  /**
   * NEO: nếu là giấy phép cho ngữ cảnh bẩn, đây là artifact bẩn người dùng
   * ĐÃ XEM lúc cấp. Chỉ hợp lệ khi label này còn trong ngữ cảnh VÀ không có
   * artifact bẩn MỚI xuất hiện từ ngoài phạm vi (mục 5.3.4.1).
   */
  granted_after_label_id: string | null
  expires_at: string // ISO 8601
  max_uses: number | null
  used_count: number
  revoked: boolean
  status: LeaseStatus
  /** Hiện lại cho người dùng khi xem lại. */
  granted_reason: string
}
