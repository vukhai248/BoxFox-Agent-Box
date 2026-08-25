/**
 * Bảng màu nhãn thống nhất (đầu bài) + hai hàm suy ra integrity_floor /
 * confidentiality_ceiling (mục 9.3). Đừng chỉ dùng màu — mỗi mục có nhãn
 * chữ tiếng Việt để người mù màu / ảnh chụp đen trắng vẫn đọc được.
 */
import { CONFIDENTIALITY_ORDER, INTEGRITY_ORDER, type Confidentiality, type Integrity } from '../types/labels'

export interface AxisMeta {
  value: string
  /** Nhãn tiếng Việt hiển thị. */
  label: string
  /** Lớp Tailwind cho chấm màu. */
  dotClass: string
  /**
   * Lớp Tailwind cho chữ/badge. PHẢI có cặp sáng/tối (`text-x-700
   * dark:text-x-300`) — chỉ dùng biến thể `-300` thì ở chế độ sáng chữ chìm
   * vào nền, không đọc được. Ý nghĩa màu không đổi giữa hai chế độ.
   */
  badgeClass: string
}

export const INTEGRITY_META: Record<Integrity, AxisMeta> = {
  duoc_nguoi_dung_cho_phep: {
    value: 'duoc_nguoi_dung_cho_phep',
    label: 'Được người dùng cho phép',
    dotClass: 'bg-emerald-500',
    badgeClass: 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500/40',
  },
  khong_tin_duoc: {
    value: 'khong_tin_duoc',
    label: 'Không tin được',
    dotClass: 'bg-amber-500',
    badgeClass: 'bg-amber-500/15 text-amber-700 dark:text-amber-300 ring-1 ring-amber-500/40',
  },
}

export const CONFIDENTIALITY_META: Record<Confidentiality, AxisMeta> = {
  cong_khai: {
    value: 'cong_khai',
    label: 'Công khai',
    dotClass: 'bg-slate-400',
    badgeClass: 'bg-slate-500/15 text-slate-700 dark:text-slate-300 ring-1 ring-slate-500/40',
  },
  noi_bo: {
    value: 'noi_bo',
    label: 'Nội bộ',
    dotClass: 'bg-blue-500',
    badgeClass: 'bg-blue-500/15 text-blue-700 dark:text-blue-300 ring-1 ring-blue-500/40',
  },
  bi_mat: {
    value: 'bi_mat',
    label: 'Bí mật',
    dotClass: 'bg-red-500',
    badgeClass: 'bg-red-500/15 text-red-700 dark:text-red-300 ring-1 ring-red-500/40',
  },
}

/**
 * integrity_floor = min(integrity của mọi artifact trong ngữ cảnh).
 * KHÔNG_TIN_ĐƯỢC < ĐƯỢC_CHO_PHÉP → một artifact bẩn làm cả ngữ cảnh bẩn.
 * Ngữ cảnh rỗng coi là sạch (mặc định của một phiên mới).
 */
export function computeIntegrityFloor(items: readonly { integrity: Integrity }[]): Integrity {
  let floorIndex = INTEGRITY_ORDER.length - 1
  for (const item of items) {
    const idx = INTEGRITY_ORDER.indexOf(item.integrity)
    if (idx < floorIndex) floorIndex = idx
  }
  return INTEGRITY_ORDER[floorIndex]
}

/**
 * confidentiality_ceiling = max(confidentiality của mọi artifact).
 * CÔNG_KHAI < NỘI_BỘ < BÍ_MẬT → một artifact bí mật làm cả ngữ cảnh bí mật.
 * Ngữ cảnh rỗng coi là công khai (mặc định của một phiên mới).
 */
export function computeConfidentialityCeiling(
  items: readonly { confidentiality: Confidentiality }[],
): Confidentiality {
  let ceilingIndex = 0
  for (const item of items) {
    const idx = CONFIDENTIALITY_ORDER.indexOf(item.confidentiality)
    if (idx > ceilingIndex) ceilingIndex = idx
  }
  return CONFIDENTIALITY_ORDER[ceilingIndex]
}
