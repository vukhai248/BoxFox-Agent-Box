/**
 * Test cho hai phép quy đổi toạ độ của panel "Màn hình máy".
 *
 * Hai thứ tệp này KHOÁ LẠI (đều là lỗi đã từng xảy ra ở chỗ khác):
 *   1. KHÔNG nhân `devicePixelRatio`. Tỉ số `imageWidth / rect.width` đã gộp sẵn
 *      hệ số đó (ảnh chụp là pixel framebuffer, rect là CSS pixel). Ca dưới đây
 *      dựng đúng tình huống DPR = 2 (ảnh rộng gấp đôi khung) và đòi kết quả
 *      KHÔNG bị nhân đôi lần nữa.
 *   2. `captureOrigin` có thể ÂM (màn hình phụ nằm bên trái màn hình chính).
 *   3. Hộp nằm HOÀN TOÀN ngoài vùng chụp phải ra `null` (không vẽ gì): khung chứa
 *      không cắt, nên toạ độ âm sẽ vẽ viền tràn ra ngoài ảnh. Hộp chỉ nằm MỘT
 *      PHẦN ngoài thì vẫn ra toạ độ âm và KHÔNG bị clamp — clamp sẽ vẽ một khung
 *      sai chỗ thay vì vẽ đúng phần nhìn thấy được.
 */
import { describe, expect, it } from 'vitest'
import { cssBoxStyle, framebufferBoxToImageCss, imagePointToFramebuffer } from './geometry'
import type { CanvasRect } from '../vnc/inspect'

/** Khung CSS 400 × 300, ảnh bên trong 800 × 600 pixel (đúng tình huống DPR = 2). */
const IMAGE_RECT: CanvasRect = { left: 100, top: 50, right: 500, bottom: 350, width: 400, height: 300 }
const OVERLAY_RECT: CanvasRect = { left: 100, top: 50, right: 500, bottom: 350, width: 400, height: 300 }

describe('imagePointToFramebuffer', () => {
  it('đổi điểm giữa ảnh sang pixel framebuffer rồi cộng gốc vùng chụp', () => {
    // Cách tâm ảnh 100 CSS px theo mỗi trục ⇒ 200 pixel ảnh ⇒ ảnh (400, 300).
    expect(
      imagePointToFramebuffer({
        imageRect: IMAGE_RECT,
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: { x: -100, y: 20 },
        clientX: 300,
        clientY: 200,
      }),
    ).toEqual({ x: 300, y: 320 })
  })

  it('KHÔNG nhân devicePixelRatio: ảnh 2× khung vẫn chỉ ra đúng pixel ảnh', () => {
    // Nếu nhân DPR (2) một lần nữa thì kết quả sẽ là (800, 600) — sai gấp đôi.
    const point = imagePointToFramebuffer({
      imageRect: IMAGE_RECT,
      imageWidth: 800,
      imageHeight: 600,
      captureOrigin: { x: 0, y: 0 },
      clientX: 300,
      clientY: 200,
    })
    expect(point).toEqual({ x: 400, y: 300 })
    expect(point).not.toEqual({ x: 800, y: 600 })
  })

  it('gốc âm (màn hình phụ bên trái) cho ra toạ độ âm, không clamp về 0', () => {
    expect(
      imagePointToFramebuffer({
        imageRect: IMAGE_RECT,
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: { x: -1920, y: 0 },
        clientX: 100,
        clientY: 50,
      }),
    ).toEqual({ x: -1920, y: 0 })
  })

  it('bấm ngoài ảnh (dải letterbox) ⇒ null, không tra vào pixel biên', () => {
    const base = {
      imageRect: IMAGE_RECT,
      imageWidth: 800,
      imageHeight: 600,
      captureOrigin: { x: 0, y: 0 },
    }
    expect(imagePointToFramebuffer({ ...base, clientX: 500, clientY: 200 })).toBeNull()
    expect(imagePointToFramebuffer({ ...base, clientX: 99, clientY: 200 })).toBeNull()
    expect(imagePointToFramebuffer({ ...base, clientX: 300, clientY: 350 })).toBeNull()
    expect(imagePointToFramebuffer({ ...base, clientX: 300, clientY: 49 })).toBeNull()
  })

  it('ảnh chưa đo được (rect rỗng) ⇒ null, không ra NaN', () => {
    expect(
      imagePointToFramebuffer({
        imageRect: { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 },
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: { x: 0, y: 0 },
        clientX: 0,
        clientY: 0,
      }),
    ).toBeNull()
  })

  it('gốc thiếu hoặc không hợp lệ coi như (0, 0) — nền cũ trả ảnh không kèm gốc', () => {
    const atCorner = (captureOrigin: { x: number; y: number } | undefined) =>
      imagePointToFramebuffer({
        imageRect: IMAGE_RECT,
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: captureOrigin as { x: number; y: number },
        clientX: 100,
        clientY: 50,
      })
    expect(atCorner(undefined)).toEqual({ x: 0, y: 0 })
    expect(atCorner({ x: Number.NaN, y: 5 })).toEqual({ x: 0, y: 0 })
  })
})

