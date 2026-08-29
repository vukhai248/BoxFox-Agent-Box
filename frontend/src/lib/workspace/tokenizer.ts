/**
 * Tokenizer thuần (không DOM) cho tô màu code cơ bản.
 *
 * Hỗ trợ typescript/javascript/python/json/css/markdown; ngôn ngữ lạ dùng fallback
 * kiểu C (comment dòng và comment khối asterisk-slash). Không thay thế
 * syntax-highlighter thật — chỉ đủ nhu cầu xem trước file trong panel với số
 * dòng + nút Copy.
 */

export type TokenKind =
  | 'comment'
  | 'string'
  | 'keyword'
  | 'number'
  | 'property'
  | 'operator'
  | 'plain'

export interface Token {
  kind: TokenKind
  /** Offset bắt đầu (inclusive) trong source. */
  start: number
  /** Offset kết thúc (exclusive). */
  end: number
}

/** Một dòng cùng các token đã dịch offset về tương đối với đầu dòng. */
export interface LineTokens {
  /** Số dòng (1-based). */
  number: number
  tokens: Token[]
}

const JS_KEYWORDS = new Set([
  'const', 'let', 'var', 'function', 'return', 'if', 'else', 'for', 'while', 'do',
  'break', 'continue', 'switch', 'case', 'default', 'class', 'extends', 'new', 'this',
  'super', 'import', 'export', 'from', 'as', 'async', 'await', 'try', 'catch', 'finally',
  'throw', 'typeof', 'instanceof', 'in', 'of', 'interface', 'type', 'enum', 'namespace',
  'public', 'private', 'protected', 'readonly', 'static', 'void', 'null', 'undefined',
  'true', 'false', 'yield', 'delete', 'implements', 'declare', 'satisfies',
])

const PY_KEYWORDS = new Set([
  'def', 'elif', 'lambda', 'pass', 'with', 'raise', 'global', 'nonlocal', 'None',
  'True', 'False', 'and', 'or', 'not', 'is', 'in', 'for', 'while', 'if', 'else',
  'return', 'import', 'from', 'as', 'try', 'except', 'finally', 'class', 'yield',
  'async', 'await', 'assert', 'del', 'print',
])

const SH_KEYWORDS = new Set([
  'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done',
  'case', 'esac', 'function', 'return', 'exit', 'echo', 'export', 'local',
  'readonly', 'shift', 'set', 'unset', 'source', 'trap', 'in',
])

const EMPTY = new Set<string>()

interface LangConfig {
  lineComment?: string
  blockComment?: [string, string]
  keywords: Set<string>
}

/** Fallback kiểu C cho ngôn ngữ chưa liệt kê — vẫn tô được comment/string/số. */
const DEFAULT_CONFIG: LangConfig = { lineComment: '//', blockComment: ['/*', '*/'], keywords: EMPTY }

function configFor(language: string): LangConfig {
  switch (language) {
    case 'typescript':
    case 'javascript':
      return { lineComment: '//', blockComment: ['/*', '*/'], keywords: JS_KEYWORDS }
    case 'python':
      return { lineComment: '#', keywords: PY_KEYWORDS }
    case 'shell':
    case 'bash':
    case 'sh':
      return { lineComment: '#', keywords: SH_KEYWORDS }
    case 'json':
      return { keywords: EMPTY }
    case 'css':
      return { blockComment: ['/*', '*/'], keywords: EMPTY }
    default:
      return DEFAULT_CONFIG
  }
}

