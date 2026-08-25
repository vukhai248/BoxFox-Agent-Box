/**
 * Kiểu dữ liệu thuần giao diện — không cần khớp schema backend, nhưng vẫn
 * tái dùng ba trục nhãn để mỗi mảnh nội dung có chấm màu đúng (mục 12.6).
 */
import type { Confidentiality, Integrity } from './labels'
import type { ToolName } from './lease'

export type FileNodeKind = 'file' | 'dir'

export interface FileNode {
  path: string // đường dẫn tương đối trong workspace, dùng làm id
  name: string
  kind: FileNodeKind
  children?: FileNode[]
  /** Chỉ file mới có nhãn + nội dung; thư mục không mang nhãn riêng. */
  integrity?: Integrity
  confidentiality?: Confidentiality
  source_uri?: string
  content_hash?: string
  /** Nội dung văn bản thuần — không có file nào được sửa trong giao diện (mục 12.3). */
  content?: string
}

export type TerminalLineKind = 'prompt' | 'stdout' | 'stderr' | 'exit'

export interface TerminalLine {
  kind: TerminalLineKind
  text: string
}

/**
 * File liên quan / được tham chiếu trong câu trả lời của Agent (Referenced File).
 * - `path`: Đường dẫn tương đối trong workspace (vd: `src/parser.py`) -> dùng để gọi `uiStore.selectFile(path)` và mở tab `files`.
 * - `name`: Tên hiển thị của file (vd: `parser.py`).
 * - `size_bytes`: Dung lượng file dạng bytes để hiển thị badge (vd: 1840 B).
 * - `language`: Ngôn ngữ lập trình (vd: 'python', 'typescript', 'markdown') để hiển thị icon màu nhận diện.
 * - `content`: Nội dung file dạng text (tùy chọn). Nếu có, nút [Download] sẽ xuất trực tiếp file này; nếu không, sẽ tìm từ cây workspace store.
 */
export interface ReferencedFile {
  path: string
  name: string
  size_bytes?: number
  language?: string
  content?: string
}

/**
 * Một dòng trong khung hội thoại Chat.
 * Bao gồm các loại tin nhắn tương thích cả bản Mock lẫn Backend WebSocket trực tiếp:
 * - `user_text`: Tin nhắn do người dùng nhập.
 * - `agent_text`: Phản hồi dạng văn bản thuần / markdown của Agent, hỗ trợ kèm danh sách `files` liên quan (mỗi file có nút Xem 👁 và Tải về ⬇).
 * - `agent_step`: Một bước ReAct (suy nghĩ → gọi tool → kết quả).
 * - `permission_request`: Thẻ xin cấp quyền tương tác (4 nút cho phép / từ chối).
 * - `mode_switch`: Đề xuất chuyển chế độ Plan -> Act.
 * - `system_note`: Thông báo hệ thống / cảnh báo bảo mật.
 * - `screenshot`: Ảnh chụp màn hình từ trình duyệt sandbox / test runner của Agent (hỗ trợ Lightbox zoom con lăn chuột & tải về).
 */
export type ChatMessage =
  | { id: string; kind: 'user_text'; text: string; created_at: string }
  | {
      id: string
      kind: 'agent_text'
      text: string
      files?: ReferencedFile[]
      label_id: string
      integrity: Integrity
      confidentiality: Confidentiality
      created_at: string
    }
  | {
      id: string
      kind: 'agent_step'
      thought: string
      tool_name?: ToolName
      params?: Record<string, string>
      result_preview?: string
      truncated_lines?: number
      label_id?: string
      integrity?: Integrity
      confidentiality?: Confidentiality
      created_at: string
    }
  | { id: string; kind: 'permission_request'; request_id: string; created_at: string }
  | { id: string; kind: 'mode_switch'; created_at: string }
  | { id: string; kind: 'system_note'; text: string; created_at: string }
  | {
      id: string
      kind: 'screenshot'
      image_url: string
      caption?: string
      source_url?: string
      width?: number
      height?: number
      label_id?: string
      integrity?: Integrity
      confidentiality?: Confidentiality
      created_at: string
    }
  | {
      id: string
      kind: 'screen_recording'
      video_url: string
      poster_url?: string
      caption?: string
      source_url?: string
      duration_seconds?: number
      width?: number
      height?: number
      label_id?: string
      integrity?: Integrity
      confidentiality?: Confidentiality
      created_at: string
    }
