/**
 * Cầu nối React cho tab IDE — nhúng code-server của box.
 *
 * Chỗ duy nhất chạm vào `fetch`, `window` và `import.meta.env`; máy trạng thái
 * thuần nằm ở `src/lib/ide/state.ts`, cấu hình ở `src/lib/ide/config.ts`.
 * `IdePanel.tsx` chỉ đọc kết quả của hook này.
 *
 * Vì sao phải THĂM DÒ trước khi mount iframe: iframe khác origin không cho đọc
 * gì bên trong, và `onLoad` của nó bắn cả khi trình duyệt hiển thị trang lỗi
 * "connection refused". Nếu tin `onLoad` thì panel sẽ khoe "đã nối" trong khi
 * người dùng đang nhìn trang lỗi của Chrome. Một `fetch(mode:'no-cors')` trả
 * response mờ (opaque) là đủ để biết code-server có trả lời hay không, mà không
 * cần code-server bật CORS.
 *
 * Không cần trả ra `key` cho iframe: mọi lượt thăm dò lại đều đưa phase về
 * 'probing', mà ở phase đó panel render thẻ chờ thay cho iframe — iframe bị
 * unmount sẵn rồi, nên "Nạp lại IDE" tự khắc nạp editor từ đầu.
 */
import { useCallback, useEffect, useMemo, useReducer, useState } from 'react'
import {
  describeIdeContextProblem,
  resolveIdeSource,
  resolveIdeUrl,
  type IdeSource,
} from '../lib/ide/config'
import {
  IDE_PROBE_TIMEOUT_MS,
  ideRetryDelayMs,
  initialIdeState,
  offIdeState,
  reduceIde,
  type IdeOfflineReason,
  type IdePhase,
} from '../lib/ide/state'
import { useUiStore } from '../store/uiStore'

export interface UseIdeFrameResult {
  /** `off` ⇒ không thăm dò, không mount iframe nào. */
  source: IdeSource
  phase: IdePhase
  reason: IdeOfflineReason | null
  url: string
  /** Mốc thời gian (ms) của lần tự thử lại kế tiếp — dùng cho đếm ngược. `null` nếu không có. */
  retryAtMs: number | null
  /** Thăm dò lại rồi mount lại iframe (dùng cho cả "Thử kết nối lại" và "Nạp lại IDE"). */
  retry: () => void
}

export function useIdeFrame(): UseIdeFrameResult {
  const source = useMemo(() => resolveIdeSource(import.meta.env), [])
  const enabled = source === 'codeServer'
  const [state, dispatch] = useReducer(reduceIde, enabled ? initialIdeState : offIdeState)
  const [retryAtMs, setRetryAtMs] = useState<number | null>(null)

  // Khi người dùng "Mở trong VS Code Web" từ tab Files, store đặt `ideLaunchUrl`
  // trỏ tới thư mục cha của file đó; ưu tiên URL này, ngược lại về mặc định.
  const ideLaunchUrl = useUiStore((s) => s.ideLaunchUrl)
  const url = useMemo(() => ideLaunchUrl ?? resolveIdeUrl(import.meta.env), [ideLaunchUrl])

  // Effect A — một lượt thăm dò. `state.seq` chỉ tăng ở `probeStarted` /
  // `manualRetry`, cả hai đều đặt phase='probing'.
  useEffect(() => {
    if (!enabled) return

    const problem = describeIdeContextProblem({ pageProtocol: window.location.protocol, url })
    if (problem) {
      dispatch({ type: 'failed', reason: problem })
      return
    }

    let cancelled = false
    const controller = new AbortController()
    let timedOut = false
    const timeoutId = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, IDE_PROBE_TIMEOUT_MS)

    // `no-cors`: chỉ cần biết có ai trả lời, không cần đọc nội dung. `cache:
    // 'no-store'` để lần thử lại không ăn cache của lần trước và báo "sống" oan.
    fetch(url, { mode: 'no-cors', cache: 'no-store', signal: controller.signal })
      .then(() => {
        if (!cancelled) dispatch({ type: 'reachable' })
      })
      .catch(() => {
        if (!cancelled) dispatch({ type: 'failed', reason: timedOut ? 'timeout' : 'unreachable' })
      })
      .finally(() => clearTimeout(timeoutId))

    return () => {
      cancelled = true
      clearTimeout(timeoutId)
      controller.abort()
    }
  }, [enabled, url, state.seq])

  // Effect B — hẹn thử lại tự động khi đang offline và còn lượt.
  useEffect(() => {
    const delay = ideRetryDelayMs(state)
    if (delay === null) {
      setRetryAtMs(null)
      return
    }
    setRetryAtMs(Date.now() + delay)
    const id = setTimeout(() => dispatch({ type: 'probeStarted' }), delay)
    return () => clearTimeout(id)
  }, [state.phase, state.attempt, state.exhausted])

  const retry = useCallback(() => dispatch({ type: 'manualRetry' }), [])

  return {
    source,
    phase: state.phase,
    reason: state.reason,
    url,
    retryAtMs,
    retry,
  }
}
