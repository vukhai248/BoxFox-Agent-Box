/**
 * Hợp đồng dữ liệu thuần cho trình duyệt file workspace.
 *
 * `path` luôn là đường dẫn TƯƠNG ĐỐI từ gốc workspace (`/home/agent/workspace`);
 * chuỗi rỗng nghĩa là thư mục gốc. Backend quyết định nhãn provenance — giao diện
 * chỉ hiển thị, không tự gán.
 */
import type { Confidentiality, Integrity } from '../../types/labels'
import type { FileNodeKind } from '../../types/ui'

/** Một mục trong danh sách thư mục (file hoặc thư mục con). */
export interface WorkspaceEntry {
  name: string
  kind: FileNodeKind
  sizeBytes: number
  /** ISO 8601 — thời gian sửa cuối. */
  mtime: string
  /** Nhãn provenance do backend cấp; `null` khi chưa biết (thư mục thường không mang nhãn). */
  integrity: Integrity | null
  confidentiality: Confidentiality | null
  /** Phần mở rộng (đã viết thường, không dấu chấm) hoặc `null` với file không có đuôi. */
  ext: string | null
  /** Ngôn ngữ nhận diện cho tô màu, hoặc `null`. */
  language: string | null
}

/** Một đoạn trong breadcrumb điều hướng. */
export interface WorkspaceCrumb {
  name: string
  path: string
}

/** Kết quả liệt kê MỘT thư mục. */
export interface WorkspaceListing {
  breadcrumb: WorkspaceCrumb[]
  entries: WorkspaceEntry[]
  /** `true` khi backend đã cắt bớt vì vượt giới hạn số mục. */
  truncated?: boolean
}

/** Nội dung văn bản của một file (chỉ cho file có thể giải mã text). */
export interface WorkspaceContent {
  content: string
  sizeBytes: number
  mime: string
  language: string | null
  /** `true` khi file là nhị phân — không giải mã text được. */
  binary: boolean
}

/**
 * Adapter đọc/ghi file workspace. Phương thức `*Url` trả URL cho subresource
 * (`<img>`, `<video>`, `<a download>`) — KHÔNG thêm header Origin/auth vì trình
 * duyệt không gửi Origin cho subresource; biên thật là bind loopback của proxy.
 */
export interface WorkspaceRepository {
  baseUrl: string
  list(path: string, signal?: AbortSignal): Promise<WorkspaceListing>
  readText(path: string, signal?: AbortSignal): Promise<WorkspaceContent>
  mediaUrl(path: string): string
  thumbnailUrl(path: string): string
  downloadUrl(path: string): string
  zip(paths: string[], signal?: AbortSignal): Promise<Blob>
  upload(
    targetDir: string,
    filename: string,
    body: Blob,
    signal?: AbortSignal,
  ): Promise<{ path: string; sizeBytes: number }>
  unzip(
    path: string,
    signal?: AbortSignal,
  ): Promise<{ extracted: number; skipped: number; warnings: string[] }>
}
