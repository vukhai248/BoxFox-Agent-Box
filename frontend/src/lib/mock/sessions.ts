/**
 * Mock sessions list for left sidebar.
 */
import type { SessionSummary } from '../../types/session'

export const ACTIVE_SESSION_ID = 's-01'

export const MOCK_SESSIONS: SessionSummary[] = [
  {
    session_id: ACTIVE_SESSION_ID,
    initials: 'NS',
    title: 'New Session',
    relative_time: 'Just now',
    status: 'dang_chay',
    mode: 'PLAN',
    active_lease_count: 0,
  },
]

export const MOCK_ACCOUNT = {
  displayName: 'Khai Vu (Me)',
  // Để trống: email thật do người dùng nhập ở Settings → Notifications. Sidebar
  // hiện "undefined user" khi chưa nhập (xem `userEmail` trong `uiStore`).
  email: '',
  initials: 'KV',
  workspace: 'agent-box / local machine',
}
