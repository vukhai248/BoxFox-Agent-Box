/**
 * Kiểm tra `buildCompletionEmail` dựng subject/body theo locale, có chèn title,
 * liệt kê việc đã làm dạng bullet và KHÔNG kèm danh sách commit (quyết định #4650).
 */
import { describe, it, expect } from 'vitest'
import { buildCompletionEmail, workTargetOf } from './notifyEmail'

describe('buildCompletionEmail', () => {
  it('en: chèn title vào subject và body', () => {
    const { subject, body } = buildCompletionEmail('en', 'Build the login flow')
    expect(subject).toContain('Build the login flow')
    expect(body).toContain('Build the login flow')
    expect(subject).toMatch(/Completed/)
  })

  it('vi: dùng bản tiếng Việt', () => {
    const { subject, body } = buildCompletionEmail('vi', 'Xây trang đăng nhập')
    expect(subject).toContain('Đã xong')
    expect(body).toContain('Xây trang đăng nhập')
  })

  it('không chứa chuỗi "commit" trong nội dung tóm tắt', () => {
    const { body } = buildCompletionEmail('en', 'Anything', [
      { tool: 'run_command', target: 'pytest' },
    ])
    expect(body.toLowerCase()).not.toContain('commit')
  })

  it('liệt kê việc đã làm khi có work items', () => {
    const { body } = buildCompletionEmail('en', 'Fix parser', [
      { tool: 'read_file', target: 'src/parser.py' },
      { tool: 'run_command', target: 'pytest' },
    ])
    expect(body).toContain('Work done:')
    expect(body).toContain('• Read file — src/parser.py')
    expect(body).toContain('• Run command — pytest')
  })

  it('title rỗng không làm vỡ template', () => {
    const { subject } = buildCompletionEmail('en', '')
    expect(subject).toContain('Completed')
  })
})

describe('workTargetOf', () => {
  it('ưu tiên path rồi command', () => {
    expect(workTargetOf({ path: 'src/a.py' })).toBe('src/a.py')
    expect(workTargetOf({ command: 'pytest' })).toBe('pytest')
  })

  it('cắt chuỗi dài quá 72 ký tự', () => {
    const long = 'x'.repeat(200)
    const out = workTargetOf({ text: long })
    expect(out.length).toBeLessThanOrEqual(73)
    expect(out.endsWith('…')).toBe(true)
  })

  it('params rỗng/undefined trả về chuỗi rỗng', () => {
    expect(workTargetOf(undefined)).toBe('')
    expect(workTargetOf({})).toBe('')
  })
})
