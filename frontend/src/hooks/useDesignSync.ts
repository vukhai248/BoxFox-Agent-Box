/**
 * Cầu nối giữa luồng sự kiện phiên (đã được `ChatPanel` hỏi mỗi 1200 ms) và `designStore` (P1).
 *
 * Vì sao không phải một vòng hỏi riêng: cùng luật với `useResearchSync` — nguồn sự thật là sự kiện
 * `design_*` trên luồng sự kiện phiên; hook này đẩy (cấu hình chế độ, sự kiện mới) sang store, và
 * store chỉ gọi mạng khi có sự kiện mới hoặc chế độ vừa đổi.
 */
import { useEffect } from 'react'
import { useAgentStore } from '../store/agentStore'
import { useHarnessChatStore } from '../store/harnessChatStore'
import { useDesignStore } from '../store/designStore'
import type { DesignMode } from '../lib/designMode'

export function useDesignSync(): DesignMode {
  const chatId = useAgentStore((s) => s.activeSessionId)
  const run = useHarnessChatStore((s) => s.sessions[chatId])
  // Danh tính ỔN ĐỊNH của phiên: id server khi đã biết, nếu không thì khoá cục bộ — cùng quy ước với
  // `useResearchSync` để sổ mốc `seq` không bị tách làm hai.
  const identity = run?.id ?? chatId
  const events = run?.events
  const designMode = run?.designMode
  const sync = useDesignStore((s) => s.sync)
  const mode = useDesignStore((s) => s.mode)

  useEffect(() => {
    sync(identity, { designMode }, events ?? [])
  }, [identity, designMode, events, sync])

  return mode
}
