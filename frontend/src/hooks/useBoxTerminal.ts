/**
 * Cầu nối React cho tab Terminal — mirror của useVncScreen (quyết định D-1).
 *
 * Vòng đời WS + xterm nằm ở đây; TerminalPanel chỉ đọc kết quả. Protocol với
 * tty-bridge (xem deploy/docker/tty-bridge.py):
 *   server → client : byte thuần (stdout của PTY) — AttachAddon ghi thẳng.
 *   client → server : byte bắt đầu 0x01 = JSON điều khiển (resize);
 *                     còn lại = keystrokes (AttachAddon gửi text thuần).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { AttachAddon } from '@xterm/addon-attach'
import '@xterm/xterm/css/xterm.css'
import { resolveBoxTtyUrl } from '../lib/terminal/config'

export type TermPhase = 'connecting' | 'live' | 'offline'

const CTRL_RESIZE = 0x01
const OPEN_TIMEOUT_MS = 5000

export interface UseBoxTerminalResult {
  containerRef: React.RefObject<HTMLDivElement | null>
  phase: TermPhase
  url: string
  retry: () => void
}

export function useBoxTerminal(): UseBoxTerminalResult {
  const containerRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const fitRef = useRef<FitAddon | null>(null)
  const [phase, setPhase] = useState<TermPhase>('connecting')
  const [attempt, setAttempt] = useState(0)
  const url = resolveBoxTtyUrl(import.meta.env)

  useEffect(() => {
    const host = containerRef.current
    if (!host) return
    setPhase('connecting')

    const term = new Terminal({
      fontFamily:
        '"Cascadia Code", "JetBrains Mono", "Fira Code", Menlo, Consolas, monospace',
      fontSize: 12,
      lineHeight: 1.2,
      cursorBlink: true,
      scrollback: 5000,
      theme: { background: '#0b0b0e', foreground: '#e4e4e7' },
    })
    const fit = new FitAddon()
    term.loadAddon(fit)
    term.open(host)
    try {
      fit.fit()
    } catch {
      /* khung chưa có kích thước — ResizeObserver sẽ fit lại */
    }
    fitRef.current = fit

    let disposed = false
    let ws: WebSocket | null = null

    const sendResize = () => {
      const sock = wsRef.current
      if (!sock || sock.readyState !== WebSocket.OPEN) return
      const meta = JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows })
      sock.send(new Uint8Array([CTRL_RESIZE, ...new TextEncoder().encode(meta)]))
    }
    term.onResize(sendResize)

    // Co giãn khung → fit + báo pty đổi kích thước cửa sổ.
    const ro = new ResizeObserver(() => {
      try {
        fit.fit()
        sendResize()
      } catch {
        /* khung 0×0 khi đang ẩn */
      }
    })
    ro.observe(host)

    // Quá hạn mở kết nối → offline, panel hiện nút thử lại.
    const timer = window.setTimeout(() => {
      if (!disposed && ws && ws.readyState !== WebSocket.OPEN) setPhase('offline')
    }, OPEN_TIMEOUT_MS)

    try {
      ws = new WebSocket(url)
      wsRef.current = ws
      ws.binaryType = 'arraybuffer'

      ws.onopen = () => {
        if (disposed) return
        window.clearTimeout(timer)
        setPhase('live')
        // Fit sau một frame để layout ổn định rồi báo pty đúng cột/dòng.
        requestAnimationFrame(() => {
          try {
            fit.fit()
            sendResize()
          } catch {
            /* bỏ qua */
          }
        })
      }
      ws.onclose = () => {
        if (!disposed) setPhase('offline')
      }

      // AttachAddon: onData ⇄ ws (text), ws.onmessage ⇄ term.write (arraybuffer).
      term.loadAddon(new AttachAddon(ws))
    } catch {
      setPhase('offline')
    }

    return () => {
      disposed = true
      window.clearTimeout(timer)
      ro.disconnect()
      try {
        wsRef.current?.close()
      } catch {
        /* chưa kịp mở */
      }
      wsRef.current = null
      try {
        term.dispose()
      } catch {
        /* đã dispose */
      }
    }
  }, [url, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  return { containerRef, phase, url, retry }
}
