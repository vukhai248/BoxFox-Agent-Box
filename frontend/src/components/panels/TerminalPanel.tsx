/**
 * Khung Terminal thật — shell bash chạy TRONG box qua cầu tty-bridge.
 *
 * Kiến trúc: @xterm/xterm ⇄ WebSocket ⇄ ide-proxy /__tty/ws → tty-bridge :7681
 *   → PTY(bash -l) user `agent` tại /home/agent/workspace (quy tắc ⑥).
 *
 * Minh bạch nhãn: mọi output của terminal là dữ liệu từ máy — integrity
 * KHÔNG_TIN_ĐƯỢC (M1). Audit từng phiên terminal (actor:user — ②c) sẽ do
 * Controller ghi khi backend chạy; tty-bridge đã in log stderr sẵn để đón.
 */
import { RotateCcw } from 'lucide-react'
import { useT } from '../../i18n/context'
import { useBoxTerminal } from '../../hooks/useBoxTerminal'
import { PanelShell, StatusChip } from '../ui'

export function TerminalPanel() {
  const t = useT()
  const { containerRef, phase, url, retry } = useBoxTerminal()

  const statusChip =
    phase === 'live' ? (
      <StatusChip tone="live" pulse>
        {t('terminal.liveChip')}
      </StatusChip>
    ) : phase === 'connecting' ? (
      <StatusChip tone="busy">{t('terminal.connectingChip')}</StatusChip>
    ) : (
      <StatusChip tone="warn">{t('terminal.offlineChip')}</StatusChip>
    )

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {statusChip}
      {phase !== 'live' && (
        <button
          type="button"
          onClick={retry}
          className="flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
        >
          <RotateCcw className="size-3.5" />
          {t('terminal.retry')}
        </button>
      )}
    </div>
  )

  const note =
    phase === 'connecting'
      ? t('terminal.connectingNote')
      : phase === 'offline'
        ? t('terminal.offlineNote')
        : undefined

  return (
    <PanelShell title={t('terminal.title')} toolbar={toolbar} note={note}>
      <div className="relative h-full min-h-0 w-full">
        {/* Container xterm LUÔN mount (kể cả khi chưa live) để FitAddon đo đúng
            kích thước ngay lúc open; ẩn bằng opacity + đưa ra khỏi luồng. */}
        <div
          ref={containerRef}
          className={
            phase === 'live'
              ? 'h-full min-h-0 w-full px-2 py-1'
              : 'pointer-events-none absolute left-0 top-0 -z-10 h-40 w-64 overflow-hidden opacity-0'
          }
        />

        {phase === 'connecting' && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-[12px] text-muted">{t('terminal.connectingNote')}</p>
          </div>
        )}

        {phase === 'offline' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center">
            <p className="max-w-md text-[12px] leading-relaxed text-muted">
              {t('terminal.offlineNote')}
            </p>
            <button
              type="button"
              onClick={retry}
              className="flex items-center gap-2 rounded-md border border-line px-3 py-1.5 text-[11px] font-semibold text-muted hover:text-fg"
            >
              <RotateCcw className="size-3.5" />
              {t('terminal.retry')}
            </button>
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-panel2/60 px-3 py-1 text-[11px] text-muted">
        <span>{t('terminal.footerInfo')}</span>
        <span className="font-mono text-[10px]">
          {phase === 'live' ? url.replace(/^ws(s?):\/\//, '$1//') : url}
        </span>
      </div>
    </PanelShell>
  )
}
