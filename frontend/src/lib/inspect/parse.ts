/**
 * Validator phản hồi của `POST /__box/inspect-element` — KHÔNG TIN dữ liệu
 * mạng. `parseInspectElementResult` chạy TRƯỚC khi bất kỳ trường nào của
 * phản hồi tới được React; hình dạng sai ở bất kỳ đâu không làm rớt cả
 * payload, chỉ làm rớt đúng trường đó về một giá trị mặc định an toàn
 * (§5 `v1-element-selector.md`, bảng "Bước 3" của `frontend-detail.md`).
 *
 * ⚠️ QUY TẮC M1 — BẮT `integrity`, KHÔNG đọc từ dữ liệu: nội dung phần tử là
 * màn hình máy nên LUÔN `khong_tin_duoc`, kể cả khi box trả giá trị khác (một
 * bug box hay một MITM không thể tự "nâng hạng" mình lên tin được). Đây là
 * đúng luật panel này đã áp cho khung hình (`SandboxScreenPanel.tsx:96-98,
 * 115-116`).
 */
import type {
  DesktopInspectResult,
  DomInspectResult,
  InspectBox,
  InspectDesktopReason,
  InspectElementResult,
  InspectLabel,
  InspectNote,
  InspectTarget,
} from '../../types/inspect'
import { CONFIDENTIALITY_ORDER } from '../../types/labels'
import type { SourceKind } from '../../types/labels'
import { INSPECTED_ELEMENT_CONFIDENTIALITY, INSPECTED_ELEMENT_TOOL } from './chunk'

/** Mười một mã `reason` hợp lệ ở nhánh desktop — bảng chuẩn §5.2. */
const KNOWN_DESKTOP_REASONS: readonly InspectDesktopReason[] = [
  'not_chromium',
  'outside_viewport',
  'frame_extents_unknown',
  'devtools_docked',
  'viewport_origin_unknown',
  'no_cdp_target',
  'ambiguous_target',
  'cdp_unreachable',
  'cdp_timeout',
  'no_node_at_point',
  'extract_failed',
]

/** Năm mã `notes` hợp lệ (§5.6, cột C3). */
const KNOWN_NOTES: readonly InspectNote[] = [
  'shadow_dom',
  'iframe_boundary',
  'selector_not_unique',
  'shadow_closed',
  'truncated_ancestors',
]

/** Danh sách đầy đủ `SourceKind` — cần bản runtime vì `types/labels.ts` chỉ khai `type`. */
const KNOWN_SOURCE_KINDS: readonly SourceKind[] = [
  'user_input',
  'user_pasted',
  'agent_config',
  'workspace_file',
  'web_content',
  'external_file',
  'external_tool',
  'screen_capture',
  'command_output',
  'plan_artifact',
]

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asNumber(value: unknown, fallback: number): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

function asOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function asOptionalNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function parseBox(raw: unknown): InspectBox {
  const obj = isRecord(raw) ? raw : {}
  return {
    x: asNumber(obj.x, 0),
    y: asNumber(obj.y, 0),
    width: asNumber(obj.width, 0),
    height: asNumber(obj.height, 0),
  }
}

function parseAttributes(raw: unknown): Record<string, string> {
  if (!isRecord(raw)) return {}
  const out: Record<string, string> = {}
  for (const [key, value] of Object.entries(raw)) {
    if (typeof value === 'string') out[key] = value
  }
  return out
}

function parseTarget(raw: unknown): InspectTarget {
  const obj = isRecord(raw) ? raw : {}
  return {
    windowId: asOptionalString(obj.windowId) ?? '',
    windowTitle: asOptionalString(obj.windowTitle) ?? '',
    targetId: asOptionalString(obj.targetId) ?? '',
  }
}

function parseNotes(raw: unknown): InspectNote[] | undefined {
  if (!Array.isArray(raw)) return undefined
  return raw.filter((item): item is InspectNote => KNOWN_NOTES.includes(item as InspectNote))
}

function parseShadowHostSelector(raw: unknown): string | null | undefined {
  if (raw === null) return null
  if (typeof raw === 'string') return raw
  return undefined
}

