/** Request deadlines are separate from a whole agent turn and HTTP body receipt. */
export const LARGE_OUTPUT_TOKENS = 8000;
export function largeRequestDeadline(value = process.env.BOXFOX_ROUTER_LARGE_REQUEST_MS) {
  const applied = value === undefined ? 180000 : Number(value);
  if (![90000, 180000, 240000].includes(applied)) {
    throw new Error('BOXFOX_ROUTER_LARGE_REQUEST_MS must be 90000, 180000 or 240000');
  }
  return applied;
}
