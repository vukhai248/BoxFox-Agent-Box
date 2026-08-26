/**
 * Bài chống hồi quy cho cơ chế khớp màn hình.
 *
 * Bài quan trọng nhất ở đây là `resizeSession === true`. Nếu ai đó đổi nó về
 * `false`, desktop trong khung ④ quay lại kẹt ở phân giải khởi động và sinh viền
 * đen mỗi khi tỉ lệ panel khác tỉ lệ framebuffer — đúng lỗi mà file `fit.ts`
 * được tạo ra để sửa. Lỗi đó chỉ nhìn thấy bằng mắt trên UI thật, nên phải có
 * một bài test giữ nó lại.
 */
import { afterEach, describe, expect, it } from 'vitest'
import {
  applyScreenFit,
  devicePixelScale,
  MAX_DEVICE_PIXEL_RATIO,
  physicalScreenSize,
  VNC_BACKGROUND,
} from './fit'
import type { RfbLike } from './attempt'

/** Giá trị khởi tạo cố tình ĐẶT NGƯỢC hết, để mọi assertion đều chứng minh
 *  `applyScreenFit` thực sự ghi lên, không phải trùng giá trị mặc định. */
function makeRfb(): RfbLike {
  return {
    viewOnly: true,
    scaleViewport: false,
    clipViewport: true,
    resizeSession: false,
    showDotCursor: false,
    background: '',
    disconnect() {},
    focus() {},
    blur() {},
    addEventListener() {},
    removeEventListener() {},
  }
}

describe('applyScreenFit', () => {
  it('bật resizeSession — cơ chế fit là ĐỔI PHÂN GIẢI THẬT, không phải scale ảnh', () => {
    const rfb = makeRfb()
    applyScreenFit(rfb)
    expect(rfb.resizeSession).toBe(true)
  })

  it('giữ scaleViewport làm lưới an toàn khi server không hỗ trợ SetDesktopSize', () => {
    const rfb = makeRfb()
    applyScreenFit(rfb)
    expect(rfb.scaleViewport).toBe(true)
  })

  it('clipViewport phải false: bật lên là noVNC tắt scale và hiện scrollbar trong panel', () => {
    const rfb = makeRfb()
    applyScreenFit(rfb)
    expect(rfb.clipViewport).toBe(false)
  })

  it('không viewOnly — người dùng phải click/gõ được vào máy (quyết định 12.3.1)', () => {
    const rfb = makeRfb()
    applyScreenFit(rfb)
    expect(rfb.viewOnly).toBe(false)
  })

  it('nền trùng màu panel/desktop nên khe hở do làm tròn không lộ ra', () => {
    const rfb = makeRfb()
    applyScreenFit(rfb)
    expect(rfb.background).toBe(VNC_BACKGROUND)
    expect(VNC_BACKGROUND).toBe('#0f172a')
  })

  it('hiện con trỏ dạng dấu chấm khi máy không gửi cursor riêng', () => {
    const rfb = makeRfb()
    applyScreenFit(rfb)
    expect(rfb.showDotCursor).toBe(true)
  })
})

describe('devicePixelScale', () => {
  const original = window.devicePixelRatio

  function setDpr(value: number): void {
    Object.defineProperty(window, 'devicePixelRatio', {
      value,
      configurable: true,
      writable: true,
    })
  }

  afterEach(() => setDpr(original))

  it('trả đúng DPR khi nằm trong khoảng dùng được (125% — mặc định nhiều laptop)', () => {
    setDpr(1.25)
    expect(devicePixelScale()).toBe(1.25)
  })

  it('kẹp trần ở MAX_DEVICE_PIXEL_RATIO — DPR 3–4 sẽ phồng framebuffer 9–16 lần', () => {
    setDpr(4)
    expect(devicePixelScale()).toBe(MAX_DEVICE_PIXEL_RATIO)
  })

  it('không bao giờ thu nhỏ: DPR < 1 (zoom out) vẫn xin framebuffer 1:1', () => {
    setDpr(0.5)
    expect(devicePixelScale()).toBe(1)
  })

  it('giá trị vô nghĩa (0 / NaN) rơi về 1 chứ không sinh framebuffer rỗng', () => {
    setDpr(0)
    expect(devicePixelScale()).toBe(1)
    setDpr(Number.NaN)
    expect(devicePixelScale()).toBe(1)
  })
})

describe('physicalScreenSize', () => {
  it('nhân DPR rồi làm tròn xuống — đúng những gì SetDesktopSize gửi đi', () => {
    // 787.2 CSS px × 1.25 = 984 px vật lý: chính con số trong ảnh người dùng gửi.
    expect(physicalScreenSize(787.2, 462.4, 1.25)).toEqual({ w: 984, h: 578 })
  })

  it('DPR 1 giữ nguyên kích thước CSS (máy không HiDPI không bị ảnh hưởng)', () => {
    expect(physicalScreenSize(805, 842, 1)).toEqual({ w: 805, h: 842 })
  })

  it('không bao giờ trả 0: panel bị thu về 0px vẫn phải là phân giải hợp lệ', () => {
    expect(physicalScreenSize(0, 0, 1.25)).toEqual({ w: 1, h: 1 })
  })
})

describe('applyScreenFit — vá HiDPI trên instance noVNC', () => {
  /** Bản giả tối thiểu của phần nội bộ noVNC mà bản vá chạm tới. */
  function makeRfbWithInternals(cssWidth: number, cssHeight: number) {
    const autoscaleCalls: Array<{ w: number; h: number }> = []
    const rfb = {
      ...makeRfb(),
      _screen: {
        getBoundingClientRect: () => ({ width: cssWidth, height: cssHeight }),
      },
      _screenSize() {
        const r = this._screen.getBoundingClientRect()
        return { w: r.width, h: r.height }
      },
      _updateScale() {},
      // noVNC thật đặt cờ này trong setter `scaleViewport`; bản giả không có
      // setter nên phải đặt tay, nếu không bản vá đi nhánh scale = 1.
      _scaleViewport: true,
      _display: {
        scale: 1,
        autoscale(w: number, h: number) {
          autoscaleCalls.push({ w, h })
        },
      },
    }
    return { rfb, autoscaleCalls }
  }

  it('_screenSize trả pixel VẬT LÝ để server cấp framebuffer đủ nét', () => {
    Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
    const { rfb } = makeRfbWithInternals(600, 400)
    applyScreenFit(rfb as unknown as RfbLike)
    expect(rfb._screenSize()).toEqual({ w: 1200, h: 800 })
  })

  it('_updateScale vẫn dùng CSS px, nếu không canvas tràn ra ngoài khung ④', () => {
    Object.defineProperty(window, 'devicePixelRatio', { value: 2, configurable: true })
    const { rfb, autoscaleCalls } = makeRfbWithInternals(600, 400)
    applyScreenFit(rfb as unknown as RfbLike)
    autoscaleCalls.length = 0
    rfb._updateScale()
    expect(autoscaleCalls).toEqual([{ w: 600, h: 400 }])
  })

  it('bỏ qua êm khi noVNC đổi API nội bộ — thà mất nét hơn là khung trắng', () => {
    const rfb = makeRfb()
    expect(() => applyScreenFit(rfb)).not.toThrow()
    expect(rfb.resizeSession).toBe(true)
  })
})
