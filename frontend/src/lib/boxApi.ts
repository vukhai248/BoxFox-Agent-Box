/** Cấu hình API máy sandbox dùng chung cho các khả năng chạy ngoài luồng agent. */

export const DEFAULT_BOX_API_URL = 'http://localhost:8081'

/**
 * Token đi kèm các request điều khiển box (bật/tắt mạng, điện).
 *
 * Đây KHÔNG phải khóa API của nhà cung cấp — nó là token chia sẻ giữa giao diện
 * web (:3100) và ide-proxy trong box trên CÙNG một máy (cả hai đều nằm sau
 * loopback). Mục đích: chặn process chạy BÊN TRONG box giả mạo header `Origin`
 * để tự bật lại mạng. Giá trị mặc định được commit để clone về chạy ngay;
 * triển khai thật có thể đổi qua VITE_BOX_API_KEY (xem .env.example) và phải
 * khớp BOXFOX_API_KEY phía deploy/docker/docker-compose.yml.
 */
export const DEFAULT_BOX_API_KEY = 'boxfox-local-dev-token'

/** Nhận `env` qua tham số để unit test không phụ thuộc Vite. */
export function resolveBoxApiUrl(env?: { VITE_BOX_API_URL?: string }): string {
  const raw = env?.VITE_BOX_API_URL?.trim()
  return (raw || DEFAULT_BOX_API_URL).replace(/\/$/, '')
}

/** Nhận token điều khiển box; rỗng nghĩa là chưa cấu hình riêng. */
export function resolveBoxApiKey(env?: { VITE_BOX_API_KEY?: string }): string {
  const raw = env?.VITE_BOX_API_KEY?.trim()
  return raw || DEFAULT_BOX_API_KEY
}
