/**
 * Chế độ agent, thẻ xin quyền, và bản kế hoạch (mục 5.3, 12.5, 12.5.1).
 *
 * ⚠️ Sinh từ schema backend về sau — xem ghi chú đầu file `labels.ts`.
 */
import type { RiskLevel, ToolName } from './lease'

export type AgentMode = 'PLAN' | 'ACT'

export type PermissionRequestStatus = 'dang_cho' | 'da_quyet_dinh' | 'qua_han'

/** Bốn loại quyết định người dùng có thể bấm — khớp mục 9.5.2, không có loại thứ năm. */
export type PermissionDecisionKind =
  | 'cho_phep_mot_lan'
  | 'cap_giay_phep'
  | 'chuan_thuan_artifact'
  | 'tu_choi'

/** Một dòng trong diff tự viết — không dùng thư viện diff (yêu cầu đề bài). */
export interface DiffLine {
  kind: 'them' | 'bot' | 'giu_nguyen'
  text: string
}

/** Thẻ xin quyền (mục 12.5) — phải hiện đủ năm thứ theo đúng thứ tự. */
export interface PermissionRequest {
  request_id: string
  task_epoch: number
  tool_name: ToolName
  risk_level: RiskLevel
  /** 1. Việc gì — mô tả bằng tiếng người, ví dụ "ghi file src/auth.py". */
  action_summary_key: string
  /** Tham số nguyên văn của tool call. */
  params: Record<string, string>
  /** 2a. Nội dung nguyên văn — dùng cho run_command / fetch_url. */
  raw_content?: string
  /** 2b. Diff — dùng cho write_file / edit_file. */
  diff?: DiffLine[]
  /** 3. Vì sao phải hỏi — câu giải thích bằng tiếng người, đã dựng sẵn. */
  reason: string
  /** 4. Nguồn gốc bấm được — label_id của các artifact đã ảnh hưởng. */
  derived_from: string[]
  /** true nếu integrity_floor = khong_tin_duoc lúc yêu cầu này sinh ra (quyết định số nút, mục 12.5). */
  context_dirty: boolean
  created_at: string
  expires_at: string
  status: PermissionRequestStatus
  decision?: PermissionDecisionKind
  /** Nếu quyết định là chuẩn thuận artifact / hỏi vì nguồn cụ thể, artifact đó. */
  dirty_source_label_id?: string
}

/** Trạng thái thực thi của một bước kế hoạch — hiện ở tab Kế hoạch. */
export type PlanStepStatus = 'cho' | 'dang_lam' | 'xong' | 'bo_qua' | 'chech_ke_hoach'

export interface PlanStep {
  id: string
  description: string
  resources: string[]
  risk_level: RiskLevel
  status: PlanStepStatus
  /** Bước này chạm tài nguyên ngoài phạm vi việc, hoặc đòi EGRESS/tải mạng (mục 12.5.1 #4). */
  out_of_scope: boolean
}

/** Bản kế hoạch do agent viết ra ở Plan mode (mục 5.3.4). */
export interface PlanArtifact {
  label_id: string
  /** Toàn văn kế hoạch — hiện đủ, không rút gọn (mục 12.5.1 #2). */
  full_text: string
  steps: PlanStep[]
  /** Nguồn đã ảnh hưởng tới kế hoạch, lấy từ derived_from (mục 12.5.1 #3). */
  derived_from: string[]
  content_hash: string
  created_at: string
}

/** Dữ liệu hiện thẻ chuyển chế độ Plan → Act (mục 12.5.1). */
export interface ModeSwitchProposal {
  plan: PlanArtifact
  /**
   * Nếu Controller từ chối cấp giấy phép gộp (chốt 2, mục 5.3.4.2), gộp
   * canonical_resources rỗng và cờ này = true — dòng phạm vi đổi thành cảnh báo.
   */
  bundled_lease_rejected: boolean
  /** Giấy phép theo phạm vi kế hoạch sẽ được cấp nếu người dùng bấm chuyển (null nếu bị từ chối). */
  proposed_lease: {
    canonical_resources: string[]
    duration_minutes: number
  } | null
}
