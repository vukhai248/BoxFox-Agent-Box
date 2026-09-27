/**
 * Harness thử lại yêu cầu model sau khi socket đứt giữa câu trả lời.
 *
 * Lượt thử đầu đã phát một phần văn bản; event `notice` với `reset: true` báo rằng
 * phần đó bị bỏ. Không có bước làm sạch này, câu trả lời mới bị DÁN vào phần cũ
 * (đúng triệu chứng văn bản lặp mà chủ sở hữu báo) và người dùng không biết vì sao
 * câu trả lời bắt đầu lại.
 */
import type { ReactNode } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { HarnessStepView } from './HarnessStepView'
import { I18nProvider } from '../../i18n'
import type { HarnessEvent } from '../../store/harnessChatStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let roots: Root[] = []
let seq = 0

function ev(type: string, data: Record<string, unknown> = {}): HarnessEvent {
  seq += 1
  return { seq, type, data, created: 1000 + seq }
}

function render(node: ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const root = createRoot(host)
  act(() => root.render(<I18nProvider>{node}</I18nProvider>))
  roots.push(root)
  return host
}

function click(el: Element | null) {
  act(() => {
    el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

/** R2 (yêu cầu 5): lượt đã xong thì khối hoạt động đang gấp — mở ra rồi mới đọc hàng bên trong. */
function openActivity(host: HTMLElement) {
  click(host.querySelector('[data-activity-toggle="true"]'))
}

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

describe('HarnessStepView — notice thử lại', () => {
  it('hiện một dòng thông báo, không phải bảng màu mới', () => {
    const host = render(
      <HarnessStepView
        events={[
          ev('user', { text: 'viết kế hoạch' }),
          ev('notice', { code: 'UPSTREAM_RETRY', reset: true, message: 'UPSTREAM_UNREACHABLE: đang thử lại' }),
          ev('assistant', { text: 'Kế hoạch mới.', final: true }),
        ]}
        status="completed"
        error={null}
      />,
    )
    openActivity(host)

    const notice = host.querySelector('[data-timeline="notice"]') as HTMLElement | null
    expect(notice).toBeTruthy()
    expect(notice?.getAttribute('data-notice-code')).toBe('UPSTREAM_RETRY')
    expect(notice?.textContent).toContain('đang thử lại')
    // Hàng thông báo là một hàng CỦA khối hoạt động (yêu cầu 5), không phải một cây riêng.
    expect(notice!.closest('[data-activity="true"]')).not.toBeNull()
  })

  it('notice ANSWER_TOO_LONG đi qua đúng bộ render notice sẵn có', () => {
    const host = render(
      <HarnessStepView
        events={[
          ev('user', { text: 'viết báo cáo' }),
          ev('assistant', { text: 'Báo cáo đầy đủ: xem .reports/v22.md', final: true }),
          ev('notice', {
            code: 'ANSWER_TOO_LONG',
            partial: true,
            chars: 200000,
            keptChars: 150000,
            limit: 150000,
            journalSeq: 1,
            message: 'ANSWER_TOO_LONG: the answer was 200000 chars and was cut at 150000 — write the '
              + 'full content to a file in the workspace and quote the path',
          }),
        ]}
        status="completed"
        error={null}
      />,
    )
    openActivity(host)

    // Cổng D2 nói ra sự thật bằng một hàng CỦA khối hoạt động: đúng bộ render sẵn có, đúng mã,
    // và có số ký tự thật — người dùng biết vì sao câu trả lời bị cắt chứ không đoán.
    const notice = host.querySelector('[data-timeline="notice"]') as HTMLElement | null
    expect(notice).toBeTruthy()
    expect(notice?.getAttribute('data-notice-code')).toBe('ANSWER_TOO_LONG')
    expect(notice?.textContent).toContain('150000')
    expect(notice!.closest('[data-activity="true"]')).not.toBeNull()
    // Lượt vẫn là lượt ĐÃ XONG: cắt bớt không biến câu trả lời thành lỗi.
    expect(host.textContent).toContain('Báo cáo đầy đủ')
  })

  it('notice BTW_PENDING sau `finish` vẫn nằm trong lượt vừa xong (câu hỏi phụ chưa kịp bơm)', () => {
    // P5 (vòng kiểm thử đầu-cuối vòng 3): lượt đóng mà câu hỏi phụ `/btw` còn nằm trong hàng chờ thì
    // harness phát `notice` NGAY SAU `finish`. Hàng ấy phải đọc được — nếu bộ dựng lượt đóng lượt
    // trước khi notice tới thì chủ nhà không bao giờ biết vì sao câu hỏi không được trả lời.
    const host = render(
      <HarnessStepView
        events={[
          ev('user', { text: '/btw pin này dùng ở đâu?' }),
          ev('assistant', { text: 'Xong việc chính.', final: true }),
          ev('turn_end', { status: 'completed', stepsUsed: 1 }),
          ev('finish', { status: 'completed', turn: 1 }),
          ev('notice', {
            code: 'BTW_PENDING',
            partial: false,
            count: 1,
            steerIds: [7],
            message: 'BTW_PENDING: lượt vừa xong không còn bước nào để bơm 1 câu hỏi phụ — câu hỏi sẽ '
              + 'được trả lời ở lượt kế tiếp (gửi một câu bất kỳ để mở lượt).',
          }),
        ]}
        status="completed"
        error={null}
      />,
    )
    openActivity(host)

    const notice = host.querySelector('[data-notice-code="BTW_PENDING"]') as HTMLElement | null
    expect(notice).toBeTruthy()
    expect(notice?.textContent).toContain('lượt kế tiếp')
    expect(notice!.closest('[data-turn-user="true"]')).not.toBeNull()
  })

  it('bỏ văn bản đang stream của lần thử hỏng, không dán vào câu trả lời mới', () => {
    const host = render(
      <HarnessStepView
        events={[
          ev('user', { text: 'viết kế hoạch' }),
          ev('assistant_delta', { text: 'Kế hoạch chi' }),
          ev('assistant_delta', { text: ' tiết cho' }),
          ev('notice', { code: 'UPSTREAM_RETRY', reset: true, message: 'thử lại' }),
          ev('assistant_delta', { text: 'Xin chào, đây là kế hoạch mới.' }),
          ev('assistant', { text: 'Xin chào, đây là kế hoạch mới.', final: true }),
        ]}
        status="completed"
        error={null}
      />,
    )
    openActivity(host)

    const text = (host.textContent ?? '').replace(/\s+/g, ' ')
    expect(text).toContain('Xin chào, đây là kế hoạch mới.')
    // Phần đã phát trước khi thử lại không được còn trên màn hình — và đây phải là số 0 THẬT
    // (khối đã mở), không phải số 0 vì hàng bị khối gấp giấu đi.
    expect(text).not.toContain('Kế hoạch chi tiết cho')
    expect(host.querySelectorAll('[data-timeline="assistant-text"]').length).toBe(0)
  })
})
