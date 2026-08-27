/**
 * Cấu hình "khớp màn hình" cho một instance RFB.
 *
 * Tách khỏi `useVncScreen.ts` vì đây là logic thuần (chỉ đặt thuộc tính), test
 * được bằng vitest không cần DOM — cùng tinh thần với `attempt.ts`.
 *
 * CƠ CHẾ FIT — đọc kỹ trước khi sửa:
 *
 * Có hai cách làm cho desktop "vừa" khung ④, và chúng khác nhau về bản chất:
 *
 *   1. `scaleViewport` — PHÓNG/THU ẢNH. Framebuffer vẫn nguyên kích thước cũ,
 *      noVNC chỉ vẽ nó nhỏ/lớn hơn và GIỮ NGUYÊN TỈ LỆ. Panel nào có tỉ lệ khác
 *      framebuffer thì BẮT BUỘC sinh viền đen (letterbox), và chữ bị nội suy
 *      nên mờ. Đây là hành vi cũ và là đúng thứ người dùng phàn nàn.
 *
 *   2. `resizeSession` — ĐỔI PHÂN GIẢI THẬT. noVNC gửi `SetDesktopSize` lên
 *      server, server đổi framebuffer đúng bằng kích thước container, XFCE
 *      reflow lại panel/icon. Không viền, không nội suy, chữ nét nguyên bản.
 *      Đây là cách Vorflux/Devin làm, và là cách duy nhất đúng.
 *
 * Ta bật (2) làm cơ chế chính và GIỮ (1) làm lưới an toàn: khi server không
 * quảng bá `ExtendedDesktopSize` (image chưa rebuild sang Xvnc, hoặc người dùng
 * trỏ vào một VNC server khác), noVNC âm thầm bỏ qua yêu cầu resize
 * (`core/rfb.js`: `if (!this._supportsSetDesktopSize) return`) và rơi về scale
 * như cũ, thay vì cắt cụt màn hình. Khi resize thành công thì framebuffer đúng
 * bằng container nên hệ số scale ≈ 1.0, tức (1) không làm mờ gì cả.
 *
 * HIDPI — vì sao phải vá `_screenSize`:
 *
 * noVNC 1.7.0 xin phân giải theo **CSS pixel**: `_requestRemoteResize()` gọi
 * `_screenSize()`, mà hàm đó chỉ trả `getBoundingClientRect()`, KHÔNG nhân
 * `devicePixelRatio` (grep `devicePixelRatio` trong `core/` chỉ ra một chỗ duy
 * nhất là `dragThreshold`). Trên máy scale 125% (DPR 1.25 — mặc định của rất
 * nhiều laptop Windows) khung ④ rộng 984 px vật lý chỉ là 787 CSS px, nên
 * framebuffer xin về là 788, rồi trình duyệt kéo giãn 1.25× cho đầy khung:
 * icon và toàn bộ UI Chromium to bất thường và nhoè. Đúng triệu chứng người
 * dùng báo.
 *
 * Sửa bằng cách xin framebuffer theo **pixel vật lý** (CSS × DPR) rồi để
 * `scaleViewport` thu ảnh về lại đúng số CSS px của khung. Kết quả: 1 pixel
 * framebuffer = 1 pixel vật lý, sắc nét và đúng cỡ như Vorflux/Devin.
 *
 * Phải vá HAI hàm, không phải một:
 *   - `_screenSize()` → trả kích thước ĐÃ nhân DPR, để `_requestRemoteResize()`
 *     xin đúng số pixel vật lý.
 *   - `_updateScale()` → dùng kích thước CSS THÔ khi gọi `display.autoscale()`.
 *     Nếu để nó cũng thấy số đã nhân DPR thì autoscale tính ra hệ số 1.0, canvas
 *     giữ nguyên 1230 CSS px trong khung 984 CSS px và bị tràn ra ngoài.
 *
 * KHÔNG tự viết debounce/throttle cho việc này: noVNC đã tự rate-limit
 * `SetDesktopSize` (một request pending tại một thời điểm, tối đa 1 lần/100 ms)
 * và tự có `ResizeObserver` trên canvas của nó. Thêm debounce chỉ làm desktop
 * đuổi theo chậm hơn khi người dùng thả chuột.
 */
import type { RfbLike } from './attempt'

