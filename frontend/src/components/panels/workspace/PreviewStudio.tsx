/**
 * Studio xem trước file — overlay chiếm panel,分支 theo previewKind:
 * ảnh (zoom + kích thước), video/âm thanh (<video>/<audio>), code (tokenizer +
 * số dòng + Copy + Mở trong VS Code Web), text (dòng + Copy), PDF (<iframe>),
 * markdown (MarkdownRenderer chung), unknown (tải về + badge nhị phân).
 */
import { Check, Copy, X, Zap, ZoomIn, ZoomOut } from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useT } from '../../../i18n/context'
import { MarkdownRenderer } from '../../chat/MarkdownRenderer'
import { basename, byLine, tokenize, type PreviewKind, type WorkspaceContent, type WorkspaceEntry, type WorkspaceRepository, type TokenKind, type Token } from '../../../lib/workspace'

interface PreviewStudioProps {
  path: string
  entry: WorkspaceEntry | null
  content: WorkspaceContent | null
  kind: PreviewKind
  repository: WorkspaceRepository
  onClose: () => void
  onOpenInIde: (path: string) => void
}

const TOKEN_CLASS: Record<TokenKind, string> = {
  comment: 'text-muted italic',
  string: 'text-emerald-400',
  keyword: 'text-brand',
  number: 'text-amber-400',
  property: 'text-sky-400',
  operator: 'text-zinc-500',
  plain: 'text-fg',
}

export function PreviewStudio({
  path,
  entry,
  content,
  kind,
  repository,
  onClose,
  onOpenInIde,
}: PreviewStudioProps) {
  const t = useT()
  const name = entry?.name ?? basename(path)
  const showIdeButton = kind === 'code' || kind === 'text' || kind === 'markdown'
  const showCopy = kind === 'code' || kind === 'text' || kind === 'markdown'

  // Phím Escape đóng nhanh overlay mà không cần rê chuột tới nút X.
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div className="absolute inset-0 z-30 flex flex-col bg-panel">
      <header className="flex items-center gap-2 border-b border-line px-3 py-2">
        <span className="truncate font-mono text-[12px] text-fg">{name}</span>
        <span className="rounded bg-panel2 px-1.5 py-0.5 text-[10px] font-medium uppercase text-muted">{kind}</span>
        <div className="ml-auto flex items-center gap-1.5">
          {showCopy && content && <CopyButton text={content.content} label={t('workspace.copy')} copiedLabel={t('workspace.copied')} />}
          {showIdeButton && (
            <button
              type="button"
              onClick={() => onOpenInIde(path)}
              className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] font-medium text-muted transition hover:border-brand/40 hover:text-fg"
            >
              <Zap className="size-3.5 text-brand" />
              <span className="hidden sm:inline">{t('workspace.openInIde')}</span>
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label={t('workspace.closePreview')}
            className="inline-flex size-7 items-center justify-center rounded-md border border-line text-muted transition hover:text-fg"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {kind === 'image' && <ImagePreview src={repository.mediaUrl(path)} />}
        {kind === 'video' && (
          <div className="flex h-full items-center justify-center p-3">
            <video controls src={repository.mediaUrl(path)} className="max-h-full max-w-full" />
          </div>
        )}
        {kind === 'audio' && (
          <div className="flex h-full items-center justify-center p-6">
            <audio controls src={repository.mediaUrl(path)} className="w-full max-w-md" />
          </div>
        )}
        {kind === 'pdf' && <iframe src={repository.mediaUrl(path)} title={name} className="size-full border-0 bg-white" />}
        {kind === 'markdown' && content && (
          <div className="h-full overflow-auto px-4 py-3">
            <MarkdownRenderer variant="document" content={content.content} />
          </div>
        )}
        {kind === 'code' && content && <CodeView source={content.content} language={content.language} />}
        {kind === 'text' && content && <TextView source={content.content} />}
        {kind === 'unknown' && <UnknownPreview href={repository.downloadUrl(path)} binary={content?.binary ?? true} />}
      </div>
    </div>
  )
}

