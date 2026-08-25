/**
 * Lõi i18n: context, kiểu khoá, và hook `useT`.
 *
 * Tách khỏi `index.tsx` (chỗ chứa component provider) để mỗi file chỉ export
 * một loại thứ — quy tắc của `eslint-plugin-react-refresh`.
 *
 * Khoá là chuỗi dạng đường dẫn, ví dụ `'labelsLeases.leaseTable.status'`.
 * Kiểu `TKey` được sinh từ shape của `vi.ts`, nên gõ sai khoá là LỖI BIÊN DỊCH,
 * không phải chuỗi rỗng lúc chạy.
 */
import { createContext, useContext } from 'react'
import vi from './vi'

export type Lang = 'vi' | 'en'

/** Sinh mọi đường dẫn tới lá (giá trị chuỗi) của một object lồng nhau. */
type Leaves<T, P extends string = ''> = {
  [K in keyof T & string]: T[K] extends string
    ? P extends ''
      ? K
      : `${P}.${K}`
    : Leaves<T[K], P extends '' ? K : `${P}.${K}`>
}[keyof T & string]

export type TKey = Leaves<typeof vi>

export type TVars = Record<string, string | number>

export interface I18nValue {
  lang: Lang
  setLang: (lang: Lang) => void
  t: (key: TKey, vars?: TVars) => string
}

export const I18nContext = createContext<I18nValue | null>(null)

export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) throw new Error('useI18n phải nằm trong <I18nProvider>')
  return value
}

/** Đường ngắn cho trường hợp phổ biến nhất: chỉ cần hàm dịch. */
export function useT(): (key: TKey, vars?: TVars) => string {
  return useI18n().t
}

/** Đi theo đường dẫn khoá trong một object lồng nhau. */
export function lookup(dict: unknown, key: string): string | undefined {
  let node: unknown = dict
  for (const part of key.split('.')) {
    if (typeof node !== 'object' || node === null) return undefined
    node = (node as Record<string, unknown>)[part]
  }
  return typeof node === 'string' ? node : undefined
}

/** Thay `{{ten}}` bằng giá trị tương ứng. Không có biến nào thì giữ nguyên. */
export function interpolate(template: string, vars?: TVars): string {
  if (!vars) return template
  return template.replace(/\{\{(\w+)\}\}/g, (whole, name: string) => {
    const value = vars[name]
    return value === undefined ? whole : String(value)
  })
}
