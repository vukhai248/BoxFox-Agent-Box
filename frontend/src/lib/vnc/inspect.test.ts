/**
 * Test hình học thuần của Element Selector — không DOM, không trình duyệt.
 */
import { describe, expect, it } from 'vitest'
import { canvasPointToFramebuffer, framebufferBoxToCanvasCss, type CanvasRect } from './inspect'

function rect(partial: Partial<CanvasRect> & { left: number; top: number; width: number; height: number }): CanvasRect {
  return {
    left: partial.left,
    top: partial.top,
    width: partial.width,
    height: partial.height,
    right: partial.right ?? partial.left + partial.width,
    bottom: partial.bottom ?? partial.top + partial.height,
  }
}

describe('canvasPointToFramebuffer', () => {
  it('tỉ lệ 1:1 trả đúng toạ độ tương đối', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 100, clientY: 50 }),
    ).toEqual({ x: 100, y: 50 })
  })

  it('phóng to (framebuffer 2560 / css 1280, DPR 2) nhân 2', () => {
    const r = rect({ left: 0, top: 0, width: 1280, height: 720 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 2560, canvasHeight: 1440, clientX: 100, clientY: 100 }),
    ).toEqual({ x: 200, y: 200 })
  })

  it('thu nhỏ (framebuffer 800 / css 1600) chia 2', () => {
    const r = rect({ left: 0, top: 0, width: 1600, height: 1200 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 200, clientY: 200 }),
    ).toEqual({ x: 100, y: 100 })
  })

  it('rect.left/top khác 0 thì trừ đúng gốc', () => {
    const r = rect({ left: 40, top: 20, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 140, clientY: 120 }),
    ).toEqual({ x: 100, y: 100 })
  })

  it('bấm sát cạnh phải/dưới kẹp về canvasWidth-1 / canvasHeight-1', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    // clientX = 799.9999 nằm trong [0, 800) sau khi làm tròn có thể vượt 799.
    const point = canvasPointToFramebuffer({
      rect: r,
      canvasWidth: 800,
      canvasHeight: 600,
      clientX: 799.6,
      clientY: 599.6,
    })
    expect(point).toEqual({ x: 799, y: 599 })
  })

  it('bấm phía trên/bên trái canvas (âm) kẹp về 0', () => {
    const r = rect({ left: 10, top: 10, width: 800, height: 600 })
    // clientX=10.1 -> (0.1)*1 = 0.1 -> round 0, đã hợp lệ; kiểm giá trị làm tròn âm giả lập bằng scale nhỏ hơn 1.
    const point = canvasPointToFramebuffer({
      rect: r,
      canvasWidth: 400,
      canvasHeight: 300,
      clientX: 10.2,
      clientY: 10.2,
    })
    // (0.2)*0.5 = 0.1 -> round 0
    expect(point).toEqual({ x: 0, y: 0 })
  })

  it('điểm ngoài canvas (bên trái) trả null, không clamp', () => {
    const r = rect({ left: 100, top: 100, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 50, clientY: 200 }),
    ).toBeNull()
  })

  it('điểm ngoài canvas (bên phải, đúng biên right) trả null — nửa-khoảng không lấy biên phải', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 800, clientY: 300 }),
    ).toBeNull()
  })

  it('điểm ngoài canvas (đúng biên bottom) trả null', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 400, clientY: 600 }),
    ).toBeNull()
  })

  it('điểm đúng biên trái/trên (left, top) vẫn hợp lệ — nửa-khoảng lấy biên trái', () => {
    const r = rect({ left: 10, top: 10, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 10, clientY: 10 }),
    ).toEqual({ x: 0, y: 0 })
  })

  it('rect.width === 0 trả null', () => {
    const r = rect({ left: 0, top: 0, width: 0, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 0, clientY: 0 }),
    ).toBeNull()
  })

  it('rect.height <= 0 trả null (jsdom default getBoundingClientRect trả toàn 0)', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 0 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: 0, clientY: 0 }),
    ).toBeNull()
  })

  it('clientX = NaN trả null', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 800, canvasHeight: 600, clientX: NaN, clientY: 10 }),
    ).toBeNull()
  })

  it('canvasWidth = Infinity trả null', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({
        rect: r,
        canvasWidth: Infinity,
        canvasHeight: 600,
        clientX: 10,
        clientY: 10,
      }),
    ).toBeNull()
  })

  it('canvasWidth = 0 trả null', () => {
    const r = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      canvasPointToFramebuffer({ rect: r, canvasWidth: 0, canvasHeight: 600, clientX: 10, clientY: 10 }),
    ).toBeNull()
  })

  it('làm tròn: 12.6 -> 13', () => {
    const r = rect({ left: 0, top: 0, width: 100, height: 100 })
    // scale = 10 -> 1.26 * 10 = 12.6 -> round 13
    const point = canvasPointToFramebuffer({
      rect: r,
      canvasWidth: 1000,
      canvasHeight: 1000,
      clientX: 1.26,
      clientY: 1.26,
    })
    expect(point).toEqual({ x: 13, y: 13 })
  })
})

describe('framebufferBoxToCanvasCss', () => {
  it('1:1, hai rect trùng nhau trả nguyên hộp', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 10, y: 20, width: 30, height: 40 },
        canvasRect,
        overlayRect,
        canvasWidth: 800,
        canvasHeight: 600,
      }),
    ).toEqual({ left: 10, top: 20, width: 30, height: 40 })
  })

  it('DPR 2 chia đôi mọi chiều', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 100, y: 200, width: 60, height: 80 },
        canvasRect,
        overlayRect,
        canvasWidth: 1600,
        canvasHeight: 1200,
      }),
    ).toEqual({ left: 50, top: 100, width: 30, height: 40 })
  })

  it('canvas letterbox trong overlay (canvasRect.left - overlayRect.left = 80) cộng đúng 80 vào left', () => {
    const canvasRect = rect({ left: 80, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 960, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 0, y: 0, width: 10, height: 10 },
        canvasRect,
        overlayRect,
        canvasWidth: 800,
        canvasHeight: 600,
      }),
    ).toEqual({ left: 80, top: 0, width: 10, height: 10 })
  })

  it('canvasRect rỗng trả null', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 0, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 0, y: 0, width: 10, height: 10 },
        canvasRect,
        overlayRect,
        canvasWidth: 800,
        canvasHeight: 600,
      }),
    ).toBeNull()
  })

  it('overlayRect rỗng trả null', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 0 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 0, y: 0, width: 10, height: 10 },
        canvasRect,
        overlayRect,
        canvasWidth: 800,
        canvasHeight: 600,
      }),
    ).toBeNull()
  })

  it('box.width <= 0 trả null', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 0, y: 0, width: 0, height: 10 },
        canvasRect,
        overlayRect,
        canvasWidth: 800,
        canvasHeight: 600,
      }),
    ).toBeNull()
  })

  it('box.height <= 0 trả null', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 0, y: 0, width: 10, height: -1 },
        canvasRect,
        overlayRect,
        canvasWidth: 800,
        canvasHeight: 600,
      }),
    ).toBeNull()
  })

  it('canvasWidth không hợp lệ trả null', () => {
    const canvasRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    const overlayRect = rect({ left: 0, top: 0, width: 800, height: 600 })
    expect(
      framebufferBoxToCanvasCss({
        box: { x: 0, y: 0, width: 10, height: 10 },
        canvasRect,
        overlayRect,
        canvasWidth: 0,
        canvasHeight: 600,
      }),
    ).toBeNull()
  })
})
