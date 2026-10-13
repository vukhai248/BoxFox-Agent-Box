/**
 * Bộ dựng Markdown & KaTeX LaTeX đa năng (MarkdownRenderer).
 * - Tương thích chuẩn React 19 + Tailwind v4.
 * - Hỗ trợ công thức Toán học KaTeX:
 *     + Inline Math: $E = mc^2$ hoặc $\mathcal{O}(N)$
 *     + Block / Display Math: $$\sum_{i=1}^n x_i$$
 * - Hỗ trợ Code Blocks với nút Copy, Language Header.
 * - Hỗ trợ Bảng biểu (Table), Danh sách (Lists), Trích dẫn (Blockquote).
 * - Cơ chế Streaming-Safe: Tự động đóng các block code hoặc thẻ toán dở dang trong lúc stream.
 * - Tối ưu hóa hiệu năng cực đại (Zero-lag 60fps Resize):
 *     + Plugin và Components tĩnh + React.memo
 *     + content-visibility: auto + contain-intrinsic-size cho các khối off-screen.
 */
import { useState, useMemo, memo, createContext, useContext, type ReactNode } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Components } from 'react-markdown'
import remarkMath from 'remark-math'
import remarkGfm from 'remark-gfm'
import rehypeKatex from 'rehype-katex'
import { Copy, Check, Camera } from 'lucide-react'
import type { LightboxMediaProps } from './MediaLightboxModal'

interface MarkdownRendererProps {
  content: string
  isStreaming?: boolean
  variant?: 'chat' | 'document'
  /**
   * P4.1 — bấm ảnh trong câu trả lời ⇒ mở khung xem lớn (`MediaLightboxModal` đã có zoom/kéo).
   * Không truyền ⇒ giữ nguyên hành vi cũ (ảnh lớn trong mạch chữ), nên các chỗ dùng khác không đổi.
   */
  onOpenImage?: (media: LightboxMediaProps) => void
  /**
   * P4.1 — bấm liên kết tệp bằng chứng trong workspace ⇒ mở tab Files đúng tệp, thay vì điều hướng
   * tab trình duyệt (hôm nay `<a target="_blank">` ⇒ mở ra một tab trắng).
   */
  onOpenFile?: (path: string) => void
  /** Nhãn nút mở tệp — chữ do người gọi cấp, vì nó phải theo ngôn ngữ câu trả lời (P5.3). */
  fileLinkLabel?: string
}

/** Hằng số plugin tĩnh — tránh khởi tạo lại mảng ở mỗi frame render */
const REMARK_PLUGINS = [remarkGfm, remarkMath]
const REHYPE_PLUGINS = [rehypeKatex]

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

/** Đuôi ảnh: dùng để biết một `href` là ảnh hay là tệp bằng chứng (P4.1). */
const IMAGE_FILE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif']

/** Nhãn mặc định của nút mở tệp khi người gọi không cấp chữ (xem `fileLinkLabel`). */
const DEFAULT_FILE_LINK_LABEL = 'Open in Files'

/**
 * Vòng 27 / C-2 2.4 — phòng hồ sơ của một việc nghiên cứu: mọi đường dẫn tương đối nằm dưới
 * `.research/<việc>/` (`.research/x/v1-x.md`, `sources.jsonl`, `tables/…`) đều là tệp THẬT trong
 * workspace, và báo cáo cuối của main trỏ tới chúng. Chúng phải mở bằng tab Files đúng như tệp
 * bằng chứng — không điều hướng tab trình duyệt (F5: đây là phép thử ĐẦU TIÊN, trước `isImageLink`).
 */
const DOSSIER_PREFIX = '.research/'

/**
 * Đường dẫn artifact đã CHUẨN HOÁ: bỏ dấu cách thừa, bỏ `?query` và `#fragment` ở cuối, bỏ `./` đầu.
 *
 * Vì sao phải có: việc PHÂN LOẠI một link (ảnh? tệp bằng chứng? link ngoài?) và việc GỬI ĐI giá trị
 * (`onOpenFile`/`onOpenImage`, `data-artifact-path`, URL `/__box/file/media`) trước đây đọc hai giá
 * trị khác nhau — phân loại thì cắt `?query`, còn giá trị gửi đi là chuỗi thô. Hệ quả: `…x.txt?raw=1`,
 * `…x.txt#L12`, `./.generated_artifacts/a.png`, `shots/a.png` đều dẫn tới đường dẫn KHÔNG mở được
 * (route media nhận sai đường dẫn, tab Files không tìm thấy tệp). Nay một hàm chuẩn hoá dùng cho cả hai.
 *
 * Chuỗi thô vẫn được giữ cho đường DỰ PHÒNG (thẻ `<a href>` nguyên bản) — trình duyệt tự hiểu link của nó.
 */
