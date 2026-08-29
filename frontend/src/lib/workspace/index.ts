/**
 * Giao diện công khai của gói workspace: kiểu, adapter, factory chọn nguồn.
 *
 * Sandbox là mặc định; mock chỉ bật tường minh qua `VITE_WORKSPACE_SOURCE=mock`
 * (test/demo) — giống `createPlanRepository`.
 */
import { resolveBoxApiKey, resolveBoxApiUrl } from '../boxApi'
import { SandboxWorkspaceRepository } from './http'
import { MockWorkspaceRepository } from './mock'
import type { WorkspaceRepository } from './types'

export * from './types'
export { WorkspaceRepositoryHttpError } from './http'

export type { PreviewKind } from './languages'
export { extOf, languageForExt, previewKindFor } from './languages'

export type { LineTokens, Token, TokenKind } from './tokenizer'
export { byLine, tokenize } from './tokenizer'

export * from './tree'

export type WorkspaceSource = 'sandbox' | 'mock'

/** Sandbox mặc định; `VITE_WORKSPACE_SOURCE=mock` → mock. */
export function createWorkspaceRepository(env: ImportMetaEnv = import.meta.env): WorkspaceRepository {
  const source = env.VITE_WORKSPACE_SOURCE?.trim().toLowerCase()
  if (source === 'mock') return new MockWorkspaceRepository()
  return new SandboxWorkspaceRepository(resolveBoxApiUrl(env), resolveBoxApiKey(env))
}
