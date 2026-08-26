/**
 * Tab IDE — nhúng code-server (VS Code bản web) đang chạy trong box.
 *
 * Mở tab ra là editor chiếm hết chỗ: người dùng không phải mở máy ảo ở khung ④
 * rồi tự gõ `http://localhost:8080` trong Chromium của box nữa. Cùng một tiến
 * trình code-server, cùng một `/home/agent/workspace`.
 *
 * Ba trạng thái do `useIdeFrame()` quyết định (`probing` / `live` / `offline`);
 * panel này không tự `fetch`, không tự đếm thời gian.
 *
 * Về `sandbox` của iframe: code-server cần khá nhiều quyền để chạy được
 * (scripts, same-origin cho service worker + webview của chính nó, forms,
 * downloads, popups, modal), nhưng danh sách cấp-đúng-những-thứ-đó vẫn còn giá
 * trị: nó KHÔNG cấp `allow-top-navigation`, nên trang trong khung không thể tự
 * điều hướng cả giao diện BoxFox sang chỗ khác. Iframe khác origin thì vốn đã
 * không đọc được DOM của giao diện này, nhưng "không đọc được DOM" không thay
 * cho "không đổi được URL của tab".
 *
 * Về nhãn: nội dung trong editor là file BÊN TRONG box, có thể do agent tải từ
 * web về, nên panel viết thẳng integrity `khong_tin_duoc` — giống quy tắc M1 ở
 * khung ④ (mục 8.5) và cùng lý do: không có nhãn nào do Controller cấp cho
 * luồng này, nên không được ngầm coi là tin được. Thao tác gõ/sửa của người dùng
 * trong đây đi TRỰC TIẾP tới box, không qua kênh agent và chưa vào sổ audit
 * (cùng caveat V4 như khung ④, mục 12.3.1).
 */
import { useState } from 'react'
import { ChevronDown, ChevronUp, ExternalLink } from 'lucide-react'
import { useT, type TKey } from '../../i18n/context'
import { useIdeFrame } from '../../hooks/useIdeFrame'
import { useNow } from '../../hooks/useNow'
import { retrySecondsLeft } from '../../lib/retry'
import type { IdeOfflineReason } from '../../lib/ide/state'
import { PanelShell, StatusChip } from '../ui'
import { IntegrityBadge } from '../LabelDot'

/** Map lý do offline → khoá i18n. Record chứ không nối chuỗi động — TKey vẫn kiểm được lúc biên dịch. */
const OFFLINE_REASON_KEY: Record<IdeOfflineReason, TKey> = {
  unreachable: 'ide.reason.unreachable',
  timeout: 'ide.reason.timeout',
  mixedContent: 'ide.reason.mixedContent',
  off: 'ide.reason.off',
}

function ProbingCard({ url }: { url: string }) {
  const t = useT()
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center"
    >
      <span
        className="size-6 animate-spin rounded-full border-2 border-line border-t-brand"
        aria-hidden="true"
      />
      <p className="text-[13px] font-semibold">{t('ide.probingTitle')}</p>
      <code className="rounded bg-panel2 px-2 py-1 text-[11px] text-muted">{url}</code>
    </div>
  )
}

