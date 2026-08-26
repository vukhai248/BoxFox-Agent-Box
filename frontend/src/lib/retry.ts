/**
 * Mẩu logic thử lại dùng chung cho các kênh nối tới box.
 *
 * Ở đây CHỈ đặt những gì không mang ngữ nghĩa của riêng kênh nào. Phase, lý do
 * offline và danh sách sự kiện vẫn nằm trong reducer của từng kênh
 * (`src/lib/vnc/state.ts` cho khung ④, `src/lib/ide/state.ts` cho tab IDE) — gộp
 * chúng lại sẽ kéo khái niệm RFB sang đường IDE, nơi không có RFB nào.
 *
 * Trước đây `IdePanel.tsx` phải import hàm này từ `lib/vnc/state`, khiến tab IDE
 * trông như phụ thuộc vào kênh VNC dù nó chỉ cần một phép `Math.ceil`.
 */

/** Số giây còn lại tới `retryAtMs`, không âm. */
export function retrySecondsLeft(retryAtMs: number, nowMs: number): number {
  return Math.max(0, Math.ceil((retryAtMs - nowMs) / 1000))
}