describe('framebufferBoxToImageCss', () => {
  it('hộp trong vùng chụp ⇒ toạ độ CSS đúng tỉ lệ ảnh', () => {
    // Hộp vật lý (200, 100) 40 × 20; gốc chụp (100, 50) ⇒ hộp ảnh (100, 50).
    // Tỉ lệ ảnh→CSS là 0.5 ⇒ (50, 25) 20 × 10, cộng gốc khung (ảnh lệch 0).
    expect(
      framebufferBoxToImageCss({
        box: { x: 200, y: 100, width: 40, height: 20 },
        imageRect: IMAGE_RECT,
        overlayRect: OVERLAY_RECT,
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: { x: 100, y: 50 },
      }),
    ).toEqual({ left: 50, top: 25, width: 20, height: 10 })
  })

  it('trừ captureOrigin trước khi co giãn — gốc âm vẫn đúng', () => {
    // Cùng hộp ẢNH như ca trên, nhưng gốc chụp âm 100 ⇒ hộp vật lý phải dịch 100.
    expect(
      framebufferBoxToImageCss({
        box: { x: 0, y: 0, width: 40, height: 20 },
        imageRect: IMAGE_RECT,
        overlayRect: OVERLAY_RECT,
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: { x: -100, y: -50 },
      }),
    ).toEqual({ left: 50, top: 25, width: 20, height: 10 })
  })

  it('ảnh lệch trong khung ⇒ cộng thêm độ lệch gốc (overlayRect khác imageRect)', () => {
    const overlay: CanvasRect = { left: 110, top: 60, right: 510, bottom: 360, width: 400, height: 300 }
    expect(
      framebufferBoxToImageCss({
        box: { x: 200, y: 100, width: 40, height: 20 },
        imageRect: IMAGE_RECT,
        overlayRect: overlay,
        imageWidth: 800,
        imageHeight: 600,
        captureOrigin: { x: 100, y: 50 },
      }),
    ).toEqual({ left: 40, top: 15, width: 20, height: 10 })
  })

  it('hộp nằm HOÀN TOÀN ngoài vùng chụp ⇒ null (không vẽ gì)', () => {
    const base = {
      imageRect: IMAGE_RECT,
      overlayRect: OVERLAY_RECT,
      imageWidth: 800,
      imageHeight: 600,
    }
    // Gốc chụp đẩy hộp ra hẳn bên trái / phía trên vùng chụp (cửa sổ ở màn hình khác).
    expect(
      framebufferBoxToImageCss({ ...base, box: { x: 0, y: 0, width: 100, height: 100 }, captureOrigin: { x: 1000, y: 500 } }),
    ).toBeNull()
    // Chạm đúng mép (x + width === 0) vẫn là ngoài: không có pixel nào để vẽ.
    expect(
      framebufferBoxToImageCss({ ...base, box: { x: 0, y: 0, width: 100, height: 100 }, captureOrigin: { x: 100, y: 0 } }),
    ).toBeNull()
    // Nằm hẳn bên phải / phía dưới vùng chụp.
    expect(
      framebufferBoxToImageCss({ ...base, box: { x: 800, y: 0, width: 100, height: 100 }, captureOrigin: { x: 0, y: 0 } }),
    ).toBeNull()
    expect(
      framebufferBoxToImageCss({ ...base, box: { x: 0, y: 600, width: 100, height: 100 }, captureOrigin: { x: 0, y: 0 } }),
    ).toBeNull()
  })

  it('hộp chỉ nằm MỘT PHẦN ngoài vùng chụp ⇒ toạ độ âm, KHÔNG clamp', () => {
    // Gốc chụp lệch 50 px: hộp vắt qua mép trái/trên ⇒ vẫn vẽ, toạ độ âm.
    const box = framebufferBoxToImageCss({
      box: { x: 0, y: 0, width: 200, height: 200 },
      imageRect: IMAGE_RECT,
      overlayRect: OVERLAY_RECT,
      imageWidth: 800,
      imageHeight: 600,
      captureOrigin: { x: 50, y: 50 },
    })
    expect(box).toEqual({ left: -25, top: -25, width: 100, height: 100 })
  })

  it('hộp suy biến (width/height ≤ 0) ⇒ null', () => {
    const base = {
      imageRect: IMAGE_RECT,
      overlayRect: OVERLAY_RECT,
      imageWidth: 800,
      imageHeight: 600,
      captureOrigin: { x: 0, y: 0 },
    }
    expect(framebufferBoxToImageCss({ ...base, box: { x: 10, y: 10, width: 0, height: 20 } })).toBeNull()
    expect(framebufferBoxToImageCss({ ...base, box: { x: 10, y: 10, width: 20, height: -5 } })).toBeNull()
  })
})

describe('cssBoxStyle', () => {
  it('chỉ lấy bốn trường cần cho style của một div tuyệt đối', () => {
    expect(cssBoxStyle({ left: 1, top: 2, width: 3, height: 4 })).toEqual({ left: 1, top: 2, width: 3, height: 4 })
  })
})
