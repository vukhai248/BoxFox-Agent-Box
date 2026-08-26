/**
 * BoxControls — cụm công tắc ĐIỆN + MẠNG của box, đặt ở header TOÀN CỤC
 * (ngang New Session), không nằm trong panel bên phải.
 *
 * Dùng chung useBoxState (module-level cache) ⇒ trạng thái không mất khi đóng/mở
 * tab. `togglePower`/`toggleNetwork` gọi ide-proxy (root) trong box qua
 * /__box/power, /__box/network.
 */
import { useBoxState } from '../../hooks/useBoxState'
import { useT } from '../../i18n/context'

export function BoxControls() {
  const t = useT()
  const box = useBoxState()

  const netBtn = (
    <button
      type="button"
      onClick={box.toggleNetwork}
      className={`rounded-md border border-line px-2 py-1 text-[11px] font-semibold hover:text-fg ${
        box.network === 'on'
          ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-zinc-500 dark:text-zinc-400'
      }`}
    >
      {box.network === 'on' ? t('screen.netOn') : t('screen.netOff')}
    </button>
  )

  const machineBtn = (
    <button
      type="button"
      onClick={box.togglePower}
      className={`rounded-md border border-line px-2 py-1 text-[11px] font-semibold hover:text-fg ${
        box.power === 'on'
          ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-zinc-500 dark:text-zinc-400'
      }`}
    >
      {box.power === 'on' ? t('screen.toDemo') : t('screen.toLiveBox')}
    </button>
  )

  return (
    <div className="flex items-center gap-2">
      {machineBtn}
      {netBtn}
    </div>
  )
}
