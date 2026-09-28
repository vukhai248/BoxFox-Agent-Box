/**
 * BUG-39 + BUG-40 (kế hoạch v1 Phần A, A1/A2/A9) — đo bằng cơ chế, không bằng ảnh.
 *
 * A1: popover `+` render qua `createPortal` vào `document.body`. Bản cũ đặt
 * `absolute` trong hàng công cụ `overflow-hidden` của `ChatInputBar.tsx`, nên
 * `document.elementFromPoint` tại tâm mục menu trả về khung chat — mục "Tải lên
 * tệp tin" KHÔNG bấm được dù có trong DOM. jsdom không có `elementFromPoint`
 * (đã đo: `typeof document.elementFromPoint === 'undefined'`), nên ở đây khẳng
 * định **cơ chế** khiến hit-test đúng — panel nằm ngoài cây DOM của tổ tiên cắt
 * và không có tổ tiên `overflow-hidden` nào; phép hit-test thật chạy trên máy
 * sống qua `agent-browser` (kế hoạch § A.2 bước 1).
 *
 * A2: `AttachedFile` giữ đối tượng `File` thật + `sizeBytes`/`relativePath`, và
 * trần phía client (25 MB/tệp, 20 tệp/lượt, 100 MB/lượt) chặn trước khi gửi.
 *
 * A9: mục Google Drive KHÔNG còn tạo tệp giả; nó nói thẳng "chưa kết nối".
 */
import type { ReactNode } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AttachmentPicker, type AttachedFile } from './AttachmentPicker'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let roots: Root[] = []
let clipper: HTMLDivElement

/** Dựng lại đúng ca sống: picker nằm trong hàng công cụ `overflow-hidden`. */
function renderClipped(node: ReactNode): HTMLElement {
  const host = document.createElement('div')
  clipper = document.createElement('div')
  clipper.className = 'flex min-w-0 items-center gap-1.5 overflow-hidden'
  document.body.append(host)
  host.append(clipper)
  const root = createRoot(clipper)
  roots.push(root)
  act(() => {
    root.render(node)
  })
  return host
}

