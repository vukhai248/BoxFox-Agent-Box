/**
 * Nút đổi dark / light. Nhận trạng thái từ ngoài để cả ứng dụng chỉ có MỘT
 * `useTheme()` — hai chỗ cùng gọi hook sẽ sinh hai state đánh nhau.
 */
import { Moon, Sun } from 'lucide-react'
import { useT } from '../../i18n/context'
import { IconButton } from '../ui'
import type { Theme } from '../../hooks/useTheme'

export function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const t = useT()
  const label = theme === 'dark' ? t('common.toLightMode') : t('common.toDarkMode')
  return (
    <IconButton label={label} onClick={onToggle}>
      {theme === 'dark' ? <Sun className="size-4" /> : <Moon className="size-4" />}
    </IconButton>
  )
}
