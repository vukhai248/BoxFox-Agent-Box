// W12.MODEL.METADATA — nguồn metadata BỔ SUNG cho các provider không công bố đủ trường.
//
// Vì sao cần file này: `/models` của OpenCode Zen chỉ trả `{id, object, created,
// owned_by}` (đo live 2026-10-02, 46 model) — không có tên hiển thị, không có
// reasoning, context hay giá. Nếu adapter chỉ dựng `modelRecord(id, id)` thì mọi
// model ngoài bảng curated đều thành `thinkingType: 'none'`, và UI không có gì
// để hiện dù provider thật sự có điều khiển reasoning.
//
// Nguyên tắc (W12 §38.2, §38.5):
//  * Đây là nguồn **bổ sung**, KHÔNG phải dữ liệu live: mỗi mục mang `source`
//    (`probe` = đo bằng request thật, `documented` = tài liệu chính thức) và
//    `asOf`; adapter ghi provenance theo từng trường, không gắn cả hàng là live.
//  * Không đoán từ tên model: một mục chỉ vào bảng khi có bằng chứng đo/tài liệu,
//    và mẫu khớp là họ model có cùng cơ chế điều khiển.
//  * Khớp theo MẪU ID, không theo danh sách ID cứng: model mới cùng họ tự nhận
//    metadata; model lạ vẫn giữ `unknown` chứ không bị đoán.
//  * Trường không có nguồn giữ `unknown`; không biến "chưa biết" thành
//    "không hỗ trợ" và không biến default nội bộ thành trần provider.

import { EFFORT_LEVELS } from './common.mjs';

/**
 * Bằng chứng đo cho họ Space Bunny (2026-10-02, BoxFox router cục bộ):
 *  * không gửi điều khiển → `reasoning_content` rỗng, 3 completion token;
 *  * `reasoning.effort` = minimal/low/medium/high → 200, có `reasoning_content`,
 *    usage có `completion_tokens_details.reasoning_tokens` (13–29 token ở prompt
 *    một câu);
 *  * provider KHÔNG công bố bảng level→budget và không từ chối giá trị lạ, nên
 *    "mức đã xác minh" ở đây nghĩa là: provider nhận và sinh reasoning thật.
 * Bằng chứng thô: `/var/tmp/w12-space-bunny-probe.json`, `/var/tmp/w12-level-probe.json`.
 */
const OPENCODE_PROBE_AS_OF = '2026-10-02';

export const OPENCODE_CAPABILITY_REGISTRY = Object.freeze([
  Object.freeze({
    // Họ `space-bunny*` (Zen free tier). Điều khiển: effort chuẩn OpenAI.
    pattern: /^space-bunny(?:[-.]|$)/i,
    thinkingType: 'effort',
    thinkingLevels: EFFORT_LEVELS,
    defaultThinking: null,
    source: 'probe',
    asOf: OPENCODE_PROBE_AS_OF,
    evidence: 'router probe 2026-10-02: /zen/v1/responses nhận reasoning.effort và trả reasoning_tokens',
  }),
  Object.freeze({
    // Họ `muse-spark*`: đã có trong bảng curated (EFFORT_LEVELS); mục này giữ
    // cùng nguồn cho các biến thể mới của họ mà bảng curated chưa liệt kê.
    // Vòng soát 2 (F3): bằng chứng chỉ là HỢP ĐỒNG (provider nhận tham số), chưa đo
    // `reasoning_tokens` trả về cho họ này — biến thể tương lai có thể nhận `effort`
    // mà không sinh reasoning. Vì vậy mức ở đây là "đã gửi được", không phải "đã chạy".
    pattern: /^muse-spark(?:[-.]|$)/i,
    thinkingType: 'effort',
    thinkingLevels: EFFORT_LEVELS,
    defaultThinking: null,
    source: 'documented',
    asOf: OPENCODE_PROBE_AS_OF,
    evidence: 'chỉ xác nhận hợp đồng: /responses nhận reasoning: {effort, summary} (fixture 2026-09-21, tests/opencode.test.mjs); chưa đo reasoning_tokens trả về cho họ này',
  }),
]);

/** Mục registry khớp một model id, hoặc `null` khi không họ nào khớp (giữ unknown). */
export function opencodeCapabilityFor(modelId) {
  const id = typeof modelId === 'string' ? modelId.trim() : '';
  if (!id) return null;
  return OPENCODE_CAPABILITY_REGISTRY.find(entry => entry.pattern.test(id)) || null;
}

/**
 * Hạn dùng của một mốc bằng chứng thinking. Registry ghim `asOf` và bằng chứng dò
 * cũng ghim `asOf`; cả hai đều là ẢNH CHỤP tại một thời điểm, không phải sự thật
 * vĩnh viễn. Sau hạn, hàng vẫn giữ level (người dùng không mất điều khiển đang
 * chạy) nhưng bị gắn `thinkingStale` để UI mời dò lại — nếu không, một mục registry
 * viết một lần sẽ được tin mãi mãi và lặp lại đúng lỗi người dùng báo.
 */
export const THINKING_EVIDENCE_MAX_AGE_DAYS = 30;

/** `asOf` (`YYYY-MM-DD` hoặc mốc ISO) đã quá `THINKING_EVIDENCE_MAX_AGE_DAYS` so với `now`. */
export function thinkingEvidenceStale(asOf, now = new Date()) {
  const at = typeof asOf === 'string' && asOf.trim() ? Date.parse(/^\d{4}-\d{2}-\d{2}$/.test(asOf.trim()) ? `${asOf.trim()}T00:00:00Z` : asOf) : NaN;
  if (!Number.isFinite(at)) return true;
  const current = now instanceof Date ? now.getTime() : Date.parse(now);
  if (!Number.isFinite(current)) return true;
  return current - at > THINKING_EVIDENCE_MAX_AGE_DAYS * 24 * 60 * 60 * 1000;
}
