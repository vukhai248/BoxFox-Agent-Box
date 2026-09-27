/**
 * `DesignErrorNotice` (P5 §7.6) — câu đọc được của lỗi ghi Design gần nhất.
 *
 * Vì sao cần: các nhánh ghi (`duyệt danh sách chạm`, `duyệt/hoàn tác lô`, `trả lời lời hỏi`, đổi chế
 * độ) đều `return false` khi server từ chối, nhưng callers cũ bỏ qua giá trị đó nên một
 * `DESIGN_WRITE_STALE` hiện ra như nút chết. Thẻ này là MỘT chỗ đọc `store.error`, dịch mã lỗi thành
 * câu tiếng người (`designMode.designErrorKey`), và tự ẩn khi store xoá lỗi sau lần ghi thành công.
 */
import { useT } from '../../../i18n/context'
import { designErrorKey } from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'

export function DesignErrorNotice() {
  const t = useT()
  const error = useDesignStore((s) => s.error)
  if (!error) return null
  const key = designErrorKey(error.code)
  return (
    <p
      data-testid="design-error"
      data-code={error.code || 'unknown'}
      role="alert"
      className="rounded border border-rose-500/40 bg-rose-500/5 px-2 py-1 text-[11px] text-rose-300"
    >
      {key ? t(key) : error.message}
    </p>
  )
}
