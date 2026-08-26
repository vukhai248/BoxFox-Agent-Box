/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_TRANSPORT?: 'mock' | 'live'
  readonly VITE_AGENT_WS_URL?: string
  /** Nguồn khung hình của khung ④: `mock` (mặc định) | `novnc` — xem `src/lib/vnc/config.ts`. */
  readonly VITE_SANDBOX_SCREEN_SOURCE?: 'mock' | 'novnc'
  /** URL websockify của kênh noVNC riêng của người dùng (xem `src/lib/vnc/config.ts`). */
  readonly VITE_SANDBOX_VNC_URL?: string
  /** Tab IDE: để trống là bật code-server; `off` là không nhúng gì — xem `src/lib/ide/config.ts`. */
  readonly VITE_IDE_SOURCE?: 'code-server' | 'off'
  /** URL code-server của box mà tab IDE nhúng (xem `src/lib/ide/config.ts`). */
  readonly VITE_IDE_URL?: string
}
