/**
 * Sinh id ngắn, đủ duy nhất trong một phiên (counter cục bộ + timestamp).
 * Id nào cần ỔN ĐỊNH (seed/fixture, để connector và bài kiểm tham chiếu được)
 * thì do người viết tự đặt, không dùng hàm này.
 */
let counter = 0

export function newId(prefix: 'node' | 'conn' | 'stroke'): string {
  counter += 1
  return `${prefix}-${Date.now().toString(36)}-${counter.toString(36)}`
}
