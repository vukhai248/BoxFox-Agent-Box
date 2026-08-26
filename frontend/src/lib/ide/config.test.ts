import { describe, it, expect } from 'vitest'
import {
  DEFAULT_IDE_URL,
  describeIdeContextProblem,
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
