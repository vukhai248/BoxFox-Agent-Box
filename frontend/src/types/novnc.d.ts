/**
 * Kiểu TypeScript tối thiểu cho `@novnc/novnc@1.7.0`.
 *
 * Gói này KHÔNG ship file `.d.ts` nào (đã kiểm: `find node_modules/@novnc/novnc
 * -name '*.d.ts'` → 0 kết quả). Gói types cộng đồng `@types/novnc__novnc`
 * khai báo cho đường `@novnc/novnc/lib/rfb`, đã CHẾT ở 1.7.0 (package.json của
 * 1.7.0 có `"exports": "./core/rfb.js"` dạng chuỗi ⇒ chỉ entry gốc, mọi
 * subpath bị chặn, và không có thư mục `lib/`) — vì vậy KHÔNG cài gói đó.
 *
 * Chỉ khai những thành viên thực sự dùng ở `src/hooks/useVncScreen.ts` (đọc
 * trực tiếp từ `node_modules/@novnc/novnc/core/rfb.js` để chắc đúng, không
 * suy diễn từ doc). Khai thừa là nợ phải bảo trì.
 *
 * Nâng cấp phiên bản `@novnc/novnc` là hành động có chủ ý — phải đọc lại file
 * `core/rfb.js` của bản mới và cập nhật khai báo này cho khớp.
 *
 * BẪY: đừng viết `class RFB extends EventTarget`. Ghi đè `addEventListener`
 * bằng chữ ký hẹp trên lớp kế thừa `EventTarget` sẽ lỗi "not assignable to
 * the same property in base type". Khai một lớp độc lập, tự có
 * add/removeEventListener với chữ ký của riêng nó.
 */
declare module '@novnc/novnc' {
  interface NoVncEventMap {
    connect: CustomEvent<Record<string, never>>
    disconnect: CustomEvent<{ clean: boolean }>
    securityfailure: CustomEvent<{ status: number; reason?: string }>
    credentialsrequired: CustomEvent<{ types: string[] }>
  }

  interface NoVncOptions {
    shared?: boolean
    credentials?: { username?: string; password?: string; target?: string }
    repeaterID?: string
    wsProtocols?: string[]
  }

  export default class RFB {
    constructor(target: Element, urlOrChannel: string | WebSocket, options?: NoVncOptions)

    viewOnly: boolean
    scaleViewport: boolean
    clipViewport: boolean
    resizeSession: boolean
    showDotCursor: boolean
    background: string

    disconnect(): void
    focus(options?: FocusOptions): void
    blur(): void

    addEventListener<K extends keyof NoVncEventMap>(
      type: K,
      listener: (event: NoVncEventMap[K]) => void,
    ): void
    removeEventListener<K extends keyof NoVncEventMap>(
      type: K,
      listener: (event: NoVncEventMap[K]) => void,
    ): void
  }
}
