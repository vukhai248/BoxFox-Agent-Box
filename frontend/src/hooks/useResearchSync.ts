/**
 * Cầu nối giữa luồng sự kiện phiên (đã được `ChatPanel` hỏi mỗi 1200 ms) và `researchStore`.
 *
 * Vì sao không phải một vòng hỏi riêng: hợp đồng §5.12 cấm `ResearchPanel` hỏi
 * `/research/jobs` mỗi 5000 ms. Nguồn sự thật là sự kiện `research_*` trên luồng sự kiện phiên;
 * hook này đẩy (cấu hình chế độ, sự kiện mới) sang store, và store chỉ gọi mạng khi có sự kiện
 * mới hoặc chế độ vừa đổi.
 */
import { useEffect } from 'react'
import { useAgentStore } from '../store/agentStore'
import { useHarnessChatStore } from '../store/harnessChatStore'
import { useResearchStore } from '../store/researchStore'
import type { ResearchMode } from '../lib/researchMode'

export function useResearchSync(): ResearchMode {
  const chatId = useAgentStore((s) => s.activeSessionId)
  const run = useHarnessChatStore((s) => s.sessions[chatId])
  // Danh tính ỔN ĐỊNH của phiên: id server khi đã biết, nếu không thì khoá cục bộ. Phiên tạo trong trang
  // bắt đầu bằng khoá tạm rồi nhận id server, còn mở lại từ danh sách bên thì dùng id server ngay: lấy
  // id server làm khoá để sổ mốc của `researchStore` không bị tách làm hai (R5-1).
  const identity = run?.id ?? chatId
  const events = run?.events
  const researchMode = run?.researchMode
  const sync = useResearchStore((s) => s.sync)
  const mode = useResearchStore((s) => s.mode)

  useEffect(() => {
    sync(identity, { researchMode }, events ?? [])
  }, [identity, researchMode, events, sync])

  return mode
}
