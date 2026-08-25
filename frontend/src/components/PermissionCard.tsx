/**
 * Thẻ xin quyền (PermissionCard).
 *
 * Năm phần đúng thứ tự:
 *  1. Tool + tham số
 *  2. Nội dung nguyên văn (write_file hiện diff tự viết)
 *  3. Lý do — bằng tiếng người
 *  4. Nguồn gốc (derived_from) — bấm được
 *  5. Nút quyết định: 3 nút cho sạch, 4 nút cho bẩn
 *
 * Bộ đếm ngược 10 phút. Hết giờ → "đã quá hạn — tính là TỪ CHỐI".
 * Mock rút ngắn bằng hằng số, nhưng mặc định phải là 10 phút thật.
 */
import { useMemo, useState } from 'react'
import { useT } from '../i18n/context'
import { useNow } from '../hooks/useNow'
import { useAgentStore } from '../store/agentStore'
import { useUiStore } from '../store/uiStore'
import { PlainText, Chip, SectionLabel } from './ui'
// Integrity/Confidentiality values are used implicitly via PermissionRequest fields.
import type { PermissionRequest } from '../types/agent'
import type { PermissionButtonId } from '../lib/permissions'
import { getPermissionButtons } from '../lib/permissions'
import type { DiffLine } from '../types/agent'

// Countdown uses expires_at from the request itself.
export function PermissionCard({ request }: { request: PermissionRequest }) {
  const t = useT()
  const now = useNow()
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const openSource = useUiStore((s) => s.openSource)
  const [resolved, setResolved] = useState(false)

  const isResolved = resolved || request.status !== 'dang_cho'

  // Đếm ngược từ expires_at
  const expiresAtMs = useMemo(() => Date.parse(request.expires_at), [request.expires_at])
  const remaining = useMemo(() => Math.max(0, expiresAtMs - now), [expiresAtMs, now])
  const timedOut = remaining <= 0
  const remainingSec = Math.ceil(remaining / 1000)
  const remainingMin = Math.floor(remainingSec / 60)
  const remainingSecPart = remainingSec % 60

  const effectiveResolved = isResolved || timedOut

  const buttons = useMemo(
    () => (effectiveResolved ? [] : getPermissionButtons(request.context_dirty)),
    [effectiveResolved, request.context_dirty],
  )

  const handleClick = (button: PermissionButtonId) => {
    setResolved(true)
    sendCommand({
      type: 'permission_response',
      request_id: request.request_id,
      button,
    })
  }

  const isWriteFile = request.tool_name === 'write_file'

  return (
    <div
      className={`rounded-lg border-2 p-3 shadow-lg ${
        effectiveResolved
          ? 'border-line bg-bg'
          : timedOut
            ? 'border-red-500/50 bg-red-50 dark:bg-red-950/20'
            : 'border-amber-500/50 bg-bg shadow-amber-500/10'
      }`}
    >
      {/* 1. Tool + tham số */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Chip tone="brand">{request.tool_name}</Chip>
        <span className="text-[11px] font-mono text-muted">
          {Object.entries(request.params)
            .map(([k, v]) => `${k}=${v}`)
            .join('  ')}
        </span>
        {effectiveResolved && (
          <Chip
            tone={
              request.decision === 'tu_choi' || timedOut ? 'danger' : 'neutral'
            }
          >
            {timedOut
              ? 'Đã quá hạn'
              : request.decision
                ? t(
                    `permission.button.${request.decision}` as 'permission.button.cho_phep_mot_lan',
                  )
                : 'Đã quyết định'}
          </Chip>
        )}
      </div>

      {/* 2. Nội dung nguyên văn */}
      <SectionLabel>Nội dung</SectionLabel>
      <div className="mb-2 max-h-48 overflow-auto rounded border border-line bg-panel2 p-2">
        {isWriteFile && request.diff ? (
          <DiffView diff={request.diff} filePath={String(request.params['path'] ?? '')} />
        ) : (
          <PlainText text={request.raw_content ?? ''} />
        )}
      </div>

      {/* 3. Lý do */}
      <SectionLabel>Vì sao phải hỏi</SectionLabel>
      <p className="mb-2 text-[12px] leading-relaxed">{request.reason}</p>

      {/* 4. Nguồn gốc */}
      {request.derived_from.length > 0 && (
        <>
          <SectionLabel>Nguồn gốc</SectionLabel>
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            {request.derived_from.map((labelId) => (
              <button
                key={labelId}
                type="button"
                onClick={() => openSource(labelId)}
                className="rounded bg-panel2 px-1.5 py-px text-[11px] font-mono text-brand hover:underline"
              >
                {labelId}
              </button>
            ))}
          </div>
        </>
      )}

      {/* 5. Nút */}
      {!effectiveResolved && (
        <div className="flex flex-wrap items-center gap-2">
          {buttons.map((button) => (
            <PermissionButton
              key={button}
              button={button}
              onClick={handleClick}
            />
          ))}
          {/* Đồng hồ đếm ngược */}
          <span
            className={`ml-auto text-[11px] font-mono tabular-nums ${
              remaining < 60000 ? 'text-red-500' : 'text-muted'
            }`}
          >
            {remainingMin}:{String(remainingSecPart).padStart(2, '0')}
          </span>
        </div>
      )}
      {timedOut && !isResolved && (
        <p className="mt-2 text-[12px] font-medium text-red-600 dark:text-red-400">
          Yêu cầu đã quá hạn 10 phút — tự động tính là TỪ CHỐI.
        </p>
      )}
    </div>
  )
}

function PermissionButton({
  button,
  onClick,
}: {
  button: PermissionButtonId
  onClick: (button: PermissionButtonId) => void
}) {
  const t = useT()

  const style =
    button === 'tu_choi'
      ? 'border-red-300 text-red-700 hover:bg-red-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30'
      : button === 'chuan_thuan_artifact'
        ? 'border-amber-400 text-amber-800 hover:bg-amber-50 dark:border-amber-600 dark:text-amber-200 dark:hover:bg-amber-950/30'
        : 'border-brand/50 text-brand hover:bg-brand/10'

  return (
    <button
      type="button"
      onClick={() => onClick(button)}
      className={`rounded-md border px-2.5 py-1 text-[12px] font-medium transition ${style}`}
    >
      {t(`permission.button.${button}` as 'permission.button.cho_phep_mot_lan')}
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Diff tự viết (không thư viện ngoài)                                 */
/* ------------------------------------------------------------------ */

function DiffView({ diff, filePath }: { diff: DiffLine[]; filePath: string }) {
  return (
    <div className="overflow-x-auto font-mono text-[11px] leading-relaxed">
      <p className="mb-1 border-b border-line pb-1 text-[10px] text-muted">{filePath}</p>
      {diff.map((dline, index) => (
        <div
          key={index}
          className={`whitespace-pre ${
            dline.kind === 'them'
              ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
              : dline.kind === 'bot'
                ? 'bg-red-500/10 text-red-700 dark:text-red-300'
                : ''
          }`}
        >
          <span className="mr-2 inline-block w-5 select-none text-right text-muted">
            {dline.kind === 'them' ? '+' : dline.kind === 'bot' ? '-' : ' '}
          </span>
          {dline.text}
        </div>
      ))}
    </div>
  )
}
