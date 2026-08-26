/**
 * Khung ④ — Màn hình sandbox (máy ảo / trình duyệt).
 *
 * Hai nguồn khung hình (`src/lib/vnc/config.ts`):
 *
 * - `mock`  — mặc định. Vẽ đúng màn hình mô phỏng như trước khi có noVNC, và
 *   gói `@novnc/novnc` KHÔNG được nạp, không socket nào được mở. Bắt buộc phải
 *   giữ nguyên vì đây là cảnh demo VPI chính (mục 14.5): nếu màn hình thật
 *   chiếm chỗ thì kịch bản 8 bước mất luôn chỉ thị độc trên màn hình.
 * - `novnc` — màn hình máy thật, ba trạng thái `connecting` / `live` / `offline`
 *   (plan §5). `useVncScreen()` là nơi DUY NHẤT chạm vào RFB/DOM/timer (D-1);
 *   panel này chỉ đọc kết quả.
 *
 * `MockBrowser` không được sửa một ký tự (kịch bản demo VPI dùng nguyên nó).
 *
 * Nhãn M1 (mục 8.5): ảnh màn hình LUÔN mang integrity = KHÔNG_TIN_ĐƯỢC — kể cả
 * khung hình thật ở trạng thái `live`. Ở nhánh live, panel CHỈ hiện integrity
 * viết thẳng, và KHÔNG mượn `confidentiality` / `label_id` của `ScreenState`:
 * `ScreenState` là nhãn của kênh agent, gán nó cho một khung hình VNC không
 * liên quan là nói dối về nguồn gốc dữ liệu.
 */
import { useEffect, useState } from 'react'
import { useAgentStore } from '../../store/agentStore'
import { useT, type TKey } from '../../i18n/context'
import { useVncScreen } from '../../hooks/useVncScreen'
import { useNow } from '../../hooks/useNow'
import { retrySecondsLeft } from '../../lib/retry'
import type { ScreenSource } from '../../lib/vnc/config'
import type { VncOfflineReason } from '../../lib/vnc/state'
import { PanelShell, Chip, StatusChip } from '../ui'
import { IntegrityBadge, ConfidentialityBadge, LabelDot } from '../LabelDot'
import type { ScreenState } from '../../types/session'

/** Map lý do offline → khoá i18n. Record chứ không nối chuỗi động — TKey vẫn kiểm được lúc biên dịch. */
const OFFLINE_REASON_KEY: Record<VncOfflineReason, TKey> = {
  timeout: 'screen.reason.timeout',
  closed: 'screen.reason.closed',
  security: 'screen.reason.security',
  credentials: 'screen.reason.credentials',
  mixedContent: 'screen.reason.mixedContent',
  insecureContext: 'screen.reason.insecureContext',
  unsupported: 'screen.reason.unsupported',
  error: 'screen.reason.error',
  skipped: 'screen.reason.skipped',
  disabled: 'screen.reason.disabled',
}

/** Viền gạch chéo cảnh báo — dấu hiệu thị giác "khung này là hàng dựng". */
const HAZARD_BORDER: React.CSSProperties = {
  backgroundImage:
    'repeating-linear-gradient(45deg, rgb(245 158 11 / 0.45) 0 8px, transparent 8px 16px)',
}

function MockBrowser({ instruction }: { instruction: string }) {
  return (
    <div className="w-full overflow-hidden rounded-lg border border-line bg-white shadow dark:bg-slate-900">
      <div className="flex items-center gap-1.5 border-b border-slate-200 bg-slate-100 px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
        <span className="flex gap-1">
          <span className="size-2 rounded-full bg-red-400" />
          <span className="size-2 rounded-full bg-amber-400" />
          <span className="size-2 rounded-full bg-emerald-400" />
        </span>
        <span className="ml-2 flex-1 truncate rounded bg-white px-2 py-0.5 text-[10px] text-slate-500 dark:bg-slate-700 dark:text-slate-300">
          https://thu-vien-mo-rong.example.com/huong-dan.html
        </span>
      </div>
      <div className="flex aspect-video items-center justify-center bg-gradient-to-br from-amber-50 to-red-50 p-4 dark:from-amber-950/30 dark:to-red-950/30">
        <div className="rounded-lg border-2 border-red-400 bg-red-50 p-6 text-center shadow-lg dark:bg-red-950/40">
          <p className="mb-1 text-[10px] font-bold uppercase tracking-wide text-red-600 dark:text-red-400">
            ⚠ Ghi chú cho trợ lý AI ⚠
          </p>
          <p className="text-[13px] font-semibold leading-relaxed text-red-800 dark:text-red-200">
            {instruction}
          </p>
        </div>
      </div>
    </div>
  )
}