function isWhitespace(ch: string): boolean {
  return ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r'
}
function isDigit(ch: string | undefined): boolean {
  return ch !== undefined && ch >= '0' && ch <= '9'
}
function isDigitOrDot(ch: string): boolean {
  return (ch >= '0' && ch <= '9') || ch === '.'
}
function isAlpha(ch: string): boolean {
  return (ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z')
}
function isIdentStart(ch: string): boolean {
  return isAlpha(ch) || ch === '_' || ch === '$'
}
function isIdentPart(ch: string): boolean {
  return isIdentStart(ch) || (ch >= '0' && ch <= '9')
}

const OPERATORS = new Set(['{', '}', '[', ']', '(', ')'])

/** Sau vị trí `pos` (bỏ qua khoảng trắng), ký tự tiếp theo có phải `:` không? */
function nextNonWsIsColon(source: string, pos: number): boolean {
  let j = pos
  while (j < source.length && isWhitespace(source[j]!)) j++
  return source[j] === ':'
}

/** Tách token cho code kiểu C/python/json/css. */
function scanCode(source: string, cfg: LangConfig, language: string): Token[] {
  const tokens: Token[] = []
  const n = source.length
  const isJson = language === 'json'
  const isCss = language === 'css'
  let i = 0

  const push = (kind: TokenKind, start: number, end: number) => {
    if (end > start) tokens.push({ kind, start, end })
  }

  while (i < n) {
    const ch = source[i]!

    if (isWhitespace(ch)) {
      const start = i
      while (i < n && isWhitespace(source[i]!)) i++
      push('plain', start, i)
      continue
    }

    if (cfg.lineComment && source.startsWith(cfg.lineComment, i)) {
      const start = i
      i += cfg.lineComment.length
      while (i < n && source[i] !== '\n') i++
      push('comment', start, i)
      continue
    }

    if (cfg.blockComment && source.startsWith(cfg.blockComment[0], i)) {
      const start = i
      i += cfg.blockComment[0].length
      while (i < n && !source.startsWith(cfg.blockComment[1], i)) i++
      if (i < n) i += cfg.blockComment[1].length
      push('comment', start, i)
      continue
    }

    if (ch === '"' || ch === "'" || ch === '`') {
      const start = i
      const quote = ch
      i++
      while (i < n) {
        const c = source[i]!
        if (c === '\\') {
          i += 2
          continue
        }
        if (c === quote) {
          i++
          break
        }
        i++
      }
      if (i > n) i = n
      const kind: TokenKind = isJson && nextNonWsIsColon(source, i) ? 'property' : 'string'
      push(kind, start, i)
      continue
    }

    if (isDigit(ch) || (ch === '.' && isDigit(source[i + 1]))) {
      const start = i
      while (i < n && isDigitOrDot(source[i]!)) i++
      push('number', start, i)
      continue
    }

    if (isIdentStart(ch)) {
      const start = i
      while (i < n && isIdentPart(source[i]!)) i++
      const word = source.slice(start, i)
      let kind: TokenKind = cfg.keywords.has(word) ? 'keyword' : 'plain'
      if (kind === 'plain' && isCss && nextNonWsIsColon(source, i)) kind = 'property'
      push(kind, start, i)
      continue
    }

    if (OPERATORS.has(ch)) {
      const start = i
      i++
      push('operator', start, i)
      continue
    }

    // Dấu câu khác (.,;:=+-/<>&|?@#…) — để plain.
    const start = i
    i++
    push('plain', start, i)
  }

  return tokens
}

function isHeading(line: string): boolean {
  let i = 0
  while (i < line.length && line[i] === '#' && i < 6) i++
  return i >= 1 && i <= 6 && line[i] === ' '
}

/** Tách token cho Markdown (dựa trên dòng): heading, fence, `code`, *em*. */
function tokenizeMarkdown(source: string): Token[] {
  const tokens: Token[] = []
  const lines = source.split('\n')
  let pos = 0

  for (const line of lines) {
    const lineStart = pos
    const lineEnd = pos + line.length

    if (line.startsWith('```')) {
      tokens.push({ kind: 'comment', start: lineStart, end: lineEnd })
    } else if (isHeading(line)) {
      tokens.push({ kind: 'keyword', start: lineStart, end: lineEnd })
    } else {
      let j = 0
      while (j < line.length) {
        const ch = line[j]!
        if (ch === '`' || ch === '*' || ch === '_') {
          const close = line.indexOf(ch, j + 1)
          const endIdx = close === -1 ? line.length : close + 1
          tokens.push({ kind: ch === '`' ? 'string' : 'property', start: lineStart + j, end: lineStart + endIdx })
          j = endIdx
          continue
        }
        const start = j
        while (j < line.length && line[j] !== '`' && line[j] !== '*' && line[j] !== '_') j++
        if (j > start) {
          tokens.push({ kind: 'plain', start: lineStart + start, end: lineStart + j })
        } else {
          tokens.push({ kind: 'plain', start: lineStart + j, end: lineStart + j + 1 })
          j++
        }
      }
    }

    pos = lineEnd + 1 // bù cho ký tự '\n' đã bị split ăn
  }

  return tokens
}

/** Tách token theo ngôn ngữ. Ngôn ngữ lạ → fallback kiểu C. */
export function tokenize(source: string, language: string): Token[] {
  if (source.length === 0) return []
  if (language === 'markdown') return tokenizeMarkdown(source)
  return scanCode(source, configFor(language), language)
}

/**
 * Chia token theo dòng để render số dòng. Mỗi token được cắt/clamp về phạm vi
 * dòng và dịch offset về tương đối với đầu dòng đó.
 */
export function byLine(source: string, tokens: Token[]): LineTokens[] {
  const lines = source.split('\n')
  const result: LineTokens[] = []
  let offset = 0

  for (let i = 0; i < lines.length; i++) {
    const lineStart = offset
    const lineEnd = offset + lines[i]!.length
    const lineTokens = tokens
      .filter((t) => t.end > lineStart && t.start < lineEnd)
      .map((t) => ({
        kind: t.kind,
        start: Math.max(t.start, lineStart) - lineStart,
        end: Math.min(t.end, lineEnd) - lineStart,
      }))
      .filter((t) => t.end > t.start)
    result.push({ number: i + 1, tokens: lineTokens })
    offset = lineEnd + 1
  }

  return result
}
