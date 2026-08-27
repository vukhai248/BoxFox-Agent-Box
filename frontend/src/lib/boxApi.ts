/** Cấu hình API máy sandbox dùng chung cho các khả năng chạy ngoài luồng agent. */

export const DEFAULT_BOX_API_URL = 'http://localhost:8081'

/** Nhận `env` qua tham số để unit test không phụ thuộc Vite. */
export function resolveBoxApiUrl(env?: { VITE_BOX_API_URL?: string }): string {
  const raw = env?.VITE_BOX_API_URL?.trim()
  return (raw || DEFAULT_BOX_API_URL).replace(/\/$/, '')
}