/**
 * Nguồn khung hình `mock`: giữ đúng giao diện trước khi có noVNC.
 *
 * Không có dải cảnh báo, không có viền gạch chéo, không có chip noVNC — người
 * dùng đang chủ động xem bản mô phỏng, không phải bị rơi về nó.
 */
function SimulatedOnlyBody({ screen }: { screen: ScreenState }) {
  const t = useT()
  return (
    <div className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded bg-panel2 px-2 py-0.5 text-[11px] font-medium">
            {screen.view_mode}
          </span>
          {/* Quy tắc M1, mục 8.5 — viết thẳng, không đọc `screen.label.integrity`:
              ảnh màn hình không bao giờ đáng tin, kể cả khi dữ liệu nói khác. */}
          <LabelDot integrity="khong_tin_duoc" confidentiality={screen.label.confidentiality} />
          <span className="text-[11px] text-muted">{screen.label.label_id}</span>
        </div>
        <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-700 ring-1 ring-amber-500/40 dark:text-amber-300">
          {t('screen.mockBanner')}
        </span>
      </div>
      <MockBrowser instruction={screen.injection_banner || t('screen.poisonInstruction')} />
      <p className="mt-3 text-center text-[11px] text-muted">{t('screen.fakeNote')}</p>
    </div>
  )
}

/** Nhãn của khung hình MÔ PHỎNG — nhãn này có thật, hiện đầy đủ. */
function MockLabelRow({ screen }: { screen: ScreenState }) {
  return (
    <div className="mt-2 flex flex-wrap items-center gap-2">
      {/* Quy tắc M1, mục 8.5 — không có ngoại lệ: viết thẳng, không đọc từ dữ liệu. */}
      <IntegrityBadge value="khong_tin_duoc" />
      <ConfidentialityBadge value={screen.label.confidentiality} />
      <span className="text-[11px] text-muted">{screen.label.label_id}</span>
      <Chip>{screen.view_mode}</Chip>
    </div>
  )
}

/**
 * Nhãn của khung hình THẬT: chỉ integrity, và nói rõ phần còn lại chưa biết.
 * Không mượn nhãn của `ScreenState` (xem chú thích đầu file).
 */
function LiveLabelRow() {
  const t = useT()
  return (
    <div className="mb-2 flex flex-wrap items-center gap-2">
      <IntegrityBadge value="khong_tin_duoc" />
      <Chip tone="warn">{t('screen.liveChip')}</Chip>
    </div>
  )
}

/**
 * Khung hình mô phỏng khi nguồn là `novnc`.
 *
 * `hazard` = người dùng đã yêu cầu máy thật mà nhận về hàng dựng ⇒ viền gạch
 * chéo + thẻ góc để không ai nhìn nhầm. Lúc còn đang kết nối thì chưa thất bại
 * gì cả, nên không cần gào lên.
 */
function SimulatedFrame({ screen, hazard }: { screen: ScreenState; hazard: boolean }) {
  const t = useT()
  const body = (
    <>
      <MockBrowser instruction={screen.injection_banner || t('screen.poisonInstruction')} />
      <p className="mt-3 text-center text-[11px] text-muted">{t('screen.fakeNote')}</p>
      <p className="mt-2 text-center text-[11px] text-muted">{t('sandbox.injectionBannerNote')}</p>
      <p className="text-center text-[11px] text-muted">{t('screen.a3DataNotCommand')}</p>
      <MockLabelRow screen={screen} />
    </>
  )

  if (!hazard) return <div>{body}</div>

  return (
    <div className="relative rounded-xl p-2" style={HAZARD_BORDER}>
      <span className="absolute -top-2 right-3 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white">
        Mô phỏng
      </span>
      <div className="rounded-lg bg-panel p-3">{body}</div>
    </div>
  )
}