/**
 * Màu nền phía sau canvas noVNC.
 *
 * Trùng đúng màu nền của panel khung ④ (`SandboxScreenPanel.tsx`) VÀ màu nền
 * desktop XFCE trong box (`deploy/docker/assets/xfconf/xfce4-desktop.xml`).
 * Nhờ ba chỗ cùng một màu, nếu kích thước panel là số phân số (ví dụ 1173.33px)
 * và framebuffer bị làm tròn xuống thì khe hở dưới 1px đó không lộ ra.
 */
export const VNC_BACKGROUND = '#0f172a'

/**
 * Trần DPR khi xin framebuffer.
 *
 * Chốt 2 vì DPR 3–4 (điện thoại) sẽ đẩy framebuffer lên gấp 9–16 lần diện tích:
 * Xvnc phải cấp phát bộ nhớ theo đó và mỗi khung phải nén/truyền qua WebSocket.
 * Ở mức 2 đã đủ nét cho mọi màn hình retina thực tế.
 */
export const MAX_DEVICE_PIXEL_RATIO = 2

/** DPR đã kẹp trong [1, MAX_DEVICE_PIXEL_RATIO]. */
export function devicePixelScale(): number {
  const raw = typeof window === 'undefined' ? 1 : window.devicePixelRatio || 1
  if (!Number.isFinite(raw) || raw < 1) return 1
  return Math.min(raw, MAX_DEVICE_PIXEL_RATIO)
}

/** Kích thước ta muốn framebuffer có, tính theo pixel VẬT LÝ. */
export function physicalScreenSize(
  cssWidth: number,
  cssHeight: number,
  ratio: number,
): { w: number; h: number } {
  return {
    w: Math.max(1, Math.floor(cssWidth * ratio)),
    h: Math.max(1, Math.floor(cssHeight * ratio)),
  }
}

/**
 * Hình dạng các thành viên private của noVNC mà `applyScreenFit` phải chạm tới.
 *
 * Đây là API nội bộ nên có thể đổi khi nâng `@novnc/novnc`. Nếu sau khi nâng
 * bản mà icon to lại như cũ thì kiểm hai tên hàm này trước tiên; các `typeof`
 * guard bên dưới cố ý để việc vá THẤT BẠI ÊM (rơi về hành vi mặc định của
 * noVNC) thay vì làm khung ④ trắng xoá.
 */
interface NovncInternals {
  _screen?: HTMLElement
  _screenSize?: () => { w: number; h: number }
  _updateScale?: () => void
  _scaleViewport?: boolean
  _display?: { scale: number; autoscale: (w: number, h: number) => void }
  _fixScrollbars?: () => void
}

/** Xin framebuffer theo pixel vật lý thay vì CSS pixel (xem chú thích đầu file). */
function patchForHiDpi(rfb: RfbLike): void {
  const internals = rfb as unknown as NovncInternals
  const screen = internals._screen
  if (
    !screen ||
    typeof internals._screenSize !== 'function' ||
    typeof internals._updateScale !== 'function'
  ) {
    return
  }

  internals._screenSize = function screenSize() {
    const rect = screen.getBoundingClientRect()
    return physicalScreenSize(rect.width, rect.height, devicePixelScale())
  }

  internals._updateScale = function updateScale() {
    const display = internals._display
    if (!display) return
    if (!internals._scaleViewport) {
      display.scale = 1
    } else {
      const rect = screen.getBoundingClientRect()
      display.autoscale(rect.width, rect.height)
    }
    internals._fixScrollbars?.()
  }
}

/** Đặt toàn bộ thuộc tính hiển thị/điều khiển cho một instance RFB vừa dựng. */
export function applyScreenFit(rfb: RfbLike): void {
  // Vá TRƯỚC mọi setter: setter `resizeSession`/`scaleViewport` gọi ngay
  // `_requestRemoteResize()`/`_updateScale()`, nên nếu vá sau thì lượt xin đầu
  // tiên vẫn dùng CSS pixel.
  patchForHiDpi(rfb)

  // V2 (quyết định 12.3.1): người dùng click/gõ được, agent không dừng.
  rfb.viewOnly = false

  // Cơ chế fit chính — xin server đổi phân giải khớp container.
  rfb.resizeSession = true

  // Lưới an toàn khi server không hỗ trợ resize (xem chú thích đầu file).
  rfb.scaleViewport = true

  // PHẢI là false. Nếu bật, noVNC tắt scale và hiện scrollbar trong panel —
  // thanh cuộn trong khung máy ảo còn tệ hơn viền đen.
  rfb.clipViewport = false

  rfb.showDotCursor = true
  rfb.background = VNC_BACKGROUND

  // Vá LẠI sau setter: một số bản noVNC gán lại hàm trong setter.
  patchForHiDpi(rfb)
}
