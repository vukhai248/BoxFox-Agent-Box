/**
 * Nguồn màu HEX thật duy nhất cho attribute SVG / JSON của canvas.
 * MIRROR `frontend/src/index.css` — KHÔNG đổi hex ở đây mà không đồng bộ
 * `index.css`. Không dùng `var(--c-*)`: attribute SVG không resolve `var()`,
 * và scene JSON gửi cho agent phải là màu thật, không phải tham chiếu CSS.
 */
export const PALETTE = {
  bg: '#0a0a0a',
  panel: '#121212',
  panel2: '#1c1c1c',
  line: '#262626',
  fg: '#f5f5f5',
  muted: '#8c8c8c',
  brand: '#3b82f6',
  brandFg: '#ffffff',
} as const

/** Accent dùng cho badge/annotation (theo Tailwind default, không phải token). */
export const ACCENT = {
  amber: '#f59e0b',
  emerald: '#10b981',
} as const

/** Ô màu fill gợi ý trong StylePalette (lựa chọn người dùng, không phải token). */
export const FILL_SWATCHES = [
  '#1c1c1c',
  '#3b82f6',
  '#10b981',
  '#f59e0b',
  '#ef4444',
  '#a855f7',
  '#0ea5e9',
  '#f5f5f5',
] as const

/** Ô màu stroke gợi ý trong StylePalette. */
export const STROKE_SWATCHES = [
  '#3b82f6',
  '#262626',
  '#f5f5f5',
  '#f59e0b',
  '#10b981',
  '#ef4444',
  '#a855f7',
] as const