function ImagePreview({ src }: { src: string }) {
  const t = useT()
  const [scale, setScale] = useState(1)
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-1.5 border-b border-line px-3 py-1.5 text-[11px] text-muted">
        <button
          type="button"
          aria-label={t('workspace.zoomOut')}
          onClick={() => setScale((s) => Math.max(0.25, s - 0.25))}
          className="inline-flex size-6 items-center justify-center rounded border border-line hover:text-fg"
        >
          <ZoomOut className="size-3.5" />
        </button>
        <button
          type="button"
          aria-label={t('workspace.zoomIn')}
          onClick={() => setScale((s) => Math.min(6, s + 0.25))}
          className="inline-flex size-6 items-center justify-center rounded border border-line hover:text-fg"
        >
          <ZoomIn className="size-3.5" />
        </button>
        <span className="font-mono">{Math.round(scale * 100)}%</span>
        {dims && <span className="ml-2 font-mono">{t('workspace.dimensions', { w: dims.w, h: dims.h })}</span>}
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <img
          src={src}
          alt=""
          onLoad={(e) => {
            const img = e.currentTarget
            if (img.naturalWidth) setDims({ w: img.naturalWidth, h: img.naturalHeight })
          }}
          style={{ transform: `scale(${scale})`, transformOrigin: 'top left' }}
          className="max-w-none origin-top-left"
        />
      </div>
    </div>
  )
}

function CodeView({ source, language }: { source: string; language: string | null }) {
  const lines = useMemo(() => byLine(source, tokenize(source, language ?? 'text')), [source, language])
  const lineTexts = useMemo(() => source.split('\n'), [source])
  return (
    <pre className="m-0 min-h-0 flex-1 overflow-auto bg-panel font-mono text-[12px] leading-relaxed">
      <code className="block">
        {lines.map((line) => {
          const text = lineTexts[line.number - 1] ?? ''
          return (
            <div key={line.number} className="flex">
              <span className="sticky left-0 w-12 shrink-0 select-none bg-panel pr-2 text-right text-muted">
                {line.number}
              </span>
              <span className="min-w-0 flex-1 whitespace-pre px-2">
                {renderLine(line.tokens, text) || '\u00a0'}
              </span>
            </div>
          )
        })}
      </code>
    </pre>
  )
}

function TextView({ source }: { source: string }) {
  const lines = useMemo(() => source.split('\n'), [source])
  return (
    <pre className="m-0 min-h-0 flex-1 overflow-auto bg-panel font-mono text-[12px] leading-relaxed">
      <code className="block">
        {lines.map((text, i) => (
          <div key={i} className="flex">
            <span className="sticky left-0 w-12 shrink-0 select-none bg-panel pr-2 text-right text-muted">{i + 1}</span>
            <span className="min-w-0 flex-1 whitespace-pre px-2">{text || '\u00a0'}</span>
          </div>
        ))}
      </code>
    </pre>
  )
}

function UnknownPreview({ href, binary }: { href: string; binary: boolean }) {
  const t = useT()
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="text-[12px] text-muted">{t('workspace.noPreview')}</p>
      {binary && (
        <span className="rounded bg-panel2 px-2 py-0.5 text-[10px] font-semibold uppercase text-muted">
          {t('workspace.binary')}
        </span>
      )}
      <a
        href={href}
        download
        className="rounded-md border border-line px-3 py-1.5 text-[11px] font-medium text-fg transition hover:border-brand/40"
      >
        {t('workspace.download')}
      </a>
    </div>
  )
}

function CopyButton({ text, label, copiedLabel }: { text: string; label: string; copiedLabel: string }) {
  const [copied, setCopied] = useState(false)
  const onClick = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // clipboard có thể bị chặn — bỏ qua im lặng
    }
  }
  return (
    <button
      type="button"
      onClick={onClick}
      className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] font-medium text-muted transition hover:text-fg"
    >
      {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
      <span className="hidden sm:inline">{copied ? copiedLabel : label}</span>
    </button>
  )
}

/** Dịch token của một dòng thành các span, lấp khoảng trống bằng text thường. */
function renderLine(tokens: Token[], text: string): ReactNode {
  const parts: ReactNode[] = []
  let cursor = 0
  for (const tok of tokens) {
    if (tok.start > cursor) {
      parts.push(<span key={parts.length} className={TOKEN_CLASS.plain}>{text.slice(cursor, tok.start)}</span>)
    }
    parts.push(<span key={parts.length} className={TOKEN_CLASS[tok.kind]}>{text.slice(tok.start, tok.end)}</span>)
    cursor = tok.end
  }
  if (cursor < text.length) {
    parts.push(<span key={parts.length} className={TOKEN_CLASS.plain}>{text.slice(cursor)}</span>)
  }
  return parts
}
