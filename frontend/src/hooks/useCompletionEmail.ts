/**
 * Theo dõi trạng thái phiên đang mở: khi nó CHUYỂN sang `xong` (box hoàn thành
 * task) và người dùng đã bật công tắc + nhập email, thì ghi một email mock vào
 * `uiStore.completionEmail` để hiển thị banner xem trước.
 *
 * "Việc đã làm" được lấy từ các bước `agent_step` đã gọi tool (tin nhắn chat),
 * vì plan snapshot trong mock không cập nhật `status` theo tiến độ. Chỉ bắn đúng
 * một lần cho mỗi lần chuyển trạng thái (dùng `prevStatus`) — reset kịch bản đưa
 * trạng thái về `dang_chay` nên lần chạy sau sẽ bắn lại bình thường.
 */
import { useEffect, useRef } from 'react'
import { useAgentStore } from '../store/agentStore'
import { useUiStore } from '../store/uiStore'
import { useI18n } from '../i18n/context'
import { workTargetOf, type ExecutedWork } from '../lib/notifyEmail'

function collectWork(messages: { kind: string; tool_name?: string; params?: Record<string, string> }[]): ExecutedWork[] {
  return messages
    .filter((m) => m.kind === 'agent_step' && m.tool_name)
    .map((m) => ({ tool: m.tool_name as ExecutedWork['tool'], target: workTargetOf(m.params) }))
}

export function useCompletionEmail(): void {
  const { lang } = useI18n()
  const status = useAgentStore(
    (s) => s.sessions.find((x) => x.session_id === s.activeSessionId)?.status,
  )
  const title = useAgentStore(
    (s) => s.sessions.find((x) => x.session_id === s.activeSessionId)?.title,
  )
  const messages = useAgentStore((s) => s.messages)
  const userEmail = useUiStore((s) => s.userEmail)
  const notifyOnComplete = useUiStore((s) => s.notifyOnComplete)
  const setCompletionEmail = useUiStore((s) => s.setCompletionEmail)

  const prevStatus = useRef(status)

  useEffect(() => {
    const completed = prevStatus.current !== 'xong' && status === 'xong'
    prevStatus.current = status
    if (!completed) return
    const to = userEmail.trim()
    if (!notifyOnComplete || !to) return
    setCompletionEmail({
      to,
      at: new Date().toISOString(),
      lang,
      title: title ?? '',
      work: collectWork(messages),
    })
  }, [status, notifyOnComplete, userEmail, lang, title, messages, setCompletionEmail])
}
