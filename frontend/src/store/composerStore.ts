/**
 * Trạng thái NHÁP của khung soạn tin: những phần tử người dùng đã đính kèm từ
 * khung ④ (Element Selector) nhưng chưa gửi.
 *
 * Vì sao là store RIÊNG, không nằm trong `uiStore` hoặc `agentStore`:
 *   - `uiStore.ts:1-4` tự khai chỉ giữ trạng thái THUẦN GIAO DIỆN (thanh bên,
 *     tab, tỉ lệ cột…). `pendingElements` là DỮ LIỆU đang chờ đi lên backend —
 *     nhét vào đó là làm chú thích kia thành lời nói dối.
 *   - `agentStore` chỉ được biết `ServerEvent` / `ClientCommand` (luật ở đầu
 *     file đó). Chip là trạng thái NHÁP trước khi có `ClientCommand` —
 *     `agentStore` chưa từng nghe tới nó.
 *
 * `input` (văn bản người dùng đang gõ) KHÔNG ở đây — nó vẫn là state cục bộ
 * của `ChatInputBar` (quyết định D3, `v1-element-selector.md` §4.2).
 */
import { create } from 'zustand'
import type { InspectedElementContext } from '../types/inspect'

export interface ComposerState {
  pendingElements: InspectedElementContext[]
  /** Nối vào CUỐI danh sách — thứ tự bấm = thứ tự chip. */
  addPendingElement: (element: InspectedElementContext) => void
  removePendingElement: (id: string) => void
  clearPendingElements: () => void
}

export const useComposerStore = create<ComposerState>((set) => ({
  pendingElements: [],

  // KHÔNG chống trùng: bấm hai lần vào cùng một phần tử là ý muốn của người
  // dùng (ví dụ để hỏi lại), và mỗi lần có `id` riêng nên vẫn xoá tách được.
  addPendingElement: (element) =>
    set((state) => ({ pendingElements: [...state.pendingElements, element] })),

  removePendingElement: (id) =>
    set((state) => ({ pendingElements: state.pendingElements.filter((item) => item.id !== id) })),

  clearPendingElements: () => set({ pendingElements: [] }),
}))