function parseReason(raw: unknown): InspectDesktopReason | undefined {
  return KNOWN_DESKTOP_REASONS.includes(raw as InspectDesktopReason) ? (raw as InspectDesktopReason) : undefined
}

function parsePoint(raw: unknown): { x: number; y: number } {
  const obj = isRecord(raw) ? raw : {}
  return { x: asNumber(obj.x, 0), y: asNumber(obj.y, 0) }
}

function parseSize(raw: unknown): { width: number; height: number } {
  const obj = isRecord(raw) ? raw : {}
  return { width: asNumber(obj.width, 0), height: asNumber(obj.height, 0) }
}

function parseLabel(raw: unknown): InspectLabel {
  const obj = isRecord(raw) ? raw : {}
  const sourceKind = KNOWN_SOURCE_KINDS.includes(obj.source_kind as SourceKind)
    ? (obj.source_kind as SourceKind)
    : 'screen_capture'
  const confidentiality = CONFIDENTIALITY_ORDER.includes(obj.confidentiality as (typeof CONFIDENTIALITY_ORDER)[number])
    ? (obj.confidentiality as InspectLabel['confidentiality'])
    : INSPECTED_ELEMENT_CONFIDENTIALITY
  const toolName = asOptionalString(obj.tool_name)

  return {
    // Bắt cứng — quy tắc M1, xem chú thích đầu file. Bất kể `obj.integrity`.
    integrity: 'khong_tin_duoc',
    confidentiality,
    source_kind: sourceKind,
    source_uri: asOptionalString(obj.source_uri) ?? '',
    tool_name: toolName && toolName.trim() !== '' ? toolName : INSPECTED_ELEMENT_TOOL,
    content_hash: asOptionalString(obj.content_hash) ?? '',
  }
}

function parseDom(raw: Record<string, unknown>): DomInspectResult | null {
  const selector = raw.selector
  const url = raw.url
  const title = raw.title
  const tagName = raw.tagName
  const text = raw.text
  const html = raw.html
  if (
    typeof selector !== 'string' ||
    typeof url !== 'string' ||
    typeof title !== 'string' ||
    typeof tagName !== 'string' ||
    typeof text !== 'string' ||
    typeof html !== 'string'
  ) {
    return null
  }

  return {
    type: 'dom',
    selector,
    url,
    title,
    tagName,
    text,
    html,
    truncated: typeof raw.truncated === 'boolean' ? raw.truncated : false,
    attributes: parseAttributes(raw.attributes),
    cssBox: parseBox(raw.cssBox),
    screenBox: parseBox(raw.screenBox),
    notes: parseNotes(raw.notes),
    shadowHostSelector: parseShadowHostSelector(raw.shadowHostSelector),
    target: parseTarget(raw.target),
    label: parseLabel(raw.label),
  }
}

function parseDesktop(raw: Record<string, unknown>): DesktopInspectResult | null {
  const windowTitle = raw.windowTitle
  const windowId = raw.windowId
  if (typeof windowTitle !== 'string' || typeof windowId !== 'string') return null

  return {
    type: 'desktop',
    reason: parseReason(raw.reason),
    message: asOptionalString(raw.message),
    appName: asOptionalString(raw.appName),
    windowClass: asOptionalString(raw.windowClass),
    windowTitle,
    windowId,
    position: parsePoint(raw.position),
    size: parseSize(raw.size),
    pid: asOptionalNumber(raw.pid),
    label: parseLabel(raw.label),
  }
}

/** Validate phản hồi 200 của `/__box/inspect-element`. Hình dạng sai ⇒ `null`. */
export function parseInspectElementResult(payload: unknown): InspectElementResult | null {
  if (!isRecord(payload)) return null
  if (payload.type === 'dom') return parseDom(payload)
  if (payload.type === 'desktop') return parseDesktop(payload)
  return null
}

/** Rút `{"error": "..."}` từ một body lỗi. Không đúng dạng ⇒ `null`. */
export function parseInspectErrorBody(payload: unknown): string | null {
  if (!isRecord(payload)) return null
  return typeof payload.error === 'string' ? payload.error : null
}
