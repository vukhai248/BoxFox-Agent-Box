/**
 * Diff dòng-theo-dòng tự viết (thuật toán LCS đơn giản) — đề bài cấm cài
 * thư viện diff. Chỉ dùng cho nội dung ngắn (nội dung file demo), không
 * tối ưu cho file lớn.
 */
import type { DiffLine } from '../types/agent'

export function computeLineDiff(before: string, after: string): DiffLine[] {
  const a = before.split('\n')
  const b = after.split('\n')
  const n = a.length
  const m = b.length

  // Bảng LCS độ dài — dp[i][j] = độ dài LCS của a[i:] và b[j:]
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array<number>(m + 1).fill(0))
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const result: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ kind: 'giu_nguyen', text: a[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ kind: 'bot', text: a[i] })
      i++
    } else {
      result.push({ kind: 'them', text: b[j] })
      j++
    }
  }
  while (i < n) {
    result.push({ kind: 'bot', text: a[i] })
    i++
  }
  while (j < m) {
    result.push({ kind: 'them', text: b[j] })
    j++
  }
  return result
}