function OfflineCard({
  url,
  reason,
  retrySeconds,
  onRetry,
}: {
  url: string
  reason: IdeOfflineReason | null
  retrySeconds: number | null
  onRetry: () => void
}) {
  const t = useT()
  const [showHelp, setShowHelp] = useState(false)
  const isOff = reason === 'off'
  // `alert` là assertive: trình đọc màn hình đọc lại CẢ thẻ mỗi lần nội dung đổi,
  // mà số giây đếm ngược đổi mỗi giây. Nên chỉ dùng `alert` khi đã hết lượt (tin
  // xấu cuối cùng, không đổi nữa); còn lúc đang chờ thử lại thì dùng `status`.
  const isWaitingToRetry = retrySeconds !== null
  return (
    <div
      role={isWaitingToRetry ? 'status' : 'alert'}
      aria-live={isWaitingToRetry ? 'polite' : undefined}
      className="flex h-full items-center justify-center p-6"
    >
      <div className="max-w-[52ch] rounded-lg border border-amber-500/40 bg-amber-500/10 p-4 text-amber-800 dark:text-amber-200">
        <p className="text-[12px] font-bold uppercase tracking-wide">
          {isOff ? t('ide.offTitle') : t('ide.offlineTitle')}
        </p>
        {reason && (
          <p className="mt-1 text-[11px] leading-relaxed">{t(OFFLINE_REASON_KEY[reason], { url })}</p>
        )}
        {!isOff && (
          <>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={onRetry}
                className="rounded-md bg-fg px-3 py-1.5 text-[11px] font-semibold text-bg"
              >
                {t('ide.retry')}
              </button>
              <button
                type="button"
                aria-expanded={showHelp}
                onClick={() => setShowHelp((v) => !v)}
                className="rounded-md border border-line px-3 py-1.5 text-[11px] font-semibold text-muted hover:text-fg"
              >
                {t('ide.howToStartBox')}
              </button>
              {retrySeconds !== null && (
                // aria-hidden: đồng hồ đếm ngược là thông tin thị giác; đọc lại
                // mỗi giây thì gây ồn mà không thêm thông tin nào.
                <span aria-hidden="true" className="text-[11px]">
                  {t('ide.retryCountdown', { seconds: retrySeconds })}
                </span>
              )}
            </div>
            {showHelp && (
              <div className="mt-2 rounded-md bg-panel2 p-2 text-[11px] text-muted">
                <p>{t('ide.howToStartBoxBody')}</p>
                <code className="mt-1 block rounded bg-panel px-2 py-1">
                  cd deploy/docker &amp;&amp; docker compose up -d
                </code>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

/** Drawer chi tiết IDE — trượt từ trên như Machine, không chiếm đáy khi đóng. */
function IdeDetailsDrawer() {
  const t = useT()
  return (
    <div className="shrink-0 animate-in slide-in-from-top-1 overflow-hidden border-b border-line bg-panel2 duration-200">
      <div className="px-3 py-2">
        <div className="flex flex-wrap items-center gap-2">
          <IntegrityBadge value="khong_tin_duoc" />
          <span className="text-[11px] text-muted">{t('ide.a3DataNotCommand')}</span>
        </div>
        <div className="mt-1.5 space-y-1">
          <p className="text-[11px] leading-relaxed text-muted">{t('ide.labelUnknown')}</p>
          <p className="text-[11px] leading-relaxed text-muted">{t('ide.inputNotAudited')}</p>
          <p className="text-[11px] leading-relaxed text-muted">{t('ide.noAiInBox')}</p>
        </div>
      </div>
    </div>
  )
}

export function IdePanel() {
  const t = useT()
  const now = useNow()
  const ide = useIdeFrame()
  const [detailsOpen, setDetailsOpen] = useState(false)

  const statusChip =
    ide.phase === 'live' ? (
      <StatusChip tone="live" pulse>
        {t('ide.liveChip')}
      </StatusChip>
    ) : ide.phase === 'probing' ? (
      <StatusChip tone="busy">{t('ide.probingChip')}</StatusChip>
    ) : (
      <StatusChip tone="warn">
        {ide.reason === 'off' ? t('ide.offChip') : t('ide.offlineChip')}
      </StatusChip>
    )

  // Nguồn `off` thì KHÔNG có nút nào: không thăm dò nên "thử lại" là ngõ cụt, và
  // không có địa chỉ nào đáng mở ở tab mới.
  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {statusChip}
      {ide.source === 'codeServer' && (
        <>
          <button
            type="button"
            onClick={ide.retry}
            className="rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
          >
            {ide.phase === 'live' ? t('ide.reload') : t('ide.retry')}
          </button>
          <a
            href={ide.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
          >
            <ExternalLink className="size-3" />
            {t('ide.openInNewTab')}
          </a>
        </>
      )}
      {ide.phase === 'live' && (
        <button
          type="button"
          aria-expanded={detailsOpen}
          onClick={() => setDetailsOpen((v) => !v)}
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition ${
            detailsOpen
              ? 'border-brand bg-brand/15 text-brand'
              : 'border-line text-muted hover:border-brand/40 hover:text-fg'
          }`}
        >
          {t('ide.details')}
          {detailsOpen ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
        </button>
      )}
    </div>
  )

  const note =
    ide.phase === 'live'
      ? t('ide.liveNote')
      : ide.phase === 'probing'
        ? t('ide.probingNote')
        : undefined

  const retrySeconds = ide.retryAtMs !== null ? retrySecondsLeft(ide.retryAtMs, now) : null

  return (
    <PanelShell title={t('ide.title')} toolbar={toolbar} note={note}>
      <div className="flex h-full min-h-0 flex-col">
        {ide.phase === 'live' ? (
          <>
            {detailsOpen && <IdeDetailsDrawer />}
            <iframe
              src={ide.url}
              title={t('ide.frameLabel')}
              allow="clipboard-read; clipboard-write"
              // Cấp đúng những gì code-server cần, và cố ý BỎ
              // `allow-top-navigation*` để trang trong khung không điều hướng
              // được cả tab BoxFox đi nơi khác.
              sandbox="allow-scripts allow-same-origin allow-forms allow-downloads allow-modals allow-popups allow-popups-to-escape-sandbox"
              className="min-h-0 w-full flex-1 border-0 bg-white dark:bg-slate-900"
            />
          </>
        ) : ide.phase === 'probing' ? (
          <ProbingCard url={ide.url} />
        ) : (
          <OfflineCard
            url={ide.url}
            reason={ide.reason}
            retrySeconds={retrySeconds}
            onRetry={ide.retry}
          />
        )}
      </div>
    </PanelShell>
  )
}
