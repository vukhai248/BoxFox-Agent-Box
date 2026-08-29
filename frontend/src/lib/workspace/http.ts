/**
 * Adapter HTTP cho endpoint file workspace của ide-proxy (`/__box/files...`).
 *
 * Ba endpoint điều khiển (`upload`, `unzip`) gửi `X-BoxFox-Api-Key` vì trình
 * duyệt không gửi Origin cho cross-origin write một cách tin cậy được; endpoint
 * đọc (`list`, `readText`, `zip`) vẫn qua `fetch` thường. Các URL media/
 * thumbnail/download KHÔNG kèm auth — chúng là subresource.
 */
import type { WorkspaceContent, WorkspaceListing, WorkspaceRepository } from './types'

export class WorkspaceRepositoryHttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'WorkspaceRepositoryHttpError'
  }
}

export class SandboxWorkspaceRepository implements WorkspaceRepository {
  constructor(
    readonly baseUrl: string,
    private readonly apiKey: string,
  ) {}

  async list(path: string, signal?: AbortSignal): Promise<WorkspaceListing> {
    return requestJson<WorkspaceListing>(`${this.baseUrl}/__box/files?path=${encodeURIComponent(path)}`, signal)
  }

  async readText(path: string, signal?: AbortSignal): Promise<WorkspaceContent> {
    return requestJson<WorkspaceContent>(
      `${this.baseUrl}/__box/file/content?path=${encodeURIComponent(path)}`,
      signal,
    )
  }

  mediaUrl(path: string): string {
    return `${this.baseUrl}/__box/file/media?path=${encodeURIComponent(path)}`
  }

  thumbnailUrl(path: string): string {
    return `${this.baseUrl}/__box/file/thumbnail?path=${encodeURIComponent(path)}`
  }

  downloadUrl(path: string): string {
    return `${this.baseUrl}/__box/file/download?path=${encodeURIComponent(path)}`
  }

  async zip(paths: string[], signal?: AbortSignal): Promise<Blob> {
    const response = await fetch(`${this.baseUrl}/__box/files/zip`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths }),
      signal,
    })
    await ensureOk(response)
    return response.blob()
  }

  async upload(
    targetDir: string,
    filename: string,
    body: Blob,
    signal?: AbortSignal,
  ): Promise<{ path: string; sizeBytes: number }> {
    const response = await fetch(
      `${this.baseUrl}/__box/file/upload?path=${encodeURIComponent(targetDir)}&name=${encodeURIComponent(filename)}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream', 'X-BoxFox-Api-Key': this.apiKey },
        body,
        signal,
      },
    )
    await ensureOk(response)
    return (await response.json()) as { path: string; sizeBytes: number }
  }

  async unzip(
    path: string,
    signal?: AbortSignal,
  ): Promise<{ extracted: number; skipped: number; warnings: string[] }> {
    const response = await fetch(`${this.baseUrl}/__box/file/unzip?path=${encodeURIComponent(path)}`, {
      method: 'POST',
      headers: { 'X-BoxFox-Api-Key': this.apiKey },
      signal,
    })
    await ensureOk(response)
    return (await response.json()) as { extracted: number; skipped: number; warnings: string[] }
  }
}

async function requestJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal })
  await ensureOk(response)
  return (await response.json()) as T
}

/** Lỗi có dạng `{"error":"..."}` — rút thông báo; không phải JSON thì giữ mặc định. */
async function ensureOk(response: Response): Promise<void> {
  if (response.ok) return
  let message = `Workspace request failed (${response.status}).`
  try {
    const payload = (await response.json()) as { error?: string }
    if (payload && typeof payload.error === 'string') message = payload.error
  } catch {
    // nội dung không phải JSON — giữ thông báo mặc định
  }
  throw new WorkspaceRepositoryHttpError(response.status, message)
}
