/**
 * Khung ④ — Màn hình sandbox (máy ảo / trình duyệt).
 *
 * QUAN TRỌNG: màn hình mô phỏng phải hiện chỉ thị độc trên màn hình
 * (kênh tấn công A3 — VPI). Đây là cảnh demo chính (mục 14.5).
 *
 * Nhãn M1: ảnh màn hình luôn mang integrity = KHÔNG_TIN_ĐƯỢC.
 */
import { useAgentStore } from '../../store/agentStore'
import { useT } from '../../i18n/context'
import { PanelShell } from '../ui'
import { LabelDot } from '../LabelDot'

function MockBrowser({ instruction }: { instruction: string }) {
  return (
    <div className="mx-auto w-full max-w-[480px] overflow-hidden rounded-lg border border-line bg-white shadow dark:bg-slate-900">
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

export function SandboxScreenPanel() {
  const t = useT()
  const screen = useAgentStore((s) => s.screen)

  if (!screen) {
    return (
      <PanelShell title={t('screen.title')}>
        <div className="flex h-full items-center justify-center p-6 text-center">
          <p className="text-[12px] text-muted">{t('screen.empty')}</p>
        </div>
      </PanelShell>
    )
  }

  return (
    <PanelShell title={t('screen.title')}>
      {screen.live ? (
        <div className="flex h-full items-center justify-center bg-black">
          <p className="text-[12px] text-slate-400">
            WebRTC stream thật — hiển thị ở đây khi backend chạy
          </p>
        </div>
      ) : (
        <div className="p-4">
          {/* Dải trạng thái */}
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded bg-panel2 px-2 py-0.5 text-[11px] font-medium">
                {screen.view_mode}
              </span>
              <LabelDot
                integrity={screen.label.integrity}
                confidentiality={screen.label.confidentiality}
              />
              <span className="text-[11px] text-muted">{screen.label.label_id}</span>
            </div>
            <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[11px] font-semibold text-amber-700 ring-1 ring-amber-500/40 dark:text-amber-300">
              {t('screen.mockBanner')}
            </span>
          </div>
          <MockBrowser instruction={screen.injection_banner || t('screen.poisonInstruction')} />
          <p className="mt-3 text-center text-[11px] text-muted">{t('screen.fakeNote')}</p>
        </div>
      )}
    </PanelShell>
  )
}
