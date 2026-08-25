import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// LƯU Ý VỀ RANH GIỚI BẢO MẬT — đọc kỹ trước khi copy cấu hình này sang bản chạy thật.
//
// Mục 12.6 của docs/plan/agent-box-plan.md yêu cầu giao diện bản chạy thật chỉ
// nghe trên 127.0.0.1 và phải kiểm header `Origin`. Cấu hình `host: true` +
// `allowedHosts: true` dưới đây CHỈ dành cho dev server trong môi trường sandbox
// phát triển, nơi trình duyệt truy cập qua một proxy xem trước nên header `Host`
// không phải là localhost. Khi đóng gói sản phẩm phải trả lại loopback-only.
//
// Port 3100 (không phải 3000) để tránh xung đột với các dự án khác chạy cùng máy.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3100,
    host: true,
    allowedHosts: true,
  },
})
