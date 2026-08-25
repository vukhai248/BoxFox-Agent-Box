/**
 * Định dạng số kiểu Việt Nam: `.` phân nhóm nghìn, `,` phân thập phân.
 * Dùng cho bộ đếm ngân sách ở top bar và các bảng ở khung ⑤.
 */

export function formatIntVi(n: number): string {
  return n.toLocaleString('vi-VN')
}

export function formatUsdVi(n: number): string {
  return n.toLocaleString('vi-VN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** "12 bước · 48.320 token · 0,07 USD / trần 0,50 USD" */
export function formatBudgetLine(params: {
  steps: number
  tokens: number
  costUsd: number
  capUsd: number
}): string {
  return `${formatIntVi(params.steps)} bước · ${formatIntVi(params.tokens)} token · ${formatUsdVi(
    params.costUsd,
  )} USD / trần ${formatUsdVi(params.capUsd)} USD`
}

/** mm:ss còn lại tới một thời điểm ISO, không âm. */
export function formatCountdown(expiresAtIso: string, nowMs: number): string {
  const remainingMs = Math.max(0, new Date(expiresAtIso).getTime() - nowMs)
  const totalSeconds = Math.floor(remainingMs / 1000)
  const mm = Math.floor(totalSeconds / 60)
  const ss = totalSeconds % 60
  return `${mm}:${ss.toString().padStart(2, '0')}`
}

export function isExpired(expiresAtIso: string, nowMs: number): boolean {
  return nowMs >= new Date(expiresAtIso).getTime()
}

/** Rút gọn hash để hiển thị: "3f9a2c1e..." → "3f9a2c1e". */
export function shortHash(hash: string, len = 10): string {
  return hash.length > len ? `${hash.slice(0, len)}…` : hash
}
