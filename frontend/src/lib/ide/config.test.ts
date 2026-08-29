import { describe, it, expect } from 'vitest'
import {
  buildIdeUrl,
  DEFAULT_IDE_URL,
  describeIdeContextProblem,
  IDE_WORKSPACE_ROOT,
  resolveIdeSource,
  resolveIdeUrl,
} from './config'

describe('resolveIdeSource', () => {
  it('không cấu hình gì → bật code-server (không có "IDE mô phỏng" để bảo vệ)', () => {
    expect(resolveIdeSource()).toBe('codeServer')
    expect(resolveIdeSource({})).toBe('codeServer')
  })

  it('off → tắt hẳn, kể cả viết hoa hay có khoảng trắng', () => {
    expect(resolveIdeSource({ VITE_IDE_SOURCE: 'off' })).toBe('off')
    expect(resolveIdeSource({ VITE_IDE_SOURCE: '  OFF  ' })).toBe('off')
  })

  it('giá trị lạ → vẫn bật, không im lặng tắt tính năng người dùng đang chờ', () => {
    expect(resolveIdeSource({ VITE_IDE_SOURCE: 'vscode-desktop' })).toBe('codeServer')
    expect(resolveIdeSource({ VITE_IDE_SOURCE: '' })).toBe('codeServer')
  })
})

describe('resolveIdeUrl', () => {
  it('không đặt → URL mặc định, có sẵn ?folder để không rơi vào trang Welcome rỗng', () => {
    expect(resolveIdeUrl()).toBe(DEFAULT_IDE_URL)
    expect(DEFAULT_IDE_URL).toContain('?folder=')
  })

  it('đặt tường minh → dùng đúng giá trị đó, đã trim', () => {
    expect(resolveIdeUrl({ VITE_IDE_URL: 'http://127.0.0.1:9000/' })).toBe('http://127.0.0.1:9000/')
    expect(resolveIdeUrl({ VITE_IDE_URL: '  http://box.local:8080  ' })).toBe(
      'http://box.local:8080',
    )
  })

  it('chuỗi rỗng hoặc chỉ khoảng trắng → mặc định', () => {
    expect(resolveIdeUrl({ VITE_IDE_URL: '' })).toBe(DEFAULT_IDE_URL)
    expect(resolveIdeUrl({ VITE_IDE_URL: '   ' })).toBe(DEFAULT_IDE_URL)
  })
})

describe('describeIdeContextProblem', () => {
  it('trang HTTPS + iframe http:// → mixedContent', () => {
    expect(
      describeIdeContextProblem({ pageProtocol: 'https:', url: 'http://localhost:8080/' }),
    ).toBe('mixedContent')
  })

  it('trang HTTP + iframe http:// → không vấn đề gì', () => {
    expect(describeIdeContextProblem({ pageProtocol: 'http:', url: 'http://localhost:8080/' })).toBe(
      null,
    )
  })

  it('trang HTTPS + iframe https:// → không vấn đề gì', () => {
    expect(
      describeIdeContextProblem({ pageProtocol: 'https:', url: 'https://box.example/' }),
    ).toBe(null)
  })
})

describe('buildIdeUrl', () => {
  it('không có folder → mở sẵn gốc workspace (khớp DEFAULT_IDE_URL)', () => {
    expect(buildIdeUrl()).toBe(DEFAULT_IDE_URL)
    expect(buildIdeUrl()).toBe(`http://localhost:8081/?folder=${IDE_WORKSPACE_ROOT}`)
  })

  it('folder con → nối vào gốc, giữ slash literal (không %2F)', () => {
    const url = buildIdeUrl({}, 'frontend/src')
    expect(url).toBe(`http://localhost:8081/?folder=${IDE_WORKSPACE_ROOT}/frontend/src`)
    expect(url).not.toContain('%2F')
  })

  it('truyền file → dùng payload openFile vscode-remote, giữ folder gốc', () => {
    const url = buildIdeUrl({}, '', '.plans/v1-agent-box-plan.md')
    const payload = encodeURIComponent(
      JSON.stringify([
        ['gotoLineMode', 'true'],
        ['openFile', `vscode-remote://localhost:8081${IDE_WORKSPACE_ROOT}/.plans/v1-agent-box-plan.md`],
      ]),
    )
    expect(url).toBe(`http://localhost:8081/?folder=${IDE_WORKSPACE_ROOT}&payload=${payload}`)
  })

  it('host trong openFile lấy từ origin theo VITE_IDE_URL tường minh', () => {
    const url = buildIdeUrl({ VITE_IDE_URL: 'http://box.local:9000/' }, '', 'src/a.py')
    const payloadRaw = new URL(url).searchParams.get('payload')!
    const decoded = JSON.parse(decodeURIComponent(payloadRaw))
    expect(decoded).toEqual([
      ['gotoLineMode', 'true'],
      ['openFile', `vscode-remote://box.local:9000${IDE_WORKSPACE_ROOT}/src/a.py`],
    ])
  })

  it('không có file → không sinh payload (chỉ ?folder=)', () => {
    expect(buildIdeUrl({}, 'docs')).not.toContain('payload')
  })

  it('dùng VITE_IDE_URL tường minh làm origin, bỏ query cũ của base', () => {
    expect(buildIdeUrl({ VITE_IDE_URL: 'http://box.local:9000/?folder=/old' }, 'docs')).toBe(
      `http://box.local:9000/?folder=${IDE_WORKSPACE_ROOT}/docs`,
    )
  })
})
