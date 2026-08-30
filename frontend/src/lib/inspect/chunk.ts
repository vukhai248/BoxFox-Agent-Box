/**
 * Dựng `ContextChunk` từ một phần tử đã thanh tra — điểm neo của quyết định D3
 * (`v1-element-selector.md` §4.2): `Add to Chat` gửi DỮ LIỆU CÓ CẤU TRÚC, đi
 * qua đúng bộ máy nhãn `ContextChunk` + `label_added` + `computeIntegrityFloor`
 * mà repo đã có cho mọi nội dung không tin được khác (ảnh màn hình, fetch_url…).
 */
import type { Confidentiality } from '../../types/labels'
import type { ContextChunk } from '../../types/context'
import type { InspectedElementContext } from '../../types/inspect'
import { formatInspectedElementForAgent } from './format'

/**
 * `confidentiality` của mọi chunk phần tử — quyết định Q4 (§6):
 * `'cong_khai'` nói dối theo hướng nguy hiểm (màn hình box có thể đang mở
 * trang nội bộ); `'bi_mat'` đẩy `confidentiality_ceiling` lên đỉnh và chặn
 * mọi hành động gửi ra ngoài suốt phần còn lại của phiên. `'noi_bo'` là điểm
 * giữa an toàn. Đặt hằng có tên để đổi một chỗ — CŨNG dùng làm giá trị dự
 * phòng khi `parseInspectElementResult` (`parse.ts`) gặp `label.confidentiality`
 * không thuộc `CONFIDENTIALITY_ORDER` (§5.3, cột C2).
 */
export const INSPECTED_ELEMENT_CONFIDENTIALITY: Confidentiality = 'noi_bo'

/** Tên tool dự phòng khi `label.tool_name` box trả về rỗng. */
export const INSPECTED_ELEMENT_TOOL = 'inspect_element'

/** `windowId` của cửa sổ chứa phần tử — cùng một trường cho cả hai nhánh. */
function resultWindowId(ctx: InspectedElementContext): string {
  return ctx.result.type === 'dom' ? ctx.result.target.windowId : ctx.result.windowId
}

/**
 * Dựng `source_uri` bằng ĐÚNG quy tắc box dùng để tự sinh `label.source_uri`
 * (§5.4): `screen://element/<windowId>`, KHÔNG bao giờ nhúng `selector` (chuỗi
 * do trang kiểm soát) và KHÔNG lấy `result.url` (§5.6 — bản này ghi đè
 * `frontend-detail.md`). Dựng lại ở đây, không đọc thẳng `label.source_uri`,
 * để hai phía luôn đồng nhất bất kể `MockInspectRepository` trả gì.
 */
function buildSourceUri(ctx: InspectedElementContext): string {
  return `screen://element/${resultWindowId(ctx)}`
}

/**
 * Dựng `ContextChunk` cho một phần tử đã đính kèm.
 *
 * @param now - nguồn giờ, tiêm được để test tất định (mặc định `Date.now`
 * qua `new Date().toISOString()`).
 */
export function buildInspectedElementChunk(
  ctx: InspectedElementContext,
  now: () => string = () => new Date().toISOString(),
): ContextChunk {
  const { label } = ctx.result

  return {
    provenance: {
      label_id: `lbl-inspect-${ctx.id}`,
      source_kind: 'screen_capture',
      source_uri: buildSourceUri(ctx),
      tool_name: INSPECTED_ELEMENT_TOOL,
      content_hash: label.content_hash ?? '',
      derived_from: [],
      created_at: now(),
    },
    // Ghi thẳng, không đọc `label.integrity` — quy tắc M1 (mục 8.5), đúng cách
    // panel này đã áp cho khung hình (`SandboxScreenPanel.tsx:96-98,115-116`).
    integrity: 'khong_tin_duoc',
    confidentiality: INSPECTED_ELEMENT_CONFIDENTIALITY,
    content: formatInspectedElementForAgent(ctx),
    step_count: 0,
    endorsed: false,
  }
}
