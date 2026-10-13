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
import { useEffect, useRef, useState } from 'react'
import { ChevronDown, ChevronUp, Sparkles } from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useComposerStore } from '../../store/composerStore'
import { useT, type TKey } from '../../i18n/context'
import { useVncScreen } from '../../hooks/useVncScreen'
import { useNow } from '../../hooks/useNow'
import { useElementInspector } from '../../hooks/useElementInspector'
import { retrySecondsLeft } from '../../lib/retry'
import { VNC_HELP_AFTER_ATTEMPTS, type VncOfflineReason } from '../../lib/vnc/state'
import { PanelShell, Chip, StatusChip } from '../ui'
import { IntegrityBadge, ConfidentialityBadge, LabelDot } from '../LabelDot'
import { ElementInspectorOverlay } from '../sandbox/ElementInspectorOverlay'
import { ElementInspectorDrawer } from '../sandbox/ElementInspectorDrawer'
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

/** Bao lâu thì dải `Reconnected` tự tắt — đủ để đọc, không đủ để thành nhiễu. */
const RECONNECTED_STRIP_MS = 4000

function MockBrowser({ instruction }: { instruction: string }) {
  return (
    <div className="w-full overflow-hidden rounded-lg border border-line bg-white shadow dark:bg-slate-900">
      <div className="flex items-center gap-1.5 border-b border-slate-200 bg-slate-100 px-3 py-2 dark:border-slate-700 dark:bg-slate-800">
        <span className="flex gap-1">
          <span className="size-2 rounded-full bg-red-400" />
          <span className="size-2 rounded-full bg-amber-400" />
          <span className="size-2 rounded-full bg-emerald-400" />
        </span>
        <span className="ml-2 flex-1 truncate rounded-full bg-panel2 px-2 py-0.5 text-[11px] text-muted">
          https://thu-vien-mo-rong.example.com/huong-dan.html
        </span>
      </div>
      <div className="flex aspect-video items-center justify-center bg-gradient-to-br from-amber-50 to-red-50 p-4 dark:from-amber-950/30 dark:to-red-950/30">
        <div className="rounded-lg border-2 border-red-400 bg-red-50 p-6 text-center shadow-lg dark:bg-red-950/40">
          <p className="mb-1 text-[11px] font-bold uppercase tracking-wide text-red-600 dark:text-red-400">
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
export function SimulatedOnlyBody({ screen }: { screen: ScreenState }) {
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
      <span className="absolute -top-2 right-3 rounded-full bg-amber-500 px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-white">
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
      <code className="rounded-full bg-panel px-1.5 py-0.5 text-[11px] text-muted">{url}</code>
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

/**
 * Link "Cách bật box" — chữ gạch chân, KHÔNG nền, KHÔNG phải nút chính.
 *
 * Vẫn là `<button>` thật (không phải `<a>`) để bàn phím và trình đọc màn hình
 * dùng được; nội dung mở ra chỉ là hướng dẫn, không phải một hành động khác.
 * Dùng chung cho lớp phủ (từ lượt thứ `VNC_HELP_AFTER_ATTEMPTS`) và thẻ lý do
 * không thể tự khỏi.
 */
function HowToStartBox() {
  const t = useT()
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="text-[11px] text-muted underline underline-offset-2 hover:text-fg"
      >
        {t('screen.howToStartBox')}
      </button>
      {open && (
        <div className="rounded-md bg-panel2 p-2 text-[11px] text-muted">
          <p>{t('screen.howToStartBoxBody')}</p>
          <code className="mt-1 block rounded bg-panel px-2 py-1">
            cd deploy/docker &amp;&amp; docker compose up -d
          </code>
        </div>
      )}
    </>
  )
}

/**
 * Lớp phủ "đang kết nối" (Kế hoạch E1) — thay cho khối hổ phách
 * `NO FRAME AVAILABLE` cùng hai nút thủ công đã xoá.
 *
 * Thang thử lại giờ chạy mãi, nên không còn gì để bấm: người dùng chỉ cần thấy
 * việc đang diễn ra và còn bao lâu. Lớp phủ nằm trong thân panel
 * (`absolute inset-0` của một khung `relative`), nên nó KHÔNG bao giờ che thanh
 * trên của panel — các nút Select Element / Details vẫn nguyên chỗ.
 *
 * Dòng đếm CỐ Ý không nằm trong vùng `aria-live`: chuỗi đổi mỗi giây, thông báo
 * từng giây là làm phiền trình đọc màn hình. Chỉ tiêu đề có `role="status"`.
 */
function ConnectingOverlay({
  attempt,
  retryAtMs,
  retryDelayMs,
  now,
}: {
  attempt: number
  retryAtMs: number | null
  retryDelayMs: number | null
  now: number
}) {
  const t = useT()
  const seconds = retryAtMs !== null ? retrySecondsLeft(retryAtMs, now) : null
  // Thanh 2 px chạy đúng khoảng nghỉ đang hẹn; transition 1 s khớp nhịp đồng hồ
  // `useNow` nên thanh chạy mượt giữa hai nhịp.
  const progress =
    retryAtMs !== null && retryDelayMs
      ? Math.min(1, Math.max(0, 1 - (retryAtMs - now) / retryDelayMs)) * 100
      : 0

  return (
    <div
      data-testid="machine-connecting-overlay"
      className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/40 px-6 text-center backdrop-blur-xs animate-fade-in"
    >
      {/* Mark BoxFox — đúng công thức ở header sidebar, chỉ đổi `rounded-md`
          thành `rounded-lg`; `animate-pulse` ở đây nghĩa là "đang xử lý". */}
      <span className="flex size-6 items-center justify-center rounded-lg bg-brand/10 text-brand animate-pulse motion-reduce:animate-none">
        <Sparkles className="size-3.5" />
      </span>
      <p role="status" className="text-[13px] font-semibold">
        {t('screen.connectingDesktop')}
      </p>
      <p className="font-mono text-[11px] text-muted">
        {t('screen.attemptLabel', { n: attempt })}
        {seconds !== null && (
          <>
            {' · '}
            {t('screen.retryCountdown', { seconds })}
          </>
        )}
      </p>
      <div aria-hidden="true" className="h-0.5 w-40 overflow-hidden rounded-full bg-white/10">
        <div
          className="h-full bg-brand transition-[width] duration-1000 ease-linear motion-reduce:transition-none"
          style={{ width: `${progress}%` }}
        />
      </div>
      <p className="text-[11px] text-muted">{t('screen.empty')}</p>
      {/* Sau vài lượt hỏng thì mới đáng nhắc tới việc bật máy — trước đó là làm
          ồn. Thang vẫn chạy tiếp phía sau link này. */}
      {attempt >= VNC_HELP_AFTER_ATTEMPTS && (
        <div className="mt-1">
          <HowToStartBox />
        </div>
      )}
    </div>
  )
}

/**
 * Nhánh lý do KHÔNG THỂ TỰ KHỎI (`mixedContent`, `insecureContext`,
 * `unsupported`, `security`, `credentials`, `disabled`, `skipped`).
 *
 * Thẻ tĩnh: không vòng xoay, không đếm ngược, không nút thử lại — một lớp phủ
 * quay mãi ở đây sẽ là lời nói dối, vì chẳng có lượt nào đang chạy. Câu lý do
 * cụ thể nằm ở hàng `note` của `PanelShell`, không lặp lại ở đây.
 */
function TerminalReasonCard() {
  const t = useT()
  return (
    <div
      role="alert"
      className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-800 dark:text-amber-200"
    >
      <p className="text-[12px] font-bold uppercase tracking-wide">{t('screen.noFrameTitle')}</p>
      <p className="mt-1 text-[11px] leading-relaxed">{t('screen.noFrameBody')}</p>
      <div className="mt-2">
        <HowToStartBox />
      </div>
    </div>
  )
}

/**
 * Thông báo hổ phách khi CÓ khung mô phỏng để xem (đường demo VPI).
 *
 * Nhãn trung thực không bao giờ biến mất; so với bản cũ nó chỉ mất hai nút thủ
 * công. Câu lý do vẫn in ở đây như trước, vì khung mô phỏng bên dưới trông y hệt
 * một màn hình thật — người xem cần biết vì sao nó lại ở đó.
 */
function SimulatedOfflineNotice({ reason, url }: { reason: VncOfflineReason | null; url: string }) {
  const t = useT()
  return (
    <div
      role="alert"
      className="mb-3 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-800 dark:text-amber-200"
    >
      <p className="text-[12px] font-bold uppercase tracking-wide">{t('screen.offlineTitle')}</p>
      <p className="mt-1 text-[11px] leading-relaxed">{t('screen.offlineBody')}</p>
      {reason && <p className="mt-1 text-[11px] leading-relaxed">{t(OFFLINE_REASON_KEY[reason], { url })}</p>}
    </div>
  )
}

export function SandboxScreenPanel() {
  const t = useT()
  const now = useNow()
  const screen = useAgentStore((s) => s.screen)
  // Máy BẬT ⇒ luôn xem live (demo chỉ bật qua env khi cần thu hình 14.5).
  const vnc = useVncScreen('novnc')
  // Dời lên đây (trước `toolbar`, TRAP F-8 mục 12 kế hoạch): khai báo sau khi
  // `toolbar` dùng tới sẽ ném `ReferenceError` do TDZ — TypeScript KHÔNG bắt
  // được lỗi này vì `const` vẫn hợp lệ về kiểu, chỉ sai thứ tự runtime.
  const isLive = vnc.phase === 'live'
  const [detailsOpen, setDetailsOpen] = useState(false)
  const inspector = useElementInspector()
  const addPendingElement = useComposerStore((s) => s.addPendingElement)

  // Điện & mạng box — trạng thái toàn cục (useBoxState), đặt ở header trên cùng.
  // (Không còn nút trong panel này — xem BoxControls.)

  // Chỉ dùng được khi đang xem máy thật: nút bật (`toolbar`) đã disable khi
  // không live, nhưng người dùng có thể đã bật rồi máy MỚI rớt kết nối — tắt
  // hộ để lớp bắt cú bấm không treo lơ lửng trên một canvas không còn sống.
  useEffect(() => {
    if (!isLive && inspector.armed) inspector.disarm()
  }, [isLive, inspector.armed, inspector.disarm])

  // Dải "Đã kết nối lại": CHỈ hiện khi kênh từng rớt rồi sống lại. Lần nối đầu
  // tiên không phải sự kiện đáng báo — nếu báo, nó thành thông báo cho mọi lần
  // mở tab. `wasOfflineRef` giữ "đã từng rớt"; đặt lại sau khi đã báo.
  const [reconnected, setReconnected] = useState(false)
  const wasOfflineRef = useRef(false)
  useEffect(() => {
    if (vnc.phase === 'offline') {
      wasOfflineRef.current = true
      return
    }
    if (vnc.phase !== 'live' || !wasOfflineRef.current) return
    wasOfflineRef.current = false
    setReconnected(true)
    const id = setTimeout(() => setReconnected(false), RECONNECTED_STRIP_MS)
    return () => clearTimeout(id)
  }, [vnc.phase])

  // Khung sáng trên lớp phủ — chỉ vẽ khi ngăn kéo đang hiện MỘT KẾT QUẢ DOM
  // (có `screenBox` framebuffer sẵn); nhánh desktop không có toạ độ nào để
  // khoanh vùng nên không vẽ gì (đúng những gì mockup thể hiện).
  const highlightResult =
    inspector.drawer?.status === 'success' && inspector.drawer.result.type === 'dom'
      ? inspector.drawer.result
      : null
  const highlightBox = highlightResult?.screenBox ?? null
  const highlightLabel = highlightResult
    ? t('screen.inspector.highlightLabel', {
        tag: highlightResult.tagName,
        width: Math.round(highlightResult.screenBox.width),
        height: Math.round(highlightResult.screenBox.height),
      })
    : null

  function handleAddToChat() {
    const state = inspector.drawer
    if (!state || state.status !== 'success') return
    const id = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `element-${Date.now()}`
    addPendingElement({ id, point: state.point, result: state.result })
    inspector.closeDrawer()
  }

  const statusChip =
    vnc.phase === 'live' ? (
      <StatusChip tone="live" pulse>
        {t('screen.liveChip')}
      </StatusChip>
    ) : vnc.phase === 'connecting' ? (
      <StatusChip tone="busy">{t('screen.connectingChip')}</StatusChip>
    ) : !vnc.exhausted ? (
      // Offline nhưng thang còn hẹn ⇒ panel ĐANG kết nối, không phải "hết khung
      // hình". Chip `warn` ở đây là nói dối (Kế hoạch E1).
      <StatusChip tone="busy">{t('screen.connectingChip')}</StatusChip>
    ) : (
      <StatusChip tone="warn">
        {screen ? t('screen.mockBanner') : t('screen.noFrameChip')}
      </StatusChip>
    )

  const toolbar = (
    <div className="flex flex-wrap items-center gap-2">
      {statusChip}
      <button
        type="button"
        aria-pressed={inspector.armed}
        disabled={!isLive}
        title={isLive ? undefined : t('screen.inspector.toggleDisabledHint')}
        onClick={inspector.toggleArmed}
        className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
          inspector.armed
            ? 'border-brand bg-brand text-brandfg'
            : 'border-line text-muted hover:border-brand/40 hover:text-fg'
        }`}
      >
        {inspector.armed ? t('screen.inspector.toggleOff') : t('screen.inspector.toggleOn')}
      </button>
      {vnc.phase === 'live' && (
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
          {t('screen.details')}
          {detailsOpen ? <ChevronUp className="size-3" /> : <ChevronDown className="size-3" />}
        </button>
      )}
      {/* KHÔNG còn nút "Thử kết nối lại" ở đây: thang thử lại chạy mãi, và nút
          thủ công chỉ khiến người dùng tưởng panel đã bỏ cuộc (Kế hoạch E1). */}
    </div>
  )

  const note =
    vnc.phase === 'connecting'
        ? t('screen.connectingNote')
        : vnc.reason
          ? t(OFFLINE_REASON_KEY[vnc.reason], { url: vnc.url })
          : undefined

  // Lớp phủ chỉ dành cho nhánh KHÔNG có khung mô phỏng: khi có khung mô phỏng
  // thì đường demo VPI giữ nguyên nhãn trung thực của nó (Kế hoạch E1, điểm lệch
  // #2 — container noVNC bị đỗ ra ngoài luồng nên không có "khung cũ dưới lớp mờ").
  const showConnectingOverlay = screen === null && vnc.phase === 'offline' && !vnc.exhausted

  return (
    <PanelShell title={t('screen.title')} toolbar={toolbar} note={note}>
      <div className="flex h-full min-h-0 flex-col">
        {/* Details drawer — trượt từ thanh trên xuống, chỉ khi live (Q1/Q2) */}
        {isLive && detailsOpen && (
          <div className="shrink-0 overflow-hidden border-b border-line bg-panel2 animate-slide-down">
            <div className="px-3 py-2">
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
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={vnc.releaseKeyboard}
                  className="rounded-md border border-line px-3 py-1.5 text-[11px] font-semibold text-muted hover:text-fg"
                >
                  {t('screen.releaseKeyboard')}
                </button>
                {vnc.frameSize && (
                  <span className="text-[11px] text-muted">
                    {t('screen.frameSize', {
                      width: vnc.frameSize.width,
                      height: vnc.frameSize.height,
                    })}
                    {' · '}
                    {t('screen.frameSourceLive')}
                  </span>
                )}
              </div>
              <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted">
                <span>
                  noVNC · {t('screen.endpointLabel')}{' '}
                  <code className="font-mono">{vnc.url}</code>
                </span>
              </div>
            </div>
          </div>
        )}

        <div
          className={
            isLive
              ? 'flex min-h-0 flex-1 flex-col overflow-hidden'
              : // `relative` để lớp phủ "đang kết nối" phủ ĐÚNG thân panel này —
                // thanh trên, thanh tab và footer không bị nó nuốt.
                'relative flex min-h-0 flex-1 flex-col overflow-auto px-2 py-2'
          }
        >
          {/* Khung noVNC luôn được mount (không hidden/h-0) để scaleViewport đo đúng
              kích thước ngay khi hiện ra; ẩn bằng opacity + đưa ra khỏi luồng khi chưa live. */}
          <div className={isLive ? 'relative flex min-h-0 flex-1 flex-col' : 'relative'}>
            <div
              className={
                isLive
                  ? // Full-bleed như Vorflux: chiếm toàn bộ panel, không rounded/border/padding,
                    // nền hòa vào desktop để không lộ viền đen.
                    'relative min-h-0 flex-1 overflow-hidden bg-[#0f172a]'
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
              {/*
                KHÔNG thêm lại nhãn nổi ở góc trên-trái. Nó nằm đè lên desktop
                thật (che tab bar của Chromium trong box) mà chẳng nói thêm gì:
                cùng chuỗi đó đã là `aria-label` của vùng `role="application"`
                ở trên, nên trình đọc màn hình vẫn đọc được.
              */}
              {/* Dải nhỏ ở mép trên canvas — MỘT khe, hai nội dung, không bao
                  giờ hai dải chồng nhau: ưu tiên "Đã kết nối lại" (chỉ 4 giây),
                  hết 4 giây thì dải "đã lên nòng" hiện lại nếu inspector còn bật.
                  Cả hai đều TUYỆT ĐỐI, KHÔNG nằm trong luồng flex: đặt
                  `shrink-0` trong luồng lại co kéo container noVNC ⇒
                  `rfb.resizeSession=true` đổi độ phân giải màn hình thật (trap
                  F-3, mục 12 — đúng lỗi review đã chỉ). `pointer-events-none`
                  để cú bấm vẫn tới lớp bắt của `ElementInspectorOverlay`. */}
              {isLive && reconnected ? (
                <div
                  role="status"
                  className="pointer-events-none absolute inset-x-0 top-0 bg-emerald-500/10 px-3 py-1.5 text-center text-[11px] font-medium text-emerald-400"
                >
                  {t('screen.reconnected')}
                </div>
              ) : (
                inspector.armed && (
                  <div
                    role="status"
                    className="pointer-events-none absolute inset-x-0 top-0 bg-brand/10 px-3 py-1.5 text-center text-[11px] font-medium text-brand"
                  >
                    {t('screen.inspector.armedBanner')}
                  </div>
                )
              )}
              {/*
                KHÔNG dựng lại thẻ số đo điểm ảnh ở góc dưới-phải (Kế hoạch E4).
                Con số đó là kích thước ĐÃ THƯƠNG LƯỢNG với box, không phải hằng
                số: `lib/vnc/fit.ts` đặt `rfb.resizeSession = true` nên hôm nay
                là 875 × 723, sau một lần đổi cỡ panel là 1280 × 800 — cả hai
                đều đúng, và nhãn "khung hình từ máy thật" không hứa một con số
                cố định. Khi chưa live thì không có framebuffer nào để đo, nên
                chỗ đúng của nó là ngăn kéo `Details` (chỉ render khi
                `phase === 'live'`) — nơi nó vẫn còn, kèm nguồn khung hình.
                Phần đọc số trong `useVncScreen` giờ chỉ nuôi ngăn kéo đó.
              */}
              {/* Lớp phủ + ngăn kéo Element Selector (khung ④, F9/F10/F11) — thêm
                  làm ANH/EM tuyệt đối với div `containerRef` ở trên, theo đúng
                  khuôn của thẻ kích thước khung hình ngay phía trên: KHÔNG chạm
                  vào kích thước/layout của div đó (trap F-3, mục 12 kế hoạch). */}
              <ElementInspectorOverlay
                armed={inspector.armed}
                canvasContainerRef={vnc.containerRef}
                highlightBox={highlightBox}
                highlightLabel={highlightLabel}
                onPick={inspector.handlePick}
                onEscape={inspector.disarm}
              />
              {inspector.drawer && (
                <ElementInspectorDrawer
                  state={inspector.drawer}
                  onClose={inspector.closeDrawer}
                  onRetry={inspector.retry}
                  onAddToChat={handleAddToChat}
                />
              )}
            </div>
          </div>

          {vnc.phase === 'connecting' &&
            (screen ? (
              <>
                <ConnectingStrip url={vnc.url} onSkip={vnc.skip} />
                <SimulatedFrame screen={screen} hazard={false} />
              </>
            ) : (
              <ConnectingCard url={vnc.url} />
            ))}

          {vnc.phase === 'offline' &&
            (screen ? (
              // Đường demo: khung mô phỏng giữ nguyên nhãn trung thực, chỉ mất
              // hai nút thủ công so với trước.
              <>
                <SimulatedOfflineNotice reason={vnc.reason} url={vnc.url} />
                <SimulatedFrame screen={screen} hazard />
              </>
            ) : showConnectingOverlay ? (
              // Thang còn hẹn ⇒ lớp phủ "đang kết nối" phủ thân panel. Không còn
              // khối `NO FRAME AVAILABLE` màu hổ phách, không còn nút thủ công,
              // và cũng không còn khối đếm ngược rời ở đáy (nó nằm trong lớp phủ).
              <ConnectingOverlay
                attempt={vnc.attempt}
                retryAtMs={vnc.retryAtMs}
                retryDelayMs={vnc.retryDelayMs}
                now={now}
              />
            ) : (
              // Lý do không thể tự khỏi: thẻ tĩnh, và câu lý do đã ở hàng `note`.
              <TerminalReasonCard />
            ))}
        </div>

        {/* Footer cũ đã chuyển vào drawer Details khi live; chỉ giữ khi không live */}
        {!isLive && (
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-line bg-panel2/60 px-3 py-1 text-[11px] text-muted">
            <span>
              noVNC · {t('screen.endpointLabel')}{' '}
              <code className="font-mono text-[11px]">{vnc.url}</code>
            </span>
            <span>
              {screen ? t('screen.frameSourceMock') : t('screen.noFrameChip')}
            </span>
          </div>
        )}
      </div>
    </PanelShell>
  )
}
