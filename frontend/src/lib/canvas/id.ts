/**
 * Sinh id ngắn, đủ duy nhất trong một phiên (counter cục bộ + timestamp).
 * KHÔNG dùng cho id seed trong `createInitialScene` — id seed phải ổn định
 * để connector/test tham chiếu được.
 */
let counter = 0

export function newId(prefix: 'node' | 'conn' | 'stroke'): string {
  counter += 1
  return `${prefix}-${Date.now().toString(36)}-${counter.toString(36)}`
}
