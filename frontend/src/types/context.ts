/**
 * Ngữ cảnh là danh sách mảnh có nhãn (mục 10.2), không phải một chuỗi văn bản.
 *
 * ⚠️ Sinh từ schema backend về sau — xem ghi chú đầu file `labels.ts`.
 */
import type { Confidentiality, Integrity, Provenance } from './labels'

/** Một mảnh dữ liệu đã nạp vào ngữ cảnh, mang đủ ba trục nhãn. */
export interface ContextChunk {
  provenance: Provenance
  integrity: Integrity
  confidentiality: Confidentiality
  /** Nội dung nguyên văn — LUÔN render văn bản thuần ở giao diện (mục 12.6). */
  content: string
  /** Số bước ReAct mà mảnh này đã ở trong ngữ cảnh. */
  step_count: number
  /** Đã bị người dùng chuẩn thuận (endorsement) hay chưa — nâng integrity riêng mảnh này. */
  endorsed: boolean
}

/** Toàn bộ ngữ cảnh hiện tại của agent, cộng hai đại lượng suy ra (mục 9.3). */
export interface ContextState {
  chunks: ContextChunk[]
  /** integrity_floor = min(integrity của mọi artifact trong ngữ cảnh). */
  integrity_floor: Integrity
  /** confidentiality_ceiling = max(confidentiality của mọi artifact). */
  confidentiality_ceiling: Confidentiality
}