/** Dải mảnh hiện trên đầu khung hình mô phỏng trong lúc còn đang thử nối máy thật. */
function ConnectingStrip({ url, onSkip }: { url: string; onSkip: () => void }) {
  const t = useT()
  return (
    <div
      role="status"
      aria-live="polite"
      className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-dashed border-line bg-panel2 p-2 text-[11px]"
    >
      <span
        className="size-3.5 animate-spin rounded-full border-2 border-line border-t-brand"
        aria-hidden="true"
      />
      <span className="font-semibold">{t('screen.connectingTitle')}</span>
      <code className="rounded bg-panel px-1.5 py-0.5 text-[10px] text-muted">{url}</code>
      <span className="text-muted">{t('screen.connectingWait')}</span>
      <button
        type="button"
        onClick={onSkip}
        className="ml-auto rounded-md border border-line px-2 py-1 font-semibold text-muted hover:text-fg"
      >
        {t('screen.skipToMock')}
      </button>
    </div>
  )
}

/** Không có khung hình mô phỏng nào để hiện kèm ⇒ thẻ chờ chiếm cả chỗ. */
function ConnectingCard({ url }: { url: string }) {
  const t = useT()
  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line bg-panel2 p-6 text-center"
    >
      <span
        className="size-6 animate-spin rounded-full border-2 border-line border-t-brand"
        aria-hidden="true"
      />
      <p className="text-[13px] font-semibold">{t('screen.connectingTitle')}</p>
      <p className="text-[11px] text-muted">{t('screen.connectingWait')}</p>
      <code className="rounded bg-panel px-2 py-1 text-[11px] text-muted">{url}</code>
      {/* Nhãn tạm: khung hình chưa về nhưng M1 đã đúng từ trước khi nó về. */}
      <div className="flex flex-wrap items-center justify-center gap-2">
        <IntegrityBadge value="khong_tin_duoc" />
      </div>
      <p className="max-w-[46ch] text-[11px] leading-relaxed text-muted">
        {t('sandbox.screenshotAlwaysUntrusted')}
      </p>
      {/* Không có nút "bỏ chờ, xem mô phỏng": phiên này chưa có khung hình mô
          phỏng nào, hứa một thứ không tồn tại thì tệ hơn là không hứa. */}
      <p className="text-[11px] text-muted">{t('screen.noFrameBody')}</p>
    </div>
  )
}

function OfflineAlert({
  url,
  reason,
  hasMockFrame,
  onRetry,
}: {
  url: string
  reason: VncOfflineReason | null
  /** `false` ⇒ tuyệt đối không được nói "đang xem mô phỏng", vì chẳng có gì để xem. */
  hasMockFrame: boolean
  onRetry: () => void
}) {
  const t = useT()
  const [showHelp, setShowHelp] = useState(false)
  return (
    <div
      role="alert"
      className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-800 dark:text-amber-200"
    >
      <p className="text-[12px] font-bold uppercase tracking-wide">
        {hasMockFrame ? t('screen.offlineTitle') : t('screen.noFrameTitle')}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed">
        {hasMockFrame ? t('screen.offlineBody') : t('screen.noFrameBody')}
      </p>
      {reason && <p className="mt-1 text-[11px] leading-relaxed">{t(OFFLINE_REASON_KEY[reason], { url })}</p>}
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md bg-fg px-3 py-1.5 text-[11px] font-semibold text-bg"
        >
          {t('screen.retry')}
        </button>
        <button
          type="button"
          aria-expanded={showHelp}
          onClick={() => setShowHelp((v) => !v)}
          className="rounded-md border border-line px-3 py-1.5 text-[11px] font-semibold text-muted hover:text-fg"
        >
          {t('screen.howToStartBox')}
        </button>
      </div>
      {showHelp && (
        <div className="mt-2 rounded-md bg-panel2 p-2 text-[11px] text-muted">
          <p>{t('screen.howToStartBoxBody')}</p>
          <code className="mt-1 block rounded bg-panel px-2 py-1">
            cd deploy/docker &amp;&amp; docker compose up -d
          </code>
        </div>
      )}
    </div>
  )
}

