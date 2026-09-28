import type { ReactNode } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import {
  HarnessStepView,
  activityReceipt,
  formatMediaLabel,
  splitAuthoredSummary,
  summarizeFinalText,
} from './HarnessStepView'
import { I18nProvider } from '../../i18n'
import type { HarnessEvent } from '../../store/harnessChatStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let roots: Root[] = []
const rootByHost = new Map<HTMLElement, Root>()
let seq = 0

function ev(type: string, data: Record<string, unknown> = {}, created?: number): HarnessEvent {
  seq += 1
  return { seq, type, data, created: created ?? 1000 + seq }
}

function render(node: ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  rootByHost.set(host, root)
  act(() => {
    root.render(<I18nProvider>{node}</I18nProvider>)
  })
  return host
}

/** R1.4: render lại CHÍNH root đó (đúng nhịp poll 1200 ms của ChatPanel), không tạo cây mới. */
function rerender(host: HTMLElement, node: ReactNode) {
  const root = rootByHost.get(host)
  if (!root) throw new Error('rerender: host chưa có root')
  act(() => {
    root.render(<I18nProvider>{node}</I18nProvider>)
  })
}

// Vòng 24: lượt thật trong app luôn có `onOpenLightbox` (ChatPanel truyền xuống), nên ca về ảnh
// bằng chứng truyền một hàm rỗng để ảnh được dựng thành tile đúng như lúc chạy thật.
function renderSession(events: HarnessEvent[], onOpenLightbox?: () => void): HTMLElement {
  return render(
    <HarnessStepView events={events} status="idle" error={null} onOpenLightbox={onOpenLightbox} />,
  )
}

function click(el: Element) {
  act(() => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function timelineKinds(host: HTMLElement): string[] {
  return [...host.querySelectorAll('[data-timeline], [data-final-answer]')].map(
    (el) => el.getAttribute('data-timeline') ?? 'final-answer',
  )
}

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  rootByHost.clear()
  document.body.innerHTML = ''
  seq = 0
})

