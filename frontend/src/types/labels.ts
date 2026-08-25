/**
 * Kiểu dữ liệu nhãn — Provenance / Integrity / Confidentiality.
 *
 * ⚠️ File này (và mọi file trong `src/types/`) phải được SINH TỪ schema
 * backend Python (xem `scripts/gen-types.sh`, chưa viết) khi backend tồn tại.
 * Đang gõ tay ở bước này vì chưa có backend. Không gõ tay lại lần thứ hai —
 * khi có backend, thay bằng bản sinh tự động để tránh nhãn/giấy phép lệch
 * kiểu giữa hai phía (mục 9.3, 9.5.1 của bản kế hoạch).
 *
 * Giá trị enum dùng đúng chuỗi tiếng Việt không dấu trong bản kế hoạch
 * (mục 9.3) để khớp thẳng với backend, không cần map lại.
 */

/** TRỤC 2 — có quyền chỉ đạo hành động không. */
export type Integrity = 'duoc_nguoi_dung_cho_phep' | 'khong_tin_duoc'

export const INTEGRITY: Record<'USER_AUTHORIZED' | 'UNTRUSTED_DATA', Integrity> = {
  USER_AUTHORIZED: 'duoc_nguoi_dung_cho_phep',
  UNTRUSTED_DATA: 'khong_tin_duoc',
}

/** Thứ tự từ xấu nhất → tốt nhất, dùng để tính integrity_floor = min(...). */
export const INTEGRITY_ORDER: readonly Integrity[] = ['khong_tin_duoc', 'duoc_nguoi_dung_cho_phep']

/** TRỤC 3 — được gửi ra đâu. */
export type Confidentiality = 'cong_khai' | 'noi_bo' | 'bi_mat'

export const CONFIDENTIALITY: Record<'PUBLIC' | 'INTERNAL' | 'SECRET', Confidentiality> = {
  PUBLIC: 'cong_khai',
  INTERNAL: 'noi_bo',
  SECRET: 'bi_mat',
}

/** Thứ tự từ thấp nhất → cao nhất, dùng để tính confidentiality_ceiling = max(...). */
export const CONFIDENTIALITY_ORDER: readonly Confidentiality[] = ['cong_khai', 'noi_bo', 'bi_mat']

/** Nguồn dữ liệu nạp một artifact vào ngữ cảnh (mục 9.3). */
export type SourceKind =
  | 'user_input' // người dùng gõ lệnh
  | 'user_pasted' // người dùng dán dữ liệu để phân tích
  | 'agent_config' // cấu hình của chính Agent Box
  | 'workspace_file' // file trong workspace
  | 'web_content' // fetch_url
  | 'external_file' // file ngoài workspace
  | 'external_tool' // kết quả tool bên ngoài / MCP
  | 'screen_capture' // ảnh màn hình / computer use
  | 'command_output' // kết quả run_command
  | 'plan_artifact' // bản kế hoạch do agent viết, đã được chuẩn thuận

/** TRỤC 1 — đến từ đâu. Dùng cho: ghi sổ, giải thích cho người dùng (mục 9.3). */
export interface Provenance {
  label_id: string
  source_kind: SourceKind
  source_uri: string // "file:///repo/a.py", "https://x.com/y", "screen://tab-3"
  tool_name: string // tool nào nạp dữ liệu này vào
  content_hash: string // sha256 (rút gọn để hiển thị)
  derived_from: string[] // label_id cha → tạo thành đồ thị dẫn xuất
  created_at: string // ISO 8601
}
