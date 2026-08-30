/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TRANSPORT?: 'mock' | 'live'
  readonly VITE_AGENT_WS_URL?: string
  /** Base URL của ide-proxy/Box API; để trống dùng http://localhost:8081. */
  readonly VITE_BOX_API_URL?: string
  /** Token điều khiển box (khớp BOXFOX_API_KEY phía deploy/docker); để trống dùng
   *  giá trị mặc định đã commit trong `src/lib/boxApi.ts`. */
  readonly VITE_BOX_API_KEY?: string
  /** Nguồn file plan: sandbox (mặc định) | mock (chỉ test/demo). */
  readonly VITE_PLAN_SOURCE?: 'sandbox' | 'mock'
  /** Nguồn trình duyệt file workspace: sandbox (mặc định) | mock (chỉ test/demo). */
  readonly VITE_WORKSPACE_SOURCE?: 'sandbox' | 'mock'
  /** Nguồn khung hình của khung ④: `mock` (mặc định) | `novnc` — xem `src/lib/vnc/config.ts`. */
  readonly VITE_SANDBOX_SCREEN_SOURCE?: 'mock' | 'novnc'
  /** URL websockify của kênh noVNC riêng của người dùng (xem `src/lib/vnc/config.ts`). */
  readonly VITE_SANDBOX_VNC_URL?: string
  /** Tab IDE: để trống là bật code-server; `off` là không nhúng gì — xem `src/lib/ide/config.ts`. */
  readonly VITE_IDE_SOURCE?: 'code-server' | 'off'
  /** URL code-server của box mà tab IDE nhúng (xem `src/lib/ide/config.ts`). */
  readonly VITE_IDE_URL?: string
  /** Đường hầm Terminal qua ide-proxy — xem `src/lib/terminal/config.ts`. */
  readonly VITE_BOX_TTY_URL?: string
  /** Nguồn dữ liệu của Element Selector (khung ④): sandbox (mặc định) | mock — xem `src/lib/inspect/index.ts`. */
  readonly VITE_ELEMENT_INSPECT_SOURCE?: 'sandbox' | 'mock'
}
