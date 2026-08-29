/**
 * Mock sessions list for left sidebar.
 */
import type { SessionSummary } from '../../types/session'

export const ACTIVE_SESSION_ID = 's-04'

/**
 * Các nhãn người được gán dùng trong submenu "Assign" của dòng phiên.
 * `Me (Khai Vu)` khớp với giá trị `assigned_to` mặc định ở mock.
 */
export const ASSIGNEES = ['Me (Khai Vu)', 'Teammate', 'Unassigned'] as const

/**
 * Danh sách phiên mock cho thanh bên trái. Đa dạng trạng thái để demo:
 * cho_nguoi_dung (BLOCKED), idle (IDLE), dang_chay (chip PLAN), có ghim, có nhóm.
 */
export const MOCK_SESSIONS: SessionSummary[] = [
  {
    session_id: 's-01',
    initials: 'KV',
    title: 'Setup docker repo',
    relative_time: '22m ago',
    status: 'cho_nguoi_dung',
    mode: 'PLAN',
    active_lease_count: 4,
    step_count: 5,
    is_pinned: true,
    assigned_to: 'Me (Khai Vu)',
  },
  {
    session_id: 's-02',
    initials: 'KV',
    title: 'Run Agentic RAG project',
    relative_time: '2d ago',
    status: 'idle',
    mode: 'PLAN',
    active_lease_count: 0,
    group_name: 'AI Projects',
    assigned_to: 'Me (Khai Vu)',
  },
  {
    session_id: 's-03',
    initials: 'KV',
    title: 'Machine Setup',
    relative_time: '2d ago',
    status: 'idle',
    mode: 'PLAN',
    active_lease_count: 0,
    group_name: 'Infrastructure',
    assigned_to: 'Teammate',
  },
  {
    session_id: ACTIVE_SESSION_ID,
    initials: 'NS',
    title: 'New Session',
    relative_time: 'Just now',
    status: 'dang_chay',
    mode: 'PLAN',
    active_lease_count: 0,
    assigned_to: 'Unassigned',
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
