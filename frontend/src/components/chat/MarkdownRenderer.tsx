/**
 * Bộ dựng Markdown & KaTeX LaTeX đa năng (MarkdownRenderer).
 * - Tương thích chuẩn React 19 + Tailwind v4.
 * - Hỗ trợ công thức Toán học KaTeX:
 *     + Inline Math: $E = mc^2$ hoặc $\mathcal{O}(N)$
 *     + Block / Display Math: $$\sum_{i=1}^n x_i$$
 * - Hỗ trợ Code Blocks với nút Copy, Language Header.
 * - Hỗ trợ Bảng biểu (Table), Danh sách (Lists), Trích dẫn (Blockquote).
 * - Cơ chế Streaming-Safe: Tự động đóng các block code hoặc thẻ toán dở dang trong lúc stream.
 */
import { useState, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import { Copy, Check } from 'lucide-react'

interface MarkdownRendererProps {
  content: string
  isStreaming?: boolean
  variant?: 'chat' | 'document'
}

/** Đảm bảo các khối mở dở dang (``` hoặc $$) được đóng an toàn khi đang stream */
export function makeStreamingSafe(rawText: string): string {
  if (!rawText) return ''
  let text = rawText

  // Kiểm tra số lượng block code ``` (nếu là số lẻ -> thêm ``` để đóng)
  const codeBlockCount = (text.match(/```/g) || []).length
  if (codeBlockCount % 2 !== 0) {
    text += '\n```'
  }

  // Kiểm tra số lượng block math $$ (nếu là số lẻ -> thêm $$ để đóng)
  const mathBlockCount = (text.match(/\$\$/g) || []).length
  if (mathBlockCount % 2 !== 0) {
    text += '$$'
  }

  return text
}

export function MarkdownRenderer({ content, isStreaming = false, variant = 'chat' }: MarkdownRendererProps) {
  const safeContent = useMemo(() => {
    return isStreaming ? makeStreamingSafe(content) : content
  }, [content, isStreaming])

  return (
    <div
      className={`markdown-body text-xs leading-relaxed text-fg select-text space-y-2 font-normal ${
        variant === 'document' ? 'w-full min-w-0 [overflow-wrap:anywhere]' : ''
      }`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          // Khối Code & Inline Code
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const codeString = String(children).replace(/\n$/, '')
            const isInline = !match && !codeString.includes('\n')

            if (isInline) {
              return (
                <code
                  className="rounded-md bg-panel2/90 border border-line/60 px-1.5 py-0.5 font-mono text-[11px] text-brand inline-block"
                  {...props}
                >
                  {children}
                </code>
              )
            }

            const language = match ? match[1] : 'text'
            return <CodeBlock language={language} code={codeString} />
          },

          // Bảng dữ liệu (Table)
          table({ children }) {
            return (
              <div className="overflow-x-auto my-3 rounded-xl border border-line bg-panel2/40 shadow-2xs">
                <table className="w-full text-left text-xs border-collapse">{children}</table>
              </div>
            )
          },
          thead({ children }) {
            return <thead className="border-b border-line bg-panel2/80">{children}</thead>
          },
          th({ children }) {
            return (
              <th className="px-3.5 py-2 font-semibold text-fg text-xs font-sans select-none">
                {children}
              </th>
            )
          },
          td({ children }) {
            return <td className="border-b border-line/40 px-3.5 py-2 text-fg text-xs">{children}</td>
          },

          // Tiêu đề (Headings)
          h1({ children }) {
            return <h1 className="text-base font-bold text-fg mt-3.5 mb-1.5">{children}</h1>
          },
          h2({ children }) {
            return <h2 className="text-sm font-bold text-fg mt-3 mb-1.5">{children}</h2>
          },
          h3({ children }) {
            return <h3 className="text-xs font-bold text-fg mt-2.5 mb-1">{children}</h3>
          },

          // Danh sách (Lists)
          ul({ children }) {
            return <ul className="list-disc list-outside pl-4 space-y-1 my-2 text-xs text-fg">{children}</ul>
          },
          ol({ children }) {
            return <ol className="list-decimal list-outside pl-4 space-y-1 my-2 text-xs text-fg">{children}</ol>
          },
          li({ children }) {
            return <li className="leading-relaxed text-xs text-fg">{children}</li>
          },

          // Trích dẫn (Blockquote)
          blockquote({ children }) {
            return (
              <blockquote className="border-l-2 border-brand/60 bg-panel2/40 pl-3.5 py-1.5 my-2.5 italic text-muted rounded-r-xl text-xs">
                {children}
              </blockquote>
            )
          },

          // Đoạn văn (Paragraph)
          p({ children }) {
            return <p className="leading-relaxed text-xs text-fg my-1.5">{children}</p>
          },

          // Đường link (Anchor)
          a({ href, children }) {
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer"
                className="text-brand hover:underline font-medium cursor-pointer"
              >
                {children}
              </a>
            )
          },
        }}
      >
        {safeContent}
      </ReactMarkdown>

      {/* Con trỏ nhấp nháy khi đang stream */}
      {isStreaming && (
        <span className="inline-block size-2 rounded-full bg-brand animate-pulse ml-0.5 align-middle" />
      )}
    </div>
  )
}

/** Khung hiển thị khối Code có header ngôn ngữ và nút Copy */
function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel2 font-mono text-xs shadow-xs my-2.5">
      <div className="flex items-center justify-between border-b border-line bg-panel px-3.5 py-1.5 text-[11px] text-muted select-none">
        <span className="font-medium text-fg uppercase text-[10px] tracking-wide">{language}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-fg transition cursor-pointer text-[11px]"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="size-3 text-emerald-500" />
              <span className="text-[10px] text-emerald-500 font-sans">Copied</span>
            </>
          ) : (
            <>
              <Copy className="size-3" />
              <span className="text-[10px] font-sans">Copy</span>
            </>
          )}
        </button>
      </div>
      <pre className="overflow-x-auto p-3.5 text-[12px] leading-relaxed text-fg">
        <code>{code}</code>
      </pre>
    </div>
  )
}
