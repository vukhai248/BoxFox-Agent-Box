/**
 * Chấm màu nhãn + badge chữ.
 *
 * LUẬT: KHÔNG BAO GIỜ chỉ dùng màu. Mỗi chấm phải có `title` bằng chữ để
 * người mù màu, ảnh chụp đen trắng, hay người đọc bằng trình đọc màn hình
 * vẫn biết nhãn là gì.
 */
import { CONFIDENTIALITY_META, INTEGRITY_META } from '../lib/labels'
import type { Confidentiality, Integrity } from '../types/labels'

interface LabelProps {
  integrity?: Integrity
  confidentiality?: Confidentiality
  className?: string
}

export function LabelDot({ integrity, confidentiality, className = '' }: LabelProps) {
  return (
    <span className={`inline-flex items-center gap-1 ${className}`}>
      {integrity && (
        <span
          className={`size-2 shrink-0 rounded-full ${INTEGRITY_META[integrity].dotClass}`}
          title={`Integrity: ${INTEGRITY_META[integrity].label}`}
          aria-label={`Integrity: ${INTEGRITY_META[integrity].label}`}
          role="img"
        />
      )}
      {confidentiality && (
        <span
          className={`size-2 shrink-0 rounded-full ${CONFIDENTIALITY_META[confidentiality].dotClass}`}
          title={`Confidentiality: ${CONFIDENTIALITY_META[confidentiality].label}`}
          aria-label={`Confidentiality: ${CONFIDENTIALITY_META[confidentiality].label}`}
          role="img"
        />
      )}
    </span>
  )
}

export function IntegrityBadge({ value }: { value: Integrity }) {
  const meta = INTEGRITY_META[value]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-medium ${meta.badgeClass}`}
    >
      <span className={`size-1.5 rounded-full ${meta.dotClass}`} />
      {meta.label}
    </span>
  )
}

export function ConfidentialityBadge({ value }: { value: Confidentiality }) {
  const meta = CONFIDENTIALITY_META[value]
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded px-1.5 py-0.5 text-[11px] font-medium ${meta.badgeClass}`}
    >
      <span className={`size-1.5 rounded-full ${meta.dotClass}`} />
      {meta.label}
    </span>
  )
}
