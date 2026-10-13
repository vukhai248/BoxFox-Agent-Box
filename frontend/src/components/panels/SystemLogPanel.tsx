/**
 * Khung Nhật ký hệ thống — bảng DEV đọc nhật ký harness/router (việc 5, bản v2).
 *
 * Khác bảng Terminal: Terminal chạy shell TRONG box (agent thấy được mọi thứ), còn
 * nhật ký này nằm ở `~/BoxFox/logs` trên HOST, ngoài box — nên agent không đọc,
 * không sửa, không xoá được nó (kế hoạch §1, §3.2). Bảng chỉ ĐỌC: dữ liệu đến từ
 * `GET /api/agent/system-log`, không có route nào để ghi từ đây.
 *
 * Khung, lớp CSS và i18n dùng lại y nguyên của các bảng cạnh nó
 * (`PanelShell`/`StatusChip`, token `border-line`/`bg-panel2`/`text-muted`).
 *
 * Kế hoạch: `docs/plan/dev-system-log-plan.md` §3.1 (API), §3.3 (bảng), §3.4 (nhịp 2
 * giây khi đang mở), §3.5 (nhóm lỗi theo `code`).
 */
import { useCallback, useMemo, useState } from 'react'
import { ClipboardCopy, RotateCcw, ScrollText } from 'lucide-react'
import { useT } from '../../i18n/context'
import { PanelShell, StatusChip } from '../ui'
import {
  SYSTEM_LOG_DEFAULT_LINES,
  useSystemLog,
  type SystemLogEntry,
} from '../../hooks/useSystemLog'

const LEVEL_OPTIONS = ['all', 'info', 'warn', 'error'] as const
const SOURCE_OPTIONS = ['all', 'harness', 'router'] as const
const LEVEL_CHIP_KEY = {
  all: 'systemLog.level.all',
  info: 'systemLog.level.info',
  warn: 'systemLog.level.warn',
  error: 'systemLog.level.error',
} as const
const SOURCE_CHIP_KEY = {
  all: 'systemLog.source.all',
  harness: 'systemLog.source.harness',
  router: 'systemLog.source.router',
} as const

/**
 * Một dòng nhật ký đọc được — cùng dạng `python scripts/system-log.py tail` in ra,
 * để bản sao chẩn đoán dán vào đâu cũng tra được bằng cùng công cụ.
 */
export function formatLogLine(entry: SystemLogEntry): string {
  const stamp = String(entry.ts ?? '').slice(11, 23)
  const level = String(entry.level ?? 'info').toUpperCase().slice(0, 5).padEnd(5)
  const event = String(entry.event ?? '').padEnd(16)
  const session = String(entry.sessionId ?? '').slice(0, 8).padEnd(8)
  const extra = [
    entry.code ?? null,
    entry.durationMs !== undefined && entry.durationMs !== null ? `${entry.durationMs}ms` : null,
  ]
    .filter((value): value is string => Boolean(value))
    .join(' ')
  return `${stamp} ${level} ${event} ${session} ${extra} ${entry.message ?? ''}`.trimEnd()
}

/**
 * Gom lỗi theo mã máy, y như `summary` của CLI: dòng lỗi không có `code` ở cấp ngoài
 * thì đọc `data.errorCode`, cuối cùng mới gắn `UNCLASSIFIED` (không in `None`).
 */
export function groupErrorCodes(entries: SystemLogEntry[]): { code: string; count: number }[] {
  const counts = new Map<string, number>()
  for (const entry of entries) {
    if (entry.level !== 'error') continue
    const inner = entry.data?.errorCode
    const code = entry.code || (typeof inner === 'string' && inner ? inner : 'UNCLASSIFIED')
    counts.set(code, (counts.get(code) ?? 0) + 1)
  }
  return Array.from(counts, ([code, count]) => ({ code, count })).sort(
    (left, right) => right.count - left.count || left.code.localeCompare(right.code),
  )
}

/** Văn bản của nút "Sao chép chẩn đoán": các dòng đang xem + phiên bản + commit. */
export function diagnosticsText(input: {
  entries: SystemLogEntry[]
  level: string
  source: string
  sessionId: string
  version: string | null
  commit: string | null
  runId: string | null
}): string {
  return [
    '# BoxFox - dev system log (harness, host-only)',
    `# version=${input.version ?? 'unknown'} commit=${input.commit ?? 'unknown'} run=${input.runId ?? 'unknown'}`,
    `# filter level=${input.level} source=${input.source} session=${input.sessionId.trim() || 'all'} lines=${input.entries.length}`,
    ...input.entries.map(formatLogLine),
  ].join('\n')
}

function levelTone(level: string): string {
  if (level === 'error') return 'text-rose-400'
  if (level === 'warn') return 'text-amber-300'
  return 'text-muted'
}

