/**
 * Kiểu dữ liệu của Element Selector / DOM Inspector (khung ④).
 *
 * ⚠️ File này (và mọi file trong `src/types/`) phải được SINH TỪ schema backend
 * Python (xem `scripts/gen-types.sh`, chưa viết) khi backend tồn tại. Đang gõ
 * tay ở bước này vì chưa có backend. Không gõ tay lại lần thứ hai — khi có
 * backend, thay bằng bản sinh tự động để tránh lệch kiểu giữa hai phía
 * (mục 9.3, 9.5.1 của bản kế hoạch).
 *
 * ⚠️ NHÃN: mọi chuỗi trong `DomInspectResult` / `DesktopInspectResult` là nội
 * dung màn hình máy ⇒ integrity LUÔN là `khong_tin_duoc` (quy tắc M1, mục 8.5),
 * kể cả khi box trả về giá trị khác. `parseInspectElementResult()` ghi đè cứng
 * (xem `lib/inspect/parse.ts`). Giao diện chỉ được render các chuỗi này qua
 * `PlainText` (mục 12.6) — không bao giờ `dangerouslySetInnerHTML`.
 *
 * ⚠️ PHASE 1 KHÔNG khai báo `InspectSource` — vị trí trong mã nguồn
 * (`{file, line, column}`) hoãn sang Phase 2 vì `data-boxfox-src` là thuộc
 * tính do MỘT TRANG WEB BẤT KỲ tự đặt, và mở file theo đường dẫn đó mà chưa
 * validate là một đường đi trọn vẹn từ dữ liệu web không tin được tới thao
 * tác mở file nội bộ (xem `v1-element-selector.md` §10.3). Không viết nhánh
 * `if (result.source)` nào ở Phase 1.
 */
import type { Confidentiality, Integrity, SourceKind } from './labels'

/** Hình chữ nhật dùng cho cả toạ độ CSS của trang và toạ độ framebuffer/X11. */
export interface InspectBox {
  x: number
  y: number
  width: number
  height: number
}

/**
 * Nhãn do box cấp cho một lần thanh tra (§5.4).
 *
 * Lồng trong một khối `label` — KHÔNG đặt các trục nhãn ở cấp cao nhất của
 * response — để có một chỗ duy nhất đọc/hash/kiểm "không rò rỉ".
 */
export interface InspectLabel {
  integrity: Integrity
  /** Box CÓ trả trường này (khác `types/labels.ts` `Provenance` không có). */
  confidentiality: Confidentiality
  source_kind: SourceKind
  /** `screen://element/<windowId>` — KHÔNG BAO GIỜ nhúng selector (§5.4). */
  source_uri: string
  tool_name: string
  content_hash: string
}

/** Cửa sổ / CDP target mà phần tử thuộc về — CHỈ đúng 3 khoá công khai (§10.1). */
export interface InspectTarget {
  windowId: string
  windowTitle: string
  targetId: string
}

/** Điểm bấm đã đổi sang toạ độ framebuffer/X11 — chính là body của request. */
export interface InspectElementRequest {
  x: number
  y: number
}

/**
 * Mã máy giải thích vì sao thanh tra suy biến sang nhánh `desktop` (§5.2).
 * Mười một giá trị — bảng này THẮNG mọi bộ tên cũ ở các tài liệu đào sâu.
 */
export type InspectDesktopReason =
  | 'not_chromium'
  | 'outside_viewport'
  | 'frame_extents_unknown'
  | 'devtools_docked'
  | 'viewport_origin_unknown'
  | 'no_cdp_target'
  | 'ambiguous_target'
  | 'cdp_unreachable'
  | 'cdp_timeout'
  | 'no_node_at_point'
  | 'extract_failed'

/** Ghi chú best-effort đi kèm một `DomInspectResult` (§5.3, cột C3). */
export type InspectNote = 'shadow_dom' | 'iframe_boundary' | 'selector_not_unique' | 'shadow_closed' | 'truncated_ancestors'

/** Bấm vào trong viewport trình duyệt ⇒ box hỏi Chrome qua CDP. */
export interface DomInspectResult {
  type: 'dom'
  selector: string
  url: string
  title: string
  tagName: string
  text: string
  attributes: Record<string, string>
  html: string
  /** `true` ⇒ box đã cắt ngắn `html`/`text`/`attributes`; giao diện phải nói rõ. */
  truncated: boolean
  /** Hộp bao trong toạ độ CSS của trang — chưa dùng ở Phase 1, giữ cho CUA (Phase 3). */
  cssBox: InspectBox
  /** Hộp bao trong toạ độ framebuffer/X11 — dùng vẽ khung sáng trên lớp phủ. */
  screenBox: InspectBox
  /** Mã máy best-effort, ví dụ `['shadow_dom']` — có thể rỗng. */
  notes?: InspectNote[]
  shadowHostSelector?: string | null
  target: InspectTarget
  label: InspectLabel
}

/** Bấm ra ngoài viewport ⇒ box hỏi X11 (`xwininfo` / `xprop`), suy biến MỀM. */
export interface DesktopInspectResult {
  type: 'desktop'
  /** Mã máy — §5.2. Vắng khi `reason` không xác định được (hiếm, xem parse.ts). */
  reason?: InspectDesktopReason
  /** Câu tiếng Việt do box dựng theo `reason` — dịch theo `reason` trước, chỉ dùng chuỗi này khi `reason` lạ. */
  message?: string
  appName?: string
  windowClass?: string
  windowTitle: string
  windowId: string
  position: { x: number; y: number }
  size: { width: number; height: number }
  pid?: number
  label: InspectLabel
}

export type InspectElementResult = DomInspectResult | DesktopInspectResult

/**
 * Một phần tử người dùng đã đính kèm vào khung soạn tin (chip).
 *
 * `id` là id CỤC BỘ của giao diện để render danh sách và xoá — không phải id
 * do backend cấp. Xem quyết định D3 (`v1-element-selector.md` §4.2): dữ liệu
 * này đi kèm `ClientCommand` dưới dạng DỮ LIỆU CÓ CẤU TRÚC ở trường `elements`,
 * tuyệt đối không nối vào `text` của người dùng.
 */
export interface InspectedElementContext {
  id: string
  /** Điểm framebuffer đã bấm — giữ lại để ghi sổ và cho CUA về sau (Phase 3). */
  point: InspectElementRequest
  result: InspectElementResult
}
