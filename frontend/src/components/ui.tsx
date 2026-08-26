/**
 * Vài mảnh giao diện nhỏ dùng lại khắp nơi.
 *
 * `PlainText` là mảnh QUAN TRỌNG NHẤT ở đây: mọi nội dung đến từ dữ liệu
 * (kết quả tool, nội dung file, chỉ thị độc) đều phải đi qua nó. Nó render
 * bằng con của React nên chuỗi luôn được escape — không có đường nào để một
 * chỉ thị độc biến thành HTML thật. ESLint đã chặn `dangerouslySetInnerHTML`
 * ở `eslint.config.js`.
 */
import type { ReactNode } from 'react'

export function IconButton({
  label,
  onClick,
  children,
  active = false,
  className = '',
}: {
  label: string
  onClick?: () => void
  children: ReactNode
  active?: boolean
  className?: string
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={`inline-flex size-7 items-center justify-center rounded-md text-muted transition hover:bg-panel2 hover:text-fg ${
        active ? 'bg-panel2 text-fg' : ''
      } ${className}`}
    >
      {children}
    </button>
  )
}

export function Chip({
  children,
  title,
  tone = 'neutral',
}: {
  children: ReactNode
  title?: string
  tone?: 'neutral' | 'brand' | 'warn' | 'danger'
}) {
  const tones: Record<string, string> = {
    neutral: 'bg-panel2 text-muted ring-1 ring-line',
    brand: 'bg-brand/15 text-brand ring-1 ring-brand/40',
    warn: 'bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/40 dark:text-amber-300',
    danger: 'bg-red-500/15 text-red-700 ring-1 ring-red-500/40 dark:text-red-300',
  }
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded px-1.5 py-px text-[10px] font-semibold tracking-wide ${tones[tone]}`}
    >
      {children}
    </span>
  )
}

/**
 * Chip trạng thái kết nối trên thanh công cụ của panel (to hơn `Chip` ở trên, có
 * chấm tròn dẫn đầu). Khung ④ và tab IDE dùng chung để hai kênh nhìn giống nhau:
 * `live` = đang nhận dữ liệu thật, `busy` = đang nối/đang thăm dò, `warn` = chưa
 * nối được hoặc đang xem dữ liệu mô phỏng.
 */
export function StatusChip({
  tone,
  pulse = false,
  children,
}: {
  tone: 'live' | 'busy' | 'warn'
  /** Chấm tròn nhấp nháy — chỉ bật khi dữ liệu đang chảy về thật. */
  pulse?: boolean
  children: ReactNode
}) {
  const tones: Record<string, { box: string; dot: string }> = {
    live: {
      box: 'bg-emerald-500/15 text-emerald-700 ring-1 ring-emerald-500/40 dark:text-emerald-300',
      dot: 'bg-emerald-500',
    },
    busy: { box: 'bg-brand/15 text-brand ring-1 ring-brand/40', dot: 'bg-brand' },
    warn: {
      box: 'bg-amber-500/15 text-amber-700 ring-1 ring-amber-500/40 dark:text-amber-300',
      dot: 'bg-amber-500',
    },
  }
  const { box, dot } = tones[tone]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-semibold ${box}`}
    >
      <span className={`size-1.5 rounded-full ${dot} ${pulse ? 'animate-pulse' : ''}`} />
      {children}
    </span>
  )
}

/**
 * Nội dung dạng VĂN BẢN THUẦN. Dùng cho mọi thứ đến từ dữ liệu.
 * Không có prop nào nhận HTML — đó là điểm chính của component này.
 */
export function PlainText({ text, className = '' }: { text: string; className?: string }) {
  return (
    <pre
      className={`overflow-x-auto whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed ${className}`}
    >
      {text}
    </pre>
  )
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
      {children}
    </div>
  )
}

export function PanelShell({
  title,
  note,
  toolbar,
  children,
}: {
  title: string
  note?: string
  toolbar?: ReactNode
  children: ReactNode
}) {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="text-[13px] font-semibold">{title}</h2>
        {toolbar}
      </div>
      {note && (
        <p className="border-b border-line bg-panel2 px-3 py-1.5 text-[11px] text-muted">{note}</p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">{children}</div>
    </div>
  )
}
