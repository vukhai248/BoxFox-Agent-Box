/** Cấu hình kênh Terminal — cùng pattern với src/lib/vnc/config.ts (quyết định D-1). */

/**
 * Đường hầm Terminal đi qua ide-proxy (:8081) — KHÔNG mở port mới:
 * browser ⇄ ws://localhost:8081/__tty/ws ⇄ tty-bridge :7681 (loopback trong box).
 */
export const DEFAULT_BOX_TTY_URL = 'ws://localhost:8081/__tty/ws'

/** Nhận `env` qua tham số (không đọc trực tiếp `import.meta.env`) để test ngoài Vite. */
export function resolveBoxTtyUrl(env?: { VITE_BOX_TTY_URL?: string }): string {
  const raw = env?.VITE_BOX_TTY_URL?.trim()
  return raw ? raw : DEFAULT_BOX_TTY_URL
}
