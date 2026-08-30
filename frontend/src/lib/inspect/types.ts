/**
 * Hợp đồng hành vi của nguồn dữ liệu thanh tra phần tử (khung ④).
 *
 * Đây là kiểu MÔ TẢ HÀNH VI (interface repository), khác với `types/inspect.ts`
 * là hợp đồng DỮ LIỆU hai phía — cùng quy ước với `lib/plans/` và
 * `lib/workspace/` (§5.5 `v1-element-selector.md`).
 */
import type { InspectElementRequest, InspectElementResult } from '../../types/inspect'

/** Phân loại lỗi để giao diện chọn đúng khoá i18n, không phô chuỗi thô của box. */
export type InspectErrorKind =
  | 'timeout' // hết 8 giây
  | 'forbidden' // 403 — secret sai / Origin sai
  | 'notFound' // 404 — box chưa có endpoint này
  | 'server' // 5xx
  | 'badResponse' // 200 nhưng hình dạng sai
  | 'network' // fetch tự ném (mất mạng, DNS, v.v.)

export class InspectHttpError extends Error {
  constructor(
    readonly kind: InspectErrorKind,
    readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'InspectHttpError'
  }
}

export interface InspectRepository {
  inspect(point: InspectElementRequest, signal?: AbortSignal): Promise<InspectElementResult>
}