describe('HarnessStepView — F2 thứ tự thời gian', () => {
  it('renders one flat timeline in event seq order: text → tool → text → tool → final answer', () => {
    const events = [
      ev('user', { text: 'Kiểm tra log' }),
      ev('assistant_delta', { text: 'Đầu tiên tôi xem log.' }),
      ev('assistant', { text: 'Đầu tiên tôi xem log.', final: false }),
      ev('tool_start', { id: 'c1', name: 'terminal_exec', args: { command: 'tail -n 20 app.log' } }),
      ev('tool_end', { id: 'c1', name: 'terminal_exec', args: { command: 'tail -n 20 app.log' }, result: { output: 'ERROR: boom' } }),
      ev('assistant_delta', { text: 'Lỗi nằm ở dòng cuối.' }),
      ev('assistant', { text: 'Lỗi nằm ở dòng cuối.', final: false }),
      ev('tool_start', { id: 'c2', name: 'file_read', args: { path: '/home/agent/workspace/app.log' } }),
      ev('tool_end', { id: 'c2', name: 'file_read', args: { path: '/home/agent/workspace/app.log' }, result: { content: 'ERROR: boom' } }),
      ev('assistant', { text: 'Xong: lỗi ở dòng cuối của app.log.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)

    // R2 (yêu cầu 5): lượt đã xong nên khối hoạt động đang GẤP — mở nó ra rồi mới đọc thứ tự.
    click(host.querySelector('[data-activity-toggle="true"]')!)

    expect(timelineKinds(host)).toEqual([
      'assistant-text',
      'tool',
      'assistant-text',
      'tool',
      'final-answer',
    ])

    // Hai hàng tool, mỗi hàng giữ đúng vị trí của nó (không gom vào accordion/gallery).
    expect(host.querySelectorAll('[data-timeline="tool"]').length).toBe(2)
    expect(host.querySelectorAll('[data-timeline="assistant-text"]').length).toBe(2)
    // Đúng MỘT khối hoạt động cho lượt này, và câu trả lời cuối nằm NGOÀI nó.
    expect(host.querySelectorAll('[data-activity="true"]').length).toBe(1)
    const finalAnswer = host.querySelector('[data-final-answer="true"]')
    expect(finalAnswer).toBeTruthy()
    expect(finalAnswer!.closest('[data-activity="true"]')).toBeNull()
    // Văn bản giữa lượt (final:false) hiện thật, không bị mất.
    expect(host.textContent).toContain('Đầu tiên tôi xem log.')
    expect(host.textContent).toContain('Lỗi nằm ở dòng cuối.')
  })

  it('renders the image of a tool_end directly under that tool row', () => {

    const events = [
      ev('user', { text: 'Chụp màn hình' }),
      ev('tool_start', { id: 'c9', name: 'computer_screen_capture', args: {} }),
      ev('tool_end', {
        id: 'c9',
        name: 'computer_screen_capture',
        args: {},
        result: { content: 'Sandbox screenshot 1280x800', artifact: 'shots/screen.png', mime: 'image/png', dimensions: [1280, 800] },
      }),
      ev('assistant', { text: 'Đã chụp.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)
    // R2: khối hoạt động gấp khi lượt đã xong, nên mở nó trước khi tìm hàng tool.
    click(host.querySelector('[data-activity-toggle="true"]')!)

    const toolRow = host.querySelector('[data-timeline="tool"]')
    expect(toolRow).toBeTruthy()
    const mediaRow = toolRow?.querySelector('[data-tool-media="image"]')
    expect(mediaRow).toBeTruthy()
    // R1 (yêu cầu 4): hàng GẤP — có ảnh thu và nhãn thật, chưa có ảnh lớn.
    expect(mediaRow?.getAttribute('data-media-collapsed')).toBe('true')
    expect(mediaRow?.querySelector('[data-media-thumb="true"]')).toBeTruthy()
    expect(mediaRow?.querySelectorAll('[data-media-toggle="true"]').length).toBe(1)
    expect(toolRow?.querySelector('[data-media-full="true"]')).toBeNull()
    // Nhãn lấy từ dữ liệu thật (F4) — không còn "1280 × 720" hardcode.
    expect(mediaRow?.querySelector('[data-media-label="true"]')?.textContent).toBe('1280 × 800 · PNG')
    expect(host.textContent).not.toContain('1280 × 720')

    click(mediaRow!.querySelector('[data-media-toggle="true"]')!)

    expect(mediaRow?.getAttribute('data-media-collapsed')).toBeNull()
    expect(mediaRow?.querySelector('[data-media-thumb="true"]')).toBeNull()
    const fullImage = toolRow?.querySelector('[data-media-full="true"] img') as HTMLImageElement | null
    expect(fullImage).toBeTruthy()
    expect(fullImage!.getAttribute('src')).toContain('/__box/file/media?path=')
  })

  it('keeps the live streaming behaviour and reports a missing tool result honestly', () => {
    const userEvent = ev('user', { text: 'Chạy lệnh' })
    const start = ev('tool_start', { id: 'c1', name: 'terminal_exec', args: { command: 'sleep 5' } })

    const running = render(<HarnessStepView events={[userEvent, start]} status="running" error={null} />)
    expect(running.querySelector('[data-tool-pending="true"]')).toBeTruthy()
    expect(running.textContent).toContain('Running')
    expect(running.querySelector('[data-state-indicator="thinking"]')).toBeNull()

    const streaming = render(
      <HarnessStepView
        events={[userEvent, ev('assistant_delta', { text: 'Đang trả lời dần' })]}
        status="running"
        error={null}
      />,
    )
    expect(streaming.querySelector('[data-timeline="assistant-text"]')).toBeTruthy()
    expect(streaming.querySelector('[data-state-indicator="thinking"]')).toBeTruthy()

    const finished = renderSession([
      userEvent,
      start,
      ev('finish', { status: 'cancelled' }),
    ])
    expect(finished.querySelector('[data-tool-pending="true"]')).toBeNull()
    // R2: việc gấp khối không được giấu chuyện có lệnh chưa trả kết quả — biên nhận nói TRƯỚC
    // khi người dùng mở khối.
    expect(finished.querySelector('[data-activity-open="false"]')).toBeTruthy()
    expect(finished.querySelector('[data-activity-receipt="true"]')?.textContent).toContain('1 without result')

    click(finished.querySelector('[data-activity-toggle="true"]')!)

    expect(finished.querySelector('[data-tool-unfinished="true"]')).toBeTruthy()
    expect(finished.textContent).toContain('no result recorded')
  })
})

describe('HarnessStepView — F5 lượt "ma" và thời lượng', () => {
  it('does not create a turn from events that precede the first user event', () => {
    const events = [
      ev('command_resolved', { kind: 'message', command: null, invocationId: 'inv_1' }, 100),
      ev('user', { text: 'Xin chào' }, 1000),
      ev('assistant', { text: 'Chào bạn.', final: true }, 1001),
      ev('finish', { status: 'completed' }, 1001),
    ]

    const host = renderSession(events)

    expect(host.querySelectorAll('[data-turn-user="true"]').length).toBe(1)
    expect(host.querySelectorAll('[data-turn-header="true"]').length).toBe(1)
    expect(host.textContent).toContain('Xin chào')
    expect(host.textContent).toContain('Worked for 1s')
  })

  it('does not extend a finished turn with events that arrive later', () => {
    const events = [
      ev('user', { text: 'Chạy tác vụ dài' }, 1000),
      ev('assistant', { text: 'Đã dừng theo yêu cầu.', final: true }, 1010),
      ev('finish', { status: 'cancelled' }, 1036),
      // Cùng lượt nhưng tới muộn (1702s sau khi lượt đã kết thúc).
      ev('usage', { usage: { prompt_tokens: 10, completion_tokens: 2 } }, 2738),
      ev('step', { iteration: 2, contextEstimate: 1200 }, 2738),
    ]

    const host = renderSession(events)

    expect(host.textContent).toContain('Worked for 36s')
    expect(host.textContent).not.toContain('1702')
  })

  it('keeps the cancelled turn duration at the finish event, not at the late usage event', () => {
    const host = renderSession([
      ev('user', { text: 'Tác vụ bị huỷ' }, 1000),
      ev('tool_start', { id: 'c1', name: 'terminal_exec', args: { command: 'sleep 40' } }, 1005),
      ev('tool_end', { id: 'c1', name: 'terminal_exec', args: { command: 'sleep 40' }, result: { output: '' } }, 1030),
      ev('finish', { status: 'cancelled' }, 1036),
      ev('usage', { usage: { prompt_tokens: 10, completion_tokens: 2 } }, 2738),
    ])

    expect(host.textContent).toContain('Worked for 36s')
    expect(host.textContent).not.toContain('1702')
  })
})

describe('HarnessStepView — F3 suy luận trung thực', () => {
  it('shows an honest reasoning-token line instead of fabricated reasoning text', () => {
    const events = [
      ev('user', { text: 'Giải thích lỗi' }),
      ev('usage', { usage: { prompt_tokens: 1200, completion_tokens: 40, reasoning_tokens: 469 } }),
      ev('assistant', { text: 'Nguyên nhân là do thiếu biến môi trường.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)

    expect(host.textContent).toContain('469')
    expect(host.textContent).toContain('no streamed reasoning text')
    expect(host.textContent).not.toContain('Cryptographically')
    expect(host.textContent).not.toContain('Deep reasoning process executed successfully')
  })

  it('renders the real thought when the model streamed reasoning, and no fabrication otherwise', () => {
    const withThought = renderSession([
      ev('user', { text: 'Câu 1' }),
      ev('thought', { text: 'Tôi cần đọc app.log trước.' }),
      ev('assistant', { text: 'Xong.', final: true }),
      ev('finish', { status: 'completed' }),
    ])
    expect(withThought.textContent).not.toContain('Tôi cần đọc app.log trước.')
    click(withThought.querySelector('[data-thinking-toggle="true"]')!)
    expect(withThought.textContent).toContain('Tôi cần đọc app.log trước.')

    const withoutReasoning = renderSession([
      ev('user', { text: 'Câu 2' }),
      ev('usage', { usage: { prompt_tokens: 10, completion_tokens: 2 } }),
      ev('assistant', { text: 'Trả lời ngắn.', final: true }),
      ev('finish', { status: 'completed' }),
    ])
    expect(withoutReasoning.textContent).not.toContain('synthesized')
    expect(withoutReasoning.querySelector('[data-thinking-tokens="true"]')).toBeNull()
  })
})

describe('HarnessStepView — F6 tóm tắt câu trả lời cuối', () => {
  it('F6 (vòng 23) tóm tắt ngắn + nút mở chi tiết; mặt câu trả lời không có lưới ảnh của app', () => {
    const full = `${'Dòng tóm tắt nội dung trả lời. '.repeat(40)}FINAL-MARKER-END`
    const events = [
      ev('user', { text: 'Chụp màn hình rồi mô tả' }),
      ev('tool_start', { id: 'c1', name: 'computer_screen_capture', args: {} }),
      ev('tool_end', {
        id: 'c1',
        name: 'computer_screen_capture',
        args: {},
        result: { content: 'Sandbox screenshot 1280x800', mime: 'image/png', image: 'AAAA', dimensions: [1280, 800] },
      }),
      ev('assistant', { text: full, final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)

    const summaryBlock = host.querySelector('[data-final-text="summary"]')
    expect(summaryBlock).toBeTruthy()
    expect(summaryBlock!.textContent!.length).toBeLessThan(full.length)
    expect(summaryBlock!.textContent).not.toContain('FINAL-MARKER-END')

    // R3 (yêu cầu 6): nút nằm NGAY DƯỚI đoạn tóm tắt (trong cùng khung chữ của tóm tắt).
    const expander = summaryBlock!.querySelector('[data-final-expander="true"]')
    // P5.3: hai nhãn mở/gấp là chữ quanh lượt, đi theo ngôn ngữ CÂU TRẢ LỜI — lượt này trả lời
    // tiếng Việt (chuỗi `Dòng tóm tắt nội dung trả lời.` lặp lại), nên nhãn phải là tiếng Việt.
    expect(expander?.textContent).toContain('Xem chi tiết')
    expect(host.querySelectorAll('[data-final-expander="true"]').length).toBe(1)

    // Vòng 23 (D-19): mặt câu trả lời KHÔNG còn lưới ảnh do app vẽ — ở trạng thái gấp cũng vậy.
    expect(host.querySelector('[data-final-answer="true"] [data-final-media="true"]')).toBeNull()

    click(expander!)

    const expandedBlock = host.querySelector('[data-final-text="expanded"]')
    expect(expandedBlock).toBeTruthy()
    expect(expandedBlock!.textContent).toContain('FINAL-MARKER-END')

    // Mở chi tiết chỉ mở phần CHỮ; không dựng thêm lưới ảnh nào, và nút gấp nằm ngay dưới khung chữ.
    expect(host.querySelector('[data-final-media="true"]')).toBeNull()
    const collapse = host.querySelector('[data-final-expander="true"]')
    expect(collapse?.textContent).toContain('Thu gọn chi tiết')
    expect(expandedBlock!.compareDocumentPosition(collapse!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()

    // Ảnh của lượt không mất: nó vẫn nằm ngay dưới hàng công cụ của lượt, đúng một hàng media.
    click(host.querySelector('[data-activity-toggle="true"]')!)
    expect(host.querySelectorAll('[data-media-collapsed="true"]').length).toBe(1)
    expect(host.querySelector('[data-media-thumb="true"]')).toBeTruthy()
  })
})

describe('HarnessStepView — F7 thông báo nén context', () => {
  it('shows the compaction numbers at turn level and reveals detail on click', () => {
    const events = [
      ev('user', { text: 'Nén context' }),
      ev('compression', { kind: 'summary', beforeEstimate: 196608, afterEstimate: 394 }),
      ev('assistant', { text: 'Đã nén xong.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)
    // R2: lượt đã xong nên khối hoạt động gấp — mở ra trước khi tìm hàng nén.
    click(host.querySelector('[data-activity-toggle="true"]')!)

    const notice = host.querySelector('[data-timeline="compaction"]')
    expect(notice).toBeTruthy()
    expect(notice!.textContent).toContain('Context compacted: 196608 → 394 tokens')
    // Nằm ở cấp cao nhất của lượt (cùng danh sách với các hàng tool), không trong cây accordion riêng.
    expect(notice!.parentElement?.querySelector('[data-timeline="tool"]')).toBeNull()
    // Câu cũ ("không nằm trong cây Thinking") không còn đúng: khối hoạt động mới CHÍNH LÀ vùng
    // suy luận (yêu cầu 5), nên hàng nén là một hàng bên trong nó.
    expect(notice!.closest('[data-activity="true"]')).not.toBeNull()
    expect(host.querySelector('[data-compaction-detail="true"]')).toBeNull()

    click(notice!.querySelector('button')!)

    const detail = host.querySelector('[data-compaction-detail="true"]')
    expect(detail).toBeTruthy()
    expect(detail!.textContent).toContain('summary')
    expect(detail!.textContent).toContain('196608')
    expect(detail!.textContent).toContain('394')
  })

  it('uses honest wording when nothing needed compaction', () => {
    const host = renderSession([
      ev('user', { text: 'Nén context' }),
      ev('compression', { kind: 'unchanged' }),
      ev('assistant', { text: 'Không cần nén.', final: true }),
      ev('finish', { status: 'completed' }),
    ])

    // R2: lượt đã xong nên khối hoạt động gấp — mở ra rồi mới đọc hàng nén.
    click(host.querySelector('[data-activity-toggle="true"]')!)

    expect(host.querySelector('[data-timeline="compaction"]')?.textContent).toContain('No compaction needed')
  })
})

const CAPTURE_ARTIFACT = '/home/agent/workspace/.generated_artifacts/captures/screen/1789971811705-screen.png'

function captureEvents(dimensions: unknown): HarnessEvent[] {
  const result: Record<string, unknown> = { content: 'Sandbox screenshot', artifact: CAPTURE_ARTIFACT, mime: 'image/png' }
  if (dimensions !== null) result.dimensions = dimensions
  return [
    ev('user', { text: 'Chụp màn hình' }),
    ev('tool_start', { id: 'c9', name: 'computer_screen_capture', args: {} }),
    ev('tool_end', { id: 'c9', name: 'computer_screen_capture', args: {}, result }),
    ev('assistant', { text: 'Đã chụp.', final: true }),
    ev('finish', { status: 'completed' }),
  ]
}

describe('HarnessStepView — R1 ảnh chụp gấp', () => {
  it('R1.1 hàng gấp là mặc định, mở ra bằng đúng một mũi tên', () => {
    const host = renderSession(captureEvents([1280, 800]))
    click(host.querySelector('[data-activity-toggle="true"]')!)

    const mediaRow = host.querySelector('[data-tool-media="image"]') as HTMLElement | null
    expect(mediaRow).toBeTruthy()
    expect(mediaRow!.getAttribute('data-media-collapsed')).toBe('true')
    expect(mediaRow!.querySelectorAll('[data-media-toggle="true"]').length).toBe(1)
    expect(mediaRow!.querySelector('[data-media-thumb="true"]')).toBeTruthy()
    expect(mediaRow!.querySelector('[data-media-label="true"]')).toBeTruthy()
    expect(mediaRow!.querySelector('[data-media-full="true"]')).toBeNull()

    click(mediaRow!.querySelector('[data-media-toggle="true"]')!)

    expect(host.querySelector('[data-tool-media="image"]')!.getAttribute('data-media-collapsed')).toBeNull()
    const full = host.querySelector('[data-media-full="true"]') as HTMLElement | null
    expect(full).toBeTruthy()
    expect(full!.querySelector('img')?.getAttribute('src')).toContain('/__box/file/media?path=')
    expect(host.querySelector('[data-media-thumb="true"]')).toBeNull()
    // Một tài liệu chỉ hiện một lần: nhãn vẫn đúng một phần tử, giờ có thêm đường dẫn artifact.
    expect(host.querySelectorAll('[data-media-label="true"]').length).toBe(1)
    expect(host.querySelector('[data-media-label="true"]')!.textContent).toContain(CAPTURE_ARTIFACT)
  })

  it('R1.2 nhãn kích thước chỉ lấy từ payload', () => {
    const withDimensions = renderSession(captureEvents([1280, 800]))
    click(withDimensions.querySelector('[data-activity-toggle="true"]')!)
    const label = withDimensions.querySelector('[data-media-label="true"]')!.textContent ?? ''
    expect(label).toContain('1280 × 800')
    expect(label).not.toContain('1280 × 720')

    const withoutDimensions = renderSession(captureEvents(null))
    click(withoutDimensions.querySelector('[data-activity-toggle="true"]')!)
    expect(withoutDimensions.querySelector('[data-media-label="true"]')!.textContent).not.toContain('×')

    expect(formatMediaLabel({ mime: 'image/png', dimensions: null, artifactPath: 'a.png', kind: 'image' })).toBe('PNG')
  })

  it('R1.3 video cũng gấp và chỉ tạo player khi người dùng hỏi', () => {
    const events = [
      ev('user', { text: 'Ghi màn hình' }),
      ev('tool_start', { id: 'r1', name: 'computer_screen_record', args: { action: 'start' } }),
      ev('tool_end', {
        id: 'r1',
        name: 'computer_screen_record',
        args: { action: 'start' },
        result: { ok: true, recordingId: 'rec-1', path: '/home/agent/workspace/.generated_artifacts/captures/screen/1789971805978-screen.mp4' },
      }),
      ev('tool_start', { id: 'r2', name: 'computer_screen_record', args: { action: 'stop' } }),
      ev('tool_end', {
        id: 'r2',
        name: 'computer_screen_record',
        args: { action: 'stop' },
        result: { ok: true, recordingId: 'rec-1', path: '/home/agent/workspace/.generated_artifacts/captures/screen/1789971805978-screen.mp4', durationSec: 40.87, bytes: 153403 },
      }),
      ev('assistant', { text: 'Đã ghi xong màn hình.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)
    click(host.querySelector('[data-activity-toggle="true"]')!)

    expect(host.querySelectorAll('video').length).toBe(0)
    const mediaRow = host.querySelector('[data-tool-media="video"]') as HTMLElement | null
    expect(mediaRow).toBeTruthy()
    expect(mediaRow!.getAttribute('data-media-collapsed')).toBe('true')
    expect(mediaRow!.querySelector('[data-media-label="true"]')!.textContent).toBe('40.87s · MP4')
    expect(mediaRow!.querySelector('[data-media-thumb="true"]')).toBeNull()

    click(mediaRow!.querySelector('[data-media-toggle="true"]')!)

    expect(host.querySelectorAll('[data-tool-media="video"] video').length).toBe(1)
  })

  it('R1.4 ý định của người dùng thắng vòng poll', () => {
    // Mảng event gốc dựng MỘT LẦN: `seq` phải ổn định, nếu không `turn_<seq>` đổi khoá và
    // React dựng cây mới (khi đó phép đo không còn là "ý định người dùng thắng vòng poll" nữa).
    const base = [
      ev('user', { text: 'Chụp màn hình' }),
      ev('tool_start', { id: 'c9', name: 'computer_screen_capture', args: {} }),
      ev('tool_end', {
        id: 'c9',
        name: 'computer_screen_capture',
        args: {},
        result: { artifact: CAPTURE_ARTIFACT, mime: 'image/png', dimensions: [1280, 800] },
      }),
    ]
    const running = (extra: HarnessEvent[]) => (
      <HarnessStepView events={[...base, ...extra]} status="running" error={null} />
    )
    const nextPoll = ev('tool_start', { id: 'c10', name: 'terminal_exec', args: { command: 'echo hi' } })

    const host = render(running([]))
    click(host.querySelector('[data-media-toggle="true"]')!)
    expect(host.querySelector('[data-media-full="true"]')).toBeTruthy()

    // Vòng poll 1200 ms của ChatPanel render lại CÙNG root — ý định người dùng phải được giữ.
    rerender(host, running([nextPoll]))

    expect(host.querySelector('[data-media-full="true"]')).toBeTruthy()
    expect(host.querySelector('[data-media-thumb="true"]')).toBeNull()
  })
})

describe('HarnessStepView — R2 một khối hoạt động', () => {
  const mixedTurn = [
    ev('user', { text: 'Làm việc' }),
    ev('thought', { text: 'Tôi nên đọc app.log trước.' }),
    ev('assistant_delta', { text: 'Tôi xem log trước.' }),
    ev('assistant', { text: 'Tôi xem log trước.', final: false }),
    ev('tool_start', { id: 'c1', name: 'terminal_exec', args: { command: 'tail -n 20 app.log' } }),
    ev('tool_end', { id: 'c1', name: 'terminal_exec', args: { command: 'tail -n 20 app.log' }, result: { output: 'ERROR: boom' } }),
    ev('notice', { code: 'UPSTREAM_RETRY', message: 'thử lại' }),
    ev('compression', { kind: 'summary', beforeEstimate: 196608, afterEstimate: 394 }),
    ev('assistant', { text: 'Xong.', final: true }),
    ev('finish', { status: 'completed' }),
  ]

  it('R2.1 mọi hàng của lượt nằm trong khối, câu trả lời cuối nằm ngoài', () => {
    const host = renderSession(mixedTurn)
    click(host.querySelector('[data-activity-toggle="true"]')!)

    const activity = host.querySelector('[data-activity="true"]')
    expect(host.querySelectorAll('[data-activity="true"]').length).toBe(1)
    const rows = [...host.querySelectorAll('[data-timeline]')]
    expect(rows.length).toBeGreaterThanOrEqual(4)
    for (const row of rows) expect(row.closest('[data-activity="true"]')).not.toBeNull()
    expect(activity!.querySelectorAll('[data-timeline]').length).toBe(rows.length)
    expect(host.querySelector('[data-final-answer="true"]')!.closest('[data-activity="true"]')).toBeNull()
  })

  it('R2.2 lượt đã xong thì gấp còn dòng biên nhận, bấm thì mở đúng thứ tự cũ', () => {
    const host = renderSession(mixedTurn)

    expect(host.querySelector('[data-activity="true"]')!.getAttribute('data-activity-open')).toBe('false')
    expect(host.querySelectorAll('[data-timeline]').length).toBe(0)
    expect(host.querySelector('[data-turn-header="true"]')).toBeTruthy()
    // Chỉ tiêu 4 của kế hoạch, đọc thẳng trên DOM: `Thinking · …` — văn bản suy luận THẬT đứng đầu
    // dòng biên nhận, dù lượt đang gấp (đây là chỗ chống giấu bằng chứng).
    expect(host.querySelector('[data-activity-receipt="true"]')!.textContent).toBe('Thinking · 1 command')

    click(host.querySelector('[data-activity-toggle="true"]')!)

    expect(host.querySelector('[data-activity="true"]')!.getAttribute('data-activity-open')).toBe('true')
    expect(timelineKinds(host)).toEqual(['assistant-text', 'tool', 'notice', 'compaction', 'final-answer'])

    click(host.querySelector('[data-activity-toggle="true"]')!)

    expect(host.querySelector('[data-activity="true"]')!.getAttribute('data-activity-open')).toBe('false')
    expect(host.querySelectorAll('[data-timeline]').length).toBe(0)
  })

  it('R2.3 lượt đang chạy thì khối mở, và biên nhận cập nhật khi hàng mới tới', () => {
    const running = (events: HarnessEvent[]) => (
      <HarnessStepView events={events} status="running" error={null} />
    )
    const first = [
      ev('user', { text: 'Chạy hai lệnh' }),
      ev('tool_start', { id: 'c1', name: 'terminal_exec', args: { command: 'echo 1' } }),
      ev('tool_end', { id: 'c1', name: 'terminal_exec', args: { command: 'echo 1' }, result: { output: '1' } }),
    ]

    const host = render(running(first))
    expect(host.querySelector('[data-activity="true"]')!.getAttribute('data-activity-open')).toBe('true')
    expect(host.querySelector('[data-activity-toggle="true"]')!.textContent).toContain('Working...')
    expect(host.querySelector('[data-activity-receipt="true"]')!.textContent).toContain('1 command')
    expect(host.querySelectorAll('[data-timeline="tool"]').length).toBe(1)

    rerender(host, running([
      ...first,
      ev('tool_start', { id: 'c2', name: 'terminal_exec', args: { command: 'echo 2' } }),
      ev('tool_end', { id: 'c2', name: 'terminal_exec', args: { command: 'echo 2' }, result: { output: '2' } }),
    ]))

    expect(host.querySelector('[data-activity="true"]')!.getAttribute('data-activity-open')).toBe('true')
    expect(host.querySelector('[data-activity-receipt="true"]')!.textContent).toContain('2 commands')
    expect(host.querySelectorAll('[data-timeline="tool"]').length).toBe(2)
  })

  it('R2.4 dòng biên nhận đếm đúng và giữ đúng thứ tự đoạn', () => {
    expect(activityReceipt({ thinking: true, commands: 6, captures: 2, failed: 1, unfinished: 0 })).toEqual([
      { label: 'Thinking', tone: 'muted' },
      { label: '6 commands', tone: 'muted' },
      { label: '2 captures', tone: 'muted' },
      { label: '1 failed', tone: 'rose' },
    ])
    expect(activityReceipt({ thinking: false, commands: 1, captures: 1, failed: 0, unfinished: 0 })).toEqual([
      { label: '1 command', tone: 'muted' },
      { label: '1 capture', tone: 'muted' },
    ])
    expect(activityReceipt({ thinking: false, commands: 0, captures: 0, failed: 0, unfinished: 2 })).toEqual([
      { label: '2 without result', tone: 'amber' },
    ])
    expect(activityReceipt({ thinking: false, commands: 0, captures: 0, failed: 0, unfinished: 0 })).toEqual([])
  })
})

describe('HarnessStepView — R3 tách tóm tắt / chi tiết', () => {
  const AUTHORED = 'Xong — đã sửa lỗi múi giờ.\n\n## Diễn biến\n| Bước | Việc |\n| --- | --- |\n| 1 | sửa |\n'

  // Đường dẫn ảnh bằng chứng do model tự viết trong câu trả lời (tương đối gốc workspace), dùng cho
  // hai ca vòng 24: tóm tắt là đoạn mở bài, và ảnh bằng chứng đóng thân câu trả lời.
  const ANSWER_CAPTURE = '.generated_artifacts/captures/tab/2e4f1a20/2e4f1a20_007_tab-runs-page.png'

  it('R3.1 đoạn đầu nguyên văn là tóm tắt, phần còn lại trả về nguyên vẹn', () => {
    expect(splitAuthoredSummary(AUTHORED)).toEqual({
      summary: 'Xong — đã sửa lỗi múi giờ.',
      rest: '## Diễn biến\n| Bước | Việc |\n| --- | --- |\n| 1 | sửa |',
    })
    expect(splitAuthoredSummary('Câu một.\nCâu hai.\nCâu ba.\n\nPhần sau.')).toEqual({
      summary: 'Câu một.\nCâu hai.\nCâu ba.',
      rest: 'Phần sau.',
    })
  })

  it('R3.2 không có dòng trống (một đoạn dài) thì không nhận là tóm tắt', () => {
    const oneBlock = 'Dòng tóm tắt nội dung trả lời. '.repeat(40) + 'HET'
    expect(splitAuthoredSummary(oneBlock)).toBeNull()
    expect(splitAuthoredSummary('Chỉ một đoạn.\n\n')).toBeNull()
  })

  it('R3.3 đoạn đầu là tiêu đề, bảng hay danh sách thì không nhận', () => {
    expect(splitAuthoredSummary('# Tiêu đề\n\nPhần sau.')).toBeNull()
    expect(splitAuthoredSummary('| a | b |\n| --- | --- |\n\nPhần sau.')).toBeNull()
    expect(splitAuthoredSummary('- việc một\n- việc hai\n\nPhần sau.')).toBeNull()
  })

  it('R3.4 đoạn kết giữa câu thì lùi về mốc câu cuối, không có mốc nào thì không nhận', () => {
    expect(splitAuthoredSummary('Bước 1 xong. Bước 2 đang\n\nPhần sau.')).toEqual({
      summary: 'Bước 1 xong.',
      rest: 'Phần sau.',
    })
    expect(splitAuthoredSummary('Bước 1 xong nhưng\n\nPhần sau.')).toBeNull()
  })

  it('R3.5 lát cắt không kết thúc trong khối ``` chưa đóng', () => {
    const text = [
      'Dòng một.',
      'Dòng hai.',
      'Dòng ba.',
      'Dòng bốn.',
      'Dòng năm.',
      '```bash',
      'echo hien-nguyen-van',
      'echo con-nua',
      '```',
    ].join('\n')

    const { summary, truncated } = summarizeFinalText(text)

    expect(truncated).toBe(true)
    expect(summary).not.toContain('```')
    expect(summary).not.toContain('hien-nguyen-van')
    expect(summary).toContain('Dòng năm.')
  })

  it('R3.6 lát cắt không giữ nửa hàng bảng', () => {
    // Lát cắt cũ bị cắt theo KÝ TỰ (600) và rơi vào giữa hàng bảng thứ ba: phần còn lại là
    // một hàng bảng chưa trọn, phải bị bỏ để bảng không hiện ra sai.
    const text = ['| Bước | Việc |', '| --- | --- |', `| 1 | ${'x'.repeat(700)} |`].join('\n')

    const { summary, truncated } = summarizeFinalText(text)

    expect(truncated).toBe(true)
    expect(summary).not.toContain('| 1 |')
    // `…` là dấu của lát cắt, không phải nội dung model viết.
    expect(summary).toBe('| Bước | Việc |\n| --- | --- |…')
  })

  it('R3.7 trong DOM: tóm tắt là đoạn đầu nguyên văn, phần còn lại chỉ hiện khi bấm', () => {
    const events = [
      ev('user', { text: 'Sửa lỗi' }),
      ev('assistant', { text: AUTHORED, final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)
    const summaryBlock = host.querySelector('[data-final-text="summary"]')!
    expect(summaryBlock.textContent).toContain('Xong — đã sửa lỗi múi giờ.')
    expect(summaryBlock.textContent).not.toContain('Diễn biến')
    expect(summaryBlock.textContent).not.toContain('|')
    expect(summaryBlock.textContent).not.toContain('…')
    // Nút nằm ngay trong khung chữ của tóm tắt (dưới đoạn đó), không phải sau một khối khác.
    expect(summaryBlock.querySelector('[data-final-expander="true"]')).toBeTruthy()

    click(summaryBlock.querySelector('[data-final-expander="true"]')!)

    const expanded = host.querySelector('[data-final-text="expanded"]')!
    expect(expanded.textContent).toContain('Diễn biến')
    expect(expanded.querySelector('[data-final-expander="true"]')).toBeNull()
    expect(host.querySelector('[data-final-expander="true"]')!.textContent).toContain('Thu gọn chi tiết')
  })

  it('F6 (vòng 23) hai nhãn mở/gấp đi theo ngôn ngữ câu trả lời, không còn chữ Anh viết cứng', () => {
    const full = `${'Summary line of the answer body. '.repeat(40)}FINAL-MARKER-END`
    const host = renderSession([
      ev('user', { text: 'Explain the change' }),
      ev('assistant', { text: full, final: true }),
      ev('finish', { status: 'completed' }),
    ])

    // Cùng một component, câu trả lời tiếng Anh ⇒ nhãn tiếng Anh; tiếng Việt ⇒ nhãn tiếng Việt
    // (hai ca tiếng Việt ở F6/R3.7 phía trên). Nhãn KHÔNG còn là hằng số trong mã.
    const expander = host.querySelector('[data-final-expander="true"]')!
    expect(expander.textContent).toContain('View details')
    expect(expander.textContent).not.toContain('Xem chi tiết')

    click(expander)

    expect(host.querySelector('[data-final-expander="true"]')!.textContent).toContain('Hide details')
  })

  it('R3.8 (vòng 23) lượt chỉ có ảnh, không có phần chữ nào để mở: mặt câu trả lời không dựng nút nào', () => {
    const events = [
      ev('user', { text: 'Chụp màn hình' }),
      ev('tool_start', { id: 'c9', name: 'computer_screen_capture', args: {} }),
      ev('tool_end', {
        id: 'c9',
        name: 'computer_screen_capture',
        args: {},
        result: { artifact: CAPTURE_ARTIFACT, mime: 'image/png', dimensions: [1280, 800] },
      }),
      ev('assistant', { text: 'Đã chụp.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)
    expect(host.querySelector('[data-final-text="summary"]')).toBeTruthy()
    // D-19: nút "xem chi tiết" chỉ có nghĩa khi có PHẦN CHỮ bị cắt. Ảnh không còn là "phần bên dưới"
    // của câu trả lời (D-22 đưa ảnh vào chính mạch chữ của model), nên lượt này không có nút nào.
    expect(host.querySelector('[data-final-expander="true"]')).toBeNull()
    expect(host.querySelector('[data-final-media="true"]')).toBeNull()

    // Ảnh không mất: vẫn đúng một hàng media ngay dưới hàng công cụ của lượt.
    click(host.querySelector('[data-activity-toggle="true"]')!)
    expect(host.querySelectorAll('[data-media-collapsed="true"]').length).toBe(1)
    expect(host.querySelector('[data-media-thumb="true"]')).toBeTruthy()
  })

  it('R3.9 câu trả lời ngắn, không ảnh, không phần còn lại: nút KHÔNG tồn tại', () => {
    const host = renderSession([
      ev('user', { text: 'Câu hỏi ngắn' }),
      ev('assistant', { text: 'Trả lời ngắn.', final: true }),
      ev('finish', { status: 'completed' }),
    ])

    expect(host.querySelector('[data-final-text="summary"]')).toBeTruthy()
    expect(host.querySelector('[data-final-expander="true"]')).toBeNull()
  })

  it('F6 (vòng 24) lượt có việc: mở bài MỘT đoạn văn xuôi, thân kết bằng ẢNH bằng chứng', () => {
    // Dạng chủ nhà chốt (D-29/D-30): đoạn văn xuôi đầu là TÓM TẮT hiện trên chat; phần model tự chọn
    // — kể cả ảnh bằng chứng ĐÓNG THÂN câu trả lời — chỉ hiện khi bấm "Xem chi tiết".
    const lead = 'Đã gắn xong gói bằng chứng sống vào lượt này.'
    const body = [
      '## Đã làm.',
      '- chạy `pytest -q` trên bộ kiểm của lượt (exit 0)',
      '- sửa `frontend/src/components/chat/HarnessStepView.tsx`',
      '',
      `![Bảng chạy đã đổi nhãn](${ANSWER_CAPTURE})`,
    ].join('\n')
    const text = `${lead}\n\n${body}`

    // Hợp đồng tách: đoạn đầu NGUYÊN VĂN là tóm tắt, phần còn lại (kết bằng ảnh) giữ nguyên.
    expect(splitAuthoredSummary(text)).toEqual({ summary: lead, rest: body })

    const events = [
      ev('user', { text: 'Làm nốt phần bằng chứng' }),
      ev('assistant', { text, final: true }),
      ev('finish', { status: 'completed' }),
    ]
    const host = renderSession(events, () => {})

    const summaryBlock = host.querySelector('[data-final-text="summary"]')!
    // Tóm tắt ĐÚNG đoạn mở bài: không mục, không ảnh, không chữ nào của phần sau.
    expect(summaryBlock.querySelector('p')?.textContent).toBe(lead)
    expect(summaryBlock.textContent).not.toContain('Đã làm.')
    expect(host.querySelector('[data-final-answer="true"] [data-capture-tile="true"]')).toBeNull()
    expect(summaryBlock.querySelector('[data-final-expander="true"]')).toBeTruthy()

    click(summaryBlock.querySelector('[data-final-expander="true"]')!)

    const expanded = host.querySelector('[data-final-text="expanded"]')!
    expect(expanded.textContent).toContain('Đã làm.')
    const tile = expanded.querySelector('[data-capture-tile="true"]')
    expect(tile).toBeTruthy()
    // D-30: khối CUỐI của thân câu trả lời là ảnh bằng chứng, không phải chữ.
    const blocks = [...expanded.querySelectorAll('p, h1, h2, h3, ul, ol, table, pre, blockquote')]
    expect(blocks[blocks.length - 1]?.contains(tile!)).toBe(true)
  })

  it('F6 (vòng 24) mở bài bằng TIÊU ĐỀ: không nhận tóm tắt model viết, rơi về lát cắt cũ (ghim nguyên trạng)', () => {
    // Ghim NGUYÊN TRẠNG hành vi cũ: đoạn đầu không phải văn xuôi ⇒ `splitAuthoredSummary` trả `null`
    // và `summarizeFinalText` quay về lát cắt 6 dòng/600 ký tự. Vòng 24 cố ý KHÔNG nới luật này
    // (kế hoạch §7: giảm thiểu bằng luật trong kỹ năng `final-report`), nên đây là bài chống trôi.
    const headed = [
      '# Báo cáo lượt',
      '',
      'Đoạn thân thứ nhất.',
      'Đoạn thân thứ hai.',
      'Dòng ba của thân.',
      'Dòng bốn của thân.',
      'Dòng năm của thân.',
      '',
      `![Bảng chạy đã đổi nhãn](${ANSWER_CAPTURE})`,
      'HET-CUOI-CUNG',
    ].join('\n')
    const sixLines = headed.split('\n').slice(0, 6).join('\n')

    expect(splitAuthoredSummary(headed)).toBeNull()
    expect(summarizeFinalText(headed)).toEqual({ summary: `${sixLines}…`, truncated: true })

    const events = [
      ev('user', { text: 'Báo cáo lượt này' }),
      ev('assistant', { text: headed, final: true }),
      ev('finish', { status: 'completed' }),
    ]
    const host = renderSession(events, () => {})

    const summaryBlock = host.querySelector('[data-final-text="summary"]')!
    expect(summaryBlock.textContent).toContain('Dòng bốn của thân.')
    expect(summaryBlock.textContent).toContain('…')
    expect(summaryBlock.textContent).not.toContain('Dòng năm của thân.')
    expect(summaryBlock.textContent).not.toContain('HET-CUOI-CUNG')
    expect(summaryBlock.querySelector('[data-final-expander="true"]')).toBeTruthy()

    click(summaryBlock.querySelector('[data-final-expander="true"]')!)

    const expanded = host.querySelector('[data-final-text="expanded"]')!
    expect(expanded.textContent).toContain('HET-CUOI-CUNG')
    expect(expanded.querySelector('[data-capture-tile="true"]')).toBeTruthy()
  })
})

/**
 * Vòng 27 / C-5 — can thiệp giữa lúc chạy. Harness phát event `user` với `{control:true, steer:true}`
 * cho câu chủ nhà gõ trong lúc lượt đang chạy (nó KHÔNG đếm thêm lượt), và phát event `child` với
 * `{cancelledBy:'owner'}` khi một nhánh bị dừng bằng `cancel_child`.
 *
 * Hai luật của giao diện:
 *  1. chỉ thị nằm ĐÚNG chỗ nó được gửi trong mạch đọc (theo `seq`) kèm nhãn nhỏ "can thiệp";
 *  2. nhánh bị chủ nhà dừng đọc là "chủ nhà dừng", không phải "lỗi".
 */
describe('HarnessStepView — C-5 can thiệp giữa lúc chạy', () => {
  it('chỉ thị giữa lượt là bong bóng của chủ nhà ở đúng vị trí, kèm nhãn "can thiệp", không mở lượt mới', () => {
    const events = [
      ev('user', { text: 'Nhờ em nghiên cứu chuyển tuyến' }),
      ev('tool_start', { id: 't1', name: 'web_search' }),
      ev('user', { text: 'dừng nhánh luật, hạ các nhánh còn lại xuống mức 2', steer: true, control: true }),
      ev('assistant', { text: 'Đã nhận chỉ thị giữa lượt', final: false }),
    ]
    const host = renderSession(events)

    // Đúng MỘT lượt: chỉ thị không mở lượt mới (harness cũng không tăng `_turn_index`).
    expect(host.querySelectorAll('[data-turn-user="true"]').length).toBe(1)

    const steer = host.querySelector('[data-timeline="owner-steer"]')
    expect(steer).toBeTruthy()
    expect(steer?.textContent).toContain('dừng nhánh luật, hạ các nhánh còn lại xuống mức 2')
    expect(steer?.querySelector('[data-testid="owner-steer-label"]')?.textContent).toBe('steering')

    // ...và nó nằm ở ĐÚNG vị trí thời gian: giữa hàng tool và văn bản sau đó.
    const activity = host.querySelector('[data-activity="true"]')
    const order = [...(activity?.querySelectorAll('[data-timeline]') ?? [])].map((el) =>
      el.getAttribute('data-timeline'),
    )
    expect(order).toEqual(['tool', 'owner-steer', 'assistant-text'])
  })

  it('nhánh bị chủ nhà dừng đọc là "chủ nhà dừng", không phải lỗi', () => {
    const events = [
      ev('user', { text: 'Nhờ em nghiên cứu chuyển tuyến' }),
      ev('child', { sessionId: 'child-77', role: 'research', status: 'failed', reason: 'OWNER_CANCELLED', cancelledBy: 'owner', is_error: false }),
    ]
    const host = renderSession(events)

    const chip = host.querySelector('[data-timeline="child"]')
    expect(chip?.textContent).toContain('stopped by the owner')
    expect(chip?.textContent).not.toContain('failed')
  })

  it('câu hỏi phụ của `/btw` giữa lượt mang nhãn riêng, không phải nhãn "can thiệp"', () => {
    // P5 — `btw` đi cùng đường steer nhưng KHÔNG phải một chỉ thị: cùng chỗ đứng, khác nhãn,
    // và vẫn đúng MỘT lượt (câu hỏi phụ không mở lượt mới).
    const events = [
      ev('user', { text: 'Nhờ em nghiên cứu chuyển tuyến' }),
      ev('tool_start', { id: 't1', name: 'web_search' }),
      ev('user', { text: 'pin này đọc ở đâu?', steer: true, control: true, btw: true }),
      ev('assistant', { text: 'Trả lời ngắn ở bước kế', final: false }),
    ]
    const host = renderSession(events)

    expect(host.querySelectorAll('[data-turn-user="true"]').length).toBe(1)
    const row = host.querySelector('[data-timeline="owner-steer"][data-btw="true"]')
    expect(row).toBeTruthy()
    expect(row?.textContent).toContain('pin này đọc ở đâu?')
    expect(row?.querySelector('[data-testid="owner-btw-label"]')?.textContent).toBe('btw')
    expect(row?.querySelector('[data-testid="owner-steer-label"]')).toBeNull()
  })

  it('lượt rảnh của `/btw` mang nhãn "btw" trên hàng của chủ nhà', () => {
    const events = [
      ev('user', { text: 'pin này đọc ở đâu?', btw: true }),
      ev('assistant', { text: 'Câu trả lời ngắn', final: true }),
      ev('finish', { status: 'completed' }),
    ]
    const host = renderSession(events)

    expect(host.querySelector('[data-testid="user-btw-label"]')?.textContent).toBe('btw')
    expect(host.querySelectorAll('[data-turn-user="true"]').length).toBe(1)
    expect(host.querySelector('[data-testid="owner-btw-label"]')).toBeNull()
  })
})

describe('HarnessStepView — Luồng suy luận và Tool xen kẽ (Interleaved Thinking & Tools)', () => {
  it('suy luận và tool hiển thị xen kẽ theo đúng trình tự thời gian seq', () => {
    const events = [
      ev('user', { text: 'Mở Youtube Shorts và lướt 5 video' }),
      ev('thought', { text: 'Bước 1: Mở trình duyệt vào shorts.' }),
      ev('tool_start', { id: 't1', name: 'browser_action', args: { action: 'open' } }),
      ev('tool_end', { id: 't1', name: 'browser_action', args: { action: 'open' }, result: { ok: true } }),
      ev('thought', { text: 'Bước 2: Lướt video short 1 và 2.' }),
      ev('tool_start', { id: 't2', name: 'browser_action', args: { action: 'scroll' } }),
      ev('tool_end', { id: 't2', name: 'browser_action', args: { action: 'scroll' }, result: { ok: true } }),
      ev('tool_start', { id: 't3', name: 'computer_screen_capture', args: {} }),
      ev('tool_end', { id: 't3', name: 'computer_screen_capture', args: {}, result: { ok: true } }),
      ev('thought', { text: 'Bước 3: Hoàn thành tác vụ.' }),
      ev('assistant', { text: 'Đã xem xong 5 video shorts.', final: true }),
      ev('finish', { status: 'completed' }),
    ]

    const host = renderSession(events)
    // Mở khối activity để xem nội dung
    click(host.querySelector('[data-activity-toggle="true"]')!)

    const activity = host.querySelector('[data-activity="true"]')
    expect(activity).toBeTruthy()

    // Kiểm tra các phần tử bên trong activity xuất hiện đúng thứ tự:
    // Thought 1 -> Tool 1 -> Thought 2 -> Group Header (Executed 2 commands) -> Thought 3
    const textContent = activity?.textContent ?? ''
    const idxThought1 = textContent.indexOf('Bước 1: Mở trình duyệt vào shorts.')
    const idxTool1 = textContent.indexOf('browser_action')
    const idxThought2 = textContent.indexOf('Bước 2: Lướt video short 1 và 2.')
    const idxGroupHeader = textContent.indexOf('Executed 2 commands')
    const idxThought3 = textContent.indexOf('Bước 3: Hoàn thành tác vụ.')

    expect(idxThought1).toBeGreaterThanOrEqual(0)
    expect(idxTool1).toBeGreaterThan(idxThought1)
    expect(idxThought2).toBeGreaterThan(idxTool1)
    expect(idxGroupHeader).toBeGreaterThan(idxThought2)
    expect(idxThought3).toBeGreaterThan(idxGroupHeader)

    // Khối group header có mặt với số lượng 2
    const groupHeader = host.querySelector('[data-tool-group-header="true"]')
    expect(groupHeader).toBeTruthy()
    expect(groupHeader?.textContent).toContain('Executed 2 commands')
  })
})

