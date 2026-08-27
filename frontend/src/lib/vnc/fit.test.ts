/**
 * Bài chống hồi quy cho cơ chế khớp màn hình và HiDPI.
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
    setDpr(0.75)
    expect(devicePixelScale()).toBe(1)
  })

  it('xử lý an toàn khi devicePixelRatio là NaN / không hợp lệ', () => {
    setDpr(Number.NaN)
    expect(devicePixelScale()).toBe(1)
  })
})

describe('physicalScreenSize', () => {
  it('nhân đúng DPR và làm tròn xuống pixel nguyên', () => {
    // 787.2 CSS px × 1.25 DPR = 984 physical px
    expect(physicalScreenSize(787.2, 532.8, 1.25)).toEqual({ w: 984, h: 666 })
  })

  it('kích thước tối thiểu là 1x1 ngay cả khi CSS pixel là 0', () => {
    expect(physicalScreenSize(0, 0, 1.25)).toEqual({ w: 1, h: 1 })
  })

  it('DPR 1.0 trả đúng kích thước CSS đã làm tròn', () => {
    expect(physicalScreenSize(1024.7, 768.2, 1)).toEqual({ w: 1024, h: 768 })
  })
})

describe('patchForHiDpi trên instance noVNC', () => {
  it('vá _screenSize để trả kích thước vật lý thay vì getBoundingClientRect thô', () => {
    const mockScreen = {
      getBoundingClientRect: () => ({
        width: 800,
        height: 600,
        top: 0,
        left: 0,
        right: 800,
        bottom: 600,
        x: 0,
        y: 0,
        toJSON() {},
      }),
    }

    const rfb = {
      ...makeRfb(),
      _screen: mockScreen,
      _screenSize() {
        return { w: 800, h: 600 }
      },
      _updateScale() {},
    }

    // Set DPR = 1.25
    Object.defineProperty(window, 'devicePixelRatio', {
      value: 1.25,
      configurable: true,
      writable: true,
    })

    applyScreenFit(rfb as unknown as RfbLike)

    const size = rfb._screenSize()
    expect(size).toEqual({ w: 1000, h: 750 })
  })
})