export function SandboxScreenPanel() {
  const t = useT()
  const now = useNow()
  const screen = useAgentStore((s) => s.screen)
  // Lựa chọn nguồn của người dùng (nút Live box/Demo). `null` = theo env mặc định.
  const [sourcePref, setSourcePref] = useState<ScreenSource | null>(null)
  const vnc = useVncScreen(sourcePref ?? undefined)
  const toggleSource = () =>
    setSourcePref(vnc.source === 'novnc' ? 'mock' : 'novnc')

  const sourceToggle = (
    <button
      type="button"
      onClick={toggleSource}
      title={vnc.source === 'novnc' ? t('screen.toDemo') : t('screen.toLiveBox')}
      className="rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
    >
      {vnc.source === 'novnc' ? t('screen.toDemo') : t('screen.toLiveBox')}
    </button>
  )

  // ── Công tắc mạng ②b (mục 12.3.1): gọi ide-proxy chạy root trong box ──
  const NET_API = 'http://localhost:8081'
  const [netState, setNetState] = useState<'on' | 'off' | 'unknown'>('unknown')
  useEffect(() => {
    fetch(NET_API + '/__box/status')
      .then((r) => r.json())
      .then((j) => setNetState(j.network))
      .catch(() => setNetState('unknown'))
  }, [])
  const [netBusy, setNetBusy] = useState(false)
  const toggleNetwork = async () => {
    if (netBusy || netState === 'unknown') return
    const next = netState === 'on' ? 'off' : 'on'
    setNetBusy(true)
    try {
      const r = await fetch(NET_API + '/__box/network', {
        method: 'POST',
        headers: { 'Content-Type': 'text/plain' },
        body: next,
      })
      const j = await r.json()
      setNetState(j.network)
    } catch {
      setNetState('unknown')
    } finally {
      setNetBusy(false)
    }
  }

  const netBtn = (
    <button
      type="button"
      onClick={toggleNetwork}
      disabled={netBusy}
      title={t('screen.netOn') + ' / ' + t('screen.netOff')}
      className={`rounded-md border border-line px-2 py-1 text-[11px] font-semibold hover:text-fg disabled:opacity-50 ${
        netState === 'on'
          ? 'text-emerald-600 dark:text-emerald-400'
          : netState === 'off'
            ? 'text-zinc-500 dark:text-zinc-400'
            : 'text-muted'
      }`}
    >
      {netState === 'on'
        ? t('screen.netOn')
        : netState === 'off'
          ? t('screen.netOff')
          : t('screen.netUnknown')}
    </button>
  )

  // Nguồn `mock`: đường cũ, nguyên vẹn. Hook không nạp noVNC, không mở socket.
  if (vnc.source === 'mock') {
    return (
      <PanelShell title={t('screen.title')} toolbar={sourceToggle}>
        {screen ? (
          <SimulatedOnlyBody screen={screen} />
        ) : (
          <div className="flex h-full items-center justify-center p-6 text-center">
            <p className="text-[12px] text-muted">{t('screen.empty')}</p>
          </div>
        )}
      </PanelShell>
    )
  }

  const statusChip =
    vnc.phase === 'live' ? (
      <StatusChip tone="live" pulse>
        {t('screen.liveChip')}
      </StatusChip>
    ) : vnc.phase === 'connecting' ? (
      <StatusChip tone="busy">{t('screen.connectingChip')}</StatusChip>
    ) : (
      <StatusChip tone="warn">
        {screen ? t('screen.mockBanner') : t('screen.noFrameChip')}
      </StatusChip>
    )

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {statusChip}
      {netBtn}
      {sourceToggle}
      {vnc.phase === 'offline' && (
        <button
          type="button"
          onClick={vnc.retry}
          className="rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
        >
          {t('screen.retry')}
        </button>
      )}
    </div>
  )

  const note =
    vnc.phase === 'connecting'
        ? t('screen.connectingNote')
        : vnc.reason
          ? t(OFFLINE_REASON_KEY[vnc.reason], { url: vnc.url })
          : undefined

  const retrySeconds = vnc.retryAtMs !== null ? retrySecondsLeft(vnc.retryAtMs, now) : null

  return (
    <PanelShell title={t('screen.title')} toolbar={toolbar} note={note}>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex min-h-0 flex-1 flex-col px-2 py-2">
          {/* Khung noVNC luôn được mount (không hidden/h-0) để scaleViewport đo đúng
              kích thước ngay khi hiện ra; ẩn bằng opacity + đưa ra khỏi luồng khi chưa live. */}
          <div className={vnc.phase === 'live' ? 'relative flex min-h-0 flex-1 flex-col' : 'relative'}>
            <div
              className={
                vnc.phase === 'live'
                  ? // Chiếm hết chỗ còn lại của khung ④: màn hình máy thật là nội
                    // dung chính, không phải một ô nhỏ giữa panel. noVNC bật
                    // `scaleViewport` nên canvas tự co giãn vừa khung và căn
                    // giữa; phần thừa là nền đen, không méo tỉ lệ.
                    'relative mb-3 min-h-0 flex-1 overflow-hidden rounded-lg border border-line bg-black'
                  : 'pointer-events-none absolute left-0 top-0 -z-10 h-40 w-64 overflow-hidden opacity-0'
              }
            >
              <div
                ref={vnc.containerRef}
                tabIndex={vnc.phase === 'live' ? 0 : -1}
                role="application"
                aria-label={t('screen.canvasLabel')}
                onFocus={vnc.focusScreen}
                className="absolute inset-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-brand"
              />
              {vnc.phase === 'live' && vnc.controlling && (
                <span className="pointer-events-none absolute left-2 top-2 rounded bg-brand/80 px-1.5 py-0.5 text-[10px] font-semibold text-white">
                  {t('screen.canvasLabel')}
                </span>
              )}
              {vnc.phase === 'live' && vnc.frameSize && (
                <span className="pointer-events-none absolute bottom-2 right-2 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-slate-200">
                  {t('screen.frameSize', {
                    width: vnc.frameSize.width,
                    height: vnc.frameSize.height,
                  })}
                </span>
              )}
            </div>
          </div>

          {vnc.phase === 'live' && (
            <details className="shrink-0 border-t border-line px-1 pt-1">
              <summary className="cursor-pointer select-none py-1 text-[11px] font-semibold text-muted hover:text-fg">
                {t('screen.details')} · {t('screen.releaseKeyboard')}
              </summary>
              <div className="pb-2">
                <LiveLabelRow />
                <p className="text-[11px] leading-relaxed text-muted">
                  {t('sandbox.screenshotAlwaysUntrusted')}
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-muted">
                  {t('screen.liveLabelUnknown')}
                </p>
                <p className="mt-1 text-[11px] leading-relaxed text-muted">
                  {t('screen.liveInputNotAudited')}
                </p>
                <div className="mt-2">
                  <button
                    type="button"
                    onClick={vnc.releaseKeyboard}
                    className="rounded-md border border-line px-3 py-1.5 text-[11px] font-semibold text-muted hover:text-fg"
                  >
                    {t('screen.releaseKeyboard')}
                  </button>
                </div>
              </div>
            </details>
          )}

          {vnc.phase === 'connecting' &&
            (screen ? (
              <>
                <ConnectingStrip url={vnc.url} onSkip={vnc.skip} />
                <SimulatedFrame screen={screen} hazard={false} />
              </>
            ) : (
              <ConnectingCard url={vnc.url} />
            ))}

          {vnc.phase === 'offline' && (
            <>
              <OfflineAlert
                url={vnc.url}
                reason={vnc.reason}
                hasMockFrame={screen !== null}
                onRetry={vnc.retry}
              />
              {screen ? (
                <SimulatedFrame screen={screen} hazard />
              ) : (
                <p className="text-center text-[12px] text-muted">{t('screen.empty')}</p>
              )}
            </>
          )}

          {retrySeconds !== null && (
            <p className="mt-2 text-center text-[11px] text-muted">
              {t('screen.retryCountdown', { seconds: retrySeconds })}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line bg-panel2/60 px-3 py-1 text-[11px] text-muted">
          <span>
            noVNC · {t('screen.endpointLabel')}{' '}
            <code className="font-mono text-[10px]">{vnc.url}</code>
          </span>
          <span>
            {vnc.phase === 'live'
              ? t('screen.frameSourceLive')
              : screen
                ? t('screen.frameSourceMock')
                : t('screen.noFrameChip')}
          </span>
        </div>
      </div>
    </PanelShell>
  )
}