function normalizeArtifactPath(path: string): string {
  let clean = path.trim().split('#')[0].split('?')[0].trim()
  while (clean.startsWith('./')) clean = clean.slice(2)
  return clean
}

/**
 * Đường dẫn media của box đi qua route `/__box/file/media`. Box báo tệp theo hai khuôn: đường dẫn
 * TUYỆT ĐỐI trong workspace (`/home/agent/workspace/…`) và đường dẫn TƯƠNG ĐỐI
 * (`.generated_artifacts/…`, `captures/…`, hoặc `shots/…`). Cả hai khuôn về cùng một URL.
 */
function resolveMediaSrc(path: string): string {
  const relative = workspaceRelative(path)
  if (!relative) return path
  return `/__box/file/media?path=${encodeURIComponent(relative)}`
}

/**
 * Đường dẫn TƯƠNG ĐỐI trong workspace, hoặc `null` nếu đường dẫn không nằm trong workspace.
 * Đây là khuôn mà tab Files và mọi mảnh cổng đang dùng.
 *
 * Mọi đường dẫn TƯƠNG ĐỐI đều được coi là đường dẫn trong workspace: model viết đường dẫn theo gốc
 * workspace (`.generated_artifacts/…`, `frontend/src/…`, `shots/a.png`), và không có gốc nào khác để
 * chúng dựa vào. Ba thứ KHÔNG nằm trong workspace: link có scheme (`https:`, `data:`, `blob:`,
 * `//host`), đường dẫn tuyệt đối của hệ điều hành (`/etc/…`), và neo trong trang (`#mục`).
 */