export function SystemLogPanel() {
  const t = useT()
  const [level, setLevel] = useState<string>('all')
  const [source, setSource] = useState<string>('all')
  const [sessionId, setSessionId] = useState('')
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')

  const { snapshot, error, refresh } = useSystemLog({
    level,
    source,
    sessionId,
    lines: SYSTEM_LOG_DEFAULT_LINES,
  })
  const entries = useMemo(() => snapshot?.entries ?? [], [snapshot])
  const groups = useMemo(() => groupErrorCodes(entries), [entries])

  const copyDiagnostics = useCallback(async () => {
    const text = diagnosticsText({
      entries,
      level,
      source,
      sessionId,
      version: snapshot?.version ?? null,
      commit: snapshot?.commit ?? null,
      runId: snapshot?.runId ?? null,
    })
    try {
      await navigator.clipboard.writeText(text)
      setCopyState('copied')
    } catch {
      // Không có quyền clipboard (ngữ cảnh không bảo mật, hoặc người dùng từ chối).
      setCopyState('failed')
    }
  }, [entries, level, source, sessionId, snapshot])

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      <StatusChip tone={snapshot?.exists ? 'live' : 'warn'} pulse={Boolean(snapshot?.exists)}>
        {snapshot?.exists ? t('systemLog.liveChip') : t('systemLog.missingChip')}
      </StatusChip>
      <select
        aria-label={t('systemLog.levelLabel')}
        value={level}
        onChange={(event) => setLevel(event.target.value)}
        className="rounded border border-line bg-panel px-1.5 py-0.5 text-[11px] text-fg"
      >
        {LEVEL_OPTIONS.map((value) => (
          <option key={value} value={value}>
            {t(LEVEL_CHIP_KEY[value])}
          </option>
        ))}
      </select>
      <select
        aria-label={t('systemLog.sourceLabel')}
        value={source}
        onChange={(event) => setSource(event.target.value)}
        className="rounded border border-line bg-panel px-1.5 py-0.5 text-[11px] text-fg"
      >
        {SOURCE_OPTIONS.map((value) => (
          <option key={value} value={value}>
            {t(SOURCE_CHIP_KEY[value])}
          </option>
        ))}
      </select>
      <input
        type="text"
        aria-label={t('systemLog.sessionLabel')}
        value={sessionId}
        onChange={(event) => setSessionId(event.target.value)}
        placeholder={t('systemLog.sessionPlaceholder')}
        className="w-32 rounded border border-line bg-panel px-1.5 py-0.5 font-mono text-[11px] text-fg placeholder:text-muted"
      />
      <button
        type="button"
        onClick={refresh}
        className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
      >
        <RotateCcw className="size-3.5" />
        {t('systemLog.refresh')}
      </button>
      <button
        type="button"
        data-testid="system-log-copy"
        onClick={() => void copyDiagnostics()}
        className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
      >
        <ClipboardCopy className="size-3.5" />
        {copyState === 'copied'
          ? t('systemLog.copied')
          : copyState === 'failed'
            ? t('systemLog.copyFailed')
            : t('systemLog.copy')}
      </button>
    </div>
  )

  return (
    <PanelShell title={t('systemLog.title')} note={t('systemLog.intro')} toolbar={toolbar}>
      <div
        data-testid="system-log-meta"
        className="flex flex-wrap items-center gap-2 border-b border-line bg-panel2/40 px-3 py-1 font-mono text-[11px] text-muted"
      >
        <ScrollText className="size-3 shrink-0" />
        <span>{snapshot?.file ?? 'harness.jsonl'}</span>
        <span>{t('systemLog.lineCount', { n: entries.length })}</span>
        <span>{t('systemLog.build', { version: snapshot?.version ?? 'unknown' })}</span>
        <span>{t('systemLog.commit', { commit: (snapshot?.commit ?? 'unknown').slice(0, 7) })}</span>
        <span>{t('systemLog.run', { run: snapshot?.runId ?? 'unknown' })}</span>
      </div>

      {error && (
        <div
          data-testid="system-log-error"
          className="flex items-center gap-2 border-b border-line bg-panel2/40 px-3 py-1.5 text-xs text-rose-400"
        >
          <ScrollText className="size-3.5 shrink-0" />
          <span>{t('systemLog.error', { message: error })}</span>
        </div>
      )}

      {groups.length > 0 && (
        <div data-testid="system-log-error-groups" className="border-b border-line bg-panel2/40 px-3 py-1.5">
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">
            {t('systemLog.errorGroups')}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {groups.map((group) => (
              <span
                key={group.code}
                data-testid={`system-log-error-code-${group.code}`}
                className="inline-flex items-center gap-1 rounded-full bg-rose-500/15 px-1.5 py-px text-[11px] font-semibold text-rose-400 ring-1 ring-rose-500/40"
              >
                <span className="font-mono">{group.code}</span>
                <span className="tabular-nums">×{group.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {entries.length === 0 ? (
        <div className="flex h-full items-center justify-center p-6 text-center">
          <p className="text-[12px] text-muted">
            {snapshot && !snapshot.exists ? t('systemLog.missingFile') : t('systemLog.empty')}
          </p>
        </div>
      ) : (
        <div className="p-0">
          {entries.map((entry, index) => (
            <div
              key={`${entry.ts}-${index}`}
              data-testid="system-log-line"
              className="flex items-start gap-2 border-b border-line/60 px-3 py-1 font-mono text-[11px]"
            >
              <span className="shrink-0 tabular-nums text-muted">{String(entry.ts ?? '').slice(11, 23)}</span>
              <span className={`w-11 shrink-0 font-semibold ${levelTone(entry.level)}`}>
                {String(entry.level ?? '').toUpperCase()}
              </span>
              <span className="shrink-0 text-fg">{entry.event}</span>
              {entry.sessionId && <span className="shrink-0 text-muted">{entry.sessionId.slice(0, 8)}</span>}
              {entry.code && <span className="shrink-0 text-rose-400">{entry.code}</span>}
              {entry.durationMs !== undefined && entry.durationMs !== null && (
                <span className="shrink-0 tabular-nums text-muted">{entry.durationMs}ms</span>
              )}
              <span className="min-w-0 flex-1 truncate text-muted">{entry.message}</span>
            </div>
          ))}
        </div>
      )}
    </PanelShell>
  )
}
