/**
 * Quyết định số nút hiện trên PermissionCard (mục 12.5, bảng nút theo
 * integrity_floor). Hàm THUẦN để test được (c) trong yêu cầu chất lượng.
 */

export type PermissionButtonId =
  | 'cho_phep_mot_lan'
  | 'chuan_thuan_artifact'
  | 'cap_giay_phep'
  | 'tu_choi'

/**
 * Ngữ cảnh sạch → 3 nút. Ngữ cảnh bẩn → 4 nút, thêm
 * "Tôi đã đọc và chấp nhận nguồn này" (chuẩn thuận artifact), theo đúng
 * thứ tự bảng ở mục 12.5.
 * LUẬT TUYỆT ĐỐI: không có và không được thêm nút "luôn cho phép" —
 * không có PermissionButtonId nào diễn đạt điều đó.
 */
export function getPermissionButtons(contextDirty: boolean): PermissionButtonId[] {
  if (contextDirty) {
    return ['cho_phep_mot_lan', 'chuan_thuan_artifact', 'cap_giay_phep', 'tu_choi']
  }
  return ['cho_phep_mot_lan', 'cap_giay_phep', 'tu_choi']
}