function workspaceRelative(path: string): string | null {
  const clean = normalizeArtifactPath(path)
  if (!clean) return null
  if (/^[a-z][a-z0-9+.-]*:/i.test(clean) || clean.startsWith('//')) return null
  if (clean.startsWith('/home/agent/workspace/')) return clean.replace(/^\/home\/agent\/workspace\//, '')
  if (clean.startsWith('/')) return null
  return clean
}

/** Tên tệp đọc được của một đường dẫn (P4.1: dòng nhãn dưới tile ảnh). */
function fileNameOf(path: string): string {
  const clean = normalizeArtifactPath(path).replace(/\/+$/, '')
  const slash = clean.lastIndexOf('/')
  return slash === -1 ? clean : clean.slice(slash + 1)
}

/** Link trỏ tới ẢNH: đuôi ảnh, hoặc thư mục ảnh chụp của box (khuôn cũ, không có đuôi đọc được). */
function isImageLink(href: string): boolean {
  const clean = normalizeArtifactPath(href).toLowerCase()
  return (
    IMAGE_FILE_EXTENSIONS.some((ext) => clean.endsWith(ext)) || clean.includes('.generated_artifacts/captures')
  )
}

/** Link trỏ tới tệp BẰNG CHỨNG trong workspace (không phải ảnh) — mở bằng tab Files, không mở tab mới. */
function isEvidenceFileLink(href: string): boolean {
  const clean = normalizeArtifactPath(href)
  if (!workspaceRelative(clean)) return false
  // Hồ sơ nghiên cứu (`.research/<việc>/…`) là tệp để MỞ — kể cả khi tên tệp tình cờ mang đuôi ảnh
  // (việc 2.4): nhận diện trước, nên nó không bao giờ rơi vào nhánh tile ảnh phía dưới.
  if (clean.toLowerCase().startsWith(DOSSIER_PREFIX)) return true
  const lower = clean.toLowerCase()
  return !IMAGE_FILE_EXTENSIONS.some((ext) => lower.endsWith(ext))
}

/** Từ điển components tĩnh — áp dụng content-visibility:auto giúp bỏ qua layout off-screen */
const STATIC_COMPONENTS: Components = {
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
      <div className="overflow-x-auto my-3 rounded-xl border border-line bg-panel2/40 shadow-2xs [content-visibility:auto] [contain-intrinsic-size:1px_120px]">
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
    return (
      <h1 className="text-base font-bold text-fg mt-3.5 mb-1.5 [content-visibility:auto] [contain-intrinsic-size:1px_32px]">
        {children}
      </h1>
    )
  },
  h2({ children }) {
    return (
      <h2 className="text-sm font-bold text-fg mt-3 mb-1.5 [content-visibility:auto] [contain-intrinsic-size:1px_28px]">
        {children}
      </h2>
    )
  },
  h3({ children }) {
    return (
      <h3 className="text-xs font-bold text-fg mt-2.5 mb-1 [content-visibility:auto] [contain-intrinsic-size:1px_24px]">
        {children}
      </h3>
    )
  },

  // Danh sách (Lists)
  ul({ children }) {
    return (
      <ul className="list-disc list-outside pl-4 space-y-1 my-2 text-xs text-fg [content-visibility:auto] [contain-intrinsic-size:1px_60px]">
        {children}
      </ul>
    )
  },
  ol({ children }) {
    return (
      <ol className="list-decimal list-outside pl-4 space-y-1 my-2 text-xs text-fg [content-visibility:auto] [contain-intrinsic-size:1px_60px]">
        {children}
      </ol>
    )
  },
  li({ children }) {
    return <li className="leading-relaxed text-xs text-fg">{children}</li>
  },

  // Trích dẫn (Blockquote)
  blockquote({ children }) {
    return (
      <blockquote className="border-l-2 border-brand/60 bg-panel2/40 pl-3.5 py-1.5 my-2.5 italic text-muted rounded-r-xl text-xs [content-visibility:auto] [contain-intrinsic-size:1px_40px]">
        {children}
      </blockquote>
    )
  },

  // Đoạn văn (Paragraph)
  p({ children }) {
    return (
      <p className="leading-relaxed text-xs text-fg my-1.5 [content-visibility:auto] [contain-intrinsic-size:1px_24px]">
        {children}
      </p>
    )
  },

  // Hình ảnh (Image) — Tự động phân giải đường dẫn media và fallback mock SVG
  img({ src, alt }) {
    const resolvedSrc = resolveMediaSrc(String(src || ''))

    return (
      <span className="block my-2.5 max-w-2xl overflow-hidden rounded-xl border border-line bg-panel2 shadow-xs group">
        <img
          src={resolvedSrc}
          alt={String(alt || 'Captured screenshot')}
          onError={(e) => {
            (e.currentTarget as HTMLElement).style.display = 'none'
          }}
          className="w-full object-contain max-h-96 rounded-lg transition group-hover:scale-[1.01]"
        />
      </span>
    )
  },

  // Đường link (Anchor) — Nếu trỏ tới ảnh artifact thì render ảnh trực tiếp thay vì chỉ để lại link
  a({ href, children }) {
    const hrefStr = String(href || '')

    if (isImageLink(hrefStr)) {
      const resolvedSrc = resolveMediaSrc(hrefStr)

      return (
        <span className="block my-2 max-w-2xl">
          <a
            href={resolvedSrc}
            target="_blank"
            rel="noreferrer"
            className="text-brand hover:underline font-medium cursor-pointer inline-flex items-center gap-1.5 font-mono text-[11px] mb-1.5"
          >
            <Camera className="size-3 text-brand" />
            <span>{children}</span>
          </a>
          <span className="block overflow-hidden rounded-xl border border-line bg-panel2 shadow-xs group">
            <img
              src={resolvedSrc}
              alt="Screenshot preview"
              onError={(e) => {
                (e.currentTarget as HTMLElement).style.display = 'none'
              }}
              className="w-full object-contain max-h-96 rounded-lg transition group-hover:scale-[1.01]"
            />
          </span>
        </span>
      )
    }

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
}

/**
 * P4.1 — hai bộ dựng cần thấy callback của lượt render (`img`, `a`); bộ tĩnh ở trên là đường KHÔNG
 * có callback, nên mọi chỗ dùng khác giữ nguyên hành vi cũ. Bộ có callback chỉ được dựng trong
 * `useMemo` (khoá là chính hai callback) — giữ đúng lời hứa "components tĩnh + `React.memo`".
 */
interface MarkdownTools {
  onOpenImage?: (media: LightboxMediaProps) => void
  onOpenFile?: (path: string) => void
  fileLinkLabel?: string
}

type ImgProps = { src?: string; alt?: string }
type AnchorProps = { href?: string; children?: ReactNode }

/** Gọi lại đúng renderer tĩnh khi lượt render này không có callback tương ứng. */
function renderStaticImage(props: ImgProps): ReactNode {
  const renderer = STATIC_COMPONENTS.img as unknown as (p: ImgProps) => ReactNode
  return renderer(props)
}

/**
 * P4.1 — một ảnh trong câu trả lời: tile nhìn thấy ngay, nhãn của model ở dưới, tên tệp đọc được,
 * bấm ra khung xem lớn. Nhiều ảnh thì `inline-block` tự xuống dòng thành lưới.
 */
function AnswerImageTile({ path, caption, tools }: { path: string; caption: string; tools: MarkdownTools }) {
  // Một đường dẫn, MỘT giá trị: phân loại và gửi đi đều dùng khuôn đã chuẩn hoá.
  const artifactPath = normalizeArtifactPath(path)
  const resolvedSrc = resolveMediaSrc(artifactPath)
  const fileName = fileNameOf(artifactPath)
  return (
    <span className="my-2.5 mr-2.5 inline-block max-w-full align-top" data-capture-tile="true" data-artifact-path={artifactPath || undefined}>
      <button
        type="button"
        onClick={() =>
          tools.onOpenImage?.({
            type: 'image',
            src: resolvedSrc,
            caption: caption || undefined,
            artifactPath: artifactPath || undefined,
          })
        }
        data-artifact-open="media"
        aria-label={caption || fileName || 'Image'}
        title={artifactPath || caption || undefined}
        className="group/tile block w-40 cursor-zoom-in text-left"
      >
        <span className="block h-24 w-full overflow-hidden rounded-lg border border-line bg-panel2 transition group-hover/tile:border-brand/60">
          <img
            src={resolvedSrc}
            alt={caption}
            onError={(e) => {
              ;(e.currentTarget as HTMLElement).style.display = 'none'
            }}
            className="h-full w-full object-cover"
          />
        </span>
        {caption && (
          <span className="mt-1 block text-[11px] leading-snug text-zinc-300" data-capture-label="true">
            {caption}
          </span>
        )}
        {fileName && (
          <span className="mt-0.5 block truncate font-mono text-[11px] text-zinc-500" data-capture-file="true" title={artifactPath || undefined}>
            {fileName}
          </span>
        )}
      </button>
    </span>
  )
}

/**
 * Ảnh nằm BÊN TRONG một liên kết phải là ảnh thường, không phải tile bấm được.
 *
 * `[![nhãn](anh.png)](https://tài-liệu)` là khuôn markdown hợp lệ: ảnh là chữ của liên kết. Nếu ảnh
 * vẫn là tile (`<button>`) thì markup thành `<a><button>…</button></a>` — ARIA sai, và một cú bấm vừa
 * mở khung xem lớn vừa mở tab trình duyệt (mất mạch chat). Liên kết bật cờ này quanh chữ của nó, và
 * bộ dựng ảnh đọc cờ ấy để vẽ ảnh TĨNH: liên kết giữ nguyên việc của nó, ảnh chỉ để nhìn.
 *
 * Dùng context (không phải thay element của `children`) vì `children` ở đây do react-markdown dựng
 * sẵn — bộ dựng `img` của mình chỉ chạy lúc render, khi cờ đã nằm trong cây.
 */
const PassiveMediaContext = createContext(false)

function makeImgRenderer(tools: MarkdownTools): (props: ImgProps) => ReactNode {
  return function AnswerImage({ src, alt }) {
    const passive = useContext(PassiveMediaContext)
    if (passive || !tools.onOpenImage) return renderStaticImage({ src, alt })
    return <AnswerImageTile path={String(src || '')} caption={String(alt || '')} tools={tools} />
  }
}

function makeAnchorRenderer(tools: MarkdownTools): (props: AnchorProps) => ReactNode {
  return function AnswerAnchor({ href, children }) {
    const hrefStr = String(href || '')
    // Một giá trị đã chuẩn hoá cho cả việc PHÂN LOẠI lẫn việc GỬI ĐI (xem `normalizeArtifactPath`).
    const cleanHref = normalizeArtifactPath(hrefStr)
    // Tệp bằng chứng trong workspace (không phải ảnh) được xét TRƯỚC phép thử ảnh: tệp kết quả test
    // nằm trong `.generated_artifacts/captures/evidence/…`, mà khuôn cũ coi cả thư mục `captures/`
    // là ảnh — nếu xét sau thì một tệp `.txt` lại thành tile ảnh hỏng.
    const relativePath = workspaceRelative(cleanHref)
    if (relativePath && tools.onOpenFile && isEvidenceFileLink(cleanHref)) {
      const label = tools.fileLinkLabel ?? DEFAULT_FILE_LINK_LABEL
      return (
        <button
          type="button"
          onClick={() => tools.onOpenFile?.(relativePath)}
          data-artifact-open="files"
          data-artifact-path={relativePath}
          aria-label={`${label}: ${relativePath}`}
          title={relativePath}
          className="inline-flex max-w-full items-center gap-1 rounded-md border border-line bg-panel2/70 px-1.5 py-0.5 font-mono text-[11px] text-brand transition cursor-pointer hover:border-brand/60"
        >
          {/* Nút không được chứa nút: ảnh trong liên kết ở đây cũng là ảnh thường. */}
          <span className="max-w-full truncate">
            <PassiveMediaContext.Provider value={true}>{children}</PassiveMediaContext.Provider>
            {!children && relativePath}
          </span>
          <span className="shrink-0 text-[11px] font-sans text-muted">{label}</span>
        </button>
      )
    }
    if (isImageLink(cleanHref)) {
      if (tools.onOpenImage) {
        const label = typeof children === 'string' ? children : ''
        return <AnswerImageTile path={cleanHref} caption={label} tools={tools} />
      }
      return renderStaticAnchor({ href, children })
    }
    // Link thường: giữ NGUYÊN `href` thô (trình duyệt tự hiểu), nhưng bên trong không có điều khiển
    // tương tác nào — ảnh lồng trong link là ảnh thường, bấm cả khối thì đi theo link.
    return (
      <a
        href={href}
        target="_blank"
        rel="noreferrer"
        className="text-brand hover:underline font-medium cursor-pointer"
      >
        <PassiveMediaContext.Provider value={true}>{children}</PassiveMediaContext.Provider>
      </a>
    )
  }
}

function renderStaticAnchor(props: AnchorProps): ReactNode {
  const renderer = STATIC_COMPONENTS.a as unknown as (p: AnchorProps) => ReactNode
  return renderer(props)
}

export const MarkdownRenderer = memo(function MarkdownRenderer({
  content,
  isStreaming = false,
  variant = 'chat',
  onOpenImage,
  onOpenFile,
  fileLinkLabel,
}: MarkdownRendererProps) {
  const safeContent = useMemo(() => {
    return isStreaming ? makeStreamingSafe(content) : content
  }, [content, isStreaming])

  // Không có callback nào ⇒ dùng thẳng bộ tĩnh (không dựng lại gì), như trước vòng 23.
  const components = useMemo(
    () =>
      onOpenImage || onOpenFile
        ? ({ ...STATIC_COMPONENTS, img: makeImgRenderer({ onOpenImage, onOpenFile, fileLinkLabel }), a: makeAnchorRenderer({ onOpenImage, onOpenFile, fileLinkLabel }) } as Components)
        : STATIC_COMPONENTS,
    [onOpenImage, onOpenFile, fileLinkLabel],
  )

  return (
    <div
      className={`markdown-body text-xs leading-relaxed text-fg select-text space-y-2 font-normal ${
        variant === 'document' ? 'w-full min-w-0 [overflow-wrap:anywhere]' : ''
      }`}
    >
      <ReactMarkdown
        remarkPlugins={REMARK_PLUGINS}
        rehypePlugins={REHYPE_PLUGINS}
        components={components}
      >
        {safeContent}
      </ReactMarkdown>

      {/* Con trỏ nhấp nháy khi đang stream */}
      {isStreaming && (
        <span className="inline-block size-2 rounded-full bg-brand animate-pulse ml-0.5 align-middle" />
      )}
    </div>
  )
})

/** Khung hiển thị khối Code có header ngôn ngữ và nút Copy */
function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel2 font-mono text-xs shadow-xs my-2.5 [content-visibility:auto] [contain-intrinsic-size:1px_140px]">
      <div className="flex items-center justify-between border-b border-line bg-panel px-3.5 py-1.5 text-[11px] text-muted select-none">
        <span className="font-medium text-fg uppercase text-[11px] tracking-wide">{language}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-fg transition cursor-pointer text-[11px]"
          title="Copy code"
        >
          {copied ? (
            <>
              <Check className="size-3 text-emerald-500" />
              <span className="text-[11px] text-emerald-500 font-sans">Copied</span>
            </>
          ) : (
            <>
              <Copy className="size-3" />
              <span className="text-[11px] font-sans">Copy</span>
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