function click(el: Element | null | undefined) {
  act(() => {
    el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function pressKey(key: string) {
  act(() => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  })
}

function mousedownOn(target: Element | null) {
  act(() => {
    target?.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
  })
}

/** Gán `FileList` cho input ẩn rồi bắn `change` — React đọc qua `onChange`. */
function setFiles(input: HTMLInputElement, files: File[]) {
  Object.defineProperty(input, 'files', { value: files, configurable: true })
  act(() => {
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

function triggerButton(host: HTMLElement): HTMLButtonElement {
  return host.querySelector('button[title="Thêm đính kèm / Tệp tin / Hình ảnh"]') as HTMLButtonElement
}

function menu(): HTMLElement | null {
  return document.querySelector('[data-testid="attach-menu"]')
}

function menuItems(): HTMLButtonElement[] {
  const panel = menu()
  return panel ? Array.from(panel.querySelectorAll('button')) : []
}

/** FileReader của ảnh chạy ở task riêng — chờ tối đa 1 s cho callback. */
async function waitFor(check: () => boolean) {
  for (let i = 0; i < 50; i += 1) {
    if (check()) return
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20))
    })
  }
}

function folderFile(name: string, relativePath: string, body = 'x'): File {
  const file = new File([body], name, { type: 'text/plain' })
  Object.defineProperty(file, 'webkitRelativePath', { value: relativePath, configurable: true })
  return file
}

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

describe('AttachmentPicker — A1: popover không bị cắt (BUG-39)', () => {
  it('menu render qua portal ngoài tổ tiên overflow-hidden, không tổ tiên nào cắt được', () => {
    const onAttach = vi.fn()
    const host = renderClipped(<AttachmentPicker onAttach={onAttach} />)

    expect(menu()).toBeNull()
    click(triggerButton(host))

    const panel = menu()
    expect(panel).not.toBeNull()
    // Cơ chế của A1: panel không nằm trong cây DOM của hàng công cụ.
    expect(clipper.contains(panel!)).toBe(false)
    expect(panel!.closest('.overflow-hidden')).toBeNull()
    expect(document.body.contains(panel!)).toBe(true)
    // Vị trí do picker tự tính (fixed), không phụ thuộc layout của tổ tiên.
    expect(panel!.style.left).not.toBe('')
    expect(panel!.style.bottom).not.toBe('')
    expect(panel!.className).toContain('fixed')
  })

  it('các mục menu đều có mặt và bấm được (không mục nào nằm ngoài panel)', () => {
    const onAttach = vi.fn()
    const host = renderClipped(<AttachmentPicker onAttach={onAttach} />)
    click(triggerButton(host))

    const items = menuItems()
    expect(items.length).toBeGreaterThanOrEqual(4)
    const text = menu()?.textContent ?? ''
    expect(text).toContain('Files & folders')
    expect(text).toContain('Repositories')
    expect(text).toContain('Google Drive')
    for (const item of items) {
      // Mỗi mục phải là con của panel đang nằm trên body — tức là điểm bấm rơi
      // vào panel, không rơi vào khung chat như BUG-39.
      expect(panel_contains(item)).toBe(true)
    }
  })

  it('Escape đóng menu', () => {
    const host = renderClipped(<AttachmentPicker onAttach={vi.fn()} />)
    click(triggerButton(host))
    expect(menu()).not.toBeNull()

    pressKey('Escape')
    expect(menu()).toBeNull()
  })

  it('click ra ngoài đóng menu; click trong panel không đóng', () => {
    const host = renderClipped(<AttachmentPicker onAttach={vi.fn()} />)
    click(triggerButton(host))

    mousedownOn(menuItems()[0])
    expect(menu()).not.toBeNull()

    mousedownOn(document.body)
    expect(menu()).toBeNull()
  })

  it('bấm lại nút [+] đóng menu (ngoài-click kiểm cả trigger)', () => {
    const host = renderClipped(<AttachmentPicker onAttach={vi.fn()} />)
    const trigger = triggerButton(host)
    click(trigger)
    expect(menu()).not.toBeNull()

    // Trình duyệt bắn mousedown TRƯỚC click: nếu chỉ kiểm panelRef thì mousedown
    // đóng rồi click mở lại — menu không bao giờ tắt.
    mousedownOn(trigger)
    click(trigger)
    expect(menu()).toBeNull()
  })

  it('khi nằm trong chat-input-bar, menu lấy đúng bề rộng width và left của thanh chat', () => {
    const host = document.createElement('div')
    const chatBar = document.createElement('div')
    chatBar.setAttribute('data-testid', 'chat-input-bar')
    chatBar.getBoundingClientRect = () => ({
      left: 200,
      top: 500,
      width: 600,
      height: 100,
      right: 800,
      bottom: 600,
      x: 200,
      y: 500,
      toJSON: () => {},
    })
    document.body.append(host)
    host.append(chatBar)
    const root = createRoot(chatBar)
    roots.push(root)
    act(() => {
      root.render(<AttachmentPicker onAttach={vi.fn()} />)
    })

    click(triggerButton(host))
    const panel = menu()
    expect(panel).not.toBeNull()
    expect(panel!.style.width).toBe('600px')
    expect(panel!.style.left).toBe('200px')
  })
})

function panel_contains(item: Element): boolean {
  const panel = menu()
  return Boolean(panel && panel.contains(item))
}

describe('AttachmentPicker — A2: giữ File thật + trần phía client', () => {
  it('tệp lẻ: giữ đúng đối tượng File, sizeBytes, không có relativePath', () => {
    const seen: AttachedFile[] = []
    const host = renderClipped(<AttachmentPicker onAttach={(file) => seen.push(file)} />)
    click(triggerButton(host))

    const file = new File(['hello box'], 'notes.md', { type: 'text/markdown' })
    setFiles(host.querySelector('[data-testid="attach-file-input"]') as HTMLInputElement, [file])

    expect(seen).toHaveLength(1)
    expect(seen[0].name).toBe('notes.md')
    expect(seen[0].file).toBeInstanceOf(File)
    expect(seen[0].file).toBe(file)
    expect(seen[0].sizeBytes).toBe(file.size)
    expect(seen[0].relativePath).toBeUndefined()
  })

  it('ảnh: vẫn giữ dataUrl (VLM) VÀ giữ File thật (nội dung phải tới box)', async () => {
    const seen: AttachedFile[] = []
    const host = renderClipped(<AttachmentPicker onAttach={(file) => seen.push(file)} />)
    click(triggerButton(host))

    const file = new File([new Uint8Array([137, 80, 78, 71])], 'shot.png', { type: 'image/png' })
    setFiles(host.querySelector('[data-testid="attach-image-input"]') as HTMLInputElement, [file])
    await waitFor(() => seen.length > 0)

    expect(seen).toHaveLength(1)
    expect(seen[0].dataUrl?.startsWith('data:image/png;base64,')).toBe(true)
    expect(seen[0].file).toBe(file)
    expect(seen[0].sizeBytes).toBe(file.size)
  })

  it('thư mục: relativePath lấy từ webkitRelativePath (giữ cây, không làm phẳng)', () => {
    const seen: AttachedFile[] = []
    const host = renderClipped(<AttachmentPicker onAttach={(file) => seen.push(file)} />)
    click(triggerButton(host))

    setFiles(host.querySelector('[data-testid="attach-folder-input"]') as HTMLInputElement, [
      folderFile('a.ts', 'proj/src/a.ts'),
    ])

    expect(seen).toHaveLength(1)
    expect(seen[0].relativePath).toBe('proj/src/a.ts')
    expect(seen[0].file).toBeInstanceOf(File)
  })

  it('tệp 26 MiB bị chặn: không có chip, có dòng lỗi trong menu', () => {
    const onAttach = vi.fn()
    const host = renderClipped(<AttachmentPicker onAttach={onAttach} />)
    click(triggerButton(host))
    click(host.ownerDocument.querySelector('[data-testid="attach-files-item"]') as HTMLButtonElement) // đóng menu như người dùng thật
    expect(menu()).toBeNull()

    const big = new File([new Uint8Array(26 * 1024 * 1024)], 'big.bin')
    setFiles(host.querySelector('[data-testid="attach-file-input"]') as HTMLInputElement, [big])

    expect(onAttach).not.toHaveBeenCalled()
    // Menu mở lại để dòng lỗi đọc được (không nuốt im lặng tệp của người dùng).
    const error = document.querySelector('[data-testid="attach-error"]')
    expect(error).not.toBeNull()
    expect(error!.textContent).toContain('vượt trần 25 MB')
  })

  it('trần số tệp mỗi lượt: đã có 20 chip thì tệp thứ 21 không được thêm', () => {
    const onAttach = vi.fn()
    const host = renderClipped(<AttachmentPicker onAttach={onAttach} existingCount={20} />)
    click(triggerButton(host))

    setFiles(host.querySelector('[data-testid="attach-file-input"]') as HTMLInputElement, [
      new File(['x'], 'late.md'),
    ])

    expect(onAttach).not.toHaveBeenCalled()
    expect(document.querySelector('[data-testid="attach-error"]')!.textContent).toContain('20 tệp mỗi lượt')
  })

  it('trần tổng dung lượng mỗi lượt: 100 MB là biên', () => {
    const onAttach = vi.fn()
    const host = renderClipped(
      <AttachmentPicker onAttach={onAttach} existingBytes={100 * 1024 * 1024} />,
    )
    click(triggerButton(host))

    setFiles(host.querySelector('[data-testid="attach-file-input"]') as HTMLInputElement, [
      new File(['x'], 'late.md'),
    ])

    expect(onAttach).not.toHaveBeenCalled()
    expect(document.querySelector('[data-testid="attach-error"]')!.textContent).toContain('100 MB mỗi lượt')
  })
})

describe('AttachmentPicker — A9: Google Drive nói thật', () => {
  it('bấm Google Drive không đính kèm gì và nói rõ chưa kết nối', () => {
    const onAttach = vi.fn()
    const host = renderClipped(<AttachmentPicker onAttach={onAttach} />)
    click(triggerButton(host))

    const drive = host.ownerDocument.querySelector('[data-testid="attach-drive-item"]') as HTMLButtonElement
    expect(drive).not.toBeNull()
    click(drive)

    expect(onAttach).not.toHaveBeenCalled()
    expect(menu()!.textContent).toContain('Chưa kết nối')
    // Không còn tệp giả nào được bịa ra.
    expect(menu()!.textContent).not.toContain('Architecture_Blueprint_2026.gdoc')
  })
})

describe('AttachmentPicker — E5: chân bảng nói rõ luật gửi tệp', () => {
  it('có dòng nhắc Esc + tệp chỉ đi khi đã lên tới box', () => {
    const host = renderClipped(<AttachmentPicker onAttach={vi.fn()} />)
    click(triggerButton(host))

    const hint = menu()?.querySelector('[data-testid="attach-menu-hint"]')
    expect(hint).toBeTruthy()
    // Đóng bằng Esc là thật: picker có listener `keydown` (test "Escape đóng menu" ở trên).
    expect(hint?.textContent ?? '').toContain('Esc để đóng')
    expect(hint?.textContent ?? '').toContain('tệp chỉ được gửi sau khi lên tới box')
    expect(hint?.textContent ?? '').toContain('/__box/file/upload')
  })

  it('dòng nhắc không thêm mục menu nào và không hoá ảo mục Drive', () => {
    const host = renderClipped(<AttachmentPicker onAttach={vi.fn()} />)
    click(triggerButton(host))

    const drive = menu()?.querySelector('[data-testid="attach-drive-item"]')
    expect(drive?.getAttribute('aria-disabled')).toBe('true')
    expect(drive?.textContent ?? '').toContain('Chưa kết nối')
  })
})

describe('AttachmentPicker — Action Palette & Repositories View', () => {
  it('bấm Repositories chuyển sang màn hình tìm kiếm repo và có nút Back quay lại', () => {
    const host = renderClipped(<AttachmentPicker onAttach={vi.fn()} />)
    click(triggerButton(host))

    const repoItem = host.ownerDocument.querySelector('[data-testid="attach-repo-item"]') as HTMLButtonElement
    expect(repoItem).toBeTruthy()
    click(repoItem)

    // View chuyển sang RepoPickerView: có ô input tìm kiếm và nút Back
    const searchInput = host.ownerDocument.querySelector('input[placeholder="Search repositories..."]')
    expect(searchInput).toBeTruthy()

    // Bấm Back quay lại menu chính
    const backBtn = host.ownerDocument.querySelector('[data-testid="repo-back-btn"]') as HTMLButtonElement
    expect(backBtn).toBeTruthy()
    click(backBtn)
    expect(host.ownerDocument.querySelector('[data-testid="attach-files-item"]')).toBeTruthy()
  })

  it('bấm các nút mode kích hoạt callback tương ứng và đóng menu', () => {
    const onToggleAutopilot = vi.fn()
    const onSelectPlan = vi.fn()
    const onToggleResearch = vi.fn()
    const onToggleDesign = vi.fn()

    const host = renderClipped(
      <AttachmentPicker
        onAttach={vi.fn()}
        onToggleAutopilot={onToggleAutopilot}
        onSelectPlan={onSelectPlan}
        onToggleResearch={onToggleResearch}
        onToggleDesign={onToggleDesign}
      />,
    )

    // Test Autopilot click
    click(triggerButton(host))
    click(host.ownerDocument.querySelector('[data-testid="attach-autopilot-item"]'))
    expect(onToggleAutopilot).toHaveBeenCalledTimes(1)
    expect(menu()).toBeNull()

    // Test Plan click
    click(triggerButton(host))
    click(host.ownerDocument.querySelector('[data-testid="attach-plan-item"]'))
    expect(onSelectPlan).toHaveBeenCalledTimes(1)
    expect(menu()).toBeNull()

    // Test Research click
    click(triggerButton(host))
    click(host.ownerDocument.querySelector('[data-testid="attach-research-item"]'))
    expect(onToggleResearch).toHaveBeenCalledTimes(1)
    expect(menu()).toBeNull()

    // Test Design click
    click(triggerButton(host))
    click(host.ownerDocument.querySelector('[data-testid="attach-design-item"]'))
    expect(onToggleDesign).toHaveBeenCalledTimes(1)
    expect(menu()).toBeNull()
  })
})

