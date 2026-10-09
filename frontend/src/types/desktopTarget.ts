/**
 * Kiểu dữ liệu của "đích CUA theo phiên" — hợp đồng giữa panel "Màn hình máy"
 * và ba route `GET|PUT|DELETE /api/agent/machines/target` (mục 2.2 của
 * `v1-cua-target.md`).
 *
 * ⚠️ File này (và `lib/desktop/target.ts`) là chỗ DUY NHẤT biết tên trường của
 * hợp đồng route. Backend đổi tên ⇒ sửa hai file này, không rải chuỗi ra khắp
 * panel.
 *
 * ⚠️ Mọi chuỗi ở đây (`title`, `processName`, `windowClass`) là nội dung máy
 * thật ⇒ dữ liệu KHÔNG tin được: chỉ render qua `PlainText`/`textContent`, không
 * bao giờ `dangerouslySetInnerHTML` (quy tắc M1).
 */
import type { InspectBox } from './inspect'

/**
 * `windowId` là HWND trên Windows — backend trả số, nhưng hợp đồng chỉ hứa
 * "định danh cửa sổ": giữ cả hai kiểu và LUÔN so sánh qua `String(...)`, để
 * `12345` và `'12345'` không thành hai cửa sổ khác nhau trong giao diện.
 */
export type CuaWindowId = string | number

export type CuaTargetKind = 'window' | 'machine'

/** Ai vừa đặt đích: người dùng bấm trong panel, hay agent tự xin cửa sổ khác. */
export type CuaTargetSetBy = 'user' | 'agent'

/** Đích đang áp cho phiên. `kind: 'machine'` không mang trường nào khác. */
export interface CuaWindowTarget {
  kind: 'window'
  windowId: CuaWindowId
  pid?: number
  title?: string
  processName?: string
  windowClass?: string
  aumid?: string | null
}

export interface CuaMachineTarget {
  kind: 'machine'
}

export type CuaTarget = CuaWindowTarget | CuaMachineTarget

/**
 * Cửa sổ agent vừa thao tác — nguồn duy nhất để vẽ viền xanh.
 *
 * `rect` ở **toạ độ màn hình vật lý** (cùng hệ với `captureOrigin` của ảnh
 * chụp), không phải toạ độ ảnh: quy đổi nằm ở `lib/desktop/geometry.ts`.
 */
export interface CuaActiveWindow {
  windowId: CuaWindowId
  pid?: number
  title?: string
  processName?: string
  rect: InspectBox
}

/**
 * Nhịp hoạt động của lớp phủ CUA — `cua_overlay.py:snapshot()`, backend đưa
 * nguyên khối vào `activity`. Panel hiện chưa vẽ từ đây (nó dùng `activeWindow`
 * + lease), nhưng giữ đúng hình dạng để lần sau không phải đoán.
 */
export interface CuaTargetActivity {
  enabled?: boolean
  /** `true` khi viền đang thật sự hiện trên desktop. */
  visible?: boolean
  paused?: boolean | null
  windowId?: CuaWindowId | null
  title?: string | null
  bounds?: InspectBox | null
  reason?: string | null
  idleSeconds?: number | null
}

/** Body của `PUT /api/agent/machines/target`. */
export interface CuaTargetRequest {
  sessionId: string
  kind: CuaTargetKind
  windowId?: CuaWindowId
  pid?: number
  /** Luôn `true`: panel chỉ gửi sau một cú bấm có chủ đích của người dùng. */
  consent: true
  /** Chống ghi đè: revision panel đang thấy; lệch ⇒ backend trả 409. */
  expectedRevision?: number
}

/**
 * Hình dạng chung của cả ba route target (GET/PUT/DELETE) — `machine_router.py:_target_state`.
 *
 * `requestedBy` là "ai vừa đổi đích" (`set_by` trong sổ đích); panel hiện dòng
 * "Agent tự chuyển sang cửa sổ này" khi giá trị là `'agent'`.
 */
export interface CuaTargetState {
  sessionId: string
  target: CuaTarget | null
  requestedBy?: CuaTargetSetBy | null
  /** Đích đã KIỂM LẠI còn sống (hwnd có thể chết hoặc bị tái dùng) — `null` khi đã mất. */
  effective?: CuaTarget | null
  /** Vì sao `effective` là `null` (ví dụ `window_gone`). */
  effectiveReason?: string | null
  /** Mã phiên nguồn khi đích được thừa hưởng từ phiên khác. */
  inheritedFrom?: string | null
  activeWindow?: CuaActiveWindow | null
  /**
   * `'workspace' | 'machine'`, hoặc chuỗi RỖNG khi máy không có động cơ quyền.
   * Ưu tiên đọc `machineAllowed` — backend đã tính sẵn cùng luật.
   */
  scope?: string | null
  /** `scope === 'machine'` (backend tính). Vắng ⇒ panel tự suy từ `scope`. */
  machineAllowed?: boolean
  cuaEnabled?: boolean | null
  /** Tăng dần mỗi lần đổi đích — panel dùng để biết "agent vừa chuyển". */
  revision: number
  /** ISO-8601 UTC của lần đổi đích gần nhất. */
  updatedAt?: string | null
  activity?: CuaTargetActivity | null
}

/** Một cửa sổ đang mở — `GET /api/agent/machines/screen` (route đã có). */
export interface HostWindowEntry {
  windowId: CuaWindowId
  zOrder?: number
  title: string
  windowClass?: string
  pid?: number
  processName?: string
  position?: { x: number; y: number }
  size?: { width: number; height: number }
  dpi?: number
}

/**
 * Ảnh chụp vùng đích — `POST /api/agent/machines/screen`.
 *
 * `captureOrigin`/`captureSize` là toạ độ **vật lý** của vùng chụp trong màn
 * hình ảo, gốc có thể ÂM (màn hình phụ nằm bên trái màn hình chính). Ảnh là một
 * lát cắt tại `captureOrigin`, nên mọi toạ độ framebuffer phải trừ đi gốc này
 * trước khi vẽ lên ảnh (`lib/desktop/geometry.ts`).
 */
export interface HostSnapshot {
  /** PNG base64 KHÔNG kèm tiền tố `data:`. */
  image: string
  mime: string
  width: number
  height: number
  hash: string
  /** Có ở ảnh cửa sổ; ảnh "cả máy" không kèm mã này. */
  snapshotId?: string
  untrusted?: boolean
  captureOrigin: { x: number; y: number }
  captureSize: { width: number; height: number }
}
