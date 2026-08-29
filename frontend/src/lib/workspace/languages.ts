/**
 * Nhận diện ngôn ngữ + loại xem trước theo phần mở rộng — thuần, không DOM.
 */
import type { WorkspaceEntry } from './types'

/** Loại xem trước dùng để chọn nhánh render trong PreviewStudio. */
export type PreviewKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'code'
  | 'text'
  | 'pdf'
  | 'markdown'
  | 'unknown'

const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'])
const VIDEO_EXTS = new Set(['mp4', 'webm', 'mov', 'mkv'])
const AUDIO_EXTS = new Set(['mp3', 'wav', 'ogg', 'm4a', 'opus'])
/** Đuôi không phải code nhưng vẫn là văn bản thuần — xem trước dạng text. */
const TEXT_FALLBACK_EXTS = new Set(['env', 'txt', 'gitignore', 'log', 'ini', 'cfg', 'conf', 'properties'])

/** Bản đồ đuôi → ngôn ngữ (cho tô màu tokenizer). */
const EXT_LANGUAGE: Record<string, string> = {
  ts: 'typescript',
  tsx: 'typescript',
  mts: 'typescript',
  cts: 'typescript',
  js: 'javascript',
  jsx: 'javascript',
  mjs: 'javascript',
  cjs: 'javascript',
  py: 'python',
  pyi: 'python',
  json: 'json',
  jsonc: 'json',
  css: 'css',
  scss: 'css',
  less: 'css',
  md: 'markdown',
  mdx: 'markdown',
  html: 'html',
  htm: 'html',
  yml: 'yaml',
  yaml: 'yaml',
  sh: 'bash',
  bash: 'bash',
  zsh: 'bash',
  go: 'go',
  rs: 'rust',
  java: 'java',
  kt: 'kotlin',
  c: 'c',
  h: 'c',
  cpp: 'cpp',
  hpp: 'cpp',
  cc: 'cpp',
  rb: 'ruby',
  php: 'php',
  sql: 'sql',
  toml: 'toml',
  xml: 'xml',
  svg: 'xml',
  vue: 'vue',
  svelte: 'svelte',
}

/** Rút phần mở rộng (viết thường, không dấu chấm). Dotfile như `.env` → `'env'`. */
export function extOf(name: string): string | null {
  const dot = name.lastIndexOf('.')
  if (dot < 0) return null
  const ext = name.slice(dot + 1).toLowerCase()
  return ext || null
}

/** Ngôn ngữ cho một đuôi, hoặc `null` khi không nhận diện. */
export function languageForExt(ext: string | null): string | null {
  if (!ext) return null
  return EXT_LANGUAGE[ext.toLowerCase()] ?? null
}

/**
 * Loại xem trước cho một entry. File không có đuôi nhưng nội dung là text sẽ
 * được hạ xuống `text` ở chỗ gọi (khi `readText` trả `binary=false`).
 */
export function previewKindFor(entry: Pick<WorkspaceEntry, 'ext' | 'language'>): PreviewKind {
  const ext = entry.ext?.toLowerCase() ?? null
  if (ext && IMAGE_EXTS.has(ext)) return 'image'
  if (ext && VIDEO_EXTS.has(ext)) return 'video'
  if (ext && AUDIO_EXTS.has(ext)) return 'audio'
  if (ext === 'pdf') return 'pdf'
  if (ext === 'md' || ext === 'mdx') return 'markdown'
  if (entry.language) return 'code'
  if (ext && TEXT_FALLBACK_EXTS.has(ext)) return 'text'
  return 'unknown'
}
