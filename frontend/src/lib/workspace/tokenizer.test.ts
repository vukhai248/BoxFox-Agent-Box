import { describe, expect, it } from 'vitest'
import { byLine, tokenize, type Token, type TokenKind } from './tokenizer'

function kinds(tokens: Token[]): TokenKind[] {
  return tokens.map((t) => t.kind)
}

describe('tokenize', () => {
  it('typescript: cho ra keyword/string/number/comment/operator', () => {
    const src = '// dòng cmt\nconst x = "hi"; /* khối */ { 1 }'
    const tokens = tokenize(src, 'typescript')
    expect(kinds(tokens)).toContain('comment')
    expect(kinds(tokens)).toContain('keyword') // const
    expect(kinds(tokens)).toContain('string') // "hi"
    expect(kinds(tokens)).toContain('number') // 1
    expect(kinds(tokens)).toContain('operator') // { }
  })

  it('python: dấu # là comment, def/return là keyword', () => {
    const src = '# ghi chú\ndef f():\n  return 1'
    const tokens = tokenize(src, 'python')
    expect(kinds(tokens)).toContain('comment')
    expect(kinds(tokens)).toContain('keyword')
    expect(kinds(tokens)).toContain('number')
  })

  it('json: khoá trước dấu `:` là property, giá trị số là number', () => {
    const tokens = tokenize('{"a": 1}', 'json')
    expect(kinds(tokens)).toContain('operator') // { }
    expect(kinds(tokens)).toContain('property') // "a"
    expect(kinds(tokens)).toContain('number') // 1
  })

  it('css: tên thuộc tính trước `:` là property, có comment khối', () => {
    const tokens = tokenize('.a { color: red; /* c */ }', 'css')
    expect(kinds(tokens)).toContain('operator')
    expect(kinds(tokens)).toContain('property') // color
    expect(kinds(tokens)).toContain('comment')
  })

  it('markdown: heading là keyword, `code` là string, *em* là property', () => {
    const tokens = tokenize('# Tiêu đề\n`code`\n*em*', 'markdown')
    expect(kinds(tokens)).toContain('keyword') // heading
    expect(kinds(tokens)).toContain('string') // `code`
    expect(kinds(tokens)).toContain('property') // *em*
  })

  it('ngôn ngữ lạ dùng fallback kiểu C — không crash, vẫn nhận số', () => {
    const tokens = tokenize('x = 1 // note', 'go')
    expect(kinds(tokens)).toContain('number')
    expect(kinds(tokens)).toContain('comment')
  })

  it('chuỗi rỗng → không token, không crash', () => {
    expect(tokenize('', 'typescript')).toEqual([])
  })

  it('input góc cạnh (lặp dấu) không crash', () => {
    expect(() => tokenize('"""', 'typescript')).not.toThrow()
    expect(() => tokenize('`unterminated', 'typescript')).not.toThrow()
    expect(() => tokenize('/* không đóng', 'typescript')).not.toThrow()
  })
})

describe('byLine', () => {
  it('chia token theo dòng, offset tương đối đầu dòng, số dòng 1-based', () => {
    const src = 'const a = 1\nconst b = 2'
    const lines = byLine(src, tokenize(src, 'typescript'))
    expect(lines).toHaveLength(2)
    expect(lines[0]!.number).toBe(1)
    expect(lines[1]!.number).toBe(2)
    // dòng 2 có keyword 'const'
    expect(kinds(lines[1]!.tokens)).toContain('keyword')
  })

  it('mỗi token nằm trong phạm vi dòng của nó', () => {
    const src = 'x = 1'
    const lines = byLine(src, tokenize(src, 'typescript'))
    for (const tok of lines[0]!.tokens) {
      expect(tok.start).toBeGreaterThanOrEqual(0)
      expect(tok.end).toBeLessThanOrEqual(src.length)
      expect(tok.end).toBeGreaterThan(tok.start)
    }
  })
})
